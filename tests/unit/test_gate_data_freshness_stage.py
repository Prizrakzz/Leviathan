"""THE DARK DATA-FRESHNESS STAGE on silver_rebuild_gate (SILVER-C001, 2026-09-11).

THE BLIND SPOT, MEASURED. Not one of the gate's ten stages reads a DATE. ``stage_feature_probe``
asserts bytes exist and carry the contract's columns; ``stage_value_census`` asserts a non-null
FRACTION; ``stage_parity``'s own docstring concedes that "identically-wrong on both backends is a clean
PASS"; ``contract_check`` is a DISTINCT vocabulary walk; ``cascade_census_diff`` counts DARK legs, and a
leg returning a stale row is LIT. So the gate passed on 2026-09-07, -08, -09 and -11 with
``gold_weather_z`` -- a SERVED numbers card -- frozen at data month 2026-07, 42 days behind, while the
board printed "for 2026-07 ... rising over the last month" beside COT at 2026-09-01.

AND THE ESTATE'S ONLY FRESHNESS CLOCK MISSES IT TOO: ``silver/freshness.py:136 newest_last_modified``
measures S3 OBJECT MTIME, and the producers rewrite the object daily, so FreshnessLagDays read 0.
Even a correct data-date read against the EXISTING denominator would have been silent -- the monthly
cadence default is 45 days and the data lag was 42, first breaching 2026-09-15. So the denominator here
is the CARD'S OWN PROMISE, ``_ym_lagged_asof_ym(asof, ym_publication_lag_days)``: the exact arithmetic
the as-of guard uses to ADMIT a month. No new threshold is invented anywhere.

DARK MEANS DARK, and this deck's first job is to prove it: with ``_DATA_FRESHNESS_BLOCKING = False``
the stage returns SKIPPED on EVERY path, so ``TableResult.ok`` -- which needs one GREEN and no RED --
is bit-identical to the pre-stage gate for every possible input.
"""
from __future__ import annotations

import types

import pytest

from jobs.audit import silver_rebuild_gate as g


class _SilverReg:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return self.tables[name]

    def value_columns(self, name):
        return list(self.tables[name].get("value_columns", []))


def _ym_card(table="gold_weather_z", lag=7):
    return types.SimpleNamespace(
        id=table, athena_table=None, year_col="year", month_col="month", date_col=None,
        knowledge_semantics="year_month", ym_publication_lag_days=lag)


def _date_card(table="silver_cot"):
    return types.SimpleNamespace(
        id=table, athena_table=None, year_col=None, month_col=None, date_col="report_date",
        knowledge_semantics="data_date", ym_publication_lag_days=None)


_DEFAULT = object()


def _ctx(card, rows, *, table="gold_weather_z", asof="2026-09-11", query_fn=_DEFAULT, **kw):
    # `_DEFAULT` and not None: an explicit ``query_fn=None`` is the OFFLINE posture and must survive
    # this helper, which is exactly what a None default would have swallowed.
    #
    # ``asof`` here sets ``census_asof`` -- the cascade-census DIFF BASELINE. Since the FATAL fix it is
    # NOT the freshness clock and no test may rely on it being one; the clock is ``_freshness_clock``,
    # pinned by the ``_clock`` fixture below and moved by ``_set_clock``.
    if query_fn is _DEFAULT:
        def query_fn(sql):                      # noqa: ANN001
            return rows
    base = dict(numbers_reg=types.SimpleNamespace(get=lambda t: card),
                silver_reg=_SilverReg({table: {"consumers": "both"}}),
                query_fn=query_fn, conn=object(), census_asof=asof, prior_census=None,
                eval_runner=None, value_census_fn=None)
    base.update(kw)
    return g.GateContext(**base)


_PINNED_CLOCK = "2026-09-11"
_REAL_CLOCK = g._freshness_clock          # bound at import, before any fixture can patch it


def _set_clock(monkeypatch, day: str) -> None:
    monkeypatch.setattr(g, "_freshness_clock", lambda: day)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    """EVERY case runs on a PINNED wall clock. Autouse and unconditional: a deck that measured against
    the real calendar would pass today and go red tomorrow, and the defect this fixture exists beside
    is precisely a stage reading the WRONG date."""
    _set_clock(monkeypatch, _PINNED_CLOCK)


