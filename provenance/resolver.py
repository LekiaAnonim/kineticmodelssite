"""Dereferenceable IRI resolver for the minted Prometheus identifiers.

Every SSSOM/provenance node is minted under ``https://dev.omethe.us/<kind>/<slug>``
(see the ``curie_map`` header in ``mappings/prometheus.sssom.tsv``). Those IRIs
are globally-unique *names*; this module makes them *dereferenceable* so a client
that follows one gets back a representation:

* HTML  (browsers)            -> a landing page describing the node.
* RDF   (``Accept: text/turtle`` etc., or ``?format=ttl|jsonld|xml|nt``)
                              -> the node's SSSOM cross-references + provenance.

Routing is host-agnostic, so ``http://127.0.0.1:8000/species/H2O`` (dev) and
``https://dev.omethe.us/species/H2O`` (prod) resolve through the same code.
"""

import csv
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from rdflib import Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD, Namespace
from rdflib.term import BNode

from provenance.models import SemanticMapping

# Namespaces for the numeric data layer (thermo / kinetics / transport values).
QUDT = Namespace("http://qudt.org/schema/qudt/")
UNIT = Namespace("http://qudt.org/vocab/unit/")
PMTX = Namespace("https://dev.omethe.us/ontology/prometheus-exp#")

# --- prefixes (kept in sync with mappings/prometheus.sssom.tsv curie_map) ----
# Characters left un-encoded in a CURIE reference: the URI sub-delims plus ``@``
# and ``%`` (so already-encoded subjects round-trip unchanged).  Everything else
# invalid -- whitespace, brackets, non-ASCII -- is percent-encoded.
_CURIE_SAFE = "!$&'()*+,;=@%"

CURIE_MAP = {
    "prom": "https://dev.omethe.us/species/",
    "promc": "https://dev.omethe.us/concept/",
    "promref": "https://dev.omethe.us/reference/",
    "promagent": "https://dev.omethe.us/agent/",
    "promorg": "https://dev.omethe.us/institution/",
    "promkm": "https://dev.omethe.us/kineticmodel/",
    "promds": "https://dev.omethe.us/dataset/",
    "promapp": "https://dev.omethe.us/apparatus/",
    "promrxn": "https://dev.omethe.us/reaction/",
    "promv": "https://dev.omethe.us/vocab/",
    "inchikey": "https://www.inchi-trust.org/inchikey/",
    "pubchem.compound": "https://pubchem.ncbi.nlm.nih.gov/compound/",
    "CHEBI": "http://purl.obolibrary.org/obo/CHEBI_",
    "chembl": "https://www.ebi.ac.uk/chembl/compound_report_card/",
    "drugbank": "https://go.drugbank.com/drugs/",
    "hmdb": "https://hmdb.ca/metabolites/",
    "doi": "https://doi.org/",
    "orcid": "https://orcid.org/",
    "ror": "https://ror.org/",
    "chemked": "https://dev.omethe.us/ontology/chemked#",
    "ontokin": "http://www.theworldavatar.com/ontology/ontokin/OntoKin.owl#",
    "ontochemexp": "http://www.theworldavatar.com/ontology/ontochemexp/OntoChemExp.owl#",
    "ontospecies": "http://www.theworldavatar.com/ontology/ontospecies/OntoSpecies.owl#",
    "pmtx": "https://dev.omethe.us/ontology/prometheus-exp#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "semapv": "https://w3id.org/semapv/vocab/",
}

# URL path segment -> CURIE prefix used in the SSSOM subject_id.
KIND_PREFIX = {
    "species": "prom",
    "concept": "promc",
    "reference": "promref",
    "agent": "promagent",
    "institution": "promorg",
    "kineticmodel": "promkm",
    "dataset": "promds",
    "apparatus": "promapp",
    "reaction": "promrxn",
}
KIND_LABEL = {
    "species": "Chemical species",
    "concept": "Concept",
    "reference": "Publication / reference",
    "agent": "Person (agent)",
    "institution": "Institution",
    "kineticmodel": "Kinetic model",
    "dataset": "Experimental dataset",
    "apparatus": "Experimental apparatus",
    "reaction": "Chemical reaction",
}

