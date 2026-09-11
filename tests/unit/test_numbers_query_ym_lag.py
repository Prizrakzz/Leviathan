"""The ``year_month`` PUBLICATION LAG, threaded -- STATE ENGINE DESIGN sec 1.4 (D21), sitting S1.

THE DEFECT. A ``year_month`` card has no date column, so ``query._guard``'s year_month branch admits a
data MONTH from its FIRST DAY (``(year*100+month) <= asof_ym``) while ``_pub_lagged_asof`` shifts only
the OTHER branch. ONI's September row is therefore citable on 1 September -- three months before CPC
prints it. S0 landed ``ym_publication_lag_days`` on the three registry cards and pinned that NOTHING read
it; S1 threads the ``ym_lag`` kwarg through ``build_sql`` / ``run`` / ``apply_pit_filter`` and moves the
branch at BOTH sites.

THE TWO PROPERTIES THIS FILE EXISTS FOR:
  1. OFF is byte-identical -- the rollback, taken from the idiom rather than from a promise;
  2. the COMPILER and its ORACLE agree. ``apply_pit_filter`` is "the pure-Python reference for the SAME
     point-in-time semantics build_sql encodes", and an oracle that verifies a different rule than the
     compiler encodes verifies nothing (the R2 trap its own comment names).
"""
import pytest

from leviathan.graphrag.numbers.query import (NumberQuery, apply_pit_filter, build_sql,
                                              _ym_lagged_asof_ym)
from leviathan.graphrag.numbers.registry import load_registry

YM_CARDS = ("silver_noaa_oni", "silver_noaa_iod", "gold_weather_z")


def _specs():
    return [
        NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="latest"),
        NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="series", limit=120),
        NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="series",
                    period_start="2016-09-01", limit=120),
        NumberQuery(table="silver_noaa_iod", metric="dmi_value", asof="2026-03-15", agg="latest"),
        NumberQuery(table="gold_weather_z", metric="drought_z", asof="2026-06-30", agg="series",
                    commodity="soybeans_cbot", country="United States", limit=120),
    ]


# ── OFF is the rollback ──────────────────────────────────────────────────────────────────────────────
def test_flag_off_is_byte_identical_on_every_spec():
    reg = load_registry()
    for spec in _specs():
        ts = reg.get(spec.table)
        assert build_sql(spec, ts) == build_sql(spec, ts, ym_lag=False), spec.table


def test_flag_ON_against_a_card_that_declares_no_lag_is_ALSO_byte_identical():
    """UNDECLARED means NO SHIFT (the field's default is ``None``, deliberately not ``0``). The board
    passes ``ym_lag=True`` on every read, so a card without the key must compile exactly what it did --
    otherwise arming the board would silently move every year_month card in the estate.

    "DECLARES NO LAG" MEANS THE WHOLE CARD (widened 2026-09-11). The guard reads the METRIC's lag now,
    through ``registry.lag_days_for``, so stripping only the card-level field leaves the per-metric
    overrides standing and the card still shifts -- correctly. The stripped card here therefore drops
    both, which is the only shape that is honestly "a card that declares no lag"."""
    reg = load_registry()
    for spec in _specs():
        card = reg.get(spec.table)
        bare = {m: s.model_copy(update={"ym_publication_lag_days": None})
                for m, s in (card.metrics or {}).items()}
        ts = card.model_copy(update={"ym_publication_lag_days": None, "metrics": bare})
        assert build_sql(spec, ts, ym_lag=True) == build_sql(spec, ts), spec.table


def test_stripping_ONLY_the_card_default_still_moves_a_card_whose_METRIC_declares_one():
    """The falsifier for the test above, and the proof that the guard is reading the metric at all: a
    ``gold_weather_z`` card with its default removed but ``drought_z``'s own 25 intact STILL shifts,
    because the metric's declaration is the one that governs."""
    reg = load_registry()
    spec = NumberQuery(table="gold_weather_z", metric="drought_z", asof="2026-09-11", agg="series",
                       commodity="soybeans_cbot", country="United States", limit=120)
    ts = reg.get("gold_weather_z").model_copy(update={"ym_publication_lag_days": None})
    assert "(year * 100 + month) <= 202607" in build_sql(spec, ts, ym_lag=True)
    assert "(year * 100 + month) <= 202609" in build_sql(spec, ts)


