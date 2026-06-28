from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from leviathan.features.computations.psd_vintages import (
    build_psd_vintage_snapshot_feature_matrix,
    build_psd_vintage_snapshot_join_audit,
    validate_psd_vintage_feature_quality,
)
from leviathan.model_datasets.psd_model_ready import (
    PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID,
    PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID,
    PSD_DATASET_KEY,
    PSD_MATRIX_ID_COLUMNS,
    PSDModelReadyBuildConfig,
    PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID,
    PSD_SNAPSHOT_DATASET_KEY,
    WASDE_MONTHLY_REVISION_FEATURE_SET_ID,
    build_psd_commodity_model_datasets,
    build_psd_commodity_snapshot_model_datasets,
)
from leviathan.model_datasets.psd_target_builder import build_psd_target_panel
from leviathan.model_datasets.snapshot_stages import load_snapshot_stage_config
from leviathan.storage.paths import (
    gold_feature_matrix_version_key,
    gold_feature_set_version_key,
    gold_model_ready_feature_set_version_key,
    gold_model_ready_feature_set_summary_key,
    gold_model_ready_baseline_metrics_key,
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
    gold_model_ready_target_key,
)
from leviathan.training.model_ready import select_model_ready_features


def _feature_matrix(years: list[int] | None = None) -> pd.DataFrame:
    years = years or list(range(2000, 2006))
    return pd.DataFrame({
        "country": ["united_states"] * len(years),
        "crop_year": years,
        "feature_a": [float(i) for i in range(len(years))],
        "feature_b": [float(i + 10) for i in range(len(years))],
        "psd_production_mom_revision": [float(i + 20) for i in range(len(years))],
        "label_production_quantity": [100.0 + i for i in range(len(years))],
    })


def _membership() -> pd.DataFrame:
    return pd.DataFrame({
        "feature_set_id": [
            "preseason_physical",
            "preseason_physical",
            "preseason_physical",
        ],
        "feature": ["feature_a", "feature_b", "label_production_quantity"],
        "is_label": [False, False, True],
        "feature_set_version": ["1", "1", "1"],
        "feature_set_sha": ["sha", "sha", "sha"],
        "dataset_version": ["gold_v", "gold_v", "gold_v"],
    })


def _membership_with_psd_vintage() -> pd.DataFrame:
    return pd.concat([
        _membership(),
        pd.DataFrame({
            "feature_set_id": [
                "psd_monthly_vintage_features",
                "psd_monthly_vintage_features",
            ],
            "feature": [
                "psd_production_mom_revision",
                "psd_production_latest_estimate_as_of",
            ],
            "is_label": [False, False],
            "feature_set_version": ["1", "1"],
            "feature_set_sha": ["vintage_sha", "vintage_sha"],
            "dataset_version": ["gold_v", "gold_v"],
        }),
    ], ignore_index=True)


def _psd_source(values: list[float] | None = None) -> pd.DataFrame:
    values = values or [10.0, 11.0, 12.0, 13.0, 14.0, 18.0]
    rows = []
    for idx, value in enumerate(values):
        year = 2000 + idx
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


def _psd_source_with_monthly_vintages(
    *,
    include_future_revision: bool = False,
) -> pd.DataFrame:
    rows = []
    for year in range(2000, 2005):
        value = 10.0 + float(year - 2000)
        rows.append({
            "leviathan_slug": "corn_cbot",
            "country": "United States",
            "market_year": year,
            "release_date": f"{year}-01-15",
            "production_mt": value,
            "ending_stocks_mt": value + 20.0,
            "su_ratio": value / 100.0,
            "exports_mt": value + 30.0,
            "imports_mt": value + 40.0,
            "consumption_mt": value + 50.0,
        })
    for release_date, value in (
        ("2005-05-10", 20.0),
        ("2005-07-10", 23.0),
        ("2005-10-10", 27.0),
    ):
        rows.append({
            "leviathan_slug": "corn_cbot",
            "country": "United States",
            "market_year": 2005,
            "release_date": release_date,
            "production_mt": value,
            "ending_stocks_mt": value + 20.0,
            "su_ratio": value / 100.0,
            "exports_mt": value + 30.0,
            "imports_mt": value + 40.0,
            "consumption_mt": value + 50.0,
        })
    if include_future_revision:
        rows.append({
            "leviathan_slug": "corn_cbot",
            "country": "United States",
            "market_year": 2005,
            "release_date": "2005-12-10",
            "production_mt": 999.0,
            "ending_stocks_mt": 1019.0,
            "su_ratio": 9.99,
            "exports_mt": 1029.0,
            "imports_mt": 1039.0,
            "consumption_mt": 1049.0,
        })
    return pd.DataFrame(rows)


