"""Bronze transform for the NOAA PSL Indian Ocean Dipole (IOD) DMI text file.

Parses the fixed-width ``dmi.had.long.data`` file published by NOAA PSL at:
    https://psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data

File format
-----------
Year-range header on line 0, then one row per year with 12 monthly values,
followed by footer metadata lines and (in some vintages) a trailing
missing-value-code line:

    1870 2025
    1870    -0.438    -0.336     0.177    -0.048  ...
    1871    -0.273    -0.170    -0.212    -0.148  ...
    ...
    2025    -0.196     0.017     0.059     0.149  -9999.000  -9999.000  ...
    Created Mon Jun 16 09:50:15 MDT 2025
    using SST anomaly 10S:10N,50E-70E minus 10S:0,90E-110E area averaged
    Timeseries output created at NOAA PSL
    https://psl.noaa.gov/gcos_wgsp/timeseries/DMI

Missing value sentinel: ``-9999.0`` (future months in the current year).

SILVER-F041 -- the ``1870 2025`` header bug
-------------------------------------------
The historical regex ``^\\s*(\\d{4})\\s+`` matched the *header* line
``1870 2025`` as though it were a data row: it parsed ``year=1870`` and read
its single trailing token ``2025`` as ``month=1``'s value -- minting the
physically impossible ``dmi_value=2025`` and COLLIDING with the real
``(1870, 1) = -0.438`` observation. The comment claimed the header was
"skipped", but it was not.

The fix parses the header BOUNDS separately from observations and admits a
data row only when it structurally is one:

  * the year-range header (two bare 4-digit years) is consumed first and gives
    ``[start_year, end_year]``;
  * a data row must carry a leading 4-digit year AND exactly 12 monthly cells
    (13 whitespace tokens). The 2-token header can never satisfy this;
  * the leading year must fall within the header bounds;
  * each monthly cell is coerced to float; the missing sentinel (``<= -999``)
    becomes NaN; a value outside the documented scientifically-plausible DMI
    range is treated as invalid (NaN) -- a third backstop against a ``2025``
    ever reaching a ``dmi_value``;
  * ``(year, month)`` uniqueness is asserted before the frame is returned.

What is the DMI?
----------------
The Dipole Mode Index (DMI) is the SST-anomaly difference between the western
(50E-70E, 10S-10N) and eastern (90E-110E, 10S-equator) Indian Ocean. Positive
IOD (DMI > +0.4) -> drought in East Africa/India/SE Asia; negative (< -0.4) ->
the opposite. Phase thresholds follow JMA convention (+/-0.4 C). The observed
DMI is a small SST anomaly; historical monthly values lie well within +/-3 C.

Source
------
HadSST-derived DMI from the NOAA/GCOS Working Group. Monthly from January 1870,
updated monthly in-place.
"""
from __future__ import annotations

import re

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Missing value sentinel: values <= this are NaN (actual file sentinel is -9999.0).
_MISSING_SENTINEL = -999.0

# Documented scientifically-plausible DMI range (deg C SST anomaly). The observed
# monthly DMI is a small anomaly; +/-3 comfortably brackets every real value in
# the 1870-present record (the strong 1997 event peaked ~1.3). A parsed value
# outside this band that is NOT the missing sentinel is invalid data -> NaN.
_DMI_PLAUSIBLE_MIN = -3.0
_DMI_PLAUSIBLE_MAX = 3.0

_MONTHS_PER_YEAR = 12
# A data row is a leading 4-digit year followed by exactly 12 monthly cells.
_DATA_ROW_TOKENS = 1 + _MONTHS_PER_YEAR

# The year-range header is exactly two bare 4-digit years (e.g. "1870 2025").
_HEADER_RE = re.compile(r"^\s*(\d{4})\s+(\d{4})\s*$")
# A candidate data row starts with a 4-digit year.
_LEADING_YEAR_RE = re.compile(r"^\s*(\d{4})(?:\s|$)")

BRONZE_COLUMNS: list[str] = [
    "year",
    "month",
    "date",
    "dmi_value",
    "source",
]


