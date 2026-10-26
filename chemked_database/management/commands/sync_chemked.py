from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from chemked_database.import_dispatcher import create_experiment_extension
from chemked_database.models import (
    Apparatus,
    AuxiliaryProfile,
    CommonProperties,
    Composition,
    CompositionSpecies,
    ConcentrationProfile,
    ExperimentDataset,
    ExperimentDatapoint,
    ExperimentType,
    FileAuthor,
    IgnitionDelayDatapoint,
    ReferenceAuthor,
    RCMData,
    SpeciesThermo,
    TimeHistory,
    ValueWithUnit,
    VolumeHistory,
)
from chemked_database.units import UnitConversionError, quantity_to_si
from chemked_database.utils.chemistry import infer_smiles_and_atomic_composition

# A number may end in a decimal point ("660. K").
VALUE_UNIT_RE = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*)$")
# The composition kinds of ChemKED 0.5; the concentrations are found in shock tube speciation files
COMPOSITION_KINDS = {
    "mass fraction", "mole fraction", "mole percent", "mol/cm3", "mol/m3", "mol/L", "mol/dm3",
}

# ChemKED 0.5 has one experiment type for every species profile measurement. The site keeps
# one per reactor, each with its own extension model, told from the apparatus.
SPECIATION_MEASUREMENT = "speciation measurement"
SPECIATION_APPARATUS_TYPES = {
    "jet stirred reactor": ExperimentType.JSR_MEASUREMENT,
    "burner stabilized flame": ExperimentType.BSFS_MEASUREMENT,
    "shock tube": ExperimentType.CONCENTRATION_TIME_PROFILE,
}


def speciation_experiment_type(data: Dict[str, Any]) -> str:
    """ExperimentType value of a ChemKED speciation measurement file.

    A flow reactor file is a concentration time profile measurement when its profiles are
    against time, and an outlet concentration measurement otherwise (temperature or
    residence-time sweeps).
    """
    kind = (data.get("apparatus") or {}).get("kind")
    if kind in SPECIATION_APPARATUS_TYPES:
        return SPECIATION_APPARATUS_TYPES[kind]
    if kind == "flow reactor":
        names = {
            variable.get("name")
            for datapoint in data.get("datapoints") or []
            for variable in (datapoint or {}).get("independent-variables") or []
        }
        if "time" in names:
            return ExperimentType.CONCENTRATION_TIME_PROFILE
        return ExperimentType.OUTLET_CONCENTRATION
    raise ValueError(
        f"experiment-type '{SPECIATION_MEASUREMENT}' on apparatus kind '{kind}' is not"
        f" supported; known kinds are {', '.join([*SPECIATION_APPARATUS_TYPES, 'flow reactor'])}"
    )


def experiment_type_of(data: Dict[str, Any]) -> str:
    """ExperimentType value of a ChemKED file.

    Raises ValueError for a missing, unknown or unsupported experiment-type: such a file is
    not imported, instead of being stored as an ignition delay dataset without datapoints.
    """
    experiment_type = data.get("experiment-type")
    if not experiment_type:
        raise ValueError("experiment-type is missing")
    if experiment_type in ExperimentType.values:
        return experiment_type
    if experiment_type == SPECIATION_MEASUREMENT:
        return speciation_experiment_type(data)
    raise ValueError(
        f"unknown experiment-type '{experiment_type}'; known types are"
        f" {', '.join([*ExperimentType.values, SPECIATION_MEASUREMENT])}"
    )


def speciation_problem(datapoint_data: Dict[str, Any]) -> Optional[str]:
    """Why a speciation datapoint cannot be stored, or None.

    Each profile row must hold one value per independent variable, then the amount, then
    optionally its uncertainty.
    """
    variables = datapoint_data.get("independent-variables") or []
    if not variables:
        return "independent-variables required by schema"
    if any(not isinstance(v, dict) or not v.get("name") or not v.get("units") for v in variables):
        return "each independent-variable needs a name and units"
    profiles = datapoint_data.get("concentration-profiles") or []
    if not profiles:
        return "concentration-profiles required by schema"
    columns = (len(variables) + 1, len(variables) + 2)
    for profile in profiles:
        name = (profile or {}).get("species-name")
        if not name:
            return "a concentration profile has no species-name"
        if not (profile.get("quantity") or {}).get("units"):
            return f"concentration profile of {name} has no quantity units"
        rows = profile.get("values") or []
        if not rows:
            return f"concentration profile of {name} has no values"
        if any(not isinstance(row, list) or len(row) not in columns for row in rows):
            return (
                f"concentration profile of {name} has rows that are not"
                f" {columns[0]} or {columns[1]} columns long"
            )
    return None


