# Analytical lenses and supporting sources

The dashboard's primary interpretive framework is a causal evidence chain:

1. **Shock** — direct physical hazard and systemic trade/price shocks.
2. **Buffer** — stocks, alternate suppliers, institutional capacity, and other shock absorbers.
3. **Service** — electricity/activity, connectivity, mobility, water, and essential-supply continuity.
4. **Welfare** — household costs, shortages, displacement, health, and other human effects.

This prevents an upstream disruption and its downstream consequence from being silently counted as independent evidence of the same thing. Signals that measure the same latent phenomenon are grouped into one family and consume that family's weight only once.

## Counterfactual selection

Every supported signal stores an observed value, an expected value, an expected-value interval, the abnormal residual, and the method used. The estimator selects the strongest available transparent method in this order:

1. same-season observations from previous years;
2. an ordinary least-squares relationship with a date-matched control location;
3. the median and empirical interval of the 15 January–27 February 2026 pre-event baseline.

The control model is deliberately simple and auditable. Where the available history cannot support it, the model falls back rather than extrapolating. The interval is an empirical/model uncertainty band, not automatically a 95% probability statement.

## Missing data and publication

Missing, failed, and rejected observations are not zeroes. They reduce the coverage score and widen the lower/upper stress bounds. An overall layered score is published only when:

- weighted coverage is at least 60%;
- service-layer coverage is at least 40%; and
- at least two causal layers have usable evidence.

The component evidence and bounds remain available when the point score is withheld.

## New sources

### JODI Oil World Database

The weekly poll ingests the current year's official primary and secondary oil CSV files for monitored Gulf producers, key Asian refiners, and New Zealand. It preserves product, flow, assessment code, and the published KBD/KBBL unit. Country submissions differ in timeliness and quality, so values should be used for balance and trend checks rather than real-time vessel attribution.

### Stats NZ overseas merchandise trade

The pipeline discovers the newest monthly HS10-by-country import file and calculates exposure for refined fuels, fertilisers, industrial chemicals, primary plastics, pharmaceuticals, and selected staples. It reports:

- direct Gulf-partner share;
- a low/mid/high Hormuz-route exposure scenario;
- supplier concentration (HHI); and
- the top-three supplier share.

Partner country is not a shipping route. The exposure band is a documented scenario and must not be presented as observed cargo routing. Cargo-level AIS or customs routing data can later replace these assumptions.

### Connectivity corroboration

RIPE Atlas connected-probe share is stored as an independent host-sample check on IODA. Its denominator is connected plus currently disconnected probes, excluding abandoned and written-off devices; the all-time registered count is retained only as metadata. Atlas probes are sparse and non-random, so the ratio is not a percentage of people online. Cloudflare Radar anomaly ingestion is available when `CLOUDFLARE_RADAR_API_TOKEN` is configured. If it is absent, the ingestion run records `auth_failed`; the pipeline does not interpret that as normal traffic.

## Deliberately deferred integrations

The generic `ExternalIndicatorObservation` envelope supports future humanitarian and environmental sources, but they are not yet scored merely because an API exists:

- **UNHCR/IOM displacement:** appropriate for the welfare layer after geography, reporting-period, and revision semantics are reconciled; annual UNHCR stock data is too slow to stand in for current conflict displacement.
- **FAO WaPOR / GIEWS and ERA5-Land:** useful for separating conflict effects from rainfall, heat, evapotranspiration, and seasonal crop conditions. These need crop masks and same-season baselines before entering a score.
- **OONI:** useful for identifying censorship and blocking mechanisms, but test-volume and user-selection effects require a dedicated normalisation model.

These remain planned corroborating sources rather than zeros or inferred evidence.

## Operator commands

Run the full refresh with:

```bash
python manage.py refresh_intelligence
```

For just the new layers in an interactive Django environment, run the four task functions in `pipeline.analytical_tasks`: JODI, Stats NZ exposure, counterfactual estimates, then causal-layer indicators. Static publication remains `refresh_intelligence` → `export_static` → committed `docs/data/` on `main`.
