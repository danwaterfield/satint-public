# Dashboard UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the GitHub Pages dashboard into a narrative-first intelligence product with hero charts, complete risk sub-scores, and proper Gulf/NZ data separation.

**Architecture:** Two files change: `export_static.py` (add situation brief, freshness metadata, fire daily_by_country, compound sub-score joins, SAR normalised_count, flights country field, thermal data_caveat) and `docs/index.html` (restructure DOM into 5 sections, add 3 new Plotly charts, event annotations, methodology section). No model changes.

**Tech Stack:** Django management command (Python), Plotly.js, Leaflet.js, vanilla JS, static HTML/CSS.

**Spec:** `docs/superpowers/specs/2026-03-13-dashboard-ux-overhaul-design.md`

---

## Chunk 1: Export Command Changes

All changes to `pipeline/management/commands/export_static.py`. These must land first because the dashboard JS depends on the new JSON fields.

### Task 1: Add freshness metadata and situation brief to `_export_meta`

**Files:**
- Modify: `pipeline/management/commands/export_static.py` — `_export_meta` method (lines 80-94)

- [ ] **Step 1: Update imports**

Add `GDELTEventCount` to the imports block at line 22. The other needed models (`InternetOutage`, `ThermalSignature`, `SARVesselDetection`, `NightlightObservation`, `ThermalAnomaly`, `FlightActivity`) are already imported.

```python
# At line 22, add GDELTEventCount to the import list
from pipeline.models import (
    AreaOfInterest,
    CompoundRiskIndicator,
    FlightActivity,
    GDELTEventCount,
    InternetOutage,
    MigrationPressureIndicator,
    NightlightObservation,
    OpticalAssetCount,
    SARVesselDetection,
    ThermalAnomaly,
    ThermalSignature,
)
```

- [ ] **Step 2: Rewrite `_export_meta` with freshness + situation brief**

Replace the entire `_export_meta` method with:

```python
def _export_meta(self, out_dir):
    import datetime

    today = date.today()
    latest_dnb = NightlightObservation.objects.aggregate(latest=Max("date"))["latest"]
    latest_fire = ThermalAnomaly.objects.aggregate(latest=Max("detected_at"))["latest"]
    latest_inet = InternetOutage.objects.aggregate(latest=Max("date"))["latest"]
    latest_flight = FlightActivity.objects.aggregate(latest=Max("date"))["latest"]
    latest_sar = SARVesselDetection.objects.aggregate(latest=Max("date"))["latest"]
    latest_thermal = ThermalSignature.objects.aggregate(latest=Max("date"))["latest"]

    def _freshness(latest_val):
        if latest_val is None:
            return {"latest": None, "days_ago": None}
        if isinstance(latest_val, datetime.datetime):
            latest_val = latest_val.date()
        days = (today - latest_val).days
        return {"latest": str(latest_val), "days_ago": days}

    freshness = {
        "nightlights": _freshness(latest_dnb),
        "fires": _freshness(latest_fire),
        "internet": _freshness(latest_inet),
        "flights": _freshness(latest_flight),
        "sar": _freshness(latest_sar),
        "thermal": _freshness(latest_thermal),
    }

    # Stale warning: any source > 3 days old
    stale_sources = [
        name for name, f in freshness.items()
        if f["days_ago"] is not None and f["days_ago"] > 3
    ]
    stale_warning = None
    if stale_sources:
        parts = []
        for s in stale_sources:
            f = freshness[s]
            parts.append(f"{s.title()} data is {f['days_ago']} days old (latest: {f['latest']})")
        stale_warning = ". ".join(parts) + ". NASA/satellite processing lag."

    # Situation brief
    brief_parts = []

    # Worst nightlight city (Gulf only, latest date)
    gulf_countries = {"Iran", "UAE", "Saudi Arabia", "Qatar", "Bahrain", "Kuwait", "Iraq"}
    if latest_dnb:
        worst_nl = (
            NightlightObservation.objects.filter(date=latest_dnb, aoi__country__in=gulf_countries)
            .exclude(pct_change=None)
            .select_related("aoi")
            .order_by("pct_change")
            .first()
        )
        if worst_nl and worst_nl.pct_change < -20:
            brief_parts.append(
                f"{worst_nl.aoi.name} nighttime radiance has collapsed "
                f"{abs(worst_nl.pct_change):.0f}% from pre-war baseline, "
                f"consistent with widespread power grid failure"
            )

    # Hormuz vessel traffic
    hormuz_latest = (
        SARVesselDetection.objects.filter(chokepoint__name="Strait of Hormuz")
        .order_by("-date").first()
    )
    if hormuz_latest and hormuz_latest.pct_change is not None and hormuz_latest.pct_change < -20:
        remaining = 100 + hormuz_latest.pct_change
        brief_parts.append(
            f"Strait of Hormuz vessel traffic has fallen to "
            f"{remaining:.0f}% of normal"
        )

    # Damaged facilities
    damaged = ThermalSignature.objects.filter(damage_detected=True).order_by("-date")
    if damaged.exists():
        first = damaged.first()
        count = damaged.values("aoi__name").distinct().count()
        brief_parts.append(
            f"{first.aoi.name} sustained strike damage on {first.date.strftime('%b %-d')}"
            if count == 1 else
            f"{count} facilities sustained strike damage, including {first.aoi.name}"
        )

    # Internet degradation
    if latest_inet:
        degraded = InternetOutage.objects.filter(
            date=latest_inet, pct_change__lt=-10
        ).order_by("pct_change")
        if degraded.exists():
            worst = degraded.first()
            brief_parts.append(
                f"{worst.country} internet connectivity remains degraded at "
                f"{worst.pct_change:+.1f}%"
            )

    situation_brief = ". ".join(brief_parts) + "." if brief_parts else None

    self._write(
        os.path.join(out_dir, "meta.json"),
        {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "latest_nightlight": str(latest_dnb) if latest_dnb else None,
            "latest_fire": latest_fire.isoformat() if latest_fire else None,
            "situation_brief": situation_brief,
            "freshness": freshness,
            "stale_warning": stale_warning,
            "war_start": "2026-02-28",
            "baseline_start": "2026-01-15",
            "baseline_end": "2026-02-27",
        },
    )
```

