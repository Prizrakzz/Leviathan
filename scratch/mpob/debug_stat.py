import ssl, urllib.request, re, pathlib

ctx = ssl.create_default_context()
ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"


def get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": ua, "Referer": "https://bepi.mpob.gov.my/"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


# 1. Fetch the stat endpoint for monthly April 2026
print("=== STAT ENDPOINT (monthly April 2026) ===")
try:
    stat_url = "https://bepi.mpob.gov.my/stat/web_report1.php?val=202675&val1=04"
    html = get(stat_url)
    print("Length:", len(html))
    tables = re.findall(r"<table[^>]*>.*?</table>", html, re.DOTALL | re.IGNORECASE)
    print("Tables found:", len(tables))
    if tables:
        text = re.sub(r"<[^>]+>", " ", tables[0])
        text = re.sub(r"\s+", " ", text).strip()
        print("First table text:", text[:1000])
    else:
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        print("Page text:", text[:2000])
    pathlib.Path("data/mpob").mkdir(parents=True, exist_ok=True)
    pathlib.Path("data/mpob/debug_stat1249.html").write_text(html, encoding="utf-8")
    print("Saved debug_stat1249.html")
except Exception as e:
    print("Error fetching stat endpoint:", e)

# 2. Find iframe src in annual summary art=1260
print()
print("=== ANNUAL SUMMARY ART=1260 IFRAME SRC ===")
try:
    art_url = "https://bepi.mpob.gov.my/index.php?option=com_content&view=article&id=1260"
    html2 = get(art_url)
    # Find iframe src containing stat
    m = re.search(r'src="([^"]*stat[^"]*)"', html2, re.IGNORECASE)
    if m:
        print("iframe src:", m.group(1))
    else:
        m2 = re.search(r"<iframe[^>]+>", html2, re.IGNORECASE)
        if m2:
            print("iframe tag:", m2.group(0)[:300])
        else:
            print("No iframe found")
    pathlib.Path("data/mpob/debug_art1260.html").write_text(html2, encoding="utf-8")
    print("Saved debug_art1260.html")
except Exception as e:
    print("Error fetching art1260:", e)