def profile_uncertainty(raw: Any):
    """A profile's uncertainty block as stored: the one dict of the ChemKED list."""
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict):
        return raw[0]
    return raw or None


def time_first(values: Any, time: Optional[Dict[str, Any]], quantity: Optional[Dict[str, Any]]):
    """Rows of a time history as [time, quantity, ...], the order the export writes back."""
    if (time or {}).get("column") == 1 and (quantity or {}).get("column") == 0:
        return [[row[1], row[0], *row[2:]] for row in values]
    return values


def parse_value_unit(raw: Any):
    """
    Parse PyKED value-unit schema (list or string) into value + units + uncertainty.
    Returns: (value, units, extra_fields)
    """
    if raw is None:
        return None, "", {}

    value = None
    units = ""
    extra: Dict[str, Any] = {}

    def parse_uncertainty(value):
        if value is None:
            return None, None
        if isinstance(value, (int, float)):
            return float(value), None
        if isinstance(value, str):
            match = VALUE_UNIT_RE.match(value)
            if match:
                return float(match.group(1)), value
            return None, value
        return None, None

    if isinstance(raw, list):
        if not raw:
            return None, "", {}
        value_part = raw[0]
        metadata = None
        if isinstance(value_part, (int, float)):
            value = float(value_part)
        elif isinstance(value_part, str):
            match = VALUE_UNIT_RE.match(value_part)
            if match:
                value = float(match.group(1))
                units = match.group(2).strip()
            else:
                extra["value_text"] = value_part
        elif isinstance(value_part, dict):
            metadata = value_part

        if metadata is None and len(raw) > 1 and isinstance(raw[1], dict):
            metadata = raw[1]

        if metadata is not None:
            uncertainty_raw = metadata.get("uncertainty")
            upper_raw = metadata.get("upper-uncertainty")
            lower_raw = metadata.get("lower-uncertainty")
            esd_raw = metadata.get("evaluated-standard-deviation")

            uncertainty_value, uncertainty_text = parse_uncertainty(uncertainty_raw)
            upper_value, upper_text = parse_uncertainty(upper_raw)
            lower_value, lower_text = parse_uncertainty(lower_raw)
            esd_value, esd_text = parse_uncertainty(esd_raw)

            extra.update({
                "uncertainty_type": metadata.get("uncertainty-type", ""),
                "uncertainty": uncertainty_value,
                "upper_uncertainty": upper_value,
                "lower_uncertainty": lower_value,
                "uncertainty_text": uncertainty_text or upper_text or lower_text or esd_text or "",
                "sourcetype": metadata.get("sourcetype", ""),
                "evaluated_standard_deviation": esd_value,
                "evaluated_standard_deviation_type": metadata.get("evaluated-standard-deviation-type", ""),
                "evaluated_standard_deviation_sourcetype": metadata.get("evaluated-standard-deviation-sourcetype", ""),
                "evaluated_standard_deviation_method": metadata.get("evaluated-standard-deviation-method", ""),
            })
        return value, units, extra

    if isinstance(raw, (int, float)):
        return float(raw), units, extra

    if isinstance(raw, str):
        match = VALUE_UNIT_RE.match(raw)
        if match:
            value = float(match.group(1))
            units = match.group(2).strip()
        else:
            extra["value_text"] = raw
        return value, units, extra

    return None, units, extra


def create_value_with_unit(raw: Any):
    value, units, extra = parse_value_unit(raw)
    if value is None and not extra.get("value_text"):
        return None
    return ValueWithUnit.objects.create(
        value=value,
        units=units or "",
        value_text=extra.get("value_text", ""),
        uncertainty_type=extra.get("uncertainty_type", ""),
        uncertainty=extra.get("uncertainty"),
        uncertainty_text=extra.get("uncertainty_text", ""),
        upper_uncertainty=extra.get("upper_uncertainty"),
        lower_uncertainty=extra.get("lower_uncertainty"),
        sourcetype=extra.get("sourcetype", ""),
        evaluated_standard_deviation=extra.get("evaluated_standard_deviation"),
        evaluated_standard_deviation_type=extra.get("evaluated_standard_deviation_type", ""),
        evaluated_standard_deviation_sourcetype=extra.get("evaluated_standard_deviation_sourcetype", ""),
        evaluated_standard_deviation_method=extra.get("evaluated_standard_deviation_method", ""),
    )


