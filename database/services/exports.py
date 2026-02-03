import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass

from django.utils.text import slugify


class ExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportResult:
    content: bytes
    filename: str
    content_type: str


def _read_file_field(file_field):
    if not file_field:
        return None
    file_field.open("rb")
    try:
        return file_field.read()
    finally:
        file_field.close()


def _build_zip(files):
    if not files:
        raise ExportError("No Chemkin files are available for this model.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return buffer.getvalue()


def _get_filename_with_fallback(file_field, fallback_name):
    """Get the original filename from a file field, or use fallback with .txt extension."""
    if file_field and hasattr(file_field, 'name') and file_field.name:
        # Extract just the filename from the path
        return os.path.basename(file_field.name)
    return f"{fallback_name}.txt"


def build_chemkin_bundle(kinetic_model, strict=False):
    files = {}
    reactions = _read_file_field(kinetic_model.chemkin_reactions_file)
    if reactions:
        filename = _get_filename_with_fallback(
            kinetic_model.chemkin_reactions_file, "chemkin_reactions"
        )
        files[filename] = reactions
    thermo = _read_file_field(kinetic_model.chemkin_thermo_file)
    if thermo:
        filename = _get_filename_with_fallback(
            kinetic_model.chemkin_thermo_file, "chemkin_thermo"
        )
        files[filename] = thermo
    transport = _read_file_field(kinetic_model.chemkin_transport_file)
    if transport:
        filename = _get_filename_with_fallback(
            kinetic_model.chemkin_transport_file, "chemkin_transport"
        )
        files[filename] = transport

    if not files:
        files = _generate_chemkin_files(kinetic_model, strict=strict)

    content = _build_zip(files)
    slug = slugify(kinetic_model.model_name or str(kinetic_model.pk))
    filename = f"{slug or kinetic_model.pk}_chemkin.zip"
    return ExportResult(content=content, filename=filename, content_type="application/zip")


def build_cantera_yaml(kinetic_model, strict=False):
    reactions = _read_file_field(kinetic_model.chemkin_reactions_file)
    thermo = _read_file_field(kinetic_model.chemkin_thermo_file)
    transport = _read_file_field(kinetic_model.chemkin_transport_file)

    if not reactions:
        generated = _generate_chemkin_files(kinetic_model, strict=strict)
        # Find the generated files (they have model name prefix)
        reactions = next((v for k, v in generated.items() if k.endswith("_chem.inp")), None)
        transport = next((v for k, v in generated.items() if k.endswith("_tran.dat")), None)
        # Thermo is embedded in chem.inp for generated files
        thermo = None

    if not reactions:
        raise ExportError("Chemkin reactions file is required to build Cantera YAML.")

    with tempfile.TemporaryDirectory() as tempdir:
        input_path = os.path.join(tempdir, "chem.inp")
        with open(input_path, "wb") as handle:
            handle.write(reactions)

        thermo_path = ""
        if thermo:
            thermo_path = os.path.join(tempdir, "thermo.dat")
            with open(thermo_path, "wb") as handle:
                handle.write(thermo)

        transport_path = ""
        if transport:
            transport_path = os.path.join(tempdir, "transport.dat")
            with open(transport_path, "wb") as handle:
                handle.write(transport)

        slug = slugify(kinetic_model.model_name or str(kinetic_model.pk))
        output_path = os.path.join(tempdir, f"{slug or kinetic_model.pk}.yaml")

        _run_ck2yaml(input_path, thermo_path, transport_path, output_path)

        with open(output_path, "rb") as handle:
            content = handle.read()

    filename = os.path.basename(output_path)
    return ExportResult(content=content, filename=filename, content_type="application/x-yaml")


def _generate_chemkin_files(kinetic_model, strict=False):
    try:
        from rmgpy.chemkin import save_chemkin_file, save_transport_file
        from rmgpy.thermo import NASAPolynomial, NASA
        from rmgpy.transport import TransportData
        from rmgpy.reaction import Reaction as RmgReaction
        from rmgpy.species import Species as RmgSpecies
    except Exception as exc:
        try:
            from rmgpy.chemkin import saveChemkinFile as save_chemkin_file
            from rmgpy.chemkin import saveTransportFile as save_transport_file
            from rmgpy.thermo import NASAPolynomial, NASA
            from rmgpy.transport import TransportData
            from rmgpy.reaction import Reaction as RmgReaction
            from rmgpy.species import Species as RmgSpecies
        except Exception as inner_exc:
            raise ExportError(
                "Chemkin generation requires RMG-Py to be installed."
            ) from inner_exc

    species_map, missing_species = _build_rmg_species_map(
        kinetic_model, NASAPolynomial, NASA, TransportData, RmgSpecies
    )
    if strict and missing_species:
        sample = ", ".join(str(species_id) for species_id in missing_species[:5])
        suffix = "" if len(missing_species) <= 5 else "..."
        raise ExportError(
            "Strict Chemkin generation failed because required species are missing thermo data: "
            f"{sample}{suffix}."
        )

    reactions = _build_rmg_reactions(kinetic_model, species_map, RmgReaction, strict=strict)

    if not species_map or not reactions:
        if missing_species:
            sample = ", ".join(str(species_id) for species_id in missing_species[:5])
            suffix = "" if len(missing_species) <= 5 else "..."
            raise ExportError(
                "Chemkin generation failed because required species are missing thermo data: "
                f"{sample}{suffix}."
            )
        raise ExportError("Chemkin generation failed: no species or reactions available.")

    # Create filename prefix from model name
    model_slug = slugify(kinetic_model.model_name or "") or str(kinetic_model.pk)

    with tempfile.TemporaryDirectory() as tempdir:
        reactions_path = os.path.join(tempdir, "chem.inp")
        save_chemkin_file(reactions_path, list(species_map.values()), reactions, verbose=False)

        transport_path = None
        if any(getattr(spec, "transport_data", None) for spec in species_map.values()):
            transport_path = os.path.join(tempdir, "tran.dat")
            save_transport_file(transport_path, list(species_map.values()))

        with open(reactions_path, "rb") as handle:
            reactions_content = handle.read()

        # Use model name prefix with standard Chemkin extensions for generated files
        files = {f"{model_slug}_chem.inp": reactions_content}
        if transport_path:
            with open(transport_path, "rb") as handle:
                files[f"{model_slug}_tran.dat"] = handle.read()

    return files


def _build_rmg_species_map(kinetic_model, nasa_poly_cls, nasa_cls, transport_cls, rmg_species_cls):
    from database.models import Thermo, Transport

    species_map = {}
    labels = set()

    def assign_label(db_species, index):
        name = None
        if hasattr(db_species, "names"):
            names = sorted(n for n in db_species.names if n)
            if names:
                name = names[0]
        candidate = name or db_species.formula or db_species.prime_id or f"S{index}"
        candidate = str(candidate).replace(" ", "")
        if len(candidate) > 16:
            candidate = f"S{index}"
        label = candidate
        suffix = 1
        while label in labels:
            label = f"{candidate[:14]}{suffix:02d}"
            suffix += 1
        labels.add(label)
        return label

    species_list = list(kinetic_model.species.all())
    reaction_species = {
        sp
        for kinetics_comment in kinetic_model.kineticscomment_set.select_related("kinetics__reaction")
        for sp in kinetics_comment.kinetics.reaction.species.all()
    }
    for sp in reaction_species:
        if sp not in species_list:
            species_list.append(sp)

    species_ids = [species.id for species in species_list]
    thermo_map = {
        thermo.species_id: thermo
        for thermo in Thermo.objects.filter(species_id__in=species_ids).select_related("species")
    }
    transport_map = {
        transport.species_id: transport
        for transport in Transport.objects.filter(species_id__in=species_ids).select_related("species")
    }
    missing_thermo = []

    for index, db_species in enumerate(species_list, start=1):
        rmg_species = rmg_species_cls(index=index, label=assign_label(db_species, index))
        rmg_species.molecule = [structure.to_rmg() for structure in db_species.structures]

        thermo = thermo_map.get(db_species.id)
        if thermo is None:
            missing_thermo.append(db_species.id)
            continue

        rmg_species.thermo = nasa_cls(
            polynomials=[
                nasa_poly_cls(
                    Tmin=(thermo.temp_min_1, "K"),
                    Tmax=(thermo.temp_max_1, "K"),
                    coeffs=thermo.coeffs_poly1,
                ),
                nasa_poly_cls(
                    Tmin=(thermo.temp_min_2, "K"),
                    Tmax=(thermo.temp_max_2, "K"),
                    coeffs=thermo.coeffs_poly2,
                ),
            ],
            Tmin=(thermo.temp_min_1, "K"),
            Tmax=(thermo.temp_max_2, "K"),
        )

        transport = transport_map.get(db_species.id)
        if transport:
            rmg_species.transport_data = transport_cls(
                shapeIndex=int(transport.geometry or 0),
                epsilon=(transport.potential_well_depth, "K"),
                sigma=(transport.collision_diameter, "angstrom"),
                dipoleMoment=(transport.dipole_moment, "debye"),
                polarizability=(transport.polarizability, "angstrom^3"),
                rotrelaxcollnum=transport.rotational_relaxation,
                comment="database",
            )
            rmg_species.transportData = rmg_species.transport_data

        species_map[db_species.id] = rmg_species

    return species_map, missing_thermo


def _build_rmg_reactions(kinetic_model, species_map, rmg_reaction_cls, strict=False):
    reactions = []
    missing_species = set()
    for kinetics_comment in kinetic_model.kineticscomment_set.select_related(
        "kinetics__reaction"
    ):
        kinetics = kinetics_comment.kinetics
        reaction = kinetics.reaction
        try:
            reactants = [species_map[sp.id] for sp in reaction.reactants()]
            products = [species_map[sp.id] for sp in reaction.products()]
        except KeyError:
            if strict:
                for sp in list(reaction.reactants()) + list(reaction.products()):
                    if sp.id not in species_map:
                        missing_species.add(sp.id)
            continue
        rmg_reaction = rmg_reaction_cls(
            reactants=reactants,
            products=products,
            reversible=reaction.reversible,
        )
        rmg_reaction.index = kinetics.id
        efficiencies = list(kinetics.efficiency_set.select_related("species"))
        rmg_reaction.kinetics = kinetics.data.to_rmg(
            kinetics.min_temp,
            kinetics.max_temp,
            kinetics.min_pressure,
            kinetics.max_pressure,
            efficiencies,
        )
        if not strict:
            _normalize_kinetics_units(rmg_reaction.kinetics, len(reactants))
        reactions.append(rmg_reaction)
    if strict and missing_species:
        sample = ", ".join(str(species_id) for species_id in sorted(missing_species)[:5])
        suffix = "" if len(missing_species) <= 5 else "..."
        raise ExportError(
            "Strict Chemkin generation failed because reactions reference species without thermo data: "
            f"{sample}{suffix}."
        )
    return reactions


def _normalize_kinetics_units(rmg_kinetics, reaction_order):
    from rmgpy.quantity import ScalarQuantity
    from rmgpy import kinetics as rmg_kinetics_module

    unit_map = {1: "s^-1", 2: "cm^3/(mol*s)", 3: "cm^6/(mol^2*s)"}
    expected_units = unit_map.get(reaction_order)
    if not expected_units:
        return

    multi_pdep_cls = getattr(rmg_kinetics_module, "MultiPdepArrhenius", None)
    multi_pdep_cls_alt = getattr(rmg_kinetics_module, "MultiPDepArrhenius", None)
    multi_pdep_types = tuple(
        cls for cls in (multi_pdep_cls, multi_pdep_cls_alt) if cls is not None
    )

    def normalize_arrhenius(arrhenius_obj, expected):
        if not expected:
            return
        if not hasattr(arrhenius_obj, "A"):
            return
        current_units = getattr(arrhenius_obj.A, "units", None)
        current_units_str = str(current_units) if current_units is not None else None
        if not current_units_str or current_units_str == expected:
            return
        value = arrhenius_obj.A.value
        uncertainty = getattr(arrhenius_obj.A, "uncertainty", None)
        if uncertainty:
            arrhenius_obj.A = ScalarQuantity(value, expected, uncertainty)
        else:
            arrhenius_obj.A = ScalarQuantity(value, expected)

    expected_units_low = unit_map.get(reaction_order + 1)

    if isinstance(rmg_kinetics, rmg_kinetics_module.Arrhenius):
        normalize_arrhenius(rmg_kinetics, expected_units)
    elif isinstance(rmg_kinetics, rmg_kinetics_module.MultiArrhenius):
        for arr in rmg_kinetics.arrhenius:
            normalize_arrhenius(arr, expected_units)
    elif isinstance(rmg_kinetics, rmg_kinetics_module.PDepArrhenius):
        for arr in rmg_kinetics.arrhenius:
            normalize_arrhenius(arr, expected_units)
    elif multi_pdep_types and isinstance(rmg_kinetics, multi_pdep_types):
        for arr in rmg_kinetics.arrhenius:
            normalize_arrhenius(arr, expected_units)
    elif isinstance(rmg_kinetics, rmg_kinetics_module.Lindemann):
        normalize_arrhenius(rmg_kinetics.arrheniusHigh, expected_units)
        normalize_arrhenius(rmg_kinetics.arrheniusLow, expected_units_low)
    elif isinstance(rmg_kinetics, rmg_kinetics_module.Troe):
        normalize_arrhenius(rmg_kinetics.arrheniusHigh, expected_units)
        normalize_arrhenius(rmg_kinetics.arrheniusLow, expected_units_low)
    elif isinstance(rmg_kinetics, rmg_kinetics_module.ThirdBody):
        normalize_arrhenius(rmg_kinetics.arrheniusLow, expected_units_low)


def _run_ck2yaml(input_path, thermo_path, transport_path, output_path):
    args = ["--input", input_path, "--output", output_path, "--no-validate", "--quiet"]
    if thermo_path:
        args.extend(["--thermo", thermo_path])
    if transport_path:
        args.extend(["--transport", transport_path])

    try:
        from cantera import ck2yaml

        ck2yaml.main(args)
        return
    except Exception:
        pass

    ck2yaml_executable = shutil.which("ck2yaml")
    if ck2yaml_executable:
        command = [ck2yaml_executable, *args]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise ExportError(
                "Cantera conversion failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return

    raise ExportError(
        "Cantera conversion is unavailable. Install Cantera or provide the ck2yaml CLI."
    )
