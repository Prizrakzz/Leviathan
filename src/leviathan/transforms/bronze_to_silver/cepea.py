"""PRICE_AND_PLAYBOOKS W1a -- CEPEA bronze -> ``silver_futures_eod`` rows (the CASH references).

This is the one leg in the table whose rows are NOT futures, and every difference follows from
that single fact:

  * ``instrument_kind = 'cash_index'`` and ``contract_month`` is **NULL**. These two slugs are
    exactly ``futures_eod_contracts.CASH_INDEX_SLUGS``, and ``lint_frame`` enforces the iff in
    BOTH directions -- a futures row with a null month and a cash row with a month are equally
    rejected. That rule is load-bearing rather than tidy: ``contract_month`` is part of the natural
    key ``(leviathan_slug, contract_month, trade_date)``, so N rows with a null month collapse to
    ONE key and the contract's ``duplicate_check: full`` cannot see it, because SQL treats every
    NULL as distinct;
  * ``settle_kind = 'cash_index'`` (map-derived) -- the honesty label. This number is a published
    spot reference, not an exchange settlement and not a mark;
  * ``raw_symbol`` is **NULL**. There is no vendor contract symbol for a cash index, and inventing
    a synthetic one would violate the registry's "raw_symbol is verbatim and is NEVER parsed into
    meaning at ingest" note in the opposite direction. NOTE the consequence, which is handled in
    ``jobs/batch/futures_eod_task.py`` rather than here: the F2 assertion groups on
    ``(leviathan_slug, trade_date, raw_symbol)`` precisely so that two NULL-symbol cash rows on one
    date -- arabica and Campinas corn -- are not read as a duplicate;
  * OHLC, ``volume`` and ``open_interest`` are all NULL BY SOURCE: a cash reference publishes one
    number per day and nothing else. ``settle`` carries it;
  * ``futures_roll.ROLL_METHOD_BY_SOURCE`` routes ``cepea -> none`` and ``front_month`` DROPS these
    rows rather than passing them through -- naming a front month for a cash index is a category
    error, and that is decided there, not here.

SOURCE FIDELITY: the value is the published ``A vista R$`` figure, in BRL per 60-kg bag, unscaled
and unconverted. The archive workbook's ``A vista US$`` column is discarded upstream in the bronze
transform and never appears here in any form.

Pure: pandas + the contract map. No boto3, no S3, no network.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.raw_to_bronze.cepea import CEPEA_INDICATORS

logger = get_logger(__name__)

PHYSICAL_COLUMNS: list[str] = FC.PHYSICAL_COLUMNS
PARTITION_COLUMNS: list[str] = FC.PARTITION_COLUMNS
SILVER_COLUMNS: list[str] = FC.SILVER_COLUMNS

_CEPEA_SLUGS: frozenset[str] = frozenset(CEPEA_INDICATORS.values())


def build_cepea_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    """One or more CEPEA bronze frames (already concatenated) -> the silver producer frame."""
    if bronze is None or len(bronze) == 0:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    required = {"trade_date", "leviathan_slug", "value_brl"}
    missing = sorted(required - set(bronze.columns))
    if missing:
        raise ValueError(f"cepea silver: bronze frame is missing columns {missing}")

    df = bronze.copy()
    slugs = sorted(set(df["leviathan_slug"]))
    alien = sorted(set(slugs) - _CEPEA_SLUGS)
    if alien:
        raise ValueError(
            f"cepea silver: slug(s) {alien} are not CEPEA cash references -- this leg owns exactly "
            f"the {sorted(_CEPEA_SLUGS)} pair, which is also the ONLY pair permitted a NULL "
            f"contract_month"
        )

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype("datetime64[us]")
    # NULL, and mandatory: the cash-index half of lint_frame's iff.
    out["contract_month"] = pd.Series(pd.NA, index=df.index, dtype="string")
    out["instrument_kind"] = "cash_index"
    # NULL, and deliberate: a cash reference has no vendor contract symbol to carry verbatim.
    out["raw_symbol"] = pd.Series(pd.NA, index=df.index, dtype="string")
    out["settle"] = pd.to_numeric(df["value_brl"], errors="coerce").astype("float64")
    recs = {slug: FC.contract_for(slug) for slug in slugs}
    out["settle_kind"] = df["leviathan_slug"].map({s: r["settle_kind"] for s, r in recs.items()})
    # NULL BY SOURCE: one published number per day, no session shape and no book behind it.
    for col in ("open", "high", "low", "close"):
        out[col] = pd.Series(float("nan"), index=df.index, dtype="float64")
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
        raise ValueError("cepea silver: NULL trade_date -- trade_year would render as the literal "
                         "partition trade_year=nan and orphan the rows")
    out["trade_year"] = year.astype("int64")

    # A cash reference publishes at most ONE value per slug per day. The widget re-serves the last
    # value on a holiday, and a backfill that re-reads the same snapshot would otherwise stack
    # exact duplicates -- both of which the natural-key assertion downstream would turn into a
    # hard fail with a confusing diagnosis. Identical rows are collapsed HERE, where the fact is
    # local; a genuine CONFLICT (two different values for one slug-day) is left to fail loudly.
    before = len(out)
    out = out.drop_duplicates(subset=["leviathan_slug", "trade_date", "settle"], keep="last")
    collapsed = before - len(out)

    out = out[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "trade_date"], kind="mergesort").reset_index(drop=True)

    logger.info("cepea silver: %d rows (%d identical duplicate(s) collapsed), %d slug(s), %s..%s",
                len(out), collapsed, len(slugs),
                str(out["trade_date"].min())[:10], str(out["trade_date"].max())[:10])
    return out
