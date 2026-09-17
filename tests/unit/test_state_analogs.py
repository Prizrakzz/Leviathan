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
from leviathan.graphrag.state.lagbands import LagBand, parse_lag
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
    fixture, built so recency and likeness disagree by construction.

    **REBUILT AT ROUND 2, AND THE OLD ONE WAS MEASURING ITS OWN BASELINE.** The first two cuts laid three
    episodes on a record that was otherwise ALL ZEROS, which makes ``rolling_zscore`` a statement about
    which spikes happen to sit inside a sixty-month window rather than about the state: the old episode's
    z was 7.681 and today's 3.544 for the same shape, so on the z alone the bar FAILED and it held first
    on the sign gate and then on the prefix percentile -- two different rules doing a distance's job,
    and round 2 struck the second of them (MAJOR 1). The baseline is now an ALTERNATING +/- 0.5, so every
    sixty-month window carries the same variance and the same mean, a z is comparable at every index, and
    every index is a direction change -- which makes the relaxed candidate pool the whole record and puts
    the bar's two candidates in it against 170-odd others rather than against nothing.

    MEASURED ON IT: the old like spike (index 80, 2.0) reads z = 3.54, today's identical spike reads
    z_now = 3.45, and the newer, SMALLER spike (index 140, 1.0) reads 1.94. The gaps are 0.09 and 1.51,
    the baseline months sit at 2.45 or worse, and the like date wins ON THE ARITHMETIC OF ONE STATISTIC."""
    d = _months(200, 2010, 1)
    v = [(0.5 if i % 2 == 0 else -0.5) for i in range(200)]
    v[80] = 2.0                                          # an OLD episode that looks like today's
    v[140] = 1.0                                         # a RECENT episode, much smaller
    v[199] = 2.0                                         # today: the same reading as the OLD one
    return v, d


def test_B9_the_LIKE_crossing_is_selected_even_when_an_UNLIKE_one_is_newer():
    """**RE-ANCHORED AT ROUND 2 ON ONE STATISTIC.** The bar is unchanged and the FIXTURE moved: see
    :func:`_like_fixture` for why a record of zeros with three spikes in it graded the window's
    composition rather than the series' state. The property is the estate's oldest one -- the LIKE
    crossing beats the RECENT unlike one -- and it now holds on the FIXED-WINDOW z ALONE, with no gate
    behind it and no second statistic behind it.

    THAT IS WHAT MAKES IT A BAR AGAIN. At HEAD the newer candidate was DELETED by the sign gate, so the
    bar measured a gate; at R3a round 1 it was outranked by a PREFIX percentile whose reference
    population grows along the record, so the bar measured a statistic that is not comparable with
    itself. Here the newer candidate is IN the pool, carries a distance, is ranked against the older one
    and LOSES -- 1.51 sigma against 0.09 -- which is the only form of this bar a reader can check."""
    v, d = _like_fixture()
    st = _row(v, d, window=60)
    h = A.state_history(st, want_pct=True)
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"])}]
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=parse_lag(B9_BAND), analog_k=1)
    assert sel["declined"] is None
    picked = sel["picked"][0]["date"]
    assert picked == d[80], f"the older LIKE crossing must win, got {picked}"
    # THE NEWER CANDIDATE IS IN THE POOL AND IS OUTRANKED -- not gated, not deleted, not unobservable.
    lk_old = A.likeness(d[80], dims)
    lk_new = A.likeness(d[140], dims)
    assert lk_old is not None and lk_new is not None
    assert lk_old["distance"] < lk_new["distance"]
    assert lk_old["distance"] < 0.2 and lk_new["distance"] > 1.0
    # AND THE PERCENTILE, WHICH NO LONGER RANKS, IS STILL READ AND STILL PRINTED beside it.
    assert "percentile" in A.likeness(
        d[80], [{**dims[0], "pct_now": 99.5}])["per_dim"][0]["observed"]


def test_B9_the_count_in_words_is_the_pool_the_header_describes_and_one_match_still_renders():
    v, d = _like_fixture()
    st = _row(v, d, window=60)
    h = A.state_history(st, want_pct=True)
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


def test_R3a_the_SIGN_GATE_IS_GONE_and_the_disagreement_is_a_RETURNED_FACT():
    """**RE-ANCHORED AT R3a. THE CAUSE: STATS GRADE, NEVER GATE** (owner doctrine 2026-09-17). This deck
    used to require ``no_like_state`` on a record whose every observable past state sits on the other
    side of zero -- the gate needed sign agreement on at least half the dimensions. The estate's own
    measurement is why it went: the analog leg declined on FIVE OF FIVE 2026-09-16 smoke turns, and the
    reader was handed "no past state on this series is like the present one" beside two windows the
    cascade leg printed anyway. A gate that removes the stanza is replaced by a word the reader can
    weigh, so the SAME fixture now yields a STANZA whose sign disagreement is printed: ``sign_agree`` of
    ``sign_seen``. Nothing about the arithmetic softened -- the distance is unchanged and large, and it
    is the distance's job to rank this candidate last."""
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
    assert sel["declined"] is None, "the sign gate is struck: a leaning pool still yields a stanza"
    p = sel["picked"][0]
    assert p["sign_seen"] == 1 and p["sign_agree"] == 0          # and the reader is TOLD it leans
    assert p["distance"] == pytest.approx(3.0)                   # |-1.0 - 2.0|, unchanged arithmetic


