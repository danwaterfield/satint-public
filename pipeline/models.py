from django.contrib.gis.db import models


class AreaOfInterest(models.Model):
    CATEGORY_CHOICES = [
        ("city", "City"),
        ("infrastructure", "Critical Infrastructure"),
        ("agriculture", "Agricultural Region"),
        ("chokepoint", "Maritime Chokepoint"),
        ("port", "Port"),
        ("marina", "Marina"),
        ("airport", "Airport"),
        ("approach", "Maritime Approach"),
    ]

    name = models.CharField(max_length=255)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    geometry = models.GeometryField()
    country = models.CharField(max_length=100)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["country", "name"]

    def __str__(self):
        return f"{self.name} ({self.country})"


class NightlightObservation(models.Model):
    aoi = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="nightlight_observations",
    )
    date = models.DateField()
    mean_radiance = models.FloatField(help_text="nW/cm²/sr")
    median_radiance = models.FloatField(help_text="nW/cm²/sr")
    baseline_radiance = models.FloatField(
        null=True, blank=True, help_text="Pre-war average nW/cm²/sr"
    )
    pct_change = models.FloatField(
        null=True, blank=True, help_text="Percentage change vs baseline"
    )
    cloud_fraction = models.FloatField(
        default=0, help_text="Fraction of pixels obscured by cloud (0–1)"
    )
    source = models.CharField(max_length=50, help_text="e.g. VIIRS, Black Marble")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["aoi", "date", "source"]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.aoi.name} — nightlight {self.date} ({self.source})"


class ThermalAnomaly(models.Model):
    CONFIDENCE_CHOICES = [
        ("low", "Low"),
        ("nominal", "Nominal"),
        ("high", "High"),
    ]

    latitude = models.FloatField()
    longitude = models.FloatField()
    point = models.PointField()
    detected_at = models.DateTimeField()
    brightness = models.FloatField(help_text="Brightness temperature in Kelvin")
    frp = models.FloatField(help_text="Fire Radiative Power in MW")
    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES)
    satellite = models.CharField(max_length=20, help_text="e.g. VIIRS, MODIS")
    nearest_infrastructure = models.ForeignKey(
        AreaOfInterest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="nearby_thermal_anomalies",
    )
    distance_to_infrastructure = models.FloatField(
        null=True, blank=True, help_text="Distance to nearest infrastructure AOI in km"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-detected_at"]

    def __str__(self):
        return (
            f"Fire {self.detected_at:%Y-%m-%d %H:%M} "
            f"({self.latitude:.3f}, {self.longitude:.3f}) "
            f"FRP={self.frp} MW [{self.confidence}]"
        )


class VesselTransit(models.Model):
    chokepoint = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="vessel_transits",
    )
    date = models.DateField()
    vessel_type = models.CharField(max_length=50)
    count = models.IntegerField()
    baseline_count = models.FloatField(
        null=True, blank=True, help_text="Pre-war daily average for this vessel type"
    )
    pct_change = models.FloatField(
        null=True, blank=True, help_text="Percentage change vs baseline"
    )

    class Meta:
        unique_together = ["chokepoint", "date", "vessel_type"]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.chokepoint.name} — {self.vessel_type} {self.date} (n={self.count})"


class VegetationIndex(models.Model):
    aoi = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="vegetation_indices",
    )
    date = models.DateField()
    mean_ndvi = models.FloatField(help_text="Mean NDVI across AOI pixels (-1 to 1)")
    baseline_ndvi = models.FloatField(
        null=True, blank=True, help_text="Same-period prior-year NDVI"
    )
    pct_change = models.FloatField(
        null=True, blank=True, help_text="Percentage change vs baseline"
    )
    cloud_fraction = models.FloatField(
        default=0, help_text="Fraction of AOI obscured by cloud (0–1)"
    )

    class Meta:
        unique_together = ["aoi", "date"]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.aoi.name} — NDVI {self.date} ({self.mean_ndvi:.3f})"