@pytest.fixture(autouse=True)
def _clean_measurements():
    g._FRESHNESS_MEASUREMENTS.clear()
    yield
    g._FRESHNESS_MEASUREMENTS.clear()


@pytest.fixture
def _mirrored(monkeypatch):
    monkeypatch.setattr(g, "PG_MIRROR_TABLES", frozenset({"gold_weather_z", "silver_cot"}))


# ---------------------------------------------------------------------------
# (1) THE FLAG-OFF INVARIANT -- the stage cannot change any verdict
# ---------------------------------------------------------------------------
class TestDarkModeChangesNothing:
    def test_the_constant_ships_OFF(self):
        assert g._DATA_FRESHNESS_BLOCKING is False, (
            "promotion to blocking is the OWNER'S word, one constant, and it must not ride in on a "
            "build that only meant to add the measurement")

    def test_a_MEASURED_DEFECT_is_still_only_SKIPPED(self, _mirrored):
        """The live case: claimed 202608, bytes 202607, one month behind -- and still not a red."""
        res = g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), [{"tip_ym": "202607"}]))
        assert res.status == g.SKIPPED
        assert res.errors == []
        assert "1 month(s) behind" in res.detail
        assert "202607" in res.detail and "202608" in res.detail

    def test_an_ON_TIME_table_is_ALSO_only_SKIPPED_never_a_GREEN(self, _mirrored):
        """SKIPPED, not GREEN, on purpose: ``TableResult.ok`` needs at least one GREEN, so a dark
        stage that could green would be able to turn an all-skipped table into a pass on its own."""
        res = g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), [{"tip_ym": "202608"}]))
        assert res.status == g.SKIPPED
        assert "0 month(s) behind" in res.detail

    def test_a_CRASHING_freshness_read_is_never_a_red(self, _mirrored):
        def _boom(sql):
            raise RuntimeError("mirror is down")
        res = g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), None, query_fn=_boom))
        assert res.status == g.SKIPPED
        assert "RuntimeError" in res.detail and "mirror is down" in res.detail

    def test_TableResult_ok_is_UNCHANGED_by_the_stage_in_either_direction(self, _mirrored):
        """The whole flag-off proof in one assertion, on the real ``ok`` property."""
        stale = g.StageResult("data_freshness", g.SKIPPED, "1 month(s) behind")
        assert g.TableResult("t", g.BRANCH_A, [g.StageResult("pg_reload", g.GREEN), stale]).ok is True
        assert g.TableResult("t", g.BRANCH_A, [g.StageResult("pg_reload", g.RED), stale]).ok is False
        assert g.TableResult("t", g.BRANCH_A, [g.StageResult("pg_reload", g.SKIPPED), stale]).ok is \
            False, "a dark stage must never be the one GREEN that makes an all-skipped table pass"

    def test_the_stage_is_on_BOTH_branch_tuples_and_LAST_on_each(self):
        assert g._BRANCH_A_STAGES[-1] is g.stage_data_freshness
        assert g._BRANCH_B_STAGES[-1] is g.stage_data_freshness


class TestWhatThePromotionFlipWouldDo:
    """The owner's one-constant flip, exercised so the flip is a known quantity before it is made."""

    def test_a_table_behind_its_own_promise_becomes_RED(self, _mirrored, monkeypatch):
        monkeypatch.setattr(g, "_DATA_FRESHNESS_BLOCKING", True)
        res = g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), [{"tip_ym": "202607"}]))
        assert res.status == g.RED
        assert res.errors and "gold_weather_z" in res.errors[0]

    def test_an_on_time_table_becomes_GREEN(self, _mirrored, monkeypatch):
        monkeypatch.setattr(g, "_DATA_FRESHNESS_BLOCKING", True)
        res = g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), [{"tip_ym": "202608"}]))
        assert res.status == g.GREEN

    def test_a_MEASURED_BUT_UNJUDGEABLE_table_stays_SKIPPED_even_when_blocking(
            self, _mirrored, monkeypatch):
        """The flip must not turn "I have no denominator" into "this table is fresh" for every
        date-grain table at once -- that is the invented threshold this stage exists to avoid."""
        monkeypatch.setattr(g, "_DATA_FRESHNESS_BLOCKING", True)
        res = g.stage_data_freshness(
            "silver_cot", _ctx(_date_card(), [{"tip_date": "2026-09-01"}], table="silver_cot"))
        assert res.status == g.SKIPPED and "NOT judgeable" in res.detail

    def test_a_table_AHEAD_of_its_promise_is_MEASURED_but_never_JUDGED(self, _mirrored, monkeypatch):
        """A negative months_behind is not a staleness verdict in either direction, so it is recorded
        and NOT judged -- not red (the card admitting a month it should not is the PIT guard's defect,
        not this stage's) and NOT green (this stage cannot tell "the producer is ahead of the promise"
        from "my clock is behind the data", and the second is exactly how the frozen census_asof
        default GREENED a 42-day-stale table)."""
        monkeypatch.setattr(g, "_DATA_FRESHNESS_BLOCKING", True)
        res = g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), [{"tip_ym": "202609"}]))
        assert res.status == g.SKIPPED
        assert "NOT judgeable" in res.detail
        assert res.errors == []
        assert g._FRESHNESS_MEASUREMENTS["gold_weather_z"]["months_behind"] == -1


