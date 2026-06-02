-- silver_fnc_colombia_area_department: annual Colombia coffee area by department.

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_fnc_colombia_area_department (
    leviathan_slug    STRING,
    country           STRING,
    department        STRING,
    department_raw    STRING,
    area_ha           DOUBLE,
    source            STRING
)
PARTITIONED BY (commodity STRING, year INT)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/fnc_colombia/area_department/'
TBLPROPERTIES (
    'projection.enabled'          = 'true',
    'projection.commodity.type'   = 'enum',
    'projection.commodity.values' = 'arabica_coffee',
    'projection.year.type'        = 'integer',
    'projection.year.range'       = '2002,2035',
    'storage.location.template'   = 's3://leviathan-dev-shahem-001/silver/fnc_colombia/area_department/commodity=${commodity}/year=${year}'
);
