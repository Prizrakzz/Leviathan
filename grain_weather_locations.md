# NASA POWER Grain Weather Location Universe

Purpose: this file defines the major weather-sensitive production regions for grain futures and grain reference contracts that should be ingested from the NASA POWER API into S3.

Contracts covered from the screenshot:

- Corn (CBOT)
- French Wheat (MATIF)
- Campinas Corn Reference (BMF/B3)
- French Maize (MATIF)
- Hard Red Winter Wheat (KCBT)
- Hard Red Spring Wheat (MGEX)
- Rough Rice (CBOT)
- Soft Red Winter Wheat (CBOT)
- South African White Maize (JSE)
- South African Yellow Maize (JSE)

Use this as the source-of-truth config for Copilot or your ingestion script.

---

## General ingestion rules

Use the `location_id` value from the YAML as the `region` Hive partition key in S3.

Recommended S3 layout:

```text
raw/weather/source=nasa_power/commodity={commodity}/country={country}/region={region}/year={year}/month={month}/payload.json
bronze/weather/source=nasa_power/commodity={commodity}/country={country}/region={region}/year={year}/month={month}/part-000.parquet
silver/weather/source=nasa_power/commodity={commodity}/country={country}/region={region}/year={year}/month={month}/part-000.parquet
```

Note: `region` in the S3 path takes the `location_id` value from the YAML (e.g. `us_corn_iowa`).
Fixed filename `part-000.parquet` enables idempotent overwrite on rerun.

Recommended historical ML backfill:

```text
2010-01-01 to 2024-12-31
```

Recommended NASA POWER daily variables:

```text
T2M
T2M_MAX
T2M_MIN
PRECTOTCORR
RH2M
WS2M
ALLSKY_SFC_SW_DWN
```

Optional variables (not yet wired into the silver transform — requires updating
`configs/sources/nasa_power.yaml` and `WEATHER_RENAME_MAP` before use):

```text
QV2M
GWETROOT
GWETTOP
T2MDEW
```

Recommended request shape:

```text
https://power.larc.nasa.gov/api/temporal/daily/point
  ?parameters=T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,RH2M,WS2M,ALLSKY_SFC_SW_DWN
  &community=AG
  &longitude={longitude}
  &latitude={latitude}
  &start=20100101
  &end=20241231
  &format=JSON
```

---

# Location Universe

