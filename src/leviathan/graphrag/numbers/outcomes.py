"""OUTCOMES JOIN -- J1 (the one shared computation) + J2 (the structural PIT clamp).

WHAT THIS IS
    `(key, window) -> {move, pct, basis, horizon}`, computed ONCE and consumed by four features (dated
    settles, episode magnitudes, the pattern-records variance axis, COT outcome pairing). Every consumer
    reads THIS module; none re-derives the join. That is the F-L discipline `futures_roll` exists to
    enforce, applied one level up (plan item 23).

THE BASIS IS THE CENTRAL CALL, AND IT IS MEASURED (plan J1.a / D-OJ-1)
    The naive front-month chain is contaminated in the MODAL case, not the tail: 84.0% of 90-day corn
    windows cross a roll (82.8% soybean oil, 99.0% arabica) and the splice artifact runs 1.0-2.6% of
    price at the median / 4.3-7.9% at p90 against realized moves of 4-12% -- 15-60% of the signal being
    measured. Holding the t0 front contract fixed answers under a third of 90-day questions (62.3-73.4%
    have no row at t1). A roll-adjusted continuous series cannot be built over this history at all
    (open_interest is NULL on all eight ICE slugs forever and on GLBX before 2016). So the basis is the
    SURVIVAL-SELECTED SINGLE CONTRACT -- `futures_roll.outcome_contract`, 99.6% coverage at 90 days,
    splice structurally zero because both endpoints are the same contract.

    ITS COST IS A LABELLING OBLIGATION. The survivor is the front contract in only 25.5-31.7% of
    anchors, and per-anchor divergence from the front chain is median 1.2-2.5pp / p90 4.6-7.2pp -- the
    same order as the claim itself. So `contract_month_used` and `basis` are READER-FACING on every row,
    never debug fields, and :func:`contract_token` is the one place the render form is decided.

    The two CEPEA cash slugs are Option E: `instrument_kind='cash_index'`, no contract axis, no roll
    decision to make, a straight self-join on `(slug, trade_date)`. They are also the CONTROL LEG
    (plan J1.f) -- the one path where a bug cannot hide behind a roll argument.

THE CLAMP IS STRUCTURAL, NOT PROSE (plan J2 / item 45)
    Readable iff  `E + H + survive_days <= min(asof - tape_lag, max(trade_date) for THAT SLUG)`.
    Both terms bite. `survive_days` is part of the BOUNDARY and not merely of the selection: Option D
    picks the contract by asking whether it still prints five CALENDAR DAYS past the endpoint (the
    constant is applied as timedelta(days=5), ~3 sessions -- never five sessions), so for any
    asof in [t1+1, t1+5) the selection -- and therefore px0, px1 and the whole move -- was made with
    tape the reader does not have. The per-slug term is live TODAY: the 15 Databento slugs end
    2026-07-27 while the 7 free-leg slugs end 2026-07-31, so a GLOBAL max(trade_date) would push the
    Databento boundary onto four sessions that have no data. This is the single most likely place for
    this join to be implemented wrong.

    A horizon that has not closed RENDERS AS PENDING WITH ITS CLOSE DATE. It is never dropped (dropping
    biases every base rate toward old firings -- survivorship bias in the denominator) and it is never
    left to arrive as an empty read, because an empty guarded read returns `record_silent`, which
    `citations._empty_label` maps to the COVERAGE-GAP string -- the judged-30 RCA conflation, inverted.

    HORIZON FAMILY {5, 30, 60, 90} sessions-of-calendar-days (AM-1), per (event, horizon): a firing
    joins each horizon's base rate the day THAT horizon closes, so only the newest instances' long
    horizons are ever pending. A YEAR horizon DOES NOT EXIST under this basis and is declined honestly
    rather than served: no ag front contract prints for 252 sessions past an arbitrary anchor, so a
    1-year outcome forces exactly the spliced basis measured above.

DISTRIBUTIONS COMPUTE THROUGH stats.py AND INHERIT ITS FLOORS (AM-3)
    Every percentile / spread / z this join emits runs through `numbers.stats`, and the coverage floor
    IS that module's refusal floor (`MIN_QUANTILE_N == MIN_PERCENTILE_N`) -- one floor family with
    pattern-records `too_thin`. Below the floor the answer is a THIN-COVERAGE DECLINE carrying counts
    only, never a distribution with fewer points behind it.

WHAT THIS MODULE DOES NOT DO
    No I/O. No AWS. No clock: every function that needs "now" takes an explicit `asof`, so a PIT
    boundary can never be read from the wall clock. The builder job (jobs/batch/gold_futures_outcomes_
    task.py) is the only S3-touching shell, and it computes nothing.
"""
from __future__ import annotations

import hashlib
import os
from datetime import date, timedelta
from typing import Mapping, Optional, Sequence

import pandas as pd

from leviathan.graphrag.numbers import stats as st
from leviathan.graphrag.numbers.pattern_records import PR_SUP_TOO_THIN
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver import futures_roll as FR

# ---------------------------------------------------------------------------------------------------
# Identity + the horizon family (AM-1).
# ---------------------------------------------------------------------------------------------------
OUTCOME_TABLE_ID = "gold_futures_outcomes"

HORIZON_DAYS: tuple[int, ...] = (5, 30, 60, 90)
HORIZON_LABELS: dict[int, str] = {5: "week", 30: "month", 60: "two-month", 90: "quarter"}

# AM-1: the desk asks in week/month/quarter/YEAR vocabulary and the fourth one is not servable under
# this basis. Stated as data so a caller renders the exclusion instead of quietly substituting 90.
YEAR_HORIZON_DECLINE = (
    "a 1-year outcome is EXCLUDED under the survival-selected single-contract basis: no ag front "
    "contract prints for ~252 sessions past an arbitrary anchor, so a year horizon forces the "
    "roll-spliced basis this join rejects on measured contamination (1.0-2.6% of price at the median, "
    "4.3-7.9% at p90, against realized moves of 4-12%). A year read is a NEW decision with its own "
    "basis (calendar-spread-adjusted or index-style), never a quiet extension of this one"
)

# ---------------------------------------------------------------------------------------------------
# The mechanical rules, each one a measured hazard (plan J1.c).
# ---------------------------------------------------------------------------------------------------
OUTCOME_LOOKBACK_DAYS = 14        # D-OJ-3: t1 = last session ON OR BEFORE t0+H, within a BOUNDED
#                                   lookback. CZCE has five gaps > 7 days and a measured max of 11
#                                   (Chinese New Year / Golden Week), so L >= 11 is forced; US/ICE/CEPEA
#                                   have zero gaps > 7. 14 covers the measured max with margin. An
#                                   unbounded lookback would silently price a different window.
SURVIVE_DAYS = FR.OUTCOME_SURVIVE_DAYS      # ONE constant, owned by the rule module.
TAPE_PUBLICATION_LAG_DAYS = 1     # silver_futures_eod: session D's settle is public at D+1, so a read
#                                   at asof D can never see D's own print (the card's own lag).
OUTCOME_PUBLICATION_LAG_DAYS = SURVIVE_DAYS + TAPE_PUBLICATION_LAG_DAYS   # = 6, D-OJ-13

BASIS_SURVIVOR = FR.OUTCOME_CONTRACT_RULE_VERSION   # 'survivor_nearest_v1'
BASIS_CASH = "cash_index"                           # Option E, the two CEPEA slugs
BASES: tuple[str, ...] = (BASIS_SURVIVOR, BASIS_CASH)

STATUS_CLOSED = "closed"
STATUS_PENDING = "pending"
STATUS_DECLINED_PREFIX = "declined_"

# Decline reasons. Every one names a DIFFERENT fact; collapsing any two would let "we could not measure
# here" read as "we measured and there was nothing", which is the failure class the pattern-records
# suppression vocabulary already spends five slugs to avoid.
DECLINE_UNMAPPED_SLUG = "unmapped_slug"             # no coverage floor -> never guessed (fail closed)
DECLINE_PRE_COVERAGE = "pre_coverage"               # window entirely before the per-contract floor
DECLINE_COVERAGE_STRADDLE = "coverage_straddle"     # window crosses the floor -> ratified DECLINE
DECLINE_UNSUPPORTED_HORIZON = "unsupported_horizon"  # AM-1 (the year read lands here)
DECLINE_NO_ANCHOR_SESSION = "no_anchor_session"     # no usable settle at/before t0 within the lookback
DECLINE_NO_SURVIVING_CONTRACT = "no_surviving_contract"   # nothing eligible survives t0+H+survive_days
DECLINE_NO_ENDPOINT_SESSION = "no_endpoint_session"       # the contract has no print in the L-day window
DECLINE_BAD_ENDPOINT_PRICE = "bad_endpoint_price"         # settle NULL or <= 0 at the endpoint
DECLINE_NO_SPANNING_CONTRACT = "no_spanning_contract"     # shape (ii): no ONE contract covers [t1, t2]
DECLINE_SPAN_INVERTED = "span_inverted"                   # t1 > t2 (a window inversion, never priced)
DECLINE_REASONS: tuple[str, ...] = (
    DECLINE_UNMAPPED_SLUG, DECLINE_PRE_COVERAGE, DECLINE_COVERAGE_STRADDLE,
    DECLINE_UNSUPPORTED_HORIZON, DECLINE_NO_ANCHOR_SESSION, DECLINE_NO_SURVIVING_CONTRACT,
    DECLINE_NO_ENDPOINT_SESSION, DECLINE_BAD_ENDPOINT_PRICE, DECLINE_NO_SPANNING_CONTRACT,
    DECLINE_SPAN_INVERTED,
)

