"""
Probe WB Documents API and Wayback CDX for pre-2018 CMO Outlook reports.
"""
import requests, json

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0"})

# 1. WB Documents search API (docs.worldbank.org covers more than DSpace 7)
print("=== WB Documents API: CMO Outlook 2014-2017 ===")
r = s.get("https://search.worldbank.org/api/v2/wds", params={
    "format": "json",
    "q": "Commodity Markets Outlook",
    "strdate": "01/01/2014",
    "enddate": "12/31/2017",
    "rows": 20,
    "srt": "docdt",
    "order": "asc",
}, timeout=30)
r.raise_for_status()
data = r.json()
docs = data.get("documents", {})
for key, doc in list(docs.items())[:25]:
    if key == "facets":
        continue
    title = doc.get("display_title") or doc.get("docna", "")
    date = (doc.get("docdt") or "?")[:10]
    url = doc.get("pdfurl") or doc.get("url") or ""
    print(f"  {date}  {title[:70]}")
    if url:
        print(f"         {url[:90]}")

total = data.get("total", "?")
print(f"\n  total_results={total}\n")

# 2. Broader Wayback CDX: any openknowledge page mentioning commodity
print("=== Wayback CDX: openknowledge commodity handles (2014-2017) ===")
r2 = s.get("https://web.archive.org/cdx/search/cdx", params={
    "url": "openknowledge.worldbank.org/handle/10986/*",
    "matchType": "prefix",
    "output": "json",
    "fl": "timestamp,original",
    "limit": "15",
    "from": "20140101",
    "to": "20180101",
    "collapse": "original",
}, timeout=30)
rows2 = r2.json()[1:]
for ts, orig in rows2:
    print(f"  {ts[:8]}  {orig}")
print(f"  ({len(rows2)} hits)")
