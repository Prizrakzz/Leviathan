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
