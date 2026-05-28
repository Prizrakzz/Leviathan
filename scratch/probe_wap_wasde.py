"""Probe WAP and WASDE raw files to understand document structure before writing parsers.

Six sections (A–F), each sampling 5 files at evenly-spaced positions in the manifest:

  A  WAP direct PDFs from S3 (2002–2026)         → pdfplumber
  B  WAP archive.org scanned PDFs (1988–2002)     → pdfplumber (text-layer check)
  C  WAP Wayback HTML (1996–2002)                 → BeautifulSoup
  D  WASDE digital PDFs from S3 (2000–2026)       → pdfplumber
  E  WASDE TXT from S3 (1995–1999)                → raw text
  F  WASDE scanned PDFs from S3 (1973–1994)       → pdfplumber (text-layer check)

Usage
-----
    # Run all sections:
    python scratch/probe_wap_wasde.py 2>&1 | tee scratch/probe_output.txt

    # Run individual sections:
    python scratch/probe_wap_wasde.py a d e
    python scratch/probe_wap_wasde.py b c

Prerequisites
-------------
    pip install pdfplumber   # in pyproject.toml [biweekly] extra
    AWS credentials configured (same env as all other ingest scripts)
"""
from __future__ import annotations

import io
import re
import sys
import time
from pathlib import Path
from typing import Any

import boto3
import requests
import yaml
from bs4 import BeautifulSoup

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed. Run: pip install pdfplumber", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BUCKET = "leviathan-dev-shahem-001"
REGION = "us-east-1"
CONFIGS = Path(__file__).parent.parent / "configs" / "sources"

HTTP_TIMEOUT = 60
HTTP_SLEEP = 1.5          # polite delay between archive.org / Wayback requests
PDF_PAGES_TO_DETAIL = 7   # how many pages to inspect in depth per file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _s3() -> Any:
    return boto3.client("s3", region_name=REGION)


