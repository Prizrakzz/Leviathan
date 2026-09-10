# BOARD CENSUS -- as-of 2026-09-07

started 2026-09-10T13:32:07+00:00  wall 191.9 s  boards 36  runs 144  ATHENA_CALLS=0  estate=pg-mirror
physical mirror reads 3484 (p50 2.55 ms, max 192.55 ms); declines {}
distinct series keys estate-wide: 286   board rows: 1270
REGISTER TRIPS: 0 (must be 0 -- PASS)
OPEN RECTANGLES: 0 []

## per mode (D2 pass, all boards)
mode      boards  reads min/med/max  cap  lines min/med/max  tokens med  trips
quick         36    3/ 14.5/ 23       25   35/ 53.0/ 69      3412.5     0
deep          36   15/ 24.0/ 35       45   43/ 84.5/ 95      5201.5     0
max           36   19/ 30.5/ 39       57   61/107.0/128      6706.0     0

## probes
P0 measured: per-read p50 w1=1.84 ms, w2=2.11 ms, w4=9.32 ms
P1 d2
P2 no window is clean on every board; leg B stays dark and the row says so
P3 all declarations parse to a band
P4 16 calendared cards over 12 sources; 11 name a release inside the next 60 days; 11 carry verified_against (owner curation, sec 10.1); 0 rule-kind finding(s)
P5 measured against a banked prior vintage -- silver_noaa_iod: 0 period(s) revised, max 0.0 over 918 overlapping period(s); silver_noaa_oni: 883 period(s) revised, max 0.44 over 917 overlapping period(s)
destinations 8 series read at the 5,000-row cap and would truncate silently: corn_cbot, grain_sorghum, hard_red_spring_wheat_mgex, hard_red_winter_wheat_kcbt, soft_red_winter_wheat_cbot, soybean_meal_cbot, soybean_oil_cbot, soybeans_cbot
oni_crossings ONI crossed 36 time(s) over 131 months from 2015-09 (a desk band is declared)
tape the front expiry is named on 23 of 26 tape boards; reasons {'served': 23, 'cash_reference': 2, 'roll_inputs_absent': 1}; 1 read(s) hit the cap
     P1 detail: d2 passes on ['deep', 'max', 'quick'], alternative on ['deep', 'max', 'quick']; branch: none -- the shipped tuple stands
CASCADE CENSUS measured {'legs': 792, 'fires': 544, 'declines': 248, 'dark': 0, 'probe_errors': 0} vs prediction {'legs': 792, 'fires': 544, 'declines': 248, 'dark': 0, 'probe_errors': 0} -> MATCH
ALTERNATIVE PASS: the alternative tuple selects a different top row on 3 of 36 board/mode pair(s); net reads differ by +0 across the pass

## the design's UNVERIFIED figures this artifact settles
- distinct_series_keys_estate [measured]: 286
    quoted: Draft A's median 17 per contract / ~444 estate estimate; the 390-key figure is config-derived and never replayed (Appendix B)
- distinct_series_keys_per_board [measured]: {"min": 3, "median": 13.5, "max": 22}
    quoted: Draft A's median 17 per contract (Appendix B)
- board_rows_total [measured]: 1270
    quoted: the design's 1,266 rows (sec 10.1(b), bar B14)
- wave1_cap_binds [measured]: {"quick": {"cap": 24, "binds_on": [], "max_board_keys": 22}, "deep": {"cap": 32, "binds_on": [], "max_board_keys": 22}, "max": {"cap": 40, "binds_on": [], "max_board_keys": 22}}
    quoted: sec 7's 'supply, not caps' (desk_cost F16): the caps are UPPER bounds and the soybeans board carries 12-13 keys, not 24
- pg_read_latency_ms [measured]: {"1": {"n": 24, "p50": 1.84, "p90": 10.12, "max": 11.47, "mean": 3.37, "total": 80.79}, "2": {"n": 24, "p50": 2.11, "p90": 11.18, "max": 16.18, "mean": 4.81, "total": 115.55}, "4": {"n": 24, "p50": 9.32, "p90": 20.73, "max": 24.83, "mean": 9.97, "total": 239.2}}
    quoted: every latency delta in secs 3.8 and 7 is a projection until P0 (Appendix B)
