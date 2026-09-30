"""ICCO Quarterly Bulletin of Cocoa Statistics (QBCS): the release-page parser, and the legacy JSON->bronze.

THE PAGE PARSER (2026-09-29, data repairs ICCO-1..4)
---------------------------------------------------
Every quarterly ICCO bulletin has a free summary page on icco.org, and the estate keeps the bytes of
each one under ``raw/production/source=icco_qbcs_summary/release_date=<d>/page.html``.  Those bytes
are the evidence; this module turns ONE page into what the page itself states, and nothing more:

* WHICH BULLETIN it is -- the publisher's own identity ``Issue No. N - Volume V`` and the bulletin
  month/year its title names -- never the URL it was fetched from (the Aug-2017 bulletin is served
  from the November-2019 URL) and never the time we fetched it.
* WHEN it became known -- the dateline of the intro paragraph, fenced to a window that opens on the
  first day of the bulletin's OWN month (the Aug-2026 page carries the May-2026 dateline by
  copy-paste); then the page's publication stamp; then the last day of the bulletin month.
* EVERY DATA COLUMN of the summary table, each mapped to (header season, kind, restated?) from the
  header cells with their colspans AND rowspans, and each cell parsed on its own -- never the HEAD
  rule that took "the last two parsed numbers" and so shifted every value one column left whenever
  a cell failed to parse (ICCO-2(a): a sign followed by a NO-BREAK SPACE, ``+\\xa075``).
* The seasons the intro paragraph says the release covers (the text BEFORE the identity statement:
  after it the paragraph names the BULLETIN's cocoa year, which in 2025-26 is not a data season).
* The footnote a/ (which columns are restatements of an earlier bulletin) and the weight-loss share
  footnote b/ states where it states one.

The page parser does NOT decide which season a column belongs to when the header is wrong: the
publisher mislabelled its own header twice (May-2023 both seasons, Aug-2023 season A).  That needs
the RELEASE CHAIN (a restated column must equal the previous bulletin's own figure), which only a
builder holding every page can read -- see ``bronze_to_silver/icco_cocoa.py:build_icco_releases``.

THE LEGACY JSON -> BRONZE (``extract_icco_bronze``)
--------------------------------------------------
SILVER-F051 restored a bronze from the fetcher's JSON sidecars.  That JSON carries a ``prior`` block
that is the SAME season's previous estimate labelled with the PRIOR season's name (ICCO-2(b)), and
nothing in the chain calls the function any more: the releases table is built from the PAGES.  It is
kept, unchanged, for the 48 bronze objects that still exist (read by nothing, deleted by nobody).
"""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

from leviathan.common.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------------------------
# The page parser
# ---------------------------------------------------------------------------------------------

#: Stamped on every row minted from a page, so a row always says which parser read its bytes.
PARSE_VERSION = "icco_qbcs_page/2026-09-29"

#: The files a release folder holds, by name.  ``page.html`` is the capture that minted the folder's
#: record; ``capture_<digest16>.html`` is a LATER capture that states something different (the
#: fetcher never writes over ``page.html``); ``page_parse_failure.html`` is a body that yielded no
#: release and is never read as one.
MINTED_PAGE_NAME = "page.html"
CAPTURE_PAGE_TEMPLATE = "capture_{digest}.html"
PARSE_FAILURE_PAGE_NAME = "page_parse_failure.html"
_CAPTURE_PAGE_RE = re.compile(r"capture_[0-9a-f]{16}\.html")


def is_page_capture(file_name: str) -> bool:
    """True for the files a release is read from: the minting page and any later capture."""
    return file_name == MINTED_PAGE_NAME or bool(_CAPTURE_PAGE_RE.fullmatch(file_name))

#: The publisher's schedule: issue N of a volume is published in the Nth of these months.
QBCS_ISSUE_MONTHS = ("february", "may", "august", "november")

# Month name -> number, from the standard library's calendar (never a typed list).
_MONTH_NUMBER = {calendar.month_name[i].lower(): i for i in range(1, 13)}

# The dateline must fall inside a window that opens on the first day of the bulletin's own month.
# Measured over the 48 table pages: every dateline sits 25..34 days in; the Aug-2026 page's
# copy-pasted "29 May 2026" sits 64 days BEFORE its window.  75 days is past the widest real lag and
# short of the ~92-day issue spacing, so the NEXT issue's date can never be accepted.
RELEASE_WINDOW_DAYS = 75

