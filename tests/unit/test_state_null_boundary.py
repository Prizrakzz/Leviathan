"""THE NULL BOUNDARY -- the shape the pg mirror actually serves, and what the state package does with it.

WHY THIS FILE EXISTS, MEASURED. ``numbers/pgnumbers._stringify`` renders a NULL cell as the EMPTY
STRING on purpose ("Athena's GetQueryResults renders NULL as '' (VarCharValue absent) -- match it",
pgnumbers.py:35). Every other deck in this package hands the producers HAND-WRITTEN arrays, where a
value is a float and a date is an ISO label -- so the whole package was graded on a shape the mirror
never serves. The S4 in-VPC census (job 7a0f90a9, leviathan-dev-graphrag-eval:12, 2026-09-09 20:50Z)
measured the consequence on the real store: of 144 board runs, 140 raised
``ValueError: invalid literal for int() with base 10: ''`` and P5 raised
``could not convert string to float: ''``. One board -- cocoa -- came back clean.

WHAT IS GRADED HERE:
  1. the boundary's own table (``transforms.num_or_none`` / ``date_or_none`` / ``clean_pairs`` /
     ``dated_pairs``): what counts as a null, what a hole is, and that a hole is never a zero;
  2. every producer that reads a fetched array -- ``state_history``, ``crossings``, ``select_analogs``,
     ``likeness``, ``outcome_over_band``, ``event_analogs``, ``co_loud_analogs``, the census's P5 and
     its lag witness -- fed BLANKS and required not to raise, and required to say how many holes it
     dropped;
  3. the whole board census, offline, over the ``mirror_nulls`` fixture set (``state.__main__``'s clean
     estate with the mirror's own blanks in it): zero board errors and zero register trips;
  4. the DROP LEDGER -- that an absence, a defect and a flag are counted as three facts and not one;
  5. the ANNUAL LABEL and its gate (section 6), which is the half of the in-VPC failure this sitting
     could not fix and therefore has to keep measurable.

THE ONE SHAPE THAT IS DECLARED AND NOT FIXED is the bare marketing-year label reaching ``walk``'s own
month arithmetic. It is the half of the measured failure that killed the ``quick`` class (35 of 36
boards, where no analog runs at all), the fix is one line inside ``walk._add_months``, and walk.py is
held by another lane. :func:`test_the_bare_YEAR_label_is_placeable_here_and_NOT_in_walks_own_arithmetic`
holds the measurement, the ``mirror_nulls_annual`` fixture set reproduces it offline (26 of 36 boards at
``quick`` on this estate), and
:func:`test_the_annual_census_is_the_RE_SUBMIT_GATE_and_it_measures_both_states` is the gate the in-VPC
re-submit waits on. Every one of those bars measures BOTH states of the tree, so the lane that lands the
one-liner does not inherit a red deck for having fixed it.

OFFLINE: no pg, no Athena, no network, no clock, no LLM.
"""
import pytest

from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import board_census as BC
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state import transforms as TR
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state.__main__ import fixtures
from leviathan.graphrag.state.lagbands import parse_lag
from leviathan.graphrag.state.rows import SeriesKey, StateRow, status_word

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
    return F.state_from_arrays(ref, values, dates, cadence="monthly", asof=ASOF, unit=unit,
                               narrate_unit=unit, windows={"monthly": window},
                               table="silver_noaa_oni", metric="oni_anom")


# ── 1. THE BOUNDARY'S OWN TABLE ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cell,want", [
    ("", None), (None, None), ("None", None), ("nan", None), ("NULL", None), ("  ", None),
    ("n/a", None), ("-", None), (float("nan"), None), (float("inf"), None),
    ("0", 0.0), (0, 0.0), ("-1.5", -1.5), (" 3.25 ", 3.25), ("1,200", 1200.0), (7, 7.0),
    ("not a number", None), (True, None), (False, None),
])
def test_num_or_none_pins_every_shape_a_served_cell_arrives_in(cell, want):
    """THE WHOLE VOCABULARY OF "NO READING", in one table. ``""`` is the mirror's NULL; ``"None"`` and
    ``"nan"`` are the same cell after something has already stringified it. A BOOLEAN IS NOT A READING
    -- ``float(True)`` is ``1.0`` and a flag column silently becoming a one is the kind of figure this
    package exists to refuse."""
    assert TR.num_or_none(cell) == want or (want is None and TR.num_or_none(cell) is None)


@pytest.mark.parametrize("cell,want", [
    ("", None), (None, None), ("None", None), ("nan", None), ("   ", None),
    ("2026-08-31", "2026-08-31"), (" 2026-08 ", "2026-08"), ("2025", "2025"), (2025, "2025"),
])
def test_date_or_none_pins_the_same_table_on_the_period_axis(cell, want):
    """It owns the NULL and not the CALENDAR: ``analogs.axis_date`` is the one place a label is placed
    on a day, and this function never parses one."""
    assert TR.date_or_none(cell) == want


def test_a_HOLE_is_dropped_and_NEVER_zero_and_the_axis_moves_with_it():
    """The doctrine the whole fix hangs on. Substituting ``0.0`` for a blank would move a mean, a z and
    a percentile by a number nobody read off a card; keeping the value while dropping its date would
    label every later observation with the wrong period."""
    vals, dates, dropped = TR.clean_pairs(["1", "", "3", None, "5"], _months(5))
    assert vals == [1.0, 3.0, 5.0] and dropped == 2
    assert dates == [_months(5)[0], _months(5)[2], _months(5)[4]]
    assert 0.0 not in vals


def test_a_SHORT_date_axis_pads_with_a_null_rather_than_shifting_a_value_onto_another_period():
    """``feeders._period_dates``' own pad case, and the reason it pads at all: a value whose label is
    missing keeps its value and loses its label, and never borrows its neighbour's."""
    vals, dates, dropped = TR.clean_pairs([1.0, 2.0, 3.0], ["2020-01-31"])
    assert vals == [1.0, 2.0, 3.0] and dates == ["2020-01-31", None, None] and dropped == 0
    # a SELECTOR cannot hold an unplaceable position, so `dated_pairs` drops the pair outright
    vals2, dates2, dropped2 = TR.dated_pairs([1.0, 2.0, 3.0], ["2020-01-31"])
    assert vals2 == [1.0] and dates2 == ["2020-01-31"] and dropped2 == 2


