"""Audit manifest by year."""
import yaml

with open("configs/sources/wb_cmo_outlook_manifest.yaml") as f:
    data = yaml.safe_load(f)

entries = data["reports"]
resolved = [e for e in entries if not e.get("wayback_needed")]
needed = [e for e in entries if e.get("wayback_needed")]
by_year = {}
for e in entries:
    yr = e["release_date"][:4]
    by_year.setdefault(yr, {"resolved": 0, "needed": 0})
    if e.get("wayback_needed"):
        by_year[yr]["needed"] += 1
    else:
        by_year[yr]["resolved"] += 1

print(f"Total: {len(entries)}  Resolved: {len(resolved)}  wayback_needed: {len(needed)}")
print()
for yr in sorted(by_year):
    d = by_year[yr]
    flag = " ***" if d["needed"] > 0 else ""
    print(f"  {yr}: {d['resolved']} resolved, {d['needed']} needed{flag}")
