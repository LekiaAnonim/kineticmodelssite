"""
Helpers to attach experiment-type-specific extension models to generic datapoints.
"""

from typing import Optional

from .models import (
    ExperimentType,
    ExperimentDatapoint,
    FlameSpeedDatapoint,
    IgnitionDelayDatapoint,
    SpeciesProfileDatapoint,
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
    if experiment_type == ExperimentType.FLAME_SPEED:
        return FlameSpeedDatapoint.objects.create(datapoint=datapoint, **payload)
    if experiment_type == ExperimentType.SPECIES_PROFILE:
        return SpeciesProfileDatapoint.objects.create(datapoint=datapoint, **payload)

    return None
