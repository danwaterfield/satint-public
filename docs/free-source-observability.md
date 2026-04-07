# Free-Source Observability Layer

This repo now includes a domestic NZ supply-chain reference layer built from
publicly accessible sources that do not require paid API access.

## Implemented Sources

- `Woolworths NZ` anonymous public product search API
  - Captures a daily essential-goods basket across fixed probes such as milk,
    bread, eggs, rice, infant formula, paracetamol, and toilet paper.
  - Stored in `RetailProductSnapshot`.
  - Exported in `docs/data/nz_supply_chain.json` and embedded in
    `docs/data/fuel_security.json`.

- `Port of Auckland` public vessel schedule pages
  - Expected arrivals via public CSV.
  - Recent departures via public CSV.
  - Vessels in port via public HTML table.
  - Stored in `PortCallSnapshot`.

- `Port of Tauranga` public shipping schedules page
  - In-port and expected-arrivals tables parsed from public HTML.
  - Stored in `PortCallSnapshot`.

## Operator Entry Points

- Manual ingest:
  - `./satint/bin/python manage.py ingest_nz_supply_chain`

- Full refresh:
  - `./satint/bin/python manage.py refresh_intelligence`

- Static export:
  - `./satint/bin/python manage.py export_static`

## Key Caveats

- Woolworths is currently **not store-scoped**.
  - The signal is best read as catalog depth and coarse stock state, not a
    confirmed per-store shelf-out dataset.
  - It is still useful for time-series changes in basket depth, low-stock
    frequency, and entry-price movement.

- Foodstuffs properties (`New World`, `PAK'nSAVE`) were not added in this pass.
  - Their public sites are Cloudflare-protected against straightforward scripted
    access from this environment.
  - A future pass should revisit them with a browser-backed collector or a more
    durable connector.

- Port of Auckland arrival/departure feeds do not publish cargo classes in the
  current public CSVs.
  - Those rows are still valuable for vessel-flow counts and timing, but cargo
    categorisation is richer for Tauranga than Auckland at present.
