from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import (
    AreaOfInterest,
    CompoundRiskIndicator,
    FlightActivity,
    FuelPriceObservation,
    FuelStockLevel,
    GDELTEventCount,
    GroundwaterAnomaly,
    InternetOutage,
    MigrationPressureIndicator,
    NightlightObservation,
    NO2Reading,
    NZFuelSecurityIndicator,
    OpticalAssetCount,
    SARCoherenceChange,
    ThermalAnomaly,
    ThermalSignature,
    VesselTransit,
    VegetationIndex,
)


@admin.register(AreaOfInterest)
class AreaOfInterestAdmin(GISModelAdmin):
    list_display = ("name", "category", "country", "created_at")
    list_filter = ("category", "country")
    search_fields = ("name", "country")
    ordering = ("country", "name")


@admin.register(NightlightObservation)
class NightlightObservationAdmin(admin.ModelAdmin):
    list_display = ("aoi", "date", "mean_radiance", "pct_change", "cloud_fraction", "source")
    list_filter = ("source", "aoi__country")
    search_fields = ("aoi__name",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(ThermalAnomaly)
class ThermalAnomalyAdmin(admin.ModelAdmin):
    list_display = (
        "detected_at",
        "satellite",
        "confidence",
        "frp",
        "nearest_infrastructure",
        "distance_to_infrastructure",
        "latitude",
        "longitude",
    )
    list_filter = ("satellite", "confidence")
    search_fields = ("nearest_infrastructure__name",)
    ordering = ("-detected_at",)
    date_hierarchy = "detected_at"


@admin.register(VesselTransit)
class VesselTransitAdmin(admin.ModelAdmin):
    list_display = ("chokepoint", "date", "vessel_type", "count", "baseline_count", "pct_change")
    list_filter = ("vessel_type", "chokepoint")
    search_fields = ("chokepoint__name",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(VegetationIndex)
class VegetationIndexAdmin(admin.ModelAdmin):
    list_display = ("aoi", "date", "mean_ndvi", "baseline_ndvi", "pct_change", "cloud_fraction")
    list_filter = ("aoi__country",)
    search_fields = ("aoi__name",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(CompoundRiskIndicator)
class CompoundRiskIndicatorAdmin(admin.ModelAdmin):
    list_display = (
        "aoi",
        "date",
        "compound_risk",
        "alert_level",
        "nightlight_score",
        "fire_activity_score",
        "trade_flow_score",
        "agricultural_score",
    )
    list_filter = ("alert_level", "aoi__country")
    search_fields = ("aoi__name",)
    ordering = ("-date", "-compound_risk")
    date_hierarchy = "date"


@admin.register(OpticalAssetCount)
class OpticalAssetCountAdmin(admin.ModelAdmin):
    list_display = ("aoi", "date", "asset_type", "count", "baseline_count", "pct_change", "source")
    list_filter = ("asset_type", "source", "aoi__country")
    search_fields = ("aoi__name",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(MigrationPressureIndicator)
class MigrationPressureIndicatorAdmin(admin.ModelAdmin):
    list_display = (
        "aoi",
        "date",
        "migration_pressure",
        "pressure_level",
        "marina_score",
        "airport_score",
        "nightlight_score",
        "sar_vessel_score",
        "gulf_push_score",
    )
    list_filter = ("pressure_level",)
    search_fields = ("aoi__name",)
    ordering = ("-date", "-migration_pressure")
    date_hierarchy = "date"


@admin.register(NO2Reading)
class NO2ReadingAdmin(admin.ModelAdmin):
    list_display = ("aoi", "date", "mean_no2", "baseline_no2", "pct_change", "pixel_count")
    list_filter = ("aoi__country",)
    search_fields = ("aoi__name",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(InternetOutage)
class InternetOutageAdmin(admin.ModelAdmin):
    list_display = ("country", "date", "overall_connectivity", "ioda_bgp", "ioda_active_probing", "pct_change")
    list_filter = ("country",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(FlightActivity)
class FlightActivityAdmin(admin.ModelAdmin):
    list_display = ("airport_name", "airport_icao", "date", "arrivals", "departures", "total_movements", "pct_change")
    list_filter = ("country", "airport_icao")
    search_fields = ("airport_name",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(SARCoherenceChange)
class SARCoherenceChangeAdmin(admin.ModelAdmin):
    list_display = ("aoi", "pre_date", "post_date", "mean_correlation", "low_correlation_fraction", "change_area_km2")
    list_filter = ("aoi__country",)
    search_fields = ("aoi__name",)
    ordering = ("-post_date",)


@admin.register(GDELTEventCount)
class GDELTEventCountAdmin(admin.ModelAdmin):
    list_display = ("country", "date", "total_crisis_events", "power_outage", "water_shortage", "protest", "infrastructure_damage")
    list_filter = ("country",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(ThermalSignature)
class ThermalSignatureAdmin(admin.ModelAdmin):
    list_display = ("aoi", "date", "status", "signature_present", "fire_count", "max_frp")
    list_filter = ("status", "aoi__country")
    search_fields = ("aoi__name",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(FuelPriceObservation)
class FuelPriceObservationAdmin(admin.ModelAdmin):
    list_display = ("date", "fuel_type", "retail_price_nzd", "import_cost_nzd", "margin_nzd", "pct_change")
    list_filter = ("fuel_type",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(FuelStockLevel)
class FuelStockLevelAdmin(admin.ModelAdmin):
    list_display = ("date", "fuel_type", "stock_type", "days_of_supply", "mso_minimum_days")
    list_filter = ("fuel_type", "stock_type")
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(NZFuelSecurityIndicator)
class NZFuelSecurityIndicatorAdmin(admin.ModelAdmin):
    list_display = ("date", "fuel_security_risk", "security_level", "estimated_days_to_mso", "estimated_rationing_date")
    list_filter = ("security_level",)
    ordering = ("-date",)
    date_hierarchy = "date"


@admin.register(GroundwaterAnomaly)
class GroundwaterAnomalyAdmin(admin.ModelAdmin):
    list_display = ("region_name", "month", "mean_ewt_cm", "baseline_ewt_cm", "anomaly_cm")
    list_filter = ("region_name",)
    ordering = ("-month",)
