"""D-EC DK-13 -- the CBOT board crush, pinned as a definition rather than a diff.

The crush is arithmetic over three legs the platform already stores, which makes
the failure mode UNITS, not availability: every coefficient IS a unit
conversion, so a leg re-quoted by its venue publishes a number wrong by a
constant factor with nothing in the data to show it.  These tests pin the
formula, the units it assumes, the three-leg rule, and the seam that stops this
implementation drifting away from the feature layer's older one.

Pure Python -- no S3, no AWS.
"""
from __future__ import annotations

import warnings

import pandas as pd
import pytest

import leviathan.transforms.gold.board_crush as BC
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver import futures_roll as FR


def _leg(slug: str, trade_date: str, contract_month: str, settle: float,
         *, open_interest: float = 1000.0, settle_kind: str = "settlement") -> dict:
    return {
        "leviathan_slug": slug,
        "trade_date": trade_date,
        "contract_month": contract_month,
        "settle": settle,
        "settle_kind": settle_kind,
        "unit": FC.CONTRACT_MAP[slug]["unit"],
        "currency": "USD",
        "open_interest": open_interest,
        "volume": 500.0,
        "instrument_kind": "futures",
        "source": "databento_glbx_mdp3",
        "close": settle,
        "raw_symbol": f"{slug}-{contract_month}",
    }


def _session(trade_date: str = "2026-08-13", *, beans: float = 1050.0,
             meal: float = 300.0, oil: float = 50.0,
             contract_month: str = "2026-11", **kw) -> pd.DataFrame:
    """One trading session with all three legs printing a front month."""
    return pd.DataFrame([
        _leg("soybeans_cbot", trade_date, contract_month, beans, **kw),
        _leg("soybean_meal_cbot", trade_date, contract_month, meal, **kw),
        _leg("soybean_oil_cbot", trade_date, contract_month, oil, **kw),
    ])


# ---------------------------------------------------------------------------
# The formula.
# ---------------------------------------------------------------------------
class TestCrushArithmetic:

    def test_the_worked_example(self) -> None:
        # beans 1050 c/bu, meal $300/short ton, oil 50 c/lb:
        #   meal  0.022 * 300  =  6.60 $/bu
        #   oil   0.11  *  50  =  5.50 $/bu
        #   beans 0.01  * 1050 = 10.50 $/bu
        #   crush = 6.60 + 5.50 - 10.50 = 1.60 $/bu
        out = BC.compute_board_crush(_session())
        assert len(out) == 1
        r = out.iloc[0]
        assert r["meal_value_usd_bu"] == pytest.approx(6.60)
        assert r["oil_value_usd_bu"] == pytest.approx(5.50)
        assert r["bean_cost_usd_bu"] == pytest.approx(10.50)
        assert r["crush_margin_usd_bu"] == pytest.approx(1.60)

    def test_a_negative_crush_is_a_real_reading_not_an_error(self) -> None:
        # Negative board crush happens -- it is what a processor squeeze looks
        # like -- and nothing here clamps it.
        out = BC.compute_board_crush(_session(beans=1400.0, meal=280.0, oil=42.0))
        assert out.iloc[0]["crush_margin_usd_bu"] < 0

    def test_the_parts_reconstruct_the_whole(self) -> None:
        # The legs ride on the row so a reader can audit the number instead of
        # trusting it. That property is only true if it actually holds.
        out = BC.compute_board_crush(_session(beans=1123.25, meal=311.4, oil=53.77))
        r = out.iloc[0]
        assert (r["meal_value_usd_bu"] + r["oil_value_usd_bu"] - r["bean_cost_usd_bu"]
                == pytest.approx(r["crush_margin_usd_bu"]))

    def test_coefficients_are_the_standard_yield_conversions(self) -> None:
        assert BC.MEAL_COEF == pytest.approx(44 / 2000)   # 44 lb meal per bushel
        assert BC.OIL_COEF == pytest.approx(11 / 100)     # 11 lb oil, cents -> dollars
        assert BC.BEAN_COEF == pytest.approx(1 / 100)     # cents/bushel -> dollars

    def test_this_module_and_the_feature_layer_cannot_drift_apart(self) -> None:
        # THE SEAM. features.computations.sd_balance.compute_crush_margin_z has
        # computed this same margin, off silver_futures_prices, since before this
        # table existed. Two implementations of one number is the exact failure
        # futures_roll.py's module docstring exists to prevent, and the estate's
        # answer is to BIND them rather than to hope. This test is that bind: if
        # either side's coefficients move, this reddens and the convergence
        # decision (retire one, or repoint the feature at this table when W3
        # retires the yfinance chain) gets made deliberately.
        import inspect

        from leviathan.features.computations import sd_balance
        src = inspect.getsource(sd_balance.compute_crush_margin_z)
        assert f'"meal_coef", {BC.MEAL_COEF}' in src, (
            "the feature layer's meal_coef default no longer matches this module's MEAL_COEF")
        assert f'"oil_coef", {BC.OIL_COEF}' in src, (
            "the feature layer's oil_coef default no longer matches this module's OIL_COEF")
        assert f'"bean_coef", {BC.BEAN_COEF}' in src, (
            "the feature layer's bean_coef default no longer matches this module's BEAN_COEF")
        # ...and the two are versioned SEPARATELY on purpose: this one is a
        # per-session level under a named roll rule, that one an annual z-score
        # off a continuous close. Same arithmetic, different objects.
        assert BC.CRUSH_RULE_VERSION == "cbot_board_crush_v1"


