"""MINAGRO -- the Ukrainian grain / pulse / flour export table, raw -> bronze.

WHAT THIS MODULE OWNS
---------------------
Every parsing decision for the Ministry of Agrarian Policy's standing export page::

    https://minagro.gov.ua/napryamki/eksport-do-krain-ies/
        eksport-z-ukrayini-zernovih-zernobobovih-ta-boroshna

and nothing else. Pure: BeautifulSoup + pandas + the house logger. No boto3, no S3, no network, no
playwright -- the BROWSER is the producer's problem and this module only ever sees the ``main``
outerHTML it landed.

WHY A BROWSER LANDS THE BYTES
-----------------------------
minagro.gov.ua sits behind a Cloudflare MANAGED CHALLENGE: a plain HTTP GET answers 403 with an
interstitial, from a laptop and from Fargate alike. The page itself is server-rendered once the
challenge clears, so the raw object is the rendered ``<main>`` outerHTML -- a DOM snapshot, the
Euronext W1c precedent. :func:`looks_like_the_export_table` is what stops a challenge body from ever
being landed as if it were the table.

THE PAGE CARRIES TWO DATES AND THEY ARE NOT THE SAME DATE
---------------------------------------------------------
1. ``div.publish_date`` -- "Опубліковано 14 серпня 2026 року, 09:05" -- the CMS publication moment,
   in Ukrainian month names. It moves every time the ministry re-publishes the page.
2. The table's own as-of, in the header paragraphs above it: "тис. тонн станом на 14.08.2026
   (дані Держмитслужби)" -- the date the STATE CUSTOMS numbers describe.

The knowledge date is (2), never (1). This mirrors the D-LD derived-date rule (see
``bronze_to_silver/mpoc_exports_by_country.py``): the anchor is the period the data measures, and a
publication guess belongs in the card's ``publication_lag_days`` where it is auditable, not baked
irreversibly into the row. Operationally the publish stamp can only ever run at or AFTER the as-of
instant -- the ministry cannot publish customs figures before the customs day closes -- so keying on
(1) would date every row late by an amount that varies with the CMS, and a re-publish of an
unchanged table (which this page does) would mint a second, later "vintage" of identical numbers.
Keying on (2) makes the raw key, the bronze rows and the silver knowledge date one single date that
the DATA itself declares.

THE 'СТАНОМ НА' PHRASE APPEARS TWICE, AND ONLY THE FIRST ONE IS OURS
--------------------------------------------------------------------
The table's third column header reads "Всього станом на 14.08.2025" -- the PRIOR marketing year's
cumulative at the same calendar date. A regex over the whole page therefore has a 50% chance of
returning last year's date, and the failure is silent: the capture lands under
``as_of=20250814``, a year early, parses perfectly, and back-dates the whole series.
:func:`as_of_date_from_page` searches ONLY the markup that precedes the first ``<table>``, and
:func:`build_bronze` re-reads the prior-year date out of the header cell separately so the two can
be cross-checked rather than confused.

DECIMAL COMMA, AND THE ONE CELL THAT IS NOT
-------------------------------------------
Ukrainian decimal notation is a COMMA ("3,0" is three point zero). The fixture also carries exactly
one cell typed with a period ("0.0" on the rye row) -- upstream inconsistency, not a different
number -- so :func:`parse_number` accepts both. The disambiguation rule is explicit rather than
locale-guessed: ``,`` followed by ONE OR TWO digits at the end of the token is a decimal separator
(the page prints at most one fractional digit anywhere); ``,`` followed by THREE is a thousands
group and is removed. Getting this backwards turns 3,0 kt into 30 kt with nothing to detect it.

THE MARKETING-YEAR HEADER IS A PIN, NOT DECORATION
---------------------------------------------------
The table's first header row declares its two column GROUPS: "2026/2027 МР" over columns 1-2 and
"2025/2026 МР" over columns 3-4. Nothing else on the page says which pair is current and which is
prior -- the values are bare numbers -- so a page that ever swaps the two groups would silently
publish last year's cumulative as this year's, with every row well formed and no error anywhere.
:func:`build_bronze` reads both labels, refuses unless the FIRST group is the LATER marketing year,
and cross-checks the current one against the marketing year printed in the header paragraph. Only
after that pin passes is the positional column decode legal.

THE COMPLETENESS FLOOR
----------------------
Ten row labels are expected (:data:`REQUIRED_CROP_SLUGS`) and a parse missing any of them is a hard
error naming the absentees. A page that renders a half-table, or a layout change that renames a row,
would otherwise yield a short-but-well-formed frame that publishes as the complete table -- the
Euronext ``EURONEXT_MIN_ROWS`` lesson, on a source where "wheat is absent this week" reads to a desk
as a collapse in wheat exports. An UNKNOWN label (the ministry adding, say, oats) is the opposite
case: it is logged and counted, never dropped silently and never fatal, because a new commodity row
must not take a weekly leg down.

THE FLOUR ROW IS TWO ROWS IN ONE ``<tr>``
------------------------------------------
"Борошно разом, тис. тонн" and "у перерахунку на зерно, тис. тонн" (flour total, and the same flour
restated in grain equivalent) share ONE table row: the label cell holds two ``<p>`` and so does each
of the four value cells, paired by paragraph index. Reading such a cell with ``get_text()`` yields
"3,21,3" -- a number that does not exist. The parse therefore pairs paragraphs positionally and
refuses a row whose label paragraph count and value paragraph counts disagree.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

import pandas as pd
from bs4 import BeautifulSoup

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# The source key: the raw prefix segment, the ``source`` column value, and the
# MIN_RAW_FILE_SIZES key are all this one string.
SOURCE = "minagro_grain_exports"

PAGE_URL = (
    "https://minagro.gov.ua/napryamki/eksport-do-krain-ies/"
    "eksport-z-ukrayini-zernovih-zernobobovih-ta-boroshna"
)

# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------
# THE FOUR VALUE COLUMNS, in the order the ministry renders them. Position is authoritative ONLY
# after the marketing-year header pin passes (see the module docstring):
#   0  current MY, cumulative since the MY opened
#   1  current MY, the current month's contribution to that cumulative
#   2  prior MY, cumulative at the SAME calendar date one year earlier
#   3  prior MY, that year's month figure at the same date
VALUE_COLUMNS: tuple[str, ...] = (
    "my_cumulative_kt",
    "month_to_date_kt",
    "prior_my_cumulative_kt",
    "prior_my_month_kt",
)
_COLUMN_COUNT = 1 + len(VALUE_COLUMNS)  # the row label + four values

# Bronze is richer than silver on purpose (bronze is source-faithful): it keeps the verbatim row
# label and the CMS publish stamp, which silver does not carry.
BRONZE_COLUMNS: list[str] = [
    "as_of_date", "marketing_year", "prior_marketing_year", "crop_slug", "row_label",
    *VALUE_COLUMNS,
    "publish_stamp_text", "published_at", "source",
]

# ---------------------------------------------------------------------------
# Row labels
# ---------------------------------------------------------------------------
# Matched by NORMALIZED SUBSTRING against the row's own label paragraph, first hit wins. Substring
# and not equality because every label carries a unit tail the ministry edits freely
# ("Борошно пшеничне, тис. тонн"); normalized because the page mixes NBSP, <br> and stray commas
# into otherwise identical labels.
#
# The two flour entries lead so that a future "Борошно пшеничне разом" cannot be captured by the
# broader "борошно разом" rule. None of the ten patterns is a substring of another (asserted at
# import time by :func:`_lint_crop_labels`), which is what makes "first hit wins" safe.
CROP_LABELS: tuple[tuple[str, str], ...] = (
    ("борошно пшеничне", "wheat_flour"),
    ("борошно інше", "other_flour"),
    ("борошно разом", "flour_total"),
    ("у перерахунку на зерно", "flour_grain_equivalent"),
    ("зернові та зернобобові", "grains_pulses_total"),
    ("експорт разом", "grain_flour_total"),
    ("пшениця", "wheat"),
    ("ячмінь", "barley"),
    ("жито", "rye"),
    ("кукурудза", "corn"),
)
CROP_SLUGS: tuple[str, ...] = tuple(slug for _, slug in CROP_LABELS)
REQUIRED_CROP_SLUGS: frozenset[str] = frozenset(CROP_SLUGS)

# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
# The table's own as-of. ``\s*`` between the words because the phrase is split across two <p>
# elements ("... тис. тонн станом на" / "14.08.2026 (дані Держмитслужби)") and the get_text
# separator lands between them.
_AS_OF_RE = re.compile(r"станом\s*на\s*(\d{2})\.(\d{2})\.(\d{4})", re.IGNORECASE)
# "2026/2027 МР" -- the marketing-year label, in the header paragraph and in the table's own
# first header row.
_MARKETING_YEAR_RE = re.compile(r"(\d{4})\s*/\s*(\d{4})")
# The CMS publish stamp: "Опубліковано 14 серпня 2026 року, 09:05".
_PUBLISH_RE = re.compile(
    r"(\d{1,2})\s+([^\s,]+)\s+(\d{4})\s*року\s*,?\s*(?:(\d{1,2}):(\d{2}))?",
    re.IGNORECASE,
)
# Ukrainian month names in the GENITIVE case -- the only form a date stamp ever uses.
UKRAINIAN_MONTHS: dict[str, int] = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5, "червня": 6,
    "липня": 7, "серпня": 8, "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
}

_TABLE_OPEN_RE = re.compile(r"<table\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
_NULL_TOKENS = frozenset({"", "-", "--", "n/a", "na", "nan"})
# ``,`` + ONE OR TWO trailing digits == a decimal comma. The page prints at most one fractional
# digit anywhere ("3,0", "0,2", "4,3"), so two is already headroom; THREE trailing digits is read
# as a thousands group instead ("3,093" -> 3093). See the module docstring.
_DECIMAL_COMMA_RE = re.compile(r"^([+-]?\d+),(\d{1,2})$")
# Spaces (including NBSP and the narrow no-break space) are Ukraine's thousands separator.
_GROUP_SPACE_RE = re.compile("[\\s\\u00a0\\u202f]+")

# The total row's label -- the ONE phrase that identifies this table. Pinned HERE, beside the
# sniff, because three different layers have to agree about which element is the table: the
# producer's browser-side ready check, the capture sniff, and :func:`find_table`. A phrase that
# lived only in the producer would let it WAIT on one element and CAPTURE another.
TOTAL_ROW_MARKER = "зернові та зернобобові"

# ---------------------------------------------------------------------------
# The capture sniff -- the markers a Cloudflare challenge body can never carry
# ---------------------------------------------------------------------------
# Deliberately a phrase from the header, one row label from each half of the table, and the
# marketing-year token: a challenge interstitial, a 404, or a CMS error page carries none of them,
# and a page that carries all four is this table or a very deliberate forgery.
TABLE_MARKERS: tuple[str, ...] = (
    "станом на",
    TOTAL_ROW_MARKER,
    "борошно",
    "мр",
)
# A complete table is ten body rows; the sniff floor is deliberately LOWER than the parse floor.
# The sniff answers "is this the export table at all" (a challenge page scores zero); the parse
# answers "is it complete" and owns the exact count, so the two cannot disagree about the ten.
MIN_SNIFF_ROWS = 8


def ascii_safe(value: Any, limit: int = 300) -> str:
    """``value`` as pure ASCII, escaped and truncated -- safe for a cp1252 Windows console.

    Every log record in this family can carry Ukrainian text (row labels, page fragments, error
    context) and a non-ASCII ``print`` CRASHES python on the operator's console. One definition,
    shared by the transform and the producer."""
    text = str(value)
    if len(text) > limit:
        text = text[:limit] + "..."
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _lint_crop_labels() -> list[str]:
    """No curated label pattern may be a substring of another -- that is what makes first-hit-wins
    a decision rather than an accident of dict order."""
    errs: list[str] = []
    for pattern, slug in CROP_LABELS:
        for other, other_slug in CROP_LABELS:
            if slug != other_slug and pattern in other:
                errs.append(
                    f"{slug}: pattern {pattern!r} is a substring of {other_slug}'s {other!r} -- "
                    f"first-hit-wins would decide by ORDER instead of by the label"
                )
    if len(set(CROP_SLUGS)) != len(CROP_SLUGS):
        errs.append("two labels map to the same crop slug")
    return errs


assert not _lint_crop_labels(), (
    "minagro_grain_exports.CROP_LABELS is malformed: " + "; ".join(_lint_crop_labels())
)


def _text(value: Any) -> str:
    """Decode bytes, single-space the whitespace runs, and keep everything else verbatim."""
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    return str(value)


def _norm(value: Any) -> str:
    """A cell / label -> a single-spaced lowercase token string.

    Punctuation (Latin and Cyrillic alike) collapses to spaces, so "Борошно пшеничне, тис. тонн"
    and "Борошно&nbsp;пшеничне" both normalize to a string containing "борошно пшеничне"."""
    if value is None:
        return ""
    text = re.sub("[^0-9a-z\\u0400-\\u04ff]+", " ", str(value).lower())
    return " ".join(text.split()).strip()


def parse_number(token: Any) -> float:
    """``'3,0' -> 3.0``; ``'0.0' -> 0.0``; ``'1 234' -> 1234.0``; ``'-'`` / blank -> NaN.

    The decimal-comma repair is the whole point (see the module docstring): a Ukrainian "3,0"
    read by a comma-stripping parser becomes 30, which is a plausible wrong number rather than an
    error. ZERO IS NOT A SENTINEL here -- the rye row publishes a real, published 0.0 in all four
    columns and masking it would erase an observation."""
    if token is None or isinstance(token, bool):
        return float("nan")
    if isinstance(token, (int, float)):
        return float(token)
    tok = _GROUP_SPACE_RE.sub("", str(token))
    tok = tok.replace("\u2013", "-").replace("\u2212", "-")
    if tok.lower() in _NULL_TOKENS:
        return float("nan")
    m = _DECIMAL_COMMA_RE.match(tok)
    if m:
        tok = f"{m.group(1)}.{m.group(2)}"
    else:
        tok = tok.replace(",", "")
    if tok.startswith("+"):
        tok = tok[1:]
    try:
        return float(tok)
    except ValueError:
        return float("nan")


def header_html(payload: Any) -> str:
    """The markup that PRECEDES the first ``<table>``.

    The as-of date and the marketing year are read from here and nowhere else: the table's own
    third column header also says "станом на", one year earlier, and a whole-page regex that
    happens to match it back-dates the capture by a year with nothing to detect it."""
    text = _text(payload)
    m = _TABLE_OPEN_RE.search(text)
    return text[: m.start()] if m else text


def _plain(html_fragment: str) -> str:
    return " ".join(BeautifulSoup(html_fragment, "html.parser").get_text(" ").split())


def as_of_date_from_page(payload: Any) -> dt.date:
    """The table's own ``станом на`` date, as a ``datetime.date``. FAIL CLOSED.

    This is the knowledge date, the raw key's ``as_of=`` segment and the silver ``as_of_date``
    -- one date, declared by the data, read once."""
    plain = _plain(header_html(payload))
    m = _AS_OF_RE.search(plain)
    if not m:
        raise ValueError(
            "minagro: no 'станом на DD.MM.YYYY' date in the markup above the table. That phrase is "
            "the table's own as-of and the ONLY knowledge date this leg has -- refusing to fall "
            f"back to the publish stamp or to the wall clock (header seen: {ascii_safe(plain)!r})"
        )
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.date(year, month, day)
    except ValueError as exc:
        raise ValueError(
            f"minagro: 'станом на {m.group(1)}.{m.group(2)}.{m.group(3)}' is not a calendar date "
            f"({exc}). The field is DD.MM.YYYY; a source that switched to MM.DD.YYYY would re-date "
            f"the whole series silently, so this refuses rather than guessing"
        ) from exc


def marketing_year_from_header(payload: Any) -> Optional[str]:
    """``'2026/2027'`` from the header paragraph above the table, or None when it is absent.

    OPTIONAL on purpose: the authoritative marketing years are the table's OWN column-group
    headers (which is what the positional decode depends on); this one is the cross-check."""
    m = _MARKETING_YEAR_RE.search(_plain(header_html(payload)))
    return f"{m.group(1)}/{m.group(2)}" if m else None


def publish_stamp(payload: Any) -> dict:
    """The CMS publish stamp: its verbatim text and, when it parses, an ISO ``published_at``.

    Returned for PROVENANCE and never used as a date of record -- see the module docstring. Never
    raises: a re-worded stamp must not take the leg down, because the knowledge date does not come
    from here."""
    soup = BeautifulSoup(_text(payload), "html.parser")
    node = soup.find(class_="publish_date")
    text = " ".join(node.get_text(" ").split()) if node is not None else ""
    published_at: Optional[str] = None
    m = _PUBLISH_RE.search(text)
    if m:
        month = UKRAINIAN_MONTHS.get(m.group(2).lower())
        if month is not None:
            try:
                day, year = int(m.group(1)), int(m.group(3))
                if m.group(4) is not None:
                    published_at = dt.datetime(
                        year, month, day, int(m.group(4)), int(m.group(5))
                    ).isoformat(timespec="minutes")
                else:
                    published_at = dt.date(year, month, day).isoformat()
            except ValueError:
                published_at = None
    if text and published_at is None:
        logger.warning(
            "minagro: the publish stamp %r did not parse -- kept verbatim. This is PROVENANCE "
            "only; the knowledge date comes from the table's own 'станом на' date",
            ascii_safe(text),
        )
    return {"publish_stamp_text": text or None, "published_at": published_at}


def find_table(payload: Any):
    """The export table element out of a landed ``main`` outerHTML (or a whole page).

    The ministry's CMS puts no id or class of its own on the table, so it is matched by CONTENT:
    the first table whose body carries the "зернові та зернобобові" total row. That is the same
    marker the capture sniff uses, so the producer and the parse cannot disagree about which
    element is the table."""
    soup = BeautifulSoup(_text(payload), "html.parser")
    for cand in soup.find_all("table"):
        if TOTAL_ROW_MARKER in _norm(cand.get_text(" ")):
            return cand
    raise ValueError(
        "minagro: no table carrying the 'Зернові та зернобобові' total row. This is the shape a "
        "Cloudflare challenge page, a 404 or a CMS error has -- it must be a hard error, because "
        "an empty parse is indistinguishable from a week the ministry published nothing"
    )


def _cell_paragraphs(cell) -> list[str]:
    """A cell's ``<p>`` texts, or its whole text when it has none.

    Load-bearing for the flour row, whose label cell and four value cells each hold TWO paragraphs
    ("Борошно разом" / "у перерахунку на зерно" and "3,2" / "4,3"). ``get_text()`` on such a cell
    yields "3,21,3" -- a number that does not exist."""
    paras = [" ".join(p.get_text(" ").split()) for p in cell.find_all("p")]
    paras = [p for p in paras if p]
    if paras:
        return paras
    text = " ".join(cell.get_text(" ").split())
    return [text] if text else []


def crop_slug_for_label(label: str) -> Optional[str]:
    """The canonical crop slug for one row label, or None when the label is not curated."""
    norm = _norm(label)
    if not norm:
        return None
    for pattern, slug in CROP_LABELS:
        if pattern in norm:
            return slug
    return None


def _marketing_year_groups(rows) -> tuple[int, list[str]]:
    """``(row index, ['2026/2027', '2025/2026'])`` from the table's first header row.

    THE PIN. The two column groups are the only statement anywhere on the page of which pair of
    columns is the current marketing year -- the values themselves are bare numbers. A page that
    swapped them would publish last year's cumulative as this year's with every row well formed."""
    for idx, tr in enumerate(rows):
        found = _MARKETING_YEAR_RE.findall(" ".join(
            " ".join(c.get_text(" ").split()) for c in tr.find_all(["td", "th"])
        ))
        if len(found) >= 2:
            return idx, [f"{a}/{b}" for a, b in found]
    raise ValueError(
        "minagro: the table has no header row declaring its marketing-year column groups "
        "('2026/2027 МР' over columns 1-2, '2025/2026 МР' over columns 3-4). Without it nothing on "
        "the page says which two columns are the CURRENT year, and the positional decode below "
        "would be a guess"
    )


def _check_marketing_years(groups: list[str], header_my: Optional[str]) -> tuple[str, str]:
    """Validate the two column-group labels and return ``(current, prior)``."""
    if len(groups) != 2:
        raise ValueError(
            f"minagro: the table declares {len(groups)} marketing-year column group(s) {groups}, "
            f"expected exactly 2 (current, prior). A third group is a layout change and the "
            f"four-column positional decode cannot be trusted through it"
        )
    current, prior = groups
    starts = [int(g.split("/")[0]) for g in groups]
    spans = [int(g.split("/")[1]) - int(g.split("/")[0]) for g in groups]
    if spans != [1, 1]:
        raise ValueError(
            f"minagro: marketing-year labels {groups} do not span consecutive years -- refusing "
            f"to read them as (current, prior)"
        )
    if starts[0] != starts[1] + 1:
        raise ValueError(
            f"minagro: the table's FIRST marketing-year column group is {current!r} and the second "
            f"is {prior!r}. The first group must be the LATER year: columns 1-2 are the current "
            f"marketing year and 3-4 the prior one, and a swap would publish last year's "
            f"cumulative as this year's with every row still well formed"
        )
    if header_my and header_my != current:
        raise ValueError(
            f"minagro: the header paragraph announces marketing year {header_my!r} but the table's "
            f"own column group says {current!r}. Two disagreeing statements of the same fact; "
            f"refusing to pick one"
        )
    return current, prior


def build_bronze(payload: Any, *, as_of_date: Optional[str] = None) -> tuple[pd.DataFrame, dict]:
    """One landed ``page.html`` -> the tidy bronze rows + a stats dict.

    ``as_of_date`` is OPTIONAL and is a CROSS-CHECK, not an input: the date of record is always the
    page's own ``станом на`` date. Passing the raw key's ``as_of=`` segment here proves the landed
    object is the one the key claims; a disagreement is a hard error rather than a silent
    re-dating (the Euronext delivery-month cross-check idiom)."""
    # ORDER MATTERS. ``find_table`` runs FIRST so that the most likely bad input -- a Cloudflare
    # challenge body, a 404, a CMS error -- fails with "this is not the export table" rather than
    # with the narrower "no станом на date", which reads as a layout nit and sends a reader looking
    # in the wrong place.
    table = find_table(payload)
    page_as_of = as_of_date_from_page(payload)
    if as_of_date:
        claimed = pd.Timestamp(as_of_date).date()
        if claimed != page_as_of:
            raise ValueError(
                f"minagro: the caller says as_of_date={claimed.isoformat()} but the landed page's "
                f"own 'станом на' date is {page_as_of.isoformat()}. The page is the authority -- "
                f"a mismatch means the object under that key is NOT the capture the key claims"
            )

    body = table.find("tbody") or table
    rows = body.find_all("tr")
    my_row_idx, groups = _marketing_year_groups(rows)
    marketing_year, prior_marketing_year = _check_marketing_years(
        groups, marketing_year_from_header(payload)
    )

    header_row = rows[my_row_idx + 1] if len(rows) > my_row_idx + 1 else None
    column_header_cells = header_row.find_all(["td", "th"]) if header_row else []
    column_header = [" ".join(c.get_text(" ").split()) for c in column_header_cells]
    prior_as_of = _column_header_pin(column_header, page_as_of)

    stamp = publish_stamp(payload)
    records: list[dict] = []
    unmapped: list[str] = []
    skipped = 0
    for tr in rows[my_row_idx + 2:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        if len(cells) != _COLUMN_COUNT:
            # A residual header/spacer row: counted, never guessed at. A DATA row with the wrong
            # cell count is caught below by the completeness floor, which is the check that
            # matters -- a mis-shaped commodity row must not be waved through as a spacer.
            skipped += 1
            continue
        labels = _cell_paragraphs(cells[0])
        if not labels:
            skipped += 1
            continue
        value_paras = [_cell_paragraphs(c) for c in cells[1:]]
        if any(len(v) != len(labels) for v in value_paras):
            raise ValueError(
                f"minagro: row {ascii_safe(labels)} carries {len(labels)} label paragraph(s) but "
                f"its value cells carry {[len(v) for v in value_paras]}. The flour row packs TWO "
                f"logical rows into one <tr> (total, and the same flour in grain equivalent) and "
                f"they are paired by paragraph index -- an unequal count means that pairing is a "
                f"guess, and reading the cell whole would yield a number that does not exist"
            )
        for para_idx, label in enumerate(labels):
            slug = crop_slug_for_label(label)
            if slug is None:
                unmapped.append(label)
                continue
            record = {
                "as_of_date": page_as_of,
                "marketing_year": marketing_year,
                "prior_marketing_year": prior_marketing_year,
                "crop_slug": slug,
                "row_label": label,
                "publish_stamp_text": stamp["publish_stamp_text"],
                "published_at": stamp["published_at"],
                "source": SOURCE,
            }
            for col_idx, col in enumerate(VALUE_COLUMNS):
                record[col] = parse_number(value_paras[col_idx][para_idx])
            records.append(record)

    if unmapped:
        # OBSERVABILITY, not a behaviour change (the MPOC unmapped-country precedent): a label this
        # vocabulary does not know is still skipped, but never SILENTLY. A ministry adding an oats
        # row must not take a weekly leg down, and must not vanish either.
        logger.warning(
            "minagro %s: %d row label(s) outside the curated vocabulary were skipped: %s",
            page_as_of.isoformat(), len(unmapped), ascii_safe(unmapped),
        )

    df = pd.DataFrame(records, columns=BRONZE_COLUMNS)
    missing = sorted(REQUIRED_CROP_SLUGS - set(df["crop_slug"]))
    if missing:
        raise ValueError(
            f"minagro {page_as_of.isoformat()}: the parse is missing {len(missing)} required "
            f"row(s) {missing} of {len(REQUIRED_CROP_SLUGS)}. Every row present may be perfectly "
            f"well formed, so nothing downstream can see a short table -- and an absent wheat row "
            f"reads to a desk as a collapse in wheat exports rather than as a parse failure. If "
            f"the ministry genuinely retired a row, re-read the page and re-pin CROP_LABELS; do "
            f"not drop it to make a capture pass"
        )
    duplicated = df["crop_slug"].duplicated()
    if bool(duplicated.any()):
        raise ValueError(
            f"minagro {page_as_of.isoformat()}: crop slug(s) "
            f"{sorted(set(df.loc[duplicated, 'crop_slug']))} appear more than once. One label maps "
            f"to one row per capture; a repeat means two different rows collapsed onto one slug"
        )

    stats = {
        "as_of_date": page_as_of.isoformat(),
        "marketing_year": marketing_year,
        "prior_marketing_year": prior_marketing_year,
        "prior_as_of_date": prior_as_of.isoformat() if prior_as_of else None,
        "column_header": column_header,
        "rows_kept": int(len(df)),
        "rows_expected": len(REQUIRED_CROP_SLUGS),
        "rows_skipped": skipped,
        "labels_unmapped": [ascii_safe(u) for u in unmapped],
        **stamp,
    }
    logger.info(
        "minagro bronze %s (MY %s vs %s): %d row(s), %d skipped, %d unmapped",
        page_as_of.isoformat(), marketing_year, prior_marketing_year,
        len(df), skipped, len(unmapped),
    )
    return df, stats


def _column_header_pin(header: list[str], page_as_of: dt.date) -> Optional[dt.date]:
    """Assert the four column labels are the four the positional decode assumes.

    Matched by ACCEPTED TOKEN per position rather than by exact string -- the ministry rewrites the
    month names in these headers every month ("у серпні 2026") and a pin on the full text would
    fail every four weeks. What is pinned is the SHAPE: total / of-which / total-as-of / of-which.

    Returns the prior year's as-of date read out of column 3's header, when it carries one."""
    if len(header) != len(VALUE_COLUMNS):
        raise ValueError(
            f"minagro: the column-header row has {len(header)} cell(s), expected "
            f"{len(VALUE_COLUMNS)} (tokens seen: {ascii_safe(header)}). The four-column positional "
            f"decode cannot be trusted through a changed column count"
        )
    expected = ("всього", "в тому числі", "всього", "в тому числі")
    bad = [
        f"col {i}: {ascii_safe(header[i])!r} does not contain {tok!r}"
        for i, tok in enumerate(expected)
        if tok not in _norm(header[i])
    ]
    if bad:
        raise ValueError(
            "minagro: the table's column headers drifted -- " + "; ".join(bad) +
            f". Full header seen: {ascii_safe(header)}. Columns 1/3 are the cumulative totals and "
            f"2/4 the 'of which, this month' figures; add the ministry's new wording to the pin, "
            f"do NOT fall back to a positional guess"
        )
    m = _AS_OF_RE.search(header[2])
    if not m:
        return None
    try:
        prior = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    if (prior.month, prior.day) != (page_as_of.month, page_as_of.day):
        # A WARNING and not an error: the ministry has been observed leaving a stale month name in
        # these headers, and the prior-year comparison date is not a number we publish.
        logger.warning(
            "minagro %s: the prior-year column is dated %s -- a different day/month from the "
            "table's own as-of. The prior_my_* values are the ministry's own comparison basis and "
            "are published as-is",
            page_as_of.isoformat(), prior.isoformat(),
        )
    return prior


def looks_like_the_export_table(payload: Any) -> Optional[str]:
    """None if the captured markup is plausibly this export table, else the reason it is not.

    STRUCTURAL ONLY -- marker phrases and a body-row count, never a parse: all parsing authority
    stays in :func:`build_bronze` so raw and bronze cannot disagree about what the page said. This
    exists so a Cloudflare challenge body, a 404 or a half-rendered page is never LANDED. Landing
    one would put a challenge interstitial under an ``as_of=`` key that claims to be the ministry's
    customs table, and the raw layer is immutable."""
    if not payload:
        return "the page produced no markup at all"
    text = _text(payload)
    norm = _norm(text)
    absent = [m for m in TABLE_MARKERS if m not in norm]
    if absent:
        return (
            f"the captured markup is missing {len(absent)} of {len(TABLE_MARKERS)} table marker(s) "
            f"{[ascii_safe(a) for a in absent]} -- this is the shape a Cloudflare managed-challenge "
            f"page, a 404 or a CMS error has. Refusing to land it: raw is immutable and a challenge "
            f"body under an as_of= key is indistinguishable from the table forever after"
        )
    if not _TABLE_OPEN_RE.search(text):
        return "the captured markup carries the marker phrases but no <table> element at all"
    rows = len(re.findall(r"<tr\b", text, re.IGNORECASE))
    if rows < MIN_SNIFF_ROWS:
        return (
            f"the captured table carries {rows} <tr> element(s), expected at least "
            f"{MIN_SNIFF_ROWS} -- the page did not finish rendering, or the ministry truncated the "
            f"table. A short table parses cleanly and publishes as the complete one"
        )
    return None
