"""feature_readiness (FR-001) -- the read-only 7-criterion feature-readiness harness (F1).

For each silver SOURCE family x each commodity it must serve, this job evaluates the FR-001
readiness checklist (ULTIMATE_DATA_PLAN F1) and rolls the verdicts up to the feature families that
consume the source. It is a READ-ONLY AUDIT: it attests readiness, adds/repairs NO data, and changes
no runtime path. Every failing criterion is a NAMED follow-up work order in the report, never an
in-place fix.

REUSES SHIPPED PRIMITIVES ONLY (no new src/leviathan surface):
  * crit-1 Present + crit-2 Schema-complete
        -> silver_rebuild_gate.stage_feature_probe (footer-only probe_source; the registry required
           set = value_columns | natural_key). F1 layers only the per-commodity crit-4 grouping on
           top of that verdict (F1V-06).
  * crit-3 Key-clean
        -> a BOUNDED, key-columns-only pyarrow projected read over the SAME footer-listed exact-prefix
           files (never Athena, never a recursive silver/weather/ list).
  * crit-4 Value-populated + crit-5 Vintage-adequate
        -> value_census.census_one_table (parquet FOOTER statistics; per-commodity groups driven off
           the registry partition_mode via sample_groups -- NOT a name heuristic, F1-C01).
  * crit-6 Vocabulary-consistent
        -> pg-mirror numbers tables emit PENDING-IN-VPC off-VPC (the C002 DISTINCT leg runs in-VPC as a
           separate AWS Batch job, E2b); non-mirror tables get footer-bounds INDETERMINATE. NEVER an
           Athena DISTINCT on a projection table (the Jul-2026 LIST-storm class).
  * crit-7 Coverage-declared
        -> a pure-offline lint: crop_calendars entry (calendar families) + <slug>_regions.yaml
           geography (weather families).

SAFETY (r4 folds):
  * F1-SAFE-01: the crit-6 pg leg is IN-VPC ONLY; the local run emits PENDING-IN-VPC (never a FAIL/skip).
  * F1-SAFE-02: the whole live run is wrapped in cascade_census._athena_firewall() -- the OBSERVABLE
    guard. `athena_queries_issued: 0` is stamped only as evidence-of, not the enforcement.
  * F1-SAFE-03: a per-probe fragment-count cap (>500 fragments -> loud abort) -- a de-compaction
    regression fails visibly instead of silently issuing a huge footer scan / key-column load.

cp1252 console: all stdout is ASCII-only. Report FILES are UTF-8.

    PYTHONPATH=<wt>/src python jobs/audit/feature_readiness.py \\
        --evidence-dir reports/silver_readiness/F1_feature_readiness
    python jobs/audit/feature_readiness.py --skip-aws --evidence-dir <dir>   # offline enumeration
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

# Batch/CLI invoke this by PATH; put the repo root (jobs.* namespace) + src on sys.path first. The
# editable install can shadow to the MAIN repo, so the worktree run must force PYTHONPATH=<wt>/src.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

# --------------------------------------------------------------------------------------------------
# Constants (harness inputs -- explicit, auditable).
# --------------------------------------------------------------------------------------------------
PACKAGE = "FR-001"
SCHEMA_VERSION = "f1_machine_summary/1"

# F1-SAFE-03: crit-1/crit-3 are footer-safe ONLY under the BF-W1-compacted layout (chirps
# commodity=cotton == 46 files today; pre-compaction ~thousands). A prefix over this many fragments
# ABORTS loudly -- a layout regression must fail visibly.
FRAGMENT_CAP = 500

# Verdict vocabulary (mirrors the machine-summary schema).
GREEN = "GREEN"
RED = "RED"
WAIVED = "WAIVED"
WAIVED_BOUNDED = "WAIVED-BOUNDED"
INDETERMINATE = "INDETERMINATE"
PENDING_IN_VPC = "PENDING-IN-VPC"
NA = "N/A"
ABORTED = "ABORTED"

CRITERIA = (
    "crit1_present",
    "crit2_schema_complete",
    "crit3_key_clean",
    "crit4_value_populated",
    "crit5_vintage_adequate",
    "crit6_vocabulary_consistent",
    "crit7_coverage_declared",
)
TABLE_LEVEL = "__table__"  # machine-summary commodity sentinel for a table-scoped criterion

# ESR crit-5 is WAIVED-BOUNDED, not SATISFIED (F1-C02): silver_esr_compact carries the as_of_date
# vintages, but the B2 attestation records the earlier vintage as a WRITE-DATE BACKFILL
# (vintage_dates_real=false). PIT-valid only from ESR_PIT_VALID_FROM forward; the report NEVER asserts
# full-history PIT for ESR pace. These live in the harness, not the registry (a B2 attestation fact).
ESR_SERVING_TABLE = "silver_esr_compact"
ESR_RAW_TABLE = "silver_esr"
ESR_RAW_PREFIX = "silver/production/source=usda_esr"  # bounded exact-prefix; NEVER a recursive list
ESR_PIT_VALID_FROM = "2026-05-24"

# Weather stage-window source tables: for a CALENDAR slug these require a crop_calendars entry
# (plan 3.3). oni/iod (global scalars broadcast to ctx.countries) and faostat/psd need NO calendar.
CALENDAR_REQUIRED_TABLES = frozenset(
    {"silver_chirps", "silver_nasa_power", "silver_cpc_soil", "silver_modis_ndvi"}
)

# Documented dedup escape hatch (extractors._dedup_natural_key is called for these -- there is NO
# registry `dedup` field; this set mirrors the extractor literals, see report discrepancy note).
DEDUP_DOCUMENTED_TABLES = frozenset(
    {"silver_fred_fx", "silver_sagis_weekly_deliveries", "silver_futures_prices"}
)

# feature-registry source_key -> silver table_name. Explicit + non-uniform (do NOT pattern-match on
# the name stem): esr serves from the COMPACT table (raw silver_esr is fenced separately below).
SOURCE_KEY_TO_TABLE = {
    "weather:chirps": "silver_chirps",
    "weather:nasa_power": "silver_nasa_power",
    "weather:cpc_soil": "silver_cpc_soil",
    "weather:modis_ndvi": "silver_modis_ndvi",
    "production:faostat": "silver_production",
    "psd": "silver_psd",
    "oni": "silver_noaa_oni",
    "iod": "silver_noaa_iod",
    "cot": "silver_cot",
    "pink_sheet": "silver_pink_sheet",
    "nass_crop_progress": "silver_nass_crop_progress",
    "wap_revisions": "silver_wap_table01_revisions",
    "mpob": "silver_mpob",
    "fred_fx": "silver_fred_fx",
    "sagis_deliveries": "silver_sagis_weekly_deliveries",
    "sagis_cec": "silver_sagis_cec",
    "futures_prices": "silver_futures_prices",
    "conab": "silver_conab_coffee",
    "fgis": "silver_fgis",
    "esr": ESR_SERVING_TABLE,
    "wasde": "silver_wasde",
    "nass_citrus": "silver_nass_citrus",
    "ams_cotton_quality": "silver_ams_cotton_quality",
    "unica_biweekly": "silver_unica_biweekly_season_history",
}

# Value-census HARD kinds that fail crit-4 (KIND_STATS_UNAVAILABLE is a FAIL -- cannot certify).
_HARD_VALUE_KINDS = frozenset(
    {"all_nan", "nonnull_below_floor", "sentinel_saturated", "stats_unavailable"}
)
_KIND_SINGLE_VINTAGE = "single_vintage"


class FragmentCapExceeded(RuntimeError):
    """A resolved prefix carries more fragments than FRAGMENT_CAP -- a de-compaction regression that
    must abort the probe loudly (F1-SAFE-03), never silently issue a huge footer/key-column read."""


# --------------------------------------------------------------------------------------------------
# Pure helpers (no AWS) -- the tested surface.
# --------------------------------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enforce_fragment_cap(table: str, probe, *, cap: int = FRAGMENT_CAP) -> None:
    """Raise FragmentCapExceeded when a probe's fragment count exceeds the cap (F1-SAFE-03)."""
    n = int(getattr(probe, "num_files", 0) or 0)
    if n > cap:
        raise FragmentCapExceeded(
            f"{table}: {n} fragments under the resolved prefix exceeds the {cap}-file cap "
            "(BF-W1 de-compaction regression -- footer/key-column read aborted)"
        )


