# Iran Crisis Autoresearcher — Design Specification

**Date:** 2026-03-16
**Status:** Reviewed
**Project:** autoresearcher-irancrisis
**Location:** /Users/danielwaterfield/Documents/autoresearcher-irancrisis/

## Purpose

A Bayesian network scenario modelling system that explores possible outcomes of the 2026 Iran war and their downstream effects on New Zealand. LLM-guided explorer agents search the space of causal assumptions, Monte Carlo sampling produces probability distributions over outcomes, and an Opus synthesis layer generates publication-quality briefings for the GitHub Pages dashboard.

This adapts the autoresearcher-nz architectural pattern (explorer loop, cross-pollination, Opus synthesis) but replaces the Mesa agent-based health simulation with a forward Monte Carlo simulator using conditional sampling. No Django, no Mesa, no database, no heavy framework — just numpy/scipy distribution sampling in a day-by-day loop.

## Design Decisions & Rationale

### Why Bayesian network, not system dynamics or Mesa ABM

The crisis is characterised by **regime changes** — discrete events (ceasefire, major strike, Hormuz closure) that fundamentally reshape the probability of everything downstream. System dynamics assumes smooth continuous flows, which is wrong for war modelling. Mesa ABM is designed for emergent behaviour from thousands of agents; we have ~15 actors and ~30 systems, making it overkill.

A causal network with conditional sampling naturally handles these dependencies: P(NZ rationing | Hormuz closed, no ceasefire) differs from P(NZ rationing | Hormuz closed, ceasefire day 45). Each turning point updates the probability distribution over all downstream nodes. This is the established methodology for catastrophe modelling in reinsurance (RMS, AIR Worldwide), applied here to geopolitical crisis.

### Why forward Monte Carlo, not pgmpy

The model is fundamentally temporal: day N depends on day N-1, with feedback loops (demand destruction moderates oil prices, grid damage slows repair). Standard Bayesian network libraries (pgmpy, pyAgrum) implement static DAG inference — they cannot handle cycles or temporal state transitions natively.

What we actually need is simpler: each node is a Python callable that takes its parents' values from the previous day and returns a sample from a conditional distribution. A forward Monte Carlo loop steps through 180 days, sampling all nodes at each step. This is ~200 lines of numpy/scipy, faster than any library, and fully transparent.

The causal network structure (which nodes depend on which) still follows Bayesian network principles. We just implement inference as forward sampling rather than using a library's built-in algorithms.

### Within-day DAG vs cross-day feedback

The within-day causal graph must be a DAG (directed acyclic graph) — no cycles within a single time step. Feedback loops operate exclusively across days: oil price at day N affects demand destruction at day N+1, which affects oil price at day N+2. This is a standard approach in dynamic Bayesian networks (DBN), but we implement it as a simple loop rather than using DBN machinery.

### Why country/system-level, not infrastructure-level

The satint pipeline's infrastructure-level data is patchy: 14 thermal signature facilities, 2 of 6 chokepoints with SAR data, zero AIS vessel transit, zero NDVI/NO2. Meanwhile, the richest free data sources are market/macro level: yfinance (daily oil/FX/indices), FRED (economic time series), EIA (petroleum supply/demand), ACLED (geocoded conflict events). The simulation operates at the level where data is densest.

Infrastructure damage enters as scenario parameters with probability distributions, not as directly simulated variables.

### Why not a database

The autoresearcher-nz uses Django + PostgreSQL because the health simulation requires spatial queries (SA2 boundaries, transport matrices). This system needs none of that. World state is a daily JSON snapshot. Experiments log to JSONL. Outputs are JSON + markdown. Files are simpler, portable, and version-controllable.

### Signal-to-reality translation

Raw satellite/OSINT signals do not equal ground truth:
- SAR vessel count in Hormuz box includes anchored, drifting, and military vessels — not commercial transit
- IODA internet "recovery" in Iran includes VPN/satellite workarounds — civilian infrastructure connectivity is near zero
- Nightlight drop of -78% in Tehran is consistent with near-total grid failure