# Item 50 -- the evaluable denominator is stated POSITIVELY, and that direction is the fail-closed one.
# Unlike the pattern-records ledger there is no decline that MEANS "measured, and the answer was no
# move": a move either measures or it does not. So the positive list is the CLOSED status alone, and an
# unrecognised status shrinks coverage toward the floor instead of swelling the denominator.
OUTCOME_EVALUABLE_STATUSES: tuple[str, ...] = (STATUS_CLOSED,)

# The floor family (AM-3). NOT a new number: it is stats.py's own refusal floor, imported.
OUTCOME_MIN_N = st.MIN_QUANTILE_N
OUTCOME_THIN_REASON = PR_SUP_TOO_THIN               # one vocabulary with pattern-records

# ---------------------------------------------------------------------------------------------------
# The output contract (plan item 40), and the guard column that makes J2 structural (item 46a).
# ---------------------------------------------------------------------------------------------------
# `readable_date` IS THE GUARD COLUMN, and its definition is the whole clamp:
#     closed row  -> endpoint_date       (the horizon CLOSE; guard compiles to endpoint <= asof - 6)
#     pending row -> event_date          (the row states NO move -- only that the horizon has not
#                                         closed and when it will -- so there is nothing to leak)
# D-OJ-13 names `endpoint_date` for both roles and D-OJ-14 requires a MATERIALIZED pending row that a
# guarded read RETURNS. Those two are jointly unsatisfiable on one column: a pending horizon's close, by
# definition, postdates the boundary, so a guard compiled on it drops exactly the rows D-OJ-14 exists to
# deliver -- and the pair renders as `record_silent`, i.e. the coverage-gap string, which is the
# inversion item 48a is about. `readable_date` keeps D-OJ-13's compiled predicate BYTE-IDENTICAL for
# every row that carries a move (lint_outcome_row_invariants pins that: a non-null move ALWAYS has
# readable_date == endpoint_date) and gives the move-less pending row an honest, already-knowable date.
#
# AND HERE IS WHAT THAT GUARANTEE DOES NOT COVER, stated plainly because a reader who assumes otherwise
# gets the judged-30 RCA inversion back. The builder writes `pending` only for horizons open AT THE
# BUILD'S ASOF. So for any reader whose PINNED asof PRECEDES the build:
#     a row the build wrote `closed` is dropped by the compiled guard (its endpoint postdates that
#     reader's boundary) -- and no pending row exists for that (event, horizon) either, because at the
#     build's asof it had closed. The guarded read comes back EMPTY, `cascade._status` records silent,
#     and `citations._empty_label` renders the COVERAGE-GAP string for what is purely a TIMING fact.
# The compiled guard is therefore D-OJ-14-safe only when the reader's asof equals the build's. Making it
# safe at every pinned asof would need a materialized pending row per (event, horizon) per candidate
# replay asof -- impractical. So the RULE for consumers is the other half:
#     EVERY registry-compiled consumer of this table reads it CENSUS-SHAPED, the
#     `pattern_records.po_census_sql` way -- ask this module's clamp FIRST (`pending_state` /
#     `clamp_anchored` / `clamp_row`), count rather than filter, and never let the guard's silence be
#     read as a coverage fact.
# In this tree that is `pattern_records.po_census_sql` (the boundary is a CASE, not a WHERE, so pending
# rows stay in the denominator) and `cascade._cot_outcome_read` (asks the clamp before the read and
# re-clamps every row it gets back). A new agent-facing read of this table inherits the obligation.
OUTCOME_COLUMNS: tuple[str, ...] = (
    "leviathan_slug", "event_key", "event_date", "horizon_days", "horizon_label",
    "anchor_date", "anchor_offset_days",
    "readable_date", "endpoint_date", "horizon_close_date",
    "realized_offset_days", "realized_sessions", "endpoint_dow",
    "contract_month_used", "was_front", "basis",
    "px0", "px1", "move_abs", "move_pct",
    "currency", "unit", "settle_kind",
    "status", "decline_reason",
    "rule_version", "survive_days", "tape_edge_date", "built_at",
)

# Physical types for the F010 contract + the generated DDL, single-sourced here so the builder, the
# card and the eventual Glue schema cannot drift. (The F010 registry entry + DDL generation are the
# BUILD wave's step; this constant is what they are generated FROM.)
OUTCOME_COLUMN_TYPES: dict[str, str] = {
    "leviathan_slug": "string", "event_key": "string", "event_date": "string",
    "horizon_days": "int", "horizon_label": "string",
    "anchor_date": "string", "anchor_offset_days": "int",
    "readable_date": "string", "endpoint_date": "string", "horizon_close_date": "string",
    "realized_offset_days": "int", "realized_sessions": "int", "endpoint_dow": "string",
    "contract_month_used": "string", "was_front": "boolean", "basis": "string",
    "px0": "double", "px1": "double", "move_abs": "double", "move_pct": "double",
    "currency": "string", "unit": "string", "settle_kind": "string",
    "status": "string", "decline_reason": "string",
    "rule_version": "string", "survive_days": "int", "tape_edge_date": "string",
    "built_at": "timestamp",
}
OUTCOME_PARTITIONS: tuple[str, ...] = ("leviathan_slug", "event_year")
OUTCOME_PARTITION_TYPES: dict[str, str] = {"leviathan_slug": "string", "event_year": "int"}

# AM-2 -- the open-instance elaboration ("tracking in the Nth percentile of prior instances at the same
# elapsed session count"). TWO implementations, ONE switch, and the default is the one that adds no
# storage: prior paths are re-measured at query time through this same engine. The stored alternative
# keeps coarse milestones on the row; it is implemented and OFF, so flipping it is a config change, not
# a rewrite. Env: GRAPHRAG_OUTCOME_MILESTONES=stored|query_time (junk -> the default, fail-safe).
MILESTONE_MODE_QUERY_TIME = "query_time"
MILESTONE_MODE_STORED = "stored"
MILESTONE_MODES: tuple[str, ...] = (MILESTONE_MODE_QUERY_TIME, MILESTONE_MODE_STORED)
MILESTONE_SESSIONS: tuple[int, ...] = (5, 10, 21, 42, 63)


def milestone_mode() -> str:
    """The AM-2 path in force. Default `query_time` (no new storage, a bounded per-turn read)."""
    raw = (os.environ.get("GRAPHRAG_OUTCOME_MILESTONES", "") or "").strip().lower()
    return raw if raw in MILESTONE_MODES else MILESTONE_MODE_QUERY_TIME


def milestone_columns() -> tuple[str, ...]:
    """The AM-2 (a) storage schema fields -- realized move at k elapsed sessions on the SAME contract.
    Present on a row only under `stored` mode; the column NAMES are declared unconditionally so the two
    modes describe the same quantity and a later flip cannot rename it."""
    return tuple(f"milestone_move_pct_{k}" for k in MILESTONE_SESSIONS)


# ---------------------------------------------------------------------------------------------------
# Small pure helpers.
# ---------------------------------------------------------------------------------------------------
def _as_date(value) -> date:
    """Coerce to a plain `date`. Raises rather than guessing -- a mis-parsed boundary is a leak."""
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        raise ValueError(f"not a date: {value!r}")
    return ts.date()


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    try:
        return _as_date(value).isoformat()
    except (ValueError, TypeError):
        return None


def contract_token(contract_month: Optional[str]) -> Optional[str]:
    """The RENDER form of a delivery month: `2024-03` -> `2024M03`.

    Not cosmetic. `eval._YM_RX` matches `(19|20)\\d{2}-(0[1-9]|1[0-2])`, and `_line_targets` is
    two-tier with NO fallback by design, so a bullet that renders ANY year-month token must have that
    token equal an endpoint of an injected episode span or the bullet is scored as a MINTED window. A
    delivery month will essentially never equal an episode endpoint, so a leaked `contract: 2024-03`
    would red `episode_magnitude_or_absence` and `min_episode_lines` together (plan item 41b). The `M`
    form cannot match the regex at all -- the class is removed rather than bounded. Every renderer of
    the contract segment calls THIS, so the format is decided once."""
    if not contract_month:
        return None
    s = str(contract_month).strip()
    if len(s) == 7 and s[4] == "-" and s[:4].isdigit() and s[5:].isdigit():
        return f"{s[:4]}M{s[5:]}"
    return s


