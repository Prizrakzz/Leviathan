"""PRICE_AND_PLAYBOOKS W1b -- the MIAX Futures (ex-MGEX) daily settlement CSV raw -> bronze.

SOURCE
------
    https://www.miaxglobal.com/sites/default/files/mgex/daily-settlement/
        Public_Daily_Settlement_File_{YYYY-MM-DD}.csv

Quoted CSV, nine columns, probed live 2026-07-28 (HTTP 200, ``text/csv``, 6,676 B, 76 lines) and
re-read 2026-07-29::

    "Trade_Date","Instrument","Prev_Settle","Open","High","Low","Settle","Change","Last_Update_DateTime"
    "7/28/26","MWEU6","7.0625","7.0400","7.0600","6.9550","7.0250","-0.0375","7/28/2026 2:35:30 PM"

Pure: pandas + the house logger. No boto3, no S3, no network, no vendor package.

THE SIX THINGS THIS MODULE ENCODES
----------------------------------
1. **The unit is DOLLARS per bushel, and the value is never scaled.** ``MWEU6`` settles ``7.0250``
   while CBOT corn settles ~430 -- the same grain family quoted a factor of 100 apart, because MGEX
   publishes decimal dollars and CBOT quotes cents. ``CONTRACT_MAP`` was corrected to ``USD/bushel``
   against this file; the alternative (multiplying by 100 to fit the CBOT convention) would have
   made the stored number a derivation rather than an observation. The vocabulary moves, the data
   never does -- the ``CAD/t`` canola precedent.
2. **Options and outrights share ONE file.** 75 rows on 2026-07-28: 7 outright futures and 68
   options. The discriminator is a SPACE in the instrument token (``OMWH7 C6.50``), and the outright
   filter is ``" " not in Instrument`` plus a full-anchor root+month+year regex. NOT an ``MW``
   prefix test -- the option roots are ``OMWH`` / ``OMWU`` / ``OMWZ`` and a prefix test that caught
   them would land 68 strike rows as if they were delivery months.
3. **The contract year digit is SINGLE, so it needs a decade anchor**, and the only correct one is
   the file's own ``Trade_Date`` -- never ``datetime.now()``. ``MWEU6`` is September 2026 in the
   2026 file and September 2016 in a 2016 one. Same doctrine as the CZCE ``YMM`` code and the
   Databento single-digit year.
4. **There is NO volume and NO open interest in this file, at all.** CZCE and JSE both carry them;
   MIAX publishes them only in a separate PDF that is not part of this leg. Both columns are
   therefore NULL BY SOURCE for ``hard_red_spring_wheat_mgex``, which is exactly why
   ``futures_roll.ROLL_METHOD_BY_SOURCE`` routes ``miax -> delivery_cycle`` rather than to the
   open-interest rule: the fallback IS the rule here, not a degradation.
5. **Option rows carry EMPTY (not zero) Open/High/Low.** They are filtered out before that matters,
   but the empty-vs-zero distinction is recorded because it is the opposite of the CZCE and JSE
   sentinel: on those venues a no-trade prints ``0`` and must be masked to NULL; here it prints
   ``""`` and parses to NaN with no mask needed.
6. **The CSV horizon starts 2025-09-09 and that is a WALL, not a truncated listing.** See
   :data:`MIAX_CSV_FIRST_TRADE_DATE`.

The Databento catalog has no MGEX/MIAX at all (29 datasets; ``MWE``/``MW`` -> HTTP 422 and ``MWN``
resolves to a Treasury contract, not wheat), and HRSW has no pre-Databento yfinance fallback -- so
this free-first producer is the only price surface this contract will ever have.
"""
from __future__ import annotations

import csv
import io
import re
from typing import Optional

import pandas as pd

from leviathan.common.logging import get_logger
from leviathan.silver import futures_eod_contracts as FC

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Roots
# ---------------------------------------------------------------------------
# MIAX lists HRSW under one product whose CSV instrument root is MWE + the CME month code. The
# leviathan slug is per PRODUCT, so all five month roots map to the same contract.
MIAX_PRODUCT_ROOT = "MWE"
MIAX_ROOT_MAP: dict[str, str] = {MIAX_PRODUCT_ROOT: "hard_red_spring_wheat_mgex"}

MIAX_SOURCE = "miax"