# ---------------------------------------------------------------------------
# Units -- the failure mode that has no signature in the data.
# ---------------------------------------------------------------------------
class TestUnitFence:

    def test_the_assumed_units_are_the_shipped_ones(self) -> None:
        assert FC.CONTRACT_MAP["soybeans_cbot"]["unit"] == "US cents/bushel"
        assert FC.CONTRACT_MAP["soybean_meal_cbot"]["unit"] == "USD/short ton"
        assert FC.CONTRACT_MAP["soybean_oil_cbot"]["unit"] == "US cents/lb"

    def test_a_requoted_leg_makes_the_transform_refuse(self, monkeypatch) -> None:
        # The MIAX class: a venue publishing dollars where the estate assumed
        # cents differs by 100x, and NOTHING in the value shows it. The estate's
        # doctrine is that the label moves to the data and the value is never
        # rescaled -- so this refuses, loudly, rather than publishing.
        patched = dict(FC.CONTRACT_MAP)
        patched["soybeans_cbot"] = dict(patched["soybeans_cbot"], unit="USD/bushel")
        monkeypatch.setattr(FC, "CONTRACT_MAP", patched)
        with pytest.raises(ValueError, match="coefficients ARE the unit conversion"):
            BC.compute_board_crush(_session())

    def test_every_leg_is_a_real_contract(self) -> None:
        for slug in BC.CRUSH_LEGS.values():
            assert slug in FC.CONTRACT_MAP


# ---------------------------------------------------------------------------
# The three-leg rule and the roll rule.
# ---------------------------------------------------------------------------
class TestThreeLegRule:

    def test_a_session_missing_a_leg_is_dropped_not_filled(self) -> None:
        # A crush from two legs and a stale third is not a wider series, it is a
        # wrong one. Decline, never splice -- the price layer's own posture.
        full = _session("2026-08-12")
        partial = _session("2026-08-13")
        partial = partial[partial.leviathan_slug != "soybean_oil_cbot"]
        out = BC.compute_board_crush(pd.concat([full, partial], ignore_index=True))
        assert list(out.trade_date) == ["2026-08-12"]

    def test_no_legs_at_all_returns_the_empty_schema(self) -> None:
        out = BC.compute_board_crush(pd.DataFrame(columns=BC.INPUT_COLUMNS))
        assert list(out.columns) == BC.PHYSICAL_COLUMNS
        assert out.empty

    def test_an_unrelated_slug_is_ignored_not_mistaken_for_a_leg(self) -> None:
        noise = pd.DataFrame([_leg("corn_cbot", "2026-08-13", "2026-12", 430.0)])
        out = BC.compute_board_crush(pd.concat([_session(), noise], ignore_index=True))
        assert len(out) == 1

    def test_missing_open_interest_declines_rather_than_degrading_the_roll(self) -> None:
        # All three legs are GLBX, i.e. front-by-OPEN-INTEREST. With OI absent the
        # rule's input contract is unsatisfied, and a crush selected by a degraded
        # rule would be indistinguishable from a real one.
        s = _session()
        s["open_interest"] = pd.NA
        assert BC.compute_board_crush(s).empty

    def test_the_front_month_is_the_ONE_rule_and_its_version_rides_the_row(self) -> None:
        # Two eligible delivery months, the far one carrying the open interest:
        # the rule picks by OI, not by nearness, and says which rule it used.
        rows = []
        for slug, settle in (("soybeans_cbot", 1050.0), ("soybean_meal_cbot", 300.0),
                             ("soybean_oil_cbot", 50.0)):
            rows.append(_leg(slug, "2026-08-13", "2026-09", settle * 2, open_interest=10.0))
            rows.append(_leg(slug, "2026-08-13", "2026-11", settle, open_interest=9000.0))
        out = BC.compute_board_crush(pd.DataFrame(rows))
        assert len(out) == 1
        assert out.iloc[0]["beans_contract_month"] == "2026-11"
        assert out.iloc[0]["roll_rule_version"] == FR.ROLL_RULE_VERSION
        assert out.iloc[0]["crush_rule_version"] == BC.CRUSH_RULE_VERSION

    def test_a_delivery_month_already_started_is_never_front(self) -> None:
        rows = []
        for slug, settle in (("soybeans_cbot", 1050.0), ("soybean_meal_cbot", 300.0),
                             ("soybean_oil_cbot", 50.0)):
            rows.append(_leg(slug, "2026-08-13", "2026-07", settle, open_interest=99999.0))
        assert BC.compute_board_crush(pd.DataFrame(rows)).empty


