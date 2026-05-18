"""
Scrape the June 2022 Wayback snapshot of the CONAB listing page (start=0)
to identify the original gids for safra 2021/2022 before the re-upload.
Also downloads a sample PDF for each mystery gid to confirm the safra/levantamento.
"""
import re
import ssl
import urllib.request
from html.parser import HTMLParser
from typing import Optional

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CTX = ssl.create_default_context()
LISTING_BASE = "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe"
DOWNLOAD_BASE = "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download"

# Mystery gids found via CDX prefix scan at June 2022 timestamps
MYSTERY_GIDS = [
    ("42143_a597248239f850c6753b2f1d1e4e826b", "20220624154229"),
    ("40911_0eac1d762da9a95acc3d8d4bd36d7359", "20220624154241"),
    ("40314_5ca4f5eaec7d5fb8e90ec9645427e205", "20220624154256"),
    ("39155_6833f8ba418f3fab83c6d910ce7ecfba", "20220624154307"),
    ("37221_c140375aec407df98f74995349fc365f", "20220624154351"),
]

# Additional CDX gids from 2024/2025 worth checking
EXTRA_GIDS = [
    ("46198_948b1c7df3f80ff9b87160bf67f15c28", "20240415152711"),
    ("46199_d2db48d30b790086dd8ddc95f2bd9dab", "20240807220203"),
    ("45165_unknown", "20240414090123"),   # known from CDX; need real hash
    ("45166_unknown", "20250317012213"),   # known from CDX; need real hash
]


def wayback_get_html(wayback_url: str) -> Optional[str]:
    req = urllib.request.Request(wayback_url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def peek_pdf(gid_hash: str, ts: str, max_kb: int = 8) -> Optional[str]:
    """Download the first max_kb KB of the PDF and look for the title."""
    url = f"https://web.archive.org/web/{ts}if_/{DOWNLOAD_BASE}/{gid_hash}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes=0-{max_kb * 1024}"})
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            data = r.read(max_kb * 1024)
            ct = r.info().get("Content-Type", "?")
            if b"%PDF" not in data[:4]:
                return f"NOT PDF: {ct} | {data[:60]}"
            # Look for PDF info dict / title patterns in first 8KB (often in metadata)
            text = data.decode("latin-1", errors="replace")
            # Search for "Boletim" or "Safra" or "Levantamento" in the binary
            for pattern in [r"Safra\s+\d{4}", r"\d+[ºo°]\s*[Ll]evantamento", r"Boletim\s+da\s+Safra"]:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    return f"MATCH: {m.group()!r}  (pdf)"
            return f"PDF {len(data)}B (no title match in header)"
    except Exception as e:
        return f"ERROR: {e}"


print("=" * 70)
print("Scraping June 2022 Wayback listing page (start=0)")
print("=" * 70)

JUN2022_TS = "20220624154429"
listing_url = f"https://web.archive.org/web/{JUN2022_TS}/{LISTING_BASE}?start=0"
print(f"URL: {listing_url}\n")
html = wayback_get_html(listing_url)
if html:
    # Parse h2 headings and download links
    headings = re.findall(r'<h2[^>]*>\s*(.*?)\s*</h2>', html, re.DOTALL | re.IGNORECASE)
    headings = [re.sub(r'<[^>]+>', '', h).strip() for h in headings]
    links = re.findall(r'href="[^"]*?/item/download/(\d+_[0-9a-f]+)"', html, re.IGNORECASE)
    print(f"Found {len(headings)} h2 headings, {len(links)} download links")
    for i, (h, l) in enumerate(zip(headings, links)):
        print(f"  [{i}] {h[:80]}")
        print(f"       gid={l}")
    print()

print("=" * 70)
print("PDF title probes for mystery gids")
print("=" * 70)
for gid_hash, ts in MYSTERY_GIDS:
    print(f"\n  gid {gid_hash[:12]} (ts={ts})")
    result = peek_pdf(gid_hash, ts)
    print(f"  → {result}")
