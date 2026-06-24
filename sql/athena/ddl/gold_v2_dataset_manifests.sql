-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=gold_v2_dataset_manifests
-- registry_sha256=5051253d025cfdb39d7754504161873adc301225bfb70e9f3064e8e15a7c1d6b
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`gold_v2_dataset_manifests` (
    `created_at`        STRING,
    `base_git_sha`      STRING,
    `snapshot_policy`   STRING,
    `commodities`       STRING,
    `certified_sources` STRING,
    `blocked_sources`   STRING,
    `warning_sources`   STRING,
    `waivers`           STRING,
    `spine_row_count`   BIGINT,
    `matrix_row_count`  BIGINT
)
PARTITIONED BY (`dataset_version` STRING)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
STORED AS INPUTFORMAT 'org.apache.hadoop.mapred.TextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.IgnoreKeyTextOutputFormat'
LOCATION 's3://leviathan-dev-shahem-001/gold_v2/dataset_manifests/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.dataset_version.type' = 'injected',
    'projection.enabled' = 'true',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/gold_v2/dataset_manifests/dataset_version=${dataset_version}/'
);
