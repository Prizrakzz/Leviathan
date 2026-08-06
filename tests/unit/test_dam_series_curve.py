"""D-AM-21 -- the futures CURVE read on /v1/series (the carry / backwardation chart's server half).

THE DEFECT THIS FILE MEASURES. /v1/series built its NumberQuery with NO contract_month, so a futures card
served through the terminal's own chart route returned the INTERLEAVED multi-expiry read -- ~13 delivery
months per session, stacked -- which is precisely the shape `query.curve_as_calendar` exists to refuse a
positional statistic over. The chart drew it anyway, and it could not have drawn anything else: the front
end's only x key was `period`, an alias the futures card does not surface at all, so every point in a
futures series collapsed onto ONE x. There was no way to ask for the term structure and no way to plot it.

WHAT IS PINNED, AND IN WHICH DIRECTION
  * THE THREADING IS VERBATIM. The route parses nothing: the comma list goes into the spec as the single
    string field the numbers tool already carries, so `_contract_months` stays the ONE splitter and the SQL
    emit and the PIT oracle cannot disagree with the URL.
  * THE DEFAULT IS BYTE-IDENTITY. An unparameterized call builds the exact spec it built before this wave
    (contract_month absent, agg='series') and compiles the exact SQL -- the new parameters are additive, and
    that is asserted rather than assumed.
  * BOTH X KEYS ARE ON THE ROWS, IN BOTH MODES. The front end needs `knowledge_date` for the time axis and
    `contract_month` for the curve axis. Both are already `_extras` aliases on a card declaring
    `contract_month_col`, and the SELECT list of BOTH compiled shapes is asserted to carry them -- with the
    non-futures anti-vacuity twin, since an assertion that only said "the aliases exist somewhere" would
    pass on a card that has no expiry axis at all.
  * THE TWO REFUSALS ARE 400s, NOT 502s. A contract_month against a card with no delivery-month column, and
    an agg this route does not serve, are REQUEST errors. Left alone the first surfaces as the generic 502
    this route wraps every query failure in, which tells the caller an outage happened when none did.
  * THE SHAPE DISCRIMINATOR. The curve read is a single-session multi-expiry object that
    `curve_as_calendar` must NOT refuse, and the DEFAULT futures read through this same route is the
    interleaved one it must. Both halves, because either alone is satisfiable by a broken discriminator.

Hermetic: no AWS, no LLM, no pg. The route is driven through TestClient with `Q.run` stubbed.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from leviathan.graphrag import config_check as CC
from leviathan.graphrag import server as sv
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R

EOD = "silver_futures_eod"
SLUG = "corn_cbot"
ASOF = "2026-06-08"
SESSION = "2026-06-05"
# A real corn term structure at ONE session -- the same measured shape the D-AM-17 spread stat is pinned on.
CURVE_MONTHS = ("2026-07", "2026-09", "2026-12", "2027-03", "2027-05")
CURVE_LEVELS = (417.5, 427.0, 446.0, 461.5, 470.75)


def _ts(table: str) -> R.TableSpec:
    """The LIVE card out of the raw tables.yaml, exactly as test_dam_series_order reads it -- never a
    hand-built TableSpec, which would let a card edit ship past every assertion below."""
    return R.TableSpec(id=table, **dict(CC._load("numbers/tables.yaml")["tables"][table]))


def _curve_rows(session: str = SESSION) -> list[dict]:
    """The documented curve read's rows: one per expiry, all at one session, each self-identifying."""
    return [{"value": str(v), "contract_month": m, "knowledge_date": session, "year": "2026",
             "unit": "US cents/bushel", "settle_kind": "settlement", "currency": "USD"}
            for m, v in zip(CURVE_MONTHS, CURVE_LEVELS)]


def _interleaved_rows(n_sessions: int = 3) -> list[dict]:
    """The DEFAULT futures series read through this route: every delivery month, every session."""
    return [{"value": "1", "contract_month": m, "knowledge_date": f"2026-06-0{i + 1}"}
            for i in range(n_sessions) for m in CURVE_MONTHS]


