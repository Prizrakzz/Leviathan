-- GENERATED from live Glue table leviathan_dev.silver_fnc_colombia_area_department; keep in sync with the S3 layout.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_fnc_colombia_area_department (
    leviathan_slug string,
    country        string,
    department     string,
    department_raw string,
    area_ha        double,
    source         string
)
PARTITIONED BY (commodity string, year int)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/area_department'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'projection.commodity.type' = 'enum',
    'projection.commodity.values' = 'arabica_coffee',
    'projection.enabled' = 'true',
    'projection.year.range' = '2002,2035',
    'projection.year.type' = 'integer',
    'storage.location.template' = 's3://leviathan-dev-shahem-001/silver/fnc_colombia/area_department/commodity=${commodity}/year=${year}'
);
