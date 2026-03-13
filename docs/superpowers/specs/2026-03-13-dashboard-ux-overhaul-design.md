# Dashboard UX Overhaul — Design Spec

**Date:** 2026-03-13
**Scope:** GitHub Pages static dashboard (`docs/index.html`) + Django export command
**Goal:** Transform the dashboard from a data display into an intelligence product that tells the story of the war's civilian impact — usable both as an operational tool and a publication-ready resource for journalists/researchers.

---

## 1. Problem Statement

The current dashboard presents data but doesn't tell a story. An analyst landing cold sees 12 risk cards, a single-city nightlight chart, and tables mixing Gulf and NZ data. The strongest findings (synchronized Mar 7 grid collapse, Hormuz emptying, Ras Laffan damage) are invisible unless you already know what to look for.

Professional crisis dashboards (ACLED, IISS Myanmar, UNDP CRD) all lead with narrative context and use progressive disclosure. Ours should too.

## 2. Target Audiences

- **Operator (primary):** Needs dense data tables, all metrics visible, operational detail for daily monitoring.
- **Journalist/researcher (secondary):** Needs to understand the story in 60 seconds, cite methodology, download data.

Both audiences are served by a single page with clear visual hierarchy: narrative and hero charts at top (journalist reads and stops), operational detail below (operator scrolls and works).

## 3. Page Structure (Top to Bottom)

### 3.1 Topbar (modified)

**Current:** Title, status dot, date, NZ link, auto-refresh note.
**Change:** Add "Methodology" anchor link between NZ link and auto-refresh. Clicking scrolls to Section 5.

### 3.2 Section 1 — Situation Brief

A new section immediately below the topbar, before the existing summary stat cards.

**Auto-generated narrative block:**
- 3-4 sentences synthesized from the latest data
- Generated server-side in `export_static` management command and included in `meta.json`
- Template-driven with explicit logic:
  - **Worst city:** City with lowest `pct_change` on the latest date in `nightlights.json` (Gulf cities only)
  - **Hormuz:** Latest `pct_change` from `sar.json` for "Strait of Hormuz"
  - **Damaged facilities:** Count of facilities where `damage_detected=True` in `ThermalSignature` table, most recent date; name the first one
  - **Internet:** Countries where latest `InternetOutage.pct_change < -10%`, ordered worst-first
  - If a metric has no concerning data, omit that sentence (brief is 2-4 sentences, not fixed at 4)
- Example output: *"Tehran nighttime radiance has collapsed 78% from pre-war baseline, consistent with widespread power grid failure. Strait of Hormuz vessel traffic has fallen to 45% of normal. Ras Laffan LNG (Qatar) sustained strike damage on Mar 6. Saudi Arabia internet connectivity remains degraded at -17.5%."*
- Styled as a blockquote-like element with left border accent, slightly larger font than body text

**Data freshness warning:**
- If any primary data source is >3 days stale, show a yellow banner below the narrative: "Nightlight data is 5 days old (latest: Mar 8). NASA processing lag — not a pipeline failure."
- Generated from `meta.json` timestamps vs current date

**Summary stat cards (existing, modified):**
- Keep: Locations Monitored, Emergency/Critical, Infrastructure Fires (48h), Facilities Damaged, Data Sources Integrated
- No structural change, just ensure they reflect current data correctly

### 3.3 Section 2 — Hero Charts

Three charts that tell the story. These replace the current nightlight chart + vessel table in the two-column layout.

#### 3.3.1 Multi-City Nightlight Overlay (full width)

- **Chart type:** Plotly line chart, all Gulf cities overlaid (% change from baseline, not raw radiance)
- **X-axis:** Date (Jan 15 → present)
- **Y-axis:** % change from pre-war baseline
- **Lines:** One per Gulf city (Tehran, Dubai, Doha, Kuwait City, Riyadh, Abu Dhabi, Manama, Isfahan, Basra). Color-coded. NZ cities excluded.
- **Annotations:** Three vertical dashed lines with labels:
  - "War begins" at Feb 28
  - "Major strikes" at Mar 6
  - "Grid collapse" at Mar 7
