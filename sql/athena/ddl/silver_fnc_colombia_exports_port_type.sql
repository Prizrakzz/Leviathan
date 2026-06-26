-- GENERATED from live Glue table leviathan_dev.silver_fnc_colombia_exports_port_type; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_fnc_colombia_exports_port_type (
    leviathan_slug    string,
    country           string,
    month             bigint,
    date              date,
    port              string,
    port_raw          string,
    coffee_type       string,
    coffee_type_raw   string,
    exports_bags_60kg double,
    exports_value_usd double,
    source            string
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/exports_port_type'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'arabica_coffee',
    'projection.enabled' = 'true',
    'projection.year.range' = '2017,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/fnc_colombia/exports_port_type/commodity=${commodity}/year=${year}'
);
