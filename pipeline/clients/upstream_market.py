"""
Upstream fuel-market reference data from Yahoo Finance.

This feeds the static dashboard's "Upstream Market Indicators" section with
daily Brent crude, heating oil, RBOB gasoline, and FX reference series.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from datetime import date, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)

LITRES_PER_BARREL = 158.987294928
LITRES_PER_US_GALLON = 3.785411784

BASELINE_START = date(2026, 1, 15)
BASELINE_END = date(2026, 2, 27)

TICKERS = {
    "brent_crude": {"symbol": "BZ=F", "unit": "usd_per_barrel"},
    "heating_oil_futures": {"symbol": "HO=F", "unit": "usd_per_gallon"},
    "rbob_gasoline_futures": {"symbol": "RB=F", "unit": "usd_per_gallon"},
    "nzdusd": {"symbol": "NZDUSD=X", "unit": "usd_per_nzd"},
}


def _fetch_history(symbol: str, start_date: date, end_date: date):
    ticker = yf.Ticker(symbol)
    return ticker.history(
        start=start_date.isoformat(),
        end=(end_date + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
    )


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def fetch_upstream_market_reference(
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict | None:
    """
    Return normalized upstream commodity and FX series for the dashboard.

    FX is stored as NZD per USD to match the chart axis and to simplify the
    conversion from USD-denominated futures prices into NZD/litre.
    """
    start_date = start_date or date(2026, 1, 1)
    end_date = end_date or date.today()

    try:
        histories = {
            key: _fetch_history(meta["symbol"], start_date, end_date)
            for key, meta in TICKERS.items()
        }
    except Exception as exc:
        logger.warning("Failed to fetch upstream market data: %s", exc)
        return None

    if any(hist.empty for hist in histories.values()):
        empties = [key for key, hist in histories.items() if hist.empty]
        logger.warning("Upstream market data missing series: %s", ", ".join(empties))
        return None

    fx_dates = []
    fx_nzd_per_usd = []
    fx_series = []
    for idx, row in histories["nzdusd"].iterrows():
        usd_per_nzd = row.get("Close")
        if usd_per_nzd in (None, 0):
            continue
        d = idx.date().isoformat()
        nzd_per_usd = float(1.0 / usd_per_nzd)
        fx_dates.append(d)
        fx_nzd_per_usd.append(nzd_per_usd)
        fx_series.append({
            "date": d,
            "rate": round(nzd_per_usd, 4),
            "usd_per_nzd": round(float(usd_per_nzd), 6),
        })

    if not fx_dates:
        logger.warning("Upstream market data missing usable FX observations")
        return None

    def fx_for_date(date_str: str) -> float | None:
        pos = bisect_right(fx_dates, date_str) - 1
        if pos < 0:
            return None
        return fx_nzd_per_usd[pos]

    def convert_to_nzd_litre(close_usd: float, unit: str, nzd_per_usd: float) -> float:
        if unit == "usd_per_barrel":
            return float(close_usd) * nzd_per_usd / LITRES_PER_BARREL
        if unit == "usd_per_gallon":
            return float(close_usd) * nzd_per_usd / LITRES_PER_US_GALLON
        raise ValueError(f"Unsupported upstream unit: {unit}")

    result = {"nzdusd": fx_series}
    baselines = {
        "nzdusd": round(
            _mean(
                item["rate"]
                for item in fx_series
                if BASELINE_START.isoformat() <= item["date"] <= BASELINE_END.isoformat()
            ),
            4,
        ),
    }

    for key in ("brent_crude", "heating_oil_futures", "rbob_gasoline_futures"):
        unit = TICKERS[key]["unit"]
        series = []
        for idx, row in histories[key].iterrows():
            close_usd = row.get("Close")
            if close_usd is None:
                continue
            d = idx.date().isoformat()
            nzd_per_usd = fx_for_date(d)
            if nzd_per_usd is None:
                continue
            series.append({
                "date": d,
                "close_usd": round(float(close_usd), 4),
                "nzd_litre": round(convert_to_nzd_litre(close_usd, unit, nzd_per_usd), 4),
            })
        result[key] = series
        baseline = _mean(
            item["nzd_litre"]
            for item in series
            if BASELINE_START.isoformat() <= item["date"] <= BASELINE_END.isoformat()
        )
        if baseline is not None:
            baselines[f"{key}_nzd_litre"] = round(baseline, 4)

    result["baselines"] = {
        "brent_nzd_litre": baselines.get("brent_crude_nzd_litre"),
        "heating_oil_nzd_litre": baselines.get("heating_oil_futures_nzd_litre"),
        "rbob_nzd_litre": baselines.get("rbob_gasoline_futures_nzd_litre"),
        "nzdusd": baselines.get("nzdusd"),
    }
    result["source"] = "Yahoo Finance daily futures and FX"
    result["latest"] = {
        key: series[-1]["date"] if series else None
        for key, series in result.items()
        if isinstance(series, list)
    }
    return result
