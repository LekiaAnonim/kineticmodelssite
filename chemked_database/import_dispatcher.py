"""
Helpers to attach experiment-type-specific extension models to generic datapoints.
"""

from typing import Optional

from .models import (
    ExperimentType,
    ExperimentDatapoint,
    BurnerStabilizedFlameSpeciationMeasurementDatapoint,
    ConcentrationTimeProfileMeasurementDatapoint,
    IgnitionDelayDatapoint,
    JetStirredReactorMeasurementDatapoint,
    LaminarBurningVelocityMeasurementDatapoint,
    OutletConcentrationMeasurementDatapoint,
)


def create_experiment_extension(
    datapoint: ExperimentDatapoint,
    experiment_type: str,
    payload: Optional[dict] = None,
):
    """
    Create an extension model for the given experiment type.

    Args:
        datapoint: Base ExperimentDatapoint instance.
        experiment_type: One of ExperimentType values.
        payload: Optional dict of fields for the extension model.

    Returns:
        Created extension model instance, or None if experiment type unsupported.
    """
    payload = payload or {}

    if experiment_type == ExperimentType.IGNITION_DELAY:
        return IgnitionDelayDatapoint.objects.create(datapoint=datapoint, **payload)
    if experiment_type == ExperimentType.LAMINAR_BURNING_VELOCITY:
        return LaminarBurningVelocityMeasurementDatapoint.objects.create(datapoint=datapoint, **payload)
    if experiment_type == ExperimentType.CONCENTRATION_TIME_PROFILE:
        return ConcentrationTimeProfileMeasurementDatapoint.objects.create(datapoint=datapoint, **payload)
    if experiment_type == ExperimentType.JSR_MEASUREMENT:
        return JetStirredReactorMeasurementDatapoint.objects.create(datapoint=datapoint, **payload)
    if experiment_type == ExperimentType.OUTLET_CONCENTRATION:
        return OutletConcentrationMeasurementDatapoint.objects.create(datapoint=datapoint, **payload)
    if experiment_type == ExperimentType.BSFS_MEASUREMENT:
        return BurnerStabilizedFlameSpeciationMeasurementDatapoint.objects.create(datapoint=datapoint, **payload)

    return None
