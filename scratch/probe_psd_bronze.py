"""One-off probe script for PSD bronze exploration."""
import boto3, io, pandas as pd
s3 = boto3.client('s3', region_name='us-east-1')
bucket = 'leviathan-dev-shahem-001'
df = pd.read_parquet(io.BytesIO(s3.get_object(Bucket=bucket, Key='bronze/production/source=usda_psd/release_date=2026-05-20/part-000.parquet')['Body'].read()))

# 1. Does silver/psd exist?
try:
    resp = s3.head_object(Bucket=bucket, Key='silver/psd/part-000.parquet')
    print('silver/psd/part-000.parquet EXISTS:', resp['ContentLength'], 'bytes')
except Exception:
    print('silver/psd/part-000.parquet: does not exist yet')

# 2. Existing silver keys
silver_keys = []
paginator = s3.get_paginator('list_objects_v2')
for page in paginator.paginate(Bucket=bucket, Prefix='silver/'):
    for obj in page.get('Contents', []):
        silver_keys.append(obj['Key'])
print('Existing silver keys:')
for k in sorted(silver_keys):
    print(' ', k)

# 3. month_code=0 semantics
m0 = df[df.month_code == 0]
print(f'\nmonth_code=0: {len(m0)} rows, MY range {m0.market_year.min()}-{m0.market_year.max()}')
corn_both = df[(df.commodity_code == 440000) & (df.country_name == 'United States')]
mc_per_my = corn_both.groupby('market_year')['month_code'].unique()
print('Corn US month_codes per MY (first 10):')
print(mc_per_my.head(10).to_string())

# 4. Null/zero values in core grain scope
core_attrs = [20, 28, 57, 88, 125, 176]
grain_codes = [410000, 440000, 422110, 459200, 2222000, 813100, 4232000, 2226000, 4239100, 813600, 4243000]
core = df[(df.commodity_code.isin(grain_codes)) & (df.attribute_id.isin(core_attrs))]
null_vals = core['value'].isna().sum()
zero_vals = (core['value'] == 0).sum()
print(f'\nCore grain+oilseed rows: {len(core)}')
print(f'Null values in core: {null_vals}')
print(f'Zero values in core: {zero_vals}')

# 5. S/U ratio pre-computed by USDA (attr 195)
su_rows = df[df.attribute_id == 195]
print(f'\nUSDA pre-computed S/U (attr 195): {len(su_rows)} rows')
print(f'Commodities: {sorted(su_rows.commodity_code.unique().tolist())}')

# 6. Row counts per target commodity
TARGET_CODES = {
    410000: 'wheat', 440000: 'corn', 422110: 'rice_milled', 459200: 'sorghum',
    2222000: 'soybeans', 813100: 'soybean_meal', 4232000: 'soybean_oil',
    2226000: 'rapeseed', 4239100: 'rapeseed_oil', 813600: 'rapeseed_meal',
    4243000: 'palm_oil', 612000: 'sugar', 711100: 'coffee', 2631000: 'cotton'
}
print('\nRow counts per target commodity:')
for code, slug in sorted(TARGET_CODES.items(), key=lambda x: x[1]):
    n = len(df[df.commodity_code == code])
    print(f'  {slug:<25} {code:>8}:  {n:>7} rows')

# 7. Key grain: how many countries per commodity?
print('\nDistinct countries per commodity:')
for code, slug in sorted(TARGET_CODES.items(), key=lambda x: x[1]):
    n_countries = df[df.commodity_code == code]['country_name'].nunique()
    print(f'  {slug:<25} {code:>8}:  {n_countries:>4} countries')

# 8. Market year range per commodity
print('\nMarket year range per commodity:')
for code, slug in sorted(TARGET_CODES.items(), key=lambda x: x[1]):
    sub = df[df.commodity_code == code]
    print(f'  {slug:<25}:  MY {sub.market_year.min()} -> {sub.market_year.max()}')
