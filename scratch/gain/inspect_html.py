"""Quick HTML inspector for the FAS GAIN search page."""
from curl_cffi import requests as cr
import re

s = cr.Session()
s.headers["Accept"] = "text/html"

# Try both the GAIN listing page and the faceted search page
urls = [
    ("gain_listing", "https://fas.usda.gov/data/gain"),
    ("search_filtered", "https://fas.usda.gov/data/search?reports%5B0%5D=report_type%3A10251&reports%5B1%5D=report_commodities%3A609"),
]

for label, url in urls:
    print(f"\n{'='*60}")
    print(f"URL ({label}): {url}")
    r = s.get(url, impersonate="chrome124", timeout=30)
    print(f"Status: {r.status_code}  Length: {len(r.text)}")
    html = r.text

    # Find report links
    links = re.findall(r'href="(/data/gain/[^"]+)"', html)
    print(f"Report links (/data/gain/...): {len(links)}")
    for lk in links[:10]:
        print(f"  {lk}")

    # CSS class patterns that might indicate result rows
    for pattern in ["views-row", "search-result", "report-item", "c-card", "c-report",
                     "l-results", "view-content", "search-api", "result-item", "facets"]:
        count = html.count(pattern)
        if count:
            print(f"  CSS pattern {pattern!r}: {count} occurrences")

    # Print main content section
    main_m = re.search(r'id="main"', html)
    if main_m:
        snippet = html[main_m.start():main_m.start() + 3000]
        print(f"\nMain content (3000 chars):\n{snippet}")
    else:
        # Try <main tag
        main_m = re.search(r"<main", html)
        if main_m:
            snippet = html[main_m.start():main_m.start() + 3000]
            print(f"\n<main> section (3000 chars):\n{snippet}")
