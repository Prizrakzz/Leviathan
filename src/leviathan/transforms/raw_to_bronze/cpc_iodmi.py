"""Bronze transform for the NOAA CPC Indian Ocean Dipole Mode Index (IODMI) file.

Parses the fixed-width ``mnth.ersstv5.clim19912020.dmi_current.txt`` file published by
NOAA CPC at:
    https://www.cpc.ncep.noaa.gov/products/international/ocean_monitoring/IODMI/mnth.ersstv5.clim19912020.dmi_current.txt

Why this module exists (ADR_IOD_SOURCE_SWITCH, RATIFIED 2026-07-24, Option B)
----------------------------------------------------------------------------
The incumbent DMI source (``raw_to_bronze/noaa_iod.py``, NOAA PSL HadISST1.1) is FROZEN
upstream: the file was last regenerated 2025-06-16 and its last real observation is
2025-04, with May-2025 onward published as ``-9999`` sentinels. The ADR re-baselines
``silver_noaa_iod`` onto the CPC ERSSTv5 IODMI record (monthly, 1950-01..present, ~1 month
lag, actively updated).

The SERVED identity does not move: same table ``silver_noaa_iod``, same 8-column schema,
same ``silver/weather/source=noaa_iod`` root (ADR-003 rule 6, legacy stable identifier).
What moves is the SST basis (ERSSTv5 on a fixed 1991-2020 climatology instead of HadISST1.1
on a full-record mean), the raw/bronze capture prefix (``source=cpc_iodmi``, truthful
provenance), and the ``source`` stamp (ADR-003 rule 2 -- the stamp names the true provider
of the rows). The HadISST parser stays runnable and untouched: it still produces the
immutable ``_hadisst_frozen`` provenance snapshot.

File format
-----------
Seven provenance/preamble lines, a column header, then one row per month, 1950-01 onward
(918 rows as of the 2026-06 vintage)::

    Data sources for indices:
    ERSST.V5 : Huang, B., Peter W. Thorne, et. al, 2017: Extended Reconstructed Sea ...
    Climatology : 1991-2020

    WTIO  : SSTA averaged in [50<deg>E-70<deg>E, 10<deg>S-10<deg>N]
    SETIO : SSTA averaged in [90<deg>E-110<deg>E, 10<deg>S-0]
    DMI  = WTIO - SETIO

      Year   Month     WTIO      SETIO       DMI
      1950     1      -0.85      -0.93       0.08
      ...
      2026     6       0.24       0.82      -0.58

All three measures are SST anomalies in degC against the fixed 1991-2020 climatology, each
published rounded independently to two decimals. The box geometry is IDENTICAL to the
HadISST product we are leaving (WTIO 50E-70E/10S-10N, SETIO 90E-110E/10S-0), so only the
reconstruction differs -- see the ADR Section 3 for the quantified divergence.

SILVER-F041 carry-over -- the column header is shaped like a data row
--------------------------------------------------------------------
The HadISST parser once admitted its ``1870 2025`` year-range header AS DATA, minting an
impossible ``dmi_value=2025`` that collided with the real ``(1870, 1)`` observation. This
file has the same trap in a different shape: the column header
``Year   Month     WTIO      SETIO       DMI`` splits into EXACTLY the five whitespace
tokens a real data row has, so a token-count rule alone would admit it. The same structural
defence is applied here:

  * a data row must begin with a bare 4-digit year (``Year`` cannot match) AND carry
    exactly 5 whitespace tokens;
  * the year must fall inside the documented record window and the month inside 1-12;
  * each measure cell is coerced to a plausible anomaly float; the missing sentinel and any
    out-of-range value become NaN (never a synthesized number, INV-4);
  * ``(year, month)`` uniqueness is asserted before the frame is returned;
  * ``DMI == WTIO - SETIO`` is asserted within the published rounding tolerance -- a
    column-order swap or a unit change fails the ingest closed instead of silently
    re-baselining the served series.

Climatology guard
-----------------
The URL pins the ``clim19912020`` vintage and the ADR ratified the 1991-2020 anomaly basis
explicitly (decision 5, "do NOT re-anomalize"). If CPC ever re-issues this file against a
different climatology every historical value shifts, so the preamble's declared climatology
is verified and a mismatch raises: a silent re-baseline is exactly the failure this ADR
exists to prevent.
"""
from __future__ import annotations

import re

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# Truthful provider stamp for every row this parser emits (ADR-003 rule 2).
SOURCE = "cpc_iodmi"

# The anomaly basis this producer is ratified against; a change upstream must fail closed.
EXPECTED_CLIMATOLOGY = "1991-2020"

# Missing value sentinel: values <= this are NaN. The live CPC file publishes only
# completed months and carries no sentinel today; the guard is defensive because sibling
# NOAA files use -99.9 / -9999.0 (the HadISST DMI file pads its current year with -9999).
_MISSING_SENTINEL = -99.0

