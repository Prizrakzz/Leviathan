-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=gold_feature_catalog
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`gold_feature_catalog` (
    `feature`   STRING,
    `scope`     STRING,
    `group`     STRING,
    `commodity` STRING,
    `is_label`  BOOLEAN
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/feature_catalog/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
