"""Build local transparent WASDE snapshot anomaly-score artifacts.

This utility reads existing model-ready WASDE snapshot matrices from S3 and
writes local Phase 1 score artifacts. It does not train models, tune alert
thresholds, or write production S3 score tables.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys

import boto3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.config import load_env  # noqa: E402
from leviathan.model_datasets.wasde_snapshot_anomaly_scores import (  # noqa: E402
    build_wasde_snapshot_anomaly_scores,
)
from leviathan.storage.paths import (  # noqa: E402
    gold_model_ready_manifest_key,
    gold_model_ready_matrix_key,
)

DEFAULT_BUCKET = "leviathan-dev-shahem-001"
DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL_DATASET_VERSION = "20260629T132008Z_phase3_wasde_snapshot_model_ready"
DEFAULT_DATASET_KEY = "corn_wasde_snapshot_solo"
DEFAULT_COMMODITY = "corn_cbot"
DEFAULT_TARGET_KEYS = "psd_stock_to_use_anomaly_pct,psd_ending_stocks_anomaly_pct"
DEFAULT_OUTPUT_DIR = "data/phase_wasde_snapshot/anomaly_detection"


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(part.strip() for part in str(raw).split(",") if part.strip())


def _read_parquet_key(s3, bucket: str, key: str) -> pd.DataFrame:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def _read_json_key(s3, bucket: str, key: str) -> dict:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return json.loads(body.decode("utf-8"))


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def _write_parquet(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return str(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--aws-region", default=DEFAULT_REGION, dest="aws_region")
    parser.add_argument(
        "--model-dataset-version",
        default=DEFAULT_MODEL_DATASET_VERSION,
        dest="model_dataset_version",
    )
    parser.add_argument("--dataset-key", default=DEFAULT_DATASET_KEY, dest="dataset_key")
    parser.add_argument("--commodity", default=DEFAULT_COMMODITY)
    parser.add_argument("--target-keys", default=DEFAULT_TARGET_KEYS, dest="target_keys")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, dest="output_dir")
    parser.add_argument("--min-prior-observations", type=int, default=10)
    parser.add_argument("--min-composite-components", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    load_env()
    args = _parse_args()
    target_keys = _parse_csv(args.target_keys)
    if not target_keys:
        raise ValueError("--target-keys must contain at least one target")

    s3 = boto3.client("s3", region_name=args.aws_region)
    frames: list[pd.DataFrame] = []
    matrix_uris: dict[str, str] = {}
    for target_key in target_keys:
        key = gold_model_ready_matrix_key(
            args.model_dataset_version,
            args.dataset_key,
            args.commodity,
            target_key,
        )
        frames.append(_read_parquet_key(s3, args.bucket, key))
        matrix_uris[target_key] = f"s3://{args.bucket}/{key}"
    matrix = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    manifest_key = gold_model_ready_manifest_key(args.model_dataset_version)
    manifest = _read_json_key(s3, args.bucket, manifest_key)
    result = build_wasde_snapshot_anomaly_scores(
        matrix,
        min_prior_observations=args.min_prior_observations,
        min_composite_components=args.min_composite_components,
    )
    report = {
        **result.report,
        "inputs": {
            "bucket": args.bucket,
            "model_dataset_version": args.model_dataset_version,
            "dataset_key": args.dataset_key,
            "commodity": args.commodity,
            "target_keys": list(target_keys),
            "matrix_uris": matrix_uris,
            "manifest_uri": f"s3://{args.bucket}/{manifest_key}",
            "source_gold_dataset_version": manifest.get("source_dataset_version"),
        },
    }

    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    output_dir = Path(args.output_dir)
    outputs = {
        "snapshot_scores": _write_parquet(
            output_dir / "phase1_snapshot_scores.parquet",
            result.scores,
        ),
        "score_coverage": _write_parquet(
            output_dir / "phase1_score_coverage.parquet",
            result.score_coverage,
        ),
        "detector_report": _write_json(
            output_dir / "phase1_detector_report.json",
            report,
        ),
    }
    print(json.dumps({"report": report, "outputs": outputs}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