class SARVesselDetection(models.Model):
    """
    Vessel count derived from Sentinel-1 SAR imagery at a chokepoint.
    Independent of AIS — detects dark/transponder-off ships.
    """

    # Also used for marina/approach AOIs (NZ migration detection)
    chokepoint = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="sar_vessel_detections",
    )
    date = models.DateField(help_text="SAR scene acquisition date")
    vessel_count = models.IntegerField(help_text="Ships detected in chokepoint bbox")
    baseline_count = models.FloatField(
        null=True, blank=True, help_text="Pre-war daily average vessel count"
    )
    pct_change = models.FloatField(
        null=True, blank=True, help_text="Percentage change vs baseline"
    )
    scene_id = models.CharField(max_length=200, help_text="Sentinel-1 granule ID")
    scene_coverage = models.FloatField(
        default=0, help_text="Fraction of chokepoint bbox covered by valid SAR data"
    )
    mean_scr_db = models.FloatField(
        default=0, help_text="Mean ship-to-clutter ratio of detections (dB)"
    )
    polarization = models.CharField(max_length=5, default="VV")

    class Meta:
        unique_together = ["chokepoint", "date"]
        ordering = ["-date"]

    def __str__(self):
        return (
            f"{self.chokepoint.name} — SAR {self.date} "
            f"({self.vessel_count} ships, {self.pct_change:+.0f}%)"
            if self.pct_change is not None
            else f"{self.chokepoint.name} — SAR {self.date} ({self.vessel_count} ships)"
        )


class CompoundRiskIndicator(models.Model):
    ALERT_LEVELS = [
        ("normal", "Normal"),
        ("elevated", "Elevated"),
        ("high", "High"),
        ("critical", "Critical"),
        ("emergency", "Emergency"),
    ]

    aoi = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="risk_indicators",
    )
    date = models.DateField()
    nightlight_score = models.FloatField(
        default=0, help_text="Normalised nightlight deviation score (0–1)"
    )
    fire_activity_score = models.FloatField(
        default=0, help_text="Normalised fire activity score (0–1)"
    )
    trade_flow_score = models.FloatField(
        default=0, help_text="Normalised trade flow disruption score (0–1)"
    )
    agricultural_score = models.FloatField(
        default=0, help_text="Normalised agricultural stress score (0–1)"
    )
    compound_risk = models.FloatField(
        default=0, help_text="Weighted composite risk score (0–1)"
    )
    alert_level = models.CharField(
        max_length=20, choices=ALERT_LEVELS, default="normal"
    )

    class Meta:
        unique_together = ["aoi", "date"]
        ordering = ["-date"]

    def __str__(self):
        return (
            f"{self.aoi.name} — risk {self.date} "
            f"({self.compound_risk:.2f}, {self.alert_level})"
        )


class OpticalAssetCount(models.Model):
    """
    Sentinel-2 derived bright-object counts on airport aprons or in marina basins.
    Tracks aircraft/vessel count changes relative to a pre-war baseline.
    """

    ASSET_TYPE_CHOICES = [
        ("aircraft", "Aircraft"),
        ("vessel", "Vessel"),
    ]

    aoi = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="optical_asset_counts",
    )
    date = models.DateField()
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPE_CHOICES)
    count = models.IntegerField(help_text="Number of bright objects detected")
    baseline_count = models.FloatField(
        null=True, blank=True, help_text="Pre-war average count for this AOI"
    )
    pct_change = models.FloatField(
        null=True, blank=True, help_text="Percentage change vs baseline"
    )
    cloud_fraction = models.FloatField(
        default=0, help_text="Fraction of AOI obscured by cloud (0–1)"
    )
    scene_id = models.CharField(max_length=200, blank=True, default="")
    source = models.CharField(
        max_length=50, default="Sentinel-2", help_text="e.g. Sentinel-2, SkyFi"
    )

    class Meta:
        unique_together = ["aoi", "date", "asset_type", "source"]
        ordering = ["-date"]

    def __str__(self):
        return (
            f"{self.aoi.name} — {self.asset_type} {self.date} "
            f"(n={self.count}, {self.pct_change:+.0f}%)"
            if self.pct_change is not None
            else f"{self.aoi.name} — {self.asset_type} {self.date} (n={self.count})"
        )


