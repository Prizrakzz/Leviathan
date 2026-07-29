"""PRICE_AND_PLAYBOOKS W1a -- CZCE bronze -> ``silver_futures_eod`` rows.

The bronze frame (:mod:`leviathan.transforms.raw_to_bronze.czce_eod`) already carries the positional
decode, the file-date-anchored delivery month and the no-session sentinel masking. This module does
the LAST mile and nothing more -- the same shape as the Databento leg, deliberately:

  * project onto the contract's SEVENTEEN physical columns in DECLARATION ORDER plus the two
    PARTITION columns ``leviathan_slug`` / ``trade_year`` (which live in the PATH and are dropped
    from the body by ``build_partition_objects``);
  * write ``unit`` / ``currency`` / ``settle_kind`` / ``source`` from
    :func:`leviathan.silver.futures_eod_contracts.contract_for` -- MAP-DERIVED, never source-parsed
    and never a local copy. ``lint_frame`` compares them back against ``CONTRACT_MAP`` verbatim, so
    a guessed unit cannot reach S3;
  * ``settle`` is the file's SETTLEMENT column and ``settle_kind`` is therefore ``settlement`` (from
    the map, not from here). The session close stays in ``close`` and is never substituted;
  * ``instrument_kind='futures'`` with a NON-NULL ``contract_month`` on every row -- neither CZCE
    slug is a cash reference, and a NULL month on a futures row collapses N natural keys to one,
    which ``duplicate_check`` cannot see because SQL treats each NULL as distinct;
  * ``expiry_date`` stays NULL: CZCE's daily file does not publish one, and it is NEVER derived
    from the delivery month;
  * ``dataset`` stays NULL: it is the VENDOR dataset id (``GLBX.MDP3``) and has no meaning for a
    venue-published file. ``source`` already carries the channel, and writing the venue name twice
    invites a two-way drift with nothing binding the pair.

Pure: pandas + the contract map. No boto3, no S3, no network.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.raw_to_bronze.czce_eod import CZCE_ROOT_MAP

logger = get_logger(__name__)

PHYSICAL_COLUMNS: list[str] = FC.PHYSICAL_COLUMNS
PARTITION_COLUMNS: list[str] = FC.PARTITION_COLUMNS
SILVER_COLUMNS: list[str] = FC.SILVER_COLUMNS

_CZCE_SLUGS: frozenset[str] = frozenset(CZCE_ROOT_MAP.values())


def build_czce_eod_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    """One or more CZCE bronze frames (already concatenated) -> the silver producer frame.

    What this returns goes straight into
    ``build_partitioned_publish(df=..., row_validator=FC.lint_frame)``."""
    if bronze is None or len(bronze) == 0:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    required = {"trade_date", "leviathan_slug", "raw_symbol", "contract_month",
                "open", "high", "low", "close", "volume", "settle", "open_interest"}
    missing = sorted(required - set(bronze.columns))
    if missing:
        raise ValueError(f"czce silver: bronze frame is missing columns {missing}")

    df = bronze.copy()
    slugs = sorted(set(df["leviathan_slug"]))
    alien = sorted(set(slugs) - _CZCE_SLUGS)
    if alien:
        raise ValueError(
            f"czce silver: slug(s) {alien} are not CZCE contracts -- this leg owns exactly the "
            f"{sorted(_CZCE_SLUGS)} pair (RM = rapeseed meal, OI = rapeseed OIL, never cotton)"
        )

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype("datetime64[us]")
    out["contract_month"] = df["contract_month"].astype("string")
    out["instrument_kind"] = "futures"
    out["raw_symbol"] = df["raw_symbol"].astype("string")
    out["settle"] = pd.to_numeric(df["settle"], errors="coerce").astype("float64")
    # unit / currency / settle_kind / source are MAP-DERIVED, one lookup per slug (not per row).
    recs = {slug: FC.contract_for(slug) for slug in slugs}
    out["settle_kind"] = df["leviathan_slug"].map({s: r["settle_kind"] for s, r in recs.items()})
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
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
        raise ValueError("czce silver: NULL trade_date -- trade_year would render as the literal "
                         "partition trade_year=nan and orphan the rows")
    out["trade_year"] = year.astype("int64")

    out = out[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "contract_month", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)

    logger.info("czce silver: %d rows, %d slug(s), %d partition(s), %s..%s",
                len(out), len(slugs), out[PARTITION_COLUMNS].drop_duplicates().shape[0],
                str(out["trade_date"].min())[:10], str(out["trade_date"].max())[:10])
    return out
