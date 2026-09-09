"""ANALOGS BY STATE -- STATE ENGINE DESIGN sec 4 whole, and the bars this file owns: **B9** likeness
not recency, **B10** the lag offset read at BOTH ends, and the two halves of sec 4.4 (event analogs
through ``flag_events``, and an absence said plainly). Sitting S3.

EVERYTHING RUNS OFFLINE ON FIXTURE ARRAYS. The state producer, the benchmark and the receipt retrieval
are INJECTED; nothing here opens a pg mirror, reaches Athena, spends a cent or reads an environment.
"""
import pytest
from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state.feeders import state_from_arrays
from leviathan.graphrag.state.lagbands import parse_lag
from leviathan.graphrag.state.rows import SeriesKey, StateRow

ASOF = "2026-09-07"


def _months(n, start_year=2000, start_month=1):
    out, y, m = [], start_year, start_month
    for _ in range(n):
        last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        out.append(f"{y:04d}-{m:02d}-{last:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _row(values, dates, *, ref="oni_climate", window=60, unit="degC"):
    return state_from_arrays(ref, values, dates, cadence="monthly", asof=ASOF, unit=unit,
                             narrate_unit=unit, windows={"monthly": window}, table="silver_noaa_oni",
                             metric="oni_anom")


# ── 4.1 THE STATE VECTOR ─────────────────────────────────────────────────────────────────────────────
def test_the_state_vector_is_the_prefix_walk_and_a_hole_is_a_hole():
    """``rolling_zscore`` is ``zscore`` per PREFIX -- a past date ranked against a distribution holding
    its own future would be ranked by information nobody held. A prefix too short for the window is
    ``None``, not zero."""
    d = _months(120)
    v = [float(i % 7) - 3.0 for i in range(120)]
    h = A.state_history(_row(v, d), want_pct=True)
    assert len(h["z"]) == 120
    assert h["z"][0] is None and h["z"][58] is None      # the window is 60; the prefix cannot fill it
    assert h["z"][-1] is not None
    assert all(p is None or 0.0 <= p <= 100.0 for p in h["pct"])
    # THE PERCENTILE VECTOR IS LAZY. It is O(n log n) when asked for and ABSENT when not, because every
    # row but a `percentile_bands` crossing and the co-loud decile test discards it -- the first cut
    # built it per observation through one transform call each and MEASURED 1.94 s on a single
    # 5,000-point daily series, against sec 7's "+0 to +4 s pre-writer" for the whole board.
    assert all(p is None for p in A.state_history(_row(v, d))["pct"])


def test_the_state_vector_stays_inside_secs_7_own_pre_writer_budget_on_a_DAILY_ref():
    """Sec 7 states "+0 to +4 s pre-writer" for the whole board. ``state_history`` used to call the
    ``percentile`` transform once per observation over a growing prefix -- O(n^2), MEASURED at 1.94 s
    for ONE 5,000-point daily series (the row cap sec 2.1 sets for a daily ref) -- and ``analog_rows``
    builds one per seed while ``co_loud_analogs`` builds one per anchor contract. The bar is generous on
    purpose: it fails on a return to the quadratic pass and on nothing else.

    **THE TWO CLAIMS ARE MEASURED BY THE INSTRUMENT THAT CAN SEE EACH, and the first cut raced two wall
    clocks that cannot.** It timed the ``want_pct`` pass against the pass without it and required the
    second to come in within 50 ms of the first. MEASURED on this box over four paired runs: 0.799 /
    0.758, 0.815 / 0.696, 0.746 / 0.791, 0.703 / 0.683 -- the two passes cost the SAME to within noise,
    because the fast prefix percentile is one sort beside a z pass that walks every prefix anyway, and
    the sign of the difference is the scheduler's to choose. The bar red on a full-deck run and green
    alone, which is a bar grading the machine. The budget claim keeps a wall clock and moves to a
    threshold that still catches the 1.94 s quadratic with room (a run at 0.82 s is the fast pass on a
    loaded box, not a regression); the laziness claim is STRUCTURAL -- the vector nobody asked for is
    absent, not merely cheap -- so it is read off the result. Neither claim is dropped."""
    import time
    n = 5000
    d = [f"{2000 + i // 250:04d}-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]
    v = [float((i * 7919) % 997) for i in range(n)]
    st = _row(v, d, window=250)
    t0 = time.perf_counter()
    h = A.state_history(st, want_pct=True)
    with_pct = time.perf_counter() - t0
    t1 = time.perf_counter()
    lean = A.state_history(st)
    without_pct = time.perf_counter() - t1
    assert len(h["pct"]) == n and h["pct"][-1] is not None
    assert with_pct < 1.5, f"the prefix percentile took {with_pct:.3f}s on {n} points"
    assert without_pct < 1.5, f"the z pass alone took {without_pct:.3f}s on {n} points"
    assert all(p is None for p in lean["pct"]), "the vector nobody asked for was built anyway"


def test_the_prefix_percentile_is_the_SAME_ARITHMETIC_stats_percentile_does():
    """A second calculator is the defect this pin exists to make impossible: the fast pass and the
    registered transform must agree at EVERY prefix, refusal included."""
    from leviathan.graphrag.numbers import stats as ST
    v = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0, 5.0, 3.0, 5.0, 8.0, 9.0, 7.0, 9.0]
    fast = A._prefix_percentiles(v)
    for i in range(len(v)):
        want = ST.percentile(v[i], v[: i + 1])
        assert (fast[i] is None) == bool(want["declined"]), i
        if fast[i] is not None:
            assert fast[i] == pytest.approx(want["value"]), i


def test_PIT_the_state_vector_is_the_prefix_KNOWABLE_at_each_date_never_the_one_dated_it():
    """Sec 4.1: "a crossing at t on MPOB stocks was knowable at t + 43 d, so the prefix stops where
    knowledge did". The lag was an admissibility filter against the as-of and nothing else, so a
    candidate was scored on prints nobody held on the day it is dated by. With a publication lag the
    vector position dated t carries the state of the newest print PUBLISHED by t."""
    d = _months(120)
    v = [float(i % 7) - 3.0 for i in range(120)]
    st = _row(v, d, window=12)
    same_day = A.state_history(st, want_pct=True)
    lagged = A.state_history(st, lag_days=43, want_pct=True)
    assert same_day["lag_days"] == 0 and lagged["lag_days"] == 43
    # 43 days back from a month-end lands in the month BEFORE the previous one on a 28-day February and
    # in the previous month otherwise: either way the state at position i is a state position i - 1 or
    # earlier already carried, and never i's own.
    for i in range(20, 120):
        assert lagged["z"][i] in (same_day["z"][i - 1], same_day["z"][i - 2]), i
        assert lagged["z"][i] != same_day["z"][i] or same_day["z"][i] == same_day["z"][i - 1]
    assert lagged["z"][0] is None                       # nothing was published before the first print


def test_the_knowledge_axis_is_the_IDENTITY_on_a_card_that_publishes_on_its_own_date():
    d = _months(40)
    v = [float(i) for i in range(40)]
    assert A._knowable_indices(d, 0) == list(range(40))
    st = _row(v, d, window=12)
    assert A.state_history(st)["z"] == A.state_history(st, lag_days=0)["z"]


# ── 4.2 CANDIDATES ───────────────────────────────────────────────────────────────────────────────────
def test_a_crossing_is_ONE_candidate_per_episode_not_one_per_month():
    """A twelve-month rise contributes ONE candidate (its start), not twelve."""
    d = _months(30)
    v = [0.0] * 9 + [round(float(i) * 0.1, 2) for i in range(1, 13)] + [1.2] * 9
    h = A.state_history(_row(v, d, window=12))
    cs = [c for c in A.crossings(h, min_run=1) if c["kind"] == "run_start"]
    assert len(cs) == 1 and cs[0]["date"] == d[9]


def test_the_run_start_rule_is_a_COMPARISON_TO_NOW_and_not_a_threshold():
    """``min_run`` is the CURRENT run's own length: a past run counts when it ran at least as long as
    the run the series is in now. Nothing here is a number somebody chose; it moves with the board."""
    d = _months(40)
    v = []
    for i in range(40):                                  # alternating two-month wiggles, then a long run
        v.append(float(i % 2))
    v[-8:] = [0.0, 0.3, 0.6, 0.9, 1.2, 1.5, 1.8, 2.1]
    h = A.state_history(_row(v, d, window=12))
    loose = [c for c in A.crossings(h, min_run=1) if c["kind"] == "run_start"]
    tight = [c for c in A.crossings(h, min_run=7) if c["kind"] == "run_start"]
    assert len(loose) > len(tight)
    assert len(tight) == 1


def test_a_declared_band_crossing_is_a_candidate_of_its_own_kind():
    d = _months(40)
    v = [0.1] * 20 + [0.9] * 20
    h = A.state_history(_row(v, d, window=12))
    cs = A.crossings(h, convention={"kind": "abs_bands", "bands": [0.5]}, min_run=99)
    assert [c["kind"] for c in cs] == ["band_crossing"]
    assert cs[0]["date"] == d[20]


# ── B9 LIKENESS, NOT RECENCY ─────────────────────────────────────────────────────────────────────────
#: The band bar B9's fixtures use. FOUR TO EIGHT QUARTERS, deliberately: its far end is twenty-four
#: months, so the CURRENT episode's own start -- always the most like state there is -- has a window
#: that has NOT closed and is correctly excluded. A shorter band admits it and the deck would be
#: measuring "is today like today".
B9_BAND = "4-8 quarters"


#: The seed's own rolling window. EVERY EPISODE IN A B9 FIXTURE SITS PAST IT, and that is not a detail:
#: ``rolling_zscore`` returns ``None`` for a prefix shorter than the window, so an episode inside the
#: warm-up has no state to be like and is correctly unobservable. The first cut of these fixtures put
#: the "old like" episode at index 40 with a sixty-month window, so the deck's own LIKE candidate was
#: invisible and the test measured the fixture rather than the selector.
B9_WINDOW = 60


def _like_fixture():
    """A series whose MOST RECENT crossing is UNLIKE now and whose OLDER one is LIKE now. Bar B9's own
    fixture, built so recency and likeness disagree by construction."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for i in range(80, 92):                              # an OLD episode that looks like today's
        v[i] = 0.10 * (i - 79)
    for i in range(140, 152):                            # a RECENT episode, much smaller
        v[i] = 0.01 * (i - 139)
    for i in range(188, 200):                            # today: the same shape as the OLD one
        v[i] = 0.10 * (i - 187)
    return v, d


def test_B9_the_LIKE_crossing_is_selected_even_when_an_UNLIKE_one_is_newer():
    v, d = _like_fixture()
    st = _row(v, d, window=60)
    h = A.state_history(st)
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"])}]
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=parse_lag(B9_BAND), analog_k=1)
    assert sel["declined"] is None
    picked = sel["picked"][0]["date"]
    assert picked == d[80], f"the older LIKE crossing must win, got {picked}"


def test_B9_the_count_in_words_is_the_pool_the_header_describes_and_one_match_still_renders():
    v, d = _like_fixture()
    st = _row(v, d, window=60)
    h = A.state_history(st)
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"])}]
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=parse_lag(B9_BAND), analog_k=5)
    assert sel["n_candidates"] >= 1
    assert len(sel["picked"]) >= 1                       # frequency floors deny the tail


def _hand_hist(dates, values, z):
    """A state vector STATED rather than computed.

    The distance and sign tests below are about the SELECTOR's arithmetic, and computing the z through
    ``rolling_zscore`` makes two structurally identical episodes carry DIFFERENT z values -- the later
    one's trailing window contains the earlier one. That is correct producer behaviour and it makes a
    tie impossible to construct, so these two decks state the vector and grade the selection."""
    return {"dates": list(dates), "values": list(values), "z": list(z),
            "pct": [None] * len(dates), "window": 12}


def test_recency_breaks_a_tie_INSIDE_an_already_like_pool_and_nowhere_else():
    """Two crossings with the SAME state and the SAME run length: the newer one wins, because the
    tie-break is date DESCENDING -- and only after the distance and the run-length difference have
    already tied. Recency never orders an unlike pool (that is the bar above)."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for base in (80, 140, 188):
        for i in range(base, base + 12):
            v[i] = 0.10 * (i - base + 1)
    z = [0.0] * 200
    z[80] = z[140] = z[199] = 1.0
    h = _hand_hist(d, v, z)
    dims = [{"id": "oni", "hist": h, "z_now": 1.0}]
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=parse_lag(B9_BAND), analog_k=1)
    assert sel["picked"][0]["date"] == d[140]


