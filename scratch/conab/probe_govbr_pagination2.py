"""Check gov.br/conab listing pagination for historical bulletins."""
from curl_cffi import requests as creq
import re

BASE = "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe"

for b_start in [0, 10, 20, 30, 40, 50]:
    url = f"{BASE}?b_start:int={b_start}"
    r = creq.get(url, impersonate="chrome124", timeout=30)
    print(f"\n[{r.status_code}] b_start={b_start}  ({len(r.content)} bytes)")
    # Find all article links on the listing page
    links = re.findall(
        r'href="(https://www\.gov\.br/conab/pt-br/atuacao/[^"]+safra-de-cafe/[^"]+)"',
        r.text,
    )
    for lnk in sorted(set(links)):
        print(f"  {lnk[-90:]}")
