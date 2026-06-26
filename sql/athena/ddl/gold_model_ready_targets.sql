-- Model-ready target rows derived from immutable gold feature matrices.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_model_ready_targets (
    source_dataset_version           string,
    target_key                       string,
    target_title                     string,
    target_unit                      string,
    country                          string,
    crop_year                        int,
    actual_value                     double,
    target_value                     double,
    trend_prediction                 double,
    prior_year_value                 double,
    trailing_mean_prediction         double,
    zero_anomaly_baseline            double,
    prior_year_anomaly_baseline      double,
    trailing_mean_anomaly_baseline   double,
    trailing_trend_anomaly_baseline  double,
    history_years                    int,
    is_trainable                     boolean,
    excluded_reason                  string
)
PARTITIONED BY (
    dataset_version string,
    dataset_key     string,
    commodity       string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/model_ready_targets/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.dataset_version.type' = 'injected',
    'projection.dataset_key.type' = 'enum',
    'projection.dataset_key.values' = 'annual_physical_anomaly',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'cocoa,corn_cbot,campinas_corn_reference_bmf,french_wheat_matif,french_maize_matif,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot,rough_rice_cbot,south_african_white_maize_jse,south_african_yellow_maize_jse,soybeans_cbot,soybean_meal_cbot,soybean_oil_cbot,soybeans_no_1_dce,soybeans_no_2_dce,soybean_meal_dce,soybean_oil_dce,french_rapeseed_matif,canola_ice,rapeseed_oil_zce,rapeseed_meal_zce,malaysian_crude_palm_oil_cme,palm_olein_dce,brazilian_arabica_coffee,arabica_coffee,robusta_coffee,cotton,raw_sugar,white_sugar,frozen_orange_juice',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold/model_ready_targets/dataset_version=${dataset_version}/dataset_key=${dataset_key}/commodity=${commodity}/'
);