def test_the_sign_gate_refuses_a_pool_that_leans_the_other_way():
    """The gate needs sign agreement on at least half the dimensions. A record whose every observable
    past state sits on the other side of zero yields ``no_like_state`` -- a row that says so, never a
    nearest match dressed as a likeness."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for base in (80, 140):
        for i in range(base, base + 12):
            v[i] = -0.10 * (i - base + 1)
    for i in range(188, 200):
        v[i] = 0.10 * (i - 187)
    h = _hand_hist(d, v, [-1.0] * 200)
    dims = [{"id": "oni", "hist": h, "z_now": 2.0}]
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=parse_lag(B9_BAND), analog_k=1)
    assert sel["declined"] == "no_like_state"


def test_every_dimension_must_be_OBSERVABLE_at_t_so_the_printed_floor_is_TRUE():
    """Sec 4.2's own candidate filter. Without it the header could say "the loud set reaches back to
    2006" one line above a stanza dated 2001 -- the two sentences contradicting each other."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for base in (80, 160, 188):
        for i in range(base, base + 12):
            v[i] = 0.10 * (i - base + 1)
    st = _row(v, d, window=B9_WINDOW)
    h = A.state_history(st)
    # A dimension whose own record starts at index 150: nothing before it is observable on BOTH.
    short = {"dates": d[150:], "values": v[150:], "z": [0.4] * 50, "pct": [None] * 50, "window": 12}
    seed_only = A.select_analogs(h, dims=[{"id": "oni", "hist": h,
                                           "z_now": float(st.z["value"])}],
                                 asof=ASOF, band=parse_lag(B9_BAND), analog_k=3)
    assert any(p["date"] < d[150] for p in seed_only["picked"])      # reachable on the seed alone
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"])},
            {"id": "late", "hist": short, "z_now": 0.4}]
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=parse_lag(B9_BAND), analog_k=3)
    assert sel["picked"]
    for p in sel["picked"]:
        assert p["date"] >= d[150]                                   # and unreachable with the second


