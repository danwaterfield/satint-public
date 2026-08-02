# Agent-based maritime fuel model

**Model version:** `nz-maritime-fuel-abm-v1.3.0`  
**Purpose:** explore conditional second- and third-order effects of the Iran crisis on New Zealand's refined-fuel supply.  
**Status:** experimental until the historical holdout gates pass and an operator explicitly approves publication.

This is a decision-support model, not a prediction of political or military events. It asks a narrower question: *if a stated chokepoint and market scenario occurs, how might adaptive decisions by refiners, importers, competing buyers, demand sectors, and government change New Zealand's physical fuel cover?*

## ODD summary

### Purpose and outputs

The primary outcomes are daily distributions, by fuel and scenario, for:

- effective physical cover (onshore stock plus only those pending shipments due before the preceding cover would be exhausted);
- the conditional frequency of falling below the 14-day operational pressure threshold;
- first threshold-crossing date;
- cumulative unmet demand in demand-day units;
- wholesale scarcity-price index; and
- allocation, shipment, reserve-release, and mass-conservation diagnostics.

The 14-day line is an analytical pressure threshold. It is not a forecast of rationing and is not a statutory Minimum Stockholding Obligation compliance test.

### Entities and state variables

| Entity | Representative role | Main state and decisions |
|---|---|---|
| Refineries | South Korea, Singapore, Japan, and Atlantic supply | Product capacity, crude buffer, Gulf-crude exposure, substitution, and production offered to the market |
| Importers | Three representative New Zealand importers plus large Asian and European buyers | Inventory, desired cover, contract share, bids, orders, and deliveries |
| Shipments | Batches of petrol, diesel, or jet fuel | Origin, destination, route, departure, expected arrival, delay, and loss state |
| Demand sectors | Freight, emergency services, agriculture, aviation, and discretionary road demand | Fuel requirement, allocation priority, price elasticity, conservation, and unmet demand |
| Government | A stylised reserve-release rule | Reserve stock, release threshold, daily release limit, and released volume |
| Market | A transparent daily allocation mechanism | Contract-protected allocation first, then price-ranked spot allocation under available refinery supply |

Agents represent classes of actors, not named companies or individual people. The spatial resolution is deliberately too coarse for military targeting or facility-level operational inference.

### Process and scheduling

Each simulated day proceeds in this order:

1. Apply the scenario's Hormuz, Bab al-Mandeb, Malacca, and Cape capacity paths and correlated disruption noise.
2. Receive due shipments.
3. Apply demand response at the current price, essential-service priority, and any rule-based reserve release; then record supplied and unmet demand.
4. Let importers place baseline replacement orders plus bounded catch-up orders based on reachable inventory, price, risk tolerance, and target cover.
5. Let refineries produce subject to crude buffers, Gulf exposure, bypass supply, and gradual substitution.
6. Clear the contract and spot market, accumulate allocations at origin, and dispatch route-dependent cargo batches once their lot threshold is reached.
7. Record stocks, total pipeline, contiguous effective cover, prices, service pressure, and mass balance.

All quantities use **New Zealand average demand-days** as the common accounting unit. This keeps the stock-flow ledger auditable while the open data do not support reliable cargo-level volume attribution.

## Scenarios

The engine runs six externally specified scenario families:

- **Status quo:** current disruption persists.
- **Partial reopening:** capacity improves but remains impaired.
- **Full reopening:** gradual normalisation.
- **Compound chokepoint:** Hormuz disruption combines with Bab al-Mandeb degradation and Cape congestion.
- **Supply competition:** large buyers compete more aggressively for non-Gulf refined supply.
- **Stop-start reopening:** improvement is interrupted by renewed disruption.

These scenario paths are conditions, not probabilities assigned to geopolitical outcomes. A result such as “35% below 14 days” means 35% of sampled model runs crossed the line **given that scenario, the observed starting state, and the documented parameter ranges**.

