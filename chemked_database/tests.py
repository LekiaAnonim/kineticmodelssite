from django.test import TestCase

from chemked_database.utils.chemistry import rdkit_available

from .import_dispatcher import create_experiment_extension
from .models import (
	Apparatus,
	ApparatusKind,
	CommonProperties,
	Composition,
	CompositionKind,
	CompositionSpecies,
	ExperimentDataset,
	ExperimentDatapoint,
	ExperimentType,
	FlameSpeedDatapoint,
	IgnitionDelayDatapoint,
	IgnitionTarget,
	IgnitionType,
	RCMData,
	SpeciesThermo,
	SpeciesProfileDatapoint,
	TimeHistory,
	TimeHistoryType,
	ValueWithUnit,
	VolumeHistory,
)


class ChemKEDModelTests(TestCase):
	def setUp(self):
		self.apparatus = Apparatus.objects.create(
			kind=ApparatusKind.RCM,
			institution="Test Institute",
			facility="RCM-1",
		)
		self.dataset = ExperimentDataset.objects.create(
			chemked_file_path="rcm_test_001.yaml",
			file_version=0,
			chemked_version="0.4.1",
			apparatus=self.apparatus,
		)
		self.common_properties = CommonProperties.objects.create(
			dataset=self.dataset,
			composition=None,
			ignition_target=IgnitionTarget.PRESSURE,
			ignition_type=IgnitionType.DDT_MAX,
			pressure=101325.0,
		)
		composition = Composition.objects.create(kind=CompositionKind.MOLE_FRACTION)
		CompositionSpecies.objects.create(
			composition=composition,
			species_name="CH4",
			inchi="InChI=1S/CH4/h1H4",
			amount=0.05,
		)
		CompositionSpecies.objects.create(
			composition=composition,
			species_name="O2",
			inchi="InChI=1S/O2/c1-2",
			amount=0.21,
		)
		CompositionSpecies.objects.create(
			composition=composition,
			species_name="N2",
			inchi="InChI=1S/N2/c1-2",
			amount=0.74,
		)
		self.common_properties.composition = composition
		self.common_properties.save()

	def test_common_properties_fallback(self):
		datapoint = ExperimentDatapoint.objects.create(
			dataset=self.dataset,
			temperature=950.0,
			pressure=101325.0,
		)
		IgnitionDelayDatapoint.objects.create(
			datapoint=datapoint,
			ignition_delay=0.003,
		)

		self.assertEqual(datapoint.get_ignition_target(), IgnitionTarget.PRESSURE)
		self.assertEqual(datapoint.get_ignition_type(), IgnitionType.DDT_MAX)
		self.assertEqual(datapoint.get_composition_kind(), CompositionKind.MOLE_FRACTION)
		self.assertEqual(datapoint.get_composition(), self.common_properties.composition)

	def test_datapoint_overrides(self):
		composition = Composition.objects.create(kind=CompositionKind.MASS_FRACTION)
		CompositionSpecies.objects.create(
			composition=composition,
			species_name="H2",
			inchi="InChI=1S/H2/h1H",
			amount=0.1,
		)
		CompositionSpecies.objects.create(
			composition=composition,
			species_name="O2",
			inchi="InChI=1S/O2/c1-2",
			amount=0.3,
		)
		CompositionSpecies.objects.create(
			composition=composition,
			species_name="N2",
			inchi="InChI=1S/N2/c1-2",
			amount=0.6,
		)

		datapoint = ExperimentDatapoint.objects.create(
			dataset=self.dataset,
			temperature=900.0,
			pressure=150000.0,
			composition=composition,
		)
		IgnitionDelayDatapoint.objects.create(
			datapoint=datapoint,
			ignition_delay=0.002,
			ignition_target=IgnitionTarget.OH,
			ignition_type=IgnitionType.MAX,
		)

		self.assertEqual(datapoint.get_ignition_target(), IgnitionTarget.OH)
		self.assertEqual(datapoint.get_ignition_type(), IgnitionType.MAX)
		self.assertEqual(datapoint.get_composition_kind(), CompositionKind.MASS_FRACTION)
		self.assertEqual(datapoint.get_composition(), datapoint.composition)

	def test_time_and_volume_history(self):
		datapoint = ExperimentDatapoint.objects.create(
			dataset=self.dataset,
			temperature=1000.0,
			pressure=202650.0,
		)
		IgnitionDelayDatapoint.objects.create(
			datapoint=datapoint,
			ignition_delay=0.004,
		)

		time_history = TimeHistory.objects.create(
			datapoint=datapoint,
			history_type=TimeHistoryType.VOLUME,
			time_units="s",
			quantity_units="cm^3",
			values=[[0.0, 100.0], [0.01, 50.0], [0.02, 30.0]],
		)
		volume_history = VolumeHistory.objects.create(
			datapoint=datapoint,
			time_units="s",
			volume_units="cm^3",
			values=[[0.0, 100.0], [0.01, 60.0], [0.02, 35.0]],
		)

		self.assertEqual(time_history.num_points, 3)
		self.assertEqual(len(volume_history.values), 3)

	def test_composition_species_optional_fields(self):
		composition = Composition.objects.create(kind=CompositionKind.MOLE_FRACTION)
		datapoint = ExperimentDatapoint.objects.create(
			dataset=self.dataset,
			temperature=1100.0,
			pressure=150000.0,
			composition=composition,
		)
		IgnitionDelayDatapoint.objects.create(
			datapoint=datapoint,
			ignition_delay=0.001,
		)

		species = CompositionSpecies.objects.create(
			composition=composition,
			species_name="CH4",
			inchi="InChI=1S/CH4/h1H4",
			amount=0.05,
			amount_uncertainty=0.002,
			amount_uncertainty_type="relative",
			atomic_composition=[{"element": "C", "amount": 1}, {"element": "H", "amount": 4}],
		)

		self.assertEqual(species.species_name, "CH4")
		self.assertIsNotNone(species.atomic_composition)

		thermo = SpeciesThermo.objects.create(
			species=species,
			t_range_1="300",
			t_range_2="1000",
			t_range_3="3000",
			coeff_1=1.0,
			coeff_2=1.0,
			coeff_3=1.0,
			coeff_4=1.0,
			coeff_5=1.0,
			coeff_6=1.0,
			coeff_7=1.0,
			coeff_8=1.0,
			coeff_9=1.0,
			coeff_10=1.0,
			coeff_11=1.0,
			coeff_12=1.0,
			coeff_13=1.0,
			coeff_14=1.0,
		)

		self.assertEqual(thermo.t_range_1, "300")

	def test_flame_speed_extension(self):
		datapoint = ExperimentDatapoint.objects.create(
			dataset=self.dataset,
			temperature=700.0,
			pressure=101325.0,
		)
		flame = FlameSpeedDatapoint.objects.create(
			datapoint=datapoint,
			laminar_flame_speed=0.35,
			laminar_flame_speed_uncertainty=0.02,
			laminar_flame_speed_uncertainty_type="relative",
			stretch=50.0,
		)

		self.assertEqual(flame.laminar_flame_speed, 0.35)

	def test_species_profile_placeholder(self):
		datapoint = ExperimentDatapoint.objects.create(
			dataset=self.dataset,
			temperature=1200.0,
			pressure=101325.0,
		)
		profile = SpeciesProfileDatapoint.objects.create(
			datapoint=datapoint,
			species_name="CO",
			quantity_units="mole fraction",
			values=[[0.0, 0.01], [0.5, 0.02], [1.0, 0.03]],
		)

		self.assertEqual(profile.species_name, "CO")
		self.assertEqual(len(profile.values), 3)

	def test_dispatcher_creates_extensions(self):
		datapoint = ExperimentDatapoint.objects.create(
			dataset=self.dataset,
			temperature=800.0,
			pressure=101325.0,
		)

		ignition = create_experiment_extension(
			datapoint,
			ExperimentType.IGNITION_DELAY,
			{"ignition_delay": 0.005},
		)
		self.assertIsInstance(ignition, IgnitionDelayDatapoint)

		flame = create_experiment_extension(
			datapoint,
			ExperimentType.FLAME_SPEED,
			{"laminar_flame_speed": 0.4},
		)
		self.assertIsInstance(flame, FlameSpeedDatapoint)

		profile = create_experiment_extension(
			datapoint,
			ExperimentType.SPECIES_PROFILE,
			{
				"species_name": "CO2",
				"quantity_units": "mole fraction",
				"values": [[0.0, 0.0], [1.0, 0.1]],
			},
		)
		self.assertIsInstance(profile, SpeciesProfileDatapoint)

	def test_inchi_inference_helpers(self):
		if not rdkit_available():
			self.skipTest("RDKit not available")
		composition = Composition.objects.create(kind=CompositionKind.MOLE_FRACTION)
		species = CompositionSpecies.objects.create(
			composition=composition,
			species_name="C2H6O",
			inchi="InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
			amount=0.1,
		)
		self.assertTrue(species.smiles)
		self.assertTrue(any(item["element"] == "C" for item in species.atomic_composition or []))

	def test_value_with_unit_links(self):
		temperature_quantity = ValueWithUnit.objects.create(value=1200.0, units="kelvin")
		pressure_quantity = ValueWithUnit.objects.create(value=1.5, units="bar")

		datapoint = ExperimentDatapoint.objects.create(
			dataset=self.dataset,
			temperature=temperature_quantity.value,
			pressure=pressure_quantity.value,
			temperature_quantity=temperature_quantity,
			pressure_quantity=pressure_quantity,
		)

		self.assertEqual(datapoint.temperature_quantity.units, "kelvin")
		self.assertEqual(datapoint.pressure_quantity.units, "bar")