def test_a_candidate_whose_window_HAS_NOT_CLOSED_is_never_selected():
    """"at least max_q quarters of the widest band before asof so the outcome window has closed" -- a
    like state whose consequence has not happened yet is not evidence."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for i in range(188, 200):
        v[i] = 0.10 * (i - 187)
    st = _row(v, d, window=60)
    h = A.state_history(st)
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"])}]
    sel = A.select_analogs(h, dims=dims, asof=d[-1], band=parse_lag("2-4 quarters"), analog_k=1)
    assert sel["declined"] == "no_like_state"


def test_the_likeness_distance_is_UNWEIGHTED_and_carries_no_scalar_score():
    h = {"dates": _months(10), "values": [0.0] * 10, "z": [1.0] * 10, "pct": [None] * 10, "window": 5}
    two = A.likeness(h["dates"][5], [{"id": "a", "hist": h, "z_now": 2.0},
                                     {"id": "b", "hist": h, "z_now": 3.0}])
    assert two["distance"] == pytest.approx((1.0 + 2.0) / 2.0)


def test_the_likeness_denominator_is_the_DECLARED_dimension_count_and_not_the_observed_one():
    """Sec 4.2 writes ``sum over dims |z_t - z_now| / |dims|``. Dividing by the OBSERVED count instead
    made a candidate seen on two of three dimensions arithmetically closer than one seen on all three
    with the same total gap -- masked inside `select_analogs`, which additionally requires every
    dimension to be observable, and wrong for any other caller."""
    d = _months(10)
    seen = {"dates": d, "values": [0.0] * 10, "z": [1.0] * 10, "pct": [None] * 10, "window": 5}
    blind = {"dates": d, "values": [0.0] * 10, "z": [None] * 10, "pct": [None] * 10, "window": 5}
    got = A.likeness(d[5], [{"id": "a", "hist": seen, "z_now": 3.0},
                            {"id": "b", "hist": seen, "z_now": 2.0},
                            {"id": "c", "hist": blind, "z_now": 1.0}])
    assert got["dims_seen"] == 2 and got["dims_declared"] == 3
    assert got["distance"] == pytest.approx((2.0 + 1.0) / 3.0)


# ── B10 THE LAG OFFSET, READ AT BOTH ENDS ────────────────────────────────────────────────────────────
def test_B10_the_outcome_window_is_the_parents_band_read_at_BOTH_ends():
    d = _months(60)
    v = [float(i) for i in range(60)]                     # +1 per month: the arithmetic is checkable
    o = A.outcome_over_band(label="x", values=v, dates=d, t=d[10], band=parse_lag("1-2 quarters"),
                            asof=ASOF, unit="MMT")
    assert o["declined"] is None
    assert o["near_date"] == d[13] and o["far_date"] == d[16]
    assert o["near_value"] == pytest.approx(3.0) and o["far_value"] == pytest.approx(6.0)
    # THE MONTH IS THE GRAIN: three months after a month-end print is that month's OWN print, not the
    # one before it. `_window_end` is what makes the sixth month's row the sixth month's row.


def test_B10_a_ZERO_quarter_near_end_is_the_states_own_date_and_its_change_is_ZERO():
    """The commonest band in the estate opens at zero quarters (484 of 1,412 declarations). "It had not
    moved yet" is the honest reading of that end, not an absence."""
    d = _months(60)
    v = [float(i) for i in range(60)]
    o = A.outcome_over_band(label="x", values=v, dates=d, t=d[10], band=parse_lag("0-2 quarters"),
                            asof=ASOF)
    assert o["declined"] is None
    assert o["near_value"] == pytest.approx(0.0) and o["far_value"] == pytest.approx(6.0)


