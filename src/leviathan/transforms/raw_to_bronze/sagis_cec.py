"""RAW-F058: era-aware SAGIS Crop Estimates Committee (CEC) workbook parser.

Net-new (task #118, wave W1). There was NO tracked raw->bronze CEC parser: the on-S3 bronze was
materialised out-of-band by an untracked prototype that folded the subsistence sector into
``commercial`` (2007+ developing rows = 0), collapsed physically-distinct sector rows onto ONE
natural key (61 conflict keys), and stamped a sentinel estimate ``99`` (45% of rows). This module
rebuilds the parser from intact raw, FAIL-CLOSED (quarantine / raise on drift -- the WASDE
``classify_region`` discipline), across the four physical era signatures.

Entrypoint (the goldens' contract, D6=(a) raw->silver-direct)::

    from leviathan.transforms.raw_to_bronze.sagis_cec import parse_cec_report
    obs: list[CecObservation] = parse_cec_report(raw_bytes, source_key)

emitting the existing ``CecObservation`` contract
(``leviathan.transforms.bronze_to_silver.sagis_cec.CecObservation``).

Era -> format -> scope-vocabulary (re-derived from the committed fixtures' bytes, W1):

  * era A  early PDF   1999-2004   digital pdfplumber text; narrative cover + per-crop province
                                   tables; winter cereals print ONLY ``TOTAAL / TOTAL RSA`` (total).
  * era D  modern PDF  2008-2026   page-0 summary matrix; ``Commercial:`` / ``Non-Commercial Maize``
                                   sections + ``Total Maize RSA`` grand line.
  * era B  old .doc    2000-2006   OLE WordDocument stream, cp1252 (or UTF-16LE), cells on \\x07;
                                   ``Kommersieel / Commercial:`` and ``Bestaanslandbou / Subsistence
                                   agriculture:`` (a.k.a. ``Ontwikkelende landbou / Developing``).
  * era C  modern .doc 2007-2024   same OLE reader; ``Non-Commercial / Nie-Kommersiele`` developing.
  * era X  .xls        2002-2004   xlrd sheet; ``Kommersieel / Commercial:`` / ``Ontwikkelende
                                   landbou / Developing agriculture:`` sections.

RATIFIED semantics (user, 2026-07-18):
  * D1(c): keep {commercial, developing, total} with STRICT per-era sector vocabulary; a sector
    label outside the era's set is QUARANTINED, never guessed.
  * D2:  estimate_number is the PRINTED ordinal per report where present ("FOURTH"/"eighth"/"AGTSTE"
    -> 4/8/8); :func:`reconcile_estimate_numbers` derives the sequence from release-date ordering
    within (production_year, crop, scope) and CROSS-CHECKS the printed field (fail-closed on a
    release-date-vs-printed order mismatch). D2a: equal-release_date ties are broken by ``source_key``
    (byte-identical re-runs). D2b: a report that prints no release_date gets a CONSERVATIVE LATE
    bound (end-of-report-month) -- never an early one (an early release_date is a PIT lookahead leak,
    ``trade_flows.py`` filters ``release_date < crop_year_start`` with ``publication_lag_days=0``);
    a report whose month cannot even be established is QUARANTINED.
  * F3 (parse-time collapse invariant): physically-distinct sector rows MUST emit DISTINCT natural
    keys. If two physical rows collapse onto one (crop, scope) within a report, :func:`parse_cec_report`
    RAISES :class:`CecCollapseError` -- the detector the transform's post-selection ``duplicated``
    guard cannot be (it always runs on the already-collapsed ``by_key.values()``).

Pure + AWS-free: parses raw bytes only. Toolchain is fully in-repo (pdfplumber / xlrd / olefile), no
LibreOffice / Docker image change (D7 verdict).
"""
from __future__ import annotations

import calendar
import io
import re
import struct
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from leviathan.common.logging import get_logger
from leviathan.transforms.bronze_to_silver.sagis_cec import CecObservation

logger = get_logger(__name__)

# --------------------------------------------------------------------------- #
# Era signatures
# --------------------------------------------------------------------------- #
ERA_EARLY_PDF = "early_pdf"      # A 1999-2004
ERA_MODERN_PDF = "modern_pdf"    # D 2008-2026
ERA_OLD_DOC = "old_doc"          # B 2000-2006
ERA_MODERN_DOC = "modern_doc"    # C 2007-2024
ERA_XLS = "xls"                  # X 2002-2004

# Which sector-vocabulary group an era draws from (D1(c) strict per-era set).
_PRE2007_ERAS = frozenset({ERA_EARLY_PDF, ERA_OLD_DOC, ERA_XLS})
_MODERN_ERAS = frozenset({ERA_MODERN_PDF, ERA_MODERN_DOC})

_PDF_MAGIC = b"%PDF"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"

# --------------------------------------------------------------------------- #
# Canonical scope vocabulary (D1(c))
# --------------------------------------------------------------------------- #
SCOPE_COMMERCIAL = "commercial"
SCOPE_DEVELOPING = "developing"
SCOPE_TOTAL = "total"
CANONICAL_SCOPES = frozenset({SCOPE_COMMERCIAL, SCOPE_DEVELOPING, SCOPE_TOTAL})

# Printed-ordinal sentinel: no ordinal on the page -> resolve via release-date ordering (D2).
ESTIMATE_UNRESOLVED = -1

# Per-era STRICT sector-header vocabulary, matched on accent-folded lowercase text. Developing terms
# are tested BEFORE commercial because "Non-Commercial" contains "Commercial".
_SECTOR_VOCAB: dict[str, dict[str, tuple[str, ...]]] = {
    "pre2007": {
        SCOPE_DEVELOPING: (
            "ontwikkelende landbou", "developing agriculture",
            "bestaanslandbou", "subsistence agriculture",
        ),
        SCOPE_COMMERCIAL: ("kommersieel", "commercial"),
    },
    "modern": {
        SCOPE_DEVELOPING: ("non-commercial", "nie-kommersiele", "nie kommersiele", "non commercial"),
        SCOPE_COMMERCIAL: ("kommersieel", "commercial"),
    },
}

# Afrikaans + English ordinal words -> N (for estimate_number parsing off the printed title).
_ORDINALS: dict[str, int] = {
    "eerste": 1, "first": 1,
    "tweede": 2, "second": 2,
    "derde": 3, "third": 3,
    "vierde": 4, "fourth": 4,
    "vyfde": 5, "fifth": 5,
    "sesde": 6, "sixth": 6,
    "sewende": 7, "seventh": 7,
    "agtste": 8, "eighth": 8,
    "negende": 9, "ninth": 9,
    "tiende": 10, "tenth": 10,
    "elfde": 11, "eleventh": 11,
    "twaalfde": 12, "twelfth": 12,
}

# Month names (Afrikaans + English) -> month number, for release-date parsing.
_MONTHS: dict[str, int] = {
    "januarie": 1, "january": 1, "jan": 1,
    "februarie": 2, "february": 2, "feb": 2,
    "maart": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "junie": 6, "june": 6, "jun": 6,
    "julie": 7, "july": 7, "jul": 7,
    "augustus": 8, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "desember": 12, "december": 12, "dec": 12,
}

# Winter cereals (wheat/barley/canola/oats) are a total-only sector (no commercial/developing split);
# ``classify_crop`` maps them straight through for the early-PDF per-crop province-table reader.

