"""T2B pattern-records SERVING surface -- the SQL-lane aggregation over gold_pattern_records.

The daily engine-replay sweep (jobs/batch/pattern_records_sweep_task.py, Writer A) writes ONE row per
(record_kind, contract, driver_or_chain_id, as_of_date) recording the deterministic engine's OWN
fired/declined verdict AT that asof. This module is the READ half: it turns "has this (driver, contract)
pair fired before, and on how many sweeps" into a CITABLE [N] fact read from an ordinary observed table
(plan secs 4 / 4.2 / 4.3), register-fenced to OBSERVATION only.

Four doctrine points this module enforces, all load-bearing (plan F8 / F7 / 3.3; coverage-plan W2 / W4):

  * PRESENCE SEMANTICS (F8). The aggregations are SCALAR COUNT / MIN queries -- NEVER bare GROUP-BYs.
    A scalar aggregate ALWAYS returns exactly one row: over zero matched rows COUNT is 0 and MIN is
    NULL, so an in-catalog pair whose sweeps all DECLINED yields a materialized `recorded_firings=0`
    (a citable 0), and a pair OUTSIDE the swept catalog yields `sweeps_total=0` (distinguishable as
    "not covered"). A bare GROUP-BY would return an EMPTY set that injects NOTHING, leaving the model
    in its no-ledger state where it mints a cross-day streak from the within-turn pace figure -- the
    exact fabrication this feature exists to close.

  * PROVENANCE NEVER MIXES SILENTLY (F5 / 3.3). Every aggregation pins ONE provenance class. The
    default persistence read filters ``provenance='daily_sweep'`` (today's sweep accruing forward);
    the backfill base-rate read is a SEPARATE, explicitly-labelled path filtering
    ``provenance='backfill_grid'`` -- an ENGINE base rate over vintaged-leg replay asofs, framed as
    such, NEVER as "N of the last M daily sweeps" (the marquee is unrealizable at flip: the live
    ledger is ~1 partition deep -- F7).

  * THE DENOMINATOR COUNTS ONLY WHAT WAS EVALUABLE (2026-07-25 gate defect D1). A sweep that DECLINED
    because the engine could not read the data is the engine being BLIND, not the signal being absent;
    folding those into the base-rate denominator inverts the reading. The 94468a0b gate printed "firing
    on 9 of 156 weekly replay asofs" for corn_cbot x export_pace -- technically true, and read by a desk
    as a ~6% rare event. The probed truth: 147 of the 156 declined with decline_reason='fetch_error'
    (ESR vintage snapshots begin 2026-05-24, so 2023-08-05..2026-05-23 had NOTHING to replay against),
    genuine "evaluated and did not fire" = ZERO, and the 9 firings are 9 CONSECUTIVE weeks -- it fired on
    every week it could be measured, a 100%-of-measurable persistent condition. Opposite conclusions from
    the same true number. So `sweeps_evaluable` is a SEPARATE, ADDITIVE column: `sweeps_total` keeps its
    old meaning (raw attempted, honest context) so nothing downstream misreads an old field with a new
    meaning, and every rate the prose states is over the evaluable count with its covered window NAMED.

  * A RATE NEEDS VARIANCE AND INDEPENDENT OBSERVATIONS, NOT A ROW COUNT (coverage-plan W2). The count
    floor above is necessary and not sufficient: re-censused over all 158 canonical partitions, 163 of the
    ledger's 251 pairs clear the shipped floor (172 at a height of 8) and every one of them is a CONSTANT
    (fired on all its evaluable sweeps, or on none). Two further predicates gate the rate sentence -- DISCRIMINATION
    (0 < fired < evaluable) and VINTAGE DEPTH (the evaluable sweeps must stand behind enough distinct
    source states to be independent observations; nine evaluable pace asofs resolved to three ESR
    vintages, one serving seven of them). Each suppression reason gets its OWN sentence: see pr_rate_gate.

  * LEAKED HISTORY IS NOT CITABLE HISTORY (coverage-plan W4). cascade x backfill_grid is refused outright
    at the leg seam -- the as-of axis those verdicts were replayed against is synthesized. See
    PR_FENCED_READS.

AWS-free + engine-agnostic: every SQL string is ANSI (COUNT / CASE / MIN / substr) so it runs
byte-identically on the pg mirror (serving), Athena, and sqlite (tests). The as-of guard is
substr(cast(col as varchar),1,10) <= asof -- the DP-5 timestamp normalization so a physical
`written_at` timestamp and its TEXT pg mirror compare identically at date grain.

J5 -- THE OUTCOME AXIS (OUTCOMES_JOIN plan sec 5 / item 76-85), the second half of this module.
    The ledger records a VERDICT and nothing else: 19 physical columns, no price, no forward return.
    Re-censused over 162 partitions the per-pair (fired, evaluable) takes exactly three CONSTANT values
    and the pairs with `0 < fired < evaluable` -- the only shape that HAS a rate -- number ZERO. So the
    firing rate is not thin, it is DEGENERATE, and no floor height and no forward-return column changes
    that: `pr_rate_gate` tests NO_VARIANCE before VINTAGE and a return column moves neither `recorded`
    nor `evaluable` (D-OJ-12). J5 therefore closes NONE of the six suppressions and states a SEPARATE,
    SEPARATELY GATED sentence over a DIFFERENT quantity -- "across the N times this pair fired, price
    did Y over the next 30/60/90 days" -- which has real variance by construction because it is a
    continuous measure rather than a constant binary verdict.

    Everything measured lives in `gold_pattern_outcomes`, a SEPARATE derived table (D-OJ-11: the grain
    differs 3:1, and widening the registered ledger touches regenerated DDL + reconcile + the pg mirror,
    which is the T2b failure path). This module owns the READ, the GATE and the RENDER; the join itself
    is `numbers.outcomes` (one engine, one basis, one clamp) and the build is
    jobs/batch/gold_pattern_outcomes_task.py.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from typing import Optional, Sequence

from leviathan.graphrag.numbers import stats as st

# ── the ledger's own vocabulary (MUST mirror jobs/batch/pattern_records_sweep_task.py; a drift test
#    pins the equality so the serving read can never diverge from what the sweep wrote) ──────────────
PR_TABLE = "gold_pattern_records"
KIND_CASCADE = "cascade"
KIND_PACE = "pace"
KIND_CHAIN = "chain"
V1_KINDS = frozenset({KIND_CASCADE, KIND_PACE, KIND_CHAIN})
VERDICT_FIRED = "fired"
VERDICT_DECLINED = "declined"
PROV_DAILY_SWEEP = "daily_sweep"
PROV_BACKFILL_GRID = "backfill_grid"

# ── DECLINE CLASSIFICATION: which declines are real NON-EVENTS and which are BLINDNESS ─────────────
# Census of the live canonical ledger (S3-direct pyarrow over all 156 partitions of
# s3://leviathan-dev-shahem-001/gold/pattern_records/, 39,156 rows -- the `_shadow/` staging copy under
# the same prefix is EXCLUDED; counting it double-reports every figure):
#     25,428  cascade  fired      (no reason)
#     10,920  cascade  declined   region-unresolved
#      1,404  cascade  declined   waived
#      1,323  pace     declined   fetch_error
#         81  pace     fired      (no reason)
# Three distinct decline_reason values exist TODAY -- all three blindness -- but the classification below
# is over the WRITER'S FULL DECLARED VOCABULARY (pattern_records_sweep_task PACE_/CHAIN_/CASCADE_
# DECLINE_REASONS), not just what happens to be present, so a reason that starts being written tomorrow
# is already classified. A drift test pins the union against the writer's enums.
#
# EVALUABLE NON-EVENT -- the engine held real resolved data at that asof and produced no firing from it.
# `thin_history` / `hop_thin` are the ONLY two, and the call is deliberate:
#   * they are reachable ONLY after the fetch and the scope resolution SUCCEEDED -- classify_pace_decline
#     tests `status != ok` -> fetch_error FIRST, so a thin_history row means the engine did read the
#     vintage series that existed at that asof;
#   * they are the only bucket that CAN hold a genuine non-event: cascade._pace_legs declines silently
#     when a resolved >=2-point series yields no window_change row and no >=2 run, and
#     classify_pace_decline's terminal `return PACE_DECLINE_THIN` catches exactly that fall-through.
#     Classifying them blind would make evaluable == fired identically for every pair in the v1
#     vocabulary -- a "base rate" structurally incapable of printing anything but 100%.
# The overload is real and worth naming: `thin_history` covers BOTH "fewer than MIN_STREAK_N collapsed
# periods" (arguably thin data) and that fall-through (a true non-event). It is counted as evaluable; the
# coverage floor + the named window below are what keep a thin history from reading as a rate.
PR_NONEVENT_DECLINES = frozenset({"thin_history", "hop_thin"})

# NOT EVALUABLE -- the engine never reached a verdict on data. Three sub-classes, all denominator poison:
#   fetch/probe failure      fetch_error, probe-error, error, root_not_grounded, hop_dark
#   resolution failure       region_unresolved, region-unresolved, country-not-a-psd-title,
#                            commodity-slug-miss, metric-empty-for-country, table-not-registered,
#                            uncertified-table   (no query was ever formed against data)
#   structural / excluded    annual_grain, cross_section_undeclared, degenerate, cap, waived
#                            (the quantity is undefined for the pair, or the pair is administratively
#                             waived -- these are ASOF-INVARIANT, so counting them inflates the
#                             denominator by a constant on every single sweep, forever)
PR_BLIND_DECLINES = frozenset({
    "fetch_error", "region_unresolved", "annual_grain", "cross_section_undeclared",
    "root_not_grounded", "hop_dark", "degenerate", "cap", "error",
    "country-not-a-psd-title", "commodity-slug-miss", "metric-empty-for-country",
    "uncertified-table", "table-not-registered", "region-unresolved", "waived", "probe-error",
})

# COVERAGE FLOOR -- below this many EVALUABLE sweeps the prose states NO rate at all (it still states the
# firing count and the covered window; F8's materialized zero is never suppressed -- that is the
# anti-fabrication mechanism itself). Chosen FROM the probed coverage distribution, which is trimodal and
# has a hole in it: across the 251 (kind, contract, driver, backfill_grid) pairs in the live ledger the
# evaluable count is 0 (79 pairs, every sweep blind), 9 (9 pairs -- the pace family, whose ESR vintages
# start 2026-05-24), or 156 (163 pairs, every sweep fired). NOTHING sits between 10 and 155, so the only
# boundary the data actually offers is the one between the 9-week pace slice and full coverage.
# 13 = one quarter of weekly checks: the smallest span a desk would call a history on a weekly grid, it
# lands inside that empty gap (so the floor is doing no knife-edge work on today's data -- it is a
# forward-looking gate that binds the week weekly coverage reaches a quarter), and it is strictly above
# the flagship's 9. Nine consecutive weeks, on a grid whose data only begins nine weeks before the asof,
# is a young series however honestly it is phrased: at n=9 even a perfect 9/9 carries a Wilson 95% lower
# bound of ~0.70, i.e. "somewhere between 7-in-10 and always" -- not a rate worth putting in front of a
# desk. CONSEQUENCE, stated plainly: today every pair the serving detector can reach is a pace pair with
# 9 evaluable sweeps, so this floor suppresses the rate on 100% of currently-reachable queries and the
# card ships the count-plus-coverage sentence until the grid deepens (~2026-08-15 at one asof/week).
PR_MIN_EVALUABLE_SWEEPS = 13

# ── THE VARIANCE GATE: coverage COUNT is the wrong SHAPE for a rate (coverage-plan W2) ─────────────
# The floor above gates on how MANY sweeps were evaluable. The re-census of the live ledger proves that
# is the wrong predicate -- not too low, the wrong QUANTITY. Over the 251 (kind, contract, driver) pairs
# in all 158 canonical partitions (39,658 rows, S3-direct pyarrow, `_shadow/` excluded) the per-pair
# (fired, evaluable) distribution takes exactly THREE values and every one of them is a CONSTANT:
#
#     (158, 158) -> 163 pairs   cascade   fired on every sweep it could evaluate
#     (  0,   0) ->  79 pairs   cascade   never evaluable at all (region-unresolved 70 / waived 9)
#     ( 11,  11) ->   9 pairs   pace      fired on every sweep it could evaluate
#
# Pairs with `0 < fired < evaluable` -- the only shape that HAS a rate -- number ZERO, and no floor height
# rescues it: >=8 admits 172 pairs, >=13 (the shipped height) and >=20 admit 163, and the non-degenerate
# count is 0 at every one. A count floor therefore admits 163 pairs today and every one of them would
# print "100%". The predicate a rate actually needs is DISCRIMINATION:
# the pair must have both fired and not-fired among the sweeps that could be measured. Anything else is a
# constant, and the honest render of a constant is to SAY it is one ("fired on all N it could evaluate"),
# never to launder it through the grammar of a base rate. See pr_rate_gate.
#
# ── THE VINTAGE DENOMINATOR: sweeps are not independent observations ───────────────────────────────
# The second wrong-shape defect, and the one the count floor cannot see at all. The 9 evaluable pace
# sweeps in the flagship slice resolved to only THREE distinct ESR source vintages (`2026-05-24` served
# SEVEN of the nine asofs, `2026-07-17` one, `2026-07-24` one). A weekly-published series read on a
# weekly-or-denser grid re-reads the SAME snapshot repeatedly: the denominator counts re-reads, and a rate
# over re-reads overstates its own evidence by whatever the re-read factor happens to be.
#
# WHAT THE LEDGER ACTUALLY CARRIES -- probed, not assumed. The row does NOT record the resolved vintage.
# The physical schema is 19 columns (registry contract configs/silver/tables/gold_pattern_records.yaml)
# and none of them is a vintage; `extra` is the only free-form slot and across ALL 158 partitions it holds
# exactly three keys -- `collapse`, `metric`, `table` -- with ZERO date-like values anywhere in it. So a
# true `COUNT(DISTINCT vintage)` is NOT COMPUTABLE from this ledger, and the honest closure is a
# writer-side change (stamp the resolved vintage into `extra`), not a read-side one.
#
# WHAT IS IMPLEMENTED INSTEAD, named as the approximation it is: the count of distinct recorded
# `window_change` values among the evaluable sweeps (vintage_depth_sql) -- a proxy for "how many distinct
# source snapshots did the engine actually see".
#
# WHICH COLUMN, AND WHY ONLY THAT ONE. This was MEASURED against the one pair whose vintage truth is known
# (corn_cbot x export_pace: ESR vintage 2026-05-24 served seven asofs, 2026-07-17 one, 2026-07-24 three).
# Per-column behaviour over those 11 fired sweeps:
#
#     window_change  2 distinct   VINTAGE-STABLE   exactly one value per vintage, on all three
#     n_points       8 distinct   asof-varying     counts DOWN 8,7,6,5,4,3,2 across the seven asofs the
#                                                  SAME snapshot served -- it counts the points remaining
#                                                  in an asof-relative lookback, so it tracks the asof,
#                                                  not the source
#     streak_len / streak_dir / n_rows             follow n_points out of the window and vary within a
#                                                  vintage too
#     grain          1 distinct   constant, carries no information
#
# window_change is stable BY CONSTRUCTION, not by luck: it is computed on the terminal windows of the
# series, and within a fixed snapshot the series end is fixed, so the last two windows are the same two
# periods no matter how far the asof has moved past them. The others slide with the asof.
# The joint 6-column state that this originally used turned 3 true vintages into NINE states -- FAIL-OPEN,
# the one direction this gate must never fail. It was caught by probing the live pg mirror, not by
# reasoning, which is why the column choice is pinned by a test.
#
# ERROR DIRECTION, measured: on that same pair the proxy returns 2 against a truth of 3, because vintages
# 2026-07-17 and 2026-07-24 happen to yield the SAME window_change. It UNDER-counts -- the fail-closed
# direction, and the same one _evaluable_pred() deliberately picks. It under-counts a SECOND way, also
# fail-closed: a decline records no measurement at all (the writer leaves window_change NULL), so every
# evaluable-but-declined sweep collapses into ONE shared state however many vintages produced them.
# _cadence_cap() bounds the residual fail-open risk for any future surface whose measurement is less
# stable than this one: at most one NEW vintage can appear per publication week, true for every table in
# VINTAGED_TABLES (ESR weekly, WASDE/PSD monthly) and fail-closed for anything faster.
# The estimate is deliberately NOT printed to the reader: it is an approximation, and this module's
# doctrine is that every figure a line states is a RECORDED OBSERVATION. It rides the signal only.
PR_MIN_DISTINCT_VINTAGES = 13
# Deliberately EQUAL to PR_MIN_EVALUABLE_SWEEPS, and that equality is the point rather than a coincidence:
# the floor's whole justification (a quarter of weekly checks; a Wilson 95% lower bound of ~0.70 at n=9)
# is an argument about INDEPENDENT OBSERVATIONS. Sweeps were only ever a proxy for those. Separate
# constant so the two can be tuned apart once the writer records real vintages.

# The recorded measurement whose distinct values stand in for "which source snapshot did the engine read".
# ONE column, chosen by measurement (above) -- adding the asof-varying ones makes the gate fail OPEN.
# A physical column of the registered contract, read by a SEPARATE, LAZY query (see _vintage_depth) so
# that this extra schema dependency can never break the card's primary presence read on a mirror that lags
# the contract -- a failure there costs the RATE (fail-closed), not the citable count.
PR_VINTAGE_STATE_COLUMNS = ("window_change",)

# ── READ-SIDE LEAKAGE FENCE (coverage-plan W4) ─────────────────────────────────────────────────────
# cascade x backfill_grid is REFUSED at the read seam. Not a coverage judgement -- a LEAKAGE one:
#   * the backfill grid replays cascade verdicts against `silver_psd`, whose as-of axis is SYNTHESIZED.
#     `_compute_psd_release_dates` (transforms/bronze_to_silver/usda_psd.py) discards bronze's real
#     download stamp and writes a closed-form label (always the 10th of a marketing-year-relative month)
#     computed from `month_code in [0,12]`, which structurally cannot encode an off-cycle revision. The
#     whole 765-value `release_date` axis is manufactured from exactly TWO real bronze observations.
#   * measured consequence: 739 keys CHANGED VALUE under an unchanged computed release_date, and a
#     further 9,292 keys exist in the July bronze but not the May bronze while carrying a computed
#     release_date backdated as far as 2020-11-10. A cascade verdict is an EXISTENCE probe (n_rows >= 1;
#     cascade_census.pg_probe is "a whole-history existence probe: agg=latest, no period window"), so
#     that second, 12.6x larger channel maps EXACTLY onto the quantity these rows record.
# The 37,752 such rows stay on S3 untouched -- they are an audit record of what the engine did, and
# deleting them would destroy evidence. They are simply not CITABLE HISTORY. Serving has no cascade path
# today, so the observable effect of this fence is ZERO: it is a RATCHET against a later, well-meaning
# widening, placed at the leg seam because that is the single funnel through which a citable [N] row can
# reach a reader. cascade x daily_sweep is NOT fenced -- a verdict recorded on the day it was reached has
# a real as-of; only the REPLAY over a manufactured axis is leaked.
PR_FENCED_READS = frozenset({(KIND_CASCADE, PROV_BACKFILL_GRID)})


def pr_read_fenced(kind: str, provenance: str) -> Optional[str]:
    """The leakage-fence slug for a (record_kind, provenance) pair, or None when the pair is readable."""
    return "cascade_backfill_leaky_asof" if (kind, provenance) in PR_FENCED_READS else None


# OBSERVATION-register fence (plan 4.3 / D8). These are the 6.8 fake-threshold + WS-COND
# premature-determinism failure words: a pattern-records line reports the COUNT and the DATES; the
# model INTERPRETS. `regime` / `trend` are legitimate elsewhere in the cascade voice, so this detector
# is applied ONLY to pattern-records lines (the bullet, the addendum, the injected leg prose) -- never
# the whole answer, so cascade regime language is untouched.
_PR_BANNED = re.compile(
    r"\b(signals?|set[- ]?ups?|regimes?|trends?|breakouts?|confirm(?:s|ed|ing)?|persistent|"
    r"momentum (?:is )?building)\b", re.I)


def pr_register_leaks(text: str) -> list[str]:
    """The banned OBSERVATION-register tokens present in one pattern-records line (empty == clean)."""
    return [m.group(0) for m in _PR_BANNED.finditer(text or "")]


def pattern_records_on() -> bool:
    """T2B card kill-switch (GRAPHRAG_PATTERN_RECORDS). Gates the gold_pattern_records SQL-lane card,
    its ## Conventions bullet, its lookup_number `table` enum entry, the answer.py `## Recorded history`
    addendum, AND the answer_numbers presence-dispatch -- so with the flag OFF the numbers-agent
    system_prompt + tool_schema + the reader-facing system string are BYTE-IDENTICAL to pre-feature (the
    identical-answers smoke, plan 7.6). DEFAULT-OFF, fail-closed: only case-insensitive on/1/true
    exposes it. Read PER CALL (never memoized) so the env-flip rollback is live -- no redeploy (the
    _pace_leg_on idiom, answer.py)."""
    return os.environ.get("GRAPHRAG_PATTERN_RECORDS", "").strip().lower() in ("on", "1", "true")


def _q(v: str) -> str:
    """Single-quote-safe SQL literal (mirrors query._q)."""
    return "'" + str(v).replace("'", "''") + "'"


def _date_at(col: str) -> str:
    """DP-5: the text-comparable date render of a column that may be a physical TIMESTAMP (Athena
    `written_at`) or its TEXT pg/sqlite mirror -- substr(cast(...),1,10) collapses both to 'YYYY-MM-DD'
    so the as-of guard compares identically on every backend. CAST is a no-op on a TEXT column."""
    return f"substr(cast({col} as varchar), 1, 10)"


def _evaluable_pred() -> str:
    """The ANSI predicate for "this sweep ACTUALLY EVALUATED the pair": it fired, or it declined for a
    reason that means the engine held data and produced no firing from it.

    Stated POSITIVELY (an IN-list of the non-event reasons) rather than negatively (NOT IN the blind
    list), and that direction is the fail-closed one: a decline_reason this build has never heard of
    falls OUTSIDE the evaluable set, which SHRINKS coverage toward the floor and suppresses the rate --
    instead of silently swelling the denominator, which is the 9-of-156 defect itself. NULL-safe on every
    backend: a fired row's decline_reason is NULL, `NULL IN (...)` is NULL, and `TRUE OR NULL` is TRUE,
    so fires count; `FALSE OR NULL` is NULL, so a malformed decline with no reason does not."""
    lits = ", ".join(_q(r) for r in sorted(PR_NONEVENT_DECLINES))
    return f"(verdict = 'fired' OR decline_reason IN ({lits}))"


def presence_sql(contract: str, driver_or_chain_id: str, *, kind: str, asof: str,
                 provenance: str = PROV_DAILY_SWEEP) -> str:
    """The SCALAR presence aggregation (F8). Returns EXACTLY ONE row -- always, by construction:

        recorded_firings  COUNT of verdict=fired rows (a materialized 0 when only declines / not covered)
        sweeps_total      COUNT(*) of swept rows for the pair (0 == the pair is NOT in the swept catalog)
                          -- the RAW ATTEMPTED total, unchanged meaning, kept as honest context
        sweeps_evaluable  COUNT of sweeps the engine actually evaluated (fired + non-event declines);
                          the ONLY honest denominator for a rate -- see PR_NONEVENT_DECLINES
        declined_count    COUNT of verdict=declined rows
        first_recorded    MIN(as_of_date) among fired rows (NULL when recorded_firings=0)
        last_recorded     MAX(as_of_date) among fired rows (NULL when recorded_firings=0)
        first_evaluable   MIN(as_of_date) among EVALUABLE rows -- the start of the covered window
        last_evaluable    MAX(as_of_date) among EVALUABLE rows -- the end of the covered window

    The two windows are deliberately separate: the fired window answers "since when has it been firing",
    the evaluable window answers "what span was ever measurable" -- and a reader who is shown only the
    first cannot tell that the rest of the grid was dark.

    PIT-guarded on BOTH axes: as_of_date <= asof (the data/verdict axis) AND written_at <= asof (the
    ingest/knowledge axis -- so a backfill_grid row written in 2026 is invisible at a past asof, F7).
    Provenance is PINNED (never mixed): the default is the daily_sweep class."""
    where = [
        f"record_kind = {_q(kind)}",
        f"contract = {_q(contract)}",
        f"driver_or_chain_id = {_q(driver_or_chain_id)}",
        f"provenance = {_q(provenance)}",
        f"{_date_at('as_of_date')} <= {_q(asof)}",
        f"{_date_at('written_at')} <= {_q(asof)}",
    ]
    ev = _evaluable_pred()
    return (
        "SELECT "
        "COUNT(CASE WHEN verdict = 'fired' THEN 1 END) AS recorded_firings, "
        "COUNT(*) AS sweeps_total, "
        f"COUNT(CASE WHEN {ev} THEN 1 END) AS sweeps_evaluable, "
        "COUNT(CASE WHEN verdict = 'declined' THEN 1 END) AS declined_count, "
        "MIN(CASE WHEN verdict = 'fired' THEN as_of_date END) AS first_recorded, "
        "MAX(CASE WHEN verdict = 'fired' THEN as_of_date END) AS last_recorded, "
        f"MIN(CASE WHEN {ev} THEN as_of_date END) AS first_evaluable, "
        f"MAX(CASE WHEN {ev} THEN as_of_date END) AS last_evaluable "
        f"FROM {PR_TABLE} WHERE " + " AND ".join(where)
    )


def baserate_backfill_sql(contract: str, driver_or_chain_id: str, *, kind: str, asof: str) -> str:
    """The EXPLICITLY-LABELLED backfill ENGINE base-rate read (plan 3.3 / 4.1 / 6.1). Filters
    provenance='backfill_grid' ONLY -- the deterministic quantification's fired/total over the bounded
    weekly VINTAGED-leg replay grid. It is framed as an engine base rate ("fired on N of M weekly replay
    asofs"), NEVER as a daily firing history. Same scalar-presence shape as presence_sql, so an in-grid
    pair that never fired still cites a materialized 0."""
    return presence_sql(contract, driver_or_chain_id, kind=kind, asof=asof,
                        provenance=PROV_BACKFILL_GRID)


def _value_state_expr() -> str:
    """The ANSI render of one sweep's RECORDED VALUE-STATE as a single comparable scalar, so
    COUNT(DISTINCT ...) counts distinct source states. NULL-safe by construction: `a || b` is NULL if
    either side is NULL on every backend, so each column is COALESCEd to a sentinel first -- a fired row
    with NULL streak_len and a declined row with NULL everything are then two well-defined states rather
    than two NULLs that COUNT(DISTINCT) would drop.

    CAST(<double> AS varchar) is the one backend-sensitive piece: a backend that rendered fewer digits
    would COLLAPSE two nearby values into one state. That is the fail-CLOSED direction (fewer states ->
    more suppression), and the count is only ever compared against a threshold within a single backend's
    own render, never across backends, so no parity claim rests on it."""
    return " || '|' || ".join(f"COALESCE(CAST({c} AS varchar), '~')" for c in PR_VINTAGE_STATE_COLUMNS)


def vintage_depth_sql(contract: str, driver_or_chain_id: str, *, kind: str, asof: str,
                      provenance: str = PROV_DAILY_SWEEP) -> str:
    """The distinct-value-state count over the EVALUABLE sweeps of one pair -- the vintage-depth proxy
    (see PR_MIN_DISTINCT_VINTAGES for what it approximates, why it is an approximation, and its measured
    error direction). Same scalar shape and the same two PIT axes and pinned provenance as presence_sql,
    so it can never see a row the presence read could not; the evaluable predicate moves into the WHERE
    clause because the count is defined only over sweeps that actually saw data."""
    where = [
        f"record_kind = {_q(kind)}",
        f"contract = {_q(contract)}",
        f"driver_or_chain_id = {_q(driver_or_chain_id)}",
        f"provenance = {_q(provenance)}",
        f"{_date_at('as_of_date')} <= {_q(asof)}",
        f"{_date_at('written_at')} <= {_q(asof)}",
        _evaluable_pred(),
    ]
    return (f"SELECT COUNT(DISTINCT {_value_state_expr()}) AS distinct_value_states "
            f"FROM {PR_TABLE} WHERE " + " AND ".join(where))


def _cadence_cap(first_evaluable, last_evaluable, evaluable: int) -> int:
    """Upper bound on how many distinct source vintages a span COULD hold, from the publication cadence:
    at most ONE new vintage per week. True for every table in the writer's VINTAGED_TABLES (silver_esr
    weekly, silver_wasde / silver_psd monthly) and fail-closed for anything faster. This is what bounds
    the value-state proxy's one fail-OPEN mode -- a single vintage read at many asofs yielding different
    values would inflate the state count, but it cannot inflate it past the number of weeks that elapsed.

    Unparseable / absent dates return the evaluable count, i.e. the cap goes INERT rather than zeroing the
    estimate: the cap is a refinement of the proxy, not the proxy itself, and the proxy is already the
    fail-closed half."""
    try:
        import datetime as _dt
        a = _dt.date.fromisoformat(str(first_evaluable)[:10])
        b = _dt.date.fromisoformat(str(last_evaluable)[:10])
    except (TypeError, ValueError):
        return max(int(evaluable), 0)
    return max(abs((b - a).days) // 7 + 1, 1)


def _one_row(rows) -> dict:
    """The single scalar row a presence/baserate query returns (defensive: a mirror gap that returns []
    is treated as the not-covered 0 -- never a crash, never a fabricated firing)."""
    if rows:
        return rows[0] or {}
    return {"recorded_firings": 0, "sweeps_total": 0, "sweeps_evaluable": 0, "declined_count": 0,
            "first_recorded": None, "last_recorded": None,
            "first_evaluable": None, "last_evaluable": None}


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# ── serving dispatch: a persistence question -> injected [N] legs (the _esr_aggregate_legs idiom) ──
_PROV_LABEL = {
    PROV_DAILY_SWEEP: "recorded daily sweeps",
    PROV_BACKFILL_GRID: "weekly replay asofs",
}

# The reasons a firing RATE may not be stated. Each one is a DIFFERENT FACT about the ledger and gets its
# own sentence in pattern_records_answer -- collapsing any two of them into shared wording would let a
# reader (or a model reading the preface) mistake "we have never looked here" for "we looked and it was
# always true", which is the entire failure class this card exists to close.
PR_SUP_NOT_COVERED = "not_covered"        # the pair is outside the swept catalog -- nothing was attempted
PR_SUP_NOTHING_EVALUABLE = "nothing_evaluable"  # attempted, but every sweep was blind -- nothing measured
PR_SUP_NO_FIRING = "no_firing"            # measured, and it never fired -- a constant, not a rate
PR_SUP_TOO_THIN = "too_thin"              # measured history shorter than the coverage floor
PR_SUP_NO_VARIANCE = "no_variance"        # fired on EVERY evaluable sweep -- a constant, not a rate
PR_SUP_VINTAGE = "vintage_depth"          # enough sweeps, too few distinct source states behind them


def pr_rate_gate(*, in_catalog: bool, recorded: int, evaluable: int,
                 vintage_depth: Optional[int]) -> Optional[str]:
    """None when a firing RATE may honestly be stated, else the slug naming the fact that forbids it.

    ORDER IS MEANINGFUL. The coverage floor is tested BEFORE the variance predicate so that a short
    all-fired history keeps reading as "too short to state a rate" (its pre-existing, correct sentence)
    rather than being relabelled as a constant -- shortness is the more informative fact about it, and the
    live 11-of-11 pace shape lands there, so the flagship path renders byte-identically to today.

    `vintage_depth=None` means the depth could NOT be established (no such column on the mirror, a probe
    error, or the estimator was never run) and it SUPPRESSES. An unknown denominator is not a permissive
    one: that inversion is the 9-of-156 defect in a different costume."""
    if not in_catalog:
        return PR_SUP_NOT_COVERED
    if evaluable <= 0:
        return PR_SUP_NOTHING_EVALUABLE
    if recorded <= 0:
        return PR_SUP_NO_FIRING
    if evaluable < PR_MIN_EVALUABLE_SWEEPS:
        return PR_SUP_TOO_THIN
    if recorded >= evaluable:
        return PR_SUP_NO_VARIANCE
    if vintage_depth is None or int(vintage_depth) < PR_MIN_DISTINCT_VINTAGES:
        return PR_SUP_VINTAGE
    return None


def _vintage_depth(contract: str, driver: str, *, kind: str, asof: str, provenance: str,
                   evaluable: int, first_evaluable, last_evaluable, query_fn) -> Optional[int]:
    """The vintage-depth ESTIMATE for one pair, or None when it could not be established.

    None is returned for EVERY failure -- the query raised (a mirror without PR_VINTAGE_STATE_COLUMNS
    raises here rather than on the presence read, which is the whole reason this is a second statement),
    it returned nothing, or the count came back NULL. pr_rate_gate reads None as "suppress", so every one
    of those paths costs the rate and nothing else."""
    try:
        rows = query_fn(vintage_depth_sql(contract, driver, kind=kind, asof=asof, provenance=provenance))
    except Exception:  # noqa: BLE001 -- an unanswerable depth probe suppresses the rate, never the leg
        return None
    if not rows:
        return None
    raw = (rows[0] or {}).get("distinct_value_states")
    # BOTH null contracts: sqlite/Athena hand back None, while the pg mirror stringifies every cell and
    # renders NULL as "" (pgnumbers._stringify, matching Athena's GetQueryResults). Either is "unknown",
    # and _as_int("") would quietly read 0 -- a count, not an absence -- so it is caught here instead.
    if raw is None or not str(raw).strip():
        return None
    states = _as_int(raw)
    # Bound the proxy from both sides: it cannot exceed the number of sweeps it was computed over, and it
    # cannot exceed the number of vintages the elapsed span could physically have published.
    return max(0, min(states, _cadence_cap(first_evaluable, last_evaluable, evaluable), max(evaluable, 0)))


def pattern_records_legs(scope: dict, asof: str, query_fn) -> tuple[list[dict], dict]:
    """Run the presence/base-rate aggregation for a persistence-scoped question and return
    (legs, signal). `legs` are injected into the numbers-agent `calls` exactly like an ESR aggregate leg
    (each carries `query` + a `rows` list whose `value` is the citable count), so the unify/verify path
    mints a real [N] handle. `signal` is the deterministic trace record the eval + soak read (the
    pace_fired idiom):

        {injected, recorded_firings, sweeps_total, sweeps_evaluable, sweeps_unmeasurable, in_catalog,
         provenance, zero_materialized, rate_stated, rate_suppressed, vintage_depth, fenced,
         first_evaluable, last_evaluable}

    `rate_suppressed` is the slug from pr_rate_gate naming WHY no rate was stated (None when one was), and
    `rate_stated` is exactly its negation -- previously it read `recorded > 0 and evaluable >= floor`,
    which was TRUE for all 163 fired-on-every-sweep cascade pairs whose "rate" is a constant. `fenced`
    carries the read-side leakage refusal (pr_read_fenced) and is None on every readable pair.

    zero_materialized=True is the F8 honesty mechanism firing: an in-catalog OR not-covered pair with
    recorded_firings=0 STILL injects a citable 0-count leg, so the model cites "no firing recorded" as a
    FACT instead of minting a streak. A leg is emitted even for the 0 case -- injected is 0 ONLY if the
    lookup itself errored (fail-closed, never a silent fabrication).

    THE LEG CARRIES TWO ROWS, and the second one is load-bearing rather than decorative. Every figure the
    preface states must be groundable or the reader gets the false-caution banner on the engine's OWN
    correct sentence (the D1/D1b class closed in 1b0e2d19). orchestrator._verify_numbers_answer harvests
    exactly two slots per row -- `value`, then `sweeps_total` -- and it harvests them ONLY when `value`
    parses as a number (the non-numeric branch `continue`s past the sweeps_total collection), so a
    value-less carrier row would ground nothing. The evaluable count is a figure the prose states in
    every coverage-bearing branch and it is NOT equal to recorded_firings in general, so it rides as the
    `value` of a second, explicitly-labelled COVERAGE row. That grounds it through the verifier as it
    stands -- the verifier lives outside this lane and is not widened here. Two knock-ons, both checked:
    citations.from_number headlines max(rows, key=_row_order_key) and both rows carry an identical order
    key, so Python's max returns rows[0] and the citation still headlines the FIRING count; and the
    turn-scoped handle's series becomes [recorded_firings, sweeps_evaluable] rather than a lone count."""
    contract = scope.get("contract")
    driver = scope.get("driver_or_chain_id")
    kind = scope.get("kind", KIND_PACE)
    provenance = scope.get("provenance", PROV_DAILY_SWEEP)
    _dead = {"injected": 0, "recorded_firings": 0, "sweeps_total": 0, "sweeps_evaluable": 0,
             "sweeps_unmeasurable": 0, "in_catalog": False, "provenance": provenance,
             "zero_materialized": False, "rate_stated": False,
             "rate_suppressed": PR_SUP_NOT_COVERED, "vintage_depth": None, "fenced": None,
             "first_evaluable": None, "last_evaluable": None}
    if not (contract and driver and kind in V1_KINDS):
        return [], dict(_dead)
    # W4 LEAKAGE FENCE (see PR_FENCED_READS): refuse the leaked class BEFORE any query is built, so the
    # refusal cannot depend on what the ledger happens to hold. No leg, no citable row, and the reason is
    # named on the signal so the refusal is observable in the trace rather than looking like an empty read.
    fenced = pr_read_fenced(kind, provenance)
    if fenced:
        return [], dict(_dead, fenced=fenced)
    sql = (baserate_backfill_sql(contract, driver, kind=kind, asof=asof)
           if provenance == PROV_BACKFILL_GRID
           else presence_sql(contract, driver, kind=kind, asof=asof, provenance=provenance))
    try:
        rows = query_fn(sql)
    except Exception:  # noqa: BLE001 -- a mirror gap is a probe error, NEVER a fabricated firing
        return [], dict(_dead)
    row = _one_row(rows)
    recorded = _as_int(row.get("recorded_firings"))
    sweeps = _as_int(row.get("sweeps_total"))
    # A mirror that predates the additive column returns no `sweeps_evaluable` at all. Falling back to
    # `sweeps` there would silently resurrect the blindness-inflated denominator, so the fallback is the
    # FIRED count: an unknown-coverage read then reports rate-unstatable coverage, never a fake rate.
    evaluable = _as_int(row.get("sweeps_evaluable")) if row.get("sweeps_evaluable") is not None else recorded
    evaluable = min(evaluable, sweeps) if sweeps else evaluable
    in_catalog = sweeps > 0
    # VINTAGE DEPTH -- probed LAZILY, and the laziness is a design choice, not an optimisation. The
    # cheaper gates (catalog / evaluability / the coverage floor / discrimination) are decided from the
    # row already in hand; the depth query is issued ONLY when every one of them has passed and a rate is
    # therefore about to be stated. Three consequences: on today's ledger, where all 251 pairs are
    # constants, it is issued ZERO times and the serving seam keeps its one-query cost exactly; the
    # widened schema dependency (PR_VINTAGE_STATE_COLUMNS) is never on the critical path of the citable
    # count; and a mirror that cannot answer it costs the RATE, never the leg.
    depth = None
    if pr_rate_gate(in_catalog=in_catalog, recorded=recorded, evaluable=evaluable,
                    vintage_depth=PR_MIN_DISTINCT_VINTAGES) is None:
        depth = _vintage_depth(contract, driver, kind=kind, asof=asof, provenance=provenance,
                               evaluable=evaluable, first_evaluable=row.get("first_evaluable"),
                               last_evaluable=row.get("last_evaluable"), query_fn=query_fn)
    suppressed = pr_rate_gate(in_catalog=in_catalog, recorded=recorded, evaluable=evaluable,
                              vintage_depth=depth)
    # the citable row: `value` = the recorded firing count (a 0 is a real, citable observation).
    leg_row = {
        "value": recorded,
        "measure": "recorded_firings",
        "sweeps_total": sweeps,
        "sweeps_evaluable": evaluable,
        "sweeps_unmeasurable": max(sweeps - evaluable, 0),
        "first_recorded": row.get("first_recorded"),
        "last_recorded": row.get("last_recorded"),
        "first_evaluable": row.get("first_evaluable"),
        "last_evaluable": row.get("last_evaluable"),
        "declined_count": _as_int(row.get("declined_count")),
        "in_catalog": in_catalog,
        "provenance": provenance,
        "knowledge_date": asof,
        "unit": None,
    }
    # the COVERAGE row (see the docstring): the evaluable count as a citable `value`, so the honest
    # denominator the preface states is grounded by the verifier exactly like the firing count is.
    coverage_row = {
        "value": evaluable,
        "measure": "sweeps_evaluable",
        "sweeps_total": sweeps,
        "in_catalog": in_catalog,
        "provenance": provenance,
        "knowledge_date": asof,
        "unit": None,
    }
    leg = {"query": {"table": PR_TABLE, "record_kind": kind, "contract": contract,
                     "driver_or_chain_id": driver, "provenance": provenance, "asof": asof},
           "rows": [leg_row, coverage_row], "status": "ok", "pattern_provenance": provenance}
    signal = {"injected": 1, "recorded_firings": recorded, "sweeps_total": sweeps,
              "sweeps_evaluable": evaluable, "sweeps_unmeasurable": max(sweeps - evaluable, 0),
              "in_catalog": in_catalog, "provenance": provenance,
              "zero_materialized": recorded == 0,
              "rate_stated": suppressed is None,
              "rate_suppressed": suppressed, "vintage_depth": depth, "fenced": None,
              "first_evaluable": row.get("first_evaluable"),
              "last_evaluable": row.get("last_evaluable")}
    return [leg], signal


