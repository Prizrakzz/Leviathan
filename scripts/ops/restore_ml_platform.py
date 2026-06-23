"""Verify or restore an MLflow/Airflow SQLite backup through SSM."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.ops.ml_platform import (  # noqa: E402
    SERVICE_SPECS,
    backup_keys,
    parse_s3_uri,
    validate_backup_manifest,
)
from leviathan.ops.ssm import encoded_python_command, parse_json_output, run_ssm_command  # noqa: E402


_REMOTE_RESTORE_SCRIPT = r'''
import base64
import hashlib
import json
import os
import pwd
import grp
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

payload = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))

def inspect(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
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
    finally:
        conn.close()
    return {
        "sha256": digest.hexdigest(),
        "integrity_check": str(integrity_row[0]) if integrity_row else "missing",
        "size_bytes": os.path.getsize(path),
        "table_counts": counts,
    }

def systemctl(action, units):
    for unit in units:
        subprocess.run(["systemctl", action, unit], check=True)

def wait_for_health(url):
    last_error = None
    for _ in range(30):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(2)
    raise RuntimeError(f"health check failed: {last_error}")

fd, downloaded = tempfile.mkstemp(prefix=f"leviathan-restore-{payload['service']}-", suffix=".db")
os.close(fd)
rollback = None
try:
    download = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error",
            "--location", "--output", downloaded, payload["download_url"],
        ],
        capture_output=True,
        check=False,
    )
    if download.returncode != 0:
        raise SystemExit(
            "backup download failed: " + download.stderr.decode("utf-8", errors="replace")
        )
    inspected = inspect(downloaded)
    if inspected["sha256"] != payload["expected_sha256"]:
        raise SystemExit("downloaded database SHA-256 does not match manifest")
    if inspected["integrity_check"] != "ok":
        raise SystemExit(f"downloaded integrity_check failed: {inspected['integrity_check']}")

    if not payload["apply"]:
        print(json.dumps({
            "service": payload["service"],
            "mode": "verify-only",
            **inspected,
        }, sort_keys=True, separators=(",", ":")))
        raise SystemExit(0)

    target = payload["database_path"]
    rollback = target + ".pre-restore-" + payload["backup_id"]
    systemctl("stop", payload["service_units"])
    if os.path.exists(target):
        shutil.copy2(target, rollback)
    os.replace(downloaded, target)
    downloaded = None
    user_name, group_name = payload["owner"].split(":", 1)
    os.chown(target, pwd.getpwnam(user_name).pw_uid, grp.getgrnam(group_name).gr_gid)
    systemctl("start", payload["service_units"])
    wait_for_health(payload["health_url"])
    live = inspect(target)
    if live["sha256"] != payload["expected_sha256"] or live["integrity_check"] != "ok":
        raise RuntimeError("post-restore database validation failed")
    print(json.dumps({
        "service": payload["service"],
        "mode": "applied",
        "rollback_path": rollback,
        **live,
    }, sort_keys=True, separators=(",", ":")))
except BaseException:
    if payload.get("apply") and rollback and os.path.exists(rollback):
        try:
            systemctl("stop", payload["service_units"])
            shutil.copy2(rollback, payload["database_path"])
            systemctl("start", payload["service_units"])
        except Exception:
            pass
    raise
finally:
    if downloaded and os.path.exists(downloaded):
        os.remove(downloaded)
'''


def load_manifest(s3, bucket: str, key: str) -> dict:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    manifest = json.loads(body)
    validate_backup_manifest(manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, choices=sorted(SERVICE_SPECS))
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--bucket", default=os.getenv("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.getenv("AWS_REGION", "us-east-1"))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--backup-id")
    source.add_argument("--manifest-uri")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-service",
        help="Required with --apply; must equal --service.",
    )
    args = parser.parse_args()
    if not args.bucket and not args.manifest_uri:
        raise SystemExit("--bucket or LEVIATHAN_BUCKET is required")
    if args.apply and args.confirm_service != args.service:
        raise SystemExit("--apply requires --confirm-service matching --service")

    spec = SERVICE_SPECS[args.service]
    if args.manifest_uri:
        bucket, manifest_key = parse_s3_uri(args.manifest_uri)
    else:
        bucket = args.bucket
        manifest_key = backup_keys(spec, args.backup_id)["manifest"]

    s3 = boto3.client("s3", region_name=args.aws_region)
    manifest = load_manifest(s3, bucket, manifest_key)
    validate_backup_manifest(manifest, expected_service=args.service)
    database_bucket, database_key = parse_s3_uri(manifest["database_s3_uri"])
    download_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": database_bucket, "Key": database_key},
        ExpiresIn=900,
    )
    payload = {
        "service": args.service,
        "backup_id": manifest["backup_id"],
        "database_path": spec.database_path,
        "service_units": list(spec.service_units),
        "owner": spec.owner,
        "health_url": spec.health_url,
        "expected_sha256": manifest["database_sha256"],
        "download_url": download_url,
        "apply": args.apply,
    }
    result = run_ssm_command(
        instance_id=args.instance_id,
        command=encoded_python_command(_REMOTE_RESTORE_SCRIPT, payload),
        aws_region=args.aws_region,
        timeout_seconds=600,
    )
    verification = parse_json_output(result)
    if verification["sha256"] != manifest["database_sha256"]:
        raise RuntimeError("remote verification SHA-256 differs from manifest")
    if verification["integrity_check"] != "ok":
        raise RuntimeError("remote verification integrity_check failed")
    print(json.dumps({
        "manifest_s3_uri": f"s3://{bucket}/{manifest_key}",
        "verification": verification,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
