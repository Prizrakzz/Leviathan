"""Probe specific CONAB survey main pages for XLS links (targeted retry)."""
import json, re, sys
from pathlib import Path
from curl_cffi import requests as cr

_ROOT = Path(__file__).parent.parent.parent
_OUT  = _ROOT / "data" / "conab" / "conab_bulletin_excels.json"

_XLS_RE = re.compile(r'href="(https://www\.gov\.br[^"]+\.xlsx?)"', re.IGNORECASE)

# Known main survey pages likely to have XLS files
TARGET_PAGES = [
    (2026, 1, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2026/1o-levantamento-de-cafe-safra-2026"),
    (2025, 4, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/4o-levantamento-de-cafe-safra-2025/4o-levantamento-de-cafe-safra-2025"),
    (2025, 3, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/3o-levantamento-de-cafe-safra-2025/3o-levantamento-de-cafe-safra-2025"),
    (2025, 2, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/2o-levantamento-de-cafe-safra-2025/2o-levantamento-de-cafe-safra-2025"),
    (2025, 1, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2025/1o-levantamento-de-cafe-safra-2025"),
    (2024, 4, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/4o-levantamento-de-cafe-safra-2024/4o-levantamento-de-cafe-safra-2024"),
    (2024, 3, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/3o-levantamento-de-cafe-safra-2024/3o-levantamento-de-cafe-safra-2024"),
    (2024, 2, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/2o-levantamento-de-cafe-safra-2024/2o-levantamento-de-cafe-safra-2024"),
    (2024, 1, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2024/1o-levantamento-de-cafe-safra-2024"),
    (2023, 4, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/4o-levantamento-de-cafe-safra-2023/4o-levantamento-de-cafe-safra-2023"),
    (2023, 3, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/3o-levantamento-de-cafe-safra-2023/3o-levantamento-de-cafe-safra-2023"),
    (2023, 2, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/2o-levantamento-de-cafe-safra-2023/2o-levantamento-de-cafe-safra-2023"),
    (2023, 1, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2023/1o-levantamento-de-cafe-safra-2023"),
    (2022, 4, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/4o-levantamento-de-cafe-safra-2022/4o-levantamento-de-cafe-safra-2022"),
    (2022, 3, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/3o-levantamento-de-cafe-safra-2022/3o-levantamento-de-cafe-safra-2022"),
    (2022, 2, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/2o-levantamento-de-cafe-safra-2022/2o-levantamento-de-cafe-safra-2022"),
    (2022, 1, "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe/1o-levantamento-de-cafe-safra-2022/1o-levantamento-de-cafe-safra-2022"),
]

results = []
for safra_year, survey_no, url in TARGET_PAGES:
    print(f"  {survey_no}o Safra {safra_year} ...", end=" ", flush=True)
    try:
        r = cr.get(url, impersonate="chrome124", timeout=30, allow_redirects=True)
        r.raise_for_status()
        links = _XLS_RE.findall(r.text)
        if links:
            for xls_url in links:
                print(f"XLS: {xls_url.rsplit('/', 1)[-1]}")
                results.append({
                    "safra_year": safra_year,
                    "survey_no": survey_no,
                    "xls_url": xls_url,
                    "source_page": url,
                })
        else:
            print("no XLS")
    except Exception as e:
        print(f"ERROR: {e}")

_OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nSaved {len(results)} entries -> {_OUT}")
