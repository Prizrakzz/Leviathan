"""THE ANCHOR'S SB-T TAPE ROW -- STATE ENGINE DESIGN sec 6.2 / D19 / bar B19, sitting S1.

ONE read per anchor board: the dated front settle named by the SHIPPED roll rule, the four SAME-CONTRACT
session changes (1 / 5 / 21 / 63) and the level's percentile over the window that read fetched. Every
test here runs OFFLINE -- ``fixture_query_fn`` compiles the real SQL against canned rows -- because a bar
that can only be measured in-VPC is a bar nobody runs.

WHY THIS DECK EXISTS AT ALL: sec 11's S1 row lists "the SB-T read" and the first S1 cut shipped neither
the read nor a not-done line for it. ``feeders.board_map()`` carries no ``silver_futures_eod`` ref and
``series_state`` can only produce a row for a map ref, so there was no path to an anchor tape row.
"""
import datetime as _dt

import pytest
from leviathan.graphrag.state import __main__ as M
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state.rows import TAPE_STATUS_WITH_DETAIL, TAPE_STATUS_WORDS, status_word

#: A slug whose roll method is ``delivery_cycle`` -- the rule needs NO activity metric, so it selects
#: honestly on the settle-only card the store serves today (``futures_roll.roll_method_for``, measured:
#: the MATIF and MGEX slugs; every GLBX / ICE / DCE slug is front-by-open-interest or front-by-volume).
CYCLE_SLUG = "french_wheat_matif"
#: A slug whose rule reads OPEN INTEREST, which the served card does not carry -- the measured
#: ``front_decline`` of today's estate, and the reason that word is in the closed set.
OI_SLUG = "corn_cbot"


def _sessions(n, last="2026-09-04"):
    end = _dt.date.fromisoformat(last)
    return [(end - _dt.timedelta(days=k)).isoformat() for k in range(n)][::-1]


def _curve(sessions, expiries, base=250.0, roll_inputs=None):
    """A silver_futures_eod SERIES read's shape: one row per (session, expiry), self-identifying.
    ``knowledge_date`` is the alias ``_extras`` emits for this card -- it serves ``trade_date`` as BOTH
    its date and its knowledge column, so there is no ``data_date`` alias on any row of it.

    ``roll_inputs`` writes the rule's own metric columns onto every row: ``None`` leaves them off
    entirely (a card that never projected them), ``""`` serves them BLANK (the mirror's NULL shape) and
    a number serves it, falling with distance to delivery so the nearest listed month wins."""
    out = []
    for i, d in enumerate(sessions):
        for j, cm in enumerate(expiries):
            r = {"value": str(round(base + i * 0.5 + j * 2.0, 2)), "knowledge_date": d,
                 "contract_month": cm, "settle_kind": "official", "currency": "EUR", "unit": "EUR/t"}
            if roll_inputs is not None:
                r["open_interest"] = roll_inputs if roll_inputs == "" else 100000 - j * 5000
                r["volume"] = roll_inputs if roll_inputs == "" else 40000 - j * 2000
            out.append(r)
    return out


def test_the_tape_row_is_ONE_read_with_the_front_named_by_the_SHIPPED_rule():
    rows = _curve(_sessions(120), ["2026-12", "2027-03", "2027-05"])
    qfn = F.fixture_query_fn({"silver_futures_eod": rows})
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=qfn)
    assert t.status == "ok" and t.reads == 1
    assert len(qfn.calls) == 1, "D19: one mirror read per anchor board"
    assert t.roll_rule_version == "front_month_v2" and t.roll_method == "delivery_cycle"
    assert t.contract_month == "2026-12" and t.level_date == "2026-09-04"
    assert t.unit == "EUR/t" and t.currency == "EUR" and t.settle_kind == "official"


def test_the_four_changes_are_SAME_CONTRACT_and_name_their_windows_in_SESSIONS():
    """Same-contract is the whole point: a delta spanning a roll is a SPLICE, which is exactly the
    contamination ``levels_only`` fences on the continuous sibling card. The fixture ramps 0.5 per
    session on every expiry and 2.0 per expiry, so a change that had wandered onto a neighbouring
    delivery month could not produce these numbers."""
    rows = _curve(_sessions(120), ["2026-12", "2027-03", "2027-05"])
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert [c["window"] for c in t.changes] == ["1 session", "5 sessions", "21 sessions", "63 sessions"]
    assert [c["delta"] for c in t.changes] == [0.5, 2.5, 10.5, 31.5]
    assert all(c["declined"] is False for c in t.changes)
    assert all(c["to_date"] == "2026-09-04" for c in t.changes)
    assert F.TR.re_execute_all(t.derivation, t.inputs) == [], "every SB-T figure reproduces from its rows"