@pytest.fixture()
def route(monkeypatch):
    """TestClient + a stubbed `Q.run` that RECORDS the spec and the canary it was handed. Recorded rather
    than swallowed: a `**_` here would let the route drop a parameter and still pass, which is the exact
    failure the threading pins exist to catch."""
    monkeypatch.setitem(sv._STATE, "graph", None)
    seen: list = []
    rows: list[dict] = []

    def _run(spec, query_fn=None, *, futures_newest_first=False):
        seen.append((spec, futures_newest_first))
        return [dict(r) for r in rows]

    monkeypatch.setattr(Q, "run", _run)          # the route imports the module lazily -> patch the module
    monkeypatch.delenv("GRAPHRAG_FUTURES_NEWEST_FIRST", raising=False)
    monkeypatch.delenv("GRAPHRAG_SERIES_NEWEST_FIRST", raising=False)
    client = TestClient(sv.app)

    class _R:
        def get(self, params=None, table=EOD, metric="settle"):
            return client.get(f"/v1/series/{table}/{metric}", params=params or {})

        def rows(self, new):
            rows[:] = new

        @property
        def specs(self):
            return [s for s, _ in seen]

        @property
        def canaries(self):
            return [c for _, c in seen]

    return _R()


# ==================================================================================================
# 1. THREADING -- the route hands the compiler the caller's own month list, verbatim
# ==================================================================================================
class TestContractMonthThreading:
    def test_the_comma_list_reaches_the_spec_UNPARSED(self, route):
        """The route must not split, sort or de-duplicate: `_contract_months` is the ONE splitter, shared by
        the SQL emit and by `apply_pit_filter`. A second parser here is a second semantics."""
        months = ",".join(CURVE_MONTHS)
        assert route.get({"contract_month": months, "agg": "latest", "commodity": SLUG,
                          "asof": ASOF}).status_code == 200
        spec = route.specs[-1]
        assert spec.contract_month == months
        assert spec.agg == "latest" and spec.table == EOD and spec.commodity == SLUG

    def test_a_single_expiry_is_the_CALENDAR_read_and_keeps_agg_series(self, route):
        """One month named with the default agg is one contract THROUGH TIME -- the other legitimate futures
        series shape, and the one whose x is `knowledge_date`. It must not be forced into the curve branch."""
        assert route.get({"contract_month": "2026-12", "commodity": SLUG, "asof": ASOF}).status_code == 200
        spec = route.specs[-1]
        assert spec.contract_month == "2026-12" and spec.agg == "series"

    def test_the_asof_is_the_CALLERS_and_is_not_re_derived(self, route):
        """PIT: the curve is read at the same point in time as the row it hangs off. The route mints no date
        of its own when one was given -- there is exactly one as-of in play per turn."""
        route.get({"contract_month": ",".join(CURVE_MONTHS), "agg": "latest", "commodity": SLUG,
                   "asof": "2011-03-04"})
        assert route.specs[-1].asof == "2011-03-04"

    def test_the_response_envelope_still_echoes_the_read(self, route):
        route.rows(_curve_rows())
        body = route.get({"contract_month": ",".join(CURVE_MONTHS), "agg": "latest", "commodity": SLUG,
                          "asof": ASOF}).json()
        assert body["table"] == EOD and body["metric"] == "settle" and body["asof"] == ASOF
        assert len(body["points"]) == len(CURVE_MONTHS)


# ==================================================================================================
# 2. THE DEFAULT CALL -- unchanged, and asserted rather than assumed
# ==================================================================================================
class TestNonFuturesPathUnchanged:
    def test_an_unparameterized_call_builds_the_PRE_WAVE_spec(self, route):
        """Both new parameters absent -> contract_month is None and agg is 'series', which is the spec this
        route built before D-AM-21. The canary stays False with both env seams unset."""
        assert route.get({"commodity": "corn"}, table="silver_psd",
                         metric="ending_stocks_mt").status_code == 200
        spec = route.specs[-1]
        assert spec.contract_month is None and spec.agg == "series"
        assert route.canaries == [False]

    def test_the_default_spec_compiles_the_SAME_SQL_a_pre_wave_spec_did(self, route):
        """The compiler-level twin of the row above: the spec the route now builds and the spec it built
        before (constructed here without either field) are the same compile, byte for byte."""
        route.get({"commodity": "corn"}, table="silver_psd", metric="ending_stocks_mt")
        spec = route.specs[-1]
        pre = Q.NumberQuery(table="silver_psd", metric="ending_stocks_mt", asof=spec.asof,
                            commodity="corn", country=None, agg="series")
        ts = _ts("silver_psd")
        assert Q.build_sql(spec, ts) == Q.build_sql(pre, ts)

    def test_a_futures_card_with_no_months_named_is_ALSO_the_pre_wave_read(self, route):
        """The new parameters are opt-in on every card, futures included: the plain expansion fetch is the
        same (interleaved) read it always was, so nothing about the existing chart moved under it."""
        route.get({"commodity": SLUG, "asof": ASOF})
        spec = route.specs[-1]
        assert spec.contract_month is None and spec.agg == "series"
        pre = Q.NumberQuery(table=EOD, metric="settle", asof=ASOF, commodity=SLUG, agg="series")
        assert Q.build_sql(spec, _ts(EOD)) == Q.build_sql(pre, _ts(EOD))


