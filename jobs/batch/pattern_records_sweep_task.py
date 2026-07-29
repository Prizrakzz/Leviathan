"""T2B pattern-records ledger: the daily engine-replay sweep + the bounded backfill grid.

Writes ONE row per (record_kind, contract, driver_or_chain_id, asof_date) recording the
DETERMINISTIC engine's OWN fired/declined verdict + values AT that asof, so persistence / streak /
base-rate / last-fired claims become CITABLE [N] facts read from an ordinary observed table
(gold_pattern_records) instead of prose the model asserts and the verifier strips.

Doctrine (docs/private/T2B_PATTERN_RECORDS_PLAN.md, D1-D12 ratified 2026-07-24 -- read it):
  * The ledger RECORDS the engine's verdicts; ONLY the model interprets. NO minted thresholds, NO
    pattern->conclusion rules (the 6.8 fake-threshold / WS-COND anti-patterns).
  * The FIRED/DECLINED split is the engine's OWN verdict, read from the trace-key-present-iff-fired
    contract (cascade.py) -- the sweep NEVER re-decides firing. It re-derives ONLY a pace decline
    REASON among declines (net-new logic that DUPLICATES the engine's inline `_pace_legs` gates, so it
    carries drift risk -- a drift-detection test pins it, plan sec 5.2 / F6).
  * PIT-safe by construction: a row written at T describes the verdict AT T and is NEVER recomputed
    with later DATA nor later CODE. The registered as_of_date partition guards the data axis; the
    engine_version WRITE-GUARD (a re-run under a bumped engine_version is REFUSED, never a silent
    overwrite) guards the code axis (plan sec 2.3 / F1).
  * v1 kinds = cascade + pace + chain ONLY. comove / reroute / price_leg are DECLARED in the enum but
    DEFERRED (cross-node forks with no single driver key, plan sec 2.2 / F4); the reserved
    `counterparty` column awaits them.
  * The DAILY path records DAILY_SWEEP_KINDS = {pace} ONLY (COVERAGE_AND_CAPACITY_PLAN W3). cascade
    verdicts are constant-valued catalog-EXISTENCE flags with zero measured variance and chain verdicts
    are 100% root_not_grounded without a trace_provider -- neither has an event axis, and both
    resolvability pictures live in cascade_census / config_check.check_chain_map instead. The BACKFILL
    path still records every kind asked for. See DAILY_SWEEP_KINDS for the measurements.
  * provenance {daily_sweep, backfill_grid} -- BOTH are batch replays (today-asof vs a past-asof grid),
    NEVER a production "live" fire (there is none; serving has zero organic traffic, plan sec 3.3 / F5).
    They are NOT additive at one asof: the layout is ONE OBJECT PER ASOF and provenance is a physical
    column, so a cross-provenance write at an occupied asof DESTROYS the incumbent rows (it did, on
    2026-07-25 09:03Z). apply_write_guard refuses it.
  * The backfill grid runs ONLY over surfaces whose EVERY leg reads a table with a GENUINE as-of axis:
    release-date-vintaged (VINTAGED_TABLES) and NOT in LEAKY_ASOF_TABLES. The period LATEST-ONLY tables
    (silver_noaa_oni / gold_weather_z) read RESTATED data at a past asof (plan sec 3.1 / F2), and
    silver_psd's release_date is SYNTHESIZED in code -- it admitted 37,752 leaked rows before it was
    fenced (COVERAGE_AND_CAPACITY_PLAN sec 1.4 / D2; see LEAKY_ASOF_TABLES).

ENGINE-REPLAY IDIOM (cascade_census): import the production quantify helpers (map_row / _scope /
_region_row / _node_specs / _run_one / _pace_series / _pace_legs from cascade.py), never copy them, so
lint and runtime cannot diverge. pg-ONLY BY CONSTRUCTION -- every probe rides pgnumbers.pg_query
(raise-on-failure), NEVER a query_fn/default_query_fn Athena-fallback closure (the ZERO-Athena rule; a
mirror gap is a probe-error verdict, never a silent billed Athena scan / LIST-storm).

    python jobs/batch/pattern_records_sweep_task.py --dry-run            # today's sweep, write NOTHING
    python jobs/batch/pattern_records_sweep_task.py --backfill --dry-run # the bounded weekly grid

NO AWS mutation unless --publish-mode canonical (signed approval; readiness identities are denied).
Runs on a DEDICATED scoped jobdef (the P3 morning-brief pattern: own role, schedule created DISABLED,
one day-0 manual run, ENABLE only after review) -- plan sec 7 step 5.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Optional

logger = logging.getLogger("pattern_records_sweep_task")

TABLE = "gold_pattern_records"
DATABASE = "leviathan_dev"
S3_PREFIX = "gold/pattern_records"

# The SAME table, SCHEMA-QUALIFIED, for statements sent to the pg mirror. These are NOT interchangeable
# and the difference is not cosmetic -- it silently disarmed the write-guard.
#
# TABLE is the GLUE/registry identity (ShadowPublisher's `table=`, load_registry().table(...)) and must
# stay bare. But the pg mirror creates every table inside the schema `leviathan_dev`
# (jobs/utils/load_pg_numbers.py: CREATE TABLE "leviathan_dev"."<physical>"), and the mirror connection
# runs with the DEFAULT search_path -- pgstore._acquire() sets only statement_timeout, never a schema.
# Probed in-VPC on the sweep's own connection (leviathan-dev-evidence-build, 2026-07-28):
#
#     search_path            = '"$user", public'
#     current_schemas(true)  = ['pg_catalog', 'public']
#     to_regclass('gold_pattern_records')               -> None
#     to_regclass('leviathan_dev.gold_pattern_records') -> leviathan_dev.gold_pattern_records
#
# So an UNQUALIFIED `FROM gold_pattern_records` raises psycopg.errors.UndefinedTable (SQLSTATE 42P01,
# message: relation "gold_pattern_records" does not exist) on EVERY call. _is_missing_ledger_table()
# then matched on all three of its branches -- including the message branch, because the name in the
# error IS our table name -- so read_existing_guard_rows returned [] ("a legitimate first write"),
# apply_write_guard saw an EMPTY partition, and BOTH refusals (cross-provenance and cross-version) were
# unreachable. The same probe run qualified returned 251 rows at as_of_date=2026-07-25: the rows the
# guard was supposed to protect were there the whole time and it never saw one of them.
#
# This is why the 2026-07-25 09:03Z overwrite was not caught: the provenance filter (plan sec E) is a
# real defect, but even with it removed the guard could not have refused, because the read itself could
# not resolve. Every other numbers query in the repo is already qualified via build_sql(db=ATHENA_DB).
PG_SCHEMA = "leviathan_dev"                 # == numbers.pgnumbers.SCHEMA == numbers.query.ATHENA_DB
PG_TABLE = f'"{PG_SCHEMA}".{TABLE}'

# ── record kinds (plan sec 1.1) ──────────────────────────────────────────────────────────────────
KIND_CASCADE = "cascade"
KIND_PACE = "pace"
KIND_CHAIN = "chain"
V1_KINDS = frozenset({KIND_CASCADE, KIND_PACE, KIND_CHAIN})
# DECLARED but DEFERRED to v1.1 (F4): cross-node forks with no single driver_or_chain_id, no per-kind
# sweep loop yet. Reserved in the enum + the counterparty column; NEVER written by v1.
DEFERRED_FORK_KINDS = frozenset({"comove", "reroute", "price_leg"})

# ── what the DAILY path records: PACE ONLY (COVERAGE_AND_CAPACITY_PLAN W3) ───────────────────────
# The daily sweep is a CITABLE ledger; only kinds with an EVENT AXIS belong in it. Measured on the
# 156-asof backfill (39,156 rows), the other two kinds have none:
#   * cascade -- 242 pairs x 156 asofs = 37,752 rows whose per-pair (fired, swept) takes exactly two
#     values, (156,156) x163 and (0,156) x79. ZERO pairs vary. A FIRED cascade row is cascade_census's
#     pg_probe returning >=1 row -- its own docstring calls it "A whole-history existence probe:
#     agg=latest, no period window" -- i.e. a CATALOG-RESOLVABILITY flag, time-invariant by
#     construction. Corroborated by the rows themselves: n_rows==1 with streak_len / streak_dir /
#     window_change / grain / n_points / n_hops ALL NULL on all 25,428 fired cascade rows. Replicating
#     a constant 242x/day dilutes every base rate computed over the ledger and cannot answer any
#     question about an EVENT ("fired on 156 of 156 sweeps" means only "this table has rows").
#   * chain -- 29 (chain, contract) pairs, and main() injects NO trace_provider, so chain_verdicts
#     declines every one `root_not_grounded`: ~10,600 rows/yr recording only "we did not run the
#     grounding walk." They are absent from the 156-asof backfill ONLY because backfill_eligible(())
#     is False on chain's empty leg set -- the daily path has no such accident to protect it.
# NOTHING IS LOST. Both resolvability pictures already live in richer, NON-citable ops surfaces:
#   * cascade -> cascade_census.census() (src/leviathan/graphrag/numbers/cascade_census.py:231-308)
#     emits the full per-leg verdict (FIRES / DARK-with-reason / DECLINES / PROBE_ERROR), the
#     per_contract_has_firing_leg rollup and the fires/declines/dark/probe_errors banner -- strictly
#     MORE than the ledger's boolean. It is published by jobs/audit/advance_rolling_census.py to
#     s3://<bucket>/cascade_census/rolling/{family}/census.json and read back by
#     jobs/audit/silver_rebuild_gate.py:468-490 from data/cascade_census/as_of_date=<asof>/census.json.
#   * chain -> config_check.check_chain_map() (src/leviathan/graphrag/config_check.py:238), a
#     fail-CLOSED BUILD lint over every hop ref, scope, country pin and contract binding. It fails the
#     build instead of accruing a constant decline row forever.
# The BACKFILL GRID path is DELIBERATELY UNCHANGED: a provenance=backfill_grid replay still records
# every kind the caller asks for, so the existing grid stays reproducible.
DAILY_SWEEP_KINDS = frozenset({KIND_PACE})

# ── verdicts + provenance (plan sec 1.1 / 3.3 / F5) ──────────────────────────────────────────────
VERDICT_FIRED = "fired"
VERDICT_DECLINED = "declined"
PROV_DAILY_SWEEP = "daily_sweep"     # the sweep at asof = today (accrues forward)
PROV_BACKFILL_GRID = "backfill_grid"  # the sweep at a past-asof weekly grid (labeled base-rate only)
PROVENANCES = frozenset({PROV_DAILY_SWEEP, PROV_BACKFILL_GRID})

# ── decline enums ────────────────────────────────────────────────────────────────────────────────
# Pace: the soak G3 target set. The shipped pace engine records declines as SILENT continues (the trace
# key is ABSENT on decline), so the sweep RE-DERIVES the reason by replaying the resolution + classifying
# the absence against the SAME inline gates as cascade._pace_legs (plan sec 5.2 / F6 -- net-new logic,
# drift-guarded). "emitted" is NOT a decline reason (it == fired).
PACE_DECLINE_THIN = "thin_history"                 # < MIN_STREAK_N collapsed periods
PACE_DECLINE_ANNUAL = "annual_grain"               # no sub-annual grain (MY / flag)
PACE_DECLINE_XSECTION = "cross_section_undeclared"  # multi-row period on an undeclared-collapse table
PACE_DECLINE_FETCH = "fetch_error"                 # the resolution/fetch did not return status=ok
PACE_DECLINE_REGION = "region_unresolved"          # _scope returned SKIP_NODE (compound/prose region)
PACE_DECLINE_REASONS = frozenset({
    PACE_DECLINE_THIN, PACE_DECLINE_ANNUAL, PACE_DECLINE_XSECTION, PACE_DECLINE_FETCH, PACE_DECLINE_REGION,
})
# Chain: the CHAIN_ENGINE_PLAN D7 enum, carried on sg.trace['quantify_chain_decline'].
CHAIN_DECLINE_REASONS = frozenset({
    "root_not_grounded", "hop_dark", "hop_thin", "degenerate", "cap", "error",
})
# Cascade: the cascade_census resolution-layer sub-reasons (DARK-WITH-REASON) + honest declines.
CASCADE_DECLINE_REASONS = frozenset({
    "country-not-a-psd-title", "commodity-slug-miss", "metric-empty-for-country",
    "uncertified-table", "table-not-registered", "region-unresolved", "waived", "probe-error",
})

# ── backfill eligibility (plan sec 3.1 / 3.4 / D6 / F2) ──────────────────────────────────────────
# Release-date-vintaged: the engine at a historical asof returns exactly what was KNOWN at T (a later
# restatement is a NEW vintage row). ONLY these are honestly as-of replayable.
# NECESSARY BUT NOT SUFFICIENT -- membership here means the table CARRIES a release_date axis, not that
# the axis is TRUE. LEAKY_ASOF_TABLES (below) overrides this set and is checked FIRST.
VINTAGED_TABLES = frozenset({
    "silver_esr_compact", "silver_esr", "silver_wasde", "silver_psd",
})
# Vintaged in SCHEMA, SYNTHESIZED in fact -- backfill_eligible REJECTS these outright, ahead of every
# other test (COVERAGE_AND_CAPACITY_PLAN sec 1.4 / D2 / SV-L2-N1 / SV-L2-N2).
#
# silver_psd: bronze holds exactly TWO objects (release_date=2026-05-20 and release_date=2026-07-17),
# yet silver carries 765 distinct release_date values -- because
# src/leviathan/transforms/bronze_to_silver/usda_psd.py::_compute_psd_release_dates REPLACES bronze's
# real download stamp with a CLOSED-FORM label (cal_year + "-" + cal_month + "-10", clamped at
# ingest_date). month_code is structurally confined to [0,12], so a revision made outside the
# marketing year's 12-release cycle CANNOT be encoded and is silently BACKDATED into the window.
# Measured by diffing the two bronze snapshots (join on country_name -- country_code is 100% NULL in
# bronze and silently collapses the diff to 69,589 of 968,699 keys):
#   * 739 keys CHANGED VALUE while keeping the SAME computed release_date (24 of them MY <= 2020);
#   * 9,292 keys EXIST in the July bronze and NOT in the May bronze yet carry a computed
#     release_date <= 2026-05-20 -- backdated as far as 2020-11-10.
# The second channel is 12.6x larger and it is the one that matters here: a cascade verdict is an
# EXISTENCE probe (n_rows >= 1), so ROW-EXISTENCE leakage maps exactly onto the recorded quantity.
# This membership is what admitted the 37,752 backfill_grid cascade rows already on S3. Those rows are
# LEFT IN PLACE as an audit record and fenced on the READ side in
# src/leviathan/graphrag/numbers/pattern_records.py; this set is the WRITE-side half of the same fence,
# so the leak cannot be re-earned by a future backfill run launched from a session that never read the
# plan. A read fence alone leaves the write re-earnable.
LEAKY_ASOF_TABLES = frozenset({"silver_psd"})
# Period-partitioned LATEST-ONLY: one value per year_month = TODAY's value, possibly REBUILT since T
# (the CHIRPS rebuild retired 17,642 weather_z partitions). A past-asof replay reads later data wearing a
# past period label -> EXCLUDED from the backfill grid; recorded daily-sweep-only going forward.
LATEST_ONLY_TABLES = frozenset({"silver_noaa_oni", "gold_weather_z"})

# The physical column order (MUST match configs/silver/tables/gold_pattern_records.yaml). as_of_date is
# the registered PARTITION key -- it is NOT a physical column (it lives in the S3 path, Hive-style).
COLUMNS = (
    "record_kind", "contract", "driver_or_chain_id", "counterparty", "verdict", "decline_reason",
    "streak_len", "streak_dir", "window_change", "grain", "n_points", "n_rows", "n_hops", "extra",
    "engine_version", "graph_version", "provenance", "run_id", "written_at",
)
PARTITION_COL = "as_of_date"


# ── version stamps ───────────────────────────────────────────────────────────────────────────────
def resolve_engine_version() -> str:
    """The serving image tag / code SHA that produced the verdict (plan sec 1.1). Env-first (the daily
    jobdef injects the deployed image tag), then a best-effort git SHA, else 'unknown'. NON-key by
    design; the write-guard (apply_write_guard) is what a cross-version change trips."""
    for var in ("GRAPHRAG_ENGINE_VERSION", "SERVING_IMAGE_TAG", "LEVIATHAN_ENGINE_VERSION", "CODE_SHA"):
        v = os.environ.get(var)
        if v and v.strip():
            return v.strip()
    try:  # pragma: no cover -- best-effort, never fatal
        import subprocess
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def resolve_graph_version(*, repo=None) -> str:
    """The causal-graph + cascade_map content hash (the tracked-config version, plan sec 1.1). A
    deterministic sha256 over cascade_map.yaml + chain_map.yaml + the causal DAG yamls (sorted, bytes),
    so a graph edit is a distinct graph_version that the write-guard separates from a prior asof's rows.

    REPO ROOT IS parents[2], NOT parents[1]. This file is <repo>/jobs/batch/…, so parents[1] is
    <repo>/jobs -- and jobs/configs/graphrag DOES NOT EXIST (jobs/configs holds only `sources/`). The
    glob therefore matched nothing, `parts` stayed empty, and every one of the 39,156 rows written so
    far carries the hash of the EMPTY STRING: sha256(b"").hexdigest()[:16] == "e3b0c44298fc1c14", i.e.
    graph_version was a DEAD guard axis and a cascade_map / causal-DAG edit was invisible to
    apply_write_guard. parents[2] is the repo root, where configs/graphrag/{numbers,causal} live.
    `repo` is injectable for tests ONLY; production always derives it (COVERAGE_AND_CAPACITY_PLAN W5).

    NOTE for the first post-fix run: rows written from here on carry a DIFFERENT graph_version from the
    39,156 backfill rows. That is intended. Because the guard only compares versions on a key that
    ALREADY EXISTS, a fresh asof is unaffected; a re-publish AT an existing asof is REFUSED, which is
    exactly the guard doing its job rather than a regression (plan U7)."""
    from pathlib import Path
    repo = Path(repo) if repo is not None else Path(__file__).resolve().parents[2]
    parts: list[bytes] = []
    cfg = repo / "configs" / "graphrag"
    for rel in ("numbers/cascade_map.yaml", "numbers/chain_map.yaml"):
        p = cfg / rel
        if p.exists():
            parts.append(p.read_bytes())
    causal = cfg / "causal"
    if causal.is_dir():
        for p in sorted(causal.glob("*.yaml")):
            parts.append(p.read_bytes())
    h = hashlib.sha256()
    for b in parts:
        h.update(b)
        h.update(b"\x00")
    return "gv1:" + h.hexdigest()[:16]


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ── the run context (the version/provenance/run stamps a sweep applies to every row) ──────────────
@dataclass(frozen=True)
class RunContext:
    """The per-run stamps applied to every record: the engine + graph version (the write-guard axes),
    the provenance class, the run_id (idempotency + audit join), and written_at (distinct from asof)."""

    engine_version: str
    graph_version: str
    provenance: str
    run_id: str
    written_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCES:
            raise ValueError(f"unknown provenance {self.provenance!r} (want one of {sorted(PROVENANCES)})")


# ── the record ───────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PatternRecord:
    """One ledger row. The FLAT numeric columns are queryable so the SQL agent aggregates base rates +
    run lengths WITHOUT parsing JSON; `extra` holds kind-specific structure (provenance detail, never an
    aggregation axis, D4)."""

    record_kind: str
    contract: str
    driver_or_chain_id: str
    as_of_date: str
    verdict: str
    engine_version: str
    graph_version: str
    provenance: str
    run_id: str
    written_at: str
    counterparty: Optional[str] = None
    decline_reason: Optional[str] = None
    streak_len: Optional[int] = None
    streak_dir: Optional[str] = None
    window_change: Optional[float] = None
    grain: Optional[str] = None
    n_points: Optional[int] = None
    n_rows: Optional[int] = None
    n_hops: Optional[int] = None
    extra: Optional[str] = None

    def __post_init__(self) -> None:
        if self.record_kind not in V1_KINDS:
            raise ValueError(f"v1 writes only {sorted(V1_KINDS)} (got {self.record_kind!r}; fork kinds "
                             f"{sorted(DEFERRED_FORK_KINDS)} are DEFERRED, F4)")
        if self.verdict not in (VERDICT_FIRED, VERDICT_DECLINED):
            raise ValueError(f"verdict must be fired|declined (got {self.verdict!r})")
        # honest-decline invariant (plan doctrine): a decline carries a reason; a fire carries none.
        if self.verdict == VERDICT_DECLINED and not self.decline_reason:
            raise ValueError("a declined record MUST record a decline_reason (honest-decline doctrine)")
        if self.verdict == VERDICT_FIRED and self.decline_reason:
            raise ValueError("a fired record MUST NOT carry a decline_reason")

    def natural_key(self) -> tuple:
        """The plan's natural key (record_kind, contract, driver_or_chain_id, asof_date) -- D3."""
        return (self.record_kind, self.contract, self.driver_or_chain_id, self.as_of_date)

    def guard_key(self) -> tuple:
        """The natural key WITHIN a provenance class -- the IDEMPOTENCY key (one row per guard_key in a
        published partition), NOT a licence to write across classes.

        The plan (sec 2.3) originally read this as "daily_sweep and backfill_grid rows for the same
        (kind, contract, driver, asof) COEXIST, so the classes never collide." That is FALSE at the
        storage layer and it destroyed data on 2026-07-25: the layout is ONE OBJECT PER ASOF
        (gold/pattern_records/as_of_date=<d>/pattern_records.parquet) and provenance is a physical
        COLUMN, not a partition key -- so a second provenance class at an occupied asof is a
        read-modify-write of a certified canonical object, not an addition. apply_write_guard therefore
        refuses cross-provenance writes at the PARTITION level, before this key is ever consulted."""
        return self.natural_key() + (self.provenance,)

    def row(self) -> dict:
        """The flat dict for the parquet writer (physical columns + the partition column)."""
        d = {c: getattr(self, c) for c in COLUMNS}
        d[PARTITION_COL] = self.as_of_date
        return d


