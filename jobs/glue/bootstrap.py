"""Standalone bootstrap module for Glue Python Shell jobs.

This file is uploaded to S3 at ``glue-libs/bootstrap.py`` and included in
every Glue job definition via ``--extra-py-files``, making it importable
without leviathan being installed first.

Usage at the top of every Glue job script (before any leviathan imports):

    from bootstrap import run_bootstrap
    run_bootstrap()
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


def ensure_leviathan_installed(bucket: str) -> None:
    """Download and pip-install the leviathan wheel from S3.

    Retries up to 3 times with exponential back-off, removing any partial
    download between attempts.  Raises on the third failure so the Glue job
    exits with a non-zero status rather than silently proceeding with no
    leviathan package.

    Args:
        bucket: S3 bucket that contains ``glue-libs/leviathan-*.whl``.
    """
    import boto3

    whl = "/tmp/leviathan-0.1.0-py3-none-any.whl"
    s3_key = "glue-libs/leviathan-0.1.0-py3-none-any.whl"

    for attempt in range(3):
        try:
            if not os.path.exists(whl):
                boto3.client("s3").download_file(bucket, s3_key, whl)
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", whl, "--no-deps", "--quiet"]
            )
            return
        except (subprocess.CalledProcessError, OSError):
            if attempt == 2:
                raise
            if os.path.exists(whl):
                os.remove(whl)
            time.sleep(5 * (attempt + 1))


def run_bootstrap() -> None:
    """Extract ``--bucket`` from sys.argv, install the leviathan wheel, and return.

    Call this at the top of every Glue job script before importing any
    leviathan code.  On error, prints a ``[BOOTSTRAP ERROR]`` diagnostic
    and re-raises so the Glue job fails with a non-zero exit status.
    """
    bucket = next(
        (sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--bucket" and i + 1 < len(sys.argv)),
        None,
    )
    if bucket is None:
        raise RuntimeError("--bucket argument required for leviathan bootstrap")
    try:
        ensure_leviathan_installed(bucket)
    except Exception as _exc:  # noqa: BLE001 — catch-log-reraise: print diagnostic before re-raising any installation failure
        print(f"[BOOTSTRAP ERROR] {type(_exc).__name__}: {_exc}", flush=True)
        raise
