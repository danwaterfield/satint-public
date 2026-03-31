"""
NZ commodity exposure model for Hormuz-dependent supply chains.

Models depletion and downstream impacts for fertiliser, plastics,
and chemicals beyond the fuel model in scenarios.py.

Uses UN Comtrade bilateral trade data to quantify exposure,
then projects stock depletion and cascading economic effects.
"""

from dataclasses import dataclass
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# NZ commodity profiles — from Comtrade 2024 + MBIE/industry sources
# ---------------------------------------------------------------------------

COMMODITY_PROFILES = {
    "fertiliser_nitrogen": {
        "label": "Nitrogenous Fertiliser (Urea)",
        "hs_code": "3102",
        "annual_import_usd": 258_207_870,
        "hormuz_exposure_pct": 49.5,
        "top_sources": ["Saudi Arabia (44%)", "Indonesia (21%)", "South Korea (7%)"],
        # NZ typically holds 2-3 months of nitrogen fertiliser stock
        # (Ballance Agri-Nutrients, Ravensdown annual reports)
        "stock_days": 75,
        # Seasonal: peak application Sep-Nov (spring) and Mar-Apr (autumn)
        # Current period (late March) is tail end of autumn application
        "seasonal_demand_multiplier": 1.3,  # above average for Mar-Apr
        # Substitution: fraction of lost supply replaceable from non-Hormuz sources
        # Urea is a commodity but Saudi is NZ's #1 source — Indonesia/Malaysia can
        # partially substitute but have own demand commitments
        "substitution_rate": 0.30,  # 30% of lost supply replaceable within 3 months
        # Downstream impact lag: fertiliser shortage → crop yield reduction → food prices
        "impact_lag_weeks": 12,  # ~3 months from shortage to visible crop impact
        "downstream_effects": [
            {"sector": "Dairy", "mechanism": "Pasture growth reduction → lower milk solids",
             "gdp_exposure_pct": 3.5, "lag_weeks": 16},
            {"sector": "Horticulture", "mechanism": "Reduced fruit/vegetable yields",
             "gdp_exposure_pct": 0.8, "lag_weeks": 12},
            {"sector": "Arable", "mechanism": "Wheat/barley yield reduction",
             "gdp_exposure_pct": 0.3, "lag_weeks": 20},
        ],
    },
    "fertiliser_mixed": {
        "label": "Mixed Fertilisers (NPK/DAP)",
        "hs_code": "3105",
        "annual_import_usd": 170_492_115,
        "hormuz_exposure_pct": 14.2,
        "top_sources": ["China (36%)", "Saudi Arabia (10%)", "Australia (9%)"],
        "stock_days": 60,
        "seasonal_demand_multiplier": 1.3,
        "substitution_rate": 0.40,  # more diversified supply — China/Australia alternatives
        "impact_lag_weeks": 12,
        "downstream_effects": [
            {"sector": "Dairy", "mechanism": "Phosphate/potash limits pasture response",
             "gdp_exposure_pct": 1.0, "lag_weeks": 16},
        ],
    },
    "polyethylene": {
        "label": "Polyethylene (Packaging/Film)",
        "hs_code": "3901",
        "annual_import_usd": 164_162_746,
        "hormuz_exposure_pct": 56.8,
        "top_sources": ["UAE (14%)", "Singapore (19%)", "Thailand (25%)"],
        # Plastics converters typically hold 4-6 weeks of resin stock
        "stock_days": 35,
        "seasonal_demand_multiplier": 1.0,
        "substitution_rate": 0.25,  # some US/Australian resin available but limited
        "impact_lag_weeks": 4,  # fast — packaging shortages hit retail quickly
        "downstream_effects": [
            {"sector": "Food packaging", "mechanism": "Meat trays, dairy containers, produce wrap shortage",
             "gdp_exposure_pct": 0.5, "lag_weeks": 6},
            {"sector": "Construction", "mechanism": "Building wrap, pipe, insulation shortage",
             "gdp_exposure_pct": 0.3, "lag_weeks": 8},
            {"sector": "Agriculture", "mechanism": "Silage wrap, bale wrap unavailable",
             "gdp_exposure_pct": 0.4, "lag_weeks": 4},
        ],
    },
    "polypropylene": {
        "label": "Polypropylene (Industrial/Auto)",
        "hs_code": "3902",
        "annual_import_usd": 45_160_333,
        "hormuz_exposure_pct": 55.1,
        "top_sources": ["South Korea (38%)", "UAE (18%)", "Singapore (8%)"],
        "stock_days": 30,
        "seasonal_demand_multiplier": 1.0,
        "substitution_rate": 0.20,  # Korean supply hard to replace — specialised grades
        "impact_lag_weeks": 6,
        "downstream_effects": [
            {"sector": "Automotive", "mechanism": "Parts shortage, repair delays",
             "gdp_exposure_pct": 0.2, "lag_weeks": 8},
            {"sector": "Medical", "mechanism": "Syringe, container, PPE shortage",
             "gdp_exposure_pct": 0.1, "lag_weeks": 4},
        ],
    },
    "organic_chemicals": {
        "label": "Organic Chemicals (Industrial)",
        "hs_code": "29",
        "annual_import_usd": 294_875_220,
        "hormuz_exposure_pct": 10.4,
        "top_sources": ["Japan (8%)", "China (18%)", "USA (15%)"],
        "stock_days": 45,
        "seasonal_demand_multiplier": 1.0,
        "substitution_rate": 0.45,  # most diversified — Japan/China/USA alternatives
        "impact_lag_weeks": 8,
        "downstream_effects": [
            {"sector": "Pharmaceuticals", "mechanism": "API shortage for generic drugs",
             "gdp_exposure_pct": 0.2, "lag_weeks": 8},
            {"sector": "Agriculture", "mechanism": "Pesticide/herbicide precursor shortage",
             "gdp_exposure_pct": 0.3, "lag_weeks": 12},
        ],
    },
    "palm_kernel": {
        "label": "Palm Kernel Expeller (Dairy Feed)",
        "hs_code": "2306",
        "annual_import_usd": 350_000_000,  # ~2Mt at ~$175/t
        # Direct Hormuz exposure is ~5%, but the REAL risk is Indonesian
        # export ban triggered by global food/energy crisis. Indonesia
        # banned palm oil exports Apr-Jun 2022 (5 months). In a deeper
        # crisis, probability is ~60-70%. If banned, ~85% of NZ supply lost.
        # Expected exposure = P(ban) × magnitude ≈ 0.65 × 0.85 ≈ 55%.
        # We model this as equivalent exposure since the stress multiplier
        # then compounds it further.
        "hormuz_exposure_pct": 55.0,  # crisis-triggered export ban risk
        "top_sources": ["Indonesia (85%)", "Malaysia (12%)"],
        # NZ is the WORLD'S LARGEST importer of palm kernel for cattle feed
        # Dairy NZ estimates 2Mt/year, ~30% of supplementary feed
        "stock_days": 21,  # feed mills hold 2-3 weeks
        "seasonal_demand_multiplier": 1.1,  # autumn calving season
        # Substitution is very limited: no domestic alternative at this scale
        # Soy meal (US/Brazil) or DDGs could partially substitute but
        # NZ dairy systems are built around PKE
        "substitution_rate": 0.15,
        "impact_lag_weeks": 2,  # feed shortage hits milk production fast
        # CRITICAL: Risk is NOT Hormuz dependency but Indonesian EXPORT BAN.
        # Indonesia banned palm oil exports in 2022 (Apr-Jun).
        # In a global food/energy crisis, Indonesia is highly likely to
        # restrict palm product exports to protect domestic supply.
        # We model this via the global_stress_multiplier + high sensitivity.
        "downstream_effects": [
            {"sector": "Dairy", "mechanism": "Cattle feed shortage → milk production drops 10-20%",
             "gdp_exposure_pct": 4.0, "lag_weeks": 4},
            {"sector": "Dairy exports", "mechanism": "WMP/SMP volume reduction → export revenue loss",
             "gdp_exposure_pct": 2.5, "lag_weeks": 8},
        ],
    },
    "refined_petroleum": {
        "label": "Refined Petroleum",
        "hs_code": "2710",
        "annual_import_usd": 6_084_940_191,
        "hormuz_exposure_pct": 61.5,
        "top_sources": ["South Korea (54%)", "Singapore (31%)", "Japan (5%)"],
        "stock_days": 20,  # current projected onshore (from fuel security model)
        "seasonal_demand_multiplier": 1.0,
        "substitution_rate": 0.15,  # very limited — refinery capacity is the bottleneck
        "impact_lag_weeks": 0,  # immediate
        "downstream_effects": [
            {"sector": "Transport", "mechanism": "Freight, aviation, commuter disruption",
             "gdp_exposure_pct": 5.0, "lag_weeks": 2},
            {"sector": "Agriculture", "mechanism": "Diesel for machinery, harvesting",
             "gdp_exposure_pct": 3.5, "lag_weeks": 4},
        ],
    },
}