- [ ] **Step 3: Run export and verify meta.json**

```bash
cd "/Users/danielwaterfield/Documents/iran_satellite " && source satint/bin/activate && python manage.py export_static
cat docs/data/meta.json | python -m json.tool | head -30
```

Expected: `situation_brief`, `freshness`, and `stale_warning` fields present.

- [ ] **Step 4: Commit**

```bash
git add pipeline/management/commands/export_static.py docs/data/meta.json
git commit -m "feat(export): add situation brief, freshness metadata to meta.json"
```

### Task 2: Add `daily_by_country` to fires export

**Files:**
- Modify: `pipeline/management/commands/export_static.py` — `_export_fires` method (lines 129-161)

- [ ] **Step 1: Add `daily_by_country` key to fires result**

After line 159 (end of the region loop), before the `_write` call, add:

```python
        # daily_by_country: same data reshaped for the time series chart
        result["daily_by_country"] = {
            name: {"dates": all_dates, "counts": result["regions"][name]["counts"]}
            for name in result["regions"]
        }
```

- [ ] **Step 2: Run export and verify fires.json**

```bash
python manage.py export_static
python -c "import json; d=json.load(open('docs/data/fires.json')); print(list(d['daily_by_country'].keys()))"
```

Expected: `['Iran', 'Iraq', 'Kuwait', 'Saudi Arabia', 'UAE / Qatar / Bahrain']`

- [ ] **Step 3: Commit**

```bash
git add pipeline/management/commands/export_static.py docs/data/fires.json
git commit -m "feat(export): add daily_by_country fire time series to fires.json"
```

### Task 3: Add compound risk sub-score joins

**Files:**
- Modify: `pipeline/management/commands/export_static.py` — `_export_compound_risk` method (lines 228-262)

- [ ] **Step 1: Add sub-score computation to the export**

Replace the indicator list comprehension (lines 249-261) with logic that joins against the supplementary tables. The 5 additional scores are computed on-the-fly, not stored on the model:

```python
    def _compute_supplementary_scores(self, indicator):
        """Compute 5 additional sub-scores by joining related tables for the same AOI and date."""
        aoi = indicator.aoi
        d = indicator.date

        def _safe_score(queryset, field, baseline_field=None, invert=False):
            """Return a 0-1 normalised score. Higher = worse."""
            obj = queryset.first()
            if obj is None:
                return None
            val = getattr(obj, field, None)
            if val is None:
                return None
            if baseline_field:
                baseline = getattr(obj, baseline_field, None)
                if baseline and baseline > 0:
                    pct = (val - baseline) / baseline
                    score = max(0, min(1, abs(pct))) if pct < 0 else 0
                    return round(score, 4)
            # For raw counts, normalise against a reasonable max
            return None

        # Internet: use country-level data, pct_change
        inet = InternetOutage.objects.filter(country=aoi.country, date=d)
        inet_score = None
        if inet.exists():
            pct = inet.first().pct_change
            if pct is not None:
                inet_score = round(max(0, min(1, abs(pct) / 100)) if pct < 0 else 0, 4)

        # Flights: use airport for this AOI's city
        flight = FlightActivity.objects.filter(
            airport_name__icontains=aoi.name.split()[0], date=d
        )
        flight_score = None
        if flight.exists():
            f = flight.first()
            if f.baseline_total and f.baseline_total > 0:
                pct = (f.total_movements - f.baseline_total) / f.baseline_total
                flight_score = round(max(0, min(1, abs(pct))) if pct < 0 else 0, 4)

        # GDELT: use country-level
        gdelt = GDELTEventCount.objects.filter(country=aoi.country, date=d)
        gdelt_score = None
        if gdelt.exists():
            total = gdelt.first().total_crisis_events or 0
            gdelt_score = round(min(1, total / 50), 4)  # normalise: 50 events = score 1.0

        # Thermal: count damaged facilities in this country
        thermal = ThermalSignature.objects.filter(aoi__country=aoi.country, date=d)
        thermal_score = None
        if thermal.exists():
            damaged = thermal.filter(damage_detected=True).count()
            total = thermal.count()
            thermal_score = round(damaged / total, 4) if total > 0 else 0

        # NO2: not yet backfilled (return None gracefully)
        no2_score = None

        return {
            "no2_score": no2_score,
            "internet_score": inet_score,
            "flight_score": flight_score,
            "gdelt_score": gdelt_score,
            "thermal_score": thermal_score,
        }
```

