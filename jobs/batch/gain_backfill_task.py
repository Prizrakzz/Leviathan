"""AWS Batch Fargate entrypoint: GAIN backfill for one commodity.

Runs the full pipeline inside a single container:
  1. Crawl FAS GAIN search pages (curl_cffi + BeautifulSoup)
  2. Build manifest (normalize, deduplicate)
  3. Download PDFs + upload to S3

One Batch task per commodity means all 10 run in parallel.

Required args:
    --commodity-name    e.g. "wheat"
    --commodity-id      FAS taxonomy ID, e.g. 15; omit for cocoa (title-filter path)
    --target-countries  comma-separated ISO2, e.g. "US,FR,AU"
    --bucket            S3 bucket name
    --aws-region        AWS region

Optional:
    --title-filter      case-insensitive title substring (for cocoa: "cocoa")
    --sleep-seconds     between PDF downloads (default 2.0)
    --skip-existing-s3  skip PDFs already in S3 (default: true)
    --dry-run           crawl + manifest only, skip S3 upload
"""
from __future__ import annotations

import argparse
import datetime
import random
import re
import time
from urllib.parse import unquote, urljoin

import boto3
from bs4 import BeautifulSoup
from curl_cffi import requests as cr

from leviathan.common.constants import MIN_RAW_FILE_SIZES
from leviathan.common.logging import get_logger
from leviathan.storage.paths import raw_gain_key

logger = get_logger("gain_backfill_task")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IMPERSONATE = "chrome136"
_BASE_URL = "https://fas.usda.gov"
_SEARCH_BASE = (
    "https://fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A10251"
    "&reports%5B1%5D=report_commodities%3A{cid}"
)
_SEARCH_NO_COMMODITY = (
    "https://fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A10251"
)
# Date-scoped search: one URL per calendar month — avoids hammering the
# global endpoint and keeps each page small (~35 results).
_SEARCH_DATE = (
    "https://fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A10251"
    "&reports%5B1%5D=report_datetime%3A{year}-{month:02d}"
)

# Stop cocoa crawl after this many consecutive empty pages
_MAX_EMPTY_PAGES = 15

COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    # Coffee
    "brazil": "BR", "colombia": "CO", "ethiopia": "ET", "vietnam": "VN",
    "viet nam": "VN", "indonesia": "ID", "honduras": "HN", "guatemala": "GT",
    "peru": "PE", "mexico": "MX", "uganda": "UG", "india": "IN",
    "tanzania": "TZ", "kenya": "KE", "cote d'ivoire": "CI",
    "côte d'ivoire": "CI", "ivory coast": "CI", "cameroon": "CM",
    "papua new guinea": "PG", "philippines": "PH", "laos": "LA",
    "lao p.d.r.": "LA", "lao pdr": "LA", "lao people": "LA",
    # Grains / wheat / corn / rice
    "united states": "US", "france": "FR", "australia": "AU", "canada": "CA",
    "ukraine": "UA", "russia": "RU", "russian federation": "RU",
    "pakistan": "PK", "egypt": "EG", "argentina": "AR", "china": "CN",
    "germany": "DE", "poland": "PL", "turkey": "TR", "türkiye": "TR",
    "turkiye": "TR", "south africa": "ZA", "nigeria": "NG", "thailand": "TH",
    "ghana": "GH", "paraguay": "PY", "bolivia": "BO", "ecuador": "EC",
    "uzbekistan": "UZ",
    # Oilseeds / palm oil
    "malaysia": "MY",
    # Additional
    "myanmar": "MM", "burma": "MM", "taiwan": "TW", "south korea": "KR",
    "korea": "KR", "japan": "JP", "senegal": "SN", "mali": "ML",
    "burkina faso": "BF", "benin": "BJ", "togo": "TG", "guinea": "GN",
    "nicaragua": "NI", "costa rica": "CR", "el salvador": "SV",
    "dominican republic": "DO", "haiti": "HT", "jamaica": "JM",
    "venezuela": "VE", "chile": "CL", "uruguay": "UY", "zambia": "ZM",
    "zimbabwe": "ZW", "mozambique": "MZ", "malawi": "MW", "rwanda": "RW",
    "burundi": "BI", "democratic republic of congo": "CD", "angola": "AO",
    "sri lanka": "LK", "nepal": "NP", "bangladesh": "BD", "iran": "IR",
    "saudi arabia": "SA", "kazakhstan": "KZ", "romania": "RO",
    "hungary": "HU", "spain": "ES", "italy": "IT", "netherlands": "NL",
    "new zealand": "NZ",
}

