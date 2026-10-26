"""The ChemKED YAML export keeps what sync_chemked stored, and PyKED can read it."""

import contextlib
import io
import shutil
import tempfile
import warnings
from pathlib import Path

import yaml
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from pyked import chemked

from .models import ExperimentDataset, IgnitionDelayDatapoint

# Shortened from ammonia/Shu_2019 of ChemKED-database (no DOI, as in hydrogen/Naumann_2011),
# with the uncertainty forms found in ChemKED-database added.
CHEMKED_FILE = """\
file-authors:
  - name: Test Author
file-version: 0
chemked-version: 0.5.0
reference:
  authors:
    - name: B. Shu
  journal: Proceedings of the Combustion Institute
  year: 2019
  volume: 37
  pages: 205-211
experiment-type: ignition delay
apparatus:
  kind: shock tube
comments:
  - Reactive volume-time profiles were obtained through personal communication with the authors.
  - Simulations should be carried out using the constant U-V reactor model.
common-properties:
  composition: &comp
    kind: mole fraction
    species:
      - {species-name: NH3, InChI: 1S/H3N/h1H3, amount: [0.1]}
      - {species-name: O2, InChI: 1S/O2/c1-2, amount: [0.15]}
      - {species-name: N2, InChI: 1S/N2/c1-2, amount: [0.75]}
  ignition-type: &ign
    target: OH*
    type: d/dt max
datapoints:
  - temperature:
      - 1213 K
      - {uncertainty-type: absolute, uncertainty: 25 K}
    ignition-delay:
      - 2152 us
      - evaluated-standard-deviation: '0.155261'
        evaluated-standard-deviation-type: relative
        evaluated-standard-deviation-sourcetype: estimated
        evaluated-standard-deviation-method: combined from scatter and reported uncertainty
    pressure:
      - 20 bar
      - evaluated-standard-deviation: 0.5 bar
        evaluated-standard-deviation-type: absolute
    equivalence-ratio: [0.5]
    composition: *comp
    ignition-type: *ign
    time-histories:
      - type: volume
        time: {units: us, column: 0}
        quantity: {units: m3, column: 1}
        values: [[0.0, 1.0], [1.9, 0.9826], [3.9, 0.9729]]
  - temperature: [1100 K]
    ignition-delay:
      - 3000 us
      - {uncertainty-type: absolute, upper-uncertainty: 50 us, lower-uncertainty: 40 us}
    pressure: [20 bar]
    composition: *comp
    ignition-type: *ign
    volume-history:
      time: {units: s, column: 1}
      volume: {units: cm3, column: 0}
      values: [[10.0, 0.0], [9.5, 0.001]]
"""


def load_in_pyked(document, skip_validation=False):
    """Load a ChemKED document with PyKED, as a user of the export does."""
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter("ignore")
        return chemked.ChemKED(dict_input=document, skip_validation=skip_validation)


