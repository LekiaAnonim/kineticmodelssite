"""
SSH Job Manager for RMG Importer Dashboard

Handles SSH connections to the cluster and job management via SLURM.
"""

import re
import logging
import json
from typing import List, Dict, Optional, Tuple
from django.utils import timezone

from .models import ClusterJob, ImportJobConfig, ImportJobStatus, JobLog
from .ssh_utils import create_ssh_client

logger = logging.getLogger(__name__)


class SSHJobManager:
    """
    Manages SSH connections and SLURM job operations on the cluster
    """
    
    def __init__(self, config: ImportJobConfig, username: Optional[str] = None, 
                 password: Optional[str] = None):
        self.config = config
        self.username = username
        self.password = password
        self.ssh_client = None
        self._connected = False
    
    def connect(self):
        """Establish SSH connection to the cluster"""
        if self._connected and self.ssh_client:
            return
        
        try:
            # Use shared SSH connection utility
            self.ssh_client = create_ssh_client(
                host=self.config.ssh_host,
                port=self.config.ssh_port,
                username=self.username,
                password=self.password
            )
            self._connected = True
            
        except Exception as e:
            logger.error(f"Failed to connect to {self.config.ssh_host}: {str(e)}")
            raise
    
    def disconnect(self):
        """Close SSH connection"""
        if self.ssh_client:
            self.ssh_client.close()
            self._connected = False
            logger.info("Disconnected from cluster")
    
    def is_connected(self):
        """Check if SSH connection is active"""
        return self._connected and self.ssh_client is not None
    
    def exec_command(self, command: str):
        """
        Execute a command on the cluster
        
        Returns: (stdout, stderr) as strings
        """
        if not self.is_connected():
            self.connect()
        
        stdin, stdout, stderr = self.ssh_client.exec_command(command)
        stdout_str = stdout.read().decode('utf-8')
        stderr_str = stderr.read().decode('utf-8')
        
        return stdout_str, stderr_str
    
    def discover_jobs(self):
        """
        Discover all possible import jobs on the cluster
        
        Finds all directories with import.sh files and extracts port numbers.
        """
        command = f'find {self.config.root_path} -name import.sh | xargs grep port'
        stdout, stderr = self.exec_command(command)
        
        discovered_jobs = []
        ports_by_path = {}
        
        for line in stdout.splitlines():
            match = re.match(r"(.*)/import.sh", line)
            if not match:
                continue
            
            path = match.group(1)
            
            # Extract port from various formats
            port_match = re.search(r'#SBATCH --job-name=port(\d+)', line)
            if not port_match:
                port_match = re.search(r'#BSUB -J port(\d+)', line)
            if not port_match:
                port_match = re.search(r'--port (\d+)', line)
            
            if port_match:
                port = int(port_match.group(1))
                ports_by_path[path] = port
        
        # Create or update job records
        for path, port in ports_by_path.items():
            job, created = ClusterJob.objects.get_or_create(
                port=port,
                defaults={
                    'name': path.replace(self.config.root_path, ''),
                    'config': self.config,
                    'status': ImportJobStatus.IDLE,  # Discovered but not started
                }
            )
            discovered_jobs.append(job)
            
            if created:
                logger.info(f"Discovered new job: {job.name} on port {port}")
        
        return discovered_jobs
    
    def update_running_jobs_status(self):
        """
        Update the status of all jobs by querying SLURM
        
        This method now properly handles job lifecycle:
        - Updates jobs found in SLURM queue
        - Checks disappeared jobs using sacct
        - Preserves historical data for completed jobs
        """
        command = "squeue -o '%i %R %j' | grep port"
        stdout, stderr = self.exec_command(command)
        
        # Parse SLURM queue to find current jobs
        jobs_in_slurm = {}  # port -> {slurm_job_id, host, status}
        
        for line in stdout.splitlines():
            job_number_match = re.match(r"(\d+)", line)
            if not job_number_match:
                continue
            
            job_number = job_number_match.group(1)
            
            # Check for running job with host
            match = re.search(r"(c[\-0-9]+)\s+port(\d+)", line)
            if match:
                host = match.group(1)
                port = int(match.group(2))
                status = ImportJobStatus.RUNNING
            else:
                # Check for pending job
                match = re.search(r"\(None\)\s+port(\d+)", line)
                if match:
                    host = None
                    port = int(match.group(1))
                    status = ImportJobStatus.PENDING
                else:
                    # Stuck job
                    match = re.search(r"\(([^)]+)\)\s+port(\d+)", line)
                    if match:
                        host = None
                        port = int(match.group(2))
                        status = ImportJobStatus.PENDING
                    else:
                        continue
            
            jobs_in_slurm[port] = {
                'slurm_job_id': job_number,
                'host': host,
                'status': status
            }
        
        # Update jobs found in SLURM
        for port, job_info in jobs_in_slurm.items():
            try:
                job = ClusterJob.objects.get(port=port)
                
                # Don't update status if job was manually cancelled, completed, or failed
                # (SLURM might still show the job briefly after cancellation)
                if job.status in [ImportJobStatus.CANCELLED, ImportJobStatus.COMPLETED, ImportJobStatus.FAILED]:
                    logger.info(f"Skipping update for job {job.name} - status is {job.status}")
                    continue
                
                job.slurm_job_id = job_info['slurm_job_id']
                job.host = job_info['host']
                job.status = job_info['status']
                
                if job_info['status'] == ImportJobStatus.RUNNING and not job.started_at:
                    job.started_at = timezone.now()
                
                job.save()
                logger.info(f"Updated job {job.name}: {job_info['status']} on {job_info['host'] or 'pending'}")
                
            except ClusterJob.DoesNotExist:
                logger.warning(f"Found SLURM job on port {port} but no ClusterJob record")
        
        # Check jobs that claim to be running/pending but aren't in SLURM anymore
        potentially_finished = ClusterJob.objects.filter(
            status__in=[ImportJobStatus.RUNNING, ImportJobStatus.PENDING]
        ).exclude(port__in=jobs_in_slurm.keys())
        
        for job in potentially_finished:
            if job.slurm_job_id:
                # Check sacct to see if it completed or failed
                try:
                    final_status = self._check_job_exit_status(job.slurm_job_id)
                    
                    if final_status in [ImportJobStatus.COMPLETED, ImportJobStatus.FAILED]:
                        job.status = final_status
                        job.host = None  # Clear host since job is done
                        job.slurm_job_id = None  # Clear SLURM ID
                        if not job.completed_at:
                            job.completed_at = timezone.now()
                        job.save()
                        logger.info(f"Job {job.name} marked as {final_status}")
                    else:
                        # Job might have just been submitted, keep current status
                        logger.debug(f"Job {job.name} not in queue but sacct shows {final_status}")
                except Exception as e:
                    logger.warning(f"Could not check exit status for job {job.name}: {e}")
            else:
                # No SLURM ID and not in queue
                # Only mark as idle if status is pending/running (not if already cancelled/completed/failed)
                if job.status in [ImportJobStatus.PENDING, ImportJobStatus.RUNNING]:
                    job.status = ImportJobStatus.IDLE
                    job.host = None
                    job.save()
                    logger.info(f"Job {job.name} marked as idle (no SLURM job ID)")
    
    def _check_job_exit_status(self, slurm_job_id):
        """
        Check the exit status of a job using sacct
        
        Returns ImportJobStatus based on SLURM accounting data
        """
        command = f"sacct -j {slurm_job_id} --format=State --noheader -P | head -1"
        stdout, stderr = self.exec_command(command)
        
        if stdout:
            state = stdout.strip()
            
            if state == 'COMPLETED':
                return ImportJobStatus.COMPLETED
            elif state in ['FAILED', 'CANCELLED', 'TIMEOUT', 'NODE_FAIL', 'OUT_OF_MEMORY']:
                return ImportJobStatus.FAILED
            elif state == 'RUNNING':
                return ImportJobStatus.RUNNING
            elif state == 'PENDING':
                return ImportJobStatus.PENDING
            else:
                logger.warning(f"Unknown SLURM state: {state}")
                return ImportJobStatus.PENDING
        
        return ImportJobStatus.PENDING
    
    def start_job(self, job: ClusterJob):
        """
        Start an import job on the cluster
        
        Returns: (slurm_job_id, host) - host will be 'Pending...' initially
        """
        if not job.config:
            job.config = self.config
            job.save()
        
        # Build the job submission command
        command = (
            f'cd {self.config.root_path}/{job.name} && '
            f'source /projects/westgroup/lekia.p/miniforge3/bin/activate && '
            f'conda activate {self.config.conda_env_name} && '
            f'sbatch {self.config.slurm_string} '
            f'--export=ALL,RMGpy={self.config.rmg_py_path},'
            f'PYTHONPATH={self.config.rmg_py_path}:$PYTHONPATH '
            f'import.sh'
        )
        
        stdout, stderr = self.exec_command(command)
        
        # Extract SLURM job ID
        for line in stdout.splitlines():
            match = re.search(r'Submitted batch job (\d+)', line)
            if match:
                slurm_job_id = match.group(1)
                logger.info(f"Started job {job.name} with SLURM ID {slurm_job_id}")
                return slurm_job_id, 'Pending...'
        
        raise Exception(f"Failed to start job: {stderr}")
    
    def kill_job(self, job: ClusterJob):
        """Kill a running job"""
        if not job.slurm_job_id:
            raise ValueError("Job does not have a SLURM ID")
        
        command = f'scancel {job.slurm_job_id}'
        stdout, stderr = self.exec_command(command)
        
        logger.info(f"Killed job {job.name} (SLURM ID: {job.slurm_job_id})")
    
    def get_log_tail(self, job: ClusterJob, lines: int = 50):
        """Get the tail of the RMG log file"""
        log_path = f'{self.config.root_path}/{job.name}/RMG-Py-output/RMG.log'
        command = f'tail -n{lines} {log_path}'
        
        stdout, stderr = self.exec_command(command)
        
        if stderr and 'No such file' in stderr:
            return f"Log file not found: {log_path}"
        
        return stdout
    
    def get_output_tail(self, job: ClusterJob, lines: int = 50):
        """Get the tail of the output.log file"""
        output_path = f'{self.config.root_path}/{job.name}/output.log'
        command = f'tail -n{lines} {output_path}'
        
        stdout, stderr = self.exec_command(command)
        
        if stderr and 'No such file' in stderr:
            return f"Console output not found: {output_path}\n\nThis file is created when the job starts on the cluster."
        
        return stdout
    
    def get_error_log(self, job: ClusterJob):
        """Get the error log for a job (SLURM stderr)"""
        error_path = f'{self.config.root_path}/{job.name}/error.log'
        command = f'cat {error_path} ; stat -c %y {error_path}'
        
        stdout, stderr = self.exec_command(command)
        
        if stderr and 'No such file' in stderr:
            return f"Error log not found: {error_path}"
        
        return stdout
    
    def get_progress_json(self, job: ClusterJob):
        """
        Get progress information from the job's web interface
        
        Note: This requires the job to be running and port forwarding to be set up.
        """
        try:
            import urllib.request
            import urllib.error
            url = f'http://localhost:{job.port}/progress.json'
            logger.info(f"Attempting to fetch progress from {url} for job {job.name} (tunnel_active={job.tunnel_active})")
            
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                logger.info(f"Successfully fetched progress for job {job.name}: {data}")
                return data
        except urllib.error.URLError as e:
            # Check if it's a ConnectionResetError (RMG web server not ready yet)
            if 'Connection reset' in str(e) or 'Connection refused' in str(e):
                logger.info(f"RMG web server not ready yet for job {job.name} on {job.host}:{job.port} - job may still be initializing")
            else:
                logger.warning(f"URLError fetching progress for job {job.name} at {url}: {str(e)}")
            return None
        except ConnectionResetError as e:
            logger.info(f"RMG web server not ready yet for job {job.name} - connection reset. Job is likely still initializing.")
            return None
        except Exception as e:
            logger.warning(f"Could not fetch progress for job {job.name} at {url}: {type(e).__name__}: {str(e)}")
            return None
    
    def refresh_all_progress(self):
        """
        Refresh progress for all running jobs
        
        Returns: number of jobs updated
        """
        running_jobs = ClusterJob.objects.filter(status=ImportJobStatus.RUNNING)
        updated_count = 0
        
        for job in running_jobs:
            progress = self.get_progress_json(job)
            if progress:
                job.total_species = progress.get('total', 0)
                job.identified_species = progress.get('confirmed', 0)
                job.processed_species = progress.get('processed', 0)
                job.confirmed_species = progress.get('confirmed', 0)
                job.total_reactions = progress.get('totalreactions', 0)
                job.unmatched_reactions = progress.get('unmatchedreactions', 0)
                job.save()
                updated_count += 1
        
        return updated_count
    
    def get_completion_stats(self, job: ClusterJob):
        """
        Get completion statistics from output files for completed jobs
        
        Returns: dict with species and reaction counts, or None if unavailable
        """
        try:
            # Check for identified_chemkin.txt which lists all identified species
            chemkin_path = f'{self.config.root_path}/{job.name}/RMG-Py-output/identified_chemkin.txt'
            command = f'wc -l {chemkin_path} && grep -c "^!" {chemkin_path}'
            stdout, stderr = self.exec_command(command)
            
            if 'No such file' in stderr:
                return None
            
            lines = stdout.strip().split('\n')
            if len(lines) >= 2:
                total_lines = int(lines[0].split()[0])
                comment_lines = int(lines[1])
                species_count = total_lines - comment_lines  # Approximate
                
                # Try to get reaction count
                reaction_command = f'grep -c "^[A-Z]" {self.config.root_path}/{job.name}/RMG-Py-output/identified_chemkin.txt || echo 0'
                reaction_stdout, _ = self.exec_command(reaction_command)
                reaction_count = int(reaction_stdout.strip().split('\n')[0])
                
                return {
                    'total_species': species_count,
                    'identified_species': species_count,
                    'confirmed_species': species_count,
                    'processed_species': species_count,
                    'total_reactions': reaction_count,
                }
        except Exception as e:
            logger.warning(f"Could not get completion stats for job {job.name}: {e}")
            return None
    
    def refresh_statuses(self):
        """
        Alias for update_running_jobs_status for compatibility
        """
        return self.update_running_jobs_status()
