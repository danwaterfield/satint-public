# Iran Crisis Autoresearcher — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a forward Monte Carlo scenario modelling system that explores war outcomes and NZ downstream effects, producing publication-quality probability distributions and briefings.

**Architecture:** Causal network of ~15 nodes (cause → transmission → NZ impact) sampled forward day-by-day via numpy/scipy. LLM-guided explorer agents (Sonnet) search causal assumptions; Opus synthesis produces narratives. No Django, no Mesa, no database — just files and functions.

**Tech Stack:** Python 3.11+, numpy, scipy, yfinance, fredapi, anthropic SDK, filelock

**Spec:** `docs/superpowers/specs/2026-03-16-irancrisis-autoresearcher-design.md`

**Project location:** `/Users/danielwaterfield/Documents/autoresearcher-irancrisis/`

**MVP scope:** Energy, Maritime, NZFuel subsystems. 3 explorer agents. Quick mode + basic synthesis.

---

## Chunk 1: Project Scaffold + Data Ingest

### Task 1: Project scaffold and dependencies

**Files:**
- Create: `autoresearcher-irancrisis/requirements.txt`
- Create: `autoresearcher-irancrisis/.env.example`
- Create: `autoresearcher-irancrisis/.gitignore`
- Create: `autoresearcher-irancrisis/run.py`

- [ ] **Step 1: Create project directory and git repo**

```bash
mkdir -p /Users/danielwaterfield/Documents/autoresearcher-irancrisis
cd /Users/danielwaterfield/Documents/autoresearcher-irancrisis
git init
```

- [ ] **Step 2: Create requirements.txt**

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

- [ ] **Step 3: Create .env.example**

```
FRED_API_KEY=your_fred_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
# ACLED_KEY=your_acled_key_here  # V2
# EIA_KEY=your_eia_key_here      # V2
```

- [ ] **Step 4: Create .gitignore**

```
.env
__pycache__/
*.pyc
.venv/
data/snapshots/
logs/
outputs/
*.egg-info/
```

- [ ] **Step 5: Create directory structure**

```bash
mkdir -p clients network explorer synthesis programs data/snapshots data/priors logs outputs
touch clients/__init__.py network/__init__.py explorer/__init__.py synthesis/__init__.py
```

- [ ] **Step 6: Create minimal run.py entry point**

```python
#!/usr/bin/env python3
"""Iran Crisis Autoresearcher — CLI entry point."""
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Iran Crisis scenario modelling")
    parser.add_argument("--quick", action="store_true", help="Quick run: 1000 samples, text output")
    parser.add_argument("--fleet", action="store_true", help="Full fleet: 7 agents, synthesis")
    parser.add_argument("--update", action="store_true", help="Update world state snapshot")
    parser.add_argument("--briefing", action="store_true", help="Generate daily briefing")
    parser.add_argument("--samples", type=int, default=None, help="Override sample count")
    parser.add_argument("--days", type=int, default=180, help="Projection horizon in days")
    args = parser.parse_args()

    if args.update:
        from clients.assemble_snapshot import assemble_snapshot
        snapshot = assemble_snapshot()
        print(f"Snapshot saved: {snapshot}")
    elif args.quick:
        from network.inference import quick_run
        results = quick_run(n_samples=args.samples or 1000, n_days=args.days)
        _print_quick_results(results)
    elif args.fleet:
        print("Fleet mode not yet implemented. Use --quick for single scenario.")
        sys.exit(1)
    elif args.briefing:
        print("Briefing mode not yet implemented.")
        sys.exit(1)
    else:
        parser.print_help()


def _print_quick_results(results):
    """Print quick-run results to terminal."""
    print("\n=== Iran Crisis Scenario — Quick Run ===\n")
    print(f"  Projection: {results['n_days']} days from {results['start_date']}")
    print(f"  Samples: {results['n_samples']}")
    print()
    for metric, dist in results.get("metrics", {}).items():
        label = metric.replace("_", " ").title()
        p50 = dist.get("p50", "?")
        p5 = dist.get("p5", "?")
        p95 = dist.get("p95", "?")
        print(f"  {label}: {p50}  (90% CI: {p5} – {p95})")
    print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Create venv and install deps**

```bash
cd /Users/danielwaterfield/Documents/autoresearcher-irancrisis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 8: Verify run.py works**

Run: `python run.py --help`
Expected: Help text with --quick, --fleet, --update, --briefing options.

- [ ] **Step 9: Commit scaffold**

```bash
git add -A
git commit -m "feat: project scaffold with CLI entry point and dependencies"
```

---

### Task 2: satint data client

**Files:**
- Create: `clients/satint_client.py`
- Create: `tests/test_satint_client.py`

The satint client reads the exported JSON files from the satint pipeline at `/Users/danielwaterfield/Documents/iran_satellite /docs/data/`. It does not query the database — it reads the static JSON exports.

- [ ] **Step 1: Write failing test**

```python
# tests/test_satint_client.py
import json
import os
import tempfile
from pathlib import Path

from clients.satint_client import fetch_satint_data


def test_fetch_satint_data_reads_exports(tmp_path):
    """satint client reads exported JSON files and returns structured dict."""
    # Create mock satint export files
    nightlights = {"observations": [{"city": "Tehran", "date": "2026-03-08", "pct_change": -78.0}]}
    fires = {"total": 1050, "date": "2026-03-15"}
    compound_risk = {"indicators": [{"city": "Tehran", "date": "2026-03-15", "compound_risk": 0.85}]}
    internet = {"observations": [{"country": "Iran", "date": "2026-03-14", "overall_connectivity": 0.04}]}
    sar = {"detections": [{"chokepoint": "Hormuz", "date": "2026-03-09", "pct_change": -55.0}]}
    meta = {"exported_at": "2026-03-15T21:00:00Z"}

    for name, data in [("nightlights", nightlights), ("fires", fires),
                       ("compound_risk", compound_risk), ("internet", internet),
                       ("sar", sar), ("meta", meta)]:
        (tmp_path / f"{name}.json").write_text(json.dumps(data))

    result = fetch_satint_data(str(tmp_path))

    assert result is not None
    assert "nightlights" in result
    assert "fires" in result
    assert "internet" in result
    assert "sar" in result
    assert result["nightlights"]["observations"][0]["pct_change"] == -78.0
    assert result["sar"]["detections"][0]["pct_change"] == -55.0


def test_fetch_satint_data_missing_dir():
    """Returns None if satint export directory doesn't exist."""
    result = fetch_satint_data("/nonexistent/path")
    assert result is None


def test_fetch_satint_data_partial_files(tmp_path):
    """Returns partial data if some files are missing."""
    nightlights = {"observations": []}
    (tmp_path / "nightlights.json").write_text(json.dumps(nightlights))
    (tmp_path / "meta.json").write_text(json.dumps({"exported_at": "2026-03-15"}))

    result = fetch_satint_data(str(tmp_path))
    assert result is not None
    assert "nightlights" in result
    assert result.get("fires") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/danielwaterfield/Documents/autoresearcher-irancrisis && python -m pytest tests/test_satint_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clients.satint_client'`

- [ ] **Step 3: Implement satint_client.py**

```python
# clients/satint_client.py
"""Read satint pipeline JSON exports."""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Default path to satint exports
DEFAULT_SATINT_PATH = "/Users/danielwaterfield/Documents/iran_satellite /docs/data"

# Files we read and their keys
EXPORT_FILES = [
    "nightlights", "fires", "fires_infra", "fires_geojson",
    "compound_risk", "internet", "sar", "thermal_signatures",
    "flights", "nz", "fuel_security", "meta",
]


def fetch_satint_data(export_dir: str = DEFAULT_SATINT_PATH) -> dict | None:
    """Read all satint JSON exports from the given directory.

    Returns a dict keyed by filename (without .json), or None if dir doesn't exist.
    Missing files are returned as None values.
    """
    export_path = Path(export_dir)
    if not export_path.is_dir():
        logger.warning("satint export dir not found: %s", export_dir)
        return None

    result = {}
    for name in EXPORT_FILES:
        filepath = export_path / f"{name}.json"
        if filepath.exists():
            try:
                result[name] = json.loads(filepath.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read %s: %s", filepath, e)
                result[name] = None
        else:
            result[name] = None

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_satint_client.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add clients/satint_client.py tests/test_satint_client.py
git commit -m "feat: satint data client reads pipeline JSON exports"
```

---

### Task 3: yfinance market data client

