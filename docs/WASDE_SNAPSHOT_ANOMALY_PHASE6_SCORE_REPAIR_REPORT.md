# WASDE Snapshot Anomaly Phase 6 Score Repair Report

## Executive Summary

Phase 6 audits the detector output before any more ML sweeps. It asks whether poor behavior is coming from target-label design, unstable score normalization, revision-streak mechanics, or threshold policy.

- Recommended next step: `retune_threshold_policy`
- Blockers: `retune_threshold_policy_after_score_repairs`
- Stage normalization issue rows: `0`
- Revision-streak issue rows: `0`
- Event-definition issue rows: `0`
- Threshold-policy issue rows: `7`

Interpretation: this is a go/no-go diagnostic layer. A blocker here means we should repair the transparent detector or event definition before promoting the scores into LightGBM/XGBoost meta-model experiments.

## Event Label Audit

| target_key | detector_id | false_positive_count | false_negative_count | soft_stress_false_positive_count | weak_stress_false_positive_count | benign_false_positive_count | near_miss_false_positive_share | event_definition_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 54 | 5 | 3 | 2 | 49 | 0.09259259259259259 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | stage_level_z | 47 | 11 | 0 | 3 | 44 | 0.06382978723404255 | detector_overalerts_benign_cases |
| psd_ending_stocks_anomaly_pct | stage_level_z | 44 | 13 | 3 | 2 | 39 | 0.11363636363636363 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 44 | 5 | 0 | 3 | 41 | 0.06818181818181818 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | revision_shock | 40 | 14 | 0 | 2 | 38 | 0.05 | detector_overalerts_benign_cases |
| psd_ending_stocks_anomaly_pct | revision_shock | 40 | 10 | 3 | 1 | 36 | 0.1 | detector_overalerts_benign_cases |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 38 | 6 | 3 | 2 | 33 | 0.13157894736842105 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 33 | 12 | 0 | 2 | 31 | 0.06060606060606061 | detector_overalerts_benign_cases |
| psd_ending_stocks_anomaly_pct | revision_streak | 12 | 28 | 0 | 1 | 11 | 0.08333333333333333 | detector_overalerts_benign_cases |
| psd_stock_to_use_anomaly_pct | revision_streak | 10 | 34 | 0 | 1 | 9 | 0.1 | detector_overalerts_benign_cases |

## Stage Normalization Audit

| target_key | detector_id | threshold_median | threshold_max | threshold_std | absurd_threshold_count | threshold_cap | normalization_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | stage_level_z | 1.5601623491524368 | 8.0 | 1.4464205414055757 | 0 | 8.0 | ok |
| psd_stock_to_use_anomaly_pct | stage_level_z | 1.5 | 8.0 | 1.1648819619743394 | 0 | 8.0 | ok |
| psd_ending_stocks_anomaly_pct | revision_shock | 2.038094227070945 | 3.0139692187691267 | 0.29225098694370244 | 0 | 8.0 | ok |
| psd_stock_to_use_anomaly_pct | revision_shock | 1.9757443419206764 | 3.0139692187691267 | 0.48090316503264924 | 0 | 8.0 | ok |
| psd_ending_stocks_anomaly_pct | revision_streak | 2.0 | 2.0 | 0.0 | 0 | 12.0 | ok |
| psd_stock_to_use_anomaly_pct | revision_streak | 2.0 | 2.0 | 0.0 | 0 | 12.0 | ok |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 0.95 | 1.0 | 0.021251185925162088 | 0 | 1.0 | ok |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 1.0 | 1.0 | 0.02508051550635507 | 0 | 1.0 | ok |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 0.52 | 0.5496874213701379 | 0.011128534015905458 | 0 | 1.0 | ok |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 0.5346842116096353 | 0.5496874213701379 | 0.010913944540759939 | 0 | 1.0 | ok |

## Score Scale Audit

| target_key | detector_id | score_q95 | score_q99 | score_max | extreme_score_count | score_cap | score_scale_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | revision_shock | 8.0 | 8.0 | 8.0 | 0 | 8.0 | ok |
| psd_ending_stocks_anomaly_pct | stage_level_z | 3.9678709453769208 | 8.0 | 8.0 | 0 | 8.0 | ok |
| psd_stock_to_use_anomaly_pct | revision_shock | 8.0 | 8.0 | 8.0 | 0 | 8.0 | ok |
| psd_stock_to_use_anomaly_pct | stage_level_z | 3.9678709453769208 | 8.0 | 8.0 | 0 | 8.0 | ok |
| psd_ending_stocks_anomaly_pct | revision_streak | 4.0 | 5.030000000000001 | 6.0 | 0 | 12.0 | ok |
| psd_stock_to_use_anomaly_pct | revision_streak | 4.0 | 5.030000000000001 | 6.0 | 0 | 12.0 | ok |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 1.0 | 1.0 | 1.0 | 0 | 1.0 | ok |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 1.0 | 1.0 | 1.0 | 0 | 1.0 | ok |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 0.6274709571800089 | 0.6928059570012715 | 0.8884357474048147 | 0 | 1.0 | ok |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 0.6274709571800089 | 0.6928059570012715 | 0.8884357474048147 | 0 | 1.0 | ok |

## Revision Streak Audit

| target_key | false_positive_count | false_negative_count | soft_stress_false_positive_count | benign_false_positive_count | mean_raw_alerts_per_case | mean_final_alerts_per_case | revision_streak_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_ending_stocks_anomaly_pct | 12 | 28 | 0 | 11 | 0.9245283018867925 | 0.4528301886792453 | diagnostic_only_low_recall |
| psd_stock_to_use_anomaly_pct | 10 | 34 | 0 | 9 | 0.9245283018867925 | 0.4528301886792453 | diagnostic_only_low_recall |