_PDF_FILENAME_RE = re.compile(
    r"(?P<category>[^_]+(?:\s[^_]+)*)"
    r"_(?P<post>[^_]+)"
    r"_(?P<country_name>[^_]+)"
    r"_(?P<report_id>[A-Z]{2}\d{4}-\d{4})"
    r"\.pdf$",
    re.IGNORECASE,
)
_REPORT_ID_RE = re.compile(r"\b([A-Z]{2})(\d{4})-(\d{4})\b")


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

def _get_html(sess: cr.Session, url: str, retries: int = 3) -> str | None:
    for attempt in range(retries + 1):
        try:
            r = sess.get(url, impersonate=_IMPERSONATE, timeout=30, allow_redirects=True)
            if r.status_code == 200:
                return r.text
            logger.warning("HTTP %s for %s (attempt %d/%d)", r.status_code, url, attempt + 1, retries + 1)
            if attempt < retries:
                backoff = 30 * (2 ** attempt)  # 30s, 60s, 120s
                logger.info("Retrying in %ds...", backoff)
                time.sleep(backoff)
            else:
                return None
        except Exception as exc:  # noqa: BLE001 — retry loop: any HTTP or parse error retried up to max retries
            if attempt == retries:
                logger.error("Failed %s: %s", url, exc)
                return None
            time.sleep(2)
    return None


def _parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for card in soup.select(".c-card"):
        link_el = card.select_one(".c-card__url")
        title_el = card.select_one(".c-card__title")
        time_el = card.select_one("time[datetime]")
        if not link_el or not title_el:
            continue
        results.append({
            "landing_url": urljoin(_BASE_URL, link_el.get("href", "")),
            "title": title_el.get_text(strip=True),
            "datetime_str": time_el.get("datetime", "") if time_el else "",
        })
    return results


def _has_next_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(
        soup.select_one("a[rel='next']")
        or soup.select_one(".pager__item--next a")
        or soup.select_one("li.next a")
    )


def _iso2_from_title(title: str) -> str | None:
    part = title.split(":")[0].strip().lower() if ":" in title else title.lower()
    for key, iso2 in COUNTRY_NAME_TO_ISO2.items():
        if key in part:
            return iso2
    return None


