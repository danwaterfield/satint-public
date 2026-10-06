# Alternative data sources

Implemented and live-checked on 6 October 2026. These collectors are part of the
normal refresh/Celery paths; the paid aviation trial is deliberately explicit.

## What changed

| Feed | Default path | Separation and quality controls |
| --- | --- | --- |
| Corrected nightlights | Existing VNP46A2 plus NOAA-20 VJ146A2 | Separate satellite baselines, at least seven quality-passing baseline days; one sensor per city's exported chart |
| Atmospheric NO₂ | Copernicus Data Space Sentinel-5P | OFFL when available, otherwise NRTI; no mixing of processing mode/version in a baseline |
| Media context | Downloadable GDELT GKG 2.1 files | All 96 daily partitions; unique document URLs; country-mention theme shares, not DOC search/event counts |
| Aviation fallback | Official Dubai, Doha and Sydney boards | Partial schedule coverage; empty feeds are unknown, not zero; no borrowed OpenSky baseline |
| Internet corroboration | IODA BGP and active probing alongside existing GTR/RIPE | Raw /24 counts retained in their own units, not mislabelled as population connectivity |
| Paid aviation trial | Official FR24 flight-summary light | One request with a result cap; actual UTC movement timestamps; no automatic purchases or scheduled paid calls |

The GKG shares and CDSE observations are exported in `analytical_lenses.json`.
They do not silently replace the legacy GDELT count-based stress component.
The IODA measurements appear in `connectivity_corroboration`. Raw data, checksums,
run states and parser versions are retained for auditing.

### Repairs found while adding the sources

- Black Marble's cloud confidence is **bits 6–7**, not bit 1. Bit 1 is part of
  land/water classification. The old decoder could misclassify clear land as
  cloud. Cloud fraction now includes cloud-screened/fill-radiance pixels in the
  spatial denominator, where cloud flags are available.
- Black Marble extraction now reads only the AOI's raster window and validates
  cached/downloaded HDF5 files before reuse. Fill, scale and offset attributes
  are honoured. A truncated cache file is quarantined as `.h5.invalid`.
- `recompute_baselines` now keeps corrected products separate and clears
  unsupported comparisons. It does not combine corrected radiance with raw DNB.
- NO₂ extraction preserves masks and valid negative retrievals rather than
  clipping the distribution upward. The legacy `cloud_fraction` field represents
  the rejected-pixel fraction for NO₂; metadata makes that distinction explicit.
- Internet ingestion no longer labels a Google usage mean/minimum as BGP/probing.
- Stale-source notices no longer assert satellite processing lag without evidence.

## Live validation

- **VJ146A2:** searched the full 15 January–27 February baseline and recent dates
  for the tile covering Tehran and Isfahan. Wrote 78 usable baseline observations
  and 16 recent observations. There are **24** quality-passing baseline days for
  Tehran and **31** for Isfahan. Recent coverage reaches **27 September**.
  Other cities can be backfilled with the command below; this validation did not
  download the entire Gulf historical archive.
- **CDSE:** retrieved and processed Tehran on **4 October** (582 usable pixels).
  Marked partial because about 33.8% of pixels were rejected. The NRTI processing
  version has no matching local historical baseline, so no percentage change is
  published. A 29 September OFFL search was empty; this established the need for
  the explicit NRTI fallback.
- **GKG:** all **96** partitions for **4 October** processed, producing **98**
  country/theme share records. One file contained an invalid UTF-8 character in
  an unused text field. Replacement decoding is permitted for descriptive text;
  corrupt document IDs, URLs, dates or theme fields reject the partition. No
  GKG historical baseline has been backfilled yet; exported changes remain null.
- **Airport boards:** all three fallback collectors returned rows for **5 October**.
  These are partial local-day schedule observations, not verified full-day totals.
- **IODA:** eight BGP/probing measurements across Iran, Iraq, UAE and New Zealand
  were ingested for **5 October**.
- **FR24:** adapter tested with fixtures; no API token is configured, so no paid
  request was made. A trial remains necessary to evaluate Gulf airport coverage.
