"""PRICE_AND_PLAYBOOKS W2 / D8 -- the named, versioned front-month rule. Pure/hermetic.

Covers the rule itself AND the F-L fence: gate 7, W3.3 and the W2b straddle rule must all import
this module, and ``config_check.check_futures_roll`` must FAIL if a second implementation appears.
"""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.graphrag import config_check as cc
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver import futures_roll as FR


def _rows(slug, trade_date, months, *, oi=None, vol=None, settle=None):
    n = len(months)
    return pd.DataFrame({
        "leviathan_slug": [slug] * n,
        "trade_date": [pd.Timestamp(trade_date)] * n,
        "contract_month": list(months),
        "raw_symbol": [f"{slug[:2].upper()}{i}" for i in range(n)],
        "settle": settle if settle is not None else [100.0 + i for i in range(n)],
        "close": settle if settle is not None else [100.0 + i for i in range(n)],
        "volume": vol if vol is not None else [None] * n,
        "open_interest": oi if oi is not None else [None] * n,
        "instrument_kind": ["futures"] * n,
        "unit": [FC.CONTRACT_MAP[slug]["unit"]] * n,
        "currency": [FC.CONTRACT_MAP[slug]["currency"]] * n,
        "settle_kind": [FC.CONTRACT_MAP[slug]["settle_kind"]] * n,
        "source": [FC.CONTRACT_MAP[slug]["source"]] * n,
    })


class TestRuleTables:
    def test_version_is_pinned(self):
        assert FR.ROLL_RULE_VERSION == "front_month_v1"

    def test_lint_is_clean(self):
        assert FR.lint_roll_rule() == []

    def test_every_source_declares_a_method(self):
        assert set(FR.ROLL_METHOD_BY_SOURCE) == set(FC.SOURCES)

    def test_the_plan_s_four_buckets(self):
        assert FR.roll_method_for("corn_cbot") == FR.METHOD_OPEN_INTEREST      # GLBX statistics
        assert FR.roll_method_for("rapeseed_meal_zce") == FR.METHOD_OPEN_INTEREST
        assert FR.roll_method_for("south_african_white_maize_jse") == FR.METHOD_OPEN_INTEREST
        assert FR.roll_method_for("arabica_coffee") == FR.METHOD_VOLUME        # ICE: no OI at all
        assert FR.roll_method_for("robusta_coffee") == FR.METHOD_VOLUME
        assert FR.roll_method_for("french_wheat_matif") == FR.METHOD_DELIVERY_CYCLE
        assert FR.roll_method_for("brazilian_arabica_coffee") == FR.METHOD_NONE

    def test_cash_references_never_roll(self):
        for slug in FC.CASH_INDEX_SLUGS:
            assert FR.roll_method_for(slug) == FR.METHOD_NONE
        rolling = {s for s in FC.CONTRACT_MAP if FR.roll_method_for(s) == FR.METHOD_NONE}
        assert rolling == set(FC.CASH_INDEX_SLUGS)

    def test_unmapped_slug_fails_closed(self):
        with pytest.raises(ValueError):
            FR.roll_method_for("not_a_contract")

    def test_delivery_cycles_cover_exactly_the_cycle_slugs(self):
        want = {s for s in FC.CONTRACT_MAP if FR.roll_method_for(s) == FR.METHOD_DELIVERY_CYCLE}
        assert set(FR.DELIVERY_CYCLES) == want

    def test_lint_fires_when_a_source_loses_its_method(self, monkeypatch):
        broken = dict(FR.ROLL_METHOD_BY_SOURCE)
        broken.pop("czce")
        monkeypatch.setattr(FR, "ROLL_METHOD_BY_SOURCE", broken)
        errs = FR.lint_roll_rule()
        assert any("have NO front-month method" in e for e in errs)

    def test_lint_fires_when_a_cash_reference_acquires_a_roll(self, monkeypatch):
        broken = dict(FR.ROLL_METHOD_BY_SOURCE)
        broken["cepea"] = FR.METHOD_VOLUME
        monkeypatch.setattr(FR, "ROLL_METHOD_BY_SOURCE", broken)
        assert any("must never roll" in e for e in FR.lint_roll_rule())

    def test_lint_fires_on_a_delivery_cycle_slug_with_no_cycle(self, monkeypatch):
        monkeypatch.setattr(FR, "DELIVERY_CYCLES",
                            {k: v for k, v in FR.DELIVERY_CYCLES.items()
                             if k != "french_wheat_matif"})
        assert any("no curated DELIVERY_CYCLES entry" in e for e in FR.lint_roll_rule())

    def test_lint_fires_on_a_bad_month_number(self, monkeypatch):
        monkeypatch.setattr(FR, "DELIVERY_CYCLES", {**FR.DELIVERY_CYCLES,
                                                    "french_wheat_matif": (3, 5, 9, 13)})
        assert any("non-month value" in e for e in FR.lint_roll_rule())


