"""Probe openknowledge handle pages for 5 missing recent CMO Outlook reports."""
import re
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
session = requests.Session()
session.headers["User-Agent"] = UA

BITSTREAM_RE = re.compile(
    r"openknowledge\.worldbank\.org/bitstreams/[^\s\"'<>]+/download",
    re.IGNORECASE,
)

# Handle IDs sourced from openknowledge search / DOI lookups
test_handles = {
    "2021-04": "https://openknowledge.worldbank.org/handle/10986/35551",
    "2023-04": "https://openknowledge.worldbank.org/handle/10986/39616",
    "2023-10": "https://openknowledge.worldbank.org/handle/10986/40553",
    "2024-04": "https://openknowledge.worldbank.org/handle/10986/41486",
    "2025-10": "https://openknowledge.worldbank.org/handle/10986/43110",
}

for label, url in test_handles.items():
    try:
        r = session.get(url, timeout=20)
        print(f"\n--- {label} (HTTP {r.status_code}) ---")
        print(f"Final URL: {r.url}")
        m = BITSTREAM_RE.search(r.text)
        if m:
            print(f"  BITSTREAM: https://{m.group(0)}")
        else:
            soup = BeautifulSoup(r.text, "html.parser")
            hits = [
                a["href"]
                for a in soup.find_all("a", href=True)
                if "bitstream" in a.get("href", "")
            ]
            print(f"  bitstream hrefs: {hits[:5]}")
    except Exception as exc:
        print(f"{label}: ERROR {exc}")