def test_the_boundary_is_a_coercion_and_not_a_second_calculator():
    """``state/transforms.py`` defines no stat (its own lint clause 1). The boundary decides whether a
    cell carries a READING; it computes nothing."""
    from leviathan.graphrag.numbers import stats as st
    names = {"is_null_token", "num_or_none", "date_or_none", "clean_pairs", "dated_pairs"}
    assert not (names & set(st.STAT_REGISTRY))
    assert not (names & set(TR.TRANSFORM_NAMES))


# ── 2. THE PRODUCERS, FED BLANKS ─────────────────────────────────────────────────────────────────────
def test_state_history_drops_the_holes_BEFORE_the_prefix_walk_and_says_how_many():
    """The z / percentile vectors are prefix walks: a hole inside one would either raise
    (``stats._floats`` refuses a ``None``) or shift every later position onto the wrong observation.
    The drop is counted on the dict -- an absence is a fact this package states, never a silence."""
    d = _months(120)
    v = [float(i % 7) - 3.0 for i in range(120)]
    v[10] = v[77] = ""                                   # two NULL numeric cells
    d[40] = ""                                           # one NULL date cell
    d[41] = None
    st = _row(v, d)
    # EACH STAGE COUNTS WHAT IT ITSELF DROPPED. The ROW drops the two unvalued cells when it builds the
    # array (and keeps the two undated observations -- their levels are real); the HISTORY then drops
    # the two it cannot place on a calendar. Two counts, two different questions, both stated.
    assert st.coverage["dropped_null"] == 2 and st.coverage["undated_periods"] == 2
    h = A.state_history(st, want_pct=True)
    assert h["n_dropped_null"] == 2
    assert len(h["values"]) == len(h["dates"]) == len(h["z"]) == len(h["pct"]) == 116
    assert all(isinstance(x, float) for x in h["values"])
    assert all(x is not None for x in h["dates"])
    assert h["z"][-1] is not None


def test_the_dropped_hole_is_a_HOLE_and_the_z_is_the_z_of_the_series_without_it():
    """A DROPPED NULL IS A HOLE, NOT A ZERO -- stated as an equality against the same array with the
    blank physically removed, which is the only way to show the arithmetic did not absorb it. The
    rolling window PARAMETER does not move either: it is still ``window`` periods of the array."""
    d = _months(90)
    v = [float((i * 13) % 29) for i in range(90)]
    with_hole = list(v)
    with_hole[44] = ""
    dates_hole = list(d)
    without = [x for i, x in enumerate(v) if i != 44]
    dates_without = [x for i, x in enumerate(d) if i != 44]
    a = A.state_history(_row(with_hole, dates_hole, window=30))
    b = A.state_history(_row(without, dates_without, window=30))
    assert a["values"] == b["values"] and a["dates"] == b["dates"]
    assert a["z"] == b["z"] and a["window"] == b["window"] == 30
    # and the zero-substitution reading is a DIFFERENT answer, which is what makes the bar mean anything
    zeroed = list(v)
    zeroed[44] = 0.0
    assert A.state_history(_row(zeroed, d, window=30))["z"] != a["z"]


def test_the_PERCENTILE_FLOOR_counts_readings_and_not_positions_walked():
    """"The transforms' declared refusal floors must not move." ``stats.MIN_PERCENTILE_N`` is a floor on
    the POPULATION, so a hole is not a member of it: a prefix of eight positions holding six readings
    must still refuse. The hole keeps its POSITION (the vector stays parallel to its own dates) and the
    rank at every later position is the rank against the readings alone."""
    from leviathan.graphrag.numbers import stats as _st
    floor = int(_st.MIN_PERCENTILE_N)
    v = [float(i) for i in range(floor + 4)]
    v[1] = v[2] = ""                                     # two holes inside the first prefix
    got = A._prefix_percentiles(v)
    assert len(got) == len(v)
    assert got[1] is None and got[2] is None
    assert got[floor - 1] is None                        # eight positions, six readings -> still refuses
    assert got[floor + 1] is not None
    # and the ranks are the ranks of the series with the holes taken out
    clean = A._prefix_percentiles([x for x in v if x != ""])
    assert [p for p in got if p is not None] == [p for p in clean if p is not None]


def test_the_STATE_ROW_keeps_an_undated_level_and_counts_its_own_holes():
    """A ROW is not a HISTORY: the level is a real reading and only its label is missing, so the row
    keeps it and says the date is absent. ``level_date`` is ``None`` -- never ``""``, which is a string
    that reaches an ``int()``."""
    d = _months(40)
    v = [float(i) for i in range(40)]
    v[3] = ""
    d[-1] = ""                                           # the newest served row has no date column
    st = _row(v, d)
    assert status_word(st.status) == "ok"
    assert st.level == 39.0 and st.level_date is None
    assert st.coverage["dropped_null"] == 1 and st.coverage["undated_periods"] == 1
    # a label is a STRING or the absence -- never `""`, and never a non-string the calendar would have
    # to guess at. (The first cut of this line read `x is not None or True`, which is a tautology and
    # asserted nothing at all; the two lines under it were carrying the whole bar.)
    assert all(x is None or isinstance(x, str) for x in st.inputs[st.key.label()]["dates"])
    assert "" not in st.inputs[st.key.label()]["values"]
    assert "" not in [x for x in st.inputs[st.key.label()]["dates"] if x is not None]


def test_a_value_column_BLANK_ALL_THE_WAY_DOWN_is_an_empty_read_with_the_served_paths_own_word():
    """The shape ``feeders.series_state`` names ``read_empty:all_blank`` on the mirror. The fixture path
    had no word for it at all and raised instead, which the walk then fenced into ``read_error`` -- a
    real column silently demoted by a defect nobody could see."""
    st = _row([""] * 30, _months(30))
    assert st.status == "read_empty:all_blank" and status_word(st.status) == "read_empty"
    assert st.level is None


