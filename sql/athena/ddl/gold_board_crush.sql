-- gold_board_crush -- the D-EC DK-13 CBOT soybean board-crush serving table.
--
-- One row per TRADING SESSION: the processor's gross margin in US dollars per bushel, computed from the
-- three CBOT soy legs the platform already stores in silver_futures_eod. Built by
-- jobs/batch/gold_board_crush_task.py (compute core: leviathan.transforms.gold.board_crush) directly from
-- the silver parquet -- no Athena read, no Glue catalog touch on the input side.
--
-- WHY GOLD AND NOT SILVER: silver_futures_eod's own contract states that a derived series carrying a roll
-- policy "would be a separate derived gold_futures_continuous with its own roll_policy_version". A board
-- crush is exactly that object -- it does not exist until the ONE named front-month rule has been applied
-- -- so roll_rule_version rides every row and the table lives in gold. gold_weather_z is the shape
-- precedent: derived, flat, tiny, served straight from the numbers registry.
--
-- No projection, non-partitioned physical layout: the whole table is flat parquet under one LOCATION
-- (~4,000 rows since the 2010-06-06 GLBX coverage floor), so a query reads it without any partition
-- enumeration -- no LIST-storm surface, and no per-partition ADD on refresh (the writer overwrites
-- gold/board_crush/part-000.parquet).
--
-- knowledge_semantics = data_date on trade_date with publication_lag_days = 1 in the numbers registry --
-- inherited EXACTLY from silver_futures_eod, because the crush is citable when its last leg's EOD print
-- is. trade_date is a STRING in ISO 'YYYY-MM-DD' form (not a TIMESTAMP as in silver_futures_eod), so the
-- DP-5 substr normalization does not apply here and a plain varchar compare orders it correctly.
--
-- The three leg settles are carried for PROVENANCE and are deliberately NOT served metrics: each is in a
-- different unit (US cents/bushel, USD/short ton, US cents/lb), and a served metric whose unit changes by
-- column is a mis-quote waiting to happen. Every SERVED metric here is USD/bushel.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_board_crush (
    trade_date           string,
    crush_margin_usd_bu  double,
    meal_value_usd_bu    double,
    oil_value_usd_bu     double,
    bean_cost_usd_bu     double,
    beans_contract_month string,
    meal_contract_month  string,
    oil_contract_month   string,
    beans_settle         double,
    meal_settle          double,
    oil_settle           double,
    settle_kind          string,
    roll_rule_version    string,
    crush_rule_version   string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/board_crush/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'classification' = 'parquet'
);