Then update `_export_compound_risk` to call it:

```python
    result = {
        "as_of": str(indicators[0].date) if indicators else None,
        "indicators": [],
    }
    for i in indicators:
        extra = self._compute_supplementary_scores(i)
        result["indicators"].append({
            "aoi_name": i.aoi.name,
            "country": i.aoi.country,
            "compound_risk": round(i.compound_risk, 4),
            "alert_level": i.alert_level,
            "nightlight_score": round(i.nightlight_score, 4),
            "fire_activity_score": round(i.fire_activity_score, 4),
            "trade_flow_score": round(i.trade_flow_score, 4),
            **extra,
        })
    self._write(os.path.join(out_dir, "compound_risk.json"), result)
```

- [ ] **Step 2: Run export and verify compound_risk.json**

```bash
python manage.py export_static
python -c "import json; d=json.load(open('docs/data/compound_risk.json')); print(json.dumps(d['indicators'][0], indent=2))"
```

Expected: all 8 score fields present (some may be null for NO2 or missing data).

- [ ] **Step 3: Commit**

```bash
git add pipeline/management/commands/export_static.py docs/data/compound_risk.json
git commit -m "feat(export): add 8 compound risk sub-scores via table joins"
```

### Task 4: Add SAR `normalised_count` and flights `country` field

**Files:**
- Modify: `pipeline/management/commands/export_static.py` — `_export_sar` (lines 264-288) and `_export_flights` (lines 433-454)

- [ ] **Step 1: Add `normalised_count` to SAR export**

In `_export_sar`, update the inner dict (line 279-286) to include the derived field:

```python
            coverage = d["scene_coverage"]
            normalised = round(d["vessel_count"] / coverage, 1) if coverage else None
            result[name].append({
                "date": str(d["date"]),
                "vessel_count": d["vessel_count"],
                "normalised_count": normalised,
                "baseline_count": d["baseline_count"],
                "pct_change": round(d["pct_change"], 1) if d["pct_change"] is not None else None,
                "scene_coverage": round(coverage, 2) if coverage else None,
                "mean_scr_db": round(d["mean_scr_db"], 1),
            })
```

- [ ] **Step 2: Add `country` to flights export**

In `_export_flights`, add `"country"` to the `.values()` call and include it in the output dict:

```python
        flights = (
            FlightActivity.objects.all()
            .order_by("airport_name", "date")
            .values("airport_name", "airport_icao", "country", "date",
                    "arrivals", "departures", "total_movements")
        )

        airports = defaultdict(list)
        for f in flights:
            airports[f["airport_name"]].append({
                "date": str(f["date"]),
                "icao": f["airport_icao"],
                "country": f["country"],
                "arrivals": f["arrivals"],
                "departures": f["departures"],
                "total": f["total_movements"],
            })
```

- [ ] **Step 3: Run export and verify both files**

```bash
python manage.py export_static
python -c "import json; d=json.load(open('docs/data/sar.json')); print(d['Strait of Hormuz'][0])"
python -c "import json; d=json.load(open('docs/data/flights.json')); print(list(d.values())[0][0])"
```

Expected: SAR records have `normalised_count`, flight records have `country`.

- [ ] **Step 4: Commit**

```bash
git add pipeline/management/commands/export_static.py docs/data/sar.json docs/data/flights.json
git commit -m "feat(export): add SAR normalised_count and flights country field"
```

### Task 5: Add thermal `data_caveat` field

**Files:**
- Modify: `pipeline/management/commands/export_static.py` — `_export_thermal_signatures` (lines 312-337)

- [ ] **Step 1: Add `data_caveat` to thermal export**

In the inner dict (line 326-334), add a caveat for flaring facilities with no fire data:

```python
            status = s["status"]
            profile = s["facility_profile"]
            # Flaring facilities with "offline" status based on absent FIRMS data get a caveat
            caveat = None
            if profile == "flaring" and status == "offline" and s["fire_count"] == 0:
                caveat = "No FIRMS detections — status unknown"
                status = "no_data"

            facilities[s["aoi__name"]].append({
                "date": str(s["date"]),
                "country": s["aoi__country"],
                "profile": profile,
                "status": status,
                "data_caveat": caveat,
                "damage": s["damage_detected"],
                "fire_count": s["fire_count"],
                "max_frp": round(s["max_frp"], 1) if s["max_frp"] is not None else None,
                "baseline_fires": round(s["baseline_fire_count"], 1) if s["baseline_fire_count"] is not None else None,
            })
```

