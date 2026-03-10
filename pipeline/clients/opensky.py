"""
OpenSky Network ADS-B flight tracking client.

Tracks flight activity at airports to detect:
1. Gulf airport collapse (corroborating grid failure)
2. NZ private jet arrivals (elite migration signal)

API docs: https://openskynetwork.github.io/opensky-api/rest.html
Auth: OAuth2 Client Credentials flow (basic auth deprecated Mar 18 2026).
Rate limits: anonymous = 400 credits/day, authenticated = 4000 credits/day
"""

import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://opensky-network.org/api"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)

MONITORED_AIRPORTS = {
    # Gulf airports (collapse signal)
    "Tehran Imam Khomeini": "OIIE",
    "Tehran Mehrabad": "OIII",
    "Dubai International": "OMDB",
    "Abu Dhabi": "OMAA",
    "Doha Hamad": "OTHH",
    "Kuwait International": "OKBK",
    "Bahrain International": "OBBI",
    "Riyadh King Khalid": "OERK",
    "Isfahan": "OIFM",
    "Basra": "ORMM",
    # NZ airports (arrival signal)
    "Auckland": "NZAA",
    "Queenstown": "NZQN",
    "Wanaka": "NZWF",  # may have limited data
}


_token_cache = {"token": None, "expires_at": 0.0}
_token_lock = threading.Lock()


def _get_oauth_token() -> str | None:
    """
    Obtain an OAuth2 access token using client credentials flow.

    Caches the token and refreshes 60s before expiry.
    Requires OPENSKY_CLIENT_ID and OPENSKY_CLIENT_SECRET env vars.
    """
    client_id = os.environ.get("OPENSKY_CLIENT_ID", os.environ.get("OPENSKY_USERNAME", ""))
    client_secret = os.environ.get("OPENSKY_CLIENT_SECRET", os.environ.get("OPENSKY_PASSWORD", ""))
    if not client_id or not client_secret:
        return None

    with _token_lock:
        if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
            return _token_cache["token"]

        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            _token_cache["token"] = data["access_token"]
            _token_cache["expires_at"] = time.time() + data.get("expires_in", 1800)
            logger.info("OpenSky OAuth2 token acquired (expires in %ds)", data.get("expires_in", 0))
            return _token_cache["token"]
        except requests.exceptions.RequestException as e:
            logger.error("Failed to obtain OpenSky OAuth2 token: %s", e)
            return None


def _to_unix(d: date) -> int:
    """Convert a date to Unix epoch seconds (start of day UTC)."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _api_get(endpoint: str, params: dict) -> list:
    """
    Make a GET request to the OpenSky API.

    Returns parsed JSON (list of flight dicts) on success,
    or an empty list on any error.
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {}
    token = _get_oauth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)

        if resp.status_code == 404:
            logger.debug("No data for %s with params %s", endpoint, params)
            return []

        if resp.status_code == 429:
            logger.warning("Rate limited by OpenSky API, backing off")
            return []

        resp.raise_for_status()
        data = resp.json()

        if data is None:
            return []

        return data

    except requests.exceptions.Timeout:
        logger.error("Timeout requesting %s", url)
        return []
    except requests.exceptions.ConnectionError:
        logger.error("Connection error requesting %s", url)
        return []
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP error %s for %s", e, url)
        return []
    except requests.exceptions.RequestException as e:
        logger.error("Request error %s for %s", e, url)
        return []
    except ValueError:
        logger.error("Invalid JSON response from %s", url)
        return []


