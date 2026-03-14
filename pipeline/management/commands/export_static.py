"""
Export pipeline data to static JSON files for GitHub Pages hosting.

Usage:
    python manage.py export_static [--output-dir docs/data]

Generates:
    docs/data/nightlights.json   — per-city time series (DNB + VNP46A2)
    docs/data/fires.json         — daily fire counts/FRP by country
    docs/data/fires_infra.json   — high-FRP fires near infrastructure
    docs/data/sar.json           — SAR vessel detections at chokepoints
    docs/data/meta.json          — generation timestamp, data ranges
"""

import json
import os
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Max, Min, Sum

from pipeline.models import (
    AreaOfInterest,
    CompoundRiskIndicator,
    FlightActivity,
    FuelPriceObservation,
    FuelStockLevel,
    GDELTEventCount,
    InternetOutage,
    MigrationPressureIndicator,
    NightlightObservation,
    NZFuelSecurityIndicator,
    OpticalAssetCount,
    SARVesselDetection,
    ThermalAnomaly,
    ThermalSignature,
)


class Command(BaseCommand):
    help = "Export live pipeline data to static JSON for GitHub Pages"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default="docs/data",
            help="Directory to write JSON files (default: docs/data)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=45,
            help="Days of history to export (default: 45)",
        )

    def handle(self, *args, **options):
        out_dir = options["output_dir"]
        os.makedirs(out_dir, exist_ok=True)
        cutoff = date.today() - timedelta(days=options["days"])

        self.stdout.write(f"Exporting to {out_dir}/...")

        self._export_meta(out_dir)
        self._export_nightlights(out_dir, cutoff)
        self._export_fires(out_dir, cutoff)
        self._export_fires_geojson(out_dir)
        self._export_fires_infra(out_dir, cutoff)
        self._export_sar(out_dir)
        self._export_compound_risk(out_dir)
        self._export_internet(out_dir)
        self._export_thermal_signatures(out_dir)
        self._export_nz(out_dir)
        self._export_flights(out_dir)
        self._export_fuel_security(out_dir)

        self.stdout.write(self.style.SUCCESS(f"Export complete → {out_dir}/"))

    # ------------------------------------------------------------------

    def _write(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"), default=str)
        self.stdout.write(f"  wrote {path}")

    def _export_meta(self, out_dir):
        import datetime

        GULF_COUNTRIES = ["Iran", "UAE", "Saudi Arabia", "Qatar", "Bahrain", "Kuwait", "Iraq"]
        today = date.today()

        # ---- freshness per source ----
        source_queries = {
            "nightlights": NightlightObservation.objects.aggregate(latest=Max("date"))["latest"],
            "fires": (
                ThermalAnomaly.objects.aggregate(latest=Max("detected_at"))["latest"]
            ),
            "internet": InternetOutage.objects.aggregate(latest=Max("date"))["latest"],
            "flights": FlightActivity.objects.aggregate(latest=Max("date"))["latest"],
            "sar": SARVesselDetection.objects.aggregate(latest=Max("date"))["latest"],
            "thermal": ThermalSignature.objects.aggregate(latest=Max("date"))["latest"],
        }

        freshness = {}
        stale_sources = []
        for src, latest in source_queries.items():
            if latest is None:
                freshness[src] = {"latest": None, "days_ago": None}
                stale_sources.append(src)
                continue
            # fires returns datetime, others return date
            latest_date = latest.date() if hasattr(latest, "date") and callable(latest.date) else latest
            days_ago = (today - latest_date).days
            freshness[src] = {"latest": str(latest_date), "days_ago": days_ago}
            if days_ago > 3:
                stale_sources.append(src)

        stale_warning = None
        if stale_sources:
            parts = []
            for s in stale_sources:
                f = freshness[s]
                if f["latest"]:
                    parts.append(f"{s.title()} data is {f['days_ago']} days old (latest: {f['latest']})")
            if parts:
                stale_warning = ". ".join(parts) + ". NASA/satellite processing lag."

        # ---- situation brief ----
        brief_parts = []

        # Worst nightlight city (Gulf, latest date, pct_change < -20)
        latest_nl_date = freshness["nightlights"]["latest"]
        if latest_nl_date:
            worst_nl = (
                NightlightObservation.objects.filter(
                    date=latest_nl_date,
                    aoi__country__in=GULF_COUNTRIES,
                    pct_change__lt=-20,
                )
                .select_related("aoi")
                .order_by("pct_change")
                .first()
            )
            if worst_nl:
                brief_parts.append(
                    f"{worst_nl.aoi.name} nighttime radiance has collapsed "
                    f"{abs(worst_nl.pct_change):.0f}% from pre-war baseline, "
                    f"consistent with widespread power grid failure"
                )

        # Hormuz vessel traffic
        latest_sar = (
            SARVesselDetection.objects.filter(
                chokepoint__name__icontains="Hormuz",
                pct_change__lt=-20,
            )
            .order_by("-date")
            .first()
        )
        if latest_sar:
            remaining = 100 + latest_sar.pct_change
            brief_parts.append(
                f"Strait of Hormuz vessel traffic has fallen to "
                f"{remaining:.0f}% of normal"
            )

        # Damaged facilities
        damaged = sorted(set(
            ThermalSignature.objects.filter(damage_detected=True).values_list(
                "aoi__name", flat=True
            )
        ))
        if damaged:
            if len(damaged) == 1:
                brief_parts.append(f"{damaged[0]} sustained strike damage")
            else:
                brief_parts.append(
                    f"{len(damaged)} facilities sustained strike damage, "
                    f"including {damaged[0]}"
                )

        # Internet degradation
        latest_inet_date = freshness["internet"]["latest"]
        if latest_inet_date:
            degraded = (
                InternetOutage.objects.filter(
                    date=latest_inet_date,
                    country__in=GULF_COUNTRIES,
                    pct_change__lt=-10,
                )
                .order_by("pct_change")
            )
            if degraded.exists():
                worst = degraded.first()
                brief_parts.append(
                    f"{worst.country} internet connectivity remains degraded "
                    f"at {worst.pct_change:+.1f}%"
                )

        situation_brief = ". ".join(brief_parts) + "." if brief_parts else None

        self._write(
            os.path.join(out_dir, "meta.json"),
            {
                "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                "latest_nightlight": freshness["nightlights"]["latest"],
                "latest_fire": freshness["fires"]["latest"],
                "war_start": "2026-02-28",
                "baseline_start": "2026-01-15",
                "baseline_end": "2026-02-27",
                "freshness": freshness,
                "stale_warning": stale_warning,
                "situation_brief": situation_brief,
            },
        )

    def _export_nightlights(self, out_dir, cutoff):
        """Per-city nightlight time series. Prefer VNP46A2 over DNB per date."""
        obs = (
            NightlightObservation.objects.filter(date__gte=cutoff)
            .exclude(pct_change=None)
            .select_related("aoi")
            .order_by("aoi__name", "date", "source")
            .values("aoi__name", "date", "mean_radiance", "pct_change", "cloud_fraction", "source")
        )

        # Build per-city series, deduplicating dates (prefer VNP46A2)
        from collections import defaultdict
        cities = defaultdict(dict)  # city → {date_str: record}
        for o in obs:
            city = o["aoi__name"]
            d = str(o["date"])
            existing = cities[city].get(d)
            # Prefer VNP46A2 over DNB; prefer any over nothing
            if existing is None or (o["source"] == "VNP46A2" and existing["source"] != "VNP46A2"):
                cities[city][d] = {
                    "date": d,
                    "mean_radiance": round(o["mean_radiance"], 3) if o["mean_radiance"] is not None else None,
                    "pct_change": round(o["pct_change"], 1) if o["pct_change"] is not None else None,
                    "cloud_fraction": round(o["cloud_fraction"], 2) if o["cloud_fraction"] is not None else None,
                    "source": o["source"],
                }

        result = {}
        for city, date_map in sorted(cities.items()):
            result[city] = sorted(date_map.values(), key=lambda x: x["date"])

        self._write(os.path.join(out_dir, "nightlights.json"), result)

    def _export_fires(self, out_dir, cutoff):
        """Daily fire counts and FRP by broad geographic region."""
        regions = {
            "Iran": (26.0, 44.0, 38.0, 63.0),
            "Saudi Arabia": (18.0, 36.5, 32.0, 55.7),
            "UAE / Qatar / Bahrain": (23.0, 51.0, 26.5, 57.0),
            "Iraq": (29.0, 43.0, 37.5, 49.0),
            "Kuwait": (28.5, 46.5, 30.2, 48.5),
        }

        # All dates in range
        all_dates = sorted(set(
            str(d) for d in
            ThermalAnomaly.objects.filter(detected_at__date__gte=cutoff)
            .values_list("detected_at__date", flat=True)
            .distinct()
        ))

        result = {"dates": all_dates, "regions": {}}
        for region_name, (lat_min, lon_min, lat_max, lon_max) in regions.items():
            counts = []
            total_frp = []
            for d in all_dates:
                agg = ThermalAnomaly.objects.filter(
                    detected_at__date=d,
                    latitude__gte=lat_min, latitude__lte=lat_max,
                    longitude__gte=lon_min, longitude__lte=lon_max,
                ).aggregate(count=Count("id"), frp=Sum("frp"))
                counts.append(agg["count"] or 0)
                total_frp.append(round(agg["frp"] or 0, 1))
            result["regions"][region_name] = {"counts": counts, "total_frp": total_frp}

        result["daily_by_country"] = {
            name: {"dates": all_dates, "counts": result["regions"][name]["counts"]}
            for name in result["regions"]
        }

        self._write(os.path.join(out_dir, "fires.json"), result)

    def _export_fires_geojson(self, out_dir):
        """Recent 48h fires as GeoJSON for the Leaflet map."""
        from datetime import datetime, timezone as tz
        cutoff_dt = datetime.now(tz=tz.utc) - timedelta(hours=48)
        fires = (
            ThermalAnomaly.objects.filter(detected_at__gte=cutoff_dt)
            .select_related("nearest_infrastructure")
            .values(
                "latitude", "longitude", "frp", "confidence",
                "satellite", "detected_at",
                "nearest_infrastructure__name", "distance_to_infrastructure",
            )
        )
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [f["longitude"], f["latitude"]]},
                "properties": {
                    "frp": round(f["frp"], 1) if f["frp"] else 0,
                    "confidence": f["confidence"],
                    "satellite": f["satellite"],
                    "detected_at": f["detected_at"].isoformat() if f["detected_at"] else None,
                    "nearest_infrastructure": f["nearest_infrastructure__name"],
                    "distance_km": round(f["distance_to_infrastructure"], 1) if f["distance_to_infrastructure"] else None,
                },
            }
            for f in fires
        ]
        self._write(
            os.path.join(out_dir, "fires_geojson.json"),
            {"type": "FeatureCollection", "features": features},
        )

    def _export_fires_infra(self, out_dir, cutoff):
        """High-FRP fires within 30km of monitored infrastructure."""
        fires = (
            ThermalAnomaly.objects.filter(
                detected_at__date__gte=cutoff,
                nearest_infrastructure__isnull=False,
                distance_to_infrastructure__lte=30,
                frp__gte=30,
            )
            .select_related("nearest_infrastructure")
            .order_by("-frp")
            .values(
                "latitude", "longitude", "frp", "confidence",
                "detected_at", "nearest_infrastructure__name",
                "distance_to_infrastructure",
            )[:200]
        )

        result = [
            {
                "lat": round(f["latitude"], 4),
                "lon": round(f["longitude"], 4),
                "frp": round(f["frp"], 1),
                "confidence": f["confidence"],
                "detected_at": f["detected_at"].isoformat(),
                "infrastructure": f["nearest_infrastructure__name"],
                "distance_km": round(f["distance_to_infrastructure"], 1),
            }
            for f in fires
        ]
        self._write(os.path.join(out_dir, "fires_infra.json"), result)

    def _compute_supplementary_scores(self, aoi, for_date):
        """Compute 5 supplementary scores by joining related tables."""
        country = aoi.country
        city_first_word = aoi.name.split()[0]

        # internet_score: from InternetOutage by country+date
        internet_score = 0.0
        try:
            inet = InternetOutage.objects.get(country=country, date=for_date)
            if inet.pct_change is not None and inet.pct_change < 0:
                internet_score = min(1.0, max(0.0, abs(inet.pct_change) / 100))
        except InternetOutage.DoesNotExist:
            internet_score = None

        # flight_score: from FlightActivity matching city name
        flight_score = 0.0
        flight = (
            FlightActivity.objects.filter(
                airport_name__icontains=city_first_word,
                date=for_date,
            ).first()
        )
        if flight is None:
            flight_score = None
        elif (
            flight.baseline_movements
            and flight.baseline_movements > 0
            and flight.pct_change is not None
            and flight.pct_change < 0
        ):
            flight_score = min(1.0, max(0.0, abs(flight.pct_change / 100)))

        # gdelt_score: from GDELTEventCount by country+date
        gdelt_score = 0.0
        try:
            gdelt = GDELTEventCount.objects.get(country=country, date=for_date)
            gdelt_score = min(1.0, gdelt.total_crisis_events / 50)
        except GDELTEventCount.DoesNotExist:
            gdelt_score = None

        # thermal_score: from ThermalSignature by country+date
        thermal_score = 0.0
        thermals = ThermalSignature.objects.filter(
            aoi__country=country, date=for_date,
        )
        total_count = thermals.count()
        if total_count > 0:
            damaged_count = thermals.filter(damage_detected=True).count()
            thermal_score = damaged_count / total_count
        else:
            thermal_score = None

        # no2_score: not yet backfilled
        no2_score = None

        return {
            "no2_score": no2_score,
            "internet_score": round(internet_score, 4) if internet_score is not None else None,
            "flight_score": round(flight_score, 4) if flight_score is not None else None,
            "gdelt_score": round(gdelt_score, 4) if gdelt_score is not None else None,
            "thermal_score": round(thermal_score, 4) if thermal_score is not None else None,
        }

    def _export_compound_risk(self, out_dir):
        """Latest compound risk indicators with supplementary scores."""
        from datetime import datetime
        today = date.today()
        indicators = (
            CompoundRiskIndicator.objects.filter(date=today)
            .select_related("aoi")
            .order_by("-compound_risk")
        )
        # Fallback: most recent date if none today
        if not indicators.exists():
            latest = CompoundRiskIndicator.objects.aggregate(d=Max("date"))["d"]
            if latest:
                indicators = (
                    CompoundRiskIndicator.objects.filter(date=latest)
                    .select_related("aoi")
                    .order_by("-compound_risk")
                )

        indicator_list = []
        for i in indicators:
            entry = {
                "aoi_name": i.aoi.name,
                "country": i.aoi.country,
                "compound_risk": round(i.compound_risk, 4),
                "alert_level": i.alert_level,
                "nightlight_score": round(i.nightlight_score, 4),
                "fire_activity_score": round(i.fire_activity_score, 4),
                "trade_flow_score": round(i.trade_flow_score, 4),
            }
            entry.update(self._compute_supplementary_scores(i.aoi, i.date))
            indicator_list.append(entry)

        result = {
            "as_of": str(indicators[0].date) if indicators else None,
            "indicators": indicator_list,
        }
        self._write(os.path.join(out_dir, "compound_risk.json"), result)

    def _export_sar(self, out_dir):
        """SAR vessel detections at chokepoints."""
        detections = (
            SARVesselDetection.objects.all()
            .select_related("chokepoint")
            .order_by("chokepoint__name", "date")
            .values("chokepoint__name", "date", "vessel_count",
                    "baseline_count", "pct_change", "scene_coverage", "mean_scr_db")
        )

        result = {}
        for d in detections:
            name = d["chokepoint__name"]
            if name not in result:
                result[name] = []
            cov = d["scene_coverage"]
            normalised = (
                round(d["vessel_count"] / cov, 1)
                if cov and cov > 0 else None
            )
            result[name].append({
                "date": str(d["date"]),
                "vessel_count": d["vessel_count"],
                "normalised_count": normalised,
                "baseline_count": d["baseline_count"],
                "pct_change": round(d["pct_change"], 1) if d["pct_change"] is not None else None,
                "scene_coverage": round(d["scene_coverage"], 2),
                "mean_scr_db": round(d["mean_scr_db"], 1),
            })

        self._write(os.path.join(out_dir, "sar.json"), result)

    def _export_internet(self, out_dir):
        """Internet connectivity time series per country."""
        observations = (
            InternetOutage.objects.all()
            .order_by("country", "date")
            .values("country", "date", "ioda_bgp", "ioda_active_probing",
                    "overall_connectivity", "baseline_connectivity", "pct_change")
        )

        from collections import defaultdict
        countries = defaultdict(list)
        for o in observations:
            countries[o["country"]].append({
                "date": str(o["date"]),
                "connectivity": round(o["overall_connectivity"], 3) if o["overall_connectivity"] is not None else None,
                "min_connectivity": round(o["ioda_active_probing"], 3) if o["ioda_active_probing"] is not None else None,
                "baseline": round(o["baseline_connectivity"], 3) if o["baseline_connectivity"] is not None else None,
                "pct_change": round(o["pct_change"], 1) if o["pct_change"] is not None else None,
            })

        self._write(os.path.join(out_dir, "internet.json"), dict(sorted(countries.items())))

    def _export_thermal_signatures(self, out_dir):
        """Infrastructure thermal signature status."""
        sigs = (
            ThermalSignature.objects.all()
            .select_related("aoi")
            .order_by("aoi__name", "date")
            .values("aoi__name", "aoi__country", "date", "facility_profile",
                    "signature_present", "damage_detected", "max_frp",
                    "fire_count", "baseline_fire_count", "status")
        )

        from collections import defaultdict
        facilities = defaultdict(list)
        for s in sigs:
            status = s["status"]
            data_caveat = None
            if (
                s["facility_profile"] == "flaring"
                and s["status"] == "offline"
                and (s["fire_count"] is None or s["fire_count"] == 0)
            ):
                status = "no_data"
                data_caveat = "No FIRMS detections \u2014 status unknown"

            facilities[s["aoi__name"]].append({
                "date": str(s["date"]),
                "country": s["aoi__country"],
                "profile": s["facility_profile"],
                "status": status,
                "damage": s["damage_detected"],
                "fire_count": s["fire_count"],
                "max_frp": round(s["max_frp"], 1) if s["max_frp"] is not None else None,
                "baseline_fires": round(s["baseline_fire_count"], 1) if s["baseline_fire_count"] is not None else None,
                "data_caveat": data_caveat,
            })

        self._write(os.path.join(out_dir, "thermal_signatures.json"), dict(sorted(facilities.items())))

    def _export_nz(self, out_dir):
        """NZ migration signal detection data — asset counts, SAR, migration pressure, nightlights."""
        from collections import defaultdict

        # Optical asset counts (marina vessels + airport aircraft)
        asset_counts = (
            OpticalAssetCount.objects.filter(aoi__country="New Zealand")
            .select_related("aoi")
            .order_by("aoi__name", "date")
            .values("aoi__name", "aoi__category", "date", "asset_type",
                    "count", "baseline_count", "pct_change", "cloud_fraction")
        )

        assets = defaultdict(list)
        for a in asset_counts:
            key = a["aoi__name"]
            assets[key].append({
                "date": str(a["date"]),
                "category": a["aoi__category"],
                "asset_type": a["asset_type"],
                "count": a["count"],
                "baseline": round(a["baseline_count"], 1) if a["baseline_count"] is not None else None,
                "pct_change": round(a["pct_change"], 1) if a["pct_change"] is not None else None,
                "cloud_fraction": round(a["cloud_fraction"], 2) if a["cloud_fraction"] is not None else None,
            })

        # NZ SAR vessel detections
        nz_sar = (
            SARVesselDetection.objects.filter(chokepoint__country="New Zealand")
            .select_related("chokepoint")
            .order_by("chokepoint__name", "date")
            .values("chokepoint__name", "date", "vessel_count",
                    "baseline_count", "pct_change", "scene_coverage")
        )

        sar = defaultdict(list)
        for s in nz_sar:
            sar[s["chokepoint__name"]].append({
                "date": str(s["date"]),
                "vessel_count": s["vessel_count"],
                "baseline": round(s["baseline_count"], 1) if s["baseline_count"] is not None else None,
                "pct_change": round(s["pct_change"], 1) if s["pct_change"] is not None else None,
                "coverage": round(s["scene_coverage"], 2) if s["scene_coverage"] is not None else None,
            })

        # Migration pressure indicators
        pressure = (
            MigrationPressureIndicator.objects.all()
            .select_related("aoi")
            .order_by("aoi__name", "date")
            .values("aoi__name", "date", "migration_pressure", "pressure_level",
                    "marina_score", "airport_score", "nightlight_score",
                    "sar_vessel_score", "gulf_push_score")
        )

        migration = defaultdict(list)
        for p in pressure:
            migration[p["aoi__name"]].append({
                "date": str(p["date"]),
                "pressure": round(p["migration_pressure"], 4),
                "level": p["pressure_level"],
                "marina": round(p["marina_score"], 3),
                "airport": round(p["airport_score"], 3),
                "nightlight": round(p["nightlight_score"], 3),
                "sar": round(p["sar_vessel_score"], 3),
                "gulf_push": round(p["gulf_push_score"], 3),
            })

        # NZ nightlights
        nz_nl = (
            NightlightObservation.objects.filter(aoi__country="New Zealand")
            .select_related("aoi")
            .order_by("aoi__name", "date")
            .values("aoi__name", "date", "mean_radiance", "pct_change", "source")
        )

        nightlights = defaultdict(list)
        for n in nz_nl:
            nightlights[n["aoi__name"]].append({
                "date": str(n["date"]),
                "radiance": round(n["mean_radiance"], 3) if n["mean_radiance"] is not None else None,
                "pct_change": round(n["pct_change"], 1) if n["pct_change"] is not None else None,
                "source": n["source"],
            })

        result = {
            "asset_counts": dict(sorted(assets.items())),
            "sar": dict(sorted(sar.items())),
            "migration_pressure": dict(sorted(migration.items())),
            "nightlights": dict(sorted(nightlights.items())),
        }

        self._write(os.path.join(out_dir, "nz.json"), result)

    def _export_flights(self, out_dir):
        """Airport flight activity time series."""
        from collections import defaultdict

        flights = (
            FlightActivity.objects.all()
            .order_by("airport_name", "date")
            .values("airport_name", "airport_icao", "date",
                    "arrivals", "departures", "total_movements", "country")
        )

        airports = defaultdict(list)
        for f in flights:
            airports[f["airport_name"]].append({
                "date": str(f["date"]),
                "icao": f["airport_icao"],
                "country": f["country"],
                "arrivals": f["arrivals"],
                "departures": f["departures"],
                "total": f["total_movements"],
            })

        self._write(os.path.join(out_dir, "flights.json"), dict(sorted(airports.items())))

    def _export_fuel_security(self, out_dir):
        """NZ fuel security indicator, stock levels, and price trends."""
        from collections import defaultdict

        # Latest fuel security indicator
        latest_indicator = NZFuelSecurityIndicator.objects.order_by("-date").first()

        indicator_data = None
        if latest_indicator:
            indicator_data = {
                "date": str(latest_indicator.date),
                "fuel_security_risk": round(latest_indicator.fuel_security_risk, 4),
                "security_level": latest_indicator.security_level,
                "estimated_days_to_mso": (
                    round(latest_indicator.estimated_days_to_mso, 1)
                    if latest_indicator.estimated_days_to_mso is not None else None
                ),
                "estimated_rationing_date": (
                    str(latest_indicator.estimated_rationing_date)
                    if latest_indicator.estimated_rationing_date else None
                ),
                "components": {
                    "hormuz_disruption": round(latest_indicator.hormuz_disruption, 4),
                    "price_acceleration": round(latest_indicator.price_acceleration, 4),
                    "stock_depletion": round(latest_indicator.stock_depletion, 4),
                    "supply_chain": round(latest_indicator.supply_chain, 4),
                    "demand_signal": round(latest_indicator.demand_signal, 4),
                    "gdelt_narrative": round(latest_indicator.gdelt_narrative, 4),
                },
                "depletion_projections": latest_indicator.depletion_projections,
            }

        # Indicator time series (last 30 days)
        indicator_series = list(
            NZFuelSecurityIndicator.objects.order_by("date")
            .values("date", "fuel_security_risk", "security_level",
                    "hormuz_disruption", "stock_depletion", "price_acceleration",
                    "estimated_days_to_mso")
        )
        series_data = [
            {
                "date": str(i["date"]),
                "risk": round(i["fuel_security_risk"], 4),
                "level": i["security_level"],
                "hormuz": round(i["hormuz_disruption"], 4),
                "stock": round(i["stock_depletion"], 4),
                "price": round(i["price_acceleration"], 4),
                "days_to_mso": round(i["estimated_days_to_mso"], 1) if i["estimated_days_to_mso"] else None,
            }
            for i in indicator_series
        ]

        # Stock levels
        stocks = FuelStockLevel.objects.order_by("date", "fuel_type", "stock_type").values(
            "date", "fuel_type", "stock_type", "days_of_supply", "mso_minimum_days",
        )
        stock_data = defaultdict(list)
        for s in stocks:
            key = f"{s['fuel_type']}_{s['stock_type']}"
            stock_data[key].append({
                "date": str(s["date"]),
                "days": round(s["days_of_supply"], 1),
                "mso_min": s["mso_minimum_days"],
            })

        # Fuel prices
        prices = FuelPriceObservation.objects.order_by("date", "fuel_type").values(
            "date", "fuel_type", "retail_price_nzd", "import_cost_nzd",
            "margin_nzd", "pct_change",
        )
        price_data = defaultdict(list)
        for p in prices:
            price_data[p["fuel_type"]].append({
                "date": str(p["date"]),
                "retail": round(p["retail_price_nzd"], 3),
                "import_cost": round(p["import_cost_nzd"], 3) if p["import_cost_nzd"] else None,
                "margin": round(p["margin_nzd"], 3) if p["margin_nzd"] else None,
                "pct_change": round(p["pct_change"], 1) if p["pct_change"] is not None else None,
            })

        # Get latest stock date for staleness calculation
        latest_stock_date = FuelStockLevel.objects.aggregate(d=Max("date"))["d"]

        # Model assumptions and confidence metadata
        methodology = {
            "model_version": "1.0",
            "composite_method": "Weighted sigmoid scoring (6 components)",
            "weights": {
                "hormuz_disruption": 0.30,
                "stock_depletion": 0.25,
                "price_acceleration": 0.20,
                "supply_chain": 0.10,
                "demand_signal": 0.10,
                "gdelt_narrative": 0.05,
            },
            "assumptions": [
                "NZ imports ~40% of refined fuel from refineries dependent on Hormuz crude",
                "Stock data is from MBIE quarterly reports — may be up to 90 days stale",
                "Depletion model assumes linear consumption and constant disruption fraction",
                "Cape of Good Hope rerouting adds ~14 days to tanker transit when Hormuz disruption >30%",
                "MSO minimums: petrol 28d, diesel 21d, jet fuel 24d (per Jan 2025 regulations)",
                "Industry cascade thresholds are domain estimates, not empirically calibrated",
                "Price data from MBIE weekly monitoring — 1 week lag",
            ],
            "data_sources": {
                "fuel_prices": "MBIE Weekly Fuel Price Monitoring (weekly CSV)",
                "fuel_stocks": "MBIE Quarterly Oil Statistics (manual entry)",
                "hormuz_traffic": "Sentinel-1 SAR vessel detection (2x/week)",
                "nz_flights": "OpenSky ADS-B flight activity (daily)",
                "gdelt_events": "GDELT Project crisis event monitoring (6-hourly)",
            },
            "confidence_notes": {
                "stock_staleness": (
                    f"{(date.today() - latest_stock_date).days} days since last stock measurement"
                    if latest_stock_date else "No stock data available"
                ),
                "price_coverage": f"{sum(len(v) for v in price_data.values())} price observations across {len(price_data)} fuel types",
                "sar_observations": f"{len(list(indicator_series))} security indicator calculations",
            },
        }

        result = {
            "indicator": indicator_data,
            "series": series_data,
            "stocks": dict(stock_data),
            "prices": dict(price_data),
            "methodology": methodology,
        }

        self._write(os.path.join(out_dir, "fuel_security.json"), result)
