"""Discover MPOB BEPI stat URLs via Joomla RSS feeds.

Approach:
- Phase 1: Scan category RSS feeds (200–370), matching on atom:link href
           (feed title is always "Economics and Industry Development Division", not category name)
- Phase 2: Annual summaries → hardcode val={YYYY}84 (confirmed pattern, no article fetch needed)
- Phase 3: Monthly releases → for each year category, get latest article ID from RSS (4-digit),
           probe ±20 article IDs, fetch each Joomla article to extract stat iframe src

Usage:
    python scratch/mpob/probe_bepi.py
"""
import ssl, urllib.request, re, json, pathlib, time

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
MONTHS_MAP = {
    "january":1,"february":2,"march":3,"april":4,
    "may":5,"june":6,"july":7,"august":8,
    "september":9,"october":10,"november":11,"december":12
}


def extract_artid_from_url(url_str):
    """Extract 4-digit article ID from a Joomla SEF URL.
    
    URL pattern: /index.php/section/{catid}-alias/{artid}-slug
    catid is 3-digit, artid is 4-digit — use \d{4} to skip catid.
    """
    m = re.search(r"/(\d{4})-[a-z]", url_str, re.IGNORECASE)
    return int(m.group(1)) if m else None


# -------------------------------------------------------------------
# Phase 1: Scan category RSS feeds — match on atom:link href
# Scan 200–370 to catch older years (2019–2022) too
# -------------------------------------------------------------------
print("Phase 1: Scanning category RSS feeds (200–370) ...")
monthly_cats = {}  # year -> {"catid", "latest_artid", "latest_url"}
summary_cats_rss = {}  # year -> catid (for reference only)

for catid in range(200, 371):
    url = f"{BASE}/index.php?format=feed&type=rss&option=com_content&view=category&id={catid}"
    status, xml = get(url)
    if status is None or status != 200 or len(xml) < 200:
        time.sleep(0.1)
        continue

    atomlink_m = re.search(r'atom:link[^>]+href="([^"]+)"', xml, re.IGNORECASE)
    atomlink = atomlink_m.group(1) if atomlink_m else ""

    monthly_m = re.search(r"monthly-release[/-](\d{4})", atomlink, re.IGNORECASE)
    summary_m = re.search(r"summary-2/\d+-(\d{4})\b", atomlink, re.IGNORECASE)

    if not (monthly_m or summary_m):
        time.sleep(0.1)
        continue

    year = int((monthly_m or summary_m).group(1))
    cat_type = "monthly_release" if monthly_m else "annual_summary"
    print(f"  cat={catid}: {cat_type} {year}")

    if cat_type == "annual_summary":
        summary_cats_rss[year] = catid
    else:
        # Extract latest article ID — 4-digit only (category IDs are 3-digit)
        latest_artid = None
        latest_url = None
        for item_link in re.findall(r"<link>([^<]+)</link>", xml):
            artid = extract_artid_from_url(item_link.strip())
            if artid and (latest_artid is None or artid > latest_artid):
                latest_artid = artid
                latest_url = item_link.strip()
        for guid in re.findall(r"<guid[^>]*>([^<]+)</guid>", xml):
            artid = extract_artid_from_url(guid.strip())
            if artid and (latest_artid is None or artid > latest_artid):
                latest_artid = artid
                latest_url = guid.strip()
        if latest_artid:
            print(f"    latest article: art={latest_artid}  {latest_url!r}")
        else:
            print(f"    (no articles in feed)")
        monthly_cats[year] = {
            "catid": catid,
            "latest_artid": latest_artid,
            "latest_url": latest_url,
        }

    time.sleep(0.2)

print(f"\n  monthly_release categories: {sorted(monthly_cats.keys())}")
print(f"  annual_summary categories (RSS): {sorted(summary_cats_rss.keys())}")