**Files:**
- Create: `clients/yfinance_client.py`
- Create: `tests/test_yfinance_client.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_yfinance_client.py
from unittest.mock import patch, MagicMock
from clients.yfinance_client import fetch_market_data


def test_fetch_market_data_returns_structured_dict():
    """Market client returns energy, financial, and index data."""
    # Mock yfinance to avoid network calls in tests
    mock_ticker = MagicMock()
    mock_ticker.info = {"regularMarketPrice": 127.40}
    mock_ticker.history.return_value = MagicMock()
    mock_ticker.history.return_value.empty = False
    mock_ticker.history.return_value.__getitem__ = lambda self, key: MagicMock(iloc=MagicMock(__getitem__=lambda s, i: 127.40))

    with patch("clients.yfinance_client.yf.Ticker", return_value=mock_ticker):
        result = fetch_market_data()

    assert result is not None
    assert "brent_usd" in result
    assert "nzd_usd" in result


def test_fetch_market_data_handles_failure():
    """Returns partial data on API failure."""
    with patch("clients.yfinance_client.yf.Ticker", side_effect=Exception("API down")):
        result = fetch_market_data()

    assert result is not None
    assert result.get("brent_usd") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_yfinance_client.py -v`
Expected: FAIL

- [ ] **Step 3: Implement yfinance_client.py**

```python
# clients/yfinance_client.py
"""Fetch market data from Yahoo Finance."""
import logging

import yfinance as yf

logger = logging.getLogger(__name__)

TICKERS = {
    "brent_usd": "BZ=F",
    "wti_usd": "CL=F",
    "natural_gas_usd": "NG=F",
    "nzd_usd": "NZDUSD=X",
    "usd_sar": "SAR=X",
    "usd_aed": "AED=X",
    "gold_usd": "GC=F",
    "tadawul": "^TASI.SR",
    "dfm": "DFMGI.AE",
}


def _get_price(symbol: str) -> float | None:
    """Get latest price for a single ticker."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 4)
    except Exception as e:
        logger.warning("yfinance failed for %s: %s", symbol, e)
        return None


def fetch_market_data() -> dict:
    """Fetch all market tickers. Returns dict with None for failures."""
    result = {}
    for key, symbol in TICKERS.items():
        result[key] = _get_price(symbol)
    return result
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_yfinance_client.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add clients/yfinance_client.py tests/test_yfinance_client.py
git commit -m "feat: yfinance market data client for oil, FX, Gulf indices"
```

---

### Task 4: World state snapshot assembler

**Files:**
- Create: `clients/assemble_snapshot.py`
- Create: `tests/test_assemble_snapshot.py`

This merges all client outputs into a single world state JSON with `raw_signal` and `estimated_actual` fields.

- [ ] **Step 1: Write failing test**

```python
# tests/test_assemble_snapshot.py
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from clients.assemble_snapshot import assemble_snapshot, build_world_state


def test_build_world_state_from_market_and_satint():
    """World state merges market + satint data with signal/actual fields."""
    market = {"brent_usd": 127.40, "nzd_usd": 0.568}
    satint = {
        "nightlights": {"observations": [
            {"city": "Tehran", "date": "2026-03-08", "pct_change": -78.0},
        ]},
        "sar": {"detections": [
            {"chokepoint": "Hormuz", "date": "2026-03-09", "pct_change": -55.0},
        ]},
        "internet": {"observations": [
            {"country": "Iran", "date": "2026-03-14", "overall_connectivity": 0.04},
        ]},
        "fuel_security": {"depletion_projections": {
            "petrol": {"onshore_days": 32.8, "days_to_mso": 10.0},
        }},
        "meta": {"exported_at": "2026-03-15T21:00:00Z"},
    }

    state = build_world_state(market_data=market, satint_data=satint, today=date(2026, 3, 16))

    assert state["date"] == "2026-03-16"
    assert state["energy"]["brent_usd"]["raw_signal"] == 127.40
    assert state["maritime"]["hormuz_vessel_pct_change"]["raw_signal"] == -55.0
    assert state["maritime"]["hormuz_vessel_pct_change"]["estimated_actual"]["estimate"] <= -80
    assert state["conflict"]["war_day"] == 16


def test_build_world_state_handles_missing_data():
    """World state gracefully handles None/missing sources."""
    state = build_world_state(market_data={}, satint_data=None, today=date(2026, 3, 16))

    assert state["date"] == "2026-03-16"
    assert state["energy"]["brent_usd"]["raw_signal"] is None
    assert state["conflict"]["war_day"] == 16


def test_assemble_snapshot_saves_json(tmp_path):
    """assemble_snapshot writes JSON to data/snapshots/."""
    with patch("clients.assemble_snapshot.SNAPSHOT_DIR", str(tmp_path)), \
         patch("clients.assemble_snapshot.fetch_market_data", return_value={"brent_usd": 127.0}), \
         patch("clients.assemble_snapshot.fetch_satint_data", return_value=None):
        path = assemble_snapshot()

    assert Path(path).exists()
    data = json.loads(Path(path).read_text())
    assert "date" in data
    assert "energy" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_assemble_snapshot.py -v`
Expected: FAIL

- [ ] **Step 3: Implement assemble_snapshot.py**

```python
# clients/assemble_snapshot.py
"""Assemble world state snapshot from all data sources."""
import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

SNAPSHOT_DIR = "data/snapshots"
WAR_START = date(2026, 2, 28)


def _signal(value, source: str, note: str = "") -> dict:
    """Wrap a raw value as a signal entry."""
    return {"raw_signal": value, "estimated_actual": value, "source": source, "note": note}


def _analyst_signal(raw, estimate: float, ci_90: list, source: str, note: str) -> dict:
    """Wrap an analyst-judged signal with uncertainty."""
    return {
        "raw_signal": raw,
        "estimated_actual": {"estimate": estimate, "ci_90": ci_90, "basis": "analyst_judgment"},
        "source": source,
        "note": note,
    }


def build_world_state(market_data: dict, satint_data: dict | None, today: date = None) -> dict:
    """Build a world state dict from raw data sources."""
    today = today or date.today()
    war_day = (today - WAR_START).days

    # --- Extract satint signals ---
    def _satint_latest(section, key, field, default=None):
        if not satint_data or not satint_data.get(section):
            return default
        obs = satint_data[section]
        if isinstance(obs, dict) and key in obs:
            items = obs[key]
            if isinstance(items, list) and items:
                return items[-1].get(field, default)
        return default

    hormuz_pct = _satint_latest("sar", "detections", "pct_change")
    tehran_nl = _satint_latest("nightlights", "observations", "pct_change")
    iran_inet = _satint_latest("internet", "observations", "overall_connectivity")
    fuel_sec = satint_data.get("fuel_security") if satint_data else None

    # NZ stock levels from fuel security export
    nz_petrol_days = None
    if fuel_sec and fuel_sec.get("depletion_projections", {}).get("petrol"):
        nz_petrol_days = fuel_sec["depletion_projections"]["petrol"].get("onshore_days")

    return {
        "date": today.isoformat(),
        "energy": {
            "brent_usd": _signal(market_data.get("brent_usd"), "yfinance"),
            "wti_usd": _signal(market_data.get("wti_usd"), "yfinance"),
            "nz_petrol_nzd_litre": _signal(
                fuel_sec.get("latest_petrol_price") if fuel_sec else None, "mbie"),
        },
        "stocks": {
            "nz_petrol_onshore_days": _signal(nz_petrol_days, "mbie/satint"),
        },
        "maritime": {
            "hormuz_vessel_pct_change": _analyst_signal(
                raw=hormuz_pct,
                estimate=-95.0 if hormuz_pct is not None and hormuz_pct < -20 else (hormuz_pct or 0),
                ci_90=[-100, -80] if hormuz_pct is not None and hormuz_pct < -20 else [-100, 0],
                source="satint_sar",
                note="SAR detects presence not transit. Commercial transit estimate.",
            ) if hormuz_pct is not None else _signal(None, "satint_sar", "No SAR data"),
        },
        "conflict": {
            "war_day": max(0, war_day),
            "acled_events_iran_7d": None,  # V2
        },
        "grid": {
            "tehran_nightlight_pct": _signal(tehran_nl, "satint"),
            "iran_internet": _analyst_signal(
                raw=iran_inet,
                estimate=-99.0 if iran_inet is not None and iran_inet < 0.5 else 0,
                ci_90=[-100, -90] if iran_inet is not None and iran_inet < 0.5 else [-50, 0],
                source="satint_ioda",
                note="IODA includes VPN. Civilian infra estimate.",
            ) if iran_inet is not None else _signal(None, "satint_ioda"),
        },
        "financial": {
            "nzd_usd": _signal(market_data.get("nzd_usd"), "yfinance"),
            "tadawul_pct": _signal(market_data.get("tadawul"), "yfinance"),
        },
    }


def assemble_snapshot(today: date = None) -> str:
    """Fetch all sources, build world state, save to JSON. Returns file path."""
    from clients.yfinance_client import fetch_market_data
    from clients.satint_client import fetch_satint_data

    today = today or date.today()
    logger.info("Assembling world state snapshot for %s", today)

    market = fetch_market_data()
    satint = fetch_satint_data()
    state = build_world_state(market, satint, today)

    out_dir = Path(SNAPSHOT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{today.isoformat()}.json"
    out_path.write_text(json.dumps(state, indent=2, default=str))

    logger.info("Snapshot saved: %s", out_path)
    return str(out_path)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_assemble_snapshot.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add clients/assemble_snapshot.py tests/test_assemble_snapshot.py
git commit -m "feat: world state snapshot assembler with signal/actual translation"
```

