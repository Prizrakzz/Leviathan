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
    otherwise arming the board would silently move every year_month card in the estate."""
    reg = load_registry()
    for spec in _specs():
        ts = reg.get(spec.table).model_copy(update={"ym_publication_lag_days": None})
        assert build_sql(spec, ts, ym_lag=True) == build_sql(spec, ts), spec.table


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
    reg = load_registry()
    assert [reg.get(t).ym_publication_lag_days for t in YM_CARDS] == [36, 45, 7]


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
