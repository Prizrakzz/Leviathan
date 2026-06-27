"""Build a Phase 10 leaderboard from candidate certification reports."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from leviathan.common.config import get_required_env, load_env                 # noqa: E402
from leviathan.storage.metadata import utc_now_iso                             # noqa: E402
from leviathan.storage.paths import model_candidate_certification_summary_key   # noqa: E402
from leviathan.training.certification_summary import certification_ranking_frame  # noqa: E402


def _list_report_keys(s3, bucket: str, prefix: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = str(item["Key"])
            if key.endswith("/certification_report.json"):
                keys.append(key)
    return sorted(keys)


def _read_report(s3, bucket: str, key: str) -> dict:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    report = json.loads(body.decode("utf-8"))
    report.setdefault("inputs", {})["certification_report_uri"] = f"s3://{bucket}/{key}"
    return report


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(
        description="Summarize Phase 10 candidate certification reports."
    )
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--aws-region", default=None, dest="aws_region")
    parser.add_argument(
        "--prefix",
        default="model_artifacts/candidate_certification/",
        help="S3 prefix containing candidate_id=*/certification_report.json objects.",
    )
    parser.add_argument("--output-local", default="", dest="output_local")
    parser.add_argument("--output-s3-key", default="", dest="output_s3_key")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    s3 = boto3.client("s3", region_name=aws_region)

    keys = _list_report_keys(s3, bucket, args.prefix)
    if args.limit and args.limit > 0:
        keys = keys[:args.limit]
    reports = [_read_report(s3, bucket, key) for key in keys]
    ranking = certification_ranking_frame(reports)

    print(ranking.to_string(index=False, max_rows=50))
    print(json.dumps({"report_count": len(reports), "row_count": int(len(ranking))}, indent=2))

    if args.output_local:
        output_path = Path(args.output_local)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".csv":
            ranking.to_csv(output_path, index=False)
        else:
            ranking.to_parquet(output_path, index=False)

    if args.output_s3_key:
        key = args.output_s3_key
        if key.lower() in {"auto", "default"}:
            run_id = utc_now_iso().replace(":", "").replace("-", "")
            key = model_candidate_certification_summary_key(run_id)
        buffer = io.BytesIO()
        ranking.to_parquet(buffer, index=False)
        s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
        print(json.dumps({"output_s3_uri": f"s3://{bucket}/{key}"}, indent=2))


if __name__ == "__main__":
    main()
