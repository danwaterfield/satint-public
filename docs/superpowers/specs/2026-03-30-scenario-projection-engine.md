# Scenario Projection Engine

**Date:** 2026-03-30
**Status:** Approved
**Purpose:** Transform the fuel security dashboard from retrospective ("here's what happened") to predictive ("here's what's coming under N scenarios").

## Problem

The pipeline tracks current state across 15 data sources but does not project forward under alternative assumptions. The fuel security model computes a single depletion trajectory based on current Hormuz disruption. Decision-makers need to see how different conflict outcomes change NZ's supply timeline — and when intervention windows close.

## Architecture

Pure calculation module. No new Django models, no migrations, no new database tables.

```
Current DB state ──▸ Scenario Engine ──▸ JSON export (fuel_security.json)
                    (pure functions)         └─▸ Dashboard (Plotly)
```

The engine:
1. Queries current state once (stocks, prices, Hormuz disruption, chokepoint data)
2. Runs the existing depletion mechanics under 5 parameter sets
3. Outputs week-by-week projection curves per fuel type per scenario
4. Is called from `calculate_fuel_security_indicator()` after the existing single-scenario calculation
5. Writes results into `NZFuelSecurityIndicator.depletion_projections["scenarios"]`

## Scenarios

### 1. Status Quo
Current disruption continues unchanged. Hormuz stays at -86%. No intervention.

**Parameters:**
- `hormuz_trajectory`: [(-86, week 0), (-86, week 52)]
- `bab_al_mandeb_disruption`: 0%
- `supply_competition_loss`: 0%
- `demand_elasticity`: 0.005
- `cape_delay_days`: 14

### 2. Partial Reopening
Hormuz recovers to -50% over 4 weeks via convoy system or limited commercial transit under naval escort.

**Parameters:**
- `hormuz_trajectory`: [(-86, week 0), (-50, week 4), (-50, week 52)]
- `bab_al_mandeb_disruption`: 0%
- `supply_competition_loss`: 0%
- `demand_elasticity`: 0.005
- `cape_delay_days`: 14 (drops to 7 when Hormuz > -60%)

### 3. Full Reopening
Ceasefire or de-escalation. Hormuz normalises over 8 weeks with gradual recovery.

**Parameters:**
- `hormuz_trajectory`: [(-86, week 0), (-50, week 4), (-20, week 6), (0, week 8), (0, week 52)]
- `bab_al_mandeb_disruption`: 0%
- `supply_competition_loss`: 0%
- `demand_elasticity`: 0.004 (demand normalises)
- `cape_delay_days`: 14 → 7 → 0 (tracks Hormuz recovery)

### 4. Compound Chokepoint
Hormuz stays closed AND Bab al-Mandeb degrades to -60% (Houthi escalation). Cape rerouting becomes the only viable route but is congested.

**Parameters:**
- `hormuz_trajectory`: [(-86, week 0), (-86, week 52)]
- `bab_al_mandeb_disruption`: -60%
- `supply_competition_loss`: 0%
- `demand_elasticity`: 0.006 (higher panic factor)
- `cape_delay_days`: 21 (Cape congestion from dual-chokepoint rerouting)

### 5. Supply Competition
Hormuz stays closed AND large importers (India, China, Japan) begin strategic stockpiling, competing for the same non-Gulf supply NZ depends on. Effective NZ supply access shrinks.

**Parameters:**
- `hormuz_trajectory`: [(-86, week 0), (-86, week 52)]
- `bab_al_mandeb_disruption`: 0%
- `supply_competition_loss`: 15% (additional effective supply loss)
- `demand_elasticity`: 0.007 (domestic panic from global scarcity signals)
- `cape_delay_days`: 14

## Engine Design

### Input: Current State Snapshot

Queried once at calculation time:

```python
@dataclass
class CurrentState:
    measurement_date: date           # Latest MBIE stock measurement
    days_since_measurement: int
    onshore_days: dict[str, float]   # {"petrol": 24.5, "diesel": 18.1, "jet": 20.1}
    on_water_days: dict[str, float]  # {"petrol": 24.2, "diesel": 28.3, "jet": 33.3}
    mso_minimums: dict[str, float]   # {"petrol": 28, "diesel": 21, "jet": 24}
    hormuz_pct: float                # Current disruption: -86
    nz_hormuz_dependency: float      # 0.40
    avg_price_pct: float             # Current price change vs baseline
```

