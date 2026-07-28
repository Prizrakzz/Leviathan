"""T2B Lane A -- THE DENOMINATOR. The 2026-07-25 gate (94468a0b) printed, verbatim, in three answers:

    "The engine has recorded export_pace on CBOT corn firing on 9 of 156 weekly replay asofs"

A desk reads "9 of 156" as ~6%: a rare event. The probed truth on the live ledger
(s3://leviathan-dev-shahem-001/gold/pattern_records/, 39,156 canonical rows / 156 partitions) is the
opposite claim: 147 of the 156 replay dates declined with decline_reason='fetch_error' -- the ESR vintage
snapshots only begin 2026-05-24, so 2023-08-05..2026-05-23 had NOTHING to replay against -- genuine
"evaluated and did NOT fire" is ZERO, and the 9 firings are 9 CONSECUTIVE weeks, i.e. it fired on every
single week it could be measured. The denominator was counting BLINDNESS as non-events.

These tests pin the fix on the REAL slice: the weekly 156-asof grid 2023-08-05..2026-07-25, 9 fired at
the tail (2026-05-30..2026-07-25), 147 fetch_error declines -- reproduced exactly as probed, so the
regression is anchored to production data rather than to a convenient invention.

AWS-free: the same ANSI SQL string serving runs on the pg mirror is exercised against in-memory sqlite.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3

from leviathan.graphrag import citations as cit
from leviathan.graphrag import orchestrator as orc
from leviathan.graphrag.numbers import pattern_records as pr

import jobs.batch.pattern_records_sweep_task as prs

WRITTEN_AT = "2026-07-25 08:57:27.175221"          # the real slice's written_at, to the microsecond
SCOPE = {"contract": "corn_cbot", "driver_or_chain_id": "export_pace", "kind": "pace",
         "provenance": pr.PROV_BACKFILL_GRID}
ASOF = "2026-07-25"


# ── fixtures ───────────────────────────────────────────────────────────────────────────────────────
def _conn(rows, states=None):
    """rows = [(as_of_date, verdict, decline_reason)] for corn_cbot/export_pace/pace/backfill_grid.

    The VALUE-BEARING columns are carried because the production table carries them (registry contract
    gold_pattern_records: window_change/n_points/streak_len/streak_dir/n_rows/grain are physical columns,
    and the pg mirror loads all of them) and the vintage-depth probe reads them. A fixture without them is
    not a mirror of production, it is a mirror with a hole -- and the hole reads as "depth unknown", which
    fails closed and suppresses every rate.

    `states` = how many DISTINCT recorded value-states the fired sweeps take. Default None = one per fired
    asof, i.e. the world where every sweep saw a fresh source vintage, which is the only world in which a
    rate is legitimately statable. Pass a small int to reproduce the LIVE ledger's shape, where many asofs
    resolve to the same source snapshot. Declined-but-evaluable rows carry no values at all (the writer
    sets n_rows=0 and leaves the rest NULL), so they all collapse into ONE further state -- faithful to
    production, and an under-count of true vintage depth in the fail-closed direction."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE gold_pattern_records (record_kind TEXT, contract TEXT, "
              "driver_or_chain_id TEXT, verdict TEXT, decline_reason TEXT, as_of_date TEXT, "
              "written_at TEXT, provenance TEXT, window_change REAL, n_points INTEGER, "
              "streak_len INTEGER, streak_dir TEXT, n_rows INTEGER, grain TEXT)")
    out, nfired = [], 0
    for d, v, r in rows:
        wc = np = nr = gr = None
        if v == "fired":
            wc = float(nfired % states if states else nfired) + 0.5
            np, nr, gr, nfired = 8, 1, "week", nfired + 1
        else:
            nr = 0
        out.append(("pace", "corn_cbot", "export_pace", v, r, d, WRITTEN_AT, "backfill_grid",
                    wc, np, None, None, nr, gr))
    c.executemany("INSERT INTO gold_pattern_records VALUES (" + ",".join(["?"] * 14) + ")", out)
    c.commit()
    return c


