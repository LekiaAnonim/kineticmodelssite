"""
Analysis Models

Models for storing simulation runs, results, and model-experiment coverage tracking.
"""

import hashlib
from django.db import models
from django.conf import settings
from django.utils import timezone


class SimulationStatus(models.TextChoices):
    """Status of a simulation run"""
    PENDING = 'pending', 'Pending'
    QUEUED = 'queued', 'Queued'
    RUNNING = 'running', 'Running'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class TriggerType(models.TextChoices):
    """What triggered the simulation"""
    MANUAL = 'manual', 'Manual (User)'
    AUTO_MODEL_UPDATE = 'auto_model', 'Auto (Model Updated)'
    AUTO_DATASET_UPDATE = 'auto_dataset', 'Auto (Dataset Updated)'
    SCHEDULED = 'scheduled', 'Scheduled'
    API = 'api', 'API Request'


class MappingMethod(models.TextChoices):
    """How species mapping was determined"""
    SMILES = 'smiles', 'SMILES Match'
    INCHI = 'inchi', 'InChI Match'
    NORMALIZED = 'normalized', 'Normalized Label Match'
    MANUAL = 'manual', 'Manual Override'
    FALLBACK = 'fallback', 'Fallback (Unverified)'


class SimulationRun(models.Model):
    """
    Represents a single PyTeCK simulation run for a model-dataset pair.
    """
    # Core relationships
    kinetic_model = models.ForeignKey(
        'database.KineticModel',
        on_delete=models.CASCADE,
        related_name='simulation_runs'
    )
    dataset = models.ForeignKey(
        'chemked_database.ExperimentDataset',
        on_delete=models.CASCADE,
        related_name='simulation_runs'
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=SimulationStatus.choices,
        default=SimulationStatus.PENDING,
        db_index=True
    )
    triggered_by = models.CharField(
        max_length=20,
        choices=TriggerType.choices,
        default=TriggerType.MANUAL
    )
    triggered_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_simulations'
    )

    # Version tracking (for detecting model changes)
    model_version_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 hash of model content at simulation time"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Error tracking
    error_message = models.TextField(blank=True)
    traceback = models.TextField(blank=True)

    # Configuration used
    skip_validation = models.BooleanField(default=True)
    spec_keys_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Species mapping used for this run"
    )

    # Output directory tracking
    results_dir = models.CharField(
        max_length=512,
        blank=True,
        help_text="Path to simulation results directory"
    )

    class Meta:
        db_table = 'analysis_simulation_run'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['kinetic_model', 'dataset']),
            models.Index(fields=['status', 'created_at']),
        ]
        # Allow multiple runs of same model-dataset pair (for re-runs)
        # unique_together is NOT set

    def __str__(self):
        return f"{self.kinetic_model.model_name} × {self.dataset.short_name} ({self.status})"

    @property
    def duration(self):
        """Return simulation duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def is_outdated(self):
        """Check if model has changed since this simulation."""
        if not self.model_version_hash:
            return True
        current_hash = self.compute_model_hash(self.kinetic_model)
        return current_hash != self.model_version_hash

    @staticmethod
    def compute_model_hash(kinetic_model):
        """Compute a hash of the model's content for change detection."""
        # Hash key model attributes that affect simulation
        content = f"{kinetic_model.pk}:{kinetic_model.model_name}"
        
        # Include file modification times if available
        for field_name in ['chemkin_reactions_file', 'chemkin_thermo_file', 'chemkin_transport_file']:
            field = getattr(kinetic_model, field_name, None)
            if field and hasattr(field, 'name') and field.name:
                content += f":{field.name}"

        return hashlib.sha256(content.encode()).hexdigest()

    def mark_running(self):
        """Mark simulation as running."""
        self.status = SimulationStatus.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])

    def mark_completed(self):
        """Mark simulation as completed."""
        self.status = SimulationStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])

    def mark_failed(self, error_message, traceback=''):
        """Mark simulation as failed with error details."""
        self.status = SimulationStatus.FAILED
        self.completed_at = timezone.now()
        self.error_message = str(error_message)[:2000]
        self.traceback = str(traceback)[:10000]
        self.save(update_fields=['status', 'completed_at', 'error_message', 'traceback'])

    def mark_cancelled(self, reason='Cancelled by user'):
        """Mark simulation as cancelled."""
        self.status = SimulationStatus.CANCELLED
        self.completed_at = timezone.now()
        self.error_message = reason
        self.save(update_fields=['status', 'completed_at', 'error_message'])

    @property
    def is_stale(self):
        """
        Check if a running simulation appears to be stale/stuck.
        A simulation is considered stale if:
        - Status is 'running' AND
        - It started more than 30 minutes ago without completing
        """
        if self.status != SimulationStatus.RUNNING:
            return False
        if not self.started_at:
            # Running but never started - definitely stale
            return True
        from datetime import timedelta
        stale_threshold = timezone.now() - timedelta(minutes=30)
        return self.started_at < stale_threshold

    @classmethod
    def cleanup_stale_runs(cls, dry_run=False):
        """
        Find and mark stale running simulations as failed.
        
        Args:
            dry_run: If True, only return count without modifying
            
        Returns:
            Number of stale runs found/cleaned
        """
        from datetime import timedelta
        stale_threshold = timezone.now() - timedelta(minutes=30)
        
        stale_runs = cls.objects.filter(
            status=SimulationStatus.RUNNING,
            started_at__lt=stale_threshold
        )
        
        # Also include runs that are "running" but never started
        never_started = cls.objects.filter(
            status=SimulationStatus.RUNNING,
            started_at__isnull=True,
            created_at__lt=stale_threshold
        )
        
        stale_count = stale_runs.count() + never_started.count()
        
        if not dry_run:
            for run in stale_runs:
                run.mark_failed('Simulation timed out or was interrupted (stale)')
            for run in never_started:
                run.mark_failed('Simulation never started (stale)')
        
        return stale_count


