"""
ChemKED Database Forms

Multi-step forms for creating and editing ChemKED datasets.
Inspired by ChemKED-gui structure with Django form handling.
"""

from django import forms
from django.forms import formset_factory, inlineformset_factory
from django.core.validators import MinValueValidator

from .models import (
    ExperimentDataset,
    ExperimentDatapoint,
    IgnitionDelayDatapoint,
    FlameSpeedDatapoint,
    CommonProperties,
    Composition,
    CompositionSpecies,
    Apparatus,
    FileAuthor,
    ReferenceAuthor,
    ApparatusKind,
    ExperimentType,
    CompositionKind,
    IgnitionTarget,
    IgnitionType,
    UncertaintyType,
)


# =============================================================================
# File Metadata Forms
# =============================================================================

class FileAuthorForm(forms.Form):
    """Form for a single file author."""
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Author name'
        })
    )
    orcid = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'ORCID (e.g., 0000-0003-4425-7097)'
        })
    )


FileAuthorFormSet = formset_factory(FileAuthorForm, extra=1, min_num=1, validate_min=True)


class FileMetadataForm(forms.Form):
    """Form for ChemKED file metadata."""
    file_version = forms.IntegerField(
        initial=0,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'File version (e.g., 0)'
        })
    )
    chemked_version = forms.CharField(
        max_length=20,
        initial='0.4.1',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'ChemKED version'
        })
    )


# =============================================================================
# Reference Forms
# =============================================================================

class ReferenceAuthorForm(forms.Form):
    """Form for a single reference/paper author."""
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Author name'
        })
    )
    orcid = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'ORCID (optional)'
        })
    )


ReferenceAuthorFormSet = formset_factory(ReferenceAuthorForm, extra=1, min_num=1, validate_min=True)


class ReferenceForm(forms.Form):
    """Form for literature reference information."""
    doi = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'DOI (e.g., 10.1016/j.combustflame.2004.08.015)'
        })
    )
    journal = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Journal name'
        })
    )
    year = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Publication year'
        })
    )
    volume = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Volume number'
        })
    )
    pages = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Page range (e.g., 300-311)'
        })
    )
    detail = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Additional details about data source'
        })
    )


# =============================================================================
# Experiment & Apparatus Forms
# =============================================================================

class ExperimentForm(forms.Form):
    """Form for experiment type and apparatus."""
    experiment_type = forms.ChoiceField(
        choices=ExperimentType.choices,
        initial=ExperimentType.IGNITION_DELAY,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    apparatus_kind = forms.ChoiceField(
        choices=ApparatusKind.choices,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    apparatus_institution = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Institution (e.g., Stanford University)'
        })
    )
    apparatus_facility = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Facility name (e.g., low pressure shock tube)'
        })
    )


# =============================================================================
# Common Properties Forms
# =============================================================================

class IgnitionInfoForm(forms.Form):
    """Form for ignition detection parameters."""
    ignition_target = forms.ChoiceField(
        choices=[('', '-- Select --')] + list(IgnitionTarget.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    ignition_type = forms.ChoiceField(
        choices=[('', '-- Select --')] + list(IgnitionType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class CompositionSpeciesForm(forms.Form):
    """Form for a single species in composition."""
    species_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Species name (e.g., nC7H16)'
        })
    )
    inchi = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'InChI (e.g., 1S/C7H16/c1-3-5-7-6-4-2/h3-7H2,1-2H3)'
        })
    )
    smiles = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'SMILES (optional)'
        })
    )
    amount = forms.FloatField(
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Amount (e.g., 0.01874)',
            'step': 'any'
        })
    )


CompositionSpeciesFormSet = formset_factory(
    CompositionSpeciesForm, extra=1, min_num=1, validate_min=True
)


class CommonPropertiesForm(forms.Form):
    """Form for properties common to all datapoints."""
    composition_kind = forms.ChoiceField(
        choices=CompositionKind.choices,
        initial=CompositionKind.MOLE_FRACTION,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    # Common pressure (optional - if same for all datapoints)
    common_pressure = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Common pressure with units (e.g., 1.5 bar) - leave empty if varies'
        })
    )
    # Pressure rise rate (for shock tubes)
    pressure_rise = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Pressure rise rate (e.g., 0.03 1/ms) - optional'
        })
    )


# =============================================================================
# Datapoint Forms
# =============================================================================

