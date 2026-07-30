"""PRICE_AND_PLAYBOOKS W1c -- Bursa Malaysia FCPO bronze -> ``silver_futures_eod`` rows.

The bronze frame (:mod:`leviathan.transforms.raw_to_bronze.bursa_fcpo`) already carries the
rendered-``thead`` pin over the API's 13 anonymous positional elements, the embedded-HTML decode of
the three cells that are not plain strings, the ``recordsTotal == len(data)`` completeness check,
the ``ses=day`` session guard and the ``"-"`` untraded sentinel. This module does the last mile:

  * project onto the contract's SEVENTEEN physical columns in DECLARATION ORDER plus the two
    PARTITION columns;
  * write ``unit`` / ``currency`` / ``settle_kind`` / ``source`` from
    :func:`leviathan.silver.futures_eod_contracts.contract_for` -- MAP-DERIVED, never source-parsed.
    ``unit`` is ``MYR/t`` and the number is NEVER scaled or FX-ed at ingest;
  * ``expiry_date`` stays NULL (never derived from a delivery month) and ``dataset`` stays NULL.

ONE SLUG, TWENTY-FOUR DELIVERY MONTHS, AND ``raw_symbol`` IS THE MONTH
---------------------------------------------------------------------
The API's NAME cell is the constant string ``FCPO`` on all 24 rows, so the MONTH cell
(``"Aug 2026"``) is what bronze carries verbatim as ``raw_symbol`` -- the JSE expiry-cell
precedent. That is load-bearing here rather than cosmetic: the F2 uniqueness key is
``(leviathan_slug, trade_date, raw_symbol)``, and a constant symbol collapses the whole curve onto
ONE key. This projection passes it through unchanged and parses nothing further out of it.

SETT. PRICE IS THE PRICE OF RECORD; LAST DONE IS A TRADE
--------------------------------------------------------
``settle`` is the venue's ``SETT. PRICE`` and ``settle_kind`` is ``settlement`` (from the map). It
prints for all 24 months, the ten quiet back months included, which is why those rows are worth
publishing at all. ``LAST DONE`` is the session's last trade and lands in ``close``; the two are
never substituted for one another in either direction.

``bid`` / ``ask`` are dropped -- a quote is not a traded or marked level and the contract has no
column for it (the JSE precedent). ``CHANGE`` is dropped too: no contract column, and on a venue
whose quiet months print ``"-"`` for every traded field it adds nothing the settlement does not
already say.

THE QUIET-MONTH DISCRIMINATOR IS THE SENTINEL, NOT A FLAG
---------------------------------------------------------
Unlike Euronext, this venue publishes no traded/untraded attribute: a month that did not trade
prints ``"-"`` in every traded cell, which bronze has already turned into NULL. So there is no mask
to apply here, and -- importantly -- ``volume`` on a quiet month is NULL and never 0. Zero would be
a count this leg invented; the venue said nothing, and nothing is what is published.

FORWARD ACCUMULATION, SO NO DUPLICATE COLLAPSE
----------------------------------------------
The API serves current prices only -- no date parameter exists on it and the body carries no date
field -- so ``trade_date`` comes from the raw key's ``as_of_date=`` segment and one session is
assembled from exactly one landed object. There is no overwritten-in-place portal object (JSE) and
no history/daily overlap (DCE, CEPEA) to collapse. A duplicate natural key on this leg is therefore
a REAL conflict and must reach ``futures_eod_task.assert_no_duplicates`` and fail loudly.

Pure: pandas + the contract map. No boto3, no S3, no network.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.raw_to_bronze.bursa_fcpo import BURSA_CODE_MAP

logger = get_logger(__name__)

PHYSICAL_COLUMNS: list[str] = FC.PHYSICAL_COLUMNS
PARTITION_COLUMNS: list[str] = FC.PARTITION_COLUMNS
SILVER_COLUMNS: list[str] = FC.SILVER_COLUMNS

_BURSA_SLUGS: frozenset[str] = frozenset(BURSA_CODE_MAP.values())


def build_bursa_fcpo_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    """One or more Bursa bronze frames (already concatenated) -> the silver producer frame."""
    if bronze is None or len(bronze) == 0:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    required = {"trade_date", "leviathan_slug", "raw_symbol", "contract_month", "settle",
                "open", "high", "low", "last", "volume", "open_interest"}
    missing = sorted(required - set(bronze.columns))
    if missing:
        raise ValueError(f"bursa silver: bronze frame is missing columns {missing}")

    df = bronze.copy()
    slugs = sorted(set(df["leviathan_slug"]))
    alien = sorted(set(slugs) - _BURSA_SLUGS)
    if alien:
        raise ValueError(
            f"bursa silver: slug(s) {alien} are not Bursa contracts -- this leg owns exactly "
            f"{sorted(_BURSA_SLUGS)} (FPKO / FSOY / FEPO / FPOL are on the venue's selector and "
            f"are each a future CONTRACT_MAP decision)"
        )

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype("datetime64[us]")
    out["contract_month"] = df["contract_month"].astype("string")
    out["instrument_kind"] = "futures"
    # The MONTH cell, verbatim from bronze. NAME is the constant "FCPO" and would collapse the F2
    # key onto one row -- see the module docstring.
    out["raw_symbol"] = df["raw_symbol"].astype("string")
    # SETT. PRICE, on all 24 months. NEVER LAST DONE.
    out["settle"] = pd.to_numeric(df["settle"], errors="coerce").astype("float64")
    recs = {slug: FC.contract_for(slug) for slug in slugs}
    out["settle_kind"] = df["leviathan_slug"].map({s: r["settle_kind"] for s, r in recs.items()})
    for col in ("open", "high", "low"):
        out[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    # LAST DONE -- the session's last trade, which is what a close is.
    out["close"] = pd.to_numeric(df["last"], errors="coerce").astype("float64")
    # NULL, not 0, on a quiet month: the venue printed "-" and this leg invents no counts.
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
        raise ValueError("bursa silver: NULL trade_date -- trade_year would render as the literal "
                         "partition trade_year=nan and orphan the rows")
    out["trade_year"] = year.astype("int64")

    out = out[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "contract_month", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)

    quiet = int(out["volume"].isna().sum())
    logger.info("bursa silver: %d rows (%d quiet month(s) carrying a settlement and no session), "
                "%d slug(s), %d partition(s), %s..%s",
                len(out), quiet, len(slugs),
                out[PARTITION_COLUMNS].drop_duplicates().shape[0],
                str(out["trade_date"].min())[:10], str(out["trade_date"].max())[:10])
    return out
