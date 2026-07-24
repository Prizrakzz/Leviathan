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
  * provenance {daily_sweep, backfill_grid} -- BOTH are batch replays (today-asof vs a past-asof grid),
    NEVER a production "live" fire (there is none; serving has zero organic traffic, plan sec 3.3 / F5).
  * The backfill grid runs ONLY over surfaces whose EVERY leg reads a RELEASE-DATE-VINTAGED table
    (esr_compact / wasde / psd) -- the period LATEST-ONLY tables (silver_noaa_oni / gold_weather_z) read
    RESTATED data at a past asof, so their legs are EXCLUDED (plan sec 3.1 / F2).

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

# ── record kinds (plan sec 1.1) ──────────────────────────────────────────────────────────────────
KIND_CASCADE = "cascade"
KIND_PACE = "pace"
KIND_CHAIN = "chain"
V1_KINDS = frozenset({KIND_CASCADE, KIND_PACE, KIND_CHAIN})
# DECLARED but DEFERRED to v1.1 (F4): cross-node forks with no single driver_or_chain_id, no per-kind
# sweep loop yet. Reserved in the enum + the counterparty column; NEVER written by v1.
DEFERRED_FORK_KINDS = frozenset({"comove", "reroute", "price_leg"})

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
VINTAGED_TABLES = frozenset({
    "silver_esr_compact", "silver_esr", "silver_wasde", "silver_psd",
})
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