# ---------------------------------------------------------------------------
# The output contract.
# ---------------------------------------------------------------------------
class TestOutputShape:

    def test_columns_and_order_are_the_declared_contract(self) -> None:
        out = BC.compute_board_crush(_session())
        assert list(out.columns) == BC.PHYSICAL_COLUMNS

    def test_one_row_per_session_ordered_by_date(self) -> None:
        frames = [_session(d) for d in ("2026-08-13", "2026-08-11", "2026-08-12")]
        out = BC.compute_board_crush(pd.concat(frames, ignore_index=True))
        assert list(out.trade_date) == ["2026-08-11", "2026-08-12", "2026-08-13"]
        assert not out.trade_date.duplicated().any()

    def test_trade_date_is_an_iso_string_like_its_source(self) -> None:
        out = BC.compute_board_crush(_session())
        assert out.trade_date.iloc[0] == "2026-08-13"
        assert isinstance(out.trade_date.iloc[0], str)

    def test_settle_kind_rides_the_row(self) -> None:
        # A crush built from session CLOSES is a different object from one built
        # from official SETTLEMENTS, exactly as it is one row down in futures_eod.
        out = BC.compute_board_crush(_session())
        assert out.iloc[0]["settle_kind"] == "settlement"

    def test_a_mixed_session_says_mixed_rather_than_picking_one(self) -> None:
        rows = [
            _leg("soybeans_cbot", "2026-08-13", "2026-11", 1050.0, settle_kind="settlement"),
            _leg("soybean_meal_cbot", "2026-08-13", "2026-11", 300.0, settle_kind="settlement"),
            _leg("soybean_oil_cbot", "2026-08-13", "2026-11", 50.0, settle_kind="close"),
        ]
        out = BC.compute_board_crush(pd.DataFrame(rows))
        assert out.iloc[0]["settle_kind"] == "mixed"

    def test_a_missing_required_column_raises_rather_than_guessing(self) -> None:
        s = _session().drop(columns=["contract_month"])
        with pytest.raises(ValueError, match="missing"):
            BC.compute_board_crush(s)


# ---------------------------------------------------------------------------
# What DK-13 asked for and this table deliberately does not do.
# ---------------------------------------------------------------------------
class TestScopeRefusals:

    def test_only_the_three_cbot_legs_are_in_scope(self) -> None:
        # DK-13 also names the ZCE rapeseed crush and the DCE import crush.
        # Neither is computable from what the platform holds: both venues quote
        # in CNY/t, so a crush there needs an FX leg (and, for the import crush,
        # freight) -- and this estate converts NOTHING at ingest by doctrine.
        # Refused on the record rather than approximated.
        assert set(BC.CRUSH_LEGS.values()) == {
            "soybeans_cbot", "soybean_meal_cbot", "soybean_oil_cbot"}
        for cny in ("soybean_meal_dce", "soybean_oil_dce", "rapeseed_meal_zce",
                    "rapeseed_oil_zce"):
            assert cny not in BC.CRUSH_LEGS.values()
            assert FC.CONTRACT_MAP[cny]["currency"] == "CNY"

    def test_the_dce_legs_are_ignored_even_when_present_in_the_frame(self) -> None:
        dce = pd.DataFrame([
            _leg("soybean_meal_dce", "2026-08-13", "2026-11", 3000.0),
            _leg("soybean_oil_dce", "2026-08-13", "2026-11", 8000.0),
        ])
        out = BC.compute_board_crush(pd.concat([_session(), dce], ignore_index=True))
        assert len(out) == 1
        assert out.iloc[0]["crush_margin_usd_bu"] == pytest.approx(1.60)