def test_period_dates_writes_a_NULL_and_never_an_empty_string():
    """``_period_dates``' reason is unchanged ("a blank date on a rendered row is visible, and a
    plausible wrong one is not"); the VALUE is. All three served label forms still ride."""
    rows = [{"data_date": "2026-01-31", "value": "1"},
            {"year": "2025", "month": "3", "value": "2"},
            {"year": "2024", "month": "", "value": "3"},        # month NULL -> the bare marketing year
            {"data_date": "", "year": "", "period": "", "value": "4"}]   # nothing at all
    got = F._period_dates(rows, None, [1.0, 2.0, 3.0, 4.0], None)
    assert got == ["2026-01-31", "2025-03", "2024", None]
    # and the pad case pads with the same null
    assert F._period_dates(rows[:1], None, [1.0, 2.0, 3.0], None) == ["2026-01-31", None, None]


# ── 2b. THE SERVED PATH: one blank cell must not relabel the whole array ─────────────────────────────
class _Node:
    """The census's ``_LegNode`` stand-in -- exactly what the replayed cascade helpers read."""
    __slots__ = ("contract", "id", "prior", "evidence")

    def __init__(self, contract, driver_id, ref, region=None):
        self.contract, self.id = contract, driver_id
        self.prior = {"silver_ref": ref, "region": region}
        self.evidence = []


def _oni_rows(n=140, start=(2015, 1)):
    out, y, m = [], *start
    for i in range(n):
        out.append({"year": y, "month": m, "value": str(round(1.4 * ((i % 23) - 11) / 11.0, 3))})
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _served(rows, asof="2026-09-08"):
    """``series_state`` over a canned executor with the SQL's own point-in-time oracle wired in."""
    from leviathan.graphrag.numbers.registry import load_registry
    ts = load_registry().get("silver_noaa_oni")
    spec = F.board_spec("silver_noaa_oni", "oni_anom", "soybeans_cbot", None, asof, "monthly")
    qfn = F.fixture_query_fn({"silver_noaa_oni": rows}, pit={"silver_noaa_oni": (spec, ts)},
                             ym_lag=True)
    st = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), asof,
                        qfn=qfn, windows={"monthly": 120}, silver_status="available")
    arrays = (st.inputs or {}).get(st.key.label()) or {}
    return st, dict(zip(arrays.get("dates") or [], arrays.get("values") or []))


def test_ONE_blank_cell_must_not_relabel_the_whole_ARRAY():
    """**THE SILENT HALF OF THE SAME DEFECT.** ``cascade._pace_series`` SKIPS a row whose value does not
    parse; ``_period_dates`` walked EVERY row. The two axes then differed in length and the mismatch
    branch trims the labels from the FRONT -- so a null anywhere but the front shifted the entire array
    by one period. MEASURED on this fixture before the fix: ONE blank cell inside the fetched window
    relabelled 110 of 118 observations, and the level, the z, the percentile, the run and every window
    change were computed against months they do not belong to. Nothing raised.

    The bar is an EQUALITY against the same read with no blank in it: every observation that survives
    keeps its own date."""
    _clean_st, clean = _served(_oni_rows())
    holed_rows = _oni_rows()
    holed_rows[130]["value"] = ""                        # one NULL cell, well inside the window
    st, holed = _served(holed_rows)
    assert len(holed) == len(clean) - 1
    mislabelled = [d for d in holed if clean.get(d) != holed[d]]
    assert mislabelled == []
    assert status_word(st.status) == "ok"


def test_the_LEVELS_own_facts_come_from_a_row_that_carried_a_reading():
    """``level_row`` fed ``derive_knowledge_date`` and the vintage ``role`` off ``rows[-1]`` -- which on
    the mirror can be a row whose value column is blank and whose value therefore is not the level at
    all. It is the last ADMITTED row now, which is the row the level actually came from."""
    rows = _oni_rows()
    rows[-1]["value"] = ""
    rows[-2]["value"] = ""
    st, arrays = _served(rows)
    assert status_word(st.status) == "ok"
    assert st.level == arrays[st.level_date]
    assert st.knowledge_date is not None


def test_crossings_never_mints_a_candidate_the_calendar_cannot_place():
    """Every downstream filter is a statement about the candidate's DATE, so a crossing at an
    unplaceable label could support none of them -- and admitting it is what put ``""`` in front of
    ``int(iso[0:4])``."""
    d = _months(60)
    v = [float(i % 5) for i in range(60)]
    hist = {"dates": list(d), "values": list(v), "z": [None] * 60, "pct": [None] * 60,
            "window": 12, "lag_days": 0}
    hist["dates"][7] = ""
    hist["dates"][8] = None
    hist["dates"][9] = "not a date"
    got = A.crossings(hist, min_run=1)
    assert got, "the fixture must actually produce crossings or the bar is vacuous"
    assert all(A.axis_date(c["date"]) is not None for c in got)
    assert not [c for c in got if c["index"] in (7, 8, 9)]


@pytest.mark.parametrize("label", ["", None, "not a date", "  "])
def test_the_three_month_helpers_return_a_stated_None_on_an_unplaceable_label(label):
    """The three that raised. Each now says "I cannot place this" instead."""
    assert A._window_end(label, 6) is None
    assert A._add_months(label, 6) is None
    assert A._months_between(label, "2026-01-31") is None
    assert A._months_between("2026-01-31", label) is None


def test_the_three_helpers_read_all_three_SERVED_label_forms():
    """``analogs.axis_date`` is the one calendar: an ISO day rides as itself, a ``year_month`` card's
    month is its MONTH-END, and a bare ``YYYY`` is that year's 31 December."""
    assert A._window_end("2026-08-31", 3) == "2026-11-30"
    assert A._window_end("2026-08", 3) == "2026-11-30"
    assert A._window_end("2025", 3) == "2026-03-31"
    assert A._months_between("2025", "2026-03") == 3
    assert A._months_between("2026-01-31", "2026-08") == 7