def si_value(quantity, kind: str, report: Callable[[str], None], context: str):
    """Value of *quantity* in the SI unit of *kind*, for a numeric field next to it.

    The quantity keeps the value and unit of the file. If the unit cannot be converted, the
    numeric field is left empty and the problem is reported.
    """
    try:
        return quantity_to_si(quantity, kind)
    except UnitConversionError as exc:
        report(f"{context}: {exc}; numeric value left empty")
        return None


def create_composition(
    composition_data: Optional[Dict[str, Any]],
    reporter: Optional[Callable[[str], None]] = None,
    context: str = "composition",
):
    if not composition_data:
        return None

    def report(message: str):
        if reporter:
            reporter(message)

    kind = composition_data.get("kind")
    if not kind:
        report(f"Skipping {context}: composition kind is required")
        return None
    if kind not in COMPOSITION_KINDS:
        report(f"Skipping {context}: invalid composition kind '{kind}'")
        return None

    species_list = composition_data.get("species") or []
    if not species_list:
        report(f"Skipping {context}: composition species list is required")
        return None

    # ChemKED 0.5 requires a name and an amount; InChI, SMILES and atomic-composition are
    # optional (pentane/Bugler_2017 gives names only)
    def is_valid_species(species: Dict[str, Any]) -> bool:
        if not species.get("species-name"):
            return False
        amount_list = species.get("amount") or []
        if not amount_list:
            return False
        try:
            float(amount_list[0])
        except (TypeError, ValueError):
            return False
        return True

    if not any(is_valid_species(species) for species in species_list):
        report(f"Skipping {context}: composition species missing required fields")
        return None

    composition = Composition.objects.create(kind=kind)

    for species in species_list:
        if not is_valid_species(species):
            report(f"Skipping species in {context}: missing required fields")
            continue

        amount_list = species.get("amount") or []
        amount_value = None
        amount_uncertainty = None
        amount_uncertainty_type = ""
        amount_uncertainty_sourcetype = ""
        amount_upper = None
        amount_lower = None

        if amount_list:
            amount_value = float(amount_list[0])
        amount_esd = None
        amount_esd_type = ""
        amount_esd_sourcetype = ""
        amount_esd_method = ""
        if len(amount_list) > 1 and isinstance(amount_list[1], dict):
            amount_uncertainty_type = amount_list[1].get("uncertainty-type", "")
            amount_uncertainty = amount_list[1].get("uncertainty")
            amount_uncertainty_sourcetype = amount_list[1].get("uncertainty-sourcetype", "")
            amount_upper = amount_list[1].get("upper-uncertainty")
            amount_lower = amount_list[1].get("lower-uncertainty")
            amount_esd = amount_list[1].get("evaluated-standard-deviation")
            amount_esd_type = amount_list[1].get("evaluated-standard-deviation-type", "")
            amount_esd_sourcetype = amount_list[1].get("evaluated-standard-deviation-sourcetype", "")
            amount_esd_method = amount_list[1].get("evaluated-standard-deviation-method", "")

        inchi_value = species.get("InChI", "")
        smiles_value = species.get("SMILES", "")
        atomic_comp = species.get("atomic-composition")

        if inchi_value and (not smiles_value or not atomic_comp):
            derived_smiles, derived_atomic = infer_smiles_and_atomic_composition(inchi_value)
            if not smiles_value and derived_smiles:
                smiles_value = derived_smiles
            if not atomic_comp and derived_atomic:
                atomic_comp = derived_atomic

        composition_species = CompositionSpecies.objects.create(
            composition=composition,
            species_name=species.get("species-name", ""),
            inchi=inchi_value,
            smiles=smiles_value,
            atomic_composition=atomic_comp,
            amount=amount_value or 0.0,
            amount_uncertainty=amount_uncertainty,
            amount_uncertainty_type=amount_uncertainty_type,
            amount_uncertainty_sourcetype=amount_uncertainty_sourcetype,
            amount_upper_uncertainty=amount_upper,
            amount_lower_uncertainty=amount_lower,
            amount_evaluated_standard_deviation=amount_esd,
            amount_evaluated_standard_deviation_type=amount_esd_type,
            amount_evaluated_standard_deviation_sourcetype=amount_esd_sourcetype,
            amount_evaluated_standard_deviation_method=amount_esd_method,
        )

        thermo = species.get("thermo") or {}
        if thermo:
            t_ranges = thermo.get("T_ranges", [])
            data = thermo.get("data", [])
            SpeciesThermo.objects.create(
                species=composition_species,
                t_range_1=str(t_ranges[0]) if len(t_ranges) > 0 else "",
                t_range_2=str(t_ranges[1]) if len(t_ranges) > 1 else "",
                t_range_3=str(t_ranges[2]) if len(t_ranges) > 2 else "",
                coeff_1=data[0] if len(data) > 0 else None,
                coeff_2=data[1] if len(data) > 1 else None,
                coeff_3=data[2] if len(data) > 2 else None,
                coeff_4=data[3] if len(data) > 3 else None,
                coeff_5=data[4] if len(data) > 4 else None,
                coeff_6=data[5] if len(data) > 5 else None,
                coeff_7=data[6] if len(data) > 6 else None,
                coeff_8=data[7] if len(data) > 7 else None,
                coeff_9=data[8] if len(data) > 8 else None,
                coeff_10=data[9] if len(data) > 9 else None,
                coeff_11=data[10] if len(data) > 10 else None,
                coeff_12=data[11] if len(data) > 11 else None,
                coeff_13=data[12] if len(data) > 12 else None,
                coeff_14=data[13] if len(data) > 13 else None,
                note=thermo.get("note", ""),
            )

    return composition


