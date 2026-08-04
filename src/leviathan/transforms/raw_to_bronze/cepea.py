"""PRICE_AND_PLAYBOOKS W1a -- the CEPEA cash-reference raw -> bronze transforms.

TWO PAYLOAD CLASSES, ONE LEG
----------------------------
``cepea`` publishes the two CASH references this estate wants through two different surfaces, and
this module parses both:

  * the DAILY widget (``widgetproduto.js.php``) -- a ~2 KB ``document.write(`...`)`` blob carrying
    a one-row HTML table with the LAST published value only. Parsed by
    :func:`build_cepea_widget_bronze`;
  * the ONE-SHOT history recovery -- a legacy ``.xls`` pulled from web.archive.org, one snapshot of
    which carries the series to its CAPTURE date. The newest captures that exist are **2017**
    (arabica 1996-09-02 .. 2017-07-07, 5,189 data rows; Campinas corn 2004-08-02 .. 2017-10-26,
    3,296 data rows -- spans MEASURED off the landed bytes, corrected 2026-07-29; the earlier
    2025-coverage claim here came from trusting a requested wayback timestamp that had no capture
    behind it). Parsed by :func:`build_cepea_history_bronze`.

Between the 2017 archive captures and the first daily run (2026-07-28) there is a **~9-year hole
in the MIDDLE of both series**. That gap is DOCUMENTED and ACCEPTED (plan W1a, corrected entry),
covered going forward by daily accumulation -- it is not a defect to engineer around, and nothing
here fabricates a value to fill it. Consumers must check spans before reading a window inside it;
see fetch_cepea_wayback_history.py for the full story and the served-capture guard.

Pure: pandas + xlrd + the house logger. No boto3, no S3, no network, no requests.

THE FIVE THINGS THAT MAKE THIS LEG DIFFERENT
--------------------------------------------
1. **These are CASH REFERENCES, not futures.** ``instrument_kind = 'cash_index'`` and
   ``contract_month`` is **NULL** -- and this is the ONLY pair in the whole table for which a null
   delivery month is legal rather than a defect. ``futures_eod_contracts.lint_frame`` enforces the
   iff in BOTH directions, which is why ``row_validator=FC.lint_frame`` is not optional on any
   publish.
2. **The slug comes from the INDICATOR ID, never from the product name.** The name is Portuguese
   and accented (``Cafe Arabica``, ``Milho``); ids 23 and 77 are the vendor's stable identity. The
   name is used only as a curated SANITY token, never as the mapping key.
3. **The unit is asserted against the payload.** ``CONTRACT_MAP`` pins ``BRL/60-kg bag``, and the
   widget states its own basis (``sc de 60kg``). If the venue ever republishes on a different
   basis, a producer that ignored that string would keep writing a now-wrong unit label onto real
   numbers. So the basis token is checked, and a mismatch is a hard error.
4. **The currency marker is asserted too.** The widget renders ``R$``. A flip to ``US$`` must be a
   hard error, never a silent currency mutation -- there is NO FX at ingest anywhere in this table.
5. **The archive workbook publishes ``Data | A vista R$ | A vista US$`` and the USD column is
   DISCARDED.** It is not converted, and it is not stored as a second row. If the USD series is
   ever wanted it is a separate METRIC, never a currency mutation of this one.

WHY THE ARCHIVE READ NEEDS A FLAG
---------------------------------
The archived workbooks are LibreOffice-generated and MALFORMED: ``pandas.read_excel`` / ``xlrd``
raise ``CompDocError: Workbook corruption: seen[2] == 4`` on them. They open only with
``xlrd.open_workbook(file_contents=..., ignore_workbook_corruption=True)``. Sheets are
``['Plan 1', 'Worksheet']``, and the header sits on row 3.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
# The vendor's numeric identity -> the leviathan slug. id 77 is the ESALQ/BM&FBovespa maize
# indicator, which IS the Campinas reference.
CEPEA_INDICATORS: dict[int, str] = {
    23: "brazilian_arabica_coffee",
    77: "campinas_corn_reference_bmf",
}

# A curated ASCII fragment that must appear in the widget's product name, per indicator. This is a
# SANITY token and never the mapping key -- the payload name is accented Portuguese and the id is
# the identity. Chosen to survive accent stripping ("Cafe Arabica" -> "caf...").
_PRODUCT_TOKENS: dict[int, str] = {23: "caf", 77: "milho"}

CEPEA_SOURCE = "cepea"

# The basis the CONTRACT_MAP unit "BRL/60-kg bag" claims, as the widget spells it ("sc de 60kg").
# Normalized to digits+letters, so "sc de 60 kg" and "sc de 60kg" both match.
_UNIT_BASIS_TOKENS = ("60kg", "60 kg")
# The currency marker the widget renders. A flip to US$ is a hard error, never a conversion.
_CURRENCY_MARKER = "R$"

# The daily payload is `document.write(`<html>`)`; the rows live in the tbody.
_TBODY_RE = re.compile(r"<tbody>(.*?)</tbody>", re.IGNORECASE | re.DOTALL)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
# A Brazilian decimal: dot thousands, comma decimals. "1.782,18" / "65,22".
_BRL_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+),(\d{1,4})")

# The archive workbook's header row (0-indexed row 2 = "row 3" as the plan counts it) and the
# columns it declares: Data | A vista R$ | A vista US$.
_HISTORY_HEADER_SEARCH_ROWS = 12
_HISTORY_COL_DATE = 0
_HISTORY_COL_BRL = 1
# _HISTORY_COL_USD = 2 -- deliberately unread. See the module docstring.
_HISTORY_DATE_TOKEN = "data"
_HISTORY_BRL_TOKENS = ("a vista r", "avista r", "vista r")

BRONZE_COLUMNS: list[str] = [
    "trade_date", "leviathan_slug", "indicator_id", "value_brl", "unit_text", "payload_kind",
]

# ---------------------------------------------------------------------------
# D-PR-20 -- the LICENCE that must travel with the bytes, on BOTH routes
# ---------------------------------------------------------------------------
# CEPEA licenses the indicator data CC BY-NC 4.0. The apex-host one-shot
# (fetch_cepea_live_history.py) has recorded this in raw_meta since 2026-07-29; the DAILY widget
# route did not, so the same data under the same licence was documented on one route only. These
# constants are the single definition; both producers pass them through
# ``write_raw_s3_metadata(extra=...)``, and a unit test pins them equal so the two routes cannot
# drift apart again. raw_metadata.py:81-83 documents ``extra`` as existing for exactly this.
CEPEA_LICENSE = ("CC BY-NC 4.0 (CEPEA 'Licenca de uso de dados'; non-commercial use with "
                 "attribution)")
CEPEA_ATTRIBUTION = "Data: CEPEA/ESALQ (cepea.org.br)"

# ---------------------------------------------------------------------------
# D-PR-19 -- the SERVED-DATE verdict (the producer half of land-and-declare)
# ---------------------------------------------------------------------------
# The widget serves the LAST PUBLISHED value only -- there is no window parameter and no series.
# So the one fact a capture can assert about itself is the date the vendor printed NEXT TO the
# value. Three outcomes, and they are not symmetric:
#
#   fresh            served == the expected session. The capture holds a session nobody has.
#   stale_reserve    served <  the expected session. The widget is re-serving an OLDER session.
#                    From ONE capture this is genuinely ambiguous -- a Brazilian holiday and a
#                    capture taken before publication produce byte-identical payloads (the plan
#                    says so, and it is why B3, a curated BR holiday calendar, was rejected on
#                    doctrine). What is NOT ambiguous is that the payload carries no new session,
#                    so landing it can only ever produce a row that already exists.
#   ahead_of_session served >  the expected session. The venue cannot publish a session that has
#                    not happened, so this means the SESSION MODEL is wrong (a bad --as-of, a
#                    timezone slip, a vendor date-format change). Hard failure, never landed.
#
# Business days here are Mon-Fri ONLY. That is not a holiday calendar and does not pretend to be
# one: a weekend is not a session at any venue on earth, whereas which weekdays Brazil trades is
# precisely the question this module refuses to answer from a curated list.
SERVED_FRESH = "fresh"
SERVED_STALE = "stale_reserve"
SERVED_AHEAD = "ahead_of_session"

# CEPEA publishes on Brazil time. Brazil abolished DST in 2019, so America/Sao_Paulo is a FIXED
# UTC-3 -- and if it were ever reinstated (UTC-2) the publication moves EARLIER in UTC, which is
# the harmless direction. A fixed offset here needs no tz database in the worker image.
BRT_UTC_OFFSET_HOURS = -3


def served_date_from_widget(payload) -> str:
    """The date the widget PRINTS NEXT TO the value it is serving, as ``YYYY-MM-DD``.

    This is the same cell :func:`build_cepea_widget_bronze` turns into ``trade_date`` -- the first
    ``<td>`` of the value row -- read here without the semantic assertions so the PRODUCER can
    decide whether to land at all before the transform ever runs. When a payload carries more than
    one dated row the LATEST is the served session, matching the ``trade_date.max()`` the bronze
    stats report.

    Raises rather than returning None: on this leg an undated payload is a hard failure, never a
    quiet no-op (the same rule as a Cloudflare challenge body)."""
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
    body = _TBODY_RE.search(text)
    if not body:
        raise ValueError(
            "cepea: the payload carries no <tbody> -- there is no served date to assert. A "
            "Cloudflare challenge body lands here too and must stay a hard failure"
        )
    dates: list[str] = []
    for tr in _TR_RE.findall(body.group(1)):
        cells = [_text(td) for td in _TD_RE.findall(tr)]
        if not cells:
            continue
        m = _DATE_RE.search(cells[0])
        if m:
            dates.append(f"{m.group(3)}-{m.group(2)}-{m.group(1)}")
    if not dates:
        raise ValueError(
            "cepea: the widget table carried no dated row -- the served session cannot be "
            "established, and a capture that cannot name its own session must not be landed"
        )
    return max(dates)


def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def previous_business_day(day) -> str:
    """The latest Mon-Fri day at or before ``day``, as ``YYYY-MM-DD``. Weekends only."""
    d = _as_date(day)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def session_for_capture(capture_instant: Optional[datetime] = None) -> str:
    """The session a capture taken at ``capture_instant`` (UTC) is expected to serve.

    The scheduled fire is ``cron(30 22 ? * MON-FRI *)`` -- 22:30Z is 19:30 BRT on the SAME calendar
    day, ~90 min after the descriptor's stated ~21:00Z publication -- so in production this is just
    "today in Brazil". It is computed from the BRT instant rather than the UTC date anyway, because
    a hand-run at 01:00Z is a different Brazilian day and would otherwise be judged against a
    session that has not happened."""
    now = capture_instant or datetime.now(tz=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    brt = now.astimezone(timezone.utc) + timedelta(hours=BRT_UTC_OFFSET_HOURS)
    return previous_business_day(brt.date())


def business_days_between(start, end) -> int:
    """Mon-Fri days in ``(start, end]``. Negative when ``end`` precedes ``start``. 0 when equal."""
    lo, hi = _as_date(start), _as_date(end)
    if lo == hi:
        return 0
    sign, a, b = (1, lo, hi) if lo < hi else (-1, hi, lo)
    count = 0
    cur = a + timedelta(days=1)
    while cur <= b:
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return sign * count


def classify_served_date(served_date: str, expected_session: str) -> tuple[str, int]:
    """``(verdict, served_lag_business_days)`` for one capture. See the verdict block above.

    The lag is business days from the SERVED session to the EXPECTED one, so a clean scheduled
    capture reports 0 and a capture taken before publication on a normal Wednesday reports 1. It is
    NEGATIVE in the ``ahead_of_session`` case, which is the shape that makes a bad ``--as-of``
    obvious in ``raw_meta`` rather than merely absent."""
    lag = business_days_between(served_date, expected_session)
    if lag == 0 and _as_date(served_date) == _as_date(expected_session):
        return SERVED_FRESH, 0
    if _as_date(served_date) > _as_date(expected_session):
        return SERVED_AHEAD, lag
    return SERVED_STALE, max(lag, 1)


def _lint_indicator_map() -> list[str]:
    """CEPEA_INDICATORS must be EXACTLY the ``source == 'cepea'`` slugs of CONTRACT_MAP, and those
    slugs must be exactly the map's CASH_INDEX_SLUGS -- the pair whose rows may carry a NULL
    contract_month."""
    errs: list[str] = []
    mapped = set(CEPEA_INDICATORS.values())
    curated = {slug for slug, rec in FC.CONTRACT_MAP.items() if rec["source"] == CEPEA_SOURCE}
    for slug in sorted(mapped - curated):
        errs.append(f"{slug}: in CEPEA_INDICATORS but not a source={CEPEA_SOURCE!r} slug")
    for slug in sorted(curated - mapped):
        errs.append(f"{slug}: a source={CEPEA_SOURCE!r} CONTRACT_MAP slug with no CEPEA indicator")
    if mapped != set(FC.CASH_INDEX_SLUGS):
        errs.append(f"CEPEA_INDICATORS values {sorted(mapped)} != CASH_INDEX_SLUGS "
                    f"{sorted(FC.CASH_INDEX_SLUGS)} -- only cash references may carry a NULL "
                    f"contract_month, and this leg is the only producer of them")
    if set(_PRODUCT_TOKENS) != set(CEPEA_INDICATORS):
        errs.append("every indicator needs a curated product sanity token")
    return errs


assert not _lint_indicator_map(), \
    "cepea.CEPEA_INDICATORS is malformed: " + "; ".join(_lint_indicator_map())


def slug_for_indicator(indicator_id: int) -> str:
    """The leviathan slug for a CEPEA indicator id. FAIL CLOSED -- never guessed from the name."""
    slug = CEPEA_INDICATORS.get(int(indicator_id))
    if slug is None:
        raise ValueError(
            f"CEPEA indicator id {indicator_id!r} is not curated (known: "
            f"{sorted(CEPEA_INDICATORS)}) -- add the mapping; never derive the slug from the "
            f"Portuguese product name"
        )
    return slug


def _ascii_fold(text: str) -> str:
    """Accented Portuguese -> a lowercase ASCII-ish token string, for the SANITY checks only."""
    import unicodedata

    folded = unicodedata.normalize("NFKD", str(text))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(folded.encode("ascii", "ignore").decode("ascii").split()).lower()


def parse_brl(token: str) -> float:
    """``'1.782,18' -> 1782.18``; ``'65,22' -> 65.22``. Brazilian separators, no locale.

    Fail-closed rather than NaN-closed: on this leg a blank value means the widget served nothing,
    and writing a NULL cash reference would be a stale-looking row rather than an honest absence."""
    m = _BRL_RE.search(str(token or ""))
    if not m:
        raise ValueError(f"cepea: {token!r} carries no BRL decimal (expected '1.782,18' form)")
    return float(m.group(1).replace(".", "") + "." + m.group(2))


def _text(html: str) -> str:
    return " ".join(_TAG_RE.sub(" ", html).split())


def build_cepea_widget_bronze(payload: bytes, *, indicator_id: int,
                              as_of_date: Optional[str] = None) -> tuple[pd.DataFrame, dict]:
    """One raw daily widget capture -> ONE bronze row + a stats dict.

    ``as_of_date`` is the FETCH day from the raw key and is carried for audit only. The value's own
    date comes out of the payload: on a Brazilian holiday (Carnival is the named risk) the widget
    keeps serving the PREVIOUS session, so conflating the two would write a stale duplicate under
    today's date -- which is exactly the failure the plan says the producer must not commit."""
    slug = slug_for_indicator(indicator_id)
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)
    body = _TBODY_RE.search(text)
    if not body:
        raise ValueError(
            f"cepea indicator {indicator_id}: the payload carries no <tbody> -- this is not a "
            f"widget response. A Cloudflare challenge body lands here too, and it MUST be a hard "
            f"failure: an empty result would silently write nothing on a table with no freshness "
            f"alarm yet"
        )
    rows: list[dict] = []
    unit_text = ""
    for tr in _TR_RE.findall(body.group(1)):
        cells = [_text(td) for td in _TD_RE.findall(tr)]
        if len(cells) < 3:
            continue
        date_cell, product_cell, value_cell = cells[0], cells[1], cells[2]
        m = _DATE_RE.search(date_cell)
        if not m:
            continue
        folded = _ascii_fold(product_cell)
        token = _PRODUCT_TOKENS[int(indicator_id)]
        if token not in folded:
            raise ValueError(
                f"cepea indicator {indicator_id}: product name {product_cell!r} does not carry the "
                f"curated token {token!r} -- the widget is serving a DIFFERENT indicator and the "
                f"id -> slug mapping would mislabel it"
            )
        basis = folded.replace(".", "")
        if not any(t in basis for t in _UNIT_BASIS_TOKENS):
            raise ValueError(
                f"cepea indicator {indicator_id}: the payload basis {product_cell!r} is not the "
                f"60-kg bag that CONTRACT_MAP pins as {FC.contract_for(slug)['unit']!r} -- the "
                f"venue changed the quotation basis and the unit label would now be wrong on real "
                f"numbers"
            )
        if _CURRENCY_MARKER not in value_cell:
            raise ValueError(
                f"cepea indicator {indicator_id}: value cell {value_cell!r} carries no "
                f"{_CURRENCY_MARKER!r} marker -- refusing to read a possibly-USD figure into a BRL "
                f"column. There is no FX conversion at ingest, ever"
            )
        rows.append({
            "trade_date": f"{m.group(3)}-{m.group(2)}-{m.group(1)}",
            "leviathan_slug": slug,
            "indicator_id": int(indicator_id),
            "value_brl": parse_brl(value_cell),
            # ASCII-FOLDED on purpose. The upstream string is accented Portuguese
            # ("Cafe Arabica" with two accents), this value rides the stats dict into the batch
            # log, and a Windows cp1252 console raises on a non-ASCII write. The fold is lossless
            # for what this field is FOR -- a human-readable basis note.
            "unit_text": _ascii_fold(product_cell),
            "payload_kind": "widget",
        })
        unit_text = rows[-1]["unit_text"]
    if not rows:
        raise ValueError(
            f"cepea indicator {indicator_id}: the widget table carried no dated value row -- an "
            f"empty result is a hard failure on this leg, never a quiet no-op"
        )
    df = _finalize(rows)
    stats = {
        "indicator_id": int(indicator_id),
        "leviathan_slug": slug,
        "as_of_date": as_of_date,
        "payload_kind": "widget",
        "payload_bytes": len(payload) if isinstance(payload, bytes) else len(text),
        "rows_kept": int(len(df)),
        "trade_date": str(df["trade_date"].max())[:10],
        "unit_text": unit_text,
    }
    logger.info("cepea widget bronze id=%s (%s): %s = %.2f BRL",
                indicator_id, slug, stats["trade_date"], float(df["value_brl"].iloc[-1]))
    return df, stats


