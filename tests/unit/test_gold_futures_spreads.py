"""GN-2 W2.3 -- the two-leg spread table, pinned as a definition (the gold_board_crush discipline).

The failure mode is UNITS and ROLLS, not availability: a spread across units is a number wearing the
wrong label, and a window straddling a roll narrates a contract change as a market move. Pure Python.
"""
from __future__ import annotations

import pandas as pd
import pytest

import leviathan.transforms.gold.futures_spreads as FS
from leviathan.silver import futures_eod_contracts as FC


def _leg(slug: str, trade_date: str, contract_month: str, settle: float,
         *, open_interest: float = 1000.0) -> dict:
    return {
        "leviathan_slug": slug, "trade_date": trade_date, "contract_month": contract_month,
        "settle": settle, "settle_kind": "settlement", "unit": FC.CONTRACT_MAP[slug]["unit"],
        "open_interest": open_interest, "volume": 500.0, "instrument_kind": "futures",
        "source": FC.CONTRACT_MAP[slug]["source"],
    }


def _kc_chi_session(d: str, kc: float, chi: float, month: str = "2026-12") -> list[dict]:
    return [_leg("hard_red_winter_wheat_kcbt", d, month, kc),
            _leg("soft_red_winter_wheat_cbot", d, month, chi)]


class TestSpreadArithmetic:
    def test_the_worked_example(self) -> None:
        gold = FS.compute_futures_spreads(pd.DataFrame(_kc_chi_session("2026-08-13", 650.0, 545.5)))
        row = gold[gold.spread_id == "kc_chi"].iloc[0]
        assert row["spread_value"] == pytest.approx(104.5)      # KC premium over Chicago
        assert row["unit"] == "US cents/bushel"
        assert row["long_slug"] == "hard_red_winter_wheat_kcbt"

    def test_a_negative_spread_is_a_real_reading(self) -> None:
        gold = FS.compute_futures_spreads(pd.DataFrame(_kc_chi_session("2026-08-13", 500.0, 545.5)))
        assert gold.iloc[0]["spread_value"] == pytest.approx(-45.5)   # KC under Chicago: real, kept

    def test_columns_are_the_declared_contract(self) -> None:
        gold = FS.compute_futures_spreads(pd.DataFrame(_kc_chi_session("2026-08-13", 650.0, 545.5)))
        assert list(gold.columns) == FS.PHYSICAL_COLUMNS


class TestSameUnitLaw:
    def test_every_registry_pair_is_same_unit_and_currency_today(self) -> None:
        for sid, (a, b) in FS.SPREADS.items():
            assert FS._assert_same_unit(sid, a, b)              # raises on drift

    def test_a_requoted_leg_refuses(self, monkeypatch) -> None:
        bad = dict(FC.CONTRACT_MAP["soft_red_winter_wheat_cbot"])
        bad["unit"] = "USD/bushel"
        monkeypatch.setitem(FC.CONTRACT_MAP, "soft_red_winter_wheat_cbot", bad)
        with pytest.raises(ValueError, match="same-unit law"):
            FS.compute_futures_spreads(pd.DataFrame(_kc_chi_session("2026-08-13", 650.0, 545.5)))


class TestTwoLegRule:
    def test_a_session_missing_one_leg_is_dropped(self) -> None:
        rows = _kc_chi_session("2026-08-13", 650.0, 545.5) + [
            _leg("hard_red_winter_wheat_kcbt", "2026-08-14", "2026-12", 655.0)]   # KC only
        gold = FS.compute_futures_spreads(pd.DataFrame(rows))
        assert list(gold["trade_date"]) == ["2026-08-13"]

    def test_one_pairs_outage_never_silences_another(self) -> None:
        gold = FS.compute_futures_spreads(pd.DataFrame(_kc_chi_session("2026-08-13", 650.0, 545.5)))
        assert set(gold["spread_id"]) == {"kc_chi"}             # white_yellow absent -> kc_chi still emits
        assert gold.attrs[FS.REFUSED_DATES]["white_yellow"].readable == ()

    def test_missing_open_interest_refuses_the_date_and_writes_it(self) -> None:
        rows = _kc_chi_session("2026-08-13", 650.0, 545.5)
        rows += [_leg("hard_red_winter_wheat_kcbt", "2026-08-14", "2026-12", 655.0,
                      open_interest=float("nan")),
                 _leg("soft_red_winter_wheat_cbot", "2026-08-14", "2026-12", 546.0)]
        gold = FS.compute_futures_spreads(pd.DataFrame(rows))
        assert list(gold["trade_date"]) == ["2026-08-13"]
        led = gold.attrs[FS.REFUSED_DATES]["kc_chi"]
        assert "2026-08-14" in led.refused


class TestRollBoundary:
    def test_the_roll_session_is_marked_string_zero_one(self) -> None:
        rows = (_kc_chi_session("2026-08-13", 650.0, 545.5) +
                _kc_chi_session("2026-08-14", 651.0, 546.0) +
                [_leg("hard_red_winter_wheat_kcbt", "2026-08-17", "2027-03", 660.0),
                 _leg("soft_red_winter_wheat_cbot", "2026-08-17", "2026-12", 547.0)] +
                [_leg("hard_red_winter_wheat_kcbt", "2026-08-18", "2027-03", 661.0),
                 _leg("soft_red_winter_wheat_cbot", "2026-08-18", "2026-12", 548.0)])
        gold = FS.compute_futures_spreads(pd.DataFrame(rows))
        assert list(gold["is_roll_boundary"]) == ["0", "0", "1", "0"]
        assert all(isinstance(v, str) for v in gold["is_roll_boundary"])


# -- THE BUCKET ENV NAME (2026-09-25): main() reads LEVIATHAN_BUCKET, the name every jobdef sets ---------------
# Both scheduled fires since 2026-09-24 died on get_required_env("S3_BUCKET") -- a name no job definition carries
# (infra/terraform/modules/batch/main.tf sets LEVIATHAN_BUCKET on every jobdef; 20+ sibling tasks read it). The pin
# drives main() in --dry-run with the S3 read stubbed and proves (a) the leg reader is handed the LEVIATHAN_BUCKET
# value and (b) with only S3_BUCKET in the environment main() refuses by naming the name it needs.


def _env_only(monkeypatch, name, value):
    import jobs.batch.gold_futures_spreads_task as T
    monkeypatch.setattr(T, "load_env", lambda: None)          # never the developer .env
    for k in ("S3_BUCKET", "LEVIATHAN_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(name, value)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    return T


def test_main_reads_the_estates_bucket_name_and_hands_it_to_the_leg_reader(monkeypatch):
    T = _env_only(monkeypatch, "LEVIATHAN_BUCKET", "bucket-under-test")
    seen = []

    def _leg(bucket, slug, region):
        seen.append((bucket, slug, region))
        return pd.DataFrame(columns=T.INPUT_COLUMNS)

    monkeypatch.setattr(T, "_read_leg", _leg)
    rc = T.main(["--dry-run", "true"])
    assert rc == 3                                   # empty legs -> the task's own written refusal, nothing written
    assert seen and all(b == "bucket-under-test" for b, _s, _r in seen)
    assert all(r == "us-east-1" for _b, _s, r in seen)


def test_main_refuses_by_name_when_only_the_retired_name_is_set(monkeypatch):
    T = _env_only(monkeypatch, "S3_BUCKET", "bucket-under-test")
    monkeypatch.setattr(T, "_read_leg", lambda *a: pytest.fail("the leg must not be read without a bucket"))
    with pytest.raises(RuntimeError, match="LEVIATHAN_BUCKET"):
        T.main(["--dry-run", "true"])
