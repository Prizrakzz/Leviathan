"""dec_p0 slice-census probe: pg connectivity + node census + S3 listing. ASCII stdout only."""
import json
import os
import sys

import boto3

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'
td = json.load(open(os.path.join(SCRATCH, 'taskdef_rev99.json')))
secrets = {s['name']: s['valueFrom'] for s in td['containerDefinitions'][0]['secrets']}
sm = boto3.client('secretsmanager', region_name='us-east-1')


def _fetch(value_from):
    cand = value_from
    while True:
        try:
            return sm.get_secret_value(SecretId=cand)['SecretString']
        except sm.exceptions.ClientError:
            if cand.count(':') <= 6:
                raise
            cand = cand.rsplit(':', 1)[0]


dsn = _fetch(secrets['EVIDENCE_PG_DSN'])
os.environ['EVIDENCE_PG_DSN'] = dsn

import psycopg  # noqa: E402

with psycopg.connect(dsn, autocommit=True, connect_timeout=20) as conn:
    rows = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1").fetchall()
    print("tables:", [r[0] for r in rows])
    for t in [r[0] for r in rows if r[0].startswith('evidence_props')]:
        n = conn.execute(f"SELECT count(*), count(DISTINCT node) FROM {t}").fetchone()
        print(f"  {t}: rows={n[0]} distinct_nodes={n[1]}")

print("--- S3 top-level + drivers LIST ---", flush=True)
s3 = boto3.client('s3')
BKT = 'leviathan-dev-shahem-001'
PFX = 'graphrag_evidence/'
top = []
for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BKT, Prefix=PFX, Delimiter='/'):
    for o in page.get('Contents') or []:
        top.append((o['Key'][len(PFX):], o['Size'], o['LastModified'].isoformat()))
    for cp in page.get('CommonPrefixes') or []:
        print("  prefix:", cp['Prefix'])
print("  top-level objects:", len(top))
drv = []
for page in s3.get_paginator('list_objects_v2').paginate(Bucket=BKT, Prefix=PFX + 'drivers/'):
    for o in page.get('Contents') or []:
        drv.append((o['Key'][len(PFX + 'drivers/'):], o['Size'], o['LastModified'].isoformat()))
print("  drivers/ objects:", len(drv))
json.dump({'top': top, 'drivers': drv}, open(os.path.join(SCRATCH, 'dec_p0_s3list.json'), 'w'), indent=1)
print("wrote dec_p0_s3list.json")