class DatasetExportYamlTests(TestCase):
    def setUp(self):
        self.dataset = self._ingest(CHEMKED_FILE)

    def _ingest(self, text, rel="ammonia/Shu_2019/Shu_2019_st.yaml"):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / rel).parent.mkdir(parents=True)
        (root / rel).write_text(text)
        call_command(
            "sync_chemked", path=str(root), files=[rel], stdout=io.StringIO(), stderr=io.StringIO()
        )
        return ExperimentDataset.objects.get(chemked_file_path=rel)

    def _export(self):
        response = self.client.get(
            reverse("chemked_database:dataset-export", args=[self.dataset.pk]), {"format": "yaml"}
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        return yaml.safe_load(response.content)

    def _point(self, document, kelvin):
        return next(dp for dp in document["datapoints"] if dp["temperature"][0].startswith(kelvin))

    def test_comments_are_kept(self):
        self.assertEqual(self._export()["comments"], yaml.safe_load(CHEMKED_FILE)["comments"])

    def test_time_histories_are_kept(self):
        histories = self._point(self._export(), "1213")["time-histories"]

        self.assertEqual(histories, [{
            "type": "volume",
            "time": {"units": "us", "column": 0},
            "quantity": {"units": "m3", "column": 1},
            "values": [[0.0, 1.0], [1.9, 0.9826], [3.9, 0.9729]],
        }])

    def test_volume_history_is_kept_with_time_first(self):
        history = self._point(self._export(), "1100")["volume-history"]

        self.assertEqual(history, {
            "time": {"units": "s", "column": 0},
            "volume": {"units": "cm3", "column": 1},
            "values": [[0.0, 10.0], [0.001, 9.5]],
        })

    def test_absolute_uncertainties_keep_their_units(self):
        document = self._export()
        hot, cold = self._point(document, "1213"), self._point(document, "1100")

        self.assertEqual(
            hot["temperature"][1], {"uncertainty-type": "absolute", "uncertainty": "25 K"}
        )
        self.assertEqual(hot["pressure"][1]["evaluated-standard-deviation"], "0.5 bar")
        # Only one text is stored per quantity; the other number takes the value's unit
        self.assertEqual(cold["ignition-delay"][1], {
            "uncertainty-type": "absolute",
            "upper-uncertainty": "50 us",
            "lower-uncertainty": "40.0 us",
        })

    def test_relative_evaluated_standard_deviation_is_unchanged(self):
        block = self._point(self._export(), "1213")["ignition-delay"][1]

        self.assertNotIn("uncertainty-type", block)
        self.assertEqual(block["evaluated-standard-deviation"], 0.155261)
        self.assertEqual(block["evaluated-standard-deviation-type"], "relative")

    def test_uncertainty_without_type_is_left_out(self):
        quantity = IgnitionDelayDatapoint.objects.get(
            datapoint__dataset=self.dataset, datapoint__temperature=1100.0
        ).ignition_delay_quantity
        quantity.uncertainty_type = ""
        quantity.save()

        with self.assertLogs("chemked_database.views", "WARNING"):
            point = self._point(self._export(), "1100")

        self.assertEqual(point["ignition-delay"], ["3000.0 us"])

    def test_empty_doi_is_left_out(self):
        reference = self._export()["reference"]

        self.assertNotIn("doi", reference)
        self.assertEqual(reference["journal"], "Proceedings of the Combustion Institute")

    def test_ignition_type_given_per_datapoint_is_kept(self):
        # As in the methyl-pentanoate RCM files of ChemKED-database
        document = yaml.safe_load(CHEMKED_FILE)
        del document["common-properties"]["ignition-type"]
        for point in document["datapoints"]:
            point["ignition-type"] = {"target": "pressure", "type": "d/dt max"}
        self.dataset = self._ingest(yaml.safe_dump(document), rel="x/rcm.yaml")

        exported = self._export()

        for point in exported["datapoints"]:
            self.assertEqual(point["ignition-type"], {"target": "pressure", "type": "d/dt max"})
        load_in_pyked(exported)

    def test_equivalence_ratio_is_a_value_unit_list(self):
        self.assertEqual(self._point(self._export(), "1213")["equivalence-ratio"], ["0.5"])

    def test_pyked_reads_the_export(self):
        ck = load_in_pyked(self._export(), skip_validation=True)

        points = {
            round(getattr(dp.temperature.magnitude, "nominal_value", dp.temperature.magnitude)): dp
            for dp in ck.datapoints
        }
        hot, cold = points[1213], points[1100]
        self.assertEqual(hot.temperature.magnitude.std_dev, 25)
        self.assertEqual(hot.volume_history.type, "volume")
        self.assertEqual(list(hot.volume_history.time.to("us").magnitude), [0.0, 1.9, 3.9])
        self.assertEqual(cold.ignition_delay.magnitude.std_dev, 50)
        self.assertEqual(list(cold.volume_history.time.to("s").magnitude), [0.0, 0.001])
        self.assertEqual(list(cold.volume_history.volume.to("cm**3").magnitude), [10.0, 9.5])

    def test_pyked_validates_the_export(self):
        load_in_pyked(self._export())
