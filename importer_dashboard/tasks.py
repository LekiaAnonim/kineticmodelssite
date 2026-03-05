"""
Celery tasks for running RMG import jobs locally.

Replaces the SLURM submission in SSHJobManager.start_job().
The import logic mirrors what import.sh did on the cluster.
"""
import os
import subprocess
import signal
import logging
import json
from pathlib import Path
from datetime import datetime

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='importer_dashboard.run_import_job')
def run_import_job(self, job_id):
    """
    Run an RMG import job locally via Celery.
    
    This replaces:
      - SSHJobManager.start_job() (which ran sbatch on the cluster)
      - The import.sh SLURM script
    
    Args:
        job_id: ID of the ClusterJob to run
    """
    # Import here to avoid circular imports
    from importer_dashboard.models import ClusterJob, ImportJobStatus, JobLog

    try:
        job = ClusterJob.objects.get(id=job_id)
    except ClusterJob.DoesNotExist:
        logger.error(f"Job {job_id} not found")
        return {'status': 'error', 'message': f'Job {job_id} not found'}

    # Store the Celery task ID on the job (replaces slurm_job_id)
    job.celery_task_id = self.request.id
    job.status = ImportJobStatus.RUNNING
    job.host = 'localhost'
    job.started_at = timezone.now()
    job.save()

    JobLog.objects.create(
        job=job,
        log_type='info',
        message=f'Import job started via Celery (task: {self.request.id})'
    )

    # Build paths
    models_root = getattr(settings, 'RMG_MODELS_PATH', '/path/to/rmg_models')
    rmg_py_path = getattr(settings, 'RMG_PY_PATH', '/path/to/RMG-Py')
    conda_env = getattr(settings, 'CONDA_ENV_NAME', 'rmg_env')
    job_path = os.path.join(models_root, job.name)

    # Build the command that import.sh used to run
    # This mirrors the sbatch script from the cluster
    port = job.port or 0
    command = (
        f'source activate {conda_env} && '
        f'cd {job_path} && '
        f'python {rmg_py_path}/scripts/importChemkin.py '
        f'--name "{job.name}" '
        f'--port {port} '
        f'mechanism.txt '
        f'thermo.txt '
        f'2>&1'
    )

    # Set up log files (same structure as the cluster)
    output_log = os.path.join(job_path, 'output.log')
    error_log = os.path.join(job_path, 'error.log')

    logger.info(f"Starting import for {job.name} at {job_path}")
    logger.info(f"Command: {command}")

    process = None
    try:
        with open(output_log, 'w') as stdout_f, open(error_log, 'w') as stderr_f:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=stdout_f,
                stderr=stderr_f,
                cwd=job_path,
                preexec_fn=os.setsid,  # Create process group for clean kill
                env={
                    **os.environ,
                    'PYTHONPATH': rmg_py_path,
                    'RMG': rmg_py_path,
                }
            )

            # Store PID for potential cancellation
            job.worker_pid = process.pid
            job.save()

            # Wait for completion
            returncode = process.wait()

        if returncode == 0:
            job.status = ImportJobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.save()

            # Try to read final progress
            _update_completion_stats(job, job_path)

            JobLog.objects.create(
                job=job,
                log_type='info',
                message='Import job completed successfully'
            )
            logger.info(f"Job {job.name} completed successfully")
            return {'status': 'completed', 'job_id': job_id}
        else:
            job.status = ImportJobStatus.FAILED
            job.completed_at = timezone.now()
            job.save()

            # Read last few lines of error log
            error_tail = _tail_file(error_log, 20)
            JobLog.objects.create(
                job=job,
                log_type='error',
                message=f'Job failed with exit code {returncode}. Errors:\n{error_tail}'
            )
            logger.error(f"Job {job.name} failed with exit code {returncode}")
            return {'status': 'failed', 'job_id': job_id, 'returncode': returncode}

    except SoftTimeLimitExceeded:
        logger.warning(f"Job {job.name} hit time limit")
        if process:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        job.status = ImportJobStatus.FAILED
        job.completed_at = timezone.now()
        job.save()
        JobLog.objects.create(
            job=job,
            log_type='error',
            message='Job exceeded time limit and was terminated'
        )
        return {'status': 'timeout', 'job_id': job_id}

    except Exception as e:
        logger.exception(f"Job {job.name} encountered an error: {e}")
        if process and process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        job.status = ImportJobStatus.FAILED
        job.completed_at = timezone.now()
        job.save()
        JobLog.objects.create(
            job=job,
            log_type='error',
            message=f'Unexpected error: {str(e)}'
        )
        return {'status': 'error', 'job_id': job_id, 'error': str(e)}


def _update_completion_stats(job, job_path):
    """Read progress.json after completion to update job statistics."""
    progress_file = os.path.join(job_path, 'RMG-Py-output', 'progress.json')
    try:
        if os.path.exists(progress_file):
            with open(progress_file, 'r') as f:
                progress = json.load(f)
            job.total_species = progress.get('totalspecies', 0)
            job.identified_species = progress.get('identifiedspecies', 0)
            job.processed_species = progress.get('processedspecies', 0)
            job.confirmed_species = progress.get('confirmedspecies', 0)
            job.total_reactions = progress.get('totalreactions', 0)
            job.save()
    except Exception as e:
        logger.warning(f"Could not read completion stats: {e}")


def _tail_file(filepath, lines=20):
    """Read last N lines of a file."""
    try:
        with open(filepath, 'r') as f:
            return '\n'.join(f.readlines()[-lines:])
    except Exception:
        return '(could not read file)'

@shared_task(name='importer_dashboard.refresh_all_job_statuses')
def refresh_all_job_statuses():
    """Periodic task to update status of all active jobs."""
    from .local_job_manager import LocalJobManager
    from .models import ImportJobConfig
    
    config = ImportJobConfig.objects.filter(is_default=True).first()
    if config:
        manager = LocalJobManager(config=config)
        manager.refresh_statuses()