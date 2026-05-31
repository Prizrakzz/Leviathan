"""Inspect the UNICA raw HTML page structure to find the idTabela for fortnightly data."""
import boto3
import re

s3 = boto3.client("s3", region_name="us-east-1")
BUCKET = "leviathan-dev-shahem-001"

# Download one raw HTML file
resp = s3.get_object(Bucket=BUCKET, Key="raw/production/source=unica/harvest_year=2014_2015/production_milling.html")
html = resp["Body"].read().decode("utf-8", errors="replace")

# Look for idTabela values and menu options
print("=== idTabela occurrences ===")
for m in re.finditer(r"idTabela[\"']?\s*[=:]\s*[\"']?(\d+)", html, re.IGNORECASE):
    start = max(0, m.start() - 50)
    end = min(len(html), m.end() + 50)
    print(f"  Found: {m.group()} | context: {html[start:end]!r}")

print("\n=== tipoHistorico occurrences ===")
for m in re.finditer(r"tipoHistorico[\"']?\s*[=:]\s*[\"']?(\w+)", html, re.IGNORECASE):
    start = max(0, m.start() - 50)
    end = min(len(html), m.end() + 50)
    print(f"  Found: {m.group()} | context: {html[start:end]!r}")

print("\n=== option elements (select dropdowns) ===")
for m in re.finditer(r"<option[^>]*value=[\"']([^\"']+)[\"'][^>]*>([^<]+)</option>", html, re.IGNORECASE):
    print(f"  value={m.group(1)!r} label={m.group(2).strip()!r}")

print("\n=== select elements ===")
for m in re.finditer(r"<select[^>]*name=[\"']([^\"']+)[\"'][^>]*>", html, re.IGNORECASE):
    print(f"  select name={m.group(1)!r}")

print("\n=== Page title ===")
m = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
if m:
    print(f"  {m.group(1)!r}")