def resolve_graph_version() -> str:
    """The causal-graph + cascade_map content hash (the tracked-config version, plan sec 1.1). A
    deterministic sha256 over cascade_map.yaml + chain_map.yaml + the causal DAG yamls (sorted, bytes),
    so a graph edit is a distinct graph_version that the write-guard separates from a prior asof's rows."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
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
        """The natural key WITHIN a provenance class. daily_sweep and backfill_grid rows for the same
        (kind, contract, driver, asof) COEXIST (they differ by the provenance column, plan sec 2.3): the
        write-guard + idempotency operate per (natural_key, provenance), never across classes."""
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
    """A surface is backfill-eligible iff EVERY leg reads a RELEASE-DATE-VINTAGED table -- equivalently,
    NO leg reads a period LATEST-ONLY table (oni / weather_z). An unknown/None table fails closed
    (excluded): the backfill records only verdicts it can honestly replay from vintage (plan sec 3.1/F2)."""
    seen = False
    for t in tables:
        seen = True
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


# ── the engine_version WRITE-GUARD (plan sec 2.3 / F1) ────────────────────────────────────────────
@dataclass
class WriteGuardResult:
    writable: list[PatternRecord]   # rows that may be published (new or a same-version idempotent replace)
    refused: list[dict]             # cross-version overwrite attempts -> ALARM, never a silent rewrite


def _as_existing(rows: Iterable[Any]) -> dict[tuple, dict]:
    """Index existing rows (PatternRecord or plain dicts) by guard_key -> {engine_version, graph_version}."""
    out: dict[tuple, dict] = {}
    for r in rows:
        if isinstance(r, PatternRecord):
            key, ev, gv = r.guard_key(), r.engine_version, r.graph_version
        else:
            key = (r["record_kind"], r["contract"], r["driver_or_chain_id"],
                   r.get("as_of_date") or r.get(PARTITION_COL), r["provenance"])
            ev, gv = r.get("engine_version"), r.get("graph_version")
        out[key] = {"engine_version": ev, "graph_version": gv}
    return out


def apply_write_guard(existing: Iterable[Any], incoming: Iterable[PatternRecord]) -> WriteGuardResult:
    """Enforce the engine_version write-guard over a partition re-publish (plan sec 2.3 / F1).

      * a key ABSENT from `existing` -> writable (a fresh record);
      * a key PRESENT with the SAME engine_version + graph_version -> writable (a same-code retry /
        same-day repair is an IDEMPOTENT replace, never a duplicate -- one row per (guard_key));
      * a key PRESENT with a DIFFERENT engine_version or graph_version -> REFUSED + alarmed: overwriting
        it would rewrite the T-verdict with LATER CODE (a retroactive code-recompute, non-goal 6). Such a
        re-derivation must instead be published as a FRESH backfill_grid row (its own provenance), NEVER
        an in-place overwrite of the daily_sweep row that recorded what the then-current engine decided.

    daily_sweep and backfill_grid rows never collide (guard_key includes provenance) -- provenance
    separation is structural, not a rule the guard has to remember (plan sec 3.3)."""
    idx = _as_existing(existing)
    writable: list[PatternRecord] = []
    refused: list[dict] = []
    for rec in incoming:
        prior = idx.get(rec.guard_key())
        if prior is None:
            writable.append(rec)
            continue
        if prior.get("engine_version") == rec.engine_version and prior.get("graph_version") == rec.graph_version:
            writable.append(rec)  # idempotent same-version replace
            continue
        refused.append({
            "guard_key": rec.guard_key(),
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


def read_existing_guard_rows(query_fn, asofs: Iterable[str], provenance: str) -> list[dict]:
    """Read the guard-key columns of any EXISTING ledger rows for the target (asofs, provenance) from the pg
    mirror, so apply_write_guard can compare engine_version/graph_version BEFORE a re-publish overwrites a
    T-verdict (plan sec 2.3 / F1). pg-ONLY (the injected query_fn is pgnumbers.pg_query) -- a mirror gap is
    NEVER a silent Athena round-trip. The partition value is normalized to the 'YYYY-MM-DD' string the
    incoming records key on (a pg date object / timestamp text would otherwise never match the guard_key,
    silently PASSING a cross-version overwrite). Best-effort: a MISSING table (the first write / flip day) or
    any read error yields [] -- the guard cannot (and must not) block a first write; it only blocks a
    cross-version OVERWRITE of a row that already exists."""
    asof_list = sorted({a for a in asofs if a})
    if not asof_list:
        return []
    in_list = ", ".join(_sql_lit(a) for a in asof_list)
    sql = (f"SELECT record_kind, contract, driver_or_chain_id, {PARTITION_COL}, provenance, "
           f"engine_version, graph_version FROM {TABLE} "
           f"WHERE provenance = {_sql_lit(provenance)} "
           f"AND substr(cast({PARTITION_COL} as varchar), 1, 10) IN ({in_list})")
    try:
        rows = list(query_fn(sql) or [])
    except Exception as e:  # noqa: BLE001 -- missing table / mirror gap -> best-effort empty; never Athena
        logger.warning("write-guard: existing-row read failed (%s); proceeding as a first write", str(e)[:200])
        return []
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
    EXCLUDED and left to accrue daily-sweep-only (plan sec 3.1 / 3.4 / F2)."""
    kinds = set(kinds)
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
                    help="comma list of record kinds to sweep (v1: cascade,pace,chain)")
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

    # (F1) the engine_version WRITE-GUARD, ENFORCED AT RUNTIME (plan sec 2.3). Read the EXISTING ledger rows
    # for the target partitions + provenance and REFUSE to overwrite any whose stored engine_version /
    # graph_version differs -- an in-place retroactive CODE-recompute of a T-verdict (non-goal 6). Refusals
    # ALARM (a loud ERROR line, never a silent rewrite); ONLY the writable set is published. daily_sweep and
    # backfill_grid rows never collide (the guard_key carries provenance). A first write / missing table reads
    # [] -> all writable. This is the read-existing-then-compare step the plan mandates; without it a same-asof
    # re-run under a bumped image would silently overwrite the T-verdict (publisher._promote copy_object is
    # unconditional and the pg mirror upserts on the natural key).
    existing = read_existing_guard_rows(query_fn, asofs, provenance)
    guard = apply_write_guard(existing, records)
    refused_n = len(guard.refused)
    if refused_n:
        for r in guard.refused:
            logger.error("ALARM write-guard REFUSED cross-version overwrite key=%s stored(engine=%s graph=%s) "
                         "incoming(engine=%s graph=%s) -- re-derive as a fresh backfill_grid row, never in place",
                         r["guard_key"], r["stored_engine_version"], r["stored_graph_version"],
                         r["incoming_engine_version"], r["incoming_graph_version"])
        logger.error("ALARM write-guard: REFUSED %d of %d built record(s) (cross engine_version/graph_version); "
                     "publishing ONLY the %d writable row(s)", refused_n, len(records), len(guard.writable))
    records = guard.writable

    if args.dry_run:
        logger.info("--dry-run: %d writable record(s) (%d refused by write-guard); nothing written",
                    len(records), refused_n)
        return 0

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
