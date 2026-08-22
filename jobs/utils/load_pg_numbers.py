"""Mirror the numbers-registry serving tables into RDS Postgres (GRAPHRAG_NUMBERS_BACKEND=pg).

Reads each table's SILVER PARQUET straight from S3 (the source of truth — no Athena paging), using the Glue
catalog only for schema + location, and rebuilds the pg mirror atomically (DROP + CREATE + COPY inside one
transaction — pg DDL is transactional; readers keep the old rows until commit). The pg schema is named like the Athena database
(`leviathan_dev`) so `build_sql()` output runs unchanged on either backend.

TYPE DOCTRINE (parity-first): every column is TEXT except the ones SQL does math on — wide metric columns /
`value_col` (avg/sum/min/max run in-database), `year_col`/`month_col` (`year*100+month` guard), and int-typed
period columns. Dates stay ISO TEXT: build_sql compares them as text (`_dcol` casts), ISO sorts
lexically==chronologically, and Athena returns strings anyway — the executor stringifies, so a pg row is
indistinguishable from an Athena row.

Tall tables load ONLY the registry-declared metrics (silver_wasde declares 5 of ~300 attributes — ~98% of
rows are never servable). P1 tables below are all small-to-modest; silver_nasa_power is EXCLUDED until a
size check (tens of millions of rows) decides pruning vs an RDS bump. silver_futures_eod is EXCLUDED on
exactly the same ground (PRICE_AND_PLAYBOOKS W1.0 / D7, probe P8) -- see the comment at its place in the
P1_TABLES list below.

    python jobs/utils/load_pg_numbers.py --dry-run
    python jobs/utils/load_pg_numbers.py --tables silver_fred_fx,silver_noaa_oni
    python jobs/utils/load_pg_numbers.py            # the P1 set

Runs IN-VPC (the RDS SG admits the Batch/serving SGs) — submit via jobs/submit/submit_batch_load_numbers_pg.py.
"""
from __future__ import annotations

import argparse
import logging
import os
import time

from leviathan.common.config import load_env
from leviathan.common.logging import get_logger

logger = get_logger("load_pg_numbers")

# W7 -- THE 2x MISCOUNT FENCE. The F015 publisher stages every object under `<root>/_shadow/` before
# promoting it and persists run manifests under `<root>/_manifests/`, so a table root can hold a
# BYTE-IDENTICAL twin of every canonical object (same size, same run_id, same written_at) under the same
# prefix. `gold/pattern_records/` is the live example: 156 canonical `as_of_date=` objects + 156 shadow
# copies + 3 manifests = 315 objects. A prefix scan that does not exclude these reads 312 parquet files /
# 78,312 rows instead of 156 / 39,156 -- exactly 2x, with no error and no warning. That is not a storage
# nuisance: this loader builds the pg mirror the serving numbers lane reads, and a DOUBLED DENOMINATOR in
# a "fired on N of M sweeps" base rate is a wrong number delivered confidently. (Athena/Hive is safe by
# accident -- `_shadow` does not match `as_of_date=`.)
#
# pyarrow's dataset discovery defaults to exactly this exclusion, so passing it EXPLICITLY is a no-op
# today (verified 2026-07-28 on pyarrow 24.0.0 against a replica of the pattern_records layout: default
# and explicit both discover 2 of 4 files; `ignore_prefixes=[]` discovers 4 AND dies on the manifest
# JSON). It is passed anyway because "correct by an unstated library default" is how the miscount gets
# re-earned -- by a future reader that lists with boto3, or by anyone who overrides this kwarg to pick up
# some other hidden path and silently takes the shadow copies with it.
_HIDDEN_PREFIXES = ["_", "."]

