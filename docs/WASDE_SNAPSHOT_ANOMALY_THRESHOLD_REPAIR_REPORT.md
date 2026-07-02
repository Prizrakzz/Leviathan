# WASDE Snapshot Anomaly Threshold Repair Report

## Executive Summary

Phase 4B reviewed the transparent detector backtest. The detector path is not ready for ML/meta-models yet if false positives remain high, but the transparent WASDE scores do contain useful early-warning signal when recall survives stricter threshold policy.

- Recommended next decision: `tune_threshold_policy`
- Reason: `revision_streak_overfires_present`
- Best detector: `stage_level_percentile` on `psd_stock_to_use_anomaly_pct`
- Best mean recall: `0.9136904761904762`
- Best mean F2: `0.8075887319308372`
- Total false positives: `393`
- Total false negatives: `126`

Interpretation: high recall is real enough to keep going, but threshold policy and revision-streak overfiring need repair before adding broader context or tree models.

## Detector Summary

| target_key | detector_id | event_count | true_positive_count | false_negative_count | false_positive_count | mean_recall | mean_f2 | mean_top20_precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 50 | 45 | 5 | 44 | 0.9136904761904762 | 0.8075887319308372 | 0.45161290322580644 |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 41 | 36 | 5 | 39 | 0.9057971014492753 | 0.8083160800552105 | 0.5806451612903226 |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 41 | 36 | 5 | 54 | 0.9057971014492753 | 0.761634199134199 | 0.3225806451612903 |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 50 | 38 | 12 | 35 | 0.7232142857142857 | 0.794181330365541 | 0.6451612903225806 |
| psd_ending_stocks_anomaly_pct | revision_shock | 41 | 29 | 12 | 40 | 0.6956521739130435 | 0.7757466299132966 | 0.45161290322580644 |
| psd_stock_to_use_anomaly_pct | stage_level_z | 50 | 34 | 16 | 45 | 0.6666666666666667 | 0.7255755608028335 | 0.5806451612903226 |
| psd_stock_to_use_anomaly_pct | revision_streak | 49 | 30 | 19 | 27 | 0.6604938271604938 | 0.8060498529248529 | 0.4666666666666667 |
| psd_ending_stocks_anomaly_pct | stage_level_z | 41 | 24 | 17 | 39 | 0.644927536231884 | 0.7102729786553317 | 0.3225806451612903 |
| psd_stock_to_use_anomaly_pct | revision_shock | 50 | 32 | 18 | 37 | 0.6279761904761905 | 0.7427368577578661 | 0.6451612903225806 |
| psd_ending_stocks_anomaly_pct | revision_streak | 41 | 24 | 17 | 33 | 0.6014492753623188 | 0.7334797555385791 | 0.4 |

## RCA Reason Summary

| case_type | target_key | detector_id | rca_reason_code | case_count |
| --- | --- | --- | --- | --- |
| false_negative | psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | threshold_too_strict | 12 |
| false_negative | psd_stock_to_use_anomaly_pct | revision_shock | no_wasde_signal | 12 |
| false_negative | psd_ending_stocks_anomaly_pct | revision_streak | threshold_too_strict | 11 |
| false_negative | psd_ending_stocks_anomaly_pct | stage_level_z | stage_normalization_issue | 11 |
| false_negative | psd_stock_to_use_anomaly_pct | revision_streak | threshold_too_strict | 11 |
| false_negative | psd_stock_to_use_anomaly_pct | stage_level_z | threshold_too_strict | 10 |
| false_negative | psd_ending_stocks_anomaly_pct | revision_shock | no_wasde_signal | 8 |
| false_negative | psd_stock_to_use_anomaly_pct | revision_streak | no_wasde_signal | 8 |
| false_negative | psd_ending_stocks_anomaly_pct | revision_streak | no_wasde_signal | 6 |
| false_negative | psd_ending_stocks_anomaly_pct | stage_level_z | threshold_too_strict | 6 |
| false_negative | psd_stock_to_use_anomaly_pct | revision_shock | threshold_too_strict | 6 |
| false_negative | psd_stock_to_use_anomaly_pct | stage_level_z | stage_normalization_issue | 6 |
| false_negative | psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | threshold_too_strict | 5 |
| false_negative | psd_ending_stocks_anomaly_pct | revision_shock | threshold_too_strict | 4 |
| false_negative | psd_ending_stocks_anomaly_pct | stage_level_percentile | threshold_too_strict | 4 |
| false_negative | psd_stock_to_use_anomaly_pct | stage_level_percentile | threshold_too_strict | 4 |
| false_negative | psd_ending_stocks_anomaly_pct | stage_level_percentile | stage_normalization_issue | 1 |
| false_negative | psd_stock_to_use_anomaly_pct | stage_level_percentile | stage_normalization_issue | 1 |
| false_positive | psd_ending_stocks_anomaly_pct | stage_level_percentile | benign_final_outcome | 42 |
| false_positive | psd_stock_to_use_anomaly_pct | stage_level_z | benign_final_outcome | 41 |
| false_positive | psd_ending_stocks_anomaly_pct | revision_shock | benign_final_outcome | 35 |
| false_positive | psd_stock_to_use_anomaly_pct | revision_shock | benign_final_outcome | 35 |
| false_positive | psd_ending_stocks_anomaly_pct | stage_level_z | benign_final_outcome | 34 |
| false_positive | psd_ending_stocks_anomaly_pct | revision_streak | revision_streak_overfires | 33 |
| false_positive | psd_stock_to_use_anomaly_pct | revision_streak | revision_streak_overfires | 27 |