#: Rows that carry a figure, by the publisher's own row label (normalised: lower case, footnote
#: markers removed, single spaces, no space around "/").  ONE declared map; a row with numbers whose
#: label is not here fails the page closed rather than being guessed.
METRIC_ROW_LABELS = {
    "world production": "production_kt",
    "world gross production": "production_kt",
    "world grindings": "grindings_kt",
    "surplus/deficit": "surplus_deficit_kt",
    "end-of-season stocks": "end_stocks_kt",
    "stocks/grindings ratio": "stocks_to_grindings_pct",
}

#: The header's own kind word (normalised) -> figure_kind.  ONE declared map (T-ICCO-4).  Whether a
#: column is a RESTATEMENT is read from its footnote marker a/, not from the word.
FIGURE_KIND_WORDS = {
    "forecasts": "forecast",
    "revised forecasts": "revised_forecast",
    "previous forecasts": "forecast",
    "estimates": "estimate",
    "revised estimates": "revised_estimate",
    "previous estimates": "estimate",
}

# The four kt metrics of the balance, in the table's row order.
BALANCE_METRICS = ("production_kt", "grindings_kt", "surplus_deficit_kt", "end_stocks_kt")

_COCOA_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\s*/\s*(\d{4}|\d{2})\b")
_IDENTITY_RE = re.compile(r"Issue\s+No\.?\s*(\d)\W+Volume\s+([IVXLCDM]+)\b", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(calendar.month_name[i] for i in range(1, 13)) + r")\s+(\d{4})\b",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(
    r"\b(" + "|".join(calendar.month_name[i] for i in range(1, 13)) + r")\s+(\d{4})\s+Quarterly\s+Bulletin",
    re.IGNORECASE,
)
_FOOTNOTE_MARK_RE = re.compile(r"(?<![\w/])([a-z])/(?![\w/])")
_LOSS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*loss", re.IGNORECASE)
_CONTENT_CLASS = "entry-content"

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(numeral: str) -> int:
    """The publisher's volume numeral as an integer (``LII`` -> 52)."""
    total = 0
    values = [_ROMAN[ch] for ch in numeral.upper()]
    for i, v in enumerate(values):
        total += -v if i + 1 < len(values) and values[i + 1] > v else v
    return total


def _is_space(ch: str) -> bool:
    """Every Unicode space separator (SPACE, NO-BREAK SPACE, THIN SPACE, NARROW NBSP ...)."""
    return unicodedata.category(ch) == "Zs"


def _is_minus(ch: str) -> bool:
    """MINUS SIGN or any dash punctuation (hyphen-minus, en dash ...)."""
    return ch == "\N{MINUS SIGN}" or unicodedata.category(ch) == "Pd"


def normalise_text(text: str) -> str:
    """Collapse every Unicode space separator (and line breaks) to one ASCII space."""
    out = "".join(" " if (_is_space(ch) or ch in "\r\n\t") else ch for ch in text)
    return re.sub(r" {2,}", " ", out).strip()


def parse_figure(text: str | None) -> float | None:
    """One printed figure -> float, or None when the cell prints no figure.

    The sign may be followed by ANY space separator (``+\\xa075``, ``\\u2212\\xa0492``, ``+ 49``) --
    ICCO-2(a): HEAD removed only ASCII spaces, so an NBSP after the sign lost the value.  Thousands
    are grouped by any space separator or a comma followed by exactly three digits; a trailing ``%``
    is dropped (the ratio row).  A cell holding only a dash is "not applicable" and returns None.
    """
    if text is None:
        return None
    s = normalise_text(text)
    if not s:
        return None
    sign = 1.0
    if s[0] == "+":
        s = s[1:]
    elif _is_minus(s[0]):
        sign = -1.0
        s = s[1:]
    s = s.strip()
    if s.endswith("%"):
        s = s[:-1].rstrip()
    s = re.sub(r"(?<=\d)[ ,](?=\d{3}(?!\d))", "", s)
    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        return None
    return sign * float(s)


def cocoa_year_label(text: str) -> str | None:
    """The one cocoa-year label in *text*, normalised to ``YYYY/YY``, or None.

    A label whose second year is not the first plus one is not a cocoa year and is refused.
    """
    labels = cocoa_year_labels(text)
    return labels[0] if len(labels) == 1 else None


def cocoa_year_labels(text: str) -> list[str]:
    """Every distinct cocoa-year label in *text* in order of appearance, normalised to ``YYYY/YY``."""
    out: list[str] = []
    for m in _COCOA_YEAR_RE.finditer(text or ""):
        start = int(m.group(1))
        tail = m.group(2)
        end = int(tail) if len(tail) == 4 else (start // 100) * 100 + int(tail)
        if len(tail) == 2 and end < start:
            end += 100
        if end != start + 1:
            continue
        label = f"{start}/{str(end)[-2:]}"
        if label not in out:
            out.append(label)
    return out


def season_start(label: str) -> int:
    return int(label.split("/")[0])


def season_label(start_year: int) -> str:
    return f"{start_year}/{str(start_year + 1)[-2:]}"


@dataclass(frozen=True)
class TableColumn:
    """One data column of the summary table, as the page prints it."""

    position: int
    group: int                       # index of the season cell (colspan) this column sits under
    header_season: str | None        # the header's season label (normalised), as printed
    kind_text: str                   # the header's kind words, as printed (normalised)
    figure_kind: str | None          # FIGURE_KIND_WORDS[kind] -- None when the words are unknown
    restated: bool                   # the column carries the footnote marker a/
    values: dict                     # metric -> float | None
    unparsed: dict                   # metric -> cell text that printed something but no figure


@dataclass
class ParsedPage:
    """What ONE captured bulletin page states.  ``failure`` names why a page yields no release."""

    page_sha256: str
    source_url: str | None = None
    title_month: str | None = None
    title_year: int | None = None
    bulletin_volume: str | None = None
    bulletin_volume_number: int | None = None
    bulletin_issue: int | None = None
    release_date: str | None = None
    release_date_source: str | None = None
    layout: str | None = None                       # "table" | "prose"
    columns: list[TableColumn] = field(default_factory=list)
    statement_seasons: list[str] = field(default_factory=list)
    prose_rows: list[dict] = field(default_factory=list)   # {cocoa_year, figure_kind, values}
    withheld_seasons: list[str] = field(default_factory=list)
    footnote_a: str | None = None
    weight_loss_pct: float | None = None
    failure: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def identity(self) -> tuple[int, int] | None:
        if self.bulletin_volume_number is None or self.bulletin_issue is None:
            return None
        return (self.bulletin_volume_number, self.bulletin_issue)

    def to_record(self) -> dict[str, Any]:
        """A JSON-safe record of the parse (the fetcher's sidecar; not evidence -- the page is)."""
        return {
            "parse_version": PARSE_VERSION,
            "page_sha256": self.page_sha256,
            "source_url": self.source_url,
            "bulletin_volume": self.bulletin_volume,
            "bulletin_issue": self.bulletin_issue,
            "bulletin_month": self.title_month,
            "bulletin_year": self.title_year,
            "release_date": self.release_date,
            "release_date_source": self.release_date_source,
            "layout": self.layout,
            "statement_seasons": list(self.statement_seasons),
            "columns": [
                {"position": c.position, "group": c.group, "header_season": c.header_season,
                 "kind_text": c.kind_text, "figure_kind": c.figure_kind, "restated": c.restated,
                 "values": dict(c.values), "unparsed": dict(c.unparsed)}
                for c in self.columns
            ],
            "prose_rows": [dict(r) for r in self.prose_rows],
            "withheld_seasons": list(self.withheld_seasons),
            "footnote_a": self.footnote_a,
            "weight_loss_pct": self.weight_loss_pct,
            "failure": self.failure,
            "notes": list(self.notes),
        }


def _content(soup: BeautifulSoup):
    """div.entry-content: the article.  Outside it sits the "Latest News" sidebar, which links FUTURE
    bulletins (the PIT container the text layer uses too)."""
    return soup.find("div", class_=_CONTENT_CLASS) or soup


def content_text(soup: BeautifulSoup) -> str:
    return normalise_text(_content(soup).get_text(separator=" ", strip=True))


def _cell_text(cell: Any) -> str:
    return normalise_text(cell.get_text(separator=" ", strip=True))


def _span(cell: Any, attr: str) -> int:
    try:
        return max(1, int(str(cell.get(attr, 1) or 1).strip()))
    except ValueError:
        return 1


def table_grid(table: Any) -> list[list[tuple[int, str]]]:
    """The table as a grid of (cell id, text), every colspan AND rowspan expanded.

    A cell spanning k columns appears k times with ONE id, so the columns under one header cell can
    be grouped by identity rather than by position; a row-spanning cell is carried down.
    """
    grid: list[list[tuple[int, str]]] = []
    carry: dict[int, list] = {}     # column -> [rows left, cell id, text]
    cell_id = 0
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False) or tr.find_all(["th", "td"])
        row: list[tuple[int, str]] = []
        col = 0
        queue = list(cells)
        while queue or any(c >= col for c in carry):
            if col in carry:
                left, cid, text = carry[col]
                row.append((cid, text))
                if left <= 1:
                    del carry[col]
                else:
                    carry[col][0] = left - 1
                col += 1
                continue
            if not queue:
                # a carried cell further right: pad the gap
                row.append((-1, ""))
                col += 1
                continue
            cell = queue.pop(0)
            cell_id += 1
            text = _cell_text(cell)
            cs, rs = _span(cell, "colspan"), _span(cell, "rowspan")
            for _ in range(cs):
                row.append((cell_id, text))
                if rs > 1:
                    carry[col] = [rs - 1, cell_id, text]
                col += 1
        grid.append(row)
    return grid


def normalise_label(text: str) -> str:
    """A row or kind label for the declared maps: lower case, footnote markers dropped, one space."""
    t = _FOOTNOTE_MARK_RE.sub(" ", normalise_text(text).lower())
    t = re.sub(r"\s*/\s*", "/", t)
    return re.sub(r"\s+", " ", t).strip(" .:")


def _footnote_markers(text: str) -> set[str]:
    return {m.group(1) for m in _FOOTNOTE_MARK_RE.finditer(normalise_text(text).lower())}


def _find_summary_table(soup: BeautifulSoup):
    """The summary table: the one whose rows carry the declared balance rows."""
    for table in _content(soup).find_all("table"):
        labels = {normalise_label(tr.find(["th", "td"]).get_text(" ", strip=True))
                  for tr in table.find_all("tr") if tr.find(["th", "td"]) is not None}
        if {"production_kt", "grindings_kt"} <= {METRIC_ROW_LABELS.get(lb) for lb in labels}:
            return table
    return None


def _footnote_text(table: Any, marker: str) -> str | None:
    """The text of footnote ``marker/`` printed AFTER the table (up to the next marker).

    Only strings outside the table are read, so the header's own ``a/`` marker is never taken for
    the footnote that defines it.
    """
    parts: list[str] = []
    for s in table.find_all_next(string=True):
        if table in s.parents:
            continue
        parts.append(str(s))
        if sum(len(p) for p in parts) > 3000:
            break
    after = normalise_text(" ".join(parts))
    marks = list(_FOOTNOTE_MARK_RE.finditer(after))
    for i, m in enumerate(marks):
        if m.group(1) != marker or not re.match(r"\s*[A-Za-z]", after[m.end():]):
            continue
        end = marks[i + 1].start() if i + 1 < len(marks) else len(after)
        return after[m.end():end].strip()
    return None


def _parse_columns(table: Any, page: ParsedPage) -> list[TableColumn] | None:
    grid = table_grid(table)
    width = max((len(r) for r in grid), default=0)
    for r in grid:
        r.extend([(-1, "")] * (width - len(r)))

    data_rows: dict[str, int] = {}
    for ri, row in enumerate(grid):
        metric = METRIC_ROW_LABELS.get(normalise_label(row[0][1])) if row else None
        if metric is None:
            numeric = [parse_figure(t) for _, t in row[1:]]
            if data_rows and any(v is not None for v in numeric):
                page.failure = f"a row with figures carries an undeclared label {row[0][1]!r}"
                return None
            continue
        if metric in data_rows:
            page.failure = f"the balance row {metric} is printed twice"
            return None
        data_rows[metric] = ri
    if not data_rows:
        page.failure = "no balance row in the summary table"
        return None
    first_data = min(data_rows.values())
    header = grid[:first_data]

    season_row = None
    for hi, row in enumerate(header):
        if sum(1 for _, t in row[1:] if cocoa_year_labels(t)) >= 1:
            season_row = hi
            break
    if season_row is None:
        page.failure = "the header names no cocoa year"
        return None

    columns: list[TableColumn] = []
    groups: dict[int, int] = {}
    for j in range(1, width):
        cid, stext = header[season_row][j]
        labels = cocoa_year_labels(stext)
        if not labels:
            continue            # a change column, or the label column
        if len(labels) > 1:
            page.failure = f"header column {j} names {len(labels)} cocoa years"
            return None
        group = groups.setdefault(cid, len(groups))
        texts: list[str] = []
        for hi, row in enumerate(header):
            t = row[j][1]
            if hi == season_row:
                t = _COCOA_YEAR_RE.sub(" ", t)
            if t and t not in texts:
                texts.append(t)
        kinds = {normalise_label(t) for t in texts} & set(FIGURE_KIND_WORDS)
        if len(kinds) != 1:
            page.failure = f"header column {j} ({labels[0]}) carries no single declared kind: {texts}"
            return None
        kind_text = kinds.pop()
        restated = any("a" in _footnote_markers(t) for t in texts
                       if normalise_label(t) == kind_text or kind_text in normalise_label(t))
        values: dict[str, float | None] = {}
        unparsed: dict[str, str] = {}
        for metric, ri in data_rows.items():
            text = grid[ri][j][1]
            v = parse_figure(text)
            values[metric] = v
            if v is None and text and not all(_is_minus(ch) for ch in text.replace(" ", "")):
                unparsed[metric] = text
        columns.append(TableColumn(position=j, group=group, header_season=labels[0],
                                   kind_text=kind_text, figure_kind=FIGURE_KIND_WORDS[kind_text],
                                   restated=restated, values=values, unparsed=unparsed))
    if not columns:
        page.failure = "no data column under a cocoa-year header"
        return None
    bad = {c.position: c.unparsed for c in columns if c.unparsed}
    if bad:
        page.failure = f"cells print something that is not a figure: {bad}"
        return None
    if any(c.restated for c in columns):
        page.footnote_a = _footnote_text(table, "a")
        if page.footnote_a is None:
            page.failure = "a column carries the marker a/ but the page defines no footnote a/"
            return None
    b = _footnote_text(table, "b")
    if b:
        m = _LOSS_RE.search(b)
        if m:
            page.weight_loss_pct = float(m.group(1))
    return columns


# The prose layout (Aug-2025, Aug-2026): no <table> at all; the Secretariat "temporarily withheld"
# one season and stated the other in a bulleted paragraph.  These are HEAD's prose rules (commit
# 31156ad8, closed in code), moved here unchanged plus the ratio the paragraph also prints.
_PROSE_NUM = r"([0-9][0-9\s,. ]*[0-9]|[0-9])"
_PROSE_UNIT = r"\s*(million|thousand)?\s*(?:metric\s+)?tonnes"
_PROSE_GAP = r"(?:(?!tonnes)[^;]){0,140}?"
_PROSE_SEASON_RE = re.compile(r"data\s+for\s+the\s+(20\d{2}/\d{2,4})\s+season", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.:;])\s+(?=[A-Z])")
_PROSE_WITHHELD_RE = re.compile(r"\bwithheld\b", re.IGNORECASE)
_PROSE_AFFIRM_RE = re.compile(r"\b(?:estimated|unchanged|revised|remain|stand)\w*\b", re.IGNORECASE)
_PROSE_PRODUCTION_RE = re.compile(
    r"world\s+(?:gross\s+)?production\b" + _PROSE_GAP + r"\bto\s+" + _PROSE_NUM + _PROSE_UNIT,
    re.IGNORECASE)