def _parse_landing(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    pdf_el = (
        soup.select_one("a[href*='gain-report']")
        or soup.select_one("a[href$='.pdf']")
    )
    if not pdf_el:
        return None
    pdf_url = urljoin(_BASE_URL, pdf_el.get("href", ""))
    decoded = unquote(pdf_url)
    filename = decoded.rstrip("/").split("/")[-1].replace(" ", "_")

    post = category_from_file = report_id = ""
    m = _PDF_FILENAME_RE.match(filename)
    if m:
        category_from_file = m.group("category").strip()
        post = m.group("post").strip()
        report_id = m.group("report_id").upper()
    else:
        rid_m = _REPORT_ID_RE.search(filename)
        if rid_m:
            report_id = rid_m.group(0)

    return {
        "pdf_url": pdf_url,
        "filename_clean": filename,
        "report_id": report_id,
        "post": post,
        "category_from_file": category_from_file,
    }


def crawl(
    search_url: str,
    target_iso2: set[str],
    title_filter: str | None,
    sleep_listing: float = 1.5,
    sleep_landing: float = 1.0,
    max_empty_pages: int = _MAX_EMPTY_PAGES,
    start_year: int | None = None,
    end_year: int | None = None,
) -> list[dict]:
    """Return list of raw record dicts (one per report PDF found).

    When start_year is provided the crawl uses date-scoped URLs
    (one per calendar month) instead of the single global search endpoint.
    This spreads requests across hundreds of distinct CDN cache keys,
    avoids triggering per-URL rate limits when multiple containers run in
    parallel, and keeps each paginated result set small (~35 cards/month).
    """
    # Build the ordered list of base URLs to iterate.
    if start_year is not None:
        today = datetime.date.today()
        stop_year = end_year if end_year is not None else today.year
        stop_month = today.month if stop_year == today.year else 12
        search_urls: list[str] = [
            _SEARCH_DATE.format(year=y, month=m)
            for y in range(start_year, stop_year + 1)
            for m in range(1, (stop_month if y == stop_year else 12) + 1)
        ]
        logger.info(
            "Date-scoped crawl: %d month URLs  (%d-01 → %d-%02d)",
            len(search_urls), start_year, stop_year, stop_month,
        )
    else:
        search_urls = [search_url]

    records: list[dict] = []
    empty_run = 0
    # max_empty early-stop only makes sense for the global no-filter search.
    max_empty = max_empty_pages if (title_filter and start_year is None) else 0

    with cr.Session() as sess:
        sess.headers.update({
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://fas.usda.gov/",
        })
        # Warm-up: fetch the FAS homepage so the session has cookies before
        # hitting the search endpoint, reducing bot-detection false positives.
        _get_html(sess, _BASE_URL)

        for base_url in search_urls:
            page_num = 0
            while True:
                page_url = base_url if page_num == 0 else f"{base_url}&page={page_num}"
                logger.info("[Page %d] %s", page_num + 1, page_url)

                html = _get_html(sess, page_url)
                if not html:
                    break

                cards = _parse_listing(html)
                logger.info("  Cards: %d", len(cards))
                if not cards:
                    break

                page_hits = 0
                for card in cards:
                    title = card["title"]

                    if title_filter and title_filter.lower() not in title.lower():
                        continue

                    iso2 = _iso2_from_title(title)
                    if not iso2 or iso2 not in target_iso2:
                        continue

                    dt_str = card["datetime_str"]
                    pub_date = dt_str[:10].replace("-", "") if dt_str else ""
                    category = title.split(":", 1)[1].strip() if ":" in title else title

                    record: dict = {
                        "landing_url": card["landing_url"],
                        "title": title,
                        "country_iso2": iso2,
                        "category": category,
                        "publication_date": pub_date,
                        "pdf_url": "",
                        "filename_clean": "",
                        "report_id": "",
                        "post": "",
                    }

                    lp_html = _get_html(sess, card["landing_url"])
                    if lp_html:
                        lp = _parse_landing(lp_html)
                        if lp:
                            record.update(lp)
                            if lp.get("category_from_file"):
                                record["category"] = lp["category_from_file"]

                    if record["pdf_url"]:
                        records.append(record)
                        page_hits += 1
                        logger.info(
                            "  [OK] %s  %s  %s",
                            iso2, pub_date, record.get("report_id") or title,
                        )
                    else:
                        logger.warning("  [NO PDF] %s (%s)", title, card["landing_url"])

                    time.sleep(sleep_landing)

                if max_empty > 0:
                    if page_hits == 0:
                        empty_run += 1
                        logger.info("  (no matches - empty run %d/%d)", empty_run, max_empty)
                        if empty_run >= max_empty:
                            logger.info("Early stop: %d consecutive empty pages.", max_empty)
                            break
                    else:
                        empty_run = 0

                if not _has_next_page(html):
                    break

                page_num += 1
                time.sleep(sleep_listing)

    logger.info("Crawl complete: %d records", len(records))
    return records


# ---------------------------------------------------------------------------
# Manifest build (inline, no file I/O — returns dict for upload to S3)
# ---------------------------------------------------------------------------

def build_manifest(records: list[dict], source_name: str) -> dict:
    """Normalize records and return manifest dict (same schema as YAML archives)."""
    seen: set[str] = set()
    entries: list[dict] = []

    for raw in records:
        report_id = raw.get("report_id", "")
        pdf_url = raw.get("pdf_url", "")
        dedup_key = report_id or pdf_url
        if not dedup_key or dedup_key in seen:
            continue
        seen.add(dedup_key)

        pub_date = raw.get("publication_date", "")
        if not pub_date or len(pub_date) != 8:
            continue

        entries.append({
            "report_id": report_id,
            "country_iso2": raw.get("country_iso2", ""),
            "publication_date": pub_date,
            "title": raw.get("title", ""),
            "category": raw.get("category", ""),
            "post": raw.get("post", ""),
            "pdf_url": pdf_url,
            "filename_clean": raw.get("filename_clean", ""),
            "source": source_name,
        })

    entries.sort(key=lambda e: (e["country_iso2"], e["publication_date"]))
    countries = sorted({e["country_iso2"] for e in entries})

    return {
        "source": source_name,
        "record_count": len(entries),
        "target_countries": countries,
        "records": entries,
    }


# ---------------------------------------------------------------------------
# S3 upload
# ---------------------------------------------------------------------------

def _s3_key_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except s3.exceptions.ClientError:
        return False


def upload_pdfs(
    manifest: dict,
    source_name: str,
    bucket: str,
    aws_region: str,
    skip_existing: bool,
    sleep_seconds: float,
) -> tuple[int, int, int]:
    """Download PDFs and upload to S3. Returns (uploaded, skipped, failed)."""
    min_size = MIN_RAW_FILE_SIZES.get("usda_gain", 30_000)
    s3 = boto3.client("s3", region_name=aws_region)
    uploaded = skipped = failed = 0

    with cr.Session() as sess:
        sess.headers.update({
            "Accept": "application/pdf,*/*",
            "Referer": "https://fas.usda.gov/",
        })

        for entry in manifest["records"]:
            pdf_url = entry.get("pdf_url", "")
            filename = entry.get("filename_clean", "")
            country = entry.get("country_iso2", "")
            pub_date = entry.get("publication_date", "")

            if not pdf_url or not filename or not country or not pub_date:
                failed += 1
                continue

            key = raw_gain_key(source_name, country, pub_date, filename)

            if skip_existing and _s3_key_exists(s3, bucket, key):
                skipped += 1
                continue

            try:
                r = sess.get(pdf_url, impersonate=_IMPERSONATE, timeout=60)
                if r.status_code != 200:
                    logger.warning("HTTP %s for %s", r.status_code, pdf_url)
                    failed += 1
                    continue
                body = r.content
                if len(body) < min_size:
                    logger.warning("Too small (%d B): %s", len(body), filename)
                    failed += 1
                    continue
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=body,
                    ContentType="application/pdf",
                )
                uploaded += 1
                logger.info("Uploaded s3://%s/%s", bucket, key)
            except Exception as exc:  # noqa: BLE001 — any download, size-check or S3 upload error is logged; loop continues
                logger.error("Failed %s: %s", pdf_url, exc)
                failed += 1

            time.sleep(sleep_seconds)

    return uploaded, skipped, failed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Stagger concurrent container startups so they don't all hit the same
    # Akamai-protected endpoint at the exact same moment.
    _jitter = random.uniform(30, 180)
    logger.info("Startup jitter: sleeping %.0fs before first request", _jitter)
    time.sleep(_jitter)

    parser = argparse.ArgumentParser(description="GAIN Fargate backfill task.")
    parser.add_argument("--commodity-name", required=True)
    parser.add_argument("--commodity-id", type=int, default=None)
    parser.add_argument("--target-countries", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--aws-region", required=True)
    parser.add_argument("--title-filter", default=None)
    parser.add_argument("--max-empty-pages", type=int, default=_MAX_EMPTY_PAGES)
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=2.0)
    parser.add_argument("--skip-existing-s3", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_name = f"usda_gain_{args.commodity_name}"
    target_iso2 = {c.strip().upper() for c in args.target_countries.split(",") if c.strip()}

    if args.commodity_id is not None:
        search_url = _SEARCH_BASE.format(cid=args.commodity_id)
    else:
        search_url = _SEARCH_NO_COMMODITY

    logger.info(
        "GAIN backfill task: source=%s  commodity_id=%s  countries=%s",
        source_name, args.commodity_id, sorted(target_iso2),
    )

    # 1. Crawl
    records = crawl(
        search_url=search_url,
        target_iso2=target_iso2,
        title_filter=args.title_filter,
        max_empty_pages=args.max_empty_pages,
        start_year=args.start_year,
        end_year=args.end_year,
    )
    if not records:
        logger.warning("No records found for %s — exiting cleanly.", source_name)
        raise SystemExit(0)

    # 2. Build manifest
    manifest = build_manifest(records, source_name)
    logger.info(
        "Manifest: %d records across %s",
        manifest["record_count"], manifest["target_countries"],
    )

    if args.dry_run:
        logger.info("--dry-run: skipping S3 upload.")
        return

    # 3. Upload PDFs
    uploaded, skipped, failed = upload_pdfs(
        manifest=manifest,
        source_name=source_name,
        bucket=args.bucket,
        aws_region=args.aws_region,
        skip_existing=args.skip_existing_s3,
        sleep_seconds=args.sleep_seconds,
    )
    logger.info(
        "Done. uploaded=%d  skipped=%d  failed=%d",
        uploaded, skipped, failed,
    )
    if failed > 0 and uploaded == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