# SA provinces (folded). The crop x sector SUMMARY matrix never lists a province; the per-crop
# province-DETAIL tables that follow it do -- so the first province row marks the summary's end.
_PROVINCES = (
    "western cape", "wes-kaap", "northern cape", "noord-kaap", "free state", "vrystaat",
    "eastern cape", "oos-kaap", "kwazulu-natal", "kwazulu natal", "mpumalanga", "limpopo",
    "gauteng", "north west", "north-west", "noordwes", "northern province", "noordelike provinsie",
)


# --------------------------------------------------------------------------- #
# Errors + quarantine ledger
# --------------------------------------------------------------------------- #
class CecParseError(ValueError):
    """Base: a CEC report could not be parsed under the fail-closed contract."""


class CecEraError(CecParseError):
    """The era signature (magic bytes / content) is not recognised -- fail closed, never guess."""


class CecCollapseError(CecParseError):
    """Two physically-distinct sector rows collapsed onto ONE natural key (F3 parse-time invariant)."""


class CecEstimateError(CecParseError):
    """A printed estimate_number contradicts release-date ordering within a group (D2 cross-check)."""


class CecNotImplementedEra(CecParseError):
    """An era whose reader is deliberately not built tonight (names the D7 decision that gates it)."""


@dataclass(frozen=True)
class QuarantineRecord:
    """One row/section the parser refused to emit, with a NAMED reason (nothing silently dropped)."""

    reason: str
    era: str
    source_key: str
    detail: str


@dataclass
class CecParseResult:
    """Full parse output: emitted observations + the quarantine ledger + per-era census."""

    observations: list[CecObservation] = field(default_factory=list)
    quarantined: list[QuarantineRecord] = field(default_factory=list)
    era: str = ""
    source_key: str = ""

    @property
    def n_observations(self) -> int:
        return len(self.observations)

    @property
    def n_quarantined(self) -> int:
        return len(self.quarantined)


