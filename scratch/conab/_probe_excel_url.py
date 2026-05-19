"""Quick probe to find Excel historical-series download link on CONAB gov.br."""
from curl_cffi import requests as cr
import re, sys

urls = [
    "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/historico-de-producao-de-cafe",
    "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras",
    "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe",
]
for url in urls:
    print("Probing:", url)
    try:
        r = cr.get(url, impersonate="chrome124", timeout=20, allow_redirects=True)
        print("  Status:", r.status_code, "  Final URL:", r.url)
        html = r.text
        xlsx_pat = re.compile(r'href=["\']([^"\']+\.xlsx?)["\']', re.IGNORECASE)
        dl_pat   = re.compile(r'href=["\']([^"\']+(?:/download|@@download)[^"\']*)["\']', re.IGNORECASE)
        links = xlsx_pat.findall(html)
        dl    = dl_pat.findall(html)
        print("  xlsx/xls:", links[:10])
        print("  downloads:", dl[:10])
        title = re.search(r"<title>([^<]+)</title>", html)
        if title:
            print("  title:", title.group(1)[:120])
    except Exception as e:
        print("  ERROR:", e)
    print()
