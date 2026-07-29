"""PRICE_AND_PLAYBOOKS W1a -- the CZCE ``FutureDataDaily.txt`` raw -> bronze transform.

WHAT THIS MODULE OWNS
---------------------
The venue-specific half of ``silver_futures_eod``'s CZCE leg, and nothing else:

  * :data:`CZCE_ROOT_MAP` -- the TWO roots we keep out of the ~26 the file carries, and their
    leviathan slugs. It carries NO unit / currency / settle_kind / source: that authority is
    :mod:`leviathan.silver.futures_eod_contracts` (one table, ten producers, so a per-transform
    unit map is by construction not single-source). An import-time assertion binds this map to the
    ``source == "czce"`` rows of ``CONTRACT_MAP`` in BOTH directions;
  * the POSITIONAL decode of the pipe-delimited file (the header is Chinese -- see below);
  * the 3-digit ``YMM`` contract-code decode, anchored on the FILE's own trade date;
  * the comma-thousands number parse and the ``0.00 == no session`` OHLC sentinel.

Pure: pandas + the house logger. No boto3, no S3, no network, no vendor package.

THE FIVE TRAPS THIS MODULE EXISTS TO NOT FALL INTO
--------------------------------------------------
1. **The header is Chinese, so the mapping is POSITIONAL and never by name.** Fourteen
   pipe-delimited fields, two header rows (a title line carrying the date, then the column line),
   and the column line's own wording DRIFTS across the history: the 2015-10-08 file's first column
   reads one thing and the 2026-07-27 file's reads another, for the same column. A name-based map
   would have silently died at that boundary; the positional map does not notice it.
2. **``OI`` is rapeseed OIL, not cotton.** CZCE cotton is ``CF`` (and ``CY`` is cotton yarn), and
   there is no ``cotton_zce`` contract in ``configs/commodities/`` at all -- the ICE cotton contract
   is a different instrument served from IFUS. Price levels corroborate: ``OI609`` settles ~10,206
   CNY/t (rapeseed oil), ``RM609`` ~2,406 CNY/t (rapeseed meal).
3. **Root selection is EXACT-MATCH on the 2-character root token, never a substring.** The file
   carries 26 roots in 2026 and 17 in 2015; a substring test is the JSE ``WHITE MAIZE`` /
   ``WHITE MAIZE GRADE 2`` defect class, which produces plausible WRONG numbers rather than a
   failure. The row filter is a full-anchor regex on ``^[A-Z]{2}[0-9]{3}$`` -- which also drops the
   two trailer rows (a subtotal and a grand total) that a looser filter would ingest as contracts.
4. **The contract code is 3-digit ``YMM`` and the decade anchor is the FILE DATE.** ``RM609`` is
   September 2026 in the ``trade_date=20260727`` file and September 2016 in the
   ``trade_date=20160727`` one. ``datetime.now()`` would silently re-date ten years of history on
   any backfill re-run -- the same doctrine as the Databento single-digit year code.
5. **The bytes are NOT always UTF-8.** The 2026 files decode as UTF-8; the 2015-10-08 file is
   GB18030 -- and the server sends ``Content-Type: text/plain; charset=utf-8`` for BOTH. The decode
   therefore tries UTF-8, then GB18030, then latin-1, and records which one worked. Every field this
   transform actually reads is pure ASCII in either encoding, so the positional parse is unaffected
   by the choice; the fallback exists so the read does not raise at the 2015 boundary.

SOURCE FIDELITY
---------------
No derived math. ``settle`` is the file's own settlement column (the 7th field), never the close;
``expiry_date`` is not published by this file and is therefore never derived from the delivery
month; there is no FX conversion (a CNY/t settle stays CNY/t).

The one decode that is NOT a pass-through is the ``0.00`` OHLC sentinel: a CZCE contract that did
not trade in a session publishes ``0.00`` for open/high/low/close while still publishing a real
settlement (e.g. ``ZC707 |801.40 |0.00 |0.00 |0.00 |0.00 |801.40 | ...``). Zero is not a possible
price for a CNY/t contract, so it is a SENTINEL, and it is masked to NULL -- the same call the plan
makes explicitly for the JSE MTM sheet ("0 means no trade and must map to NULL, not zero") and the
same class as the Databento undefined-price sentinel masking. It is applied ONLY to
open/high/low/close: ``settle`` is a real published number on those rows, and ``volume`` /
``open_interest`` of 0 are true counts, not sentinels. Every masked row is counted into the stats
dict so the phenomenon is measured rather than assumed.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Roots
# ---------------------------------------------------------------------------
# The two CZCE roots this leg keeps, of the ~26 the daily file carries.
#   RM = rapeseed MEAL, OI = rapeseed OIL.
# No unit / currency / settle_kind / source here on purpose -- see the module docstring.
CZCE_ROOT_MAP: dict[str, str] = {
    "RM": "rapeseed_meal_zce",
    "OI": "rapeseed_oil_zce",
}

# The publication ``source`` value these rows carry, verbatim from CONTRACT_MAP.
CZCE_SOURCE = "czce"

# The venue's first published FutureDataDaily.txt. 2015-10-08 returns 200 (21,982 B, 154 lines);
# 2015-09-07 and every probed date before it return 404. That is a PERMANENT absence, not a gap.
CZCE_FIRST_TRADE_DATE = "2015-10-08"

# The 14 pipe-delimited fields, in file order. THE MAP IS POSITIONAL: the header row is Chinese and
# its wording drifts across the history, so nothing here is ever looked up by name.
#   0 code          1 prev_settle   2 open          3 high          4 low
#   5 close         6 SETTLE        7 change_1      8 change_2      9 volume
#  10 open_interest 11 oi_change   12 turnover     13 delivery_settle (trailing, usually empty)
_COL_CODE = 0
_COL_PREV_SETTLE = 1
_COL_OPEN = 2
_COL_HIGH = 3
_COL_LOW = 4
_COL_CLOSE = 5
_COL_SETTLE = 6
_COL_VOLUME = 9
_COL_OPEN_INTEREST = 10
_COL_OI_CHANGE = 11
_COL_TURNOVER = 12
_FIELD_COUNT = 14

# A data row is EXACTLY two uppercase letters + three digits. Full anchors on both ends: this is
# what keeps `CF` out of a `CF`-substring test, and what drops the subtotal / grand-total trailer
# rows whose first field is a Chinese label.
_CODE_RE = re.compile(r"^([A-Z]{2})([0-9]{3})$")
# The title line carries the session date in plain ASCII: "...(2026-07-27)".
_HEADER_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_HEADER_SNIFF_LINES = 3

# The decode order for the raw bytes. The server claims utf-8 for every session; the 2015 files are
# GB18030. Every field the parse reads is ASCII in both, so this only has to not raise.
_ENCODINGS = ("utf-8", "gb18030", "latin-1")

CONTRACT_MONTH_FMT = "%04d-%02d"

# The bronze frame's columns. Richer than silver on purpose (bronze is source-faithful); the
# bronze_to_silver step projects onto the contract's 17 physical + 2 partition columns.
BRONZE_COLUMNS: list[str] = [
    "trade_date", "leviathan_slug", "root", "raw_symbol", "contract_month",
    "prev_settle", "open", "high", "low", "close", "settle",
    "volume", "open_interest", "oi_change", "turnover",
]


def _lint_root_map() -> list[str]:
    """CZCE_ROOT_MAP must be EXACTLY the ``source == 'czce'`` slugs of CONTRACT_MAP, both ways."""
    errs: list[str] = []
    mapped = set(CZCE_ROOT_MAP.values())
    curated = {slug for slug, rec in FC.CONTRACT_MAP.items() if rec["source"] == CZCE_SOURCE}
    for slug in sorted(mapped - curated):
        errs.append(f"{slug}: in CZCE_ROOT_MAP but not a source={CZCE_SOURCE!r} CONTRACT_MAP slug")
    for slug in sorted(curated - mapped):
        errs.append(f"{slug}: a source={CZCE_SOURCE!r} CONTRACT_MAP slug with no CZCE root")
    for root in sorted(CZCE_ROOT_MAP):
        if not _CODE_RE.match(root + "000"):
            errs.append(f"{root!r}: not a 2-character uppercase CZCE root")
    return errs


# Import-time fail-closed, the yfinance UNIT_MAP == TICKER_MAP precedent: a root map that has
# drifted from the curated contract map must never reach a producer.
assert not _lint_root_map(), "czce_eod.CZCE_ROOT_MAP is malformed: " + "; ".join(_lint_root_map())


def decode_bytes(payload: bytes) -> tuple[str, str]:
    """``(text, encoding)`` for one raw CZCE file. UTF-8, then GB18030, then latin-1.

    The server labels every session ``charset=utf-8``; the 2015 files are GB18030. Nothing the
    parse reads is non-ASCII, so the fallback only has to avoid raising at that boundary."""
    for enc in _ENCODINGS:
        try:
            return payload.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return payload.decode("latin-1", errors="replace"), "latin-1"


def header_trade_date(text: str) -> Optional[str]:
    """The ``YYYY-MM-DD`` in the file's own title line, or None if it is not there.

    Read from the first few lines only -- a date-shaped token deeper in the file is data, not the
    header. Used to CROSS-CHECK the path's trade_date; never as the anchor itself, because a
    misfiled object must be a hard error rather than a silently re-dated partition."""
    for line in text.splitlines()[:_HEADER_SNIFF_LINES]:
        m = _HEADER_DATE_RE.search(line)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def parse_number(token: str) -> float:
    """``'10,078.00' -> 10078.0``; blank / '-' -> NaN. Comma thousands separators, no locale."""
    tok = (token or "").strip().replace(",", "")
    if not tok or tok in {"-", "--"}:
        return float("nan")
    try:
        return float(tok)
    except ValueError:
        return float("nan")


def resolve_contract_year(year_digit: int, trade_date: str) -> int:
    """The FILE-DATE-ANCHORED decade rule for the 3-digit ``YMM`` code's single year digit.

    Of the (at most three) candidate years whose final digit is ``year_digit`` and which sit within
    a decade of the session, take the one whose delivery month is CLOSEST to the session month,
    preferring the FUTURE on a tie. CZCE lists roughly 18 months of delivery months, so the nearest
    candidate is the only reachable one -- and the rule stays correct across a decade boundary in
    both directions (a ``001`` code in a 2029-12 file is 2030-01; a ``912`` code in a 2030-01 file
    is 2029-12).

    The anchor is the session date carried in the raw S3 path segment, NEVER ``datetime.now()``: a
    2031 re-run over the 2016 raw bytes must decode identically."""
    if not 0 <= int(year_digit) <= 9:
        raise ValueError(f"year_digit {year_digit!r} is not a single decimal digit")
    ts = pd.Timestamp(trade_date)
    base = ts.year - (ts.year % 10) + int(year_digit)
    best, best_key = None, None
    for cand in (base - 10, base, base + 10):
        # Distance in months, measured on the year alone (the caller supplies the month separately
        # via `contract_month_str`; the year choice must not depend on which month it is, or two
        # codes one month apart could land a decade apart).
        dist = abs(cand - ts.year)
        key = (dist, 0 if cand >= ts.year else 1)   # tie -> prefer the future
        if best_key is None or key < best_key:
            best, best_key = cand, key
    return int(best)


def contract_month_str(code_digits: str, trade_date: str) -> str:
    """``('609', '2026-07-27') -> '2026-09'``. Fail-closed on a month outside 1..12."""
    if len(code_digits) != 3 or not code_digits.isdigit():
        raise ValueError(f"{code_digits!r} is not a 3-digit CZCE YMM contract code")
    month = int(code_digits[1:])
    if not 1 <= month <= 12:
        raise ValueError(f"{code_digits!r}: delivery month {month} is outside 1..12")
    return CONTRACT_MONTH_FMT % (resolve_contract_year(int(code_digits[0]), trade_date), month)


def build_czce_bronze(payload: bytes, *, trade_date: str) -> tuple[pd.DataFrame, dict]:
    """One raw ``FutureDataDaily.txt`` -> the bronze rows for the TWO kept roots + a stats dict.

    ``trade_date`` is the session the file publishes, taken from the raw key's own
    ``trade_date=YYYYMMDD`` segment. It is both the ``trade_date`` column and the decade anchor. If
    the file's title line carries a date and it DISAGREES, that is a hard error: a misfiled object
    would otherwise re-date a whole partition silently."""
    text, encoding = decode_bytes(payload)
    session = str(pd.Timestamp(trade_date).date())
    stamped = header_trade_date(text)
    if stamped is not None and stamped != session:
        raise ValueError(
            f"CZCE file at trade_date={session} carries the header date {stamped} -- the object is "
            f"misfiled; refusing to parse (the path segment is the decade anchor for every "
            f"contract code in the file)"
        )

    lines = text.splitlines()
    rows: list[dict] = []
    roots_seen: set[str] = set()
    data_rows = 0
    malformed = 0
    zero_ohlc = 0
    for line in lines:
        fields = line.split("|")
        code = fields[_COL_CODE].strip() if fields else ""
        m = _CODE_RE.match(code)
        if not m:
            # The title line, the column line, the subtotal and the grand total all land here.
            # The grand total carries 13.9M lots of volume; a looser row filter publishes it as a
            # contract.
            continue
        root, digits = m.group(1), m.group(2)
        roots_seen.add(root)
        data_rows += 1
        slug = CZCE_ROOT_MAP.get(root)
        if slug is None:
            continue                      # EXACT root match: 24 of the 26 roots are not this leg
        # The delivery-settlement field (14th) is empty on every observed session and its trailing
        # pipe is therefore optional; everything up to the turnover column is not.
        if len(fields) < _FIELD_COUNT - 1:
            malformed += 1
            raise ValueError(
                f"CZCE {session} {code}: {len(fields)} pipe-delimited field(s), expected "
                f"{_FIELD_COUNT} -- the positional map cannot be trusted on this row"
            )
        vals = {
            "prev_settle": parse_number(fields[_COL_PREV_SETTLE]),
            "open": parse_number(fields[_COL_OPEN]),
            "high": parse_number(fields[_COL_HIGH]),
            "low": parse_number(fields[_COL_LOW]),
            "close": parse_number(fields[_COL_CLOSE]),
            "settle": parse_number(fields[_COL_SETTLE]),
            "volume": parse_number(fields[_COL_VOLUME]),
            "open_interest": parse_number(fields[_COL_OPEN_INTEREST]),
            "oi_change": parse_number(fields[_COL_OI_CHANGE]),
            "turnover": parse_number(fields[_COL_TURNOVER]),
        }
        # The no-session sentinel. Zero is not a price; settle and the counts are left alone.
        if all(vals[c] == 0.0 for c in ("open", "high", "low", "close")):
            zero_ohlc += 1
            for c in ("open", "high", "low", "close"):
                vals[c] = float("nan")
        rows.append({
            "trade_date": session,
            "leviathan_slug": slug,
            "root": root,
            "raw_symbol": code,           # VERBATIM. Never parsed into meaning at ingest.
            "contract_month": contract_month_str(digits, session),
            **vals,
        })

    df = pd.DataFrame(rows, columns=BRONZE_COLUMNS)
    if len(df):
        df["trade_date"] = pd.to_datetime(df["trade_date"]).astype("datetime64[us]")
        for col in ("volume", "open_interest", "oi_change"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    stats = {
        "trade_date": session,
        "encoding": encoding,
        "header_date": stamped,
        "raw_lines": len(lines),
        "data_rows": data_rows,
        "roots_seen": len(roots_seen),
        "roots_kept": sorted(set(CZCE_ROOT_MAP) & roots_seen),
        "rows_kept": int(len(df)),
        "zero_ohlc_rows": zero_ohlc,
        "malformed_rows": malformed,
    }
    logger.info("czce bronze %s: %d/%d row(s) kept from %d root(s), encoding=%s",
                session, len(df), data_rows, len(roots_seen), encoding)
    return df, stats