# --------------------------------------------------------------------------- #
# Text / number helpers
# --------------------------------------------------------------------------- #
def _fold(s: str) -> str:
    """Accent-fold + lowercase + collapse whitespace (matches WASDE normalize discipline).

    ``e-acute`` -> ``e``; the PDF replacement glyph U+FFFD (from ``Kommersieel``) is dropped so the
    ASCII stem ``kommersie`` still matches. Slashes/dots kept (labels are bilingual ``A/B``)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("�", "").replace(" ", " ")
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


# A comma-decimal / percentage token (the CHANGE column, e.g. "+1,41" / "3,05%") is NOT a value.
_CHANGE_TOKEN_RE = re.compile(r"[+-]?\d+,\d+\s*%?")
# A CEC value integer: space/nbsp-grouped thousands ("3 615 650", "985 000") or a bare integer.
_CEC_INT_RE = re.compile(r"\d{1,3}(?:[  ]\d{3})+|\d+")

# ── THE CELL-FUSION FENCE (GN-2 W2.2, 2026-08-22; EDA-SEMANTIC-UNIT-001) ────────────────────
# The era-B .doc extraction sometimes drops a  cell delimiter, FUSING two table cells into one
# string ("2 05072 050" = two figures). The old accept branch space-stripped and float()'d that into
# 205,072,050 -- a plausible-looking fabrication -- and longer fusions minted the measured 1.7e30
# monsters (52 silver rows, 31.9% MAD outliers on the served column). The signature is structural
# and detectable BEFORE any float exists:
#   * a digit cell CONTAINING spaces must be exactly thousands-grouped (\d{1,3}( \d{3})*): a 5-digit
#     group like "05072" can only come from fusion;
#   * a spaceless digit run longer than _MAX_BARE_DIGITS cannot be a South African crop figure
#     (the largest crop ever measured is ~2.4e7 t = 8 digits).
# A fused cell POISONS ITS WHOLE ROW: _emit_summary_rows assigns values POSITIONALLY (values[0] =
# area, values[1] = current), so dropping one cell silently shifts every later figure into the wrong
# column -- worse than the big number. Fused rows are QUARANTINED (counted, source-keyed), never
# emitted and never "repaired".
_MAX_BARE_DIGITS = 8
_GROUPED_CELL_RE = re.compile(r"[+-]?\d{1,3}(?:[  ]\d{3})*")
_MALFORMED = object()      # _cell_value's fusion sentinel -- distinct from None (label/dash/change)


def _is_fused_digit_cell(s: str) -> bool:
    """True when a digit-bearing cell shows the cell-fusion signature (see the block above).

    TWO independent arms, either sufficient: (1) STRUCTURE -- a spaced cell whose grouping is not
    exactly thousands-grouped; (2) MAGNITUDE -- more than _MAX_BARE_DIGITS total digits REGARDLESS
    of grouping: a fusion can land on perfectly valid grouping by luck ("158 915 500" -- the
    measured 2022-09-28 total_maize 1.59e8, nine digits, which then poisoned six 2023 rows through
    the prior-year join), and no South African crop figure has ever exceeded eight digits."""
    if re.fullmatch(r"[+-]?[\d  ]+", s) is None:
        return False                                   # not a pure digit/space cell: not ours to judge
    if sum(ch.isdigit() for ch in s) > _MAX_BARE_DIGITS:
        return True
    if " " in s or " " in s:
        return re.fullmatch(_GROUPED_CELL_RE, s) is None
    return False


def _line_values(rest: str) -> list[float]:
    """Extract the ordered numeric VALUES from the part of a PDF text line after the crop label.

    Strips comma-decimal change tokens first so ``3,05%`` never fractures into ``3`` and ``05``; then
    reads space-grouped thousands as single integers. Returns them in printed order (area first)."""
    cleaned = _CHANGE_TOKEN_RE.sub(" ", rest.replace(" ", " "))
    cleaned = cleaned.replace("%", " ")
    # NO fusion belt HERE, deliberately (W2.2 post-mortem): this function's ONE consumer is the
    # early-PDF title check ("a title line carries no values"), so silently DROPPING an over-long
    # token turned data lines into "titles" and misattributed whole province tables to the wrong
    # crop (six fabricated rows: 2000 "soybeans" and 2008 "sunflower" wearing the maize table's
    # figures). Magnitude fencing lives in _cell_value, the path that actually mints values.
    return [float(m.group().replace(" ", "").replace(" ", "")) for m in _CEC_INT_RE.finditer(cleaned)]


def _cell_value(cell) -> Optional[float]:
    """One workbook/doc CELL -> a numeric value, or None if the cell is a label / dash / change-%."""
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    s = str(cell).replace(" ", " ").strip()
    if not s or s in {"-", "–", "—"}:
        return None
    if "," in s or "%" in s:            # change column -> not a value
        return None
    if _is_fused_digit_cell(s):         # W2.2: fusion signature -> the caller QUARANTINES the row
        return _MALFORMED
    s2 = s.replace(" ", "")
    if re.fullmatch(r"[+-]?\d+", s2):
        return float(s2)
    return None


def _split_label(line: str) -> tuple[str, list[float]]:
    """PDF text line -> (label, values). Label = text before the first value digit-run."""
    line = line.replace(" ", " ").strip()
    m = re.search(r"\d", line)
    if m is None:
        return line, []
    return line[: m.start()].strip(), _line_values(line[m.start():])


# --------------------------------------------------------------------------- #
# Scope + crop classification (fail-closed)
# --------------------------------------------------------------------------- #
def classify_sector(label: str, era: str) -> Optional[str]:
    """Classify a SECTION-HEADER label into a canonical scope, or None if it is not a sector header.

    D1(c) strict per-era vocabulary. Developing is tested before commercial ("Non-Commercial"
    contains "Commercial"). Returns None for a non-sector line (a crop row / noise); the caller
    fails closed separately on a colon-terminated header that matches nothing (:func:`_looks_like_header`)."""
    group = "pre2007" if era in _PRE2007_ERAS else "modern"
    f = _fold(label)
    if "+" in f:
        return None  # a combined descriptor ("Commercial + Non-Commercial"), not a pure header
    for term in _SECTOR_VOCAB[group][SCOPE_DEVELOPING]:
        if term in f:
            return SCOPE_DEVELOPING
    # A "non-commercial" / "nie-kommersiele" label that the era's developing vocab did NOT list is
    # still NOT commercial: fail closed rather than match the "commercial" substring (the pre-2007
    # vocab has no non-commercial term, so this negation guard prevents a mis-label to commercial).
    if "non-commercial" in f or "non commercial" in f or "nie-kommersi" in f or "nie kommersi" in f:
        return None
    for term in _SECTOR_VOCAB[group][SCOPE_COMMERCIAL]:
        if term in f:
            return SCOPE_COMMERCIAL
    return None


def _is_province(label: str) -> bool:
    """True if a row label is a SA province name (marks the start of the province-detail tables)."""
    f = _fold(label)
    return any(p in f for p in _PROVINCES)


def _looks_like_header(label: str) -> bool:
    """A colon-terminated, value-free line that reads like a sector header (drift tripwire)."""
    f = _fold(label)
    return f.endswith(":") and any(
        kw in f for kw in ("landbou", "agriculture", "kommersieel", "commercial", "sector", "mielies")
    )


# crop kinds
_CROP_ROW = "row"                # an ordinary per-sector crop row (scope = current section)
_CROP_GRAND = "grand"            # the RSA grand total maize line (scope = total)
_CROP_ALLCROP_TOTAL = "allcrop"  # an all-crop total ("TOTAL/TOTAAL") -> skip, not a crop
_CROP_UNKNOWN = "unknown"        # data row whose label maps to no known crop -> quarantine


def classify_crop(label: str, era: str) -> tuple[Optional[str], str]:
    """Map a data-row label to (canonical_crop, kind). ``kind`` in {row, grand, allcrop, unknown}.

    Maize disambiguation order matters: white/yellow FIRST (``witmielies`` contains ``mielies``),
    then the RSA grand-total line, then the per-sector maize subtotal. Winter cereals map straight
    through (early-PDF reader). An unrecognised label on a row that carries data is QUARANTINED."""
    f = _fold(label)

    # winter cereals (early PDF, total-only)
    if "koring" in f or re.search(r"\bwheat\b", f):
        return "wheat", _CROP_ROW
    if "gars" in f or re.search(r"\bbarley\b", f):
        return "barley", _CROP_ROW
    if "kanola" in f or "canola" in f:
        return "canola", _CROP_ROW
    if "hawer" in f or re.search(r"\boats\b", f):
        return "oats", _CROP_ROW

    # maize family
    if "witmielies" in f or "white maize" in f:
        return "white_maize", _CROP_ROW
    if "geelmielies" in f or "yellow maize" in f:
        return "yellow_maize", _CROP_ROW
    if "mielies" in f or "maize" in f:
        if "rsa" in f:
            return "total_maize", _CROP_GRAND
        if era in _PRE2007_ERAS and ("totaal mielies" in f or "total maize" in f):
            return "total_maize", _CROP_GRAND
        return "total_maize", _CROP_ROW      # per-sector maize subtotal

    # non-maize summer crops
    if "sorghum" in f:
        return "sorghum", _CROP_ROW
    if "grondbone" in f or "groundnut" in f:
        return "groundnuts", _CROP_ROW
    if "sonneblom" in f or "sunflower" in f:
        return "sunflower_seed", _CROP_ROW
    if "sojabone" in f or "soya" in f or "soybean" in f:
        return "soybeans", _CROP_ROW
    if "drobone" in f or "droebone" in f or "dry bean" in f:
        return "dry_beans", _CROP_ROW

    # an all-crop grand total ("TOTAL / TOTAAL") -> not a crop, skip
    if re.fullmatch(r"(total\s*/\s*totaal|totaal\s*/\s*total|total|totaal)", f):
        return None, _CROP_ALLCROP_TOTAL

    return None, _CROP_UNKNOWN


# --------------------------------------------------------------------------- #
# Report-level metadata parsing (ordinal, release_date, season)
# --------------------------------------------------------------------------- #
# Season-qualifying phrases that pin an ordinal to a crop-season title ("... produksieskatting van
# SOMERGEWASSE", "... production estimate of SUMMER crops"). Used to disambiguate a COMBINED
# winter+summer report, where the two sections carry DIFFERENT ordinals (a winter-final "fifth" and a
# summer "first"), so the report-level ordinal must match the season actually being emitted.
_SEASON_ORDINAL_TERMS: dict[str, tuple[str, ...]] = {
    "summer": ("somergewasse", "somer gewasse", "summer crop", "summer field crop"),
    "winter": ("wintergewasse", "winter gewasse", "winter crop", "winter cereal"),
}

# A season word only NAMES an ordinal's title when it sits adjacent to the ordinal (the title
# itself: "eerste produksieskatting van SOMERGEWASSE"). A wider window overruns the title boundary
# into the NEXT section's heading ("... van wintergewasse <break> SUMMER FIELD CROPS - 2004/05")
# and mislabels the season -- hence the tight bound, vs the 90-char estimate-keyword window.
_SEASON_WINDOW = 45
# Same overrun hazard for the title YEAR: every genuine title prints its season-year within ~50
# chars of the ordinal ("...: 2001/02 SEASON", "... for summer crops for 2019"); a wider window
# reads the NEIGHBOURING section's year ("... 2008-seisoen sorghum <break> preliminary area
# planted estimate: 2008/09" -- the pair belongs to the next title).
_TITLE_YEAR_WINDOW = 55

# Future-schedule NOTICE phrasing ("the fifth production forecast ... WILL BE RELEASED on 27 June" /
# "... op 21 Februarie 2006 VRYGESTEL SAL word"): a notice window names an ordinal but is not a data
# title -- excluded from attribution candidates. The present-tense data phrasing ("... is hereby
# released" / "hiermee word ... vrygestel") is KEPT.
_NOTICE_TERMS = ("will be released", "vrygestel sal")

# Crop -> season membership (SA cropping calendar). Winter cereals never appear in a summer
# crop x sector matrix; a cross-season row in an emitted matrix is a transition-release bleed.
_WINTER_CROPS = frozenset({"wheat", "barley", "canola", "oats"})
_SUMMER_CROPS = frozenset({
    "white_maize", "yellow_maize", "total_maize", "sorghum", "groundnuts",
    "sunflower_seed", "soybeans", "dry_beans",
})


def _crop_season_mismatch(crop: str, season_type: Optional[str]) -> bool:
    """True when a crop row cannot belong to the report's emitted season (transition bleed)."""
    if season_type == "summer":
        return crop in _WINTER_CROPS
    if season_type == "winter":
        return crop in _SUMMER_CROPS
    return False


@dataclass(frozen=True)
class _OrdinalCandidate:
    """One printed estimate-ordinal title: position, N, the season its title names (or None),
    the season/production year its title prints (or None) + the form it was printed in
    (``pair`` = "2004/05", ``bare`` = "2019"), and whether it is a future notice."""

    pos: int
    n: int
    season: Optional[str]
    title_year: Optional[int]
    year_form: Optional[str]
    notice: bool


