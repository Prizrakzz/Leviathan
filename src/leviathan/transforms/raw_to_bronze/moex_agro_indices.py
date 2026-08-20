"""MOEX agro indices -- the raw -> bronze transform AND the ISS source-contract authority.

WHAT THIS MODULE OWNS
---------------------
Every judgement about the Moscow Exchange ISS history endpoint that is a DECISION rather than
plumbing, so the producer, the parser and the tests cannot disagree about it:

  * :data:`MEASURED_HISTORY_COLUMNS` -- the ``history.columns`` list ISS served on 2026-08-20, kept
    as a DRIFT DETECTOR, and :data:`REQUIRED_HISTORY_COLUMNS`, the five this family actually reads;
  * :data:`MEASURED_SECURITIES` -- the five agro indices, their boards and their currencies;
  * :func:`parse_history_rows` / :func:`history_cursor` / :func:`next_start` -- the ISS envelope
    decode and the PAGING rule;
  * :data:`OBSERVATION_SCHEMA`, :func:`build_observation` and
    :func:`canonical_observation_bytes` -- the exact deterministic shape of a landed raw object,
    which is also what the first-capture-wins byte comparison compares;
  * :func:`build_bronze` -- one landed ``row.json`` -> the bronze frame, with the key/payload
    cross-check.

Pure: json + pandas + the house logger. No boto3, no S3, no network.

WHY THIS LEG EXISTS
-------------------
The Russian floating wheat export duty (the "damper", Decree 117 of 06.02.2021 as amended) is
computed from an INDICATIVE PRICE derived from export contracts registered on the Moscow Exchange,
and the Ministry of Agriculture publishes the resulting rate weekly on a page that is unreachable
from this estate (``mcx.gov.ru``: ``http=000`` from the laptop; see
``docs/private/recon/black_sea_numbers_recon.md`` section 2, PARKED-FOR-HOME). Every English-language
mirror of the weekly rate is licensing-fouled -- Interfax and TASS are copyrighted wires, Alta-Soft
requires a back-link, Global Trade Alert is CC BY-NC *and* gates the number behind a sign-in.

MOEX itself publishes the INPUT to that calculation, openly, daily, through its own ISS API. This
family takes the input series. It does NOT compute the duty -- see "THE DUTY DERIVATION" below.

REACHABILITY -- THE FACT THAT SHAPES THE WHOLE FAMILY
------------------------------------------------------
``iss.moex.com`` answers from AWS and does NOT answer from the estate's laptop. Probed 2026-08-20:
local ``http=000``, AWS ``200``. So:

  * every real run of ``jobs/ingest/fetch_moex_agro_indices.py`` is CLOUD-SIDE; the laptop gets
    ``--dry-run`` and nothing else;
  * this module and its tests are network-free by construction, and the fixtures under
    ``tests/fixtures/moex/`` are built from values measured through an AWS probe job on 2026-08-20;
  * a handful of envelope details below could NOT be verified from here and are marked
    ``ASSUMPTION`` in the constant that carries them. Each one wants a single cloud-side probe before
    the backfill fires -- they are listed in the producer's prepared-commands section.

THE ENDPOINT
------------
::

    GET https://iss.moex.com/iss/history/engines/stock/markets/index/securities/{SECID}.json
        ?from=YYYY-MM-DD&till=YYYY-MM-DD[&start=N]

The response is the standard ISS block envelope: a named block (``history``) carrying ``columns``
(a list of names) and ``data`` (positional rows), plus a ``history.cursor`` block that reports how
far through the result set the current page sits.

COLUMNS ARE READ BY NAME, NEVER BY POSITION
--------------------------------------------
``history.columns`` is 20 wide and this family reads five of them. Reading positionally would mean a
venue that inserts a column silently re-labels every value -- ``CLOSE`` becoming ``LOW`` produces a
plausible wrong number rather than an error, which is the failure class this estate refuses.
:func:`parse_history_rows` therefore builds ``{column_name: value}`` dicts and
:data:`REQUIRED_HISTORY_COLUMNS` is checked by name on every payload.

THE FIVE SECURITIES, AND THE DORMANT ONE
-----------------------------------------
Measured 2026-08-20 through ISS search (see :data:`MEASURED_SECURITIES`). ``WH4CPTNOV`` is DORMANT:
it exists as a security and serves ZERO history rows for August 2026. An empty history is therefore
a NORMAL, EXPECTED answer on this family and is handled as data -- zero rows, zero objects, exit 0,
one written log line -- never as an error. A dormant index that starts printing must be captured on
the day it does, which is why it stays in the default universe rather than being deleted from it.

THE DUTY DERIVATION -- DOCUMENTED HERE, NOT BUILT
--------------------------------------------------
The damper is::

    duty = 0.70 x (indicative_price_in_RUB - base_price_in_RUB)      floored at zero

where the indicative price is the MOEX-derived export price and the base price is a constant set by
Decree 117 and amended repeatedly (the wheat base is BELIEVED to be RUB-denominated in 2026, having
been USD-denominated in earlier editions -- that redenomination is exactly the kind of change that
silently breaks a hardcoded formula).

VALIDATION SKETCH, and it is a SKETCH -- a plausibility check, not a derivation::

    WHFOB 2026-08-19 close        229.3 USD/t          (measured, this family's own series)
    x an assumed ~83 RUB/USD                        ~= 19,032 RUB/t
    - an assumed 18,000 RUB/t base                  ~=  1,032 RUB/t
    x 0.70                                          ~=    722 RUB/t

against the known 19-Aug-2026 duty print of RUB 326.6 -> 721.1/t (recon section 2). Inverting the
sketch on the 721.1 print gives an IMPLIED FX of 19,030.1 / 229.3 = 82.99 RUB/USD.

That agreement is close enough to say the mechanism is understood and FAR too loose to publish a
number from. THREE separate things are unverified: (1) the exact base-price constants per crop and
per amendment; (2) the official FX convention -- which CBR rate, and over which averaging window;
(3) which indicative-price window feeds a given duty week (the rate effective 19-25 Aug was set
before 19 Aug, so the 229.3 print used above is almost certainly not the one the Ministry used).

**FOLLOW-UP MOEX-DUTY-1** -- named, and blocking. Computing a duty column requires the decree text
(``consultant.ru/document/cons_doc_LAW_376329/`` or ``base.garant.ru/400295266/``, both reachable),
read for the per-crop base constants, the amendment timeline and the FX convention, plus a
back-test of the reconstructed series against a run of published weekly rates. Until that is done
NO base-price constant and NO FX rule appears anywhere in this package -- a guessed constant inside
a transform is a wrong number with a provenance trail, which is worse than no number at all.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

import pandas as pd

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
# The raw prefix segment, the ``source`` column value and the family name are all this one string.
MOEX_AGRO_INDICES_SOURCE = "moex_agro_indices"

# The landed object's self-describing schema tag. Bumped -- never redefined in place -- if the
# document shape changes, so objects landed under v1 keep parsing forever.
OBSERVATION_SCHEMA = "moex_agro_indices_history_row/v1"

ISS_BASE = "https://iss.moex.com"
ISS_HISTORY_PATH = "/iss/history/engines/stock/markets/index/securities/{secid}.json"

# The ISS block names. ``history`` carries the rows; ``history.cursor`` reports the paging state.
HISTORY_BLOCK = "history"
CURSOR_BLOCK = "history.cursor"

# ---------------------------------------------------------------------------
# The measured ISS contract
# ---------------------------------------------------------------------------
# ``history.columns``, verbatim from a live AWS probe on 2026-08-20. A DRIFT DETECTOR, not a gate:
# ISS adding a column must be SAID OUT LOUD, never fatal, because this family reads by name.
#
# ASSUMPTION (one cloud-side probe to close): the probe transcript truncated a TWENTIETH column name
# after ``RECALC_DAT`` -- almost certainly a recalculation-date field. It is deliberately NOT
# guessed at here and NOT present in the fixtures. Nothing depends on it: the parser is name-keyed
# and an unknown column is logged, kept in the verbatim row of the landed object, and ignored by the
# five columns this family reads. Re-pin this tuple from the first cloud-side response.
MEASURED_HISTORY_COLUMNS: tuple[str, ...] = (
    "BOARDID", "SECID", "TRADEDATE", "SHORTNAME", "NAME", "CLOSE", "OPEN", "HIGH", "LOW", "VALUE",
    "DURATION", "YIELD", "DECIMALS", "CAPITALIZATION", "CURRENCYID", "DIVISOR", "TRADINGSESSION",
    "VOLUME", "TRADE_SESSION_DATE",
)

# The five columns this family actually reads. Checked BY NAME on every payload -- their absence is
# fatal, because everything below decodes them.
COL_BOARDID = "BOARDID"
COL_SECID = "SECID"
COL_TRADEDATE = "TRADEDATE"
COL_CLOSE = "CLOSE"
COL_CURRENCYID = "CURRENCYID"
REQUIRED_HISTORY_COLUMNS: tuple[str, ...] = (
    COL_BOARDID, COL_SECID, COL_TRADEDATE, COL_CLOSE, COL_CURRENCYID,
)

# The numeric columns carried through to bronze verbatim. NULL stays NULL and is never synthesised
# as 0.0 (INV-4: an unquoted session and a zero level are different facts).
NUMERIC_COLUMNS: tuple[str, ...] = ("CLOSE", "OPEN", "HIGH", "LOW", "VALUE", "VOLUME")

# ---------------------------------------------------------------------------
# The source universe -- measured, and a DRIFT DETECTOR
# ---------------------------------------------------------------------------
# The agro indices ISS search returned on 2026-08-20, with the board and currency each was served
# under. The producer fetches THIS list by default; the map exists so a board move, a
# re-denomination or an unlisted code is said out loud rather than absorbed.
#
# The two currencies are the whole point of the family and the reason ``currency`` is a published
# column rather than a constant: WHFOB prints ~229 (USD per tonne, FOB deep-water Black Sea) and
# WHCPT prints ~11,000-14,000 (RUB per tonne, CPT to the port). A schema that assumed one unit would
# file a rouble CPT level as a dollar FOB level, or vice versa -- a plausible wrong number with
# nothing downstream able to detect it (the EEX DAYS/TN lesson, on a different axis).
MEASURED_SECURITIES: dict[str, dict[str, str]] = {
    "WHFOB": {
        "board": "RTSI", "currency": "USD",
        "note": "wheat indicative index, FOB Black Sea deep-water ports -- the series the export "
                "duty's indicative price is derived from",
    },
    "BRFOB": {
        "board": "RTSI", "currency": "USD",
        "note": "barley FOB indicative index (the barley duty leg; zero for stretches of 2026)",
    },
    "CRFOB": {
        "board": "RTSI", "currency": "USD",
        "note": "corn FOB indicative index (the corn duty leg)",
    },
    "WHCPT": {
        "board": "AGRO", "currency": "RUB",
        "note": "NTB wheat CPT index -- the domestic rouble price delivered to port, the inland "
                "half of the same arbitrage",
    },
    "WH4CPTNOV": {
        "board": "", "currency": "",
        "note": "wheat class 4, CPT Novorossiysk. DORMANT: the security exists and served ZERO "
                "history rows for August 2026, so its board and currency are UNMEASURED. Fetched "
                "anyway -- an index that starts printing must be captured on the day it does",
    },
}

# The securities that served NO rows in the measured window. Their empty history is expected DATA,
# not a failure: zero rows, zero objects, exit 0, one log line.
DORMANT_SECIDS: frozenset[str] = frozenset({"WH4CPTNOV"})

# ISS's default page size. ASSUMPTION (one cloud-side probe to close): the standard ISS page is 100
# rows and the cursor reports it in ``PAGESIZE``. Nothing REQUIRES this number to be right --
# :func:`next_start` advances by the row count it actually received and stops on an empty page, so a
# different page size costs one extra request and never loses a row. It is here to size the log line
# and the backfill estimate.
ASSUMED_PAGE_SIZE = 100

# A runaway guard on the paging loop. A decade of daily rows is ~2,600; 500 pages at any plausible
# page size is orders of magnitude of headroom, and a cursor that never advances hits it in seconds
# instead of never terminating.
MAX_PAGES = 500

# The ISS cursor column names. ASSUMPTION (one cloud-side probe to close): the standard ISS cursor
# block is ``INDEX`` / ``TOTAL`` / ``PAGESIZE``. The embedded contract named the BLOCK
# (``history.cursor``) but not its columns. :func:`next_start` degrades to the row-count walk when
# the cursor is absent or shaped differently, so a wrong guess here costs one request, not a row.
CURSOR_INDEX = "INDEX"
CURSOR_TOTAL = "TOTAL"
CURSOR_PAGESIZE = "PAGESIZE"

# ---------------------------------------------------------------------------
# Bronze schema
# ---------------------------------------------------------------------------
# Bronze is richer than silver on purpose (bronze is source-faithful): it keeps the venue's own
# OPEN/HIGH/LOW/VALUE/VOLUME and its SHORTNAME/NAME labels, which the tidy silver contract does not
# carry. Nothing is dropped at the raw layer at all -- the landed object holds the whole row.
BRONZE_COLUMNS: list[str] = [
    "trade_date", "secid", "board", "close", "currency",
    "open", "high", "low", "value", "volume",
    "shortname", "name", "source",
]


# ---------------------------------------------------------------------------
# The ISS envelope
# ---------------------------------------------------------------------------
def _as_dict(payload: Any, *, context: str) -> dict:
    """Bytes / str / dict -> the parsed ISS response dict. Fail closed."""
    if isinstance(payload, dict):
        return payload
    text = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"moex {context}: the ISS response is not valid JSON ({len(text)} chars): {exc}"
        ) from exc
    if not isinstance(doc, dict):
        raise ValueError(
            f"moex {context}: the ISS response is a {type(doc).__name__}, expected the block "
            f"envelope object"
        )
    return doc


def parse_history_rows(payload: Any, *, context: str = "history") -> list[dict]:
    """One ISS response -> ``[{column_name: value}, ...]`` for the ``history`` block.

    BY NAME, never by position -- see the module docstring. An EMPTY ``data`` list returns ``[]``
    and is not an error: a dormant index and a request window with no sessions both answer that way,
    and both are data.

    Raises:
        ValueError: If the ``history`` block is absent or malformed, if ``columns`` is empty, if a
                    row's width disagrees with ``columns``, or if any of
                    :data:`REQUIRED_HISTORY_COLUMNS` is missing. Every one of those is a contract
                    change, and decoding through it would re-label values silently.
    """
    doc = _as_dict(payload, context=context)
    block = doc.get(HISTORY_BLOCK)
    if not isinstance(block, dict):
        raise ValueError(
            f"moex {context}: the response carries no {HISTORY_BLOCK!r} block (keys seen: "
            f"{sorted(doc)}). An ISS error document, an HTML interstitial or a renamed block all "
            f"look like this, and none of them may be read as 'no rows today'"
        )
    columns = list(block.get("columns") or [])
    if not columns:
        raise ValueError(
            f"moex {context}: the {HISTORY_BLOCK!r} block declares no columns. Without the column "
            f"names the positional rows cannot be decoded at all, and guessing at the 2026-08-20 "
            f"order would silently re-label every value"
        )
    missing = [c for c in REQUIRED_HISTORY_COLUMNS if c not in columns]
    if missing:
        raise ValueError(
            f"moex {context}: the {HISTORY_BLOCK!r} columns are missing {missing}. Columns served: "
            f"{columns}. These five are what this family reads by name; refusing to fall back to a "
            f"positional decode"
        )

    unknown = [c for c in columns if c not in MEASURED_HISTORY_COLUMNS]
    if unknown:
        # OBSERVABILITY, not a behaviour change: the parser is name-keyed, so a new column is
        # harmless -- but it is also the single cheapest signal that the venue changed something.
        logger.info(
            "moex %s: ISS serves %d column(s) %s that are not in MEASURED_HISTORY_COLUMNS (the "
            "2026-08-20 census). Kept verbatim in the landed row and ignored by the five columns "
            "this family reads -- re-pin the census",
            context, len(unknown), unknown,
        )

    rows: list[dict] = []
    for idx, row in enumerate(block.get("data") or []):
        if not isinstance(row, (list, tuple)):
            raise ValueError(
                f"moex {context}: {HISTORY_BLOCK} row {idx} is a {type(row).__name__}, expected the "
                f"positional list ISS serves"
            )
        if len(row) != len(columns):
            raise ValueError(
                f"moex {context}: {HISTORY_BLOCK} row {idx} has {len(row)} cell(s) against "
                f"{len(columns)} declared column(s). An off-by-one here re-labels every value in "
                f"the row"
            )
        rows.append(dict(zip(columns, row)))
    return rows


def history_cursor(payload: Any) -> Optional[dict]:
    """The ``history.cursor`` block as ``{INDEX, TOTAL, PAGESIZE}``, or None when absent/unusable.

    Returns None rather than raising: the cursor is an OPTIMISATION (it tells the walk when to
    stop without one extra request), and :func:`next_start` has a complete fallback that needs
    only the row count. A venue that renames the cursor columns must cost one request, not a leg.
    """
    doc = _as_dict(payload, context="cursor")
    block = doc.get(CURSOR_BLOCK)
    if not isinstance(block, dict):
        return None
    columns = list(block.get("columns") or [])
    data = list(block.get("data") or [])
    if not columns or not data or not isinstance(data[0], (list, tuple)):
        return None
    if len(data[0]) != len(columns):
        return None
    record = dict(zip(columns, data[0]))
    out: dict[str, int] = {}
    for name in (CURSOR_INDEX, CURSOR_TOTAL, CURSOR_PAGESIZE):
        value = record.get(name)
        try:
            out[name] = int(value)
        except (TypeError, ValueError):
            return None
    return out


def next_start(payload: Any, *, start: int, rows_received: int) -> Optional[int]:
    """The ``&start=`` for the NEXT page, or None when this page was the last.

    Two rules, in order, and the second is what makes the first safe:

    1. **The cursor, when ISS serves a usable one.** ``INDEX + PAGESIZE >= TOTAL`` means the page
       just read reaches the end. Otherwise the next offset is ``INDEX + PAGESIZE``.
    2. **The row-count walk, otherwise.** A page that returned ZERO rows is the end; a page that
       returned any rows advances ``start`` by exactly that many. This terminates on every source
       that returns rows monotonically and it needs nothing but the rows themselves, so a cursor
       that is absent, renamed or re-shaped costs ONE extra request and never a row.

    Rule 2 also guards rule 1: a cursor whose ``PAGESIZE`` is 0 or whose ``INDEX`` does not advance
    would loop forever, so a cursor that fails to move past ``start`` falls through to the walk.
    """
    if rows_received <= 0:
        return None
    cursor = history_cursor(payload)
    if cursor is not None:
        index, total, pagesize = (
            cursor[CURSOR_INDEX], cursor[CURSOR_TOTAL], cursor[CURSOR_PAGESIZE],
        )
        if pagesize > 0:
            following = index + pagesize
            if following >= total:
                return None
            if following > start:
                return following
            logger.warning(
                "moex: the ISS cursor reports INDEX=%d PAGESIZE=%d TOTAL=%d, whose next offset %d "
                "does not advance past start=%d. Falling back to the row-count walk rather than "
                "looping", index, pagesize, total, following, start,
            )
    return start + rows_received


def iter_pages(fetch_page, *, secid: str, max_pages: int = MAX_PAGES) -> list[dict]:
    """Walk every ISS page for one secid and return the concatenated ``history`` rows.

    ``fetch_page(start: int) -> payload`` is supplied by the caller -- the producer passes an HTTP
    call, the tests pass a dict lookup -- so the PAGING RULE is testable without a network.

    Raises:
        RuntimeError: If the walk exceeds *max_pages*. That can only mean the cursor and the row
                      count are both lying about progress, and an unbounded loop against a venue is
                      worse than a refusal.
    """
    rows: list[dict] = []
    start = 0
    for page in range(max_pages):
        payload = fetch_page(start)
        page_rows = parse_history_rows(payload, context=f"{secid} start={start}")
        rows.extend(page_rows)
        following = next_start(payload, start=start, rows_received=len(page_rows))
        if following is None:
            logger.debug("moex %s: page %d (start=%d) returned %d row(s) and ends the walk",
                         secid, page, start, len(page_rows))
            return rows
        start = following
    raise RuntimeError(
        f"moex {secid}: the ISS history walk exceeded {max_pages} pages without terminating. The "
        f"cursor and the row count both claim progress that is not happening -- refusing to keep "
        f"requesting"
    )


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------
def _number(value: Any) -> Optional[float]:
    """A JSON scalar -> float, or None. ``null`` stays NULL and is NEVER synthesised as 0.0."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    """A JSON scalar -> a stripped string; ``null`` -> ``''``."""
    return "" if value is None else str(value).strip()


def trade_date_of(row: dict) -> str:
    """The row's own ``TRADEDATE`` as ``YYYY-MM-DD``. Fail closed -- never a wall clock.

    THIS is the knowledge date of the whole family: it is the raw key's ``trade_date=`` segment, the
    bronze ``trade_date`` and the silver ``trade_date``, and it is read once, here, from the value
    the venue published.
    """
    raw = _text(row.get(COL_TRADEDATE))
    if not raw:
        raise ValueError(
            f"moex: a history row carries no {COL_TRADEDATE}. That value is the ONLY knowledge date "
            f"this leg has and it is also the raw key -- refusing to fall back to the fetch date, "
            f"which would file a back-filled row under today"
        )
    try:
        stamp = pd.Timestamp(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"moex: {COL_TRADEDATE} {raw!r} is not a date ({exc}). ISS serves ISO YYYY-MM-DD; a "
            f"source that switched format would re-date the whole series silently"
        ) from exc
    if pd.isna(stamp):
        raise ValueError(f"moex: {COL_TRADEDATE} {raw!r} parsed to NaT")
    return str(stamp.date())


# ---------------------------------------------------------------------------
# The landed object
# ---------------------------------------------------------------------------
def canonical_observation_bytes(document: dict) -> bytes:
    """The EXACT bytes of a landed raw object, rendered deterministically.

    Byte-stability is load-bearing rather than cosmetic: first-capture-wins compares a re-served row
    against the landed object BY BYTES, so two renderings of the same published row must be
    identical or every re-run would report a false divergence. ``sort_keys`` + fixed separators +
    ``ensure_ascii`` give that, and the document carries NO timestamp for the same reason -- capture
    provenance lives in the ``raw_meta`` companion, which is allowed to differ.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8") + b"\n"