def _window(a, b) -> str:
    """', <first> to <last>' (or ', <first>' for a single point; '' for none). Dates only -- the
    verifier scrubs ISO dates before extracting stated figures, so a named window is always free."""
    if a and b and str(a) != str(b):
        return f", {a} to {b}"
    return f", {a}" if a else ""


def _covered_window(row: dict) -> str:
    """The span that was actually EVALUABLE -- the window any stated rate covers."""
    return _window(row.get("first_evaluable"), row.get("last_evaluable"))


def _fired_window(row: dict) -> str:
    """The span over which firings were RECORDED. Kept distinct from the covered window: attributing the
    evaluable span to a firing count would imply firings across dates that did not fire."""
    return _window(row.get("first_recorded"), row.get("last_recorded"))


def pattern_records_answer(scope: dict, indexed_leg: tuple[int, dict], signal: dict) -> Optional[str]:
    """The reader-facing OBSERVATION-register line built from the injected leg and its 1-based [N]
    position. Reports the COUNT + the DATES; NEVER a conclusion (no signal/setup/regime/trend/
    confirms/breakout/persistent -- pr_register_leaks pins it). Returns None when there is no leg (the
    caller then leaves the model's own honest narration to stand).

    Both prefaces -- the base-rate line AND the in-catalog honest-zero line -- quote the EVALUABLE
    denominator, never the raw attempted total (the 9-of-156 inversion, D1). Three properties hold on
    every branch:
      * a rate is stated over sweeps the engine could actually measure, with the covered window NAMED,
        so "9 of 156" can never again read as a rare event when it means "every week with data";
      * whenever coverage is incomplete, the SAME SENTENCE says how much of the grid was measurable --
        the reader never has to infer that the rest was dark;
      * below PR_MIN_EVALUABLE_SWEEPS no rate is stated AT ALL. The firing count and the window still
        are: F8's materialized zero and the citable count are the anti-fabrication mechanism, and
        suppressing those would hand the model back the empty-ledger state where it mints a streak.

    SIX SUPPRESSION FACTS, SIX SENTENCES (pr_rate_gate). The reasons a rate cannot be stated are not
    interchangeable and the wording never lets them blur:
      not_covered        we have never swept this pair          -> no figure at all
      nothing_evaluable  we swept it and never once saw data    -> the attempted count, and nothing measured
      no_firing          we measured it and it never fired      -> the honest, citable, MEASURED zero
      too_thin           measured, but over too few sweeps      -> the count and the window, no ratio
      no_variance        it fired on every sweep we could judge -> "on all N", named AS a constant
      vintage_depth      enough sweeps, too few source states   -> the count, and why the sweeps repeat
    The last two are the coverage-plan W2 additions and they are the ones a count floor cannot express:
    163 of the ledger's 251 pairs clear the count floor and every one of them is a constant.

    Every figure any branch states is a value on the injected leg's rows (`recorded_firings` and
    `sweeps_total` on the firing row, `sweeps_evaluable` as the coverage row's value), which is what
    orchestrator._verify_numbers_answer harvests -- so a correct engine sentence never wears the
    false-caution banner. Dates are scrubbed by the verifier before extraction, so they are free."""
    if not indexed_leg:
        return None
    idx, leg = indexed_leg
    row = (leg.get("rows") or [{}])[0]
    driver = scope.get("driver_or_chain_id", "this driver")
    contract = scope.get("contract", "this contract")
    provenance = signal.get("provenance", PROV_DAILY_SWEEP)
    unit = _PROV_LABEL.get(provenance, "recorded sweeps")
    recorded = _as_int(signal.get("recorded_firings"))
    sweeps = _as_int(signal.get("sweeps_total"))
    evaluable = _as_int(signal.get("sweeps_evaluable"))
    win = _covered_window(row)
    # the coverage clause, stated as "<evaluable> of <total>" -- both figures are citable row values, and
    # naming the measurable count directly is plainer than making the reader subtract.
    partial = evaluable < sweeps
    # ONE gate decides both the prose and the signal (pattern_records_legs stores the identical call's
    # result as `rate_suppressed`), so the sentence a reader sees and the slug the eval scores can never
    # drift apart. Read from the signal, `vintage_depth` absent -> None -> suppress, fail-closed.
    gate = pr_rate_gate(in_catalog=bool(signal.get("in_catalog")), recorded=recorded,
                        evaluable=evaluable, vintage_depth=signal.get("vintage_depth"))

    if recorded == 0:
        if not signal.get("in_catalog"):
            # not in the swept catalog / before the first partition -> "not covered", not a 0-firing claim.
            return (f"The engine has not recorded this pair in the swept ledger yet [N{idx}], so there is "
                    f"no recorded firing history to cite.")
        if evaluable == 0:
            # in the catalog, but EVERY sweep was blind: the old line called this "no firing on any of
            # its 156 sweeps", which reads as 156 measured non-events. It is zero measured anything.
            return (f"For {driver} on {contract}, the engine attempted {sweeps} {unit} and could not "
                    f"evaluate any of them [N{idx}] -- no firing history has been measured for this pair "
                    f"yet, so I cannot state a run length or a rate.")
        # in the swept catalog and genuinely evaluated -> a materialized, MEASURED 0 (F8).
        line = (f"For {driver} on {contract}, the engine has recorded no firing on any of the "
                f"{evaluable} {unit} it could evaluate{win} [N{idx}]")
        if partial:
            line += f" -- only {evaluable} of the {sweeps} attempted carried data"
        line += ". There is no recorded firing history for this pair yet, so I cannot state a run length"
        if evaluable < PR_MIN_EVALUABLE_SWEEPS:
            line += ", and that history is too short to read as a rate"
        return line + "."

    if gate in (PR_SUP_TOO_THIN, PR_SUP_NOTHING_EVALUABLE):
        # COVERAGE FLOOR: the count and the window are facts and stay; the RATIO does not get stated.
        # The window on the COUNT is the fired window -- pinning the evaluable span to a firing count
        # would imply firings on dates that did not fire. NOTHING_EVALUABLE is folded in here rather than
        # given its own sentence because it can only be reached on THIS path by a malformed mirror
        # (recorded > 0 with evaluable == 0, which the writer's invariants forbid): the honest-zero branch
        # above owns the real nothing-evaluable case, and this keeps that malformed shape rendering
        # exactly as it does today instead of claiming nothing was measured while stating firings.
        plural = "" if recorded == 1 else "s"
        line = (f"For {driver} on {contract}, the engine has recorded {recorded} firing{plural}"
                f"{_fired_window(row)} [N{idx}]. Only {evaluable} of the {sweeps} attempted {unit} "
                f"carried data it could evaluate")
        if win and win != _fired_window(row):
            line += f" ({win.lstrip(', ')})"
        return line + ", which is too short a recorded history to state a firing rate."

    if gate == PR_SUP_NO_VARIANCE:
        # THE DISCRIMINATION GATE (W2a). recorded == evaluable: it fired on every sweep that could be
        # judged. There is no rate here -- a ratio whose numerator and denominator are the same number is
        # a constant wearing a fraction's clothes, and 163 of the ledger's 251 pairs are exactly this. The
        # sentence therefore SAYS "all N", and then says in as many words that a rate is not available,
        # which also closes the older gap where the 100%-of-measurable case never named itself as such.
        line = (f"For {driver} on {contract}, the engine has recorded firing on all {evaluable} "
                f"{unit} it could evaluate{win} [N{idx}]")
        if partial:
            line += f"; only {evaluable} of the {sweeps} attempted carried data"
        # NOTE the deliberate absence of the "so that rate covers only the window named" tail used by the
        # rate branch below: there is no rate on this branch and the word must not appear as if there were.
        return line + (". Every sweep it could evaluate fired, so this is a constant over the window "
                       "named, not a firing rate.")

    if gate == PR_SUP_VINTAGE:
        # THE VINTAGE DENOMINATOR (W2b). Enough evaluable sweeps AND real variance among them, but those
        # sweeps do not stand behind enough DISTINCT SOURCE STATES to be independent observations -- the
        # flagship case is nine evaluable pace asofs resolving to three ESR vintages, one of which served
        # seven of them. The count and the window are facts and stay; the ratio would silently claim more
        # evidence than exists. No estimate is PRINTED: the depth is an approximation (see
        # PR_MIN_DISTINCT_VINTAGES) and only recorded observations get stated as figures.
        plural = "" if recorded == 1 else "s"
        line = (f"For {driver} on {contract}, the engine has recorded {recorded} firing{plural} across "
                f"the {evaluable} {unit} it could evaluate{win} [N{idx}]")
        if partial:
            line += f"; only {evaluable} of the {sweeps} attempted carried data"
        return line + (". Those sweeps resolve to too few distinct source vintages to read as independent "
                       "observations -- a series republished less often than the sweep grid runs is read "
                       "again and again at the same vintage -- so I am not stating a firing rate over them.")

    line = (f"For {driver} on {contract}, the engine has recorded firing on {recorded} of the "
            f"{evaluable} {unit} it could evaluate{win} [N{idx}]")
    if partial:
        line += (f"; only {evaluable} of the {sweeps} attempted carried data, so that rate covers only "
                 f"the window named")
    first = row.get("first_recorded")
    if first and str(first) != str(row.get("first_evaluable")):
        line += f", first recorded {first}"
    return line + "."