_PROSE_GRINDINGS_RE = re.compile(
    r"world\s+grindings\b" + _PROSE_GAP + r"\bto\s+" + _PROSE_NUM + _PROSE_UNIT, re.IGNORECASE)
_PROSE_BALANCE_RE = re.compile(
    r"global\s+supply\s+(surplus|deficit)\b" + _PROSE_GAP + r"\b(?:as|to|of|at)\s+"
    + _PROSE_NUM + _PROSE_UNIT, re.IGNORECASE)
_PROSE_STOCKS_RE = re.compile(
    r"end[-\s]?of[-\s]?season\s+stocks\b" + _PROSE_GAP + r"\bto\s+" + _PROSE_NUM + _PROSE_UNIT,
    re.IGNORECASE)
_PROSE_RATIO_RE = re.compile(
    r"stocks[-\s]to[-\s]grindings\s+ratio\b" + _PROSE_GAP + r"\bto\s+([0-9]+(?:\.[0-9]+)?)\s*%",
    re.IGNORECASE)
#: The prose page's affirmative word (its stem) -> figure_kind: the prose twin of FIGURE_KIND_WORDS.
#: A sentence carrying a "revised" word is a revised estimate; any other affirmative word states the
#: season's estimate as of this release ("are estimated as", "remain unchanged from the previous").
PROSE_KIND_WORDS = {"estimate": "estimate", "unchanged": "estimate", "remain": "estimate",
                    "stand": "estimate", "revise": "revised_estimate"}


