"""PRICE_AND_PLAYBOOKS W1b -- MIAX bronze -> ``silver_futures_eod`` rows.

The bronze frame (:mod:`leviathan.transforms.raw_to_bronze.miax_eod`) already carries the outright
filter, the file-date-anchored delivery month and the numeric parse. This module does the last mile:

  * project onto the contract's SEVENTEEN physical columns in DECLARATION ORDER plus the two
    PARTITION columns;
  * write ``unit`` / ``currency`` / ``settle_kind`` / ``source`` from
    :func:`leviathan.silver.futures_eod_contracts.contract_for` -- MAP-DERIVED, never source-parsed.
    ``unit`` is ``USD/bushel``, corrected against the live file: MIAX publishes decimal dollars per
    bushel (7.0250), not the CBOT cents convention (~430). The value is NOT scaled to match a prior
    guess -- the label moved to the data, which is the ``CAD/t`` canola precedent;
  * ``settle`` is the file's own ``Settle`` column and ``settle_kind`` is ``settlement`` -- a TRUE
    exchange settlement, unlike the ICE legs whose ``close`` label is an honest stand-in for a
    settlement series that was not purchased;
  * ``close`` stays NULL: this file has no closing-trade column at all, and filling it from
    ``Settle`` would launder a settlement into a trade. ``Prev_Settle`` is likewise not written --
    it is the PRIOR session's settle, already present as its own row, and duplicating it into this
    row would double-count on any aggregation.

TWO NULLS BY SOURCE, NOT BY OVERSIGHT
-------------------------------------
``volume`` and ``open_interest`` are NULL on every MIAX row. The settlement CSV simply does not
carry them (they live in a separate daily PDF that is not part of this leg), and this is the ONLY
free leg for which that is true -- CZCE and JSE both publish both. Two consequences, both already
handled elsewhere and recorded here so neither looks like a bug later:

  * ``futures_roll.ROLL_METHOD_BY_SOURCE`` routes ``miax -> delivery_cycle`` rather than to the
    open-interest rule, so the curated ``(3, 5, 7, 9, 12)`` listing cycle IS the rule here rather
    than a degraded fallback. The 2026-07-28 file lists exactly H/K/N/U/Z, which matches;
  * the per-day row floor for this leg (6) is set against the 7 OUTRIGHTS the file carries, not
    against its 75 total rows -- 68 of which are options.

``expiry_date`` stays NULL (never derived from a delivery month) and ``dataset`` stays NULL (it is
the VENDOR dataset id; ``source`` already carries the publication channel).

Pure: pandas + the contract map. No boto3, no S3, no network.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.raw_to_bronze.miax_eod import MIAX_ROOT_MAP

logger = get_logger(__name__)

PHYSICAL_COLUMNS: list[str] = FC.PHYSICAL_COLUMNS
PARTITION_COLUMNS: list[str] = FC.PARTITION_COLUMNS
SILVER_COLUMNS: list[str] = FC.SILVER_COLUMNS

_MIAX_SLUGS: frozenset[str] = frozenset(MIAX_ROOT_MAP.values())


def build_miax_eod_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    """One or more MIAX bronze frames (already concatenated) -> the silver producer frame."""
    if bronze is None or len(bronze) == 0:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    required = {"trade_date", "leviathan_slug", "raw_symbol", "contract_month",
                "open", "high", "low", "settle"}
    missing = sorted(required - set(bronze.columns))
    if missing:
        raise ValueError(f"miax silver: bronze frame is missing columns {missing}")

    df = bronze.copy()
    slugs = sorted(set(df["leviathan_slug"]))
    alien = sorted(set(slugs) - _MIAX_SLUGS)
    if alien:
        raise ValueError(
            f"miax silver: slug(s) {alien} are not MIAX contracts -- this leg owns exactly "
            f"{sorted(_MIAX_SLUGS)}"
        )

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype("datetime64[us]")
    out["contract_month"] = df["contract_month"].astype("string")
    out["instrument_kind"] = "futures"
    out["raw_symbol"] = df["raw_symbol"].astype("string")
    out["settle"] = pd.to_numeric(df["settle"], errors="coerce").astype("float64")
    recs = {slug: FC.contract_for(slug) for slug in slugs}
    out["settle_kind"] = df["leviathan_slug"].map({s: r["settle_kind"] for s, r in recs.items()})
    for col in ("open", "high", "low"):
        out[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    # NULL BY SOURCE. The file has no close, and Settle is not one.
    out["close"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    # NULL BY SOURCE. Neither is published anywhere in this file -- see the module docstring.
    for col in ("volume", "open_interest"):
        out[col] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    out["unit"] = df["leviathan_slug"].map({s: r["unit"] for s, r in recs.items()})
    out["currency"] = df["leviathan_slug"].map({s: r["currency"] for s, r in recs.items()})
    out["expiry_date"] = pd.Series(pd.NaT, index=df.index).astype("datetime64[us]")
    out["source"] = df["leviathan_slug"].map({s: r["source"] for s, r in recs.items()})
    out["dataset"] = pd.Series(pd.NA, index=df.index, dtype="string")

    out["leviathan_slug"] = df["leviathan_slug"].astype("string")
    year = out["trade_date"].dt.year
    if year.isna().any():
        raise ValueError("miax silver: NULL trade_date -- trade_year would render as the literal "
                         "partition trade_year=nan and orphan the rows")
    out["trade_year"] = year.astype("int64")

    out = out[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "contract_month", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)

    logger.info("miax silver: %d rows, %d slug(s), %d partition(s), %s..%s",
                len(out), len(slugs), out[PARTITION_COLUMNS].drop_duplicates().shape[0],
                str(out["trade_date"].min())[:10], str(out["trade_date"].max())[:10])
    return out
