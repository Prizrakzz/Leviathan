"""OUTCOMES_JOIN J4 + J6 -- the two SERVING legs, and the fences that decide what they may say.

Hermetic: no pg, no Athena, no LLM. The tape arrives through an injected `qfn(sql) -> rows` (the
test_cascade_pace_live_path convention) and the join itself is `numbers.outcomes`, which is pure.

WHAT EACH HALF IS FOR
---------------------
J4 (episode MAGNITUDE) makes a persona branch REACHABLE that has never fired: `_SYSTEM_EPISODES`
already specifies "the price move with its [N] handle, when an injected number row actually covers that
window", and nothing ever injected one. So the pins here are about the three ways that could go wrong
rather than about the arithmetic (which `test_outcomes_join.py` owns):

  * WINDOWS ARE READ LIVE. Episode spans move when the timeline artifact is rebuilt, so a leg that kept
    its own copy would price a window the model was never shown. Pinned by running the SAME leg twice
    against two different injected records and watching the priced span follow.
  * THE MEASURED WINDOW IS DAY-GRAIN, THE MATCHED LABEL IS MONTH-GRAIN (D-OJ-16). Expanding a
    `YYYY-MM` end token to month-end prices up to 30 days past the as-of; the month token is what
    `eval._line_targets` compares and must stay exactly what the prompt line showed.
  * THE CONTRACT SEGMENT MUST NOT LOOK LIKE A DATE (D-OJ-5). `eval._YM_RX` matches a bare year-month
    and `_line_targets` is two-tier with no fallback, so a leaked `contract: 2024-03` on a bullet would
    be scored as a MINTED window and would red `episode_magnitude_or_absence` and `min_episode_lines`
    together -- the exact pins J4 exists to turn green.

J6 (COT outcome pairing) is bounded by ratified D1 before anything else: a past-tense CONTEXT lane,
never an engine lane, never an outlook turn. Its pins are almost entirely about the fence, because the
number itself is the same number J4 computes and the only thing that makes it safe is WHERE it is
served from and WHEN it is reachable. The register half -- the addendum object and the forward-looking
rewrites that must still flag -- lives in tests/unit/test_register_corpus.py, which is the file nobody
may edit to make a change pass.

WHAT IS NOT PINNED HERE, AND WHY (read before adding a green test)
------------------------------------------------------------------
`gold_cot_outcomes` IS NOT REGISTERED YET -- the builder wave has not landed. So `_cot_outcome_read`
returns [] on a live registry and the J6 leg renders nothing. That is the fail-closed direction and it
is stated in the read's own docstring; the tests below stub that ONE seam to exercise the render, and
`test_the_cot_read_is_inert_until_the_card_is_registered` pins the un-stubbed behaviour so nobody reads
a stubbed green as a shipped feature.
"""
from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace

import pytest
from leviathan.graphrag import eval as ev
from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import outcomes as OC

ASOF = "2026-07-31"
SLUG = "corn_cbot"                       # coverage floor 2010-06-06, a delivery-cycle slug (H/K/N/U/Z)
EP_START, EP_END = "2021-03-05", "2021-06-25"
EP_SPAN = "2021-03..2021-06"

# The synthetic tape. Daily rows on four listed expiries; each contract stops printing on its own last
# print date, which is the ONLY input Option D's survival test has (expiry_date is NULL on all 455,421
# real rows, which is why contract life is inferable and nothing else).
_LIFE = {"2021-05": ("2021-02-15", "2021-05-10"),   # dies BEFORE the span end -> fails survival
         "2021-07": ("2021-02-15", "2021-07-12"),   # nearest expiry surviving t2 + 5 -> SELECTED
         "2021-09": ("2021-02-15", "2021-08-15"),
         "2021-12": ("2021-02-15", "2021-08-15")}
_PX0, _PX1 = 500.0, 575.0                 # -> exactly +15.0 % on the survivor


def _tape_rows(life=None, t0="2021-02-15", t1="2021-08-15"):
    """A daily curve, each expiry printing only between its own first and last print. Contract LIFE is
    the whole input Option D's survival test has: `expiry_date` is NULL on all 455,421 real tape rows,
    so a contract's life is inferable from `max(trade_date)` and from nothing else."""
    d, end = _dt.date.fromisoformat(t0), _dt.date.fromisoformat(t1)
    out = []
    while d <= end:
        iso = d.isoformat()
        for cm, (first, last) in (life or _LIFE).items():
            if not (first <= iso <= last):
                continue
            settle = (_PX0 if iso <= EP_START else _PX1) if cm == "2021-07" else 400.0
            out.append({"value": settle, "knowledge_date": iso, "contract_month": cm,
                        "unit": "US cents/bushel", "currency": "USD", "settle_kind": "settlement"})
        d += _dt.timedelta(days=1)
    return out


class _Tape:
    """A qfn that answers every read with the whole synthetic tape and RECORDS the SQL it was handed.

    Returning a superset is honest here: the join does its own endpoint and survivor selection, so the
    measurement is unaffected, while the recorded SQL is what lets a test assert the read SHAPE -- that
    the deep read named delivery months (the ~1 row/session scoping that keeps the 5,000-row series cap
    from binding), and that a declined window cost NO read at all."""

    def __init__(self, rows=None):
        self.rows = _tape_rows() if rows is None else rows
        self.sql: list[str] = []

    def __call__(self, sql):
        self.sql.append(sql)
        return list(self.rows)


def _sg(records):
    return SimpleNamespace(nodes=[], trace={"episodes_injected": records}, fired_regimes=[])


def _episode_rec(node=SLUG, start=EP_START, end=EP_END, span=EP_SPAN, n=7):
    """One `trace['episodes_injected']` record, exactly as answer._l2_blocks stamps it."""
    return {"node": node, "line": f"DATED EPISODES for {node} ...",
            "spans": [span], "windows": [{"start": start, "end": end, "span": span, "n": n}]}


def _run_episode_leg(records, *, qfn=None, asof=ASOF, calls=None):
    qfn = qfn or _Tape()
    calls = [] if calls is None else calls
    lines, trace = cq._episode_outcome_legs(_sg(records), qfn, asof, calls, len(calls))
    return lines, trace, calls, qfn