## Threshold Stability

| target_key | detector_id | fold_count | threshold_min | threshold_median | threshold_max | threshold_std |
| --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 31 | 0.52 | 0.52 | 0.5251347345664374 | 0.0012195970937224428 |
| psd_ending_stocks_anomaly_pct | revision_shock | 31 | 1.25 | 1.25 | 2.657532623754334 | 0.3225252415962198 |
| psd_ending_stocks_anomaly_pct | revision_streak | 30 | 2.0 | 2.0 | 2.0 | 0.0 |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 31 | 0.95 | 0.95 | 1.0 | 0.02125118592516207 |
| psd_ending_stocks_anomaly_pct | stage_level_z | 31 | 1.5 | 1.6166519565763349 | 109.76408648130317 | 19.343069148211388 |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 31 | 0.52 | 0.5206221834244167 | 0.5270893927378558 | 0.0027032462948467753 |
| psd_stock_to_use_anomaly_pct | revision_shock | 31 | 1.25 | 1.25 | 2.657532623754334 | 0.31988038833047167 |
| psd_stock_to_use_anomaly_pct | revision_streak | 30 | 2.0 | 2.0 | 2.0 | 0.0 |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 31 | 0.95 | 1.0 | 1.0 | 0.02508051550635507 |
| psd_stock_to_use_anomaly_pct | stage_level_z | 31 | 1.5 | 1.5 | 109.76408648130317 | 19.439190993206125 |

## Composite Dominance

| target_key | top_attribute | top_attribute_contribution_share | top_feature | top_feature_contribution_share | effective_component_count |
| --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | domestic_total | 0.1885291934182615 | wasde_domestic_total_latest | 0.0637074753022078 | 31.352259316735932 |
| psd_stock_to_use_anomaly_pct | domestic_total | 0.1885291934182615 | wasde_domestic_total_latest | 0.0637074753022078 | 31.352259316735932 |

## Top False Negatives

| target_key | detector_id | origin_key | target_market_year | max_score | threshold | score_threshold_margin | rca_reason_code |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | revision_shock | argentina | 1995 | 433.19900271931834 | 2.657532623754334 | 430.541470095564 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | revision_shock | argentina | 1995 | 433.19900271931834 | 2.657532623754334 | 430.541470095564 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | revision_shock | argentina | 2011 | 9.537177108755024 | 1.25 | 8.287177108755024 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | revision_shock | argentina | 2011 | 9.537177108755024 | 1.25 | 8.287177108755024 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | stage_level_z | argentina | 2025 | 5.843935123212447 | 1.5 | 4.343935123212447 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | revision_shock | ukraine | 2005 | 4.567048668631849 | 1.4766649624024577 | 3.0903837062293915 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | revision_shock | argentina | 2000 | 4.066990106424515 | 1.8268711643942892 | 2.240118942030226 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | revision_shock | argentina | 2000 | 4.066990106424515 | 1.8268711643942892 | 2.240118942030226 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | revision_streak | brazil | 2023 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | revision_streak | ukraine | 2024 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | revision_streak | ukraine | 2020 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | revision_streak | ukraine | 2020 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | revision_streak | ukraine | 2007 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | revision_streak | ukraine | 2007 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | revision_streak | united_states | 2013 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | revision_streak | united_states | 2013 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | revision_streak | ukraine | 2024 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | revision_streak | united_states | 2024 | 3.0 | 2.0 | 1.0 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | stage_level_z | united_states | 2000 | 2.8796991180232503 | 1.767839113912913 | 1.1118600041103373 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | stage_level_z | united_states | 1995 | 2.6372891746093234 | 109.76408648130317 | -107.12679730669385 | stage_normalization_issue |
| psd_ending_stocks_anomaly_pct | stage_level_z | united_states | 1995 | 2.6372891746093234 | 109.76408648130317 | -107.12679730669385 | stage_normalization_issue |
| psd_stock_to_use_anomaly_pct | stage_level_z | argentina | 1995 | 2.329372337908172 | 109.76408648130317 | -107.434714143395 | stage_normalization_issue |
| psd_ending_stocks_anomaly_pct | stage_level_z | argentina | 1995 | 2.329372337908172 | 109.76408648130317 | -107.434714143395 | stage_normalization_issue |
| psd_ending_stocks_anomaly_pct | stage_level_z | brazil | 2020 | 2.238645436357804 | 3.23036651547279 | -0.9917210791149857 | stage_normalization_issue |
| psd_ending_stocks_anomaly_pct | stage_level_z | brazil | 2021 | 2.1362022302470787 | 3.2069990438956824 | -1.0707968136486037 | stage_normalization_issue |

