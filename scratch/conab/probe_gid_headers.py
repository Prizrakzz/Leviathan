"""Check Content-Disposition headers from Wayback if_ responses to identify PDFs."""
import ssl
import urllib.request

UA = "Mozilla/5.0"
CTX = ssl.create_default_context()
BASE = "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download"

GIDS = [
    ("42143_a597248239f850c6753b2f1d1e4e826b", "20220624154229", "?"),
    ("40911_0eac1d762da9a95acc3d8d4bd36d7359", "20220624154241", "?"),
    ("40314_5ca4f5eaec7d5fb8e90ec9645427e205", "20220624154256", "?"),
    ("39155_6833f8ba418f3fab83c6d910ce7ecfba", "20220624154307", "?"),
    ("37221_c140375aec407df98f74995349fc365f", "20220624154351", "?"),
    ("34932_6bdced374e56fe17fe8f1d7f88be63df", "20220624154337", "4º safra 2020 (known)"),
    ("35523_e51cdbd4fe3af97e44226a6a07c3cb9c", "20220624154421", "1º safra 2021 (known)"),
    ("45165_52f8285113b08b6e60b1a1ec72e9ca2a", "20240414090123", "4º safra 2020 re-upload (known)"),
    ("45166_c217a37038a20b21a70a8a7049de7cda", "20250317012213", "1º safra 2021 re-upload (known)"),
]


class HeadOnlyHandler(urllib.request.BaseHandler):
    def http_response(self, request, response):
        return response
    https_response = http_response


for gid_hash, ts, label in GIDS:
    url = f"https://web.archive.org/web/{ts}if_/{BASE}/{gid_hash}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    print(f"\ngid {gid_hash[:12]}  ({label})")
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
            cd = r.info().get("Content-Disposition", "")
            ct = r.info().get("Content-Type", "")
            cr = r.info().get("Content-Range", "")
            print(f"  CT: {ct}")
            print(f"  CD: {cd}")
            print(f"  CR: {cr}")
    except Exception as e:
        print(f"  ERROR: {e}")
