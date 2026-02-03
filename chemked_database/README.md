# ChemKED Database App

This app provides Django models for storing ChemKED experimental data (currently focused on ignition-delay datasets) with support for complex structures like common-properties, time histories, and RCM data.

## What’s modeled

- **Datasets** (`ExperimentDataset`) representing one ChemKED YAML file
- **Datapoints** (`ExperimentDatapoint`) representing individual measurements
- **Compositions** (`Composition`) with normalized species rows
- **Ignition delay datapoints** (`IgnitionDelayDatapoint`) for ignition-delay-specific fields
- **Flame speed datapoints** (`FlameSpeedDatapoint`) placeholder for laminar flame speed datasets
- **Species profile datapoints** (`SpeciesProfileDatapoint`) placeholder for species-vs-time datasets
- **Species thermo** (`SpeciesThermo`) stored as a separate model (no JSON field)
- **Common properties** (`CommonProperties`) shared across a dataset
- **RCM data** (`RCMData`) for compression parameters
- **Time histories** (`TimeHistory`) and **Volume histories** (`VolumeHistory`)
- **Composition species** (`CompositionSpecies`) for normalized species queries

## Notes

- Numeric values are stored in SI unless noted in the source YAML.
- Large time-series arrays are stored as JSON for efficiency.
- Composition is available in both JSON form and normalized species rows.
- Use `chemked_database/import_dispatcher.py` to attach the correct experiment-type extension model.
- Quantities can also be stored with units via `ValueWithUnit` to mirror PyKED's value-unit schema.

## Tests

Run the app tests from the project root:

```bash
python3.9 manage.py test chemked_database
```

## Importer

Use the management command to import ChemKED YAML files:

```bash
python manage.py sync_chemked --path /path/to/ChemKED-database
```

Options:
- `--limit N` to import only the first N files
- `--dry-run` to scan without writing to the database

To backfill any missing composition links:

```bash
python manage.py backfill_compositions
```

To infer missing SMILES/atomic composition from existing InChI values:

```bash
python manage.py backfill_species_identifiers
```