# ── record builders (the tested pure core -- fed engine trace entries / verdicts) ─────────────────
def _extra(payload: dict) -> Optional[str]:
    payload = {k: v for k, v in payload.items() if v is not None}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) if payload else None


def pace_record(contract: str, driver_id: str, asof: str, ctx: RunContext, *,
                entry: Optional[dict] = None, decline_reason: Optional[str] = None,
                n_rows: int = 0) -> PatternRecord:
    """Build a pace record. EXACTLY one of `entry` (a cascade.py quantify_pace entry -> FIRED) or
    `decline_reason` (-> DECLINED) is supplied. The fired/declined split is the ENGINE's verdict (entry
    present iff fired); the sweep never re-decides it (plan sec 5.2 mitigation 2)."""
    if (entry is None) == (decline_reason is None):
        raise ValueError("pace_record: supply exactly one of entry (fired) or decline_reason (declined)")
    if entry is not None:
        return PatternRecord(
            record_kind=KIND_PACE, contract=contract, driver_or_chain_id=driver_id, as_of_date=asof,
            verdict=VERDICT_FIRED,
            streak_len=entry.get("streak"), streak_dir=entry.get("streak_direction"),
            window_change=entry.get("window_change"), grain=entry.get("grain"),
            n_points=entry.get("n_points"), n_rows=int(n_rows),
            extra=_extra({"table": entry.get("table"), "metric": entry.get("metric"),
                          "collapse": entry.get("collapse")}),
            engine_version=ctx.engine_version, graph_version=ctx.graph_version,
            provenance=ctx.provenance, run_id=ctx.run_id, written_at=ctx.written_at)
    if decline_reason not in PACE_DECLINE_REASONS:
        raise ValueError(f"unknown pace decline reason {decline_reason!r} (want {sorted(PACE_DECLINE_REASONS)})")
    return PatternRecord(
        record_kind=KIND_PACE, contract=contract, driver_or_chain_id=driver_id, as_of_date=asof,
        verdict=VERDICT_DECLINED, decline_reason=decline_reason, n_rows=0,
        engine_version=ctx.engine_version, graph_version=ctx.graph_version,
        provenance=ctx.provenance, run_id=ctx.run_id, written_at=ctx.written_at)


