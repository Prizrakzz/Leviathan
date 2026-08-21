import json
import os

import boto3

OUT = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
s3 = boto3.client("s3", region_name="us-east-1")
for name in ("write_manifest_rebuild_20260803T134404Z.json", "write_manifest_seed_20260801T222451Z.json"):
    body = s3.get_object(Bucket="leviathan-dev-shahem-001",
                         Key=f"graphrag_evidence/eval/{name}")["Body"].read()
    d = json.loads(body)
    with open(os.path.join(OUT, name), "wb") as fh:
        fh.write(body)
    print("=" * 70)
    print(name, "label=", d.get("label"), "chunk_version=", d.get("chunk_version"))
    print("command:", " ".join(d.get("command") or [])[:200])
    print("layers:", list((d.get("slices") or {}).keys()))
    for layer, recs in (d.get("slices") or {}).items():
        tot = sum((r.get("after_n") or 0) for r in recs.values())
        print(f"  layer {layer}: {len(recs)} slices, after_n total {tot:,}")
    g = d.get("guard") or {}
    for layer, gg in g.items():
        print(f"  guard {layer}: before_n={gg.get('layer_before_n')} after_n={gg.get('layer_after_n')}")
    print("docs:", {k: v for k, v in (d.get("docs") or {}).items() if k != "per_doc_delta"})
    print("unwritten layers:", {k: len(v) for k, v in (d.get("unwritten") or {}).items()})
