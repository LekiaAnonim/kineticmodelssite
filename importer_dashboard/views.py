"""
Views for the RMG Importer Dashboard

Provides web interface for managing import jobs on the cluster.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import json
import logging
import os

from .models import ClusterJob, ImportJobConfig, SpeciesIdentification, JobLog, ImportJobStatus
from .ssh_manager import SSHJobManager
from .logger import dashboard_logger, setup_dashboard_logging

# Set up dashboard logging - this forwards Python logging to dashboard_logger
logger = setup_dashboard_logging('importer_dashboard', 'dashboard')

# Also create a standard logger for non-dashboard messages (console/file logs)
# But note: dashboard_logger is the one that shows in the Activity Log UI
# logger is for standard Python logging (console, files, etc.)
standard_logger = logging.getLogger(__name__)


@login_required
def dashboard_index(request):
    """
    Main dashboard view showing all import jobs
    """
    # Get or create default configuration
    config, created = ImportJobConfig.objects.get_or_create(
        is_default=True,
        defaults={
            'name': "Default Explorer Configuration",
            'ssh_host': 'login.explorer.northeastern.edu',
            'ssh_port': 22,
            'root_path': '/projects/westgroup/lekia.p/Importer/RMG-models/',
            'slurm_partition': 'west',
            'slurm_time_limit': '3-00:00:00',
            'slurm_memory': '32768M',
            'conda_env_name': 'rmg_env',
            'rmg_py_path': '/projects/westgroup/lekia.p/RMG/RMG-Py',
        }
    )
    
    # Get all jobs ordered by status and updated time
    jobs = ClusterJob.objects.all().order_by('-updated_at')
    
    # Calculate stats
    stats = {
        'total_jobs': jobs.count(),
        'running_jobs': jobs.filter(status='running').count(),
        'pending_jobs': jobs.filter(status='pending').count(),
        'idle_jobs': jobs.filter(status='idle').count(),
        'completed_jobs': jobs.filter(status='completed').count(),
        'failed_jobs': jobs.filter(status='failed').count(),
    }
    
    # Get list of running job IDs for AJAX updates
    running_job_ids = json.dumps(list(jobs.filter(status='running').values_list('id', flat=True)))
    
    context = {
        'jobs': jobs,
        'config': config,
        'stats': stats,
        'running_job_ids': running_job_ids,
        'page_title': 'RMG Importer Dashboard',
    }
    
    return render(request, 'importer_dashboard/index.html', context)


@login_required
def job_detail(request, job_id):
    """
    Detailed view of a specific import job
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
    
    dashboard_logger.info(
        f"Viewing job details", 
        "dashboard",
        job_id=job.id,
        job_name=job.name,
        details={
            'status': job.status,
            'host': job.host or 'Not assigned',
            'port': job.port,
            'tunnel_active': job.tunnel_active
        }
    )
    
    # Check if host needs to be updated from SLURM
    if job.status == 'running' and (not job.host or job.host == 'Pending...') and config:
        try:
            dashboard_logger.info(
                "Refreshing job status from SLURM", 
                "dashboard",
                job_id=job.id,
                job_name=job.name
            )
            ssh_manager = SSHJobManager(config=config)
            ssh_manager.refresh_statuses()
            job.refresh_from_db()
            dashboard_logger.success(
                f"Updated host: {job.host}", 
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'host': job.host,
                    'slurm_job_id': job.slurm_job_id
                }
            )
        except Exception as e:
            dashboard_logger.warning(
                f"Could not refresh job status: {str(e)}", 
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'error': str(e),
                    'error_type': type(e).__name__
                }
            )
    
    # Now try to fetch live progress if we have a valid host
    if job.status == 'running' and job.host and job.host != 'Pending...' and config:
        try:
            ssh_manager = SSHJobManager(config=config) if 'ssh_manager' not in locals() else ssh_manager
            progress_url = f"http://localhost:{job.port}/progress.json"
            
            dashboard_logger.info(
                "Attempting to fetch live progress", 
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'progress_url': progress_url,
                    'host': job.host,
                    'port': job.port,
                    'tunnel_active': job.tunnel_active
                }
            )
            
            progress = ssh_manager.get_progress_json(job)
            if progress:
                # Update job progress from live data
                job.total_species = progress.get('total', 0)
                job.identified_species = progress.get('confirmed', 0)
                job.processed_species = progress.get('processed', 0)
                job.confirmed_species = progress.get('confirmed', 0)
                job.total_reactions = progress.get('totalreactions', 0)
                job.unmatched_reactions = progress.get('unmatchedreactions', 0)
                job.save()
                dashboard_logger.success(
                    f"Updated progress: {job.total_species} species, {job.total_reactions} reactions", 
                    "dashboard",
                    job_id=job.id,
                    job_name=job.name,
                    details={
                        'total_species': job.total_species,
                        'processed': job.processed_species,
                        'confirmed': job.confirmed_species,
                        'total_reactions': job.total_reactions
                    }
                )
            else:
                dashboard_logger.warning(
                    "No progress data returned - port forwarding may not be active", 
                    "dashboard",
                    job_id=job.id,
                    job_name=job.name,
                    details={
                        'suggestion': 'Start an Interactive Session to enable port forwarding',
                        'progress_url': progress_url
                    }
                )
        except Exception as e:
            dashboard_logger.error(
                f"Could not fetch live progress: {str(e)}", 
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'suggestion': 'Ensure port forwarding is active via Interactive Session'
                }
            )
    
    # For completed jobs with no stats, try to fetch from output files
    if job.status == 'completed' and job.total_species == 0 and config:
        try:
            dashboard_logger.info(
                "Fetching completion statistics from output files",
                "dashboard",
                job_id=job.id,
                job_name=job.name
            )
            ssh_manager = SSHJobManager(config=config) if 'ssh_manager' not in locals() else ssh_manager
            completion_stats = ssh_manager.get_completion_stats(job)
            
            if completion_stats:
                job.total_species = completion_stats.get('total_species', 0)
                job.identified_species = completion_stats.get('identified_species', 0)
                job.processed_species = completion_stats.get('processed_species', 0)
                job.confirmed_species = completion_stats.get('confirmed_species', 0)
                job.total_reactions = completion_stats.get('total_reactions', 0)
                job.save()
                
                dashboard_logger.success(
                    f"Retrieved completion stats: {job.total_species} species, {job.total_reactions} reactions",
                    "dashboard",
                    job_id=job.id,
                    job_name=job.name,
                    details=completion_stats
                )
        except Exception as e:
            dashboard_logger.warning(
                f"Could not fetch completion stats: {str(e)}",
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'error': str(e),
                    'error_type': type(e).__name__
                }
            )
    
    # Determine progress status message
    progress_status = None
    if job.status == 'running':
        if not job.host or job.host == 'Pending...':
            progress_status = {
                'type': 'warning',
                'message': 'Job is running but compute node not yet assigned. Progress will be available once SLURM assigns a node.'
            }
        elif not job.tunnel_active:
            progress_status = {
                'type': 'info',
                'message': f'Port forwarding not active. Click "Interactive Session" to enable live progress tracking on port {job.port}.'
            }
        elif job.total_species == 0:
            progress_status = {
                'type': 'warning',
                'message': f'RMG job is initializing on {job.host}. The web server on port {job.port} may not be ready yet. Progress data will appear once RMG starts processing species. This can take several minutes.'
            }
    elif job.status == 'completed':
        if job.total_species > 0:
            progress_status = {
                'type': 'success',
                'message': f'Job completed successfully. Processed {job.total_species} species and {job.total_reactions} reactions.'
            }
        else:
            progress_status = {
                'type': 'warning',
                'message': 'Job completed but no statistics available. Output files may not have been generated.'
            }
    elif job.status == 'failed':
        progress_status = {
            'type': 'danger',
            'message': 'Job failed. Check the Error Log tab for details.'
        }
    elif job.status == 'pending':
        progress_status = {
            'type': 'info',
            'message': 'Job is pending in SLURM queue. Waiting for compute resources.'
        }
    
    # Get recent logs
    recent_logs = job.logs.all()[:50]
    
    # Get species identifications
    identifications = job.species_identifications.all()[:20]
    
    context = {
        'job': job,
        'recent_logs': recent_logs,
        'identifications': identifications,
        'page_title': f'Job: {job.name}',
        'progress_status': progress_status,
    }
    
    return render(request, 'importer_dashboard/job_detail.html', context)


