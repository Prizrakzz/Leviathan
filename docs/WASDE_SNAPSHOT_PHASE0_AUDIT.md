# WASDE Snapshot Phase 0 Audit

## Decision

- Proceed to Phase 1: `True`
- Blockers: `none`
- Recommended first surface: `corn_wasde_snapshot_solo`

## WASDE Inventory

| commodity | row_count | release_date_count | marketing_year_count | region_count | core_snapshot_key_count |
| --- | --- | --- | --- | --- | --- |
| cotton | 126927 | 395 | 42 | 570 | 97422 |
| rice | 112337 | 412 | 44 | 639 | 90582 |
| wheat | 77746 | 376 | 36 | 93 | 58744 |
| soybeans | 70356 | 422 | 44 | 312 | 54711 |
| corn | 67163 | 401 | 43 | 129 | 51317 |
| soybean_oil | 62865 | 414 | 44 | 371 | 52863 |
| soybean_meal | 59881 | 412 | 41 | 293 | 50365 |
| sugar | 3596 | 187 | 20 | 1 | 2521 |

## Region Quality

| commodity | quality_class | region_count | row_count |
| --- | --- | --- | --- |
| corn | aggregate_region | 12 | 14257 |
| corn | clean_origin | 10 | 26917 |
| corn | garbled_parser_artifact | 58 | 653 |
| corn | unknown_review_required | 49 | 25336 |
| rice | aggregate_region | 31 | 18700 |
| rice | clean_origin | 7 | 32286 |
| rice | garbled_parser_artifact | 85 | 628 |
| rice | unknown_review_required | 516 | 60723 |
| soybean_meal | aggregate_region | 34 | 18828 |
| soybean_meal | clean_origin | 6 | 24946 |
| soybean_meal | garbled_parser_artifact | 43 | 87 |
| soybean_meal | unknown_review_required | 210 | 16020 |
| soybean_oil | aggregate_region | 41 | 18741 |
| soybean_oil | clean_origin | 6 | 25202 |
| soybean_oil | garbled_parser_artifact | 81 | 162 |
| soybean_oil | unknown_review_required | 243 | 18760 |
| soybeans | aggregate_region | 39 | 18432 |
| soybeans | clean_origin | 5 | 27828 |
| soybeans | garbled_parser_artifact | 62 | 171 |
| soybeans | unknown_review_required | 206 | 23925 |
| wheat | aggregate_region | 10 | 15171 |
| wheat | clean_origin | 10 | 32731 |
| wheat | garbled_parser_artifact | 32 | 570 |
| wheat | unknown_review_required | 41 | 29274 |

## PSD Target Compatibility