def cascade_record(contract: str, driver_id: str, asof: str, ctx: RunContext, *,
                   fired: bool, decline_reason: Optional[str] = None, n_rows: int = 0,
                   table: Optional[str] = None, metric: Optional[str] = None) -> PatternRecord:
    """Build a cascade record from a cascade_census leg verdict (FIRES -> fired; DARK/DECLINES -> declined
    with the census resolution-layer reason). The base quantified-cascade leg carries no streak/window
    (pace-only), so those stay NULL."""
    if fired:
        return PatternRecord(
            record_kind=KIND_CASCADE, contract=contract, driver_or_chain_id=driver_id, as_of_date=asof,
            verdict=VERDICT_FIRED, n_rows=int(n_rows), extra=_extra({"table": table, "metric": metric}),
            engine_version=ctx.engine_version, graph_version=ctx.graph_version,
            provenance=ctx.provenance, run_id=ctx.run_id, written_at=ctx.written_at)
    if decline_reason not in CASCADE_DECLINE_REASONS:
        raise ValueError(f"unknown cascade decline reason {decline_reason!r}")
    return PatternRecord(
        record_kind=KIND_CASCADE, contract=contract, driver_or_chain_id=driver_id, as_of_date=asof,
        verdict=VERDICT_DECLINED, decline_reason=decline_reason, n_rows=0,
        extra=_extra({"table": table, "metric": metric}),
        engine_version=ctx.engine_version, graph_version=ctx.graph_version,
        provenance=ctx.provenance, run_id=ctx.run_id, written_at=ctx.written_at)


def _chain_hops(fired: dict) -> list[dict]:
    return [h for h in (fired.get("hops") or []) if isinstance(h, dict)]


def chain_record(contract: str, chain_id: str, asof: str, ctx: RunContext, *,
                 fired: Optional[dict] = None, decline: Optional[dict] = None) -> PatternRecord:
    """Build a chain record from the chain engine's OWN per-turn trace (plan sec 5, D9): a fired
    sg.trace['quantify_chain'] {chain_id, contract, window, hops, n_rows} -> FIRED; a
    sg.trace['quantify_chain_decline'] {chain_id, reason, hop?} -> DECLINED. The ledger READS the trace;
    it never re-derives chain firing (the chain engine already emits its decline enum, D7)."""
    if (fired is None) == (decline is None):
        raise ValueError("chain_record: supply exactly one of fired or decline")
    if fired is not None:
        hops = _chain_hops(fired)
        quantified = [h for h in hops if "collapsed_into" not in h]  # collapsed originals are not hops
        return PatternRecord(
            record_kind=KIND_CHAIN, contract=contract, driver_or_chain_id=chain_id, as_of_date=asof,
            verdict=VERDICT_FIRED, n_hops=len(quantified), n_rows=int(fired.get("n_rows") or 0),
            grain=fired.get("grain"),
            extra=_extra({"window": fired.get("window"),
                          "path": " -> ".join(str(h.get("node")) for h in quantified if h.get("node"))}),
            engine_version=ctx.engine_version, graph_version=ctx.graph_version,
            provenance=ctx.provenance, run_id=ctx.run_id, written_at=ctx.written_at)
    reason = decline.get("reason")
    if reason not in CHAIN_DECLINE_REASONS:
        raise ValueError(f"unknown chain decline reason {reason!r} (want {sorted(CHAIN_DECLINE_REASONS)})")
    return PatternRecord(
        record_kind=KIND_CHAIN, contract=contract, driver_or_chain_id=chain_id, as_of_date=asof,
        verdict=VERDICT_DECLINED, decline_reason=reason, n_rows=0,
        extra=_extra({"hop": decline.get("hop")}),
        engine_version=ctx.engine_version, graph_version=ctx.graph_version,
        provenance=ctx.provenance, run_id=ctx.run_id, written_at=ctx.written_at)


