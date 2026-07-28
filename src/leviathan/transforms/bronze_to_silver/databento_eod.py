"""PRICE_AND_PLAYBOOKS W2 -- Databento bronze -> ``silver_futures_eod`` rows.

The bronze frame (:mod:`leviathan.transforms.raw_to_bronze.databento_eod`) already carries the
decoded delivery month, the scaled prices, the GLBX statistics join and the ICE dedupe. This module
does the LAST mile and nothing more:

  * project onto the F010 contract's SEVENTEEN physical columns, in DECLARATION ORDER (declaration
    order IS writer order for the INV-2 pinned schema), plus the two PARTITION columns
    ``leviathan_slug`` / ``trade_year`` that live in the PATH and are dropped from the body by
    ``build_partition_objects``;
  * write ``unit`` / ``currency`` / ``settle_kind`` / ``source`` from
    :func:`leviathan.silver.futures_eod_contracts.contract_for` -- MAP-DERIVED, never source-parsed,
    never a local copy. ``lint_frame`` compares them back against ``CONTRACT_MAP`` verbatim and
    fails the whole stage on drift, so a guessed unit cannot survive to S3;
  * set ``instrument_kind='futures'`` with a NON-NULL ``contract_month`` on every row. None of the
    15 Databento contracts is a cash reference (``CASH_INDEX_SLUGS`` is the two CEPEA slugs), and a
    NULL month on a futures row collapses N natural keys to one, which ``duplicate_check`` cannot
    see because SQL treats each NULL as distinct;
  * leave ``expiry_date`` NULL -- it is recorded only where PUBLISHED and is NEVER derived from the
    delivery month (registry notes, W1.0);
  * derive ``trade_year`` as a real ``int``: pandas widens any column that has ever held a NaN to
    float64, and ``partition_value_str`` refuses ``2026.0`` against an ``int`` Glue key rather than
    silently truncating.

Pure: pandas + the contract map. No boto3, no S3, no vendor package.
"""
from __future__ import annotations

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC
from leviathan.transforms.raw_to_bronze.databento_eod import DATASET_SLUGS, ROOT_MAP

logger = get_logger(__name__)

# The F010 contract's physical column order, verbatim from configs/silver/tables/
# silver_futures_eod.yaml (declaration order IS writer order under the INV-2 pinned schema).
PHYSICAL_COLUMNS: list[str] = [
    "trade_date", "contract_month", "instrument_kind", "raw_symbol", "settle", "settle_kind",
    "open", "high", "low", "close", "volume", "open_interest", "unit", "currency",
    "expiry_date", "source", "dataset",
]
# The two registered partition keys, in the contract's declared ORDER (Glue keys partitions
# positionally, so a transposed pair is silent at write time and unrecoverable afterwards).
PARTITION_COLUMNS: list[str] = ["leviathan_slug", "trade_year"]
SILVER_COLUMNS: list[str] = PHYSICAL_COLUMNS + PARTITION_COLUMNS


def build_databento_eod_silver(bronze: pd.DataFrame) -> pd.DataFrame:
    """One or more bronze frames (already concatenated) -> the silver producer frame.

    The frame this returns is what goes straight into
    ``build_partitioned_publish(df=..., row_validator=FC.lint_frame)``."""
    if bronze is None or len(bronze) == 0:
        return pd.DataFrame(columns=SILVER_COLUMNS)

    required = {"trade_date", "leviathan_slug", "raw_symbol", "contract_month",
                "open", "high", "low", "close", "volume", "settle", "open_interest", "dataset"}
    missing = sorted(required - set(bronze.columns))
    if missing:
        raise ValueError(f"databento silver: bronze frame is missing columns {missing}")

    df = bronze.copy()
    slugs = sorted(set(df["leviathan_slug"]))
    databento_slugs = {slug for _root, (_ds, slug) in ROOT_MAP.items()}
    alien = sorted(set(slugs) - databento_slugs)
    if alien:
        raise ValueError(
            f"databento silver: slug(s) {alien} are not Databento-covered contracts -- W2 owns "
            f"exactly the 15 ROOT_MAP slugs; the other 16 are W1a/W1b/W1c legs"
        )
    bad_dataset = sorted({d for d in df["dataset"].dropna().unique() if d not in DATASET_SLUGS})
    if bad_dataset:
        raise ValueError(f"databento silver: unknown dataset id(s) {bad_dataset}")

    out = pd.DataFrame(index=df.index)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").astype("datetime64[us]")
    out["contract_month"] = df["contract_month"].astype("string")
    # Not one of the 15 is a cash reference, so instrument_kind is a constant here and
    # contract_month must be non-null on every row (lint_frame invariant 1, both directions).
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
    # NEVER derived from contract_month: expiry is recorded only where the venue publishes it, and
    # Databento's ohlcv-1d / statistics payloads do not carry one.
    out["expiry_date"] = pd.Series(pd.NaT, index=df.index).astype("datetime64[us]")
    out["source"] = df["leviathan_slug"].map({s: r["source"] for s, r in recs.items()})
    out["dataset"] = df["dataset"].astype("string")

    out["leviathan_slug"] = df["leviathan_slug"].astype("string")
    # A REAL int: partition_value_str refuses 2026.0 against an int Glue key.
    year = out["trade_date"].dt.year
    if year.isna().any():
        raise ValueError("databento silver: NULL trade_date -- trade_year would render as the "
                         "literal partition trade_year=nan and orphan the rows")
    out["trade_year"] = year.astype("int64")

    out = out[SILVER_COLUMNS].sort_values(
        ["leviathan_slug", "trade_year", "contract_month", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)

    logger.info("databento silver: %d rows, %d slug(s), %d partition(s), %s..%s",
                len(out), len(slugs),
                out[PARTITION_COLUMNS].drop_duplicates().shape[0],
                str(out["trade_date"].min())[:10], str(out["trade_date"].max())[:10])
    return out