# ---------------------------------------------------------------------------
# THE HISTORY BOUNDARY (probe P1a, 2026-07-28)
# ---------------------------------------------------------------------------
# The machine-readable CSV exists from 2025-09-09 forward: 222 files listed on the canonical index,
# and four probed pre-boundary dates (2025-09-08, 2025-06-02, 2024-07-29, 2023-09-18) ALL return a
# 63,668-byte Drupal 404 page. So the wall is real, not a paginated listing.
#
# 2023-06-01 .. 2025-09-08 exists as PDF ONLY (Public_Daily_Settlement_Report_{DATE}.pdf, plus a
# legacy {YYYYMMDD}.pdf naming before 2023-09-15), and NOTHING exists before 2023-06-01 anywhere on
# the site. MIAX's historical-market-data product page offers options and equities feeds only --
# futures/HRSW are not sold there either. The PDF tier is OUT OF SCOPE for this wave: recovering it
# is a table-extraction job with its own naming break, and it must be an explicit decision rather
# than something a backfill loop wanders into and silently half-does.
MIAX_CSV_FIRST_TRADE_DATE = "2025-09-09"
MIAX_PDF_FIRST_TRADE_DATE = "2023-06-01"

# The nine CSV columns, by NAME: unlike CZCE this header is ASCII, stable and self-describing, so a
# name-based map is the honest choice here and a positional one would be the fragile one. The names
# are asserted on every read.
_REQUIRED_COLUMNS = ("Trade_Date", "Instrument", "Prev_Settle", "Open", "High", "Low", "Settle",
                     "Change", "Last_Update_DateTime")

# An OUTRIGHT instrument: root + one CME month code + one year digit, fully anchored. An option is
# "OMWH7 C6.50" -- the space alone excludes it, and the anchors exclude everything else.
_INSTRUMENT_RE = re.compile(r"^([A-Z]{2,4})([FGHJKMNQUVXZ])([0-9])$")
# The CME month codes, in calendar order.
_MONTH_CODES = {c: i for i, c in enumerate("FGHJKMNQUVXZ", start=1)}
# "7/28/26" -- M/D/YY with a two-digit year.
_TRADE_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")

CONTRACT_MONTH_FMT = "%04d-%02d"

BRONZE_COLUMNS: list[str] = [
    "trade_date", "leviathan_slug", "root", "raw_symbol", "contract_month",
    "prev_settle", "open", "high", "low", "settle", "change", "last_update",
]


def _lint_root_map() -> list[str]:
    """MIAX_ROOT_MAP must be EXACTLY the ``source == 'miax'`` slugs of CONTRACT_MAP, both ways."""
    errs: list[str] = []
    mapped = set(MIAX_ROOT_MAP.values())
    curated = {slug for slug, rec in FC.CONTRACT_MAP.items() if rec["source"] == MIAX_SOURCE}
    for slug in sorted(mapped - curated):
        errs.append(f"{slug}: in MIAX_ROOT_MAP but not a source={MIAX_SOURCE!r} CONTRACT_MAP slug")
    for slug in sorted(curated - mapped):
        errs.append(f"{slug}: a source={MIAX_SOURCE!r} CONTRACT_MAP slug with no MIAX root")
    return errs


assert not _lint_root_map(), \
    "miax_eod.MIAX_ROOT_MAP is malformed: " + "; ".join(_lint_root_map())


def resolve_trade_date(token: str) -> str:
    """``'7/28/26' -> '2026-07-28'``. Two-digit years resolve into the 2000s.

    The file's own ``Trade_Date`` is the session AND the decade anchor for the single-digit contract
    year. MIAX's CSV horizon opens in 2025 and the two-digit form cannot reach back past 2000, so
    the century rule is unambiguous over every date this leg can ever see."""
    m = _TRADE_DATE_RE.match(str(token or "").strip())
    if not m:
        raise ValueError(f"miax: Trade_Date {token!r} is not M/D/YY or M/D/YYYY")
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    return f"{year:04d}-{month:02d}-{day:02d}"


def resolve_contract_year(year_digit: int, trade_date: str) -> int:
    """The FILE-DATE-ANCHORED decade rule for the single year digit in ``MWEU6``.

    Of the candidate years within a decade of the session whose final digit matches, take the
    NEAREST, preferring the future on a tie. HRSW lists ~18 months out, so the nearest candidate is
    the only reachable one, and the rule stays correct across a decade boundary in both directions.
    The anchor is the file's own Trade_Date, never ``datetime.now()``: a re-run in 2035 over the
    2026 raw bytes must decode identically."""
    if not 0 <= int(year_digit) <= 9:
        raise ValueError(f"year_digit {year_digit!r} is not a single decimal digit")
    ts = pd.Timestamp(trade_date)
    base = ts.year - (ts.year % 10) + int(year_digit)
    best, best_key = None, None
    for cand in (base - 10, base, base + 10):
        key = (abs(cand - ts.year), 0 if cand >= ts.year else 1)
        if best_key is None or key < best_key:
            best, best_key = cand, key
    return int(best)


