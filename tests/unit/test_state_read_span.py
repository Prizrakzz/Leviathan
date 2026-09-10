"""THE READ SPAN -- every cadence reads a span LONGER than the window it is measured over, by that
cadence's own publication slack. The read-span landing.

THE DEFECT THIS DECK EXISTS FOR, MEASURED IN-VPC (board census run #3, job 72fd69e3, the pg mirror at
as-of 2026-09-07, artifacts banked). ``CADENCE_READ_SPAN['monthly']`` was ``('months', 120)`` and
``CADENCE_HISTORY_WINDOW['monthly']`` was ``120`` -- EQUAL. The span is measured back from the AS-OF and
the newest KNOWABLE period sits a publication lag behind it, so the array came back SHORT by the lag:
ONI read 117 months, 2016-09 to 2026-05, against a 120-month window, and ``stats.zscore`` refused with
``history has 117 points, window needs 120``. The row still printed its level, its 92nd percentile (floor
8) and its six-month run beside the refusal -- a standing refused while two neighbouring measures compute
is the tell, and it was permanent: a longer wait moves the as-of and the frontier together.

86 rendered rows across 144 board runs carried it, and EVERY ONE sat on a cadence whose span equalled
its window -- ONI 32, gold_weather_z 25, IOD 12, COT 12, ESR 5. No daily row (5 years for a 250-session
window) and no annual row (the whole history) did.

WHAT IS PINNED HERE, in the order a reader wants it:
  1. the SLACK table exists for every cadence and carries the numbers the landing chose;
  2. the INVARIANT -- ``span >= window + slack`` -- per cadence, over the module's own tables AND over
     ``state_conventions.yaml``'s ``windows:`` block and its per-series ``history_window`` declarations
     (the config_check shape, run here because ``feeders`` must not import yaml for every consumer);
  3. the REPRODUCTION on the ``mirror_lagged`` fixture set: window - 3 knowable monthly points, the z
     REFUSED under the pre-fix table and COMPUTED under the shipped one, on one fixture and one producer;
  4. the PER-SERIES OVERRIDE: a declared window wider than the cadence default widens the read, and the
     memo's read layer partitions on the span so the narrow read is never served to the wide row.

OFFLINE: no pg mirror, no Athena, no network, no clock beyond the as-of each test is handed.
"""
import pytest

from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state.lint import load_conventions

ASOF = "2026-09-07"

#: The pre-fix table, kept HERE and nowhere else: it is the thing the reproduction has to be able to put
#: back, and a fixture that could not restate the defect could not prove it had been fixed.
PRE_FIX_SPAN: dict = {
    "daily": ("years", 5),
    "weekly": ("weeks", 156),
    "weekly_destination": ("weeks", 52),
    "biweekly": ("days", 78 * 14),
    "monthly": ("months", 120),
    "annual": None,
    "release": None,
}


def _put_back(monkeypatch, *, slack: bool):
    """The pre-fix span table, with the shipped slack kept or zeroed.

    TWO PRE-FIX STATES, AND THE DIFFERENCE IS THE WHOLE POINT OF HAVING TWO FENCES.
      * ``slack=True``  -- the span table as it shipped BEFORE, judged against the slack this landing
        declares. This is what :func:`feeders.check_read_spans` must FLAG, and the state a careless
        edit of the span table would actually produce.
      * ``slack=False`` -- span AND slack both put back, which is the estate as it truly behaved: with
        the slack zero, :func:`feeders.read_span` has nothing to widen to and the read is the short one
        the mirror answered. Anything reproducing the DEFECT needs this state, because the widening
        rule alone would otherwise silently repair it and the reproduction would prove nothing."""
    monkeypatch.setattr(F, "CADENCE_READ_SPAN", dict(PRE_FIX_SPAN), raising=True)
    if not slack:
        monkeypatch.setattr(F, "CADENCE_READ_SLACK", {k: 0 for k in F.CADENCE_READ_SLACK},
                            raising=True)


@pytest.fixture()
def pre_fix_table(monkeypatch):
    """The pre-fix SPAN table against the shipped slack -- what the invariant must flag."""
    _put_back(monkeypatch, slack=True)
    return PRE_FIX_SPAN


@pytest.fixture()
def pre_fix(monkeypatch):
    """The estate as it truly behaved before this landing: span == window and no slack to widen to."""
    _put_back(monkeypatch, slack=False)
    return PRE_FIX_SPAN


