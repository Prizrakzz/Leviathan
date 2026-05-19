"""Manual retry for the 3 bulletins that failed in the main job."""
import ssl, urllib.request, json
from curl_cffi import requests as cr

BASE = "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download"
SSL_CTX = ssl.create_default_context()

MISSING = [
    {"label": "3o/2022", "gid": "43031_158073aea1af4048cdbd8e12898d3eb8", "snap": "20220811171826"},
    {"label": "4o/2022", "gid": "45502_94f81af36eb923bc7561183a3f1e1761", "snap": "20221219095715"},
    {"label": "1o/2019", "gid": "24572_0d93c50ad02a492689d26f1319defa39", "snap": "20210206051321"},
]

for m in MISSING:
    gid   = m["gid"]
    snap  = m["snap"]
    label = m["label"]
    orig  = f"{BASE}/{gid}"
    print(f"\n--- {label}  gid={gid[:25]}... ---")

    # Strategy 1: Wayback snap if_
    wb1 = f"https://web.archive.org/web/{snap}if_/{orig}"
    try:
        req = urllib.request.Request(wb1, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=25) as r:
            data = r.read()
        print(f"  [snap if_]  HTTP {r.status}  {len(data)} bytes  magic={data[:4].hex()}")
    except Exception as e:
        print(f"  [snap if_]  ERROR: {e}")

    # Strategy 2: CDX lookup
    cdx_url = (
        f"https://web.archive.org/cdx/search/cdx"
        f"?url={orig}&output=json&fl=timestamp&limit=3&filter=statuscode:200"
    )
    try:
        req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as r:
            rows = json.loads(r.read())
        print(f"  [CDX]  {len(rows)-1} hits: {[r[0] for r in rows[1:]]}")
    except Exception as e:
        print(f"  [CDX]  ERROR: {e}")

    # Strategy 3: Direct gov.br (curl_cffi, TLS impersonation)
    try:
        resp = cr.get(orig, impersonate="chrome124", timeout=20, allow_redirects=True)
        print(f"  [direct]  HTTP {resp.status_code}  {len(resp.content)} bytes  magic={resp.content[:4].hex()}  final={resp.url[-80:]}")
    except Exception as e:
        print(f"  [direct]  ERROR: {e}")
