from __future__ import annotations


def parse_hive_key(key: str, field: str) -> str:
    """Extract the value of a hive-partition field from an S3 key.

    Example:
        parse_hive_key("raw/weather/commodity=cocoa/country=US/file.json", "country")
        # returns "US"
    """
    return next((p[len(field) + 1:] for p in key.split("/") if p.startswith(f"{field}=")), "")


def raw_weather_key(
    source: str,
    commodity: str,
    country: str,
    region: str,
    year: int,
    month: int,
    filename: str,
) -> str:
    return (
        f"raw/weather/"
        f"source={source}/"
        f"commodity={commodity}/"
        f"country={country}/"
        f"region={region}/"
        f"year={year}/"
        f"month={month:02d}/"
        f"{filename}"
    )


def raw_production_key(
    source: str,
    commodity: str,
    year: int,
    filename: str,
) -> str:
    return (
        f"raw/production/"
        f"source={source}/"
        f"commodity={commodity}/"
        f"year={year}/"
        f"{filename}"
    )


def raw_wmt_key(publication_date: str) -> str:
    """S3 key for a USDA FAS Coffee World Markets and Trade circular PDF.

    Args:
        publication_date: Publication date in ``YYYYMMDD`` format, e.g. ``"20251218"``.
    """
    filename = f"coffee_wmt_{publication_date}.pdf"
    return (
        f"raw/production/"
        f"source=usda_fas_coffee_wmt/"
        f"publication_date={publication_date}/"
        f"{filename}"
    )


def raw_gain_key(
    source_name: str,
    country_iso2: str,
    publication_date: str,
    filename: str,
) -> str:
    """Generic S3 key for any USDA FAS GAIN commodity report PDF.

    Args:
        source_name: Source identifier, e.g. ``"usda_gain_wheat"``.
        country_iso2: ISO 3166-1 alpha-2 country code, e.g. ``"US"``.
        publication_date: Publication date in ``YYYYMMDD`` format.
        filename: Sanitised PDF filename (spaces replaced by underscores).
    """
    return (
        f"raw/production/"
        f"source={source_name}/"
        f"country={country_iso2}/"
        f"publication_date={publication_date}/"
        f"{filename}"
    )


def raw_gain_coffee_key(
    country_iso2: str,
    publication_date: str,
    filename: str,
) -> str:
    """S3 key for a USDA FAS GAIN Coffee Annual / Semi-annual report PDF."""
    return raw_gain_key("usda_gain_coffee", country_iso2, publication_date, filename)


def raw_conab_key(
    crop_year: str,
    survey_number: int,
    ext: str = ".pdf",
) -> str:
    """S3 key for a CONAB Boletim da Safra de Café PDF.

    One PDF covers all coffee commodities; no commodity partition at raw layer.

    Args:
        crop_year: Marketing year in underscore format, e.g. ``"2024_25"``.
        survey_number: Survey number within the season (1–5).  For pre-2013
            OlalaCMS bulletins this is the publication month (1–12).
        ext: File extension including dot, e.g. ``".pdf"`` (default) or
            ``".doc"`` for OLE2/Word captures from the pre-2013 OlalaCMS era.
    """
    filename = f"boletim_cafe_{crop_year}_{survey_number:02d}{ext}"
    return (
        f"raw/production/"
        f"source=conab/"
        f"crop_year={crop_year}/"
        f"survey={survey_number:02d}/"
        f"{filename}"
    )


def raw_conab_hist_series_key(
    safra_year: int,
    survey_no: int,
    filename: str,
) -> str:
    """S3 key for a CONAB per-bulletin Excel (previsão de safra) data file.

    Args:
        safra_year: Marketing year the survey covers, e.g. ``2026``.
        survey_no: Survey number within the season (1–5).
        filename: Original Excel filename, e.g. ``"site_previsao-de-safra-cafe-fev-2026.xls"``.
    """
    return (
        f"raw/production/"
        f"source=conab/"
        f"bulletin_xls/"
        f"safra_year={safra_year}/"
        f"survey={survey_no:02d}/"
        f"{filename}"
    )