# ---------------------------------------------------------------------------------------------------
# 1. THE TABLE
# ---------------------------------------------------------------------------------------------------
def test_every_cadence_declares_a_slack():
    """A cadence with a window and a span and NO slack is the defect with a different spelling."""
    assert set(F.CADENCE_READ_SLACK) == set(F.CADENCE_READ_SPAN) == set(F.CADENCE_HISTORY_WINDOW)
    for cadence, slack in F.CADENCE_READ_SLACK.items():
        assert isinstance(slack, int) and slack >= 0, cadence


def test_the_slack_table_is_the_landing_numbers():
    """The numbers, said once here so a change to them is a change to a test as well as to a table."""
    assert F.CADENCE_READ_SLACK == {"daily": 10, "weekly": 8, "weekly_destination": 6,
                                    "biweekly": 4, "monthly": 12, "annual": 1, "release": 0}


def test_the_spans_that_moved_and_the_two_that_did_not():
    """monthly 120 -> 132 months, weekly 156 -> 164 weeks, weekly_destination 52 -> 58 weeks, biweekly
    78 -> 82 fortnights. ``daily`` and ``annual`` are UNCHANGED and were never short."""
    assert F.CADENCE_READ_SPAN["monthly"] == ("months", 132)
    assert F.CADENCE_READ_SPAN["weekly"] == ("weeks", 164)
    assert F.CADENCE_READ_SPAN["weekly_destination"] == ("weeks", 58)
    assert F.CADENCE_READ_SPAN["biweekly"] == ("days", 82 * 14)
    assert F.CADENCE_READ_SPAN["daily"] == PRE_FIX_SPAN["daily"] == ("years", 5)
    assert F.CADENCE_READ_SPAN["annual"] is PRE_FIX_SPAN["annual"] is None


def test_a_span_prices_in_its_own_periods():
    """The invariant cannot be stated in the DECLARED units: daily declares 5 years against a
    250-SESSION window and biweekly declares 1,148 days against an 82-FORTNIGHT one."""
    assert F.read_span_periods("monthly") == 132
    assert F.read_span_periods("weekly") == 164
    assert F.read_span_periods("weekly_destination") == 58
    assert F.read_span_periods("biweekly") == 82
    assert F.read_span_periods("daily") == 1260          # 5 * 252 sessions
    assert F.read_span_periods("annual") is None         # the whole history
    assert F.read_span_periods("release") is None


# ---------------------------------------------------------------------------------------------------
# 2. THE INVARIANT
# ---------------------------------------------------------------------------------------------------
def test_the_invariant_holds_for_every_cadence_that_carries_a_window():
    """The claim, per cadence, in the form the module asserts at import."""
    for cadence, win in F.CADENCE_HISTORY_WINDOW.items():
        span = F.CADENCE_READ_SPAN.get(cadence)
        if not win or span is None:
            continue                                     # `release` has no window; `annual` is unbounded
        have = F.read_span_periods(cadence, span)
        need = int(win) + int(F.CADENCE_READ_SLACK[cadence])
        assert have >= need, (f"cadence {cadence!r}: span {have} periods, window {win} + slack "
                              f"{F.CADENCE_READ_SLACK[cadence]} needs {need}")


def test_the_module_asserts_it_at_import():
    assert F.check_read_spans() == []


def test_the_pre_fix_table_FAILS_the_invariant(pre_fix_table):
    """THE FALSIFIER FOR THE CHECK ITSELF. A pin that passes on the defect it was written for is not a
    pin, and this names the four cadences that were short: the two weekly grains, biweekly and monthly."""
    problems = F.check_read_spans()
    flagged = {p.split("'")[1] for p in problems if "'" in p}
    assert {"monthly", "weekly", "weekly_destination", "biweekly"} <= flagged
    assert "daily" not in flagged and "annual" not in flagged and "release" not in flagged


def test_the_config_windows_and_the_per_series_overrides_are_covered():
    """THE config_check SHAPE, run here. ``state_conventions.yaml`` carries a ``windows:`` block and two
    per-series ``history_window`` declarations (``cot_mm_positioning`` 156 weeks,
    ``psd_ending_stock_su_ratio`` 10 marketing years); ``TABLE_HISTORY_WINDOW`` carries a third
    (``silver_pink_sheet`` 60 months). Every one of them must be readable inside its own read span."""
    doc = load_conventions()
    windows = dict(doc.get("windows") or {})
    conventions = dict(doc.get("conventions") or {})
    assert windows and conventions, "state_conventions.yaml did not load"
    declared = {r: (row or {}).get("history_window")
                for r, row in conventions.items() if (row or {}).get("history_window")}
    assert declared == {"cot_mm_positioning": 156, "psd_ending_stock_su_ratio": 10}, declared
    assert F.check_read_spans(windows=windows, conventions=conventions) == []


