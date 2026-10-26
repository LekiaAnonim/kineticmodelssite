"""
Tests for the ingest-after-merge path (sync_chemked --files) and the shared
ChemKED import used by the REST contribution API.

Kept apart from tests.py, which needs pyked.batch_convert.
"""

import os
import shutil
import tempfile
from io import StringIO
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from .import_dispatcher import import_chemked_to_db
from .management.commands.sync_chemked import experiment_type_of, time_first
from .models import ExperimentDataset, ExperimentType

TESTDATA = Path(__file__).resolve().parent / "testdata"
FIXTURE_NAME = "Test_2020_ST_7.yaml"


class SyncChemkedIngestTests(TestCase):
    """What the chemked-ingest workflow runs after a merge."""

    def _sync(self, *files, **options):
        call_command(
            "sync_chemked", files=list(files), stdout=StringIO(), stderr=StringIO(), **options
        )

    def test_settings_path_is_the_default(self):
        with self.settings(CHEMKED_DATABASE_PATH=str(TESTDATA)):
            self._sync(FIXTURE_NAME)

        dataset = ExperimentDataset.objects.get(chemked_file_path=FIXTURE_NAME)
        self.assertEqual(dataset.datapoints.count(), 2)

    def test_reingest_replaces_datapoints(self):
        self._sync(FIXTURE_NAME, path=str(TESTDATA))
        self._sync(FIXTURE_NAME, path=str(TESTDATA))

        dataset = ExperimentDataset.objects.get(chemked_file_path=FIXTURE_NAME)
        self.assertEqual(dataset.datapoints.count(), 2)

    def test_missing_file_fails_the_command(self):
        with self.assertRaises(CommandError):
            self._sync("no-such-dir/missing.yaml", path=str(TESTDATA))


# A jet-stirred reactor file of ChemKED-database (hydrogen/Cong_2009), shortened
SPECIATION_FILE = """\
file-authors:
  - name: Test Author
file-version: 0
chemked-version: 0.5.0
reference:
  doi: 10.1021/ef800832q
  authors:
    - name: T. Le Cong
  journal: Energy & Fuels
  year: 2009
experiment-type: speciation measurement
apparatus:
  kind: jet stirred reactor
common-properties:
  pressure: [1 atm]
  composition: &comp
    kind: mole fraction
    species:
      - {species-name: H2, InChI: 1S/H2/h1H, amount: [0.0108]}
      - {species-name: O2, InChI: 1S/O2/c1-2, amount: [0.025]}
      - {species-name: N2, InChI: 1S/N2/c1-2, amount: [0.9642]}
datapoints:
  - independent-variables:
      - {name: temperature, units: K, primary: true}
    concentration-profiles:
      - species-name: H2
        InChI: 1S/H2/h1H
        quantity: {units: mole fraction}
        values: [[800.0, 0.0108], [900.0, 0.00751]]
    pressure: [1 atm]
    composition: *comp
"""

LBV_FILE = """\
file-authors:
  - name: Test Author
file-version: 0
chemked-version: 0.5.0
reference:
  authors:
    - name: A. Tester
  year: 2020
experiment-type: laminar burning velocity measurement
apparatus:
  kind: heat flux burner
datapoints:
  - temperature: [298 K]
    pressure: [1 atm]
    laminar-burning-velocity: [40 cm/s]
    composition:
      kind: mole fraction
      species:
        - {species-name: H2, InChI: 1S/H2/h1H, amount: [0.3]}
        - {species-name: O2, InChI: 1S/O2/c1-2, amount: [0.15]}
        - {species-name: N2, InChI: 1S/N2/c1-2, amount: [0.55]}
"""


