"""IOD bronze → silver transform — SST-basis agnostic.

Serves ``silver_noaa_iod`` from EITHER DMI basis (ADR_IOD_SOURCE_SWITCH, RATIFIED
2026-07-24, Option B):

  * the incumbent NOAA PSL **HadISST1.1** long file (``raw_to_bronze/noaa_iod.py``) --
    frozen upstream, last real observation 2025-04, retained only as the immutable
    ``_hadisst_frozen`` provenance snapshot;
  * the re-baselined NOAA CPC **ERSSTv5** IODMI record (``raw_to_bronze/cpc_iodmi.py``,
    ``bronze_to_silver/cpc_iodmi.py``) -- monthly, 1950-01..present, actively updated,
    anomalies against a fixed 1991-2020 climatology.

Every derivation below (3-month mean, ±0.4 phase band, Ethiopia lag-4, trailing-tail
trim) is a pure function of the ordered ``dmi_value`` series, so all of it is
basis-agnostic and is REUSED unchanged across the switch; the ONLY basis-dependent
output is the ``source`` stamp (:func:`build_iod_silver`, ADR Section 5).  The served
identity does not move either: same table, same 8 columns, same
``silver/weather/source=noaa_iod`` root (ADR decision 6.4, legacy stable identifier).

Extends the bronze (year, month, date, dmi_value) with three features:

iod_dmi_3month_avg
    3-month rolling mean of dmi_value (min_periods=2).
    Maps to the ``iod_dmi_3month_avg`` universal feature in the taxonomy.
    Smooths month-to-month noise; the IOD signal is most meaningful on
    a seasonal (3-month) timescale rather than individual months.

iod_phase
    Categorical phase classification based on raw dmi_value:
        "positive"  — dmi_value > +0.4  (JMA threshold)
        "negative"  — dmi_value < −0.4
        "neutral"   — otherwise
    NaN months are classified "unknown".

iod_dmi_ethiopia_lag4
    iod_dmi_3month_avg shifted forward 4 months.
    Maps to the ``iod_dmi_ethiopia_lag4`` commodity-specific feature for
    arabica coffee (Ethiopia origin).

    Rationale: The IOD typically peaks in September–November (SON season).
    Ethiopian arabica growing regions (Sidama, Yirgacheffe, Guji) experience
    the primary Kiremt (long) rains June–September and the secondary Belg
    (short) rains March–May.  A positive IOD peak in October suppresses the
    Belg rains that follow approximately 4 months later — affecting flowering
    and early cherry development.  The well-documented 1997 event (peak
    DMI ≈ 1.55 in November on the SERVED CPC ERSSTv5 basis) preceded a major
    Ethiopian crop failure in the 1998 harvest season.  The 4-month lag captures
    the Belg window stress directly.

    Basis note (ADR Section 3.1): that same November-1997 peak reads ≈ 1.28 on the
    retired HadISST1.1 basis — the two SST reconstructions diverge MOST exactly at
    the analogue peaks (1997-11 +21%, 2019-10 +85%), which is why the re-baseline
    restates event magnitudes rather than only refreshing the tail.  Any teaching
    example or cited magnitude must name the basis it came from.

    Feature engineering note: the lag here is applied against the already
    3-month-smoothed series, so ``iod_dmi_ethiopia_lag4`` at month T is the
    smoothed DMI from month T−4.  The feature engineering pipeline does NOT
    apply an additional lag when building the annual crop-year feature matrix;
    it reads this column directly for the relevant growing-season month(s).

Trailing-tail trim (IOD-FRESHNESS)
----------------------------------
The HadISST source pads the current year with the ``-9999`` sentinel for months
not yet observed (which the bronze parser maps to ``dmi_value = NaN``), and the
HadISST1.1 reconstruction it is built on lags the calendar by several months.
This silver transform drops that trailing all-placeholder block so the last row
is the last month with a real ``dmi_value``.  (The CPC ERSSTv5 file publishes only
COMPLETED months and pads nothing, so on that basis the trim is normally a no-op —
it stays as the basis-agnostic invariant that the last served row is a real
reading whichever file feeds it.)  Without the trim, the numbers-agent
``agg=latest`` (which has no ``IS NOT NULL`` guard on its LIMIT-1 pick) would
return the NaN sentinel row for a live "latest IOD" ask instead of the last real
reading.  Only the CONTIGUOUS trailing block is removed; every earlier row —
including any interior gap — is preserved.  The bronze layer is unchanged: it
still carries the sentinel months as NaN (source-faithful provenance); the trim
is a silver-only concern because silver is the served / feature surface.
"""
from __future__ import annotations

