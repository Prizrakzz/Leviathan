"""Fetch UNICA (Brazilian CS) bi-weekly (quinzenal) production report PDFs to raw S3.

Background
----------
The UNICADATA portal publishes bi-weekly PDF bulletins showing cumulative
Centre-South sugarcane production totals (cane crushed, sugar, ethanol) for
each fortnight of the milling season (typically April–November).

The listing page — https://unicadata.com.br/listagem.php?idMn=63 — is
*fully JavaScript-rendered*.  Static HTTP GET returns only the most recent
bulletin; a headless browser is required to enumerate all available bulletins
for a given harvest year.

Modes
-----
--discover  (requires ``playwright>=1.40`` installed and ``playwright install chromium``)
    Launch a headless Chromium browser, navigate the listing page, and
    enumerate the bulletin PDF URLs for each target harvest year.  Discovered
    bulletins are merged into the ``bulletins:`` section of
    configs/sources/unica_biweekly_sources.yaml.

Normal (no --discover)
    Read the ``bulletins:`` manifest from the config, download any PDFs not
    yet present in S3, and upload them.

Idempotency
-----------
Pass ``--skip-existing-s3`` (default in normal mode) to skip bulletins whose
S3 key already exists.

"""
from __future__ import annotations

import argparse
import logging
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from leviathan.common.config import get_required_env, load_env
from leviathan.common.logging import get_logger
from leviathan.storage.paths import unica_biweekly_raw_key
from leviathan.storage.raw_metadata import write_raw_s3_metadata
from leviathan.storage.s3 import s3_object_exists, upload_bytes_to_s3

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCES_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "unica_biweekly_sources.yaml"
)
_MANIFEST_PATH = (
    Path(__file__).parent.parent.parent
    / "configs"
    / "sources"
    / "unica_biweekly_manifest.yaml"
)

_LISTING_URL = "https://unicadata.com.br/listagem.php?idMn=63&idioma=2"
_DOWNLOAD_BASE = "https://unicadata.com.br/download_media.php?idM="

_PDF_MAGIC = b"%PDF"
_MIN_PDF_BYTES = 50_000  # real bulletins are ~2.8 MB; require at least 50 KB

_REQUEST_TIMEOUT_S = 60
_PLAYWRIGHT_TIMEOUT_MS = 60_000


# ---------------------------------------------------------------------------
# HTTP download
# ---------------------------------------------------------------------------