def horizon_label(horizon_days: int) -> str:
    return HORIZON_LABELS.get(int(horizon_days), f"{int(horizon_days)}-day")


def horizon_supported(horizon_days: int) -> bool:
    return int(horizon_days) in HORIZON_DAYS


def horizon_decline(horizon_days: int) -> dict:
    """The honest refusal for an unsupported horizon -- AM-1's year exclusion, stated, never rounded to
    the nearest supported horizon."""
    h = int(horizon_days)
    reason = YEAR_HORIZON_DECLINE if h >= 180 else (
        f"horizon {h}d is not in the anchored family {list(HORIZON_DAYS)}; this join serves exactly "
        f"those four and never interpolates a fifth")
    return {"declined": True, "horizon_days": h, "reason": DECLINE_UNSUPPORTED_HORIZON,
            "detail": reason, "supported_horizons": list(HORIZON_DAYS)}


def horizon_close(event_date, horizon_days: int) -> date:
    """The NOMINAL close `E + H` calendar days. This is the term the clamp compiles and the term the
    contract selection uses -- one knob, per item 46's `survive_days` correction."""
    return _as_date(event_date) + timedelta(days=int(horizon_days))


# ---------------------------------------------------------------------------------------------------
# J2 -- THE PIT CLAMP.
# ---------------------------------------------------------------------------------------------------
def pit_boundary(asof, tape_edge, *, tape_lag_days: int = TAPE_PUBLICATION_LAG_DAYS) -> date:
    """`min(asof - tape_lag, max(trade_date) for THAT SLUG)` -- the latest tape date a reader may use.

    PER SLUG. A global max(trade_date) would push the 15 Databento slugs (edge 2026-07-27) onto four
    sessions they have no data for, because the 7 free legs run to 2026-07-31. `tape_edge=None` means
    the slug's edge was not established, and that is NOT a licence: it collapses to `asof - tape_lag`
    only for callers that pass it explicitly, which the builder never does (fail closed at the call
    site, where the missing edge is visible)."""
    bound = _as_date(asof) - timedelta(days=int(tape_lag_days))
    if tape_edge is None:
        return bound
    edge = _as_date(tape_edge)
    return min(bound, edge)


def clamp_anchored(event_date, horizon_days: int, asof, tape_edge, *,
                   survive_days: int = SURVIVE_DAYS,
                   tape_lag_days: int = TAPE_PUBLICATION_LAG_DAYS) -> dict:
    """J2 item 46, per (event, horizon): `E + H + survive_days <= min(asof - lag, slug tape edge)`.

    Returns `{"status": closed|pending, "close_date": <E+H>, "boundary": <the min above>, ...}`. A
    pending horizon carries its CLOSE DATE so the renderer can say when it closes -- that is the whole
    difference between a timing statement and a coverage gap."""
    close = horizon_close(event_date, horizon_days)
    boundary = pit_boundary(asof, tape_edge, tape_lag_days=tape_lag_days)
    need = close + timedelta(days=int(survive_days))
    status = STATUS_CLOSED if need <= boundary else STATUS_PENDING
    return {"status": status, "close_date": close, "boundary": boundary,
            "survive_days": int(survive_days),
            "readable_on": need,          # the first asof-lagged tape date at which it becomes readable
            "pending_reason": None if status == STATUS_CLOSED else (
                "edge" if (_as_date(asof) - timedelta(days=int(tape_lag_days))) > boundary else "asof")}


def clamp_span(span_end, asof, tape_edge, *, survive_days: int = SURVIVE_DAYS,
               tape_lag_days: int = TAPE_PUBLICATION_LAG_DAYS) -> dict:
    """J2 item 47a -- the SHAPE (ii) clamp, which the first draft never stated and which is the one J4
    uses: `t2 + survive_days <= min(asof - lag, slug tape edge)`.

    `span_end` is the DAY-GRAIN episode end, NEVER the `YYYY-MM` month token. Expanding a month token
    to month-end prices up to 30 days past the asof; the month token is a LABEL for matching, never an
    interval to measure (D-OJ-16)."""
    end = _as_date(span_end)
    boundary = pit_boundary(asof, tape_edge, tape_lag_days=tape_lag_days)
    need = end + timedelta(days=int(survive_days))
    return {"status": STATUS_CLOSED if need <= boundary else STATUS_PENDING,
            "close_date": end, "boundary": boundary, "readable_on": need,
            "survive_days": int(survive_days)}


def clamp_row(row: Mapping, asof, tape_edge, *, survive_days: int = SURVIVE_DAYS,
              tape_lag_days: int = TAPE_PUBLICATION_LAG_DAYS) -> dict:
    """RE-CLAMP a fetched row at the READER's asof. Defense in depth beside the compiled guard.

    The table is a FULL REBUILD at the tape edge (D-OJ-15), so a row materialized `closed` by today's
    build is physically present when a PINNED-ASOF replay reads the partition. The SQL guard already
    excludes it (`readable_date <= asof - 6`), but a consumer that assembles rows by any other path --
    a mirror read, a fixture, a cached frame -- would otherwise inherit a closed row whose horizon had
    not closed at ITS asof. This function is what makes "pending" a function of the reader's asof
    rather than of the build's, and it strips px1/move on the way (a pending row states no move).

    IT STRIPS THE SELECTION FIELDS TOO, and that is not tidiness. `anchored_outcome` runs the clamp
    BEFORE the contract selection for a stated reason (see its own comment): Option D picks the contract
    by asking whether it still prints `survive_days` past a close that, for a pending horizon, HAS NOT
    HAPPENED -- so `contract_month_used`, `px0`, `was_front`, the anchor and the price metadata are all
    FUTURE-CONDITIONED. A re-clamped row that kept them would publish exactly the two values the build
    path refuses to publish, on a row that is supposed to state nothing but timing -- and the re-clamp is
    the path EVERY pinned-asof replay takes (`pattern_records.pattern_outcome_legs`). The mirror
    assertion lives in `lint_outcome_row_invariants`: a pending row carries no px0 and no
    contract_month_used."""
    out = dict(row)
    if str(out.get("status") or "") .startswith(STATUS_DECLINED_PREFIX):
        return out
    verdict = clamp_anchored(out.get("event_date"), int(out.get("horizon_days") or 0), asof, tape_edge,
                             survive_days=survive_days, tape_lag_days=tape_lag_days)
    if verdict["status"] == STATUS_CLOSED:
        return out
    out["status"] = STATUS_PENDING
    out["horizon_close_date"] = verdict["close_date"].isoformat()
    out["readable_date"] = _iso(out.get("event_date"))
    for k in ("endpoint_date", "px1", "move_abs", "move_pct", "realized_offset_days",
              "realized_sessions", "endpoint_dow",
              # the SELECTION half -- every one of these was chosen with tape past this reader's boundary
              "px0", "contract_month_used", "was_front", "anchor_date", "anchor_offset_days",
              "unit", "currency", "settle_kind", "basis"):
        out[k] = None
    return out


def pending_state(event_date, horizon_days: int, asof, tape_edge, **kw) -> bool:
    """True when this (event, horizon) has NOT closed at `asof`. Computed from the event and the tape
    edge, never inferred from an absent row -- which is what makes `n_pending` a count rather than a
    guess (item 49)."""
    return clamp_anchored(event_date, horizon_days, asof, tape_edge, **kw)["status"] == STATUS_PENDING


def evaluable_pred(status_col: str = "status") -> str:
    """The ANSI predicate for "this row is an EVALUABLE outcome", stated POSITIVELY (item 50). An
    unrecognised status falls OUTSIDE it and SHRINKS coverage -- the fail-closed direction."""
    lits = ", ".join(f"'{s}'" for s in OUTCOME_EVALUABLE_STATUSES)
    return f"({status_col} IN ({lits}))"


# ---------------------------------------------------------------------------------------------------
# J1 -- the shared computation.
# ---------------------------------------------------------------------------------------------------
def _slug_frame(tape: pd.DataFrame, slug: str) -> pd.DataFrame:
    work = tape[tape["leviathan_slug"].astype("string") == str(slug)].copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work = work[work["trade_date"].notna()]
    work["_settle"] = pd.to_numeric(work["settle"], errors="coerce")
    return work


def tape_edges(tape: pd.DataFrame) -> dict[str, date]:
    """`max(trade_date)` PER SLUG -- the per-slug half of the clamp, measured, never assumed global."""
    work = tape[["leviathan_slug", "trade_date"]].copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work = work[work["trade_date"].notna()]
    if work.empty:
        return {}
    agg = work.groupby("leviathan_slug")["trade_date"].max()
    return {str(k): v.date() for k, v in agg.items()}