The world state snapshot carries `raw_signal` and an `estimated_actual` distribution (not a point estimate) with documented reasoning. Where the translation involves analyst judgment (e.g., "Hormuz is effectively closed"), the estimate is a distribution with a confidence interval, not a single number. This lets the simulation sample from the uncertainty rather than treating a guess as a measurement. This transparency is essential for publication quality.

### Caveats

- **No historical precedent** for full Hormuz closure. The 2019 Abqaiq attack (~5% of global supply offline for 2 weeks) is the closest analogue. All model outputs extrapolate beyond observed data.
- **NZ is a food exporter.** Food price impact is nuanced: dairy/meat export revenue increases while import costs rise. Modelled as terms-of-trade, not a simple price index.
- **Feedback loops exist.** Oil price spike → demand destruction → price moderates. Hormuz closure → Cape rerouting → Cape congestion → further delays. The network models bidirectional effects where each day's node states depend on the previous day's.
- **CPDs are expert elicitation, not empirical estimation.** The conditional probability distributions are analyst-specified, not learned from historical data (because there is no historical data for this scenario). The explorer loop's role is to characterise sensitivity to these elicited assumptions rather than to "find the right answer." The methodology document must be explicit about this distinction.

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  Data Ingest     │───▸│  Forward MC       │───▸│  Explorer Loop   │───▸│  Synthesis        │
│  (market, OSINT) │    │  Simulator        │    │  (LLM-guided)   │    │  (Opus analysis)  │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └──────────────────┘
```

### Layer 1: Data Ingest

Python clients pull current state from free APIs into a daily world state snapshot (`data/snapshots/YYYY-MM-DD.json`). One file per source, an assembler merges them.

**Sources:**

| Source | Data | Library | Cost | Update |
|--------|------|---------|------|--------|
| yfinance | Brent, WTI, NZD/USD, Gulf indices (^TASI.SR, DFMGI.AE) | `yfinance` | Free | Real-time |
| FRED | Oil/gas prices, commodity indices, FX, Baltic indices | `fredapi` | Free (key) | Daily |
| EIA | Petroleum supply/demand, refinery utilisation, OPEC production | REST API | Free (key) | Weekly |
| ACLED | Geocoded conflict events, fatalities, actors | REST API | Free (research) | Weekly |
| ReliefWeb | Humanitarian situation reports, flash appeals | REST API | Free | Real-time |
| MBIE | NZ fuel prices, stock levels | CSV download | Free | Weekly |
| satint pipeline | Nightlights, fires, IODA, SAR, thermal sigs, compound risk | Read `docs/data/*.json` | Local | Daily |

Fields that can't be populated are `null`. The simulation widens uncertainty bands for missing data rather than crashing.

**World state schema:**

```python
{
    "date": "2026-03-16",
    "energy": {
        "brent_usd": {"raw_signal": 127.40, "estimated_actual": 127.40, "source": "yfinance"},
        "nz_petrol_nzd_litre": {"raw_signal": 3.02, "estimated_actual": 3.02, "source": "mbie"},
        # ...
    },
    "stocks": {
        "nz_petrol_onshore_days": {"raw_signal": 32.8, "estimated_actual": 30.8,
            "source": "mbie", "note": "Projected from Mar 8 measurement minus 7 days depletion"},
        # ...
    },
    "maritime": {
        "hormuz_vessel_pct_change": {"raw_signal": -55.0,
            "estimated_actual": {"estimate": -95.0, "ci_90": [-100, -80], "basis": "analyst_judgment"},
            "source": "satint_sar", "note": "Raw SAR detects presence not transit. Strait effectively closed to commercial shipping."},
        # ...
    },
    "conflict": {
        "war_day": 16,
        "acled_events_iran_7d": null,  # not yet integrated
        # ...
    },
    "grid": {
        "iran_internet": {"raw_signal": -5.2,
            "estimated_actual": {"estimate": -99.0, "ci_90": [-100, -90], "basis": "analyst_judgment"},
            "source": "satint_ioda", "note": "IODA recovery is VPN/satellite. Civilian infrastructure near zero."},
        "tehran_nightlight_pct": {"raw_signal": -78.0, "estimated_actual": -78.0, "source": "satint"},
        # ...
    },
    "financial": {
        "nzd_usd": {"raw_signal": 0.568, "estimated_actual": 0.568, "source": "yfinance"},
        # ...
    },
}
```

### Layer 2: Forward Monte Carlo Simulator

**Network structure — three layers of nodes:**

**Cause layer** (conflict events):
- `escalation_level` — continuous [0,1], current conflict intensity
- `ceasefire_probability` — daily probability of ceasefire, may increase over time
- `hormuz_status` — continuous [0,1], fraction of commercial transit blocked
- `strike_targets` — categorical, what infrastructure categories are being hit
- `china_stance` — binary, whether China continues Iranian oil imports
- `sanctions_regime` — continuous [0,1], intensity of secondary sanctions

**Transmission layer** (global systems):
- `oil_price` — USD/bbl, conditional on Hormuz, refinery state, OPEC spare capacity
- `shipping_cost` — multiplier on baseline, conditional on Hormuz, insurance, Cape rerouting
- `gulf_grid_state` — per-country grid capacity, conditional on strikes and repair rate
- `gulf_desal_state` — per-country desal capacity, conditional on grid (cascade dependency)
- `gulf_refinery_state` — per-country refinery output, conditional on strikes and grid
- `insurance_premiums` — war risk multiplier, conditional on Hormuz status and conflict intensity
- `fertiliser_supply` — global supply index, conditional on oil price and Gulf port status
- `food_market` — global food price index, conditional on fertiliser and shipping

**NZ impact layer** (downstream effects):
- `nz_fuel_price` — NZD/litre, conditional on oil price, shipping cost, NZD/USD
- `nz_stock_depletion` — days of supply remaining, imports satint's calibrated depletion logic
- `nz_days_to_rationing` — days until MSO breach, conditional on depletion and demand surge
- `nz_food_price_index` — pct change from baseline, conditional on food market and shipping
- `nz_terms_of_trade` — net effect: export revenue up (dairy/meat) vs import costs up
- `nz_gdp_impact` — estimated GDP impact, conditional on fuel, food, and trade effects

Each node has:
- A conditional probability distribution (CPD) given its parent nodes
- An observation (from world state snapshot) that constrains the posterior via Bayesian updating
- Uncertainty bands that widen when observations are missing or stale

**Cascade logic (feedback loops):**

```
hormuz_closed → oil_price_spike → nz_fuel_cost_up
                                → fertiliser_cost_up → nz_food_price_up
             → shipping_reroute → delivery_delays → nz_stock_depletion
             → gulf_revenue_collapse → infrastructure_repair_slows

grid_damage → desal_offline → water_crisis → humanitarian_displacement
           → refinery_offline → oil_supply_further_reduced
           → internet_down → economic_activity_collapses

oil_price_spike → demand_destruction → oil_price_moderates (feedback)
ceasefire → repair_begins → gradual_normalisation
         → hormuz_reopening → shipping_resumes
         → insurance_premiums_persist (slow decay, not instant)
```

Feedback is handled by making each day-step read previous day's state. Node values at day N depend on parent node values at day N-1.

**How a run works:**

1. Set evidence — clamp observed nodes to current world state values
2. Sample 5,000 Monte Carlo paths, 180 days each
3. At each day-step, sample each node conditional on parents' day N-1 state, plus probabilistic events
4. Collect outcome distributions — percentiles for all output metrics
5. Return: p5/p25/p50/p75/p95 for each metric, plus daily time series with confidence bands

**Bayesian updating:**

When new satint/market data arrives, yesterday's posterior becomes today's prior. Example: MBIE publishes new stock data showing faster depletion → P(nz_days_to_rationing) shifts toward shorter timeframes → propagates to all downstream NZ impact nodes.

**Calibration anchors** (the network must reproduce these observed values when inputs match current reality):

Static anchors (current state):
- Hormuz ~95% closed → model outputs near-total commercial transit cessation
- Tehran nightlights -78% → model outputs severe Iranian grid failure
- NZ petrol $3.02/L, stations running dry → model outputs matching fuel stress
- MBIE 52 days total cover (as of Mar 8) → model stock depletion matches

Dynamic anchors (rate of change — constrains trajectory parameters):
- Hormuz SAR: +114% on Feb 28 → -55% by Mar 9 (12-day transit collapse). Model must reproduce this timeline.
- Tehran nightlights: -12% on Mar 5 → -78% on Mar 8 (3-day grid collapse). Model must reproduce this rate.
- Iran internet: -66% on Feb 28 → partial IODA recovery by Mar 3 (5-day VPN workaround). Model should distinguish grid recovery from VPN.
- NZ fuel prices: baseline ~$2.50 → $3.02 by Mar 15 (17 days, ~20% rise). Model must reproduce this pass-through speed.

**Observed vs projected boundary:**

The simulation runs from day 0 (war start, Feb 28) through day 180 (Aug 27). Days 0 through today have observations; future days do not.

- **Past days (0 to today):** Clamp all available observations as evidence. Sample only unobserved nodes. Model is constrained by reality.
- **Projection boundary (today):** Uncertainty widens discontinuously. The last observation for each node becomes the initial condition for forward sampling.
- **Future days (today + 1 onward):** Sample all nodes. Variance grows with sqrt(days_ahead) — reflecting increasing uncertainty over time. No observations to clamp.

This transition must be visible in the output: confidence bands narrow where we have data and widen into the future. The daily_briefing output explicitly marks which metrics are "observed" vs "projected."

**Computation budget:**
- Quick run (1,000 samples × 180 days): ~3 seconds
- Full scenario (5,000 samples × 180 days): ~15 seconds
- Explorer experiment (propose + simulate + compare): ~20-30 seconds (LLM call 5-15s + simulation 15s)
- Full fleet (7 agents × 60 experiments): ~3-5 hours (LLM-latency-dominated, not compute; requires 7 concurrent Anthropic API connections)

**Implementation:** Hand-rolled forward sampler using numpy/scipy. Each node is a Python callable with a `sample(parents: dict, rng: np.random.Generator) -> float` method. The causal graph structure follows Bayesian network principles (within-day DAG, cross-day feedback), but inference is pure forward sampling — no library needed. This is faster, more transparent, and avoids fighting framework assumptions.

**Reproducibility:** Every MC run uses a deterministic seed (recorded in the experiment log) so any published result can be exactly reproduced.

### Layer 3: Explorer Loop

Seven agents, each probing a different dimension of uncertainty. Sonnet 4 proposes changes to CPDs (conditional probability distributions), simulation evaluates via MC sampling, accept/reject based on whether the scenario is informative.

**Agent fleet:**

| Agent | Mandate | Searches |
|---|---|---|
| `escalation_explorer` | How does conflict trajectory affect outcomes? | Ceasefire probability curves, escalation step functions, strike target probabilities |
| `nz_fuel_explorer` | What drives NZ fuel security most? | Demand surge, government intervention timing, alternative supply lag, stock depletion rates |
| `trade_explorer` | How does maritime disruption propagate? | Hormuz→oil price elasticity, Cape rerouting speed, insurance premium decay, shipping capacity constraints |
| `recovery_explorer` | What does post-ceasefire look like? | Repair rates, Hormuz reopening speed, insurance normalisation lag, demand recovery curves |
| `food_explorer` | How do food/fertiliser cascades affect NZ? | Fertiliser price pass-through, NZ export revenue uplift vs import cost, pastoral farming lag |
| `tail_risk_explorer` | What are the worst-case scenarios? | Searches for parameter combinations producing extreme NZ outcomes (5th percentile) |
| `assumption_explorer` | Which structural assumptions matter most? | Tests network structure changes: adding/removing edges, changing CPD functional forms |

**Accept/reject logic:**

A proposed CPD change is accepted if it meets ANY of:
- **Sensitivity discovery**: ≤10% parameter shift → ≥15% shift in median NZ rationing date
- **Tail exploration**: produces outcome in 5th or 95th percentile of previously observed runs
- **Novelty**: CPD configuration is far from previously explored configs (KL-divergence) AND the output distribution differs meaningfully from existing runs (prevents "novel but uninformative" experiments)
- **Contradiction**: produces outcome contradicting another accepted scenario with similar inputs

Rejected if:
- Output distribution indistinguishable from existing scenarios (redundant)
- CPD values physically implausible (violates hard constraints)

**Three-phase search:**
1. **Sweep** (1-20): Single CPD changes. Which individual parameters matter?
2. **Combination** (21-60): Combine sensitive parameters. Interaction effects.
3. **Creative** (61+): LLM proposes structural changes — new edges, regime-switching CPDs, feedback loops not in baseline network.

**Experiment log format (JSONL):**

```json
{
    "experiment_id": "ESC-014",
    "agent_id": "escalation_explorer",
    "timestamp": "2026-03-16T10:32:00Z",
    "hypothesis": "If ceasefire probability increases 3% per week, median war duration drops from 95 to 62 days, shifting NZ rationing from 72% to 41%",
    "seed": 20260316001,
    "cpd_changes": [
        {"node": "ceasefire_probability", "param": "weekly_increase", "old": 0.01, "new": 0.03}
    ],
    "structural_changes": [],
    "output_distribution": {
        "nz_days_to_rationing": {"p5": 12, "p25": 28, "p50": 45, "p75": 89, "p95": null},
        "brent_peak_usd": {"p5": 118, "p25": 132, "p50": 148, "p75": 167, "p95": 203}
    },
    "baseline_distribution": { "..." },
    "status": "accepted",
    "acceptance_reason": "sensitivity_discovery",
    "sensitivity_score": 0.73,
    "phase": "sweep"
}
```

**Cross-pollination** (every 15 minutes during fleet run): If the escalation_explorer discovers that ceasefire timing dominates variance, that finding is shared with all other agents so they condition on it rather than re-discovering it.

### Layer 4: Synthesis

Opus reads all experiments and produces publication-quality output.

**Quick mode** (`python run.py --quick`): Single scenario, 1,000 MC samples, text summary to terminal. ~5 seconds. For personal decision-making.

**Full fleet mode** (`./fleet_run.sh`): 7 agents × 60 experiments, cross-pollination, Opus synthesis. ~3 hours. Produces all outputs below.

**Outputs:**

1. **`outputs/probability_dashboard.json`** — For GitHub Pages. Posterior probabilities with confidence intervals for key outcomes (NZ rationing probability at 30/60/90 days, Brent price ranges, ceasefire probability, MSO breach dates per fuel type).

2. **`outputs/sensitivity_ranking.json`** — Which assumptions drive the most variance in NZ outcomes, ranked by variance contribution. Tells the reader: "Hormuz closure duration matters 3x more than oil price elasticity."

3. **`outputs/scenario_narratives.md`** — Three Opus-written narrative scenarios:
   - **Best case** (p75-p95): Early ceasefire, rapid reopening, NZ stocks hold
   - **Base case** (p25-p75): Protracted conflict, alternative supply, rationing likely but managed
   - **Worst case** (p5-p25): Escalation, cascading failure, NZ rationing within weeks
   Each includes: timeline, turning points, NZ impact sequence, confidence level, assumption dependencies, and "no historical precedent" caveats.

4. **`outputs/methodology.md`** — How the model works, data sources, what it can and cannot predict. Published alongside results.

5. **`outputs/daily_briefing.md`** — Auto-generated when new data arrives. "Today's observations shifted P(rationing 30d) from 68% to 72%, driven by [specific data change]."

**Integration with satint GitHub Pages:**

Autoresearcher outputs exported to `docs/data/scenarios.json` and `docs/data/briefing.json` on the satint-public repo. Dashboard gets a "Scenario Analysis" tab.

## Project Structure

```
autoresearcher-irancrisis/
├── README.md
├── requirements.txt
├── .env                          # FRED_API_KEY, ACLED_KEY, ANTHROPIC_API_KEY
├── run.py                        # CLI: --quick, --fleet, --update, --briefing
├── fleet_run.sh                  # Parallel agent orchestration + synthesis
│
├── clients/                      # Data ingest
│   ├── yfinance_client.py
│   ├── fred_client.py
│   ├── eia_client.py
│   ├── acled_client.py
│   ├── reliefweb_client.py
│   ├── satint_client.py          # Reads satint pipeline docs/data/*.json
│   └── assemble_snapshot.py      # Merge → data/snapshots/YYYY-MM-DD.json
│
├── network/                      # Causal network + forward MC sampler
│   ├── structure.py              # Node definitions, edges, within-day DAG topology
│   ├── nodes.py                  # Node callables: sample(parents, rng) → float
│   ├── calibration.py            # Fit node distributions to observed data + dynamic anchors
│   ├── inference.py              # Forward MC sampling loop (day-by-day, 5000 paths)
│   └── validate.py               # Hard constraints on node parameter values
│
├── explorer/                     # LLM-guided search
│   ├── loop.py                   # Propose → simulate → accept/reject
│   ├── agents.py                 # Agent definitions and mandates
│   ├── accept_reject.py          # Sensitivity/novelty/tail logic
│   ├── cross_pollinate.py        # Share findings between agents
│   └── prompts.py                # Sonnet prompt templates
│
├── synthesis/                    # Opus analysis
│   ├── run_synthesis.py          # Pareto maps, sensitivity, narratives
│   ├── briefing.py               # Daily briefing generation
│   └── prompts.py                # Opus prompt templates
│
├── programs/                     # Agent mandates (markdown)
│   ├── escalation.md
│   ├── nz_fuel.md
│   ├── trade.md
│   ├── recovery.md
│   ├── food.md
│   ├── tail_risk.md
│   └── assumption.md
│
├── data/
│   ├── snapshots/                # Daily world state JSONs
│   └── priors/                   # Baseline CPDs, calibration data
│
├── logs/
│   └── experiments.jsonl         # File-locked experiment log
│
└── outputs/
    ├── probability_dashboard.json
    ├── sensitivity_ranking.json
    ├── scenario_narratives.md
    ├── methodology.md
    └── daily_briefing.md
```

**Dependencies:**

```
yfinance>=0.2.36
fredapi>=0.5.1
anthropic>=0.49.0
numpy>=1.26
pandas>=2.2
scipy>=1.12
requests>=2.31
python-dotenv>=1.0
filelock>=3.13
```

No pgmpy or Mesa dependency. The forward MC sampler is ~200 lines of numpy/scipy.

## MVP Scope

**V1 (build first):** Energy, Maritime, and NZFuel subsystems only. Three explorer agents (escalation, nz_fuel, trade). Quick mode + basic synthesis. Enough to answer "what's the probability of NZ rationing?"

**V2 (add later):** Food/fertiliser system, humanitarian system, remaining 4 explorer agents, daily briefing auto-generation, full GitHub Pages integration.

## Implementation Order

1. Project scaffold, dependencies, .env setup
2. Data clients (yfinance, satint reader, MBIE) + snapshot assembler
3. Network structure (MVP nodes only: ~15 nodes, 3 layers)
4. CPD definitions + calibration against current satint/market data
5. MC inference engine — single scenario run producing distributions
6. Quick mode CLI (`python run.py --quick`)
7. Explorer loop (reuse autoresearcher-nz pattern)
8. 3 agent mandates (escalation, nz_fuel, trade)
9. Fleet run + cross-pollination
10. Opus synthesis
11. Export to satint-public dashboard
