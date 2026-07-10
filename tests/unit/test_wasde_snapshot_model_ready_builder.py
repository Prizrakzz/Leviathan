from __future__ import annotations

import json
import subprocess
import sys

import pandas as pd
from leviathan.model_datasets.wasde_snapshot_model_ready import (
    build_wasde_snapshot_model_ready_matrix,
)

from jobs.utils.build_wasde_snapshot_model_ready_dataset import (
    _selected_dynamic_features,
    _target_matrix_outputs,
    build_model_ready_feature_membership,
)


def _psd_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = [10.0, 11.0, 12.0, 13.0, 14.0, 12.0]
    for offset, value in enumerate(values):
        year = 2000 + offset
        rows.append({
            "leviathan_slug": "corn_cbot",
            "country": "United States",
            "market_year": year,
            "release_date": f"{year + 1}-02-01",
            "production_mt": value,
            "ending_stocks_mt": value + 20.0,
            "su_ratio": value / 100.0,
            "exports_mt": value + 30.0,
            "imports_mt": value + 40.0,
            "consumption_mt": value + 50.0,
        })
    return pd.DataFrame(rows)


def _wasde_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for release_idx, release_date in enumerate(["2005-05-12", "2005-06-10", "2005-08-12"]):
        for attr_idx, attribute in enumerate([
            "production",
            "ending_stocks",
            "exports",
            "imports",
            "domestic_total",
            "total_use",
        ]):
            rows.append({
                "release_date": release_date,
                "commodity": "corn",
                "table_type": "us",
                "region": "United States",
                "marketing_year": "2005/06",
                "attribute": attribute,
                "estimate": 100.0 + release_idx + attr_idx,
                "revision": 1.0 if release_idx else 0.0,
            })
    return pd.DataFrame(rows)


def test_release_date_builder_outputs_training_aliases_and_membership() -> None:
    result = build_wasde_snapshot_model_ready_matrix(
        _psd_rows(),
        _wasde_rows(),
        source_dataset_version="source_v",
        dataset_key="corn_wasde_snapshot_solo",
        target_keys=("psd_stock_to_use_anomaly_pct", "psd_ending_stocks_anomaly_pct"),
        min_history_years=2,
    )

    selected = _selected_dynamic_features(
        result.matrix,
        result.dynamic_feature_columns,
        min_non_null_rate=0.5,
    )
    matrices = _target_matrix_outputs(result.matrix)
    membership, summary = build_model_ready_feature_membership(
        model_dataset_version="model_v",
        feature_set_ids=("wasde_monthly_revision",),
        feature_columns=selected,
        matrix=result.matrix,
    )

    assert set(matrices) == {"psd_ending_stocks_anomaly_pct", "psd_stock_to_use_anomaly_pct"}
    for matrix in matrices.values():
        assert {"country", "crop_year"}.issubset(matrix.columns)
        assert set(matrix["country"]) == {"united_states"}
        assert matrix["zero_anomaly_baseline"].eq(0.0).all()
        assert matrix["source_release_date_max"].le(matrix["as_of_date"]).all()
    assert membership["feature_set_id"].unique().tolist() == ["wasde_monthly_revision"]
    assert summary["feature_count_by_set"]["wasde_monthly_revision"] == len(selected)
    assert any(feature.startswith("wasde_ending_stocks_") for feature in selected)


def test_wasde_snapshot_model_ready_job_definition_exposes_phase3_parameters() -> None:
    completed = subprocess.run(
        [sys.executable, "jobs/utils/register_wasde_snapshot_model_ready_jobdef.py", "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    command = payload["containerProperties"]["command"]
    params = payload["parameters"]

    assert "jobs/batch/wasde_snapshot_model_ready_task.py" in command
    assert "--target-keys" in command
    assert "--feature-set-ids" in command
    assert "--skip-existing-versioned" in command
    assert params["dataset_key"] == "corn_wasde_snapshot_solo"
    assert "psd_stock_to_use_anomaly_pct" in params["target_keys"]
