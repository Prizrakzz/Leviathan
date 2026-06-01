"""Probe UNICA biweekly PDFs from S3 to understand table structure across eras."""
from __future__ import annotations
import boto3, io, pdfplumber

s3 = boto3.client('s3', region_name='us-east-1')
bucket = 'leviathan-dev-shahem-001'

# One per era: 2012/13, 2013/14, 2017/18, 2018/19, 2020/21, 2022/23, 2024/25, 2025/26
samples = [
    ('2012_2013', 'pdf_04500aa73c3eb5ce'),
    ('2013_2014', 'pdf_c2c901c6936f42b1f79c9fee898d0a44'),
    ('2017_2018', 'pdf_99fd14c6be76141141135874325a7236'),
    ('2018_2019', 'pdf_b851e3557530ca223a81fcce166a6c3e'),
    ('2020_2021', 'pdf_1db4ecbb8cd25ecacd375ccb1a17cd89'),
    ('2022_2023', 'pdf_3d218fe534ceccb61233b93ba0712f01'),
    ('2024_2025', 'pdf_2bacb7cddca1cd1eef3511eab0106a46'),
]

for hy, idm in samples:
    key = f'raw/production/source=unica_biweekly/harvest_year={hy}/idm={idm}/report.pdf'
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = obj['Body'].read()
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            n = len(pdf.pages)
            size_kb = len(data) // 1024
            print(f'=== {hy} | {idm[:24]} | {n} pages | {size_kb} KB ===')
            for i, pg in enumerate(pdf.pages):
                txt = (pg.extract_text() or '').strip()
                snippet = txt[:300].replace('\n', ' | ')
                print(f'  p{i+1}: {snippet!r}')
            print()
    except Exception as e:
        print(f'ERROR {hy} {idm}: {e}')
