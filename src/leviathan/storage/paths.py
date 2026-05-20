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