def _qfn(conn):
    def run(sql: str):
        cur = conn.execute(sql)
        cols = [x[0] for x in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    return run


def _weekly(end: str, n: int) -> list[str]:
    e = _dt.date.fromisoformat(end)
    return [(e - _dt.timedelta(weeks=i)).isoformat() for i in range(n - 1, -1, -1)]


def _real_corn_slice() -> list[tuple]:
    """The PROBED slice: 156 weekly asofs 2023-08-05..2026-07-25; the last 9 fired; the other 147
    declined fetch_error (the pre-ESR-vintage span of the grid)."""
    grid = _weekly(ASOF, 156)
    assert grid[0] == "2023-08-05" and grid[-1] == ASOF        # the probed endpoints
    return ([(d, "declined", "fetch_error") for d in grid[:-9]]
            + [(d, "fired", None) for d in grid[-9:]])


def _answer(rows, scope=None, asof=ASOF, states=None):
    scope = scope or SCOPE
    legs, sig = pr.pattern_records_legs(scope, asof, _qfn(_conn(rows, states)))
    line = pr.pattern_records_answer(scope, (1, legs[0]), sig)
    return legs, sig, line


# ── (1) the flagship: the 9/156 case now renders the honest sentence ───────────────────────────────
def test_real_corn_slice_counts_only_evaluable_sweeps():
    legs, sig, line = _answer(_real_corn_slice())
    row = legs[0]["rows"][0]
    # the raw attempted total KEEPS its old meaning (honest context, nothing downstream re-reads it)...
    assert sig["sweeps_total"] == 156 and row["sweeps_total"] == 156
    # ...and the evaluable count is ADDITIVE: 147 blind fetch_errors are not non-events.
    assert sig["sweeps_evaluable"] == 9 and sig["sweeps_unmeasurable"] == 147
    assert sig["recorded_firings"] == 9                        # unchanged: the numerator is a fact
    # the covered window is the span that was ever measurable, and it is NAMED.
    assert row["first_evaluable"] == "2026-05-30" and row["last_evaluable"] == "2026-07-25"
    assert "2026-05-30" in line and "2026-07-25" in line
    # THE INVERSION IS GONE: the sentence can never again read as "9 of 156 == a ~6% rare event".
    assert "9 of 156" not in line
    assert "156" in line, "the attempted total must still appear -- silence about coverage is not honesty"
    assert "carried data" in line, "the reader must be TOLD the rest of the grid was unmeasurable"


def test_real_corn_slice_states_no_rate_under_the_coverage_floor():
    _legs, sig, line = _answer(_real_corn_slice())
    assert sig["sweeps_evaluable"] < pr.PR_MIN_EVALUABLE_SWEEPS
    assert sig["rate_stated"] is False
    assert "too short a recorded history to state a firing rate" in line
    # the COUNT and the WINDOW survive the floor -- suppressing those would hand the model back the
    # empty-ledger state where it mints a cross-day streak from the within-turn pace figure.
    assert "9 firings" in line


# ── (2) a genuine non-event slice still reports a real base rate ───────────────────────────────────
def _nonevent_slice() -> list[tuple]:
    """20 evaluable weekly asofs (14 fired + 6 declined thin_history -- the engine held a resolved
    series and produced no pace claim) behind 30 blind fetch_error asofs."""
    grid = _weekly(ASOF, 50)
    out = [(d, "declined", "fetch_error") for d in grid[:30]]
    for i, d in enumerate(grid[30:]):
        out.append((d, "declined", "thin_history") if i % 10 in (3, 7) else (d, "fired", None))
    return out


def test_genuine_non_events_count_and_a_real_base_rate_is_stated():
    legs, sig, line = _answer(_nonevent_slice())
    assert sig["sweeps_total"] == 50
    assert sig["sweeps_evaluable"] == 20 and sig["recorded_firings"] == 16
    assert sig["rate_stated"] is True
    # a sweep that RAN and decided not to fire IS a real non-event -- it must still count.
    assert "16 of the 20" in line and "could evaluate" in line
    # coverage is materially incomplete, so the SAME SENTENCE says so.
    assert "only 20 of the 50 attempted carried data" in line
    assert "16 of 50" not in line and "16 of the 50" not in line


def test_full_coverage_states_the_rate_without_a_coverage_caveat():
    grid = _weekly(ASOF, 20)
    rows = [(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None)
            for i, d in enumerate(grid)]
    _legs, sig, line = _answer(rows)
    assert sig["sweeps_total"] == sig["sweeps_evaluable"] == 20 and sig["recorded_firings"] == 16
    assert "16 of the 20" in line
    assert "attempted carried data" not in line, "no coverage caveat when nothing was unmeasurable"


def test_all_evaluable_fired_reads_as_every_check_not_a_fraction():
    grid = _weekly(ASOF, 40)
    rows = ([(d, "declined", "fetch_error") for d in grid[:20]]
            + [(d, "fired", None) for d in grid[20:]])
    _legs, sig, line = _answer(rows)
    assert sig["recorded_firings"] == 20 and sig["sweeps_evaluable"] == 20
    assert "on all 20" in line, "100%-of-measurable must read as such, not as 20 of 40"
    assert "20 of 40" not in line


# ── (3) the coverage floor ─────────────────────────────────────────────────────────────────────────
def test_below_floor_suppresses_the_rate_at_the_boundary():
    """The floor is a boundary, not a vibe: one evaluable sweep either side flips the sentence.

    The slice is deliberately NON-degenerate (one evaluable sweep declines thin_history) so the floor is
    the ONLY gate under test. An all-fired slice would be suppressed by the variance gate on both sides of
    the boundary and this test would pass for the wrong reason."""
    n_blind = 5
    for evaluable, want_rate in ((pr.PR_MIN_EVALUABLE_SWEEPS - 1, False),
                                 (pr.PR_MIN_EVALUABLE_SWEEPS, True)):
        grid = _weekly(ASOF, evaluable + n_blind)
        rows = ([(d, "declined", "fetch_error") for d in grid[:n_blind]]
                + [(grid[n_blind], "declined", "thin_history")]
                + [(d, "fired", None) for d in grid[n_blind + 1:]])
        _legs, sig, line = _answer(rows)
        assert sig["sweeps_evaluable"] == evaluable
        assert sig["rate_stated"] is want_rate
        assert ("too short a recorded history to state a firing rate" in line) is (not want_rate)
        assert sig["rate_suppressed"] == (None if want_rate else pr.PR_SUP_TOO_THIN)


def test_floor_is_a_named_constant_chosen_above_the_flagship_coverage():
    # the justification is in the module; the property the tests defend is that 9 -- the entire
    # measurable history of every pace pair in the live ledger -- does NOT clear it.
    assert isinstance(pr.PR_MIN_EVALUABLE_SWEEPS, int)
    assert pr.PR_MIN_EVALUABLE_SWEEPS > 9


# ── (4) the honest-zero branch carries the SAME coverage honesty ───────────────────────────────────
def test_honest_zero_quotes_the_evaluable_denominator_not_the_attempted_total():
    """F8's materialized zero had the identical defect: 'no firing on any of its 156 sweeps' claims 156
    measured non-events when only 9 were ever measured."""
    grid = _weekly(ASOF, 156)
    rows = ([(d, "declined", "fetch_error") for d in grid[:-9]]
            + [(d, "declined", "thin_history") for d in grid[-9:]])
    legs, sig, line = _answer(rows)
    assert sig["recorded_firings"] == 0 and sig["zero_materialized"] is True
    assert sig["in_catalog"] is True and sig["sweeps_evaluable"] == 9
    assert len(legs) == 1, "the zero STILL injects a citable leg -- silence is not honesty (F8)"
    assert "no firing on any of the 9" in line and "156" in line
    assert "any of its 156" not in line and "no firing on any of the 156" not in line
    assert "2026-05-30" in line                                  # the covered window is named here too
    assert "too short to read as a rate" in line                 # the floor applies to the zero as well


def test_honest_zero_with_no_evaluable_sweep_says_nothing_was_measured():
    """Every sweep blind: the pair is in the catalog but the engine has measured NOTHING. Claiming
    'no firing on any of its 156 sweeps' here is the purest form of the inversion."""
    legs, sig, line = _answer([(d, "declined", "fetch_error") for d in _weekly(ASOF, 156)])
    assert sig["in_catalog"] is True and sig["sweeps_evaluable"] == 0 and sig["recorded_firings"] == 0
    assert len(legs) == 1 and sig["zero_materialized"] is True
    assert "could not evaluate any of them" in line and "156" in line
    assert "cannot state a run length or a rate" in line


def test_not_covered_branch_is_unchanged_and_states_no_figure():
    legs, sig, line = _answer([], scope=SCOPE)
    assert sig["in_catalog"] is False and sig["sweeps_total"] == 0 and sig["sweeps_evaluable"] == 0
    assert "not recorded this pair in the swept ledger yet" in line
    assert orc._verify_numbers_answer(line, legs)["mismatched"] == 0


# ── (5) register + verifier: the two properties that must hold on EVERY branch ─────────────────────
def _every_branch():
    """(name, rows, states) covering every prose branch the module can emit."""
    grid156 = _weekly(ASOF, 156)
    g20, g40 = _weekly(ASOF, 20), _weekly(ASOF, 40)
    return [
        ("flagship_9_of_156", _real_corn_slice(), None),
        ("nonevent_rate", _nonevent_slice(), None),
        ("no_variance_full_coverage", [(d, "fired", None) for d in g20], None),
        # W2a: fired on every evaluable sweep AND half the grid dark -> the constant sentence + coverage.
        ("no_variance_partial", [(d, "declined", "fetch_error") for d in g40[:20]]
                                + [(d, "fired", None) for d in g40[20:]], None),
        # W2b: real variance and enough sweeps, but they resolve to ~3 distinct source states.
        ("vintage_too_shallow", [(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None)
                                 for i, d in enumerate(g20)], 2),
        ("below_floor", [(d, "fired", None) for d in _weekly(ASOF, 4)], None),
        ("single_firing", [(_weekly(ASOF, 1)[0], "fired", None)], None),
        ("honest_zero_partial", [(d, "declined", "fetch_error") for d in grid156[:-9]]
                                + [(d, "declined", "thin_history") for d in grid156[-9:]], None),
        ("honest_zero_all_blind", [(d, "declined", "fetch_error") for d in grid156], None),
        ("honest_zero_full_coverage", [(d, "declined", "thin_history") for d in g20], None),
        ("not_covered", [], None),
    ]


def test_register_stays_clean_on_every_branch():
    for name, rows, states in _every_branch():
        _legs, _sig, line = _answer(rows, states=states)
        assert pr.pr_register_leaks(line) == [], f"{name}: OBSERVATION register leaked -> {line!r}"


def test_verifier_grounds_every_figure_the_preface_states_on_every_branch():
    """The D1/D1b property (commit 1b0e2d19) must survive the rewrite: the engine's OWN deterministic
    sentence must never wear the '_[verifier: a value stated below does not match any looked-up row]_'
    caution banner. orchestrator._verify_numbers_answer is OUTSIDE this lane and is not widened -- the
    new evaluable denominator is grounded by riding the leg's second row as a citable `value`."""
    for name, rows, states in _every_branch():
        legs, _sig, line = _answer(rows, states=states)
        v = orc._verify_numbers_answer(line, legs)
        assert v["mismatched"] == 0, f"{name}: ungrounded stated figure(s) {v['mismatch_values']} in {line!r}"


def test_verifier_would_still_catch_a_fabricated_figure():
    """Anti-vacuity: the check above must not be passing because nothing is ever flagged."""
    legs, _sig, line = _answer(_real_corn_slice())
    # a bare fabricated count -- NOT '37 weeks', which the verifier's duration scrub legitimately eats.
    assert orc._verify_numbers_answer(line + " The run length was 37.", legs)["mismatched"] == 1


# ── (6) leg shape: the coverage row must not displace the firing count anywhere it is read ─────────
def test_leg_carries_both_counts_and_the_citation_still_headlines_the_firing_count():
    legs, sig, _line = _answer(_real_corn_slice())
    rows = legs[0]["rows"]
    assert [r["measure"] for r in rows] == ["recorded_firings", "sweeps_evaluable"]
    assert rows[0]["value"] == 9 and rows[1]["value"] == 9
    # citations.from_number headlines max(rows, key=_row_order_key); the keys tie, so rows[0] wins.
    c = cit.from_number(legs[0], 1)
    assert c.value == str(sig["recorded_firings"])


def test_evaluable_is_clamped_and_falls_back_to_fired_on_a_mirror_without_the_column():
    """A pg mirror that predates the additive column returns no sweeps_evaluable. Falling back to
    sweeps_total there would silently resurrect the blindness-inflated denominator, so the fallback is
    the FIRED count -> coverage reads as rate-unstatable, never as a fake rate."""
    def stale(_sql):
        return [{"recorded_firings": 9, "sweeps_total": 156, "declined_count": 147,
                 "first_recorded": "2026-05-30", "last_recorded": "2026-07-25"}]
    legs, sig = pr.pattern_records_legs(SCOPE, ASOF, stale)
    assert sig["sweeps_evaluable"] == 9 and sig["rate_stated"] is False
    line = pr.pattern_records_answer(SCOPE, (1, legs[0]), sig)
    assert "9 of 156" not in line and orc._verify_numbers_answer(line, legs)["mismatched"] == 0

    def absurd(_sql):
        return [{"recorded_firings": 2, "sweeps_total": 5, "sweeps_evaluable": 99}]
    _legs2, sig2 = pr.pattern_records_legs(SCOPE, ASOF, absurd)
    assert sig2["sweeps_evaluable"] == 5, "evaluable can never exceed the attempted total"


def test_probe_error_still_fails_closed():
    def boom(_sql):
        raise RuntimeError("mirror gap")
    legs, sig = pr.pattern_records_legs(SCOPE, ASOF, boom)
    assert legs == [] and sig["injected"] == 0 and sig["rate_stated"] is False


# ── (7) the classification itself: complete, disjoint, and fail-closed on an unknown reason ────────
def test_every_decline_reason_the_writer_can_emit_is_classified():
    """DRIFT GUARD. A new decline reason must be classified deliberately, not default into a
    denominator. The writer's three enums are the whole vocabulary the ledger can ever hold."""
    declared = set(prs.PACE_DECLINE_REASONS) | set(prs.CHAIN_DECLINE_REASONS) | set(prs.CASCADE_DECLINE_REASONS)
    classified = pr.PR_NONEVENT_DECLINES | pr.PR_BLIND_DECLINES
    assert declared - classified == set(), f"unclassified decline reason(s): {sorted(declared - classified)}"
    assert pr.PR_NONEVENT_DECLINES & pr.PR_BLIND_DECLINES == set(), "a reason cannot be both"
    # the three reasons the LIVE ledger actually holds (S3 census, 39,156 canonical rows) are all blind.
    assert {"fetch_error", "region-unresolved", "waived"} <= pr.PR_BLIND_DECLINES


def test_unknown_decline_reason_is_not_counted_as_a_non_event():
    """Fail-closed: an unheard-of reason shrinks coverage toward the floor (suppression) instead of
    swelling the denominator, which is the 9-of-156 defect itself."""
    grid = _weekly(ASOF, 40)
    rows = ([(d, "declined", "brand_new_reason_v2") for d in grid[:20]]
            + [(d, "fired", None) for d in grid[20:]])
    _legs, sig, line = _answer(rows)
    assert sig["sweeps_evaluable"] == 20 and sig["sweeps_total"] == 40
    assert "on all 20" in line and "20 of the 40 attempted carried data" in line


def test_a_declined_row_with_no_reason_is_not_evaluable():
    """The writer forbids it (honest-decline invariant), so if one ever appears it is malformed -- and a
    malformed decline must not be read as a measured non-event."""
    grid = _weekly(ASOF, 20)
    rows = [(d, "declined", None) for d in grid[:10]] + [(d, "fired", None) for d in grid[10:]]
    _legs, sig, _line = _answer(rows)
    assert sig["sweeps_evaluable"] == 10 and sig["sweeps_total"] == 20


def test_sql_is_ansi_scalar_and_pins_provenance_and_both_pit_axes():
    sql = pr.baserate_backfill_sql("corn_cbot", "export_pace", kind="pace", asof=ASOF)
    assert "sweeps_evaluable" in sql and "sweeps_total" in sql        # BOTH counts ride the one row
    assert "first_evaluable" in sql and "last_evaluable" in sql
    assert "GROUP BY" not in sql.upper()                              # F8: a scalar always returns a row
    assert "'backfill_grid'" in sql and "'daily_sweep'" not in sql
    assert sql.count("substr(cast(") == 2                             # as_of_date AND written_at guards
    for r in sorted(pr.PR_NONEVENT_DECLINES):
        assert f"'{r}'" in sql
    for r in sorted(pr.PR_BLIND_DECLINES):
        assert f"'{r}'" not in sql, "the predicate is a POSITIVE non-event list (fail-closed)"