def _sessions(frame: pd.DataFrame, *, contract_month: Optional[str]) -> pd.DataFrame:
    """The usable session rows of ONE series: settle present and > 0 (the price fence -- 9,983 NULL and
    217 exact-zero rows on the live tape, and a zero denominator fabricates a -100% move)."""
    work = frame
    if contract_month is not None:
        work = work[work["contract_month"].astype("string") == str(contract_month)]
    work = work[work["_settle"].notna() & (work["_settle"] > 0)]
    return work.sort_values("trade_date", kind="mergesort")


def _last_on_or_before(sessions: pd.DataFrame, target: date, lookback_days: int):
    """The last session at or before `target`, within a BOUNDED lookback. None when the series is dark
    for longer than the bound -- a stretched endpoint is auditable (`realized_offset_days`), an
    unbounded one silently prices a different window."""
    lo = target - timedelta(days=int(lookback_days))
    hit = sessions[(sessions["trade_date"].dt.date <= target) & (sessions["trade_date"].dt.date >= lo)]
    if hit.empty:
        return None
    return hit.iloc[-1]


def _declined(reason: str, **extra) -> dict:
    row = {c: None for c in OUTCOME_COLUMNS}
    row.update({"status": f"{STATUS_DECLINED_PREFIX}{reason}", "decline_reason": reason})
    row.update(extra)
    return row


def _coverage_verdict(slug: str, start: date, end: date) -> Optional[str]:
    """Route the window against the MEASURED per-contract floor -- reuse, never re-derive (item 37).
    `coverage_start_for` RAISES on an unmapped slug and never returns a permissive default; nine of the
    31 registry contracts have zero rows, so the raise is a live path."""
    try:
        verdict = FC.covers(slug, start, end)
    except ValueError:
        return DECLINE_UNMAPPED_SLUG
    if verdict == "straddle":
        return DECLINE_COVERAGE_STRADDLE
    if verdict == "legacy":
        return DECLINE_PRE_COVERAGE
    return None


def _was_front(frame: pd.DataFrame, anchor_date, contract_month: Optional[str]) -> Optional[bool]:
    """D-OJ-2: was the survivor ALSO the front contract at the anchor? NULL -- never False -- where the
    roll rule's inputs are absent. `front_month_inputs_present` is both-sided fail-closed and OI is
    absent on all ICE forever and on GLBX before 2016, so a False there would assert a fact never
    established. Labelling only: `front_month` never selects here."""
    at = frame[frame["trade_date"].dt.date == _as_date(anchor_date)]
    if at.empty or not FR.front_month_inputs_present(at):
        return None
    picked = FR.front_month(at)
    if picked.empty:
        return None
    return bool(str(picked.iloc[0]["contract_month"]) == str(contract_month))


def anchored_outcome(tape: pd.DataFrame, *, slug: str, event_key: str, event_date,
                     horizon_days: int, asof, tape_edge=None, last_print: pd.DataFrame | None = None,
                     survive_days: int = SURVIVE_DAYS,
                     lookback_days: int = OUTCOME_LOOKBACK_DAYS,
                     built_at=None) -> dict:
    """SHAPE (i) -- the anchored forward horizon (J5, J6). One (event, horizon) -> one outcome row.

    `tape` carries silver_futures_eod rows (at least `leviathan_slug, trade_date, contract_month,
    settle, unit, currency, settle_kind`). `tape_edge` is THAT SLUG's max(trade_date); when omitted it
    is measured from `tape`, which is correct only when `tape` is the full slug history -- the builder
    always passes it explicitly.

    Returns exactly one row of :data:`OUTCOME_COLUMNS`. `status` is `closed` (measured), `pending` (the
    horizon has not closed at `asof` -- with its close date, and NO move) or `declined_<reason>`."""
    event_d = _as_date(event_date)
    edges = tape_edges(tape) if tape_edge is None else {}
    edge = _as_date(tape_edge) if tape_edge is not None else edges.get(str(slug))
    base = {
        "leviathan_slug": slug, "event_key": event_key, "event_date": event_d.isoformat(),
        "horizon_days": int(horizon_days), "horizon_label": horizon_label(horizon_days),
        "horizon_close_date": None, "rule_version": BASIS_SURVIVOR,
        "survive_days": int(survive_days), "tape_edge_date": _iso(edge),
        "built_at": built_at, "basis": None,
    }
    if not horizon_supported(horizon_days):
        return {**_declined(DECLINE_UNSUPPORTED_HORIZON), **base}

    close = horizon_close(event_d, horizon_days)
    base["horizon_close_date"] = close.isoformat()
    is_cash = str(slug) in FC.CASH_INDEX_SLUGS
    base["basis"] = BASIS_CASH if is_cash else BASIS_SURVIVOR
    if is_cash:
        base["rule_version"] = BASIS_CASH

    cov = _coverage_verdict(str(slug), event_d, close)
    if cov:
        return {**_declined(cov), **base}

    # THE CLAMP RUNS BEFORE THE SELECTION, and that ordering is load-bearing rather than tidy. Option D
    # chooses the contract by asking whether it still prints `survive_days` past a close that, for a
    # pending horizon, HAS NOT HAPPENED -- so selecting first and emitting `contract_month_used` / `px0`
    # on a pending row would publish two future-conditioned values on a row that is supposed to state
    # nothing but timing. A pending row therefore carries its close date and nothing else measured.
    verdict = clamp_anchored(event_d, horizon_days, asof, edge, survive_days=survive_days)
    if verdict["status"] == STATUS_PENDING:
        return {**{c: None for c in OUTCOME_COLUMNS}, **base,
                "status": STATUS_PENDING, "decline_reason": None,
                "readable_date": event_d.isoformat()}

    frame = _slug_frame(tape, slug)

    # THE ANCHOR. Snap to the last session at or before the event date within the same bounded lookback
    # (a firing can land on a holiday or a weekend); snapping BACKWARD only ever uses past tape.
    anchor = _last_on_or_before(_sessions(frame, contract_month=None), event_d, lookback_days)
    if anchor is None:
        return {**_declined(DECLINE_NO_ANCHOR_SESSION), **base}
    anchor_date = anchor["trade_date"].date()
    base["anchor_date"] = anchor_date.isoformat()
    base["anchor_offset_days"] = (event_d - anchor_date).days

    # THE SERIES. Option D for futures (one contract, both endpoints), Option E for the two CEPEA cash
    # references -- which have no contract axis at all, so a survivor rule would be a category error.
    if is_cash:
        contract_month = None
        px0_row = anchor
    else:
        at_anchor = frame[frame["trade_date"].dt.date == anchor_date]
        lp = last_print if last_print is not None else FR.contract_last_print(frame)
        picked = FR.outcome_contract(at_anchor, horizon_end=close, survive_days=survive_days,
                                     last_print=lp)
        if picked.empty:
            return {**_declined(DECLINE_NO_SURVIVING_CONTRACT), **base}
        contract_month = str(picked.iloc[0]["contract_month"])
        px0_row = picked.iloc[0]
        base["contract_month_used"] = contract_month
        base["was_front"] = _was_front(frame, anchor_date, contract_month)

    px0 = float(pd.to_numeric(px0_row["settle"], errors="coerce"))
    if not (px0 > 0):
        # THE SAME PRICE FENCE `_sessions` applies, applied to the ANCHOR leg: the survivor is picked
        # from the raw anchor-day rows (the selection rule reads expiries, not prices), so a NULL or
        # exact-zero settle reaches here unfenced -- 9,983 NULL and 217 exact-zero rows on the live
        # tape. A zero denominator fabricates a -100% move; a NaN one ships a closed row with no move.
        return {**_declined(DECLINE_BAD_ENDPOINT_PRICE), **base}
    base["px0"] = px0
    for col in ("unit", "currency", "settle_kind"):
        val = px0_row.get(col) if hasattr(px0_row, "get") else None
        base[col] = None if val is None or pd.isna(val) else str(val)

    sessions = _sessions(frame, contract_month=contract_month)
    end_row = _last_on_or_before(sessions, close, lookback_days)
    if end_row is None:
        return {**_declined(DECLINE_NO_ENDPOINT_SESSION), **base}
    px1 = float(pd.to_numeric(end_row["settle"], errors="coerce"))
    if not (px1 > 0):
        return {**_declined(DECLINE_BAD_ENDPOINT_PRICE), **base}
    end_date = end_row["trade_date"].date()
    between = sessions[(sessions["trade_date"].dt.date > anchor_date)
                       & (sessions["trade_date"].dt.date <= end_date)]
    if len(between) < 1:
        # A ZERO-LENGTH WINDOW IS NOT A MEASUREMENT. When the endpoint snaps back onto the anchor
        # session itself (a horizon whose whole span is dark, or an as-of clamp that leaves one visible
        # date), px1 IS px0 and the "move" is +0.0% over a window across which no session elapsed. That
        # renders as a closed [N] handle carrying a fabricated magnitude. The honest answer is that the
        # window has no endpoint session distinct from its anchor.
        return {**_declined(DECLINE_NO_ENDPOINT_SESSION), **base}

    # AM-3, ONE STORY: even the two-point move goes through the calculator, exactly as `realized_so_far`
    # does -- never inline arithmetic in one place and `st.window_change` in another. Both endpoints are
    # fenced > 0 above, so this cannot decline; the branch is kept because a future fence change must
    # decline rather than divide.
    change = st.window_change([px0, px1], 0, 1)
    if change["declined"] or change["pct_change"] is None:
        return {**_declined(DECLINE_BAD_ENDPOINT_PRICE), **base}

    row = {c: None for c in OUTCOME_COLUMNS}
    row.update(base)
    row.update({
        "readable_date": end_date.isoformat(),   # closed rows guard on the CLOSE, exactly as D-OJ-13
        "endpoint_date": end_date.isoformat(),
        "realized_offset_days": (close - end_date).days,
        "realized_sessions": int(len(between)),
        "endpoint_dow": end_date.strftime("%a"),   # D-OJ-4: Sundays are real sessions; record the day
        "px1": px1, "move_abs": change["value"], "move_pct": change["pct_change"],
        "status": STATUS_CLOSED, "decline_reason": None,
    })
    return row


