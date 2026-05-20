"""Build MPOB BEPI stat URL manifest.

Strategy:
- Annual summaries: hardcode val={YYYY}84 (confirmed pattern for 2017–2026)
- Monthly releases: fetch known category pages directly to list all articles,
  then fetch each article to extract its stat iframe src.

Known categories (from RSS probe):
  2023: cat=300  /monthly-release/300-monthly-release-2023
  2024: cat=311  /monthly-release/311-monthly-release-2024
  2025: cat=330  /monthly-release/330-monthly-release-2025
  2026: cat=341  /monthly-release/341-monthly-release-2026

Usage:
    python scratch/mpob/build_manifest.py
"""
import ssl, urllib.request, re, json, yaml, pathlib, time

ctx = ssl.create_default_context()
ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
BASE = "https://bepi.mpob.gov.my"


def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Referer": BASE})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Phase 1: Annual summaries — deterministic val={YYYY}84
# ---------------------------------------------------------------------------
print("Phase 1: Annual summaries (val={YYYY}84 pattern, years 2017-2026)")
annual_entries = []
for year in range(2017, 2027):
    val = f"{year}84"
    stat_url = f"{BASE}/stat/web_report1.php?val={val}"
    annual_entries.append({
        "release_type": "annual_summary",
        "year": year,
        "month": None,
        "val": val,
        "stat_url": stat_url,
    })
    print(f"  annual/{year}  val={val}")

# ---------------------------------------------------------------------------
# Phase 2: Monthly releases — fetch category pages to discover article links
# ---------------------------------------------------------------------------
MONTHLY_CATS = {
    2023: f"{BASE}/index.php/monthly-release/300-monthly-release-2023",
    2024: f"{BASE}/index.php/monthly-release/311-monthly-release-2024",
    2025: f"{BASE}/index.php/monthly-release/330-monthly-release-2025",
    2026: f"{BASE}/index.php/monthly-release/341-monthly-release-2026",
}

print("\nPhase 2: Monthly releases — discovering articles from category pages")
monthly_entries = []

for year, cat_url in sorted(MONTHLY_CATS.items()):
    print(f"\n  Year {year}: {cat_url}")
    status, html = get(cat_url)
    if status != 200:
        print(f"    ERROR: status={status}")
        continue

    # Extract article links — pattern: /monthly-release/{catid}-*/{artid}-{month-name}
    # Links appear as hrefs in the page HTML
    art_links = {}  # artid -> full_url
    for href in re.findall(r'href="(/index\.php/monthly-release/[^"]+/(\d{4})-[^"]+)"', html, re.IGNORECASE):
        full_href, artid_str = href
        artid = int(artid_str)
        art_links[artid] = BASE + full_href

    print(f"    Found {len(art_links)} article links: artids={sorted(art_links.keys())}")

    if not art_links:
        # Fallback: if only the latest month is published, try the RSS anchor art=1249 for 2026
        if year == 2026:
            art_links[1249] = f"{BASE}/index.php/monthly-release/341-monthly-release-2026/1249-april-2026"
            print(f"    Fallback: using known art=1249 for April 2026")
        else:
            print(f"    No articles found for {year}, skipping")
            continue

    # Fetch each article to extract stat iframe src
    for artid in sorted(art_links.keys()):
        art_url = art_links[artid]
        print(f"    Fetching art={artid}: {art_url!r}")
        status, html = get(art_url)
        if status != 200:
            print(f"      ERROR: status={status}")
            time.sleep(0.5)
            continue

        m = re.search(r'src="([^"]*stat/web_report1\.php\?[^"]+)"', html, re.IGNORECASE)
        if not m:
            print(f"      No stat iframe found")
            time.sleep(0.3)
            continue

        iframe_src = re.sub(r"^/\.\./", "", m.group(1).strip())
        stat_url = f"{BASE}/{iframe_src}"
        # Decode &amp; to & in URLs
        stat_url = stat_url.replace("&amp;", "&")

        val_m = re.search(r"val=(\d+)", stat_url)
        val1_m = re.search(r"val1=(\d+)", stat_url)
        val = val_m.group(1) if val_m else None
        val1 = val1_m.group(1) if val1_m else None

        if not val1:
            print(f"      No val1 in iframe src — not a monthly release")
            time.sleep(0.3)
            continue

        month = int(val1)
        print(f"      OK: monthly/{year}/{month:02d}  val={val}  stat_url={stat_url!r}")
        monthly_entries.append({
            "release_type": "monthly_release",
            "year": year,
            "month": month,
            "val": val,
            "stat_url": stat_url,
        })
        time.sleep(0.4)

# ---------------------------------------------------------------------------
# Combine and save
# ---------------------------------------------------------------------------
all_entries = annual_entries + monthly_entries
# Deduplicate by (release_type, year, month)
seen = {}
for e in all_entries:
    k = (e["release_type"], e["year"], e["month"])
    seen[k] = e
all_entries = sorted(
    seen.values(),
    key=lambda e: (e["year"] or 0, 0 if e["release_type"] == "annual_summary" else 1, e["month"] or 0),
)

# Save JSON
pathlib.Path("data/mpob").mkdir(parents=True, exist_ok=True)
json_path = pathlib.Path("data/mpob/mpob_val_map.json")
json_path.write_text(json.dumps(list(all_entries), indent=2), encoding="utf-8")
print(f"\nSaved {len(all_entries)} entries to {json_path}")

annual = [e for e in all_entries if e["release_type"] == "annual_summary"]
monthly = [e for e in all_entries if e["release_type"] == "monthly_release"]
print(f"  annual_summary:   {len(annual)}")
print(f"  monthly_release:  {len(monthly)}")
for e in sorted(annual, key=lambda x: x["year"]):
    print(f"    annual/{e['year']}  val={e['val']}")
for y in sorted(set(e["year"] for e in monthly)):
    months = sorted(e["month"] for e in monthly if e["year"] == y)
    print(f"    monthly/{y}: {months}")