# ==================================================================================================
# 3. THE X KEYS -- both aliases on futures rows, in BOTH modes
# ==================================================================================================
def _select_aliases(sql: str) -> set[str]:
    """The aliases the OUTERMOST projection actually returns. The curve branch wraps a ROW_NUMBER subquery
    and re-projects `value, <aliases>`, so reading the inner SELECT list would pass for a shape that never
    surfaced them -- the outer projection is the one the front end receives."""
    head = sql.split(" FROM ", 1)[0]
    return {part.strip().rsplit(" AS ", 1)[-1].strip().split()[-1]
            for part in head.replace("SELECT ", "", 1).split(",")}


class TestFuturesRowsCarryAnXKey:
    CURVE = Q.NumberQuery(table=EOD, metric="settle", asof=ASOF, commodity=SLUG, agg="latest",
                          contract_month=",".join(CURVE_MONTHS))
    CALENDAR = Q.NumberQuery(table=EOD, metric="settle", asof=ASOF, commodity=SLUG, agg="series",
                             contract_month="2026-12")

    @pytest.mark.parametrize("mode", ["CURVE", "CALENDAR"])
    def test_both_modes_return_knowledge_date_AND_contract_month(self, mode):
        """`knowledge_date` is the time axis (silver_futures_eod's knowledge_date_col IS its session date)
        and `contract_month` is the curve axis. A row missing both is a number the chart cannot place and
        the citation cannot attribute -- which is what a futures point was before this wave."""
        sql = Q.build_sql(getattr(self, mode), _ts(EOD))
        assert {"knowledge_date", "contract_month"} <= _select_aliases(sql)

    def test_the_extras_aliasing_is_where_they_come_from(self):
        """Stated at the source rather than only at the compile: `_extras` mints both aliases for any card
        declaring the columns, so this is the vocabulary's home and no route re-spells it."""
        aliases = {a for _, a in Q._extras(_ts(EOD))}
        assert {"knowledge_date", "contract_month"} <= aliases

    def test_ANTI_VACUITY_a_non_futures_card_surfaces_no_contract_month(self):
        """If every card surfaced a contract_month alias the row above would pin nothing. PSD has no
        delivery-month column, so its rows carry no expiry -- which is also why the curve affordance can
        never appear on one."""
        psd = _ts("silver_psd")
        assert psd.contract_month_col is None
        assert "contract_month" not in {a for _, a in Q._extras(psd)}

    def test_the_curve_branch_is_one_row_per_expiry_at_one_asof(self):
        """The compiled curve is the documented shape: PARTITION BY the delivery month, keep the newest
        session per expiry. A bare `LIMIT 1` here would narrate ONE number as the curve."""
        sql = Q.build_sql(self.CURVE, _ts(EOD))
        assert "ROW_NUMBER() OVER (PARTITION BY contract_month" in sql
        assert "_rn = 1" in sql and "LIMIT 1" not in sql


