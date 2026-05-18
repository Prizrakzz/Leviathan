"""
CONAB coffee survey PDF URL collector.
Two patterns on gov.br/conab:
  A) Direct .pdf link on the survey page (most surveys)
  B) Sub-page URL that IS the PDF (no .pdf extension — Plone file object)
     e.g. .../4o-levantamento-de-cafe-safra-2025/boletim-cafe-dezembro-2025
     Verified: Range request returns Content-Type: application/pdf
"""
from curl_cffi import requests as cr
import re, time, json, urllib.request, ssl

BASE = 'https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/safra-de-cafe'
session = cr.Session()
SSL_CTX = ssl.create_default_context()

def get_page(url, timeout=25):
    return session.get(url, impersonate='chrome124', timeout=timeout, allow_redirects=True)

def find_pdfs_in_text(text):
    return sorted(set(re.findall(r'https?://[^\s"<>]+?\.pdf', text)))

def get_gov_hrefs(text):
    return [h for h in re.findall(r'href="([^"]+)"', text)
            if h.startswith('https://www.gov.br/conab/')]

def is_pdf_url(url, timeout=12):
    """Return True if the URL serves a PDF, using a tiny Range request."""
    try:
        req = urllib.request.Request(
            url, headers={'Range': 'bytes=0-3', 'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as resp:
            ct = resp.getheader('content-type', '')
            if 'pdf' in ct.lower():
                return True
            data = resp.read(4)
            return data == b'%PDF'
    except Exception as e:
        print(f'    is_pdf_url err {url[-40:]}: {e}')
        return False

# ── 1. Collect levantamento page URLs (gov.br only, canonical slug/slug) ──────
lev_pages = set()
for archive in [BASE, f'{BASE}/safra-de-cafe-1']:
    r = get_page(archive)
    for h in get_gov_hrefs(r.text):
        if re.search(r'/\do-levantamento-de-cafe-safra-\d{4}/', h):
            slug = h.rstrip('/').split('/')[-1]
            parent = h.rstrip('/').split('/')[-2]
            if slug == parent:
                lev_pages.add(h)
    print(f'After {archive[-40:]}: {len(lev_pages)} pages')

print(f'\nTotal levantamento pages: {len(lev_pages)}')

# ── 2. For each survey page, find the PDF ─────────────────────────────────────
results = []
for page_url in sorted(lev_pages):
    lev_folder = '/'.join(page_url.rstrip('/').split('/')[:-1])  # drop last slug
    r = get_page(page_url)
    # Pattern A: direct .pdf link
    pdfs = find_pdfs_in_text(r.text)
    if pdfs:
        results.append({'page': page_url, 'pdf': pdfs[0]})
        print(f'  PDF (direct): {pdfs[0][-65:]}')
    else:
        # Pattern B: child links within the levantamento folder
        # Exclude: XLS/XLSX data files, the canonical URL itself, and nav links
        gov_hrefs = get_gov_hrefs(r.text)
        candidates = [
            h for h in gov_hrefs
            if h.startswith(lev_folder + '/')          # inside the survey folder
            and not h.rstrip('/').endswith(page_url.rstrip('/').split('/')[-1])  # not the canonical link
            and not any(h.lower().endswith(ext) for ext in ('.xls', '.xlsx', '.csv', '.zip'))
            and not h.endswith('/')
        ]
        candidates = list(dict.fromkeys(candidates))  # deduplicate, preserve order
        pdf_found = None
        for cand in candidates:
            if cand.lower().endswith('.pdf'):
                pdf_found = cand
                print(f'  PDF (child .pdf): {cand[-65:]}')
                break
            # Check if this URL IS a PDF (no extension)
            print(f'    checking candidate: {cand[-60:]}')
            if is_pdf_url(cand):
                pdf_found = cand
                print(f'  PDF (no-ext): {cand[-65:]}')
                break
        if pdf_found:
            results.append({'page': page_url, 'pdf': pdf_found})
        else:
            print(f'  NO PDF: {page_url[-60:]}')
            results.append({'page': page_url, 'pdf': None})
    time.sleep(0.4)

print(f'\nRecent surveys: {len(results)} found, {sum(1 for r in results if r["pdf"])} with PDF\n')
for item in results:
    status = 'OK' if item['pdf'] else 'MISSING'
    print(f'  [{status}] {item["page"][-55:]}')
    if item['pdf']:
        print(f'         → {item["pdf"][-55:]}')

with open('conab_pdf_urls.json', 'w') as f:
    json.dump(results, f, indent=2)
print('\nSaved conab_pdf_urls.json')

# ── 3. Wayback CDX for pre-2023 CONAB PDFs ───────────────────────────────────
print('\n=== Wayback CDX (pre-2023 history) ===')
import requests as req
for label, cdx_url in [
    ('item/download', 'http://web.archive.org/cdx/search/cdx?url=www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download*&output=json&fl=timestamp,original&collapse=original&limit=300&matchType=prefix'),
    ('OlalaCMS cafe', 'http://web.archive.org/cdx/search/cdx?url=www.conab.gov.br/OlalaCMS*cafe*.pdf&output=json&fl=timestamp,original&collapse=original&limit=300&matchType=prefix&filter=mimetype:application/pdf'),
    ('images cafe', 'http://web.archive.org/cdx/search/cdx?url=www.conab.gov.br/images*cafe*.pdf&output=json&fl=timestamp,original&collapse=original&limit=300&matchType=prefix&filter=mimetype:application/pdf'),
]:
    rc = req.get(cdx_url, timeout=25)
    rows = rc.json() if rc.status_code == 200 else []
    header_skipped = rows[1:] if rows and rows[0] == ['timestamp','original'] else rows
    print(f'CDX [{rc.status_code}] {label}: {len(header_skipped)} rows')
    for row in header_skipped[:5]: print('  ', row)