def test_R3a_COVERAGE_IS_A_PRINTED_FACT_and_never_the_filter_it_used_to_be():
    """**RE-ANCHORED AT R3a. THE CAUSE: a fence CORRECTS or COMPUTES, never deletes.** The struck rule
    was ``like['dims_seen'] < len(dims)`` -> skip, and its measured motivation was real -- the
    scenario-3 stanza printed "the series sat like this in May 2001" one line under "the loud set
    reaches back to 2006". The remedy was a DELETION where a SENTENCE was owed. What answers it now is
    ``record_span`` (the first date each dimension's own record could be read on) and ``precedes_dims``
    (how many of them a picked date precedes), so the header states the contradiction instead of the
    selector hiding it."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for base in (80, 160, 188):
        for i in range(base, base + 12):
            v[i] = 0.10 * (i - base + 1)
    st = _row(v, d, window=B9_WINDOW)
    h = A.state_history(st, want_pct=True)
    # A dimension whose own record starts at index 150: nothing before it is observable on BOTH.
    short = {"dates": d[150:], "values": v[150:], "z": [0.4] * 50, "pct": [None] * 50, "window": 12}
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"])},
            {"id": "late", "hist": short, "z_now": 0.4}]
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=parse_lag(B9_BAND), analog_k=3)
    assert sel["picked"]
    old = [p for p in sel["picked"] if p["date"] < d[150]]
    assert old, "a date before the second dimension's record is REACHABLE now, and that is the point"
    for p in old:
        assert p["dims_seen"] == 1 and p["dims_declared"] == 2       # the coverage, as a FACT
        assert p["precedes_dims"] == 1                               # and the header's correction
    span = {r["id"]: r["first_date"] for r in sel["record_span"]}
    assert span["late"] == d[150] and span["oni"] < d[150]


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


def test_R2_an_UNOBSERVED_dimension_counts_a_FULL_SIGMA_apart_and_the_COUNT_RIDES_BESIDE_IT():
    """**RE-ANCHORED AT ROUND 2: UNKNOWN IS FAR** (orchestrator ruling). R3a divided by the OBSERVED
    count, which was the honest scope of the figure and the wrong ORDERING: the oldest stretch of every
    record is where the fewest dimensions have warmed up, so a candidate readable on two of five competed
    on a two-dimension average and the relaxation bought an ANTIQUITY bias where it meant to remove a
    recency one. An unread dimension is now charged ``UNOBSERVED_SIGMA`` and the denominator is the
    DECLARED count again -- a RANK RULE, printed, and never a filter: the candidate stays in the pool and
    the row carries ``dims_seen`` / ``dims_unread`` so the stanza says what it cost."""
    d = _months(10)
    seen = {"dates": d, "values": [0.0] * 10, "z": [1.0] * 10, "pct": [None] * 10, "window": 5}
    blind = {"dates": d, "values": [0.0] * 10, "z": [None] * 10, "pct": [None] * 10, "window": 5}
    got = A.likeness(d[5], [{"id": "a", "hist": seen, "z_now": 3.0},
                            {"id": "b", "hist": seen, "z_now": 2.0},
                            {"id": "c", "hist": blind, "z_now": 1.0}])
    assert got["dims_seen"] == 2 and got["dims_declared"] == 3 and got["dims_unread"] == 1
    assert got["unread_sigma"] == A.UNOBSERVED_SIGMA
    assert got["distance"] == pytest.approx((2.0 + 1.0 + A.UNOBSERVED_SIGMA) / 3.0)
    # THE BLIND DIMENSION IS NOT SILENTLY DROPPED: it is enumerated with what it could and could not be
    # read on, which is what a coverage sentence is built from.
    per = {r["id"]: r for r in got["per_dim"]}
    assert "z" not in per["c"]["observed"] and "gap" not in per["c"]
    assert "z" in per["a"]["observed"]


def test_R2_a_2_of_5_candidate_at_0_04_RANKS_BELOW_a_5_of_5_candidate_at_0_3():
    """THE ORCHESTRATOR'S OWN PIN for the early-date rule, and it is the case the fixture boards
    MEASURED: ``b40_event / ending_stocks`` moved from 2020-10-31 to 1992-09-30 on a candidate observable
    on two of five dimensions with a distance of 0.0412. Two observed gaps averaging 0.04 buy
    ``(0.08 + 3 x 1.0) / 5 = 0.616``; five observed gaps of 0.3 buy ``1.5 / 5 = 0.3``. The thin candidate
    is still SELECTABLE -- it is in the pool, it carries a distance, the stanza would print its coverage
    -- and it does not outrank the candidate the board could actually read."""
    d = _months(20)
    flat = [0.0] * 20

    def _dim(i, z_at, z_now, blind=False):
        h = {"dates": d, "values": flat, "z": [None] * 20, "pct": [None] * 20, "window": 5}
        if not blind:
            h["z"][5] = z_at                             # the THIN date: only two dimensions read it
            h["z"][10] = 0.0                             # the FULL date: every dimension reads it
        else:
            h["z"][10] = 0.0
        return {"id": "d%d" % i, "hist": h, "z_now": z_now}

    dims = [_dim(1, 0.04, 0.0), _dim(2, 0.04, 0.0),
            _dim(3, 0.0, 0.3, blind=True), _dim(4, 0.0, 0.3, blind=True),
            _dim(5, 0.0, 0.3, blind=True)]
    thin = A.likeness(d[5], dims)
    full = A.likeness(d[10], dims)
    assert (thin["dims_seen"], thin["dims_declared"], thin["dims_unread"]) == (2, 5, 3)
    assert (full["dims_seen"], full["dims_unread"]) == (5, 0)
    assert thin["distance"] == pytest.approx((0.04 + 0.04 + 3.0) / 5.0)
    assert full["distance"] == pytest.approx((0.0 + 0.0 + 0.3 + 0.3 + 0.3) / 5.0)
    assert thin["distance"] > full["distance"], "unknown is FAR: the 2-of-5 date ranks below"
    # ON THE STRUCK RULE THE THIN DATE WOULD HAVE WON -- the bar is a measurement of the correction.
    assert (0.08 / 2.0) < full["distance"]


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
YM_CARDS: dict = {"silver_noaa_oni": 36, "silver_noaa_iod": 45, "gold_weather_z": 5}


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


def test_the_accessor_reads_the_METRICS_lag_and_not_just_the_cards(monkeypatch):
    """S7-W (2026-09-11). ``gold_weather_z`` carries metrics fed by TWO sources ~20 days apart in
    release cadence, so ONE lag on this axis has to be wrong for four metrics or wrong for the fifth.
    (The CHIRPS number was corrected 45 -> 25 the same day: the two HTTP-HEAD observations behind it
    BOUND the lag -- July's block present at day 22 past month-end is an upper bound, August absent at
    day 11 is a lower one -- so 11 < lag <= 22, and 25 is that upper bound plus a 3-day margin.)

    THE ROW'S OWN STAMP IS THE DEFAULT, NOT THE ANSWER. ``feeders._recency`` writes the CARD's value
    onto every row, so a per-metric read that only consulted the row would be the card-level read with
    extra steps; the accessor passes the stamp to ``registry.metric_lag_override`` as the fallback and
    lets a declared metric override win. That ordering is what keeps every OTHER card, every fixture
    row, and every unresolvable table byte-identical -- graded below."""
    st = _ym_state(_ym_labels(24), [float(i % 5) for i in range(24)], lag=5)
    st.table = "gold_weather_z"
    row = B.NodeRow(contract="c", driver_id="d", state=st)
    for metric, want in (("drought_z", 25), ("drought_z_tail_share", 25), ("drought_z_cells", 25),
                         ("tmax_anomaly", 5), ("gdd_z", 5), ("heat_stress_z", 5),
                         ("frost_event_flag", 5), ("frost_event_share", 5)):
        st.metric = metric
        assert A._lag_days_of(row) == want, metric

    # the three fall-throughs, each of which keeps a caller reading exactly what it read before
    st.metric = "a_metric_the_card_never_declared"
    assert A._lag_days_of(row) == 5, "an unnamed metric takes the card default"
    st.table = "a_table_the_registry_never_had"
    assert A._lag_days_of(row) == 5, "an unresolvable table falls back to the row's own stamp"
    st.table, st.metric = "gold_weather_z", "drought_z"
    st.recency = {**st.recency, "ym_publication_lag_days": None, "publication_lag_days": 6}
    assert A._lag_days_of(row) == 25, "the registry still answers when the row carries no ym stamp"


def test_the_per_metric_lag_LEAVES_the_knowledge_axis_WHERE_IT_WAS_for_both_sources():
    """THE MEASURED EFFECT, on the axis the 2026-09-07 board census actually read, RE-MEASURED after
    the CHIRPS lag was corrected 45 -> 25 (2026-09-11 verify pass).

    The census banked ``history_n = 131`` for the ``drought`` / ``flash_drought`` analog seeds on eight
    boards, and the gold bytes tip at data month 2026-07 -- so the axis is the 131 monthly labels
    2015-09 .. 2026-07. Re-indexing it under the old blanket 7 and the two DECLARED values:

      * 7 -> 5  (NASA)  : **0 of 131** positions move; admissible set unchanged at 131.
      * 7 -> 25 (CHIRPS): **0 of 131** positions move; admissible set unchanged at 131, still ending
        at 2026-07.

    WHY BOTH ARE ZERO, and the precise form of a claim this deck used to state too widely. Every
    position on THIS axis is a month END, and the knowable index at position P is the newest label
    whose month-end plus the lag is <= P. Consecutive month-ends are 28-31 days apart, so any lag up
    to 28 admits exactly the prior month and the map is one step wide across that whole band. The
    band is NOT a general property of the lag arithmetic: ``query._ym_lagged_asof_ym`` is evaluated at
    an ARBITRARY calendar as-of, and there 5 and 7 place different months on 24 days of 2026 (see
    tests/unit/test_state_registry_ym_lag.py). Month-end positions, one step; any day of the month,
    not. Stating which one is being measured is the whole correction.

    AND THE COUNTERFACTUAL IS KEPT, because it is what the wave believed for half a day: under the
    misread 45, **130 of 131** positions move back a month, the head gains a second hole, and 2026-07
    stops being an admissible candidate at the census as-of (131 -> 130). So the size of this
    correction is not cosmetic -- 45 would have re-scored every drought crossing on the board against
    a month block it did not need to withhold, and 25 is measured to re-score none of them."""
    d = _ym_labels(131, 2015, 9)
    assert d[0] == "2015-09" and d[-1] == "2026-07" and len(d) == 131

    i7, i5, i25, i45 = (A._knowable_indices(d, n) for n in (7, 5, 25, 45))
    assert i7 == i5, "the NASA default is the old blanket number on a month-END axis"
    assert i7 == i25, "and so is the corrected CHIRPS number -- 25 is inside the 28-day step"
    assert i7.count(None) == i25.count(None) == 1
    # the counterfactual: the misread 45 crosses the step and moves almost the whole axis
    assert sum(1 for a, b in zip(i7, i45) if a != b) == 130 and i45.count(None) == 2

    asof = "2026-09-07"                                   # the census as-of these seeds were read at
    admissible = {lag: [x for x in d if A._add_days(A.axis_date(x), lag) <= asof]
                  for lag in (7, 5, 25, 45)}
    assert len(admissible[7]) == len(admissible[5]) == len(admissible[25]) == 131
    assert admissible[7][-1] == admissible[25][-1] == "2026-07"
    assert len(admissible[45]) == 130 and admissible[45][-1] == "2026-06"


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


# ===================================================================================================
# LANE R3a -- THE ANALOG RELAXATION, SELECTION HALF (DESIGN sec C, owner doctrine 2026-09-17)
#
# THE DOCTRINE THESE BARS EXIST TO HOLD: **STATS GRADE, NEVER GATE.** The only hard filters left in the
# selection are POINT-IN-TIME (the outcome window has closed; the candidate was knowable at t) and
# EXISTENCE (some dimension carries a readable state at t). Coverage and sign agreement are PRINTED
# FACTS. Recency stays THIRD in the tie-break. No decline word is added. Every bar below is one of
# those five sentences made mechanical.
# ===================================================================================================
R3a_BAND = "4-8 quarters"


def _episodes(n=200, bases=(80, 140, 188), length=12, step=0.10, start_year=2010):
    """A monthly record of flat stretches interrupted by rising episodes -- the shape every bar below
    reads, stated rather than generated so the candidate set is countable by hand."""
    d = _months(n, start_year, 1)
    v = [0.0] * n
    for b in bases:
        for i in range(b, min(b + length, n)):
            v[i] = step * (i - b + 1)
    return v, d


# -- (1) THE CANDIDATE RULE: ANY MONTH, ONE PER EPISODE ----------------------------------------------
def test_R3a_a_run_of_LIKE_MONTHS_yields_ONE_candidate_AT_ITS_START():
    """"candidates from ANY month, deduplicated per EPISODE" (owner). The dedup IS the episode: a
    twelve-month rise contributes its START and not its twelve months, which is the property the old
    crossing rule bought with a run FLOOR and this one buys with the dedup alone."""
    v, d = _episodes(bases=(80, 140, 188))
    h = _hand_hist(d, v, [None] * 200)
    got = A.crossings(h, any_month=True)
    assert all(c["kind"] == "episode_start" for c in got)
    dates = [c["date"] for c in got]
    assert d[80] in dates and d[140] in dates and d[188] in dates
    # ONE per episode: the eleven months INSIDE each rise are not candidates of their own.
    for b in (80, 140, 188):
        assert not [c for c in got if b < c["index"] < b + 12]


def test_R3a_the_run_FLOOR_is_GONE_and_a_SHORT_episode_is_a_candidate_again():
    """THE RULE DESIGN C.1 DROPS. ``min_run=run_now`` denied any episode shorter than the one the series
    is in now -- a frequency floor, and frequency floors deny the tail. The run length does not leave
    the selection: it is the second term of the tie-break, where it GRADES."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for i in range(80, 83):                              # a THREE-month episode
        v[i] = 0.10 * (i - 79)
    for i in range(188, 200):                            # against a TWELVE-month present run
        v[i] = 0.10 * (i - 187)
    h = _hand_hist(d, v, [None] * 200)
    run_now = A._run_at(h, 199)
    assert run_now == 12
    assert not [c for c in A.crossings(h, min_run=run_now) if c["index"] == 80]   # the OLD rule
    assert [c for c in A.crossings(h, any_month=True) if c["index"] == 80]        # the NEW one