def test_likeness_and_select_analogs_survive_a_history_full_of_blanks():
    """The selector end to end on the mirror's shape: blanks in the values, blanks and bare years on the
    dates. Before the boundary this raised inside ``_window_end`` on the first candidate."""
    d = _months(240)
    v = [float((i * 7) % 23) - 11.0 for i in range(240)]
    v[15] = v[100] = ""
    d[30] = ""
    d[31] = d[32] = None
    for i in (60, 61, 62):
        d[i] = d[i][:4]                                  # a bare marketing year inside the history
    st = _row(v, d, window=36)
    hist = A.state_history(st, want_pct=True)
    dims = [{"id": "El_Nino", "hist": hist, "z_now": hist["z"][-1]}]
    assert A.likeness(hist["dates"][-1], dims) is not None
    sel = A.select_analogs(hist, dims=dims, asof=ASOF, band=parse_lag("1-2 quarters"), analog_k=3,
                           min_separation_months=12)
    assert sel["declined"] is None or sel["declined"] == "no_like_state"
    for p in sel["picked"]:
        assert A.axis_date(p["date"]) is not None


def test_a_z_that_arrives_as_a_blank_is_a_MISSING_dimension_and_not_a_zero_sigma():
    """``likeness`` skips a dimension whose z is missing at ``t`` and counts it against the gate's
    denominator. A blank coerced to ``0.0`` would make an unobserved dimension AGREE on sign."""
    d = _months(60)
    hist = {"dates": d, "values": [float(i) for i in range(60)], "z": [""] * 60,
            "pct": [None] * 60, "window": 12, "lag_days": 0}
    assert A.likeness(d[30], [{"id": "d", "hist": hist, "z_now": ""}]) is None


def test_outcome_over_band_takes_a_blank_benchmark_column_and_an_unplaceable_state_date():
    d = _months(80)
    v = [float(100 + i) for i in range(80)]
    v[5] = ""
    d[6] = ""
    band = parse_lag("1-2 quarters")
    got = A.outcome_over_band(label="the benchmark", values=v, dates=d, t=d[20], band=band, asof=ASOF)
    assert got["declined"] is None and got["near_value"] is not None
    # an anchor the calendar cannot place declines by the CLOSED vocabulary's own word
    bad = A.outcome_over_band(label="the benchmark", values=v, dates=d, t="", band=band, asof=ASOF)
    assert bad["declined"] == "no_tape_rows" and bad["decline_leg"] == "analog"
    assert bad["declined"] in B.ANALOG_REASONS


def test_event_analogs_read_a_flag_column_with_blank_cells_and_blank_dates():
    d = _months(60)
    v = [0.0] * 60
    v[10] = v[30] = 1.0
    v[11] = ""                                           # a NULL cell beside a real event
    d[31] = ""                                           # and one event with no date at all
    st = F.state_from_arrays("biodiesel_mandate_flag", v, d, cadence="monthly", asof=ASOF,
                             is_flag=True, windows={"monthly": 12}, table="silver_flag",
                             metric="flag")
    row = B.NodeRow(contract="c", driver_id="policy_event", type="policy_event",
                    lag_band=parse_lag("0-2 quarters"), state=st)
    got = A.event_analogs(row, asof=ASOF, band=parse_lag("0-2 quarters"))
    assert got["declined"] is None
    assert all(A.axis_date(x) is not None for x in got["dates"])
    assert (st.flag_state or {}).get("last_event_date") != "None"


def _positioning_board(vals_by_contract, *, driver_id="cot_mm_positioning", dates=None):
    d = dates if dates is not None else _months(60, 2018, 1)
    bd = B.Board(asof=ASOF, mode="max", knobs=B.board_knobs_of("max"),
                 anchors=tuple(B.Anchor(contract=c, source="focus_driver", rank=i,
                                        driver_id=driver_id, subject=True)
                               for i, c in enumerate(vals_by_contract)))
    for c, vals in vals_by_contract.items():
        st = F.state_from_arrays("cot_mm_positioning", vals, d, cadence="monthly", asof=ASOF,
                                 windows={"monthly": 24}, table="silver_cot", metric="mm_net",
                                 commodity=c)
        bd.rows.append(B.NodeRow(contract=c, driver_id=driver_id,
                                 lag_band=parse_lag("0-1 quarters"), state=st, subject=True))
    bd.order = tuple(r.key for r in bd.rows)
    return bd


def test_co_loud_analogs_survive_blanks_on_every_contract():
    d = _months(60, 2018, 1)
    d[20] = ""
    d[21] = None
    d[22] = d[22][:4]
    spike = [0.0] * 30 + [100.0] * 12 + [0.0] * 18
    spike[5] = ""
    bd = _positioning_board({"soybeans_cbot": list(spike), "corn_cbot": list(spike)}, dates=d)
    got = A.co_loud_analogs(bd, "cot_mm_positioning", k=2, analog_k=2)
    assert got["declined"] in (None, "no_like_state")
    for h in got.get("dates") or ():
        assert A.axis_date(h["date"]) is not None


def test_analog_rows_run_a_whole_board_of_blank_carrying_rows_without_raising():
    d = _months(120, 2010, 1)
    d[70] = ""
    d[71] = d[71][:4]
    bd = _positioning_board({"soybeans_cbot": [float((i * 5) % 17) for i in range(120)],
                             "corn_cbot": [float((i * 3) % 13) for i in range(120)]}, dates=d)
    for r in bd.rows:
        r.legs["loud"] = True
    got = A.analog_rows(bd, knobs=B.board_knobs_of("max"))
    assert isinstance(got, list)
    for a in got:
        if not a.get("declined"):
            assert A.axis_date(a["date"]) is not None


