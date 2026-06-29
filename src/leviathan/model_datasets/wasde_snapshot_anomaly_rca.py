"""False-case RCA tables for WASDE snapshot anomaly evaluation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from leviathan.model_datasets.wasde_snapshot_targets import GROUP_KEY as TARGET_GROUP_KEY

FALSE_CASE_COLUMNS = [
    *TARGET_GROUP_KEY,
    "detector_id",
    "case_type",
    "target_event_label",
    "any_alert",
    "first_alert_date",
    "max_score",
    "snapshot_count",
    "rca_reason_code",
]


def _as_bool(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def _safe_float(value: object) -> float:
    try:
        out = float(value)
    except Exception:  # noqa: BLE001
        return np.nan
    return out if np.isfinite(out) else np.nan


def build_annual_alert_cases(oof_predictions: pd.DataFrame) -> pd.DataFrame:
    """Collapse out-of-fold snapshot alerts to annual event cases."""
    if oof_predictions.empty:
        return pd.DataFrame(columns=[
            *TARGET_GROUP_KEY,
            "detector_id",
            "target_event_label",
            "any_alert",
            "first_alert_date",
            "max_score",
            "snapshot_count",
        ])
    rows: list[dict[str, object]] = []
    for keys, group in oof_predictions.groupby([*TARGET_GROUP_KEY, "detector_id"], dropna=False, sort=True):
        values = dict(zip([*TARGET_GROUP_KEY, "detector_id"], keys, strict=False))
        alerts = _as_bool(group["alert"])
        dates = pd.to_datetime(group.loc[alerts, "as_of_date"], errors="coerce")
        rows.append({
            **values,
            "target_event_label": bool(_as_bool(group["target_event_label"]).iloc[0]),
            "any_alert": bool(alerts.any()),
            "first_alert_date": dates.min() if not dates.empty else pd.NaT,
            "max_score": _safe_float(pd.to_numeric(group["score_value"], errors="coerce").max()),
            "snapshot_count": int(len(group)),
        })
    return pd.DataFrame(rows)


def build_false_case_tables(
    annual_alert_cases: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return false-negative and false-positive RCA tables."""
    if annual_alert_cases.empty:
        empty = pd.DataFrame(columns=FALSE_CASE_COLUMNS)
        return empty.copy(), empty.copy()
    cases = annual_alert_cases.copy()
    cases["target_event_label"] = _as_bool(cases["target_event_label"])
    cases["any_alert"] = _as_bool(cases["any_alert"])

    false_negatives = cases.loc[cases["target_event_label"] & ~cases["any_alert"]].copy()
    false_negatives["case_type"] = "false_negative"
    false_negatives["rca_reason_code"] = "event_without_any_alert"

    false_positives = cases.loc[~cases["target_event_label"] & cases["any_alert"]].copy()
    false_positives["case_type"] = "false_positive"
    false_positives["rca_reason_code"] = "alert_without_final_event"

    return (
        false_negatives.reindex(columns=FALSE_CASE_COLUMNS).reset_index(drop=True),
        false_positives.reindex(columns=FALSE_CASE_COLUMNS).reset_index(drop=True),
    )
