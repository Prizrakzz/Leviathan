-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=gold_v2_feature_group_map
-- registry_sha256=e1aa1e389fe22701f0e4b2067591f95bbe239435b4ad757f5c397d7871ea1631
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`gold_v2_feature_group_map` (
    `feature`         STRING,
    `group`           STRING,
    `entity_count`    BIGINT,
    `commodity_count` BIGINT,
    `row_count`       BIGINT
)
PARTITIONED BY (`dataset_version` STRING)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold_v2/feature_group_map/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.dataset_version.type' = 'injected',
    'projection.enabled' = 'true',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold_v2/feature_group_map/dataset_version=${dataset_version}/'
);