## Top False Positives

| target_key | detector_id | origin_key | target_market_year | first_alert_stage | max_score | threshold | score_threshold_margin | rca_reason_code |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2023 | midseason | 468.37271483297303 | 1.25 | 467.12271483297303 | final_outcome_reversal |
| psd_ending_stocks_anomaly_pct | revision_shock | united_states | 1998 | finalization | 65.61950929411162 | 1.8248543709161014 | 63.79465492319552 | final_outcome_reversal |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2002 | post_harvest | 42.74607355212538 | 1.3996650029739672 | 41.34640854915141 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2002 | post_harvest | 42.74607355212538 | 1.3996650029739672 | 41.34640854915141 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | united_states | 2009 | post_harvest | 38.48965006218911 | 1.25 | 37.23965006218911 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2010 | early_season | 24.990535843001368 | 1.25 | 23.740535843001368 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2010 | early_season | 24.990535843001368 | 1.25 | 23.740535843001368 | benign_final_outcome |
| psd_stock_to_use_anomaly_pct | revision_shock | argentina | 1997 | preseason | 14.774055884310451 | 1.8832302887109744 | 12.890825595599477 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | argentina | 1997 | preseason | 14.774055884310451 | 1.8832302887109744 | 12.890825595599477 | benign_final_outcome |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2009 | post_harvest | 14.548029464168566 | 1.25 | 13.298029464168566 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2009 | post_harvest | 14.548029464168566 | 1.25 | 13.298029464168566 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2014 | late_season | 13.776122188871359 | 1.25 | 12.526122188871359 | benign_final_outcome |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2014 | late_season | 13.776122188871359 | 1.25 | 12.526122188871359 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | argentina | 2010 | early_season | 13.358514472998813 | 1.25 | 12.108514472998813 | benign_final_outcome |
| psd_stock_to_use_anomaly_pct | revision_shock | argentina | 2010 | early_season | 13.358514472998813 | 1.25 | 12.108514472998813 | benign_final_outcome |
| psd_stock_to_use_anomaly_pct | stage_level_z | brazil | 2024 | preseason | 12.781766547638009 | 1.5 | 11.281766547638009 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | stage_level_z | brazil | 2024 | preseason | 12.781766547638009 | 3.233079138014174 | 9.548687409623835 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | stage_level_z | brazil | 2018 | post_harvest | 12.213024610931948 | 3.146137786825053 | 9.066886824106895 | benign_final_outcome |
| psd_stock_to_use_anomaly_pct | stage_level_z | brazil | 2018 | preseason | 12.213024610931948 | 1.5 | 10.713024610931948 | benign_final_outcome |
| psd_stock_to_use_anomaly_pct | revision_shock | ukraine | 2019 | midseason | 11.12497871976174 | 1.25 | 9.87497871976174 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | ukraine | 2019 | midseason | 11.12497871976174 | 1.25 | 9.87497871976174 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | united_states | 2000 | post_harvest | 10.01260664938486 | 1.8268711643942892 | 8.185735484990571 | benign_final_outcome |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2013 | late_season | 9.91624167705249 | 1.25 | 8.66624167705249 | benign_final_outcome |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2013 | late_season | 9.91624167705249 | 1.25 | 8.66624167705249 | benign_final_outcome |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2011 | post_harvest | 9.661397296964903 | 1.25 | 8.411397296964903 | benign_final_outcome |

## Phase 4 Implication

Do not jump to LightGBM/XGBoost yet. First tighten threshold policy, especially for revision streaks, then rerun Phase 2. If false positives remain high but economically plausible, Phase 4 should add substitute/context surfaces and compare whether broader WASDE context reduces noisy alerts.
