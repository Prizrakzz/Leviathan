"""Certify a Phase 10 MLflow smoke run without invoking Airflow.

This is the final gate before broad experiment sweeps.  It checks that the run
is visible in MLflow, carries required provenance, has reviewable artifacts,
can replay the fitted model, and points to an external prediction object in S3.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.training.mlflow_replay import verify_mlflow_run_replay  # noqa: E402


REQUIRED_TAGS = (
    "commodity",
    "feature_set_sha",
    "data_fingerprint",
    "fitted_model_artifact_path",
    "fitted_model_flavor",
    "predictions_uri",
)

REQUIRED_ARTIFACTS = (
    "metadata/training_summary.json",
    "metadata/selected_features.json",
    "logs/training.log",
    "tables/cv_predictions.parquet",
    "tables/fold_metrics.parquet",
    "tables/model_replay_sample.parquet",
    "tables/selected_features.parquet",
)


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"not an S3 URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _s3_object_exists(s3, uri: str) -> bool:
    bucket, key = _parse_s3_uri(uri)
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except Exception:  # noqa: BLE001 - reported as failed check
        return False
    return True


def _artifact_exists(client, run_id: str, artifact_path: str) -> bool:
    parts = artifact_path.rstrip("/").split("/")
    parent = "/".join(parts[:-1])
    name = parts[-1]
    try:
        infos = client.list_artifacts(run_id, parent or None)
    except Exception:  # noqa: BLE001 - reported as failed check
        return False
    for info in infos:
        if info.path.rstrip("/").split("/")[-1] == name:
            return True
    return False


def _logged_model_exists(client, run) -> tuple[bool, str]:
    """Return whether MLflow has a fitted model for this run.

    MLflow 2.x commonly exposes the model as a run artifact under ``model/``.
    MLflow 3.x stores flavor-logged models in the logged-model namespace while
    retaining ``runs:/<run_id>/model`` loading compatibility.  Accept either.
    """
    run_id = run.info.run_id
    if _artifact_exists(client, run_id, "model"):
        return True, "run artifact:model"
    try:
        models = client.search_logged_models(
            experiment_ids=[run.info.experiment_id],
            filter_string=f"source_run_id = '{run_id}'",
        )
    except Exception as exc:  # noqa: BLE001 - reported in the detail
        return False, f"logged model search failed: {exc}"
    for model in models:
        if getattr(model, "name", None) == "model" and str(getattr(model, "status", "")):
            model_id = getattr(model, "model_id", "")
            return True, f"logged model:{model_id}"
    return False, "no run artifact or logged model named model"


def _check(name: str, passed: bool, detail: str = "") -> dict[str, str | bool]:
    return {"name": name, "status": "pass" if passed else "fail", "detail": detail}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--tracking-uri", default=None)
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-8)
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    import mlflow
    from mlflow.tracking import MlflowClient

    if args.tracking_uri:
        mlflow.set_tracking_uri(args.tracking_uri)
    client = MlflowClient()
    run = client.get_run(args.run_id)
    tags = run.data.tags
    checks: list[dict[str, str | bool]] = []

    for tag in REQUIRED_TAGS:
        checks.append(_check(f"tag:{tag}", bool(tags.get(tag)), tags.get(tag, "")))

    has_dataset_version = bool(tags.get("model_dataset_version") or tags.get("dataset_version"))
    checks.append(
        _check(
            "tag:dataset_version_or_model_dataset_version",
            has_dataset_version,
            tags.get("model_dataset_version") or tags.get("dataset_version") or "",
        )
    )

    for artifact_path in REQUIRED_ARTIFACTS:
        checks.append(
            _check(
                f"artifact:{artifact_path}",
                _artifact_exists(client, args.run_id, artifact_path),
            )
        )
    model_exists, model_detail = _logged_model_exists(client, run)
    checks.append(_check("mlflow:fitted_model", model_exists, model_detail))

    s3 = boto3.client("s3", region_name=args.aws_region)
    predictions_uri = tags.get("predictions_uri", "")
    checks.append(
        _check(
            "s3:predictions_uri",
            bool(predictions_uri) and _s3_object_exists(s3, predictions_uri),
            predictions_uri,
        )
    )

    replay_payload: dict | None = None
    try:
        replay = verify_mlflow_run_replay(
            args.run_id,
            tracking_uri=args.tracking_uri,
            tolerance=args.tolerance,
        )
        replay_payload = replay.to_dict()
        checks.append(
            _check(
                "mlflow:model_replay",
                replay.passed,
                f"max_abs_error={replay.max_abs_error}",
            )
        )
    except Exception as exc:  # noqa: BLE001 - keep full report visible
        replay_payload = {"status": "error", "error": str(exc)}
        checks.append(_check("mlflow:model_replay", False, str(exc)))

    failed = [check for check in checks if check["status"] != "pass"]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": args.run_id,
        "tracking_uri": args.tracking_uri,
        "status": "pass" if not failed else "fail",
        "failed_check_count": len(failed),
        "checks": checks,
        "replay": replay_payload,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.fail_on_error and failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
