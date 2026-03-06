"""
Local job manager that replaces SSHJobManager for office-server deployments.

Instead of SSH + SLURM, this uses Celery for task execution and reads
log files directly from the local filesystem.

API parity with SSHJobManager — every public method that views.py or
incremental_sync.py calls on SSHJobManager exists here so the manager
factory can swap them transparently.
"""
import os
import re
import signal
import json
import logging
import subprocess
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from celery.result import AsyncResult

from .models import ClusterJob, ImportJobConfig, ImportJobStatus
from .tasks import run_import_job

logger = logging.getLogger(__name__)


class LocalJobManager:
    """
    Manages import jobs running locally via Celery.
    Drop-in replacement for SSHJobManager.
    """

    def __init__(self, config: ImportJobConfig = None):
        self.config = config
        self.root_path = getattr(settings, 'RMG_MODELS_PATH',
                                 config.root_path if config else '/tmp')

    def connect(self):
        """No-op for local execution (no SSH needed)."""
        pass

    def disconnect(self):
        """No-op for local execution."""
        pass

    def is_connected(self):
        """Always True for local execution."""
        return True

    def discover_jobs(self):
        """
        Discover import jobs from local filesystem.
        Replaces SSHJobManager.discover_jobs() which used SSH ls commands.
        """
        root = Path(self.root_path)
        discovered = []

        if not root.exists():
            logger.error(f"Root path does not exist: {self.root_path}")
            return discovered

        for journal_dir in sorted(root.iterdir()):
            if not journal_dir.is_dir() or journal_dir.name.startswith('.'):
                continue
            for model_dir in sorted(journal_dir.iterdir()):
                if not model_dir.is_dir():
                    continue
                import_sh = model_dir / 'import.sh'
                if import_sh.exists():
                    job_name = f"{journal_dir.name}/{model_dir.name}"
                    discovered.append(job_name)

                    # Create ClusterJob if it doesn't exist
                    job, created = ClusterJob.objects.get_or_create(
                        name=job_name,
                        defaults={
                            'status': ImportJobStatus.IDLE,
                            'config': self.config,
                        }
                    )
                    if created:
                        # Parse port from import.sh
                        port = self._parse_port(import_sh)
                        if port:
                            job.port = port
                            job.save()
                        logger.info(f"Discovered new job: {job_name}")

        return discovered

    def _parse_port(self, import_sh_path):
        """Extract port number from import.sh file."""
        try:
            content = import_sh_path.read_text()
            # Match both LSF and SLURM formats
            for line in content.split('\n'):
                match = re.search(r'port(\d+)', line)
                if match:
                    return int(match.group(1))
                match = re.search(r'--port\s+(\d+)', line)
                if match:
                    return int(match.group(1))
        except Exception as e:
            logger.warning(f"Could not parse port from {import_sh_path}: {e}")
        return None

    def start_job(self, job: ClusterJob):
        """
        Start an import job via Celery.
        Replaces SSHJobManager.start_job() which used sbatch.
        
        Returns (task_id, host) to match the SLURM interface.
        """
        result = run_import_job.delay(job.id)
        
        job.celery_task_id = result.id
        job.status = ImportJobStatus.PENDING
        job.save()

        logger.info(f"Submitted Celery task {result.id} for job {job.name}")
        return result.id, 'localhost'

    def kill_job(self, job: ClusterJob):
        """
        Kill a running job.
        Replaces SSHJobManager.kill_job() which used scancel.
        """
        # First, revoke the Celery task
        if job.celery_task_id:
            from kms.celery import app
            app.control.revoke(job.celery_task_id, terminate=True, signal='SIGTERM')
            logger.info(f"Revoked Celery task {job.celery_task_id}")

        # Also kill the subprocess if it's running
        if job.worker_pid:
            try:
                os.killpg(os.getpgid(job.worker_pid), signal.SIGTERM)
                logger.info(f"Killed process group {job.worker_pid}")
            except (ProcessLookupError, PermissionError) as e:
                logger.warning(f"Could not kill PID {job.worker_pid}: {e}")

        job.status = ImportJobStatus.CANCELLED
        job.completed_at = timezone.now()
        job.save()

    def get_log_tail(self, job: ClusterJob, lines: int = 50):
        """
        Read RMG.log tail from local filesystem.
        Replaces SSHJobManager.get_log_tail() which used SSH.
        """
        log_path = os.path.join(self.root_path, job.name, 'RMG-Py-output', 'RMG.log')
        return self._tail_local_file(log_path, lines)

    def get_console_output(self, job: ClusterJob):
        """Read output.log from local filesystem."""
        log_path = os.path.join(self.root_path, job.name, 'output.log')
        return self._read_local_file(log_path)

    def get_error_log(self, job: ClusterJob):
        """Read error.log from local filesystem."""
        log_path = os.path.join(self.root_path, job.name, 'error.log')
        return self._read_local_file(log_path)

    def get_completion_stats(self, job: ClusterJob):
        """Read progress.json from local filesystem."""
        progress_path = os.path.join(
            self.root_path, job.name, 'RMG-Py-output', 'progress.json'
        )
        try:
            with open(progress_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"Could not read progress for {job.name}: {e}")
            return None

    def get_live_progress(self, job: ClusterJob):
        """
        Read progress.json for a running job.
        Replaces fetching from OOD URL or localhost tunnel.
        """
        return self.get_completion_stats(job)

    def refresh_statuses(self):
        """
        Update status of all jobs based on Celery task state.
        Replaces update_running_jobs_status() which parsed squeue output.
        """
        active_jobs = ClusterJob.objects.filter(
            status__in=[ImportJobStatus.RUNNING, ImportJobStatus.PENDING],
            celery_task_id__isnull=False
        )

        for job in active_jobs:
            result = AsyncResult(job.celery_task_id)

            if result.state == 'PENDING':
                job.status = ImportJobStatus.PENDING
            elif result.state == 'STARTED' or result.state == 'RETRY':
                if job.worker_pid and not self._is_pid_running(job.worker_pid):
                    job.status = ImportJobStatus.FAILED
                    job.completed_at = timezone.now()
                    logger.warning(
                        f"Marking job {job.name} as failed: worker PID {job.worker_pid} is not running"
                    )
                else:
                    job.status = ImportJobStatus.RUNNING
            elif result.state == 'SUCCESS':
                job.status = ImportJobStatus.COMPLETED
                job.completed_at = timezone.now()
            elif result.state in ('FAILURE', 'REVOKED'):
                job.status = ImportJobStatus.FAILED
                job.completed_at = timezone.now()

            job.save()

    # ------------------------------------------------------------------
    # Aliases so views.py can call the same names as SSHJobManager
    # ------------------------------------------------------------------

    def update_running_jobs_status(self):
        """Alias for refresh_statuses() — matches SSHJobManager API."""
        return self.refresh_statuses()

    def get_progress_json(self, job: ClusterJob):
        """
        Read progress.json for a job (running or completed).
        Matches SSHJobManager.get_progress_json() signature.
        """
        progress_path = os.path.join(self.root_path, job.name, 'progress.json')
        if not os.path.exists(progress_path):
            # Also try the RMG-Py-output subdirectory
            progress_path = os.path.join(
                self.root_path, job.name, 'RMG-Py-output', 'progress.json'
            )
        try:
            with open(progress_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"Could not read progress for {job.name}: {e}")
            return None

    def refresh_all_progress(self):
        """
        Refresh progress for all running jobs from local progress.json files.
        Matches SSHJobManager.refresh_all_progress() return signature.
        Returns the count of jobs updated.
        """
        running_jobs = ClusterJob.objects.filter(
            status=ImportJobStatus.RUNNING
        ).exclude(host=None)

        updated = 0
        for job in running_jobs:
            progress = self.get_progress_json(job)
            if progress:
                job.total_species = progress.get('total', 0)
                job.processed_species = progress.get('processed', 0)
                job.unprocessed_species = progress.get('unprocessed', 0)
                job.confirmed_species = progress.get('confirmed', 0)
                job.tentative_species = progress.get('tentative', 0)
                job.unidentified_species = progress.get('unidentified', 0)
                job.identified_species = (
                    progress.get('confirmed', 0) + progress.get('tentative', 0)
                )
                job.total_reactions = progress.get('totalreactions', 0)
                job.unmatched_reactions = progress.get('unmatchedreactions', 0)
                job.matched_reactions = (
                    progress.get('totalreactions', 0) -
                    progress.get('unmatchedreactions', 0)
                )
                job.thermo_matches_count = progress.get('thermomatches', 0)
                job.save()
                updated += 1
        return updated

    def exec_command(self, command: str):
        """
        Run a shell command locally.
        Matches SSHJobManager.exec_command() return signature: (stdout, stderr).
        """
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=120
            )
            return result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return '', 'Command timed out after 120 seconds'
        except Exception as e:
            return '', str(e)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_local_file(self, path, max_bytes=5_000_000):
        """Read a local file, capped at max_bytes."""
        try:
            with open(path, 'r') as f:
                return f.read(max_bytes)
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"Could not read {path}: {e}")
            return None

    def _tail_local_file(self, path, lines=50):
        """Read last N lines of a local file."""
        try:
            with open(path, 'r') as f:
                all_lines = f.readlines()
                return ''.join(all_lines[-lines:])
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"Could not tail {path}: {e}")
            return None

    def _is_pid_running(self, pid):
        """Return True if a local PID currently exists."""
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True