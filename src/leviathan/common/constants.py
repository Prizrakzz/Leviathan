"""Pipeline-wide constants shared across batch tasks, Glue jobs, and submit scripts.

All commodity lists are derived from the canonical :data:`CommodityName` Literal
defined in :mod:`leviathan.common.types` to guarantee a single source of truth.
"""
from __future__ import annotations

from typing import get_args

from leviathan.common.types import CommodityName

CHIRPS_START_YEAR: int = 1981
CPC_SOIL_MOISTURE_START_YEAR: int = 2000

# Minimum expected raw file sizes in bytes, keyed by source identifier.
# Files below these thresholds indicate a truncated/empty download.
MIN_RAW_FILE_SIZES: dict[str, int] = {
    "nasa_power": 1_000,              # 1 KB — each monthly JSON window is typically 50–200 KB
    "faostat_qcl": 10_000_000,        # 10 MB — the FAOSTAT QCL ZIP is ~50 MB in practice
    "conab": 500_000,                 # 500 KB — CONAB coffee bulletins are typically 1–3 MB
    "usda_fas_coffee_wmt": 100_000,   # 100 KB — WMT circulars are typically 1–2 MB
    "usda_gain_coffee": 30_000,        # 30 KB — GAIN attaché reports range from 50 KB to 500 KB
    "usda_gain": 30_000,               # 30 KB — generic GAIN key used by fetch_gain.py for all other commodities
    "mpob": 5_000,                    # 5 KB — MPOB BEPI HTML table pages are typically 20–80 KB
    "mpob_overview_pdf": 50_000,       # 50 KB — early PDFs (2010-2011) can be ~100 KB; guards against empty responses
    "mpoc_trade_stats": 50_000,        # 50 KB — annual HTML pages are ~350-390 KB in practice
    "mpoc_stock_comparison": 5_000,    # 5 KB — single page with tables + narrative, ~390 KB in practice
    "mpoc_competitive_prices": 1_000,  # 1 KB — small table page, ~330 KB in practice
    "mpoc_article": 2_000,             # 2 KB — individual article pages vary widely
    "usda_psd": 10_000_000,            # 10 MB — bulk ZIP is ~50-80 MB compressed in practice
    "usda_nass_crops": 800_000_000,    # 800 MB — qs.crops bulk .gz is ~1.05 GB in practice
    "sagis_swb": 50_000,               # 50 KB — SWB bulletins are multi-page with charts
    "sagis_weekly": 5_000,             # 5 KB — oldest .xls files (2005/06) may be small
    "sagis_cec": 5_000,                # 5 KB — old .doc/.xls reports (2001-2006) can be small
    "usda_ams_cotton_classing_annual": 100_000,  # 100 KB — older reports (2008-2017) can be ~250 KB; modern ones are 2-4 MB
    "usda_nass_citrus": 30_000,                  # 30 KB — conservative floor; smallest observed monthly PDFs are ~80 KB
    "usda_wasde_txt": 10_000,                     # 10 KB — some early 1995 TXT reports are ~15 KB
    "usda_wasde_pdf": 40_000,                     # 40 KB — early digital PDFs (2000–2003) observed at 75–87 KB; magic-bytes check handles truncation
    "world_bank_pink_sheet": 500_000,             # 500 KB — actual file is ~783 KB; guards against error-page HTML responses
    "wb_cmo_outlook": 15_000,                      # 15 KB — modern reports are 3–8 MB; 1999 monthly data-table PDFs can be as small as 36 KB; catches HTML error pages
    "cftc_cot": 100_000,                            # 100 KB — weekly TXT is ~200-400 KB; annual extracted TXT is ~3-5 MB; catches HTML error pages
    "usda_esr": 500,                                  # 500 B — ESR JSON arrays for sparse early years can be small; catches HTML error pages from api.data.gov
    "databento": 200,                                 # 200 B -- a zstd DBN file whose only content is the header is ~150-190 B; the floor catches a truncated/empty batch download without rejecting a legitimately sparse year (KE 2013 = 74 bars)
    "databento_symbology": 200,                       # 200 B -- the two-step resolve artifact always carries the ten symbology.resolve keys plus the per-symbol outright verdict; anything smaller is a truncated write
    "czce": 5_000,                                    # 5 KB -- the daily FutureDataDaily.txt is 21,982 B on the earliest session (2015-10-08, 17 roots) and 37,747 B in 2026 (26 roots); the floor catches a CZCE WAF 412 challenge body or a truncated read. NOTE check_min_file_size returns SILENTLY for an unknown source, so a MISSING entry is a DISABLED floor, not an error
    "jse_safex": 40_000,                              # 40 KB -- the agri MTM sheet measures 81,920 B (legacy OLE, 31 contract sections); the floor catches a portal error page served with HTTP 200
    "cepea_widget": 500,                              # 500 B -- the daily widget is ~1,988 B of document.write() markup carrying ONE value; the Cloudflare cdn-cgi challenge body is ~5,600 B and is BIGGER, so size cannot separate them -- the producer treats a 403 as a HARD failure and this floor is only the truncated-read backstop
    "cepea_wayback": 50_000,                          # 50 KB -- the one-shot archive recovery measures 386,048 B (id 23) / 246,784 B (id 77); the 2017 captures ARE the newest that exist (corrected 2026-07-29 -- the earlier 136,726 B / 2025 note here trusted a wayback timestamp that had no capture behind it)
    "cepea_live": 100_000,                            # 100 KB -- the apex-host live series exports measure ~552 KB (id 23) / ~408 KB (id 77), verified 2026-07-29; the producer additionally parse-validates header, spans and the archive JOIN ROW before landing, so this floor is only the truncated-read backstop
    "miax": 1_000,                                    # 1 KB -- the daily settlement CSV measures 6,676 B for 75 rows (7 outrights + 68 options); a Drupal 404 page is 63,668 B and is caught by STATUS, never by size, so this floor catches truncation only
    "dce_daily": 500,                                 # 500 B -- the per-variety quote JSON measures 5,184 B for the 12 listed palm-olein contracts (~430 B per contract); the empty success envelope {"success":true,...,"data":[]} is ~140 B, so this floor separates "a thin variety" from "the WAF answered 200 with nothing". The all-zero-settle NOT_READY shape is a DIFFERENT check and lives in the producer -- it is full-size and no floor can see it
    "dce_history": 4_000,                             # 4 KB -- the per-(variety, year) workbook measures 188,440 B for 2016 palm olein (2,928 rows); an xlsx carrying a single row still costs ~5 KB of zip + styles overhead, so this floor catches a truncated download without rejecting a variety's thin first year
    "euronext": 2_000,                                # 2 KB -- the landed object is the rendered table's outerHTML ONLY, never the page: 11,848 B for EBM's 12 expiries (whitespace-normalized), ~10 expiries on EMA/ECO. The empty server-side shell (a thead and no tbody rows) is well under this and is exactly what the floor exists to catch; a WAF/error page cannot reach here at all, because the producer captures a DOM element rather than a response body
    "bursa": 2_000,                                   # 2 KB -- the landed object is {"thead": [...], "api": <body>}; the day body alone measures 14,195 B for 24 delivery months. A Cloudflare challenge body never gets this far (it is a 403 that the in-page fetch refuses), so this floor catches a truncated curve or an empty data array
}

