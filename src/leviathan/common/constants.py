from __future__ import annotations

CHIRPS_START_YEAR: int = 1981

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
    "usda_wasde_pdf": 200_000,                    # 200 KB — floor covers scanned (1973–1994) and digital PDFs
}

ALL_COMMODITIES: list[str] = [
    "cocoa",
    "corn_cbot",
    "campinas_corn_reference_bmf",
    "french_wheat_matif",
    "french_maize_matif",
    "hard_red_winter_wheat_kcbt",
    "hard_red_spring_wheat_mgex",
    "soft_red_winter_wheat_cbot",
    "rough_rice_cbot",
    "south_african_white_maize_jse",
    "south_african_yellow_maize_jse",
    "soybeans_cbot",
    "soybean_meal_cbot",
    "soybean_oil_cbot",
    "soybeans_no_1_dce",
    "soybeans_no_2_dce",
    "soybean_meal_dce",
    "soybean_oil_dce",
    "french_rapeseed_matif",
    "canola_ice",
    "rapeseed_oil_zce",
    "rapeseed_meal_zce",
    "malaysian_crude_palm_oil_cme",
    "palm_olein_dce",
    "brazilian_arabica_coffee",
    "arabica_coffee",
    "robusta_coffee",
    "cotton",
    "raw_sugar",
    "white_sugar",
    "frozen_orange_juice",
]
