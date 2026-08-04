"""PRICE_AND_PLAYBOOKS W3.1 -- the DELIVERY-MONTH dimension. Pure/hermetic: no AWS, no LLM, no pg.

Before this wave a curve or named-contract ask was not EXPRESSIBLE: NumberQuery had no delivery-month
field, so "what is the December corn settle" and "is the corn curve in carry" could only decline. What
these tests pin:

  * the ROUND TRIP through build_sql -- one month compiles to an equality, several to an ``IN (...)``
    curve read, the expiry/settle_kind/currency labels come back ON every row, and ``contract_month``
    enters the deterministic total order AHEAD of ``unit`` (without it a multi-expiry result under LIMIT
    is engine-arbitrary: Athena and the pg mirror would return different EXPIRIES for the same SQL);
  * the ORACLE LOCKSTEP -- apply_pit_filter mirrors the equality and the IN form byte-for-byte, so the
    anti-leakage reference never diverges from the SQL it verifies;
  * the PARTITIONED card compiling at all -- [leviathan_slug, trade_year] with trade_year pinned by the
    sargable year bounds derived from the query's own window, never by an equality that would silently
    return zero rows for every historical read;
  * FAIL-CLOSED on a table that has no delivery month -- a contract_month ask against the roll-spliced
    continuous silver_futures_prices RAISES instead of quietly answering with a number that is not that
    expiry's, and the levels_only guard keeps priority over it;
  * the WHITELIST FLIP (2026-07-30) -- W3.1 made the dimension EXPRESSIBLE; serving the card was a
    separate, gated step, and TestWhitelistFlipLanded at the foot of this file is that step's pin (it
    held the inverse, "the fence is untouched", for the whole of W3.1).
"""
from __future__ import annotations

import re

import pytest

from leviathan.graphrag import config_check as cc
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R

TABLE = "silver_futures_eod"
FLAT = "silver_futures_prices"


def _card() -> dict:
    """The LIVE card out of the raw tables.yaml. Read RAW (not via load_registry) deliberately: these tests
    were written while the table was fenced out of the loaded registry, and reading the card directly is
    what proves it still parses under the registry's extra='forbid' schema rather than proving the loader
    happens to be configured a particular way today."""
    return dict(cc._load("numbers/tables.yaml")["tables"][TABLE])


def _ts() -> R.TableSpec:
    return R.TableSpec(id=TABLE, **_card())


def _spec(**kw) -> Q.NumberQuery:
    base = dict(table=TABLE, metric="settle", asof="2026-07-15", commodity="corn_cbot", agg="latest")
    base.update(kw)
    return Q.NumberQuery(**base)


# -- TableSpec: the new optional dimension columns -------------------------------------------------
class TestTableSpecFields:
    def test_default_to_none_so_every_other_card_is_unchanged(self):
        ts = R.TableSpec(id="x", description="", shape="wide", date_col="d")
        assert ts.contract_month_col is None
        assert ts.settle_kind_col is None
        assert ts.currency_col is None

    def test_declaring_them_is_accepted_and_readable(self):
        ts = R.TableSpec(id="x", description="", shape="wide", date_col="d",
                         contract_month_col="contract_month", settle_kind_col="settle_kind",
                         currency_col="currency")
        assert (ts.contract_month_col, ts.settle_kind_col, ts.currency_col) == (
            "contract_month", "settle_kind", "currency")

    def test_a_typoed_key_still_fails_at_load(self):
        # extra='forbid' is the whole reason a mistyped knob cannot silently disarm a dimension.
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            R.TableSpec(id="x", description="", shape="wide", contract_month_column="contract_month")

    def test_the_live_card_declares_all_three_plus_the_partition_layout(self):
        card = _card()
        assert card["contract_month_col"] == "contract_month"
        assert card["settle_kind_col"] == "settle_kind"
        assert card["currency_col"] == "currency"
        assert card["partition_cols"] == ["leviathan_slug", "trade_year"]
        assert card["year_col"] == "trade_year"          # the year partition is pinned by BOUNDS, not equality
        assert not card.get("levels_only")               # per-expiry series carry no roll splice
        assert _ts().grain_cols == ["leviathan_slug", "contract_month", "trade_date"]


# -- the round trip: one expiry, many expiries -----------------------------------------------------
class TestContractMonthFilter:
    def test_one_month_compiles_to_an_equality(self):
        sql = Q.build_sql(_spec(contract_month="2026-12"), _ts())
        assert "contract_month = '2026-12'" in sql
        assert "contract_month IN (" not in sql

    def test_several_months_compile_to_the_curve_in_list(self):
        sql = Q.build_sql(_spec(contract_month="2026-12,2027-03,2027-05"), _ts())
        assert "contract_month IN ('2026-12', '2027-03', '2027-05')" in sql
        assert "contract_month = '" not in sql

    def test_the_in_list_is_deduped_sorted_and_whitespace_tolerant(self):
        # two orderings of the SAME curve ask must compile to the SAME SQL string, or the session
        # SQL-keyed result cache misses and the two answers can diverge on a LIMIT tiebreak.
        a = Q.build_sql(_spec(contract_month="2027-03, 2026-12 ,2027-03"), _ts())
        b = Q.build_sql(_spec(contract_month="2026-12,2027-03"), _ts())
        assert a == b
        assert "contract_month IN ('2026-12', '2027-03')" in a

    def test_no_month_named_reads_the_whole_curve(self):
        sql = Q.build_sql(_spec(agg="series", period_start="2026-07-01", period_end="2026-07-10"), _ts())
        assert "contract_month = " not in sql and "contract_month IN (" not in sql
        assert "settle AS value" in sql                  # ...and it is still a real, compilable read

    def test_a_blank_month_is_not_a_filter(self):
        assert Q.build_sql(_spec(contract_month="  ,  "), _ts()) == Q.build_sql(_spec(), _ts())

    def test_the_month_literal_is_quote_safe(self):
        sql = Q.build_sql(_spec(contract_month="2026-12'; DROP"), _ts())
        assert "contract_month = '2026-12''; DROP'" in sql