def span_outcome(tape: pd.DataFrame, *, slug: str, span_start, span_end, asof, tape_edge=None,
                 last_print: pd.DataFrame | None = None, event_key: Optional[str] = None,
                 survive_days: int = SURVIVE_DAYS,
                 lookback_days: int = OUTCOME_LOOKBACK_DAYS) -> dict:
    """SHAPE (ii) -- the SPAN MOVE `[t1, t2]` an episode hands over (J4). COMPUTED AT QUERY TIME, from
    the same rule module, and NEVER written to `gold_futures_outcomes` (item 98(d)): episode windows
    move when the artifact is rebuilt, so a stored span row would be stale by construction and a baked
    window would sit at the one layer the interlock does not cover.

    The read is `contract_month`-scoped by construction (~1 row/session), which is why the 5,000-row
    `agg='series'` cap does not bind here (J1.39); a full-curve read is 3.7-12.9 rows/session and WOULD
    truncate silently.

    Both endpoints must live on ONE contract: an episode span longer than a contract's life (corn 587
    sessions average, soybean oil 396, arabica 514, CZCE rapeseed meal 243) has none, and that case
    DECLINES -- which the episodes persona already treats as the normal outcome."""
    t1, t2 = _as_date(span_start), _as_date(span_end)
    edge = _as_date(tape_edge) if tape_edge is not None else tape_edges(tape).get(str(slug))
    base = {c: None for c in OUTCOME_COLUMNS}
    base.update({"leviathan_slug": slug, "event_key": event_key, "event_date": t1.isoformat(),
                 "horizon_days": None, "horizon_label": "span",
                 "horizon_close_date": t2.isoformat(), "rule_version": BASIS_SURVIVOR,
                 "survive_days": int(survive_days), "tape_edge_date": _iso(edge)})
    is_cash = str(slug) in FC.CASH_INDEX_SLUGS
    base["basis"] = BASIS_CASH if is_cash else BASIS_SURVIVOR
    if t1 > t2:
        # The SAME decline idiom every other branch here uses -- `_declined` blanks the whole row, so
        # re-adding five keys by hand silently dropped `horizon_label` and `basis` from the one decline
        # that took that route. An inverted span is still a span on a known basis.
        return {**base, "status": f"{STATUS_DECLINED_PREFIX}{DECLINE_SPAN_INVERTED}",
                "decline_reason": DECLINE_SPAN_INVERTED}

    cov = _coverage_verdict(str(slug), t1, t2)
    if cov:
        return {**base, "status": f"{STATUS_DECLINED_PREFIX}{cov}", "decline_reason": cov}

    verdict = clamp_span(t2, asof, edge, survive_days=survive_days)
    if verdict["status"] == STATUS_PENDING:
        return {**base, "status": STATUS_PENDING, "decline_reason": None,
                "readable_date": t1.isoformat()}

    frame = _slug_frame(tape, slug)
    start_row = _last_on_or_before(_sessions(frame, contract_month=None), t1, lookback_days)
    if start_row is None:
        return {**base, "status": f"{STATUS_DECLINED_PREFIX}{DECLINE_NO_ANCHOR_SESSION}",
                "decline_reason": DECLINE_NO_ANCHOR_SESSION}
    anchor_date = start_row["trade_date"].date()

    if is_cash:
        contract_month = None
    else:
        at_anchor = frame[frame["trade_date"].dt.date == anchor_date]
        lp = last_print if last_print is not None else FR.contract_last_print(frame)
        picked = FR.outcome_contract(at_anchor, horizon_end=t2, survive_days=survive_days,
                                     last_print=lp)
        if picked.empty:
            # No ONE contract spans the window -- the multi-year-episode case, declined by design.
            return {**base, "status": f"{STATUS_DECLINED_PREFIX}{DECLINE_NO_SPANNING_CONTRACT}",
                    "decline_reason": DECLINE_NO_SPANNING_CONTRACT}
        contract_month = str(picked.iloc[0]["contract_month"])
        base["contract_month_used"] = contract_month
        base["was_front"] = _was_front(frame, anchor_date, contract_month)

    sessions = _sessions(frame, contract_month=contract_month)
    px0_row = _last_on_or_before(sessions, t1, lookback_days)
    end_row = _last_on_or_before(sessions, t2, lookback_days)
    if px0_row is None or end_row is None:
        return {**base, "status": f"{STATUS_DECLINED_PREFIX}{DECLINE_NO_ENDPOINT_SESSION}",
                "decline_reason": DECLINE_NO_ENDPOINT_SESSION}
    px0 = float(pd.to_numeric(px0_row["settle"], errors="coerce"))
    px1 = float(pd.to_numeric(end_row["settle"], errors="coerce"))
    if not (px0 > 0 and px1 > 0):
        return {**base, "status": f"{STATUS_DECLINED_PREFIX}{DECLINE_BAD_ENDPOINT_PRICE}",
                "decline_reason": DECLINE_BAD_ENDPOINT_PRICE}
    start_date, end_date = px0_row["trade_date"].date(), end_row["trade_date"].date()
    between = sessions[(sessions["trade_date"].dt.date > start_date)
                       & (sessions["trade_date"].dt.date <= end_date)]
    if len(between) < 1:
        # THE SINGLE-VISIBLE-DATE EPISODE. `timeline.episodes_for` builds `start, end = vis[0], vis[-1]`
        # from the AS-OF-CLAMPED visible prop dates, so one visible date manufactures `start == end` --
        # and the as-of clamp manufactures exactly that for recent episodes. Both endpoints then land on
        # the same session and the leg would render `+0 %` across a window over which no session
        # elapsed. Declined on the ENDPOINT, which is the fact: there is no second session to price.
        return {**base, "status": f"{STATUS_DECLINED_PREFIX}{DECLINE_NO_ENDPOINT_SESSION}",
                "decline_reason": DECLINE_NO_ENDPOINT_SESSION}
    change = st.window_change([px0, px1], 0, 1)      # AM-3, one story (see anchored_outcome)
    if change["declined"] or change["pct_change"] is None:
        return {**base, "status": f"{STATUS_DECLINED_PREFIX}{DECLINE_BAD_ENDPOINT_PRICE}",
                "decline_reason": DECLINE_BAD_ENDPOINT_PRICE}
    base.update({
        "anchor_date": start_date.isoformat(), "anchor_offset_days": (t1 - start_date).days,
        "readable_date": end_date.isoformat(), "endpoint_date": end_date.isoformat(),
        "realized_offset_days": (t2 - end_date).days, "realized_sessions": int(len(between)),
        "endpoint_dow": end_date.strftime("%a"),
        "px0": px0, "px1": px1, "move_abs": change["value"], "move_pct": change["pct_change"],
        "status": STATUS_CLOSED, "decline_reason": None,
    })
    for col in ("unit", "currency", "settle_kind"):
        val = px0_row.get(col)
        base[col] = None if val is None or pd.isna(val) else str(val)
    return base