class SyncChemkedExperimentTypeTests(TestCase):
    """A file is stored with its own experiment type or not at all."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.err = StringIO()

    def _write(self, rel, text):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)

    def _sync(self, *files):
        call_command(
            "sync_chemked", path=str(self.root), files=list(files),
            stdout=StringIO(), stderr=self.err,
        )

    def test_speciation_measurement_is_not_stored_as_ignition_delay(self):
        rel = "hydrogen/Cong_2009/Cong_2009_jsr_p1atm.yaml"
        self._write(rel, SPECIATION_FILE)

        with self.assertRaises(CommandError):
            self._sync(rel)

        self.assertFalse(ExperimentDataset.objects.exists())
        self.assertIn(
            "experiment-type 'speciation measurement' is not supported", self.err.getvalue()
        )
        self.assertNotIn("defaulting to", self.err.getvalue())

    def test_unknown_and_missing_types_are_not_stored(self):
        unknown = yaml.safe_load(LBV_FILE) | {"experiment-type": "flame speed"}
        missing = yaml.safe_load(LBV_FILE)
        del missing["experiment-type"]
        self._write("x/unknown.yaml", yaml.safe_dump(unknown))
        self._write("x/missing.yaml", yaml.safe_dump(missing))

        with self.assertRaisesMessage(CommandError, "2 file(s) were not imported"):
            self._sync("x/unknown.yaml", "x/missing.yaml")

        self.assertFalse(ExperimentDataset.objects.exists())
        self.assertIn("unknown experiment-type 'flame speed'", self.err.getvalue())
        self.assertIn("experiment-type is missing", self.err.getvalue())

    def test_other_files_of_the_run_are_imported(self):
        self._write("x/jsr.yaml", SPECIATION_FILE)
        self._write("x/lbv.yaml", LBV_FILE)

        with self.assertRaisesMessage(CommandError, "1 file(s) were not imported"):
            self._sync("x/jsr.yaml", "x/lbv.yaml")

        dataset = ExperimentDataset.objects.get()
        self.assertEqual(dataset.chemked_file_path, "x/lbv.yaml")
        self.assertEqual(dataset.experiment_type, ExperimentType.LAMINAR_BURNING_VELOCITY)
        lbv = dataset.datapoints.get().laminar_burning_velocity_measurement
        self.assertAlmostEqual(lbv.laminar_burning_velocity, 0.4)

    def test_dataset_stored_earlier_is_named_and_left_unchanged(self):
        rel = "x/jsr.yaml"
        self._write(rel, SPECIATION_FILE)
        stale = ExperimentDataset.objects.create(
            chemked_file_path=rel, experiment_type=ExperimentType.IGNITION_DELAY
        )

        with self.assertRaises(CommandError):
            self._sync(rel)

        self.assertIn(
            f"dataset {stale.pk} stored earlier for this file was left unchanged",
            self.err.getvalue(),
        )
        stale.refresh_from_db()
        self.assertEqual(stale.experiment_type, ExperimentType.IGNITION_DELAY)


class ExperimentTypeOfTests(SimpleTestCase):
    def test_site_types_are_kept(self):
        for value in ExperimentType.values:
            with self.subTest(value=value):
                self.assertEqual(experiment_type_of({"experiment-type": value}), value)

    def test_other_types_raise(self):
        for data in ({}, {"experiment-type": ""}, {"experiment-type": "speciation measurement"},
                     {"experiment-type": "Ignition Delay"}):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    experiment_type_of(data)


class TimeFirstTests(SimpleTestCase):
    def test_time_column_first(self):
        rows = [[1.0, 0.0], [0.9, 2.5]]
        self.assertEqual(time_first(rows, {"column": 1}, {"column": 0}), [[0.0, 1.0], [2.5, 0.9]])
        self.assertIs(time_first(rows, {"column": 0}, {"column": 1}), rows)
        self.assertIs(time_first(rows, None, None), rows)

    def test_uncertainty_column_kept(self):
        rows = [[1.0, 0.0, 0.1]]
        self.assertEqual(time_first(rows, {"column": 1}, {"column": 0}), [[0.0, 1.0, 0.1]])


class ChemkedDatabasePathSettingTests(TestCase):
    def test_setting_is_defined(self):
        expected = os.getenv(
            "CHEMKED_DATABASE_PATH",
            os.path.join(os.path.dirname(settings.BASE_DIR), "ChemKED-database"),
        )
        self.assertEqual(settings.CHEMKED_DATABASE_PATH, expected)


class ImportChemkedToDbTests(TestCase):
    """The API's import_to_db option uses the web upload's importer."""

    def test_imports_yaml_bytes(self):
        dataset = import_chemked_to_db(
            (TESTDATA / FIXTURE_NAME).read_bytes(), FIXTURE_NAME, file_author="Test Author"
        )

        self.assertEqual(dataset.datapoints.count(), 2)
        self.assertEqual(dataset.reference_year, 2020)
        self.assertEqual(dataset.experiment_type, "ignition delay")

    def test_custom_dataset_name(self):
        dataset = import_chemked_to_db(
            (TESTDATA / FIXTURE_NAME).read_text(), FIXTURE_NAME, dataset_name="api-test"
        )

        self.assertEqual(dataset.chemked_file_path, "api-test")

    def test_rejects_non_mapping(self):
        with self.assertRaises(ValueError):
            import_chemked_to_db(b"- just\n- a list\n", "bad.yaml")