- pool_contention [measured]: {"state_cache": "off", "state_cache_note": "the memo is OFF: every agent-thread read is a physical read and the load is real", "board_wall_ms": 153.7, "board_per_read": {"n": 24, "p50": 6.19, "p90": 18.46, "max": 32.67, "mean": 10.18, "total": 244.37}, "board_reads": 24, "board_declines": {}, "board_pool_declined_rate": 0.0, "board_statuses": {"ok": 23, "read_empty:all_blank": 1}, "agent_reads": 1
    quoted: the BoardPoolDeclined rate with a 4-wide agent round beside the wave (sec 10.1)
- span_fence_365 [measured]: {"tally": {"180": {"clean": 21, "of": 26, "clean_slugs": ["arabica_coffee", "brazilian_arabica_coffee", "campinas_corn_reference_bmf", "canola_ice", "cocoa", "corn_cbot", "cotton", "frozen_orange_juice", "hard_red_spring_wheat_mgex", "hard_red_winter_wheat_kcbt", "malaysian_crude_palm_oil_cme", "rapeseed_meal_zce", "rapeseed_oil_zce", "raw_sugar", "robusta_coffee", "rough_rice_cbot", "soft_red_win
    quoted: CW_SPAN_MAX_DAYS 270 is r2-certified to ~267 d and failures start ~563 d; the gap is unmeasured while a 2-4q band is ~365 d (analogs.leg_b_rows)
- oni_iod_revision_magnitude [measured]: "measured against a banked prior vintage -- silver_noaa_iod: 0 period(s) revised, max 0.0 over 918 overlapping period(s); silver_noaa_oni: 883 period(s) revised, max 0.44 over 917 overlapping period(s)"
    quoted: the magnitude of any in-place ONI / IOD revision on the mirror -- no prior vintage exists (Appendix B)
- esr_fgis_destination_counts [measured]: {"series": 11, "read": 11, "min_headroom": -25837, "at_cap": ["corn_cbot", "grain_sorghum", "hard_red_spring_wheat_mgex", "hard_red_winter_wheat_kcbt", "soft_red_winter_wheat_cbot", "soybean_meal_cbot", "soybean_oil_cbot", "soybeans_cbot"], "unread": 0, "verdict": "8 series read at the 5,000-row cap and would truncate silently: corn_cbot, grain_sorghum, hard_red_spring_wheat_mgex, hard_red_winter_
    quoted: the per-slug ESR / FGIS destination counts and the 52-week window's headroom under the 5,000-row cap (Appendix B)
- per_anchor_line_counts [measured]: {"quick": {"lines": {"min": 35, "median": 53.0, "max": 69}, "est_tokens": {"min": 2081, "median": 3412.5, "max": 4527}, "planned_lines": "17-20", "planned_tokens": 1100}, "deep": {"lines": {"min": 43, "median": 84.5, "max": 95}, "est_tokens": {"min": 2737, "median": 5201.5, "max": 5800}, "planned_lines": "~40", "planned_tokens": 2400}, "max": {"lines": {"min": 61, "median": 107.0, "max": 128}, "es
    quoted: sec 7's per-anchor line and token counts are [A]; the S4 artifact adds the measured ones and sec 7 is re-derived from the MEDIAN board
- cascade_census_split [measured]: {"legs": 792, "fires": 544, "declines": 248, "dark": 0, "probe_errors": 0}
    quoted: 790 = 541 FIRES / 249 DECLINES (commit 9b2cfb56) superseded by prediction #14 = 792 = 544 / 248 / 0 / 0 after D-10 sitting 9
- p1_falsifier [measured]: {"verdict": "d2", "d2_passes_on": ["deep", "max", "quick"], "alternative_passes_on": ["deep", "max", "quick"]}
    quoted: ONI's +0.98 degC against its own 120-month history is a modest sigma [A] and a same-month weather z can out-rank it (sec 3.2)
- lag_declarations_parse [measured]: {"declarations": 1270, "distinct_lag_strings": 18, "table_key_count": 19, "unparsed": 0}
    quoted: S0's exit reads '1,412 declarations parse (18 + 8 strings, zero unparsed)' (sec 11 row S0, P3)
- release_calendar_verified [measured]: {"rules": 16, "sources": 12, "verified_against_set": 11, "releases_in_horizon": 11, "uncalendared": ["gold_weather_z", "silver_noaa_iod", "silver_production_livestock"]}
    quoted: every publisher print time and window is owner curation, verified_against: null until confirmed (Appendix B, P4)
- tape_roster [measured]: {"boards_with_tape": 26, "with_tape": ["arabica_coffee", "brazilian_arabica_coffee", "campinas_corn_reference_bmf", "canola_ice", "cocoa", "corn_cbot", "cotton", "french_maize_matif", "french_rapeseed_matif", "french_wheat_matif", "frozen_orange_juice", "hard_red_spring_wheat_mgex", "hard_red_winter_wheat_kcbt", "malaysian_crude_palm_oil_cme", "rapeseed_meal_zce", "rapeseed_oil_zce", "raw_sugar", 
    quoted: the then/now design's roster measurement (20 boards) is QUOTED, not re-measured (Appendix B); bar B19 names 'each of the ten tape-less boards'
- oni_crossing_count [measured]: {"crossings": 36, "history_start": "2015-09", "n_periods": 131, "windows": {"1_2q": {"opens": "2026-10-31", "closes": "2027-01-31", "open_ended": false, "declined": null}, "2_4q": {"opens": "2027-01-31", "closes": "2027-07-31", "open_ended": false, "declined": null}}}
    quoted: the ONI crossing count since 1950 with closed 1-2q and 2-4q windows -- the words scenario 2 narrates (sec 10.1)