- **Radar:** no Radar token is configured in the current environment. A token with
  **Account → Radar → Read** is required; HTTP 401/403 are recorded as auth failures.
- **MBIE:** existing browser-HTML ingestion remains the fallback. No equivalent
  public national fuel-stock feed was established, and port activity is not used
  as a substitute. See [fuel-source-repair.md](fuel-source-repair.md) for the
  proposed machine-readable data request. No message was sent to MBIE.

## Reproducible operation

Apply migration `0021_alternative_no2_provenance` before running the new NO₂ path.
It retains existing readings under `NASA_S5P_NO2_LEGACY` and allows separately
identified products on the same city/date.

```bash
./satint/bin/python manage.py migrate

# Backfill a NOAA-20 baseline; downloaded files are cached.
./satint/bin/python manage.py ingest_alternatives nightlights \
  --city Tehran --start 2026-01-15 --end 2026-02-27

# Current NOAA-20 observations; omit --city for the existing Gulf bounding box.
./satint/bin/python manage.py ingest_alternatives nightlights \
  --city Tehran --start 2026-09-20 --end 2026-10-05

# NO2 selects OFFL, then NRTI if no OFFL product exists.
./satint/bin/python manage.py ingest_alternatives no2 \
  --city Tehran --start 2026-10-04

# A full GKG day. Rerunning retries missing files and reuses valid cached files.
./satint/bin/python manage.py ingest_alternatives gkg --start 2026-10-04

# Optional GKG baseline: substantial download; every day needs 96 files.
./satint/bin/python manage.py ingest_alternatives gkg \
  --start 2026-01-15 --end 2026-02-27

# Explicit paid trial, only after setting FR24_API_TOKEN in the local environment.
./satint/bin/python manage.py trial_fr24 OMDB --date 2026-10-04 --limit 1000

./satint/bin/python manage.py recompute_baselines --force
./satint/bin/python manage.py export_static
```

The FR24 query includes a 48-hour lookback because its date filter uses
`first_seen`, not arrival time. Responses that hit the cap are rejected as
truncated. Even an uncapped response stays partial until coverage is validated;
trial observations live separately from operational flight totals.

NO₂ historical backfills must use matching mode/version. A baseline from an
older processing version is not automatically borrowed. GKG baseline comparisons
require at least seven complete daily partitions and use percentage-point changes
in theme share. Missing country coverage remains null.

Normal refresh defaults are `TROPOMI_PROVIDER=cdse` and `GDELT_BACKEND=gkg`.
The legacy routes remain available with `TROPOMI_PROVIDER=nasa` and
`GDELT_BACKEND=doc`. Credentials belong in `.env`, not source control.

The implementation and generated exports are local workspace changes. Public
GitHub Pages publication still requires committing and pushing the intended
`docs/` artifacts; see [deployment.md](deployment.md).

## Provider references

- [NASA VJ146A2](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VJ146A2/)
- [NASA Black Marble user guide, including cloud flags](https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/Document%20Archive/Science%20Data%20Product%20Documentation/VIIRS_Black_Marble_UG_v1.3_Sep_2022.pdf)
- [Copernicus OData catalogue and downloads](https://documentation.dataspace.copernicus.eu/APIs/OData.html)
- [GDELT data and codebooks](https://gdeltproject.org/data.html)
- [GDELT theme dictionary](https://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT)
- [FR24 flight-summary documentation](https://fr24api.flightradar24.com/docs/endpoints/flight-summary)
- [IODA signal definitions](https://ioda.inetintel.cc.gatech.edu/resources?tab=glossary)
- [Cloudflare Radar token permissions](https://developers.cloudflare.com/radar/get-started/first-request/)

## Validation

The 54-test source, quality, ingestion, export, compound-indicator, analytical-lens,
and static-chart suite passed. After the final flight-provenance adjustment,
the 26 directly affected tests passed again. All 21 exported JSON artifacts
passed strict JSON parsing and manifest size/hash verification. The refreshed
local dashboard displays two corrected Black Marble cities, with observations
through 27 September, and produced no browser console errors during verification.