# ── pace decline re-derivation (net-new logic; DUPLICATES cascade._pace_legs gates, F6) ───────────
def classify_pace_decline(pace_rec: Optional[dict], row: Optional[dict], *,
                          scope_skipped: bool = False) -> str:
    """Re-derive the pace decline REASON by replaying cascade._pace_legs' inline gates on the resolved
    leg record. This is NET-NEW logic that DUPLICATES the engine's inline `continue`s (there is no
    importable predicate -- they are inline in _pace_legs, F6), so it carries DRIFT RISK; the sweep uses
    it ONLY to name the reason among declines, NEVER to decide fired/declined (that is the engine's own
    verdict, read from trace-key presence). A drift-detection test pins the two in agreement (plan 6.2).

    Gate order mirrors cascade._pace_legs at HEAD:
      SKIP_NODE region      -> region_unresolved  (cascade._scope returned SKIP_NODE)
      status != ok          -> fetch_error        (~cascade.py L795)
      grain is None         -> annual_grain        (MY / event-flag; ~L798-800, cascade._pace_grain)
      _pace_series ([],None) -> cross_section_undeclared (undeclared multi-row period; ~L766-767)
      len(vals) < MIN_STREAK_N -> thin_history     (< 2 collapsed periods; ~L805-806)
    """
    from leviathan.graphrag.numbers import cascade as casc
    from leviathan.graphrag.numbers import stats as st
    if scope_skipped:
        return PACE_DECLINE_REGION
    if not pace_rec or pace_rec.get("status") != "ok":
        return PACE_DECLINE_FETCH
    grain = casc._pace_grain(row) if row else None
    if grain is None:
        return PACE_DECLINE_ANNUAL
    vals, _collapsed = casc._pace_series(pace_rec, (row or {}).get("table"))
    if not vals:
        return PACE_DECLINE_XSECTION
    if len(vals) < st.MIN_STREAK_N:
        return PACE_DECLINE_THIN
    # A record that passes every gate would have FIRED -- the caller must not reach here on a fire (the
    # fired/declined split is the engine's verdict, read from the quantify_pace trace, not re-derived).
    return PACE_DECLINE_THIN


# ── backfill eligibility + grid (plan sec 3.1 / 3.4) ──────────────────────────────────────────────
def backfill_eligible(tables: Iterable[Optional[str]]) -> bool:
    """A surface is backfill-eligible iff EVERY leg reads a table whose as-of axis is GENUINE:

      * a leg in LEAKY_ASOF_TABLES  -> EXCLUDED. The table carries a release_date axis but the axis is
        SYNTHESIZED in code, so a past-asof replay reads values that were not knowable at T. Checked
        FIRST, so membership in VINTAGED_TABLES cannot re-admit it (W4-writer / SV-L2-N2).
      * a leg in LATEST_ONLY_TABLES -> EXCLUDED. Period-partitioned latest-only (oni / weather_z): one
        value per year_month = TODAY's value, possibly rebuilt since T (plan sec 3.1 / F2).
      * a leg NOT in VINTAGED_TABLES -> EXCLUDED. Unknown/None fails CLOSED.

    The backfill records only verdicts it can honestly replay from vintage."""
    seen = False
    for t in tables:
        seen = True
        if t in LEAKY_ASOF_TABLES:
            return False   # synthesized as-of axis -- a replay reads values not knowable at T
        if t in LATEST_ONLY_TABLES:
            return False
        if t not in VINTAGED_TABLES:
            return False
    return seen  # an empty leg set is NOT eligible (nothing vintaged to replay)


def weekly_backfill_grid(end: str, years: int = 3) -> list[str]:
    """A BOUNDED weekly grid of pinned asofs over the last ~`years` (default 3; plan sec 3.4 says ~3-5,
    the exact list is a soak-gate fill-in, sec 8). Weekly cadence, most-recent first, ISO YYYY-MM-DD.
    NOT deep history (marginal value decays, cost grows)."""
    end_d = _dt.date.fromisoformat(end)
    n = max(1, int(round(years * 52)))
    return [(end_d - _dt.timedelta(weeks=i)).isoformat() for i in range(n)]


# ── the WRITE-GUARD (plan sec 2.3 / F1 + COVERAGE_AND_CAPACITY_PLAN W6 / sec E) ───────────────────
REFUSE_CROSS_VERSION = "cross_version"
REFUSE_CROSS_PROVENANCE = "cross_provenance"


@dataclass
class WriteGuardResult:
    writable: list[PatternRecord]   # rows that may be published (new or a same-version idempotent replace)
    refused: list[dict]             # refused overwrite attempts -> ALARM, never a silent rewrite

    @property
    def cross_provenance(self) -> list[dict]:
        """The refusals that would have DESTROYED another provenance class's partition (sec E)."""
        return [r for r in self.refused if r.get("refusal") == REFUSE_CROSS_PROVENANCE]

    @property
    def cross_version(self) -> list[dict]:
        return [r for r in self.refused if r.get("refusal") == REFUSE_CROSS_VERSION]


def _asof_str(v: Any) -> Optional[str]:
    """Normalize a partition value to the 'YYYY-MM-DD' string the incoming records key on. Defence in
    depth: read_existing_guard_rows already normalizes, but a pg date/timestamp arriving by any other
    route would otherwise miss the guard_key and the occupancy map -- i.e. fail OPEN."""
    return None if v is None else str(v)[:10]


def _existing_key(r: Any) -> tuple:
    if isinstance(r, PatternRecord):
        return r.guard_key()
    return (r["record_kind"], r["contract"], r["driver_or_chain_id"],
            _asof_str(r.get("as_of_date") or r.get(PARTITION_COL)), r["provenance"])


def _as_existing(rows: Iterable[Any]) -> dict[tuple, dict]:
    """Index existing rows (PatternRecord or plain dicts) by guard_key -> {engine_version, graph_version}."""
    out: dict[tuple, dict] = {}
    for r in rows:
        if isinstance(r, PatternRecord):
            ev, gv = r.engine_version, r.graph_version
        else:
            ev, gv = r.get("engine_version"), r.get("graph_version")
        out[_existing_key(r)] = {"engine_version": ev, "graph_version": gv}
    return out


def _occupancy(rows: Iterable[Any]) -> dict[str, set]:
    """asof -> the set of provenance classes ALREADY holding rows at that asof. The partition-level
    fact the cross-provenance refusal keys on (one physical object per asof, sec E)."""
    out: dict[str, set] = {}
    for r in rows:
        if isinstance(r, PatternRecord):
            asof, prov = r.as_of_date, r.provenance
        else:
            asof = _asof_str(r.get("as_of_date") or r.get(PARTITION_COL))
            prov = r.get("provenance")
        if asof is None or prov is None:
            continue
        out.setdefault(str(asof), set()).add(str(prov))
    return out


