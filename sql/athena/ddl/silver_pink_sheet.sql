-- GENERATED from configs/datasets/datasets.yaml; do not edit by hand.
-- dataset_id=silver_pink_sheet
-- registry_sha256=fcc347a2e81b7b5fd3a6b6223801a375b77ec9819afa289ec9f7a1342d2cdce3
CREATE EXTERNAL TABLE IF NOT EXISTS `leviathan_dev`.`silver_pink_sheet` (
    `date`                                TIMESTAMP,
    `year`                                BIGINT,
    `month`                               BIGINT,
    `urea_usd_mt`                         DOUBLE,
    `dap_usd_mt`                          DOUBLE,
    `potassium_usd_mt`                    DOUBLE,
    `natural_gas_us_usd_mmbtu`            DOUBLE,
    `natural_gas_eu_usd_mmbtu`            DOUBLE,
    `phosphate_rock_usd_mt`               DOUBLE,
    `brent_crude_usd_bbl`                 DOUBLE,
    `blended_npk_index`                   DOUBLE,
    `soybeans_usd_t`                      DOUBLE,
    `soybean_oil_usd_t`                   DOUBLE,
    `soybean_meal_usd_t`                  DOUBLE,
    `palm_oil_cpo_usd_t`                  DOUBLE,
    `raw_sugar_world_usd_t`               DOUBLE,
    `wheat_us_hrw_usd_t`                  DOUBLE,
    `wheat_us_srw_usd_t`                  DOUBLE,
    `rapeseed_oil_usd_t`                  DOUBLE,
    `urea_usd_mt_zscore_5yr`              DOUBLE,
    `dap_usd_mt_zscore_5yr`               DOUBLE,
    `potassium_usd_mt_zscore_5yr`         DOUBLE,
    `natural_gas_us_usd_mmbtu_zscore_5yr` DOUBLE,
    `natural_gas_eu_usd_mmbtu_zscore_5yr` DOUBLE,
    `phosphate_rock_usd_mt_zscore_5yr`    DOUBLE,
    `brent_crude_usd_bbl_zscore_5yr`      DOUBLE,
    `blended_npk_index_zscore_5yr`        DOUBLE,
    `soybeans_usd_t_zscore_5yr`           DOUBLE,
    `soybean_oil_usd_t_zscore_5yr`        DOUBLE,
    `soybean_meal_usd_t_zscore_5yr`       DOUBLE,
    `palm_oil_cpo_usd_t_zscore_5yr`       DOUBLE,
    `raw_sugar_world_usd_t_zscore_5yr`    DOUBLE,
    `wheat_us_hrw_usd_t_zscore_5yr`       DOUBLE,
    `wheat_us_srw_usd_t_zscore_5yr`       DOUBLE,
    `rapeseed_oil_usd_t_zscore_5yr`       DOUBLE,
    `latest_release_ym`                   STRING
)
STORED AS PARQUET
LOCATION 's3://leviathan-dev-shahem-001/silver/pink_sheet/'
TBLPROPERTIES (
    'parquet.compression' = 'SNAPPY'
);