def raw_fnc_excel_key(filename: str) -> str:
    """S3 key for a FNC Colombia bulk Excel data file.

    Args:
        filename: Original Excel filename, e.g.
            ``"Precios-area-y-produccion-de-cafe-2026-1.xlsx"``.
    """
    return f"raw/production/source=fnc/bulk/{filename}"


def raw_fnc_report_key(
    report_type: str,
    upload_year: int,
    upload_month: int,
    filename: str,
) -> str:
    """S3 key for a FNC Colombia monthly report PDF.

    The upload_year/upload_month come from the ``/wp-content/uploads/YYYY/MM/``
    path component and represent when the file was uploaded to the FNC server,
    not necessarily the report reference month.

    Args:
        report_type: ``"cifras"`` or ``"exportaciones"``.
        upload_year: Year from the uploads URL path component.
        upload_month: Month from the uploads URL path component.
        filename: URL-decoded PDF filename.
    """
    return (
        f"raw/production/"
        f"source=fnc/"
        f"monthly_reports/"
        f"report_type={report_type}/"
        f"upload_year={upload_year}/"
        f"upload_month={upload_month:02d}/"
        f"{filename}"
    )


def raw_cotton_annual_key(season_year: int, filename: str) -> str:
    """S3 key for a USDA AMS Cotton Annual Quality Report PDF.

    Args:
        season_year: Beginning year of the marketing season, e.g. ``2024``
            for the 2024-25 season.  For archive PDFs (1986-2013) this equals
            the year in the filename (e.g. ``1986`` for ``1986ACQ.pdf``).
        filename: PDF filename, e.g. ``"2013ACQ.pdf"`` or ``"ams_1658_00010.pdf"``.
    """
    return (
        f"raw/production/"
        f"source=usda_ams_cotton_classing/"
        f"report_type=annual_quality/"
        f"season={season_year}/"
        f"{filename}"
    )


def raw_nass_citrus_key(season: str, report_type: str, filename: str) -> str:
    """S3 key for a USDA NASS Florida Citrus PDF.

    Args:
        season: Season string in ``YYYY-YY`` format, e.g. ``"2024-25"``.
        report_type: One of ``monthly_forecast``, ``maturity_test``,
            ``freeze_damage``, ``annual_statistics``,
            ``citrus_summary_prelim``, ``citrus_summary_final``.
        filename: PDF filename, e.g. ``"cit0425.pdf"``.
    """
    return (
        f"raw/production/"
        f"source=usda_nass_citrus/"
        f"report_type={report_type}/"
        f"season={season}/"
        f"{filename}"
    )


def raw_reference_key(
    source: str,
    domain: str,
    commodity: str,
    filename: str,
) -> str:
    return (
        f"raw/reference/"
        f"source={source}/"
        f"domain={domain}/"
        f"commodity={commodity}/"
        f"{filename}"
    )

def bronze_production_key(
    source: str,
    dataset: str,
    commodity: str,
    year: int,
    filename: str,
) -> str:
    return (
        f"bronze/production/"
        f"source={source}/"
        f"dataset={dataset}/"
        f"commodity={commodity}/"
        f"year={year}/"
        f"{filename}"
    )

def bronze_weather_key(
    source: str,
    commodity: str,
    country: str,
    region: str,
    year: int,
    month: int,
    filename: str,
) -> str:
    return (
        f"bronze/weather/"
        f"source={source}/"
        f"commodity={commodity}/"
        f"country={country}/"
        f"region={region}/"
        f"year={year}/"
        f"month={month:02d}/"
        f"{filename}"
    )

def silver_production_key(
    commodity: str,
    year: int,
    filename: str,
) -> str:
    return (
        f"silver/production/"
        f"commodity={commodity}/"
        f"year={year}/"
        f"{filename}"
    )


