"""Evaluate local Phase 1 WASDE snapshot anomaly-score artifacts.

The utility reads Phase 1 transparent scores from local disk, joins them to the
immutable model-ready snapshot matrices, and writes local Phase 2 backtest,
baseline, false-case, and component-diagnostic artifacts.
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
from leviathan.model_datasets.wasde_snapshot_anomaly_diagnostics import (  # noqa: E402
    build_composite_dominance_report,
    build_redundant_feature_family_report,
    build_score_component_clusters,
    build_score_component_correlation,
    build_score_missingness_diagnostics,
)
from leviathan.model_datasets.wasde_snapshot_anomaly_eval import (  # noqa: E402
    evaluate_wasde_snapshot_anomaly_scores,
)
from leviathan.model_datasets.wasde_snapshot_anomaly_rca import (  # noqa: E402
    build_false_case_tables,
)
from leviathan.storage.paths import gold_model_ready_matrix_key  # noqa: E402

DEFAULT_BUCKET = "leviathan-dev-shahem-001"
DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL_DATASET_VERSION = "20260629T132008Z_phase3_wasde_snapshot_model_ready"
DEFAULT_DATASET_KEY = "corn_wasde_snapshot_solo"
DEFAULT_COMMODITY = "corn_cbot"
DEFAULT_TARGET_KEYS = "psd_stock_to_use_anomaly_pct,psd_ending_stocks_anomaly_pct"
DEFAULT_INPUT_SCORES = (
    "data/phase_wasde_snapshot/anomaly_detection/phase1_snapshot_scores.parquet"
)
DEFAULT_OUTPUT_DIR = "data/phase_wasde_snapshot/anomaly_detection"


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(part.strip() for part in str(raw).split(",") if part.strip())


def _read_parquet_key(s3, bucket: str, key: str) -> pd.DataFrame:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
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
    parser.add_argument("--input-scores", default=DEFAULT_INPUT_SCORES, dest="input_scores")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, dest="output_dir")
    parser.add_argument("--min-train-years", type=int, default=10, dest="min_train_years")
    parser.add_argument("--threshold-quantiles", default="0.50,0.60,0.70,0.80,0.90")
    parser.add_argument(
        "--threshold-policy",
        default="legacy_f2",
        choices=("legacy_f2", "precision_guarded_f2", "recall_with_fp_budget"),
    )
    parser.add_argument("--min-precision", type=float, default=0.0)
    parser.add_argument("--max-false-positive-rate", type=float, default=1.0)
    parser.add_argument("--min-persistent-releases", type=int, default=1)
    parser.add_argument(
        "--detector-threshold-floor-json",
        default="{}",
        help="JSON object such as {\"revision_streak\": 2.0}",
    )
    parser.add_argument(
        "--detector-threshold-floors",
        default="",
        help="Comma-separated detector floors, e.g. revision_streak=2,stage_level_z=1.5",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    load_env()
    args = _parse_args()
    target_keys = _parse_csv(args.target_keys)
    quantiles = tuple(float(value) for value in _parse_csv(args.threshold_quantiles))
    if args.detector_threshold_floors:
        detector_threshold_floors = {}
        for item in _parse_csv(args.detector_threshold_floors):
            key, sep, value = item.partition("=")
            if not sep:
                raise ValueError(
                    "--detector-threshold-floors entries must look like detector=value"
                )
            detector_threshold_floors[key.strip()] = float(value)
    else:
        detector_threshold_floors = json.loads(args.detector_threshold_floor_json)
    if not isinstance(detector_threshold_floors, dict):
        raise ValueError("--detector-threshold-floor-json must be a JSON object")
    if not target_keys:
        raise ValueError("--target-keys must contain at least one target")

    scores_path = Path(args.input_scores)
    if not scores_path.exists():
        raise FileNotFoundError(f"missing local Phase 1 scores: {scores_path}")
    scores = pd.read_parquet(scores_path)

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

    result = evaluate_wasde_snapshot_anomaly_scores(
        scores,
        matrix,
        min_train_years=args.min_train_years,
        candidate_quantiles=quantiles,
        threshold_policy=args.threshold_policy,
        min_precision=args.min_precision,
        max_false_positive_rate=args.max_false_positive_rate,
        min_persistent_releases=args.min_persistent_releases,
        detector_threshold_floors={
            str(key): float(value)
            for key, value in detector_threshold_floors.items()
        },
    )
    missingness = build_score_missingness_diagnostics(scores)
    correlations = build_score_component_correlation(scores)
    clusters = build_score_component_clusters(correlations)
    redundant = build_redundant_feature_family_report(scores)
    dominance = build_composite_dominance_report(scores)
    false_negatives, false_positives = build_false_case_tables(result.annual_alert_cases)

    report = {
        **result.report,
        "inputs": {
            "bucket": args.bucket,
            "model_dataset_version": args.model_dataset_version,
            "dataset_key": args.dataset_key,
            "commodity": args.commodity,
            "target_keys": list(target_keys),
            "matrix_uris": matrix_uris,
            "scores_path": str(scores_path),
        },
        "diagnostics": {
            "missingness_rows": int(len(missingness)),
            "correlation_rows": int(len(correlations)),
            "cluster_rows": int(len(clusters)),
            "redundant_family_rows": int(len(redundant)),
            "dominance_rows": int(len(dominance)),
            "false_negative_count": int(len(false_negatives)),
            "false_positive_count": int(len(false_positives)),
        },
    }

    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return

    output_dir = Path(args.output_dir)
    outputs = {
        "backtest_report": _write_json(output_dir / "phase2_backtest_report.json", report),
        "fold_metrics": _write_parquet(output_dir / "phase2_fold_metrics.parquet", result.fold_metrics),
        "thresholds": _write_parquet(output_dir / "phase2_thresholds.parquet", result.thresholds),
        "oof_predictions": _write_parquet(output_dir / "phase2_oof_predictions.parquet", result.oof_predictions),
        "baseline_comparison": _write_parquet(output_dir / "phase2_baseline_comparison.parquet", result.baseline_comparison),
        "false_negatives": _write_parquet(output_dir / "phase2_false_negatives.parquet", false_negatives),
        "false_positives": _write_parquet(output_dir / "phase2_false_positives.parquet", false_positives),
        "score_missingness": _write_parquet(output_dir / "phase2_score_missingness.parquet", missingness),
        "component_correlations": _write_parquet(output_dir / "phase2_component_correlations.parquet", correlations),
        "component_clusters": _write_parquet(output_dir / "phase2_component_clusters.parquet", clusters),
        "redundant_feature_families": _write_parquet(output_dir / "phase2_redundant_feature_families.parquet", redundant),
        "composite_dominance": _write_parquet(output_dir / "phase2_composite_dominance.parquet", dominance),
    }
    print(json.dumps({"report": report, "outputs": outputs}, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
