import os
import shutil
import tempfile

from django.test import TestCase

from database import models as db
from database.scripts.import_rmg_models import (
    get_or_create_species, get_reaction_hash, get_species_hash, import_kinetics, import_thermo)
from database.services import cleanup
from database.tests.test_import_rmg_species_unit import MODELS, model_folder, molecule, resonance_forms

FIELDS = {"coeffs_poly1": [3.5, 0, 0, 0, 0, 100.0, 1.0], "coeffs_poly2": [3.5, 0, 0, 0, 0, 100.0, 1.0],
          "temp_min_1": 298.0, "temp_max_1": 1000.0, "temp_min_2": 1000.0, "temp_max_2": 5000.0}
RATE = {"type": "Arrhenius", "A": 1e14, "n": 0, "Ea": 0}


def split_records(label="HCCO"):
    """The two records an older import left for one radical: one resonance form (from a thermo
    entry) and the full set (from a reaction)."""
    forms = resonance_forms(label)
    get_or_create_species(None, "", forms, MODELS)
    isomers = list(db.Isomer.objects.filter(formula__formula=forms[0].get_formula()).order_by("pk"))
    db.Species.objects.filter(isomers__in=isomers).delete()
    single = db.Species.objects.create(hash="single")
    single.isomers.add(isomers[0])
    full = db.Species.objects.create(hash="full")
    full.isomers.add(*isomers)
    return single, full


def reaction(*rows):
    """A reaction from (coeff, species) rows, as the importer stores it."""
    row = db.Reaction.objects.create(hash=get_reaction_hash(rows), reversible=True)
    for coeff, species in rows:
        db.Stoichiometry.objects.create(reaction=row, species=species, coeff=coeff)
    return row


def provider_copy(species, thermo_fields=FIELDS):
    copy = db.Thermo.objects.create(species=species, **thermo_fields)
    db.ThermoRecord.objects.create(
        species=species, structure=db.Structure.objects.filter(isomer__species=species).first(),
        provider="rmg_thermo_library", external_id=f"copy-{copy.pk}", source_version="test",
        label="copy", nasa_thermo=copy)
    return copy