def commodity_partitioned(contract: dict) -> bool:
    """Does the PHYSICAL layout partition by commodity= ? Drives crit-4 per_group vs table_level
    granularity off the registry partition_mode (F1-C01) -- never a name heuristic.

    * projected  -> per-commodity iff a projection.commodity.values enum is declared.
    * registered/partitioned -> per-commodity iff a `commodity` partition key exists.
    * flat       -> False (in-file commodity: silver_psd, silver_modis_ndvi -> table_level, F1V-01).
    """
    mode = contract.get("partition_mode", "flat")
    if mode == "projected":
        dom = contract.get("projection_domains") or {}
        return bool(dom.get("projection.commodity.values"))
    if mode in ("registered", "partitioned"):
        return "commodity" in {pk.get("name") for pk in contract.get("partition_keys", [])}
    return False


def build_source_key_resolution(silver_reg) -> dict:
    """The named SOURCE_KEY_RESOLUTION harness input (2.0.1): source_key ->
    {table_name, s3_prefix, s3_root, partition_mode, layout, commodity_partitioned}. Derived
    deterministically from the F010 registry, cross-checked against the SOURCE_KEY_TO_TABLE literals.
    Emitted verbatim so a reviewer can audit exactly which prefix each probe reads."""
    out: dict = {}
    for skey, table in SOURCE_KEY_TO_TABLE.items():
        c = silver_reg.tables.get(table) if hasattr(silver_reg, "tables") else None
        if c is None:
            out[skey] = {"table_name": table, "resolved": False,
                         "note": "table_name not present in the F010 registry (ASSERTED)"}
            continue
        entry = {
            "table_name": table,
            "resolved": True,
            "s3_prefix": c.get("s3_prefix"),
            "s3_root": c.get("s3_root"),
            "partition_mode": c.get("partition_mode"),
            "layout": c.get("layout"),
            "commodity_partitioned": commodity_partitioned(c),
        }
        if table == ESR_SERVING_TABLE:
            entry["raw_source"] = {
                "table_name": ESR_RAW_TABLE,
                "s3_prefix": ESR_RAW_PREFIX,
                "note": "raw ESR probed as a BOUNDED exact-prefix under silver/production/source=usda_esr "
                        "-- NEVER a recursive silver/production/ list",
            }
        out[skey] = entry
    return out


