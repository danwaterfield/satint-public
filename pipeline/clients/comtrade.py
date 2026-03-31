"""
UN Comtrade API client for mapping NZ trade dependencies.

Uses the free preview API (no auth required, 500 records/call).
Queries NZ imports by commodity and partner country to determine
Hormuz-exposed supply chains.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

COMTRADE_BASE = "https://comtradeapi.un.org/public/v1/preview/C"

# NZ reporter code
NZ_CODE = 554

# Countries whose exports transit Hormuz (oil producers + refiners dependent on Gulf crude)
HORMUZ_DEPENDENT_COUNTRIES = {
    # Direct Gulf exporters
    682: "Saudi Arabia",
    784: "United Arab Emirates",
    634: "Qatar",
    512: "Oman",
    414: "Kuwait",
    48:  "Bahrain",
    364: "Iran",
    368: "Iraq",
    # Refiners heavily dependent on Gulf crude (>40% of crude input from Gulf)
    702: "Singapore",       # ~70% of crude from Gulf
    410: "South Korea",     # ~70% from Gulf
    356: "India",           # ~60% from Gulf
    392: "Japan",           # ~80% from Gulf (less direct to NZ but significant)
    158: "Taiwan",          # ~70% from Gulf
    764: "Thailand",        # ~50% from Gulf
}

# Estimated Hormuz dependency fraction per refiner country
# (fraction of their crude input that transits Hormuz)
HORMUZ_CRUDE_DEPENDENCY = {
    682: 1.0,   # Saudi — all exports via Gulf/Hormuz or Red Sea
    784: 1.0,   # UAE
    634: 1.0,   # Qatar
    512: 1.0,   # Oman (some via Indian Ocean directly, but close enough)
    414: 1.0,   # Kuwait
    48:  1.0,   # Bahrain
    364: 1.0,   # Iran
    368: 0.8,   # Iraq (some via Turkey pipeline)
    702: 0.65,  # Singapore — ~65% of crude from Gulf
    410: 0.70,  # South Korea
    356: 0.55,  # India — diversified but still majority Gulf
    392: 0.80,  # Japan
    158: 0.70,  # Taiwan
    764: 0.45,  # Thailand
}

# HS commodity codes of interest
COMMODITY_CODES = {
    "2710": "Petroleum oils (refined)",
    "2709": "Crude petroleum",
    "2711": "Petroleum gases (LPG/LNG)",
    "31":   "Fertilisers",
    "3102": "Nitrogenous fertilisers",
    "3103": "Phosphatic fertilisers",
    "3104": "Potassic fertilisers",
    "3105": "Mineral/chemical fertilisers (mixed)",
    "29":   "Organic chemicals",
    "3901": "Polymers of ethylene (plastics)",
    "3902": "Polymers of propylene (plastics)",
}


def query_nz_imports(cmd_code, period="2024", freq="A"):
    """
    Query NZ imports for a commodity code, all partner countries.

    Returns list of dicts with partner info and trade values.
    """
    url = f"{COMTRADE_BASE}/{freq}/HS"
    params = {
        "reporterCode": NZ_CODE,
        "cmdCode": cmd_code,
        "flowCode": "M",  # imports
        "period": period,
        "includeDesc": "true",
        "maxRecords": 500,
    }

    try:
        resp = requests.get(url, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        records = data.get("data", [])
        logger.info("Comtrade: %d records for NZ imports of HS %s (%s)",
                     len(records), cmd_code, period)
        return records
    except Exception as e:
        logger.error("Comtrade query failed for HS %s: %s", cmd_code, e)
        return []


def calculate_hormuz_exposure(records):
    """
    Given Comtrade import records, calculate what fraction of NZ imports
    for this commodity are Hormuz-dependent.

    Returns dict with:
      - total_value_usd: total NZ imports
      - hormuz_exposed_value_usd: value from Hormuz-dependent sources
      - hormuz_exposure_pct: percentage
      - by_partner: breakdown by partner country
    """
    total_value = 0
    hormuz_exposed = 0
    by_partner = []

    for rec in records:
        partner_code = rec.get("partnerCode", 0)
        value = rec.get("primaryValue") or rec.get("cifvalue") or 0

        # Skip world aggregate and zero-value partners
        if partner_code == 0 or value <= 0:
            continue

        total_value += value

        dependency = HORMUZ_CRUDE_DEPENDENCY.get(partner_code, 0)
        exposed_value = value * dependency

        if dependency > 0:
            hormuz_exposed += exposed_value
            by_partner.append({
                "partner_code": partner_code,
                "partner": rec.get("partnerDesc", f"Code {partner_code}"),
                "partner_iso": rec.get("partnerISO", ""),
                "value_usd": round(value, 2),
                "hormuz_dependency": dependency,
                "exposed_value_usd": round(exposed_value, 2),
            })

    by_partner.sort(key=lambda x: x["exposed_value_usd"], reverse=True)

    return {
        "total_value_usd": round(total_value, 2),
        "hormuz_exposed_value_usd": round(hormuz_exposed, 2),
        "hormuz_exposure_pct": round(
            (hormuz_exposed / total_value * 100) if total_value > 0 else 0, 1
        ),
        "by_partner": by_partner,
    }


def map_nz_hormuz_dependencies(period="2024"):
    """
    Full NZ Hormuz dependency mapping across key commodities.

    Returns dict keyed by commodity code with exposure analysis.
    """
    results = {}

    for cmd_code, description in COMMODITY_CODES.items():
        logger.info("Querying NZ imports: %s (%s)", description, cmd_code)
        records = query_nz_imports(cmd_code, period=period)
        time.sleep(1)  # rate limiting courtesy

        if not records:
            results[cmd_code] = {
                "description": description,
                "error": "No data returned",
            }
            continue

        exposure = calculate_hormuz_exposure(records)
        exposure["description"] = description
        exposure["period"] = period
        exposure["hs_code"] = cmd_code
        results[cmd_code] = exposure

    # Calculate aggregate exposure
    total_all = sum(r.get("total_value_usd", 0) for r in results.values()
                    if "total_value_usd" in r)
    exposed_all = sum(r.get("hormuz_exposed_value_usd", 0) for r in results.values()
                      if "hormuz_exposed_value_usd" in r)

    results["_aggregate"] = {
        "description": "All tracked commodities",
        "total_value_usd": round(total_all, 2),
        "hormuz_exposed_value_usd": round(exposed_all, 2),
        "hormuz_exposure_pct": round(
            (exposed_all / total_all * 100) if total_all > 0 else 0, 1
        ),
    }

    return results
