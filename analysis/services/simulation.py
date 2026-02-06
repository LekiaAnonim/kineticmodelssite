"""
Analysis Services - Simulation Runner

Core PyTeCK simulation execution logic extracted from notebook.
"""

import os
import tempfile
import logging
import yaml
from collections import OrderedDict
from typing import Optional, Dict, List, Any, Tuple

import cantera as ct
from django.conf import settings

from database.models import KineticModel, SpeciesName
from database.services.exports import build_cantera_yaml
from chemked_database.models import ExperimentDataset, CompositionSpecies

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mechanism Export
# ---------------------------------------------------------------------------

def get_cantera_mechanism_from_model(kinetic_model: KineticModel) -> Optional[str]:
    """
    Export a KineticModel from the database to a Cantera YAML file.
    
    Args:
        kinetic_model: KineticModel instance
        
    Returns:
        Path to the temporary YAML file, or None if export failed
    """
    try:
        result = build_cantera_yaml(kinetic_model)
        
        # Save to a temporary file
        temp_dir = tempfile.mkdtemp(prefix='pyteck_mech_')
        yaml_path = os.path.join(temp_dir, result.filename)
        
        with open(yaml_path, 'wb') as f:
            f.write(result.content)
        
        logger.info(f"Exported mechanism to {yaml_path}")
        return yaml_path
        
    except Exception as e:
        logger.error(f"Error exporting model {kinetic_model}: {e}")
        return None


def get_mechanism_species_names(mechanism_path: str) -> List[str]:
    """
    Load a Cantera mechanism and return list of species names.
    
    Args:
        mechanism_path: Path to Cantera YAML file
        
    Returns:
        List of species names in the mechanism
    """
    try:
        solution = ct.Solution(mechanism_path)
        return list(solution.species_names)
    except Exception as e:
        logger.error(f"Error loading mechanism {mechanism_path}: {e}")
        return []


# ---------------------------------------------------------------------------
# ChemKED Dataset Path Resolution
# ---------------------------------------------------------------------------

def _find_file_in_tree(root_dir: str, rel_path: str) -> Optional[str]:
    """Try to locate rel_path under root_dir."""
    candidate = os.path.join(root_dir, rel_path)
    if os.path.exists(candidate):
        return candidate

    # Fallback: search by filename in tree
    filename = os.path.basename(rel_path)
    for dirpath, _, filenames in os.walk(root_dir):
        if filename in filenames:
            return os.path.join(dirpath, filename)

    return None


def get_chemked_dataset_path(
    dataset: ExperimentDataset,
    base_dir: Optional[str] = None,
    search_dirs: Optional[List[str]] = None
) -> Optional[str]:
    """
    Return the full file path for a ChemKED dataset.

    Args:
        dataset: ExperimentDataset instance or a chemked_file_path string
        base_dir: Optional base directory override
        search_dirs: Optional list of directories to search
        
    Returns:
        Full path to the ChemKED YAML file, or None if not found
    """
    rel_path = dataset.chemked_file_path if hasattr(dataset, "chemked_file_path") else str(dataset)

    if base_dir is None:
        base_dir = (
            getattr(settings, "CHEMKED_DATA_ROOT", None)
            or os.getenv("CHEMKED_DATA_ROOT")
        )

    # Fallback candidates
    if not base_dir:
        base_dir_setting = getattr(settings, "BASE_DIR", "")
        media_root = getattr(settings, "MEDIA_ROOT", "")
        candidates = [
            os.path.join(base_dir_setting, "chemked_database", "chemked_data"),
            os.path.join(base_dir_setting, "chemked_database", "results"),
            os.path.join(base_dir_setting, "..", "ChemKED-database"),
            os.path.join(media_root, "chemked"),
            os.path.join(media_root, "chemked_database"),
        ]
    else:
        candidates = [base_dir]

    if search_dirs:
        candidates.extend(search_dirs)

    for root_dir in [c for c in candidates if c]:
        root_dir = os.path.abspath(root_dir)
        if os.path.exists(root_dir):
            match = _find_file_in_tree(root_dir, rel_path)
            if match:
                return match

    return None


def get_chemked_root_dir() -> str:
    """Get the ChemKED database root directory."""
    base_dir = getattr(settings, "BASE_DIR", "")
    candidates = [
        getattr(settings, "CHEMKED_DATA_ROOT", None),
        os.getenv("CHEMKED_DATA_ROOT"),
        os.path.join(base_dir, "..", "ChemKED-database"),
        os.path.join(base_dir, "chemked_database", "chemked_data"),
    ]
    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            return os.path.abspath(candidate)
    
    # Default fallback
    return os.path.abspath(os.path.join(base_dir, "..", "ChemKED-database"))


