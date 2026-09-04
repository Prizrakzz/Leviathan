"""The ONE place both Pink Sheet lanes derive a release's CONTENT KEY and its CLOCK.

WHY THIS MODULE EXISTS
----------------------
The World Bank publishes ``CMO-Historical-Data-Monthly.xlsx`` with NO trustworthy self-description
of which release it is.  Measured 2026-09-03 across six workbooks:

  * the download page's anchor LABEL can advertise month ``M-1`` while the workbook already holds
    month ``M`` (the 2026-08-04 mislabelling fire);
  * the Description sheet's ``Updated as of:`` tail was a month STALE in 1 of 6 (the 2026M05
    workbook says "April 2, 2026" for a workbook whose last monthly row is 2026M04);
  * ``'Monthly Prices'!A4`` carried the wrong YEAR in 1 of 6 (the 2026M01 vintage says
    "Updated on January 06, 2025").

Each in-file stamp is wrong in a DIFFERENT one of the six, so none of them can be the key.  The one
rule consistent across all six is the CONTENT KEY: **the last monthly row plus one calendar month.**
That is what ``derived_release_ym`` computes, and everything else in this module hangs off it.

Pure by construction: no network, no ``datetime.now()``.  A clock read here would make the key a
function of WHEN the code ran rather than of WHAT the bytes are, which is the whole defect being
closed.

MEASURED (six workbooks, 2026-09-03)::

    release   n_months   expected_month_count   hole-free 1960M01..R-1
    2025M01   780        780                    yes
    2026M01   792        792                    yes
    2026M05   796        796                    yes
    2026M07   798        798                    yes
    2026M08   799        799                    yes
    2026M09   800        800                    yes
"""
from __future__ import annotations

import io
import re
from typing import Iterable, Optional

# The sheet is addressed BY NAME and the rows BY MASK -- exactly the shipped extractor's own
# conventions (``raw_to_bronze/world_bank_pink_sheet.py`` ``_SHEET_NAME`` / ``_HEADER_ROW`` and the
# ``^\d{4}M\d{2}$`` mask it applies to column 0).  Re-deriving them here with a different rule would
# put two definitions of "a monthly row" in one estate.
SHEET_NAME = "Monthly Prices"
HEADER_ROW = 4                       # 0-indexed; row 5 in the workbook (1-indexed)
MONTH_RX = re.compile(r"^\d{4}M\d{2}$")

# THE HISTORY FLOOR.  Every Pink Sheet release restates the whole series back to 1960-01; that is
# the premise the bitemporal table's one-clock guarantee rests on, so it is a named constant and not
# a literal buried in an arithmetic expression.
EPOCH_YEAR = 1960
EPOCH_MONTH = 1

# Magic bytes.  ZIP (``PK\x03\x04``) is a modern .xlsx; OLE2/BIFF is a REAL legacy .xls, which the
# fetch's PK gate and ``engine='openpyxl'`` both refuse; anything else is not a workbook at all --
# MEASURED on the 2016 document-ID epoch, whose unhyphenated URL 200s with 100,826 bytes of HTML
# under ``Content-Type: application/vnd...spreadsheetml.sheet``.
_PK_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

KIND_XLSX = "xlsx"
KIND_OLE2 = "ole2_biff"
KIND_NOT_WORKBOOK = "not_a_workbook"

# The clock ladder's two tokens, plus the archive-leg variant and the month-end CLAMP variant.
# They are VALUES on every row (``release_date_source``), so the corpus can count how many vintages
# carry an origin clock and how many carry the derived fallback -- absent is never zero.
SOURCE_ORIGIN_LAST_MODIFIED = "origin_last_modified"
SOURCE_ORIGIN_LAST_MODIFIED_CLAMPED = "origin_last_modified_clamped"
SOURCE_DERIVED_MONTH_FIRST = "derived_month_first"
SOURCE_DERIVED_MONTH_FIRST_ARCHIVE = "derived_month_first_archive"

# The closed set, so a reader (and a gate) can enumerate the ladder's rungs without re-deriving it.
RELEASE_DATE_SOURCES: frozenset[str] = frozenset({
    SOURCE_ORIGIN_LAST_MODIFIED,
    SOURCE_ORIGIN_LAST_MODIFIED_CLAMPED,
    SOURCE_DERIVED_MONTH_FIRST,
    SOURCE_DERIVED_MONTH_FIRST_ARCHIVE,
})