# ── persistence-question detection (the esr_destination_scope idiom: detect ONCE, up front) ────────
# Fail-CLOSED: a scope is returned ONLY when a persistence-intent phrase AND a resolvable driver keyword
# AND a contract are all present, so the existing decks (no export-pace persistence phrasing) never
# false-fire -- and the whole detector is called ONLY when the card flag is on (answer_numbers).
_PERSIST_INTENT = re.compile(
    r"first .*\b(?:second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th))\b"
    r"|how many .*(?:week|sweep|time)s?\b"
    r"|how (?:long|often)\b"
    r"|(?:fired|firing|fire)\b.*(?:streak|run|history|record|before|base[- ]?rate|so far)"
    r"|\bon record\b|\bbase[- ]?rate\b|\btrack record\b|\bhow many times\b|\brecorded (?:firing|history)",
    re.I)
_DRIVER_KEYWORDS = (
    (re.compile(r"export[- ]?pace|export (?:sales |commitments? )?pace|\bsales pace\b|pace of (?:export|sales)",
                re.I), "export_pace", KIND_PACE),
)
_SLUG_TOKENS = {
    "corn_cbot": "corn_cbot", "corn": "corn_cbot",
    "soybeans_cbot": "soybeans_cbot", "soybeans": "soybeans_cbot", "soybean": "soybeans_cbot",
    "wheat": "soft_red_winter_wheat_cbot",
}
_BACKFILL_INTENT = re.compile(
    r"base[- ]?rate|how often|over the (?:years|replay|history)|historical(?:ly)?|replay|track record", re.I)


