"""Loading RMG-format kinetics and thermo libraries the way older RMG did.

RMG-Py 4 refuses a whole library when one reaction has more than three reactants or products,
or a collider that is missing from the dictionary, and it cannot parse dictionaries whose
adjacency lists carry `molecularTermSymbol` lines. Many RMG-models mechanisms (and the
site's existing imports of them) contain such reactions. This loader skips only those
reactions and records why, so the rest of the library still loads.

RMG-Py 4 also refuses a whole thermo library when two entries share a label or a structure.
CHEMKIN mechanisms do that when they list an excited state (OH*, CH*) next to the ground
state: only a `molecularTermSymbol` line tells them apart. The thermo loader keeps the first
entry of each structure and records the others, so the import can report them.
"""
import os
import re
import tempfile

from rmgpy.data.kinetics.library import KineticsLibrary
from rmgpy.data.thermo import ThermoLibrary
from rmgpy.molecule import Molecule

NON_STANDARD_ADJACENCY_TOKENS = ("molecularTermSymbol",)
COLLIDER = re.compile(r"\(\+[^\)]+\)")


def dictionary_labels(path):
    """The species labels of an RMG dictionary file: the first line of each block."""
    labels, block_start = set(), True
    with open(path) as handle:
        for line in handle:
            if not line.strip():
                block_start = True
            elif block_start:
                labels.add(line.strip())
                block_start = False
    return labels


def rejection(label, species_labels):
    """Why RMG 4 would refuse this reaction label, or None."""
    reactants, _, products = label.partition("=>")
    reactants = reactants[:-1] if reactants.endswith("<") else reactants
    collider = COLLIDER.search(reactants)
    if collider:
        name = collider.group(0)[2:-1].strip()
        reactants, products = reactants.replace(collider.group(0), "", 1), products.replace(collider.group(0), "", 1)
        if name.upper() != "M" and name not in species_labels:
            return f"collider {name} missing from the dictionary"
    sides = [[s.strip() for s in side.split("+") if s.strip()] for side in (reactants, products)]
    if len(sides[0]) > 3 or len(sides[1]) > 3:
        return "more than 3 reactants or products"
    missing = [s for side in sides for s in side if s not in species_labels]
    if missing:
        return f"species {', '.join(missing)} missing from the dictionary"
    return None


class TolerantKineticsLibrary(KineticsLibrary):
    def load(self, path, local_context=None, global_context=None):
        self.rejected = []
        self._species_labels = dictionary_labels(os.path.join(os.path.dirname(path), "dictionary.txt"))
        return super().load(path, local_context, global_context)

    def load_entry(self, *args, **kwargs):
        label = kwargs.get("label", args[1] if len(args) > 1 else "")
        reason = rejection(label, self._species_labels)
        if reason:
            self.rejected.append((label, reason))
            return None
        return super().load_entry(*args, **kwargs)

    def get_species(self, path, resonance=True):
        # Kept as species_dict: the importer names collider-efficiency species from it.
        with open(path) as handle:
            lines = handle.readlines()
        cleaned = [line for line in lines if not line.split() or line.split()[0] not in NON_STANDARD_ADJACENCY_TOKENS]
        if len(cleaned) == len(lines):
            self.species_dict = super().get_species(path, resonance=resonance)
            return self.species_dict
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as temp:
            temp.writelines(cleaned)
        try:
            self.species_dict = super().get_species(temp.name, resonance=resonance)
            return self.species_dict
        finally:
            os.unlink(temp.name)

    def check_for_duplicates(self, mark_duplicates=False):
        # Some mechanisms list a reaction twice without DUPLICATE; mark them rather than refuse.
        return super().check_for_duplicates(mark_duplicates=True)


def strip_non_standard_tokens(adjacency_list):
    """The adjacency list without lines RMG cannot parse, and whether any were removed."""
    lines = adjacency_list.splitlines()
    kept = [line for line in lines
            if not line.split() or line.split()[0] not in NON_STANDARD_ADJACENCY_TOKENS]
    return "\n".join(kept), len(kept) != len(lines)


class TolerantThermoLibrary(ThermoLibrary):
    """Keeps the first entry for each label and structure; `skipped` lists the rest.

    Each skipped entry is a dict with the skipped `label`, the `kept` label that has its
    structure (graph and multiplicity), and the `reason`.
    """

    def load(self, path, local_context=None, global_context=None):
        self.skipped = []
        self._term_symbol_dropped = set()
        return super().load(path, local_context, global_context)

    def load_entry(self, index, label, molecule, thermo, **kwargs):
        adjacency_list, dropped = strip_non_standard_tokens(molecule)
        if label in self.entries:
            self.skipped.append({"label": label, "kept": label, "reason": "label repeated"})
            return None
        try:
            item = Molecule().from_adjacency_list(adjacency_list)
        except Exception as error:
            self.skipped.append({"label": label, "kept": "",
                                 "reason": f"adjacency list not readable: {error}"})
            return None
        for entry in self.entries.values():
            if item.multiplicity == entry.item.multiplicity and item.is_isomorphic(entry.item):
                notes = []
                if dropped:
                    notes.append(f"{label} had an electronic term symbol, which RMG cannot store")
                if entry.label in self._term_symbol_dropped:
                    notes.append(f"the kept entry {entry.label} is the one with a term symbol")
                reason = f"same structure and multiplicity as {entry.label}"
                self.skipped.append({"label": label, "kept": entry.label,
                                     "reason": "; ".join([reason] + notes)})
                return None
        if dropped:
            self._term_symbol_dropped.add(label)
        return super().load_entry(index, label, adjacency_list, thermo, **kwargs)
