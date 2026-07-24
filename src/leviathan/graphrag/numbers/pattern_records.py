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


def presence_sql(contract: str, driver_or_chain_id: str, *, kind: str, asof: str,
                 provenance: str = PROV_DAILY_SWEEP) -> str:
    """The SCALAR presence aggregation (F8). Returns EXACTLY ONE row -- always, by construction:

        recorded_firings  COUNT of verdict=fired rows (a materialized 0 when only declines / not covered)
        sweeps_total      COUNT(*) of swept rows for the pair (0 == the pair is NOT in the swept catalog)
        declined_count    COUNT of verdict=declined rows
        first_recorded    MIN(as_of_date) among fired rows (NULL when recorded_firings=0)
        last_recorded     MAX(as_of_date) among fired rows (NULL when recorded_firings=0)

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
    return (
        "SELECT "
        "COUNT(CASE WHEN verdict = 'fired' THEN 1 END) AS recorded_firings, "
        "COUNT(*) AS sweeps_total, "
        "COUNT(CASE WHEN verdict = 'declined' THEN 1 END) AS declined_count, "
        "MIN(CASE WHEN verdict = 'fired' THEN as_of_date END) AS first_recorded, "
        "MAX(CASE WHEN verdict = 'fired' THEN as_of_date END) AS last_recorded "
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
    return {"recorded_firings": 0, "sweeps_total": 0, "declined_count": 0,
            "first_recorded": None, "last_recorded": None}


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

        {injected, recorded_firings, sweeps_total, in_catalog, provenance, zero_materialized}

    zero_materialized=True is the F8 honesty mechanism firing: an in-catalog OR not-covered pair with
    recorded_firings=0 STILL injects a citable 0-count leg, so the model cites "no firing recorded" as a
    FACT instead of minting a streak. A leg is emitted even for the 0 case -- injected is 0 ONLY if the
    lookup itself errored (fail-closed, never a silent fabrication)."""
    contract = scope.get("contract")
    driver = scope.get("driver_or_chain_id")
    kind = scope.get("kind", KIND_PACE)
    provenance = scope.get("provenance", PROV_DAILY_SWEEP)
    if not (contract and driver and kind in V1_KINDS):
        return [], {"injected": 0, "recorded_firings": 0, "sweeps_total": 0, "in_catalog": False,
                    "provenance": provenance, "zero_materialized": False}
    sql = (baserate_backfill_sql(contract, driver, kind=kind, asof=asof)
           if provenance == PROV_BACKFILL_GRID
           else presence_sql(contract, driver, kind=kind, asof=asof, provenance=provenance))
    try:
        rows = query_fn(sql)
    except Exception:  # noqa: BLE001 -- a mirror gap is a probe error, NEVER a fabricated firing
        return [], {"injected": 0, "recorded_firings": 0, "sweeps_total": 0, "in_catalog": False,
                    "provenance": provenance, "zero_materialized": False}
    row = _one_row(rows)
    recorded = _as_int(row.get("recorded_firings"))
    sweeps = _as_int(row.get("sweeps_total"))
    in_catalog = sweeps > 0
    # the citable row: `value` = the recorded firing count (a 0 is a real, citable observation).
    leg_row = {
        "value": recorded,
        "sweeps_total": sweeps,
        "first_recorded": row.get("first_recorded"),
        "last_recorded": row.get("last_recorded"),
        "declined_count": _as_int(row.get("declined_count")),
        "in_catalog": in_catalog,
        "provenance": provenance,
        "knowledge_date": asof,
        "unit": None,
    }
    leg = {"query": {"table": PR_TABLE, "record_kind": kind, "contract": contract,
                     "driver_or_chain_id": driver, "provenance": provenance, "asof": asof},
           "rows": [leg_row], "status": "ok", "pattern_provenance": provenance}
    signal = {"injected": 1, "recorded_firings": recorded, "sweeps_total": sweeps,
              "in_catalog": in_catalog, "provenance": provenance,
              "zero_materialized": recorded == 0}
    return [leg], signal


def pattern_records_answer(scope: dict, indexed_leg: tuple[int, dict], signal: dict) -> Optional[str]:
    """The reader-facing OBSERVATION-register line built from the injected leg and its 1-based [N]
    position. Reports the COUNT + the DATES; NEVER a conclusion (no signal/setup/regime/trend/
    confirms/breakout/persistent -- pr_register_leaks pins it). Returns None when there is no leg (the
    caller then leaves the model's own honest narration to stand)."""
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
    if recorded == 0:
        if signal.get("in_catalog"):
            # in the swept catalog, but every recorded sweep DECLINED -> a materialized 0 (F8).
            return (f"For {driver} on {contract}, the engine has recorded no firing on any of its "
                    f"{sweeps} {unit} so far [N{idx}] -- there is no recorded firing history for this "
                    f"pair yet; I cannot state a run length.")
        # not in the swept catalog / before the first partition -> "not covered", not a 0-firing claim.
        return (f"The engine has not recorded this pair in the swept ledger yet [N{idx}], so there is "
                f"no recorded firing history to cite.")
    first = row.get("first_recorded")
    line = f"The engine has recorded {driver} on {contract} firing on {recorded} of {sweeps} {unit} [N{idx}]"
    if first:
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
    "row prints them (e.g. \"recorded firing on 9 of 12 sweeps, first recorded 2026-07-15 [N]\"). If the "
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
    "or direction word (the reader interprets). `contract` is the focus contract slug; "
    "`driver_or_chain_id` is the driver node id (e.g. export_pace) or chain id. Filter "
    "provenance='daily_sweep' for the recorded daily firing history; provenance='backfill_grid' is a "
    "SEPARATE labelled engine base rate over vintaged replay asofs (phrase it 'weekly replay asofs', "
    "not recent daily firing). If no firing is recorded for the pair, say so plainly -- do NOT infer a "
    "run length.\n")
