"""Build Phase 3 RCA artifacts for WASDE snapshot anomaly detectors."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.model_datasets.wasde_snapshot_anomaly_rca import (  # noqa: E402
    build_annual_alert_cases,
    build_detector_rca_summary,
    build_false_case_tables,
    build_rca_reason_summary,
    build_threshold_stability_report,
    recommend_phase4_decision,
)

DEFAULT_INPUT_DIR = "data/phase_wasde_snapshot/anomaly_detection"
DEFAULT_OUTPUT_DIR = "data/phase_wasde_snapshot/anomaly_detection/phase3_rca"
DEFAULT_MARKDOWN = "docs/WASDE_SNAPSHOT_ANOMALY_DETECTOR_RCA.md"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR, dest="input_dir")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, dest="output_dir")
    parser.add_argument("--markdown", default=DEFAULT_MARKDOWN)
    parser.add_argument("--title", default="WASDE Snapshot Anomaly Detector RCA")
    parser.add_argument("--phase-name", default="wasde_snapshot_anomaly_phase3_rca", dest="phase_name")
    parser.add_argument("--phase-label", default="Phase 3")
    parser.add_argument("--top-n", type=int, default=25, dest="top_n")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing required Phase 2 artifact: {path}")
    return pd.read_parquet(path)


def _write_parquet(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return str(path)


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return str(path)


def _markdown_table(frame: pd.DataFrame, columns: list[str], *, limit: int = 12) -> str:
    if frame.empty:
        return "_No rows._"
    view = frame.reindex(columns=columns).head(limit).copy()
    for col in view.columns:
        view[col] = view[col].map(lambda value: "" if pd.isna(value) else str(value))
    header = "| " + " | ".join(view.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(view.columns)) + " |"
    rows = [
        "| " + " | ".join(str(row[col]) for col in view.columns) + " |"
        for _, row in view.iterrows()
    ]
    return "\n".join([header, sep, *rows])


def _build_markdown(
    *,
    title: str,
    phase_label: str,
    report: dict,
    detector_summary: pd.DataFrame,
    threshold_stability: pd.DataFrame,
    reason_summary: pd.DataFrame,
    false_negatives: pd.DataFrame,
    false_positives: pd.DataFrame,
    composite_dominance: pd.DataFrame,
    top_n: int,
) -> str:
    decision = report["decision"]
    lines = [
        f"# {title}",
        "",
        "## Executive Summary",
        "",
        f"{phase_label} reviewed the transparent detector backtest. The detector path is not ready for ML/meta-models yet if false positives remain high, but the transparent WASDE scores do contain useful early-warning signal when recall survives stricter threshold policy.",
        "",
        f"- Recommended next decision: `{decision['decision']}`",
        f"- Reason: `{decision['reason']}`",
        f"- Best detector: `{decision.get('best_detector_id', '')}` on `{decision.get('best_target_key', '')}`",
        f"- Best mean recall: `{decision.get('best_mean_recall')}`",
        f"- Best mean F2: `{decision.get('best_mean_f2')}`",
        f"- Total false positives: `{decision.get('false_positive_count')}`",
        f"- Total false negatives: `{decision.get('false_negative_count')}`",
        "",
        "Interpretation: high recall is real enough to keep going, but threshold policy and revision-streak overfiring need repair before adding broader context or tree models.",
        "",
        "## Detector Summary",
        "",
        _markdown_table(
            detector_summary,
            [
                "target_key",
                "detector_id",
                "event_count",
                "true_positive_count",
                "false_negative_count",
                "false_positive_count",
                "mean_recall",
                "mean_f2",
                "mean_top20_precision",
            ],
            limit=top_n,
        ),
        "",
        "## RCA Reason Summary",
        "",
        _markdown_table(
            reason_summary,
            ["case_type", "target_key", "detector_id", "rca_reason_code", "case_count"],
            limit=top_n,
        ),
        "",
        "## Threshold Stability",
        "",
        _markdown_table(
            threshold_stability,
            [
                "target_key",
                "detector_id",
                "fold_count",
                "threshold_min",
                "threshold_median",
                "threshold_max",
                "threshold_std",
            ],
            limit=top_n,
        ),
        "",
        "## Composite Dominance",
        "",
        _markdown_table(
            composite_dominance,
            [
                "target_key",
                "top_attribute",
                "top_attribute_contribution_share",
                "top_feature",
                "top_feature_contribution_share",
                "effective_component_count",
            ],
            limit=top_n,
        ),
        "",
        "## Top False Negatives",
        "",
        _markdown_table(
            false_negatives.sort_values("max_score", ascending=False),
            [
                "target_key",
                "detector_id",
                "origin_key",
                "target_market_year",
                "max_score",
                "threshold",
                "score_threshold_margin",
                "rca_reason_code",
            ],
            limit=top_n,
        ),
        "",
        "## Top False Positives",
        "",
        _markdown_table(
            false_positives.sort_values("max_score", ascending=False),
            [
                "target_key",
                "detector_id",
                "origin_key",
                "target_market_year",
                "first_alert_stage",
                "max_score",
                "threshold",
                "score_threshold_margin",
                "rca_reason_code",
            ],
            limit=top_n,
        ),
        "",
        "## Phase 4 Implication",
        "",
        "Do not jump to LightGBM/XGBoost yet. First tighten threshold policy, especially for revision streaks, then rerun Phase 2. If false positives remain high but economically plausible, Phase 4 should add substitute/context surfaces and compare whether broader WASDE context reduces noisy alerts.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    args = _parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    markdown_path = Path(args.markdown)

    fold_metrics = _read_parquet(input_dir / "phase2_fold_metrics.parquet")
    thresholds = _read_parquet(input_dir / "phase2_thresholds.parquet")
    oof = _read_parquet(input_dir / "phase2_oof_predictions.parquet")
    composite_dominance = _read_parquet(input_dir / "phase2_composite_dominance.parquet")

    annual_cases = build_annual_alert_cases(oof)
    false_negatives, false_positives = build_false_case_tables(annual_cases)
    detector_summary = build_detector_rca_summary(fold_metrics)
    threshold_stability = build_threshold_stability_report(thresholds)
    reason_summary = build_rca_reason_summary(false_negatives, false_positives)
    decision = recommend_phase4_decision(detector_summary, reason_summary)

    report = {
        "phase": args.phase_name,
        "status": "complete",
        "decision": decision,
        "counts": {
            "annual_case_count": int(len(annual_cases)),
            "false_negative_count": int(len(false_negatives)),
            "false_positive_count": int(len(false_positives)),
            "detector_summary_rows": int(len(detector_summary)),
            "threshold_stability_rows": int(len(threshold_stability)),
            "reason_summary_rows": int(len(reason_summary)),
        },
    }

    markdown = _build_markdown(
        title=args.title,
        phase_label=args.phase_label,
        report=report,
        detector_summary=detector_summary,
        threshold_stability=threshold_stability,
        reason_summary=reason_summary,
        false_negatives=false_negatives,
        false_positives=false_positives,
        composite_dominance=composite_dominance,
        top_n=args.top_n,
    )

    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return

    outputs = {
        "phase3_report": _write_json(output_dir / "phase3_rca_report.json", report),
        "annual_cases": _write_parquet(output_dir / "phase3_annual_alert_cases.parquet", annual_cases),
        "false_negatives": _write_parquet(output_dir / "phase3_false_negatives.parquet", false_negatives),
        "false_positives": _write_parquet(output_dir / "phase3_false_positives.parquet", false_positives),
        "detector_summary": _write_parquet(output_dir / "phase3_detector_summary.parquet", detector_summary),
        "threshold_stability": _write_parquet(output_dir / "phase3_threshold_stability.parquet", threshold_stability),
        "reason_summary": _write_parquet(output_dir / "phase3_reason_summary.parquet", reason_summary),
    }
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    outputs["markdown"] = str(markdown_path)
    print(json.dumps({"report": report, "outputs": outputs}, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
