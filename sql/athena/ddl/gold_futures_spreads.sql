-- gold_futures_spreads -- the GN-2 W2.3 same-unit two-leg spread serving table.
--
-- One row per (spread_id, trading session): the front-month spread between two contracts the
-- platform already serves, under the ONE named roll rule, with both legs' identity and provenance on
-- the row. LONG shape: `spread_id` is the series axis (kc_chi = HRW-SRW wheat class premium in US
-- cents/bushel; white_yellow = JSE white-yellow maize premium in ZAR/t), and `unit` rides every row
-- because units differ ACROSS spreads while each spread is single-unit by the transform's same-unit
-- law (both legs' unit AND currency asserted equal at runtime -- the MIAX class refuses, never
-- rescales). Built by jobs/batch/gold_futures_spreads_task.py (compute core:
-- leviathan.transforms.gold.futures_spreads) directly from the silver parquet -- no Athena read.
--
-- WHY GOLD: the same doctrine as gold_board_crush -- a spread only exists once a roll policy has been
-- applied, so roll_rule_version + spread_rule_version ride every row and the table lives in gold.
-- Flat, non-projected, non-partitioned: the whole table is one parquet object (~10k rows), no
-- LIST-storm surface, no per-partition ADD on refresh.
--
-- is_roll_boundary: STRING '0'/'1' -- '1' when EITHER leg's front contract differs from the previous
-- emitted session's (a contract change, not a market move). String for the three-backend comparison
-- identity (Athena literal-IN, pg text, the pure-Python oracle -- the gold_board_crush precedent);
-- every served read excludes ='1' via the card's row_filters.
CREATE EXTERNAL TABLE IF NOT EXISTS gold_futures_spreads (
    spread_id            string,
    trade_date           string,
    spread_value         double,
    unit                 string,
    long_slug            string,
    short_slug           string,
    long_contract_month  string,
    short_contract_month string,
    long_settle          double,
    short_settle         double,
    settle_kind          string,
    is_roll_boundary     string,
    roll_rule_version    string,
    spread_rule_version  string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/gold/futures_spreads/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY',
    'classification' = 'parquet'
);
