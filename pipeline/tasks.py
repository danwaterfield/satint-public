"""
Celery tasks for the satellite intelligence pipeline.

Task schedule is defined in satint/settings.py under CELERY_BEAT_SCHEDULE.
"""

import logging
import os
from datetime import date, datetime, timedelta

from celery import shared_task
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone

from pipeline.clients.firms import FIRMSClient, GULF_BBOX
from pipeline.clients.gfw import fetch_all_chokepoints, get_baseline_transits
from pipeline.clients.nightlight import NightlightClient, BASELINE_START, BASELINE_END
from pipeline.clients.sar import SARClient
from pipeline.clients.sentinel2 import Sentinel2Client, count_bright_objects
from pipeline.clients.dnb_swath import fetch_dnb_for_aoi
from pipeline.models import (
    AreaOfInterest,
    CommercialTransit,
    CompoundRiskIndicator,
    FlightActivity,
    GDELTEventCount,
    GroundwaterAnomaly,
    InternetOutage,
    MigrationPressureIndicator,
    NightlightObservation,
    NO2Reading,
    OpticalAssetCount,
    SARCoherenceChange,
    SARVesselDetection,
    ThermalAnomaly,
    ThermalSignature,
    VesselTransit,
)

logger = logging.getLogger(__name__)


def _sigmoid_score(value: float, midpoint: float, steepness: float = 0.1) -> float:
    """
    Map a raw value to a 0–1 score using a sigmoid curve.

    Produces smooth, continuous scores instead of discontinuous step functions.
    midpoint: value at which score = 0.5
    steepness: how sharp the transition is (higher = sharper)
    """
    import math
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (value - midpoint)))
    except OverflowError:
        return 0.0 if value < midpoint else 1.0


def _parse_acq_datetime(acq_date_str, acq_time_val):
    """Parse FIRMS acq_date (YYYY-MM-DD) and acq_time (HHMM int) into datetime."""
    try:
        acq_time_int = int(acq_time_val or 0)
        hour = acq_time_int // 100
        minute = acq_time_int % 100
        dt = datetime.strptime(str(acq_date_str), "%Y-%m-%d").replace(
            hour=hour, minute=minute
        )
        return timezone.make_aware(dt)
    except Exception:
        return timezone.now()


def _infra_aois_as_dicts():
    """Return infrastructure AOIs as plain dicts for proximity calculation."""
    aois = AreaOfInterest.objects.filter(category="infrastructure")
    result = []
    for aoi in aois:
        try:
            lon, lat = aoi.geometry.coords
            result.append({"id": aoi.pk, "name": aoi.name, "lat": lat, "lon": lon})
        except Exception:
            pass
    return result


@shared_task(bind=True, max_retries=3)
def fetch_viirs_active_fires(self):
    """
    Fetch VIIRS active fire detections from both SNPP and NOAA-20 satellites,
    deduplicate, cross-reference against infrastructure AOIs, and persist.
    """
    logger.info("Starting VIIRS active fire fetch")
    client = FIRMSClient()

    all_fires = []
    for satellite in ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"):
        try:
            detections = client.fetch_active_fires(GULF_BBOX, days=2, satellite=satellite)
            for d in detections:
                d["_satellite"] = satellite
            all_fires.extend(detections)
            logger.info("  %s: %d detections", satellite, len(detections))
        except Exception as exc:
            logger.error("Error fetching %s: %s", satellite, exc)

    # Deduplicate on lat/lon/date/time
    seen = set()
    unique_fires = []
    for f in all_fires:
        key = (f.get("latitude"), f.get("longitude"), f.get("acq_date"), f.get("acq_time"))
        if key not in seen:
            seen.add(key)
            unique_fires.append(f)

    logger.info("Unique detections after dedup: %d", len(unique_fires))

    # Skip fires already in DB (no unique constraint on model)
    existing_times = set(
        ThermalAnomaly.objects.filter(
            detected_at__gte=timezone.now() - timedelta(days=3),
        ).values_list("latitude", "longitude", "detected_at", named=False)
    )

    infra_aois = _infra_aois_as_dicts()
    infra_map = {a["id"]: a for a in infra_aois}

    anomalies = []
    near_infra_count = 0

    for f in unique_fires:
        try:
            lat = float(f["latitude"])
            lon = float(f["longitude"])
        except (TypeError, ValueError):
            continue

        detected_at = _parse_acq_datetime(f.get("acq_date"), f.get("acq_time"))

        # Skip if already in DB
        if (lat, lon, detected_at) in existing_times:
            continue

        nearest_aoi_obj = None
        distance_km = None
        nearest_dict, dist = client.classify_fire_proximity(lat, lon, infra_aois, threshold_km=25)
        if nearest_dict:
            try:
                nearest_aoi_obj = AreaOfInterest.objects.get(pk=nearest_dict["id"])
                distance_km = dist
                near_infra_count += 1
            except AreaOfInterest.DoesNotExist:
                pass

        satellite_label = f.get("_satellite", f.get("satellite", "VIIRS"))

        anomalies.append(
            ThermalAnomaly(
                latitude=lat,
                longitude=lon,
                point=Point(lon, lat),
                detected_at=detected_at,
                brightness=float(f.get("bright_ti4") or f.get("brightness") or 0),
                frp=float(f.get("frp") or 0),
                confidence=str(f.get("confidence", "n"))[:10],
                satellite=satellite_label[:20],
                nearest_infrastructure=nearest_aoi_obj,
                distance_to_infrastructure=distance_km,
            )
        )

    with transaction.atomic():
        ThermalAnomaly.objects.bulk_create(anomalies, ignore_conflicts=True)

    logger.info(
        "Saved %d thermal anomalies (%d near infrastructure)",
        len(anomalies),
        near_infra_count,
    )
    return {
        "total": len(anomalies),
        "near_infrastructure": near_infra_count,
        "date": date.today().isoformat(),
    }