class Command(BaseCommand):
    help = "Sync ChemKED YAML files into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default=getattr(settings, "CHEMKED_DATABASE_PATH", None),
            help="Path to ChemKED-database directory",
        )
        parser.add_argument("--limit", type=int, default=None, help="Limit number of files")
        parser.add_argument("--dry-run", action="store_true", help="Parse without writing DB")
        parser.add_argument(
            "--files",
            nargs="+",
            default=None,
            metavar="FILE",
            help=(
                "Repo-relative paths of specific files to import "
                "(e.g. methane/Smith_2020/file.yaml). "
                "When omitted all YAML files under --path are scanned."
            ),
        )

    def handle(self, *args, **options):
        base_path = options["path"]
        if not base_path:
            raise ValueError("Provide --path or set CHEMKED_DATABASE_PATH in settings.")

        failed = 0
        if options["files"]:
            yaml_files = []
            for rel in options["files"]:
                p = Path(base_path) / rel
                if p.is_file():
                    yaml_files.append(p)
                else:
                    self.stderr.write(f"File not found, skipping: {p}")
                    failed += 1
        else:
            yaml_files = sorted(Path(base_path).rglob("*.yaml"))

        limit = options["limit"]
        if limit:
            yaml_files = yaml_files[:limit]

        for yaml_path in yaml_files:
            self.stdout.write(f"Processing {yaml_path}")
            if options["dry_run"]:
                continue
            try:
                self._import_file(yaml_path, base_path)
            except Exception as exc:
                self.stderr.write(f"Failed to import {yaml_path}: {exc}")
                failed += 1

        # Non-zero exit so the chemked-ingest workflow reports failed files
        if failed:
            raise CommandError(f"{failed} file(s) were not imported")

    def _import_file(self, yaml_path: Path, base_path: str):
        with open(yaml_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)

        rel_path = str(yaml_path.relative_to(base_path))

        try:
            experiment_type = experiment_type_of(data)
        except ValueError as exc:
            stored = ExperimentDataset.objects.filter(chemked_file_path=rel_path).first()
            if stored:
                raise ValueError(
                    f"{exc}; dataset {stored.pk} stored earlier for this file was left unchanged"
                ) from exc
            raise
        speciation = data.get("experiment-type") == SPECIATION_MEASUREMENT

        with transaction.atomic():
            dataset, created = ExperimentDataset.objects.get_or_create(
                chemked_file_path=rel_path,
                defaults={
                    "file_version": data.get("file-version", 0),
                    "chemked_version": data.get("chemked-version", "0.4.1"),
                    "experiment_type": experiment_type,
                },
            )
            # Re-ingesting an updated file replaces its datapoints instead of
            # appending a second copy.
            if not created:
                # The species of profiles belong to no composition, so they go first
                CompositionSpecies.objects.filter(
                    concentration_profiles__datapoint__dataset=dataset
                ).delete()
                dataset.datapoints.all().delete()

            apparatus_data = data.get("apparatus") or {}
            if apparatus_data:
                apparatus, _ = Apparatus.objects.get_or_create(
                    kind=apparatus_data.get("kind", ""),
                    institution=apparatus_data.get("institution", ""),
                    facility=apparatus_data.get("facility", ""),
                )
                mode_raw = apparatus_data.get("mode", [])
                if mode_raw:
                    if isinstance(mode_raw, list):
                        mode_str = ", ".join(
                            m.replace("-", " ") if isinstance(m, str) else str(m)
                            for m in mode_raw
                        )
                    else:
                        mode_str = str(mode_raw).replace("-", " ")
                    if apparatus.mode != mode_str:
                        apparatus.mode = mode_str
                        apparatus.save(update_fields=["mode"])
                dataset.apparatus = apparatus

            dataset.file_version = data.get("file-version", dataset.file_version)
            dataset.chemked_version = data.get("chemked-version", dataset.chemked_version)
            dataset.experiment_type = experiment_type
            dataset.reference_doi = (data.get("reference") or {}).get("doi", "")
            dataset.reference_journal = (data.get("reference") or {}).get("journal", "")
            dataset.reference_year = (data.get("reference") or {}).get("year")
            dataset.reference_volume = (data.get("reference") or {}).get("volume")
            dataset.reference_pages = (data.get("reference") or {}).get("pages", "")
            dataset.reference_detail = (data.get("reference") or {}).get("detail", "")
            dataset.comments = data.get("comments", [])
            dataset.save()

            dataset.file_authors.clear()
            for author in data.get("file-authors", []) or []:
                file_author, _ = FileAuthor.objects.get_or_create(
                    name=author.get("name", ""),
                    orcid=author.get("ORCID", ""),
                )
                dataset.file_authors.add(file_author)

            dataset.reference_authors.clear()
            for author in (data.get("reference") or {}).get("authors", []) or []:
                ref_author, _ = ReferenceAuthor.objects.get_or_create(
                    name=author.get("name", ""),
                    orcid=author.get("ORCID", ""),
                )
                dataset.reference_authors.add(ref_author)

            common_props = data.get("common-properties") or {}
            if common_props:
                common_obj, _ = CommonProperties.objects.get_or_create(dataset=dataset)
                common_obj.composition = create_composition(
                    common_props.get("composition"),
                    reporter=self.stderr.write,
                    context=f"{rel_path} common-properties",
                )
                ignition_type = common_props.get("ignition-type") or {}
                if experiment_type == ExperimentType.IGNITION_DELAY:
                    if not ignition_type or not ignition_type.get("target") or not ignition_type.get("type"):
                        self.stderr.write(
                            f"{rel_path} common-properties: ignition-type is required by schema"
                        )
                common_obj.ignition_target = ignition_type.get("target", "")
                common_obj.ignition_type = ignition_type.get("type", "")

                context = f"{rel_path} common-properties"

                pressure_raw = common_props.get("pressure")
                pressure_quantity = create_value_with_unit(pressure_raw)
                common_obj.pressure_quantity = pressure_quantity
                common_obj.pressure = si_value(pressure_quantity, "pressure", self.stderr.write, context)

                pressure_rise_raw = common_props.get("pressure-rise")
                pressure_rise_quantity = create_value_with_unit(pressure_rise_raw)
                common_obj.pressure_rise_quantity = pressure_rise_quantity
                common_obj.pressure_rise = si_value(
                    pressure_rise_quantity, "rate", self.stderr.write, context
                )

                temperature_raw = common_props.get("temperature")
                temperature_quantity = create_value_with_unit(temperature_raw)
                common_obj.temperature_quantity = temperature_quantity
                common_obj.temperature = si_value(
                    temperature_quantity, "temperature", self.stderr.write, context
                )

                equiv_raw = common_props.get("equivalence-ratio")
                equiv_quantity = create_value_with_unit(equiv_raw)
                common_obj.equivalence_ratio_quantity = equiv_quantity
                common_obj.equivalence_ratio = equiv_quantity.value if equiv_quantity else None

                reactor_vol_raw = common_props.get("reactor-volume")
                reactor_vol_quantity = create_value_with_unit(reactor_vol_raw)
                common_obj.reactor_volume_quantity = reactor_vol_quantity
                if reactor_vol_quantity:
                    common_obj.reactor_volume = si_value(
                        reactor_vol_quantity, "volume", self.stderr.write, context
                    )
                    common_obj.reactor_volume_units = "m3"

                residence_time_raw = common_props.get("residence-time")
                residence_time_quantity = create_value_with_unit(residence_time_raw)
                common_obj.residence_time_quantity = residence_time_quantity
                if residence_time_quantity:
                    common_obj.residence_time = si_value(
                        residence_time_quantity, "time", self.stderr.write, context
                    )
                    common_obj.residence_time_units = "s"

                # A burner-stabilized flame file may give the burning velocity of its flame
                lbv_quantity = create_value_with_unit(common_props.get("laminar-burning-velocity"))
                common_obj.laminar_burning_velocity_quantity = lbv_quantity

                flow_rate_raw = common_props.get("flow-rate")
                flow_rate_quantity = create_value_with_unit(flow_rate_raw)
                common_obj.flow_rate_quantity = flow_rate_quantity
                common_obj.flow_rate = si_value(flow_rate_quantity, "mass_flux", self.stderr.write, context)

                common_obj.save()

            for datapoint_data in data.get("datapoints", []) or []:
                temperature_quantity = create_value_with_unit(datapoint_data.get("temperature"))
                pressure_quantity = create_value_with_unit(datapoint_data.get("pressure"))
                ignition_delay_raw = datapoint_data.get("ignition-delay")
                first_stage_raw = datapoint_data.get("first-stage-ignition-delay")
                ignition_type = datapoint_data.get("ignition-type") or {}
                pressure_rise_raw = datapoint_data.get("pressure-rise")

                if dataset.experiment_type == ExperimentType.IGNITION_DELAY:
                    if not ignition_delay_raw:
                        self.stderr.write(
                            f"Skipping datapoint in {rel_path}: ignition-delay required by schema"
                        )
                        continue
                    if not ignition_type or not ignition_type.get("target") or not ignition_type.get("type"):
                        self.stderr.write(
                            f"Skipping datapoint in {rel_path}: ignition-type required by schema"
                        )
                        continue

                if speciation:
                    problem = speciation_problem(datapoint_data)
                    if problem:
                        self.stderr.write(f"Skipping datapoint in {rel_path}: {problem}")
                        continue

                if not temperature_quantity and not pressure_quantity:
                    self.stderr.write(
                        f"Skipping datapoint in {rel_path}: missing both temperature and pressure"
                    )
                    continue

                # Parse per-datapoint equivalence ratio
                equiv_raw = datapoint_data.get("equivalence-ratio")
                equiv_quantity = create_value_with_unit(equiv_raw) if equiv_raw is not None else None
                equiv_value = equiv_quantity.value if equiv_quantity else (
                    float(equiv_raw) if isinstance(equiv_raw, (int, float)) else None
                )

                # Parse per-datapoint residence time
                res_quantity = create_value_with_unit(datapoint_data.get("residence-time"))

                # Temperature and pressure are required numbers, so a datapoint whose unit
                # cannot be converted is skipped rather than stored in the wrong unit.
                try:
                    temperature = quantity_to_si(temperature_quantity, "temperature")
                    pressure = quantity_to_si(pressure_quantity, "pressure")
                except UnitConversionError as exc:
                    self.stderr.write(f"Skipping datapoint in {rel_path}: {exc}")
                    continue
                context = f"{rel_path} datapoint"

                datapoint = ExperimentDatapoint.objects.create(
                    dataset=dataset,
                    temperature=temperature if temperature is not None else 0.0,
                    pressure=pressure if pressure is not None else 0.0,
                    temperature_quantity=temperature_quantity,
                    pressure_quantity=pressure_quantity,
                    equivalence_ratio=equiv_value,
                    equivalence_ratio_quantity=equiv_quantity,
                    residence_time=si_value(res_quantity, "time", self.stderr.write, context),
                    residence_time_units="s",
                    composition=create_composition(
                        datapoint_data.get("composition"),
                        reporter=self.stderr.write,
                        context=f"{rel_path} datapoint",
                    ),
                    independent_variables=(
                        datapoint_data.get("independent-variables") if speciation else []
                    ),
                )

                # --- Experiment-type-specific extensions ---
                if speciation:
                    self._store_speciation(datapoint, datapoint_data, dataset.experiment_type, context)

                elif dataset.experiment_type == ExperimentType.IGNITION_DELAY:
                    ignition_payload = {
                        "ignition_delay": None,
                        "ignition_delay_quantity": create_value_with_unit(ignition_delay_raw),
                        "first_stage_ignition_delay": None,
                        "first_stage_ignition_delay_quantity": create_value_with_unit(first_stage_raw),
                        "ignition_target": ignition_type.get("target", ""),
                        "ignition_type": ignition_type.get("type", ""),
                        "pressure_rise": None,
                        "pressure_rise_quantity": create_value_with_unit(pressure_rise_raw),
                    }
                    for field, kind in (
                        ("ignition_delay", "time"),
                        ("first_stage_ignition_delay", "time"),
                        ("pressure_rise", "rate"),
                    ):
                        ignition_payload[field] = si_value(
                            ignition_payload[f"{field}_quantity"], kind, self.stderr.write, context
                        )
                    create_experiment_extension(datapoint, dataset.experiment_type, ignition_payload)

                elif dataset.experiment_type == ExperimentType.LAMINAR_BURNING_VELOCITY:
                    lbv_quantity = create_value_with_unit(datapoint_data.get("laminar-burning-velocity"))
                    lbv_payload = {
                        "laminar_burning_velocity": si_value(
                            lbv_quantity, "velocity", self.stderr.write, context
                        ),
                        "laminar_burning_velocity_quantity": lbv_quantity,
                    }
                    pr_quantity = create_value_with_unit(pressure_rise_raw)
                    if pr_quantity:
                        lbv_payload["pressure_rise"] = si_value(pr_quantity, "rate", self.stderr.write, context)
                        lbv_payload["pressure_rise_quantity"] = pr_quantity
                    create_experiment_extension(datapoint, dataset.experiment_type, lbv_payload)

                elif dataset.experiment_type == ExperimentType.JSR_MEASUREMENT:
                    measured_comp = create_composition(
                        datapoint_data.get("measured-composition"),
                        reporter=self.stderr.write,
                        context=f"{rel_path} JSR measured-composition",
                    )
                    jsr_payload = {"measured_composition": measured_comp}
                    create_experiment_extension(datapoint, dataset.experiment_type, jsr_payload)

                elif dataset.experiment_type == ExperimentType.OUTLET_CONCENTRATION:
                    measured_comp = create_composition(
                        datapoint_data.get("measured-composition"),
                        reporter=self.stderr.write,
                        context=f"{rel_path} outlet measured-composition",
                    )
                    ocm_payload = {"measured_composition": measured_comp}
                    ocm_res_quantity = create_value_with_unit(datapoint_data.get("residence-time"))
                    if ocm_res_quantity:
                        ocm_payload["residence_time"] = si_value(
                            ocm_res_quantity, "time", self.stderr.write, context
                        )
                        ocm_payload["residence_time_quantity"] = ocm_res_quantity
                    create_experiment_extension(datapoint, dataset.experiment_type, ocm_payload)

                elif dataset.experiment_type == ExperimentType.BSFS_MEASUREMENT:
                    measured_comp = create_composition(
                        datapoint_data.get("measured-composition"),
                        reporter=self.stderr.write,
                        context=f"{rel_path} BSFS measured-composition",
                    )
                    distance_quantity = create_value_with_unit(datapoint_data.get("distance"))
                    flow_rate_quantity = create_value_with_unit(datapoint_data.get("flow-rate"))
                    bsfs_payload = {
                        "measured_composition": measured_comp,
                        "distance": si_value(distance_quantity, "length", self.stderr.write, context),
                        "distance_quantity": distance_quantity,
                        "flow_rate": si_value(flow_rate_quantity, "mass_flux", self.stderr.write, context),
                        "flow_rate_quantity": flow_rate_quantity,
                    }
                    create_experiment_extension(datapoint, dataset.experiment_type, bsfs_payload)

                elif dataset.experiment_type == ExperimentType.CONCENTRATION_TIME_PROFILE:
                    create_experiment_extension(datapoint, dataset.experiment_type, {})

                rcm_data = datapoint_data.get("rcm-data") or {}
                if rcm_data:
                    rcm = RCMData.objects.create(
                        datapoint=datapoint,
                        compressed_temperature_quantity=create_value_with_unit(rcm_data.get("compressed-temperature")),
                        compressed_pressure_quantity=create_value_with_unit(rcm_data.get("compressed-pressure")),
                        compression_time_quantity=create_value_with_unit(rcm_data.get("compression-time")),
                        stroke_quantity=create_value_with_unit(rcm_data.get("stroke")),
                        clearance_quantity=create_value_with_unit(rcm_data.get("clearance")),
                        compression_ratio_quantity=create_value_with_unit(rcm_data.get("compression-ratio")),
                    )
                    for field, kind in (
                        ("compressed_temperature", "temperature"),
                        ("compressed_pressure", "pressure"),
                        ("compression_time", "time"),
                        ("stroke", "length"),
                        ("clearance", "length"),
                    ):
                        quantity = getattr(rcm, f"{field}_quantity")
                        if quantity:
                            setattr(rcm, field, si_value(quantity, kind, self.stderr.write, f"{context} rcm-data"))
                    if rcm.compression_ratio_quantity:
                        rcm.compression_ratio = rcm.compression_ratio_quantity.value
                    rcm.save()

                for history in datapoint_data.get("time-histories", []) or []:
                    values = history.get("values")
                    if isinstance(values, dict):
                        TimeHistory.objects.create(
                            datapoint=datapoint,
                            history_type=history.get("type"),
                            time_units=(history.get("time") or {}).get("units", ""),
                            quantity_units=(history.get("quantity") or {}).get("units", ""),
                            values=None,
                            source_filename=values.get("filename", ""),
                        )
                    else:
                        TimeHistory.objects.create(
                            datapoint=datapoint,
                            history_type=history.get("type"),
                            time_units=(history.get("time") or {}).get("units", ""),
                            quantity_units=(history.get("quantity") or {}).get("units", ""),
                            values=time_first(values, history.get("time"), history.get("quantity")),
                        )

                volume_history = datapoint_data.get("volume-history") or {}
                if volume_history:
                    VolumeHistory.objects.create(
                        datapoint=datapoint,
                        time_units=(volume_history.get("time") or {}).get("units", ""),
                        volume_units=(volume_history.get("volume") or {}).get("units", ""),
                        values=time_first(
                            volume_history.get("values", []),
                            volume_history.get("time"),
                            volume_history.get("volume"),
                        ),
                    )

            # A file none of whose datapoints could be stored is not imported, so it leaves
            # no dataset without datapoints (an updated file leaves the stored one unchanged)
            if not dataset.datapoints.exists():
                raise ValueError("no datapoint could be stored")

    def _store_speciation(
        self,
        datapoint: ExperimentDatapoint,
        datapoint_data: Dict[str, Any],
        experiment_type: str,
        context: str,
    ):
        """Store a ChemKED speciation datapoint's profiles and its reactor's extension row.

        Profiles keep the file's species name and identifiers, units, rows and uncertainty
        block unchanged; the independent variables are on the datapoint.
        """
        report = self.stderr.write
        time_units = next(
            (
                variable.get("units", "")
                for variable in datapoint_data.get("independent-variables") or []
                if variable.get("name") == "time"
            ),
            "",
        )

        payload: Dict[str, Any] = {}
        if experiment_type == ExperimentType.JSR_MEASUREMENT:
            quantity = create_value_with_unit(datapoint_data.get("environment-temperature"))
            if quantity:
                payload["environment_temperature"] = si_value(quantity, "temperature", report, context)
                payload["environment_temperature_quantity"] = quantity
        elif experiment_type == ExperimentType.OUTLET_CONCENTRATION:
            quantity = create_value_with_unit(datapoint_data.get("residence-time"))
            if quantity:
                payload["residence_time"] = si_value(quantity, "time", report, context)
                payload["residence_time_quantity"] = quantity
            quantity = create_value_with_unit(datapoint_data.get("volumetric-flow-in-reference-state"))
            if quantity:
                payload["volumetric_flow_in_reference_state"] = si_value(
                    quantity, "volumetric_flow", report, context
                )
                payload["volumetric_flow_quantity"] = quantity
        elif experiment_type == ExperimentType.BSFS_MEASUREMENT:
            quantity = create_value_with_unit(datapoint_data.get("flow-rate"))
            if quantity:
                payload["flow_rate"] = si_value(quantity, "mass_flux", report, context)
                payload["flow_rate_quantity"] = quantity
        elif experiment_type == ExperimentType.CONCENTRATION_TIME_PROFILE:
            # The profiles are ConcentrationProfile rows, not this record's single profile
            payload = {"time_units": time_units, "quantity_units": "", "values": []}
            time_shift = datapoint_data.get("time-shift") or {}
            if time_shift:
                amount = create_value_with_unit(time_shift.get("amount"))
                payload.update({
                    "timeshift_target": time_shift.get("target", ""),
                    "timeshift_type": time_shift.get("type", ""),
                    "timeshift_amount": amount.value if amount else None,
                    "timeshift_amount_quantity": amount,
                })
        create_experiment_extension(datapoint, experiment_type, payload)

        for profile in datapoint_data.get("concentration-profiles") or []:
            species = CompositionSpecies.objects.create(
                composition=None,
                species_name=profile["species-name"],
                inchi=profile.get("InChI", ""),
                smiles=profile.get("SMILES", ""),
                amount=None,
            )
            ConcentrationProfile.objects.create(
                datapoint=datapoint,
                species=species,
                time_units=time_units,
                quantity_units=profile["quantity"]["units"],
                values=profile["values"],
                uncertainty=profile_uncertainty(profile.get("uncertainty")),
            )

        for profile in datapoint_data.get("auxiliary-profiles") or []:
            independent = profile.get("independent") or {}
            AuxiliaryProfile.objects.create(
                datapoint=datapoint,
                profile_type=profile.get("type", ""),
                independent_name=independent.get("name", ""),
                independent_units=independent.get("units", ""),
                quantity_units=(profile.get("quantity") or {}).get("units", ""),
                values=profile.get("values") or [],
            )