class TestTheClockIsTheWallClockNeverTheCensusBaseline:
    """THE FATAL, PINNED (found in review, driven on the real registry card 2026-09-11).

    ``ctx.census_asof`` is the cascade-census DIFF BASELINE -- a deliberately PINNED historical date
    whose argparse default is the frozen ``"2026-02-15"``, already on the record as its own measured
    incident (``jobs/submit/submit_batch_silver_rebuild_gate.py:49-56``, "a census asof must default to
    NOW unless the caller pins one"). Reading it as "now" made this stage report ``-6 month(s) behind``
    on the real 202607 tip, publish ``DataFreshnessMonthsBehind = -6.0`` into the very week of data the
    alarm threshold is to be set from, and -- on the stated one-constant promotion flip -- return GREEN
    on the 42-day-stale table that is the whole reason the stage exists.
    """

    def test_a_FROZEN_census_asof_does_not_move_the_measurement(self, _mirrored):
        res = g.stage_data_freshness(
            "gold_weather_z", _ctx(_ym_card(), [{"tip_ym": "202607"}], asof="2026-02-15"))
        m = g._FRESHNESS_MEASUREMENTS["gold_weather_z"]
        assert m["asof"] == _PINNED_CLOCK, "the clock is the wall clock, not the diff baseline"
        assert (m["claimed_ym"], m["months_behind"]) == (202608, 1)
        assert "-6 month(s) behind" not in res.detail
        assert "wall clock" in res.detail, (
            "the bundle also carries `as_of_census`; the freshness line must say WHICH date it used")

    def test_the_frozen_default_can_no_longer_GREEN_a_stale_table_on_the_flip(
            self, _mirrored, monkeypatch):
        """The exact driven case: the argparse default asof, the real 202607 tip, blocking ON."""
        monkeypatch.setattr(g, "_DATA_FRESHNESS_BLOCKING", True)
        res = g.stage_data_freshness(
            "gold_weather_z", _ctx(_ym_card(), [{"tip_ym": "202607"}], asof="2026-02-15"))
        assert res.status == g.RED
        assert res.errors and "gold_weather_z" in res.errors[0]

    def test_the_frozen_default_is_STILL_the_context_default_so_this_is_not_a_dead_case(self):
        """The baseline default is deliberately unchanged -- it is the census diff's pin, not a bug in
        itself -- which is exactly why the freshness stage must never read it."""
        assert g.GateContext(numbers_reg=None, silver_reg=None).census_asof == "2026-02-15"

    def test_a_date_grain_AGE_is_measured_on_the_same_wall_clock(self, _mirrored):
        g.stage_data_freshness(
            "silver_cot", _ctx(_date_card(), [{"tip_date": "2026-09-01"}], table="silver_cot",
                               asof="2026-02-15"))
        m = g._FRESHNESS_MEASUREMENTS["silver_cot"]
        assert (m["asof"], m["data_age_days"]) == (_PINNED_CLOCK, 10), \
            "a frozen baseline would have read the tip as 193 days in the FUTURE"

    def test_the_UNPATCHED_clock_is_todays_UTC_date(self):
        """The fixture pins it; this case proves what it pins is the real thing. ``_REAL_CLOCK`` is
        bound at import, BEFORE any fixture runs, so this never depends on undo ordering."""
        from datetime import datetime, timezone
        assert _REAL_CLOCK() == datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# (2) THE MEASUREMENT ITSELF