class MigrationPressureIndicator(models.Model):
    """
    Compound score tracking inflow signals at NZ bolt-hole locations.
    Analogous to CompoundRiskIndicator but measures arrival pressure,
    not infrastructure collapse.
    """

    PRESSURE_LEVELS = [
        ("baseline", "Baseline"),
        ("elevated", "Elevated"),
        ("high", "High"),
        ("surge", "Surge"),
    ]

    aoi = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="migration_indicators",
    )
    date = models.DateField()
    marina_score = models.FloatField(
        default=0, help_text="Normalised marina vessel count delta (0–1)"
    )
    airport_score = models.FloatField(
        default=0, help_text="Normalised airport aircraft count delta (0–1)"
    )
    nightlight_score = models.FloatField(
        default=0, help_text="Normalised nightlight activity change (0–1)"
    )
    sar_vessel_score = models.FloatField(
        default=0, help_text="SAR-detected vessel count in approach zones (0–1)"
    )
    gulf_push_score = models.FloatField(
        default=0,
        help_text="Inverse of Gulf compound risk — higher = more push factor (0–1)",
    )
    migration_pressure = models.FloatField(
        default=0, help_text="Weighted composite migration pressure score (0–1)"
    )
    pressure_level = models.CharField(
        max_length=20, choices=PRESSURE_LEVELS, default="baseline"
    )

    class Meta:
        unique_together = ["aoi", "date"]
        ordering = ["-date"]

    def __str__(self):
        return (
            f"{self.aoi.name} — migration {self.date} "
            f"({self.migration_pressure:.2f}, {self.pressure_level})"
        )


class NO2Reading(models.Model):
    """
    Sentinel-5P TROPOMI tropospheric NO2 column density per AOI.
    Power generation proxy — NO2 drops when generators go offline.
    """

    aoi = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="no2_readings",
    )
    date = models.DateField()
    mean_no2 = models.FloatField(help_text="Mean tropospheric NO2 in µmol/m²")
    median_no2 = models.FloatField(
        null=True, blank=True, help_text="Median tropospheric NO2 in µmol/m²"
    )
    baseline_no2 = models.FloatField(
        null=True, blank=True, help_text="Pre-war average NO2 in µmol/m²"
    )
    pct_change = models.FloatField(
        null=True, blank=True, help_text="Percentage change vs baseline"
    )
    pixel_count = models.IntegerField(default=0, help_text="Valid pixels in AOI")
    cloud_fraction = models.FloatField(
        default=0, help_text="Fraction of AOI with low QA (0–1)"
    )

    class Meta:
        unique_together = ["aoi", "date"]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.aoi.name} — NO2 {self.date} ({self.mean_no2:.1f} µmol/m²)"


class InternetOutage(models.Model):
    """
    Internet connectivity score per country from IODA/Cloudflare.
    Independent corroboration of grid collapse detected via nightlights.
    """

    country = models.CharField(max_length=100)
    date = models.DateField()
    ioda_bgp = models.FloatField(
        null=True, blank=True, help_text="IODA BGP visibility level (0–1)"
    )
    ioda_active_probing = models.FloatField(
        null=True, blank=True, help_text="IODA active probing reachability (0–1)"
    )
    cloudflare_traffic = models.FloatField(
        null=True, blank=True, help_text="Cloudflare HTTP traffic index (0–1)"
    )
    overall_connectivity = models.FloatField(
        help_text="Combined connectivity score (0=offline, 1=normal)"
    )
    baseline_connectivity = models.FloatField(
        null=True, blank=True, help_text="Pre-war average connectivity"
    )
    pct_change = models.FloatField(
        null=True, blank=True, help_text="Percentage change vs baseline"
    )

    class Meta:
        unique_together = ["country", "date"]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.country} — internet {self.date} ({self.overall_connectivity:.2f})"


class FlightActivity(models.Model):
    """
    Daily flight count at monitored airports from OpenSky ADS-B.
    Collapse signal for Gulf airports, arrival signal for NZ airports.
    """

    airport_icao = models.CharField(max_length=4, help_text="ICAO airport code")
    airport_name = models.CharField(max_length=200)
    date = models.DateField()
    arrivals = models.IntegerField(default=0)
    departures = models.IntegerField(default=0)
    total_movements = models.IntegerField(default=0)
    baseline_movements = models.FloatField(
        null=True, blank=True, help_text="Pre-war daily average movements"
    )
    pct_change = models.FloatField(
        null=True, blank=True, help_text="Percentage change vs baseline"
    )
    country = models.CharField(max_length=100, default="")

    class Meta:
        unique_together = ["airport_icao", "date"]
        ordering = ["-date"]

    def __str__(self):
        return (
            f"{self.airport_name} ({self.airport_icao}) — {self.date} "
            f"({self.total_movements} movements)"
        )