def test_the_config_windows_pin_fails_on_the_pre_fix_table(pre_fix_table):
    doc = load_conventions()
    assert F.check_read_spans(windows=dict(doc.get("windows") or {}),
                              conventions=dict(doc.get("conventions") or {})) != []


# ---------------------------------------------------------------------------------------------------
# 3. THE PERIOD START THE READ ACTUALLY CARRIES
# ---------------------------------------------------------------------------------------------------
def test_period_start_is_the_widened_span():
    """The dates, at the as-of the census measured. 132 months back from 2026-09-07 is 2015-09-01; the
    pre-fix 120 was 2016-09-01, and the ONI history that came back started at 2016-09."""
    assert F._period_start(ASOF, "monthly") == "2015-09-01"
    assert F._period_start(ASOF, "weekly") == "2023-07-17"
    assert F._period_start(ASOF, "weekly_destination") == "2025-07-28"
    assert F._period_start(ASOF, "daily") == "2021-09-07"
    assert F._period_start(ASOF, "annual") is None
    assert F._period_start(ASOF, "release") is None


def test_period_start_pre_fix_is_the_month_the_mirror_started_at(pre_fix):
    assert F._period_start(ASOF, "monthly") == "2016-09-01"


def test_the_board_spec_carries_that_period_start_and_the_cap():
    spec = F.board_spec("silver_noaa_oni", "oni_anom", "soybeans_cbot", None, ASOF, "monthly")
    assert spec.period_start == "2015-09-01"
    assert spec.limit == F.READ_LIMIT == 5000
    assert spec.agg == "series"


def test_the_5000_row_cap_cannot_bind_a_monthly_read_at_132_months():
    """STATED AND PROVED RATHER THAN ASSUMED. A monthly series read is ONE row per period per resolved
    (commodity, country) scope -- ``agg='series'`` over a card whose period key is (year, month) -- so a
    132-month read fetches at most 132 rows against a 5,000-row cap: 37.9x of headroom, and the widening
    added 12 rows. The cap is a row count and the span is a calendar bound; the only monthly read that
    could reach 5,000 would need 38 rows per month on one scope, which is a cross-section, and a
    cross-section is collapsed by ``cascade._pace_series`` to one value per period before any window is
    measured. The GRAIN that does carry many rows per period is the destination grain, and it has its own
    cadence, its own 4-week slack and its own probe."""
    months = F.read_span_periods("monthly")
    assert months == 132 and months * 1 < F.READ_LIMIT
    assert F.READ_LIMIT / float(months) > 37.0
    assert F.read_span_periods("monthly", PRE_FIX_SPAN["monthly"]) == 120
    assert months - 120 == 12                              # the widening's whole row cost, per scope


# ---------------------------------------------------------------------------------------------------
# 4. THE REPRODUCTION -- one fixture, one producer, before and after
# ---------------------------------------------------------------------------------------------------
def _lagged(name="oni_climate"):
    from leviathan.graphrag.state.__main__ import _fixtures, _mirror_lagged
    return _mirror_lagged(_fixtures())[name]


def _row(spec, ref="oni_climate", cadence="monthly", table="silver_noaa_oni", metric="oni_anom"):
    """The row the fixture set produces, through the SHIPPED arithmetic half of the producer."""
    return F.state_from_arrays(ref, list(spec["values"]), list(spec["dates"]), cadence=cadence,
                               asof=ASOF, commodity="soybeans_cbot", country=None,
                               unit=spec.get("unit", ""), narrate_unit=spec.get("narrate_unit", ""),
                               table=table, metric=metric)


def test_the_fixture_carries_exactly_window_minus_three_monthly_points_before_the_fix(pre_fix):
    """THE REPRODUCTION'S OWN BAR: window - 3 knowable points, and the SAME 117 the mirror served, over
    the SAME months (2016-09 to 2026-05). The three months are ONI's own 36-day ym lag rounded to the
    month plus the two months the mirror itself was behind its PIT frontier."""
    spec = _lagged()
    assert len(spec["values"]) == F.CADENCE_HISTORY_WINDOW["monthly"] - 3 == 117
    assert spec["dates"][0][:7] == "2016-09" and spec["dates"][-1][:7] == "2026-05"


