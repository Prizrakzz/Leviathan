-- graphrag_causal_edges: directed causal links extracted by Claude Haiku.
-- Each row is one (cause → effect) pair anchored by an explicit linguistic marker.
-- Partition projection — no MSCK REPAIR TABLE needed.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.graphrag_causal_edges (
    doc_key           STRING    COMMENT 'S3 key of the source document.json',
    document_date     STRING    COMMENT 'YYYY-MM-DD publication date',
    section_name      STRING    COMMENT 'WASDE/WAP section label (WHEAT, OILSEEDS, full, etc.)',
    chunk_index       INT       COMMENT '0-based chunk index within the parent document',
    cause             STRING    COMMENT 'Brief text description of the cause',
    effect            STRING    COMMENT 'Brief text description of the effect',
    cause_commodity   STRING    COMMENT 'Canonical commodity slug of the cause (nullable)',
    cause_origin      STRING    COMMENT 'Canonical country of the cause (nullable)',
    effect_commodity  STRING    COMMENT 'Canonical commodity slug of the effect (nullable)',
    effect_origin     STRING    COMMENT 'Canonical country of the effect (nullable)',
    lag               STRING    COMMENT 'Time lag description if stated (nullable)',
    marker            STRING    COMMENT 'Exact causal phrase from the source text',
    confidence        STRING    COMMENT 'high | medium | low'
)
PARTITIONED BY (source STRING, year INT, month INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/graphrag/causal_edges/'
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
    'storage.location.template'     = 's3://leviathan-dev-shahem-001/graphrag/causal_edges/source=${source}/year=${year}/month=${month}'
);
