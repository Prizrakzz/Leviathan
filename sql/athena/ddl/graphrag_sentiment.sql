-- graphrag_sentiment: tone scores + policy changes extracted by Claude Haiku.
-- One row per (chunk × policy_change); chunks with no policy changes have
-- policy_* columns empty.  Tone score is repeated on each policy row.
-- Partition projection — no MSCK REPAIR TABLE needed.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.graphrag_sentiment (
    doc_key           STRING    COMMENT 'S3 key of the source document.json',
    document_date     STRING    COMMENT 'YYYY-MM-DD publication date',
    section_name      STRING    COMMENT 'WASDE/WAP section label (WHEAT, OILSEEDS, full, etc.)',
    chunk_index       INT       COMMENT '0-based chunk index within the parent document',
    -- Tone fields
    commodity         STRING    COMMENT 'Canonical commodity for this tone observation (nullable)',
    origin            STRING    COMMENT 'Canonical country for this tone observation (nullable)',
    tone_score        INT       COMMENT '-1 bearish | 0 neutral | 1 bullish',
    phrases           STRING    COMMENT 'JSON-encoded array of up to 3 verbatim phrases driving tone',
    -- Policy change fields (empty string when no policy change on this row)
    policy_country    STRING    COMMENT 'Country that issued the policy',
    policy_commodity  STRING    COMMENT 'Commodity affected by the policy',
    policy_type       STRING    COMMENT 'export_restriction | import_duty | subsidy | mandate | quota | other',
    policy_direction  STRING    COMMENT 'bullish | bearish | neutral (price effect)'
)
PARTITIONED BY (source STRING, year INT, month INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/graphrag/sentiment/'
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
    'storage.location.template'     = 's3://leviathan-dev-shahem-001/graphrag/sentiment/source=${source}/year=${year}/month=${month}'
);