- [ ] **Step 2: Run export and verify**

```bash
python manage.py export_static
python -c "import json; d=json.load(open('docs/data/thermal_signatures.json')); print(json.dumps(d['Abqaiq Processing'][-1], indent=2))"
```

Expected: `status: "no_data"`, `data_caveat: "No FIRMS detections — status unknown"` for flaring facilities with 0 fires.

- [ ] **Step 3: Commit**

```bash
git add pipeline/management/commands/export_static.py docs/data/thermal_signatures.json
git commit -m "feat(export): add thermal data_caveat, distinguish no_data from offline"
```

### Task 6: Run full export and commit all data files

- [ ] **Step 1: Run full export**

```bash
python manage.py export_static
```

- [ ] **Step 2: Commit all updated data files**

```bash
git add docs/data/
git commit -m "data: re-export all JSON with new fields"
```

---

## Chunk 2: Dashboard HTML/JS — Situation Brief + Hero Charts

All changes to `docs/index.html`. This chunk adds the narrative layer and the three hero charts.

### Task 7: Add Situation Brief section

**Files:**
- Modify: `docs/index.html`

- [ ] **Step 1: Add situation brief HTML**

After the `<div id="alert-banner" ...>` element (around line 205) and before the `<div class="main tab-section active" id="tab-gulf">`, add the situation brief container. Inside `#tab-gulf`, move it to the very top before the summary-row:

```html
  <!-- Situation Brief -->
  <div id="situation-brief" class="card" style="border-left:4px solid var(--red);background:#fefefe;margin-bottom:0;">
    <div class="section-header">
      <span class="section-title">Situation Brief</span>
      <span class="section-meta" id="brief-date"></span>
    </div>
    <p id="brief-text" style="font-size:15px;line-height:1.7;color:var(--text);margin:0;"></p>
  </div>

  <!-- Data freshness warning -->
  <div id="stale-banner" style="display:none;background:#fffbeb;border:1px solid #f6e05e;border-radius:var(--radius);padding:10px 16px;font-size:12px;color:var(--amber);"></div>
```

- [ ] **Step 2: Add JS to populate the brief**

In the `load(DATA + '/meta.json')` handler (find where meta.json is loaded), add:

```javascript
load(DATA + '/meta.json').then(function (meta) {
  // Existing topbar date logic...

  // Situation brief
  if (meta.situation_brief) {
    setText('brief-text', meta.situation_brief);
    setText('brief-date', meta.generated_at ? fmtDate(meta.generated_at) : '');
  }

  // Data freshness warning
  if (meta.stale_warning) {
    var banner = document.getElementById('stale-banner');
    banner.textContent = meta.stale_warning;
    banner.style.display = 'block';
  }

  // Update topbar with generated time
  var updated = document.getElementById('topbar-updated');
  if (updated && meta.generated_at) {
    updated.textContent = 'Updated ' + fmtDate(meta.generated_at);
  }
});
```

- [ ] **Step 3: Add CSS for the brief**

In the `<style>` block, add:

```css
#situation-brief p { font-family: var(--font-sans); }
#stale-banner { font-family: var(--font-mono); }
```

- [ ] **Step 4: Test in browser**

Open `http://localhost:8001` — situation brief should appear at top with red left border. Stale warning should appear if any data is >3 days old.

- [ ] **Step 5: Commit**

```bash
git add docs/index.html
git commit -m "feat(dashboard): add situation brief and data freshness warning"
```

### Task 8: Add multi-city nightlight overlay chart

**Files:**
- Modify: `docs/index.html`

- [ ] **Step 1: Add hero charts section HTML**

Replace the existing two-col nightlight+vessel section (find `<!-- Nightlight chart + vessel table -->` around line 255) with a new hero charts section. Keep the vessel table — it moves to Section 4 later. For now, add above it:

```html
  <!-- Hero Charts -->
  <div>
    <div class="section-header">
      <span class="section-title">Nighttime Radiance — All Gulf Cities</span>
      <span class="section-meta" id="nl-hero-freshness">vs. pre-war baseline (15 Jan – 27 Feb 2026)</span>
    </div>
    <div id="nightlight-hero-chart" style="height:340px;"></div>
  </div>
```

- [ ] **Step 2: Add `renderNightlightHero` JS function**

