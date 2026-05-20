"""Use Joomla RSS feeds to discover MPOB BEPI monthly release and annual summary articles.

Strategy
--------
1. Scan Joomla category IDs 270–360 using the RSS feed endpoint:
   /index.php?format=feed&type=rss&option=com_content&view=category&id={catid}
   This is fast (1 request per category) and returns article IDs in the feed.

2. For RSS feeds containing "monthly-release" or "summary" in the feed title:
   - Parse article IDs and URLs from <link> elements
   - Fetch each article's stat URL (iframe src) to get the val parameters

3. Save results to data/mpob/mpob_val_map.json

Sleep: 0.3s between requests (polite but fast for a small site without WAF).
"""
import ssl, urllib.request, re, json, pathlib, time
from xml.etree import ElementTree as ET

ctx = ssl.create_default_context()
ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"


def get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


BASE = "https://bepi.mpob.gov.my"
MONTHS = {
    "january":1,"february":2,"march":3,"april":4,
    "may":5,"june":6,"july":7,"august":8,
    "september":9,"october":10,"november":11,"december":12
}

# -------------------------------------------------------------------
# Phase 1: Scan category RSS feeds
# -------------------------------------------------------------------
print("Phase 1: Scanning category RSS feeds (270–360) ...")
relevant_categories = {}  # catid -> {"type": "monthly_release"|"summary", "year": int, "art_ids": [...]}

for catid in range(270, 361):
    url = f"{BASE}/index.php?format=feed&type=rss&option=com_content&view=category&id={catid}"
    status, xml = get(url)
    if status is None or status != 200:
        time.sleep(0.15)
        continue

    # Check feed title for monthly-release or summary keywords
    title_m = re.search(r"<title>([^<]+)</title>", xml)
    feed_title = title_m.group(1).strip() if title_m else ""

    is_monthly = bool(re.search(r"monthly[\s\-]release[\s\-](20\d{2})", feed_title, re.IGNORECASE))
    is_summary = bool(re.search(r"summary.*?of.*?the.*?(20\d{2})|^\s*(20\d{2})\s*$", feed_title, re.IGNORECASE))

    # Also check if category alias is in the URL (Joomla may redirect RSS to SEF)
    # Try to extract year from title
    year_m = re.search(r"(20\d{2})", feed_title)
    year = int(year_m.group(1)) if year_m else None

    if not (is_monthly or is_summary) or year is None:
        time.sleep(0.15)
        continue

    cat_type = "monthly_release" if is_monthly else "annual_summary"
    print(f"  cat={catid}: {cat_type} {year}  title={feed_title!r}")

    # Extract article IDs and URLs from feed <link> elements
    # Format: <link>https://bepi.mpob.gov.my/index.php/section/{catid}-alias/{artid}-slug</link>
    art_links = re.findall(r"<link>([^<]+bepi\.mpob\.gov\.my[^<]+)</link>", xml)
    # Also try <guid> elements
    art_guids = re.findall(r"<guid[^>]*>([^<]+)</guid>", xml)
    all_links = set(art_links + art_guids)

    art_ids = []
    for link in all_links:
        # Extract artid from SEF URL or from query param
        m = re.search(r"/(\d+)-[a-z]", link, re.IGNORECASE)
        if m:
            artid = int(m.group(1))
            if artid > 200:  # filter out nav/menu IDs
                art_ids.append((artid, link.strip()))

    relevant_categories[catid] = {
        "type": cat_type,
        "year": year,
        "feed_title": feed_title,
        "articles": sorted(set(art_ids)),
    }
    time.sleep(0.3)

print(f"  Found {len(relevant_categories)} relevant categories.")

# -------------------------------------------------------------------
# Phase 2: For each article, fetch its stat URL
# -------------------------------------------------------------------
print("\nPhase 2: Fetching article stat URLs ...")
results = []
seen_art_ids = set()