class SARCoherenceChange(models.Model):
    """
    SAR intensity correlation change detection for infrastructure damage assessment.
    Low correlation between pre/post war scenes indicates structural damage.
    """

    aoi = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="sar_coherence_changes",
    )
    pre_date = models.DateField(help_text="Pre-war scene date")
    post_date = models.DateField(help_text="Post-war scene date")
    mean_correlation = models.FloatField(
        help_text="Mean intensity correlation (0=destroyed, 1=unchanged)"
    )
    low_correlation_fraction = models.FloatField(
        help_text="Fraction of area with correlation < 0.3"
    )
    change_area_km2 = models.FloatField(
        default=0, help_text="Estimated area of significant change in km²"
    )
    pixel_count = models.IntegerField(default=0)
    pre_scene_id = models.CharField(max_length=200, blank=True, default="")
    post_scene_id = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        unique_together = ["aoi", "pre_date", "post_date"]
        ordering = ["-post_date"]

    def __str__(self):
        return (
            f"{self.aoi.name} — coherence {self.pre_date}→{self.post_date} "
            f"(corr={self.mean_correlation:.2f}, change={self.low_correlation_fraction:.0%})"
        )


class GDELTEventCount(models.Model):
    """
    Daily GDELT crisis event counts per country.
    Ground-truth narrative layer corroborating satellite signals.
    """

    country = models.CharField(max_length=100)
    date = models.DateField()
    power_outage = models.IntegerField(default=0)
    water_shortage = models.IntegerField(default=0)
    fuel_shortage = models.IntegerField(default=0)
    food_shortage = models.IntegerField(default=0)
    protest = models.IntegerField(default=0)
    refugee = models.IntegerField(default=0)
    infrastructure_damage = models.IntegerField(default=0)
    economic_impact = models.IntegerField(default=0)
    total_crisis_events = models.IntegerField(default=0)

    class Meta:
        unique_together = ["country", "date"]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.country} — GDELT {self.date} ({self.total_crisis_events} events)"


class ThermalSignature(models.Model):
    """
    Persistent thermal signature tracking for desalination/power plants.
    Detects when expected thermal signatures disappear (plant offline).
    """

    FACILITY_PROFILES = [
        ("flaring", "Flaring (oil/refinery/LNG — fires expected when operating)"),
        ("non_flaring", "Non-flaring (desal/power — fires indicate damage)"),
    ]

    aoi = models.ForeignKey(
        AreaOfInterest,
        on_delete=models.CASCADE,
        related_name="thermal_signatures",
    )
    date = models.DateField()
    facility_profile = models.CharField(
        max_length=20, choices=FACILITY_PROFILES, default="non_flaring",
        help_text="Determines interpretation: flaring=fires normal, non_flaring=fires abnormal",
    )
    signature_present = models.BooleanField(
        help_text="Whether expected thermal signature was detected"
    )
    damage_detected = models.BooleanField(
        default=False,
        help_text="True if fire pattern indicates strike/damage (not normal operations)",
    )
    max_frp = models.FloatField(
        null=True, blank=True, help_text="Maximum FRP within detection radius (MW)"
    )
    fire_count = models.IntegerField(
        default=0, help_text="Number of thermal detections within radius"
    )
    baseline_fire_count = models.FloatField(
        null=True, blank=True, help_text="Pre-war average daily fire count"
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ("operating", "Operating"),
            ("degraded", "Degraded"),
            ("offline", "Offline"),
            ("damaged", "Damaged"),
            ("unknown", "Unknown"),
        ],
        default="unknown",
    )

    class Meta:
        unique_together = ["aoi", "date"]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.aoi.name} — thermal {self.date} ({self.status})"


class FuelPriceObservation(models.Model):
    """
    Weekly MBIE retail fuel prices for New Zealand.
    Tracks petrol (91/95) and diesel price trends.
    """

    FUEL_TYPE_CHOICES = [
        ("91", "Regular Petrol 91"),
        ("95", "Premium Petrol 95"),
        ("diesel", "Diesel"),
    ]

    date = models.DateField()
    fuel_type = models.CharField(max_length=10, choices=FUEL_TYPE_CHOICES)
    retail_price_nzd = models.FloatField(help_text="Retail price NZD/litre")
    import_cost_nzd = models.FloatField(
        null=True, blank=True, help_text="Import cost NZD/litre"
    )
    margin_nzd = models.FloatField(
        null=True, blank=True, help_text="Margin NZD/litre"
    )
    baseline_price = models.FloatField(
        null=True, blank=True, help_text="Pre-war average price NZD/litre"
    )
    pct_change = models.FloatField(
        null=True, blank=True, help_text="Percentage change vs baseline"
    )

    class Meta:
        unique_together = ["date", "fuel_type"]
        ordering = ["-date"]

    def __str__(self):
        return f"Fuel {self.fuel_type} {self.date} — ${self.retail_price_nzd:.3f}/L"


