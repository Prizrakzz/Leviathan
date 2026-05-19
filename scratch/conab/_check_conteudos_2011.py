"""Check the 2011 CONAB conteudos.php?a=1253 page for coffee bulletin PDFs."""
import urllib.request, ssl, re

ctx = ssl.create_default_context()

ts  = "20111020230137"
url = "http://www.conab.gov.br/conteudos.php?a=1253&t="
wb  = f"https://web.archive.org/web/{ts}if_/{url}"

req = urllib.request.Request(wb, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, context=ctx, timeout=40) as r:
    html = r.read().decode("utf-8", errors="replace")

print(f"Fetched {len(html):,} chars")
title_m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
print("Title:", title_m.group(1).strip()[:100] if title_m else "n/a")

# Find OlalaCMS upload links (pre-Joomla style)
ola = re.findall(r"OlalaCMS/uploads/arquivos/[^\s\"'<>]+", html, re.I)
print(f"\n{len(ola)} OlalaCMS file links:")
for o in ola[:20]:
    print(" ", o)

# Find all hrefs that look like file downloads
hrefs = re.findall(r'href="([^"]{10,120})"', html, re.I)
file_hrefs = [h for h in hrefs if any(h.lower().endswith(ext) for ext in (".pdf", ".xls", ".xlsx", ".doc", ".zip"))]
print(f"\n{len(file_hrefs)} file href links:")
for h in file_hrefs[:20]:
    print(" ", h[-100:])

# Find all hrefs for context
print("\nFirst 30 hrefs:")
for h in hrefs[:30]:
    print(" ", h[-90:])