P1_TABLES = ["silver_psd", "silver_wasde", "silver_production", "silver_esr", "silver_fred_fx",
             "silver_noaa_oni", "gold_weather_z",         # gold_weather_z: small tall z-table (D-W4);
             #                                              silver_nasa_power stays EXCLUDED (size, above)
             # D-EC DK-13: gold_board_crush is a FLAT WIDE table of ~4,000 rows (one per session since
             # the 2010-06-06 GLBX floor) with four double metrics -- comfortably the smallest table on
             # this list. trade_date and the three contract_month columns stay ISO TEXT under the type
             # doctrine; the four *_usd_bu metrics plus the three raw leg settles mirror numeric.
             "gold_board_crush",
             # GN-2 W2.3: gold_futures_spreads -- flat WIDE table, ~2,700 rows (kc_chi's decade +
             # white_yellow's young JSE feed). spread_value mirrors numeric (the declared metric);
             # trade_date/spread_id/unit/slugs/contract months/is_roll_boundary ('0'/'1' STRING --
             # the crush's three-backend identity) stay ISO TEXT under the type doctrine; the two
             # raw leg settles mirror numeric as declared value columns' siblings do on the crush.
             "gold_futures_spreads",
             # numbers-depth wave (W0-4 / D3): three freshly wired WIDE tables. All small-to-modest and
             # numeric-column-safe under the type doctrine: ICCO metrics production_kt/grindings_kt/
             # end_stocks_kt/su_ratio, MPOB *_mt + su_ratio, SAGIS current_estimate_t/area_planted_ha
             # mirror as numeric; every date/slug/scope/period-string column stays ISO TEXT. SAGIS's
             # production_year (period_sql_type=int) also mirrors numeric. Justified by the serving
             # fast-path + the per-lane golden-vocabulary fixtures (NOT a C002 requirement; C002's
             # wide-metric check is AWS-free -- CORRECTION V2).
             "silver_icco_cocoa", "silver_mpob", "silver_sagis_cec",
             # PRICE_OBSERVABILITY W3.3: pink_sheet is a small flat wide table (798 rows); metric columns
             # mirror numeric, `date` (physical timestamp) stringifies to the Athena render and stays
             # TEXT COLLATE "C" -- the DP-5 substr normalization makes both backends compare identically.
             "silver_pink_sheet",
             # PRICE_OBSERVABILITY W4.2 (v2): silver_cot is a small flat wide table; the managed-money
             # metric columns (open_interest / mm_* levels + net + signed pct_oi + 3-yr z-scores) mirror
             # numeric under the type doctrine, and report_date / leviathan_slug / source stay ISO TEXT.
             "silver_cot",
             # SEAM C (futures v1.5-lite, whitelisted 2026-07-23): a small flat wide table (12 continuous
             # front-month slugs x daily `close`); the single `close` metric column mirrors numeric under the
             # type doctrine, and `date` (physical timestamp) / leviathan_slug / source stay ISO TEXT. The
             # DP-5 substr normalization makes both backends compare identically. FUTURES v1.5 W1.3
             # (2026-07-23): the additive `unit` column is TEXT, never numeric -- not a metric/value_col,
             # so _numeric_cols routes it to TEXT COLLATE "C" automatically; NO loader change, just a
             # re-run after the canonical schema widen.
             "silver_futures_prices",
             # PRICE_AND_PLAYBOOKS W1.0 / D7 (probe P8) -- silver_futures_eod, ADDED 2026-07-31.
             # It was deliberately absent and the deferral named THREE conditions. All three are now
             # discharged, each by measurement rather than assertion:
             #   (1) SIZE. The old rationale was that this table "can plausibly exceed the t4g.micro
             #       envelope" -- ~29 contracts x every delivery month x daily back to 2010-06, two to
             #       three orders of magnitude more rows than silver_futures_prices. MEASURED after the
             #       W2 backfill: 269 canonical parquet objects, 12.5 MB total. Not a capacity question.
             #   (2) THAT ENVELOPE NO LONGER EXISTS. The sentence reasoned about a db.t4g.micro; the
             #       instance is db.m7g.large (2 vCPU / 8 GB, 20 GB storage), upgraded during the latency
             #       RCA that also found the starved DB and set the 300 s statement timeout. The
             #       "pruning versus an RDS bump" choice this comment asked for was settled independently
             #       -- the bump already happened, so the question it poses is stale, not open.
             #   (3) WHITELIST. Adding it early used to be inert-to-harmful: the table was whitelist-absent
             #       from the numbers registry, so reg.get(tid) raised KeyError, load_table recorded a
             #       per-table failure and the run ended SystemExit(1) -- a red nightly loader for a table
             #       with zero rows. The W3 flip (2026-07-30) emptied WHITELIST_ABSENT_DEFAULT.
             # WHAT FORCED THE ISSUE: served but unmirrored, GRAPHRAG_NUMBERS_BACKEND=pg raises
             # UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA -- the partition-projection path
             # behind the 26.8M-request LIST storm. A served numbers table must be mirrored.
             # TYPE DOCTRINE (unchanged): settle/open/high/low/close/volume/open_interest mirror numeric;
             # trade_date (physical TIMESTAMP), contract_month, raw_symbol, instrument_kind, settle_kind,
             # unit, currency, source, dataset stay TEXT COLLATE "C"; trade_year (an int partition key)
             # mirrors numeric via meta["partitions"].
             # SEQUENCING, enforced rather than documented: numbers_parity carries the D8 SAMPLE_COMMODITY
             # entry for this table and SKIPs (loudly, SKIP-UNMIRRORED) any sampled table absent from THIS
             # list -- it imports P1_TABLES, so the two cannot drift. That skip now deactivates and the
             # parity entry goes live with the mirror.
             "silver_futures_eod",
             # WIRING WAVE-1 (2026-07-23): two freshly wired WIDE tables. silver_noaa_iod (year_month, 2
             # served metrics dmi_value/iod_dmi_3month_avg mirror numeric; year/month mirror numeric; the
             # producer trims the trailing NaN tail so latest is a real reading). silver_conab_coffee
             # (survey-vintage; production_thousand_bags/area_in_production_ha/yield_bags_per_ha mirror
             # numeric; safra_year period_sql_type=int mirrors numeric; commodity/region/survey_release_date
             # stay ISO/TEXT).
             # WIRING WAVE-1 Card C (2026-07-24): silver_sagis_weekly_exports is now wired -- the catalog ALTER
             # landed week_ending_date DATE. WIDE data_date table: the three served metrics prog_exports_mt/
             # pct_of_prior_yr/z_vs_3yr_avg mirror numeric; crop/season/week_ending/source stay ISO/TEXT and the
             # derived week_ending_date (DATE) stringifies to ISO TEXT COLLATE "C" (DP-5 substr-normalized, so
             # both backends compare identically). Small (1204 rows).
             "silver_noaa_iod", "silver_conab_coffee", "silver_sagis_weekly_exports",
             # T2B PATTERN RECORDS (2026-07-24): gold_pattern_records is the engine's recorded verdict ledger
             # (one row per record_kind x contract x driver x as_of_date). Its numeric metric columns
             # (streak_len/window_change/n_points/n_rows/n_hops) mirror numeric under the type doctrine; every
             # id/verdict/reason/provenance/run_id column stays ISO/TEXT COLLATE "C", and `written_at` (physical
             # TIMESTAMP) / as_of_date stringify to the Athena render (DP-5 substr-normalized in the presence
             # SQL, so both backends compare identically). Mirrored so the SQL-lane presence/base-rate
             # aggregations serve warm from pg; the serving CARD is independently gated by GRAPHRAG_PATTERN_RECORDS.
             "gold_pattern_records",
             # D-CW-2a (2026-08-07): silver_nass_crop_progress joins the mirror in the SAME change that
             # gives it a numbers card, for the reason stated three entries up and MEASURED there --
             # served but unmirrored means GRAPHRAG_NUMBERS_BACKEND=pg raises UndefinedTable per query and
             # SILENTLY FALLS BACK TO ATHENA. Here that fallback lands on a PARTITION-PROJECTED table
             # (commodity enum x year 1979-2035), i.e. the LIST-storm class -- small (~342 candidates,
             # and build_sql pins the commodity equality plus sargable year bounds), but the doctrine is
             # not about the size: a served numbers table must be mirrored.
             # TYPE DOCTRINE: the five pct_* metric columns mirror numeric (wide metrics); `year` (an int
             # partition key) mirrors numeric via meta["partitions"]; leviathan_slug / state / commodity /
             # source stay TEXT COLLATE "C", and `date` (a physical DATE) stringifies to the Athena ISO
             # render, which is what build_sql's CAST-as-varchar compare expects on both backends.
             # SEQUENCING: this entry defines the mirror; the LOAD still has to run in-VPC before the
             # serving flip. numbers_parity deliberately carries NO SAMPLE_COMMODITY row for it yet -- a
             # sample entry is what makes a panel non-vacuous, and choosing that commodity/as-of pair is
             # worth doing against the first real mirror rather than guessing here (the reverse drift,
             # a sampled-but-unmirrored table, is the one the futures_eod pin forbids).
             "silver_nass_crop_progress",
             # D-PQ tranche 1a (2026-08-07): silver_mpoc_stock_comparison joins the mirror in the SAME
             # change that gives it a numbers card -- served but unmirrored means
             # GRAPHRAG_NUMBERS_BACKEND=pg raises UndefinedTable per query and SILENTLY FALLS BACK TO
             # ATHENA. Here the fallback would land on a flat, projection-forbidden table (272 rows, one
             # object), so the cost of the fallback is trivial and the doctrine is the whole reason:
             # a served numbers table must be mirrored, and "small enough not to matter" is how a
             # silent-fallback path gets normalized.
             # TYPE DOCTRINE: ending_stocks_mt mirrors numeric (the single wide metric); `year` and
             # `month` mirror numeric because they are the declared year_col/month_col the
             # (year*100+month) guard does arithmetic on; country / oil_type / source stay TEXT
             # COLLATE "C". No date column exists, so nothing stringifies.
             # SEQUENCING: this entry DEFINES the mirror; the LOAD still has to run in-VPC before any
             # serving flip (see the orchestrator note in the D-PQ record). numbers_parity deliberately
             # carries NO SAMPLE_COMMODITY row for it yet, for the reason the NASS entry gives.
             "silver_mpoc_stock_comparison",
             # D-LD (2026-08-18): silver_fgis joins the mirror in the SAME change that gives it a numbers
             # card -- served but unmirrored means GRAPHRAG_NUMBERS_BACKEND=pg raises UndefinedTable per
             # query and SILENTLY FALLS BACK TO ATHENA, and here the fallback lands on a partition-PROJECTED
             # table (leviathan_slug enum x marketing_year 1982-2035). Small: 113,072 rows, 223 canonical
             # objects, 6.5 MB total -- not a capacity question, and the doctrine is the point.
             # TYPE DOCTRINE: exports_mt_weekly / exports_mt_ctd mirror NUMERIC (wide metrics);
             # marketing_year mirrors NUMERIC because it is the declared period_col with
             # period_sql_type=int, which is exactly what makes the compiled `marketing_year = 2025`
             # equality (a bare int literal, query.py:390-391) work on pg as it does on Athena;
             # week_of_marketing_year is NOT referenced by the card and stays TEXT COLLATE "C" (nothing
             # does arithmetic on it); leviathan_slug / destination_country / source stay TEXT COLLATE "C";
             # and week_ending_date (a physical DATE) stringifies to the Athena ISO render, which is what
             # build_sql's CAST-as-varchar compare expects on both backends -- the nass_crop_progress shape
             # exactly. NOTE the loader already handles this table's one quirk without any change:
             # leviathan_slug AND marketing_year are BOTH Glue partition keys AND in-file body columns
             # (physical_parquet_cols 8 vs glue_nonpartition_cols 6), which makes pyarrow's dataset-schema
             # unification fail -- _probe_body_columns drops such keys from the partitioning schema and
             # takes the authoritative body value (load_pg_numbers.py:180-188). Confirmed by reproducing
             # the exact ArrowTypeError ("Field leviathan_slug has incompatible types: large_string vs
             # string") on a naive hive read of the canonical prefix.
             # SEQUENCING: this entry DEFINES the mirror; the LOAD still has to run in-VPC before any
             # serving flip. numbers_parity deliberately carries NO SAMPLE_COMMODITY row for it yet, for
             # the reason the NASS entry gives -- a sampled-but-unmirrored table turns the whole parity
             # gate red, and choosing the commodity/as-of pair is worth doing against the first real mirror.
             "silver_fgis",
             # D-LD (2026-08-18): silver_wap_table01_revisions joins the mirror in the SAME change that
             # gives it a numbers card -- served but unmirrored means GRAPHRAG_NUMBERS_BACKEND=pg raises
             # UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA. Trivially small (one flat
             # object, 346 KB / 96,410 rows, projection forbidden), so the fallback would be cheap and
             # that is precisely how a silent-fallback path gets normalised.
             # TYPE DOCTRINE: the three wide metric columns value_mmt / prior_value_mmt / revision_mmt
             # mirror NUMERIC (SQL runs avg/sum/min/max on them). Everything else stays TEXT COLLATE "C":
             # release_month and prior_release_month are 'YYYY-MM' LABELS, not dates -- the as-of guard is
             # a byte compare of that label against the lag-shifted ISO cutoff, and TEXT COLLATE "C" is
             # byte-for-byte Presto's varchar order, so the prefix semantics ('2026-07' <= '2026-08-06')
             # are identical on both backends. commodity / country / marketing_year / row_label /
             # vintage_type / vintage_status / month_abbr are all TEXT; marketing_year is
             # period_sql_type=string, so it must NOT be coerced numeric. There is no partition key
             # (partition_keys []), so meta["partitions"] contributes nothing.
             # SEQUENCING: this entry DEFINES the mirror; the LOAD still has to run IN-VPC before any
             # serving flip. numbers_parity deliberately carries NO SAMPLE_COMMODITY row for it yet -- a
             # sampled-but-unmirrored table turns the WHOLE parity gate red (the futures_eod pin), and
             # choosing the commodity/as-of pair is worth doing against the first real mirror.
             "silver_wap_table01_revisions",
             # D-LD Track 1 (2026-08-18): silver_fnc_colombia_monthly joins the mirror in the SAME change
             # that gives it a numbers card -- served but unmirrored means GRAPHRAG_NUMBERS_BACKEND=pg
             # raises UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA. Here that fallback lands
             # on a partition-PROJECTED table (commodity enum x year 1913-2035), i.e. the LIST-storm class
             # -- tiny in practice (<=114 live candidates, and build_sql pins the commodity equality plus
             # sargable year bounds), but the doctrine is not about the size: a served numbers table must
             # be mirrored. It is 1,360 rows in 114 objects, ~800 KB total.
             # TYPE DOCTRINE: the five metric columns (production_bags_60kg, exports_bags_60kg,
             # exports_value_usd_m, ex_dock_price_usd_cents_per_lb, internal_price_cop_per_125kg) mirror
             # NUMERIC as wide metrics; `year` (an int PARTITION key) mirrors numeric via meta["partitions"]
             # because it is the declared year_col the sargable bounds do arithmetic on; `month` (bigint,
             # an in-file column) is NOT declared as month_col and is not a metric, so it routes to TEXT
             # COLLATE "C" under _numeric_cols -- harmless, nothing compares it; leviathan_slug / country /
             # commodity / source stay TEXT COLLATE "C", and `date` (a physical DATE) stringifies to the
             # Athena ISO render, which is exactly what build_sql's CAST-as-varchar compare expects on both
             # backends.
             # SEQUENCING: this entry DEFINES the mirror; the LOAD still has to run IN-VPC before any
             # serving flip. numbers_parity deliberately carries NO SAMPLE_COMMODITY row for it yet -- a
             # sampled-but-unmirrored table turns the WHOLE parity gate red (numbers_parity.py:30-36), so
             # the sample entry is chosen against the first real mirror, not guessed here.
             "silver_fnc_colombia_monthly",
             # D-LD (2026-08-18): silver_fnc_colombia_exports_port_type joins the mirror in the SAME
             # change that gives it a numbers card -- served but unmirrored means
             # GRAPHRAG_NUMBERS_BACKEND=pg raises UndefinedTable per query and SILENTLY FALLS BACK TO
             # ATHENA, and here that fallback lands on a partition-PROJECTED table. Tiny (2,147 rows,
             # 10 objects, 108 KB).
             # TYPE DOCTRINE: exports_bags_60kg / exports_value_usd mirror numeric (the two wide
             # metrics); `year` mirrors numeric because it is the declared year_col (Glue type int,
             # arriving via meta["partitions"]). Everything else stays TEXT COLLATE "C": leviathan_slug,
             # country, port, port_raw, coffee_type, coffee_type_raw, source, commodity -- and `month`
             # too, which is a physical bigint but is NOT the declared month_col (no year_month
             # arithmetic runs on it), so the doctrine routes it to TEXT and nothing filters on it.
             # `date` is a physical DATE and stringifies to the Athena ISO render, which is what
             # build_sql's CAST-as-varchar compare expects on both backends (the NASS precedent; NO
             # date_col_type is needed -- that knob is for physical TIMESTAMPs only).
             # NOTE the shadowed key: `year` is BOTH a projected partition key and an in-file int64
             # column. _probe_body_columns already handles exactly this (it drops such keys from the
             # partitioning schema and loads them from the body); the two values are byte-equal on all
             # 2,147 rows (verified 2026-08-18). Glue Columns carries 11 names and PartitionKeys 2, so
             # `all_cols` has no duplicate.
             # SEQUENCING: this entry DEFINES the mirror; the LOAD still has to run in-VPC before the
             # serving flip. numbers_parity deliberately carries NO SAMPLE_COMMODITY row for it yet
             # (the NASS reason -- choose the pair against the first real mirror, and never sample an
             # unmirrored table).
             "silver_fnc_colombia_exports_port_type",
             # D-LD (2026-08-18): silver_nass_citrus joins the mirror in the SAME change that gives it a
             # numbers card -- served but unmirrored means GRAPHRAG_NUMBERS_BACKEND=pg raises
             # UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA. The fallback here lands on a
             # FLAT, projection-forbidden table (2,450 rows, ONE 17.7 KiB object), so its cost is
             # trivial and the doctrine is the entire reason: a served numbers table must be mirrored,
             # and "small enough not to matter" is how a silent-fallback path gets normalized.
             # TYPE DOCTRINE: forecast_1000_boxes and revision_1000_boxes mirror NUMERIC (the two wide
             # metrics -- _numeric_cols takes them straight off ts.metrics). Everything else stays TEXT
             # COLLATE "C": season / release_date / crop / state / source are already strings, and --
             # note, because it is the one that looks wrong -- `report_month` (bigint) and
             # `hlb_trend_factor` (double) mirror as TEXT too, because neither is a declared metric,
             # value_col, year_col, month_col or int-typed period col. That is correct and intended: no
             # SQL this card compiles does arithmetic on either, and hlb_trend_factor is deliberately
             # unserved. There is no year_col/month_col and no int period col here, so nothing else
             # goes numeric; `season` is period_sql_type=string and stays TEXT.
             # SEQUENCING: this entry DEFINES the mirror; the LOAD still has to run in-VPC before any
             # serving flip. numbers_parity deliberately carries NO SAMPLE_COMMODITY row for it yet --
             # a sampled-but-unmirrored table turns the WHOLE parity gate red (numbers_parity.py:30-36
             # imports P1_TABLES and SKIPs loudly), and choosing the (commodity, as-of) pair is worth
             # doing against the first real mirror. When it is added it must be a CROP LABEL from the
             # silver data (e.g. all_orange), never a contract slug.
             "silver_nass_citrus",
             # D-LD (2026-08-18): silver_mpoc_trade_stats_monthly joins the mirror in the SAME change
             # that gives it a numbers card -- served but unmirrored means GRAPHRAG_NUMBERS_BACKEND=pg
             # raises UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA. The fallback here is
             # trivially cheap (180 rows, ONE 5.8 KB object, flat / projection-forbidden), and it is
             # mirrored anyway for the reason the entry above states: "small enough not to matter" is
             # exactly how a silent-fallback path gets normalized.
             # TYPE DOCTRINE: `exports_mt` mirrors NUMERIC (the single wide metric the card declares);
             # `year` and `month` mirror NUMERIC because they are the declared year_col/month_col the
             # (year*100 + month) guard does arithmetic on; `source` stays TEXT COLLATE "C". The
             # physical `imports_mt` is a double and will mirror numeric under _numeric_cols like any
             # other double -- that is correct and harmless: it is loaded but NEVER SERVED, because the
             # card declares no metric for it (see the card comment: prior-year exports on 2020/21/22).
             # There is no date column of any kind, so nothing stringifies and no DP-5 substr
             # normalization applies.
             # SEQUENCING: this entry DEFINES the mirror; the LOAD still has to run IN-VPC
             # (jobs/submit/submit_batch_load_numbers_pg.py) before any serving flip. numbers_parity
             # deliberately carries NO SAMPLE_COMMODITY row for it -- and here that is not a deferral
             # but a STRUCTURAL fact: SAMPLE_COMMODITY panels are keyed by commodity and this table has
             # no commodity column, so a sampled entry would be vacuous.
             "silver_mpoc_trade_stats_monthly",
             # ── D-LD TRANCHE 2 (2026-08-18): six more cards, six more mirrors, all in the SAME change
             # that lands the cards. The doctrine is one sentence and it does not bend for size: a
             # SERVED numbers table must be MIRRORED, because served-but-unmirrored means
             # GRAPHRAG_NUMBERS_BACKEND=pg raises UndefinedTable per query and SILENTLY FALLS BACK TO
             # ATHENA (pgnumbers.py:66-77, warning-log only -- never an error, never a wrong number,
             # just a quietly different backend). "Small enough not to matter" is precisely how that
             # silent-fallback path gets normalized.
             # SEQUENCING, common to all six: these entries DEFINE the mirror; the LOAD still has to run
             # IN-VPC (jobs/submit/submit_batch_load_numbers_pg.py) before any serving flip, and
             # numbers_parity deliberately carries NO SAMPLE_COMMODITY row for any of them yet -- a
             # sampled-but-unmirrored table turns the WHOLE parity gate red (numbers_parity.py:30-36
             # imports P1_TABLES and SKIPs loudly), so the pair is chosen against the first real mirror.
             #
             # silver_sagis_weekly_deliveries -- 3,007 rows / one 110 KB object, flat + projection
             # forbidden. TYPE DOCTRINE: the four wide metrics prog_total_mt / prior_prog_total_mt /
             # pct_of_prior_yr / z_vs_3yr_avg mirror NUMERIC. week_number is a bigint that is NOT a
             # metric, NOT the value_col and NOT a year/month/int-period col, so _numeric_cols routes it
             # to TEXT COLLATE "C" -- correct, because nothing compares it arithmetically (it is a LABEL
             # on the season axis, and the card orders by week_ending_date). season / crop /
             # week_ending / source stay TEXT COLLATE "C", and the derived week_ending_date (Glue DATE)
             # stringifies to ISO TEXT COLLATE "C", which is what build_sql's CAST-as-varchar compare
             # expects on both backends -- byte-identical to the exports sibling.
             "silver_sagis_weekly_deliveries",
             # silver_ams_cotton_quality -- 27 rows / 9.6 KB, the smallest table in the mirror by two
             # orders of magnitude; size is not a question here. TYPE DOCTRINE: the three declared wide
             # metrics (percent_tenderable, samples_classed, avg_staple) mirror NUMERIC because metric
             # NAME == column name on a wide table, and `season` mirrors NUMERIC too because it is the
             # period_col with period_sql_type=int (_numeric_cols). EVERYTHING ELSE stays TEXT COLLATE
             # "C" -- commodity, geography, release_date (the ISO 'YYYY-MM-DD' vintage stamp: byte-order
             # collation is exactly how Athena compares the varchar the guard CASTs to, so the two
             # backends order it identically), source_pages, source_raw_key, source_file_etag, source.
             # The two UNDECLARED columns avg_micronaire / avg_strength are not metrics, so they route
             # to TEXT COLLATE "C" automatically and land as all-NULL text -- never served, never
             # numeric, no loader change needed.
             "silver_ams_cotton_quality",
             # silver_nass_annual -- 14,631 rows / 593 canonical objects, partition-PROJECTED (commodity
             # enum x year 1866-2035), so the fallback would land on the LIST-storm class. TYPE
             # DOCTRINE: the four wide metrics production_mt / yield_t_ha / area_harvested_ha /
             # area_planted_ha mirror NUMERIC; `year` mirrors NUMERIC because it is BOTH the declared
             # year_col and the int-typed period_col the sargable bounds do arithmetic on, arriving via
             # meta["partitions"]; marketing_year is a bigint that the card does NOT reference, so it
             # stays TEXT COLLATE "C" (nothing compares it); leviathan_slug / country / state /
             # commodity / source / release_date stay TEXT COLLATE "C". NOTE the shadowed keys, already
             # handled with no loader change: `year` is BOTH a Glue partition key and an in-file body
             # column (the silver_esr_compact / fnc class) -- _probe_body_columns drops such keys from
             # the pyarrow partitioning schema and takes the authoritative body value. The four all-NULL
             # *_cv_pct columns are not metrics and route to TEXT COLLATE "C" as all-NULL text.
             "silver_nass_annual",
             # silver_food_cpi -- 264 rows / one 10 KB object, flat. TYPE DOCTRINE: the four wide
             # metrics mirror numeric -- cpi_yoy_pct / cpi_yoy_z_5yr / cpi_yoy_z_10yr as DOUBLE
             # PRECISION and cpi_available as BIGINT -- and `year` mirrors bigint because
             # period_sql_type is int. Everything else is TEXT COLLATE "C": country_iso, country_name,
             # source, and BOTH derived ISO date strings (data_date, release_date), which the
             # CAST-as-varchar guard compares identically on both backends.
             # SEQUENCING NOTE SPECIFIC TO THIS TABLE: the loader reads the GLUE schema, so the catalog
             # type fix had to land BEFORE the load or the mirror would inherit `real`/`smallint` (the
             # pre-REPLACE declared widths) instead. The REPLACE COLUMNS is APPLIED (2026-08-18), so the
             # ordering constraint is discharged, not pending.
             "silver_food_cpi",
             # silver_fnc_colombia_area_department -- 464 rows / 24 objects, partition-PROJECTED
             # (commodity enum {arabica_coffee} x year 2002-2035 = 34 candidates, the smallest projected
             # grid in the registry). TYPE DOCTRINE: area_ha mirrors NUMERIC (the single wide metric);
             # `year` mirrors numeric because it is the declared year_col (an int partition key arriving
             # via meta["partitions"]); leviathan_slug / country / department / department_raw /
             # commodity / source stay TEXT COLLATE "C", and the carried-through `ingest_date` is an ISO
             # string that stays TEXT COLLATE "C" -- byte-order collation is exactly how Athena compares
             # the varchar the INGEST guard CASTs to.
             "silver_fnc_colombia_area_department",
             # silver_mpoc_exports_by_country -- 145 rows / one 3.9 KB object, flat + projection
             # forbidden; the smallest fallback surface in the tranche. TYPE DOCTRINE: exports_mt
             # mirrors NUMERIC (the single wide metric); `year` mirrors NUMERIC because it is the
             # period_col with period_sql_type=int; country / source stay TEXT COLLATE "C"; and the
             # derived year_ending_date (a physical date32) stringifies to the ISO render both backends
             # compare through CAST-as-varchar.
             # ONE ORDERING FACT, stated because it is the only one in this batch that is NOT yet
             # discharged: this table's anchor column is STAGED HIDDEN in the F010 contract and its Glue
             # ADD COLUMNS has NOT been applied, so a load run before that ALTER would mirror FOUR
             # columns and every as-of-guarded pg lookup would fail on the missing column. Run the ALTER
             # (and the producer re-fire) first; the entry is defined here so the two cannot drift.
             "silver_mpoc_exports_by_country",
             # ── D-LD TRANCHE 3 (2026-08-19): the three UNICA cards. Same doctrine, unbent: a SERVED
             # numbers table must be MIRRORED, because served-but-unmirrored means
             # GRAPHRAG_NUMBERS_BACKEND=pg raises UndefinedTable per query and SILENTLY FALLS BACK TO
             # ATHENA (pgnumbers.py:66-77, warning-log only). All three are tiny -- 305 / 86 / 58 rows,
             # one flat object each, projection forbidden, no partition grid -- so the fallback here is
             # a latency cost rather than a LIST-storm one; the entries exist so the mirror set and the
             # served set cannot drift, not because these three are expensive to miss.
             # SEQUENCING, common to all three and simpler than Tranche 2's: their PIT anchors are
             # columns that ALREADY EXIST in the live catalog (no staged-hidden column, no gated ADD
             # COLUMNS, no ordering constraint), so the in-VPC load
             # (jobs/submit/submit_batch_load_numbers_pg.py) can run the moment the cards land.
             # numbers_parity deliberately carries NO SAMPLE_COMMODITY row for any of them yet: a
             # sampled-but-unmirrored table turns the WHOLE parity gate red (numbers_parity.py:30-36
             # imports P1_TABLES and SKIPs loudly), so the pair is chosen against the first real mirror.
             #
             # silver_unica_biweekly_season_history -- 305 rows / one 20 KB object. TYPE DOCTRINE: the
             # five wide metrics (cane_crushed_t, sugar_produced_t, ethanol_total_m3,
             # ethanol_anhydrous_m3, ethanol_hydrous_m3) mirror NUMERIC. harvest_year is the period_col
             # but period_sql_type is STRING ('2025_2026'), so it stays TEXT COLLATE "C" -- correct,
             # because build_sql emits a string equality on it and nothing compares it arithmetically.
             # region (the country_col), fortnight_label, source_idm and source_position_date (the
             # provenance_col) stay TEXT COLLATE "C"; fortnight_seq is a bigint that is NOT a metric and
             # NOT an int period col, so it routes to TEXT COLLATE "C" as a label. The Glue DATE
             # fortnight_date stringifies to ISO TEXT COLLATE "C", which is exactly what the guard's
             # CAST-as-varchar compare expects on both backends.
             "silver_unica_biweekly_season_history",
             # silver_unica_corn_ethanol -- 86 rows / one 12 KB object. Same shape one axis narrower
             # (no region column). Six wide metrics mirror NUMERIC; harvest_year TEXT COLLATE "C" (string
             # period), fortnight_seq TEXT COLLATE "C" (a label, not a metric), fortnight_date the ISO
             # date render, fortnight_label / source_idm / source_position_date TEXT COLLATE "C".
             "silver_unica_corn_ethanol",
             # silver_unica_monthly_ethanol_sales -- 58 rows / one 10 KB object, the smallest of the
             # three. Six wide metrics mirror NUMERIC. TWO type facts worth stating because neither is
             # the obvious guess: month_date is a Glue STRING already in ISO 'YYYY-MM-01' form (not a
             # date32 like the two cards above), so it mirrors TEXT COLLATE "C" directly and the
             # CAST-as-varchar guard compares byte-identically on both backends with no render step in
             # between; and `is_partial` is a BOOLEAN that the card deliberately does NOT serve as a
             # metric (it is measured unreliable -- see the card's notes), so it is not in the numeric
             # set and lands as text. month_num is a bigint label, TEXT COLLATE "C"; harvest_year /
             # month_label / source_idm / source_position_date likewise.
             "silver_unica_monthly_ethanol_sales",
             # LIGHT THE CARD (2026-08-20): silver_minagro_grain_exports joins the mirror in the SAME
             # change that gives it a numbers card -- served but unmirrored means
             # GRAPHRAG_NUMBERS_BACKEND=pg raises UndefinedTable per query and SILENTLY FALLS BACK TO
             # ATHENA (pgnumbers.py, warning-log only). FLAT, projection forbidden, one small object, so
             # the fallback would be a latency cost rather than a LIST-storm one -- the entry exists so
             # the mirror set and the served set cannot drift, which is the whole doctrine.
             # TYPE DOCTRINE: the four wide metrics (my_cumulative_kt, month_to_date_kt,
             # prior_my_cumulative_kt, prior_my_month_kt) mirror NUMERIC. as_of_date is a Glue DATE and
             # stringifies to the Athena ISO render, which is exactly what the guard's CAST-as-varchar
             # compare expects on both backends (the nass_crop_progress / fnc_port shape; NO
             # date_col_type is needed -- that knob is for physical TIMESTAMPs only). crop_slug,
             # marketing_year, prior_marketing_year and source stay TEXT COLLATE "C": the two
             # marketing-year columns are LABELS ('2026/2027'), not periods this card compares, and no
             # partition key exists (partition_keys []), so meta["partitions"] contributes nothing.
             # SIZING NOTE, stated because this table GROWS FROM BOTH ENDS: ten rows per weekly capture,
             # plus whatever an archive backfill lands behind it -- still trivial at any plausible
             # horizon (a decade of weekly captures is ~5,200 rows), so no capacity question arises.
             # SEQUENCING: this entry DEFINES the mirror; the LOAD still has to run in-VPC. The load is
             # NOT a one-off here -- the mirror must be re-run after captures land, or pg answers from a
             # stale snapshot while Athena has the new week. numbers_parity deliberately carries NO
             # SAMPLE_COMMODITY row for it yet (a sampled-but-unmirrored table turns the WHOLE parity
             # gate red), so the pair is chosen against the first real mirror.
             "silver_minagro_grain_exports"]
