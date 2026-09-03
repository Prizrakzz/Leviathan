"""PRICE_AND_PLAYBOOKS W1c -- the Bursa Malaysia FCPO derivatives-prices raw -> bronze transform.

WHAT THIS MODULE OWNS
---------------------
The venue-specific half of ``silver_futures_eod``'s Bursa leg, and nothing else:

  * :data:`BURSA_CODE_MAP` -- the product codes this leg keeps (EMPTY while PARKED, V2-4 2026-09-02:
    the palm slug moved to the CME USD tape), bound to CONTRACT_MAP's ``source == "bursa"`` rows in
    both directions by an import-time assertion. The venue's selector offers FCPO / FPKO / FSOY /
    FEPO / FPOL; each is a future CONTRACT_MAP decision, never something this parser infers;
  * the ``thead`` pin (the JSE precedent) over the API's 13 POSITIONAL elements;
  * the embedded-HTML decode of the three cells that are not plain strings;
  * the ``ses=day`` session guard;
  * the ``"-"`` untraded sentinel and the ``Aug 2026 -> '2026-08'`` delivery-month decode.

Pure: pandas + the house logger + stdlib. No boto3, no S3, no network, no playwright, no bs4 --
the three HTML cells are single fixed-shape fragments and are decoded with anchored regexes, which
keeps this module importable anywhere the browser image is not.

WHY THERE IS A BROWSER
----------------------
Cloudflare answers a plain request with ``403`` + ``Cf-Mitigated: challenge`` from BOTH a
residential and a Fargate IP (probed 2026-07-29). The challenge CLEARS in headless Chromium with no
Turnstile presented, so the producer drives a real page and then calls the JSON API in-page with the
session cookie. The API body is what lands.

THE FIVE THINGS THIS MODULE ENCODES
-----------------------------------
1. **The payload is POSITIONAL -- 13 elements, no field names -- so the ``thead`` is the pin.**
   The API returns ``data: [[13 elements], ...]`` and nothing in the body says what element 8 is.
   The rendered table's ``thead`` is the only self-description the venue publishes, so the producer
   scrapes it into a ``"thead"`` side-channel beside the body and this module refuses to parse when
   it drifts (:func:`assert_thead`). Without that, a venue that inserts a column silently swaps
   HIGH for LOW and publishes plausible wrong numbers -- the JSE GRADE-2 defect class, in a shape
   no row count can catch.
2. **THREE cells are HTML, not values.** NAME is a ``<div>``, CHANGE is a ``<span>``, and OI is an
   ``<a>`` anchor followed by two hidden ``<div>``s. A blanket tag-strip of the OI cell yields
   ``"9,202FCPO/Aug 2026As of "`` -- a string that parses to NaN and silently NULLs the open
   interest on every traded month, which would degrade ``futures_roll``'s open-interest front-month
   rule into the nearest-month tie-break with no error anywhere. So OI takes the ANCHOR TEXT
   specifically, and handles the two other observed shapes (a bare ``"-"``, a bare number).
3. **``ses=day`` or nothing.** The venue serves ``day`` (T), ``night`` (T+1, after-hours) and
   ``all`` from the same URL shape, and the night payload is a COMPLETE, PLAUSIBLE 24-month table
   with different prices -- ``4,557`` against the day's ``4,540`` for Aug 2026. The only
   discriminator in the body is the NAME cell, which reads ``FCPO (T+1)`` on the night session. A
   mis-parameterized producer would therefore publish after-hours prices as the daily settlement
   and nothing downstream could tell. :func:`assert_day_session` is a HARD error on that.
4. **The delivery month is the ONLY unique thing on a row.** The NAME cell is the constant string
   ``FCPO`` on all 24 rows, so it cannot be ``raw_symbol``: the F2 uniqueness key is
   ``(leviathan_slug, trade_date, raw_symbol)`` and a constant symbol collapses all 24 rows onto one
   key -- a hard publish failure at best, and at worst 23 lost months. ``raw_symbol`` is the MONTH
   cell verbatim (``"Aug 2026"``), the JSE expiry-cell precedent.
5. **SETT. PRICE prints for all 24 months** -- including the eight quiet back months whose every
   other cell is ``"-"`` -- and it is the price of record. LAST DONE is a trade and is never
   promoted into it.

HISTORY: THERE IS NONE
----------------------
The API serves CURRENT prices only; no date parameter exists on it and the body carries no date
field. So (a) ``trade_date`` comes from the raw key's ``as_of_date=`` segment and from nowhere else,
and (b) this leg is FORWARD-ACCUMULATION like CEPEA's daily widget: the series starts at the first
run of the producer and a missed session is permanently unrecoverable.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------
# The venue's own product-selector value -> the leviathan slug. EXACT match.
# PARKED 2026-09-02 (V2-4): malaysian_crude_palm_oil_cme now carries the CME USD tape (source
# databento_glbx_mdp3), so no source=='bursa' slug exists and this map is EMPTY by the lint below --
# the parser stays intact and is exercised under a fixture-injected binding ({"FCPO": <slug>});
# a bursa slug is a CONTRACT_MAP + configs/commodities decision (docket). slug_for_code fails
# closed on every code while parked, and the producer refuses before the browser.
BURSA_CODE_MAP: dict[str, str] = {}

BURSA_SOURCE = "bursa"

# The ONLY session this leg publishes. "day" is the T session whose settlement is THE daily
# settlement; "night" is the T+1 after-hours session and "all" merges them.
BURSA_DAY_SESSION = "day"
# The night session's own label, verbatim from the NAME cell. Presence of this token ANYWHERE in the
# payload means the producer asked for the wrong session.
_NIGHT_LABEL = "(T+1)"

# ---------------------------------------------------------------------------
# Columns -- 13 POSITIONAL elements, pinned by the rendered thead
# ---------------------------------------------------------------------------
# The POSITIONS were resolved cell-by-cell against the rendered first row on 2026-07-29 (the OI
# anchor text 9,202 matched the rendered OI exactly). Accepted token SETS per position rather than
# one exact string: the JSE `_FIELD_TOKENS` idiom, so a cosmetic re-wording ("VOL" -> "VOLUME") is
# survivable while a reordering is not.
#
# HONEST PROVENANCE, because it decides what run one means: the TOKENS below are a normalization of
# the column LABELS recorded in capture_notes.md plus defensive aliases -- there is no thead fixture
# in tests/fixtures/w1c/, so the pin has never been matched against a live rendered header. If the
# real page renders any cell the API does not carry (a chart or action column), this refuses the day
# with "expected 13" -- fail-closed, which is the design, and RECOVERABLE, because the raw object
# lands with both halves and can be re-parsed once the tokens are re-pinned. So: capture the real
# thead on the first Fargate run, commit it as a fixture and re-pin these sets BEFORE the schedule
# is armed. Do NOT soften the reorder/rename checks to make a capture pass -- a reordered column
# publishes plausible WRONG numbers, which is the one failure nothing downstream can see.
_HEADER_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("no", ("no", "no.", "num", "n")),
    ("name", ("name", "instrument", "contract")),
    ("month", ("month", "contract month", "delivery month", "expiry")),
    ("open", ("open", "open price")),
    ("bid", ("bid", "buy", "bid price")),
    ("ask", ("ask", "sell", "ask price", "offer")),
    ("last", ("last done", "last", "last done price", "last price")),
    ("change", ("change", "chg", "change rm", "chg rm")),
    ("high", ("high", "high price")),
    ("low", ("low", "low price")),
    ("volume", ("vol", "volume", "vol lots", "volume lots")),
    ("open_interest", ("oi", "o i", "open interest")),
    ("settle", ("sett price", "settlement price", "sett", "settle price", "settlement")),
)
_FIELDS: tuple[str, ...] = tuple(f for f, _ in _HEADER_TOKENS)
_COLUMN_COUNT = len(_HEADER_TOKENS)
_IDX = {field: i for i, field in enumerate(_FIELDS)}

# The anchor that carries the open interest as its TEXT. Non-greedy, anchored on the tag pair --
# a whole-cell tag strip would append the two hidden <div>s and destroy the number.
_ANCHOR_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
# Any tag. Used only on cells whose ENTIRE text is the value (NAME, CHANGE).
_TAG_RE = re.compile(r"<[^>]*>")
# "Aug 2026"
_MONTH_RE = re.compile(r"^([A-Za-z]{3,10})\s+(\d{4})$")
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

# The untraded sentinel. "-" is the venue's; the rest are defensive.
_NULL_TOKENS = frozenset({"", "-", "--", "n/a", "na", "nan", "none"})

CONTRACT_MONTH_FMT = "%04d-%02d"

BRONZE_COLUMNS: list[str] = [
    "trade_date", "leviathan_slug", "code", "raw_symbol", "contract_month",
    "open", "bid", "ask", "last", "change", "high", "low",
    "volume", "open_interest", "settle",
]


def _lint_code_map() -> list[str]:
    """BURSA_CODE_MAP must be EXACTLY the ``source == 'bursa'`` slugs of CONTRACT_MAP, both ways."""
    errs: list[str] = []
    mapped = set(BURSA_CODE_MAP.values())
    curated = {slug for slug, rec in FC.CONTRACT_MAP.items() if rec["source"] == BURSA_SOURCE}
    for slug in sorted(mapped - curated):
        errs.append(f"{slug}: in BURSA_CODE_MAP but not a source={BURSA_SOURCE!r} CONTRACT_MAP slug")
    for slug in sorted(curated - mapped):
        errs.append(f"{slug}: a source={BURSA_SOURCE!r} CONTRACT_MAP slug with no Bursa code")
    return errs


assert not _lint_code_map(), \
    "bursa_fcpo.BURSA_CODE_MAP is malformed: " + "; ".join(_lint_code_map())


def slug_for_code(code: str) -> str:
    """The leviathan slug for one Bursa product code. FAIL CLOSED -- never guessed."""
    token = str(code or "").strip().upper()
    slug = BURSA_CODE_MAP.get(token)
    if slug is None:
        raise ValueError(
            f"bursa: code {code!r} is not one of {sorted(BURSA_CODE_MAP)}. The venue also lists "
            f"FPKO / FSOY / FEPO / FPOL; each is an explicit CONTRACT_MAP decision, not something "
            f"this parser infers"
        )
    return slug


def _norm(value) -> str:
    """A header cell -> a single-spaced lowercase ASCII token string ('SETT. PRICE' -> 'sett
    price'). Punctuation is collapsed, which is what lets the pin match without guessing it."""
    if value is None:
        return ""
    text = re.sub(r"[^0-9A-Za-z]+", " ", str(value))
    return " ".join(text.split()).strip().lower()


def strip_tags(cell) -> str:
    """The visible text of a WHOLE cell. For NAME and CHANGE only -- NOT for OI (see
    :func:`anchor_text` and the module docstring)."""
    if cell is None:
        return ""
    text = _TAG_RE.sub("", str(cell))
    return " ".join(text.replace("&nbsp;", " ").split()).strip()


def anchor_text(cell) -> str:
    """The OI cell -> the open interest as published, across all THREE observed shapes.

    ``<a ...>9,202</a><div class='head d-none'>FCPO/Aug 2026</div>...`` -> ``'9,202'``;
    a bare ``'-'`` -> ``'-'``; a bare ``'28'`` -> ``'28'``.

    The anchor is taken SPECIFICALLY. Stripping tags off the whole cell appends the two hidden
    ``<div>``s (``FCPO/Aug 2026``, ``As of``) to the number and yields a string that parses to NaN
    -- silently NULLing open interest on every traded month."""
    if cell is None:
        return ""
    text = str(cell)
    m = _ANCHOR_RE.search(text)
    if m:
        return strip_tags(m.group(1))
    return strip_tags(text)


def parse_number(token) -> float:
    """``'4,534.0000' -> 4534.0``; ``'-'`` / blank -> NaN. Comma thousands separators, 4 dp.

    NOTE what is NOT here: no zero sentinel. CZCE and JSE publish ``0`` for a no-trade and must mask
    it; this venue publishes ``"-"``, so masking zero here would erase true observations."""
    if token is None or isinstance(token, bool):
        return float("nan")
    if isinstance(token, (int, float)):
        return float(token)
    tok = str(token).strip().replace(",", "").replace("\xa0", "").replace(" ", "")
    if tok.lower() in _NULL_TOKENS:
        return float("nan")
    if tok.startswith("+"):
        tok = tok[1:]
    try:
        return float(tok)
    except ValueError:
        return float("nan")


def contract_month_str(month_text: str) -> str:
    """``'Aug 2026' -> '2026-08'``. Fail-closed on anything else."""
    m = _MONTH_RE.match(" ".join(str(month_text or "").split()))
    if not m:
        raise ValueError(f"bursa: {month_text!r} is not a 'MMM YYYY' delivery month")
    month = _MONTHS.get(m.group(1)[:3].lower())
    if month is None:
        raise ValueError(f"bursa: {month_text!r} carries an unknown month name")
    return CONTRACT_MONTH_FMT % (int(m.group(2)), month)


def unwrap(payload) -> tuple[dict, Optional[list]]:
    """One landed raw object -> ``(api_body, thead_or_None)``.

    Two shapes are accepted, deliberately:

      * ``{"thead": [...], "api": {...}}`` -- what the producer lands. The rendered header is a
        SIDE CHANNEL beside the body because the body has no field names at all, and pinning it
        per-run is the JSE precedent;
      * a bare API body -- the captured fixture, and any object landed before the side channel
        existed. The thead check then cannot run, which is recorded in the stats rather than
        silently passed.

    An EMPTY ``thead`` is the SECOND of those cases, not a drift. ``fetch_bursa_fcpo.scrape_thead``
    returns ``[]`` whenever its page evaluate fails, and the producer lands ``{"thead": [], "api":
    ...}`` on purpose -- the documented contract is that a scrape failure degrades the PIN and never
    the prices, because this leg has no history and a refused session is gone for good. Handing that
    ``[]`` on as a list made it a 13-to-0 column drift and hard-failed the whole capture, which is
    the exact opposite of the contract; it is normalized to ``None`` here so there is ONE code path
    for "the pin is unavailable".
    """
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError(f"bursa: the raw object decoded to {type(payload).__name__}, not a JSON "
                         f"object")
    if "api" in payload:
        body = payload.get("api")
        thead = payload.get("thead")
        if not isinstance(body, dict):
            raise ValueError("bursa: the raw wrapper carries no 'api' object -- the capture is "
                             "malformed")
        return body, (list(thead) if isinstance(thead, (list, tuple)) and thead else None)
    return payload, None


def assert_thead(thead: Optional[list]) -> list[str]:
    """PIN THE RENDERED HEADER. Returns the normalized tokens; raises on drift.

    ``None`` -- or an EMPTY sequence, which is what a landed object carries when the producer's
    thead scrape failed -- returns ``[]`` and logs. The check is UNAVAILABLE, not passed, and it is
    emphatically not a 13-to-0 column drift: refusing the capture there would lose the session's
    PRICES over a lost PIN, on a leg whose API serves current prices only and has no re-fetch.
    Everything else is fail-closed: the API body is 13 anonymous positional elements and this header
    is the only thing that says which is which."""
    if not thead:
        logger.warning("bursa: the raw object carries no 'thead' side channel (absent or empty) -- "
                       "the column pin cannot run on this capture (positional map assumed)")
        return []
    cells = list(thead)
    if isinstance(cells[0], (list, tuple)):
        cells = list(cells[-1])                 # a multi-row thead: the LAST row is the labels
    if not cells:
        # A multi-row thead whose label row came back empty. Same fact, same answer.
        logger.warning("bursa: the raw object's 'thead' side channel carries no label cells -- the "
                       "column pin cannot run on this capture (positional map assumed)")
        return []
    seen = [_norm(c) for c in cells]
    if len(seen) != _COLUMN_COUNT:
        raise ValueError(
            f"bursa: the rendered thead has {len(seen)} column(s), expected {_COLUMN_COUNT} "
            f"(tokens seen: {seen}) -- the API's 13 positional elements can no longer be mapped; "
            f"refusing to guess"
        )
    bad: list[str] = []
    for idx, (field, tokens) in enumerate(_HEADER_TOKENS):
        if seen[idx] not in tokens:
            bad.append(f"col {idx} ({field}): {seen[idx]!r} not in {list(tokens)}")
    if bad:
        raise ValueError(
            "bursa: the rendered thead drifted -- " + "; ".join(bad) + f". Full header seen: "
            f"{seen}. The payload is POSITIONAL and carries no field names, so a reordered column "
            f"publishes plausible WRONG numbers rather than failing. Add the upstream spelling to "
            f"_HEADER_TOKENS only after confirming the POSITION is unchanged"
        )
    return seen


def assert_day_session(names: list[str], *, code: str) -> None:
    """HARD FAIL when the payload is the after-hours (T+1) session, or another instrument.

    The night body is a complete, plausible 24-month table with DIFFERENT prices (Aug 2026 settles
    4,557 against the day's 4,540), and the NAME cell is the only discriminator in it. Publishing
    it as the daily settlement is undetectable downstream, which is why this is a hard error and
    not a warning."""
    want = str(code).strip().upper()
    night = sorted({n for n in names if _NIGHT_LABEL in n})
    if night:
        raise ValueError(
            f"bursa: the payload's NAME cell reads {night[0]!r} -- this is the AFTER-HOURS (T+1) "
            f"session, not the ses=day (T) session whose settlement is the daily settlement. The "
            f"night table is complete and plausible with different prices, so it must be a hard "
            f"error: refusing to publish after-hours prices as a settlement"
        )
    alien = sorted({n for n in names if n.upper() != want})
    if alien:
        raise ValueError(
            f"bursa: the payload carries instrument name(s) {alien} but the capture is keyed "
            f"code={want} -- the object is misfiled or the venue's code selector changed"
        )


def build_bronze(payload, *, code: str = "FCPO", as_of_date: str) -> tuple[pd.DataFrame, dict]:
    """One landed Bursa capture -> the bronze rows for ONE product code + a stats dict.

    ``as_of_date`` is the raw key's own segment and is the ONLY trade-date authority on this leg:
    the API body carries no date field and the endpoint has no date parameter. It is REQUIRED --
    a wall-clock fallback would re-date the partition on any re-parse -- and it must be the
    MALAYSIAN calendar day of the T session."""
    slug = slug_for_code(code)
    want_code = str(code).strip().upper()
    if not as_of_date:
        raise ValueError(
            "bursa: as_of_date is required -- the API body carries no date field and the endpoint "
            "has no date parameter, so the raw key's as_of_date= segment is the session's only "
            "authority and a wall-clock fallback would silently re-date the partition"
        )
    session = str(pd.Timestamp(as_of_date).date())

    body, thead = unwrap(payload)
    header = assert_thead(thead)
    data = body.get("data")
    if not isinstance(data, list):
        raise ValueError("bursa: the API body carries no 'data' array -- the capture is not a "
                         "derivatives_prices response")
    declared = body.get("recordsTotal")
    if isinstance(declared, int) and declared != len(data):
        # per_page=50 covers the 24 listed months with room to spare, so a short page means the
        # venue paginated on us and months are MISSING -- never a thin day.
        raise ValueError(
            f"bursa: the body declares recordsTotal={declared} but carries {len(data)} row(s) -- "
            f"the response is paginated or truncated and delivery months are missing; refusing to "
            f"publish a partial curve"
        )

    names: list[str] = []
    rows: list[dict] = []
    for pos, rec in enumerate(data):
        if not isinstance(rec, (list, tuple)):
            raise ValueError(f"bursa: data[{pos}] is {type(rec).__name__}, not the expected "
                             f"{_COLUMN_COUNT}-element positional row")
        if len(rec) != _COLUMN_COUNT:
            raise ValueError(
                f"bursa: data[{pos}] has {len(rec)} element(s), expected {_COLUMN_COUNT} -- the "
                f"positional map cannot be trusted on this row"
            )
        name = strip_tags(rec[_IDX["name"]])
        names.append(name)
        month_text = strip_tags(rec[_IDX["month"]])
        vals = {field: parse_number(strip_tags(rec[_IDX[field]]))
                for field in ("open", "bid", "ask", "last", "change", "high", "low", "volume")}
        # OI is the ONE cell whose value is the ANCHOR text and not the cell text.
        vals["open_interest"] = parse_number(anchor_text(rec[_IDX["open_interest"]]))
        vals["settle"] = parse_number(strip_tags(rec[_IDX["settle"]]))
        rows.append({
            "trade_date": session,
            "leviathan_slug": slug,
            "code": want_code,
            # VERBATIM, and the MONTH cell rather than the NAME cell: NAME is the constant string
            # "FCPO" on all 24 rows and would collapse the F2 key onto one row.
            "raw_symbol": month_text,
            "contract_month": contract_month_str(month_text),
            **vals,
        })

    # AFTER the loop so the diagnostic can name every offending label at once, and BEFORE the frame
    # is handed back so no night row can ever reach silver.
    assert_day_session(names, code=want_code)

    df = pd.DataFrame(rows, columns=BRONZE_COLUMNS)
    if len(df):
        df["trade_date"] = pd.to_datetime(df["trade_date"]).astype("datetime64[us]")
        for col in ("volume", "open_interest"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    settle_rows = int(df["settle"].notna().sum()) if len(df) else 0
    # SETT. PRICE prints for ALL 24 months, quiet back months included. Not one row carrying it is
    # a layout drift, never a thin session -- and the tempting repair (fall back to LAST DONE)
    # would publish a trade as the settlement.
    if len(df) and settle_rows == 0:
        raise ValueError(
            f"bursa {want_code} {session}: not one of {len(df)} row(s) carries a SETT. PRICE. It "
            f"prints for all 24 months on this venue, so this is a layout drift or a pre-close "
            f"capture. Refusing to parse -- and never falling back to LAST DONE, which is a trade "
            f"and not a settlement"
        )
    traded = int(df["volume"].notna().sum()) if len(df) else 0
    stats = {
        "trade_date": session,
        "as_of_date": as_of_date,
        "code": want_code,
        "leviathan_slug": slug,
        "session": BURSA_DAY_SESSION,
        "thead_checked": bool(header),
        "header": header,
        "records_total": declared,
        "rows_kept": int(len(df)),
        "rows_traded": traded,
        "rows_quiet": int(len(df)) - traded,
        "rows_with_settle": settle_rows,
        "rows_with_open_interest": int(df["open_interest"].notna().sum()) if len(df) else 0,
    }
    logger.info("bursa bronze %s %s: %d row(s) (%d traded), settle on %d, OI on %d, thead_pin=%s",
                want_code, session, len(df), traded, settle_rows,
                stats["rows_with_open_interest"], bool(header))
    return df, stats
