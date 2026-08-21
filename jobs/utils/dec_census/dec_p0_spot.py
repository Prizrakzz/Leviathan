import boto3, collections, json, io, gzip

B = "leviathan-dev-shahem-001"
s3 = boto3.client("s3")
out = {}


def lst(prefix):
    p = s3.get_paginator("list_objects_v2")
    keys = []
    for pg in p.paginate(Bucket=B, Prefix=prefix):
        for o in pg.get("Contents", []):
            keys.append((o["Key"], o["Size"]))
    return keys


# SC1 -- usda_wasde text layer re-count
k = lst("text/source=usda_wasde/")
base = collections.Counter(x[0].rsplit("/", 1)[-1] for x in k)
out["SC1_usda_wasde"] = {"objects": len(k), "basenames": dict(base)}
print("SC1", out["SC1_usda_wasde"])

# SC2 -- chunk doc-cache object count
c = lst("graphrag_evidence/chunks/")
out["SC2_chunks_prefix"] = {
    "objects": len(c),
    "bytes": sum(x[1] for x in c),
    "empty_objects": sum(1 for x in c if x[1] == 0),
}
print("SC2", out["SC2_chunks_prefix"])

# SC4 -- tiny slice prop counts, re-read from the live objects
res = {}
for name in ["indian_ocean_dipole", "cftc_positioning", "corn_tar_spot", "harmattan"]:
    key = "graphrag_evidence/drivers/%s.jsonl" % name
    try:
        b = s3.get_object(Bucket=B, Key=key)["Body"].read()
    except s3.exceptions.NoSuchKey:
        res[name] = {"present": False}
        continue
    except Exception as e:
        res[name] = {"present": False, "err": type(e).__name__}
        continue
    lines = [x for x in b.split(b"\n") if x.strip()]
    recs = [json.loads(x) for x in lines]
    res[name] = {
        "present": True,
        "bytes": len(b),
        "n_lines": len(lines),
        "n_with_vector": sum(1 for r in recs if r.get("vector") or r.get("embedding")),
        "distinct_source_keys": len({r.get("source_key") for r in recs}),
        "keys_on_rec": sorted(recs[0].keys()) if recs else [],
    }
print("SC4", json.dumps({k2: {kk: vv for kk, vv in v.items() if kk != "keys_on_rec"} for k2, v in res.items()}, indent=1))
out["SC4_slices"] = res

with open("dec_p0_spot_out.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print("WROTE dec_p0_spot_out.json")