---

## Chunk 2: Forward Monte Carlo Simulator

### Task 5: Network structure — node definitions and DAG topology

**Files:**
- Create: `network/structure.py`
- Create: `tests/test_structure.py`

Defines the causal graph: which nodes exist, what their parents are, and the topological sort order for within-day sampling.

- [ ] **Step 1: Write failing test**

```python
# tests/test_structure.py
from network.structure import CausalGraph, NODES


def test_nodes_defined():
    """All MVP nodes are defined."""
    expected = [
        "escalation_level", "ceasefire", "hormuz_status",
        "oil_price", "shipping_cost", "insurance_premiums",
        "gulf_refinery_state",
        "nz_fuel_price", "nz_stock_depletion", "nz_days_to_rationing",
    ]
    for name in expected:
        assert name in NODES, f"Missing node: {name}"


def test_causal_graph_is_dag():
    """Within-day graph has no cycles."""
    graph = CausalGraph()
    order = graph.topological_sort()
    assert len(order) == len(NODES)
    # Verify ordering: parents always before children
    positions = {name: i for i, name in enumerate(order)}
    for node_name, node_def in NODES.items():
        for parent in node_def.get("parents", []):
            assert positions[parent] < positions[node_name], \
                f"Parent {parent} must come before {node_name}"


def test_cause_layer_has_no_parents():
    """Cause layer nodes have no within-day parents."""
    cause_nodes = ["escalation_level", "ceasefire", "hormuz_status"]
    for name in cause_nodes:
        assert NODES[name].get("parents", []) == [], f"{name} should have no parents"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_structure.py -v`
Expected: FAIL

- [ ] **Step 3: Implement structure.py**

```python
# network/structure.py
"""Causal network structure — node definitions and DAG topology."""
from collections import deque

# MVP node definitions. Each node has:
#   layer: cause | transmission | nz_impact
#   parents: list of within-day parent node names (DAG — no cycles)
#   unit: human-readable unit
#   description: what the node represents
NODES = {
    # --- Cause layer (no within-day parents; driven by priors + cross-day feedback) ---
    "escalation_level": {
        "layer": "cause",
        "parents": [],
        "unit": "[0, 1]",
        "description": "Current conflict intensity. 0=ceasefire, 1=full regional war.",
    },
    "ceasefire": {
        "layer": "cause",
        "parents": [],
        "unit": "boolean",
        "description": "Whether ceasefire has occurred by this day.",
    },
    "hormuz_status": {
        "layer": "cause",
        "parents": [],
        "unit": "[0, 1]",
        "description": "Fraction of commercial transit blocked. 0=open, 1=fully closed.",
    },

    # --- Transmission layer ---
    "gulf_refinery_state": {
        "layer": "transmission",
        "parents": ["escalation_level"],
        "unit": "[0, 1]",
        "description": "Fraction of Gulf refining capacity operational.",
    },
    "oil_price": {
        "layer": "transmission",
        "parents": ["hormuz_status", "gulf_refinery_state"],
        "unit": "USD/bbl",
        "description": "Brent crude price.",
    },
    "shipping_cost": {
        "layer": "transmission",
        "parents": ["hormuz_status"],
        "unit": "multiplier",
        "description": "Shipping cost multiplier relative to pre-war baseline.",
    },
    "insurance_premiums": {
        "layer": "transmission",
        "parents": ["hormuz_status", "escalation_level"],
        "unit": "multiplier",
        "description": "War risk insurance premium multiplier.",
    },

    # --- NZ impact layer ---
    "nz_fuel_price": {
        "layer": "nz_impact",
        "parents": ["oil_price", "shipping_cost", "insurance_premiums"],
        "unit": "NZD/litre",
        "description": "NZ retail petrol price.",
    },
    "nz_stock_depletion": {
        "layer": "nz_impact",
        "parents": ["hormuz_status", "shipping_cost"],
        "unit": "days_of_supply",
        "description": "NZ onshore petrol stock in days of supply.",
    },
    "nz_days_to_rationing": {
        "layer": "nz_impact",
        "parents": ["nz_stock_depletion"],
        "unit": "days",
        "description": "Days until NZ petrol stocks breach MSO minimum.",
    },
}


class CausalGraph:
    """DAG structure for within-day causal ordering."""

    def __init__(self, nodes: dict = None):
        self.nodes = nodes or NODES

    def topological_sort(self) -> list[str]:
        """Return node names in valid sampling order (parents before children)."""
        in_degree = {name: 0 for name in self.nodes}
        children = {name: [] for name in self.nodes}
        for name, defn in self.nodes.items():
            for parent in defn.get("parents", []):
                children[parent].append(name)
                in_degree[name] += 1

        queue = deque(name for name, deg in in_degree.items() if deg == 0)
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for child in children[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(order) != len(self.nodes):
            raise ValueError("Cycle detected in within-day causal graph")
        return order
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_structure.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add network/structure.py tests/test_structure.py
git commit -m "feat: causal network structure with DAG topology and topological sort"
```

---

### Task 6: Node sampling functions

**Files:**
- Create: `network/nodes.py`
- Create: `tests/test_nodes.py`

Each node is a callable that takes parent values + previous day state + rng, and returns a sampled value.

- [ ] **Step 1: Write failing test**

```python
# tests/test_nodes.py
import numpy as np
from network.nodes import sample_node, NODE_SAMPLERS


def test_all_nodes_have_samplers():
    """Every node in the structure has a sampling function."""
    from network.structure import NODES
    for name in NODES:
        assert name in NODE_SAMPLERS, f"Missing sampler for {name}"


def test_oil_price_increases_with_hormuz_closure():
    """Higher Hormuz closure → higher oil price."""
    rng = np.random.default_rng(42)
    prices_open = [sample_node("oil_price", {"hormuz_status": 0.1, "gulf_refinery_state": 0.9}, {}, rng) for _ in range(200)]
    prices_closed = [sample_node("oil_price", {"hormuz_status": 0.95, "gulf_refinery_state": 0.5}, {}, rng) for _ in range(200)]
    assert np.mean(prices_closed) > np.mean(prices_open) * 1.3


def test_nz_stock_depletion_decreases_over_time():
    """NZ stocks deplete when Hormuz is closed."""
    rng = np.random.default_rng(42)
    prev = {"nz_stock_depletion": 32.0}
    parents = {"hormuz_status": 0.95, "shipping_cost": 2.5}
    new_stock = sample_node("nz_stock_depletion", parents, prev, rng)
    assert new_stock < 32.0


def test_ceasefire_is_boolean():
    """Ceasefire node returns 0 or 1."""
    rng = np.random.default_rng(42)
    for _ in range(50):
        val = sample_node("ceasefire", {}, {"ceasefire": 0, "war_day": 30}, rng)
        assert val in (0, 1)


def test_ceasefire_stays_once_triggered():
    """Once ceasefire=1, it stays 1."""
    rng = np.random.default_rng(42)
    val = sample_node("ceasefire", {}, {"ceasefire": 1, "war_day": 50}, rng)
    assert val == 1


def test_node_sampling_is_deterministic_with_seed():
    """Same seed produces same results."""
    parents = {"hormuz_status": 0.5, "gulf_refinery_state": 0.7}
    v1 = sample_node("oil_price", parents, {}, np.random.default_rng(99))
    v2 = sample_node("oil_price", parents, {}, np.random.default_rng(99))
    assert v1 == v2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_nodes.py -v`
Expected: FAIL

- [ ] **Step 3: Implement nodes.py**