# ── 3. THE CENSUS'S OWN PROBES ───────────────────────────────────────────────────────────────────────
_P5_ROWS = [
    {"year": "1991", "month": "1", "oni_anom": "0.40", "oni_lag3": "", "oni_lag6": "0.10"},
    {"year": "1991", "month": "2", "oni_anom": "", "oni_lag3": "0.40", "oni_lag6": ""},
    {"year": "1991", "month": "3", "oni_anom": "0.55", "oni_lag3": "", "oni_lag6": ""},
    {"year": "", "month": "", "oni_anom": "0.20", "oni_lag3": "", "oni_lag6": ""},
]


def test_P5_reads_a_vintage_whose_cells_are_blank_and_declines_by_name():
    """The measured probe failure: ``P5 ERROR ValueError: could not convert string to float: ''``. A
    blank cell is now a stated ``None`` inside the banked snapshot, and ``non_null_values`` counts it as
    the absence it is -- so the NEXT run's vintage diff has a prior to read instead of nothing."""
    got = BC.probe_p5(ASOF, qfn=lambda sql: list(_P5_ROWS))
    assert "error" not in got
    for table, rec in got["tables"].items():
        assert rec["n_periods"] == 3, table                # the year/month-less row is not a period
        assert rec["non_null_values"] == 2, table
        assert None in rec["snapshot"].values()
        assert rec["lag_witness"]["available"] is False    # every lagged cell or its base was null
    assert got["verdict"]


def test_the_LAG_WITNESS_compares_only_cells_that_carry_readings():
    """A blank lag cell is not a disagreement and not a comparison either. The witness refuses to run
    over zero comparisons rather than printing a clean verdict over nothing."""
    rows = [{"year": "1990", "month": f"{m}", "oni_anom": f"{m * 0.1:.2f}",
             "oni_lag3": ("" if m % 2 else f"{(m - 3) * 0.1:.2f}")} for m in range(1, 13)]
    got = BC._lag_witness(rows, {}, "silver_noaa_oni", anom_col="oni_anom")
    assert got["available"] is True
    # six of the twelve lag cells are blank and three of the six real ones have no base three months
    # back, so FIVE cells are comparable and five is what the witness claims to have checked
    assert got["checked"] == 5 and got["checked_by_column"] == {"oni_lag3": 5}
    assert got["mismatches"] == 0 and got["max_delta"] == 0.0
    assert "is NOT proof that no in-place revision happened" in got["reading"]


def test_the_PRIOR_VINTAGE_DIFF_never_raises_on_an_archive_banked_before_this_fix():
    """A run older than the boundary banked ``""`` cells into ``probes.json``; the diff reads its own
    archive and must not raise on it."""
    got = BC._prior_diff({"1991-01": 0.4, "1991-02": None},
                         {"hash": "abc", "snapshot": {"1991-01": "", "1991-02": "0.3"}})
    assert got["compared"] is True and isinstance(got["changed"], int)


def test_a_destination_COUNT_that_comes_back_NULL_is_an_absence_and_not_an_int_of_empty():
    """``COUNT(DISTINCT <destination>)`` on a card with no destination column serves NULL, which the
    mirror renders as ``""`` -- and ``int("")`` raised. The count is a number or a stated absence."""
    from leviathan.graphrag import graph as G
    graph = G.CausalGraph(G.load_contracts(), silver=set(), version="deck")
    got = BC.destination_census(graph, ASOF, qfn=lambda sql: [{"n": "12", "destinations": ""}])
    assert got["errors"] == []
    rows = got["rows"]
    assert rows and all(r.get("error") is None for r in rows)
    assert all(r["destinations"] is None and r["rows_52w"] == 12 for r in rows)
    assert got["verdict"]


# ── 4. THE CENSUS, OFFLINE, ON THE MIRROR'S OWN SHAPE ────────────────────────────────────────────────
def test_the_mirror_nulls_fixture_actually_carries_the_mirrors_blanks():
    """A null-boundary deck that silently ran on clean arrays would pass while proving nothing."""
    fx = fixtures("mirror_nulls")
    blank_dates = sum(1 for s in fx.values() for d in s["dates"] if d == "")
    blank_values = sum(1 for s in fx.values() for v in s["values"] if v == "")
    year_only = sum(1 for s in fx.values() for d in s["dates"] if isinstance(d, str) and len(d) == 4)
    assert blank_dates >= 10 and blank_values >= 10 and year_only >= 4
    assert fixtures("default") != fx
    with pytest.raises(KeyError):
        fixtures("no_such_set")


@pytest.mark.parametrize("mode", ["quick", "deep", "max"])
def test_the_board_census_runs_the_mirror_nulls_estate_with_zero_errors_and_zero_trips(mode):
    """THE BAR THE IN-VPC PASS FAILED. Four of the boards that errored on the mirror, at every mode, on
    the mirror's own null shape: zero board errors, zero register trips, and the rectangle closed."""
    art = BC.census(asof=ASOF, qfn=BC._dead_qfn,
                    state_fn_factory=BC.fixture_state_fn_factory("mirror_nulls"),
                    modes=(mode,),
                    contracts=["arabica_coffee", "barley", "soybeans_cbot",
                               "malaysian_crude_palm_oil_cme"],
                    alternative_pass="", probes=(), cascade_legs=False)
    s = art["summary"]
    assert s["board_errors"] == []
    assert s["register_trips"] == 0 and s["register_trips_zero"] is True
    assert s["rectangles_open"] == []
    assert not [b for b in art["boards"] if b.get("error")]


def test_the_clean_fixture_estate_is_unchanged_by_the_boundary():
    """The boundary must be a no-op on an array with no nulls in it: the default census is the pass the
    S4 artifact's measured figures were taken from, and a fix that moved it would have moved them."""
    art = BC.census(asof=ASOF, qfn=BC._dead_qfn,
                    state_fn_factory=BC.fixture_state_fn_factory("default"),
                    modes=("deep",), contracts=["soybeans_cbot", "cocoa"],
                    alternative_pass="", probes=(), cascade_legs=False)
    s = art["summary"]
    assert s["board_errors"] == [] and s["register_trips"] == 0
    for b in art["boards"]:
        st = (b.get("rows") or {}).get("by_status") or {}
        assert st.get("read_error", 0) == 0, b["contract"]


