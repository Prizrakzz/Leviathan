"""
Get bitstream UUIDs for the 5 CMO Outlook entries using correct handle IDs.
"""
import requests
import time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
BASE = "https://openknowledge.worldbank.org/server/api"

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept": "application/json"})


def get_bitstream_uuid(handle_id):
    r = s.get(
        f"{BASE}/discover/search/objects",
        params={"query": f"handle:{handle_id}", "size": 1},
        timeout=30,
    )
    r.raise_for_status()
    objects = (
        r.json()
        .get("_embedded", {})
        .get("searchResult", {})
        .get("_embedded", {})
        .get("objects", [])
    )
    if not objects:
        return None, "not found"
    obj = objects[0]["_embedded"]["indexableObject"]
    item_uuid = obj["uuid"]
    item_name = obj.get("name", "")

    r2 = s.get(f"{BASE}/core/items/{item_uuid}/bundles", timeout=30)
    r2.raise_for_status()
    for bundle in r2.json().get("_embedded", {}).get("bundles", []):
        if bundle["name"] == "ORIGINAL":
            r3 = s.get(bundle["_links"]["bitstreams"]["href"], timeout=30)
            r3.raise_for_status()
            for bit in r3.json().get("_embedded", {}).get("bitstreams", []):
                bname = bit.get("name", "")
                if bname.lower().endswith(".pdf"):
                    return bit["uuid"], f"{bname} [{item_name}]"
    return None, "no PDF bitstream"


# Correct handle IDs from title search
entries = [
    ("2021-04", "10986/35458"),
    ("2023-04", "10986/39633"),
    ("2023-10", "10986/40363"),
    ("2024-04", "10986/41280"),
    ("2025-10", "10986/43864"),
]

for release, handle in entries:
    uuid, info = get_bitstream_uuid(handle)
    if uuid:
        url = f"https://openknowledge.worldbank.org/server/api/core/bitstreams/{uuid}/content"
        print(f"{release}:  {url}  # {info}")
    else:
        print(f"{release}:  ERROR — {info}")
    time.sleep(0.5)

