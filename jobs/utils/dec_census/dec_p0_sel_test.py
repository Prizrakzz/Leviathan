import time

import boto3

s3 = boto3.client('s3', region_name='us-east-1')
t0 = time.time()
try:
    r = s3.select_object_content(
        Bucket='leviathan-dev-shahem-001',
        Key='graphrag_evidence/cocoa.jsonl',
        ExpressionType='SQL',
        Expression=("SELECT s.source_key, s.source, s.date, s.char_start, s.offset_kind, "
                    "s.contract, s.chunk_version, s.id FROM S3Object[*] s"),
        InputSerialization={'JSON': {'Type': 'LINES'}},
        OutputSerialization={'JSON': {'RecordDelimiter': '\n'}},
    )
    buf = b''
    for ev in r['Payload']:
        if 'Records' in ev:
            buf += ev['Records']['Payload']
        if 'Stats' in ev:
            print('STATS', ev['Stats']['Details'])
    print('bytes out', len(buf), 'lines', buf.count(b'\n'))
    print(buf[:600].decode())
    print('elapsed', round(time.time() - t0, 1))
except Exception as e:
    print('S3SELECT FAILED:', type(e).__name__, str(e)[:400])
