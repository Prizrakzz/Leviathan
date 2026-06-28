"""Build a read-only PSD/WASDE source truth audit for model-ready planning."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import boto3
import pandas as pd


DEFAULT_BUCKET = "leviathan-dev-shahem-001"
DEFAULT_REGION = "us-east-1"
DEFAULT_PSD_KEY = "silver/psd/part-000.parquet"
DEFAULT_WASDE_PREFIX = "silver/wasde/"


def _list_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(str(obj["Key"]) for obj in page.get("Contents", []))
    return sorted(keys)


def _read_parquet_key(s3, bucket: str, key: str) -> pd.DataFrame:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def _read_parquet_prefix(s3, bucket: str, prefix: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for key in _list_keys(s3, bucket, prefix):
        if key.endswith(".parquet"):
            frame = _read_parquet_key(s3, bucket, key)
            if not frame.empty:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _prefix_summary(s3, bucket: str, prefix: str) -> dict:
    keys = _list_keys(s3, bucket, prefix)
    parquet_keys = [key for key in keys if key.endswith(".parquet")]
    return {
        "prefix": prefix,
        "object_count": len(keys),
        "parquet_count": len(parquet_keys),
        "sample_keys": keys[:5],
    }


def _psd_summary(psd: pd.DataFrame) -> dict:
    out = {
        "row_count": int(len(psd)),
        "columns": sorted(str(col) for col in psd.columns),
        "release_date_count": 0,
        "release_dates": [],
        "duplicate_source_key_count": None,
    }
    if psd.empty:
        return out
    if "release_date" in psd.columns:
        releases = sorted(psd["release_date"].dropna().astype(str).unique())
        out["release_date_count"] = len(releases)
        out["release_dates"] = releases[:20]
    key_cols = [
        col for col in ("leviathan_slug", "country", "market_year") if col in psd.columns
    ]
    if len(key_cols) == 3:
        counts = psd.groupby(key_cols, dropna=False).size()
        out["duplicate_source_key_count"] = int((counts > 1).sum())
        out["max_rows_per_source_key"] = int(counts.max()) if not counts.empty else 0
    return out


def _wasde_summary(wasde: pd.DataFrame) -> dict:
    out = {
        "row_count": int(len(wasde)),
        "columns": sorted(str(col) for col in wasde.columns),
        "release_date_count": 0,
        "release_date_min": None,
        "release_date_max": None,
        "non_null_revision_rows": 0,
        "commodities": [],
        "attributes": [],
    }
    if wasde.empty:
        return out
    if "release_date" in wasde.columns:
        releases = pd.to_datetime(wasde["release_date"], errors="coerce").dropna()
        out["release_date_count"] = int(releases.nunique())
        if not releases.empty:
            out["release_date_min"] = releases.min().date().isoformat()
            out["release_date_max"] = releases.max().date().isoformat()
    if "revision" in wasde.columns:
        out["non_null_revision_rows"] = int(
            pd.to_numeric(wasde["revision"], errors="coerce").notna().sum()
        )
    if "commodity" in wasde.columns:
        out["commodities"] = sorted(wasde["commodity"].dropna().astype(str).unique())[:50]
    if "attribute" in wasde.columns:
        out["attributes"] = sorted(wasde["attribute"].dropna().astype(str).unique())[:50]
    return out


def build_audit(bucket: str, region: str, psd_key: str, wasde_prefix: str) -> dict:
    s3 = boto3.client("s3", region_name=region)
    psd = _read_parquet_key(s3, bucket, psd_key)
    wasde = _read_parquet_prefix(s3, bucket, wasde_prefix)
    return {
        "bucket": bucket,
        "region": region,
        "prefixes": {
            "psd_raw": _prefix_summary(s3, bucket, "raw/production/source=usda_psd/"),
            "psd_bronze": _prefix_summary(s3, bucket, "bronze/production/source=usda_psd/"),
            "psd_silver": _prefix_summary(s3, bucket, "silver/psd/"),
            "wasde_silver": _prefix_summary(s3, bucket, wasde_prefix),
        },
        "psd_silver": _psd_summary(psd),
        "wasde_silver": _wasde_summary(wasde),
        "conclusion": {
            "psd_monthly_revision_signal_available": False,
            "psd_reason": (
                "Current raw/bronze/silver PSD lake contains one 2026-05-20 "
                "bulk release and one silver row per slug/country/market_year, "
                "so it cannot support true month-over-month PSD revision features."
            ),
            "wasde_monthly_revision_signal_available": True,
            "wasde_reason": (
                "WASDE silver is partitioned by release_date and carries prior_estimate, "
                "revision, and revision_direction columns suitable for point-in-time "
                "revision features."
            ),
        },
    }


def _write_outputs(audit: dict, output_json: Path | None, output_parquet: Path | None) -> None:
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    if output_parquet is not None:
        output_parquet.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for source, summary in audit.get("prefixes", {}).items():
            rows.append({"section": "prefix", "name": source, **summary})
        rows.append({"section": "psd_silver", "name": "silver/psd", **audit["psd_silver"]})
        rows.append({"section": "wasde_silver", "name": "silver/wasde", **audit["wasde_silver"]})
        pd.DataFrame(rows).to_parquet(output_parquet, index=False)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--aws-region", default=DEFAULT_REGION, dest="aws_region")
    parser.add_argument("--psd-key", default=DEFAULT_PSD_KEY, dest="psd_key")
    parser.add_argument("--wasde-prefix", default=DEFAULT_WASDE_PREFIX, dest="wasde_prefix")
    parser.add_argument("--output-json", default=None, dest="output_json")
    parser.add_argument("--output-parquet", default=None, dest="output_parquet")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    audit = build_audit(args.bucket, args.aws_region, args.psd_key, args.wasde_prefix)
    _write_outputs(
        audit,
        Path(args.output_json) if args.output_json else None,
        Path(args.output_parquet) if args.output_parquet else None,
    )
    print(json.dumps(audit["conclusion"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
