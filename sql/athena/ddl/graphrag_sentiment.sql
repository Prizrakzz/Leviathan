-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=graphrag_sentiment
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`graphrag_sentiment` (
    `doc_key`          STRING,
    `document_date`    STRING,
    `section_name`     STRING,
    `chunk_index`      INT,
    `commodity`        STRING,
    `origin`           STRING,
    `tone_score`       TINYINT,
    `phrases`          STRING,
    `policy_country`   STRING,
    `policy_commodity` STRING,
    `policy_type`      STRING,
    `policy_direction` STRING
)
PARTITIONED BY (`source` STRING, `year` INT, `month` INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/graphrag/sentiment/'
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
    'storage.location.template' = 's3://leviathan-dev-shahem-001/graphrag/sentiment/source=${source}/year=${year}/month=${month}'
);