import pandas as pd
import pyarrow as pa

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# INV-2: the explicit writer schema pinned at the write step, matching the
# silver_noaa_iod registry contract's target_arrow_type for every column (measures
# float64, not float32; integers int64; date timestamp[us]; text string). A test
# (test_transforms_noaa_iod.py) reconciles this literal against the registry so the
# two can never drift.
SILVER_ARROW_SCHEMA = pa.schema([
    ("year", pa.int64()),
    ("month", pa.int64()),
    ("date", pa.timestamp("us")),
    ("dmi_value", pa.float64()),
    ("iod_dmi_3month_avg", pa.float64()),
    ("iod_phase", pa.string()),
    ("iod_dmi_ethiopia_lag4", pa.float64()),
    ("source", pa.string()),
])


def silver_arrow_schema() -> pa.Schema:
    """Return the explicit INV-2 writer schema for ``silver_noaa_iod``."""
    return SILVER_ARROW_SCHEMA

_POSITIVE_IOD_THRESHOLD =  0.4
_NEGATIVE_IOD_THRESHOLD = -0.4
_ROLLING_WINDOW = 3
_MIN_PERIODS    = 2
_ETHIOPIA_LAG   = 4   # months

# Fallback provider stamp when the caller names none and the bronze carries none. It is the
# HadISST identity because that is the basis this transform shipped with; a CPC-fed run never
# reaches it (its bronze stamps ``cpc_iodmi``, and bronze_to_silver/cpc_iodmi.py passes the
# stamp explicitly). Never a table/path name — the stamp names the TRUE PROVIDER of the rows
# (ADR-003 rule 2), which is why the silver source column and the legacy s3_root diverge here.
_DEFAULT_SOURCE_STAMP = "noaa_iod"

SILVER_COLUMNS: list[str] = [
    "year",
    "month",
    "date",
    "dmi_value",
    "iod_dmi_3month_avg",
    "iod_phase",
    "iod_dmi_ethiopia_lag4",
    "source",
]


def _classify_phase(val: float | None) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "unknown"
    if val >= _POSITIVE_IOD_THRESHOLD:
        return "positive"
    if val <= _NEGATIVE_IOD_THRESHOLD:
        return "negative"
    return "neutral"


def _resolve_source_stamp(df_bronze: pd.DataFrame, source: str | None) -> str:
    """Resolve the served ``source`` stamp: explicit argument > the bronze's own stamp >
    :data:`_DEFAULT_SOURCE_STAMP`.

    Both IOD bronze parsers stamp their own truthful provider (``noaa_iod`` / ``cpc_iodmi``),
    so the middle rung means an unmodified caller that just hands a bronze frame through
    carries the right basis into silver instead of silently re-labelling it.  A blank or
    mixed bronze stamp is ignored in favour of the default — the stamp must be ONE
    unambiguous provider for every row of a published frame.
    """
    if source:
        return source
    if "source" in df_bronze.columns:
        stamps = {str(s) for s in df_bronze["source"].dropna().unique() if str(s).strip()}
        if len(stamps) == 1:
            return stamps.pop()
    return _DEFAULT_SOURCE_STAMP