def test_B10_an_OPEN_horizon_declines_by_name_and_never_invents_a_far_end():
    d = _months(60)
    v = [float(i) for i in range(60)]
    o = A.outcome_over_band(label="x", values=v, dates=d, t=d[-2], band=parse_lag("2-4 quarters"),
                            asof=d[-1])
    assert o["declined"] == "horizon_open"
    assert "far_value" not in o


def test_B10_structural_opens_and_never_closes_so_no_outcome_is_readable():
    d = _months(60)
    o = A.outcome_over_band(label="x", values=[1.0] * 60, dates=d, t=d[5],
                            band=parse_lag("structural"), asof=ASOF)
    assert o["declined"] == "horizon_open"


def test_B10_an_UNDECLARED_band_declines_on_the_EDGE_leg_by_its_own_word():
    """"a child whose parent declares no band declines `lag_undeclared_between_nodes`" -- an `edge:`
    word, carried on the row with the leg it belongs to, never folded into an analog word."""
    d = _months(60)
    o = A.outcome_over_band(label="x", values=[1.0] * 60, dates=d, t=d[5],
                            band=parse_lag("a lag nobody declared"), asof=ASOF)
    assert o["declined"] == "lag_undeclared_between_nodes" and o["decline_leg"] == "edge"


def test_the_outcome_re_executes_from_its_own_inputs():
    """Every printed magnitude reproduces from the rows it was computed from (sec 2.5 lint clause 3)."""
    from leviathan.graphrag.state import transforms as TR
    d = _months(60)
    v = [float(i) for i in range(60)]
    o = A.outcome_over_band(label="x", values=v, dates=d, t=d[10], band=parse_lag("1-2 quarters"),
                            asof=ASOF)
    assert TR.re_execute_all(o["derivation"], o["inputs"]) == []