def crit12_from_stage(stage_status: str, stage_detail: str, probe) -> tuple[tuple, tuple]:
    """Derive (crit-1, crit-2) verdicts from the shipped stage_feature_probe result (F1V-06). The
    harness does NOT re-implement existence + required-column logic; it maps the stage verdict.

    Returns ((crit1_verdict, crit1_evidence), (crit2_verdict, crit2_evidence))."""
    ev = {
        "exists": bool(getattr(probe, "exists", False)),
        "num_files": getattr(probe, "num_files", None),
        "num_rows": getattr(probe, "num_rows", None),
    }
    if stage_status == "green":
        return (GREEN, ev), (GREEN, {"required_columns_present": True})
    detail = stage_detail or ""
    if "missing required columns" in detail:
        # exists, but the registry required set is not a subset of the footer schema.
        return (GREEN, ev), (RED, {"detail": detail})
    # absent / no s3_root / probe error -> crit-1 FAIL; schema is uncheckable.
    return (RED, {"detail": detail, **ev}), (INDETERMINATE, {"detail": "source absent; schema uncheckable"})


def _value_rows_for_group(census_d: dict, group_label: str) -> list[dict]:
    """value gate rows tagged for one per-group label (census_one_table prefixes detail with
    `[<label>] ...`)."""
    tag = f"[{group_label}]"
    return [r for r in census_d.get("gate_rows", [])
            if r.get("kind") in _HARD_VALUE_KINDS and (r.get("detail") or "").startswith(tag)]


def crit4_per_commodity(table: str, census_d: dict, commodities, *, per_commodity: str) -> dict:
    """Map value_census per-group gate rows to a per-commodity crit-4 verdict (F1-C01).

    * per_commodity == 'per_group': each commodity's group label is `commodity=<slug>`; a hard value
      row for that group -> RED, a sampled clean group -> GREEN, an unsampled commodity ->
      INDETERMINATE.
    * per_commodity == 'table_level': one table-wide value verdict (any hard value row -> RED) applied
      to every served commodity (in-file-commodity flat tables cannot separate commodities from
      footer stats -- F1V-01).

    CHIRPS crit-4 is MEASURED here (never inherited from a BF-W1 certificate) -- F1-C05.
    """
    out: dict = {}
    if per_commodity == "table_level":
        hard = [r for r in census_d.get("gate_rows", []) if r.get("kind") in _HARD_VALUE_KINDS]
        verdict = RED if hard else GREEN
        ev = {"per_commodity": "table_level",
              "hard_rows": [r.get("detail") for r in hard][:8]} if hard else {"per_commodity": "table_level"}
        for cm in commodities:
            out[cm] = (verdict, dict(ev))
        return out
    groups = census_d.get("per_group_value_census", {}) or {}
    for cm in commodities:
        label = f"commodity={cm}"
        hard = _value_rows_for_group(census_d, label)
        if hard:
            out[cm] = (RED, {"per_commodity": "per_group",
                             "hard_rows": [r.get("detail") for r in hard][:4]})
        elif label in groups:
            out[cm] = (GREEN, {"per_commodity": "per_group", "group": label})
        else:
            out[cm] = (INDETERMINATE, {"per_commodity": "per_group",
                                       "detail": f"commodity group {label!r} not sampled"})
    return out


def _measured_distinct(census_d: dict, col: Optional[str]):
    if not col:
        return None
    c = (census_d.get("columns", {}) or {}).get(col)
    return c.get("distinct_lower_bound") if isinstance(c, dict) else None


def _fired_single_vintage(census_d: dict) -> bool:
    for r in list(census_d.get("gate_rows", [])) + list(census_d.get("warn_rows", [])):
        if r.get("kind") == _KIND_SINGLE_VINTAGE:
            return True
    return False