# ---------------------------------------------------------------------------
# The input contract, asked PER TRADE DATE.
#
# MEASURED on the published tape 2026-08-20: GLBX open interest -- the input the
# ONE front-month rule reads for all three legs -- does not exist before
# 2015-11-19 (1,485 dates, zero OI prints on any contract of any leg), and 47
# later sessions are statistics blackouts or expiring-contract final prints.
# Asked ONCE over the whole 153,806-row history the contract is therefore always
# False, which is how this table's first fire published nothing at all. Asked per
# session it is True on 2,652 dates. These tests pin that the granularity moved
# and the POSTURE did not: a refused date is refused alone, in writing, and is
# never filled, carried, or tie-broken around.
# ---------------------------------------------------------------------------
class TestPerDateInputContract:

    def test_one_missing_print_refuses_its_own_date_and_no_other(self) -> None:
        good_before = _session("2026-08-12")
        bad = _session("2026-08-13")
        # ONE leg, ONE eligible candidate, on ONE date.
        bad.loc[bad.leviathan_slug == "soybean_oil_cbot", "open_interest"] = pd.NA
        good_after = _session("2026-08-14")
        out = BC.compute_board_crush(
            pd.concat([good_before, bad, good_after], ignore_index=True))
        assert list(out.trade_date) == ["2026-08-12", "2026-08-14"]

    def test_the_neighbours_are_untouched_not_merely_present(self) -> None:
        # "Refused alone" has to mean the surviving rows are the SAME rows the
        # transform would have emitted anyway -- not a rebuilt series.
        clean = pd.concat([_session("2026-08-12"), _session("2026-08-14")],
                          ignore_index=True)
        bad = _session("2026-08-13")
        bad.loc[bad.leviathan_slug == "soybeans_cbot", "open_interest"] = pd.NA
        mixed = BC.compute_board_crush(pd.concat([clean, bad], ignore_index=True))
        assert mixed.reset_index(drop=True).equals(
            BC.compute_board_crush(clean).reset_index(drop=True))

    def test_a_refused_date_is_never_filled_from_its_neighbour(self) -> None:
        bad = _session("2026-08-13", beans=1050.0, meal=300.0, oil=50.0)
        bad.loc[bad.leviathan_slug == "soybean_meal_cbot", "open_interest"] = pd.NA
        out = BC.compute_board_crush(pd.concat(
            [_session("2026-08-12", beans=1000.0, meal=310.0, oil=52.0), bad],
            ignore_index=True))
        assert list(out.trade_date) == ["2026-08-12"]
        assert "2026-08-13" not in set(out.trade_date)
        assert out.iloc[0]["meal_settle"] == pytest.approx(310.0)

    def test_a_missing_print_on_an_INELIGIBLE_candidate_does_not_refuse(self) -> None:
        # The contract is asked about the rows the rule READS. A delivery month
        # already under way is not one of them -- front_month drops it before it
        # ever looks at open interest -- so its absent print is not a defect in
        # the session, and refusing on it would cost dates for nothing.
        rows = []
        for slug, settle in (("soybeans_cbot", 1050.0), ("soybean_meal_cbot", 300.0),
                             ("soybean_oil_cbot", 50.0)):
            rows.append(_leg(slug, "2026-08-13", "2026-07", settle * 2, open_interest=None))
            rows.append(_leg(slug, "2026-08-13", "2026-11", settle, open_interest=9000.0))
        frame = pd.DataFrame(rows)
        frame["open_interest"] = frame["open_interest"].astype("object").where(
            frame["contract_month"] != "2026-07", pd.NA)
        out = BC.compute_board_crush(frame)
        assert len(out) == 1
        assert out.iloc[0]["beans_contract_month"] == "2026-11"
        assert out.iloc[0]["crush_margin_usd_bu"] == pytest.approx(1.60)

    def test_a_blank_string_print_counts_as_absent_exactly_as_NaN_does(self) -> None:
        # futures_roll's contract says '' and NaN are both ABSENT. The per-date
        # ask inherits that rather than re-deciding it.
        bad = _session("2026-08-13")
        bad["open_interest"] = bad["open_interest"].astype("object")
        bad.loc[bad.leviathan_slug == "soybean_oil_cbot", "open_interest"] = ""
        out = BC.compute_board_crush(
            pd.concat([_session("2026-08-12"), bad], ignore_index=True))
        assert list(out.trade_date) == ["2026-08-12"]

    def test_every_date_refused_still_emits_nothing(self) -> None:
        # The pre-2015-11-19 tape in miniature: no leg carries OI on any session,
        # so there is no date to compute and the zero-row fence in
        # jobs/batch/gold_board_crush_task.py is what the caller then hits.
        frames = []
        for d in ("2026-08-11", "2026-08-12", "2026-08-13"):
            s = _session(d)
            s["open_interest"] = pd.NA
            frames.append(s)
        out = BC.compute_board_crush(pd.concat(frames, ignore_index=True))
        assert out.empty
        assert list(out.columns) == BC.PHYSICAL_COLUMNS
        led = out.attrs[BC.REFUSED_DATES]
        assert led.readable == ()
        assert led.n_refused == 3
        assert led.refused == ("2026-08-11", "2026-08-12", "2026-08-13")


