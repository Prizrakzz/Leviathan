-- silver_ams_gtr - trade_flows silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_ams_gtr.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = registered. recovery: get-partitions reconcile against the seven fixed dataset= prefixes (the partition set is CLOSED and enumerable from GTR_DATASETS; never MSCK)
--
-- REGISTERED partitions -- DO NOT re-add partition projection. The projected grid is
-- the Jul-2026 S3 LIST-storm class ($134/2 days); partitions carry explicit Glue
-- locations (MSCK cannot repair them). After a DROP+CREATE from this DDL, re-register:
--     python jobs/utils/deproject_glue_table.py --register --tables silver_ams_gtr
CREATE EXTERNAL TABLE IF NOT EXISTS silver_ams_gtr (
    series               string,
    route_or_reach       string,
    period_date          date,
    period_grain         string,
    rate                 double,
    unit                 string,
    forward_month_offset bigint,
    rate_month           bigint,
    commodity            string,
    vessel_size          string,
    knowledge_date       date,
    knowledge_date_basis string,
    as_of_date           string,
    ingest_date          string,
    source_attribution   string,
    source               string
)
PARTITIONED BY (dataset string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/ams_gtr/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