# Refiner re-sourcing curve (same as scenarios.py)
REFINER_OUTPUT_LOSS = [
    (0.55, 0), (0.40, 4), (0.30, 8), (0.25, 16), (0.20, 52),
]

# ---------------------------------------------------------------------------
# Global stress multiplier
# ---------------------------------------------------------------------------
# Models indirect/second-order effects that compound with direct Hormuz exposure:
#
# 1. Refinery competition: 20M bbl/day Gulf crude offline → all refineries
#    bid for same non-Gulf supply → small buyers (NZ) get squeezed out.
#    NZ buys ~150k bbl/day — a rounding error vs China/Japan/India.
#
# 2. European ammonia shutdown: ~30% of global ammonia is European, produced
#    from natural gas. Qatar LNG offline → European gas spike → fertiliser
#    plants close (as in 2022 Russian gas crisis). NZ's "non-Hormuz"
#    fertiliser sources face competition from European buyers.
#
# 3. Shipping capacity crunch: Cape rerouting adds ~15% to global tanker-days.
#    Fewer ships for ALL routes including NZ's non-Hormuz trade. Freight
#    rates spike across the board.
#
# 4. Export bans: Food-exporting countries restrict exports when prices spike
#    (India wheat 2022, Indonesia palm oil 2022). Reduces NZ's alternative
#    sourcing options.
#
# 5. Financial contagion: Oil-importing EMs (Egypt, Pakistan, Bangladesh)
#    face sovereign stress → trade finance dries up → physical trade stops.
#
# 6. Insurance market: War risk premiums spread beyond Gulf, increasing
#    shipping costs globally.
#
# Shape: sigmoid — slow start (buffers absorb), rapid acceleration
# (substitution plans collide), saturation (new degraded equilibrium).
# Multiplier applies to effective_loss, compounding the direct supply gap.
#
# Format: (multiplier, week) — 1.0 = no indirect effect

