-- graphrag_forecasts: explicit production estimates extracted by Claude Haiku.
-- Only rows where an analyst cited a specific number or direction revision.
-- Partition projection — no MSCK REPAIR TABLE needed.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.graphrag_forecasts (
    doc_key        STRING    COMMENT 'S3 key of the source document.json',
    document_date  STRING    COMMENT 'YYYY-MM-DD publication date',
    section_name   STRING    COMMENT 'WASDE/WAP section label (WHEAT, OILSEEDS, full, etc.)',
    chunk_index    INT       COMMENT '0-based chunk index within the parent document',
    commodity      STRING    COMMENT 'Canonical leviathan commodity slug',
    origin         STRING    COMMENT 'Canonical country name',
    value          DOUBLE    COMMENT 'Numeric forecast value (nullable if direction only)',
    unit           STRING    COMMENT 'Unit of measure: MMT, 1000 MT, million bags, etc.',
    crop_year      STRING    COMMENT 'Crop year (e.g. 2021/22) if stated',
    direction      STRING    COMMENT 'up | down | unchanged (when no numeric value given)'
)
PARTITIONED BY (source STRING, year INT, month INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/graphrag/forecasts/'
TBLPROPERTIES (
    'parquet.compress'              = 'SNAPPY',
    'projection.enabled'            = 'true',
    'projection.source.type'        = 'enum',
    'projection.source.values'      = 'usda_wasde,usda_wap,usda_gain,conab,fnc',
    'projection.year.type'          = 'integer',
    'projection.year.range'         = '2000,2030',
    'projection.month.type'         = 'integer',
    'projection.month.range'        = '1,12',
    'projection.month.digits'       = '2',
    'storage.location.template'     = 's3://leviathan-dev-shahem-001/graphrag/forecasts/source=${source}/year=${year}/month=${month}'
);
