"""PRICE_AND_PLAYBOOKS W1c -- Euronext/MATIF bronze -> ``silver_futures_eod`` rows.

The bronze frame (:mod:`leviathan.transforms.raw_to_bronze.euronext_eod`) already carries the
twelve-column header pin (including the ``display: none`` Ask column), the ``md=DD-MM-YYYY``
delivery-month decode with its text cross-check, the per-product completeness floor and the ``"-"``
untraded sentinel. This module does the last mile:

  * project onto the contract's SEVENTEEN physical columns in DECLARATION ORDER plus the two
    PARTITION columns;
  * write ``unit`` / ``currency`` / ``settle_kind`` / ``source`` from
    :func:`leviathan.silver.futures_eod_contracts.contract_for` -- MAP-DERIVED, never source-parsed;
  * ``expiry_date`` stays NULL (the table publishes a delivery MONTH; an expiry date is never
    derived from one) and ``dataset`` stays NULL (it is the VENDOR dataset id).

SETTL. IS THE PRICE OF RECORD, AND IT IS THE REASON THE UNTRADED ROWS ARE KEPT
-----------------------------------------------------------------------------
``settle`` is the venue's ``Settl.`` column and ``settle_kind`` is ``settlement`` (from the map).
It prints on EVERY row -- traded expiries and quiet back months alike -- which is the whole reason
this leg publishes the deep end of the curve at all. ``Last`` is a TRADE and is never promoted into
``settle``; it lands in ``close``, which is what a session's last traded price is.

THE ``traded`` FLAG DECIDES WHICH MEASURES EXIST -- NEVER A VALUE'S BEING ZERO
-----------------------------------------------------------------------------
The venue publishes its own discriminator (``data-lasttradesdate``, whose name says "date" and
whose value is a time of day), and bronze carries it as ``traded``. Every measure that only exists
on a session that traded -- ``open`` / ``high`` / ``low`` / ``close`` / ``volume`` -- is NULLed here
wherever ``traded`` is False.

That is a SECOND guard on top of the ``"-"`` sentinel bronze already applies, and it is not
redundant belt-and-braces: the verifier's note on the capture is that a bronze row can carry
``change == 0.0`` while ``last`` is NULL, i.e. the venue prints a numerically-perfect "unchanged"
on a month that DID NOT TRADE. Zero is a real published value on this venue (an unchanged ``+/-``,
an open interest of exactly 0 on May 2029), so no value test can separate "flat" from "absent" --
only the venue's own flag can. The same fact is why the ``+/-`` column is DROPPED rather than
carried: the contract has no column for it, and a change of 0.0 on an untraded month would read
downstream as a real observation of an unchanged market. What actually happened is nothing.

``bid`` / ``ask`` are likewise dropped: a quote is not a traded or marked level and the contract
has no column for it (the JSE precedent). ``quote_time`` is a clock label, not a measure.

``open_interest`` IS written on every row, traded or not -- it is published for the quiet months
too, and a 0 there is a true observation. ``settle`` is likewise never masked.

NO DUPLICATE COLLAPSE HERE, AND THAT IS A DECISION
--------------------------------------------------
JSE and CEPEA collapse identical re-serves because their portal overwrites ONE object in place, so
the capture axis and the session axis differ. Not here: the producer lands one object per
``(product, as_of_date)`` and ``trade_date`` comes from that key, so one session is assembled from
exactly one object per product. A duplicate natural key on this leg is therefore a REAL conflict --
two different curves claiming one product-day -- and it must reach
``futures_eod_task.assert_no_duplicates`` and fail loudly rather than being quietly deduped.

Pure: pandas + the contract map. No boto3, no S3, no network, no bs4.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.raw_to_bronze.euronext_eod import EURONEXT_PRODUCT_MAP

logger = get_logger(__name__)

PHYSICAL_COLUMNS: list[str] = FC.PHYSICAL_COLUMNS
PARTITION_COLUMNS: list[str] = FC.PARTITION_COLUMNS
SILVER_COLUMNS: list[str] = FC.SILVER_COLUMNS

_EURONEXT_SLUGS: frozenset[str] = frozenset(EURONEXT_PRODUCT_MAP.values())

# The measures that exist only on a session that TRADED. Masked by the venue's own flag; see the
# module docstring for why no value test can stand in for it.
_TRADED_ONLY_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


def build_euronext_eod_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    """One or more Euronext bronze frames (already concatenated) -> the silver producer frame."""
    if bronze is None or len(bronze) == 0:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    required = {"trade_date", "leviathan_slug", "raw_symbol", "contract_month", "settle",
                "open", "high", "low", "last", "volume", "open_interest", "traded"}
    missing = sorted(required - set(bronze.columns))
    if missing:
        raise ValueError(f"euronext silver: bronze frame is missing columns {missing}")

    df = bronze.copy()
    slugs = sorted(set(df["leviathan_slug"]))
    alien = sorted(set(slugs) - _EURONEXT_SLUGS)
    if alien:
        raise ValueError(
            f"euronext silver: slug(s) {alien} are not MATIF contracts -- this leg owns exactly "
            f"the {sorted(_EURONEXT_SLUGS)} three (a fourth MATIF product is an explicit "
            f"CONTRACT_MAP decision, never something a projection infers)"
        )

    # The venue's own traded/untraded discriminator. A missing flag is read as NOT traded: the
    # conservative direction is to publish the settlement alone, never to invent a session shape.
    traded = df["traded"].fillna(False).astype(bool)

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype("datetime64[us]")
    out["contract_month"] = df["contract_month"].astype("string")
    out["instrument_kind"] = "futures"
    out["raw_symbol"] = df["raw_symbol"].astype("string")
    # SETTL., on every row including the untraded back months. NEVER the Last.
    out["settle"] = pd.to_numeric(df["settle"], errors="coerce").astype("float64")
    recs = {slug: FC.contract_for(slug) for slug in slugs}
    out["settle_kind"] = df["leviathan_slug"].map({s: r["settle_kind"] for s, r in recs.items()})
    for col in ("open", "high", "low"):
        out[col] = pd.to_numeric(df[col], errors="coerce").astype("float64").where(traded)
    # `Last` is the session's last TRADE -- that is what a close is, and it is not a settlement.
    out["close"] = pd.to_numeric(df["last"], errors="coerce").astype("float64").where(traded)
    out["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64").where(traded)
    # NOT masked: O.I is published for the quiet months too, and a 0 there is a real observation.
    out["open_interest"] = pd.to_numeric(df["open_interest"], errors="coerce").astype("Int64")
    out["unit"] = df["leviathan_slug"].map({s: r["unit"] for s, r in recs.items()})
    out["currency"] = df["leviathan_slug"].map({s: r["currency"] for s, r in recs.items()})
    out["expiry_date"] = pd.Series(pd.NaT, index=df.index).astype("datetime64[us]")
    out["source"] = df["leviathan_slug"].map({s: r["source"] for s, r in recs.items()})
    out["dataset"] = pd.Series(pd.NA, index=df.index, dtype="string")

    out["leviathan_slug"] = df["leviathan_slug"].astype("string")
    year = out["trade_date"].dt.year
    if year.isna().any():
        raise ValueError("euronext silver: NULL trade_date -- trade_year would render as the "
                         "literal partition trade_year=nan and orphan the rows")
    out["trade_year"] = year.astype("int64")

    out = out[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "contract_month", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)

    untraded = int((~traded).sum())
    logger.info("euronext silver: %d rows (%d untraded month(s) carrying a settlement and no "
                "session), %d slug(s), %d partition(s), %s..%s",
                len(out), untraded, len(slugs),
                out[PARTITION_COLUMNS].drop_duplicates().shape[0],
                str(out["trade_date"].min())[:10], str(out["trade_date"].max())[:10])
    return out
