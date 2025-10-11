"""
Django models for the RMG Importer Dashboard

These models track import jobs, their status, and configuration.
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class ImportJobStatus(models.TextChoices):
    """Status choices for import jobs"""
    IDLE = 'idle', 'Idle'  # Job discovered but never started
    PENDING = 'pending', 'Pending'  # Job submitted to SLURM but not running yet
    RUNNING = 'running', 'Running'
    PAUSED = 'paused', 'Paused'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class ImportJobConfig(models.Model):
    """
    Configuration for RMG importer jobs
    
    This stores the SLURM and SSH settings for running import jobs on the cluster.
    """
    name = models.CharField(max_length=200, unique=True, help_text="Configuration name")
    
    # SSH Settings
    ssh_host = models.CharField(max_length=255, default='login.explorer.northeastern.edu', 
                                help_text="SSH server hostname")
    ssh_port = models.IntegerField(default=22, help_text="SSH server port")
    root_path = models.CharField(max_length=500, default='/projects/westgroup/Importer/RMG-models/',
                                 help_text="Root path for import jobs on cluster")
    
    # SLURM Settings
    slurm_partition = models.CharField(max_length=100, default='west', 
                                      help_text="SLURM partition")
    slurm_time_limit = models.CharField(max_length=50, default='3-00:00:00',
                                       help_text="SLURM time limit (e.g., 3-00:00:00 for 3 days)")
    slurm_memory = models.CharField(max_length=50, default='32768M',
                                   help_text="SLURM memory allocation (e.g., 32768M for 32GB)")
    slurm_extra_args = models.TextField(blank=True, 
                                       help_text="Additional SLURM arguments")
    
    # Environment Settings
    conda_env_name = models.CharField(max_length=100, default='rmg_env',
                                     help_text="Conda environment name")
    rmg_py_path = models.CharField(max_length=500, 
                                  default='/projects/westgroup/lekia.p/RMG/RMG-Py',
                                  help_text="Path to RMG-Py installation")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_default = models.BooleanField(default=False, 
                                    help_text="Use as default configuration")
    
    class Meta:
        ordering = ['-is_default', 'name']
        verbose_name = "Import Job Configuration"
        verbose_name_plural = "Import Job Configurations"
    
    def __str__(self):
        return self.name
    
    @property
    def slurm_string(self):
        """Generate the SLURM argument string"""
        args = [
            f"--partition={self.slurm_partition}",
            f"--time={self.slurm_time_limit}",
            f"--mem={self.slurm_memory}"
        ]
        if self.slurm_extra_args:
            args.append(self.slurm_extra_args)
        return ' '.join(args)
    
    def save(self, *args, **kwargs):
        # Ensure only one default configuration
        if self.is_default:
            ImportJobConfig.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class ClusterJob(models.Model):
    """
    Represents an RMG import job running on the cluster
    """
    # Job Identification
    name = models.CharField(max_length=500, help_text="Job name/path")
    port = models.IntegerField(unique=True, help_text="Port number for web interface")
    slurm_job_id = models.CharField(max_length=50, blank=True, null=True, 
                                   help_text="SLURM job ID")
    
    # Job Status
    status = models.CharField(max_length=20, choices=ImportJobStatus.choices,
                             default=ImportJobStatus.PENDING)
    host = models.CharField(max_length=100, blank=True, null=True,
                           help_text="Compute node running the job")
    
    # Configuration
    config = models.ForeignKey(ImportJobConfig, on_delete=models.SET_NULL, 
                              null=True, blank=True,
                              help_text="Configuration used for this job")
    
    # Progress Tracking
    total_species = models.IntegerField(default=0)
    identified_species = models.IntegerField(default=0)
    processed_species = models.IntegerField(default=0)
    confirmed_species = models.IntegerField(default=0)
    total_reactions = models.IntegerField(default=0)
    unmatched_reactions = models.IntegerField(default=0)
    
    # Logs
    last_log_update = models.DateTimeField(null=True, blank=True)
    last_error_update = models.DateTimeField(null=True, blank=True)
    
    # Tunnel Status
    tunnel_active = models.BooleanField(default=False, 
                                       help_text="Whether SSH tunnel is currently active")
    
    # User Tracking
    started_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='started_jobs')
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-updated_at']
        verbose_name = "Cluster Job"
        verbose_name_plural = "Cluster Jobs"
    
    def __str__(self):
        return f"{self.name} (port {self.port})"
    
    @property
    def is_running(self):
        """Check if job is currently running"""
        return self.status == ImportJobStatus.RUNNING
    
    @property
    def progress_percentage(self):
        """Calculate overall progress percentage"""
        if self.total_species == 0:
            return 0
        return int((self.identified_species / self.total_species) * 100)
    
    def mark_as_running(self, host=None):
        """Mark job as running"""
        self.status = ImportJobStatus.RUNNING
        self.host = host
        if not self.started_at:
            self.started_at = timezone.now()
        self.save()
    
    def mark_as_completed(self):
        """Mark job as completed"""
        self.status = ImportJobStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save()
    
    def mark_as_failed(self):
        """Mark job as failed"""
        self.status = ImportJobStatus.FAILED
        self.completed_at = timezone.now()
        self.save()


class SpeciesIdentification(models.Model):
    """
    Tracks species identifications made during import jobs
    
    This allows resuming jobs and sharing identifications across runs.
    """
    job = models.ForeignKey(ClusterJob, on_delete=models.CASCADE, 
                           related_name='species_identifications')
    
    # Species Information
    chemkin_label = models.CharField(max_length=200, help_text="Chemkin species label")
    smiles = models.CharField(max_length=500, help_text="SMILES string")
    rmg_species_label = models.CharField(max_length=200, blank=True,
                                        help_text="RMG species label")
    
    # Identification Details
    identified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    identification_method = models.CharField(max_length=100, default='manual',
                                            help_text="How species was identified")
    confidence = models.FloatField(default=1.0, help_text="Confidence score (0-1)")
    
    # Vote Information (from vote system)
    vote_count = models.IntegerField(default=0, help_text="Number of votes")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = [['job', 'chemkin_label']]
        ordering = ['-created_at']
        verbose_name = "Species Identification"
        verbose_name_plural = "Species Identifications"
    
    def __str__(self):
        return f"{self.chemkin_label} -> {self.smiles}"


class JobLog(models.Model):
    """
    Stores log entries for import jobs
    """
    job = models.ForeignKey(ClusterJob, on_delete=models.CASCADE, 
                           related_name='logs')
    
    LOG_TYPE_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('debug', 'Debug'),
    ]
    
    log_type = models.CharField(max_length=20, choices=LOG_TYPE_CHOICES, default='info')
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Job Log"
        verbose_name_plural = "Job Logs"
    
    def __str__(self):
        return f"[{self.log_type}] {self.message[:50]}"
