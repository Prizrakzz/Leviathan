"""PRICE_AND_PLAYBOOKS W1a -- JSE/SAFEX bronze -> ``silver_futures_eod`` rows.

The bronze frame (:mod:`leviathan.transforms.raw_to_bronze.jse_safex`) already carries the exact
section match, the sheet's own header date, the delivery-month decode and the ``0 == no trade``
mask. This module does the last mile and nothing more -- the same shape as the CZCE and Databento
legs, deliberately:

  * project onto the contract's SEVENTEEN physical columns in DECLARATION ORDER plus the two
    PARTITION columns;
  * write ``unit`` / ``currency`` / ``settle_kind`` / ``source`` from
    :func:`leviathan.silver.futures_eod_contracts.contract_for` -- MAP-DERIVED, never source-parsed;
  * ``settle`` is the sheet's **MTM**, and ``settle_kind`` is therefore ``mark_to_market``, from the
    map. That label is the whole point of the column: the JSE number is an exchange MARK, not a
    settlement, and no prose downstream can mislabel it because the label rides the row.

TWO NULLS THAT ARE DECLARED, NOT ACCIDENTAL
-------------------------------------------
* ``open`` and ``close`` are NULL BY SOURCE. The sheet publishes
  ``Cloisng Bid | Closing Offer | MTM | VWAP | High | Low`` and there is no opening print and no
  closing trade anywhere in it. This is undeclared data loss in the upstream, recorded here so a
  later reader does not mistake the NULLs for a producer bug -- and so nobody "helpfully" fills
  ``close`` from the MTM, which would launder a mark into a trade.
* The bid/offer pair is carried through bronze for provenance and DROPPED here: a quote is not a
  traded or marked level, and the contract has no column for it.

``open_interest`` IS written, and that is load-bearing rather than nice-to-have:
``futures_roll.ROLL_METHOD_BY_SOURCE`` routes ``jse_safex -> open_interest`` on the stated ground
that the JSE publishes it, and ``front_month`` fills a missing metric with ``-1.0``, so a dropped OI
column would silently demote the roll rule to its nearest-delivery-month tie-break with no error and
no gate.

``expiry_date`` stays NULL (the sheet publishes a delivery MONTH, and an expiry date is never
derived from one) and ``dataset`` stays NULL (it is the VENDOR dataset id; ``source`` already
carries the publication channel).

THE CAPTURE AXIS IS NOT THE SESSION AXIS
----------------------------------------
The portal serves ONE object that it overwrites in place, so each fetch lands under its own
``as_of_date`` while the SESSION comes from inside the sheet. On any day the sheet is not refreshed
-- a South African public holiday, a late publish, a portal stall -- two consecutive captures carry
the SAME header date and therefore the same 18 rows, and the nightly 5-day window reads all of them.
EXACT duplicates are collapsed here (see :func:`build_jse_safex_silver`); rows that share a natural
key but differ in any value are not, and still fail loudly downstream.

Pure: pandas + the contract map. No boto3, no S3, no network.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.raw_to_bronze.jse_safex import JSE_SECTION_MAP

logger = get_logger(__name__)

PHYSICAL_COLUMNS: list[str] = FC.PHYSICAL_COLUMNS
PARTITION_COLUMNS: list[str] = FC.PARTITION_COLUMNS
SILVER_COLUMNS: list[str] = FC.SILVER_COLUMNS

_JSE_SLUGS: frozenset[str] = frozenset(JSE_SECTION_MAP.values())


def build_jse_safex_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    """One or more JSE bronze frames (already concatenated) -> the silver producer frame."""
    if bronze is None or len(bronze) == 0:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    required = {"trade_date", "leviathan_slug", "raw_symbol", "contract_month",
                "mtm", "high", "low", "volume", "open_interest"}
    missing = sorted(required - set(bronze.columns))
    if missing:
        raise ValueError(f"jse silver: bronze frame is missing columns {missing}")

    df = bronze.copy()
    slugs = sorted(set(df["leviathan_slug"]))
    alien = sorted(set(slugs) - _JSE_SLUGS)
    if alien:
        raise ValueError(
            f"jse silver: slug(s) {alien} are not JSE contracts -- this leg owns exactly the "
            f"{sorted(_JSE_SLUGS)} pair (the GRADE 2 sections are a DIFFERENT deliverable and are "
            f"rejected in the bronze transform, by exact match)"
        )

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype("datetime64[us]")
    out["contract_month"] = df["contract_month"].astype("string")
    out["instrument_kind"] = "futures"
    out["raw_symbol"] = df["raw_symbol"].astype("string")
    out["settle"] = pd.to_numeric(df["mtm"], errors="coerce").astype("float64")
    recs = {slug: FC.contract_for(slug) for slug in slugs}
    out["settle_kind"] = df["leviathan_slug"].map({s: r["settle_kind"] for s, r in recs.items()})
    # NULL BY SOURCE, both of them. See the module docstring -- the sheet has no open and no close.
    out["open"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    out["high"] = pd.to_numeric(df["high"], errors="coerce").astype("float64")
    out["low"] = pd.to_numeric(df["low"], errors="coerce").astype("float64")
    out["close"] = pd.Series(float("nan"), index=df.index, dtype="float64")
    out["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")
    out["open_interest"] = pd.to_numeric(df["open_interest"], errors="coerce").astype("Int64")
    out["unit"] = df["leviathan_slug"].map({s: r["unit"] for s, r in recs.items()})
    out["currency"] = df["leviathan_slug"].map({s: r["currency"] for s, r in recs.items()})
    out["expiry_date"] = pd.Series(pd.NaT, index=df.index).astype("datetime64[us]")
    out["source"] = df["leviathan_slug"].map({s: r["source"] for s, r in recs.items()})
    out["dataset"] = pd.Series(pd.NA, index=df.index, dtype="string")

    out["leviathan_slug"] = df["leviathan_slug"].astype("string")
    year = out["trade_date"].dt.year
    if year.isna().any():
        raise ValueError("jse silver: NULL trade_date -- trade_year would render as the literal "
                         "partition trade_year=nan and orphan the rows")
    out["trade_year"] = year.astype("int64")

    # THE OVERWRITTEN-OBJECT COLLAPSE. The portal serves ONE object that is overwritten in place,
    # and every fetch lands under its own as_of_date -- so the CAPTURE axis and the SESSION axis are
    # different, and on any day the sheet is not refreshed (a South African public holiday, a late
    # publish, a portal stall) two consecutive captures carry the SAME header date and therefore the
    # SAME 18 rows. A 5-day incremental window reads all of them, and without this the assembled
    # frame carries 18 duplicate NATURAL KEYS -- which `futures_eod_task.assert_no_duplicates` hard
    # fails, nightly, while reporting it as "the F2 double bar survived the ICE_BAR_RULE dedupe":
    # a false diagnosis of an ICE defect on a South African maize frame.
    #
    # So EXACT duplicates -- identical on all 19 columns, which is what re-reading one unchanged
    # sheet produces -- are collapsed HERE, where the fact is local. This is the same call the CEPEA
    # leg makes for the widget's holiday re-serve, and it is deliberately the NARROW form: rows that
    # share a natural key but DIFFER in any value (a revised MTM, a corrected volume) are left
    # standing and still fail loudly downstream, because that is a real conflict and not a re-read.
    before = len(out)
    out = out.drop_duplicates(keep="last")
    collapsed = before - len(out)

    out = out[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "contract_month", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)

    if collapsed:
        # Name the diagnosis in the log rather than leaving the operator a bare count: this is the
        # normal, expected shape on a JSE non-publication day, NOT a defect and NOT data loss.
        logger.info("jse silver: %d row(s) were an IDENTICAL RE-SERVE of an already-parsed session "
                    "(the portal overwrites ONE object, so a non-publication day re-serves the "
                    "previous sheet) -- collapsed as a no-op; a CHANGED value at the same natural "
                    "key is NOT collapsed and still hard-fails downstream", collapsed)
    logger.info("jse silver: %d rows (%d re-captured duplicate(s) collapsed), %d slug(s), "
                "%d partition(s), %s..%s",
                len(out), collapsed, len(slugs),
                out[PARTITION_COLUMNS].drop_duplicates().shape[0],
                str(out["trade_date"].min())[:10], str(out["trade_date"].max())[:10])
    return out