# ══ J4 -- the priced branch ═════════════════════════════════════════════════════════════════════════
def test_a_priced_episode_window_renders_one_handled_row():
    """Acceptance (i): the leg injects ONE [N] row per priced window, carrying the move, its unit, and
    the full scope tag -- including the delivery month it was measured on, which is the whole of
    D-OJ-5 (the survivor is the front contract in only 25.5-31.7% of anchors)."""
    lines, trace, calls, _ = _run_episode_leg([_episode_rec()])
    assert len(lines) == 1 and len(calls) == 1
    assert lines[0].startswith("- [N1] corn_cbot settle change across the episode window 2021-03..2021-06")
    assert "+15 %" in lines[0]
    assert lines[0].endswith("[series: corn_cbot; contract: 2021M07; table: FUTURES EOD]")
    assert [e["status"] for e in trace] == ["closed"]


def test_the_printed_magnitude_is_bound_as_shown():
    """The verifier is fail-CLOSED by default (`GRAPHRAG_VERIFY_NUM_MODE` is absent from serving), so a
    cited figure that is not in the call's `shown` list triggers number_mismatch and the repair path
    fires only in a narrow shape -- otherwise the whole SENTENCE is deleted. A priced bullet whose
    magnitude was never bound would therefore be deleted after the model wrote it correctly."""
    _lines, _trace, calls, _ = _run_episode_leg([_episode_rec()])
    assert calls[0]["shown"] == [15.0]
    assert calls[0]["rows"][0]["value"] == 15.0
    assert calls[0]["query"]["contract_month"] == "2021-07"
    # the [N] row is DATED at the endpoint, on a guard-column key, so the pinned-asof leakage backtest
    # has a day-grained stamp to read instead of the bare `year` a futures row otherwise carries
    assert calls[0]["rows"][0]["knowledge_date"] == calls[0]["rows"][0]["_provenance"]["date"]


def test_the_period_label_is_the_month_span_the_model_was_shown():
    """`query.period` is the MATCHING label (D-OJ-16): eval compares month tokens, so the citation and
    the prompt line must carry the same string the injected episode line did. The MEASURED window --
    day-grain -- rides the trace instead, where it can be audited without becoming a matchable token."""
    lines, trace, calls, _ = _run_episode_leg([_episode_rec()])
    assert calls[0]["query"]["period"] == EP_SPAN
    assert EP_SPAN in lines[0]
    assert (trace[0]["start"], trace[0]["end"]) == (EP_START, EP_END)


def test_the_measured_window_is_the_day_grain_end_not_the_month_end():
    """D-OJ-16's sharp edge. The span end is 2021-06-25; a month-expanded reading would measure to
    2021-06-30. The survivor prints daily here, so the two would give DIFFERENT endpoint dates -- and
    on a live window a month expansion prices up to 30 days past the as-of."""
    _lines, trace, _calls, _ = _run_episode_leg([_episode_rec()])
    assert trace[0]["endpoint_date"] == EP_END
    assert trace[0]["endpoint_date"] != "2021-06-30"


def test_the_contract_token_cannot_be_read_as_a_date():
    """D-OJ-5(a) / item 41b, and it is why the render form is '2021M07' and not '2021-07'. If a bullet
    ever echoed the tag, a bare year-month would have to EQUAL an endpoint of an injected span or
    `_line_targets` scores the bullet as a minted window -- redding both episode pins at once. The M
    form cannot match the regex at all, so the class is removed rather than bounded."""
    lines, _trace, _calls, _ = _run_episode_leg([_episode_rec()])
    tag = lines[0][lines[0].rindex("[series:"):]
    assert "contract: 2021M07" in tag
    assert ev._YM_RX.findall(tag) == []
    assert cq._contract_seg("2021-07") == "2021M07"


def test_a_bullet_copying_the_injected_span_still_matches_the_injected_episode():
    """Acceptance (ii), at the level a unit test can reach: both deck pins share the `all(_adj)`
    expression over `_line_targets`, so what matters is that a bullet written in the instructed shape
    -- span copied from the injected line, magnitude on its [N] handle -- resolves to the injected
    episode. A priced bullet must not lose the match the absence bullet already had."""
    injected = [{"node": SLUG, "span": EP_SPAN, "start": "2021-03", "end": "2021-06"}]
    bullet = ("- 2021-03..2021-06 -- Brazilian frost window: the report restates the damage [E2], and "
              "across that window the settle change on the delivery month the row names was [N1].")
    assert ev._line_targets(bullet, injected) == {0}


# ══ J4 -- the declines, which are the normal case ═══════════════════════════════════════════════════
def test_a_driver_node_declines_without_a_read():
    """Acceptance (iii) / item 68. `coverage_start_for` RAISES on an unmapped slug and never returns a
    permissive default, so a driver node must be turned away at the seam -- with the absence phrase the
    persona already specifies -- rather than reaching the join as an error."""
    lines, trace, calls, qfn = _run_episode_leg([_episode_rec(node="drivers/african_swine_fever")])
    assert lines == [] and calls == []
    assert qfn.sql == []                                          # and it cost nothing
    assert trace[0]["reason"] == cq.EP_DECLINE_UNRESOLVED_NODE


def test_a_multi_year_span_declines_on_contract_life_without_a_read():
    """Item 69: contract life is 396-587 sessions and the maximum measured forward tenor is 3.96y, so a
    span longer than that has NO single contract to measure on. The decline is arithmetic, so it costs
    no read -- and it is the shape the persona already calls the normal outcome."""
    rec = _episode_rec(start="2015-01-05", end="2021-06-25", span="2015-01..2021-06")
    lines, trace, calls, qfn = _run_episode_leg([rec])
    assert lines == [] and calls == [] and qfn.sql == []
    assert trace[0]["reason"] == cq.EP_DECLINE_SPAN_TOO_LONG


def test_a_window_below_the_coverage_floor_declines_without_a_read():
    """The backward clamp is reused, never re-derived: `futures_eod_contracts.covers` returns
    serve|legacy|straddle and a pre-floor window is `legacy`. corn_cbot's floor is 2010-06-06."""
    rec = _episode_rec(start="2004-03-05", end="2004-06-25", span="2004-03..2004-06")
    lines, trace, calls, qfn = _run_episode_leg([rec])
    assert lines == [] and calls == [] and qfn.sql == []
    assert trace[0]["reason"] == OC.DECLINE_PRE_COVERAGE


