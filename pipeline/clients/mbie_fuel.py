"""
MBIE Weekly Fuel Price client.

Parses MBIE weekly fuel price CSV data for NZ retail fuel prices.
Data source: https://www.mbie.govt.nz/building-and-energy/energy-and-natural-resources/
             energy-statistics-and-modelling/energy-statistics/weekly-fuel-price-monitoring/

CSV is long/tidy format with columns:
  Week, Date, Fuel, Variable, Value, Unit, Status

Fuel types: "Regular Petrol", "Premium Petrol 95R", "Diesel", "NA" (crude/FX)
Variables we care about: "Adjusted retail price", "Importer cost", "Importer margin"
Values are in NZD cents/litre.
"""

import csv
import io
import logging
from collections import defaultdict
from datetime import date, datetime

import requests

logger = logging.getLogger(__name__)

MBIE_FUEL_CSV_URL = (
    "https://www.mbie.govt.nz/assets/Data-Files/Energy/Weekly-fuel-price-monitoring/"
    "weekly-table.csv"
)

# Map MBIE fuel names to our internal types
_FUEL_MAP = {
    "Regular Petrol": "91",
    "Premium Petrol 95R": "95",
    "Diesel": "diesel",
}

# Variables to extract
_RETAIL_VAR = "Adjusted retail price"
_COST_VAR = "Importer cost"
_MARGIN_VAR = "Importer margin"


def parse_fuel_csv(csv_text: str) -> list[dict]:
    """
    Parse MBIE weekly fuel price CSV (long format) into a list of dicts.

    Returns list of:
        {
            'date': date,
            'fuel_type': '91' | '95' | 'diesel',
            'retail_price_nzd': float,       # NZD per litre
            'import_cost_nzd': float | None,  # NZD per litre
            'margin_nzd': float | None,       # NZD per litre
        }
    """
    reader = csv.DictReader(io.StringIO(csv_text))

    # Accumulate by (date, fuel_type) → {retail, cost, margin}
    accumulator: dict[tuple, dict] = defaultdict(dict)

    for row in reader:
        fuel_raw = row.get("Fuel", "").strip()
        fuel_type = _FUEL_MAP.get(fuel_raw)
        if fuel_type is None:
            continue  # skip NA (crude/FX) and unknown

        date_str = row.get("Date", "").strip()
        if not date_str:
            continue

        try:
            obs_date = date.fromisoformat(date_str)
        except ValueError:
            try:
                obs_date = datetime.strptime(date_str, "%d/%m/%Y").date()
            except ValueError:
                continue

        variable = row.get("Variable", "").strip()
        try:
            value = float(row.get("Value", "").strip())
        except (ValueError, AttributeError):
            continue

        # Convert cents/litre to dollars/litre
        value_nzd = value / 100.0

        key = (obs_date, fuel_type)

        if variable == _RETAIL_VAR:
            accumulator[key]["retail_price_nzd"] = value_nzd
            accumulator[key]["date"] = obs_date
            accumulator[key]["fuel_type"] = fuel_type
        elif variable == _COST_VAR:
            accumulator[key]["import_cost_nzd"] = value_nzd
        elif variable == _MARGIN_VAR:
            accumulator[key]["margin_nzd"] = value_nzd

    # Build results — only include entries that have a retail price
    results = []
    for key, data in sorted(accumulator.items()):
        if "retail_price_nzd" in data:
            results.append({
                "date": data["date"],
                "fuel_type": data["fuel_type"],
                "retail_price_nzd": data["retail_price_nzd"],
                "import_cost_nzd": data.get("import_cost_nzd"),
                "margin_nzd": data.get("margin_nzd"),
            })

    logger.info("Parsed %d fuel price observations from MBIE CSV", len(results))
    return results


def fetch_mbie_csv() -> str | None:
    """
    Attempt to download MBIE weekly fuel price CSV.
    Returns CSV text or None if download fails.
    """
    try:
        resp = requests.get(
            MBIE_FUEL_CSV_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; satint-pipeline/1.0)",
                "Accept": "text/csv, text/plain, */*",
            },
            timeout=30,
        )
        if resp.status_code == 200 and len(resp.text) > 100:
            logger.info("Downloaded MBIE fuel CSV (%d bytes)", len(resp.text))
            return resp.text
        else:
            logger.warning(
                "MBIE CSV download returned %d (%d bytes)",
                resp.status_code,
                len(resp.text),
            )
            return None
    except requests.RequestException as e:
        logger.warning("Failed to download MBIE CSV: %s", e)
        return None