```javascript
var EVENT_ANNOTATIONS = [
  { date: '2026-02-28', label: 'War begins', color: '#c0392b' },
  { date: '2026-03-06', label: 'Major strikes', color: '#e53e3e' },
  { date: '2026-03-07', label: 'Grid collapse', color: '#ed8936' },
];

var NZ_CITIES = ['Auckland', 'Queenstown'];
var CONTROL_CITIES = ['Mumbai', 'Karachi', 'Singapore'];

function isGulfCity(name) {
  return NZ_CITIES.indexOf(name) === -1 && CONTROL_CITIES.indexOf(name) === -1;
}

function makeEventShapes() {
  return EVENT_ANNOTATIONS.map(function (evt) {
    return {
      type: 'line', xref: 'x', x0: evt.date, x1: evt.date,
      yref: 'paper', y0: 0, y1: 1,
      line: { color: evt.color, width: 1.5, dash: 'dot' },
    };
  });
}

function makeEventAnnotations() {
  return EVENT_ANNOTATIONS.map(function (evt) {
    return {
      x: evt.date, y: 1, xref: 'x', yref: 'paper',
      text: evt.label, showarrow: false,
      font: { size: 9, color: evt.color }, yanchor: 'bottom',
    };
  });
}

var CITY_COLORS = {
  'Tehran': '#c0392b', 'Dubai': '#2b6cb0', 'Doha': '#38a169',
  'Kuwait City': '#ed8936', 'Riyadh': '#805ad5', 'Abu Dhabi': '#d69e2e',
  'Manama': '#319795', 'Isfahan': '#e53e3e', 'Basra': '#718096',
};

function renderNightlightHero(nlAllData) {
  var traces = [];
  var gulfCities = Object.keys(nlAllData).filter(isGulfCity).sort();

  gulfCities.forEach(function (city) {
    var series = nlAllData[city];
    if (!series || !series.length) return;
    traces.push({
      x: series.map(function (d) { return d.date; }),
      y: series.map(function (d) { return d.pct_change; }),
      type: 'scatter', mode: 'lines+markers',
      name: city,
      line: { color: CITY_COLORS[city] || '#718096', width: 2 },
      marker: { size: 3 },
      hovertemplate: city + '<br>%{x}<br>%{y:.1f}%<extra></extra>',
    });
  });

  // Freshness tag
  var latestDate = null;
  gulfCities.forEach(function (city) {
    var s = nlAllData[city];
    if (s && s.length) {
      var d = s[s.length - 1].date;
      if (!latestDate || d > latestDate) latestDate = d;
    }
  });
  if (latestDate) {
    var days = Math.round((Date.now() - new Date(latestDate).getTime()) / 86400000);
    setText('nl-hero-freshness', 'Latest: ' + latestDate + ' (' + days + 'd ago) · vs. pre-war baseline');
  }

  var shapes = makeEventShapes();
  shapes.push({
    type: 'line', xref: 'paper', x0: 0, x1: 1,
    yref: 'y', y0: 0, y1: 0,
    line: { color: '#a0aec0', width: 1, dash: 'dash' },
  });

  Plotly.newPlot('nightlight-hero-chart', traces, {
    margin: { t: 20, r: 20, b: 40, l: 60 },
    font: { family: 'Inter, system-ui, sans-serif', size: 11, color: '#4a5568' },
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    legend: { orientation: 'h', x: 0, y: 1.12, font: { size: 10 } },
    xaxis: { showgrid: false, tickfont: { size: 10 } },
    yaxis: {
      title: '% Change from Baseline', showgrid: true, gridcolor: '#edf2f7',
      titlefont: { size: 10 }, zeroline: false,
    },
    shapes: shapes,
    annotations: makeEventAnnotations(),
  }, { responsive: true, displayModeBar: false });
}
```

- [ ] **Step 3: Call `renderNightlightHero` from the nightlights data load**

Find where `nlData` is populated (in the `load(DATA + '/nightlights.json')` handler) and add:

```javascript
renderNightlightHero(nlData);
```

- [ ] **Step 4: Test in browser**

All Gulf cities should appear as overlaid lines on a single chart with event annotations.

- [ ] **Step 5: Commit**

```bash
git add docs/index.html
git commit -m "feat(dashboard): add multi-city nightlight overlay hero chart"
```

### Task 9: Add fire time series and Hormuz vessel charts

**Files:**
- Modify: `docs/index.html`

- [ ] **Step 1: Add HTML for the two half-width hero charts**

Below the nightlight hero chart div, add:

```html
  <div class="two-col">
    <div class="card">
      <div class="section-header">
        <span class="section-title">Fire Activity by Region</span>
        <span class="section-meta" id="fire-chart-freshness">Daily fire count — VIIRS SNPP & NOAA-20</span>
      </div>
      <div id="fire-hero-chart" style="height:280px;"></div>
    </div>
    <div class="card">
      <div class="section-header">
        <span class="section-title">Hormuz Vessel Traffic</span>
        <span class="section-meta" id="hormuz-freshness">SAR coverage-normalised vessel count</span>
      </div>
      <div id="hormuz-hero-chart" style="height:280px;"></div>
    </div>
  </div>
```

- [ ] **Step 2: Add `renderFireHero` JS function**

