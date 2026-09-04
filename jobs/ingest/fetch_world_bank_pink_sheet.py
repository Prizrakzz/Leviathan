"""Fetch the World Bank Commodity Markets Pink Sheet XLSX to raw S3.

Source
------
World Bank Prospects Group — Commodity Markets ("Pink Sheet")
    https://www.worldbank.org/en/research/commodity-markets

No authentication required.  The file is a publicly accessible XLSX
(~2–3 MB) containing monthly commodity price series back to January 1960.
Because the full history is bundled in every release, one download is
sufficient to bootstrap the entire historical baseline.

URL discovery
-------------
The World Bank uses an opaque document-ID that changes every month, so
there is no stable direct download URL.  This script scrapes the entry-point
page to locate the current "CMO-Pink-Sheet-*.xlsx" href, following the same
pattern documented in ``configs/sources/world_bank_pink_sheet.yaml``.

S3 key structure
----------------
    raw/production/source=world_bank_pink_sheet/
        release={YYYYMmm}/{original_filename}.xlsx

e.g.
    raw/production/source=world_bank_pink_sheet/
        release=2026M05/CMO-Pink-Sheet-May-2026.xlsx

Each monthly release is stored as a separate, immutable object.  This
preserves retroactive WB revisions (WB frequently revises prior months)
and enables exact point-in-time reconstruction of the historical price series.

Update schedule
---------------
The WB publishes around the first Tuesday of each month.  The Airflow DAG
``pink_sheet_monthly_ingest_dag.py`` runs at 14:00 UTC on the first Tuesday
of each month (cron: ``0 14 1-7 * 2``).

THE CONTENT KEY (2026-09-03 RE-ORDER)
-------------------------------------
The object is keyed on the month the WORKBOOK DERIVES -- its last monthly row plus one calendar
month -- never on the page's anchor label.  Measured across six vintages, every self-description the
World Bank ships is wrong in a different one of them: the page label was a month stale on
2026-08-04, the Description sheet's ``Updated as of:`` tail was a month stale in the 2026M05
workbook, and ``'Monthly Prices'!A4`` carried the wrong YEAR in the 2026M01 workbook.  The content
key is the only rule consistent across all six.

Order, and why it is this order:

1. the page label is parsed exactly as before and DEMOTED to a log field -- it keys nothing and
   fences nothing;
2. ``--skip-existing-s3`` is an ADVISORY label-key pre-probe that logs and can never return.  It
   used to return BEFORE the download, which is precisely what made the derived-month re-key
   unreachable on the one incident it was written for: with the page advertising M-1 while the
   workbook already held M, the label key existed, the job returned, and the workbook was never
   fetched;
3. DOWNLOAD, then ``workbook_kind`` (magic bytes: a lying origin and a real legacy .xls are counted
   apart), then ``_validate_xlsx``;
4. derive the release month from the bytes, log any label/derived divergence LOUDLY, and key the
   object on the DERIVED month;
5. the release-recency fence runs on the DERIVED month, below the download, so it measures ADVANCE
   rather than page freshness;
6. FIRST CAPTURE WINS: an already-held derived key is not overwritten (raw is immutable), unless the
   held bytes differ -- a same-key content collision, which is a hard refusal, or ``--force-overwrite``.

``SystemExit`` is reserved for four cases, none of them a plain label disagreement: the bytes are
not a workbook; the derived month is unparseable; the derived month is in the FUTURE relative to
``--asof``; or the derived key is already held by DIFFERENT bytes.

THE COST, STATED.  Every scheduled fire now performs exactly one full workbook GET (0.55-0.75 MB
measured) where today a fire whose label key already existed performed none.  AWS cost is $0
(inbound egress is free, and the S3 PUT still happens only on a genuinely new object); wall time is
+2-6 s per fire.  That is the price of never losing a vintage to a stale label.

Idempotency
-----------
Pass ``--skip-existing-s3`` for the advisory label-key pre-probe (it no longer skips the download).
Pass ``--dry-run`` to print the discovered URL and the page label without downloading; it cannot
print an S3 key, because the key is derived from bytes a dry run does not fetch.
Pass ``--force-overwrite`` to replace a known-bad held capture.
Pass ``--release-month YYYY-MM`` to override the page label (which is now a log field only).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import logging
import re
import zipfile

import requests
from bs4 import BeautifulSoup
from leviathan.common.config import get_required_env, load_env
from leviathan.common.dates import coerce_date
from leviathan.common.logging import get_logger
from leviathan.common.pink_sheet_release import (
    KIND_OLE2,
    KIND_XLSX,
    expected_month_count,
    is_full_restatement,
    monthly_rows,
    release_from_months,
    workbook_kind,
)
from leviathan.storage.paths import raw_pink_sheet_key
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import download_s3_json, s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENTRY_URL = "https://www.worldbank.org/en/research/commodity-markets"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Monthly historical data file (the download target).
# The XLSX filename is static: "CMO-Historical-Data-Monthly.xlsx".
# The opaque document-ID in the URL changes each month.
_XLS_RE = re.compile(r"CMO-Historical-Data-Monthly\.xlsx", re.IGNORECASE)

# Fallback: any href ending in .xlsx on thedocs.worldbank.org
_XLS_FALLBACK_RE = re.compile(r"thedocs\.worldbank\.org.*\.xlsx", re.IGNORECASE)

# The release month is extracted from the accompanying PDF href, which DOES
# contain the month name and year in its filename.
# e.g. "CMO-Pink-Sheet-May-2026.pdf"
_PDF_DATE_RE = re.compile(r"CMO-Pink-Sheet-([A-Za-z]+)-(\d{4})\.pdf", re.IGNORECASE)

# Timeout for all HTTP requests.  Entry page is ~200 KB; XLS is ~2–3 MB.
_PAGE_TIMEOUT = 30
_DOWNLOAD_TIMEOUT = 120


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def _discover_xls_url_from_html(page_html: str) -> tuple[str, str]:
    """Return (xls_url, filename) from already-fetched page HTML."""
    soup = BeautifulSoup(page_html, "html.parser")

    all_hrefs = [tag["href"] for tag in soup.find_all("a", href=True)]

    # Pass 1: look for CMO-Historical-Data-Monthly.xlsx
    for href in all_hrefs:
        if _XLS_RE.search(href):
            url = href if href.startswith("http") else f"https://www.worldbank.org{href}"
            filename = "CMO-Historical-Data-Monthly.xlsx"
            logger.info("Discovered Pink Sheet XLS URL: %s", url)
            return url, filename

    # Pass 2: any xlsx on thedocs.worldbank.org
    for href in all_hrefs:
        if _XLS_FALLBACK_RE.search(href):
            url = href
            filename = href.rstrip("/").split("/")[-1].split("?")[0]
            logger.info("Discovered Pink Sheet XLS URL (fallback): %s", url)
            return url, filename

    raise RuntimeError(
        "Could not locate the Pink Sheet XLSX href on the World Bank commodity-markets "
        f"page ({_ENTRY_URL}). The page structure may have changed. "
        "Check the page manually and update _XLS_RE in this script."
    )


# ---------------------------------------------------------------------------
# Release-month parsing
# ---------------------------------------------------------------------------

def _parse_release_ym_from_page(html: str) -> str | None:
    """Extract the release year-month from the Pink Sheet PDF href on the page.

    The XLSX filename is static (``CMO-Historical-Data-Monthly.xlsx``), so the
    release date is inferred from the accompanying PDF href, which does encode
    the month and year: ``CMO-Pink-Sheet-May-2026.pdf``.

    Returns:
        ``"YYYYMmm"`` string (e.g. ``"2026M05"``), or ``None`` if not found.

    2026-09-01 FIX (the zero-advance RCA): the page now lists MULTIPLE editions' PDF anchors at
    once (measured: ``CMO-Pink-Sheet-August-2026.pdf`` x2 AND ``CMO-Pink-Sheet-July-2026.pdf`` x2
    on one page), and ``.search()`` took whichever appeared FIRST in the HTML -- the archive link
    -- so three catch-up fires in a row derived the stale month and the zero-advance tripwire
    (correctly) refused. The release is now the LATEST month across every anchor on the page.
    """
    found: list[tuple[int, int]] = []
    for month_name, year_str in _PDF_DATE_RE.findall(html):
        try:
            found.append((int(year_str),
                          datetime.datetime.strptime(month_name, "%B").month))
        except ValueError:
            continue
    if not found:
        return None
    year, month_num = max(found)
    return f"{year}M{month_num:02d}"


def _release_ym_from_override(release_month: str) -> str:
    """Convert a ``YYYY-MM`` CLI override to the ``YYYYMmm`` S3 partition format.

    Args:
        release_month: e.g. ``"2026-05"``

    Returns:
        e.g. ``"2026M05"``
    """
    try:
        dt = datetime.datetime.strptime(release_month, "%Y-%m")
    except ValueError:
        raise ValueError(
            f"--release-month must be in YYYY-MM format, got: {release_month!r}"
        )
    return f"{dt.year}M{dt.month:02d}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_xlsx(data: bytes, source_url: str) -> None:
    """Validate that *data* is a well-formed XLSX (ZIP) file.

    XLSX files are ZIP archives.  We perform two checks:
    1. Magic bytes: first two bytes must be ``PK`` (0x50 0x4B).
    2. Open with :mod:`zipfile` to confirm structural integrity.
    3. Minimum size check via :func:`check_min_file_size`.

    We deliberately do NOT open the file with openpyxl here — that is a heavy
    dependency and belongs in the bronze transform, not the raw ingest layer.

    Raises:
        RuntimeError: If any check fails.
    """
    # Magic bytes (ZIP / XLSX)
    if len(data) < 4 or data[:2] != b"PK":
        raise RuntimeError(
            f"Validation failed: response from {source_url} does not have XLSX/ZIP "
            f"magic bytes. Got: {data[:8]!r}. Possible HTML error page."
        )

    # Structural integrity
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise RuntimeError(
            f"Validation failed: response from {source_url} is not a valid ZIP/XLSX "
            f"file: {exc}"
        ) from exc

    # Sanity: at minimum an xl/ directory should be present in a real XLSX
    if not any(n.startswith("xl/") for n in names):
        raise RuntimeError(
            f"Validation failed: ZIP from {source_url} does not look like a valid XLSX "
            f"(no xl/ entries found). Contents: {names[:10]}"
        )

    # Minimum size check
    check_min_file_size(data, "world_bank_pink_sheet", context=source_url)


def _held_sha256(bucket: str, s3_key: str, region: str) -> str | None:
    """The sha256 the raw_meta sidecar recorded for an already-held object, or ``None``.

    ``None`` means "the sidecar does not say", never "the bytes match": a missing or unreadable
    sidecar cannot certify a collision either way, so the caller treats it as unrecorded and keeps
    first-capture-wins rather than overwriting on a guess.
    """
    try:
        return str(download_s3_json(bucket, f"raw_meta/{s3_key}_meta.json", region)
                   .get("sha256") or "") or None
    except Exception:  # noqa: BLE001 -- a missing/unreadable sidecar is an ABSENT answer, not an error
        logger.info("no readable raw_meta sidecar for %s -- sha comparison unavailable", s3_key)
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download the World Bank Commodity Markets Pink Sheet XLSX to raw S3. "
            "Scrapes the WB commodity-markets page to discover the current monthly "
            "download URL (the document ID is opaque and changes each month). "
            "No authentication required."
        )
    )
    parser.add_argument(
        "--release-month",
        metavar="YYYY-MM",
        default=None,
        help=(
            "Override the PAGE LABEL only. It KEYS NOTHING: since the 2026-09-03 re-order the "
            "object is filed under the month the WORKBOOK derives (last monthly row + 1), because "
            "each of the workbook's own stamps and the page label was wrong in a different one of "
            "the six measured vintages. This flag now only changes the label the divergence warning "
            "and the advance fence quote. TO RECOVER A PRIOR MONTH you must fetch the BYTES of that "
            "release: run jobs/ingest/backfill_pink_sheet_vintages.py (retired document-ID epochs, "
            "then the Wayback archive), which lands under the ARCHIVE raw prefix. The declared "
            "2026M06 hole is NOT recoverable through this flag -- the current page serves the "
            "current workbook, and a label override would only re-file today's bytes under a lie."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help=(
            "ADVISORY label-key pre-probe: log whether the PAGE LABEL's key already exists. It no "
            "longer skips the download -- the object is keyed on the month the WORKBOOK derives, "
            "and the upload is skipped on THAT key (first capture wins) after the bytes have "
            "spoken. Keeping the flag's old meaning would make the derived-month re-key unreachable "
            "on exactly the stale-label fire it exists for."
        ),
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help=(
            "Replace an already-held raw object. Raw is immutable by contract, so this is an OWNER "
            "action on a known-bad capture (a truncated or wrong-month first capture); without it a "
            "same-key content collision is a hard refusal. It is answered BEFORE the sha compare, so "
            "it also repairs the interrupted-first-capture shape -- an object whose raw_meta sidecar "
            "is missing or unreadable, where no held sha exists to differ from."
        ),
    )
    parser.add_argument(
        "--asof",
        default=None,
        help="Scheduled-time ISO the release-recency fence measures against. Default: today (UTC).",
    )
    parser.add_argument(
        "--max-release-lag-months",
        type=int,
        default=1,
        dest="max_release_lag_months",
        help=(
            "Advance fence: fail if the release discovered on the WB page is more than this "
            "many calendar months behind --asof. Default 1 (the WB publishes monthly, around "
            "the first Tuesday; a fire on the 4th legitimately sees month-1, never month-2)."
        ),
    )
    parser.add_argument(
        "--no-advance-fence",
        dest="advance_fence",
        action="store_false",
        default=True,
        help="Disable the D-SG G2-1 release-recency fence (deliberate historical reruns only).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Discover the URL and print the page LABEL without downloading anything. It CANNOT "
            "print the S3 key: the key is derived from the workbook's own content, which a dry run "
            "has not fetched, so it prints that the key is unknown rather than a key the live run "
            "will not use."
        ),
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    # Fetch the entry page once — needed for both URL discovery and release-month
    # extraction (the PDF href encodes the month name we need).
    logger.info("Fetching entry page: %s", _ENTRY_URL)
    page_resp = session.get(_ENTRY_URL, timeout=_PAGE_TIMEOUT)
    page_resp.raise_for_status()
    page_html = page_resp.text

    # Discover the current XLS download URL.
    xls_url, filename = _discover_xls_url_from_html(page_html)

    # Determine the release year-month for the S3 partition.
    if args.release_month:
        release_ym = _release_ym_from_override(args.release_month)
    else:
        release_ym = _parse_release_ym_from_page(page_html)
        if release_ym is None:
            today = datetime.date.today()
            release_ym = f"{today.year}M{today.month:02d}"
            logger.warning(
                "Could not extract release month from PDF href on page; "
                "defaulting to current calendar month: %s. "
                "Use --release-month to override.",
                release_ym,
            )

    # THE LABEL IS A LOG FIELD, NOT A KEY (2026-09-03 re-order). It keys no object and fences
    # nothing; the workbook's own content decides both. See the module docstring's
    # "CONTENT KEY" section for why.
    label_ym = release_ym

    # ------------------------------------------------------------------
    # Dry run -- it cannot print an S3 key it has not derived, and it does not download.
    # Stating an unknown as unknown is cheaper than printing a key the live run will not use.
    # ------------------------------------------------------------------
    if args.dry_run:
        print(f"Entry page : {_ENTRY_URL}")
        print(f"XLS URL    : {xls_url}")
        print(f"Filename   : {filename}")
        print(f"Page label : {label_ym}")
        print("S3 key     : <derived after download; --dry-run does not download>")
        return

    # ------------------------------------------------------------------
    # Live run
    # ------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    # ADVISORY LABEL-KEY PRE-PROBE. It logs and NOTHING ELSE -- it can never `return`.
    # It used to return here, and that is exactly what made the derived-month re-key
    # unreachable on the one incident it was written for: with the page advertising M-1 while the
    # workbook already held M, the LABEL key already existed, the job returned, and the workbook was
    # never downloaded. The real skip is the first-capture-wins upload skip below, on the DERIVED
    # key, after the bytes have spoken.
    if args.skip_existing_s3:
        _label_key = raw_pink_sheet_key(label_ym, filename)
        logger.info("label-key pre-probe: %s exists=%s (advisory only -- the derived key decides)",
                    _label_key, s3_object_exists(bucket, _label_key, region))

    logger.info("Downloading Pink Sheet XLSX from %s …", xls_url)
    resp = session.get(xls_url, timeout=_DOWNLOAD_TIMEOUT, stream=False)
    resp.raise_for_status()
    data = resp.content

    logger.info("Downloaded %.2f MB", len(data) / 1_048_576)

    # MAGIC BYTES BEFORE ANYTHING ELSE. `_validate_xlsx` also refuses non-PK bytes, but it reports
    # "possible HTML error page" for every failure alike; `workbook_kind` separates a LYING ORIGIN
    # (an HTML body under an xlsx Content-Type -- measured on the 2016 document-ID epoch, 100,826
    # bytes beginning `<!DOCTYPE`) from a REAL legacy .xls (OLE2/BIFF), which is a supported-format
    # question and not a broken-response one. The two must be counted apart or the decline census
    # cannot tell them apart either.
    kind = workbook_kind(data)
    if kind != KIND_XLSX:
        raise SystemExit(
            f"NOT A WORKBOOK: {xls_url} returned {len(data):,} bytes classified {kind!r} "
            f"(first 8 bytes {data[:8]!r}). "
            + ("A real legacy .xls (OLE2/BIFF) -- openpyxl cannot read it and this lane does not "
               "support the format; the era is a declared refusal, never a loosened gate."
               if kind == KIND_OLE2 else
               "The origin served something that is not a workbook at all under an xlsx "
               "content type. Nothing is landed.")
        )

    _validate_xlsx(data, xls_url)
    logger.info("Validation passed — %d bytes, well-formed XLSX", len(data))

    # ---- THE CONTENT KEY ----------------------------------------------------
    # The workbook decides which release it is: last monthly row + one calendar month. Each of the
    # workbook's own stamps is wrong in a different one of the six measured vintages (the Description
    # tail was a month stale in 2026M05; 'Monthly Prices'!A4 carried the wrong YEAR in 2026M01), and
    # the page label was a month stale on 2026-08-04. The content key is the only rule consistent
    # across all six.
    # ONE parse of the workbook, not two: the month rows are needed for the full-restatement check
    # anyway, and `release_from_months` is the same rule `derived_release_ym` applies to them.
    try:
        months = monthly_rows(data)
        derived_ym = release_from_months(months)
    except ValueError as exc:
        raise SystemExit(
            f"UNPARSEABLE CONTENT KEY: {exc}. The object is NOT filed under the page label "
            f"{label_ym!r} -- a guessed month writes a permanently quotable wrong knowledge date. "
            f"Nothing is landed."
        ) from exc

    n_expected = expected_month_count(derived_ym)
    # Measured against the DERIVED month, which is the only one that exists here: the page label
    # keys nothing and there is no declared stamp until bronze carries one. That leaves ONE shape
    # this check cannot see -- a trailing labelled-but-blank monthly row, which files one month high
    # and self-certifies -- and it is caught downstream in build_silver_vintages, where the release
    # the rows are FILED under is available to measure against.
    full = is_full_restatement(months, derived_ym)
    if full:
        logger.info("content key: derived=%s months=%d expected=%d full-restatement=yes",
                    derived_ym, len(months), n_expected)
    else:
        # NOT A REFUSAL. A hole or a duplicate month makes the release unusable as a VINTAGE (the
        # bitemporal table's one-clock guarantee rests on every release being a full as-published
        # history), but the bytes are still the raw asset and are still the latest-only builder's
        # input. It lands, LOUDLY counted, and the vintage builder's own G-A1 gate is where a
        # non-restatement is refused -- one refusal, at the layer whose invariant it breaks.
        #
        # THE SENTENCE BELOW NAMES WHAT THE BUILDER ACTUALLY DOES, not what would be convenient:
        # build_silver_vintages QUARANTINES this release under the counted name
        # `not_full_restatement` and builds every OTHER release normally. It does not abort the
        # table, and the row never reaches silver -- so the served latest-only table still consumes
        # these bytes while the bitemporal table declares the release missing, by name, in its own
        # run log.
        logger.warning(
            "NOT A FULL RESTATEMENT: derived=%s carries %d monthly rows against the %d a hole-free "
            "1960M01..%s history requires (duplicates or gaps). The bytes still land as raw -- raw "
            "is the asset -- but this release cannot serve as a VINTAGE: build_silver_vintages will "
            "QUARANTINE it under 'not_full_restatement' (a counted decline in the vintages run log, "
            "not an aborted table) and it will be ABSENT from silver_pink_sheet_vintages. "
            "Investigate before it is bronzed.",
            derived_ym, len(months), n_expected, derived_ym,
        )

    if derived_ym != label_ym:
        logger.warning(
            "content-key divergence: page label %s, workbook derives %s -- filing under the "
            "DERIVED month", label_ym, derived_ym,
        )

    release_ym = derived_ym
    s3_key = raw_pink_sheet_key(release_ym, filename)

    # ---- D-SG G2-1(c) RELEASE-RECENCY FENCE, RE-BASED ON THE DERIVED MONTH ---
    # It used to fence on the LABEL, before any download. That measured PAGE FRESHNESS, not
    # ADVANCE: a correctly-advancing workbook behind a stale label went hard-RED, and a stale
    # workbook behind a fresh label passed. Keyed on the derived month it measures the thing its
    # name claims. Same --max-release-lag-months semantics, same failure text, plus the label it
    # disagreed with.
    if args.advance_fence:
        _asof = coerce_date(args.asof)
        _rel_year, _rel_month = int(release_ym[:4]), int(release_ym[5:7])
        _lag = (_asof.year - _rel_year) * 12 + (_asof.month - _rel_month)
        if _lag < 0:
            raise SystemExit(
                f"FUTURE RELEASE: the workbook derives release {release_ym}, which is "
                f"{-_lag} calendar month(s) AHEAD of asof {_asof.isoformat()}. A workbook cannot "
                f"have been published after the moment it was fetched; either the derived clock or "
                f"--asof is wrong. Nothing is landed."
            )
        if _lag > args.max_release_lag_months:
            raise SystemExit(
                f"ZERO-ADVANCE: the World Bank workbook derives release {release_ym} "
                f"(the page label said {label_ym}), which is {_lag} calendar months behind asof "
                f"{_asof.isoformat()} (limit {args.max_release_lag_months}). Either the WB "
                "has stopped publishing, or the download URL is serving a stale workbook. This "
                "fire would have re-downloaded an already-held release and exited 0."
            )
        logger.info(
            "release-recency fence OK: release=%s (label=%s), lag=%d month(s) behind asof=%s",
            release_ym, label_ym, _lag, _asof.isoformat(),
        )

    # ---- FIRST-CAPTURE-WINS UPLOAD SKIP -------------------------------------
    # Raw is IMMUTABLE by contract: one object per release, never overwritten. If the derived key is
    # already held we exit 0 without uploading -- unless the held bytes are DIFFERENT, which is a
    # same-key content collision and must never be resolved silently, or --force-overwrite says the
    # owner has decided to replace a known-bad capture.
    #
    # WHAT THIS LEAVES INVISIBLE, SAID OUT LOUD: a SAME-MONTH regeneration (the WB re-posting the
    # same release with revised numbers) keeps the FIRST bytes. The compare that would catch it is
    # Last-Modified + Content-Length or a full digest against the sidecar -- NOT ETag, which these
    # objects do not serve (measured). That is the standing mid-month-recheck docket; it now costs a
    # REVISION rather than a whole vintage.
    if s3_object_exists(bucket, s3_key, region):
        held_sha = _held_sha256(bucket, s3_key, region)
        new_sha = hashlib.sha256(data).hexdigest()
        # --force-overwrite IS ANSWERED BEFORE THE COMPARISON, and that ordering is the whole point.
        # `_held_sha256` returns None when the raw_meta sidecar is MISSING or UNREADABLE -- which is
        # exactly the shape of the interrupted first capture the flag exists to repair, because
        # write_raw_s3_metadata runs AFTER the upload and never re-raises. Inside the
        # `held_sha and held_sha != new_sha` branch the flag was unreachable on precisely that case:
        # control fell through to the "already held" return and the owner's explicit instruction was
        # ignored in silence.
        if args.force_overwrite:
            logger.warning(
                "--force-overwrite: replacing %s (held sha %s, new sha %s...). This is an OWNER "
                "action on a known-bad capture; raw immutability is being deliberately broken.",
                s3_key, f"{held_sha[:16]}..." if held_sha else "UNRECORDED (no readable sidecar)",
                new_sha[:16],
            )
        elif held_sha and held_sha != new_sha:
            raise SystemExit(
                f"SAME-KEY CONTENT COLLISION: {s3_key} is already held with sha256 "
                f"{held_sha[:16]}... and these bytes are {new_sha[:16]}.... Raw is immutable, so "
                f"this is either a World Bank re-release under the same derived month or a "
                f"corrupted capture -- both need a decision, neither may be resolved silently. "
                f"Delete the object and its raw_meta sibling to re-capture, or re-run with "
                f"--force-overwrite once you know which bytes are right."
            )
        else:
            logger.info(
                "already held under the derived key -- not overwriting (raw is immutable): %s "
                "(sha %s)", s3_key,
                "matches" if held_sha == new_sha else "unrecorded in the sidecar",
            )
            return

    upload_bytes_to_s3(data, bucket, s3_key, region)
    logger.info("Uploaded → s3://%s/%s", bucket, s3_key)

    write_raw_s3_metadata(
        bucket,
        s3_key,
        data,
        xls_url,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        region,
        # THE ORIGIN CLOCK MUST BE RECORDED AT CAPTURE OR IT IS GONE FOREVER. Last-Modified is rung
        # 1 of the release-clock ladder; without it every vintage falls back to the first of its
        # derived month, which the six measured Description stamps put 1-5 days EARLY. These
        # objects serve NO ETag (measured), so Last-Modified + Content-Length is the pair.
        extra={
            "http_last_modified": resp.headers.get("Last-Modified"),
            "http_content_length": resp.headers.get("Content-Length"),
            "derived_release_ym": derived_ym,
            "page_label_release_ym": label_ym,
            "expected_month_count": n_expected,
            "observed_month_count": len(months),
            "is_full_restatement": bool(full),
        },
    )
    logger.info("Metadata written → raw_meta/%s_meta.json", s3_key)


if __name__ == "__main__":
    main()