# Always include the known anchors
known_anchors = [
    (1249, "https://bepi.mpob.gov.my/index.php/monthly-release/341-monthly-release-2026/1249-april-2026"),
    (1260, "https://bepi.mpob.gov.my/index.php/summary-2/344-2026/1260-summary-of-the-malaysian-palm-oil-industry-2026"),
]

all_articles = []
for catid, cat_info in relevant_categories.items():
    for artid, link in cat_info["articles"]:
        all_articles.append((artid, link))

# Add known anchors if not already in list
for artid, link in known_anchors:
    if artid not in {a for a, _ in all_articles}:
        all_articles.append((artid, link))

all_articles = sorted(set(all_articles), key=lambda x: x[0])
print(f"  Total articles to fetch: {len(all_articles)}")

for artid, art_url in all_articles:
    if artid in seen_art_ids:
        continue
    seen_art_ids.add(artid)

    art_full_url = art_url if art_url.startswith("http") else BASE + art_url
    status, html = get(art_full_url)
    if status is None or status in (403, 404):
        print(f"  art={artid}: skip (status={status})")
        time.sleep(0.3)
        continue

    # Find iframe stat src
    m = re.search(r'src="([^"]*stat/web_report1\.php\?[^"]+)"', html, re.IGNORECASE)
    if not m:
        print(f"  art={artid}: no stat iframe")
        time.sleep(0.3)
        continue

    iframe_src = m.group(1).strip()
    iframe_src_clean = re.sub(r'^/\.\./', '', iframe_src)
    stat_url = f"{BASE}/{iframe_src_clean}" if not iframe_src_clean.startswith("http") else iframe_src_clean

    val_m = re.search(r'val=(\d+)', stat_url)
    val1_m = re.search(r'val1=(\d+)', stat_url)
    val = val_m.group(1) if val_m else None
    val1 = val1_m.group(1) if val1_m else None

    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    title = title_m.group(1).strip() if title_m else ""

    release_type = None
    year = None
    month = None

    if re.search(r"Summary Of The Malaysian Palm Oil Industry", title, re.IGNORECASE):
        release_type = "annual_summary"
        year_m = re.search(r"(20\d{2})", title)
        year = int(year_m.group(1)) if year_m else None
    elif val1:
        release_type = "monthly_release"
        month = int(val1)
        title_lower = title.lower()
        year_m2 = re.search(r"(20\d{2})", title)
        year = int(year_m2.group(1)) if year_m2 else None
    else:
        print(f"  art={artid}: other (title={title!r}  val={val})")
        time.sleep(0.3)
        continue

    if release_type and year:
        record = {
            "art_id": artid,
            "release_type": release_type,
            "year": year,
            "month": month,
            "val": val,
            "val1": val1,
            "stat_url": stat_url,
            "art_url": art_full_url,
            "title": title,
        }
        label = f"annual/{year}" if release_type == "annual_summary" else f"monthly/{year}/{month:02d}"
        print(f"  [found] art={artid}: {label}  val={val}  title={title!r}")
        results.append(record)

    time.sleep(0.3)

# Sort results
results.sort(key=lambda r: (r["year"], 0 if r["release_type"] == "annual_summary" else 1, r["month"] or 0))

pathlib.Path("data/mpob").mkdir(parents=True, exist_ok=True)
pathlib.Path("data/mpob/mpob_val_map.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

print(f"\nDone. Found {len(results)} total entries.")
annual = [r for r in results if r["release_type"] == "annual_summary"]
monthly = [r for r in results if r["release_type"] == "monthly_release"]
print(f"  annual_summary:   {len(annual)}")
print(f"  monthly_release:  {len(monthly)}")
for r in annual:
    print(f"    annual/{r['year']}  val={r['val']}")
for y in sorted(set(r['year'] for r in monthly)):
    months_found = sorted(r['month'] for r in monthly if r['year'] == y)
    print(f"    monthly/{y}: months={months_found}")