# SemanticMapping FK attribute -> URLconf name of the human detail page.
DETAIL_VIEW = {
    "species": "species-detail",
    "source": "source-detail",
    "kinetic_model": "kinetic-model-detail",
    "experiment_dataset": "dataset-detail",
    "reaction": "reaction-detail",
}

# Provenance edge kind -> (predicate IRI, human label).
PROV_PREDICATE = {
    "uses": ("https://dev.omethe.us/vocab/usesSpecies", "uses species"),
    "contains": ("https://dev.omethe.us/vocab/containsSpecies", "contains species"),
    "cites": ("http://purl.org/dc/terms/references", "references"),
    "from": ("http://purl.org/dc/terms/source", "derived from source"),
    "locatedAt": ("https://dev.omethe.us/vocab/locatedAtInstitution", "located at institution"),
    "usesApparatus": ("https://dev.omethe.us/vocab/usesApparatus", "uses apparatus"),
    "usesReaction": ("https://dev.omethe.us/vocab/usesReaction", "uses reaction"),
    "thermoFrom": ("https://dev.omethe.us/vocab/thermoDataFrom", "thermo data from"),
    "kineticsFrom": ("https://dev.omethe.us/vocab/kineticsDataFrom", "kinetics data from"),
}

# Human-readable documentation for the semapv mapping-justification vocabulary.
# The w3id namespace base (CURIE_MAP["semapv"]) does not dereference to a page.
SEMAPV_DOCS = "https://mapping-commons.github.io/semantic-mapping-vocabulary/"

# Terms minted under the promv: vocabulary namespace.
PROMV = "https://dev.omethe.us/vocab/"
PROMV_TERMS = {
    "usesSpecies": (
        "uses species",
        "Relates a kinetic model to a chemical species that appears in its mechanism.",
    ),
    "containsSpecies": (
        "contains species",
        "Relates an experimental dataset to a chemical species present in a reported mixture.",
    ),
    "locatedAtInstitution": (
        "located at institution",
        "Relates an experimental apparatus to the institution that operates it.",
    ),
    "usesApparatus": (
        "uses apparatus",
        "Relates an experimental dataset to the apparatus used to produce its measurements.",
    ),
    "usesReaction": (
        "uses reaction",
        "Relates a kinetic model to a chemical reaction whose rate it incorporates.",
    ),
    "thermoDataFrom": (
        "thermo data from",
        "Relates a chemical species to a publication that is the source of its "
        "thermodynamic (NASA polynomial) data.",
    ),
    "kineticsDataFrom": (
        "kinetics data from",
        "Relates a chemical reaction to a publication that is the source of "
        "a rate-coefficient expression for it.",
    ),
}

# RDF serialisation: query-string token / mime -> (content-type, rdflib format).
RDF_FORMATS = {
    "ttl": ("text/turtle", "turtle"),
    "turtle": ("text/turtle", "turtle"),
    "jsonld": ("application/ld+json", "json-ld"),
    "json-ld": ("application/ld+json", "json-ld"),
    "rdf": ("application/rdf+xml", "xml"),
    "xml": ("application/rdf+xml", "xml"),
    "nt": ("application/n-triples", "nt"),
    "ntriples": ("application/n-triples", "nt"),
}
_ACCEPT_RDF = [
    ("text/turtle", ("text/turtle", "turtle")),
    ("application/x-turtle", ("text/turtle", "turtle")),
    ("application/ld+json", ("application/ld+json", "json-ld")),
    ("application/rdf+xml", ("application/rdf+xml", "xml")),
    ("application/n-triples", ("application/n-triples", "nt")),
]

_MAPPINGS_DIR = Path(__file__).resolve().parents[2] / "mappings"