def _history_grid(payload: bytes) -> list[list]:
    """The archived workbook as a list-of-rows.

    ``ignore_workbook_corruption=True`` is MANDATORY here, not defensive: these books are
    LibreOffice-generated and malformed, and both pandas and a plain xlrd open raise
    ``CompDocError: Workbook corruption: seen[2] == 4`` without it."""
    import xlrd  # lazy: a [batch] extra; the module must import without it

    book = xlrd.open_workbook(file_contents=payload, ignore_workbook_corruption=True,
                              formatting_info=False)
    best = None
    for sheet in book.sheets():
        if best is None or sheet.nrows > best.nrows:
            best = sheet
    if best is None or best.nrows == 0:
        raise ValueError("cepea history: the workbook carries no non-empty sheet")
    return [[best.cell_value(r, c) for c in range(best.ncols)] for r in range(best.nrows)]


def _history_first_data_row(grid: list[list]) -> int:
    """The row index after the ``Data | A vista R$ | A vista US$`` header."""
    for r in range(min(len(grid), _HISTORY_HEADER_SEARCH_ROWS)):
        cells = [_ascii_fold(c) for c in grid[r]]
        if not cells:
            continue
        if cells[_HISTORY_COL_DATE].startswith(_HISTORY_DATE_TOKEN) and len(cells) > _HISTORY_COL_BRL \
                and any(cells[_HISTORY_COL_BRL].startswith(t) for t in _HISTORY_BRL_TOKENS):
            return r + 1
    raise ValueError(
        "cepea history: no 'Data | A vista R$' header row found in the first "
        f"{_HISTORY_HEADER_SEARCH_ROWS} rows -- refusing to read the series positionally, because "
        f"column 2 is the US$ series and reading it into a BRL column is a silent currency mutation"
    )


