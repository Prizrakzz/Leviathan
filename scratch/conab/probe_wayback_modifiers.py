"""Test Wayback raw-content modifiers to get actual PDF bytes."""
import ssl
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CTX = ssl.create_default_context()

def fetch(label, url, follow_redirect=True):
    if not follow_redirect:
        class NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a): return None
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=CTX), NoRedir()
        )
    else:
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    print(f"\n── {label} ──")
    print(f"   {url[-90:]}")
    try:
        with opener.open(req, timeout=60) as r:
            data = r.read(4096)
            ct = r.info().get("Content-Type", "?")
            cl = r.info().get("Content-Length", "?")
            print(f"   Status: {r.status}   CT: {ct[:60]}   CL: {cl}")
            print(f"   First bytes: {data[:20]}")
            if data[:4] == b"%PDF":
                print(f"   >>> IS A PDF!")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location", "")
        print(f"   HTTPError {e.code}   Location: {loc[:100]}")
    except Exception as exc:
        print(f"   ERROR: {exc}")

BASE_GID = "1183_46d101ed07800927c23e1828eec4ed4a"
TS = "20220714211141"
ORIG = f"https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/{BASE_GID}"

# Test 1: Standard Wayback URL (follows redirects)
fetch("standard (follow)", f"https://web.archive.org/web/{TS}/{ORIG}")

# Test 2: if_ modifier (original headers, no toolbar)
fetch("if_ modifier", f"https://web.archive.org/web/{TS}if_/{ORIG}")

# Test 3: id_ modifier (raw content, no modification)
fetch("id_ modifier", f"https://web.archive.org/web/{TS}id_/{ORIG}")

# Test 4: id_ without following redirect
fetch("id_ no-redir", f"https://web.archive.org/web/{TS}id_/{ORIG}", follow_redirect=False)

# Test with a 2020 gid that's known to be PDF
BASE_GID2 = "33315_25cecd701f64485618ddb18944982bd5"
TS2 = "20200924152218"
ORIG2 = f"https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/{BASE_GID2}"

fetch("gid33315 standard", f"https://web.archive.org/web/{TS2}/{ORIG2}")
fetch("gid33315 if_", f"https://web.archive.org/web/{TS2}if_/{ORIG2}")
fetch("gid33315 id_", f"https://web.archive.org/web/{TS2}id_/{ORIG2}")