```python
# network/nodes.py
"""Node sampling functions for the causal network.

Each function signature: (parents: dict, prev_state: dict, rng: np.random.Generator) -> float

parents: current-day parent node values (within-day DAG)
prev_state: previous day's full state dict (for cross-day feedback)
rng: numpy random generator for reproducibility

CPDs are expert-elicited, not empirically estimated. See spec caveats.
"""
import numpy as np
from scipy import stats

# --- Configurable parameters (these are what explorer agents modify) ---
PARAMS = {
    # Ceasefire
    "ceasefire_daily_prob": 0.003,        # ~10% chance within 30 days
    "ceasefire_prob_weekly_increase": 0.01,  # probability rises over time

    # Hormuz
    "hormuz_baseline_closure": 0.95,       # current closure level
    "hormuz_post_ceasefire_reopen_rate": 0.03,  # fraction reopened per day after ceasefire

    # Oil price
    "oil_baseline_usd": 80.0,             # pre-war Brent
    "oil_hormuz_sensitivity": 0.8,         # price multiplier per unit of Hormuz closure
    "oil_refinery_sensitivity": 0.3,       # price multiplier per unit of refinery damage
    "oil_demand_destruction_rate": 0.002,  # daily price decay from demand destruction
    "oil_volatility": 0.03,               # daily log-normal volatility

    # Shipping
    "shipping_hormuz_multiplier": 2.5,     # max shipping cost multiplier at full closure
    "cape_additional_days": 14,

    # Insurance
    "insurance_max_multiplier": 5.0,
    "insurance_decay_rate": 0.01,          # daily decay after ceasefire

    # Gulf refinery
    "refinery_initial_damage": 0.20,
    "refinery_repair_rate": 0.005,         # fraction repaired per day
    "refinery_strike_prob": 0.02,          # daily probability of further strike

    # NZ fuel
    "nz_fuel_passthrough_speed": 0.15,     # fraction of oil price change passed through per day
    "nz_demand_surge": 1.15,              # panic buying multiplier
    "nz_hormuz_dependency": 0.40,
    "nz_mso_petrol": 28.0,               # minimum stockholding obligation (days)
}


def _sample_ceasefire(parents, prev, rng):
    """Ceasefire is absorbing: once triggered, stays 1."""
    if prev.get("ceasefire", 0) == 1:
        return 1
    war_day = prev.get("war_day", 0)
    weekly_increase = PARAMS["ceasefire_prob_weekly_increase"]
    daily_prob = PARAMS["ceasefire_daily_prob"] + (war_day / 7) * weekly_increase
    daily_prob = min(daily_prob, 0.15)  # cap at 15% per day
    return 1 if rng.random() < daily_prob else 0


def _sample_escalation(parents, prev, rng):
    """Escalation level: mean-reverting with shocks."""
    prev_esc = prev.get("escalation_level", 0.7)
    ceasefire = prev.get("ceasefire", 0)
    if ceasefire:
        # De-escalate toward 0
        return max(0, prev_esc - 0.05 + rng.normal(0, 0.02))
    # Mean-revert toward 0.7 with noise
    return np.clip(prev_esc + rng.normal(0, 0.05), 0, 1)


def _sample_hormuz(parents, prev, rng):
    """Hormuz closure: high while war active, reopens after ceasefire."""
    ceasefire = prev.get("ceasefire", 0)
    prev_h = prev.get("hormuz_status", PARAMS["hormuz_baseline_closure"])
    if ceasefire:
        reopen = PARAMS["hormuz_post_ceasefire_reopen_rate"]
        new_h = prev_h - reopen + rng.normal(0, 0.01)
    else:
        # Stay near baseline closure with small noise
        new_h = prev_h + rng.normal(0, 0.02)
    return np.clip(new_h, 0, 1)


def _sample_gulf_refinery(parents, prev, rng):
    """Gulf refinery capacity: degrades from strikes, repairs over time."""
    prev_state = prev.get("gulf_refinery_state", 1.0 - PARAMS["refinery_initial_damage"])
    escalation = parents.get("escalation_level", 0.5)

    # Possible further strike damage
    if rng.random() < PARAMS["refinery_strike_prob"] * escalation:
        damage = rng.uniform(0.02, 0.08)
        prev_state -= damage

    # Repair
    prev_state += PARAMS["refinery_repair_rate"]
    return np.clip(prev_state + rng.normal(0, 0.005), 0.1, 1.0)


def _sample_oil_price(parents, prev, rng):
    """Oil price: driven by Hormuz closure and refinery state."""
    base = PARAMS["oil_baseline_usd"]
    hormuz = parents.get("hormuz_status", 0)
    refinery = parents.get("gulf_refinery_state", 1.0)
    prev_price = prev.get("oil_price", base)

    # Supply disruption premium
    hormuz_premium = hormuz * PARAMS["oil_hormuz_sensitivity"]
    refinery_premium = (1 - refinery) * PARAMS["oil_refinery_sensitivity"]
    target = base * (1 + hormuz_premium + refinery_premium)

    # Demand destruction: high prices erode demand
    if prev_price > base * 1.5:
        target *= (1 - PARAMS["oil_demand_destruction_rate"] * (prev_price / base - 1.5))

    # Move toward target with momentum + volatility
    price = prev_price + 0.2 * (target - prev_price)
    price *= np.exp(rng.normal(0, PARAMS["oil_volatility"]))
    return max(40, price)  # floor at $40


def _sample_shipping_cost(parents, prev, rng):
    """Shipping cost multiplier: Cape rerouting adds cost when Hormuz closed."""
    hormuz = parents.get("hormuz_status", 0)
    max_mult = PARAMS["shipping_hormuz_multiplier"]
    mult = 1.0 + (max_mult - 1.0) * hormuz
    return mult * np.exp(rng.normal(0, 0.02))  # small noise


def _sample_insurance(parents, prev, rng):
    """War risk insurance premium: spikes with conflict, slow decay after ceasefire."""
    hormuz = parents.get("hormuz_status", 0)
    escalation = parents.get("escalation_level", 0.5)
    prev_ins = prev.get("insurance_premiums", 1.0)
    ceasefire = prev.get("ceasefire", 0)

    target = 1.0 + (PARAMS["insurance_max_multiplier"] - 1.0) * max(hormuz, escalation)
    if ceasefire:
        target = max(1.0, prev_ins * (1 - PARAMS["insurance_decay_rate"]))

    return prev_ins + 0.15 * (target - prev_ins) + rng.normal(0, 0.05)


def _sample_nz_fuel_price(parents, prev, rng):
    """NZ retail petrol price: passes through oil + shipping + insurance."""
    oil = parents.get("oil_price", 80)
    shipping = parents.get("shipping_cost", 1.0)
    insurance = parents.get("insurance_premiums", 1.0)
    prev_price = prev.get("nz_fuel_price", 2.50)

    # Target price = baseline proportional to oil, adjusted for shipping/insurance
    target = 2.50 * (oil / 80) * (0.6 + 0.2 * shipping + 0.2 * insurance)
    speed = PARAMS["nz_fuel_passthrough_speed"]
    new_price = prev_price + speed * (target - prev_price)
    return max(1.50, new_price + rng.normal(0, 0.02))


def _sample_nz_stock(parents, prev, rng):
    """NZ onshore petrol stock: depletes when supply disrupted, demand surged."""
    hormuz = parents.get("hormuz_status", 0)
    prev_stock = prev.get("nz_stock_depletion", 32.0)

    supply_loss = hormuz * PARAMS["nz_hormuz_dependency"]
    demand_excess = PARAMS["nz_demand_surge"] - 1.0
    daily_depletion = supply_loss + demand_excess

    new_stock = prev_stock - daily_depletion + rng.normal(0, 0.1)
    return max(0, new_stock)


def _sample_nz_rationing(parents, prev, rng):
    """Days until NZ petrol hits MSO. Derived from stock level."""
    stock = parents.get("nz_stock_depletion", 32.0)
    mso = PARAMS["nz_mso_petrol"]
    above_mso = stock - mso
    if above_mso <= 0:
        return 0  # already at or below MSO
    # Estimate days remaining at current depletion rate
    hormuz = prev.get("hormuz_status", 0.95)
    daily_rate = hormuz * PARAMS["nz_hormuz_dependency"] + (PARAMS["nz_demand_surge"] - 1.0)
    if daily_rate <= 0:
        return 365  # no depletion
    return above_mso / daily_rate


# --- Registry ---
NODE_SAMPLERS = {
    "escalation_level": _sample_escalation,
    "ceasefire": _sample_ceasefire,
    "hormuz_status": _sample_hormuz,
    "gulf_refinery_state": _sample_gulf_refinery,
    "oil_price": _sample_oil_price,
    "shipping_cost": _sample_shipping_cost,
    "insurance_premiums": _sample_insurance,
    "nz_fuel_price": _sample_nz_fuel_price,
    "nz_stock_depletion": _sample_nz_stock,
    "nz_days_to_rationing": _sample_nz_rationing,
}


def sample_node(name: str, parents: dict, prev_state: dict, rng: np.random.Generator) -> float:
    """Sample a single node given parent values and previous state."""
    return NODE_SAMPLERS[name](parents, prev_state, rng)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_nodes.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add network/nodes.py tests/test_nodes.py
git commit -m "feat: node sampling functions with expert-elicited CPDs"
```

