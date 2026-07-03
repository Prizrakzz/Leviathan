# WASDE Snapshot Anomaly Detector RCA

## Executive Summary

Phase 3 reviewed the Phase 2 transparent detector backtest. The detector path is not ready for ML/meta-models yet because false positives are high, but the transparent WASDE scores do contain useful early-warning signal.

- Recommended next decision: `tune_threshold_policy`
- Reason: `false_positives_dominate_false_negatives`
- Best detector: `revision_streak` on `psd_ending_stocks_anomaly_pct`
- Best mean recall: `1.0`
- Best mean F2: `0.8202522115565595`
- Total false positives: `526`
- Total false negatives: `51`

Interpretation: high recall is real enough to keep going, but threshold policy and revision-streak overfiring need repair before adding broader context or tree models.

## Detector Summary

| target_key | detector_id | event_count | true_positive_count | false_negative_count | false_positive_count | mean_recall | mean_f2 | mean_top20_precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | revision_streak | 41 | 41 | 0 | 65 | 1.0 | 0.8202522115565595 | 0.4 |
| psd_stock_to_use_anomaly_pct | revision_streak | 49 | 49 | 0 | 57 | 1.0 | 0.8195947570947572 | 0.4666666666666667 |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 50 | 45 | 5 | 47 | 0.9404761904761905 | 0.7932932642754071 | 0.45161290322580644 |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 41 | 38 | 3 | 49 | 0.9275362318840579 | 0.8340466351829988 | 0.5806451612903226 |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 41 | 35 | 6 | 58 | 0.8840579710144927 | 0.7421536796536796 | 0.3225806451612903 |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 50 | 45 | 5 | 49 | 0.8839285714285714 | 0.8043612089664721 | 0.6451612903225806 |
| psd_ending_stocks_anomaly_pct | stage_level_z | 41 | 35 | 6 | 60 | 0.8623188405797101 | 0.7501762757444577 | 0.3225806451612903 |
| psd_stock_to_use_anomaly_pct | stage_level_z | 50 | 42 | 8 | 53 | 0.8392857142857143 | 0.7670905483405484 | 0.5806451612903226 |
| psd_stock_to_use_anomaly_pct | revision_shock | 50 | 41 | 9 | 42 | 0.8005952380952381 | 0.8118336798435483 | 0.6451612903225806 |
| psd_ending_stocks_anomaly_pct | revision_shock | 41 | 32 | 9 | 46 | 0.7753623188405797 | 0.8117244597507756 | 0.45161290322580644 |

## RCA Reason Summary

| case_type | target_key | detector_id | rca_reason_code | case_count |
| --- | --- | --- | --- | --- |
| false_negative | psd_ending_stocks_anomaly_pct | revision_shock | no_wasde_signal | 9 |
| false_negative | psd_stock_to_use_anomaly_pct | revision_shock | no_wasde_signal | 9 |
| false_negative | psd_ending_stocks_anomaly_pct | stage_level_percentile | threshold_too_strict | 5 |
| false_negative | psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | threshold_too_strict | 5 |
| false_negative | psd_ending_stocks_anomaly_pct | stage_level_z | stage_normalization_issue | 4 |
| false_negative | psd_stock_to_use_anomaly_pct | stage_level_percentile | threshold_too_strict | 4 |
| false_negative | psd_stock_to_use_anomaly_pct | stage_level_z | stage_normalization_issue | 4 |
| false_negative | psd_stock_to_use_anomaly_pct | stage_level_z | threshold_too_strict | 4 |
| false_negative | psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | threshold_too_strict | 3 |
| false_negative | psd_ending_stocks_anomaly_pct | stage_level_z | threshold_too_strict | 2 |
| false_negative | psd_ending_stocks_anomaly_pct | stage_level_percentile | stage_normalization_issue | 1 |
| false_negative | psd_stock_to_use_anomaly_pct | stage_level_percentile | stage_normalization_issue | 1 |
| false_positive | psd_ending_stocks_anomaly_pct | revision_streak | revision_streak_overfires | 65 |
| false_positive | psd_ending_stocks_anomaly_pct | stage_level_z | event_definition_too_narrow | 60 |
| false_positive | psd_stock_to_use_anomaly_pct | revision_streak | revision_streak_overfires | 57 |
| false_positive | psd_stock_to_use_anomaly_pct | stage_level_z | event_definition_too_narrow | 52 |
| false_positive | psd_ending_stocks_anomaly_pct | stage_level_percentile | threshold_too_loose | 47 |
| false_positive | psd_ending_stocks_anomaly_pct | revision_shock | event_definition_too_narrow | 44 |
| false_positive | psd_stock_to_use_anomaly_pct | revision_shock | event_definition_too_narrow | 41 |
| false_positive | psd_stock_to_use_anomaly_pct | stage_level_percentile | threshold_too_loose | 38 |
| false_positive | psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | threshold_too_loose | 26 |
| false_positive | psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | genuine_temporary_stress | 26 |
| false_positive | psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | genuine_temporary_stress | 23 |
| false_positive | psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | threshold_too_loose | 23 |
| false_positive | psd_ending_stocks_anomaly_pct | stage_level_percentile | event_definition_too_narrow | 11 |

