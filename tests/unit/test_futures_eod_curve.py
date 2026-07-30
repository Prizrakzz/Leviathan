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
  * the FENCE IS UNTOUCHED -- silver_futures_eod is still whitelist-absent, still absent from the served
    registry, and check_futures_eod is still green. W3.1 makes the dimension expressible; the W3 whitelist
    flip is a separate, gated step.
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
    """The LIVE card out of the raw tables.yaml. The table is fenced out of the loaded registry, so the
    only honest way to compile its SQL is to build the TableSpec from the card itself -- which also proves
    the card still parses under the registry's extra='forbid' schema."""
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
        if TABLE in R.load_registry().tables:                 # the whitelist flip has landed
            assert "contract_month" in self._schema_props(), (
                "silver_futures_eod is SERVED but tool_schema declares no contract_month -- every "
                "named-expiry ask is silently widened to the whole curve (W3.1 items 1-8 land TOGETHER)")
        else:
            assert TABLE in R.WHITELIST_ABSENT_DEFAULT         # pre-flip: the fence is the reason

    def test_the_card_notes_never_instruct_a_parameter_the_schema_omits(self):
        # the other half of the bind: while the parameter is undeclared, the card must not tell the
        # model to pass it (a prompt that instructs an absent knob teaches a phantom capability).
        notes = str(_card().get("notes") or "")
        if "contract_month" not in self._schema_props():
            assert not re.search(r"\bpass\s+`?contract_month", notes, re.I), notes

    def test_the_notes_state_what_an_UNNAMED_expiry_read_returns(self):
        # nearest-listed-expiry is a deterministic ORDER BY tie-break, NOT front_month_v1 (front-by-OI
        # on GLBX/CZCE/JSE) -- the serving default and the ratified roll rule name different contracts
        # for much of the year, so the card says so rather than leaving it to be inferred.
        notes = str(_card().get("notes") or "")
        assert "NEAREST listed expiry" in notes and "front month" in notes
        sql = Q.build_sql(_spec(), _ts())                      # ...and the SQL really does behave so
        assert "ORDER BY trade_date DESC, year, knowledge_date, contract_month, value LIMIT 1" in sql


# -- the fence is NOT part of this wave -------------------------------------------------------------
class TestFenceUnchanged:
    def test_still_whitelist_absent_and_unserved(self):
        assert TABLE in R.WHITELIST_ABSENT_DEFAULT
        assert TABLE not in R.load_registry().tables

    def test_registry_routed_build_sql_still_fails_closed(self):
        with pytest.raises(KeyError):
            Q.build_sql(Q.NumberQuery(table=TABLE, metric="settle", asof="2026-07-15",
                                      commodity="corn_cbot", contract_month="2026-12"))

    def test_the_card_lint_is_still_green_with_the_new_dimensions(self):
        assert cc.check_futures_eod() == []