@login_required
@require_http_methods(["POST"])
def job_start(request, job_id):
    """
    Start an import job on the cluster
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    dashboard_logger.info(
        f"Starting job: {job.name}", 
        "dashboard",
        job_id=job.id,
        job_name=job.name,
        details={'user': request.user.username, 'action': 'start'}
    )
    
    config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
    
    if not config:
        dashboard_logger.error(
            "No configuration available", 
            "dashboard",
            job_id=job.id,
            job_name=job.name
        )
        messages.error(request, "No configuration available for this job")
        return redirect('importer_dashboard:index')
    
    try:
        dashboard_logger.info(
            f"Connecting to cluster...", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={'host': config.ssh_host, 'port': config.ssh_port}
        )
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        dashboard_logger.success(
            "Connected to cluster", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={'host': config.ssh_host}
        )
        
        dashboard_logger.info(
            f"Submitting job to SLURM...", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'partition': config.slurm_partition,
                'time_limit': config.slurm_time_limit,
                'memory': config.slurm_memory
            }
        )
        slurm_job_id, host = ssh_manager.start_job(job)
        
        job.slurm_job_id = slurm_job_id
        job.started_by = request.user
        job.mark_as_running(host=host)
        
        JobLog.objects.create(
            job=job,
            log_type='info',
            message=f'Job started by {request.user.username} with SLURM ID {slurm_job_id}'
        )
        
        dashboard_logger.success(
            f"Job started successfully", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'slurm_job_id': slurm_job_id,
                'host': host,
                'user': request.user.username
            }
        )
        messages.success(request, f'Job started successfully (SLURM ID: {slurm_job_id})')
        
    except Exception as e:
        dashboard_logger.error(
            f"Failed to start job: {str(e)}", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={'error': str(e), 'error_type': type(e).__name__}
        )
        logger.error(f"Failed to start job {job.id}: {str(e)}")
        messages.error(request, f'Failed to start job: {str(e)}')
        job.mark_as_failed()
    
    return redirect('importer_dashboard:index')


@login_required
@require_http_methods(["POST"])
def job_kill(request, job_id):
    """
    Kill a running import job
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    dashboard_logger.info(
        f"Killing job", 
        "dashboard",
        job_id=job.id,
        job_name=job.name,
        details={'slurm_job_id': job.slurm_job_id, 'user': request.user.username}
    )
    
    config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
    
    if not job.slurm_job_id:
        dashboard_logger.warning(
            f"Job has no SLURM ID", 
            "dashboard",
            job_id=job.id,
            job_name=job.name
        )
        messages.error(request, "Job does not have a SLURM ID")
        return redirect('importer_dashboard:index')
    
    try:
        dashboard_logger.info(
            "Connecting to cluster...", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={'host': config.ssh_host}
        )
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        
        dashboard_logger.info(
            f"Sending scancel command...", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={'slurm_job_id': job.slurm_job_id, 'command': 'scancel'}
        )
        ssh_manager.kill_job(job)
        
        job.status = ImportJobStatus.CANCELLED
        job.slurm_job_id = None
        job.host = None
        job.completed_at = timezone.now()
        job.save()
        
        JobLog.objects.create(
            job=job,
            log_type='info',
            message=f'Job cancelled by {request.user.username}'
        )
        
        dashboard_logger.success(
            f"Job killed successfully", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={'user': request.user.username}
        )
        
        messages.success(request, 'Job cancelled successfully')
        
    except Exception as e:
        dashboard_logger.error(f"❌ Failed to kill job: {str(e)}", "dashboard")
        logger.error(f"Failed to kill job {job.id}: {str(e)}")
        messages.error(request, f'Failed to kill job: {str(e)}')
    
    return redirect('importer_dashboard:index')