# ---------------------------------------------------------------------------------------------------
# AM-2 -- the OPEN instance: realized-so-far (observed) + percentile against prior paths.
# ---------------------------------------------------------------------------------------------------
def realized_so_far(tape: pd.DataFrame, *, slug: str, event_key: str, event_date, horizon_days: int,
                    asof, tape_edge=None, last_print: pd.DataFrame | None = None,
                    survive_days: int = SURVIVE_DAYS,
                    lookback_days: int = OUTCOME_LOOKBACK_DAYS) -> dict:
    """AM-2 -- an OPEN firing's move from t0 to the asof boundary. This is OBSERVED data and is servable
    immediately under the ordinary [N] contract; the clamp governs membership in CLOSED statistics, not
    the readability of what has already printed.

    THE BASIS IS PROVISIONAL, AND THE ROW SAYS SO. The closed-row survival test asks whether a contract
    still prints five calendar days past a close that has not happened yet -- unanswerable at this asof
    without future tape. So the open read selects against the KNOWN boundary instead
    (`horizon_end=boundary, survive_days=0`, the same rule module, no second selection rule) and sets
    `basis_provisional=True`: the contract this instance is tracked on may differ from the one its
    eventual closed row is measured on, and a reader who is not told that would compare two different
    series without knowing it."""
    event_d = _as_date(event_date)
    edge = _as_date(tape_edge) if tape_edge is not None else tape_edges(tape).get(str(slug))
    boundary = pit_boundary(asof, edge)
    close = horizon_close(event_d, horizon_days)
    frame = _slug_frame(tape, slug)
    out = {"leviathan_slug": slug, "event_key": event_key, "event_date": event_d.isoformat(),
           "horizon_days": int(horizon_days), "horizon_close_date": close.isoformat(),
           "asof_boundary": boundary.isoformat(), "status": "open", "basis_provisional": True,
           "declined": False, "reason": None, "contract_month_used": None,
           "elapsed_sessions": None, "px0": None, "px_asof": None, "move_pct": None}
    if not horizon_supported(horizon_days):
        return {**out, "declined": True, "reason": DECLINE_UNSUPPORTED_HORIZON,
                "detail": horizon_decline(horizon_days)["detail"]}
    cov = _coverage_verdict(str(slug), event_d, boundary)
    if cov:
        return {**out, "declined": True, "reason": cov}
    anchor = _last_on_or_before(_sessions(frame, contract_month=None), event_d, lookback_days)
    if anchor is None:
        return {**out, "declined": True, "reason": DECLINE_NO_ANCHOR_SESSION}
    anchor_date = anchor["trade_date"].date()

    if str(slug) in FC.CASH_INDEX_SLUGS:
        contract_month = None
        out["basis"] = BASIS_CASH
    else:
        at_anchor = frame[frame["trade_date"].dt.date == anchor_date]
        lp = last_print if last_print is not None else FR.contract_last_print(frame)
        picked = FR.outcome_contract(at_anchor, horizon_end=boundary, survive_days=0, last_print=lp)
        if picked.empty:
            return {**out, "declined": True, "reason": DECLINE_NO_SURVIVING_CONTRACT}
        contract_month = str(picked.iloc[0]["contract_month"])
        out["contract_month_used"] = contract_month
        out["basis"] = BASIS_SURVIVOR

    sessions = _sessions(frame, contract_month=contract_month)
    px0_row = _last_on_or_before(sessions, anchor_date, lookback_days)
    now_row = _last_on_or_before(sessions, boundary, lookback_days)
    if px0_row is None or now_row is None:
        return {**out, "declined": True, "reason": DECLINE_NO_ENDPOINT_SESSION}
    px0 = float(pd.to_numeric(px0_row["settle"], errors="coerce"))
    pxn = float(pd.to_numeric(now_row["settle"], errors="coerce"))
    if not (px0 > 0 and pxn > 0):
        return {**out, "declined": True, "reason": DECLINE_BAD_ENDPOINT_PRICE}
    end_date = now_row["trade_date"].date()
    elapsed = int(len(sessions[(sessions["trade_date"].dt.date > anchor_date)
                               & (sessions["trade_date"].dt.date <= end_date)]))
    change = st.window_change([px0, pxn], 0, 1)          # AM-3: even the two-point move goes through
    if change["declined"]:                                # the calculator, never inline arithmetic
        return {**out, "declined": True, "reason": DECLINE_BAD_ENDPOINT_PRICE}
    return {**out, "anchor_date": anchor_date.isoformat(), "px0": px0, "px_asof": pxn,
            "asof_date": end_date.isoformat(), "elapsed_sessions": elapsed,
            "move_abs": change["value"], "move_pct": change["pct_change"],
            "pending": pending_state(event_d, horizon_days, asof, edge)}


def path_move_pct_at(tape: pd.DataFrame, *, slug: str, contract_month: Optional[str], anchor_date,
                     elapsed_sessions: int, asof=None, tape_edge=None, boundary=None,
                     lookback_days: int = OUTCOME_LOOKBACK_DAYS) -> Optional[float]:
    """The realized move (%) `elapsed_sessions` sessions after the anchor, ON THE SAME CONTRACT -- the
    prior-path value AM-2's percentile needs at arbitrary elapsed k. None when the path is shorter than
    k (a prior instance that never reached k contributes NOTHING rather than a truncated value).

    IT TAKES THE BOUNDARY, like every other tape-reading function in this module. This was the one that
    did not, and it is the QUERY-TIME default for AM-2's percentile -- so PIT-safety rested entirely on
    the caller having pre-clamped `tape`, which nothing enforced and which this module's own docstring
    ("No clock: every function that needs 'now' takes an explicit asof") says is not how the boundary
    travels here. Pass `asof` (with the slug's `tape_edge` where it is known) or an explicit
    `boundary`; both ends of the read are then clamped to it. Omitting both keeps the old, unclamped
    behaviour for callers that genuinely hold a pre-clamped frame -- the builder passes its own asof."""
    frame = _slug_frame(tape, slug)
    sessions = _sessions(frame, contract_month=contract_month)
    anchor_d = _as_date(anchor_date)
    bound: Optional[date] = None
    if boundary is not None:
        bound = _as_date(boundary)
    elif asof is not None:
        edge = _as_date(tape_edge) if tape_edge is not None else tape_edges(tape).get(str(slug))
        bound = pit_boundary(asof, edge)
    if bound is not None:
        sessions = sessions[sessions["trade_date"].dt.date <= bound]
    after = sessions[sessions["trade_date"].dt.date > anchor_d]
    at_anchor = sessions[sessions["trade_date"].dt.date <= anchor_d]
    if at_anchor.empty or len(after) < int(elapsed_sessions) or int(elapsed_sessions) < 1:
        return None
    px0 = float(pd.to_numeric(at_anchor.iloc[-1]["settle"], errors="coerce"))
    pxk = float(pd.to_numeric(after.iloc[int(elapsed_sessions) - 1]["settle"], errors="coerce"))
    if not (px0 > 0 and pxk > 0):
        return None
    change = st.window_change([px0, pxk], 0, 1)
    return None if change["declined"] else change["pct_change"]


def elapsed_percentile(current_move_pct: float, prior_paths: Sequence[Mapping], *,
                       elapsed_sessions: int, tape: pd.DataFrame | None = None,
                       asof=None, mode: Optional[str] = None) -> dict:
    """AM-2's flagship elaboration: "the current instance is tracking in the Nth percentile of prior
    instances at the same elapsed-session count".

    `prior_paths` are prior CLOSED instances. Under `query_time` (the default, no new storage) each
    prior contributes `path_move_pct_at(...)` re-measured from the served tape through the J1 engine;
    under `stored` each contributes its `milestone_move_pct_<k>` column, which requires k to be one of
    :data:`MILESTONE_SESSIONS` -- the cost of the storage path is exactly that coarseness, which is why
    the query-time path is the default.

    The percentile itself is `stats.percentile`, so the refusal floor is inherited: fewer than
    MIN_PERCENTILE_N priors is a THIN-COVERAGE DECLINE carrying counts only (`too_thin`), never a rank
    computed over a handful of paths.

    `asof` is threaded to `path_move_pct_at` under the query-time path so every re-measured prior stops
    at the reader's boundary; each prior's own stored `tape_edge_date` supplies the per-slug half."""
    use = (mode or milestone_mode())
    k = int(elapsed_sessions)
    if current_move_pct is None:
        # The open instance has no measured move yet (its own read declined). `stats.percentile` would
        # raise TypeError comparing None; a rank of an unmeasured x is not a thin-coverage fact, so it
        # gets its own honest reason rather than borrowing `too_thin`.
        return {"declined": True, "reason": DECLINE_NO_ENDPOINT_SESSION, "n": 0, "n_unusable": 0,
                "elapsed_sessions": k, "mode": use,
                "detail": "the open instance has no measured move at this asof, so there is nothing to "
                          "rank against the prior paths"}
    values: list[float] = []
    unusable = 0
    for prior in prior_paths:
        if use == MILESTONE_MODE_STORED:
            col = f"milestone_move_pct_{k}"
            if col not in prior:
                return {"declined": True, "reason": "milestone_not_stored", "n": 0,
                        "detail": f"stored mode has no {col} (milestones: {list(MILESTONE_SESSIONS)}); "
                                  f"the query-time path measures arbitrary k"}
            val = prior.get(col)
        else:
            if tape is None:
                raise ValueError("elapsed_percentile: query_time mode needs the served `tape` frame")
            val = path_move_pct_at(tape, slug=prior.get("leviathan_slug"),
                                   contract_month=prior.get("contract_month_used"),
                                   anchor_date=prior.get("anchor_date") or prior.get("event_date"),
                                   elapsed_sessions=k, asof=asof,
                                   tape_edge=prior.get("tape_edge_date"))
        if val is None:
            unusable += 1
            continue
        values.append(float(val))
    res = st.percentile(current_move_pct, values)
    if res["declined"]:
        return {"declined": True, "reason": OUTCOME_THIN_REASON, "n": len(values),
                "n_unusable": unusable, "floor": st.MIN_PERCENTILE_N, "elapsed_sessions": k,
                "mode": use, "detail": res["reason"]}
    return {"declined": False, "percentile": res["value"], "n": res["n"], "n_unusable": unusable,
            "elapsed_sessions": k, "mode": use, "x": res["x"]}