def test_the_percentile_ranks_the_level_INSIDE_THE_FETCHED_WINDOW_and_prints_that_window():
    """"the level at the {pct}th percentile of its fetched five-year window" (sec 6.2). The window is
    what the read FETCHED, never "full history" and never the contract's whole quoted life, and the row
    says so in sessions and dates so the rank can never claim a span it did not measure."""
    rows = _curve(_sessions(120), ["2026-12", "2027-03"])
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert t.percentile and t.percentile["declined"] is False and t.percentile["n"] == 120
    assert t.percentile["value"] > 99.0, "a monotone ramp puts the newest settle at the top of its window"
    assert t.window_note == "120 sessions on 2026-12, 2026-05-08 to 2026-09-04"
    assert t.coverage["n_obs"] == 120 and t.coverage["truncated"] is False


def test_a_thin_contract_declines_percentile_thin_and_changes_thin_BY_NAME():
    rows = _curve(_sessions(3), ["2026-12"])
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert t.percentile["declined"] is True
    assert status_word(t.status) in ("percentile_thin", "changes_thin")
    assert t.status.split(":", 1)[1] == "3"
    assert [c["declined"] for c in t.changes] == [False, True, True, True]


def test_the_tapeless_boards_decline_no_tape_slug_at_ZERO_reads():
    """Bar B19: the ten boards absent from ``PRICE_COVERAGE_START`` have no SB-T row and say so. A board
    with no per-contract tape never borrows a neighbour's and never falls back to the continuous card."""
    def _never(sql):
        raise AssertionError("a tape-less board must not spend a read")
    for slug in ("soybeans", "corn", "palm_olein_dce", "barley", "sorghum"):
        t = F.tape_state(slug, "2026-09-08", qfn=_never)
        assert t.status == "no_tape_slug" and t.reads == 0 and t.level is None


def test_an_asof_before_the_slugs_own_coverage_floor_declines_pre_coverage_at_ZERO_reads():
    def _never(sql):
        raise AssertionError("a pre-coverage as-of must not spend a read")
    t = F.tape_state(OI_SLUG, "2005-01-01", qfn=_never)
    assert t.status == "pre_coverage" and t.reads == 0
    assert t.coverage_start == "2010-06-06", "the floor is PRICE_COVERAGE_START's own, printed on the row"


def test_a_frame_whose_ROLL_INPUT_is_SERVED_BLANK_still_declines_front_decline():
    """THE RESIDUAL CASE after the projection landed, and it is the mirror's own shape: the read now
    PROJECTS ``open_interest`` / ``volume`` (``roll_inputs=True``), but a column served EMPTY is not an
    input the rule can read -- ``pgnumbers._stringify`` renders NULL as ``""`` -- so
    ``front_month_inputs_present`` refuses and ``select_front_expiry`` returns its own reasoned ``[]``.
    The board declines by name rather than falling through to the nearest listed expiry, which would be a
    DIFFERENT, unnamed rule wearing ``front_month_v2``'s name."""
    rows = _curve(_sessions(90), ["2026-12", "2027-03"], roll_inputs="")
    t = F.tape_state(OI_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert t.status == "front_decline" and t.reads == 1 and t.level is None
    assert t.coverage["n_obs"] == 180, "the read is still counted: the ledger sees what it spent"


def test_the_tape_read_is_SCOPED_capped_and_newest_first_and_carries_the_rules_own_input():
    spec = F.tape_spec(CYCLE_SLUG, "2026-09-08")
    assert spec.agg == "series" and spec.limit == F.READ_LIMIT
    assert F.TAPE_READ_SESSIONS == 330 and F.TAPE_READ_DAYS == 478, (
        "the scope is DERIVED: the 250-session percentile window + the 63-session change + the "
        "17-session roll margin, priced in days off CADENCE_DAYS")
    assert spec.period_start == "2025-05-18" == F.tape_period_start("2026-09-08"), (
        "330 sessions, never the daily cadence's five-year SERIES span: this read is a CURVE")
    rows = _curve(_sessions(40), ["2026-12"])
    qfn = F.fixture_query_fn({"silver_futures_eod": rows})
    F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=qfn)
    sql = qfn.calls[0]
    assert "settle AS value" in sql and "LIMIT 5000" in sql
    assert ", open_interest, volume" in sql, (
        "the front-month rule's OWN input columns ride the tape's projection -- without them "
        "front_month_inputs_present refuses every board whose method reads a metric")
    assert "trade_year >= 2025" in sql, "the scope prunes the partition too, four years of it"
    # the ORDER BY reads the ALIASES `_extras` minted, and this card's session axis is `knowledge_date`
    # (it serves `trade_date` as both its date and its knowledge column, so there is no `data_date`)
    assert "knowledge_date DESC" in sql, "a cap that bites must keep the NEWEST sessions (NEWEST_FIRST_ALL)"