# ---------------------------------------------------------------------------
class TestYearMonthMeasurement:
    def test_the_denominator_is_the_CARDS_OWN_arithmetic_not_a_new_constant(self, _mirrored):
        """``_ym_lagged_asof_ym('2026-09-11', 7)`` -> 202608: the newest month the as-of guard ADMITS.
        The card declares lag 7 with its own note that the number is UNVERIFIED; the measurement
        below is what refutes it (the governing feeder's real lag is ~45 days), and this stage
        deliberately reports against the number the serving stack actually uses."""
        from leviathan.graphrag.numbers.query import _ym_lagged_asof_ym
        assert _ym_lagged_asof_ym("2026-09-11", 7) == 202608
        g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), [{"tip_ym": "202607"}]))
        m = g._FRESHNESS_MEASUREMENTS["gold_weather_z"]
        assert m == {"grain": "year_month", "claimed_ym": 202608, "actual_ym": 202607,
                     "months_behind": 1, "asof": "2026-09-11", "ym_publication_lag_days": 7,
                     "detail": m["detail"]}

    def test_months_behind_counts_MONTHS_across_a_year_boundary(self, _mirrored, monkeypatch):
        _set_clock(monkeypatch, "2026-02-11")
        g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), [{"tip_ym": "202512"}]))
        assert g._FRESHNESS_MEASUREMENTS["gold_weather_z"]["months_behind"] == 1

    def test_the_sql_is_ONE_bounded_aggregate_on_the_mirror(self, _mirrored):
        sql = g._tip_ym_sql(_ym_card())
        assert sql == ("SELECT MAX((year * 100) + month) AS tip_ym "
                       "FROM leviathan_dev.gold_weather_z")

    def test_an_athena_table_alias_is_honoured_so_the_mirror_name_is_the_physical_one(self):
        card = _ym_card()
        card.athena_table = "gold_weather_z_v2"
        assert g._tip_ym_sql(card).endswith("FROM leviathan_dev.gold_weather_z_v2")

    def test_BOTH_tip_statements_name_the_mirror_SCHEMA_or_they_never_run_in_prod(self):
        """THE REGRESSION PIN for the review's major-1 defect, stated as the failure it caused.

        The pg mirror creates its tables as ``"leviathan_dev"."<physical>"`` and the numbers pool
        connects with no search_path, so a BARE relation raises UndefinedTable -- which this stage's
        own never-raises fence then converts into a SKIPPED "not measured". The instrument would have
        reported nothing forever while reading as installed. Both statements are pinned, because only
        the year_month one was exercised by the deck when the defect shipped."""
        from leviathan.graphrag.numbers import query as Q
        assert Q.ATHENA_DB == "leviathan_dev"
        card = _ym_card()
        for sql in (g._tip_ym_sql(card), g._tip_date_sql(_date_card())):
            frm = sql.split(" FROM ", 1)[1].strip()
            assert frm.startswith(f"{Q.ATHENA_DB}."), f"unqualified relation in: {sql}"
            assert "." in frm and not frm.startswith("."), sql

    def test_a_card_that_DECLARES_NO_LAG_makes_no_promise_and_is_not_judged(self, _mirrored):
        """"Undeclared" must read as "no claim", never as "lag 0" -- the same reading
        ``_ym_lagged_asof_ym`` itself takes of a falsy lag."""
        res = g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(lag=None), [{"tip_ym": "202607"}]))
        assert res.status == g.SKIPPED
        assert "declares no ym_publication_lag_days" in res.detail
        assert "gold_weather_z" not in g._FRESHNESS_MEASUREMENTS

    def test_an_EMPTY_mirror_is_reported_as_unmeasured_not_as_infinitely_behind(self, _mirrored):
        res = g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), [{"tip_ym": None}]))
        assert res.status == g.SKIPPED and "no tip month" in res.detail
        assert g._FRESHNESS_MEASUREMENTS == {}