| commodity | target_key | row_count | trainable_row_count | origin_count | market_year_min | market_year_max |
| --- | --- | --- | --- | --- | --- | --- |
| corn_cbot | psd_domestic_use_anomaly_pct | 241 | 221 | 4 | 1960 | 2026 |
| corn_cbot | psd_ending_stocks_anomaly_pct | 241 | 221 | 4 | 1960 | 2026 |
| corn_cbot | psd_exports_anomaly_pct | 241 | 221 | 4 | 1960 | 2026 |
| corn_cbot | psd_imports_anomaly_pct | 241 | 220 | 4 | 1960 | 2026 |
| corn_cbot | psd_production_anomaly_pct | 241 | 221 | 4 | 1960 | 2026 |
| corn_cbot | psd_stock_to_use_anomaly_pct | 241 | 221 | 4 | 1960 | 2026 |
| rough_rice_cbot | psd_domestic_use_anomaly_pct | 268 | 248 | 4 | 1960 | 2026 |
| rough_rice_cbot | psd_ending_stocks_anomaly_pct | 268 | 217 | 4 | 1960 | 2026 |
| rough_rice_cbot | psd_exports_anomaly_pct | 268 | 248 | 4 | 1960 | 2026 |
| rough_rice_cbot | psd_imports_anomaly_pct | 268 | 226 | 4 | 1960 | 2026 |
| rough_rice_cbot | psd_production_anomaly_pct | 268 | 248 | 4 | 1960 | 2026 |
| rough_rice_cbot | psd_stock_to_use_anomaly_pct | 268 | 217 | 4 | 1960 | 2026 |
| soft_red_winter_wheat_cbot | psd_domestic_use_anomaly_pct | 67 | 62 | 1 | 1960 | 2026 |
| soft_red_winter_wheat_cbot | psd_ending_stocks_anomaly_pct | 67 | 62 | 1 | 1960 | 2026 |
| soft_red_winter_wheat_cbot | psd_exports_anomaly_pct | 67 | 62 | 1 | 1960 | 2026 |
| soft_red_winter_wheat_cbot | psd_imports_anomaly_pct | 67 | 62 | 1 | 1960 | 2026 |
| soft_red_winter_wheat_cbot | psd_production_anomaly_pct | 67 | 62 | 1 | 1960 | 2026 |
| soft_red_winter_wheat_cbot | psd_stock_to_use_anomaly_pct | 67 | 62 | 1 | 1960 | 2026 |
| soybean_meal_cbot | psd_domestic_use_anomaly_pct | 164 | 149 | 3 | 1964 | 2026 |
| soybean_meal_cbot | psd_ending_stocks_anomaly_pct | 164 | 149 | 3 | 1964 | 2026 |
| soybean_meal_cbot | psd_exports_anomaly_pct | 164 | 149 | 3 | 1964 | 2026 |
| soybean_meal_cbot | psd_imports_anomaly_pct | 164 | 129 | 3 | 1964 | 2026 |
| soybean_meal_cbot | psd_production_anomaly_pct | 164 | 149 | 3 | 1964 | 2026 |
| soybean_meal_cbot | psd_stock_to_use_anomaly_pct | 164 | 148 | 3 | 1964 | 2026 |
| soybean_oil_cbot | psd_domestic_use_anomaly_pct | 164 | 149 | 3 | 1964 | 2026 |
| soybean_oil_cbot | psd_ending_stocks_anomaly_pct | 164 | 149 | 3 | 1964 | 2026 |
| soybean_oil_cbot | psd_exports_anomaly_pct | 164 | 149 | 3 | 1964 | 2026 |
| soybean_oil_cbot | psd_imports_anomaly_pct | 164 | 133 | 3 | 1964 | 2026 |
| soybean_oil_cbot | psd_production_anomaly_pct | 164 | 149 | 3 | 1964 | 2026 |
| soybean_oil_cbot | psd_stock_to_use_anomaly_pct | 164 | 148 | 3 | 1964 | 2026 |
| soybeans_cbot | psd_domestic_use_anomaly_pct | 163 | 148 | 3 | 1964 | 2026 |
| soybeans_cbot | psd_ending_stocks_anomaly_pct | 163 | 148 | 3 | 1964 | 2026 |
| soybeans_cbot | psd_exports_anomaly_pct | 163 | 148 | 3 | 1964 | 2026 |
| soybeans_cbot | psd_imports_anomaly_pct | 163 | 129 | 3 | 1964 | 2026 |
| soybeans_cbot | psd_production_anomaly_pct | 163 | 148 | 3 | 1964 | 2026 |
| soybeans_cbot | psd_stock_to_use_anomaly_pct | 163 | 148 | 3 | 1964 | 2026 |

## Target Event Balance