def _pr_pair(q: str, contracts: Optional[list]) -> Optional[tuple]:
    """The (contract, driver_or_chain_id, kind) a question resolves to, or None.

    Extracted VERBATIM from pattern_records_scope so the J5 outcome detector resolves the pair through
    the SAME code rather than a second copy: the two detectors differ in INTENT (a ledger question vs a
    price-outcome question) and must not be allowed to drift in which pair they resolve to."""
    driver = kind = None
    for rx, d, k in _DRIVER_KEYWORDS:
        if rx.search(q):
            driver, kind = d, k
            break
    if not driver:
        return None
    ql = q.lower()
    contract = None
    for tok, slug in _SLUG_TOKENS.items():
        if re.search(rf"\b{re.escape(tok)}\b", ql):
            contract = slug
            break
    if not contract and contracts:
        contract = contracts[0]
    if not contract:
        return None
    return contract, driver, kind


def pattern_records_scope(question: str, *, contracts: Optional[list] = None) -> Optional[dict]:
    """Detect a persistence/history question about a (driver, contract) pair and return the scope dict
    {contract, driver_or_chain_id, kind, provenance}, or None. The backfill ENGINE base-rate path
    (provenance=backfill_grid) is chosen for a 'how often / base rate / over the replay history' ask; the
    daily_sweep presence path (which materializes a citable 0 for a pair with no firing) otherwise."""
    q = question or ""
    if not _PERSIST_INTENT.search(q):
        return None
    pair = _pr_pair(q, contracts)
    if not pair:
        return None
    contract, driver, kind = pair
    provenance = PROV_BACKFILL_GRID if _BACKFILL_INTENT.search(q) else PROV_DAILY_SWEEP
    return {"contract": contract, "driver_or_chain_id": driver, "kind": kind, "provenance": provenance}


# the OBSERVATION-register [N]-rendering directive appended to the reader-facing system string when the
# card flag is on (answer.py _system). Reports counts + dates; the F8 empty-ledger honesty is explicit.
RECORDED_HISTORY_ADDENDUM = (
    "\nRECORDED HISTORY. When a 'RECORDED HISTORY' [N] row is injected, it is a COUNT the deterministic "
    "engine recorded of how many past sweeps a (driver, contract) pair fired -- an OBSERVATION, not a "
    "verdict. Under a '## Recorded history' heading, state the count and the dates EXACTLY as the [N] "
    "row prints them (e.g. \"recorded firing on all 14 checks it could evaluate, 2026-04-18 to "
    "2026-07-18 [N]\"). Copy the injected line's OWN denominator and window -- never re-express the "
    "count over how many sweeps were attempted, and never drop the coverage clause: a count of sweeps "
    "the engine could not evaluate is NOT a count of times the pair failed to fire. If the injected "
    "line states no rate, do not compute one -- and if it says the count is a CONSTANT (it fired on "
    "every sweep it could evaluate) or that the sweeps resolve to too few distinct source vintages, "
    "carry that clause through: those sentences are not rates and must never be paraphrased into one. "
    "If the "
    "injected row reads recorded_firings=0 or says no firing is recorded yet, state PLAINLY that no "
    "firing history is recorded for this pair yet -- and do NOT infer a cross-day run from any "
    "within-turn pace figure (the within-window streak is a DIFFERENT quantity). State ONLY the number "
    "and the dates; add NO interpretation, conclusion, or direction word -- the reader draws any "
    "conclusion. A backfill base rate is the engine's replay over vintage data, phrased 'fired on N of "
    "M weekly replay asofs', and is NEVER phrased as recent daily firing history.\n")

# the numbers-agent ## Conventions bullet (observation register only), shown only when the card flag is
# on (agent.system_prompt). Teaches the SQL agent what the table records + the honest-decline vocabulary.
AGENT_CONVENTIONS_BULLET = (
    "- gold_pattern_records is the engine's OWN recorded verdict ledger: one row per (record_kind, "
    "contract, driver_or_chain_id, as_of_date) recording whether the deterministic cascade/pace/chain "
    "engine FIRED or DECLINED for that pair at that as-of, plus the recorded values. Use it to answer "
    "how many past sweeps a pair fired on, when it was first/last recorded, and the recorded decline "
    "reasons -- report the COUNT and the DATES only (recorded/fired/declined), and add NO conclusion "
    "or direction word (the reader interprets). A rate must be taken over the sweeps that could be "
    "EVALUATED: a decline whose decline_reason is a fetch/resolution failure (e.g. fetch_error, "
    "region-unresolved) or a waiver means the engine had no data to judge, NOT that the pair failed to "
    "fire, so it belongs in neither the numerator nor the denominator -- report the covered date window "
    "alongside any rate. `contract` is the focus contract slug; "
    "`driver_or_chain_id` is the driver node id (e.g. export_pace) or chain id. Filter "
    "provenance='daily_sweep' for the recorded daily firing history; provenance='backfill_grid' is a "
    "SEPARATE labelled engine base rate over vintaged replay asofs (phrase it 'weekly replay asofs', "
    "not recent daily firing). If no firing is recorded for the pair, say so plainly -- do NOT infer a "
    "run length.\n")


# ===================================================================================================
# J5 -- THE OUTCOME AXIS: gold_pattern_outcomes (OUTCOMES_JOIN plan items 76-85, D-OJ-11/12)
#
# WHAT THIS ADDS, AND WHAT IT DELIBERATELY DOES NOT.
#   It does NOT fix the firing rate. `pr_rate_gate` is ORDERED and NO_VARIANCE is tested before
#   VINTAGE; a forward-return column changes neither `recorded` nor `evaluable`, so all 163 constant
#   cascade pairs still return NO_VARIANCE, the 9+9 pace pairs still return TOO_THIN and the 79 empty
#   pairs still return NOTHING_EVALUABLE. Every one of the six suppressions above stays exactly as it
#   is, byte for byte (D-OJ-12, and an acceptance leg pins it). What J5 adds is a SECOND, SEPARATELY
#   GATED sentence about a DIFFERENT quantity: not "this pair fires X% of the time" but "across the N
#   times it fired, price did Y over the next 30 / 60 / 90 days".
#
# WHY THAT ONE HAS A GATE OF ITS OWN. A firing rate over a constant is degenerate; an outcome
# distribution over eight overlapping windows is something worse -- it LOOKS non-degenerate. Its four
# failure modes are different from the rate's and each gets its own suppression slug: too few closed
# horizons (the floor, INHERITED from stats.py rather than declared here), too few NON-OVERLAPPING
# windows behind those horizons (the outcome axis's own version of the vintage-depth defect: a daily
# sweep firing 90 days running measures ONE stretch of tape ninety times), too large a share of
# firings still pending (a distribution over what has closed describes the OLDEST firings -- the
# survivorship-in-the-denominator failure item 49 names), and nothing measurable at all.
#
# THE PIT CLAMP IS THE JOIN'S, NOT A SECOND ONE. Every horizon is clamped per (event, horizon) by
# `numbers.outcomes`: a horizon whose close postdates the reader's boundary is EXCLUDED from the
# closed statistics and renders as pending WITH ITS CLOSE DATE. The clamp is applied twice on purpose
# -- compiled into the aggregate SQL below (so no post-boundary move ever leaves the database) and
# re-applied per row in Python from the row's own stored tape edge (so a pinned-asof replay of a
# table built LATER cannot inherit a `closed` row that had not closed at its own asof).
#
# ONE CALCULATOR. Every quantile / spread / percentile computes through `numbers.stats` and inherits
# its refusal floor; below the floor the answer is a thin-coverage decline carrying COUNTS ONLY, under
# the SAME `too_thin` slug this module already uses. There is no second floor constant anywhere here.
# ===================================================================================================
PO_TABLE = "gold_pattern_outcomes"