# ---------------------------------------------------------------------------------------------------
# Distributions -- through stats.py, floors inherited (AM-3 / the standing stats-tools directive).
# ---------------------------------------------------------------------------------------------------
def outcome_distribution(rows: Sequence[Mapping], *, probs: Sequence[float] = (0.1, 0.5, 0.9),
                         value_col: str = "move_pct") -> dict:
    """The J5/J6 outcome distribution over already-fetched, PIT-clamped rows.

    Publishes `n_pending` BESIDE `n_closed` unconditionally (item 49): a pending firing that is silently
    dropped biases every base rate toward OLD firings, which is survivorship bias in the denominator --
    the same failure `pattern_records.presence_sql` guards by publishing first/last_recorded alongside
    first/last_evaluable.

    BELOW THE FLOOR IT DECLINES, and the decline carries COUNTS ONLY -- no quantile, no min/max, nothing
    a reader could mistake for a distribution. The floor is stats.MIN_QUANTILE_N (== MIN_PERCENTILE_N)
    and the slug is pattern-records' `too_thin`: one floor family, one vocabulary."""
    closed, pending, declined = [], 0, {}
    for r in rows:
        status = str(r.get("status") or "")
        if status == STATUS_CLOSED:
            val = r.get(value_col)
            if val is not None and not pd.isna(val):
                closed.append(float(val))
        elif status == STATUS_PENDING:
            pending += 1
        elif status.startswith(STATUS_DECLINED_PREFIX):
            reason = str(r.get("decline_reason") or status[len(STATUS_DECLINED_PREFIX):])
            declined[reason] = declined.get(reason, 0) + 1
    n = len(closed)
    head = {"n_closed": n, "n_pending": pending, "n_declined": sum(declined.values()),
            "declined_by_reason": dict(sorted(declined.items())), "floor": OUTCOME_MIN_N,
            "value_col": value_col}
    if n < OUTCOME_MIN_N:
        return {**head, "declined": True, "reason": OUTCOME_THIN_REASON,
                "detail": f"{n} closed outcome(s) is below the coverage floor of {OUTCOME_MIN_N}; "
                          f"a spread over that many firings fakes precision, so the honest answer is "
                          f"the count and the window, never a distribution"}
    qs = st.quantiles(closed, probs)
    ext = st.extrema(closed)
    if qs["declined"] or ext["declined"]:                 # belt and braces: the floors agree by
        return {**head, "declined": True, "reason": OUTCOME_THIN_REASON,   # construction, but a future
                "detail": qs.get("reason") or ext.get("reason")}           # floor bump must not leak
    return {**head, "declined": False,
            "quantiles": qs["quantiles"], "min": ext["min"], "max": ext["max"],
            "n_up": sum(1 for v in closed if v > 0), "n_down": sum(1 for v in closed if v < 0),
            "n_flat": sum(1 for v in closed if v == 0)}


# ---------------------------------------------------------------------------------------------------
# The builder core (full rebuild, deterministic) + the rebuild-and-diff fingerprint (D-OJ-15).
# ---------------------------------------------------------------------------------------------------
def build_outcomes(anchors: Sequence[Mapping], tape: pd.DataFrame, *, asof, built_at,
                   horizons: Sequence[int] = HORIZON_DAYS,
                   survive_days: int = SURVIVE_DAYS,
                   lookback_days: int = OUTCOME_LOOKBACK_DAYS,
                   milestones: Optional[str] = None) -> pd.DataFrame:
    """The SHAPE (i) build: one row per (anchor, horizon), for every horizon in the family.

    A FULL REBUILD, no incremental state (item 82): the anchors are event dates on tables that do not
    move, so the build is re-derivable and `built_at` is PROVENANCE, never a guard axis (D-OJ-15 --
    under a full rebuild every row carries the same stamp, so `built_at <= asof` is all-pass or
    all-fail and cannot bind).

    NO EPISODE-DERIVED ROW IS EVER WRITTEN (item 98(d)). Episode spans move when the artifact is
    rebuilt; shape (ii) is computed at query time by :func:`span_outcome` from the same rule module. An
    anchor carrying a span key RAISES rather than being quietly precomputed."""
    edges = tape_edges(tape)
    last_prints: dict[str, pd.DataFrame] = {}
    rows: list[dict] = []
    mode = milestones or milestone_mode()
    for a in anchors:
        if a.get("span_start") is not None or a.get("span_end") is not None:
            raise ValueError(
                "build_outcomes: an anchor carries a SPAN -- gold_futures_outcomes stores no "
                "episode-derived row (item 98d). Span moves are computed at query time by "
                "span_outcome() from the same rule module, because episode windows change under an "
                "artifact rebuild and a stored span would be stale by construction"
            )
        slug = str(a["leviathan_slug"])
        if slug not in last_prints:
            last_prints[slug] = FR.contract_last_print(_slug_frame(tape, slug))
        for h in horizons:
            row = anchored_outcome(tape, slug=slug, event_key=str(a["event_key"]),
                                   event_date=a["event_date"], horizon_days=int(h), asof=asof,
                                   tape_edge=edges.get(slug), last_print=last_prints[slug],
                                   survive_days=survive_days, lookback_days=lookback_days,
                                   built_at=built_at)
            if mode == MILESTONE_MODE_STORED:
                for k in MILESTONE_SESSIONS:
                    row[f"milestone_move_pct_{k}"] = (
                        path_move_pct_at(tape, slug=slug, contract_month=row.get("contract_month_used"),
                                         anchor_date=row.get("anchor_date") or row.get("event_date"),
                                         elapsed_sessions=k, asof=asof, tape_edge=edges.get(slug))
                        if row.get("status") == STATUS_CLOSED else None)
            rows.append(row)
    cols = list(OUTCOME_COLUMNS) + (list(milestone_columns()) if mode == MILESTONE_MODE_STORED else [])
    frame = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
    if len(frame):
        # int, matching the REGISTERED partition's Glue type (the tape's trade_year precedent) so the
        # card's sargable year bounds compare as numbers rather than as text.
        frame["event_year"] = frame["event_date"].astype("string").str.slice(0, 4).astype(int)
        frame = frame.sort_values(["leviathan_slug", "event_date", "event_key", "horizon_days"],
                                  kind="mergesort").reset_index(drop=True)
    else:
        frame["event_year"] = pd.Series(dtype="int64")
    return frame


def outcomes_fingerprint(frame: pd.DataFrame) -> str:
    """D-OJ-15's acceptance leg: a content digest of a built partition set with `built_at` EXCLUDED.

    Two consecutive full rebuilds at the same tape edge must produce the same digest. `built_at` is
    excluded precisely because it is provenance rather than data -- including it would make the check
    unfalsifiable in the wrong direction (always different), which is how a rebuild-and-diff gate ends
    up being quietly dropped."""
    work = frame.drop(columns=[c for c in ("built_at",) if c in frame.columns], errors="ignore")
    if len(work):
        work = work.sort_values([c for c in ("leviathan_slug", "event_date", "event_key",
                                             "horizon_days") if c in work.columns],
                                kind="mergesort")
    payload = work.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------------------------------
# D-OJ-13 -- the card lint. The card is what makes section 4 STRUCTURAL rather than prose.
# ---------------------------------------------------------------------------------------------------
# The compiled guard is `query._guard` -> `TableSpec.knowledge_col()`, which returns EXACTLY ONE column,
# and `_pub_lagged_asof` shifts the RHS literal -- so `readable_date <= asof - 6` IS item 46's rule
# compiled, with survive_days(5) + the tape's own lag(1) carried in the one field that can carry it.
OUTCOME_CARD_FIELDS: dict[str, object] = {
    "shape": "wide",
    "commodity_col": "leviathan_slug",
    "period_col": "event_date",              # the reader-facing PERIOD is the EVENT (item 46a)
    "period_type": "date",
    "date_col": "readable_date",             # the DATA axis the guard compiles on
    "knowledge_date_col": "readable_date",
    "knowledge_semantics": "data_date",      # NOT vintage: that drags build_sql's latest-vintage
    #                                          ROW_NUMBER collapse, which is wrong for this grain
    "publication_lag_days": OUTCOME_PUBLICATION_LAG_DAYS,
    "year_col": "event_year",                # the registered year partition -> sargable bounds
    "contract_month_col": "contract_month_used",
    "settle_kind_col": "settle_kind",
    "currency_col": "currency",
}