@login_required
def job_log_view(request, job_id):
    """
    View the RMG log tail for a job
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    dashboard_logger.info(
        "Fetching log tail", 
        "dashboard",
        job_id=job.id,
        job_name=job.name,
        details={
            'user': request.user.username,
            'log_type': 'RMG.log'
        }
    )
    
    config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
    
    try:
        dashboard_logger.info(
            "Connecting to cluster", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'host': config.ssh_host,
                'port': config.ssh_port
            }
        )
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        
        log_path = f"{config.root_path}/{job.name}/RMG.log" if config and job.name else "unknown"
        dashboard_logger.info(
            f"Reading RMG.log from {job.host or 'cluster'}", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'log_path': log_path,
                'host': job.host or config.ssh_host
            }
        )
        log_content = ssh_manager.get_log_tail(job)
        
        line_count = len(log_content.split('\n')) if log_content else 0
        file_size = len(log_content) if log_content else 0
        
        dashboard_logger.success(
            f"Retrieved {line_count} lines", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'lines': line_count,
                'bytes': file_size,
                'log_path': log_path
            }
        )
        
        job.last_log_update = timezone.now()
        job.save()
        
    except Exception as e:
        dashboard_logger.error(
            f"Failed to fetch log: {str(e)}", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'error': str(e),
                'error_type': type(e).__name__,
                'log_path': log_path if 'log_path' in locals() else 'unknown'
            }
        )
        logger.error(f"Failed to get log for job {job.id}: {str(e)}")
        log_content = f"Error retrieving log: {str(e)}"
    
    context = {
        'job': job,
        'log_content': log_content,
        'page_title': f'Log: {job.name}',
    }
    
    return render(request, 'importer_dashboard/job_log.html', context)


@login_required
def job_console_output_view(request, job_id):
    """
    View the SLURM console output (output.log) - shows complete job execution
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    dashboard_logger.info(
        "Fetching console output", 
        "dashboard",
        job_id=job.id,
        job_name=job.name,
        details={
            'user': request.user.username,
            'log_type': 'console_output'
        }
    )
    
    config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
    
    try:
        dashboard_logger.info(
            "Connecting to cluster", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'host': config.ssh_host,
                'port': config.ssh_port
            }
        )
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        
        output_path = f"{config.root_path}/{job.name}/output.log" if config and job.name else "unknown"
        dashboard_logger.info(
            f"Reading console output from {job.host or 'cluster'}", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'output_path': output_path,
                'host': job.host or config.ssh_host
            }
        )
        console_content = ssh_manager.get_console_output(job)
        
        line_count = len(console_content.split('\n')) if console_content else 0
        file_size = len(console_content) if console_content else 0
        
        dashboard_logger.success(
            f"Retrieved {line_count} lines", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'lines': line_count,
                'bytes': file_size,
                'output_path': output_path
            }
        )
        
    except Exception as e:
        dashboard_logger.error(
            f"Failed to fetch console output: {str(e)}", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'error': str(e),
                'error_type': type(e).__name__,
                'output_path': output_path if 'output_path' in locals() else 'unknown'
            }
        )
        logger.error(f"Failed to get console output for job {job.id}: {str(e)}")
        console_content = f"Error retrieving console output: {str(e)}"
    
    context = {
        'job': job,
        'log_content': console_content,
        'page_title': f'Console Output: {job.name}',
        'log_type': 'console',
    }
    
    return render(request, 'importer_dashboard/job_log.html', context)