def test_R3a_a_FLAT_record_still_offers_a_candidate_and_the_old_rule_offered_NONE():
    """"any month" means the record whose only structure is a flat stretch is not silent. The old rule
    minted a candidate only where the DIRECTION changed, so a series that never turned had no date to
    offer at all."""
    d = _months(60, 2010, 1)
    h = _hand_hist(d, [1.0] * 60, [None] * 60)
    assert A.crossings(h, min_run=1) == []
    got = A.crossings(h, any_month=True)
    assert len(got) == 1 and got[0]["index"] == 1        # index 0 has no preceding observation


def test_R3a_a_DECLARED_band_crossing_is_kept_EXACTLY_as_it_was():
    """"the convention-band crossings kept as they are" -- a desk line is the one candidate rule the
    desk itself wrote, and the relaxation does not touch it."""
    d = _months(40)
    v = [0.1] * 20 + [0.9] * 20
    h = _hand_hist(d, v, [None] * 40)
    conv = {"kind": "abs_bands", "bands": [0.5]}
    old = A.crossings(h, convention=conv, min_run=99)
    new = [c for c in A.crossings(h, convention=conv, any_month=True)
           if c["kind"] == "band_crossing"]
    assert [(c["index"], c["kind"], c["band"]) for c in old] == \
           [(c["index"], c["kind"], c["band"]) for c in new]


# -- (2) LIKENESS: THE WIDENED VECTOR, AND EVERY COUNT A FACT -----------------------------------------
def test_R2_a_PREFIX_percentile_is_READ_and_PRINTED_and_does_NOT_rank():
    """**RE-ANCHORED AT ROUND 2, MAJOR 1: EVERY DISTANCE COMPONENT IS ONE STATISTIC ACROSS THE RECORD.**
    R3a widened the vector so a dimension inside its rolling warm-up could be OBSERVED on its prefix
    percentile -- and the price was that the distance then compared a rank against 33 observations with a
    rank against 440, because ``_prefix_percentiles``' reference population GROWS along the record. The
    measured cost is in the flagship: ``b40_event / ending_stocks`` moved from 2020-10-31 to 1992-09-30
    (index 32, population 33) on a candidate carrying no z at all.

    THE PERCENTILE DID NOT LEAVE THE STATE VECTOR -- it left :data:`A.DISTANCE_COMPONENTS`. It is still
    computed for every seed, still returned in ``observed``, still carried as ``pct_gap`` for the stanza
    to print. What it no longer does is decide which date the reader is shown."""
    v, d = _episodes(bases=(20, 188))
    st = _row(v, d, window=60)
    h = A.state_history(st, want_pct=True)
    assert h["z"][20] is None and h["pct"][20] is not None
    dim = {"id": "oni", "hist": h, "z_now": float(st.z["value"]), "pct_now": 99.0}
    # THE DATE IS UNOBSERVABLE FOR THE RANK: no dimension carries a DISTANCE component there.
    assert A.likeness(d[20], [dim]) is None
    # ...and the same reading is READ where the z can be read, and printed beside the gap that ranks.
    lk = A.likeness(d[188], [dim])
    assert lk is not None and lk["dims_seen"] == 1
    per = lk["per_dim"][0]
    assert "percentile" in per["observed"] and "z" in per["observed"]
    assert per["pct_gap"] == pytest.approx(abs(A._pct_to_z(h["pct"][188]) - A._pct_to_z(99.0)))
    assert per["gap"] == pytest.approx(abs(h["z"][188] - float(st.z["value"]))), \
        "the per-dimension GAP is the mean of the DISTANCE components, which is the z alone"


def test_R2_the_percentile_GAP_is_stated_on_the_z_axis_and_is_NOT_a_term_of_the_distance():
    """**RE-ANCHORED AT ROUND 2.** A percentile IS a z read off the same distribution, so the conversion
    is ``NormalDist().inv_cdf`` and not a constant somebody picked (sec 14: no weights) -- and the
    conversion stays, because printing a gap in percentage POINTS beside a distance in sigmas invites the
    reader to add them. What went is the gap's membership of the MEAN: the distance is the z alone, and
    the percentile gap rides ``per_dim[].pct_gap`` as a fact."""
    from statistics import NormalDist
    assert A._pct_to_z(50.0) == pytest.approx(0.0)
    assert A._pct_to_z(97.5) == pytest.approx(NormalDist().inv_cdf(0.975))
    assert A._pct_to_z(100.0) == pytest.approx(NormalDist().inv_cdf(1.0 - A._PCT_EPS))  # clamped
    assert A._pct_to_z(None) is None and A._pct_to_z("") is None
    d = _months(10)
    h = {"dates": d, "values": [0.0] * 10, "z": [1.0] * 10, "pct": [97.5] * 10, "window": 5}
    got = A.likeness(d[5], [{"id": "a", "hist": h, "z_now": 2.0, "pct_now": 50.0}])
    assert got["distance"] == pytest.approx(1.0), "the distance is |z_t - z_now| and nothing else"
    assert got["per_dim"][0]["pct_gap"] == pytest.approx(NormalDist().inv_cdf(0.975))
    # AND A DIMENSION READABLE ONLY ON ITS PERCENTILE IS AN UNREAD DIMENSION FOR THE RANK.
    p_only = {"dates": d, "values": [0.0] * 10, "z": [None] * 10, "pct": [97.5] * 10, "window": 5}
    assert A.likeness(d[5], [{"id": "a", "hist": p_only, "z_now": 2.0, "pct_now": 50.0}]) is None


def test_R2_a_FIRED_row_ALWAYS_CARRIES_A_READABLE_SIGMA_so_sign_0_of_0_CANNOT_BE_PRINTED():
    """**THE ROUND-2 RULING RETIRED A SENTENCE THE RENDER HALF WAS OWED** (HANDOFF item 2). While the
    prefix percentile ranked, a candidate could be picked with NO z readable on any dimension, and the
    stanza's lean clause then read "agreed in sign on none of none" -- measured at round 1 on SIX of the
    23 fixture stanzas. With the distance back to the z alone the branch is UNREACHABLE by construction:
    ``sign_seen`` counts exactly the dimensions that carry both ``z_t`` and ``z_now``, which is exactly
    what puts a number in ``parts``, and :func:`A.likeness` returns ``None`` when ``parts`` was never
    filled. Measured on the same three boards after the ruling: ZERO of 23.

    IT IS PINNED AS AN INVARIANT AND NOT AS A COUNT, because the render half needs to know the branch is
    dead rather than merely empty today: every date of a mixed-observability record is walked, and the
    two facts are graded together on each."""
    d = _months(60, 2010, 1)
    flat = [0.0] * 60
    z_all = [0.5] * 60
    z_odd = [None if i % 2 else 1.0 for i in range(60)]
    dims = [{"id": "z_only", "hist": {"dates": d, "values": flat, "z": z_all,
                                      "pct": [None] * 60, "window": 5}, "z_now": 0.4},
            {"id": "pct_only", "hist": {"dates": d, "values": flat, "z": [None] * 60,
                                        "pct": [70.0] * 60, "window": 5},
             "z_now": 0.4, "pct_now": 55.0},
            {"id": "z_odd", "hist": {"dates": d, "values": flat, "z": z_odd,
                                     "pct": [None] * 60, "window": 5}, "z_now": -0.4}]
    fired = 0
    for dt in d:
        got = A.likeness(dt, dims)
        if got is None:
            continue
        fired += 1
        assert got["dims_seen"] >= 1
        assert got["sign_seen"] >= 1, "a distance is a z, so a fired row has a sigma to lean on"
        assert got["sign_seen"] == got["dims_seen"]
    assert fired == 60, "the bar must fire on every date here or it grades an empty walk"
    # AND THE SAME HOLDS THROUGH THE SELECTOR, which is the object the stanza is built from.
    seed = dims[0]["hist"]
    sel = A.select_analogs(seed, dims=dims, asof=ASOF, band=parse_lag(R3a_BAND), analog_k=3)
    assert sel["picked"], "a non-vacuous selection or this half of the bar grades nothing"
    assert all(p["sign_seen"] >= 1 for p in sel["picked"])
    # ...while a dimension readable ONLY on the components that do not rank is still ENUMERATED, so the
    # coverage sentence can name it: it is unread for the distance and observed for the reader.
    per = {r["id"]: r for r in sel["picked"][0]["per_dim"]}
    assert "percentile" in per["pct_only"]["observed"] and "gap" not in per["pct_only"]


