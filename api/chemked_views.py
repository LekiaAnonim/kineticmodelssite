"""Read-only API for the ChemKED experimental-data layer (``chemked_database``).

Experimental datasets, datapoints, and the per-measurement-type detail tables
are exposed as read-only endpoints. New experimental data is contributed through
the contribution endpoints (see ``api/contribution_views.py``) and the PR/CI
workflow, not written directly through these endpoints.

High-value relations (quantities, apparatus, authors, composition) are nested
inline via explicit named serializers so responses carry real values rather than
bare IDs. Parent back-references (e.g. a datapoint's ``dataset``) are kept as IDs
to avoid circular and oversized payloads.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny

from chemked_database import models


class ReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """List/retrieve only. Experimental data is contributed via the PR workflow."""

    permission_classes = [AllowAny]


# ---------------------------------------------------------------------------
# Leaf / nested serializers (defined first so composites can reference them)
# ---------------------------------------------------------------------------
class ValueWithUnitSerializer(serializers.ModelSerializer):
    """A measured quantity: value, units, and uncertainty metadata."""

    class Meta:
        model = models.ValueWithUnit
        fields = "__all__"


class ApparatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Apparatus
        fields = "__all__"


class FileAuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.FileAuthor
        fields = "__all__"


class ReferenceAuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ReferenceAuthor
        fields = "__all__"


class CompositionSpeciesSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.CompositionSpecies
        fields = "__all__"


class CompositionSerializer(serializers.ModelSerializer):
    # related_name on CompositionSpecies.composition is "species"
    species = CompositionSpeciesSerializer(many=True, read_only=True)

    class Meta:
        model = models.Composition
        fields = "__all__"


class CommonPropertiesSerializer(serializers.ModelSerializer):
    pressure_quantity = ValueWithUnitSerializer(read_only=True)
    pressure_rise_quantity = ValueWithUnitSerializer(read_only=True)
    reactor_volume_quantity = ValueWithUnitSerializer(read_only=True)
    residence_time_quantity = ValueWithUnitSerializer(read_only=True)
    equivalence_ratio_quantity = ValueWithUnitSerializer(read_only=True)
    temperature_quantity = ValueWithUnitSerializer(read_only=True)
    flow_rate_quantity = ValueWithUnitSerializer(read_only=True)
    laminar_burning_velocity_quantity = ValueWithUnitSerializer(read_only=True)
    composition = CompositionSerializer(read_only=True)

    class Meta:
        model = models.CommonProperties
        fields = "__all__"


# ---------------------------------------------------------------------------
# Top-level resource serializers
# ---------------------------------------------------------------------------
class ExperimentDatasetSerializer(serializers.ModelSerializer):
    apparatus = ApparatusSerializer(read_only=True)
    file_authors = FileAuthorSerializer(many=True, read_only=True)
    reference_authors = ReferenceAuthorSerializer(many=True, read_only=True)
    common_properties = CommonPropertiesSerializer(read_only=True)

    class Meta:
        model = models.ExperimentDataset
        fields = "__all__"


class ExperimentDatapointSerializer(serializers.ModelSerializer):
    temperature_quantity = ValueWithUnitSerializer(read_only=True)
    pressure_quantity = ValueWithUnitSerializer(read_only=True)
    equivalence_ratio_quantity = ValueWithUnitSerializer(read_only=True)
    composition = CompositionSerializer(read_only=True)

    class Meta:
        model = models.ExperimentDatapoint
        fields = "__all__"


class IgnitionDelayDatapointSerializer(serializers.ModelSerializer):
    ignition_delay_quantity = ValueWithUnitSerializer(read_only=True)
    first_stage_ignition_delay_quantity = ValueWithUnitSerializer(read_only=True)
    pressure_rise_quantity = ValueWithUnitSerializer(read_only=True)

    class Meta:
        model = models.IgnitionDelayDatapoint
        fields = "__all__"


class LaminarBurningVelocityDatapointSerializer(serializers.ModelSerializer):
    laminar_burning_velocity_quantity = ValueWithUnitSerializer(read_only=True)
    stretch_quantity = ValueWithUnitSerializer(read_only=True)
    pressure_rise_quantity = ValueWithUnitSerializer(read_only=True)

    class Meta:
        model = models.LaminarBurningVelocityMeasurementDatapoint
        fields = "__all__"


class RateCoefficientDatapointSerializer(serializers.ModelSerializer):
    rate_coefficient_quantity = ValueWithUnitSerializer(read_only=True)

    class Meta:
        model = models.RateCoefficientDatapoint
        fields = "__all__"


class ConcentrationTimeProfileDatapointSerializer(serializers.ModelSerializer):
    timeshift_amount_quantity = ValueWithUnitSerializer(read_only=True)

    class Meta:
        model = models.ConcentrationTimeProfileMeasurementDatapoint
        fields = "__all__"


class JetStirredReactorDatapointSerializer(serializers.ModelSerializer):
    environment_temperature_quantity = ValueWithUnitSerializer(read_only=True)
    measured_composition = CompositionSerializer(read_only=True)

    class Meta:
        model = models.JetStirredReactorMeasurementDatapoint
        fields = "__all__"


class OutletConcentrationDatapointSerializer(serializers.ModelSerializer):
    residence_time_quantity = ValueWithUnitSerializer(read_only=True)
    volumetric_flow_quantity = ValueWithUnitSerializer(read_only=True)
    measured_composition = CompositionSerializer(read_only=True)
    initial_composition = CompositionSerializer(read_only=True)

    class Meta:
        model = models.OutletConcentrationMeasurementDatapoint
        fields = "__all__"


class BurnerStabilizedFlameDatapointSerializer(serializers.ModelSerializer):
    distance_quantity = ValueWithUnitSerializer(read_only=True)
    flow_rate_quantity = ValueWithUnitSerializer(read_only=True)
    measured_composition = CompositionSerializer(read_only=True)

    class Meta:
        model = models.BurnerStabilizedFlameSpeciationMeasurementDatapoint
        fields = "__all__"


# ---------------------------------------------------------------------------
# ViewSets
# ---------------------------------------------------------------------------
@extend_schema(tags=["experimental-data"])
class ExperimentDatasetViewSet(ReadOnlyViewSet):
    queryset = models.ExperimentDataset.objects.all()
    serializer_class = ExperimentDatasetSerializer


@extend_schema(tags=["experimental-data"])
class ExperimentDatapointViewSet(ReadOnlyViewSet):
    queryset = models.ExperimentDatapoint.objects.all()
    serializer_class = ExperimentDatapointSerializer


@extend_schema(tags=["experimental-data"])
class ApparatusViewSet(ReadOnlyViewSet):
    queryset = models.Apparatus.objects.all()
    serializer_class = ApparatusSerializer


@extend_schema(tags=["experimental-data"])
class CommonPropertiesViewSet(ReadOnlyViewSet):
    queryset = models.CommonProperties.objects.all()
    serializer_class = CommonPropertiesSerializer


@extend_schema(tags=["experimental-data"])
class CompositionViewSet(ReadOnlyViewSet):
    queryset = models.Composition.objects.all()
    serializer_class = CompositionSerializer


@extend_schema(tags=["experimental-data"])
class IgnitionDelayViewSet(ReadOnlyViewSet):
    queryset = models.IgnitionDelayDatapoint.objects.all()
    serializer_class = IgnitionDelayDatapointSerializer


@extend_schema(tags=["experimental-data"])
class LaminarBurningVelocityViewSet(ReadOnlyViewSet):
    queryset = models.LaminarBurningVelocityMeasurementDatapoint.objects.all()
    serializer_class = LaminarBurningVelocityDatapointSerializer


@extend_schema(tags=["experimental-data"])
class RateCoefficientViewSet(ReadOnlyViewSet):
    queryset = models.RateCoefficientDatapoint.objects.all()
    serializer_class = RateCoefficientDatapointSerializer


@extend_schema(tags=["experimental-data"])
class ConcentrationTimeProfileViewSet(ReadOnlyViewSet):
    queryset = models.ConcentrationTimeProfileMeasurementDatapoint.objects.all()
    serializer_class = ConcentrationTimeProfileDatapointSerializer


@extend_schema(tags=["experimental-data"])
class JetStirredReactorViewSet(ReadOnlyViewSet):
    queryset = models.JetStirredReactorMeasurementDatapoint.objects.all()
    serializer_class = JetStirredReactorDatapointSerializer


@extend_schema(tags=["experimental-data"])
class OutletConcentrationViewSet(ReadOnlyViewSet):
    queryset = models.OutletConcentrationMeasurementDatapoint.objects.all()
    serializer_class = OutletConcentrationDatapointSerializer


@extend_schema(tags=["experimental-data"])
class BurnerStabilizedFlameViewSet(ReadOnlyViewSet):
    queryset = models.BurnerStabilizedFlameSpeciationMeasurementDatapoint.objects.all()
    serializer_class = BurnerStabilizedFlameDatapointSerializer
