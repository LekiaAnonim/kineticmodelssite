"""Export the provenance edges that connect the SSSOM nodes to each other.

The SSSOM mapping set (``prometheus.sssom.tsv``) is an *identifier crosswalk*:
every row maps one local entity to one external authority id, so the graph it
draws is intentionally a field of disconnected stars.  The relationships that
actually tie those entities together -- which species a kinetic model uses,
which publication a dataset cites -- live in the platform database as foreign
keys, not as mappings, so they are deliberately *not* in the SSSOM file.

This command reads those database relationships and emits them as a sidecar so
the interactive graph (``sssom_graph.py``) can overlay a connectivity layer on
top of the pure mapping set, without polluting the SSSOM artifact.  Endpoints are
the existing SSSOM subject CURIEs (resolved via the populated SemanticMapping
foreign keys), so an edge is only emitted when *both* of its nodes already exist
in the graph.

Two outputs (both beside the TSV by default):
  * ``prometheus.provenance.json`` -- typed edges for the HTML graph overlay.
  * ``prometheus.provenance.ttl``  -- the same edges as RDF, designed to be
    loaded *alongside* ``prometheus.sssom.ttl``: shared IRIs connect the two
    layers into one knowledge graph (SSSOM = authority bridges, this = domain
    links) without merging provenance into the mapping set.

Relationship types (all kept even when a type currently resolves to zero edges,
so the overlay lights up automatically as coverage improves):
  * ``uses``     KineticModel       --> Species          (via SpeciesName)
  * ``cites``    ExperimentDataset  --> publication       (promds <-> promref)
  * ``contains`` ExperimentDataset  --> Species          (via CompositionSpecies)
  * ``from``     KineticModel       --> Source/publication (model's reference)

Read-only against the database; idempotent (overwrites the sidecars).
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand

from chemked_database.models import CompositionSpecies, ExperimentDataset
from database.models import KineticModel
from database.models.kinetic_model import SpeciesName
from provenance.models import SemanticMapping

# Sidecars live beside the SSSOM artifacts in the sibling mappings/ directory.
# This file: <Prometheus>/kineticmodelssite/provenance/management/commands/<this>
#            parents: [0]commands [1]management [2]provenance [3]kineticmodelssite
#                     [4]Prometheus
MAPPINGS_DIR = Path(__file__).resolve().parents[4] / "mappings"
DEFAULT_JSON = MAPPINGS_DIR / "prometheus.provenance.json"
DEFAULT_TTL = MAPPINGS_DIR / "prometheus.provenance.ttl"

# Local domain predicates for the RDF (knowledge-graph) serialization.
PROMV = "https://dev.omethe.us/vocab/"
PREDICATE_IRI = {
    "uses": PROMV + "usesSpecies",
    "contains": PROMV + "containsSpecies",
    "cites": "http://purl.org/dc/terms/references",
    "from": "http://purl.org/dc/terms/source",
}


def _norm_doi(value):
    return (value or "").strip().lower().rstrip("/")


def _norm_inchi(value):
    """Normalize an InChI string so the ``InChI=`` prefix is always present."""
    value = (value or "").strip()
    if not value:
        return ""
    return value if value.startswith("InChI=") else "InChI=" + value


class Command(BaseCommand):
    help = (
        "Export database provenance edges (KM-uses-species, dataset-cites-"
        "publication, ...) as a sidecar for the SSSOM graph overlay."
    )

    def add_arguments(self, parser):
        parser.add_argument("--json", default=str(DEFAULT_JSON))
        parser.add_argument("--ttl", default=str(DEFAULT_TTL))
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report edge counts without writing the sidecars.",
        )

    # -- node resolution -------------------------------------------------
    def _resolve_nodes(self):
        """Map each DB entity id -> the SSSOM subject CURIEs that represent it."""
        ds_subjects = defaultdict(set)
        km_subject = {}
        sp_subjects = defaultdict(set)
        sp_by_inchi = defaultdict(set)
        promref_by_doi = {}

        for r in SemanticMapping.objects.filter(
            experiment_dataset__isnull=False
        ).values("experiment_dataset_id", "subject_id"):
            ds_subjects[r["experiment_dataset_id"]].add(r["subject_id"])
        for r in SemanticMapping.objects.filter(
            kinetic_model__isnull=False
        ).values("kinetic_model_id", "subject_id"):
            km_subject[r["kinetic_model_id"]] = r["subject_id"]
        for r in SemanticMapping.objects.filter(species__isnull=False).values(
            "species_id", "subject_id", "subject_match_field"
        ):
            sp_subjects[r["species_id"]].add(r["subject_id"])
            inchi = _norm_inchi(r["subject_match_field"])
            if inchi:
                sp_by_inchi[inchi].add(r["subject_id"])
        for r in SemanticMapping.objects.filter(
            subject_id__startswith="promref:", object_id__startswith="doi:"
        ).values("subject_id", "object_id"):
            promref_by_doi.setdefault(
                _norm_doi(r["object_id"][len("doi:"):]), r["subject_id"]
            )
        return ds_subjects, km_subject, sp_subjects, sp_by_inchi, promref_by_doi

    @staticmethod
    def _dataset_anchor(subjects):
        """Prefer the dataset-identity (promds) node as a dataset's anchor."""
        promds = sorted(s for s in subjects if s.startswith("promds:"))
        if promds:
            return promds[0]
        promref = sorted(s for s in subjects if s.startswith("promref:"))
        return promref[0] if promref else None

    # -- main ------------------------------------------------------------
    def handle(self, *args, **options):
        (
            ds_subjects,
            km_subject,
            sp_subjects,
            sp_by_inchi,
            promref_by_doi,
        ) = self._resolve_nodes()

        edges = []
        seen = set()

        def emit(src, dst, kind):
            if not src or not dst or src == dst:
                return
            key = (src, dst, kind)
            if key in seen:
                return
            seen.add(key)
            edges.append({"from": src, "to": dst, "kind": kind})

        # (1) KineticModel --uses--> Species
        for sn in (
            SpeciesName.objects.filter(
                kinetic_model_id__in=km_subject.keys(),
                species_id__in=sp_subjects.keys(),
            )
            .values("kinetic_model_id", "species_id")
            .distinct()
        ):
            src = km_subject.get(sn["kinetic_model_id"])
            for dst in sp_subjects.get(sn["species_id"], ()):
                emit(src, dst, "uses")

        # (2) ExperimentDataset --cites--> publication (promds <-> promref)
        for ds_id, subjects in ds_subjects.items():
            anchor = self._dataset_anchor(subjects)
            for s in subjects:
                if s.startswith("promref:"):
                    emit(anchor, s, "cites")

        # (3) ExperimentDataset --contains--> Species (via CompositionSpecies).
        # CompositionSpecies.database_species is not backfilled, but each row
        # carries the raw InChI, so match that to the InChI-keyed species nodes
        # (same basis the SSSOM species rows use) and walk composition ->
        # datapoints -> dataset for the anchor.
        comp_pairs = (
            CompositionSpecies.objects.exclude(inchi="")
            .values("inchi", "composition__datapoints__dataset_id")
            .distinct()
        )
        for cp in comp_pairs:
            ds_id = cp["composition__datapoints__dataset_id"]
            if ds_id is None:
                continue
            dsts = sp_by_inchi.get(_norm_inchi(cp["inchi"]))
            if not dsts:
                continue
            anchor = self._dataset_anchor(ds_subjects.get(ds_id, set()))
            for dst in dsts:
                emit(anchor, dst, "contains")

        # (4) KineticModel --from--> publication (model's Source DOI)
        for km in KineticModel.objects.filter(
            id__in=km_subject.keys(), source__isnull=False
        ).select_related("source"):
            doi = _norm_doi(getattr(km.source, "doi", ""))
            dst = promref_by_doi.get(doi) if doi else None
            emit(km_subject.get(km.id), dst, "from")

        counts = defaultdict(int)
        for e in edges:
            counts[e["kind"]] += 1

        self.stdout.write("Provenance edges resolved to existing SSSOM nodes:")
        for kind in ("uses", "cites", "contains", "from"):
            self.stdout.write(f"  {kind:9s} {counts[kind]}")
        self.stdout.write(f"  {'total':9s} {len(edges)}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no files written."))
            return

        json_path = Path(options["json"])
        json_path.write_text(
            json.dumps({"edges": edges, "counts": dict(counts)}, indent=2),
            encoding="utf-8",
        )
        self._write_ttl(Path(options["ttl"]), edges)
        self.stdout.write(self.style.SUCCESS(f"Wrote {json_path}"))
        self.stdout.write(self.style.SUCCESS(f"Wrote {options['ttl']}"))

    # -- RDF serialization ----------------------------------------------
    def _write_ttl(self, path, edges):
        """Serialize the edges as Turtle to load alongside the SSSOM graph."""
        curie_map = self._curie_map()

        def iri(curie):
            if "://" in curie:
                return curie
            prefix, _, local = curie.partition(":")
            base = curie_map.get(prefix)
            return (base + local) if base else None

        lines = [
            "# Prometheus provenance layer (domain relationships between SSSOM",
            "# nodes).  Load together with prometheus.sssom.ttl: shared IRIs",
            "# connect the two layers into one knowledge graph.  Generated by",
            "# `manage.py export_provenance_edges` -- do not edit by hand.",
            "@prefix dcterms: <http://purl.org/dc/terms/> .",
            f"@prefix promv: <{PROMV}> .",
            "",
        ]
        for e in edges:
            s, o = iri(e["from"]), iri(e["to"])
            if not s or not o:
                continue
            pred = PREDICATE_IRI[e["kind"]]
            pred_term = (
                "dcterms:" + pred.rsplit("/", 1)[1]
                if pred.startswith("http://purl.org/dc/terms/")
                else "promv:" + pred.rsplit("/", 1)[1]
            )
            lines.append(f"<{s}> {pred_term} <{o}> .")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _curie_map():
        """Read the curie_map from the SSSOM TSV header for IRI resolution."""
        tsv = MAPPINGS_DIR / "prometheus.sssom.tsv"
        curie_map = {}
        if not tsv.exists():
            return curie_map
        in_block = False
        pair = re.compile(r'^#\s+([\w.]+):\s+"([^"]+)"\s*$')
        for line in tsv.read_text(encoding="utf-8").splitlines():
            if line.startswith("# curie_map:"):
                in_block = True
                continue
            if in_block:
                m = pair.match(line)
                if m:
                    curie_map[m.group(1)] = m.group(2)
                elif not line.startswith("#") or line.strip() == "#":
                    break
        return curie_map