# -------------------------------------------------------------------
# Phase 2: Annual summaries — hardcoded val={YYYY}84 pattern
# Confirmed working for 2021–2026; extend to 2017–2026.
# Skip fetching; val codes are deterministic.
# -------------------------------------------------------------------
print("\nPhase 2: Building annual summary entries (val={YYYY}84 pattern) ...")
annual_results = []
for year in range(2017, 2027):
    val = f"{year}84"
    stat_url = f"{BASE}/stat/web_report1.php?val={val}"
    annual_results.append({
        "release_type": "annual_summary",
        "year": year,
        "month": None,
        "val": val,
        "stat_url": stat_url,
    })
    print(f"  annual/{year}  val={val}")

# -------------------------------------------------------------------
# Phase 3: Monthly releases — probe article ID range per year
# For each monthly category, probe (latest_artid - 20) to (latest_artid + 3).
# Fetch each Joomla article, extract stat iframe src.
# -------------------------------------------------------------------
print("\nPhase 3: Probing article ID ranges for monthly releases ...")
monthly_results = []

# For each year, determine probe range
for year in sorted(monthly_cats.keys()):
    cat_info = monthly_cats[year]
    latest_artid = cat_info["latest_artid"]
    if not latest_artid:
        print(f"  {year}: no latest artid from RSS, skipping")
        continue

    probe_start = max(900, latest_artid - 20)
    probe_end = latest_artid + 3
    print(f"  {year} (cat={cat_info['catid']}): probing art {probe_start}–{probe_end}  (latest={latest_artid})")

    for artid in range(probe_start, probe_end + 1):
        art_url = f"{BASE}/index.php?option=com_content&view=article&id={artid}"
        status, html = get(art_url)
        if status not in (200,):
            time.sleep(0.2)
            continue

        m = re.search(r'src="([^"]*stat/web_report1\.php\?[^"]+)"', html, re.IGNORECASE)
        if not m:
            time.sleep(0.2)
            continue

        iframe_src = re.sub(r"^/\.\./", "", m.group(1).strip())
        stat_url = f"{BASE}/{iframe_src}"

        val_m = re.search(r"val=(\d+)", stat_url)
        val1_m = re.search(r"val1=(\d+)", stat_url)
        val = val_m.group(1) if val_m else None
        val1 = val1_m.group(1) if val1_m else None

        if not val1:
            # Not a monthly release (could be another stat type)
            time.sleep(0.2)
            continue

        month = int(val1)
        print(f"    [found] art={artid}: monthly/{year}/{month:02d}  val={val}  stat_url={stat_url!r}")
        monthly_results.append({
            "release_type": "monthly_release",
            "year": year,
            "month": month,
            "val": val,
            "stat_url": stat_url,
        })
        time.sleep(0.3)


# -------------------------------------------------------------------
# Combine, deduplicate, sort, and save
# -------------------------------------------------------------------
all_results = annual_results + monthly_results
seen_keys = {}
for r in all_results:
    k = (r["release_type"], r["year"], r["month"])
    seen_keys[k] = r
all_results = sorted(
    seen_keys.values(),
    key=lambda r: (r["year"] or 0, 0 if r["release_type"] == "annual_summary" else 1, r["month"] or 0),
)

pathlib.Path("data/mpob").mkdir(parents=True, exist_ok=True)
pathlib.Path("data/mpob/mpob_val_map.json").write_text(
    json.dumps(list(all_results), indent=2), encoding="utf-8"
)

print(f"\nDone. Found {len(all_results)} total entries.")
annual = [r for r in all_results if r["release_type"] == "annual_summary"]
monthly = [r for r in all_results if r["release_type"] == "monthly_release"]
print(f"  annual_summary:   {len(annual)}")
print(f"  monthly_release:  {len(monthly)}")
for r in sorted(annual, key=lambda x: x["year"]):
    print(f"    annual/{r['year']}  val={r['val']}")
for y in sorted(set(r["year"] for r in monthly)):
    months_found = sorted(r["month"] for r in monthly if r["year"] == y)
    print(f"    monthly/{y}: {months_found}")
