"""django-filter FilterSets for the API.

These power range/equality query parameters on the data endpoints (e.g. filter
ignition-delay datapoints by temperature and pressure ranges). drf-spectacular
introspects them, so every parameter is documented automatically in the schema.
"""

import django_filters as df

from analysis import models as am
from chemked_database import models as cm


class ExperimentDatasetFilter(df.FilterSet):
    class Meta:
        model = cm.ExperimentDataset
        fields = {
            "experiment_type": ["exact"],
            "reference_doi": ["exact", "icontains"],
            "reference_journal": ["icontains"],
            "reference_year": ["exact", "gte", "lte"],
            "file_doi": ["exact"],
            "is_valid": ["exact"],
            "apparatus__kind": ["exact"],
            "apparatus__mode": ["exact"],
        }


class ExperimentDatapointFilter(df.FilterSet):
    class Meta:
        model = cm.ExperimentDatapoint
        fields = {
            "temperature": ["exact", "gte", "lte"],
            "pressure": ["exact", "gte", "lte"],
            "equivalence_ratio": ["exact", "gte", "lte"],
            "residence_time": ["exact", "gte", "lte"],
            "position": ["exact", "gte", "lte"],
            "dataset": ["exact"],
        }


class CommonPropertiesFilter(df.FilterSet):
    class Meta:
        model = cm.CommonProperties
        fields = {
            "temperature": ["exact", "gte", "lte"],
            "pressure": ["exact", "gte", "lte"],
            "equivalence_ratio": ["exact", "gte", "lte"],
            "ignition_target": ["exact"],
            "ignition_type": ["exact"],
        }


class IgnitionDelayFilter(df.FilterSet):
    class Meta:
        model = cm.IgnitionDelayDatapoint
        fields = {
            "ignition_delay": ["exact", "gte", "lte"],
            "first_stage_ignition_delay": ["gte", "lte"],
            "ignition_target": ["exact"],
            "ignition_type": ["exact"],
            "datapoint__temperature": ["gte", "lte"],
            "datapoint__pressure": ["gte", "lte"],
            "datapoint__equivalence_ratio": ["gte", "lte"],
        }


class LaminarBurningVelocityFilter(df.FilterSet):
    class Meta:
        model = cm.LaminarBurningVelocityMeasurementDatapoint
        fields = {
            "laminar_burning_velocity": ["exact", "gte", "lte"],
            "stretch": ["gte", "lte"],
            "datapoint__temperature": ["gte", "lte"],
            "datapoint__pressure": ["gte", "lte"],
            "datapoint__equivalence_ratio": ["gte", "lte"],
        }


class CompositionSpeciesFilter(df.FilterSet):
    class Meta:
        model = cm.CompositionSpecies
        fields = {
            "species_name": ["exact", "icontains"],
            "cas": ["exact"],
            "inchi": ["exact"],
            "smiles": ["exact"],
            "amount": ["gte", "lte"],
        }


class SimulationRunFilter(df.FilterSet):
    class Meta:
        model = am.SimulationRun
        fields = {
            "status": ["exact"],
            "triggered_by": ["exact"],
            "kinetic_model": ["exact"],
            "dataset": ["exact"],
        }


class ModelDatasetCoverageFilter(df.FilterSet):
    class Meta:
        model = am.ModelDatasetCoverage
        fields = {
            "has_successful_run": ["exact"],
            "is_outdated": ["exact"],
            "needs_rerun": ["exact"],
            "latest_error_function": ["gte", "lte"],
            "latest_deviation": ["gte", "lte"],
            "kinetic_model": ["exact"],
            "dataset": ["exact"],
        }


class DatapointResultFilter(df.FilterSet):
    class Meta:
        model = am.DatapointResult
        fields = {
            "temperature": ["gte", "lte"],
            "pressure": ["gte", "lte"],
            "success": ["exact"],
            "error_value": ["gte", "lte"],
            "simulation_result": ["exact"],
        }