def _sentences(text: str) -> list[tuple[int, str]]:
    """(offset, sentence) pairs.  Decimals survive: the split needs a capital after the space."""
    out: list[tuple[int, str]] = []
    start = 0
    for m in _SENTENCE_SPLIT_RE.finditer(text):
        out.append((start, text[start:m.start()]))
        start = m.end()
    out.append((start, text[start:]))
    return out


def prose_season(text: str) -> tuple[str, int, str] | None:
    """(season, offset the figures start after, figure_kind) of the prose statement, or None.

    A sentence naming "withheld" is never the data season; a sentence must carry an affirmative
    verb; zero or several distinct candidate seasons return None -- a refusal, never a guess.
    """
    candidates: list[tuple[str, int, str]] = []
    for offset, sentence in _sentences(text):
        m = _PROSE_SEASON_RE.search(sentence)
        if m is None or _PROSE_WITHHELD_RE.search(sentence):
            continue
        words = [w.group(0).lower() for w in _PROSE_AFFIRM_RE.finditer(sentence)]
        if not words:
            continue
        kinds = {k for w in words for stem, k in PROSE_KIND_WORDS.items() if w.startswith(stem)}
        kind = "revised_estimate" if "revised_estimate" in kinds else "estimate"
        label = cocoa_year_label(m.group(1))
        if label:
            candidates.append((label, offset + len(sentence), kind))
    if len({c[0] for c in candidates}) != 1:
        return None
    return candidates[0]


