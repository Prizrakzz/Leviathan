# NASA POWER Commodity Weather Location Universe

Purpose: this file defines the major weather-sensitive production regions for commodities that should be ingested from the NASA POWER API into S3.

Use this as the source-of-truth config for Copilot or your ingestion script.

Excluded: `polyester_staple_fiber` because it is not an agricultural/weather-driven commodity.

---

## General ingestion rules

Use the `location_id` value from the YAML as the `region` Hive partition key in S3.

Recommended S3 layout:

```text
raw/weather/source=nasa_power/commodity={commodity}/country={country}/region={region}/year={year}/month={month}/payload.json
bronze/weather/source=nasa_power/commodity={commodity}/country={country}/region={region}/year={year}/month={month}/part-000.parquet
silver/weather/source=nasa_power/commodity={commodity}/country={country}/region={region}/year={year}/month={month}/part-000.parquet
```

Note: `region` in the S3 path takes the `location_id` value from the YAML (e.g. `br_arabica_sul_de_minas`).
Fixed filename `part-000.parquet` enables idempotent overwrite on rerun.

Recommended date range for historical ML backfill:

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

  brazilian_arabica_coffee:
    description: "Brazil-specific Arabica coffee weather universe."
    countries:
      brazil:
        regions:
          - location_id: "br_arabica_sul_de_minas"
            region: "Minas Gerais / Sul de Minas"
            latitude: -21.55
            longitude: -45.43
          - location_id: "br_arabica_cerrado_mineiro"
            region: "Minas Gerais / Cerrado Mineiro"
            latitude: -18.94
            longitude: -46.99
          - location_id: "br_arabica_matas_de_minas"
            region: "Minas Gerais / Matas de Minas"
            latitude: -20.76
            longitude: -42.03
          - location_id: "br_arabica_sao_paulo_mogiana"
            region: "São Paulo / Mogiana"
            latitude: -20.54
            longitude: -47.40
          - location_id: "br_arabica_espirito_santo_highlands"
            region: "Espírito Santo / Arabica Highlands"
            latitude: -20.36
            longitude: -41.24
          - location_id: "br_arabica_bahia_chapada_diamantina"
            region: "Bahia / Chapada Diamantina"
            latitude: -13.00
            longitude: -41.37
          - location_id: "br_arabica_parana_norte_pioneiro"
            region: "Paraná / Norte Pioneiro"
            latitude: -23.16
            longitude: -50.07

  arabica_coffee:
    description: "Major Arabica coffee production regions."
    countries:
      brazil:
        regions:
          - location_id: "br_arabica_sul_de_minas"
            region: "Minas Gerais / Sul de Minas"
            latitude: -21.55
            longitude: -45.43
          - location_id: "br_arabica_cerrado_mineiro"
            region: "Minas Gerais / Cerrado Mineiro"
            latitude: -18.94
            longitude: -46.99
          - location_id: "br_arabica_sao_paulo_mogiana"
            region: "São Paulo / Mogiana"
            latitude: -20.54
            longitude: -47.40
          - location_id: "br_arabica_espirito_santo_highlands"
            region: "Espírito Santo / Arabica Highlands"
            latitude: -20.36
            longitude: -41.24
          - location_id: "br_arabica_bahia_chapada_diamantina"
            region: "Bahia / Chapada Diamantina"
            latitude: -13.00
            longitude: -41.37

      colombia:
        regions:
          - location_id: "co_arabica_antioquia"
            region: "Antioquia"
            latitude: 6.56
            longitude: -75.83
          - location_id: "co_arabica_huila"
            region: "Huila"
            latitude: 2.93
            longitude: -75.28
          - location_id: "co_arabica_tolima"
            region: "Tolima"
            latitude: 4.44
            longitude: -75.24
          - location_id: "co_arabica_cauca"
            region: "Cauca"
            latitude: 2.44
            longitude: -76.61
          - location_id: "co_arabica_caldas"
            region: "Caldas"
            latitude: 5.30
            longitude: -75.25
          - location_id: "co_arabica_risaralda"
            region: "Risaralda"
            latitude: 5.31
            longitude: -75.99
          - location_id: "co_arabica_quindio"
            region: "Quindío"
            latitude: 4.54
            longitude: -75.67
          - location_id: "co_arabica_narino"
            region: "Nariño"
            latitude: 1.29
            longitude: -77.36

      ethiopia:
        regions:
          - location_id: "et_arabica_sidama"
            region: "Sidama"
            latitude: 6.75
            longitude: 38.45
          - location_id: "et_arabica_yirgacheffe"
            region: "Yirgacheffe"
            latitude: 6.16
            longitude: 38.21
          - location_id: "et_arabica_jimma"
            region: "Jimma"
            latitude: 7.67
            longitude: 36.83
          - location_id: "et_arabica_limu"
            region: "Limu"
            latitude: 8.10
            longitude: 36.95
          - location_id: "et_arabica_harar"
            region: "Harar"
            latitude: 9.31
            longitude: 42.13
          - location_id: "et_arabica_guji"
            region: "Guji"
            latitude: 5.73
            longitude: 39.05

      honduras:
        regions:
          - location_id: "hn_arabica_copan"
            region: "Copán"
            latitude: 14.83
            longitude: -88.78
          - location_id: "hn_arabica_ocotepeque"
            region: "Ocotepeque"
            latitude: 14.44
            longitude: -89.18
          - location_id: "hn_arabica_santa_barbara"
            region: "Santa Bárbara"
            latitude: 14.92
            longitude: -88.24
          - location_id: "hn_arabica_el_paraiso"
            region: "El Paraíso"
            latitude: 13.86
            longitude: -86.55
          - location_id: "hn_arabica_marcala_la_paz"
            region: "Marcala / La Paz"
            latitude: 14.15
            longitude: -88.03

      peru:
        regions:
          - location_id: "pe_arabica_cajamarca"
            region: "Cajamarca"
            latitude: -6.56
            longitude: -78.65
          - location_id: "pe_arabica_junin"
            region: "Junín"
            latitude: -11.15
            longitude: -75.35
          - location_id: "pe_arabica_san_martin"
            region: "San Martín"
            latitude: -6.50
            longitude: -76.50
          - location_id: "pe_arabica_cusco"
            region: "Cusco"
            latitude: -13.52
            longitude: -71.97
          - location_id: "pe_arabica_amazonas"
            region: "Amazonas"
            latitude: -5.07
            longitude: -78.05

  robusta_coffee:
    description: "Major Robusta coffee production regions."
    countries:
      vietnam:
        regions:
          - location_id: "vn_robusta_dak_lak_buon_ma_thuot"
            region: "Đắk Lắk / Buôn Ma Thuột"
            latitude: 12.67
            longitude: 108.05
          - location_id: "vn_robusta_lam_dong_bao_loc"
            region: "Lâm Đồng / Bảo Lộc"
            latitude: 11.55
            longitude: 107.80
          - location_id: "vn_robusta_gia_lai_pleiku"
            region: "Gia Lai / Pleiku"
            latitude: 13.98
            longitude: 108.00
          - location_id: "vn_robusta_dak_nong"
            region: "Đắk Nông"
            latitude: 12.00
            longitude: 107.70
          - location_id: "vn_robusta_kon_tum"
            region: "Kon Tum"
            latitude: 14.35
            longitude: 108.00

      brazil:
        regions:
          - location_id: "br_robusta_espirito_santo_conilon"
            region: "Espírito Santo / Conilon"
            latitude: -19.15
            longitude: -40.08
          - location_id: "br_robusta_bahia_conilon"
            region: "Bahia / Conilon"
            latitude: -14.86
            longitude: -40.84
          - location_id: "br_robusta_rondonia"
            region: "Rondônia"
            latitude: -10.88
            longitude: -61.95
          - location_id: "br_robusta_minas_matas"
            region: "Minas Gerais / Robusta Matas"
            latitude: -20.76
            longitude: -42.03

      indonesia:
        regions:
          - location_id: "id_robusta_lampung_south_sumatra"
            region: "Lampung / South Sumatra"
            latitude: -5.45
            longitude: 105.27
          - location_id: "id_robusta_west_sumatra"
            region: "West Sumatra"
            latitude: -0.95
            longitude: 100.35
          - location_id: "id_robusta_east_java"
            region: "East Java"
            latitude: -7.54
            longitude: 112.24
          - location_id: "id_robusta_west_java"
            region: "West Java"
            latitude: -6.90
            longitude: 107.60
          - location_id: "id_robusta_south_sulawesi"
            region: "South Sulawesi"
            latitude: -4.50
            longitude: 120.00

      uganda:
        regions:
          - location_id: "ug_robusta_central"
            region: "Central Region"
            latitude: 0.35
            longitude: 32.58
          - location_id: "ug_robusta_western"
            region: "Western Region"
            latitude: 0.65
            longitude: 30.27
          - location_id: "ug_robusta_eastern"
            region: "Eastern Region"
            latitude: 1.06
            longitude: 34.18

      india:
        regions:
          - location_id: "in_robusta_karnataka"
            region: "Karnataka"
            latitude: 12.42
            longitude: 75.74
          - location_id: "in_robusta_kerala"
            region: "Kerala"
            latitude: 10.85
            longitude: 76.27
          - location_id: "in_robusta_tamil_nadu"
            region: "Tamil Nadu"
            latitude: 11.13
            longitude: 78.66

  cotton:
    description: "Major cotton production regions."
    countries:
      china:
        regions:
          - location_id: "cn_cotton_xinjiang"
            region: "Xinjiang"
            latitude: 41.76
            longitude: 86.15

      india:
        regions:
          - location_id: "in_cotton_gujarat"
            region: "Gujarat"
            latitude: 22.26
            longitude: 71.19
          - location_id: "in_cotton_maharashtra"
            region: "Maharashtra"
            latitude: 19.75
            longitude: 75.71
          - location_id: "in_cotton_telangana"
            region: "Telangana"
            latitude: 18.11
            longitude: 79.02
          - location_id: "in_cotton_rajasthan"
            region: "Rajasthan"
            latitude: 26.91
            longitude: 75.79
          - location_id: "in_cotton_madhya_pradesh"
            region: "Madhya Pradesh"
            latitude: 22.97
            longitude: 78.66
          - location_id: "in_cotton_andhra_pradesh"
            region: "Andhra Pradesh"
            latitude: 15.91
            longitude: 79.74

      brazil:
        regions:
          - location_id: "br_cotton_mato_grosso"
            region: "Mato Grosso"
            latitude: -12.64
            longitude: -55.42
          - location_id: "br_cotton_bahia"
            region: "Bahia"
            latitude: -12.58
            longitude: -41.70
          - location_id: "br_cotton_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14
          - location_id: "br_cotton_minas_gerais"
            region: "Minas Gerais"
            latitude: -18.10
            longitude: -44.38

      united_states:
        regions:
          - location_id: "us_cotton_texas_high_plains"
            region: "Texas High Plains"
            latitude: 33.58
            longitude: -101.85
          - location_id: "us_cotton_texas_rolling_plains"
            region: "Texas Rolling Plains"
            latitude: 32.45
            longitude: -99.73
          - location_id: "us_cotton_georgia"
            region: "Georgia"
            latitude: 32.17
            longitude: -82.90
          - location_id: "us_cotton_mississippi_delta"
            region: "Mississippi Delta"
            latitude: 33.45
            longitude: -90.65
          - location_id: "us_cotton_arkansas_delta"
            region: "Arkansas Delta"
            latitude: 35.05
            longitude: -90.75
          - location_id: "us_cotton_california_san_joaquin"
            region: "California / San Joaquin Valley"
            latitude: 36.74
            longitude: -119.77

      pakistan:
        regions:
          - location_id: "pk_cotton_punjab"
            region: "Punjab"
            latitude: 30.37
            longitude: 71.52
          - location_id: "pk_cotton_sindh"
            region: "Sindh"
            latitude: 26.30
            longitude: 68.63

  raw_sugar:
    description: "Major raw sugar cane production and export-relevant regions."
    countries:
      brazil:
        regions:
          - location_id: "br_sugar_sao_paulo"
            region: "São Paulo"
            latitude: -21.29
            longitude: -48.18
          - location_id: "br_sugar_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14
          - location_id: "br_sugar_minas_gerais"
            region: "Minas Gerais"
            latitude: -18.10
            longitude: -44.38
          - location_id: "br_sugar_parana"
            region: "Paraná"
            latitude: -24.89
            longitude: -51.55
          - location_id: "br_sugar_mato_grosso_do_sul"
            region: "Mato Grosso do Sul"
            latitude: -20.51
            longitude: -54.54

      india:
        regions:
          - location_id: "in_sugar_uttar_pradesh"
            region: "Uttar Pradesh"
            latitude: 26.85
            longitude: 80.95
          - location_id: "in_sugar_maharashtra"
            region: "Maharashtra"
            latitude: 19.75
            longitude: 75.71
          - location_id: "in_sugar_karnataka"
            region: "Karnataka"
            latitude: 15.32
            longitude: 75.71

      thailand:
        regions:
          - location_id: "th_sugar_northeast"
            region: "Northeast Thailand"
            latitude: 15.87
            longitude: 102.00
          - location_id: "th_sugar_central"
            region: "Central Thailand"
            latitude: 14.35
            longitude: 100.57
          - location_id: "th_sugar_kanchanaburi"
            region: "Kanchanaburi"
            latitude: 14.02
            longitude: 99.53
          - location_id: "th_sugar_nakhon_sawan"
            region: "Nakhon Sawan"
            latitude: 15.70
            longitude: 100.12

      china:
        regions:
          - location_id: "cn_sugar_guangxi"
            region: "Guangxi"
            latitude: 23.83
            longitude: 108.32
          - location_id: "cn_sugar_yunnan"
            region: "Yunnan"
            latitude: 24.88
            longitude: 102.83
          - location_id: "cn_sugar_guangdong"
            region: "Guangdong"
            latitude: 23.13
            longitude: 113.26

      australia:
        regions:
          - location_id: "au_sugar_queensland"
            region: "Queensland"
            latitude: -19.26
            longitude: 146.82
          - location_id: "au_sugar_northern_new_south_wales"
            region: "Northern New South Wales"
            latitude: -29.43
            longitude: 153.35

  white_sugar:
    description: "Major white sugar regions: cane and beet sugar."
    countries:
      india:
        regions:
          - location_id: "in_sugar_uttar_pradesh"
            region: "Uttar Pradesh"
            latitude: 26.85
            longitude: 80.95
          - location_id: "in_sugar_maharashtra"
            region: "Maharashtra"
            latitude: 19.75
            longitude: 75.71
          - location_id: "in_sugar_karnataka"
            region: "Karnataka"
            latitude: 15.32
            longitude: 75.71

      european_union:
        regions:
          - location_id: "eu_sugar_france_hauts_de_france"
            region: "France / Hauts-de-France"
            latitude: 50.48
            longitude: 2.79
          - location_id: "eu_sugar_france_grand_est"
            region: "France / Grand Est"
            latitude: 48.70
            longitude: 6.18
          - location_id: "eu_sugar_germany_lower_saxony"
            region: "Germany / Lower Saxony"
            latitude: 52.64
            longitude: 9.84
          - location_id: "eu_sugar_germany_nrw"
            region: "Germany / North Rhine-Westphalia"
            latitude: 51.43
            longitude: 7.66
          - location_id: "eu_sugar_poland_wielkopolskie"
            region: "Poland / Wielkopolskie"
            latitude: 52.40
            longitude: 16.93
          - location_id: "eu_sugar_netherlands_flevoland"
            region: "Netherlands / Flevoland"
            latitude: 52.53
            longitude: 5.60

      china:
        regions:
          - location_id: "cn_sugar_guangxi"
            region: "Guangxi"
            latitude: 23.83
            longitude: 108.32
          - location_id: "cn_sugar_yunnan"
            region: "Yunnan"
            latitude: 24.88
            longitude: 102.83
          - location_id: "cn_sugar_guangdong"
            region: "Guangdong"
            latitude: 23.13
            longitude: 113.26

      thailand:
        regions:
          - location_id: "th_sugar_northeast"
            region: "Northeast Thailand"
            latitude: 15.87
            longitude: 102.00
          - location_id: "th_sugar_central"
            region: "Central Thailand"
            latitude: 14.35
            longitude: 100.57

      united_states:
        regions:
          - location_id: "us_sugar_red_river_valley"
            region: "Minnesota / North Dakota Red River Valley"
            latitude: 47.92
            longitude: -97.03
          - location_id: "us_sugar_michigan"
            region: "Michigan"
            latitude: 43.62
            longitude: -84.68
          - location_id: "us_sugar_idaho"
            region: "Idaho"
            latitude: 43.62
            longitude: -116.20
          - location_id: "us_sugar_louisiana"
            region: "Louisiana"
            latitude: 30.98
            longitude: -91.96
          - location_id: "us_sugar_florida"
            region: "Florida"
            latitude: 26.65
            longitude: -80.70

  frozen_orange_juice:
    description: "Major orange juice production regions."
    countries:
      brazil:
        regions:
          - location_id: "br_orange_sao_paulo_citrus_belt"
            region: "São Paulo Citrus Belt"
            latitude: -21.29
            longitude: -48.18
          - location_id: "br_orange_minas_gerais_triangulo"
            region: "Minas Gerais / Triângulo Mineiro"
            latitude: -19.75
            longitude: -47.93
          - location_id: "br_orange_parana_northwest"
            region: "Paraná / Northwest"
            latitude: -23.42
            longitude: -51.93

      united_states:
        regions:
          - location_id: "us_orange_florida_central_ridge"
            region: "Florida / Central Ridge"
            latitude: 27.90
            longitude: -81.59
          - location_id: "us_orange_florida_indian_river"
            region: "Florida / Indian River"
            latitude: 27.64
            longitude: -80.40
          - location_id: "us_orange_florida_southwest"
            region: "Florida / Southwest"
            latitude: 26.64
            longitude: -81.87

      mexico:
        regions:
          - location_id: "mx_orange_veracruz"
            region: "Veracruz"
            latitude: 19.17
            longitude: -96.13
          - location_id: "mx_orange_tamaulipas"
            region: "Tamaulipas"
            latitude: 23.74
            longitude: -99.14
          - location_id: "mx_orange_san_luis_potosi"
            region: "San Luis Potosí"
            latitude: 22.16
            longitude: -100.99
          - location_id: "mx_orange_nuevo_leon"
            region: "Nuevo León"
            latitude: 25.68
            longitude: -100.32

      european_union:
        regions:
          - location_id: "eu_orange_spain_valencia"
            region: "Spain / Valencia"
            latitude: 39.47
            longitude: -0.38
          - location_id: "eu_orange_spain_andalusia"
            region: "Spain / Andalusia"
            latitude: 37.39
            longitude: -5.99
          - location_id: "eu_orange_italy_sicily"
            region: "Italy / Sicily"
            latitude: 37.60
            longitude: 14.02
          - location_id: "eu_orange_italy_calabria"
            region: "Italy / Calabria"
            latitude: 39.31
            longitude: 16.25
```

---

# Copilot task prompt

Use this prompt in VS Code Copilot Chat:

```text
You are working in the Leviathan commodity data pipeline.

Read the file `Softs_weather locations.md` and the existing code in
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