@lru_cache(maxsize=2)
def _load_pmtx_vocab(path, _mtime):
    """Parse prometheus-exp.ttl; return the pmtx: classes/properties it defines."""
    ns = CURIE_MAP["pmtx"]
    g = Graph()
    try:
        g.parse(path, format="turtle")
    except Exception:  # noqa: BLE001 - any parse failure -> no extra terms
        return []
    terms = {}
    for subj, _, lbl in g.triples((None, RDFS.label, None)):
        iri = str(subj)
        if not iri.startswith(ns):
            continue
        types = set(g.objects(subj, RDF.type))
        if OWL.Class in types or RDFS.Class in types:
            kind = "Class"
        elif types & {OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property}:
            kind = "Property"
        else:
            kind = ""
        comment = g.value(subj, RDFS.comment)
        local = iri[len(ns):]
        terms[iri] = {
            "name": local,
            "curie": f"pmtx:{local}",
            "iri": iri,
            "label": str(lbl),
            "comment": str(comment) if comment else "",
            "kind": kind,
        }
    return sorted(terms.values(), key=lambda t: (t["kind"] != "Class", t["name"].lower()))


def _pmtx_vocab():
    """pmtx: experimental-extension terms, reloaded when the TTL file changes."""
    path = _MAPPINGS_DIR / "prometheus-exp.ttl"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    return _load_pmtx_vocab(str(path), mtime)


@lru_cache(maxsize=2)
def _load_pmtx_graph(path, _mtime):
    """Parse the whole prometheus-exp.ttl into a Graph for RDF dereferencing."""
    g = Graph()
    try:
        g.parse(path, format="turtle")
    except Exception:  # noqa: BLE001 - any parse failure -> no document
        return None
    return g


def _pmtx_graph():
    """The pmtx: ontology graph, reloaded when the TTL file changes."""
    path = _MAPPINGS_DIR / "prometheus-exp.ttl"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return _load_pmtx_graph(str(path), mtime)


@lru_cache(maxsize=8)
def _load_external_vocab(path, _mtime, prefix, ns):
    """Read a reused-ontology term inventory; keep only terms Prometheus reuses.

    Shared by the OntoKin, OntoChemExp and OntoSpecies vocabulary catalogues.
    Each is a curated CSV (term, kind, definition, ..., prometheus_status,
    prometheus_mapping) that supplies the labels/definitions the source
    ontologies do not always carry, so the vocab page can render reused terms.
    """
    terms = []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get("prometheus_status") or "").strip() == "not currently represented":
                    continue  # the source defines it but Prometheus does not use it
                iri = (row.get("iri") or "").strip()
                name = (row.get("term") or "").strip()
                definition = (row.get("definition") or "").strip()
                if definition.startswith("No textual definition"):
                    definition = ""
                terms.append(
                    {
                        "name": name,
                        "curie": f"{prefix}:{name}" if iri.startswith(ns) else "",
                        "iri": iri,
                        "kind": (row.get("kind") or "").strip(),
                        "definition": definition,
                        "status": (row.get("prometheus_status") or "").strip(),
                        "mapping": (row.get("prometheus_mapping") or "").strip(),
                    }
                )
    except (OSError, ValueError):
        return []
    return sorted(terms, key=lambda t: (t["kind"] != "class", t["name"].lower()))


def _external_vocab(filename, prefix):
    """A reused-ontology vocabulary, reloaded when its inventory CSV changes."""
    path = _MAPPINGS_DIR / filename
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    return _load_external_vocab(str(path), mtime, prefix, CURIE_MAP[prefix])


def _ontokin_vocab():
    """OntoKin terms Prometheus reuses for mechanism concepts."""
    return _external_vocab("ontokin_vocabulary_definitions.csv", "ontokin")


def _ontochemexp_vocab():
    """OntoChemExp terms Prometheus reuses for experimental concepts."""
    return _external_vocab("ontochemexp_vocabulary_definitions.csv", "ontochemexp")


def _ontospecies_vocab():
    """OntoSpecies terms Prometheus reuses for species concepts."""
    return _external_vocab("ontospecies_vocabulary_definitions.csv", "ontospecies")


# --- helpers ----------------------------------------------------------------
def _expand(curie):
    """Expand a CURIE to a full IRI using CURIE_MAP; pass through bare IRIs."""
    if ":" not in curie:
        return curie
    prefix, _, local = curie.partition(":")
    base = CURIE_MAP.get(prefix)
    if base is None:
        return curie  # already an IRI (http:, https:, urn:) or unknown prefix
    return base + local