def build_observation(*, secid: str, row: dict) -> dict:
    """One ISS ``history`` row -> the document landed at ``.../secid=X/trade_date=Y/row.json``.

    PURE -- the producer uses this to build what it lands and the tests use it to build fixtures, so
    the landed shape has exactly one definition.

    The venue's whole row is kept VERBATIM under ``row`` (source fidelity at the raw layer: a column
    this family ignores today costs nothing to keep and cannot be re-fetched into an object already
    written), and the five read columns are also promoted to top-level fields so a consumer never
    has to know the ISS column spelling.

    Raises:
        ValueError: If the row names a different secid than the caller; or if ``CLOSE`` is null. An
                    observation with no level is not an observation -- landing one would be
                    indistinguishable from a session the index genuinely printed at zero, forever.
    """
    want = str(secid).strip().upper()
    got = _text(row.get(COL_SECID)).upper()
    if got and got != want:
        raise ValueError(
            f"moex: a history row requested for secid={want} names {got!r} in its own {COL_SECID} "
            f"cell. Refusing to land one index's level under another's key"
        )
    trade_date = trade_date_of(row)
    close = _number(row.get(COL_CLOSE))
    if close is None:
        raise ValueError(
            f"moex {want} {trade_date}: the row carries a null {COL_CLOSE}. An observation with no "
            f"level must never be landed -- once written it is indistinguishable from a real "
            f"printed level, and the key it burns is immutable"
        )
    return {
        "schema": OBSERVATION_SCHEMA,
        "source": MOEX_AGRO_INDICES_SOURCE,
        "secid": want,
        "trade_date": trade_date,
        "board": _text(row.get(COL_BOARDID)),
        "currency": _text(row.get(COL_CURRENCYID)),
        "close": close,
        # The venue's own row, verbatim and complete. Column names are ISS's, not this estate's.
        "row": {str(k): v for k, v in row.items()},
    }