def withheld_seasons(text: str) -> list[str]:
    """Seasons a sentence of the page says the Secretariat WITHHELD."""
    out: list[str] = []
    for _, sentence in _sentences(text):
        if _PROSE_WITHHELD_RE.search(sentence):
            for label in cocoa_year_labels(sentence):
                if label not in out:
                    out.append(label)
    return out


def _kt(value: float, unit: str | None) -> float:
    u = (unit or "").strip().lower()
    if u == "million":
        return round(value * 1000.0, 3)
    if u == "thousand":
        return round(value, 3)
    return round(value / 1000.0, 3)      # a bare "tonnes" figure ("37,000 tonnes")


def parse_prose_statement(text: str) -> dict | None:
    """The prose layout's one stated season: {cocoa_year, figure_kind, values} or None."""
    chosen = prose_season(text)
    if chosen is None:
        return None
    season, start, kind = chosen
    body = text[start:]
    values: dict[str, float | None] = {}
    for metric, rx, grp in (("production_kt", _PROSE_PRODUCTION_RE, 1),
                            ("grindings_kt", _PROSE_GRINDINGS_RE, 1)):
        m = rx.search(body)
        v = parse_figure(m.group(grp)) if m else None
        values[metric] = _kt(v, m.group(grp + 1)) if (m and v is not None) else None
    m = _PROSE_BALANCE_RE.search(body)
    v = parse_figure(m.group(2)) if m else None
    if m and v is not None:
        mag = _kt(abs(v), m.group(3))
        values["surplus_deficit_kt"] = -mag if m.group(1).lower() == "deficit" else mag
    else:
        values["surplus_deficit_kt"] = None
    m = _PROSE_STOCKS_RE.search(body)
    v = parse_figure(m.group(1)) if m else None
    values["end_stocks_kt"] = _kt(v, m.group(2)) if (m and v is not None) else None
    m = _PROSE_RATIO_RE.search(body)
    values["stocks_to_grindings_pct"] = float(m.group(1)) if m else None
    if all(values[k] is None for k in BALANCE_METRICS):
        return None
    return {"cocoa_year": season, "figure_kind": kind, "values": values}