def test_the_oni_z_is_REFUSED_before_the_fix(pre_fix):
    """The measured banner, offline: the z declines, the percentile and the run compute beside it."""
    st = _row(_lagged())
    assert st.z["declined"] is True
    assert "117 points" in str(st.z["reason"]) and "window needs 120" in str(st.z["reason"])
    assert st.percentile["declined"] is False               # floor 8 -- it computes on 117 points
    assert st.run and st.run["length"] >= 1                 # and so does the run
    assert st.window_note == "120 months"                   # the row still NAMES the window it lost


def test_the_oni_z_COMPUTES_after_the_fix():
    """The same fixture builder, the same producer, the shipped table: 129 points, a computed z over the
    120-month window it names."""
    spec = _lagged()
    assert len(spec["values"]) == 129 >= F.CADENCE_HISTORY_WINDOW["monthly"]
    assert spec["dates"][0][:7] == "2015-09" and spec["dates"][-1][:7] == "2026-05"
    st = _row(spec)
    assert st.z["declined"] is False
    assert st.z["n"] == 120 and st.z["window"] == 120
    assert st.window_note == "120 months"


@pytest.mark.parametrize("ref,cadence,table,metric,win", [
    ("iod_climate", "monthly", "silver_noaa_iod", "dmi_value", 120),
    ("drought_z", "monthly", "gold_weather_z", "drought_z", 120),
    ("mpob_ending_stocks", "monthly", "silver_mpob", "ending_stocks", 120),
    ("cot_mm_positioning", "weekly", "silver_cot", "mm_net", 156),
])
def test_every_other_short_cadence_flips_the_same_way(ref, cadence, table, metric, win, monkeypatch):
    """THE BLAST RADIUS, one row per family the in-VPC census counted: IOD, gold_weather_z, MPOB, COT."""
    after = _row(_lagged(ref), ref=ref, cadence=cadence, table=table, metric=metric)
    assert after.z["declined"] is False, ref
    monkeypatch.setattr(F, "CADENCE_READ_SPAN", dict(PRE_FIX_SPAN), raising=True)
    monkeypatch.setattr(F, "CADENCE_READ_SLACK", {k: 0 for k in F.CADENCE_READ_SLACK}, raising=True)
    before = _row(_lagged(ref), ref=ref, cadence=cadence, table=table, metric=metric)
    assert before.z["declined"] is True, ref
    assert f"window needs {win}" in str(before.z["reason"]), ref


def test_the_destination_slack_is_SIX_and_a_four_would_not_have_been_enough(monkeypatch):
    """THE ONE SLACK THAT IS A MEASURED CHOICE BETWEEN TWO FAILURES, pinned with its own falsifier.

    The worst frontier on the destination grain is corn's ESR week 2026-08-06 at as-of 2026-09-07 --
    32 days, 4.57 weeks -- so the fixture carries five whole weeks of lag. At the pre-fix 52-week span
    the read returns 47 points for a 52-week window; at a 4-week slack it returns 51 and the standing
    STILL refuses; at the shipped 6 it returns 53 and computes. A number one short of the defect is not
    a fix, and this is the test that says so."""
    def _esr(span_weeks, slack):
        monkeypatch.setattr(F, "CADENCE_READ_SPAN",
                            dict(F.CADENCE_READ_SPAN, weekly_destination=("weeks", span_weeks)))
        monkeypatch.setattr(F, "CADENCE_READ_SLACK",
                            dict(F.CADENCE_READ_SLACK, weekly_destination=slack))
        spec = _lagged("esr_exports")
        return len(spec["values"]), _row(spec, ref="esr_exports", cadence="weekly_destination",
                                         table="silver_esr", metric="exports")

    n52, pre = _esr(52, 0)
    n56, four = _esr(56, 4)
    n58, six = _esr(58, 6)
    assert (n52, n56, n58) == (47, 51, 53)
    assert pre.z["declined"] is True and "47 points" in str(pre.z["reason"])
    assert four.z["declined"] is True and "51 points" in str(four.z["reason"])
    assert six.z["declined"] is False
    assert F.CADENCE_READ_SLACK["weekly_destination"] == 6