# ── 4.4 EVENT ANALOGS ────────────────────────────────────────────────────────────────────────────────
def _flag_row(values, dates, *, status="ok"):
    st = state_from_arrays("policy_flag", values, dates, cadence="monthly", asof=ASOF, is_flag=True,
                           table="silver_flag", metric="flag")
    st.status = status
    return B.NodeRow(contract="c", driver_id="policy_event", type="policy_event",
                     lag_band=parse_lag("0-2 quarters"), state=st)


def test_event_analogs_come_from_the_FLAG_series_own_events():
    d = _months(60)
    v = [0.0] * 60
    v[10] = v[30] = 1.0
    got = A.event_analogs(_flag_row(v, d), asof=ASOF, band=parse_lag("0-2 quarters"))
    assert got["declined"] is None
    assert d[10] in got["dates"]


def test_a_PLANNED_policy_row_says_there_is_no_numeric_event_history():
    """"prior steps are receipts, not analogs" -- a receipt-selected candidate pool would be
    text-selected, which is the shape ruling 4 retires."""
    row = B.NodeRow(contract="c", driver_id="biodiesel_mandate", type="policy_event",
                    lag_band=parse_lag("0-2 quarters"),
                    state=StateRow(key=SeriesKey(ref="biodiesel_mandate_flag"),
                                   status="unmapped_ref"))
    got = A.event_analogs(row, asof=ASOF)
    assert got["declined"] == "no_numeric_event_history"


def test_EVERY_admissible_event_rides_including_the_NEWEST_one():
    """The first cut returned ``out[:-1] or out``, silently dropping the newest prior event under no
    stated rule. The two filters that ARE rules -- an event at or after the as-of is not history, and
    one whose band has not closed has no outcome -- already ran above it."""
    d = _months(60)
    v = [0.0] * 60
    v[10] = v[30] = 1.0
    got = A.event_analogs(_flag_row(v, d), asof=ASOF, band=parse_lag("0-2 quarters"))
    assert got["dates"] == (d[10], d[30])


def test_an_event_whose_own_band_has_not_closed_is_not_an_analog_candidate():
    d = _months(60)
    v = [0.0] * 60
    v[-1] = 1.0
    got = A.event_analogs(_flag_row(v, d), asof=d[-1], band=parse_lag("2-4 quarters"))
    assert got["declined"] == "no_like_state"


