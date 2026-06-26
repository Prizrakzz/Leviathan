-- GENERATED from live Glue table leviathan_dev.metadata_s3_inventory; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS metadata_s3_inventory (
    bucket             string,
    key                string,
    size               bigint,
    last_modified_date timestamp,
    e_tag              string,
    storage_class      string,
    replication_status string,
    encryption_status  string
)
PARTITIONED BY (dt string)
ROW FORMAT SERDE 'org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe'
STORED AS INPUTFORMAT 'org.apache.hadoop.hive.ql.io.SymlinkTextInputFormat'
OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION 's3://leviathan-dev-shahem-001/metadata/s3_inventory/leviathan-dev-shahem-001/leviathan-dev-weekly/hive'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.dt.format' = 'yyyy-MM-dd-HH-mm',
    'projection.dt.interval' = '1',
    'projection.dt.interval.unit' = 'HOURS',
    'projection.dt.range' = '2026-06-23-00-00,NOW',
    'projection.dt.type' = 'date',
    'projection.enabled' = 'true'
);
