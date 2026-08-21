"""The COT bronze parser's JOIN IDENTITY (D-EC COT recovery, 2026-08-21).

The defect this file fences: the parser joined contracts to CFTC markets by exact NAME string, and
CFTC renames markets. The FCOJ keys matched ZERO raw rows in ANY era -- the raw name has been
"FRZN CONCENTRATED ORANGE JUICE - ICE FUTURES U.S." since 2006 -- so 1,049 weeks were silently
absent from silver, indistinguishable from no-data. The join is now keyed on
``CFTC_Contract_Market_Code``, which was measured stable across every rename (wheat 2013/14,
MGEX->MIAX, CANOLA OIL->CANOLA, the palm contract's display-name drift). These tests pin the
rename classes BY the historical names that actually appeared in the raw files, so a regression to
name-keying fails on the exact rows the defect lost.
"""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.transforms.raw_to_bronze import cftc_cot as m


def _row(name: str, code: str, date: str = "2010-03-02", oi: int = 1000,
         long_: int = 400, short: int = 150, spread: int = 50,
         futonly: str = "FutOnly") -> str:
    """One 191-field CSV data row with our 8 kept columns populated, everything else '0'."""
    fields = ["0"] * len(m._CANONICAL_COLUMNS)
    idx = {c: i for i, c in enumerate(m._CANONICAL_COLUMNS)}
    quoted = f'"{name}"' if "," in name else name
    fields[idx["Market_and_Exchange_Names"]] = quoted
    fields[idx["Report_Date_as_YYYY-MM-DD"]] = date
    fields[idx["CFTC_Contract_Market_Code"]] = code
    fields[idx["Open_Interest_All"]] = str(oi)
    fields[idx["M_Money_Positions_Long_All"]] = str(long_)
    fields[idx["M_Money_Positions_Short_All"]] = str(short)
    fields[idx["M_Money_Positions_Spread_All"]] = str(spread)
    fields[idx["FutOnly_or_Combined"]] = futonly
    return ",".join(fields)


def _file(rows: list[str], *, headered: bool = True) -> bytes:
    body = "\n".join(rows)
    if headered:
        return (m._CANONICAL_HEADER + "\n" + body).encode("utf-8")
    return body.encode("utf-8")


# ── the rename classes the name join LOST, pinned by the names the raw files actually carry ──────
def test_fcoj_resolves_under_the_name_the_old_map_never_matched():
    df = m.parse_cot_txt(_file([_row("FRZN CONCENTRATED ORANGE JUICE - ICE FUTURES U.S.",
                                     "040701")]), "t")
    assert df["leviathan_slug"].tolist() == ["frozen_orange_juice"]
    assert df["cftc_code"].tolist() == ["040701"]


def test_legacy_wheat_names_2006_2013_resolve_to_the_class_boards():
    rows = [_row("WHEAT - CHICAGO BOARD OF TRADE", "001602"),
            _row("WHEAT - KANSAS CITY BOARD OF TRADE", "001612"),
            _row("WHEAT - MINNEAPOLIS GRAIN EXCHANGE", "001626")]
    df = m.parse_cot_txt(_file(rows), "t")
    assert sorted(df["leviathan_slug"]) == ["hard_red_spring_wheat_mgex",
                                            "hard_red_winter_wheat_kcbt",
                                            "soft_red_winter_wheat_cbot"]


def test_every_rename_era_of_one_code_lands_on_one_slug():
    """001626 spans three names across the eras; the code is the identity, so all three rows land
    on hard_red_spring_wheat_mgex -- the property the re-key exists to hold."""
    rows = [_row("WHEAT - MINNEAPOLIS GRAIN EXCHANGE", "001626", date="2010-01-05"),
            _row("WHEAT-HRSpring - MINNEAPOLIS GRAIN EXCHANGE", "001626", date="2018-01-02"),
            _row("WHEAT-HRSpring - MIAX FUTURES EXCHANGE", "001626", date="2026-01-06")]
    df = m.parse_cot_txt(_file(rows), "t")
    assert df["leviathan_slug"].unique().tolist() == ["hard_red_spring_wheat_mgex"]
    assert len(df) == 3