def test_no_non_year_month_card_moves_under_the_flag():
    """ONE BRANCH. ``publication_lag_days`` and the vintage collapse are untouched -- that separation is
    the whole reason the key is not ``publication_lag_days`` (which would also render a lag sentence into
    the numbers agent's cached system block)."""
    reg = load_registry()
    for table, metric in [("silver_cot", "mm_net_position"), ("silver_pink_sheet", "brent_crude")]:
        try:
            ts = reg.get(table)
        except Exception:                                    # noqa: BLE001 -- card absent, skip
            continue
        m = metric if metric in ts.metrics else sorted(ts.metrics)[0]
        spec = NumberQuery(table=table, metric=m, asof="2026-09-08", agg="series", limit=50)
        assert ts.knowledge_semantics != "year_month"
        assert build_sql(spec, ts, ym_lag=True) == build_sql(spec, ts), table


# ── ON: the month-end arithmetic ─────────────────────────────────────────────────────────────────────
def test_the_lag_is_days_after_MONTH_END_not_days_after_the_month_starts():
    """MEASURED (ONI, the S0 declaration of 36 days, as-of 2026-09-08): ``asof - 36 d`` is 2026-08-03,
    whose MONTH reads as 2026-08 -- but 2026-08 does not END until the 31st, so the newest month the
    publisher has actually printed is 2026-07. A bare ``_asof_ym(asof - lag)`` would admit a month that
    does not exist yet, which is the very leak the key exists to close."""
    assert _ym_lagged_asof_ym("2026-09-08", 36) == 202607
    assert _ym_lagged_asof_ym("2026-09-08", None) == 202609      # undeclared -> identity
    assert _ym_lagged_asof_ym("2026-09-08", 0) == 202609
    # exactly ON a month end: the month has ended, so it is admitted
    assert _ym_lagged_asof_ym("2026-10-06", 36) == 202608        # 2026-10-06 - 36 d = 2026-08-31
    assert _ym_lagged_asof_ym("2026-10-07", 36) == 202608
    # a JANUARY shifted-date rolls the YEAR back, never to month 0
    assert _ym_lagged_asof_ym("2026-02-20", 36) == 202512        # 2026-02-20 - 36 d = 2026-01-15
    assert _ym_lagged_asof_ym("2026-02-06", 36) == 202512        # 2026-02-06 - 36 d = 2025-12-31 (end)
    assert _ym_lagged_asof_ym("2026-02-01", 36) == 202511        # 2026-02-01 - 36 d = 2025-12-27
    # a FEBRUARY month end is 28 or 29, and the arithmetic reads the real calendar, never a 30/31 rule
    assert _ym_lagged_asof_ym("2024-03-05", 5) == 202402         # 2024-02-29 == that leap month's end


def test_the_compiled_guard_moves_and_takes_its_year_bound_with_it():
    reg = load_registry()
    ts = reg.get("silver_noaa_oni")
    spec = NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-01-05", agg="series",
                       limit=120)
    off, on = build_sql(spec, ts), build_sql(spec, ts, ym_lag=True)
    assert "(year * 100 + month) <= 202601" in off and "year <= 2026" in off
    # 2026-01-05 - 36 d = 2025-11-30 == that month's end -> 2025-11, and the YEAR bound follows it, or
    # projection pruning would keep enumerating a year the guard no longer admits
    assert "(year * 100 + month) <= 202511" in on and "year <= 2025" in on