```yaml
commodities:

  corn_cbot:
    description: "CBOT corn weather universe: major corn-producing and export-relevant regions."
    countries:
      united_states:
        regions:
          - location_id: "us_corn_iowa"
            region: "Iowa"
            latitude: 42.03
            longitude: -93.64
          - location_id: "us_corn_illinois"
            region: "Illinois"
            latitude: 40.63
            longitude: -89.40
          - location_id: "us_corn_nebraska"
            region: "Nebraska"
            latitude: 41.50
            longitude: -99.68
          - location_id: "us_corn_minnesota"
            region: "Minnesota"
            latitude: 46.73
            longitude: -94.69
          - location_id: "us_corn_indiana"
            region: "Indiana"
            latitude: 40.27
            longitude: -86.13
          - location_id: "us_corn_south_dakota"
            region: "South Dakota"
            latitude: 44.50
            longitude: -100.00
          - location_id: "us_corn_kansas"
            region: "Kansas"
            latitude: 38.50
            longitude: -98.00
          - location_id: "us_corn_missouri"
            region: "Missouri"
            latitude: 38.50
            longitude: -92.50
          - location_id: "us_corn_ohio"
            region: "Ohio"
            latitude: 40.42
            longitude: -82.91

      brazil:
        regions:
          - location_id: "br_corn_mato_grosso"
            region: "Mato Grosso"
            latitude: -12.64
            longitude: -55.42
          - location_id: "br_corn_parana"
            region: "Paraná"
            latitude: -24.89
            longitude: -51.55
          - location_id: "br_corn_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14
          - location_id: "br_corn_mato_grosso_do_sul"
            region: "Mato Grosso do Sul"
            latitude: -20.51
            longitude: -54.54
          - location_id: "br_corn_minas_gerais"
            region: "Minas Gerais"
            latitude: -18.10
            longitude: -44.38
          - location_id: "br_corn_sao_paulo"
            region: "São Paulo"
            latitude: -21.29
            longitude: -48.18

      argentina:
        regions:
          - location_id: "ar_corn_buenos_aires"
            region: "Buenos Aires"
            latitude: -36.68
            longitude: -60.56
          - location_id: "ar_corn_cordoba"
            region: "Córdoba"
            latitude: -31.42
            longitude: -64.18
          - location_id: "ar_corn_santa_fe"
            region: "Santa Fe"
            latitude: -31.63
            longitude: -60.70
          - location_id: "ar_corn_entre_rios"
            region: "Entre Ríos"
            latitude: -31.77
            longitude: -60.52

      ukraine:
        regions:
          - location_id: "ua_corn_vinnytsia"
            region: "Vinnytsia"
            latitude: 49.23
            longitude: 28.48
          - location_id: "ua_corn_poltnava"
            region: "Poltava"
            latitude: 49.59
            longitude: 34.55
          - location_id: "ua_corn_cherkasy"
            region: "Cherkasy"
            latitude: 49.44
            longitude: 32.06
          - location_id: "ua_corn_kirovohrad"
            region: "Kirovohrad"
            latitude: 48.51
            longitude: 32.26
          - location_id: "ua_corn_dnipropetrovsk"
            region: "Dnipropetrovsk"
            latitude: 48.46
            longitude: 35.05

  campinas_corn_reference_bmf:
    description: "Brazil-focused corn weather universe for Campinas/BMF/B3 reference pricing."
    countries:
      brazil:
        regions:
          - location_id: "br_corn_sao_paulo_campinas"
            region: "São Paulo / Campinas"
            latitude: -22.91
            longitude: -47.06
          - location_id: "br_corn_mato_grosso"
            region: "Mato Grosso"
            latitude: -12.64
            longitude: -55.42
          - location_id: "br_corn_parana"
            region: "Paraná"
            latitude: -24.89
            longitude: -51.55
          - location_id: "br_corn_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14
          - location_id: "br_corn_mato_grosso_do_sul"
            region: "Mato Grosso do Sul"
            latitude: -20.51
            longitude: -54.54
          - location_id: "br_corn_minas_gerais"
            region: "Minas Gerais"
            latitude: -18.10
            longitude: -44.38
          - location_id: "br_corn_sao_paulo"
            region: "São Paulo"
            latitude: -21.29
            longitude: -48.18
          - location_id: "br_corn_bahia_west"
            region: "Bahia / West"
            latitude: -12.15
            longitude: -45.00

  french_wheat_matif:
    description: "MATIF French wheat weather universe: French and EU export-relevant soft wheat regions."
    countries:
      france:
        regions:
          - location_id: "fr_wheat_centre_val_de_loire"
            region: "Centre-Val de Loire"
            latitude: 47.75
            longitude: 1.68
          - location_id: "fr_wheat_hauts_de_france"
            region: "Hauts-de-France"
            latitude: 50.48
            longitude: 2.79
          - location_id: "fr_wheat_grand_est"
            region: "Grand Est"
            latitude: 48.70
            longitude: 6.18
          - location_id: "fr_wheat_normandy"
            region: "Normandy"
            latitude: 49.18
            longitude: 0.37
          - location_id: "fr_wheat_bourgogne_franche_comte"
            region: "Bourgogne-Franche-Comté"
            latitude: 47.28
            longitude: 4.99
          - location_id: "fr_wheat_nouvelle_aquitaine"
            region: "Nouvelle-Aquitaine"
            latitude: 45.00
            longitude: 0.00

      germany:
        regions:
          - location_id: "de_wheat_lower_saxony"
            region: "Lower Saxony"
            latitude: 52.64
            longitude: 9.84
          - location_id: "de_wheat_saxony_anhalt"
            region: "Saxony-Anhalt"
            latitude: 51.95
            longitude: 11.69
          - location_id: "de_wheat_north_rhine_westphalia"
            region: "North Rhine-Westphalia"
            latitude: 51.43
            longitude: 7.66
          - location_id: "de_wheat_bavaria"
            region: "Bavaria"
            latitude: 48.79
            longitude: 11.50

      poland:
        regions:
          - location_id: "pl_wheat_wielkopolskie"
            region: "Wielkopolskie"
            latitude: 52.40
            longitude: 16.93
          - location_id: "pl_wheat_lubelskie"
            region: "Lubelskie"
            latitude: 51.25
            longitude: 22.57
          - location_id: "pl_wheat_kujawsko_pomorskie"
            region: "Kujawsko-Pomorskie"
            latitude: 53.12
            longitude: 18.00

      romania:
        regions:
          - location_id: "ro_wheat_south_muntenia"
            region: "South-Muntenia"
            latitude: 44.85
            longitude: 25.00
          - location_id: "ro_wheat_dobrogea"
            region: "Dobrogea"
            latitude: 44.18
            longitude: 28.64
          - location_id: "ro_wheat_moldavia"
            region: "Moldavia"
            latitude: 46.20
            longitude: 27.70

  french_maize_matif:
    description: "MATIF French maize weather universe: French and EU maize regions."
    countries:
      france:
        regions:
          - location_id: "fr_maize_nouvelle_aquitaine"
            region: "Nouvelle-Aquitaine"
            latitude: 45.00
            longitude: 0.00
          - location_id: "fr_maize_occitanie"
            region: "Occitanie"
            latitude: 43.60
            longitude: 1.44
          - location_id: "fr_maize_auvergne_rhone_alpes"
            region: "Auvergne-Rhône-Alpes"
            latitude: 45.76
            longitude: 4.84
          - location_id: "fr_maize_grand_est"
            region: "Grand Est"
            latitude: 48.70
            longitude: 6.18
          - location_id: "fr_maize_centre_val_de_loire"
            region: "Centre-Val de Loire"
            latitude: 47.75
            longitude: 1.68

      romania:
        regions:
          - location_id: "ro_maize_south_muntenia"
            region: "South-Muntenia"
            latitude: 44.85
            longitude: 25.00
          - location_id: "ro_maize_dobrogea"
            region: "Dobrogea"
            latitude: 44.18
            longitude: 28.64
          - location_id: "ro_maize_west"
            region: "West Romania"
            latitude: 45.75
            longitude: 21.23

      hungary:
        regions:
          - location_id: "hu_maize_great_plain"
            region: "Great Hungarian Plain"
            latitude: 47.16
            longitude: 19.50
          - location_id: "hu_maize_southern_transdanubia"
            region: "Southern Transdanubia"
            latitude: 46.07
            longitude: 18.23

      italy:
        regions:
          - location_id: "it_maize_lombardy"
            region: "Lombardy"
            latitude: 45.48
            longitude: 9.19
          - location_id: "it_maize_veneto"
            region: "Veneto"
            latitude: 45.44
            longitude: 12.33
          - location_id: "it_maize_emilia_romagna"
            region: "Emilia-Romagna"
            latitude: 44.50
            longitude: 11.34

  hard_red_winter_wheat_kcbt:
    description: "KCBT Hard Red Winter wheat weather universe: US Plains HRW belt."
    countries:
      united_states:
        regions:
          - location_id: "us_hrw_kansas_west"
            region: "Kansas / Western HRW Belt"
            latitude: 38.87
            longitude: -99.34
          - location_id: "us_hrw_kansas_central"
            region: "Kansas / Central HRW Belt"
            latitude: 38.50
            longitude: -98.00
          - location_id: "us_hrw_oklahoma"
            region: "Oklahoma"
            latitude: 35.47
            longitude: -97.52
          - location_id: "us_hrw_texas_panhandle"
            region: "Texas Panhandle"
            latitude: 35.22
            longitude: -101.83
          - location_id: "us_hrw_colorado_eastern_plains"
            region: "Colorado / Eastern Plains"
            latitude: 39.01
            longitude: -103.60
          - location_id: "us_hrw_nebraska_southwest"
            region: "Nebraska / Southwest"
            latitude: 40.20
            longitude: -101.30
          - location_id: "us_hrw_montana"
            region: "Montana HRW"
            latitude: 46.88
            longitude: -110.36

  hard_red_spring_wheat_mgex:
    description: "MGEX Hard Red Spring wheat weather universe: Northern Plains and Canadian Prairies."
    countries:
      united_states:
        regions:
          - location_id: "us_hrs_north_dakota"
            region: "North Dakota"
            latitude: 47.55
            longitude: -100.47
          - location_id: "us_hrs_minnesota_northwest"
            region: "Minnesota / Northwest"
            latitude: 47.75
            longitude: -96.00
          - location_id: "us_hrs_montana_north_central"
            region: "Montana / North Central"
            latitude: 47.50
            longitude: -111.30
          - location_id: "us_hrs_south_dakota"
            region: "South Dakota"
            latitude: 44.50
            longitude: -100.00

      canada:
        regions:
          - location_id: "ca_hrs_saskatchewan"
            region: "Saskatchewan"
            latitude: 52.13
            longitude: -106.67
          - location_id: "ca_hrs_alberta"
            region: "Alberta"
            latitude: 52.27
            longitude: -113.81
          - location_id: "ca_hrs_manitoba"
            region: "Manitoba"
            latitude: 49.90
            longitude: -97.14

  soft_red_winter_wheat_cbot:
    description: "CBOT Soft Red Winter wheat weather universe: Eastern US SRW belt."
    countries:
      united_states:
        regions:
          - location_id: "us_srw_illinois"
            region: "Illinois"
            latitude: 40.63
            longitude: -89.40
          - location_id: "us_srw_missouri"
            region: "Missouri"
            latitude: 38.50
            longitude: -92.50
          - location_id: "us_srw_ohio"
            region: "Ohio"
            latitude: 40.42
            longitude: -82.91
          - location_id: "us_srw_indiana"
            region: "Indiana"
            latitude: 40.27
            longitude: -86.13
          - location_id: "us_srw_arkansas"
            region: "Arkansas"
            latitude: 34.75
            longitude: -92.29
          - location_id: "us_srw_kentucky"
            region: "Kentucky"
            latitude: 37.84
            longitude: -84.27
          - location_id: "us_srw_tennessee"
            region: "Tennessee"
            latitude: 35.86
            longitude: -86.66

  rough_rice_cbot:
    description: "CBOT Rough Rice weather universe: major US and global rice regions relevant to supply balance."
    countries:
      united_states:
        regions:
          - location_id: "us_rice_arkansas_delta"
            region: "Arkansas Delta"
            latitude: 35.05
            longitude: -90.75
          - location_id: "us_rice_louisiana"
            region: "Louisiana"
            latitude: 30.98
            longitude: -91.96
          - location_id: "us_rice_mississippi_delta"
            region: "Mississippi Delta"
            latitude: 33.45
            longitude: -90.65
          - location_id: "us_rice_texas_gulf_coast"
            region: "Texas Gulf Coast"
            latitude: 29.76
            longitude: -95.37
          - location_id: "us_rice_california_sacramento_valley"
            region: "California / Sacramento Valley"
            latitude: 39.50
            longitude: -121.75

      india:
        regions:
          - location_id: "in_rice_west_bengal"
            region: "West Bengal"
            latitude: 23.00
            longitude: 87.85
          - location_id: "in_rice_uttar_pradesh"
            region: "Uttar Pradesh"
            latitude: 26.85
            longitude: 80.95
          - location_id: "in_rice_punjab"
            region: "Punjab"
            latitude: 30.90
            longitude: 75.85
          - location_id: "in_rice_andhra_pradesh"
            region: "Andhra Pradesh"
            latitude: 15.91
            longitude: 79.74
          - location_id: "in_rice_telanganа"
            region: "Telangana"
            latitude: 18.11
            longitude: 79.02

      thailand:
        regions:
          - location_id: "th_rice_central_plain"
            region: "Central Plain"
            latitude: 14.35
            longitude: 100.57
          - location_id: "th_rice_northeast"
            region: "Northeast Thailand"
            latitude: 15.87
            longitude: 102.00

      vietnam:
        regions:
          - location_id: "vn_rice_mekong_delta"
            region: "Mekong Delta"
            latitude: 10.05
            longitude: 105.78
          - location_id: "vn_rice_red_river_delta"
            region: "Red River Delta"
            latitude: 20.97
            longitude: 105.84

  south_african_white_maize_jse:
    description: "JSE South African white maize weather universe: food maize belt."
    countries:
      south_africa:
        regions:
          - location_id: "za_white_maize_free_state"
            region: "Free State"
            latitude: -28.45
            longitude: 26.80
          - location_id: "za_white_maize_north_west"
            region: "North West"
            latitude: -26.66
            longitude: 25.28
          - location_id: "za_white_maize_mpumalanga"
            region: "Mpumalanga"
            latitude: -26.00
            longitude: 30.00
          - location_id: "za_white_maize_gauteng"
            region: "Gauteng"
            latitude: -26.27
            longitude: 28.11
          - location_id: "za_white_maize_limpopo"
            region: "Limpopo"
            latitude: -23.90
            longitude: 29.45

  south_african_yellow_maize_jse:
    description: "JSE South African yellow maize weather universe: feed maize belt."
    countries:
      south_africa:
        regions:
          - location_id: "za_yellow_maize_free_state"
            region: "Free State"
            latitude: -28.45
            longitude: 26.80
          - location_id: "za_yellow_maize_north_west"
            region: "North West"
            latitude: -26.66
            longitude: 25.28
          - location_id: "za_yellow_maize_mpumalanga"
            region: "Mpumalanga"
            latitude: -26.00
            longitude: 30.00
          - location_id: "za_yellow_maize_kwazulu_natal"
            region: "KwaZulu-Natal"
            latitude: -29.00
            longitude: 30.00
          - location_id: "za_yellow_maize_limpopo"
            region: "Limpopo"
            latitude: -23.90
            longitude: 29.45
```