# ---------------------------------------------------------------------------
# Species Mapping
# ---------------------------------------------------------------------------

def _best_species_label(species_name_obj) -> str:
    """Pick a stable label from a SpeciesName object."""
    if species_name_obj.name:
        return species_name_obj.name
    names = sorted(getattr(species_name_obj.species, "names", []) or [])
    if names:
        return names[0]
    formula = getattr(species_name_obj.species, "formula", None)
    if formula:
        return formula
    return str(species_name_obj.species_id)


def _normalize_label(label: str) -> str:
    """Normalize species label for comparison."""
    return "".join(ch for ch in label.upper() if ch.isalnum())


def _best_normalized_match(target: str, normalized_candidates: Dict[str, str]) -> Optional[str]:
    """Find best candidate whose normalized name matches target.
    
    Prefers:
    1. Exact match (always wins)
    2. Prefix match with smallest length diff (e.g. O2 matches O225 not CO22)
    3. Substring match with smallest length diff
    """
    if not target:
        return None
    best = None
    best_len_diff = float('inf')
    best_is_prefix = False
    for norm, original in normalized_candidates.items():
        if target == norm:
            return original  # Exact match always wins
        if target in norm or norm in target:
            diff = abs(len(norm) - len(target))
            is_prefix = norm.startswith(target) or target.startswith(norm)
            # Prefer prefix matches over substring matches;
            # among same type, prefer smaller length diff
            if (is_prefix and not best_is_prefix) or \
               (is_prefix == best_is_prefix and diff < best_len_diff):
                best = original
                best_len_diff = diff
                best_is_prefix = is_prefix
    return best


def get_species_label_smiles_map(model: KineticModel) -> OrderedDict:
    """
    Return OrderedDict of {label: smiles} for a KineticModel.
    """
    label_smiles = OrderedDict()

    for sn in SpeciesName.objects.filter(kinetic_model=model).select_related("species"):
        label = _best_species_label(sn)
        smiles = None

        for struct in sn.species.structures:
            if getattr(struct, "smiles", None):
                smiles = struct.smiles
                break

        label_smiles[label] = smiles or label

    return label_smiles


def get_dataset_species_map(dataset: ExperimentDataset) -> OrderedDict:
    """Return {species_name: smiles_or_name} for a ChemKED dataset."""
    species_map = OrderedDict()
    if not dataset:
        return species_map
        
    dp = dataset.datapoints.first()
    if not dp or not dp.composition:
        return species_map

    for sp in dp.composition.species.all():
        key = sp.species_name
        value = sp.smiles or sp.species_name
        species_map[key] = value

    return species_map