def test_a_window_straddling_the_floor_declines_rather_than_splicing():
    """A straddle DECLINES by ratified design -- silently splicing the legacy continuous card onto the
    per-expiry tape is the failure the floor exists to prevent."""
    rec = _episode_rec(start="2009-01-05", end="2011-06-25", span="2009-01..2011-06")
    _lines, trace, calls, qfn = _run_episode_leg([rec])
    assert calls == [] and qfn.sql == []
    assert trace[0]["reason"] == OC.DECLINE_COVERAGE_STRADDLE


def test_a_window_inside_the_survival_margin_is_PENDING_not_a_number():
    """THE CLAMP, and `survive_days` is part of the BOUNDARY rather than only of the selection: Option D
    picks the contract by asking whether it still prints five sessions past the endpoint, so for any
    as-of inside [t2+1, t2+survive] the selection -- and therefore px0, px1 and the whole move -- would
    have been made with tape the reader does not have. Pending renders NO magnitude and costs no read."""
    rec = _episode_rec(start="2021-03-05", end="2021-06-25", span=EP_SPAN)
    lines, trace, calls, qfn = _run_episode_leg([rec], asof="2021-06-28")
    assert lines == [] and calls == [] and qfn.sql == []
    assert trace[0]["status"] == "pending"
    assert trace[0]["readable_on"] == "2021-06-30"                # t2 + survive_days, stated


def test_the_slug_tape_edge_and_not_a_global_one_decides_pending():
    """Item 47, the single most likely place for this join to be implemented wrong. With the slug's own
    tape stopping four days after the span end, the horizon has NOT closed for THIS slug however much
    tape other slugs carry -- and the row must come back pending rather than measured."""
    short = [r for r in _tape_rows() if r["knowledge_date"] <= "2021-06-29"]
    lines, trace, _calls, _ = _run_episode_leg([_episode_rec()], qfn=_Tape(short))
    assert lines == []
    assert trace[0]["status"] == "pending"


class _ScopedTape:
    """A qfn that HONOURS the compiled window and the delivery-month filter, which the superset `_Tape`
    deliberately does not. The distinction is the whole subject of the two tests below: the deep read is
    delivery-month-SCOPED, so an edge measured from the frame it returns is the edge of THOSE MONTHS and
    not of the slug."""

    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def __call__(self, sql):
        import re
        self.sql.append(sql)
        lo = max(re.findall(r">= '(\d{4}-\d\d-\d\d)'", sql) or ["0000-00-00"])
        hi = min(re.findall(r"<= '(\d{4}-\d\d-\d\d)'", sql) or ["9999-99-99"])
        m = re.search(r"contract_month IN \(([^)]*)\)", sql)
        months = {s.strip().strip("'") for s in m.group(1).split(",")} if m else None
        return [r for r in self.rows
                if lo <= r["knowledge_date"] <= hi
                and (months is None or r["contract_month"] in months)]


# The candidates all stop printing INSIDE the survival margin while the slug's tape runs on through a
# farther expiry the candidate bound never asks for -- the exact shape that makes a month-scoped edge
# say "pending" about a slug whose tape is fine.
_SCOPED_LIFE = {"2021-05": ("2021-02-15", "2021-05-10"),
                "2021-07": ("2021-02-15", "2021-06-28"),
                "2021-09": ("2021-02-15", "2021-06-29"),
                "2021-12": ("2021-02-15", "2021-06-29"),
                "2022-03": ("2021-02-15", "2021-08-15")}    # never a candidate: only 3 are carried


def test_a_month_scoped_edge_never_gets_to_call_a_coverage_fact_a_timing_one():
    """The per-slug half of the clamp is measured from the FETCHED frame, and that frame is scoped to the
    <=3 candidate delivery months. If every candidate's last print falls inside `t2 + survive_days` while
    the SLUG's tape runs on, the frame-derived edge yields PENDING -- a TIMING verdict -- for what is
    actually `no_spanning_contract`, a COVERAGE fact. The dry run has already cleared the as-of half, so
    a pending verdict here can come from the scoped edge and nowhere else; the leg therefore measures the
    slug's real edge with ONE tiny unscoped read ([t2, t2+survive+lookback]) and asks again."""
    qfn = _ScopedTape(_tape_rows(life=_SCOPED_LIFE))
    lines, trace, calls, _ = _run_episode_leg([_episode_rec()], qfn=qfn)
    assert lines == [] and calls == []
    assert trace[0]["status"] == "declined"
    assert trace[0]["reason"] == OC.DECLINE_NO_SPANNING_CONTRACT      # not "pending"
    assert trace[0]["slug_tape_edge"] == "2021-07-14"                 # measured UNSCOPED, past t2 + 5
    assert len(qfn.sql) == 3 and "contract_month IN" not in qfn.sql[2]


def test_the_second_look_is_lazy_and_a_genuinely_short_tape_stays_pending():
    """The extra read fires ONLY in the ambiguous branch, and it never argues a real pending away: with
    the slug's own tape stopping inside the margin, the unscoped edge agrees with the scoped one and the
    verdict stands."""
    ok = _ScopedTape(_tape_rows())
    _l, _t, _c, _q = _run_episode_leg([_episode_rec()], qfn=ok)
    assert len(ok.sql) == 2                                          # priced window: no second look
    short = _ScopedTape([r for r in _tape_rows(life=_SCOPED_LIFE) if r["knowledge_date"] <= "2021-06-29"])
    _lines, trace, _calls, _ = _run_episode_leg([_episode_rec()], qfn=short)
    assert trace[0]["status"] == "pending"
    assert trace[0]["slug_tape_edge"] == "2021-06-29"     # the UNSCOPED edge agrees: t2 + 5 is not there


def test_a_single_visible_date_episode_never_renders_plus_zero_percent():
    """`timeline.episodes_for` builds `start, end = vis[0], vis[-1]` from the AS-OF-CLAMPED visible prop
    dates, so ONE visible date gives `start == end` -- and the as-of clamp manufactures that for recent
    episodes. Both endpoints then land on the same session: px1 IS px0, no session elapsed, and the leg
    rejected only `move_pct is None`, so it rendered `... 2021-06..2021-06 ...: +0 %` -- a fabricated
    magnitude on a window nothing happened across."""
    rec = _episode_rec(start="2021-06-25", end="2021-06-25", span="2021-06..2021-06")
    lines, trace, calls, _qfn = _run_episode_leg([rec])
    assert lines == [] and calls == []
    assert trace[0]["status"] == "declined"
    assert trace[0]["reason"] == OC.DECLINE_NO_ENDPOINT_SESSION