def silver_weather_key(
    source: str,
    commodity: str,
    country: str,
    region: str,
    year: int,
    month: int,
    filename: str,
) -> str:
    return (
        f"silver/weather/"
        f"source={source}/"
        f"commodity={commodity}/"
        f"country={country}/"
        f"region={region}/"
        f"year={year}/"
        f"month={month:02d}/"
        f"{filename}"
    )


def raw_mpob_monthly_key(year: int, month: int) -> str:
    """S3 key for an MPOB BEPI monthly release HTML page.

    One HTML file per calendar month; contains national + regional CPO
    production, closing stocks, exports, imports, and FFB price data.

    Args:
        year:  Calendar year, e.g. ``2026``.
        month: Calendar month (1–12).
    """
    filename = f"mpob_monthly_{year}_{month:02d}.html"
    return (
        f"raw/production/"
        f"source=mpob/"
        f"release_type=monthly_release/"
        f"year={year}/"
        f"month={month:02d}/"
        f"{filename}"
    )


def raw_mpob_overview_pdf_key(year: int) -> str:
    """S3 key for an MPOB BEPI *Overview of Industry* annual PDF.

    These PDFs predate the BEPI HTML stat pages (which start 2017) and are
    the primary data source for years ≤2016.  Files are named differently
    across years on the source server but are normalised here.

    Args:
        year: Calendar year, e.g. ``2016``.
    """
    filename = f"mpob_overview_{year}.pdf"
    return (
        f"raw/production/"
        f"source=mpob/"
        f"release_type=overview_pdf/"
        f"year={year}/"
        f"{filename}"
    )


# ---------------------------------------------------------------------------
# MPOC (Malaysian Palm Oil Council) — market data and narrative
# ---------------------------------------------------------------------------

def raw_mpoc_trade_stats_key(year: int) -> str:
    """S3 key for an MPOC Monthly Palm Oil Trade Statistics HTML page.

    One page per calendar year; contains Malaysia's exports/imports,
    export destinations by country, production & stocks, and CPO prices.
    Available years: 2009–2023.
    """
    filename = f"mpoc_trade_stats_{year}.html"
    return (
        f"raw/production/"
        f"source=mpoc/"
        f"release_type=trade_statistics/"
        f"year={year}/"
        f"{filename}"
    )


def raw_mpoc_stock_comparison_key() -> str:
    """S3 key for the MPOC Stock Comparison page.

    Single live page covering oils & fats ending stocks for China, India,
    Pakistan, Bangladesh, and USA — cross-commodity (Palm, Soy, Sunflower,
    Rapeseed) with analyst narrative paragraphs per country.
    Re-run without --skip-existing-s3 to refresh with current month's data.
    """
    return (
        "raw/production/"
        "source=mpoc/"
        "release_type=stock_comparison/"
        "mpoc_stock_comparison.html"
    )


def raw_mpoc_competitive_prices_key() -> str:
    """S3 key for the MPOC Competitive Price Table page.

    Monthly CPO BMD+3 vs SBO ARG FOB vs SFO Black Sea FOB price comparison
    with price premiums of substitute oils over CPO.
    Single live page — re-run without --skip-existing-s3 to refresh.
    """
    return (
        "raw/production/"
        "source=mpoc/"
        "release_type=competitive_prices/"
        "mpoc_competitive_prices.html"
    )


def raw_mpoc_article_key(slug: str) -> str:
    """S3 key for an MPOC Market Highlights article.

    Args:
        slug: URL slug of the article, e.g.
              ``"the-rise-of-aseans-foodservice-industry-an-engine-for-palm-oil-demand"``.
    """
    filename = f"mpoc_article_{slug}.html"
    return (
        f"raw/production/"
        f"source=mpoc/"
        f"release_type=market_highlights/"
        f"slug={slug}/"
        f"{filename}"
    )


def raw_mpob_annual_key(year: int) -> str:
    """S3 key for an MPOB BEPI annual summary HTML page.

    One HTML file per calendar year; contains national CPO production,
    closing stocks, exports, imports, and FFB price for all 12 months.

    Args:
        year: Calendar year, e.g. ``2026``.
    """
    filename = f"mpob_annual_summary_{year}.html"
    return (
        f"raw/production/"
        f"source=mpob/"
        f"release_type=annual_summary/"
        f"year={year}/"
        f"{filename}"
    )


