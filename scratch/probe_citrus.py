import requests
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

r = session.get(
    "https://www.nass.usda.gov/Statistics_by_State/Florida/Publications/Citrus/Citrus_Forecast/history.php",
    timeout=30,
)
soup = BeautifulSoup(r.text, "html.parser")
all_pdf = [a for a in soup.find_all("a", href=True) if a["href"].lower().endswith(".pdf")]
print("Total PDF links on history.php:", len(all_pdf))

freeze = [
    a for a in all_pdf
    if "frz" in a["href"].lower() or "freeze" in a.get_text(strip=True).lower()
]
print("Freeze links found:", len(freeze))
for a in freeze:
    print(" href:", a["href"])
    print(" text:", a.get_text(strip=True))

print("\nFirst 3 href samples (absolute vs relative?):")
for a in all_pdf[:3]:
    print(" ", a["href"][:100])