def test_no_surviving_contract_declines_rather_than_splicing_a_second_one():
    """Option D's whole claim is that the splice is STRUCTURALLY zero -- one contract, two endpoints. If
    no contract printing at the anchor survives the window, the answer is a decline, never two contracts
    stitched together: a roll-crossing artifact runs 1.0-2.6% of price at the median against realized
    moves of 4-12%, i.e. 15-60% of the signal being measured.

    THE TAPE HERE RUNS WELL PAST THE WINDOW -- only the CONTRACTS are short. That separates this decline
    from the per-slug clamp below, which is a different refusal with a different meaning."""
    life = {"2021-05": ("2021-02-15", "2021-05-10"),      # dies before the span end
            "2021-07": ("2021-02-15", "2021-06-20"),      # dies inside the survival margin
            "2021-09": ("2021-07-01", "2021-08-15")}      # never prints at the anchor
    lines, trace, calls, _ = _run_episode_leg([_episode_rec()], qfn=_Tape(_tape_rows(life)))
    assert lines == [] and calls == []
    assert trace[0]["status"] == "declined"
    assert trace[0]["reason"] == OC.DECLINE_NO_SPANNING_CONTRACT


def test_the_per_turn_budget_declines_the_overflow_visibly():
    """timeline.MAX_PER_NODE is 4 and a walk grounds several nodes, so an unbudgeted leg fans tens of
    reads onto the serve path. The overflow is RECORDED as a decline rather than dropped -- a window
    that was never asked about must not look like a window that had no answer.

    The budget is spent on windows that reach a READ, including ones that then decline for want of an
    anchor session; the free declines above (unresolved node, span too long, coverage floor, clamp) cost
    nothing and are deliberately not counted against it."""
    recs = [_episode_rec(span=f"2021-03..2021-06", start=f"2021-03-0{i}") for i in range(1, 5)]
    lines, trace, _calls, _ = _run_episode_leg(recs)
    assert len(lines) == cq.EPISODE_OUTCOME_MAX_WINDOWS
    assert [e["reason"] for e in trace][-1] == cq.EP_DECLINE_BUDGET