def crit5_vintage(table: str, contract: dict, census_d: dict) -> tuple:
    """Vintage-adequacy (table-level). Returns (verdict, evidence_dict).

    Semantics (plan 3.2):
      * silver_esr_compact       -> WAIVED-BOUNDED (vintage_dates_real=false, pit_valid_from), NEVER
        GREEN -- the earlier as_of vintage is a write-date backfill (F1-C02).
      * knowledge_date_col unset + vintage_retention 'per-vintage' -> INDETERMINATE (F-KDC follow-up;
        crit-5 cannot fire without a knowledge_date_col -- the silent-pass hole).
      * knowledge_date_col unset (latest-only)                     -> N/A (by design).
      * vintage_waiver mapping present (e.g. faostat)              -> WAIVED (reason+approved surfaced).
      * distinct_lower_bound == 1 / single_vintage fired           -> RED.
      * distinct_lower_bound >= 2 (measured at run time, F1-C09)   -> GREEN.
    """
    kcol = contract.get("knowledge_date_col")
    vint = contract.get("vintage_retention")
    waiver = contract.get("vintage_waiver")
    measured = _measured_distinct(census_d, kcol)

    if table == ESR_SERVING_TABLE:
        return (WAIVED_BOUNDED, {
            "knowledge_date_col": kcol,
            "measured_distinct_lower_bound": measured,
            "vintage_dates_real": False,
            "pit_valid_from": ESR_PIT_VALID_FROM,
            "decision": "D-ESR: serving-layer suffices from pit_valid_from forward; raw single-vintage + "
                        "the pre-2026-05-24 PIT gap are documented follow-ups (F-ESR-RAW)",
        })
    if not kcol:
        if vint == "per-vintage":
            return (INDETERMINATE, {
                "detail": "vintage_retention=per-vintage but knowledge_date_col unset -- crit-5 cannot "
                          "fire (follow-up F-KDC: add knowledge_date_col or an explicit vintage_required flag)",
                "vintage_retention": vint})
        return (NA, {"detail": "latest-only, no knowledge_date_col (by design)"})
    if waiver:
        return (WAIVED, {
            "knowledge_date_col": kcol,
            "measured_distinct_lower_bound": measured,
            "reason": waiver.get("reason") if isinstance(waiver, dict) else str(waiver),
            "approved": waiver.get("approved") if isinstance(waiver, dict) else None})
    if measured == 1 or _fired_single_vintage(census_d):
        return (RED, {"knowledge_date_col": kcol, "measured_distinct_lower_bound": measured,
                      "detail": "single vintage; PIT-inadequate"})
    return (GREEN, {"knowledge_date_col": kcol, "measured_distinct_lower_bound": measured})


def crit6_vocabulary(table: str, contract: dict, *, pg_mirror: bool, pg_reachable: bool) -> tuple:
    """Vocabulary-consistent (table-level). Returns (verdict, evidence_dict).

    * pg-mirror numbers table + pg unreachable (the off-VPC local run) -> PENDING-IN-VPC (never a FAIL;
      the C002 DISTINCT leg runs in-VPC as AWS Batch, E2b -- F1-SAFE-01).
    * every other (feature/flat/projection) table -> INDETERMINATE via footer distinct-BOUNDS only.
      NEVER an Athena DISTINCT on a projection table, NEVER a recursive silver/weather/ list (the
      Jul-2026 LIST-storm class).
    """
    if pg_mirror:
        if not pg_reachable:
            return (PENDING_IN_VPC, {
                "detail": "C002 DISTINCT vocabulary leg requires the in-VPC RDS pg mirror; resolved by "
                          "the E2b AWS Batch job (GRAPHRAG_NUMBERS_BACKEND=pg)"})
        return (INDETERMINATE, {"detail": "pg reachable but the in-harness C002 leg is not run here "
                                          "(delegated to contract_check.run_live at E2b)"})
    return (INDETERMINATE, {
        "detail": "non-mirror table: crit-6 via footer distinct-bounds only (largest genuine scope gap); "
                  "declared filter strings that cannot be footer-confirmed are reported indeterminate -- "
                  "NEVER an Athena DISTINCT on a projection table"})


def crit7_coverage(table: str, commodity: str, *, calendar_slugs, regions_present: bool,
                   calendar_required: bool) -> tuple:
    """Coverage-declared (per commodity). Returns (verdict, evidence_dict). Pure offline lint."""
    if calendar_required:
        cal_ok = commodity in calendar_slugs
        if not cal_ok and not regions_present:
            return (RED, {"detail": "missing crop_calendars entry AND regions", "calendar_required": True})
        if not cal_ok:
            return (RED, {"detail": "missing crop_calendars entry", "calendar_required": True})
        if not regions_present:
            return (RED, {"detail": "missing regions geography", "calendar_required": True})
        return (GREEN, {"calendar_required": True, "calendar_ok": True, "regions_ok": True})
    if not regions_present:
        return (RED, {"detail": "missing regions geography", "calendar_required": False})
    return (GREEN, {"calendar_required": False, "regions_ok": True, "calendar": "n/a"})


