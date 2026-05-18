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
) -> str:
    """S3 key for a CONAB Boletim da Safra de Café PDF.

    One PDF covers all coffee commodities; no commodity partition at raw layer.

    Args:
        crop_year: Marketing year in underscore format, e.g. ``"2024_25"``.
        survey_number: Survey number within the season (1–5).
    """
    filename = f"boletim_cafe_{crop_year}_{survey_number:02d}.pdf"
    return (
        f"raw/production/"
        f"source=conab/"
        f"crop_year={crop_year}/"
        f"survey={survey_number:02d}/"
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