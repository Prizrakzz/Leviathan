"""NOAA IOD bronze → silver transform.

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
    DMI ≈ 1.28 in November) preceded a major Ethiopian crop failure in the
    1998 harvest season.  The 4-month lag captures the Belg window stress
    directly.

    Feature engineering note: the lag here is applied against the already
    3-month-smoothed series, so ``iod_dmi_ethiopia_lag4`` at month T is the
    smoothed DMI from month T−4.  The feature engineering pipeline does NOT
    apply an additional lag when building the annual crop-year feature matrix;
    it reads this column directly for the relevant growing-season month(s).
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


def build_iod_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform NOAA IOD bronze into the silver feature table.

    Args:
        df_bronze: Bronze DataFrame produced by
                   :func:`~leviathan.transforms.raw_to_bronze.noaa_iod.extract_iod_bronze`.
                   Must contain ``year``, ``month``, ``date``, ``dmi_value``.

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

    df["source"] = "noaa_iod"

    result = df[SILVER_COLUMNS].reset_index(drop=True)

    positive_count = int((result["iod_phase"] == "positive").sum())
    negative_count = int((result["iod_phase"] == "negative").sum())
    neutral_count  = int((result["iod_phase"] == "neutral").sum())
    lag_non_null   = int(result["iod_dmi_ethiopia_lag4"].notna().sum())

    logger.info(
        "IOD silver: %d rows  years=%d–%d  "
        "positive=%d  negative=%d  neutral=%d  "
        "ethiopia_lag4_non_null=%d",
        len(result),
        int(result["year"].min()),
        int(result["year"].max()),
        positive_count,
        negative_count,
        neutral_count,
        lag_non_null,
    )
    return result
