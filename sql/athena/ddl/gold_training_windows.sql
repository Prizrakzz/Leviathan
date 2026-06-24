-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=gold_training_windows
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`gold_training_windows` (
    `commodity`          STRING,
    `tier`               STRING,
    `n_features`         BIGINT,
    `label_first_year`   BIGINT,
    `label_last_year`    BIGINT,
    `n_label_years`      BIGINT,
    `dense_start_year`   DOUBLE,
    `dense_window_years` BIGINT,
    `present_families`   STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/training_windows/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