# -- the labels that make a curve row attributable -------------------------------------------------
class TestExtras:
    def test_expiry_settle_kind_and_currency_ride_on_every_row(self):
        sql = Q.build_sql(_spec(), _ts())
        assert "contract_month AS contract_month" in sql
        assert "settle_kind AS settle_kind" in sql
        assert "currency AS currency" in sql

    def test_a_card_without_the_columns_surfaces_nothing_new(self):
        # byte-identical for every table that does not declare them -- no stray aliases, no ORDER BY term.
        ts = R.TableSpec(id="silver_fred_fx", description="", shape="wide", period_type="date",
                         date_col="date", knowledge_semantics="data_date")
        sql = Q.build_sql(Q.NumberQuery(table="silver_fred_fx", metric="usd_brl", asof="2026-07-15"), ts)
        for alias in ("AS contract_month", "AS settle_kind", "AS currency"):
            assert alias not in sql


# -- the deterministic total order ------------------------------------------------------------------
class TestTotalOrder:
    def test_contract_month_sits_ahead_of_unit_in_the_priority_list(self):
        pri = Q._total_order([("u", "unit"), ("c", "contract_month")])
        assert pri.split(", ").index("contract_month") < pri.split(", ").index("unit")

    def test_a_curve_read_orders_by_expiry_before_falling_back_to_value(self):
        sql = Q.build_sql(_spec(agg="series", contract_month="2026-12,2027-03"), _ts())
        order = sql.split("ORDER BY ")[1]
        assert order.startswith("year, knowledge_date, contract_month, value")

    def test_agg_latest_breaks_its_limit_1_tie_on_the_expiry(self):
        # WITHOUT contract_month in the order, "the latest corn settle" picks an ARBITRARY expiry -- a
        # different one on Athena than on the pg mirror, for the same SQL.
        sql = Q.build_sql(_spec(), _ts())
        assert "ORDER BY trade_date DESC, year, knowledge_date, contract_month, value LIMIT 1" in sql


# -- the partitioned card compiles (trade_year is BOUNDED, never pinned by equality) ----------------
class TestPartitionedCompilation:
    def test_the_slug_partition_is_a_static_equality(self):
        sql = Q.build_sql(_spec(), _ts())
        assert "leviathan_slug = 'corn_cbot'" in sql

    def test_a_commodity_less_lookup_fails_closed_twice_over(self):
        # build_sql stops at the DP-1 unit_overrides guard (a settle with 31 per-contract units cannot be
        # served without a contract), and the partition contract underneath would refuse it anyway --
        # BOTH are fail-closed, so no unattributable curve row can ever be compiled.
        with pytest.raises(ValueError, match="unit_overrides"):
            Q.build_sql(Q.NumberQuery(table=TABLE, metric="settle", asof="2026-07-15"), _ts())
        with pytest.raises(ValueError, match="requires commodity"):
            Q._partition_filters(Q.NumberQuery(table=TABLE, metric="settle", asof="2026-07-15"), _ts())

    def test_trade_year_is_bounded_by_the_asof_never_equality_pinned(self):
        sql = Q.build_sql(_spec(), _ts())
        assert "trade_year <= 2026" in sql
        assert "trade_year = " not in sql              # an equality would zero out every historical read

    def test_trade_year_bounds_follow_the_query_window(self):
        sql = Q.build_sql(_spec(agg="series", period_start="2024-02-01", period_end="2025-06-30"), _ts())
        assert "trade_year >= 2024" in sql and "trade_year <= 2025" in sql
        # the bounds are IMPLIED by the date predicates -- they exist so the catalog can prune.
        assert "substr(CAST(trade_date AS varchar), 1, 10) >= '2024-02-01'" in sql
        assert "substr(CAST(trade_date AS varchar), 1, 10) <= '2025-06-30'" in sql

    def test_dp5_normalized_guard_with_the_one_day_publication_lag(self):
        sql = Q.build_sql(_spec(), _ts())
        assert "substr(CAST(trade_date AS varchar), 1, 10) <= '2026-07-14'" in sql

    def test_levels_only_raise_is_untouched_and_never_fires_here(self):
        # the guard belongs to the roll-spliced flat table; a per-expiry window read is legitimate.
        sql = Q.build_sql(_spec(agg="mean", period_start="2026-01-01", period_end="2026-06-30",
                                contract_month="2026-12"), _ts())
        assert "avg(value) AS value" in sql and "contract_month = '2026-12'" in sql


# -- fail-closed: a delivery month asked of a table that has none -----------------------------------
class TestNoDeliveryMonthFailsClosed:
    def test_the_continuous_card_refuses_a_named_expiry(self):
        ts = R.load_registry().get(FLAT)
        assert ts.contract_month_col is None
        with pytest.raises(ValueError, match="no delivery-month column"):
            Q.build_sql(Q.NumberQuery(table=FLAT, metric="close", asof="2026-06-05",
                                      commodity="corn_cbot", agg="latest", contract_month="2026-12"), ts)

    def test_the_levels_only_guard_keeps_priority(self):
        ts = R.load_registry().get(FLAT)
        with pytest.raises(ValueError, match="levels-only"):
            Q.build_sql(Q.NumberQuery(table=FLAT, metric="close", asof="2026-06-05", commodity="corn_cbot",
                                      agg="series", period_start="2026-01-01", contract_month="2026-12"), ts)