---

# Copilot task prompt

Use this prompt in VS Code Copilot Chat:

```text
You are working in the Leviathan commodity data pipeline.

Read the file `grain_weather_locations.md` and the existing code in
jobs/glue/, src/leviathan/ingestion/weather/, and src/leviathan/transforms/.

This pipeline uses a three-layer medallion architecture: raw → bronze → silver.
  raw:    unmodified API JSON payloads on S3
  bronze: parsed, typed Parquet (one row per day per location)
  silver: cleaned, renamed, ML-ready Parquet

The standard S3 partition structure is:
  raw/weather/source=nasa_power/commodity={commodity}/country={country}/region={region}/year={year}/month={month}/payload.json
  bronze/weather/source=nasa_power/commodity={commodity}/country={country}/region={region}/year={year}/month={month}/part-000.parquet
  silver/weather/source=nasa_power/commodity={commodity}/country={country}/region={region}/year={year}/month={month}/part-000.parquet

Use the `location_id` value from the YAML as the `region` partition key.

Layer 1 — Ingestion (AWS Batch Fargate):
Follow the existing pattern in src/leviathan/ingestion/weather/nasa_power.py.
- Iterate over every commodity / country / region in the Location Universe YAML.
- Call the NASA POWER daily point API (parameters and base URL in configs/sources/nasa_power.yaml).
- Issue one request per (location, year) pair; date range 2010-01-01 to 2024-12-31.
- Write each raw JSON response to the raw layer path above (payload.json).
- Use tenacity for retries with exponential backoff (already bundled in the leviathan whl).
- Use BUCKET and AWS_REGION environment variables.

Layer 2 — Raw to Bronze (Glue Python Shell):
Extend jobs/glue/raw_to_bronze_nasa_power.py.
- Read raw JSON from the raw layer path above.
- Parse via src/leviathan/transforms/raw_to_bronze/nasa_power.py
  (nasa_power_payload_to_daily_dataframe — pass location_id as the region argument).
- Write Parquet to the bronze layer path above.
- Fixed filename part-000.parquet enables idempotent overwrite on rerun.

Layer 3 — Bronze to Silver (Glue Python Shell):
Extend jobs/glue/bronze_to_silver_nasa_power.py.
- Read all bronze Parquet files for the commodity (use pyarrow.dataset for parallel I/O).
- Apply the silver transform via src/leviathan/transforms/bronze_to_silver/nasa_power_weather.py
  (clean_one_weather_df).
- Silver output columns:
    date, year, month, day, country, region, commodity, source, ingest_date, source_file_name,
    temperature_2m_mean_c, temperature_2m_max_c, temperature_2m_min_c,
    precipitation_mm, relative_humidity_2m_pct, wind_speed_2m_m_s, solar_radiation_mj_m2_day
- Write Parquet to the silver layer path above.
- Fixed filename part-000.parquet enables idempotent overwrite on rerun.

Technical constraints:
- Use pandas and pyarrow — consistent with the existing pipeline.
- Use boto3 and requests — pre-installed in Glue Python Shell 3.9.
- Do NOT use polars, pyyaml, or any library not already in the leviathan whl.
- Do NOT skip the bronze layer — always ingest raw → transform to bronze → clean to silver.
- End year must not exceed 2024 (MAX_INGEST_YEAR guard in the ingestion code).
```