def _window_title_year(window: str) -> tuple[Optional[int], Optional[str]]:
    """The season/production year printed inside an ordinal-title window -> (year, form).

    Prefers the season-PAIR form ("2007/08" -> 2008, "1999/2000" -> 2000, form=``pair``) over a
    bare year (form=``bare``); a bare year directly following a month name is a DATE
    ("... 24 October 2019"), not a season year."""
    m = re.search(r"\b((?:19|20)\d{2})\s*/\s*(\d{2,4})\b", window)
    if m:
        first, second = int(m.group(1)), m.group(2)
        if len(second) == 4:
            end = int(second)
        else:
            end = (first // 100) * 100 + int(second)
            if end < first:
                end += 100
        if 1990 <= end <= 2100:
            return end, "pair"
    for m in re.finditer(r"\b((?:19|20)\d{2})\b", window):
        pre = window[max(0, m.start() - 14): m.start()]
        if any(mn in pre for mn in _MONTHS):
            continue  # "... 24 october 2019" -- a date, not the season year
        return int(m.group(1)), "bare"
    return None, None


def _ordinal_candidates(text: str) -> list[_OrdinalCandidate]:
    """Collect every estimate-adjacent printed ordinal with its title season/year (folded text)."""
    f = _fold(text)
    out: list[_OrdinalCandidate] = []
    for m in re.finditer(r"[a-z]+", f):
        n = _ORDINALS.get(m.group())
        if n is None:
            continue
        window = f[m.end(): m.end() + 90]
        if not any(k in window for k in ("estimate", "skatting", "forecast", "produksieskatting")):
            continue
        season_win = window[:_SEASON_WINDOW]
        season = None
        for s, terms in _SEASON_ORDINAL_TERMS.items():
            if any(t in season_win for t in terms):
                season = s
                break
        ty, form = _window_title_year(window[:_TITLE_YEAR_WINDOW])
        out.append(_OrdinalCandidate(
            pos=m.start(), n=n, season=season, title_year=ty, year_form=form,
            notice=any(t in window for t in _NOTICE_TERMS),
        ))
    return out


def _has_season_markers(text: str) -> tuple[bool, bool]:
    """(has_summer, has_winter) section markers in the folded document text."""
    f = _fold(text)
    return (
        any(t in f for t in _SEASON_ORDINAL_TERMS["summer"]),
        any(t in f for t in _SEASON_ORDINAL_TERMS["winter"]),
    )


def parse_estimate_ordinal(text: str, season: Optional[str] = None) -> Optional[int]:
    """Parse the printed estimate ordinal ("FOURTH ... ESTIMATE", "eighth ... forecast",
    "VIERDE ... SKATTING") -> N, or None if none is printed. Only ordinals adjacent to an
    estimate/forecast keyword count (avoids "second-hand", province ordinals, etc.).

    ``season`` (``summer``/``winter``): a COMBINED report prints BOTH a winter-season and a
    summer-season estimate title with DIFFERENT ordinals (e.g. the Feb release carries the winter
    crops' FINAL/5th estimate AND the summer crops' 1st estimate). The scalar report ordinal must
    then match the season whose matrix is actually emitted. When ``season`` is given, an ordinal
    whose title names that season ("... produksieskatting van SOMERGEWASSE") is PREFERRED; only if
    no season-named ordinal exists does the earliest estimate-adjacent ordinal apply (the modern
    single-season / no-season-word reports, e.g. "EIGHTH PRODUCTION FORECAST: 2025", are unchanged).

    This is the simple positional reading; the corpus attribution rules (title-year cross-check,
    transition-release quarantine) live in :func:`_resolve_estimate_ordinal` / :func:`_build_meta`."""
    cands = [c for c in _ordinal_candidates(text) if not c.notice]
    if season:
        named = [c for c in cands if c.season == season]
        if named:
            return min(named, key=lambda c: c.pos).n
    return min(cands, key=lambda c: c.pos).n if cands else None


_DATE_RE = re.compile(
    r"(\d{1,2})\s+([A-Za-z]+)(?:\s*/\s*([A-Za-z]+))?\s+(\d{4})"
)


def parse_release_date(text: str) -> Optional[str]:
    """Parse the printed release/meeting date -> ISO ``YYYY-MM-DD``, or None if none is printed.

    Handles bilingual ``DD Month1/ Month2 YYYY`` ("20 Mei/ May 2002", "23 May / Mei 2006") and the
    single-month form ("20 October 1999", "30 September 2025"). Prefers the "as at / soos op /
    conditions as at" meeting date, then EMBARGO, then the first date on the page."""
    folded = text.replace(" ", " ")
    candidates: list[tuple[int, str]] = []
    for m in _DATE_RE.finditer(folded):
        day = int(m.group(1))
        month = _MONTHS.get(m.group(2).lower())
        if month is None and m.group(3):
            month = _MONTHS.get(m.group(3).lower())
        if month is None:
            continue
        year = int(m.group(4))
        if not (1 <= day <= 31 and 1990 <= year <= 2100):
            continue
        iso = f"{year:04d}-{month:02d}-{day:02d}"
        # priority: 0 = near "as at / soos op", 1 = near "embargo", 2 = anywhere
        pre = folded[max(0, m.start() - 60): m.start()].lower()
        prio = 2
        if "as at" in pre or "soos op" in pre or "conditions" in pre:
            prio = 0
        elif "embargo" in pre:
            prio = 1
        candidates.append((prio, iso))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[0][1]


def _expand_season_end_year(text: str) -> Optional[int]:
    """Season string -> production_year (END year). "2001/02" -> 2002, "1999/2000" -> 2000,
    "2005/06" -> 2006. Falls back to a bare 4-digit year after a FORECAST/ESTIMATE keyword
    (modern reports print a calendar year, e.g. "EIGHTH PRODUCTION FORECAST: 2025" -> 2025)."""
    for m in re.finditer(r"\b(\d{4})\s*/\s*(\d{2,4})\b", text):
        first, second = int(m.group(1)), m.group(2)
        if not (1990 <= first <= 2100):
            continue  # not a season (e.g. the "8043/32" phone-number false positive)
        if len(second) == 4:
            end = int(second)
        else:
            # two-digit end year: carry the century of the first year, rolling forward on wrap.
            century = first // 100
            end = century * 100 + int(second)
            if end < first:
                end += 100
        if 1990 <= end <= 2100:
            return end
    f = _fold(text)
    m = re.search(r"(?:forecast|estimate|skatting)[:\s]*?(\d{4})", f)
    if m:
        return int(m.group(1))
    return None


def _season_type(text: str) -> Optional[str]:
    f = _fold(text)
    if "somergewasse" in f or "summer crop" in f:
        return "summer"
    if "wintergewasse" in f or "winter crop" in f:
        return "winter"
    return None


def _report_month_from_key(source_key: str) -> Optional[int]:
    """Extract the report month from a ``...CEC[-_]YYYY[-_]MM...`` source key/filename."""
    stem = source_key.rsplit("/", 1)[-1]
    m = re.search(r"(19|20)\d{2}[-_](\d{2})", stem)
    if m:
        mm = int(m.group(2))
        if 1 <= mm <= 12:
            return mm
    return None


def _end_of_month(year: int, month: int) -> str:
    """Conservative LATE release_date bound (D2b): the last calendar day of the report month."""
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last:02d}"


