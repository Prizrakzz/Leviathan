from curl_cffi import requests as cr
import json

r = cr.get(
    "https://apps.fas.usda.gov/newgainapi/api/Report/FindReports?reporttypeid=13286&max=5",
    impersonate="chrome136",
    timeout=25,
)
print("status:", r.status_code)
print("text:", r.text[:800])