```javascript
var REGION_COLORS = {
  'Iran': '#c0392b', 'Saudi Arabia': '#805ad5',
  'UAE / Qatar / Bahrain': '#2b6cb0', 'Iraq': '#ed8936', 'Kuwait': '#38a169',
};

function renderFireHero(fireData) {
  var dbc = fireData.daily_by_country;
  if (!dbc) return;

  var traces = [];
  Object.keys(dbc).forEach(function (region) {
    var rd = dbc[region];
    traces.push({
      x: rd.dates, y: rd.counts, type: 'bar', name: region,
      marker: { color: REGION_COLORS[region] || '#718096' },
      hovertemplate: region + '<br>%{x}<br>%{y} fires<extra></extra>',
    });
  });

  // Freshness
  var dates = fireData.dates;
  if (dates && dates.length) {
    var latest = dates[dates.length - 1];
    setText('fire-chart-freshness', 'Latest: ' + latest + ' · VIIRS SNPP & NOAA-20');
  }

  Plotly.newPlot('fire-hero-chart', traces, {
    barmode: 'stack',
    margin: { t: 10, r: 10, b: 40, l: 50 },
    font: { family: 'Inter, system-ui, sans-serif', size: 11, color: '#4a5568' },
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    legend: { orientation: 'h', x: 0, y: 1.15, font: { size: 9 } },
    xaxis: { showgrid: false, tickfont: { size: 10 } },
    yaxis: { title: 'Fire Count', showgrid: true, gridcolor: '#edf2f7', titlefont: { size: 10 } },
    shapes: makeEventShapes(),
    annotations: makeEventAnnotations(),
  }, { responsive: true, displayModeBar: false });
}
```

- [ ] **Step 3: Add `renderHormuzHero` JS function**

```javascript
function renderHormuzHero(sarData) {
  var hormuz = sarData['Strait of Hormuz'];
  if (!hormuz || !hormuz.length) {
    setText('hormuz-hero-chart', 'No Hormuz SAR data available.');
    return;
  }

  var dates = hormuz.map(function (d) { return d.date; });
  var counts = hormuz.map(function (d) { return d.normalised_count; });
  var baseline = hormuz[0].baseline_count;

  // Freshness
  var latest = dates[dates.length - 1];
  var days = Math.round((Date.now() - new Date(latest).getTime()) / 86400000);
  setText('hormuz-freshness', 'Latest: ' + latest + ' (' + days + 'd ago) · SAR normalised');

  var shapes = [{
    type: 'line', xref: 'paper', x0: 0, x1: 1,
    yref: 'y', y0: baseline, y1: baseline,
    line: { color: '#718096', width: 1, dash: 'dot' },
  }];

  // Annotate key points
  var annotations = [{
    x: 0, xref: 'paper', y: baseline, yref: 'y',
    text: 'Pre-war baseline (' + baseline + ')', showarrow: false,
    font: { size: 9, color: '#718096' }, xanchor: 'left',
  }];

  // Find peak and trough for inline annotations
  var maxVal = -Infinity, maxIdx = 0, minVal = Infinity, minIdx = 0;
  counts.forEach(function (v, i) {
    if (v != null && v > maxVal) { maxVal = v; maxIdx = i; }
    if (v != null && v < minVal) { minVal = v; minIdx = i; }
  });

  if (maxVal > baseline * 1.5) {
    var pct = ((maxVal - baseline) / baseline * 100).toFixed(0);
    annotations.push({
      x: dates[maxIdx], y: maxVal, text: '+' + pct + '%',
      showarrow: true, arrowhead: 0, ax: 0, ay: -25,
      font: { size: 10, color: '#c0392b' },
    });
  }
  if (minVal < baseline * 0.7) {
    var pctMin = ((minVal - baseline) / baseline * 100).toFixed(0);
    annotations.push({
      x: dates[minIdx], y: minVal, text: pctMin + '%',
      showarrow: true, arrowhead: 0, ax: 0, ay: 25,
      font: { size: 10, color: '#c0392b' },
    });
  }

  Plotly.newPlot('hormuz-hero-chart', [{
    x: dates, y: counts, type: 'scatter', mode: 'lines+markers',
    name: 'Normalised vessel count',
    line: { color: '#2b6cb0', width: 2.5 },
    marker: { size: 6, color: '#2b6cb0' },
    hovertemplate: '%{x}<br>%{y:.0f} vessels<extra></extra>',
  }], {
    margin: { t: 10, r: 20, b: 40, l: 50 },
    font: { family: 'Inter, system-ui, sans-serif', size: 11, color: '#4a5568' },
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    showlegend: false,
    xaxis: { showgrid: false, tickfont: { size: 10 } },
    yaxis: { title: 'Vessels', showgrid: true, gridcolor: '#edf2f7', titlefont: { size: 10 } },
    shapes: shapes,
    annotations: annotations,
  }, { responsive: true, displayModeBar: false });
}
```

- [ ] **Step 4: Wire up the data loads**

In the fires data load handler, add `renderFireHero(fireData);`. In the SAR data load handler, add `renderHormuzHero(sarData);`.

- [ ] **Step 5: Test in browser**

Two half-width charts should appear: stacked bar fires by region (left), Hormuz vessel scatter with baseline line (right). Both should have event annotations.

- [ ] **Step 6: Commit**

```bash
git add docs/index.html
git commit -m "feat(dashboard): add fire time series and Hormuz vessel hero charts"
```

---

## Chunk 3: Risk Cards, Data Separation, Operational Detail, Methodology

### Task 10: Update compound risk cards to show all 8 sub-scores