def build_spec_keys_for_dataset(
    model: KineticModel,
    dataset: ExperimentDataset,
    model_species_names: Optional[List[str]] = None
) -> OrderedDict:
    """
    Build mapping of dataset species -> model species label.
    
    Uses a multi-step strategy:
    1. InChI-based matching (robust: handles different SMILES for same molecule)
    2. Exact normalized label matching
    3. Substring-based normalized matching
    4. Direct label matching
    """
    model_label_smiles = get_species_label_smiles_map(model)

    # Build SMILES -> database label map
    smiles_to_label = {smiles: label for label, smiles in model_label_smiles.items() if smiles}

    normalized_model_names = {}
    # Also build a map from base name (without index suffix) to mechanism name.
    # Mechanism names follow the pattern "label(index)" e.g. "O2(25)", "sc4h9oh(55)".
    # Stripping the "(index)" gives the base name used during export.
    import re
    base_to_mech: Dict[str, str] = {}
    if model_species_names:
        for name in model_species_names:
            normalized_model_names[_normalize_label(name)] = name
            # Strip trailing (digits) to get the base name
            base = re.sub(r'\(\d+\)$', '', name)
            base_norm = _normalize_label(base)
            if base_norm:
                base_to_mech[base_norm] = name

    # --- Build InChI -> mechanism label map ---
    # This goes through each DB species in this model, finds its SMILES,
    # converts to InChI, then resolves the DB label to the actual mechanism
    # species name.  This handles cases where the DB label (e.g. sc4h9oh)
    # differs from the exported mechanism name (e.g. N2C4H9OH(55)) because
    # the export may have picked a different alias for the same Species.
    inchi_to_mech_label: Dict[str, str] = {}
    try:
        from rdkit import Chem
        from rdkit.Chem.inchi import MolToInchi

        for db_label, smiles in model_label_smiles.items():
            if not smiles or smiles == db_label:
                continue
            mol = Chem.MolFromSmiles(smiles)
            if not mol:
                continue
            inchi = MolToInchi(mol)
            if not inchi:
                continue

            # Resolve db_label to the mechanism species name.
            # The mechanism species name may differ from the DB label because
            # the export function picks the alphabetically-first alias.
            mech_label = None
            db_norm = _normalize_label(db_label)

            # Exact normalized match (includes the index digits)
            mech_label = normalized_model_names.get(db_norm)

            # Try base-name match (strip trailing index from mechanism names)
            if not mech_label:
                mech_label = base_to_mech.get(db_norm)

            if not mech_label:
                # The DB label might not match any mechanism name at all
                # (e.g. "sc4h9oh" vs "N2C4H9OH(55)").  Look up ALL names
                # for this Species in the DB and check each one.
                sn_obj = SpeciesName.objects.filter(
                    kinetic_model=model, name=db_label
                ).select_related("species").first()
                if sn_obj:
                    all_names = set(
                        SpeciesName.objects.filter(species=sn_obj.species)
                        .values_list("name", flat=True)
                    )
                    for alias in all_names:
                        if not alias:
                            continue
                        alias_norm = _normalize_label(alias)
                        candidate = (
                            normalized_model_names.get(alias_norm)
                            or base_to_mech.get(alias_norm)
                        )
                        if candidate:
                            mech_label = candidate
                            break

            if mech_label:
                inchi_to_mech_label[inchi] = mech_label
            # If we still can't find a mechanism name, skip this InChI
            # (it won't be useful for mapping anyway)
    except ImportError:
        pass  # RDKit not available

    dataset_species = get_dataset_species_map(dataset)
    spec_keys = OrderedDict()

    for ds_label, ds_smiles in dataset_species.items():
        ds_norm = _normalize_label(ds_label)
        model_label = None

        # 1. InChI-based match (most robust — same molecule, any SMILES form)
        if not model_label and inchi_to_mech_label:
            try:
                from rdkit import Chem
                from rdkit.Chem.inchi import MolToInchi
                mol = Chem.MolFromSmiles(ds_smiles)
                if mol:
                    inchi = MolToInchi(mol)
                    if inchi:
                        model_label = inchi_to_mech_label.get(inchi)
            except ImportError:
                pass

        # 2. Exact normalized label match against mechanism names
        if not model_label and model_species_names:
            model_label = normalized_model_names.get(ds_norm)

        # 3. Substring match
        if not model_label and model_species_names:
            model_label = _best_normalized_match(ds_norm, normalized_model_names)

        # 4. Direct label match against DB labels
        if not model_label and ds_label in model_label_smiles:
            model_label = ds_label

        spec_keys[ds_label] = model_label or ds_label

    return spec_keys


def write_spec_keys_yaml(
    model: KineticModel,
    dataset: ExperimentDataset,
    output_path: str,
    mechanism_filename: str,
    model_species_names: Optional[List[str]] = None
) -> str:
    """
    Write spec_keys.yaml for a single model-dataset pair.
    
    Args:
        model: KineticModel instance
        dataset: ExperimentDataset instance
        output_path: Path to write the YAML file
        mechanism_filename: Filename of the mechanism (used as key)
        model_species_names: List of species names in mechanism
        
    Returns:
        Path to the written file
    """
    spec_keys = build_spec_keys_for_dataset(model, dataset, model_species_names)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"{mechanism_filename}:\n")
        for label, mapped in spec_keys.items():
            f.write(f'    {label}: "{mapped}"\n')

    return output_path


# ---------------------------------------------------------------------------
# PyTeCK Simulation Runner
# ---------------------------------------------------------------------------