def unica_raw_key(harvest_year: str) -> str:
    """S3 key for a UNICA production-and-milling HTML page.

    One HTML file covers one full harvest year; no commodity partition
    (UNICA reports Center-South aggregate totals only).

    Args:
        harvest_year: Harvest year in slash format, e.g. ``"2024/25"``.
    """
    hy = harvest_year.replace("/", "_")
    return f"raw/production/source=unica/harvest_year={hy}/production_milling.html"


def unica_biweekly_raw_key(harvest_year: str, idm: str) -> str:
    """S3 key for a UNICA bi-weekly (quinzenal) production report PDF.

    One PDF per bulletin; ``idm`` is the UNICADATA ``download_media.php?idM=``
    value and uniquely identifies the bulletin across languages.

    Args:
        harvest_year: Harvest year in slash format, e.g. ``"2024/2025"``.
        idm: The UNICADATA media download ID, e.g. ``"12439002"``.
    """
    hy = harvest_year.replace("/", "_")
    return f"raw/production/source=unica_biweekly/harvest_year={hy}/idm={idm}/report.pdf"


# ---------------------------------------------------------------------------
# USDA PSD (Production, Supply and Distribution) — global S/D balance sheets
# ---------------------------------------------------------------------------

def raw_psd_bulk_key(release_date: str) -> str:
    """S3 key for a USDA PSD bulk all-commodities ZIP download.

    One ZIP per download event; contains a single CSV with all commodities,
    all countries, all marketing years (1960s–present), and all monthly
    WASDE vintages.  The ``Month`` column in the CSV identifies the WASDE
    release month, enabling revision-surprise feature engineering downstream.

    Downloaded without authentication from:
        https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip

    Args:
        release_date: Date of download in ``YYYY-MM-DD`` format, e.g.
            ``"2026-05-20"``.  Using date (not month) avoids key collision
            when downloading both before and after the WASDE release within
            the same calendar month.
    """
    return (
        f"raw/production/"
        f"source=usda_psd/"
        f"release_type=bulk/"
        f"release_date={release_date}/"
        f"psd_alldata.zip"
    )


# ---------------------------------------------------------------------------
# USDA NASS QuickStats — U.S. domestic crop survey & Crop Progress
# ---------------------------------------------------------------------------

def raw_nass_crops_key(download_date: str) -> str:
    """S3 key for a USDA NASS QuickStats bulk crops sector .gz download.

    One .gz file per download event; contains the full QuickStats CROPS sector
    as a tab-delimited CSV covering all U.S. commodities (corn, soybeans, wheat,
    cotton, rice, sugar cane, ...), all geographies (national, state, county),
    and all time periods from the 1860s through the present day.

    Critically, this file includes the weekly **Crop Progress** series
    (``statisticcat_desc = 'PROGRESS'``, ``unit_desc = 'PCT'``) alongside the
    standard annual AREA PLANTED / AREA HARVESTED / YIELD / PRODUCTION stats.
    The Crop Progress Good/Excellent % is the most-watched leading indicator for
    U.S. corn and soybean futures during the growing season.

    Downloaded without authentication from:
        https://www.nass.usda.gov/datasets/qs.crops_{YYYYMMDD}.txt.gz

    The filename is date-stamped and regenerated nightly (~3 am ET); the
    ``download_date`` is discovered by scraping the datasets page and parsing
    the filename, not from wall-clock time.

    Args:
        download_date: Date embedded in the discovered filename, in
            ``YYYY-MM-DD`` format, e.g. ``"2026-05-20"``.
    """
    return (
        f"raw/production/"
        f"source=usda_nass/"
        f"sector=crops/"
        f"download_date={download_date}/"
        f"qs.crops.txt.gz"
    )