## Threshold Stability

| target_key | detector_id | fold_count | threshold_min | threshold_median | threshold_max | threshold_std |
| --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 31 | 0.5004306836102661 | 0.5158831879475532 | 0.5606061290543631 | 0.015622473277340726 |
| psd_ending_stocks_anomaly_pct | revision_shock | 31 | 0.48956057769294786 | 0.9526853511592873 | 1.5879574471614062 | 0.29908841511907336 |
| psd_ending_stocks_anomaly_pct | revision_streak | 30 | -0.0 | 0.0 | 1.0 | 0.466091599699399 |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 31 | 0.8808823529411764 | 0.972972972972973 | 0.9849615558570782 | 0.028544510850148627 |
| psd_ending_stocks_anomaly_pct | stage_level_z | 31 | 1.1325452482773741 | 1.4387057311750107 | 1.941052392305206 | 0.21126866470536707 |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 31 | 0.5004306836102661 | 0.5133481474592997 | 0.5381125403427528 | 0.012351709125266114 |
| psd_stock_to_use_anomaly_pct | revision_shock | 31 | 0.48956057769294786 | 0.8993736265595738 | 1.0355795823483 | 0.1203831906549965 |
| psd_stock_to_use_anomaly_pct | revision_streak | 30 | -0.0 | 0.0 | 1.0 | 0.466091599699399 |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 31 | 0.8808823529411764 | 0.975 | 1.0 | 0.03150864910571506 |
| psd_stock_to_use_anomaly_pct | stage_level_z | 31 | 1.175732640293544 | 1.4387057311750107 | 1.941052392305206 | 0.1963591321083218 |

## Composite Dominance

| target_key | top_attribute | top_attribute_contribution_share | top_feature | top_feature_contribution_share | effective_component_count |
| --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | domestic_total | 0.1885291934182615 | wasde_domestic_total_latest | 0.0637074753022078 | 31.352259316735932 |
| psd_stock_to_use_anomaly_pct | domestic_total | 0.1885291934182615 | wasde_domestic_total_latest | 0.0637074753022078 | 31.352259316735932 |

## Top False Negatives

| target_key | detector_id | origin_key | target_market_year | max_score | threshold | score_threshold_margin | rca_reason_code |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_stock_to_use_anomaly_pct | stage_level_z | united_states | 1998 | 1.9172457619124215 | 1.941052392305206 | -0.023806630392784633 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | stage_level_z | united_states | 1999 | 1.5520965151887758 | 1.848808842389032 | -0.2967123272002563 | stage_normalization_issue |
| psd_stock_to_use_anomaly_pct | stage_level_z | united_states | 1999 | 1.5520965151887758 | 1.848808842389032 | -0.2967123272002563 | stage_normalization_issue |
| psd_ending_stocks_anomaly_pct | stage_level_z | united_states | 2020 | 1.3951654273819205 | 1.5941192571665277 | -0.19895382978460718 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | stage_level_z | united_states | 2020 | 1.3951654273819205 | 1.5941192571665277 | -0.19895382978460718 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | stage_level_z | united_states | 2022 | 1.299979743524825 | 1.5989073581030138 | -0.2989276145781887 | stage_normalization_issue |
| psd_ending_stocks_anomaly_pct | stage_level_z | united_states | 2021 | 1.2938200439695575 | 1.5941192571665277 | -0.30029921319697017 | stage_normalization_issue |
| psd_stock_to_use_anomaly_pct | stage_level_z | united_states | 2021 | 1.2938200439695575 | 1.5941192571665277 | -0.30029921319697017 | stage_normalization_issue |
| psd_ending_stocks_anomaly_pct | stage_level_z | argentina | 2000 | 1.2814164639559413 | 1.329101593062212 | -0.04768512910627076 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | stage_level_z | argentina | 2000 | 1.2814164639559413 | 1.329101593062212 | -0.04768512910627076 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2021 | 1.1914172301426948 | 1.542847571064061 | -0.35143034092136616 | no_wasde_signal |
| psd_stock_to_use_anomaly_pct | stage_level_z | ukraine | 2005 | 1.0177632999370887 | 1.185200425006487 | -0.16743712506939823 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | stage_level_z | ukraine | 2004 | 1.0174174302679344 | 1.2519863019880946 | -0.23456887172016017 | stage_normalization_issue |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | argentina | 2008 | 0.9855072463768116 | 1.0 | -0.01449275362318836 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | united_states | 2024 | 0.970873786407767 | 0.972972972972973 | -0.0020991865652060238 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | united_states | 2020 | 0.9583333333333334 | 0.9777777777777777 | -0.019444444444444375 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | united_states | 2020 | 0.9583333333333334 | 0.9777777777777777 | -0.019444444444444375 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | ukraine | 2023 | 0.9545454545454546 | 0.972972972972973 | -0.01842751842751844 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | ukraine | 2023 | 0.9545454545454546 | 0.972972972972973 | -0.01842751842751844 | threshold_too_strict |
| psd_stock_to_use_anomaly_pct | stage_level_z | ukraine | 2020 | 0.9429549239226906 | 1.5941192571665277 | -0.651164333243837 | stage_normalization_issue |
| psd_ending_stocks_anomaly_pct | stage_level_z | ukraine | 2020 | 0.9429549239226906 | 1.5941192571665277 | -0.651164333243837 | stage_normalization_issue |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | united_states | 2021 | 0.9230769230769231 | 0.975 | -0.05192307692307685 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | united_states | 2021 | 0.9230769230769231 | 0.975 | -0.05192307692307685 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | united_states | 2022 | 0.9223300970873787 | 0.9743589743589743 | -0.052028877271595664 | threshold_too_strict |
| psd_ending_stocks_anomaly_pct | revision_shock | ukraine | 2020 | 0.8885620872289192 | 1.5826946201242595 | -0.6941325328953404 | no_wasde_signal |