class MergeSplitSpeciesTests(TestCase):
    def setUp(self):
        self.single, self.full = split_records()
        self.a = db.KineticModel.objects.create(model_name="a")
        self.b = db.KineticModel.objects.create(model_name="b")
        # Model a: name and thermo on the one-form record, an empty placeholder and its
        # reaction on the full record. Model b: everything on the full record.
        db.SpeciesName.objects.create(species=self.single, kinetic_model=self.a, name="HCCO")
        db.SpeciesName.objects.create(species=self.full, kinetic_model=self.a, name="")
        db.SpeciesName.objects.create(species=self.full, kinetic_model=self.b, name="HCCO")
        self.thermo = db.Thermo.objects.create(species=self.single, **FIELDS)
        db.ThermoComment.objects.create(thermo=self.thermo, kinetic_model=self.a)
        self.record = db.ThermoRecord.objects.create(
            species=self.single, structure=db.Structure.objects.filter(isomer__species=self.single).first(),
            provider="burcat", external_id="HCCO", source_version="test", label="HCCO")
        o = get_or_create_species(None, "", [molecule("O")], MODELS)
        co = get_or_create_species(None, "", [molecule("CO")], MODELS)
        # The same reaction twice, once on each record, with the same rate.
        self.r_single = reaction((-1, self.single), (-1, o), (2, co))
        self.r_full = reaction((-1, self.full), (-1, o), (2, co))
        k_single = db.Kinetics.objects.create(reaction=self.r_single, raw_data=RATE)
        k_full = db.Kinetics.objects.create(reaction=self.r_full, raw_data=RATE)
        db.KineticsComment.objects.create(kinetics=k_single, kinetic_model=self.a)
        db.KineticsComment.objects.create(kinetics=k_full, kinetic_model=self.b)
        db.KineticsRecord.objects.create(
            reaction=self.r_full, provider="rmg_library", external_id="x", source_version="test",
            label="HCCO + O", raw_data=RATE)

    def test_report_counts_the_split(self):
        report = cleanup.integrity_report()
        self.assertEqual(report["split_species"], 1)
        self.assertEqual(report["split_species_with_model_names_on_2plus_records"], 1)
        self.assertEqual(report["name_links_empty_next_to_a_name"], 0)
        self.assertEqual(report["reactions_sharing_stoichiometry"], 0)

    def test_merge_moves_every_reference_to_the_record_with_all_forms(self):
        report = cleanup.merge_split_species(apply=True)
        self.assertEqual(report["records_merged_away"], 1)
        self.assertEqual(report["reactions_merged"], 1)
        self.assertFalse(db.Species.objects.filter(pk=self.single.pk).exists())
        full = db.Species.objects.get(pk=self.full.pk)
        self.assertEqual(full.hash, get_species_hash(full.isomers.all()))
        self.assertEqual(sorted(full.speciesname_set.values_list("kinetic_model__model_name", "name")),
                         [("a", "HCCO"), ("b", "HCCO")])
        self.thermo.refresh_from_db()
        self.record.refresh_from_db()
        self.assertEqual((self.thermo.species_id, self.record.species_id), (full.pk, full.pk))
        # One reaction, one kinetics row used by both models, the provider record on it.
        reaction_row = db.Reaction.objects.get(stoichiometry__species=full)
        self.assertEqual(reaction_row.pk, self.r_single.pk)
        self.assertEqual(reaction_row.hash, cleanup.stoichiometry_hash(reaction_row.pk))
        kinetics = db.Kinetics.objects.get(reaction=reaction_row)
        self.assertEqual(set(kinetics.kineticscomment_set.values_list("kinetic_model__model_name", flat=True)),
                         {"a", "b"})
        self.assertEqual(db.KineticsRecord.objects.get().reaction_id, reaction_row.pk)
        report = cleanup.integrity_report()
        self.assertEqual((report["split_species"], report["model_names_on_2plus_records"],
                          report["species_with_stale_hash"], report["reactions_with_stale_hash"]), (0, 0, 0, 0))

    def test_dry_run_writes_nothing(self):
        before = (db.Species.objects.count(), db.Reaction.objects.count(), db.SpeciesName.objects.count())
        report = cleanup.merge_split_species(apply=False)
        self.assertEqual(report["records_merged_away"], 1)
        self.assertEqual(before, (db.Species.objects.count(), db.Reaction.objects.count(),
                                  db.SpeciesName.objects.count()))

    def test_states_are_not_merged(self):
        ground = get_or_create_species(None, "OH", [molecule("OH")], MODELS)
        excited = get_or_create_species(None, "OH*", [molecule("OH")], MODELS, electronic_state="A^2S+")
        groups = cleanup.split_groups()
        self.assertFalse(any({ground.pk, excited.pk} <= set(g) for g in groups))


class RebuildModelLinksTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        self.model = db.KineticModel.objects.create(model_name="model")
        self.thermo_path, self.kinetics_path = model_folder(
            self.directory, "model", ["H", "O", "O2", "OH*", "OH", "H2O", "HCCO", "CO", "AR"], kinetics=True)
        import_thermo(self.thermo_path, self.model, MODELS)
        import_kinetics(self.kinetics_path, self.model, MODELS)
        self.clean = self.links()
        self.oh = self.record("OH")
        # What an older import left: OH* also named on the ground state, a second link to one
        # thermo row, a link to a provider's copy.
        db.SpeciesName.objects.create(species=self.oh, kinetic_model=self.model, name="OH*")
        first = db.ThermoComment.objects.filter(kinetic_model=self.model).first()
        db.ThermoComment.objects.create(thermo=first.thermo, kinetic_model=self.model, comment=first.comment)
        thermo = self.oh.thermo_set.get()
        copy = provider_copy(self.oh, {k: getattr(thermo, k) for k in FIELDS})
        db.ThermoComment.objects.create(thermo=copy, kinetic_model=self.model)

    def record(self, name):
        return db.Species.objects.get(speciesname__kinetic_model=self.model, speciesname__name=name,
                                      electronic_state="" if name == "OH" else "A^2S+")

    def links(self):
        return (sorted(db.SpeciesName.objects.filter(kinetic_model=self.model).values_list("species_id", "name")),
                sorted(db.ThermoComment.objects.filter(kinetic_model=self.model).values_list("thermo_id", flat=True)),
                sorted(db.KineticsComment.objects.filter(kinetic_model=self.model).values_list("kinetics_id", flat=True)))

    def test_rebuild_leaves_exactly_what_the_importer_makes(self):
        report = cleanup.integrity_report()
        self.assertEqual((report["thermo_links_duplicate"], report["thermo_links_to_provider_rows"],
                          report["excited_names_on_ground_state_records"]), (1, 1, 1))
        result = cleanup.rebuild_model_links(self.model, self.thermo_path, self.kinetics_path)
        self.assertEqual(self.links(), self.clean)
        self.assertEqual(result["names"]["removed"], 1)
        self.assertEqual(result["thermo_links"]["removed"], 2)
        self.assertEqual(result["kinetics_links"]["removed"], 0)
        report = cleanup.integrity_report()
        self.assertEqual((report["thermo_links_duplicate"], report["thermo_links_to_provider_rows"],
                          report["excited_names_on_ground_state_records"]), (0, 0, 0))

    def test_links_whose_entries_fail_to_import_are_kept(self):
        o2 = db.Species.objects.get(speciesname__kinetic_model=self.model, speciesname__name="O2")
        db.SpeciesName.objects.create(species=o2, kinetic_model=self.model, name="OXYGEN")
        with open(self.kinetics_path, "w") as handle:
            handle.write("entry(\n")  # the library no longer loads
        result = cleanup.rebuild_model_links(self.model, self.thermo_path, self.kinetics_path)
        self.assertTrue(result["kinetics_import"].startswith("library not loaded"))
        names, _, kinetics = self.links()
        self.assertEqual(kinetics, self.clean[2])
        self.assertIn((o2.pk, "OXYGEN"), names)
        # A name the thermo library gives to another record is still replaced.
        self.assertNotIn((self.oh.pk, "OH*"), names)
        self.assertEqual(result["kinetics_links"]["kept_after_import_failure"], len(self.clean[2]))


class PruneUnlinkedRowsTests(TestCase):
    def test_only_rows_nothing_refers_to_are_deleted(self):
        model = db.KineticModel.objects.create(model_name="m")
        h = get_or_create_species(model, "H", [molecule("H")], MODELS)
        o = get_or_create_species(model, "O", [molecule("O")], MODELS)
        lonely = get_or_create_species(None, "", [molecule("AR")], MODELS)
        db.SpeciesName.objects.filter(species=lonely).delete()
        provided = get_or_create_species(None, "", [molecule("CO")], MODELS)
        db.SpeciesName.objects.filter(species=provided).delete()
        provider_copy(provided)
        used = db.Thermo.objects.create(species=h, **FIELDS)
        db.ThermoComment.objects.create(thermo=used, kinetic_model=model)
        unused = db.Thermo.objects.create(species=h, **{**FIELDS, "temp_max_2": 3000.0})
        linked = reaction((-1, h), (1, o))
        db.KineticsComment.objects.create(
            kinetics=db.Kinetics.objects.create(reaction=linked, raw_data=RATE), kinetic_model=model)
        orphan = reaction((-2, o), (1, h))
        orphan_kinetics = db.Kinetics.objects.create(reaction=orphan, raw_data=RATE)
        db.Efficiency.objects.create(species=h, kinetics=orphan_kinetics, efficiency=2.0)
        external = reaction((-1, o), (2, h))
        db.KineticsRecord.objects.create(reaction=external, provider="rmg_library", external_id="e",
                                         source_version="test", label="O = 2 H", raw_data=RATE)
        report = cleanup.prune_unlinked_rows(apply=True)
        self.assertFalse(db.Thermo.objects.filter(pk=unused.pk).exists())
        self.assertTrue(db.Thermo.objects.filter(pk=used.pk).exists())
        self.assertEqual(db.Thermo.objects.filter(species=provided).count(), 1)
        self.assertFalse(db.Kinetics.objects.filter(pk=orphan_kinetics.pk).exists())
        self.assertFalse(db.Reaction.objects.filter(pk=orphan.pk).exists())
        self.assertTrue(db.Reaction.objects.filter(pk__in=[linked.pk, external.pk]).count() == 2)
        self.assertFalse(db.Species.objects.filter(pk=lonely.pk).exists())
        self.assertTrue(db.Species.objects.filter(pk=provided.pk).exists())
        self.assertEqual(report["database.Reaction"]["kept_only_for"], {"database.KineticsRecord": 1})