---

### Task 7: Forward MC inference engine

**Files:**
- Create: `network/inference.py`
- Create: `tests/test_inference.py`

The core simulation loop: sample N paths of D days through the network.

- [ ] **Step 1: Write failing test**

```python
# tests/test_inference.py
import numpy as np
from network.inference import simulate, quick_run


def test_simulate_returns_correct_shape():
    """simulate() returns (n_samples, n_days, n_nodes) array + metadata."""
    result = simulate(n_samples=50, n_days=30, seed=42)
    assert "traces" in result
    assert "metrics" in result
    assert result["traces"].shape[0] == 50   # samples
    assert result["traces"].shape[1] == 30   # days
    assert result["n_samples"] == 50
    assert result["n_days"] == 30


def test_simulate_is_deterministic():
    """Same seed → same results."""
    r1 = simulate(n_samples=10, n_days=10, seed=42)
    r2 = simulate(n_samples=10, n_days=10, seed=42)
    np.testing.assert_array_equal(r1["traces"], r2["traces"])


def test_simulate_metrics_have_percentiles():
    """Output metrics include p5, p25, p50, p75, p95."""
    result = simulate(n_samples=100, n_days=30, seed=42)
    for metric_name, dist in result["metrics"].items():
        for p in ["p5", "p25", "p50", "p75", "p95"]:
            assert p in dist, f"Missing {p} in {metric_name}"


def test_oil_price_elevated_under_crisis():
    """Under default params (Hormuz 95% closed), oil price should be well above $80 baseline."""
    result = simulate(n_samples=200, n_days=30, seed=42)
    median_oil = result["metrics"]["oil_price_day30"]["p50"]
    assert median_oil > 100, f"Expected oil >$100, got {median_oil}"


def test_nz_stocks_deplete():
    """NZ stocks should decrease over 30 days of crisis."""
    result = simulate(n_samples=200, n_days=30, seed=42)
    median_stock_d30 = result["metrics"]["nz_stock_day30"]["p50"]
    assert median_stock_d30 < 25, f"Expected stock <25, got {median_stock_d30}"


def test_quick_run_returns_summary():
    """quick_run() returns a user-friendly dict."""
    result = quick_run(n_samples=50, n_days=30)
    assert "metrics" in result
    assert "start_date" in result
    assert "nz_days_to_rationing" in result["metrics"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_inference.py -v`
Expected: FAIL

- [ ] **Step 3: Implement inference.py**

```python
# network/inference.py
"""Forward Monte Carlo inference engine."""
import logging
from datetime import date

import numpy as np

from network.structure import CausalGraph, NODES
from network.nodes import sample_node, PARAMS

logger = logging.getLogger(__name__)

WAR_START = date(2026, 2, 28)

# Default initial state (current crisis conditions as of mid-March 2026)
DEFAULT_INITIAL_STATE = {
    "escalation_level": 0.7,
    "ceasefire": 0,
    "hormuz_status": 0.95,
    "gulf_refinery_state": 0.80,
    "oil_price": 127.0,
    "shipping_cost": 2.3,
    "insurance_premiums": 3.5,
    "nz_fuel_price": 3.02,
    "nz_stock_depletion": 30.8,
    "nz_days_to_rationing": 10.0,
    "war_day": 16,
}


def simulate(
    n_samples: int = 5000,
    n_days: int = 180,
    seed: int = 42,
    initial_state: dict = None,
    params: dict = None,
) -> dict:
    """Run forward Monte Carlo simulation.

    Returns dict with:
        traces: np.ndarray of shape (n_samples, n_days, n_nodes)
        node_names: list of node names (column order)
        metrics: dict of summary statistics with percentiles
        n_samples, n_days, seed: run metadata
    """
    if params:
        PARAMS.update(params)

    init = initial_state or DEFAULT_INITIAL_STATE
    graph = CausalGraph()
    node_order = graph.topological_sort()
    node_idx = {name: i for i, name in enumerate(node_order)}
    n_nodes = len(node_order)

    traces = np.zeros((n_samples, n_days, n_nodes))
    base_rng = np.random.default_rng(seed)
    # Generate per-sample seeds for reproducibility
    sample_seeds = base_rng.integers(0, 2**32, size=n_samples)

    for s in range(n_samples):
        rng = np.random.default_rng(sample_seeds[s])
        prev_state = dict(init)

        for d in range(n_days):
            prev_state["war_day"] = init.get("war_day", 16) + d
            day_state = {}

            for node_name in node_order:
                parent_names = NODES[node_name].get("parents", [])
                parent_values = {p: day_state[p] for p in parent_names}
                value = sample_node(node_name, parent_values, prev_state, rng)
                day_state[node_name] = value
                traces[s, d, node_idx[node_name]] = value

            prev_state.update(day_state)

    # Compute summary metrics
    metrics = _compute_metrics(traces, node_idx, n_days)

    return {
        "traces": traces,
        "node_names": node_order,
        "metrics": metrics,
        "n_samples": n_samples,
        "n_days": n_days,
        "seed": seed,
    }


def _compute_metrics(traces, node_idx, n_days):
    """Compute percentile-based summary metrics from traces."""
    metrics = {}

    def _percentiles(values):
        return {
            "p5": round(float(np.percentile(values, 5)), 2),
            "p25": round(float(np.percentile(values, 25)), 2),
            "p50": round(float(np.percentile(values, 50)), 2),
            "p75": round(float(np.percentile(values, 75)), 2),
            "p95": round(float(np.percentile(values, 95)), 2),
        }

    # Terminal day metrics
    for node_name, idx in node_idx.items():
        metrics[f"{node_name}_day{n_days}"] = _percentiles(traces[:, -1, idx])

    # Key NZ metrics
    if "nz_days_to_rationing" in node_idx:
        idx = node_idx["nz_days_to_rationing"]
        # Find the first day each sample hits 0 (MSO breach)
        rationing_days = []
        for s in range(traces.shape[0]):
            breach_days = np.where(traces[s, :, idx] <= 0)[0]
            rationing_days.append(int(breach_days[0]) if len(breach_days) > 0 else n_days + 1)
        metrics["nz_days_to_rationing"] = _percentiles(rationing_days)

        # Probability of rationing within 30/60/90 days
        arr = np.array(rationing_days)
        for horizon in [30, 60, 90]:
            prob = float(np.mean(arr <= horizon))
            metrics[f"nz_rationing_prob_{horizon}d"] = round(prob, 3)

    # Peak oil price
    if "oil_price" in node_idx:
        idx = node_idx["oil_price"]
        peak_prices = traces[:, :, idx].max(axis=1)
        metrics["brent_peak_usd"] = _percentiles(peak_prices)

    # Ceasefire day
    if "ceasefire" in node_idx:
        idx = node_idx["ceasefire"]
        ceasefire_days = []
        for s in range(traces.shape[0]):
            cf_days = np.where(traces[s, :, idx] >= 1)[0]
            ceasefire_days.append(int(cf_days[0]) if len(cf_days) > 0 else n_days + 1)
        metrics["ceasefire_day"] = _percentiles(ceasefire_days)

    return metrics


def quick_run(n_samples: int = 1000, n_days: int = 180, seed: int = None) -> dict:
    """Quick mode: run simulation and return user-friendly summary."""
    if seed is None:
        seed = int(date.today().strftime("%Y%m%d"))

    result = simulate(n_samples=n_samples, n_days=n_days, seed=seed)

    return {
        "start_date": WAR_START.isoformat(),
        "projection_days": n_days,
        "n_samples": n_samples,
        "seed": seed,
        "metrics": result["metrics"],
    }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_inference.py -v`
Expected: 6 passed

- [ ] **Step 5: Integration test — quick run from CLI**

Run: `cd /Users/danielwaterfield/Documents/autoresearcher-irancrisis && python run.py --quick --samples 200 --days 60`
Expected: Terminal output showing NZ rationing probability, oil price ranges, ceasefire estimates with confidence intervals.

- [ ] **Step 6: Commit**

```bash
git add network/inference.py tests/test_inference.py
git commit -m "feat: forward MC inference engine with percentile metrics"
```

---

## Chunk 3: Explorer Loop

### Task 8: Explorer loop — propose, simulate, accept/reject

**Files:**
- Create: `explorer/loop.py`
- Create: `explorer/agents.py`
- Create: `explorer/accept_reject.py`
- Create: `explorer/prompts.py`
- Create: `tests/test_explorer.py`

- [ ] **Step 1: Write failing test for accept/reject logic**