@login_required
def job_error_log_view(request, job_id):
    """
    View comprehensive error information for a job (live from cluster)
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    dashboard_logger.info(
        "Fetching error log", 
        "dashboard",
        job_id=job.id,
        job_name=job.name,
        details={
            'user': request.user.username,
            'log_type': 'error_log'
        }
    )
    
    config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
    
    error_content = None
    error_updated = None
    
    try:
        dashboard_logger.info(
            "Connecting to cluster", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'host': config.ssh_host,
                'port': config.ssh_port
            }
        )
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        
        error_path = f"{config.root_path}/{job.name}" if config and job.name else "unknown"
        dashboard_logger.info(
            f"Reading error logs from {job.host or 'cluster'}", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'error_path': error_path,
                'host': job.host or config.ssh_host
            }
        )
        error_content = ssh_manager.get_error_log(job)
        error_updated = timezone.now()
        
        # Parse error file modification time from stat output
        error_file_mtime = None
        if error_content:
            lines = error_content.split('\n')
            # Last line should be the stat timestamp
            if lines and len(lines) > 1:
                last_line = lines[-1].strip()
                # Try to parse timestamp like "2025-10-10 08:55:31.244482512 -0400"
                if last_line and not last_line.startswith('Error') and not last_line.startswith('Traceback'):
                    try:
                        from datetime import datetime
                        # Split on space and take first two parts (date and time with microseconds)
                        parts = last_line.split()
                        if len(parts) >= 2:
                            datetime_str = f"{parts[0]} {parts[1].split('.')[0]}"  # Remove microseconds
                            error_file_mtime = timezone.datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                            # Make timezone-aware
                            error_file_mtime = timezone.make_aware(error_file_mtime)
                            # Remove the timestamp line from content
                            error_content = '\n'.join(lines[:-1])
                    except Exception as parse_error:
                        logger.debug(f"Could not parse error log timestamp: {parse_error}")
                        pass
        
        # Determine if errors are from current run or previous run
        error_is_stale = False
        if error_file_mtime and job.started_at:
            # If error file was last modified before this job started, errors are from previous run
            if error_file_mtime < job.started_at:
                error_is_stale = True
        
        if error_content and error_content.strip():
            error_lines = error_content.split('\n')
            error_count = len([line for line in error_lines if 'error' in line.lower()])
            dashboard_logger.warning(
                f"Found {error_count} error entries", 
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'error_count': error_count,
                    'total_lines': len(error_lines),
                    'error_path': error_path,
                    'error_is_stale': error_is_stale,
                    'error_file_mtime': str(error_file_mtime) if error_file_mtime else 'unknown'
                }
            )
        else:
            dashboard_logger.success(
                "No errors found", 
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'error_path': error_path
                }
            )
        
        # Update the job's last error check time
        job.last_error_update = error_updated
        job.save()
        
    except Exception as e:
        dashboard_logger.error(
            f"Failed to fetch error log: {str(e)}", 
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'error': str(e),
                'error_type': type(e).__name__,
                'error_path': error_path if 'error_path' in locals() else 'unknown'
            }
        )
        logger.error(f"Failed to get error log for job {job.id}: {str(e)}")
        error_content = f"Error retrieving live error information: {str(e)}\n\n"
        error_content += "Please check:\n"
        error_content += "1. SSH connection is active (click 'Reconnect SSH')\n"
        error_content += "2. Job directory exists on cluster\n"
        error_content += f"3. You have access to: {config.root_path if config else 'N/A'}"
    
    context = {
        'job': job,
        'error_content': error_content,
        'error_updated': error_updated,
        'error_file_mtime': error_file_mtime,
        'error_is_stale': error_is_stale if 'error_is_stale' in locals() else False,
        'page_title': f'Error Log: {job.name}',
    }
    
    return render(request, 'importer_dashboard/job_error_log.html', context)


@login_required
def refresh_jobs(request):
    """
    Refresh the list of jobs from the cluster
    """
    dashboard_logger.info(
        "Starting job refresh", 
        "dashboard",
        details={
            'user': request.user.username,
            'action': 'refresh_jobs'
        }
    )
    
    config = ImportJobConfig.objects.filter(is_default=True).first()
    
    if not config:
        dashboard_logger.error(
            "No default configuration found", 
            "dashboard",
            details={
                'user': request.user.username,
                'error_type': 'ConfigurationError'
            }
        )
        messages.error(request, "No default configuration found")
        return redirect('importer_dashboard:index')
    
    try:
        ssh_username = os.getenv('SSH_USERNAME', 'unknown')
        
        dashboard_logger.info(
            "Connecting to SSH", 
            "dashboard",
            details={
                'host': config.ssh_host,
                'port': config.ssh_port,
                'user': ssh_username
            }
        )
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        dashboard_logger.success(
            "SSH connection established", 
            "dashboard",
            details={
                'host': config.ssh_host,
                'connection_method': 'environment_credentials'
            }
        )
        
        # Discover possible jobs
        dashboard_logger.info(
            "Discovering jobs on cluster", 
            "dashboard",
            details={
                'root_path': config.root_path,
                'search_location': f"{ssh_username}@{config.ssh_host}"
            }
        )
        discovered_jobs = ssh_manager.discover_jobs()
        dashboard_logger.success(
            f"Discovered {len(discovered_jobs)} jobs", 
            "dashboard",
            details={
                'jobs_found': len(discovered_jobs),
                'root_path': config.root_path
            }
        )
        
        # Update running jobs status
        dashboard_logger.info(
            "Querying SLURM for job status", 
            "dashboard",
            details={
                'command': 'squeue',
                'partition': config.slurm_partition
            }
        )
        ssh_manager.update_running_jobs_status()
        
        # Get updated counts
        running_count = ClusterJob.objects.filter(status='running').count()
        pending_count = ClusterJob.objects.filter(status='pending').count()
        completed_count = ClusterJob.objects.filter(status='completed').count()
        
        dashboard_logger.success(
            f"Status updated: {running_count} running, {pending_count} pending, {completed_count} completed",
            "dashboard",
            details={
                'running': running_count,
                'pending': pending_count,
                'completed': completed_count,
                'total_discovered': len(discovered_jobs)
            }
        )
        
        messages.success(request, f'Refreshed {len(discovered_jobs)} jobs from cluster')
        
    except Exception as e:
        dashboard_logger.error(
            f"Failed to refresh jobs: {str(e)}", 
            "dashboard",
            details={
                'error': str(e),
                'error_type': type(e).__name__,
                'user': request.user.username
            }
        )
        logger.error(f"Failed to refresh jobs: {str(e)}")
        messages.error(request, f'Failed to refresh jobs: {str(e)}')
    
    return redirect('importer_dashboard:index')


@login_required
def refresh_progress(request):
    """
    Refresh progress information for all running jobs
    """
    dashboard_logger.info(
        "Starting progress refresh", 
        "dashboard",
        details={
            'user': request.user.username,
            'action': 'refresh_progress'
        }
    )
    
    config = ImportJobConfig.objects.filter(is_default=True).first()
    
    if not config:
        dashboard_logger.error(
            "No default configuration found", 
            "dashboard",
            details={
                'user': request.user.username,
                'error_type': 'ConfigurationError'
            }
        )
        messages.error(request, "No default configuration found")
        return redirect('importer_dashboard:index')
    
    try:
        ssh_username = os.getenv('SSH_USERNAME', 'unknown')
        
        dashboard_logger.info(
            "Connecting to SSH", 
            "dashboard",
            details={
                'host': config.ssh_host,
                'port': config.ssh_port,
                'user': ssh_username
            }
        )
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        dashboard_logger.success(
            "SSH connection established", 
            "dashboard",
            details={
                'host': config.ssh_host
            }
        )
        
        # First update job status from SLURM
        dashboard_logger.info(
            "Updating job statuses from SLURM", 
            "dashboard",
            details={
                'command': 'squeue',
                'partition': config.slurm_partition
            }
        )
        ssh_manager.update_running_jobs_status()
        
        # Get running jobs with hosts
        running_jobs = ClusterJob.objects.filter(status='running').exclude(host=None)
        dashboard_logger.info(
            f"Found {running_jobs.count()} jobs with active hosts", 
            "dashboard",
            details={
                'active_jobs': running_jobs.count(),
                'job_names': [job.name for job in running_jobs[:5]]  # First 5 jobs
            }
        )
        
        # Refresh progress for each job
        updated_count = ssh_manager.refresh_all_progress()
        
        dashboard_logger.success(
            f"Progress updated for {updated_count} jobs", 
            "dashboard",
            details={
                'updated_count': updated_count,
                'total_running': running_jobs.count()
            }
        )
        messages.success(request, f'Refreshed progress for {updated_count} jobs')
        
    except Exception as e:
        dashboard_logger.error(
            f"Failed to refresh progress: {str(e)}", 
            "dashboard",
            details={
                'error': str(e),
                'error_type': type(e).__name__,
                'user': request.user.username
            }
        )
        logger.error(f"Failed to refresh progress: {str(e)}")
        messages.error(request, f'Failed to refresh progress: {str(e)}')
    
    return redirect('importer_dashboard:index')


@login_required
def settings_view(request):
    """
    View and edit dashboard settings
    """
    import os
    
    config = ImportJobConfig.objects.filter(is_default=True).first()
    
    if request.method == 'POST':
        # Update all configuration fields
        config.name = request.POST.get('name', config.name)
        config.ssh_host = request.POST.get('ssh_host', config.ssh_host)
        config.ssh_port = int(request.POST.get('ssh_port', config.ssh_port))
        config.root_path = request.POST.get('root_path', config.root_path)
        config.slurm_partition = request.POST.get('slurm_partition', 'west')
        config.slurm_time_limit = request.POST.get('slurm_time_limit', '3-00:00:00')
        config.slurm_memory = request.POST.get('slurm_memory', '32768M')
        config.additional_slurm_args = request.POST.get('additional_slurm_args', '')
        config.conda_env_name = request.POST.get('conda_env_name', config.conda_env_name)
        config.rmg_py_path = request.POST.get('rmg_py_path', config.rmg_py_path)
        config.is_default = request.POST.get('is_default') == 'on'
        config.save()
        
        messages.success(request, 'Settings updated successfully')
        return redirect('importer_dashboard:settings')
    
    context = {
        'config': config,
        'ssh_username': os.environ.get('SSH_USERNAME', 'Not configured'),
        'page_title': 'Dashboard Settings',
    }
    
    return render(request, 'importer_dashboard/settings.html', context)


# API Endpoints for interactive use

@csrf_exempt
def api_job_progress(request, job_id):
    """
    API endpoint to get job progress (JSON)
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    
    data = {
        'job_id': job.id,
        'name': job.name,
        'status': job.status,
        'progress': {
            'total': job.total_species,
            'identified': job.identified_species,
            'processed': job.processed_species,
            'confirmed': job.confirmed_species,
            'percentage': job.progress_percentage,
        },
        'reactions': {
            'total': job.total_reactions,
            'unmatched': job.unmatched_reactions,
        },
        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
    }
    
    return JsonResponse(data)


