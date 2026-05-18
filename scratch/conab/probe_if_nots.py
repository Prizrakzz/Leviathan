import ssl, urllib.request
UA = 'Mozilla/5.0'
CTX = ssl.create_default_context()
GID = '1183_46d101ed07800927c23e1828eec4ed4a'
ORIG = f'https://www.conab.gov.br/info-agro/safras/cafe/boletim-da-safra-de-cafe/item/download/{GID}'
url = f'https://web.archive.org/web/if_/{ORIG}'
print('Testing:', url[-80:])
req = urllib.request.Request(url, headers={'User-Agent': UA})
try:
    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
        data = r.read(512)
        ct = r.info().get('Content-Type', '?')
        print(f'Status: {r.status}  CT: {ct}  First: {data[:20]}')
        print('IS PDF!' if data[:4] == b'%PDF' else f'NOT PDF: {data[:60]}')
except Exception as e:
    print('ERROR:', e)
