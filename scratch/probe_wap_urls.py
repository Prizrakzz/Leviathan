"""Use Wayback CDX to find actual historical URLs for USDA WAP production.pdf"""
import urllib.request, json, re

# Try CDX for the production.pdf URL to see historical patterns
cdx_url = (
    "https://web.archive.org/cdx/search/cdx"
    "?url=fas.usda.gov/sites/default/files/*/production.pdf"
    "&output=json"
    "&fl=timestamp,original,statuscode"
    "&filter=statuscode:200"
    "&limit=500"
    "&collapse=original"
)
req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    print(f"CDX records: {len(data)} (including header)")
    rows = data[1:]
    print("\nAll unique original URLs found:")
    for row in rows[:20]:
        print(" ", row[0], row[1])
except Exception as e:
    print("CDX error:", e)

# Also check the older URL pattern that USDA uses
# The WAP page at fas.usda.gov has a report archive - try the actual page link pattern
print("\n--- Checking Wayback for older WAP URL patterns ---")
cdx_url2 = (
    "https://web.archive.org/cdx/search/cdx"
    "?url=fas.usda.gov/*production*"
    "&output=json"
    "&fl=timestamp,original,statuscode"
    "&filter=statuscode:200"
    "&filter=original:.*production.*\.pdf"
    "&limit=50"
    "&collapse=original"
)
req2 = urllib.request.Request(cdx_url2, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req2, timeout=30) as r:
        data2 = json.load(r)
    rows2 = data2[1:] if len(data2) > 1 else []
    print(f"Found {len(rows2)} unique URLs")
    for row in rows2[:20]:
        print(" ", row[1])
except Exception as e:
    print("CDX error2:", e)