def test_the_roll_input_projection_FAILS_CLOSED_on_a_card_that_cannot_serve_it():
    """A caller that asked for the rule's input and silently did not get it is the whole defect. On a card
    with no ``roll_input_cols`` the compiler RAISES instead of returning the settle-only SQL."""
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry
    spec = F.board_spec("silver_noaa_oni", "oni_anom", None, None, "2026-09-08", "monthly")
    ts = load_registry().get("silver_noaa_oni")
    assert Q.build_sql(spec, ts) == Q.build_sql(spec, ts, roll_inputs=False), "default-off is silent"
    with pytest.raises(ValueError, match="roll_input_cols"):
        Q.build_sql(spec, ts, roll_inputs=True)


def test_a_truncated_tape_read_says_so_on_the_row():
    rows = _curve(_sessions(30), ["2026-12", "2027-03"])
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}),
                     limit=60)
    assert t.coverage["truncated"] is True and "row cap" in t.window_note


def test_the_tape_handler_NEVER_RAISES_and_names_its_own_resource_declines():
    def _explode(sql):
        raise RuntimeError("the mirror is on fire")

    def _pool(sql):
        raise F.BoardReadDecline("pool_exhausted", "no connection freed in 5s")
    assert F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=_explode).status == "read_error"
    assert F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=_explode).reads == 1
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=_pool)
    assert t.status == "pool_exhausted" and t.reads == 1


def test_the_tape_never_reads_the_ANCHOR_as_a_DRIVER_ref():
    """``cascade_map.yaml``'s self-reference refusal binds DRIVER refs; SB-T is the anchor's OWN tape.
    The board's map accessor carries no ``silver_futures_eod`` row, so the only path to this table is
    :func:`tape_state` -- which is the design's separation, in code."""
    assert not [r for r, row in F.board_map().items() if (row or {}).get("table") == F.TAPE_TABLE]


def test_every_word_the_tape_row_can_carry_is_in_ITS_OWN_closed_set():
    words = {"ok", "no_tape_slug", "pre_coverage", "front_decline", "changes_thin:3",
             "percentile_thin:3", "pool_exhausted", "pg_timeout", "read_error"}
    for w in words:
        head = status_word(w)
        assert head in TAPE_STATUS_WORDS
        if w != head:
            assert head in TAPE_STATUS_WITH_DETAIL
    assert "read_empty" not in TAPE_STATUS_WORDS, (
        "an empty tape fetch is select_front_expiry's own front_decline, not a second word for it")


