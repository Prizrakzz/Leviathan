# WASDE Snapshot Anomaly Phase 5 Root-Cause Audit

## Executive Summary

Phase 5 audits the repaired Phase 4B detector output before any more ML sweeps. It asks whether poor behavior is coming from target-label design, unstable score normalization, revision-streak mechanics, or threshold policy.

- Recommended next step: `fix_stage_level_z_before_more_sweeps`
- Blockers: `repair_stage_normalization, repair_revision_streak_magnitude_filter, retune_threshold_policy_after_score_repairs`
- Stage normalization issue rows: `2`
- Revision-streak issue rows: `2`
- Event-definition issue rows: `0`
- Threshold-policy issue rows: `8`

Interpretation: this is a go/no-go diagnostic layer. A blocker here means we should repair the transparent detector or event definition before promoting the scores into LightGBM/XGBoost meta-model experiments.

## Event Label Audit

| target_key | detector_id | false_positive_count | false_negative_count | soft_stress_false_positive_count | weak_stress_false_positive_count | benign_false_positive_count | near_miss_false_positive_share | event_definition_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 54 | 5 | 3 | 2 | 49 | 0.09259259259259259 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | stage_level_z | 45 | 16 | 0 | 3 | 42 | 0.06666666666666667 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 44 | 5 | 0 | 3 | 41 | 0.06818181818181818 | detector_overalerts_benign_cases |
| psd_ending_stocks_anomaly_pct | revision_shock | 40 | 12 | 3 | 2 | 35 | 0.125 | detector_overalerts_benign_cases |
| psd_ending_stocks_anomaly_pct | stage_level_z | 39 | 17 | 3 | 2 | 34 | 0.1282051282051282 | detector_overalerts_benign_cases |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 39 | 5 | 3 | 1 | 35 | 0.10256410256410256 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | revision_shock | 37 | 18 | 0 | 2 | 35 | 0.05405405405405406 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 35 | 12 | 0 | 3 | 32 | 0.08571428571428572 | detector_overalerts_benign_cases |
| psd_ending_stocks_anomaly_pct | revision_streak | 33 | 17 | 2 | 1 | 30 | 0.09090909090909091 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | revision_streak | 27 | 19 | 0 | 1 | 26 | 0.037037037037037035 | detector_overalerts_benign_cases |

## Stage Normalization Audit

| target_key | detector_id | threshold_median | threshold_max | threshold_std | absurd_threshold_count | threshold_cap | normalization_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | stage_level_z | 1.6166519565763349 | 109.76408648130317 | 19.343069148211384 | 1 | 8.0 | unstable_threshold_scale |
| psd_stock_to_use_anomaly_pct | stage_level_z | 1.5 | 109.76408648130317 | 19.43919099320612 | 1 | 8.0 | unstable_threshold_scale |
| psd_ending_stocks_anomaly_pct | revision_shock | 1.25 | 2.657532623754334 | 0.3225252415962198 | 0 | 8.0 | ok |
| psd_stock_to_use_anomaly_pct | revision_shock | 1.25 | 2.657532623754334 | 0.31988038833047183 | 0 | 8.0 | ok |
| psd_ending_stocks_anomaly_pct | revision_streak | 2.0 | 2.0 | 0.0 | 0 | 12.0 | ok |
| psd_stock_to_use_anomaly_pct | revision_streak | 2.0 | 2.0 | 0.0 | 0 | 12.0 | ok |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 0.95 | 1.0 | 0.021251185925162088 | 0 | 1.0 | ok |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 1.0 | 1.0 | 0.02508051550635507 | 0 | 1.0 | ok |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 0.5206221834244167 | 0.5270893927378558 | 0.002703246294846786 | 0 | 1.0 | ok |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 0.52 | 0.5251347345664374 | 0.0012195970937224233 | 0 | 1.0 | ok |

## Score Scale Audit

| target_key | detector_id | score_q95 | score_q99 | score_max | extreme_score_count | score_cap | score_scale_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | revision_shock | 4.330207597671834 | 12.078307222016731 | 468.37271483297303 | 47 | 8.0 | extreme_scores_present |
| psd_stock_to_use_anomaly_pct | revision_shock | 4.330207597671834 | 12.078307222016731 | 468.37271483297303 | 47 | 8.0 | extreme_scores_present |
| psd_ending_stocks_anomaly_pct | stage_level_z | 3.3545441375815654 | 6.387909702201817 | 16.58596464745205 | 17 | 8.0 | extreme_scores_present |
| psd_stock_to_use_anomaly_pct | stage_level_z | 3.3545441375815654 | 6.387909702201817 | 16.58596464745205 | 17 | 8.0 | extreme_scores_present |
| psd_ending_stocks_anomaly_pct | revision_streak | 2.0 | 3.6799999999998363 | 7.0 | 0 | 12.0 | ok |
| psd_stock_to_use_anomaly_pct | revision_streak | 2.0 | 3.6799999999998363 | 7.0 | 0 | 12.0 | ok |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 1.0 | 1.0 | 1.0 | 0 | 1.0 | ok |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 1.0 | 1.0 | 1.0 | 0 | 1.0 | ok |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 0.5822036540733883 | 0.622247540974474 | 0.8488213617507204 | 0 | 1.0 | ok |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 0.5822036540733883 | 0.622247540974474 | 0.8488213617507204 | 0 | 1.0 | ok |

