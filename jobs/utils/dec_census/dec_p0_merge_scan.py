"""dec_p0: fold the in-VPC scan into the scan store and cross-check it against the local one.

The cloud job re-measured ALL 125 slices; the laptop had already measured 104 of them over the home
link. Those 104 are therefore an INDEPENDENT second measurement of the same bytes by a different
transport -- if n_props and every era bucket agree, the scan is verified end to end.

Writes dec_p0_era_scan_final.jsonl (cloud rows, the complete universe) + prints the agreement report.
ASCII stdout only.
"""
import json
import os
import sys

import boto3

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
BKT = 'leviathan-dev-shahem-001'
ERAS = ("pre1990", "1990s", "2000s", "2010_17", "2018_26", "undated")

key = sys.argv[1]
body = boto3.client('s3').get_object(Bucket=BKT, Key=key)['Body'].read()
cloud_doc = json.loads(body.decode('utf-8'))
json.dump(cloud_doc, open(os.path.join(SCRATCH, 'dec_p0_cloud_scan.json'), 'w'), indent=1)
cloud = {r['slice']: r for r in cloud_doc['slices']}

local = {}
p = os.path.join(SCRATCH, 'dec_p0_era_scan.jsonl')
if os.path.exists(p):
    for ln in open(p, encoding='utf-8'):
        if ln.strip():
            r = json.loads(ln)
            local[r['slice']] = r

print("cloud: %d slices, %d failed, %.0fs elapsed" % (
    cloud_doc['n_slices'], cloud_doc['n_failed'], cloud_doc['elapsed_seconds']))
if cloud_doc['n_failed']:
    print("FAILURES:", json.dumps(cloud_doc['failures'])[:500])

both = sorted(set(cloud) & set(local))
n_ok = 0
bad = []
for nm in both:
    c, l = cloud[nm], local[nm]
    if c['n_props'] == l['n_props'] and all(c['era_hist'][e] == l['era_hist'][e] for e in ERAS):
        n_ok += 1
    else:
        bad.append({"slice": nm, "cloud_n": c['n_props'], "local_n": l['n_props'],
                    "cloud_hist": c['era_hist'], "local_hist": l['era_hist']})
print("independent cross-check (laptop vs VPC, same bytes, different transport): %d/%d slices agree "
      "on n_props AND all six era buckets" % (n_ok, len(both)))
for b in bad[:10]:
    print("  DISAGREE", json.dumps(b))

out = os.path.join(SCRATCH, 'dec_p0_era_scan_final.jsonl')
with open(out, 'w', encoding='utf-8') as f:
    for nm in sorted(cloud):
        f.write(json.dumps(cloud[nm]) + "\n")
print("wrote %s (%d slices)" % (out, len(cloud)))
json.dump({"n_compared": len(both), "n_agree": n_ok, "disagreements": bad,
           "cloud_key": key, "cloud_elapsed_seconds": cloud_doc['elapsed_seconds'],
           "cloud_n_failed": cloud_doc['n_failed']},
          open(os.path.join(SCRATCH, 'dec_p0_crosscheck.json'), 'w'), indent=1)
