"""Build Phase 5 root-cause audit artifacts for WASDE anomaly detectors."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.model_datasets.wasde_snapshot_anomaly_phase5 import (  # noqa: E402
    build_event_label_audit,
    build_false_positive_severity_cases,
    build_revision_streak_audit,
    build_score_scale_audit,
    build_stage_normalization_audit,
    build_threshold_tradeoff_audit,
    recommend_phase5_decision,
)
from leviathan.model_datasets.wasde_snapshot_anomaly_rca import (  # noqa: E402
    build_annual_alert_cases,
)

DEFAULT_INPUT_DIR = "data/phase_wasde_snapshot/anomaly_detection/phase4_threshold_repair"
DEFAULT_OUTPUT_DIR = "data/phase_wasde_snapshot/anomaly_detection/phase5_root_cause_audit"
DEFAULT_MARKDOWN = "docs/WASDE_SNAPSHOT_ANOMALY_PHASE5_ROOT_CAUSE_AUDIT.md"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR, dest="input_dir")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, dest="output_dir")
    parser.add_argument("--markdown", default=DEFAULT_MARKDOWN)
    parser.add_argument("--title", default="WASDE Snapshot Anomaly Phase 5 Root-Cause Audit")
    parser.add_argument("--phase-label", default="Phase 5", dest="phase_label")
    parser.add_argument(
        "--phase-name",
        default="wasde_snapshot_anomaly_phase5_root_cause_audit",
        dest="phase_name",
    )
    parser.add_argument("--soft-stress-ratio", type=float, default=0.75)
    parser.add_argument("--weak-stress-ratio", type=float, default=0.50)
    parser.add_argument("--top-n", type=int, default=20, dest="top_n")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing required backtest artifact: {path}")
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
    event_audit: pd.DataFrame,
    false_positive_severity: pd.DataFrame,
    stage_audit: pd.DataFrame,
    score_scale_audit: pd.DataFrame,
    revision_streak_audit: pd.DataFrame,
    threshold_tradeoff: pd.DataFrame,
    top_n: int,
) -> str:
    decision = report["decision"]
    lines = [
        f"# {title}",
        "",
        "## Executive Summary",
        "",
        f"{phase_label} audits the detector output before any more ML sweeps. It asks whether poor behavior is coming from target-label design, unstable score normalization, revision-streak mechanics, or threshold policy.",
        "",
        f"- Recommended next step: `{decision['decision']}`",
        f"- Blockers: `{', '.join(decision.get('blockers', [])) or 'none'}`",
        f"- Stage normalization issue rows: `{decision.get('stage_issue_count')}`",
        f"- Revision-streak issue rows: `{decision.get('revision_streak_issue_count')}`",
        f"- Event-definition issue rows: `{decision.get('event_definition_issue_count')}`",
        f"- Threshold-policy issue rows: `{decision.get('threshold_policy_issue_count')}`",
        "",
        "Interpretation: this is a go/no-go diagnostic layer. A blocker here means we should repair the transparent detector or event definition before promoting the scores into LightGBM/XGBoost meta-model experiments.",
        "",
        "## Event Label Audit",
        "",
        _markdown_table(
            event_audit,
            [
                "target_key",
                "detector_id",
                "false_positive_count",
                "false_negative_count",
                "soft_stress_false_positive_count",
                "weak_stress_false_positive_count",
                "benign_false_positive_count",
                "near_miss_false_positive_share",
                "event_definition_diagnosis",
            ],
            limit=top_n,
        ),
        "",
        "## Stage Normalization Audit",
        "",
        _markdown_table(
            stage_audit,
            [
                "target_key",
                "detector_id",
                "threshold_median",
                "threshold_max",
                "threshold_std",
                "absurd_threshold_count",
                "threshold_cap",
                "normalization_diagnosis",
            ],
            limit=top_n,
        ),
        "",
        "## Score Scale Audit",
        "",
        _markdown_table(
            score_scale_audit,
            [
                "target_key",
                "detector_id",
                "score_q95",
                "score_q99",
                "score_max",
                "extreme_score_count",
                "score_cap",
                "score_scale_diagnosis",
            ],
            limit=top_n,
        ),
        "",
        "## Revision Streak Audit",
        "",
        _markdown_table(
            revision_streak_audit,
            [
                "target_key",
                "false_positive_count",
                "false_negative_count",
                "soft_stress_false_positive_count",
                "benign_false_positive_count",
                "mean_raw_alerts_per_case",
                "mean_final_alerts_per_case",
                "revision_streak_diagnosis",
            ],
            limit=top_n,
        ),
        "",
        "## Threshold Tradeoff Audit",
        "",
        _markdown_table(
            threshold_tradeoff,
            [
                "target_key",
                "detector_id",
                "mean_fold_recall",
                "mean_fold_precision",
                "mean_fold_f2",
                "false_positive_count",
                "false_negative_count",
                "threshold_policy_diagnosis",
            ],
            limit=top_n,
        ),
        "",
        "## Top False-Positive Severity Cases",
        "",
        _markdown_table(
            false_positive_severity,
            [
                "target_key",
                "detector_id",
                "origin_key",
                "target_market_year",
                "stress_ratio_to_hard_threshold",
                "target_severity_band",
                "max_score",
                "threshold",
                "first_alert_stage",
            ],
            limit=top_n,
        ),
        "",
        f"## {phase_label} Implication",
        "",
        "Do not run broader model sweeps until the listed blockers are addressed. If event-definition pressure is high, add a watchlist/soft-stress label. If z-score scale is unstable, repair normalization with robust prior-only scaling or caps. If revision streak still overfires, require directional magnitude and cumulative revision confirmation.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    args = _parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    markdown_path = Path(args.markdown)

    oof = _read_parquet(input_dir / "phase2_oof_predictions.parquet")
    thresholds = _read_parquet(input_dir / "phase2_thresholds.parquet")
    fold_metrics = _read_parquet(input_dir / "phase2_fold_metrics.parquet")

    annual_cases = build_annual_alert_cases(oof)
    event_audit = build_event_label_audit(
        annual_cases,
        soft_stress_ratio=args.soft_stress_ratio,
        weak_stress_ratio=args.weak_stress_ratio,
    )
    false_positive_severity = build_false_positive_severity_cases(
        annual_cases,
        soft_stress_ratio=args.soft_stress_ratio,
        weak_stress_ratio=args.weak_stress_ratio,
    )
    stage_audit = build_stage_normalization_audit(thresholds)
    score_scale_audit = build_score_scale_audit(oof)
    revision_streak_audit = build_revision_streak_audit(
        oof,
        annual_cases,
        soft_stress_ratio=args.soft_stress_ratio,
        weak_stress_ratio=args.weak_stress_ratio,
    )
    threshold_tradeoff = build_threshold_tradeoff_audit(fold_metrics, thresholds)
    decision = recommend_phase5_decision(
        event_audit,
        stage_audit,
        revision_streak_audit,
        threshold_tradeoff,
    )
    report = {
        "phase": args.phase_name,
        "status": "complete",
        "parameters": {
            "soft_stress_ratio": float(args.soft_stress_ratio),
            "weak_stress_ratio": float(args.weak_stress_ratio),
        },
        "counts": {
            "annual_case_count": int(len(annual_cases)),
            "event_audit_rows": int(len(event_audit)),
            "false_positive_severity_rows": int(len(false_positive_severity)),
            "stage_audit_rows": int(len(stage_audit)),
            "score_scale_audit_rows": int(len(score_scale_audit)),
            "revision_streak_audit_rows": int(len(revision_streak_audit)),
            "threshold_tradeoff_rows": int(len(threshold_tradeoff)),
        },
        "decision": decision,
    }

    markdown = _build_markdown(
        title=args.title,
        phase_label=args.phase_label,
        report=report,
        event_audit=event_audit,
        false_positive_severity=false_positive_severity,
        stage_audit=stage_audit,
        score_scale_audit=score_scale_audit,
        revision_streak_audit=revision_streak_audit,
        threshold_tradeoff=threshold_tradeoff,
        top_n=args.top_n,
    )

    if args.dry_run:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return

    outputs = {
        "report": _write_json(output_dir / "phase5_report.json", report),
        "event_label_audit": _write_parquet(output_dir / "phase5_event_label_audit.parquet", event_audit),
        "false_positive_severity": _write_parquet(output_dir / "phase5_false_positive_severity.parquet", false_positive_severity),
        "stage_normalization_audit": _write_parquet(output_dir / "phase5_stage_normalization_audit.parquet", stage_audit),
        "score_scale_audit": _write_parquet(output_dir / "phase5_score_scale_audit.parquet", score_scale_audit),
        "revision_streak_audit": _write_parquet(output_dir / "phase5_revision_streak_audit.parquet", revision_streak_audit),
        "threshold_tradeoff_audit": _write_parquet(output_dir / "phase5_threshold_tradeoff_audit.parquet", threshold_tradeoff),
    }
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    outputs["markdown"] = str(markdown_path)
    print(json.dumps({"report": report, "outputs": outputs}, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