# Documented scientifically-plausible band (degC SST anomaly) for all three measures. The
# two box anomalies and their difference are small; over the full 1950-present record the
# observed extremes are WTIO [-1.49, 1.22], SETIO [-1.71, 1.16], DMI [-1.19, 1.78]. A
# parsed value outside +/-3 that is NOT the missing sentinel is invalid data -> NaN.
_ANOMALY_PLAUSIBLE_MIN = -3.0
_ANOMALY_PLAUSIBLE_MAX = 3.0

# The CPC record starts 1950-01; the upper bound is a permissive calendar guard (the file
# carries no year-range header to bound against, unlike the HadISST product).
_RECORD_START_YEAR = 1950
_MAX_PLAUSIBLE_YEAR = 2100

# A data row is: year, month, WTIO, SETIO, DMI.
_DATA_ROW_TOKENS = 5

# WTIO / SETIO / DMI are each rounded INDEPENDENTLY to two decimals, so the published
# identity can miss by up to three half-ULPs of that precision (0.005 on each box plus
# 0.005 on the difference) = 0.015. The worst residual over all 918 months of the live
# file is exactly 0.01 (e.g. 1958-07: -0.68 - 0.18 = -0.86 published as -0.85), so this
# tolerance admits the real file while still catching a swapped column order or a unit
# change -- both of which produce residuals far larger than one published ULP.
_PUBLISHED_HALF_ULP = 0.005
_IDENTITY_TOLERANCE = 3 * _PUBLISHED_HALF_ULP + 1e-9

# The declared anomaly basis, e.g. "Climatology : 1991-2020".
_CLIMATOLOGY_RE = re.compile(r"^\s*Climatology\s*:\s*(\S+)\s*$", re.IGNORECASE)
# A candidate data row starts with a bare 4-digit year (the column header does not).
_LEADING_YEAR_RE = re.compile(r"^\s*(\d{4})(?:\s|$)")

BRONZE_COLUMNS: list[str] = [
    "year",
    "month",
    "date",
    "wtio_value",
    "setio_value",
    "dmi_value",
    "source",
]


def parse_climatology(lines: list[str]) -> str | None:
    """Return the declared anomaly climatology (e.g. ``"1991-2020"``) from the preamble.

    Parsed independently of the observation rows -- the preamble can never be admitted as
    data. Returns ``None`` when the file carries no ``Climatology :`` line.
    """
    for line in lines:
        m = _CLIMATOLOGY_RE.match(line)
        if m:
            return m.group(1)
    return None


def _coerce_cell(val_str: str) -> float | None:
    """Coerce one measure cell to a plausible anomaly float, else ``None`` (NaN).

    Missing sentinel and out-of-plausible-range values both map to ``None`` -- the latter
    is the structural backstop that keeps a header token or a decimal-shifted value out of
    a served measure.
    """
    try:
        val = float(val_str)
    except ValueError:
        return None
    if val <= _MISSING_SENTINEL:
        return None
    if not (_ANOMALY_PLAUSIBLE_MIN <= val <= _ANOMALY_PLAUSIBLE_MAX):
        return None
    return val


def _is_invalid_cell(val_str: str) -> bool:
    """True when a cell is unparseable or out of range -- i.e. NaN for a reason that is NOT
    the documented missing sentinel (which is expected and counted separately)."""
    try:
        raw = float(val_str)
    except ValueError:
        return True
    return raw > _MISSING_SENTINEL and not (
        _ANOMALY_PLAUSIBLE_MIN <= raw <= _ANOMALY_PLAUSIBLE_MAX
    )


