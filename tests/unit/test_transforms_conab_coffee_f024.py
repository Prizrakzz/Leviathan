"""SILVER-F024: CONAB coffee revision/provenance algorithms (OP-4 close) + the WIRING_WAVE1 additive
survey_release_date vintage anchor (23-column contract)."""
from __future__ import annotations

import pandas as pd
import pytest
from leviathan.transforms.bronze_to_silver.conab_coffee import (
    OUTPUT_COLUMNS,
    PARSER_VERSION,
    _survey_release_date,
    transform_conab_coffee_bronze_to_silver,
)


def _rows(safra, survey, sheet, region, area, yld, prod, extra=None):
    out = []
    for elem, val in [
        ("area_in_production_ha", area),
        ("yield_bags_per_ha", yld),
        ("production_thousand_bags", prod),
    ]:
        row = {"safra_year": safra, "survey": survey, "sheet_name": sheet,
               "region": region, "element": elem, "value": val, "unit": "u"}
        if extra:
            row.update(extra)
        out.append(row)
    return out


def _run(rows) -> pd.DataFrame:
    return transform_conab_coffee_bronze_to_silver(pd.DataFrame(rows))


def test_exactly_23_columns_in_contract_order():
    df = _run(_rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000))
    assert list(df.columns) == OUTPUT_COLUMNS
    assert len(df.columns) == 23
    assert OUTPUT_COLUMNS[-1] == "survey_release_date"   # additive tail


def test_survey_release_date_conservative_never_leak_calendar():
    """Each survey_number maps to the fixed conservative first-of-month stamp; the derived date is
    ALWAYS on/after the real (mid-month) CONAB release, so the vintage guard never leaks."""
    assert _survey_release_date(2024, 1) == "2024-03-01"   # S1 real: Jan-Feb 2024
    assert _survey_release_date(2024, 2) == "2024-06-01"   # S2 real: ~May 23 2024
    assert _survey_release_date(2024, 3) == "2024-10-01"   # S3 real: ~Sep 19 2024
    assert _survey_release_date(2024, 4) == "2025-02-01"   # S4 real: Jan 21 2025 (NEXT year)


def test_survey_release_date_is_strictly_increasing_in_survey_number():
    """knowledge_date DESC and survey_number DESC must agree -- a later survey always carries a later
    derived release (within a safra), so the vintage tiebreak is deterministic."""
    for safra in (2023, 2024, 2025, 2026):
        stamps = [_survey_release_date(safra, s) for s in (1, 2, 3, 4)]
        assert stamps == sorted(stamps)
        assert len(set(stamps)) == 4


def test_survey_release_date_populated_on_every_row():
    df = _run(
        _rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000)
        + _rows(2025, 2, "2 Cafe Arabica", "MG", 12, 25, 1200)
    )
    assert df["survey_release_date"].notna().all()
    s1 = df[df["survey_number"] == 1].iloc[0]
    s2 = df[df["survey_number"] == 2].iloc[0]
    assert s1["survey_release_date"] == "2025-03-01"
    assert s2["survey_release_date"] == "2025-06-01"


def test_survey_release_date_raises_outside_fixed_1_to_4_calendar():
    for bad in (0, 5, 9):
        with pytest.raises(ValueError, match="outside the fixed 1..4 survey"):
            _survey_release_date(2025, bad)


def test_revision_deltas_and_pct():
    df = _run(
        _rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000)
        + _rows(2025, 2, "2 Cafe Arabica", "MG", 12, 25, 1200)
    )
    s2 = df[df["survey_number"] == 2].iloc[0]
    assert s2["production_revision_thousand_bags"] == pytest.approx(200.0)
    assert s2["area_revision_ha"] == pytest.approx(2.0)
    assert s2["yield_revision_bags_per_ha"] == pytest.approx(5.0)
    assert s2["production_revision_pct"] == pytest.approx(20.0)   # 200 / 1000 * 100