# The horizon family J5 measures. A STRICT SUBSET of the AM-1 anchored family {5, 30, 60, 90}: the
# 5-day leg exists on `gold_futures_outcomes` for the single-event lane, but a week is shorter than the
# weekly sweep grid itself, so a pattern-outcome distribution over 5-day horizons would be dominated by
# the grid's own cadence rather than by the pairs' behaviour. A YEAR horizon does not exist under this
# basis at all and is declined honestly rather than rounded to 90 (AM-1; po_horizon_decline).
PO_HORIZONS: tuple[int, ...] = (30, 60, 90)

# The ledger key the outcome row must carry back, verbatim, so an outcome can always be traced to the
# verdict it was measured from. `provenance` is part of the KEY, not a label: daily_sweep and
# backfill_grid are different populations and mixing them is the F5 defect one layer down.
PO_KEY_COLUMNS: tuple[str, ...] = (
    "record_kind", "contract", "driver_or_chain_id", "provenance", "as_of_date")
PO_KEY_COLUMN_TYPES: dict[str, str] = {
    "record_kind": "string", "contract": "string", "driver_or_chain_id": "string",
    "provenance": "string", "as_of_date": "string",
}
# THE SECOND PIT AXIS, carried forward from the ledger and guarded exactly as `presence_sql` guards it.
# Not in the plan's column list, and it is not optional: a backfill_grid verdict for as_of 2023 was
# WRITTEN in 2026, so an outcome row guarded only on `as_of_date` would be readable at a pinned 2023
# asof at which the verdict did not exist. The ingest axis is the ledger's, so it travels with the row.
PO_EXTRA_COLUMNS: tuple[str, ...] = ("ledger_written_at",)
PO_EXTRA_COLUMN_TYPES: dict[str, str] = {"ledger_written_at": "timestamp"}

PO_PARTITIONS: tuple[str, ...] = ("leviathan_slug", "as_of_year")
PO_PARTITION_TYPES: dict[str, str] = {"leviathan_slug": "string", "as_of_year": "int"}

# The distribution actually published: a CENTRAL statistic and a DISPERSION statistic beside it (item
# 78). A median with no spread beside it is the shape that reads as a point forecast.
PO_PROBS: tuple[float, ...] = (0.1, 0.5, 0.9)

# The pending-share ceiling. Above it the closed set is a minority AND is systematically the OLDEST
# firings, so a distribution over it is a statement about 2019 dressed as a statement about the pair.
# The count and the pending count are still published -- they always are (item 49).
PO_MAX_PENDING_SHARE = 0.5

PO_ROUND_PCT = 1          # the published precision of a move: one decimal, on the ROW and in the
#                           prose, so the figure a reader sees IS the figure the verifier checks.


def _oc():
    """The join engine, imported LAZILY and only here.

    `numbers.outcomes` imports `PR_SUP_TOO_THIN` from this module at import time (one floor family, one
    vocabulary), so a module-level import in this direction is a cycle. Deferring it to call time is
    the whole fix: by the time any of these functions runs, both modules are fully initialised. The
    alternative -- re-declaring the statuses, the decline vocabulary and the clamp here -- is exactly
    the second copy of a rule that this codebase's F-L discipline exists to prevent."""
    from leviathan.graphrag.numbers import outcomes as OC
    return OC


def po_min_closed() -> int:
    """The coverage floor for an outcome distribution: `stats.MIN_QUANTILE_N`, INHERITED, never a
    second constant. A spread over a handful of firings fakes precisely the precision a rank over the
    same handful fakes, and the outcome axis has no claim to a laxer floor than the calculator that
    computes it (AM-3 / the standing stats-tools directive)."""
    return int(st.MIN_QUANTILE_N)


def po_min_independent_windows() -> int:
    """The floor on NON-OVERLAPPING windows. Deliberately the SAME constant as the count floor, for the
    same reason PR_MIN_DISTINCT_VINTAGES equals PR_MIN_EVALUABLE_SWEEPS: the floor's justification was
    always an argument about INDEPENDENT OBSERVATIONS, and rows were only ever a proxy for those."""
    return int(st.MIN_QUANTILE_N)


def po_columns() -> tuple[str, ...]:
    """The physical columns of `gold_pattern_outcomes`: the ledger key + the ingest axis + the outcome
    contract VERBATIM. The outcome half is not re-declared here -- it is `outcomes.OUTCOME_COLUMNS`, so
    a column added to the join arrives on this table without a second edit and cannot drift from it."""
    return PO_KEY_COLUMNS + PO_EXTRA_COLUMNS + tuple(_oc().OUTCOME_COLUMNS)


def po_column_types() -> dict[str, str]:
    """The single schema authority the F010 contract + the generated DDL are derived FROM."""
    return {**PO_KEY_COLUMN_TYPES, **PO_EXTRA_COLUMN_TYPES, **dict(_oc().OUTCOME_COLUMN_TYPES)}


def po_horizon_decline(horizon_days: int) -> dict:
    """The honest refusal for a horizon this axis does not serve -- AM-1's year exclusion first among
    them. Never rounded to the nearest supported horizon: a year read is a NEW basis decision
    (calendar-spread-adjusted or index-style), not a quiet extension of this one."""
    OC = _oc()
    base = OC.horizon_decline(horizon_days)
    return {**base, "supported_horizons": list(PO_HORIZONS), "table": PO_TABLE}


def po_resolve_slug(contract: Optional[str]) -> Optional[str]:
    """The ledger's `contract` -> a PRICE-TAPE slug, or None. RESOLVE OR SKIP; never guess (item 81).

    The ledger holds BOTH shapes -- the measured pace pairs include `(corn, export_pace)` AND
    `(corn_cbot, export_pace)`, where `corn` is a graph node and `corn_cbot` is a tape slug. Only the
    slug shape maps to a tape, and `futures_eod_contracts.coverage_start_for` RAISES on the rest. The
    tempting repair is an alias table (`corn` -> `corn_cbot`), and it is exactly the mis-attribution
    class D-OJ-1's labelling obligation is about: `corn` could as honestly resolve to MATIF maize or to
    the CEPEA Campinas cash reference, and a silently chosen one would put a US move under a Brazilian
    question. So an unresolvable contract is SKIPPED and COUNTED -- the builder publishes the count and
    reconciles `resolved + skipped == ledger pairs`, or the table quietly covers half the ledger while
    looking complete."""
    from leviathan.silver import futures_eod_contracts as FC
    key = str(contract or "").strip()
    return key if key in FC.CONTRACT_MAP else None


def po_anchor_key(record_kind: str, contract: str, driver_or_chain_id: str, provenance: str,
                  as_of_date) -> str:
    """The stable `event_key` an outcome row carries: the ledger's natural key, pipe-joined. Stable
    across rebuilds (the fingerprint depends on it) and reversible by split, so the outcome table can
    always be joined back to the verdict it measures."""
    return "|".join(str(x) for x in (record_kind, contract, driver_or_chain_id, provenance,
                                     str(as_of_date)[:10]))


def po_ledger_anchors(ledger_rows: Sequence[dict], *, kinds: Optional[Sequence[str]] = None,
                      provenance: Optional[str] = None) -> dict:
    """FIRED ledger rows -> join anchors, plus the skip census that has to reconcile (acceptance (i)).

    Returns `{anchors, meta, skipped, skipped_by_reason, pairs, resolved_pairs}`:
      * `anchors`   -- `[{leviathan_slug, event_key, event_date}]`, the shape `outcomes.build_outcomes`
                       consumes. NOTHING else is passed to the engine: the join must not be able to see
                       the verdict it is measuring.
      * `meta`      -- `event_key -> the ledger key columns + ledger_written_at`, re-attached after the
                       build so the outcome row carries its provenance back.
      * `skipped_*` -- counted by reason, never dropped silently.

    Only `verdict='fired'` rows produce an anchor: a decline records that the engine could not judge,
    and a forward move measured from a non-event would put price history under a question about
    firings. The leakage fence is applied HERE as well as at the read seam -- cascade x backfill_grid
    verdicts were replayed against a synthesized as-of axis, and a price move joined to a leaked
    verdict is a leaked row however clean the price side is."""
    want_kinds = frozenset(kinds) if kinds else V1_KINDS
    anchors: list[dict] = []
    meta: dict[str, dict] = {}
    skipped: dict[str, int] = {}
    pairs: set[tuple] = set()
    resolved_pairs: set[tuple] = set()

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for row in ledger_rows or []:
        kind = str(row.get("record_kind") or "")
        contract = str(row.get("contract") or "")
        driver = str(row.get("driver_or_chain_id") or "")
        prov = str(row.get("provenance") or "")
        asof_d = str(row.get("as_of_date") or "")[:10]
        pair = (kind, contract, driver, prov)
        pairs.add(pair)
        if kind not in want_kinds:
            _skip("kind_not_requested")
            continue
        if provenance is not None and prov != provenance:
            _skip("provenance_not_requested")
            continue
        if pr_read_fenced(kind, prov):
            _skip("fenced_leaky_asof")
            continue
        if str(row.get("verdict") or "") != VERDICT_FIRED:
            _skip("not_a_firing")
            continue
        if not asof_d:
            _skip("no_as_of_date")
            continue
        slug = po_resolve_slug(contract)
        if not slug:
            _skip("slug_unresolved")
            continue
        key = po_anchor_key(kind, contract, driver, prov, asof_d)
        if key in meta:
            _skip("duplicate_key")            # the ledger's natural key forbids it; count, never merge
            continue
        anchors.append({"leviathan_slug": slug, "event_key": key, "event_date": asof_d})
        meta[key] = {"record_kind": kind, "contract": contract, "driver_or_chain_id": driver,
                     "provenance": prov, "as_of_date": asof_d, "leviathan_slug": slug,
                     "ledger_written_at": row.get("written_at")}
        resolved_pairs.add(pair)
    return {"anchors": anchors, "meta": meta, "skipped": sum(skipped.values()),
            "skipped_by_reason": dict(sorted(skipped.items())),
            "pairs": len(pairs), "resolved_pairs": len(resolved_pairs)}


def independent_windows(anchor_dates: Sequence, horizon_days: int) -> int:
    """How many NON-OVERLAPPING `horizon_days` windows the anchors actually stand on (greedy from the
    earliest). This is the outcome axis's independence measure and it is the one a row count cannot
    see: the daily sweep writes one row per pair per day, so a condition that holds for three months
    produces ~90 firings whose 90-day windows are ~90 re-measurements of ONE stretch of tape. Counting
    those as 90 observations overstates the evidence by the overlap factor -- the identical failure the
    vintage denominator catches on the rate side, in the time domain instead of the source domain.

    Unparseable dates are DROPPED rather than defaulted (a date that cannot be read cannot be shown to
    be independent of anything), which is the fail-closed direction."""
    days: list[_dt.date] = []
    for value in anchor_dates or []:
        try:
            days.append(_dt.date.fromisoformat(str(value)[:10]))
        except (TypeError, ValueError):
            continue
    if not days:
        return 0
    days.sort()
    count, cursor = 0, None
    for d in days:
        if cursor is None or (d - cursor).days >= int(horizon_days):
            count += 1
            cursor = d
    return count


# -- the SEVENTH suppression-or-statement render, and its own vocabulary ----------------------------
# Same doctrine as the six above (pattern_records.py: collapsing any two suppression slugs would let a
# reader mistake "never looked" for "always true"), applied to a different question. `too_thin` is
# DELIBERATELY SHARED with the rate side rather than duplicated: it names the identical fact (measured
# history shorter than the floor) about the identical floor constant, and a second slug for it would
# split one fact across two vocabularies.
PO_SUP_UNSUPPORTED_HORIZON = "outcome_horizon_unsupported"   # AM-1: the year ask lands here
PO_SUP_SLUG_UNRESOLVED = "outcome_slug_unresolved"       # ledger key is a node, not a tape slug
PO_SUP_NOT_JOINED = "outcome_not_joined"                 # the pair has no outcome row at all
PO_SUP_UNMEASURABLE = "outcome_unmeasurable"             # joined, but every firing declined
PO_SUP_ALL_PENDING = "outcome_all_pending"               # joined, and no horizon has closed yet
PO_SUP_TOO_THIN = PR_SUP_TOO_THIN                        # below the INHERITED stats floor
PO_SUP_OVERLAP = "outcome_windows_overlap"               # too few non-overlapping windows
PO_SUP_PENDING_HEAVY = "outcome_pending_heavy"           # closed set is a minority, and it is the old half
PO_SUP_OUTLOOK_HELD = "outcome_outlook_held"             # D-OJ-17 option (a): not reached on an outlook turn
PO_SUPPRESSIONS: tuple[str, ...] = (
    PO_SUP_UNSUPPORTED_HORIZON, PO_SUP_SLUG_UNRESOLVED, PO_SUP_NOT_JOINED, PO_SUP_UNMEASURABLE,
    PO_SUP_ALL_PENDING, PO_SUP_TOO_THIN, PO_SUP_OVERLAP, PO_SUP_PENDING_HEAVY, PO_SUP_OUTLOOK_HELD,
)


def po_outcome_gate(*, joined: int, n_closed: int, n_pending: int, n_declined: int,
                    n_independent: Optional[int]) -> Optional[str]:
    """None when an outcome DISTRIBUTION may honestly be stated, else the slug naming what forbids it.

    ORDER IS MEANINGFUL, and it is the same principle `pr_rate_gate` uses: the most informative fact
    about the pair wins. Nothing joined outranks nothing measurable outranks nothing closed outranks
    too few closed; only then does independence, and only then the pending share -- because "you have
    eight outcomes" is a more useful thing to be told than "your eight outcomes overlap", and both are
    more useful than a share.

    `n_independent=None` means the window independence was NOT established (the values probe was never
    run, or it failed) and it SUPPRESSES. An unknown denominator is not a permissive one -- that
    inversion is the 9-of-156 defect in yet another costume."""
    if joined <= 0:
        return PO_SUP_NOT_JOINED
    if n_closed <= 0 and n_pending <= 0:
        return PO_SUP_UNMEASURABLE
    if n_closed <= 0:
        return PO_SUP_ALL_PENDING
    if n_closed < po_min_closed():
        return PO_SUP_TOO_THIN
    if n_independent is None or int(n_independent) < po_min_independent_windows():
        return PO_SUP_OVERLAP
    if (n_closed + n_pending) > 0 and n_pending / float(n_closed + n_pending) > PO_MAX_PENDING_SHARE:
        return PO_SUP_PENDING_HEAVY
    return None