def apply_write_guard(existing: Iterable[Any], incoming: Iterable[PatternRecord]) -> WriteGuardResult:
    """Enforce the write-guard over a partition re-publish. TWO independent refusals, checked in order.

    (1) CROSS-PROVENANCE, at the PARTITION level (COVERAGE_AND_CAPACITY_PLAN sec E -- this one has
        ALREADY DESTROYED DATA). If the target asof holds rows of ANY OTHER provenance class, every
        incoming record at that asof is REFUSED. The old guard read `WHERE provenance = <target>`, so a
        backfill_grid write at an asof holding daily_sweep rows saw NOTHING in the way and proceeded as
        a "first write":

            2026-07-25 08:35:31Z  daily_sweep  created as_of_date=2026-07-25 (object feca06a0..., engine ...4dd0860b)
            2026-07-25 09:03:40Z  backfill_grid wrote the SAME canonical key (object 2e5222a4..., engine ...8e63f381)
                                  and the publisher recorded it as "existing / exact managed match"
            today                 the ledger holds ZERO daily_sweep rows

        The engine_version ALSO differed, which is precisely the condition (2) exists to catch -- the
        provenance filter meant (2) never got to see it. provenance CANNOT be additive here: the layout
        is ONE OBJECT PER ASOF and provenance is a physical column, not a partition key, so a
        second-class write is a read-modify-write of a certified canonical object. Refuse it. The
        sanctioned move is a DIFFERENT asof, or a shadow prefix.

    (2) CROSS-VERSION, per guard_key (plan sec 2.3 / F1):
      * a key ABSENT from `existing` -> writable (a fresh record);
      * a key PRESENT with the SAME engine_version + graph_version -> writable (a same-code retry /
        same-day repair is an IDEMPOTENT replace, never a duplicate -- one row per guard_key);
      * a key PRESENT with a DIFFERENT engine_version or graph_version -> REFUSED + alarmed: overwriting
        it would rewrite the T-verdict with LATER CODE (a retroactive code-recompute, non-goal 6).

    `existing` MUST come from a read that spans ALL provenance classes at the target asofs -- that is
    what read_existing_guard_rows now does. Passing a provenance-filtered read back into this function
    silently disarms (1)."""
    idx = _as_existing(existing)
    occupied = _occupancy(existing)
    writable: list[PatternRecord] = []
    refused: list[dict] = []
    for rec in incoming:
        foreign = sorted(occupied.get(rec.as_of_date, set()) - {rec.provenance})
        if foreign:
            refused.append({
                "refusal": REFUSE_CROSS_PROVENANCE,
                "guard_key": rec.guard_key(),
                "as_of_date": rec.as_of_date,
                "incoming_provenance": rec.provenance,
                "stored_provenance": foreign,
                "stored_engine_version": (idx.get(rec.guard_key()) or {}).get("engine_version"),
                "incoming_engine_version": rec.engine_version,
                "stored_graph_version": (idx.get(rec.guard_key()) or {}).get("graph_version"),
                "incoming_graph_version": rec.graph_version,
                "reason": f"CROSS-PROVENANCE overwrite REFUSED: as_of_date={rec.as_of_date} already holds "
                          f"{foreign} rows and the layout is ONE OBJECT PER ASOF (provenance is a column, "
                          f"NOT a partition key), so writing provenance={rec.provenance} here would "
                          f"DESTROY them -- this is exactly what happened on 2026-07-25 09:03Z. Publish "
                          f"the re-derivation at a different asof or to a shadow prefix; never in place.",
            })
            continue
        prior = idx.get(rec.guard_key())
        if prior is None:
            writable.append(rec)
            continue
        if prior.get("engine_version") == rec.engine_version and prior.get("graph_version") == rec.graph_version:
            writable.append(rec)  # idempotent same-version replace
            continue
        refused.append({
            "refusal": REFUSE_CROSS_VERSION,
            "guard_key": rec.guard_key(),
            "as_of_date": rec.as_of_date,
            "incoming_provenance": rec.provenance,
            "stored_provenance": [rec.provenance],
            "stored_engine_version": prior.get("engine_version"),
            "incoming_engine_version": rec.engine_version,
            "stored_graph_version": prior.get("graph_version"),
            "incoming_graph_version": rec.graph_version,
            "reason": "engine_version/graph_version write-guard: refusing to overwrite a T-verdict under "
                      "changed code; re-derive as a fresh backfill_grid row, never in place (F1)",
        })
    return WriteGuardResult(writable=writable, refused=refused)


def _sql_lit(v: str) -> str:
    """Single-quote-safe SQL literal (mirrors query._q / pattern_records._q)."""
    return "'" + str(v).replace("'", "''") + "'"


class GuardReadError(RuntimeError):
    """The write-guard could not READ the existing ledger rows, so it cannot know what it would
    overwrite. NOT the same as "there is nothing there" -- and the publish MUST abort (W6.i)."""


class GuardStaleMirrorError(RuntimeError):
    """The mirror READ SUCCEEDED and returned nothing, but S3 says those asofs are occupied.

    The third failure mode, and the one that actually bit (2026-07-29): the mirror is READABLE,
    the table EXISTS, the query is well-formed -- and it is simply BEHIND. The pg loader for this
    ledger runs on demand, and had not run since 2026-07-24, so every asof written after that
    date read back as empty. apply_write_guard cannot tell "no rows" from "no rows YET", so a
    backfill_grid replay was licensed straight over a certified daily_sweep partition, exactly
    the class of damage the guard exists to prevent -- and every daily partition written since
    the last load had been silently unprotected the whole time.

    W6.i's failure policy covered unreadable and missing-table. It did not cover STALE, because
    stale looks identical to empty from inside pg. S3 is the authority on occupancy (the layout
    is one object per asof), so the cross-check is cheap and exact: if pg claims an asof is empty
    while its canonical object exists, the guard's picture is WRONG and the publish aborts."""


def _is_missing_ledger_table(exc: BaseException) -> bool:
    """Is this pg error 'the ledger table does not exist yet' -- a LEGITIMATE first write / flip day --
    as opposed to 'the read FAILED' (mirror gap, dead connection, timeout, permission, syntax)?

    The old code could not tell them apart: it swallowed EVERY exception and returned [], which
    apply_write_guard reads as "first write" and therefore "everything is writable". A single pg blip
    during a re-publish was a silent full overwrite of a certified canonical partition. Only the
    narrow, positively-identified missing-table case may fail open; everything else raises.

    "Undefined table" is recognised three ways, so the classification never depends on a driver import:
      * the psycopg exception CLASS (psycopg2.errors.UndefinedTable / psycopg.errors.UndefinedTable);
      * SQLSTATE 42P01 (undefined_table) off `.pgcode` or `.diag.sqlstate`, whichever the driver sets;
      * the message text ('does not exist' / 'no such table').

    ALL THREE are then AND-ed with "and the message names OUR table". That conjunction is load-bearing
    and was missing: psycopg raises UndefinedTable/42P01 for ANY missing relation, so the class and
    SQLSTATE tests are table-BLIND on their own and a missing *different* relation -- somebody else's
    schema problem -- used to fail open into "everything is writable". Requiring the table name is the
    only scoped signal available, and anything unrecognised now raises instead, which is the safe
    direction: an unreadable guard MUST abort, never assume an empty partition.
    """
    msg = str(exc).lower()
    if TABLE.lower() not in msg:
        return False
    if "undefinedtable" in type(exc).__name__.lower():
        return True
    code = getattr(exc, "pgcode", None) or getattr(getattr(exc, "diag", None), "sqlstate", None)
    if code == "42P01":
        return True
    return "does not exist" in msg or "no such table" in msg