# Calibrated against research: 1.25-1.45x at week ~5 (confirmed by SK export caps,
# SCFI +28%, Yara at 35% capacity, P&I Gulf coverage cancelled).
GLOBAL_STRESS_MULTIPLIER = [
    (1.0,  0),    # Week 0: buffers absorb
    (1.10, 2),    # Week 2: SK export caps enacted, shipping costs +15%
    (1.25, 4),    # Week 4: EU gas spike, refinery competition, freight +28%
    (1.45, 8),    # Week 8: EU fertiliser shutting, export bans starting, insurance seized
    (1.65, 12),   # Week 12: substitution plans colliding globally, freight 2x+
    (1.85, 16),   # Week 16: EM financial contagion, trade finance contracting
    (2.00, 20),   # Week 20: alternatives largely exhausted for small buyers
    (2.15, 26),   # Week 26: structural degradation
    (2.25, 36),   # Week 36: new degraded equilibrium
    (2.25, 52),   # Week 52: saturated
]

# Per-commodity sensitivity to global stress
# Some commodities are more affected by indirect channels than others
COMMODITY_STRESS_SENSITIVITY = {
    "fertiliser_nitrogen": 1.3,   # High: European ammonia shutdown directly reduces global supply
    "fertiliser_mixed": 1.1,      # Moderate: more diversified, less gas-dependent
    "polyethylene": 1.2,          # High: petrochemical feedstock competition
    "polypropylene": 1.2,         # High: same feedstock competition
    "organic_chemicals": 1.0,     # Low: diversified sources, lower Hormuz exposure
    "palm_kernel": 2.0,           # EXTREME: risk is Indonesian export ban, not Hormuz transit.
                                  # Indonesia banned palm oil exports in 2022 (5 months duration).
                                  # In a global food/energy crisis, export ban probability is very high.
                                  # High stress sensitivity models this as a quasi-certain event.
    "refined_petroleum": 1.4,     # Highest non-ban: most fungible, most competed-for globally
}