- **Horizontal reference:** Dashed line at 0% (baseline)
- **Interactivity:** Plotly legend click to toggle cities on/off (built-in). No custom dropdown needed.
- **Data freshness tag:** Small grey text in section header: "Latest: Mar 8 (5d ago)" computed from data
- **Height:** ~320px

**Data source:** Existing `nightlights.json` — already has per-city time series with `pct_change`. Just need to render all cities simultaneously instead of one at a time.

#### 3.3.2 Fire Activity Time Series (half width, left)

- **Chart type:** Plotly stacked bar chart, daily fire count by country
- **X-axis:** Date (Feb 28 → present, war period only)
- **Y-axis:** Fire count
- **Stacks:** Use existing region groupings from `_export_fires`: Iran, Saudi Arabia, UAE/Qatar/Bahrain, Iraq, Kuwait (these are pre-defined bounding boxes that cannot be trivially split further)
- **Annotations:** Same three vertical event lines as nightlight chart
- **Data freshness tag:** "Latest: Mar 12"
- **Height:** ~260px

**Data source:** `fires.json` already has `{dates, regions}` structure with per-region daily counts. Currently rendered as a map only — this adds the time series view.

#### 3.3.3 Hormuz Vessel Traffic (half width, right)

- **Chart type:** Plotly scatter + line chart showing coverage-normalised vessel count over time
- **X-axis:** Date
- **Y-axis:** Normalised vessel count
- **Horizontal reference:** Dashed line at baseline value (123.6) with label "Pre-war baseline"
- **Annotations:** Key points labeled: "+114% war-day rush" at Feb 28, "-55% strait emptying" at Mar 9
- **Data freshness tag:** "Latest: Mar 9"
- **Height:** ~260px

**Data source:** `sar.json` has Strait of Hormuz records with `vessel_count`, `baseline_count`, `pct_change`, and `scene_coverage` per observation. The chart needs a `normalised_count` field (= `vessel_count / scene_coverage`) which does **not** currently exist in the export. `_export_sar` in `export_static.py` must be modified to compute and include this derived field.

### 3.4 Section 3 — Compound Risk Cards

**Current:** 12 risk cards showing 3 sub-scores each, mixing Gulf and NZ cities.
**Changes:**

1. **Gulf only** — Remove Mumbai, Karachi, Singapore (low signal, dilute the grid). Keep: Tehran, Dubai, Doha, Kuwait City, Riyadh, Abu Dhabi, Manama, Isfahan, Basra (9 cities).
2. **All 8 sub-scores visible** — Currently shows Nightlight/Fire/Trade. Add: NO2, Internet, Flights, GDELT, Thermal. These 5 additional scores are **not stored on the `CompoundRiskIndicator` model** — they must be computed on-the-fly in `_export_compound_risk` by joining against `NO2Reading`, `InternetOutage`, `FlightActivity`, `GDELTEventCount`, and `ThermalSignature` tables for the same AOI and date. This avoids a model migration. Use a compact 4×2 grid within each card instead of the current 3-column layout.
3. **Sorted worst-first** — Already the case, keep it.

### 3.5 Section 4 — Operational Detail

Six panels in a 2-column grid. These are the existing panels reorganized and cleaned up.

#### 3.5.1 Fire Map + Infrastructure Proximity (left)
- Existing Leaflet fire map — no change
- Existing proximity alerts table below it — no change

#### 3.5.2 Infrastructure Status (right)
- Existing facility status table
- **Fix:** Change "Offline" to "No Data" for flaring facilities where status is inferred from absence of FIRMS data (Abqaiq, Bandar Abbas, Jebel Ali Port, Mina Al Ahmadi, Ras Tanura, Rumaila). Add tooltip or footnote: "No FIRMS fire detections — may indicate offline status or data gap."
- Damage Detected sub-table — no change

