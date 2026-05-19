import urllib.request, re

url = "https://unicadata.com.br/js/scripts.js"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=15) as r:
    js = r.read().decode("utf-8", "replace")

# Print the full JS file
print(js)