SCHEMA = "leviathan_dev"                       # == numbers.pgnumbers.SCHEMA == query.ATHENA_DB
GLUE_DB = "leviathan_dev"

_NUM_PG = {"double": "double precision", "float": "real", "bigint": "bigint", "int": "integer",
           "integer": "integer", "smallint": "smallint", "tinyint": "smallint"}


def _glue_table(name: str) -> dict:
    import boto3
    g = boto3.client("glue", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    t = g.get_table(DatabaseName=GLUE_DB, Name=name)["Table"]
    sd = t["StorageDescriptor"]
    cols = [(c["Name"], c["Type"].lower()) for c in sd.get("Columns", [])]
    parts = [(c["Name"], c["Type"].lower()) for c in t.get("PartitionKeys", [])]
    return {"location": sd["Location"], "columns": cols, "partitions": parts}


def _probe_body_columns(location: str) -> set[str]:
    """Physical column names of ONE parquet fragment under `location` (a single-footer schema probe).

    Why: a Glue PARTITION key that ALSO exists inside file bodies (silver_esr_compact post-BF-W2:
    as_of_date is both the vintage partition axis and a per-row column) makes pyarrow's dataset-schema
    unification fail — the declared partition field (string) clashes with the body column
    (large_string), live-proven on the vintage layout. The body value is authoritative (byte-identical
    to the directory value by construction), so such keys are dropped from the partitioning schema.
    Hidden prefixes ('_'/'.') are skipped, mirroring pyarrow's own discovery rule."""
    import boto3
    import pyarrow.dataset as pads
    path = location.removeprefix("s3://").rstrip("/")
    bucket, _, prefix = path.partition("/")
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix):].lstrip("/")
            if any(seg.startswith(tuple(_HIDDEN_PREFIXES)) for seg in rel.split("/")):
                continue                                     # W7: _shadow/ + _manifests/ -- the 2x fence.
                # This is the RAW-LIST reader, where the hazard is real and unguarded (boto3 has no
                # ignore_prefixes default). Checked per SEGMENT, not on the basename, because the twin is
                # `_shadow/as_of_date=<d>/pattern_records.parquet` -- an ordinary file name under a hidden
                # DIRECTORY. See _HIDDEN_PREFIXES for what a doubled count actually costs.
            if obj["Key"].endswith(".parquet"):
                # single URI STRING: the list form skips pyarrow's filesystem-from-URI resolution
                # and raises ArrowInvalid ("Expected a local filesystem path, got a URI") -- caught
                # live at the first BF-W2 in-VPC gate run.
                one = pads.dataset(f"s3://{bucket}/{obj['Key']}", format="parquet")
                return set(one.schema.names)
    return set()