@lru_cache(maxsize=4)
def _load_edges(path, _mtime):
    """Parse the sidecar; cached per (path, mtime) so regenerating it reloads."""
    try:
        with open(path) as fh:
            return json.load(fh).get("edges", [])
    except (OSError, ValueError):
        return []


def _provenance_edges():
    """Load the provenance sidecar: list of {from, to, kind} CURIE edges.

    Keyed on the file's modification time so that regenerating
    ``prometheus.provenance.json`` (via ``export_provenance_edges``) is reflected
    without restarting the server.
    """
    path = _MAPPINGS_DIR / "prometheus.provenance.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    return _load_edges(str(path), mtime)


def _edges_for(curie):
    """Provenance edges incident on ``curie`` as (other_curie, predicate, label, outgoing)."""
    out = []
    for e in _provenance_edges():
        kind = e.get("kind")
        pred = PROV_PREDICATE.get(kind)
        if not pred:
            continue
        if e.get("from") == curie:
            out.append((e["to"], pred[0], pred[1], True))
        elif e.get("to") == curie:
            out.append((e["from"], pred[0], pred[1], False))
    return out


def _negotiate(request):
    """Return (content_type, rdflib_format) for RDF, or None for HTML."""
    fmt = request.GET.get("format")
    if fmt:
        return RDF_FORMATS.get(fmt.lower())
    accept = request.META.get("HTTP_ACCEPT", "")
    for token, fmt in _ACCEPT_RDF:
        if token in accept:
            return fmt
    return None


def _detail_url(request, mappings):
    """Absolute URL of the canonical human page for the resolved DB entity."""
    for m in mappings:
        for attr, view in DETAIL_VIEW.items():
            pk = getattr(m, attr + "_id", None)
            if pk:
                try:
                    return request.build_absolute_uri(reverse(view, args=[pk]))
                except NoReverseMatch:
                    pass
    return None


def _bind_prefixes(g):
    for prefix, ns in CURIE_MAP.items():
        # rdflib prefixes cannot contain a dot.
        g.bind(prefix.replace(".", "_"), ns, replace=True)
    g.bind("dcterms", DCTERMS)
    g.bind("owl", OWL)
    g.bind("qudt", QUDT)
    g.bind("unit", UNIT)


def _rdf_response(request, graph, fmt):
    content_type, rdflib_format = fmt
    data = graph.serialize(format=rdflib_format)
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return HttpResponse(data, content_type=f"{content_type}; charset=utf-8")