class SimulationResult(models.Model):
    """
    Aggregated results from a simulation run.
    """
    simulation_run = models.OneToOneField(
        SimulationRun,
        on_delete=models.CASCADE,
        related_name='result'
    )

    # PyTeCK metrics
    average_error_function = models.FloatField(
        null=True,
        blank=True,
        help_text="Average error function value across all datapoints"
    )
    average_deviation_function = models.FloatField(
        null=True,
        blank=True,
        help_text="Average deviation (log ratio) across all datapoints"
    )

    # Raw results storage
    results_yaml = models.TextField(
        blank=True,
        help_text="Raw YAML output from PyTeCK"
    )
    results_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Parsed results as JSON"
    )

    # Summary statistics
    num_datapoints = models.PositiveIntegerField(default=0)
    num_successful = models.PositiveIntegerField(default=0)
    num_failed = models.PositiveIntegerField(default=0)

    # Temperature/pressure ranges evaluated
    min_temperature = models.FloatField(null=True, blank=True)
    max_temperature = models.FloatField(null=True, blank=True)
    min_pressure = models.FloatField(null=True, blank=True)
    max_pressure = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'analysis_simulation_result'

    def __str__(self):
        return f"Result for {self.simulation_run}"

    @property
    def error_function_display(self):
        """Format error function for display."""
        if self.average_error_function is not None:
            return f"{self.average_error_function:.2f}"
        return "N/A"

    @property
    def deviation_display(self):
        """Format deviation for display (as orders of magnitude)."""
        if self.average_deviation_function is not None:
            return f"{self.average_deviation_function:.2f}"
        return "N/A"

    @property
    def std_error_function(self):
        """Get standard deviation from results_json (from first dataset)."""
        if self.results_json:
            # Try to get from datasets (PyTeCK stores it per-dataset)
            datasets = self.results_json.get('datasets', [])
            if datasets and len(datasets) > 0:
                return datasets[0].get('standard deviation')
            # Fallback to top-level error function standard deviation
            return self.results_json.get('error function standard deviation')
        return None


class DatapointResult(models.Model):
    """
    Individual datapoint comparison result.
    """
    simulation_result = models.ForeignKey(
        SimulationResult,
        on_delete=models.CASCADE,
        related_name='datapoint_results'
    )
    datapoint = models.ForeignKey(
        'chemked_database.ExperimentDatapoint',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='simulation_results'
    )

    # Conditions
    temperature = models.FloatField(help_text="Temperature in Kelvin")
    pressure = models.FloatField(help_text="Pressure in Pascal")

    # Composition snapshot
    composition = models.JSONField(
        default=list,
        help_text="Species composition at this datapoint"
    )
    composition_type = models.CharField(max_length=50, default='mole fraction')

    # Ignition delay comparison
    experimental_ignition_delay = models.FloatField(
        help_text="Experimental ignition delay in seconds"
    )
    simulated_ignition_delay = models.FloatField(
        null=True,
        blank=True,
        help_text="Simulated ignition delay in seconds"
    )

    # Error metrics for this point
    error_value = models.FloatField(
        null=True,
        blank=True,
        help_text="Error function value for this datapoint"
    )
    deviation = models.FloatField(
        null=True,
        blank=True,
        help_text="Log deviation (simulated/experimental)"
    )

    # Simulation status for this point
    success = models.BooleanField(default=True)
    error_message = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = 'analysis_datapoint_result'
        ordering = ['temperature']

    def __str__(self):
        return f"T={self.temperature}K, P={self.pressure/1e5:.1f}bar"

    @property
    def ignition_delay_ratio(self):
        """Ratio of simulated to experimental ignition delay."""
        if self.simulated_ignition_delay and self.experimental_ignition_delay:
            return self.simulated_ignition_delay / self.experimental_ignition_delay
        return None

    @property
    def pressure_atm(self):
        """Pressure converted from Pascal to atm."""
        if self.pressure:
            return self.pressure / 101325.0
        return None

    @property
    def equivalence_ratio(self):
        """
        Calculate equivalence ratio (φ) from composition.
        φ = (fuel/oxidizer)_actual / (fuel/oxidizer)_stoichiometric
        For n-heptane: C7H16 + 11 O2 -> 7 CO2 + 8 H2O
        """
        if not self.composition:
            return None
        
        fuel_amount = 0.0
        oxidizer_amount = 0.0
        
        for species in self.composition:
            name = species.get('species-name', '').lower()
            try:
                amount = float(species.get('amount', 0))
            except (ValueError, TypeError):
                continue
            
            # Common fuel identifiers
            if any(f in name for f in ['c7h16', 'heptane', 'nc7', 'fuel']):
                fuel_amount = amount
            # Oxidizer (O2)
            elif name in ['o2', 'oxygen']:
                oxidizer_amount = amount
        
        if fuel_amount > 0 and oxidizer_amount > 0:
            # Stoichiometric ratio for n-heptane: 11 moles O2 per mole C7H16
            stoich_ratio = 11.0
            actual_ratio = fuel_amount / oxidizer_amount
            return actual_ratio * stoich_ratio
        
        return None


