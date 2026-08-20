"""Fetch the USDA AMS Grain Transportation Report (GTR) freight family to raw S3.

Source
------
USDA / Agricultural Marketing Service / Transportation & Marketing Program.

    Program landing:  https://www.ams.usda.gov/services/transportation-analysis/gtr
    Datasets index:   https://www.ams.usda.gov/services/transportation-analysis/gtr-datasets
    SODA portal:      https://agtransport.usda.gov/

Seven datasets, one family, no authentication anywhere.  The full table -- endpoint,
cadence, unit, and the phrase the publisher itself uses to declare that unit -- lives
in :data:`leviathan.transforms.raw_to_bronze.ams_gtr.GTR_DATASETS`, which is the single
authority.  This module fetches what that table names and nothing else.

    ocean_weekly              GTRTable1.xlsx        weekly     USD/metric ton
    ocean_monthly             SODA ehs5-yac3        monthly    USD/metric ton
    barge_pct_tariff          SODA deqi-uken        weekly     percent of tariff
    barge_per_ton             SODA 7spn-fbua        weekly     USD/ton
    barge_fwd_1m              SODA svms-9yya        weekly     percent of tariff
    barge_fwd_3m              SODA uuhv-5etw        weekly     percent of tariff
    ukraine_ocean_quarterly   SODA 2n8s-739j        quarterly  USD/metric ton

Why one leg is a spreadsheet
----------------------------
The lane preferred the SODA JSON API over the spreadsheets, and six of the seven
datasets take it.  ``ocean_weekly`` cannot: GTRTable1.xlsx is the ONLY publication of
the weekly dollars-per-metric-ton Gulf->Japan and PNW->Japan rate.  The recon's note
that a SODA twin exists points at ``8uye-ieij``, which is the INDEX twin (2017 = 100),
not the rate twin, and whose own column descriptions wrongly say "$/metric ton" -- the
measurement that settles it is written out in the bronze module's docstring and the
refusal is recorded in ``REFUSED_DATASETS``.

User agent -- MEASURED 2026-08-20, and the recon is overturned
---------------------------------------------------------------
The recon says ``ams.usda.gov`` "403s non-browser UAs" and that a browser UA is
mandatory.  Re-probed against ``GTRTable1.xlsx``:

    (no UA header)                                 -> 200, 297,236 bytes
    "leviathan-etl/1.0"                            -> 200, 297,236 bytes
    "Leviathan-GTR/1.0"                            -> 200, 297,236 bytes
    python-requests default                        -> 200, 297,236 bytes
    "Leviathan-Ingest/1.0 (+research data pipeline; contact <addr>)" -> 403

The host is not browser-gated.  What draws the 403 is the long parenthetical-with-
contact UA shape, not the absence of a browser string.  So :data:`_UA` is a short
honest product token.  **No fake browser User-Agent is sent by this producer** -- there
is no access problem that would justify one, and pretending to be Chrome to a host
that answers a truthful token is exactly the evasion the estate refuses.

The AgTransport SODA endpoints gate on nothing: every dataset above answered 200 to
python-urllib's default UA.

Rate limiting
-------------
Government servers, not CDNs.  Sequential requests only, never threaded, with a
:data:`_SLEEP` second pause between every request.  A full backfill is 13 requests
(7 payloads + 6 SODA metadata sidecars) and moves about 12 MB; a weekly run is the
same.  SODA anonymous requests are throttled per IP rather than hard-capped -- an app
token would raise the ceiling and is not needed at this volume, so none is used and
none is stored.

Two modes
---------
backfill
    Pull each dataset's FULL history once into the static ``backfill/`` prefix.
    Every dataset in this family publishes its whole series on one endpoint, so a
    backfill is one request per dataset rather than a year loop.

weekly
    Snapshot every dataset to an immutable ``as_of={YYYYMMDD}/`` key.  GTR publishes
    on Thursday and the SODA datasets are revised IN PLACE -- measured: ``2n8s-739j``
    carries a row whose ``rate`` was absent and later quoted -- so a per-Thursday
    vintage is what preserves what was knowable when, exactly as FGIS and ESR do.

S3 key structure
----------------
    backfill:  raw/production/source=ams_gtr/dataset={dataset}/backfill/{filename}
    weekly:    raw/production/source=ams_gtr/dataset={dataset}/as_of={YYYYMMDD}/{filename}

The SODA legs land two objects: ``full.json`` (the rows) and ``meta.json`` (the
publisher's own column metadata).  ``meta.json`` is not decoration -- it is what makes
the unit an assertion instead of a memory.  Every run checks that the source still
declares the unit this family maps, and FAILS the dataset if it does not.

Update schedule
---------------
Run ``--mode weekly`` every Thursday after GTR publishes (report day is Thursday;
the AgTransport rows land the same morning).  A 15:00 UTC fire is comfortably clear.

Idempotency
-----------
``--skip-existing-s3`` skips keys already in S3 (safe for re-runs).
``--dry-run`` prints the S3 keys and makes no network call at all.

Licence
-------
Public domain.  The AMS datasets page states verbatim: "These data series are
aggregated from non-confidential and non-copyrighted sources."  USDA requests
attribution as "U.S. Department of Agriculture".  ``ocean_monthly`` additionally
carries "SOURCE: O'Neil Commodity Consulting" and that attribution travels with the
bytes in the raw metadata sidecar and on every silver row.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import time
import urllib.parse

import requests
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    AMS_GTR_DATASETS,
    raw_ams_gtr_backfill_key,
    raw_ams_gtr_weekly_key,
)
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3
from leviathan.transforms.raw_to_bronze.ams_gtr import (
    GTR_DATASETS,
    assert_soda_unit_declaration,
    get_dataset,
    soda_metadata_url,
    soda_resource_url,
    transform_gtr_ocean_weekly_xlsx_to_bronze,
    transform_gtr_soda_json_to_bronze,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# A short, honest product token.  See the module docstring for the measurement that
# chose this shape.  NEVER replace it with a browser string.
_UA = "leviathan-gtr/1.0"

_TIMEOUT = 180  # seconds; the largest payload is ~4.3 MB and takes ~7 s

# Government servers, not CDNs.  Sequential only -- concurrency buys nothing here and
# risks a throttle on a host that has no published rate limit to plan against.
_SLEEP = 1.2

# Socrata caps a single page at 50,000 rows.  The largest dataset in this family is
# 30,706 rows, so one page suffices today; the loop exists so that a growing dataset
# does not silently truncate.
_SODA_PAGE = 50_000

# Stable paging order.  Socrata's ``:id`` is the row's internal identifier and is the
# documented way to page deterministically -- paging without an explicit order can
# repeat or skip rows between requests.  Verified live: overlapping pages agree.
_SODA_ORDER = ":id"

_METADATA_FILENAME = "meta.json"

_LICENSE = (
    "US Government public domain. USDA AMS states verbatim of these series: "
    '"These data series are aggregated from non-confidential and non-copyrighted '
    'sources." (https://www.ams.usda.gov/services/transportation-analysis/gtr-datasets). '
    'Attribution requested as "U.S. Department of Agriculture".'
)

# The ZIP local-file-header magic every .xlsx starts with.  A 200 that is not a zip is
# an error page wearing a spreadsheet's URL.
_XLSX_MAGIC = b"PK\x03\x04"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": _UA, "Accept-Encoding": "gzip, deflate"})
    return session


def _get(session: requests.Session, url: str) -> bytes:
    """One polite GET.  Raises for any non-2xx."""
    logger.info("  GET %s", url)
    response = session.get(url, timeout=_TIMEOUT)
    response.raise_for_status()
    data = response.content
    logger.info("    %.1f KB received", len(data) / 1024)
    return data


def _fetch_soda_rows(session: requests.Session, dataset: str) -> bytes:
    """Fetch every row of a SODA dataset, paging deterministically.

    Returns the rows as one canonical JSON array.  When the dataset fits in a single
    page the publisher's own bytes are returned VERBATIM, so the raw object is a
    faithful capture rather than a re-serialisation; only a genuinely paged pull is
    re-encoded, and the fact is logged.

    Raises:
        RuntimeError: If the response is not a JSON array, or if it is empty.
    """
    base = soda_resource_url(dataset)
    pages: list[list] = []
    offset = 0
    first_page_bytes: bytes | None = None

    while True:
        query = urllib.parse.urlencode(
            {"$limit": _SODA_PAGE, "$offset": offset, "$order": _SODA_ORDER}
        )
        raw = _get(session, f"{base}?{query}")
        try:
            records = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"ams_gtr {dataset}: SODA response is not valid JSON: {raw[:200]!r}"
            ) from exc
        if not isinstance(records, list):
            raise RuntimeError(
                f"ams_gtr {dataset}: SODA response is not a JSON array "
                f"({type(records).__name__}) -- {raw[:200]!r}"
            )
        if offset == 0:
            first_page_bytes = raw
        pages.append(records)
        if len(records) < _SODA_PAGE:
            break
        offset += _SODA_PAGE
        time.sleep(_SLEEP)

    total = sum(len(p) for p in pages)
    if total == 0:
        raise RuntimeError(
            f"ams_gtr {dataset}: SODA returned zero rows. An empty payload is never "
            "a normal state for this family -- every dataset has years of history."
        )

    if len(pages) == 1:
        logger.info("  %s: %d rows in one page (bytes kept verbatim)", dataset, total)
        assert first_page_bytes is not None
        return first_page_bytes

    logger.info(
        "  %s: %d rows across %d pages -- re-serialised into one array (the only case "
        "where the raw object is not the publisher's exact bytes)",
        dataset, total, len(pages),
    )
    merged: list = []
    for page in pages:
        merged.extend(page)
    return json.dumps(merged).encode("utf-8")


# ---------------------------------------------------------------------------
# Per-dataset fetch + validate
# ---------------------------------------------------------------------------

def _validate_payload(data: bytes, dataset: str, as_of_date: str) -> None:
    """Prove the payload parses into rows BEFORE it is written to raw.

    This runs the real bronze transform.  A cheap size floor would not catch the
    failures that actually happen here -- an HTML error page served with a 200, or a
    re-laid spreadsheet -- and a byte floor has its own history in this estate of
    refusing legitimately thin data.  Parsing is the stronger check and it costs a
    second.

    Raises:
        Exception: Whatever the transform raises.  Nothing is uploaded on failure.
    """
    spec = get_dataset(dataset)
    ingest_date = datetime.date.today().isoformat()
    if spec.channel == "xlsx":
        if not data.startswith(_XLSX_MAGIC):
            raise RuntimeError(
                f"ams_gtr {dataset}: response is not a ZIP/xlsx container "
                f"(first bytes {data[:8]!r}) -- an error page served as 200."
            )
        frame = transform_gtr_ocean_weekly_xlsx_to_bronze(data, as_of_date, ingest_date)
    else:
        frame = transform_gtr_soda_json_to_bronze(data, dataset, as_of_date, ingest_date)

    if frame.empty:
        raise RuntimeError(f"ams_gtr {dataset}: payload parsed to zero rows.")
    logger.info(
        "  %s: validated -- %d bronze rows, %s .. %s",
        dataset, len(frame), frame["period_date"].min(), frame["period_date"].max(),
    )


def _fetch_dataset(
    session: requests.Session,
    dataset: str,
    as_of_date: str,
) -> list[tuple[str, bytes, str, str]]:
    """Fetch one dataset.

    Returns:
        A list of ``(filename, payload_bytes, source_url, content_type)`` tuples --
        one entry for a spreadsheet leg, two for a SODA leg (rows plus the
        publisher's column metadata).
    """
    spec = get_dataset(dataset)
    out: list[tuple[str, bytes, str, str]] = []

    if spec.channel == "xlsx":
        data = _get(session, spec.endpoint)
        _validate_payload(data, dataset, as_of_date)
        out.append((
            spec.filename, data, spec.endpoint,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ))
        return out

    meta_url = soda_metadata_url(dataset)
    meta_bytes = _get(session, meta_url)
    # Units are asserted from the publisher BEFORE the rows are accepted.  A drifted
    # declaration fails the dataset rather than landing numbers whose meaning changed.
    assert_soda_unit_declaration(meta_bytes, dataset)
    time.sleep(_SLEEP)

    rows = _fetch_soda_rows(session, dataset)
    _validate_payload(rows, dataset, as_of_date)

    out.append((spec.filename, rows, soda_resource_url(dataset), "application/json"))
    out.append((_METADATA_FILENAME, meta_bytes, meta_url, "application/json"))
    return out


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(
    datasets: list[str],
    mode: str,
    as_of_date: str,
    bucket: str,
    region: str,
    skip_existing: bool,
    dry_run: bool,
) -> None:
    """Fetch *datasets* and land them under the mode's raw prefix.

    Args:
        datasets:      Dataset slugs to fetch.
        mode:          ``"backfill"`` (static prefix) or ``"weekly"`` (as_of prefix).
        as_of_date:    Snapshot date ``YYYYMMDD``; the as_of partition in weekly mode
                       and the validation/ingest stamp in both.
        bucket:        S3 bucket name.
        region:        AWS region.
        skip_existing: Skip a dataset whose payload key already exists.
        dry_run:       Print keys, make no network call.
    """

    def key_for(dataset: str, filename: str) -> str:
        if mode == "backfill":
            return raw_ams_gtr_backfill_key(dataset, filename)
        return raw_ams_gtr_weekly_key(dataset, as_of_date, filename)

    if dry_run:
        for dataset in datasets:
            spec = get_dataset(dataset)
            names = [spec.filename]
            if spec.channel == "soda":
                names.append(_METADATA_FILENAME)
            for filename in names:
                print(f"[dry-run] s3://{bucket}/{key_for(dataset, filename)}")
        return

    session = _session()
    uploaded = skipped = failed = 0

    for index, dataset in enumerate(datasets):
        spec = get_dataset(dataset)
        payload_key = key_for(dataset, spec.filename)

        if skip_existing and s3_object_exists(bucket, payload_key, region):
            logger.info("  [skip] already in S3: %s", payload_key)
            skipped += 1
            continue

        logger.info("Fetching %s (%s, %s)", dataset, spec.channel, spec.endpoint)
        try:
            for filename, data, source_url, content_type in _fetch_dataset(
                session, dataset, as_of_date
            ):
                s3_key = key_for(dataset, filename)
                upload_bytes_to_s3(data, bucket, s3_key, region)
                write_raw_s3_metadata(
                    bucket, s3_key, data, source_url, content_type, region,
                    extra={
                        "license": _LICENSE,
                        "attribution": spec.attribution,
                        "dataset": dataset,
                        "unit": spec.unit,
                        "unit_declaration": spec.unit_declaration,
                        "cadence": spec.period_grain,
                        "as_of_date": as_of_date,
                    },
                )
                logger.info("  -> s3://%s/%s", bucket, s3_key)
                uploaded += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("  FAILED dataset=%s -- %s", dataset, exc)
            failed += 1

        if index < len(datasets) - 1:
            time.sleep(_SLEEP)

    logger.info(
        "AMS GTR %s complete. uploaded=%d skipped=%d failed=%d",
        mode, uploaded, skipped, failed,
    )
    if failed:
        raise SystemExit(f"{failed} dataset(s) failed -- see log above.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    today = datetime.date.today()
    default_as_of = today.strftime("%Y%m%d")
    all_datasets = sorted(GTR_DATASETS)

    parser = argparse.ArgumentParser(
        description=(
            "Download the USDA AMS Grain Transportation Report freight family to raw "
            "S3 (AgTransport SODA JSON + GTRTable1.xlsx). No authentication required."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["backfill", "weekly"],
        required=True,
        help=(
            "backfill: pull each dataset's full history once to the static prefix. "
            "weekly: snapshot every dataset to an immutable as_of= key (Thursdays)."
        ),
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=all_datasets,
        metavar="SLUG",
        help=f"Datasets to fetch (default: all {len(all_datasets)}): {', '.join(all_datasets)}",
    )
    parser.add_argument(
        "--as-of",
        default=default_as_of,
        metavar="YYYYMMDD",
        help=f"Snapshot date, the as_of partition in weekly mode (default: {default_as_of}).",
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip a dataset whose payload key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print S3 keys without making any network call.",
    )
    args = parser.parse_args()

    unknown = [d for d in args.datasets if d not in GTR_DATASETS]
    if unknown:
        raise SystemExit(
            f"unknown dataset(s) {unknown}; known: {all_datasets}"
        )
    # The path layer keeps its own copy of the slug set so it stays dependency-free;
    # a divergence would produce keys the transform cannot read back.
    if set(GTR_DATASETS) != set(AMS_GTR_DATASETS):
        raise SystemExit(
            "ams_gtr dataset sets have diverged between GTR_DATASETS and "
            f"paths.AMS_GTR_DATASETS: {sorted(set(GTR_DATASETS) ^ set(AMS_GTR_DATASETS))}"
        )

    if not args.dry_run:
        load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET") if not args.dry_run else "BUCKET"
    region = get_required_env("AWS_REGION") if not args.dry_run else "us-east-1"

    run(
        datasets=list(args.datasets),
        mode=args.mode,
        as_of_date=args.as_of,
        bucket=bucket,
        region=region,
        skip_existing=args.skip_existing_s3,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