### Core: Weekly Step Function

For each scenario, for each week (0–52), for each fuel type:

```python
def project_week(state, scenario, week, fuel_type):
    # 1. Interpolate Hormuz disruption at this week
    hormuz_pct = interpolate(scenario.hormuz_trajectory, week)
    hormuz_frac = max(0, -hormuz_pct / 100)

    # 2. Calculate supply loss rate
    supply_loss = hormuz_frac * state.nz_hormuz_dependency
    supply_loss += scenario.bab_al_mandeb_disruption_frac * 0.10  # NZ Bab dependency ~10%
    supply_loss += scenario.supply_competition_loss / 100

    # 3. Calculate demand surge (decays as prices rise — demand destruction)
    price_effect = min(0.15, max(0, state.avg_price_pct) * scenario.demand_elasticity)
    demand_surge = 1.0 + price_effect

    # 4. Net daily depletion
    net_depletion = supply_loss + (demand_surge - 1.0)

    # 5. Project onshore stock
    days_depleted = week * 7 * net_depletion
    projected_onshore = state.onshore_days[fuel_type] - days_depleted

    # 6. Effective on-water (adjusted for rerouting delays)
    cape_delay = scenario.cape_delay_at_week(week, hormuz_pct)
    effective_on_water = max(0, state.on_water_days[fuel_type] - cape_delay)

    # 7. Total effective supply
    total = max(0, projected_onshore) + effective_on_water

    return ProjectedWeek(
        week=week,
        onshore=max(0, projected_onshore),
        on_water=effective_on_water,
        total=total,
        hormuz_pct=hormuz_pct,
        above_mso=projected_onshore - state.mso_minimums[fuel_type],
    )
```

### Output: Key Dates Extraction

After generating all 52 weeks, extract:

- `mso_breach_date`: First week where projected_onshore < MSO (per fuel type)
- `stock_exhaustion_date`: First week where total effective supply ≤ 0
- `rationing_onset`: Earliest MSO breach across all fuel types
- `first_industry_impact`: Earliest industry cascade trigger
- `food_inflation_onset`: When freight industry impact + 2-week lag fires
- `recovery_date`: First week where stocks climb back above MSO (reopening scenarios only)

### Cape Delay Logic

Cape delay is not a constant — it tracks Hormuz recovery:

```python
def cape_delay_at_week(scenario, week, hormuz_pct):
    if hormuz_pct < -60:
        return scenario.cape_delay_days  # Full rerouting
    elif hormuz_pct < -30:
        return scenario.cape_delay_days // 2  # Partial rerouting
    else:
        return 0  # Direct route viable
```

## JSON Export Schema

New `scenarios` key added to existing `fuel_security.json`:

```json
{
  "indicator": { },
  "series": [ ],
  "scenarios": {
    "generated_at": "2026-03-30T...",
    "horizon_weeks": 52,
    "current_state": {
      "onshore_days": {"petrol": 24.5, "diesel": 18.1, "jet": 20.1},
      "on_water_days": {"petrol": 24.2, "diesel": 28.3, "jet": 33.3},
      "hormuz_pct": -86,
      "measurement_date": "2026-03-22"
    },
    "projections": {
      "status_quo": {
        "label": "Status Quo",
        "description": "Current disruption continues unchanged",
        "weeks": [
          {
            "week": 0,
            "petrol": {"onshore": 20.5, "on_water": 10.2, "total": 30.7, "above_mso": -7.5},
            "diesel": {"onshore": 14.1, "on_water": 14.3, "total": 28.4, "above_mso": -6.9},
            "jet":    {"onshore": 16.1, "on_water": 19.3, "total": 35.4, "above_mso": -7.9}
          },
          {"week": 1, "...": "..."},
          {"week": 2, "...": "..."}
        ],
        "key_dates": {
          "petrol_mso_breach": "2026-03-28",
          "diesel_mso_breach": "2026-03-27",
          "jet_mso_breach": "2026-03-26",
          "petrol_exhaustion": "2026-05-15",
          "diesel_exhaustion": "2026-05-02",
          "jet_exhaustion": "2026-04-28",
          "rationing_onset": "2026-03-26",
          "first_industry_impact": "2026-03-30",
          "food_inflation_onset": "2026-04-13",
          "recovery_date": null
        }
      },
      "partial_reopening": { },
      "full_reopening": { },
      "compound_chokepoint": { },
      "supply_competition": { }
    },
    "comparison": {
      "rationing_dates": {
        "status_quo": "2026-03-26",
        "partial_reopening": "2026-04-15",
        "full_reopening": null,
        "compound_chokepoint": "2026-03-26",
        "supply_competition": "2026-03-26"
      },
      "recovery_dates": {
        "status_quo": null,
        "partial_reopening": "2026-06-10",
        "full_reopening": "2026-05-20",
        "compound_chokepoint": null,
        "supply_competition": null
      },
      "worst_fuel": "jet",
      "window_of_intervention": "Partial reopening by week 4 delays rationing by ~3 weeks. Full reopening by week 8 averts rationing entirely. Beyond week 8, no modeled scenario averts rationing."
    }
  }
}
```