def test_R3a_a_candidate_observable_on_THREE_OF_FIVE_with_TWO_SIGN_DISAGREEMENTS_IS_PICKED():
    """THE BAR THE OWNER STATED. Three of five dimensions readable at ``t``, sign agreement on ONE of
    those three -- under HEAD both the all-dimensions filter AND the sign gate deleted it, and the two
    of them are why the leg declined on five of five smoke turns. It is now a stanza whose coverage and
    whose lean are NUMBERS: 3 of 5 observed, 1 of 3 agreeing."""
    v, d = _episodes(bases=(80, 188))
    seed = _hand_hist(d, v, [None] * 200)
    seed["z"][80] = 1.0                                  # exactly one admissible candidate date
    flat = [0.0] * 200

    def _dim(i, z_at_80, z_now):
        h = _hand_hist(d, flat, [None] * 200)
        h["z"][80] = z_at_80
        return {"id": "dim%d" % i, "hist": h, "z_now": z_now}

    dims = [{"id": "seed", "hist": seed, "z_now": 1.0},   # observed, AGREES in sign
            _dim(2, -1.0, 2.0),                           # observed, DISAGREES
            _dim(3, -0.5, 1.5),                           # observed, DISAGREES
            {"id": "blind4", "hist": _hand_hist(d, flat, [None] * 200), "z_now": 0.9},
            {"id": "blind5", "hist": _hand_hist(d, flat, [None] * 200), "z_now": 0.9}]
    sel = A.select_analogs(seed, dims=dims, asof=ASOF, band=parse_lag(R3a_BAND), analog_k=1)
    assert sel["declined"] is None
    p = sel["picked"][0]
    assert p["date"] == d[80]
    assert (p["dims_seen"], p["dims_declared"]) == (3, 5)
    assert (p["sign_agree"], p["sign_seen"]) == (1, 3)


def test_R3a_likeness_declines_ONLY_on_EXISTENCE_and_says_so_through_the_one_word():
    """The one filter beside the two PIT ones. A distance against nothing is not a distance -- but a
    record that offered candidates and could be read on NONE of them still returns the SAME closed word
    (``no_like_state``) with the finer reason on ``detail``."""
    v, d = _episodes(bases=(80, 188))
    seed = _hand_hist(d, v, [None] * 200)                # no z anywhere, no pct anywhere
    sel = A.select_analogs(seed, dims=[{"id": "seed", "hist": seed, "z_now": 1.0}],
                           asof=ASOF, band=parse_lag(R3a_BAND), analog_k=1)
    assert sel["declined"] == "no_like_state" and sel["detail"] == "unobservable"
    assert sel["n_candidates"] == 0 and sel["n_candidates_pit"] > 0


# -- (3) THE TWO PIT FILTERS, UNCHANGED --------------------------------------------------------------
def test_R3a_PIT_ONE_a_candidate_whose_OUTCOME_WINDOW_IS_STILL_OPEN_is_never_picked():
    """KEPT EXACTLY (R2). A like state whose consequence has not happened yet is not evidence, and
    widening the candidate pool does not widen this. Measured on the pool itself: the newest episode
    survives the CANDIDATE rule and is struck by the WINDOW."""
    v, d = _episodes(bases=(80, 188))
    st = _row(v, d, window=60)
    h = A.state_history(st, want_pct=True)
    raw = {c["index"] for c in A.crossings(h, any_month=True)}
    assert 188 in raw, "the fixture must offer the open-window candidate or the bar is vacuous"
    sel = A.select_analogs(h, dims=[{"id": "oni", "hist": h, "z_now": float(st.z["value"])}],
                           asof=ASOF, band=parse_lag(R3a_BAND), analog_k=5)
    assert sel["n_candidates_raw"] > sel["n_candidates_pit"]
    assert d[188] not in [p["date"] for p in sel["picked"]]
    assert all(p["date"] < d[188] for p in sel["picked"])


def test_R3a_PIT_TWO_a_candidate_NOT_KNOWABLE_AT_t_is_never_picked():
    """KEPT EXACTLY (R2). The prefix stops at ``t - lag_days``, and a crossing dated by a card published
    later is admitted only from the day it was READABLE. ``silver_noaa_oni`` declares 36 days."""
    v, d = _episodes(n=200, bases=(80, 196), start_year=2010)
    st = _row(v, d, window=60)
    h = A.state_history(st, want_pct=True)
    asof = A._add_days(d[196], 5)                        # five days after the episode's own date
    # A **ZERO-QUARTER** BAND ISOLATES THE SECOND PIT FILTER, and it has to: any band with a quarter in
    # it closes its window at least ninety-two days after the state's own date, which is longer than any
    # publication lag the estate declares, so the WINDOW filter would subsume the KNOWABILITY one and
    # the bar would be measuring the first rule twice. With ``max_q = 0`` the window closes on the
    # state's own month end and the only thing that can strike this candidate is its lag.
    zero_q = LagBand("zero quarters", "band", 0, 0)
    kw = dict(dims=[{"id": "oni", "hist": h, "z_now": 1.0}], asof=asof, band=zero_q, analog_k=9)
    free = A.select_analogs(h, lag_days=0, **kw)
    lagged = A.select_analogs(h, lag_days=36, **kw)
    assert d[196] in [c["date"] for c in A.crossings(h, any_month=True)]
    assert d[196] in [p["date"] for p in free["picked"]]          # knowable at t with no lag declared
    assert lagged["n_candidates_pit"] < free["n_candidates_pit"]
    assert d[196] not in [p["date"] for p in lagged["picked"]]    # and struck once the card declares one
    assert all(A._add_days(p["date"], 36) <= asof for p in lagged["picked"])


# -- (4) THE TIE-BREAK: DISTANCE, RUN DIFFERENCE, THEN RECENCY ---------------------------------------
def test_R3a_recency_stays_THIRD_and_the_RUN_DIFFERENCE_breaks_an_equal_distance_first():
    """BAR B9 UNDER THE WIDENED POOL (DESIGN C.4's first threat). Two candidates at the SAME distance:
    the one whose run length is closer to the present run wins, and the NEWER one loses -- so the pool
    is ordered by likeness with recency reading third, never by recency wearing a likeness name.

    THE TWO CANDIDATES ARE BAND CROSSINGS BY CONSTRUCTION, and that is a statement about the shipped
    tie-break rather than about this fixture: ``_run_at`` at an EPISODE START is always 1 (the direction
    has just turned), so the run term can only discriminate a crossing that lands mid-run. It is HEAD's
    property, not this lane's change, and it is recorded in this lane's report and its handoff."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for i in range(60, 66):                              # OLD: a six-step climb through the 0.5 line
        v[i] = 0.1 * (i - 59)
    v[120] = 0.6                                         # NEW: one step through the same line
    v[199] = 0.6                                         # the present run is ONE step long
    z = [None] * 200
    z[64] = z[120] = 1.0                                 # the two crossings are EQUIDISTANT
    h = _hand_hist(d, v, z)
    conv = {"kind": "abs_bands", "bands": [0.5]}
    xs = {c["index"] for c in A.crossings(h, convention=conv, any_month=True)
          if c["kind"] == "band_crossing"}
    # 0.5 IS past the 0.5 line (`_past_line`), so the old climb crosses at 64 and not 65; the present
    # step across the line at 199 is a crossing too and is struck by the OUTCOME WINDOW, which leaves
    # exactly the two the tie-break is being measured on.
    assert xs == {64, 120, 199}
    assert A._run_at(h, 64) == 5 and A._run_at(h, 120) == 1 and A._run_at(h, 199) == 1
    sel = A.select_analogs(h, dims=[{"id": "oni", "hist": h, "z_now": 1.0}], asof=ASOF,
                           band=parse_lag(R3a_BAND), analog_k=1, convention=conv)
    top = sel["picked"][0]
    assert top["distance"] == pytest.approx(0.0)
    assert top["date"] == d[120] and top["run_length"] == 1 and top["run_now"] == 1


def test_R3a_and_when_the_RUN_LENGTHS_TIE_TOO_the_newer_wins_and_only_then():
    """The third term, and it fires only after the first two have tied -- bar B9's own rule, re-read
    through the relaxed pool so the ordering is pinned where the pool is widest."""
    v, d = _episodes(bases=(80, 140, 188))
    z = [None] * 200
    z[80] = z[140] = 1.0
    h = _hand_hist(d, v, z)
    sel = A.select_analogs(h, dims=[{"id": "oni", "hist": h, "z_now": 1.0}], asof=ASOF,
                           band=parse_lag(R3a_BAND), analog_k=1)
    assert A._run_at(h, 80) == A._run_at(h, 140), "the run term must TIE or this bar reads term two"
    assert sel["picked"][0]["date"] == d[140]


def test_R3a_ONE_candidate_still_yields_ONE_stanza():
    """Frequency floors deny the tail (house doctrine). A record that offers exactly one admissible
    like state renders it, and the count that rides the header is one."""
    v, d = _episodes(bases=(80, 188))
    seed = _hand_hist(d, v, [None] * 200)
    seed["z"][80] = 1.0
    sel = A.select_analogs(seed, dims=[{"id": "seed", "hist": seed, "z_now": 1.0}],
                           asof=ASOF, band=parse_lag(R3a_BAND), analog_k=5)
    assert sel["n_candidates"] == 1 and len(sel["picked"]) == 1


def test_R3a_min_separation_still_binds_and_it_binds_PER_EPISODE():
    """KEPT, and per EPISODE because a candidate is now an episode's own START. It runs over the
    DISTANCE-ordered list, so the member of an episode that survives is its most-like one -- which is
    why the rule lives here and not in ``crossings``, where a date-ordered pass would delete the
    most-like candidate whenever likeness and recency disagree."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for base in (100, 104, 188):                         # two episodes FOUR months apart
        for i in range(base, base + 3):
            v[i] = 0.10 * (i - base + 1)
    z = [None] * 200
    z[100] = 1.0
    z[104] = 1.05
    h = _hand_hist(d, v, z)
    kw = dict(dims=[{"id": "oni", "hist": h, "z_now": 1.0}], asof=ASOF,
              band=parse_lag(R3a_BAND), analog_k=5)
    assert len(A.select_analogs(h, min_separation_months=12, **kw)["picked"]) == 1
    both = A.select_analogs(h, min_separation_months=1, **kw)["picked"]
    assert [p["date"] for p in both] == [d[100], d[104]]  # the MOST-LIKE member leads