# -- the pure-Python oracle stays in lockstep with the SQL ------------------------------------------
class TestPitOracleMirror:
    @staticmethod
    def _rows() -> list[dict]:
        out = []
        for d in ("2026-07-08 00:00:00.000", "2026-07-09 00:00:00.000"):
            for m in ("2026-09", "2026-12", "2027-03"):
                out.append({"leviathan_slug": "corn_cbot", "contract_month": m, "trade_date": d,
                            "settle_kind": "settlement", "currency": "USD", "settle": 430.0})
        out.append({"leviathan_slug": "brazilian_arabica_coffee", "contract_month": None,
                    "trade_date": "2026-07-09 00:00:00.000", "settle_kind": "cash_index",
                    "currency": "BRL", "settle": 2100.0})
        return out

    def test_one_month_keeps_only_that_expiry(self):
        kept = Q.apply_pit_filter(self._rows(), _spec(contract_month="2026-12"), _ts())
        assert {r["contract_month"] for r in kept} == {"2026-12"}
        assert len(kept) == 2                                    # both trading dates, one expiry

    def test_the_curve_form_keeps_exactly_the_listed_expiries(self):
        kept = Q.apply_pit_filter(self._rows(), _spec(contract_month="2026-12,2027-03"), _ts())
        assert {r["contract_month"] for r in kept} == {"2026-12", "2027-03"}

    def test_no_month_named_keeps_the_whole_curve(self):
        kept = Q.apply_pit_filter(self._rows(), _spec(), _ts())
        assert {r["contract_month"] for r in kept} == {"2026-09", "2026-12", "2027-03"}

    def test_a_null_month_row_never_matches_a_named_expiry(self):
        # the CEPEA cash references carry contract_month IS NULL -- fail CLOSED, exactly as SQL does.
        rows = [r for r in self._rows() if r["leviathan_slug"] == "brazilian_arabica_coffee"]
        spec = _spec(commodity="brazilian_arabica_coffee", contract_month="2026-12")
        assert Q.apply_pit_filter(rows, spec, _ts()) == []
        assert len(Q.apply_pit_filter(rows, _spec(commodity="brazilian_arabica_coffee"), _ts())) == 1

    def test_the_month_scope_does_not_weaken_the_leakage_guard(self):
        spec = _spec(asof="2026-07-09", contract_month="2026-12")     # pub lag 1 -> cutoff 2026-07-08
        kept = Q.apply_pit_filter(self._rows(), spec, _ts())
        assert [r["trade_date"][:10] for r in kept] == ["2026-07-08"]


# -- the dimension must be reachable FROM THE MODEL, not only from the engine ------------------------
class TestModelReachability:
    """An expressible dimension the TOOL SCHEMA does not declare is a dimension the model cannot use.
    The omission is SILENT, not loud: contract_month is a real NumberQuery field and the forced-spec
    path honours it if the model emits it anyway, so a model that adheres to the declared schema simply
    never names an expiry -- the December ask is WIDENED to the whole curve and agg=latest answers it
    with the nearest listed month. That is 'answer a December ask with a number that is not December's',
    the failure build_sql's delivery-month guard exists to prevent, arriving by another route.

    These are the W3.1 item-7 FLIP FENCE: whitelisting the card without the parameter fails here."""

    @staticmethod
    def _schema_props() -> dict:
        from leviathan.graphrag.numbers import agent as A
        return A.tool_schema(R.load_registry())["input_schema"]["properties"]

    def test_serving_the_card_and_declaring_the_parameter_move_together(self):
        # THE BUILD FENCE, and it has now fired in the affirmative: the flip landed 2026-07-30 and the
        # parameter landed with it. The branch is KEPT so the invariant survives a rollback (re-fencing
        # the card via WHITELIST_ABSENT_DEFAULT still passes; serving it bare still fails).
        if TABLE in R.load_registry().tables:                 # the whitelist flip has landed
            assert "contract_month" in self._schema_props(), (
                "silver_futures_eod is SERVED but tool_schema declares no contract_month -- every "
                "named-expiry ask is silently widened to the whole curve (W3.1 items 1-8 land TOGETHER)")
        else:
            assert TABLE in R.WHITELIST_ABSENT_DEFAULT         # rolled back: the fence is the reason

    def test_the_card_notes_never_instruct_a_parameter_the_schema_omits(self):
        # the other half of the bind: while the parameter is undeclared, the card must not tell the
        # model to pass it (a prompt that instructs an absent knob teaches a phantom capability).
        notes = str(_card().get("notes") or "")
        if "contract_month" not in self._schema_props():
            assert not re.search(r"\bpass\s+`?contract_month", notes, re.I), notes

    def test_the_notes_state_what_an_UNNAMED_expiry_read_returns(self):
        # nearest-listed-expiry is a deterministic ORDER BY tie-break, NOT front_month_v2 (front-by-OI
        # on GLBX/CZCE/JSE) -- the serving default and the ratified roll rule name different contracts
        # for much of the year, so the card says so rather than leaving it to be inferred.
        notes = str(_card().get("notes") or "")
        assert "NEAREST listed expiry" in notes and "front month" in notes
        sql = Q.build_sql(_spec(), _ts())                      # ...and the SQL really does behave so
        assert "ORDER BY trade_date DESC, year, knowledge_date, contract_month, value LIMIT 1" in sql


