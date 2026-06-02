-- silver_fnc_colombia_exports_port_type: monthly Colombia coffee exports by port/type.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_fnc_colombia_exports_port_type (
    leviathan_slug       STRING,
    country              STRING,
    month                INT,
    date                 DATE,
    port                 STRING,
    port_raw             STRING,
    coffee_type          STRING,
    coffee_type_raw      STRING,
    exports_bags_60kg    DOUBLE,
    exports_value_usd    DOUBLE,
    source               STRING
)
PARTITIONED BY (commodity STRING, year INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/exports_port_type/'
TBLPROPERTIES (
    'projection.enabled'          = 'true',
    'projection.commodity.type'   = 'enum',
    'projection.commodity.values' = 'arabica_coffee',
    'projection.year.type'        = 'integer',
    'projection.year.range'       = '2017,2035',
    'storage.location.template'   = 's3://leviathan-dev-shahem-001/silver/fnc_colombia/exports_port_type/commodity=${commodity}/year=${year}'
);
