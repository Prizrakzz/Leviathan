# NASA POWER Oilseeds Weather Location Universe

Purpose: this file defines the major weather-sensitive production regions for oilseed futures, oilseed meals, and vegetable oil reference contracts that should be ingested from the NASA POWER API into S3.

Contracts covered from the screenshot:

- Soybean Meal (DCE)
- Soybeans No. 1 (DCE)
- Soybean Oil (CBOT)
- Soybeans No. 2 (DCE)
- Soybean Meal (CBOT)
- French Rapeseed (MATIF)
- Malaysian Crude Palm Oil (CME)
- Palm Olein (DCE)
- Canola (ICE)
- Soybeans (CBOT)
- Soybean Oil (DCE)
- Rapeseed Oil (ZCE)
- Rapeseed Meal (ZCE)

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

Note: `region` in the S3 path takes the `location_id` value from the YAML (e.g. `br_soy_mato_grosso`).
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

  soybeans_cbot:
    description: "CBOT soybeans weather universe: major soybean-producing and export-relevant regions."
    countries:
      united_states:
        regions:
          - location_id: "us_soy_iowa"
            region: "Iowa"
            latitude: 42.03
            longitude: -93.64
          - location_id: "us_soy_illinois"
            region: "Illinois"
            latitude: 40.63
            longitude: -89.40
          - location_id: "us_soy_minnesota"
            region: "Minnesota"
            latitude: 46.73
            longitude: -94.69
          - location_id: "us_soy_indiana"
            region: "Indiana"
            latitude: 40.27
            longitude: -86.13
          - location_id: "us_soy_nebraska"
            region: "Nebraska"
            latitude: 41.50
            longitude: -99.68
          - location_id: "us_soy_missouri"
            region: "Missouri"
            latitude: 38.50
            longitude: -92.50
          - location_id: "us_soy_ohio"
            region: "Ohio"
            latitude: 40.42
            longitude: -82.91
          - location_id: "us_soy_south_dakota"
            region: "South Dakota"
            latitude: 44.50
            longitude: -100.00
          - location_id: "us_soy_north_dakota"
            region: "North Dakota"
            latitude: 47.55
            longitude: -100.47
          - location_id: "us_soy_arkansas_delta"
            region: "Arkansas Delta"
            latitude: 35.05
            longitude: -90.75

      brazil:
        regions:
          - location_id: "br_soy_mato_grosso"
            region: "Mato Grosso"
            latitude: -12.64
            longitude: -55.42
          - location_id: "br_soy_parana"
            region: "Paraná"
            latitude: -24.89
            longitude: -51.55
          - location_id: "br_soy_rio_grande_do_sul"
            region: "Rio Grande do Sul"
            latitude: -30.03
            longitude: -51.23
          - location_id: "br_soy_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14
          - location_id: "br_soy_mato_grosso_do_sul"
            region: "Mato Grosso do Sul"
            latitude: -20.51
            longitude: -54.54
          - location_id: "br_soy_minas_gerais"
            region: "Minas Gerais"
            latitude: -18.10
            longitude: -44.38
          - location_id: "br_soy_bahia_west"
            region: "Bahia / West"
            latitude: -12.15
            longitude: -45.00
          - location_id: "br_soy_maranhao_matopiba"
            region: "Maranhão / MATOPIBA"
            latitude: -7.00
            longitude: -45.00
          - location_id: "br_soy_piaui_matopiba"
            region: "Piauí / MATOPIBA"
            latitude: -7.72
            longitude: -42.73
          - location_id: "br_soy_tocantins_matopiba"
            region: "Tocantins / MATOPIBA"
            latitude: -10.25
            longitude: -48.25

      argentina:
        regions:
          - location_id: "ar_soy_buenos_aires"
            region: "Buenos Aires"
            latitude: -36.68
            longitude: -60.56
          - location_id: "ar_soy_cordoba"
            region: "Córdoba"
            latitude: -31.42
            longitude: -64.18
          - location_id: "ar_soy_santa_fe"
            region: "Santa Fe"
            latitude: -31.63
            longitude: -60.70
          - location_id: "ar_soy_entre_rios"
            region: "Entre Ríos"
            latitude: -31.77
            longitude: -60.52
          - location_id: "ar_soy_santiago_del_estero"
            region: "Santiago del Estero"
            latitude: -27.78
            longitude: -64.26

      paraguay:
        regions:
          - location_id: "py_soy_alto_parana"
            region: "Alto Paraná"
            latitude: -25.50
            longitude: -54.75
          - location_id: "py_soy_itapua"
            region: "Itapúa"
            latitude: -27.33
            longitude: -55.90
          - location_id: "py_soy_canindeyu"
            region: "Canindeyú"
            latitude: -24.25
            longitude: -55.10

  soybean_meal_cbot:
    description: "CBOT soybean meal weather universe: driven by soybean crop supply in major soybean origins."
    countries:
      united_states:
        regions:
          - location_id: "us_soy_iowa"
            region: "Iowa"
            latitude: 42.03
            longitude: -93.64
          - location_id: "us_soy_illinois"
            region: "Illinois"
            latitude: 40.63
            longitude: -89.40
          - location_id: "us_soy_minnesota"
            region: "Minnesota"
            latitude: 46.73
            longitude: -94.69
          - location_id: "us_soy_indiana"
            region: "Indiana"
            latitude: 40.27
            longitude: -86.13
          - location_id: "us_soy_nebraska"
            region: "Nebraska"
            latitude: 41.50
            longitude: -99.68
          - location_id: "us_soy_missouri"
            region: "Missouri"
            latitude: 38.50
            longitude: -92.50

      brazil:
        regions:
          - location_id: "br_soy_mato_grosso"
            region: "Mato Grosso"
            latitude: -12.64
            longitude: -55.42
          - location_id: "br_soy_parana"
            region: "Paraná"
            latitude: -24.89
            longitude: -51.55
          - location_id: "br_soy_rio_grande_do_sul"
            region: "Rio Grande do Sul"
            latitude: -30.03
            longitude: -51.23
          - location_id: "br_soy_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14
          - location_id: "br_soy_mato_grosso_do_sul"
            region: "Mato Grosso do Sul"
            latitude: -20.51
            longitude: -54.54

      argentina:
        regions:
          - location_id: "ar_soy_buenos_aires"
            region: "Buenos Aires"
            latitude: -36.68
            longitude: -60.56
          - location_id: "ar_soy_cordoba"
            region: "Córdoba"
            latitude: -31.42
            longitude: -64.18
          - location_id: "ar_soy_santa_fe"
            region: "Santa Fe"
            latitude: -31.63
            longitude: -60.70
          - location_id: "ar_soy_entre_rios"
            region: "Entre Ríos"
            latitude: -31.77
            longitude: -60.52

  soybean_oil_cbot:
    description: "CBOT soybean oil weather universe: driven by soybean crop supply in major soybean origins."
    countries:
      united_states:
        regions:
          - location_id: "us_soy_iowa"
            region: "Iowa"
            latitude: 42.03
            longitude: -93.64
          - location_id: "us_soy_illinois"
            region: "Illinois"
            latitude: 40.63
            longitude: -89.40
          - location_id: "us_soy_minnesota"
            region: "Minnesota"
            latitude: 46.73
            longitude: -94.69
          - location_id: "us_soy_indiana"
            region: "Indiana"
            latitude: 40.27
            longitude: -86.13
          - location_id: "us_soy_nebraska"
            region: "Nebraska"
            latitude: 41.50
            longitude: -99.68
          - location_id: "us_soy_missouri"
            region: "Missouri"
            latitude: 38.50
            longitude: -92.50

      brazil:
        regions:
          - location_id: "br_soy_mato_grosso"
            region: "Mato Grosso"
            latitude: -12.64
            longitude: -55.42
          - location_id: "br_soy_parana"
            region: "Paraná"
            latitude: -24.89
            longitude: -51.55
          - location_id: "br_soy_rio_grande_do_sul"
            region: "Rio Grande do Sul"
            latitude: -30.03
            longitude: -51.23
          - location_id: "br_soy_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14
          - location_id: "br_soy_mato_grosso_do_sul"
            region: "Mato Grosso do Sul"
            latitude: -20.51
            longitude: -54.54

      argentina:
        regions:
          - location_id: "ar_soy_buenos_aires"
            region: "Buenos Aires"
            latitude: -36.68
            longitude: -60.56
          - location_id: "ar_soy_cordoba"
            region: "Córdoba"
            latitude: -31.42
            longitude: -64.18
          - location_id: "ar_soy_santa_fe"
            region: "Santa Fe"
            latitude: -31.63
            longitude: -60.70
          - location_id: "ar_soy_entre_rios"
            region: "Entre Ríos"
            latitude: -31.77
            longitude: -60.52

  soybeans_no_1_dce:
    description: "DCE Soybeans No. 1: China non-GMO/domestic soybean weather universe."
    countries:
      china:
        regions:
          - location_id: "cn_soy_heilongjiang"
            region: "Heilongjiang"
            latitude: 47.86
            longitude: 127.76
          - location_id: "cn_soy_jilin"
            region: "Jilin"
            latitude: 43.90
            longitude: 125.32
          - location_id: "cn_soy_inner_mongolia"
            region: "Inner Mongolia"
            latitude: 43.65
            longitude: 112.00
          - location_id: "cn_soy_liaoning"
            region: "Liaoning"
            latitude: 41.84
            longitude: 123.43
          - location_id: "cn_soy_henan"
            region: "Henan"
            latitude: 34.76
            longitude: 113.65
          - location_id: "cn_soy_shandong"
            region: "Shandong"
            latitude: 36.65
            longitude: 117.12
          - location_id: "cn_soy_anhui"
            region: "Anhui"
            latitude: 31.86
            longitude: 117.28

  soybeans_no_2_dce:
    description: "DCE Soybeans No. 2: imported soybeans; track major export origins plus China arrival-demand context."
    countries:
      brazil:
        regions:
          - location_id: "br_soy_mato_grosso"
            region: "Mato Grosso"
            latitude: -12.64
            longitude: -55.42
          - location_id: "br_soy_parana"
            region: "Paraná"
            latitude: -24.89
            longitude: -51.55
          - location_id: "br_soy_rio_grande_do_sul"
            region: "Rio Grande do Sul"
            latitude: -30.03
            longitude: -51.23
          - location_id: "br_soy_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14
          - location_id: "br_soy_mato_grosso_do_sul"
            region: "Mato Grosso do Sul"
            latitude: -20.51
            longitude: -54.54
          - location_id: "br_soy_bahia_west"
            region: "Bahia / West"
            latitude: -12.15
            longitude: -45.00

      united_states:
        regions:
          - location_id: "us_soy_iowa"
            region: "Iowa"
            latitude: 42.03
            longitude: -93.64
          - location_id: "us_soy_illinois"
            region: "Illinois"
            latitude: 40.63
            longitude: -89.40
          - location_id: "us_soy_minnesota"
            region: "Minnesota"
            latitude: 46.73
            longitude: -94.69
          - location_id: "us_soy_indiana"
            region: "Indiana"
            latitude: 40.27
            longitude: -86.13
          - location_id: "us_soy_nebraska"
            region: "Nebraska"
            latitude: 41.50
            longitude: -99.68

      argentina:
        regions:
          - location_id: "ar_soy_buenos_aires"
            region: "Buenos Aires"
            latitude: -36.68
            longitude: -60.56
          - location_id: "ar_soy_cordoba"
            region: "Córdoba"
            latitude: -31.42
            longitude: -64.18
          - location_id: "ar_soy_santa_fe"
            region: "Santa Fe"
            latitude: -31.63
            longitude: -60.70

  soybean_meal_dce:
    description: "DCE soybean meal: imported soybean supply plus domestic China crushing context."
    countries:
      brazil:
        regions:
          - location_id: "br_soy_mato_grosso"
            region: "Mato Grosso"
            latitude: -12.64
            longitude: -55.42
          - location_id: "br_soy_parana"
            region: "Paraná"
            latitude: -24.89
            longitude: -51.55
          - location_id: "br_soy_rio_grande_do_sul"
            region: "Rio Grande do Sul"
            latitude: -30.03
            longitude: -51.23
          - location_id: "br_soy_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14

      united_states:
        regions:
          - location_id: "us_soy_iowa"
            region: "Iowa"
            latitude: 42.03
            longitude: -93.64
          - location_id: "us_soy_illinois"
            region: "Illinois"
            latitude: 40.63
            longitude: -89.40
          - location_id: "us_soy_minnesota"
            region: "Minnesota"
            latitude: 46.73
            longitude: -94.69
          - location_id: "us_soy_indiana"
            region: "Indiana"
            latitude: 40.27
            longitude: -86.13

      argentina:
        regions:
          - location_id: "ar_soy_buenos_aires"
            region: "Buenos Aires"
            latitude: -36.68
            longitude: -60.56
          - location_id: "ar_soy_cordoba"
            region: "Córdoba"
            latitude: -31.42
            longitude: -64.18
          - location_id: "ar_soy_santa_fe"
            region: "Santa Fe"
            latitude: -31.63
            longitude: -60.70

      china:
        regions:
          - location_id: "cn_soy_heilongjiang"
            region: "Heilongjiang"
            latitude: 47.86
            longitude: 127.76
          - location_id: "cn_soy_jilin"
            region: "Jilin"
            latitude: 43.90
            longitude: 125.32
          - location_id: "cn_soy_inner_mongolia"
            region: "Inner Mongolia"
            latitude: 43.65
            longitude: 112.00

  soybean_oil_dce:
    description: "DCE soybean oil: imported soybean supply plus domestic China crushing context."
    countries:
      brazil:
        regions:
          - location_id: "br_soy_mato_grosso"
            region: "Mato Grosso"
            latitude: -12.64
            longitude: -55.42
          - location_id: "br_soy_parana"
            region: "Paraná"
            latitude: -24.89
            longitude: -51.55
          - location_id: "br_soy_rio_grande_do_sul"
            region: "Rio Grande do Sul"
            latitude: -30.03
            longitude: -51.23
          - location_id: "br_soy_goias"
            region: "Goiás"
            latitude: -15.93
            longitude: -50.14

      united_states:
        regions:
          - location_id: "us_soy_iowa"
            region: "Iowa"
            latitude: 42.03
            longitude: -93.64
          - location_id: "us_soy_illinois"
            region: "Illinois"
            latitude: 40.63
            longitude: -89.40
          - location_id: "us_soy_minnesota"
            region: "Minnesota"
            latitude: 46.73
            longitude: -94.69
          - location_id: "us_soy_indiana"
            region: "Indiana"
            latitude: 40.27
            longitude: -86.13

      argentina:
        regions:
          - location_id: "ar_soy_buenos_aires"
            region: "Buenos Aires"
            latitude: -36.68
            longitude: -60.56
          - location_id: "ar_soy_cordoba"
            region: "Córdoba"
            latitude: -31.42
            longitude: -64.18
          - location_id: "ar_soy_santa_fe"
            region: "Santa Fe"
            latitude: -31.63
            longitude: -60.70

      china:
        regions:
          - location_id: "cn_soy_heilongjiang"
            region: "Heilongjiang"
            latitude: 47.86
            longitude: 127.76
          - location_id: "cn_soy_jilin"
            region: "Jilin"
            latitude: 43.90
            longitude: 125.32
          - location_id: "cn_soy_inner_mongolia"
            region: "Inner Mongolia"
            latitude: 43.65
            longitude: 112.00

  french_rapeseed_matif:
    description: "MATIF French rapeseed weather universe: French and EU rapeseed/canola production regions."
    countries:
      france:
        regions:
          - location_id: "fr_rapeseed_centre_val_de_loire"
            region: "Centre-Val de Loire"
            latitude: 47.75
            longitude: 1.68
          - location_id: "fr_rapeseed_grand_est"
            region: "Grand Est"
            latitude: 48.70
            longitude: 6.18
          - location_id: "fr_rapeseed_bourgogne_franche_comte"
            region: "Bourgogne-Franche-Comté"
            latitude: 47.28
            longitude: 4.99
          - location_id: "fr_rapeseed_hauts_de_france"
            region: "Hauts-de-France"
            latitude: 50.48
            longitude: 2.79
          - location_id: "fr_rapeseed_normandy"
            region: "Normandy"
            latitude: 49.18
            longitude: 0.37

      germany:
        regions:
          - location_id: "de_rapeseed_mecklenburg_vorpommern"
            region: "Mecklenburg-Vorpommern"
            latitude: 53.61
            longitude: 12.43
          - location_id: "de_rapeseed_saxony_anhalt"
            region: "Saxony-Anhalt"
            latitude: 51.95
            longitude: 11.69
          - location_id: "de_rapeseed_lower_saxony"
            region: "Lower Saxony"
            latitude: 52.64
            longitude: 9.84
          - location_id: "de_rapeseed_schleswig_holstein"
            region: "Schleswig-Holstein"
            latitude: 54.22
            longitude: 9.70

      poland:
        regions:
          - location_id: "pl_rapeseed_wielkopolskie"
            region: "Wielkopolskie"
            latitude: 52.40
            longitude: 16.93
          - location_id: "pl_rapeseed_dolnoslaskie"
            region: "Dolnośląskie"
            latitude: 51.11
            longitude: 17.03
          - location_id: "pl_rapeseed_kujawsko_pomorskie"
            region: "Kujawsko-Pomorskie"
            latitude: 53.12
            longitude: 18.00

      ukraine:
        regions:
          - location_id: "ua_rapeseed_vinnytsia"
            region: "Vinnytsia"
            latitude: 49.23
            longitude: 28.48
          - location_id: "ua_rapeseed_odesa"
            region: "Odesa"
            latitude: 46.48
            longitude: 30.73
          - location_id: "ua_rapeseed_lviv"
            region: "Lviv"
            latitude: 49.84
            longitude: 24.03
          - location_id: "ua_rapeseed_khmelnytskyi"
            region: "Khmelnytskyi"
            latitude: 49.42
            longitude: 26.98

  canola_ice:
    description: "ICE canola weather universe: Canadian canola belt plus Australia as export-relevant canola origin."
    countries:
      canada:
        regions:
          - location_id: "ca_canola_saskatchewan"
            region: "Saskatchewan"
            latitude: 52.13
            longitude: -106.67
          - location_id: "ca_canola_alberta"
            region: "Alberta"
            latitude: 52.27
            longitude: -113.81
          - location_id: "ca_canola_manitoba"
            region: "Manitoba"
            latitude: 49.90
            longitude: -97.14
          - location_id: "ca_canola_peace_river"
            region: "Peace River"
            latitude: 56.23
            longitude: -117.29

      australia:
        regions:
          - location_id: "au_canola_western_australia"
            region: "Western Australia Wheatbelt"
            latitude: -31.65
            longitude: 117.24
          - location_id: "au_canola_new_south_wales"
            region: "New South Wales"
            latitude: -34.50
            longitude: 147.50
          - location_id: "au_canola_victoria"
            region: "Victoria"
            latitude: -36.85
            longitude: 144.28
          - location_id: "au_canola_south_australia"
            region: "South Australia"
            latitude: -34.93
            longitude: 138.60

  rapeseed_oil_zce:
    description: "ZCE rapeseed oil: China domestic rapeseed regions plus major import-relevant origins."
    countries:
      china:
        regions:
          - location_id: "cn_rapeseed_hubei"
            region: "Hubei"
            latitude: 30.59
            longitude: 114.30
          - location_id: "cn_rapeseed_hunan"
            region: "Hunan"
            latitude: 28.23
            longitude: 112.94
          - location_id: "cn_rapeseed_sichuan"
            region: "Sichuan"
            latitude: 30.65
            longitude: 104.07
          - location_id: "cn_rapeseed_anhui"
            region: "Anhui"
            latitude: 31.86
            longitude: 117.28
          - location_id: "cn_rapeseed_jiangsu"
            region: "Jiangsu"
            latitude: 32.06
            longitude: 118.78
          - location_id: "cn_rapeseed_jiangxi"
            region: "Jiangxi"
            latitude: 28.67
            longitude: 115.91
          - location_id: "cn_rapeseed_henan"
            region: "Henan"
            latitude: 34.76
            longitude: 113.65

      canada:
        regions:
          - location_id: "ca_canola_saskatchewan"
            region: "Saskatchewan"
            latitude: 52.13
            longitude: -106.67
          - location_id: "ca_canola_alberta"
            region: "Alberta"
            latitude: 52.27
            longitude: -113.81
          - location_id: "ca_canola_manitoba"
            region: "Manitoba"
            latitude: 49.90
            longitude: -97.14

      european_union:
        regions:
          - location_id: "fr_rapeseed_centre_val_de_loire"
            region: "France / Centre-Val de Loire"
            latitude: 47.75
            longitude: 1.68
          - location_id: "de_rapeseed_mecklenburg_vorpommern"
            region: "Germany / Mecklenburg-Vorpommern"
            latitude: 53.61
            longitude: 12.43
          - location_id: "pl_rapeseed_wielkopolskie"
            region: "Poland / Wielkopolskie"
            latitude: 52.40
            longitude: 16.93

  rapeseed_meal_zce:
    description: "ZCE rapeseed meal: China domestic rapeseed regions plus major import-relevant origins."
    countries:
      china:
        regions:
          - location_id: "cn_rapeseed_hubei"
            region: "Hubei"
            latitude: 30.59
            longitude: 114.30
          - location_id: "cn_rapeseed_hunan"
            region: "Hunan"
            latitude: 28.23
            longitude: 112.94
          - location_id: "cn_rapeseed_sichuan"
            region: "Sichuan"
            latitude: 30.65
            longitude: 104.07
          - location_id: "cn_rapeseed_anhui"
            region: "Anhui"
            latitude: 31.86
            longitude: 117.28
          - location_id: "cn_rapeseed_jiangsu"
            region: "Jiangsu"
            latitude: 32.06
            longitude: 118.78
          - location_id: "cn_rapeseed_jiangxi"
            region: "Jiangxi"
            latitude: 28.67
            longitude: 115.91
          - location_id: "cn_rapeseed_henan"
            region: "Henan"
            latitude: 34.76
            longitude: 113.65

      canada:
        regions:
          - location_id: "ca_canola_saskatchewan"
            region: "Saskatchewan"
            latitude: 52.13
            longitude: -106.67
          - location_id: "ca_canola_alberta"
            region: "Alberta"
            latitude: 52.27
            longitude: -113.81
          - location_id: "ca_canola_manitoba"
            region: "Manitoba"
            latitude: 49.90
            longitude: -97.14

  malaysian_crude_palm_oil_cme:
    description: "Malaysian crude palm oil weather universe: Malaysia core palm belt plus Indonesia as global palm supply context."
    countries:
      malaysia:
        regions:
          - location_id: "my_palm_sabah"
            region: "Sabah"
            latitude: 5.98
            longitude: 116.08
          - location_id: "my_palm_sarawak"
            region: "Sarawak"
            latitude: 1.55
            longitude: 110.36
          - location_id: "my_palm_johor"
            region: "Johor"
            latitude: 1.49
            longitude: 103.76
          - location_id: "my_palm_pahang"
            region: "Pahang"
            latitude: 3.81
            longitude: 103.33
          - location_id: "my_palm_perak"
            region: "Perak"
            latitude: 4.60
            longitude: 101.07
          - location_id: "my_palm_selangor"
            region: "Selangor"
            latitude: 3.07
            longitude: 101.52

      indonesia:
        regions:
          - location_id: "id_palm_riau"
            region: "Riau"
            latitude: 0.51
            longitude: 101.45
          - location_id: "id_palm_north_sumatra"
            region: "North Sumatra"
            latitude: 2.50
            longitude: 99.00
          - location_id: "id_palm_south_sumatra"
            region: "South Sumatra"
            latitude: -3.32
            longitude: 104.91
          - location_id: "id_palm_west_kalimantan"
            region: "West Kalimantan"
            latitude: -0.03
            longitude: 109.34
          - location_id: "id_palm_central_kalimantan"
            region: "Central Kalimantan"
            latitude: -1.68
            longitude: 113.38
          - location_id: "id_palm_east_kalimantan"
            region: "East Kalimantan"
            latitude: 0.54
            longitude: 116.42

  palm_olein_dce:
    description: "DCE palm olein: global palm oil supply weather universe plus Malaysia/Indonesia core origins."
    countries:
      indonesia:
        regions:
          - location_id: "id_palm_riau"
            region: "Riau"
            latitude: 0.51
            longitude: 101.45
          - location_id: "id_palm_north_sumatra"
            region: "North Sumatra"
            latitude: 2.50
            longitude: 99.00
          - location_id: "id_palm_south_sumatra"
            region: "South Sumatra"
            latitude: -3.32
            longitude: 104.91
          - location_id: "id_palm_west_kalimantan"
            region: "West Kalimantan"
            latitude: -0.03
            longitude: 109.34
          - location_id: "id_palm_central_kalimantan"
            region: "Central Kalimantan"
            latitude: -1.68
            longitude: 113.38
          - location_id: "id_palm_east_kalimantan"
            region: "East Kalimantan"
            latitude: 0.54
            longitude: 116.42

      malaysia:
        regions:
          - location_id: "my_palm_sabah"
            region: "Sabah"
            latitude: 5.98
            longitude: 116.08
          - location_id: "my_palm_sarawak"
            region: "Sarawak"
            latitude: 1.55
            longitude: 110.36
          - location_id: "my_palm_johor"
            region: "Johor"
            latitude: 1.49
            longitude: 103.76
          - location_id: "my_palm_pahang"
            region: "Pahang"
            latitude: 3.81
            longitude: 103.33
          - location_id: "my_palm_perak"
            region: "Perak"
            latitude: 4.60
            longitude: 101.07

```

---

# Copilot task prompt

Use this prompt in VS Code Copilot Chat:

```text
You are working in the Leviathan commodity data pipeline.

Read the file `oilseeds_weather_locations.md` and the existing code in
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
