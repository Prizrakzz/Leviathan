-- silver_wasde - balance_sheet silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_wasde.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = registered. recovery: get-partitions reconcile + explicit per-partition locations (ESR as_of=/as_of_date mapping; never MSCK)
--
-- REGISTERED partitions -- DO NOT re-add partition projection. The projected grid is
-- the Jul-2026 S3 LIST-storm class ($134/2 days); partitions carry explicit Glue
-- locations (MSCK cannot repair them). After a DROP+CREATE from this DDL, re-register:
--     python jobs/utils/deproject_glue_table.py --register --tables silver_wasde
CREATE EXTERNAL TABLE IF NOT EXISTS silver_wasde (
    commodity                    string,
    table_type                   string,
    region                       string,
    marketing_year               string,
    attribute                    string,
    unit                         string,
    estimate                     double,
    prior_release_date           string,
    prior_estimate               double,
    revision                     double,
    revision_direction           string,
    months_to_marketing_year_end bigint,
    is_first_estimate            boolean,
    is_final_or_latest           boolean,
    raw_table_name               string,
    raw_region                   string,
    raw_attribute                string,
    raw_status                   string,
    raw_projection_month         string,
    source                       string,
    source_table_id              string,
    estimate_role                string,
    projection_month             string,
    is_current_release_estimate  boolean,
    release_sequence             bigint,
    revision_gap_days            bigint,
    is_projection                boolean,
    is_source_final              boolean,
    marketing_year_end_date      string
)
PARTITIONED BY (release_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/wasde/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