@shared_task(bind=True, max_retries=3)
def fetch_viirs_nightlights(self):
    """
    Download today's Black Marble granules for the Gulf region and extract
    per-city radiance, comparing against the pre-war baseline.
    """
    logger.info("Starting nightlight fetch")
    client = NightlightClient()

    try:
        client.authenticate()
    except Exception as exc:
        logger.error("Earthdata authentication failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)

    today = date.today()
    today_str = today.isoformat()

    # VNP46A2 has a ~4-7 day processing lag; search the last 8 days
    import os, tempfile
    search_start = (today - timedelta(days=8)).isoformat()
    try:
        granules = client.search_nightlight_granules(search_start, today_str, GULF_BBOX)
        if not granules:
            logger.warning("No nightlight granules found from %s to %s", search_start, today_str)
            return {"date": today_str, "processed": 0}

        # Use the most recent acquisition date available from the granules
        data_date_str = None
        for g in sorted(granules, key=lambda x: x.data_links()[0], reverse=True):
            fname = g.data_links()[0].split("/")[-1]
            # VNP46A2.A2026054.hXXvYY.002.*.h5 → day-of-year 054
            parts = fname.split(".")
            if len(parts) >= 2 and parts[1].startswith("A"):
                year = int(parts[1][1:5])
                doy  = int(parts[1][5:8])
                from datetime import datetime
                d = datetime(year, 1, 1) + timedelta(days=doy - 1)
                data_date_str = d.strftime("%Y-%m-%d")
                break
        if not data_date_str:
            data_date_str = today_str

        download_dir = os.path.join(tempfile.gettempdir(), "satint_nightlights", data_date_str)
        files = client.download_granules(granules, download_dir)
        logger.info("Downloaded %d granule files (data date: %s)", len(files), data_date_str)
    except Exception as exc:
        logger.error("Granule download failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)

    from datetime import datetime as _dt
    data_date = _dt.strptime(data_date_str, "%Y-%m-%d").date()

    city_aois = AreaOfInterest.objects.filter(category="city")
    processed = 0

    for aoi in city_aois:
        try:
            lon, lat = aoi.geometry.coords
            radius_km = aoi.metadata.get("radius_km", 30)

            # Try each downloaded file until we get a result for this city
            result = None
            for filepath in files:
                result = client.extract_radiance_for_point(filepath, lat, lon, radius_km)
                if result:
                    break

            if not result:
                logger.debug("No radiance result for %s", aoi.name)
                continue

            # Calculate baseline from stored observations
            # Use all cloud fractions — strict filtering eliminates all data for cities
            # with chronic winter cloud cover (Tehran, Isfahan). Prefer clearest days
            # when multiple observations exist, but don't exclude entirely cloudy days.
            baseline_obs = NightlightObservation.objects.filter(
                aoi=aoi,
                date__range=(BASELINE_START, BASELINE_END),
            ).values_list("mean_radiance", flat=True)

            baseline = (
                sum(baseline_obs) / len(baseline_obs) if baseline_obs else None
            )
            pct_change = client.calculate_pct_change(result["mean_radiance"], baseline)

            NightlightObservation.objects.update_or_create(
                aoi=aoi,
                date=data_date,
                source="VNP46A2",
                defaults={
                    "mean_radiance": result["mean_radiance"],
                    "median_radiance": result["median_radiance"],
                    "baseline_radiance": baseline,
                    "pct_change": pct_change,
                    "cloud_fraction": result.get("cloud_fraction", 0),
                },
            )
            processed += 1

        except Exception as exc:
            logger.error("Error processing nightlight for %s: %s", aoi.name, exc)

    logger.info("Nightlight processing complete: %d cities updated", processed)
    return {"date": today_str, "processed": processed}


# City bounding boxes for DNB swath extraction (≈ radius_km * 2 in degrees)
_DNB_CITY_BOXES = {
    "Tehran":       {"min_lat": 35.2, "max_lat": 36.2, "min_lon": 50.9, "max_lon": 51.9},
    "Dubai":        {"min_lat": 24.9, "max_lat": 25.5, "min_lon": 54.9, "max_lon": 55.6},
    "Doha":         {"min_lat": 25.1, "max_lat": 25.5, "min_lon": 51.4, "max_lon": 51.7},
    "Kuwait City":  {"min_lat": 29.1, "max_lat": 29.6, "min_lon": 47.7, "max_lon": 48.2},
    "Riyadh":       {"min_lat": 24.3, "max_lat": 25.1, "min_lon": 46.3, "max_lon": 47.1},
    "Abu Dhabi":    {"min_lat": 24.2, "max_lat": 24.7, "min_lon": 54.1, "max_lon": 54.6},
    "Manama":       {"min_lat": 26.1, "max_lat": 26.4, "min_lon": 50.4, "max_lon": 50.7},
    "Isfahan":      {"min_lat": 32.4, "max_lat": 32.9, "min_lon": 51.4, "max_lon": 52.0},
    "Basra":        {"min_lat": 30.3, "max_lat": 30.7, "min_lon": 47.6, "max_lon": 48.0},
    # NZ migration targets — larger boxes due to coastal cloud fill patterns
    "Auckland":     {"min_lat": -37.3, "max_lat": -36.4, "min_lon": 174.3, "max_lon": 175.2},
    "Queenstown":   {"min_lat": -45.2, "max_lat": -44.8, "min_lon": 168.4, "max_lon": 168.9},
}

_DNB_DOWNLOAD_DIR = "/tmp/satint_dnb"


@shared_task(bind=True, max_retries=2)
def fetch_dnb_nightlights(self):
    """
    Fetch raw VIIRS DNB L1B swaths (VNP02DNB + VNP03DNB) for Gulf cities.

    Near-real-time alternative to VNP46A2: ~3h lag instead of ~11 days.
    Stores results as NightlightObservation with source='VIIRS_DNB_L1B'.
    Runs daily after VNP46A2 for any dates VNP46A2 hasn't yet delivered.
    """
    logger.info("Starting DNB swath nightlight fetch")
    today = date.today()

    # Only fetch dates where we have no VNP46A2 data yet
    from django.db.models import Max
    latest_vnp46 = (
        NightlightObservation.objects.filter(source="VNP46A2")
        .aggregate(latest=Max("date"))["latest"]
    )
    # Fetch the gap: day after latest VNP46A2 up to yesterday (DNB has ~3h lag)
    fetch_start = (latest_vnp46 + timedelta(days=1)) if latest_vnp46 else (today - timedelta(days=7))
    fetch_end   = today - timedelta(days=1)  # yesterday guaranteed complete

    if fetch_start > fetch_end:
        logger.info("No DNB gap to fill (VNP46A2 latest=%s)", latest_vnp46)
        return {"gap_days": 0, "processed": 0}

    gap_days = (fetch_end - fetch_start).days + 1
    logger.info("DNB gap: %s to %s (%d days)", fetch_start, fetch_end, gap_days)

    city_aois = {aoi.name: aoi for aoi in AreaOfInterest.objects.filter(category="city")}
    processed = 0

    current = fetch_start
    while current <= fetch_end:
        date_str = current.isoformat()
        # Per-date download dir so granules for different dates don't clash
        date_dl_dir = os.path.join(_DNB_DOWNLOAD_DIR, date_str)
        os.makedirs(date_dl_dir, exist_ok=True)

        for city_name, bbox in _DNB_CITY_BOXES.items():
            aoi = city_aois.get(city_name)
            if not aoi:
                continue
            # Skip if we already have DNB data for this city/date
            if NightlightObservation.objects.filter(aoi=aoi, date=current, source="VIIRS_DNB_L1B").exists():
                continue
            try:
                result = fetch_dnb_for_aoi(city_name, bbox, current, date_dl_dir)
                if result and result.get("mean_radiance") is not None:
                    # Compute pct_change vs baseline
                    baseline_obs = NightlightObservation.objects.filter(
                        aoi=aoi,
                        date__range=(BASELINE_START, BASELINE_END),
                    ).values_list("mean_radiance", flat=True)
                    baseline = (
                        sum(baseline_obs) / len(baseline_obs) if baseline_obs else None
                    )
                    pct_change = (
                        (result["mean_radiance"] - baseline) / baseline * 100
                        if baseline and baseline > 0 else None
                    )
                    NightlightObservation.objects.update_or_create(
                        aoi=aoi,
                        date=current,
                        source="VIIRS_DNB_L1B",
                        defaults={
                            "mean_radiance": result["mean_radiance"],
                            "median_radiance": result["median_radiance"],
                            "baseline_radiance": baseline,
                            "pct_change": pct_change,
                            "cloud_fraction": result.get("cloud_fraction", 1.0),
                        },
                    )
                    processed += 1
                    logger.info(
                        "DNB %s %s: %.1f nW → pct_change=%.1f%%",
                        city_name, date_str, result["mean_radiance"], pct_change or 0,
                    )
            except Exception as exc:
                logger.error("DNB fetch failed for %s %s: %s", city_name, date_str, exc)

        # Clean up per-date downloads after all cities processed
        import shutil
        try:
            shutil.rmtree(date_dl_dir)
        except OSError:
            pass

        current += timedelta(days=1)

    logger.info("DNB fetch complete: %d observations stored", processed)
    return {"gap_start": fetch_start.isoformat(), "gap_end": fetch_end.isoformat(), "processed": processed}


@shared_task(bind=True, max_retries=3)
def fetch_vessel_data(self):
    """
    Fetch vessel transit counts at all monitored maritime chokepoints
    and compare against pre-war baseline.
    """
    logger.info("Starting vessel data fetch")
    today = date.today()
    today_str = today.isoformat()

    try:
        results = fetch_all_chokepoints(today_str)
    except Exception as exc:
        logger.error("GFW fetch failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)

    saved = 0
    for result in results:
        chokepoint_name = result.get("chokepoint", "")
        vessel_counts = result.get("vessel_counts_by_type", {})

        aoi = AreaOfInterest.objects.filter(
            category="chokepoint", name__icontains=chokepoint_name.replace("_", " ")
        ).first()

        if not aoi:
            logger.warning("No AOI found for chokepoint: %s", chokepoint_name)
            continue

        try:
            baseline = get_baseline_transits(chokepoint_name)
        except Exception as exc:
            logger.warning("Could not fetch baseline for %s: %s", chokepoint_name, exc)
            baseline = {}

        for vessel_type, count in vessel_counts.items():
            baseline_count = baseline.get(vessel_type)
            pct_change = None
            if baseline_count and baseline_count > 0:
                pct_change = (count - baseline_count) / baseline_count * 100

            VesselTransit.objects.update_or_create(
                chokepoint=aoi,
                date=today,
                vessel_type=vessel_type,
                defaults={
                    "count": count,
                    "baseline_count": baseline_count,
                    "pct_change": pct_change,
                },
            )
            saved += 1

    logger.info("Vessel data saved: %d records", saved)
    return {"date": today_str, "records_saved": saved}


# SAR baseline window (same as nightlight baseline)
_SAR_BASELINE_START = BASELINE_START
_SAR_BASELINE_END   = BASELINE_END

# Chokepoints to monitor with their bounding boxes (must match AOI names)
_SAR_CHOKEPOINTS = {
    "Hormuz": {"min_lat": 26.0, "max_lat": 27.0, "min_lon": 55.5, "max_lon": 57.0},
    "Bab al-Mandeb": {"min_lat": 12.3, "max_lat": 13.0, "min_lon": 43.0, "max_lon": 44.0},
}

# Local cache dir for SAR zips (large, keep between runs)
_SAR_CACHE_DIR = "/tmp/satint_sar"


@shared_task(bind=True, max_retries=2)
def fetch_sar_vessel_counts(self):
    """
    Download the latest Sentinel-1A GRD scene for each monitored chokepoint,
    count vessel detections via CFAR, and persist vs pre-war baseline.

    Scenes are ~850 MB each; runs ~2× per week matching Sentinel-1 revisit.
    """
    logger.info("Starting SAR vessel detection")
    client = SARClient()

    try:
        client.authenticate()
    except Exception as exc:
        logger.error("SAR auth failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)

    today = date.today()
    results_summary = {}

    for chokepoint_name, bbox in _SAR_CHOKEPOINTS.items():
        aoi = AreaOfInterest.objects.filter(
            category="chokepoint",
            name__icontains=chokepoint_name.split()[0],  # "Hormuz", "Bab"
        ).first()

        if not aoi:
            logger.warning("No AOI found for SAR chokepoint: %s", chokepoint_name)
            continue

        try:
            # Search last 7 days (Sentinel-1 ~6-day repeat, some gaps)
            search_start = (today - timedelta(days=7)).isoformat()
            scenes = client.search_scenes(bbox, search_start, today.isoformat())

            if not scenes:
                logger.warning("No Sentinel-1 scenes found for %s", chokepoint_name)
                continue

            # Use most recent scene
            scene = scenes[0]
            scene_date = client.get_scene_date(scene)
            if not scene_date:
                scene_date = today

            # Skip if already processed this scene date
            if SARVesselDetection.objects.filter(chokepoint=aoi, date=scene_date).exists():
                logger.info("SAR already processed for %s on %s", chokepoint_name, scene_date)
                continue

            cache_dir = os.path.join(_SAR_CACHE_DIR, chokepoint_name.replace(" ", "_"))
            detection = client.process_scene_for_chokepoint(scene, bbox, cache_dir)

            if not detection:
                continue

            # Compute baseline from stored pre-war detections
            baseline_qs = SARVesselDetection.objects.filter(
                chokepoint=aoi,
                date__range=(_SAR_BASELINE_START, _SAR_BASELINE_END),
            ).values_list("vessel_count", flat=True)

            baseline_count = (
                sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
            )
            pct_change = None
            if baseline_count and baseline_count > 0:
                pct_change = (
                    (detection["vessel_count"] - baseline_count) / baseline_count * 100
                )

            SARVesselDetection.objects.update_or_create(
                chokepoint=aoi,
                date=scene_date,
                defaults={
                    "vessel_count": detection["vessel_count"],
                    "baseline_count": baseline_count,
                    "pct_change": pct_change,
                    "scene_id": detection["scene_id"],
                    "scene_coverage": detection["scene_coverage"],
                    "mean_scr_db": detection["mean_scr_db"],
                    "polarization": "VV",
                },
            )

            results_summary[chokepoint_name] = {
                "date": scene_date.isoformat(),
                "vessel_count": detection["vessel_count"],
                "pct_change": pct_change,
                "coverage": detection["scene_coverage"],
            }
            logger.info(
                "SAR %s %s: %d vessels (baseline=%.1f, pct=%s)",
                chokepoint_name, scene_date, detection["vessel_count"],
                baseline_count or 0,
                f"{pct_change:+.1f}%" if pct_change is not None else "no baseline",
            )

        except Exception as exc:
            logger.error("SAR processing error for %s: %s", chokepoint_name, exc)

    return {"processed": results_summary}


@shared_task(bind=True, max_retries=3)
def calculate_compound_indicators(self):
    """
    Calculate compound risk scores for all city AOIs based on
    nightlight, fire activity, and trade flow sub-scores.
    """
    logger.info("Calculating compound risk indicators")
    today = date.today()

    # Pre-fetch chokepoint pct_changes for trade flow score
    # Priority: 1) CommercialTransit (OSINT-verified AIS counts)
    #           2) SAR (non-military only)
    #           3) GFW AIS (VesselTransit)
    commercial_changes = list(
        CommercialTransit.objects.filter(
            date__gte=today - timedelta(days=7),
            chokepoint="hormuz",
        )
        .exclude(pct_change=None)
        .values_list("pct_change", flat=True)
    )
    if commercial_changes:
        avg_chokepoint_change = sum(commercial_changes) / len(commercial_changes)
    else:
        sar_changes = list(
            SARVesselDetection.objects.filter(
                date__gte=today - timedelta(days=7),
                chokepoint__category="chokepoint",
                is_military=False,
            )
            .exclude(pct_change=None)
            .values_list("pct_change", flat=True)
        )
        if sar_changes:
            avg_chokepoint_change = sum(sar_changes) / len(sar_changes)
        else:
            hormuz_change = (
                VesselTransit.objects.filter(
                    chokepoint__name__icontains="Hormuz", date=today
                )
                .exclude(pct_change=None)
                .values_list("pct_change", flat=True)
            )
            mandeb_change = (
                VesselTransit.objects.filter(
                    chokepoint__name__icontains="Mandeb", date=today
                )
                .exclude(pct_change=None)
                .values_list("pct_change", flat=True)
            )
            all_ais = list(hormuz_change) + list(mandeb_change)
            avg_chokepoint_change = sum(all_ais) / len(all_ais) if all_ais else 0

    # Exclude NZ cities — they have their own migration pressure indicator
    city_aois = AreaOfInterest.objects.filter(category="city").exclude(country="New Zealand")
    cutoff_48h = timezone.now() - timedelta(hours=48)
    updated = 0

    for aoi in city_aois:
        try:
            # --- Nightlight score ---
            # Use most recent observation within last 20 days (handles processing lag + baseline gap)
            nl_obs = (
                NightlightObservation.objects.filter(
                    aoi=aoi,
                    date__gte=today - timedelta(days=20),
                )
                .exclude(pct_change=None)
                .order_by("-date")
                .first()
            )
            pct = nl_obs.pct_change if nl_obs else 0
            # Sigmoid: 50% score at -30% drop, steepness 0.08
            nightlight_score = _sigmoid_score(-pct, 30, steepness=0.08)

            # --- Fire activity score ---
            # Count anomalies near this city's coordinates within 50km
            lon, lat = aoi.geometry.coords
            from django.contrib.gis.measure import D
            from django.contrib.gis.geos import Point as GEOSPoint
            city_point = GEOSPoint(lon, lat, srid=4326)
            fire_count = ThermalAnomaly.objects.filter(
                detected_at__gte=cutoff_48h,
                nearest_infrastructure__isnull=False,
                point__distance_lte=(city_point, D(km=100)),
            ).count()

            # Sigmoid: 50% score at 5 fires, steepness 0.4
            fire_activity_score = _sigmoid_score(fire_count, 5, steepness=0.4)

            # --- Trade flow score ---
            # Sigmoid: 50% score at -20% chokepoint change, steepness 0.1
            trade_flow_score = _sigmoid_score(-avg_chokepoint_change, 20, steepness=0.1)

            # --- Compound risk (weighted) ---
            compound_risk = round(
                nightlight_score * 0.35
                + fire_activity_score * 0.35
                + trade_flow_score * 0.30,
                4,
            )

            if compound_risk >= 0.8:
                alert_level = "emergency"
            elif compound_risk >= 0.6:
                alert_level = "critical"
            elif compound_risk >= 0.4:
                alert_level = "high"
            elif compound_risk >= 0.2:
                alert_level = "elevated"
            else:
                alert_level = "normal"

            CompoundRiskIndicator.objects.update_or_create(
                aoi=aoi,
                date=today,
                defaults={
                    "nightlight_score": nightlight_score,
                    "fire_activity_score": fire_activity_score,
                    "trade_flow_score": trade_flow_score,
                    "compound_risk": compound_risk,
                    "alert_level": alert_level,
                },
            )
            updated += 1

        except Exception as exc:
            logger.error("Error calculating risk for %s: %s", aoi.name, exc)

    logger.info("Compound indicators updated for %d cities", updated)
    return {"date": today.isoformat(), "updated": updated}


@shared_task(bind=True, max_retries=3)
def check_threshold_alerts(self):
    """
    Check for threshold breaches and log alerts.
    Returns a list of alert dicts for monitoring/webhook use.
    """
    logger.info("Running threshold alert check")
    today = date.today()
    cutoff_6h = timezone.now() - timedelta(hours=6)
    alerts = []

    # Critical/emergency compound risk
    critical = CompoundRiskIndicator.objects.filter(
        date=today, alert_level__in=("critical", "emergency")
    ).select_related("aoi")
    for indicator in critical:
        alert = {
            "type": "compound_risk",
            "level": indicator.alert_level,
            "location": indicator.aoi.name,
            "country": indicator.aoi.country,
            "score": indicator.compound_risk,
        }
        alerts.append(alert)
        logger.warning(
            "ALERT [%s] %s (%s) — compound risk %.2f",
            indicator.alert_level.upper(),
            indicator.aoi.name,
            indicator.aoi.country,
            indicator.compound_risk,
        )

    # Nightlight drops >20%
    dim_cities = NightlightObservation.objects.filter(
        date=today, pct_change__lt=-20
    ).select_related("aoi")
    for obs in dim_cities:
        alert = {
            "type": "nightlight_drop",
            "level": "high" if obs.pct_change < -40 else "elevated",
            "location": obs.aoi.name,
            "pct_change": round(obs.pct_change, 1),
        }
        alerts.append(alert)
        logger.warning(
            "ALERT [NIGHTLIGHT] %s — %.1f%% below baseline",
            obs.aoi.name,
            obs.pct_change,
        )

    # Recent fires near infrastructure
    infra_fires = ThermalAnomaly.objects.filter(
        detected_at__gte=cutoff_6h,
        nearest_infrastructure__isnull=False,
    ).select_related("nearest_infrastructure")
    for fire in infra_fires:
        alert = {
            "type": "infrastructure_fire",
            "level": "critical" if fire.frp > 100 else "elevated",
            "infrastructure": fire.nearest_infrastructure.name,
            "distance_km": fire.distance_to_infrastructure,
            "frp_mw": fire.frp,
            "satellite": fire.satellite,
        }
        alerts.append(alert)
        logger.warning(
            "ALERT [FIRE] %s — %.1fkm from %s (FRP: %.1f MW)",
            fire.satellite,
            fire.distance_to_infrastructure or 0,
            fire.nearest_infrastructure.name,
            fire.frp,
        )

    logger.info("Alert check complete: %d alerts", len(alerts))
    return alerts


# ---------------------------------------------------------------------------
# NZ Elite Migration Signal Detection tasks
# ---------------------------------------------------------------------------

# NZ marina/airport bounding boxes for Sentinel-2 and SAR processing
_NZ_MARINA_BBOXES = {
    "Viaduct Harbour":      {"min_lon": 174.7560, "min_lat": -36.8460, "max_lon": 174.7630, "max_lat": -36.8410},
    "Westhaven Marina":     {"min_lon": 174.7420, "min_lat": -36.8420, "max_lon": 174.7560, "max_lat": -36.8340},
    "Silo Marina":          {"min_lon": 174.7545, "min_lat": -36.8430, "max_lon": 174.7600, "max_lat": -36.8390},
    "Half Moon Bay Marina": {"min_lon": 174.8940, "min_lat": -36.8910, "max_lon": 174.9020, "max_lat": -36.8850},
    "Queenstown Marina":    {"min_lon": 168.6530, "min_lat": -45.0340, "max_lon": 168.6610, "max_lat": -45.0280},
}

_NZ_AIRPORT_BBOXES = {
    "Auckland GA Apron":    {"min_lon": 174.7820, "min_lat": -37.0110, "max_lon": 174.7900, "max_lat": -37.0060},
    "Queenstown Airport":   {"min_lon": 168.7320, "min_lat": -45.0250, "max_lon": 168.7470, "max_lat": -45.0170},
    "Wanaka Airport":       {"min_lon": 169.2380, "min_lat": -44.7260, "max_lon": 169.2530, "max_lat": -44.7180},
}

# Combined NZ search bbox (covers Auckland to Queenstown)
_NZ_SEARCH_BBOX = {"min_lon": 168.0, "min_lat": -46.0, "max_lon": 177.0, "max_lat": -34.0}


@shared_task(bind=True, max_retries=2)
def fetch_nz_sentinel2_counts(self):
    """
    Download latest Sentinel-2 scenes for NZ marinas and airports,
    count bright objects (vessels/aircraft), compare vs baseline.
    """
    logger.info("Starting NZ Sentinel-2 bright-object count")
    client = Sentinel2Client()

    try:
        client.authenticate()
    except Exception as exc:
        logger.error("CDSE authentication failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)

    today = date.today()
    search_start = (today - timedelta(days=10)).isoformat()
    search_end = today.isoformat()

    # Separate searches for Auckland and Queenstown regions
    auckland_bbox = {"min_lon": 174.5, "min_lat": -37.1, "max_lon": 175.0, "max_lat": -36.7}
    queenstown_bbox = {"min_lon": 168.5, "min_lat": -45.1, "max_lon": 169.5, "max_lat": -44.6}

    all_products = []
    for region_bbox in (auckland_bbox, queenstown_bbox):
        try:
            products = client.search_scenes(region_bbox, search_start, search_end)
            all_products.extend(products)
        except Exception as exc:
            logger.error("S2 scene search failed: %s", exc)

    if not all_products:
        logger.warning("No Sentinel-2 scenes found for NZ")
        return {"processed": 0}

    import tempfile
    dl_dir = os.path.join(tempfile.gettempdir(), "satint_s2_nz")
    processed = 0

    # Process most recent scene per region
    seen_dates = set()
    for product in all_products:
        scene_date = client.get_scene_date(product)
        if not scene_date or scene_date in seen_dates:
            continue
        seen_dates.add(scene_date)

        try:
            band_files = client.download_scene_bands(product, dl_dir, bands=("B08", "SCL"))
        except Exception as exc:
            logger.error("S2 download failed: %s", exc)
            continue

        b08_path = band_files.get("B08")
        scl_path = band_files.get("SCL")
        if not b08_path:
            continue

        # Process marinas
        for marina_name, bbox in _NZ_MARINA_BBOXES.items():
            aoi = AreaOfInterest.objects.filter(
                name=marina_name, category="marina"
            ).first()
            if not aoi:
                continue
            if OpticalAssetCount.objects.filter(
                aoi=aoi, date=scene_date, asset_type="vessel", source="Sentinel-2"
            ).exists():
                continue

            result = count_bright_objects(b08_path, scl_path, bbox, min_pixels=3, max_pixels=200)

            # Compute baseline
            baseline_qs = OpticalAssetCount.objects.filter(
                aoi=aoi, asset_type="vessel",
                date__range=(BASELINE_START, BASELINE_END),
            ).values_list("count", flat=True)
            baseline = sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
            pct_change = None
            if baseline and baseline > 0:
                pct_change = (result["count"] - baseline) / baseline * 100

            OpticalAssetCount.objects.update_or_create(
                aoi=aoi, date=scene_date, asset_type="vessel", source="Sentinel-2",
                defaults={
                    "count": result["count"],
                    "baseline_count": baseline,
                    "pct_change": pct_change,
                    "cloud_fraction": result["cloud_fraction"],
                    "scene_id": product.get("Name", ""),
                },
            )
            processed += 1
            logger.info("S2 %s %s: %d vessels (pct=%s)",
                        marina_name, scene_date, result["count"],
                        f"{pct_change:+.1f}%" if pct_change is not None else "no baseline")

        # Process airports
        for airport_name, bbox in _NZ_AIRPORT_BBOXES.items():
            aoi = AreaOfInterest.objects.filter(
                name=airport_name, category="airport"
            ).first()
            if not aoi:
                continue
            if OpticalAssetCount.objects.filter(
                aoi=aoi, date=scene_date, asset_type="aircraft", source="Sentinel-2"
            ).exists():
                continue

            result = count_bright_objects(b08_path, scl_path, bbox, min_pixels=2, max_pixels=50)

            baseline_qs = OpticalAssetCount.objects.filter(
                aoi=aoi, asset_type="aircraft",
                date__range=(BASELINE_START, BASELINE_END),
            ).values_list("count", flat=True)
            baseline = sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
            pct_change = None
            if baseline and baseline > 0:
                pct_change = (result["count"] - baseline) / baseline * 100

            OpticalAssetCount.objects.update_or_create(
                aoi=aoi, date=scene_date, asset_type="aircraft", source="Sentinel-2",
                defaults={
                    "count": result["count"],
                    "baseline_count": baseline,
                    "pct_change": pct_change,
                    "cloud_fraction": result["cloud_fraction"],
                    "scene_id": product.get("Name", ""),
                },
            )
            processed += 1
            logger.info("S2 %s %s: %d aircraft (pct=%s)",
                        airport_name, scene_date, result["count"],
                        f"{pct_change:+.1f}%" if pct_change is not None else "no baseline")

    logger.info("NZ S2 processing complete: %d observations", processed)
    return {"processed": processed}


# NZ SAR approach/marina bounding boxes
_NZ_SAR_ZONES = {
    "NZ North Approach": {"min_lat": -35.5, "max_lat": -34.0, "min_lon": 172.0, "max_lon": 177.0},
    "NZ East Approach":  {"min_lat": -38.0, "max_lat": -35.0, "min_lon": 177.0, "max_lon": 180.0},
}

_NZ_SAR_MARINAS = {
    "Westhaven Marina":     {"min_lon": 174.7420, "min_lat": -36.8420, "max_lon": 174.7560, "max_lat": -36.8340},
    "Viaduct Harbour":      {"min_lon": 174.7560, "min_lat": -36.8460, "max_lon": 174.7630, "max_lat": -36.8410},
    "Silo Marina":          {"min_lon": 174.7545, "min_lat": -36.8430, "max_lon": 174.7600, "max_lat": -36.8390},
}


@shared_task(bind=True, max_retries=2)
def fetch_nz_sar_marina(self):
    """
    Sentinel-1 SAR yacht detection at NZ marinas and approach zones.
    Uses yacht detection profile (MIN_SHIP_PIXELS=3) for marina basins.
    """
    logger.info("Starting NZ SAR yacht/approach detection")
    client = SARClient()

    try:
        client.authenticate()
    except Exception as exc:
        logger.error("SAR auth failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)

    today = date.today()
    search_start = (today - timedelta(days=12)).isoformat()
    results_summary = {}

    # Process approach zones (cargo profile — large vessels inbound)
    for zone_name, bbox in _NZ_SAR_ZONES.items():
        aoi = AreaOfInterest.objects.filter(
            name=zone_name, category="approach"
        ).first()
        if not aoi:
            continue

        try:
            scenes = client.search_scenes(bbox, search_start, today.isoformat())
            if not scenes:
                continue

            scene = scenes[0]
            scene_date = client.get_scene_date(scene) or today

            if SARVesselDetection.objects.filter(chokepoint=aoi, date=scene_date).exists():
                continue

            cache_dir = os.path.join("/tmp/satint_sar", zone_name.replace(" ", "_"))
            detection = client.process_scene_for_chokepoint(
                scene, bbox, cache_dir, profile="cargo"
            )
            if not detection:
                continue

            baseline_qs = SARVesselDetection.objects.filter(
                chokepoint=aoi,
                date__range=(BASELINE_START, BASELINE_END),
            ).values_list("vessel_count", flat=True)
            baseline_count = sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
            pct_change = None
            if baseline_count and baseline_count > 0:
                pct_change = (detection["vessel_count"] - baseline_count) / baseline_count * 100

            SARVesselDetection.objects.update_or_create(
                chokepoint=aoi, date=scene_date,
                defaults={
                    "vessel_count": detection["vessel_count"],
                    "baseline_count": baseline_count,
                    "pct_change": pct_change,
                    "scene_id": detection["scene_id"],
                    "scene_coverage": detection["scene_coverage"],
                    "mean_scr_db": detection["mean_scr_db"],
                    "polarization": "VV",
                },
            )
            results_summary[zone_name] = {
                "date": scene_date.isoformat(),
                "vessel_count": detection["vessel_count"],
                "pct_change": pct_change,
            }
            logger.info("SAR %s %s: %d vessels", zone_name, scene_date, detection["vessel_count"])

        except Exception as exc:
            logger.error("SAR error for %s: %s", zone_name, exc)

    # Process marinas (yacht profile — smaller hulls)
    auckland_bbox = {"min_lon": 174.7, "min_lat": -36.9, "max_lon": 174.8, "max_lat": -36.8}
    try:
        scenes = client.search_scenes(auckland_bbox, search_start, today.isoformat())
        if scenes:
            scene = scenes[0]
            scene_date = client.get_scene_date(scene) or today
            cache_dir = os.path.join("/tmp/satint_sar", "NZ_marinas")

            for marina_name, bbox in _NZ_SAR_MARINAS.items():
                aoi = AreaOfInterest.objects.filter(
                    name=marina_name, category="marina"
                ).first()
                if not aoi:
                    continue
                if SARVesselDetection.objects.filter(chokepoint=aoi, date=scene_date).exists():
                    continue

                detection = client.process_scene_for_chokepoint(
                    scene, bbox, cache_dir, profile="yacht"
                )
                if not detection:
                    continue

                baseline_qs = SARVesselDetection.objects.filter(
                    chokepoint=aoi,
                    date__range=(BASELINE_START, BASELINE_END),
                ).values_list("vessel_count", flat=True)
                baseline_count = sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
                pct_change = None
                if baseline_count and baseline_count > 0:
                    pct_change = (detection["vessel_count"] - baseline_count) / baseline_count * 100

                SARVesselDetection.objects.update_or_create(
                    chokepoint=aoi, date=scene_date,
                    defaults={
                        "vessel_count": detection["vessel_count"],
                        "baseline_count": baseline_count,
                        "pct_change": pct_change,
                        "scene_id": detection["scene_id"],
                        "scene_coverage": detection["scene_coverage"],
                        "mean_scr_db": detection["mean_scr_db"],
                        "polarization": "VV",
                    },
                )
                results_summary[marina_name] = {
                    "date": scene_date.isoformat(),
                    "vessel_count": detection["vessel_count"],
                }
                logger.info("SAR yacht %s %s: %d vessels",
                            marina_name, scene_date, detection["vessel_count"])

    except Exception as exc:
        logger.error("SAR marina processing error: %s", exc)

    return {"processed": results_summary}


@shared_task(bind=True, max_retries=2)
def calculate_migration_pressure(self):
    """
    Calculate compound migration pressure scores for NZ locations.
    Combines marina occupancy, airport aircraft, nightlight activity,
    SAR vessel approaches, and Gulf push factor into a single score.
    """
    logger.info("Calculating NZ migration pressure indicators")
    today = date.today()
    lookback = today - timedelta(days=14)

    # Gulf push factor: average compound risk across Gulf cities
    gulf_risks = list(
        CompoundRiskIndicator.objects.filter(
            date__gte=today - timedelta(days=7),
            aoi__country__in=["UAE", "Qatar", "Bahrain", "Kuwait", "Saudi Arabia", "Iran"],
        ).values_list("compound_risk", flat=True)
    )
    gulf_push = sum(gulf_risks) / len(gulf_risks) if gulf_risks else 0.0

    # Process NZ city AOIs
    nz_cities = AreaOfInterest.objects.filter(
        category="city", country="New Zealand"
    )
    updated = 0

    for aoi in nz_cities:
        try:
            city_name = aoi.name

            # Marina score: average pct_change across nearby marinas
            if city_name == "Auckland":
                marina_names = ["Viaduct Harbour", "Westhaven Marina", "Silo Marina", "Half Moon Bay Marina"]
            elif city_name == "Queenstown":
                marina_names = ["Queenstown Marina"]
            else:
                marina_names = []

            marina_changes = list(
                OpticalAssetCount.objects.filter(
                    aoi__name__in=marina_names,
                    date__gte=lookback,
                    asset_type="vessel",
                ).exclude(pct_change=None).values_list("pct_change", flat=True)
            )
            # Also include SAR marina detections
            sar_marina_changes = list(
                SARVesselDetection.objects.filter(
                    chokepoint__name__in=marina_names,
                    date__gte=lookback,
                ).exclude(pct_change=None).values_list("pct_change", flat=True)
            )
            all_marina = marina_changes + sar_marina_changes
            avg_marina_pct = sum(all_marina) / len(all_marina) if all_marina else 0

            # Sigmoid: 50% score at +25% marina vessel increase, steepness 0.06
            marina_score = _sigmoid_score(avg_marina_pct, 25, steepness=0.06)

            # Airport score
            if city_name == "Auckland":
                airport_names = ["Auckland GA Apron"]
            elif city_name == "Queenstown":
                airport_names = ["Queenstown Airport", "Wanaka Airport"]
            else:
                airport_names = []

            airport_changes = list(
                OpticalAssetCount.objects.filter(
                    aoi__name__in=airport_names,
                    date__gte=lookback,
                    asset_type="aircraft",
                ).exclude(pct_change=None).values_list("pct_change", flat=True)
            )
            avg_airport_pct = sum(airport_changes) / len(airport_changes) if airport_changes else 0

            # Sigmoid: 50% score at +25% airport aircraft increase, steepness 0.06
            airport_score = _sigmoid_score(avg_airport_pct, 25, steepness=0.06)

            # Nightlight score: positive change = activity increase
            nl_obs = (
                NightlightObservation.objects.filter(
                    aoi=aoi,
                    date__gte=lookback,
                )
                .exclude(pct_change=None)
                .order_by("-date")
                .first()
            )
            nl_pct = nl_obs.pct_change if nl_obs else 0
            # Sigmoid: 50% score at +10% nightlight increase, steepness 0.1
            nightlight_score = _sigmoid_score(nl_pct, 10, steepness=0.1)

            # SAR approach vessel score
            if city_name == "Auckland":
                approach_names = ["NZ North Approach", "NZ East Approach"]
            else:
                approach_names = []

            approach_changes = list(
                SARVesselDetection.objects.filter(
                    chokepoint__name__in=approach_names,
                    date__gte=lookback,
                ).exclude(pct_change=None).values_list("pct_change", flat=True)
            )
            avg_approach_pct = sum(approach_changes) / len(approach_changes) if approach_changes else 0

            # Sigmoid: 50% score at +20% approach vessel increase, steepness 0.08
            sar_vessel_score = _sigmoid_score(avg_approach_pct, 20, steepness=0.08)

            # Gulf push score (inverse — higher Gulf risk = higher NZ push)
            gulf_push_score = min(gulf_push, 1.0)

            # Compound migration pressure (weighted)
            migration_pressure = round(
                marina_score * 0.25
                + airport_score * 0.25
                + nightlight_score * 0.15
                + sar_vessel_score * 0.15
                + gulf_push_score * 0.20,
                4,
            )

            if migration_pressure >= 0.7:
                pressure_level = "surge"
            elif migration_pressure >= 0.4:
                pressure_level = "high"
            elif migration_pressure >= 0.2:
                pressure_level = "elevated"
            else:
                pressure_level = "baseline"

            MigrationPressureIndicator.objects.update_or_create(
                aoi=aoi,
                date=today,
                defaults={
                    "marina_score": marina_score,
                    "airport_score": airport_score,
                    "nightlight_score": nightlight_score,
                    "sar_vessel_score": sar_vessel_score,
                    "gulf_push_score": gulf_push_score,
                    "migration_pressure": migration_pressure,
                    "pressure_level": pressure_level,
                },
            )
            updated += 1
            logger.info(
                "Migration %s: pressure=%.3f (%s) — marina=%.1f airport=%.1f nl=%.1f sar=%.1f gulf=%.1f",
                city_name, migration_pressure, pressure_level,
                marina_score, airport_score, nightlight_score,
                sar_vessel_score, gulf_push_score,
            )

        except Exception as exc:
            logger.error("Error calculating migration pressure for %s: %s", aoi.name, exc)

    logger.info("Migration pressure updated for %d NZ locations", updated)
    return {"date": today.isoformat(), "updated": updated}


# ---------------------------------------------------------------------------
# Complementary intelligence sources
# ---------------------------------------------------------------------------

# NO2 bounding boxes — same cities as nightlights but wider for the coarser grid
_NO2_CITY_BOXES = {
    "Tehran":      {"min_lat": 35.0, "max_lat": 36.5, "min_lon": 50.5, "max_lon": 52.5},
    "Dubai":       {"min_lat": 24.5, "max_lat": 25.8, "min_lon": 54.5, "max_lon": 56.0},
    "Riyadh":      {"min_lat": 24.0, "max_lat": 25.5, "min_lon": 46.0, "max_lon": 47.5},
    "Isfahan":     {"min_lat": 32.0, "max_lat": 33.2, "min_lon": 51.0, "max_lon": 52.5},
    "Basra":       {"min_lat": 30.0, "max_lat": 31.0, "min_lon": 47.0, "max_lon": 48.5},
    "Kuwait City": {"min_lat": 28.8, "max_lat": 29.8, "min_lon": 47.5, "max_lon": 48.5},
    "Doha":        {"min_lat": 24.8, "max_lat": 25.7, "min_lon": 51.0, "max_lon": 51.8},
    "Abu Dhabi":   {"min_lat": 24.0, "max_lat": 25.0, "min_lon": 53.8, "max_lon": 55.0},
    "Manama":      {"min_lat": 25.9, "max_lat": 26.5, "min_lon": 50.2, "max_lon": 50.9},
}


@shared_task(bind=True, max_retries=2)
def fetch_tropomi_no2(self):
    """
    Fetch Sentinel-5P TROPOMI tropospheric NO2 column density for Gulf cities.
    Independent power generation proxy — corroborates nightlight grid collapse.
    """
    from pipeline.clients.tropomi import fetch_no2_for_aoi
    logger.info("Starting TROPOMI NO2 fetch")

    today = date.today()
    # TROPOMI has ~1-3 day processing lag
    target_date = today - timedelta(days=2)

    city_aois = {
        aoi.name: aoi
        for aoi in AreaOfInterest.objects.filter(category="city").exclude(country="New Zealand")
    }
    processed = 0
    dl_dir = os.path.join("/tmp", "satint_tropomi", target_date.isoformat())

    for city_name, bbox in _NO2_CITY_BOXES.items():
        aoi = city_aois.get(city_name)
        if not aoi:
            continue
        if NO2Reading.objects.filter(aoi=aoi, date=target_date).exists():
            continue

        try:
            result = fetch_no2_for_aoi(city_name, bbox, target_date, dl_dir)
            if not result or result.get("mean_no2") is None:
                continue

            # Compute baseline
            baseline_qs = NO2Reading.objects.filter(
                aoi=aoi,
                date__range=(BASELINE_START, BASELINE_END),
            ).values_list("mean_no2", flat=True)
            baseline = sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
            pct_change = None
            if baseline and baseline > 0:
                pct_change = (result["mean_no2"] - baseline) / baseline * 100

            NO2Reading.objects.update_or_create(
                aoi=aoi,
                date=target_date,
                defaults={
                    "mean_no2": result["mean_no2"],
                    "median_no2": result.get("median_no2"),
                    "baseline_no2": baseline,
                    "pct_change": pct_change,
                    "pixel_count": result.get("pixel_count", 0),
                    "cloud_fraction": result.get("cloud_fraction", 0),
                },
            )
            processed += 1
            logger.info(
                "NO2 %s %s: %.1f µmol/m² (pct=%s)",
                city_name, target_date, result["mean_no2"],
                f"{pct_change:+.1f}%" if pct_change is not None else "no baseline",
            )
        except Exception as exc:
            logger.error("NO2 fetch failed for %s: %s", city_name, exc)

    # Cleanup
    import shutil
    try:
        shutil.rmtree(dl_dir, ignore_errors=True)
    except OSError:
        pass

    logger.info("TROPOMI NO2 complete: %d readings", processed)
    return {"date": target_date.isoformat(), "processed": processed}


# Countries to monitor for internet outages
_MONITORED_COUNTRIES = [
    "Iran", "United Arab Emirates", "Saudi Arabia", "Qatar",
    "Kuwait", "Iraq", "Bahrain",
]


@shared_task(bind=True, max_retries=2)
def fetch_internet_connectivity(self):
    """
    Fetch IODA internet connectivity data for Gulf countries.
    Independent grid collapse corroboration — if nightlights drop, internet should too.
    """
    from pipeline.clients.ioda import fetch_connectivity_for_country
    logger.info("Starting internet connectivity fetch")

    today = date.today()
    target_date = today - timedelta(days=1)  # yesterday (data needs to settle)
    processed = 0

    for country_name in _MONITORED_COUNTRIES:
        if InternetOutage.objects.filter(country=country_name, date=target_date).exists():
            continue

        try:
            result = fetch_connectivity_for_country(country_name, target_date)
            if not result:
                continue

            # Compute baseline
            baseline_qs = InternetOutage.objects.filter(
                country=country_name,
                date__range=(BASELINE_START, BASELINE_END),
            ).values_list("overall_connectivity", flat=True)
            baseline = sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
            pct_change = None
            if baseline and baseline > 0:
                pct_change = (result["overall_connectivity"] - baseline) / baseline * 100

            InternetOutage.objects.update_or_create(
                country=country_name,
                date=target_date,
                defaults={
                    "ioda_bgp": result.get("ioda_connectivity"),
                    "ioda_active_probing": result.get("ioda_min"),
                    "cloudflare_traffic": result.get("cloudflare_traffic"),
                    "overall_connectivity": result["overall_connectivity"],
                    "baseline_connectivity": baseline,
                    "pct_change": pct_change,
                },
            )
            processed += 1
            logger.info(
                "Internet %s %s: connectivity=%.2f (pct=%s)",
                country_name, target_date, result["overall_connectivity"],
                f"{pct_change:+.1f}%" if pct_change is not None else "no baseline",
            )
        except Exception as exc:
            logger.error("Internet fetch failed for %s: %s", country_name, exc)

    logger.info("Internet connectivity complete: %d countries", processed)
    return {"date": target_date.isoformat(), "processed": processed}


# Airport ICAO codes grouped by region
_GULF_AIRPORTS = {
    "Tehran Imam Khomeini": {"icao": "OIIE", "country": "Iran"},
    "Tehran Mehrabad": {"icao": "OIII", "country": "Iran"},
    "Dubai International": {"icao": "OMDB", "country": "United Arab Emirates"},
    "Abu Dhabi": {"icao": "OMAA", "country": "United Arab Emirates"},
    "Doha Hamad": {"icao": "OTHH", "country": "Qatar"},
    "Kuwait International": {"icao": "OKBK", "country": "Kuwait"},
    "Bahrain International": {"icao": "OBBI", "country": "Bahrain"},
    "Riyadh King Khalid": {"icao": "OERK", "country": "Saudi Arabia"},
    "Isfahan": {"icao": "OIFM", "country": "Iran"},
    "Basra": {"icao": "ORMM", "country": "Iraq"},
}

_NZ_AIRPORTS_ADSB = {
    "Auckland": {"icao": "NZAA", "country": "New Zealand"},
    "Queenstown": {"icao": "NZQN", "country": "New Zealand"},
    "Wanaka": {"icao": "NZWF", "country": "New Zealand"},
}


@shared_task(bind=True, max_retries=2)
def fetch_flight_activity(self):
    """
    Fetch daily flight counts from OpenSky Network for Gulf + NZ airports.
    Gulf collapse + NZ private jet arrivals — both sides of the migration thesis.
    """
    from pipeline.clients.opensky import count_daily_flights
    logger.info("Starting OpenSky flight activity fetch")

    today = date.today()
    target_date = today - timedelta(days=1)  # yesterday (complete data)
    all_airports = {**_GULF_AIRPORTS, **_NZ_AIRPORTS_ADSB}
    processed = 0

    for airport_name, info in all_airports.items():
        icao = info["icao"]
        if FlightActivity.objects.filter(airport_icao=icao, date=target_date).exists():
            continue

        try:
            result = count_daily_flights(icao, target_date)
            if not result:
                continue

            # Compute baseline
            baseline_qs = FlightActivity.objects.filter(
                airport_icao=icao,
                date__range=(BASELINE_START, BASELINE_END),
            ).values_list("total_movements", flat=True)
            baseline = sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
            pct_change = None
            if baseline and baseline > 0:
                pct_change = (result["total_movements"] - baseline) / baseline * 100

            FlightActivity.objects.update_or_create(
                airport_icao=icao,
                date=target_date,
                defaults={
                    "airport_name": airport_name,
                    "arrivals": result["arrivals"],
                    "departures": result["departures"],
                    "total_movements": result["total_movements"],
                    "baseline_movements": baseline,
                    "pct_change": pct_change,
                    "country": info["country"],
                },
            )
            processed += 1
            logger.info(
                "Flights %s (%s) %s: %d movements (pct=%s)",
                airport_name, icao, target_date, result["total_movements"],
                f"{pct_change:+.1f}%" if pct_change is not None else "no baseline",
            )
        except Exception as exc:
            logger.error("Flight fetch failed for %s: %s", airport_name, exc)

    logger.info("Flight activity complete: %d airports", processed)
    return {"date": target_date.isoformat(), "processed": processed}


@shared_task(bind=True, max_retries=2)
def fetch_gdelt_events(self):
    """
    Fetch GDELT crisis event counts for Gulf countries.
    Ground-truth narrative layer — protests, shortages, displacement.
    """
    from pipeline.clients.gdelt import fetch_crisis_summary
    logger.info("Starting GDELT event fetch")

    today = date.today()
    target_date = today - timedelta(days=1)
    processed = 0

    for country_name in _MONITORED_COUNTRIES:
        if GDELTEventCount.objects.filter(country=country_name, date=target_date).exists():
            continue

        try:
            result = fetch_crisis_summary(country_name, target_date)
            if not result:
                continue

            GDELTEventCount.objects.update_or_create(
                country=country_name,
                date=target_date,
                defaults={
                    "power_outage": result.get("power_outage", 0),
                    "water_shortage": result.get("water_shortage", 0),
                    "fuel_shortage": result.get("fuel_shortage", 0),
                    "food_shortage": result.get("food_shortage", 0),
                    "protest": result.get("protest", 0),
                    "refugee": result.get("refugee", 0),
                    "infrastructure_damage": result.get("infrastructure_damage", 0),
                    "economic_impact": result.get("economic_impact", 0),
                    "total_crisis_events": result.get("total_crisis_events", 0),
                },
            )
            processed += 1
            logger.info(
                "GDELT %s %s: %d total crisis events",
                country_name, target_date, result.get("total_crisis_events", 0),
            )
        except Exception as exc:
            logger.error("GDELT fetch failed for %s: %s", country_name, exc)

    logger.info("GDELT events complete: %d countries", processed)
    return {"date": target_date.isoformat(), "processed": processed}


# Infrastructure AOIs to track thermal signatures
_THERMAL_SIGNATURE_RADIUS_KM = 5.0  # detection radius around known infrastructure


@shared_task(bind=True, max_retries=2)
def track_thermal_signatures(self):
    """
    Check if known infrastructure sites show expected thermal signatures.
    Missing thermal activity at a normally-hot facility = plant offline.
    """
    logger.info("Starting thermal signature tracking")
    today = date.today()
    cutoff_24h = timezone.now() - timedelta(hours=24)
    processed = 0

    infra_aois = AreaOfInterest.objects.filter(category="infrastructure")

    for aoi in infra_aois:
        if ThermalSignature.objects.filter(aoi=aoi, date=today).exists():
            continue

        try:
            lon, lat = aoi.geometry.coords
            from django.contrib.gis.measure import D
            from django.contrib.gis.geos import Point as GEOSPoint
            infra_point = GEOSPoint(lon, lat, srid=4326)

            # Count thermal anomalies within radius in last 24h
            nearby_fires = ThermalAnomaly.objects.filter(
                detected_at__gte=cutoff_24h,
                point__distance_lte=(infra_point, D(km=_THERMAL_SIGNATURE_RADIUS_KM)),
            )
            fire_count = nearby_fires.count()
            max_frp = None
            if fire_count > 0:
                from django.db.models import Max
                max_frp = nearby_fires.aggregate(m=Max("frp"))["m"]

            # Compute baseline (pre-war average daily fire count within radius)
            baseline_qs = ThermalSignature.objects.filter(
                aoi=aoi,
                date__range=(BASELINE_START, BASELINE_END),
            ).values_list("fire_count", flat=True)
            baseline_count = (
                sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
            )

            # Classify facility type — determines fire interpretation
            facility_type = aoi.metadata.get("type", "")

            # FLARING facilities (oil, refinery, LNG): fires are NORMAL (gas flaring)
            #   - fires present at normal levels = operating
            #   - fires absent = shutdown/offline
            #   - fires WAY above baseline = possible strike/explosion
            is_flaring = facility_type in ("oil", "refinery", "lng")

            # NON-FLARING facilities (desal, power): fires are ABNORMAL
            #   - no fires = normal operation
            #   - fires present = damage/strike
            #   - high FRP = active fire at facility

            if is_flaring:
                profile = "flaring"
                if fire_count == 0:
                    status = "offline"
                    signature_present = False
                    damage_detected = False
                elif baseline_count and fire_count > baseline_count * 3 and max_frp and max_frp > 30:
                    # Way above normal + high intensity = strike/explosion
                    status = "damaged"
                    signature_present = True
                    damage_detected = True
                elif baseline_count and fire_count < baseline_count * 0.3:
                    # Well below normal flaring = degraded/partial shutdown
                    status = "degraded"
                    signature_present = True
                    damage_detected = False
                else:
                    status = "operating"
                    signature_present = True
                    damage_detected = False
            else:
                # Non-flaring (desalination, power station)
                profile = "non_flaring"
                if fire_count == 0:
                    status = "operating"  # no fires = normal for desal
                    signature_present = False
                    damage_detected = False
                elif max_frp and max_frp > 30:
                    # High-intensity fire at a facility that shouldn't have any
                    status = "damaged"
                    signature_present = True
                    damage_detected = True
                elif fire_count >= 3:
                    # Multiple fire detections = active damage
                    status = "damaged"
                    signature_present = True
                    damage_detected = True
                else:
                    # 1-2 low-intensity fires = possibly nearby, not necessarily damage
                    status = "degraded"
                    signature_present = True
                    damage_detected = False

            ThermalSignature.objects.update_or_create(
                aoi=aoi,
                date=today,
                defaults={
                    "facility_profile": profile,
                    "signature_present": signature_present,
                    "damage_detected": damage_detected,
                    "max_frp": max_frp,
                    "fire_count": fire_count,
                    "baseline_fire_count": baseline_count,
                    "status": status,
                },
            )
            processed += 1
            if damage_detected:
                logger.warning(
                    "THERMAL ALERT: %s — DAMAGE DETECTED (fires=%d, max_frp=%.1f MW, profile=%s)",
                    aoi.name, fire_count, max_frp or 0, profile,
                )
            elif is_flaring and not signature_present:
                logger.warning(
                    "THERMAL ALERT: %s — flaring facility OFFLINE (0 fires)",
                    aoi.name,
                )
        except Exception as exc:
            logger.error("Thermal signature error for %s: %s", aoi.name, exc)

    logger.info("Thermal signatures tracked: %d facilities", processed)
    return {"date": today.isoformat(), "processed": processed}


# SAR coherence: infrastructure sites to check for damage
_SAR_COHERENCE_TARGETS = {
    "Bandar Abbas": {"min_lat": 27.1, "max_lat": 27.3, "min_lon": 56.1, "max_lon": 56.5},
    "Ras Tanura": {"min_lat": 26.5, "max_lat": 26.8, "min_lon": 50.0, "max_lon": 50.3},
    "Abqaiq": {"min_lat": 25.8, "max_lat": 26.1, "min_lon": 49.5, "max_lon": 49.9},
    "Jebel Ali": {"min_lat": 24.9, "max_lat": 25.1, "min_lon": 54.9, "max_lon": 55.2},
}


@shared_task(bind=True, max_retries=1)
def fetch_sar_coherence(self):
    """
    Compute SAR intensity correlation between pre-war and post-war scenes
    at critical infrastructure sites to detect structural damage.
    """
    from pipeline.clients.sar_coherence import analyze_infrastructure_damage
    logger.info("Starting SAR coherence change detection")

    processed = {}
    for site_name, bbox in _SAR_COHERENCE_TARGETS.items():
        aoi = AreaOfInterest.objects.filter(
            name__icontains=site_name.split()[0],
            category="infrastructure",
        ).first()
        if not aoi:
            logger.debug("No AOI found for coherence target: %s", site_name)
            continue

        # Skip if already computed
        if SARCoherenceChange.objects.filter(aoi=aoi).exists():
            continue

        try:
            cache_dir = os.path.join("/tmp/satint_sar_coherence", site_name.replace(" ", "_"))
            result = analyze_infrastructure_damage(site_name, bbox, cache_dir)

            if not result:
                continue

            SARCoherenceChange.objects.update_or_create(
                aoi=aoi,
                pre_date=result.get("pre_date", date(2026, 2, 15)),
                post_date=result.get("post_date", date.today()),
                defaults={
                    "mean_correlation": result["mean_correlation"],
                    "low_correlation_fraction": result["low_correlation_fraction"],
                    "change_area_km2": result.get("change_area_km2", 0),
                    "pixel_count": result.get("pixel_count", 0),
                    "pre_scene_id": result.get("pre_scene_id", ""),
                    "post_scene_id": result.get("post_scene_id", ""),
                },
            )
            processed[site_name] = {
                "mean_correlation": result["mean_correlation"],
                "change_fraction": result["low_correlation_fraction"],
            }
            logger.info(
                "SAR coherence %s: corr=%.2f, change=%.1f%%",
                site_name, result["mean_correlation"],
                result["low_correlation_fraction"] * 100,
            )
        except Exception as exc:
            logger.error("SAR coherence error for %s: %s", site_name, exc)

    return {"processed": processed}


@shared_task(bind=True, max_retries=2)
def fetch_grace_groundwater(self):
    """
    Fetch GRACE-FO groundwater anomaly data for Gulf regions.
    Monthly, coarse — tracks aquifer stress when desalination fails.
    """
    from pipeline.clients.grace import fetch_groundwater_for_region, GROUNDWATER_REGIONS
    logger.info("Starting GRACE groundwater fetch")

    today = date.today()
    # GRACE data has ~2-3 month lag; fetch the most recent available month
    target_month = date(today.year, today.month, 1) - timedelta(days=90)
    target_month = date(target_month.year, target_month.month, 1)

    processed = 0
    dl_dir = os.path.join("/tmp", "satint_grace")

    for region_name, bbox in GROUNDWATER_REGIONS.items():
        if GroundwaterAnomaly.objects.filter(
            region_name=region_name, month=target_month
        ).exists():
            continue

        try:
            result = fetch_groundwater_for_region(
                region_name, bbox, target_month, dl_dir
            )
            if not result:
                continue

            GroundwaterAnomaly.objects.update_or_create(
                region_name=region_name,
                month=target_month,
                defaults={
                    "mean_ewt_cm": result["mean_ewt_cm"],
                    "baseline_ewt_cm": result.get("baseline_ewt_cm"),
                    "anomaly_cm": result.get("anomaly_cm"),
                    "min_ewt_cm": result.get("min_ewt_cm"),
                    "max_ewt_cm": result.get("max_ewt_cm"),
                    "pixel_count": result.get("pixel_count", 0),
                },
            )
            processed += 1
            logger.info(
                "GRACE %s %s: EWT=%.1f cm (anomaly=%s)",
                region_name, target_month,
                result["mean_ewt_cm"],
                f"{result.get('anomaly_cm', 0):+.1f} cm"
                if result.get("anomaly_cm") is not None else "no baseline",
            )
        except Exception as exc:
            logger.error("GRACE fetch failed for %s: %s", region_name, exc)

    logger.info("GRACE groundwater complete: %d regions", processed)
    return {"month": target_month.isoformat(), "processed": processed}


# ---------------------------------------------------------------------------
# Enhanced compound risk — integrate new data sources
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=2)
def calculate_enhanced_compound_risk(self):
    """
    Enhanced compound risk calculation incorporating all data sources:
    nightlights, fires, trade flow, NO2, internet, flights, GDELT events,
    and thermal signature status.
    """
    logger.info("Calculating enhanced compound risk indicators")
    today = date.today()

    # Pre-fetch shared scores
    # Trade flow: prefer CommercialTransit (OSINT-verified), fall back to SAR (non-military)
    commercial_changes = list(
        CommercialTransit.objects.filter(
            date__gte=today - timedelta(days=7),
            chokepoint="hormuz",
        )
        .exclude(pct_change=None)
        .values_list("pct_change", flat=True)
    )
    if commercial_changes:
        avg_chokepoint_change = sum(commercial_changes) / len(commercial_changes)
    else:
        sar_changes = list(
            SARVesselDetection.objects.filter(
                date__gte=today - timedelta(days=7),
                chokepoint__category="chokepoint",
                is_military=False,
            )
            .exclude(pct_change=None)
            .values_list("pct_change", flat=True)
        )
        avg_chokepoint_change = sum(sar_changes) / len(sar_changes) if sar_changes else 0

    city_aois = AreaOfInterest.objects.filter(category="city").exclude(country="New Zealand")
    cutoff_48h = timezone.now() - timedelta(hours=48)
    updated = 0

    for aoi in city_aois:
        try:
            # --- Nightlight score (same as before) ---
            nl_obs = (
                NightlightObservation.objects.filter(
                    aoi=aoi, date__gte=today - timedelta(days=20),
                )
                .exclude(pct_change=None)
                .order_by("-date")
                .first()
            )
            pct = nl_obs.pct_change if nl_obs else 0
            nightlight_score = _sigmoid_score(-pct, 30, steepness=0.08)

            # --- Fire activity score ---
            lon, lat = aoi.geometry.coords
            from django.contrib.gis.measure import D
            from django.contrib.gis.geos import Point as GEOSPoint
            city_point = GEOSPoint(lon, lat, srid=4326)
            fire_count = ThermalAnomaly.objects.filter(
                detected_at__gte=cutoff_48h,
                nearest_infrastructure__isnull=False,
                point__distance_lte=(city_point, D(km=100)),
            ).count()
            fire_activity_score = _sigmoid_score(fire_count, 5, steepness=0.4)

            # --- Trade flow score ---
            trade_flow_score = _sigmoid_score(-avg_chokepoint_change, 20, steepness=0.1)

            # --- NO2 score (NEW) ---
            no2_obs = (
                NO2Reading.objects.filter(
                    aoi=aoi, date__gte=today - timedelta(days=7),
                )
                .exclude(pct_change=None)
                .order_by("-date")
                .first()
            )
            no2_pct = no2_obs.pct_change if no2_obs else 0
            # NO2 drop = generation collapse → higher risk score
            no2_score = _sigmoid_score(-no2_pct, 30, steepness=0.08)

            # --- Internet score (NEW) ---
            inet = (
                InternetOutage.objects.filter(
                    country=aoi.country,
                    date__gte=today - timedelta(days=3),
                )
                .order_by("-date")
                .first()
            )
            inet_connectivity = inet.overall_connectivity if inet else 1.0
            # Low connectivity = high risk
            internet_score = _sigmoid_score(1.0 - inet_connectivity, 0.3, steepness=8.0)

            # --- Flight score (NEW) ---
            # Find airports in this country
            flight_obs = (
                FlightActivity.objects.filter(
                    country=aoi.country,
                    date__gte=today - timedelta(days=3),
                )
                .exclude(pct_change=None)
                .values_list("pct_change", flat=True)
            )
            flight_changes = list(flight_obs)
            avg_flight_pct = sum(flight_changes) / len(flight_changes) if flight_changes else 0
            # Flight activity drop = collapse
            flight_score = _sigmoid_score(-avg_flight_pct, 30, steepness=0.06)

            # --- GDELT score (NEW) ---
            gdelt = (
                GDELTEventCount.objects.filter(
                    country=aoi.country,
                    date__gte=today - timedelta(days=3),
                )
                .order_by("-date")
                .first()
            )
            crisis_events = gdelt.total_crisis_events if gdelt else 0
            gdelt_score = _sigmoid_score(crisis_events, 20, steepness=0.15)

            # --- Thermal signature score (NEW) ---
            # Count infrastructure going offline near this city
            offline_count = ThermalSignature.objects.filter(
                aoi__geometry__distance_lte=(city_point, D(km=200)),
                date__gte=today - timedelta(days=2),
                status="offline",
            ).count()
            thermal_sig_score = _sigmoid_score(offline_count, 2, steepness=1.0)

            # --- Enhanced compound risk (weighted) ---
            compound_risk = round(
                nightlight_score * 0.20
                + fire_activity_score * 0.15
                + trade_flow_score * 0.15
                + no2_score * 0.12
                + internet_score * 0.12
                + flight_score * 0.10
                + gdelt_score * 0.08
                + thermal_sig_score * 0.08,
                4,
            )

            if compound_risk >= 0.8:
                alert_level = "emergency"
            elif compound_risk >= 0.6:
                alert_level = "critical"
            elif compound_risk >= 0.4:
                alert_level = "high"
            elif compound_risk >= 0.2:
                alert_level = "elevated"
            else:
                alert_level = "normal"

            CompoundRiskIndicator.objects.update_or_create(
                aoi=aoi,
                date=today,
                defaults={
                    "nightlight_score": nightlight_score,
                    "fire_activity_score": fire_activity_score,
                    "trade_flow_score": trade_flow_score,
                    "compound_risk": compound_risk,
                    "alert_level": alert_level,
                },
            )
            updated += 1

        except Exception as exc:
            logger.error("Enhanced risk error for %s: %s", aoi.name, exc)

    logger.info("Enhanced compound risk updated for %d cities", updated)
    return {"date": today.isoformat(), "updated": updated}


@shared_task(bind=True, max_retries=2)
def fetch_ndvi_vegetation(self):
    """
    Fetch Sentinel-2 NDVI for agricultural AOIs.
    Detects crop stress from water/fertiliser supply chain disruption.
    """
    logger.info("Starting NDVI vegetation index fetch")
    from pipeline.models import VegetationIndex

    client = Sentinel2Client()
    try:
        client.authenticate()
    except Exception as exc:
        logger.error("CDSE auth failed: %s", exc)
        raise self.retry(exc=exc, countdown=300)

    today = date.today()
    search_start = (today - timedelta(days=10)).isoformat()
    search_end = today.isoformat()

    ag_aois = AreaOfInterest.objects.filter(category="agriculture")
    processed = 0

    import tempfile
    dl_dir = os.path.join(tempfile.gettempdir(), "satint_ndvi")

    for aoi in ag_aois:
        try:
            # Get bbox from geometry
            extent = aoi.geometry.extent  # (xmin, ymin, xmax, ymax)
            bbox = {
                "min_lon": extent[0], "min_lat": extent[1],
                "max_lon": extent[2], "max_lat": extent[3],
            }

            products = client.search_scenes(bbox, search_start, search_end)
            if not products:
                continue

            product = products[0]
            scene_date = client.get_scene_date(product)
            if not scene_date:
                continue

            if VegetationIndex.objects.filter(aoi=aoi, date=scene_date).exists():
                continue

            band_files = client.download_scene_bands(
                product, dl_dir, bands=("B04", "B08", "SCL")
            )
            b04_path = band_files.get("B04")
            b08_path = band_files.get("B08")
            scl_path = band_files.get("SCL")

            if not b04_path or not b08_path:
                continue

            # Compute NDVI = (B08 - B04) / (B08 + B04)
            import rasterio
            from pyproj import Transformer
            from rasterio.windows import from_bounds

            with rasterio.open(b08_path) as nir_src:
                src_crs = nir_src.crs
                if src_crs and not src_crs.is_geographic:
                    transformer = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
                    left, bottom = transformer.transform(bbox["min_lon"], bbox["min_lat"])
                    right, top = transformer.transform(bbox["max_lon"], bbox["max_lat"])
                else:
                    left, bottom = bbox["min_lon"], bbox["min_lat"]
                    right, top = bbox["max_lon"], bbox["max_lat"]

                window = from_bounds(
                    left=left, bottom=bottom, right=right, top=top,
                    transform=nir_src.transform,
                )
                import numpy as np
                nir = nir_src.read(1, window=window).astype(np.float32)

            with rasterio.open(b04_path) as red_src:
                red_window = from_bounds(
                    left=left, bottom=bottom, right=right, top=top,
                    transform=red_src.transform,
                )
                red = red_src.read(1, window=red_window).astype(np.float32)

            # Ensure same shape
            min_r = min(nir.shape[0], red.shape[0])
            min_c = min(nir.shape[1], red.shape[1])
            nir = nir[:min_r, :min_c]
            red = red[:min_r, :min_c]

            denom = nir + red
            ndvi = np.where(denom > 0, (nir - red) / denom, 0)

            # Cloud mask from SCL if available
            cloud_fraction = 0.0
            if scl_path and os.path.exists(scl_path):
                try:
                    with rasterio.open(scl_path) as scl_src:
                        scl_crs = scl_src.crs
                        if scl_crs and not scl_crs.is_geographic:
                            scl_tf = Transformer.from_crs("EPSG:4326", scl_crs, always_xy=True)
                            sl, sb = scl_tf.transform(bbox["min_lon"], bbox["min_lat"])
                            sr, st = scl_tf.transform(bbox["max_lon"], bbox["max_lat"])
                        else:
                            sl, sb = bbox["min_lon"], bbox["min_lat"]
                            sr, st = bbox["max_lon"], bbox["max_lat"]
                        scl_window = from_bounds(
                            left=sl, bottom=sb, right=sr, top=st,
                            transform=scl_src.transform,
                        )
                        scl_arr = scl_src.read(1, window=scl_window)
                        clear = np.isin(scl_arr, [4, 5, 6])  # vegetation, bare, water
                        cloud_fraction = 1.0 - float(np.sum(clear)) / float(clear.size)
                except Exception:
                    pass

            mean_ndvi = float(np.nanmean(ndvi))

            # Baseline from same period prior year
            baseline_qs = VegetationIndex.objects.filter(
                aoi=aoi,
                date__range=(BASELINE_START, BASELINE_END),
            ).values_list("mean_ndvi", flat=True)
            baseline = sum(baseline_qs) / len(baseline_qs) if baseline_qs else None
            pct_change = None
            if baseline and baseline > 0:
                pct_change = (mean_ndvi - baseline) / baseline * 100

            VegetationIndex.objects.update_or_create(
                aoi=aoi,
                date=scene_date,
                defaults={
                    "mean_ndvi": mean_ndvi,
                    "baseline_ndvi": baseline,
                    "pct_change": pct_change,
                    "cloud_fraction": cloud_fraction,
                },
            )
            processed += 1
            logger.info(
                "NDVI %s %s: %.3f (pct=%s)",
                aoi.name, scene_date, mean_ndvi,
                f"{pct_change:+.1f}%" if pct_change is not None else "no baseline",
            )
        except Exception as exc:
            logger.error("NDVI error for %s: %s", aoi.name, exc)

    logger.info("NDVI processing complete: %d AOIs", processed)
    return {"processed": processed}


@shared_task(bind=True, max_retries=2)
def calculate_enhanced_migration_pressure(self):
    """
    Enhanced NZ migration pressure including OpenSky flight data.
    Gulfstream landing at NZAA is a much stronger signal than marina pixels.
    """
    logger.info("Calculating enhanced NZ migration pressure")
    today = date.today()
    lookback = today - timedelta(days=14)

    # Gulf push factor
    gulf_risks = list(
        CompoundRiskIndicator.objects.filter(
            date__gte=today - timedelta(days=7),
            aoi__country__in=["UAE", "Qatar", "Bahrain", "Kuwait", "Saudi Arabia", "Iran"],
        ).values_list("compound_risk", flat=True)
    )
    gulf_push = sum(gulf_risks) / len(gulf_risks) if gulf_risks else 0.0

    nz_cities = AreaOfInterest.objects.filter(category="city", country="New Zealand")
    updated = 0

    for aoi in nz_cities:
        try:
            city_name = aoi.name

            # Marina score (same as before)
            if city_name == "Auckland":
                marina_names = ["Viaduct Harbour", "Westhaven Marina", "Silo Marina", "Half Moon Bay Marina"]
            elif city_name == "Queenstown":
                marina_names = ["Queenstown Marina"]
            else:
                marina_names = []

            marina_changes = list(
                OpticalAssetCount.objects.filter(
                    aoi__name__in=marina_names, date__gte=lookback, asset_type="vessel",
                ).exclude(pct_change=None).values_list("pct_change", flat=True)
            )
            sar_marina_changes = list(
                SARVesselDetection.objects.filter(
                    chokepoint__name__in=marina_names, date__gte=lookback,
                ).exclude(pct_change=None).values_list("pct_change", flat=True)
            )
            all_marina = marina_changes + sar_marina_changes
            avg_marina_pct = sum(all_marina) / len(all_marina) if all_marina else 0
            marina_score = _sigmoid_score(avg_marina_pct, 25, steepness=0.06)

            # Airport score from optical
            if city_name == "Auckland":
                airport_names = ["Auckland GA Apron"]
            elif city_name == "Queenstown":
                airport_names = ["Queenstown Airport", "Wanaka Airport"]
            else:
                airport_names = []

            airport_changes = list(
                OpticalAssetCount.objects.filter(
                    aoi__name__in=airport_names, date__gte=lookback, asset_type="aircraft",
                ).exclude(pct_change=None).values_list("pct_change", flat=True)
            )
            avg_airport_pct = sum(airport_changes) / len(airport_changes) if airport_changes else 0
            optical_airport_score = _sigmoid_score(avg_airport_pct, 25, steepness=0.06)

            # OpenSky ADS-B flight score (NEW — much stronger signal)
            if city_name == "Auckland":
                adsb_icaos = ["NZAA"]
            elif city_name == "Queenstown":
                adsb_icaos = ["NZQN", "NZWF"]
            else:
                adsb_icaos = []

            flight_changes = list(
                FlightActivity.objects.filter(
                    airport_icao__in=adsb_icaos, date__gte=lookback,
                ).exclude(pct_change=None).values_list("pct_change", flat=True)
            )
            avg_flight_pct = sum(flight_changes) / len(flight_changes) if flight_changes else 0
            adsb_airport_score = _sigmoid_score(avg_flight_pct, 15, steepness=0.08)

            # Combined airport score: weight ADS-B higher (direct measurement)
            airport_score = adsb_airport_score * 0.7 + optical_airport_score * 0.3

            # Nightlight score
            nl_obs = (
                NightlightObservation.objects.filter(aoi=aoi, date__gte=lookback)
                .exclude(pct_change=None)
                .order_by("-date")
                .first()
            )
            nl_pct = nl_obs.pct_change if nl_obs else 0
            nightlight_score = _sigmoid_score(nl_pct, 10, steepness=0.1)

            # SAR approach vessels
            if city_name == "Auckland":
                approach_names = ["NZ North Approach", "NZ East Approach"]
            else:
                approach_names = []

            approach_changes = list(
                SARVesselDetection.objects.filter(
                    chokepoint__name__in=approach_names, date__gte=lookback,
                ).exclude(pct_change=None).values_list("pct_change", flat=True)
            )
            avg_approach_pct = sum(approach_changes) / len(approach_changes) if approach_changes else 0
            sar_vessel_score = _sigmoid_score(avg_approach_pct, 20, steepness=0.08)

            # Gulf push
            gulf_push_score = min(gulf_push, 1.0)

            # Enhanced weighted composite
            migration_pressure = round(
                marina_score * 0.20
                + airport_score * 0.30      # increased weight — ADS-B is strongest signal
                + nightlight_score * 0.10
                + sar_vessel_score * 0.15
                + gulf_push_score * 0.25,   # increased — this is the thesis driver
                4,
            )

            if migration_pressure >= 0.7:
                pressure_level = "surge"
            elif migration_pressure >= 0.4:
                pressure_level = "high"
            elif migration_pressure >= 0.2:
                pressure_level = "elevated"
            else:
                pressure_level = "baseline"

            MigrationPressureIndicator.objects.update_or_create(
                aoi=aoi,
                date=today,
                defaults={
                    "marina_score": marina_score,
                    "airport_score": airport_score,
                    "nightlight_score": nightlight_score,
                    "sar_vessel_score": sar_vessel_score,
                    "gulf_push_score": gulf_push_score,
                    "migration_pressure": migration_pressure,
                    "pressure_level": pressure_level,
                },
            )
            updated += 1
            logger.info(
                "Enhanced migration %s: pressure=%.3f (%s)",
                city_name, migration_pressure, pressure_level,
            )
        except Exception as exc:
            logger.error("Enhanced migration error for %s: %s", aoi.name, exc)

    logger.info("Enhanced migration pressure: %d NZ locations", updated)
    return {"date": today.isoformat(), "updated": updated}


# ---------------------------------------------------------------------------
# NZ Fuel Security Indicator
# ---------------------------------------------------------------------------

# MSO minimums (since Jan 2025)
_MSO_MINIMUMS = {"petrol": 28.0, "diesel": 21.0, "jet": 24.0}

# Industry cascade parameters: (fuel_type, impact_threshold_above_mso, elasticity, priority, label, effect)
_INDUSTRY_CASCADE = [
    ("jet", 5, "low", "medium", "Aviation", "Route cuts, frequency reduction"),
    ("diesel", 3, "very_low", "low", "Fishing", "Fleet grounding, seafood price spike"),
    ("diesel", 7, "low", "high", "Freight", "Delivery delays, essential goods priority"),
    ("diesel", 5, "very_low", "medium", "Agriculture", "Harvest delays, machinery idle"),
    ("diesel", 10, "medium", "low", "Construction", "Project delays, bitumen shortage"),
    ("petrol", 3, "high", "low", "Commuter", "Price rationing, demand destruction"),
]

# Second/third order effects: (trigger_industry, lag_weeks, label, explanation)
_SECOND_ORDER_EFFECTS = [
    ("Freight", 14, 2, "Food price inflation", "Freight disruption cascades to retail food prices"),
    ("Aviation", 21, 3, "Tourism contraction", "Reduced aviation capacity impacts tourism arrivals"),
    ("Agriculture", 14, 4, "Agricultural disruption", "Diesel shortage + fertiliser dependency via Hormuz"),
    ("Construction", 21, 4, "Construction halt", "Diesel shortage stalls projects, bitumen from oil refineries"),
    (None, 0, 2, "Emergency services strain", "Any fuel hitting MSO triggers emergency protocols"),
    (None, 0, 8, "GDP contraction", "3+ industries impacted signals broader economic contraction"),
]


@shared_task(bind=True, max_retries=2)
def calculate_fuel_security_indicator(self):
    """
    Calculate NZ fuel security compound indicator.
    Combines Hormuz disruption, price trends, stock levels,
    supply chain, demand signals, and GDELT narrative.
    """
    from pipeline.models import (
        FuelPriceObservation,
        FuelStockLevel,
        NZFuelSecurityIndicator,
    )

    logger.info("Calculating NZ fuel security indicator")
    today = date.today()

    # --- 1. Hormuz disruption score (30%) ---
    # Recency-weighted: most recent SAR reading counts most (weights: 0.6, 0.25, 0.15)
    hormuz_sar = list(
        SARVesselDetection.objects.filter(
            chokepoint__name__icontains="Hormuz",
            date__gte=today - timedelta(days=14),
        )
        .exclude(pct_change=None)
        .order_by("-date")
        .values_list("pct_change", flat=True)[:3]
    )
    if hormuz_sar:
        recency_weights = [0.6, 0.25, 0.15][:len(hormuz_sar)]
        w_total = sum(recency_weights)
        avg_hormuz_pct = sum(v * w for v, w in zip(hormuz_sar, recency_weights)) / w_total
    else:
        avg_hormuz_pct = 0
    # Negative pct_change = disruption
    hormuz_score = _sigmoid_score(-avg_hormuz_pct, 30, steepness=0.08)

    # --- 2. Price acceleration score (20%) ---
    latest_prices = FuelPriceObservation.objects.filter(
        date__gte=today - timedelta(days=14),
    ).exclude(pct_change=None).values_list("pct_change", flat=True)
    price_changes = list(latest_prices)
    avg_price_pct = sum(price_changes) / len(price_changes) if price_changes else 0
    price_score = _sigmoid_score(avg_price_pct, 10, steepness=0.15)

    # --- 3. Stock depletion score (25%) ---
    # Get latest stock levels
    from django.db.models import Max
    latest_stock_date = FuelStockLevel.objects.aggregate(d=Max("date"))["d"]
    stock_score = 0.0
    depletion_projections = {}
    min_days_to_mso = None

    if latest_stock_date:
        for fuel_type in ("petrol", "diesel", "jet"):
            onshore = FuelStockLevel.objects.filter(
                date=latest_stock_date, fuel_type=fuel_type, stock_type="onshore",
            ).first()
            on_water = FuelStockLevel.objects.filter(
                date=latest_stock_date, fuel_type=fuel_type, stock_type="on_water",
            ).first()

            if not onshore:
                continue

            mso = _MSO_MINIMUMS.get(fuel_type, 21)
            days_above_mso = onshore.days_of_supply - mso
            total_days = onshore.days_of_supply + (on_water.days_of_supply if on_water else 0)

            # Depletion model — calibrated against MBIE actuals (Mar 15 2026)
            hormuz_disruption_frac = max(0, -avg_hormuz_pct / 100) if hormuz_sar else 0
            nz_hormuz_dependency = 0.40
            resupply_reduction = hormuz_disruption_frac * nz_hormuz_dependency

            # Demand surge multiplier: panic buying accelerates consumption
            # NZ Herald Mar 15: Gull reported 15%+ demand surge, $3/L breached
            # Fuel demand elasticity is low — price rises cause initial panic buying
            # then demand destruction. Net effect ~10-15% at peak.
            # Scale: 0% price rise = 1.0x, 10% = 1.05x, 20% = 1.10x, 30%+ = 1.15x
            demand_surge = 1.0 + min(0.15, max(0, avg_price_pct) * 0.005)

            # Days elapsed since stock measurement
            days_elapsed = (today - latest_stock_date).days

            # Project current onshore stock
            # Net depletion = supply loss + excess demand
            # Supply loss: fraction of daily consumption not resupplied
            # Demand surge: fraction of extra consumption beyond normal
            supply_loss_rate = resupply_reduction
            demand_excess_rate = demand_surge - 1.0  # e.g. 0.15 = 15% extra
            net_daily_depletion = supply_loss_rate + demand_excess_rate

            if net_daily_depletion > 0:
                projected_onshore = onshore.days_of_supply - (days_elapsed * net_daily_depletion)
                projected_onshore = max(0, projected_onshore)
                projected_days_above_mso = projected_onshore - mso

                days_to_mso = max(0, projected_days_above_mso / net_daily_depletion)
            else:
                projected_onshore = onshore.days_of_supply
                projected_days_above_mso = days_above_mso
                days_to_mso = None

            # On-water adjustment: any significant Hormuz disruption forces
            # Cape of Good Hope rerouting (+14 days transit time)
            cape_delay = 14 if hormuz_disruption_frac > 0.10 else 0
            effective_on_water = max(0, (on_water.days_of_supply if on_water else 0) - cape_delay)

            # Store the actual daily depletion rate for cascade calculations
            daily_depletion_rate = net_daily_depletion

            depletion_projections[fuel_type] = {
                "onshore_days": round(onshore.days_of_supply, 1),
                "on_water_days": round(on_water.days_of_supply, 1) if on_water else None,
                "projected_onshore": round(projected_onshore, 1),
                "mso_minimum": mso,
                "days_above_mso": round(projected_days_above_mso, 1),
                "days_to_mso": round(days_to_mso, 1) if days_to_mso is not None else None,
                "effective_on_water": round(effective_on_water, 1),
                "cape_delay_days": cape_delay,
                "total_effective": round(projected_onshore + effective_on_water, 1),
                "daily_depletion_rate": round(daily_depletion_rate, 4),
                "supply_loss_rate": round(supply_loss_rate, 4),
                "demand_surge_multiplier": round(demand_surge, 3),
                "demand_excess_rate": round(demand_excess_rate, 4),
                "stock_measurement_date": latest_stock_date.isoformat(),
                "days_since_measurement": days_elapsed,
                "hormuz_disruption_fraction": round(hormuz_disruption_frac, 4),
                "nz_hormuz_dependency": nz_hormuz_dependency,
            }

            if days_to_mso is not None and (min_days_to_mso is None or days_to_mso < min_days_to_mso):
                min_days_to_mso = days_to_mso

        # Stock score: based on worst fuel type's margin above MSO
        worst_margin = min(
            (p["days_above_mso"] for p in depletion_projections.values()),
            default=30,
        )
        # 0 days above MSO = score 1.0, 30 days = score ~0
        stock_score = _sigmoid_score(-worst_margin, -10, steepness=0.15)

    # --- 4. Supply chain score (10%) — uses Hormuz as proxy ---
    supply_chain_score = hormuz_score * 0.8  # correlated but dampened

    # --- 5. Demand signal (10%) — NZ flights as proxy ---
    nz_flights = list(
        FlightActivity.objects.filter(
            country="New Zealand",
            date__gte=today - timedelta(days=7),
        ).exclude(pct_change=None).values_list("pct_change", flat=True)
    )
    avg_nz_flight_pct = sum(nz_flights) / len(nz_flights) if nz_flights else 0
    # Flight reduction = demand destruction / self-rationing
    demand_score = _sigmoid_score(-avg_nz_flight_pct, 15, steepness=0.1)

    # --- 6. GDELT narrative (5%) ---
    nz_gdelt = (
        GDELTEventCount.objects.filter(
            country="New Zealand",
            date__gte=today - timedelta(days=7),
        ).order_by("-date").first()
    )
    fuel_shortage_events = nz_gdelt.fuel_shortage if nz_gdelt else 0
    gdelt_score = _sigmoid_score(fuel_shortage_events, 5, steepness=0.5)

    # --- Composite score ---
    fuel_security_risk = round(
        hormuz_score * 0.30
        + stock_score * 0.25
        + price_score * 0.20
        + supply_chain_score * 0.10
        + demand_score * 0.10
        + gdelt_score * 0.05,
        4,
    )

    if fuel_security_risk >= 0.8:
        security_level = "rationing"
    elif fuel_security_risk >= 0.6:
        security_level = "critical"
    elif fuel_security_risk >= 0.4:
        security_level = "warning"
    elif fuel_security_risk >= 0.2:
        security_level = "watch"
    else:
        security_level = "normal"

    # Estimated rationing date
    estimated_rationing_date = None
    if min_days_to_mso is not None and min_days_to_mso < 365:
        estimated_rationing_date = today + timedelta(days=int(min_days_to_mso))

    # Industry cascade projections
    industry_cascade = []
    for fuel_type, threshold_above_mso, elasticity, priority, label, effect in _INDUSTRY_CASCADE:
        proj = depletion_projections.get(fuel_type, {})
        mso = _MSO_MINIMUMS.get(fuel_type, 21)
        target_stock = mso + threshold_above_mso
        current_projected = proj.get("projected_onshore", 0)
        rate = proj.get("daily_depletion_rate", 0)

        if rate > 0 and current_projected > target_stock:
            days_above = current_projected - target_stock
            days_to_impact = days_above / rate
        elif rate > 0:
            days_to_impact = 0  # already below threshold
        else:
            days_to_impact = None

        industry_cascade.append({
            "industry": label,
            "fuel_type": fuel_type,
            "impact_threshold": threshold_above_mso,
            "elasticity": elasticity,
            "priority": priority,
            "effect": effect,
            "days_to_impact": round(days_to_impact, 1) if days_to_impact is not None else None,
            "impact_date": (today + timedelta(days=int(days_to_impact))).isoformat() if days_to_impact is not None else None,
        })

    # Sort by days_to_impact (soonest first, None last)
    industry_cascade.sort(key=lambda x: x["days_to_impact"] if x["days_to_impact"] is not None else 9999)

    # Add cascade to depletion projections
    depletion_projections["industry_cascade"] = industry_cascade

    # Second-order effects
    second_order = []
    triggered_industries = [ic for ic in industry_cascade if ic["days_to_impact"] is not None and ic["days_to_impact"] < 60]
    for trigger_industry, trigger_days, lag_weeks, label, explanation in _SECOND_ORDER_EFFECTS:
        if trigger_industry is None:
            # Special triggers
            if label == "Emergency services strain":
                triggered = min_days_to_mso is not None and min_days_to_mso < 30
            elif label == "GDP contraction":
                triggered = len(triggered_industries) >= 3
            else:
                triggered = False
            source_days = min_days_to_mso if min_days_to_mso else None
        else:
            matching = [ic for ic in industry_cascade if ic["industry"] == trigger_industry]
            if matching and matching[0]["days_to_impact"] is not None and matching[0]["days_to_impact"] < trigger_days:
                triggered = True
                source_days = matching[0]["days_to_impact"]
            else:
                triggered = False
                source_days = matching[0]["days_to_impact"] if matching else None

        onset_days = (source_days + lag_weeks * 7) if source_days is not None else None

        second_order.append({
            "effect": label,
            "triggered": triggered,
            "trigger_industry": trigger_industry,
            "lag_weeks": lag_weeks,
            "explanation": explanation,
            "onset_days": round(onset_days, 0) if onset_days is not None else None,
            "onset_date": (today + timedelta(days=int(onset_days))).isoformat() if onset_days is not None else None,
            "severity": "high" if triggered else ("medium" if source_days is not None and source_days < 60 else "low"),
        })

    depletion_projections["second_order_effects"] = second_order

    NZFuelSecurityIndicator.objects.update_or_create(
        date=today,
        defaults={
            "hormuz_disruption": hormuz_score,
            "price_acceleration": price_score,
            "stock_depletion": stock_score,
            "supply_chain": supply_chain_score,
            "demand_signal": demand_score,
            "gdelt_narrative": gdelt_score,
            "fuel_security_risk": fuel_security_risk,
            "security_level": security_level,
            "estimated_days_to_mso": min_days_to_mso,
            "estimated_rationing_date": estimated_rationing_date,
            "depletion_projections": depletion_projections,
        },
    )

    logger.info(
        "NZ fuel security: risk=%.3f (%s), days_to_mso=%s",
        fuel_security_risk, security_level,
        f"{min_days_to_mso:.0f}" if min_days_to_mso else "n/a",
    )
    return {
        "date": today.isoformat(),
        "risk": fuel_security_risk,
        "level": security_level,
        "days_to_mso": min_days_to_mso,
    }


@shared_task(bind=True, max_retries=2)
def fetch_mbie_fuel_prices(self):
    """
    Attempt to fetch and ingest MBIE weekly fuel prices automatically.
    Falls back gracefully if MBIE blocks automated downloads.
    """
    from pipeline.clients.mbie_fuel import fetch_mbie_csv, parse_fuel_csv
    from pipeline.models import FuelPriceObservation
    from django.db.models import Avg

    logger.info("Attempting MBIE fuel price fetch")

    csv_text = fetch_mbie_csv()
    if csv_text is None:
        logger.warning("MBIE CSV download failed — manual CSV ingest required")
        return {"status": "download_failed"}

    records = parse_fuel_csv(csv_text)
    if not records:
        logger.warning("No records parsed from MBIE CSV")
        return {"status": "no_records"}

    war_start = date(2026, 2, 28)
    baselines = {}
    for fuel_type in ("91", "95", "diesel"):
        bl = FuelPriceObservation.objects.filter(
            fuel_type=fuel_type, date__lt=war_start,
        ).aggregate(avg=Avg("retail_price_nzd"))["avg"]
        if bl:
            baselines[fuel_type] = bl
        else:
            pre_war = [r["retail_price_nzd"] for r in records
                       if r["fuel_type"] == fuel_type and r["date"] < war_start]
            if pre_war:
                baselines[fuel_type] = sum(pre_war) / len(pre_war)

    saved = 0
    for r in records:
        baseline = baselines.get(r["fuel_type"])
        pct_change = None
        if baseline and baseline > 0:
            pct_change = round((r["retail_price_nzd"] - baseline) / baseline * 100, 2)

        _, created = FuelPriceObservation.objects.update_or_create(
            date=r["date"],
            fuel_type=r["fuel_type"],
            defaults={
                "retail_price_nzd": r["retail_price_nzd"],
                "import_cost_nzd": r["import_cost_nzd"],
                "margin_nzd": r["margin_nzd"],
                "baseline_price": baseline,
                "pct_change": pct_change,
            },
        )
        if created:
            saved += 1

    logger.info("MBIE fuel prices: %d new, %d total records", saved, len(records))
    return {"status": "ok", "new_records": saved, "total_parsed": len(records)}


@shared_task(bind=True, max_retries=2)
def fetch_commercial_transits(self):
    """
    Fetch commercial vessel transit counts from Windward Maritime Intelligence Daily.
    Windward publishes daily blog posts with AIS-confirmed crossing counts
    for Hormuz, Bab al-Mandeb, Suez, and Cape of Good Hope.
    """
    from pipeline.clients.windward import fetch_windward_daily

    logger.info("Fetching Windward commercial transit data")
    # Try yesterday (post usually covers prior day's crossings)
    target = date.today() - timedelta(days=1)

    data = fetch_windward_daily(target)
    if not data:
        logger.warning("No Windward data for %s", target)
        return {"date": str(target), "processed": 0}

    saved = 0
    for chokepoint, values in data.items():
        obj, created = CommercialTransit.objects.update_or_create(
            chokepoint=chokepoint,
            date=target,
            source="windward",
            defaults={
                "crossings": values["crossings"],
                "inbound": values.get("inbound"),
                "outbound": values.get("outbound"),
                "seven_day_avg": values.get("seven_day_avg"),
                "baseline_crossings": values["baseline"],
                "notes": "Auto-scraped from Windward Maritime Intelligence Daily",
            },
        )
        if created:
            saved += 1
        logger.info(
            "CommercialTransit %s %s: %d crossings (pct=%s%%)",
            chokepoint, target, values["crossings"], obj.pct_change,
        )

    return {"date": str(target), "processed": saved}
