-- GENERATED from live Glue table leviathan_dev.silver_fnc_colombia_monthly; keep in sync with the S3 layout.
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
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/monthly'
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