def run_pyteck_simulation(
    model: KineticModel,
    dataset: ExperimentDataset,
    results_dir: str,
    skip_validation: bool = True
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Run PyTeCK evaluation for a model-dataset pair.
    
    Args:
        model: KineticModel instance
        dataset: ExperimentDataset instance
        results_dir: Directory to store results
        skip_validation: Whether to skip ChemKED validation
        
    Returns:
        Tuple of (success, message, results_dict)
    """
    from pyteck.eval_model import evaluate_model
    
    try:
        # Export mechanism
        mechanism_path = get_cantera_mechanism_from_model(model)
        if not mechanism_path:
            return False, "Failed to export mechanism", None
        
        mechanism_filename = os.path.basename(mechanism_path)
        mechanism_dir = os.path.dirname(mechanism_path)
        
        # Get species names from mechanism
        model_species_names = get_mechanism_species_names(mechanism_path)
        if not model_species_names:
            return False, "Failed to load mechanism species", None
        
        # Get ChemKED root
        chemked_root = get_chemked_root_dir()
        
        # Check dataset file exists
        dataset_path = get_chemked_dataset_path(dataset)
        if not dataset_path:
            return False, f"Dataset file not found: {dataset.chemked_file_path}", None
        
        # Create temp directory for this run
        work_dir = tempfile.mkdtemp(prefix='pyteck_run_')
        
        # Write spec_keys.yaml
        spec_keys_path = os.path.join(work_dir, 'spec_keys.yaml')
        write_spec_keys_yaml(
            model=model,
            dataset=dataset,
            output_path=spec_keys_path,
            mechanism_filename=mechanism_filename,
            model_species_names=model_species_names
        )
        
        # Write dataset list file
        dataset_list_path = os.path.join(work_dir, 'datasets.txt')
        with open(dataset_list_path, 'w') as f:
            f.write(f"{dataset.chemked_file_path}\n")
        
        # Run PyTeCK evaluation
        # NOTE: PyTeCK writes results YAML to the current working directory,
        # so we must change to results_dir before calling evaluate_model
        logger.info(f"Running PyTeCK: {model.model_name} × {dataset.chemked_file_path}")
        
        original_cwd = os.getcwd()
        try:
            os.chdir(results_dir)
            evaluate_model(
                model_name=mechanism_filename,
                spec_keys_file=spec_keys_path,
                dataset_file=dataset_list_path,
                data_path=chemked_root,
                model_path=mechanism_dir,
                results_path=results_dir,
                skip_validation=skip_validation,
            )
        finally:
            os.chdir(original_cwd)
        
        # Parse results
        expected_results_file = os.path.join(
            results_dir,
            f"{os.path.splitext(mechanism_filename)[0]}-results.yaml"
        )

        # Try expected path first
        if os.path.exists(expected_results_file):
            with open(expected_results_file, 'r') as f:
                results = yaml.safe_load(f)
            return True, "Simulation completed successfully", results

        # Fallback: search for any results YAML in results_dir
        candidate_files = []
        try:
            for filename in os.listdir(results_dir):
                if filename.endswith('.yaml') and 'results' in filename:
                    candidate_files.append(os.path.join(results_dir, filename))
        except FileNotFoundError:
            candidate_files = []

        if candidate_files:
            # Use the most recently modified file
            candidate_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            with open(candidate_files[0], 'r') as f:
                results = yaml.safe_load(f)
            return True, "Simulation completed successfully (fallback results file)", results

        # No results found - include directory contents for debugging
        try:
            dir_listing = ", ".join(sorted(os.listdir(results_dir))) or "(empty)"
        except FileNotFoundError:
            dir_listing = "(results directory missing)"

        debug_message = (
            "Results file not generated. "
            f"Expected: {os.path.basename(expected_results_file)}. "
            f"Results dir: {results_dir}. "
            f"Contents: {dir_listing}"
        )
        return False, debug_message, None
            
    except Exception as e:
        logger.exception(f"PyTeCK simulation failed: {e}")
        return False, str(e), None


def parse_pyteck_results(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse PyTeCK results YAML into structured format.
    
    Args:
        results: Parsed YAML results dict
        
    Returns:
        Structured results with metrics and datapoints
    """
    parsed = {
        'average_error_function': results.get('average error function'),
        'average_deviation_function': results.get('average deviation function'),
        'datasets': [],
    }
    
    for ds in results.get('datasets', []):
        dataset_result = {
            'absolute_deviation': ds.get('absolute deviation'),
            'datapoints': [],
        }
        
        for dp in ds.get('datapoints', []):
            datapoint = {
                'temperature': dp.get('temperature'),
                'pressure': dp.get('pressure'),
                'composition': dp.get('composition', []),
                'composition_type': dp.get('composition type'),
                'experimental_ignition_delay': dp.get('experimental ignition delay'),
                'simulated_ignition_delay': dp.get('simulated ignition delay'),
            }
            dataset_result['datapoints'].append(datapoint)
        
        parsed['datasets'].append(dataset_result)
    
    return parsed