@csrf_exempt
@require_http_methods(["POST"])
def api_species_identify(request, job_id):
    """
    API endpoint to record a species identification
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    
    try:
        data = json.loads(request.body)
        chemkin_label = data.get('chemkin_label')
        smiles = data.get('smiles')
        
        identification, created = SpeciesIdentification.objects.get_or_create(
            job=job,
            chemkin_label=chemkin_label,
            defaults={
                'smiles': smiles,
                'identified_by': request.user if request.user.is_authenticated else None,
                'identification_method': data.get('method', 'manual'),
            }
        )
        
        if not created:
            identification.smiles = smiles
            identification.save()
        
        return JsonResponse({
            'success': True,
            'identification_id': identification.id,
            'created': created,
        })
        
    except Exception as e:
        logger.error(f"Failed to record identification: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def interactive_session(request, job_id):
    """
    Interactive session view for species identification
    
    This provides a WebSocket-like interface for real-time interaction
    with the importChemkin.py process.
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    
    # Try to refresh progress if tunnel is active and data is stale
    config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
    
    # Check if host needs to be updated from SLURM
    if job.status == 'running' and (not job.host or job.host == 'Pending...') and config:
        try:
            ssh_manager = SSHJobManager(config=config)
            ssh_manager.refresh_statuses()
            job.refresh_from_db()
            logger.info(f"Refreshed job status for {job.name}, host is now: {job.host}")
        except Exception as e:
            logger.warning(f"Could not refresh job status for job {job.id}: {str(e)}")
    
    # Now try to fetch live progress if we have a valid host
    if job.status == 'running' and job.host and job.host != 'Pending...' and config:
        try:
            ssh_manager = SSHJobManager(config=config) if 'ssh_manager' not in locals() else ssh_manager
            progress = ssh_manager.get_progress_json(job)
            if progress:
                # Update job progress from live data
                job.total_species = progress.get('total', 0)
                job.identified_species = progress.get('confirmed', 0)
                job.processed_species = progress.get('processed', 0)
                job.confirmed_species = progress.get('confirmed', 0)
                job.total_reactions = progress.get('totalreactions', 0)
                job.unmatched_reactions = progress.get('unmatchedreactions', 0)
                job.save()
                logger.info(f"Updated progress for job {job.name}: {job.total_species} species")
        except Exception as e:
            logger.warning(f"Could not fetch live progress for job {job.id}: {str(e)}")
    
    # Get recent identifications
    recent_identifications = SpeciesIdentification.objects.filter(
        job=job
    ).order_by('-created_at')[:20]
    
    # Calculate unidentified species
    unidentified_count = max(0, job.total_species - job.identified_species) if job.total_species else 0
    
    # Mock pending species (in production, this would come from the job's progress.json)
    # TODO: Fetch actual pending species from the job's web interface
    pending_species = []
    if unidentified_count > 0:
        pending_species = [
            {
                'chemkin_label': f'species_{i}', 
                'structure': None,
                'note': 'Placeholder - connect to job interface for actual species'
            }
            for i in range(min(5, unidentified_count))
        ]
    
    context = {
        'job': job,
        'recent_identifications': recent_identifications,
        'pending_species': pending_species,
        'tunnel_active': job.status == 'running' and job.host,
        'unidentified_count': unidentified_count,
        'page_title': f'Interactive Session: {job.name}',
    }
    
    return render(request, 'importer_dashboard/interactive_session.html', context)


