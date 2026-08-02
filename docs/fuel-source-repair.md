# Fuel-model source repair

## Outcome

The fuel model now has a source ladder that distinguishes observations from
proxies and assumptions:

1. **MBIE fuel-stock and shipping publication** — national stock state,
   within/outside-EEZ split, named vessels, published demand denominators, and
   forward-supply horizon.
2. **Channel Infrastructure operational updates** — observed quarterly Marsden
   Point throughput and number of import shipments, kept as separate
   plausibility constraints.
3. **Gas Industry Company workbooks** — daily domestic gas production, major
   electricity/industrial use, and Ahuroa storage as an independent energy-buffer
   context, not a liquid-fuel substitute coefficient.
4. **Public port schedules and AIS** — arrival timing corroboration, not cargo
   product or volume unless the source explicitly publishes those fields.
5. **Latent model behaviour** — contracts, not-yet-departed orders, cargo
   product mix, and cargo volume remain uncertain until a cargo-level source is
   obtained.

The model must not calculate “average cargo size” by dividing Channel's
quarterly throughput by its shipment count. Throughput and vessel discharge
cross different inventory boundaries and the ratio would be a proxy presented
with false physical precision.

## Implemented collection

### MBIE

`ingest_mbie_supply` archives the retrieved official HTML, versions each
publication by SHA-256, ingests all published stock-history rows, converts
days' cover to volume using MBIE's own demand denominators, and stores each
named vessel with its published EEZ zone.

MBIE currently presents an Imperva challenge to an unattended client. The
pipeline records this as `fetch_failed`; it does not replace the last good
snapshot with zero or empty data. A browser-saved copy of the official page can
be ingested without manual re-keying:

```bash
./satint/bin/python manage.py ingest_mbie_supply --html /absolute/path/to/saved-mbie-page.html
```

The normal Wednesday-afternoon schedule attempts a direct retrieval. If MBIE
later permits it, no parser or database change is required.

Source: [MBIE fuel stock and shipping updates](https://www.mbie.govt.nz/building-and-energy/energy-and-natural-resources/energy-generation-and-markets/liquid-fuel-market/fuel-supply-disruption-response/fuel-stock-and-shipping-updates)

### Channel Infrastructure

`ingest_channel_constraints` archives and parses the official Q4 2025, Q1 2026,
and Q2 2026 NZX operational updates plus the terminal/pipeline page. It records:

- quarterly total throughput;
- import shipments received and discharged;
- contracted storage lower bound;
- stated annual throughput range;
- stated share of national demand served; and
- pipeline length.

The quarterly observations enter the immutable simulation input as contextual
constraints. They do not yet alter cargo quantities because they cannot identify
the product, destination, or inventory timing of any individual ship.

Sources: [Channel terminal and pipeline services](https://channelnz.com/what-we-do/terminal-pipeline-services/), [NZX Q1 2026 update](https://www.nzx.com/announcements/470921), and [NZX Q2 2026 update](https://www.nzx.com/announcements/476108).

### Gas Industry Company

`ingest_gas_industry` archives two first-party XLSX workbooks and ingests daily
aggregate context:

- public-pipeline gas production, excluding Kapuni in line with the publisher's
  coverage warning;
- gas use by named electricity generators and representative major industrial
  users; and
- Ahuroa opening, daily change, closing balance, cushion gas, and the explicitly
  derived balance above the cushion line.

The production/use workbook has complete daily dates from 1 January 2018. The
storage workbook has a complete date grid from 1 January 2020 and reconciles
opening plus change to closing balance within its published 0.001 TJ precision.
However, the publisher states that only the most recent calendar year was
received daily and older source history was supplied monthly; those older rows
are therefore marked partial and cannot be used as true daily backtest evidence.
The production workbook does not explicitly state the flow unit, so those
aggregates are stored in published source units and used only for relative comparisons.
Ahuroa is one facility, and closing balance minus cushion gas is not labelled
accessible or nationally available supply.

These observations enter the immutable simulation snapshot as domestic energy
context. They do not alter liquid-fuel demand until a gas-to-liquid-fuel
substitution mechanism beats persistence in untouched historical periods.

Sources: [Gas production and consumption](https://www.gasindustry.co.nz/data/resources/gas-production-and-consumption/) and [Ahuroa gas storage](https://www.gasindustry.co.nz/data/resources/gas-storage/).

## Highest-value public-data request

The next material improvement is an Official Information Act request to MBIE
for aggregated or anonymised extracts of information already reported under
the Fuel Industry Regulations 2021. Request machine-readable daily data from
1 January 2025 onward, with revisions preserved, for:

- onshore stock volume by fuel and terminal or region;
- daily drawings/demand by fuel and terminal or region;
- vessel name or stable anonymised vessel identifier;
- overseas load port and load/departure date;
- date of entry into the New Zealand EEZ;
- fuel type and volume on board;
- New Zealand unload date, port, fuel type, and volume;
- the demand denominator used to calculate days' cover; and
- the date and nature of any revision to those fields.

Ask MBIE to aggregate terminal or importer identifiers where necessary rather
than withhold the time, fuel, volume, and movement fields. Those fields are the
minimum needed to distinguish a genuine supply response from the ordinary
sawtooth of cargo arrivals and stock drawdown.

Regulatory basis: [Fuel Industry Regulations 2021, regulations 41–42](https://www.legislation.govt.nz/regulation/public/2021/0174/latest/whole.html).

## Paid-data trial, if needed

A Kpler or Vortexa trial is useful only if it supplies, historically and going
forward: IMO, vessel name, product/grade, estimated volume, loading terminal,
departure, destination, ETA revisions, arrival, and discharge event. AIS-only
position data does not close the model's cargo-content gap.

The acceptance test should be a rolling-origin comparison at 7, 14, and 21
days against both stock persistence and a seasonal cargo-cycle baseline. No
paid feed should be retained merely because it makes the model more detailed;
it must improve calibration, interval coverage, or forecast skill on untouched
periods.
