-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=gold_v2_feature_matrix
-- registry_sha256=5051253d025cfdb39d7754504161873adc301225bfb70e9f3064e8e15a7c1d6b
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`gold_v2_feature_matrix` (
    `entity_type`        STRING,
    `entity_id`          STRING,
    `physical_commodity` STRING,
    `contract_slug`      STRING,
    `origin`             STRING,
    `crop_year`          INT,
    `as_of_date`         DATE,
    `snapshot_stage`     STRING
)
PARTITIONED BY (`dataset_version` STRING, `commodity` STRING)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold_v2/feature_matrix/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'cocoa,corn_cbot,campinas_corn_reference_bmf,french_wheat_matif,french_maize_matif,hard_red_winter_wheat_kcbt,hard_red_spring_wheat_mgex,soft_red_winter_wheat_cbot,rough_rice_cbot,south_african_white_maize_jse,south_african_yellow_maize_jse,soybeans_cbot,soybean_meal_cbot,soybean_oil_cbot,soybeans_no_1_dce,soybeans_no_2_dce,soybean_meal_dce,soybean_oil_dce,french_rapeseed_matif,canola_ice,rapeseed_oil_zce,rapeseed_meal_zce,malaysian_crude_palm_oil_cme,palm_olein_dce,brazilian_arabica_coffee,arabica_coffee,robusta_coffee,cotton,raw_sugar,white_sugar,frozen_orange_juice',
    'projection.dataset_version.type' = 'injected',
    'projection.enabled' = 'true',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold_v2/feature_matrix/dataset_version=${dataset_version}/commodity=${commodity}/'
);
