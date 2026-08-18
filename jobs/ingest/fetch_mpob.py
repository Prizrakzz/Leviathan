"""Fetch MPOB BEPI palm oil reports (HTML tables and PDFs) to raw S3.

Three report series are downloaded:

  annual_summary   — "Summary Of The Malaysian Palm Oil Industry {year}"
                     One HTML page per calendar year; national CPO production,
                     closing stocks, exports, imports, FFB price (all months).
                     bepi.mpob.gov.my/stat/web_report1.php?val={YYYY}84

  monthly_release  — "{Month} {year}"
                     One HTML page per calendar month; same variables plus
                     regional breakdown (Peninsular Malaysia / Sabah / Sarawak).
                     bepi.mpob.gov.my/stat/web_report1.php?val={YYYY}75&val1={MM}

  overview_pdf     — "Overview of Industry {year}"
                     Annual PDF report covering production, trade, prices and
                     area statistics.  Primary source for pre-2017 data.
                     bepi.mpob.gov.my/images/overview/Overview_of_Industry_{year}.pdf

Discovery strategy
------------------
All report URLs are stored in a static manifest produced by the probe script:
  configs/sources/mpob_archive.yaml

The BEPI stat server has NO archive listing for monthly releases: the
``{YYYY}75`` root serves only the LATEST published month and rolls older
``val1`` slots back to an "under construction" placeholder once superseded.
A static manifest therefore ages out the moment MPOB publishes a month nobody
hand-added (month=05/2026 was lost exactly this way: published ~Jun 10, rolled
off ~Jul 10 when June superseded it, zero Wayback captures).

``--refresh-manifest`` closes that class: before fetching, it probes all 12
monthly ``val1`` slots (plus the annual base) for the current and previous
year and merges any published slot the manifest has never heard of -- the
WASDE archive-head merge (fetch_usda_wasde.py), adapted to a site whose
archive is not enumerable. It fails closed (exit 1) when the sweep finds zero
published monthly slots. ``--save-manifest`` appends adopted entries back to
the YAML (a dev convenience; the scheduled container's filesystem is
ephemeral, so the in-memory merge is what makes a scheduled run complete).
There is deliberately no full ``--discover`` rebuild: only the latest month
is ever visible, so a rebuild would erase manifest history, not rediscover it.

MPOB BEPI (bepi.mpob.gov.my) is a Joomla CMS site with no WAF; standard
``requests`` with a Chrome User-Agent works without fingerprint bypass.

S3 key structure
----------------
  annual_summary:
    raw/production/source=mpob/release_type=annual_summary/
        year={YYYY}/mpob_annual_summary_{YYYY}.html

  monthly_release:
    raw/production/source=mpob/release_type=monthly_release/
        year={YYYY}/month={MM}/mpob_monthly_{YYYY}_{MM}.html

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip pages already uploaded.  Re-running with
this flag is safe and fast.  Use ``--limit 1`` for a quick smoke-test.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import yaml
from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import (
    raw_mpob_annual_key,
    raw_mpob_monthly_key,
    raw_mpob_overview_pdf_key,
)
from leviathan.storage.raw_metadata import check_min_file_size, write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Validation marker — every MPOB BEPI palm oil table page contains this string
_TABLE_MARKER = "CRUDE PALM OIL"


class _ContentValidationMiss(Exception):
    """An HTTP-200 page that lacks the expected palm-oil table marker.

    MPOB's stat server serves ``This page is under construction`` (HTTP 200,
    ~32 bytes) for a monthly_release ``val1`` slot until that month is
    published — and rolls older months back to that placeholder once a newer
    release supersedes them.  For a monthly_release entry this is a not-yet-
    published (or rolled-off) month, so ``main`` downgrades it to a soft miss
    (WARNING + tally) rather than failing the whole autonomous chain.  All
    other entry classes keep treating a marker miss as fatal.
    """


def _is_unpublished_month(release_type: str, exc: BaseException) -> bool:
    """Return True when *exc* is a monthly_release content-validation miss.

    Only a marker-absent HTTP-200 page (``_ContentValidationMiss``) on a
    ``monthly_release`` entry qualifies as a soft miss.  HTTP errors, S3
    failures, bad PDFs, and marker misses on other entry classes all stay
    fatal.
    """
    return isinstance(exc, _ContentValidationMiss) and release_type == "monthly_release"


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent / "configs" / "sources" / "mpob_archive.yaml"
)

# ---------------------------------------------------------------------------
# Monthly-slot discovery (D-LD MPOB retrofit, 2026-08-18)
# ---------------------------------------------------------------------------
# BEPI has no monthly archive listing: the {YYYY}75 root serves ONLY the latest
# published month, and older val1 slots roll back to the under-construction
# placeholder once superseded. Discovery is therefore a constructive probe of
# every slot per year-base, not a listing scrape -- and a full manifest REBUILD
# is impossible from the live site (only the latest month is visible), which is
# why this fetcher has --refresh-manifest but no --discover.

_STAT_BASE = "https://bepi.mpob.gov.my/stat/web_report1.php"
_MONTHLY_VAL_SUFFIX = "75"
_ANNUAL_VAL_SUFFIX = "84"

# The val+val1 monthly format starts at 2026: 2021-2025 have no monthly pages
# in this format (exhaustive art=1008-1248 scan) and 2020's twelve slots all
# serve the placeholder -- see the manifest's monthly section notes.
_MONTHLY_FORMAT_FLOOR_YEAR = 2026


def _monthly_stat_url(year: int, month: int) -> str:
    return f"{_STAT_BASE}?val={year}{_MONTHLY_VAL_SUFFIX}&val1={month:02d}"


def _annual_stat_url(year: int) -> str:
    return f"{_STAT_BASE}?val={year}{_ANNUAL_VAL_SUFFIX}"


def _entry_label(entry: dict) -> str:
    month = entry.get("month")
    base = f"{entry['release_type']}/{entry['year']}"
    return f"{base}/{month:02d}" if month is not None else base


def _probe_years(today: date) -> list[int]:
    """Year bases the refresh sweep probes: current + previous, floored at 2026.

    The previous year matters at the January boundary: the December release
    publishes ~Jan 10 under the OLD year's val base.
    """
    return [y for y in (today.year, today.year - 1) if y >= _MONTHLY_FORMAT_FLOOR_YEAR]


def _sweep_stat_slots(
    session: requests.Session,
    years: list[int],
    sleep_seconds: float,
) -> tuple[list[dict], int, int]:
    """Probe every monthly val1 slot (and the annual base) for *years*.

    Returns ``(published_entries, placeholder_count, error_count)``. A slot is
    PUBLISHED on HTTP 200 with the palm-oil table marker, a PLACEHOLDER on
    HTTP 200 without it (the under-construction state), and an ERROR on
    anything else. Errors are counted, never raised, so one bad slot cannot
    mask what the rest of the sweep proved -- the caller decides whether the
    sweep as a whole is trustworthy (see the zero-published rule in main).
    """
    published: list[dict] = []
    placeholders = 0
    errors = 0
    for year in years:
        for month in range(1, 13):
            url = _monthly_stat_url(year, month)
            try:
                html_text = _download_html(url, session)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Sweep probe failed %d/%02d (%s): %s", year, month, url, exc)
                errors += 1
            else:
                if _TABLE_MARKER in html_text.upper():
                    published.append(
                        {
                            "release_type": "monthly_release",
                            "year": year,
                            "month": month,
                            "stat_url": url,
                        }
                    )
                    logger.info("Sweep: %d/%02d PUBLISHED", year, month)
                else:
                    placeholders += 1
            time.sleep(sleep_seconds)
        # The annual summary rides the same sweep with the same adopt-if-absent
        # semantics (a new year's {YYYY}84 entry otherwise needs a hand-add every
        # Q1), but it never counts toward the monthly fail-closed rule: a new
        # year's annual is legitimately absent for most of the year.
        annual_url = _annual_stat_url(year)
        try:
            html_text = _download_html(annual_url, session)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sweep probe failed annual/%d (%s): %s", year, annual_url, exc)
            errors += 1
        else:
            if _TABLE_MARKER in html_text.upper():
                published.append(
                    {
                        "release_type": "annual_summary",
                        "year": year,
                        "stat_url": annual_url,
                    }
                )
                logger.info("Sweep: annual %d PUBLISHED", year)
            else:
                placeholders += 1
        time.sleep(sleep_seconds)
    return published, placeholders, errors


def _merge_manifest(
    releases: list[dict],
    discovered: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Adopt discovered entries whose (release_type, year, month) is absent.

    Unlike WASDE there is no correction case: a slot's URL is fully determined
    by (year, month), so a known entry is always left byte-identical and the
    merge is a no-op on a quiet day. Existing entries are never reordered (the
    manifest's section layout is operator documentation); adopted entries
    append at the end, which the fetch loop is indifferent to. Returns
    ``(merged, adopted)``.
    """
    have = {(e["release_type"], e["year"], e.get("month")) for e in releases}
    adopted = [
        e for e in discovered if (e["release_type"], e["year"], e.get("month")) not in have
    ]
    return releases + adopted, adopted


