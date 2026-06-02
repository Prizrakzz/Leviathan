import boto3

b = boto3.client("batch", region_name="us-east-1")
s3 = boto3.client("s3", region_name="us-east-1")
pag = s3.get_paginator("list_objects_v2")

by_source = {}
for page in pag.paginate(Bucket="leviathan-dev-shahem-001", Prefix="text/source=usda_gain"):
    for obj in page.get("Contents", []):
        src = next((p for p in obj["Key"].split("/") if p.startswith("source=")), "unknown")
        by_source[src] = by_source.get(src, 0) + 1

# One entry per source: map canonical source name → latest job ID (rekey run)
LATEST_JOB_IDS = {
    "usda_gain_cocoa":            "763468e6-c802-454d-b51d-fc699aedbdb0",
    "usda_gain_coffee":           "efb18908-fd54-4682-ae78-038801f79097",
    "usda_gain_coffee_semiannual":"f53dd7e7-d3b7-4174-8ecc-7b994c99e94b",
    "usda_gain_corn":             "0bb0f138-e852-48db-ab60-aa45e99bd943",
    "usda_gain_cotton":           "5071f646-efd0-4896-8cc3-2184b399646e",
    "usda_gain_cotton_monthly":   "9d962c39-4299-4e73-9fd0-db93d98c9c07",
    "usda_gain_grain_monthly":    "096493fc-da86-4aed-94f9-a8c9f5e09fc7",
    "usda_gain_orange_juice":     "3209eca6-cce0-4383-8e21-eacbcad89784",
    "usda_gain_palm_oil":         "0d23d612-4e23-4c9a-a396-37ad0b06b06b",
    "usda_gain_rapeseed":         "084f78c2-393b-4415-abd1-02813dadb786",
    "usda_gain_rice":             "ad304345-be95-4ac8-89e5-ca9f4ba427fc",
    "usda_gain_soybean_meal":     "10de9d2f-af2b-4ae5-9079-fcda7d839da2",
    "usda_gain_soybean_oil":      "cc14e0e6-5de8-42f9-ad52-ce9bcdcfbe91",
    "usda_gain_soybeans":         "8589eb1a-5c6f-43a2-a46f-19d49081fede",
    "usda_gain_sugar":            "76a0e3f0-0d29-4463-825a-2c0801e5edf4",
    "usda_gain_sugar_semiannual": "d5c6aa98-ad19-4491-a635-12303df117c2",
    "usda_gain_wheat":            "fd040e44-76e6-4233-a50e-46df3061e4a8",
}
resp = b.describe_jobs(jobs=list(LATEST_JOB_IDS.values()))
jobs = {j["jobId"]: j for j in resp["jobs"]}

raw_counts = {
    "usda_gain_cocoa": 21, "usda_gain_coffee": 645, "usda_gain_coffee_semiannual": 86,
    "usda_gain_corn": 167, "usda_gain_cotton": 889, "usda_gain_cotton_monthly": 226,
    "usda_gain_grain_monthly": 645, "usda_gain_orange_juice": 179, "usda_gain_palm_oil": 73,
    "usda_gain_rapeseed": 84, "usda_gain_rice": 120, "usda_gain_soybean_meal": 261,
    "usda_gain_soybean_oil": 133, "usda_gain_soybeans": 127, "usda_gain_sugar": 801,
    "usda_gain_sugar_semiannual": 159, "usda_gain_wheat": 214,
}

print(f"{'Source':<32} {'Status':<12} {'Written':>8} {'Total':>7}")
print("-" * 64)
for src, total in sorted(raw_counts.items()):
    jid = LATEST_JOB_IDS.get(src, "")
    j = jobs.get(jid, {})
    status = j.get("status", "UNKNOWN")
    written = by_source.get("source=" + src, 0)
    print(f"{src:<32} {status:<12} {written:>8} {total:>7}")

total_written = sum(by_source.get("source=" + src, 0) for src in raw_counts)
total_raw = sum(raw_counts.values())
print(f"\n{'TOTAL':<32} {'':12} {total_written:>8} {total_raw:>7}")
