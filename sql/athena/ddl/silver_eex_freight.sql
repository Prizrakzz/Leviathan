-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_eex_freight.yaml).
-- NOT inferred from a live parquet: this table is REGISTERED BEFORE FIRST WRITE, so the registry
-- is the only schema authority there is.  Semantically identical to
-- sql/athena/ddl_generated/silver_eex_freight.sql (leviathan.silver.ddl.diff_structured == []).
--
-- Flat table over silver/eex_freight/ -- no partition-enumeration surface at all.
--
-- FORWARD-ONLY ACCUMULATOR.  api.eex-group.com serves a rolling ~5-trading-day settlement window
-- and no history, so every row here was captured on the day it was published and can never be
-- re-derived.  DROP this table freely (it is external, the data is in S3); never DELETE the S3
-- prefix behind it.
--
-- UNITS ARE PER ROW AND ARE NOT ALL THE SAME.  `unit` is the authority: 'USD/day' for the ten
-- time/trip-charter averages (Panamax/Supramax/Capesize 5TC, Handysize 7TC ...) and 'USD/tonne'
-- for the three Capesize VOYAGE routes C3EM/C5EM/C7EM, whose settlements print near 15-36 beside
-- Panamax figures near 20,000.  NEVER aggregate settle_px across `unit` values.
-- `volume_lots` is in LOTS on every row and is safe to sum.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_eex_freight (
    trade_date     date,
    symbol         string,
    contract_month string,
    product        string,
    route          string,
    settle_px      double,
    currency       string,
    unit           string,
    volume_lots    double,
    long_name      string,
    source         string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/eex_freight/'
TBLPROPERTIES ('parquet.compression' = 'SNAPPY');
