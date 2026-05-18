"""Follow the Wayback redirect chain manually to find the final PDF URL."""
import ssl
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CTX = ssl.create_default_context()

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=CTX),
    NoRedirectHandler(),
)

# These were the redirect targets found in probe_wayback_redirect.py
test_urls = [
    ("gid1183-wb-ts2",  "https://web.archive.org/web/20220714211141/https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/1183_46d101ed07800927c23e1828eec4ed4a"),
    ("gid24572-wb-ts2", "https://web.archive.org/web/20220714210928/https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/24572_0d93c50ad02a492689d26f1319defa39"),
]

for label, url in test_urls:
    print(f"\n── {label} ──")
    print(f"   {url[:100]}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=60) as r:
            data = r.read(2048)
            info = r.info()
            print(f"   Status: {r.status}")
            print(f"   Content-Type: {info.get('Content-Type','?')}")
            print(f"   Content-Length: {info.get('Content-Length','?')}")
            print(f"   Location: {info.get('Location','(none)')}")
            print(f"   First 20 bytes: {data[:20]}")
            if data[:4] == b"%PDF":
                print(f"   >>> IT'S A PDF! Total read: {len(data)} bytes")
    except urllib.error.HTTPError as e:
        location = e.headers.get("Location", "")
        print(f"   HTTPError {e.code}   Location: {location[:120]}")
        print(f"   CT: {e.headers.get('Content-Type','?')}")
    except Exception as exc:
        print(f"   ERROR: {exc}")
