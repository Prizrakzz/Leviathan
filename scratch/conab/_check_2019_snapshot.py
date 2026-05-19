"""Check 2019 Wayback snapshot of CONAB listing to see depth of older entries."""
import urllib.request, ssl, re

ts  = "20190107142111"
base_url = "https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe"

ctx = ssl.create_default_context()
for suffix in ["", "?start=10", "?start=20", "?start=30", "?start=40"]:
    wb = f"https://web.archive.org/web/{ts}if_/{base_url}{suffix}"
    req = urllib.request.Request(wb, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=35) as r:
            html = r.read().decode("utf-8", errors="replace")
        gids = re.findall(r"item/download/(\d+_[a-f0-9]{32})", html, re.I)
        h2s  = [re.sub(r"<[^>]+>", "", h).strip()[:70]
                for h in re.findall(r"<h2\b[^>]*>(.*?)</h2>", html, re.DOTALL|re.I)
                if "Safra" in h or "safra" in h]
        label = suffix or "(main)"
        print(f"  {label:15}  {len(html):>8,} chars  {len(gids)} gids")
        for h in h2s:
            print(f"    {h}")
    except Exception as e:
        print(f"  {suffix or '(main)':15}  ERROR: {e}")
