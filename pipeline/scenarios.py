"""
Scenario projection engine for NZ fuel security.

Pure calculation module — no Django models, no DB writes.
Takes current state as input, runs depletion mechanics under 5 parameter sets,
outputs week-by-week projection curves per fuel type per scenario.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

SCENARIOS = {
    "status_quo": {
        "label": "Status Quo",
        "description": "Current disruption continues unchanged",
        "hormuz_trajectory": [(-86, 0), (-86, 52)],
        "bab_al_mandeb_pct": 0,
        "supply_competition_pct": 0,
        "demand_elasticity": 0.005,
        "cape_delay_days": 14,
    },
    "partial_reopening": {
        "label": "Partial Reopening",
        "description": "Hormuz recovers to -50% over 4 weeks (convoy system)",
        "hormuz_trajectory": [(-86, 0), (-50, 4), (-50, 52)],
        "bab_al_mandeb_pct": 0,
        "supply_competition_pct": 0,
        "demand_elasticity": 0.005,
        "cape_delay_days": 14,
    },
    "full_reopening": {
        "label": "Full Reopening",
        "description": "Hormuz normalises over 8 weeks (ceasefire)",
        "hormuz_trajectory": [(-86, 0), (-50, 4), (-20, 6), (0, 8), (0, 52)],
        "bab_al_mandeb_pct": 0,
        "supply_competition_pct": 0,
        "demand_elasticity": 0.004,
        "cape_delay_days": 14,
    },
    "compound_chokepoint": {
        "label": "Compound Chokepoint",
        "description": "Hormuz closed + Bab al-Mandeb degrades to -60%",
        "hormuz_trajectory": [(-86, 0), (-86, 52)],
        "bab_al_mandeb_pct": -60,
        "supply_competition_pct": 0,
        "demand_elasticity": 0.006,
        "cape_delay_days": 21,
    },
    "supply_competition": {
        "label": "Supply Competition",
        "description": "Large importers stockpile, squeezing NZ access",
        "hormuz_trajectory": [(-86, 0), (-86, 52)],
        "bab_al_mandeb_pct": 0,
        "supply_competition_pct": 15,
        "demand_elasticity": 0.007,
        "cape_delay_days": 14,
    },
}

FUEL_TYPES = ["petrol", "diesel", "jet"]

MSO_MINIMUMS = {"petrol": 28.0, "diesel": 21.0, "jet": 24.0}

# NZ dependency fractions on chokepoints
# Hormuz: 61.5% of refined petroleum imports are Hormuz-dependent
# (Source: UN Comtrade 2024 — South Korea 70% Gulf crude, Singapore 65%)
NZ_HORMUZ_DEPENDENCY = 0.62
NZ_BAB_DEPENDENCY = 0.10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CurrentState:
    """Snapshot of current NZ fuel supply position."""
    measurement_date: date
    days_since_measurement: int
    onshore_days: dict          # {"petrol": 24.5, "diesel": 18.1, "jet": 20.1}
    on_water_days: dict         # {"petrol": 24.2, "diesel": 28.3, "jet": 33.3}
    hormuz_pct: float           # Current disruption: -86
    avg_price_pct: float        # Current price change vs baseline
    demand_surge_multiplier: float  # Current demand surge


@dataclass
class WeekProjection:
    """Single week's projection for one fuel type."""
    onshore: float
    on_water: float
    total: float
    above_mso: float


@dataclass
class ScenarioResult:
    """Full projection for one scenario."""
    key: str
    label: str
    description: str
    weeks: list         # list of dicts, one per week
    key_dates: dict     # named dates (mso breach, exhaustion, recovery, etc.)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _interpolate_hormuz(trajectory, week):
    """Linearly interpolate Hormuz disruption % at a given week."""
    for i in range(len(trajectory) - 1):
        pct_a, week_a = trajectory[i]
        pct_b, week_b = trajectory[i + 1]
        if week_a <= week <= week_b:
            if week_b == week_a:
                return pct_a
            t = (week - week_a) / (week_b - week_a)
            return pct_a + t * (pct_b - pct_a)
    # Beyond trajectory — hold last value
    return trajectory[-1][0]