# ---------------------------------------------------------------------------
# USDA WAP (World Agricultural Production)
# ---------------------------------------------------------------------------

def raw_wap_key(release_month: str) -> str:
    """S3 key for a USDA FAS World Agricultural Production monthly PDF.

    One file per calendar month; the filename is always ``production.pdf``
    (matching the CDN source).

    Args:
        release_month: ``YYYY-MM``, e.g. ``"2026-05"``.
    """
    return (
        f"raw/production/"
        f"source=usda_wap/"
        f"release_month={release_month}/"
        f"production.pdf"
    )


# ---------------------------------------------------------------------------
# USDA WASDE
# ---------------------------------------------------------------------------

def raw_wasde_key(release_date: str, mmyy: str, fmt: str) -> str:
    """S3 key for a single USDA WASDE release file.

    Args:
        release_date: YYYY-MM-DD, e.g. "1995-01-12" or "2026-05-12"
        mmyy: Two-digit month + two-digit year, e.g. "0195" for January 1995,
              "0526" for May 2026.
        fmt: File format extension — "txt" (1995–1999) or "pdf" (all other years).
    """
    return (
        f"raw/production/"
        f"source=usda_wasde/"
        f"release_date={release_date}/"
        f"wasde{mmyy}.{fmt}"
    )


# ---------------------------------------------------------------------------
# SAGIS (South African Grain Information Service) — Weekly Bulletin
# ---------------------------------------------------------------------------

def raw_sagis_swb_key(upload_year: int, upload_month: int, filename: str) -> str:
    """S3 key for a SAGIS South Africa Weekly Bulletin (SWB) PDF.

    The ``upload_year`` / ``upload_month`` come from the
    ``/wp-content/uploads/YYYY/MM/`` URL path component, consistent with
    ``raw_fnc_report_key()``.  Bulletin date extraction is deferred to the
    bronze transform.

    Args:
        upload_year:  Year from the uploads URL path component, e.g. ``2026``.
        upload_month: Month from the uploads URL path component, e.g. ``5``.
        filename:     URL-decoded PDF filename, e.g. ``"SWB_20260514.pdf"``.
    """
    return (
        f"raw/production/"
        f"source=sagis_swb/"
        f"upload_year={upload_year}/"
        f"upload_month={upload_month:02d}/"
        f"{filename}"
    )


def raw_sagis_weekly_key(dataset: str, crop: str, filename: str) -> str:
    """S3 key for a SAGIS South Africa Weekly Data Excel file.

    SAGIS publishes one cumulative Excel/XLS file per marketing season per
    crop, updated weekly with a new filename (new week number).  Both the
    current-season weekly snapshots and historical season-end files are stored
    under the same flat ``dataset/crop/`` prefix.

    Args:
        dataset:  One of ``"producer_deliveries"``, ``"imp_exp_intentions"``,
                  ``"imp_exp_progressive"``, ``"imp_exp_historic"``.
        crop:     One of ``"maize"``, ``"maize_grade"``, ``"wheat"``,
                  ``"soybeans"``, ``"sunflower"``.
        filename: URL-decoded Excel filename as-is, e.g.
                  ``"ProdProgressive-Mielies_2026-2027_03.xlsx"``.
    """
    return (
        f"raw/production/"
        f"source=sagis_weekly/"
        f"dataset={dataset}/"
        f"crop={crop}/"
        f"{filename}"
    )


def raw_sagis_cec_key(filename: str) -> str:
    """S3 key for a SAGIS South Africa Crop Estimates Committee (CEC) report.

    Flat layout — no upload_year/upload_month partition.  The WordPress upload
    path is unreliable: SAGIS bulk-uploaded the historical archive (~170 files)
    to ``/2026/05/`` in May 2026, so the upload path bears no relation to
    document date for pre-2025 content.

    Args:
        filename: URL-decoded filename as-is, e.g. ``"CEC_2026-05-07.pdf"``
                  or ``"CEC-2024-12.doc"``.
    """
    return f"raw/production/source=sagis_cec/{filename}"
