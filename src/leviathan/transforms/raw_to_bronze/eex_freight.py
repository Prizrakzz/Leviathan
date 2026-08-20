"""EEX dry-bulk freight settlements -- the raw -> bronze transform AND the source-universe authority.

WHAT THIS MODULE OWNS
---------------------
Everything about the EEX public market-data API that is a JUDGEMENT rather than plumbing, so the
producer, the parser and the tests cannot disagree about it:

  * :data:`OBSERVATION_SCHEMA` and :func:`build_observation` / :func:`canonical_observation_bytes`
    -- the exact, deterministic shape of a landed raw object, which is also what the
    first-capture-wins byte comparison compares;
  * :data:`DRY_BULK_PRODUCTS` and :data:`NON_DRY_BULK_PRODUCTS` -- the vessel-class boundary, and
    the WRITTEN refusal for the freight products that are not dry bulk;
  * :data:`MEASURED_FUTURES_SYMBOLS` -- the 16 freight FUTURES short codes the endpoint served on
    2026-08-20, kept as a DRIFT DETECTOR (not a gate: the producer enumerates live);
  * the parse, and the two cross-checks the payload's own fields make possible.

Pure: json + pandas + the house logger. No boto3, no S3, no network.

WHY THIS LEG EXISTS AT ALL, AND WHY IT IS SHAPED LIKE THIS
----------------------------------------------------------
``https://api.eex-group.com/pub/market-data/chart/eod`` is unauthenticated and serves the daily
settlement (``settlPx``) of every listed EEX freight future -- the Baltic Panamax/Supramax/Capesize/
Handysize contracts that are the grain-freight tempo. It serves a **rolling ~5-trading-day window
and nothing earlier**: measured live 2026-08-20, widening the request to ``startDate=2025-01-01``
still returns exactly five ``settlPx`` points (2026-08-13..2026-08-19), while the ``volume`` series
of the SAME response reaches ~33 sessions back. There is no history endpoint, no date-seek, and no
archive. **Every day not fetched is gone forever.**

That single fact dictates the whole design:

1. The raw grain is ``(symbol, trade_date)`` -- one immutable object per symbol per SETTLEMENT DATE,
   holding that symbol's whole listed curve for that date. Not ``(symbol, capture_date)``: a capture
   date would re-key the same published settlement under five different names across five runs.
2. FIRST CAPTURE WINS. A settlement is published once. A later window re-serving the same
   ``(symbol, trade_date)`` is byte-compared against what is landed; a difference is LOGGED to a
   divergence sibling and the first capture is kept. The producer therefore offers no ``--force``.
3. The five-day window is also the leg's own resilience budget: up to four consecutive missed runs
   are recoverable, the fifth is not. That is why ``freshness_sla.max_lag_days`` on the silver
   registry is 5 and not a comfortable 30 -- the SLA is the source's, not a preference.

THE DATE IS THE SOURCE'S OWN -- THE ONE THING THIS LEG HAS THAT ITS SIBLINGS DO NOT
-----------------------------------------------------------------------------------
The Euronext and Bursa producers land pages that carry NO date, so their ``as_of_date=`` key segment
IS the trade date by assertion and nothing can check it. Here the ``settlPx`` series is a list of
``[trade_date, value]`` pairs published BY THE VENUE, so:

  * ``trade_date`` is a real knowledge date, never derived from a wall clock (PIT law), and
  * :func:`build_bronze` CROSS-CHECKS the raw key's ``trade_date=``/``symbol=`` segments against the
    payload's own ``trade_date``/``symbol`` fields and refuses a mismatch. A mis-keyed object is the
    one corruption a forward-only accumulator can never repair from source.

Note what this does NOT license: the newest settlement in the window lags the wall clock. Probed at
~10:00 UTC on 2026-08-20 the window ended 2026-08-19, because EEX settles ~18:30 CET. The producer
must therefore never assert "today"; it lands whatever dates the payload names, and today's
settlement arrives on tomorrow's run (or on a late-enough run today).

UNIT HONESTY -- MEASURED, AND **NOT** UNIFORM
---------------------------------------------
The lane's working assumption was "USD/day for time-charter averages". That is true for ten of the
thirteen dry-bulk futures and FALSE for three. Measured live 2026-08-20 from the payloads' own
``uOM`` field:

    uOM = DAYS  (a time/trip-charter average, USD per day)
        CPTM Capesize 5TC, C5TM Capesize 5TC(182), P5TC Panamax 5TC, PE8M/PF8M/PG8M Panamax
        P1E_82/P2E_82/P3E_82, PREM Panamax P6, S11F Supramax 11TC, SPTM Supramax 10TC,
        H7TC Handysize 7TC
    uOM = TN    (a VOYAGE route, USD per tonne of cargo)
        C3EM Capesize C3, C5EM Capesize C5, C7EM Capesize C7

So a schema that hard-coded "USD/day" would publish three Capesize voyage rates -- numbers near
$35 -- under a per-day name, beside Panamax numbers near $20,000. ``uOM`` is therefore carried
VERBATIM through bronze and resolved to an explicit ``unit`` string in silver, where an unrecognised
``uOM`` is FATAL (the ESR unknown-unit doctrine: unknown-unit drift is never silently converted).

The SAME split runs through the volume series, where it is better hidden: ``volume`` is quantity in
the contract's uOM and ``lotSize`` is quantity in LOTS, the two are numerically identical on every
``DAYS`` contract, and they diverge by the lot size (x1,000) on the ``TN`` voyage routes. See the
note on :data:`_VOLUME_SERIES` -- it is the trap this leg is most likely to be re-broken by.

THE SOURCE UNIVERSE, AND THE WRITTEN REFUSALS
----------------------------------------------
``POST https://api.eex-group.com/pub/customise-widget/filter-data-with-scope`` with a base64 scope
blob enumerates the instruments. Measured 2026-08-20 for ``commodity == FREIGHT``: **1,123
instruments across 23 products** -- 16 FUTURES (``pricing == "F"``) and 7 OPTIONS
(``pricing == "O"``). Of the 16 futures, 13 are dry bulk and 3 are LNG carriers.

  * OPTIONS are refused at the FETCH boundary (:data:`REFUSED_PRICINGS`). They are served by a
    different endpoint (``/table-data-option``, strike-keyed) and an option premium is not a freight
    rate; landing them under a ``settle_px`` column would be a category error, not a units one.
  * LNG ROUTE futures (LNG1/LNG2/LNG3, the Baltic BLNG1/2/3 174k-cbm routes) ARE fetched into raw
    and REFUSED IN WRITING in silver (:data:`NON_DRY_BULK_PRODUCTS`). This follows the ESR
    precedent exactly: the fetcher takes the full source universe so nothing is ever lost to a
    boundary decision taken today, and the SILVER transform enforces the lane's dry-bulk scope with
    a log line. LNG shipping is a gas-freight instrument, not a grain-carrier one; if it is ever
    wanted, raw already holds every day of it and no re-fetch is needed -- which is the entire point
    on a source with no history.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
# The publication ``source`` value the silver rows carry AND the raw prefix segment. Unlike the
# Euronext leg (one venue fetch -> three products -> three slugs, so prefix != source), this leg is
# one venue == one source == one instrument family, so the two agree and there is nothing to explain
# away.
EEX_FREIGHT_SOURCE = "eex_freight"

# The landed object's self-describing schema tag. Bumped -- never redefined in place -- if the
# document shape ever changes, because objects landed under v1 are UNREPRODUCIBLE and must keep
# parsing forever.
OBSERVATION_SCHEMA = "eex_freight_settlements/v1"

# The venue's own scope vocabulary, verbatim from /filter-data-with-scope (2026-08-20).
COMMODITY_FREIGHT = "FREIGHT"
PRICING_FUTURE = "F"
# Options are a DIFFERENT endpoint and a different measure -- see the module docstring.
REFUSED_PRICINGS: dict[str, str] = {
    "O": ("pricing=O is the OPTIONS book (7 products: O5TM/OC05/OCPM/OH7C/OP5M/OPSM/OS11). It is "
          "served by /table-data-option, is keyed by strike, and its price is a PREMIUM -- not a "
          "freight settlement. Out of lane and refused at the fetch boundary"),
}

# ---------------------------------------------------------------------------
# The dry-bulk boundary
# ---------------------------------------------------------------------------
# The four Baltic dry-bulk vessel classes, spelled exactly as the API's ``product`` field spells
# them. These are the grain-carrying sizes: Panamax and Supramax carry the overwhelming majority of
# seaborne grain, Capesize sets the iron-ore-driven floor the whole dry market prices off, and
# Handysize is the small-parcel/Black-Sea-draft class.
DRY_BULK_PRODUCTS: frozenset[str] = frozenset({
    "Capesize", "Panamax", "Supramax", "Handysize",
})

# The freight products that are NOT dry bulk. Fetched into raw (source fidelity), dropped from
# silver WITH A LOG LINE -- the ESR ``_NON_MASS_UNIT_CODES`` idiom.
NON_DRY_BULK_PRODUCTS: dict[str, str] = {
    "LNG Route": ("LNG carrier routes (Baltic BLNG1/2/3, 174k cbm). Gas freight, not dry bulk: no "
                  "grain, ore or coal ever moves on these vessels. Raw keeps accumulating them "
                  "daily so the decision can be revisited against real history at zero re-fetch "
                  "cost -- which matters here because there is no history endpoint to re-fetch"),
}

# ---------------------------------------------------------------------------
# The measured universe -- a DRIFT DETECTOR, never a gate
# ---------------------------------------------------------------------------
# Every ``commodity=FREIGHT``, ``pricing=F`` short code the endpoint served on 2026-08-20, with the
# ``product``/``productSpecific``/``uOM`` it served them under. The producer ENUMERATES LIVE and does
# not read this map to decide what to fetch -- a source that lists a new dry-bulk contract must be
# captured on the day it appears, because a day not fetched is unrecoverable. This exists so that
# such an appearance (or a disappearance, or a uOM re-base) is SAID OUT LOUD in the log rather than
# absorbed silently, exactly as the ESR bronze transform surfaces unknown API fields.
MEASURED_FUTURES_SYMBOLS: dict[str, tuple[str, str, str]] = {
    # shortCode: (product, productSpecific, uOM measured 2026-08-20)
    "C3EM": ("Capesize", "C3", "TN"),
    "C5EM": ("Capesize", "C5", "TN"),
    "C5TM": ("Capesize", "5TC (182)", "DAYS"),
    "C7EM": ("Capesize", "C7", "TN"),
    "CPTM": ("Capesize", "5TC", "DAYS"),
    "H7TC": ("Handysize", "7TC", "DAYS"),
    "LNG1": ("LNG Route", "BLNG1 174", "DAYS"),
    "LNG2": ("LNG Route", "BLNG2 174", "DAYS"),
    "LNG3": ("LNG Route", "BLNG3 174", "DAYS"),
    "P5TC": ("Panamax", "5TC", "DAYS"),
    "PE8M": ("Panamax", "P1E_82", "DAYS"),
    "PF8M": ("Panamax", "P2E_82", "DAYS"),
    "PG8M": ("Panamax", "P3E_82", "DAYS"),
    "PREM": ("Panamax", "P6", "DAYS"),
    "S11F": ("Supramax", "11TC", "DAYS"),
    "SPTM": ("Supramax", "10TC", "DAYS"),
}

# The measured settlement-window width. NOT a floor to refuse below (a run on the day after a
# holiday legitimately sees fewer): it is the number the producer uses to size its request window and
# the number the docs quote. Measured 2026-08-20 across every symbol: exactly 5, every time.
SETTLEMENT_WINDOW_TRADING_DAYS = 5

# ---------------------------------------------------------------------------
# Bronze schema
# ---------------------------------------------------------------------------
BRONZE_COLUMNS: list[str] = [
    "trade_date", "symbol", "product", "route", "long_name",
    "contract_month", "maturity", "settle_px", "volume_uom", "volume_lots",
    "currency", "uom", "source",
]

_SETTLEMENT_SERIES = "settlPx"
# THE TWO VOLUME SERIES ARE TWO UNITS, AND THE NAMES DO NOT SAY SO.
#
# ``volume`` is the traded quantity expressed in the contract's OWN uOM -- the same denominator the
# price carries -- and ``lotSize`` is that quantity expressed in LOTS. That is not an inference from
# the numbers; it is what the venue's own widget does with them
# (eds.eex-group.com/widgets/pub/lib/v1/templates/customized-solution/marketDataHubTemplate.html):
#
#     if (obj.uOM !== undefined && obj.uOM !== '') { ...chart.volumeUnit = obj.uOM; }
#     ...volumeSeriesYaxisTitleOptions.text = ...chart.volumeUnit;
#
# i.e. the ``volume`` series is plotted against an axis TITLED WITH uOM, and a "Lots" toggle
# (``lotsSwitchLabel: 'Lots'``) swaps the ``lotSize`` series in and re-titles the axis.
#
# On the ``DAYS`` contracts the two series are numerically IDENTICAL (a lot is one day), which is
# exactly why this is a trap: P5TC, S11F and every other charter average agree on every point, so a
# parser that conflated them would look correct on twelve of the sixteen symbols. The disagreement
# only shows on a ``TN`` voyage route -- measured C3EM 2026-08-06: ``volume = 100000`` against
# ``lotSize = 100``, a factor of 1,000, which is the C3 contract's 1,000-tonne lot. Calling that
# 100,000 "lots" would overstate the traded size of every Capesize voyage route by three orders of
# magnitude, and no downstream consumer could tell.
_VOLUME_SERIES = "volume"       # -> volume_uom  (unit == the `uom` column: DAYS or TN)
_LOTSIZE_SERIES = "lotSize"     # -> volume_lots (unit == lots, and comparable across contracts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_dry_bulk(product: Optional[str]) -> bool:
    """True iff ``product`` is one of the four Baltic dry-bulk vessel classes."""
    return str(product or "").strip() in DRY_BULK_PRODUCTS


def contract_month(maturity: str) -> str:
    """``'202609'`` -> ``'2026-09'``. Fail-closed -- never guessed.

    The API's ``maturity`` is a compact ``YYYYMM`` for every freight instrument (``maturityType`` is
    ``Month`` on all 1,123 of them, measured 2026-08-20). A quarter/season maturity would arrive in a
    different shape entirely, and refusing it here is what stops it being silently read as a month.
    """
    token = str(maturity or "").strip()
    if len(token) != 6 or not token.isdigit():
        raise ValueError(
            f"eex freight: maturity {maturity!r} is not a compact YYYYMM. Every freight instrument "
            f"the endpoint serves is maturityType=Month; a quarter or season contract is a NEW "
            f"shape and must be decided on, not decoded by a parser that assumes months"
        )
    month = int(token[4:])
    if not 1 <= month <= 12:
        raise ValueError(f"eex freight: maturity {maturity!r} carries month {month}, outside 1..12")
    return f"{token[:4]}-{token[4:]}"


def _number(value: Any) -> Optional[float]:
    """A JSON scalar -> float, or None. ``null`` stays NULL and is NEVER synthesised as 0.0 (INV-4:
    a zero-volume session and an unreported one are different facts)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _series_points(payload: dict, name: str) -> dict[str, Any]:
    """``{trade_date: value}`` for one named series of a ``/chart/eod`` response."""
    for series in payload.get("series") or []:
        if series.get("serieName") == name:
            out: dict[str, Any] = {}
            for pair in series.get("timeAndValue") or []:
                if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0]:
                    out[str(pair[0])] = pair[1]
            return out
    return {}