# ── 5. THE ONE SHAPE THIS SITTING DECLARES RATHER THAN FIXES ─────────────────────────────────────────
def test_an_UNDATED_level_reaches_walks_projection_as_a_DECLINE_and_never_a_raise():
    """The boundary turns ``""`` into ``None`` and both are FALSY, so ``walk.projection_window``'s own
    guard catches them -- which is what makes the change safe across a seam this sitting does not own."""
    band = parse_lag("1-2 quarters")
    for anchor in ("", None):
        assert W.projection_window(anchor, band)["declined"] == "lag_unparsed"


def _annual_handover_open() -> bool:
    """Does ``walk``'s own month arithmetic still raise on a bare marketing-year label?

    THE ONE PREDICATE THE HAND-OVER BARS BRANCH ON, so there is exactly one place that knows how to ask
    and the bars below read as sentences. It asks ``walk`` a question and reports the answer; it never
    asserts, because BOTH answers are legitimate states of the tree -- open (the hand-over has not
    landed) and closed (it has). ``jobs/submit/submit_batch_board_census.annual_handover_open`` is the
    same question asked at the door where the money is spent."""
    try:
        W._add_months("2025", 3)
    except ValueError:
        return True
    return False


def test_the_bare_YEAR_label_is_placeable_here_and_NOT_in_walks_own_arithmetic():
    """**DECLARED, NOT FIXED -- the remaining half of the measured in-VPC failure.**

    ``feeders._period_dates`` legitimately writes a bare ``YYYY`` for a marketing-year card that carries
    ``year`` and no month -- ``configs/graphrag/numbers/tables.yaml`` declares TEN annual tables with no
    ``date_col`` (``silver_psd``, ``silver_production``, ``silver_nass_annual``, ``silver_icco_cocoa``,
    ``silver_psd_attributes``, ``silver_ams_cotton_quality``, ``silver_production_livestock``,
    ``silver_fnc_colombia_area_department`` among them) and several are carried by nearly every board.
    ``analogs.axis_date`` names that form first-class ("a bare ``YYYY`` is that year's 31 December").
    ``walk._add_months`` slices ``iso[5:7]`` instead, and on that label the slice is EMPTY --
    ``int("")`` raises the very same ``invalid literal for int() with base 10: ''`` the S4 census
    measured, from ``render``'s SB-J projection at every mode including ``quick``
    (``anchor_date = win.get("near") or st.level_date``). That is why the in-VPC pass lost 35 boards at
    ``quick``, where no analog runs at all.

    THE FIX IS ONE LINE inside ``walk._add_months`` -- place the label through ``analogs.axis_date``,
    exactly as :func:`analogs._window_end` now does -- and walk.py is held by the subject-resolver lane,
    so this sitting measures it and hands it over instead of editing it. (The function is cited by NAME
    and not by line: the lane moved it while the review was being written.) ``watch.py`` (this package's
    own caller) already guards; ``render.py`` is held too and does not.

    THIS BAR IS NOT A LANDMINE. It measures BOTH states and demands the right thing of each: while the
    hand-over is open, ``walk`` must raise on the bare year (a fixture whose defect quietly healed would
    be a fixture proving nothing); once it lands, ``walk`` must return exactly the date ``analogs``
    places the label on. Neither branch lets a THIRD behaviour through, and the lane that lands the
    one-liner does not have to also land a test edit to keep the deck green."""
    assert A.axis_date("2025") == "2025-12-31"
    assert A._window_end("2025", 3) == "2026-03-31"
    assert A._add_months("2025", 3) == "2026-03-31"
    if _annual_handover_open():
        with pytest.raises(ValueError):
            W._add_months("2025", 3)
        with pytest.raises(ValueError):
            W.projection_window("2025", parse_lag("1-2 quarters"))
    else:
        # THE HAND-OVER LANDED. `walk` and `analogs` must place the label on the SAME day: two
        # calendars for one label is the S3 defect `axis_date`'s own docstring measures.
        assert W._add_months("2025", 3) == A._add_months("2025", 3) == "2026-03-31"
        w = W.projection_window("2025", parse_lag("1-2 quarters"))
        assert w["declined"] is None and w["opens"] and w["closes"]


def test_watchs_own_projection_anchor_declines_a_label_walk_cannot_read():
    """The guard this sitting DID land, on the caller it owns: an anchor shorter than ``YYYY-MM``
    produces no lag-window row rather than ending the board."""
    bd = _positioning_board({"soybeans_cbot": [float(i) for i in range(60)]},
                            dates=[f"{2000 + i}" for i in range(60)])
    from leviathan.graphrag.state import watch as WA
    rows = WA.watch_rows(bd, analogs=[])
    assert isinstance(rows, list)
    assert not [w for w in rows if w.get("kind") == "lag_window" and w.get("dates")]


# -- 6. THE ANNUAL LABEL: the hand-over's own fixture, and the gate on the in-VPC re-submit ----------
def test_the_mirror_nulls_set_does_NOT_carry_the_annual_render_shape_and_says_so():
    """WHY THE GREEN ABOVE IS NARROWER THAN IT LOOKS, pinned so nobody has to re-derive it.

    ``mirror_nulls`` puts bare ``YYYY`` labels only MID-ARRAY (``heat_stress_z`` 5-8), and the only card
    whose LAST label is not a full ISO day is ``mpob_ending_stocks``, whose blank is FALSY and declines
    at ``walk.projection_window``'s own guard. So no rendered row's ``level_date`` is ever a bare year
    in that set, ``walk``'s month arithmetic is never handed one, and a census over it is green for a
    reason that has nothing to say about the ``quick``-mode class the in-VPC pass actually lost."""
    fx = fixtures("mirror_nulls")
    tails = {ref: s["dates"][-1] for ref, s in fx.items()}
    assert not [r for r, d in tails.items() if isinstance(d, str) and len(d) == 4], tails
    assert tails["mpob_ending_stocks"] == ""                       # falsy: declines, never raises
    ann = fixtures("mirror_nulls_annual")
    assert [r for r, s in ann.items() if isinstance(s["dates"][-1], str) and len(s["dates"][-1]) == 4]


