"""
Scenario projection engine for NZ fuel security.

Pure calculation module — no Django models, no DB writes.
Takes current state as input, runs depletion mechanics under 5 parameter sets,
outputs week-by-week projection curves per fuel type per scenario.
"""

from dataclasses import dataclass
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

# Refiner re-sourcing curve: fraction of Hormuz-dependent refinery output
# actually lost over time. Refiners scramble for non-Gulf crude but can't
# replace all of it. Decays as alternative supply contracts establish.
# Source: IEA disruption response estimates, 1973/1990/2019 precedents.
# Format: (loss_fraction, week) — same tuple order as hormuz_trajectory
REFINER_OUTPUT_LOSS = [
    (0.55, 0),    # Week 0: 55% of dependent output lost (crude stocks buffer ~2-3 weeks)
    (0.40, 4),    # Week 4: re-sourcing from Atlantic basin begins
    (0.30, 8),    # Week 8: alternative contracts established
    (0.25, 16),   # Week 16: structural deficit stabilises
    (0.20, 52),   # Week 52: long-term irreducible loss
]

# Maximum stock recovery rate: 1 day of supply per week when resupply > demand.
# Constrained by port throughput, tanker scheduling, and terminal capacity.
MAX_WEEKLY_RECOVERY = 1.0

# Global stress multiplier — indirect effects that compound over time.
# See pipeline/commodity_exposure.py for detailed channel descriptions.
# Format: (multiplier, week) — 1.0 = no indirect effect
# Fuel has stress_sensitivity of 1.4 (most competed-for globally)
FUEL_STRESS_SENSITIVITY = 1.4
GLOBAL_STRESS_MULTIPLIER = [
    (1.0,  0),    # Week 0: buffers absorb
    (1.10, 2),    # Week 2: SK export caps, shipping +15%
    (1.25, 4),    # Week 4: EU gas spike, refinery competition, freight +28%
    (1.45, 8),    # Week 8: EU fertiliser shutting, export bans, insurance seized
    (1.65, 12),   # Week 12: substitution plans colliding, freight 2x+
    (1.85, 16),   # Week 16: EM financial contagion, trade finance contracting
    (2.00, 20),   # Week 20: alternatives exhausted for small buyers
    (2.15, 26),   # Week 26: structural degradation
    (2.25, 36),   # Week 36: new degraded equilibrium
    (2.25, 52),   # Week 52: saturated
]


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


@dataclass
class ScenarioResult:
    """Full projection for one scenario."""
    key: str
    label: str
    description: str
    weeks: list         # list of dicts, one per week
    key_dates: dict     # named dates (mso breach, exhaustion, recovery, etc.)


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------

def _interpolate(waypoints, week):
    """Linearly interpolate a value at a given week from (value, week) waypoints."""
    for i in range(len(waypoints) - 1):
        val_a, week_a = waypoints[i]
        val_b, week_b = waypoints[i + 1]
        if week_a <= week <= week_b:
            if week_b == week_a:
                return val_a
            t = (week - week_a) / (week_b - week_a)
            return val_a + t * (val_b - val_a)
    return waypoints[-1][0]


def _cape_delay_at_week(base_delay, hormuz_pct):
    """Cape delay tracks Hormuz severity."""
    if hormuz_pct < -60:
        return base_delay
    elif hormuz_pct < -30:
        return base_delay // 2
    else:
        return 0


def _demand_surge_at_week(base_price_pct, elasticity, week):
    """
    Demand surge decays over time as demand destruction takes hold.

    Week 0-3: full panic buying (15% cap)
    Week 4-8: fading as prices bite (halved)
    Week 9+:  demand destruction dominates (minimal surge)
    """
    base_effect = min(0.15, max(0, base_price_pct) * elasticity)
    if week <= 3:
        return 1.0 + base_effect
    elif week <= 8:
        # Linear decay from full to half
        decay = 1.0 - 0.5 * (week - 3) / 5
        return 1.0 + base_effect * decay
    else:
        # Demand destruction: surge drops to 20% of initial, then to 0
        decay = max(0, 0.2 - 0.01 * (week - 8))
        return 1.0 + base_effect * decay


