"""Test if listing snap_ts with if_ modifier redirects to correct PDF capture."""
import ssl
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CTX = ssl.create_default_context()


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a):
        return None


opener_noredir = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=CTX), NoRedirectHandler()
)
opener_follow = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX))

GID = "1183_46d101ed07800927c23e1828eec4ed4a"
ORIG = f"https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/{GID}"

# Listing snap_ts for gid1183 (from page3 of listing = June 2022 snapshot)
LISTING_TS = "20220624154435"
CDX_TS = "20220714211141"

tests = [
    # (label, url, follow_redirect)
    (f"listing_ts + if_ (follow)",   f"https://web.archive.org/web/{LISTING_TS}if_/{ORIG}", True),
    (f"listing_ts + if_ (noredir)",  f"https://web.archive.org/web/{LISTING_TS}if_/{ORIG}", False),
    (f"cdx_ts + if_ (follow)",       f"https://web.archive.org/web/{CDX_TS}if_/{ORIG}", True),
]

for label, url, follow in tests:
    print(f"\n── {label} ──")
    print(f"   {url[-90:]}")
    opener = opener_follow if follow else opener_noredir
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with opener.open(req, timeout=60) as r:
            data = r.read(512)
            ct = r.info().get("Content-Type", "?")
            cl = r.info().get("Content-Length", "?")
            print(f"   Status: {r.status}   CT: {ct[:60]}   CL: {cl}")
            print(f"   First bytes: {data[:20]}")
            if data[:4] == b"%PDF":
                print(f"   >>> IS A PDF!  ({cl} bytes)")
    except urllib.error.HTTPError as e:
        print(f"   HTTPError {e.code}  Location: {e.headers.get('Location','')[:100]}")
    except Exception as exc:
        print(f"   ERROR: {exc}")
