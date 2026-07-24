-- gold_pattern_records - observability gold table (generated); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/gold_pattern_records.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = registered. recovery: get-partitions reconcile + explicit per-partition locations (ESR as_of=/as_of_date mapping; never MSCK)
--
-- REGISTERED partitions -- DO NOT re-add partition projection. The projected grid is
-- the Jul-2026 S3 LIST-storm class ($134/2 days); partitions carry explicit Glue
-- locations (MSCK cannot repair them). After a DROP+CREATE from this DDL, re-register:
--     python jobs/utils/deproject_glue_table.py --register --tables gold_pattern_records
CREATE EXTERNAL TABLE IF NOT EXISTS gold_pattern_records (
    record_kind        string,
    contract           string,
    driver_or_chain_id string,
    counterparty       string,
    verdict            string,
    decline_reason     string,
    streak_len         bigint,
    streak_dir         string,
    window_change      double,
    grain              string,
    n_points           bigint,
    n_rows             bigint,
    n_hops             bigint,
    extra              string,
    engine_version     string,
    graph_version      string,
    provenance         string,
    run_id             string,
    written_at         timestamp
)
PARTITIONED BY (as_of_date string)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/pattern_records/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