# ==================================================================================================
# 4. THE TWO REFUSALS -- deterministic 400s, never the route's catch-all 502
# ==================================================================================================
class TestDeterministicRefusals:
    def test_a_contract_month_against_a_card_with_no_expiry_axis_is_a_400(self, route):
        """build_sql's own delivery-month guard, lifted to the request layer: a dimension the table cannot
        express is a decline. Reaching the compiler instead would surface as `series query failed` -- a 502,
        i.e. an outage, which is the one thing it would not have been."""
        r = route.get({"contract_month": "2026-12", "commodity": "corn"}, table="silver_psd",
                      metric="ending_stocks_mt")
        assert r.status_code == 400 and "delivery-month" in r.json()["detail"]
        assert route.specs == [], "the refused read still compiled a query"

    def test_an_agg_this_route_does_not_serve_is_a_400(self, route):
        """The four scalar aggs collapse to a single `{value}` row with no date, no period and no expiry --
        a point the chart cannot place. They are refused at the door rather than served as a blank point."""
        for bad in ("sum", "mean", "max", "min", "", "SERIES", "latest;drop"):
            r = route.get({"agg": bad, "commodity": SLUG, "asof": ASOF})
            assert r.status_code == 400, bad
        assert route.specs == []

    def test_the_two_aggs_that_ARE_served_still_pass(self, route):
        for good in ("series", "latest"):
            assert route.get({"agg": good, "commodity": SLUG, "asof": ASOF}).status_code == 200
        assert [s.agg for s in route.specs] == ["series", "latest"]

    def test_the_unknown_table_and_metric_refusals_are_untouched(self, route):
        assert route.get(table="not_a_table", metric="x").status_code == 404
        assert route.get(table=EOD, metric="definitely_not_a_metric").status_code == 400


# ==================================================================================================
# 5. THE SHAPE DISCRIMINATOR -- the curve is computable, the default read is the one that is not
# ==================================================================================================
class TestCurveIsNotTheInterleavedRead:
    def test_the_curve_reads_as_a_single_session_multi_expiry_object(self):
        shape = Q.series_shape(_curve_rows())
        assert shape["n_expiries"] == len(CURVE_MONTHS) and shape["n_sessions"] == 1
        assert Q.curve_as_calendar(shape) is False

    def test_the_DEFAULT_futures_series_read_is_the_shape_S4_refuses(self):
        """The defect, restated as a measurement: what /v1/series serves a futures card with no month named
        is many expiries across many sessions -- the interleaved read, where every positional index is off
        by the expiry multiplicity."""
        shape = Q.series_shape(_interleaved_rows())
        assert shape["n_expiries"] > 1 and shape["n_sessions"] > 1
        assert Q.curve_as_calendar(shape) is True

    def test_the_single_expiry_calendar_still_computes(self):
        rows = [{"value": "1", "contract_month": "2026-12", "knowledge_date": f"2026-06-0{i + 1}"}
                for i in range(5)]
        shape = Q.series_shape(rows)
        assert shape["n_expiries"] == 1 and shape["n_sessions"] == 5
        assert Q.curve_as_calendar(shape) is False

    def test_the_months_sort_nearest_to_deferred_LEXICALLY(self):
        """'YYYY-MM' sorts lexically == chronologically, which is what lets the chart take the server's
        order as the x domain instead of parsing dates client-side."""
        assert sorted(CURVE_MONTHS) == list(CURVE_MONTHS)
        assert Q._contract_months(self_spec := Q.NumberQuery(
            table=EOD, metric="settle", asof=ASOF, commodity=SLUG,
            contract_month="2027-03, 2026-07 ,2026-12")) == ["2026-07", "2026-12", "2027-03"]
        assert self_spec.contract_month == "2027-03, 2026-07 ,2026-12"   # the spec keeps the caller's text


# ==================================================================================================
# 6. THE CANARY -- still threaded, and the curve branch is unmoved under it
# ==================================================================================================
class TestCanaryStillThreaded:
    def test_the_route_still_hands_the_scope_token_to_run(self, route, monkeypatch):
        route.get({"commodity": SLUG, "asof": ASOF})
        monkeypatch.setenv("GRAPHRAG_FUTURES_NEWEST_FIRST", "on")
        route.get({"commodity": SLUG, "asof": ASOF})
        assert route.canaries == [False, True]

    def test_the_curve_compile_is_byte_identical_under_every_scope(self):
        """agg='latest' with a chronological axis is not a series branch, so no newest-first scope may touch
        it -- the curve is a single-as-of object and there is no cap to re-aim."""
        curve = TestFuturesRowsCarryAnXKey.CURVE
        ts = _ts(EOD)
        assert Q.build_sql(curve, ts) == Q.build_sql(curve, ts, futures_newest_first=True)
        assert Q.build_sql(curve, ts) == Q.build_sql(curve, ts, futures_newest_first=Q.NEWEST_FIRST_ALL)