def build_iod_silver(df_bronze: pd.DataFrame, source: str | None = None) -> pd.DataFrame:
    """Transform IOD bronze into the silver feature table (either SST basis).

    Args:
        df_bronze: Bronze DataFrame produced by
                   :func:`~leviathan.transforms.raw_to_bronze.noaa_iod.extract_iod_bronze`
                   (HadISST) or
                   :func:`~leviathan.transforms.raw_to_bronze.cpc_iodmi.extract_cpc_iodmi_bronze`
                   (CPC ERSSTv5). Must contain ``year``, ``month``, ``date``, ``dmi_value``;
                   any additional bronze column (the CPC parser's ``wtio_value`` /
                   ``setio_value`` boxes) is carried through the derivation and dropped by the
                   :data:`SILVER_COLUMNS` projection — the served schema never widens.
        source: Truthful provider stamp for the served rows (ADR-003 rule 2). Defaults to the
                bronze's own stamp, then to :data:`_DEFAULT_SOURCE_STAMP`. This is the ONLY
                basis-dependent input: everything else here is a pure function of the ordered
                ``dmi_value`` series and is reused UNCHANGED across the source switch.

    Returns:
        DataFrame with columns :data:`SILVER_COLUMNS`, sorted by
        ``(year, month)``.  Lag and rolling columns are ``NaN`` for the
        first N rows — handled natively by XGBoost.

    Raises:
        ValueError: If the input DataFrame is empty or missing required columns.
    """
    required = {"year", "month", "date", "dmi_value"}
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"IOD bronze missing required columns: {missing}")
    if df_bronze.empty:
        raise ValueError("IOD bronze DataFrame is empty")

    # SILVER-F041: assert (year, month) uniqueness BEFORE any rolling/lag feature.
    # A duplicated key (the 1870,1 header/observation collision) would silently
    # corrupt the ordered rolling mean and the 4-month shift. Fail closed.
    dup_mask = df_bronze.duplicated(subset=["year", "month"], keep=False)
    if bool(dup_mask.any()):
        dup_keys = sorted(
            df_bronze.loc[dup_mask, ["year", "month"]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
        raise ValueError(
            f"IOD silver: duplicate (year, month) keys in bronze {dup_keys} "
            "-- refusing to compute rolling/lag features on a corrupt series"
        )

    df = (
        df_bronze
        .sort_values(["year", "month"])
        .reset_index(drop=True)
        .copy()
    )

    # 3-month rolling mean -- universal feature. INV-2: measures write as float64
    # (the registry drift_summary widen_float target, owner SILVER-F041); no float32
    # fragment across write eras.
    df["iod_dmi_3month_avg"] = (
        df["dmi_value"]
        .rolling(_ROLLING_WINDOW, min_periods=_MIN_PERIODS)
        .mean()
        .round(4)
        .astype("float64")
    )

    # Phase classification on raw dmi_value
    df["iod_phase"] = df["dmi_value"].apply(_classify_phase)

    # Ethiopia-specific lag: smoothed DMI shifted 4 months forward
    df["iod_dmi_ethiopia_lag4"] = (
        df["iod_dmi_3month_avg"]
        .shift(_ETHIOPIA_LAG)
        .round(4)
        .astype("float64")
    )

    df["source"] = _resolve_source_stamp(df_bronze, source)

    # IOD-FRESHNESS (SKEPTIC-2) -- trim the trailing placeholder tail.
    # The HadISST source pads the CURRENT year with the -9999 sentinel for months not
    # yet observed (-> dmi_value NaN), and it is a lagging HadISST1.1 reconstruction
    # whose real horizon trails the calendar. (The CPC ERSSTv5 basis publishes only
    # completed months and pads nothing, so there the trim is normally a no-op -- it
    # stays as the basis-agnostic invariant.) Left in place, those trailing all-
    # placeholder months make the numbers-agent ``agg=latest`` return the NaN
    # sentinel row (the latest-pick has no IS NOT NULL guard) instead of the last
    # real DMI -- a live "latest IOD" ask serves NaN. Trim so the max (year, month)
    # present IS the last observed reading, i.e. the last month with a real
    # ``dmi_value`` (the source observation). Both served metrics (dmi_value and its
    # 3-month mean) are real at that boundary, so ``agg=latest`` is honest.
    #
    # Only the CONTIGUOUS trailing block after the last real observation is removed:
    # ``.loc[:last_obs]`` keeps every earlier row, so any interior gap (none exist in
    # the complete 1870-present HadISST record, but guard regardless) is preserved.
    # NB the sibling ``silver_noaa_oni`` needs no such trim -- the CPC ONI source
    # publishes only completed seasons and never pads a sentinel tail.
    observed = df.index[df["dmi_value"].notna()]
    if len(observed) == 0:
        raise ValueError(
            "IOD silver: no non-null dmi_value in the series -- refusing to publish "
            "an all-placeholder frame (upstream source is malformed or all-sentinel)"
        )
    last_obs = int(observed.max())
    trimmed = len(df) - (last_obs + 1)
    if trimmed:
        logger.info(
            "IOD silver: trimmed %d trailing placeholder month(s) past the last "
            "observed dmi_value at %d-%02d",
            trimmed, int(df.at[last_obs, "year"]), int(df.at[last_obs, "month"]),
        )
    df = df.loc[:last_obs]

    result = df[SILVER_COLUMNS].reset_index(drop=True)

    positive_count = int((result["iod_phase"] == "positive").sum())
    negative_count = int((result["iod_phase"] == "negative").sum())
    neutral_count  = int((result["iod_phase"] == "neutral").sum())
    lag_non_null   = int(result["iod_dmi_ethiopia_lag4"].notna().sum())

    logger.info(
        "IOD silver: %d rows  source=%s  years=%d–%d  "
        "positive=%d  negative=%d  neutral=%d  "
        "ethiopia_lag4_non_null=%d",
        len(result),
        str(result["source"].iloc[0]),           # the SST basis this frame was built on
        int(result["year"].min()),
        int(result["year"].max()),
        positive_count,
        negative_count,
        neutral_count,
        lag_non_null,
    )
    return result