def _history_date(value) -> Optional[str]:
    """A workbook date cell -> ``YYYY-MM-DD``; None when the cell is not a date."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        # An Excel serial date. 1900 date system; the archive books are all post-1996.
        try:
            return str((pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(value))).date())
        except (ValueError, OverflowError):
            return None
    m = _DATE_RE.search(str(value or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def build_cepea_history_bronze(payload: bytes, *, indicator_id: int,
                               snapshot_ts: Optional[str] = None,
                               payload_kind: str = "wayback") -> tuple[pd.DataFrame, dict]:
    """One archived CEPEA series workbook -> the whole series as bronze rows + a stats dict.

    Reads column 0 (``Data``) and column 1 (``A vista R$``) ONLY. Column 2 is ``A vista US$`` and
    is DISCARDED: it is neither converted nor stored as a second row, because a currency is not a
    mutation of this metric -- if the USD series is ever wanted it is a separate metric."""
    return build_cepea_history_from_grid(_history_grid(payload), indicator_id=indicator_id,
                                         snapshot_ts=snapshot_ts, payload_kind=payload_kind)


def build_cepea_history_from_grid(grid: list[list], *, indicator_id: int,
                                  snapshot_ts: Optional[str] = None,
                                  payload_kind: str = "wayback") -> tuple[pd.DataFrame, dict]:
    """The archive parse proper, over an already-read cell grid.

    Split from :func:`build_cepea_history_bronze` at the OLE boundary so the header resolve, the
    USD-column exclusion and the date/number handling are all testable hermetically -- no library
    in this estate can WRITE a legacy .xls to build a fixture from."""
    slug = slug_for_indicator(indicator_id)
    start = _history_first_data_row(grid)
    rows: list[dict] = []
    skipped = 0
    for row in grid[start:]:
        if not row:
            continue
        day = _history_date(row[_HISTORY_COL_DATE])
        if day is None:
            skipped += 1
            continue
        raw_value = row[_HISTORY_COL_BRL] if len(row) > _HISTORY_COL_BRL else ""
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            value = float(raw_value)
        else:
            try:
                value = parse_brl(raw_value)
            except ValueError:
                skipped += 1
                continue
        if value <= 0.0:
            # A zero "price" in a cash-reference series is an upstream placeholder, not a print.
            # Measured 2026-07-29: the 2017 corn export carries 30/12/2004 = 0.0/0.0 where CEPEA's
            # current record prints 17.37 (curve-consistent between 17.36 and 17.03) -- the one
            # row, out of 8,487 overlapping days, on which the archive and the live export
            # disagreed. Keeping the zero would either publish a fake price or (with both
            # payloads landed) trip F2 uniqueness on a placeholder. Absence is absence.
            skipped += 1
            continue
        rows.append({
            "trade_date": day,
            "leviathan_slug": slug,
            "indicator_id": int(indicator_id),
            "value_brl": value,
            "unit_text": "",
            "payload_kind": payload_kind,
        })
    if not rows:
        raise ValueError(
            f"cepea history id={indicator_id}: the workbook yielded no dated BRL rows -- the "
            f"snapshot is empty or the layout changed"
        )
    df = _finalize(rows)
    stats = {
        "indicator_id": int(indicator_id),
        "leviathan_slug": slug,
        "payload_kind": payload_kind,
        "snapshot_ts": snapshot_ts,
        "header_row": start - 1,
        "rows_kept": int(len(df)),
        "rows_skipped": skipped,
        "first_trade_date": str(df["trade_date"].min())[:10],
        "last_trade_date": str(df["trade_date"].max())[:10],
    }
    logger.info("cepea history bronze id=%s (%s): %d row(s), %s .. %s",
                indicator_id, slug, len(df), stats["first_trade_date"], stats["last_trade_date"])
    return df, stats


def _finalize(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=BRONZE_COLUMNS)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).astype("datetime64[us]")
    df["indicator_id"] = df["indicator_id"].astype("int64")
    df["value_brl"] = pd.to_numeric(df["value_brl"], errors="coerce").astype("float64")
    return df.sort_values(["leviathan_slug", "trade_date"], kind="mergesort").reset_index(drop=True)
