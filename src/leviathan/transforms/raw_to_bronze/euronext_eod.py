"""PRICE_AND_PLAYBOOKS W1c -- the Euronext (MATIF) rendered quote table raw -> bronze transform.

WHAT THIS MODULE OWNS
---------------------
The venue-specific half of ``silver_futures_eod``'s Euronext leg, and nothing else:

  * :data:`EURONEXT_PRODUCT_MAP` -- the THREE products this leg keeps, matched by EXACT product
    slug. No unit / currency / settle_kind / source lives here: that authority is
    :mod:`leviathan.silver.futures_eod_contracts`, and an import-time assertion binds this map to
    the ``source == "euronext_matif"`` rows of ``CONTRACT_MAP`` in BOTH directions;
  * the ``thead`` pin and the POSITIONAL cell decode underneath it;
  * the delivery-month decode, read from the row anchor's ``md=DD-MM-YYYY`` query parameter;
  * the ``"-"`` untraded sentinel and the two row shapes.

Pure: BeautifulSoup + pandas + the house logger. No boto3, no S3, no network, no playwright -- the
BROWSER is the producer's problem and this module only ever sees the outerHTML it landed.

WHY THERE IS A BROWSER AT ALL
-----------------------------
Probed live 2026-07-29: a plain-``requests`` GET of the product page returns HTTP 200 and 247 KB of
HTML from BOTH a residential and a Fargate IP -- there is no WAF here. But the quote table is
CLIENT-RENDERED out of an AES ``{ct,iv,s}`` payload, so ``table#future-prices-table`` exists only in
a browser DOM. That is why the raw object is rendered outerHTML rather than the page bytes, and it
is the one place in this estate where "raw" is a DOM snapshot instead of the wire response. The
producer records the source URL in the ``raw_meta`` companion so the provenance is not lost.

THE FIVE THINGS THIS MODULE ENCODES
-----------------------------------
1. **The page carries NO DATE.** Anywhere. The table publishes a ``Time`` column (``18:31``) and the
   rows carry ``data-lasttradesdate`` -- which, despite the name, is a TIME OF DAY and not a date.
   So unlike JSE (header date inside the sheet) and CZCE (date in the file's own title line), this
   leg has NO independent session authority: ``trade_date`` comes from the raw key's ``as_of_date=``
   segment and from nowhere else. :func:`build_bronze` therefore REQUIRES ``as_of_date`` and refuses
   to invent one from the wall clock -- a re-parse of a 2026 object in 2031 must decode identically.
   The corollary is operational and belongs on the leg, not in a runbook: the producer must fire
   after the ~18:30 CET settlement publish and before local midnight, or the session and the key
   disagree with nothing to detect it.
2. **SETTL. is the price of record and is NEVER substituted.** It prints for EVERY row -- including
   the untraded back months, which is the whole reason those rows are worth keeping -- and ``Last``
   is a trade, not a settlement. A row whose ``Settl.`` is absent lands with ``settle`` NULL; the
   ``Last`` value is never promoted into it (the F3 doctrine, verbatim from the Databento GLBX leg).
3. **TWO ROW SHAPES, and the untraded one is not an error.** Traded expiries carry
   Last/Time/+-/Day Vol./Open/High/Low; untraded back months carry ONLY Bid/Ask/Settl./O.I with
   ``"-"`` everywhere else and ``data-lasttradesdate="-"``. The EBM capture is 7 traded + 5 untraded.
   ``"-"`` is the sentinel and maps to NULL -- it is not zero, and (unlike CZCE/JSE) zero is not the
   sentinel here: ``+/-`` legitimately prints ``0.00`` on an unchanged month.
4. **The ``Ask`` column is ``style="display: none"`` -- PRESENT in the DOM, INVISIBLE on screen.**
   A parser written against a screenshot of the page counts 11 columns, is off by one from ``Last``
   onward, and lands the Bid as the Last and the Settl. as the Low. The header pin below is the
   defence: 12 columns in a fixed order, matched by ACCEPTED TOKEN SET per position, and a drift is
   a hard error naming the tokens actually seen. Hidden or not, the cell is a cell.
5. **A SHORT TABLE IS A TRUNCATION, NOT A THIN SESSION.** The header pin says what each column
   MEANS; nothing in it says how many ROWS a complete curve has, and a client-rendered tbody can
   stop halfway with every row it did render being perfectly well formed. So
   :data:`EURONEXT_MIN_ROWS` pins the measured expiry count per product and :func:`build_bronze`
   refuses a short or empty parse -- the only detector this leg has for the shape that would
   otherwise publish as a COMPLETE curve with no error anywhere.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
# EXACT product slugs, as they appear in the live.euronext.com URL. All three were verified live
# 2026-07-29 and carry an IDENTICAL table id and shape:
#   EBM-DPAR "Milling Wheat"   12 expiries
#   EMA-DPAR "Corn / Mais"     10 expiries
#   ECO-DPAR "Rapeseed / Colza" 10 expiries
# No unit / currency / settle_kind / source here on purpose -- see the module docstring.
EURONEXT_PRODUCT_MAP: dict[str, str] = {
    "EBM-DPAR": "french_wheat_matif",
    "EMA-DPAR": "french_maize_matif",
    "ECO-DPAR": "french_rapeseed_matif",
}

# The publication ``source`` value these rows carry, verbatim from CONTRACT_MAP. NOTE that it is
# NOT the raw prefix's ``source=euronext`` segment: one venue fetch lands three products, so the
# raw tree is keyed by VENUE and the silver column by PUBLICATION SOURCE. See
# ``storage.paths.raw_euronext_key``.
EURONEXT_SOURCE = "euronext_matif"

# The id the venue renders. Pinned here rather than in the producer so the fetch-time ready check
# and the parse agree by construction.
EURONEXT_TABLE_ID = "future-prices-table"

# ---------------------------------------------------------------------------
# THE COMPLETENESS FLOOR -- one entry per product, MEASURED, never guessed
# ---------------------------------------------------------------------------
# How many delivery months each product LISTS, counted live 2026-07-29 (capture_notes.md): EBM 12,
# EMA 10, ECO 10. Pinned HERE, beside the table id, for the same reason the table id is: the
# fetch-time ready check, the capture sniff and the parse must all mean the same thing by "the
# table", and a floor that lived only in the producer would let a re-parse of a landed object
# disagree with the capture that landed it.
#
# A FLOOR and not an equality, deliberately: a venue that lists a FURTHER expiry is publishing more
# of the curve, which is never a truncation, while one row fewer is exactly what a partially
# rendered tbody or a venue-side page cut looks like.
#
# WHY IT HAS TO EXIST AT ALL. The table is CLIENT-RENDERED, so "the tbody has some rows" is a moment
# in a render and not a fact about the session. Without this floor a 3-of-12 EBM parses to 3 bronze
# rows with NO error anywhere and publishes as a COMPLETE curve; the per-day silver floor cannot see
# it either, because a 5-row EBM plus a full EMA (10) plus a full ECO (10) is 25 rows and clears the
# 24-row day floor. The Bursa leg carries the equivalent guard as `recordsTotal == len(data)` --
# this venue declares no count of its own, so the count is pinned here instead.
#
# A venue that genuinely DELISTS an expiry is a code change, exactly like a header rename: re-count
# the rendered table and re-pin, having confirmed it is a delisting and not a truncation.
EURONEXT_MIN_ROWS: dict[str, int] = {"EBM-DPAR": 12, "EMA-DPAR": 10, "ECO-DPAR": 10}
# The floor for a product that is not in the curated map. It exists only so the producer's sniff
# helper stays TOTAL (``build_bronze`` never reaches it -- ``slug_for_product`` fails closed on an
# unmapped product first), and 8 is below the thinnest MATIF curve observed rather than a guess.
EURONEXT_MIN_ROWS_FALLBACK = 8

# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------
# THE HEADER PIN. Twelve columns, in order, matched by ACCEPTED TOKEN SET per POSITION (the JSE
# `_FIELD_TOKENS` idiom) rather than by one exact string -- the venue's wording is short and
# punctuated ("Settl.", "O.I", "Day Vol.") and normalizing punctuation away is what makes the match
# stable without making it loose. Position is authoritative once the pin passes; the pin is what
# makes the positional read legal.
#
# `ask` is the hidden column (style="display: none"). It is listed because it EXISTS, and dropping
# it would shift every later index by one.
_HEADER_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("delivery", ("delivery", "delivery month", "expiry", "echeance")),
    ("bid", ("bid",)),
    ("ask", ("ask", "offer")),
    ("last", ("last", "last price", "last traded")),
    ("quote_time", ("time",)),
    ("change", ("", "chg", "change", "var")),          # the venue's own token is "+/-" -> "" once
    ("volume", ("day vol", "day volume", "volume", "vol")),  # punctuation is normalized away
    ("open", ("open",)),
    ("high", ("high",)),
    ("low", ("low",)),
    ("settle", ("settl", "settle", "settlement", "settl price", "settlement price")),
    ("open_interest", ("o i", "oi", "open interest")),
)
_FIELDS: tuple[str, ...] = tuple(f for f, _ in _HEADER_TOKENS)
_COLUMN_COUNT = len(_HEADER_TOKENS)

# The delivery month, preferred source: the row anchor's own query parameter, e.g.
#   .../instrument?Class_symbol=EBM&Class_exchange=DPAR&fOrO=F&md=01-09-2026
# DD-MM-YYYY, and unambiguous -- which the anchor TEXT ("Sep 2026") is not across locales.
_MD_RE = re.compile(r"[?&]md=(\d{2})-(\d{2})-(\d{4})")
# The fallback: the anchor text. English month abbreviations, which is what the /en/ page serves.
_TEXT_MONTH_RE = re.compile(r"^([A-Za-z]{3,10})\s+(\d{4})$")
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

# The untraded sentinel. "-" is the venue's, the rest are defensive.
_NULL_TOKENS = frozenset({"", "-", "--", "n/a", "na", "nan"})

CONTRACT_MONTH_FMT = "%04d-%02d"

# Richer than silver on purpose (bronze is source-faithful); bronze_to_silver projects onto the
# contract's 17 physical + 2 partition columns.
BRONZE_COLUMNS: list[str] = [
    "trade_date", "leviathan_slug", "product", "raw_symbol", "contract_month",
    "bid", "ask", "last", "quote_time", "change", "volume",
    "open", "high", "low", "settle", "open_interest", "traded",
]


def _lint_product_map() -> list[str]:
    """EURONEXT_PRODUCT_MAP must be EXACTLY the ``source == 'euronext_matif'`` slugs of
    CONTRACT_MAP, both ways."""
    errs: list[str] = []
    mapped = set(EURONEXT_PRODUCT_MAP.values())
    curated = {slug for slug, rec in FC.CONTRACT_MAP.items() if rec["source"] == EURONEXT_SOURCE}
    for slug in sorted(mapped - curated):
        errs.append(f"{slug}: in EURONEXT_PRODUCT_MAP but not a source={EURONEXT_SOURCE!r} "
                    f"CONTRACT_MAP slug")
    for slug in sorted(curated - mapped):
        errs.append(f"{slug}: a source={EURONEXT_SOURCE!r} CONTRACT_MAP slug with no Euronext "
                    f"product")
    if len(mapped) != len(EURONEXT_PRODUCT_MAP):
        errs.append("two products map to the same leviathan slug -- the three MATIF products are "
                    "three deliverable contracts")
    # And every product must carry a MEASURED completeness floor. A fourth product added here with
    # no row count would land truncated curves silently, which is the one failure this leg has no
    # other detector for.
    for product in sorted(set(EURONEXT_PRODUCT_MAP) - set(EURONEXT_MIN_ROWS)):
        errs.append(f"{product}: no EURONEXT_MIN_ROWS entry -- count the rendered table's delivery "
                    f"months live and pin them before this product is captured")
    for product in sorted(set(EURONEXT_MIN_ROWS) - set(EURONEXT_PRODUCT_MAP)):
        errs.append(f"{product}: has an EURONEXT_MIN_ROWS floor but is not a curated product")
    return errs


def min_rows_for_product(product: str) -> int:
    """The completeness floor for one product: how many delivery months it must publish.

    TOTAL by design -- an unmapped product answers :data:`EURONEXT_MIN_ROWS_FALLBACK` rather than
    raising, because the caller that can see an unmapped product is the producer's structural sniff
    and its job is to describe the capture, not to adjudicate the product (``slug_for_product`` has
    already refused an unmapped one everywhere the answer is load-bearing)."""
    return EURONEXT_MIN_ROWS.get(str(product or "").strip().upper(), EURONEXT_MIN_ROWS_FALLBACK)


# Import-time fail-closed, the CZCE/JSE precedent: a product map that has drifted from the curated
# contract map must never reach a producer.
assert not _lint_product_map(), \
    "euronext_eod.EURONEXT_PRODUCT_MAP is malformed: " + "; ".join(_lint_product_map())


def slug_for_product(product: str) -> str:
    """The leviathan slug for one Euronext product. FAIL CLOSED -- never guessed."""
    token = str(product or "").strip().upper()
    slug = EURONEXT_PRODUCT_MAP.get(token)
    if slug is None:
        raise ValueError(
            f"euronext: product {product!r} is not one of {sorted(EURONEXT_PRODUCT_MAP)}. A new "
            f"MATIF product is an explicit CONTRACT_MAP decision, not something a parser infers"
        )
    return slug


def _norm(value) -> str:
    """A header cell -> a single-spaced lowercase ASCII token string.

    Punctuation is collapsed to spaces, which is what makes ``"Settl."`` -> ``settl``,
    ``"Day Vol."`` -> ``day vol`` and ``"O.I"`` -> ``o i`` match a curated token without the pin
    having to guess the venue's punctuation. ``"+/-"`` normalizes to the EMPTY string; that is why
    the change column's accepted set carries ``""`` explicitly rather than by accident."""
    if value is None:
        return ""
    text = re.sub(r"[^0-9A-Za-z]+", " ", str(value))
    return " ".join(text.split()).strip().lower()