def _interpolate(waypoints, week):
    """Linearly interpolate from (value, week) waypoints."""
    for i in range(len(waypoints) - 1):
        val_a, week_a = waypoints[i]
        val_b, week_b = waypoints[i + 1]
        if week_a <= week <= week_b:
            if week_b == week_a:
                return val_a
            t = (week - week_a) / (week_b - week_a)
            return val_a + t * (val_b - val_a)
    return waypoints[-1][0]


@dataclass
class CommodityProjection:
    """Projection for a single commodity under current disruption."""
    key: str
    label: str
    hormuz_exposure_pct: float
    annual_import_usd: float
    stock_days_initial: float
    stock_weeks: list           # week-by-week stock levels
    depletion_date: str         # when stock hits critical (10% of initial)
    exhaustion_date: str        # when stock hits 0
    downstream_impacts: list    # sector impacts with onset dates


def project_commodity(key: str, profile: dict, hormuz_frac: float,
                      war_start: date, today: date,
                      horizon_weeks: int = 52) -> CommodityProjection:
    """
    Project a commodity's stock depletion under current Hormuz disruption,
    including indirect global stress effects.
    """
    stock = profile["stock_days"]
    exposure = profile["hormuz_exposure_pct"] / 100
    seasonal = profile["seasonal_demand_multiplier"]
    substitution = profile["substitution_rate"]
    stress_sensitivity = COMMODITY_STRESS_SENSITIVITY.get(key, 1.0)

    weeks_since_war = (today - war_start).days / 7
    stock_weeks = []

    current_stock = stock
    depletion_date = None
    exhaustion_date = None

    for week in range(horizon_weeks + 1):
        absolute_week = weeks_since_war + week
        refiner_loss = _interpolate(REFINER_OUTPUT_LOSS, absolute_week)

        # Direct supply loss from Hormuz closure
        direct_loss = hormuz_frac * exposure * refiner_loss

        # Substitution partially offsets direct loss — fraction of LOST supply
        # replaceable from non-Hormuz sources. Ramps up over 12 weeks.
        sub_fraction = substitution * min(1.0, absolute_week / 12)
        net_direct_loss = direct_loss * (1.0 - sub_fraction)

        # Global stress multiplier: indirect effects that compound with time.
        # The stress multiplier degrades the substitution effectiveness —
        # the "alternatives" NZ is counting on are simultaneously under
        # pressure from global competition, export bans, shipping crunch, etc.
        global_stress = _interpolate(GLOBAL_STRESS_MULTIPLIER, absolute_week)

        # Apply stress with commodity-specific sensitivity
        # The multiplier amplifies the net loss, representing that alternatives
        # are harder to secure than the base model assumes
        effective_stress = 1.0 + (global_stress - 1.0) * stress_sensitivity
        net_loss = min(1.0, net_direct_loss * effective_stress)  # cap at 100% loss

        # Apply seasonal demand multiplier
        effective_loss = net_loss * seasonal

        if week > 0:
            current_stock = max(0, current_stock - effective_loss * 7)

        stock_weeks.append({
            "week": week,
            "stock_days": round(current_stock, 1),
            "direct_loss_rate": round(net_direct_loss, 4),
            "global_stress": round(effective_stress, 2),
            "effective_loss_rate": round(net_loss, 4),
        })

        # Critical threshold: 10% of initial stock
        if depletion_date is None and current_stock < stock * 0.10:
            depletion_date = (today + timedelta(weeks=week)).isoformat()

        if exhaustion_date is None and current_stock <= 0:
            exhaustion_date = (today + timedelta(weeks=week)).isoformat()

    # Calculate downstream impact onset dates
    downstream = []
    trigger_date = depletion_date or exhaustion_date
    for effect in profile.get("downstream_effects", []):
        onset = None
        if trigger_date:
            trigger = date.fromisoformat(trigger_date)
            onset = (trigger + timedelta(weeks=effect["lag_weeks"])).isoformat()

        downstream.append({
            "sector": effect["sector"],
            "mechanism": effect["mechanism"],
            "gdp_exposure_pct": effect["gdp_exposure_pct"],
            "lag_weeks": effect["lag_weeks"],
            "onset_date": onset,
        })

    return CommodityProjection(
        key=key,
        label=profile["label"],
        hormuz_exposure_pct=profile["hormuz_exposure_pct"],
        annual_import_usd=profile["annual_import_usd"],
        stock_days_initial=stock,
        stock_weeks=stock_weeks,
        depletion_date=depletion_date,
        exhaustion_date=exhaustion_date,
        downstream_impacts=downstream,
    )