# -- the CURVE the schema PROMISES must actually COMPILE as a curve (fold 2026-07-31) --------------
class TestLatestIsPerExpiryWhenMonthsAreNamed:
    """The tool schema tells the model that a comma-separated contract_month "reads the CURVE across
    those expiries at one as-of, one row per expiry" -- and `agg` DEFAULTS to 'latest'. Through the plain
    latest branch that promise was FALSE: `ORDER BY trade_date DESC, ... LIMIT 1` returned the NEAREST
    listed expiry, and the answer narrated one number as the curve. That is the exact failure the
    delivery-month dimension exists to prevent, arriving through the new parameter -- and the deck's four
    headline rows pin curve_cited (>= 2 distinct served months), so the judged gate's affirmative half was
    uninterpretable. agg='series' is not the escape: it returns EVERY session in the window (LIMIT 5000),
    not the curve at one as-of."""

    def test_a_named_curve_read_dedups_PER_EXPIRY_not_to_one_row(self):
        sql = Q.build_sql(_spec(contract_month="2026-07,2026-09,2026-12"), _ts())
        assert "ROW_NUMBER() OVER (PARTITION BY contract_month ORDER BY trade_date DESC)" in sql
        assert "_rn = 1" in sql
        assert not sql.rstrip().endswith("LIMIT 1")            # one row per expiry, never one row overall
        assert "contract_month IN ('2026-07', '2026-09', '2026-12')" in sql

    def test_a_single_named_expiry_takes_the_same_per_expiry_shape(self):
        sql = Q.build_sql(_spec(contract_month="2026-12"), _ts())
        assert "PARTITION BY contract_month" in sql and "contract_month = '2026-12'" in sql

    def test_an_UNNAMED_read_keeps_the_documented_nearest_expiry_tiebreak(self):
        # the card's own trap and the curve_corn_nearest_not_front deck row: with NO month named a latest
        # read is still ONE row -- the nearest listed expiry, a deterministic tie-break and NOT the front
        # month. Byte-identical to before the fix, which is why the fix is scoped to a NAMED month.
        sql = Q.build_sql(_spec(), _ts())
        assert "PARTITION BY contract_month" not in sql
        assert "ORDER BY trade_date DESC, year, knowledge_date, contract_month, value LIMIT 1" in sql

    def test_every_row_still_carries_its_own_expiry_settle_kind_and_currency(self):
        # the dedup subquery exposes ALIASES only, so the outer scope must RE-PROJECT the three labels --
        # a curve row that loses its expiry / settle_kind / currency is unattributable.
        sql = Q.build_sql(_spec(contract_month="2026-07,2026-12"), _ts())
        outer_cols = sql.split(" FROM (", 1)[0]
        for alias in ("contract_month", "settle_kind", "currency"):
            assert f"AS {alias}" in sql                        # surfaced inside the dedup...
            assert alias in outer_cols                         # ...and re-projected outside it

    def test_the_leakage_guard_and_the_partition_bounds_survive_the_rewrite(self):
        sql = Q.build_sql(_spec(contract_month="2026-07,2026-12"), _ts())
        assert "leviathan_slug = 'corn_cbot'" in sql
        assert "trade_year" in sql                             # sargable year bounds still present
        assert "2026-07-14" in sql                             # as-of minus the 1-day publication lag

    def test_a_table_with_no_delivery_month_is_byte_identical(self):
        ts = R.TableSpec(id="silver_fred_fx", description="", shape="wide", period_type="date",
                         date_col="date", knowledge_semantics="data_date")
        sql = Q.build_sql(Q.NumberQuery(table="silver_fred_fx", metric="usd_brl", asof="2026-07-15"), ts)
        assert "ROW_NUMBER()" not in sql and sql.rstrip().endswith("LIMIT 1")

    def test_the_other_aggs_are_untouched(self):
        assert "ROW_NUMBER()" not in Q.build_sql(_spec(agg="series", contract_month="2026-12,2027-03"),
                                                 _ts())
        assert "ROW_NUMBER()" not in Q.build_sql(
            _spec(agg="mean", period_start="2026-01-01", period_end="2026-06-30",
                  contract_month="2026-12"), _ts())

    def test_the_agg_parameter_is_DESCRIBED_in_the_tool_schema(self):
        # `agg` had NO description at all, which is how the curve form stayed unreachable in practice:
        # the model was told the parameter reads a curve and never told which agg makes that true.
        from leviathan.graphrag.numbers import agent as A
        desc = str((A.tool_schema(R.load_registry())["input_schema"]["properties"]["agg"]
                    ).get("description") or "").lower()
        assert desc and "each" in desc and "expiry" in desc

    def test_the_card_notes_state_the_per_expiry_latest_rule(self):
        notes = str(_card().get("notes") or "")
        assert "FOR EACH named expiry" in notes


# -- the fence was a SEPARATE, gated step -- and it landed 2026-07-30 -------------------------------
# This class pinned "the fence is untouched" for the whole of W3.1. It was INVERTED at the flip rather
# than deleted: the same three facts, each pointing at its post-flip form. The dimension being
# EXPRESSIBLE (everything above) and the card being SERVED are still two different claims -- these are
# the ones about serving.
class TestWhitelistFlipLanded:
    def test_whitelisted_and_served(self):
        assert TABLE not in R.WHITELIST_ABSENT_DEFAULT
        assert TABLE in R.load_registry().tables

    def test_registry_routed_build_sql_now_compiles_the_named_expiry(self):
        # the whole point of the flip: the same call that raised KeyError through W1/W2 now compiles,
        # WITH the delivery-month equality on it (never widened to the whole curve).
        sql = Q.build_sql(Q.NumberQuery(table=TABLE, metric="settle", asof="2026-07-15",
                                        commodity="corn_cbot", contract_month="2026-12"))
        assert "contract_month = '2026-12'" in sql
        assert "leviathan_slug = 'corn_cbot'" in sql

    def test_the_card_lint_is_still_green_with_the_new_dimensions(self):
        assert cc.check_futures_eod() == []


# ==================================================================================================
# FUTURES_READPATH WAVE -- S1 (the series read shape), S3/S7 (the shape stamp), S4 (curve-vs-calendar)
# ==================================================================================================
#
# THE DEFECT S1 FIXES. The series branch compiled `ORDER BY <total order> LIMIT 5000` ASCENDING on every
# term, so a read that exceeds the cap keeps the OLDEST rows: an unbounded corn_cbot settle series stops
# around 2011 and the answer narrates a fifteen-year-old price wearing today's as-of -- no error, no
# exception, no sentinel. The remedy is not a bigger cap (that only moves the silent truncation point, and
# re-opens the scan surface the LIST-storm work closed) but which END the cap keeps: DESC in SQL, re-sorted
# back to ASC in run() so every consumer written against ascending rows stays byte-identical.
#
# THE PARTIAL FAILURE THESE TESTS EXIST TO CATCH is invisible to every other suite: ship the run() re-sort
# WITHOUT the DESC flip -- or ship a BARE DESC with no NULLS LAST -- and the cap still keeps the wrong end
# while every consumer looks right. TestS1SeriesOrderCanary pins the exact emitted string and
# TestS1CuresTheCornStops2011Case pins the row SET through an engine emulator, so neither half passes alone.
#
# NOTE ON THE :143-146 PIN. `test_a_curve_read_orders_by_expiry_before_falling_back_to_value` above is the
# ONLY series-branch ORDER BY pin in the estate, and the wave requires it to move or S1 is a no-op. It stays
# GREEN here because the flip ships behind a default-OFF canary: the flag-off surface must be byte-identical
# FROM THE IDIOM, not from a promise. The re-pin the wave owes is therefore the flag-ON twin below
# (test_the_canary_flips_the_series_order_...), which asserts the full emitted string.

