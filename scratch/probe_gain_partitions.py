"""Check if sugar/coffee 'shortfall' is from multiple PDFs per partition."""
import boto3
from collections import defaultdict

pag = boto3.client("s3", region_name="us-east-1").get_paginator("list_objects_v2")

for source in ["usda_gain_sugar", "usda_gain_coffee"]:
    keys = []
    for page in pag.paginate(Bucket="leviathan-dev-shahem-001", Prefix=f"raw/production/source={source}/"):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".pdf"):
                keys.append(obj["Key"])

    partitions: dict = defaultdict(list)
    for k in keys:
        parts = {p.split("=")[0]: p.split("=")[1] for p in k.split("/") if "=" in p}
        pkey = (parts.get("country", "?"), parts.get("publication_date", "?"))
        partitions[pkey].append(k)

    dupes = {k: v for k, v in partitions.items() if len(v) > 1}
    print(f"\n{source}")
    print(f"  raw PDFs: {len(keys)}  unique partitions: {len(partitions)}  multi-PDF: {len(dupes)}")
    for (c, d), ks in sorted(dupes.items())[:5]:
        print(f"  {c}/{d}: {len(ks)} PDFs")
        for k in ks[:2]:
            print(f"    {k.split('/')[-1]}")