@login_required
@require_http_methods(["POST"])
def reconnect(request):
    """Reconnect SSH connection"""
    dashboard_logger.info("🔌 Attempting SSH reconnection...", "dashboard")
    
    try:
        config = ImportJobConfig.objects.filter(is_default=True).first()
        if config:
            ssh_manager = SSHJobManager(config=config)
            ssh_manager.connect()
            dashboard_logger.success("✅ SSH connection reestablished", "dashboard")
            messages.success(request, "SSH connection reestablished successfully")
        else:
            dashboard_logger.error("❌ No default configuration found", "dashboard")
            messages.error(request, "No default configuration found")
    except Exception as e:
        dashboard_logger.error(f"❌ Failed to reconnect: {str(e)}", "dashboard")
        logger.error(f"Failed to reconnect: {str(e)}")
        messages.error(request, f"Failed to reconnect: {str(e)}")
    
    return redirect('importer_dashboard:index')


@login_required
@require_http_methods(["POST"])
def git_pull(request):
    """Pull updates from GitHub repository"""
    try:
        config = ImportJobConfig.objects.filter(is_default=True).first()
        ssh_manager = SSHJobManager(config=config)
        ssh_manager.connect()
        
        cmd = f'cd {config.root_path} && git pull official master'
        stdout, stderr = ssh_manager.exec_command(cmd)
        
        if stderr:
            messages.warning(request, f"Git pull completed with warnings: {stderr}")
        else:
            messages.success(request, f"Git pull successful: {stdout}")
        
        ssh_manager.disconnect()
    except Exception as e:
        logger.error(f"Failed to git pull: {str(e)}")
        messages.error(request, f"Failed to pull updates: {str(e)}")
    
    return redirect('importer_dashboard:index')


