import urllib.request, ssl, json, urllib.parse
ctx = ssl.create_default_context()
ua = 'Mozilla/5.0'

gids = ['1171_9b6a51134e3bc5f18d5387a498b98c7d', '45502_94f81af36eb923bc7561183a3f1e1761']
base = 'https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/'
for gid in gids:
    full_url = base + gid
    encoded = urllib.parse.quote(full_url, safe='')
    api = f'https://web.archive.org/cdx/search/cdx?url={encoded}*&matchType=prefix&output=json&fl=original,timestamp&limit=5'
    req = urllib.request.Request(api, headers={'User-Agent': ua})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        rows = json.loads(r.read())
    print(f'gid {gid[:20]}: {len(rows)} CDX hits')
    for row in rows[:3]: print('  ', row)