def test_a_saturated_read_declines_because_series_truncation_eats_the_ENDPOINT():
    """J3b, applied here. `agg='series'` compiles `ORDER BY <chronological ASC> ... LIMIT n`, so a read
    at the cap has lost its NEWEST rows -- which is exactly the endpoint half of every move. Measuring
    across that hole would produce a confident number over a window the read did not cover."""
    class _Sat(_Tape):
        def __call__(self, sql):
            self.sql.append(sql)
            return list(self.rows) * (cq.EPISODE_TAPE_ROW_CAP // max(1, len(self.rows)) + 1)

    lines, trace, calls, _ = _run_episode_leg([_episode_rec()], qfn=_Sat())
    assert lines == [] and calls == []
    assert trace[0]["reason"] == cq.EP_DECLINE_READ_TRUNCATED


# ══ J4 -- the artifact-wave interlock ═══════════════════════════════════════════════════════════════
def test_no_window_is_baked_anywhere():
    """Acceptance (iv). Episode windows MOVE when the timeline artifact is rebuilt, so the leg reads
    them live from `trace['episodes_injected']` every turn. Run the same leg against a SHIFTED record
    and the priced span follows it -- there is nothing to go stale, which is what makes deck pins that
    assert SHAPE (a magnitude-or-absence phrase) correct and a pin naming a literal span wrong."""
    a_lines, _a, _ac, _aq = _run_episode_leg([_episode_rec()])
    shifted = _episode_rec(start="2021-04-05", end="2021-06-10", span="2021-04..2021-06")
    b_lines, b_trace, _bc, _bq = _run_episode_leg([shifted])
    assert "2021-03..2021-06" in a_lines[0]
    assert "2021-04..2021-06" in b_lines[0] and "2021-03..2021-06" not in b_lines[0]
    assert (b_trace[0]["start"], b_trace[0]["end"]) == ("2021-04-05", "2021-06-10")


def test_the_deep_read_is_delivery_month_scoped():
    """Item 40b / J1.39: the reason the 5,000-row cap does not bind is that the deep read is scoped to a
    few delivery months (~1 row/session/expiry). An unscoped curve read is 3.7-12.9 rows/session (max
    19 on soymeal) and a multi-year window WOULD truncate silently."""
    _lines, _trace, _calls, qfn = _run_episode_leg([_episode_rec()])
    assert len(qfn.sql) == 2                                      # the anchor curve, then the deep read
    assert "2021-07" in qfn.sql[1] and "contract_month" in qfn.sql[1]
    assert "2021-05" not in qfn.sql[1]                            # expiries before the span end are not asked for


def test_no_episodes_no_leg():
    """A turn with no injected episodes has nothing to price, and must not read, cite or trace."""
    lines, trace, calls, qfn = _run_episode_leg([])
    assert (lines, trace, calls, qfn.sql) == ([], [], [], [])


def test_quantify_is_byte_identical_with_the_flag_off():
    """Item 108's measurement, and the omit-when-off kwarg idiom is what buys it. The flag-off call
    injects no row, renders no block and writes no trace key -- so the J-rows can ride an A/B whose only
    intended variable is something else."""
    sg_off, sg_on = _sg([_episode_rec()]), _sg([_episode_rec()])
    calls_off: list = []
    block_off, _t, _r = cq.quantify(sg_off, None, qfn=_Tape(), asof=ASOF, near=None,
                                    extra_number_calls=calls_off)
    assert block_off is None and calls_off == []
    assert "quantify_episode_outcomes" not in sg_off.trace
    calls_on: list = []
    block_on, _t2, _r2 = cq.quantify(sg_on, None, qfn=_Tape(), asof=ASOF, near=None,
                                     extra_number_calls=calls_on, episode_outcomes=True)
    assert block_on and "[N1] corn_cbot settle change" in block_on
    assert len(calls_on) == 1 and sg_on.trace["quantify_episode_outcomes"]


def test_the_leg_survives_a_turn_with_no_cascade_groups():
    """The modal episodes turn is a thin walk: dated episodes, no mapped silver ref, so `quantify` takes
    its no-groups early return. The episode leg owns no groups of its own, so tying it to that return
    would kill it on exactly the turns it serves."""
    sg = _sg([_episode_rec()])
    calls: list = []
    block, trace, rtrace = cq.quantify(sg, None, qfn=_Tape(), asof=ASOF, near=None,
                                       extra_number_calls=calls, episode_outcomes=True)
    assert block and block.startswith(cq._BLOCK_HEADER)
    assert (trace, rtrace) == ([], [])
    assert len(calls) == 1


def test_a_broken_join_degrades_to_the_absence_branch(monkeypatch):
    """R6. The episodes persona treats a missing magnitude as the normal case, so an outcomes failure
    must land there -- never as a 500, and never as a turn with no answer."""
    monkeypatch.setattr(cq, "_episode_outcome_legs",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    sg = _sg([_episode_rec()])
    calls: list = []
    block, _t, _r = cq.quantify(sg, None, qfn=_Tape(), asof=ASOF, near=None,
                                extra_number_calls=calls, episode_outcomes=True)
    assert block is None and calls == []


# ══ J6 -- the COT outcome pairing, CONTEXT LANE ONLY ════════════════════════════════════════════════
_COT_ROW = {"table": "silver_cot", "metric": "mm_net", "agg": "latest", "period_type": "date",
            "leg_mode": "current", "country_rule": "none", "native_unit": "contracts",
            "narrate_unit": "contracts", "scale": 1}


def _cot_node(contract=SLUG, ref="cot_mm_positioning", nid="managed_money_positioning"):
    return SimpleNamespace(contract=contract, id=nid, prior={"silver_ref": ref, "region": "US"},
                           evidence=[])


def _cot_qfn(sql):
    """The C1 fixture's shape: agg=latest -> the freshest weekly print, dated by its report date."""
    return [{"value": "118432", "knowledge_date": "2024-03-12"}]


def _outcome_row(h, pct):
    """One `gold_cot_outcomes` row as the card will surface it -- period = the EVENT date, plus the
    horizon and the delivery month the move was measured on."""
    return {"value": pct, "period": "2024-03-12", "horizon_days": h, "unit": "%",
            "knowledge_date": "2024-06-10", "contract_month_used": "2024-07", "status": "closed"}


def _run_cot(monkeypatch, *, outlook=False, reader=None, node=None, cot_outcomes=True):
    monkeypatch.setattr(cq, "load_map", lambda: {"cot_mm_positioning": _COT_ROW})
    seen: list = []

    def _read(qfn, *, slug, event_date, horizon_days, asof):
        seen.append((slug, event_date, horizon_days))
        return (reader or (lambda h: []))(horizon_days)

    monkeypatch.setattr(cq, "_cot_outcome_read", _read)
    sg = SimpleNamespace(nodes=[node or _cot_node()], trace={}, fired_regimes=[])
    calls: list = []
    kw = {"cot_outcomes": True} if cot_outcomes else {}
    block, _t, _r = cq.quantify(sg, None, qfn=_cot_qfn, asof=ASOF, near=None,
                                extra_number_calls=calls, pace=True, outlook=outlook, **kw)
    return block, sg.trace, calls, seen


def test_the_pairing_renders_past_tense_on_a_fenced_turn(monkeypatch):
    """Acceptance (i): both clauses are past-tense record. The line states a LEVEL of record and a MOVE
    of record joined by nothing -- "the regime made +12%" is the forbidden shape, and so is every
    quieter form of it, because each turns a coincidence of dates into a performance claim."""
    block, trace, calls, seen = _run_cot(monkeypatch,
                                         reader=lambda h: [_outcome_row(h, 8.24)] if h == 90 else [])
    assert "settle change across the 90 days after the 2024-03-12 positioning report date" in block
    assert "+8.24 %" in block
    assert cq.COT_OUTCOME_ADDENDUM in block
    assert [c for c in calls if c["query"]["table"] == cq.COT_OUTCOME_TABLE]
    assert [e["status"] for e in trace["quantify_cot_outcomes"] if e["horizon_days"] == 90] == ["closed"]
    assert seen == [(SLUG, "2024-03-12", h) for h in OC.HORIZON_DAYS]


def test_the_rendered_pairing_states_its_own_per_slug_start_date(monkeypatch):
    """Acceptance (v) / item 89. The two series start in different places -- MGEX positioning runs from
    2014-03-25 while its tape starts 2025-09-09 -- so a reader shown a number and no floor cannot tell
    which part of the record was even measurable."""
    block, _trace, _calls, _seen = _run_cot(
        monkeypatch, reader=lambda h: [_outcome_row(h, 8.24)] if h == 90 else [])
    assert "record begins 2010-06-06" in block


def test_the_pairing_adds_zero_raw_flow_register(monkeypatch):
    """Acceptance (i), the RAW bound D1 asked for. `_count_banned_flow` is a PRE-sanitize counter, so a
    rendered-cleanliness gate cannot observe it -- the leg's own lines and its addendum must add nothing
    to it on a fenced turn."""
    from leviathan.graphrag import answer as an
    block, _trace, _calls, _seen = _run_cot(
        monkeypatch, reader=lambda h: [_outcome_row(h, 8.24)] if h == 90 else [])
    assert an._count_banned_flow({"tldr": block, "mechanism": ""}) == 0
    assert an._count_banned_valuation({"tldr": block, "mechanism": ""}) == 0
    assert an._count_banned_exec({"tldr": block, "mechanism": ""}) == 0
    assert reg.exec_leaks(block) == []


def test_an_outlook_turn_does_not_reach_the_ref_at_all(monkeypatch):
    """Acceptance (i-bis) / D-OJ-17 option (a). Under OUTLOOK, register.py places the flow and valuation
    fences inside `if not outlook:`, so a cited, arrow-free conditional-performance sentence returns
    False from `_is_banned_sentence` and ships as a setup. No phrasing rule inside a released fence is
    load-bearing, so the ref is held out of the lane entirely -- and the proof is that the read is never
    even attempted."""
    block, trace, calls, seen = _run_cot(monkeypatch, outlook=True,
                                         reader=lambda h: [_outcome_row(h, 8.24)])
    assert seen == []
    assert "quantify_cot_outcomes" not in trace
    assert [c for c in calls if c["query"]["table"] == cq.COT_OUTCOME_TABLE] == []
    assert block is None or cq.COT_OUTCOME_ADDENDUM not in block


def test_the_flag_off_call_is_byte_identical(monkeypatch):
    """The omit-when-off idiom again: no kwarg, no read, no line, no trace key."""
    block, trace, _calls, seen = _run_cot(monkeypatch, cot_outcomes=False,
                                          reader=lambda h: [_outcome_row(h, 8.24)])
    assert seen == [] and "quantify_cot_outcomes" not in trace
    assert block is None or cq.COT_OUTCOME_ADDENDUM not in block


def test_a_pre_coverage_mgex_anchor_declines_rather_than_returning_a_number(monkeypatch):
    """Acceptance (iv). MGEX COT history starts 2014-03-25 but its TAPE starts 2025-09-09, so `covers()`
    returns legacy/straddle for eleven years of it. Those anchors decline -- and they decline before the
    outcomes card is ever read, which is the fail-closed direction."""
    monkeypatch.setattr(cq, "_cot_qfn_unused", None, raising=False)

    def _mgex_qfn(sql):
        return [{"value": "1200", "knowledge_date": "2020-05-12"}]

    monkeypatch.setattr(cq, "load_map", lambda: {"cot_mm_positioning": _COT_ROW})
    seen: list = []
    monkeypatch.setattr(cq, "_cot_outcome_read",
                        lambda qfn, **kw: seen.append(kw) or [])
    sg = SimpleNamespace(nodes=[_cot_node(contract="hard_red_spring_wheat_mgex")], trace={},
                         fired_regimes=[])
    calls: list = []
    block, _t, _r = cq.quantify(sg, None, qfn=_mgex_qfn, asof=ASOF, near=None,
                                extra_number_calls=calls, pace=True, cot_outcomes=True)
    assert seen == []
    reasons = {e["reason"] for e in sg.trace["quantify_cot_outcomes"]}
    assert reasons <= {OC.DECLINE_PRE_COVERAGE, OC.DECLINE_COVERAGE_STRADDLE}
    assert block is None or cq.COT_OUTCOME_ADDENDUM not in block


def test_an_honest_positioning_absence_earns_no_pairing(monkeypatch):
    """The E-STREAK-NODATA idiom: the leg runs only where a positioning CONTEXT leg actually rendered,
    so it can never introduce positioning to a turn that had none."""
    seen: list = []
    monkeypatch.setattr(cq, "load_map", lambda: {"cot_mm_positioning": _COT_ROW})
    monkeypatch.setattr(cq, "_cot_outcome_read", lambda qfn, **kw: seen.append(kw) or [])
    sg = SimpleNamespace(nodes=[_cot_node()], trace={}, fired_regimes=[])
    calls: list = []
    block, _t, _r = cq.quantify(sg, None, qfn=lambda sql: [], asof=ASOF, near=None,
                                extra_number_calls=calls, pace=True, cot_outcomes=True)
    assert seen == [] and calls == []
    assert block is None or cq.COT_OUTCOME_ADDENDUM not in block


# ══ J6 -- the fence itself ══════════════════════════════════════════════════════════════════════════
def test_the_new_card_is_inside_the_positioning_fence_on_both_sides():
    """Acceptance (ii-bis) / D-OJ-18. Every leg of this fence keys on the TABLE ID, so a
    positioning-derived number served from a table OUTSIDE the set would satisfy R9's letter while
    vacating the context-shape rule, the never-a-chain-hop ban and the never-a-relative-value-leg ban at
    once. Both constants, because a fence that lands half-on is not a fence."""
    from leviathan.graphrag import config_check as cc
    assert cq.COT_OUTCOME_TABLE in cq.POSITIONING_TABLES
    assert cq.COT_OUTCOME_TABLE in cc.POSITIONING_TABLES
    assert frozenset(cc.POSITIONING_TABLES) == cq.POSITIONING_TABLES


def test_removing_the_id_from_one_side_only_fails_the_build(monkeypatch):
    """The cheapest available proof the fence is gripping: the drift pin reports it, by name, the moment
    the two constants disagree."""
    from leviathan.graphrag import config_check as cc
    monkeypatch.setattr(cc, "POSITIONING_TABLES", ("silver_cot",))
    errs = cc._check_positioning_lane()
    assert any("R9 drift" in e and cq.COT_OUTCOME_TABLE in e for e in errs)


def test_the_new_cards_metrics_are_unit_whitelisted_and_name_banned():
    """D-OJ-18's third leg. R7b bars a "% move over N days" unit from the silver_cot card and is right
    to, which is why this is a separate card -- so the unit is admitted BY NAME here, and a
    forecast-shaped metric name still fails the build. An admitted unit that was never written down is
    the same fail-open in a different costume."""
    from leviathan.graphrag import config_check as cc
    from leviathan.graphrag import register as _reg
    from leviathan.graphrag.numbers import stats as _st

    def _card(**metrics):
        return SimpleNamespace(metrics={k: SimpleNamespace(unit=u, desc=d)
                                        for k, (u, d) in metrics.items()})

    assert cc._check_cot_outcome_metrics(None, _reg, _st) == []          # vacuous until registered
    assert cc._check_cot_outcome_metrics(
        _card(move_pct=("%", "realized settle change over the horizon")), _reg, _st) == []
    bad = cc._check_cot_outcome_metrics(
        _card(forecast_move=("%", "x"), move_abs=("US cents/bushel", "y")), _reg, _st)
    assert any("forward-looking" in e for e in bad)
    assert any("admitted set" in e for e in bad)


def test_the_cot_read_is_inert_until_the_card_is_registered():
    """The precondition, stated as a test so a stubbed green above is never read as a shipped feature.
    `gold_cot_outcomes` is not in the registry until the builder wave lands, so `fetch_window` returns
    an error record and this returns [] -- the leg is inert, not wrong."""
    from leviathan.graphrag.numbers.registry import load_registry
    assert cq.COT_OUTCOME_TABLE not in load_registry().tables
    assert cq._cot_outcome_read(lambda sql: [], slug=SLUG, event_date="2024-03-12",
                                horizon_days=90, asof=ASOF) == []


@pytest.mark.parametrize("row", [
    {"value": 8.2, "period": "2024-03-11", "horizon_days": 90},        # wrong event date
    {"value": 8.2, "period": "2024-03-12", "horizon_days": 30},        # wrong horizon
    {"value": 8.2, "period": "2024-03-12"},                            # card does not surface the horizon
])
def test_the_cot_read_keeps_only_rows_that_name_this_event_and_this_horizon(row):
    """Fail-closed in all three directions. The last case matters most: three horizons collapsed into
    one line would be a distribution wearing a single number's clothes."""
    assert cq._cot_outcome_read(lambda sql: [row], slug=SLUG, event_date="2024-03-12",
                                horizon_days=90, asof=ASOF) == []


def test_the_cot_read_is_census_shaped_because_the_compiled_guard_is_not_enough(monkeypatch):
    """D-OJ-14 holds only when the reader's asof EQUALS the build's. The builder writes `pending` only
    for horizons open at ITS asof, so at an earlier pinned asof a row it wrote `closed` is dropped by the
    compiled guard and NO pending row exists in its place -- and an empty guarded read is `record_silent`,
    i.e. the COVERAGE-GAP string, for what is purely a TIMING fact. That is the judged-30 RCA inversion
    arriving through the guard. So this read never lets the guard's silence speak: it asks the clamp
    first, and re-clamps every row it gets back."""
    seen: list = []

    def _fw(qfn, **kw):
        seen.append(kw)
        return {"status": "ok", "rows": [dict(_outcome_row(90, 8.2), tape_edge_date="2024-06-12")]}

    monkeypatch.setattr(cq, "fetch_window", _fw)
    # (1) THE CLAMP IS ASKED FIRST: inside the horizon there is nothing to read, and no read is issued.
    assert cq._cot_outcome_read(lambda sql: [], slug=SLUG, event_date="2024-03-12",
                                horizon_days=90, asof="2024-04-01") == []
    assert seen == []
    # (2) A ROW THE BUILD CALLED CLOSED IS RE-CLAMPED at the reader's asof from the row's OWN stored tape
    # edge -- the per-slug term the compiled guard cannot see. Close + survive = 2024-06-15, edge
    # 2024-06-12: pending, no move, and no delivery month either (the selection was future-conditioned).
    rows = cq._cot_outcome_read(lambda sql: [], slug=SLUG, event_date="2024-03-12",
                                horizon_days=90, asof=ASOF)
    assert len(seen) == 1 and len(rows) == 1
    assert rows[0]["status"] == OC.STATUS_PENDING
    assert rows[0]["contract_month_used"] is None
    # ... so the leg's closed-only filter drops it: a TIMING answer, never a stale magnitude
    assert next((r for r in rows if str(r.get("status") or "closed") == OC.STATUS_CLOSED), None) is None
    # (3) a row whose horizon really has closed at this asof passes through untouched
    seen.clear()
    monkeypatch.setattr(cq, "fetch_window",
                        lambda qfn, **kw: {"status": "ok",
                                           "rows": [dict(_outcome_row(90, 8.2),
                                                         tape_edge_date="2026-07-27")]})
    ok = cq._cot_outcome_read(lambda sql: [], slug=SLUG, event_date="2024-03-12",
                              horizon_days=90, asof=ASOF)
    assert len(ok) == 1 and ok[0]["status"] == OC.STATUS_CLOSED and ok[0]["value"] == 8.2


def test_the_performance_framing_is_not_caught_by_any_register_detector():
    """SKEPTIC F13, PINNED AS A FACT RATHER THAN ARGUED. "Descriptive, not predictive" is PROSE, and
    plan item 45 forbids resting a fence on prose.

    The sentence below is the exact shape J6 makes available -- a conditional PERFORMANCE statistic
    read as a setup -- and every register detector in the codebase returns zero on it. It carries no
    flow idiom, no valuation idiom, no execution idiom and no unbacked level; on an OUTLOOK turn it also
    carries a citation and no derivation arrow, so `_is_banned_sentence` returns False and it ships
    verbatim.

    So this test does not assert a fence. It asserts that NO LEXICAL FENCE EXISTS HERE, which is why
    the three that do exist are structural and must all stay: (i) the ref is held out of outlook turns
    entirely (D-OJ-17), (ii) the card sits inside POSITIONING_TABLES so its shape is gated at runtime as
    well as at lint (D-OJ-18), (iii) the card's metrics pass the unit whitelist and the banned-name
    check. Delete any one of them and this sentence is one adjective from advice.

    ONE CORRECTION TO THE PLAN'S OWN EXAMPLE, measured here rather than assumed. Item 90b's sample
    sentence ("across the 47 times ... rose a median 8.2% over the next 90 days [N7]") IS refused under
    OUTLOOK -- but by the DERIVATION GATE, for carrying bare numerals 47 and 90, not by anything that
    understands it as a performance claim. Drop the incidental numerals and the same claim ships. The
    finding survives its example: the fence that fires is about NUMERALS, and the claim's shape is
    invisible to every detector in the module."""
    from leviathan.graphrag import answer as an
    claim = ("Across prior instances where managed-money net length exceeded its z threshold, "
             "front-month corn rose by 8.2431% [N7] over the following quarter.")
    assert an._count_banned_flow({"tldr": claim, "mechanism": ""}) == 0
    assert an._count_banned_valuation({"tldr": claim, "mechanism": ""}) == 0
    assert an._count_banned_exec({"tldr": claim, "mechanism": ""}) == 0
    assert reg.count_flow_words(claim) == 0 and reg.exec_leaks(claim) == []
    assert reg.unbacked_levels(claim) == []
    assert not reg._is_banned_sentence(claim, market_register=reg.OUTLOOK)
    # the plan's own example, and WHY it is refused -- numerals, not framing
    plan_example = ("Across the 47 times managed-money net length exceeded +1.5z, front-month corn "
                    "rose a median 8.2% over the next 90 days [N7].")
    assert reg._is_banned_sentence(plan_example, market_register=reg.OUTLOOK)
    assert reg._level_tokens(plan_example) == ["47", "90"]
    assert reg.count_flow_words(plan_example) == 0


# ══ the prompt half of D-OJ-5, and the CASE 3 rewrite ═══════════════════════════════════════════════
def test_the_scope_paragraph_describes_the_tag_the_rows_actually_carry():
    """D-OJ-5(b) / skeptic F17. The render grew a fourth segment; the SYSTEM PROMPT enumerated three.
    A prompt that under-describes the tag the rows carry is the mirror image of one describing a tag
    they do not -- and the paragraph is what trains the reader that the tag names EXACTLY what the
    figure was measured on, so it is where the delivery month has to be introduced."""
    from leviathan.graphrag import answer as an
    sysprompt = an._SYSTEM_CASCADE
    assert "'[series: ...; country: ...; table: ...]'" in sysprompt
    assert "fourth 'contract: ...' segment" in sysprompt
    assert "2024M03" in sysprompt and "never as '2024-03'" in sysprompt
    # and the docstring on the renderer documents the same four segments
    assert "contract: <DELIVERY MONTH>" in cq._series_tag.__doc__


def test_case_three_no_longer_points_at_the_marketing_year_farm_price():
    """Item 66(ii). The old worked example was the SEAM-B WASDE marketing-year pair -- at most ONE pair
    per turn, on ONE derived focus window, declined outright on a market-price or non-US slug -- i.e.
    an example of the one priced path that almost never covers an episode. The priced path is now an
    episode-window row, and the example is the shape the engine actually injects."""
    from leviathan.graphrag import answer as an
    assert "season-average farm price across those marketing years" not in an._SYSTEM_EPISODES
    assert "across that window the settle change on the delivery month the row names" in an._SYSTEM_EPISODES
    # the absence branch survives the change -- it is still the NORMAL case, now for a measured reason
    assert "THE ABSENCE IS THE NORMAL CASE" in an._SYSTEM_EPISODES
    assert "no price record for this window" in an._SYSTEM_EPISODES
    # ... and the two slots stay two records, never cause and effect
    assert "TWO SEPARATE RECORDS placed side by side" in an._SYSTEM_EPISODES


# ══ S1 -- the canary reaches the J4 tape, END TO END through quantify ═══════════════════════════════
#
# WHY THIS LIVES HERE AND NOT ONLY IN THE PINS FILE. The J4 tape is the one read in cascade.py that is
# UNCONDITIONALLY futures -- `_TAPE_TABLE` is silver_futures_eod and `agg` is the literal 'series', so
# `_newest_first_applies` is True the instant the canary is. The pins file proves each LINK of the chain
# in isolation; what this fixture can prove that a link test cannot is that a REAL priced window, with the
# whole leg running (dry run, curve read, candidate months, deep read, join), compiles all of its reads
# on the same side of the flip -- and still produces the same measurement.
#
# The second half is the one that would be easy to skip. `run()` re-sorts DESC rows back to ascending
# before any consumer sees them, so the flipped read must be MEASUREMENT-NEUTRAL here: same move, same
# survivor, same anchor. If it were not, the canary would be changing what an episode is worth rather than
# which end of an over-long window survives the row cap, and that is a different (unratified) change.


def _sql_flags(monkeypatch) -> list:
    """Record the canary every compile in this leg was actually handed, at the compiler itself."""
    from leviathan.graphrag.numbers import query as Q
    seen: list = []
    real = Q.build_sql

    def _spy(spec, ts=None, *, db=Q.ATHENA_DB, futures_newest_first=False):
        seen.append(futures_newest_first)
        return real(spec, ts, db=db, futures_newest_first=futures_newest_first)

    monkeypatch.setattr(Q, "build_sql", _spy)
    return seen


def test_quantify_carries_the_canary_into_every_tape_read(monkeypatch):
    """The J4 chain end to end: quantify -> _episode_leg_or_nothing -> _episode_outcome_legs ->
    _tape_read -> build_sql. EVERY compile on the turn carries the flag; a leg that flipped its deep read
    and not its curve read would select candidate delivery months off one ordering and measure on another."""
    seen = _sql_flags(monkeypatch)
    calls: list = []
    block, _t, _r = cq.quantify(_sg([_episode_rec()]), None, qfn=_Tape(), asof=ASOF, near=None,
                                extra_number_calls=calls, episode_outcomes=True,
                                futures_newest_first=True)
    assert block, "the fixture stopped pricing the window -- the flag assertion would be vacuous"
    assert len(seen) >= 2, seen                    # curve read + deep read at minimum
    assert all(seen), "a tape read compiled on the pre-wave ordering while its sibling flipped"


def test_the_same_turn_with_the_canary_OFF_compiles_the_pre_wave_ordering(monkeypatch):
    """The rollback half, on the same fixture: omit the kwarg and every compile is the ASC read."""
    seen = _sql_flags(monkeypatch)
    calls: list = []
    block, _t, _r = cq.quantify(_sg([_episode_rec()]), None, qfn=_Tape(), asof=ASOF, near=None,
                                extra_number_calls=calls, episode_outcomes=True)
    assert block and seen and not any(seen)


def test_the_flip_is_MEASUREMENT_NEUTRAL_on_a_priced_window():
    """`run()` re-sorts the rows back to ascending before the frame is built, so flipping the read shape
    must not move the number. Same move, same survivor, same anchor, same endpoint -- byte for byte on
    the injected [N] row. If this ever diverges, the canary is no longer 'which end of the cap survives'."""
    off_calls: list = []
    on_calls: list = []
    off_lines, off_trace = cq._episode_outcome_legs(_sg([_episode_rec()]), _Tape(), ASOF, off_calls,
                                                    len(off_calls))
    on_lines, on_trace = cq._episode_outcome_legs(_sg([_episode_rec()]), _Tape(), ASOF, on_calls,
                                                  len(on_calls), futures_newest_first=True)
    assert off_lines == on_lines
    assert off_calls == on_calls
    assert [e["status"] for e in off_trace] == [e["status"] for e in on_trace] == ["closed"]
    # NON-VACUITY: the window really was priced, so "identical" is not two empty results agreeing.
    assert off_calls and off_calls[0]["shown"] == [15.0]