@login_required
@require_http_methods(["POST"])
def job_pause(request, job_id):
    """Pause a running job"""
    try:
        job = get_object_or_404(ClusterJob, id=job_id)
        
        if job.status != 'running':
            messages.error(request, "Job is not running")
            return redirect('importer_dashboard:interactive_session', job_id=job_id)
        
        # Send pause signal (implementation depends on importChemkin.py support)
        job.status = 'paused'
        job.save()
        
        JobLog.objects.create(
            job=job,
            level='info',
            message=f"Job paused by {request.user.username}"
        )
        
        messages.success(request, f"Job {job.name} paused")
    except Exception as e:
        logger.error(f"Failed to pause job: {str(e)}")
        messages.error(request, f"Failed to pause job: {str(e)}")
    
    return redirect('importer_dashboard:interactive_session', job_id=job_id)


@login_required
def log_stream(request):
    """
    Server-Sent Events endpoint for real-time log streaming
    """
    import time
    
    def event_stream():
        """Generator that yields SSE formatted messages"""
        # Send initial connection message
        yield f"data: {json.dumps({'type': 'connected', 'message': 'Log stream connected'})}\n\n"
        
        # Get recent messages
        recent = dashboard_logger.get_recent_messages(50)
        for msg in recent:
            yield f"data: {json.dumps(msg)}\n\n"
        
        # Keep connection alive and send new messages
        last_count = len(dashboard_logger.messages)
        
        while True:
            time.sleep(0.5)  # Poll every 500ms
            
            current_count = len(dashboard_logger.messages)
            if current_count > last_count:
                # New messages available
                new_messages = dashboard_logger.get_recent_messages(current_count - last_count)
                for msg in new_messages:
                    yield f"data: {json.dumps(msg)}\n\n"
                last_count = current_count
            
            # Send heartbeat every 15 seconds
            yield f": heartbeat\n\n"
    
    response = HttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@login_required
def get_logs(request):
    """
    Get recent log messages as JSON
    """
    count = int(request.GET.get('count', 100))
    category = request.GET.get('category', None)
    
    messages = dashboard_logger.get_recent_messages(count, category)
    
    return JsonResponse({
        'messages': messages,
        'count': len(messages)
    })


