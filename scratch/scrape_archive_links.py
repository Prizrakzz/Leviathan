"""
Scrape the live WB CMO archive page, resolve ALL thedocs.worldbank.org PDF links
(via landing pages when needed), and patch the manifest.

Usage:
    python scratch/scrape_archive_links.py           # probe only, print results
    python scratch/scrape_archive_links.py --patch   # probe + patch manifest
    python scratch/scrape_archive_links.py --patch --also-2014-2017
        # also try to find main report PDFs for 2014-2017 via doc landing pages
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
MANIFEST_PATH = (
    Path(__file__).parent.parent / "configs" / "sources" / "wb_cmo_outlook_manifest.yaml"
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Month name → zero-padded month number
_MONTH_NAME_MAP = {
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
    # quarter / half-year → approximate month
    "q1": "01", "q2": "04", "q3": "07", "q4": "10",
    "h1": "01", "h2": "07",
}

# Year embedded in thedocs URL suffix: -0050022017 → 2017
_THEDOCS_YEAR_RE = re.compile(r"-005002(\d{4})$")
# Filename-based year+month hint, e.g. CMO2013July, CMOJanuary2014, CMO-2008-January
_FILENAME_DATE_RE = re.compile(
    r"CMO[- ]?(\d{4})[- ]?([A-Za-z]+)|CMO[- ]?([A-Za-z]+)[- ]?(\d{4})",
    re.IGNORECASE,
)


def _parse_release_from_url(href: str) -> str | None:
    """Try to extract YYYY-MM release date from a thedocs URL."""
    # Try filename portion (last path segment)
    filename = href.split("/")[-1].split("?")[0]
    m = _FILENAME_DATE_RE.search(filename)
    if m:
        if m.group(1) and m.group(2):
            year, mon = m.group(1), m.group(2).lower()[:3]
        else:
            mon, year = m.group(3).lower()[:3], m.group(4)
        month = _MONTH_NAME_MAP.get(mon)
        if month:
            return f"{year}-{month}"

    # Try the suffix year + label context (caller must supply)
    return None


def _parse_release_from_context(link_text: str, year: int | None) -> str | None:
    """Infer YYYY-MM from link text (Jan, February, Q1, H2, 2013Q3, etc.) + year."""
    if year is None:
        return None
    text = link_text.strip().lower()
    # Might be like "2013q3" — strip the year prefix
    text = re.sub(r"^\d{4}", "", text).strip()
    month = _MONTH_NAME_MAP.get(text)
    if month:
        return f"{year}-{month}"
    return None


def _validate_url_as_pdf(url: str, session: requests.Session) -> bool:
    """HEAD (or GET) the URL; return True if it delivers a PDF."""
    try:
        r = session.head(url, timeout=20, allow_redirects=True)
        if r.status_code == 405:  # HEAD not allowed
            r = session.get(url, timeout=20, stream=True)
        content_type = r.headers.get("content-type", "")
        if "pdf" in content_type.lower():
            return True
        # Try reading the first 8 bytes for %PDF magic
        if hasattr(r, "content"):
            return r.content[:4] == b"%PDF"
        for chunk in r.iter_content(8):
            return chunk[:4] == b"%PDF"
    except Exception as exc:
        print(f"    validation error: {exc}")
    return False


def scrape_archive_links(session: requests.Session) -> list[dict]:
    """Fetch the archive page and return list of {release_date, url, label, link_text}."""
    print(f"Fetching {ARCHIVE_URL} …")
    r = session.get(ARCHIVE_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    found: list[dict] = []

    # Walk the page looking for thedocs links (and openknowledge bitstream handle links)
    # grouped by their closest year context
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        current_year: int | None = None
        for row in rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            first_cell_text = cells[0].get_text(strip=True)
            m = re.match(r"^(\d{4})", first_cell_text)
            if m:
                current_year = int(m.group(1))

            for a in row.find_all("a", href=True):
                href = a["href"]
                link_text = a.get_text(strip=True)

                is_thedocs = "thedocs.worldbank.org" in href
                is_openknowledge_handle = (
                    "openknowledge.worldbank.org/bitstream/handle" in href
                    and ".pdf" in href.lower()
                )

                if not (is_thedocs or is_openknowledge_handle):
                    continue

                # Skip Excel / Zip / data supplement links (we want main report PDFs)
                skip_keywords = ["data", "excel", "zip", "supplement", "special", "focus",
                                 "feature", "gdf", "gep", "h1", "h2", "q1", "q2"]
                link_lower = link_text.lower()
                fname_lower = href.split("/")[-1].lower()
                if any(kw in link_lower for kw in ["excel", "zip", "data", "special focus",
                                                     "feature", "focus"]):
                    # Skip data/supplementary links
                    pass  # fall through — we might still want these if they look like main PDFs
                # Actually let's keep ALL thedocs links and filter later
                # The validate step will check if it's a real PDF

                # Try to determine release_date
                release_date = _parse_release_from_url(href)
                if not release_date and current_year:
                    release_date = _parse_release_from_context(link_text, current_year)

                # For thedocs links without .pdf extension — resolve the year from URL suffix
                if not release_date:
                    m2 = _THEDOCS_YEAR_RE.search(href)
                    if m2:
                        url_year = int(m2.group(1))
                        release_date = _parse_release_from_context(link_text, url_year)

                if not release_date:
                    continue  # can't map to a manifest entry

                found.append({
                    "release_date": release_date,
                    "url": href,
                    "link_text": link_text,
                    "is_thedocs": is_thedocs,
                })

    print(f"  Raw candidate links extracted: {len(found)}")
    return found


def deduplicate_and_prefer_pdf(candidates: list[dict]) -> dict[str, list[dict]]:
    """Group candidates by release_date."""
    grouped: dict[str, list[dict]] = {}
    for c in candidates:
        rd = c["release_date"]
        grouped.setdefault(rd, []).append(c)
    return grouped


def resolve_candidates(
    grouped: dict[str, list[dict]],
    manifest_entries: list[dict],
    session: requests.Session,
) -> list[dict]:
    """For each unresolved manifest entry, probe candidates to find a valid PDF URL."""
    unresolved = {
        e["release_date"]: e
        for e in manifest_entries
        if e.get("wayback_needed")
    }

    results = []
    for release_date, entry in sorted(unresolved.items()):
        candidates = grouped.get(release_date, [])
        if not candidates:
            results.append({"release_date": release_date, "url": None, "notes": None})
            print(f"  {release_date}  no candidates from archive page")
            continue

        # Prefer candidates whose filename looks like the full report (not data/special focus)
        def score(c: dict) -> int:
            fname = c["url"].split("/")[-1].lower()
            link = c["link_text"].lower()
            # Deprioritise clearly supplementary links
            if any(x in fname for x in ["data", "special", "focus", "feature", "gdf", "gep"]):
                return 0
            if any(x in link for x in ["excel", "zip", "data supp", "special focus"]):
                return 0
            if fname.endswith(".pdf"):
                return 3
            if "pdf" in link:
                return 2
            return 1

        candidates_sorted = sorted(candidates, key=score, reverse=True)

        resolved_url = None
        for c in candidates_sorted:
            url = c["url"]
            print(f"  {release_date}  probing: [{c['link_text']!r}] {url[:80]}")
            if _validate_url_as_pdf(url, session):
                resolved_url = url
                print(f"    ✓ PDF confirmed")
                break
            else:
                print(f"    ✗ not a PDF (or error)")
            time.sleep(0.3)

        if resolved_url:
            results.append({
                "release_date": release_date,
                "url": resolved_url,
                "notes": f"thedocs.worldbank.org link from archive page",
            })
        else:
            results.append({"release_date": release_date, "url": None, "notes": None})
            print(f"    → no valid PDF found for {release_date}")

        time.sleep(0.5)

    return results


def try_thedocs_landing_pages_2014_2017(
    grouped: dict[str, list[dict]],
    manifest_entries: list[dict],
    session: requests.Session,
) -> list[dict]:
    """For 2014-2017 entries: look at thedocs doc landing pages for main report PDFs.

    The archive page only has Excel/special-focus links for 2014-2017.
    But thedocs landing pages often list related documents including the full PDF.
    """
    unresolved = [
        e for e in manifest_entries
        if e.get("wayback_needed") and 2014 <= int(e["release_date"][:4]) <= 2017
    ]
    print(f"\n[2014-2017 landing page probe] {len(unresolved)} entries\n")

    # Build a map: release_date → thedocs doc hash (from any available link for that year)
    year_to_hash: dict[int, list[str]] = {}
    for release_date, candidates in grouped.items():
        year = int(release_date[:4])
        if 2014 <= year <= 2017:
            for c in candidates:
                href = c["url"]
                if "thedocs.worldbank.org" in href:
                    m = re.search(r"/en/doc/(\d+)-\d{10}/", href)
                    if m:
                        year_to_hash.setdefault(year, []).append(m.group(1))

    results = []
    for entry in unresolved:
        release_date = entry["release_date"]
        year = int(release_date[:4])
        hashes = year_to_hash.get(year, [])
        if not hashes:
            print(f"  {release_date}  no thedocs doc hashes found for year {year}")
            results.append({"release_date": release_date, "url": None, "notes": None})
            continue

        # Try fetching the landing page for each known hash and look for main PDF link
        found_url = None
        for doc_hash in hashes[:3]:  # cap at 3 tries per entry
            suffix_pattern = re.compile(r"-005002\d{4}$")
            # Find the full doc ID from grouped candidates
            full_id = None
            for cands in grouped.values():
                for c in cands:
                    if "thedocs.worldbank.org" in c["url"] and doc_hash in c["url"]:
                        m = re.search(r"/en/doc/(\d+-\d{10})/", c["url"])
                        if m:
                            full_id = m.group(1)
                            break
                if full_id:
                    break

            if not full_id:
                continue

            landing_url = f"https://thedocs.worldbank.org/en/doc/{full_id}/"
            print(f"  {release_date}  fetching landing page: {landing_url}")
            try:
                r = session.get(landing_url, timeout=20, allow_redirects=True)
                r.raise_for_status()
                # Look for .pdf links on the landing page
                lsoup = BeautifulSoup(r.text, "html.parser")
                for a in lsoup.find_all("a", href=True):
                    pdf_href = a["href"]
                    pdf_text = a.get_text(strip=True).lower()
                    if pdf_href.endswith(".pdf") and "data" not in pdf_text:
                        full_pdf = (
                            pdf_href if pdf_href.startswith("http")
                            else f"https://thedocs.worldbank.org{pdf_href}"
                        )
                        print(f"    found PDF link: {full_pdf[:80]}")
                        if _validate_url_as_pdf(full_pdf, session):
                            found_url = full_pdf
                            print(f"    ✓ PDF confirmed")
                            break
            except Exception as exc:
                print(f"    landing page error: {exc}")
            time.sleep(0.5)

            if found_url:
                break

        if found_url:
            results.append({
                "release_date": release_date,
                "url": found_url,
                "notes": f"thedocs landing page (2014-2017 main report)",
            })
        else:
            print(f"  {release_date}  → not found via landing pages")
            results.append({"release_date": release_date, "url": None, "notes": None})

    return results


def patch_manifest(resolved: list[dict]) -> None:
    """Write resolved URLs back into the manifest YAML using regex text replacement."""
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    patched = 0
    skipped = 0

    for r in resolved:
        if not r.get("url"):
            skipped += 1
            continue

        release_date = r["release_date"]
        url = r["url"]
        notes = (r.get("notes") or "").replace('"', '\\"')
        escaped_url = url.replace('"', '\\"')

        entry_pattern = re.compile(
            r"(  - release_date: \"" + re.escape(release_date) + r"\".*?"
            r'    url: )""'
            r"(.*?    wayback_needed: )true"
            r'(.*?    notes: )"[^"]*"',
            re.DOTALL,
        )

        def replacer(m: re.Match, _url: str = escaped_url, _notes: str = notes) -> str:
            return (
                m.group(1) + f'"{_url}"'
                + m.group(2) + "false"
                + m.group(3) + f'"{_notes}"'
            )

        new_text, n = entry_pattern.subn(replacer, text)
        if n == 1:
            text = new_text
            patched += 1
            print(f"  Patched {release_date}")
        elif n == 0:
            print(f"  WARNING: no match for {release_date}")
        else:
            print(f"  WARNING: {n} matches for {release_date} — skipping")

    MANIFEST_PATH.write_text(text, encoding="utf-8")
    print(f"\nManifest updated: {patched} patched, {skipped} skipped (no URL)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", action="store_true",
                        help="Write resolved URLs to manifest")
    parser.add_argument("--also-2014-2017", action="store_true",
                        help="Also probe thedocs landing pages for 2014-2017 main PDFs")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries: list[dict] = manifest["reports"]

    # Step 1: scrape archive page for all thedocs/openknowledge links
    candidates = scrape_archive_links(session)
    grouped = deduplicate_and_prefer_pdf(candidates)

    print(f"\n  Release dates found on archive page: {sorted(grouped.keys())}\n")

    # Step 2: resolve candidates for each unresolved manifest entry
    print("[Resolving manifest entries from archive page links]")
    results = resolve_candidates(grouped, entries, session)

    # Step 3 (optional): try thedocs landing pages for 2014-2017
    if args.also_2014_2017:
        extra = try_thedocs_landing_pages_2014_2017(grouped, entries, session)
        # Merge: prefer results over extra (results was first-pass)
        resolved_dates = {r["release_date"] for r in results if r.get("url")}
        for e in extra:
            if e["release_date"] not in resolved_dates and e.get("url"):
                results.append(e)

    resolved = [r for r in results if r.get("url")]
    unresolved = [r for r in results if not r.get("url")]

    print(f"\n--- Summary ---")
    print(f"  Resolved:   {len(resolved)}")
    print(f"  Unresolved: {len(unresolved)}")
    if resolved:
        for r in resolved:
            print(f"    {r['release_date']}  {r['url'][:80]}")
    if unresolved:
        print(f"  Still needed: {[r['release_date'] for r in unresolved]}")

    if args.patch and resolved:
        print(f"\nPatching manifest …")
        patch_manifest(resolved)
    elif resolved and not args.patch:
        print(f"\nRun with --patch to write these URLs to the manifest.")


if __name__ == "__main__":
    main()