def test_canola_and_palm_the_never_mapped_pair_now_resolve():
    rows = [_row("CANOLA - ICE FUTURES U.S.", "135731"),
            _row("CANOLA OIL - ICE FUTURES U.S.", "135731"),
            _row("USD Malaysian Crude Palm Oil C - CHICAGO MERCANTILE EXCHANGE", "037021")]
    df = m.parse_cot_txt(_file(rows), "t")
    assert sorted(df["leviathan_slug"]) == ["canola_ice", "canola_ice",
                                            "malaysian_crude_palm_oil_cme"]


# ── the near-miss traps, measured in the raw and deliberately unmapped ──────────────────────────
def test_mini_contracts_black_sea_and_the_palm_swap_stay_excluded():
    rows = [_row("MINI CORN - CHICAGO BOARD OF TRADE", "002603"),
            _row("MINI SOYBEANS - CHICAGO BOARD OF TRADE", "005603"),
            _row("BLACK SEA WHEAT FINANCIAL - CHICAGO BOARD OF TRADE", "00160F"),
            _row("MALAYSIAN PALM OIL CALENDAR SW - CHICAGO MERCANTILE EXCHANGE", "037642"),
            _row("CORN - CHICAGO BOARD OF TRADE", "002602")]
    df = m.parse_cot_txt(_file(rows), "t")
    assert df["leviathan_slug"].tolist() == ["corn_cbot"]


# ── the mechanics the re-key must not disturb ───────────────────────────────────────────────────
def test_derived_columns_and_schema_survive_the_rekey():
    df = m.parse_cot_txt(_file([_row("CORN - CHICAGO BOARD OF TRADE", "002602",
                                     oi=2000, long_=700, short=200, spread=100)]), "t")
    assert list(df.columns) == m.BRONZE_COLUMNS
    r = df.iloc[0]
    assert r["mm_net"] == 500 and r["mm_pct_oi"] == pytest.approx(25.0)
    assert r["market_name"] == "CORN - CHICAGO BOARD OF TRADE"        # name still carried, not joined on


def test_headerless_weekly_variant_still_parses_by_code():
    df = m.parse_cot_txt(_file([_row("FRZN CONCENTRATED ORANGE JUICE - ICE FUTURES U.S.",
                                     "040701")], headered=False), "t")
    assert df["leviathan_slug"].tolist() == ["frozen_orange_juice"]


def test_combined_rows_are_still_dropped():
    rows = [_row("CORN - CHICAGO BOARD OF TRADE", "002602", futonly="Combined")]
    assert m.parse_cot_txt(_file(rows), "t").empty


def test_the_rename_tripwire_logs_but_never_drops(caplog):
    """A mapped code under an unseen name is tomorrow's rename: the row must LAND (code-keyed) and
    the log must SAY so -- visible, never silent, never fatal."""
    import logging
    with caplog.at_level(logging.INFO):
        df = m.parse_cot_txt(_file([_row("FCOJ TOTALLY RENAMED AGAIN - ICE", "040701")]), "t")
    assert df["leviathan_slug"].tolist() == ["frozen_orange_juice"]
    assert any("NEW market name" in r.message for r in caplog.records)


def test_every_mapped_slug_is_a_real_contract_and_the_map_is_injective_by_intent():
    from typing import get_args

    from leviathan.common.types import CommodityName
    valid = set(get_args(CommodityName))
    assert set(m._CODE_TO_SLUG.values()) <= valid
    assert len(m._CODE_TO_SLUG) == 15                     # 12 previously live + FCOJ + canola + palm
    # and the map is a bijection: each board has exactly one CFTC code (renames move NAMES, never
    # codes), so a second code appearing for a mapped slug is a curation event, not a merge.
    assert len(set(m._CODE_TO_SLUG.values())) == 15
