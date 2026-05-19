import urllib.request, urllib.parse, json, re

# Wayback Machine CDX API — find all captured versions of listagem.php?idMn=63
# and extract the idM values from each snapshot
cdx_url = (
    "https://web.archive.org/cdx/search/cdx"
    "?url=unicadata.com.br/listagem.php%3FidMn%3D63"
    "&output=json"
    "&fl=timestamp,statuscode"
    "&filter=statuscode:200"
    "&limit=500"
)
req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    print(f"CDX records: {len(data)} (including header)")
    if len(data) > 1:
        rows = data[1:]  # skip header
        print("First 5 timestamps:", [r[0] for r in rows[:5]])
        print("Last 5 timestamps:", [r[0] for r in rows[-5:]])
        # Sample a few snapshots spread across recent years
        import random
        sample = rows  # take all since we need idMs from each
        print(f"\nSampling {min(len(sample), 20)} snapshots for idM values...")
        
        # Filter to recent years (2021-2025)
        recent = [r for r in rows if r[0][:4] >= "2021"]
        print(f"Recent (2021+) snapshots: {len(recent)}")
        print("Recent timestamps:", [r[0] for r in recent[:10]])
        
        # Fetch a few archived snapshots to extract idM values
        seen_ids = set()
        for ts, code in recent[:10]:
            archive_url = f"https://web.archive.org/web/{ts}/https://unicadata.com.br/listagem.php?idMn=63"
            req2 = urllib.request.Request(archive_url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req2, timeout=20) as r2:
                    body = r2.read()
                ids = re.findall(rb"download_media\.php\?idM=(\d+)", body)
                pdfs = re.findall(rb"arquivos/pdfs/(\d{4}/\d{2})", body)
                print(f"  ts={ts}  idMs={[x.decode() for x in ids[:5]]}  pdf_months={[x.decode() for x in pdfs[:2]]}")
                seen_ids.update(x.decode() for x in ids)
            except Exception as e:
                print(f"  ts={ts}  ERROR: {e}")
        
        print(f"\nUnique idM values found: {sorted(seen_ids)}")
except Exception as e:
    print("CDX error:", e)
