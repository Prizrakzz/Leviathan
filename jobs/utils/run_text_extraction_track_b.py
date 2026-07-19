"""Track B one-shot: extract ICCO QBCS/EWG + SAGIS CEC narrative into the text/ layer.

Local threaded runner (the transforms are pure-python; S3 GetObject in, document.json out via the
house writer). Idempotent: document_exists() skips already-written keys, and CEC raw re-uploads are
deduped by content sha256 (first-seen wins; copies logged, never silently mixed).

Key shape follows the WASDE precedent -- release_date=<PIT date> is the partition the chunker
dates from -- with a doc=<sha8> leaf so two same-date documents can never clobber each other:

    text/source=icco_qbcs_summary/release_date=YYYY-MM-DD/doc=<sha8>/document.json
    text/source=icco_ewg_stocks/release_date=YYYY-MM-DD/doc=<sha8>/document.json
    text/source=sagis_cec/release_date=YYYY-MM-DD/doc=<sha8>/document.json

The PIT stamp is ALWAYS the transform's derived publication date (fail-closed), never extracted_at.

    python jobs/utils/run_text_extraction_track_b.py --dry-run
    python jobs/utils/run_text_extraction_track_b.py            # extract + write
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import time

import boto3
from botocore.config import Config

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger
from leviathan.transforms.raw_to_text.icco_qbcs import extract_icco_qbcs, publication_date
from leviathan.transforms.raw_to_text.sagis_cec_text import derive_release_date, extract_sagis_cec_text
from leviathan.transforms.raw_to_text.writer import document_exists, write_document

logger = get_logger("run_text_extraction_track_b")

BUCKET = "leviathan-dev-shahem-001"
ICCO_SOURCES = ("icco_qbcs_summary", "icco_ewg_stocks")
CEC_PREFIX = "raw/production/source=sagis_cec/"


def _get_bytes(s3, key: str, attempts: int = 4) -> bytes:
    for i in range(attempts):
        try:
            return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        except Exception:  # noqa: BLE001 -- mid-stream resets aren't retried by botocore
            if i == attempts - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError("unreachable")


def _list_keys(s3, prefix: str) -> list[str]:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []))
    return keys


def _process_icco(s3, source: str, key: str, dry: bool) -> str:
    data = _get_bytes(s3, key)
    doc = extract_icco_qbcs(data, key, source)
    rel = publication_date(key, doc["full_text"])
    sha8 = hashlib.sha256(data).hexdigest()[:8]
    out = f"text/source={source}/release_date={rel}/doc={sha8}/document.json"
    if document_exists(s3, BUCKET, out):
        return f"SKIP-exists {out}"
    if not dry:
        write_document(s3, BUCKET, out, doc)
    return f"WROTE {out} ({len(doc['full_text'])} chars)"


def _process_cec(s3, key: str, data: bytes, dry: bool) -> str:
    doc = extract_sagis_cec_text(data, key)
    rel = derive_release_date(data, key, full_text=doc["full_text"])
    sha8 = hashlib.sha256(data).hexdigest()[:8]
    out = f"text/source=sagis_cec/release_date={rel}/doc={sha8}/document.json"
    if document_exists(s3, BUCKET, out):
        return f"SKIP-exists {out}"
    if not dry:
        write_document(s3, BUCKET, out, doc)
    return f"WROTE {out} ({len(doc['full_text'])} chars)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    load_env()
    s3 = boto3.client("s3", config=Config(retries={"max_attempts": 10, "mode": "adaptive"}))

    jobs = []  # (fn, label)
    for source in ICCO_SOURCES:
        for key in _list_keys(s3, f"raw/production/source={source}/"):
            if key.endswith(".html"):  # sidecar .json carries metadata, not narrative
                jobs.append(("icco", source, key, None))

    # CEC: download-once + sha256 dedup across raw re-uploads
    seen: dict[str, str] = {}
    for key in _list_keys(s3, CEC_PREFIX):
        data = _get_bytes(s3, key)
        h = hashlib.sha256(data).hexdigest()
        if h in seen:
            logger.info("DUP skipped: %s (== %s)", key, seen[h])
            continue
        seen[h] = key
        jobs.append(("cec", "sagis_cec", key, data))
    print("queued: %d docs (%d unique CEC)" % (len(jobs), len(seen)), flush=True)

    ok = err = 0
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {}
        for kind, source, key, data in jobs:
            if kind == "icco":
                futs[ex.submit(_process_icco, s3, source, key, args.dry_run)] = key
            else:
                futs[ex.submit(_process_cec, s3, key, data, args.dry_run)] = key
        for f in as_completed(futs):
            try:
                logger.info(f.result())
                ok += 1
            except Exception as exc:  # noqa: BLE001 -- tally + report every failure at the end
                err += 1
                failures.append(f"{futs[f]}: {type(exc).__name__}: {exc}")
                logger.error("FAILED %s: %s", futs[f], exc)
    print("DONE: %d ok, %d failed%s" % (ok, err, " (dry-run)" if args.dry_run else ""), flush=True)
    for msg in failures[:20]:
        print("  FAIL " + msg, flush=True)
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