def test_the_pink_sheet_escapes_both_ways_and_so_do_daily_and_annual():
    """THE CONTROLS, and they are what make the flips above a SPAN defect rather than a thin-data one.
    ``brent_crude_z`` sits on ``silver_pink_sheet``, whose ``TABLE_HISTORY_WINDOW`` is 60 months, so its
    z computes on the SAME 117-point array that refuses ONI's. The daily cards read five years for a
    250-session window."""
    from leviathan.graphrag.state.__main__ import _fixtures, _mirror_lagged
    fx = _mirror_lagged(_fixtures())
    brent = _row(fx["brent_crude_z"], ref="brent_crude_z", table="silver_pink_sheet",
                 metric="crude_brent")
    assert brent.z["declined"] is False and brent.window_note == "60 months"
    fx_daily = _row(fx["fred_fx_macro"], ref="fred_fx_macro", cadence="daily",
                    table="silver_fred_fx", metric="fx_index")
    assert fx_daily.z["declined"] is False and fx_daily.z["n"] == 250


def test_the_lagged_set_is_a_function_of_the_live_table_not_a_copy_of_it(monkeypatch):
    """A fixture that computed its OWN ``asof - 120 months`` would keep passing after the table was
    fixed and would grade nothing. Widen the table and the fixture widens with it."""
    from leviathan.graphrag.state.__main__ import _fixtures, _mirror_lagged
    monkeypatch.setattr(F, "CADENCE_READ_SPAN", dict(F.CADENCE_READ_SPAN, monthly=("months", 240)),
                        raising=True)
    assert len(_mirror_lagged(_fixtures())["oni_climate"]["values"]) == 237     # 240 - the 3-month lag


def test_the_fixture_set_is_on_the_roster_and_the_clean_set_is_untouched():
    from leviathan.graphrag.state.__main__ import FIXTURE_SETS, _fixtures, fixtures
    assert "mirror_lagged" in FIXTURE_SETS
    assert fixtures("default") == _fixtures()                # the default set did not move
    lagged = fixtures("mirror_lagged")
    assert set(lagged) == set(_fixtures())                   # same roster, shorter arrays
    assert len(lagged["oni_climate"]["values"]) < len(_fixtures()["oni_climate"]["values"])


# ---------------------------------------------------------------------------------------------------
# 4b. THE SAME FLIP ON THE **SERVED** PATH -- the real SQL, the real point-in-time oracle
# ---------------------------------------------------------------------------------------------------
class _Node:
    """The census's ``_LegNode`` stand-in, the shape ``series_key_for`` reads."""
    __slots__ = ("contract", "id", "prior", "evidence")

    def __init__(self, contract, driver_id, ref, region=None):
        self.contract, self.id = contract, driver_id
        self.prior = {"silver_ref": ref, "region": region}
        self.evidence = []


def _mirror_oni_rows():
    """``silver_noaa_oni`` as the mirror actually held it on run #3: monthly from 1950-01 to 2026-05.

    The FRONTIER IS THE FIXTURE'S WHOLE POINT. ONI's own ``ym_publication_lag_days`` is 36, so at as-of
    2026-09-07 the PIT rule would admit 2026-07 -- the mirror simply did not have it. Serving rows only
    through 2026-05 is that staleness, and it is what makes 117 the number the read comes back with."""
    import math
    out, y, m = [], 1950, 1
    while (y, m) <= (2026, 5):
        i = (y - 1950) * 12 + (m - 1)
        out.append({"year": y, "month": m,
                    "value": str(round(1.15 * math.sin(2 * math.pi * i / 44.0)
                                       + 0.45 * math.sin(2 * math.pi * i / 131.0), 3))})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _served_oni_row():
    """``series_state`` end to end: ``build_sql`` compiles the board's spec, ``query.apply_pit_filter``
    runs the SQL's OWN oracle over the canned rows (``period_start`` included), and the whole producer
    -- collapse, transforms, derivation records -- runs on what comes back."""
    from leviathan.graphrag.numbers.registry import load_registry
    rows = _mirror_oni_rows()
    ts = load_registry().get("silver_noaa_oni")
    spec = F.board_spec("silver_noaa_oni", "oni_anom", "soybeans_cbot", None, ASOF, "monthly", 120)
    qfn = F.fixture_query_fn({"silver_noaa_oni": rows}, pit={"silver_noaa_oni": (spec, ts)})
    F.cache_clear()
    return F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), ASOF,
                          qfn=qfn, windows={"monthly": 120},
                          silver_status="available"), spec


