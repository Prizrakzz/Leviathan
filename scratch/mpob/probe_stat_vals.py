"""Find all monthly release and annual summary BEPI articles by scanning article IDs.

For each article:
  1. Fetch the Joomla article page
  2. Find the iframe src with /stat/web_report1.php
  3. Extract val and val1 parameters
  4. Classify: monthly_release (has val1) or annual_summary (no val1, title matches)
  5. Verify by fetching the actual stat endpoint and checking for markers

Outputs data/mpob/mpob_val_map.json — maps each year/month to its stat URL.
"""
import ssl, urllib.request, re, json, pathlib, time

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


BASE_ART = "https://bepi.mpob.gov.my/index.php?option=com_content&view=article&id="
BASE_STAT = "https://bepi.mpob.gov.my/stat/web_report1.php"

MONTHS = {
    "january":1,"february":2,"march":3,"april":4,
    "may":5,"june":6,"july":7,"august":8,
    "september":9,"october":10,"november":11,"december":12
}

results = []

print(f"Scanning article IDs 1050–1270 ...")
for artid in range(1050, 1271):
    status, html = get(BASE_ART + str(artid))
    if status is None or status == 403 or status == 404:
        time.sleep(0.3)
        continue

    # Find iframe src with stat endpoint
    m = re.search(r'src="([^"]*stat/web_report1\.php\?[^"]+)"', html, re.IGNORECASE)
    if not m:
        time.sleep(0.3)
        continue

    iframe_src = m.group(1).strip()
    # Normalize: remove /../ prefix
    iframe_src_clean = re.sub(r'^/\.\./', '', iframe_src)
    stat_url = f"https://bepi.mpob.gov.my/{iframe_src_clean}"

    # Parse val and val1
    val_m = re.search(r'val=(\d+)', stat_url)
    val1_m = re.search(r'val1=(\d+)', stat_url)
    val = val_m.group(1) if val_m else None
    val1 = val1_m.group(1) if val1_m else None

    # Get page title
    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    title = title_m.group(1).strip() if title_m else ""

    # Classify
    release_type = None
    year = None
    month = None

    if re.search(r"Summary Of The Malaysian Palm Oil Industry", title, re.IGNORECASE):
        release_type = "annual_summary"
        year_m = re.search(r"(20\d{2})", title)
        year = int(year_m.group(1)) if year_m else None
    elif val1:
        # Has val1 → monthly release
        release_type = "monthly_release"
        month = int(val1)
        # Extract year from title
        title_lower = title.lower()
        for mname, mnum in MONTHS.items():
            if mname in title_lower:
                year_m2 = re.search(r"(20\d{2})", title)
                year = int(year_m2.group(1)) if year_m2 else None
                break
        if year is None:
            # Try from val prefix
            year_m3 = re.search(r"^(20\d{2})", val or "")
            year = int(year_m3.group(1)) if year_m3 else None
    else:
        # Other stat page (FFB mill, capacity, etc.) - skip
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
            "title": title,
        }
        label = f"annual/{year}" if release_type == "annual_summary" else f"monthly/{year}/{month:02d}"
        print(f"  [found] art={artid}: {label}  val={val}  title={title!r}")
        results.append(record)

    time.sleep(0.3)

# Sort and save
results.sort(key=lambda r: (r["year"], 0 if r["release_type"] == "annual_summary" else 1, r["month"] or 0))

pathlib.Path("data/mpob").mkdir(parents=True, exist_ok=True)
pathlib.Path("data/mpob/mpob_val_map.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

print(f"\nDone. Found {len(results)} entries.")
annual = [r for r in results if r["release_type"] == "annual_summary"]
monthly = [r for r in results if r["release_type"] == "monthly_release"]
print(f"  annual_summary:  {len(annual)}")
print(f"  monthly_release: {len(monthly)}")
if monthly:
    by_year = {}
    for r in monthly:
        by_year.setdefault(r["year"], []).append(r["month"])
    for y, months in sorted(by_year.items()):
        print(f"    {y}: months={sorted(months)}")
