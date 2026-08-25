-- silver_psd_attributes -- the LONG companion to silver_psd (projection wave, Lane 3 / L2-2).
--
-- One row per (leviathan_slug, country, market_year, wasde_release_month, attribute), with the value
-- in USDA's OWN unit. silver_psd pivots EIGHT balance-sheet attributes into MT-denominated columns
-- and discards everything else at one line; this table is the other half -- Crush, the whole demand
-- decomposition, the TY trade trio, the coffee and sugar variety splits, and the rate attributes.
-- Built by leviathan.transforms.bronze_to_silver.usda_psd_attributes off the SAME bronze object and
-- the SAME shared prefix as the wide producer, branching before its step-6 attribute filter.
--
-- NATIVE UNITS, AND `unit` IS THE AUTHORITY ON EVERY ROW. Nothing here is converted, which is what
-- lets the table carry PERCENT/RATIO rates and a (1000 HEAD) herd count at all: the wide producer's
-- step-7 guard RAISES on any unit absent from its factor table, and PERCENT/RATIO are DELIBERATELY
-- absent -- that absence is the fence keeping the head-count refusal honest, so a long table that
-- converts nothing never approaches it. Six units are live across the served attributes and rows are
-- NEVER summed across them.
--
-- wasde_release_month IS PART OF THE GRAIN AND THE COLUMN ORDER SAYS SO. PSD re-publishes one
-- marketing year at up to thirteen WASDE release months (month_code 0..12; 389,283 rows carry 0 --
-- the pre-WASDE-tracking mass, MY 1960-2004). silver_wasde shipped without its full grain and the
-- latest-vintage ROW_NUMBER collapsed ACROSS regions for months without anyone seeing it; dropping
-- this column from the numbers card's grain_cols reopens the identical failure here.
--
-- attribute + attribute_id RIDE TOGETHER ON PURPOSE. `attribute` is USDA's OWN label, byte-for-byte
-- (sugar keeps "Total Disappearance", cotton "Domestic Use", fresh citrus "Fresh Dom. Consumption" --
-- the wide pivot folds all three onto "Domestic Consumption" and this table must not), and
-- attribute_id is USDA's stable key. The R4 attribute-aware fan-out registry joins on the ID, never
-- on the label: a string-identity join loses a source-side rename silently, and PSD labels carry
-- punctuation that makes them fragile ("Rst,Ground Dom. Consum", "Refined Imp.(Raw Val)").
--
-- FLAT, NON-PROJECTED, latest-only: one publish overwrites the object set, and re-printed vintages
-- resolve latest-wins on (release_date, bronze_ingest_date) inside the transform -- so there is no
-- partition surface to enumerate and no per-partition ADD on refresh.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_psd_attributes (
    leviathan_slug      string,
    country             string,
    market_year         smallint,
    wasde_release_month tinyint,
    release_date        string,
    attribute           string,
    attribute_id        smallint,
    value               double,
    unit                string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/psd_attributes/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'classification' = 'parquet'
);
