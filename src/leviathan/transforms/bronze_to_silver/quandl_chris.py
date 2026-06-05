"""Quandl CHRIS bronze → silver transform.

Joins the C1/C2/C3 bronze DataFrames for each slug and produces:

settle_c1 / settle_c2 / settle_c3
    Official daily settlement prices for front, 2nd-nearby, 3rd-nearby.
    Roll-adjusted (Panama canal method) — no gaps at roll dates.

spread_c1c3
    settle_c1 − settle_c3.
    Positive = backwardation (front premium) = tight near-term supply.
    Negative = contango (deferred premium) = ample storage / surplus.

    This is the primary Tier 3 calendar spread signal.  In normal
    inventory conditions, futures are in contango (cost of carry dominates).
    When supply is tight, nearby demand exceeds deferred and the spread
    inverts to backwardation.

spread_c1c3_z_3yr
    Rolling 756-day (3yr) z-score of spread_c1c3.
    Answers: "is the current calendar spread unusually backwardated or
    contangoed relative to its own recent history?"
    This is the raw calendar spread signal consumed by the Tier 3 model.
    Conditioning on S/U ratio quintile (which maps supply fundamentals to
    the expected spread level) happens at feature engineering time by
    joining this silver against the PSD/FAOSTAT silver — NOT here.

contango_flag
    1 if spread_c1c3 < 0 (deferred > front = market expects future supply).
    0 if backwardation (front > deferred = near-term supply tightness).

Z-score window
--------------
756 trading days ≈ 3 calendar years.  3yr is the standard window used in
systematic commodity trading for calendar spread signals — long enough to
span a full commodity cycle but short enough to adapt to structural shifts
in the market (new crop year baselines, demand regime changes).

Validation benchmarks
---------------------
Corn (corn_cbot):
  2012 drought year: spread_c1c3 should be strongly positive (backwardation)
  2016–2017 surplus: spread_c1c3 should be negative (contango)

These are built into the validation assertions in the task file.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

_SPREAD_Z_WINDOW  = 756   # 3yr ≈ 252 × 3
_SPREAD_Z_MIN     = 252   # 1yr minimum before producing z-score

SILVER_COLUMNS: list[str] = [
    "date",
    "leviathan_slug",
    "settle_c1",
    "settle_c2",
    "settle_c3",
    "spread_c1c3",
    "spread_c1c3_z_3yr",
    "contango_flag",
    "source",
]


def _rolling_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    roll = series.rolling(window=window, min_periods=min_periods)
    return ((series - roll.mean()) / roll.std()).round(4)


def build_calendar_spreads_silver(
    bronze_by_slug: dict[str, dict[int, pd.DataFrame]],
) -> pd.DataFrame:
    """Build the calendar spreads silver table from per-slug CHRIS bronze data.

    Args:
        bronze_by_slug: Nested dict ``{slug: {tenor: df_bronze}}``.
                        Missing tenors (e.g. discontinued rough rice C2/C3)
                        are handled gracefully — the slug is skipped if C1
                        is missing, C2/C3 are NaN if missing.

    Returns:
        Long-format DataFrame with columns :data:`SILVER_COLUMNS`, sorted
        by ``(date, leviathan_slug)``.

    Raises:
        ValueError: If no slugs have at least a C1 series.
    """
    if not bronze_by_slug:
        raise ValueError("CHRIS silver: no input data provided")

    slug_results: list[pd.DataFrame] = []

    for slug, tenors in sorted(bronze_by_slug.items()):
        df1 = tenors.get(1)
        df2 = tenors.get(2)
        df3 = tenors.get(3)

        if df1 is None or df1.empty:
            logger.warning("CHRIS silver %s: no C1 data — skipping slug", slug)
            continue

        # Base on C1 dates
        result = df1[["date"]].copy()
        result["leviathan_slug"] = slug
        result["settle_c1"] = df1["settle"].values

        # Join C2 — align on date, NaN if missing
        if df2 is not None and not df2.empty:
            c2 = df2.set_index("date")["settle"].rename("settle_c2")
            result = result.set_index("date").join(c2).reset_index()
        else:
            result["settle_c2"] = float("nan")

        # Join C3
        if df3 is not None and not df3.empty:
            c3 = df3.set_index("date")["settle"].rename("settle_c3")
            result = result.set_index("date").join(c3).reset_index()
        else:
            result["settle_c3"] = float("nan")

        for col in ("settle_c1", "settle_c2", "settle_c3"):
            result[col] = result[col].astype("float32")

        # Calendar spread: C1 − C3 (backwardation positive)
        result["spread_c1c3"] = (result["settle_c1"] - result["settle_c3"]).astype("float32")

        # 3yr rolling z-score of the spread
        result["spread_c1c3_z_3yr"] = _rolling_zscore(
            result["spread_c1c3"], _SPREAD_Z_WINDOW, _SPREAD_Z_MIN
        ).astype("float32")

        # Contango flag
        result["contango_flag"] = (result["spread_c1c3"] < 0).astype("int8")

        result["source"] = "quandl_chris"

        slug_results.append(result[SILVER_COLUMNS])

        non_null_z = int(result["spread_c1c3_z_3yr"].notna().sum())
        c3_coverage = int(result["settle_c3"].notna().sum())
        logger.info(
            "CHRIS silver %s: %d rows  C3_coverage=%d  z_non_null=%d  "
            "spread_last=%.2f  contango_pct=%.0f%%",
            slug, len(result), c3_coverage, non_null_z,
            float(result["spread_c1c3"].dropna().iloc[-1]) if result["spread_c1c3"].notna().any() else float("nan"),
            float((result["contango_flag"] == 1).mean() * 100),
        )

    if not slug_results:
        raise ValueError("CHRIS silver: no slugs produced output")

    final = (
        pd.concat(slug_results, ignore_index=True)
        .sort_values(["date", "leviathan_slug"])
        .reset_index(drop=True)
    )
    return final