def _numeric_cols(ts) -> set[str]:
    """Columns SQL does arithmetic/aggregation on — everything else mirrors as TEXT."""
    cols: set[str] = set()
    if ts.shape == "wide":
        cols |= set(ts.metrics)                              # metric NAME == column name on wide tables
    if ts.value_col:
        cols.add(ts.value_col)
    for c in (ts.year_col, ts.month_col):
        if c:
            cols.add(c)
    if ts.period_col and ts.period_sql_type == "int":
        cols.add(ts.period_col)
    if ts.commodity_code_col:
        cols.add(ts.commodity_code_col)
    return cols


def _pg_type(name: str, glue_type: str, numeric: set[str]) -> str:
    if name in numeric:
        base = glue_type.split("(")[0]
        return _NUM_PG.get(base, "double precision")
    # COLLATE "C" = byte order = Unicode code-point order = how Presto/Athena compares VARCHARs. The
    # database's linguistic default (en_US) orders punctuation/case differently, which would break
    # ORDER-BY parity on text tiebreak columns (country, period strings).
    return 'text COLLATE "C"'


def _coerce(v, is_numeric: bool):
    if v is None:
        return None
    if is_numeric:
        return v if isinstance(v, (int, float)) else float(v)
    return v if isinstance(v, str) else str(v)