# --------------------------------------------------------------------------------------------------
# The harness (AWS wired via injectable backends -- all default to shipped primitives).
# --------------------------------------------------------------------------------------------------
@dataclass
class Backends:
    """Injectable AWS/footer backends. Tests pass offline fakes; production leaves them default."""
    probe_fn: Optional[Callable] = None          # (table, s3_root) -> SourceProbe
    stage_probe_fn: Optional[Callable] = None     # (table, gate_ctx) -> StageResult
    census_fn: Optional[Callable] = None          # (contract) -> (TableCensusResult, dict)
    key_dup_fn: Optional[Callable] = None         # (table, natural_key, files, region) -> int


@dataclass
class Harness:
    silver_reg: object
    feature_reg: object
    calendar_slugs: set
    geo_dir: Path
    backends: Backends = field(default_factory=Backends)
    pg_mirror_tables: frozenset = frozenset()
    pg_reachable: bool = False
    skip_aws: bool = False

    # ---- enumeration -----------------------------------------------------------------------------
    def served_commodities(self, table: str) -> list[str]:
        """Commodities the source table must serve = union over the feature families whose sources
        map to this table (via SOURCE_KEY_TO_TABLE)."""
        keys = {k for k, t in SOURCE_KEY_TO_TABLE.items() if t == table}
        served: set = set()
        for spec in getattr(self.feature_reg, "specs", ()):  # FeatureSpec
            if set(spec.sources) & keys:
                served.update(spec.commodities)
        return sorted(served)

    def regions_present(self, commodity: str) -> bool:
        p = self.geo_dir / f"{commodity}_regions.yaml"
        if not p.exists():
            return False
        try:
            import yaml
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
            return bool(doc)
        except Exception:  # noqa: BLE001 -- a malformed regions file is "not present" for the gate
            return False

    # ---- crit-3 (the one load-bearing data read; bounded, key-columns only) ----------------------
    def _key_dup_count(self, table: str, natural_key: list, probe) -> int:
        """Bounded key-columns-only projected read over the footer-listed exact-prefix files. NEVER
        Athena, NEVER a recursive list. Respects the fragment cap already enforced on `probe`."""
        if self.backends.key_dup_fn is not None:
            return self.backends.key_dup_fn(table, natural_key, getattr(probe, "files", ()), None)
        import pyarrow.dataset as ds  # lazy
        import pyarrow.fs as pafs
        from urllib.parse import urlparse
        files = list(getattr(probe, "files", ()) or ())
        if not files or not natural_key:
            return 0
        first = str(files[0])
        if Path(first).exists():
            # local parquet (tests / a local materialization) -- read directly.
            dataset = ds.dataset(files, format="parquet")
        else:
            # pyarrow S3 fragment paths are `bucket/key` (no scheme); read via S3FileSystem.
            import os
            region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
            fs = pafs.S3FileSystem(region=region)
            norm = [f"{urlparse(f).netloc}{urlparse(f).path}" if str(f).startswith("s3://") else str(f)
                    for f in files]
            dataset = ds.dataset(norm, filesystem=fs, format="parquet")
        cols = [c for c in natural_key if c in dataset.schema.names]
        if not cols:
            return 0
        import pandas as pd  # lazy
        tbl = dataset.to_table(columns=cols)
        df: pd.DataFrame = tbl.to_pandas()
        return int(df.duplicated(subset=cols).sum())

    def crit3_key_clean(self, table: str, contract: dict, probe, *, per_commodity: str,
                        commodities) -> dict:
        """Per-commodity crit-3 verdict. dup==0 -> GREEN; dup>0 on a documented-dedup table ->
        WAIVED; dup>0 otherwise -> RED. Absent source (crit-1 RED) -> INDETERMINATE."""
        out: dict = {}
        natural_key = list(contract.get("natural_key") or [])
        if not getattr(probe, "exists", False):
            for cm in commodities:
                out[cm] = (INDETERMINATE, {"detail": "source absent; key-cleanliness uncheckable"})
            return out
        documented = table in DEDUP_DOCUMENTED_TABLES
        if self.skip_aws:
            for cm in commodities:
                out[cm] = (INDETERMINATE, {"detail": "--skip-aws: bounded key-column read not run"})
            return out
        # table_level tables read the whole key column set once; per_group tables would scope to the
        # commodity's files -- both go through the same bounded projected reader. For simplicity and to
        # keep this the ONE data read, the harness reads table-wide key dups and applies the verdict
        # per commodity (a duplicate key is a table-level defect regardless of commodity).
        try:
            dups = self._key_dup_count(table, natural_key, probe)
        except Exception as exc:  # noqa: BLE001 -- a read failure is INDETERMINATE, never a false pass
            for cm in commodities:
                out[cm] = (INDETERMINATE, {"detail": f"key read failed: {type(exc).__name__}: {exc}"[:200]})
            return out
        if dups == 0:
            verdict, ev = GREEN, {"duplicate_keys": 0, "natural_key": natural_key}
        elif documented:
            verdict, ev = WAIVED, {"duplicate_keys": dups, "natural_key": natural_key,
                                   "detail": "documented dedup (extractors._dedup_natural_key)"}
        else:
            verdict, ev = RED, {"duplicate_keys": dups, "natural_key": natural_key}
        for cm in commodities:
            out[cm] = (verdict, dict(ev))
        return out

    # ---- one table ------------------------------------------------------------------------------
    def evaluate_table(self, table: str) -> dict:
        contract = self.silver_reg.table(table)
        commodities = self.served_commodities(table)
        per_commodity = "per_group" if commodity_partitioned(contract) else "table_level"
        resolution = build_source_key_resolution(self.silver_reg)
        skey = next((k for k, t in SOURCE_KEY_TO_TABLE.items() if t == table), None)
        rec: dict = {
            "source_family": table,
            "package": PACKAGE,
            "generated_at": _now(),
            "athena_queries_issued": 0,   # evidence-of (F1-SAFE-02); enforcement is the firewall
            "source_key": skey,
            "source_key_resolution": resolution.get(skey) if skey else None,
            "per_commodity_granularity": per_commodity,
            "min_nonnull_frac": contract.get("min_nonnull_frac"),
            "min_nonnull_frac_overrides": contract.get("min_nonnull_frac_overrides") or {},
            "vintage_waiver": (dict(contract["vintage_waiver"])
                               if isinstance(contract.get("vintage_waiver"), dict) else None),
            "served_commodities": commodities,
            "feature_families": self._families_for(table),
            "criteria": {},
            "commodities": {},
        }

        # --- crit-1 + crit-2 (table-level) via stage_feature_probe -------------------------------
        if self.skip_aws:
            rec["criteria"]["crit1_present"] = (INDETERMINATE, {"detail": "--skip-aws"})
            rec["criteria"]["crit2_schema_complete"] = (INDETERMINATE, {"detail": "--skip-aws"})
            probe = None
        else:
            probe = self.backends.probe_fn(table, contract.get("s3_root"))
            try:
                enforce_fragment_cap(table, probe)
            except FragmentCapExceeded as exc:
                rec["aborted"] = str(exc)
                rec["criteria"]["crit1_present"] = (ABORTED, {"detail": str(exc)})
                rec["criteria"]["crit2_schema_complete"] = (ABORTED, {"detail": str(exc)})
                # a de-compaction abort taints the footer criteria; record and stop this table's probes.
                print(f"  ABORT {table}: {str(exc)[:160]}")
                self._materialize(rec, commodities)
                return rec
            gate_ctx = self._gate_ctx()
            stage = self.backends.stage_probe_fn(table, gate_ctx)
            c1, c2 = crit12_from_stage(getattr(stage, "status", ""), getattr(stage, "detail", ""), probe)
            rec["criteria"]["crit1_present"] = c1
            rec["criteria"]["crit2_schema_complete"] = c2

        # --- crit-4 + crit-5 via census_one_table (footer) --------------------------------------
        crit4 = {}
        if self.skip_aws:
            rec["criteria"]["crit5_vintage_adequate"] = (INDETERMINATE, {"detail": "--skip-aws"})
        else:
            _result, census_d = self.backends.census_fn(contract)
            rec["value_census"] = {"passed": census_d.get("passed"),
                                   "files_sampled": census_d.get("files_sampled")}
            crit4 = crit4_per_commodity(table, census_d, commodities, per_commodity=per_commodity)
            rec["criteria"]["crit5_vintage_adequate"] = crit5_vintage(table, contract, census_d)

        # --- crit-3 (bounded key read) ----------------------------------------------------------
        crit3 = self.crit3_key_clean(table, contract, probe, per_commodity=per_commodity,
                                     commodities=commodities) if not self.skip_aws else {}

        # --- crit-6 (table-level) ----------------------------------------------------------------
        pg_mirror = table in self.pg_mirror_tables
        rec["criteria"]["crit6_vocabulary_consistent"] = crit6_vocabulary(
            table, contract, pg_mirror=pg_mirror, pg_reachable=self.pg_reachable)

        # --- crit-7 (per commodity) --------------------------------------------------------------
        calendar_required = table in CALENDAR_REQUIRED_TABLES
        crit7 = {}
        for cm in commodities:
            crit7[cm] = crit7_coverage(table, cm, calendar_slugs=self.calendar_slugs,
                                       regions_present=self.regions_present(cm),
                                       calendar_required=calendar_required)

        # --- assemble per-commodity block --------------------------------------------------------
        for cm in commodities:
            rec["commodities"][cm] = {
                "crit3_key_clean": crit3.get(cm, (INDETERMINATE, {"detail": "--skip-aws"})),
                "crit4_value_populated": crit4.get(cm, (INDETERMINATE, {"detail": "--skip-aws"})),
                "crit7_coverage_declared": crit7.get(cm, (NA, {})),
            }
        return rec

    def _materialize(self, rec: dict, commodities) -> None:
        """After an early return (abort), still record per-commodity crit-7 (offline) so the row is
        not vacuous."""
        calendar_required = rec["source_family"] in CALENDAR_REQUIRED_TABLES
        rec.setdefault("criteria", {}).setdefault(
            "crit6_vocabulary_consistent",
            crit6_vocabulary(rec["source_family"], self.silver_reg.table(rec["source_family"]),
                             pg_mirror=rec["source_family"] in self.pg_mirror_tables,
                             pg_reachable=self.pg_reachable))
        rec.setdefault("criteria", {}).setdefault("crit5_vintage_adequate", (ABORTED, {}))
        for cm in commodities:
            rec.setdefault("commodities", {})[cm] = {
                "crit3_key_clean": (ABORTED, {}),
                "crit4_value_populated": (ABORTED, {}),
                "crit7_coverage_declared": crit7_coverage(
                    rec["source_family"], cm, calendar_slugs=self.calendar_slugs,
                    regions_present=self.regions_present(cm), calendar_required=calendar_required),
            }

    def _families_for(self, table: str) -> list[str]:
        keys = {k for k, t in SOURCE_KEY_TO_TABLE.items() if t == table}
        return sorted({spec.family for spec in getattr(self.feature_reg, "specs", ())
                       if set(spec.sources) & keys})

    def _gate_ctx(self):
        from jobs.audit.silver_rebuild_gate import GateContext
        return GateContext(numbers_reg=None, silver_reg=self.silver_reg)