def detect_stale_mirror(existing: Iterable[dict], asofs: Iterable[str], *, bucket: Optional[str],
                        s3_client=None) -> list[str]:
    """The asofs pg calls EMPTY whose canonical S3 object EXISTS -- i.e. proof the mirror is behind.

    Returns [] when the mirror's picture is consistent with S3, which is the only state in which
    apply_write_guard's refusals mean anything. See GuardStaleMirrorError for why this is a third,
    distinct failure mode from unreadable and missing-table.

    Only pg-EMPTY asofs are probed, so a current mirror costs ZERO calls and the worst case is one
    HEAD per target asof. A missing bucket is NOT silently tolerated: without it the cross-check
    cannot run at all, and a cross-check that cannot run must not be mistaken for one that passed."""
    occupied_in_pg = {str(r.get("as_of_date")) for r in (existing or []) if r.get("as_of_date")}
    candidates = sorted({a for a in asofs if a and str(a) not in occupied_in_pg})
    if not candidates:
        return []
    if not bucket:
        raise RuntimeError(
            "stale-mirror cross-check needs a bucket (--bucket or LEVIATHAN_BUCKET) and has none; "
            "refusing to treat an un-runnable cross-check as a passing one")
    if s3_client is None:
        import boto3
        s3_client = boto3.client("s3", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    stale: list[str] = []
    for asof in candidates:
        key = f"{S3_PREFIX}/{PARTITION_COL}={asof}/pattern_records.parquet"
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
        except Exception as e:  # noqa: BLE001
            # 404/NoSuchKey is the GOOD case: pg and S3 agree the asof is empty. Anything else is
            # an S3 problem, and an unverifiable occupancy picture must abort rather than pass.
            code = getattr(getattr(e, "response", None), "get", lambda *_a: {})("Error") or {}
            status = str(code.get("Code", "")) if isinstance(code, dict) else ""
            if status in ("404", "NoSuchKey", "NotFound"):
                continue
            raise
        stale.append(asof)
    return stale


def read_existing_guard_rows(query_fn, asofs: Iterable[str]) -> list[dict]:
    """Read the guard-key columns of EVERY existing ledger row at the target asofs from the pg mirror, so
    apply_write_guard can (a) refuse a cross-provenance partition overwrite and (b) compare
    engine_version/graph_version BEFORE a re-publish rewrites a T-verdict.

    ACROSS ALL PROVENANCE CLASSES -- the `WHERE provenance = <target>` predicate this function used to
    carry is the defect in COVERAGE_AND_CAPACITY_PLAN sec E: on 2026-07-25 a backfill_grid run asked
    "are there any backfill_grid rows at 2026-07-25?", got no, and overwrote the daily_sweep partition
    written 28 minutes earlier. The guard cannot refuse what it does not read. provenance stays in the
    SELECT list because it is part of the guard_key and of the occupancy map.

    pg-ONLY (the injected query_fn is pgnumbers.pg_query) -- a mirror gap is NEVER a silent Athena
    round-trip. The partition value is normalized to the 'YYYY-MM-DD' string the incoming records key on
    (a pg date object / timestamp text would otherwise never match the guard_key, silently PASSING an
    overwrite).

    FAILURE POLICY (W6.i): a positively-identified MISSING TABLE -> [] (a first write is never blocked).
    ANY OTHER read failure -> GuardReadError. Returning [] on an unreadable mirror is indistinguishable
    from "the partition is empty" and licences a full overwrite."""
    asof_list = sorted({a for a in asofs if a})
    if not asof_list:
        return []
    in_list = ", ".join(_sql_lit(a) for a in asof_list)
    # PG_TABLE, not TABLE -- schema-qualified. An unqualified name does not resolve on the mirror's
    # default search_path and made this entire guard a no-op; see the PG_TABLE definition.
    sql = (f"SELECT record_kind, contract, driver_or_chain_id, {PARTITION_COL}, provenance, "
           f"engine_version, graph_version FROM {PG_TABLE} "
           f"WHERE substr(cast({PARTITION_COL} as varchar), 1, 10) IN ({in_list})")
    try:
        rows = list(query_fn(sql) or [])
    except Exception as e:  # noqa: BLE001 -- classify; never Athena, never a blanket swallow
        if _is_missing_ledger_table(e):
            logger.warning("write-guard: %s does not exist (%s) -- treating as a FIRST WRITE", TABLE, str(e)[:200])
            return []
        raise GuardReadError(
            f"write-guard could not read existing rows for asofs={asof_list[:5]}"
            f"{'...' if len(asof_list) > 5 else ''}: {type(e).__name__}: {str(e)[:300]}. ABORTING the "
            f"publish -- an unreadable guard cannot distinguish 'nothing there' from 'could not look', "
            f"and proceeding would overwrite a certified partition (W6.i)") from e
    for r in rows:
        av = r.get("as_of_date")  # PARTITION_COL == "as_of_date"; the SELECT aliases the column to this key
        r["as_of_date"] = str(av)[:10] if av is not None else None
    return rows


# ── live engine-replay drivers (pg-only; not exercised by the unit suite, which feeds fixtures) ────
@dataclass
class _EngineVerdict:
    """A raw per-pair verdict emitted by a live driver, converted to a PatternRecord by _to_record."""

    kind: str
    contract: str
    driver_or_chain_id: str
    fired: bool
    tables: tuple = ()
    n_rows: int = 0
    pace_entry: Optional[dict] = None
    decline_reason: Optional[str] = None
    chain_fired: Optional[dict] = None
    chain_decline: Optional[dict] = None
    cascade_table: Optional[str] = None
    cascade_metric: Optional[str] = None


def _pace_capable(row: Optional[dict]) -> bool:
    """Is this mapped map-row a PACE-kind surface -- leg_mode=current AND a sub-annual pace grain? Such a
    (driver, contract) pair belongs to the PACE kind, NOT the cascade kind: the one-kind-per-pair partition
    (plan F3 / sec 8 cap). This is the SINGLE predicate that cascade_verdicts uses to EXCLUDE the pair and
    _pace_pairs uses to SELECT it, so the two kinds can never double-count a pair (which would trip the
    duplication alarm and understate the ~600-row cost model) nor drop one between them."""
    from leviathan.graphrag.numbers import cascade as casc
    if not row:
        return False
    return row.get("leg_mode") == "current" and casc._pace_grain(row) is not None


def cascade_verdicts(asof: str, query_fn) -> list[_EngineVerdict]:
    """The cascade-kind spine: replay cascade_census over the mapped catalog and convert each NON-pace leg
    verdict (FIRES / DARK-WITH-REASON / DECLINES-HONESTLY / probe-error) to a cascade verdict. Reuses the
    census wholesale (map_row/_scope/_region_row + the pg row-existence probe) -- the exact production
    helpers. PACE-capable legs (leg_mode=current + a sub-annual grain) are EXCLUDED: they are PACE-kind pairs
    recorded by pace_verdicts, so each (driver, contract) pair is recorded under EXACTLY ONE record_kind (the
    one-kind-per-pair partition -- plan F3; double-recording a pair as both cascade and pace would trip the
    sec-8 duplication cap and understate the cost model)."""
    from leviathan.graphrag.numbers import cascade as casc
    from leviathan.graphrag.numbers import cascade_census as cc
    art = cc.census(asof=asof, query_fn=query_fn)
    out: list[_EngineVerdict] = []
    for leg in art.get("legs", []):
        if _pace_capable(casc.map_row(leg.get("silver_ref"))):
            continue                                 # a PACE-kind pair -> recorded by pace_verdicts, not here
        v = leg.get("verdict")
        fired = v == cc.FIRES
        reason = None
        if not fired:
            if v == cc.DARK:
                reason = leg.get("reason")
            elif v == cc.PROBE_ERROR:
                reason = "probe-error"
            elif v == cc.DECLINES:
                reason = "region-unresolved" if leg.get("reason") == "region-unresolved" else "waived"
            reason = reason if reason in CASCADE_DECLINE_REASONS else "metric-empty-for-country"
        out.append(_EngineVerdict(
            kind=KIND_CASCADE, contract=leg["contract"], driver_or_chain_id=leg["node_id"],
            fired=fired, n_rows=1 if fired else 0, decline_reason=reason,
            cascade_table=leg.get("table"), cascade_metric=leg.get("metric"),
            tables=(leg.get("table"),) if leg.get("table") else ()))
    return out


def _pace_pairs() -> Iterator[tuple]:
    """(contract, driver, map_row) for every pace-CAPABLE leg (leg_mode=current + a sub-annual grain).
    Enumerated from the causal YAMLs via the census contract index -- the same node set the engine walks."""
    from leviathan.graphrag.numbers import cascade as casc
    from leviathan.graphrag.numbers import cascade_census as cc
    for contract, c in sorted(cc._contract_index().items()):
        for d in c.drivers:
            row = casc.map_row(d.silver_ref)
            if not _pace_capable(row):               # the SAME predicate cascade_verdicts EXCLUDES on (F3)
                continue
            yield contract, d, row


def pace_verdicts(asof: str, query_fn) -> list[_EngineVerdict]:
    """Replay the pace leg for every pace-capable pair through the REAL cascade helpers (_node_specs /
    _run_one / _pace_legs), read the fired entry from the engine's own quantify_pace output, and classify
    a decline reason when it does not fire."""
    from leviathan.graphrag.numbers import cascade as casc
    from leviathan.graphrag.numbers import cascade_census as cc
    out: list[_EngineVerdict] = []
    for contract, d, row in _pace_pairs():
        node = cc._LegNode(contract, d.id, d.silver_ref, d.region)
        try:
            commodity, country = casc._scope(node, row)
        except Exception:  # noqa: BLE001
            out.append(_EngineVerdict(KIND_PACE, contract, d.id, False, decline_reason=PACE_DECLINE_FETCH))
            continue
        if country is casc.SKIP_NODE:
            out.append(_EngineVerdict(KIND_PACE, contract, d.id, False, decline_reason=PACE_DECLINE_REGION))
            continue
        row2 = casc._region_row(node, row)
        table = row2.get("table")
        try:
            specs = casc._node_specs(node, row2, commodity, country, [], asof, pace=True)
            records = [casc._run_one(query_fn, s) for s in specs]
            kept = [{"specs": specs, "row": row2, "node": node, "commodity": commodity,
                     "contract": contract, "country": country, "eras": []}]
            _lines, trace = casc._pace_legs(records, kept, 0, [])
        except Exception as e:  # noqa: BLE001 -- a resolution/fetch failure is a fetch_error verdict
            logger.warning("pace replay failed for %s/%s: %s", contract, d.id, e)
            out.append(_EngineVerdict(KIND_PACE, contract, d.id, False, decline_reason=PACE_DECLINE_FETCH,
                                      tables=(table,) if table else ()))
            continue
        if trace:  # the ENGINE's own verdict: quantify_pace non-empty == fired
            entry = trace[0]
            out.append(_EngineVerdict(KIND_PACE, contract, d.id, True, pace_entry=entry,
                                      n_rows=len(_lines), tables=(table,) if table else ()))
        else:
            pace_rec = next((r for r in records if (r.get("leg") or (None,))[0] == "pace"), None)
            reason = classify_pace_decline(pace_rec, row2)
            out.append(_EngineVerdict(KIND_PACE, contract, d.id, False, decline_reason=reason,
                                      tables=(table,) if table else ()))
    return out


def chain_verdicts(asof: str, query_fn, *, trace_provider: Optional[Callable[[str, str], dict]] = None
                   ) -> list[_EngineVerdict]:
    """Record the chain kind from day one (plan sec 5 / D9). A chain FIRE depends on the WALK grounding
    the root from the evidence store, which is NOT vintage-partitioned and NOT replayable from the
    catalog alone (plan sec 3.2) -- so a pure daily catalog replay honestly DECLINES most chains
    (root_not_grounded). When a `trace_provider(contract, asof) -> sg.trace` is injected (the serving
    respond seam in the cloud, or a fixture in tests), the sweep READS the engine's own
    quantify_chain / quantify_chain_decline keys instead (the trace-key-present-iff-fired contract)."""
    from leviathan.graphrag.numbers import cascade as casc
    try:
        chains = casc.load_chain_map() or []
    except Exception:  # noqa: BLE001
        return []
    out: list[_EngineVerdict] = []
    for chain in chains:
        if chain.get("deferred"):
            continue
        cid = chain.get("id")
        for contract in (chain.get("contracts") or []):
            trace = {}
            if trace_provider is not None:
                try:
                    trace = trace_provider(contract, asof) or {}
                except Exception:  # noqa: BLE001
                    trace = {}
            fired = trace.get("quantify_chain")
            decline = trace.get("quantify_chain_decline")
            if fired and fired.get("chain_id") == cid:
                out.append(_EngineVerdict(KIND_CHAIN, contract, cid, True, chain_fired=fired))
            elif decline and decline.get("chain_id") == cid:
                out.append(_EngineVerdict(KIND_CHAIN, contract, cid, False, chain_decline=decline))
            else:
                # pure catalog replay, no grounding walk -> the honest deterministic verdict.
                out.append(_EngineVerdict(KIND_CHAIN, contract, cid, False,
                                          chain_decline={"chain_id": cid, "reason": "root_not_grounded"}))
    return out


def _to_record(v: _EngineVerdict, asof: str, ctx: RunContext) -> PatternRecord:
    """Convert a live driver's raw verdict to a PatternRecord via the tested pure builders."""
    if v.kind == KIND_PACE:
        if v.fired:
            return pace_record(v.contract, v.driver_or_chain_id, asof, ctx, entry=v.pace_entry, n_rows=v.n_rows)
        return pace_record(v.contract, v.driver_or_chain_id, asof, ctx, decline_reason=v.decline_reason)
    if v.kind == KIND_CHAIN:
        if v.fired:
            return chain_record(v.contract, v.driver_or_chain_id, asof, ctx, fired=v.chain_fired)
        return chain_record(v.contract, v.driver_or_chain_id, asof, ctx, decline=v.chain_decline)
    return cascade_record(v.contract, v.driver_or_chain_id, asof, ctx, fired=v.fired,
                          decline_reason=v.decline_reason, n_rows=v.n_rows,
                          table=v.cascade_table, metric=v.cascade_metric)


def sweep(asof: str, query_fn, ctx: RunContext, *,
          kinds: Iterable[str] = V1_KINDS,
          trace_provider: Optional[Callable[[str, str], dict]] = None,
          backfill_only_vintaged: bool = False) -> list[PatternRecord]:
    """Produce the day's (or a grid asof's) records across the v1 kinds. When
    `backfill_only_vintaged` (the backfill grid), a verdict is recorded ONLY if its surface is
    backfill-eligible (every leg reads a release-date-vintaged table); oni/weather_z-legged surfaces are
    EXCLUDED and left to accrue daily-sweep-only (plan sec 3.1 / 3.4 / F2).

    W3: on the DAILY path (ctx.provenance == daily_sweep) the kind set is narrowed to DAILY_SWEEP_KINDS
    = {pace} -- see that constant for the measured justification and for where the cascade/chain
    resolvability pictures live instead. The narrowing keys on ctx.provenance, NOT on the --kinds CLI
    argument, so it cannot be lost by an invocation that passes --kinds (the deployed jobdef passes
    none, and the default is all three). The BACKFILL path is untouched."""
    kinds = set(kinds)
    if ctx.provenance == PROV_DAILY_SWEEP:
        dropped = kinds - DAILY_SWEEP_KINDS
        kinds &= DAILY_SWEEP_KINDS
        if dropped:
            logger.info("W3: daily sweep records %s only -- dropping %s (cascade rows are constant-valued "
                        "catalog-existence flags, chain rows are 100%% root_not_grounded without a "
                        "trace_provider; both pictures live in cascade_census / config_check.check_chain_map, "
                        "not in a citable ledger)", sorted(DAILY_SWEEP_KINDS), sorted(dropped))
    verdicts: list[_EngineVerdict] = []
    if KIND_CASCADE in kinds:
        verdicts += cascade_verdicts(asof, query_fn)
    if KIND_PACE in kinds:
        verdicts += pace_verdicts(asof, query_fn)
    if KIND_CHAIN in kinds:
        verdicts += chain_verdicts(asof, query_fn, trace_provider=trace_provider)
    records: list[PatternRecord] = []
    for v in verdicts:
        if backfill_only_vintaged and not backfill_eligible(v.tables):
            continue
        records.append(_to_record(v, asof, ctx))
    return records


# ── publish (F015 shadow-first, F013 REGISTERED strategy) ─────────────────────────────────────────
def build_staged_objects(records: list[PatternRecord], contract: dict) -> list:
    """One StagedObject per as_of_date partition (partition_values=[asof]); the day's rows encoded to
    parquet via the registry contract schema. Registered-partition publish -> each partition carries an
    explicit Glue location (never projection; the LIST-storm discipline)."""
    import pandas as pd
    from leviathan.silver.flat_producer import encode_parquet
    from leviathan.silver.publisher import StagedObject
    by_asof: dict[str, list[dict]] = {}
    for r in records:
        by_asof.setdefault(r.as_of_date, []).append(r.row())
    objects = []
    for asof in sorted(by_asof):
        rows = by_asof[asof]
        df = pd.DataFrame(rows, columns=list(COLUMNS) + [PARTITION_COL])
        df = df.drop(columns=[PARTITION_COL])  # the partition value lives in the path, not the parquet
        # written_at is a timestamp[us] column (contract target): coerce the ISO strings to tz-naive UTC
        # datetimes so pyarrow writes the physical INT64 timestamp (a raw str would fail the cast).
        df["written_at"] = pd.to_datetime(df["written_at"], utc=True, errors="coerce").dt.tz_localize(None)
        for _int_col in ("streak_len", "n_points", "n_rows", "n_hops"):
            df[_int_col] = df[_int_col].astype("Int64")  # nullable int64 (None -> <NA>, never a float cast)
        body = encode_parquet(df, contract)
        key = f"{S3_PREFIX}/{PARTITION_COL}={asof}/pattern_records.parquet"
        objects.append(StagedObject(canonical_key=key, body=body, partition_values=[asof],
                                    row_count=len(rows)))
    return objects


def publish(records: list[PatternRecord], contract: dict, *, bucket: str, s3_client, glue_client, auth,
            run_id: str, code_sha: Optional[str] = None, shadow_prefix: Optional[str] = None):
    """Publish the day's partitions through the F015 ShadowPublisher + the F013 REGISTERED strategy. No
    canonical mutation unless auth.may_mutate_canonical (dry-run/shadow leave every partition PLANNED)."""
    from leviathan.silver.publisher import (PublishStrategy, ShadowPublisher, StagedObject,  # noqa: F401
                                            ValidationHooks)
    objects = build_staged_objects(records, contract)
    publisher = ShadowPublisher(
        job="pattern_records_sweep", table=TABLE, database=DATABASE, bucket=bucket,
        canonical_root=f"s3://{bucket}/{S3_PREFIX}", auth=auth, s3_client=s3_client,
        glue_client=glue_client, strategy=PublishStrategy.REGISTERED, shadow_prefix=shadow_prefix,
        validation=ValidationHooks(min_rows=1, min_nonnull_frac=0.0),
        code_sha=code_sha, registry_schema_version=int(contract.get("schema_version") or 1), run_id=run_id)
    return publisher.run(objects)


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────────
def _assert_pg_only() -> None:
    """pg-ONLY BY CONSTRUCTION (the cascade_census discipline): the sweep is an engine replay over the pg
    mirror; a mirror gap is a probe-error verdict, NEVER a silent Athena round-trip (the ZERO-Athena /
    LIST-storm rule). A pg-dead run would read an empty ledger and false-negative every persistence claim
    (the 2026-07-23 phantom-regression class), so refuse to run without the full serving pg env."""
    from leviathan.graphrag.numbers import pgnumbers
    backend = os.environ.get("GRAPHRAG_NUMBERS_BACKEND", "").strip().lower()
    assert backend == "pg", "pattern_records_sweep requires GRAPHRAG_NUMBERS_BACKEND=pg (pg-mirror only)"
    assert os.environ.get("EVIDENCE_PG_DSN"), "pattern_records_sweep requires EVIDENCE_PG_DSN"
    assert pgnumbers.enabled(), "pattern_records_sweep requires pgnumbers.enabled() (backend=pg + DSN)"


def _load_contract() -> dict:
    from leviathan.silver.registry import load_registry
    return load_registry().table(TABLE)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    ap = argparse.ArgumentParser(description="T2B pattern-records ledger: daily sweep / backfill grid.")
    ap.add_argument("--asof", default=None, help="sweep as-of (YYYY-MM-DD); default = today UTC")
    ap.add_argument("--backfill", action="store_true",
                    help="run the bounded weekly grid over vintaged-leg surfaces (provenance=backfill_grid)")
    ap.add_argument("--backfill-years", type=float, default=3.0, help="backfill grid depth in years (~3-5)")
    ap.add_argument("--kinds", default=",".join(sorted(V1_KINDS)),
                    help="comma list of record kinds to sweep (v1: cascade,pace,chain). The DAILY path "
                         f"records {sorted(DAILY_SWEEP_KINDS)} regardless (W3); --kinds only narrows.")
    ap.add_argument("--dry-run", action="store_true", help="build records + print counts; write NOTHING")
    ap.add_argument("--publish-mode", default="dry-run", help="dry-run (default) | shadow | canonical")
    ap.add_argument("--shadow-prefix", default=None, dest="shadow_prefix")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--json", dest="out", default=None, help="also write the built records to this path")
    args = ap.parse_args(argv)

    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    asof = args.asof or today
    # (F4) a daily_sweep row MUST be written at its OWN asof=today. A non-backfill sweep at a BACKDATED asof
    # would record provenance=daily_sweep rows from TODAY's data -- and oni/weather_z are period LATEST-ONLY,
    # so a past asof reads RESTATED values -- stamped written_at=now. Such a row PASSES the serving PIT guard
    # (presence_sql: written_at<=asof AND as_of_date<=asof) at a today-asof query and leaks a backdated
    # as_of_date into the daily_sweep base rate / streak. The sanctioned past-asof replay is the BACKFILL path
    # (vintaged legs only, provenance=backfill_grid). Refuse here, before any pg/AWS work (plan sec 3.1 / F4).
    if not args.backfill and asof != today:
        logger.error("REFUSING a daily_sweep at a past asof %s (today=%s): a non-backfill sweep must run at "
                     "asof=today; use --backfill for a past-asof grid (vintaged legs only) -- plan sec 3.1/F4.",
                     asof, today)
        return 2

    from leviathan.common.config import load_env
    load_env()
    _assert_pg_only()
    from leviathan.graphrag.numbers import pgnumbers
    query_fn = pgnumbers.pg_query

    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    engine_version = resolve_engine_version()
    graph_version = resolve_graph_version()
    provenance = PROV_BACKFILL_GRID if args.backfill else PROV_DAILY_SWEEP
    run_id = f"{TABLE}-{provenance}-{int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1000)}"
    ctx = RunContext(engine_version=engine_version, graph_version=graph_version,
                     provenance=provenance, run_id=run_id)

    asofs = weekly_backfill_grid(asof, years=args.backfill_years) if args.backfill else [asof]
    records: list[PatternRecord] = []
    for a in asofs:
        recs = sweep(a, query_fn, ctx, kinds=kinds, backfill_only_vintaged=args.backfill)
        records += recs
        logger.info("swept asof=%s kinds=%s -> %d record(s)", a, sorted(kinds), len(recs))

    fired = sum(1 for r in records if r.verdict == VERDICT_FIRED)
    by_kind = {k: sum(1 for r in records if r.record_kind == k) for k in sorted(kinds)}
    logger.info("built %d record(s): fired=%d declined=%d by_kind=%s provenance=%s engine=%s graph=%s",
                len(records), fired, len(records) - fired, by_kind, provenance, engine_version, graph_version)

    if args.out:
        from pathlib import Path
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps([r.row() for r in records], indent=1), encoding="utf-8")

    # (F1 + W6 + sec E) the WRITE-GUARD, ENFORCED AT RUNTIME. Read EVERY existing ledger row at the target
    # asofs -- ACROSS ALL PROVENANCE CLASSES, which is the sec-E fix -- and refuse two things: a
    # cross-PROVENANCE partition overwrite (the layout is one object per asof; provenance is a column, so a
    # second class DESTROYS the first -- it did on 2026-07-25 09:03Z), and a cross-VERSION overwrite of a
    # T-verdict under changed code (non-goal 6). Refusals ALARM (loud ERROR lines, never a silent rewrite)
    # and ONLY the writable set is published. A positively-identified MISSING TABLE reads [] -> all
    # writable; ANY OTHER read failure raises GuardReadError and ABORTS (W6.i) -- proceeding on an
    # unreadable guard is how a pg blip becomes a full overwrite (publisher._promote copy_object is
    # unconditional and the pg mirror upserts on the natural key).
    try:
        existing = read_existing_guard_rows(query_fn, asofs)
    except GuardReadError as e:
        logger.error("ABORT %s", e)
        return 3
    # STALE-MIRROR CROSS-CHECK (2026-07-29 incident). A successful read that returns nothing is
    # ambiguous: the partition may be genuinely empty, or the mirror may simply be behind. S3 is
    # the authority on occupancy -- one object per asof -- so any asof pg calls empty while its
    # canonical object EXISTS means the guard is reasoning from a stale picture, and every
    # refusal it would have raised is silently disarmed. Abort instead (rc 3, same class as an
    # unreadable guard). Costs one HEAD per pg-empty asof and nothing at all when pg is current.
    # Runs BEFORE the dry-run branch: a dry-run's whole job is to predict the publish, and a
    # dry-run that green-lights a write the live run would botch is worse than no dry-run.
    try:
        stale = detect_stale_mirror(existing, asofs,
                                    bucket=args.bucket or os.environ.get("LEVIATHAN_BUCKET"))
    except Exception as e:  # noqa: BLE001 -- a cross-check that cannot run must not fail open
        logger.error("ABORT write-guard stale-mirror cross-check could not run: %s: %s",
                     type(e).__name__, e)
        return 3
    if stale:
        logger.error(
            "ABORT write-guard STALE MIRROR: pg reports ZERO rows at %d asof(s) whose canonical "
            "object EXISTS on S3 %s -- the mirror is behind (its loader is on-demand), so every "
            "guard refusal is silently disarmed and a replay would overwrite certified rows (this "
            "is the 2026-07-29 incident). Run: python jobs/utils/load_pg_numbers.py --tables %s, "
            "then re-run.", len(stale), sorted(stale)[:8], TABLE)
        return 3
    guard = apply_write_guard(existing, records)
    refused_n = len(guard.refused)
    for r in guard.cross_provenance:
        logger.error("ALARM write-guard REFUSED CROSS-PROVENANCE overwrite asof=%s stored_provenance=%s "
                     "incoming_provenance=%s key=%s -- %s",
                     r["as_of_date"], r["stored_provenance"], r["incoming_provenance"], r["guard_key"],
                     r["reason"])
    for r in guard.cross_version:
        logger.error("ALARM write-guard REFUSED cross-version overwrite key=%s stored(engine=%s graph=%s) "
                     "incoming(engine=%s graph=%s) -- re-derive as a fresh backfill_grid row, never in place",
                     r["guard_key"], r["stored_engine_version"], r["stored_graph_version"],
                     r["incoming_engine_version"], r["incoming_graph_version"])
    cross_prov_n = len(guard.cross_provenance)
    if refused_n:
        blocked = sorted({r["as_of_date"] for r in guard.cross_provenance})
        logger.error("ALARM write-guard: REFUSED %d of %d built record(s) -- %d cross-provenance over %d "
                     "asof(s) %s, %d cross-version. %s",
                     refused_n, len(records), cross_prov_n, len(blocked), blocked[:8],
                     len(guard.cross_version),
                     "ABORTING the whole publish (cross-provenance)." if cross_prov_n
                     else f"Publishing ONLY the {len(guard.writable)} writable row(s).")
    records = guard.writable
    # A cross-provenance collision is an OPERATOR error (a backfill grid overlapping asofs the daily sweep
    # already owns), not a data condition -- the run is NOT clean even though the guard prevented the
    # damage, so the WHOLE publish aborts rather than writing a silently-partial grid. The same non-zero
    # exit is returned under --dry-run, because the dry-run's whole job is to predict the publish.
    # Cross-VERSION refusals keep their historical behaviour (alarm + publish the writable remainder).

    if args.dry_run:
        logger.info("--dry-run: %d writable record(s) (%d refused by write-guard); nothing written",
                    len(records), refused_n)
        return 4 if cross_prov_n else 0
    if cross_prov_n:
        logger.error("ABORT: %d record(s) would have overwritten another provenance class's partition; "
                     "refusing the whole publish. Re-derive at a different asof or to a shadow prefix.",
                     cross_prov_n)
        return 4

    contract = _load_contract()
    import boto3
    from leviathan.common.publish_guard import PublishTarget, authorize_publish
    bucket = args.bucket or os.environ.get("LEVIATHAN_BUCKET", contract.get("s3_bucket"))
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    ident = boto3.client("sts", region_name=region).get_caller_identity()
    auth = authorize_publish(
        PublishTarget(account_id=ident["Account"], bucket=bucket, database=DATABASE,
                      prefix=f"{S3_PREFIX}/", role_arn=ident["Arn"], table=TABLE),
        argv=sys.argv if argv is None else ["--publish-mode", args.publish_mode])
    s3_client = boto3.client("s3", region_name=region)
    glue_client = boto3.client("glue", region_name=region) if auth.may_mutate_canonical else None
    manifest = publish(records, contract, bucket=bucket, s3_client=s3_client, glue_client=glue_client,
                       auth=auth, run_id=run_id, code_sha=engine_version, shadow_prefix=args.shadow_prefix)
    logger.info("publish complete: mode=%s state=%s partitions=%d",
                auth.mode.value, manifest.state.value, len({r.as_of_date for r in records}))
    from leviathan.silver.publisher import ManifestState
    return 1 if manifest.state == ManifestState.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