CAP = 5000                                            # NumberQuery.limit's pydantic default
EXPIRIES = ["2026-%02d" % m for m in range(1, 13)] + ["2027-03"]   # 13 delivery months, as the card serves


def _emulate(universe: list[dict]):
    """A query_fn that does to `universe` what an engine does with the ORDER BY / LIMIT build_sql emitted:
    parse the emitted terms (alias + direction), sort by them, truncate at the LIMIT.

    Deliberately NOT a SQL engine -- it ignores the WHERE clause, and the universe is supplied already
    point-in-time-filtered. What it reproduces faithfully is the ONE mechanism under test: an ordered read
    truncated by a row cap. NULLs sort LAST in both directions, which is what Presto does unconditionally
    and what the flipped SQL states explicitly on every term (Postgres defaults NULLS FIRST on DESC)."""
    import functools

    def _cmp(terms):
        def cmp(a, b):
            for alias, desc in terms:
                sa = "" if a.get(alias) is None else str(a.get(alias))
                sb = "" if b.get(alias) is None else str(b.get(alias))
                if sa == sb:
                    continue
                if sa == "":
                    return 1
                if sb == "":
                    return -1
                c = 1 if sa > sb else -1
                return -c if desc else c
            return 0
        return cmp

    def qf(sql: str) -> list[dict]:
        tail = sql.split(" ORDER BY ")[1]
        order, lim = tail.rsplit(" LIMIT ", 1)
        terms = [(t.split()[0], " DESC" in f" {t}") for t in order.split(", ")]
        rows = sorted(universe, key=functools.cmp_to_key(_cmp(terms)))
        return [dict(r) for r in rows[:int(lim)]]
    return qf


def _universe(n_sessions: int = 1000, step_days: int = 6, start: str = "2010-01-04") -> list[dict]:
    """`n_sessions` corn sessions x 13 delivery months, in the alias shape BOTH backends return (every cell
    a STRING, exactly as Athena's VarCharValue and pgnumbers._stringify hand them over). 13,000 rows against
    a 5,000-row cap -- the real ratio: silver_futures_eod carries ~13 delivery months per session, which is
    why the cap bites inside a couple of years on this one card and on no other."""
    import datetime as _dt
    d0 = _dt.date.fromisoformat(start)
    rows = []
    for i in range(n_sessions):
        d = (d0 + _dt.timedelta(days=step_days * i)).isoformat()
        for j, m in enumerate(EXPIRIES):
            rows.append({"value": "%.1f" % (400 + j), "knowledge_date": d, "year": d[:4],
                         "contract_month": m, "settle_kind": "settlement", "currency": "USD"})
    return rows


def _curve_rows(n_expiries: int = 13, n_sessions: int = 1, start: str = "2026-06-08") -> list[dict]:
    import datetime as _dt
    d0 = _dt.date.fromisoformat(start)
    return [{"knowledge_date": (d0 + _dt.timedelta(days=i)).isoformat(), "year": start[:4],
             "contract_month": EXPIRIES[j], "value": "430.0"}
            for i in range(n_sessions) for j in range(n_expiries)]


def _dates(rows: list[dict]) -> list[str]:
    return [r["knowledge_date"] for r in rows]


class TestS1SeriesOrderCanary:
    """The SQL half of S1."""

    def test_flag_off_is_byte_identical_on_every_branch_of_the_futures_card(self):
        for kw in (dict(agg="series"),
                   dict(agg="series", contract_month="2026-12,2027-03"),
                   dict(agg="series", period_start="2026-01-01", period_end="2026-06-30"),
                   dict(agg="latest"),
                   dict(agg="latest", contract_month="2026-12"),
                   dict(agg="mean", period_start="2026-01-01", period_end="2026-06-30")):
            assert Q.build_sql(_spec(**kw), _ts()) == Q.build_sql(_spec(**kw), _ts(),
                                                                  futures_newest_first=False)

    def test_the_named_order_by_pin_is_untouched_with_the_canary_off(self):
        # the pin at :143-146, verbatim -- the proof the DEFAULT surface did not move
        sql = Q.build_sql(_spec(agg="series", contract_month="2026-12,2027-03"), _ts())
        assert sql.split("ORDER BY ")[1].startswith("year, knowledge_date, contract_month, value")

    def test_the_canary_flips_the_series_order_to_the_exact_reverse_with_NULLS_LAST_on_every_term(self):
        # A BARE DESC REDS HERE, and that is the point: Presto defaults NULLS LAST in both directions while
        # Postgres defaults NULLS FIRST on DESC, so a bare flip places NULL settles (~10k rows) and the
        # CEPEA cash slugs' NULL contract_month differently on the two backends for the SAME SQL.
        sql = Q.build_sql(_spec(agg="series", contract_month="2026-12,2027-03"), _ts(),
                          futures_newest_first=True)
        order, lim = sql.split("ORDER BY ")[1].rsplit(" LIMIT ", 1)
        assert order == ("year DESC NULLS LAST, knowledge_date DESC NULLS LAST, "
                         "contract_month DESC NULLS LAST, value DESC NULLS LAST")
        assert int(lim) == CAP
        assert all(t.endswith(" DESC NULLS LAST") for t in order.split(", "))   # every term, not one

    def test_the_canary_is_the_exact_reverse_of_the_ASC_order_term_for_term(self):
        asc = Q.build_sql(_spec(agg="series"), _ts()).split("ORDER BY ")[1].rsplit(" LIMIT ", 1)[0]
        desc = Q.build_sql(_spec(agg="series"), _ts(), futures_newest_first=True
                           ).split("ORDER BY ")[1].rsplit(" LIMIT ", 1)[0]
        assert [t.replace(" DESC NULLS LAST", "") for t in desc.split(", ")] == asc.split(", ")

    def test_the_canary_does_not_touch_agg_latest_bare_or_named_expiry(self):
        # the proof S1 stayed on the SERIES branch -- these two are the reads the four futures decks run
        for kw in (dict(agg="latest"), dict(agg="latest", contract_month="2026-07,2026-09,2026-12")):
            assert (Q.build_sql(_spec(**kw), _ts(), futures_newest_first=True)
                    == Q.build_sql(_spec(**kw), _ts()))

    def test_the_canary_does_not_touch_the_scalar_aggs(self):
        kw = dict(agg="mean", period_start="2026-01-01", period_end="2026-06-30", contract_month="2026-12")
        assert (Q.build_sql(_spec(**kw), _ts(), futures_newest_first=True)
                == Q.build_sql(_spec(**kw), _ts()))

    def test_a_card_with_no_delivery_month_is_byte_identical_even_with_the_canary_ON(self):
        # D-FR-2's whole scope claim, on the one test that can falsify it: the flip is keyed on
        # ts.contract_month_col, so the other 18 cards cannot move and the pg-parity re-baseline stays shut.
        ts = R.TableSpec(id="silver_fred_fx", description="", shape="wide", period_type="date",
                         date_col="date", knowledge_semantics="data_date")
        for agg in ("series", "latest", "mean"):
            spec = Q.NumberQuery(table="silver_fred_fx", metric="usd_brl", asof="2026-07-15", agg=agg,
                                 period_start="2020-01-01", period_end="2026-01-01")
            assert Q.build_sql(spec, ts, futures_newest_first=True) == Q.build_sql(spec, ts)

    def test_the_scope_guard_agrees_with_build_sqls_own_branch_selection(self):
        ts = _ts()
        assert Q._newest_first_applies(_spec(agg="series"), ts, True) is True
        assert Q._newest_first_applies(_spec(agg="series"), ts, False) is False
        assert Q._newest_first_applies(_spec(agg="latest"), ts, True) is False
        assert Q._newest_first_applies(_spec(agg="latest", contract_month="2026-12"), ts, True) is False
        assert Q._newest_first_applies(_spec(agg="mean", period_start="2026-01-01"), ts, True) is False