def _ym_parts(release_ym: str) -> tuple[int, int]:
    """``'2026M09'`` -> ``(2026, 9)``.  Raises on any other shape -- a release month that cannot be
    parsed is never guessed at."""
    text = str(release_ym).strip()
    if not MONTH_RX.match(text):
        raise ValueError(
            f"release month {release_ym!r} is not in 'YYYYMmm' form (e.g. '2026M09'); a release "
            f"whose month cannot be parsed is refused, never defaulted"
        )
    return int(text[:4]), int(text[5:7])


def _fmt_ym(year: int, month: int) -> str:
    """``(2026, 9)`` -> ``'2026M09'``."""
    return f"{year:04d}M{month:02d}"


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def workbook_kind(body: bytes) -> str:
    """Classify raw bytes BEFORE anything tries to parse them.

    Returns one of :data:`KIND_XLSX` (PK magic), :data:`KIND_OLE2` (a real legacy .xls, which the
    PK gate at ``jobs/ingest/fetch_world_bank_pink_sheet.py`` and ``engine='openpyxl'`` at
    ``raw_to_bronze/world_bank_pink_sheet.py`` both refuse) or :data:`KIND_NOT_WORKBOOK`.

    RUN THIS FIRST, ALWAYS, on every body from every source.  The 2016 epoch measurement is the
    reason: a 200 with an xlsx ``Content-Type`` carrying ``<!DOCTYPE`` HTML is a lying origin, and
    the two failures must be counted apart (``body_not_workbook`` vs ``format_unsupported``) or the
    decline census cannot tell "the World Bank served us a web page" from "this era is a legacy
    format we do not support".
    """
    head = bytes(body or b"")[:8]
    if head.startswith(_PK_MAGIC):
        return KIND_XLSX
    if head.startswith(_OLE2_MAGIC):
        return KIND_OLE2
    return KIND_NOT_WORKBOOK


def monthly_rows(xlsx_bytes: bytes) -> list[str]:
    """Every ``YYYYMmm`` label in column 0 of the ``'Monthly Prices'`` sheet, in file order.

    Reads the sheet BY NAME and selects rows by the same ``^\\d{4}M\\d{2}$`` mask the shipped
    extractor applies, so "a monthly row" means one thing in this estate.  Blank separator rows and
    the workbook's notes/aggregate rows fall out of the mask.
    """
    import pandas as pd  # local import: this module stays importable without the pandas stack

    kind = workbook_kind(xlsx_bytes)
    if kind != KIND_XLSX:
        raise ValueError(
            f"these bytes are {kind!r}, not an xlsx workbook -- classify with workbook_kind() and "
            f"decline (body_not_workbook / format_unsupported) before parsing"
        )
    df_raw = pd.read_excel(
        io.BytesIO(xlsx_bytes),
        sheet_name=SHEET_NAME,
        header=HEADER_ROW,
        engine="openpyxl",
    )
    if df_raw.empty:
        raise ValueError(f"Pink Sheet sheet '{SHEET_NAME}' is empty")
    first = df_raw.columns[0]
    labels = df_raw[first].dropna().astype(str).str.strip()
    return [v for v in labels.tolist() if MONTH_RX.match(v)]


def release_from_months(months: Iterable[str]) -> str:
    """The release month a month set implies: its LAST monthly row plus one calendar month.

    Split out of :func:`derived_release_ym` so a caller that already has the rows (the fetch, which
    also needs them for the full-restatement check) derives the key WITHOUT re-parsing a 700 KB
    workbook a second time -- and so the rule itself is unit-testable on a list.

    ``max`` rather than ``[-1]``: 'YYYYMmm' is fixed-width, so lexicographic order IS chronological
    order, and a re-sorted or interleaved sheet cannot move the key.

    Raises:
        ValueError: on an empty month set. An unparseable derived month is a REFUSAL, never a
            default -- filing a workbook under a guessed month writes a permanently quotable wrong
            knowledge date.
    """
    seq = [str(m).strip() for m in months or [] if MONTH_RX.match(str(m).strip())]
    if not seq:
        raise ValueError(
            f"Pink Sheet: no ^\\d{{4}}M\\d{{2}}$ rows in '{SHEET_NAME}' -- the content key cannot be "
            f"derived and the object is refused rather than filed under a guessed month"
        )
    year, month = _ym_parts(max(seq))
    return _fmt_ym(*_next_month(year, month))


