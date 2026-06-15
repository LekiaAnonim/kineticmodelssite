"""Append OntoKin / Prometheus-ontology class-bridge rows (T-Box) to the SSSOM set.

The rest of the SSSOM set is A-Box: it links *instances* (this species, this
model, this reference) to external identifiers. This command adds the
complementary T-Box layer: it maps Prometheus *concepts* (from
``prometheus_chemked_thesaurus.csv`` / ``prometheus-exp.ttl``) to their ontology
classes, so a single ``/api/semantic-mapping/`` query spans both levels:

  * mechanism concepts (``prom:*``)   -> OntoKin classes (``ontokin:*``), the
    "reuse" layer of the ontology.
  * experimental concepts (``chemked:*``) -> Prometheus extension classes
    (``pmtx:*``), the concepts OntoKin 1.0 does not cover.

The bridge is a fixed, curated table (no instance data, no network). Rows are
appended idempotently -- an existing ``(subject_id, predicate_id, object_id)`` is
never duplicated. ``import_sssom`` then loads them as ``SemanticMapping`` rows;
``link_semantic_mappings`` ignores them (there is no DB table for an ontology
class), so they remain pure class-level mappings.
"""

from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

# Prometheus/mappings/prometheus.sssom.tsv (shared with the A-Box generators).
DEFAULT = Path(__file__).resolve().parents[4] / "mappings" / "prometheus.sssom.tsv"
AUTHOR_ID = "orcid:0000-0001-7137-5721"
TOOL = "generate_ontology_bridge"

# Curated concept -> ontology-class mappings.
#   confidence 1.0 -> skos:exactMatch (direct class equivalence)
#   confidence <1.0 -> skos:closeMatch (closely related, not strict equivalence)
# Mechanism concepts reuse OntoKin; experimental concepts use the pmtx extension.
BRIDGE = [
    # promc: mechanism concepts -> OntoKin classes (REUSE layer)
    ("promc:KineticModel", "Kinetic model", "ontokin:ReactionMechanism", "Reaction mechanism", 0.9),
    ("promc:Species", "Species", "ontokin:ChemicalSpecies", "Chemical species", 1.0),
    ("promc:Reaction", "Reaction", "ontokin:ChemicalReaction", "Chemical reaction", 1.0),
    ("promc:Reactant", "Reactant", "ontokin:Reactant", "Reactant", 1.0),
    ("promc:Product", "Product", "ontokin:Product", "Product", 1.0),
    ("promc:StoichiometricCoefficient", "Stoichiometric coefficient",
     "ontokin:StoichiometricCoefficient", "Stoichiometric coefficient", 1.0),
    ("promc:Kinetics", "Kinetics", "ontokin:RateCoefficient", "Rate coefficient", 0.9),
    ("promc:Arrhenius", "Arrhenius expression", "ontokin:ArrheniusCoefficient", "Arrhenius coefficient", 0.9),
    ("promc:Chebyshev", "Chebyshev rate expression", "ontokin:CHEBRateCoefficient", "Chebyshev rate coefficient", 0.9),
    ("promc:PLOG", "PLOG expression", "ontokin:PLOGReaction", "PLOG reaction", 0.9),
    ("promc:Lindemann", "Lindemann falloff", "ontokin:LindemannReaction", "Lindemann reaction", 0.9),
    ("promc:Troe", "Troe falloff", "ontokin:TroeReaction", "Troe reaction", 0.9),
    ("promc:ThirdBody", "Third-body reaction", "ontokin:ThreeBodyReaction", "Three-body reaction", 0.9),
    ("promc:ThirdBodyEfficiency", "Third-body efficiency", "ontokin:ThirdBodyEfficiency", "Third-body efficiency", 1.0),
    ("promc:Thermo", "Thermodynamic model", "ontokin:ThermoModel", "Thermo model", 0.9),
    ("promc:Transport", "Transport model", "ontokin:TransportModel", "Transport model", 0.9),
    # chemked: experimental concepts -> Prometheus extension classes (OntoKin lacks these)
    ("chemked:ExperimentDataset", "Experiment dataset", "pmtx:ExperimentDataset", "Experiment dataset", 1.0),
    ("chemked:ExperimentDatapoint", "Experiment datapoint", "pmtx:ExperimentDatapoint", "Experiment datapoint", 1.0),
    ("chemked:Measurement", "Measurement", "pmtx:Measurement", "Measurement", 1.0),
    ("chemked:Apparatus", "Apparatus", "pmtx:Apparatus", "Apparatus", 1.0),
]


class Command(BaseCommand):
    help = "Append OntoKin/pmtx class-bridge (T-Box) rows to prometheus.sssom.tsv (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(DEFAULT))
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the rows that would be appended without writing the file.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            self.stderr.write(self.style.ERROR(f"SSSOM file not found: {path}"))
            return

        existing = set()
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or line.startswith("subject_id\t"):
                    continue
                cols = line.rstrip("\n").split("\t")
                if len(cols) >= 4:
                    existing.add((cols[0], cols[2], cols[3]))

        today = date.today().isoformat()
        new_rows = []
        for subject_id, subject_label, object_id, object_label, confidence in BRIDGE:
            predicate = "skos:exactMatch" if confidence >= 1.0 else "skos:closeMatch"
            key = (subject_id, predicate, object_id)
            if key in existing:
                continue
            existing.add(key)
            new_rows.append(
                [
                    subject_id,
                    subject_label,
                    predicate,
                    object_id,
                    object_label,
                    "semapv:ManualMappingCuration",
                    "",  # subject_match_field (class-level, no instance field)
                    f"{confidence}",
                    TOOL,
                    today,
                    AUTHOR_ID,
                    "Concept-to-ontology-class mapping (T-Box).",
                ]
            )

        if not new_rows:
            self.stdout.write(self.style.WARNING("No new class-bridge rows; all present."))
            return

        if options["dry_run"]:
            for r in new_rows:
                self.stdout.write("\t".join(r))
            self.stdout.write(
                self.style.SUCCESS(f"[dry-run] {len(new_rows)} class-bridge rows would be appended.")
            )
            return

        with path.open("a", encoding="utf-8") as fh:
            for r in new_rows:
                fh.write("\t".join(r) + "\n")
        self.stdout.write(
            self.style.SUCCESS(f"Appended {len(new_rows)} class-bridge rows to {path.name}.")
        )
