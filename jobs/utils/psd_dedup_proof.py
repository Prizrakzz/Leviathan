"""Pre-registered equivalence proof for the PSD bronze ETag-dedup rider (D-SG G1-1b).

The rider in ``jobs/batch/psd_silver_task._load_bronze`` drops bronze partitions whose RAW
vendor zip is a byte-identical OLDER copy of a newer one (the fetch leg stamps
``release_date`` with the fetch date, so one monthly USDA bulk file lands under up to six
labels). The argument that this is content-preserving is step 11.5 of the transform: a
re-printed vintage is already resolved by keeping the LATEST release_date, so an older
byte-identical copy can never be the row that survives.

That argument is checkable, and this harness is the check. It runs
``transform_psd_bronze_to_silver`` TWICE over the LIVE bronze partitions -- once over every
partition, once over only the ETag-deduped selection the rider would load -- and compares a
canonical hash of the two output frames. PASS = identical. The proof is MANDATORY before the
rider's first canonical fire; a FAIL refuses the rider (the sizing then falls back to the
4 vCPU / 30720 MB fork).

Read-only: S3 ListObjectsV2 + GetObject only, ~30 MB of parquet. Nothing is written to S3.

The two arms run as SUBPROCESSES of this script, one at a time: the full-input arm peaks at
~8.7 GiB RSS inside the concat -> pivot_table, so holding both frames in one process is not
affordable on a workstation.

Usage
-----
    python jobs/utils/psd_dedup_proof.py
    python jobs/utils/psd_dedup_proof.py --cache-dir <dir>   # reuse an earlier download
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from jobs.batch.psd_silver_task import (  # noqa: E402
    _BRONZE_PREFIX,
    _distinct_release_dates,
)
from leviathan.storage.paths import parse_hive_key  # noqa: E402
from leviathan.storage.s3 import get_thread_local_s3_client, list_s3_keys  # noqa: E402
from leviathan.transforms.bronze_to_silver.usda_psd import (  # noqa: E402
    _SILVER_COLS,
    transform_psd_bronze_to_silver,
)

_DEFAULT_BUCKET = "leviathan-dev-shahem-001"
_DEFAULT_REGION = "us-east-1"


def _frame_hash(df: pd.DataFrame) -> str:
    """Order-independent, index-independent sha256 of a silver frame.

    The transform pins the column order (step 16), so both arms hash the same columns in
    the same order; sorting by every column with a stable kind removes any dependence on
    the order rows happen to leave the pivot in.
    """
    ordered = df[list(_SILVER_COLS)].sort_values(
        list(_SILVER_COLS), kind="mergesort", na_position="last"
    ).reset_index(drop=True)
    hashed = pd.util.hash_pandas_object(ordered, index=False)
    return hashlib.sha256(hashed.values.tobytes()).hexdigest()


def _download(bucket: str, region: str, cache_dir: str) -> list[str]:
    """Cache every live bronze PSD partition locally, named by its release_date label."""
    s3 = get_thread_local_s3_client(region)
    keys = sorted(list_s3_keys(bucket, _BRONZE_PREFIX, suffix="part-000.parquet",
                               aws_region=region))
    if not keys:
        raise SystemExit("no bronze PSD partitions under %s" % _BRONZE_PREFIX)
    os.makedirs(cache_dir, exist_ok=True)
    paths = []
    for key in keys:
        label = parse_hive_key(key, "release_date")
        path = os.path.join(cache_dir, "%s.parquet" % label)
        if not os.path.exists(path):
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            with open(path, "wb") as fh:
                fh.write(body)
        paths.append(path)
        print("  bronze %s -> %s (%d bytes)" % (label, path, os.path.getsize(path)))
    return paths


def _run_arm(cache_dir: str, keep: set[str] | None) -> None:
    """One arm, in its own process: load the selected parquets, transform, print the hash."""
    paths = sorted(glob.glob(os.path.join(cache_dir, "*.parquet")))
    if keep is not None:
        paths = [p for p in paths
                 if os.path.basename(p)[: -len(".parquet")] in keep]
    dfs = [pd.read_parquet(p) for p in paths]
    out = transform_psd_bronze_to_silver(dfs)
    print("ARM_PARTITIONS=%d" % len(paths))
    print("ARM_ROWS=%d" % len(out))
    print("ARM_HASH=%s" % _frame_hash(out))


def _spawn(label: str, cache_dir: str, keep: set[str] | None) -> tuple[int, str]:
    """Run one arm as a subprocess so its peak RSS is released before the next arm."""
    cmd = [sys.executable, os.path.abspath(__file__), "--arm", "--cache-dir", cache_dir]
    if keep is not None:
        cmd += ["--keep", ",".join(sorted(keep))]
    print("\n[%s] %s" % (label, " ".join(cmd)))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit("arm %s failed with exit %d" % (label, proc.returncode))
    rows, digest = 0, ""
    for line in proc.stdout.splitlines():
        print("  " + line)
        if line.startswith("ARM_ROWS="):
            rows = int(line.split("=", 1)[1])
        elif line.startswith("ARM_HASH="):
            digest = line.split("=", 1)[1]
    if not digest:
        raise SystemExit("arm %s printed no hash" % label)
    return rows, digest


def main() -> None:
    parser = argparse.ArgumentParser(description="PSD ETag-dedup equivalence proof (read-only)")
    parser.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET", _DEFAULT_BUCKET))
    parser.add_argument("--aws-region", default=os.environ.get("AWS_REGION", _DEFAULT_REGION),
                        dest="aws_region")
    parser.add_argument("--cache-dir", default=os.path.join(tempfile.gettempdir(),
                                                            "psd_dedup_proof"),
                        dest="cache_dir")
    parser.add_argument("--arm", action="store_true",
                        help="INTERNAL: run one arm in this process and print its hash.")
    parser.add_argument("--keep", default="",
                        help="INTERNAL: comma-separated release_date labels for --arm.")
    args = parser.parse_args()
    # The arms take minutes; line-buffer so a redirected log interleaves with their stderr
    # in the order things actually happened.
    sys.stdout.reconfigure(line_buffering=True)

    if args.arm:
        _run_arm(args.cache_dir, set(args.keep.split(",")) if args.keep else None)
        return

    print("PSD ETag-dedup equivalence proof (D-SG G1-1b)")
    print("bucket=%s region=%s cache=%s" % (args.bucket, args.aws_region, args.cache_dir))

    s3 = get_thread_local_s3_client(args.aws_region)
    keep, seen_raw = _distinct_release_dates(s3, args.bucket)
    if keep is None:
        raise SystemExit("raw ETag listing unavailable -- the rider would be inert; nothing proved")
    print("distinct vendor releases (newest label per raw zip ETag): %s" % ", ".join(sorted(keep)))

    print("caching live bronze partitions (read-only GETs):")
    paths = _download(args.bucket, args.aws_region, args.cache_dir)
    labels = [os.path.basename(p)[: -len(".parquet")] for p in paths]
    # Model the SHIPPED selection (review M-2): a label raw proves duplicate is dropped;
    # a label with NO raw counterpart is KEPT -- the same rule _load_bronze applies.
    selected = {l for l in labels if l in keep or l not in seen_raw}
    dropped = sorted(set(labels) - selected)
    print("partitions=%d kept=%d dropped=%s" % (len(labels), len(selected), dropped or "none"))

    rows_all, hash_all = _spawn("FULL", args.cache_dir, None)
    rows_dedup, hash_dedup = _spawn("DEDUP", args.cache_dir, selected)

    print("\nFULL   partitions=%d rows=%d hash=%s" % (len(labels), rows_all, hash_all))
    print("DEDUP  partitions=%d rows=%d hash=%s" % (len(selected), rows_dedup, hash_dedup))
    if hash_all == hash_dedup:
        print("RESULT: PASS -- the dedup rider is output-identical on the live bronze")
        return
    print("RESULT: FAIL -- the rider changes the silver output and is REFUSED by its own proof")
    sys.exit(1)


if __name__ == "__main__":
    main()
