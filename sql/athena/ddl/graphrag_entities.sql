-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=graphrag_entities
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`graphrag_entities` (
    `doc_key`       STRING,
    `document_date` STRING,
    `section_name`  STRING,
    `chunk_index`   INT,
    `commodity`     STRING,
    `origin`        STRING,
    `stress_type`   STRING,
    `severity`      TINYINT,
    `crop_year`     STRING,
    `window`        STRING
)
PARTITIONED BY (`source` STRING, `year` INT, `month` INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/graphrag/entities/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY',
    'projection.enabled' = 'true',
    'projection.month.digits' = '2',
    'projection.month.range' = '1,12',
    'projection.month.type' = 'integer',
    'projection.source.type' = 'enum',
    'projection.source.values' = 'usda_wasde,usda_wap,usda_gain,conab',
    'projection.year.range' = '1973,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/graphrag/entities/source=${source}/year=${year}/month=${month}'
);
