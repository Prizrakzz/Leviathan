"""SILVER-F082: the DAG catalog -- the orchestration-family grouping of the silver estate.

The observability layer (per-family Batch-failure alarms) and the incident-runbook completeness
lint both need ONE deterministic answer to "which orchestration family does table T belong to?".
The plan's Attacker-2 framing is an EventBridge+Step-Functions (or MWAA) estate of ~7-ish source
DAGs; a *family* here is one such orchestration unit: the set of silver/gold tables a single source
pipeline produces and that a single DAG would schedule/backfill together (e.g. the weather DAG owns
nasa_power + chirps + cpc_soil + modis + the gold_weather_z consumer; the USDA-ESR DAG owns
silver_esr + its silver_esr_compact serving copy).

This module derives the catalog **from the SILVER-F010 registry**, so it can never drift from the
canonical table set: every registry table maps to exactly one family via an explicit, ordered
table-name rule table (:data:`FAMILY_RULES`), and :func:`build_catalog` raises if any table fails to
map (a new table forces an explicit family decision -- completeness is enforced, not assumed).

Pure + AWS-free + deterministic. ``silver_model_predictions`` is grouped into the ``model_output``
family but flagged ``backfillable=False`` (generation-only; it has no source-backfill DAG and is out
of the R4 backfill boundary), so consumers can include or exclude it explicitly rather than by
guessing from the name.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from leviathan.silver.registry import SilverRegistry, load_registry

__all__ = [
    "FAMILY_RULES",
    "FAMILY_LABELS",
    "CADENCE_DEFAULT_LAG_DAYS",
    "FRESHNESS_LAG_OVERRIDES",
    "DagFamily",
    "family_of",
    "build_catalog",
    "effective_sla_lag_days",
]

# ---------------------------------------------------------------------------
# The family rule table. ORDERED: the first prefix that matches a table name
# wins, so the more specific multi-token prefixes (silver_wap_table01) precede
# the shorter ones. Keyed on the stable ``table_name`` (registry identity), NOT
# on a mutable producer path. gold_weather_z is the one non-``silver_`` name.
# ---------------------------------------------------------------------------
FAMILY_RULES: tuple[tuple[str, str], ...] = (
    # --- USDA source DAGs -------------------------------------------------
    ("silver_esr_compact", "usda_esr"),
    ("silver_esr", "usda_esr"),
    ("silver_wasde", "usda_wasde"),
    ("silver_psd", "usda_psd"),
    ("silver_wap_table01", "usda_wap"),          # + _revisions
    ("silver_nass_", "usda_nass"),               # nass_annual / nass_crop_progress / nass_citrus
    ("silver_fgis", "usda_fgis"),
    # --- Weather / climate ------------------------------------------------
    ("silver_nasa_power", "weather"),
    ("silver_chirps", "weather"),
    ("silver_cpc_soil", "weather"),
    ("silver_modis_ndvi", "weather"),
    ("gold_weather_z", "weather"),               # the gold weather serving consumer
    ("silver_noaa_", "noaa_climate"),            # noaa_iod / noaa_oni
    # --- Palm-oil complex (Malaysia) -------------------------------------
    ("silver_mpoc_", "mpoc"),
    ("silver_mpob", "mpob"),                     # mpob / mpob_annual
    # --- Brazil / Colombia / South Africa ---------------------------------
    ("silver_unica_", "unica"),
    ("silver_conab_coffee", "conab"),
    ("silver_fnc_colombia_", "fnc_colombia"),
    ("silver_sagis_", "sagis"),
    # --- Macro / prices / positioning -------------------------------------
    ("silver_fred_fx", "fred"),
    ("silver_food_cpi", "world_bank"),
    ("silver_pink_sheet", "world_bank"),
    ("silver_futures_prices", "futures"),
    # PRICE_AND_PLAYBOOKS W1.0: the per-delivery-month EOD table gets its OWN family, not the yfinance
    # `futures` one. Its producers are a different estate (CZCE / JSE / CEPEA / Bursa / MIAX / Euronext /
    # DCE / Databento, on their own venue-timezone crons), and W3 retires the yfinance chain -- so a
    # shared family would page the wrong on-call and make the `futures` label ("...(yfinance)") a lie.
    # NOTE the ordering hazard: never write this rule as ("silver_futures", ...) -- that prefix swallows
    # BOTH tables (family_of matches on startswith) and would silently re-home the live yfinance table.
    ("silver_futures_eod", "futures_eod"),
    ("silver_cot", "cftc"),
    # --- Single-source specialty ------------------------------------------
    ("silver_production", "faostat"),
    ("silver_ams_cotton_quality", "ams"),
    ("silver_icco_cocoa", "icco"),
    # --- Model output (generation-only; NOT a source-backfill DAG) --------
    ("silver_model_predictions", "model_output"),
    # --- Observability ledger (T2B; generation-only engine replay) --------
    # gold_pattern_records is produced by the pattern-records sweep (an engine replay over the mapped
    # catalog), NOT ingested from an external source -- so it has no source-backfill DAG and carries no
    # F082 batch/freshness alarm (its own missed-sweep / zero-rows alarms are the T2B plan sec 8 set,
    # separate from this estate). Grouped like model_output: generation-only.
    ("gold_pattern_records", "pattern_records"),
)

# Human-facing family labels for runbook/alarm descriptions.
FAMILY_LABELS: dict[str, str] = {
    "usda_esr": "USDA FAS Export Sales (ESR)",
    "usda_wasde": "USDA WASDE",
    "usda_psd": "USDA PSD",
    "usda_wap": "USDA World Ag Production (WAP)",
    "usda_nass": "USDA NASS (QuickStats / crop progress / citrus)",
    "usda_fgis": "USDA FGIS grain inspections",
    "weather": "Weather + climate (NASA POWER / CHIRPS / CPC-soil / MODIS / gold z-score)",
    "noaa_climate": "NOAA climate indices (IOD / ONI)",
    "mpoc": "MPOC Malaysian palm-oil council",
    "mpob": "MPOB Malaysian palm-oil board",
    "unica": "UNICA Brazil sugar/ethanol",
    "conab": "CONAB Brazil coffee",
    "fnc_colombia": "FNC Colombia coffee",
    "sagis": "SAGIS South Africa grain",
    "fred": "FRED FX rates",
    "world_bank": "World Bank (food CPI / Pink Sheet)",
    "futures": "Exchange futures prices (yfinance)",
    "futures_eod": "Exchange futures EOD per delivery month (CZCE / JSE / CEPEA / Bursa / MIAX / "
                   "Euronext / DCE / Databento)",
    "cftc": "CFTC Commitments of Traders",
    "faostat": "FAOSTAT production",
    "ams": "USDA AMS cotton quality",
    "icco": "ICCO cocoa",
    "model_output": "Model predictions (generation-only)",
    "pattern_records": "Pattern-records ledger (T2B; generation-only engine replay)",
}

# Interim freshness-SLA lag ceilings per cadence, used when the registry
# ``freshness_sla.max_lag_days`` is still null (all tables today -- OP-8 / AV-11
# per-source calibration is deferred). A weekly source is stale past ~2 cycles,
# a daily one past ~3 days, etc. The certificate emits FreshnessLagDays and the
# F082 alarm fires when it exceeds this ceiling (plus any publication_lag grace).
CADENCE_DEFAULT_LAG_DAYS: dict[str, int] = {
    "daily": 3,
    "weekly": 14,
    "monthly": 45,
    "annual": 400,
}
# Fallback when cadence is unrecorded (6 tables). Conservative monthly-ish.
_CADENCE_FALLBACK_LAG_DAYS = 45

# Freshness-audit corrections (freshness-poller lane, 2026-07-23). A registry ``max_lag_days`` value
# that the freshness audit found MASKED a stalled producer -- the emitted family ceiling (and the
# per-table alarm in silver_alarms.BURNED_TABLE_FRESHNESS) use the corrected value instead. Keyed by
# ``table_name``; applied in :func:`build_catalog` and only ever TIGHTENS (``min`` with the registry-
# derived lag), so it is a no-op the moment the registry baseline is regenerated with the real fix.
#   silver_nass_crop_progress: cadence=weekly but the registry carried max_lag_days=170 (~24 weeks),
#   which let the weekly crop-progress producer sit stale-green for 6-10 weeks. Corrected to the
#   weekly cadence default (14) -- this is what drops the usda_nass family ceiling 170 -> 14.
FRESHNESS_LAG_OVERRIDES: dict[str, int] = {
    "silver_nass_crop_progress": 14,
}


def family_of(table_name: str) -> str:
    """The orchestration family a table belongs to. Raises ``KeyError`` if unmapped.

    First-match wins over :data:`FAMILY_RULES` (ordered specific-before-general)."""
    for prefix, family in FAMILY_RULES:
        if table_name == prefix or table_name.startswith(prefix):
            return family
    raise KeyError(
        f"{table_name!r} maps to no DAG family. Add an explicit FAMILY_RULES entry "
        f"(dag_catalog.py) -- a new silver table must declare its orchestration family."
    )


def effective_sla_lag_days(contract: dict) -> tuple[int, str]:
    """Return ``(max_lag_days, basis)`` -- the interim freshness ceiling for a table.

    Precedence: an explicit registry ``freshness_sla.max_lag_days`` (none set today) >
    the cadence default (:data:`CADENCE_DEFAULT_LAG_DAYS`) > the monthly-ish fallback. A
    ``publication_lag_days`` (e.g. ESR=7) is added as grace so the alarm never fires on the
    expected publication delay."""
    fs = contract.get("freshness_sla") or {}
    grace = int(contract.get("publication_lag_days") or 0)
    explicit = fs.get("max_lag_days")
    if explicit is not None:
        return int(explicit) + grace, "registry.max_lag_days"
    cadence = fs.get("cadence")
    if cadence in CADENCE_DEFAULT_LAG_DAYS:
        return CADENCE_DEFAULT_LAG_DAYS[cadence] + grace, f"cadence_default:{cadence}"
    return _CADENCE_FALLBACK_LAG_DAYS + grace, "cadence_default:fallback"


@dataclass(frozen=True)
class DagFamily:
    """One orchestration family: the tables a single source DAG produces/schedules together."""

    key: str
    label: str
    tables: tuple[str, ...]
    owner: str                              # dominant registry owner across the family
    cadences: tuple[str, ...]               # sorted distinct freshness cadences in the family
    batch_tasks: tuple[str, ...]            # distinct producer batch-task entrypoints
    backfillable: bool                      # False for model_output (generation-only)
    max_sla_lag_days: int = 0               # tightest interim freshness ceiling in the family
    sla_basis: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "tables": list(self.tables),
            "owner": self.owner,
            "cadences": list(self.cadences),
            "batch_tasks": list(self.batch_tasks),
            "backfillable": self.backfillable,
            "max_sla_lag_days": self.max_sla_lag_days,
            "sla_basis": self.sla_basis,
        }


# Families that carry no source-backfill DAG (generation-only outputs).
_NON_BACKFILL_FAMILIES = frozenset({"model_output", "pattern_records"})


def build_catalog(registry: Optional[SilverRegistry] = None) -> dict[str, DagFamily]:
    """Group every registry table into its DAG family. Deterministic; raises on an unmapped table.

    Returns ``{family_key: DagFamily}`` ordered by family key. Each family's ``max_sla_lag_days`` is
    the *tightest* (minimum) interim ceiling across its tables (the family is stale as soon as its
    freshest-cadence member is)."""
    reg = registry or load_registry()
    grouped: dict[str, list[dict]] = {}
    for name in reg.names():
        grouped.setdefault(family_of(name), []).append(reg.table(name))

    out: dict[str, DagFamily] = {}
    for family in sorted(grouped):
        contracts = sorted(grouped[family], key=lambda c: c["table_name"])
        tables = tuple(c["table_name"] for c in contracts)
        owners = [c.get("owner") for c in contracts if c.get("owner")]
        owner = _dominant(owners)
        cadences = tuple(sorted({
            (c.get("freshness_sla") or {}).get("cadence")
            for c in contracts
            if (c.get("freshness_sla") or {}).get("cadence")
        }))
        batch_tasks = tuple(sorted({
            (c.get("producer") or {}).get("batch_task")
            for c in contracts
            if (c.get("producer") or {}).get("batch_task")
        }))
        lags = []
        for c in contracts:
            lag, basis = effective_sla_lag_days(c)
            override = FRESHNESS_LAG_OVERRIDES.get(c["table_name"])
            if override is not None and override < lag:
                lag, basis = override, f"audit_override(was {lag},{basis})"
            lags.append((lag, basis))
        tightest = min(lags, key=lambda t: t[0]) if lags else (_CADENCE_FALLBACK_LAG_DAYS, "none")
        out[family] = DagFamily(
            key=family,
            label=FAMILY_LABELS.get(family, family),
            tables=tables,
            owner=owner,
            cadences=cadences,
            batch_tasks=batch_tasks,
            backfillable=family not in _NON_BACKFILL_FAMILIES,
            max_sla_lag_days=tightest[0],
            sla_basis=tightest[1],
        )
    return out


def _dominant(values: list[str]) -> str:
    """Most frequent value (ties broken alphabetically); '' for an empty list."""
    if not values:
        return ""
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts, key=lambda k: (-counts[k], k))[0]
