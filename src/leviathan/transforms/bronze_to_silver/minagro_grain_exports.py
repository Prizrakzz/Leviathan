"""MINAGRO Ukrainian grain / pulse / flour exports: bronze -> silver (silver_minagro_grain_exports).

Grain: ``as_of_date x crop_slug``. Consumes the tidy bronze frames produced by
``raw_to_bronze/minagro_grain_exports.build_bronze`` -- one frame per landed capture -- and projects
them onto the SILVER-F010 contract. Pure + AWS-free: no boto3, no network, no browser. The batch
task (not built in this wave -- see the producer's ``prepared_commands``) wires the raw reader and
the SILVER-F015 flat publisher; this module is only the transform.

THE PIT ANCHOR IS THE TABLE'S OWN 'СТАНОМ НА' DATE
---------------------------------------------------
``as_of_date`` is the date the State Customs figures describe, read out of the header paragraph
above the table ("тис. тонн станом на 14.08.2026"), and it is the table's ``knowledge_date_col``
with ``knowledge_semantics: data_date``. It is NOT the CMS publish stamp, which the page also
carries ("Опубліковано 14 серпня 2026 року, 09:05") and which bronze keeps for provenance only.

This is the D-LD derived-date rule applied to a source that, unusually, states its own anchor: the
mpoc/sagis/conab pre-steps had to DERIVE a period-end date because the table carried none, and the
governing sentence there was "the publication guess belongs in the card's ``publication_lag_days``,
where it is auditable and tunable, not baked irreversibly into the data". Here the ministry prints
the anchor itself, so nothing is derived at all -- but the same choice has to be made explicitly,
because the page offers a SECOND date that looks like an answer. The publish stamp runs at or after
the as-of instant (customs figures cannot be published before the day they describe closes), it
moves whenever the CMS re-publishes the page -- which this standing slug does, in place, roughly
weekly -- and keying on it would mint a fresh, later "vintage" of numbers that never changed.
``as_of_date`` is one date, declared by the data, and it is the same date in the raw key
(``as_of=YYYYMMDD``), in bronze and here. The publication lag is carried on the CARD as
``publication_lag_days`` when a card is eventually minted, never in this column.

WHY THE PRIOR MARKETING YEAR RIDES EVERY ROW
--------------------------------------------
Two of the four measures (``prior_my_cumulative_kt`` / ``prior_my_month_kt``) belong to the PREVIOUS
marketing year, and the table states which one it is in its own column-group header. Carrying
``prior_marketing_year`` explicitly costs one string column and removes the alternative -- a
downstream consumer doing string arithmetic on ``marketing_year`` to work out which season those two
numbers describe, which is exactly the kind of re-derivation this estate refuses. The raw_to_bronze
pin already refuses a page whose two column groups are not consecutive-and-descending, so the pair
is always internally consistent.

LATEST-ONLY, AND WHY THAT IS NOT A LOSS
----------------------------------------
``write_mode: overwrite`` / ``vintage_retention: latest-only``: the silver object is rewritten in
full from every landed capture, so it holds ONE row per (as_of_date, crop_slug) across the whole
history rather than a stack of vintages of the same fact. Each weekly capture is a NEW observation
(a later as-of), not a revision of an older one -- the ministry does not re-state prior weeks -- so
the vintage axis has nothing to hold. A capture that ever DID restate an earlier as-of with a
different number is a conflict, and :func:`build_silver` fails closed on it rather than silently
keeping whichever row sorted last.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable, Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.raw_to_bronze.minagro_grain_exports import (
    SOURCE,
    VALUE_COLUMNS,
    ascii_safe,
)

logger = get_logger(__name__)

# The SILVER-F010 physical column order. Declared here and mirrored, name for name and type for
# type, by configs/silver/tables/silver_minagro_grain_exports.yaml -- flat_producer.encode_parquet
# fails closed on any column the contract does not declare, so the two cannot drift silently.
OUTPUT_COLUMNS: list[str] = [
    "as_of_date",
    "crop_slug",
    "marketing_year",
    "prior_marketing_year",
    *VALUE_COLUMNS,
    "source",
]

NATURAL_KEY: list[str] = ["as_of_date", "crop_slug"]


class MinagroConflictError(ValueError):
    """The same (as_of_date, crop_slug) carried two different values across the input (fail closed).

    Mirrors ``MpocConflictError``: an EXACT duplicate (the same capture read twice, or a re-landed
    identical page) is collapsed; a CONFLICTING value for the same key is a hard error, because
    "whichever row sorted last" is not a decision anybody made."""


def _as_date(value) -> Optional[dt.date]:
    """A bronze ``as_of_date`` cell -> a python ``datetime.date``.

    Held as ``datetime.date`` and not as a string so the flat publisher encodes ``date32[day]``
    under the contract's INV-2 target type (the SILVER-F059 / D-LD anchor idiom); a string anchor
    is comparable only lexicographically and silently defeats a PIT range guard."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    ts = pd.Timestamp(value)
    return None if pd.isna(ts) else ts.date()


def build_silver(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Project one or more bronze capture frames onto the silver contract.

    Exact duplicates (an identical value tuple for the same key) are collapsed; a conflicting value
    for the same key raises :class:`MinagroConflictError`. Rows are sorted (as_of_date, crop_slug)
    so a re-run over the same raw objects produces a byte-stable object."""
    frames = [f for f in frames if f is not None and len(f)]
    if not frames:
        logger.warning("minagro silver: no bronze rows supplied -- emitting an empty contract frame")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = pd.concat(frames, ignore_index=True)
    missing = [c for c in OUTPUT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"minagro silver: the bronze frame is missing {missing}. This transform projects the "
            f"raw_to_bronze output verbatim and never re-derives a column -- a missing one means "
            f"the bronze frame was not built by build_bronze"
        )
    out = df[OUTPUT_COLUMNS].copy()
    out["as_of_date"] = [_as_date(v) for v in out["as_of_date"]]
    if out["as_of_date"].isna().any():
        raise ValueError(
            "minagro silver: a row carries a null as_of_date. That column IS the knowledge date -- "
            "a null one is not a missing attribute, it is a row that no as-of guard can ever admit "
            "(null <= asof is UNKNOWN, so the row silently drops out of every PIT read)"
        )
    for col in VALUE_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
    out["source"] = out["source"].fillna(SOURCE)

    # Collapse EXACT duplicates; refuse conflicting ones.
    conflicts: list[tuple] = []
    seen: dict[tuple, tuple] = {}
    keep: list[int] = []
    for idx, row in out.iterrows():
        key = (row["as_of_date"], row["crop_slug"])
        values = tuple(
            None if pd.isna(row[c]) else float(row[c]) for c in VALUE_COLUMNS
        )
        if key not in seen:
            seen[key] = values
            keep.append(idx)
        elif seen[key] != values:
            conflicts.append((key[0].isoformat(), key[1], seen[key], values))
    if conflicts:
        raise MinagroConflictError(
            f"minagro silver: {len(conflicts)} (as_of_date, crop_slug) key(s) carry two different "
            f"value tuples across the supplied captures: {ascii_safe(conflicts)}. The ministry does "
            f"not restate a past as-of, so this is either two different pages landed under one date "
            f"or a parse that moved -- refusing to keep whichever row sorted last"
        )

    out = out.loc[keep].sort_values(NATURAL_KEY).reset_index(drop=True)
    logger.info(
        "minagro silver: %d row(s) across %d as-of date(s)",
        len(out), out["as_of_date"].nunique(),
    )
    return out[OUTPUT_COLUMNS]