def contract_month_str(month_code: str, year_digit: str, trade_date: str) -> str:
    """``('U', '6', '2026-07-28') -> '2026-09'``."""
    month = _MONTH_CODES.get(str(month_code).upper())
    if month is None:
        raise ValueError(f"miax: {month_code!r} is not a CME month code")
    return CONTRACT_MONTH_FMT % (resolve_contract_year(int(year_digit), trade_date), month)


def parse_number(token) -> float:
    """``'7.0250' -> 7.025``; blank -> NaN. Option rows publish EMPTY (never 0) OHL."""
    if token is None or isinstance(token, bool):
        return float("nan")
    if isinstance(token, (int, float)):
        return float(token)
    tok = str(token).strip().replace(",", "")
    if not tok or tok in {"-", "--"}:
        return float("nan")
    try:
        return float(tok)
    except ValueError:
        return float("nan")


def is_outright(instrument: str) -> bool:
    """True for a listed delivery month; False for an option (``OMWH7 C6.50``) or anything else."""
    return bool(_INSTRUMENT_RE.match(str(instrument or "").strip()))


def build_miax_bronze(payload: bytes, *, trade_date: Optional[str] = None
                      ) -> tuple[pd.DataFrame, dict]:
    """One raw settlement CSV -> the OUTRIGHT bronze rows + a stats dict.

    ``trade_date`` is the session from the raw key's own ``trade_date=`` segment. It is
    CROSS-CHECKED against the file's ``Trade_Date`` column and a disagreement is a hard error: a
    misfiled object would otherwise re-date a whole partition and re-anchor every contract code in
    it. When omitted, the file's own column is the authority."""
    text = payload.decode("utf-8-sig", errors="replace") if isinstance(payload, bytes) \
        else str(payload)
    reader = csv.DictReader(io.StringIO(text))
    header = reader.fieldnames or []
    missing = [c for c in _REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(
            f"miax: the CSV is missing column(s) {missing} (header seen: {header}) -- the file "
            f"layout changed and the name-based map cannot be trusted"
        )

    want = str(pd.Timestamp(trade_date).date()) if trade_date else None
    rows: list[dict] = []
    roots_seen: set[str] = set()
    data_rows = option_rows = 0
    file_dates: set[str] = set()
    for rec in reader:
        instrument = (rec.get("Instrument") or "").strip()
        if not instrument:
            continue
        data_rows += 1
        session = resolve_trade_date(rec.get("Trade_Date"))
        file_dates.add(session)
        if want is not None and session != want:
            raise ValueError(
                f"miax file at trade_date={want} carries the row date {session} -- the object is "
                f"misfiled; refusing to parse (the path segment is the decade anchor for every "
                f"contract code in the file)"
            )
        m = _INSTRUMENT_RE.match(instrument)
        if not m:
            option_rows += 1          # "OMWH7 C6.50" and anything else that is not a delivery month
            continue
        root, month_code, year_digit = m.group(1), m.group(2), m.group(3)
        roots_seen.add(root)
        slug = MIAX_ROOT_MAP.get(root)
        if slug is None:
            continue                  # EXACT root match; a new MIAX product is not this leg's
        rows.append({
            "trade_date": session,
            "leviathan_slug": slug,
            "root": root,
            "raw_symbol": instrument,     # VERBATIM. Never parsed into meaning at ingest.
            "contract_month": contract_month_str(month_code, year_digit, session),
            "prev_settle": parse_number(rec.get("Prev_Settle")),
            "open": parse_number(rec.get("Open")),
            "high": parse_number(rec.get("High")),
            "low": parse_number(rec.get("Low")),
            "settle": parse_number(rec.get("Settle")),
            "change": parse_number(rec.get("Change")),
            "last_update": (rec.get("Last_Update_DateTime") or "").strip(),
        })

    df = pd.DataFrame(rows, columns=BRONZE_COLUMNS)
    if len(df):
        df["trade_date"] = pd.to_datetime(df["trade_date"]).astype("datetime64[us]")
    stats = {
        "trade_date": want or (sorted(file_dates)[-1] if file_dates else None),
        "file_dates": sorted(file_dates),
        "data_rows": data_rows,
        "option_rows": option_rows,
        "roots_seen": sorted(roots_seen),
        "rows_kept": int(len(df)),
        # Stated on every run so the absence is measured rather than assumed: this file has no
        # volume and no open interest, and the two columns are NULL BY SOURCE downstream.
        "volume_published": False,
        "open_interest_published": False,
    }
    logger.info("miax bronze %s: %d outright(s) kept of %d row(s) (%d option rows), roots %s",
                stats["trade_date"], len(df), data_rows, option_rows, sorted(roots_seen))
    return df, stats