class TestS1CuresTheCornStops2011Case:
    """The ROW half, through an engine emulator -- because the SQL pin alone cannot tell a landed S1 from a
    re-sort shipped without the flip. 13,000 rows (1,000 sessions x 13 expiries) against the 5,000 cap."""

    @staticmethod
    def _read(newest_first: bool, universe):
        return Q.run(_spec(agg="series"), query_fn=_emulate(universe),
                     futures_newest_first=newest_first)

    def test_today_the_read_stops_years_before_the_asof_and_says_nothing(self):
        uni = _universe()
        rows = self._read(False, uni)
        d = _dates(rows)
        assert len(rows) == CAP                                   # capped...
        assert d[0] == min(_dates(uni))                           # ...at the OLDEST end
        assert d[-1] < max(_dates(uni))                           # it never reaches the newest session
        assert d == sorted(d)                                     # and it still LOOKS chronological

    def test_under_the_canary_the_read_ENDS_AT_THE_ASOF_and_is_still_ascending(self):
        uni = _universe()
        rows = self._read(True, uni)
        d = _dates(rows)
        assert len(rows) == CAP
        assert d[-1] == max(_dates(uni))                          # THE FIX: the newest session survives
        assert d[0] > min(_dates(uni))                            # the cap now bites at the OLD end
        assert d == sorted(d)                                     # ...and presentation is ASC, as before

    def test_the_canary_returns_exactly_the_NEWEST_cap_rows_of_the_universe(self):
        # equality, not an endpoint check: "ends at the as-of" is also true of a read that dropped rows out
        # of the MIDDLE. Compare the returned rows against the true newest-5000 under the total order.
        uni = _universe()
        want = sorted(uni, key=lambda r: (r["year"], r["knowledge_date"], r["contract_month"],
                                          r["value"]))[-CAP:]
        got = self._read(True, uni)
        assert [(r["knowledge_date"], r["contract_month"]) for r in got] == [
            (r["knowledge_date"], r["contract_month"]) for r in want]

    def test_the_two_reads_share_NO_ROWS_which_is_why_this_changes_served_numbers(self):
        uni = _universe()
        off = {(r["knowledge_date"], r["contract_month"]) for r in self._read(False, uni)}
        on = {(r["knowledge_date"], r["contract_month"]) for r in self._read(True, uni)}
        assert not (off & on)

    def test_S7_SPAN_the_canary_is_a_HALF_FIX_and_the_residue_is_MEASURED_not_papered_over(self):
        # (c) changes WHICH END the cap keeps, not THAT the read is capped. With limit=5000 and ~13 expiries
        # per session the survivor is the newest ~385 sessions -- a window, not a history. An endpoint check
        # alone passes that perfectly, which is exactly why S7 surfaces the span.
        uni = _universe()
        shape_all = Q.series_shape(uni)
        shape_on = Q.series_shape(self._read(True, uni))
        assert shape_on["n_sessions"] == -(-CAP // len(EXPIRIES))          # 385 sessions, not 1,000
        assert shape_on["n_sessions"] < shape_all["n_sessions"]            # the residual truncation, NAMED
        assert shape_on["last_date"] == shape_all["last_date"]             # ...the newest end is intact
        assert shape_on["first_date"] > shape_all["first_date"]
        assert shape_on["n_rows"] == CAP

    def test_the_resort_key_drops_value_so_the_backends_cannot_break_a_tie_differently(self):
        # D-FR-18. Athena prints large doubles in Java E-notation and psycopg prints plain decimal for the
        # SAME float; a Python string compare on `value` would order them differently on the two backends
        # AND differently from the SQL. The key is _total_order MINUS its final term, so `value` cannot.
        assert "value" not in Q._order_aliases(Q._extras(_ts()))
        assert Q._total_order(Q._extras(_ts())).endswith(", value")        # ...while the SQL still has it
        rows = [{"knowledge_date": "2026-05-01", "year": "2026", "contract_month": "2026-12",
                 "value": v} for v in ("1.5461095E7", "15461095.0")]
        out = Q.resort_rows_chronological(list(rows), _spec(agg="series"), _ts())
        assert [r["value"] for r in out] == ["1.5461095E7", "15461095.0"]  # executor order, untouched
        rev = Q.resort_rows_chronological(list(reversed(rows)), _spec(agg="series"), _ts())
        assert [r["value"] for r in rev] == ["15461095.0", "1.5461095E7"]

    def test_the_resort_puts_a_NULL_expiry_LAST_exactly_as_an_ASC_SQL_does(self):
        # the two CEPEA cash slugs carry contract_month IS NULL by design, and BOTH backends render NULL as
        # "". A naive text compare would hoist them to the HEAD of the read; SQL puts them last.
        rows = [{"knowledge_date": "2026-05-01", "year": "2026", "contract_month": ""},
                {"knowledge_date": "2026-05-01", "year": "2026", "contract_month": "2026-12"},
                {"knowledge_date": "2026-05-01", "year": "2026", "contract_month": None}]
        out = Q.resort_rows_chronological(rows, _spec(agg="series"), _ts())
        assert [r["contract_month"] for r in out] == ["2026-12", "", None]

    def test_the_resort_runs_BEFORE_apply_unit_overrides_and_the_line_order_IS_the_pin(self):
        # `unit` is a real total-order term (priority 9) and _apply_unit_overrides CLOBBERS r["unit"] on
        # every row -- silver_wasde declares BOTH unit_col and unit_overrides on avg_farm_price. A re-sort
        # placed after it sorts on a string the SQL never ordered by, giving an order that is neither the
        # DESC SQL's nor today's ASC. Source-position pin (the test_decline_overlap getsource idiom).
        import inspect
        body = inspect.getsource(Q.run).split('"""')[-1]        # the CODE, never the docstring's prose
        for frag in ("query_fn(sql)", "resort_rows_chronological(rows",
                     "_apply_unit_overrides(rows", "_apply_country_names(rows"):
            assert frag in body, frag
        assert (body.index("query_fn(sql)")
                < body.index("resort_rows_chronological(rows")
                < body.index("_apply_unit_overrides(rows")
                < body.index("_apply_country_names(rows"))

    def test_run_with_the_canary_OFF_is_byte_identical_rows_AND_byte_identical_SQL(self):
        uni = _universe(n_sessions=10)
        seen: list[str] = []

        def spy(sql):
            seen.append(sql)
            return _emulate(uni)(sql)
        a = Q.run(_spec(agg="series"), query_fn=spy)
        b = Q.run(_spec(agg="series"), query_fn=spy, futures_newest_first=False)
        assert a == b and seen[0] == seen[1]

    def test_a_non_futures_card_is_untouched_by_run_even_with_the_canary_ON(self):
        rows = [{"value": "3", "data_date": "2026-01-02"}, {"value": "1", "data_date": "2026-01-01"}]
        spec = Q.NumberQuery(table="silver_fred_fx", metric="usd_brl", asof="2026-07-15", agg="series")
        assert (Q.run(spec, query_fn=lambda _s: [dict(r) for r in rows], futures_newest_first=True)
                == Q.run(spec, query_fn=lambda _s: [dict(r) for r in rows]))

    def test_silver_wasde_the_ONE_card_declaring_BOTH_unit_col_AND_unit_overrides_cannot_move(self):
        # THE PLACEMENT PIN, on the named card. silver_wasde declares unit_col AND unit_overrides on
        # avg_farm_price, so it is the one card where a re-sort placed AFTER _apply_unit_overrides would
        # sort on a CLOBBERED `unit` -- an order that is neither the DESC SQL's nor today's ASC. Under the
        # futures-scoped guard the card cannot be flipped at all, so the hazard is structurally unreachable
        # rather than merely avoided, and BOTH the SQL and the post-run row order stay byte-identical.
        ts = R.load_registry().get("silver_wasde")
        assert ts.unit_col and ts.contract_month_col is None
        spec = Q.NumberQuery(table="silver_wasde", metric="avg_farm_price", asof="2026-07-15",
                             commodity="corn", agg="series")
        assert Q.build_sql(spec, ts, futures_newest_first=True) == Q.build_sql(spec, ts)
        assert Q._newest_first_applies(spec, ts, True) is False
        raw = [{"value": "4.30", "knowledge_date": "2026-05-10", "period": "2025", "country": "us",
                "unit": "junk section heading", "metric": "avg_farm_price"},
               {"value": "4.10", "knowledge_date": "2026-04-10", "period": "2025", "country": "us",
                "unit": "junk section heading", "metric": "avg_farm_price"}]
        on = Q.run(spec, query_fn=lambda _s: [dict(r) for r in raw], futures_newest_first=True)
        off = Q.run(spec, query_fn=lambda _s: [dict(r) for r in raw])
        assert on == off
        assert [r["knowledge_date"] for r in off] == ["2026-05-10", "2026-04-10"]   # executor order kept
        assert {r["unit"] for r in off} == {"$/bu"}                                 # ...and DP-1 still fires


class TestS3S7SeriesShape:
    """S3 + S7: the row count, the span and the two cardinalities the handle discards today. Every
    assertion is NON-DEGENERATE in both directions -- presence alone would pass a hardcoded stamp."""

    def test_a_single_session_curve_counts_13_expiries_and_1_session(self):
        s = Q.series_shape(_curve_rows(13, 1))
        assert (s["n_expiries"], s["n_sessions"], s["n_rows"]) == (13, 1, 13)
        assert s["first_date"] == s["last_date"] == "2026-06-08"

    def test_a_single_expiry_month_counts_1_expiry_and_22_sessions(self):
        s = Q.series_shape(_curve_rows(1, 22))
        assert (s["n_expiries"], s["n_sessions"], s["n_rows"]) == (1, 22, 22)
        assert s["first_date"] < s["last_date"]

    def test_an_all_NULL_expiry_column_counts_ZERO_expiries_not_one(self):
        # the CEPEA cash slugs. "" is absence on both backends; counting it as an expiry would make a cash
        # series look like a one-contract calendar read that happens to carry a delivery month.
        rows = [{"knowledge_date": "2026-06-0%d" % i, "contract_month": "", "value": "2100"}
                for i in range(1, 6)]
        s = Q.series_shape(rows)
        assert (s["n_expiries"], s["n_sessions"]) == (0, 5)

    def test_the_date_axis_prefers_data_date_exactly_as_the_total_order_does(self):
        rows = [{"data_date": "2026-01-01", "knowledge_date": "2026-03-01"},
                {"data_date": "2026-01-02", "knowledge_date": "2026-03-01"}]
        assert Q.series_shape(rows)["n_sessions"] == 2

    def test_an_empty_read_reports_zeros_and_never_raises(self):
        assert Q.series_shape([]) == {"n_rows": 0, "n_expiries": 0, "n_sessions": 0,
                                      "first_date": None, "last_date": None}


class TestS4CurveAsCalendarDecline:
    """S4, with the CORRECTED discriminator. The bare '>1 distinct contract_month' test OVER-DECLINES: it
    refuses a single-session CURVE, which is the read the tool schema documents and which five curve12 deck
    rows exercise. The conjunction is what makes S4's blast radius on the four futures decks ZERO."""

    def test_multi_expiry_AND_multi_session_DECLINES(self):
        assert Q.curve_as_calendar({"n_expiries": 13, "n_sessions": 22}) is True

    def test_ANTI_VACUITY_TWIN_1_a_single_expiry_calendar_still_COMPUTES(self):
        assert Q.curve_as_calendar({"n_expiries": 1, "n_sessions": 22}) is False

    def test_ANTI_VACUITY_TWIN_2_a_single_session_curve_still_COMPUTES(self):
        # the documented curve read: agg='latest' + a comma-separated contract_month, one row per expiry at
        # ONE as-of. `extrema` over it and a percentile of one expiry within it are real curve statistics.
        assert Q.curve_as_calendar({"n_expiries": 13, "n_sessions": 1}) is False

    def test_a_degenerate_or_empty_read_does_not_decline(self):
        for sh in ({"n_expiries": 0, "n_sessions": 0}, {"n_expiries": 1, "n_sessions": 1},
                   {"n_expiries": 0, "n_sessions": 22}, {}):
            assert Q.curve_as_calendar(sh) is False

    def test_THE_CASE_a_windowed_month_of_the_corn_curve_is_286_rows_and_window_change_reads_2_DAYS(self):
        # "how far has the corn curve moved over the last month" -> 22 sessions x 13 expiries = 286 rows,
        # FAR under every cap. S0 is irrelevant, S1 is irrelevant, the truncation stamp says False -- and
        # window_change(t1=-21, t2=-1) walks 21 ROWS, which on an interleaved read is ~1.6 SESSIONS. The
        # arithmetic is ASSERTED here rather than asserted in prose.
        shape = Q.series_shape(_curve_rows(13, 22))
        assert shape["n_rows"] == 286 and shape["n_rows"] < CAP
        assert (shape["n_expiries"], shape["n_sessions"]) == (13, 22)
        assert 21 / shape["n_expiries"] < 2                       # it reads under two trading days
        assert Q.curve_as_calendar(shape) is True                 # ...so it must not be computed at all

    def test_the_reason_names_BOTH_measured_counts_and_says_what_to_ask_instead(self):
        r = Q.curve_as_calendar_reason({"n_expiries": 13, "n_sessions": 22})
        assert "13 delivery months" in r and "22 sessions" in r
        assert "contract_month" in r                              # the actionable alternative, not just a no
        assert "settle" not in r                                  # the futures_lite census's banned token

    def test_the_reason_renders_from_the_shape_not_from_a_literal(self):
        a = Q.curve_as_calendar_reason(Q.series_shape(_curve_rows(3, 4)))
        b = Q.curve_as_calendar_reason(Q.series_shape(_curve_rows(13, 22)))
        assert a != b and "3 delivery months" in a and "4 sessions" in a


class TestS1CanaryFlagSeam:
    """D-FR-10: ONE env seam, cloned from _episode_outcomes_on, threaded DOWN as an omit-when-off kwarg --
    never an os.environ read inside the compiler."""

    @staticmethod
    def _an():
        from leviathan.graphrag import answer as AN
        return AN

    def test_query_py_still_reads_exactly_two_env_names_and_neither_is_a_feature_flag(self):
        import inspect
        import re as _re
        names = set(_re.findall(r"os\.environ\.get\(\s*[\"']([A-Z_]+)[\"']", inspect.getsource(Q)))
        assert names == {"LEVIATHAN_BUCKET", "ATHENA_QUERY_TIMEOUT_S"}, names

    def test_the_seam_defaults_OFF(self, monkeypatch):
        monkeypatch.delenv("GRAPHRAG_FUTURES_NEWEST_FIRST", raising=False)
        assert self._an()._futures_newest_first_on() is False

    def test_the_seam_accepts_the_house_on_1_true_spellings_and_nothing_else(self, monkeypatch):
        for v in ("on", "ON", "1", "true", "True"):
            monkeypatch.setenv("GRAPHRAG_FUTURES_NEWEST_FIRST", v)
            assert self._an()._futures_newest_first_on() is True
        for v in ("", "off", "no", "yes", "2"):
            monkeypatch.setenv("GRAPHRAG_FUTURES_NEWEST_FIRST", v)
            assert self._an()._futures_newest_first_on() is False

    def test_the_seam_is_read_PER_CALL_so_the_env_flip_rollback_needs_no_redeploy(self, monkeypatch):
        monkeypatch.setenv("GRAPHRAG_FUTURES_NEWEST_FIRST", "on")
        assert self._an()._futures_newest_first_on() is True
        monkeypatch.setenv("GRAPHRAG_FUTURES_NEWEST_FIRST", "off")
        assert self._an()._futures_newest_first_on() is False

    def test_the_kwarg_is_omit_when_off_and_keyword_only_on_both_public_entry_points(self):
        import inspect
        for fn in (Q.build_sql, Q.run):
            p = inspect.signature(fn).parameters["futures_newest_first"]
            assert p.default is False
            assert p.kind is inspect.Parameter.KEYWORD_ONLY
