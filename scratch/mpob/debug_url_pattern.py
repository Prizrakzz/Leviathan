import ssl, urllib.request, re

ctx = ssl.create_default_context()
ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"


def get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": ua, "Referer": "https://bepi.mpob.gov.my/"}
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


BASE = "https://bepi.mpob.gov.my/stat/web_report1.php"
MARKER = "CRUDE PALM OIL"

# Test annual summaries
print("=== ANNUAL SUMMARIES (val={YYYY}84) ===")
for year in range(2017, 2027):
    url = f"{BASE}?val={year}84"
    status, html = get(url)
    has_marker = MARKER in html if html else False
    snippet = ""
    if has_marker:
        tables = re.findall(r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE)
        if tables:
            text = re.sub(r"<[^>]+>", " ", tables[0])
            text = re.sub(r"\s+", " ", text).strip()
            snippet = text[:80]
    print(f"  {year}: status={status}  marker={has_marker}  {snippet[:80]}")

print()
# Test a few monthly releases
print("=== MONTHLY RELEASES (val={YYYY}75&val1={MM}) ===")
test_cases = [
    (2026, 4), (2026, 1), (2025, 12), (2025, 1),
    (2024, 12), (2024, 1), (2023, 1), (2020, 1), (2017, 1),
]
for year, month in test_cases:
    url = f"{BASE}?val={year}75&val1={month:02d}"
    status, html = get(url)
    has_marker = MARKER in html if html else False
    snippet = ""
    if has_marker:
        tables = re.findall(r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE)
        if tables:
            text = re.sub(r"<[^>]+>", " ", tables[0])
            text = re.sub(r"\s+", " ", text).strip()
            snippet = text[:80]
    print(f"  {year}-{month:02d}: status={status}  marker={has_marker}  {snippet[:80]}")
