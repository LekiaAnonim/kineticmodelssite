"""
Django models for storing import voting data
"""
from django.db import models
from django.contrib.auth.models import User
import json


class ImportJob(models.Model):
    """Tracks import sessions/jobs"""
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    job_id = models.CharField(
        max_length=255, 
        unique=True, 
        db_index=True,
        help_text="Unique identifier for this import job (hash of input files)"
    )
    model_name = models.CharField(
        max_length=255,
        help_text="Name/path of the model being imported"
    )
    user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="User who initiated this import"
    )
    status = models.CharField(
        max_length=50, 
        choices=STATUS_CHOICES, 
        default='active'
    )
    
    # File paths
    species_file = models.TextField(blank=True)
    reactions_file = models.TextField(blank=True)
    thermo_file = models.TextField(blank=True)
    
    # Statistics
    total_species = models.IntegerField(default=0)
    identified_species = models.IntegerField(default=0)
    total_reactions = models.IntegerField(default=0)
    matched_reactions = models.IntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_activity = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'import_jobs'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['job_id', 'status']),
            models.Index(fields=['status', '-updated_at']),
        ]
    
    def __str__(self):
        return f"{self.job_id} - {self.model_name} ({self.status})"
    
    def update_statistics(self):
        """Update statistics based on related objects"""
        self.identified_species = self.identified_species_set.count()
        self.save(update_fields=['identified_species', 'updated_at'])


class SpeciesVote(models.Model):
    """Stores individual votes for species matching"""
    
    import_job = models.ForeignKey(
        ImportJob, 
        on_delete=models.CASCADE, 
        related_name='species_votes'
    )
    chemkin_label = models.CharField(
        max_length=255, 
        db_index=True,
        help_text="Chemkin species label"
    )
    chemkin_formula = models.CharField(
        max_length=100,
        blank=True,
        help_text="Chemical formula of the Chemkin species"
    )
    
    # RMG species information
    rmg_species_label = models.CharField(max_length=255)
    rmg_species_smiles = models.TextField()
    rmg_species_index = models.IntegerField()
    rmg_species_formula = models.CharField(max_length=100, blank=True)
    
    # Vote metadata
    vote_count = models.IntegerField(
        default=0,
        help_text="Number of reactions voting for this match"
    )
    enthalpy_discrepancy = models.FloatField(
        null=True, 
        blank=True,
        help_text="Enthalpy difference in kJ/mol at 298K"
    )
    confidence_score = models.FloatField(
        default=0.0,
        help_text="Confidence score for this match (0-1)"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'species_votes'
        unique_together = [['import_job', 'chemkin_label', 'rmg_species_index']]
        indexes = [
            models.Index(fields=['import_job', 'chemkin_label']),
            models.Index(fields=['import_job', 'vote_count']),
        ]
        ordering = ['-vote_count', 'chemkin_label']
    
    def __str__(self):
        return f"{self.chemkin_label} -> {self.rmg_species_label} ({self.vote_count} votes)"


class VotingReaction(models.Model):
    """Stores the reactions that contribute to each vote"""
    
    species_vote = models.ForeignKey(
        SpeciesVote, 
        on_delete=models.CASCADE, 
        related_name='voting_reactions'
    )
    
    # Reaction representations (as strings for display)
    chemkin_reaction_str = models.TextField()
    edge_reaction_str = models.TextField()
    reaction_family = models.CharField(max_length=255, blank=True)
    
    # Serialized reaction data (JSON for portability instead of pickle)
    chemkin_reaction_json = models.JSONField(null=True, blank=True)
    edge_reaction_json = models.JSONField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'voting_reactions'
        indexes = [
            models.Index(fields=['species_vote']),
        ]
    
    def __str__(self):
        return f"Vote: {self.chemkin_reaction_str}"


class IdentifiedSpecies(models.Model):
    """Tracks species that have been confirmed/identified"""
    
    IDENTIFICATION_METHOD = [
        ('auto', 'Automatic'),
        ('manual', 'Manual'),
        ('vote', 'Voting System'),
        ('thermo', 'Thermo Library Match'),
        ('formula', 'Formula Match'),
    ]
    
    import_job = models.ForeignKey(
        ImportJob, 
        on_delete=models.CASCADE, 
        related_name='identified_species_set'
    )
    chemkin_label = models.CharField(max_length=255, db_index=True)
    chemkin_formula = models.CharField(max_length=100, blank=True)
    
    # Matched RMG species
    rmg_species_label = models.CharField(max_length=255)
    rmg_species_smiles = models.TextField()
    rmg_species_index = models.IntegerField(null=True, blank=True)
    
    # Identification metadata
    identification_method = models.CharField(
        max_length=50,
        choices=IDENTIFICATION_METHOD,
        default='auto'
    )
    identified_by = models.CharField(
        max_length=255, 
        null=True, 
        blank=True,
        help_text="Username who confirmed the match"
    )
    enthalpy_discrepancy = models.FloatField(
        null=True,
        blank=True,
        help_text="Enthalpy difference in kJ/mol at 298K"
    )
    notes = models.TextField(blank=True)
    
    identified_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'identified_species'
        unique_together = [['import_job', 'chemkin_label']]
        indexes = [
            models.Index(fields=['import_job', 'chemkin_label']),
            models.Index(fields=['import_job', 'identification_method']),
        ]
    
    def __str__(self):
        return f"{self.chemkin_label} = {self.rmg_species_label}"


class BlockedMatch(models.Model):
    """Tracks matches that have been manually blocked/rejected"""
    
    import_job = models.ForeignKey(
        ImportJob, 
        on_delete=models.CASCADE, 
        related_name='blocked_matches'
    )
    chemkin_label = models.CharField(max_length=255, db_index=True)
    rmg_species_label = models.CharField(max_length=255)
    rmg_species_smiles = models.TextField()
    rmg_species_index = models.IntegerField(null=True, blank=True)
    
    blocked_by = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Username who blocked this match"
    )
    reason = models.TextField(blank=True)
    blocked_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'blocked_matches'
        unique_together = [['import_job', 'chemkin_label', 'rmg_species_index']]
        indexes = [
            models.Index(fields=['import_job', 'chemkin_label']),
        ]
    
    def __str__(self):
        return f"Blocked: {self.chemkin_label} ≠ {self.rmg_species_label}"
