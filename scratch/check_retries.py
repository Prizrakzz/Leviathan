import boto3

b = boto3.client("batch", region_name="us-east-1")

ids = {
    "cotton-lowmem":  "6fe4bbd2-0d87-451f-8004-018f7067949d",
    "rapeseed-retry": "591d4304-bc9c-43c2-be5f-5aad8e6bafab",
    "soybean_meal":   "e0a35782-6971-45e9-971f-efad145d5e08",
    "soybean_oil":    "0bbdaa6f-b8ff-41ea-ac8c-024d372ad85a",
}
resp = b.describe_jobs(jobs=list(ids.values()))
by_id = {j["jobId"]: j for j in resp["jobs"]}
for name, jid in ids.items():
    j = by_id.get(jid, {})
    a = (j.get("attempts") or [{}])[-1]
    c = a.get("container", {})
    print(f"{name:<22} status={j.get('status','?'):<12} exit={c.get('exitCode','?'):<6} reason={c.get('reason','N/A')}")
