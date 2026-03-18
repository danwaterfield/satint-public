from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pipeline', '0007_sar_military_flag'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommercialTransit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chokepoint', models.CharField(choices=[('hormuz', 'Strait of Hormuz'), ('bab_al_mandeb', 'Bab al-Mandeb'), ('suez', 'Suez Canal'), ('cape', 'Cape of Good Hope'), ('malacca', 'Malacca Strait')], max_length=20)),
                ('date', models.DateField(help_text='Date of observation (crossings reported for this day)')),
                ('crossings', models.IntegerField(help_text='Total confirmed commercial vessel crossings')),
                ('inbound', models.IntegerField(blank=True, null=True)),
                ('outbound', models.IntegerField(blank=True, null=True)),
                ('seven_day_avg', models.FloatField(blank=True, help_text='7-day rolling average of crossings', null=True)),
                ('baseline_crossings', models.FloatField(default=138, help_text='Pre-war daily average (Hormuz=138, adjustable per chokepoint)')),
                ('pct_change', models.FloatField(blank=True, help_text='Percentage change vs pre-war baseline', null=True)),
                ('source', models.CharField(default='windward', help_text='Data source (windward, uani, bloomberg, manual)', max_length=100)),
                ('notes', models.TextField(blank=True, default='')),
            ],
            options={
                'ordering': ['-date'],
                'unique_together': {('chokepoint', 'date', 'source')},
            },
        ),
        migrations.CreateModel(
            name='WarRiskPremium',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(help_text='Date of rate observation')),
                ('chokepoint', models.CharField(default='hormuz', max_length=20)),
                ('premium_pct_low', models.FloatField(help_text='Low end of quoted war risk premium (% of hull value per transit)')),
                ('premium_pct_high', models.FloatField(help_text='High end of quoted war risk premium (% of hull value per transit)')),
                ('premium_pct_mid', models.FloatField(help_text='Midpoint estimate of premium range')),
                ('baseline_pct', models.FloatField(default=0.035, help_text='Pre-war baseline premium (% hull value) — ~0.02-0.05%')),
                ('pct_change', models.FloatField(blank=True, help_text='Multiple vs baseline (e.g. 10x = 1000%)', null=True)),
                ('vlcc_cost_usd', models.IntegerField(blank=True, help_text='Estimated cost for a $120M VLCC transit at mid rate', null=True)),
                ('source', models.CharField(default='', help_text='Source attribution', max_length=200)),
                ('notes', models.TextField(blank=True, default='')),
            ],
            options={
                'ordering': ['-date'],
                'unique_together': {('chokepoint', 'date')},
            },
        ),
    ]