def published_time_date(soup: BeautifulSoup) -> str | None:
    """ISO date of the page's own WordPress ``article:published_time`` stamp, or None."""
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    content = (meta.get("content") or "") if meta is not None else ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", content)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def in_release_window(iso_date: str, month: str, year: int) -> bool:
    """True when *iso_date* sits in [first day of the bulletin month, +RELEASE_WINDOW_DAYS)."""
    try:
        start = date(year, _MONTH_NUMBER[month.lower()], 1)
        candidate = date.fromisoformat(iso_date)
    except (KeyError, ValueError, AttributeError):
        return False
    return start <= candidate < start + timedelta(days=RELEASE_WINDOW_DAYS)


def month_end(month: str, year: int) -> str:
    m = _MONTH_NUMBER[month.lower()]
    return date(year, m, calendar.monthrange(year, m)[1]).isoformat()


def _first_date(text: str) -> str | None:
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), _MONTH_NUMBER[m.group(2).lower()], int(m.group(1))).isoformat()
    except ValueError:
        return None


def release_date_of(soup: BeautifulSoup, month: str, year: int,
                    intro: str | None = None) -> tuple[str, str]:
    """(release date, rung) for a bulletin of *month*/*year* -- the dateline, fenced.

    Rungs: ``dateline`` (the intro paragraph's date, else the article's first date) when in the
    bulletin's window; ``publication_stamp`` (``article:published_time``) when in window;
    ``bulletin_month_fallback`` (the last day of the bulletin month) otherwise.  The fence CORRECTS
    the date; it never drops the release.
    """
    for text in (intro, content_text(soup)):
        candidate = _first_date(text) if text else None
        if candidate:
            if in_release_window(candidate, month, year):
                return candidate, "dateline"
            logger.warning("Dateline %s is outside the %s %d window -- not this issue's date",
                           candidate, month, year)
            break
    stamp = published_time_date(soup)
    if stamp and in_release_window(stamp, month, year):
        return stamp, "publication_stamp"
    return month_end(month, year), "bulletin_month_fallback"