def _quintile_sample(items: list) -> list:
    """Return up to 5 items at 0%, 25%, 50%, 75%, 100% positions."""
    n = len(items)
    if n == 0:
        return []
    indices = sorted({0, n // 4, n // 2, 3 * n // 4, n - 1})
    return [items[i] for i in indices]


def _banner(label: str) -> None:
    width = 72
    print(f"\n{'=' * width}")
    print(f"  {label}")
    print(f"{'=' * width}")


def _section_header(title: str) -> None:
    print(f"\n\n{'#' * 72}")
    print(f"# {title}")
    print(f"{'#' * 72}")


# ---------------------------------------------------------------------------
# PDF probe
# ---------------------------------------------------------------------------

def _probe_pdf(data: bytes, label: str) -> None:
    """Run pdfplumber on in-memory PDF bytes and print structured findings."""
    _banner(label)
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            n_pages = len(pdf.pages)
            print(f"  Page count : {n_pages}")

            # Collect full text across ALL pages to run cross-page searches
            all_page_texts: list[str] = []
            for page in pdf.pages:
                all_page_texts.append(page.extract_text() or "")
            full_text = "\n".join(all_page_texts)
            nonws_chars = len(re.sub(r"\s", "", full_text))
            print(f"  Non-whitespace chars (all pages): {nonws_chars:,}")

            if nonws_chars < 200:
                print("  *** SCANNED / IMAGE-ONLY — pdfplumber extracted minimal text ***")
                print("  *** Textract OCR will be required for this era ***")
                return

            # ---------------------------------------------------------------
            # Per-page detail (first PDF_PAGES_TO_DETAIL pages)
            # ---------------------------------------------------------------
            print(f"\n  Per-page detail (first {min(PDF_PAGES_TO_DETAIL, n_pages)} pages):")
            for i, page in enumerate(pdf.pages[:PDF_PAGES_TO_DETAIL]):
                text = all_page_texts[i]
                lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                tables = page.extract_tables()

                print(f"\n  --- Page {i} ---")
                print(f"  chars={len(text)}  tables={len(tables)}")
                print(f"  First 8 non-empty lines:")
                for ln in lines[:8]:
                    print(f"    | {ln[:110]}")

                for t_idx, table in enumerate(tables):
                    if not table:
                        continue
                    ncols = len(table[0]) if table[0] else 0
                    nrows = len(table)
                    print(f"\n  Table {t_idx}: {nrows} rows × {ncols} cols")
                    print(f"    Header row : {table[0]}")
                    if nrows > 1:
                        print(f"    Data row 1 : {table[1]}")
                    if nrows > 2:
                        print(f"    Data row 2 : {table[2]}")

            # ---------------------------------------------------------------
            # WASDE-specific: locate "OUTLOOK FOR ..." sections
            # ---------------------------------------------------------------
            outlook_hits = re.findall(r"OUTLOOK FOR [A-Z ,/&]+", full_text)
            if outlook_hits:
                seen: set[str] = set()
                unique_sections = []
                for s in outlook_hits:
                    s = s.strip()
                    if s not in seen:
                        seen.add(s)
                        unique_sections.append(s)
                print(f"\n  WASDE 'OUTLOOK FOR' sections detected ({len(unique_sections)}):")
                for sec in unique_sections:
                    # Find the page it appears on
                    page_num = next(
                        (i for i, t in enumerate(all_page_texts) if sec in t), None
                    )
                    print(f"    Page {page_num}: '{sec}'")
                    # Print the first 300 chars of that section's text
                    idx = full_text.find(sec)
                    snippet = full_text[idx:idx + 350].replace("\n", " ").strip()
                    print(f"    Snippet : {snippet[:250]!r}")

            # ---------------------------------------------------------------
            # WAP-specific: commodity section names in text
            # ---------------------------------------------------------------
            wap_commodity_names = [
                "WHEAT", "COARSE GRAINS", "RICE", "OILSEEDS",
                "COTTON", "SUGAR",
            ]
            found_commodities = [c for c in wap_commodity_names if c in full_text]
            if found_commodities:
                print(f"\n  WAP commodity sections found in text: {found_commodities}")

            # ---------------------------------------------------------------
            # WAP-specific: revision / change column check
            # ---------------------------------------------------------------
            rev_match = re.search(
                r".{0,40}(revis\w*|change\s+from\s+prev\w*|prior\s+month\s+est).{0,60}",
                full_text,
                re.IGNORECASE,
            )
            if rev_match:
                print(f"\n  Explicit revision/change text found:")
                print(f"    ...{rev_match.group().strip()[:120]}...")
            else:
                print(f"\n  No explicit revision column detected — revisions must be computed")
                print(f"  by differencing consecutive monthly issues.")

    except Exception as exc:
        print(f"  ERROR running pdfplumber: {exc}")


# ---------------------------------------------------------------------------
# HTML probe
# ---------------------------------------------------------------------------

def _probe_html(html: str, label: str, source_url: str) -> None:
    """Parse WAP Wayback HTML with BeautifulSoup and print findings."""
    _banner(label)
    soup = BeautifulSoup(html, "html.parser")

    # Structural headers
    header_tags = soup.find_all(["h1", "h2", "h3", "h4"])
    bold_tags = soup.find_all(["b", "strong"])
    all_headers = (
        [t.get_text(strip=True) for t in header_tags]
        + [t.get_text(strip=True) for t in bold_tags if 3 < len(t.get_text(strip=True)) < 80]
    )
    print(f"  Header/bold tags ({len(all_headers)} total, first 20):")
    for h in all_headers[:20]:
        print(f"    {h!r}")

    # Tables
    tables = soup.find_all("table")
    print(f"\n  Tables found: {len(tables)}")
    for t_idx, table in enumerate(tables[:5]):
        rows = table.find_all("tr")
        print(f"\n  Table {t_idx}: {len(rows)} rows")
        for r_idx, row in enumerate(rows[:6]):
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            # Trim long cells
            cells = [c[:40] for c in cells]
            print(f"    Row {r_idx}: {cells}")

    # Pagination: links to wap2.html, wap3.html, etc.
    all_links = [a.get("href", "") for a in soup.find_all("a", href=True)]
    wap_page_links = [lnk for lnk in all_links if re.search(r"wap\d+\.html?", lnk, re.IGNORECASE)]
    if wap_page_links:
        base = source_url.rsplit("/", 1)[0]
        print(f"\n  Pagination links found (multi-page report):")
        for lnk in wap_page_links:
            full = lnk if lnk.startswith("http") else f"{base}/{lnk.lstrip('/')}"
            print(f"    {full}")
    else:
        print(f"\n  No WAP pagination links — single-page HTML report")

    # Commodity section names in plain text
    full_text = soup.get_text()
    found_commodities = [
        c for c in ["WHEAT", "COARSE GRAINS", "RICE", "OILSEEDS", "COTTON", "SUGAR"]
        if c in full_text.upper()
    ]
    print(f"\n  Commodity sections found in text: {found_commodities}")

    # Revision column check
    rev_match = re.search(r"revis\w*|change\s+from", full_text, re.IGNORECASE)
    if rev_match:
        snippet = re.search(r".{0,30}(revis\w*|change\s+from).{0,60}", full_text, re.IGNORECASE)
        print(f"  Explicit revision/change text: ...{snippet.group().strip()[:100]}...")
    else:
        print(f"  No explicit revision column — must diff consecutive issues")


# ---------------------------------------------------------------------------
# TXT probe
# ---------------------------------------------------------------------------

def _probe_txt(text: str, label: str) -> None:
    """Parse WASDE TXT content and print section structure."""
    _banner(label)
    total = len(text)
    formfeeds = text.count("\x0c")
    print(f"  Total chars    : {total:,}")
    print(f"  Form-feed (\\x0c) page breaks: {formfeeds}")

    # Show file start
    print(f"\n  File start (first 600 chars):")
    print(repr(text[:600]))

    # Split on "OUTLOOK FOR"
    parts = text.split("OUTLOOK FOR")
    print(f"\n  Splitting on 'OUTLOOK FOR' gives {len(parts)} parts")
    if len(parts) > 1:
        for i, part in enumerate(parts[1:], 1):
            first_line = part.split("\n")[0].strip()
            body_start = part.find("\n")
            body = part[body_start: body_start + 350].strip() if body_start != -1 else part[:350]
            print(f"\n  Section {i}: 'OUTLOOK FOR {first_line[:70]}'")
            print(f"    Body preview: {repr(body[:250])}")

    # Check for tables (fixed-width ASCII heuristic: lots of whitespace-aligned numbers)
    number_lines = [ln for ln in text.split("\n") if re.search(r"\d{3,}", ln) and ln.count(" ") > 10]
    print(f"\n  Lines with 3+ consecutive digits and heavy spacing (table rows?): {len(number_lines)}")
    if number_lines:
        print(f"  Sample: {repr(number_lines[0][:120])}")

    # Check for "OUTLOOK FOR" variants
    variants = re.findall(r"OUTLOOK\s+FOR\s+[A-Z ,/&]+", text)
    if variants:
        unique_v = sorted(set(v.strip() for v in variants))
        print(f"\n  All 'OUTLOOK FOR' variants found: {unique_v}")


# ---------------------------------------------------------------------------
# Section A — WAP direct PDFs from S3 (2002–2026)
# ---------------------------------------------------------------------------

def section_a(s3_client: Any) -> None:
    _section_header("SECTION A: WAP direct PDFs from S3 (2002–2026)")
    manifest_path = CONFIGS / "usda_wap_manifest.yaml"
    with open(manifest_path) as f:
        releases = yaml.safe_load(f)["releases"]
    print(f"  Manifest entries: {len(releases)}")
    print(f"  Range: {releases[0]['release_month']} to {releases[-1]['release_month']}")
    samples = _quintile_sample(releases)

    for r in samples:
        release_month = r["release_month"]
        s3_key = f"raw/production/source=usda_wap/release_month={release_month}/production.pdf"
        print(f"\n  → s3://{BUCKET}/{s3_key}")
        try:
            data = s3_client.get_object(Bucket=BUCKET, Key=s3_key)["Body"].read()
            print(f"  Size: {len(data):,} bytes")
            _probe_pdf(data, f"A: WAP direct PDF — {release_month}")
        except Exception as exc:
            print(f"  SKIP: {exc}")


# ---------------------------------------------------------------------------
# Section B — WAP archive.org scanned PDFs (1988–2002)
# ---------------------------------------------------------------------------

def section_b() -> None:
    _section_header("SECTION B: WAP archive.org scanned PDFs (1988–2002)")
    manifest_path = CONFIGS / "usda_wap_archiveorg_manifest.yaml"
    with open(manifest_path) as f:
        releases = yaml.safe_load(f)["releases"]
    print(f"  Manifest entries: {len(releases)}")
    print(f"  Range: {releases[0]['release_month']} to {releases[-1]['release_month']}")
    samples = _quintile_sample(releases)

    for r in samples:
        url = r["url"]
        release_month = r["release_month"]
        print(f"\n  → {url}")
        try:
            resp = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.content
            print(f"  Size: {len(data):,} bytes")
            _probe_pdf(data, f"B: WAP archive.org — {release_month}")
        except Exception as exc:
            print(f"  SKIP: {exc}")
        time.sleep(HTTP_SLEEP)


# ---------------------------------------------------------------------------
# Section C — WAP Wayback HTML (1996–2002)
# ---------------------------------------------------------------------------

def section_c() -> None:
    _section_header("SECTION C: WAP Wayback HTML (1996–2002)")
    manifest_path = CONFIGS / "usda_wap_wayback_manifest.yaml"
    with open(manifest_path) as f:
        releases = yaml.safe_load(f)["releases"]
    print(f"  Manifest entries: {len(releases)}")
    print(f"  Range: {releases[0]['release_month']} to {releases[-1]['release_month']}")
    samples = _quintile_sample(releases)

    for r in samples:
        url = r["wayback_url"]
        release_month = r["release_month"]
        fmt = r.get("format", "html")
        print(f"\n  → {url}  (format={fmt})")
        try:
            resp = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            if fmt == "pdf" or resp.content[:4] == b"%PDF":
                print(f"  Size: {len(resp.content):,} bytes (PDF)")
                _probe_pdf(resp.content, f"C: WAP Wayback PDF — {release_month}")
            else:
                html = resp.text
                print(f"  Size: {len(html):,} chars (HTML)")
                _probe_html(html, f"C: WAP Wayback HTML — {release_month}", url)
        except Exception as exc:
            print(f"  SKIP: {exc}")
        time.sleep(HTTP_SLEEP)


# ---------------------------------------------------------------------------
# Section D — WASDE digital PDFs from S3 (2000–2026)
# ---------------------------------------------------------------------------

def section_d(s3_client: Any) -> None:
    _section_header("SECTION D: WASDE digital PDFs from S3 (2000–2026)")
    manifest_path = CONFIGS / "usda_wasde_manifest.yaml"
    with open(manifest_path) as f:
        all_reports = yaml.safe_load(f)["reports"]

    # release_date may come back as a date object from PyYAML; normalise to str
    digital = [
        r for r in all_reports
        if r["fmt"] == "pdf" and str(r["release_date"]) >= "2000-01-01"
    ]
    print(f"  Digital PDF reports (2000+): {len(digital)}")
    print(f"  Range: {digital[0]['release_date']} to {digital[-1]['release_date']}")
    samples = _quintile_sample(digital)

    for r in samples:
        release_date = str(r["release_date"])
        filename = r["filename"]
        s3_key = f"raw/production/source=usda_wasde/release_date={release_date}/{filename}"
        print(f"\n  → s3://{BUCKET}/{s3_key}")
        try:
            data = s3_client.get_object(Bucket=BUCKET, Key=s3_key)["Body"].read()
            print(f"  Size: {len(data):,} bytes")
            _probe_pdf(data, f"D: WASDE digital PDF — {release_date}")
        except Exception as exc:
            print(f"  SKIP: {exc}")


# ---------------------------------------------------------------------------
# Section E — WASDE TXT from S3 (1995–1999)
# ---------------------------------------------------------------------------

def section_e(s3_client: Any) -> None:
    _section_header("SECTION E: WASDE TXT from S3 (1995–1999)")
    manifest_path = CONFIGS / "usda_wasde_manifest.yaml"
    with open(manifest_path) as f:
        all_reports = yaml.safe_load(f)["reports"]

    txt_reports = [r for r in all_reports if r["fmt"] == "txt"]
    print(f"  TXT reports: {len(txt_reports)}")
    print(f"  Range: {txt_reports[0]['release_date']} to {txt_reports[-1]['release_date']}")
    samples = _quintile_sample(txt_reports)

    for r in samples:
        release_date = str(r["release_date"])
        filename = r["filename"]
        s3_key = f"raw/production/source=usda_wasde/release_date={release_date}/{filename}"
        print(f"\n  → s3://{BUCKET}/{s3_key}")
        try:
            body = s3_client.get_object(Bucket=BUCKET, Key=s3_key)["Body"].read()
            # Try latin-1 first (USDA 1990s era TXT), then utf-8
            try:
                text = body.decode("latin-1")
            except UnicodeDecodeError:
                text = body.decode("utf-8", errors="replace")
            print(f"  Size: {len(text):,} chars")
            _probe_txt(text, f"E: WASDE TXT — {release_date}")
        except Exception as exc:
            print(f"  SKIP: {exc}")


# ---------------------------------------------------------------------------
# Section F — WASDE scanned PDFs from S3 (1973–1994)
# ---------------------------------------------------------------------------

def section_f(s3_client: Any) -> None:
    _section_header("SECTION F: WASDE scanned PDFs from S3 (1973–1994)")
    manifest_path = CONFIGS / "usda_wasde_manifest.yaml"
    with open(manifest_path) as f:
        all_reports = yaml.safe_load(f)["reports"]

    scanned = [
        r for r in all_reports
        if r["fmt"] == "pdf" and str(r["release_date"]) < "1995-01-01"
    ]
    print(f"  Scanned PDF reports (pre-1995): {len(scanned)}")
    print(f"  Range: {scanned[0]['release_date']} to {scanned[-1]['release_date']}")
    samples = _quintile_sample(scanned)

    for r in samples:
        release_date = str(r["release_date"])
        filename = r["filename"]
        s3_key = f"raw/production/source=usda_wasde/release_date={release_date}/{filename}"
        print(f"\n  → s3://{BUCKET}/{s3_key}")
        try:
            data = s3_client.get_object(Bucket=BUCKET, Key=s3_key)["Body"].read()
            print(f"  Size: {len(data):,} bytes")
            _probe_pdf(data, f"F: WASDE scanned PDF — {release_date}")
        except Exception as exc:
            print(f"  SKIP: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    requested = [s.lower() for s in sys.argv[1:]] if len(sys.argv) > 1 else list("abcdef")
    print(f"Sections to run : {requested}")
    print(f"Bucket          : {BUCKET}")
    print(f"Configs dir     : {CONFIGS}")

    s3_client = _s3() if any(s in requested for s in ["a", "d", "e", "f"]) else None

    if "a" in requested:
        section_a(s3_client)
    if "b" in requested:
        section_b()
    if "c" in requested:
        section_c()
    if "d" in requested:
        section_d(s3_client)
    if "e" in requested:
        section_e(s3_client)
    if "f" in requested:
        section_f(s3_client)

    print("\n\nDone.")
