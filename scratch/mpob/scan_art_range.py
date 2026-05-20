"""Targeted scan of article IDs 1008-1248 to find monthly release stat iframes."""
import ssl, urllib.request, re, json, time, pathlib

ctx = ssl.create_default_context()
ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124"
BASE = "https://bepi.mpob.gov.my"


def get_art(artid):
    url = f"{BASE}/index.php?option=com_content&view=article&id={artid}"
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            html = r.read().decode("utf-8", errors="replace")
        m = re.search(r'src="([^"]*stat/web_report1\.php\?[^"]+)"', html, re.IGNORECASE)
        if not m:
            return None
        src = re.sub(r"^/\.\./", "", m.group(1)).replace("&amp;", "&")
        stat_url = f"{BASE}/{src}"
        val_m = re.search(r"val=(\d+)", stat_url)
        val1_m = re.search(r"val1=(\d+)", stat_url)
        val = val_m.group(1) if val_m else None
        val1 = val1_m.group(1) if val1_m else None
        return {"artid": artid, "val": val, "val1": val1, "stat_url": stat_url}
    except Exception:
        return None


import os
os.chdir(r"C:\Users\User\Desktop\Leviathan")
print("Scanning art=1008-1248 for stat iframes (monthly and annual) ...")
found = []
for artid in range(1008, 1249):
    r = get_art(artid)
    if r and r["val1"]:
        print(f"  art={artid}: val={r['val']} val1={r['val1']}  {r['stat_url']}")
        found.append(r)
    elif r:
        print(f"  art={artid}: no val1 (annual?)  val={r['val']}")
        found.append(r)
    time.sleep(0.25)

monthly = [x for x in found if x["val1"]]
print(f"\nDone. Total with stat iframe: {len(found)}, with val1 (monthly): {len(monthly)}")
pathlib.Path("data/mpob").mkdir(parents=True, exist_ok=True)
pathlib.Path("data/mpob/art_scan_1008_1248.json").write_text(json.dumps(found, indent=2))
print("Saved to data/mpob/art_scan_1008_1248.json")