def _title_month_year(soup: BeautifulSoup) -> tuple[str, int] | None:
    for node in (soup.find("title"), _content(soup).find("h1"), soup.find("h1")):
        if node is None:
            continue
        m = _TITLE_RE.search(normalise_text(node.get_text(" ", strip=True)))
        if m:
            return m.group(1).lower(), int(m.group(2))
    return None


def _intro_paragraph(soup: BeautifulSoup) -> str | None:
    """The article paragraph that carries the bulletin's identity statement."""
    for p in _content(soup).find_all(["p", "div"]):
        text = normalise_text(p.get_text(" ", strip=True))
        if _IDENTITY_RE.search(text) and len(text) < 4000:
            return text
    return None


def parse_qbcs_page(html: bytes | str, *, url_month: str | None = None,
                    url_year: int | None = None, source_url: str | None = None) -> ParsedPage:
    """Parse ONE captured QBCS page.  Never raises on a page: a failure is named in ``failure``.

    ``url_month`` / ``url_year`` are used ONLY when the page's own title names no bulletin month
    (the identity the release date is fenced by is the PAGE's, never the URL's when both exist).
    """
    raw = html if isinstance(html, bytes) else html.encode("utf-8")
    page = ParsedPage(page_sha256=hashlib.sha256(raw).hexdigest())
    text = raw.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    canon = soup.find("link", rel="canonical")
    page.source_url = (canon.get("href") if canon is not None and canon.get("href") else source_url)

    intro = _intro_paragraph(soup)
    ident = _IDENTITY_RE.search(intro or content_text(soup))
    if ident:
        page.bulletin_issue = int(ident.group(1))
        page.bulletin_volume = ident.group(2).upper()
        page.bulletin_volume_number = roman_to_int(page.bulletin_volume)

    title = _title_month_year(soup)
    if title:
        page.title_month, page.title_year = title
        if page.bulletin_issue is not None and page.title_month in QBCS_ISSUE_MONTHS and \
                QBCS_ISSUE_MONTHS.index(page.title_month) + 1 != page.bulletin_issue:
            page.notes.append(f"title month {page.title_month} is not issue No. {page.bulletin_issue}")
    elif url_month and url_year:
        page.title_month, page.title_year = url_month.lower(), int(url_year)
        page.notes.append("no bulletin month in the title: the URL's month fences the dateline")
    if page.title_month is None or page.title_year is None:
        page.failure = "the page names no bulletin month (title) and no URL month was given"
        return page

    page.release_date, page.release_date_source = release_date_of(
        soup, page.title_month, page.title_year, intro)

    # The seasons the release says it covers: the intro paragraph BEFORE the identity statement.
    if intro:
        cut = _IDENTITY_RE.search(intro)
        page.statement_seasons = cocoa_year_labels(intro[:cut.start()] if cut else intro)

    table = _find_summary_table(soup)
    if table is not None:
        page.layout = "table"
        cols = _parse_columns(table, page)
        if cols is None:
            return page
        page.columns = cols
        # On a table page only the release's OWN statement (the intro paragraph) can withhold a
        # season; a commentary sentence recalling an earlier withholding is history, not a statement.
        page.withheld_seasons = withheld_seasons(intro or "")
        return page

    body = content_text(soup)
    stmt = parse_prose_statement(body)
    page.withheld_seasons = withheld_seasons(body)
    if stmt is None and not page.withheld_seasons:
        page.failure = "neither a summary table nor a prose statement of any season"
        return page
    page.layout = "prose"
    if stmt is not None:
        page.prose_rows = [stmt]
    return page