def derived_release_ym(xlsx_bytes: bytes) -> str:
    """The release month a workbook's OWN CONTENT establishes: last monthly row + 1 calendar month.

    MEASURED 2026-09-03 as the only rule consistent across all six known vintages, where each in-file
    stamp is wrong in a DIFFERENT one of the six.  A Pink Sheet published in month R carries data
    through R-1, so the last row plus one month IS the release.

    Raises:
        ValueError: when the bytes are not an xlsx, the sheet is empty, or no row matches the mask.
    """
    return release_from_months(monthly_rows(xlsx_bytes))


def expected_month_count(release_ym: str) -> int:
    """``12 * (year - 1960) + month - 1`` -- the row count a FULL as-published history must have.

    Verified: 2025M01->780, 2026M01->792, 2026M05->796, 2026M07->798, 2026M08->799, 2026M09->800.
    """
    year, month = _ym_parts(release_ym)
    return 12 * (year - EPOCH_YEAR) + month - EPOCH_MONTH


def expected_months(release_ym: str) -> list[str]:
    """The complete hole-free run ``1960M01 .. (release_ym minus one month)``."""
    year, month = _ym_parts(release_ym)
    out: list[str] = []
    y, m = EPOCH_YEAR, EPOCH_MONTH
    while (y, m) < (year, month):
        out.append(_fmt_ym(y, m))
        y, m = _next_month(y, m)
    return out


def is_full_restatement(months: Iterable[str], release_ym: Optional[str] = None) -> bool:
    """True iff *months* is the COMPLETE hole-free run from 1960M01 with no duplicates.

    A COUNT ALONE CANNOT SEE A HOLE: 796 rows with 1971M04 missing and 2026M05 duplicated counts the
    same as a clean history.  The bitemporal table's one-clock guarantee -- and therefore the whole
    storage ruling -- rests on every release being a full as-published history, so the invariant is
    checked on the SET, not on the tally.

    THE TRAILING PARTIAL MONTH, AND WHY *release_ym* EXISTS.  With no *release_ym* the run is
    measured against the month IT ITSELF implies (``max(seq)`` + 1), so ANY prefix-complete run
    passes and a trailing partial row is invisible: months ``1960M01..2026M09`` derive 2026M10 and
    self-certify at n == expected == 801, even though the release under which those rows are FILED
    is 2026M09 and the 2026M09 row is a labelled-but-blank tail.  Passing the release the run is
    filed under measures the run against ``expected_months(release_ym)`` instead -- the DECLARED
    month rather than the run's own max -- and the trailing partial then fails, which is what the
    vintage builder's gate needs (bronze rows carry the declared ``release_ym``; a workbook whose
    last labelled row is blank files one month high and lands one month short).

    Args:
        months: the ``'YYYYMmm'`` labels of the run.
        release_ym: the release the run is filed under.  When ``None`` the release is derived from
            the run itself (the fetch's pre-bronze shape, where no declared stamp exists yet).
    """
    seq = [str(m).strip() for m in months or []]
    if not seq:
        return False
    if len(set(seq)) != len(seq):
        return False
    if release_ym is None:
        year, month = _ym_parts(max(seq))
        release = _fmt_ym(*_next_month(year, month))
    else:
        release = str(release_ym).strip()
    return sorted(seq) == expected_months(release)


def _http_date_ym(value: Optional[str]) -> Optional[tuple[int, int]]:
    """(year, month) of an RFC-1123 HTTP date, or None when it is absent/unparseable."""
    if not value:
        return None
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return dt.year, dt.month


def _http_date_iso(value: str) -> str:
    from email.utils import parsedate_to_datetime
    return parsedate_to_datetime(str(value)).strftime("%Y-%m-%d")


