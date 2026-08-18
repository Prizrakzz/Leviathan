-- Hand DDL for silver_food_cpi (flat table over silver/food_cpi/).
--
-- D-LD (2026-08-18): edited by hand ahead of the registry regeneration, and BOTH edits below are
-- corrections of a live defect, not decoration:
--
--  (1) TYPES. cpi_yoy_pct / cpi_yoy_z_5yr / cpi_yoy_z_10yr were declared `float` (Athena `real`)
--      while the canonical parquet stores DOUBLE -- the SILVER-F062 widen landed in the WRITER
--      (the F010 target_arrow_type is float64) and never in the CATALOG. Athena REFUSES to read
--      them: "HIVE_BAD_DATA: Malformed Parquet file. Field cpi_yoy_pct's type DOUBLE in parquet
--      file ... is incompatible with type real defined in table schema". Strings, `year`,
--      `cpi_available` and count(*) all succeed, so the table looked alive while every measure
--      column was unreadable. cpi_available is corrected int32/tinyint -> bigint for truthfulness
--      (Athena widens that one silently; it was never broken).
--
--  (2) PIT ANCHORS. data_date + release_date are DERIVED BY THE PRODUCER (the WIRING WAVE-1
--      pre-step mechanism: CONAB survey_release_date, SAGIS week_ending_date). The table had no
--      date column of any kind, so every as-of-guarded lookup raised "table silver_food_cpi has
--      no knowledge/date column to anchor the as-of guard". data_date is the year-end OBSERVATION
--      date 'YYYY-12-31'; release_date is the World Bank API's own `lastupdated` release stamp,
--      which the bronze parser already read and discarded.
--
-- The registry-rendered twin (sql/athena/ddl_generated/) catches up when the F010 contract is
-- regenerated; until then this file leads it by exactly these two columns and four types.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_food_cpi (
    country_iso    string,
    country_name   string,
    year           bigint,
    cpi_yoy_pct    double,
    cpi_yoy_z_5yr  double,
    cpi_yoy_z_10yr double,
    cpi_available  bigint,
    source         string,
    data_date      string,
    release_date   string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/food_cpi/'
TBLPROPERTIES ('parquet.compression' = 'SNAPPY');