def observations_from_rows(rows: Iterable[dict], *, secid: str) -> list[dict]:
    """Every landable observation for one secid, in trade-date order.

    A row whose ``CLOSE`` is null is SKIPPED with a warning rather than aborting the secid: a single
    unquoted session must never cost the rest of the window. A row that names the wrong secid is
    still fatal -- that is a mis-served payload, not a thin session.
    """
    out: list[dict] = []
    for row in rows:
        try:
            out.append(build_observation(secid=secid, row=row))
        except ValueError as exc:
            if f"null {COL_CLOSE}" in str(exc):
                logger.warning("moex %s: %s -- row skipped, nothing landed for that date",
                               secid, exc)
                continue
            raise
    out.sort(key=lambda doc: doc["trade_date"])
    return out


# ---------------------------------------------------------------------------
# raw -> bronze
# ---------------------------------------------------------------------------
def build_bronze(payload, *, secid: str, trade_date: str) -> tuple[pd.DataFrame, dict]:
    """One landed ``row.json`` -> the single bronze row for that (secid, trade_date) + stats.

    ``secid`` and ``trade_date`` are the raw KEY's own segments, and the payload carries both fields
    itself, so they are CROSS-CHECKED and a disagreement is fatal (the EEX idiom). A mis-keyed
    object is a corruption that reads as perfectly valid data forever.

    Raises:
        ValueError: On a schema tag this parser does not know; on a key/payload disagreement; or on
                    a document with no ``close``.
    """
    doc = _as_dict(payload, context=f"{secid} {trade_date}")

    schema = str(doc.get("schema") or "")
    if schema != OBSERVATION_SCHEMA:
        raise ValueError(
            f"moex {secid} {trade_date}: the landed object declares schema {schema!r}, this parser "
            f"reads {OBSERVATION_SCHEMA!r}. Add a reader for the old tag; never redefine a tag in "
            f"place -- landed objects are immutable"
        )

    want_secid = str(secid).strip().upper()
    got_secid = _text(doc.get("secid")).upper()
    want_date = str(pd.Timestamp(trade_date).date())
    got_date = _text(doc.get("trade_date"))
    if got_secid != want_secid or got_date != want_date:
        raise ValueError(
            f"moex: the raw key names (secid={want_secid}, trade_date={want_date}) but the landed "
            f"object names (secid={got_secid!r}, trade_date={got_date!r}). ISS publishes TRADEDATE "
            f"inside the row, so the two must agree; a mis-keyed object cannot be told from a real "
            f"one downstream"
        )

    close = _number(doc.get("close"))
    if close is None:
        raise ValueError(
            f"moex {want_secid} {want_date}: the landed object carries no close. build_observation "
            f"refuses to write one, so this object is corrupt rather than thin"
        )

    row = doc.get("row") if isinstance(doc.get("row"), dict) else {}
    record = {
        "trade_date": want_date,
        "secid": want_secid,
        "board": _text(doc.get("board")),
        "close": close,
        "currency": _text(doc.get("currency")),
        "open": _number(row.get("OPEN")),
        "high": _number(row.get("HIGH")),
        "low": _number(row.get("LOW")),
        "value": _number(row.get("VALUE")),
        "volume": _number(row.get("VOLUME")),
        "shortname": _text(row.get("SHORTNAME")),
        "name": _text(row.get("NAME")),
        "source": MOEX_AGRO_INDICES_SOURCE,
    }

    measured = MEASURED_SECURITIES.get(want_secid)
    if measured is None:
        logger.warning(
            "moex UNIVERSE DRIFT %s %s: secid is not in MEASURED_SECURITIES (the five measured "
            "2026-08-20). A NEW listing is captured, not refused -- re-measure the ISS security "
            "search and re-pin the map", want_secid, want_date,
        )
    else:
        for field, column in (("board", "board"), ("currency", "currency")):
            expected = measured.get(field) or ""
            actual = record[column]
            if expected and actual and actual != expected:
                logger.warning(
                    "moex CONTRACT DRIFT %s %s: %s is %r, measured %r on 2026-08-20. A board move "
                    "or a re-denomination changes what the number MEANS -- the silver unit must be "
                    "re-decided, not re-applied", want_secid, want_date, field, actual, expected,
                )

    df = pd.DataFrame([record], columns=BRONZE_COLUMNS)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    for col in ("close", "open", "high", "low", "value", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    stats = {
        "secid": want_secid,
        "trade_date": want_date,
        "board": record["board"],
        "currency": record["currency"],
        "close": close,
        "rows": int(len(df)),
        "dormant_secid": want_secid in DORMANT_SECIDS,
    }
    logger.info("moex bronze %s %s: close=%s %s (board %s)",
                want_secid, want_date, close, record["currency"] or "?", record["board"] or "?")
    return df, stats