def release_clock(
    release_ym: str,
    xlsx_bytes: bytes = b"",
    *,
    http_last_modified: Optional[str] = None,
    archive: bool = False,
) -> tuple[str, str]:
    """``(release_date_iso 'YYYY-MM-DD', source_token)`` -- THE ADJUDICATED LADDER.

    1. ``http_last_modified`` -- the ORIGIN's HTTP ``Last-Modified`` DATE recorded AT CAPTURE --
       when its (year, month) equals the derived release month.  Token
       :data:`SOURCE_ORIGIN_LAST_MODIFIED`.

       ON AN ARCHIVE BODY THE CALLER MUST PASS ``X-Archive-Orig-Last-Modified`` AND NOTHING ELSE.
       A ``web.archive.org/web/{ts}id_/`` replay's own ``Last-Modified`` is the ARCHIVE's, and
       feeding it here would stamp the CRAWL date as ``release_date`` under a token asserting the
       opposite -- a provenance lie, permanently quotable.  With ``archive=True`` and no origin
       header the row takes rung 2 under the DISTINCT token
       :data:`SOURCE_DERIVED_MONTH_FIRST_ARCHIVE`, so the corpus can tell an origin-clocked vintage
       from an archive-clocked one.

    2. else the FIRST day of the derived release month.  Token
       :data:`SOURCE_DERIVED_MONTH_FIRST` (or the archive variant).

    NEVER THE MONTH-END, ON EITHER RUNG.  The as-of guard is a lexical
    ``CAST(release_date AS varchar) <= '<asof>'`` (``numbers/query.py``), so a 2026M09 vintage
    stamped ``2026-09-30`` is unselectable at every asof from 2026-09-02 to 2026-09-29: a
    point-in-time read INSIDE the release month would silently serve the PREVIOUS vintage while a
    one-clock gate still passed.  That is a property of the GUARD, not of the rung, so rung 1 obeys
    it too: an origin ``Last-Modified`` that lands on the month-end (a legitimate late-month
    re-upload) is CLAMPED to the day before and takes the distinct token
    :data:`SOURCE_ORIGIN_LAST_MODIFIED_CLAMPED`.  The clamp is one day EARLY -- the same direction
    as, and strictly smaller than, rung 2's declared 1-5 day window -- and it is counted rather than
    silent.  The unclamped header rides on as an audit value in the raw_meta sidecar.

    THE RESIDUAL IS BOUNDED AND DECLARED.  The six workbooks' own Description stamps are Apr 2 /
    Jul 2 / Aug 4 / Jan 3 / Jan 6 / Sep 2, so ``derived_month_first`` is 1-5 days EARLY -- a bounded
    early-knowledge window, counted per row in ``release_date_source`` and never silenced.  The
    in-file Description and A4 stamps ride as counted AUDIT values only; neither is ever the clock
    (each is wrong in a different one of the six).

    ``xlsx_bytes`` is accepted so callers can hand the workbook through one seam; the ladder does not
    read it, deliberately.
    """
    year, month = _ym_parts(release_ym)
    lm_ym = _http_date_ym(http_last_modified)
    if lm_ym is not None and lm_ym == (year, month):
        iso = _http_date_iso(str(http_last_modified))
        end = month_end_iso(release_ym)
        if iso == end:
            # THE MONTH-END CLAMP. "NEVER THE MONTH-END" is a STRUCTURAL law about the as-of guard,
            # not a statement about which rung supplied the day: a lexical
            # `CAST(release_date AS varchar) <= '<asof>'` makes a 2026M09 vintage stamped
            # 2026-09-30 unselectable at every asof from 2026-09-02 to 2026-09-29, so a legitimate
            # LATE-MONTH origin re-upload would serve the PREVIOUS vintage inside its own release
            # month while a one-clock gate still passed. Rung 1 is therefore clamped to the day
            # BEFORE the month-end rather than being allowed to emit the one value the ladder
            # forbids. The clamp moves the stamp one day EARLY -- the same direction as, and
            # strictly smaller than, rung 2's declared 1-5 day early window -- and it takes its OWN
            # token so the corpus counts clamped rows rather than reading them as clean origin
            # clocks. The unclamped header still rides in the raw_meta sidecar as an audit value.
            clamped = f"{end[:8]}{int(end[8:]) - 1:02d}"
            return clamped, SOURCE_ORIGIN_LAST_MODIFIED_CLAMPED
        return iso, SOURCE_ORIGIN_LAST_MODIFIED
    token = SOURCE_DERIVED_MONTH_FIRST_ARCHIVE if archive else SOURCE_DERIVED_MONTH_FIRST
    return f"{year:04d}-{month:02d}-01", token


def month_end_iso(release_ym: str) -> str:
    """The last day of *release_ym*, exposed ONLY so tests can assert the ladder never returns it."""
    import calendar
    year, month = _ym_parts(release_ym)
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
