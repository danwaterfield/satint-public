from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pipeline', '0006_fuel_security_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='sarvesseldetection',
            name='is_military',
            field=models.BooleanField(default=False, help_text='True if detection is predominantly military vessels (excluded from trade-flow scoring)'),
        ),
        migrations.AddField(
            model_name='sarvesseldetection',
            name='notes',
            field=models.TextField(blank=True, default='', help_text='Analyst notes — e.g. context from OSINT, naval tracker cross-reference'),
        ),
    ]
