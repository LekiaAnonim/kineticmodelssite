"""
ChemKED Database Views

Views for browsing and exploring experimental combustion data.
Designed for combustion research community and scientists.
"""

import os
import re
import tempfile
import logging
import json
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db import transaction
from django.db.models import Count, Avg, Min, Max, Q
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import TemplateView, DetailView, ListView, FormView
from django.views.generic.edit import CreateView
from django_filters.views import FilterView

from .models import (
    ExperimentDataset,
    ExperimentDatapoint,
    CommonProperties,
    Composition,
    CompositionSpecies,
    IgnitionDelayDatapoint,
    FlameSpeedDatapoint,
    RateCoefficientDatapoint,
    Apparatus,
    FileAuthor,
    ReferenceAuthor,
    ValueWithUnit,
    ExperimentType,
    ApparatusKind,
    CompositionKind,
)
from .filters import DatasetFilter, DatapointFilter
from .forms import (
    FileMetadataForm,
    FileAuthorFormSet,
    ReferenceForm,
    ReferenceAuthorFormSet,
    ExperimentForm,
    CommonPropertiesForm,
    IgnitionInfoForm,
    CompositionSpeciesFormSet,
    DatapointFormSet,
    IgnitionDelayFormSet,
    FlameSpeedFormSet,
    ChemKEDUploadForm,
    ExportOptionsForm,
)

logger = logging.getLogger(__name__)