# -- the reads: ANSI, scalar-presence shaped, and PIT-clamped on THREE axes -------------------------
def po_readable_asof(asof: str) -> str:
    """The as-of the HORIZON-CLOSE axis is compared against: `asof - (survive_days + tape_lag)`.

    This is `query._pub_lagged_asof` done by hand, and the hand version is the point: that helper
    shifts the RHS LITERAL of a compiled guard, and these queries are hand-built ANSI (the pg-mirror
    lane), so the shift has to happen here or the clamp is simply absent. The lag is not this module's
    number -- it is `outcomes.OUTCOME_PUBLICATION_LAG_DAYS`, which is `OUTCOME_SURVIVE_DAYS + 1` and is
    lint-bound to the card. `survive_days` is inside it because the contract was SELECTED by asking
    whether it still printed five calendar days past the close: for any asof in [t1+1, t1+5) that
    selection
    used tape the reader does not have, and selection determines px0 and px1 and therefore the whole
    move (plan item 46)."""
    lag = int(_oc().OUTCOME_PUBLICATION_LAG_DAYS)
    try:
        return (_dt.date.fromisoformat(str(asof)[:10]) - _dt.timedelta(days=lag)).isoformat()
    except (TypeError, ValueError):
        # An unparseable asof must never widen the window. '' compares below every ISO date on every
        # backend, so the guard admits NOTHING -- fail closed, and visibly (the census returns zeros).
        return ""


def _po_where(contract: str, driver_or_chain_id: str, *, kind: str, asof: str, horizon_days: int,
              provenance: str) -> list[str]:
    """The key + the three PIT axes every read of this table carries.

      as_of_date        <= asof            the FIRING must be knowable (the ledger's data axis)
      ledger_written_at <= asof            the VERDICT must have been written (the ledger's ingest
                                           axis -- a backfill_grid row for 2023 was written in 2026)
      readable_date     <= asof - lag      the horizon CLOSE (applied per aggregate below, not here,
                                           because a row past it must still COUNT as pending)

    `built_at` is NOT among them: under a full rebuild every row carries the same stamp, so
    `built_at <= asof` is all-pass or all-fail and cannot bind (D-OJ-15). It is provenance."""
    return [
        f"record_kind = {_q(kind)}",
        f"contract = {_q(contract)}",
        f"driver_or_chain_id = {_q(driver_or_chain_id)}",
        f"provenance = {_q(provenance)}",
        f"horizon_days = {int(horizon_days)}",
        f"{_date_at('as_of_date')} <= {_q(asof)}",
        f"{_date_at('ledger_written_at')} <= {_q(asof)}",
    ]


def po_census_sql(contract: str, driver_or_chain_id: str, *, kind: str, asof: str,
                  horizon_days: int, provenance: str = PROV_DAILY_SWEEP) -> str:
    """The SCALAR outcome census for one (pair, horizon). Returns EXACTLY ONE row, always -- the same
    F8 presence property the rate side rests on: over zero matched rows COUNT is 0 and MIN is NULL, so
    a pair with no joined outcome yields a citable `joined=0` instead of an empty result the model
    would fill in from its own head.

    THE CLAMP IS COMPILED INTO THE AGGREGATE, and that is what keeps the denominator honest. A row the
    builder wrote `closed` is counted CLOSED only if its horizon close is at or before the reader's
    lagged boundary; otherwise it counts PENDING. Filtering those rows out instead -- the obvious
    reading of "guard the data axis" -- would delete them from the denominator as well, which is
    precisely the survivorship bias toward OLD firings that publishing `n_pending` exists to prevent
    (item 49). Nothing about the move leaks either way: the VALUES read below applies the same boundary
    as a hard filter, so a post-boundary move never leaves the database at all."""
    where = _po_where(contract, driver_or_chain_id, kind=kind, asof=asof, horizon_days=horizon_days,
                      provenance=provenance)
    readable = f"{_date_at('readable_date')} <= {_q(po_readable_asof(asof))}"
    closed = f"(status = 'closed' AND {readable})"
    # PENDING = written pending, OR written closed but not yet readable at THIS asof. An unrecognised
    # status falls in NEITHER arm and lands in declined below -- the fail-closed direction.
    pending = f"(status = 'pending' OR (status = 'closed' AND NOT ({readable})))"
    return (
        "SELECT "
        "COUNT(*) AS joined, "
        f"COUNT(CASE WHEN {closed} THEN 1 END) AS n_closed, "
        f"COUNT(CASE WHEN {pending} THEN 1 END) AS n_pending, "
        "COUNT(CASE WHEN status NOT IN ('closed', 'pending') THEN 1 END) AS n_declined, "
        "MIN(as_of_date) AS first_firing, "
        "MAX(as_of_date) AS last_firing, "
        f"MIN(CASE WHEN {closed} THEN as_of_date END) AS first_closed_firing, "
        f"MAX(CASE WHEN {closed} THEN as_of_date END) AS last_closed_firing, "
        f"MIN(CASE WHEN {pending} THEN horizon_close_date END) AS first_pending_close, "
        f"MAX(CASE WHEN {pending} THEN horizon_close_date END) AS last_pending_close "
        f"FROM {PO_TABLE} WHERE " + " AND ".join(where)
    )


def po_values_sql(contract: str, driver_or_chain_id: str, *, kind: str, asof: str,
                  horizon_days: int, provenance: str = PROV_DAILY_SWEEP) -> str:
    """The CLOSED outcome rows of one (pair, horizon) -- the input the distribution is computed FROM.

    Scoped to one pair, one horizon and the readable side of the boundary, so the result is one row per
    firing (a few hundred at the very most) and the row-cap class the plan flags for `agg='series'`
    reads cannot arise. The evaluable predicate is `outcomes.evaluable_pred`, reused rather than
    re-derived: it is stated POSITIVELY, so a status this build has never heard of falls outside it and
    SHRINKS coverage toward the floor instead of swelling a denominator.

    The selected columns are exactly what the Python-side re-clamp needs (`event_date`, `horizon_days`,
    `status`, `tape_edge_date`) plus what the render and the audit need. `move_pct` is the measured
    quantity; `contract_month_used` rides so the basis of every measured move is inspectable."""
    where = _po_where(contract, driver_or_chain_id, kind=kind, asof=asof, horizon_days=horizon_days,
                      provenance=provenance)
    where.append(_oc().evaluable_pred("status"))
    where.append(f"{_date_at('readable_date')} <= {_q(po_readable_asof(asof))}")
    return (
        "SELECT as_of_date, event_date, horizon_days, status, move_pct, move_abs, px0, px1, "
        "endpoint_date, horizon_close_date, readable_date, realized_sessions, contract_month_used, "
        "basis, leviathan_slug, tape_edge_date, unit, currency "
        f"FROM {PO_TABLE} WHERE " + " AND ".join(where) + " ORDER BY as_of_date"
    )


# -- serving dispatch: an outcome question -> ONE injected [N] leg + ONE deterministic line --------
def _po_round(value) -> Optional[float]:
    """The PUBLISHED precision of a move. Rounded ONCE, here, and the rounded number is what goes on
    the row AND into the prose -- so the figure the reader sees is the figure the verifier checks,
    with no 1%-tolerance gap between them. `-0.0` is normalised away (a reader shown '-0.0%' learns
    nothing true that '0.0%' does not)."""
    try:
        out = round(float(value), PO_ROUND_PCT)
    except (TypeError, ValueError):
        return None
    return 0.0 if out == 0 else out


def pattern_outcome_legs(scope: dict, asof: str, query_fn, *,
                         outlook: bool = False) -> tuple[list[dict], dict]:
    """Run the outcome census / distribution for one (pair, horizon) and return (legs, signal).

    THE OUTLOOK GATE IS THE FIRST THING IT ASKS, and it is the `_cot_outcomes_on`/`not outlook` idiom
    J6 uses one module over (cascade.py: `if cot_outcomes and not outlook`). The statement branch below
    ships a median, a p10/p90 spread and "N of them closed higher" -- a CITED, ARROW-FREE CONDITIONAL
    PERFORMANCE sentence. Under OUTLOOK, `register.py` places `_VALUATION_PHRASES`, `_FLOW_PHRASES`,
    `_PERSISTENCE` and both Lane-B arms inside `if not outlook:`, so exactly that sentence returns False
    from `_is_banned_sentence` and ships as a setup: item 90b's argument, verbatim, one table over. J6's
    three remedies do not reach here -- `gold_pattern_outcomes` is (correctly) not in
    `POSITIONING_TABLES`, so the `quantify` node-drop that fences J6 structurally never touches this
    leg. So the gate is HERE, at the leg, ahead of every read: on an outlook turn the outcome ref is not
    reached at all (D-OJ-17 option (a)), and the wiring commit cannot forget to add it because the
    parameter is already in the signature.

    The leg is the SAME shape the pattern-records presence leg is (`query` + `rows` whose `value` is a
    citable magnitude), so the existing append site mints a real [N] handle over it with no new
    machinery. It carries ONE ROW PER FIGURE THE LINE PRINTS -- the median, the two decile bounds, the
    closed count, the pending count, the up-count and the independent-window count -- because
    `orchestrator._verify_numbers_answer` grounds a stated number only against row `value`s (plus the
    `sweeps_total` slot), and an engine sentence whose own figures are ungrounded wears the
    false-caution banner. That is the D1/D1b class this module already paid for once.

    THE DISTRIBUTION IS NOT COMPUTED HERE. It is `outcomes.outcome_distribution` over
    `stats.quantiles` / `stats.extrema`, so the refusal floor is the calculator's and the answer below
    the floor is a thin-coverage decline carrying COUNTS ONLY. No quantile is ever put on a row that
    the gate then suppresses -- a suppressed distribution that still shipped its numbers would be the
    suppression doing nothing.

    THE VALUES PROBE IS LAZY, exactly as the vintage-depth probe is: the cheap scalar census decides
    every gate it can decide, and the row-returning query is issued ONLY when a distribution is
    actually about to be stated. On today's ledger -- where the reachable pairs are pace pairs with
    nine weekly firings -- it is issued zero times."""
    OC = _oc()
    contract = scope.get("contract")
    driver = scope.get("driver_or_chain_id")
    kind = scope.get("kind", KIND_PACE)
    provenance = scope.get("provenance", PROV_DAILY_SWEEP)
    horizon = int(scope.get("horizon_days") or PO_HORIZONS[0])
    _dead = {"injected": 0, "table": PO_TABLE, "horizon_days": horizon,
             "horizon_label": OC.horizon_label(horizon), "leviathan_slug": None, "basis": None,
             "provenance": provenance, "joined": 0, "n_closed": 0, "n_pending": 0, "n_declined": 0,
             "n_unusable": 0, "n_independent": None, "pending_share": None,
             "outcome_stated": False, "outcome_suppressed": PO_SUP_NOT_JOINED, "fenced": None,
             "first_firing": None, "last_firing": None, "first_closed_firing": None,
             "last_closed_firing": None, "first_pending_close": None, "last_pending_close": None,
             "median": None, "p10": None, "p90": None, "n_up": None, "n_down": None}
    if outlook:
        # No leg, no read, no sentence: `pattern_outcome_answer` returns None for a gate it has no
        # no-leg render for, so the model's own narration stands and this axis contributes nothing.
        return [], dict(_dead, outcome_suppressed=PO_SUP_OUTLOOK_HELD)
    if not (contract and driver and kind in V1_KINDS):
        return [], dict(_dead)
    # THE LEAKAGE FENCE IS TESTED FIRST, ahead of the horizon and the slug, because it is a fact about
    # the DATA rather than about the question: a fenced pair has no citable outcome at any horizon, so
    # answering "that horizon is unsupported" would name the smaller of two reasons and imply the
    # bigger one away. The W4 fence carries to the outcome axis unchanged -- a price move joined to a
    # verdict replayed against a synthesized as-of axis is a leaked row however clean the price side
    # is -- and refusing BEFORE any query is built keeps the refusal independent of what the table
    # happens to hold. The builder applies the identical fence, so such a row should not exist; this
    # is the second lock on the same door, at the seam where a citable [N] reaches a reader.
    fenced = pr_read_fenced(kind, provenance)
    if fenced:
        return [], dict(_dead, fenced=fenced)
    if horizon not in PO_HORIZONS:
        # AM-1, rendered rather than rounded: a year read forces the spliced basis this join rejects.
        return [], dict(_dead, outcome_suppressed=PO_SUP_UNSUPPORTED_HORIZON,
                        horizon_detail=po_horizon_decline(horizon)["detail"])
    slug = po_resolve_slug(contract)
    if not slug:
        # item 81: the ledger holds BOTH node names and tape slugs, and only the slug shape maps to a
        # series. Never guessed -- a guessed slug puts one exchange's move under another's question.
        return [], dict(_dead, outcome_suppressed=PO_SUP_SLUG_UNRESOLVED)
    try:
        rows = query_fn(po_census_sql(contract, driver, kind=kind, asof=asof, horizon_days=horizon,
                                      provenance=provenance))
    except Exception:  # noqa: BLE001 -- a mirror gap is a probe error, NEVER a fabricated outcome
        return [], dict(_dead)
    row = (rows[0] if rows else {}) or {}
    joined = _as_int(row.get("joined"))
    n_closed = _as_int(row.get("n_closed"))
    n_pending = _as_int(row.get("n_pending"))
    n_declined = _as_int(row.get("n_declined"))

    dist: Optional[dict] = None
    n_independent: Optional[int] = None
    n_unusable = 0
    # THE PRE-GATE decides everything the cheap counts can decide, by handing the gate a PASSING
    # independence count purely to ask "is anything ELSE already suppressing?". Its verdict is FINAL
    # when it is not None -- and that is not an optimisation, it is what keeps the stated reason true:
    # a pair suppressed on its pending share never had its windows measured, so re-running the gate
    # afterwards with an unmeasured (=None) independence would report OVERLAP, i.e. blame a fact
    # nobody looked at for a suppression something else caused.
    pre = po_outcome_gate(joined=joined, n_closed=n_closed, n_pending=n_pending,
                          n_declined=n_declined, n_independent=po_min_independent_windows())
    suppressed = pre
    if pre is None:
        try:
            values = query_fn(po_values_sql(contract, driver, kind=kind, asof=asof,
                                            horizon_days=horizon, provenance=provenance))
        except Exception:  # noqa: BLE001 -- an unanswerable values probe costs the DISTRIBUTION only
            values = []
        # DEFENCE IN DEPTH, and it is not redundant: this table is a FULL REBUILD at the current tape
        # edge, so a pinned-asof replay reads rows materialized `closed` by a LATER build. The SQL
        # boundary above already excludes them; re-clamping each row against the reader's asof from the
        # row's OWN stored tape edge makes "pending" a function of the reader rather than of the build,
        # and strips px1/move on the way. A row that flips here is counted pending, never dropped.
        clamped = [OC.clamp_row(v, asof, v.get("tape_edge_date")) for v in (values or [])]
        dist = OC.outcome_distribution(clamped, probs=PO_PROBS)
        n_independent = independent_windows(
            [c.get("as_of_date") for c in clamped if c.get("status") == OC.STATUS_CLOSED], horizon)
        flipped = _as_int(dist.get("n_pending"))
        n_unusable = max(len(clamped) - _as_int(dist.get("n_closed")) - flipped
                         - _as_int(dist.get("n_declined")), 0)
        n_closed = _as_int(dist.get("n_closed"))
        n_pending += flipped
        n_declined += n_unusable
        # The real gate, over the MEASURED independence and over counts the re-clamp may have moved.
        suppressed = po_outcome_gate(joined=joined, n_closed=n_closed, n_pending=n_pending,
                                     n_declined=n_declined, n_independent=n_independent)

    total = n_closed + n_pending
    share = (n_pending / float(total)) if total else None
    med = p10 = p90 = n_up = n_down = None
    if suppressed is None and dist and not dist.get("declined"):
        qs = dist.get("quantiles") or {}
        med, p10, p90 = (_po_round(qs.get("0.5")), _po_round(qs.get("0.1")), _po_round(qs.get("0.9")))
        n_up, n_down = _as_int(dist.get("n_up")), _as_int(dist.get("n_down"))
        if med is None or p10 is None or p90 is None:
            suppressed = PO_SUP_TOO_THIN            # a distribution that will not render is not one

    head = {"horizon_days": horizon, "knowledge_date": asof, "in_catalog": joined > 0,
            "provenance": provenance, "basis": None, "unit": None}
    if suppressed is None:
        head["basis"] = OC.BASIS_CASH if slug in _po_cash_slugs() else OC.BASIS_SURVIVOR
        leg_rows = [
            {**head, "value": med, "measure": "move_pct_median", "unit": "%",
             "first_closed_firing": row.get("first_closed_firing"),
             "last_closed_firing": row.get("last_closed_firing")},
            {**head, "value": n_closed, "measure": "closed_firings"},
            {**head, "value": n_pending, "measure": "pending_firings"},
            {**head, "value": p10, "measure": "move_pct_p10", "unit": "%"},
            {**head, "value": p90, "measure": "move_pct_p90", "unit": "%"},
            {**head, "value": n_up, "measure": "closed_higher"},
            {**head, "value": n_independent, "measure": "independent_windows"},
        ]
    else:
        # THE SUPPRESSED LEG STILL SHIPS, and it ships COUNTS ONLY. The count and the window are
        # observations; the distribution is what the gate refused. Dropping the leg entirely would
        # hand the model back the empty-ledger state in which it mints the number itself -- which is
        # the failure the whole pattern-records card exists to close.
        leg_rows = [
            {**head, "value": n_closed, "measure": "closed_firings"},
            {**head, "value": n_pending, "measure": "pending_firings"},
            {**head, "value": joined, "measure": "joined_firings"},
            {**head, "value": n_declined, "measure": "unmeasurable_firings"},
        ]
        if n_independent is not None:
            # The overlap sentence STATES this count, so it has to be citable -- an engine sentence
            # whose own figure is ungrounded wears the false-caution banner, which is the D1/D1b class
            # this module has already paid for once. (Caught by the grounding test, not by review.)
            leg_rows.append({**head, "value": n_independent, "measure": "independent_windows"})
    leg = {"query": {"table": PO_TABLE, "commodity": slug, "metric": "move_pct",
                     "record_kind": kind, "contract": contract, "driver_or_chain_id": driver,
                     "provenance": provenance, "horizon_days": horizon, "asof": asof},
           "rows": leg_rows, "status": "ok", "pattern_provenance": provenance,
           "outcome_horizon_days": horizon}
    signal = {"injected": 1, "table": PO_TABLE, "horizon_days": horizon,
              "horizon_label": OC.horizon_label(horizon), "leviathan_slug": slug,
              "basis": head["basis"], "provenance": provenance,
              "joined": joined, "n_closed": n_closed, "n_pending": n_pending,
              "n_declined": n_declined, "n_unusable": n_unusable, "n_independent": n_independent,
              "pending_share": share, "outcome_stated": suppressed is None,
              "outcome_suppressed": suppressed, "fenced": None,
              "first_firing": row.get("first_firing"), "last_firing": row.get("last_firing"),
              "first_closed_firing": row.get("first_closed_firing"),
              "last_closed_firing": row.get("last_closed_firing"),
              "first_pending_close": row.get("first_pending_close"),
              "last_pending_close": row.get("last_pending_close"),
              "median": med, "p10": p10, "p90": p90, "n_up": n_up, "n_down": n_down}
    return [leg], signal