# -- (5) THE LINT-FACING GUARD: near_asof IS A FLAG, NEVER A FILTER ----------------------------------
def test_R3a_near_asof_is_STAMPED_on_a_date_inside_the_separation_window_and_the_date_still_rides():
    """DESIGN C.4's own mitigation for bar B9, and the word in the spec is FLAG. A widened pool whose
    tie fell to the date term could hand the reader "the series sat like this" about a date inside the
    separation window of today -- the present state described as its own precedent. The selection SAYS
    SO and the render half grades it; a filter here would be the deletion this whole lane removes."""
    v, d = _episodes(n=120, bases=(60, 110), start_year=2016)
    seed = _hand_hist(d, v, [None] * 120)
    seed["z"][60] = seed["z"][110] = 1.0
    asof = d[113]                                        # three months past the newer episode's start
    kw = dict(dims=[{"id": "oni", "hist": seed, "z_now": 1.0}], asof=asof,
              band=parse_lag("0-1 quarters"), analog_k=5, min_separation_months=12)
    picked = {p["date"]: p for p in A.select_analogs(seed, **kw)["picked"]}
    assert d[110] in picked, "near_asof is a FLAG: the date is still selected"
    assert picked[d[110]]["near_asof"] is True
    assert picked[d[60]]["near_asof"] is False


# -- (6) NO NEW DECLINE WORD -------------------------------------------------------------------------
def test_R3a_the_relaxation_adds_NO_WORD_to_the_closed_analog_vocabulary():
    """"Relaxing the rules must not add a sixth orphan" (DESIGN C.4). Every decline this selector can
    produce is ``no_like_state``, which ``board.ANALOG_REASONS`` already declares and
    ``render.ABSENCE_WHY`` already has a sentence for; the finer reason rides a separate ``detail``
    field that is NOT a word of the vocabulary and NOT a colon tail on a stamp, so
    ``board.DETAIL_REASONS`` and lint clause 9 are both untouched."""
    from leviathan.graphrag.state.render import ABSENCE_WHY
    d = _months(60, 2010, 1)
    seen = set()
    # A ONE-POINT RECORD OFFERS NO CANDIDATE AT ALL: index 0 has no preceding observation, so it carries
    # no direction, no run and no delta, and ``crossings`` refuses it under both rules.
    cases = [(_hand_hist(d[:1], [0.0], [None]), "no_candidates"),
             (_hand_hist(d, [float(i % 3) for i in range(60)], [1.0] * 60), "window_open")]
    for h, want in cases:
        sel = A.select_analogs(h, dims=[{"id": "x", "hist": h, "z_now": 1.0}],
                               asof=d[3], band=parse_lag(R3a_BAND), analog_k=1)
        assert sel["declined"] == "no_like_state"
        assert sel["detail"] == want
        seen.add(sel["detail"])
    assert seen == {"no_candidates", "window_open"}
    for w in seen | {"unobservable"}:
        assert w not in B.ANALOG_REASONS, w
        assert w not in ABSENCE_WHY, w
    assert "no_like_state" in B.ANALOG_REASONS and "no_like_state" in ABSENCE_WHY


# -- (7) THE CHAIN-FIRST DIMENSION ORDER -------------------------------------------------------------
def test_R3a_first_dim_leads_the_vector_and_CANNOT_move_the_distance():
    """DESIGN C.2: the stanza is the THEN for the TOP CHAIN, so the dimension the chain's receipt hop
    names leads the vector the coverage line enumerates. The distance is an UNWEIGHTED mean, so a
    reorder is a statement about what the reader is shown first and never about what ranks -- and that
    is pinned rather than asserted."""
    v, d = _episodes(bases=(80, 188))
    seed = _hand_hist(d, v, [None] * 200)
    seed["z"][80] = 1.0
    other = _hand_hist(d, [0.0] * 200, [None] * 200)
    other["z"][80] = 0.4
    dims = [{"id": "seed", "hist": seed, "z_now": 1.0},
            {"id": "hop", "hist": other, "z_now": 0.4}]
    plain = A.select_analogs(seed, dims=dims, asof=ASOF, band=parse_lag(R3a_BAND), analog_k=1)
    led = A.select_analogs(seed, dims=dims, asof=ASOF, band=parse_lag(R3a_BAND), analog_k=1,
                           first_dim="hop")
    assert plain["dims_order"] == ("seed", "hop") and plain["first_dim"] is None
    assert led["dims_order"] == ("hop", "seed") and led["first_dim"] == "hop"
    assert led["picked"][0]["distance"] == pytest.approx(plain["picked"][0]["distance"])
    assert led["picked"][0]["date"] == plain["picked"][0]["date"]
    # A ``first_dim`` this board does not rank is a NO-OP: a chain whose hop the board never ranked
    # must not cost the stanza its selection.
    absent = A.select_analogs(seed, dims=dims, asof=ASOF, band=parse_lag(R3a_BAND), analog_k=1,
                              first_dim="nothing_here")
    assert absent["dims_order"] == ("seed", "hop") and absent["picked"]


# -- (8) THE PRODUCER CARRIES THE FACTS AS DATA, AND RENDERS NOTHING ---------------------------------
def _analog_board(values, dates, *, contract="soybeans_cbot", driver_id="oni_climate"):
    """A one-row board whose single loud row carries a real array -- the smallest thing
    ``analog_rows`` will run on."""
    st = state_from_arrays("oni_climate", values, dates, cadence="monthly", asof=ASOF, unit="degC",
                           narrate_unit="degC", windows={"monthly": 60}, table="silver_noaa_oni",
                           metric="oni_anom", commodity=contract)
    bd = B.Board(asof=ASOF, mode="max", knobs=B.board_knobs_of("max"),
                 anchors=(B.Anchor(contract=contract, source="named", rank=0),))
    row = B.NodeRow(contract=contract, driver_id=driver_id, lag_band=parse_lag(R3a_BAND), state=st,
                    legs={"loud": True})
    bd.rows.append(row)
    bd.order = (row.key,)
    bd.series[st.key.label()] = st
    return bd


def test_R3a_analog_rows_carries_every_printed_fact_ONTO_THE_ROW_and_renders_nothing():
    """THE PRODUCER'S HALF OF THE CONTRACT. The clauses DESIGN C.1 promises the header -- the coverage,
    the sign agreement, the record span, the precedes count, the near-as-of flag and the candidate
    yield -- ride the row as DATA. Nothing here is a sentence: ``render.py`` is not this lane's file."""
    v, d = _episodes(bases=(80, 140, 188))
    bd = _analog_board(v, d)
    rows = A.analog_rows(bd, knobs=bd.knobs)
    assert rows and not rows[0]["declined"]
    want = {"dims_seen", "dims_declared", "sign_agree", "sign_seen", "dir_agree", "dir_seen",
            "run_length", "run_now", "run_gap", "per_dim", "precedes_dims", "near_asof",
            "record_span", "dims_order", "first_dim", "n_candidates", "n_candidates_raw",
            "n_candidates_pit", "n_dropped_unreadable", "detail"}
    assert want <= set(rows[0]), sorted(want - set(rows[0]))
    assert rows[0]["n_candidates_raw"] >= rows[0]["n_candidates_pit"] >= rows[0]["n_candidates"]
    assert all(isinstance(r["first_date"], (str, type(None))) for r in rows[0]["record_span"])


def test_R3a_the_producer_builds_the_PERCENTILE_VECTOR_for_every_seed_now():
    """The producer half of the widened vector: ``want_pct`` used to be lit only where a
    ``percentile_bands`` convention needed a band crossing, so on every other board the percentile
    component of the state vector had no producer and the widening would have been inert."""
    v, d = _episodes(bases=(80, 188))
    bd = _analog_board(v, d)
    rows = A.analog_rows(bd, knobs=bd.knobs, conventions={})     # NO convention declared at all
    assert rows and not rows[0]["declined"]
    assert "percentile" in rows[0]["per_dim"][0]["observed"]


def test_R3a_a_DECLINED_row_carries_the_detail_and_the_yield_counts_too():
    """A decline is where the yield question is ASKED, so the row that says ``no_like_state`` is the one
    that must carry how many candidates the record offered and where they went."""
    d = _months(200, 2010, 1)
    bd = _analog_board([0.0] * 200, d)
    rows = A.analog_rows(bd, knobs=bd.knobs)
    assert rows and rows[0]["declined"] == "no_like_state"
    assert rows[0]["detail"] in ("no_candidates", "window_open", "unobservable")
    assert rows[0]["n_candidates"] == 0
    assert "n_candidates_raw" in rows[0] and "record_span" in rows[0]
    # AND THE FIFTH EXIT IS COUNTED ON A DECLINED ROW TOO (round 3, minor): a decline whose own
    # subtraction is absent is a decline the census cannot close.
    assert rows[0]["n_candidates_pit"] == (rows[0]["n_dropped_unreadable"]
                                           + rows[0]["n_candidates"])


