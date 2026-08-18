"""SILVER-F052: the shared MPOC source/versioning + HTML-table normalization adapter.

WHAT IT DOES (plan L688-690)
----------------------------
1. **Source-page versioning** -- :func:`version_page` records every fetched HTML page by
   ``as_of_date`` + a content ``sha256`` so a live-snapshot refresh (stock_comparison /
   competitive_prices are single-page live pages) can NEVER erase prior evidence. The version log
   is append-only + deduplicated on ``(release_type, source_url, content_sha256)``: an unchanged
   refetch is a no-op, a changed page adds a new immutable version. This is the provenance spine
   the F055 stock-comparison producer's mandatory source-as-of requirement stands on.

2. **Source-faithful HTML-table normalization** -- :func:`parse_tables` reads every ``<table>``
   through one library (``bs4`` + lxml) into a :class:`NormalizedTable` that preserves table
   IDENTITY (the nearest preceding heading/caption), the header row, and the cell grid verbatim.
   No numbers are coerced here -- faithfulness first; the producers coerce with :func:`parse_number`
   under an explicit unit hint.

3. **Vocabulary normalization** -- :func:`normalize_country` and :func:`normalize_oil_type` map the
   MPOC surface forms to the canonical silver vocabulary; :func:`parse_number` strips thousands
   separators / footnote marks / unit suffixes deterministically.

4. **Drift diagnostics** -- :func:`diagnose_table_drift` compares an observed table's header +
   identity against an expected fingerprint and returns structured findings so a changed MPOC
   layout fails LOUD in a producer instead of silently mis-mapping columns.

Pure + AWS-free + ASCII-only. ``bs4``/``lxml`` are already project deps (used by the raw->text
layer). Nothing here reads S3 or prints.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 1. Source-page versioning (append-only evidence preservation).
# ---------------------------------------------------------------------------
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class SourceVersion:
    """One immutable record of a fetched MPOC source page.

    ``content_sha256`` is over the raw page bytes: two fetches with identical content collapse to
    one version (idempotent refresh); a changed page is a NEW version, never an overwrite."""

    release_type: str
    source_url: str
    as_of_date: str            # ISO YYYY-MM-DD -- the knowledge date of THIS fetch
    content_sha256: str
    byte_len: int

    def key(self) -> tuple[str, str, str]:
        return (self.release_type, self.source_url, self.content_sha256)

    def to_dict(self) -> dict:
        return {
            "release_type": self.release_type,
            "source_url": self.source_url,
            "as_of_date": self.as_of_date,
            "content_sha256": self.content_sha256,
            "byte_len": self.byte_len,
        }


def version_page(*, html: bytes, release_type: str, source_url: str, as_of_date: str) -> SourceVersion:
    """Build the :class:`SourceVersion` evidence record for one fetched page."""
    if not _ISO_DATE_RE.match(as_of_date or ""):
        raise ValueError(f"as_of_date must be ISO YYYY-MM-DD, got {as_of_date!r}")
    body = html if isinstance(html, (bytes, bytearray)) else str(html).encode("utf-8")
    return SourceVersion(
        release_type=release_type,
        source_url=source_url,
        as_of_date=as_of_date,
        content_sha256=hashlib.sha256(bytes(body)).hexdigest(),
        byte_len=len(bytes(body)),
    )


def merge_version_log(existing: list[dict], new: list[SourceVersion]) -> list[dict]:
    """Append-only merge of new versions into an existing version log, deduped on the content key.

    An unchanged refetch (same release_type+url+content hash) is dropped; a changed page is kept.
    Prior evidence is NEVER removed -- the log only grows. Deterministic order: existing first,
    then new versions in call order."""
    out = list(existing)
    seen = {(e["release_type"], e["source_url"], e["content_sha256"]) for e in existing}
    for v in new:
        if v.key() not in seen:
            out.append(v.to_dict())
            seen.add(v.key())
    return out


# ---------------------------------------------------------------------------
# 2. Source-faithful HTML-table normalization.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NormalizedTable:
    """One HTML ``<table>`` normalized to a header + cell grid, tagged with its identity."""

    index: int                       # position of the table in the document (0-based)
    identity: str                    # nearest preceding heading/caption text (table identity)
    header: tuple[str, ...]          # first row cells (verbatim, whitespace-collapsed)
    rows: tuple[tuple[str, ...], ...]  # remaining rows
    caption: Optional[str] = None

    def header_fingerprint(self) -> str:
        """A stable identity fingerprint of the header (lower-cased, order-preserving)."""
        norm = "|".join(_collapse_ws(h).lower() for h in self.header)
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _nearest_heading(table_tag) -> str:
    """The nearest preceding heading/caption text that names a table (its identity)."""
    cap = table_tag.find("caption")
    if cap and _collapse_ws(cap.get_text()):
        return _collapse_ws(cap.get_text())
    node = table_tag.previous_element
    hops = 0
    while node is not None and hops < 400:
        name = getattr(node, "name", None)
        if name in ("h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "th", "caption"):
            txt = _collapse_ws(node.get_text())
            if txt:
                return txt
        node = node.previous_element
        hops += 1
    return ""


def parse_tables(html: str) -> list[NormalizedTable]:
    """Parse every ``<table>`` in ``html`` into a :class:`NormalizedTable` (source-faithful).

    Header = the first ``<tr>``; each cell's text is whitespace-collapsed but otherwise verbatim
    (no numeric coercion). Rows shorter/longer than the header are kept as-is so a producer's
    drift check can see the mismatch instead of a silent pad/truncate."""
    text = html.decode("utf-8", "replace") if isinstance(html, (bytes, bytearray)) else html
    soup = BeautifulSoup(text, "lxml")
    out: list[NormalizedTable] = []
    for i, tbl in enumerate(soup.find_all("table")):
        trs = tbl.find_all("tr")
        if not trs:
            continue
        grid: list[tuple[str, ...]] = []
        for tr in trs:
            cells = tr.find_all(["th", "td"])
            grid.append(tuple(_collapse_ws(c.get_text()) for c in cells))
        header = grid[0] if grid else ()
        rows = tuple(grid[1:])
        cap = tbl.find("caption")
        out.append(NormalizedTable(
            index=i,
            identity=_nearest_heading(tbl),
            header=header,
            rows=rows,
            caption=_collapse_ws(cap.get_text()) if cap else None,
        ))
    return out


# ---------------------------------------------------------------------------
# 3. Vocabulary + numeric normalization.
# ---------------------------------------------------------------------------
# Canonical silver country vocabulary (lower_snake). MPOC surface forms -> canonical.
# D-LD Tranche 2 (2026-08-18): `china p.r` and `u.s.a` are LIVE MPOC surface forms that folded to a
# key the map did not carry, so normalize_country returned None and the F053 producer dropped the row
# WITHOUT a warning -- 9 rows across the 2015-2020 pages (china 2015-2017, usa 2015-2020). The map
# already had 'p.r. china' / 'pr china' (the other spelling) and 'u.s.a.' (WITH the trailing dot);
# these two are the same countries under MPOC's other printed spelling, not new destinations. Measured
# effect: silver goes 121 -> 130 rows and the china/usa gaps -- which a desk would otherwise narrate as
# demand collapsing -- close as the INGEST LOSS they were.
_COUNTRY_ALIASES: dict[str, str] = {
    "china": "china",
    "p.r. china": "china",
    "pr china": "china",
    "china p.r": "china",
    "india": "india",
    "pakistan": "pakistan",
    "bangladesh": "bangladesh",
    "usa": "usa",
    "u.s.a.": "usa",
    "u.s.a": "usa",          # D-LD tranche 2: MPOC's 2015-2020 spelling (no trailing dot) -- 6 rows
    "united states": "usa",
    "united states of america": "usa",
    "eu": "eu",
    "european union": "eu",
    "eu-27": "eu",
    "eu 27": "eu",
    "netherlands": "netherlands",
    "turkey": "turkey",
    "turkiye": "turkey",
    "japan": "japan",
    "philippines": "philippines",
    "vietnam": "vietnam",
    "viet nam": "vietnam",
    "korea": "south_korea",
    "south korea": "south_korea",
    "republic of korea": "south_korea",
    "egypt": "egypt",
    "kenya": "kenya",
    "iran": "iran",
    "iraq": "iraq",
    "saudi arabia": "saudi_arabia",
    "myanmar": "myanmar",
    "russia": "russia",
    "ukraine": "ukraine",
    "spain": "spain",
    "italy": "italy",
    "brazil": "brazil",
    "singapore": "singapore",
    "tanzania": "tanzania",
    "others": "others",
    "other": "others",
    "total": "total",
    "grand total": "total",
    "world": "world",
}

# Canonical oil-type vocabulary for stock_comparison.
_OIL_TYPE_ALIASES: dict[str, str] = {
    "palm": "palm_oil",
    "palm oil": "palm_oil",
    "palmoil": "palm_oil",
    "cpo": "palm_oil",
    "soy": "soybean_oil",
    "soya": "soybean_oil",
    "soybean": "soybean_oil",
    "soybean oil": "soybean_oil",
    "soyabean oil": "soybean_oil",
    "soy oil": "soybean_oil",
    "sbo": "soybean_oil",
    "sun": "sunflower_oil",
    "sunflower": "sunflower_oil",
    "sunflower oil": "sunflower_oil",
    "sunflowerseed oil": "sunflower_oil",
    "sfo": "sunflower_oil",
    "rape": "rapeseed_oil",
    "rapeseed": "rapeseed_oil",
    "rapeseed oil": "rapeseed_oil",
    "canola": "rapeseed_oil",
    "canola oil": "rapeseed_oil",
}


def _fold(raw: str) -> str:
    """Lower-case, strip accents + trailing footnote symbols, collapse whitespace.

    Trailing *symbols* (``* + dagger``) are footnote marks and are stripped; trailing digits are
    NOT stripped (they are meaningful, e.g. the ``eu-27`` alias) -- number/month parsing is done by
    the dedicated parsers, not here."""
    s = unicodedata.normalize("NFKD", raw or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _collapse_ws(s).lower()
    s = re.sub(r"[*+†‡]+$", "", s).strip()  # trailing footnote symbols only
    return s


def normalize_country(raw: str) -> Optional[str]:
    """Map an MPOC country surface form to the canonical vocabulary, or ``None`` if unknown."""
    folded = _fold(raw)
    if not folded:
        return None
    return _COUNTRY_ALIASES.get(folded)


def normalize_oil_type(raw: str) -> Optional[str]:
    """Map an MPOC oil-type surface form to the canonical vocabulary, or ``None`` if unknown."""
    folded = _fold(raw)
    if not folded:
        return None
    if folded in _OIL_TYPE_ALIASES:
        return _OIL_TYPE_ALIASES[folded]
    # tolerate a leading qualifier, e.g. "crude palm oil" -> palm_oil
    for token, canon in _OIL_TYPE_ALIASES.items():
        if folded.endswith(token):
            return canon
    return None


_NUM_TOKEN_RE = re.compile(r"[-+]?\d*\.?\d+")


def parse_number(raw: str) -> Optional[float]:
    """Parse an MPOC numeric cell to ``float`` (thousands separators / footnotes / units stripped).

    Returns ``None`` for blank / dash / 'n.a.' / non-numeric cells so a producer can distinguish a
    genuine missing value from a zero. A parenthesised value ``(1,234)`` is read as negative. Unit
    words that happen to contain 'e' (e.g. 'tonnes') never leak into the number: the first numeric
    TOKEN is extracted, not a char-filter."""
    if raw is None:
        return None
    s = _collapse_ws(str(raw))
    if not s or s.lower() in {"-", "--", "n.a.", "na", "n/a", "nil", "."}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    core = s.replace(",", "").replace(" ", "")
    m = _NUM_TOKEN_RE.search(core)
    if not m:
        return None
    val = float(m.group(0))
    return -val if neg else val


MONTHS: dict[str, int] = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_month(raw: str) -> Optional[int]:
    """Map a month label ('Jan', 'JANUARY', '01', '3') to 1..12, or ``None``."""
    s = _collapse_ws(str(raw or "")).lower()
    if not s:
        return None
    if s.isdigit():
        m = int(s)
        return m if 1 <= m <= 12 else None
    letters = re.sub(r"[^a-z]", "", s)   # drop footnote marks/superscripts, keep month letters
    if not letters:
        return None
    return MONTHS.get(letters[:9]) or MONTHS.get(letters[:3])


# ---------------------------------------------------------------------------
# 4. Drift diagnostics.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DriftFinding:
    """One structured layout-drift finding for a producer to fail on."""

    kind: str          # missing_table | header_changed | missing_column | identity_changed
    detail: str
    observed: object = None
    expected: object = field(default=None)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail,
                "observed": self.observed, "expected": self.expected}


def diagnose_table_drift(
    table: Optional[NormalizedTable],
    *,
    expected_identity_substr: Optional[str] = None,
    expected_columns: Optional[list[str]] = None,
) -> list[DriftFinding]:
    """Compare an observed normalized table against an expected identity + required header columns.

    ``expected_columns`` are matched case-insensitively as substrings of any header cell (MPOC
    headers carry units, e.g. 'Exports (tonnes)'). Returns an ordered list of findings (empty ==
    the layout matches). A producer treats a non-empty result as a hard, loud failure."""
    findings: list[DriftFinding] = []
    if table is None:
        findings.append(DriftFinding("missing_table",
                                     f"no table matched identity ~ {expected_identity_substr!r}",
                                     observed=None, expected=expected_identity_substr))
        return findings
    if expected_identity_substr:
        ident = (table.identity or "").lower() + " " + (table.caption or "").lower()
        if expected_identity_substr.lower() not in ident:
            findings.append(DriftFinding(
                "identity_changed",
                f"table identity {table.identity!r} lacks expected {expected_identity_substr!r}",
                observed=table.identity, expected=expected_identity_substr))
    if expected_columns:
        header_l = [h.lower() for h in table.header]
        for col in expected_columns:
            if not any(col.lower() in h for h in header_l):
                findings.append(DriftFinding(
                    "missing_column",
                    f"expected header column ~ {col!r} not found",
                    observed=list(table.header), expected=col))
    return findings


def find_table(tables: list[NormalizedTable], identity_substr: str) -> Optional[NormalizedTable]:
    """First table whose identity/caption contains ``identity_substr`` (case-insensitive).

    NOTE: MPOC's current live pages render every data table inside an Elementor *tab widget* whose
    section titles all sit in the nav BEFORE any panel content, so :func:`_nearest_heading` can only
    ever reach the preceding table's trailing number cells -- table identity is unreliable on the
    live layout. Prefer :func:`find_table_by_header` (header-row signature) for those pages; this
    heading-based finder still serves the older archive pages that carry numbered section headings."""
    needle = identity_substr.lower()
    for t in tables:
        blob = (t.identity or "").lower() + " " + (t.caption or "").lower()
        if needle in blob:
            return t
    return None


def find_table_by_header(
    tables: list[NormalizedTable],
    *,
    first_col: Optional[str] = None,
    header_all: Optional[list[str]] = None,
    header_any: Optional[list[str]] = None,
) -> Optional[NormalizedTable]:
    """Resolve a table by its HEADER-ROW signature -- robust when section headings are absent.

    The header row is the stable anchor on MPOC's live tab-widget pages (see :func:`find_table`).
    All checks are case-insensitive against the whitespace-collapsed header cells:

    * ``first_col`` -- the first header cell must START WITH this string (e.g. ``"country"`` selects
      the country-grain tables). Combined with returning the FIRST match, this picks the leading
      "Exports to Major Countries" table ahead of the trailing full-destination list.
    * ``header_all`` -- every token must appear as a substring of SOME header cell (e.g.
      ``["export", "import"]`` uniquely selects the monthly Exports/Imports table).
    * ``header_any`` -- at least one token must appear as a substring of some header cell.

    Returns the FIRST table satisfying every supplied constraint, or ``None`` (a producer treats
    ``None`` as fail-closed layout drift)."""
    for t in tables:
        header_l = [(h or "").strip().lower() for h in t.header]
        if first_col is not None:
            if not header_l or not header_l[0].startswith(first_col.lower()):
                continue
        if header_all is not None and not all(
            any(tok.lower() in h for h in header_l) for tok in header_all
        ):
            continue
        if header_any is not None and not any(
            any(tok.lower() in h for h in header_l) for tok in header_any
        ):
            continue
        return t
    return None
