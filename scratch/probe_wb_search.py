"""Quick probe of WB documents search for unresolved CMO Outlook entries."""
import requests

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"

queries = {
    "2015-01": "commodity markets outlook January 2015",
    "2017-04": "commodity markets outlook April 2017",
    "2017-10": "commodity markets outlook October 2017",
    "1996-11": "commodity markets outlook November 1996",
}

for date_key, q in queries.items():
    url = "https://search.worldbank.org/api/v2/wds"
    params = {
        "format": "json",
        "q": q,
        "fl": "doc_id,docdt,url,repnme,titl",
        "rows": 3,
        "srt": "docdt",
        "so": "ASC",
    }
    try:
        r = session.get(url, params=params, timeout=15)
        docs = r.json().get("documents", {})
        hits = [v for k, v in docs.items() if k not in ("facets", "total")]
        print(f"\n{date_key}:")
        if not hits:
            print("  (no results)")
        for h in hits[:3]:
            print(f"  {h.get('titl','')[:70]}")
            print(f"  url: {h.get('url','')[:100]}")
    except Exception as e:
        print(f"{date_key}: error {e}")