# ---------------------------------------------------------------------------
# Core projection
# ---------------------------------------------------------------------------

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

    # Track net stock position per fuel type (can go negative = deficit, positive = surplus vs start)
    cumulative_depletion = {ft: 0.0 for ft in FUEL_TYPES}
    on_water_remaining = {ft: state.on_water_days.get(ft, 0) for ft in FUEL_TYPES}
    starting_onshore = dict(state.onshore_days)

    for week in range(horizon_weeks + 1):
        hormuz_pct = _interpolate(trajectory, week)
        hormuz_frac = max(0, -hormuz_pct / 100)

        # Refiner re-sourcing: not all Hormuz-dependent output is lost —
        # refiners scramble for alternative crude. Loss fraction decays over time.
        refiner_loss = _interpolate(REFINER_OUTPUT_LOSS, week)

        # Direct supply loss rate: physical supply lost to NZ
        direct_loss = (hormuz_frac * NZ_HORMUZ_DEPENDENCY * refiner_loss
                       + bab_frac * NZ_BAB_DEPENDENCY * refiner_loss
                       + competition_frac)

        # Global stress multiplier: indirect effects compound over time.
        # Other countries competing for same alternatives, export bans,
        # shipping crunch, financial contagion degrade NZ's ability to
        # substitute away from Hormuz-dependent supply.
        global_stress = _interpolate(GLOBAL_STRESS_MULTIPLIER, week)
        effective_stress = 1.0 + (global_stress - 1.0) * FUEL_STRESS_SENSITIVITY
        supply_loss = min(1.0, direct_loss * effective_stress)

        # Demand surge decays over time (panic buying → demand destruction)
        demand_surge = _demand_surge_at_week(state.avg_price_pct, elasticity, week)

        # Net daily depletion rate
        # Positive = depleting, negative = resupplying (stocks recovering)
        net_daily = supply_loss + (demand_surge - 1.0)

        # Cape delay for this week
        cape_delay = _cape_delay_at_week(base_cape, hormuz_pct)

        week_row = {"week": week, "hormuz_pct": round(hormuz_pct, 1)}

        for ft in FUEL_TYPES:
            if week > 0:
                weekly_delta = net_daily * 7
                # If recovering (negative delta), cap at realistic refill rate
                if weekly_delta < 0:
                    weekly_delta = max(weekly_delta, -MAX_WEEKLY_RECOVERY)
                cumulative_depletion[ft] = max(0, cumulative_depletion[ft] + weekly_delta)

            projected_onshore = max(0, starting_onshore[ft] - cumulative_depletion[ft])

            # On-water adjusted for cape delay
            effective_on_water = max(0, on_water_remaining[ft] - cape_delay)

            # Once onshore hits zero, on-water depletes too (it becomes the active buffer)
            # Guard: only deplete on-water if there's still accessible supply
            if projected_onshore <= 0 and week > 0 and net_daily > 0:
                accessible = on_water_remaining[ft] - cape_delay
                if accessible > 0:
                    draw = min(net_daily * 7, accessible)
                    on_water_remaining[ft] -= draw
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

            # Recovery: was below MSO, now above again
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
    today = measurement_date + timedelta(days=days_since)
    return today + timedelta(weeks=week)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_all_scenarios(state: CurrentState, horizon_weeks: int = 52) -> dict:
    """
    Run all 5 scenarios and return structured output for JSON export.
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

    sq = rationing_dates.get("status_quo")
    pr = rationing_dates.get("partial_reopening")
    fr = rationing_dates.get("full_reopening")
    fr_rec = recovery_dates.get("full_reopening")

    if pr and sq and pr > sq:
        parts.append(f"Partial reopening of Hormuz delays NZ rationing to {pr}.")
    elif pr and sq and pr == sq:
        parts.append("Partial reopening alone does not delay rationing — damage is already done.")

    if fr is None:
        parts.append("Full reopening within 8 weeks averts rationing entirely.")
    elif fr_rec:
        parts.append(f"Full reopening allows stock recovery by {fr_rec}.")
    elif fr and sq:
        parts.append(f"Full reopening delays rationing to {fr}.")

    cc = rationing_dates.get("compound_chokepoint")
    if cc and sq and cc < sq:
        parts.append(f"Compound chokepoint failure accelerates rationing to {cc}.")

    sc = rationing_dates.get("supply_competition")
    if sc and sq and sc < sq:
        parts.append(f"Supply competition accelerates rationing to {sc}.")

    if not parts:
        parts.append("Insufficient data to determine intervention windows.")

    return " ".join(parts)