# ── THE LAG IS THE METRIC'S, NOT THE CARD'S (fix 2026-09-11) ─────────────────────────────────────────
class TestTheGuardReadsTheMetricsOwnLag:
    """``_guard`` and ``apply_pit_filter`` read ``registry.lag_days_for(ts, spec.metric)``.

    THE DEFECT, stated as the turn it produced. Both sites read the CARD default off ``ts`` while the
    spec in hand named a metric, and the board passes ``ym_lag=True`` on EVERY read
    (``state/feeders`` :693/:1059/:1350/:1391/:1692, ``state/board_census`` :1138/:1288). So on the one
    card that declares per-metric lags a ``drought_z`` row was ADMITTED under the card's 5-day NASA
    default, while the analog knowledge axis -- ``state/analogs._lag_days_of`` via
    ``registry.metric_lag_override`` -- RANKED that same row under CHIRPS' own block lag. One engine,
    one turn, two point-in-time rules for one figure.

    THE ARITHMETIC, at the as-of the fix was measured on (2026-09-11):
      * ``drought_z`` (lag 25): 2026-07-31 + 25 = 2026-08-25 <= 2026-09-11, so 202607 is admitted;
        2026-08-31 + 25 = 2026-09-25 > 2026-09-11, so 202608 is not. Guard literal 202607.
      * ``tmax_anomaly`` (lag 5): 2026-08-31 + 5 = 2026-09-05 <= 2026-09-11. Guard literal 202608.
    """

    ASOF = "2026-09-11"

    @staticmethod
    def _spec(metric):
        return NumberQuery(table="gold_weather_z", metric=metric, asof="2026-09-11", agg="series",
                           commodity="soybeans_cbot", country="United States", limit=120)

    @staticmethod
    def _literal(sql):
        return int(sql.split("(year * 100 + month) <= ")[1].split()[0])

    def test_two_metrics_of_ONE_card_compile_TWO_different_guard_literals(self):
        ts = load_registry().get("gold_weather_z")
        assert self._literal(build_sql(self._spec("drought_z"), ts, ym_lag=True)) == 202607
        assert self._literal(build_sql(self._spec("tmax_anomaly"), ts, ym_lag=True)) == 202608
        # the YEAR bound follows each one, or projection pruning enumerates a year the guard refuses
        assert "year <= 2026" in build_sql(self._spec("drought_z"), ts, ym_lag=True)

    def test_the_DERIVED_SIBLINGS_compile_the_STEMS_literal_not_the_cards(self):
        """``drought_z_tail_share`` and ``drought_z_cells`` are the same CHIRPS cells aggregated. The
        defect served them under the NASA promise -- a basin tail-share a month before the rain that
        made it was published, and nothing downstream could see it."""
        ts = load_registry().get("gold_weather_z")
        for metric in ("drought_z_tail_share", "drought_z_cells"):
            assert self._literal(build_sql(self._spec(metric), ts, ym_lag=True)) == 202607, metric
        for metric in ("heat_stress_z_tail_share", "gdd_z_cells", "frost_event_share"):
            assert self._literal(build_sql(self._spec(metric), ts, ym_lag=True)) == 202608, metric

    def test_the_ORACLE_agrees_with_the_COMPILER_metric_by_metric(self):
        """``apply_pit_filter`` is build_sql's pure-Python reference and the anti-leakage property
        test's own oracle. An oracle holding the card default while the compiler holds the metric's
        override verifies nothing -- the R2 trap, one level down."""
        ts = load_registry().get("gold_weather_z")
        rows = [{"year": 2026, "month": m, "value": float(m), "metric": None,
                 "commodity": "soybeans_cbot", "country": "United States"} for m in (6, 7, 8, 9)]
        for metric, want in (("drought_z", 202607), ("tmax_anomaly", 202608),
                             ("drought_z_cells", 202607), ("gdd_z", 202608)):
            spec = self._spec(metric)
            for r in rows:
                r["metric"] = metric
            literal = self._literal(build_sql(spec, ts, ym_lag=True))
            assert literal == want, metric
            kept = apply_pit_filter(rows, spec, ts, ym_lag=True)
            assert {r["year"] * 100 + r["month"] for r in kept} == \
                   {r["year"] * 100 + r["month"] for r in rows
                    if r["year"] * 100 + r["month"] <= literal}, metric

    def test_the_defect_itself_reproduced_on_the_CARD_DEFAULT_read_it_replaced(self):
        """What the shipped code did, written out so the fix is a diff rather than a claim: reading
        ``ts.ym_publication_lag_days`` for ``drought_z`` compiles 202608 -- one month wider than the
        metric's own promise, which is a CHIRPS block that had not published."""
        ts = load_registry().get("gold_weather_z")
        assert _ym_lagged_asof_ym(self.ASOF, ts.ym_publication_lag_days) == 202608
        assert self._literal(build_sql(self._spec("drought_z"), ts, ym_lag=True)) == 202607

    def test_OFF_is_still_byte_identical_for_every_metric_of_the_card(self):
        """The rollback is untouched by the fix: with the flag off, the metric is never consulted."""
        ts = load_registry().get("gold_weather_z")
        for metric in sorted(ts.metrics):
            spec = self._spec(metric)
            assert build_sql(spec, ts) == build_sql(spec, ts, ym_lag=False), metric
            assert self._literal(build_sql(spec, ts)) == 202609, metric


# ── the compiler and its oracle agree ────────────────────────────────────────────────────────────────
def _rows(y0=2025, n=15):
    out, y, m = [], y0, 1
    for i in range(n):
        out.append({"year": y, "month": m, "value": float(i)})
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


@pytest.mark.parametrize("asof", ["2026-09-08", "2026-01-05", "2026-02-01", "2026-10-06"])
def test_the_oracle_admits_exactly_the_months_the_compiled_guard_admits(asof):
    """PARITY, spec by spec: the oracle's kept set is exactly the rows whose ``year*100+month`` clears
    the literal the SQL compiled. Compiled-vs-filtered on ONE fixture, both settings."""
    reg = load_registry()
    ts = reg.get("silver_noaa_oni")
    spec = NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof=asof, agg="series", limit=200)
    rows = _rows()
    for ym_lag in (False, True):
        sql = build_sql(spec, ts, ym_lag=ym_lag)
        literal = int(sql.split("(year * 100 + month) <= ")[1].split()[0])
        kept = apply_pit_filter(rows, spec, ts, ym_lag=ym_lag)
        assert {r["year"] * 100 + r["month"] for r in kept} == \
               {r["year"] * 100 + r["month"] for r in rows if r["year"] * 100 + r["month"] <= literal}