def _read_card() -> tuple[Optional[Mapping], str]:
    """`(card, source)` where source is 'served' | 'staged' | 'none'. The SERVED registry wins the
    moment the card is pasted into it, so nothing has to be un-wired at that point."""
    try:
        import yaml

        from leviathan.graphrag import extract as ex
        served = ex._CFG / "numbers" / "tables.yaml"
        if served.exists():
            doc = yaml.safe_load(served.read_text(encoding="utf-8")) or {}
            got = (doc.get("tables") or {}).get(OUTCOME_TABLE_ID)
            if got:
                return got, "served"
        staged = ex._CFG / "numbers" / "cards" / f"{OUTCOME_TABLE_ID}.yaml"
        if staged.exists():
            doc = yaml.safe_load(staged.read_text(encoding="utf-8")) or {}
            got = (doc.get("tables") or {}).get(OUTCOME_TABLE_ID)
            if got:
                return got, "staged"
    except Exception:  # noqa: BLE001 -- an unreadable config is a lint error, not a crash
        return None, "none"
    return None, "none"


def lint_outcome_card(card: Optional[Mapping] = None) -> list[str]:
    """D-OJ-13: the `gold_futures_outcomes` card is coherent with THIS module's constants.

    The load-bearing pin is `publication_lag_days == SURVIVE_DAYS + 1`. If `survive_days` ever
    changes and the card does not, the compiled guard silently admits rows whose CONTRACT SELECTION used
    tape past the boundary -- and per-anchor survivor-vs-front divergence is median 1.2-2.5pp / p90
    4.6-7.2pp, the same order as the claim itself. The two knobs are one knob.

    Reads the RAW card (authoritative regardless of any load-time whitelist drop) from the SERVED
    registry, falling back to the STAGED card at `configs/graphrag/numbers/cards/<table>.yaml`. The card
    is staged until its SILVER-F010 contract + registration wiring land in one atomic change (the
    staged file's own header carries that recipe), and the fallback is what keeps the clamp arithmetic
    pinned while the card is in transit rather than only after it arrives."""
    errs: list[str] = []
    if card is None:
        card, source = _read_card()
        if source == "none":
            # VACUOUS UNTIL THE CARD EXISTS -- the `check_cot_register` / `check_futures_eod` idiom.
            # Both `configs/graphrag/numbers/tables.yaml` and `configs/graphrag/numbers/cards/*.yaml`
            # are gitignored, so a hard error here makes the BUILD red on an untracked file: a fresh
            # clone fails a lint about a card it was never given. What keeps serving safe in that state
            # is not this lint but `registry.WHITELIST_ABSENT_DEFAULT`, which drops the id at load so
            # every build_sql lookup raises. The lint goes NON-VACUOUS the moment a card exists at
            # either path -- which is the state that can actually compile a guard.
            return []
    if not card:
        return [f"outcomes card: {OUTCOME_TABLE_ID} is EMPTY"]
    for field, want in sorted(OUTCOME_CARD_FIELDS.items()):
        got = card.get(field)
        if got != want:
            errs.append(f"outcomes card: {field} is {got!r}, expected {want!r}")
    lag = card.get("publication_lag_days")
    if lag != SURVIVE_DAYS + TAPE_PUBLICATION_LAG_DAYS:
        errs.append(
            f"outcomes card: publication_lag_days {lag!r} != SURVIVE_DAYS "
            f"({SURVIVE_DAYS}) + tape lag ({TAPE_PUBLICATION_LAG_DAYS}) -- the survival margin "
            f"is HALF THE PIT BOUNDARY and the card is the only place it compiles into SQL")
    parts = list(card.get("partitions") or []) or list(card.get("partition_cols") or [])
    if tuple(parts) != OUTCOME_PARTITIONS:
        errs.append(f"outcomes card: partitions {parts} != {list(OUTCOME_PARTITIONS)} (registered "
                    f"partitions, projection FORBIDDEN -- the S3 LIST-storm class)")
    if card.get("levels_only"):
        errs.append("outcomes card: levels_only must be false -- this table IS the cross-date delta, "
                    "computed on ONE contract so no splice exists to fence")
    metrics = set((card.get("metrics") or {}))
    for m in ("move_pct", "move_abs"):
        if m not in metrics:
            errs.append(f"outcomes card: metric {m!r} is not declared -- an outcome table whose move "
                        f"columns are unreadable serves nothing")
    for banned in sorted(metrics):
        if st.is_banned_name(banned):
            errs.append(f"outcomes card: metric {banned!r} matches the forward-looking ban "
                        f"(fit|trend|forecast|project|extrapolat|predict) -- descriptive history only")
    return errs


def lint_outcome_row_invariants(rows: Sequence[Mapping]) -> list[str]:
    """THE CLAMP AS A DATA INVARIANT -- what makes it structural rather than a column name.

      (1) a row that carries a MOVE guards on its horizon CLOSE (`readable_date == endpoint_date`), so
          D-OJ-13's compiled predicate is byte-identical for every move-bearing row;
      (2) a PENDING row carries NO forward measurement (no px1, no move, no endpoint) AND NO SELECTION
          (no px0, no contract_month_used -- both were chosen with tape past the boundary) and DOES
          carry its close date -- it is a timing statement, never a coverage gap;
      (3) a DECLINED row carries a known reason and no move;
      (4) every closed row names the contract it was measured on (or is the cash-index basis, which has
          no contract axis) -- the 25.5-31.7% front-share is exactly why a bare move is a
          mis-attribution -- and stands on AT LEAST ONE realized session: a window over which no
          session elapsed is a zero-length window, and +0.0% across it is a fabricated magnitude, not a
          measurement (`DECLINE_NO_ENDPOINT_SESSION` is where that case belongs).
    The builder runs this over its own output; a test runs it over fixtures."""
    errs: list[str] = []
    for i, r in enumerate(rows):
        status = str(r.get("status") or "")
        has_move = r.get("move_pct") is not None and not pd.isna(r.get("move_pct"))
        if has_move and r.get("readable_date") != r.get("endpoint_date"):
            errs.append(f"row {i}: carries a move but readable_date {r.get('readable_date')!r} != "
                        f"endpoint_date {r.get('endpoint_date')!r} -- a move must never be readable "
                        f"before its horizon closes")
        if status == STATUS_PENDING:
            for k in ("px1", "move_abs", "move_pct", "endpoint_date"):
                if r.get(k) is not None and not pd.isna(r.get(k)):
                    errs.append(f"row {i}: pending row carries {k}={r.get(k)!r} -- a horizon that has "
                                f"not closed has no forward measurement")
            for k in ("px0", "contract_month_used"):
                # THE SELECTION MIRROR of clamp_row's strip: the survivor was picked by asking whether it
                # still printed past a close that has not happened, so px0 and the delivery month are
                # future-conditioned values on a row that may state only timing.
                if r.get(k) is not None and not pd.isna(r.get(k)):
                    errs.append(f"row {i}: pending row carries {k}={r.get(k)!r} -- the contract was "
                                f"SELECTED with tape past this boundary, so a pending row states no "
                                f"price and names no delivery month")
            if not r.get("horizon_close_date"):
                errs.append(f"row {i}: pending row has no horizon_close_date -- pending RENDERS with "
                            f"its close date, else it reads as a coverage gap")
        elif status.startswith(STATUS_DECLINED_PREFIX):
            if str(r.get("decline_reason") or "") not in DECLINE_REASONS:
                errs.append(f"row {i}: decline_reason {r.get('decline_reason')!r} is not in the "
                            f"declared vocabulary {list(DECLINE_REASONS)}")
            if has_move:
                errs.append(f"row {i}: declined row carries a move")
        elif status == STATUS_CLOSED:
            if not has_move:
                errs.append(f"row {i}: closed row carries no move_pct")
            if r.get("basis") == BASIS_SURVIVOR and not r.get("contract_month_used"):
                errs.append(f"row {i}: survivor-basis row does not name its contract -- the survivor is "
                            f"the front contract in only 25.5-31.7% of anchors, so an unnamed contract "
                            f"is a scope mis-attribution")
            rs = r.get("realized_sessions")
            if rs is None or pd.isna(rs) or int(rs) < 1:
                errs.append(f"row {i}: closed row has realized_sessions={rs!r} -- no session elapsed "
                            f"between the anchor and the endpoint, so the move is a zero-length "
                            f"window's +0.0%, which is a fabricated magnitude rather than a measurement")
        elif status:
            errs.append(f"row {i}: unknown status {status!r}")
    return errs