## Revision Streak Audit

| target_key | false_positive_count | false_negative_count | soft_stress_false_positive_count | benign_false_positive_count | mean_raw_alerts_per_case | mean_final_alerts_per_case | revision_streak_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | 33 | 17 | 2 | 30 | 2.169811320754717 | 1.3679245283018868 | magnitude_filter_needed |
| psd_stock_to_use_anomaly_pct | 27 | 19 | 0 | 26 | 2.169811320754717 | 1.3679245283018868 | magnitude_filter_needed |

## Threshold Tradeoff Audit

| target_key | detector_id | mean_fold_recall | mean_fold_precision | mean_fold_f2 | false_positive_count | false_negative_count | threshold_policy_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 0.9136904761904762 | 0.5305555555555556 | 0.8075887319308372 | 44 | 5 | acceptable_tradeoff_candidate |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 0.9057971014492753 | 0.5111111111111111 | 0.8083160800552105 | 39 | 5 | acceptable_tradeoff_candidate |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 0.9057971014492753 | 0.41944444444444445 | 0.761634199134199 | 54 | 5 | precision_too_low |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 0.7232142857142857 | 0.5222222222222223 | 0.794181330365541 | 35 | 12 | recall_loss |
| psd_ending_stocks_anomaly_pct | revision_shock | 0.6956521739130435 | 0.3879310344827586 | 0.7757466299132966 | 40 | 12 | recall_loss |
| psd_stock_to_use_anomaly_pct | stage_level_z | 0.6666666666666667 | 0.46296296296296297 | 0.7255755608028335 | 45 | 16 | recall_loss |
| psd_stock_to_use_anomaly_pct | revision_streak | 0.6604938271604938 | 0.5246913580246914 | 0.8060498529248529 | 27 | 19 | recall_loss |
| psd_ending_stocks_anomaly_pct | stage_level_z | 0.644927536231884 | 0.3977272727272727 | 0.7102729786553317 | 39 | 17 | recall_loss |
| psd_stock_to_use_anomaly_pct | revision_shock | 0.6279761904761905 | 0.47413793103448276 | 0.7427368577578661 | 37 | 18 | recall_loss |
| psd_ending_stocks_anomaly_pct | revision_streak | 0.6014492753623188 | 0.4166666666666667 | 0.7334797555385791 | 33 | 17 | recall_loss |

## Top False-Positive Severity Cases

| target_key | detector_id | origin_key | target_market_year | stress_ratio_to_hard_threshold | target_severity_band | max_score | threshold | first_alert_stage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | united_states | 2022 | 0.7379736362352777 | weak_stress_near_miss | 0.5710068928924195 | 0.52 | preseason |
| psd_stock_to_use_anomaly_pct | revision_shock | ukraine | 2011 | 0.7171938386610371 | weak_stress_near_miss | 9.08704947607123 | 1.25 | late_season |
| psd_stock_to_use_anomaly_pct | stage_level_z | ukraine | 2011 | 0.7171938386610371 | weak_stress_near_miss | 3.237578969754516 | 1.5 | preseason |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | ukraine | 2011 | 0.7171938386610371 | weak_stress_near_miss | 1.0 | 1.0 | post_harvest |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | ukraine | 2011 | 0.7171938386610371 | weak_stress_near_miss | 0.5861233773638647 | 0.52 | midseason |
| psd_ending_stocks_anomaly_pct | revision_shock | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 38.48965006218911 | 1.25 | post_harvest |
| psd_ending_stocks_anomaly_pct | revision_streak | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 5.0 | 2.0 | early_season |
| psd_ending_stocks_anomaly_pct | stage_level_z | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 3.0768244367924336 | 1.5 | late_season |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 1.0 | 0.95 | late_season |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 0.6166766548003552 | 0.52 | post_harvest |
| psd_ending_stocks_anomaly_pct | stage_level_z | ukraine | 2012 | 0.5805960278173036 | weak_stress_near_miss | 6.635868886687699 | 1.5 | preseason |
| psd_ending_stocks_anomaly_pct | revision_shock | ukraine | 2012 | 0.5805960278173036 | weak_stress_near_miss | 3.736016647812759 | 1.25 | early_season |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | ukraine | 2012 | 0.5805960278173036 | weak_stress_near_miss | 1.0 | 0.95 | preseason |
| psd_stock_to_use_anomaly_pct | revision_streak | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 5.0 | 2.0 | midseason |
| psd_stock_to_use_anomaly_pct | revision_shock | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 3.6249394063963467 | 1.4766649624024577 | late_season |
| psd_stock_to_use_anomaly_pct | stage_level_z | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 3.0020735594813917 | 1.5 | preseason |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 1.0 | 1.0 | preseason |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 0.6476635788314173 | 0.5240861903481375 | early_season |
| psd_stock_to_use_anomaly_pct | stage_level_z | argentina | 2013 | 0.5294091401684957 | weak_stress_near_miss | 2.9609268490967824 | 1.5 | preseason |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | argentina | 2013 | 0.5294091401684957 | weak_stress_near_miss | 1.0 | 0.95 | preseason |

## Phase 5 Implication

Do not run broader model sweeps until the listed blockers are addressed. If event-definition pressure is high, add a watchlist/soft-stress label. If z-score scale is unstable, repair normalization with robust prior-only scaling or caps. If revision streak still overfires, require directional magnitude and cumulative revision confirmation.