def _cape_delay_at_week(base_delay, hormuz_pct):
    """Cape delay tracks Hormuz severity."""
    if hormuz_pct < -60:
        return base_delay
    elif hormuz_pct < -30:
        return base_delay // 2
    else:
        return 0


def project_scenario(state: CurrentState, scenario_key: str, scenario: dict,
                     horizon_weeks: int = 52) -> ScenarioResult:
    """Run depletion model for one scenario over the projection horizon."""

    trajectory = scenario["hormuz_trajectory"]
    bab_frac = max(0, -scenario["bab_al_mandeb_pct"] / 100)
    competition_frac = scenario["supply_competition_pct"] / 100
    elasticity = scenario["demand_elasticity"]
    base_cape = scenario["cape_delay_days"]

    weeks_data = []
    key_dates = {}

    # Track cumulative depletion per fuel type
    cumulative_depletion = {ft: 0.0 for ft in FUEL_TYPES}
    # Track on-water depletion once onshore hits zero (on-water becomes the buffer)
    on_water_remaining = {ft: state.on_water_days.get(ft, 0) for ft in FUEL_TYPES}

    # Pre-compute starting onshore (already adjusted for days since measurement
    # using current depletion rate from the main model)
    starting_onshore = dict(state.onshore_days)

    for week in range(horizon_weeks + 1):
        hormuz_pct = _interpolate_hormuz(trajectory, week)
        hormuz_frac = max(0, -hormuz_pct / 100)

        # Supply loss rate
        supply_loss = (hormuz_frac * NZ_HORMUZ_DEPENDENCY
                       + bab_frac * NZ_BAB_DEPENDENCY
                       + competition_frac)

        # Demand surge — decays toward normal as disruption eases
        price_effect = min(0.15, max(0, state.avg_price_pct) * elasticity)
        demand_surge = 1.0 + price_effect

        # Net daily depletion rate (fraction of supply consumed per day beyond resupply)
        net_daily = supply_loss + (demand_surge - 1.0)

        # Cape delay for this week
        cape_delay = _cape_delay_at_week(base_cape, hormuz_pct)

        week_row = {"week": week, "hormuz_pct": round(hormuz_pct, 1)}

        for ft in FUEL_TYPES:
            # Weekly depletion (7 days per week)
            if week > 0:
                cumulative_depletion[ft] += net_daily * 7

            projected_onshore = max(0, starting_onshore[ft] - cumulative_depletion[ft])

            # On-water adjusted for cape delay
            effective_on_water = max(0, on_water_remaining[ft] - cape_delay)

            # Once onshore hits zero, on-water depletes too (it becomes the active buffer)
            if projected_onshore <= 0 and week > 0:
                on_water_remaining[ft] = max(0, on_water_remaining[ft] - net_daily * 7)
                effective_on_water = max(0, on_water_remaining[ft] - cape_delay)

            total = projected_onshore + effective_on_water
            above_mso = projected_onshore - MSO_MINIMUMS[ft]

            week_row[ft] = {
                "onshore": round(projected_onshore, 1),
                "on_water": round(effective_on_water, 1),
                "total": round(total, 1),
                "above_mso": round(above_mso, 1),
            }

            # Track key dates
            mso_key = f"{ft}_mso_breach"
            if mso_key not in key_dates and above_mso < 0:
                key_dates[mso_key] = _week_to_date(state.measurement_date,
                                                    state.days_since_measurement, week)

            exhaust_key = f"{ft}_exhaustion"
            if exhaust_key not in key_dates and total <= 0:
                key_dates[exhaust_key] = _week_to_date(state.measurement_date,
                                                        state.days_since_measurement, week)

            # Recovery: was below MSO, now above (only for reopening scenarios)
            recovery_key = f"{ft}_recovery"
            if recovery_key not in key_dates and mso_key in key_dates and above_mso >= 0 and week > 0:
                key_dates[recovery_key] = _week_to_date(state.measurement_date,
                                                         state.days_since_measurement, week)

        weeks_data.append(week_row)

    # Derive summary dates
    mso_breaches = [key_dates[f"{ft}_mso_breach"] for ft in FUEL_TYPES
                    if f"{ft}_mso_breach" in key_dates]
    key_dates["rationing_onset"] = min(mso_breaches).isoformat() if mso_breaches else None

    exhaustions = [key_dates[f"{ft}_exhaustion"] for ft in FUEL_TYPES
                   if f"{ft}_exhaustion" in key_dates]
    key_dates["first_exhaustion"] = min(exhaustions).isoformat() if exhaustions else None

    recoveries = [key_dates[f"{ft}_recovery"] for ft in FUEL_TYPES
                  if f"{ft}_recovery" in key_dates]
    key_dates["full_recovery"] = max(recoveries).isoformat() if recoveries else None

    # Convert remaining date objects to strings
    for k, v in key_dates.items():
        if isinstance(v, date):
            key_dates[k] = v.isoformat()

    return ScenarioResult(
        key=scenario_key,
        label=scenario["label"],
        description=scenario["description"],
        weeks=weeks_data,
        key_dates=key_dates,
    )


