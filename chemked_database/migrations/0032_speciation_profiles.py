"""Store ChemKED 0.5 speciation measurement datapoints.

Adds the independent variables of a datapoint, links concentration profiles to any datapoint
(not only to a concentration time profile measurement) with their uncertainty block, adds
auxiliary profiles, and lets a CompositionSpecies have no amount, as a profile's species has none.
All changes are additive; no existing row is rewritten.
"""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chemked_database', '0031_store_numeric_values_in_si'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='concentrationprofile',
            options={'ordering': ['id']},
        ),
        migrations.AddField(
            model_name='concentrationprofile',
            name='datapoint',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='concentration_profiles', to='chemked_database.experimentdatapoint'),
        ),
        migrations.AddField(
            model_name='concentrationprofile',
            name='uncertainty',
            field=models.JSONField(blank=True, help_text="The profile's ChemKED uncertainty block as in the file (uncertainty-type, uncertainty, upper/lower-uncertainty, uncertainty-sourcetype, evaluated-standard-deviation and its type, sourcetype and method)", null=True),
        ),
        migrations.AddField(
            model_name='experimentdatapoint',
            name='independent_variables',
            field=models.JSONField(blank=True, default=list, help_text='ChemKED independent-variables in column order: name, units, primary, and the species-name / InChI / SMILES a sweep may name'),
        ),
        migrations.AlterField(
            model_name='compositionspecies',
            name='amount',
            field=models.FloatField(blank=True, help_text='Amount (units depend on composition kind)', null=True, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AlterField(
            model_name='concentrationprofile',
            name='measurement',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='concentration_profiles', to='chemked_database.concentrationtimeprofilemeasurementdatapoint'),
        ),
        migrations.AlterField(
            model_name='concentrationprofile',
            name='time_units',
            field=models.CharField(blank=True, default='s', help_text='Units of the time column; blank when the profile has no time column', max_length=20),
        ),
        migrations.AlterField(
            model_name='concentrationprofile',
            name='values',
            field=models.JSONField(help_text='Rows of [independent values..., amount] or [independent values..., amount, uncertainty]'),
        ),
        migrations.CreateModel(
            name='AuxiliaryProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('profile_type', models.CharField(help_text='Measured property: temperature, pressure, volume or velocity', max_length=30)),
                ('independent_name', models.CharField(help_text='Independent variable: distance or time', max_length=30)),
                ('independent_units', models.CharField(max_length=20)),
                ('quantity_units', models.CharField(max_length=50)),
                ('values', models.JSONField(help_text='Rows of [independent, value] or [independent, value, uncertainty]')),
                ('datapoint', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='auxiliary_profiles', to='chemked_database.experimentdatapoint')),
            ],
            options={
                'db_table': 'chemked_auxiliary_profiles',
                'ordering': ['id'],
            },
        ),
    ]