def parse_number(token) -> float:
    """``'41,367' -> 41367.0``; ``'-'`` / blank -> NaN. Comma thousands separators, no locale.

    NOTE what is NOT here: no zero sentinel. On CZCE and JSE a no-trade prints ``0`` and must be
    masked to NULL; on this venue the no-trade prints ``"-"`` and ``0.00`` is a REAL published value
    (an unchanged ``+/-``). Masking zero here would erase true observations."""
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


def contract_month_from_href(href: str) -> Optional[str]:
    """``'...&md=01-09-2026' -> '2026-09'``; None when the anchor carries no ``md=``.

    PREFERRED over the anchor text: ``md`` is DD-MM-YYYY and unambiguous, while ``"Sep 2026"`` is a
    localized label that the venue is free to change without changing the data."""
    m = _MD_RE.search(str(href or ""))
    if not m:
        return None
    month = int(m.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"euronext: md={m.group(0)!r} carries month {month}, outside 1..12")
    return CONTRACT_MONTH_FMT % (int(m.group(3)), month)


def contract_month_from_text(text: str) -> str:
    """``'Sep 2026' -> '2026-09'``. The FALLBACK path; fail-closed on anything else."""
    m = _TEXT_MONTH_RE.match(" ".join(str(text or "").split()))
    if not m:
        raise ValueError(
            f"euronext: delivery {text!r} is neither an ``md=DD-MM-YYYY`` anchor nor a "
            f"'MMM YYYY' label -- refusing to guess a delivery month"
        )
    month = _MONTHS.get(m.group(1)[:3].lower())
    if month is None:
        raise ValueError(f"euronext: delivery {text!r} carries an unknown month name")
    return CONTRACT_MONTH_FMT % (int(m.group(2)), month)


