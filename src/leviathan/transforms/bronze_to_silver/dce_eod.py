"""PRICE_AND_PLAYBOOKS W1c -- DCE (Dalian) bronze -> ``silver_futures_eod`` rows.

The bronze frame (:mod:`leviathan.transforms.raw_to_bronze.dce_eod`) already carries the two
parsers, the session-anchored ``YYMM`` delivery-month decode, the NOT_READY refusal and the ``0``
undefined-price sentinel (masked to NULL there, per cell, never here). This module does the last
mile -- the same shape as the CZCE leg, deliberately, since both Chinese venues emit the same
bronze column list:

  * project onto the contract's SEVENTEEN physical columns in DECLARATION ORDER plus the two
    PARTITION columns ``leviathan_slug`` / ``trade_year``;
  * write ``unit`` / ``currency`` / ``settle_kind`` / ``source`` from
    :func:`leviathan.silver.futures_eod_contracts.contract_for` -- MAP-DERIVED, never source-parsed
    and never a local copy;
  * ``settle`` is the venue's own settlement (``settlePrice`` on the daily API, the 9th history
    column) and ``settle_kind`` is therefore ``settlement``, from the map. The session close stays
    in ``close`` and is NEVER substituted into ``settle``, in either direction;
  * ``instrument_kind='futures'`` with a NON-NULL ``contract_month`` on every row -- no DCE slug is
    a cash reference, and a NULL month on a futures row collapses N natural keys to one, which
    ``duplicate_check`` cannot see because SQL treats each NULL as distinct;
  * ``expiry_date`` stays NULL (never derived from a delivery month) and ``dataset`` stays NULL (it
    is the VENDOR dataset id; ``source`` already carries the publication channel).

TWO PAYLOAD KINDS, ONE SERIES PER SLUG -- AND WHERE THEY MEET
-------------------------------------------------------------
This is the only leg whose bronze arrives from two different wire formats: the daily quote JSON
(forward, post-close) and the per-``(variety, year)`` history workbook (the backfill). Both already
emit the SAME frame, so there is nothing to reconcile shape-wise -- but they OVERLAP in time by
construction, because the workbook covers the whole calendar year INCLUDING sessions the daily
capture has already landed. One contract-session can therefore arrive twice.

``futures_eod_task.dce_units`` orders HISTORY FIRST and the daily captures LAST (the CEPEA
ordering precedent), and the rule here is the JSE one, narrow on purpose:

  * rows IDENTICAL on all nineteen columns are collapsed keeping the LAST -- that is the same
    observation read twice, and the ordering above means the survivor is the fresher post-close
    capture;
  * a row that shares a natural key but DIFFERS in any value -- a REVISED settlement, a corrected
    volume -- is NOT collapsed. It survives as two rows and the task's ``assert_no_duplicates``
    hard-fails the run. That is deliberate: a revision is a real conflict, and silently picking the
    daily row (or the workbook's) would publish one of two disagreeing numbers with no trace. The
    rule is wrong, not the data.

THE COLLAPSE HAPPENS AFTER THE PROJECTION, AND THAT IS LOAD-BEARING. The daily endpoint publishes
no turnover and no open-interest change (NULL by source in bronze) while the workbook publishes
both -- and NEITHER is a contract column. Comparing BRONZE rows would therefore read every single
overlapping session as a value conflict and hard-fail the first backfill that met the forward feed.
Compared on what is actually published, the two kinds agree cell for cell on an unrevised session.

THREE BRONZE COLUMNS ARE DROPPED, NOT LOST
------------------------------------------
``prev_settle``, ``oi_change`` and ``turnover`` have no column in this contract. ``prev_settle`` is
the PRIOR session's settlement and is already present as its own row, so carrying it forward would
double-count on any aggregation (the MIAX ``Prev_Settle`` precedent); the other two are venue
statistics the schema does not model. They stay in bronze for provenance.

Pure: pandas + the contract map. No boto3, no S3, no network.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.raw_to_bronze.dce_eod import DCE_VARIETY_MAP

logger = get_logger(__name__)

PHYSICAL_COLUMNS: list[str] = FC.PHYSICAL_COLUMNS
PARTITION_COLUMNS: list[str] = FC.PARTITION_COLUMNS
SILVER_COLUMNS: list[str] = FC.SILVER_COLUMNS

_DCE_SLUGS: frozenset[str] = frozenset(DCE_VARIETY_MAP.values())


def build_dce_eod_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    """One or more DCE bronze frames (already concatenated) -> the silver producer frame.

    What this returns goes straight into
    ``build_partitioned_publish(df=..., row_validator=FC.lint_frame)``."""
    if bronze is None or len(bronze) == 0:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    required = {"trade_date", "leviathan_slug", "raw_symbol", "contract_month",
                "open", "high", "low", "close", "settle", "volume", "open_interest"}
    missing = sorted(required - set(bronze.columns))
    if missing:
        raise ValueError(f"dce silver: bronze frame is missing columns {missing}")

    df = bronze.copy()
    slugs = sorted(set(df["leviathan_slug"]))
    alien = sorted(set(slugs) - _DCE_SLUGS)
    if alien:
        raise ValueError(
            f"dce silver: slug(s) {alien} are not DCE contracts -- this leg owns exactly the five "
            f"{sorted(_DCE_SLUGS)} (the raw key's variety letter decides the slug, never the "
            f"Chinese commodity name inside the payload)"
        )

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype("datetime64[us]")
    out["contract_month"] = df["contract_month"].astype("string")
    out["instrument_kind"] = "futures"
    out["raw_symbol"] = df["raw_symbol"].astype("string")
    # The venue's SETTLEMENT field. Never the close, in either direction.
    out["settle"] = pd.to_numeric(df["settle"], errors="coerce").astype("float64")
    # unit / currency / settle_kind / source are MAP-DERIVED, one lookup per slug (not per row).
    recs = {slug: FC.contract_for(slug) for slug in slugs}
    out["settle_kind"] = df["leviathan_slug"].map({s: r["settle_kind"] for s, r in recs.items()})
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    # Counts, both published by both payload kinds. A ZERO here is a true observation (the contract
    # did not trade) and was never touched by the bronze price-sentinel mask.
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
        raise ValueError("dce silver: NULL trade_date -- trade_year would render as the literal "
                         "partition trade_year=nan and orphan the rows")
    out["trade_year"] = year.astype("int64")

    # THE TWO-PAYLOAD SEAM. See the module docstring: identical rows are the same session read
    # twice (the history workbook covers days the daily capture already landed), a DIFFERING pair
    # at one natural key is a revision and must reach assert_no_duplicates and fail loudly.
    before = len(out)
    out = out.drop_duplicates(keep="last")
    collapsed = before - len(out)

    out = out[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "contract_month", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)

    if collapsed:
        logger.info("dce silver: %d row(s) were the SAME contract-session read from BOTH payload "
                    "kinds (the history workbook overlaps the daily captures by construction) -- "
                    "collapsed as a no-op; a REVISED value at one natural key is NOT collapsed and "
                    "still hard-fails downstream", collapsed)
    logger.info("dce silver: %d rows (%d overlapping duplicate(s) collapsed), %d slug(s), "
                "%d partition(s), %s..%s",
                len(out), collapsed, len(slugs),
                out[PARTITION_COLUMNS].drop_duplicates().shape[0],
                str(out["trade_date"].min())[:10], str(out["trade_date"].max())[:10])
    return out