## Threshold Tradeoff Audit

| target_key | detector_id | mean_fold_recall | mean_fold_precision | mean_fold_f2 | false_positive_count | false_negative_count | threshold_policy_diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | 0.9136904761904762 | 0.5305555555555556 | 0.8075887319308372 | 44 | 5 | acceptable_tradeoff_candidate |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | 0.9057971014492753 | 0.41944444444444445 | 0.761634199134199 | 54 | 5 | precision_too_low |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | 0.8492063492063492 | 0.5 | 0.8026903651903652 | 38 | 6 | acceptable_tradeoff_candidate |
| psd_stock_to_use_anomaly_pct | stage_level_z | 0.7738095238095238 | 0.48850574712643674 | 0.7770637926887928 | 47 | 11 | acceptable_tradeoff_candidate |
| psd_ending_stocks_anomaly_pct | revision_shock | 0.7608695652173914 | 0.41388888888888886 | 0.7671113608613609 | 40 | 10 | precision_too_low |
| psd_ending_stocks_anomaly_pct | stage_level_z | 0.7246376811594203 | 0.37666666666666665 | 0.7643247955747956 | 44 | 13 | recall_loss |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | 0.7211538461538461 | 0.5416666666666666 | 0.7664538412146068 | 33 | 12 | recall_loss |
| psd_stock_to_use_anomaly_pct | revision_shock | 0.7083333333333333 | 0.49166666666666664 | 0.7636128967650706 | 40 | 14 | recall_loss |
| psd_stock_to_use_anomaly_pct | revision_streak | 0.3302469135802469 | 0.6203703703703703 | 0.6845735963383023 | 10 | 34 | recall_loss |
| psd_ending_stocks_anomaly_pct | revision_streak | 0.30434782608695654 | 0.5185185185185186 | 0.7035409035409035 | 12 | 28 | recall_loss |

## Top False-Positive Severity Cases

| target_key | detector_id | origin_key | target_market_year | stress_ratio_to_hard_threshold | target_severity_band | max_score | threshold | first_alert_stage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | united_states | 2022 | 0.7379736362352777 | weak_stress_near_miss | 0.63633120636189 | 0.52 | preseason |
| psd_stock_to_use_anomaly_pct | revision_shock | ukraine | 2011 | 0.7171938386610371 | weak_stress_near_miss | 8.0 | 2.018630775619544 | late_season |
| psd_stock_to_use_anomaly_pct | stage_level_z | ukraine | 2011 | 0.7171938386610371 | weak_stress_near_miss | 5.287462449866826 | 1.5 | preseason |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | ukraine | 2011 | 0.7171938386610371 | weak_stress_near_miss | 1.0 | 1.0 | post_harvest |
| psd_ending_stocks_anomaly_pct | revision_shock | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 8.0 | 1.918219879173854 | post_harvest |
| psd_ending_stocks_anomaly_pct | revision_streak | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 4.0 | 2.0 | late_season |
| psd_ending_stocks_anomaly_pct | stage_level_z | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 3.4093983764847846 | 1.5 | late_season |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 1.0 | 0.95 | late_season |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | united_states | 2009 | 0.6848459314811522 | weak_stress_near_miss | 0.7847061582861082 | 0.52 | post_harvest |
| psd_ending_stocks_anomaly_pct | stage_level_z | ukraine | 2012 | 0.5805960278173036 | weak_stress_near_miss | 8.0 | 1.5 | preseason |
| psd_ending_stocks_anomaly_pct | stage_level_percentile | ukraine | 2012 | 0.5805960278173036 | weak_stress_near_miss | 1.0 | 0.95 | preseason |
| psd_ending_stocks_anomaly_pct | composite_balance_sheet_stress | ukraine | 2012 | 0.5805960278173036 | weak_stress_near_miss | 0.5717625527964528 | 0.52 | early_season |
| psd_stock_to_use_anomaly_pct | revision_shock | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 8.0 | 2.1034439089942096 | late_season |
| psd_stock_to_use_anomaly_pct | revision_streak | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 5.0 | 2.0 | midseason |
| psd_stock_to_use_anomaly_pct | stage_level_z | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 3.4862226045094316 | 1.5 | preseason |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 1.0 | 1.0 | preseason |
| psd_stock_to_use_anomaly_pct | composite_balance_sheet_stress | united_states | 2005 | 0.5362978623724851 | weak_stress_near_miss | 0.7549019143174217 | 0.5368328058253912 | early_season |
| psd_stock_to_use_anomaly_pct | stage_level_z | argentina | 2013 | 0.5294091401684957 | weak_stress_near_miss | 3.28563772537313 | 1.5 | preseason |
| psd_stock_to_use_anomaly_pct | stage_level_percentile | argentina | 2013 | 0.5294091401684957 | weak_stress_near_miss | 1.0 | 0.95 | preseason |
| psd_ending_stocks_anomaly_pct | revision_shock | united_states | 2008 | 0.8857469367519112 | soft_stress_near_miss | 6.92204381049914 | 1.926827458419216 | preseason |

## Phase 6 Implication

Do not run broader model sweeps until the listed blockers are addressed. If event-definition pressure is high, add a watchlist/soft-stress label. If z-score scale is unstable, repair normalization with robust prior-only scaling or caps. If revision streak still overfires, require directional magnitude and cumulative revision confirmation.
