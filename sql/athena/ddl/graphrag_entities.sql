-- graphrag_entities: stress events extracted by Claude Haiku from text/ layer.
-- Partition projection — no MSCK REPAIR TABLE needed.
-- Run via: python jobs/submit/submit_batch_text_to_graphrag.py
--
-- source: enum projection — all sources that have been processed through
--   the text_to_graphrag pipeline. Add new values as new sources are ingested.
-- year:   integer 2000-2030
-- month:  integer 1-12 (zero-padded in S3 path)

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.graphrag_entities (
    doc_key        STRING    COMMENT 'S3 key of the source document.json',
    document_date  STRING    COMMENT 'YYYY-MM-DD publication date',
    section_name   STRING    COMMENT 'WASDE/WAP section label (WHEAT, OILSEEDS, full, etc.)',
    chunk_index    INT       COMMENT '0-based chunk index within the parent document',
    commodity      STRING    COMMENT 'Canonical leviathan commodity slug',
    origin         STRING    COMMENT 'Canonical country name',
    stress_type    STRING    COMMENT 'drought | frost | flood | disease | pest | wind | heat_stress | biennial_cycle | planting_delay',
    severity       INT       COMMENT '-1 mild | 0 neutral | 1 severe',
    crop_year      STRING    COMMENT 'Crop year (e.g. 2021/22) if stated',
    time_window    STRING    COMMENT 'Seasonal/monthly window if stated'
)
PARTITIONED BY (source STRING, year INT, month INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/graphrag/entities/'
TBLPROPERTIES (
    'parquet.compress'              = 'SNAPPY',
    'projection.enabled'            = 'true',
    'projection.source.type'        = 'enum',
    'projection.source.values'      = 'usda_wasde,usda_wap,usda_gain,conab',
    'projection.year.type'          = 'integer',
    'projection.year.range'         = '2000,2030',
    'projection.month.type'         = 'integer',
    'projection.month.range'        = '1,12',
    'projection.month.digits'       = '2',
    'storage.location.template'     = 's3://leviathan-dev-shahem-001/graphrag/entities/source=${source}/year=${year}/month=${month}'
);