def test_the_annual_fixture_is_the_mirror_set_plus_the_bare_marketing_year():
    """The third set is the second set with ONE change, so a difference between their censuses is
    attributable to the label and to nothing else."""
    from leviathan.graphrag.state.__main__ import ANNUAL_LABEL_INJECTIONS
    base, ann = fixtures("mirror_nulls"), fixtures("mirror_nulls_annual")
    assert set(base) == set(ann)
    changed = {r for r in base if base[r]["dates"] != ann[r]["dates"]}
    assert changed == {r for r, _shape, _why in ANNUAL_LABEL_INJECTIONS}
    for ref in changed:
        assert base[ref]["values"] == ann[ref]["values"]           # only the AXIS moved
        assert all(isinstance(d, str) and len(d) == 4 and d.isdigit() for d in ann[ref]["dates"])
    assert "export" in changed                                     # the one that RENDERS a row


def test_a_bare_marketing_year_reaches_the_row_as_its_level_date_and_the_row_is_ok():
    """THE PRODUCER'S HALF IS ALREADY RIGHT, which is what makes this a hand-over and not a defect
    here: the state row carries the marketing year as its printed period, the way a reader expects an
    annual card to be labelled."""
    st = F.state_from_arrays("export", [float(i) for i in range(20)],
                             [str(2006 + i) for i in range(20)], cadence="annual", asof=ASOF,
                             unit="MMT", narrate_unit="MMT", windows={"annual": 10},
                             table="silver_psd", metric="exports")
    assert status_word(st.status) == "ok"
    assert st.level_date == "2025" and A.axis_date(st.level_date) == "2025-12-31"


@pytest.mark.parametrize("mode", ["quick", "deep", "max"])
def test_the_annual_census_is_the_RE_SUBMIT_GATE_and_it_measures_both_states(mode):
    """**THE GATE.** ``board_census --offline --fixture mirror_nulls_annual`` must come back with ZERO
    board errors before the in-VPC census is submitted again.

    MEASURED ON THIS TREE, at ``quick``, all 36 boards: 26 error with
    ``ValueError: invalid literal for int() with base 10: ''`` and 10 come back clean -- and ``cocoa``
    is among the clean ten, which is the in-VPC pass's own clue reproduced offline (cocoa was the ONE
    board that survived all four passes on the mirror). The estate's own rate is higher still (35 of 36
    at ``quick``) because the real mirror serves ten ``date_col``-less annual tables where this fixture
    serves two.

    WHILE THE HAND-OVER IS OPEN this bar requires that EVERY error is that exact signature -- a board
    that died of something else would be a second defect hiding inside the first, and the gate would
    read as though it were already accounted for. ONCE IT LANDS the bar requires zero errors outright.
    It never goes red for the lane that lands the one-liner."""
    art = BC.census(asof=ASOF, qfn=BC._dead_qfn,
                    state_fn_factory=BC.fixture_state_fn_factory("mirror_nulls_annual"),
                    modes=(mode,),
                    contracts=["soybeans_cbot", "corn_cbot", "barley", "cocoa"],
                    alternative_pass="", probes=(), cascade_legs=False,
                    fixture="mirror_nulls_annual")
    s = art["summary"]
    assert s["register_trips"] == 0 and s["rectangles_open"] == []
    if not _annual_handover_open():
        assert s["board_errors"] == []
        return
    errs = s["board_errors"]
    assert errs, "the annual fixture must REPRODUCE the failure while the hand-over is open"
    assert {e["error"] for e in errs} == {"ValueError: invalid literal for int() with base 10: ''"}
    # cocoa is the board that carries no rendered annual card -- the in-VPC survivor, offline
    assert "cocoa" not in {e["contract"] for e in errs}


def test_the_census_artifact_says_WHICH_ESTATE_it_measured():
    """A banked banner from a fixture pass and a banked banner from the real mirror were identical in
    every header field, and only the first line of STDOUT -- which is not banked -- said which. That is
    exactly the provenance a census artifact exists to carry."""
    art = BC.census(asof=ASOF, qfn=BC._dead_qfn,
                    state_fn_factory=BC.fixture_state_fn_factory("mirror_nulls"),
                    modes=("quick",), contracts=["cocoa"], alternative_pass="", probes=(),
                    cascade_legs=False, fixture="mirror_nulls")
    assert art["summary"]["fixture"] == "mirror_nulls"
    assert art["summary"]["estate"] == "fixtures:mirror_nulls"
    assert "estate=fixtures:mirror_nulls" in BC.banner(art)
    # and a pass that names no fixture is the LIVE mirror, in the artifact's own words
    live = dict(art)
    live["summary"] = dict(art["summary"], fixture="", estate="pg-mirror")
    assert "estate=pg-mirror" in BC.banner(live)