| commodity | target_key | stress_event_direction | threshold_type | trainable_row_count | positive_event_count | positive_event_rate |
| --- | --- | --- | --- | --- | --- | --- |
| corn_cbot | psd_domestic_use_anomaly_pct | higher_is_stress | fixed_10pct | 221 | 103 | 0.4660633484162896 |
| corn_cbot | psd_domestic_use_anomaly_pct | higher_is_stress | fixed_5pct | 221 | 129 | 0.583710407239819 |
| corn_cbot | psd_domestic_use_anomaly_pct | higher_is_stress | history_quintile | 221 | 45 | 0.20361990950226244 |
| corn_cbot | psd_ending_stocks_anomaly_pct | lower_is_stress | fixed_10pct | 221 | 83 | 0.3755656108597285 |
| corn_cbot | psd_ending_stocks_anomaly_pct | lower_is_stress | fixed_5pct | 221 | 92 | 0.416289592760181 |
| corn_cbot | psd_ending_stocks_anomaly_pct | lower_is_stress | history_quintile | 221 | 45 | 0.20361990950226244 |
| corn_cbot | psd_exports_anomaly_pct | higher_is_stress | fixed_10pct | 221 | 116 | 0.5248868778280543 |
| corn_cbot | psd_exports_anomaly_pct | higher_is_stress | fixed_5pct | 221 | 124 | 0.5610859728506787 |
| corn_cbot | psd_exports_anomaly_pct | higher_is_stress | history_quintile | 221 | 45 | 0.20361990950226244 |
| corn_cbot | psd_imports_anomaly_pct | higher_is_stress | fixed_10pct | 220 | 105 | 0.4772727272727273 |
| corn_cbot | psd_imports_anomaly_pct | higher_is_stress | fixed_5pct | 220 | 114 | 0.5181818181818182 |
| corn_cbot | psd_imports_anomaly_pct | higher_is_stress | history_quintile | 220 | 44 | 0.2 |
| corn_cbot | psd_production_anomaly_pct | lower_is_stress | fixed_10pct | 221 | 26 | 0.11764705882352941 |
| corn_cbot | psd_production_anomaly_pct | lower_is_stress | fixed_5pct | 221 | 44 | 0.19909502262443438 |
| corn_cbot | psd_production_anomaly_pct | lower_is_stress | history_quintile | 221 | 45 | 0.20361990950226244 |
| corn_cbot | psd_stock_to_use_anomaly_pct | lower_is_stress | fixed_10pct | 221 | 92 | 0.416289592760181 |
| corn_cbot | psd_stock_to_use_anomaly_pct | lower_is_stress | fixed_5pct | 221 | 99 | 0.4479638009049774 |
| corn_cbot | psd_stock_to_use_anomaly_pct | lower_is_stress | history_quintile | 221 | 45 | 0.20361990950226244 |

## Static Feature Reuse

| feature_set_id | decision | availability_policy | allowed_snapshot_stages |
| --- | --- | --- | --- |
| balance_sheet | safe_if_prior_marketing_year | prior_marketing_year_at_snapshot | preseason,early_season,midseason,late_season,post_harvest,finalization |
| corn_preseason_core | safe_all_snapshots | annual_prior_or_preseason_context | preseason,early_season,midseason,late_season,post_harvest,finalization |
| crop_condition | stage_limited_requires_as_of_filter | inseason_observation_must_be_visible_by_snapshot | early_season,midseason,late_season,post_harvest,finalization |
| inseason_weather_dense | stage_limited_requires_as_of_filter | inseason_observation_must_be_visible_by_snapshot | early_season,midseason,late_season,post_harvest,finalization |
| physical_flow | stage_limited_requires_as_of_filter | inseason_observation_must_be_visible_by_snapshot | early_season,midseason,late_season,post_harvest,finalization |
| planting_incentives | safe_all_snapshots | lagged_certified_economic_driver | preseason,early_season,midseason,late_season,post_harvest,finalization |
| preseason_physical | safe_all_snapshots | annual_prior_or_preseason_context | preseason,early_season,midseason,late_season,post_harvest,finalization |
| trade_competitiveness | safe_all_snapshots | lagged_certified_economic_driver | preseason,early_season,midseason,late_season,post_harvest,finalization |
| wasde_monthly_revision | dynamic_snapshot_feature_not_static_join | computed_from_wasde_release_rows | preseason,early_season,midseason,late_season,post_harvest,finalization |

## Notes

- `silver/wasde` is the dynamic monthly release surface; raw WASDE cells must be
  aggregated into snapshot features rather than used as one row per cell.
- Current static gold/model-ready features can be reused where availability policy
  is safe for the snapshot date.
- Later CV must hold out whole contract/origin/market-year groups.
