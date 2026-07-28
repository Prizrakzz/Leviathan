"""T2B pattern-records SERVING surface -- the SQL-lane aggregation over gold_pattern_records.

The daily engine-replay sweep (jobs/batch/pattern_records_sweep_task.py, Writer A) writes ONE row per
(record_kind, contract, driver_or_chain_id, as_of_date) recording the deterministic engine's OWN
fired/declined verdict AT that asof. This module is the READ half: it turns "has this (driver, contract)
pair fired before, and on how many sweeps" into a CITABLE [N] fact read from an ordinary observed table
(plan secs 4 / 4.2 / 4.3), register-fenced to OBSERVATION only.

Two doctrine points this module enforces, both load-bearing (plan F8 / F7 / 3.3):

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

AWS-free + engine-agnostic: every SQL string is ANSI (COUNT / CASE / MIN / substr) so it runs
byte-identically on the pg mirror (serving), Athena, and sqlite (tests). The as-of guard is
substr(cast(col as varchar),1,10) <= asof -- the DP-5 timestamp normalization so a physical
`written_at` timestamp and its TEXT pg mirror compare identically at date grain.
"""
from __future__ import annotations

import os
import re
from typing import Optional

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


def pattern_records_legs(scope: dict, asof: str, query_fn) -> tuple[list[dict], dict]:
    """Run the presence/base-rate aggregation for a persistence-scoped question and return
    (legs, signal). `legs` are injected into the numbers-agent `calls` exactly like an ESR aggregate leg
    (each carries `query` + a `rows` list whose `value` is the citable count), so the unify/verify path
    mints a real [N] handle. `signal` is the deterministic trace record the eval + soak read (the
    pace_fired idiom):

        {injected, recorded_firings, sweeps_total, sweeps_evaluable, sweeps_unmeasurable, in_catalog,
         provenance, zero_materialized, rate_stated, first_evaluable, last_evaluable}

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
             "first_evaluable": None, "last_evaluable": None}
    if not (contract and driver and kind in V1_KINDS):
        return [], dict(_dead)
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
              "rate_stated": recorded > 0 and evaluable >= PR_MIN_EVALUABLE_SWEEPS,
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

    if evaluable < PR_MIN_EVALUABLE_SWEEPS:
        # COVERAGE FLOOR: the count and the window are facts and stay; the RATIO does not get stated.
        # The window on the COUNT is the fired window -- pinning the evaluable span to a firing count
        # would imply firings on dates that did not fire.
        plural = "" if recorded == 1 else "s"
        line = (f"For {driver} on {contract}, the engine has recorded {recorded} firing{plural}"
                f"{_fired_window(row)} [N{idx}]. Only {evaluable} of the {sweeps} attempted {unit} "
                f"carried data it could evaluate")
        if win and win != _fired_window(row):
            line += f" ({win.lstrip(', ')})"
        return line + ", which is too short a recorded history to state a firing rate."

    if recorded == evaluable:
        line = (f"For {driver} on {contract}, the engine has recorded firing on all {evaluable} "
                f"{unit} it could evaluate{win} [N{idx}]")
    else:
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


def pattern_records_scope(question: str, *, contracts: Optional[list] = None) -> Optional[dict]:
    """Detect a persistence/history question about a (driver, contract) pair and return the scope dict
    {contract, driver_or_chain_id, kind, provenance}, or None. The backfill ENGINE base-rate path
    (provenance=backfill_grid) is chosen for a 'how often / base rate / over the replay history' ask; the
    daily_sweep presence path (which materializes a citable 0 for a pair with no firing) otherwise."""
    q = question or ""
    if not _PERSIST_INTENT.search(q):
        return None
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
    "line states no rate, do not compute one. If the "
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
