"""``TableSpec.ym_publication_lag_days`` -- landed, declared, and READ BY NOTHING at S0.

STATE ENGINE DESIGN sec 1.4 (D21, D23), sitting S0. The field exists because ``TableSpec`` is
``extra="forbid"``: the key on the card and the field on the model must land in ONE commit or every
registry load raises. Nothing consumes it until the threaded ``ym_lag`` kwarg arrives at S1, so the
whole deck below is one claim said several ways -- **every compiled SQL string and every oracle verdict
is byte-identical with the field present**.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from leviathan.graphrag.numbers.query import NumberQuery, apply_pit_filter, build_sql
from leviathan.graphrag.numbers.registry import (
    Metric,
    NumbersRegistry,
    TableSpec,
    check_metric_lags,
    lag_days_for,
    load_registry,
)

#: silver_noaa_oni was 15 at the first S0 landing -- a DECLARATION, corrected to 36 at the S0 review
#: against the design's own publisher read. The arithmetic and its falsifier are one test down.
#:
#: gold_weather_z was 7 until 2026-09-11, and the 7 was never measured against a producer -- the card's
#: own note said so ("UNVERIFIED ... S4's census measures it"). What the measurement found was not a
#: wrong number but a wrong SHAPE: this card's metrics are fed by TWO sources ~40 days apart in release
#: cadence, and `weather_z._complete_months_only` gates month completeness PER SOURCE SLICE, so the four
#: NASA metrics really do emit a month CHIRPS has not published. The card default is now the NASA value
#: (3 d measured + a 2 d margin) and drought_z carries its own 25; :data:`WEATHER_METRIC_LAGS` is the
#: per-metric pin and the reason this one is only half the story.
YM_BOARD_CARDS = {"silver_noaa_oni": 36, "silver_noaa_iod": 45, "gold_weather_z": 5}

#: The per-metric truth on the ONE card that declares one. MEASURED 2026-09-11:
#:   NASA POWER AG -- the September window fetched that day returned 11 day keys, 8 of them real, last
#:     real day 2026-09-08: the endpoint fills its trailing ~3 days with -999. Source lag 3 d; the card
#:     default is 3 + a 2 d margin.
#:   CHIRPS v2.0 FINAL -- HTTP HEAD against .../global_daily/tifs/p05/2026/: every day of 2026-07 there
#:     (the block was already complete on 2026-08-22, day 22 past July's month-end), every day of
#:     2026-08 a 404 on 2026-09-11, day 11 past August's. It publishes the month AS A BLOCK.
#: WHAT THOSE TWO CHIRPS OBSERVATIONS BOUND (corrected 2026-09-11, same day, by the verify pass):
#: PRESENT at day 22 is an UPPER bound -- the block was there by then and may have landed earlier, so
#: lag <= 22 -- and ABSENT at day 11 is a LOWER bound, lag > 11. The lag is 11 < lag <= 22 and the
#: declaration is 25: the upper bound plus a 3-day margin (a lag is a WITHHOLDING -- long is safe,
#: short is a leak). THE 45 THIS REPLACES WAS A MISREADING of the same two numbers, reached by analogy
#: to the slow monthly ``silver_noaa_iod`` sibling while the measurement in hand already bounded the
#: lag at 22. Nothing new was measured to correct it; the arithmetic was re-read.
#: AND A FASTER PRODUCT EXISTS, unread here (found 2026-09-11): CHIRPS v2.0 also publishes a PRELIM
#: daily series at .../CHIRPS-2.0/prelim/global_daily/tifs/p05/2026/ , current to 2026-09-05 with all
#: 31 August days present. A follow-up fetcher lane reads it; after that this metric's lag is ~5 and
#: the 25 becomes the FINAL product's revision horizon rather than its first print.
#: EVERY metric the card declares is listed, not just the interesting ones: the failure mode of a
#: per-metric lag is an ABSENT declaration on a metric nobody enumerated, so a pin that named only
#: drought_z would grade the half that cannot go wrong silently.
WEATHER_METRIC_LAGS = {
    # CHIRPS -- the reading and its two aggregates, one source, one promise
    "drought_z": 25, "drought_z_tail_share": 25, "drought_z_cells": 25,
    # NASA POWER -- four readings and their aggregates
    "tmax_anomaly": 5, "tmax_anomaly_tail_share": 5, "tmax_anomaly_cells": 5,
    "gdd_z": 5, "gdd_z_tail_share": 5, "gdd_z_cells": 5,
    "heat_stress_z": 5, "heat_stress_z_tail_share": 5, "heat_stress_z_cells": 5,
    "frost_event_flag": 5, "frost_event_share": 5, "frost_event_flag_cells": 5,
}


def test_the_field_defaults_to_none_not_zero():
    ts = TableSpec(id="x", description="d", shape="wide")
    assert ts.ym_publication_lag_days is None, \
        "None is UNDECLARED; 0 would be a positive claim that the source prints on the data month's " \
        "last day, which no card in this estate has measured"


def test_the_three_board_cards_declare_their_lag():
    cards = load_registry().tables
    for tid, want in YM_BOARD_CARDS.items():
        assert cards[tid].ym_publication_lag_days == want, tid
        assert cards[tid].knowledge_semantics == "year_month", tid


def test_no_other_card_declares_one_and_the_two_that_could_are_named():
    cards = load_registry().tables
    declared = {t for t, ts in cards.items() if ts.ym_publication_lag_days is not None}
    assert declared == set(YM_BOARD_CARDS)
    ym = {t for t, ts in cards.items() if ts.knowledge_semantics == "year_month"}
    assert ym - declared == {"silver_mpoc_stock_comparison", "silver_mpoc_trade_stats_monthly"}, \
        "the estate's year_month roster moved; state/lint.py's warning clause names the undeclared ones"


def test_the_oni_lag_is_the_center_month_arithmetic_and_not_the_publishers_bare_print_lag():
    """36 is the PRODUCT of two measured facts, and this is where either one breaking is caught.

    (1) THE PUBLISHER: CPC posts the ONI table "by the 5th of each month" (design APPENDIX B DELTA
        PASS 1 item B4.1, cpc.ncep.noaa.gov/.../enso/oni/v6/, read 2026-09-08).
    (2) THE ROW KEY: a row's ``month`` is the 3-month season's CENTER month, so the row for month M
        rides the print that lands by the 5th of M+2 -- 33 to 36 days after M's own month-end.

    The same read is the falsifier: on 2026-09-08 the newest published row was JJA 2026 = (2026, 7)
    and JAS = (2026, 8) was blank. Any lag that admits (2026, 8) that day is serving a month the
    publisher had not printed -- which is exactly what a bare 5 and the first landing's 15 both do.
    """
    from leviathan.transforms.raw_to_bronze.noaa_oni import SEASON_TO_MONTH
    assert SEASON_TO_MONTH["JJA"] == 7, "the CENTER-month stamp is half of this arithmetic"

    lag = load_registry().get("silver_noaa_oni").ym_publication_lag_days

    def admitted_from(year: int, month: int, days: int) -> date:
        return date(year, month, monthrange(year, month)[1]) + timedelta(days=days)

    read_day = date(2026, 9, 8)
    printed_month_8 = date(2026, 10, 5)       # the 5th of M+2, in the publisher's own words
    assert admitted_from(2026, 7, lag) <= read_day, "JJA 2026 WAS on the publisher's page that day"
    assert admitted_from(2026, 8, lag) > read_day, "JAS 2026 was NOT, and the lag must withhold it"
    assert admitted_from(2026, 8, lag) >= printed_month_8,         "and it must stay withheld until the print that carries it"
    # The two values this deck would previously have accepted, each shown serving (2026, 8) before the
    # print that carries it. A bare 5 -- the delta pass's own headline, which is the PRINT lag and not
    # this row's lag -- serves it before the seat had even watched it not exist.
    for leaky, first_served in ((5, date(2026, 9, 5)), (15, date(2026, 9, 15))):
        assert admitted_from(2026, 8, leaky) == first_served
        assert first_served < printed_month_8
    assert admitted_from(2026, 8, 5) <= read_day

    # a lag is a WITHHOLDING, so being a few days long is safe and being short is not; 36 is the long
    # end of the 33-36 day span (33 falls in a non-leap February).
    spans = {admitted_from(2025, m, lag).day for m in range(1, 13)}
    assert lag >= 33 and max(spans) <= 8, spans


# ── THE PER-METRIC LAG (2026-09-11) ─────────────────────────────────────────────────────────────────
class TestPerMetricLag:
    """``Metric.ym_publication_lag_days`` -- one card, two sources, two point-in-time promises."""

    def test_the_metric_override_wins_and_EVERY_metric_declares_its_own_explicitly(self):
        """Clause 5 (2026-09-11): on a card carrying any override, NO metric inherits by silence, so
        the resolved map below is also the DECLARED map -- every entry is written in the overlay."""
        ts = load_registry().get("gold_weather_z")
        assert ts.ym_publication_lag_days == 5, "the CARD default is the NASA value"
        got = {m: lag_days_for(ts, m) for m in ts.metrics}
        assert got == WEATHER_METRIC_LAGS, sorted(set(got.items()) ^ set(WEATHER_METRIC_LAGS.items()))
        declared = {m: getattr(spec, "ym_publication_lag_days", None) for m, spec in ts.metrics.items()}
        assert declared == WEATHER_METRIC_LAGS, \
            "a metric resolving to the card default by SILENCE is what clause 5 forbids"

    def test_the_two_sources_land_on_DIFFERENT_knowable_months_which_is_the_whole_point(self):
        """If both lags placed the same month the declaration would be decoration. MEASURED at the
        wall clock the wave was built on: NASA's 5 admits 2026-08 and CHIRPS' 25 admits 2026-07 --
        one month apart, on one card, for the same as-of. (Under the 45 this corrects, the gap read
        as two months; one month is the gap the bounded measurement supports, and a gap of one is
        still the whole point -- the four NASA metrics emit a month CHIRPS has not printed.)"""
        from leviathan.graphrag.numbers.query import _ym_lagged_asof_ym
        assert _ym_lagged_asof_ym("2026-09-11", 5) == 202608
        assert _ym_lagged_asof_ym("2026-09-11", 25) == 202607
        # and the 7 the card default replaces is indistinguishable from the NASA value AT THIS AS-OF,
        # which is a fact about this date and NOT the general claim the old comment made here
        # ("every lag from 1 to 28 places the same prior month"). That claim is REFUTED: the two lags
        # place different months on 24 days of 2026 -- see the boundary-day test below, which is where
        # the measurement lives.
        assert _ym_lagged_asof_ym("2026-09-11", 7) == _ym_lagged_asof_ym("2026-09-11", 5)

    def test_two_lags_inside_one_month_DO_place_different_months_on_the_boundary_days(self):
        """THE REFUTED CLAIM, restated as the measurement that refutes it.

        The card comment and this deck both said "on a MONTHLY axis every lag from 1 to 28 places the
        same prior month", and used it to argue that only "one month back" and "two months back" are
        distinguishable. FALSE, and falsifiable from the arithmetic alone: ``_ym_lagged_asof_ym``
        subtracts the lag and then asks whether the SHIFTED date's month has ENDED, so two lags
        straddle a month boundary whenever they straddle a month-end. MEASURED over all 365 days of
        2026 for the card's own pair (5 and 7): they disagree on 24 days -- the 5th and 6th of every
        month -- and agree on the other 341.

        WHY IT MATTERS beyond the correction: it means a lag is NOT a free choice inside a 28-day
        band, so "round it up for safety" moves the served month on real dates. The margins this
        estate adds (NASA 3 -> 5, CHIRPS 22 -> 25) are deliberate WITHHOLDINGS that cost a month on
        those boundary days, not no-ops."""
        from leviathan.graphrag.numbers.query import _ym_lagged_asof_ym
        d, disagree = date(2026, 1, 1), []
        while d < date(2027, 1, 1):
            s = d.isoformat()
            if _ym_lagged_asof_ym(s, 5) != _ym_lagged_asof_ym(s, 7):
                disagree.append(s)
            d += timedelta(days=1)
        assert len(disagree) == 24 and [s[-2:] for s in disagree] == ["05", "06"] * 12, disagree
        # the boundary itself, spelled out on one pair of days rather than left to the loop
        assert _ym_lagged_asof_ym("2026-03-05", 5) == 202602    # 2026-03-05 - 5 d = 2026-02-28 (END)
        assert _ym_lagged_asof_ym("2026-03-05", 7) == 202601    # 2026-03-05 - 7 d = 2026-02-26
        # and 1 vs 28 -- the pair the refuted claim named explicitly -- disagree on far more than none
        wide = sum(_ym_lagged_asof_ym((date(2026, 1, 1) + timedelta(days=i)).isoformat(), 1) !=
                   _ym_lagged_asof_ym((date(2026, 1, 1) + timedelta(days=i)).isoformat(), 28)
                   for i in range(365))
        assert wide > 0, "'every lag from 1 to 28 places the same prior month' was never true"

    def test_a_metric_the_card_does_not_name_and_an_empty_metric_both_fall_to_the_card_default(self):
        ts = load_registry().get("gold_weather_z")
        assert lag_days_for(ts, "not_a_metric") == 5
        assert lag_days_for(ts, "") == 5 and lag_days_for(ts, None) == 5

    def test_a_card_with_no_metrics_dict_at_all_is_read_not_raised_on(self):
        """The gate's freshness stage builds SimpleNamespace card doubles with no ``metrics``; a rule
        that raised on one would be a telemetry stage deciding a gate."""
        import types
        assert lag_days_for(types.SimpleNamespace(ym_publication_lag_days=9), "drought_z") == 9
        assert lag_days_for(types.SimpleNamespace(), "drought_z") is None

    def test_undeclared_stays_None_and_is_never_coerced_to_zero(self):
        """Same reading the card-level field takes: absent is "no promise", not "prints on month-end"."""
        assert Metric().ym_publication_lag_days is None
        ts = TableSpec(id="x", description="d", shape="tall",
                       metrics={"m": Metric(ym_publication_lag_days=0)})
        assert lag_days_for(ts, "m") == 0, "a declared 0 is a real declaration and is honoured"
        assert lag_days_for(ts, "absent") is None

    def test_the_estate_has_exactly_ONE_card_declaring_per_metric_lags(self):
        reg = load_registry()
        declaring = sorted(t for t, ts in reg.tables.items()
                           if any(getattr(m, "ym_publication_lag_days", None) is not None
                                  for m in (ts.metrics or {}).values()))
        assert declaring == ["gold_weather_z"], \
            "a new per-metric card landed -- give it a pin here and re-read check_metric_lags"

    def test_the_lint_is_green_on_the_live_registry(self):
        assert check_metric_lags() == []

    def test_the_lint_catches_an_override_on_a_card_that_is_not_year_month(self):
        reg = load_registry()
        bad = reg.get("gold_weather_z").model_copy(update={"knowledge_semantics": "data_date"})
        errs = check_metric_lags(reg.model_copy(update={"tables": {"gold_weather_z": bad}}))
        assert any("shifts only the year_month branch" in e for e in errs), errs

    def test_the_lint_catches_a_card_default_that_went_missing_under_its_own_overrides(self):
        reg = load_registry()
        bad = reg.get("gold_weather_z").model_copy(update={"ym_publication_lag_days": None})
        errs = check_metric_lags(reg.model_copy(update={"tables": {"gold_weather_z": bad}}))
        assert any("the CARD declares none" in e for e in errs), errs

    def test_the_lint_catches_a_DERIVED_SIBLING_left_behind_on_the_default(self):
        """THE CLAUSE THAT EARNS THE LINT, and the defect it is shaped to. ``drought_z_tail_share`` is
        the share of basin cells in ``drought_z``'s tail -- same CHIRPS cells, same producer, same
        month block. Left on the card default it would be served forty days before the rain that made
        it was published, and nothing else in the stack could see it: the value is well formed, the
        SQL compiles, and the row simply arrives early."""
        reg = load_registry()
        ts = reg.get("gold_weather_z")
        metrics = dict(ts.metrics)
        metrics["drought_z_tail_share"] = metrics["drought_z_tail_share"].model_copy(
            update={"ym_publication_lag_days": None})
        bad = ts.model_copy(update={"metrics": metrics})
        errs = check_metric_lags(reg.model_copy(update={"tables": {"gold_weather_z": bad}}))
        assert any("drought_z_tail_share" in e and "same stem" in e for e in errs), errs

    def test_the_sibling_clause_does_not_fire_on_an_UNRELATED_metric_name(self):
        """``frost_event_share`` is not ``frost_event_flag``'s stem-child and must not be dragged in --
        a lint that over-matched would force a false declaration onto a metric with no such promise."""
        assert not any("frost_event_share" in e for e in check_metric_lags())

    # ── CLAUSE 5: no silent inheritance on a card that declares any override ────────────────────
    def test_clause_5_bites_on_a_NEW_metric_that_declares_nothing(self):
        """THE HOLE CLAUSE 4 LEAVES, and the one the next lane walks straight into. Clause 4 only
        grades metrics whose id starts with a DECLARING metric's stem, so a brand-new reading fed by
        the slow source -- a second CHIRPS metric on this card, which is exactly what the prelim-daily
        fetcher lane plans -- passes with no override at all and silently inherits the FAST source's
        5 days, serving up to a month before its block prints. Clause 5 is the direction clause 4
        does not cover: once one metric narrows the promise, silence is no longer a reading."""
        reg = load_registry()
        ts = reg.get("gold_weather_z")
        metrics = dict(ts.metrics)
        metrics["basin_rainfall_z"] = Metric(label="a new CHIRPS reading", unit="z", desc="new")
        bad = ts.model_copy(update={"metrics": metrics})
        errs = check_metric_lags(reg.model_copy(update={"tables": {"gold_weather_z": bad}}))
        assert any("basin_rainfall_z" in e and "NO ym_publication_lag_days of their own" in e
                   for e in errs), errs

    def test_clause_5_bites_when_the_STEM_drops_its_own_override_and_the_siblings_keep_theirs(self):
        """THE OTHER DIRECTION, and clause 4 is blind to it by construction: clause 4 iterates the
        DECLARING metrics and looks DOWN at their stem-children, so a stem that declares nothing is
        never a stem. Strip ``drought_z``'s own 25 and the two aggregates keep theirs: the reading
        would be served on the NASA promise while its own tail-share and cell count were withheld to
        the CHIRPS one -- one source, one month block, two answers in the same board row."""
        reg = load_registry()
        ts = reg.get("gold_weather_z")
        metrics = dict(ts.metrics)
        metrics["drought_z"] = metrics["drought_z"].model_copy(
            update={"ym_publication_lag_days": None})
        bad = ts.model_copy(update={"metrics": metrics})
        errs = check_metric_lags(reg.model_copy(update={"tables": {"gold_weather_z": bad}}))
        assert any("drought_z" in e and "NO ym_publication_lag_days of their own" in e
                   for e in errs), errs
        assert not any("same stem" in e for e in errs), \
            "clause 4 is silent here -- that silence is the whole reason clause 5 exists"

    def test_clause_5_reads_a_declared_ZERO_as_a_DECLARATION_and_stays_quiet(self):
        """``0`` is a real promise ("this source prints on the data month's last day") and ``None`` is
        the absence. A clause 5 written with a falsy test rather than ``is None`` would demand a
        redeclaration from the one metric that had been most explicit -- the same confusion the gate's
        ``_metric_lags`` filter was fixed for on this date."""
        ts = TableSpec(id="x", description="d", shape="tall", knowledge_semantics="year_month",
                       year_col="year", month_col="month", metric_col="metric",
                       ym_publication_lag_days=5,
                       metrics={"a": Metric(ym_publication_lag_days=0),
                                "b": Metric(ym_publication_lag_days=25)})
        assert check_metric_lags(NumbersRegistry(tables={"x": ts})) == []
        assert lag_days_for(ts, "a") == 0

    def test_clause_5_is_SILENT_on_every_card_that_declares_no_override_at_all(self):
        """The clause is scoped by the ``if not declared: continue`` above it, and the estate is
        almost entirely such cards. MEASURED: with the one declaring card removed the lint is empty,
        so no card in the estate is being asked to declare a lag it never promised."""
        reg = load_registry()
        rest = {t: ts for t, ts in reg.tables.items() if t != "gold_weather_z"}
        assert check_metric_lags(reg.model_copy(update={"tables": rest})) == []
        assert any((ts.metrics or {}) and ts.knowledge_semantics == "year_month"
                   for ts in rest.values()), "the premise: other year_month cards with metrics exist"


def _specs():
    return [
        NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="latest"),
        NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="series", limit=120),
        NumberQuery(table="silver_noaa_iod", metric="dmi_value", asof="2026-03-15", agg="latest"),
        NumberQuery(table="gold_weather_z", metric="drought_z", asof="2026-06-30", agg="series",
                    commodity="soybeans_cbot", country="United States", limit=120),
    ]


def test_the_compiled_sql_is_byte_identical_with_the_field_stripped():
    """The direct proof that nothing reads the field: compile each query against the card as loaded,
    and again against a copy whose lag is None. Any difference would be a live SQL change riding a
    data edit -- the thing D23 exists to prevent."""
    reg = load_registry()
    for spec in _specs():
        ts = reg.get(spec.table)
        stripped = ts.model_copy(update={"ym_publication_lag_days": None})
        assert build_sql(spec, ts) == build_sql(spec, stripped), spec.table


def test_the_oracle_agrees_with_itself_too():
    """``apply_pit_filter`` is build_sql's pure-Python twin (the test oracle and client fallback); the
    year_month branch is the ONE branch S1 moves, so it is pinned here at S0 in its unmoved form."""
    reg = load_registry()
    rows = [
        {"year": 2026, "month": 7, "value": 1.0},
        {"year": 2026, "month": 8, "value": 2.0},
        {"year": 2026, "month": 9, "value": 3.0},
        {"year": 2026, "month": 10, "value": 4.0},
    ]
    spec = NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="series")
    ts = reg.get("silver_noaa_oni")
    stripped = ts.model_copy(update={"ym_publication_lag_days": None})
    kept = apply_pit_filter(rows, spec, ts)
    assert kept == apply_pit_filter(rows, spec, stripped)
    # the UNMOVED semantics: a data month is admitted from its FIRST DAY, so 2026-09 is already in at
    # an as-of of the 8th -- three months ahead of the print that will carry it. That is exactly what
    # the declared 36-day lag shifts once `ym_lag` arms (2026-09 would drop out here, and 2026-08 with
    # it), and pinning the unmoved form makes S1's change visible as a diff rather than a surprise.
    assert [(r["year"], r["month"]) for r in kept] == [(2026, 7), (2026, 8), (2026, 9)]
