"""Verify candidate XLS URLs return valid Excel bytes."""
from curl_cffi import requests as cr

CANDIDATES = [
    (2026, 1, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2026/site_previsao-de-safra-cafe-fev-2026.xls",
              "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2026/1o-levantamento-de-cafe-safra-2026"),
    (2023, 1, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2023/site_previsao-de-safra-cafe-abr-2023.xls",
              "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2023/1o-levantamento-de-cafe-safra-2023"),
    (2022, 4, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/4o-levantamento-de-cafe-safra-2022/site_previsao-de-safra-cafe-dez-2022.xls",
              "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/4o-levantamento-de-cafe-safra-2022/4o-levantamento-de-cafe-safra-2022"),
    (2022, 2, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/2o-levantamento-de-cafe-safra-2022/site_previsao-de-safra-cafe-ago-2022.xls",
              "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/2o-levantamento-de-cafe-safra-2022/2o-levantamento-de-cafe-safra-2022"),
    (2022, 1, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2022/site_previsao-de-safra-cafe-abr-2022.xls",
              "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2022/1o-levantamento-de-cafe-safra-2022"),
]

for safra_year, survey_no, xls_url, src in CANDIDATES:
    try:
        r = cr.get(xls_url, impersonate="chrome124", timeout=20, allow_redirects=True)
        magic = r.content[:4].hex() if len(r.content) >= 4 else ""
        ok = magic.startswith("d0cf11") or magic.startswith("504b03")
        status = "OK" if ok else "NOT XLS"
        print(f"  {survey_no}o/{safra_year}  HTTP {r.status_code}  {len(r.content):>7} bytes  magic={magic}  {status}")
    except Exception as e:
        print(f"  {survey_no}o/{safra_year}  ERROR: {e}")