def fetch_airport_arrivals(icao: str, start_date: date, end_date: date) -> list:
    """
    Fetch arrival records for an airport over a date range.

    The OpenSky arrivals endpoint accepts a max 7-day window,
    so this function chunks longer ranges automatically.

    Args:
        icao: ICAO airport code (e.g. "OMDB")
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)

    Returns:
        List of flight dicts from OpenSky API. Each dict contains:
        icao24, firstSeen, lastSeen, estDepartureAirport,
        estArrivalAirport, callsign, etc.
    """
    all_flights = []
    chunk_start = start_date
    max_window = timedelta(days=7)

    while chunk_start <= end_date:
        chunk_end = min(chunk_start + max_window, end_date + timedelta(days=1))

        begin_ts = _to_unix(chunk_start)
        end_ts = _to_unix(chunk_end)

        flights = _api_get("/flights/arrival", {
            "airport": icao,
            "begin": begin_ts,
            "end": end_ts,
        })

        all_flights.extend(flights)
        logger.info(
            "Fetched %d arrivals for %s (%s to %s)",
            len(flights), icao, chunk_start, chunk_end,
        )

        chunk_start = chunk_end.date() if isinstance(chunk_end, datetime) else chunk_end
        time.sleep(1)  # respect rate limits

    return all_flights


def fetch_airport_departures(icao: str, start_date: date, end_date: date) -> list:
    """
    Fetch departure records for an airport over a date range.

    The OpenSky departures endpoint accepts a max 7-day window,
    so this function chunks longer ranges automatically.

    Args:
        icao: ICAO airport code (e.g. "OMDB")
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)

    Returns:
        List of flight dicts from OpenSky API.
    """
    all_flights = []
    chunk_start = start_date
    max_window = timedelta(days=7)

    while chunk_start <= end_date:
        chunk_end = min(chunk_start + max_window, end_date + timedelta(days=1))

        begin_ts = _to_unix(chunk_start)
        end_ts = _to_unix(chunk_end)

        flights = _api_get("/flights/departure", {
            "airport": icao,
            "begin": begin_ts,
            "end": end_ts,
        })

        all_flights.extend(flights)
        logger.info(
            "Fetched %d departures for %s (%s to %s)",
            len(flights), icao, chunk_start, chunk_end,
        )

        chunk_start = chunk_end.date() if isinstance(chunk_end, datetime) else chunk_end
        time.sleep(1)  # respect rate limits

    return all_flights


def count_daily_flights(icao: str, target_date: date) -> dict:
    """
    Count total arrivals and departures at an airport for one day.

    Args:
        icao: ICAO airport code
        target_date: The date to count flights for

    Returns:
        {
            "icao": str,
            "date": date,
            "arrivals": int,
            "departures": int,
            "total_movements": int,
        }
    """
    next_day = target_date + timedelta(days=1)

    arrivals = fetch_airport_arrivals(icao, target_date, target_date)
    departures = fetch_airport_departures(icao, target_date, target_date)

    arrival_count = len(arrivals)
    departure_count = len(departures)

    return {
        "icao": icao,
        "date": target_date,
        "arrivals": arrival_count,
        "departures": departure_count,
        "total_movements": arrival_count + departure_count,
    }


def fetch_flights_for_all_airports(target_date: date) -> list[dict]:
    """
    Fetch flight counts for all monitored airports for a given date.

    Iterates through MONITORED_AIRPORTS, fetching arrivals and departures
    for each. Includes a 1-second sleep between airports to respect
    rate limits.

    Args:
        target_date: The date to fetch flight counts for

    Returns:
        List of count dicts, one per airport. Each dict contains:
        icao, airport_name, date, arrivals, departures, total_movements.
    """
    results = []

    for airport_name, icao in MONITORED_AIRPORTS.items():
        logger.info("Fetching flights for %s (%s) on %s", airport_name, icao, target_date)

        counts = count_daily_flights(icao, target_date)
        counts["airport_name"] = airport_name

        results.append(counts)

        logger.info(
            "%s (%s): %d arrivals, %d departures, %d total",
            airport_name, icao,
            counts["arrivals"], counts["departures"], counts["total_movements"],
        )

        # Sleep between airports (count_daily_flights already sleeps
        # between its own requests, but add a buffer between airports)
        time.sleep(1)

    return results
