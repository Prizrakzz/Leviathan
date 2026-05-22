"""
Resolve pre-2018 CMO Outlook URLs via the WB archive page thedocs.worldbank.org links.

Two-step approach:
  1. Scrape the live archive page for all thedocs.worldbank.org link URLs
  2. For each URL without .pdf extension: fetch the landing page and extract
     the direct /original/*.pdf URL
  3. Validate the final PDF URL (HEAD/GET magic bytes check)
  4. Patch the manifest

Usage:
    python scratch/resolve_via_thedocs.py                            # probe only
    python scratch/resolve_via_thedocs.py --patch                    # probe + patch
    python scratch/resolve_via_thedocs.py --from-year 2013 --to-year 2013 --patch
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

ARCHIVE_URL = "https://www.worldbank.org/en/research/commodity-markets/report-archive"
THEDOCS_BASE = "https://thedocs.worldbank.org"
MANIFEST_PATH = (
    Path(__file__).parent.parent / "configs" / "sources" / "wb_cmo_outlook_manifest.yaml"
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_MONTH_MAP = {
    "january": "01", "jan": "01",
    "february": "02", "feb": "02",
    "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "may": "05",
    "june": "06", "jun": "06",
    "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09",
    "october": "10", "oct": "10",
    "november": "11", "nov": "11",
    "december": "12", "dec": "12",
    "q1": "01", "q2": "04", "q3": "07", "q4": "10",
    "h1": "01", "h2": "07",
}

# Filename patterns: CMO2013July, CMO-2008-January, CMOJanuary2014
_FNAME_RE = re.compile(
    r"CMO[- _]?(\d{4})[- _]?([A-Za-z]+)|CMO[- _]?([A-Za-z]+)[- _]?(\d{4})",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _release_from_filename(url: str) -> str | None:
    """Extract YYYY-MM from a URL path segment."""
    filename = url.split("/")[-1].split("?")[0]
    m = _FNAME_RE.search(filename)
    if not m:
        return None
    if m.group(1) and m.group(2):
        year, mon_raw = m.group(1), m.group(2).lower()[:3]
    else:
        mon_raw, year = m.group(3).lower()[:3], m.group(4)
    month = _MONTH_MAP.get(mon_raw)
    return f"{year}-{month}" if month else None


def _release_from_link_text(link_text: str, year: int | None) -> str | None:
    """Infer YYYY-MM from link label (Jan, Q1, etc.) and year context."""
    if year is None:
        return None
    text = re.sub(r"^\d{4}", "", link_text.strip()).strip().lower()
    month = _MONTH_MAP.get(text)
    return f"{year}-{month}" if month else None


def _abs(href: str) -> str:
    return href if href.startswith("http") else f"{THEDOCS_BASE}{href}"


def _priority(href: str, link_text: str) -> int:
    fname = href.split("/")[-1].lower()
    link = link_text.lower()
    # Deprioritise clearly supplementary files
    if any(x in fname for x in ["data", "special", "focus", "feature"]):
        return 0
    if any(x in link for x in ["excel", "zip", "special focus", "feature"]):
        return 0
    if href.lower().endswith(".pdf"):
        return 3
    return 1


# ---------------------------------------------------------------------------
# Landing page resolver
# ---------------------------------------------------------------------------

def _resolve_to_pdf_url(raw_url: str, session: requests.Session) -> str | None:
    """Convert any thedocs URL to a direct /original/*.pdf URL.

    If raw_url already ends in .pdf, return it as-is.
    Otherwise fetch the landing page and return the first /original/*.pdf href.
    """
    if raw_url.lower().endswith(".pdf"):
        return raw_url

    try:
        r = session.get(raw_url, timeout=20, allow_redirects=True)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "pdf" in ct.lower():
            return raw_url  # server returned PDF directly (redirect)
        soup = BeautifulSoup(r.text, "html.parser")
        # Prefer /original/ path PDF links
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/original/" in href and href.lower().endswith(".pdf"):
                return _abs(href)
        # Fallback: any .pdf link
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf"):
                return _abs(href)
    except Exception as exc:
        print(f"      landing page error: {exc}")
    return None


def _validate_pdf(url: str, session: requests.Session) -> bool:
    """Return True if URL serves a PDF (by content-type or %PDF magic).

    Always uses GET with stream=True because thedocs.worldbank.org returns
    incorrect content-type for HEAD requests on some files.
    """
    try:
        r = session.get(url, timeout=25, stream=True, allow_redirects=True)
        ct = r.headers.get("content-type", "")
        if "pdf" in ct.lower():
            r.close()
            return True
        for chunk in r.iter_content(8):
            r.close()
            return chunk[:4] == b"%PDF"
        r.close()
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Archive page scraping
# ---------------------------------------------------------------------------

def scrape_archive_grouped(session: requests.Session) -> dict[str, list[dict]]:
    """Fetch archive page; return {release_date: [candidates sorted by priority]}."""
    print(f"Fetching {ARCHIVE_URL} …")
    r = session.get(ARCHIVE_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    grouped: dict[str, list[dict]] = {}
    for table in soup.find_all("table"):
        current_year: int | None = None
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if cells:
                m = re.match(r"^(\d{4})", cells[0].get_text(strip=True))
                if m:
                    current_year = int(m.group(1))

            for a in row.find_all("a", href=True):
                href = a["href"]
                if "thedocs.worldbank.org" not in href:
                    continue
                link_text = a.get_text(strip=True)
                rd = _release_from_filename(href) or _release_from_link_text(link_text, current_year)
                if not rd:
                    continue
                grouped.setdefault(rd, []).append({
                    "url": _abs(href),
                    "link_text": link_text,
                    "priority": _priority(href, link_text),
                })

    # Sort each group so highest-priority candidates come first
    for rd in grouped:
        grouped[rd].sort(key=lambda c: c["priority"], reverse=True)

    print(f"  Unique release dates found: {len(grouped)}")
    return grouped


# ---------------------------------------------------------------------------
# Main resolution loop
# ---------------------------------------------------------------------------

def resolve_entries(
    grouped: dict[str, list[dict]],
    unresolved_dates: list[str],
    session: requests.Session,
) -> list[dict]:
    results = []
    for release_date in sorted(unresolved_dates):
        candidates = grouped.get(release_date, [])
        if not candidates:
            print(f"  {release_date}  [no candidates on archive page]")
            results.append({"release_date": release_date, "url": None})
            continue

        resolved_url: str | None = None
        for c in candidates:
            raw_url = c["url"]
            link_text = c["link_text"]
            print(f"  {release_date}  [{link_text!r:<25}] {raw_url[-65:]}")

            pdf_url = _resolve_to_pdf_url(raw_url, session)
            if not pdf_url:
                print(f"      ✗ no PDF link on landing page")
                time.sleep(0.4)
                continue

            if pdf_url != raw_url:
                print(f"      → {pdf_url[-65:]}")

            if _validate_pdf(pdf_url, session):
                resolved_url = pdf_url
                print(f"      ✓ PDF confirmed")
                break
            else:
                print(f"      ✗ not a PDF or unreachable")
            time.sleep(0.4)

        if resolved_url:
            results.append({
                "release_date": release_date,
                "url": resolved_url,
                "notes": "thedocs.worldbank.org PDF via WB archive page",
            })
        else:
            print(f"      → NO valid PDF found for {release_date}")
            results.append({"release_date": release_date, "url": None})

        time.sleep(0.5)

    return results


# ---------------------------------------------------------------------------
# Manifest patching
# ---------------------------------------------------------------------------

def patch_manifest(results: list[dict]) -> None:
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    patched = skipped = 0

    for res in results:
        if not res.get("url"):
            skipped += 1
            continue

        rd = res["release_date"]
        url = res["url"].replace('"', '\\"')
        notes = (res.get("notes") or "").replace('"', '\\"')

        pattern = re.compile(
            r"(  - release_date: \"" + re.escape(rd) + r"\".*?"
            r'    url: )""'
            r"(.*?    wayback_needed: )true"
            r'(.*?    notes: )"[^"]*"',
            re.DOTALL,
        )

        def _sub(m: re.Match, _u: str = url, _n: str = notes) -> str:
            return m.group(1) + f'"{_u}"' + m.group(2) + "false" + m.group(3) + f'"{_n}"'

        new_text, n = pattern.subn(_sub, text)
        if n == 1:
            text = new_text
            patched += 1
            print(f"  Patched {rd}")
        elif n == 0:
            print(f"  WARNING: no match for {rd}")
        else:
            print(f"  WARNING: {n} matches for {rd} — skipped")

    MANIFEST_PATH.write_text(text, encoding="utf-8")
    print(f"\nManifest: {patched} patched, {skipped} skipped (no URL)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch", action="store_true", help="Write resolved URLs to manifest")
    ap.add_argument("--from-year", type=int, default=1994)
    ap.add_argument("--to-year", type=int, default=2017)
    args = ap.parse_args()

    session = requests.Session()
    session.headers["User-Agent"] = UA

    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    all_entries: list[dict] = manifest["reports"]

    unresolved = [
        e["release_date"]
        for e in all_entries
        if e.get("wayback_needed")
        and args.from_year <= int(e["release_date"][:4]) <= args.to_year
    ]
    print(f"Unresolved in {args.from_year}–{args.to_year}: {len(unresolved)}\n")

    grouped = scrape_archive_grouped(session)

    print(f"\n[Resolving {len(unresolved)} entries]\n")
    results = resolve_entries(grouped, unresolved, session)

    resolved = [r for r in results if r.get("url")]
    not_found = [r for r in results if not r.get("url")]

    print(f"\n{'='*60}")
    print(f"Resolved:   {len(resolved)}")
    print(f"Not found:  {len(not_found)}")
    if not_found:
        print(f"Unresolved dates: {[r['release_date'] for r in not_found]}")

    if args.patch and resolved:
        print("\nPatching manifest …")
        patch_manifest(resolved)
    elif resolved and not args.patch:
        print(f"\nRun with --patch to write these {len(resolved)} URL(s).")


if __name__ == "__main__":
    main()