def test_the_served_read_refuses_the_standing_before_the_fix(pre_fix):
    """THE MEASURED IN-VPC ROW, OFFLINE AND END TO END: 117 points from 2016-09, and the same refusal
    string the census banked -- ``history has 117 points, window needs 120``."""
    st, spec = _served_oni_row()
    assert spec.period_start == "2016-09-01"
    assert st.coverage["n_obs"] == 117
    assert st.coverage["history_start"][:7] == "2016-09"
    assert st.coverage["history_end"][:7] == "2026-05"
    assert st.z["declined"] is True and "117 points" in str(st.z["reason"])
    assert st.percentile["declined"] is False and st.status == "ok"


def test_the_served_read_computes_the_standing_after_the_fix():
    """The same rows, the same producer, the shipped span: 129 points and a z over its 120-month
    window. Nothing about the DATA changed -- only how far back the read reached."""
    st, spec = _served_oni_row()
    assert spec.period_start == "2015-09-01"
    assert st.coverage["n_obs"] == 129
    assert st.coverage["history_start"][:7] == "2015-09"
    assert st.z["declined"] is False and st.z["n"] == 120 and st.z["window"] == 120
    assert st.window_note == "120 months"
    assert st.reads == 1                                     # and it is still ONE read


# ---------------------------------------------------------------------------------------------------
# 5. THE PER-SERIES OVERRIDE
# ---------------------------------------------------------------------------------------------------
def test_a_declared_window_wider_than_the_cadence_default_widens_the_read():
    """The rule the cadence table cannot keep on its own: a series declaring 200 weeks is read over
    208, not over the cadence's 164 -- otherwise it would refuse its own standing for ever."""
    assert F.read_span("weekly", 200) == ("weeks", 208)
    assert F.read_span_periods("weekly", F.read_span("weekly", 200)) >= 200 + 8
    assert F.read_span("monthly", 400) == ("months", 412)
    assert F._period_start(ASOF, "weekly", 200) < F._period_start(ASOF, "weekly")


def test_it_only_ever_widens():
    """A window SHORTER than the cadence default keeps the full span: the pink sheet's 60 months is read
    over 132, because a narrower read would save rows nobody is short of."""
    assert F.read_span("monthly", 60) == F.read_span("monthly") == ("months", 132)
    assert F.read_span("daily", 1) == ("years", 5)
    assert F.read_span("annual", 10_000) is None             # the whole history is already unbounded


def test_the_board_spec_honours_the_declared_window():
    wide = F.board_spec("silver_cot", "mm_net", "soybeans_cbot", None, ASOF, "weekly", 200)
    plain = F.board_spec("silver_cot", "mm_net", "soybeans_cbot", None, ASOF, "weekly")
    assert wide.period_start < plain.period_start


def test_the_memo_read_layer_partitions_on_the_span():
    """Two rows on ONE series key, one cadence and one read shape can now issue two different
    ``period_start`` values. Without the span on the key the NARROW read would be served to the WIDE
    row -- a short array under a long window's label, which is this landing's own defect re-entering
    through the memo."""
    from leviathan.graphrag.state.rows import SeriesKey
    key = SeriesKey(ref="cot_mm_positioning", commodity="soybeans_cbot", country="", metric="mm_net")
    args = (key, "silver_cot", "mm_net", ASOF, "weekly", "nf_all", True, "")
    narrow = F.series_read_key(*args, F.read_span("weekly", 156))
    wide = F.series_read_key(*args, F.read_span("weekly", 200))
    assert narrow != wide
    assert F.series_read_key(*args, F.read_span("weekly", 156)) == narrow      # and it is stable


def test_the_conventions_declared_window_reaches_the_read():
    """``history_window()`` does not consult the convention row, so ``series_state`` takes the WIDER of
    the two for the read and leaves the MEASURED window exactly what it was. Pinned on the shape rather
    than on the served path: every declared window on the estate today is at or below its cadence
    default, so this branch is a no-op at this landing and a fence for the next one."""
    doc = load_conventions()
    conv = (doc.get("conventions") or {}).get("cot_mm_positioning") or {}
    win = F.history_window("weekly", "silver_cot", dict(doc.get("windows") or {}))
    read_win = max(int(win or 0), int(conv.get("history_window") or 0))
    assert win == 156 and read_win == 156                    # equal today, by measurement not by luck
    assert F.read_span("weekly", read_win) == F.CADENCE_READ_SPAN["weekly"]
    assert F.read_span("weekly", max(win, 300)) == ("weeks", 308)