## Evidence snapshot

Every run receives an immutable, date-bounded input object. The adapter refuses observations dated after the run's `as_of_date`. Its content hash, coverage score, observation counts, source dates, parameter registry, seed range, model version, and output diagnostics are stored with the run.

Inputs currently include:

- MBIE onshore, on-water, and total physical fuel-cover observations, retaining the within/outside-EEZ split where published;
- versioned MBIE releases, demand denominators, and named vessels by EEZ zone, without assigning unobserved product or volume to a ship;
- Channel Infrastructure quarterly throughput, import-ship count, storage, demand-share, and pipeline statements as separate plausibility constraints rather than inferred cargo sizes;
- Gas Industry Company daily public-pipeline production/use and Ahuroa storage observations as domestic energy-buffer context, without an unvalidated gas-to-diesel substitution coefficient;
- source-matched commercial chokepoint transit ratios, preferring IMF PortWatch for the historical path;
- MBIE retail/import price observations;
- war-risk premium observations;
- Stats NZ trade-exposure bands and supplier concentration; and
- recent JODI observations as contextual evidence.

Missing observations remain missing. They reduce coverage and cannot silently become normal conditions or zero stress.

Fuel-stock rows retain the archived source-file SHA-256, publication vintage, optional public URL and retrieval time, and source-specific metadata. Small HTML/CSV/JSON source payloads are retained for replay. Each MBIE publication is versioned by effective stock date and content hash; named vessels are stored separately because their fuel and cargo volume are not public. A blank URL or retrieval time means it was not recoverable from the archived artifact; the pipeline does not invent one.

Transit gaps are bounded. A directly observed value may be carried forward for at most seven days; longer internal gaps are explicitly interpolated between observations, while a trailing gap falls back to the declared prior. Commercial crossing counts remain route-capacity evidence and are not treated as a crude-volume series for refineries.

## Uncertainty and reproducibility

Uncertain behavioural and operational parameters are sampled from bounded triangular distributions. Bounds, defaults, source labels, confidence labels, and calibration roles live in the parameter registry. Seeds are explicit and deterministic: rerunning the same version, snapshot, parameter set, scenario, and seed produces the same result. Different seeds vary cargo voyage times, latent product-cohort sizes, and the number of product cohorts within each published shipping zone. Reported tanker counts cap the possible timing slots; they no longer imply that every reported ship carries every fuel. Cargo batching prevents variation from being averaged across implausibly tiny daily shipments, while the published aggregate on-water stock remains exactly conserved.

Reported bands are empirical ensemble quantiles (`p10`, `p50`, `p90`). They express model and parameter uncertainty inside the chosen scenario. They do not include every form of structural, political, measurement, or surprise-event uncertainty.

## Historical calibration and validation

Backtesting preserves the time boundary:

- the model starts from the stock snapshot available on the historical start date;
- later transit observations form an explicitly labelled *observed conditioning path* and are not allowed into the initial snapshot;
- stock observations through the calibration cutoff jointly score onshore (60%), on-water (30%), and total (10%) stock-system error;
- the observed stock and pipeline state at the calibration cutoff is assimilated as the information set that a real forecast would possess; and
- later stock observations are held out for validation and never used to choose parameters or mechanisms.

Candidate sets are retained by history matching rather than collapsed into one apparently precise optimum. A run becomes technically publishable only when all of these gates pass:

1. holdout mean absolute error is at most five stock-cover days;
2. at least 70% of held-out targets fall inside the model's 80% ensemble interval;
3. retained calibration stock-system MAE is at most five days;
4. the model achieves at least 5% skill over naive persistence from the holdout-boundary stock observation;
5. the daily stock-flow mass-conservation error remains below `1e-7`; and
6. the current input snapshot meets the model's data-coverage gate.

Passing those checks is still not sufficient to publish. The command also requires an explicit `--publish` approval. Failed, insufficient, and merely unapproved results stay quarantined from the public scenario payload.

