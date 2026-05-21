"""Glue Python Shell bootstrap: install the leviathan wheel from S3 at runtime.

Every Glue Python Shell job calls ``ensure_leviathan_installed(bucket)`` once
at module load time before importing any leviathan code.  The wheel is uploaded
to ``s3://{bucket}/glue-libs/leviathan-0.1.0-py3-none-any.whl`` as part of the
deployment process.

This module is intentionally importable without leviathan itself being installed
(it uses only stdlib + boto3, which Glue provides).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time


def ensure_leviathan_installed(bucket: str) -> None:
    """Download and pip-install the leviathan wheel from S3.

    Retries up to 3 times with exponential back-off, removing any partial
    download between attempts.  Raises on the third failure.

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
        except Exception:  # noqa: BLE001 — retry loop; raises on the third consecutive failure
            if attempt == 2:
                raise
            if os.path.exists(whl):
                os.remove(whl)
            time.sleep(5 * (attempt + 1))
