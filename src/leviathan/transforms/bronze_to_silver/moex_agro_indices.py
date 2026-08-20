"""MOEX agro indices: bronze -> silver (``silver_moex_agro_indices``).

Grain: ``secid x trade_date``. Consumes the bronze frames produced by
``raw_to_bronze/moex_agro_indices.build_bronze`` -- one frame per landed ``row.json`` -- and projects
them onto the SILVER-F010 contract. Pure + AWS-free: no boto3, no network. The batch task is NOT
built in this wave (see the producer's prepared-commands section); this module is only the transform.

THE TIDY SHAPE, AND WHY IT IS THIS NARROW
------------------------------------------
``(secid, trade_date, close, currency, board)`` plus the house ``source`` stamp. The venue's
OPEN/HIGH/LOW/VALUE/VOLUME and its SHORTNAME/NAME labels stay in BRONZE. That is not a loss: these
are INDICATIVE INDICES, not traded contracts -- the published level is the fact, and MOEX serves
VOLUME/VALUE as the registered-contract turnover behind the index rather than as a tradable volume.
Publishing them in silver would invite a desk to read an indicative index as a liquidity series.
Bronze keeps every column, so widening the contract later is a transform change and never a
re-fetch.

CURRENCY AND BOARD ARE PUBLISHED COLUMNS, NOT CONSTANTS -- THIS IS THE UNIT DECISION
-------------------------------------------------------------------------------------
Measured 2026-08-20, this family serves TWO currencies on TWO boards:

    WHFOB / BRFOB / CRFOB   board RTSI   currency USD   USD per tonne, FOB deep-water Black Sea
                                                        (WHFOB prints ~229-232)
    WHCPT                   board AGRO   currency RUB   RUB per tonne, CPT to the port
                                                        (WHCPT prints ~11,000-14,000)

A schema that fixed one unit would file a rouble CPT level as a dollar FOB level -- a plausible
WRONG NUMBER two orders of magnitude out, with nothing downstream able to detect it. So ``currency``
comes from the row's own ``CURRENCYID`` and ``board`` from its own ``BOARDID``, and
:func:`transform_moex_agro_indices_bronze_to_silver` REFUSES a row that carries neither. There is
deliberately NO conversion layer and no derived USD column: converting RUB to USD would require an
FX convention this family has not established (see the duty note below), and a converted column is
indistinguishable from a published one once written.

The unit DENOMINATOR (per tonne) is not a published field on this endpoint. It is recorded here and
in the registry notes as source knowledge -- MOEX's agro indices are quoted per metric tonne -- and
it is deliberately NOT synthesised into a ``unit`` column, because a denominator this module asserts
rather than reads would look exactly like one the venue published. **FOLLOW-UP MOEX-UNIT-1**: pin
the denominator from the ISS securities-description block
(``/iss/securities/{SECID}.json``, ``description`` rows) on the first cloud-side run and add a
``unit`` column only once it is READ rather than assumed.

PIT -- TRADEDATE IS THE KNOWLEDGE DATE
---------------------------------------
``trade_date`` is the venue's own ``TRADEDATE``, carried verbatim from the ISS row through raw and
bronze to here. Nothing on this leg is derived from a wall clock. MOEX publishes these indices
SAME-DAY at end of session, so the registry carries ``knowledge_date_col: trade_date``,
``knowledge_semantics: data_date`` and ``publication_lag_days: 0`` -- the index level IS the
publication, and an as-of guard on ``trade_date`` is exact rather than approximate.

The residual, disclosed rather than hidden: "same-day EOD" means the day's level appears after the
session closes (MOEX evening session ends 23:50 MSK = 20:50 UTC), so a run early in the UTC day sees
yesterday's newest row. The producer therefore never asserts "today"; it lands whatever TRADEDATEs
the payload names, and the daily arm's window is wide enough that the previous session is always
re-offered.

WHAT THIS MODULE DOES NOT DO: THE EXPORT DUTY
----------------------------------------------
These indices are the INPUT to Russia's floating wheat export duty (the "damper"), which is::

    duty = 0.70 x (indicative_price_in_RUB - base_price_in_RUB)      floored at zero

with the base price set by Government Decree No. 117 of 06.02.2021 as amended (latest edition
07.03.2026); the wheat base is BELIEVED to be RUB-denominated in 2026 after an earlier
USD-denominated era. Plausibility sketch, against this family's own measured series::

    WHFOB 2026-08-19 = 229.3 USD/t  x ~83 RUB/USD  ~= 19,032  - 18,000 base = 1,032  x0.70 ~= 722

versus the published 19-Aug-2026 print of RUB 326.6 -> 721.1/t; inverting on 721.1 implies
82.99 RUB/USD. Close enough to confirm the mechanism, nowhere near close enough to publish.

**NO DUTY COLUMN IS COMPUTED HERE AND NONE MAY BE ADDED WITHOUT FOLLOW-UP MOEX-DUTY-1.** Three
inputs are unverified: the exact per-crop base constants and their amendment timeline; the official
FX convention (which CBR rate, over which averaging window); and which indicative-price window feeds
a given duty week -- the rate effective 19-25 Aug was fixed BEFORE 19 Aug, so the 229.3 print above
is almost certainly not the one the Ministry used. Closing it needs the decree text
(``consultant.ru/document/cons_doc_LAW_376329/`` or ``base.garant.ru/400295266/``, both reachable
from this estate) plus a back-test against a run of published weekly rates. A guessed constant
inside a transform is a wrong number carrying a provenance trail, which is strictly worse than no
number.

LATEST-ONLY, AND WHY THAT IS NOT A LOSS
----------------------------------------
One row per (secid, trade_date) across the whole history. MOEX does not restate a settled index
level, so the vintage axis has nothing to hold; a capture that DID restate an earlier date with a
different value is a conflict, and :func:`transform_moex_agro_indices_bronze_to_silver` fails closed
on it rather than keeping whichever row sorted last.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable, Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.transforms.raw_to_bronze.moex_agro_indices import (
    MEASURED_SECURITIES,
    MOEX_AGRO_INDICES_SOURCE,
)

logger = get_logger(__name__)

# The SILVER-F010 physical column order. Declared here and mirrored, name for name and type for
# type, by configs/silver/tables/silver_moex_agro_indices.yaml -- flat_producer.encode_parquet fails
# closed on any column the contract does not declare, so the two cannot drift silently.
SILVER_COLUMNS: list[str] = [
    "secid",
    "trade_date",
    "close",
    "currency",
    "board",
    "source",
]

NATURAL_KEY: list[str] = ["secid", "trade_date"]

_REQUIRED_COLS: frozenset[str] = frozenset({"secid", "trade_date", "close", "currency", "board"})

# The currencies this family has MEASURED. An unmeasured one is a WARNING and not a refusal: the
# currency is published per row and carried verbatim, so an unexpected token is honestly labelled
# rather than silently mis-denominated -- unlike EEX's uOM, nothing here is converted or mapped, so
# there is no wrong conversion to fail closed against. It still must be said out loud.
MEASURED_CURRENCIES: frozenset[str] = frozenset(
    spec["currency"] for spec in MEASURED_SECURITIES.values() if spec.get("currency")
)


class MoexConflictError(ValueError):
    """The same (secid, trade_date) carried two different closes across the input (fail closed).

    An EXACT duplicate (the same landed object read twice) is collapsed; a CONFLICTING value for the
    same key is a hard error, because "whichever row sorted last" is not a decision anybody made.
    MOEX does not restate a settled level, so a conflict is either two different rows landed under
    one key or a parse that moved.
    """


def _as_date(value) -> Optional[dt.date]:
    """A bronze ``trade_date`` cell -> a python ``datetime.date``.

    Held as ``datetime.date`` and not as a string so the flat publisher encodes ``date32[day]`` under
    the contract's INV-2 target type (the SILVER-F059 / D-LD anchor idiom); a string anchor is
    comparable only lexicographically and silently defeats a PIT range guard.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    ts = pd.Timestamp(value)
    return None if pd.isna(ts) else ts.date()


