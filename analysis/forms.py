"""
Analysis Forms
"""

from django import forms
from django.db.models import Q

from database.models import KineticModel
from chemked_database.models import ExperimentDataset, ExperimentType, ApparatusKind


class SimulationCreateForm(forms.Form):
    """Form for creating new simulation runs."""
    
    kinetic_model = forms.ModelChoiceField(
        queryset=KineticModel.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Kinetic Model"
    )
    
    datasets = forms.ModelMultipleChoiceField(
        queryset=ExperimentDataset.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        label="Datasets to Evaluate",
        required=True
    )
    
    experiment_type = forms.ChoiceField(
        choices=[('', 'All Types')] + list(ExperimentType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Filter by Experiment Type"
    )
    
    apparatus_kind = forms.ChoiceField(
        choices=[('', 'All Apparatus')] + list(ApparatusKind.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Filter by Apparatus"
    )
    
    skip_validation = forms.BooleanField(
        initial=True,
        required=False,
        label="Skip ChemKED validation",
        help_text="Skip schema validation for faster execution"
    )
    
    auto_execute = forms.BooleanField(
        initial=True,
        required=False,
        label="Start simulation automatically",
        help_text="Uncheck to create the run without starting it immediately"
    )
    
    def __init__(self, *args, **kwargs):
        # Allow pre-filtering datasets
        initial_model = kwargs.pop('initial_model', None)
        dataset_queryset = kwargs.pop('dataset_queryset', None)
        super().__init__(*args, **kwargs)

        if initial_model:
            self.fields['kinetic_model'].initial = initial_model

        # Filter datasets to ignition delay by default
        if dataset_queryset is None:
            dataset_queryset = ExperimentDataset.objects.filter(
                experiment_type='ignition delay'
            )
        self.fields['datasets'].queryset = dataset_queryset.order_by('chemked_file_path')


class DatasetFilterForm(forms.Form):
    """Form for filtering datasets in the selection interface."""
    
    experiment_type = forms.ChoiceField(
        choices=[('', 'All')] + list(ExperimentType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    apparatus_kind = forms.ChoiceField(
        choices=[('', 'All')] + list(ApparatusKind.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    
    fuel_species = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Search by fuel name, SMILES, or InChI...'
        })
    )
    
    min_temperature = forms.FloatField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Min T (K)'
        })
    )
    
    max_temperature = forms.FloatField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Max T (K)'
        })
    )


class SpeciesMappingForm(forms.Form):
    """Form for manually overriding species mapping."""
    
    dataset_species_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': True})
    )
    
    model_species_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    
    override_reason = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Reason for override...'
        })
    )