def _download_pdf(download_url: str) -> bytes:
    """Download a bulletin PDF via plain HTTP.  Returns raw bytes."""
    req = urllib.request.Request(
        download_url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
        pdf_bytes: bytes = resp.read()

    if not pdf_bytes.startswith(_PDF_MAGIC):
        raise RuntimeError(
            f"Response is not a PDF (missing %%PDF header): {download_url}"
        )
    if len(pdf_bytes) < _MIN_PDF_BYTES:
        raise RuntimeError(
            f"PDF too small ({len(pdf_bytes):,} bytes) — likely an error page: {download_url}"
        )
    return pdf_bytes


# ---------------------------------------------------------------------------
# Playwright discovery
# ---------------------------------------------------------------------------

def _discover_bulletins(
    harvest_years: list[str],
    existing_idms: set[str],
) -> list[dict[str, Any]]:
    """Enumerate bulletin URLs using a headless browser.

    Navigates to the English listing page, waits for JavaScript to render,
    and for each available harvest year select option that matches one of
    *harvest_years*, captures the current PDF URL and download link.

    Requires ``playwright>=1.40`` to be installed in the active environment
    and ``playwright install chromium`` to have been run.

    Returns a list of bulletin dicts (same schema as the ``bulletins:`` YAML
    section) for bulletins not already in *existing_idms*.
    """
    import asyncio

    return asyncio.run(_discover_bulletins_async(harvest_years, existing_idms))


async def _discover_bulletins_async(
    harvest_years: list[str],
    existing_idms: set[str],
) -> list[dict[str, Any]]:
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    from playwright.async_api import async_playwright

    found: list[dict[str, Any]] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        logger.info("Playwright: navigating to %s", _LISTING_URL)
        await page.goto(_LISTING_URL, wait_until="domcontentloaded", timeout=_PLAYWRIGHT_TIMEOUT_MS)
        # Give JS-rendered content extra time to settle after initial load
        await page.wait_for_timeout(5_000)

        # ------------------------------------------------------------------
        # Attempt to find a harvest-year filter <select> element.
        # The JS may populate it after page load; try several common names.
        # ------------------------------------------------------------------
        safra_select = page.locator(
            "select[name='safra'], select[name='safraIni'], "
            "select[name='ano'], select[name='harvest_year']"
        ).first

        year_options: list[str] = []
        try:
            await safra_select.wait_for(state="visible", timeout=8_000)
            opts = await safra_select.locator("option[value]").all()
            for opt in opts:
                val = await opt.get_attribute("value")
                if val and re.match(r"\d{4}/\d{4}", val):
                    year_options.append(val)
            logger.info(
                "Playwright: harvest-year select has %d options: %s",
                len(year_options),
                year_options[:6],
            )
        except PlaywrightTimeout:
            logger.info(
                "Playwright: no harvest-year select found — "
                "will capture whichever bulletin is currently displayed."
            )

        # ------------------------------------------------------------------
        # For each target harvest year (or just once if no filter found),
        # select the year, wait for the page to update, then extract the
        # bulletin metadata.
        # ------------------------------------------------------------------
        iterations: list[str | None] = (
            [y for y in harvest_years if not year_options or y in year_options]
            if year_options
            else [None]  # single pass — capture whatever is shown
        )

        for year in iterations:
            if year and year_options:
                try:
                    await safra_select.select_option(value=year)
                    # Some pages auto-reload; others need an explicit submit.
                    submit_btn = page.locator(
                        "form#formConsulta button[type='submit'], "
                        "form#formConsulta input[type='submit']"
                    ).first
                    try:
                        if await submit_btn.is_visible(timeout=2_000):
                            await submit_btn.click()
                    except PlaywrightTimeout:
                        pass  # no submit button — likely auto-refreshes
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception as exc:  # noqa: BLE001 — Playwright interactions can raise diverse exceptions; log and continue to next year
                    logger.warning("Playwright: failed to select year %s: %s", year, exc)
                    continue

            # Extract ALL bulletin download links from the current page state.
            page_bulletins = await _extract_all_bulletins(page, year)
            if not page_bulletins:
                logger.warning("Playwright: no bulletins found for year=%s", year)
                continue

            for bulletin in page_bulletins:
                idm = bulletin.get("idm")
                if idm and idm in existing_idms:
                    logger.debug("Playwright: bulletin idm=%s already known — skipping", idm)
                    continue

                logger.info(
                    "Playwright: discovered bulletin  harvest_year=%s  idm=%s  "
                    "published=%s  bulletin_num=%s",
                    bulletin.get("harvest_year"),
                    idm,
                    bulletin.get("published_ym"),
                    bulletin.get("bulletin_num"),
                )
                if idm:
                    existing_idms.add(idm)
                found.append(bulletin)

        await browser.close()

    return found


async def _extract_current_bulletin(
    page: Any, year: str | None
) -> dict[str, Any] | None:
    """Extract metadata for the bulletin currently displayed on *page*."""
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    try:
        iframe_el = page.locator("iframe.iframe-doc, iframe[id^='iframe_doc']").first
        await iframe_el.wait_for(state="attached", timeout=8_000)
        iframe_src = await iframe_el.get_attribute("src") or ""
    except PlaywrightTimeout:
        return None

    # Download button href → extract idM.
    dl_href = ""
    try:
        dl_href = (
            await page.locator("a[href*='download_media.php']").first.get_attribute("href")
        ) or ""
    except Exception:  # noqa: BLE001 — download button may not exist; idM falls back to None
        logger.debug("download_media.php link not found — idM will be None")

    idm_match = re.search(r"idM=(\d+)", dl_href)
    idm = idm_match.group(1) if idm_match else None

    # Note: iframe_doc_NNN is an internal DOM ID, NOT the UNICA bulletin
    # sequential number — omit to avoid confusion.
    bulletin_num = None

    # Publication year/month from the PDF path (/arquivos/pdfs/YYYY/MM/...).
    ym_match = re.search(r"/arquivos/pdfs/(\d{4})/(\d{2})/", iframe_src)
    published_ym = (
        f"{ym_match.group(1)}/{ym_match.group(2)}" if ym_match else None
    )

    # Infer harvest year from publication month if not supplied by caller.
    # Brazil’s milling season: April–November.  The “YYYY/YYYY+1” label uses the
    # calendar year in which the bulk of the cane is crushed (i.e. the start year).
    #   April–November → season starting in April of that year  e.g. 2024/04 → 2024/2025
    #   December–March  → tail / early of prior-start-year season e.g. 2024/12 → 2024/2025
    if year is None and published_ym:
        pub_year = int(published_ym[:4])
        pub_month = int(published_ym[5:7])
        # Bulletins published Jan–March close out the season that started ~18 months prior.
        if pub_month <= 3:
            season_start = pub_year - 1
        else:
            season_start = pub_year
        year = f"{season_start}/{season_start + 1}"

    if not idm:
        return None

    download_url = _DOWNLOAD_BASE + idm
    return {
        "harvest_year": year,
        "idm": idm,
        "bulletin_num": bulletin_num,
        "published_ym": published_ym,
        "pdf_url": iframe_src if iframe_src else None,
        "download_url": download_url,
    }


async def _extract_all_bulletins(
    page: Any, year: str | None
) -> list[dict[str, Any]]:
    """Extract metadata for ALL bulletins visible on the current listing page.

    Strategy
    --------
    1. Collect every ``download_media.php`` link on the page.
    2. If the page also has a second ``<select>`` for bulletin number (common
       in UNICADATA's JS-rendered portal), iterate through its options, selecting
       each to load the corresponding iframe, then capture the PDF URL.
    3. Fall back to ``_extract_current_bulletin`` for the single displayed
       bulletin if no list/select is found.

    Returns a list of bulletin dicts (may be empty).
    """
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    bulletins: list[dict[str, Any]] = []

    # ── Strategy A: check for a secondary <select> that lists bulletin numbers
    # ─────────────────────────────────────────────────────────────────────────
    # UNICADATA sometimes has a second select (e.g. name="idBoletim" or
    # name="numero") populated after the harvest-year is chosen.  If present,
    # iterate through its options to enumerate each bulletin.
    bulletin_select = page.locator(
        "select[name='idBoletim'], select[name='numero'], "
        "select[name='boletim'], select[name='bulletin']"
    ).first
    try:
        await bulletin_select.wait_for(state="visible", timeout=4_000)
        opts = await bulletin_select.locator("option[value]").all()
        bulletin_values = [
            (await o.get_attribute("value"), await o.inner_text())
            for o in opts
            if (await o.get_attribute("value") or "").strip()
        ]
        logger.info(
            "Playwright: bulletin select has %d options for year=%s",
            len(bulletin_values), year,
        )
        for val, label in bulletin_values:
            try:
                await bulletin_select.select_option(value=val)
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:  # noqa: BLE001 — option navigation may stall; extraction proceeds regardless
                logger.debug("select_option/wait_for_load_state failed for val=%s year=%s", val, year)
            b = await _extract_current_bulletin(page, year)
            if b and b.get("idm"):
                bulletins.append(b)
        if bulletins:
            return bulletins
    except PlaywrightTimeout:
        pass  # no second select — fall through

    # ── Strategy B: gather all download_media.php links visible at once
    # ─────────────────────────────────────────────────────────────────────────
    dl_links = await page.locator("a[href*='download_media.php']").all()
    logger.info(
        "Playwright: found %d download_media.php links for year=%s",
        len(dl_links), year,
    )
    if len(dl_links) > 1:
        # Get the current iframe src to pair with the first link.
        iframe_src = ""
        try:
            iframe_el = page.locator("iframe.iframe-doc, iframe[id^='iframe_doc']").first
            await iframe_el.wait_for(state="attached", timeout=5_000)
            iframe_src = await iframe_el.get_attribute("src") or ""
        except PlaywrightTimeout:
            pass

        ym_match_first = re.search(r"/arquivos/pdfs/(\d{4})/(\d{2})/", iframe_src)
        first_published_ym = (
            f"{ym_match_first.group(1)}/{ym_match_first.group(2)}"
            if ym_match_first else None
        )

        for i, link in enumerate(dl_links):
            dl_href = await link.get_attribute("href") or ""
            idm_match = re.search(r"idM=(\d+)", dl_href, re.IGNORECASE)
            if not idm_match:
                continue
            idm = idm_match.group(1)
            # Only the first link's iframe src is known without clicking each row.
            published_ym = first_published_ym if i == 0 else None
            pdf_url = iframe_src if (i == 0 and iframe_src) else None
            bulletins.append({
                "harvest_year": year,
                "idm": idm,
                "bulletin_num": None,
                "published_ym": published_ym,
                "pdf_url": pdf_url,
                "download_url": _DOWNLOAD_BASE + idm,
            })
        return bulletins

    # ── Strategy C: single bulletin — delegate to existing function
    # ─────────────────────────────────────────────────────────────────────────
    b = await _extract_current_bulletin(page, year)
    if b:
        bulletins.append(b)
    return bulletins


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _load_sources() -> dict[str, Any]:
    return yaml.safe_load(_SOURCES_PATH.read_text(encoding="utf-8"))


def _load_manifest() -> list[dict[str, Any]]:
    raw = yaml.safe_load(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return raw.get("bulletins") or [] if raw else []


def _save_manifest(bulletins: list[dict[str, Any]]) -> None:
    """Overwrite ONLY the ``bulletins:`` list; preserve header comments."""
    # Re-read the file so we keep the comment block above ``bulletins:``.
    original = _MANIFEST_PATH.read_text(encoding="utf-8")
    # Replace everything from the ``bulletins:`` key onward.
    header_end = original.find("\nbulletins:")
    if header_end == -1:
        header = original
    else:
        header = original[: header_end]

    lines = [header, "\nbulletins:\n\n"]
    for b in bulletins:
        lines.append(f"  - harvest_year: \"{b['harvest_year']}\"\n")
        lines.append(f"    idm: \"{b['idm']}\"\n")
        lines.append(f"    bulletin_num: {b.get('bulletin_num')}\n")
        lines.append(f"    published_ym: \"{b.get('published_ym')}\"\n")
        lines.append(f"    pdf_url: {repr(b.get('pdf_url')) if b.get('pdf_url') else 'null'}\n")
        dl = b.get("download_url")
        lines.append(f"    download_url: {repr(dl) if dl else 'null'}\n")
        lines.append("\n")

    _MANIFEST_PATH.write_text("".join(lines), encoding="utf-8")


def _merge_bulletins(
    existing: list[dict[str, Any]],
    new_bulletins: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append *new_bulletins* to *existing*, deduplicating by idm."""
    seen = {b["idm"] for b in existing if b.get("idm")}
    merged = list(existing)
    for b in new_bulletins:
        if b.get("idm") not in seen:
            merged.append(b)
            seen.add(b["idm"])
    return merged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Download UNICA bi-weekly (quinzenal) production report PDFs to raw S3. "
            "Run with --discover first to enumerate available bulletin URLs (requires Playwright). "
            "Subsequent runs without --discover use the cached manifest."
        )
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help=(
            "Use Playwright to enumerate available bulletin URLs for the configured "
            "harvest years and update configs/sources/unica_biweekly_sources.yaml. "
            "Requires: pip install 'leviathan[biweekly]' && playwright install chromium"
        ),
    )
    parser.add_argument(
        "--harvest-years",
        nargs="+",
        metavar="YYYY/YYYY",
        default=None,
        help=(
            "Limit discovery/download to these harvest years, "
            "e.g. --harvest-years 2023/2024 2024/2025. "
            "Defaults to all years in the manifest."
        ),
    )
    parser.add_argument(
        "--skip-existing-s3",
        action="store_true",
        default=True,
        help="Skip bulletins whose S3 key already exists (default: True).",
    )
    parser.add_argument(
        "--no-skip-existing-s3",
        dest="skip_existing_s3",
        action="store_false",
        help="Re-download and overwrite existing S3 objects.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be downloaded without making any HTTP or S3 calls.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=3.0,
        help="Polite delay between PDF downloads in seconds (default: 3.0).",
    )
    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Load config (harvest_years) + manifest (bulletin list) separately
    # -----------------------------------------------------------------------
    sources = _load_sources()
    all_harvest_years: list[str] = [str(y) for y in sources.get("harvest_years", [])]
    target_years: list[str] = args.harvest_years if args.harvest_years else all_harvest_years
    bulletins: list[dict[str, Any]] = _load_manifest()

    logger.info(
        "Manifest: %d known bulletins across %d configured harvest years",
        len(bulletins),
        len(all_harvest_years),
    )

    # -----------------------------------------------------------------------
    # Discovery mode — enumerate new bulletin URLs via Playwright
    # -----------------------------------------------------------------------
    if args.discover:
        logger.info("Discovery mode: enumerating bulletins for %s", target_years)
        existing_idms = {b["idm"] for b in bulletins if b.get("idm")}
        try:
            new_bulletins = _discover_bulletins(target_years, existing_idms)
        except ImportError:
            logger.error(
                "Playwright is not installed. "
                "Run: pip install 'leviathan[biweekly]' && playwright install chromium"
            )
            raise SystemExit(1)

        if new_bulletins:
            bulletins = _merge_bulletins(bulletins, new_bulletins)
            if not args.dry_run:
                _save_manifest(bulletins)
                logger.info(
                    "Manifest updated: added %d bulletin(s). "
                    "Total: %d",
                    len(new_bulletins),
                    len(bulletins),
                )
            else:
                logger.info("Dry run — manifest not written. Would add %d bulletin(s).", len(new_bulletins))
        else:
            logger.info("Discovery found no new bulletins.")

    # -----------------------------------------------------------------------
    # Dry run — list what would be downloaded
    # -----------------------------------------------------------------------
    if args.dry_run:
        target_bulletins = [
            b for b in bulletins
            if not target_years or b.get("harvest_year") in target_years
        ]
        print(
            f"Manifest: {_MANIFEST_PATH.name}  "
            f"({len(bulletins)} bulletins total, {len(target_bulletins)} in target years)"
        )
        for b in target_bulletins:
            print(
                f"  harvest_year={b.get('harvest_year')}  idm={b.get('idm')}  "
                f"published={b.get('published_ym')}  bulletin_num={b.get('bulletin_num')}"
            )
        return

    # -----------------------------------------------------------------------
    # Download & upload
    # -----------------------------------------------------------------------
    load_env()
    bucket = get_required_env("LEVIATHAN_BUCKET")
    region = get_required_env("AWS_REGION")

    target_bulletins = [
        b for b in bulletins
        if not target_years or b.get("harvest_year") in target_years
    ]
    logger.info("Downloading %d bulletin(s) …", len(target_bulletins))

    uploaded = skipped = errors = 0
    first = True

    for b in target_bulletins:
        idm = b.get("idm")
        harvest_year = b.get("harvest_year") or "unknown"
        # For normal bulletins: use download_url or fall back to download_media.php.
        # For hash-based (pdf_*) bulletins: use pdf_url directly.
        download_url = b.get("download_url")
        # Guard against "None" strings written by older versions of _save_manifest.
        if not download_url or download_url == "None":
            if idm and str(idm).startswith("pdf_"):
                download_url = b.get("pdf_url")
            elif idm:
                download_url = _DOWNLOAD_BASE + idm

        if not idm or not download_url:
            logger.warning("Skipping bulletin with missing idm or download_url: %s", b)
            errors += 1
            continue

        s3_key = unica_biweekly_raw_key(harvest_year, idm)

        try:
            if args.skip_existing_s3 and s3_object_exists(bucket, s3_key, region):
                logger.info(
                    "Skipping — already in S3: idm=%s harvest_year=%s", idm, harvest_year
                )
                skipped += 1
                continue

            if not first:
                time.sleep(args.sleep_seconds)
            first = False

            logger.info(
                "Downloading bulletin idm=%s  harvest_year=%s  %s …",
                idm,
                harvest_year,
                download_url,
            )
            pdf_bytes = _download_pdf(download_url)

            upload_bytes_to_s3(pdf_bytes, bucket, s3_key, region)
            write_raw_s3_metadata(
                bucket, s3_key, pdf_bytes, download_url, "application/pdf", region
            )

            logger.info(
                "Uploaded idm=%s  (%.1f MB) → s3://%s/%s",
                idm,
                len(pdf_bytes) / 1_048_576,
                bucket,
                s3_key,
            )
            uploaded += 1

        except urllib.error.URLError as exc:
            logger.error("Network error for idm=%s: %s", idm, exc)
            errors += 1
        except RuntimeError as exc:
            logger.error("Validation error for idm=%s: %s", idm, exc)
            errors += 1
        except Exception as exc:  # noqa: BLE001 — unexpected error counted and logged; loop continues to remaining bulletins
            logger.error("Unexpected error for idm=%s: %s", idm, exc)
            errors += 1

    logger.info(
        "Done. uploaded=%d  skipped=%d  errors=%d", uploaded, skipped, errors
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