def _po_cash_slugs() -> frozenset:
    from leviathan.silver import futures_eod_contracts as FC
    return FC.CASH_INDEX_SLUGS


class _Fig:
    """The one place a figure is turned into text, and the SAME expression records that it was shown.

    `cascade._shown` binds the magnitudes a reader LINE printed to the call its [N] handle indexes, so
    the verifier checks a citation against what was displayed rather than against the whole row pool.
    Building the sentence through this object makes the printed string and the bound list the same
    act: there is no second list to keep in step, so they cannot drift the way a hand-maintained
    `shown=[...]` beside a hand-written f-string eventually does."""

    def __init__(self) -> None:
        self.values: list[float] = []

    def n(self, value) -> str:
        """A count, printed as an integer and recorded as one."""
        v = _as_int(value)
        self.values.append(float(v))
        return str(v)

    def pct(self, value) -> str:
        """A move, printed SIGNED to one decimal -- the same rounded number that is on the row."""
        v = _po_round(value)
        v = 0.0 if v is None else v
        self.values.append(float(v))
        return f"{v:+.1f}"


def pattern_outcome_answer(scope: dict, indexed_leg: Optional[tuple], signal: dict,
                           asof: Optional[str] = None) -> Optional[str]:
    """The SEVENTH suppression-or-statement render (item 83), beside the six the rate side owns.

    EIGHT FACTS, EIGHT SENTENCES, and the wording never lets two of them blur -- the same doctrine the
    rate side spends five slugs on, applied to the outcome axis:
      horizon_unsupported  a year is not servable on this basis   -> the exclusion, stated (AM-1)
      slug_unresolved      the ledger key is a node, not a series -> no outcome exists to measure
      not_joined           the pair has no outcome row at all     -> a citable, materialized zero
      unmeasurable         joined, and every firing declined      -> a COVERAGE gap, said as one
      all_pending          joined, and no horizon has closed yet  -> a TIMING fact, with the date
      too_thin             fewer closed horizons than the floor   -> the counts, never a spread
      windows_overlap      the closed horizons re-measure one span-> counts, and why they repeat
      pending_heavy        the closed half is the OLD half        -> counts, and the bias named
    `all_pending` and `too_thin` are deliberately NOT collapsed: one says the measurement has not
    happened yet, the other says it happened too few times, and a reader who is told the wrong one
    forms the wrong expectation about whether waiting helps.

    EVERY FIGURE THIS FUNCTION PRINTS IS A `value` ON THE INJECTED LEG, and the ones it prints are
    bound to the leg as `shown`. Dates are free (the verifier scrubs ISO dates before extracting
    stated figures) and the horizon is written hyphen-glued (`30-day`), which the same scrubber drops
    as a unit descriptor rather than reading as a claim.

    Returns None only when there is nothing honest to say (no leg AND no named suppression) -- the
    caller then leaves the model's own narration to stand."""
    OC = _oc()
    driver = scope.get("driver_or_chain_id", "this driver")
    contract = scope.get("contract", "this contract")
    horizon = _as_int(signal.get("horizon_days") or PO_HORIZONS[0])
    gate = signal.get("outcome_suppressed")
    asof = asof or scope.get("asof") or signal.get("asof")

    # -- the three no-leg refusals: they state no figure, so they need no [N] ----------------------
    if signal.get("fenced"):
        return (f"For {driver} on {contract}, the recorded verdicts available for this pair come from "
                f"the replay grid whose as-of axis is synthesized, so they are not citable history and "
                f"no forward price move is measured from them.")
    if gate == PO_SUP_UNSUPPORTED_HORIZON:
        if horizon >= 180:
            return ("A one-year forward move is not servable on this basis: no agricultural contract "
                    "prints for a full year past an arbitrary anchor, so a year read would have to "
                    "splice across delivery months -- the contaminated basis this join rejects. The "
                    "horizons measured here are one month, two months and a quarter.")
        return (f"A {horizon}-day horizon is not one this axis measures. The horizons measured here "
                f"are one month, two months and a quarter.")
    if gate == PO_SUP_SLUG_UNRESOLVED:
        return (f"For {driver} on {contract}, the ledger's contract key is a graph node rather than a "
                f"price-tape slug, so there is no single series a forward move could be measured on. "
                f"The recorded firing history for this pair is citable; a price outcome is not.")
    if not indexed_leg:
        return None

    idx, leg = indexed_leg
    fig = _Fig()
    joined = signal.get("joined")
    n_closed, n_pending = signal.get("n_closed"), signal.get("n_pending")
    win = _window(signal.get("first_closed_firing"), signal.get("last_closed_firing"))
    pend_from = signal.get("first_pending_close")

    def _bind(text: str) -> str:
        leg["shown"] = list(fig.values)     # what the LINE printed, recorded by the panel itself
        return text

    if gate == PO_SUP_NOT_JOINED:
        return _bind(
            f"For {driver} on {contract}, the outcome table records {fig.n(joined)} joined firings for "
            f"this pair [N{idx}], so I cannot state what price did after them.")
    if gate == PO_SUP_UNMEASURABLE:
        # THE REASONS ARE NOT ENUMERATED, because this branch never asked for them. `po_census_sql`
        # counts declines as ONE bucket (`status NOT IN ('closed','pending')`) and never selects
        # `decline_reason`, while the vocabulary has ten members (outcomes.DECLINE_REASONS) --
        # `no_anchor_session`, `bad_endpoint_price` and `span_inverted` among them. Naming two causes
        # the query did not look for is the same class of error as naming a rate nobody measured, so
        # the sentence states what IS known: joined, unmeasurable, and therefore a coverage gap.
        return _bind(
            f"For {driver} on {contract}, all {fig.n(joined)} recorded firings were joined to the "
            f"price tape and none of them could be measured [N{idx}]. That is a coverage gap, not a "
            f"zero move.")
    if gate == PO_SUP_ALL_PENDING:
        tail = f" the earliest closes {pend_from}." if pend_from else "."
        return _bind(
            f"For {driver} on {contract}, all {fig.n(n_pending)} recorded firings still have an open "
            f"{horizon}-day horizon as of {asof} [N{idx}];{tail} No forward move has closed yet, so "
            f"there is nothing measured to state.")
    if gate == PO_SUP_TOO_THIN:
        return _bind(
            f"For {driver} on {contract}, {fig.n(n_closed)} of the {fig.n(joined)} recorded firings "
            f"have a closed {horizon}-day horizon{win}; {fig.n(n_pending)} are still open [N{idx}]. "
            f"That is too few measured outcomes to state a distribution over, so the count and the "
            f"window are the whole of what I can say.")
    if gate == PO_SUP_OVERLAP:
        n_ind = _as_int(signal.get("n_independent"))
        return _bind(
            f"For {driver} on {contract}, the {fig.n(n_closed)} closed {horizon}-day outcomes stand on "
            f"only {fig.n(n_ind)} non-overlapping window{'' if n_ind == 1 else 's'} [N{idx}], so they "
            f"re-measure the same stretch of tape rather than standing as separate observations, and I "
            f"am not stating a distribution over them.")
    if gate == PO_SUP_PENDING_HEAVY:
        return _bind(
            f"For {driver} on {contract}, {fig.n(n_pending)} of the {fig.n(joined)} recorded firings "
            f"still have an open {horizon}-day horizon and only {fig.n(n_closed)} have closed [N{idx}]. "
            f"A distribution over the closed ones would describe the oldest firings only, so I am not "
            f"stating one.")
    if gate:                                  # an unrecognised slug suppresses and says so plainly
        return _bind(f"For {driver} on {contract}, the {horizon}-day outcome distribution is "
                     f"suppressed ({gate}); the recorded counts stand [N{idx}].")

    # -- the STATEMENT branch ---------------------------------------------------------------------
    basis_clause = ("Each move is measured on the cash reference itself, which has no delivery month"
                    if signal.get("basis") == OC.BASIS_CASH else
                    "Each move is measured on the single delivery month that still printed five "
                    "calendar days past that firing's own horizon, so no roll splice is priced into it")
    line = (f"For {driver} on {contract}, across the {fig.n(n_closed)} recorded firings whose "
            f"{horizon}-day horizon had closed by {asof}{win}, the settle moved a median "
            f"{fig.pct(signal.get('median'))}% [N{idx}]; the low-decile to high-decile spread ran "
            f"{fig.pct(signal.get('p10'))}% to {fig.pct(signal.get('p90'))}%, and "
            f"{fig.n(signal.get('n_up'))} of them closed higher. Those firings stand on "
            f"{fig.n(signal.get('n_independent'))} non-overlapping {horizon}-day windows. "
            f"{basis_clause}.")
    if _as_int(n_pending) > 0:
        tail = f" (the earliest closes {pend_from})" if pend_from else ""
        line += (f" A further {fig.n(n_pending)} recorded firings have a {horizon}-day horizon that "
                 f"has not closed yet{tail}.")
    return _bind(line + " This is what price did after those firings; it is neither a firing rate nor "
                        "a statement about the next one.")


# -- outcome-question detection (the pattern_records_scope idiom: detect ONCE, fail CLOSED) ---------
# Requires an OUTCOME phrase on top of everything pattern_records_scope requires. The persistence
# detector is deliberately NOT reused as a sufficient condition: "how many times has it fired" is a
# question about the ledger and must keep getting the ledger's answer, not a price distribution.
_OUTCOME_INTENT = re.compile(
    r"what (?:did|has|does) .{0,30}\bprices?\b"
    r"|prices? (?:did|do|does|has done|moved|move|reacted|behaved)\b"
    r"|\bforward (?:move|return|price)\b"
    r"|\b(?:after|following) (?:it|they|these|those|the pair)? ?(?:fired|fires|firing)\b"
    r"|\bwhat (?:happened|follows|followed)\b.{0,40}\b(?:fired|firing|firings)\b"
    r"|\bwhat (?:usually |typically )?(?:happens|follows)\b"
    r"|\boutcome[sd]?\b", re.I)
# The horizon tokens, longest-first so 'two-month' never matches the bare 'month' arm. A YEAR token
# resolves to a horizon this axis does not serve, ON PURPOSE: it must reach the AM-1 decline render
# rather than be silently rounded down to the quarter.
_HORIZON_TOKENS: tuple[tuple, ...] = (
    (re.compile(r"\b(?:year|twelve months|12 months|annual|12[- ]month)\b", re.I), 365),
    (re.compile(r"\b(?:quarter|90[- ]days?|three months|3 months)\b", re.I), 90),
    (re.compile(r"\b(?:two months|2 months|60[- ]days?|two[- ]month)\b", re.I), 60),
    (re.compile(r"\b(?:month|30[- ]days?|four weeks)\b", re.I), 30),
)


