import ssl, urllib.request, re, pathlib

ctx = ssl.create_default_context()
ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"


def get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": ua, "Referer": "https://bepi.mpob.gov.my/"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        return r.read().decode("utf-8", errors="replace")


BASE = "https://bepi.mpob.gov.my/stat/web_report1.php"

# Test the annual summary for 2026 (val=202684)
print("=== ANNUAL SUMMARY 2026 (val=202684) ===")
html = get(f"{BASE}?val=202684")
print("Length:", len(html))
tables = re.findall(r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE)
print("Tables:", len(tables))
text = re.sub(r"<[^>]+>", " ", html)
text = re.sub(r"\s+", " ", text).strip()
print("Text (first 1500):", text[:1500])
pathlib.Path("data/mpob/debug_annual2026.html").write_text(html, encoding="utf-8")

print()
# Check what other years respond with for val=202384 etc.
# Maybe the annual code varies
for year in [2025, 2024, 2023]:
    url = f"{BASE}?val={year}84"
    html2 = get(url)
    tables2 = re.findall(r"<table[^>]*>.*?</table>", html2, re.DOTALL | re.IGNORECASE)
    text2 = re.sub(r"<[^>]+>", " ", html2[:500])
    text2 = re.sub(r"\s+", " ", text2).strip()
    print(f"val={year}84: tables={len(tables2)}, text[:200]={text2[:200]}")

print()
# Check what the article page for 2025 annual summary (cat=333) looks like
# to get its iframe src
print("=== 2025 ANNUAL SUMMARY ARTICLE - finding iframe src ===")
# We know cat=333 is 2025 - but we don't know the artid. Let me try some nearby IDs
for artid in range(1200, 1215):
    try:
        url = f"https://bepi.mpob.gov.my/index.php?option=com_content&view=article&id={artid}"
        html3 = get(url)
        m = re.search(r'src="([^"]*stat[^"]*)"', html3, re.IGNORECASE)
        title_m = re.search(r"<title[^>]*>([^<]+)</title>", html3, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else ""
        if m:
            print(f"  art={artid}: title={title!r}  iframe_src={m.group(1)}")
        elif "summary" in title.lower() or "2025" in title:
            print(f"  art={artid}: title={title!r}  (no stat iframe)")
    except Exception as e:
        print(f"  art={artid}: error {e}")
