-- silver_conab_coffee: Brazil CONAB coffee survey production revisions.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_conab_coffee (
    country                             STRING,
    survey_number                       INT,
    region                              STRING,
    area_in_production_ha               DOUBLE,
    yield_bags_per_ha                   DOUBLE,
    production_thousand_bags            DOUBLE,
    production_revision_thousand_bags   DOUBLE,
    source                              STRING
)
PARTITIONED BY (commodity STRING, safra_year INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/conab_coffee/'
TBLPROPERTIES (
    'projection.enabled'            = 'true',
    'projection.commodity.type'     = 'enum',
    'projection.commodity.values'   = 'arabica_coffee,robusta_coffee',
    'projection.safra_year.type'    = 'integer',
    'projection.safra_year.range'   = '2023,2035',
    'storage.location.template'     = 's3://leviathan-dev-shahem-001/silver/conab_coffee/commodity=${commodity}/safra_year=${safra_year}'
);