def test_first_survey_has_null_revision_and_zero_streak():
    df = _run(_rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000))
    r = df.iloc[0]
    assert pd.isna(r["production_revision_thousand_bags"])
    assert pd.isna(r["production_revision_pct"])
    assert r["production_revision_streak"] == 0


def test_zero_prior_production_gives_null_pct_not_inf():
    df = _run(
        _rows(2025, 1, "2 Cafe Arabica", "MG", 0, 0, 0)
        + _rows(2025, 2, "2 Cafe Arabica", "MG", 1, 1, 50)
    )
    s2 = df[df["survey_number"] == 2].iloc[0]
    assert s2["production_revision_thousand_bags"] == pytest.approx(50.0)
    assert pd.isna(s2["production_revision_pct"])   # divide-by-zero -> null, never inf


def test_streak_runs_and_resets_on_sign_flip():
    rows = (
        _rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000)
        + _rows(2025, 2, "2 Cafe Arabica", "MG", 10, 20, 1100)   # +100 streak 1
        + _rows(2025, 3, "2 Cafe Arabica", "MG", 10, 20, 1150)   # +50  streak 2
        + _rows(2025, 4, "2 Cafe Arabica", "MG", 10, 20, 1050)   # -100 streak 1 (flip)
    )
    df = _run(rows).sort_values("survey_number")
    streaks = list(df["production_revision_streak"])
    assert streaks == [0, 1, 2, 1]


def test_repeated_survey_detected_by_content_fingerprint():
    rows = (
        _rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000)
        + _rows(2025, 2, "2 Cafe Arabica", "MG", 11, 21, 1100)
        + _rows(2025, 3, "2 Cafe Arabica", "MG", 11, 21, 1100)   # identical content to survey 2
    )
    df = _run(rows).sort_values("survey_number").reset_index(drop=True)
    assert not bool(df.loc[1, "is_repeated_survey"])
    assert bool(df.loc[2, "is_repeated_survey"])
    assert df.loc[2, "repeated_from_survey_number"] == 2
    assert df.loc[1, "survey_content_fingerprint"] == df.loc[2, "survey_content_fingerprint"]
    assert df.loc[0, "survey_content_fingerprint"] != df.loc[1, "survey_content_fingerprint"]


def test_fingerprint_is_order_independent():
    a = _run(
        _rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000)
        + _rows(2025, 1, "2 Cafe Arabica", "SP", 5, 15, 500)
    )
    b = _run(
        _rows(2025, 1, "2 Cafe Arabica", "SP", 5, 15, 500)
        + _rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000)
    )
    assert set(a["survey_content_fingerprint"]) == set(b["survey_content_fingerprint"])


def test_provenance_carried_from_bronze():
    extra = {"source_raw_key": "raw/.../s01.xls", "source_file_etag": "etag123"}
    df = _run(_rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000, extra=extra))
    r = df.iloc[0]
    assert r["worksheet"] == "2 Cafe Arabica"
    assert r["region_raw"] == "MG"
    assert r["source_raw_key"] == "raw/.../s01.xls"
    assert r["source_file_etag"] == "etag123"
    assert r["parser_version"] == PARSER_VERSION


def test_absent_provenance_defaults_null():
    df = _run(_rows(2025, 1, "2 Cafe Arabica", "MG", 10, 20, 1000))
    r = df.iloc[0]
    assert pd.isna(r["source_raw_key"])
    assert pd.isna(r["source_file_etag"])


def test_conflicting_duplicate_metric_raises():
    rows = [
        {"safra_year": 2025, "survey": 1, "sheet_name": "2 Cafe Arabica", "region": "MG",
         "element": "production_thousand_bags", "value": 1000.0, "unit": "u"},
        {"safra_year": 2025, "survey": 1, "sheet_name": "2 Cafe Arabica", "region": "MG",
         "element": "production_thousand_bags", "value": 1001.0, "unit": "u"},
    ]
    with pytest.raises(ValueError, match="conflicting duplicate metrics"):
        _run(rows)
