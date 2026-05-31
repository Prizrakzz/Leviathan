-- silver_unica_annual_state: UNICA Brazil Centre-South annual production by state.
-- Single flat unpartitioned file at silver/unica_annual_state/part-000.parquet.
-- Managed programmatically by jobs/run_athena_ddl.py.
--
-- Data layer:  silver (pivoted from UNICA EAV bronze).
-- Granularity: one row per (harvest_year, state_region).
--              41 seasons × 27 rows = 1,107 rows total.
-- Source:      UNICA historical HTML table (idTabela=2495, tipoHistorico=4).
-- Units:       metric tonnes (t) for cane/sugar; cubic metres (m3) for ethanol.
--
-- Values are annual totals for the full harvest season.
--
-- state_region: Brazilian state name or regional aggregate from the UNICA portal.
--   State examples: "São Paulo", "Minas Gerais", "Goiás", ...
--   Regional aggregates: "South-Central Region", "North-Northeast Region", "Brazil".
--
-- Coverage: 1980/1981–2020/2021 (historical HTML source).
--           2021/2022+ is sourced from unica_biweekly PDFs (separate pipeline).

CREATE EXTERNAL TABLE IF NOT EXISTS leviathan_dev.silver_unica_annual_state (
    harvest_year        STRING,
    state_region        STRING,
    cane_crushed_t      DOUBLE,
    sugar_produced_t    DOUBLE,
    ethanol_total_m3    DOUBLE,
    ethanol_hydrous_m3  DOUBLE,
    ethanol_anhydrous_m3 DOUBLE,
    source              STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/unica_annual_state/'
TBLPROPERTIES (
    'parquet.compress' = 'SNAPPY'
);
