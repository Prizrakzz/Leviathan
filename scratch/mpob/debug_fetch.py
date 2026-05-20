
import pathlib, re, ssl, urllib.request

ctx = ssl.create_default_context()
ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'
url = 'https://bepi.mpob.gov.my/index.php?option=com_content&view=article&id=1249'
req = urllib.request.Request(url, headers={'User-Agent': ua})

try:
    with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
        html = r.read().decode('utf-8', errors='replace')
    print('Status: 200, Length:', len(html), 'Final URL:', url)
except Exception as e:
    print('Error:', e)
    raise SystemExit(1)

pathlib.Path('data/mpob').mkdir(parents=True, exist_ok=True)
pathlib.Path('data/mpob/debug_art1249.html').write_text(html, encoding='utf-8')
print('Saved')

# Check for data-loading keywords
for kw in ['ajax', 'fetch(', 'XMLHttpRequest', '.json', '.php?', 'api/', 'DataTable', 'highcharts', 'iframe', 'embed', 'csv', 'xlsx', 'JTable', 'CRUDE PALM', 'palm oil', 'production']:
    ct = html.lower().count(kw.lower())
    if ct:
        print(f'  {kw!r}: {ct}')

# Print text snippet (first 3000 visible chars)
html = re.sub(r'<[^>]+>', ' ', html)
html = re.sub(r'\s+', ' ', html).strip()
print('Visible text (first 3000 chars):', html[:3000])