def _week_to_date(measurement_date, days_since, week):
    """Convert a week number to an actual calendar date."""
    # Week 0 = today (measurement_date + days_since_measurement)
    today = measurement_date + timedelta(days=days_since)
    return today + timedelta(weeks=week)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_all_scenarios(state: CurrentState, horizon_weeks: int = 52) -> dict:
    """
    Run all 5 scenarios and return structured output for JSON export.

    Returns dict ready to merge into depletion_projections or export directly.
    """
    from datetime import datetime

    projections = {}
    rationing_dates = {}
    recovery_dates = {}

    for key, scenario in SCENARIOS.items():
        result = project_scenario(state, key, scenario, horizon_weeks)
        projections[key] = {
            "label": result.label,
            "description": result.description,
            "weeks": result.weeks,
            "key_dates": result.key_dates,
        }
        rationing_dates[key] = result.key_dates.get("rationing_onset")
        recovery_dates[key] = result.key_dates.get("full_recovery")

    # Determine worst fuel type (earliest exhaustion across scenarios)
    worst_fuel = None
    earliest_exhaust = None
    for ft in FUEL_TYPES:
        for key in SCENARIOS:
            exhaust = projections[key]["key_dates"].get(f"{ft}_exhaustion")
            if exhaust and (earliest_exhaust is None or exhaust < earliest_exhaust):
                earliest_exhaust = exhaust
                worst_fuel = ft

    # Generate intervention window text
    window_text = _generate_intervention_text(rationing_dates, recovery_dates)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "horizon_weeks": horizon_weeks,
        "current_state": {
            "onshore_days": {ft: round(state.onshore_days[ft], 1) for ft in FUEL_TYPES},
            "on_water_days": {ft: round(state.on_water_days.get(ft, 0), 1) for ft in FUEL_TYPES},
            "hormuz_pct": state.hormuz_pct,
            "measurement_date": state.measurement_date.isoformat(),
        },
        "projections": projections,
        "comparison": {
            "rationing_dates": rationing_dates,
            "recovery_dates": recovery_dates,
            "worst_fuel": worst_fuel,
            "window_of_intervention": window_text,
        },
    }


def _generate_intervention_text(rationing_dates, recovery_dates):
    """Generate a human-readable intervention window summary."""
    parts = []

    # Check if partial reopening helps
    sq = rationing_dates.get("status_quo")
    pr = rationing_dates.get("partial_reopening")
    fr = rationing_dates.get("full_reopening")

    if pr and sq and pr > sq:
        parts.append(f"Partial reopening of Hormuz delays NZ rationing to {pr}.")
    elif pr and sq and pr == sq:
        parts.append("Partial reopening alone does not delay rationing — damage is already done.")

    if fr is None:
        parts.append("Full reopening within 8 weeks averts rationing entirely.")
    elif fr and sq:
        parts.append(f"Full reopening delays rationing to {fr}.")

    # Check compound scenarios
    cc = rationing_dates.get("compound_chokepoint")
    if cc and sq and cc < sq:
        parts.append(f"Compound chokepoint failure accelerates rationing to {cc}.")

    sc = rationing_dates.get("supply_competition")
    if sc and sq and sc < sq:
        parts.append(f"Supply competition accelerates rationing to {sc}.")

    if not parts:
        parts.append("Insufficient data to determine intervention windows.")

    return " ".join(parts)
