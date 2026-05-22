"""Probe thedocs.worldbank.org URL formats to find direct PDF download paths."""
import requests
from bs4 import BeautifulSoup

s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0 Chrome/124"

tests = [
    # Direct PDF from landing page link
    ("2008-01 direct-pdf", "https://thedocs.worldbank.org/en/doc/79521462997099628-0050022016/original/CMO2008January.pdf"),
    ("2008-09 direct-pdf", "https://thedocs.worldbank.org/en/doc/147451462997102813-0050022016/original/CMO2008September.pdf"),
    # 2012-01 correct filename (GEP analysis)
    ("2012-01 gep-pdf",    "https://thedocs.worldbank.org/en/doc/167541462308752776-0050022016/original/CMO2012JanuaryGEPanalysis.pdf"),
    # 1994-11 direct PDF via /original/
    ("1994-11 direct-pdf", "https://thedocs.worldbank.org/en/doc/475131464184948121-0050022016/original/CMO1994November.pdf"),
    # 2013-07 direct PDF (confirmed working)
    ("2013-07 PDF",        "https://thedocs.worldbank.org/en/doc/632561461935834019-0050022016/original/CMO2013July.pdf"),
]

for label, url in tests:
    print(f"\n--- {label}")
    print(f"    {url}")
    try:
        r = s.get(url, timeout=20, allow_redirects=True)
        ct = r.headers.get("content-type", "?")
        print(f"  status={r.status_code}  ct={ct[:60]}  final_url={r.url[-80:]}")
        if "pdf" in ct.lower():
            print(f"  => DIRECT PDF ({len(r.content)} bytes)")
        elif "html" in ct.lower():
            soup = BeautifulSoup(r.text, "html.parser")
            pdf_links = [
                (a.get_text(strip=True)[:50], a["href"][-80:])
                for a in soup.find_all("a", href=True)
                if ".pdf" in a["href"].lower()
            ]
            dl_links = [
                (a.get_text(strip=True)[:50], a["href"][-80:])
                for a in soup.find_all("a", href=True)
                if "download" in a["href"].lower() or "download" in a.get("class", [])
            ]
            print(f"  PDF links found: {pdf_links[:4]}")
            print(f"  Download links:  {dl_links[:3]}")
            # Also check for JSON data embedded in page
            scripts = [s.string for s in soup.find_all("script") if s.string and "pdf" in s.string.lower()]
            if scripts:
                import re
                pdf_refs = re.findall(r'https?://[^\s"\']+\.pdf', scripts[0])
                print(f"  PDF refs in JS: {pdf_refs[:3]}")
        else:
            print(f"  (other content type)")
    except Exception as e:
        print(f"  ERROR: {e}")
