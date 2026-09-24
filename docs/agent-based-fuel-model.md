# Agent-based maritime fuel model

**Model version:** `nz-maritime-fuel-abm-v1.4.0`
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

The output now keeps two layers separate:

- **raw process paths** are the physically conserved ABM runs; and
- **observable forecasts** shrink the raw change towards the latest published stock state by a weight learned after parameter selection, then widen the onshore P10–P90 interval using cross-fitted historical residuals.

Version 1.4 retains 30% of the simulated stock change. That is an empirical correction, not a physical flow. Conservation therefore applies to the raw paths, and both layers remain visible in private output. Reported bands still omit political and structural surprises outside the scenario design.

## Historical calibration and validation

Backtesting now uses four distinct roles for history:

1. **Parameter fitting (8 March–3 May):** 120 candidate parameter sets are scored from four rolling origins, each forecasting no more than 21 days. The score combines onshore (60%), on-water (30%), and total (10%) error.
2. **Forecast calibration (6–31 May):** the retained parameter sets are frozen. Publication-date leave-one-out cross-fitting estimates how much of the simulated stock change to retain and constructs empirical interval residuals without scoring a release using a correction trained on that same release.
3. **Fixed holdout (3 June–19 July):** one forecast from the 31 May observed state is compared with four predeclared baselines.
4. **Rolling-origin audit:** four 14-day forecasts are reinitialised on 31 May, 14 June, 28 June, and 12 July to test the way the model would operate as new releases arrive.

Later transit observations remain an explicitly labelled *observed conditioning path*. They are never allowed into an earlier input snapshot. The fixed holdout is unchanged from the previous repair work, but it should no longer be called untouched: it has now informed several development rounds.

Candidate sets are retained by history matching rather than collapsed into one apparently precise optimum. A run becomes technically publishable only when all of these gates pass:

1. fixed-holdout onshore and weighted stock-system MAE are each at most five days;
2. at least 70% of held-out onshore targets fall inside the calibrated nominal 80% interval;
3. mean calibrated interval width is at most 16 days, so coverage cannot be bought with an unbounded interval;
4. rolling parameter-fit stock-system MAE is at most five days;
5. the observable forecast achieves at least 5% skill over the strongest of persistence, recent-three median, damped robust trend, and four-week cycle baselines on both fixed-holdout targets;
6. the same +5% benchmark-skill requirement passes in at least three rolling-origin folds;
7. the historical record contains as-known publication vintages rather than only a later retrospective archive;
8. daily raw-path mass-conservation error remains below `1e-7`; and
9. the current input snapshot meets the data-coverage gate.

Passing those checks is still not sufficient to publish. The command also requires an explicit `--publish` approval. Failed, insufficient, and merely unapproved results stay quarantined from the public scenario payload.

### Current historical result

Version 1.4.0 remains rejected. Across 120 candidate sets, 12 retained sets, and three stochastic replicates per set:

- rolling parameter-fit stock-system MAE: **5.5116 days** (fails the five-day fit gate);
- raw fixed-holdout onshore MAE: **2.5448 days**;
- observable fixed-holdout onshore MAE: **2.2848 days**, versus **2.1638** for the best onshore baseline (**−5.6% skill**);
- observable stock-system MAE: **3.1928 days**, versus **3.0872** for the best system baseline (**−3.4% skill**);
- raw nominal-80% coverage: **50.0%** at **5.1542 days** mean width;
- calibrated nominal-80% coverage: **97.22%** at **10.2517 days** mean width;
- rolling-origin onshore/system skill: **−14.92% / −5.89%**; and
- maximum raw-path conservation error: **9.66e-13** (passes).

The correction retains **30%** of the simulated stock change; leave-one-publication-date-out weights range from **0% to 37%**. The uncertainty repair is therefore useful but conservative, and it does not create predictive skill.

The provenance gate also fails. All retrospective stock observations used here are preserved from one 29 July archive and source hash. They are official historical values, but the project cannot yet demonstrate that each value is the exact, unrevised information available at each historical forecast origin. Prospective shadow validation is required.

Accordingly, the model remains experimental and is not exported to the public dashboard. The reproducible v1.4 bundle is stored in `analysis/model_validation_v140.json`, with long-form holdout and ablation CSVs and an executed notebook under `output/jupyter-notebook/`. Earlier diagnostic and repair artifacts remain as versioned failure records.

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
