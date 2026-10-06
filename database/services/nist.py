"""Links to the NIST Chemical Kinetics Database (SRD 17) and the NIST Chemistry WebBook.

NIST's robots.txt does not allow automated agents, so the site never fetches from NIST. Reaction
pages link to NIST's own reaction search, which identifies species by CAS number; species link to
their WebBook page by InChI, where a missing CAS number can be looked up.
"""
import re
from collections import defaultdict
from urllib.parse import quote, urlencode

from database import models

KINETICS_URL = "https://kinetics.nist.gov/kinetics/"
SEARCH_FORM = KINETICS_URL + "KineticsSearchForm.jsp"
CITATION_URL = KINETICS_URL + "citation.jsp"
WEBBOOK_INCHI_URL = "https://webbook.nist.gov/cgi/inchi/"
CAS = re.compile(r"^(?:CAS[- ]?)?(\d{2,7}-\d{2}-\d)$", re.IGNORECASE)
SLOTS = 5               # species per side in NIST's ReactionSearch (r0-r4, p0-p4)
ANY_PRODUCTS = "-10"    # p0 value NIST uses for "→ Products"


def valid_cas(cas):
    digits = cas.replace("-", "")
    return sum(int(d) * (i + 1) for i, d in enumerate(reversed(digits[:-1]))) % 10 == int(digits[-1])


RMG_LAYERS = re.compile(r"/(?:u|lp)[^/]*")


def standard_inchi(inchi):
    """RMG's augmented InChI without its unpaired-electron (/u) and lone-pair (/lp) layers."""
    return RMG_LAYERS.sub("", inchi) if inchi else ""


def webbook_url(inchi):
    """The WebBook page for an InChI ('/' stays unencoded, as NIST asks)."""
    inchi = standard_inchi(inchi)
    return WEBBOOK_INCHI_URL + quote(inchi, safe="/=") if inchi.startswith("InChI=") else ""


def species_cas(species_ids):
    """species id -> (CAS, where it came from) for species with one unambiguous CAS number.

    ATcT's CAS comes first: its records are matched to the structure. Otherwise the structure's
    PubChem synonyms must give exactly one, or exactly one that ATcT confirms; failing that, the
    first CAS number PubChem lists for its standard InChIKey (enrich_structure_cas).
    """
    atct, pubchem, by_inchikey = defaultdict(set), defaultdict(set), defaultdict(list)
    for species_id, numbers in models.Structure.objects.filter(isomer__species__in=species_ids).exclude(
            cas_numbers=[]).order_by("pk").values_list("isomer__species", "cas_numbers"):
        by_inchikey[species_id] += [n for n in numbers if n not in by_inchikey[species_id]]
    for species_id, cas in models.ThermoRecord.objects.filter(
            provider="atct", structure__isomer__species__in=species_ids).values_list(
            "structure__isomer__species", "raw_data__CASRN"):
        if cas and CAS.match(cas) and valid_cas(cas):
            atct[species_id].add(cas)
    for species_id, name in models.StructureName.objects.filter(
            structure__isomer__species__in=species_ids).values_list("structure__isomer__species", "name"):
        match = CAS.match(name.strip())
        if match and valid_cas(match.group(1)):
            pubchem[species_id].add(match.group(1))
    found = {}
    for species_id in species_ids:
        a, p = atct.get(species_id, set()), pubchem.get(species_id, set())
        if len(a) == 1:
            found[species_id] = (next(iter(a)), "ATcT")
        elif len(p) == 1:
            found[species_id] = (next(iter(p)), "PubChem")
        elif len(a & p) == 1:
            found[species_id] = (next(iter(a & p)), "ATcT and PubChem")
        elif by_inchikey.get(species_id):
            # PubChem lists the most relevant synonyms first; its first CAS number is the primary one.
            numbers = by_inchikey[species_id]
            found[species_id] = (numbers[0], "PubChem, by InChIKey" + (f", first of {len(numbers)}" if len(numbers) > 1 else ""))
    return found


def reaction_sides(reaction):
    rows = list(reaction.stoichiometry_set.values_list("species_id", "coeff"))
    reactant_ids = {s for s, c in rows if c < 0}
    product_ids = {s for s, c in rows if c > 0}
    colliders = reactant_ids & product_ids  # explicit third bodies are not NIST reactants
    expand = lambda sign: [s for s, c in rows if (c < 0) == (sign < 0) and s not in colliders
                           for _ in range(int(round(abs(c))))]
    return expand(-1), expand(1)


def _search(reactant_cas, product_cas):
    def side(prefix, numbers, empty):
        numbers = [n.replace("-", "") for n in numbers][:SLOTS]
        return {f"{prefix}{i}": (numbers[i] if i < len(numbers) else ("0" if i or numbers else empty)) for i in range(SLOTS)}
    params = {**side("r", reactant_cas, "0"), **side("p", product_cas, ANY_PRODUCTS), "expandResults": "true"}
    return KINETICS_URL + "ReactionSearch?" + urlencode(params)


def search_links(reaction):
    """NIST searches for this reaction, built from the CAS numbers we can trust:

    - every species identified: the reaction as written, written in reverse, and every reaction of
      the reactants (other product channels);
    - only one side identified: every reaction of those species;
    - otherwise NIST's search form, to search by formula.
    Also each species with its CAS (or none) and WebBook page.
    """
    from database.services.chemistry_index import species_tables
    reactants, products = reaction_sides(reaction)
    cas = species_cas(set(reactants) | set(products))
    _, formulas = species_tables(set(reactants) | set(products))
    inchi = {}
    for species_id, value in models.Species.isomers.through.objects.filter(
            species_id__in=set(reactants) | set(products)).order_by("isomer_id").values_list("species_id", "isomer__inchi"):
        inchi.setdefault(species_id, value)
    species = [{"id": s, "formula": formulas.get(s) or f"#{s}", "cas": cas.get(s, (None, None))[0],
                "cas_source": cas.get(s, (None, None))[1], "webbook": webbook_url(inchi.get(s))}
               for s in dict.fromkeys(reactants + products)]
    name = lambda ids: " + ".join(formulas.get(s) or f"#{s}" for s in ids)
    known = lambda ids: bool(ids) and len(ids) <= SLOTS and all(s in cas for s in ids)
    numbers = lambda ids: [cas[s][0] for s in ids]
    links = []
    if known(reactants) and known(products):
        links.append({"label": "This reaction", "url": _search(numbers(reactants), numbers(products))})
        links.append({"label": "Written in reverse", "url": _search(numbers(products), numbers(reactants))})
    if known(reactants):
        links.append({"label": f"All reactions of {name(reactants)}", "url": _search(numbers(reactants), [])})
    if known(products):
        links.append({"label": f"All reactions of {name(products)}", "url": _search(numbers(products), [])})
    return {"links": links, "species": species, "missing": [s for s in species if not s["cas"]],
            "form": SEARCH_FORM, "citation": CITATION_URL}