## Dashboard Visualization

### Scenario Projection Chart

Plotly line chart in the Fuel Security tab, below existing components.

- **X-axis:** Weeks from now (0–26, with option to extend to 52)
- **Y-axis:** Days of supply (onshore)
- **Lines:** One per scenario, color-coded and labeled
  - Status Quo: red solid
  - Partial Reopening: orange dashed
  - Full Reopening: green dashed
  - Compound Chokepoint: dark red solid
  - Supply Competition: purple solid
- **MSO line:** Horizontal red dashed line at fuel-type MSO minimum
- **Zero line:** Horizontal black line at 0 (exhaustion)
- **Dropdown:** Switch between petrol, diesel, jet views
- **Annotations:** Key dates marked with vertical dotted lines (rationing onset, recovery)
- **Hover:** Shows exact days-of-supply and date for each scenario at that week

### Scenario Comparison Table

Below the chart. Compact grid:

| Scenario | Rationing Onset | Recovery | Diesel Exhaustion | Jet Exhaustion |
|----------|----------------|----------|-------------------|----------------|
| Status Quo | Mar 26 (NOW) | Never | May 2 | Apr 28 |
| Partial Reopening | Apr 15 | Jun 10 | Jun 1 | May 28 |
| Full Reopening | Averted | May 20 | Averted | Averted |
| Compound Chokepoint | Mar 26 (NOW) | Never | Apr 20 | Apr 15 |
| Supply Competition | Mar 26 (NOW) | Never | Apr 25 | Apr 20 |

Color coding: green = averted, amber = delayed (>2 weeks from now), red = imminent or breached.

### Window of Intervention Text

A single sentence generated by the engine, displayed prominently:

> "Partial reopening of Hormuz by [date] delays NZ rationing by ~3 weeks. Full reopening by [date] averts it entirely. Beyond [date], no modeled scenario averts rationing."

This is the most important output — it answers the user's original question with a data-driven deadline.

## Implementation Scope

### New files:
- `pipeline/scenarios.py` — pure scenario engine (~150 lines)

### Modified files:
- `pipeline/tasks.py` — call scenario engine from `calculate_fuel_security_indicator()`, store results in `depletion_projections["scenarios"]`
- `pipeline/management/commands/export_static.py` — export `scenarios` key from stored projections
- `docs/index.html` — new Plotly chart + comparison table in Fuel Security tab

### No changes to:
- `pipeline/models.py` — no new models, scenarios stored in existing JSONField
- Database schema — no migrations
- Any other existing functionality

## Assumptions and Limitations

1. **Linear depletion** — stocks deplete at constant rate per scenario. Reality has stochastic variation (weather delays, demand spikes, emergency shipments). The model provides central estimates, not confidence bands.
2. **NZ Hormuz dependency at 40%** — this is a blended estimate across fuel types. In reality jet fuel dependency may be higher (~50%) and diesel lower (~35%). Could be parameterised per fuel type in a future iteration.
3. **Bab al-Mandeb NZ dependency at 10%** — rough estimate of NZ-bound refined product transiting Red Sea. Less critical than Hormuz but compounds in scenario 4.
4. **Supply competition modeled as flat loss** — the 15% additional loss in scenario 5 is a simplification. Real competition dynamics would depend on spot market pricing, contract structures, and government intervention.
5. **No restocking model** — reopening scenarios show when stocks stop declining, but modeling the restocking curve (how fast ships arrive, refinery ramp-up) is not included. Recovery dates mark when depletion stops, not when stocks return to pre-war levels.
6. **Stock measurement staleness** — MBIE data is quarterly with up to 90-day lag. The model projects forward from the last measurement, which adds uncertainty proportional to staleness.