@pytest.mark.parametrize("asof", ["2026-09-08", "2024-03-15", "2020-06-30"])
def test_PIT_the_tape_row_never_reads_a_session_after_the_asof(asof):
    """The guard is in the SQL and AGAIN in the selector (``select_front_expiry`` recomputes the cutoff
    from ``spec.asof`` and the card's ``publication_lag_days`` and drops every later session before it
    walks). The fixture hands back rows the real WHERE clause would never have returned, so this pins
    the SECOND belt: a caller that supplies post-cutoff rows cannot make the walk reach one."""
    rows = _curve(_sessions(200, last="2026-09-04"), ["2026-12", "2027-03"])
    t = F.tape_state(CYCLE_SLUG, asof, qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert t.status in ("ok", "front_decline", "pre_coverage") or status_word(t.status) in (
        "changes_thin", "percentile_thin")
    if t.level_date:
        assert t.level_date < asof, "a session at or after the as-of cutoff reached the row"
    for d in (c["from_date"] for c in t.changes):
        if d:
            assert d < asof


# ---------------------------------------------------------------------------------------------------
# THE MEASURED FAILURE (census run #3) AND THE READ THAT FIXES IT
#
# Run #3 declined `front_decline` on 22 of the 26 boards that have a tape -- most of them carrying
# {"n_obs": 5000, "truncated": true} and nothing that could say WHY (a decline, a row count and a flag
# is all a tape row printed). Three different failures produce exactly those fields, so the three are
# separated here on ONE synthetic frame shaped like the real card -- ten delivery months on 1,300
# sessions, 13,000 rows against a 5,000-row cap, both orderings -- read through
# `state.__main__.mirror_query_fn`, an executor that OBEYS the compiled SQL's WHERE, PROJECTION, ORDER
# BY and LIMIT. `feeders.fixture_query_fn` hands back every canned row, which is right for grading the
# arithmetic ABOVE the read and cannot grade the read itself: the cap never bites, the order never
# matters, and a column the SELECT never projected is present anyway -- all three of which are the
# failure being diagnosed.
# ---------------------------------------------------------------------------------------------------
ASOF = "2026-09-08"


def _old_shape_read(slug, rows, *, newest_first):
    """The read AS IT SHIPPED: `board_spec`'s five-year daily span, no roll-input projection."""
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry
    spec = F.board_spec(F.TAPE_TABLE, F.TAPE_METRIC, slug, None, ASOF, "daily")
    ts = load_registry().get(F.TAPE_TABLE)
    qfn = M.mirror_query_fn({"silver_futures_eod": rows})
    got = Q.run(spec, query_fn=qfn, futures_newest_first=newest_first, ym_lag=True)
    sessions = sorted({r["knowledge_date"] for r in got})
    newest = sessions[-1] if sessions else ""
    curve = [r for r in got if r["knowledge_date"] == newest]
    return got, sessions, curve, Q.select_front_expiry(curve, spec, ts)


def test_DIAGNOSIS_the_cap_keeps_the_OLDEST_rows_when_the_newest_first_scope_is_off():
    """CANDIDATE (a), and it is REAL but NOT the live cause: the five-year read is 13,000 rows against a
    5,000-row cap, so under the shipped ASC order the frame stops in 2023 and "the newest session" is
    three years before the as-of. The board threads NEWEST_FIRST_ALL, which is what holds this off --
    and it holds it off by ONE kwarg, on a read that sits at its cap on every liquid board."""
    rows = M.tape_fixture_rows(CYCLE_SLUG)
    assert len(rows) == 13000, "ten delivery months on 1,300 sessions -- the real card's own shape"
    got, sessions, _curve_rows, front = _old_shape_read(CYCLE_SLUG, rows, newest_first=False)
    assert len(got) == 5000 and sessions[-1] < "2023-12-31", "the cap kept the OLDEST end"
    assert front and front[0]["contract_month"] == "2023-09", (
        "a front month IS named -- three years stale, and nothing on the row would say so")
    got, sessions, _curve_rows, front = _old_shape_read(CYCLE_SLUG, rows, newest_first="all")
    assert len(got) == 5000 and sessions[-1] == "2026-09-04", "newest-first keeps the as-of's session"
    assert front and front[0]["contract_month"] == "2026-09"


def test_DIAGNOSIS_the_SERIES_PROJECTION_drops_the_rules_own_input_and_THAT_is_the_cause():
    """CANDIDATE (b), and it is THE cause. ``_extras`` surfaces the card's SERVED aliases; the front-month
    rule reads ``open_interest`` / ``volume``, which are not served metrics, so the frame handed to the
    selector carries the settle and nothing the rule reads -- on a COMPLETE ten-row newest-session curve,
    under EITHER ordering, truncated or not. It reproduces the mirror exactly: on run #3 all 20
    metric-reading boards declined (three of them on reads that never hit the cap) and all four
    ``delivery_cycle`` boards, whose rule reads no metric, served."""
    for nf in (False, "all"):
        got, _sessions, curve, front = _old_shape_read(OI_SLUG, M.tape_fixture_rows(OI_SLUG),
                                                       newest_first=nf)
        cols = sorted(got[0])
        assert "open_interest" not in cols and "volume" not in cols, (
            f"the SERIES projection is settle-only: {cols}")
        assert len(curve) == 10, "the newest session's curve is COMPLETE -- nothing is missing but a column"
        assert front == [], "front_decline, on a frame that is whole in every other respect"
    # the SAME frame, the SAME cap, the SAME ordering -- a slug whose rule reads NO metric serves
    _, _, _, front = _old_shape_read(CYCLE_SLUG, M.tape_fixture_rows(CYCLE_SLUG), newest_first="all")
    assert front and front[0]["contract_month"] == "2026-09"


def test_DIAGNOSIS_the_selectors_own_multi_session_belt_is_NOT_what_fired():
    """CANDIDATE (c), ruled out: ``tape_state`` slices to the newest session before it calls the selector,
    so the frame handed over holds exactly one session and the fail-closed multi-session branch cannot
    fire. Handed the WHOLE fetch, that branch is what would refuse -- which is why the slice exists."""
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry
    rows = M.tape_fixture_rows(CYCLE_SLUG, sessions=40)
    got, _sessions, curve, front = _old_shape_read(CYCLE_SLUG, rows, newest_first="all")
    assert len({r["knowledge_date"] for r in curve}) == 1 and front != []
    spec = F.board_spec(F.TAPE_TABLE, F.TAPE_METRIC, CYCLE_SLUG, None, ASOF, "daily")
    ts = load_registry().get(F.TAPE_TABLE)
    assert Q.select_front_expiry(got, spec, ts) == [], "the belt refuses a multi-session frame"


def test_THE_FIX_the_scoped_read_names_the_front_on_a_board_whose_rule_reads_a_metric():
    """The whole row, end to end, on the frame that reproduced the failure: the front named by the
    shipped rule, the level dated on the as-of's own newest session, and the read still ONE."""
    qfn = M.mirror_query_fn({"silver_futures_eod": M.tape_fixture_rows(OI_SLUG)})
    t = F.tape_state(OI_SLUG, ASOF, qfn=qfn)
    assert t.status == "ok" and t.reads == 1 and len(qfn.calls) == 1
    assert t.contract_month == "2026-09" and t.level_date == "2026-09-04"
    assert t.roll_method == "open_interest" and t.roll_rule_version == "front_month_v2"
    assert t.unit == "US cents/bushel", "the card's per-slug unit override rides the served row"


@pytest.mark.parametrize("expiries,rows,capped", [(8, 2720, False), (10, 3400, False),
                                                 (12, 4080, False), (15, 5000, True)])
def test_THE_FIX_the_scoped_frame_stays_UNDER_THE_CAP_on_the_widest_liquid_board(expiries, rows,
                                                                                 capped):
    """COUNT THE ROWS. The scope is 330 sessions (478 calendar days); a venue that took no holiday at all
    would print 341 sessions in that span, so the frame is 341 x <expiries listed> and stays under the
    5,000-row cap up to FOURTEEN delivery months. COUNTED here on the weekday-dense worst case (340
    sessions in the fixture's own span): 2,720 rows at 8 expiries, 4,080 at 12 -- the widest LIQUID
    board -- and 15 is where the cap turns. Five years of the same board is 12,000-19,000."""
    from leviathan.graphrag.numbers import query as Q
    assert 341 * 14 < F.READ_LIMIT <= 341 * 15, "the bound this scope is chosen against"
    fixture = M.tape_fixture_rows(CYCLE_SLUG, expiries=expiries, cycle=())
    qfn = M.mirror_query_fn({"silver_futures_eod": fixture})
    got = Q.run(F.tape_spec(CYCLE_SLUG, ASOF), query_fn=qfn, futures_newest_first="all",
                ym_lag=True, roll_inputs=True)
    # the cap cuts the OLDEST end, so a capped read's oldest session is a PARTIAL curve: 5,000 rows at
    # 15 expiries is 333 whole sessions plus five rows of a 334th
    assert len(got) == rows
    assert len({r["knowledge_date"] for r in got}) == (340 if not capped
                                                       else -(-F.READ_LIMIT // expiries))
    t = F.tape_state(CYCLE_SLUG, ASOF, qfn=qfn)
    assert t.coverage["truncated"] is capped
    assert t.contract_month == "2026-09" and t.level_date == "2026-09-04", (
        "the front is named on the as-of's own newest session whether or not the cap bit")
    assert t.coverage["n_obs"] > max(F.TAPE_CHANGE_SESSIONS), (
        "the same-contract series still holds the widest change window this row computes")


def test_THE_FIX_a_DEEP_LISTED_board_still_truncates_and_SAYS_SO_keeping_the_newest_sessions():
    """``truncated`` is rare, not impossible: a board listing 61 delivery months a session (the widest
    curve measured on this card) is over 20,000 rows in the scoped window. The cap keeps the NEWEST end,
    the front is still named on the as-of's own session, and the window note prints the window the row
    actually measured rather than the one it asked for."""
    qfn = M.mirror_query_fn({"silver_futures_eod": M.tape_fixture_rows(
        CYCLE_SLUG, sessions=360, expiries=61, cycle=())})
    t = F.tape_state(CYCLE_SLUG, ASOF, qfn=qfn)
    assert t.coverage["truncated"] is True and "row cap" in t.window_note
    assert t.contract_month == "2026-09" and t.level_date == "2026-09-04"
    assert t.coverage["n_obs"] == 82 and t.coverage["history_end"] == "2026-09-04"
    assert "82 sessions on 2026-09" in t.window_note


def test_THE_FIX_the_changes_and_the_percentile_read_EXACTLY_AS_BEFORE_on_the_scoped_frame():
    """The scope moves WHICH ROWS the read fetches and nothing about the arithmetic over them: the four
    SAME-CONTRACT changes off a 0.5-per-session ramp are the same numbers the deck pins on a hand-written
    curve, and every figure still re-executes from its own inputs."""
    qfn = M.mirror_query_fn({"silver_futures_eod": M.tape_fixture_rows(CYCLE_SLUG)})
    t = F.tape_state(CYCLE_SLUG, ASOF, qfn=qfn)
    assert [c["window"] for c in t.changes] == ["1 session", "5 sessions", "21 sessions", "63 sessions"]
    assert [c["delta"] for c in t.changes] == [0.5, 2.5, 10.5, 31.5]
    assert all(c["declined"] is False for c in t.changes)
    assert all(c["to_date"] == "2026-09-04" for c in t.changes)
    assert t.percentile and t.percentile["declined"] is False and t.percentile["n"] == 340
    assert t.percentile["value"] > 99.0, "a monotone ramp puts the newest settle at the top"
    assert t.window_note == "340 sessions on 2026-09, 2025-05-19 to 2026-09-04"
    assert F.TR.re_execute_all(t.derivation, t.inputs) == [], "every SB-T figure reproduces from its rows"


def test_THE_FIX_an_EMPTY_frame_declines_without_raising():
    """A window that fetched nothing is ``front_decline`` with the read it spent -- never a raise, and
    never a percentile over no points."""
    t = F.tape_state(OI_SLUG, ASOF, qfn=M.mirror_query_fn({"silver_futures_eod": []}))
    assert t.status == "front_decline" and t.reads == 1 and t.level is None
    assert t.coverage["n_obs"] == 0 and t.coverage["truncated"] is False
    assert t.percentile is None and t.changes == []
    # and a frame lying entirely OUTSIDE the scope reads the same way, through the real WHERE clause
    old = M.tape_fixture_rows(OI_SLUG, sessions=200, last="2019-06-28")
    t2 = F.tape_state(OI_SLUG, ASOF, qfn=M.mirror_query_fn({"silver_futures_eod": old}))
    assert t2.status == "front_decline" and t2.coverage["n_obs"] == 0


def test_THE_FIX_the_roll_inputs_are_STRIPPED_off_the_row_the_selector_returns():
    """They ride the READ and stop at the SELECTION: the served surface stays settle-only, so no consumer
    downstream of the front-month choice sees a key that is not a served metric."""
    from leviathan.graphrag.numbers import query as Q
    from leviathan.graphrag.numbers.registry import load_registry
    spec, ts = F.tape_spec(OI_SLUG, ASOF), load_registry().get(F.TAPE_TABLE)
    qfn = M.mirror_query_fn({"silver_futures_eod": M.tape_fixture_rows(OI_SLUG, sessions=40)})
    got = Q.run(spec, query_fn=qfn, futures_newest_first="all", ym_lag=True, roll_inputs=True)
    assert "open_interest" in got[0] and "volume" in got[0], "the READ carries the rule's input"
    newest = max(r["knowledge_date"] for r in got)
    front = Q.select_front_expiry([r for r in got if r["knowledge_date"] == newest], spec, ts)
    assert front and "open_interest" not in front[0] and "volume" not in front[0]
    assert front[0]["roll_method"] == "open_interest" and front[0]["contract_month"] == "2026-09"
