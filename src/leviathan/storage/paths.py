from __future__ import annotations


def raw_modis_ndvi_key(run_id: str, group: str, filename: str) -> str:
    """S3 key for a raw MODIS NDVI results CSV downloaded from AppEEARS.

    Args:
        run_id:   Fetch run identifier, e.g. ``"20260524T203000Z"``.
        group:    Commodity group name, e.g. ``"grains"``.
        filename: Original AppEEARS CSV filename.
    """
    return f"raw/weather/source=modis_ndvi/run_id={run_id}/group={group}/{filename}"


def bronze_modis_ndvi_key(
    commodity: str,
    country: str,
    region: str,
    year: int,
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for a MODIS NDVI bronze Parquet file.

    One file per (commodity, country, region, year); each file contains
    up to 23 rows — one per 16-day composite period within the year.
    """
    return (
        f"bronze/weather/source=modis_ndvi/"
        f"commodity={commodity}/"
        f"country={country}/"
        f"region={region}/"
        f"year={year}/"
        f"{filename}"
    )


def silver_modis_ndvi_key(
    commodity: str,
    country: str,
    region: str,
    year: int,
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for a MODIS NDVI silver Parquet file (includes z-scores)."""
    return (
        f"silver/weather/source=modis_ndvi/"
        f"commodity={commodity}/"
        f"country={country}/"
        f"region={region}/"
        f"year={year}/"
        f"{filename}"
    )


def raw_cpc_tif_key(variable: str, date_str: str, filename: str) -> str:
    """S3 key for a CPC Leaky Bucket daily GeoTIFF file.

    Args:
        variable: Variable prefix, e.g. ``"w"`` (soil moisture).
        date_str: Date in ``YYYYMMDD`` format, e.g. ``"20240115"``.
        filename: Original filename, e.g. ``"w.20240115.tif"``.
    """
    return (
        f"raw/weather/"
        f"source=cpc_soil/"
        f"variable={variable}/"
        f"date={date_str}/"
        f"{filename}"
    )


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


def bronze_ams_cotton_key(season: int) -> str:
    """S3 key for a USDA AMS Cotton Annual Quality bronze Parquet.

    One file per season — long-format (metric, value) rows extracted from
    the annual quality report narrative and distribution tables.

    Args:
        season: Beginning year of the marketing season, e.g. ``2024``.
    """
    return (
        f"bronze/production/"
        f"source=usda_ams_cotton_classing/"
        f"season={season}/"
        f"part-000.parquet"
    )


def silver_ams_cotton_key() -> str:
    """S3 key for the USDA AMS Cotton Annual Quality silver Parquet.

    Single flat file — one row per season, all quality metrics wide-format.
    """
    return "silver/ams_cotton_quality/part-000.parquet"


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


def bronze_nass_citrus_key(season: str, report_type: str, report_month: int) -> str:
    """S3 key for a USDA NASS Citrus bronze Parquet.

    One file per (season, report_type, report_month).  For ``monthly_forecast``
    reports this maps to one Parquet per calendar month of the season
    (Oct = 10 through Jul = 7 of the following year).

    Args:
        season:       Season in ``YYYY-YY`` format, e.g. ``"2024-25"``.
        report_type:  E.g. ``"monthly_forecast"``.
        report_month: Calendar month number (1–12), e.g. ``1`` for January.
    """
    return (
        f"bronze/production/"
        f"source=usda_nass_citrus/"
        f"report_type={report_type}/"
        f"season={season}/"
        f"report_month={report_month:02d}/"
        f"part-000.parquet"
    )


def silver_nass_citrus_key() -> str:
    """S3 key for the USDA NASS Citrus silver Parquet.

    Single flat file — one row per (season, report_month, crop, state).
    Contains the current-month forecast, prior-month revision, and HLB
    structural decline index.
    """
    return "silver/nass_citrus/part-000.parquet"


def raw_icco_qbcs_summary_key(release_date: str, filename: str) -> str:
    """S3 key for a parsed ICCO QBCS quarterly bulletin summary JSON or raw HTML.

    Args:
        release_date: ISO 8601 release date, e.g. ``"2024-11-29"``.
        filename: File name, e.g. ``"icco_qbcs_summary_20241129.json"`` or
            ``"page.html"``.
    """
    return (
        f"raw/production/"
        f"source=icco_qbcs_summary/"
        f"release_date={release_date}/"
        f"{filename}"
    )


def raw_icco_ewg_stocks_key(season: str, filename: str) -> str:
    """S3 key for a parsed ICCO EWG annual cocoa bean stocks report JSON or raw HTML.

    Args:
        season: Cocoa season in ``YYYY-YY`` format, e.g. ``"2024-25"``.
        filename: File name, e.g. ``"icco_ewg_stocks_2024-25.json"`` or
            ``"page.html"``.
    """
    return (
        f"raw/production/"
        f"source=icco_ewg_stocks/"
        f"season={season}/"
        f"{filename}"
    )


def bronze_icco_qbcs_key(release_date: str) -> str:
    """S3 key for an ICCO QBCS quarterly summary bronze Parquet.

    One file per quarterly release date — 8 rows per file
    (2 vintages × 4 metrics: production, grindings, end_stocks, surplus_deficit).

    Args:
        release_date: ISO 8601 release date, e.g. ``"2024-11-29"``.
    """
    return (
        f"bronze/production/"
        f"source=icco_qbcs/"
        f"release_date={release_date}/"
        f"part-000.parquet"
    )


def bronze_icco_ewg_key(season: str) -> str:
    """S3 key for an ICCO EWG annual cocoa bean stocks bronze Parquet.

    One file per cocoa season — one row per stock location category.

    Args:
        season: Cocoa season in ``YYYY-YY`` format, e.g. ``"2020-21"``.
    """
    return (
        f"bronze/production/"
        f"source=icco_ewg_stocks/"
        f"season={season}/"
        f"part-000.parquet"
    )


def silver_icco_cocoa_key() -> str:
    """S3 key for the ICCO cocoa silver Parquet.

    One row per cocoa year — latest quarterly estimate for production,
    grindings, end-season stocks, S/U ratio, and grindings trend deviation.
    """
    return "silver/icco_cocoa/part-000.parquet"


def text_cmo_outlook_key(release_ym: str) -> str:
    """S3 key for the extracted text document for a single WB CMO Outlook PDF.

    One file per release — mirrors the raw key Hive partition structure.
    Written by the CMO Outlook text extraction pipeline.

    Args:
        release_ym: Publication year-month in ``YYYY-MM`` format,
                    e.g. ``"2022-04"``.
    """
    return (
        f"text/"
        f"source=wb_cmo_outlook/"
        f"release={release_ym}/"
        f"document.json"
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


# ---------------------------------------------------------------------------
# Weather SILVER staging (A1-A2 weather_daily coherence).
#
# The per-source bronze->silver producers write MONTH-grain objects, but the
# canonical weather silver layout is the COMPACTED [commodity, year] grain
# (SILVER-F047; ``commodity=<c>/year=<y>/part-000.parquet``). Re-minting
# month-grain objects UNDER ``commodity=<c>/`` would resurrect the ~590k
# tiny-file layout AND be double-read by every raw-LIST consumer that bounds
# on ``year=`` (leviathan.features.extractors._paths_with_year_partitions and
# gold_weather_z._read_long both LIST ``.../source=<s>/commodity=<c>/`` and keep
# every ``.parquet`` whose key carries a ``year=`` segment). So the daily chain's
# b2s writes month-grain to a NON-canonical STAGING prefix that sits OUTSIDE the
# ``commodity=`` data plane -- ``silver/weather/source=<s>/_staging/commodity=<c>/``
# -- and the compaction job reads staging UNION canonical, merges within-year,
# and publishes the coarse ``commodity=<c>/year=<y>`` object canonically (through
# the F015 shadow publisher). Staging is a sibling of ``commodity=`` under the
# ``source=`` root, so neither the extractor nor gold ever lists it.
_WEATHER_STAGING_MARKER = "_staging"


def weather_staging_prefix(source: str, commodity: str | None = None) -> str:
    """LIST prefix for the weather silver STAGING tier (b2s -> compact handoff).

    ``silver/weather/source=<source>/_staging/`` (whole source) or
    ``.../_staging/commodity=<commodity>/`` (one commodity). Lives OUTSIDE the
    canonical ``commodity=`` data plane, so the feature extractor and gold reader
    never see it."""
    base = f"silver/weather/source={source}/{_WEATHER_STAGING_MARKER}/"
    return base if commodity is None else f"{base}commodity={commodity}/"


def silver_weather_staging_key(
    source: str,
    commodity: str,
    country: str,
    region: str,
    year: int,
    month: int,
    filename: str,
) -> str:
    """One MONTH-grain staging object key (mirror of :func:`silver_weather_key` with the
    ``_staging`` marker inserted after ``source=`` so it sits outside ``commodity=``)."""
    return (
        f"silver/weather/"
        f"source={source}/"
        f"{_WEATHER_STAGING_MARKER}/"
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


def bronze_unica_biweekly_key(harvest_year: str, idm: str, table_name: str) -> str:
    """S3 key for a UNICA bi-weekly bulletin bronze Parquet file.

    One Parquet per (idm, table_name) pair; the table_name partition separates
    the five output tables emitted by the bronze transform.

    Args:
        harvest_year: Harvest year in slash or underscore format,
                      e.g. ``"2024/2025"`` or ``"2024_2025"``.
        idm:          The UNICADATA media download ID, e.g. ``"12439002"`` or
                      ``"pdf_1775f0afde26b483"``.
        table_name:   One of ``"fortnight_production"``, ``"summary_snapshot"``,
                      ``"corn_ethanol"``, ``"monthly_ethanol_sales"``,
                      ``"season_final_extras"``.
    """
    hy = harvest_year.replace("/", "_")
    return (
        f"bronze/production/"
        f"source=unica_biweekly/"
        f"table={table_name}/"
        f"harvest_year={hy}/"
        f"idm={idm}/"
        f"part-000.parquet"
    )


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
    (matching the CDN source).  Used for both the modern FAS portal
    (2002-08 → present) and the Archive.org historical PDFs (pre-2002).

    Args:
        release_month: ``YYYY-MM``, e.g. ``"2026-05"``.
    """
    return (
        f"raw/production/"
        f"source=usda_wap/"
        f"release_month={release_month}/"
        f"production.pdf"
    )


def raw_wap_html_key(release_month: str) -> str:
    """S3 key for a pre-2002 USDA FAS WAP circular in original HTML format.

    The 1996–2001 WAP circulars were published as HTML on fas.usda.gov and
    are only available via the Wayback Machine.  They are stored under a
    separate source prefix because bronze extraction uses BeautifulSoup
    table parsing rather than pdfplumber.

    Args:
        release_month: ``YYYY-MM``, e.g. ``"1999-03"``.
    """
    return (
        f"raw/production/"
        f"source=usda_wap_html/"
        f"release_month={release_month}/"
        f"wap.html"
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


def text_wasde_key(release_date: str) -> str:
    """S3 key for the extracted text document for a single USDA WASDE release.

    One file per release regardless of format era (digital PDF, TXT, or scanned).
    Written by the text extraction pipeline; idempotency check uses head_object
    on this key before any extraction is attempted.

    Args:
        release_date: YYYY-MM-DD, e.g. "2026-05-12".
    """
    return (
        f"text/"
        f"source=usda_wasde/"
        f"release_date={release_date}/"
        f"document.json"
    )


def text_wap_key(release_month: str) -> str:
    """S3 key for the extracted text document for a single USDA WAP release.

    One file per calendar month, regardless of source era (A: FAS portal PDF,
    B: Archive.org PDF, C: Wayback HTML).  Written by the WAP text extraction
    pipeline; idempotency check uses head_object on this key.

    Args:
        release_month: YYYY-MM, e.g. "2026-05".
    """
    return (
        f"text/"
        f"source=usda_wap/"
        f"release_month={release_month}/"
        f"document.json"
    )


def text_gain_key(
    source_name: str,
    country_iso2: str,
    publication_date: str,
    document_slug: str,
) -> str:
    """S3 key for the extracted text document for a single USDA FAS GAIN report.

    One file per raw PDF, keyed by (source, country, publication_date,
    document_slug).  The ``document_slug`` is the lowercased stem of the raw
    PDF filename (e.g. ``"sugar_annual_sao_paulo_ato_brazil_04-15-2020"``),
    which disambiguates the multiple reports that can share the same
    country/date partition.

    Args:
        source_name:      Source identifier, e.g. ``"usda_gain_wheat"``.
        country_iso2:     ISO 3166-1 alpha-2 country code, e.g. ``"US"``.
        publication_date: Publication date in ``YYYYMMDD`` format, e.g.
                          ``"20060419"`` — kept as-is from the raw key partition.
        document_slug:    Lowercased PDF filename stem, used as the
                          ``document=`` Hive partition value.
    """
    return (
        f"text/"
        f"source={source_name}/"
        f"country={country_iso2}/"
        f"publication_date={publication_date}/"
        f"document={document_slug}/"
        f"document.json"
    )


def text_mpob_overview_key(year: int) -> str:
    """S3 key for the extracted text document for an MPOB Overview of Industry PDF.

    One file per calendar year, covering 2010–2016 (pre-BEPI-HTML era).
    Written by the MPOB overview text extraction pipeline.

    Args:
        year: Calendar year, e.g. ``2015``.
    """
    return (
        f"text/"
        f"source=mpob/"
        f"release_type=overview_pdf/"
        f"year={year}/"
        f"document.json"
    )


def bronze_wap_key(release_month: str) -> str:
    """S3 key for the bronze Parquet table for a single USDA WAP release.

    Contains Table 01 (World Agricultural Production) in long/tidy format —
    one row per (release_month, commodity, row_label, country).  Written by
    the WAP bronze extraction pipeline.

    Args:
        release_month: YYYY-MM, e.g. "2026-05".
    """
    return (
        f"bronze/production/"
        f"source=usda_wap/"
        f"release_month={release_month}/"
        f"table01.parquet"
    )


# ---------------------------------------------------------------------------
# USDA FGIS Export Inspections — per-shipment grain inspection records
# ---------------------------------------------------------------------------

def raw_fgis_backfill_key(year: int) -> str:
    """S3 key for a USDA FGIS Export Inspections historical annual CSV.

    Prior-year files (1983–previous year) are static and never revised once
    a calendar year closes.  One file per calendar year.  Downloaded from:
        https://fgisonline.ams.usda.gov/ExportGrainReport/CY{year}.csv

    Args:
        year: Calendar year, e.g. ``2024``.
    """
    return (
        f"raw/production/"
        f"source=usda_fgis_export_inspections/"
        f"backfill/"
        f"CY{year}.csv"
    )


def raw_fgis_weekly_key(year: int, as_of_date: str) -> str:
    """S3 key for a weekly point-in-time snapshot of the current-year FGIS CSV.

    FGIS updates ``CY{year}.csv`` in-place every week.  Storing an immutable
    snapshot partitioned by ``as_of_date`` preserves what was knowable on each
    publication date, preventing lookahead bias in backtested ML features.

    Args:
        year: Calendar year of the current FGIS file, e.g. ``2026``.
        as_of_date: Snapshot date in ``YYYYMMDD`` format, e.g. ``"20260522"``.
    """
    return (
        f"raw/production/"
        f"source=usda_fgis_export_inspections/"
        f"year={year}/"
        f"as_of={as_of_date}/"
        f"CY{year}.csv"
    )


def bronze_fgis_key(year: int) -> str:
    """S3 key for a USDA FGIS Export Inspections bronze Parquet (one calendar year).

    Args:
        year: Calendar year, e.g. ``2024``.
    """
    return (
        f"bronze/production/"
        f"source=usda_fgis_export_inspections/"
        f"year={year}/"
        f"part-000.parquet"
    )


def silver_fgis_key(
    leviathan_slug: str,
    marketing_year: int,
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for a USDA FGIS Export Inspections silver Parquet partition.

    One file per (leviathan_slug, marketing_year).  Lives under
    ``silver/fgis/`` rather than ``silver/production/`` to avoid schema
    collision with the long-form silver_production Athena table.

    Args:
        leviathan_slug: Commodity slug, e.g. ``"corn_cbot"``.
        marketing_year: Marketing year start, e.g. ``2024``.
        filename:       Parquet filename (default ``"part-000.parquet"``).
    """
    return (
        f"silver/fgis/"
        f"leviathan_slug={leviathan_slug}/"
        f"marketing_year={marketing_year}/"
        f"{filename}"
    )


# ---------------------------------------------------------------------------
# USDA FAS Export Sales Reporting (ESR) — weekly forward export commitments
# ---------------------------------------------------------------------------

def raw_esr_backfill_key(commodity_code: int, market_year: int) -> str:
    """S3 key for a historical ESR JSON file (all countries, one marketing year).

    Historical marketing years are fetched once via the FAS API and stored as
    static JSON arrays.  One file per (commodity_code, market_year) pair.
    Fetched from:
        https://api.fas.usda.gov/api/esr/exports/commodityCode/{code}/allCountries/marketYear/{year}

    Args:
        commodity_code: ESR commodity code, e.g. ``401`` for corn.
        market_year:    Marketing year start, e.g. ``2024`` for the 2024/25 season.
    """
    return (
        f"raw/production/"
        f"source=usda_esr/"
        f"commodity_code={commodity_code}/"
        f"market_year={market_year}/"
        f"all_countries.json"
    )


def raw_esr_weekly_key(commodity_code: int, market_year: int, as_of_date: str) -> str:
    """S3 key for a weekly point-in-time ESR snapshot.

    ESR is updated every Thursday.  Storing an immutable snapshot partitioned
    by ``as_of_date`` preserves what was knowable on each publication date,
    preventing lookahead bias in backtested ML features.

    Both current and new-crop marketing years are snapshotted each Thursday
    (ESR publishes new-crop forward sales before the season starts).

    Args:
        commodity_code: ESR commodity code, e.g. ``401`` for corn.
        market_year:    Marketing year start, e.g. ``2025`` for the 2025/26 season.
        as_of_date:     Snapshot date in ``YYYYMMDD`` format, e.g. ``"20260522"``.
    """
    return (
        f"raw/production/"
        f"source=usda_esr/"
        f"commodity_code={commodity_code}/"
        f"market_year={market_year}/"
        f"as_of={as_of_date}/"
        f"all_countries.json"
    )


def bronze_esr_key(commodity_code: int, market_year: int, as_of_date: str) -> str:
    """S3 key for a bronze ESR Parquet file.

    ``as_of_date`` is always present so the partition schema is consistent
    across both backfill and weekly runs:
    - Backfill: ``as_of_date`` is the date the backfill Glue job ran.
    - Weekly:   ``as_of_date`` is the Thursday publication date.

    Athena queries use ``WHERE as_of_date = MAX(as_of_date)`` for the current
    view, or a specific date for point-in-time backtesting.

    Args:
        commodity_code: ESR commodity code, e.g. ``401`` for corn.
        market_year:    Marketing year start, e.g. ``2024``.
        as_of_date:     Snapshot date in ``YYYYMMDD`` format.
    """
    return (
        f"bronze/production/"
        f"source=usda_esr/"
        f"commodity_code={commodity_code}/"
        f"market_year={market_year}/"
        f"as_of={as_of_date}/"
        f"part-000.parquet"
    )


def silver_esr_key(commodity_code: int, market_year: int, as_of_date: str) -> str:
    """S3 key for a silver ESR Parquet file.

    Mirrors ``bronze_esr_key`` but lives under ``silver/``.  Each bronze
    Parquet produces exactly one silver Parquet at the same partition
    coordinates (commodity_code, market_year, as_of_date).

    Args:
        commodity_code: ESR commodity code, e.g. ``401`` for corn.
        market_year:    Marketing year start, e.g. ``2024``.
        as_of_date:     Snapshot date in ``YYYYMMDD`` format.
    """
    return (
        f"silver/production/"
        f"source=usda_esr/"
        f"commodity_code={commodity_code}/"
        f"market_year={market_year}/"
        f"as_of={as_of_date}/"
        f"part-000.parquet"
    )


# ---------------------------------------------------------------------------
# CFTC Commitments of Traders (COT) — Disaggregated
# ---------------------------------------------------------------------------

def raw_cot_backfill_key(report_type: str, year_label: str) -> str:
    """S3 key for a CFTC COT historical file (bulk or annual).

    Two report types are stored under separate prefixes:
      - ``disagg_futures``  — Disaggregated Futures Only
      - ``disagg_combined`` — Disaggregated Futures-and-Options Combined

    Year label is either ``"2006_2016"`` (the CFTC-supplied bulk covering
    the full disaggregated history through 2016) or a single year string
    such as ``"2017"`` for the per-year files from 2017 onwards.

    Args:
        report_type: ``"disagg_futures"`` or ``"disagg_combined"``.
        year_label:  ``"2006_2016"`` for the bulk file, or ``"YYYY"`` for
                     an individual year, e.g. ``"2024"``.
    """
    prefix = "fut_disagg" if report_type == "disagg_futures" else "com_disagg"
    return (
        f"raw/production/"
        f"source=cftc_cot/"
        f"{report_type}/"
        f"backfill/"
        f"{prefix}_{year_label}.txt"
    )


def raw_cot_weekly_key(report_type: str, year: int, as_of_date: str) -> str:
    """S3 key for a weekly point-in-time COT snapshot.

    CFTC publishes updated files every Friday.  Storing an immutable snapshot
    partitioned by ``as_of_date`` (the Friday publication date) preserves
    exact point-in-time correctness for backtested ML features and allows
    detection of retrospective CFTC corrections.

    Args:
        report_type: ``"disagg_futures"`` or ``"disagg_combined"``.
        year:        Calendar year of the as_of date, e.g. ``2026``.
        as_of_date:  Friday publication date in ``YYYYMMDD`` format,
                     e.g. ``"20260523"``.
    """
    prefix = "fut_disagg" if report_type == "disagg_futures" else "com_disagg"
    return (
        f"raw/production/"
        f"source=cftc_cot/"
        f"{report_type}/"
        f"year={year}/"
        f"as_of={as_of_date}/"
        f"{prefix}_{as_of_date}.txt"
    )


def bronze_cot_key(year_label: str) -> str:
    """S3 key for a CFTC COT Disaggregated Futures bronze Parquet.

    One file per year label — the 2006-2016 bulk file gets ``"2006_2016"``;
    each subsequent annual file gets its year, e.g. ``"2017"``.

    Args:
        year_label: ``"2006_2016"`` or ``"YYYY"`` (e.g. ``"2024"``).
    """
    return (
        f"bronze/production/"
        f"source=cftc_cot/"
        f"year={year_label}/"
        f"part-000.parquet"
    )


def silver_cot_key() -> str:
    """S3 key for the CFTC COT silver Parquet.

    Single flat file — one row per (report_date, leviathan_slug), weekly,
    2006-present, covering the 14 Leviathan contracts that have CFTC
    disaggregated futures data.
    """
    return "silver/cot/part-000.parquet"


# ---------------------------------------------------------------------------
# World Bank Pink Sheet
# ---------------------------------------------------------------------------

def raw_pink_sheet_key(release_ym: str, filename: str) -> str:
    """S3 key for a World Bank Commodity Markets (Pink Sheet) monthly XLS release.

    The full monthly price history back to 1960 is included in every release,
    so one download per calendar month is the complete backfill strategy.  Each
    monthly snapshot is stored as an immutable versioned object; downstream
    bronze jobs can diff sequential releases to detect retroactive WB revisions.

    Args:
        release_ym: Release year-month in ``YYYYMmm`` format, e.g. ``"2026M05"``.
        filename:   Original XLS filename from the WB download URL, e.g.
                    ``"CMO-Pink-Sheet-May-2026.xlsx"``.
    """
    return (
        f"raw/production/"
        f"source=world_bank_pink_sheet/"
        f"release={release_ym}/"
        f"{filename}"
    )


# ---------------------------------------------------------------------------
# World Bank Commodity Markets Outlook (CMO Outlook)
# ---------------------------------------------------------------------------

def raw_cmo_outlook_key(release_ym: str, filename: str) -> str:
    """S3 key for a World Bank Commodity Markets Outlook PDF.

    Published semi-annually (April + October) since 2018; monthly/quarterly
    in earlier eras back to 1994.  The ``release_ym`` partition normalises
    all frequencies to ``YYYY-MM`` (e.g. H1 → ``2022-04``, H2 → ``2022-10``,
    Q1 → ``2013-01``, monthly → actual month).

    Args:
        release_ym: Publication year-month in ``YYYY-MM`` format,
                    e.g. ``"2022-04"``.
        filename:   Normalised PDF filename, e.g.
                    ``"CMO-Outlook-2022-April.pdf"``.
    """
    return (
        f"raw/production/"
        f"source=wb_cmo_outlook/"
        f"release={release_ym}/"
        f"{filename}"
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


def bronze_sagis_weekly_key(dataset: str, crop: str, season: str) -> str:
    """S3 key for a SAGIS Weekly Data bronze Parquet.

    One file per (dataset, crop, season).

    Args:
        dataset: ``"producer_deliveries"`` or ``"imp_exp_progressive"``.
        crop:    E.g. ``"maize"``, ``"wheat"``, ``"soybeans"``, ``"sunflower"``.
        season:  Marketing year in ``YYYY-YY`` format, e.g. ``"2024-25"``.
    """
    return (
        f"bronze/production/"
        f"source=sagis_weekly/"
        f"dataset={dataset}/"
        f"crop={crop}/"
        f"season={season}/"
        f"part-000.parquet"
    )


def silver_sagis_weekly_key(metric_name: str) -> str:
    """S3 key for a SAGIS Weekly silver Parquet.

    Args:
        metric_name: ``"deliveries"`` or ``"exports"``.
    """
    return f"silver/sagis_weekly_{metric_name}/part-000.parquet"


def bronze_psd_key(release_date: str) -> str:
    """S3 key for a USDA PSD bronze Parquet (all commodities, one release date).

    Args:
        release_date: Download date in ``YYYY-MM-DD`` format, e.g. ``"2026-05-20"``.
    """
    return (
        f"bronze/production/"
        f"source=usda_psd/"
        f"release_date={release_date}/"
        f"part-000.parquet"
    )


def bronze_wasde_key(release_date: str) -> str:
    """S3 key for a USDA WASDE bronze Parquet (all S/D tables, one release date).

    Args:
        release_date: Release date in ``YYYY-MM-DD`` format, e.g. ``"2010-01-12"``.
    """
    return (
        f"bronze/production/"
        f"source=usda_wasde/"
        f"release_date={release_date}/"
        f"part-000.parquet"
    )


def silver_psd_key() -> str:
    """S3 key for the USDA PSD silver Parquet (all commodities, all releases).

    The single consolidated Parquet accumulates every monthly release date and
    all in-scope Leviathan contract slugs.  Fan-out means each PSD commodity
    appears once per contract slug, so ``leviathan_slug`` is a universal join
    key consistent with ESR, FGIS, and other silver tables.
    """
    return "silver/psd/part-000.parquet"


def bronze_pink_sheet_key(release_ym: str) -> str:
    """S3 key for a World Bank Pink Sheet bronze Parquet (one monthly release).

    Args:
        release_ym: Release year-month in ``YYYYMmm`` format, e.g. ``"2026M05"``.
    """
    return (
        f"bronze/production/"
        f"source=world_bank_pink_sheet/"
        f"release={release_ym}/"
        f"part-000.parquet"
    )


def bronze_nass_key(series: str, commodity: str, year: int) -> str:
    """S3 key for a USDA NASS bronze Parquet (one series/commodity/year shard).

    Args:
        series:    ``"annual"`` or ``"crop_progress"``.
        commodity: Leviathan commodity slug, e.g. ``"corn_cbot"``.
        year:      Calendar year of the data, e.g. ``2024``.
    """
    return (
        f"bronze/production/"
        f"source=usda_nass/"
        f"series={series}/"
        f"commodity={commodity}/"
        f"year={year}/"
        f"part-000.parquet"
    )


def silver_nass_annual_key(
    commodity: str,
    year: int,
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for a USDA NASS annual silver Parquet partition.

    This intentionally lives outside ``silver/production/`` because the
    existing ``silver_production`` Athena table projects that prefix with a
    long FAOSTAT-shaped schema.
    """
    return (
        f"silver/nass_annual/"
        f"commodity={commodity}/"
        f"year={year}/"
        f"{filename}"
    )


def silver_nass_crop_progress_key(
    commodity: str,
    year: int,
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for a USDA NASS crop-progress silver Parquet partition.

    This intentionally lives outside ``silver/production/`` and
    ``silver/nass_annual/`` because it has a weekly, wide feature schema.
    """
    return (
        f"silver/nass_crop_progress/"
        f"commodity={commodity}/"
        f"year={year}/"
        f"{filename}"
    )


def bronze_conab_xls_key(safra_year: int, survey: int) -> str:
    """S3 key for a CONAB bulletin XLS bronze Parquet (one survey per safra year).

    Args:
        safra_year: Marketing year the survey covers, e.g. ``2026``.
        survey:     Survey number within the season (1–5).
    """
    return (
        f"bronze/production/"
        f"source=conab_xls/"
        f"safra_year={safra_year}/"
        f"survey={survey:02d}/"
        f"part-000.parquet"
    )


def silver_conab_coffee_key(
    safra_year: int,
    commodity: str,
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for CONAB Brazil coffee production survey silver features."""
    return (
        f"silver/conab_coffee/"
        f"commodity={commodity}/"
        f"safra_year={safra_year}/"
        f"{filename}"
    )


def bronze_fnc_key(series: str) -> str:
    """S3 key for a FNC Colombia Excel bronze Parquet (one named series).

    Each series corresponds to one sheet extracted from one of the two FNC
    bulk Excel files.

    Args:
        series: Series identifier, e.g. ``"produccion_mensual"``.
    """
    return (
        f"bronze/production/"
        f"source=fnc_excel/"
        f"series={series}/"
        f"part-000.parquet"
    )


def silver_fnc_colombia_monthly_key(
    year: int,
    commodity: str = "arabica_coffee",
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for FNC Colombia monthly coffee silver features."""
    return (
        f"silver/fnc_colombia/monthly/"
        f"commodity={commodity}/"
        f"year={year}/"
        f"{filename}"
    )


def silver_fnc_colombia_area_department_key(
    year: int,
    commodity: str = "arabica_coffee",
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for FNC Colombia annual department area silver features."""
    return (
        f"silver/fnc_colombia/area_department/"
        f"commodity={commodity}/"
        f"year={year}/"
        f"{filename}"
    )


def silver_fnc_colombia_exports_port_type_key(
    year: int,
    commodity: str = "arabica_coffee",
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for FNC Colombia export port/type silver features."""
    return (
        f"silver/fnc_colombia/exports_port_type/"
        f"commodity={commodity}/"
        f"year={year}/"
        f"{filename}"
    )


def bronze_mpob_annual_key(year: int) -> str:
    """S3 key for an MPOB BEPI annual summary bronze Parquet.

    Contains 12 rows (one per month) of national CPO production, stocks,
    exports, imports, and FFB price extracted from the annual summary HTML.

    Args:
        year: Calendar year, e.g. ``2026``.
    """
    return (
        f"bronze/production/"
        f"source=mpob/"
        f"release_type=annual_summary/"
        f"year={year}/"
        f"part-000.parquet"
    )


def bronze_mpob_overview_key(year: int) -> str:
    """S3 key for an MPOB Overview-PDF annual bronze Parquet.

    Contains annual national totals (CPO production, closing stocks,
    exports, imports, FFB price) extracted from the overview PDF stats pages.
    Covers 2010–2016, complementing the annual_summary HTML series (2017+).

    Args:
        year: Calendar year, e.g. ``2015``.
    """
    return (
        f"bronze/production/"
        f"source=mpob/"
        f"release_type=overview_pdf/"
        f"year={year}/"
        f"part-000.parquet"
    )


def bronze_mpob_monthly_key(year: int, month: int) -> str:
    """S3 key for an MPOB BEPI monthly release bronze Parquet.

    Contains national + regional CPO data for one specific calendar month.

    Args:
        year:  Calendar year, e.g. ``2026``.
        month: Calendar month (1–12).
    """
    return (
        f"bronze/production/"
        f"source=mpob/"
        f"release_type=monthly_release/"
        f"year={year}/"
        f"month={month:02d}/"
        f"part-000.parquet"
    )


def silver_mpob_key() -> str:
    """S3 key for the MPOB silver Parquet.

    Single flat file containing all years of monthly CPO supply/demand
    metrics, derived from the annual_summary bronze.

    Returns:
        ``"silver/mpob/part-000.parquet"``
    """
    return "silver/mpob/part-000.parquet"


def silver_mpob_annual_key() -> str:
    """S3 key for the MPOB overview-PDF annual silver Parquet.

    Single flat file containing annual CPO supply/demand metrics derived
    from the overview_pdf bronze (2010–2016, pre-BEPI-HTML era).

    Returns:
        ``"silver/mpob_annual/part-000.parquet"``
    """
    return "silver/mpob_annual/part-000.parquet"


def silver_unica_annual_state_key() -> str:
    """S3 key for the UNICA annual-by-state silver Parquet.

    Single flat file containing annual production totals per Brazilian state
    and regional aggregate for Brazil Centre-South sugarcane (1980/1981–2020/2021).

    Returns:
        ``"silver/unica_annual_state/part-000.parquet"``
    """
    return "silver/unica_annual_state/part-000.parquet"


def silver_unica_biweekly_season_history_key() -> str:
    """S3 key for the UNICA biweekly season history silver Parquet.

    One row per (harvest_year, fortnight_seq, region).  Deduplicated across all
    bulletins — each fortnight slot keeps the value from the latest bulletin that
    reported it.

    Returns:
        ``"silver/unica_biweekly_season_history/part-000.parquet"``
    """
    return "silver/unica_biweekly_season_history/part-000.parquet"


def silver_unica_biweekly_release_series_key() -> str:
    """S3 key for the UNICA biweekly release series silver Parquet.

    One row per (harvest_year, position_date, region) — the vintage/surprise
    series of accumulated totals as reported on each bulletin release date.

    Returns:
        ``"silver/unica_biweekly_release_series/part-000.parquet"``
    """
    return "silver/unica_biweekly_release_series/part-000.parquet"


def silver_unica_corn_ethanol_key() -> str:
    """S3 key for the UNICA corn-derived ethanol silver Parquet.

    One row per (harvest_year, fortnight_seq).  Deduplicated across bulletins.

    Returns:
        ``"silver/unica_corn_ethanol/part-000.parquet"``
    """
    return "silver/unica_corn_ethanol/part-000.parquet"


def silver_unica_monthly_ethanol_sales_key() -> str:
    """S3 key for the UNICA monthly ethanol sales silver Parquet.

    One row per (harvest_year, month_num).  Prefers final (non-partial) monthly
    totals; falls back to latest partial reading.

    Returns:
        ``"silver/unica_monthly_ethanol_sales/part-000.parquet"``
    """
    return "silver/unica_monthly_ethanol_sales/part-000.parquet"


def silver_unica_supply_demand_key() -> str:
    """S3 key for the UNICA supply/demand balance silver Parquet.

    Derived from season_final_extras bronze (supply_demand_ethanol and
    supply_demand_sugar sub-tables).  One row per (harvest_year, commodity).

    Returns:
        ``"silver/unica_supply_demand/part-000.parquet"``
    """
    return "silver/unica_supply_demand/part-000.parquet"


def silver_wap_table01_key() -> str:
    """S3 key for the WAP Table 01 long-format silver Parquet.

    One row per (release_month, commodity, marketing_year, vintage_type,
    vintage_status, month_abbr, country).

    Returns:
        ``"silver/wap_table01/part-000.parquet"``
    """
    return "silver/wap_table01/part-000.parquet"


def silver_wap_table01_revisions_key() -> str:
    """S3 key for the WAP Table 01 revision series silver Parquet.

    One row per (release_month, commodity, marketing_year, vintage_type,
    vintage_status, month_abbr, country) with prior_release_month and
    revision_mmt columns added.

    Returns:
        ``"silver/wap_table01_revisions/part-000.parquet"``
    """
    return "silver/wap_table01_revisions/part-000.parquet"


def silver_pink_sheet_key() -> str:
    """S3 key for the World Bank Pink Sheet silver Parquet.

    One row per calendar month (1960-01 onward).  Includes wide-format
    fertilizer/energy price columns, ``blended_npk_index``, rolling 5-year
    z-scores for each series, and ``latest_release_ym`` provenance.

    Returns:
        ``"silver/pink_sheet/part-000.parquet"``
    """
    return "silver/pink_sheet/part-000.parquet"


def bronze_unica_key(harvest_year: str) -> str:
    """S3 key for a UNICA Center-South production bronze Parquet (one harvest year).

    Contains fortnightly cumulative cane crushed, sugar and ethanol produced.

    Args:
        harvest_year: Harvest year in slash or underscore format,
                      e.g. ``"2024/25"`` or ``"2024_25"``.
    """
    hy = harvest_year.replace("/", "_")
    return (
        f"bronze/production/"
        f"source=unica/"
        f"harvest_year={hy}/"
        f"part-000.parquet"
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


def bronze_sagis_cec_key(production_year: int, report_month: int, filename_stem: str) -> str:
    """S3 key for a SAGIS CEC bronze Parquet.

    One file per (production_year, report_month, filename_stem).
    The filename_stem preserves any ``a``/``b``/``summer``/``winter`` suffix
    so that multiple releases in the same month are stored separately; silver
    deduplicates by keeping the latest release_date.

    Args:
        production_year: Season year in the filename, e.g. ``2025``.
        report_month:    Calendar month of the estimate (1–12).
        filename_stem:   Filename without extension, e.g. ``"CEC-2025-09"``.
    """
    return (
        f"bronze/production/"
        f"source=sagis_cec/"
        f"production_year={production_year}/"
        f"report_month={report_month:02d}/"
        f"{filename_stem}.parquet"
    )


def silver_sagis_cec_key() -> str:
    """S3 key for the SAGIS CEC silver Parquet.

    Single flat file — one row per (production_year, report_month, crop, scope),
    deduplicated to the latest release per slot.
    """
    return "silver/sagis_cec/part-000.parquet"


# ---------------------------------------------------------------------------
# NOAA ONI (Ocean Niño Index) — ENSO 3-month SST anomaly series
# ---------------------------------------------------------------------------

def raw_oni_key() -> str:
    """S3 key for the NOAA CPC Ocean Niño Index (ONI) text file.

    Single overwrite object — NOAA updates the file in-place each month,
    appending the latest 3-month season row.  No versioned snapshot is needed
    because the full history from 1950 is included in every release and
    historical revisions are rare (only when the 30-year baseline shifts).
    """
    return "raw/weather/source=noaa_oni/oni.ascii.txt"


def bronze_oni_key() -> str:
    """S3 key for the NOAA ONI bronze Parquet.

    Single flat file — one row per 3-month overlapping season (12 rows/year),
    1950-present.  Overwritten on each ingest run.
    """
    return "bronze/weather/source=noaa_oni/part-000.parquet"


def raw_fred_fx_key(series_id: str) -> str:
    """S3 key for a FRED FX rate raw CSV file.

    Overwritten on each fetch — FRED returns the full history on every request.

    Args:
        series_id: FRED series identifier, e.g. ``"DEXBZUS"``.
    """
    return f"raw/fx/source=fred/{series_id}.csv"


def bronze_fred_fx_key(series_id: str) -> str:
    """S3 key for a FRED FX rate bronze Parquet (one file per series).

    Args:
        series_id: FRED series identifier, e.g. ``"DEXBZUS"``.
    """
    return f"bronze/fx/source=fred/{series_id}/part-000.parquet"


def silver_fred_fx_key() -> str:
    """S3 key for the FRED FX silver Parquet.

    Wide daily table — one row per calendar day with rate and
    pct_change_90d columns for each ingested series.
    """
    return "silver/fred_fx/part-000.parquet"


def silver_oni_key() -> str:
    """S3 key for the NOAA ONI silver Parquet.

    Single flat file — one row per (year, month), 1950-present.  Extends
    the bronze with lagged ONI columns and binary phase flags ready for
    direct consumption by the feature engineering layer.
    """
    return "silver/weather/source=noaa_oni/part-000.parquet"


def raw_iod_key() -> str:
    """S3 key for the NOAA PSL Indian Ocean Dipole (IOD) DMI text file.

    Single overwrite object — NOAA updates the file in-place each month.
    Full history from 1870 included in every release.
    """
    return "raw/weather/source=noaa_iod/dmi.had.long.data"


def bronze_iod_key() -> str:
    """S3 key for the NOAA IOD bronze Parquet.

    Single flat file — one row per (year, month), 1870-present.
    Overwritten on each ingest run.
    """
    return "bronze/weather/source=noaa_iod/part-000.parquet"


def silver_iod_key() -> str:
    """S3 key for the NOAA IOD silver Parquet.

    One row per (year, month), 1870-present.  Extends bronze with
    iod_dmi_3month_avg (universal feature), iod_phase classification,
    and iod_dmi_ethiopia_lag4 (arabica coffee commodity-specific feature).
    """
    return "silver/weather/source=noaa_iod/part-000.parquet"


def raw_food_cpi_key(country_iso: str) -> str:
    """S3 key for a World Bank DataBank food CPI raw JSON file.

    One file per country.  Overwritten on each fetch — the API returns
    the full history on every request.

    Args:
        country_iso: ISO 3166-1 alpha-3 country code, e.g. ``"IND"``.
    """
    return f"raw/production/source=wb_food_cpi/country={country_iso}/part-000.json"


def bronze_food_cpi_key(country_iso: str) -> str:
    """S3 key for a World Bank food CPI bronze Parquet (one file per country).

    Args:
        country_iso: ISO 3166-1 alpha-3 country code, e.g. ``"IND"``.
    """
    return f"bronze/production/source=wb_food_cpi/country={country_iso}/part-000.parquet"


def silver_food_cpi_key() -> str:
    """S3 key for the food CPI silver Parquet.

    Long format — one row per (country_iso, year).  All four countries
    (IND, RUS, IDN, UKR) combined with expanding-window z-scores.
    """
    return "silver/food_cpi/part-000.parquet"


def raw_yfinance_key(slug: str) -> str:
    """S3 key for a yfinance raw OHLCV Parquet (one file per slug).

    Overwritten on each fetch — yfinance returns the full history on every
    ``period='max'`` request.

    Args:
        slug: Leviathan slug, e.g. ``"corn_cbot"``.
    """
    return f"raw/production/source=yfinance/{slug}/part-000.parquet"


def bronze_yfinance_key(slug: str) -> str:
    """S3 key for a yfinance bronze Parquet (one file per slug).

    Adds ``is_roll_date`` and ``log_return`` columns to the raw OHLCV.

    Args:
        slug: Leviathan slug, e.g. ``"corn_cbot"``.
    """
    return f"bronze/production/source=yfinance/{slug}/part-000.parquet"


def silver_futures_prices_key() -> str:
    """S3 key for the combined yfinance futures prices silver Parquet.

    Long format — one row per (date, leviathan_slug).  All 12 US/ICE
    front-month continuous contracts combined with price features.
    """
    return "silver/futures_prices/part-000.parquet"


# ---------------------------------------------------------------------------
# Gold feature-spine versioning
# ---------------------------------------------------------------------------

def gold_feature_spine_version_key(
    dataset_version: str,
    commodity: str,
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for an immutable long-format feature spine partition.

    The mutable training surface remains ``gold/feature_spine``.  Versioned
    partitions live under a dataset_version prefix so MLflow experiments can
    pin the exact dataset they trained on.
    """
    return (
        f"gold/feature_spine_versions/"
        f"dataset_version={dataset_version}/"
        f"commodity={commodity}/"
        f"{filename}"
    )


def gold_feature_matrix_version_key(
    dataset_version: str,
    commodity: str,
    filename: str = "part-0.parquet",
) -> str:
    """S3 key for an immutable wide feature matrix partition."""
    return (
        f"gold/feature_matrix_versions/"
        f"dataset_version={dataset_version}/"
        f"commodity={commodity}/"
        f"{filename}"
    )


def gold_feature_catalog_version_key(
    dataset_version: str,
    filename: str = "feature_catalog.parquet",
) -> str:
    """S3 key for the feature catalog observed in a dataset version."""
    return (
        f"gold/feature_catalog_versions/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_feature_entity_map_version_key(
    dataset_version: str,
    filename: str = "feature_entity_map.parquet",
) -> str:
    """S3 key for feature-to-entity coverage in a dataset version."""
    return (
        f"gold/feature_entity_map_versions/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_feature_group_map_version_key(
    dataset_version: str,
    filename: str = "feature_group_map.parquet",
) -> str:
    """S3 key for feature-to-commodity-group coverage in a dataset version."""
    return (
        f"gold/feature_group_map_versions/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_feature_set_version_key(
    dataset_version: str,
    filename: str = "feature_sets.parquet",
) -> str:
    """S3 key for model-purpose feature-set membership in a dataset version."""
    return (
        f"gold/feature_set_versions/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_feature_set_summary_key(
    dataset_version: str,
    filename: str = "feature_sets.json",
) -> str:
    """S3 key for the JSON summary of model-purpose feature-set membership."""
    return (
        f"gold/feature_set_manifests/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_feature_spine_manifest_key(
    dataset_version: str,
    filename: str = "manifest.json",
) -> str:
    """S3 key for a dataset-level feature spine manifest."""
    return (
        f"gold/feature_spine_manifests/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_feature_spine_commodity_manifest_key(
    dataset_version: str,
    commodity: str,
    filename: str = "run.json",
) -> str:
    """S3 key for a per-commodity manifest inside a dataset version."""
    return (
        f"gold/feature_spine_commodity_manifests/"
        f"dataset_version={dataset_version}/"
        f"commodity={commodity}/"
        f"{filename}"
    )


def gold_training_windows_version_key(
    dataset_version: str,
    filename: str = "training_windows.parquet",
) -> str:
    """S3 key for the training-window manifest for an immutable dataset version."""
    return (
        f"gold/training_windows_versions/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_model_ready_target_key(
    dataset_version: str,
    dataset_key: str,
    commodity: str,
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for long model-ready target rows."""
    return (
        f"gold/model_ready_targets/"
        f"dataset_version={dataset_version}/"
        f"dataset_key={dataset_key}/"
        f"commodity={commodity}/"
        f"{filename}"
    )


def gold_model_ready_matrix_key(
    dataset_version: str,
    dataset_key: str,
    commodity: str,
    target_key: str,
    filename: str = "part-000.parquet",
) -> str:
    """S3 key for a model-ready wide matrix for one target."""
    return (
        f"gold/model_ready_matrices/"
        f"dataset_version={dataset_version}/"
        f"dataset_key={dataset_key}/"
        f"commodity={commodity}/"
        f"target={target_key}/"
        f"{filename}"
    )


def gold_model_ready_baseline_metrics_key(
    dataset_version: str,
    filename: str = "baseline_metrics.parquet",
) -> str:
    """S3 key for baseline metrics computed for model-ready targets."""
    return (
        f"gold/model_ready_baselines/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_model_ready_feature_set_version_key(
    dataset_version: str,
    filename: str = "feature_sets.parquet",
) -> str:
    """S3 key for model-ready-specific feature-set membership."""
    return (
        f"gold/model_ready_feature_sets/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_model_ready_feature_set_summary_key(
    dataset_version: str,
    filename: str = "feature_sets.json",
) -> str:
    """S3 key for the JSON summary of model-ready-specific feature sets."""
    return (
        f"gold/model_ready_feature_set_manifests/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def gold_model_ready_manifest_key(
    dataset_version: str,
    filename: str = "manifest.json",
) -> str:
    """S3 key for a model-ready dataset manifest."""
    return (
        f"gold/model_ready_manifests/"
        f"dataset_version={dataset_version}/"
        f"{filename}"
    )


def model_candidate_certification_key(
    candidate_id: str,
    filename: str = "certification_report.json",
) -> str:
    """S3 key for a model candidate certification report."""
    return (
        f"model_artifacts/candidate_certification/"
        f"candidate_id={candidate_id}/"
        f"{filename}"
    )


def model_candidate_certification_summary_key(
    run_id: str,
    filename: str = "candidate_ranking.parquet",
) -> str:
    """S3 key for a Phase 10 candidate-certification ranking table."""
    return (
        f"model_artifacts/candidate_certification_summaries/"
        f"run_id={run_id}/"
        f"{filename}"
    )


def snapshot_candidate_certification_key(
    candidate_id: str,
    filename: str = "certification_report.json",
) -> str:
    """S3 key for a grouped WASDE snapshot candidate smoke report."""
    return (
        f"model_artifacts/snapshot_candidate_certification/"
        f"candidate_id={candidate_id}/"
        f"{filename}"
    )


# ---------------------------------------------------------------------------
# CONAB text and silver keys
# ---------------------------------------------------------------------------

def text_mpoc_article_key(date: str, slug: str) -> str:
    """S3 key for the extracted text document for a single MPOC Market Highlights article.

    Both date and slug together form the unique key — two articles can share a
    publication date, but slug is always unique.

    Args:
        date: Publication date in ``YYYYMMDD`` format, e.g. ``"20260123"``.
        slug: URL slug of the article, e.g.
              ``"the-rise-of-aseans-foodservice-industry-an-engine-for-palm-oil-demand"``.
    """
    return (
        f"text/"
        f"source=mpoc/"
        f"release_type=market_highlights/"
        f"date={date}/"
        f"slug={slug}/"
        f"document.json"
    )


def bronze_mpoc_trade_stats_key(year: int, table_name: str) -> str:
    """S3 key for an MPOC Trade Statistics bronze Parquet (one table per year).

    Args:
        year:       Calendar year the page covers, e.g. ``2023``.
        table_name: One of ``"monthly_totals"``, ``"annual_by_product"``,
                    ``"annual_by_country"``.
    """
    return (
        f"bronze/production/"
        f"source=mpoc/"
        f"release_type=trade_statistics/"
        f"table={table_name}/"
        f"year={year}/"
        f"part-000.parquet"
    )


def bronze_mpoc_stock_comparison_key() -> str:
    """S3 key for the MPOC Stock Comparison bronze Parquet.

    Single file — 5 import-country × 6 oil-type × 12-month × 2-year grid.
    Overwritten on each run (source page is a live single-page snapshot).
    """
    return "bronze/production/source=mpoc/release_type=stock_comparison/part-000.parquet"


def silver_mpoc_key(table_name: str) -> str:
    """S3 key for an MPOC silver Parquet.

    Args:
        table_name: One of ``"trade_stats_monthly"``, ``"exports_by_country"``,
                    ``"stock_comparison"``.
    """
    return f"silver/mpoc_{table_name}/part-000.parquet"


def text_wmt_key(publication_date: str) -> str:
    """S3 key for the extracted text document for a single USDA FAS WMT circular.

    One file per publication date — mirrors the raw key Hive partition structure
    so the two layers join without re-parsing.  Written by the WMT text extraction
    pipeline; idempotency check uses head_object on this key.

    Args:
        publication_date: Publication date in ``YYYYMMDD`` format,
                          e.g. ``"20250625"``.
    """
    return (
        f"text/"
        f"source=usda_fas_coffee_wmt/"
        f"publication_date={publication_date}/"
        f"document.json"
    )


def text_conab_key(crop_year: str, survey_number: int) -> str:
    """S3 key for the extracted text document for a single CONAB bulletin PDF.

    One file per (crop_year, survey_number) pair — mirrors the raw key Hive
    partition structure so the two layers join without re-parsing.
    Written by the CONAB PDF text extraction pipeline; idempotency check
    uses head_object on this key.

    Args:
        crop_year:     Marketing year in underscore format, e.g. ``"2024_25"``.
        survey_number: Survey number within the season (1–5).
    """
    return (
        f"text/"
        f"source=conab/"
        f"crop_year={crop_year}/"
        f"survey={survey_number:02d}/"
        f"document.json"
    )


def silver_conab_key(commodity: str, safra_year: int, survey: int) -> str:
    """S3 key for a CONAB XLS silver Parquet partition.

    One file per (commodity, safra_year, survey); contains all Brazilian
    state rows plus the BRASIL aggregate row for that survey.

    Args:
        commodity:  Leviathan commodity slug, e.g. ``"arabica_coffee"``.
        safra_year: Marketing year the survey covers, e.g. ``2026``.
        survey:     Survey number within the season (1–5).
    """
    return (
        f"silver/production/"
        f"source=conab/"
        f"commodity={commodity}/"
        f"safra_year={safra_year}/"
        f"survey={survey:02d}/"
        f"part-000.parquet"
    )