ALL_COMMODITIES: tuple[CommodityName, ...] = get_args(CommodityName)

# ---------------------------------------------------------------------------
# Silver-readiness IAM role identities (SILVER-F014, Milestone R1)
# ---------------------------------------------------------------------------
# SINGLE SOURCE OF TRUTH for the two-role validator/publisher separation. The
# Terraform module ``infra/terraform/modules/iam`` builds the SAME names as
# ``${var.project_name}-${var.environment}-silver-{validator,publisher}`` and
# ``leviathan.common.publish_guard`` imports these so the canonical role-ARN
# match pattern is NOT a duplicated string literal (a drift between the two
# would silently change which identity may mint canonical partitions).
#
#   * validator -- READ-ONLY (Glue/S3-Inventory/parquet/Athena-results inspect).
#     Recognised by publish_guard as a deny-first identity: it can never select
#     ``--publish-mode canonical`` even with a valid approval.
#   * publisher -- the single gated deployer/publisher. Recognised by
#     publish_guard as a canonical-capable role ARN; canonical writes still
#     require a signed approval AND (in IAM) the explicit silver/ deny flipped.
IAM_ROLE_NAME_PREFIX: str = "leviathan-dev"  # == "${project_name}-${environment}"
SILVER_VALIDATOR_ROLE_NAME: str = f"{IAM_ROLE_NAME_PREFIX}-silver-validator"
SILVER_PUBLISHER_ROLE_NAME: str = f"{IAM_ROLE_NAME_PREFIX}-silver-publisher"

SILVER_WEATHER_ID_COLS: list[str] = [
    "date",
    "year",
    "month",
    "day",
    "country",
    "region",
    "commodity",
    "source",
    "ingest_date",
]