def settlement_dates(payload: dict) -> list[str]:
    """The settlement dates ONE ``/chart/eod`` response actually carries, sorted ascending."""
    return sorted(_series_points(payload, _SETTLEMENT_SERIES))


# ---------------------------------------------------------------------------
# The landed object
# ---------------------------------------------------------------------------
def canonical_observation_bytes(document: dict) -> bytes:
    """The EXACT bytes of a landed raw object, rendered deterministically.

    Byte-stability is load-bearing rather than cosmetic: first-capture-wins compares a re-served
    window against the landed object BY BYTES, so two renderings of the same published settlements
    must be identical or every re-run would report a false divergence. ``sort_keys`` + fixed
    separators + ``ensure_ascii`` give that; the document itself carries no timestamp for the same
    reason (capture provenance lives in the ``raw_meta`` companion, which is allowed to differ).
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8") + b"\n"


def build_observation(
    *,
    symbol: str,
    trade_date: str,
    spec: dict,
    per_maturity: dict[str, dict],
) -> dict:
    """Assemble ONE ``(symbol, trade_date)`` observation from the per-maturity API responses.

    PURE -- this is the function the producer uses to build what it lands and the tests use to build
    fixtures, so the landed shape has exactly one definition.

    Args:
        symbol:       EEX short code, e.g. ``"P5TC"``.
        trade_date:   The settlement date, ``YYYY-MM-DD``, read from the payloads themselves.
        spec:         The instrument's scope record -- ``product``, ``route`` (the API's
                      ``productSpecific``), ``area``, ``pricing``, ``commodity``.
        per_maturity: ``{maturity: chart/eod payload}`` for every LIVE maturity of this symbol.

    Returns:
        The observation document (render it with :func:`canonical_observation_bytes`).

    Raises:
        ValueError: If no maturity carries a settlement for *trade_date* (an empty observation must
                    never be landed -- it is indistinguishable from a market holiday downstream); or
                    if the maturities disagree about ``currency`` / ``uOM`` for the same symbol,
                    which would make the unit of the landed curve unknowable.
    """
    settlements: list[dict] = []
    currencies: set[str] = set()
    uoms: set[str] = set()
    long_names: set[str] = set()

    for maturity in sorted(per_maturity):
        payload = per_maturity[maturity] or {}
        px = _series_points(payload, _SETTLEMENT_SERIES).get(trade_date)
        if px is None:
            continue
        settlements.append({
            "maturity": str(maturity),
            "settle_px": _number(px),
            # Two units, never conflated -- see the note on _VOLUME_SERIES / _LOTSIZE_SERIES.
            "volume_uom": _number(_series_points(payload, _VOLUME_SERIES).get(trade_date)),
            "volume_lots": _number(_series_points(payload, _LOTSIZE_SERIES).get(trade_date)),
        })
        if payload.get("currency"):
            currencies.add(str(payload["currency"]))
        if payload.get("uOM"):
            uoms.add(str(payload["uOM"]))
        if payload.get("longName"):
            long_names.add(str(payload["longName"]))

    if not settlements:
        raise ValueError(
            f"eex freight {symbol} {trade_date}: not one live maturity carries a settlement for "
            f"this date. An empty observation must never be landed -- once written it is "
            f"indistinguishable from a market holiday, and this source has no history endpoint to "
            f"re-derive the truth from"
        )
    # A symbol whose maturities disagree about the unit has no knowable unit, and the wrong guess
    # publishes a $35/tonne voyage rate beside a $20,000/day charter rate. Fail closed.
    if len(currencies) > 1 or len(uoms) > 1:
        raise ValueError(
            f"eex freight {symbol} {trade_date}: the listed maturities disagree about the unit "
            f"(currency={sorted(currencies)}, uOM={sorted(uoms)}). Refusing to land a curve whose "
            f"unit is ambiguous -- three of this venue's dry-bulk futures are USD/TONNE voyage "
            f"routes and the rest are USD/DAY charter averages, so a wrong pick is a plausible "
            f"wrong number rather than an error"
        )

    return {
        "schema": OBSERVATION_SCHEMA,
        "source": EEX_FREIGHT_SOURCE,
        "symbol": str(symbol).strip().upper(),
        "trade_date": str(trade_date),
        "commodity": str(spec.get("commodity") or COMMODITY_FREIGHT),
        "pricing": str(spec.get("pricing") or PRICING_FUTURE),
        "area": str(spec.get("area") or ""),
        "product": str(spec.get("product") or ""),
        "route": str(spec.get("route") or ""),
        "long_name": sorted(long_names)[0] if long_names else "",
        "currency": sorted(currencies)[0] if currencies else "",
        "uom": sorted(uoms)[0] if uoms else "",
        "settlements": settlements,
    }


# ---------------------------------------------------------------------------
# raw -> bronze
# ---------------------------------------------------------------------------
def build_bronze(payload, *, symbol: str, trade_date: str) -> tuple[pd.DataFrame, dict]:
    """One landed ``settlements.json`` -> the bronze rows for ONE (symbol, trade_date) + stats.

    ``symbol`` and ``trade_date`` are the raw KEY's own segments. Unlike the Euronext leg -- whose
    page carries no date, so its key segment is the sole authority -- the payload here carries both
    fields itself, so they are CROSS-CHECKED and a disagreement is fatal. A mis-keyed object is the
    one corruption a forward-only accumulator can never repair from source, and the check costs a
    string compare.

    Raises:
        ValueError: On a schema tag this parser does not know; on a key/payload disagreement about
                    symbol or trade_date; on a zero-settlement document; or on a maturity that is
                    not a compact ``YYYYMM``.
    """
    text = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"eex freight {symbol} {trade_date}: the landed object is not valid JSON "
            f"({len(text)} chars): {exc}"
        ) from exc
    if not isinstance(doc, dict):
        raise ValueError(
            f"eex freight {symbol} {trade_date}: the landed object is a "
            f"{type(doc).__name__}, expected the settlements document object"
        )

    schema = str(doc.get("schema") or "")
    if schema != OBSERVATION_SCHEMA:
        raise ValueError(
            f"eex freight {symbol} {trade_date}: landed object declares schema {schema!r}, this "
            f"parser reads {OBSERVATION_SCHEMA!r}. Objects landed under an older tag are "
            f"UNREPRODUCIBLE (there is no history endpoint) -- add a reader for the old tag; never "
            f"redefine a tag in place"
        )

    want_symbol = str(symbol).strip().upper()
    got_symbol = str(doc.get("symbol") or "").strip().upper()
    got_date = str(doc.get("trade_date") or "").strip()
    want_date = str(pd.Timestamp(trade_date).date())
    if got_symbol != want_symbol or got_date != want_date:
        raise ValueError(
            f"eex freight: the raw key names (symbol={want_symbol}, trade_date={want_date}) but the "
            f"payload names (symbol={got_symbol!r}, trade_date={got_date!r}). This leg publishes the "
            f"settlement date INSIDE the payload, so the two must agree; a mis-keyed object on a "
            f"forward-only source can never be repaired from upstream"
        )

    rows: list[dict] = []
    for entry in doc.get("settlements") or []:
        maturity = str(entry.get("maturity") or "")
        rows.append({
            "trade_date": want_date,
            "symbol": want_symbol,
            "product": str(doc.get("product") or ""),
            "route": str(doc.get("route") or ""),
            "long_name": str(doc.get("long_name") or ""),
            "contract_month": contract_month(maturity),
            "maturity": maturity,
            "settle_px": _number(entry.get("settle_px")),
            "volume_uom": _number(entry.get("volume_uom")),
            "volume_lots": _number(entry.get("volume_lots")),
            "currency": str(doc.get("currency") or ""),
            "uom": str(doc.get("uom") or ""),
            "source": EEX_FREIGHT_SOURCE,
        })

    if not rows:
        raise ValueError(
            f"eex freight {want_symbol} {want_date}: the landed object carries ZERO settlements. "
            f"An empty curve is indistinguishable from a market holiday downstream and this source "
            f"cannot be re-queried for the truth -- refusing to parse"
        )

    df = pd.DataFrame(rows, columns=BRONZE_COLUMNS)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    for col in ("settle_px", "volume_uom", "volume_lots"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    # A settlement prints for EVERY listed maturity on this venue -- measured 2026-08-20, P5TC's
    # full 84-maturity curve out to 2033-07 carried a settlement on all five window days, 84/84,
    # every day. So a document where NOT ONE maturity has a price is a shape failure, never a thin
    # session, and it must not reach silver as "the curve".
    priced = int(df["settle_px"].notna().sum())
    if priced == 0:
        raise ValueError(
            f"eex freight {want_symbol} {want_date}: not one of {len(df)} listed maturity(ies) "
            f"carries a settlement price. EEX settles every listed contract every trading day "
            f"(measured 84/84 on P5TC), so this is a payload-shape drift, not an illiquid session"
        )

    unknown_product = ""
    if str(doc.get("product") or "") not in DRY_BULK_PRODUCTS | set(NON_DRY_BULK_PRODUCTS):
        unknown_product = str(doc.get("product") or "")
        logger.warning(
            "eex freight UNIVERSE DRIFT %s %s: product %r is neither a curated dry-bulk vessel "
            "class %s nor a written refusal %s. Raw has it; the silver dry-bulk boundary will drop "
            "it. Classify it in eex_freight.DRY_BULK_PRODUCTS or NON_DRY_BULK_PRODUCTS",
            want_symbol, want_date, unknown_product,
            sorted(DRY_BULK_PRODUCTS), sorted(NON_DRY_BULK_PRODUCTS),
        )
    if want_symbol not in MEASURED_FUTURES_SYMBOLS:
        logger.warning(
            "eex freight UNIVERSE DRIFT %s %s: short code is not in MEASURED_FUTURES_SYMBOLS (the "
            "16 futures measured 2026-08-20). A NEW listing is captured, not refused -- re-measure "
            "the scope endpoint and re-pin the map", want_symbol, want_date,
        )
    elif str(doc.get("uom") or "") != MEASURED_FUTURES_SYMBOLS[want_symbol][2]:
        logger.warning(
            "eex freight UNIT DRIFT %s %s: uOM is %r, measured %r on 2026-08-20. The venue may have "
            "re-based the contract; the silver unit map must be re-decided, not re-applied",
            want_symbol, want_date, doc.get("uom"), MEASURED_FUTURES_SYMBOLS[want_symbol][2],
        )

    stats = {
        "symbol": want_symbol,
        "trade_date": want_date,
        "product": str(doc.get("product") or ""),
        "route": str(doc.get("route") or ""),
        "rows": int(len(df)),
        "rows_priced": priced,
        "currency": str(doc.get("currency") or ""),
        "uom": str(doc.get("uom") or ""),
        "dry_bulk": is_dry_bulk(doc.get("product")),
        "unknown_product": unknown_product,
        "contract_month_first": df["contract_month"].min(),
        "contract_month_last": df["contract_month"].max(),
    }
    logger.info("eex freight bronze %s %s: %d maturity(ies), %d priced, %s/%s",
                want_symbol, want_date, len(df), priced,
                stats["currency"] or "?", stats["uom"] or "?")
    return df, stats