### Current historical result

The unchanged 1 June–19 July holdout still rejects version 1.3.0. Across 120 candidate sets, 12 retained parameter sets, and three voyage-time replicates per set:

- calibration stock-system MAE: **4.9243 days** (passes the five-day gate);
- holdout onshore-stock MAE: **2.7095 days** (passes the five-day absolute-error gate but is worse than persistence);
- 80% interval coverage: **50.0%** (up from 41.67% in version 1.2.0, but still below the 70% gate);
- 31 May persistence MAE: **2.2667 days**, giving the model **−19.54% persistence skill** (fails the new +5% gate); and
- maximum absolute mass-conservation error: **1.03e-12** (passes).

Version 1.3.0 is structurally more honest but not more accurate at the median: it removes the implicit assumption that every reported tanker supplies every product, which widens the ensemble towards the observed cargo-cycle variability, but petrol/diesel/jet product assignment and discharge timing remain unidentified. That is a reason to keep the ensemble quarantined, not to narrow the intervals or weaken the benchmark.

Accordingly, the model remains experimental and is not exported to the public dashboard. The reproducible repair result is stored in `analysis/historical_miss_repair_validation.json`; the earlier diagnostic is retained as the version 1.0.0 failure record.

## Operation

Apply migrations, then run a small private smoke test:

```bash
python manage.py migrate
python manage.py run_fuel_simulation --no-save --runs 10 --horizon-days 30 --scenario status_quo
```

Refresh the two improved domestic supply sources:

```bash
python manage.py ingest_channel_constraints
python manage.py ingest_mbie_supply
python manage.py ingest_gas_industry
```

If MBIE presents its browser challenge, save the official page as HTML and run
`python manage.py ingest_mbie_supply --html /absolute/path/to/page.html`. A
challenge is retained as a failed fetch and never becomes an empty observation.

Run the historical calibration/holdout exercise and all scenarios:

```bash
python manage.py run_fuel_simulation --backcast --runs 500 --horizon-days 182
```

Inspect the validation diagnostics. If the evidence and outputs are fit for publication, rerun with explicit approval:

```bash
python manage.py run_fuel_simulation --backcast --runs 500 --horizon-days 182 --publish --force
python manage.py export_static
```

The normal refresh leaves the ABM untouched. To include a fresh experimental run in an operator refresh, use `refresh_intelligence --include-fuel-abm`; add `--fuel-abm-backcast` for validation and `--fuel-abm-publish` only after review.

## Interpretation limits

- The model does not forecast attacks, ceasefires, state decisions, or individual-firm behaviour.
- Representative agents are a testable abstraction; they do not identify actual contracts, cargo owners, destinations, or inventories.
- Open transit observations measure passage or activity, not guaranteed delivery of usable fuel to New Zealand.
- Demand-day accounting is deliberately simpler than a full litre-, grade-, terminal-, and regional-distribution model.
- Results are most useful for comparing mechanisms and intervention timing across scenarios. Point estimates and precise dates should not be used alone for operational decisions.
- Publication should remain focused on civilian service continuity and systemic resilience, never target selection or military damage assessment.

## Code map

- `pipeline/simulation/schema.py` — immutable input and backcast schemas
- `pipeline/simulation/parameters.py` — versioned parameter registry and sampling
- `pipeline/simulation/agents/` — agent rules
- `pipeline/simulation/network.py` — routes and scenario paths
- `pipeline/simulation/market.py` — allocation and price formation
- `pipeline/simulation/model.py` — daily event loop and conservation ledger
- `pipeline/simulation/ensemble.py` — seeded ensembles, quantiles, and sensitivity
- `pipeline/simulation/calibration.py` — history matching and holdout validation
- `pipeline/simulation/snapshots.py` — point-in-time Django data adapter
- `pipeline/management/commands/run_fuel_simulation.py` — operator entry point
