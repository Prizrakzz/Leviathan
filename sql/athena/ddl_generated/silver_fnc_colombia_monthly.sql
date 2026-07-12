-- silver_fnc_colombia_monthly - production silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_fnc_colombia_monthly.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = projected. recovery: get-partitions inventory + single sargable Athena probe on a registered surface
--
-- LEGACY-QUARANTINED partition projection (INV-3): the projected grid enumerates every
-- candidate partition (the Jul-2026 S3 LIST-storm class). NEVER DROP+CREATE this into a
-- flat or re-projected shape; recovery reads S3 parquet footers, NEVER Athena.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_fnc_colombia_monthly (
    leviathan_slug                 string,
    country                        string,
    month                          bigint,
    date                           date,
    production_bags_60kg           double,
    ex_dock_price_usd_cents_per_lb double,
    internal_price_cop_per_125kg   double,
    exports_bags_60kg              double,
    exports_value_usd_m            double,
    source                         string
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/monthly/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'arabica_coffee',
    'projection.enabled' = 'true',
    'projection.year.range' = '1913,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/fnc_colombia/monthly/commodity=${commodity}/year=${year}'
);