def load_table(ts, conn, *, dry_run: bool = False, batch_rows: int = 20000) -> int:
    physical = ts.athena_table or ts.id
    meta = _glue_table(physical)
    all_cols = meta["columns"] + meta["partitions"]
    numeric = _numeric_cols(ts)
    col_defs = ", ".join(f'"{n}" {_pg_type(n, t, numeric)}' for n, t in all_cols)
    names = [n for n, _ in all_cols]
    is_num = [n in numeric for n in names]
    logger.info("[%s] physical=%s location=%s cols=%d (numeric: %s)",
                ts.id, physical, meta["location"], len(names), sorted(numeric) or "-")
    if dry_run:
        logger.info("[%s] DRY RUN - no DDL/load", ts.id)
        return 0

    import pyarrow as pa
    import pyarrow.dataset as pads

    # Partition keys that also live INSIDE file bodies are excluded from the partitioning schema
    # (unification clash — see _probe_body_columns); their values load from the body columns, and
    # pyarrow tolerates the unparsed directory segment.
    body_cols = _probe_body_columns(meta["location"])
    part_keys = [(n, t) for n, t in meta["partitions"] if n not in body_cols]

    def _open(unified: bool):
        if not unified:
            # EXPLICIT partition schema from Glue's declared types — pyarrow's hive inference types integer
            # path values as int64, which clashes with int32 columns inside the files ("Field year has
            # incompatible types" on silver_production). Glue is the source of truth for partition types.
            _ARROW = {"int": pa.int32(), "integer": pa.int32(), "bigint": pa.int64(),
                      "smallint": pa.int16()}
            part_schema = pa.schema(
                [(n, _ARROW.get(t.split("(")[0], pa.string())) for n, t in part_keys])
            partitioning = pads.partitioning(part_schema, flavor="hive") if part_keys else None
            return pads.dataset(meta["location"], format="parquet", partitioning=partitioning,
                                ignore_prefixes=_HIDDEN_PREFIXES)   # W7: never the _shadow/ twin
        # Glue-derived UNIFIED read schema for fragments whose schemas diverge across write eras
        # (silver_production: year int32 in some files, int64 in others) or that carry all-null columns
        # written as arrow `null` type (silver_wasde: "Unsupported cast from string to null"). Ints widen
        # to int64 / floats to float64 so every fragment casts UP safely; null-typed columns cast to the
        # declared type (null -> anything is a valid cast).
        _WIDE = {"int": pa.int64(), "integer": pa.int64(), "bigint": pa.int64(), "smallint": pa.int64(),
                 "tinyint": pa.int64(), "float": pa.float64(), "double": pa.float64(),
                 "boolean": pa.bool_(), "date": pa.date32(), "timestamp": pa.timestamp("us")}
        read_schema = pa.schema(
            [(n, _WIDE.get(t.split("(")[0], pa.string())) for n, t in meta["columns"]]
            + [(n, _WIDE.get(t.split("(")[0], pa.string())) for n, t in meta["partitions"]])
        wide_parts = pa.schema([(n, _WIDE.get(t.split("(")[0], pa.string())) for n, t in part_keys])
        partitioning = pads.partitioning(wide_parts, flavor="hive") if part_keys else None
        return pads.dataset(meta["location"], format="parquet", partitioning=partitioning,
                            schema=read_schema, ignore_prefixes=_HIDDEN_PREFIXES)   # W7, as above

    flt = None
    if ts.shape == "tall" and ts.metric_col and ts.metrics:
        flt = pads.field(ts.metric_col).isin(list(ts.metrics))   # serve-relevant rows only (wasde: ~2%)

    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    def _load(dataset) -> int:
        n = 0
        # DROP+CREATE (not TRUNCATE) so column-definition changes (e.g. COLLATE "C") actually apply on
        # re-load; pg DDL is transactional, so readers still see the old table until commit.
        with conn.transaction():                                # atomic swap: readers see old rows until commit
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{SCHEMA}"."{physical}"')
                cur.execute(f'CREATE TABLE "{SCHEMA}"."{physical}" ({col_defs})')
                collist = ", ".join(f'"{c}"' for c in names)
                with cur.copy(f'COPY "{SCHEMA}"."{physical}" ({collist}) FROM STDIN') as copy:
                    # dataset schema may lack hive partition cols in some fragments; select explicitly
                    scanner = dataset.scanner(columns=names, filter=flt, batch_size=batch_rows)
                    for rb in scanner.to_batches():
                        pyd = rb.to_pydict()
                        cols = [pyd[c] for c in names]
                        for row in zip(*cols):
                            copy.write_row(tuple(_coerce(v, num) for v, num in zip(row, is_num)))
                            n += 1
        return n

    # Cast failures surface either at dataset() creation (whole-dataset schema unification:
    # silver_production) or MID-SCAN inside _load (fragment-local casts: silver_wasde's null-typed
    # columns raise ArrowNotImplementedError only when their fragment is actually read). The transaction
    # rolls back on exception, so retrying the whole load with the forced Glue schema is clean.
    _CAST_ERRS = (pa.lib.ArrowTypeError, pa.lib.ArrowNotImplementedError, pa.lib.ArrowInvalid)
    n = 0
    t0 = time.time()
    for unified in (False, True):
        try:
            n = _load(_open(unified))
            break
        except _CAST_ERRS as e:
            if unified:
                raise
            logger.info("[%s] arrow cast failure on default read (%s: %s) -> retrying with Glue-derived "
                        "unified read schema", ts.id, type(e).__name__, str(e)[:150])
    with conn.cursor() as cur:                                  # cheap serve-shaped indexes (idempotent)
        for col in filter(None, {ts.commodity_col, ts.metric_col, ts.knowledge_col(), ts.date_col}):
            cur.execute(f'CREATE INDEX IF NOT EXISTS "ix_{physical}_{col}" '
                        f'ON "{SCHEMA}"."{physical}" ("{col}")')
    with conn.cursor() as cur:                                  # REFRESH planner statistics: a DROP+CREATE
        cur.execute(f'ANALYZE "{SCHEMA}"."{physical}"')         # table starts with ZERO stats, so the planner
    #                                                             estimates blindly and can pick a catastrophic
    #                                                             plan for the serve SQL (the vintage ROW_NUMBER
    #                                                             window + row_filters `col IN (...)`) on a large
    #                                                             table -- the 2026-07-22 rev-51 pool death, where
    #                                                             the first heavy run after silver_wasde reloaded
    #                                                             to ~800K rows wedged multi-minute queries that
    #                                                             starved the serving pool. ANALYZE is seconds and
    #                                                             the serving statement_timeout only MASKS a
    #                                                             missing one (kills the bad-plan query, degrades
    #                                                             the lookup to Athena) -- this prevents it.
    logger.info("[%s] loaded %d rows in %.1fs", ts.id, n, time.time() - t0)
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    load_env()
    ap = argparse.ArgumentParser(description="Mirror numbers-registry tables into RDS pg")
    ap.add_argument("--tables", default=",".join(P1_TABLES),
                    help="comma-separated registry table ids (default: the P1 set)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    dsn = os.environ.get("EVIDENCE_PG_DSN")
    if not dsn and not args.dry_run:
        raise SystemExit("EVIDENCE_PG_DSN not set (run in-VPC via the Batch submit)")
    conn = None
    if not args.dry_run:
        import psycopg
        conn = psycopg.connect(dsn, autocommit=True)
    total, failures = 0, []
    for tid in [t.strip() for t in args.tables.split(",") if t.strip()]:
        try:
            total += load_table(reg.get(tid), conn, dry_run=args.dry_run)
        except Exception as e:  # noqa: BLE001 — one table's failure must not kill the rest of the mirror
            logger.error("[%s] FAILED: %s: %s", tid, type(e).__name__, str(e)[:300])
            failures.append(tid)
    logger.info("DONE: %d rows across %s%s", total, args.tables,
                f"  FAILURES: {failures}" if failures else "")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