class ChemKEDHomeView(TemplateView):
    """
    ChemKED database home page with overview statistics.
    """
    template_name = "chemked_database/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Overall statistics
        context["dataset_count"] = ExperimentDataset.objects.count()
        context["datapoint_count"] = ExperimentDatapoint.objects.count()
        context["species_count"] = CompositionSpecies.objects.values("species_name").distinct().count()

        # Experiment type breakdown
        context["experiment_types"] = (
            ExperimentDataset.objects
            .values("experiment_type")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # Apparatus breakdown
        context["apparatus_types"] = (
            ExperimentDataset.objects
            .filter(apparatus__isnull=False)
            .values("apparatus__kind")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        # Temperature and pressure ranges
        temp_stats = ExperimentDatapoint.objects.aggregate(
            min_temp=Min("temperature"),
            max_temp=Max("temperature"),
            avg_temp=Avg("temperature"),
        )
        context["temp_stats"] = temp_stats

        pressure_stats = ExperimentDatapoint.objects.aggregate(
            min_pressure=Min("pressure"),
            max_pressure=Max("pressure"),
        )
        context["pressure_stats"] = pressure_stats

        # Recent datasets
        context["recent_datasets"] = ExperimentDataset.objects.order_by("-created_at")[:5]

        # Top fuels (species appearing most frequently)
        context["top_fuels"] = (
            CompositionSpecies.objects
            .exclude(species_name__in=["O2", "N2", "Ar", "He", "CO2", "H2O"])
            .values("species_name")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )

        return context


class DatasetListView(FilterView):
    """
    Filterable list of ChemKED datasets.
    """
    model = ExperimentDataset
    filterset_class = DatasetFilter
    template_name = "chemked_database/dataset_list.html"
    context_object_name = "datasets"
    paginate_by = 25

    def get_queryset(self):
        return (
            ExperimentDataset.objects
            .select_related("apparatus")
            .prefetch_related("file_authors", "reference_authors")
            .annotate(datapoint_count=Count("datapoints", distinct=True))
            .order_by("-reference_year", "chemked_file_path")
        )

    def get_template_names(self):
        # Return partial template for AJAX requests
        if self.request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return ["chemked_database/partials/dataset_table.html"]
        return [self.template_name]


class DatasetDetailView(DetailView):
    """
    Detailed view of a single ChemKED dataset.
    """
    model = ExperimentDataset
    template_name = "chemked_database/dataset_detail.html"
    context_object_name = "dataset"

    def get_queryset(self):
        return (
            ExperimentDataset.objects
            .select_related("apparatus", "common_properties", "common_properties__composition")
            .prefetch_related(
                "file_authors",
                "reference_authors",
                "datapoints",
                "datapoints__ignition_delay",
                "datapoints__temperature_quantity",
                "datapoints__pressure_quantity",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dataset = self.object

        # Paginate datapoints
        datapoints = dataset.datapoints.select_related(
            "ignition_delay",
            "composition",
            "temperature_quantity",
            "pressure_quantity",
        ).order_by("temperature")

        page = self.request.GET.get("page", 1)
        paginator = Paginator(datapoints, 25)
        try:
            context["datapoints"] = paginator.page(page)
        except PageNotAnInteger:
            context["datapoints"] = paginator.page(1)
        except EmptyPage:
            context["datapoints"] = paginator.page(paginator.num_pages)

        # Common composition species
        if hasattr(dataset, "common_properties") and dataset.common_properties:
            common_props = dataset.common_properties
            context["common_properties"] = common_props
            if common_props.composition:
                context["common_species"] = common_props.composition.species.all()

        # Temperature and pressure ranges for this dataset
        context["temp_range"] = datapoints.aggregate(
            min_temp=Min("temperature"),
            max_temp=Max("temperature"),
        )
        context["pressure_range"] = datapoints.aggregate(
            min_pressure=Min("pressure"),
            max_pressure=Max("pressure"),
        )

        # Ignition delay range (if applicable)
        if dataset.experiment_type == ExperimentType.IGNITION_DELAY:
            ignition_stats = (
                IgnitionDelayDatapoint.objects
                .filter(datapoint__dataset=dataset, ignition_delay__isnull=False)
                .aggregate(
                    min_delay=Min("ignition_delay"),
                    max_delay=Max("ignition_delay"),
                )
            )
            context["ignition_stats"] = ignition_stats

        # Check if any datapoints have per-datapoint species composition data
        # (common for JSR, concentration profiles, etc.)
        context["has_species_data"] = datapoints.filter(
            composition__isnull=False
        ).exists()

        return context


class DatapointDetailView(DetailView):
    """
    Detailed view of a single experimental datapoint.
    """
    model = ExperimentDatapoint
    template_name = "chemked_database/datapoint_detail.html"
    context_object_name = "datapoint"

    def get_queryset(self):
        return (
            ExperimentDatapoint.objects
            .select_related(
                "dataset",
                "dataset__apparatus",
                "composition",
                "temperature_quantity",
                "pressure_quantity",
            )
            .prefetch_related(
                "time_histories",
                "composition__species",
                "composition__species__thermo_data",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        datapoint = self.object

        # Get composition species
        composition = datapoint.get_composition()
        if composition:
            context["composition"] = composition
            context["species_list"] = composition.species.select_related("thermo_data").all()

        # Get experiment-type extension
        if hasattr(datapoint, "ignition_delay"):
            context["ignition_delay"] = datapoint.ignition_delay
        if hasattr(datapoint, "flame_speed"):
            context["flame_speed"] = datapoint.flame_speed
        if hasattr(datapoint, "species_profile"):
            context["species_profile"] = datapoint.species_profile

        # RCM data
        if hasattr(datapoint, "rcm_data"):
            context["rcm_data"] = datapoint.rcm_data

        # Time histories
        context["time_histories"] = datapoint.time_histories.all()

        # Volume history
        if hasattr(datapoint, "volume_history"):
            context["volume_history"] = datapoint.volume_history

        return context


class SpeciesSearchView(ListView):
    """
    Search for species across all ChemKED compositions.
    """
    model = CompositionSpecies
    template_name = "chemked_database/species_search.html"
    context_object_name = "species_list"
    paginate_by = 50

    def get_queryset(self):
        queryset = (
            CompositionSpecies.objects
            .values("species_name", "inchi", "smiles")
            .annotate(occurrence_count=Count("id"))
            .order_by("-occurrence_count")
        )

        q = self.request.GET.get("q", "").strip()
        if q:
            queryset = queryset.filter(
                Q(species_name__icontains=q) |
                Q(inchi__icontains=q) |
                Q(smiles__icontains=q)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "")
        return context


class SpeciesDatapointsView(ListView):
    """
    Detailed view of a species with all its attributes and related datapoints.
    """
    model = ExperimentDatapoint
    template_name = "chemked_database/species_datapoints.html"
    context_object_name = "datapoints"
    paginate_by = 25

    def get_queryset(self):
        species_name = self.kwargs.get("species_name", "")
        return (
            ExperimentDatapoint.objects
            .filter(
                Q(composition__species__species_name=species_name) |
                Q(dataset__common_properties__composition__species__species_name=species_name)
            )
            .select_related("dataset", "ignition_delay", "temperature_quantity", "pressure_quantity")
            .distinct()
            .order_by("temperature")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        species_name = self.kwargs.get("species_name", "")
        context["species_name"] = species_name

        # Get species info from the first occurrence with complete data
        species_instance = (
            CompositionSpecies.objects
            .filter(species_name=species_name)
            .select_related("thermo_data", "database_species")
            .order_by("-inchi", "-smiles", "-atomic_composition")  # Prefer ones with identifiers
            .first()
        )
        context["species_info"] = species_instance

        # Get thermo data if available
        if species_instance:
            try:
                context["thermo_data"] = species_instance.thermo_data
            except CompositionSpecies.thermo_data.RelatedObjectDoesNotExist:
                context["thermo_data"] = None

            # Link to database Species if matched
            context["database_species"] = species_instance.database_species

        # Aggregate species statistics across all occurrences
        species_stats = (
            CompositionSpecies.objects
            .filter(species_name=species_name)
            .aggregate(
                occurrence_count=Count("id"),
                dataset_count=Count("composition__datapoints__dataset", distinct=True),
                avg_amount=Avg("amount"),
                min_amount=Min("amount"),
                max_amount=Max("amount"),
            )
        )
        context["species_stats"] = species_stats

        # Get all unique identifiers for this species
        identifiers = (
            CompositionSpecies.objects
            .filter(species_name=species_name)
            .filter(Q(inchi__gt="") | Q(smiles__gt=""))
            .values("inchi", "smiles")
            .distinct()
        )
        seen_identifiers = set()
        unique_identifiers = []
        for item in identifiers:
            inchi = (item.get("inchi") or "").strip()
            smiles = (item.get("smiles") or "").strip()
            key = (inchi, smiles)
            if key in seen_identifiers:
                continue
            seen_identifiers.add(key)
            unique_identifiers.append({"inchi": inchi, "smiles": smiles})
        context["all_identifiers"] = unique_identifiers

        primary_inchi = (species_instance.inchi or "").strip() if species_instance else ""
        primary_smiles = (species_instance.smiles or "").strip() if species_instance else ""
        primary_key = (primary_inchi, primary_smiles)
        alternative_identifiers = [
            ident for ident in unique_identifiers
            if (ident["inchi"], ident["smiles"]) != primary_key
        ]
        context["alternative_identifiers"] = alternative_identifiers

        # Temperature/pressure range for this species
        datapoints = self.get_queryset()
        context["temp_range"] = datapoints.aggregate(
            min_temp=Min("temperature"),
            max_temp=Max("temperature"),
        )
        context["pressure_range"] = datapoints.aggregate(
            min_pressure=Min("pressure"),
            max_pressure=Max("pressure"),
        )

        # Experiment type breakdown for this species
        context["experiment_types"] = (
            datapoints
            .values("dataset__experiment_type")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        return context


class ApparatusListView(ListView):
    """
    List of apparatus with associated datasets.
    """
    model = Apparatus
    template_name = "chemked_database/apparatus_list.html"
    context_object_name = "apparatus_list"

    def get_queryset(self):
        return (
            Apparatus.objects
            .annotate(dataset_count=Count("datasets"))
            .order_by("-dataset_count")
        )


# =============================================================================
# Dataset Creation Views (Multi-Step Wizard)
# =============================================================================

class DatasetCreateWizardView(TemplateView):
    """
    Multi-step wizard for creating a new ChemKED dataset.
    Similar to ChemKED-gui with tabs for different sections.
    """
    template_name = "chemked_database/dataset_create.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Initialize all forms with session data or empty
        session_data = self.request.session.get('chemked_wizard', {})
        
        # File metadata forms
        context['file_metadata_form'] = FileMetadataForm(
            initial=session_data.get('file_metadata', {})
        )
        context['file_author_formset'] = FileAuthorFormSet(
            initial=session_data.get('file_authors', [{'name': '', 'orcid': ''}]),
            prefix='file_authors'
        )
        
        # Reference forms
        context['reference_form'] = ReferenceForm(
            initial=session_data.get('reference', {})
        )
        context['reference_author_formset'] = ReferenceAuthorFormSet(
            initial=session_data.get('reference_authors', [{'name': '', 'orcid': ''}]),
            prefix='ref_authors'
        )
        
        # Experiment & apparatus form
        context['experiment_form'] = ExperimentForm(
            initial=session_data.get('experiment', {})
        )
        
        # Common properties
        context['common_properties_form'] = CommonPropertiesForm(
            initial=session_data.get('common_properties', {})
        )
        context['ignition_info_form'] = IgnitionInfoForm(
            initial=session_data.get('ignition_info', {})
        )
        context['composition_species_formset'] = CompositionSpeciesFormSet(
            initial=session_data.get('composition_species', []),
            prefix='species'
        )
        
        # Datapoints
        context['datapoint_formset'] = DatapointFormSet(
            initial=session_data.get('datapoints', []),
            prefix='datapoints'
        )
        context['ignition_delay_formset'] = IgnitionDelayFormSet(
            initial=session_data.get('ignition_delays', []),
            prefix='ignition_delays'
        )
        
        # Active tab (default to first)
        context['active_tab'] = self.request.GET.get('tab', 'metadata')
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Handle form submissions - save to session and validate."""
        action = request.POST.get('action', 'save')
        
        # Parse all forms
        file_metadata_form = FileMetadataForm(request.POST)
        file_author_formset = FileAuthorFormSet(request.POST, prefix='file_authors')
        reference_form = ReferenceForm(request.POST)
        reference_author_formset = ReferenceAuthorFormSet(request.POST, prefix='ref_authors')
        experiment_form = ExperimentForm(request.POST)
        common_properties_form = CommonPropertiesForm(request.POST)
        ignition_info_form = IgnitionInfoForm(request.POST)
        composition_species_formset = CompositionSpeciesFormSet(request.POST, prefix='species')
        datapoint_formset = DatapointFormSet(request.POST, prefix='datapoints')
        ignition_delay_formset = IgnitionDelayFormSet(request.POST, prefix='ignition_delays')
        
        # Collect data into session
        wizard_data = {
            'file_metadata': file_metadata_form.data if file_metadata_form.is_valid() else {},
            'file_authors': [f.cleaned_data for f in file_author_formset if f.is_valid() and f.cleaned_data],
            'reference': reference_form.cleaned_data if reference_form.is_valid() else {},
            'reference_authors': [f.cleaned_data for f in reference_author_formset if f.is_valid() and f.cleaned_data],
            'experiment': experiment_form.cleaned_data if experiment_form.is_valid() else {},
            'common_properties': common_properties_form.cleaned_data if common_properties_form.is_valid() else {},
            'ignition_info': ignition_info_form.cleaned_data if ignition_info_form.is_valid() else {},
            'composition_species': [f.cleaned_data for f in composition_species_formset if f.is_valid() and f.cleaned_data],
            'datapoints': [f.cleaned_data for f in datapoint_formset if f.is_valid() and f.cleaned_data],
            'ignition_delays': [f.cleaned_data for f in ignition_delay_formset if f.is_valid() and f.cleaned_data],
        }
        request.session['chemked_wizard'] = wizard_data
        
        if action == 'save_draft':
            messages.success(request, 'Draft saved to session.')
            return redirect(request.path)
        
        elif action == 'export_yaml':
            # Export as ChemKED YAML without saving to database
            return self._export_yaml(wizard_data)
        
        elif action == 'submit':
            # Validate all forms
            all_valid = all([
                file_metadata_form.is_valid(),
                file_author_formset.is_valid(),
                reference_form.is_valid(),
                reference_author_formset.is_valid(),
                experiment_form.is_valid(),
                common_properties_form.is_valid(),
                composition_species_formset.is_valid(),
                datapoint_formset.is_valid(),
            ])
            
            experiment_type = experiment_form.cleaned_data.get('experiment_type', '')
            if experiment_type == ExperimentType.IGNITION_DELAY:
                all_valid = all_valid and ignition_delay_formset.is_valid()
            
            if all_valid:
                try:
                    dataset = self._create_dataset(wizard_data)
                    # Clear session data
                    del request.session['chemked_wizard']
                    messages.success(request, f'Dataset created successfully with {dataset.datapoints.count()} datapoints.')
                    return redirect('chemked_database:dataset-detail', pk=dataset.pk)
                except Exception as e:
                    logger.exception("Error creating dataset")
                    messages.error(request, f'Error creating dataset: {str(e)}')
            else:
                messages.error(request, 'Please correct the errors below.')
        
        # Re-render with errors
        context = self.get_context_data(**kwargs)
        context.update({
            'file_metadata_form': file_metadata_form,
            'file_author_formset': file_author_formset,
            'reference_form': reference_form,
            'reference_author_formset': reference_author_formset,
            'experiment_form': experiment_form,
            'common_properties_form': common_properties_form,
            'ignition_info_form': ignition_info_form,
            'composition_species_formset': composition_species_formset,
            'datapoint_formset': datapoint_formset,
            'ignition_delay_formset': ignition_delay_formset,
        })
        return self.render_to_response(context)
    
    def _parse_value_with_unit(self, value_string):
        """
        Parse a string like '1249 K' or '529 us' into value and unit.
        Returns (value, unit) tuple.
        """
        if not value_string:
            return None, None
        
        value_string = value_string.strip()
        # Pattern: number followed by optional space and unit
        match = re.match(r'^([\d.eE+-]+)\s*(.*)$', value_string)
        if match:
            try:
                value = float(match.group(1))
                unit = match.group(2).strip() or 'dimensionless'
                return value, unit
            except ValueError:
                pass
        return None, value_string
    
    def _convert_to_si(self, value, unit):
        """
        Convert value to SI units. Returns (si_value, si_unit).
        Uses pint for unit conversion if available.
        """
        try:
            from pint import UnitRegistry
            ureg = UnitRegistry()
            quantity = value * ureg(unit)
            
            # Define SI base units for common quantities
            if quantity.dimensionality == {'[temperature]': 1}:
                si_quantity = quantity.to('kelvin')
            elif quantity.dimensionality == {'[pressure]': 1}:
                si_quantity = quantity.to('pascal')
            elif quantity.dimensionality == {'[time]': 1}:
                si_quantity = quantity.to('second')
            elif quantity.dimensionality == {'[length]': 1, '[time]': -1}:
                si_quantity = quantity.to('meter/second')
            else:
                si_quantity = quantity.to_base_units()
            
            return si_quantity.magnitude, str(si_quantity.units)
        except Exception as e:
            logger.warning(f"Unit conversion failed for {value} {unit}: {e}")
            return value, unit
    
    @transaction.atomic
    def _create_dataset(self, data):
        """Create ExperimentDataset and related models from wizard data."""
        
        # Get or create apparatus
        exp_data = data.get('experiment', {})
        apparatus, _ = Apparatus.objects.get_or_create(
            kind=exp_data.get('apparatus_kind', ApparatusKind.SHOCK_TUBE),
            institution=exp_data.get('apparatus_institution', ''),
            facility=exp_data.get('apparatus_facility', ''),
        )
        
        # Create dataset
        file_meta = data.get('file_metadata', {})
        ref_data = data.get('reference', {})
        
        dataset = ExperimentDataset.objects.create(
            chemked_file_path=f"user_created/{self.request.user.username if self.request.user.is_authenticated else 'anonymous'}/{ref_data.get('doi', 'no-doi')}",
            file_version=file_meta.get('file_version', 0),
            chemked_version=file_meta.get('chemked_version', '0.4.1'),
            experiment_type=exp_data.get('experiment_type', ExperimentType.IGNITION_DELAY),
            apparatus=apparatus,
            reference_doi=ref_data.get('doi', ''),
            reference_journal=ref_data.get('journal', ''),
            reference_year=ref_data.get('year'),
            reference_volume=ref_data.get('volume'),
            reference_pages=ref_data.get('pages', ''),
            reference_detail=ref_data.get('detail', ''),
        )
        
        # Add file authors
        for author_data in data.get('file_authors', []):
            if author_data.get('name'):
                author, _ = FileAuthor.objects.get_or_create(
                    name=author_data['name'],
                    orcid=author_data.get('orcid', ''),
                )
                dataset.file_authors.add(author)
        
        # Add reference authors
        for author_data in data.get('reference_authors', []):
            if author_data.get('name'):
                author, _ = ReferenceAuthor.objects.get_or_create(
                    name=author_data['name'],
                    orcid=author_data.get('orcid', ''),
                )
                dataset.reference_authors.add(author)
        
        # Create common composition
        common_props_data = data.get('common_properties', {})
        species_data = data.get('composition_species', [])
        
        common_composition = None
        if species_data:
            common_composition = Composition.objects.create(
                kind=common_props_data.get('composition_kind', CompositionKind.MOLE_FRACTION)
            )
            for sp in species_data:
                if sp.get('species_name') and sp.get('amount') is not None:
                    CompositionSpecies.objects.create(
                        composition=common_composition,
                        species_name=sp['species_name'],
                        inchi=sp.get('inchi', ''),
                        smiles=sp.get('smiles', ''),
                        amount=sp['amount'],
                    )
        
        # Create common properties
        ignition_data = data.get('ignition_info', {})
        common_pressure = None
        common_pressure_quantity = None
        if common_props_data.get('common_pressure'):
            val, unit = self._parse_value_with_unit(common_props_data['common_pressure'])
            if val is not None:
                si_val, si_unit = self._convert_to_si(val, unit)
                common_pressure = si_val
                common_pressure_quantity = ValueWithUnit.objects.create(
                    value=val, units=unit
                )
        
        common_properties = CommonProperties.objects.create(
            dataset=dataset,
            composition=common_composition,
            ignition_target=ignition_data.get('ignition_target', ''),
            ignition_type=ignition_data.get('ignition_type', ''),
            pressure=common_pressure,
            pressure_quantity=common_pressure_quantity,
        )
        
        # Create datapoints
        datapoints_data = data.get('datapoints', [])
        ignition_delays_data = data.get('ignition_delays', [])
        
        for idx, dp_data in enumerate(datapoints_data):
            # Parse temperature
            temp_val, temp_unit = self._parse_value_with_unit(dp_data.get('temperature', ''))
            si_temp, _ = self._convert_to_si(temp_val, temp_unit) if temp_val else (None, None)
            
            temp_quantity = None
            if temp_val is not None:
                temp_quantity = ValueWithUnit.objects.create(
                    value=temp_val,
                    units=temp_unit,
                    uncertainty_type=dp_data.get('temperature_uncertainty_type', ''),
                    uncertainty=dp_data.get('temperature_uncertainty'),
                )
            
            # Parse pressure
            press_val, press_unit = self._parse_value_with_unit(dp_data.get('pressure', ''))
            si_press, _ = self._convert_to_si(press_val, press_unit) if press_val else (None, None)
            
            press_quantity = None
            if press_val is not None:
                press_quantity = ValueWithUnit.objects.create(
                    value=press_val,
                    units=press_unit,
                    uncertainty_type=dp_data.get('pressure_uncertainty_type', ''),
                    uncertainty=dp_data.get('pressure_uncertainty'),
                )
            
            # Create datapoint
            datapoint = ExperimentDatapoint.objects.create(
                dataset=dataset,
                temperature=si_temp or 0,
                temperature_quantity=temp_quantity,
                temperature_uncertainty=dp_data.get('temperature_uncertainty'),
                temperature_uncertainty_type=dp_data.get('temperature_uncertainty_type', ''),
                pressure=si_press or 0,
                pressure_quantity=press_quantity,
                pressure_uncertainty=dp_data.get('pressure_uncertainty'),
                pressure_uncertainty_type=dp_data.get('pressure_uncertainty_type', ''),
                equivalence_ratio=dp_data.get('equivalence_ratio'),
                composition=common_composition,  # Use common composition
            )
            
            # Create experiment-type specific extension
            if dataset.experiment_type == ExperimentType.IGNITION_DELAY and idx < len(ignition_delays_data):
                ign_data = ignition_delays_data[idx]
                
                # Parse ignition delay
                ign_val, ign_unit = self._parse_value_with_unit(ign_data.get('ignition_delay', ''))
                si_ign, _ = self._convert_to_si(ign_val, ign_unit) if ign_val else (None, None)
                
                ign_quantity = None
                if ign_val is not None:
                    ign_quantity = ValueWithUnit.objects.create(
                        value=ign_val,
                        units=ign_unit,
                        uncertainty_type=ign_data.get('ignition_delay_uncertainty_type', ''),
                        uncertainty=ign_data.get('ignition_delay_uncertainty'),
                    )
                
                IgnitionDelayDatapoint.objects.create(
                    datapoint=datapoint,
                    ignition_delay=si_ign,
                    ignition_delay_quantity=ign_quantity,
                    ignition_delay_uncertainty=ign_data.get('ignition_delay_uncertainty'),
                    ignition_delay_uncertainty_type=ign_data.get('ignition_delay_uncertainty_type', ''),
                    ignition_target=ign_data.get('ignition_target_override', ''),
                    ignition_type=ign_data.get('ignition_type_override', ''),
                )
        
        return dataset
    
    def _export_yaml(self, data):
        """Generate ChemKED YAML from wizard data and return as file download."""
        try:
            from pyked import chemked
            
            # Build the ChemKED dictionary
            chemked_dict = self._build_chemked_dict(data)
            
            # Create ChemKED object and write to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                temp_path = f.name
            
            try:
                ck = chemked.ChemKED(dict_input=chemked_dict, skip_validation=False)
                ck.write_file(temp_path, overwrite=True)
                
                with open(temp_path, 'r') as f:
                    yaml_content = f.read()
                
                response = HttpResponse(yaml_content, content_type='application/x-yaml')
                response['Content-Disposition'] = 'attachment; filename="chemked_dataset.yaml"'
                return response
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    
        except ImportError:
            messages.error(self.request, 'PyKED is not installed. Cannot export YAML.')
            return redirect(self.request.path)
        except Exception as e:
            logger.exception("Error exporting YAML")
            messages.error(self.request, f'Error exporting YAML: {str(e)}')
            return redirect(self.request.path)
    
    def _build_chemked_dict(self, data):
        """Build a ChemKED-compatible dictionary from wizard data."""
        file_meta = data.get('file_metadata', {})
        ref_data = data.get('reference', {})
        exp_data = data.get('experiment', {})
        common_props = data.get('common_properties', {})
        ignition_info = data.get('ignition_info', {})
        species_data = data.get('composition_species', [])
        datapoints_data = data.get('datapoints', [])
        ignition_delays = data.get('ignition_delays', [])
        
        # File authors
        file_authors = []
        for auth in data.get('file_authors', []):
            author_dict = {'name': auth.get('name', '')}
            if auth.get('orcid'):
                author_dict['ORCID'] = auth['orcid']
            file_authors.append(author_dict)
        
        # Reference authors
        ref_authors = []
        for auth in data.get('reference_authors', []):
            author_dict = {'name': auth.get('name', '')}
            if auth.get('orcid'):
                author_dict['ORCID'] = auth['orcid']
            ref_authors.append(author_dict)
        
        # Build composition
        composition = {
            'kind': common_props.get('composition_kind', 'mole fraction'),
            'species': []
        }
        for sp in species_data:
            species_entry = {
                'species-name': sp.get('species_name', ''),
                'amount': [float(sp.get('amount', 0))]
            }
            if sp.get('inchi'):
                species_entry['InChI'] = sp['inchi']
            composition['species'].append(species_entry)
        
        # Build ignition type
        ignition_type = {}
        if ignition_info.get('ignition_target'):
            ignition_type['target'] = ignition_info['ignition_target']
        if ignition_info.get('ignition_type'):
            ignition_type['type'] = ignition_info['ignition_type']
        
        # Build datapoints
        datapoints = []
        for idx, dp in enumerate(datapoints_data):
            dp_dict = {}
            
            # Temperature
            if dp.get('temperature'):
                dp_dict['temperature'] = [dp['temperature']]
                if dp.get('temperature_uncertainty') and dp.get('temperature_uncertainty_type'):
                    dp_dict['temperature'].append({
                        'uncertainty-type': dp['temperature_uncertainty_type'],
                        'uncertainty': dp['temperature_uncertainty']
                    })
            
            # Pressure
            if dp.get('pressure'):
                dp_dict['pressure'] = [dp['pressure']]
                if dp.get('pressure_uncertainty') and dp.get('pressure_uncertainty_type'):
                    dp_dict['pressure'].append({
                        'uncertainty-type': dp['pressure_uncertainty_type'],
                        'uncertainty': dp['pressure_uncertainty']
                    })
            
            # Equivalence ratio
            if dp.get('equivalence_ratio'):
                dp_dict['equivalence-ratio'] = dp['equivalence_ratio']
            
            # Composition (reference to common)
            dp_dict['composition'] = composition
            
            # Ignition type (reference to common)
            if ignition_type:
                dp_dict['ignition-type'] = ignition_type
            
            # Ignition delay (if applicable)
            if idx < len(ignition_delays):
                ign = ignition_delays[idx]
                if ign.get('ignition_delay'):
                    dp_dict['ignition-delay'] = [ign['ignition_delay']]
                    if ign.get('ignition_delay_uncertainty') and ign.get('ignition_delay_uncertainty_type'):
                        dp_dict['ignition-delay'].append({
                            'uncertainty-type': ign['ignition_delay_uncertainty_type'],
                            'uncertainty': ign['ignition_delay_uncertainty']
                        })
            
            datapoints.append(dp_dict)
        
        # Build final dictionary
        chemked_dict = {
            'file-version': int(file_meta.get('file_version', 0)),
            'chemked-version': file_meta.get('chemked_version', '0.4.1'),
            'file-authors': file_authors,
            'reference': {
                'doi': ref_data.get('doi', ''),
                'authors': ref_authors,
                'journal': ref_data.get('journal', ''),
                'year': int(ref_data.get('year', 2020)),
                'volume': int(ref_data.get('volume', 1)) if ref_data.get('volume') else None,
                'pages': ref_data.get('pages', ''),
                'detail': ref_data.get('detail', ''),
            },
            'experiment-type': exp_data.get('experiment_type', 'ignition delay'),
            'apparatus': {
                'kind': exp_data.get('apparatus_kind', 'shock tube'),
                'institution': exp_data.get('apparatus_institution', ''),
                'facility': exp_data.get('apparatus_facility', ''),
            },
            'common-properties': {
                'composition': composition,
                'ignition-type': ignition_type,
            },
            'datapoints': datapoints,
        }
        
        # Remove empty values
        if not chemked_dict['reference'].get('volume'):
            del chemked_dict['reference']['volume']
        
        return chemked_dict


class DatasetUploadView(FormView):
    """
    View for uploading existing ChemKED YAML or ReSpecTh XML files.
    Parses the file and imports into the database.
    Supports both ReSpecTh v1.x (via PyKED) and v2.x (via custom converter).
    
    For ReSpecTh files, shows a preview step where user can edit the dataset name.
    """
    template_name = "chemked_database/dataset_upload.html"
    form_class = ChemKEDUploadForm
    success_url = reverse_lazy('chemked_database:dataset-list')
    
    def get(self, request, *args, **kwargs):
        """Handle GET request - check if we're in preview mode or cancelling."""
        # Handle cancel - clean up temp file and session
        if 'cancel' in request.GET:
            return self._cancel_preview(request)
        
        if 'preview' in request.GET and request.session.get('respecth_preview'):
            return self._show_preview(request)
        return super().get(request, *args, **kwargs)
    
    def _cancel_preview(self, request):
        """Cancel the preview and clean up temp file."""
        preview_data = request.session.get('respecth_preview', {})
        temp_file_path = preview_data.get('temp_file_path', '')
        
        # Clean up temp file
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        
        # Clear session data
        if 'respecth_preview' in request.session:
            del request.session['respecth_preview']
        
        messages.info(request, 'Import cancelled.')
        return redirect('chemked_database:dataset-upload')
    
    def post(self, request, *args, **kwargs):
        """Handle POST - either initial upload or preview confirmation."""
        if 'confirm_import' in request.POST:
            return self._confirm_import(request)
        return super().post(request, *args, **kwargs)
    
    def _show_preview(self, request):
        """Show the preview page with editable dataset name."""
        from .forms import ReSpecThPreviewForm
        
        preview_data = request.session.get('respecth_preview', {})
        form = ReSpecThPreviewForm(initial=preview_data)
        
        context = self.get_context_data()
        context['preview_mode'] = True
        context['preview_form'] = form
        context['preview_data'] = preview_data
        
        return self.render_to_response(context)
    
    def _confirm_import(self, request):
        """Confirm the import after preview."""
        from .forms import ReSpecThPreviewForm
        
        form = ReSpecThPreviewForm(request.POST)
        if not form.is_valid():
            messages.error(request, 'Invalid form data. Please try again.')
            return redirect('chemked_database:dataset-upload')
        
        dataset_name = form.cleaned_data['dataset_name']
        temp_file_path = form.cleaned_data['temp_file_path']
        file_type = form.cleaned_data['file_type']
        original_filename = form.cleaned_data['original_filename']
        file_author = form.cleaned_data.get('file_author', '')
        
        # Clear session data
        if 'respecth_preview' in request.session:
            del request.session['respecth_preview']
        
        # Check if temp file still exists
        if not os.path.exists(temp_file_path):
            messages.error(request, 'Temporary file expired. Please upload the file again.')
            return redirect('chemked_database:dataset-upload')
        
        try:
            from .respecth_v2_converter import parse_respecth_v2
            data = parse_respecth_v2(temp_file_path)
            
            # Check for duplicate based on file_doi
            if data.file_doi:
                existing = ExperimentDataset.objects.filter(file_doi=data.file_doi).first()
                if existing:
                    formatted = self._format_import_error(
                        f'Dataset with DOI "{data.file_doi}" already exists as '
                        f'"{existing.chemked_file_path}" (ID: {existing.pk}). '
                        'Skipping duplicate upload.'
                    )
                    messages.warning(request, formatted['message'])
                    return redirect('chemked_database:dataset-upload')
            
            # Import with the user-specified name
            if data.file_type == 'kdetermination':
                dataset = self._import_kdetermination(data, original_filename, file_author, custom_name=dataset_name)
            elif data.file_type == 'tdetermination':
                dataset = self._import_tdetermination(data, original_filename, file_author, custom_name=dataset_name)
            else:
                dataset = self._import_respecth_experiment(data, original_filename, file_author, custom_name=dataset_name)
            
            messages.success(
                request,
                f'Successfully imported "{original_filename}" as "{dataset.chemked_file_path}" '
                f'with {dataset.datapoints.count()} datapoints.'
            )
            
            return redirect('chemked_database:dataset-detail', pk=dataset.pk)
            
        except Exception as e:
            logger.exception("Error during confirmed import")
            formatted = self._format_import_error(str(e))
            level = messages.warning if formatted['kind'] == 'skipped' else messages.error
            level(request, formatted['message'])
        finally:
            # Clean up temp file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
        
        return redirect('chemked_database:dataset-upload')
    
    def form_valid(self, form):
        # Check if this is an AJAX request (for SSE-based progress)
        is_ajax = self.request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Get all uploaded files (supports multiple file upload)
        data_files = self.request.FILES.getlist('data_file')
        file_format = form.cleaned_data.get('file_format', 'auto')
        validate = form.cleaned_data.get('validate_on_upload', True)
        file_author = form.cleaned_data.get('file_author', '')
        file_author_orcid = form.cleaned_data.get('file_author_orcid', '')

        if not data_files:
            if is_ajax:
                return JsonResponse(
                    {
                        'success': False,
                        'batch_id': None,
                        'messages': [
                            {
                                'level': 'error',
                                'text': 'No files were received by the server. Please try selecting the files again.'
                            }
                        ]
                    },
                    status=400,
                )
            return self.form_invalid(form)
        
        # If only one file and it's XML (not AJAX), use the preview flow
        if len(data_files) == 1 and not is_ajax:
            return self._process_single_file(
                data_files[0], file_format, validate, file_author, file_author_orcid, form
            )
        
        # For AJAX requests: Save files to temp storage and return batch_id for SSE processing
        if is_ajax:
            return self._prepare_batch_for_sse(data_files, file_format, validate, file_author, file_author_orcid)
        
        # Non-AJAX multi-file: process synchronously
        successful_imports = []
        skipped_imports = []
        failed_imports = []
        
        for data_file in data_files:
            result = self._process_file_batch(
                data_file, file_format, validate, file_author, file_author_orcid
            )
            if result['success']:
                successful_imports.append(result)
            else:
                if result.get('error_kind') == 'skipped':
                    skipped_imports.append(result)
                else:
                    failed_imports.append(result)
        
        # Non-AJAX: use messages framework
        if successful_imports:
            total_datapoints = sum(r.get('datapoints', 0) for r in successful_imports)
            messages.success(
                self.request,
                f'Successfully imported {len(successful_imports)} dataset(s) with {total_datapoints} total datapoints.'
            )
        
        if failed_imports:
            details = "\n".join(
                f'- {fail["filename"]}: {fail["error"]}' for fail in failed_imports
            )
            messages.error(
                self.request,
                f'Failed to import {len(failed_imports)} file(s):\n{details}'
            )

        if skipped_imports:
            details = "\n".join(
                f'- {skip["filename"]}: {skip["error"]}' for skip in skipped_imports
            )
            messages.warning(
                self.request,
                f'Skipped {len(skipped_imports)} file(s):\n{details}'
            )
        
        if successful_imports:
            return redirect('chemked_database:dataset-list')
        return self.form_invalid(form)
    
    def _prepare_batch_for_sse(self, data_files, file_format, validate, file_author, file_author_orcid):
        """
        Save uploaded files to temp storage and return batch_id for SSE processing.
        This allows the client to track real-time progress via Server-Sent Events.
        """
        batch_id = str(uuid.uuid4())
        temp_files = []
        
        for data_file in data_files:
            filename = data_file.name.lower()
            suffix = '.xml' if filename.endswith('.xml') else '.yaml'
            
            try:
                with tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False) as f:
                    for chunk in data_file.chunks():
                        f.write(chunk)
                    temp_files.append({
                        'temp_path': f.name,
                        'original_name': data_file.name
                    })
            except Exception as e:
                # Clean up any already-saved files
                for tf in temp_files:
                    if os.path.exists(tf['temp_path']):
                        os.unlink(tf['temp_path'])
                return JsonResponse({
                    'success': False,
                    'batch_id': None,
                    'messages': [{
                        'level': 'error',
                        'text': f'Failed to save file {data_file.name}: {str(e)}'
                    }]
                }, status=500)
        
        # Store batch data in session
        batch_key = f'upload_batch_{batch_id}'
        self.request.session[batch_key] = {
            'temp_files': temp_files,
            'file_format': file_format,
            'validate': validate,
            'file_author': file_author,
            'file_author_orcid': file_author_orcid,
        }
        self.request.session.modified = True
        
        # Return batch_id for SSE connection
        return JsonResponse({
            'success': True,
            'batch_id': batch_id,
            'total_files': len(temp_files),
            'sse_url': reverse('chemked_database:dataset-process') + f'?batch_id={batch_id}'
        })
    
    def _process_file_batch(self, data_file, file_format, validate, file_author, file_author_orcid):
        """Process a single file in batch mode (no preview)."""
        filename = data_file.name.lower()
        original_name = data_file.name
        
        # Determine file format
        actual_format = file_format
        if actual_format == 'auto':
            if filename.endswith('.xml'):
                actual_format = 'xml'
            else:
                actual_format = 'yaml'
        
        suffix = '.xml' if actual_format == 'xml' else '.yaml'
        
        # Save uploaded file temporarily
        try:
            with tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False) as f:
                for chunk in data_file.chunks():
                    f.write(chunk)
                temp_path = f.name
        except Exception as e:
            return {'success': False, 'filename': original_name, 'error': str(e)}
        
        try:
            if actual_format == 'xml':
                # Import ReSpecTh XML directly (no preview in batch mode)
                dataset = self._import_respecth_xml_batch(temp_path, original_name, file_author, file_author_orcid)
                return {
                    'success': True,
                    'filename': original_name,
                    'dataset_id': dataset.pk,
                    'dataset_name': dataset.chemked_file_path,
                    'datapoints': dataset.datapoints.count()
                }
            else:
                # Parse ChemKED YAML
                from pyked import chemked
                ck = chemked.ChemKED(yaml_file=temp_path, skip_validation=not validate)
                dataset = self._import_chemked(ck, original_name)
                return {
                    'success': True,
                    'filename': original_name,
                    'dataset_id': dataset.pk,
                    'dataset_name': dataset.chemked_file_path,
                    'datapoints': dataset.datapoints.count()
                }
        except Exception as e:
            logger.exception(f"Error importing file {original_name}")
            formatted = self._format_import_error(str(e))
            return {
                'success': False,
                'filename': original_name,
                'error': formatted['message'],
                'error_kind': formatted['kind']
            }
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def _import_respecth_xml_batch(self, temp_path, original_filename, file_author, file_author_orcid):
        """Import ReSpecTh XML in batch mode (no preview)."""
        from .respecth_v2_converter import parse_respecth_v2
        
        data = parse_respecth_v2(temp_path)
        
        # Check for duplicate based on file_doi
        if data.file_doi:
            existing = ExperimentDataset.objects.filter(file_doi=data.file_doi).first()
            if existing:
                raise ValueError(
                    f'Dataset with DOI "{data.file_doi}" already exists as "{existing.chemked_file_path}" (ID: {existing.pk}). '
                    'Skipping duplicate upload.'
                )
        
        # Also check by reference DOI + similar composition (fallback for files without file_doi)
        if not data.file_doi and data.reference and data.reference.doi:
            # Check if we already have a dataset with the same reference DOI and similar datapoint count
            similar = ExperimentDataset.objects.filter(
                reference__doi=data.reference.doi
            )
            if data.datapoints:
                similar = similar.annotate(dp_count=Count('datapoints')).filter(
                    dp_count=len(data.datapoints)
                )
            existing = similar.first()
            if existing:
                raise ValueError(
                    f'Possible duplicate: Dataset with reference DOI "{data.reference.doi}" '
                    f'and {len(data.datapoints)} datapoints already exists as "{existing.chemked_file_path}" (ID: {existing.pk}). '
                    'Skipping duplicate upload.'
                )
        
        if data.file_type == 'kdetermination':
            return self._import_kdetermination(data, original_filename, file_author)
        elif data.file_type == 'tdetermination':
            return self._import_tdetermination(data, original_filename, file_author)
        else:
            return self._import_respecth_experiment(data, original_filename, file_author)

    def _format_import_error(self, error_msg):
        """Normalize import errors into user-friendly messages."""
        message = str(error_msg or '').strip()
        lower = message.lower()

        if 'skipping duplicate upload' in lower or ('duplicate upload' in lower and 'already exists' in lower):
            clean = message.replace('Skipping duplicate upload.', '').strip()
            if clean:
                return {'kind': 'skipped', 'message': f'Duplicate upload. {clean}'}
            return {'kind': 'skipped', 'message': 'Duplicate upload skipped.'}

        if 'unsupported experiment type' in lower:
            return {
                'kind': 'error',
                'message': f'Unsupported experiment type. {message}'
            }

        if 'value too long for type character varying(100)' in lower:
            return {
                'kind': 'error',
                'message': (
                    'Metadata text is too long for a 100-character field (likely File Author). '
                    'Please shorten the File Author value or contact the admin.'
                )
            }

        if 'chemked_unique_species_per_datapoint' in lower or 'duplicate key value violates unique constraint' in lower:
            return {
                'kind': 'error',
                'message': (
                    'Duplicate species entry in composition. '
                    'The XML file contains the same species listed multiple times in one composition. '
                    'Please check the source file or contact the admin.'
                )
            }

        return {'kind': 'error', 'message': message}
    
    def _process_single_file(self, data_file, file_format, validate, file_author, file_author_orcid, form):
        """Process a single file upload (supports preview for XML)."""
        # Determine file format
        filename = data_file.name.lower()
        if file_format == 'auto':
            if filename.endswith('.xml'):
                file_format = 'xml'
            else:
                file_format = 'yaml'
        
        # Determine suffix based on format
        suffix = '.xml' if file_format == 'xml' else '.yaml'
        
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False) as f:
            for chunk in data_file.chunks():
                f.write(chunk)
            temp_path = f.name
        
        try:
            if file_format == 'xml':
                # Try to detect ReSpecTh version
                result = self._import_respecth_xml(temp_path, data_file.name, file_author, file_author_orcid)
                return result
            else:
                # Parse ChemKED YAML
                try:
                    from pyked import chemked
                    ck = chemked.ChemKED(yaml_file=temp_path, skip_validation=not validate)
                    file_type_label = "ChemKED YAML"
                    
                    # Import into database
                    dataset = self._import_chemked(ck, data_file.name)
                    
                    messages.success(
                        self.request,
                        f'Successfully imported {file_type_label} "{data_file.name}" with {dataset.datapoints.count()} datapoints.'
                    )
                    return redirect('chemked_database:dataset-detail', pk=dataset.pk)
                except ImportError:
                    messages.error(self.request, 'PyKED is not installed. Cannot import YAML files.')
                    return self.form_invalid(form)
                    
        except ValueError as e:
            error_msg = str(e)
            # Provide more user-friendly messages for common errors
            if 'preferredKey' in error_msg or 'bibliographyLink' in error_msg:
                messages.error(
                    self.request, 
                    f'ReSpecTh XML Error: The file is missing required bibliography information. '
                    f'Please ensure the <bibliographyLink> element has "preferredKey" and "doi" attributes. '
                    f'Technical details: {error_msg}'
                )
            elif 'experimentType' in error_msg:
                messages.error(
                    self.request,
                    f'ReSpecTh XML Error: Invalid or missing experiment type. '
                    f'Only "Ignition delay measurement" is currently supported. '
                    f'Technical details: {error_msg}'
                )
            else:
                messages.error(self.request, f'Validation error: {error_msg}')
        except NotImplementedError as e:
            messages.error(self.request, f'Not supported: {str(e)}')
        except KeyError as e:
            messages.error(
                self.request, 
                f'Missing required field in file: {str(e)}. '
                f'Please check that all required elements are present in your file.'
            )
        except Exception as e:
            error_msg = str(e)
            logger.exception("Error importing file")
            # Provide context-specific messages for ReSpecTh errors
            if 'preferredKey' in error_msg or 'bibliographyLink' in error_msg:
                messages.error(
                    self.request,
                    f'ReSpecTh XML Error: Missing bibliography reference. '
                    f'The file requires a <bibliographyLink> element with preferredKey and doi attributes. '
                    f'Details: {error_msg}'
                )
            elif 'attribute' in error_msg.lower() and 'missing' in error_msg.lower():
                messages.error(
                    self.request,
                    f'ReSpecTh XML Error: A required XML attribute is missing. {error_msg}'
                )
            else:
                messages.error(self.request, f'Error importing file: {error_msg}')
        finally:
            # Only clean up temp file if we're NOT showing a preview
            # The preview step will clean it up after confirmation/cancellation
            if not self.request.session.get('respecth_preview'):
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        
        return self.form_invalid(form)
    
    def _generate_readable_name(self, data, original_filename, file_type='experiment'):
        """
        Generate a human-readable dataset name following ChemKED database conventions.
        
        Format: {FuelSpecies}/{FirstAuthor}_{Year}_{ApparatusAbbrev}_{ID}.yaml
        
        Examples from ChemKED-database:
        - n-pentane_NOx/Fuller_2021_RCM_1004.yaml
        - n-heptane/Gauthier 2004/st_gauthier_2004-1.yaml
        
        For our flat naming, we use:
        - FuelSpecies_Author_Year_ApparatusAbbrev_ID
        
        Examples:
        - n-pentane_Fuller_2021_RCM_1004
        - n-heptane_Gauthier_2004_ST_1
        """
        import re
        
        parts = []
        
        # 1. Get fuel/parent species from composition
        fuel_species = self._extract_fuel_species(data)
        if fuel_species:
            parts.append(fuel_species)
        elif data.reaction and hasattr(data.reaction, 'preferred_key') and data.reaction.preferred_key:
            # For rate coefficient files, use simplified reaction
            reaction = data.reaction.preferred_key
            # Simplify reaction: "H + O2 = OH + O" -> "H+O2"
            reactants = reaction.split('=')[0].strip() if '=' in reaction else reaction
            species_part = reactants.replace(' + ', '+').replace(' ', '')
            if len(species_part) > 20:
                species_part = species_part[:20]
            parts.append(species_part)
        
        # 2. Get first author's last name
        author_name = None
        if data.reference and data.reference.authors:
            first_author = data.reference.authors[0].name
            # Extract last name (handle "First Last" and "Last, First" formats)
            if ',' in first_author:
                author_name = first_author.split(',')[0].strip()
            else:
                name_parts = first_author.split()
                author_name = name_parts[-1] if name_parts else None
            if author_name:
                # Clean up the last name (keep only alphanumeric)
                author_name = re.sub(r'[^\w]', '', author_name)
                parts.append(author_name)
        
        # 3. Get year
        year = None
        if data.reference and data.reference.year:
            year = str(data.reference.year)
            parts.append(year)
        
        # 4. Get apparatus abbreviation (following ChemKED convention)
        apparatus_abbrev = self._get_apparatus_abbreviation(data)
        if apparatus_abbrev:
            parts.append(apparatus_abbrev)
        
        # 5. Extract ID from original filename
        # e.g., "x00002001.xml" -> "2001", "Fuller_2021_RCM_1004.yaml" -> "1004"
        base_name = os.path.splitext(os.path.basename(original_filename))[0]
        file_id = None
        
        # Try to extract numeric ID from end of filename
        match = re.search(r'(\d+)$', base_name)
        if match:
            file_id = match.group(1).lstrip('0') or '0'  # Remove leading zeros but keep at least one digit
        else:
            # Use last 4 chars as fallback
            file_id = base_name[-4:] if len(base_name) > 4 else base_name
        
        if file_id:
            parts.append(file_id)
        
        # Join with underscores
        if parts:
            readable_name = '_'.join(parts)
        else:
            # Ultimate fallback: use original filename
            readable_name = base_name
        
        # Ensure uniqueness by checking database
        base_readable_name = readable_name
        counter = 1
        while ExperimentDataset.objects.filter(chemked_file_path=readable_name).exists():
            readable_name = f"{base_readable_name}_{counter}"
            counter += 1
        
        return readable_name
    
    def _get_apparatus_abbreviation(self, data):
        """
        Get standard apparatus abbreviation following ChemKED conventions.
        
        Standard abbreviations:
        - ST = Shock Tube
        - RCM = Rapid Compression Machine  
        - JSR = Jet-Stirred Reactor
        - FR = Flow Reactor
        - FL = Flame
        """
        apparatus_kind = None
        
        # Try to get apparatus kind from data
        if hasattr(data, 'apparatus') and data.apparatus:
            if hasattr(data.apparatus, 'kind') and data.apparatus.kind:
                apparatus_kind = data.apparatus.kind
        
        # Also check method field for rate coefficient data
        if not apparatus_kind and hasattr(data, 'method') and data.method:
            apparatus_kind = data.method
        
        if not apparatus_kind:
            return None
        
        kind_lower = apparatus_kind.lower()
        
        # Map to standard abbreviations
        if 'shock' in kind_lower or kind_lower == 'st':
            return 'ST'
        elif 'rcm' in kind_lower or 'rapid compression' in kind_lower:
            return 'RCM'
        elif 'jet' in kind_lower and 'stirred' in kind_lower:
            return 'JSR'
        elif 'stirred' in kind_lower:
            return 'SR'
        elif 'flow' in kind_lower:
            return 'FR'
        elif 'flame' in kind_lower:
            return 'FL'
        elif 'cbs' in kind_lower or 'ab initio' in kind_lower or 'calc' in kind_lower:
            return 'calc'
        else:
            # Return first 3 chars capitalized as fallback
            return re.sub(r'[^\w]', '', apparatus_kind)[:3].upper()
    
    def _extract_fuel_species(self, data):
        """
        Extract primary fuel species from parsed data composition.
        
        Returns the species with highest concentration that is not 
        a common oxidizer/diluent (O2, N2, Ar, He, etc.)
        """
        # Common oxidizers and diluents to exclude
        excluded = {'O2', 'N2', 'Ar', 'He', 'CO2', 'H2O', 'air', 'AR', 'N2O', 'Kr', 'Xe'}
        
        species_list = []
        
        # First, try to get composition from initial_composition (ReSpecTh v2.x format)
        if hasattr(data, 'initial_composition') and data.initial_composition:
            for comp in data.initial_composition:
                sp_name = getattr(comp, 'species_name', None)
                amount = getattr(comp, 'amount', 0)
                if sp_name:
                    species_list.append((sp_name, float(amount) if amount else 0))
        
        # Try to get composition from common_properties
        if not species_list and hasattr(data, 'common_properties') and data.common_properties:
            for prop in data.common_properties:
                if hasattr(prop, 'name') and 'composition' in prop.name.lower():
                    if hasattr(prop, 'species') and prop.species:
                        for sp in prop.species:
                            sp_name = getattr(sp, 'name', None) or getattr(sp, 'species_name', None)
                            amount = getattr(sp, 'amount', 0)
                            if isinstance(amount, (list, tuple)):
                                amount = amount[0] if amount else 0
                            if sp_name:
                                species_list.append((sp_name, float(amount) if amount else 0))
        
        # Try to get composition from datapoints if not in common_properties
        if not species_list and hasattr(data, 'datapoints') and data.datapoints:
            # Get composition from first datapoint
            if data.datapoints:
                dp = data.datapoints[0]
                if hasattr(dp, 'composition') and dp.composition:
                    comp = dp.composition
                    if hasattr(comp, 'species') and comp.species:
                        for sp in comp.species:
                            sp_name = getattr(sp, 'name', None) or getattr(sp, 'species_name', None)
                            amount = getattr(sp, 'amount', 0)
                            if isinstance(amount, (list, tuple)):
                                amount = amount[0] if amount else 0
                            if sp_name:
                                species_list.append((sp_name, float(amount) if amount else 0))
        
        if not species_list:
            return None
        
        # Find the fuel (species with highest concentration not in excluded list)
        fuel = None
        max_amount = -1
        
        for sp_name, amount in species_list:
            # Skip excluded species
            if sp_name.upper() in excluded or sp_name in excluded:
                continue
            if amount > max_amount:
                max_amount = amount
                fuel = sp_name
        
        # If no fuel found (all species excluded), just pick the first non-excluded
        if not fuel:
            for sp_name, _ in species_list:
                if sp_name.upper() not in excluded and sp_name not in excluded:
                    fuel = sp_name
                    break
        
        # Clean up the fuel name (replace special chars with dashes)
        if fuel:
            # Handle common naming patterns
            fuel = fuel.replace(' ', '-')
            # Keep reasonable length
            if len(fuel) > 30:
                fuel = fuel[:30]
        
        return fuel

    def _map_apparatus_kind(self, apparatus_kind, strict=False):
        """Map ReSpecTh apparatus kind text to ApparatusKind enum."""
        if not apparatus_kind:
            return ApparatusKind.SHOCK_TUBE

        kind_lower = apparatus_kind.lower()
        if 'jet' in kind_lower and 'stirred' in kind_lower:
            return ApparatusKind.JET_STIRRED_REACTOR
        if 'stirred' in kind_lower:
            return ApparatusKind.STIRRED_REACTOR
        if 'rcm' in kind_lower or 'rapid compression' in kind_lower:
            return ApparatusKind.RCM
        if 'flow' in kind_lower:
            return ApparatusKind.FLOW_REACTOR
        if 'flame' in kind_lower:
            return ApparatusKind.FLAME
        if 'shock' in kind_lower:
            return ApparatusKind.SHOCK_TUBE

        if strict:
            raise ValueError(
                f'Unsupported apparatus kind "{apparatus_kind}". '
                'Please contact the database maintainer to add support.'
            )
        return ApparatusKind.SHOCK_TUBE

    def _map_experiment_type(self, experiment_type, strict=False):
        """Map ReSpecTh experiment type text to ExperimentType enum."""
        if not experiment_type:
            return ExperimentType.IGNITION_DELAY

        exp_lower = experiment_type.lower()
        if 'jet stirred reactor' in exp_lower or 'jsr' in exp_lower:
            return ExperimentType.JSR_MEASUREMENT
        if 'outlet' in exp_lower and 'concentration' in exp_lower:
            return ExperimentType.OUTLET_CONCENTRATION
        if 'concentration' in exp_lower and 'profile' in exp_lower:
            return ExperimentType.CONCENTRATION_PROFILE
        if 'ignition' in exp_lower or 'delay' in exp_lower:
            return ExperimentType.IGNITION_DELAY
        if 'flame' in exp_lower or 'speed' in exp_lower:
            return ExperimentType.FLAME_SPEED
        if 'species' in exp_lower and 'profile' in exp_lower:
            return ExperimentType.SPECIES_PROFILE
        if 'rate' in exp_lower or 'coefficient' in exp_lower:
            return ExperimentType.RATE_COEFFICIENT
        if 'thermo' in exp_lower:
            return ExperimentType.THERMOCHEMICAL

        if strict:
            raise ValueError(
                f'Unsupported experiment type "{experiment_type}". '
                'Please contact the database maintainer to add support.'
            )
        return ExperimentType.IGNITION_DELAY
    
    def _import_respecth_xml(self, temp_path, original_filename, file_author, file_author_orcid):
        """
        Import ReSpecTh XML file. Tries v2.x format first, falls back to v1.x via PyKED.
        """
        import xml.etree.ElementTree as ET
        
        # First, detect the ReSpecTh version by checking the root element
        try:
            tree = ET.parse(temp_path)
            root = tree.getroot()
            root_tag = root.tag
        except ET.ParseError as e:
            messages.error(self.request, f'Invalid XML file: {str(e)}')
            return self.form_invalid(self.get_form())
        
        # Check if it's a ReSpecTh v2.x file (kdetermination, tdetermination, etc.)
        v2_root_tags = ['kdetermination', 'tdetermination', 'experiment']
        
        if root_tag in v2_root_tags:
            # Use our ReSpecTh v2 converter
            return self._import_respecth_v2(temp_path, original_filename, root_tag, file_author)
        else:
            # Try PyKED's converter for v1.x format
            return self._import_respecth_v1(temp_path, original_filename, file_author, file_author_orcid)
    
    def _import_respecth_v2(self, temp_path, original_filename, file_type, file_author):
        """
        Import ReSpecTh v2.x format file (kdetermination, tdetermination, etc.).
        Shows a preview step first so user can edit the dataset name.
        """
        from .respecth_v2_converter import parse_respecth_v2, ReSpecThV2Data
        
        try:
            data = parse_respecth_v2(temp_path)

            validation_error = None
            if data.file_type == 'experiment':
                # Validate experiment type early so users get clear feedback
                try:
                    self._map_experiment_type(data.experiment_type, strict=True)
                except ValueError as exc:
                    validation_error = str(exc)
            
            # Generate suggested name
            suggested_name = self._generate_readable_name(data, original_filename, data.file_type)
            
            # Build preview info
            ref = data.reference
            preview_info = {
                'dataset_name': suggested_name,
                'original_filename': original_filename,
                'temp_file_path': temp_path,
                'file_type': data.file_type,
                'file_author': file_author or data.file_author or '',
                'datapoints_count': len(data.datapoints),
                'reference_doi': ref.doi if ref else '',
                'reference_journal': ref.journal if ref else '',
                'reference_year': ref.year if ref else '',
                'reference_authors': ', '.join([a.name for a in ref.authors]) if ref and ref.authors else '',
                'reaction': data.reaction.preferred_key if data.reaction else '',
                'experiment_type': data.experiment_type or data.file_type,
                'validation_error': validation_error,
                'can_confirm': validation_error is None,
                'supported_experiment_types': [choice.label for choice in ExperimentType],
            }
            
            # Store in session for preview
            self.request.session['respecth_preview'] = preview_info
            
            # Redirect to preview
            return redirect(f"{self.request.path}?preview=1")
            
        except Exception as e:
            logger.exception("Error parsing ReSpecTh v2 file")
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            messages.error(
                self.request,
                f'Error parsing ReSpecTh v2 file: {str(e)}'
            )
            return self.form_invalid(self.get_form())
            messages.error(
                self.request,
                f'Error importing ReSpecTh v2 file: {str(e)}'
            )
            return self.form_invalid(self.get_form())
    
    def _import_respecth_v1(self, temp_path, original_filename, file_author, file_author_orcid):
        """Import ReSpecTh v1.x format file using PyKED."""
        try:
            from pyked import chemked
            
            ck = chemked.ChemKED.from_respecth(
                temp_path,
                file_author=file_author,
                file_author_orcid=file_author_orcid
            )
            
            dataset = self._import_chemked(ck, original_filename)
            
            messages.success(
                self.request,
                f'Successfully imported ReSpecTh v1 XML "{original_filename}" with {dataset.datapoints.count()} datapoints.'
            )
            return redirect('chemked_database:dataset-detail', pk=dataset.pk)
            
        except ImportError:
            messages.error(self.request, 'PyKED is not installed. Cannot import ReSpecTh v1.x files.')
        except Exception as e:
            error_msg = str(e)
            logger.exception("Error importing ReSpecTh v1 file")
            if 'preferredKey' in error_msg or 'bibliographyLink' in error_msg:
                messages.error(
                    self.request,
                    f'This appears to be a ReSpecTh v2.x file but was not recognized. '
                    f'Please check the file format. Details: {error_msg}'
                )
            else:
                messages.error(self.request, f'Error importing ReSpecTh file: {error_msg}')
        
        return self.form_invalid(self.get_form())
    
    @transaction.atomic
    def _import_kdetermination(self, data, original_filename, file_author, custom_name=None):
        """Import a ReSpecTh v2 kdetermination (rate coefficient) file."""
        from .respecth_v2_converter import ReSpecThV2Data
        
        # Use custom name if provided, otherwise generate one
        if custom_name:
            readable_name = custom_name
            # Ensure uniqueness
            base_name = readable_name
            counter = 1
            while ExperimentDataset.objects.filter(chemked_file_path=readable_name).exists():
                readable_name = f"{base_name}_{counter}"
                counter += 1
        else:
            readable_name = self._generate_readable_name(data, original_filename, 'kdetermination')
        
        # Create a minimal apparatus (not really applicable for k data)
        apparatus, _ = Apparatus.objects.get_or_create(
            kind=ApparatusKind.SHOCK_TUBE,  # Default, can be overridden
            institution='',
            facility='',
        )
        
        # Prepare reference data
        ref = data.reference
        ref_doi = ref.doi if ref else ''
        ref_journal = ref.journal if ref else ''
        ref_year = ref.year if ref else None
        ref_volume = None
        if ref and ref.volume:
            try:
                ref_volume = int(ref.volume)
            except (ValueError, TypeError):
                pass
        ref_pages = ref.pages if ref else ''
        ref_detail = ref.location if ref else ''
        
        # Create dataset with inline reference fields
        # Use RATE_COEFFICIENT experiment type for kdetermination files
        dataset = ExperimentDataset.objects.create(
            chemked_file_path=readable_name,  # Use human-readable name
            experiment_type=ExperimentType.RATE_COEFFICIENT,
            apparatus=apparatus,
            chemked_version='0.4.1',  # Standard ChemKED schema version
            file_version=0,  # Start at 0, increment on modifications
            reference_doi=ref_doi or '',
            reference_journal=ref_journal or '',
            reference_year=ref_year,
            reference_volume=ref_volume,
            reference_pages=ref_pages or '',
            reference_detail=ref_detail or '',
        )
        
        # Add reference authors
        if ref and ref.authors:
            for author_data in ref.authors:
                author, _ = ReferenceAuthor.objects.get_or_create(
                    name=author_data.name,
                    defaults={'orcid': author_data.orcid or ''}
                )
                dataset.reference_authors.add(author)
        
        # Add file author
        if file_author or data.file_author:
            author_name = file_author or data.file_author
            author, _ = FileAuthor.objects.get_or_create(name=author_name)
            dataset.file_authors.add(author)
        
        # Store reaction info in reference_detail if present
        if data.reaction:
            reaction_info = f"Reaction: {data.reaction.preferred_key}"
            if dataset.reference_detail:
                dataset.reference_detail += f"\n{reaction_info}"
            else:
                dataset.reference_detail = reaction_info
            dataset.save()
        
        # Get reaction and method info for rate coefficient records
        reaction_str = data.reaction.preferred_key if data.reaction else ''
        reaction_order = data.reaction.order if data.reaction else None
        bulk_gas = data.reaction.bulk_gas if data.reaction else ''
        method_str = data.method or ''
        
        # Create datapoints
        prop_map = {p.id: p for p in data.data_properties}
        
        for i, dp_data in enumerate(data.datapoints):
            # Find temperature, pressure, and rate coefficient values
            temp_value = None
            temp_units = 'K'
            pressure_value = None
            pressure_units = 'atm'
            rate_coeff_value = None
            rate_coeff_units = 'cm3 mol-1 s-1'
            
            for prop_id, value in dp_data.values.items():
                prop = prop_map.get(prop_id)
                if prop:
                    prop_name_lower = prop.name.lower() if prop.name else ''
                    if 'temperature' in prop_name_lower:
                        try:
                            temp_value = float(value) if value else None
                        except (ValueError, TypeError):
                            temp_value = None
                        temp_units = prop.units or 'K'
                    elif 'pressure' in prop_name_lower:
                        try:
                            pressure_value = float(value) if value else None
                        except (ValueError, TypeError):
                            pressure_value = None
                        pressure_units = prop.units or 'atm'
                    elif 'rate' in prop_name_lower or 'coefficient' in prop_name_lower:
                        try:
                            rate_coeff_value = float(value) if value else None
                        except (ValueError, TypeError):
                            rate_coeff_value = None
                        rate_coeff_units = prop.units or 'cm3 mol-1 s-1'
            
            # Convert to SI if needed
            temp_si = self._convert_to_si(temp_value, temp_units, 'temperature') if temp_value else 0
            pressure_si = self._convert_to_si(pressure_value, pressure_units, 'pressure') if pressure_value else None
            
            # Create datapoint (temperature is required, pressure may be None for k data)
            datapoint = ExperimentDatapoint.objects.create(
                dataset=dataset,
                temperature=temp_si,
                pressure=pressure_si or 0,  # Default to 0 if no pressure data
            )
            
            # Create RateCoefficientDatapoint for rate coefficient data
            if rate_coeff_value is not None:
                RateCoefficientDatapoint.objects.create(
                    datapoint=datapoint,
                    rate_coefficient=rate_coeff_value,
                    rate_coefficient_units=rate_coeff_units,
                    reaction=reaction_str,
                    reaction_order=reaction_order,
                    bulk_gas=bulk_gas,
                    method=method_str,
                )
        
        return dataset
    
    @transaction.atomic
    def _import_tdetermination(self, data, original_filename, file_author, custom_name=None):
        """Import a ReSpecTh v2 tdetermination (thermochemical) file."""
        # Use THERMOCHEMICAL experiment type
        from .respecth_v2_converter import ReSpecThV2Data
        
        # Use custom name if provided, otherwise generate one
        if custom_name:
            readable_name = custom_name
            base_name = readable_name
            counter = 1
            while ExperimentDataset.objects.filter(chemked_file_path=readable_name).exists():
                readable_name = f"{base_name}_{counter}"
                counter += 1
        else:
            readable_name = self._generate_readable_name(data, original_filename, 'tdetermination')
        
        apparatus, _ = Apparatus.objects.get_or_create(
            kind=ApparatusKind.SHOCK_TUBE,
            institution='',
            facility='',
        )
        
        ref = data.reference
        ref_doi = ref.doi if ref else ''
        ref_journal = ref.journal if ref else ''
        ref_year = ref.year if ref else None
        ref_volume = None
        if ref and ref.volume:
            try:
                ref_volume = int(ref.volume)
            except (ValueError, TypeError):
                pass
        ref_pages = ref.pages if ref else ''
        ref_detail = ref.location if ref else ''
        
        dataset = ExperimentDataset.objects.create(
            chemked_file_path=readable_name,
            experiment_type=ExperimentType.THERMOCHEMICAL,
            apparatus=apparatus,
            chemked_version='0.4.1',
            file_version=0,
            reference_doi=ref_doi or '',
            reference_journal=ref_journal or '',
            reference_year=ref_year,
            reference_volume=ref_volume,
            reference_pages=ref_pages or '',
            reference_detail=ref_detail or '',
        )
        
        # Add authors
        if ref and ref.authors:
            for author_data in ref.authors:
                author, _ = ReferenceAuthor.objects.get_or_create(
                    name=author_data.name,
                    defaults={'orcid': author_data.orcid or ''}
                )
                dataset.reference_authors.add(author)
        
        if file_author or data.file_author:
            author_name = file_author or data.file_author
            author, _ = FileAuthor.objects.get_or_create(name=author_name)
            dataset.file_authors.add(author)
        
        # Create datapoints (similar to kdetermination but without rate coefficients)
        prop_map = {p.id: p for p in data.data_properties}
        
        for dp_data in data.datapoints:
            temp_value = None
            temp_units = 'K'
            
            for prop_id, value in dp_data.values.items():
                prop = prop_map.get(prop_id)
                if prop and 'temperature' in (prop.name or '').lower():
                    try:
                        temp_value = float(value) if value else None
                    except (ValueError, TypeError):
                        temp_value = None
                    temp_units = prop.units or 'K'
            
            temp_si = self._convert_to_si(temp_value, temp_units, 'temperature') if temp_value else 0
            
            ExperimentDatapoint.objects.create(
                dataset=dataset,
                temperature=temp_si,
                pressure=0,  # Thermochemical data typically doesn't have pressure
            )
        
        return dataset
    
    @transaction.atomic
    def _import_respecth_experiment(self, data, original_filename, file_author, custom_name=None):
        """Import a ReSpecTh v2 experiment file (ignition delay, species profiles, etc.)."""
        from .respecth_v2_converter import ReSpecThV2Data
        
        # Use custom name if provided, otherwise generate one
        if custom_name:
            readable_name = custom_name
            base_name = readable_name
            counter = 1
            while ExperimentDataset.objects.filter(chemked_file_path=readable_name).exists():
                readable_name = f"{base_name}_{counter}"
                counter += 1
        else:
            readable_name = self._generate_readable_name(data, original_filename, 'experiment')
        
        # Determine apparatus kind from data
        apparatus_kind = self._map_apparatus_kind(data.apparatus_kind)
        
        apparatus, _ = Apparatus.objects.get_or_create(
            kind=apparatus_kind,
            institution='',
            facility='',
        )
        
        # Determine experiment type
        exp_type = self._map_experiment_type(data.experiment_type, strict=True)
        
        ref = data.reference
        ref_doi = ref.doi if ref else ''
        ref_journal = ref.journal if ref else ''
        ref_year = ref.year if ref else None
        ref_volume = None
        if ref and ref.volume:
            try:
                ref_volume = int(ref.volume)
            except (ValueError, TypeError):
                pass
        ref_pages = ref.pages if ref else ''
        ref_detail = ref.location if ref else ''
        ref_title = ref.title if ref else ''
        ref_table = ref.table if ref else ''
        ref_figure = ref.figure if ref else ''
        ref_location = ref.location if ref else ''
        
        # Parse dates
        first_pub_date = None
        last_mod_date = None
        if data.first_publication_date:
            try:
                from datetime import datetime
                first_pub_date = datetime.strptime(data.first_publication_date, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                pass
        if data.last_modification_date:
            try:
                from datetime import datetime
                last_mod_date = datetime.strptime(data.last_modification_date, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                pass
        
        dataset = ExperimentDataset.objects.create(
            chemked_file_path=readable_name,
            experiment_type=exp_type,
            apparatus=apparatus,
            chemked_version='0.4.1',
            file_version=0,
            reference_doi=ref_doi or '',
            reference_journal=ref_journal or '',
            reference_year=ref_year,
            reference_volume=ref_volume,
            reference_pages=ref_pages or '',
            reference_detail=ref_detail or '',
            reference_title=ref_title or '',
            reference_table=ref_table or '',
            reference_figure=ref_figure or '',
            reference_location=ref_location or '',
            file_doi=data.file_doi or '',
            respecth_version=data.respecth_version or '',
            first_publication_date=first_pub_date,
            last_modification_date=last_mod_date,
            method=data.method or '',
        )
        
        # Add authors
        if ref and ref.authors:
            for author_data in ref.authors:
                author, _ = ReferenceAuthor.objects.get_or_create(
                    name=author_data.name,
                    defaults={'orcid': author_data.orcid or ''}
                )
                dataset.reference_authors.add(author)
        
        if file_author or data.file_author:
            author_name = file_author or data.file_author
            author, _ = FileAuthor.objects.get_or_create(name=author_name)
            dataset.file_authors.add(author)
        
        # Import initial composition if available
        common_composition = self._import_composition(data, dataset)
        
        # Extract common properties (equivalence ratio, pressure, temperature, volume, residence time)
        common_pressure = None
        common_pressure_units = 'Pa'
        common_temperature = None
        common_temperature_units = 'K'
        common_equiv_ratio = None
        common_volume = None
        common_volume_units = 'cm3'
        common_residence_time = None
        common_residence_time_units = 's'
        
        if data.common_properties:
            for prop in data.common_properties:
                prop_name = (prop.name or '').lower()
                if 'pressure' in prop_name and prop.value is not None:
                    try:
                        common_pressure = float(prop.value)
                        common_pressure_units = prop.units or 'Pa'
                    except (ValueError, TypeError):
                        pass
                elif 'temperature' in prop_name and prop.value is not None:
                    try:
                        common_temperature = float(prop.value)
                        common_temperature_units = prop.units or 'K'
                    except (ValueError, TypeError):
                        pass
                elif 'equivalence' in prop_name or 'phi' in prop_name:
                    try:
                        common_equiv_ratio = float(prop.value)
                    except (ValueError, TypeError):
                        pass
                elif 'volume' in prop_name and prop.value is not None:
                    try:
                        common_volume = float(prop.value)
                        common_volume_units = prop.units or 'cm3'
                    except (ValueError, TypeError):
                        pass
                elif 'residence' in prop_name and prop.value is not None:
                    try:
                        common_residence_time = float(prop.value)
                        common_residence_time_units = prop.units or 's'
                    except (ValueError, TypeError):
                        pass
        
        # Convert common pressure/temperature to SI
        if common_pressure is not None:
            common_pressure = self._convert_to_si(common_pressure, common_pressure_units, 'pressure')
        if common_temperature is not None:
            common_temperature = self._convert_to_si(common_temperature, common_temperature_units, 'temperature')
        if common_volume is not None:
            common_volume = self._convert_volume_to_si(common_volume, common_volume_units)
        if common_residence_time is not None:
            common_residence_time = self._convert_to_si(common_residence_time, common_residence_time_units, 'time')
        
        # Create common properties record if we have any
        if common_pressure is not None or common_equiv_ratio is not None or common_composition or common_volume is not None or common_residence_time is not None:
            common_props = CommonProperties.objects.create(
                dataset=dataset,
                pressure=common_pressure,
                composition=common_composition,
                equivalence_ratio=common_equiv_ratio,
                reactor_volume=common_volume,
                reactor_volume_units='m3' if common_volume else '',
                residence_time=common_residence_time,
                residence_time_units='s' if common_residence_time else '',
            )
        
        # Create datapoints
        prop_map = {p.id: p for p in data.data_properties}
        
        # Build uncertainty map for species
        uncertainty_map = {}
        if hasattr(data, 'uncertainties') and data.uncertainties:
            for unc in data.uncertainties:
                uncertainty_map[unc.species_name] = unc
        
        for dp_data in data.datapoints:
            temp_value = None
            temp_units = 'K'
            pressure_value = None
            pressure_units = 'Pa'
            ignition_delay_value = None
            ignition_delay_units = 's'
            residence_time_value = None
            residence_time_units = 's'
            species_concentrations = []  # List of (species_info, concentration)
            
            for prop_id, value in dp_data.values.items():
                prop = prop_map.get(prop_id)
                if prop:
                    prop_name = (prop.name or '').lower()
                    if 'temperature' in prop_name:
                        try:
                            temp_value = float(value) if value else None
                        except (ValueError, TypeError):
                            temp_value = None
                        temp_units = prop.units or 'K'
                    elif 'pressure' in prop_name:
                        try:
                            pressure_value = float(value) if value else None
                        except (ValueError, TypeError):
                            pressure_value = None
                        pressure_units = prop.units or 'Pa'
                    elif 'ignition' in prop_name or 'delay' in prop_name:
                        try:
                            ignition_delay_value = float(value) if value else None
                        except (ValueError, TypeError):
                            ignition_delay_value = None
                        ignition_delay_units = prop.units or 's'
                    elif 'residence' in prop_name:
                        try:
                            residence_time_value = float(value) if value else None
                        except (ValueError, TypeError):
                            residence_time_value = None
                        residence_time_units = prop.units or 's'
                    elif 'composition' in prop_name and prop.species_link:
                        # Species concentration data
                        try:
                            conc_value = float(value) if value else None
                            if conc_value is not None:
                                species_concentrations.append((prop, conc_value))
                        except (ValueError, TypeError):
                            pass
            
            # Convert to SI (fallback to common temperature if needed)
            if temp_value is not None:
                temp_si = self._convert_to_si(temp_value, temp_units, 'temperature')
            elif common_temperature is not None:
                temp_si = common_temperature
            else:
                temp_si = 0
            
            # Use datapoint pressure or fall back to common pressure
            if pressure_value is not None:
                pressure_si = self._convert_to_si(pressure_value, pressure_units, 'pressure')
            elif common_pressure is not None:
                pressure_si = common_pressure
            else:
                pressure_si = 0
            
            # Convert residence time to SI if present
            residence_time_si = None
            if residence_time_value is not None:
                residence_time_si = self._convert_to_si(residence_time_value, residence_time_units, 'time')
            
            # Create datapoint
            datapoint = ExperimentDatapoint.objects.create(
                dataset=dataset,
                temperature=temp_si,
                pressure=pressure_si,
                equivalence_ratio=common_equiv_ratio,  # Use common equivalence ratio
                residence_time=residence_time_si,
                residence_time_units='s' if residence_time_si else '',
            )
            
            # Create IgnitionDelayDatapoint if applicable
            if ignition_delay_value is not None:
                ignition_delay_si = self._convert_to_si(ignition_delay_value, ignition_delay_units, 'time')
                IgnitionDelayDatapoint.objects.create(
                    datapoint=datapoint,
                    ignition_delay=ignition_delay_si,
                )
            
            # Create Composition with SpeciesConcentration data (stored as CompositionSpecies)
            if species_concentrations:
                # Create a new composition for this datapoint's measured concentrations
                datapoint_composition = Composition.objects.create(
                    kind=CompositionKind.MOLE_FRACTION,  # Default for concentration data
                )
                
                for prop, conc_value in species_concentrations:
                    species_link = prop.species_link
                    species_name = species_link.preferred_key if species_link else ''
                    
                    # Look up uncertainty for this species
                    unc_value = None
                    unc_type = ''
                    if species_name in uncertainty_map:
                        unc_data = uncertainty_map[species_name]
                        unc_value = unc_data.value
                        unc_type = unc_data.kind
                    
                    # Use get_or_create to avoid duplicate species in the same composition
                    CompositionSpecies.objects.get_or_create(
                        composition=datapoint_composition,
                        species_name=species_name,
                        inchi=species_link.inchi or '' if species_link else '',
                        smiles=species_link.smiles or '' if species_link else '',
                        defaults={
                            'chem_name': species_link.chem_name or '' if species_link else '',
                            'cas': species_link.cas or '' if species_link else '',
                            'amount': conc_value,
                            'amount_uncertainty': unc_value,
                            'amount_uncertainty_type': unc_type or '',
                        }
                    )
                
                # Link composition to datapoint
                datapoint.composition = datapoint_composition
                datapoint.save()
        
        return dataset
    
    def _import_composition(self, data, dataset):
        """
        Import initial composition from ReSpecTh data.
        Returns the Composition object if created, None otherwise.
        """
        if not hasattr(data, 'initial_composition') or not data.initial_composition:
            return None
        
        # Create composition record
        composition = Composition.objects.create(
            kind=CompositionKind.MOLE_FRACTION,  # Default, most common
        )
        
        for comp_data in data.initial_composition:
            # Use get_or_create to avoid duplicate species in the same composition
            CompositionSpecies.objects.get_or_create(
                composition=composition,
                species_name=comp_data.species_name,
                inchi=getattr(comp_data, 'inchi', '') or '',
                smiles=getattr(comp_data, 'smiles', '') or '',
                defaults={
                    'amount': comp_data.amount,
                    'cas': getattr(comp_data, 'cas', '') or '',
                }
            )
        
        return composition
    
    def _convert_volume_to_si(self, value, units):
        """Convert volume to SI units (m³)."""
        try:
            from pint import UnitRegistry
            ureg = UnitRegistry()
            
            units = units.strip()
            # Handle common volume unit variations
            unit_map = {
                'cm3': 'cm**3',
                'cm^3': 'cm**3',
                'ml': 'mL',
                'l': 'L',
                'm3': 'm**3',
                'm^3': 'm**3',
            }
            units_key = units.lower()
            if units_key in unit_map:
                units = unit_map[units_key]
            
            quantity = ureg.Quantity(value, units)
            return quantity.to('m**3').magnitude
        except Exception as e:
            logger.warning(f"Could not convert volume {value} {units} to SI: {e}")
            return value
    
    def _convert_to_si(self, value, units, quantity_type):
        """Convert a value to SI units using pint."""
        try:
            from pint import UnitRegistry
            ureg = UnitRegistry()
            
            # Handle common unit variations
            units = units.strip()
            unit_map = {
                'torr': 'torr',
                'mmhg': 'mmHg',
                'mm hg': 'mmHg',
                'bar': 'bar',
                'atm': 'atm',
            }
            units_key = units.lower()
            if units_key in unit_map:
                units = unit_map[units_key]
            
            # Create quantity and convert
            quantity = ureg.Quantity(value, units)
            
            if quantity_type == 'temperature':
                return quantity.to('kelvin').magnitude
            elif quantity_type == 'pressure':
                return quantity.to('pascal').magnitude
            elif quantity_type == 'time':
                return quantity.to('second').magnitude
            else:
                return value
        except Exception as e:
            logger.warning(f"Could not convert {value} {units} to SI: {e}")
            return value

    @transaction.atomic
    def _import_chemked(self, ck, original_filename):
        """Import a ChemKED object into the database."""
        
        # Get or create apparatus
        apparatus, _ = Apparatus.objects.get_or_create(
            kind=ck.apparatus.kind or ApparatusKind.SHOCK_TUBE,
            institution=ck.apparatus.institution or '',
            facility=ck.apparatus.facility or '',
        )
        
        # Create dataset
        dataset = ExperimentDataset.objects.create(
            chemked_file_path=original_filename,
            file_version=ck.file_version or 0,
            chemked_version=ck.chemked_version or '0.4.1',
            experiment_type=ck.experiment_type or ExperimentType.IGNITION_DELAY,
            apparatus=apparatus,
            reference_doi=ck.reference.doi or '',
            reference_journal=ck.reference.journal or '',
            reference_year=ck.reference.year,
            reference_volume=ck.reference.volume,
            reference_pages=ck.reference.pages or '',
            reference_detail=ck.reference.detail or '',
        )
        
        # Add file authors
        for author in ck.file_authors or []:
            if isinstance(author, dict) and author.get('name'):
                fa, _ = FileAuthor.objects.get_or_create(
                    name=author['name'],
                    orcid=author.get('ORCID', ''),
                )
                dataset.file_authors.add(fa)
        
        # Add reference authors
        for author in ck.reference.authors or []:
            if isinstance(author, dict) and author.get('name'):
                ra, _ = ReferenceAuthor.objects.get_or_create(
                    name=author['name'],
                    orcid=author.get('ORCID', ''),
                )
                dataset.reference_authors.add(ra)
        
        # Process datapoints
        common_composition = None
        common_composition_type = None
        
        for dp in ck.datapoints:
            # Handle composition
            composition = None
            if dp.composition:
                # Check if same as common composition
                if common_composition is None:
                    common_composition_type = dp.composition_type
                    common_composition = Composition.objects.create(
                        kind=dp.composition_type or CompositionKind.MOLE_FRACTION
                    )
                    for species_name, species in dp.composition.items():
                        CompositionSpecies.objects.create(
                            composition=common_composition,
                            species_name=species_name,
                            inchi=species.InChI or '',
                            smiles=species.SMILES or '',
                            amount=species.amount.magnitude if hasattr(species.amount, 'magnitude') else species.amount,
                        )
                composition = common_composition
            
            # Parse quantities with units
            temp_val = dp.temperature.magnitude if hasattr(dp.temperature, 'magnitude') else dp.temperature
            temp_unit = str(dp.temperature.units) if hasattr(dp.temperature, 'units') else 'K'
            
            press_val = dp.pressure.magnitude if hasattr(dp.pressure, 'magnitude') else dp.pressure
            press_unit = str(dp.pressure.units) if hasattr(dp.pressure, 'units') else 'Pa'
            
            # Convert to SI
            try:
                from pint import UnitRegistry
                ureg = UnitRegistry()
                si_temp = (temp_val * ureg(temp_unit)).to('kelvin').magnitude
                si_press = (press_val * ureg(press_unit)).to('pascal').magnitude
            except:
                si_temp = temp_val
                si_press = press_val
            
            # Create ValueWithUnit objects
            temp_quantity = ValueWithUnit.objects.create(value=temp_val, units=temp_unit)
            press_quantity = ValueWithUnit.objects.create(value=press_val, units=press_unit)
            
            # Create datapoint
            datapoint = ExperimentDatapoint.objects.create(
                dataset=dataset,
                temperature=si_temp,
                temperature_quantity=temp_quantity,
                pressure=si_press,
                pressure_quantity=press_quantity,
                equivalence_ratio=dp.equivalence_ratio,
                composition=composition,
            )
            
            # Create ignition delay extension if applicable
            if hasattr(dp, 'ignition_delay') and dp.ignition_delay is not None:
                ign_val = dp.ignition_delay.magnitude if hasattr(dp.ignition_delay, 'magnitude') else dp.ignition_delay
                ign_unit = str(dp.ignition_delay.units) if hasattr(dp.ignition_delay, 'units') else 's'
                
                try:
                    si_ign = (ign_val * ureg(ign_unit)).to('second').magnitude
                except:
                    si_ign = ign_val
                
                ign_quantity = ValueWithUnit.objects.create(value=ign_val, units=ign_unit)
                
                ign_target = ''
                ign_type = ''
                if dp.ignition_type:
                    ign_target = dp.ignition_type.get('target', '')
                    ign_type = dp.ignition_type.get('type', '')
                
                IgnitionDelayDatapoint.objects.create(
                    datapoint=datapoint,
                    ignition_delay=si_ign,
                    ignition_delay_quantity=ign_quantity,
                    ignition_target=ign_target,
                    ignition_type=ign_type,
                )
        
        # Create common properties
        if common_composition:
            # Get ignition info from first datapoint
            first_dp = ck.datapoints[0] if ck.datapoints else None
            ign_target = ''
            ign_type = ''
            if first_dp and first_dp.ignition_type:
                ign_target = first_dp.ignition_type.get('target', '')
                ign_type = first_dp.ignition_type.get('type', '')
            
            CommonProperties.objects.create(
                dataset=dataset,
                composition=common_composition,
                ignition_target=ign_target,
                ignition_type=ign_type,
            )
        
        return dataset


class DatasetExportView(View):
    """
    Export a dataset to ChemKED YAML or ReSpecTh XML format.
    """
    
    def get(self, request, pk):
        dataset = get_object_or_404(
            ExperimentDataset.objects
            .select_related('apparatus', 'common_properties', 'common_properties__composition')
            .prefetch_related(
                'file_authors',
                'reference_authors',
                'datapoints',
                'datapoints__ignition_delay',
                'datapoints__composition__species',
            ),
            pk=pk
        )
        
        export_format = request.GET.get('format', 'yaml')
        
        if export_format == 'yaml':
            return self._export_yaml(dataset)
        elif export_format == 'xml':
            return self._export_xml(dataset)
        elif export_format == 'csv':
            return self._export_csv(dataset)
        else:
            messages.error(request, f'Unknown export format: {export_format}')
            return redirect('chemked_database:dataset-detail', pk=pk)
    
    def _export_yaml(self, dataset):
        """Export dataset to ChemKED YAML format."""
        try:
            from pyked import chemked
            
            # Build ChemKED dictionary from dataset
            chemked_dict = self._dataset_to_chemked_dict(dataset)
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                temp_path = f.name
            
            try:
                ck = chemked.ChemKED(dict_input=chemked_dict, skip_validation=True)
                ck.write_file(temp_path, overwrite=True)
                
                with open(temp_path, 'r') as f:
                    yaml_content = f.read()
                
                filename = Path(dataset.chemked_file_path).stem + '.yaml'
                response = HttpResponse(yaml_content, content_type='application/x-yaml')
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                return response
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    
        except ImportError:
            return HttpResponse('PyKED not installed', status=500)
        except Exception as e:
            logger.exception("Error exporting YAML")
            return HttpResponse(f'Error: {str(e)}', status=500)
    
    def _export_xml(self, dataset):
        """Export dataset to ReSpecTh XML format."""
        try:
            from pyked import chemked
            
            chemked_dict = self._dataset_to_chemked_dict(dataset)
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                yaml_path = f.name
            with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
                xml_path = f.name
            
            try:
                ck = chemked.ChemKED(dict_input=chemked_dict, skip_validation=True)
                ck.write_file(yaml_path, overwrite=True)
                ck.convert_to_ReSpecTh(xml_path)
                
                with open(xml_path, 'r') as f:
                    xml_content = f.read()
                
                filename = Path(dataset.chemked_file_path).stem + '.xml'
                response = HttpResponse(xml_content, content_type='application/xml')
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                return response
            finally:
                for p in [yaml_path, xml_path]:
                    if os.path.exists(p):
                        os.unlink(p)
                        
        except Exception as e:
            logger.exception("Error exporting XML")
            return HttpResponse(f'Error: {str(e)}', status=500)
    
    def _export_csv(self, dataset):
        """Export datapoints to CSV format."""
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Header
        headers = ['Temperature (K)', 'Pressure (Pa)', 'Equivalence Ratio']
        if dataset.experiment_type == ExperimentType.IGNITION_DELAY:
            headers.append('Ignition Delay (s)')
        
        # Add species columns
        species_names = set()
        for dp in dataset.datapoints.all():
            comp = dp.get_composition()
            if comp:
                for sp in comp.species.all():
                    species_names.add(sp.species_name)
        species_names = sorted(species_names)
        headers.extend([f'{sp} (amount)' for sp in species_names])
        
        writer.writerow(headers)
        
        # Data rows
        for dp in dataset.datapoints.select_related('ignition_delay', 'composition').all():
            row = [dp.temperature, dp.pressure, dp.equivalence_ratio or '']
            
            if dataset.experiment_type == ExperimentType.IGNITION_DELAY:
                if hasattr(dp, 'ignition_delay') and dp.ignition_delay:
                    row.append(dp.ignition_delay.ignition_delay or '')
                else:
                    row.append('')
            
            # Species amounts
            comp = dp.get_composition()
            species_amounts = {}
            if comp:
                for sp in comp.species.all():
                    species_amounts[sp.species_name] = sp.amount
            
            for sp_name in species_names:
                row.append(species_amounts.get(sp_name, ''))
            
            writer.writerow(row)
        
        filename = Path(dataset.chemked_file_path).stem + '.csv'
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    
    def _dataset_to_chemked_dict(self, dataset):
        """Convert database dataset to ChemKED dictionary."""
        # File authors
        file_authors = []
        for fa in dataset.file_authors.all():
            author = {'name': fa.name}
            if fa.orcid:
                author['ORCID'] = fa.orcid
            file_authors.append(author)
        
        if not file_authors:
            file_authors = [{'name': 'Database Export'}]
        
        # Reference authors
        ref_authors = []
        for ra in dataset.reference_authors.all():
            author = {'name': ra.name}
            if ra.orcid:
                author['ORCID'] = ra.orcid
            ref_authors.append(author)
        
        if not ref_authors:
            ref_authors = [{'name': 'Unknown'}]
        
        # Build composition from common properties or first datapoint
        composition = None
        if hasattr(dataset, 'common_properties') and dataset.common_properties:
            cp = dataset.common_properties
            if cp.composition:
                composition = {
                    'kind': cp.composition.kind or 'mole fraction',
                    'species': []
                }
                for sp in cp.composition.species.all():
                    sp_dict = {
                        'species-name': sp.species_name,
                        'amount': [sp.amount]
                    }
                    if sp.inchi:
                        sp_dict['InChI'] = sp.inchi
                    composition['species'].append(sp_dict)
        
        # Ignition type from common properties
        ignition_type = None
        if hasattr(dataset, 'common_properties') and dataset.common_properties:
            cp = dataset.common_properties
            if cp.ignition_target or cp.ignition_type:
                ignition_type = {}
                if cp.ignition_target:
                    ignition_type['target'] = cp.ignition_target
                if cp.ignition_type:
                    ignition_type['type'] = cp.ignition_type
        
        # Build datapoints
        datapoints = []
        for dp in dataset.datapoints.all():
            dp_dict = {}
            
            # Temperature
            if dp.temperature_quantity:
                dp_dict['temperature'] = [f"{dp.temperature_quantity.value} {dp.temperature_quantity.units}"]
            else:
                dp_dict['temperature'] = [f"{dp.temperature} kelvin"]
            
            # Pressure
            if dp.pressure_quantity:
                dp_dict['pressure'] = [f"{dp.pressure_quantity.value} {dp.pressure_quantity.units}"]
            else:
                dp_dict['pressure'] = [f"{dp.pressure} pascal"]
            
            # Equivalence ratio
            if dp.equivalence_ratio:
                dp_dict['equivalence-ratio'] = dp.equivalence_ratio
            
            # Composition
            if composition:
                dp_dict['composition'] = composition
            elif dp.composition:
                dp_dict['composition'] = {
                    'kind': dp.composition.kind or 'mole fraction',
                    'species': [
                        {'species-name': sp.species_name, 'amount': [sp.amount]}
                        for sp in dp.composition.species.all()
                    ]
                }
            
            # Ignition type
            if ignition_type:
                dp_dict['ignition-type'] = ignition_type
            
            # Ignition delay
            if hasattr(dp, 'ignition_delay') and dp.ignition_delay:
                ign = dp.ignition_delay
                if ign.ignition_delay_quantity:
                    dp_dict['ignition-delay'] = [
                        f"{ign.ignition_delay_quantity.value} {ign.ignition_delay_quantity.units}"
                    ]
                elif ign.ignition_delay:
                    dp_dict['ignition-delay'] = [f"{ign.ignition_delay} s"]
            
            datapoints.append(dp_dict)
        
        chemked_dict = {
            'file-version': dataset.file_version or 0,
            'chemked-version': dataset.chemked_version or '0.4.1',
            'file-authors': file_authors,
            'reference': {
                'doi': dataset.reference_doi or '',
                'authors': ref_authors,
                'journal': dataset.reference_journal or '',
                'year': dataset.reference_year or 2020,
                'pages': dataset.reference_pages or '',
                'detail': dataset.reference_detail or '',
            },
            'experiment-type': dataset.experiment_type or 'ignition delay',
            'apparatus': {
                'kind': dataset.apparatus.kind if dataset.apparatus else 'shock tube',
                'institution': dataset.apparatus.institution if dataset.apparatus else '',
                'facility': dataset.apparatus.facility if dataset.apparatus else '',
            },
            'datapoints': datapoints,
        }
        
        if dataset.reference_volume:
            chemked_dict['reference']['volume'] = dataset.reference_volume
        
        return chemked_dict


class DatasetProcessView(View):
    """
    SSE endpoint for processing uploaded files with real-time progress.
    
    This view receives a batch_id from session, processes files one by one,
    and streams progress updates back to the client.
    """
    
    def get(self, request):
        """Stream processing progress via Server-Sent Events."""
        batch_id = request.GET.get('batch_id')
        
        if not batch_id:
            return JsonResponse({'error': 'No batch_id provided'}, status=400)
        
        # Get batch data from session
        batch_key = f'upload_batch_{batch_id}'
        batch_data = request.session.get(batch_key)
        
        if not batch_data:
            return JsonResponse({'error': 'Batch not found or expired'}, status=404)
        
        # Clear session data immediately
        del request.session[batch_key]
        request.session.modified = True
        
        # Create SSE response
        response = StreamingHttpResponse(
            self._process_files_stream(batch_data, request),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
        return response
    
    def _process_files_stream(self, batch_data, request):
        """Generator that processes files and yields SSE events."""
        temp_files = batch_data.get('temp_files', [])
        file_format = batch_data.get('file_format', 'auto')
        validate = batch_data.get('validate', True)
        file_author = batch_data.get('file_author', '')
        file_author_orcid = batch_data.get('file_author_orcid', '')
        
        total_files = len(temp_files)
        successful_imports = []
        skipped_imports = []
        failed_imports = []
        
        # Send initial event
        yield self._sse_event('start', {
            'total': total_files,
            'message': f'Starting to process {total_files} file(s)...'
        })
        
        # Get the upload view for processing methods
        upload_view = DatasetUploadView()
        upload_view.request = request
        
        for i, file_info in enumerate(temp_files):
            temp_path = file_info['temp_path']
            original_name = file_info['original_name']
            
            # Send progress event
            progress = ((i + 0.5) / total_files) * 100
            yield self._sse_event('progress', {
                'current': i + 1,
                'total': total_files,
                'percent': round(progress, 1),
                'filename': original_name,
                'message': f'Processing {original_name}...'
            })
            
            # Process the file
            try:
                if not os.path.exists(temp_path):
                    raise FileNotFoundError(f'Temporary file not found: {temp_path}')
                
                result = self._process_single_file(
                    upload_view, temp_path, original_name, 
                    file_format, validate, file_author, file_author_orcid
                )
                
                if result['success']:
                    successful_imports.append(result)
                    yield self._sse_event('file_complete', {
                        'filename': original_name,
                        'status': 'success',
                        'dataset_name': result.get('dataset_name', ''),
                        'datapoints': result.get('datapoints', 0)
                    })
                else:
                    if result.get('error_kind') == 'skipped':
                        skipped_imports.append(result)
                        yield self._sse_event('file_complete', {
                            'filename': original_name,
                            'status': 'skipped',
                            'error': result.get('error', 'Skipped')
                        })
                    else:
                        failed_imports.append(result)
                        yield self._sse_event('file_complete', {
                            'filename': original_name,
                            'status': 'failed',
                            'error': result.get('error', 'Unknown error')
                        })
            except Exception as e:
                logger.exception(f"Error processing {original_name}")
                failed_imports.append({
                    'success': False,
                    'filename': original_name,
                    'error': str(e)
                })
                yield self._sse_event('file_complete', {
                    'filename': original_name,
                    'status': 'failed',
                    'error': str(e)
                })
            finally:
                # Clean up temp file
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
            
            # Update progress after file is complete
            progress = ((i + 1) / total_files) * 100
            yield self._sse_event('progress', {
                'current': i + 1,
                'total': total_files,
                'percent': round(progress, 1),
                'filename': original_name,
                'message': f'Completed {i + 1} of {total_files}'
            })
        
        # Send completion event
        total_datapoints = sum(r.get('datapoints', 0) for r in successful_imports)
        yield self._sse_event('complete', {
            'successful': len(successful_imports),
            'skipped': len(skipped_imports),
            'failed': len(failed_imports),
            'total_datapoints': total_datapoints,
            'redirect_url': reverse('chemked_database:dataset-list') if successful_imports else None
        })
    
    def _process_single_file(self, upload_view, temp_path, original_name, file_format, validate, file_author, file_author_orcid):
        """Process a single file and return result dict."""
        filename = original_name.lower()
        
        # Determine file format
        actual_format = file_format
        if actual_format == 'auto':
            if filename.endswith('.xml'):
                actual_format = 'xml'
            else:
                actual_format = 'yaml'
        
        try:
            if actual_format == 'xml':
                dataset = upload_view._import_respecth_xml_batch(temp_path, original_name, file_author, file_author_orcid)
                return {
                    'success': True,
                    'filename': original_name,
                    'dataset_id': dataset.pk,
                    'dataset_name': dataset.chemked_file_path,
                    'datapoints': dataset.datapoints.count()
                }
            else:
                from pyked import chemked
                ck = chemked.ChemKED(yaml_file=temp_path, skip_validation=not validate)
                dataset = upload_view._import_chemked(ck, original_name)
                return {
                    'success': True,
                    'filename': original_name,
                    'dataset_id': dataset.pk,
                    'dataset_name': dataset.chemked_file_path,
                    'datapoints': dataset.datapoints.count()
                }
        except Exception as e:
            formatted = upload_view._format_import_error(str(e))
            return {
                'success': False,
                'filename': original_name,
                'error': formatted['message'],
                'error_kind': formatted['kind']
            }
    
    def _sse_event(self, event_type, data):
        """Format a Server-Sent Event."""
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


class ClearWizardView(View):
    """Clear the wizard session data."""
    
    def get(self, request):
        """Allow GET for simple link-based clearing."""
        return self._clear_session(request)
    
    def post(self, request):
        return self._clear_session(request)
    
    def _clear_session(self, request):
        if 'chemked_wizard' in request.session:
            del request.session['chemked_wizard']
        messages.info(request, 'Form data cleared.')
        return redirect('chemked_database:dataset-create')