def find_table(html) -> "BeautifulSoup":
    """The quote table element out of a landed raw object.

    Accepts the table's own outerHTML (what the producer lands) or a whole page. Matched by ID
    first, then -- and only then -- by "the first table carrying a Delivery header", so a venue id
    rename is a WARNING plus a still-correct parse rather than a dead leg. The header pin
    immediately downstream is what makes that fallback safe."""
    text = html.decode("utf-8", errors="replace") if isinstance(html, (bytes, bytearray)) \
        else str(html)
    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table", id=EURONEXT_TABLE_ID)
    if table is not None:
        return table
    for cand in soup.find_all("table"):
        head = cand.find("thead")
        if head is not None and _norm(head.get_text(" ")).startswith("delivery"):
            logger.warning("euronext: table#%s absent; using the first table with a Delivery "
                           "header instead", EURONEXT_TABLE_ID)
            return cand
    raise ValueError(
        f"euronext: no table#{EURONEXT_TABLE_ID} and no table with a 'Delivery' header in the "
        f"landed object ({len(text)} chars) -- the capture is not a rendered quote table. This is "
        f"the shape a page that never finished rendering has; it must be a hard error, because an "
        f"empty parse is indistinguishable from an exchange holiday"
    )


def resolve_header(table) -> list[str]:
    """The ``thead`` cells, normalized -- after asserting they ARE the pinned twelve.

    Fail-closed and never positional-by-hope: an off-by-one from the hidden ``Ask`` column lands the
    Bid as the Last and the Settl. as the Low, which is a plausible WRONG NUMBER rather than an
    error. Returns the observed tokens for the stats dict."""
    head = table.find("thead")
    cells = head.find_all("th") if head is not None else []
    if not cells:
        cells = head.find_all("td") if head is not None else []
    seen = [_norm(c.get_text(" ")) for c in cells]
    if len(seen) != _COLUMN_COUNT:
        raise ValueError(
            f"euronext: the quote table has {len(seen)} header cell(s), expected {_COLUMN_COUNT} "
            f"(tokens seen: {seen}). NOTE the 'Ask' column is style='display: none' -- it is "
            f"PRESENT in the DOM and counted; a parser written against the visible 11 columns is "
            f"off by one from 'Last' onward and lands the Settl. as the Low"
        )
    bad: list[str] = []
    for idx, (field, tokens) in enumerate(_HEADER_TOKENS):
        if seen[idx] not in tokens:
            bad.append(f"col {idx} ({field}): {seen[idx]!r} not in {list(tokens)}")
    if bad:
        raise ValueError(
            "euronext: the quote table header drifted -- " + "; ".join(bad) +
            f". Full header seen: {seen}. Add the upstream spelling to _HEADER_TOKENS; do NOT fall "
            f"back to a positional guess"
        )
    return seen


