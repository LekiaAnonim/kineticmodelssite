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

from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS

from provenance.models import SemanticMapping

# --- prefixes (kept in sync with mappings/prometheus.sssom.tsv curie_map) ----
CURIE_MAP = {
    "prom": "https://dev.omethe.us/species/",
    "promc": "https://dev.omethe.us/concept/",
    "promref": "https://dev.omethe.us/reference/",
    "promagent": "https://dev.omethe.us/agent/",
    "promorg": "https://dev.omethe.us/institution/",
    "promkm": "https://dev.omethe.us/kineticmodel/",
    "promds": "https://dev.omethe.us/dataset/",
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
    "chemked": "https://dev.omethe.us/concept/",
    "ontokin": "http://www.theworldavatar.com/ontology/ontokin/OntoKin.owl#",
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
}
KIND_LABEL = {
    "species": "Chemical species",
    "concept": "Concept",
    "reference": "Publication / reference",
    "agent": "Person (agent)",
    "institution": "Institution",
    "kineticmodel": "Kinetic model",
    "dataset": "Experimental dataset",
}

# SemanticMapping FK attribute -> URLconf name of the human detail page.
DETAIL_VIEW = {
    "species": "species-detail",
    "source": "source-detail",
    "kinetic_model": "kinetic-model-detail",
    "experiment_dataset": "dataset-detail",
}

# Provenance edge kind -> (predicate IRI, human label).
PROV_PREDICATE = {
    "uses": ("https://dev.omethe.us/vocab/usesSpecies", "uses species"),
    "contains": ("https://dev.omethe.us/vocab/containsSpecies", "contains species"),
    "cites": ("http://purl.org/dc/terms/references", "references"),
    "from": ("http://purl.org/dc/terms/source", "derived from source"),
}

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


@lru_cache(maxsize=2)
def _load_ontokin_vocab(path, _mtime):
    """Read the OntoKin term inventory; keep only terms Prometheus reuses."""
    ns = CURIE_MAP["ontokin"]
    terms = []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if (row.get("prometheus_status") or "").strip() == "not currently represented":
                    continue  # OntoKin defines it but Prometheus does not use it
                iri = (row.get("iri") or "").strip()
                name = (row.get("term") or "").strip()
                definition = (row.get("definition") or "").strip()
                if definition.startswith("No textual definition"):
                    definition = ""
                terms.append(
                    {
                        "name": name,
                        "curie": f"ontokin:{name}" if iri.startswith(ns) else "",
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


def _ontokin_vocab():
    """OntoKin terms Prometheus reuses, reloaded when the inventory CSV changes."""
    path = _MAPPINGS_DIR / "ontokin_vocabulary_definitions.csv"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    return _load_ontokin_vocab(str(path), mtime)


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


def _rdf_response(request, graph, fmt):
    content_type, rdflib_format = fmt
    data = graph.serialize(format=rdflib_format)
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return HttpResponse(data, content_type=f"{content_type}; charset=utf-8")


# --- views ------------------------------------------------------------------
def resolve_node(request, kind, slug):
    """Dereference a minted entity IRI (species, reference, kineticmodel, ...)."""
    prefix = KIND_PREFIX.get(kind)
    if prefix is None:
        raise Http404("Unknown identifier kind")
    curie = f"{prefix}:{slug}"
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
