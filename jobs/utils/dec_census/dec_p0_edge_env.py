"""Shared env helper for the DEC-P0 edge-evidence audit. Fetches EVIDENCE_PG_DSN from
Secrets Manager (never printed) and exposes get_dsn()."""
import json
import os

import boto3

SCRATCH = r'C:/Users/User/AppData/Local/Temp/claude/C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad'


def get_dsn():
    if os.environ.get('EVIDENCE_PG_DSN'):
        return os.environ['EVIDENCE_PG_DSN']
    td = json.load(open(os.path.join(SCRATCH, 'taskdef_rev99.json')))
    secrets = {s['name']: s['valueFrom'] for s in td['containerDefinitions'][0]['secrets']}
    sm = boto3.client('secretsmanager', region_name='us-east-1')
    cand = secrets['EVIDENCE_PG_DSN']
    while True:
        try:
            return sm.get_secret_value(SecretId=cand)['SecretString']
        except sm.exceptions.ClientError:
            if cand.count(':') <= 6:
                raise
            cand = cand.rsplit(':', 1)[0]