def test_the_oracle_off_is_byte_identical_to_the_shipped_behaviour():
    reg = load_registry()
    ts = reg.get("silver_noaa_oni")
    spec = NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="series")
    rows = [{"year": 2026, "month": m, "value": float(m)} for m in (7, 8, 9, 10)]
    assert [(r["year"], r["month"]) for r in apply_pit_filter(rows, spec, ts)] == \
           [(2026, 7), (2026, 8), (2026, 9)]
    # and the S0 pin's own stated expectation of what the 36-day lag does when it arms
    assert [(r["year"], r["month"]) for r in apply_pit_filter(rows, spec, ts, ym_lag=True)] == \
           [(2026, 7)]


def test_the_three_board_cards_still_carry_their_declared_lags():
    """gold_weather_z moved 7 -> 5 on 2026-09-11, and the move is a MEASUREMENT replacing a card note
    that called its own 7 unverified: NASA POWER AG runs 3 days behind (the September window fetched
    that day held 8 real days, last 2026-09-08, the trailing ~3 filled with -999), plus a 2-day margin.
    The card's OTHER source is ~20 days slower, so drought_z carries its own 25 as a per-metric
    override -- see tests/unit/test_state_registry_ym_lag.py::TestPerMetricLag, which is where that
    half lives (and where the 45 this corrects is written up as a misread bound).

    WHAT THIS CARD-LEVEL NUMBER STILL GOVERNS, stated correctly (2026-09-11): since the metric fix,
    ``_guard`` reads ``registry.lag_days_for(ts, spec.metric)``, so the card field governs every
    metric that declares nothing of its own -- which on THIS card is now none of them, and on every
    OTHER card in the estate is all of them. It is still the value ``lag_days_for`` falls back to and
    still the one a reader with no metric in hand gets.

    MEASURED, and the correction of a claim this docstring used to make: the knowable month is a step
    function of the lag but the steps are NOT 28 days wide -- ``_ym_lagged_asof_ym`` subtracts the lag
    and then asks whether the shifted month has ENDED, so two lags disagree whenever they straddle a
    month-end. 5 and 7 differ on exactly 24 days of 2026 (the 5th and 6th of each month) and agree on
    the other 341; "every value from 1 to 28 places the same prior month" is refuted by that same
    count."""
    reg = load_registry()
    assert [reg.get(t).ym_publication_lag_days for t in YM_CARDS] == [36, 45, 5]

    import datetime as _dt

    from leviathan.graphrag.numbers.query import _ym_lagged_asof_ym
    d, disagree = _dt.date(2026, 1, 1), []
    while d < _dt.date(2027, 1, 1):
        s = d.isoformat()
        if _ym_lagged_asof_ym(s, 7) != _ym_lagged_asof_ym(s, 5):
            disagree.append(s)
        d += _dt.timedelta(days=1)
    assert [s[-2:] for s in disagree] == ["05", "06"] * 12 and len(disagree) == 24, disagree


# ── the kwarg is OMITTED at the call site while it is off ────────────────────────────────────────────
def test_run_does_not_even_MENTION_the_kwarg_while_the_flag_is_off(monkeypatch):
    """MEASURED, not stylistic: the estate wraps ``build_sql`` in spies that RE-DECLARE its signature
    (``tests/unit/test_futures_readpath_pins.py::_sql_spy`` sits AT the compiler on purpose, so that a
    kwarg accepted and then dropped one frame lower is caught). Passing a new kwarg unconditionally
    broke five of those pins on turns not using the flag at all. Omit-when-off keeps the shipped call
    byte-identical until the board arms it -- the same discipline the emitted SQL follows.

    The shim below is DELIBERATELY NARROW: it accepts exactly what the shipped compiler accepted, so a
    regression to an unconditional pass raises TypeError here rather than in someone else's deck."""
    import leviathan.graphrag.numbers.query as Q

    real = Q.build_sql
    seen = []

    def _narrow(spec, ts=None, *, db=Q.ATHENA_DB, futures_newest_first=False):
        seen.append(futures_newest_first)
        return real(spec, ts, db=db, futures_newest_first=futures_newest_first)

    monkeypatch.setattr(Q, "build_sql", _narrow)
    spec = NumberQuery(table="silver_noaa_oni", metric="oni_anom", asof="2026-09-08", agg="series",
                       limit=10)
    Q.run(spec, query_fn=lambda _sql: [])
    assert seen == [False]

    with pytest.raises(TypeError):                       # and ARMING it needs the widened signature
        Q.run(spec, query_fn=lambda _sql: [], ym_lag=True)
