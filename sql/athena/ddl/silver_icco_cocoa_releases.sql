-- silver_icco_cocoa_releases - balance_sheet silver table (source); SILVER-F011 registry-generated DDL.
--
-- GENERATED from the SILVER-F010 registry (configs/silver/tables/silver_icco_cocoa_releases.yaml) by
-- leviathan.silver.ddl -- this RETIRES the first-parquet schema inference. Do NOT
-- hand-edit; re-run:  python scripts/silver/generate_ddls_from_registry.py --write
-- partition_mode = flat. recovery: active-release manifest / bounded full relist under the flat root
--
-- Flat physical layout under one LOCATION -- no partition-enumeration (LIST-storm)
-- surface; any hive-partition keys are also in-file data columns.
CREATE EXTERNAL TABLE IF NOT EXISTS silver_icco_cocoa_releases (
    release_date                      string,
    release_date_source               string,
    bulletin_volume                   string,
    bulletin_issue                    bigint,
    cocoa_year                        string,
    figure_kind                       string,
    header_season                     string,
    season_witnesses                  string,
    production_kt                     double,
    grindings_kt                      double,
    end_stocks_kt                     double,
    surplus_deficit_kt                double,
    stocks_to_grindings_pct_published double,
    su_ratio                          double,
    weight_loss_pct                   double,
    weight_loss_source                string,
    identity_gap_kt                   double,
    identity_status                   string,
    stocks_identity_gap_kt            double,
    missing_reason                    string,
    source_url                        string,
    page_key                          string,
    page_sha256                       string,
    parse_version                     string,
    source                            string
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/icco_cocoa_releases/'
TBLPROPERTIES (
    'EXTERNAL' = 'TRUE',
    'parquet.compression' = 'SNAPPY'
);
