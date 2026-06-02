import boto3

s3 = boto3.client("s3", region_name="us-east-1")
pag = s3.get_paginator("list_objects_v2")

keys = []
for page in pag.paginate(Bucket="leviathan-dev-shahem-001", Prefix="bronze/production/source=usda_wasde/"):
    for obj in page.get("Contents", []):
        keys.append(obj["Key"])

print(f"Bronze WASDE partitions: {len(keys)}")
dates = sorted(
    k.split("release_date=")[1].split("/")[0]
    for k in keys if "release_date=" in k
)
if dates:
    print(f"Earliest: {dates[0]}")
    print(f"Latest:   {dates[-1]}")
    by_year = {}
    for d in dates:
        y = d[:4]
        by_year[y] = by_year.get(y, 0) + 1
    for yr in sorted(by_year):
        print(f"  {yr}: {by_year[yr]} files")
