"""Fetch the USDA FAS ESR *country reference* (code -> name) — ESR_DESTINATION_PLAN W0 provenance.

The weekly/backfill ESR export endpoint (``fetch_usda_esr.py``) returns per-country rows keyed by a
raw FAS ``countryCode`` with NO name. The FAS **``/api/esr/countries``** reference endpoint is the
never-fetched source of the code->name mapping (fields: ``countryCode``, ``countryName``,
``countryDescription``, ``regionId``, ``gencCode``). This one-shot fetch is provenance for the committed
``configs/graphrag/numbers/esr_destinations.yaml`` (built by ``jobs/utils/build_esr_destinations.py``) —
it is NOT a runtime dependency of serving.

  # local provenance (no AWS writes):
  python jobs/ingest/fetch_usda_esr_countries.py --out reports/esr/esr_countries_raw.json
  # immutable raw S3 (main-loop action; mirrors the ESR raw convention):
  python jobs/ingest/fetch_usda_esr_countries.py --s3

Requires ``FAS_API_KEY`` (free from api.data.gov; passed as the ``X-Api-Key`` header, never in the URL),
exactly like ``fetch_usda_esr.py``. Read-only GET; the reference is tiny (~210 rows) and static.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
from pathlib import Path

import requests
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_API_URL = "https://api.fas.usda.gov/api/esr/countries"
_API_KEY_ENV = "FAS_API_KEY"
_DOWNLOAD_TIMEOUT = 30
_MIN_ROWS = 100                         # sanity floor: the reference is ~210 rows; <100 == an error page


def raw_countries_key(as_of_date: str) -> str:
    """Immutable raw S3 key for the ESR country reference (mirrors ``raw/... source=usda_esr`` layout)."""
    return f"raw/reference/source=usda_esr/countries/as_of={as_of_date}/countries.json"


def fetch_countries(api_key: str) -> bytes:
    """GET the FAS country reference; return raw JSON bytes. Raises on a non-array / too-small payload."""
    logger.info("GET %s", _API_URL)
    resp = requests.get(_API_URL, timeout=_DOWNLOAD_TIMEOUT, headers={"X-Api-Key": api_key})
    resp.raise_for_status()
    data = resp.content
    parsed = json.loads(data)
    if not isinstance(parsed, list) or len(parsed) < _MIN_ROWS:
        raise RuntimeError(f"ESR countries response not a >= {_MIN_ROWS}-row array "
                           f"(type={type(parsed).__name__}, len={len(parsed) if isinstance(parsed, list) else 'n/a'})")
    expect = {"countryCode", "countryName", "countryDescription", "regionId", "gencCode"}
    missing = expect - set(parsed[0])
    if missing:
        raise RuntimeError(f"ESR countries rows missing expected fields: {sorted(missing)}")
    logger.info("  %d rows, %.1f KB", len(parsed), len(data) / 1024)
    return data


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="local path to write raw JSON (provenance)")
    ap.add_argument("--s3", action="store_true",
                    help="ALSO upload immutable raw JSON to S3 (main-loop action; needs LEVIATHAN_BUCKET/AWS_REGION)")
    ap.add_argument("--as-of", default=datetime.date.today().strftime("%Y%m%d"))
    args = ap.parse_args()

    load_env()
    api_key = get_required_env(_API_KEY_ENV)
    data = fetch_countries(api_key)

    out = Path(args.out) if args.out else Path("reports/esr") / f"esr_countries_{args.as_of}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    logger.info("wrote local provenance -> %s", out)

    if args.s3:
        # Immutable raw persistence. S3 WRITE -- a data-plane mutation; run this only in the main loop.
        from leviathan.storage.raw_metadata import write_raw_s3_metadata
        from leviathan.storage.s3 import upload_bytes_to_s3
        bucket = get_required_env("LEVIATHAN_BUCKET")
        region = get_required_env("AWS_REGION")
        key = raw_countries_key(args.as_of)
        upload_bytes_to_s3(data, bucket, key, region)
        write_raw_s3_metadata(bucket, key, data, _API_URL, "application/json", region)
        logger.info("uploaded -> s3://%s/%s", bucket, key)

    print(f"esr countries fetched: {len(json.loads(data))} rows -> {out}")


if __name__ == "__main__":
    main()