class DatapointForm(forms.Form):
    """Form for a single experimental datapoint."""
    temperature = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Temperature with units (e.g., 1249 K)'
        })
    )
    temperature_uncertainty = forms.FloatField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Uncertainty value',
            'step': 'any'
        })
    )
    temperature_uncertainty_type = forms.ChoiceField(
        choices=[('', '-- None --')] + list(UncertaintyType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    pressure = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Pressure with units (e.g., 1.97 bar)'
        })
    )
    pressure_uncertainty = forms.FloatField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Uncertainty value',
            'step': 'any'
        })
    )
    pressure_uncertainty_type = forms.ChoiceField(
        choices=[('', '-- None --')] + list(UncertaintyType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    equivalence_ratio = forms.FloatField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Equivalence ratio (e.g., 1.0)',
            'step': 'any'
        })
    )


DatapointFormSet = formset_factory(DatapointForm, extra=1, min_num=1, validate_min=True)


class IgnitionDelayForm(forms.Form):
    """Form for ignition delay specific data."""
    ignition_delay = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ignition delay with units (e.g., 529 us)'
        })
    )
    ignition_delay_uncertainty = forms.FloatField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Uncertainty value',
            'step': 'any'
        })
    )
    ignition_delay_uncertainty_type = forms.ChoiceField(
        choices=[('', '-- None --')] + list(UncertaintyType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    # Override ignition target/type per datapoint (usually inherits from common)
    ignition_target_override = forms.ChoiceField(
        choices=[('', '-- Use Common --')] + list(IgnitionTarget.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    ignition_type_override = forms.ChoiceField(
        choices=[('', '-- Use Common --')] + list(IgnitionType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )


IgnitionDelayFormSet = formset_factory(IgnitionDelayForm, extra=1, min_num=1, validate_min=True)


class FlameSpeedForm(forms.Form):
    """Form for flame speed specific data."""
    laminar_flame_speed = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Flame speed with units (e.g., 0.35 m/s)'
        })
    )
    laminar_flame_speed_uncertainty = forms.FloatField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Uncertainty value',
            'step': 'any'
        })
    )
    laminar_flame_speed_uncertainty_type = forms.ChoiceField(
        choices=[('', '-- None --')] + list(UncertaintyType.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )


FlameSpeedFormSet = formset_factory(FlameSpeedForm, extra=1, min_num=1, validate_min=True)


# =============================================================================
# YAML Upload Form
# =============================================================================

class MultipleFileInput(forms.ClearableFileInput):
    """Custom widget that allows multiple file selection."""
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Custom field that handles multiple file uploads."""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = [single_file_clean(data, initial)]
        return result


class ChemKEDUploadForm(forms.Form):
    """Form for uploading existing ChemKED YAML or ReSpecTh XML files."""
    data_file = MultipleFileField(
        widget=MultipleFileInput(attrs={
            'class': 'form-control',
            'accept': '.yaml,.yml,.xml',
        }),
        help_text='Upload ChemKED YAML or ReSpecTh XML files (you can select multiple files)'
    )
    file_format = forms.ChoiceField(
        choices=[
            ('auto', 'Auto-detect'),
            ('yaml', 'ChemKED YAML'),
            ('xml', 'ReSpecTh XML'),
        ],
        initial='auto',
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='File format (auto-detects based on extension if not specified)'
    )
    validate_on_upload = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text='Validate the file against ChemKED schema before importing'
    )
    file_author = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Your name (optional, for ReSpecTh imports)'
        }),
        help_text='File author to add when importing ReSpecTh files'
    )
    file_author_orcid = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '0000-0000-0000-0000 (optional)'
        }),
        help_text='ORCID for the file author (optional)'
    )


class ReSpecThPreviewForm(forms.Form):
    """Form for previewing and editing ReSpecTh import details before confirmation."""
    dataset_name = forms.CharField(
        max_length=500,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Dataset name'
        }),
        help_text='Human-readable name for this dataset (auto-generated, but you can modify it)'
    )
    original_filename = forms.CharField(
        widget=forms.HiddenInput()
    )
    temp_file_path = forms.CharField(
        widget=forms.HiddenInput()
    )
    file_type = forms.CharField(
        widget=forms.HiddenInput()
    )
    file_author = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.HiddenInput()
    )
    file_author_orcid = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.HiddenInput()
    )


# =============================================================================
# Export Form
# =============================================================================

class ExportOptionsForm(forms.Form):
    """Form for export options when downloading datasets."""
    format_choice = forms.ChoiceField(
        choices=[
            ('yaml', 'ChemKED YAML'),
            ('xml', 'ReSpecTh XML'),
            ('csv', 'CSV (datapoints only)'),
        ],
        initial='yaml',
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'})
    )
    include_uncertainties = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