# -- (9) THE FLAG-OFF IDENTITY -----------------------------------------------------------------------
def test_R2_this_module_READS_NO_ENVIRONMENT_and_ITS_CALLERS_ARE_NAMED():
    """**RE-ANCHORED AT ROUND 2, MAJOR 3: THE OLD BAR ASSERTED A FALSE PROPERTY AND COULD NOT FAIL.** It
    claimed that with ``GRAPHRAG_STATE_BOARD`` off this module is never IMPORTED, and enforced it by
    scanning every file under ``state/`` for an unindented line containing the substring
    ``"import analogs"``. ``state/walk.py`` carries
    ``from leviathan.graphrag.state.analogs import axis_date`` at module level, on the serving path, at
    HEAD and today -- and that line does not contain the substring. The claim was wrong and its guard
    could not see the counterexample two files away in its own package: the estate's own standing lesson
    about rules that never fire, committed inside a package about rules that never fire.

    WHAT IS TRUE AND CHECKABLE IS PINNED HERE INSTEAD, and all of it by NAME rather than by substring:

      (1) this module READS NO ENVIRONMENT -- an ``ast`` walk for ``environ`` / ``getenv`` anywhere in
          the tree, which a comment or a docstring cannot satisfy and a renamed import cannot hide;
      (2) its module BODY has no import-time side effect -- only the docstring, imports, constants and
          function definitions -- so an import (``walk.py``'s, or any other) executes nothing and moves
          no rendered byte;
      (3) every CALL SITE of the producer in this package is named, with its enclosing function: the
          SERVING one is ``seam.fill_stage2``, which ``answer.py`` reaches only on a board
          ``fill_stage1`` built under ``_state_board_on()``; the other two are the offline census and
          the offline harness and neither is a serving path.

    **THE THIRD CHECK WALKS THE WHOLE TREE, NOT THE ONE PACKAGE DIRECTORY** (review round 2, minor 2).
    It scanned ``state/*.py`` while claiming to name every caller, so a caller added one directory away
    -- ``answer.py`` itself, a new numbers leg -- would not have failed it: the guard was narrower than
    the claim it defends, which is the class MAJOR 3 was about. The walk is now ``rglob`` over the whole
    of ``src`` and it stays cheap by READING every file (0.26 s over 386) and PARSING only the five that
    contain the producer's name: a call site's own source must contain the token it calls, so the
    pre-filter cannot hide one, while parsing all 386 costs 5.9 s of deck time for the same answer.
    ``utf-8-sig`` rather than ``utf-8`` because the estate carries at least one BOM-headed module and
    ``ast.parse`` refuses U+FEFF -- a bar that raises on an unrelated file grades nothing.

    Together those are the flag-off OUTPUT identity, which is the property the commit needs -- the
    IMPORT identity was never true and was never what the flag buys."""
    import ast
    import pathlib

    def _called(f):
        return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")

    src = pathlib.Path(A.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    env = [n.attr if isinstance(n, ast.Attribute) else n.id for n in ast.walk(tree)
           if (isinstance(n, ast.Attribute) and n.attr in ("environ", "getenv"))
           or (isinstance(n, ast.Name) and n.id in ("environ", "getenv"))]
    assert env == [], "analogs.py must read no environment; the flag is resolved at the answer seam"
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]                                  # the module docstring is not a side effect
    ok = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
          ast.Assign, ast.AnnAssign)
    assert [type(s).__name__ for s in body if not isinstance(s, ok)] == [], \
        "an import-time statement here would execute on a flag-off turn through walk.py's import"
    tree_root = pathlib.Path(A.__file__).parents[3]      # .../src -- the whole tree, not state/
    sites = set()
    for py in sorted(tree_root.rglob("*.py")):
        if py.name == "analogs.py":
            continue
        text = py.read_text(encoding="utf-8-sig")
        if "analog_rows" not in text:                    # a caller's source must carry the name
            continue
        for fn in ast.walk(ast.parse(text)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for c in ast.walk(fn):
                if isinstance(c, ast.Call) and _called(c.func) == "analog_rows":
                    sites.add((py.name, fn.name))
    assert sites == {("seam.py", "fill_stage2"),         # THE serving call, under the board flag
                     ("board_census.py", "board_run"),   # the offline census
                     ("__main__.py", "build_scenario")}, sorted(sites)


def test_R3a_the_declared_STATE_COMPONENTS_are_exactly_what_likeness_can_observe():
    """The two tuples are the contract between this selector and the coverage sentence the render half
    will write, so they are graded against what the code actually produces rather than left as prose. A
    fifth component cannot arrive without moving :data:`STATE_COMPONENTS`, and a component that carries a
    DISTANCE cannot arrive without moving :data:`DISTANCE_COMPONENTS` -- which is the line where a WEIGHT
    would have to be declared."""
    assert A.STATE_COMPONENTS == ("z", "percentile", "direction", "run")
    assert A.DISTANCE_COMPONENTS == ("z",)               # round 2, MAJOR 1: ONE statistic
    assert set(A.COMPONENT_VECTOR) >= set(A.DISTANCE_COMPONENTS)
    d = _months(20)
    h = {"dates": d, "values": [float(i) for i in range(20)], "z": [1.0] * 20,
         "pct": [60.0] * 20, "window": 5}
    got = A.likeness(d[10], [{"id": "a", "hist": h, "z_now": 2.0, "pct_now": 55.0,
                              "dir_now": "up", "run_now": 3}])
    assert set(got["per_dim"][0]["observed"]) == set(A.STATE_COMPONENTS)
    # and a history carrying ONLY the three non-distance components is an UNOBSERVED dimension
    bare = {"dates": d, "values": [float(i) for i in range(20)], "z": [None] * 20,
            "pct": [60.0] * 20, "window": 5}
    assert A.likeness(d[10], [{"id": "a", "hist": bare, "z_now": 2.0, "pct_now": 55.0,
                               "dir_now": "up", "run_now": 3}]) is None


def test_R3a_the_candidate_pool_thinning_COMPUTES_and_is_OFF_by_default():
    """``crossings(min_separation_months=...)`` exists so the other reading of DESIGN C.1 can be
    MEASURED rather than assumed, and it is off everywhere: the survivor of a close pair stamps
    ``n_merged`` instead of the pair vanishing, and ``select_analogs`` passes zero, because a date-ordered
    thinning deletes the most-like member of an episode whenever likeness and recency disagree.

    ``n_merged`` IS PRESENT AND ZERO WITH THE THINNING OFF (round 2, minor 5). It used to exist only when
    the kwarg was passed, so ``c["n_merged"]`` RAISED on the default pool -- a key whose presence depended
    on a knob nobody turns, in a package whose whole subject is that the row says what it did."""
    d = _months(200, 2010, 1)
    v = [0.0] * 200
    for base in (100, 104, 150):
        for i in range(base, base + 3):
            v[i] = 0.10 * (i - base + 1)
    h = _hand_hist(d, v, [None] * 200)
    loose = A.crossings(h, any_month=True)
    tight = A.crossings(h, any_month=True, min_separation_months=12)
    assert len(tight) < len(loose)
    assert sum(int(c.get("n_merged") or 0) for c in tight) == len(loose) - len(tight)
    assert all(c["n_merged"] == 0 for c in loose)         # present, and zero, on the default pool
    # and the SELECTOR leaves it off, so its pool is the unthinned one
    sel = A.select_analogs(h, dims=[{"id": "x", "hist": h, "z_now": 1.0}], asof=ASOF,
                           band=parse_lag(R3a_BAND), analog_k=1)
    assert sel["n_candidates_raw"] == len(loose)


def test_R3a_the_precedes_correction_places_a_year_month_label_on_its_MONTH_END():
    """THE MODULE'S ONE STANDING LESSON, applied to the one new comparison this lane adds. A raw
    ``year_month`` label sorts as the month's FIRST instant, so a bare string compare of ``"2016-12"``
    against ``"2016-12-31"`` calls two names for the SAME month-end a difference -- which is the leak
    ``axis_date`` exists to close and the reason ``_knowable_indices`` had to be re-fixed at S3. The
    correction the header prints goes through the one calendar."""
    span = ({"id": "a", "first_date": "2016-12"}, {"id": "b", "first_date": "2020-06-30"},
            {"id": "c", "first_date": None}, {"id": "d", "first_date": "not a date"})
    assert A._precedes_count(span, "2016-12-31") == 1          # 'a' is the SAME month-end, not later
    assert A._precedes_count(span, "2016-11-30") == 2
    assert A._precedes_count(span, "2026-01-31") == 0
    assert A._precedes_count(span, "") == 0                    # an unplaceable pick corrects nothing


# -- ROUND 2: THE FIVE MAJORS' OWN PINS --------------------------------------------------------------
def _head_n_candidates(seed_hist, dims, *, asof, band, lag_days=0, convention=None, min_run=None):
    """HEAD's ``n_candidates``, RESTATED HERE FROM THE S3 SOURCE (``git show HEAD:state/analogs.py``)
    rather than imported, because the tree no longer holds those rules.

    The shipped selector counted a candidate when it was minted by the ``run >= run_now`` crossing rule,
    survived the two POINT-IN-TIME filters, carried a readable z on EVERY declared dimension and agreed
    in sign with ``z_now`` on at least ``ceil(len(dims) / 2)`` of them. That number -- and only that
    number -- is what ``watch.like_state_base_rate`` has ever printed to a reader.

    **``run_now`` HERE IS THE TAIL OF THE SEED'S OWN VECTOR, WHICH IS WHERE HEAD TOOK IT FROM** -- HEAD
    had no ``StateRow`` in this function and no kwarg to take one through. ``min_run`` is an override
    the bars below use to MEASURE the other floor (round 2's, the row's), never to state it as HEAD's:
    it is what makes the round-3 bar non-vacuous rather than a restatement of its own conclusion."""
    import math
    run_now = (A._run_at(seed_hist, len(seed_hist["values"]) - 1) if min_run is None
               else int(min_run))
    horizon = None if band.max_q is None else int(band.max_q) * 3
    n = 0
    for c in A.crossings(seed_hist, convention=convention, min_run=run_now):
        if horizon is not None:
            far = A._window_end(c["date"], horizon)
            if far is None or far > str(asof)[:10]:
                continue
        if lag_days:
            kn = A._add_days(c["date"], int(lag_days))
            if kn is None or kn > str(asof)[:10]:
                continue
        seen = agree = 0
        for dim in dims:
            hist = dim["hist"]
            i = A._index_on_or_before(hist["dates"], c["date"])
            zs = hist.get("z") or ()
            z_t = None if (i is None or i >= len(zs)) else zs[i]
            z_now = dim.get("z_now")
            if z_t is None or z_now is None:
                continue
            seen += 1
            if (z_t >= 0) == (z_now >= 0):
                agree += 1
        if seen == 0 or seen < len(dims) or agree < math.ceil(len(dims) / 2.0):
            continue
        n += 1
    return n


def test_R2_MAJOR4_the_RARITY_NUMERATOR_reproduces_HEADs_number_EXACTLY():
    """**THE RULING: THE FIELD THE WATCH READER CONSUMES KEEPS ITS OLD MEANING** (orchestrator, round 2).
    ``watch.like_state_base_rate`` prints "N like states in M observations" to a PM. Under the relaxation
    the ranked pool is 50%-79% of the record, so reading ``n_candidates`` there turns a rarity claim into
    a coverage statement wearing its name. ``n_candidates_head`` is the shipped rule's own count, carried
    beside the relaxed three, and this bar grades it against a RESTATEMENT of the S3 source rather than
    against a number typed into a docstring.

    IT IS A COUNT AND NOT A FILTER, and that is pinned too: the candidates it does not count are still
    ranked, still picked, still printed."""
    v, d = _episodes(bases=(80, 140, 188))
    st = _row(v, d, window=60)
    h = A.state_history(st, want_pct=True)
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"]),
             "pct_now": float(st.percentile["value"])}]
    band = parse_lag(R3a_BAND)
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=band, analog_k=3)
    want = _head_n_candidates(h, dims, asof=ASOF, band=band)
    assert want > 0, "the bar must measure a non-zero HEAD count or it grades nothing"
    assert sel["n_candidates_head"] == want
    # THE RELAXED POOL IS THE ONE THAT MOVED, and it is the one the header describes.
    assert sel["n_candidates"] > sel["n_candidates_head"]
    assert sel["n_candidates_raw"] >= sel["n_candidates_pit"] >= sel["n_candidates"]
    assert len(sel["picked"]) >= 1


