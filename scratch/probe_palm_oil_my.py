"""Probe FAS GAIN for Malaysia palm oil reports across commodity IDs."""
import sys
sys.path.insert(0, "src")
sys.path.insert(0, ".")

import curl_cffi.requests as cr
from jobs.batch.gain_backfill_task import _get_html, _parse_listing, _iso2_from_title

URLS = {
    "cid=13023": (
        "https://fas.usda.gov/data/search"
        "?reports%5B0%5D=report_type%3A10251"
        "&reports%5B1%5D=report_commodities%3A13023"
    ),
    "cid=27": (
        "https://fas.usda.gov/data/search"
        "?reports%5B0%5D=report_type%3A10251"
        "&reports%5B1%5D=report_commodities%3A27"
    ),
    "no_cid": (
        "https://fas.usda.gov/data/search"
        "?reports%5B0%5D=report_type%3A10251"
    ),
}

with cr.Session() as sess:
    sess.headers.update({
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://fas.usda.gov/",
    })
    for label, base_url in URLS.items():
        print(f"\n=== {label} (pages 0-1) ===")
        for pg in range(2):
            url = base_url if pg == 0 else f"{base_url}&page={pg}"
            html = _get_html(sess, url)
            cards = _parse_listing(html) if html else []
            print(f"  Page {pg}: {len(cards)} cards")
            for c in cards:
                iso2 = _iso2_from_title(c["title"])
                is_palm = "palm" in c["title"].lower()
                is_my = (iso2 == "MY")
                if is_palm or is_my:
                    print(f"    [{iso2}] {c['title']}")
            if len(cards) == 0:
                break
