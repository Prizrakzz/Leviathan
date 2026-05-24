"""Probe the AppEEARS API using the EARTH_DATA token from .env.

Tests:
  1. Auth — tries EARTH_DATA JWT as Bearer token, then falls back to /login
  2. GET /product/MOD13Q1.061  — confirm product exists
  3. GET /task                  — list existing tasks (proves auth is working)

Usage:
  python scratch/probe_appeears.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values

_env = dotenv_values(Path(__file__).parent.parent / ".env")

BASE = "https://appeears.earthdatacloud.nasa.gov/api"
USER = _env.get("EARTHDATA_USER", "")
PASSWORD = _env.get("EARTHDATA_PASSWORD", "")

if not USER or not PASSWORD:
    print("ERROR: EARTHDATA_USER / EARTHDATA_PASSWORD not found in .env")
    sys.exit(1)


# ── helpers ──────────────────────────────────────────────────────────────────

def get_bearer_token() -> str:
    """POST /login with Basic Auth → returns short-lived AppEEARS Bearer token."""
    r = requests.post(
        f"{BASE}/login",
        auth=(USER, PASSWORD),
        headers={"Content-Length": "0"},
        timeout=15,
    )
    if r.status_code == 200:
        token = r.json()["token"]
        expires = r.json()["expiration"]
        print(f"✓ Login OK — token expires {expires}")
        return token
    print(f"  POST /login → HTTP {r.status_code}: {r.text[:200]}")
    return ""


# ── 1. Auth ───────────────────────────────────────────────────────────────────
print("\n=== 1. Auth ===")
token = get_bearer_token()

# ── 2. Product info (no auth needed) ─────────────────────────────────────────
print("\n=== 2. MOD13Q1.061 product info ===")
r = requests.get(f"{BASE}/product/MOD13Q1.061", timeout=15)
if r.status_code == 200:
    layers = r.json()
    ndvi_layers = [k for k in layers if "NDVI" in k or "pixel_reliability" in k]
    print(f"✓ Product exists. Relevant layers: {ndvi_layers}")
else:
    print(f"  HTTP {r.status_code}: {r.text[:200]}")

# ── 3. List tasks (auth required) ────────────────────────────────────────────
if token:
    print("\n=== 3. Existing tasks ===")
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE}/task", headers=headers, timeout=15)
    if r.status_code == 200:
        tasks = r.json()
        print(f"✓ {len(tasks)} task(s) on account")
        for t in tasks[:5]:
            print(f"  [{t.get('status')}] {t.get('task_name')} — id={t.get('task_id')}")
    else:
        print(f"  HTTP {r.status_code}: {r.text[:200]}")

# ── 4. Show example payload for our full run ──────────────────────────────────
print("\n=== 4. Example task payload (for reference) ===")
example_payload = {
    "task_type": "point",
    "task_name": "leviathan-modis-ndvi-backfill",
    "params": {
        "dates": [{"startDate": "02-18-2000", "endDate": "12-31-2025"}],
        "layers": [
            {"product": "MOD13Q1.061", "layer": "_250m_16_days_NDVI"},
            {"product": "MOD13Q1.061", "layer": "_250m_16_days_pixel_reliability"},
        ],
        "coordinates": [
            {"id": "us_corn_iowa",      "category": "corn_cbot", "latitude": 42.03, "longitude": -93.64},
            {"id": "us_corn_illinois",  "category": "corn_cbot", "latitude": 40.63, "longitude": -89.40},
        ],
    },
}
print(json.dumps(example_payload, indent=2))
