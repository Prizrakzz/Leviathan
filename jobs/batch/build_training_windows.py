"""Build the per-(commodity, tier) training-window manifest from gold matrices.

Reads every ``gold/feature_matrix/commodity={slug}/part-0.parquet``, applies the
named tiers in ``configs/features/feature_tiers.yaml`` via
``leviathan.features.windows``, and writes:

  gold/training_windows/training_windows.parquet   — one row per (commodity, tier)
  gold/training_windows/training_windows.md         — human-readable summary

Run after a spine fan-out completes (it reads gold, so it needs no image of its
own — runs anywhere with bucket access):

    python jobs/batch/build_training_windows.py --bucket leviathan-dev-shahem-001

A training script then picks a (commodity, tier) row to get its window and
feeds the matching feature columns to leviathan.training.cv.walk_forward_cv.
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import boto3
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.features.windows import compute_training_windows  # noqa: E402

_MATRIX_PREFIX = "gold/feature_matrix/"
_MATRIX_VERSION_PREFIX = "gold/feature_matrix_versions/"
_OUT_PREFIX = "gold/training_windows/"
_OUT_VERSION_PREFIX = "gold/training_windows_versions/"
_TIERS = Path(__file__).resolve().parents[2] / "configs" / "features" / "feature_tiers.yaml"


def _matrix_prefix(dataset_version: str | None = None) -> str:
    if dataset_version:
        return f"{_MATRIX_VERSION_PREFIX}dataset_version={dataset_version}/"
    return _MATRIX_PREFIX


def _out_prefix(dataset_version: str | None = None) -> str:
    if dataset_version:
        return f"{_OUT_VERSION_PREFIX}dataset_version={dataset_version}/"
    return _OUT_PREFIX


def _list_commodities(s3, bucket: str, dataset_version: str | None = None) -> list[str]:
    out: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=_matrix_prefix(dataset_version), Delimiter="/"):
        for pre in page.get("CommonPrefixes", []):
            slug = pre["Prefix"].split("commodity=")[-1].rstrip("/")
            if slug:
                out.append(slug)
    return sorted(out)


def _read_matrix(
    s3,
    bucket: str,
    commodity: str,
    dataset_version: str | None = None,
) -> pd.DataFrame | None:
    paginator = s3.get_paginator("list_objects_v2")
    prefix = f"{_matrix_prefix(dataset_version)}commodity={commodity}/"
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".parquet"):
                body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
                return pd.read_parquet(io.BytesIO(body))
    return None


def _to_markdown(df: pd.DataFrame) -> str:
    lines = ["# Training windows (per commodity × tier)", ""]
    for commodity, g in df.groupby("commodity"):
        lines.append(f"## {commodity}")
        lines.append("")
        lines.append("| tier | features | label window | dense window |")
        lines.append("|---|---|---|---|")
        for _, r in g.iterrows():
            lw = (f"{r.label_first_year}-{r.label_last_year} ({r.n_label_years}y)"
                  if pd.notna(r.label_first_year) else "— (no labels)")
            dw = (f"{r.dense_start_year}-{r.label_last_year} ({r.dense_window_years}y)"
                  if pd.notna(r.dense_start_year) else "—")
            lines.append(f"| {r.tier} | {int(r.n_features)} | {lw} | {dw} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the training-window manifest.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--aws-region", default="us-east-1", dest="aws_region")
    parser.add_argument(
        "--dataset-version", default=None, dest="dataset_version",
        help="Read gold/feature_matrix_versions/dataset_version=... instead of mutable latest.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.aws_region)
    tiers_config = yaml.safe_load(_TIERS.read_text(encoding="utf-8"))

    commodities = _list_commodities(s3, args.bucket, args.dataset_version)
    frames = []
    for c in commodities:
        m = _read_matrix(s3, args.bucket, c, args.dataset_version)
        if m is None or m.empty:
            print(f"  {c}: no matrix, skipped")
            continue
        frames.append(compute_training_windows(m, tiers_config, c))
        print(f"  {c}: {len(m)} rows, {m.shape[1]} cols")

    if not frames:
        raise SystemExit("No feature matrices found — run the spine fan-out first.")

    manifest = pd.concat(frames, ignore_index=True)
    print(f"\nComputed {len(manifest)} (commodity, tier) windows across {len(frames)} commodities.")

    if args.dry_run:
        with pd.option_context("display.width", 200, "display.max_rows", 200):
            print(manifest.to_string(index=False))
        return

    buf = io.BytesIO()
    manifest.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    out_prefix = _out_prefix(args.dataset_version)
    s3.put_object(Bucket=args.bucket, Key=f"{out_prefix}training_windows.parquet", Body=buf.getvalue())
    s3.put_object(Bucket=args.bucket, Key=f"{out_prefix}training_windows.md",
                  Body=_to_markdown(manifest).encode("utf-8"))
    print(f"Wrote s3://{args.bucket}/{out_prefix}training_windows.parquet (+ .md)")


if __name__ == "__main__":
    main()
