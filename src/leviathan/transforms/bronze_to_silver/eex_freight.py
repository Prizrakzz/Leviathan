"""Silver transform for EEX dry-bulk freight settlements.

Converts a bronze EEX freight DataFrame into the tidy ``silver_eex_freight`` shape:
one row per ``(symbol, contract_month, trade_date)``.

THE TWO JUDGEMENTS THIS MODULE MAKES
------------------------------------
1. **The unit is resolved here, from the payload's own ``uOM``, and an unknown one is FATAL.**
   Measured live 2026-08-20 across every listed freight future, the venue publishes TWO units and
   not one:

       ``uOM = DAYS`` -> ``USD/day``    the time- and trip-charter averages (Panamax 5TC/P1E/P2E/
                                        P3E/P6, Supramax 10TC/11TC, Capesize 5TC and 5TC(182),
                                        Handysize 7TC). Values print in the tens of thousands.
       ``uOM = TN``   -> ``USD/tonne``  the Capesize VOYAGE routes C3 (Tubarao-Qingdao), C5
                                        (W Australia-Qingdao) and C7 (Bolivar-Rotterdam). Values
                                        print near 15-36.

   A schema that assumed "USD/day for time-charter averages" would file $35.71 as a daily hire rate
   next to $19,671 -- a plausible WRONG NUMBER with nothing downstream able to detect it. So
   :data:`_UOM_TO_UNIT_DENOMINATOR` is a closed map and an unrecognised ``uOM`` raises, exactly as
   ``usda_esr``'s ``_UNIT_TO_1000MT_FACTOR`` does for an unrecognised ``unit_id``. The ``unit``
   column is built from BOTH currency and uOM (``USD/day``, ``USD/tonne``) so a future EUR-quoted
   contract reads honestly without a code change.

   The volume column follows from the same split. Bronze carries TWO: ``volume_uom`` (quantity in
   the contract's own uOM -- days or tonnes) and ``volume_lots`` (quantity in lots). Silver
   publishes ``volume_lots`` and only ``volume_lots``, because lots are the one volume unit that
   means the same thing on a Panamax charter average and a Capesize voyage route, so the column can
   be summed and compared across the whole table without carrying a per-row unit. ``volume_uom``
   stays in bronze for anyone who needs the native figure. On the ``DAYS`` contracts the two are
   numerically identical; on ``TN`` they differ by the 1,000-tonne lot -- see the raw->bronze
   module's note on ``_VOLUME_SERIES``.

2. **The dry-bulk boundary is enforced here, in writing, not at the fetch boundary.**
   ``NON_DRY_BULK_PRODUCTS`` (today: the three LNG Route futures) is dropped with an INFO line, the
   ESR ``_NON_MASS_UNIT_CODES`` idiom. The fetcher deliberately keeps landing them, because this
   source has NO history endpoint: a boundary decision taken today and enforced at the fetch would
   destroy the option of revisiting it, permanently. Raw is source-faithful; silver is the lane.

   A frame consisting ENTIRELY of refused rows returns an EMPTY silver frame carrying the full
   column set -- the producer skips empty results, so a refused symbol contributes no partition and
   no error.

PIT
---
``trade_date`` is the venue's OWN published settlement date, carried verbatim from raw through
bronze to here. Nothing on this leg is derived from a wall clock, and the silver registry's
``knowledge_date_col`` is ``trade_date`` with ``data_date`` semantics. ``publication_lag_days`` is 0:
the settlement IS the publication.

No S3 or AWS dependencies -- pure data transformation.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.raw_to_bronze.eex_freight import (
    DRY_BULK_PRODUCTS,
    EEX_FREIGHT_SOURCE,
    NON_DRY_BULK_PRODUCTS,
)

logger = get_logger(__name__)

# The venue's ``uOM`` token -> the denominator of the published price. CLOSED: an unrecognised token
# raises rather than passing through, because a price whose unit is unknown is not a number.
_UOM_TO_UNIT_DENOMINATOR: dict[str, str] = {
    "DAYS": "day",     # a time- / trip-charter average: USD per day of hire
    "TN": "tonne",     # a voyage route: USD per tonne of cargo
}

SILVER_COLUMNS: list[str] = [
    "trade_date",
    "symbol",
    "contract_month",
    "product",
    "route",
    "settle_px",
    "currency",
    "unit",
    "volume_lots",
    "long_name",
    "source",
]

_REQUIRED_COLS: frozenset[str] = frozenset({
    "trade_date", "symbol", "product", "route", "contract_month",
    "settle_px", "currency", "uom",
})


def unit_label(currency: str, uom: str) -> str:
    """``('USD', 'DAYS')`` -> ``'USD/day'``; ``('USD', 'TN')`` -> ``'USD/tonne'``.

    Fail-closed on an unknown ``uOM``: see the module docstring. The currency is taken from the
    payload rather than assumed, so a contract the venue re-denominates reads honestly.
    """
    token = str(uom or "").strip().upper()
    denominator = _UOM_TO_UNIT_DENOMINATOR.get(token)
    if denominator is None:
        raise ValueError(
            f"eex freight: unrecognised uOM {uom!r}. This venue publishes DAYS (USD/day charter "
            f"averages) and TN (USD/tonne voyage routes); a third unit is a NEW measure and must be "
            f"decided on, never converted by assumption -- the wrong pick files a $35/tonne voyage "
            f"rate as a daily hire rate. Update _UOM_TO_UNIT_DENOMINATOR deliberately"
        )
    cur = str(currency or "").strip().upper()
    if not cur:
        raise ValueError(
            f"eex freight: uOM {uom!r} arrived with no currency. The unit is a pair; half of it is "
            f"not a unit"
        )
    return f"{cur}/{denominator}"


def transform_eex_freight_bronze_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and narrow a bronze EEX freight frame into the tidy silver shape.

    Args:
        df: Bronze EEX freight DataFrame (one row per listed maturity of one
            ``(symbol, trade_date)``), as produced by
            :func:`leviathan.transforms.raw_to_bronze.eex_freight.build_bronze`.

    Returns:
        Silver DataFrame with :data:`SILVER_COLUMNS`. Rows whose ``product`` is a written
        non-dry-bulk refusal are dropped with a log line; a frame of nothing but refused rows
        returns EMPTY with the full column set.

    Raises:
        ValueError: If required columns are absent; if a KEPT row carries an unrecognised ``uOM``
                    (unknown-unit drift stays fatal); or if a written non-dry-bulk product arrives
                    under a vessel class that is now curated as dry bulk (universe drift -- the
                    refusal has stopped describing reality and must be re-decided, not re-applied).
    """
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(
            f"eex freight bronze DataFrame is missing required column(s): {sorted(missing)}. "
            f"Got: {list(df.columns)}"
        )

    df = df.copy()
    products = df["product"].astype("string").fillna("")

    # --- Universe drift FIRST, before the skip: a product that is BOTH written off and curated is
    # a contradiction in this module's own two maps, and silently applying the refusal would hide it.
    contradiction = sorted(set(NON_DRY_BULK_PRODUCTS) & set(DRY_BULK_PRODUCTS))
    if contradiction:
        raise ValueError(
            f"eex freight: product(s) {contradiction} are declared BOTH dry bulk and non-dry-bulk. "
            f"The boundary has two authorities and they disagree -- fix the maps in "
            f"transforms/raw_to_bronze/eex_freight.py before any row is written"
        )

    refused = products.isin(list(NON_DRY_BULK_PRODUCTS)).fillna(False).to_numpy(dtype=bool)
    if refused.any():
        for product in sorted(set(products[refused])):
            logger.info(
                "eex freight silver: SKIPPING product %r (%d row(s)) -- %s",
                product, int((products == product).sum()), NON_DRY_BULK_PRODUCTS[product],
            )
        df = df.loc[~refused].reset_index(drop=True)
        products = df["product"].astype("string").fillna("")

    # An uncurated product is NOT dropped here. It reached bronze with a loud UNIVERSE DRIFT warning
    # and it is a freight future the venue lists; refusing it in silver would lose it from the only
    # table anything reads, on a source that cannot be re-fetched. It is kept, and the bronze warning
    # is the signal to classify it.
    uncurated = sorted(set(products) - DRY_BULK_PRODUCTS)
    if uncurated:
        logger.warning(
            "eex freight silver: product(s) %s are not in DRY_BULK_PRODUCTS %s and are not a "
            "written refusal -- KEPT (a freight future the venue lists, on a source with no history "
            "endpoint), but classify them",
            uncurated, sorted(DRY_BULK_PRODUCTS),
        )

    if not len(df):
        logger.info("eex freight silver: every row was a written non-dry-bulk refusal -- "
                    "returning an empty frame with the full column set")
        return pd.DataFrame(columns=SILVER_COLUMNS)

    # --- The unit, resolved per row from the payload's own currency + uOM. Vectorised over the
    # DISTINCT pairs so an unknown uOM raises once, naming itself, rather than per row.
    pairs = (
        df[["currency", "uom"]].astype("string").fillna("")
        .drop_duplicates().itertuples(index=False, name=None)
    )
    unit_by_pair = {pair: unit_label(pair[0], pair[1]) for pair in pairs}
    df["unit"] = [
        unit_by_pair[(str(c or ""), str(u or ""))]
        for c, u in zip(df["currency"].astype("string").fillna(""),
                        df["uom"].astype("string").fillna(""))
    ]

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    null_dates = int(pd.isna(df["trade_date"]).sum())
    if null_dates:
        raise ValueError(
            f"eex freight silver: {null_dates} row(s) carry an unparseable trade_date. The venue "
            f"publishes the settlement date itself, so a null here is a corrupted landed object, "
            f"never a thin session"
        )

    for col in ("settle_px", "volume_lots"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce").astype("float64")
    for col in ("symbol", "contract_month", "product", "route", "currency"):
        df[col] = df[col].astype("string").fillna("")
    df["long_name"] = df.get("long_name", pd.Series([""] * len(df))).astype("string").fillna("")
    df["source"] = EEX_FREIGHT_SOURCE

    df = (
        df[SILVER_COLUMNS]
        .sort_values(["trade_date", "symbol", "contract_month"], kind="stable")
        .reset_index(drop=True)
    )

    logger.info(
        "eex freight silver: %d row(s), %d symbol(s), trade_date %s..%s, unit(s) %s",
        len(df), df["symbol"].nunique(), df["trade_date"].min(), df["trade_date"].max(),
        sorted(set(df["unit"])),
    )
    return df
