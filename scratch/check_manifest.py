import yaml
with open("configs/sources/wb_cmo_outlook_manifest.yaml", encoding="utf-8") as f:
    m = yaml.safe_load(f)
reports = m["reports"]
total = len(reports)
resolved = [r for r in reports if not r.get("wayback_needed", True) and r.get("url")]
unresolved = [r for r in reports if r.get("wayback_needed", True) or not r.get("url")]
print(f"Total: {total}  Resolved: {len(resolved)}  Unresolved: {len(unresolved)}")
print()
print("Resolved entries:")
for r in sorted(resolved, key=lambda x: x["release_date"]):
    print(f"  {r['release_date']}  {str(r['label'])[:18]:18s}  {str(r['url'])[:65]}")
