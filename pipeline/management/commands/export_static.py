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
    NightlightObservation,
    SARVesselDetection,
    ThermalAnomaly,
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

        self.stdout.write(self.style.SUCCESS(f"Export complete → {out_dir}/"))

    # ------------------------------------------------------------------

    def _write(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"), default=str)
        self.stdout.write(f"  wrote {path}")

    def _export_meta(self, out_dir):
        import datetime
        latest_dnb = NightlightObservation.objects.aggregate(latest=Max("date"))["latest"]
        latest_fire = ThermalAnomaly.objects.aggregate(latest=Max("detected_at"))["latest"]
        self._write(
            os.path.join(out_dir, "meta.json"),
            {
                "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
                "latest_nightlight": str(latest_dnb) if latest_dnb else None,
                "latest_fire": latest_fire.isoformat() if latest_fire else None,
                "war_start": "2026-02-28",
                "baseline_start": "2026-01-15",
                "baseline_end": "2026-02-27",
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

    def _export_compound_risk(self, out_dir):
        """Latest compound risk indicators."""
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

        result = {
            "as_of": str(indicators[0].date) if indicators else None,
            "indicators": [
                {
                    "aoi_name": i.aoi.name,
                    "country": i.aoi.country,
                    "compound_risk": round(i.compound_risk, 4),
                    "alert_level": i.alert_level,
                    "nightlight_score": round(i.nightlight_score, 4),
                    "fire_activity_score": round(i.fire_activity_score, 4),
                    "trade_flow_score": round(i.trade_flow_score, 4),
                }
                for i in indicators
            ],
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
            result[name].append({
                "date": str(d["date"]),
                "vessel_count": d["vessel_count"],
                "baseline_count": d["baseline_count"],
                "pct_change": round(d["pct_change"], 1) if d["pct_change"] is not None else None,
                "scene_coverage": round(d["scene_coverage"], 2),
                "mean_scr_db": round(d["mean_scr_db"], 1),
            })

        self._write(os.path.join(out_dir, "sar.json"), result)