@login_required
@require_http_methods(["POST"])
def clear_logs(request):
    """Clear all log messages"""
    dashboard_logger.clear()
    dashboard_logger.info("🗑️ Logs cleared", "dashboard")
    messages.success(request, "Logs cleared")
    return redirect('importer_dashboard:index')


@login_required
def log_stream_test(request):
    """Diagnostic page for testing log stream"""
    return render(request, 'importer_dashboard/log_stream_test.html', {
        'page_title': 'Log Stream Test',
    })


@login_required
def test_progress_fetch(request, job_id):
    """
    Debug endpoint to manually test progress.json fetching
    """
    job = get_object_or_404(ClusterJob, id=job_id)
    config = job.config or ImportJobConfig.objects.filter(is_default=True).first()
    
    result = {
        'job_id': job.id,
        'job_name': job.name,
        'port': job.port,
        'host': job.host,
        'status': job.status,
        'tunnel_active': job.tunnel_active,
        'progress_url': f'http://localhost:{job.port}/progress.json',
        'current_stats': {
            'total_species': job.total_species,
            'processed': job.processed_species,
            'identified': job.identified_species,
            'confirmed': job.confirmed_species,
            'total_reactions': job.total_reactions,
        },
        'fetch_result': None,
        'error': None,
    }
    
    # Try to fetch progress
    try:
        import urllib.request
        import urllib.error
        url = f'http://localhost:{job.port}/progress.json'
        
        dashboard_logger.info(
            f"Testing progress fetch from {url}",
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'url': url,
                'tunnel_active': job.tunnel_active,
                'host': job.host
            }
        )
        
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            result['fetch_result'] = data
            result['success'] = True
            
            dashboard_logger.success(
                f"Successfully fetched progress data",
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'total': data.get('total', 0),
                    'processed': data.get('processed', 0),
                    'confirmed': data.get('confirmed', 0)
                }
            )
            
    except urllib.error.URLError as e:
        error_str = str(e)
        # Check if it's a ConnectionResetError or ConnectionRefusedError
        if 'Connection reset' in error_str or 'Errno 54' in error_str:
            result['error'] = f"Connection reset by peer - RMG web server not ready yet"
            result['suggestion'] = f"The RMG job is still initializing on {job.host}. Wait a few minutes and refresh. The web server on port {job.port} will start once RMG begins processing."
            dashboard_logger.warning(
                f"RMG web server not ready yet - connection reset",
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'error_type': 'ConnectionResetError',
                    'host': job.host,
                    'port': job.port,
                    'suggestion': 'Job is initializing. Web server will start shortly.'
                }
            )
        elif 'Connection refused' in error_str or 'Errno 61' in error_str:
            result['error'] = f"Connection refused - RMG web server not running"
            result['suggestion'] = f"The RMG web server on {job.host}:{job.port} is not running yet. Check the job's RMG.log to see if it has started."
            dashboard_logger.warning(
                f"RMG web server not running - connection refused",
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'error_type': 'ConnectionRefusedError',
                    'host': job.host,
                    'port': job.port,
                    'suggestion': 'Check RMG.log for startup status'
                }
            )
        else:
            result['error'] = f"URLError: {error_str}"
            result['suggestion'] = "Port forwarding may not be active"
            dashboard_logger.error(
                f"Failed to fetch progress: {error_str}",
                "dashboard",
                job_id=job.id,
                job_name=job.name,
                details={
                    'error_type': 'URLError',
                    'error': error_str,
                    'suggestion': 'Ensure SSH tunnel is active on port ' + str(job.port)
                }
            )
        result['success'] = False
    except Exception as e:
        result['error'] = f"{type(e).__name__}: {str(e)}"
        result['success'] = False
        dashboard_logger.error(
            f"Failed to fetch progress: {str(e)}",
            "dashboard",
            job_id=job.id,
            job_name=job.name,
            details={
                'error_type': type(e).__name__,
                'error': str(e)
            }
        )
    
    return JsonResponse(result, json_dumps_params={'indent': 2})


@login_required
@require_http_methods(["POST"])
def job_resume(request, job_id):
    """Resume a paused job"""
    try:
        job = get_object_or_404(ClusterJob, id=job_id)
        
        if job.status != 'paused':
            messages.error(request, "Job is not paused")
            return redirect('importer_dashboard:interactive_session', job_id=job_id)
        
        # Resume job
        job.status = 'running'
        job.save()
        
        JobLog.objects.create(
            job=job,
            level='info',
            message=f"Job resumed by {request.user.username}"
        )
        
        messages.success(request, f"Job {job.name} resumed")
    except Exception as e:
        logger.error(f"Failed to resume job: {str(e)}")
        messages.error(request, f"Failed to resume job: {str(e)}")
    
    return redirect('importer_dashboard:interactive_session', job_id=job_id)
