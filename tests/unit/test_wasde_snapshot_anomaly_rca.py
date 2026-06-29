from __future__ import annotations

import pandas as pd

from leviathan.model_datasets.wasde_snapshot_anomaly_rca import (
    build_annual_alert_cases,
    build_false_case_tables,
)


def _prediction(
    *,
    year: int,
    event: bool,
    alert: bool,
    detector: str = "composite_balance_sheet_stress",
) -> dict[str, object]:
    return {
        "dataset_key": "corn_wasde_snapshot_solo",
        "contract_key": "corn_cbot",
        "origin_key": "united_states",
        "target_market_year": year,
        "target_key": "psd_stock_to_use_anomaly_pct",
        "as_of_date": f"{year}-08-12",
        "snapshot_stage": "early_season",
        "detector_id": detector,
        "fold_id": 0,
        "threshold": 0.5,
        "score_value": 0.9 if alert else 0.1,
        "alert": alert,
        "target_event_label": event,
        "target_value": -0.2 if event else 0.1,
        "sample_weight": 1.0,
    }


def test_false_negative_case_table_contains_required_columns() -> None:
    predictions = pd.DataFrame([
        _prediction(year=2000, event=True, alert=False),
        _prediction(year=2001, event=False, alert=True),
    ])
    annual = build_annual_alert_cases(predictions)
    false_negatives, _ = build_false_case_tables(annual)

    assert len(false_negatives) == 1
    assert false_negatives.iloc[0]["case_type"] == "false_negative"
    assert false_negatives.iloc[0]["rca_reason_code"] == "event_without_any_alert"


def test_false_positive_case_table_contains_required_columns() -> None:
    predictions = pd.DataFrame([
        _prediction(year=2000, event=True, alert=False),
        _prediction(year=2001, event=False, alert=True),
    ])
    annual = build_annual_alert_cases(predictions)
    _, false_positives = build_false_case_tables(annual)

    assert len(false_positives) == 1
    assert false_positives.iloc[0]["case_type"] == "false_positive"
    assert false_positives.iloc[0]["rca_reason_code"] == "alert_without_final_event"


def test_rca_reason_codes_are_valid() -> None:
    predictions = pd.DataFrame([
        _prediction(year=2000, event=True, alert=False),
        _prediction(year=2001, event=False, alert=True),
    ])
    annual = build_annual_alert_cases(predictions)
    false_negatives, false_positives = build_false_case_tables(annual)

    reasons = set(false_negatives["rca_reason_code"]) | set(false_positives["rca_reason_code"])
    assert reasons == {"event_without_any_alert", "alert_without_final_event"}