def test_the_submit_wrapper_refuses_to_buy_the_same_failure_twice():
    """A SUBMIT IS A PURCHASE. The wrapper asks ``walk`` the same question this deck asks, before any
    env read and before any AWS call, and refuses while the answer is 'it still raises'."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "jobs" / "submit" / "submit_batch_board_census.py"
    text = src.read_text(encoding="utf-8")
    assert "def annual_handover_open()" in text
    assert "--ack-annual-handover" in text
    assert "mirror_nulls_annual" in text
    # the refusal is BEFORE the first env read, which is the first line that can fail for any other
    # reason -- a gate after it would not fire on a laptop at all
    assert (text.index("annual_handover_open() and not a.ack_annual_handover")
            < text.index('get_required_env("AWS_REGION")'))


# -- 7. THE DROP LEDGER: an absence, a defect and a flag are three facts -----------------------------
@pytest.mark.parametrize("cell,kind", [
    ("", "null"), (None, "null"), ("None", "null"), ("nan", "null"), ("N/A", "null"), ("-", "null"),
    ("1.5", "reading"), (" 2,400 ", "reading"), (0, "reading"), (-3.25, "reading"),
    ("abc", "unparseable"), ("1,234 MT", "unparseable"), ("n.a.(p)", "unparseable"),
    ("2026-01-31", "unparseable"), (True, "bool"), (False, "bool"),
])
def test_cell_kind_names_which_kind_of_hole_a_dropped_cell_was(cell, kind):
    assert TR.cell_kind(cell) == kind
    assert (TR.num_or_none(cell) is None) == (kind != "reading")


def test_a_DEFECT_column_is_counted_apart_from_a_NULL_column():
    """``num_or_none`` returns ``None`` for both and the ARRAY is right either way; the LEDGER was not.
    A systematically malformed column dropped every observation into ``dropped_null`` and therefore
    read as a SPARSE column under a word that means "the source declared no value" -- the one shape a
    coverage counter exists to make raisable."""
    d = _months(30)
    v = [float(i) for i in range(30)]
    v[3] = ""                                            # a declared NULL
    v[4] = "12 MT"                                       # a DEFECT
    v[5] = True                                          # a FLAG served as a bool
    st = _row(v, d)
    assert st.coverage["dropped_null"] == 1
    assert st.coverage["dropped_unparseable"] == 1
    assert st.coverage["dropped_bool"] == 1
    assert st.coverage["n_obs"] == 27
    # the total is still the total -- clean_pairs' third element is unchanged in meaning
    assert TR.clean_pairs(v, d)[2] == 3


def test_an_ALL_DEFECT_column_no_longer_wears_the_word_blank():
    """The closed WORD stays ``read_empty`` (``status_word`` splits at the colon, so every consumer
    branches as before); the QUALIFIER stops calling a defect an absence."""
    blank = _row([""] * 20, _months(20))
    defect = _row(["1,2 MT"] * 20, _months(20))
    assert blank.status == "read_empty:all_blank"
    assert defect.status == "read_empty:all_unparseable"
    assert status_word(blank.status) == status_word(defect.status) == "read_empty"


def test_the_history_says_which_kind_of_hole_it_dropped():
    """TWO STAGES, TWO LEDGERS. The ROW cleans the array it builds, so by the time ``state_history``
    reads ``st.inputs`` the values are floats and only the unplaceable LABELS are left for it to drop.
    Fed a bundle straight off the mirror -- which is what a row assembled by another producer could
    hand it -- it counts all three kinds itself and never raises."""
    d = _months(40)
    v = [float(i) for i in range(40)]
    v[7], v[8] = "", "oops"
    d[9] = ""
    st = _row(v, d)
    assert st.coverage["dropped_null"] == 1 and st.coverage["dropped_unparseable"] == 1
    hist = A.state_history(st)
    assert hist["dropped"] == {"null": 0, "unparseable": 0, "bool": 0, "undated": 1}
    assert hist["n_dropped_null"] == 1                    # the total keeps its name and its meaning
    assert len(hist["values"]) == len(hist["dates"]) == 37

    # the RAW bundle, as the mirror serves it: the history is the boundary for whatever reaches it
    key = SeriesKey(ref="oni_climate", commodity="", country="")
    raw = StateRow(key=key, asof=ASOF, table="silver_noaa_oni", metric="oni_anom", cadence="monthly",
                   unit="degC", narrate_unit="degC")
    raw.inputs = {key.label(): {"values": v, "dates": d, "unit": "degC"}}
    h2 = A.state_history(raw, window=24)
    assert h2["dropped"] == {"null": 1, "unparseable": 1, "bool": 0, "undated": 1}
    assert h2["n_dropped_null"] == 3
    assert len(h2["values"]) == len(h2["dates"]) == 37
    assert all(isinstance(x, float) for x in h2["values"])


# -- 8. ONE ALIGNMENT RULE --------------------------------------------------------------------------
def test_the_axis_is_aligned_by_ONE_rule_and_both_builders_take_it():
    """``_period_dates`` trimmed a too-long label axis from the FRONT and ``clean_pairs`` from the END:
    two rules for one alignment is a disagreement about which observation a date belongs to."""
    vals = [1.0, 2.0, 3.0]
    assert TR.align_axis(vals, ["a", "b", "c", "d", "e"]) == ["c", "d", "e"]     # surplus: oldest go
    assert TR.align_axis(vals, ["a"]) == ["a", None, None]                       # short: pad the back
    assert TR.align_axis(vals, ["a", "b", "c"]) == ["a", "b", "c"]
    assert TR.align_axis(vals, None) == [None, None, None]
    # the served builder and the boundary now agree, on the same inputs
    rows = [{"data_date": "2026-0%d-01" % i, "value": "1"} for i in range(1, 6)]
    assert F._period_dates(rows, None, vals, None) == TR.align_axis(
        vals, ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"])
    assert TR.clean_pairs(vals, ["a", "b", "c", "d", "e"])[1] == ["c", "d", "e"]


# -- 9. THE LAST UNGUARDED PARSE ON THE ROW PATH ----------------------------------------------------
def test_a_MALFORMED_knowledge_date_declines_by_name_instead_of_raising():
    """A NULL was always safe here (``""`` is falsy and returns a stated basis); a non-empty label the
    calendar cannot read reached ``date.fromisoformat`` unguarded. The walk fences a raise into a
    ``read_error`` row, so one bad cell silently DEMOTED a real column."""
    class _TS:
        publication_lag_days = 3
        ym_publication_lag_days = None
        period_semantics = "observation"

    kd, basis = F.derive_knowledge_date(_TS(), {"data_date": "2026-13-45"})
    assert kd is None and "cannot read" in basis
    kd, basis = F.derive_knowledge_date(_TS(), {"data_date": "2026-01-31"})
    assert kd == "2026-02-03"
    kd, basis = F.derive_knowledge_date(_TS(), {"data_date": ""})
    assert kd is None and "neither a knowledge date nor a data date" in basis