## Top False Positives

| target_key | detector_id | origin_key | target_market_year | first_alert_stage | max_score | threshold | score_threshold_margin | rca_reason_code |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2023 | midseason | 468.37271483297303 | 0.7365026391677365 | 467.6362121938053 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | united_states | 1998 | early_season | 65.61950929411162 | 0.8094371167662316 | 64.81007217734539 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2002 | preseason | 42.74607355212538 | 0.9207585844054221 | 41.82531496771996 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2002 | preseason | 42.74607355212538 | 0.9207585844054221 | 41.82531496771996 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | united_states | 2009 | late_season | 38.48965006218911 | 0.9740040565222918 | 37.51564600566682 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2010 | preseason | 24.990535843001368 | 1.0148363652638395 | 23.97569947773753 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2010 | preseason | 24.990535843001368 | 1.0148363652638395 | 23.97569947773753 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | revision_shock | argentina | 1997 | preseason | 14.774055884310451 | 0.785025721561521 | 13.98903016274893 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | argentina | 1997 | preseason | 14.774055884310451 | 0.785025721561521 | 13.98903016274893 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2009 | early_season | 14.548029464168566 | 0.9740040565222918 | 13.574025407646275 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2009 | early_season | 14.548029464168566 | 0.9740040565222918 | 13.574025407646275 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | stage_level_z | ukraine | 2019 | early_season | 14.526708764283415 | 1.5927224363075103 | 12.933986327975905 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | stage_level_z | ukraine | 2019 | early_season | 14.526708764283415 | 1.5927224363075103 | 12.933986327975905 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2014 | midseason | 13.776122188871359 | 0.9733709660154851 | 12.802751222855873 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | brazil | 2014 | midseason | 13.776122188871359 | 0.9733709660154851 | 12.802751222855873 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | argentina | 2010 | preseason | 13.358514472998813 | 1.0148363652638395 | 12.343678107734974 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | revision_shock | argentina | 2010 | preseason | 13.358514472998813 | 1.0148363652638395 | 12.343678107734974 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | stage_level_z | brazil | 2024 | preseason | 12.781766547638009 | 1.5955504267581868 | 11.186216120879822 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | stage_level_z | brazil | 2024 | preseason | 12.781766547638009 | 1.5955504267581868 | 11.186216120879822 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | stage_level_z | brazil | 2018 | preseason | 12.213024610931948 | 1.5821985377796919 | 10.630826073152257 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | stage_level_z | brazil | 2018 | preseason | 12.213024610931948 | 1.5821985377796919 | 10.630826073152257 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | revision_shock | ukraine | 2019 | midseason | 11.12497871976174 | 0.8232585460579687 | 10.301720173703771 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | ukraine | 2019 | midseason | 11.12497871976174 | 1.5857052594656196 | 9.53927346029612 | event_definition_too_narrow |
| psd_ending_stocks_anomaly_pct | revision_shock | united_states | 2000 | late_season | 10.01260664938486 | 0.9526853511592873 | 9.059921298225573 | event_definition_too_narrow |
| psd_stock_to_use_anomaly_pct | revision_shock | brazil | 2013 | early_season | 9.91624167705249 | 1.0120733200820435 | 8.904168356970446 | event_definition_too_narrow |

## Phase 4 Implication

Do not jump to LightGBM/XGBoost yet. First tighten threshold policy, especially for revision streaks, then rerun Phase 2. If false positives remain high but economically plausible, Phase 4 should add substitute/context surfaces and compare whether broader WASDE context reduces noisy alerts.