```python
# tests/test_explorer.py
from explorer.accept_reject import should_accept


def test_accept_sensitivity_discovery():
    """Accept when small param change produces large output shift."""
    baseline = {"nz_days_to_rationing": {"p50": 45}}
    candidate = {"nz_days_to_rationing": {"p50": 25}}  # 44% shift
    cpd_change_magnitude = 0.08  # 8% parameter shift
    result = should_accept(baseline, candidate, cpd_change_magnitude, history=[])
    assert result["accepted"] is True
    assert result["reason"] == "sensitivity_discovery"


def test_reject_redundant():
    """Reject when output is indistinguishable from baseline."""
    baseline = {"nz_days_to_rationing": {"p50": 45}}
    candidate = {"nz_days_to_rationing": {"p50": 44}}  # 2% shift
    result = should_accept(baseline, candidate, 0.05, history=[])
    assert result["accepted"] is False
    assert result["reason"] == "redundant"


def test_accept_tail_exploration():
    """Accept when output is in extreme percentiles of history."""
    baseline = {"nz_days_to_rationing": {"p50": 45}}
    candidate = {"nz_days_to_rationing": {"p50": 8}}  # extreme
    history = [{"metrics": {"nz_days_to_rationing": {"p50": v}}} for v in [40, 42, 44, 46, 48, 50]]
    result = should_accept(baseline, candidate, 0.30, history=history)
    assert result["accepted"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_explorer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement accept_reject.py**

```python
# explorer/accept_reject.py
"""Accept/reject logic for explorer experiments."""
import numpy as np


def should_accept(
    baseline_metrics: dict,
    candidate_metrics: dict,
    cpd_change_magnitude: float,
    history: list,
) -> dict:
    """Decide whether to accept a candidate experiment.

    Returns dict with 'accepted' (bool) and 'reason' (str).
    """
    # Key metric for sensitivity analysis
    key = "nz_days_to_rationing"
    bl_val = baseline_metrics.get(key, {}).get("p50", 0)
    cd_val = candidate_metrics.get(key, {}).get("p50", 0)

    if bl_val == 0:
        pct_shift = abs(cd_val) * 100
    else:
        pct_shift = abs(cd_val - bl_val) / abs(bl_val) * 100

    # 1. Sensitivity discovery: small input → large output
    if cpd_change_magnitude <= 0.10 and pct_shift >= 15:
        return {"accepted": True, "reason": "sensitivity_discovery", "sensitivity_score": pct_shift / cpd_change_magnitude}

    # 2. Tail exploration: extreme output vs history
    if history:
        historical_p50s = [h.get("metrics", {}).get(key, {}).get("p50", 0) for h in history if h.get("metrics")]
        if historical_p50s:
            p5 = np.percentile(historical_p50s, 5)
            p95 = np.percentile(historical_p50s, 95)
            if cd_val < p5 or cd_val > p95:
                return {"accepted": True, "reason": "tail_exploration", "sensitivity_score": pct_shift}

    # 3. Large change with novel output: combination of novelty + output difference
    if cpd_change_magnitude > 0.10 and pct_shift >= 15:
        return {"accepted": True, "reason": "novel_significant", "sensitivity_score": pct_shift}

    # 4. Redundant — output too similar to baseline
    if pct_shift < 5:
        return {"accepted": False, "reason": "redundant", "sensitivity_score": pct_shift}

    # 5. Moderate change — accept if pct_shift meaningful
    if pct_shift >= 10:
        return {"accepted": True, "reason": "moderate_shift", "sensitivity_score": pct_shift}

    return {"accepted": False, "reason": "insufficient_shift", "sensitivity_score": pct_shift}
```

- [ ] **Step 4: Implement agents.py**

```python
# explorer/agents.py
"""Agent definitions for the explorer fleet."""

AGENTS = {
    "escalation_explorer": {
        "prefix": "ESC",
        "mandate": "How does conflict trajectory affect NZ outcomes? Explore ceasefire probability, escalation curves, and strike target assumptions.",
        "searchable_params": [
            "ceasefire_daily_prob", "ceasefire_prob_weekly_increase",
            "hormuz_baseline_closure", "hormuz_post_ceasefire_reopen_rate",
            "refinery_strike_prob", "refinery_initial_damage",
        ],
    },
    "nz_fuel_explorer": {
        "prefix": "NZF",
        "mandate": "What drives NZ fuel security most? Explore demand surge, supply chain lag, government intervention timing, and stock depletion assumptions.",
        "searchable_params": [
            "nz_demand_surge", "nz_hormuz_dependency", "nz_mso_petrol",
            "nz_fuel_passthrough_speed", "oil_demand_destruction_rate",
        ],
    },
    "trade_explorer": {
        "prefix": "TRD",
        "mandate": "How does maritime disruption propagate? Explore Hormuz→oil price elasticity, Cape rerouting speed, insurance decay, and shipping capacity.",
        "searchable_params": [
            "oil_hormuz_sensitivity", "oil_refinery_sensitivity", "oil_volatility",
            "shipping_hormuz_multiplier", "cape_additional_days",
            "insurance_max_multiplier", "insurance_decay_rate",
        ],
    },
}
```

- [ ] **Step 5: Implement prompts.py**

```python
# explorer/prompts.py
"""Prompt templates for explorer agents."""

SYSTEM_TEMPLATE = """You are an autonomous explorer agent investigating how the 2026 Iran war affects New Zealand.

YOUR MANDATE: {mandate}

You propose changes to the model's causal assumptions (conditional probability distribution parameters). Each change is evaluated by Monte Carlo simulation. You see the results of recent experiments and propose the next change.

SEARCHABLE PARAMETERS (you may only modify these):
{param_list}

RULES:
- Propose exactly ONE logical change per experiment (may modify 1-3 related parameters)
- Return ONLY a JSON object
- Parameters must stay within physical constraints
- Your goal is NOT to optimise — it is to discover which assumptions matter most

RESPONSE FORMAT:
```json
{{
    "hypothesis": "2-3 sentences: what you're changing and why you expect it to reveal sensitivity",
    "param_changes": [
        {{"param": "ceasefire_daily_prob", "old": 0.003, "new": 0.01}}
    ]
}}
```

Return ONLY the JSON object. No preamble, no markdown fences."""

USER_TEMPLATE = """EXPERIMENT {experiment_number} | Phase: {phase}

## Current Baseline Metrics (from {n_samples} MC samples, {n_days} days)
{metrics_table}

## Current Parameter Values
{params_table}

## Last 10 Experiments
{history}

Propose your next change."""
```

- [ ] **Step 6: Implement loop.py**

```python
# explorer/loop.py
"""Core explorer loop: propose → simulate → accept/reject → log."""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

import anthropic
import numpy as np

from network.inference import simulate
from network.nodes import PARAMS
from explorer.agents import AGENTS
from explorer.accept_reject import should_accept
from explorer.prompts import SYSTEM_TEMPLATE, USER_TEMPLATE

logger = logging.getLogger(__name__)
LOG_PATH = Path("logs/experiments.jsonl")
LOG_LOCK = Path("logs/experiments.jsonl.lock")