def _wasde_source_with_revisions(include_future_revision: bool = False) -> pd.DataFrame:
    rows = []
    for year, revisions in {
        2000: [1.0, 2.0],
        2001: [2.0, 3.0],
        2002: [3.0, 4.0],
        2003: [4.0, 5.0],
        2004: [5.0, 6.0],
        2005: [7.0, 9.0],
    }.items():
        for month, revision in zip((5, 6), revisions):
            rows.append({
                "release_date": f"{year}-{month:02d}-10",
                "commodity": "corn",
                "table_type": "world",
                "region": "united_states",
                "marketing_year": f"{year}/{str(year + 1)[-2:]}",
                "attribute": "production",
                "unit": "million_metric_tons",
                "estimate": 100.0 + revision,
                "prior_release_date": f"{year}-{month - 1:02d}-10",
                "prior_estimate": 100.0,
                "revision": revision,
                "revision_direction": "up",
                "source": "usda_wasde",
            })
            rows.append({
                "release_date": f"{year}-{month:02d}-10",
                "commodity": "corn",
                "table_type": "world",
                "region": "united_states",
                "marketing_year": f"{year}/{str(year + 1)[-2:]}",
                "attribute": "ending_stocks",
                "unit": "million_metric_tons",
                "estimate": 50.0 + revision,
                "prior_release_date": f"{year}-{month - 1:02d}-10",
                "prior_estimate": 50.0,
                "revision": revision / 2.0,
                "revision_direction": "up",
                "source": "usda_wasde",
            })
    if include_future_revision:
        rows.append({
            "release_date": "2005-08-10",
            "commodity": "corn",
            "table_type": "world",
            "region": "united_states",
            "marketing_year": "2005/06",
            "attribute": "production",
            "unit": "million_metric_tons",
            "estimate": 999.0,
            "prior_release_date": "2005-07-10",
            "prior_estimate": 100.0,
            "revision": 999.0,
            "revision_direction": "up",
            "source": "usda_wasde",
        })
    return pd.DataFrame(rows)


def _psd_targets() -> pd.DataFrame:
    return build_psd_target_panel(
        _psd_source(),
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )


def test_psd_model_ready_builds_matrices_and_baselines() -> None:
    built = build_psd_commodity_model_datasets(
        _feature_matrix(),
        _psd_targets(),
        commodity="corn_cbot",
        feature_membership=_membership(),
        target_keys=("psd_production_anomaly_pct",),
    )

    assert set(built.target_tables) == {PSD_DATASET_KEY}
    assert set(built.matrices) == {(PSD_DATASET_KEY, "psd_production_anomaly_pct")}
    matrix = built.matrices[(PSD_DATASET_KEY, "psd_production_anomaly_pct")]

    assert set(PSD_MATRIX_ID_COLUMNS).issubset(matrix.columns)
    assert "feature_a" in matrix.columns
    assert "feature_b" in matrix.columns
    assert "label_production_quantity" not in matrix.columns
    assert matrix.loc[matrix["crop_year"] == 2005, "is_trainable"].iloc[0]
    assert set(built.baseline_metrics["baseline_name"]) == {
        "zero_anomaly",
        "prior_year",
        "trailing_mean",
        "trailing_linear_trend",
    }
    assert built.summaries[0]["target_source"] == "psd"
    assert built.summaries[0]["target_attribute"] == "production_mt"


def test_psd_model_ready_marks_missing_feature_rows() -> None:
    built = build_psd_commodity_model_datasets(
        _feature_matrix(years=list(range(2000, 2005))),
        _psd_targets(),
        commodity="corn_cbot",
        feature_membership=_membership(),
        target_keys=("psd_production_anomaly_pct",),
    )
    matrix = built.matrices[(PSD_DATASET_KEY, "psd_production_anomaly_pct")]
    row = matrix.loc[matrix["crop_year"] == 2005].iloc[0]

    assert not row["is_trainable"]
    assert row["excluded_reason"] == "missing_features"


