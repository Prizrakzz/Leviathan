"""NOAA ONI bronze -> silver transform (SILVER-F057, full-orphan rebuild).

Extends the bronze (year, month, season, oni_total, oni_anom) into the canonical
``silver_noaa_oni`` feature table consumed by the numbers stack (``silverleg.py``,
``numbers/agent.py``) and the feature layer (``macro_climate.compute_oni_climate`` /
``compute_oni_lag``).

Every derived column below was reverse-engineered from the live physical silver
(915 rows, 1950-2026) and reproduces it bit-for-bit (validated in the F057 golden test):

phase / el_nino_flag / la_nina_flag
    Per-row threshold classification on ``oni_anom`` (NOT the "5 consecutive seasons"
    event rule -- the physical table classifies each row independently):
        oni_anom >= +0.5  -> "el_nino"  (el_nino_flag = 1)
        oni_anom <= -0.5  -> "la_nina"  (la_nina_flag = 1)
        otherwise          -> "neutral"
    A null anomaly stays "neutral" with both flags 0 (absent evidence is not an event;
    the null measure itself is never synthesized -- INV-4).

oni_lag3 / oni_lag6 / oni_lag9 / oni_lag12
    The ONI anomaly from 3 / 6 / 9 / 12 months earlier -- ``oni_anom.shift(N)`` on the
    chronologically-sorted series. Strictly backward-looking (no lookahead): the first N
    rows are ``NaN`` by construction, handled natively downstream by XGBoost.

la_nina_brazil_flag
    La Nina restricted to the DJF core (months 12, 1, 2) -- the Southern-Hemisphere summer
    peak that drives southern-Brazil drought risk for soy / coffee / sugar / cane.
    = la_nina_flag AND month in {12, 1, 2}.

argentina_la_nina_flag
    La Nina across the whole episode (the Argentine Pampas teleconnection is not gated to
    the DJF peak in the source table) -- identical to ``la_nina_flag``. Kept as a distinct
    semantically-named column because the feature layer surfaces it only for Argentine-origin
    commodities (``macro_climate._ARGENTINA_TELECONNECTION``).
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_EL_NINO_THRESHOLD = 0.5
_LA_NINA_THRESHOLD = -0.5
_ONI_LAGS = (3, 6, 9, 12)

# The DJF-core months where the La Nina teleconnection is strongest for southern Brazil.
_BRAZIL_LA_NINA_MONTHS = frozenset({12, 1, 2})

PHASE_EL_NINO = "el_nino"
PHASE_LA_NINA = "la_nina"
PHASE_NEUTRAL = "neutral"

SILVER_COLUMNS: list[str] = [
    "year",
    "month",
    "season",
    "oni_anom",
    "phase",
    "oni_lag3",
    "oni_lag6",
    "oni_lag9",
    "oni_lag12",
    "el_nino_flag",
    "la_nina_flag",
    "la_nina_brazil_flag",
    "argentina_la_nina_flag",
    "source",
]


def classify_oni_phase(anom) -> str:
    """Classify one ONI anomaly into the ENSO phase (per-row threshold rule)."""
    if anom is None or (isinstance(anom, float) and pd.isna(anom)):
        return PHASE_NEUTRAL
    if anom >= _EL_NINO_THRESHOLD:
        return PHASE_EL_NINO
    if anom <= _LA_NINA_THRESHOLD:
        return PHASE_LA_NINA
    return PHASE_NEUTRAL


def build_oni_silver(df_bronze: pd.DataFrame) -> pd.DataFrame:
    """Transform NOAA ONI bronze into the silver feature table.

    Args:
        df_bronze: Bronze DataFrame from
            :func:`~leviathan.transforms.raw_to_bronze.noaa_oni.extract_oni_bronze`; must
            carry ``year``, ``month``, ``season``, ``oni_anom``.

    Returns:
        DataFrame with columns :data:`SILVER_COLUMNS`, one row per (year, month), sorted
        chronologically, with zero natural-key (year, month, season) duplicates.

    Raises:
        ValueError: If required columns are missing, the frame is empty, or the natural
            key is not unique.
    """
    required = {"year", "month", "season", "oni_anom"}
    missing = required - set(df_bronze.columns)
    if missing:
        raise ValueError(f"ONI bronze missing required columns: {sorted(missing)}")
    if df_bronze.empty:
        raise ValueError("ONI bronze DataFrame is empty")

    df = (
        df_bronze
        .sort_values(["year", "month"])
        .reset_index(drop=True)
        .copy()
    )

    dup = df.duplicated(subset=["year", "month", "season"]).sum()
    if dup:
        raise ValueError(f"ONI silver: {int(dup)} duplicate (year, month, season) rows in bronze")

    # Phase + binary flags (per-row threshold).
    df["phase"] = df["oni_anom"].apply(classify_oni_phase)
    df["el_nino_flag"] = (df["phase"] == PHASE_EL_NINO).astype("int64")
    df["la_nina_flag"] = (df["phase"] == PHASE_LA_NINA).astype("int64")

    # Backward-looking anomaly lags (no lookahead; first N rows are NaN).
    for n in _ONI_LAGS:
        df[f"oni_lag{n}"] = df["oni_anom"].shift(n)

    # Region-specific La Nina teleconnection flags.
    df["la_nina_brazil_flag"] = (
        (df["la_nina_flag"] == 1) & (df["month"].isin(_BRAZIL_LA_NINA_MONTHS))
    ).astype("int64")
    df["argentina_la_nina_flag"] = df["la_nina_flag"].astype("int64")

    df["source"] = "noaa_oni"

    result = df[SILVER_COLUMNS].reset_index(drop=True)

    logger.info(
        "ONI silver: %d rows  years=%d-%d  el_nino=%d  la_nina=%d  neutral=%d  "
        "brazil_lanina=%d  lag3_non_null=%d",
        len(result), int(result["year"].min()), int(result["year"].max()),
        int(result["el_nino_flag"].sum()), int(result["la_nina_flag"].sum()),
        int((result["phase"] == PHASE_NEUTRAL).sum()),
        int(result["la_nina_brazil_flag"].sum()),
        int(result["oni_lag3"].notna().sum()),
    )
    return result