#### 3.5.3 Internet Connectivity (left)
- Existing country table + Plotly time series chart — no change

#### 3.5.4 Flight Activity (right)
- Existing airport chart + table
- **Fix:** Gulf airports only (remove Auckland, Queenstown, Wanaka from this tab). Filtering done in JS using the `country` field (must be added to `flights.json` export — see Section 4.5).

#### 3.5.5 Nightlight Detail Table (left)
- Existing per-city deviation table
- **Fix:** Gulf cities only (remove Auckland, Queenstown)
- **Fix:** "Source" column should show data source (VNP46A2 / VIIRS_DNB_L1B), not country name

#### 3.5.6 Maritime Detail Table (right)
- Existing chokepoint table
- **Fix:** Gulf chokepoints only (Strait of Hormuz, Bab al-Mandeb). Remove NZ marinas/approaches.
- Keep the single-city nightlight chart here as a detail tool (moved from its current hero position), with the existing city dropdown

### 3.6 Section 5 — Methodology & Sources

Collapsible `<details>` element with `<summary>` showing "Methodology & Data Sources".

**Contents:**

1. **Data sources table:** Source name, update frequency, resolution, access tier, latest observation date
   - NASA FIRMS (VIIRS active fires) — 4-hourly, 375m, free
   - NASA Black Marble VNP46A2 — daily (11-day processing lag), 500m, free
   - VIIRS DNB L1B swaths — daily (~3h lag, no lunar correction), 750m, free
   - Sentinel-1 SAR — 6-day revisit, 10m, free
   - IODA / Cloudflare — daily, country-level, free
   - OpenSky ADS-B — daily, airport-level, free (rate-limited)
   - GDELT — daily, country-level, free (rate-limited)

2. **Methodology notes:**
   - Baseline period: Jan 15 – Feb 27 2026 (pre-war)
   - % change = (current - baseline) / baseline × 100
   - Compound risk: weighted composite of 8 normalised factors (weights listed)
   - DNB L1B caveat: no lunar illumination or straylight correction — absolute values less reliable than relative trends
   - Cloud cover: tracked per observation, not filtered — quality indicator only
   - Ramadan caveat: baseline is pre-Ramadan; behavioral changes may affect nightlight comparisons
   - Infrastructure "No Data" vs "Offline" distinction explained

3. **Download links:**
   - Individual JSON files: nightlights, fires, fires_geojson, compound_risk, internet, flights, thermal_signatures, sar, meta
   - Link format: `data/{filename}.json`

4. **Citation:**
   - Suggested citation format for journalists

### 3.7 NZ Migration Tab

**Minimal changes:**
- Receives NZ-specific data removed from Gulf tables (Auckland/Queenstown nightlights, NZ SAR locations, NZ airports)
- No structural redesign — keep existing layout
- Add NZ flight data (Auckland, Queenstown, Wanaka airports) if not already present

### 3.8 Footer

- Keep existing attribution line
- Add: "Methodology" anchor link

## 4. Export / Data Changes

### 4.1 `meta.json` additions

```json
{
  "generated_at": "...",
  "situation_brief": "Tehran nighttime radiance has collapsed 78% from...",
  "freshness": {
    "nightlights": {"latest": "2026-03-08", "days_ago": 5},
    "fires": {"latest": "2026-03-12T10:03:00Z", "days_ago": 1},
    "internet": {"latest": "2026-03-12", "days_ago": 1},
    "flights": {"latest": "2026-03-12", "days_ago": 1},
    "sar": {"latest": "2026-03-09", "days_ago": 4},
    "thermal": {"latest": "2026-03-13", "days_ago": 0}
  },
  "stale_warning": "Nightlight data is 5 days old (latest: Mar 8). NASA processing lag.",
  "war_start": "2026-02-28",
  "baseline_start": "2026-01-15",
  "baseline_end": "2026-02-27"
}
```

