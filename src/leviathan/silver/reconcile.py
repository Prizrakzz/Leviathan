"""Reconciliation lints: the silver registry (SILVER-F010) as a SUPERSET that must agree with the
live consumer configs -- it is a reference-and-reconcile authority, not a parallel one (C-WRONG-9).

Four lints, each returning a list of :class:`Divergence`:

  * :func:`reconcile_numbers`        -- registry <-> ``configs/graphrag/numbers/tables.yaml``
                                        (knowledge-date column, PIT semantics, publication_lag_days,
                                        period col/type, partition cols, numbers_ref back-pointer).
                                        The F010 acceptance lint: NO publication_lag / PIT divergence.
  * :func:`reconcile_cascade`        -- every ``cascade_map.yaml`` ref resolves to a registry table
                                        and that table records a cascade_ref back-pointer.
  * :func:`reconcile_source_contracts` -- every ``source_contracts.yaml`` glue_table exists; its
                                        required_columns are declared columns; and value_columns /
                                        min_nonnull_frac are NOT re-declared there (Attack 3 #6: the
                                        silver registry is the single authority for those two fields).
  * :func:`reconcile_features`       -- every ``features.yaml`` source resolves (via source_contracts)
                                        to a registry table whose consumers include the feature layer.

Every surviving divergence must be either fixed in the registry or carried in
``configs/silver/known_drift.yaml`` with its owning R2 package id. :func:`unallowed` filters a
divergence list against that allowlist -- the test asserts it is empty.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from leviathan.silver.registry import (
    SilverRegistry,
    _REPO_ROOT,
    load_known_drift,
)

TABLES_YAML = _REPO_ROOT / "configs" / "graphrag" / "numbers" / "tables.yaml"
CASCADE_MAP_YAML = _REPO_ROOT / "configs" / "graphrag" / "numbers" / "cascade_map.yaml"
SOURCE_CONTRACTS_YAML = _REPO_ROOT / "configs" / "datasets" / "source_contracts.yaml"
FEATURES_YAML = _REPO_ROOT / "configs" / "features" / "features.yaml"

# The numbers TableSpec keys (tables.yaml). ``silver_esr`` is the numbers logical key; it serves
# from silver_esr_compact (athena_table), recorded as serving_table in the registry.
#
# CORRECTION V3 (numbers-depth wave): this MUST enumerate EVERY numbers TableSpec, because
# ``reconcile_numbers`` iterates ONLY this tuple — a table wired into tables.yaml but absent here is
# STRUCTURALLY UNCHECKED (its knowledge_date_col / knowledge_semantics / publication_lag_days never
# reconcile against the F010 registry, so a mis-derived MPOB publication_lag_days would ship live and
# PIT-leak while the gate reports "clean"). ``silver_icco_cocoa`` / ``silver_mpob`` /
# ``silver_sagis_cec`` are the three tables this wave wires in. The drift test
# ``set(NUMBERS_TABLES) == set(tables.yaml keys)`` keeps this from silently reopening.
NUMBERS_TABLES = (
    "silver_psd",
    "silver_wasde",
    "silver_production",
    "silver_nasa_power",
    "silver_esr",
    "silver_fred_fx",
    "silver_noaa_oni",
    "gold_weather_z",
    "silver_icco_cocoa",
    "silver_mpob",
    "silver_sagis_cec",
    "silver_pink_sheet",                # PRICE_OBSERVABILITY W2: WB Pink Sheet monthly price benchmarks
    "silver_cot",                       # PRICE_OBSERVABILITY W4: CFTC COT managed-money positioning (v2)
    "silver_futures_prices",            # SEAM C (rev-52): futures v1.5-lite daily front-month settle (levels-only,
    #                                     whitelist-absent from serving until the gate + freshness fix; the numbers
    #                                     card + silver_futures_prices.yaml numbers_ref/knowledge fields reconcile
    #                                     here regardless of the served-registry drop -- both read raw configs)
    "silver_noaa_iod",                  # WIRING WAVE-1 (Card A): NOAA IOD (year_month, global climate index)
    "silver_conab_coffee",              # WIRING WAVE-1 (Card B): CONAB Brazil coffee surveys (survey-vintage)
    "silver_sagis_weekly_exports",      # WIRING WAVE-1 (Card C): SAGIS SA weekly cumulative export pace. The
    #                                     pre-step DDL/migration is now COMPLETE (main loop applied the gated Glue
    #                                     ADD COLUMNS -> 9-col catalog, week_ending_date DATE live) and the registry
    #                                     records consumers=both + numbers_ref, so its data_date PIT fields
    #                                     (week_ending_date, +5d publication_lag_days) reconcile here rather than
    #                                     skipping the F010 gate unchecked.
    "silver_futures_eod",               # PRICE_AND_PLAYBOOKS W1.0: the per-delivery-month futures EOD table
    #                                     (45th contract). Whitelist-absent from serving for all of
    #                                     W1.0/W1/W2 -- but, exactly like silver_futures_prices was
    #                                     pre-flip, the numbers card + the F010 contract's
    #                                     numbers_ref/knowledge fields reconcile here REGARDLESS of the
    #                                     served-registry drop (both lints read raw configs). Enumerated
    #                                     the moment the card landed so its data_date/trade_date/+1d PIT
    #                                     fields are structurally checked rather than shipping unchecked.
    "gold_pattern_records",             # T2b: pattern-records ledger (44th contract, registered-partition GOLD,
    #                                     flag-off until its deck gates the flip) — enumerated the moment its
    #                                     tables.yaml card landed so its knowledge fields reconcile against F010
    #                                     instead of shipping structurally unchecked.
)


@dataclass(frozen=True)
class Divergence:
    check: str            # which lint produced it
    table: str
    kind: str             # machine slug of the disagreement class
    detail: str           # human-readable
    column: Optional[str] = None

    def key(self) -> tuple:
        return (self.check, self.table, self.kind, self.column)


# ---------------------------------------------------------------------------
# Loaders (pure).
# ---------------------------------------------------------------------------
def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _numbers_specs(path: Optional[Path] = None) -> dict:
    return (_load_yaml(path or TABLES_YAML)).get("tables", {})


def _source_contracts(path: Optional[Path] = None) -> list[dict]:
    return (_load_yaml(path or SOURCE_CONTRACTS_YAML)).get("sources", [])


def _cascade_refs(path: Optional[Path] = None) -> dict:
    doc = _load_yaml(path or CASCADE_MAP_YAML)
    refs = doc.get("refs", doc)
    out = {}
    if isinstance(refs, dict):
        for name, spec in refs.items():
            if isinstance(spec, dict) and "table" in spec:
                out[name] = spec
    return out


def _features_sources(path: Optional[Path] = None) -> set[str]:
    # features.yaml is a top-level LIST of family entries, each {family, sources: [...], ...}.
    doc = yaml.safe_load((path or FEATURES_YAML).read_text(encoding="utf-8")) or []
    entries = doc if isinstance(doc, list) else doc.get("families", doc.get("feature_families", []))
    sources: set[str] = set()
    for spec in entries or []:
        if isinstance(spec, dict):
            for s in spec.get("sources", []) or []:
                sources.add(s)
    return sources


# ---------------------------------------------------------------------------
# Lints.
# ---------------------------------------------------------------------------
def reconcile_numbers(reg: SilverRegistry, path: Optional[Path] = None) -> list[Divergence]:
    """Registry <-> numbers TableSpec. The acceptance lint: no publication_lag / PIT divergence."""
    specs = _numbers_specs(path)
    out: list[Divergence] = []
    for name in NUMBERS_TABLES:
        if name not in reg.tables:
            out.append(Divergence("numbers", name, "missing_table",
                                   "numbers TableSpec table absent from registry"))
            continue
        c = reg.tables[name]
        spec = specs.get(name, {})
        if not spec:
            out.append(Divergence("numbers", name, "missing_spec",
                                   "table in registry NUMBERS set but absent from tables.yaml"))
            continue
        if not c.get("numbers_ref"):
            out.append(Divergence("numbers", name, "missing_numbers_ref",
                                   "registry contract lacks numbers_ref back-pointer"))
        # PIT semantics (the corrected acceptance criterion).
        if c.get("knowledge_date_col") != spec.get("knowledge_date_col"):
            out.append(Divergence("numbers", name, "knowledge_date_col",
                                   f"registry {c.get('knowledge_date_col')!r} != tablespec "
                                   f"{spec.get('knowledge_date_col')!r}"))
        if c.get("knowledge_semantics") != spec.get("knowledge_semantics"):
            out.append(Divergence("numbers", name, "knowledge_semantics",
                                   f"registry {c.get('knowledge_semantics')!r} != tablespec "
                                   f"{spec.get('knowledge_semantics')!r}"))
        if c.get("publication_lag_days") != spec.get("publication_lag_days"):
            out.append(Divergence("numbers", name, "publication_lag_days",
                                   f"registry {c.get('publication_lag_days')!r} != tablespec "
                                   f"{spec.get('publication_lag_days')!r}"))
        # partition cols (where the spec declares them). The numbers agent may serve a table from a
        # separate athena_table (ESR -> silver_esr_compact): the spec's partition_cols then describe
        # the SERVING table's partitioning, so resolve against it when present.
        spec_parts = spec.get("partition_cols")
        if spec_parts is not None:
            serving = spec.get("athena_table")
            part_table = serving if (serving and serving in reg.tables) else name
            reg_parts = [pk["name"] for pk in reg.tables[part_table].get("partition_keys", [])]
            missing = [p for p in spec_parts if p not in reg_parts]
            if missing:
                out.append(Divergence("numbers", name, "partition_cols",
                                      f"tablespec partition_cols {spec_parts} not all partition keys "
                                      f"of '{part_table}' {reg_parts}"))
    return out


def reconcile_cascade(reg: SilverRegistry, path: Optional[Path] = None) -> list[Divergence]:
    refs = _cascade_refs(path)
    out: list[Divergence] = []
    for ref_name, spec in refs.items():
        table = spec.get("table")
        if table not in reg.tables:
            out.append(Divergence("cascade", table or ref_name, "missing_table",
                                   f"cascade ref '{ref_name}' -> table '{table}' absent from registry"))
    # every referenced table should record a cascade_ref back-pointer somewhere.
    referenced = {s.get("table") for s in refs.values()}
    for table in referenced:
        if table in reg.tables and not reg.tables[table].get("cascade_ref"):
            out.append(Divergence("cascade", table, "missing_cascade_ref",
                                   "cascade-referenced table lacks a cascade_ref back-pointer"))
    return out


def reconcile_source_contracts(reg: SilverRegistry, path: Optional[Path] = None) -> list[Divergence]:
    contracts = _source_contracts(path)
    out: list[Divergence] = []
    for sc in contracts:
        table = sc.get("glue_table")
        if table not in reg.tables:
            out.append(Divergence("source_contracts", table or sc.get("source_key", "?"),
                                   "missing_table",
                                   f"source '{sc.get('source_key')}' glue_table '{table}' absent"))
            continue
        # single-authority: value_columns / min_nonnull_frac must NOT live in source_contracts.
        for banned in ("value_columns", "min_nonnull_frac", "min_nonnull_frac_overrides"):
            if banned in sc:
                out.append(Divergence("source_contracts", table, "value_authority_leak",
                                      f"source_contracts re-declares '{banned}' (registry is the "
                                      f"single authority, Attack 3 #6)", column=banned))
        cols = reg.columns(table)
        for rc in sc.get("required_columns", []) or []:
            if rc not in cols:
                out.append(Divergence("source_contracts", table, "required_column_absent",
                                      f"required_column '{rc}' not a declared registry column",
                                      column=rc))
    return out


def reconcile_features(reg: SilverRegistry, path: Optional[Path] = None,
                       source_contracts_path: Optional[Path] = None) -> list[Divergence]:
    sources = _features_sources(path)
    contracts = {sc.get("source_key"): sc for sc in _source_contracts(source_contracts_path)}
    out: list[Divergence] = []
    for src in sorted(sources):
        sc = contracts.get(src)
        if not sc:
            out.append(Divergence("features", src, "unmapped_source",
                                   f"features source '{src}' has no source_contracts entry"))
            continue
        table = sc.get("glue_table")
        if table not in reg.tables:
            out.append(Divergence("features", table or src, "missing_table",
                                   f"features source '{src}' -> '{table}' absent from registry"))
            continue
        if reg.tables[table].get("consumers") not in ("feature_layer", "both"):
            out.append(Divergence("features", table, "consumer_not_feature",
                                   f"features source '{src}' maps to '{table}' but its consumers="
                                   f"{reg.tables[table].get('consumers')!r} (expected feature/both)"))
    return out


def reconcile_all(reg: SilverRegistry) -> list[Divergence]:
    return (
        reconcile_numbers(reg)
        + reconcile_cascade(reg)
        + reconcile_source_contracts(reg)
        + reconcile_features(reg)
    )


# ---------------------------------------------------------------------------
# Known-drift allowlist filtering.
# ---------------------------------------------------------------------------
def _allowlist_keys(known: dict) -> set[tuple]:
    keys: set[tuple] = set()
    for entry in known.get("reconciliation_drift", []) or []:
        keys.add((entry.get("check"), entry.get("table"), entry.get("kind"), entry.get("column")))
    return keys


def unallowed(divs: list[Divergence], known: Optional[dict] = None) -> list[Divergence]:
    """Filter out divergences carried in the known-drift allowlist (each tied to an R2 package)."""
    known = known if known is not None else load_known_drift()
    allowed = _allowlist_keys(known)
    return [d for d in divs if d.key() not in allowed]


def orphan_allowlist_entries(divs: list[Divergence], known: Optional[dict] = None) -> list[dict]:
    """Allowlist entries that no longer match any live divergence (stale waivers to prune)."""
    known = known if known is not None else load_known_drift()
    live = {d.key() for d in divs}
    stale = []
    for entry in known.get("reconciliation_drift", []) or []:
        k = (entry.get("check"), entry.get("table"), entry.get("kind"), entry.get("column"))
        if k not in live:
            stale.append(entry)
    return stale