def test_psd_model_ready_rejects_duplicate_feature_keys() -> None:
    duplicated = pd.concat([_feature_matrix(), _feature_matrix().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate feature matrix keys"):
        build_psd_commodity_model_datasets(
            duplicated,
            _psd_targets(),
            commodity="corn_cbot",
            feature_membership=_membership(),
            target_keys=("psd_production_anomaly_pct",),
        )


def test_psd_model_ready_rejects_duplicate_target_keys() -> None:
    targets = _psd_targets()
    duplicate = targets.loc[
        targets["target_key"] == "psd_production_anomaly_pct"
    ].iloc[[0]]
    bad_targets = pd.concat([targets, duplicate], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate PSD target keys"):
        build_psd_commodity_model_datasets(
            _feature_matrix(),
            bad_targets,
            commodity="corn_cbot",
            feature_membership=_membership(),
            target_keys=("psd_production_anomaly_pct",),
        )


def test_training_feature_selection_excludes_psd_metadata() -> None:
    built = build_psd_commodity_model_datasets(
        _feature_matrix(),
        _psd_targets(),
        commodity="corn_cbot",
        feature_membership=_membership(),
        target_keys=("psd_production_anomaly_pct",),
    )
    matrix = built.matrices[(PSD_DATASET_KEY, "psd_production_anomaly_pct")]

    feature_cols, _ = select_model_ready_features(matrix, _membership(), "preseason_physical")

    assert feature_cols == ["feature_a", "feature_b"]


def test_psd_model_ready_default_excludes_monthly_vintage_feature_set() -> None:
    built = build_psd_commodity_model_datasets(
        _feature_matrix(),
        _psd_targets(),
        commodity="corn_cbot",
        feature_membership=_membership_with_psd_vintage(),
        target_keys=("psd_production_anomaly_pct",),
    )
    matrix = built.matrices[(PSD_DATASET_KEY, "psd_production_anomaly_pct")]

    assert "feature_a" in matrix.columns
    assert "psd_production_mom_revision" not in matrix.columns


def test_model_ready_cli_writes_local_psd_version(tmp_path: Path) -> None:
    source_version = "gold_v"
    model_version = "model_psd_v"
    matrix_key = gold_feature_matrix_version_key(source_version, "corn_cbot")
    membership_key = gold_feature_set_version_key(source_version)
    psd_key = "silver/psd/part-000.parquet"
    (tmp_path / matrix_key).parent.mkdir(parents=True)
    _feature_matrix().to_parquet(tmp_path / matrix_key, index=False)
    (tmp_path / membership_key).parent.mkdir(parents=True)
    _membership().to_parquet(tmp_path / membership_key, index=False)
    (tmp_path / psd_key).parent.mkdir(parents=True)
    _psd_source().to_parquet(tmp_path / psd_key, index=False)

    subprocess.run(
        [
            sys.executable,
            "jobs/batch/build_model_ready_datasets.py",
            "--local-root",
            str(tmp_path),
            "--target-source",
            "psd",
            "--source-dataset-version",
            source_version,
            "--model-dataset-version",
            model_version,
            "--commodities",
            "corn_cbot",
            "--target-keys",
            "psd_production_anomaly_pct",
            "--workers",
            "2",
        ],
        check=True,
    )

    assert (tmp_path / gold_model_ready_target_key(
        model_version, PSD_DATASET_KEY, "corn_cbot"
    )).exists()
    assert (tmp_path / gold_model_ready_matrix_key(
        model_version, PSD_DATASET_KEY, "corn_cbot", "psd_production_anomaly_pct"
    )).exists()
    assert (tmp_path / gold_model_ready_baseline_metrics_key(model_version)).exists()

    manifest = json.loads((tmp_path / gold_model_ready_manifest_key(model_version)).read_text())
    assert manifest["target_source"] == "psd"
    assert manifest["psd_mapping_sha"]
    assert manifest["summary"]["built_target_count"] == 1
    assert manifest["summary"]["matrix_count"] == 1


def test_model_ready_cli_can_materialize_psd_vintage_feature_set(tmp_path: Path) -> None:
    source_version = "gold_v"
    model_version = "model_psd_vintage_v"
    matrix_key = gold_feature_matrix_version_key(source_version, "corn_cbot")
    membership_key = gold_feature_set_version_key(source_version)
    psd_key = "silver/psd/part-000.parquet"
    (tmp_path / matrix_key).parent.mkdir(parents=True)
    _feature_matrix().to_parquet(tmp_path / matrix_key, index=False)
    (tmp_path / membership_key).parent.mkdir(parents=True)
    _membership_with_psd_vintage().to_parquet(tmp_path / membership_key, index=False)
    (tmp_path / psd_key).parent.mkdir(parents=True)
    _psd_source().to_parquet(tmp_path / psd_key, index=False)

    subprocess.run(
        [
            sys.executable,
            "jobs/batch/build_model_ready_datasets.py",
            "--local-root",
            str(tmp_path),
            "--target-source",
            "psd",
            "--source-dataset-version",
            source_version,
            "--model-dataset-version",
            model_version,
            "--commodities",
            "corn_cbot",
            "--target-keys",
            "psd_production_anomaly_pct",
            "--compatible-feature-sets",
            "psd_monthly_vintage_features",
            "--workers",
            "2",
        ],
        check=True,
    )

    matrix = pd.read_parquet(tmp_path / gold_model_ready_matrix_key(
        model_version, PSD_DATASET_KEY, "corn_cbot", "psd_production_anomaly_pct"
    ))
    manifest = json.loads((tmp_path / gold_model_ready_manifest_key(model_version)).read_text())

    assert "psd_production_mom_revision" in matrix.columns
    assert "feature_a" not in matrix.columns
    assert manifest["psd_compatible_feature_sets"] == ["psd_monthly_vintage_features"]


def test_psd_snapshot_model_ready_builds_named_stage_rows() -> None:
    psd_source = _psd_source_with_monthly_vintages()
    psd_targets = build_psd_target_panel(
        psd_source,
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    from leviathan.features.calendar import load_crop_calendars

    built = build_psd_commodity_snapshot_model_datasets(
        psd_source,
        psd_targets,
        commodity="corn_cbot",
        feature_membership=_membership_with_psd_vintage(),
        calendar=load_crop_calendars()["corn_cbot"],
        snapshot_config=load_snapshot_stage_config(),
        snapshot_stage_ids=("early_inseason", "midseason"),
        target_keys=("psd_production_anomaly_pct",),
    )

    matrix = built.matrices[
        (PSD_SNAPSHOT_DATASET_KEY, "psd_production_anomaly_pct")
    ]
    year_rows = matrix.loc[matrix["crop_year"] == 2005].set_index("snapshot_stage")

    assert set(built.target_tables) == {PSD_SNAPSHOT_DATASET_KEY}
    assert set(year_rows.index) == {"early_inseason", "midseason"}
    assert year_rows.loc["early_inseason", "psd_production_latest_estimate_as_of"] == 20.0
    assert year_rows.loc["midseason", "psd_production_latest_estimate_as_of"] == 23.0
    assert "snapshot_stage" in matrix.columns
    assert "as_of_date" in matrix.columns
    assert matrix["dataset_key"].eq(PSD_SNAPSHOT_DATASET_KEY).all()
    assert built.summaries[0]["vintage_feature_quality"]["feature_count"] > 0
    assert built.summaries[0]["vintage_join_audit"]["row_count"] > 0


def test_psd_vintage_snapshot_uses_explicit_target_market_year() -> None:
    psd_source = pd.DataFrame([
        {
            "country": "united_states",
            "market_year": 2005,
            "release_date": "2005-07-10",
            "production_mt": 50.0,
        },
        {
            "country": "united_states",
            "market_year": 2006,
            "release_date": "2006-05-10",
            "production_mt": 100.0,
        },
        {
            "country": "united_states",
            "market_year": 2006,
            "release_date": "2006-07-10",
            "production_mt": 110.0,
        },
    ])
    snapshots = pd.DataFrame([
        {
            "country": "united_states",
            "crop_year": 2005,
            "target_market_year": 2006,
            "snapshot_stage": "explicit_as_of",
            "as_of_date": "2006-08-01",
        }
    ])

    matrix = build_psd_vintage_snapshot_feature_matrix(
        psd_source,
        countries=["united_states"],
        snapshots=snapshots,
    )
    row = matrix.iloc[0]

    assert row["crop_year"] == 2005
    assert row["psd_production_latest_estimate_as_of"] == 110.0
    assert row["psd_production_mom_revision"] == 10.0


def test_psd_vintage_join_audit_reports_no_visible_rows() -> None:
    psd_source = pd.DataFrame([
        {
            "country": "united_states",
            "market_year": 2005,
            "release_date": "2005-10-10",
            "production_mt": 50.0,
        }
    ])
    snapshots = pd.DataFrame([
        {
            "country": "united_states",
            "crop_year": 2005,
            "target_market_year": 2005,
            "snapshot_stage": "early",
            "as_of_date": "2005-07-01",
        }
    ])

    audit = build_psd_vintage_snapshot_join_audit(
        psd_source,
        countries=["united_states"],
        snapshots=snapshots,
    )
    row = audit.loc[audit["psd_attribute"] == "production_mt"].iloc[0]

    assert row["market_year_rows"] == 1
    assert row["visible_rows"] == 0
    assert row["missing_reason"] == "no_visible_rows_as_of_snapshot"


def test_psd_vintage_quality_rejects_all_missing_required_family() -> None:
    matrix = pd.DataFrame({
        "country": ["united_states"],
        "crop_year": [2005],
        "snapshot_stage": ["early"],
        "as_of_date": [pd.Timestamp("2005-07-01").date()],
        "psd_production_latest_estimate_as_of": [float("nan")],
    })

    with pytest.raises(ValueError, match="PSD vintage feature quality failed"):
        validate_psd_vintage_feature_quality(matrix)


def test_psd_snapshot_model_ready_infers_vintage_features_without_source_feature_set() -> None:
    psd_source = _psd_source_with_monthly_vintages()
    psd_targets = build_psd_target_panel(
        psd_source,
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    from leviathan.features.calendar import load_crop_calendars

    built = build_psd_commodity_snapshot_model_datasets(
        psd_source,
        psd_targets,
        commodity="corn_cbot",
        feature_membership=_membership(),
        calendar=load_crop_calendars()["corn_cbot"],
        snapshot_config=load_snapshot_stage_config(),
        snapshot_stage_ids=("early_inseason", "midseason"),
        target_keys=("psd_production_anomaly_pct",),
    )
    matrix = built.matrices[
        (PSD_SNAPSHOT_DATASET_KEY, "psd_production_anomaly_pct")
    ]

    assert "psd_production_latest_estimate_as_of" in matrix.columns
    assert "psd_production_mom_revision" in matrix.columns
    assert built.summaries[0]["feature_count_by_set"][PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID] > 0


def test_psd_snapshot_model_ready_can_combine_preseason_and_vintage_features() -> None:
    psd_source = _psd_source_with_monthly_vintages()
    psd_targets = build_psd_target_panel(
        psd_source,
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    from leviathan.features.calendar import load_crop_calendars

    built = build_psd_commodity_snapshot_model_datasets(
        psd_source,
        psd_targets,
        commodity="corn_cbot",
        feature_membership=_membership(),
        calendar=load_crop_calendars()["corn_cbot"],
        snapshot_config=load_snapshot_stage_config(),
        snapshot_stage_ids=("early_inseason", "midseason"),
        static_feature_matrix=_feature_matrix(),
        config=PSDModelReadyBuildConfig(
            compatible_feature_sets=(PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID,)
        ),
        target_keys=("psd_production_anomaly_pct",),
    )
    matrix = built.matrices[
        (PSD_SNAPSHOT_DATASET_KEY, "psd_production_anomaly_pct")
    ]

    assert "feature_a" in matrix.columns
    assert "feature_b" in matrix.columns
    assert "psd_production_latest_estimate_as_of" in matrix.columns
    assert built.summaries[0]["feature_count_by_set"][
        PSD_PRESEASON_PLUS_VINTAGE_FEATURE_SET_ID
    ] >= 3


def test_psd_snapshot_model_ready_adds_visible_wasde_revisions() -> None:
    psd_source = _psd_source_with_monthly_vintages()
    psd_targets = build_psd_target_panel(
        psd_source,
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    from leviathan.features.calendar import load_crop_calendars

    built = build_psd_commodity_snapshot_model_datasets(
        psd_source,
        psd_targets,
        commodity="corn_cbot",
        feature_membership=_membership(),
        calendar=load_crop_calendars()["corn_cbot"],
        snapshot_config=load_snapshot_stage_config(),
        as_of_date="2005-07-01",
        include_named_stages=False,
        wasde_source=_wasde_source_with_revisions(include_future_revision=True),
        config=PSDModelReadyBuildConfig(
            compatible_feature_sets=(WASDE_MONTHLY_REVISION_FEATURE_SET_ID,)
        ),
        target_keys=("psd_production_anomaly_pct",),
    )
    matrix = built.matrices[
        (PSD_SNAPSHOT_DATASET_KEY, "psd_production_anomaly_pct")
    ]
    row = matrix.loc[matrix["crop_year"] == 2005].iloc[0]

    assert "wasde_latest_revision" in matrix.columns
    assert "wasde_production_revision_z" in matrix.columns
    assert row["wasde_latest_revision"] == 9.0
    assert row["wasde_consecutive_revision_count"] == 2.0
    assert row["wasde_production_revision_z"] < 999.0
    assert built.summaries[0]["feature_count_by_set"][WASDE_MONTHLY_REVISION_FEATURE_SET_ID] > 0


def test_psd_snapshot_model_ready_can_combine_preseason_and_wasde_features() -> None:
    psd_source = _psd_source_with_monthly_vintages()
    psd_targets = build_psd_target_panel(
        psd_source,
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    from leviathan.features.calendar import load_crop_calendars

    built = build_psd_commodity_snapshot_model_datasets(
        psd_source,
        psd_targets,
        commodity="corn_cbot",
        feature_membership=_membership(),
        calendar=load_crop_calendars()["corn_cbot"],
        snapshot_config=load_snapshot_stage_config(),
        as_of_date="2005-07-01",
        include_named_stages=False,
        static_feature_matrix=_feature_matrix(),
        wasde_source=_wasde_source_with_revisions(),
        config=PSDModelReadyBuildConfig(
            compatible_feature_sets=(PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID,)
        ),
        target_keys=("psd_production_anomaly_pct",),
    )
    matrix = built.matrices[
        (PSD_SNAPSHOT_DATASET_KEY, "psd_production_anomaly_pct")
    ]

    assert "feature_a" in matrix.columns
    assert "feature_b" in matrix.columns
    assert "wasde_latest_revision" in matrix.columns
    assert built.summaries[0]["feature_count_by_set"][
        PRESEASON_PLUS_WASDE_REVISION_FEATURE_SET_ID
    ] >= 3


def test_psd_snapshot_model_ready_explicit_as_of_uses_only_visible_releases() -> None:
    psd_source = _psd_source_with_monthly_vintages(include_future_revision=True)
    psd_targets = build_psd_target_panel(
        _psd_source_with_monthly_vintages(),
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    from leviathan.features.calendar import load_crop_calendars

    built = build_psd_commodity_snapshot_model_datasets(
        psd_source,
        psd_targets,
        commodity="corn_cbot",
        feature_membership=_membership_with_psd_vintage(),
        calendar=load_crop_calendars()["corn_cbot"],
        snapshot_config=load_snapshot_stage_config(),
        as_of_date="2005-07-01",
        include_named_stages=False,
        target_keys=("psd_production_anomaly_pct",),
    )

    matrix = built.matrices[
        (PSD_SNAPSHOT_DATASET_KEY, "psd_production_anomaly_pct")
    ]
    row = matrix.loc[matrix["crop_year"] == 2005].iloc[0]

    assert row["snapshot_stage"] == "explicit_as_of"
    assert row["as_of_date"] == pd.Timestamp("2005-07-01").date()
    assert row["snapshot_policy"] == "explicit_as_of_date"
    assert row["psd_production_latest_estimate_as_of"] == 20.0
    assert "psd_production_mom_revision" not in matrix.columns


def test_psd_snapshot_model_ready_prunes_all_missing_vintage_features() -> None:
    psd_source = _psd_source_with_monthly_vintages()
    psd_targets = build_psd_target_panel(
        _psd_source_with_monthly_vintages(),
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    from leviathan.features.calendar import load_crop_calendars

    built = build_psd_commodity_snapshot_model_datasets(
        psd_source,
        psd_targets,
        commodity="corn_cbot",
        feature_membership=_membership_with_psd_vintage(),
        calendar=load_crop_calendars()["corn_cbot"],
        snapshot_config=load_snapshot_stage_config(),
        as_of_date="2005-07-01",
        include_named_stages=False,
        target_keys=("psd_production_anomaly_pct",),
    )

    matrix = built.matrices[
        (PSD_SNAPSHOT_DATASET_KEY, "psd_production_anomaly_pct")
    ]

    assert "psd_production_latest_estimate_as_of" in matrix.columns
    assert "psd_production_mom_revision" not in matrix.columns
    assert "psd_production_mom_revision" in built.summaries[0][
        "dropped_empty_vintage_features"
    ]


def test_psd_snapshot_features_are_invariant_to_future_revisions() -> None:
    base_source = _psd_source_with_monthly_vintages()
    future_source = _psd_source_with_monthly_vintages(include_future_revision=True)
    psd_targets = build_psd_target_panel(
        base_source,
        source_dataset_version="gold_v",
        commodities=["corn_cbot"],
    )
    from leviathan.features.calendar import load_crop_calendars

    kwargs = {
        "commodity": "corn_cbot",
        "feature_membership": _membership_with_psd_vintage(),
        "calendar": load_crop_calendars()["corn_cbot"],
        "snapshot_config": load_snapshot_stage_config(),
        "snapshot_stage_ids": ("early_inseason", "midseason"),
        "target_keys": ("psd_production_anomaly_pct",),
    }
    without_future = build_psd_commodity_snapshot_model_datasets(
        base_source, psd_targets, **kwargs
    ).matrices[(PSD_SNAPSHOT_DATASET_KEY, "psd_production_anomaly_pct")]
    with_future = build_psd_commodity_snapshot_model_datasets(
        future_source, psd_targets, **kwargs
    ).matrices[(PSD_SNAPSHOT_DATASET_KEY, "psd_production_anomaly_pct")]

    compare_cols = [
        "country",
        "crop_year",
        "snapshot_stage",
        "as_of_date",
        "psd_production_latest_estimate_as_of",
        "psd_production_mom_revision",
    ]
    pd.testing.assert_frame_equal(
        without_future[compare_cols].reset_index(drop=True),
        with_future[compare_cols].reset_index(drop=True),
    )


def test_model_ready_cli_writes_local_psd_snapshot_version(tmp_path: Path) -> None:
    source_version = "g"
    model_version = "mps"
    membership_key = gold_feature_set_version_key(source_version)
    psd_key = "silver/psd/part-000.parquet"
    (tmp_path / membership_key).parent.mkdir(parents=True)
    _membership_with_psd_vintage().to_parquet(tmp_path / membership_key, index=False)
    (tmp_path / psd_key).parent.mkdir(parents=True)
    _psd_source_with_monthly_vintages().to_parquet(tmp_path / psd_key, index=False)

    subprocess.run(
        [
            sys.executable,
            "jobs/batch/build_model_ready_datasets.py",
            "--local-root",
            str(tmp_path),
            "--target-source",
            "psd",
            "--snapshot-stages",
            "early_inseason,midseason",
            "--source-dataset-version",
            source_version,
            "--model-dataset-version",
            model_version,
            "--commodities",
            "corn_cbot",
            "--target-keys",
            "psd_production_anomaly_pct",
            "--workers",
            "2",
        ],
        check=True,
    )

    matrix = pd.read_parquet(tmp_path / gold_model_ready_matrix_key(
        model_version,
        PSD_SNAPSHOT_DATASET_KEY,
        "corn_cbot",
        "psd_production_anomaly_pct",
    ))
    manifest = json.loads((tmp_path / gold_model_ready_manifest_key(model_version)).read_text())

    assert matrix["dataset_key"].eq(PSD_SNAPSHOT_DATASET_KEY).all()
    assert set(matrix["snapshot_stage"]) == {"early_inseason", "midseason"}
    assert "psd_production_latest_estimate_as_of" in matrix.columns
    assert manifest["snapshot_mode"] is True
    assert manifest["snapshot_stages"] == ["early_inseason", "midseason"]


def test_model_ready_cli_writes_snapshot_model_ready_feature_sets(tmp_path: Path) -> None:
    source_version = "g"
    model_version = "mps_feature_sets"
    membership_key = gold_feature_set_version_key(source_version)
    psd_key = "silver/psd/part-000.parquet"
    (tmp_path / membership_key).parent.mkdir(parents=True)
    _membership().to_parquet(tmp_path / membership_key, index=False)
    (tmp_path / psd_key).parent.mkdir(parents=True)
    _psd_source_with_monthly_vintages().to_parquet(tmp_path / psd_key, index=False)

    subprocess.run(
        [
            sys.executable,
            "jobs/batch/build_model_ready_datasets.py",
            "--local-root",
            str(tmp_path),
            "--target-source",
            "psd",
            "--snapshot-mode",
            "true",
            "--snapshot-stages",
            "early_inseason,midseason",
            "--source-dataset-version",
            source_version,
            "--model-dataset-version",
            model_version,
            "--commodities",
            "corn_cbot",
            "--target-keys",
            "psd_production_anomaly_pct",
            "--workers",
            "2",
        ],
        check=True,
    )

    feature_sets = pd.read_parquet(
        tmp_path / gold_model_ready_feature_set_version_key(model_version)
    )
    manifest = json.loads((tmp_path / gold_model_ready_manifest_key(model_version)).read_text())

    assert (tmp_path / gold_model_ready_feature_set_summary_key(model_version)).exists()
    assert set(feature_sets["feature_set_id"]) == {PSD_BALANCE_SHEET_SNAPSHOT_FEATURE_SET_ID}
    assert "psd_production_latest_estimate_as_of" in set(feature_sets["feature"])
    assert manifest["outputs"]["model_ready_feature_sets_key"] == (
        gold_model_ready_feature_set_version_key(model_version)
    )


def test_model_ready_cli_can_materialize_wasde_snapshot_feature_set(tmp_path: Path) -> None:
    source_version = "g"
    model_version = "mps_wasde_snapshot"
    membership_key = gold_feature_set_version_key(source_version)
    psd_key = "silver/psd/part-000.parquet"
    wasde_key = "silver/wasde/release_date=2005-06-10/part-000.parquet"
    (tmp_path / membership_key).parent.mkdir(parents=True)
    _membership().to_parquet(tmp_path / membership_key, index=False)
    (tmp_path / psd_key).parent.mkdir(parents=True)
    _psd_source_with_monthly_vintages().to_parquet(tmp_path / psd_key, index=False)
    (tmp_path / wasde_key).parent.mkdir(parents=True)
    _wasde_source_with_revisions().to_parquet(tmp_path / wasde_key, index=False)

    subprocess.run(
        [
            sys.executable,
            "jobs/batch/build_model_ready_datasets.py",
            "--local-root",
            str(tmp_path),
            "--target-source",
            "psd",
            "--snapshot-mode",
            "true",
            "--as-of-date",
            "2005-07-01",
            "--source-dataset-version",
            source_version,
            "--model-dataset-version",
            model_version,
            "--commodities",
            "corn_cbot",
            "--target-keys",
            "psd_production_anomaly_pct",
            "--compatible-feature-sets",
            WASDE_MONTHLY_REVISION_FEATURE_SET_ID,
            "--workers",
            "2",
        ],
        check=True,
    )

    matrix = pd.read_parquet(tmp_path / gold_model_ready_matrix_key(
        model_version,
        PSD_SNAPSHOT_DATASET_KEY,
        "corn_cbot",
        "psd_production_anomaly_pct",
    ))
    feature_sets = pd.read_parquet(
        tmp_path / gold_model_ready_feature_set_version_key(model_version)
    )

    assert "wasde_latest_revision" in matrix.columns
    assert matrix.loc[matrix["crop_year"] == 2005, "wasde_latest_revision"].iloc[0] == 9.0
    assert set(feature_sets["feature_set_id"]) == {WASDE_MONTHLY_REVISION_FEATURE_SET_ID}
    assert "wasde_latest_revision" in set(feature_sets["feature"])
