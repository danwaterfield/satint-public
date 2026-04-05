"""
Gaspy live fuel price snapshot client.

Gaspy's public stats page is rendered from a Firebase Realtime Database
snapshot. We use the JSON endpoint directly so export_static can capture a
same-day NZ retail price reference without scraping rendered HTML.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

GASPY_STATS_JSON_URL = "https://gaspy-datamine-stats.firebaseio.com/.json"

_AVERAGE_KEY_MAP = {
    "91": "91",
    "95": "95",
    "98": "98",
    "100": "100",
    "Diesel": "diesel",
    "LPG": "lpg",
}


def fetch_gaspy_stats(timeout: int = 20) -> dict | None:
    """
    Fetch the live Gaspy stats snapshot.

    Returns a normalized dict such as:
        {
            "updated": "05 Apr 2026 @ 04:07PM",
            "station_count": 2462,
            "brand_count": 57,
            "confirmations_last_7_days": 95203,
            "user_count": 2074600,
            "averages": {
                "91": {
                    "retail_price_nzd": 3.4709,
                    "change_cents_28d": 84.14,
                    "change_pct_28d": 32.0,
                },
                ...
            },
            "top_91": [...],
        }
    """
    try:
        response = requests.get(
            GASPY_STATS_JSON_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; satint-pipeline/1.0)",
                "Accept": "application/json, text/plain, */*",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("Failed to fetch Gaspy stats: %s", exc)
        return None
    except ValueError as exc:
        logger.warning("Gaspy returned invalid JSON: %s", exc)
        return None

    datamine = payload.get("datamine") or {}
    gaspy = payload.get("gaspy") or {}
    averages = {}

    for raw_key, normalized_key in _AVERAGE_KEY_MAP.items():
        item = (datamine.get("Averages") or {}).get(raw_key)
        if not item:
            continue
        average_cents = item.get("Average")
        if average_cents is None:
            continue
        averages[normalized_key] = {
            "retail_price_nzd": round(float(average_cents) / 100.0, 4),
            "change_cents_28d": float(item.get("28DayChange", 0)),
            "change_pct_28d": float(item.get("28DayPercent", 0)),
        }

    result = {
        "updated": datamine.get("Updated"),
        "station_count": datamine.get("StationCount"),
        "brand_count": datamine.get("BrandCount"),
        "confirmations_last_7_days": datamine.get("PriceConfirmationsInLast7Days"),
        "user_count": gaspy.get("usercount"),
        "averages": averages,
        "top_91": datamine.get("Top91") or [],
        "source": "Gaspy public stats Firebase snapshot",
    }

    if not averages:
        logger.warning("Gaspy stats payload did not contain any average price data")
        return None

    return result