# ── 4.4 RECEIPTS EXPLAIN; ABSENCE IS SAID PLAINLY ────────────────────────────────────────────────────
def test_a_receipt_published_AFTER_the_like_date_never_rides_the_stanza():
    """The publication axis is pre-filtered to ``<= t`` -- the second as-of hop's own discipline."""
    seed = B.NodeRow(contract="c", driver_id="d")
    got = A._receipts_for(None, seed, "2020-01-31", cap=3, receipt_fn=lambda *_a: [
        {"date": "2019-12-01", "source": "s", "text": "before"},
        {"date": "2020-06-01", "source": "s", "text": "after"}])
    assert [r["text"] for r in got] == ["before"]


def test_no_receipt_is_an_ABSENCE_WITH_WORDS_and_the_render_says_them():
    from leviathan.graphrag.state.render import ABSENCE_WHY
    assert ABSENCE_WHY["no_receipt"] == "no documents exist for it"


# ── leg B, dark ──────────────────────────────────────────────────────────────────────────────────────
def test_leg_B_is_DARK_and_returns_nothing_with_its_rider_off():
    assert A.leg_b_rows([{"contract": "c", "driver_id": "d", "band": parse_lag("1-2 quarters"),
                          "date": "2020-01-31", "asof": ASOF, "declined": None}], on=False) == []


def test_leg_B_prices_the_LOWER_END_of_a_band_the_span_fence_cannot_certify():
    """"if 365 d does not close both fences on a clear majority, leg B prices `[t + 3*min_q, t + 3*min_q
    + 270 d]` and the row says in words that the window is the lower end of the declared band"."""
    calls = []
    rows = A.leg_b_rows([{"contract": "c", "driver_id": "d", "band": parse_lag("4-8 quarters"),
                          "date": "2020-01-31", "asof": ASOF, "declined": None}],
                        on=True, span_max_days=270, verdict_fn=lambda *_a, **_k: "",
                        cell_fn=lambda *a: calls.append(a) or {"ok": True})
    assert len(rows) == 1 and "lower end of the declared band" in rows[0]["note"]
    t1, t2 = rows[0]["span"]
    assert A._days_between(t1, t2) == 270


def test_the_cascade_symbols_leg_B_reads_all_resolve():
    """A rename in the K9 lane must red at IMPORT rather than at serve -- ``feeders.CASCADE_IMPORTS``'
    discipline, applied to the one other place this package reads that file."""
    assert A.check_cascade_analog_imports() == []


# ── AMENDMENT 1: the CO-LOUD analog for a driver-as-subject anchor ───────────────────────────────────
def _positioning_board(pcts_by_contract, *, driver_id="cot_mm_positioning"):
    """A board whose anchors are the contracts carrying ONE driver -- the shape a ``focus_driver``
    anchor produces (sec 16 Amendment 1)."""
    d = _months(60, 2018, 1)
    bd = B.Board(asof=ASOF, mode="max", knobs=B.board_knobs_of("max"),
                 anchors=tuple(B.Anchor(contract=c, source="focus_driver", rank=i,
                                        driver_id=driver_id, subject=True)
                               for i, c in enumerate(pcts_by_contract)))
    for c, vals in pcts_by_contract.items():
        st = state_from_arrays("cot_mm_positioning", vals, d, cadence="monthly", asof=ASOF,
                               windows={"monthly": 24}, table="silver_cot", metric="mm_net",
                               commodity=c)
        row = B.NodeRow(contract=c, driver_id=driver_id, lag_band=parse_lag("0-1 quarters"),
                        state=st, subject=True)
        bd.rows.append(row)
    bd.order = tuple(r.key for r in bd.rows)
    return bd


def test_the_CO_LOUD_analog_finds_the_dates_when_k_CONTRACTS_sat_in_the_top_decile_at_once():
    """Amendment 1: "a CO-LOUD analog: dates when >= k contracts sat in the top decile at once,
    outcomes over each contract's own lag band". It is a different selector from the ordinary one
    because a driver anchored as the SUBJECT is a question about co-occurrence across the contracts
    that carry it, not about one series looking like itself."""
    rising = [float(i) for i in range(60)]
    spike = [0.0] * 30 + [100.0] * 12 + [0.0] * 18
    bd = _positioning_board({"soybeans_cbot": spike, "corn_cbot": spike, "cotton": rising})
    bench = {c: {"values": [float(100 + i) for i in range(60)], "dates": _months(60, 2018, 1),
                 "unit": "USD/t", "label": f"the monthly benchmark for {c}",
                 "table": "silver_pink_sheet", "metric": "px"}
             for c in ("soybeans_cbot", "corn_cbot", "cotton")}
    got = A.co_loud_analogs(bd, "cot_mm_positioning", k=2, analog_k=2,
                            benchmark_fn=lambda c: bench.get(c))
    assert got["declined"] is None
    assert got["dates"] and all(h["n_contracts"] >= 2 for h in got["dates"])
    assert set(got["per_contract"]) == {"soybeans_cbot", "corn_cbot", "cotton"}
    # THE OUTCOME HALF IS HALF THE AMENDMENT. The first cut returned row KEYS and computed nothing, so
    # "each contract's outcome over its OWN lag band" had no producer at all: one outcome per picked
    # date, per contract, over that contract's declared band, read at both ends.
    for c, entry in got["per_contract"].items():
        assert entry["band"].raw == "0-1 quarters", c
        assert len(entry["outcomes"]) == len(got["dates"]), c
        fired = [o for o in entry["outcomes"] if not o.get("declined")]
        assert fired, c
        for o in fired:
            assert o["band"].raw == entry["band"].raw
            assert o["near_value"] is not None and o["far_value"] is not None


