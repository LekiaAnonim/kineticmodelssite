from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from chemked_database.import_dispatcher import create_experiment_extension
from chemked_database.models import (
    Apparatus,
    CommonProperties,
    Composition,
    CompositionSpecies,
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
from chemked_database.utils.chemistry import infer_smiles_and_atomic_composition

VALUE_UNIT_RE = re.compile(r"^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(.*)$")
COMPOSITION_KINDS = {"mass fraction", "mole fraction", "mole percent"}


def parse_value_unit(raw: Any) -> Tuple[Optional[float], str, Dict[str, Any]]:
    """
    Parse PyKED value-unit schema (list or string) into value + units + uncertainty.
    Returns: (value, units, extra_fields)
    """
    if raw is None:
        return None, "", {}

    value = None
    units = ""
    extra: Dict[str, Any] = {}

    if isinstance(raw, list):
        if not raw:
            return None, "", {}
        value_part = raw[0]
        if isinstance(value_part, (int, float)):
            value = float(value_part)
        elif isinstance(value_part, str):
            match = VALUE_UNIT_RE.match(value_part)
            if match:
                value = float(match.group(1))
                units = match.group(2).strip()
            else:
                extra["value_text"] = value_part
        if len(raw) > 1 and isinstance(raw[1], dict):
            uncertainty_raw = raw[1].get("uncertainty")
            upper_raw = raw[1].get("upper-uncertainty")
            lower_raw = raw[1].get("lower-uncertainty")

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

            uncertainty_value, uncertainty_text = parse_uncertainty(uncertainty_raw)
            upper_value, upper_text = parse_uncertainty(upper_raw)
            lower_value, lower_text = parse_uncertainty(lower_raw)

            extra.update({
                "uncertainty_type": raw[1].get("uncertainty-type", ""),
                "uncertainty": uncertainty_value,
                "upper_uncertainty": upper_value,
                "lower_uncertainty": lower_value,
                "uncertainty_text": uncertainty_text or upper_text or lower_text or "",
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


def create_value_with_unit(raw: Any) -> Optional[ValueWithUnit]:
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
    )


def create_composition(
    composition_data: Optional[Dict[str, Any]],
    reporter: Optional[Callable[[str], None]] = None,
    context: str = "composition",
) -> Optional[Composition]:
    if not composition_data:
        return None

    def report(message: str) -> None:
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
        has_identifier = bool(
            species.get("InChI")
            or species.get("SMILES")
            or (species.get("atomic-composition") or [])
        )
        return has_identifier

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
        amount_upper = None
        amount_lower = None

        if amount_list:
            amount_value = float(amount_list[0])
        if len(amount_list) > 1 and isinstance(amount_list[1], dict):
            amount_uncertainty_type = amount_list[1].get("uncertainty-type", "")
            amount_uncertainty = amount_list[1].get("uncertainty")
            amount_upper = amount_list[1].get("upper-uncertainty")
            amount_lower = amount_list[1].get("lower-uncertainty")

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
            amount_upper_uncertainty=amount_upper,
            amount_lower_uncertainty=amount_lower,
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

        if options["files"]:
            yaml_files = []
            for rel in options["files"]:
                p = Path(base_path) / rel
                if p.is_file():
                    yaml_files.append(p)
                else:
                    self.stderr.write(f"File not found, skipping: {p}")
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

    def _import_file(self, yaml_path: Path, base_path: str):
        with open(yaml_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)

        rel_path = str(yaml_path.relative_to(base_path))

        with transaction.atomic():
            dataset, _ = ExperimentDataset.objects.get_or_create(
                chemked_file_path=rel_path,
                defaults={
                    "file_version": data.get("file-version", 0),
                    "chemked_version": data.get("chemked-version", "0.4.1"),
                    "experiment_type": data.get("experiment-type", ExperimentType.IGNITION_DELAY),
                },
            )

            apparatus_data = data.get("apparatus") or {}
            if apparatus_data:
                apparatus, _ = Apparatus.objects.get_or_create(
                    kind=apparatus_data.get("kind", ""),
                    institution=apparatus_data.get("institution", ""),
                    facility=apparatus_data.get("facility", ""),
                )
                dataset.apparatus = apparatus

            dataset.file_version = data.get("file-version", dataset.file_version)
            dataset.chemked_version = data.get("chemked-version", dataset.chemked_version)
            experiment_type = data.get("experiment-type", dataset.experiment_type)
            if experiment_type not in ExperimentType.values:
                self.stderr.write(
                    f"Unknown experiment-type '{experiment_type}' in {rel_path};"
                    f" defaulting to {ExperimentType.IGNITION_DELAY}"
                )
                experiment_type = ExperimentType.IGNITION_DELAY
            dataset.experiment_type = experiment_type
            dataset.reference_doi = (data.get("reference") or {}).get("doi", "")
            dataset.reference_journal = (data.get("reference") or {}).get("journal", "")
            dataset.reference_year = (data.get("reference") or {}).get("year")
            dataset.reference_volume = (data.get("reference") or {}).get("volume")
            dataset.reference_pages = (data.get("reference") or {}).get("pages", "")
            dataset.reference_detail = (data.get("reference") or {}).get("detail", "")
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
                if not ignition_type or not ignition_type.get("target") or not ignition_type.get("type"):
                    self.stderr.write(
                        f"{rel_path} common-properties: ignition-type is required by schema"
                    )
                common_obj.ignition_target = ignition_type.get("target", "")
                common_obj.ignition_type = ignition_type.get("type", "")

                pressure_raw = common_props.get("pressure")
                pressure_quantity = create_value_with_unit(pressure_raw)
                common_obj.pressure_quantity = pressure_quantity
                common_obj.pressure = pressure_quantity.value if pressure_quantity else None

                pressure_rise_raw = common_props.get("pressure-rise")
                pressure_rise_quantity = create_value_with_unit(pressure_rise_raw)
                common_obj.pressure_rise_quantity = pressure_rise_quantity
                common_obj.pressure_rise = pressure_rise_quantity.value if pressure_rise_quantity else None

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

                if not temperature_quantity or not pressure_quantity:
                    self.stderr.write(
                        f"Skipping datapoint in {rel_path}: missing temperature/pressure"
                    )
                    continue

                datapoint = ExperimentDatapoint.objects.create(
                    dataset=dataset,
                    temperature=temperature_quantity.value if temperature_quantity else 0.0,
                    pressure=pressure_quantity.value if pressure_quantity else 0.0,
                    temperature_quantity=temperature_quantity,
                    pressure_quantity=pressure_quantity,
                    equivalence_ratio=datapoint_data.get("equivalence-ratio"),
                    composition=create_composition(
                        datapoint_data.get("composition"),
                        reporter=self.stderr.write,
                        context=f"{rel_path} datapoint",
                    ),
                )

                if dataset.experiment_type == ExperimentType.IGNITION_DELAY:
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
                    if ignition_payload["ignition_delay_quantity"]:
                        ignition_payload["ignition_delay"] = ignition_payload["ignition_delay_quantity"].value
                    if ignition_payload["first_stage_ignition_delay_quantity"]:
                        ignition_payload["first_stage_ignition_delay"] = ignition_payload[
                            "first_stage_ignition_delay_quantity"
                        ].value
                    if ignition_payload["pressure_rise_quantity"]:
                        ignition_payload["pressure_rise"] = ignition_payload["pressure_rise_quantity"].value
                    create_experiment_extension(datapoint, dataset.experiment_type, ignition_payload)

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
                    if rcm.compressed_temperature_quantity:
                        rcm.compressed_temperature = rcm.compressed_temperature_quantity.value
                    if rcm.compressed_pressure_quantity:
                        rcm.compressed_pressure = rcm.compressed_pressure_quantity.value
                    if rcm.compression_time_quantity:
                        rcm.compression_time = rcm.compression_time_quantity.value
                    if rcm.stroke_quantity:
                        rcm.stroke = rcm.stroke_quantity.value
                    if rcm.clearance_quantity:
                        rcm.clearance = rcm.clearance_quantity.value
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
                            values=values,
                        )

                volume_history = datapoint_data.get("volume-history") or {}
                if volume_history:
                    VolumeHistory.objects.create(
                        datapoint=datapoint,
                        time_units=(volume_history.get("time") or {}).get("units", ""),
                        volume_units=(volume_history.get("volume") or {}).get("units", ""),
                        values=volume_history.get("values", []),
                    )
