"""Local, stereochemistry-preserving identities for search and API validation."""

import re

from rdkit import Chem, rdBase


def canonical_smiles(value):
    if not value or len(value) > 500:
        return None
    # Do not accept a trailing name or CXSMILES metadata as part of a search.
    params = Chem.SmilesParserParams()
    params.parseName = False
    params.allowCXSMILES = False
    with rdBase.BlockLogs():
        molecule = Chem.MolFromSmiles(value, params)
    if molecule is None:
        return None
    for atom in molecule.GetAtoms():
        atom.SetAtomMapNum(0)
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)


def canonical_inchi(value):
    # Augmented RMG InChIs encode spin/radicals in extra layers. Match those
    # literally rather than silently discarding information through standard InChI.
    if re.search(r"/(u|lp|mult)", value):
        return None
    with rdBase.BlockLogs():
        molecule = Chem.MolFromInchi(value)
    return canonical_smiles(Chem.MolToSmiles(molecule)) if molecule is not None else None


def normalize_formula(value):
    """Recognize a molecular formula and return Hill order (including subscripts)."""
    value = value.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    tokens = re.findall(r"([A-Z][a-z]?)([1-9][0-9]*)?", value)
    if not tokens or "".join(element + number for element, number in tokens) != value:
        return None
    elements = {Chem.GetPeriodicTable().GetElementSymbol(i) for i in range(1, 119)}
    if any(element not in elements for element, _ in tokens):
        return None
    # Repeated elements usually indicate SMILES (CCO), not a molecular formula.
    if len({element for element, _ in tokens}) != len(tokens):
        return None
    counts = {element: int(number or 1) for element, number in tokens}
    order = sorted(counts)
    if "C" in counts:
        order = ["C"] + (["H"] if "H" in counts else [])
        order += sorted(set(counts) - {"C", "H"})
    return "".join(element + (str(counts[element]) if counts[element] != 1 else "")
                   for element in order)
