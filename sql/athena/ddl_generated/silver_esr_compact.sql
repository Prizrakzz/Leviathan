-- silver_esr_compact - trade_flows silver table (serving_copy); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_esr_compact.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = registered. recovery: get-partitions reconcile + explicit per-partition locations (ESR as_of=/as_of_date mapping; never MSCK)
--
-- REGISTERED partitions -- DO NOT re-add partition projection. The projected grid is
-- the Jul-2026 S3 LIST-storm class ($134/2 days); partitions carry explicit Glue
-- locations (MSCK cannot repair them). After a DROP+CREATE from this DDL, re-register:
--     python jobs/utils/deproject_glue_table.py --register --tables silver_esr_compact
CREATE EXTERNAL TABLE IF NOT EXISTS silver_esr_compact (
    commodity_code           smallint,
    commodity_name           string,
    market_year              smallint,
    country_code             smallint,
    week_ending_date         date,
    outstanding_sales_1000mt float,
    weekly_exports_1000mt    float,
    gross_new_sales_1000mt   float,
    changes_1000mt           float,
    source_unit_id           smallint,
    ingest_date              string,
    source                   string
)
PARTITIONED BY (commodity string, as_of_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/esr/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
