"""Create online, checksummed backups of the MLflow and Airflow SQLite stores."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.ops.ml_platform import (  # noqa: E402
    SERVICE_SPECS,
    backup_keys,
    canonical_json_bytes,
    utc_backup_id,
    validate_backup_manifest,
)
from leviathan.ops.ssm import encoded_python_command, parse_json_output, run_ssm_command  # noqa: E402


_REMOTE_BACKUP_SCRIPT = r'''
import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

payload = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
database_path = payload["database_path"]

def integrity(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "missing"
    finally:
        conn.close()

def table_counts(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
        return counts
    finally:
        conn.close()

source_integrity = integrity(database_path)
if source_integrity != "ok":
    raise SystemExit(f"source integrity_check failed: {source_integrity}")

fd, backup_path = tempfile.mkstemp(prefix=f"leviathan-{payload['service']}-", suffix=".db")
os.close(fd)
try:
    source = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    backup_integrity = integrity(backup_path)
    if backup_integrity != "ok":
        raise SystemExit(f"backup integrity_check failed: {backup_integrity}")

    digest = hashlib.sha256()
    with open(backup_path, "rb") as handle:
        data = handle.read()
        digest.update(data)
    upload = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error",
            "--request", "PUT", "--upload-file", backup_path,
            payload["upload_url"],
        ],
        capture_output=True,
        check=False,
    )
    if upload.returncode != 0:
        raise SystemExit(
            "backup upload failed: " + upload.stderr.decode("utf-8", errors="replace")
        )

    statuses = {}
    for unit in payload["service_units"]:
        proc = subprocess.run(
            ["systemctl", "is-active", unit],
            text=True, capture_output=True, check=False,
        )
        statuses[unit] = proc.stdout.strip() or proc.stderr.strip()
    version_proc = subprocess.run(
        payload["version_command"],
        shell=True, text=True, capture_output=True, check=False,
    )
    version = (version_proc.stdout or version_proc.stderr).strip()

    result = {
        "schema_version": 1,
        "backup_id": payload["backup_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "service": payload["service"],
        "instance_id": payload["instance_id"],
        "database_path": database_path,
        "database_size_bytes": os.path.getsize(backup_path),
        "database_sha256": digest.hexdigest(),
        "source_integrity_check": source_integrity,
        "backup_integrity_check": backup_integrity,
        "service_version": version,
        "service_status": statuses,
        "table_counts": table_counts(backup_path),
        "database_s3_uri": payload["database_s3_uri"],
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
finally:
    try:
        os.remove(backup_path)
    except FileNotFoundError:
        pass
'''


def backup_service(
    *,
    service: str,
    backup_id: str,
    instance_id: str,
    bucket: str,
    aws_region: str,
    s3_client=None,
    ssm_client=None,
) -> dict:
    spec = SERVICE_SPECS[service]
    s3 = s3_client or boto3.client("s3", region_name=aws_region)
    keys = backup_keys(spec, backup_id)
    for key in keys.values():
        try:
            s3.head_object(Bucket=bucket, Key=key)
        except s3.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise
        else:
            raise FileExistsError(f"refusing to overwrite s3://{bucket}/{key}")

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": keys["database"]},
        ExpiresIn=900,
    )
    payload = {
        "service": service,
        "backup_id": backup_id,
        "instance_id": instance_id,
        "database_path": spec.database_path,
        "service_units": list(spec.service_units),
        "version_command": spec.version_command,
        "database_s3_uri": f"s3://{bucket}/{keys['database']}",
        "upload_url": upload_url,
    }
    result = run_ssm_command(
        instance_id=instance_id,
        command=encoded_python_command(_REMOTE_BACKUP_SCRIPT, payload),
        aws_region=aws_region,
        timeout_seconds=300,
        ssm_client=ssm_client,
    )
    manifest = parse_json_output(result)
    validate_backup_manifest(manifest, expected_service=service)

    head = s3.head_object(Bucket=bucket, Key=keys["database"])
    if int(head["ContentLength"]) != int(manifest["database_size_bytes"]):
        raise RuntimeError("uploaded database size does not match backup manifest")
    s3.put_object(
        Bucket=bucket,
        Key=keys["manifest"],
        Body=canonical_json_bytes(manifest),
        ContentType="application/json",
        Metadata={
            "service": service,
            "backup-id": backup_id,
            "database-sha256": manifest["database_sha256"],
        },
    )
    return {
        **manifest,
        "manifest_s3_uri": f"s3://{bucket}/{keys['manifest']}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--bucket", default=os.getenv("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--services",
        default="mlflow,airflow",
        help="Comma-separated subset of mlflow,airflow.",
    )
    parser.add_argument("--backup-id", help="Default: current UTC timestamp.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.bucket:
        raise SystemExit("--bucket or LEVIATHAN_BUCKET is required")

    services = [name.strip() for name in args.services.split(",") if name.strip()]
    unknown = sorted(set(services) - set(SERVICE_SPECS))
    if unknown:
        raise SystemExit(f"unknown services: {unknown}")
    backup_id = args.backup_id or utc_backup_id()

    results = [
        backup_service(
            service=service,
            backup_id=backup_id,
            instance_id=args.instance_id,
            bucket=args.bucket,
            aws_region=args.aws_region,
        )
        for service in services
    ]
    document = {
        "schema_version": 1,
        "backup_id": backup_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instance_id": args.instance_id,
        "services": results,
    }
    rendered = json.dumps(document, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