### 4.2 `fires.json` additions

Add `daily_by_country` field with per-date, per-country fire counts for the time series chart. Use the **existing region bounding boxes** from `_export_fires`. **Use the exact key strings from the existing `regions` dict** (e.g., `"UAE / Qatar / Bahrain"` with spaces) — do not invent new key names:

```json
{
  "dates": [...],
  "regions": {...},
  "daily_by_country": {
    "Iran": {"dates": ["2026-03-06", ...], "counts": [35, 7, 26, ...]},
    "Saudi Arabia": {"dates": [...], "counts": [42, 10, 24, ...]},
    "UAE/Qatar/Bahrain": {"dates": [...], "counts": [...]},
    "Iraq": {"dates": [...], "counts": [...]},
    "Kuwait": {"dates": [...], "counts": [...]}
  }
}
```

### 4.3 `compound_risk.json` additions

Add all 8 sub-scores per indicator (currently only nightlight_score, fire_activity_score, trade_flow_score are exported):

```json
{
  "indicators": [{
    "aoi_name": "Tehran",
    "compound_risk": 0.44,
    "nightlight_score": 0.98,
    "fire_activity_score": 0.12,
    "trade_flow_score": 0.86,
    "no2_score": 0.15,
    "internet_score": 0.33,
    "flight_score": 0.45,
    "gdelt_score": 0.20,
    "thermal_score": 0.10,
    "alert_level": "high"
  }, ...]
}
```

### 4.4 `thermal_signatures.json` changes

Add `data_caveat` field per facility:

```json
{
  "Abqaiq Processing": {
    "status": "no_data",
    "facility_profile": "flaring",
    "data_caveat": "No FIRMS detections — status unknown"
  }
}
```

### 4.5 `sar.json` additions

Add `normalised_count` derived field per observation (= `vessel_count / scene_coverage`). This is needed for the Hormuz vessel traffic chart (Section 3.3.3). Modify `_export_sar` to compute and include this field. **Guard against division by zero:** if `scene_coverage` is 0 or null, emit `normalised_count: null`.

### 4.6 `flights.json` additions

Add `country` field to each per-airport record in `_export_flights`. The field exists on the `FlightActivity` model but is not currently included in the export output dict. Needed for JS-side filtering of Gulf vs NZ airports (Sections 3.5.4 and 3.7).

## 5. Implementation Scope

### Files modified:
- `docs/index.html` — main dashboard (bulk of changes: restructured DOM, 3 new Plotly charts, event annotations, freshness tags, 8-score risk cards, methodology section, Gulf/NZ data separation)
- `pipeline/management/commands/export_static.py` — situation brief generation, freshness metadata, fire `daily_by_country` aggregation, compound risk sub-score joins, SAR `normalised_count`, flights `country` field, thermal `data_caveat`

### Files NOT modified:
- `pipeline/models.py` — no model changes (compound sub-scores computed at export time via table joins, not stored)
- `pipeline/tasks.py` — no task changes (already fixed FIRMS days=2)
- `pipeline/clients/*` — no client changes
- `pipeline/views.py` — Django live dashboard not in scope for this spec (would be a follow-up)

### Estimated complexity:
- `export_static.py` changes: moderate (situation brief template, fire aggregation query, additional JSON fields)
- `index.html` JavaScript: significant (3 new Plotly charts, restructured DOM, event annotations, freshness tags, methodology section, 8-score risk cards)
- CSS: minor (situation brief styling, methodology details element, freshness tag styling)

## 6. What This Does NOT Include

- No new data sources or API integrations
- No Django model changes
- No Celery task changes
- No map redesign (Leaflet map stays as-is in Section 4)
- No NZ tab redesign
- No real-time/WebSocket features
- No user authentication or access control