def test_R2_MAJOR4_a_STANZA_the_SHIPPED_RULE_WOULD_HAVE_DECLINED_carries_a_HEAD_COUNT_OF_ZERO():
    """WHY ``n_candidates`` COULD NOT SIMPLY BE LEFT AT ITS OLD MEANING, measured rather than argued. On
    a record the shipped rule declined -- which is the five 2026-09-16 smoke turns, by construction --
    HEAD's count is ZERO while the relaxed selector picks a date. A header printing HEAD's number would
    then read "the record carries zero such crossings" directly above a dated stanza. Two questions, two
    names: the header keeps the pool it ranks, the base rate keeps the rarity.

    AND THE WATCH FLOOR IS WHAT CATCHES IT: a base rate of zero is not a recurrence, so
    ``_floor_of``'s clause 5 refuses ``base_rated_episode`` and kind 7 never nominates."""
    v, d = _like_fixture()
    st = _row(v, d, window=60)
    h = A.state_history(st, want_pct=True)
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"])}]
    band = parse_lag(B9_BAND)
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=band, analog_k=1)
    assert sel["n_candidates_head"] == _head_n_candidates(h, dims, asof=ASOF, band=band) == 0
    assert sel["picked"], "the relaxed selector picks where the shipped one declined -- the whole lane"
    assert sel["n_candidates"] > 100


def test_R2_MAJOR5_every_NOW_comes_from_the_ROW_and_never_from_the_vectors_TAIL(monkeypatch):
    """**THE VINTAGE GAP** (round 2, MAJOR 5). ``z_now`` was always the ROW's -- computed over everything
    published at the as-of -- while ``pct_now`` fell back to the TAIL of the knowledge-axis percentile
    vector, which on a lagged card is an older print. Measured on ``b40_event / drought`` (25 days
    declared): the row's z is 0.7581 and the vector's tail 0.6351, 0.123 sigma of pure vintage
    disagreement, against winning distances of 0.011 to 0.065. Two components of ONE dimension's state
    were read at two vintages and nothing said so.

    THE PRODUCER NOW PASSES ALL FOUR OFF THE ROW, and the bar reads the dimension the producer actually
    built rather than a number downstream of it."""
    v, d = _episodes(bases=(80, 140, 188))
    bd = _analog_board(v, d)
    st = bd.rows[0].state
    grabbed: dict = {}
    real = A.likeness

    def _spy(date, dims):
        grabbed.setdefault("dims", [dict(x) for x in dims])
        return real(date, dims)

    monkeypatch.setattr(A, "likeness", _spy)
    # A DECLARED PUBLICATION LAG IS WHAT MAKES THE TWO AXES DISAGREE AT ALL. `lag_days_fn` is the
    # injected override the walk already uses, and thirty-six days is `silver_noaa_oni`'s own declared
    # lag -- with it the knowledge axis slides a month or two and the vector's tail stops being today.
    A.analog_rows(bd, knobs=bd.knobs, lag_days_fn=lambda _r: 36)
    dim = grabbed["dims"][0]
    assert dim["z_now"] == pytest.approx(float(st.z["value"]))
    assert dim["pct_now"] == pytest.approx(float(st.percentile["value"]))
    assert dim["dir_now"] == st.run["direction"]
    assert dim["run_now"] == st.run["length"]
    # NON-VACUOUS: on this LAGGED card at least one tail read is a different number from the row's.
    hist = dim["hist"]
    tail_pct = next((p for p in reversed(hist["pct"]) if p is not None), None)
    tail_dir = A._direction_at(hist, len(hist["dates"]) - 1)
    tail_run = A._run_at(hist, len(hist["dates"]) - 1)
    assert (tail_pct != pytest.approx(dim["pct_now"])
            or tail_dir != A._direction_word(dim["dir_now"])
            or tail_run != dim["run_now"]), \
        "the knowledge axis must actually shift here or this bar grades nothing"
    # AND A ROW THAT DECLINED A MEASURE IS A HOLE, NEVER A GUESS.
    assert A._direction_word(None) is None and A._direction_word("") is None


def test_R2_MINOR4_run_gap_is_a_MEAN_OVER_DIMENSIONS_and_not_the_tie_breaks_own_term():
    """THREE SIMILARLY NAMED NUMBERS, TWO SUBJECTS (round 2, minor 4). ``run_gap`` is the mean over
    DIMENSIONS of ``|run at t - that dimension's run now|``; ``run_length`` and ``run_now`` on the picked
    row are the SEED's own, and the tie-break's second term is ``abs(run_length - run_now)``. A render
    that prints them as one arithmetic prints a falsehood, so the difference is measured here."""
    d = _months(40, 2010, 1)
    rise = [0.0] * 40
    for i in range(10, 20):
        rise[i] = 0.1 * (i - 9)
    seed = _hand_hist(d, rise, [None] * 40)
    seed["z"][10] = 1.0                                  # index 10 opens the rise: an episode START
    other = _hand_hist(d, [float(i % 3) for i in range(40)], [None] * 40)
    other["z"][10] = 1.0
    dims = [{"id": "seed", "hist": seed, "z_now": 1.0, "run_now": 9},
            {"id": "other", "hist": other, "z_now": 1.0, "run_now": 1}]
    got = A.likeness(d[10], dims)
    per = {r["id"]: r for r in got["per_dim"]}
    assert per["seed"]["run_gap"] != per["other"]["run_gap"], "two dimensions, two run gaps"
    assert got["run_gap"] == pytest.approx(
        (per["seed"]["run_gap"] + per["other"]["run_gap"]) / 2.0)
    sel = A.select_analogs(seed, dims=dims, asof=ASOF, band=parse_lag(R3a_BAND), analog_k=1,
                           run_now=9)
    p = sel["picked"][0]
    assert p["run_now"] == 9 and p["run_length"] == A._run_at(seed, 10)
    assert p["run_gap"] != pytest.approx(abs(p["run_length"] - p["run_now"]))