# --- numeric data layer (thermo / kinetics / transport VALUES) --------------
# OntoKin 1.0 has the structural classes but no datatype properties for the
# actual numbers, so dereferencing a node returned only identity + provenance.
# These helpers attach the real coefficients, using the QUDT QuantityValue
# pattern (numericValue + unit IRI) for scalars and rdf:List for vectors, so an
# agent that follows a species or reaction IRI gets the values as RDF.
def _quantity(g, value, unit_iri=None, unit_text=None):
    """A qudt:QuantityValue bnode for a scalar, or None if the value is missing."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    qv = BNode()
    g.add((qv, RDF.type, QUDT.QuantityValue))
    g.add((qv, QUDT.numericValue, Literal(num, datatype=XSD.double)))
    if unit_iri is not None:
        g.add((qv, QUDT.unit, unit_iri))
    if unit_text:
        g.add((qv, PMTX.unitText, Literal(unit_text)))
    return qv


def _add_quantity(g, subject, predicate, value, unit_iri=None, unit_text=None):
    qv = _quantity(g, value, unit_iri=unit_iri, unit_text=unit_text)
    if qv is not None:
        g.add((subject, predicate, qv))


def _vector(g, values):
    """An ordered rdf:List of xsd:double for a coefficient vector."""
    head = BNode()
    Collection(g, head, [Literal(float(v), datatype=XSD.double) for v in values])
    return head


def _record_source(g, record_node, record):
    """Attribute one value record (thermo/transport/rate) to the paper it came
    from, so the N competing fits on a node are individually traceable."""
    source = getattr(record, "source", None)
    doi = (getattr(source, "doi", "") or "").strip()
    if doi:
        g.add((record_node, DCTERMS.source, URIRef(f"https://doi.org/{doi}")))


def _emit_arrhenius(g, node, data):
    """Attach Arrhenius A/n/Ea to a pmtx:RateParameters node from a raw_data dict."""
    _add_quantity(g, node, PMTX.preExponentialFactor, data.get("a_si"),
                  unit_text=data.get("a_units"))
    if data.get("n") is not None:
        g.add((node, PMTX.temperatureExponent, Literal(float(data["n"]), datatype=XSD.double)))
    _add_quantity(g, node, PMTX.activationEnergy, data.get("e_si"), unit_iri=UNIT["J-PER-MOL"])


def _emit_rate(g, node, data):
    """Attach the numeric parameters of one rate expression (any supported type)."""
    rtype = data.get("type")
    if rtype:
        g.add((node, PMTX.rateExpressionType, Literal(rtype)))
    if rtype in ("arrhenius", "arrhenius_ep"):
        _emit_arrhenius(g, node, data)
    elif rtype == "troe":
        if data.get("alpha") is not None:
            g.add((node, PMTX.troeAlpha, Literal(float(data["alpha"]), datatype=XSD.double)))
        _add_quantity(g, node, PMTX.troeT1, data.get("t1"), unit_iri=UNIT.K)
        if data.get("t2"):
            _add_quantity(g, node, PMTX.troeT2, data.get("t2"), unit_iri=UNIT.K)
        _add_quantity(g, node, PMTX.troeT3, data.get("t3"), unit_iri=UNIT.K)
        _emit_falloff(g, node, data)
    elif rtype == "lindemann":
        _emit_falloff(g, node, data)
    elif rtype == "third_body":
        low = data.get("low_arrhenius")
        if low:
            sub = _rate_subnode(g, node, PMTX.lowPressureParameters, "arrhenius")
            _emit_arrhenius(g, sub, low)
    elif rtype == "pdep_arrhenius":
        for point in data.get("pressure_set", []):
            sub = _rate_subnode(g, node, PMTX.pressurePoint, "arrhenius")
            _add_quantity(g, sub, PMTX.atPressure, point.get("pressure"), unit_iri=UNIT.PA)
            arr = point.get("arrhenius")
            if arr:
                _emit_arrhenius(g, sub, arr)
    elif rtype == "chebyshev":
        matrix = data.get("coefficient_matrix")
        if matrix:
            rows = [_vector(g, row) for row in matrix]
            head = BNode()
            Collection(g, head, rows)
            g.add((node, PMTX.chebyshevCoefficients, head))


def _emit_falloff(g, node, data):
    """Attach the low/high-pressure-limit Arrhenius nodes of a fall-off rate."""
    low = data.get("low_arrhenius")
    if low:
        sub = _rate_subnode(g, node, PMTX.lowPressureParameters, "arrhenius")
        _emit_arrhenius(g, sub, low)
    high = data.get("high_arrhenius")
    if high:
        sub = _rate_subnode(g, node, PMTX.highPressureParameters, "arrhenius")
        _emit_arrhenius(g, sub, high)


def _rate_subnode(g, parent, predicate, rtype):
    sub = BNode()
    g.add((sub, RDF.type, PMTX.RateParameters))
    g.add((sub, PMTX.rateExpressionType, Literal(rtype)))
    g.add((parent, predicate, sub))
    return sub


def _emit_thermo(g, subject, thermo):
    tnode = BNode()
    g.add((subject, PMTX.hasThermo, tnode))
    g.add((tnode, RDF.type, PMTX.ThermoData))
    _record_source(g, tnode, thermo)
    _add_quantity(g, tnode, PMTX.enthalpyOfFormation, thermo.enthalpy_formation,
                  unit_iri=UNIT["J-PER-MOL"])
    _add_quantity(g, tnode, PMTX.referenceTemperature, thermo.reference_temp, unit_iri=UNIT.K)
    _add_quantity(g, tnode, PMTX.referencePressure, thermo.reference_pressure, unit_iri=UNIT.PA)
    for coeffs, tmin, tmax, predicate in (
        (thermo.coeffs_poly1, thermo.temp_min_1, thermo.temp_max_1, PMTX.lowTemperaturePolynomial),
        (thermo.coeffs_poly2, thermo.temp_min_2, thermo.temp_max_2, PMTX.highTemperaturePolynomial),
    ):
        if not coeffs:
            continue
        poly = BNode()
        g.add((poly, RDF.type, PMTX.NASAPolynomial))
        g.add((poly, PMTX.coefficients, _vector(g, coeffs)))
        _add_quantity(g, poly, PMTX.lowerTemperatureBound, tmin, unit_iri=UNIT.K)
        _add_quantity(g, poly, PMTX.upperTemperatureBound, tmax, unit_iri=UNIT.K)
        g.add((tnode, predicate, poly))


def _emit_transport(g, subject, tr):
    tnode = BNode()
    g.add((subject, PMTX.hasTransport, tnode))
    g.add((tnode, RDF.type, PMTX.TransportData))
    _record_source(g, tnode, tr)
    _add_quantity(g, tnode, PMTX.potentialWellDepth, tr.potential_well_depth, unit_iri=UNIT.K)
    _add_quantity(g, tnode, PMTX.collisionDiameter, tr.collision_diameter, unit_iri=UNIT.ANGSTROM)
    _add_quantity(g, tnode, PMTX.dipoleMoment, tr.dipole_moment, unit_text="debye")
    _add_quantity(g, tnode, PMTX.polarizability, tr.polarizability, unit_text="cubic angstrom")
    if tr.rotational_relaxation:
        g.add((tnode, PMTX.rotationalRelaxation,
               Literal(float(tr.rotational_relaxation), datatype=XSD.double)))


def _emit_kinetics(g, subject, kin):
    knode = BNode()
    g.add((subject, PMTX.hasRateParameters, knode))
    g.add((knode, RDF.type, PMTX.RateParameters))
    _record_source(g, knode, kin)
    _emit_rate(g, knode, kin.raw_data or {})
    _add_quantity(g, knode, PMTX.lowerTemperatureBound, kin.min_temp, unit_iri=UNIT.K)
    _add_quantity(g, knode, PMTX.upperTemperatureBound, kin.max_temp, unit_iri=UNIT.K)
    _add_quantity(g, knode, PMTX.lowerPressureBound, kin.min_pressure, unit_iri=UNIT.PA)
    _add_quantity(g, knode, PMTX.upperPressureBound, kin.max_pressure, unit_iri=UNIT.PA)


def _emit_species_data(g, node, mappings):
    """Attach NASA thermo + transport values for the species behind these mappings."""
    species_ids = {m.species_id for m in mappings if m.species_id}
    if not species_ids:
        return
    try:
        from database.models import Thermo, Transport
        for thermo in Thermo.objects.filter(species_id__in=species_ids).select_related("source"):
            _emit_thermo(g, node, thermo)
        for tr in Transport.objects.filter(species_id__in=species_ids).select_related("source"):
            _emit_transport(g, node, tr)
    except Exception:  # noqa: BLE001 - data layer must never break dereferencing
        pass


def _emit_reaction_data(g, node, mappings):
    """Attach rate-coefficient values for the reaction behind these mappings."""
    reaction_ids = {m.reaction_id for m in mappings if m.reaction_id}
    if not reaction_ids:
        return
    try:
        from database.models import Kinetics
        for kin in Kinetics.objects.filter(reaction_id__in=reaction_ids).select_related("source"):
            _emit_kinetics(g, node, kin)
    except Exception:  # noqa: BLE001 - data layer must never break dereferencing
        pass


# --- views ------------------------------------------------------------------
def resolve_node(request, kind, slug):
    """Dereference a minted entity IRI (species, reference, kineticmodel, ...)."""
    prefix = KIND_PREFIX.get(kind)
    if prefix is None:
        raise Http404("Unknown identifier kind")
    # Django hands us the percent-decoded path segment; re-encode the invalid
    # CURIE characters (whitespace, brackets, non-ASCII) so it matches the
    # stored subject_id (e.g. species ``CHFCH[Z]`` -> ``CHFCH%5BZ%5D``).  A
    # no-op for clean slugs such as reference or kinetic-model identifiers.
    curie = f"{prefix}:{quote(slug, safe=_CURIE_SAFE)}"
    mappings = list(SemanticMapping.objects.filter(subject_id=curie))
    if not mappings:
        raise Http404(f"No minted node for {curie}")

    node_iri = _expand(curie)
    label = next((m.subject_label for m in mappings if m.subject_label), slug)
    detail_url = _detail_url(request, mappings)
    edges = _edges_for(curie)

    fmt = _negotiate(request)
    if fmt is not None:
        g = Graph()
        _bind_prefixes(g)
        node = URIRef(node_iri)
        g.add((node, RDF.type, SKOS.Concept))
        g.add((node, RDFS.label, Literal(label)))
        g.add((node, SKOS.prefLabel, Literal(label)))
        for m in mappings:
            g.add((node, URIRef(_expand(m.predicate_id)), URIRef(_expand(m.object_id))))
        for other, pred, _lbl, outgoing in edges:
            other_iri = URIRef(_expand(other))
            if outgoing:
                g.add((node, URIRef(pred), other_iri))
            else:
                g.add((other_iri, URIRef(pred), node))
        # Attach the actual numeric data so an agent gets the values, not just
        # the citation: NASA thermo + transport for species, rate params for
        # reactions.
        if kind == "species":
            _emit_species_data(g, node, mappings)
        elif kind == "reaction":
            _emit_reaction_data(g, node, mappings)
        if detail_url:
            g.add((node, RDFS.seeAlso, URIRef(detail_url)))
        return _rdf_response(request, g, fmt)

    context = {
        "curie": curie,
        "node_iri": node_iri,
        "label": label,
        "kind": kind,
        "kind_label": KIND_LABEL.get(kind, kind),
        "detail_url": detail_url,
        "mappings": [
            {
                "predicate": m.predicate_id,
                "object_curie": m.object_id,
                "object_iri": _expand(m.object_id),
                "object_label": m.object_label,
                "confidence": m.confidence,
                "justification": m.mapping_justification,
            }
            for m in mappings
        ],
        "edges": [
            {
                "other_curie": other,
                "other_iri": _expand(other),
                "label": lbl,
                "outgoing": outgoing,
            }
            for other, _pred, lbl, outgoing in edges
        ],
    }
    return render(request, "provenance/node.html", context)


def resolve_collection(request, kind):
    """Dereference a namespace/collection base IRI (e.g. ``.../kineticmodel/``).

    The per-entity leaf IRIs (``.../kineticmodel/mb-dooley``) resolve via
    :func:`resolve_node`; this view makes the *parent* base dereferenceable too,
    returning an index of the minted members (HTML) or a ``skos:Collection`` with
    ``skos:member`` links (RDF).
    """
    prefix = KIND_PREFIX.get(kind)
    if prefix is None:
        raise Http404("Unknown identifier kind")
    base_iri = CURIE_MAP[prefix]

    subjects = sorted(
        SemanticMapping.objects.filter(subject_id__startswith=f"{prefix}:")
        .values_list("subject_id", flat=True)
        .distinct()
    )
    members = []
    for curie in subjects:
        slug = curie.split(":", 1)[1]
        try:
            url = request.build_absolute_uri(reverse(f"prom-{kind}", args=[slug]))
        except NoReverseMatch:
            url = _expand(curie)
        members.append({"curie": curie, "iri": _expand(curie), "url": url, "slug": slug})

    fmt = _negotiate(request)
    if fmt is not None:
        g = Graph()
        _bind_prefixes(g)
        coll = URIRef(base_iri)
        g.add((coll, RDF.type, SKOS.Collection))
        g.add((coll, RDFS.label, Literal(f"{KIND_LABEL.get(kind, kind)} namespace")))
        for m in members:
            g.add((coll, SKOS.member, URIRef(m["iri"])))
        return _rdf_response(request, g, fmt)

    display_cap = 500
    context = {
        "kind": kind,
        "kind_label": KIND_LABEL.get(kind, kind),
        "base_iri": base_iri,
        "count": len(members),
        "members": members[:display_cap],
        "shown": min(len(members), display_cap),
        "truncated": len(members) > display_cap,
    }
    return render(request, "provenance/collection.html", context)


def vocab(request, term=None):
    """Serve the promv: provenance vocabulary (ontology document)."""
    onto = URIRef(PROMV)
    fmt = _negotiate(request)
    if fmt is not None:
        g = Graph()
        g.bind("promv", PROMV, replace=True)
        g.bind("owl", OWL)
        g.bind("rdfs", RDFS)
        g.add((onto, RDF.type, OWL.Ontology))
        g.add((onto, RDFS.label, Literal("Prometheus provenance vocabulary")))
        g.add(
            (
                onto,
                RDFS.comment,
                Literal(
                    "Domain predicates used to connect Prometheus SSSOM nodes "
                    "(kinetic models, datasets, species) in the knowledge graph."
                ),
            )
        )
        items = (
            [(term, PROMV_TERMS[term])] if term in PROMV_TERMS else PROMV_TERMS.items()
        )
        for name, (lbl, desc) in items:
            t = URIRef(PROMV + name)
            g.add((t, RDF.type, RDF.Property))
            g.add((t, RDFS.label, Literal(lbl)))
            g.add((t, RDFS.comment, Literal(desc)))
            g.add((t, RDFS.isDefinedBy, onto))
        if term is None:
            # Point clients at the vocabularies Prometheus reuses without
            # re-minting their IRIs: the experimental extension (pmtx:) and
            # OntoKin. seeAlso is non-authoritative, so it is FAIR-correct here.
            g.bind("pmtx", CURIE_MAP["pmtx"])
            g.bind("ontokin", CURIE_MAP["ontokin"])
            g.add((onto, RDFS.seeAlso, URIRef(CURIE_MAP["pmtx"])))
            g.add((onto, RDFS.seeAlso, URIRef(CURIE_MAP["ontokin"])))
            # The semapv mapping-justification namespace base does not
            # dereference to a document; point humans at its rendered docs.
            g.add((onto, RDFS.seeAlso, URIRef(SEMAPV_DOCS)))
        return _rdf_response(request, g, fmt)

    if term is not None and term not in PROMV_TERMS:
        raise Http404(f"No vocabulary term {term}")
    context = {
        "vocab_iri": PROMV,
        "focus": term,
        "terms": [
            {"name": name, "iri": PROMV + name, "label": lbl, "comment": desc}
            for name, (lbl, desc) in PROMV_TERMS.items()
        ],
        # Full vocabulary hub (only on the index page, not a single-term focus):
        # terms Prometheus reuses from its experimental extension and from OntoKin.
        "pmtx": {"iri": CURIE_MAP["pmtx"], "terms": _pmtx_vocab()} if term is None else None,
        "ontokin": (
            {"iri": CURIE_MAP["ontokin"], "terms": _ontokin_vocab()} if term is None else None
        ),
        "ontochemexp": (
            {"iri": CURIE_MAP["ontochemexp"], "terms": _ontochemexp_vocab()}
            if term is None
            else None
        ),
        "ontospecies": (
            {"iri": CURIE_MAP["ontospecies"], "terms": _ontospecies_vocab()}
            if term is None
            else None
        ),
        # The mapping-justification vocabulary (semapv:) used in the SSSOM set.
        # Its namespace base does not dereference, so link humans to its docs.
        "semapv": (
            {"iri": CURIE_MAP["semapv"], "docs": SEMAPV_DOCS} if term is None else None
        ),
    }
    return render(request, "provenance/vocab.html", context)


def pmtx_ontology(request):
    """Dereference the pmtx: experimental-extension ontology and its terms.

    Term IRIs carry a fragment (``...prometheus-exp#Apparatus``); fragments are
    never sent to the server, so every ``pmtx:`` term dereferences to this one
    document. RDF clients get the full ontology graph; browsers get the
    vocabulary hub, whose pmtx term anchors (``id="Apparatus"``) let the
    fragment scroll straight to the requested term.
    """
    fmt = _negotiate(request)
    if fmt is not None:
        g = _pmtx_graph()
        if g is None:
            raise Http404("pmtx ontology unavailable")
        return _rdf_response(request, g, fmt)
    return vocab(request)
