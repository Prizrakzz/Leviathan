"""Check what PDF files from conab.gov.br are actually captured in Wayback CDX."""
import ssl
import urllib.request
import json
import time

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CTX = ssl.create_default_context()

def cdx_get(params_str: str) -> list:
    url = f"https://web.archive.org/cdx/search/cdx?{params_str}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    print(f"  CDX: {url[:110]}")
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
            raw = r.read()
            print(f"  Status: {r.status}  Bytes: {len(raw)}")
            return json.loads(raw) if raw else []
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return []

# Test 1: What captures exist for gid1183 download URL?
print("\n=== CDX for gid1183 download URL ===")
rows = cdx_get("url=www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/1183_46d101ed07800927c23e1828eec4ed4a&output=json&fl=timestamp,statuscode,mimetype&limit=20")
for r in rows:
    print(f"  {r}")
time.sleep(2)

# Test 2: CDX broad PDF search under conab.gov.br/images/ prefix
print("\n=== CDX for any PDF under conab.gov.br (images/, files/, attachments/) ===")
for prefix in ["www.conab.gov.br/images/", "www.conab.gov.br/files/", "www.conab.gov.br/media/"]:
    rows = cdx_get(f"url={prefix}&matchType=prefix&output=json&fl=timestamp,original,mimetype&filter=mimetype:application/pdf&collapse=original&limit=30")
    if rows:
        print(f"  Found {len(rows)} at {prefix}:")
        for r in rows[:10]:
            print(f"    {r}")
    else:
        print(f"  None at {prefix}")
    time.sleep(2)

# Test 3: CDX for any PDF with 'boletim' in URL from conab.gov.br
print("\n=== CDX boletim PDFs from conab.gov.br (prefix search) ===")
rows = cdx_get("url=www.conab.gov.br/&matchType=prefix&output=json&fl=timestamp,original,mimetype&filter=mimetype:application/pdf&filter=original:.*boletim.*&collapse=original&limit=50")
for r in rows[:20]:
    print(f"  {r}")
