from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rmgpy.molecule import Molecule

from database import models
from database.services import chemistry_index, nist
from database.services import thermo_sources as sources


class IdentifierTests(SimpleTestCase):
    def test_cas_check_digit(self):
        self.assertTrue(nist.valid_cas("7782-44-7"))
        self.assertFalse(nist.valid_cas("7782-44-8"))

    def test_webbook_links_use_standard_inchi(self):
        # RMG's unpaired-electron and lone-pair layers are not standard InChI.
        self.assertEqual(nist.standard_inchi("InChI=1S/O2/c1-2/u1,2"), "InChI=1S/O2/c1-2")
        self.assertEqual(nist.standard_inchi("InChI=1S/CF/c1-2/u1/lp1"), "InChI=1S/CF/c1-2")
        self.assertEqual(nist.webbook_url("InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3"),
                         "https://webbook.nist.gov/cgi/inchi/InChI=1S/C2H6O/c1-2-3/h3H%2C2H2%2C1H3")
        self.assertEqual(nist.webbook_url(""), "")


class SearchLinkTests(TestCase):
    def species(self, smiles, cas=None, atct=None):
        species, structure = sources._species_and_structure(Molecule().from_smiles(smiles), smiles)
        if cas:
            models.StructureName.objects.create(structure=structure, name=cas)
        if atct:
            models.ThermoRecord.objects.create(
                species=species, structure=structure, provider="atct", external_id=f"{atct}*0", source_version="test",
                label=smiles, raw_data={"CASRN": atct})
        return species

    def setUp(self):
        # H and OH come from ATcT only, as radicals usually do; O2 and O from PubChem synonyms.
        self.h, self.o2, self.oh, self.o = (self.species(s, c, a) for s, c, a in (
            ("[H]", None, "12385-13-6"), ("[O][O]", "7782-44-7", None),
            ("[OH]", None, "3352-57-6"), ("[O]", "17778-80-2", None)))
        self.reaction = models.Reaction.objects.create(hash="h+o2", reversible=True)
        for species, coeff in ((self.h, -1), (self.o2, -1), (self.oh, 1), (self.o, 1)):
            models.Stoichiometry.objects.create(reaction=self.reaction, species=species, coeff=coeff)
        chemistry_index.index_reactions()

    def test_every_species_identified(self):
        found = nist.search_links(self.reaction)
        labels = [link["label"] for link in found["links"]]
        self.assertEqual(labels, ["This reaction", "Written in reverse", "All reactions of H + O2", "All reactions of HO + O"])
        forward = found["links"][0]["url"]
        for part in ("r0=12385136", "r1=7782447", "r4=0", "p0=3352576", "p1=17778802", "p4=0", "expandResults=true"):
            self.assertIn(part, forward)
        self.assertIn("r0=3352576", found["links"][1]["url"])
        self.assertIn("p0=-10", found["links"][2]["url"])        # any products
        self.assertEqual(found["missing"], [])
        self.assertEqual({s["formula"]: s["cas_source"] for s in found["species"]},
                         {"H": "ATcT", "O2": "PubChem", "HO": "ATcT", "O": "PubChem"})
        page = self.client.get(reverse("reaction-detail", args=[self.reaction.pk]))
        self.assertContains(page, "Search NIST Chemical Kinetics:")
        self.assertContains(page, "This reaction")

    def test_one_side_identified(self):
        models.StructureName.objects.filter(name="17778-80-2").delete()
        found = nist.search_links(self.reaction)
        self.assertEqual([link["label"] for link in found["links"]], ["All reactions of H + O2"])
        self.assertEqual([s["formula"] for s in found["missing"]], ["O"])
        page = self.client.get(reverse("reaction-detail", args=[self.reaction.pk]))
        self.assertContains(page, "none was found for")
        self.assertContains(page, "https://webbook.nist.gov/cgi/inchi/InChI=1S/O")

    def test_ambiguous_pubchem_cas_needs_atct(self):
        structure = models.Structure.objects.filter(isomer__species=self.o2).first()
        models.StructureName.objects.create(structure=structure, name="80937-33-3")   # a second valid CAS
        self.assertNotIn(self.o2.pk, nist.species_cas([self.o2.pk]))
        models.ThermoRecord.objects.create(species=self.o2, structure=structure, provider="atct", external_id="7782-44-7*0",
                                           source_version="test", label="O2", raw_data={"CASRN": "7782-44-7"})
        self.assertEqual(nist.species_cas([self.o2.pk])[self.o2.pk], ("7782-44-7", "ATcT"))

    def test_inchikey_cas_is_the_last_resort(self):
        # PubChem by InChIKey (enrich_structure_cas) fills a species neither ATcT nor its synonyms cover.
        models.StructureName.objects.filter(name="17778-80-2").delete()
        models.Structure.objects.filter(isomer__species=self.o).update(cas_numbers=["17778-80-2", "1-00-0"])
        self.assertEqual(nist.species_cas([self.o.pk])[self.o.pk], ("17778-80-2", "PubChem, by InChIKey, first of 2"))
        self.assertIn("This reaction", [link["label"] for link in nist.search_links(self.reaction)["links"]])
