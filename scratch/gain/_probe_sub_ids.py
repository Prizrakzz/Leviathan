"""One-off script to probe FAS GAIN sub-filters for Fruits & Vegetables (ID 8)."""
from curl_cffi import requests as cr
from bs4 import BeautifulSoup
import re

sess = cr.Session()
sess.headers.update({"Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"})

url = (
    "https://fas.usda.gov/data/search"
    "?reports%5B0%5D=report_type%3A10251"
    "&reports%5B1%5D=report_commodities%3A8"
)
r = sess.get(url, impersonate="chrome124", timeout=30)
soup = BeautifulSoup(r.text, "html.parser")

links = [a for a in soup.find_all("a") if "report_commodities" in (a.get("href") or "")]
ids: dict[str, str] = {}
for a in links:
    href = a.get("href", "")
    m = re.search(r"report_commodities(?:%3A|:)(\d+)", href)
    if m:
        ids[m.group(1)] = a.get_text(strip=True)

print("Sub-IDs after filtering by 8 (Fruits & Veg):")
for k, v in sorted(ids.items(), key=lambda x: int(x[0])):
    print(f"  {k:>8}  {v}")

print()
cards = soup.select(".c-card")
print(f"Cards on page 1: {len(cards)}")
for card in cards[:8]:
    t = card.select_one(".c-card__title")
    if t:
        print(" ", t.get_text(strip=True))
