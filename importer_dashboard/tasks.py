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
    conda_base = getattr(settings, 'CONDA_BASE_PATH', '/home/prometheus/miniconda3')
    job_path = os.path.join(models_root, job.name)

    # Parse the actual import.sh to get the correct command for this mechanism.
    # Each import.sh has different filenames (species, thermo, reactions, etc.)
    import_sh_path = os.path.join(job_path, 'import.sh')
    command = _build_command_from_import_sh(import_sh_path, rmg_py_path, conda_env, job_path)

    # Build the command that import.sh used to run
    # This mirrors the sbatch script from the cluster
    port = job.port or 0

    # Set up log files (same structure as the cluster)
    output_log = os.path.join(job_path, 'output.log')
    error_log = os.path.join(job_path, 'error.log')

    logger.info(f"Starting import for {job.name} at {job_path}")
    logger.info(f"Command: {command}")

    conda_bin = os.path.join(conda_base, 'envs', conda_env, 'bin')
    proc_env = {
        **os.environ,
        'PYTHONPATH': rmg_py_path,
        'RMG': rmg_py_path,
        'PATH': f'{conda_bin}:{os.environ.get("PATH", "")}',
    }

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
                env=proc_env,
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


def _build_command_from_import_sh(import_sh_path, rmg_py_path, conda_env, job_path):
    """
    Parse import.sh and build a local command from it.

    Each mechanism's import.sh has different filenames and flags. Example:

        python -m cProfile -o importChemkin.profile $RMGpy/importChemkin.py \\
            --species hfcmech_v448a.txt \\
            --reactions hfcmech_v448a.txt \\
            --thermo thermo-hfo1234zee-burcat-c.txt \\
            --known SMILES.txt \\
            --port 8179

    This function:
    1. Reads import.sh
    2. Strips SLURM headers (#SBATCH), comments, blank lines, and the
       cProfile/gprof2dot wrapper
    3. Extracts the actual importChemkin.py invocation with all its args
    4. Replaces $RMGpy with the real path
    5. Wraps it with conda activation

    Returns a shell command string ready for subprocess.
    """
    import re

    if not os.path.exists(import_sh_path):
        raise FileNotFoundError(
            f"import.sh not found at {import_sh_path}. "
            f"Cannot determine the correct command for this mechanism."
        )

    with open(import_sh_path, 'r') as f:
        raw_content = f.read()

    # Join continuation lines (backslash + newline)
    content = raw_content.replace('\\\n', ' ')

    # Find the line that runs importChemkin.py
    import_cmd = None
    for line in content.splitlines():
        stripped = line.strip()

        # Skip empty lines, shebangs, SBATCH directives, comments
        if not stripped or stripped.startswith('#'):
            continue

        # Skip gprof2dot post-processing line
        if 'gprof2dot' in stripped:
            continue

        # This is the importChemkin command (possibly wrapped in cProfile)
        if 'importChemkin' in stripped:
            import_cmd = stripped
            break

    if not import_cmd:
        raise ValueError(
            f"Could not find importChemkin.py command in {import_sh_path}. "
            f"File contents:\n{raw_content[:500]}"
        )

    # Strip cProfile wrapper: "python -m cProfile -o importChemkin.profile $RMGpy/importChemkin.py ..."
    # becomes:                 "python $RMGpy/importChemkin.py ..."
    import_cmd = re.sub(
        r'python\s+-m\s+cProfile\s+-o\s+\S+\s+',
        'python ',
        import_cmd
    )

    # Replace $RMGpy or ${RMGpy} with the actual path
    import_cmd = import_cmd.replace('$RMGpy', rmg_py_path)
    import_cmd = import_cmd.replace('${RMGpy}', rmg_py_path)
    import_cmd = import_cmd.replace('$RMG', rmg_py_path)
    import_cmd = import_cmd.replace('${RMG}', rmg_py_path)

    # Collapse multiple spaces
    import_cmd = re.sub(r'\s+', ' ', import_cmd).strip()

    import_cmd = re.sub(
        r'^python\b',
        f'/home/prometheus/miniconda3/envs/{conda_env}/bin/python',
        import_cmd
    )

    # Wrap with conda activation and cd
    command = (
        f'cd {job_path} && '
        f'{import_cmd} '
        f'2>&1'
    )

    logger.info(f"Built command from import.sh: {command}")
    return command


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
