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
}

ALL_COMMODITIES: tuple[CommodityName, ...] = get_args(CommodityName)

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