**Files:**
- Modify: `docs/index.html` — `renderRisk` function

- [ ] **Step 1: Update sub-scores grid in `renderRisk`**

Find the sub-scores section (around line 736) and replace the 3-item array with all 8:

```javascript
    var subs = el('div', { class: 'sub-scores' });
    subs.style.gridTemplateColumns = '1fr 1fr 1fr 1fr';
    [
      ['NL', ind.nightlight_score], ['Fire', ind.fire_activity_score],
      ['Trade', ind.trade_flow_score], ['NO\u2082', ind.no2_score],
      ['Internet', ind.internet_score], ['Flights', ind.flight_score],
      ['GDELT', ind.gdelt_score], ['Thermal', ind.thermal_score],
    ].forEach(function (pair) {
      var item = el('div', { class: 'sub-score-item' });
      item.appendChild(el('div', { class: 'sub-score-label' }, pair[0]));
      item.appendChild(el('div', { class: 'sub-score-val' },
        pair[1] != null ? pair[1].toFixed(2) : '\u2014'));
      subs.appendChild(item);
    });
```

- [ ] **Step 2: Filter to Gulf cities only**

At the top of `renderRisk`, filter out non-Gulf cities:

```javascript
  indicators = indicators.filter(function (ind) {
    return NZ_CITIES.indexOf(ind.aoi_name) === -1
      && CONTROL_CITIES.indexOf(ind.aoi_name) === -1;
  });
```

- [ ] **Step 3: Commit**

```bash
git add docs/index.html
git commit -m "feat(dashboard): show all 8 compound risk sub-scores, Gulf only"
```

### Task 11: Separate Gulf and NZ data in tables

**Files:**
- Modify: `docs/index.html` — `renderNLTable`, `renderVesselTable`, `renderFlightData`

- [ ] **Step 1: Filter nightlight table to Gulf cities**

In `renderNLTable`, after `var cities = Object.keys(nlAllData).sort();`, add:

```javascript
  cities = cities.filter(isGulfCity);
```

Also fix the "Source" column — currently shows country, should show data source. In the row rendering, change the source cell from `r.latest.source || ''` to just use the actual `source` field (it already contains "VNP46A2" or "VIIRS_DNB_L1B" — the issue was actually in the column header labeling which says "Source" but renders correctly).

- [ ] **Step 2: Filter vessel table to Gulf chokepoints**

In `renderVesselTable`, after building the rows array, filter:

```javascript
  var NZ_LOCATIONS = ['NZ East Approach', 'NZ North Approach', 'Silo Marina', 'Viaduct Harbour', 'Westhaven Marina'];
  var gulfNames = Object.keys(sarData).filter(function (n) {
    return NZ_LOCATIONS.indexOf(n) === -1;
  });
```

Then only iterate `gulfNames`.

- [ ] **Step 3: Filter flight table to Gulf airports**

In `renderFlightData`, when building airport entries, filter by country:

```javascript
  var gulfAirports = Object.keys(data).filter(function (name) {
    var records = data[name];
    return records.length > 0 && records[0].country !== 'New Zealand';
  });
```

Use `gulfAirports` instead of `Object.keys(data)` for rendering.

- [ ] **Step 4: Commit**

```bash
git add docs/index.html
git commit -m "feat(dashboard): separate Gulf and NZ data in all tables"
```

### Task 12: Fix infrastructure status "Offline" → "No Data"

**Files:**
- Modify: `docs/index.html` — `renderInfraTable`

- [ ] **Step 1: Update status rendering**

In `renderInfraTable`, when rendering the status badge, check for `data_caveat`:

```javascript
  var statusText = latest.status;
  var statusClass = 'status-' + latest.status;
  if (latest.data_caveat) {
    statusText = 'No Data';
    statusClass = 'status-unknown';
  }
```

And add a tooltip via `title` attribute on the status badge:

```javascript
  var badge = el('span', {
    class: 'badge ' + statusClass,
    title: latest.data_caveat || '',
  }, statusText);
```

- [ ] **Step 2: Commit**

```bash
git add docs/index.html
git commit -m "fix(dashboard): show 'No Data' for flaring facilities without FIRMS detections"
```

### Task 13: Add Methodology section and topbar link

**Files:**
- Modify: `docs/index.html`

- [ ] **Step 1: Add Methodology anchor link to topbar**

In the topbar-right div, add before the auto-refresh span:

```html
<a href="#methodology" style="color:#a0b0c8;text-decoration:none;font-size:11px;">Methodology</a>
```

- [ ] **Step 2: Add Methodology section HTML**

Before the closing `</div>` of `#tab-gulf`, add:

