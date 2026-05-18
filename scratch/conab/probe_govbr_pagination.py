"""Check if gov.br/conab Plone listing has older bulletins via b_start pagination."""
from curl_cffi import requests as creq
import re

LISTING = "https://www.gov.br/conab/pt-br/assuntos/noticias/safras/cafe"

for b_start in [0, 10, 20, 30, 40, 50]:
    url = f"{LISTING}?b_start={b_start}"
    r = creq.get(url, impersonate="chrome124", timeout=20)
    print(f"\n[{r.status_code}] b_start={b_start}  ({len(r.content)} bytes)")
    
    # Find article/PDF links
    # Plone article links
    articles = re.findall(
        r'href="(https://www\.gov\.br/conab/pt-br/assuntos/noticias/safras/cafe/[^"]+)"',
        r.text,
    )
    # PDF download links
    pdfs = re.findall(r'href="(https://www\.gov\.br/conab/[^"]+\.pdf[^"]*)"', r.text, re.I)
    pdfs += re.findall(r'href="(/conab/[^"]+boletim[^"]+)"', r.text, re.I)
    
    print(f"  Article links: {len(articles)}")
    for a in articles[:5]:
        print(f"    {a[-80:]}")
    print(f"  PDF links: {len(pdfs)}")
    for p in pdfs[:5]:
        print(f"    {p}")
