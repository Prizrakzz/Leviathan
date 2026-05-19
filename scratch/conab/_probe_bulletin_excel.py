"""Check individual CONAB bulletin pages for Excel historical-series attachments."""
from curl_cffi import requests as cr
import re

# Check a recent bulletin page for any Excel links
urls = [
    "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2026/1o-levantamento-de-cafe-safra-2026",
    "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/4o-levantamento-de-cafe-safra-2025/4o-levantamento-de-cafe-safra-2025",
    "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/3o-levantamento-de-cafe-safra-2025/3o-levantamento-de-cafe-safra-2025",
]
for url in urls:
    print("Probing:", url)
    try:
        r = cr.get(url, impersonate="chrome124", timeout=25, allow_redirects=True)
        print("  Status:", r.status_code, " Final URL:", r.url)
        html = r.text
        # All href links — look for xlsx, xls, or 'serie'
        xlsx_pat = re.compile(r'href="([^"]+\.xlsx?)"', re.IGNORECASE)
        dl_pat   = re.compile(r'href="([^"]+/@@download/[^"]+)"', re.IGNORECASE)
        serie_pat = re.compile(r'href="([^"]*serie[^"]*)"', re.IGNORECASE)
        hist_pat  = re.compile(r'href="([^"]*histori[^"]*)"', re.IGNORECASE)
        all_files = re.compile(r'href="([^"]+/@@download[^"]*|[^"]+\.(?:xlsx?|csv|ods))"', re.IGNORECASE)
        print("  xlsx/xls:", xlsx_pat.findall(html)[:10])
        print("  @@download:", dl_pat.findall(html)[:10])
        print("  serie links:", serie_pat.findall(html)[:10])
        print("  histori links:", hist_pat.findall(html)[:10])
        print("  all files:", all_files.findall(html)[:10])
    except Exception as e:
        print("  ERROR:", e)
    print()