def _append_manifest_entries(adopted: list[dict]) -> None:
    """Append adopted entries to the manifest YAML without touching its body.

    The manifest is heavily commented operator documentation, so the WASDE
    approach (rewrite everything below the header) would destroy it. The file
    ends inside the ``releases:`` list, so same-indent items appended at the
    end are valid list members -- entry order carries no meaning to the fetch
    loop.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "",
        f"  # --- adopted by fetch_mpob.py --refresh-manifest --save-manifest ({stamp}) ---",
        "",
    ]
    for e in adopted:
        lines.append(f"  - release_type: {e['release_type']}")
        lines.append(f"    year: {e['year']}")
        if e.get("month") is not None:
            lines.append(f"    month: {e['month']}")
        lines.append(f'    stat_url: "{e["stat_url"]}"')
        lines.append("")
    with _MANIFEST_PATH.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _download_html(url: str, session: requests.Session, timeout: int = 30) -> str:
    resp = session.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int | None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download MPOB BEPI palm oil HTML table pages to raw S3. "
            "Reads URLs from configs/sources/mpob_archive.yaml."
        )
    )
    parser.add_argument(
        "--refresh-manifest",
        action="store_true",
        help=(
            "Before fetching, probe all 12 monthly val1 slots (plus the annual base) for "
            "the current + previous year and merge any published slot the manifest has "
            "never heard of. Exits 1 when the sweep finds ZERO published monthly slots -- "
            "the {YYYY}75 root always serves the latest month once any month exists, so an "
            "empty sweep is a probe fault or site regression, never a quiet month. There "
            "is no full --discover rebuild: only the latest month is ever visible."
        ),
    )
    parser.add_argument(
        "--save-manifest",
        action="store_true",
        help=(
            "With --refresh-manifest: append adopted entries to the manifest YAML "
            "(dev convenience; the scheduled container's filesystem is ephemeral)."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip pages whose S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print all S3 keys and source URLs without downloading anything.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="Polite delay between HTTP requests in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N entries — use 1 for a smoke test.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Process only entries for this calendar year.",
    )
    parser.add_argument(
        "--release-type",
        choices=["annual_summary", "monthly_release", "overview_pdf"],
        default=None,
        help="Process only this release type (default: all).",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load manifest
    # -----------------------------------------------------------------------
    manifest_data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    releases: list[dict] = manifest_data["releases"]
    logger.info("Loaded %d entries from manifest %s", len(releases), _MANIFEST_PATH.name)

    # -----------------------------------------------------------------------
    # Manifest refresh (runs before filters and before any AWS access)
    # -----------------------------------------------------------------------
    if args.refresh_manifest:
        sweep_session = requests.Session()
        sweep_session.headers.update({"User-Agent": _UA})
        years = _probe_years(datetime.now(timezone.utc).date())
        discovered, placeholders, probe_errors = _sweep_stat_slots(
            sweep_session, years, args.sleep_seconds
        )
        sweep_session.close()
        monthly_found = [e for e in discovered if e["release_type"] == "monthly_release"]
        if not monthly_found:
            # The {YYYY}75 root serves the latest month whenever ANY month has
            # published, so a zero-published sweep is a probe fault or a site
            # regression (the 2020 all-placeholder state), never a quiet month.
            # Proceeding on the static manifest is the silent-miss class that
            # lost month=05/2026 -- fail closed instead.
            logger.error(
                "MANIFEST REFRESH FAILED: swept years %s and found ZERO published "
                "monthly slots (placeholders=%d, probe_errors=%d) -- exiting 1 rather "
                "than proceeding on the static manifest.",
                years,
                placeholders,
                probe_errors,
            )
            return 1
        releases, adopted = _merge_manifest(releases, discovered)
        logger.info(
            "Manifest refresh: years %s -> %d published slot(s) (placeholders=%d, "
            "probe_errors=%d); adopted: %s",
            years,
            len(discovered),
            placeholders,
            probe_errors,
            [_entry_label(e) for e in adopted] or "none",
        )
        if args.save_manifest and adopted:
            _append_manifest_entries(adopted)
            logger.info(
                "Appended %d adopted entrie(s) to %s", len(adopted), _MANIFEST_PATH.name
            )

    # -----------------------------------------------------------------------
    # Apply filters
    # -----------------------------------------------------------------------
    if args.year is not None:
        releases = [r for r in releases if r["year"] == args.year]
    if args.release_type is not None:
        releases = [r for r in releases if r["release_type"] == args.release_type]
    if args.limit:
        releases = releases[: args.limit]

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(
            f"Manifest: {_MANIFEST_PATH.name}  "
            f"({len(releases)} entries after filters)"
        )
        for entry in releases:
            rt = entry["release_type"]
            year = entry["year"]
            month = entry.get("month")
            if rt == "annual_summary":
                s3_key = raw_mpob_annual_key(year)
            elif rt == "monthly_release":
                s3_key = raw_mpob_monthly_key(year, month)
            else:
                s3_key = raw_mpob_overview_pdf_key(year)
            # ASCII-only: the dry run is the recommended local verification and
            # Windows consoles are cp1252.
            print(f"  {rt:<20}  {year}/{month or '--':>2}  ->  {s3_key}")
        return None

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = missing = errors = 0

    session = requests.Session()
    session.headers.update({"User-Agent": _UA})

    for entry in releases:
        rt = entry["release_type"]
        year = entry["year"]
        month = entry.get("month")
        url = entry["stat_url"]

        if rt == "annual_summary":
            s3_key = raw_mpob_annual_key(year)
            label = f"annual_summary/{year}"
        elif rt == "monthly_release":
            s3_key = raw_mpob_monthly_key(year, month)
            label = f"monthly_release/{year}/{month:02d}"
        else:
            s3_key = raw_mpob_overview_pdf_key(year)
            label = f"overview_pdf/{year}"

        try:
            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            logger.info("Downloading %s  %s …", label, url)

            if rt == "overview_pdf":
                resp = session.get(url, timeout=60, allow_redirects=True)
                resp.raise_for_status()
                payload = resp.content
                if not payload.startswith(b"%PDF"):
                    raise RuntimeError(
                        f"Validation failed: response is not a PDF (magic bytes missing) from {url}"
                    )
                check_min_file_size(payload, "mpob_overview_pdf", context=url)
                content_type = "application/pdf"
            else:
                html_text = _download_html(url, session)
                if _TABLE_MARKER not in html_text.upper():
                    raise _ContentValidationMiss(
                        f"Validation failed: '{_TABLE_MARKER}' not found in response from {url}"
                    )
                payload = html_text.encode("utf-8")
                check_min_file_size(payload, "mpob", context=url)
                content_type = "text/html; charset=utf-8"

            upload_bytes_to_s3(payload, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket,
                s3_key,
                payload,
                url,
                content_type,
                region,
            )

            logger.info(
                "Uploaded %s  (%.1f KB) → s3://%s/%s",
                label,
                len(payload) / 1_024,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            # A not-yet-published (or rolled-off) monthly_release month returns
            # HTTP 200 without the table marker; that must not fail an autonomous
            # chain, so downgrade it to a soft miss. Everything else stays fatal.
            if _is_unpublished_month(rt, exc):
                logger.warning("Not yet published — skipping %s (%s): %s", label, url, exc)
                missing += 1
            else:
                logger.error("Failed %s (%s): %s", label, url, exc)
                errors += 1

        time.sleep(args.sleep_seconds)

    session.close()

    logger.info(
        "Done. uploaded=%d  skipped=%d  missing=%d  errors=%d",
        uploaded,
        skipped,
        missing,
        errors,
    )

    if errors:
        raise SystemExit(f"{errors} report(s) failed — see logs above.")


if __name__ == "__main__":
    raise SystemExit(main())