# ---------------------------------------------------------------------------
# The refusal is WRITTEN. An empty frame that cannot say why it is empty is the
# thing that cost this table its first fire.
# ---------------------------------------------------------------------------
class TestWrittenRefusal:

    def _mixed(self) -> pd.DataFrame:
        good = _session("2026-08-12")
        bad_oil = _session("2026-08-13")
        bad_oil.loc[bad_oil.leviathan_slug == "soybean_oil_cbot", "open_interest"] = pd.NA
        bad_two = _session("2026-08-17")
        bad_two.loc[bad_two.leviathan_slug.isin(
            ["soybean_oil_cbot", "soybeans_cbot"]), "open_interest"] = pd.NA
        return pd.concat([good, bad_oil, bad_two], ignore_index=True)

    def test_the_ledger_rides_out_on_the_frame(self) -> None:
        out = BC.compute_board_crush(self._mixed())
        assert BC.REFUSED_DATES in out.attrs
        assert isinstance(out.attrs[BC.REFUSED_DATES], BC.DateContractLedger)

    def test_readable_and_refused_partition_the_dates_exactly(self) -> None:
        led = BC.compute_board_crush(self._mixed()).attrs[BC.REFUSED_DATES]
        assert led.readable == ("2026-08-12",)
        assert led.refused == ("2026-08-13", "2026-08-17")
        assert set(led.readable) & set(led.refused) == set()
        assert led.n_dates == 3 == led.n_readable + led.n_refused

    def test_the_breakdown_names_the_leg_that_refused(self) -> None:
        led = BC.compute_board_crush(self._mixed()).attrs[BC.REFUSED_DATES]
        assert led.refused_by_role["oil"] == ("2026-08-13", "2026-08-17")
        assert led.refused_by_role["beans"] == ("2026-08-17",)
        assert led.refused_by_role["meal"] == ()

    def test_the_rendered_line_carries_count_breakdown_and_span(self) -> None:
        led = BC.compute_board_crush(self._mixed()).attrs[BC.REFUSED_DATES]
        line = led.render()
        assert "REFUSED 2 of 3 trade dates" in line
        assert "2026-08-13..2026-08-17" in line          # min .. max refused
        assert "oil(soybean_oil_cbot)=2" in line
        assert "beans(soybeans_cbot)=1" in line
        assert "meal(soybean_meal_cbot)=0" in line
        assert "readable 1 (2026-08-12..2026-08-12)" in line

    def test_the_written_refusal_is_ascii(self) -> None:
        # The Windows console is cp1252; a non-ASCII log line is an ops failure,
        # not a cosmetic one.
        led = BC.compute_board_crush(self._mixed()).attrs[BC.REFUSED_DATES]
        led.render().encode("ascii")

    def test_a_clean_run_still_accounts_for_every_date(self) -> None:
        led = BC.compute_board_crush(pd.concat(
            [_session("2026-08-12"), _session("2026-08-13")],
            ignore_index=True)).attrs[BC.REFUSED_DATES]
        assert led.n_refused == 0
        assert led.readable == ("2026-08-12", "2026-08-13")
        assert all(v == () for v in led.refused_by_role.values())

    def test_the_batch_task_reads_the_same_accounting_this_module_writes(self) -> None:
        # The seam: the job prints the ledger BEFORE its zero-row fence, so a run
        # that publishes nothing still says which dates it could not read.
        import inspect

        from jobs.batch import gold_board_crush_task as T

        assert T.REFUSED_DATES is BC.REFUSED_DATES
        src = inspect.getsource(T.main)
        assert "attrs.get(REFUSED_DATES)" in src
        assert src.index("ledger.render()") < src.index("computed ZERO rows")
        # ...and the ledger is a RUN RECORD, so it stays out of the published
        # parquet: pyarrow cannot JSON a dataclass into the pandas metadata block
        # and warns when asked to try.
        assert "body.attrs = {}" in src
        assert src.index("body.attrs = {}") < src.index("pq.write_table")

    def test_the_ledger_never_reaches_the_written_object(self) -> None:
        import io

        import pyarrow as pa
        import pyarrow.parquet as pq

        gold = BC.compute_board_crush(_session())
        body = gold[BC.PHYSICAL_COLUMNS].copy()
        body.attrs = {}
        buf = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("error")          # the pyarrow attrs warning is a failure
            pq.write_table(pa.Table.from_pandas(body, preserve_index=False), buf)
        assert BC.REFUSED_DATES in gold.attrs      # still on what the caller holds
        assert list(pq.read_table(io.BytesIO(buf.getvalue())).to_pandas().columns) == (
            BC.PHYSICAL_COLUMNS)


