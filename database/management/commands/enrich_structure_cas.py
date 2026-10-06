from collections import defaultdict

from django.core.management.base import BaseCommand
from django.utils import timezone

from database.models import Isomer, Structure
from database.services.nist import species_cas, standard_inchi
from database.services.pubchem import PubChemClient, PubChemError


def inchikey(inchi):
    from rdkit.Chem import inchi as rdkit_inchi
    return rdkit_inchi.InchiToInchiKey(inchi) or ""


class Command(BaseCommand):
    help = ("Look up CAS numbers in PubChem by standard InChIKey, for structures in reactions that "
            "have no CAS from ATcT or their PubChem synonyms. Used for NIST kinetics search links.")

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int)
        parser.add_argument("--refresh", action="store_true", help="Recheck structures already looked up")

    def handle(self, *args, **options):
        # InChI drops spin, so a standard InChI shared by spin isomers on the site (singlet and
        # triplet CH2, O(1D) and O(3P)) cannot tell which one a CAS number means.
        variants = defaultdict(set)
        for augmented in Isomer.objects.values_list("inchi", flat=True):
            variants[standard_inchi(augmented)].add(augmented)
        structures = (Structure.objects.filter(isomer__species__stoichiometry__isnull=False).distinct()
                      .select_related("isomer").order_by("pk"))
        if not options["refresh"]:
            structures = structures.filter(cas_checked_at__isnull=True)
        species_of = defaultdict(set)
        for structure_id, species_id in Structure.objects.filter(pk__in=structures.values("pk")).values_list(
                "pk", "isomer__species"):
            species_of[structure_id].add(species_id)
        known = species_cas({s for ids in species_of.values() for s in ids})
        client = PubChemClient()
        counts = defaultdict(int)
        for structure in structures.iterator(chunk_size=200):
            if options["limit"] and counts["looked up"] >= options["limit"]:
                break
            if species_of[structure.pk] and all(s in known for s in species_of[structure.pk]):
                counts["already known"] += 1
                continue
            standard = standard_inchi(structure.isomer.inchi)
            numbers = []
            if len(variants[standard]) > 1:
                counts["spin isomers, skipped"] += 1
            else:
                key = inchikey(standard)
                if not key:
                    counts["no InChIKey"] += 1
                    continue
                try:
                    numbers = client.cas_numbers(key)
                except PubChemError as exc:
                    counts["failed"] += 1
                    self.stderr.write(f"Structure {structure.pk}: {exc}")
                    continue
                counts["looked up"] += 1
                counts["one CAS" if len(numbers) == 1 else "several CAS" if numbers else "no CAS"] += 1
            Structure.objects.filter(pk=structure.pk).update(cas_numbers=numbers, cas_checked_at=timezone.now())
            if counts["looked up"] and counts["looked up"] % 200 == 0:
                self.stdout.write(f"{dict(counts)}")
                self.stdout.flush()
        self.stdout.write(f"Done: {dict(counts)}")