def run_commodity_exposure(hormuz_frac: float, war_start: date = None,
                           today: date = None,
                           horizon_weeks: int = 52) -> dict:
    """
    Run exposure model for all tracked commodities.

    Returns dict ready for JSON export.
    """
    if war_start is None:
        war_start = date(2026, 2, 28)
    if today is None:
        today = date.today()

    commodities = {}
    all_downstream = []
    total_exposed_usd = 0

    for key, profile in COMMODITY_PROFILES.items():
        proj = project_commodity(key, profile, hormuz_frac, war_start, today, horizon_weeks)

        total_exposed_usd += profile["annual_import_usd"] * profile["hormuz_exposure_pct"] / 100

        commodities[key] = {
            "label": proj.label,
            "hs_code": profile["hs_code"],
            "hormuz_exposure_pct": proj.hormuz_exposure_pct,
            "annual_import_usd": proj.annual_import_usd,
            "top_sources": profile["top_sources"],
            "stock_days_initial": proj.stock_days_initial,
            "current_stock_days": proj.stock_weeks[0]["stock_days"],
            "depletion_date": proj.depletion_date,
            "exhaustion_date": proj.exhaustion_date,
            "stock_series": proj.stock_weeks,
            "downstream_impacts": proj.downstream_impacts,
        }

        for impact in proj.downstream_impacts:
            if impact["onset_date"]:
                all_downstream.append({
                    "commodity": proj.label,
                    "sector": impact["sector"],
                    "mechanism": impact["mechanism"],
                    "gdp_exposure_pct": impact["gdp_exposure_pct"],
                    "onset_date": impact["onset_date"],
                })

    # Sort downstream by onset date
    all_downstream.sort(key=lambda x: x["onset_date"])

    # Aggregate GDP exposure
    total_gdp_at_risk = sum(d["gdp_exposure_pct"] for d in all_downstream)

    # Timeline summary: what breaks when
    timeline = {}
    for d in all_downstream:
        month = d["onset_date"][:7]  # YYYY-MM
        if month not in timeline:
            timeline[month] = []
        timeline[month].append(f"{d['sector']} ({d['commodity']})")

    return {
        "generated_at": today.isoformat(),
        "hormuz_disruption_frac": round(hormuz_frac, 3),
        "total_exposed_annual_usd": round(total_exposed_usd, 0),
        "commodities": commodities,
        "cascade_timeline": all_downstream,
        "timeline_by_month": timeline,
        "total_gdp_at_risk_pct": round(total_gdp_at_risk, 1),
    }
