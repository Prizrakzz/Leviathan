"""Fetch UNICA (Brazilian CS) production-and-milling HTML pages to raw S3.

Discovery strategy
------------------
The UNICADATA portal (unicadata.com.br) is fully JavaScript-rendered: tables
load via AJAX after the user interacts with the form.  This job uses Playwright
(headless Chromium) to:

  1. Navigate to the production-and-milling history page.
  2. For each harvest year: locate the two harvest-year <select> dropdowns,
     set both to the target year, click the submit button, and wait for the
     table to appear in the DOM.
  3. Capture the full rendered HTML and upload it to S3.

Selector discovery
------------------
On the first run use ``--debug-html`` to dump the raw page source before any
interaction.  This lets you verify the actual select/button selectors the site
uses and update the code if needed.

Idempotency
-----------
Pass ``--skip-existing-s3`` to skip harvest years already uploaded.  Re-running
with this flag is safe and fast.  Use ``--harvest-years 2024/25`` to target a
single year.

Docker / ECS Fargate notes
--------------------------
Chromium requires ``--no-sandbox`` and ``--disable-gpu`` when running inside
a container with no user-namespace support (ECS Fargate).  These flags are
applied unconditionally.  The Docker image must have Playwright and its system
dependencies installed (see Dockerfile).
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import unica_raw_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MANIFEST_PATH = Path(__file__).parent.parent.parent / "configs" / "sources" / "unica_sources.yaml"

# Minimum plausible HTML size: a real table page is typically >10 KB.
_MIN_HTML_BYTES = 5_000

# Chromium launch flags required in a Docker/ECS Fargate environment.
_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
]


# ---------------------------------------------------------------------------
# Playwright scraper
# ---------------------------------------------------------------------------

def _scrape_harvest_year(
    url: str,
    harvest_year: str,
    page_load_wait_ms: int,
    table_wait_ms: int,
    debug_html: bool,
) -> bytes:
    """Launch a headless browser, submit the form for *harvest_year*, and return
    the rendered page HTML as UTF-8 bytes.

    Raises:
        RuntimeError: If the table is not found within *table_wait_ms* or if the
            page returns suspiciously little content.
    """
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=page_load_wait_ms)

            if debug_html:
                logger.info("[debug-html] Page source before interaction:\n%s", page.content()[:3000])

            # ------------------------------------------------------------------
            # Locate the harvest-year <select> elements.
            # The page typically has two selects for range (start / end).  We
            # set both to the same year to get a single-year view.
            # ------------------------------------------------------------------
            selects = page.locator("select").all()
            if not selects:
                raise RuntimeError(
                    f"No <select> elements found on the page for harvest_year={harvest_year}. "
                    "Run with --debug-html to inspect the page source."
                )

            logger.info(
                "Found %d <select> element(s) on the page for harvest_year=%s",
                len(selects),
                harvest_year,
            )

            # Log available options from the first select to aid debugging.
            first_select_options = selects[0].locator("option").all_text_contents()
            logger.info("Select[0] options: %s", first_select_options[:10])

            # Try to match the harvest year label (e.g. "2024/25" or "2024-25").
            # UNICADATA uses "YYYY/YY" format in Portuguese UI.
            label_variants = [harvest_year, harvest_year.replace("/", "-")]

            for select in selects:
                selected = False
                for label in label_variants:
                    try:
                        select.select_option(label=label)
                        selected = True
                        break
                    except Exception:  # noqa: BLE001
                        pass
                if not selected:
                    # Fall back: pick the option whose text contains the start year.
                    start_year = harvest_year.split("/")[0]
                    options = select.locator("option").all()
                    for opt in options:
                        text = opt.text_content() or ""
                        if start_year in text:
                            val = opt.get_attribute("value")
                            if val:
                                select.select_option(value=val)
                            break
                    else:
                        logger.warning(
                            "Could not find option matching harvest_year=%s in select; "
                            "leaving at default. Options: %s",
                            harvest_year,
                            [o.text_content() for o in options[:10]],
                        )

            # ------------------------------------------------------------------
            # Submit the form.
            # ------------------------------------------------------------------
            submit = page.locator("input[type='submit'], button[type='submit'], button:has-text('Visualizar'), button:has-text('Consultar')")
            count = submit.count()
            if count == 0:
                raise RuntimeError(
                    f"No submit button found for harvest_year={harvest_year}. "
                    "Run with --debug-html to inspect the page source."
                )

            submit.first.click()

            # ------------------------------------------------------------------
            # Wait for the results table to appear.
            # ------------------------------------------------------------------
            page.wait_for_selector("table", timeout=table_wait_ms)

            html = page.content()
            return html.encode("utf-8")

        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download UNICA production-and-milling HTML pages to raw S3. "
            "Uses Playwright (headless Chromium) to render JS-driven tables. "
            "One HTML file per harvest year."
        )
    )
    parser.add_argument(
        "--harvest-years",
        nargs="+",
        metavar="YYYY/YY",
        default=None,
        help=(
            "One or more harvest years to fetch, e.g. --harvest-years 2024/25 2025/26. "
            "Defaults to all years listed in configs/sources/unica_sources.yaml."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        help="Skip harvest years whose S3 key already exists (safe for re-runs).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print harvest years that would be fetched without downloading anything.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=3.0,
        help="Polite delay between Playwright sessions in seconds (default: 3.0).",
    )
    parser.add_argument(
        "--debug-html",
        action="store_true",
        help="Log a snippet of raw page source before form interaction (first year only).",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load manifest
    # -----------------------------------------------------------------------
    manifest_data = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    url: str = manifest_data["url"]
    pw_cfg: dict = manifest_data.get("playwright", {})
    page_load_wait_ms: int = int(pw_cfg.get("page_load_wait_ms", 10_000))
    table_wait_ms: int = int(pw_cfg.get("table_wait_ms", 20_000))
    all_harvest_years: list[str] = [str(y) for y in manifest_data["harvest_years"]]

    harvest_years = args.harvest_years if args.harvest_years else all_harvest_years
    logger.info(
        "Loaded %d harvest years from manifest %s",
        len(all_harvest_years),
        _MANIFEST_PATH.name,
    )

    # -----------------------------------------------------------------------
    # Dry run
    # -----------------------------------------------------------------------
    if args.dry_run:
        print(f"Manifest: {_MANIFEST_PATH.name}  ({len(all_harvest_years)} total harvest years)")
        print(f"Would fetch {len(harvest_years)} harvest year(s):")
        for hy in harvest_years:
            s3_key = unica_raw_key(hy)
            print(f"  {hy}  →  s3://{{bucket}}/{s3_key}")
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    uploaded = skipped = errors = 0
    first = True

    for harvest_year in harvest_years:
        s3_key = unica_raw_key(harvest_year)

        try:
            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info("Skipping — already in S3: %s", s3_key)
                skipped += 1
                continue

            logger.info("Scraping harvest_year=%s …", harvest_year)

            html_bytes = _scrape_harvest_year(
                url=url,
                harvest_year=harvest_year,
                page_load_wait_ms=page_load_wait_ms,
                table_wait_ms=table_wait_ms,
                debug_html=args.debug_html and first,
            )
            first = False

            if len(html_bytes) < _MIN_HTML_BYTES:
                raise RuntimeError(
                    f"Response suspiciously small ({len(html_bytes):,} bytes) for "
                    f"harvest_year={harvest_year} — table may not have loaded."
                )

            if b"<table" not in html_bytes.lower():
                raise RuntimeError(
                    f"No <table> tag found in response for harvest_year={harvest_year}. "
                    "The form submission may have failed. Re-run with --debug-html."
                )

            upload_bytes_to_s3(html_bytes, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket, s3_key, html_bytes, url, "text/html", region
            )

            logger.info(
                "Uploaded harvest_year=%s  (%.1f KB) → s3://%s/%s",
                harvest_year,
                len(html_bytes) / 1_024,
                bucket,
                s3_key,
            )
            uploaded += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed harvest_year=%s: %s", harvest_year, exc)
            errors += 1

        if harvest_years.index(harvest_year) < len(harvest_years) - 1:
            time.sleep(args.sleep_seconds)

    logger.info(
        "UNICA fetch complete. uploaded=%d  skipped=%d  errors=%d",
        uploaded,
        skipped,
        errors,
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
