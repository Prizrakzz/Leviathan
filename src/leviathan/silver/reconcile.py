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
    "silver_nass_crop_progress",        # D-CW-2a (DARK CAPABILITY CENSUS item 6): the weekly NASS crop
    #                                     condition / pace card. Enumerated in the SAME change that adds the
    #                                     tables.yaml card -- the drift test below is what forces that, and
    #                                     it is exactly the point: this table's PIT fields were all null in
    #                                     the registry until the card gave them a meaning (data_date on the
    #                                     week-ending date, +2d publication lag), and an unenumerated table
    #                                     would let that pair drift apart unchecked.
    "silver_mpoc_stock_comparison",     # D-PQ tranche 1a (2026-08-07): MPOC importer-country vegetable-oil
    #                                     ending stocks. Enumerated in the SAME change that adds the tables.yaml
    #                                     card, for the reason the NASS entry below states and which applies
    #                                     with full force here: all three knowledge fields were NULL in the F010
    #                                     contract until this card gave them a meaning (year_month on year+month,
    #                                     no publication lag because the year_month guard branch never applies
    #                                     one). An unenumerated table would let that trio drift apart unchecked.
    "silver_fgis",                      # D-LD (2026-08-18): USDA FGIS export inspections. Enumerated in
    #                                     the SAME change that adds the tables.yaml card -- all three
    #                                     knowledge fields were NULL in the F010 contract until this card
    #                                     gave them a meaning (data_date on the derived week-ending bucket,
    #                                     +13d publication lag MEASURED off three Thursday snapshots), and
    #                                     an unenumerated table would let that trio drift apart unchecked.
    #                                     The drift test set(NUMBERS_TABLES)==set(tables.yaml keys) at
    #                                     tests/unit/silver/test_silver_reconcile.py:30-38 is what forces
    #                                     the two edits to land together.
    "silver_wap_table01_revisions",     # D-LD (2026-08-18): the USDA FAS WAP Table 01 revision ledger.
    #                                     Enumerated in the SAME change that adds the tables.yaml card --
    #                                     the drift test set(NUMBERS_TABLES)==set(tables.yaml keys) forces
    #                                     that, and it matters here more than usual: the F010 contract
    #                                     carried knowledge_semantics `year_month` on a table with NO
    #                                     year/month column (build_sql would RAISE on every read), so this
    #                                     card REWRITES the trio to vintage/release_month/+12d. An
    #                                     unenumerated table would let that rewrite drift from the card
    #                                     unchecked, which is the exact class this tuple exists to catch.
    "silver_fnc_colombia_monthly",      # D-LD Track 1 (2026-08-18): FNC Colombia monthly coffee. Enumerated
    #                                     in the SAME change that adds the tables.yaml card -- the drift test
    #                                     set(NUMBERS_TABLES) == set(tables.yaml keys) is what forces that, and
    #                                     it is the point: all three knowledge fields were NULL in the F010
    #                                     contract until this card gave them a meaning (data_date on the
    #                                     first-of-month `date`, +45d publication lag), and an unenumerated
    #                                     table would let that trio drift apart STRUCTURALLY UNCHECKED.
    "silver_fnc_colombia_exports_port_type",  # D-LD (2026-08-18): FNC Colombia green-coffee exports by
    #                                     PORT. Enumerated in the SAME change that adds the tables.yaml
    #                                     card -- all three knowledge fields were NULL in the F010
    #                                     contract until this card gave them a meaning (data_date on the
    #                                     first-of-month `date`, +45d publication lag), and an
    #                                     unenumerated table would let that trio drift apart unchecked.
    #                                     partition_cols [commodity, year] are both PROJECTED Glue
    #                                     partition keys, so the partition_cols lint passes.
    "silver_nass_citrus",               # D-LD (2026-08-18): the USDA NASS citrus forecast card, the
    #                                     numbers home of frozen_orange_juice. Enumerated in the SAME
    #                                     change that adds the tables.yaml card. Unlike the two entries
    #                                     above, this contract already CARRIED its PIT trio (release_date
    #                                     / vintage / 0) before the card -- which is exactly why it must
    #                                     be enumerated: an already-populated trio is the one that drifts
    #                                     silently, because nothing about the card's arrival looks like a
    #                                     new field being minted.
    "silver_mpoc_trade_stats_monthly",  # D-LD (2026-08-18): MPOC Malaysian monthly palm EXPORT tonnage,
    #                                     the pre-2017 depth silver_mpob cannot reach. Enumerated in the
    #                                     SAME change that adds the tables.yaml card, and for the reason
    #                                     the two entries above give: all three knowledge fields were NULL
    #                                     in the F010 contract until this card gave them a meaning
    #                                     (year_month on year+month, no publication lag because the
    #                                     year_month guard branch never applies one). An unenumerated
    #                                     table is STRUCTURALLY UNCHECKED -- that trio would drift apart
    #                                     silently, and this is the table whose PIT story is the LEAKIEST
    #                                     of the year_month set (annual pages, ~12-month knowability lag),
    #                                     so the structural check matters more here, not less.
    # ── D-LD TRANCHE 2 (2026-08-18): the six no-date-column tables whose producers gained PIT anchors
    #    in this wave. Every one of them carried knowledge_date_col / knowledge_semantics /
    #    publication_lag_days ALL NULL in its F010 contract until its card gave them a meaning, and each
    #    is enumerated in the SAME change that adds the tables.yaml card -- the drift test
    #    set(NUMBERS_TABLES) == set(tables.yaml keys) (tests/unit/silver/test_silver_reconcile.py:30-38)
    #    is what forces the two edits to land together, and it is the point: an unenumerated table is
    #    STRUCTURALLY UNCHECKED, so a mis-derived lag would ship live while the gate reported clean.
    "silver_sagis_weekly_deliveries",   # the SUPPLY-side twin of silver_sagis_weekly_exports: data_date on
    #                                     the DERIVED week_ending_date, +5d (byte-identical to the sibling,
    #                                     same source and cadence).
    "silver_ams_cotton_quality",        # USDA AMS annual US cotton classing quality. vintage on the AMS-1
    #                                     DERIVED release_date (+0d) -- the conab Card B idiom, so the PIT
    #                                     trio reconciles against F010 here.
    "silver_nass_annual",               # USDA NASS settled annual crop production. vintage on the D-LD-9a
    #                                     DERIVED release_date ('<crop year+1>-02-01', +0d). partition_cols
    #                                     [commodity, year] are both PROJECTED Glue partition keys, so the
    #                                     partition_cols lint passes.
    "silver_food_cpi",                  # World Bank annual consumer-price inflation for the four food-policy
    #                                     countries. data_date on the derived year-end date, +195d MEASURED
    #                                     against the WDI release stamp. This contract ALSO carries the
    #                                     applied REPLACE COLUMNS type corrections (CURATION_OVERRIDES), so
    #                                     the trio and the catalog landed in one reconciled change.
    "silver_fnc_colombia_area_department",  # FNC Colombia annual coffee AREA by department. INGEST semantics
    #                                     on the carried-through bronze ingest_date -- publication_lag_days
    #                                     stays NULL in F010 and ABSENT on the card (byte-equal, the
    #                                     silver_production idiom); a non-revising snapshot has no lag.
    "silver_mpoc_exports_by_country",   # MPOC Malaysian palm exports by DESTINATION. data_date on the derived
    #                                     year_ending_date, +60d. The anchor column is STAGED HIDDEN in the
    #                                     contract (glue_type null) ahead of its own gated ADD COLUMNS, which
    #                                     is exactly why the trio needs a structural check now rather than
    #                                     after the catalog catches up.
    # ── D-LD TRANCHE 3 (2026-08-19): the UNICA Brazil sugar/ethanol family. UNLIKE Tranche 2, these
    #    three needed NO producer pre-step -- each already carried a usable data date, which is why
    #    the DDL regen for this tranche is a no-op and only the PIT trio moves. They still land here
    #    in the SAME change as the cards, because the drift test set(NUMBERS_TABLES) == set(tables.yaml
    #    keys) is what makes that true rather than merely intended.
    "silver_unica_biweekly_season_history",  # UNICA biweekly cane crush / sugar / ethanol, season-to-date
    #                                     cumulative by region. data_date on the fortnight POSITION date
    #                                     (a real Glue `date`, not derived), +14d for the bulletin print.
    #                                     consumers=both: it was already a feature-layer table.
    "silver_unica_corn_ethanol",        # UNICA biweekly CORN ethanol, fortnight flow + season accumulation.
    #                                     data_date on fortnight_date, +14d -- the same bulletin as the cane
    #                                     card, but the ceiling was sampled INDEPENDENTLY (both land on
    #                                     2026-02-01; that is a measured coincidence, not an inheritance).
    "silver_unica_monthly_ethanol_sales",  # UNICA monthly ethanol SALES with stored year-ago comparators.
    #                                     data_date on month_date (a Glue string, ISO 'YYYY-MM-01' in 58/58
    #                                     rows), +45d = month-end plus the following bulletin. This contract
    #                                     ALSO carries the measured per-column floors for the two export
    #                                     channels (CURATION_OVERRIDES), because carding a wide table is what
    #                                     first subjects its metrics to a non-null floor at all.
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
        #
        # WHAT THIS LINT IS ACTUALLY FOR (SILVER-F047, 2026-07-28). ``partition_cols`` in the numbers
        # TableSpec means "every query MUST carry a static equality on each of these". Its original
        # failure mode is the Jul-2026 LIST storm: a PROJECTED partition that a query does not pin
        # makes Athena enumerate the whole projected grid. So a spec partition_col that is not a
        # partition key of a PROJECTED table is a real, expensive divergence and stays a hard fail.
        #
        # A DEPROJECTED column is a different animal. BF-W1 collapsed the weather storm trio to
        # REGISTERED [commodity, year] and folded country/region/month into the parquet as ordinary
        # declared columns. The numbers card keeps emitting the same country/region equalities --
        # still correct SQL, still the right scoping discipline, and with catalog-side pruning on a
        # registered table there is no enumeration to storm. Requiring those columns to be Glue
        # PARTITION keys would force the card to declare [commodity, year] instead, and `year` is not
        # a NumberQuery field, so every weather lookup would raise "requires a static year equality".
        # Hence: a spec partition_col is legal when it is a partition key, OR when the table is
        # partition_mode=registered AND the column is a declared physical column. Anything else --
        # including any column on a projected table -- is still a divergence.
        spec_parts = spec.get("partition_cols")
        if spec_parts is not None:
            serving = spec.get("athena_table")
            part_table = serving if (serving and serving in reg.tables) else name
            part_contract = reg.tables[part_table]
            reg_parts = [pk["name"] for pk in part_contract.get("partition_keys", [])]
            deprojected: set = set()
            if str(part_contract.get("partition_mode")) == "registered":
                deprojected = {(col["name"] if isinstance(col, dict) else col)
                               for col in (part_contract.get("physical_columns") or [])}
            missing = [p for p in spec_parts if p not in reg_parts and p not in deprojected]
            if missing:
                out.append(Divergence("numbers", name, "partition_cols",
                                      f"tablespec partition_cols {spec_parts} are neither partition "
                                      f"keys nor declared columns of '{part_table}' "
                                      f"(keys {reg_parts}, offending {missing})"))
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
