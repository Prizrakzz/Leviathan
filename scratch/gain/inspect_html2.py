"""Dig deeper into the FAS GAIN search page HTML structure."""
from curl_cffi import requests as cr
from bs4 import BeautifulSoup
import re

s = cr.Session()
s.headers["Accept"] = "text/html"

BASE_URL = "https://fas.usda.gov/data/search?reports%5B0%5D=report_type%3A10251&reports%5B1%5D=report_commodities%3A609"

# ---------- Page 1 ----------
r = s.get(BASE_URL, impersonate="chrome124", timeout=30)
html = r.text
soup = BeautifulSoup(html, "html.parser")

# Find c-card elements
cards = soup.select(".c-card")
print(f"c-card elements: {len(cards)}")

# Show the first 2 card HTML snippets
print("\n=== First 2 c-card HTML ===")
for card in cards[:2]:
    print(card.prettify()[:1500])
    print("---")

# Find pagination
print("\n=== Pagination elements ===")
pager = soup.select(".pager, .pager__item, nav[aria-label*='paginat'], .js-pager, li.next")
for p in pager[:5]:
    print(p)

# Check for page=N in any links
page_links = re.findall(r'href="[^"]*page=(\d+)[^"]*"', html)
print(f"\npage= values found: {sorted(set(int(x) for x in page_links))}")

# ---------- Page 2 test ----------
print("\n=== Page 2 test ===")
r2 = s.get(BASE_URL + "&page=1", impersonate="chrome124", timeout=30)
links2 = re.findall(r'href="(/data/gain/[^"]+)"', r2.text)
print(f"Report links on page 2: {len(links2)}")
for lk in links2[:5]:
    print(f"  {lk}")

# ---------- Landing page ----------
print("\n=== Kenya Coffee Annual landing page ===")
r3 = s.get("https://fas.usda.gov/data/gain/2026/05/kenya-coffee-annual", impersonate="chrome124", timeout=30)
soup3 = BeautifulSoup(r3.text, "html.parser")

# Look for PDF link
for sel in ["a[href*='gain-report']", "a[href$='.pdf']", ".field--name-field-report-file a", "[class*='file'] a", ".c-report__file a"]:
    els = soup3.select(sel)
    if els:
        print(f"  Selector {sel!r}: {len(els)} matches")
        for el in els[:3]:
            print(f"    href={el.get('href')}  text={el.get_text()[:50]}")

# Country + date fields
print("\n  Country field:")
for sel in [".field--name-field-country .field__item", "[class*='country']"]:
    els = soup3.select(sel)
    for el in els[:3]:
        print(f"    {sel}: {el.get_text()[:80]}")

print("\n  Date field:")
time_el = soup3.find("time")
if time_el:
    print(f"    <time datetime={time_el.get('datetime')}> {time_el.get_text()}")