# --------------------------------------------------------------------------- #
# .doc (OLE WordDocument) text extraction -- olefile, pure python (D7)
# --------------------------------------------------------------------------- #
def extract_doc_text(data: bytes) -> str:
    """Extract the main WordDocument text of a legacy ``.doc`` (OLE) file via the CLX piece table.

    Word ALWAYS stores the main text through a piece table (PlcPcd in the CLX): each piece's
    ``FcCompressed.fCompressed`` bit selects cp1252 (byte offset fc/2) vs UTF-16LE (byte offset fc),
    and the SAGIS CEC modern docs are fast-saved (qsaves up to 15) with MIXED-encoding pieces -- a
    UTF-16 cover page followed by cp1252 crop tables. Reading the FIB ``[fcMin, fcMac)`` region with a
    single encoding therefore garbles the tables (they are absent from a whole-region UTF-16 decode).
    So the piece table is the PRIMARY path; a contiguous single-encoding read is only the fallback for
    a doc whose CLX cannot be located. Table cells (\\x07) and paragraphs (\\r->\\n) are preserved so
    the caller can split cells deterministically. A doc whose text cannot be located at all raises
    :class:`CecParseError` (fail closed, never a partial guess)."""
    import olefile

    if not olefile.isOleFile(io.BytesIO(data)):
        raise CecParseError("not an OLE compound file")
    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        if not ole.exists("WordDocument"):
            raise CecParseError("OLE file has no WordDocument stream (not a .doc)")
        wd = ole.openstream("WordDocument").read()
        if len(wd) < 0x1AA:
            raise CecParseError("WordDocument stream too short for a Word97 FIB")
        flags = struct.unpack_from("<H", wd, 0x0A)[0]
        which_table = "1Table" if (flags >> 9) & 1 else "0Table"
        ccp_text = struct.unpack_from("<I", wd, 0x4C)[0]
        try:
            text = _extract_doc_text_complex(wd, ole, which_table, ccp_text)
        except CecParseError:
            # Fallback: contiguous main-text region (a doc with no usable CLX). Detect cp1252 vs
            # UTF-16LE by the null-byte signature; fcMac spans other subdocuments so bound by ccpText.
            fc_min, fc_mac = struct.unpack_from("<II", wd, 0x18)
            if ccp_text and _looks_utf16le(wd, fc_min, ccp_text):
                text = wd[fc_min: fc_min + 2 * ccp_text].decode("utf-16-le", errors="replace")
            elif ccp_text:
                text = wd[fc_min: fc_min + ccp_text].decode("cp1252", errors="replace")
            else:
                text = wd[fc_min:fc_mac].decode("cp1252", errors="replace")
        return _normalise_doc_text(text)
    finally:
        ole.close()


def _looks_utf16le(wd: bytes, fc_min: int, ccp_text: int) -> bool:
    """True if the ccpText-wide main-text region reads as UTF-16LE (Latin -> ~50% 0x00 bytes).

    cp1252 Latin text has almost no NUL bytes; UTF-16LE Latin text has a NUL in every high byte."""
    if fc_min + 2 * ccp_text > len(wd):
        return False
    sample = wd[fc_min: fc_min + min(2 * ccp_text, 512)]
    if not sample:
        return False
    return sample.count(0) > len(sample) * 0.25


def _extract_doc_text_complex(wd: bytes, ole, which_table: str, ccp_text: int) -> str:
    """Reconstruct text for a fast-saved (fComplex=1) .doc via the CLX piece table in the table stream.

    fcClx/lcbClx live at 0x01A2/0x01A6 in the Word97 FIB. The CLX ends in a Pcdt (0x02) whose PlcPcd
    holds (n+1) CPs then n 8-byte PCDs; each PCD's fc field's bit30 selects cp1252 (set, fc/2) vs
    UTF-16LE (clear). Concatenates piece text in document order."""
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)
    if not ole.exists(which_table):
        raise CecParseError(f"fComplex=1 but table stream {which_table!r} missing")
    tbl = ole.openstream(which_table).read()
    clx = tbl[fc_clx: fc_clx + lcb_clx]
    # skip any leading Prc (0x01) blobs, find the Pcdt (0x02)
    i = 0
    while i < len(clx) and clx[i] == 0x01:
        cb = struct.unpack_from("<H", clx, i + 1)[0]
        i += 3 + cb
    if i >= len(clx) or clx[i] != 0x02:
        raise CecParseError("CLX has no Pcdt piece table (fComplex .doc unsupported shape)")
    lcb_pcdt = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5: i + 5 + lcb_pcdt]
    n = (len(plc) - 4) // (4 + 8)
    cps = [struct.unpack_from("<I", plc, k * 4)[0] for k in range(n + 1)]
    pcd_base = (n + 1) * 4
    parts: list[str] = []
    for k in range(n):
        fc_field = struct.unpack_from("<I", plc, pcd_base + k * 8 + 2)[0]
        compressed = bool(fc_field & 0x40000000)
        fc = fc_field & 0x3FFFFFFF
        cp_len = cps[k + 1] - cps[k]
        if compressed:
            start = fc // 2
            parts.append(wd[start: start + cp_len].decode("cp1252", errors="replace"))
        else:
            parts.append(wd[fc: fc + cp_len * 2].decode("utf-16-le", errors="replace"))
    return "".join(parts)


def _normalise_doc_text(text: str) -> str:
    """Drop Word field-instruction runs (HYPERLINK/SHAPE codes) and keep cell (\\x07) / para (\\n)."""
    text = text.replace("\x0b", "\n").replace("\x0c", "\n").replace("\r", "\n")
    # Field codes sit between \x13 (start) ... \x14 (separator) and end at \x15; drop the instruction.
    text = re.sub(r"\x13[^\x14\x15]*[\x14\x15]", " ", text)
    text = text.replace("\x13", " ").replace("\x14", " ").replace("\x15", " ")
    return text


# --------------------------------------------------------------------------- #
# Era detection (magic bytes + content) -- fail closed on an unknown signature
# --------------------------------------------------------------------------- #
def detect_era(data: bytes, source_key: str) -> str:
    """Return the era constant for ``data`` (magic bytes + content), or raise :class:`CecEraError`."""
    if data.startswith(_PDF_MAGIC):
        return _detect_pdf_era(data)
    if data.startswith(_OLE_MAGIC):
        return _detect_ole_era(data)
    raise CecEraError(f"unrecognised magic bytes {data[:4]!r} for {source_key!r}")