def _cell_text(cell) -> str:
    return " ".join(cell.get_text(" ").split()).strip()


def build_bronze(payload, *, product: str, as_of_date: str) -> tuple[pd.DataFrame, dict]:
    """One landed Euronext ``table.html`` -> the bronze rows for ONE product + a stats dict.

    ``as_of_date`` is the raw key's own segment and is the ONLY trade-date authority on this leg --
    the rendered table carries no date anywhere (see the module docstring). It is REQUIRED: a
    wall-clock fallback would re-date the partition on any re-parse.

    ``product`` is the Euronext product slug (``EBM-DPAR``); the leviathan slug is derived from it
    through :data:`EURONEXT_PRODUCT_MAP` and never from the page's own title."""
    slug = slug_for_product(product)
    if not as_of_date:
        raise ValueError(
            "euronext: as_of_date is required -- the rendered table publishes a Time but NO date, "
            "so the raw key's as_of_date= segment is the session's only authority and a wall-clock "
            "fallback would silently re-date the partition on a re-parse"
        )
    session = str(pd.Timestamp(as_of_date).date())

    table = find_table(payload)
    header = resolve_header(table)
    body = table.find("tbody") or table
    rows: list[dict] = []
    skipped = 0
    traded_rows = 0
    md_hrefs = 0
    text_fallbacks = 0
    cross_checked = 0
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue                                   # a nested header row, or a spacer
        if len(cells) != _COLUMN_COUNT:
            raise ValueError(
                f"euronext {product} {session}: a body row has {len(cells)} cell(s), expected "
                f"{_COLUMN_COUNT} -- the positional map cannot be trusted on this row "
                f"(row text: {_cell_text(tr)[:120]!r})"
            )
        anchor = cells[0].find("a")
        href = anchor.get("href", "") if anchor is not None else ""
        delivery = _cell_text(anchor if anchor is not None else cells[0])
        if not delivery:
            # A full-width spacer row that still carries 12 empty cells. Counted, never guessed at.
            skipped += 1
            continue
        month = contract_month_from_href(href)
        if month is None:
            month = contract_month_from_text(delivery)
            text_fallbacks += 1
        else:
            md_hrefs += 1
            # CROSS-CHECK the two readings of the same row. `md` is read as DD-MM-YYYY and every
            # observed value is `01-MM-YYYY`, so the fixture alone cannot tell DD-MM from MM-DD --
            # the ONLY evidence for the DD-MM reading is the anchor text beside it. If the venue
            # ever serves MM-DD, all 12 rows decode to month 01 of four distinct years, raw_symbol
            # stays distinct so the F2 key stays unique, and NOTHING fails. It costs one call to a
            # parser that is already written, so the disagreement is a hard error.
            try:
                from_text = contract_month_from_text(delivery)
            except ValueError:
                from_text = None      # a label this parser cannot read is not evidence of a flip
            if from_text is not None:
                if from_text != month:
                    raise ValueError(
                        f"euronext {product} {session}: delivery {delivery!r} decodes to "
                        f"{from_text} from the anchor text but to {month} from the anchor's md= "
                        f"parameter ({href!r}). `md` is read as DD-MM-YYYY; a venue that switched "
                        f"to MM-DD-YYYY would re-date the WHOLE curve with nothing else failing. "
                        f"Refusing to guess which reading is current"
                    )
                cross_checked += 1
        vals = {field: parse_number(_cell_text(cells[idx]))
                for idx, field in enumerate(_FIELDS) if field not in ("delivery", "quote_time")}
        # `Time` is a clock label, not a number: keep it as published text (NULL on an untraded
        # month). It is the only non-numeric measure the table carries.
        quote_time = _cell_text(cells[_FIELDS.index("quote_time")])
        vals["quote_time"] = None if quote_time.lower() in _NULL_TOKENS else quote_time
        # The venue's OWN traded/untraded discriminator, kept verbatim as a boolean. Note the
        # attribute name says "date" and the value is a TIME OF DAY ("18:31") -- it is never a date
        # and is never used as one.
        last_trade = " ".join(str(tr.get("data-lasttradesdate", "")).split()).strip()
        traded = bool(last_trade) and last_trade.lower() not in _NULL_TOKENS
        traded_rows += int(traded)
        rows.append({
            "trade_date": session,
            "leviathan_slug": slug,
            "product": str(product).strip().upper(),
            "raw_symbol": delivery,        # VERBATIM. Never parsed into meaning at ingest.
            "contract_month": month,
            "traded": traded,
            **vals,
        })

    df = pd.DataFrame(rows, columns=BRONZE_COLUMNS)
    if len(df):
        df["trade_date"] = pd.to_datetime(df["trade_date"]).astype("datetime64[us]")
        for col in ("volume", "open_interest"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    # THE COMPLETENESS FLOOR. A zero-row parse is refused for exactly the reason `find_table`
    # refuses a missing table -- an empty parse is indistinguishable from an exchange holiday -- and
    # a SHORT parse is refused because a client-rendered table can stop halfway with every row it
    # did render being perfectly well formed. Neither shape may reach silver as "the curve".
    expected = min_rows_for_product(product)
    if not len(df):
        raise ValueError(
            f"euronext {product} {session}: the landed table parsed to ZERO delivery months. That "
            f"is a rendered SHELL (the venue ships the empty <table> in the server HTML and fills "
            f"the tbody from the decrypted payload), not a thin session -- this venue publishes "
            f"{expected} expiries and never zero. Refusing to parse: an empty frame is "
            f"indistinguishable from an exchange holiday downstream"
        )
    if len(df) < expected:
        raise ValueError(
            f"euronext {product} {session}: the landed table carries {len(df)} delivery month(s), "
            f"expected at least {expected} (measured live 2026-07-29). This is a partially "
            f"rendered tbody or a venue-side truncation -- every row present is well formed, so "
            f"nothing else in the chain can see it, and it would publish as a COMPLETE curve. If "
            f"the venue genuinely delisted an expiry, re-count the rendered table and re-pin "
            f"EURONEXT_MIN_ROWS; do not lower it to make a capture pass"
        )

    settle_rows = int(df["settle"].notna().sum()) if len(df) else 0
    # SETTL. prints for EVERY row on this venue -- traded and untraded alike -- so a table where NOT
    # ONE row carries it is a layout drift or a pre-publish capture, never a thin session. It is a
    # hard error precisely because the tempting repair (fall back to `Last`) would publish a trade
    # as a settlement on the one leg whose settle_kind claims otherwise.
    if len(df) and settle_rows == 0:
        raise ValueError(
            f"euronext {product} {session}: not one of {len(df)} row(s) carries a Settl. value. "
            f"Settlement prints for every row on this venue, so this is either a header drift the "
            f"pin did not catch or a capture taken BEFORE the ~18:30 CET settlement publish. "
            f"Refusing to parse -- and never falling back to Last, which is a trade and not a "
            f"settlement"
        )
    stats = {
        "trade_date": session,
        "as_of_date": as_of_date,
        "product": str(product).strip().upper(),
        "leviathan_slug": slug,
        "header": header,
        "rows_kept": int(len(df)),
        "rows_expected": expected,
        "rows_traded": traded_rows,
        "rows_untraded": int(len(df)) - traded_rows,
        "rows_skipped": skipped,
        "rows_with_settle": settle_rows,
        "delivery_from_href": md_hrefs,
        "delivery_from_text": text_fallbacks,
        "delivery_cross_checked": cross_checked,
    }
    logger.info("euronext bronze %s %s: %d row(s) (%d traded, %d untraded), settle on %d",
                product, session, len(df), traded_rows, len(df) - traded_rows, settle_rows)
    return df, stats