def parse_header_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Return ``(start_year, end_year)`` from the first year-range header line, else ``None``.

    The header is the first line that is EXACTLY two bare 4-digit years. It is parsed
    independently of the observation rows so it can never be admitted as data.
    """
    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if start <= end:
                return start, end
    return None


def _coerce_cell(val_str: str) -> float | None:
    """Coerce one monthly cell to a plausible DMI float, else ``None`` (NaN).

    Missing sentinel and out-of-plausible-range values both map to ``None`` -- the
    latter is the structural backstop that keeps a stray ``2025`` out of ``dmi_value``.
    """
    try:
        val = float(val_str)
    except ValueError:
        return None
    if val <= _MISSING_SENTINEL:
        return None
    if not (_DMI_PLAUSIBLE_MIN <= val <= _DMI_PLAUSIBLE_MAX):
        return None
    return val


def extract_iod_bronze(raw_bytes: bytes) -> pd.DataFrame:
    """Parse the NOAA PSL DMI text file into a long-format bronze DataFrame.

    Args:
        raw_bytes: Raw bytes of the ``dmi.had.long.data`` file from S3.

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS`. One row per (year, month),
        1870-present. Future months in the current year have ``dmi_value = NaN``.
        ``(year, month)`` is unique (asserted).

    Raises:
        ValueError: If no parseable data rows are found, or if a duplicate
            ``(year, month)`` survives parsing (a header/observation collision).
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.strip().splitlines()

    bounds = parse_header_bounds(lines)
    if bounds is None:
        # No header found: fall back to permissive-but-sane bounds and rely on the
        # 12-cell + plausible-range rules. Warn -- a healthy NOAA file always has one.
        logger.warning("IOD bronze: no year-range header found; using permissive bounds")
        start_year, end_year = 1800, 2100
    else:
        start_year, end_year = bounds

    records: list[dict] = []
    skipped_nondata = 0
    rejected_bounds = 0
    invalid_cells = 0

    for line in lines:
        # The header line is never data (it is not a 13-token row anyway).
        if _HEADER_RE.match(line):
            continue
        ym = _LEADING_YEAR_RE.match(line)
        if not ym:
            skipped_nondata += 1
            continue

        parts = line.split()
        if len(parts) != _DATA_ROW_TOKENS:
            # Footer text, a bare missing-value-code line, or a truncated row.
            # A real data row is year + 12 monthly cells; the 2-token header and
            # any footer line fail this and are correctly excluded.
            skipped_nondata += 1
            continue

        year = int(parts[0])
        if not (start_year <= year <= end_year):
            rejected_bounds += 1
            continue

        for month_idx, val_str in enumerate(parts[1:], start=1):
            val = _coerce_cell(val_str)
            if val is None and val_str not in ("", None):
                # Distinguish a real sentinel (expected) from an out-of-range value.
                try:
                    raw = float(val_str)
                    if raw > _MISSING_SENTINEL and not (
                        _DMI_PLAUSIBLE_MIN <= raw <= _DMI_PLAUSIBLE_MAX
                    ):
                        invalid_cells += 1
                except ValueError:
                    invalid_cells += 1
            records.append({"year": year, "month": month_idx, "dmi_value": val})

    if not records:
        raise ValueError(
            "IOD bronze: no parseable data rows found -- file may be malformed or empty"
        )

    df = pd.DataFrame(records)

    # Hard uniqueness assertion: the header/observation collision that produced the
    # duplicate (1870, 1) MUST NOT survive. Fail closed if it does.
    dupes = df.duplicated(subset=["year", "month"], keep=False)
    if bool(dupes.any()):
        dup_keys = (
            df.loc[dupes, ["year", "month"]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
        raise ValueError(
            f"IOD bronze: duplicate (year, month) keys after parsing: {sorted(dup_keys)} "
            "-- a header line was admitted as data"
        )

    df["date"] = pd.to_datetime(df[["year", "month"]].assign(day=1))
    df["source"] = "noaa_iod"
    df["dmi_value"] = df["dmi_value"].astype("float64")

    df = df[BRONZE_COLUMNS].sort_values(["year", "month"]).reset_index(drop=True)

    non_null = int(df["dmi_value"].notna().sum())
    logger.info(
        "IOD bronze: %d rows parsed  non-null=%d  years=%d-%d  "
        "header_bounds=[%d,%d]  skipped_nondata=%d  rejected_out_of_bounds=%d  invalid_cells=%d",
        len(df), non_null, int(df["year"].min()), int(df["year"].max()),
        start_year, end_year, skipped_nondata, rejected_bounds, invalid_cells,
    )
    return df
