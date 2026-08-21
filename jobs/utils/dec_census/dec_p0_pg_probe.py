"""DEC-P0 chunk census: pg probe. Never prints the DSN."""
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

conn = psycopg.connect(dsn, autocommit=True, connect_timeout=20)
cur = conn.cursor()
cur.execute("select table_name from information_schema.tables where table_schema='public' order by 1")
print("TABLES:", [r[0] for r in cur.fetchall()])
cur.execute("select count(*) from evidence_props")
print("evidence_props rows:", cur.fetchone()[0])
cur.execute("select column_name, data_type from information_schema.columns where table_name='evidence_props' order by ordinal_position")
for r in cur.fetchall():
    print("  col", r)
cur.execute("select meta from evidence_props where meta is not null limit 3")
for r in cur.fetchall():
    print("  meta sample keys:", sorted((r[0] or {}).keys()))
conn.close()
print("OK")