class TestPerMetricYearMonthMeasurement:
    """A card whose metrics promise DIFFERENT months is measured once per metric (2026-09-11).

    THE DEFECT IT CLOSES IS A WRONG VERDICT, not a missing one. Under the single blanket lag this stage
    read "1 month behind" for all five live ``gold_weather_z`` metrics on 2026-09-11. That is TRUE of
    the four NASA ones -- a real raw->bronze freeze -- and FALSE of ``drought_z``, whose CHIRPS month
    block simply had not published and which is exactly ON its own promise that day. One number cannot
    carry both verdicts, and the wrong half is the half an operator would have chased.

    THE CHIRPS NUMBER MOVED 45 -> 25 (2026-09-11, verify pass, same day): the two HTTP-HEAD
    observations behind it BOUND the lag rather than fixing it -- July's block PRESENT at day 22 past
    month-end is an UPPER bound, August ABSENT at day 11 is a LOWER one, so 11 < lag <= 22 and the
    declaration is 22 plus a 3-day margin. Under 25 the measured 2026-09-11 verdict for ``drought_z``
    is 0 months behind, not -1: the promise admits 202607 and the bytes hold 202607.
    """

    @staticmethod
    def _live_card():
        """THE REAL CARD, not a double. The whole claim is about what the shipped declaration says, and
        a hand-built double would grade this deck's opinion of it instead."""
        from leviathan.graphrag.numbers.registry import load_registry
        return load_registry().get("gold_weather_z")

    @staticmethod
    def _rows(**tips):
        return [{"metric": m, "tip_ym": str(ym)} for m, ym in tips.items()]

    def test_the_live_card_takes_the_per_metric_path_and_the_single_lag_cards_do_not(self):
        assert len(set(g._metric_lags(self._live_card()).values())) > 1
        for card in (_ym_card(), _date_card()):
            assert g._metric_lags(card) == {}, "a card double with no metrics must not switch paths"

    def test_the_MEASURED_2026_09_11_verdict_splits_the_two_sources(self, _mirrored):
        """The live tip, measured off gold/weather_z/corn_cbot.parquet that day: every metric at
        202607. NASA's 5-day lag admits 202608 (one month behind -- the freeze); CHIRPS' 25-day lag
        admits 202607 (2026-09-11 minus 25 days is 2026-08-17, and August has not ended), so
        ``drought_z`` is exactly ON its promise and the freeze verdict belongs to the NASA four alone.
        That is the split, and it is the same split the 45 produced -- one metric clear, four behind --
        arrived at from the bound the measurement actually supports."""
        rows = self._rows(drought_z=202607, tmax_anomaly=202607, gdd_z=202607,
                          heat_stress_z=202607, frost_event_flag=202607)
        g.stage_data_freshness("gold_weather_z", _ctx(self._live_card(), rows))
        m = g._FRESHNESS_MEASUREMENTS["gold_weather_z"]
        assert m["grain"] == "year_month_per_metric"
        by = m["by_metric"]
        assert by["drought_z"] == {"lag_days": 25, "claimed_ym": 202607, "actual_ym": 202607,
                                   "months_behind": 0}
        for nasa in ("tmax_anomaly", "gdd_z", "heat_stress_z", "frost_event_flag"):
            assert by[nasa] == {"lag_days": 5, "claimed_ym": 202608, "actual_ym": 202607,
                                "months_behind": 1}, nasa
        assert m["months_behind"] == 1
        assert m["worst_metric"] in {"tmax_anomaly", "gdd_z", "heat_stress_z", "frost_event_flag"}

    def test_the_judgement_is_the_WORST_metric_so_four_fresh_ones_cannot_bury_one_frozen(self,
                                                                                        _mirrored):
        """Averaging, or reading the table's own tip, is how a blind spot re-enters one level down."""
        rows = self._rows(drought_z=202606, tmax_anomaly=202608, gdd_z=202608,
                          heat_stress_z=202608, frost_event_flag=202512)
        g.stage_data_freshness("gold_weather_z", _ctx(self._live_card(), rows))
        m = g._FRESHNESS_MEASUREMENTS["gold_weather_z"]
        assert m["worst_metric"] == "frost_event_flag" and m["months_behind"] == 8
        # drought_z at 202606 is ONE month behind its own 25-day promise (which admits 202607) -- a
        # real, small shortfall that the aggregate correctly declines to let win. Under the 45 this
        # number replaced the same tip read as 0; the verdict the test is about -- max, not mean --
        # is the same either way, and pinning the measured value keeps the deck honest about which
        # lag it is grading.
        assert m["by_metric"]["drought_z"]["months_behind"] == 1
        assert m["by_metric"]["drought_z"]["lag_days"] == 25

    def test_an_ALL_NEGATIVE_card_still_reaches_the_bytes_are_ahead_branch(self, _mirrored):
        """``max`` must not clamp: when every metric is ahead of its promise the aggregate stays
        negative and the stage's stated "cannot read that as fresh" branch is the one that answers."""
        rows = self._rows(drought_z=202608, tmax_anomaly=202609)
        res = g.stage_data_freshness("gold_weather_z", _ctx(self._live_card(), rows))
        assert g._FRESHNESS_MEASUREMENTS["gold_weather_z"]["months_behind"] < 0
        assert res.status == g.SKIPPED

    def test_a_metric_ABSENT_from_the_mirror_is_unmeasured_not_infinitely_behind(self, _mirrored):
        """The card's whitelist carries aggregate-only basin metrics that have ZERO rows on a per-cell
        commodity. Honest absence -- the same reading the empty-mirror rule already takes."""
        g.stage_data_freshness("gold_weather_z",
                               _ctx(self._live_card(), self._rows(drought_z=202607)))
        m = g._FRESHNESS_MEASUREMENTS["gold_weather_z"]
        assert m["worst_metric"] == "drought_z"
        assert "tmax_anomaly" in m["metrics_absent_from_mirror"]
        assert "drought_z" not in m["metrics_absent_from_mirror"]

    def test_an_EMPTY_mirror_is_still_unmeasured_rather_than_a_breach(self, _mirrored):
        res = g.stage_data_freshness("gold_weather_z", _ctx(self._live_card(), []))
        assert res.status == g.SKIPPED and "no tip month for any metric" in res.detail
        assert g._FRESHNESS_MEASUREMENTS == {}

    def test_the_grouped_sql_is_ONE_bounded_aggregate_on_the_qualified_mirror_relation(self):
        from leviathan.graphrag.numbers import query as Q
        sql = g._tip_ym_by_metric_sql(self._live_card())
        assert sql == ("SELECT metric AS metric, MAX((year * 100) + month) AS tip_ym "
                       f"FROM {Q.ATHENA_DB}.gold_weather_z GROUP BY metric")
        assert sql.count("SELECT") == 1 and " JOIN " not in sql

    def test_a_metric_that_DECLARES_ZERO_is_measured_and_not_dropped_as_undeclared(self, _mirrored):
        """``_metric_lags`` filtered with ``if lag:`` and a declared ``0`` is falsy (fix 2026-09-11).

        ``registry.lag_days_for`` draws the line the estate agreed on -- ``None`` is UNDECLARED and
        ``0`` is a real declaration, "this source prints on the data month's last day" -- and the
        falsy filter un-drew it one consumer down. The consequence is not a wrong number but a MISSING
        verdict, and on the freshest metric of the card: ``_measure_year_month_by_metric`` grades only
        ``set(tips) & set(lags)``, so a zero-lag metric drops out of ``lags``, is never compared to
        anything, and lands in ``metrics_absent_from_mirror`` while its rows sit right there. The
        metric whose promise a freeze would breach FIRST is the one the staleness stage would never
        have graded."""
        from leviathan.graphrag.numbers.registry import Metric, TableSpec
        card = TableSpec(
            id="gold_weather_z", description="d", shape="tall", year_col="year", month_col="month",
            metric_col="metric", value_col="value", knowledge_semantics="year_month",
            ym_publication_lag_days=5,
            metrics={"prints_on_month_end": Metric(ym_publication_lag_days=0),
                     "prints_a_block_later": Metric(ym_publication_lag_days=25)})
        assert g._metric_lags(card) == {"prints_on_month_end": 0, "prints_a_block_later": 25}, \
            "a declared 0 is a lag; only None is undeclared"

        rows = self._rows(prints_on_month_end=202608, prints_a_block_later=202607)
        g.stage_data_freshness("gold_weather_z", _ctx(card, rows))
        m = g._FRESHNESS_MEASUREMENTS["gold_weather_z"]
        by = m["by_metric"]
        # THE ARITHMETIC A DECLARED ZERO GETS, measured rather than assumed: ``_ym_lagged_asof_ym``
        # treats a FALSY lag as the IDENTITY by its own stated contract (the byte-identical pre-wave
        # literal, pinned in test_numbers_query_ym_lag), so 0 admits the AS-OF's own month 202609 --
        # not 202608, which is what month-end arithmetic on a 0-day lag would give. That is a
        # property of the compiler, deliberately unchanged here; what this fix is about is that the
        # metric is GRADED AT ALL. Both facts are pinned so neither can move silently.
        assert by["prints_on_month_end"] == {"lag_days": 0, "claimed_ym": 202609,
                                             "actual_ym": 202608, "months_behind": 1}
        assert by["prints_a_block_later"]["months_behind"] == 0
        assert "prints_on_month_end" not in m["metrics_absent_from_mirror"]
        assert "prints_on_month_end=1(lag 0)" in m["detail"]
        assert m["worst_metric"] == "prints_on_month_end" and m["months_behind"] == 1

    def test_the_detail_line_names_every_metric_and_its_own_lag(self, _mirrored):
        """A per-metric verdict that printed only the worst would hide the very split it exists to
        show -- an operator has to be able to see that drought_z is not the frozen one."""
        rows = self._rows(drought_z=202607, tmax_anomaly=202607)
        g.stage_data_freshness("gold_weather_z", _ctx(self._live_card(), rows))
        detail = g._FRESHNESS_MEASUREMENTS["gold_weather_z"]["detail"]
        assert "drought_z=0(lag 25)" in detail and "tmax_anomaly=1(lag 5)" in detail


