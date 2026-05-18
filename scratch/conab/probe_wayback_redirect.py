"""Diagnose what Wayback returns for download URLs — check redirect chain without following."""
import ssl
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CTX = ssl.create_default_context()

# Disable automatic redirect following so we see the raw response
class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=CTX),
    NoRedirectHandler(),
)

test_urls = [
    # Old gid - small gid number from 2016
    ("gid1183-wb",  "https://web.archive.org/web/20220624154435/https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/1183_46d101ed07800927c23e1828eec4ed4a"),
    # Old gid from 2019
    ("gid24572-wb", "https://web.archive.org/web/20210206051321/https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/24572_0d93c50ad02a492689d26f1319defa39"),
    # Direct conab.gov.br - old gid
    ("gid1183-dir", "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/1183_46d101ed07800927c23e1828eec4ed4a"),
]

for label, url in test_urls:
    print(f"\n── {label} ──")
    print(f"   {url[:90]}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=30) as r:
            data = r.read(512)
            info = r.info()
            print(f"   Status: {r.status}   CT: {info.get('Content-Type','?')[:50]}")
            print(f"   Location: {info.get('Location','(none)')}")
            print(f"   First bytes: {data[:20]}")
    except urllib.error.HTTPError as e:
        print(f"   HTTPError {e.code}   Location: {e.headers.get('Location','?')}")
        print(f"   CT: {e.headers.get('Content-Type','?')}")
    except Exception as exc:
        print(f"   ERROR: {exc}")
