from __future__ import annotations

CHIRPS_START_YEAR: int = 1981

# Minimum expected raw file sizes in bytes, keyed by source identifier.
# Files below these thresholds indicate a truncated/empty download.
MIN_RAW_FILE_SIZES: dict[str, int] = {
    "nasa_power": 1_000,              # 1 KB — each monthly JSON window is typically 50–200 KB
    "faostat_qcl": 10_000_000,        # 10 MB — the FAOSTAT QCL ZIP is ~50 MB in practice
    "conab": 500_000,                 # 500 KB — CONAB coffee bulletins are typically 1–3 MB
    "usda_fas_coffee_wmt": 100_000,   # 100 KB — WMT circulars are typically 1–2 MB
    "mpob": 5_000,                    # 5 KB — MPOB BEPI HTML table pages are typically 20–80 KB
    "mpob_overview_pdf": 50_000,       # 50 KB — early PDFs (2010-2011) can be ~100 KB; guards against empty responses
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