def _detect_pdf_era(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    f = _fold(text)
    if "non-commercial" in f or "nie-kommersiele" in f or "total maize rsa" in f or "totaal mielies rsa" in f:
        return ERA_MODERN_PDF
    if "produksieskatting" in f or "production estimate" in f or "production forecast" in f:
        return ERA_EARLY_PDF
    raise CecEraError("PDF matches no CEC era signature (not a crop-estimate report?)")


def _detect_ole_era(data: bytes) -> str:
    import olefile

    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        streams = {"/".join(p) for p in ole.listdir()}
    finally:
        ole.close()
    if "Workbook" in streams or "Book" in streams:
        return ERA_XLS
    if "WordDocument" not in streams:
        raise CecEraError("OLE file is neither a Word .doc nor an Excel .xls (no known stream)")
    text = extract_doc_text(data)
    f = _fold(text)
    if "non-commercial" in f or "nie-kommersiele" in f:
        return ERA_MODERN_DOC
    if ("bestaanslandbou" in f or "subsistence agriculture" in f
            or "ontwikkelende landbou" in f or "developing agriculture" in f):
        return ERA_OLD_DOC
    # A doc with a commercial section but no developing marker: classify by whether the modern
    # "forecast" phrasing is present; otherwise fail closed rather than guess the sector vocab.
    if "kommersieel" in f or "commercial" in f:
        return ERA_MODERN_DOC if "forecast" in f else ERA_OLD_DOC
    # It IS a CEC crop report but carries no commercial/developing sector matrix (a winter-only /
    # total-only report -- wheat/barley/canola -- or a preliminary area-planted release). The
    # summer sector-matrix reader does not model this sub-layout; fail closed with a NAMED,
    # quarantine-countable error (W2/W3 residue) rather than silently mis-scoping a total-only row.
    if any(c in f for c in ("koring", "wheat", "gars", "barley", "kanola", "canola", "mielies", "maize")) \
            and any(k in f for k in ("skatting", "estimate", "produksie", "forecast")):
        raise CecNotImplementedEra(
            "CEC .doc with no commercial/developing sector matrix (winter/total-only or preliminary "
            "area report) -- summer-matrix reader does not model this sub-layout; W2/W3 residue")
    raise CecEraError("Word .doc matches no CEC era signature")


# --------------------------------------------------------------------------- #
# Summary-block emission (shared by modern-PDF / .doc / .xls readers)
# --------------------------------------------------------------------------- #
@dataclass
class _ReportMeta:
    era: str
    source_key: str
    production_year: int
    report_month: int
    estimate_number: int
    release_date: Optional[str]
    season_type: Optional[str]
    source_format: str


def _emit_summary_rows(
    rows: list[tuple[str, list[float]]],
    meta: _ReportMeta,
    result: CecParseResult,
) -> None:
    """Walk (label, values) rows of a crop x sector SUMMARY matrix, emitting one CecObservation per
    physical sector row. Section headers set the current scope (fail-closed on unknown headers);
    the RSA grand-total line emits scope=total and resets the section to commercial so the trailing
    pre-2007 non-maize crops (listed after the maize block) are attributed to the commercial sector.

    Enforces the F3 collapse invariant: two physical rows may never share one (crop, scope)."""
    current_scope: Optional[str] = None
    started = False  # skip preamble rows before the first sector header / grand total
    seen_keys: set[tuple[str, str]] = set()

    def _emit(crop: str, scope: str, values: list[float]) -> None:
        if _crop_season_mismatch(crop, meta.season_type):
            # a winter cereal inside a summer matrix (or vice versa) belongs to the OTHER season's
            # section of a transition release -- the scalar meta cannot attribute it (cec-w23).
            result.quarantined.append(QuarantineRecord(
                "crop_season_mismatch", meta.era, meta.source_key,
                f"{crop} row under season_type={meta.season_type}"))
            return
        key = (crop, scope)
        if key in seen_keys:
            raise CecCollapseError(
                f"{meta.source_key}: two physical rows collapse onto ({crop}, {scope}) "
                f"in {meta.era} -- parse-time F3 invariant"
            )
        seen_keys.add(key)
        area = values[0] if values else None
        current = values[1] if len(values) > 1 else None
        result.observations.append(CecObservation(
            production_year=meta.production_year,
            report_month=meta.report_month,
            crop=crop,
            scope=scope,
            estimate_number=meta.estimate_number,
            current_estimate_t=current,
            release_date=meta.release_date,
            season_type=meta.season_type,
            area_planted_ha=area,
            source_format=meta.source_format,
            source_key=meta.source_key,
        ))

    for label, values in rows:
        if not label and not values:
            continue
        if started and _is_province(label):
            break  # the per-crop province-detail tables begin -- summary matrix is finished
        if not values:
            scope = classify_sector(label, meta.era)
            if scope is not None:
                current_scope = scope
                started = True
            elif _looks_like_header(label):
                # an unrecognised sector label (D1(c) drift): enter the data region under an UNKNOWN
                # scope so the rows beneath it are quarantined per-row, never inherited/guessed.
                result.quarantined.append(QuarantineRecord(
                    "unrecognised_sector_header", meta.era, meta.source_key, label.strip()))
                current_scope = None
                started = True
            continue

        crop, kind = classify_crop(label, meta.era)
        if kind == _CROP_ALLCROP_TOTAL:
            continue  # all-crop total, not a per-crop estimate
        if kind == _CROP_GRAND:
            _emit(crop, SCOPE_TOTAL, values)
            current_scope = SCOPE_COMMERCIAL
            started = True
            continue
        if not started:
            continue  # data row in the preamble (before any sector header) -- not a crop estimate
        if kind == _CROP_UNKNOWN:
            result.quarantined.append(QuarantineRecord(
                "unknown_crop_with_data", meta.era, meta.source_key, label.strip()))
            continue
        if current_scope is None:
            result.quarantined.append(QuarantineRecord(
                "crop_row_without_scope", meta.era, meta.source_key, label.strip()))
            continue
        _emit(crop, current_scope, values)


# --------------------------------------------------------------------------- #
# Per-era readers
# --------------------------------------------------------------------------- #
def _read_modern_pdf(data: bytes, source_key: str) -> CecParseResult:
    """Modern PDF: page-0 summary matrix via ``extract_tables`` (clean cells -- the raw text collapses
    space-thousands and column gaps into the same whitespace, so a 3-digit-leading row like sunflower
    fuses into one giant number; the ruled table is unambiguous)."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page0 = pdf.pages[0]
        header = page0.extract_text() or ""
        full = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        tables = page0.extract_tables()

    meta = _build_meta(ERA_MODERN_PDF, source_key, header, full, "pdf")
    result = CecParseResult(era=ERA_MODERN_PDF, source_key=source_key)
    rows: list[tuple[str, list[float]]] = []
    for tbl in tables:
        for row in tbl:
            if not row:
                continue
            label = (row[0] or "").replace("\n", " ").strip()
            cellvals = [_cell_value(c) for c in row[1:]]
            if any(v is _MALFORMED for v in cellvals):
                result.quarantined.append(QuarantineRecord(
                    "cell_fusion", ERA_MODERN_PDF, source_key, label[:80]))
                continue
            values = [v for v in cellvals if v is not None]
            rows.append((label, values))
    _emit_summary_rows(rows, meta, result)
    return result


def _read_early_pdf(data: bytes, source_key: str) -> CecParseResult:
    """Early PDF: narrative cover + one ruled province table PER crop. Emit each crop block's
    ``TOTAAL / TOTAL RSA`` row as scope=total (winter cereals have no commercial/developing split).
    The crop identity comes from the title line directly above each table (matched by y-position)."""
    import pdfplumber

    result = CecParseResult(era=ERA_EARLY_PDF, source_key=source_key)
    seen: set[tuple[str, str]] = set()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        full = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        meta = _build_meta(ERA_EARLY_PDF, source_key, full, full, "pdf")
        for page in pdf.pages:
            titles: list[tuple[float, str]] = []
            for ln in page.extract_text_lines():
                crop, kind = classify_crop(ln["text"], ERA_EARLY_PDF)
                if crop is not None and kind == _CROP_ROW and not _split_label(ln["text"])[1]:
                    titles.append((ln["top"], crop))
            for tbl in page.find_tables():
                ttop = tbl.bbox[1]
                above = [c for (t, c) in titles if t < ttop]
                crop = above[-1] if above else None
                if crop is None:
                    continue
                for row in tbl.extract():
                    if not row:
                        continue
                    f = _fold((row[0] or "").replace("\n", " "))
                    if not ("total rsa" in f or f.startswith("totaal")):
                        continue
                    cellvals = [_cell_value(c) for c in row[1:]]
                    if any(v is _MALFORMED for v in cellvals):
                        result.quarantined.append(QuarantineRecord(
                            "cell_fusion", ERA_EARLY_PDF, source_key, f[:80]))
                        continue
                    values = [v for v in cellvals if v is not None]
                    if len(values) < 2:
                        continue
                    if _crop_season_mismatch(crop, meta.season_type):
                        # a winter-cereal block inside a summer-attributed report (2008-09
                        # transition PDFs under this reader) -- other-season section, quarantine.
                        result.quarantined.append(QuarantineRecord(
                            "crop_season_mismatch", ERA_EARLY_PDF, source_key,
                            f"{crop} block under season_type={meta.season_type}"))
                        break
                    key = (crop, SCOPE_TOTAL)
                    if key in seen:
                        raise CecCollapseError(
                            f"{source_key}: two blocks emit ({crop}, total) -- early-PDF F3 invariant")
                    seen.add(key)
                    result.observations.append(CecObservation(
                        production_year=meta.production_year,
                        report_month=meta.report_month,
                        crop=crop,
                        scope=SCOPE_TOTAL,
                        estimate_number=meta.estimate_number,
                        current_estimate_t=values[1],
                        release_date=meta.release_date,
                        season_type=meta.season_type,
                        area_planted_ha=values[0],
                        source_format="pdf",
                        source_key=source_key,
                    ))
                    break
    return result


def _read_doc(data: bytes, era: str, source_key: str) -> CecParseResult:
    text = extract_doc_text(data)
    # The summary matrix ends where the first per-crop province detail table begins.
    head = re.split(r"kommersieel\s*:\s*wit", text, flags=re.IGNORECASE)[0]
    head = re.split(r"commercial\s*:\s*white", head, flags=re.IGNORECASE)[0]
    meta = _build_meta(era, source_key, text, text, "doc")
    result = CecParseResult(era=era, source_key=source_key)
    cells = [c.strip() for c in head.split("\x07")]
    rows, fused = _rows_from_cells(cells)
    for lbl in fused:
        result.quarantined.append(QuarantineRecord(
            "cell_fusion", era, source_key,
            f"{lbl[:80]}: a fused digit cell broke the row's positional integrity (W2.2)"))
    _emit_summary_rows(rows, meta, result)
    return result


def _rows_from_cells(cells: list[str]) -> tuple[list[tuple[str, list[float]]], list[str]]:
    """Group a flat .doc cell stream into (label, values) rows: a non-numeric label cell starts a
    row and the following numeric cells are its values (until the next label cell). Returns
    (rows, fused_labels) -- a row containing a fused digit cell (W2.2) is refused WHOLE and its
    label lands in the second list for the caller to quarantine."""
    rows: list[tuple[str, list[float]]] = []
    fused: list[str] = []
    label: Optional[str] = None
    values: list[float] = []
    poisoned = False

    def _flush() -> None:
        nonlocal poisoned
        if label is not None:
            if poisoned:
                fused.append(label)     # W2.2: positional integrity broken -> refuse the row whole
            else:
                rows.append((label, values))
        poisoned = False

    for cell in cells:
        if not cell:
            continue
        num = _cell_value(cell)
        if num is _MALFORMED:
            poisoned = True
        elif num is None:
            # a change-% cell ("+1,41") is not a value and not a new label -> ignore mid-row
            if "," in cell or "%" in cell:
                continue
            _flush()
            label, values = cell, []
        else:
            values.append(num)
    _flush()
    return rows, fused


def _read_xls(data: bytes, source_key: str) -> CecParseResult:
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    sheet = book.sheet_by_index(0)
    all_text_parts: list[str] = []
    grid: list[tuple[str, list[float]]] = []
    fused_rows: list[str] = []
    for r in range(sheet.nrows):
        raw_cells = [sheet.cell_value(r, c) for c in range(sheet.ncols)]
        label = ""
        for cell in raw_cells:
            if isinstance(cell, str) and cell.strip():
                label = cell.strip()
                all_text_parts.append(label)
                break
        cellvals = [_cell_value(c) for c in raw_cells]
        if any(v is _MALFORMED for v in cellvals):
            fused_rows.append(label[:80])
            continue
        values = [v for v in cellvals if v is not None]
        grid.append((label, values))

    full = "\n".join(all_text_parts)
    meta = _build_meta(ERA_XLS, source_key, full, full, "xls")
    result = CecParseResult(era=ERA_XLS, source_key=source_key)
    for lbl in fused_rows:
        result.quarantined.append(QuarantineRecord("cell_fusion", ERA_XLS, source_key, lbl))
    # Bound to the summary block: stop at the first province-detail header row.
    summary: list[tuple[str, list[float]]] = []
    for label, values in grid:
        f = _fold(label)
        if "wit- en geelmielies" in f or "white and yellow maize" in f:
            break
        summary.append((label, values))
    _emit_summary_rows(summary, meta, result)
    return result


# --------------------------------------------------------------------------- #
# Metadata assembly (shared)
# --------------------------------------------------------------------------- #
def _resolve_estimate_ordinal(
    era: str, source_key: str, full_text: str, season_type: Optional[str], production_year: int,
) -> int:
    """Resolve the report-level printed ordinal via TITLE-ANCHORED attribution (cec-w23).

    A CEC transition release (Aug-Dec/Jan) is a MULTI-SEASON document: the summer final forecast /
    intentions to plant sit next to the winter-cereal forecasts (and in January, next to the previous
    summer season's final). ONE scalar (production_year, estimate_number, season_type) cannot describe
    such a document, and the un-anchored earliest-ordinal read bled the other section's ordinal (or
    year) onto the emitted rows -- the source of every reconcile contradiction in the corpus census.

    Rules (fail-closed; ``S`` = the season whose matrix is emitted, ``py`` = production_year):
      1. Prefer the earliest S-NAMED data title whose printed title-year is ``py`` (or prints none).
         Under the EARLY-PDF reader a second S-named title for a DIFFERENT year (the January
         dual-summer layout) quarantines the file -- that reader walks per-crop province tables and
         cannot prove which season's table it read.
      2. S-named titles exist but ALL print a different year -> the emitted attribution belongs to
         another season-year (the October intentions+final combined matrix) -> QUARANTINE.
      3. No S-named title: an UNNAMED ordinal whose title prints EXACTLY ``py`` (the emitted
         matrix's own column headers, "sewende skatting ... 2004/05") is positive evidence and is
         used. Otherwise, if the OTHER season has a data title, the emitted matrix is an
         intentions / area-revision block with no ordinal of its own (Oct/Nov transition) ->
         QUARANTINE (never inherit the other season's ordinal -- the original defect).
      4. Otherwise: multi-season documents with orphan ordinals QUARANTINE; single-season documents
         fall back to the earliest year-consistent ordinal, else UNRESOLVED (rank-derived -- D2).
    Future-schedule notices ("... will be released on 27 June") are never attribution candidates."""
    cands = [c for c in _ordinal_candidates(full_text) if not c.notice]
    if season_type is None:
        return min(cands, key=lambda c: c.pos).n if cands else ESTIMATE_UNRESOLVED

    s_cands = [c for c in cands if c.season == season_type]
    o_cands = [c for c in cands if c.season not in (None, season_type)]
    u_cands = [c for c in cands if c.season is None]
    ok = [c for c in s_cands if c.title_year in (None, production_year)]
    if ok:
        if era == ERA_EARLY_PDF and any(c.title_year not in (None, production_year) for c in s_cands):
            raise CecNotImplementedEra(
                f"{source_key}: transition release with {season_type}-titles for two different "
                f"season-years under the early-PDF reader -- per-section reader required (cec-w23)")
        return min(ok, key=lambda c: c.pos).n
    if s_cands:
        years = sorted({c.title_year for c in s_cands})
        raise CecNotImplementedEra(
            f"{source_key}: transition release -- every {season_type}-season title prints year(s) "
            f"{years} != production_year {production_year} (combined intentions/final matrix; cec-w23)")
    u_strict = [c for c in u_cands
                if c.title_year == production_year and c.year_form == "pair"]
    if u_strict:
        # the emitted matrix's own column headers print ordinal + the emitted season-year in the
        # unambiguous PAIR form ("sewende skatting ... 2004/05") -- positive evidence (e.g. the Sep
        # 2004/05-final whose cover title is the unnumbered "FINALE"). A BARE calendar year is NOT
        # accepted here: winter sections print "second ... forecast: 2010 production season", whose
        # bare 2010 collides with the summer production_year (the Sep-2010/11/12 false rescue).
        return min(u_strict, key=lambda c: c.pos).n
    if o_cands:
        raise CecNotImplementedEra(
            f"{source_key}: transition release -- emitted {season_type} matrix has no printed "
            f"{season_type} ordinal while the other season does (intentions/area-revision; cec-w23)")
    has_summer, has_winter = _has_season_markers(full_text)
    if has_summer and has_winter and cands:
        raise CecNotImplementedEra(
            f"{source_key}: multi-season report with season-unattributable ordinal(s) (cec-w23)")
    ok2 = [c for c in u_cands if c.title_year in (None, production_year)]
    return min(ok2, key=lambda c: c.pos).n if ok2 else ESTIMATE_UNRESOLVED


def _build_meta(era: str, source_key: str, header_text: str, full_text: str, source_format: str) -> _ReportMeta:
    """Assemble report-level metadata, applying the D2b conservative-late release_date rule."""
    # season first: a COMBINED winter+summer report carries a distinct ordinal per section, so the
    # scalar report ordinal must be read for the season whose matrix is emitted (fixes the Feb
    # winter-final "5th" bleeding onto the summer 1st-estimate maize rows -- cec-w23).
    season_type = _season_type(header_text) or _season_type(full_text)

    production_year = _expand_season_end_year(header_text) or _expand_season_end_year(full_text)
    release_date = parse_release_date(header_text) or parse_release_date(full_text)

    report_month = _report_month_from_key(source_key)
    if report_month is None and release_date is not None:
        report_month = int(release_date[5:7])
    if production_year is None and release_date is not None:
        production_year = int(release_date[:4])

    if production_year is None or report_month is None:
        raise CecParseError(
            f"{source_key}: cannot establish production_year/report_month (era={era}) -- quarantine")

    # ordinal AFTER the year: the title-anchored rules cross-check each candidate title's printed
    # season-year against production_year and quarantine the multi-season transition releases the
    # scalar meta cannot describe (cec-w23).
    estimate_number = _resolve_estimate_ordinal(
        era, source_key, full_text, season_type, int(production_year))

    # D2b: if no printed release_date, impute a CONSERVATIVE LATE bound (end of report month),
    # never an early one (early = PIT lookahead leak).
    if release_date is None:
        release_date = _end_of_month(production_year, report_month)

    return _ReportMeta(
        era=era,
        source_key=source_key,
        production_year=int(production_year),
        report_month=int(report_month),
        estimate_number=int(estimate_number),
        release_date=release_date,
        season_type=season_type,
        source_format=source_format,
    )


# --------------------------------------------------------------------------- #
# Public entrypoints
# --------------------------------------------------------------------------- #
def parse_cec_report_detailed(data: bytes, source_key: str) -> CecParseResult:
    """Parse one raw CEC report -> :class:`CecParseResult` (observations + quarantine ledger + era)."""
    era = detect_era(data, source_key)
    if era == ERA_MODERN_PDF:
        return _read_modern_pdf(data, source_key)
    if era == ERA_EARLY_PDF:
        return _read_early_pdf(data, source_key)
    if era in (ERA_OLD_DOC, ERA_MODERN_DOC):
        return _read_doc(data, era, source_key)
    if era == ERA_XLS:
        return _read_xls(data, source_key)
    raise CecEraError(f"no reader for era {era!r}")  # unreachable; detect_era already fails closed


def parse_cec_report(data: bytes, source_key: str) -> list[CecObservation]:
    """Parse one raw CEC report into the list of ``CecObservation`` (the raw->silver contract).

    Fail-closed: an unknown era signature raises :class:`CecEraError`; a two-physical-row collapse
    raises :class:`CecCollapseError`; unrecognised sector/crop rows are quarantined (see
    :func:`parse_cec_report_detailed` for the ledger), never emitted with a guessed scope."""
    return parse_cec_report_detailed(data, source_key).observations


# --------------------------------------------------------------------------- #
# Corpus-level estimate_number reconciliation (D2 / D2a)
# --------------------------------------------------------------------------- #
def reconcile_estimate_numbers(observations: list[CecObservation]) -> list[CecObservation]:
    """Derive/verify estimate_number from release-date ordering across the CORPUS (D2).

    Groups by (production_year, crop, scope); within each group orders by (release_date, source_key)
    -- the D2a deterministic total order so equal-release_date ties (renamed-duplicate raw) resolve
    identically on byte-identical re-runs. The release-date rank (1-based) is the DERIVED estimate
    number; any PRINTED number that contradicts the ordering (a later release with a lower printed
    number) raises :class:`CecEstimateError` (D2 fail-closed on mismatch). Rows whose printed number
    was unresolved (:data:`ESTIMATE_UNRESOLVED`) are filled from the rank.

    Fail-closed but COLLECT-AND-REPORT-ALL: every contradicting group is gathered (one line per
    group, sorted by key for a deterministic report) and raised together, so a corpus dry-run surfaces
    the FULL set of attribution defects in one pass instead of dying on the first. The raise is
    unconditional whenever any contradiction exists -- the run still fails closed.

    Returns NEW observations (frozen dataclass); input is not mutated."""
    from collections import defaultdict

    groups: dict[tuple, list[CecObservation]] = defaultdict(list)
    for o in observations:
        groups[(o.production_year, o.crop, o.scope)].append(o)

    out: list[CecObservation] = []
    contradictions: list[tuple[tuple, str]] = []
    for key, members in groups.items():
        ordered = sorted(members, key=lambda o: (o.release_date or "", o.source_key or ""))
        printed = [(rank, o.estimate_number) for rank, o in enumerate(ordered, start=1)
                   if o.estimate_number != ESTIMATE_UNRESOLVED]
        # release-date ordering must not contradict the printed sequence: a strictly later release
        # (higher rank) can never carry a strictly lower printed estimate number. Record the FIRST
        # inversion per group (enough to flag it) and keep scanning the rest of the corpus.
        for (r1, n1), (r2, n2) in zip(printed, printed[1:]):
            if n2 < n1:
                contradictions.append((key, (
                    f"estimate_number order contradicts release-date order for {key}: "
                    f"printed {n1} (rank {r1}) then {n2} (rank {r2})")))
                break
        for rank, o in enumerate(ordered, start=1):
            resolved = rank if o.estimate_number == ESTIMATE_UNRESOLVED else o.estimate_number
            out.append(_replace_estimate(o, resolved))

    if contradictions:
        contradictions.sort(key=lambda kv: str(kv[0]))
        lines = "\n  ".join(msg for _, msg in contradictions)
        raise CecEstimateError(
            f"{len(contradictions)} estimate_number contradiction(s) across CEC groups:\n  {lines}")
    return out


def _replace_estimate(o: CecObservation, estimate_number: int) -> CecObservation:
    return CecObservation(
        production_year=o.production_year,
        report_month=o.report_month,
        crop=o.crop,
        scope=o.scope,
        estimate_number=estimate_number,
        current_estimate_t=o.current_estimate_t,
        release_date=o.release_date,
        season_type=o.season_type,
        area_planted_ha=o.area_planted_ha,
        source_format=o.source_format,
        source_key=o.source_key,
    )
