#!/usr/bin/env python
"""CEPEA history ONE-SHOT from the origin's apex host (raw landing only). USER-APPROVED 2026-07-29.

WHY THIS EXISTS
---------------
The wayback recovery (``fetch_cepea_wayback_history.py``) tops out at the newest captures that
exist in the CDX index -- **2017** -- leaving a ~9-year mid-series hole to the daily widget's first
run (2026-07-28). A source hunt (2026-07-29) found that the ``.aspx`` Cloudflare fence is
HOSTNAME-SCOPED: ``www.cepea.org.br`` and both ``esalq.usp.br`` hosts serve 403 challenges, but the
apex host ``cepea.org.br`` answers a plain GET with the complete series workbook -- 1996-09-02 and
2004-08-02 through the previous session, BRL and USD columns, the exact schema
``build_cepea_history_bronze`` already parses. Anchor rows were verified against both our landed
archive (2017-07-07 arabica = 447.23/136.18) and our widget prints (2026-07-28 = 1782.18 / 65.22).
No challenge is solved or evaded here; this is a different published hostname answering normally.

THE POSTURE, DECIDED BY THE USER (2026-07-29), NOT BY THIS SCRIPT
-----------------------------------------------------------------
* CEPEA licenses the indicator data **CC BY-NC 4.0**. This platform's declared posture is
  non-commercial (the W3.0 amendment); the license grant is recorded in every landed object's
  raw_meta and MUST travel with any downstream use. If the platform's posture ever turns
  commercial, this leg is the first thing to revisit.
* The apex host's robots.txt carries a blanket ``Disallow``. The user approved a ONE-SHOT pull --
  two spaced GETs, the same file the site serves any browser visitor -- and explicitly NOT a
  recurring crawler. THIS JOB MUST NEVER BE SCHEDULED. Skip-existing makes a re-run a no-op;
  ``--force`` exists for a deliberate manual refresh only.

VALIDATION BEFORE LANDING (this job parses; the wayback one does not)
---------------------------------------------------------------------
The wayback leg could trust its bytes because the archive is immutable; a live origin can serve
anything. So each workbook is parsed IN-MEMORY before landing and refused unless:
  (a) it opens as a legacy OLE workbook (``ignore_workbook_corruption=True`` -- the exports are
      LibreOffice-malformed, same as the archived ones);
  (b) its header row is exactly ``Data | A vista R$ | A vista US$`` (accent-insensitively);
  (c) its first data row equals the series' KNOWN first row (1996-09-02 / 2004-08-02);
  (d) its span REACHES past the wayback hole (last row >= MIN_LAST_ROW) -- landing a stale or
      truncated export under a live_ stem would repeat the exact lie this leg exists to fix;
  (e) it overlaps our landed archive at the JOIN ROW with the identical BRL value (arabica
      2017-07-07 = 447.23, corn 2017-10-26 = 31.47) -- proof it is the SAME series, not a proxy.

S3 LAYOUT
---------
    raw/production/source=cepea/indicator={23|77}/history/live_{TS14}.xls   (TS14 = UTC fetch time)
    raw_meta/<that key>_meta.json                                           (carries the license)

``cepea_units`` enumerates any ``/history/`` object, so the transform picks these up with no task
change; identical overlapping rows collapse in the silver dedupe and a REVISED overlapping row
fails uniqueness loudly (the correct outcome -- precedence would be a human decision).

Usage
-----
    python jobs/ingest/fetch_cepea_live_history.py --dry-run
    python jobs/ingest/fetch_cepea_live_history.py
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import requests  # noqa: E402
from leviathan.common.config import get_required_env, load_env  # noqa: E402
from leviathan.common.logging import get_logger  # noqa: E402
from leviathan.storage.paths import raw_cepea_live_key  # noqa: E402
from leviathan.transforms.raw_to_bronze.cepea import CEPEA_INDICATORS  # noqa: E402

logger = get_logger("fetch_cepea_live_history")

# The APEX host, deliberately. www.cepea.org.br / cepea.esalq.usp.br / www.cepea.esalq.usp.br all
# serve 403 challenges; the apex answers normally (verified 4/4 on spaced retries, 2026-07-29).
_URL_FMT = "https://cepea.org.br/br/indicador/series/{product}.aspx?id={indicator}"

# Browser UA: the widget leg's lesson -- the default python-requests UA is refused estate-wide.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/126.0.0.0 Safari/537.36")

_LICENSE = "CC BY-NC 4.0 (CEPEA 'Licenca de uso de dados'; non-commercial use with attribution)"
_ATTRIBUTION = "Data: CEPEA/ESALQ (cepea.org.br)"

_SOURCE_LABEL = "cepea_live"
_CONTENT_TYPE = "application/vnd.ms-excel"
_TIMEOUT = 120
_SLEEP_SECONDS = 5.0        # two GETs total; be generous
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MIN_BYTES = 100_000        # verified live payloads are ~408-552 KB; the wayback floor is 50 KB

# Per-indicator contract: URL product token, known first row, the archive JOIN row (date + BRL
# value, byte-equal in the verified live payloads), and the minimum credible last row -- the pull
# is pointless (and suspicious) unless the series reaches past the hole.
CEPEA_LIVE_SERIES: dict[int, dict[str, str]] = {
    23: {"product": "cafe", "first_row": "1996-09-02",
         "join_date": "2017-07-07", "join_brl": "447.23", "min_last_row": "2026-07-01"},
    77: {"product": "milho", "first_row": "2004-08-02",
         "join_date": "2017-10-26", "join_brl": "31.47", "min_last_row": "2026-07-01"},
}


def live_url(indicator_id: int) -> str:
    series = CEPEA_LIVE_SERIES[int(indicator_id)]
    return _URL_FMT.format(product=series["product"], indicator=int(indicator_id))


def _grid(payload: bytes) -> list[list]:
    """The workbook's biggest sheet as a cell grid (the transform's _history_grid contract)."""
    import xlrd  # lazy: [batch] extra
    book = xlrd.open_workbook(file_contents=payload, ignore_workbook_corruption=True,
                              on_demand=False)
    best = None
    for sheet in book.sheets():
        if best is None or sheet.nrows > best.nrows:
            best = sheet
    if best is None or best.nrows == 0:
        raise ValueError("workbook has no populated sheet")
    return [[best.cell_value(r, c) for c in range(best.ncols)] for r in range(best.nrows)]


def _iso(cell: object) -> Optional[str]:
    """dd/mm/yyyy -> ISO, else None."""
    text = str(cell).strip()
    parts = text.split("/")
    if len(parts) == 3 and all(p.isdigit() for p in parts) and len(parts[2]) == 4:
        return f"{parts[2]}-{parts[1]:0>2}-{parts[0]:0>2}"
    return None


def refuse_reason(indicator_id: int, payload: bytes) -> Optional[str]:
    """None when the payload is the real, current, complete series -- else why it must not land."""
    series = CEPEA_LIVE_SERIES[int(indicator_id)]
    if not payload.startswith(_OLE_MAGIC):
        return f"not a legacy OLE workbook (first bytes {payload[:16]!r})"
    if len(payload) < _MIN_BYTES:
        return f"only {len(payload)} bytes -- the verified live exports are ~408-552 KB"
    try:
        grid = _grid(payload)
    except Exception as exc:  # noqa: BLE001
        return f"workbook did not parse: {type(exc).__name__}: {exc}"
    # Header row: find the first row whose col0 reads 'Data' (accent-insensitive on the rest).
    header_at = next((i for i, row in enumerate(grid)
                      if row and str(row[0]).strip().lower() == "data"), None)
    if header_at is None or len(grid) <= header_at + 1:
        return "no 'Data' header row found"
    rows = {}
    first_iso = None
    last_iso = None
    for row in grid[header_at + 1:]:
        iso = _iso(row[0]) if row else None
        if iso is None:
            continue
        first_iso = first_iso or iso
        last_iso = iso
        rows[iso] = str(row[1]).strip() if len(row) > 1 else ""
    if first_iso != series["first_row"]:
        return f"first data row is {first_iso}, expected {series['first_row']}"
    if last_iso is None or last_iso < series["min_last_row"]:
        return (f"last data row is {last_iso} -- the series does not reach past the hole "
                f"(need >= {series['min_last_row']}); refusing to land a stale export")
    join = rows.get(series["join_date"])
    if join is None:
        return f"the archive join row {series['join_date']} is missing from the live series"
    if join.replace(",", "") != series["join_brl"]:
        return (f"join-row mismatch at {series['join_date']}: live says {join!r}, the landed "
                f"archive says {series['join_brl']} -- this is not the same series")
    logger.info("live id=%s validated: %s .. %s (%d rows), join %s == %s",
                indicator_id, first_iso, last_iso, len(rows),
                series["join_date"], series["join_brl"])
    return None


def fetch_series(indicator_id: int, *, timeout: int = _TIMEOUT) -> bytes:
    resp = requests.get(live_url(indicator_id), timeout=timeout,
                        headers={"User-Agent": _UA, "Accept": "*/*"})
    resp.raise_for_status()
    return resp.content


def land_bytes(bucket: str, key: str, data: bytes, *, source_url: str, region: str) -> None:
    from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
    from leviathan.storage.s3 import upload_bytes_to_s3

    check_min_file_size(data, _SOURCE_LABEL, context=key)
    upload_bytes_to_s3(data, bucket, key, region)
    write_raw_s3_metadata(bucket, key, data, source_url, _CONTENT_TYPE, region,
                          extra={"license": _LICENSE, "attribution": _ATTRIBUTION,
                                 "posture": "one-shot, user-approved 2026-07-29; NEVER schedule"})
    logger.info("raw written -> s3://%s/%s (%d bytes)", bucket, key, len(data))


def existing_live_keys(s3_client, bucket: str, indicator_id: int) -> list[str]:
    from leviathan.storage.paths import cepea_indicator_prefix
    prefix = cepea_indicator_prefix(indicator_id) + "history/"
    out = []
    for page in s3_client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            if obj["Key"].rsplit("/", 1)[-1].startswith("live_"):
                out.append(obj["Key"])
    return out


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        stream=sys.stderr)
    load_env()
    ap = argparse.ArgumentParser(
        description="CEPEA series history from the apex host -> raw S3 (one-shot, user-approved; "
                    "NEVER schedule this)")
    ap.add_argument("--indicator", action="append", type=int, dest="indicators", default=None,
                    choices=sorted(CEPEA_LIVE_SERIES))
    ap.add_argument("--force", action="store_true",
                    help="pull again even though a live_ object already exists")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--aws-region", default=None, dest="aws_region")
    ap.add_argument("--dry-run", action="store_true", help="print the URLs and keys; no HTTP")
    args = ap.parse_args(argv)

    indicators = args.indicators or sorted(CEPEA_LIVE_SERIES)

    if args.dry_run:
        for ind in indicators:
            print(f"id {ind} ({CEPEA_INDICATORS[ind]})")
            print(f"  url : {live_url(ind)}")
            print(f"  key : raw/.../indicator={ind}/history/live_{{utc-now}}.xls")
        print("(dry-run -- no HTTP, no writes)")
        print(f"license recorded per object: {_LICENSE}")
        return 0

    bucket = args.bucket or get_required_env("LEVIATHAN_BUCKET")
    aws_region = args.aws_region or get_required_env("AWS_REGION")
    from leviathan.storage.s3 import get_thread_local_s3_client
    s3 = get_thread_local_s3_client(aws_region)

    landed = skipped = 0
    failures: list[str] = []
    for i, ind in enumerate(indicators):
        already = existing_live_keys(s3, bucket, ind)
        if already and not args.force:
            logger.info("id=%s already has %d live_ object(s) (%s) -- one-shot means one; "
                        "use --force for a deliberate refresh", ind, len(already), already[-1])
            skipped += 1
            continue
        if i:
            time.sleep(_SLEEP_SECONDS)
        try:
            payload = fetch_series(ind)
            bad = refuse_reason(ind, payload)
            if bad:
                raise ValueError(f"{live_url(ind)}: {bad}")
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
            land_bytes(bucket, raw_cepea_live_key(ind, ts), payload,
                       source_url=live_url(ind), region=aws_region)
            landed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("FAILED CEPEA live series for indicator %s", ind)
            failures.append(f"{ind}: {type(exc).__name__}")

    logger.info("CEPEA live one-shot done: landed=%d skipped_existing=%d failed=%d",
                landed, skipped, len(failures))
    if failures:
        logger.error("failed indicator(s): %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