def transform_moex_agro_indices_bronze_to_silver(
    frames: Iterable[pd.DataFrame] | pd.DataFrame,
) -> pd.DataFrame:
    """Project one or more bronze frames onto the tidy silver contract.

    Args:
        frames: A single bronze DataFrame or an iterable of them, as produced by
                :func:`leviathan.transforms.raw_to_bronze.moex_agro_indices.build_bronze`.

    Returns:
        Silver DataFrame with :data:`SILVER_COLUMNS`, one row per ``(secid, trade_date)``, sorted so
        a re-run over the same raw objects produces a byte-stable object. An empty input returns an
        EMPTY frame carrying the full column set -- a dormant index contributes no rows and no error.

    Raises:
        ValueError: If a required column is absent; if a row carries a null ``trade_date`` or a null
                    ``close``; or if a row carries neither currency nor board (an unlabelled level
                    is not a number -- see the module docstring).
        MoexConflictError: If one ``(secid, trade_date)`` carries two different closes.
    """
    if isinstance(frames, pd.DataFrame):
        frames = [frames]
    frames = [f for f in frames if f is not None and len(f)]
    if not frames:
        logger.info("moex silver: no bronze rows supplied -- emitting an empty contract frame "
                    "(a dormant index and an empty window both land here, and both are data)")
        return pd.DataFrame(columns=SILVER_COLUMNS)

    df = pd.concat(frames, ignore_index=True)
    missing = sorted(_REQUIRED_COLS - set(df.columns))
    if missing:
        raise ValueError(
            f"moex silver: the bronze frame is missing {missing}. Got: {list(df.columns)}. This "
            f"transform projects the raw_to_bronze output verbatim and never re-derives a column -- "
            f"a missing one means the frame was not built by build_bronze"
        )

    out = df.reindex(columns=SILVER_COLUMNS).copy()
    out["secid"] = out["secid"].astype("string").fillna("").str.strip().str.upper()
    out["trade_date"] = [_as_date(v) for v in out["trade_date"]]
    if pd.isna(pd.Series(out["trade_date"])).any():
        raise ValueError(
            "moex silver: a row carries a null trade_date. That column IS the knowledge date -- a "
            "null one is not a missing attribute, it is a row that no as-of guard can ever admit "
            "(null <= asof is UNKNOWN, so the row silently drops out of every PIT read)"
        )

    out["close"] = pd.to_numeric(out["close"], errors="coerce").astype("float64")
    if bool(out["close"].isna().any()):
        bad = out.loc[out["close"].isna(), NATURAL_KEY].to_dict("records")
        raise ValueError(
            f"moex silver: {len(bad)} row(s) carry a null close: {bad[:5]}. The producer refuses to "
            f"land an observation without a level, so a null here is a corrupted bronze frame, "
            f"never a thin session"
        )

    for col in ("currency", "board"):
        out[col] = out[col].astype("string").fillna("").str.strip()
    unlabelled = out.loc[(out["currency"] == "") & (out["board"] == ""), NATURAL_KEY]
    if len(unlabelled):
        raise ValueError(
            f"moex silver: {len(unlabelled)} row(s) carry neither a currency nor a board: "
            f"{unlabelled.to_dict('records')[:5]}. This family publishes USD FOB levels near 230 "
            f"beside RUB CPT levels near 12,000; an unlabelled level is not a number"
        )

    unmeasured = sorted(set(out.loc[out['currency'] != '', 'currency']) - MEASURED_CURRENCIES)
    if unmeasured:
        logger.warning(
            "moex silver: currency(ies) %s were not measured on 2026-08-20 %s. The value is carried "
            "VERBATIM and nothing is converted, so the row is honestly labelled -- but a new "
            "denomination changes what the number means and must be classified",
            unmeasured, sorted(MEASURED_CURRENCIES),
        )

    out["source"] = MOEX_AGRO_INDICES_SOURCE

    # Collapse EXACT duplicates; refuse conflicting ones.
    conflicts: list[tuple] = []
    seen: dict[tuple, tuple] = {}
    keep: list[int] = []
    for idx, row in out.iterrows():
        key = (row["secid"], row["trade_date"])
        values = (float(row["close"]), str(row["currency"]), str(row["board"]))
        if key not in seen:
            seen[key] = values
            keep.append(idx)
        elif seen[key] != values:
            conflicts.append((key[0], key[1].isoformat(), seen[key], values))
    if conflicts:
        raise MoexConflictError(
            f"moex silver: {len(conflicts)} (secid, trade_date) key(s) carry two different values "
            f"across the supplied frames: {conflicts[:5]}. MOEX does not restate a settled index "
            f"level, so this is either two different rows landed under one key or a parse that "
            f"moved -- refusing to keep whichever row sorted last"
        )

    out = out.loc[keep].sort_values(NATURAL_KEY, kind="stable").reset_index(drop=True)
    logger.info(
        "moex silver: %d row(s), %d secid(s) %s, trade_date %s..%s, currency(ies) %s",
        len(out), out["secid"].nunique(), sorted(set(out["secid"])),
        out["trade_date"].min(), out["trade_date"].max(), sorted(set(out["currency"])),
    )
    return out[SILVER_COLUMNS]