# -- ROUND 3: THE TWO MAJORS THE ROUND-2 REVIEW MEASURED ---------------------------------------------
def _floor_fixture(n=240, long_every=6, long_len=5, step=0.30):
    """A record of ONE-MONTH wiggles with a LONG rise every sixth segment, ending on a single-month
    move -- so the crossing FLOOR bites hard: ``min_run=1`` mints 143 candidates and ``min_run=2`` mints
    24, while the tail of the vector's own run is 1.

    IT EXISTS BECAUSE THE CLEAN ESTATE COULD NOT SEE MAJOR A. On every fixture board the row's streak
    and the vector's tail run agree (13 of 13), so a bar built there grades the head count at a floor
    where the two rules coincide and cannot fail. This shape separates them."""
    d = _months(n, 2000, 1)
    v = [0.0] * n
    i, seg, cur, up = 1, 0, 0.0, True
    while i < n:
        for _ in range(long_len if seg % long_every == 0 else 1):
            if i >= n:
                break
            cur += (step if up else -step)
            v[i] = cur
            i += 1
        up = not up
        seg += 1
    return v, d


def test_R3_MAJORA_the_RARITY_FLOOR_IS_HEADS_OWN_TAIL_READ_AND_NEVER_THE_ROWS_RUN():
    """**THE RARITY NUMERATOR IS HEAD'S ARITHMETIC END TO END, ITS ``min_run`` INCLUDED** (round-3
    review, MAJOR A). ``n_candidates_head`` is a claim about what the SHIPPED rule admitted, and the
    shipped rule minted its candidates with ``min_run = _run_at(seed_hist, tail)`` -- the tail of the
    seed's own knowledge-axis vector, because HEAD had no ``StateRow`` in that function. Round 2 gave
    the tie-break the ROW's run (rightly) and the head count inherited it by sharing one variable.

    THE CLEAN FIXTURE ESTATE CANNOT SEE THE DIFFERENCE and the round-2 bars could not either: row run
    == tail run on 13 of 13 dimensions, and both MAJOR-4 bars called the selector with NO ``run_now``
    kwarg -- the fallback path, never the shipped one. On the ``mirror_nulls`` estate, where a served
    NULL DATE drops a position out of ``state_history`` while the row's streak still counted it, the
    printed count moved 57 -> 33, 49 -> 5 and 30 -> 4 against HEAD's real module.

    THIS BAR GRADES THE SHIPPED CALL: it passes a ``run_now`` that DIFFERS from the tail, and it is
    non-vacuous by construction -- the same count computed at the ROW's floor is a different number."""
    v, d = _floor_fixture()
    st = _row(v, d, window=24)
    h = A.state_history(st, want_pct=True)
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"]),
             "pct_now": float(st.percentile["value"])}]
    band = parse_lag(R3a_BAND)
    tail = A._run_at(h, len(h["values"]) - 1)
    row_run = tail + 1                                   # the disagreement the mirror shape produces
    want = _head_n_candidates(h, dims, asof=ASOF, band=band)
    at_row = _head_n_candidates(h, dims, asof=ASOF, band=band, min_run=row_run)
    assert want > 0, "the bar must measure a non-zero HEAD count or it grades nothing"
    assert at_row != want, "the fixture must separate the two floors or this bar cannot fail"
    for rn in (None, row_run, tail, row_run + 3):
        sel = A.select_analogs(h, dims=dims, asof=ASOF, band=band, analog_k=3, run_now=rn)
        # THE NUMERATOR IS HEAD'S, AT EVERY CALLER'S ``run_now`` ...
        assert sel["n_candidates_head"] == want, rn
        # ... AND THE ROW'S RUN KEEPS THE SEAT A "NOW" BELONGS IN: the tie-break's own term.
        assert all(p["run_now"] == (tail if rn is None else rn) for p in sel["picked"])
    # ROUND-3 REVIEW MINOR 1: an EXPLICIT ``min_run`` is HEAD floor too -- the count follows the caller floor.
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=band, analog_k=3, run_now=row_run, min_run=row_run)
    assert sel["n_candidates_head"] == at_row


def test_R3_MAJORB_the_DIRECTION_and_the_RUN_are_read_on_the_KNOWLEDGE_AXIS_like_the_z():
    """**ONE POSITION, ONE VINTAGE, ON ALL FOUR COMPONENTS** (round-3 review, MAJOR B).
    ``state_history`` re-indexes ``z`` and ``pct`` onto the knowledge axis and leaves ``values`` on the
    observation axis, so ``likeness`` read ``z[i]`` -- the state knowable at ``dates[i]`` -- beside
    ``_direction_at(hist, i)``, the move INTO observation ``i``, which on a lagged card nobody could
    read at that date. MEASURED on the one lagged card in the fixture estate (``b40_event / drought``,
    25 days declared): the direction differed from the knowable one on 292 of 440 positions and the run
    on 257, and the six stanzas that board fires printed ``dir 3/5`` where the knowable reading is 4/5.

    It never ranked -- only the z carries a distance -- so this is a FACT heading for a sentence, caught
    before the sentence exists. Both components now read at :func:`analogs._knowable_at`, which is the
    IDENTITY on a zero-lag card and therefore moves no hand-stated vector."""
    v, d = _episodes(bases=(80, 140, 188))
    st = _row(v, d, window=60)
    h = A.state_history(st, lag_days=25, want_pct=True)  # `gold_weather_z`'s own declared lag
    idx = A._knowable_map(h)
    assert idx != list(range(len(d))), "a lag that re-indexes nothing would grade nothing"
    dim = {"id": "oni", "hist": h, "z_now": 0.5, "dir_now": "up", "run_now": 0}
    graded = moved = 0
    for i, t in enumerate(d):
        got = A.likeness(t, [dim])
        if got is None:                                  # inside the window's warm-up: no readable z
            continue
        rec = got["per_dim"][0]
        assert rec["index"] == i
        j = idx[i]
        if j is None:                                    # nothing was knowable there: a HOLE, not a 0
            assert "run_gap" not in rec and "dir_agree" not in rec
            continue
        graded += 1
        # THE ASSERTION THE REVIEW ASKS FOR: at position i, the run and the direction are the ones
        # KNOWABLE at dates[i] -- `run_now` is 0, so the gap IS the candidate's own knowable run.
        assert rec.get("run_gap") == A._run_at(h, j)
        kdir = A._direction_at(h, j)
        assert rec.get("dir_agree") == (None if kdir is None else (kdir == 1))
        if A._run_at(h, i) != A._run_at(h, j) or A._direction_at(h, i) != kdir:
            moved += 1
    assert graded > 100 and moved > 0, (graded, moved)
    # AND THE ZERO-LAG CARD IS UNTOUCHED: the map is the identity, so every hand-stated vector in this
    # deck keeps the arithmetic it stated.
    flat = A.state_history(st, want_pct=True)
    assert flat["knowable"] == list(range(len(d)))
    same = A.likeness(d[120], [{"id": "oni", "hist": flat, "z_now": 0.5, "dir_now": "up",
                                "run_now": 0}])
    assert same["per_dim"][0]["run_gap"] == A._run_at(flat, 120)


def test_R3_the_SEED_RUN_the_TIE_BREAK_reads_is_on_the_KNOWLEDGE_AXIS_TOO():
    """``run_length`` RANKS -- it is the second sort term -- and the doctrine is absolute: a state used
    to rank a candidate at ``t`` is the state KNOWABLE at ``t`` on every component. So the seed's own
    run at a candidate index is read through the same map, and a candidate with nothing knowable behind
    it scores ``_run_at``'s own answer for that, 0. MEASURED on the three fixture boards: the correction
    moves ZERO stanza lists, so it is a pure consistency fix and not a re-ranking."""
    v, d = _episodes(bases=(80, 140, 188))
    st = _row(v, d, window=60)
    h = A.state_history(st, lag_days=25, want_pct=True)
    idx = A._knowable_map(h)
    dims = [{"id": "oni", "hist": h, "z_now": float(st.z["value"]), "run_now": 3}]
    sel = A.select_analogs(h, dims=dims, asof=ASOF, band=parse_lag(R3a_BAND), analog_k=3,
                           lag_days=25, run_now=3)
    assert sel["picked"], "the fixture must fire or the bar grades nothing"
    off_axis = 0
    for p in sel["picked"]:
        i = A._index_on_or_before(h["dates"], p["date"])
        j = idx[i]
        assert p["run_length"] == (0 if j is None else A._run_at(h, j))
        if A._run_at(h, i) != p["run_length"]:
            off_axis += 1
    assert off_axis > 0, "on this lagged card at least one pick must show the two axes disagreeing"


def test_R3_the_EXISTENCE_filter_is_COUNTED_on_the_row_and_the_CENSUS_CLOSES():
    """**A DECLINE NOBODY COUNTS IS A DECLINE NOBODY AUDITS** (round-3 review, minor). Since round 2
    "existence" means a readable Z on at least one declared dimension, which is NARROWER than it was --
    a candidate inside every dimension's rolling warm-up used to be rankable on its percentile. That is
    a named choice, and it was derivable from two other numbers and stated nowhere.
    ``n_dropped_unreadable`` is the one subtraction between ``n_candidates_pit`` and ``n_candidates``,
    so the census closes by arithmetic on every row, fired or declined. MEASURED on the fixture estate:
    60, 91 and 91 candidates per 440-month card, the oldest stretch of each record."""
    v, d = _episodes(bases=(80, 140, 188))
    bd = _analog_board(v, d)
    rows = A.analog_rows(bd, knobs=bd.knobs)
    assert rows and not rows[0]["declined"]
    r0 = rows[0]
    assert r0["n_candidates_pit"] == r0["n_dropped_unreadable"] + r0["n_candidates"]
    assert r0["n_dropped_unreadable"] > 0, "the warm-up stretch must actually decline here"
    # AND IT IS A COUNT, NOT A GATE: the ranked pool is what the selector picks from, unchanged.
    assert r0["n_candidates_raw"] >= r0["n_candidates_pit"] >= r0["n_candidates"] >= 1