class TestDataDateMeasurement:
    def test_a_date_grain_card_reports_AGE_and_refuses_to_call_it_behind(self, _mirrored):
        """There is NO declared denominator: freshness_sla.max_lag_days is null on gold_weather_z,
        silver_chirps AND silver_nasa_power, and configs/datasets/source_contracts.yaml declares no
        publication lag for either weather source. A metric named 'DaysBehind' with no declared
        denominator would be a threshold invented in telemetry."""
        res = g.stage_data_freshness(
            "silver_cot", _ctx(_date_card(), [{"tip_date": "2026-09-01"}], table="silver_cot"))
        assert res.status == g.SKIPPED
        m = g._FRESHNESS_MEASUREMENTS["silver_cot"]
        assert m["tip_date"] == "2026-09-01" and m["data_age_days"] == 10
        assert m["months_behind"] is None, "no declared lag -> no 'behind' claim"
        assert "no declared source publication lag" in m["detail"]

    def test_a_timestamp_tip_is_truncated_to_its_date(self, _mirrored):
        g.stage_data_freshness(
            "silver_cot", _ctx(_date_card(), [{"tip_date": "2026-09-01 00:00:00"}], table="silver_cot"))
        assert g._FRESHNESS_MEASUREMENTS["silver_cot"]["tip_date"] == "2026-09-01"

    def test_the_metric_NAMES_say_what_each_one_actually_is(self):
        assert g.FRESHNESS_MONTHS_BEHIND_METRIC == "DataFreshnessMonthsBehind"
        assert g.FRESHNESS_DATA_AGE_METRIC == "DataDateAgeDays"