def test_the_CO_LOUD_outcome_DECLINES_BY_NAME_when_no_benchmark_seat_was_filled():
    """The consequence of a driver-as-subject state is the CONTRACT'S PRICE. Reading the shared driver's
    own array back "on that board" returns the parent's move wearing another board's name -- the defect
    ``_outcomes_for`` measures -- so an unfilled seat is a row that says so."""
    spike = [0.0] * 30 + [100.0] * 12 + [0.0] * 18
    bd = _positioning_board({"soybeans_cbot": spike, "corn_cbot": spike})
    got = A.co_loud_analogs(bd, "cot_mm_positioning", k=2, analog_k=1)
    for entry in got["per_contract"].values():
        assert all(o.get("declined") for o in entry["outcomes"])


def test_the_CO_LOUD_analog_says_no_like_state_when_the_contracts_never_co_occur():
    early = [100.0] * 12 + [0.0] * 48
    late = [0.0] * 48 + [100.0] * 12
    bd = _positioning_board({"soybeans_cbot": early, "corn_cbot": late})
    got = A.co_loud_analogs(bd, "cot_mm_positioning", k=2, analog_k=2)
    assert got["declined"] == "no_like_state"


def test_POSITIONING_AS_SUBJECT_is_the_one_exception_to_context_only():
    """D18 holds everywhere else: a positioning row is never a fan source, a convergence member, an
    analog dimension or a projection anchor. Amendment 1 yields ONLY when the query names the driver
    being explained, and the yielding is recorded on the ROW so every consumer reads one field."""
    bd = _positioning_board({"soybeans_cbot": [float(i) for i in range(60)]})
    assert all(r.subject for r in bd.rows)
    assert bd.subject_driver == "cot_mm_positioning"


# ── 1.4 / 4.1 THE year_month PUBLICATION LAG -- the SAME lag the live read applies ───────────────────
#: The three ``year_month`` cards the board leans on, and the lag each DECLARES (S0, measured against
#: the live registry here rather than restated). They are the whole population of the ym rule: every
#: other board card is a ``data_date`` or a ``vintage`` card and carries its lag in the other field.
YM_CARDS: dict = {"silver_noaa_oni": 36, "silver_noaa_iod": 45, "gold_weather_z": 7}


def _ym_labels(n, start_year=2010, start_month=1):
    """``YYYY-MM`` period labels -- what ``feeders._period_dates`` writes for a card with no date
    column, and the axis every ``year_month`` state history is actually indexed on."""
    out, y, m = [], start_year, start_month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _ym_state(dates, values, *, ref="oni_climate", lag=36):
    """A ym-card StateRow carrying the recency block ``feeders._recency`` writes -- BOTH lag fields, in
    the shape the live producer fills them: the ym lag declared, the day lag null."""
    st = _row(values, dates, ref=ref, window=12)
    st.recency = {"age_days": None, "age_periods": None, "level_date": dates[-1],
                  "knowledge_date": None, "publication_lag_days": 0,
                  "ym_publication_lag_days": lag, "next_release": None}
    return st