# ---------------------------------------------------------------------------------------------
# The legacy JSON -> bronze (unchanged; called by nothing in the chain since 2026-09-29)
# ---------------------------------------------------------------------------------------------

# The four ICCO balance-sheet metrics, in the physical bronze column order.
_METRICS = ("world_production_kt", "world_grindings_kt", "end_season_stocks_kt", "surplus_deficit_kt")
# current is emitted before prior (matches the physical bronze row order).
_VINTAGES = ("current", "prior")

BRONZE_COLUMNS: list[str] = ["release_date", "cocoa_year", "vintage", "metric", "value_kt", "source"]


def extract_icco_bronze(raw_json: bytes | str | dict) -> pd.DataFrame:
    """Parse one PRE-2026-09-29 ICCO QBCS summary JSON into the long-format bronze (8 rows).

    Superseded: the JSON's ``prior`` block is the same season's previous estimate under the prior
    season's name (ICCO-2(b)).  The releases table is built from the banked PAGES instead.

    Raises:
        ValueError: If the JSON lacks a release_date or both vintage blocks.
    """
    doc = raw_json if isinstance(raw_json, dict) else json.loads(raw_json)
    release_date = doc.get("release_date")
    if not release_date:
        raise ValueError("ICCO bronze: raw JSON has no release_date")

    records: list[dict] = []
    for vintage in _VINTAGES:
        block = doc.get(vintage)
        cocoa_year = doc.get(f"cocoa_year_{vintage}")
        if not isinstance(block, dict) or not cocoa_year:
            continue
        for metric in _METRICS:
            val = block.get(metric)
            records.append({
                "release_date": release_date,
                "cocoa_year": cocoa_year,
                "vintage": vintage,
                "metric": metric,
                "value_kt": float(val) if val is not None else None,
                "source": "icco_qbcs",
            })

    if not records:
        raise ValueError(f"ICCO bronze: release {release_date} has no current/prior block")

    df = pd.DataFrame(records)[BRONZE_COLUMNS]
    logger.info("ICCO bronze: release=%s rows=%d cocoa_years=%s",
                release_date, len(df), sorted(df["cocoa_year"].unique()))
    return df
