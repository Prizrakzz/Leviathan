-- silver_fnc_colombia_monthly: monthly Colombia coffee production, prices, and exports.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_fnc_colombia_monthly (
    leviathan_slug                    STRING,
    country                           STRING,
    month                             INT,
    date                              DATE,
    production_bags_60kg              DOUBLE,
    ex_dock_price_usd_cents_per_lb    DOUBLE,
    internal_price_cop_per_125kg      DOUBLE,
    exports_bags_60kg                 DOUBLE,
    exports_value_usd_m               DOUBLE,
    source                            STRING
)
PARTITIONED BY (commodity STRING, year INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/monthly/'
TBLPROPERTIES (
    'projection.enabled'          = 'true',
    'projection.commodity.type'   = 'enum',
    'projection.commodity.values' = 'arabica_coffee',
    'projection.year.type'        = 'integer',
    'projection.year.range'       = '1913,2035',
    'storage.location.template'   = 's3://leviathan-dev-shahem-001/silver/fnc_colombia/monthly/commodity=${commodity}/year=${year}'
);
