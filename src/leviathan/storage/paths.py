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