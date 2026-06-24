-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=metadata_s3_inventory
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`metadata_s3_inventory` (
    `bucket`             STRING,
    `key`                STRING,
    `size`               BIGINT,
    `last_modified_date` TIMESTAMP,
    `e_tag`              STRING,
    `storage_class`      STRING,
    `replication_status` STRING,
    `encryption_status`  STRING
)
PARTITIONED BY (`dt` STRING)
ROW FORMAT SERDE 'org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe'
STORED AS INPUTFORMAT 'org.apache.hadoop.hive.ql.io.SymlinkTextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.IgnoreKeyTextOutputFormat'
LOCATION 's3://leviathan-dev-shahem-001/metadata/s3_inventory/leviathan-dev-shahem-001/leviathan-dev-weekly/hive/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.dt.format' = 'yyyy-MM-dd-HH-mm',
    'projection.dt.interval' = '1',
    'projection.dt.interval.unit' = 'HOURS',
    'projection.dt.range' = '2026-06-23-00-00,NOW',
    'projection.dt.type' = 'date',
    'projection.enabled' = 'true'
);