# --------------------------------------------------------------------------------------------------
# Machine summary + per-family JSON writers.
# --------------------------------------------------------------------------------------------------
def _summary_records(table_rec: dict) -> list[dict]:
    """Flatten one table record into machine-summary rows keyed by (table_name, commodity, criterion)."""
    table = table_rec["source_family"]
    gran = table_rec.get("per_commodity_granularity")
    waiver = table_rec.get("vintage_waiver")
    rows: list[dict] = []

    def _row(commodity, criterion, verdict_ev):
        verdict, ev = verdict_ev if isinstance(verdict_ev, (list, tuple)) else (verdict_ev, {})
        rows.append({
            "table_name": table,
            "commodity": commodity,
            "criterion": criterion,
            "verdict": verdict,
            "evidence": ev,
            "per_commodity_granularity": gran,
            "waiver": waiver,
            "pit_valid_from": ev.get("pit_valid_from") if isinstance(ev, dict) else None,
        })

    # table-level criteria
    for crit in ("crit1_present", "crit2_schema_complete", "crit5_vintage_adequate",
                 "crit6_vocabulary_consistent"):
        if crit in table_rec.get("criteria", {}):
            _row(TABLE_LEVEL, crit, table_rec["criteria"][crit])
    # per-commodity criteria
    for cm, block in table_rec.get("commodities", {}).items():
        for crit in ("crit3_key_clean", "crit4_value_populated", "crit7_coverage_declared"):
            if crit in block:
                _row(cm, crit, block[crit])
    return rows