class TestFrontMonth:
    def test_front_by_open_interest(self):
        df = _rows("corn_cbot", "2026-03-10", ["2026-05", "2026-07", "2026-09"],
                   oi=[10, 900, 50], vol=[5000, 1, 1])
        got = FR.front_month(df)
        assert len(got) == 1
        assert got["contract_month"].iloc[0] == "2026-07"      # OI wins, not volume
        assert got["roll_method"].iloc[0] == FR.METHOD_OPEN_INTEREST
        assert got["roll_rule_version"].iloc[0] == FR.ROLL_RULE_VERSION

    def test_front_by_volume_where_there_is_no_oi(self):
        df = _rows("arabica_coffee", "2026-03-10", ["2026-05", "2026-07", "2026-09"],
                   vol=[10, 900, 50])
        got = FR.front_month(df)
        assert got["contract_month"].iloc[0] == "2026-07"
        assert got["roll_method"].iloc[0] == FR.METHOD_VOLUME

    def test_open_interest_is_ignored_on_a_volume_slug(self):
        # An OI column that leaked in from somewhere must not silently take over the ICE rule.
        df = _rows("arabica_coffee", "2026-03-10", ["2026-05", "2026-07"],
                   vol=[900, 10], oi=[1, 9999])
        assert FR.front_month(df)["contract_month"].iloc[0] == "2026-05"

    def test_delivery_cycle_picks_the_nearest_listed_month(self):
        df = _rows("french_wheat_matif", "2026-03-10",
                   ["2026-04", "2026-05", "2026-09", "2026-12"])
        got = FR.front_month(df)
        # April is NOT in the MATIF wheat cycle (3, 5, 9, 12) -- May is the front.
        assert got["contract_month"].iloc[0] == "2026-05"

    def test_expired_months_are_not_eligible(self):
        df = _rows("corn_cbot", "2026-06-10", ["2026-03", "2026-07"], oi=[9999, 1])
        # The March contract has the highest OI but is in the past -- a stale print must not keep
        # it "front" forever.
        assert FR.front_month(df)["contract_month"].iloc[0] == "2026-07"

    def test_cash_index_rows_are_dropped_not_passed_through(self):
        df = _rows("corn_cbot", "2026-03-10", ["2026-05"], oi=[10])
        cash = df.copy()
        cash["leviathan_slug"] = "brazilian_arabica_coffee"
        cash["instrument_kind"] = "cash_index"
        cash["settle_kind"] = "cash_index"
        got = FR.front_month(pd.concat([df, cash], ignore_index=True))
        assert set(got["leviathan_slug"]) == {"corn_cbot"}

    def test_ties_break_on_the_nearest_month_deterministically(self):
        df = _rows("corn_cbot", "2026-03-10", ["2026-09", "2026-05", "2026-07"],
                   oi=[100, 100, 100])
        assert FR.front_month(df)["contract_month"].iloc[0] == "2026-05"
        # and the reverse input order gives the same answer
        assert FR.front_month(df.iloc[::-1])["contract_month"].iloc[0] == "2026-05"

    def test_missing_metric_never_outranks_a_real_one(self):
        df = _rows("corn_cbot", "2026-03-10", ["2026-05", "2026-07"], oi=[None, 3])
        assert FR.front_month(df)["contract_month"].iloc[0] == "2026-07"

    def test_one_row_per_slug_per_date(self):
        a = _rows("corn_cbot", "2026-03-10", ["2026-05", "2026-07"], oi=[1, 2])
        b = _rows("corn_cbot", "2026-03-11", ["2026-05", "2026-07"], oi=[9, 2])
        got = FR.front_month(pd.concat([a, b], ignore_index=True))
        assert len(got) == 2
        assert got["contract_month"].tolist() == ["2026-07", "2026-05"]

    def test_empty_frame(self):
        assert FR.front_month(pd.DataFrame()).empty

    def test_a_foreign_version_is_refused(self):
        with pytest.raises(ValueError, match="roll_rule_version"):
            FR.front_month(_rows("corn_cbot", "2026-03-10", ["2026-05"], oi=[1]),
                           rule_version="front_month_v0")


class TestFLFence:
    """F-L's stated failure mode is THREE inline copies. The lint is the thing that prevents it."""

    def test_check_futures_roll_is_clean(self):
        assert cc.check_futures_roll() == []

    def test_check_futures_roll_is_wired_into_main(self):
        import inspect
        assert "check_futures_roll()" in inspect.getsource(cc.main)

    def test_the_fence_fires_on_a_second_implementation(self, tmp_path, monkeypatch):
        repo = tmp_path
        (repo / "src" / "leviathan" / "silver").mkdir(parents=True)
        owner = repo / "src" / "leviathan" / "silver" / "futures_roll.py"
        owner.write_text("ROLL_RULE_VERSION = 'x'\n", encoding="utf-8")
        (repo / "jobs").mkdir()
        (repo / "jobs" / "sneaky_task.py").write_text(
            "def front_month(df):\n    return df.sort_values('open_interest').head(1)\n",
            encoding="utf-8")
        monkeypatch.setattr(cc, "_REPO", repo)
        errs = cc.check_futures_roll()
        assert any("jobs/sneaky_task.py" in e and "def front_month(" in e for e in errs)

    def test_the_fence_fires_when_the_owner_disappears(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cc, "_REPO", tmp_path)
        assert any("rule owner" in e and "MISSING" in e for e in cc.check_futures_roll())

    def test_the_gate_imports_the_rule_rather_than_re_deriving_it(self):
        from pathlib import Path
        gate = (Path(__file__).resolve().parents[2] / "scripts" / "silver" / "futures_eod_gate.py")
        text = gate.read_text(encoding="utf-8")
        assert "from leviathan.silver import futures_roll as FR" in text
        # AMENDED 2026-07-29: the parity gate now emulates the RETIRING lane's own selection
        # (measured: yfinance rolls by volume and prints settlements; front-by-volume x settle
        # reproduced it exactly, front-by-OI sits ~2.1% away as a calendar spread). The fence's
        # intent is unchanged -- the selection lives in the roll MODULE, never re-derived inline.
        assert "FR.legacy_lane_front(" in text
        for tok in cc._ROLL_RULE_FORBIDDEN_TOKENS:
            assert tok not in text