def run_explorer(agent_id: str, max_experiments: int = 60, n_samples: int = 2000, n_days: int = 180):
    """Run the explorer loop for one agent."""
    agent = AGENTS[agent_id]
    prefix = agent["prefix"]
    client = anthropic.Anthropic()

    # Run baseline
    logger.info("Running baseline for %s", agent_id)
    baseline_result = simulate(n_samples=n_samples, n_days=n_days, seed=42)
    baseline_metrics = baseline_result["metrics"]
    current_params = dict(PARAMS)

    history = []

    for exp_num in range(1, max_experiments + 1):
        phase = "sweep" if exp_num <= 20 else ("combination" if exp_num <= 60 else "creative")
        exp_id = f"{prefix}-{exp_num:03d}"

        # Build prompt
        system = SYSTEM_TEMPLATE.format(
            mandate=agent["mandate"],
            param_list="\n".join(f"  - {p}: {current_params[p]}" for p in agent["searchable_params"]),
        )
        user = USER_TEMPLATE.format(
            experiment_number=exp_num,
            phase=phase,
            n_samples=n_samples,
            n_days=n_days,
            metrics_table=_format_metrics(baseline_metrics),
            params_table=_format_params(current_params, agent["searchable_params"]),
            history=_format_history(history[-10:]),
        )

        # Call LLM
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}, {"role": "assistant", "content": "{"}],
            )
            proposal = json.loads("{" + response.content[0].text)
        except Exception as e:
            logger.error("LLM call failed for %s: %s", exp_id, e)
            continue

        # Apply param changes
        test_params = dict(current_params)
        changes = proposal.get("param_changes", [])
        magnitude = 0
        for ch in changes:
            param = ch["param"]
            if param not in agent["searchable_params"]:
                continue
            old_val = current_params.get(param, 0)
            new_val = ch["new"]
            test_params[param] = new_val
            if old_val != 0:
                magnitude = max(magnitude, abs(new_val - old_val) / abs(old_val))

        # Simulate with proposed params
        seed = int(datetime.now(timezone.utc).timestamp()) + exp_num
        candidate_result = simulate(n_samples=n_samples, n_days=n_days, seed=seed, params=test_params)
        candidate_metrics = candidate_result["metrics"]

        # Accept/reject
        decision = should_accept(baseline_metrics, candidate_metrics, magnitude, history)

        # Log
        entry = {
            "experiment_id": exp_id,
            "agent_id": agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hypothesis": proposal.get("hypothesis", ""),
            "seed": seed,
            "cpd_changes": changes,
            "structural_changes": [],
            "output_distribution": {k: v for k, v in candidate_metrics.items()
                                     if k.startswith("nz_") or k.startswith("brent_") or k.startswith("ceasefire_")},
            "baseline_distribution": {k: v for k, v in baseline_metrics.items()
                                       if k.startswith("nz_") or k.startswith("brent_") or k.startswith("ceasefire_")},
            "status": "accepted" if decision["accepted"] else "rejected",
            "acceptance_reason": decision["reason"],
            "sensitivity_score": decision.get("sensitivity_score", 0),
            "phase": phase,
        }

        _log_experiment(entry)
        history.append(entry)

        if decision["accepted"]:
            logger.info("%s ACCEPTED: %s (score=%.1f)", exp_id, decision["reason"], decision.get("sensitivity_score", 0))
            baseline_metrics = candidate_metrics
            current_params = test_params
        else:
            logger.info("%s REJECTED: %s", exp_id, decision["reason"])
            # Restore params
            PARAMS.update(current_params)

        time.sleep(0.5)  # rate limit courtesy


def _log_experiment(entry: dict):
    """Append to JSONL log with file locking."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(LOG_LOCK)):
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def _format_metrics(metrics: dict) -> str:
    lines = []
    for key in sorted(metrics):
        m = metrics[key]
        if isinstance(m, dict) and "p50" in m:
            lines.append(f"  {key}: {m['p50']}  (90% CI: {m.get('p5','?')} – {m.get('p95','?')})")
        elif isinstance(m, (int, float)):
            lines.append(f"  {key}: {m}")
    return "\n".join(lines)


def _format_params(params: dict, searchable: list) -> str:
    return "\n".join(f"  {p}: {params.get(p, '?')}" for p in searchable)


def _format_history(history: list) -> str:
    if not history:
        return "  (no experiments yet)"
    lines = []
    for h in reversed(history):
        status = h["status"].upper()
        changes_summary = "; ".join(f"{c['param']}={c.get('old','?')}→{c.get('new','?')}" for c in h.get("cpd_changes", []))
        lines.append(f"  {h['experiment_id']} {status} | {h.get('acceptance_reason','')} | {changes_summary}")
    return "\n".join(lines)
```

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_explorer.py -v`
Expected: 3 passed

- [ ] **Step 8: Commit**

```bash
git add explorer/ tests/test_explorer.py
git commit -m "feat: explorer loop with accept/reject, agent definitions, and Sonnet prompts"
```

---

### Task 9: Agent mandates and fleet_run.sh

**Files:**
- Create: `programs/escalation.md`
- Create: `programs/nz_fuel.md`
- Create: `programs/trade.md`
- Create: `fleet_run.sh`

- [ ] **Step 1: Write agent mandates**

`programs/escalation.md`:
```markdown
# Escalation Explorer

You investigate how the conflict trajectory affects NZ downstream outcomes. Your primary question: **how sensitive are NZ fuel security timelines to assumptions about escalation, ceasefire timing, and continued strikes?**

Focus areas:
- Ceasefire probability: does a 2x increase in daily ceasefire probability meaningfully change NZ rationing timelines?
- Hormuz reopening rate: how fast must the strait reopen post-ceasefire to prevent NZ rationing?
- Strike continuation: does ongoing refinery damage matter more than Hormuz closure itself?
- Escalation persistence: what if conflict intensity increases rather than mean-reverts?

You are NOT optimising for a "good" outcome. You are mapping which conflict trajectory assumptions drive the most variance in NZ impact.
```

`programs/nz_fuel.md`:
```markdown
# NZ Fuel Explorer

You investigate NZ fuel security sensitivity. Your primary question: **which NZ-specific assumptions matter most for predicting when rationing hits?**

Focus areas:
- Demand surge: is the 15% panic buying assumption too high or too low?
- Hormuz dependency: NZ imports ~40% via Hormuz routes — is this the right number?
- MSO threshold: would lowering MSO from 28 to 24 days delay rationing meaningfully?
- Pass-through speed: how fast do oil price spikes reach NZ pumps?
- Government intervention: would price controls or rationing change the depletion curve?

Ground truth: NZ Herald (Mar 15) reports Gull stations running dry, $3/L breached. MBIE says 52 days total cover as of Mar 8.
```

`programs/trade.md`:
```markdown
# Trade Explorer

You investigate maritime disruption propagation. Your primary question: **how do Hormuz closure parameters propagate through shipping and insurance to NZ fuel costs?**

Focus areas:
- Oil price sensitivity: is the Hormuz→oil price elasticity right? Should it be higher?
- Shipping cost multiplier: 2.5x at full closure — too high or too low?
- Insurance decay: how fast do war risk premiums fall after ceasefire?
- Cape rerouting: 14 additional days — sensitive to this assumption?
- Demand destruction feedback: does high price reduce demand enough to moderate price?

Ground truth: Hormuz SAR shows -55% vessel detection (but effectively closed). Brent at ~$127.
```

- [ ] **Step 2: Write fleet_run.sh**

```bash
#!/bin/bash
# fleet_run.sh — Run explorer fleet in parallel with cross-pollination
set -e

MAX=${1:-60}  # max experiments per agent
SAMPLES=${2:-2000}
DAYS=${3:-180}

echo "=== Iran Crisis Autoresearcher Fleet ==="
echo "Agents: 3 | Max experiments: $MAX | Samples: $SAMPLES | Days: $DAYS"
echo ""

# Activate venv
source .venv/bin/activate

# Launch agents in parallel
python -c "
from explorer.loop import run_explorer
run_explorer('escalation_explorer', max_experiments=$MAX, n_samples=$SAMPLES, n_days=$DAYS)
" &
PID_ESC=$!

python -c "
from explorer.loop import run_explorer
run_explorer('nz_fuel_explorer', max_experiments=$MAX, n_samples=$SAMPLES, n_days=$DAYS)
" &
PID_NZF=$!

python -c "
from explorer.loop import run_explorer
run_explorer('trade_explorer', max_experiments=$MAX, n_samples=$SAMPLES, n_days=$DAYS)
" &
PID_TRD=$!

echo "Launched: escalation=$PID_ESC nz_fuel=$PID_NZF trade=$PID_TRD"

# Wait for all agents
wait $PID_ESC $PID_NZF $PID_TRD

echo ""
echo "=== Fleet complete. Running synthesis... ==="
python -c "
from synthesis.run_synthesis import run_synthesis
run_synthesis()
"

echo "=== Done. Outputs in outputs/ ==="
```

- [ ] **Step 3: Make fleet_run.sh executable**

```bash
chmod +x fleet_run.sh
```

- [ ] **Step 4: Commit**

```bash
git add programs/ fleet_run.sh
git commit -m "feat: agent mandates for 3 MVP explorers and fleet orchestration script"
```

---

## Chunk 4: Synthesis + Quick Mode Integration

### Task 10: Basic synthesis — sensitivity ranking and probability dashboard

**Files:**
- Create: `synthesis/run_synthesis.py`
- Create: `synthesis/prompts.py`
- Create: `tests/test_synthesis.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_synthesis.py
import json
from pathlib import Path
from synthesis.run_synthesis import compute_sensitivity_ranking, generate_probability_dashboard


def test_sensitivity_ranking_from_experiments():
    """Compute which parameters contributed most variance."""
    experiments = [
        {"status": "accepted", "acceptance_reason": "sensitivity_discovery",
         "sensitivity_score": 45.0, "cpd_changes": [{"param": "hormuz_baseline_closure"}]},
        {"status": "accepted", "acceptance_reason": "sensitivity_discovery",
         "sensitivity_score": 30.0, "cpd_changes": [{"param": "ceasefire_daily_prob"}]},
        {"status": "rejected", "acceptance_reason": "redundant",
         "sensitivity_score": 2.0, "cpd_changes": [{"param": "oil_volatility"}]},
        {"status": "accepted", "acceptance_reason": "moderate_shift",
         "sensitivity_score": 12.0, "cpd_changes": [{"param": "hormuz_baseline_closure"}]},
    ]
    ranking = compute_sensitivity_ranking(experiments)
    assert len(ranking) > 0
    assert ranking[0]["parameter"] == "hormuz_baseline_closure"


def test_probability_dashboard_format():
    """Dashboard JSON has required structure."""
    metrics = {
        "nz_days_to_rationing": {"p5": 8, "p25": 18, "p50": 32, "p75": 60, "p95": 120},
        "nz_rationing_prob_30d": 0.65,
        "nz_rationing_prob_60d": 0.82,
        "brent_peak_usd": {"p5": 110, "p25": 125, "p50": 148, "p75": 170, "p95": 210},
        "ceasefire_day": {"p5": 20, "p25": 45, "p50": 80, "p75": 130, "p95": 181},
    }
    dashboard = generate_probability_dashboard(metrics)
    assert "outcomes" in dashboard
    assert "nz_fuel_security" in dashboard
    assert "as_of" in dashboard
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthesis.py -v`
Expected: FAIL

- [ ] **Step 3: Implement run_synthesis.py**

```python
# synthesis/run_synthesis.py
"""Synthesis layer: sensitivity ranking, probability dashboard, and Opus narratives."""
import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

WAR_START = date(2026, 2, 28)
OUTPUT_DIR = Path("outputs")


def load_experiments() -> list:
    """Load all experiments from JSONL log."""
    log_path = Path("logs/experiments.jsonl")
    if not log_path.exists():
        return []
    experiments = []
    for line in log_path.read_text().strip().split("\n"):
        if line:
            experiments.append(json.loads(line))
    return experiments


def compute_sensitivity_ranking(experiments: list) -> list:
    """Rank parameters by their contribution to output variance."""
    param_scores = defaultdict(list)
    for exp in experiments:
        if exp.get("status") != "accepted":
            continue
        score = exp.get("sensitivity_score", 0)
        for change in exp.get("cpd_changes", []):
            param = change.get("param", "unknown")
            param_scores[param].append(score)

    ranking = []
    total_score = sum(max(scores) for scores in param_scores.values()) or 1
    for param, scores in sorted(param_scores.items(), key=lambda x: -max(x[1])):
        ranking.append({
            "parameter": param,
            "max_sensitivity": round(max(scores), 1),
            "mean_sensitivity": round(sum(scores) / len(scores), 1),
            "experiments_accepted": len(scores),
            "variance_contribution": round(max(scores) / total_score, 3),
        })
    return ranking


def generate_probability_dashboard(metrics: dict) -> dict:
    """Generate the probability dashboard JSON for GitHub Pages."""
    today = date.today()
    return {
        "as_of": today.isoformat(),
        "war_day": (today - WAR_START).days,
        "outcomes": {
            "nz_rationing_30d": {"probability": metrics.get("nz_rationing_prob_30d", None)},
            "nz_rationing_60d": {"probability": metrics.get("nz_rationing_prob_60d", None)},
            "nz_rationing_90d": {"probability": metrics.get("nz_rationing_prob_90d", None)},
            "brent_peak_usd": metrics.get("brent_peak_usd", {}),
            "ceasefire_day": metrics.get("ceasefire_day", {}),
        },
        "nz_fuel_security": {
            "days_to_rationing": metrics.get("nz_days_to_rationing", {}),
        },
    }


def run_synthesis():
    """Full synthesis pass: load experiments, compute rankings, write outputs."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    experiments = load_experiments()
    logger.info("Loaded %d experiments", len(experiments))

    # Sensitivity ranking
    ranking = compute_sensitivity_ranking(experiments)
    (OUTPUT_DIR / "sensitivity_ranking.json").write_text(json.dumps(ranking, indent=2))
    logger.info("Wrote sensitivity_ranking.json (%d parameters)", len(ranking))

    # Probability dashboard from latest accepted metrics
    accepted = [e for e in experiments if e.get("status") == "accepted"]
    if accepted:
        latest = accepted[-1].get("output_distribution", {})
        dashboard = generate_probability_dashboard(latest)
    else:
        # Fall back to a quick baseline run
        from network.inference import quick_run
        result = quick_run(n_samples=2000, n_days=180)
        dashboard = generate_probability_dashboard(result["metrics"])

    (OUTPUT_DIR / "probability_dashboard.json").write_text(json.dumps(dashboard, indent=2))
    logger.info("Wrote probability_dashboard.json")

    # Methodology stub
    methodology = f"""# Methodology

## Model Type
Forward Monte Carlo simulator with causal network structure.
Expert-elicited conditional probability distributions. NOT empirically estimated.

## Data Sources
- yfinance: Oil prices, FX rates, Gulf stock indices
- satint pipeline: Nightlights, fires, IODA internet, SAR vessel detection
- MBIE: NZ fuel prices and stock levels

## Calibration
Anchored to observed data as of {date.today().isoformat()} (war day {(date.today() - WAR_START).days}).
Dynamic calibration against observed rate-of-change in Hormuz transit, Tehran nightlights, and NZ fuel prices.

## Caveats
- No historical precedent for full Hormuz closure. All projections extrapolate beyond observed data.
- CPDs are expert-elicited, not learned from historical data.
- The explorer loop characterises sensitivity to assumptions, not ground truth.

## Experiments
{len(experiments)} total experiments across {len(set(e.get('agent_id','') for e in experiments))} agents.
{len(accepted)} accepted, {len(experiments) - len(accepted)} rejected.

Generated: {date.today().isoformat()}
"""
    (OUTPUT_DIR / "methodology.md").write_text(methodology)
    logger.info("Wrote methodology.md")

    print(f"\nSynthesis complete: {len(experiments)} experiments → outputs/")
    if ranking:
        print("\nTop 3 sensitivity drivers:")
        for r in ranking[:3]:
            print(f"  {r['parameter']}: max_sensitivity={r['max_sensitivity']}, contribution={r['variance_contribution']:.0%}")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_synthesis.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add synthesis/ tests/test_synthesis.py
