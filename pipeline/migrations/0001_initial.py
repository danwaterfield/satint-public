"""
Initial migration for the pipeline app.
Creates all models: AreaOfInterest, NightlightObservation, ThermalAnomaly,
VesselTransit, VegetationIndex, CompoundRiskIndicator.

Generated to match the unique_together Meta declarations in models.py so that
`manage.py makemigrations --check` reports no pending changes.
"""

import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        # ------------------------------------------------------------------
        # AreaOfInterest
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="AreaOfInterest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("city", "City"),
                            ("infrastructure", "Critical Infrastructure"),
                            ("agriculture", "Agricultural Region"),
                            ("chokepoint", "Maritime Chokepoint"),
                            ("port", "Port"),
                        ],
                        max_length=50,
                    ),
                ),
                ("geometry", django.contrib.gis.db.models.fields.GeometryField(srid=4326)),
                ("country", models.CharField(max_length=100)),
                ("metadata", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["country", "name"],
            },
        ),
        # ------------------------------------------------------------------
        # NightlightObservation
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="NightlightObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "aoi",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="nightlight_observations",
                        to="pipeline.areaofinterest",
                    ),
                ),
                ("date", models.DateField()),
                ("mean_radiance", models.FloatField(help_text="nW/cm\u00b2/sr")),
                ("median_radiance", models.FloatField(help_text="nW/cm\u00b2/sr")),
                (
                    "baseline_radiance",
                    models.FloatField(
                        blank=True,
                        help_text="Pre-war average nW/cm\u00b2/sr",
                        null=True,
                    ),
                ),
                (
                    "pct_change",
                    models.FloatField(
                        blank=True,
                        help_text="Percentage change vs baseline",
                        null=True,
                    ),
                ),
                (
                    "cloud_fraction",
                    models.FloatField(
                        default=0,
                        help_text="Fraction of pixels obscured by cloud (0\u20131)",
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        help_text="e.g. VIIRS, Black Marble", max_length=50
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-date"],
                "unique_together": {("aoi", "date", "source")},
            },
        ),
        # ------------------------------------------------------------------
        # ThermalAnomaly
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="ThermalAnomaly",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("latitude", models.FloatField()),
                ("longitude", models.FloatField()),
                ("point", django.contrib.gis.db.models.fields.PointField(srid=4326)),
                ("detected_at", models.DateTimeField()),
                (
                    "brightness",
                    models.FloatField(help_text="Brightness temperature in Kelvin"),
                ),
                (
                    "frp",
                    models.FloatField(help_text="Fire Radiative Power in MW"),
                ),
                (
                    "confidence",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("nominal", "Nominal"),
                            ("high", "High"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "satellite",
                    models.CharField(
                        help_text="e.g. VIIRS, MODIS", max_length=20
                    ),
                ),
                (
                    "nearest_infrastructure",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="nearby_thermal_anomalies",
                        to="pipeline.areaofinterest",
                    ),
                ),
                (
                    "distance_to_infrastructure",
                    models.FloatField(
                        blank=True,
                        help_text="Distance to nearest infrastructure AOI in km",
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-detected_at"],
            },
        ),
        # ------------------------------------------------------------------
        # VesselTransit
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="VesselTransit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "chokepoint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vessel_transits",
                        to="pipeline.areaofinterest",
                    ),
                ),
                ("date", models.DateField()),
                ("vessel_type", models.CharField(max_length=50)),
                ("count", models.IntegerField()),
                (
                    "baseline_count",
                    models.FloatField(
                        blank=True,
                        help_text="Pre-war daily average for this vessel type",
                        null=True,
                    ),
                ),
                (
                    "pct_change",
                    models.FloatField(
                        blank=True,
                        help_text="Percentage change vs baseline",
                        null=True,
                    ),
                ),
            ],
            options={
                "ordering": ["-date"],
                "unique_together": {("chokepoint", "date", "vessel_type")},
            },
        ),
        # ------------------------------------------------------------------
        # VegetationIndex
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="VegetationIndex",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "aoi",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vegetation_indices",
                        to="pipeline.areaofinterest",
                    ),
                ),
                ("date", models.DateField()),
                (
                    "mean_ndvi",
                    models.FloatField(
                        help_text="Mean NDVI across AOI pixels (-1 to 1)"
                    ),
                ),
                (
                    "baseline_ndvi",
                    models.FloatField(
                        blank=True,
                        help_text="Same-period prior-year NDVI",
                        null=True,
                    ),
                ),
                (
                    "pct_change",
                    models.FloatField(
                        blank=True,
                        help_text="Percentage change vs baseline",
                        null=True,
                    ),
                ),
                (
                    "cloud_fraction",
                    models.FloatField(
                        default=0,
                        help_text="Fraction of AOI obscured by cloud (0\u20131)",
                    ),
                ),
            ],
            options={
                "ordering": ["-date"],
                "unique_together": {("aoi", "date")},
            },
        ),
        # ------------------------------------------------------------------
        # CompoundRiskIndicator
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="CompoundRiskIndicator",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "aoi",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="risk_indicators",
                        to="pipeline.areaofinterest",
                    ),
                ),
                ("date", models.DateField()),
                (
                    "nightlight_score",
                    models.FloatField(
                        default=0,
                        help_text="Normalised nightlight deviation score (0\u20131)",
                    ),
                ),
                (
                    "fire_activity_score",
                    models.FloatField(
                        default=0,
                        help_text="Normalised fire activity score (0\u20131)",
                    ),
                ),
                (
                    "trade_flow_score",
                    models.FloatField(
                        default=0,
                        help_text="Normalised trade flow disruption score (0\u20131)",
                    ),
                ),
                (
                    "agricultural_score",
                    models.FloatField(
                        default=0,
                        help_text="Normalised agricultural stress score (0\u20131)",
                    ),
                ),
                (
                    "compound_risk",
                    models.FloatField(
                        default=0,
                        help_text="Weighted composite risk score (0\u20131)",
                    ),
                ),
                (
                    "alert_level",
                    models.CharField(
                        choices=[
                            ("normal", "Normal"),
                            ("elevated", "Elevated"),
                            ("high", "High"),
                            ("critical", "Critical"),
                            ("emergency", "Emergency"),
                        ],
                        default="normal",
                        max_length=20,
                    ),
                ),
            ],
            options={
                "ordering": ["-date"],
                "unique_together": {("aoi", "date")},
            },
        ),
    ]
