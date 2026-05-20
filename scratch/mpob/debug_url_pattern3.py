import ssl, urllib.request, re

ctx = ssl.create_default_context()
ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"


def get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": ua, "Referer": "https://bepi.mpob.gov.my/"}
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"


BASE = "https://bepi.mpob.gov.my/stat/web_report1.php"

# Check all 2026 months with val=202675
print("=== 2026 MONTHLY (val=202675&val1={MM}) ===")
for month in range(1, 13):
    url = f"{BASE}?val=202675&val1={month:02d}"
    html = get(url)
    if html.startswith("ERROR"):
        print(f"  2026-{month:02d}: {html}")
        continue
    tables = re.findall(r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html[:800])
    text = re.sub(r"\s+", " ", text).strip()
    has_cpo = "CRUDE PALM OIL" in html
    print(f"  2026-{month:02d}: tables={len(tables)}  cpo={has_cpo}  text[:150]={text[:150]}")

print()
# Check all 2025 months with val=202575
print("=== 2025 MONTHLY (val=202575&val1={MM}) ===")
for month in range(1, 13):
    url = f"{BASE}?val=202575&val1={month:02d}"
    html = get(url)
    if html.startswith("ERROR"):
        print(f"  2025-{month:02d}: {html}")
        continue
    tables = re.findall(r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html[:500])
    text = re.sub(r"\s+", " ", text).strip()
    has_cpo = "CRUDE PALM OIL" in html
    print(f"  2025-{month:02d}: tables={len(tables)}  cpo={has_cpo}  text[:120]={text[:120]}")