git commit -m "feat: synthesis layer with sensitivity ranking and probability dashboard"
```

---

### Task 11: End-to-end integration test

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_e2e.py
"""End-to-end: snapshot → simulate → quick output."""
from datetime import date
from clients.assemble_snapshot import build_world_state
from network.inference import quick_run


def test_full_pipeline():
    """Build world state, run quick simulation, get probability outputs."""
    market = {"brent_usd": 127.0, "nzd_usd": 0.568}
    satint = {
        "sar": {"detections": [{"chokepoint": "Hormuz", "date": "2026-03-09", "pct_change": -55.0}]},
        "internet": {"observations": [{"country": "Iran", "date": "2026-03-14", "overall_connectivity": 0.04}]},
        "nightlights": {"observations": [{"city": "Tehran", "date": "2026-03-08", "pct_change": -78.0}]},
        "fuel_security": {"depletion_projections": {"petrol": {"onshore_days": 30.8, "days_to_mso": 10.0}}},
        "meta": {"exported_at": "2026-03-15T21:00:00Z"},
    }

    state = build_world_state(market, satint, today=date(2026, 3, 16))
    assert state["conflict"]["war_day"] == 16

    result = quick_run(n_samples=100, n_days=60)
    assert "metrics" in result
    assert result["metrics"]["nz_rationing_prob_30d"] > 0
    assert result["metrics"]["brent_peak_usd"]["p50"] > 100

    # NZ should face rationing risk under crisis conditions
    rationing_prob_60d = result["metrics"].get("nz_rationing_prob_60d", 0)
    assert rationing_prob_60d > 0.3, f"Expected >30% rationing risk, got {rationing_prob_60d}"
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Run quick mode end-to-end**

Run: `cd /Users/danielwaterfield/Documents/autoresearcher-irancrisis && python run.py --quick --samples 500 --days 90`
Expected: Terminal output showing NZ rationing probabilities at 30/60/90 days, oil price forecasts, ceasefire timing distributions.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: end-to-end integration test for snapshot → simulate → output"
```

---

### Task 12: Final commit and verify

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests pass.

- [ ] **Step 2: Verify quick run produces sensible output**

Run: `python run.py --quick --samples 2000 --days 180`
Expected: Output with NZ rationing probabilities, oil price ranges, ceasefire estimates. Verify:
- NZ rationing 30d probability > 50% (given current crisis)
- Brent peak p50 > $120
- Ceasefire day p50 > 30 (unlikely in next month)

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: Iran crisis autoresearcher MVP — forward MC simulator with quick mode"
```