def write_artifacts(table_recs: list[dict], evidence_dir: Path) -> dict:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for rec in table_recs:
        (evidence_dir / f"{rec['source_family']}.json").write_text(
            json.dumps(rec, indent=2, sort_keys=True, default=str), encoding="utf-8")

    records: list[dict] = []
    for rec in table_recs:
        records.extend(_summary_records(rec))
    summary = {
        "schema_version": SCHEMA_VERSION,
        "package": PACKAGE,
        "generated_at": _now(),
        "mechanism": "parquet_footer_statistics + config lint (read-only)",
        "athena_queries_issued": 0,
        "tables": [r["source_family"] for r in table_recs],
        "records": records,
    }
    (evidence_dir / "f1_machine_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")

    _write_report_md(table_recs, records, evidence_dir)
    return summary


def _verdict_of(vev):
    return vev[0] if isinstance(vev, (list, tuple)) else vev


def _write_report_md(table_recs: list[dict], records: list[dict], evidence_dir: Path) -> None:
    """The human scoreboard (ASCII) + the follow-up work-order list (2.8). Signed at g2."""
    lines = ["# FR-001 Feature-Readiness Report", "",
             f"generated_at: {_now()}", f"schema_version: {SCHEMA_VERSION}",
             f"tables: {len(table_recs)}   machine_summary_records: {len(records)}", ""]
    tally: dict = {}
    for r in records:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    lines.append("## Verdict tally")
    for v in sorted(tally):
        lines.append(f"- {v}: {tally[v]}")
    lines.append("")
    lines.append("## Source x criterion scoreboard (table-level criteria)")
    for rec in table_recs:
        crits = rec.get("criteria", {})
        cells = "  ".join(f"{c.split('_')[0]}={_verdict_of(crits.get(c, (NA,)))}"
                          for c in ("crit1_present", "crit2_schema_complete",
                                    "crit5_vintage_adequate", "crit6_vocabulary_consistent"))
        lines.append(f"- {rec['source_family']} [{rec.get('per_commodity_granularity')}]: {cells}")
    lines.append("")
    lines.append("## Follow-up work orders (failing / bounded criteria)")
    wo = [r for r in records if r["verdict"] in (RED, INDETERMINATE, PENDING_IN_VPC, WAIVED_BOUNDED,
                                                 ABORTED)]
    if not wo:
        lines.append("- none")
    for r in wo:
        det = r["evidence"].get("detail") if isinstance(r["evidence"], dict) else ""
        lines.append(f"- {r['verdict']}  {r['table_name']}/{r['commodity']}/{r['criterion']}"
                     + (f" -- {det}" if det else ""))
    (evidence_dir / "FEATURE_READINESS_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# Live wiring + CLI.
# --------------------------------------------------------------------------------------------------
def _default_backends():
    from leviathan.features import extractors
    from jobs.audit.silver_rebuild_gate import stage_feature_probe
    from jobs.audit.value_census import census_one_table
    return Backends(
        probe_fn=lambda table, s3_root: extractors.probe_source(table, s3_root),
        stage_probe_fn=stage_feature_probe,
        census_fn=census_one_table,
    )


def _pg_mirror_tables() -> frozenset:
    try:
        from jobs.utils.load_pg_numbers import P1_TABLES
        return frozenset(set(P1_TABLES) | {ESR_SERVING_TABLE})
    except Exception:  # noqa: BLE001 -- keep the harness usable if the pg loader import is unavailable
        return frozenset({"silver_psd", "silver_wasde", "silver_production", ESR_RAW_TABLE,
                          ESR_SERVING_TABLE, "silver_fred_fx", "silver_noaa_oni", "gold_weather_z"})


def build_harness(*, skip_aws: bool, backends: Optional[Backends] = None) -> Harness:
    from leviathan.silver import registry as sreg
    from leviathan.features import registry as freg
    from leviathan.features.calendar import load_crop_calendars
    silver_reg = sreg.load_registry()
    feature_reg = freg.load_registry()
    geo_dir = _REPO_ROOT / "configs" / "geographies"
    calendar_slugs = set(load_crop_calendars(_REPO_ROOT / "configs" / "features" / "crop_calendars.yaml"))
    return Harness(
        silver_reg=silver_reg,
        feature_reg=feature_reg,
        calendar_slugs=calendar_slugs,
        geo_dir=geo_dir,
        backends=backends or (Backends() if skip_aws else _default_backends()),
        pg_mirror_tables=_pg_mirror_tables(),
        pg_reachable=False,
        skip_aws=skip_aws,
    )


def run(evidence_dir: Path, tables: Optional[list[str]], *, skip_aws: bool) -> int:
    harness = build_harness(skip_aws=skip_aws)
    targets = tables or [t for t in SOURCE_KEY_TO_TABLE.values() if t in harness.silver_reg.tables]
    targets = sorted(dict.fromkeys(targets))

    def _sweep():
        recs = []
        for t in targets:
            if t not in harness.silver_reg.tables:
                print(f"WARN skip unknown table: {t}")
                continue
            print(f"[FR-001] readiness {t} ...")
            recs.append(harness.evaluate_table(t))
        return recs

    if skip_aws:
        table_recs = _sweep()
    else:
        # F1-SAFE-02: the OBSERVABLE Athena firewall wraps the whole live run.
        from leviathan.graphrag.numbers.cascade_census import _athena_firewall
        with _athena_firewall():
            table_recs = _sweep()

    summary = write_artifacts(table_recs, evidence_dir)
    n_red = sum(1 for r in summary["records"] if r["verdict"] == RED)
    n_pending = sum(1 for r in summary["records"] if r["verdict"] == PENDING_IN_VPC)
    print(f"[FR-001] tables={len(table_recs)} records={len(summary['records'])} "
          f"red={n_red} pending_in_vpc={n_pending}")
    print(f"[FR-001] evidence -> {evidence_dir}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="feature_readiness (FR-001): read-only 7-criterion harness")
    ap.add_argument("--evidence-dir", required=True, help="output directory for the F1 artifacts")
    ap.add_argument("--tables", default=None, help="comma-separated subset (default: all source families)")
    ap.add_argument("--skip-aws", action="store_true", help="offline enumeration mode (no AWS reads)")
    a = ap.parse_args(argv)
    tables = [t.strip() for t in a.tables.split(",") if t.strip()] if a.tables else None
    return run(Path(a.evidence_dir), tables, skip_aws=a.skip_aws)


if __name__ == "__main__":
    raise SystemExit(main())