class SpeciesMapping(models.Model):
    """
    Cached species name mapping between dataset and model.
    Allows manual overrides and tracks mapping confidence.
    """
    kinetic_model = models.ForeignKey(
        'database.KineticModel',
        on_delete=models.CASCADE,
        related_name='species_mappings'
    )
    dataset = models.ForeignKey(
        'chemked_database.ExperimentDataset',
        on_delete=models.CASCADE,
        related_name='species_mappings',
        null=True,
        blank=True,
        help_text="If null, applies to all datasets"
    )

    # Mapping details
    dataset_species_name = models.CharField(
        max_length=100,
        help_text="Species name as it appears in the dataset"
    )
    model_species_name = models.CharField(
        max_length=100,
        help_text="Corresponding species name in the kinetic model"
    )

    # How the mapping was determined
    mapping_method = models.CharField(
        max_length=20,
        choices=MappingMethod.choices,
        default=MappingMethod.FALLBACK
    )
    confidence = models.FloatField(
        default=0.5,
        help_text="Confidence score 0-1"
    )

    # For manual overrides
    is_manual_override = models.BooleanField(default=False)
    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    override_reason = models.CharField(max_length=200, blank=True)

    # Identifiers used for matching
    smiles = models.CharField(max_length=500, blank=True)
    inchi = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'analysis_species_mapping'
        unique_together = ['kinetic_model', 'dataset', 'dataset_species_name']
        indexes = [
            models.Index(fields=['kinetic_model', 'dataset_species_name']),
        ]

    def __str__(self):
        return f"{self.dataset_species_name} → {self.model_species_name}"


class ModelDatasetCoverage(models.Model):
    """
    Denormalized table tracking which model-dataset pairs have been evaluated.
    Updated automatically via signals when SimulationRuns complete.
    """
    kinetic_model = models.ForeignKey(
        'database.KineticModel',
        on_delete=models.CASCADE,
        related_name='dataset_coverage'
    )
    dataset = models.ForeignKey(
        'chemked_database.ExperimentDataset',
        on_delete=models.CASCADE,
        related_name='model_coverage'
    )

    # Latest successful run
    latest_run = models.ForeignKey(
        SimulationRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    # Cached metrics from latest run
    latest_error_function = models.FloatField(null=True, blank=True)
    latest_deviation = models.FloatField(null=True, blank=True)

    # Status flags
    has_successful_run = models.BooleanField(default=False)
    is_outdated = models.BooleanField(
        default=False,
        help_text="True if model changed since last run"
    )
    needs_rerun = models.BooleanField(
        default=False,
        help_text="Flagged for re-evaluation"
    )

    # Run counts
    total_runs = models.PositiveIntegerField(default=0)
    successful_runs = models.PositiveIntegerField(default=0)
    failed_runs = models.PositiveIntegerField(default=0)

    # Timestamps
    first_evaluated_at = models.DateTimeField(null=True, blank=True)
    last_evaluated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'analysis_model_dataset_coverage'
        unique_together = ['kinetic_model', 'dataset']
        indexes = [
            models.Index(fields=['has_successful_run', 'is_outdated']),
        ]

    def __str__(self):
        status = "✓" if self.has_successful_run else "✗"
        return f"{status} {self.kinetic_model.model_name} × {self.dataset.short_name}"

    def update_from_run(self, simulation_run):
        """Update coverage record from a completed simulation run."""
        self.total_runs += 1
        self.last_evaluated_at = simulation_run.completed_at

        if not self.first_evaluated_at:
            self.first_evaluated_at = simulation_run.completed_at

        if simulation_run.status == SimulationStatus.COMPLETED:
            self.successful_runs += 1
            self.has_successful_run = True
            self.latest_run = simulation_run
            self.is_outdated = False
            self.needs_rerun = False

            # Cache metrics
            if hasattr(simulation_run, 'result'):
                self.latest_error_function = simulation_run.result.average_error_function
                self.latest_deviation = simulation_run.result.average_deviation_function
        else:
            self.failed_runs += 1

        self.save()
