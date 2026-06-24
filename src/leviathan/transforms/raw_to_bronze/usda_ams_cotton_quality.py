"""USDA AMS Cotton Annual Quality PDF -> bronze rows."""
from __future__ import annotations

import io
import re

import pandas as pd

BRONZE_COLUMNS = [
    "season",
    "geography",
    "extraction_scope",
    "metric",
    "value",
    "unit",
    "source_page",
    "source_raw_key",
    "source_file_etag",
    "source",
]

_METRIC_PATTERNS = {
    "percent_tenderable": (
        re.compile(r"percent\s+tenderable[^0-9]{0,40}(\d+(?:\.\d+)?)", re.I),
        "pct",
    ),
    "samples_classed": (
        re.compile(r"samples\s+classed[^0-9]{0,40}([\d,]+)", re.I),
        "samples",
    ),
    "avg_staple": (
        re.compile(r"(?:average|avg\.?)\s+staple[^0-9]{0,40}(\d+(?:\.\d+)?)", re.I),
        "staple_code",
    ),
    "avg_micronaire": (
        re.compile(r"(?:average|avg\.?)\s+micronaire[^0-9]{0,40}(\d+(?:\.\d+)?)", re.I),
        "micronaire",
    ),
    "avg_strength": (
        re.compile(r"(?:average|avg\.?)\s+strength[^0-9]{0,40}(\d+(?:\.\d+)?)", re.I),
        "grams_per_tex",
    ),
}
_NATIONAL_SCOPES = {"national_summary", "national_narrative"}


def extract_metrics_from_text(
    text: str,
    *,
    season: int,
    source_page: int,
    source_raw_key: str | None = None,
    source_file_etag: str | None = None,
) -> list[dict]:
    """Extract conservative AMS quality metrics from a single page of text."""
    rows: list[dict] = []
    normalized = re.sub(r"\s+", " ", text)
    for metric, (pattern, unit) in _METRIC_PATTERNS.items():
        match = pattern.search(normalized)
        if not match:
            continue
        raw = match.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        rows.append({
            "season": int(season),
            "geography": "unknown",
            "extraction_scope": "raw_match",
            "metric": metric,
            "value": value,
            "unit": unit,
            "source_page": int(source_page),
            "source_raw_key": source_raw_key,
            "source_file_etag": source_file_etag,
            "source": "usda_ams_cotton_classing_annual",
        })
    return rows


def _assign_national_scope(rows: list[dict]) -> list[dict]:
    if not rows:
        return rows

    percent_pages = [
        int(row["source_page"])
        for row in rows
        if row["metric"] == "percent_tenderable"
    ]
    if not percent_pages:
        return rows

    summary_page = min(percent_pages)
    summary_metrics = {
        row["metric"]
        for row in rows
        if int(row["source_page"]) == summary_page
    }

    for row in rows:
        source_page = int(row["source_page"])
        metric = str(row["metric"])
        if source_page == summary_page:
            row["geography"] = "us_total"
            row["extraction_scope"] = "national_summary"
        elif (
            source_page < summary_page
            and metric.startswith("avg_")
            and metric not in summary_metrics
        ):
            row["geography"] = "us_total"
            row["extraction_scope"] = "national_narrative"
        else:
            row["geography"] = "unknown"
            row["extraction_scope"] = "regional_or_appendix"
    return rows


def extract_ams_cotton_quality_pdf(
    pdf_bytes: bytes,
    *,
    season: int,
    source_raw_key: str | None = None,
    source_file_etag: str | None = None,
) -> pd.DataFrame:
    """Parse one annual AMS Cotton Quality PDF into long bronze rows."""
    import pdfplumber

    rows: list[dict] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            rows.extend(
                extract_metrics_from_text(
                    text,
                    season=season,
                    source_page=page_number,
                    source_raw_key=source_raw_key,
                    source_file_etag=source_file_etag,
                )
            )
    return pd.DataFrame(_assign_national_scope(rows), columns=BRONZE_COLUMNS)
