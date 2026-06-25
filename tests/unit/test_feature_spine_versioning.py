from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from jobs.batch.feature_spine_task import (
    _assert_absent,
    _bool_arg,
    _build_dataset_manifest,
    _default_dataset_version,
    _source_certification_metadata,
)


def test_default_dataset_version_contains_git_prefix(monkeypatch) -> None:
    class FixedDateTime:
        timezone = __import__("datetime").timezone

        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 25, 12, 30, tzinfo=tz)

    import jobs.batch.feature_spine_task as task

    monkeypatch.setattr(task.datetime, "datetime", FixedDateTime)
    assert _default_dataset_version("abcdef1234567890") == "20260625T123000Z_abcdef123456"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("1", True), ("yes", True), ("false", False), ("0", False), ("no", False)],
)
def test_bool_arg_accepts_batch_strings(raw: str, expected: bool) -> None:
    assert _bool_arg(raw) is expected


def test_assert_absent_refuses_existing_local_versioned_object(tmp_path) -> None:
    key = "gold/feature_spine_versions/dataset_version=v1/commodity=corn_cbot/part-000.parquet"
    path = tmp_path / key
    path.parent.mkdir(parents=True)
    path.write_bytes(b"already here")
    args = SimpleNamespace(local_root=tmp_path, fail_if_version_exists=True)

    with pytest.raises(FileExistsError):
        _assert_absent(args, key)


def test_source_certification_metadata_summarizes_statuses(tmp_path) -> None:
    report = tmp_path / "source_certification_report.json"
    report.write_text(
        json.dumps({
            "contracts_sha256": "contracts",
            "feature_registry_sha256": "features",
            "source_results": [
                {"source_key": "psd", "status": "pass"},
                {"source_key": "cot", "status": "diagnostic_only"},
                {"source_key": "fnc", "status": "deferred"},
            ],
        }),
        encoding="utf-8",
    )
    args = SimpleNamespace(source_certification_report=str(report), local_root=None)

    metadata = _source_certification_metadata(args)

    assert metadata["provided"] is True
    assert metadata["contracts_sha256"] == "contracts"
    assert metadata["feature_registry_sha256"] == "features"
    assert metadata["status_counts"] == {
        "deferred": 1,
        "diagnostic_only": 1,
        "pass": 1,
    }


def test_dataset_manifest_summarizes_written_commodities() -> None:
    args = SimpleNamespace(dataset_version="v1")
    registry = SimpleNamespace(params_hash="params")
    results = [
        {
            "commodity": "corn_cbot",
            "status": "written",
            "rows": 100,
            "feature_count": 20,
            "label_row_count": 5,
            "matrix_rows": 10,
            "matrix_columns": 22,
            "latest_keys": {"spine": "gold/feature_spine/commodity=corn_cbot/part-000.parquet"},
            "versioned_keys": {
                "spine": (
                    "gold/feature_spine_versions/"
                    "dataset_version=v1/commodity=corn_cbot/part-000.parquet"
                )
            },
            "report": {"passed": True},
            "inputs": [
                {"source": "psd", "num_files": 2, "num_rows": 30},
                {"source": "weather:chirps", "num_files": 3, "num_rows": 40},
            ],
        },
        {"commodity": "cotton", "status": "skipped_no_inputs", "rows": 0},
    ]

    manifest = _build_dataset_manifest(
        args,
        commodities=["corn_cbot", "cotton"],
        crop_years=[2023, 2024],
        git_sha="abc123",
        registry=registry,
        results=results,
        source_certification={"provided": False},
    )

    assert manifest["dataset_version"] == "v1"
    assert manifest["summary"]["requested_commodity_count"] == 2
    assert manifest["summary"]["written_count"] == 1
    assert manifest["summary"]["skipped_count"] == 1
    assert manifest["summary"]["total_spine_rows"] == 100
    assert manifest["source_summary"]["psd"]["num_rows"] == 30
    assert manifest["source_summary"]["weather:chirps"]["num_files"] == 3
