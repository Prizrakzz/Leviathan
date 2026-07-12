"""SILVER-F024: orphan EAV <-> canonical wide reconciliation for CONAB coffee."""
from __future__ import annotations

import pandas as pd

from leviathan.silver.conab_reconcile import (
    CANONICAL_METRICS,
    canonical_to_eav,
    reconcile_conab_eav,
)


def _wide_row(commodity, safra, survey, region, area, yld, prod):
    return {
        "commodity": commodity, "safra_year": safra, "survey_number": survey, "region": region,
        "area_in_production_ha": area, "yield_bags_per_ha": yld, "production_thousand_bags": prod,
    }


def _canonical():
    return pd.DataFrame([
        _wide_row("arabica_coffee", 2025, 1, "minas_gerais", 10.0, 20.0, 1000.0),
        _wide_row("arabica_coffee", 2025, 2, "minas_gerais", 11.0, 21.0, 1125.0),
    ])


def _eav_from_wide(wide: pd.DataFrame) -> pd.DataFrame:
    return canonical_to_eav(wide)


def test_identical_orphan_reconciles_with_zero_unexplained():
    wide = _canonical()
    orphan = _eav_from_wide(wide)
    report = reconcile_conab_eav(orphan, wide)
    assert report.reconciled
    assert report.unexplained_difference_count == 0
    assert report.matched == len(orphan)   # every EAV cell matched


def test_value_mismatch_is_unexplained():
    wide = _canonical()
    orphan = _eav_from_wide(wide)
    orphan.loc[orphan["metric"] == "production_thousand_bags", "value"] = 999.0
    report = reconcile_conab_eav(orphan, wide)
    assert not report.reconciled
    assert len(report.value_mismatch) == 2   # two production cells differ


def test_orphan_only_and_canonical_only_counted():
    wide = _canonical()
    orphan = _eav_from_wide(wide)
    # drop one canonical cell from orphan (canonical_only) + add a stray orphan cell (orphan_only).
    orphan = orphan[~((orphan["survey_number"] == 2) & (orphan["metric"] == "yield_bags_per_ha"))]
    stray = pd.DataFrame([{
        "commodity": "arabica_coffee", "safra_year": 2025, "survey_number": 9,
        "region": "sao_paulo", "metric": "production_thousand_bags", "value": 5.0,
    }])
    orphan = pd.concat([orphan, stray], ignore_index=True)
    report = reconcile_conab_eav(orphan, wide)
    assert len(report.canonical_only) == 1
    assert len(report.orphan_only) == 1
    assert not report.reconciled


def test_approved_exception_ledger_suppresses_difference():
    wide = _canonical()
    orphan = _eav_from_wide(wide)
    orphan.loc[orphan["metric"] == "production_thousand_bags", "value"] = 999.0
    exc = [
        ("arabica_coffee", 2025, 1, "minas_gerais", "production_thousand_bags"),
        ("arabica_coffee", 2025, 2, "minas_gerais", "production_thousand_bags"),
    ]
    report = reconcile_conab_eav(orphan, wide, exceptions=exc)
    assert report.reconciled                 # both diffs are approved exceptions
    assert report.exceptions_applied == 2


def test_float_tolerance():
    wide = _canonical()
    orphan = _eav_from_wide(wide)
    orphan["value"] = orphan["value"] + 1e-9   # sub-tolerance noise
    assert reconcile_conab_eav(orphan, wide, tol=1e-6).reconciled


def test_canonical_to_eav_drops_nulls_and_covers_metrics():
    wide = _canonical()
    wide.loc[0, "area_in_production_ha"] = None
    eav = canonical_to_eav(wide)
    assert set(eav["metric"].unique()) <= set(CANONICAL_METRICS)
    assert eav["value"].notna().all()
