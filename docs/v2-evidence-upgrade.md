# V2 Evidence and Reproducibility Upgrade

## Objective

Make the public dashboard explicit about what was observed, what is inferred,
what is modeled, and what is unknown. The v2 pipeline must not convert a failed
request into a zero, infer facility damage from FIRMS alone, mix incompatible
satellite products, or slide scenario dates forward when a reader opens a stale
export.

## Implemented sequence

1. Repository reproducibility
   - Django project files are no longer hidden with the historical virtualenv.
   - New virtual environments use `.venv/`; direct runtime dependencies and
     development checks are declared separately.
2. Provenance and source state
   - `SourceDataset`, `IngestionRun`, `RawArtifact`, and
     `ObservationProvenance` record the source, request partition, retrieval
     outcome, parser version, checksums, and observation quality.
   - Observation states distinguish observed zero, no records, no coverage,
     partial data, rate limiting, authentication failure, retrieval failure,
     parse failure, and quality rejection.
3. Satellite quality
   - VNP46A2 files are grouped by acquisition date, all intersecting tiles are
     mosaicked, and only Mandatory Quality Flag 0 pixels are used.
   - Raw DNB L1B observations are exported separately as provisional and are
     never compared with a VNP46A2 baseline.
   - Sentinel-2 red, NIR, and SCL rasters are aligned; water, shadow, cloud,
     cirrus, snow and invalid pixels are removed. Baselines are product-specific
     and season-matched to 2024/2025.
4. Evidence semantics
   - FIRMS produces `no qualifying anomaly`, `anomaly near site`, or
     `persistent anomaly` evidence. It does not produce operating, offline,
     damaged, destroyed, or strike assessments.
   - IODA is labelled as a normalized Google usage signal rather than a
     percentage of people connected.
   - OpenSky and GDELT failures do not create zero-count observations.
5. Compound stress
   - One scheduled v2 model stores raw values, source dates, transformations,
     declared and used weights, local stress, systemic trade exposure, model
     version, and coverage.
   - Missing components are omitted, partial components receive half weight,
     and publication requires at least 60% local component coverage plus a
     nightlight or NO2 anchor.
6. Fuel scenarios
   - Scenario paths are anchored to their model as-of date and current Hormuz
     observation, while long-run stress uses elapsed crisis time.
   - Physical cover, legally eligible MSO stock, the 14-day operational
     pressure threshold, and rationing are distinct. MSO dates are withheld
     when eligible incoming stock is unknown; rationing dates are not emitted.
   - Scenario bands are deterministic ±20% sensitivity ranges, not probability
     intervals.
7. Static export and presentation
   - Export is staged, validated, checksummed, and atomically promoted.
   - The UI recomputes freshness in the browser, shows observation, ingestion,
     model, and export dates separately, lazy-loads secondary tabs, vendors its
     pinned chart/map runtimes, and exposes keyboard-accessible explanations.

## Operational consequence

The migration marks legacy observations `unknown` because their historical
retrieval outcome was not recorded. This is intentional. Run fresh source
ingestions to populate v2 provenance before expecting compound-stress rows to
be publishable. A coverage-gated empty state is preferable to a falsely normal
score.

## Verification gates

```bash
./satint/bin/python manage.py check
./satint/bin/python manage.py makemigrations --check --dry-run
./satint/bin/python manage.py test pipeline.tests
./satint/bin/python manage.py export_static --output-dir docs/data
python3 -m json.tool docs/data/manifest.json >/dev/null
```
