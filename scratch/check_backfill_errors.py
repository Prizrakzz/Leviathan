import re

content = open("logs/unica_biweekly_bronze_run.log", encoding="utf-8", errors="replace").read()

# Find Parquet write errors
matches = re.findall(r"Parquet write failed  table=(\S+)  key=(\S+): (.+)", content)
print(f"Total parquet errors: {len(matches)}")
for table, key, err in matches[:5]:
    print(f"  table={table}")
    print(f"  key={key[:90]}")
    print(f"  err={err[:200]}")
    print()
