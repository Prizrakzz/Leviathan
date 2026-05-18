"""Identify mystery gids by reading more PDF bytes to find metadata."""
import re
import ssl
import urllib.request

UA = "Mozilla/5.0"
CTX = ssl.create_default_context()
DOWNLOAD_BASE = "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download"

GIDS = [
    ("42143_a597248239f850c6753b2f1d1e4e826b", "20220624154229"),
    ("40911_0eac1d762da9a95acc3d8d4bd36d7359", "20220624154241"),
    ("40314_5ca4f5eaec7d5fb8e90ec9645427e205", "20220624154256"),
    ("39155_6833f8ba418f3fab83c6d910ce7ecfba", "20220624154307"),
    ("37221_c140375aec407df98f74995349fc365f", "20220624154351"),
    # Also check known Dec 2022 gids that ARE in CDX (to confirm mapping)
    ("45166_c217a37038a20b21a70a8a7049de7cda", "20250317012213"),  # 1º safra 2021
    ("45165_52f8285113b08b6e60b1a1ec72e9ca2a", "20240414090123"),  # 4º safra 2020
]


def find_title(data: bytes) -> str:
    text = data.decode("latin-1", errors="replace")
    patterns = [
        r"\d+[ºo°]\.?\s*[Ll]evantamento",
        r"Levantamento\s+\d+",
        r"Safra\s+\d{4}[/\s\-]\d{2,4}",
        r"caf[eé]\s*[\d/]+",
        r"\bsafra\b.*?\d{4}",
        r"\blevantamento\b",
        r"boletim\s+da\s+safra",
    ]
    hits = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx = text[max(0, m.start()-20):m.end()+40].strip()
            ctx = re.sub(r'\s+', ' ', ctx)
            if len(ctx) > 5:
                hits.append(repr(ctx[:80]))
        if hits:
            return " | ".join(hits[:2])
    return "(no pattern found)"


for gid_hash, ts in GIDS:
    url = f"https://web.archive.org/web/{ts}if_/{DOWNLOAD_BASE}/{gid_hash}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-65535"})
    print(f"\ngid {gid_hash[:12]} (ts={ts[:8]})")
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            data = r.read(65536)
            ct = r.info().get("Content-Type", "?")
            cl = r.info().get("Content-Range", r.info().get("Content-Length", "?"))
            if data[:4] != b"%PDF":
                print(f"  NOT PDF: {ct} | {data[:60]}")
                continue
            title = find_title(data)
            print(f"  PDF  {len(data)} bytes  range={cl}")
            print(f"  → {title}")
    except Exception as e:
        print(f"  ERROR: {e}")
