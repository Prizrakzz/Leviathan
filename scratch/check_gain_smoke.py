import boto3
import json

s3 = boto3.client("s3", region_name="us-east-1")
bucket = "leviathan-dev-shahem-001"
pag = s3.get_paginator("list_objects_v2")

keys = []
for page in pag.paginate(Bucket=bucket, Prefix="text/source=usda_gain_cocoa/"):
    keys += [o["Key"] for o in page.get("Contents", [])]

print(f"Found {len(keys)} document.json files")
for k in keys:
    obj = s3.get_object(Bucket=bucket, Key=k)
    doc = json.loads(obj["Body"].read())
    src = doc["source"]
    method = doc["extraction_method"]
    nsec = len(doc["sections"])
    ftlen = len(doc["full_text"])
    print(f"  {k}")
    print(f"    source={src}  method={method}  sections={nsec}  full_text_len={ftlen}")