def test_the_THREE_year_month_cards_DECLARE_their_lag_in_the_ym_field_and_the_accessor_READS_it():
    """S3-1, MEASURED against the live registry. ``_lag_days_of`` read ``publication_lag_days`` alone,
    and all three ``year_month`` cards leave that field null -- so the accessor returned ZERO on ONI
    (36 d), IOD (45 d) and the weather z (7 d), the three cards whose lag the board leans hardest on.
    The live read has applied the ym lag since S1 (``query._ym_lagged_asof_ym``); the analog history it
    is compared against was reading a lag of nothing."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    for tid, lag in YM_CARDS.items():
        ts = reg.get(tid)
        assert ts is not None and ts.knowledge_semantics == "year_month", tid
        assert ts.ym_publication_lag_days == lag, tid
        assert not (ts.publication_lag_days or 0), \
            "%s declares a DAY lag too -- the accessor's precedence needs re-reading" % tid
        d = _ym_labels(24)
        st = _ym_state(d, [float(i % 5) for i in range(24)], lag=ts.ym_publication_lag_days)
        row = B.NodeRow(contract="c", driver_id="d", state=st)
        assert A._lag_days_of(row) == lag, tid


def test_a_year_month_label_is_placed_on_its_MONTH_END_the_day_the_live_read_places_it():
    """The raw label sorts as the month's FIRST instant (``"2026-01" <= "2026-01-31"`` is a prefix
    comparison and is True), which is the exact leak D21 closes on the read side. One placement rule,
    both sides of the knowledge axis."""
    assert A.axis_date("2026-01") == "2026-01-31"
    assert A.axis_date("2026-02") == "2026-02-28" and A.axis_date("2024-02") == "2024-02-29"
    assert A.axis_date("2026-01-15") == "2026-01-15"    # an ISO day rides as itself
    assert A.axis_date("2026") == "2026-12-31"
    assert A.axis_date("") is None and A.axis_date("not-a-date") is None


def test_an_ONI_analog_candidate_NEVER_SEES_the_month_that_was_published_AFTER_the_asof():
    """S3-1's own bar, on ONI's declared 36 days at as-of 2026-09-07.

    The August data month is dated 2026-08-31 and is knowable on 2026-10-06 -- a month after the as-of.
    With the lag read as zero it was an admissible analog candidate and its print sat in every earlier
    candidate's distribution. With the card's own lag applied it is not admitted, and the newest
    candidate that IS admitted is one whose publication date had passed."""
    asof = "2026-09-07"
    d = _ym_labels(60, 2021, 9)                         # ... 2026-07, 2026-08
    assert d[-1] == "2026-08" and d[-2] == "2026-07"
    v = [0.0] * 60
    v[-2], v[-1] = 0.9, 0.4          # up-start at 2026-07, down-start at 2026-08: TWO episodes
    h = _hand_hist(d, v, [0.0] * 58 + [1.0, 1.8])
    dims = [{"id": "oni", "hist": h, "z_now": 1.8}]
    # a POINT band ("0 quarters", six nodes declare it): the outcome window closes in the candidate's
    # own month, so this deck grades the KNOWLEDGE filter and not the outcome-window one.
    band = parse_lag("0 quarters")
    kw = dict(dims=dims, asof=asof, band=band, analog_k=3, min_run=1)

    landing = A.select_analogs(h, lag_days=0, **kw)
    assert landing["picked"] and landing["picked"][0]["date"] == "2026-08", \
        "the fixture must reproduce the defect, or it is grading nothing"

    fixed = A.select_analogs(h, lag_days=36, **kw)
    assert "2026-08" not in {p["date"] for p in fixed["picked"]}
    assert fixed["picked"] and fixed["picked"][0]["date"] == "2026-07"
    for p in fixed["picked"]:
        assert A._add_days(p["date"], 36) <= asof, p["date"]

    # AND THE THIRTY-SIX ARRIVES FROM THE CARD, not from this deck's hand. The two halves of S3-1 are
    # the accessor (which field it reads) and the selector (what the lag then excludes); grading them
    # apart leaves the SEAM ungraded, and the seam is where the defect lived -- a correct selector fed
    # a zero by an accessor reading the wrong field.
    row = B.NodeRow(contract="c", driver_id="oni_climate",
                    state=_ym_state(d, v, lag=YM_CARDS["silver_noaa_oni"]))
    assert A._lag_days_of(row) == 36
    end_to_end = A.select_analogs(h, lag_days=A._lag_days_of(row), **kw)
    assert {p["date"] for p in end_to_end["picked"]} == {p["date"] for p in fixed["picked"]}


def test_the_ONI_knowledge_axis_holds_the_newest_month_the_publisher_had_PRINTED():
    """The re-index itself, on ONI's own 36 days. At the August position a desk held the JUNE print:
    June's month-end plus 36 days is 2026-08-05, July's is 2026-09-05 -- five days past August's end."""
    d = _ym_labels(12, 2025, 9)                          # ... 2026-07, 2026-08
    idx = A._knowable_indices(d, 36)
    assert d[idx[-1]] == "2026-06", d[idx[-1]]
    assert d[idx[-2]] == "2026-05"
    assert A._knowable_indices(d, 0) == list(range(12))  # a zero lag is still the identity