def extract_cpc_iodmi_bronze(raw_bytes: bytes) -> pd.DataFrame:
    """Parse the CPC IODMI text file into a long-format bronze DataFrame.

    Args:
        raw_bytes: Raw bytes of ``mnth.ersstv5.clim19912020.dmi_current.txt`` from S3 (or
            an HTTP fetch). Decoded as UTF-8 -- the preamble carries degree signs.

    Returns:
        DataFrame with columns :data:`BRONZE_COLUMNS`. One row per (year, month) in file
        order, 1950-01 onward, source-faithful: every parsed row is kept, and all three
        published measures (``wtio_value``, ``setio_value``, ``dmi_value``) are retained.
        ``(year, month)`` is unique (asserted).

    Raises:
        ValueError: If the declared climatology is not the ratified basis, if no parseable
            data rows are found, if a duplicate ``(year, month)`` survives parsing, or if
            any fully-populated row violates ``DMI == WTIO - SETIO`` beyond the published
            rounding tolerance.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.strip().splitlines()

    climatology = parse_climatology(lines)
    if climatology is None:
        # Warn -- a healthy CPC file always declares one; the values are still parseable.
        logger.warning(
            "CPC IODMI bronze: no 'Climatology :' preamble line found; cannot verify the "
            "ratified %s anomaly basis", EXPECTED_CLIMATOLOGY,
        )
    elif climatology != EXPECTED_CLIMATOLOGY:
        raise ValueError(
            f"CPC IODMI bronze: file declares climatology {climatology!r}, expected "
            f"{EXPECTED_CLIMATOLOGY!r} -- upstream re-anomalized the record, which restates "
            "every historical value. Refusing to publish silently; re-ratify the source "
            "basis (ADR_IOD_SOURCE_SWITCH decision 5) before repinning."
        )

    records: list[dict] = []
    skipped_nondata = 0
    rejected_bounds = 0
    invalid_cells = 0

    for line in lines:
        ym = _LEADING_YEAR_RE.match(line)
        if not ym:
            # Preamble, blank lines, and the "Year Month WTIO SETIO DMI" column header --
            # which has exactly _DATA_ROW_TOKENS tokens and is excluded HERE, by the
            # leading-year rule, not by the token count (SILVER-F041 carry-over).
            skipped_nondata += 1
            continue

        parts = line.split()
        if len(parts) != _DATA_ROW_TOKENS:
            # A truncated row or a footer line that happens to start with a year.
            skipped_nondata += 1
            continue

        year = int(parts[0])
        try:
            month = int(parts[1])
        except ValueError:
            skipped_nondata += 1
            continue

        if not (_RECORD_START_YEAR <= year <= _MAX_PLAUSIBLE_YEAR) or not (1 <= month <= 12):
            rejected_bounds += 1
            continue

        measures: list[float | None] = []
        for val_str in parts[2:]:
            val = _coerce_cell(val_str)
            if val is None and _is_invalid_cell(val_str):
                invalid_cells += 1
            measures.append(val)

        wtio, setio, dmi = measures
        records.append({
            "year": year,
            "month": month,
            "wtio_value": wtio,
            "setio_value": setio,
            "dmi_value": dmi,
        })

    if not records:
        raise ValueError(
            "CPC IODMI bronze: no parseable data rows found -- file may be malformed or empty"
        )

    df = pd.DataFrame(records)

    # Hard uniqueness assertion (SILVER-F041): a header/observation collision MUST NOT
    # survive into a frame the rolling/lag features are computed on. Fail closed.
    dupes = df.duplicated(subset=["year", "month"], keep=False)
    if bool(dupes.any()):
        dup_keys = (
            df.loc[dupes, ["year", "month"]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
        raise ValueError(
            f"CPC IODMI bronze: duplicate (year, month) keys after parsing: {sorted(dup_keys)}"
        )

    for col in ("wtio_value", "setio_value", "dmi_value"):
        df[col] = df[col].astype("float64")

    # DMI == WTIO - SETIO, within the published rounding tolerance. Checked only where all
    # three measures are present (a sentinel in any column makes the identity uncheckable,
    # not violated).
    checkable = df[["wtio_value", "setio_value", "dmi_value"]].notna().all(axis=1)
    residual = (df["dmi_value"] - (df["wtio_value"] - df["setio_value"])).abs()
    violations = df.loc[checkable & (residual > _IDENTITY_TOLERANCE)]
    if not violations.empty:
        offenders = [
            (int(r.year), int(r.month), float(r.wtio_value), float(r.setio_value),
             float(r.dmi_value))
            for r in violations.head(5).itertuples(index=False)
        ]
        raise ValueError(
            f"CPC IODMI bronze: {len(violations)} row(s) violate DMI = WTIO - SETIO beyond "
            f"the published rounding tolerance {_IDENTITY_TOLERANCE:.4f}; first offenders "
            f"(year, month, wtio, setio, dmi): {offenders} -- the column order or the units "
            "of the upstream file have changed"
        )
    unchecked = int((~checkable).sum())

    df["date"] = pd.to_datetime(df[["year", "month"]].assign(day=1))
    df["source"] = SOURCE

    df = df[BRONZE_COLUMNS].sort_values(["year", "month"]).reset_index(drop=True)

    non_null = int(df["dmi_value"].notna().sum())
    logger.info(
        "CPC IODMI bronze: %d rows parsed  non-null_dmi=%d  years=%d-%d  climatology=%s  "
        "identity_checked=%d  identity_unchecked=%d  skipped_nondata=%d  "
        "rejected_out_of_bounds=%d  invalid_cells=%d",
        len(df), non_null, int(df["year"].min()), int(df["year"].max()),
        climatology or "unknown", len(df) - unchecked, unchecked, skipped_nondata,
        rejected_bounds, invalid_cells,
    )
    return df