def pattern_outcome_horizon(question: str) -> int:
    """The horizon a question asks for, defaulting to the SHORTEST member of the family.

    The default is named in every rendered sentence ('whose 30-day horizon had closed'), so a reader
    is never left to assume which window a distribution covers -- which is the only thing that makes a
    default acceptable here at all."""
    for rx, days in _HORIZON_TOKENS:
        if rx.search(question or ""):
            return days
    return PO_HORIZONS[0]


def pattern_outcome_scope(question: str, *, contracts: Optional[list] = None) -> Optional[dict]:
    """Detect an OUTCOME question about a (driver, contract) pair -> the scope dict, or None.

    Fail-CLOSED: an outcome phrase AND a resolvable driver AND a contract must all be present. It is
    NOT a sub-case of `pattern_records_scope` -- "how many times has it fired" is a question about the
    ledger and must keep getting the ledger's answer -- so the persistence phrase is not required and
    the outcome phrase is. Both detectors resolve the pair through `_pr_pair`, so they can never
    disagree about WHICH pair a question is about, only about which question it is.

    The returned scope carries `horizon_days`, which may be a horizon this axis does not serve (a
    year) -- that is deliberate, so the refusal is rendered from the same path as every other answer
    instead of being swallowed by the detector."""
    q = question or ""
    if not _OUTCOME_INTENT.search(q):
        return None
    pair = _pr_pair(q, contracts)
    if not pair:
        return None
    contract, driver, kind = pair
    return {"contract": contract, "driver_or_chain_id": driver, "kind": kind,
            "provenance": PROV_BACKFILL_GRID if _BACKFILL_INTENT.search(q) else PROV_DAILY_SWEEP,
            "horizon_days": pattern_outcome_horizon(q)}


# -- the card + the row invariants (the two lints that keep the clamp compiled and the table honest) -
PO_CARD_FIELDS: dict[str, object] = {
    "shape": "wide",
    "commodity_col": "leviathan_slug",
    "period_col": "as_of_date",           # the reader-facing PERIOD is the FIRING date
    "period_type": "date",
    "date_col": "readable_date",          # the DATA axis the as-of guard compiles on
    "knowledge_date_col": "readable_date",
    "knowledge_semantics": "data_date",
    "year_col": "as_of_year",
    "contract_month_col": "contract_month_used",
    "settle_kind_col": "settle_kind",
    "currency_col": "currency",
}


def lint_pattern_outcome_card(card: Optional[dict] = None) -> list[str]:
    """The `gold_pattern_outcomes` card is coherent with THIS module's constants, or the clamp is prose.

    Identical in force to `outcomes.lint_outcome_card`, and the load-bearing pin is the same one:
    `publication_lag_days == survive_days + tape_lag`. The guard compiles from exactly one column and
    `_pub_lagged_asof` shifts the RHS literal, so those two numbers ARE the clamp once the card is
    served; if `survive_days` moved and the card did not, the compiled predicate would admit rows whose
    CONTRACT SELECTION used tape past the boundary.

    ONE THING THE CARD CANNOT EXPRESS, stated here because a lint that pretends otherwise is worse than
    none: the LEDGER's ingest axis (`ledger_written_at`). `TableSpec.knowledge_col()` yields a single
    column, so a registry-compiled read of this table would guard the horizon close and NOT the date
    the verdict was written -- and a backfill_grid verdict for a 2023 asof was written in 2026. The
    engine leg above applies both axes by hand. Until a second axis exists, this table must stay
    WHITELIST-fenced out of the agent tool enum, so the leg is the only path to it. The lint says so
    rather than leaving it to a reviewer to notice."""
    errs: list[str] = []
    if card is None:
        card, source = _po_read_card()
        if source == "none":
            return [f"pattern-outcome card: {PO_TABLE} is ABSENT from both the numbers registry and "
                    f"the staged card path -- the card is where the PIT clamp compiles; without it a "
                    f"guard would fall on whatever column the schema implies, and with as_of_date that "
                    f"is the WHOLE forward move of a firing that happened yesterday"]
    if not card:
        return [f"pattern-outcome card: {PO_TABLE} is EMPTY"]
    for field, want in sorted(PO_CARD_FIELDS.items()):
        got = card.get(field)
        if got != want:
            errs.append(f"pattern-outcome card: {field} is {got!r}, expected {want!r}")
    want_lag = int(_oc().OUTCOME_PUBLICATION_LAG_DAYS)
    if card.get("publication_lag_days") != want_lag:
        errs.append(
            f"pattern-outcome card: publication_lag_days {card.get('publication_lag_days')!r} != "
            f"{want_lag} (outcomes.OUTCOME_SURVIVE_DAYS + the tape lag) -- the survival margin is HALF "
            f"the PIT boundary and the card is the only place it compiles into SQL")
    parts = list(card.get("partitions") or []) or list(card.get("partition_cols") or [])
    if tuple(parts) != PO_PARTITIONS:
        errs.append(f"pattern-outcome card: partitions {parts} != {list(PO_PARTITIONS)} (registered "
                    f"partitions, projection FORBIDDEN -- the S3 LIST-storm class)")
    if card.get("levels_only"):
        errs.append("pattern-outcome card: levels_only must be false -- every metric on this table IS "
                    "a cross-date delta, computed on ONE contract so no splice exists to fence")
    metrics = set(card.get("metrics") or {})
    for m in ("move_pct", "move_abs"):
        if m not in metrics:
            errs.append(f"pattern-outcome card: metric {m!r} is not declared")
    for m in sorted(metrics):
        if st.is_banned_name(m):
            errs.append(f"pattern-outcome card: metric {m!r} matches the forward-looking ban "
                        f"(fit|trend|forecast|project|extrapolat|predict) -- this axis is descriptive "
                        f"history and nothing else")
    declared = set(po_columns()) | set(PO_PARTITIONS)
    for field in ("commodity_col", "period_col", "date_col", "knowledge_date_col", "year_col",
                  "contract_month_col", "settle_kind_col", "currency_col"):
        if card.get(field) and card[field] not in declared:
            errs.append(f"pattern-outcome card: {field}={card[field]!r} is not a column the builder "
                        f"writes")
    return errs


def _po_read_card() -> tuple[Optional[dict], str]:
    """`(card, source)` where source is 'served' | 'staged' | 'none'. The SERVED registry wins the
    moment the card is pasted into it, so nothing has to be un-wired at that point."""
    try:
        import yaml

        from leviathan.graphrag import extract as ex
        served = ex._CFG / "numbers" / "tables.yaml"
        if served.exists():
            doc = yaml.safe_load(served.read_text(encoding="utf-8")) or {}
            got = (doc.get("tables") or {}).get(PO_TABLE)
            if got:
                return got, "served"
        staged = ex._CFG / "numbers" / "cards" / f"{PO_TABLE}.yaml"
        if staged.exists():
            doc = yaml.safe_load(staged.read_text(encoding="utf-8")) or {}
            got = (doc.get("tables") or {}).get(PO_TABLE)
            if got:
                return got, "staged"
    except Exception:  # noqa: BLE001 -- an unreadable config is a lint error, not a crash
        return None, "none"
    return None, "none"


def po_reconcile(rows: Sequence[dict]) -> dict:
    """The build census, per (pair, horizon), with the identity acceptance leg (ii) asks for.

    The plan states it as `n_pending + n_closed == n_firings`. That is true only where nothing
    declined, and declines are structural here (a firing before the contract's coverage floor, a
    horizon no single delivery month survives), so the identity is carried with its THIRD TERM NAMED:
    `n_closed + n_pending + n_declined == n_firings`. Dropping the declined term instead would make
    the check pass by shrinking the denominator -- which is the failure the check exists to catch."""
    per: dict[tuple, dict] = {}
    for r in rows or []:
        key = tuple(str(r.get(c) or "") for c in PO_KEY_COLUMNS[:4]) + (_as_int(r.get("horizon_days")),)
        cell = per.setdefault(key, {"n_firings": 0, "n_closed": 0, "n_pending": 0, "n_declined": 0,
                                    "n_unknown": 0})
        cell["n_firings"] += 1
        status = str(r.get("status") or "")
        if status == "closed":
            cell["n_closed"] += 1
        elif status == "pending":
            cell["n_pending"] += 1
        elif status.startswith("declined_"):
            cell["n_declined"] += 1
        else:
            cell["n_unknown"] += 1
    return {"pairs": len(per), "per_pair": per,
            "n_firings": sum(c["n_firings"] for c in per.values()),
            "n_closed": sum(c["n_closed"] for c in per.values()),
            "n_pending": sum(c["n_pending"] for c in per.values()),
            "n_declined": sum(c["n_declined"] for c in per.values()),
            "n_unknown": sum(c["n_unknown"] for c in per.values())}


def lint_pattern_outcome_rows(rows: Sequence[dict]) -> list[str]:
    """The write-time invariants of `gold_pattern_outcomes`. The builder runs this over its own output
    and a publish refuses on any violation; a test runs it over fixtures.

    It is the join's own row lint (`outcomes.lint_outcome_row_invariants` -- a move is never readable
    before its horizon closes; a pending row carries no measurement; a survivor-basis row names its
    contract) PLUS the four things only this table can get wrong: a key that does not trace back to a
    ledger verdict, an anchor that is not the firing date, a horizon outside the family, and a row
    built from a FENCED (leaked-as-of) verdict."""
    OC = _oc()
    errs: list[str] = list(OC.lint_outcome_row_invariants(rows))
    seen: set[tuple] = set()
    for i, r in enumerate(rows or []):
        missing = [c for c in PO_KEY_COLUMNS if not str(r.get(c) or "").strip()]
        if missing:
            errs.append(f"row {i}: missing ledger key column(s) {missing} -- an outcome that cannot be "
                        f"traced back to the verdict it measures is not a ledger outcome")
            continue
        if not str(r.get("ledger_written_at") or "").strip():
            errs.append(f"row {i}: no ledger_written_at -- the verdict's INGEST axis is the second PIT "
                        f"guard on this table (a 2023-asof backfill verdict was written in 2026)")
        horizon = _as_int(r.get("horizon_days"))
        if horizon not in PO_HORIZONS:
            errs.append(f"row {i}: horizon_days {horizon} is outside the family {list(PO_HORIZONS)}")
        if pr_read_fenced(str(r.get("record_kind")), str(r.get("provenance"))):
            errs.append(f"row {i}: built from a FENCED (record_kind, provenance) pair -- those verdicts "
                        f"were replayed against a synthesized as-of axis and are not citable history")
        want_key = po_anchor_key(r.get("record_kind"), r.get("contract"), r.get("driver_or_chain_id"),
                                 r.get("provenance"), r.get("as_of_date"))
        if str(r.get("event_key") or "") != want_key:
            errs.append(f"row {i}: event_key {r.get('event_key')!r} != {want_key!r}")
        if str(r.get("event_date") or "")[:10] != str(r.get("as_of_date") or "")[:10]:
            errs.append(f"row {i}: event_date {r.get('event_date')!r} != as_of_date "
                        f"{r.get('as_of_date')!r} -- the anchor of a pattern outcome IS the firing")
        if not po_resolve_slug(r.get("leviathan_slug")):
            errs.append(f"row {i}: leviathan_slug {r.get('leviathan_slug')!r} is not a mapped price "
                        f"slug -- unresolvable contracts are SKIPPED and counted, never written")
        key = (want_key, horizon)
        if key in seen:
            errs.append(f"row {i}: duplicate (ledger key, horizon) {key} -- the grain is one row per "
                        f"firing per horizon")
        seen.add(key)
    census = po_reconcile(rows)
    if census["n_unknown"]:
        errs.append(f"{census['n_unknown']} row(s) carry a status outside "
                    f"closed|pending|declined_<reason>")
    for key, cell in sorted(census["per_pair"].items()):
        got = cell["n_closed"] + cell["n_pending"] + cell["n_declined"]
        if got != cell["n_firings"]:
            errs.append(f"{key}: closed({cell['n_closed']}) + pending({cell['n_pending']}) + "
                        f"declined({cell['n_declined']}) = {got} != {cell['n_firings']} firings")
    return errs


# The reader-facing [N]-rendering directive for the OUTCOME line, and the numbers-agent conventions
# bullet for the outcome table. BOTH ARE DECLARED AND NOT YET WIRED, deliberately: their edit sites
# (answer.py `_system`, agent.py `system_prompt`, and the leg-append site at the pattern-records
# branch) are files the in-flight wave owns, and the plan's own sequencing rule is that no J-item is
# authored against a file another item is editing (item 95a). Wiring them is a one-commit change after
# the wave's confirmation run: append these two strings beside their pattern-records twins under the
# same flag, and append `pattern_outcome_legs` beside `pattern_records_legs`. Until then the outcome
# surface is engine-testable and reader-invisible, which is the omit-when-off property the flag parity
# smoke depends on.
OUTCOME_HISTORY_ADDENDUM = (
    "\nRECORDED OUTCOMES. When a 'RECORDED OUTCOMES' [N] row is injected, it is a DESCRIPTIVE record of "
    "what price did over a fixed forward window after past firings of one (driver, contract) pair -- "
    "measured, not modelled. State the figures and the dates EXACTLY as the [N] row prints them, "
    "including the horizon, the number of firings the distribution covers and the number whose horizon "
    "has NOT closed yet; never drop the pending count, because a distribution over what has closed "
    "describes the OLDEST firings only. If the injected line states no distribution -- because too few "
    "horizons have closed, because the closed ones re-measure the same stretch of tape, or because the "
    "pair could not be measured against the price tape at all -- carry that clause through verbatim and "
    "do NOT compute a central tendency yourself. NEVER restate an outcome distribution as a "
    "probability, an expectation, or a claim about what will happen after the next firing: it is a "
    "record of what happened, and the reader draws any conclusion.\n")

PO_AGENT_CONVENTIONS_BULLET = (
    "- gold_pattern_outcomes records what PRICE DID after each recorded firing in gold_pattern_records: "
    "one row per (record_kind, contract, driver_or_chain_id, as_of_date, horizon_days) for the 30 / 60 "
    "/ 90-day horizons, measured on ONE delivery month per firing (the nearest expiry that still "
    "printed five calendar days past the horizon close), so no roll splice is priced into the move. "
    "`status` "
    "is the whole point-in-time story: 'closed' = measured; 'pending' = that horizon has not closed yet "
    "at this as-of and the row carries NO move, only the date it closes; 'declined_<reason>' = it could "
    "not be measured. Report closed and pending counts TOGETHER -- dropping pending firings biases "
    "every summary toward the oldest ones. There is no year horizon on this table and there will not "
    "be one: no contract prints that long past an anchor. Descriptive history only -- no rate, no "
    "expectation, no forward statement.\n")
