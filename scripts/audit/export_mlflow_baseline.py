"""Freeze one existing MLflow run and its referenced artifacts as a baseline."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.audit.experiment_baseline import (  # noqa: E402
    baseline_prefix,
    build_baseline_record,
    source_artifacts_from_tags,
)
from leviathan.ops.ml_platform import canonical_json_bytes, sha256_bytes  # noqa: E402
from leviathan.ops.ssm import encoded_python_command, run_ssm_command  # noqa: E402


_REMOTE_EXPORT_SCRIPT = r'''
import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

payload = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
conn = sqlite3.connect(payload["database_path"])
conn.row_factory = sqlite3.Row

def one(query, params=()):
    row = conn.execute(query, params).fetchone()
    return dict(row) if row else None

def many(query, params=()):
    return [dict(row) for row in conn.execute(query, params).fetchall()]

try:
    run = one(
        "SELECT r.*, e.name AS experiment_name, e.artifact_location AS experiment_artifact_location "
        "FROM runs r JOIN experiments e ON r.experiment_id = e.experiment_id "
        "WHERE r.run_uuid = ?",
        (payload["run_id"],),
    )
    if run is None:
        raise SystemExit(f"MLflow run not found: {payload['run_id']}")
    metadata = {
        "run": run,
        "metrics": many(
            "SELECT key, value, timestamp, step, is_nan "
            "FROM latest_metrics WHERE run_uuid = ? ORDER BY key",
            (payload["run_id"],),
        ),
        "params": {
            row["key"]: row["value"]
            for row in many(
                "SELECT key, value FROM params WHERE run_uuid = ? ORDER BY key",
                (payload["run_id"],),
            )
        },
        "tags": {
            row["key"]: row["value"]
            for row in many(
                "SELECT key, value FROM tags WHERE run_uuid = ? ORDER BY key",
                (payload["run_id"],),
            )
        },
        "registered_model_versions": many(
            "SELECT name, version, current_stage, status, source "
            "FROM model_versions WHERE run_id = ? ORDER BY name, version",
            (payload["run_id"],),
        ),
    }
finally:
    conn.close()

data = json.dumps(metadata, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
temporary_path = None
try:
    with tempfile.NamedTemporaryFile(prefix="mlflow-baseline-", suffix=".json", delete=False) as handle:
        handle.write(data)
        temporary_path = handle.name
    upload = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error",
            "--upload-file", temporary_path, payload["upload_url"],
        ],
        capture_output=True,
        check=False,
    )
    if upload.returncode != 0:
        raise SystemExit(
            "metadata upload failed: "
            + upload.stderr.decode("utf-8", errors="replace")
        )
finally:
    if temporary_path:
        os.unlink(temporary_path)
print(json.dumps({"run_id": payload["run_id"], "bytes": len(data)}, sort_keys=True))
'''


def object_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except s3.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline-id", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--bucket", default=os.getenv("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--mlflow-database-path",
        default="/home/ec2-user/mlflow/mlflow.db",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.bucket:
        raise SystemExit("--bucket or LEVIATHAN_BUCKET is required")

    s3 = boto3.client("s3", region_name=args.aws_region)
    prefix = baseline_prefix(args.baseline_id)
    record_key = f"{prefix}/baseline_record.json"
    if object_exists(s3, args.bucket, record_key):
        raise FileExistsError(
            f"refusing to overwrite frozen baseline s3://{args.bucket}/{record_key}"
        )

    metadata_key = f"{prefix}/run_metadata.json"
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": args.bucket, "Key": metadata_key},
        ExpiresIn=900,
    )
    run_ssm_command(
        instance_id=args.instance_id,
        command=encoded_python_command(_REMOTE_EXPORT_SCRIPT, {
            "run_id": args.run_id,
            "database_path": args.mlflow_database_path,
            "upload_url": upload_url,
        }),
        aws_region=args.aws_region,
        timeout_seconds=300,
    )
    run_metadata_bytes = s3.get_object(
        Bucket=args.bucket, Key=metadata_key
    )["Body"].read()
    run_metadata = json.loads(run_metadata_bytes)
    if run_metadata["run"]["run_uuid"] != args.run_id:
        raise RuntimeError("exported MLflow metadata belongs to the wrong run")

    copied: list[dict] = [{
        "name": "run_metadata.json",
        "source_uri": None,
        "frozen_uri": f"s3://{args.bucket}/{metadata_key}",
        "size_bytes": len(run_metadata_bytes),
        "sha256": sha256_bytes(run_metadata_bytes),
    }]
    for artifact in source_artifacts_from_tags(run_metadata["tags"]):
        body = s3.get_object(
            Bucket=artifact["source_bucket"],
            Key=artifact["source_key"],
        )["Body"].read()
        target_key = f"{prefix}/{artifact['filename']}"
        s3.put_object(Bucket=args.bucket, Key=target_key, Body=body)
        copied.append({
            "name": artifact["filename"],
            "source_tag": artifact["tag"],
            "source_uri": artifact["source_uri"],
            "frozen_uri": f"s3://{args.bucket}/{target_key}",
            "size_bytes": len(body),
            "sha256": sha256_bytes(body),
        })

    artifact_uri = run_metadata["run"].get("artifact_uri")
    mlflow_artifact_objects = []
    if artifact_uri and artifact_uri.startswith(f"s3://{args.bucket}/"):
        artifact_prefix = artifact_uri.split(f"s3://{args.bucket}/", 1)[1].rstrip("/") + "/"
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=args.bucket, Prefix=artifact_prefix):
            for item in page.get("Contents", []):
                body = s3.get_object(Bucket=args.bucket, Key=item["Key"])["Body"].read()
                relative = item["Key"][len(artifact_prefix):]
                target_key = f"{prefix}/mlflow_artifacts/{relative}"
                s3.put_object(Bucket=args.bucket, Key=target_key, Body=body)
                entry = {
                    "name": f"mlflow_artifacts/{relative}",
                    "source_uri": f"s3://{args.bucket}/{item['Key']}",
                    "frozen_uri": f"s3://{args.bucket}/{target_key}",
                    "size_bytes": len(body),
                    "sha256": sha256_bytes(body),
                }
                copied.append(entry)
                mlflow_artifact_objects.append(entry)

    record = build_baseline_record(
        baseline_id=args.baseline_id,
        run_metadata=run_metadata,
        copied_artifacts=copied,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    record["mlflow_artifact_object_count"] = len(mlflow_artifact_objects)
    record_bytes = canonical_json_bytes(record)
    s3.put_object(
        Bucket=args.bucket,
        Key=record_key,
        Body=record_bytes,
        ContentType="application/json",
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(record_bytes)
    print(json.dumps({
        "baseline_id": args.baseline_id,
        "record_s3_uri": f"s3://{args.bucket}/{record_key}",
        "record_sha256": record["record_sha256"],
        "artifact_count": len(copied),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