class TestWhatIsDeliberatelyNotMeasured:
    def test_a_table_outside_the_pg_mirror_says_SO_rather_than_scanning_athena(self, _mirrored):
        """silver_chirps and silver_nasa_power are the projection/INV-3 class -- Athena is barred here,
        and a footer walk of silver_chirps' canonical objects is ~1.4K GETs per gate run, which is not
        a cost a DARK stage may impose. Named as the follow-up, deliberately unbuilt."""
        res = g.stage_data_freshness(
            "silver_chirps", _ctx(_date_card("silver_chirps"), [], table="silver_chirps"))
        assert res.status == g.SKIPPED
        assert "not in the pg mirror" in res.detail and "footer" in res.detail

    def test_an_offline_run_skips_without_touching_anything(self):
        res = g.stage_data_freshness("gold_weather_z", _ctx(_ym_card(), [], query_fn=None))
        assert res.status == g.SKIPPED and "offline" in res.detail

    def test_a_table_with_no_numbers_card_is_skipped_not_crashed(self, _mirrored):
        res = g.stage_data_freshness("gold_weather_z", _ctx(None, []))
        assert res.status == g.SKIPPED and "no numbers-registry card" in res.detail


# ---------------------------------------------------------------------------
# (3) THE NUMBERS REACH THE BUNDLE AND THE METRIC
# ---------------------------------------------------------------------------
class TestTheMeasurementTravels:
    def test_run_gate_carries_the_measurements_into_the_artifact_bundle(self, _mirrored, monkeypatch):
        ctx = _ctx(_ym_card(), [{"tip_ym": "202607"}])
        bundle = g.run_gate(["gold_weather_z"], ctx,
                            branch_a_stages=(g.stage_data_freshness,),
                            branch_b_stages=(g.stage_data_freshness,))
        assert bundle["data_freshness"]["gold_weather_z"]["months_behind"] == 1
        assert bundle["data_freshness"]["gold_weather_z"]["actual_ym"] == 202607

    def test_run_gate_CLEARS_the_measurements_so_a_second_run_cannot_inherit_the_first(
            self, _mirrored):
        ctx = _ctx(_ym_card(), [{"tip_ym": "202607"}])
        g.run_gate(["gold_weather_z"], ctx, branch_a_stages=(g.stage_data_freshness,),
                   branch_b_stages=(g.stage_data_freshness,))
        offline = _ctx(_ym_card(), [], query_fn=None)
        bundle = g.run_gate(["gold_weather_z"], offline,
                            branch_a_stages=(g.stage_data_freshness,),
                            branch_b_stages=(g.stage_data_freshness,))
        assert bundle["data_freshness"] == {}

    def test_the_datums_ride_the_put_metric_data_call_the_gate_ALREADY_makes(self, monkeypatch):
        """No second put_metric_data, no new IAM -- the `_emit_gate_metrics` precedent."""
        captured = {}

        class _CW:
            def put_metric_data(self, Namespace, MetricData):   # noqa: N803
                captured["ns"] = Namespace
                captured["data"] = MetricData

        monkeypatch.setitem(__import__("sys").modules, "boto3",
                            types.SimpleNamespace(client=lambda name: _CW()))
        g._emit_gate_metrics({
            "family": "weather", "verdict": g.VERDICT_PASS, "census_hard_fail": 0,
            "data_freshness": {
                "gold_weather_z": {"months_behind": 1, "detail": "d"},
                "silver_cot": {"data_age_days": 10, "months_behind": None, "detail": "d"},
            },
        })
        assert captured["ns"] == g.GATE_METRIC_NAMESPACE
        names = [d["MetricName"] for d in captured["data"]]
        assert names.count(g.FRESHNESS_MONTHS_BEHIND_METRIC) == 1
        assert names.count(g.FRESHNESS_DATA_AGE_METRIC) == 1
        assert g.GATE_VERDICT_METRIC in names and g.CENSUS_HARDFAIL_METRIC in names
        behind = next(d for d in captured["data"]
                      if d["MetricName"] == g.FRESHNESS_MONTHS_BEHIND_METRIC)
        assert behind["Value"] == 1.0
        assert {dim["Name"] for dim in behind["Dimensions"]} == {"Table", "Family"}

    def test_a_run_with_NO_measurement_emits_exactly_what_it_used_to(self, monkeypatch):
        captured = {}

        class _CW:
            def put_metric_data(self, Namespace, MetricData):   # noqa: N803
                captured["data"] = MetricData

        monkeypatch.setitem(__import__("sys").modules, "boto3",
                            types.SimpleNamespace(client=lambda name: _CW()))
        g._emit_gate_metrics({"family": "weather", "verdict": g.VERDICT_PASS, "census_hard_fail": 0})
        assert len(captured["data"]) == 3, "the pre-wave datum set, unchanged"

    def test_a_metric_failure_still_cannot_kill_the_gate(self, monkeypatch):
        class _CW:
            def put_metric_data(self, **kw):
                raise RuntimeError("cloudwatch is down")

        monkeypatch.setitem(__import__("sys").modules, "boto3",
                            types.SimpleNamespace(client=lambda name: _CW()))
        g._emit_gate_metrics({"family": "weather", "verdict": g.VERDICT_FAIL, "census_hard_fail": 1,
                              "data_freshness": {"gold_weather_z": {"months_behind": 1}}})


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