# ---------------------------------------------------------------------------
# is_roll_boundary (GN-2 W1.3): a contract step is marked, never narrated as a move.
# ---------------------------------------------------------------------------
class TestRollBoundary:

    def _four_sessions(self) -> pd.DataFrame:
        rows = []
        # two ordinary sessions, then BEANS rolls to 2027-01 while the products stay, then quiet again
        for d in ("2026-08-13", "2026-08-14"):
            rows += [_leg("soybeans_cbot", d, "2026-11", 1050.0),
                     _leg("soybean_meal_cbot", d, "2026-11", 300.0),
                     _leg("soybean_oil_cbot", d, "2026-11", 50.0)]
        for d in ("2026-08-17", "2026-08-18"):
            rows += [_leg("soybeans_cbot", d, "2027-01", 1060.0),
                     _leg("soybean_meal_cbot", d, "2026-11", 300.0),
                     _leg("soybean_oil_cbot", d, "2026-11", 50.0)]
        return pd.DataFrame(rows)

    def test_the_roll_session_is_marked_and_its_neighbours_are_not(self) -> None:
        gold = BC.compute_board_crush(self._four_sessions())
        assert list(gold["trade_date"]) == ["2026-08-13", "2026-08-14", "2026-08-17", "2026-08-18"]
        assert list(gold["is_roll_boundary"]) == ["0", "0", "1", "0"]

    def test_the_flag_is_a_string_not_a_bool_or_int(self) -> None:
        # build_sql's row_filters emit is a QUOTED literal with no cast: an INT column type-errors on
        # Athena and a bool diverges (str(True)='True' vs SQL 'true'). String is the one type all
        # three backends compare identically -- so the dtype IS the contract, not a formatting choice.
        gold = BC.compute_board_crush(self._four_sessions())
        assert all(isinstance(v, str) and v in ("0", "1") for v in gold["is_roll_boundary"])

    def test_first_emitted_session_is_not_a_boundary(self) -> None:
        gold = BC.compute_board_crush(_session())
        assert list(gold["is_roll_boundary"]) == ["0"]

    def test_the_level_still_emits_on_a_roll_session(self) -> None:
        # the boundary row stays IN the table (provenance); exclusion is the CARD's row_filters,
        # never the producer dropping a real settled number
        gold = BC.compute_board_crush(self._four_sessions())
        boundary = gold[gold["is_roll_boundary"] == "1"]
        assert len(boundary) == 1 and boundary["crush_margin_usd_bu"].notna().all()
