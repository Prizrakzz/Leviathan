"""Find all Wayback PDF captures for CONAB Joomla download URLs.

The CDX scan reveals Wayback captured these URLs as PDFs under the
index.php/ URL prefix (the legacy Joomla non-SEF URL form):
  https://www.conab.gov.br/index.php/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/{gid_hash}

Also check the agricultura-familiar item/download URLs which also showed as PDFs.
"""
import ssl
import urllib.request
import json
import time

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CTX = ssl.create_default_context()

def cdx_get(params_str: str, timeout: int = 45) -> list:
    url = f"https://web.archive.org/cdx/search/cdx?{params_str}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else []
    except Exception as exc:
        print(f"  ERROR {url[:80]}: {exc}")
        return []

# Full scan: all item/download PDFs from conab.gov.br including index.php prefix
print("=== All item/download PDFs from Wayback CDX ===")
for base_url in [
    "www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/",
    "www.conab.gov.br/index.php/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/",
]:
    rows = cdx_get(
        f"url={base_url}&matchType=prefix"
        "&output=json&fl=timestamp,original,statuscode,mimetype"
        "&filter=mimetype:application/pdf"
        "&collapse=original"
        "&limit=200"
    )
    pdfs = [r for r in rows if r and r != ['timestamp','original','statuscode','mimetype'] and len(r) >= 2]
    print(f"\nBase: {base_url}")
    print(f"Found {len(pdfs)} PDF captures:")
    for row in pdfs:
        gid = row[1].split("/item/download/")[-1] if "/item/download/" in row[1] else "?"
        print(f"  ts={row[0]}  gid={gid[:45]}  mime={row[3] if len(row)>3 else '?'}")
    time.sleep(2)

# Also check for the safra 2015-2022 gid range (24xxx-45xxx)
print("\n=== CDX check for gid ranges NOT shown above ===")
# A few specific known gids to verify coverage
test_gids = {
    "1171 (safra 2013 1o)": "1171_9b6a51134e3bc5f18d5387a498b98c7d",
    "1183 (safra 2016 1o)": "1183_46d101ed07800927c23e1828eec4ed4a",
    "24572 (safra 2019 1o)": "24572_0d93c50ad02a492689d26f1319defa39",
    "28519 (safra 2019 3o)": "28519_1451c80af85a09013032c62c38317623",
    "33315 (safra 2020 3o)": "33315_25cecd701f64485618ddb18944982bd5",
    "35523 (safra 2021 1o)": "35523_38fae3bc88d9b5f875d991b8be1490da",
}
for label, gid_hash in test_gids.items():
    rows = cdx_get(
        f"url=www.conab.gov.br/index.php/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/{gid_hash}"
        "&output=json&fl=timestamp,statuscode,mimetype&limit=5"
    )
    data_rows = [r for r in rows if r and r != ['timestamp','statuscode','mimetype']]
    print(f"  {label}: {data_rows if data_rows else 'NOT FOUND'}")
    time.sleep(1.5)
