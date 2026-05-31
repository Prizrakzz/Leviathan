"""Probe UNICA website to find tipoHistorico value for fortnightly data."""
import time
import urllib.parse
import urllib.request

BASE = "https://unicadata.com.br/historico-de-producao-e-moagem.php"


def probe(tipo: int, idt: str = "2495", safra: str = "2020/2021") -> None:
    params = {
        "idMn": "32",
        "tipoHistorico": str(tipo),
        "idioma": "2",
        "idTabela": idt,
        "safra": safra,
        "acao": "visualizar",
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        row_c = html.lower().count("<tr")
        has_quinz = "quinzena" in html.lower()
        print(f"  tipo={tipo} idTabela={idt}: len={len(html)}, rows={row_c}, quinzena={has_quinz}")
    except Exception as e:
        print(f"  tipo={tipo} idTabela={idt}: ERROR {e}")


# Check tipoHistorico=4 still works
probe(4, "2495")
time.sleep(1)

# Try tipoHistorico=3 with various idTabela values
for idt in ["2495", "2496", "2494", "2497"]:
    probe(3, idt)
    time.sleep(1)

# Try tipoHistorico=1 and 2 with idTabela=2495
probe(1, "2495")
time.sleep(1)
probe(2, "2495")
