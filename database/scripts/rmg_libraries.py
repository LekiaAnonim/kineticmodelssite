"""Loading RMG-format kinetics and thermo libraries the way older RMG did.

RMG-Py 4 refuses a whole library when one reaction has more than three reactants or products,
or a collider that is missing from the dictionary, and it cannot parse dictionaries whose
adjacency lists carry `molecularTermSymbol` lines. Many RMG-models mechanisms (and the
site's existing imports of them) contain such reactions. This loader skips only those
reactions and records why, so the rest of the library still loads.

RMG-Py 4 also refuses a whole thermo library when two entries share a label or a structure.
CHEMKIN mechanisms do that when they list an excited state (OH*, CH*) next to the ground
state. The thermo loader keeps both when their electronic states differ (from a
`molecularTermSymbol` line or SMILES.txt), and keeps the first of any other repeat and
records the rest, so the import can report them.
"""
import os
import re
import tempfile

from rmgpy.data.base import Entry
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
        # term_symbols keeps the electronic states that the cleaned dictionary loses.
        with open(path) as handle:
            lines = handle.readlines()
        self.term_symbols = dictionary_term_symbols(lines)
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


# Electronic states. RMG molecules cannot carry one, so the importer reads it beside them:
# a `molecularTermSymbol` line gives the term symbol (A^2S+), and the RMG importer marks
# excited species in SMILES.txt with an `excited` prefix (OH*  excited[OH]).
EXCITED = "excited"


def term_symbol(adjacency_list):
    """The term symbol of a `molecularTermSymbol` line, or ""."""
    for line in adjacency_list.splitlines():
        parts = line.split()
        if parts and parts[0] == "molecularTermSymbol":
            return " ".join(parts[1:])
    return ""


def dictionary_term_symbols(lines):
    """label -> term symbol for the blocks of an RMG dictionary that carry one."""
    terms, label = {}, None
    for line in lines:
        parts = line.split()
        if not parts:
            label = None
        elif label is None:
            label = parts[0]
        elif parts[0] == "molecularTermSymbol":
            terms[label] = " ".join(parts[1:])
    return terms


def smiles_txt_states(model_dir):
    """label -> "excited" for the SMILES.txt lines whose SMILES has the `excited` prefix."""
    path = os.path.join(model_dir, "SMILES.txt")
    states = {}
    if not os.path.exists(path):
        return states
    with open(path, errors="replace") as handle:
        for line in handle:
            body = line.split("!", 1)[0].split()  # a line starting with ! was deleted
            if len(body) >= 2 and body[1].startswith(EXCITED):
                states[body[0]] = EXCITED
    return states


class TolerantThermoLibrary(ThermoLibrary):
    """Keeps the first entry for each label, and for each structure in each electronic state.

    Set `declared_states` (label -> state, e.g. from smiles_txt_states) before load(); an
    entry's own term symbol wins over it. Entries with one structure but different states
    (OH and OH*) are both kept, and `states` gives the state of each kept entry. `skipped`
    lists the rest, as dicts with the skipped `label`, the `kept` label and the `reason`.
    """

    declared_states = None

    def load(self, path, local_context=None, global_context=None):
        self.skipped = []
        self.states = {}
        return super().load(path, local_context, global_context)

    def load_entry(self, index, label, molecule, thermo, **kwargs):
        adjacency_list, _ = strip_non_standard_tokens(molecule)
        state = term_symbol(molecule) or (self.declared_states or {}).get(label, "")
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
            if (item.multiplicity == entry.item.multiplicity
                    and self.states[entry.label] == state and item.is_isomorphic(entry.item)):
                self.skipped.append({
                    "label": label, "kept": entry.label,
                    "reason": ("same structure, multiplicity and electronic state as "
                               f"{entry.label}")})
                return None
        # RMG's own load_entry refuses a second entry for a structure even in another state,
        # so the entry is made here, as RMG makes it.
        item.update_atomtypes()
        self.entries[label] = Entry(
            index=index, label=label, item=item, data=thermo,
            reference=kwargs.get("reference"), reference_type=kwargs.get("referenceType", ""),
            short_desc=kwargs.get("shortDesc", ""),
            long_desc=(kwargs.get("longDesc") or "").strip(),
            rank=kwargs.get("rank"), metal=kwargs.get("metal"), facet=kwargs.get("facet"),
            site=kwargs.get("site"),
        )
        self.states[label] = state
        return None