class FuelStockLevel(models.Model):
    """
    MBIE fuel stock snapshots for New Zealand.
    Quarterly manual entry from MBIE reports.
    """

    FUEL_TYPE_CHOICES = [
        ("petrol", "Petrol"),
        ("diesel", "Diesel"),
        ("jet", "Jet Fuel"),
    ]

    STOCK_TYPE_CHOICES = [
        ("onshore", "Onshore"),
        ("on_water", "On Water"),
        ("total", "Total"),
    ]

    date = models.DateField()
    fuel_type = models.CharField(max_length=10, choices=FUEL_TYPE_CHOICES)
    stock_type = models.CharField(max_length=10, choices=STOCK_TYPE_CHOICES)
    days_of_supply = models.FloatField(help_text="Days of supply at current consumption")
    volume_ml = models.FloatField(
        null=True, blank=True, help_text="Volume in megalitres"
    )
    mso_minimum_days = models.FloatField(
        null=True, blank=True, help_text="Minimum Stock Obligation minimum days"
    )

    class Meta:
        unique_together = ["date", "fuel_type", "stock_type"]
        ordering = ["-date"]

    def __str__(self):
        return f"Fuel stock {self.fuel_type}/{self.stock_type} {self.date} — {self.days_of_supply} days"


class NZFuelSecurityIndicator(models.Model):
    """
    Daily compound fuel security score for New Zealand.
    Combines Hormuz disruption, price acceleration, stock depletion,
    supply chain stress, demand signals, and narrative indicators.
    """

    SECURITY_LEVELS = [
        ("normal", "Normal"),
        ("watch", "Watch"),
        ("warning", "Warning"),
        ("critical", "Critical"),
        ("rationing", "Rationing"),
    ]

    date = models.DateField(unique=True)

    # Component scores (0-1, higher = worse)
    hormuz_disruption = models.FloatField(default=0, help_text="Hormuz SAR disruption score (0-1)")
    price_acceleration = models.FloatField(default=0, help_text="Fuel price acceleration score (0-1)")
    stock_depletion = models.FloatField(default=0, help_text="Stock depletion score (0-1)")
    supply_chain = models.FloatField(default=0, help_text="Supply chain disruption score (0-1)")
    demand_signal = models.FloatField(default=0, help_text="Demand signal score (0-1)")
    gdelt_narrative = models.FloatField(default=0, help_text="GDELT fuel_shortage narrative score (0-1)")

    # Composite
    fuel_security_risk = models.FloatField(default=0, help_text="Weighted composite risk (0-1)")
    security_level = models.CharField(max_length=20, choices=SECURITY_LEVELS, default="normal")

    # Projections
    estimated_days_to_mso = models.FloatField(
        null=True, blank=True, help_text="Estimated days until worst fuel type hits MSO minimum"
    )
    estimated_rationing_date = models.DateField(
        null=True, blank=True, help_text="Projected date rationing begins"
    )

    # Per-fuel-type depletion projections (stored as JSON)
    depletion_projections = models.JSONField(
        default=dict, blank=True,
        help_text="Per-fuel-type depletion model outputs"
    )

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"NZ Fuel Security {self.date} — {self.fuel_security_risk:.2f} ({self.security_level})"


class GroundwaterAnomaly(models.Model):
    """
    GRACE-FO groundwater equivalent water thickness anomaly.
    Monthly, coarse resolution — tracks aquifer stress when desalination fails.
    """

    region_name = models.CharField(max_length=100)
    month = models.DateField(help_text="First day of the month")
    mean_ewt_cm = models.FloatField(
        help_text="Mean equivalent water thickness anomaly in cm"
    )
    baseline_ewt_cm = models.FloatField(
        null=True, blank=True, help_text="Long-term average EWT for this month"
    )
    anomaly_cm = models.FloatField(
        null=True, blank=True, help_text="Deviation from baseline in cm"
    )
    min_ewt_cm = models.FloatField(null=True, blank=True)
    max_ewt_cm = models.FloatField(null=True, blank=True)
    pixel_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ["region_name", "month"]
        ordering = ["-month"]

    def __str__(self):
        return f"{self.region_name} — GRACE {self.month} ({self.mean_ewt_cm:+.1f} cm)"