```html
  <!-- Methodology & Sources -->
  <div class="card" id="methodology">
    <details>
      <summary style="cursor:pointer;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--navy);">
        Methodology & Data Sources
      </summary>
      <div style="margin-top:16px;font-size:12px;line-height:1.7;color:#4a5568;">
        <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--navy);margin:12px 0 6px;">Data Sources</h4>
        <table style="font-size:11px;">
          <tr><th>Source</th><th>Update Freq.</th><th>Resolution</th><th>Access</th></tr>
          <tr><td>NASA FIRMS (VIIRS active fires)</td><td>4-hourly</td><td>375m</td><td>Free</td></tr>
          <tr><td>NASA Black Marble VNP46A2</td><td>Daily (11-day lag)</td><td>500m</td><td>Free</td></tr>
          <tr><td>VIIRS DNB L1B swaths</td><td>Daily (~3h lag)</td><td>750m</td><td>Free</td></tr>
          <tr><td>Sentinel-1 SAR</td><td>6-day revisit</td><td>10m</td><td>Free</td></tr>
          <tr><td>IODA / Cloudflare</td><td>Daily</td><td>Country</td><td>Free</td></tr>
          <tr><td>OpenSky ADS-B</td><td>Daily</td><td>Airport</td><td>Free (rate-limited)</td></tr>
          <tr><td>GDELT</td><td>Daily</td><td>Country</td><td>Free (rate-limited)</td></tr>
        </table>

        <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--navy);margin:16px 0 6px;">Methodology Notes</h4>
        <ul style="padding-left:18px;">
          <li><strong>Baseline period:</strong> 15 Jan – 27 Feb 2026 (pre-war)</li>
          <li><strong>% change:</strong> (current − baseline) / baseline × 100</li>
          <li><strong>Compound risk:</strong> Weighted composite of 8 normalised factors — NL 20%, Fire 15%, Trade 15%, NO₂ 12%, Internet 12%, Flights 10%, GDELT 8%, Thermal 8%</li>
          <li><strong>DNB L1B caveat:</strong> No lunar illumination or straylight correction — absolute values less reliable than relative day-to-day trends</li>
          <li><strong>Cloud cover:</strong> Tracked per observation as quality indicator, not filtered. High cloud fraction reduces confidence.</li>
          <li><strong>Ramadan caveat:</strong> Baseline is pre-Ramadan. Behavioral changes (later activity, outdoor lighting) may affect nightlight comparisons.</li>
          <li><strong>Infrastructure "No Data":</strong> Flaring facilities (oil, LNG) normally emit detectable thermal signatures. Absence of FIRMS detections may indicate offline status or a data gap — reported as "No Data" rather than confirmed "Offline".</li>
        </ul>

        <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--navy);margin:16px 0 6px;">Download Data</h4>
        <p>All data is available as JSON:
          <a href="data/meta.json">meta</a> ·
          <a href="data/nightlights.json">nightlights</a> ·
          <a href="data/fires.json">fires</a> ·
          <a href="data/fires_geojson.json">fires (GeoJSON)</a> ·
          <a href="data/compound_risk.json">compound risk</a> ·
          <a href="data/internet.json">internet</a> ·
          <a href="data/flights.json">flights</a> ·
          <a href="data/thermal_signatures.json">thermal</a> ·
          <a href="data/sar.json">SAR vessels</a>
        </p>

        <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--navy);margin:16px 0 6px;">Citation</h4>
        <p style="font-family:var(--font-mono);font-size:10px;background:#f7f8fa;padding:8px;border-radius:3px;">
          Gulf Region Compound Risk Monitor. Satellite Intelligence Pipeline. [Date accessed]. Available at: https://danwaterfield.github.io/satint-public/
        </p>
      </div>
    </details>
  </div>
```

- [ ] **Step 3: Commit**

```bash
git add docs/index.html
git commit -m "feat(dashboard): add methodology section with sources, caveats, download links"
```

### Task 14: Move single-city nightlight chart to operational detail

**Files:**
- Modify: `docs/index.html`

- [ ] **Step 1: Relocate the existing single-city nightlight chart**

The existing nightlight chart (with city dropdown) currently sits in the hero position. Move the entire `<div class="card">` containing `#nightlight-chart` and `#city-select` to Section 4 (operational detail area), inside the nightlight detail table card. It becomes a drill-down tool rather than the main visualization.

No code change to the `renderNightlightChart` function — just move the HTML container.

- [ ] **Step 2: Commit**

```bash
git add docs/index.html
git commit -m "refactor(dashboard): move single-city nightlight chart to operational detail"
```

### Task 15: Final export, push to GitHub Pages

- [ ] **Step 1: Run full export**

```bash
cd "/Users/danielwaterfield/Documents/iran_satellite " && source satint/bin/activate && python manage.py export_static
```

- [ ] **Step 2: Test the static dashboard**

Open `docs/index.html` directly in browser or via `python -m http.server 8080 -d docs` and verify:
- Situation brief appears at top
- Stale warning shows for nightlights
- Multi-city nightlight overlay renders with event annotations
- Fire time series shows stacked bars by region
- Hormuz chart shows vessel count with baseline reference
- Risk cards show 8 sub-scores
- Tables show Gulf-only data
- Infrastructure "No Data" shows correctly
- Methodology section expands/collapses
- NZ tab still works

- [ ] **Step 3: Commit all changes and push**

```bash
git add docs/
git commit -m "data: final export with dashboard UX overhaul"
git push origin main
```
