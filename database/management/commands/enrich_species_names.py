from functools import lru_cache

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from database.models import Structure, StructureName
from database.services.chemical_identity import canonical_smiles
from database.services.pubchem import PubChemClient, PubChemError


class Command(BaseCommand):
    help = "Index exact structures and cache PubChem IUPAC names/synonyms for species search."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int)
        parser.add_argument("--after-id", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true", help="Resolve without saving changes")
        parser.add_argument("--refresh", action="store_true", help="Recheck resolved rows")
        parser.add_argument("--index-only", action="store_true", help="Index without API requests")

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be a positive integer")
        queryset = Structure.objects.filter(pk__gt=options["after_id"]).order_by("pk")
        if not options["refresh"]:
            if options["index_only"]:
                queryset = queryset.filter(canonical_smiles="")
            else:
                queryset = queryset.filter(names_checked_at__isnull=True)
        if options["limit"]:
            queryset = queryset[:options["limit"]]

        client = PubChemClient()
        resolve = lru_cache(maxsize=256)(client.resolve)
        indexed = named = skipped = 0
        for structure in queryset.iterator(chunk_size=100):
            identity = canonical_smiles(structure.smiles)
            if not identity:
                try:
                    identity = canonical_smiles(structure.to_rmg().to_smiles())
                except Exception as exc:
                    self.stderr.write(f"Structure {structure.pk}: cannot read structure ({exc})")
            if not identity:
                skipped += 1
                continue
            result = None
            if not options["index_only"]:
                try:
                    result = resolve(identity)
                except PubChemError as exc:
                    raise CommandError(f"Stopped at structure {structure.pk}: {exc}") from exc

            if not options["dry_run"]:
                with transaction.atomic():
                    updates = {"canonical_smiles": identity}
                    if not options["index_only"]:
                        updates["names_checked_at"] = timezone.now()
                        updates["iupac_name"] = result["iupac_name"] if result else ""
                        updates["pubchem_cid"] = result["cid"] if result else None
                    # Guard against a concurrent edit while the API call was in flight.
                    changed = Structure.objects.filter(
                        pk=structure.pk, smiles=structure.smiles,
                        adjacency_list=structure.adjacency_list,
                        multiplicity=structure.multiplicity, isomer_id=structure.isomer_id,
                    ).update(**updates)
                    if not changed:
                        skipped += 1
                        continue
                    if not options["index_only"]:
                        structure.names.all().delete()
                        if result:
                            StructureName.objects.bulk_create([
                                StructureName(structure=structure, name=name)
                                for name in result["synonyms"]
                            ])
            indexed += 1
            if result:
                named += 1
                self.stdout.write(f"Structure {structure.pk}: {result['iupac_name']}")
        mode = "Would index" if options["dry_run"] else "Indexed"
        self.stdout.write(f"{mode} {indexed} structures; named {named}; skipped {skipped}.")
