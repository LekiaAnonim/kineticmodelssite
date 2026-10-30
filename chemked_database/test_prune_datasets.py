"""ChemKED datasets that match a ChemKED-database checkout (prune_chemked_datasets, sync_chemked).

The database holds the files of the repository's main branch and nothing else: no dataset the
web pages stored without a file, no dataset of a moved file, and no second copy of a file's
compositions and values after a re-ingest. Kept apart from tests.py, which needs
pyked.batch_convert.
"""

import shutil
import tempfile
from io import StringIO
from pathlib import Path

import yaml
from django.core.management import CommandError, call_command
from django.test import TestCase

from .management.commands.sync_chemked import store_chemked_data
from .models import Composition, CompositionSpecies, ExperimentDataset, ValueWithUnit

TESTDATA = Path(__file__).resolve().parent / "testdata"
IN_MAIN = "hydrogen/Test_2020/Test_2020_ST_7.yaml"


def counts():
    return {
        "datasets": ExperimentDataset.objects.count(),
        "compositions": Composition.objects.count(),
        "species": CompositionSpecies.objects.count(),
        "values": ValueWithUnit.objects.count(),
    }


class ChemkedCheckout(TestCase):
    """A checkout with one file, stored once from the checkout, and two datasets without a file."""

    def setUp(self):
        self.checkout = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.checkout)
        target = self.checkout / IN_MAIN
        target.parent.mkdir(parents=True)
        shutil.copy(TESTDATA / "Test_2020_ST_7.yaml", target)
        self.data = yaml.safe_load(target.read_text())

    def sync(self):
        call_command("sync_chemked", path=str(self.checkout), stdout=StringIO(), stderr=StringIO())

    def prune(self, *args):
        out = StringIO()
        call_command("prune_chemked_datasets", "--path", str(self.checkout), *args, stdout=out)
        return out.getvalue()


class ReingestTests(ChemkedCheckout):
    def test_a_second_ingest_leaves_no_second_copy(self):
        self.sync()
        first = counts()
        self.sync()
        self.assertEqual(counts(), first)
        self.assertFalse(Composition.objects.filter(datapoints__isnull=True, common_properties__isnull=True).exists())


class PruneTests(ChemkedCheckout):
    def setUp(self):
        super().setUp()
        self.sync()
        self.kept = counts()
        # Stored by the web pages under a flat name, and a file that moved in the repository
        store_chemked_data(self.data, "H2_Test_2020_ST_10004084", lambda message: None)
        store_chemked_data(self.data, "hydrogen/Old_folder/Test_2020_ST_7.yaml", lambda message: None)
        # A composition that an earlier re-ingest left behind
        left = Composition.objects.create(kind="mole fraction")
        CompositionSpecies.objects.create(composition=left, species_name="O2", amount=0.2)

    def test_dry_run_writes_nothing(self):
        before = counts()
        out = self.prune()
        self.assertEqual(counts(), before)
        self.assertIn("2 without", out)
        self.assertIn("1 with a flat name", out)
        self.assertIn("1 with a repository path not in the checkout", out)
        self.assertIn("rolled back", out)

    def test_only_the_files_of_the_checkout_stay(self):
        self.prune("--apply")
        self.assertEqual(list(ExperimentDataset.objects.values_list("chemked_file_path", flat=True)), [IN_MAIN])
        self.assertEqual(counts(), self.kept)

    def test_a_second_run_changes_nothing(self):
        self.prune("--apply")
        out = self.prune("--apply")
        self.assertIn("0 without", out)
        self.assertIn("Unused rows deleted: 0 compositions with 0 species", out)

    def test_report_lists_the_deleted_datasets(self):
        report = self.checkout / "deleted.csv"
        self.prune("--report", str(report))
        rows = report.read_text().splitlines()
        self.assertEqual(len(rows), 3)
        self.assertIn("H2_Test_2020_ST_10004084", rows[1])

    def test_a_checkout_without_files_is_refused(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty)
        with self.assertRaises(CommandError):
            call_command("prune_chemked_datasets", "--path", str(empty), "--apply", stdout=StringIO())
        self.assertEqual(ExperimentDataset.objects.count(), 3)
