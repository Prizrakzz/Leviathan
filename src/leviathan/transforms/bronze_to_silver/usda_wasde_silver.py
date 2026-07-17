"""Coherent WASDE bronze->silver transform (SILVER-F033 / F034 / F036).

This is the pure, current-`main` restoration of the WASDE bronze->silver producer that the
Ultimate Data Plan (LANE M) requires. It is deliberately a fresh, source-faithful implementation
(NOT a cherry-pick of the historical off-main producer) and it holds the plan's invariants:

* **F033 -- source-faithful parse + region-junk gate.** ``parse_marketing_year_status`` reads
  ``"2026/27 (Proj.) May"`` STRUCTURALLY into ``(marketing_year, estimate_role, projection_month)``
  so a bare month name can never leak into the ``region`` axis. ``classify_region`` /
  ``region_pollution_census`` measure the region defect the way the live 72,780-row re-census
  proved it (Attack 1 #1): a long tail of malformed DISTINCT tokens at LOW row prevalence -- NOT a
  ~50%-of-rows majority. The gate (``region_cleanliness_gate``) therefore fires on *distinct-value
  pollution fraction* AND asserts the malformed tokens stay a small share of rows; a ~50%-of-rows
  floor (the draft's calibration) would never trip and is explicitly rejected.

* **F034 -- coherent producer.** Every displayed estimate survives into silver with an explicit
  ``estimate_role`` / ``projection_month``; ONE deterministic source-supported current-release
  estimate is marked (``is_current_release_estimate``) for revision math rather than discarding the
  comparison columns; conflicting natural keys are NEVER resolved with drop/keep-last
  (``resolve_conflicts`` raises :class:`WasdeKeyConflict`); revisions are computed only within a
  stable logical series with release-sequence + release-gap metadata; the commodity marketing-year
  calendar has NO universal June fallback (an unsupported commodity quarantines, it never imputes).
  ``is_final_or_latest`` is deprecated (never re-computed here); a nullable ``is_source_final`` is
  set only when the source supports it; latest state is a query/view over release dates
  (``latest_state_view``), not a timeless row flag.

* **F036 -- explicit writer schema (INV-2).** ``arrow_schema_from_contract`` /
  ``to_arrow_table`` build the writer's ``pyarrow`` schema from the SILVER-F010 registry contract's
  ``target_arrow_type`` -- first-file inference is never used. The nine additive governed columns
  (``source_table_id``, ``estimate_role``, ``projection_month``, ``is_current_release_estimate``,
  ``release_sequence``, ``revision_gap_days``, ``is_projection``, ``is_source_final``,
  ``marketing_year_end_date``) are produced here and carried by the schema.

The module is PURE + AWS-free + deterministic + ASCII-only. It consumes the bronze long rows emitted
by :mod:`leviathan.transforms.raw_to_bronze.usda_wasde` (columns: ``release_date, table_name,
region, market_year, status, projection_month, attribute, value, unit``) and returns silver rows +
a quarantine ledger + the region gate. The controlled S3/Glue publish is a separate concern handled
by :mod:`jobs.batch.wasde_silver_task` through the SILVER-F015 :class:`ShadowPublisher` (dry-run by
default); this module writes nothing.
"""
from __future__ import annotations

import calendar as _calmod
import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Iterable, Optional, Sequence

from leviathan.silver.value_census import GateRow

if TYPE_CHECKING:  # pyarrow is imported lazily inside the writer-schema functions below.
    import pyarrow as pa

# ---------------------------------------------------------------------------
# Canonical vocabularies (INV-1: the physical vocabulary the numbers registry must match exactly).
# ---------------------------------------------------------------------------
# The 19 normalized snake_case attribute terms (plan L567). Anything else is quarantined, never
# silently renamed or published.
WASDE_ATTRIBUTES: frozenset[str] = frozenset({
    "avg_farm_price",
    "beginning_stocks",
    "crush",
    "domestic_total",
    "ending_stocks",
    "exports",
    "feed",
    "feed_residual",
    "food_use",
    "harvested_area",
    "imports",
    "loss",
    "planted_area",
    "production",
    "residual",
    "seed_use",
    "total_supply",
    "total_use",
    "yield",
})

# Raw header fragment -> canonical attribute. Only maps that resolve INTO WASDE_ATTRIBUTES are kept;
# a raw attribute that does not resolve (e.g. the historical "trade" line) is quarantined.
_ATTRIBUTE_ALIASES: dict[str, str] = {
    "avg_farm_price": "avg_farm_price",
    "avg. farm price": "avg_farm_price",
    "average farm price": "avg_farm_price",
    "farm price": "avg_farm_price",
    "beginning_stocks": "beginning_stocks",
    "beginning stocks": "beginning_stocks",
    "beginning": "beginning_stocks",
    "beg. stocks": "beginning_stocks",
    "beg stocks": "beginning_stocks",
    "crush": "crush",
    "domestic_total": "domestic_total",
    "domestic total": "domestic_total",
    "domestic": "domestic_total",
    "domestic use": "domestic_total",
    "ending_stocks": "ending_stocks",
    "ending stocks": "ending_stocks",
    "ending": "ending_stocks",
    "exports": "exports",
    "feed": "feed",
    "feed_residual": "feed_residual",
    "feed and residual": "feed_residual",
    "feed/residual": "feed_residual",
    "food_use": "food_use",
    "food": "food_use",
    "food use": "food_use",
    "harvested_area": "harvested_area",
    "harvested": "harvested_area",
    "harvested area": "harvested_area",
    "imports": "imports",
    "loss": "loss",
    "planted_area": "planted_area",
    "planted": "planted_area",
    "planted area": "planted_area",
    "production": "production",
    "output": "production",
    "residual": "residual",
    "seed_use": "seed_use",
    "seed": "seed_use",
    "seed use": "seed_use",
    "total_supply": "total_supply",
    "total supply": "total_supply",
    "supply, total": "total_supply",
    "supply total": "total_supply",
    "total_use": "total_use",
    "total use": "total_use",
    "use, total": "total_use",
    "use total": "total_use",
    "yield": "yield",
    "yield per harvested": "yield",
    "yield per harvested acre": "yield",
}

# estimate_role vocabulary. Derived deterministically from the source status marker; NO invented
# roles (the "don't force +/- on 0-signs" doctrine applied to WASDE finality).
ROLE_PROJECTION = "projection"   # source printed "(Proj.)"
ROLE_ESTIMATE = "estimate"       # source printed "(Est.)"
ROLE_ACTUAL = "actual"           # settled year, no status marker
ESTIMATE_ROLES: frozenset[str] = frozenset({ROLE_PROJECTION, ROLE_ESTIMATE, ROLE_ACTUAL})

# The commodity marketing-year END month (1-12). This is the reviewed calendar F034 mandates INSTEAD
# of a universal June fallback: a commodity that is NOT in this table quarantines (never imputes an
# end month). USDA marketing-year conventions.
MARKETING_YEAR_END_MONTH: dict[str, int] = {
    "wheat": 5,          # Jun - May
    "barley": 5,
    "oats": 5,
    "rye": 5,
    "corn": 8,           # Sep - Aug
    "sorghum": 8,
    "soybeans": 8,
    "rice": 7,           # Aug - Jul
    "cotton": 7,
    "soybean_meal": 9,   # Oct - Sep
    "soybean_oil": 9,
    "sugar": 9,
    "peanuts": 7,
}

# table_name -> (commodity, table_type). Deterministic; an unmatched heading quarantines. table_type
# is the geographic scope class carried by the source table ("world" | "us").
_TABLE_COMMODITY_PATTERNS: tuple[tuple[str, str], ...] = (
    # (regex over the lower-cased heading, commodity slug). First match wins; order is specific->broad.
    (r"soybean\s*meal|soymeal", "soybean_meal"),
    (r"soybean\s*oil|soyoil", "soybean_oil"),
    (r"soybean", "soybeans"),
    (r"\bwheat\b", "wheat"),
    (r"\bcorn\b", "corn"),
    (r"\bsorghum\b", "sorghum"),
    (r"\bbarley\b", "barley"),
    (r"\boats?\b", "oats"),
    (r"\brye\b", "rye"),
    (r"\brice\b", "rice"),
    (r"\bcotton\b", "cotton"),
    (r"\bsugar\b", "sugar"),
    (r"\bpeanuts?\b", "peanuts"),
)


# ---------------------------------------------------------------------------
# The final silver column contract (the order the writer emits + the arrow schema pins).
# 20 legacy physical columns + 9 F036 additive columns. release_date is the Hive partition key.
# ---------------------------------------------------------------------------
PARTITION_KEY = "release_date"

LEGACY_COLUMNS: tuple[str, ...] = (
    "commodity", "table_type", "region", "marketing_year", "attribute", "unit", "estimate",
    "prior_release_date", "prior_estimate", "revision", "revision_direction",
    "months_to_marketing_year_end", "is_first_estimate", "is_final_or_latest",
    "raw_table_name", "raw_region", "raw_attribute", "raw_status", "raw_projection_month", "source",
)

ADDITIVE_COLUMNS: tuple[str, ...] = (
    "source_table_id", "estimate_role", "projection_month", "is_current_release_estimate",
    "release_sequence", "revision_gap_days", "is_projection", "is_source_final",
    "marketing_year_end_date",
)

SILVER_COLUMNS: tuple[str, ...] = LEGACY_COLUMNS + ADDITIVE_COLUMNS

# The frozen F033 natural key (target). release_date is the partition; the row grain is the rest.
NATURAL_KEY: tuple[str, ...] = (
    "release_date", "source_table_id", "commodity", "region", "marketing_year",
    "attribute", "unit", "estimate_role", "projection_month",
)

# The stable logical series a revision is computed WITHIN (a single balance-sheet line for a single
# marketing year, tracked across release_dates -- regardless of the changing estimate_role).
REVISION_SERIES_KEY: tuple[str, ...] = (
    "source_table_id", "commodity", "region", "marketing_year", "attribute",
)

# The deprecated compatibility columns retained but NOT repurposed (F036).
DEPRECATED_COLUMNS: frozenset[str] = frozenset({"is_final_or_latest", "months_to_marketing_year_end"})

_SOURCE = "usda_wasde"

_MONTHS = {
    "january": "January", "february": "February", "march": "March", "april": "April",
    "may": "May", "june": "June", "july": "July", "august": "August",
    "september": "September", "october": "October", "november": "November", "december": "December",
}
_MONTH_NAMES_LOWER = frozenset(_MONTHS)

# Bare month ABBREVIATIONS leak into the region axis from scanned-era two-vintage
# projection column headers ("Feb. Proj. / Mar. Proj." on World S&U continuation
# tables) -- Textract row reconstruction emits the header token as a region cell.
# 1989-03-09 live canary: region='Mar'/'Mar.' rows carried stray numbers that
# collided on the F036 natural key (0.31 vs 16.0 -- parse noise, not competing
# estimates). Exact-token match only: no real WASDE geographic scope is a bare
# 3-letter month abbreviation.
_MONTH_ABBREVS_LOWER = frozenset({
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec",
})

# Roman-numeral OCR / column-index fragments leak into the region axis of scanned-era
# World S&U continuation tables -- Textract reconstructs a numbered column header or a
# footnote roman numeral ("II *", "III", "IV *") as a region cell. 1994-07-12 live canary:
# region='II' rows on world_soybean_oil_supply_and_use carried stray numbers that collided
# on the F036 natural key (6050.0 vs 67.0 -- parse noise, not competing estimates); the same
# ii/iii/iv signature recurs across the whole 1994-1999 scanned era. Exact-token match on the
# canonical roman numerals 1-10: NO real WASDE geographic scope is a bare roman numeral. (i/v/x
# are single characters already quarantined by the REGION_SINGLE_CHAR rule; they are listed here
# only to make the set self-documenting -- the roman check sits AFTER the single-char check.)
_ROMAN_NUMERALS_LOWER = frozenset({
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
})

# A month token (name OR abbreviation) followed by a projection/estimate marker is a
# TWO-VINTAGE PROJECTION COLUMN HEADER leaked into the region axis ("Sep. Proj", "Aug Proj",
# "Feb Est" on scanned-era World S&U tables) -- the multi-token sibling of the bare month-abbrev
# leak. 1994-10-12 canary: region='Sep Proj' collided on the natural key (56.0 vs 66.0). The rule
# is general (every month x {proj,est}) so it pre-empts the whack-a-mole rather than chasing one
# colliding header at a time; it is anchored (^...$) and marker-terminated so a real region can
# never partial-match. Same quarantine class as a bare month header (REGION_MONTH_NAME).
_HEADER_MARKERS = (
    "proj", "projection", "projections", "projected",
    "est", "estimate", "estimated", "estimates",
)
_MONTH_HEADER_RE = re.compile(
    r"^(?:"
    + "|".join(sorted(_MONTH_NAMES_LOWER | _MONTH_ABBREVS_LOWER, key=len, reverse=True))
    + r")_(?:"
    + "|".join(_HEADER_MARKERS)
    + r")$"
)


class WasdeKeyConflict(RuntimeError):
    """Two rows share a natural key with DIVERGENT estimate values. F034 forbids drop/keep-last;
    the conflict is surfaced (fail/quarantine), never silently resolved."""


# ---------------------------------------------------------------------------
# F033 -- region cleanliness (distinct-value pollution, low row prevalence).
# ---------------------------------------------------------------------------
_NUMERIC_CONCAT_RE = re.compile(r"^[a-z]*_?\d+(?:_\d+){1,}$")   # e.g. february_0_30_4_58_0_62
_PURE_NUMERIC_RE = re.compile(r"^[\d.,_-]+$")
# header/attribute words that leak into the region axis. NOTE: "world" / "us" / "united_states" are
# LEGIT scopes and are deliberately NOT here (removing them was the recon's top-15-by-row list).
_HEADER_LEAK_TOKENS = frozenset({
    "item", "items", "table", "supply", "use", "and", "total",
    "continued", "proj", "est", "projected", "estimated",
})

REGION_CLEAN = "clean"
REGION_EMPTY = "empty"
REGION_MONTH_NAME = "month_name"
REGION_NUMERIC_CONCAT = "numeric_concat"
REGION_PURE_NUMERIC = "pure_numeric"
REGION_SINGLE_CHAR = "single_char"
REGION_HEADER_LEAK = "header_leak"
REGION_ROMAN_NUMERAL = "roman_numeral"

_MALFORMED_CLASSES = frozenset({
    REGION_EMPTY, REGION_MONTH_NAME, REGION_NUMERIC_CONCAT, REGION_PURE_NUMERIC,
    REGION_SINGLE_CHAR, REGION_HEADER_LEAK, REGION_ROMAN_NUMERAL,
})

# The region-gate KIND surfaced as a value-census GateRow (parallel to KIND_ALL_NAN etc).
KIND_REGION_POLLUTED = "region_polluted"


def normalize_region(raw: str) -> str:
    """Snake_case a region label into the numbers-registry scope form (united_states, world, ...).

    Strips trailing footnote refs and punctuation; collapses whitespace to a single underscore. This
    is the value the ``region`` column carries; ``raw_region`` keeps the original for provenance.
    """
    s = (raw or "").strip()
    s = re.sub(r"\s*\d+/\s*$", "", s)         # trailing FOOTNOTE "3/" (slash required; keeps eu_27)
    s = s.lower().replace(".", "").replace(",", "")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def classify_region(raw: str) -> str:
    """Classify a RAW region token into a cleanliness class (F033).

    Clean == a plausible geographic scope. The malformed classes are exactly the distinct-value
    pollution the live re-census + the archival key-conflict sweep found: month names leaked from a
    mis-parsed year header, bare month abbreviations and month+marker column headers (``Sep Proj``,
    ``Feb Est``), numeric concatenations (``february_0_30_4_58_0_62``), pure numerics, single
    characters (``i``), roman-numeral OCR/column fragments (``II *``, ``III``, ``IV``), and
    header/attribute leaks (``item``). Legitimate multi-token scopes (``eu_27``, ``fsu_12``) are
    NOT flagged just for containing a digit -- only the >=2-underscore-separated numeric-group
    signature is (the 0.6% clean signal from the recon).
    """
    s = (raw or "").strip()
    if not s:
        return REGION_EMPTY
    low = s.lower()
    norm = normalize_region(s)
    if not norm:
        return REGION_EMPTY
    # a bare month name is the classic "year header leaked into region" defect
    if low.rstrip(".:") in _MONTH_NAMES_LOWER or norm in _MONTH_NAMES_LOWER:
        return REGION_MONTH_NAME
    # bare month ABBREVIATION ("Feb." / "Mar.") = a two-vintage projection column
    # header leaked into the region axis (scanned-era continuation tables); its rows
    # carry stray numbers that collide on the F036 natural key (1989-03-09 canary).
    if low.rstrip(".:") in _MONTH_ABBREVS_LOWER or norm in _MONTH_ABBREVS_LOWER:
        return REGION_MONTH_NAME
    # month token + projection/estimate MARKER ("Sep. Proj", "Aug Proj", "Feb Est") = the
    # multi-token sibling of the bare month-abbrev leak (two-vintage column header). Same
    # collide-on-the-key defect as a bare month header (1994-10-12 'Sep Proj' canary).
    if _MONTH_HEADER_RE.match(norm):
        return REGION_MONTH_NAME
    # single alpha character (OCR fragment "i")
    if len(norm) == 1 and norm.isalpha():
        return REGION_SINGLE_CHAR
    # bare roman numeral ("II *", "III", "IV") = an OCR / column-index fragment from a
    # scanned-era continuation table (1994-07-12 'II' canary). i/v/x are already caught above
    # as single characters; ii/iii/iv/vi/vii/viii/ix are quarantined here by exact token.
    if norm in _ROMAN_NUMERALS_LOWER:
        return REGION_ROMAN_NUMERAL
    # pure numeric / punctuation-only
    if _PURE_NUMERIC_RE.match(low):
        return REGION_PURE_NUMERIC
    # numeric-concatenation signature (optionally month-prefixed): >=2 underscore-separated numbers
    if _NUMERIC_CONCAT_RE.match(norm):
        return REGION_NUMERIC_CONCAT
    # header / attribute word leak
    if low.rstrip(".:") in _HEADER_LEAK_TOKENS or norm in _HEADER_LEAK_TOKENS:
        return REGION_HEADER_LEAK
    return REGION_CLEAN


def is_clean_region(raw: str) -> bool:
    return classify_region(raw) == REGION_CLEAN


@dataclass(frozen=True)
class RegionPollutionCensus:
    """The F033 region defect measured the way the live re-census measured it: distinct-value
    pollution + row prevalence (NOT a fraction-of-rows majority)."""

    total_rows: int
    distinct_regions: int
    malformed_distinct: int
    malformed_rows: int
    distinct_pollution_fraction: float    # malformed_distinct / distinct_regions
    row_prevalence_fraction: float        # malformed_rows / total_rows
    malformed_by_class: dict[str, int]
    malformed_examples: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "distinct_regions": self.distinct_regions,
            "malformed_distinct": self.malformed_distinct,
            "malformed_rows": self.malformed_rows,
            "distinct_pollution_fraction": round(self.distinct_pollution_fraction, 6),
            "row_prevalence_fraction": round(self.row_prevalence_fraction, 6),
            "malformed_by_class": dict(self.malformed_by_class),
            "malformed_examples": list(self.malformed_examples),
        }


def region_pollution_census(regions: Sequence[str]) -> RegionPollutionCensus:
    """Compute the distinct-value pollution + row prevalence of a region column.

    ``regions`` is the RAW region value of every row (repeats allowed). Distinct pollution is the
    fraction of DISTINCT tokens that are malformed; row prevalence is the fraction of ROWS carrying a
    malformed token. The recon showed the first is large (a fifth-to-half) while the second is small
    (~1-6%) -- so the gate must key on the first, and assert the second stays low.
    """
    total_rows = len(regions)
    counts: dict[str, int] = {}
    for r in regions:
        counts[r] = counts.get(r, 0) + 1
    distinct = list(counts)
    malformed_by_class: dict[str, int] = {}
    malformed_distinct = 0
    malformed_rows = 0
    examples: list[str] = []
    for token in distinct:
        cls = classify_region(token)
        if cls in _MALFORMED_CLASSES:
            malformed_distinct += 1
            malformed_rows += counts[token]
            malformed_by_class[cls] = malformed_by_class.get(cls, 0) + 1
            if len(examples) < 25:
                examples.append(token)
    return RegionPollutionCensus(
        total_rows=total_rows,
        distinct_regions=len(distinct),
        malformed_distinct=malformed_distinct,
        malformed_rows=malformed_rows,
        distinct_pollution_fraction=(malformed_distinct / len(distinct)) if distinct else 0.0,
        row_prevalence_fraction=(malformed_rows / total_rows) if total_rows else 0.0,
        malformed_by_class=malformed_by_class,
        malformed_examples=tuple(sorted(examples)),
    )


def region_cleanliness_gate(
    table: str,
    regions: Sequence[str],
    *,
    max_distinct_pollution: float = 0.02,
    max_row_prevalence: float = 0.02,
) -> list[GateRow]:
    """F033 region-cleanliness gate as value-census :class:`GateRow` findings.

    Calibrated on DISTINCT-VALUE POLLUTION (the fraction of distinct region tokens that are
    malformed) AND their row prevalence -- NEVER a ~50%-of-rows floor (which the 72,780-row re-census
    proved would never trip). Two hard findings:

      * distinct pollution above ``max_distinct_pollution`` (the axis carries malformed distinct
        tokens the producer must exclude);
      * malformed-row prevalence above ``max_row_prevalence`` (the malformed tokens are not a
        negligible tail -- a genuinely broken commodity/table_type subset, the open probe).

    A CLEAN silver output (produced by ``build_silver_frame``, which excludes malformed regions)
    returns an EMPTY list -- the gate is green precisely because the junk was quarantined, not
    published.
    """
    c = region_pollution_census(regions)
    rows: list[GateRow] = []
    if c.total_rows == 0:
        return rows
    if c.distinct_pollution_fraction > max_distinct_pollution:
        rows.append(GateRow(
            table, "region", KIND_REGION_POLLUTED, round(c.distinct_pollution_fraction, 4),
            max_distinct_pollution,
            f"{c.malformed_distinct}/{c.distinct_regions} distinct region tokens malformed "
            f"({c.malformed_by_class}); examples={list(c.malformed_examples[:6])}"))
    if c.row_prevalence_fraction > max_row_prevalence:
        rows.append(GateRow(
            table, "region", KIND_REGION_POLLUTED, round(c.row_prevalence_fraction, 4),
            max_row_prevalence,
            f"{c.malformed_rows}/{c.total_rows} rows carry a malformed region -- a broken "
            f"commodity/table_type subset, not the low-prevalence tail"))
    return rows


# ---------------------------------------------------------------------------
# F033 -- structural marketing-year / status / projection-month parse.
# ---------------------------------------------------------------------------
_MY_STATUS_RE = re.compile(
    r"^\s*(?P<my>\d{4}/\d{2,4})"
    r"(?:\s*\(?\s*(?P<status>Est(?:imated)?\.?|Proj(?:ected|ections?)?\.?)\s*\)?)?"
    r"(?:\s+(?P<month>January|February|March|April|May|June|July|August|September|October"
    r"|November|December))?"
    r"\s*$",
    re.IGNORECASE,
)


def estimate_role_from_status(status: str) -> str:
    """Map a source status marker to the estimate_role vocabulary. Empty status == a settled actual."""
    s = re.sub(r"[^a-z]", "", (status or "").lower())   # tolerate "(Est.)", "Proj." etc.
    if s.startswith("proj"):
        return ROLE_PROJECTION
    if s.startswith("est"):
        return ROLE_ESTIMATE
    return ROLE_ACTUAL


def parse_marketing_year_status(label: str) -> Optional[tuple[str, str, str]]:
    """Structurally parse a WASDE year label into ``(marketing_year, estimate_role, projection_month)``.

    Handles ``"2026/27"``, ``"2026/27 (Proj.)"``, ``"2008/09 (Est.)"``, ``"2026/27 (Proj.) May"``.
    Returns ``None`` when the label is NOT a marketing-year header -- so a bare month name
    (``"May"``) or a region (``"Argentina"``) returns ``None`` here and can never be mis-read as a
    marketing year (and, conversely, the month token inside a year header is captured as
    ``projection_month``, never leaked into ``region``).
    """
    m = _MY_STATUS_RE.match(label or "")
    if not m:
        return None
    my = normalize_marketing_year(m.group("my"))
    role = estimate_role_from_status(m.group("status") or "")
    month = m.group("month") or ""
    month = _MONTHS.get(month.lower(), "") if month else ""
    return my, role, month


def normalize_marketing_year(my: str) -> str:
    """Normalize a marketing-year string to ``YYYY/YY``. ``2009/2010`` -> ``2009/10``."""
    s = (my or "").strip()
    m = re.match(r"^(\d{4})/(\d{2,4})$", s)
    if not m:
        return s
    start, suffix = m.group(1), m.group(2)
    if len(suffix) == 4:
        suffix = suffix[2:]
    return f"{start}/{suffix}"


def marketing_year_end_year(marketing_year: str) -> Optional[int]:
    """The ending calendar year of a ``YYYY/YY`` marketing year (``2009/10`` -> 2010)."""
    m = re.match(r"^(\d{4})/(\d{2,4})$", (marketing_year or "").strip())
    if not m:
        return None
    start = int(m.group(1))
    suffix = m.group(2)
    if len(suffix) == 4:
        return int(suffix)
    end = (start // 100) * 100 + int(suffix)
    if end < start:
        end += 100
    return end


def marketing_year_end_date(commodity: str, marketing_year: str) -> Optional[date]:
    """The last calendar day of ``commodity``'s marketing year. ``None`` for an unsupported commodity
    (F034: NO universal June fallback -- the caller quarantines instead of imputing)."""
    month = MARKETING_YEAR_END_MONTH.get(commodity)
    end_year = marketing_year_end_year(marketing_year)
    if month is None or end_year is None:
        return None
    last_day = _calmod.monthrange(end_year, month)[1]
    return date(end_year, month, last_day)


def months_to_marketing_year_end(
    release_date: str, commodity: str, marketing_year: str,
) -> Optional[int]:
    """Whole months from a release date to the marketing-year end. ``None`` when unsupported (no
    calendar entry) or the release date is unparseable."""
    end = marketing_year_end_date(commodity, marketing_year)
    if end is None:
        return None
    rel = _parse_iso_date(release_date)
    if rel is None:
        return None
    return (end.year - rel.year) * 12 + (end.month - rel.month)


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat((s or "").strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# F033 -- stable source_table_id + commodity/table_type derivation.
# ---------------------------------------------------------------------------
def source_table_id(table_name: str) -> str:
    """A STABLE, deterministic id for a WASDE source table (its snake_case, footnote-stripped
    heading). Two runs over the same heading yield the same id; a bare month can never become one."""
    s = (table_name or "").strip()
    s = re.sub(r"\([^)]*\)", " ", s)                 # unit parenthetical
    s = re.sub(r"\b\d+/", " ", s)                    # footnote refs "1/", "2/" anywhere
    s = re.sub(r"\s*\d+\s*$", " ", s)                # trailing bare footnote digit
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def derive_commodity_table_type(table_name: str) -> Optional[tuple[str, str]]:
    """Derive ``(commodity, table_type)`` from a table heading. ``None`` when the heading matches no
    known commodity -- the caller quarantines (never guesses)."""
    low = (table_name or "").lower()
    commodity = None
    for pat, slug in _TABLE_COMMODITY_PATTERNS:
        if re.search(pat, low):
            commodity = slug
            break
    if commodity is None:
        return None
    if re.search(r"\bu\.?s\.?\b|united states", low):
        table_type = "us"
    elif re.search(r"\bworld\b", low):
        table_type = "world"
    else:
        table_type = "world"
    return commodity, table_type


# ---------------------------------------------------------------------------
# F034 -- conflict resolution (NO drop/keep-last).
# ---------------------------------------------------------------------------
def _natural_key_of(row: dict) -> tuple:
    return tuple(str(row.get(k, "")) for k in NATURAL_KEY)


def resolve_conflicts(rows: Sequence[dict]) -> list[dict]:
    """Collapse EXACT duplicates and RAISE on a divergent-value natural-key conflict.

    F034: "never resolve conflicting keys with drop/keep-last". Identical rows (same key AND same
    estimate) are deduplicated silently (a table repeated across two PDF pages); a key that appears
    with two DIFFERENT estimate values is a real ambiguity and raises :class:`WasdeKeyConflict`.
    """
    seen: dict[tuple, dict] = {}
    for row in rows:
        key = _natural_key_of(row)
        prior = seen.get(key)
        if prior is None:
            seen[key] = row
            continue
        if not _same_estimate(prior.get("estimate"), row.get("estimate")):
            raise WasdeKeyConflict(
                f"natural key {key} carries divergent estimates "
                f"{prior.get('estimate')!r} vs {row.get('estimate')!r} "
                "(F034: drop/keep-last is forbidden -- quarantine or fix the parse)")
    return list(seen.values())


def _same_estimate(a: Any, b: Any) -> bool:
    an, bn = (a is None or _is_nan(a)), (b is None or _is_nan(b))
    if an and bn:
        return True
    if an != bn:
        return False
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


def _is_nan(v: Any) -> bool:
    return isinstance(v, float) and v != v


# ---------------------------------------------------------------------------
# F034 -- revisions within a stable logical series.
# ---------------------------------------------------------------------------
@dataclass
class SeriesState:
    """The carried state of one revision series across releases (F034 release-sequence + gap)."""

    release_date: str
    estimate: Optional[float]
    sequence: int


def _series_key_of(row: dict) -> tuple:
    return tuple(str(row.get(k, "")) for k in REVISION_SERIES_KEY)


def compute_revisions(
    rows: Sequence[dict],
    prior_series_state: Optional[dict[tuple, SeriesState]] = None,
) -> dict[tuple, SeriesState]:
    """Fill the revision columns of ``rows`` IN PLACE from the carried ``prior_series_state`` and
    return the UPDATED state (so releases can be threaded in order, or an older release replayed to
    recompute only its own series).

    Sets: ``prior_release_date``, ``prior_estimate``, ``revision``, ``revision_direction``,
    ``release_sequence``, ``revision_gap_days``, ``is_first_estimate``. Revisions are computed ONLY
    within a :data:`REVISION_SERIES_KEY` series -- never across regions/attributes/commodities.
    """
    state: dict[tuple, SeriesState] = dict(prior_series_state or {})
    for row in rows:
        skey = _series_key_of(row)
        prior = state.get(skey)
        est = row.get("estimate")
        if prior is None:
            row["prior_release_date"] = None
            row["prior_estimate"] = None
            row["revision"] = None
            row["revision_direction"] = None
            row["revision_gap_days"] = None
            row["release_sequence"] = 1
            row["is_first_estimate"] = True
        else:
            row["prior_release_date"] = prior.release_date
            row["prior_estimate"] = prior.estimate
            row["release_sequence"] = prior.sequence + 1
            row["is_first_estimate"] = False
            row["revision_gap_days"] = _days_between(prior.release_date, row.get("release_date"))
            rev = _revision(prior.estimate, est)
            row["revision"] = rev
            row["revision_direction"] = _direction(rev)
        state[skey] = SeriesState(
            release_date=str(row.get("release_date")),
            estimate=(None if (est is None or _is_nan(est)) else float(est)),
            sequence=row["release_sequence"],
        )
    return state


def _revision(prior: Any, cur: Any) -> Optional[float]:
    if prior is None or cur is None or _is_nan(prior) or _is_nan(cur):
        return None
    return round(float(cur) - float(prior), 10)


def _direction(rev: Optional[float]) -> Optional[str]:
    if rev is None:
        return None
    if rev > 0:
        return "up"
    if rev < 0:
        return "down"
    return "unchanged"


def _days_between(a: str, b: str) -> Optional[int]:
    da, db = _parse_iso_date(a), _parse_iso_date(b)
    if da is None or db is None:
        return None
    return (db - da).days


# ---------------------------------------------------------------------------
# F034 -- the build.
# ---------------------------------------------------------------------------
@dataclass
class QuarantineRecord:
    reason: str
    detail: str
    raw: dict


@dataclass
class SilverBuildResult:
    """The output of :func:`build_silver_frame`: publishable rows + the quarantine ledger + the
    region gate + the region census, plus the carried series state for the next release."""

    rows: list[dict]
    quarantined: list[QuarantineRecord]
    region_gate: list[GateRow]
    region_census: RegionPollutionCensus
    series_state: dict[tuple, SeriesState]
    release_date: str

    @property
    def ok(self) -> bool:
        return not self.region_gate

    def to_summary(self) -> dict[str, Any]:
        by_reason: dict[str, int] = {}
        for q in self.quarantined:
            by_reason[q.reason] = by_reason.get(q.reason, 0) + 1
        return {
            "release_date": self.release_date,
            "silver_rows": len(self.rows),
            "quarantined_rows": len(self.quarantined),
            "quarantined_by_reason": by_reason,
            "region_gate_green": self.ok,
            "region_gate_findings": [g.to_dict() for g in self.region_gate],
            "region_census": self.region_census.to_dict(),
        }


def build_silver_frame(
    bronze_rows: Iterable[dict],
    *,
    prior_series_state: Optional[dict[tuple, SeriesState]] = None,
    source: str = _SOURCE,
    region_max_distinct_pollution: float = 0.02,
    region_max_row_prevalence: float = 0.02,
) -> SilverBuildResult:
    """Transform one release's bronze long rows into silver rows (F033 + F034).

    Steps:
      1. derive commodity/table_type + source_table_id (quarantine unmatched headings);
      2. parse marketing-year / estimate_role / projection_month structurally (a bare month never
         becomes a region);
      3. classify the region and QUARANTINE malformed tokens (they never reach silver);
      4. normalize the attribute to the 19-term vocabulary (quarantine anything else, INV-1);
      5. compute the marketing-year calendar fields (quarantine an unsupported commodity, no June
         fallback);
      6. reject drop/keep-last conflicts (:func:`resolve_conflicts`);
      7. mark the single deterministic current-release estimate per group + is_source_final;
      8. compute revisions within the stable logical series;
      9. run the region-cleanliness gate over the RAW regions of the release (audit signal).

    ``is_final_or_latest`` is set to ``None`` (deprecated, F036) -- latest state is
    :func:`latest_state_view`, not a row flag.
    """
    bronze_rows = list(bronze_rows)
    quarantined: list[QuarantineRecord] = []
    staged: list[dict] = []
    release_date = ""
    raw_regions: list[str] = []

    for br in bronze_rows:
        release_date = release_date or str(br.get("release_date", ""))
        raw_regions.append(str(br.get("region", "")))
        rec = _stage_one(br, source=source)
        if isinstance(rec, QuarantineRecord):
            quarantined.append(rec)
        else:
            staged.append(rec)

    # F034: conflicting keys fail rather than keep-last.
    staged = resolve_conflicts(staged)

    # mark the deterministic current-release estimate per (source_table_id, commodity, region,
    # attribute): the row for the latest marketing year in this release.
    _mark_current_release_estimate(staged)

    # revisions within the stable logical series.
    series_state = compute_revisions(staged, prior_series_state)

    # order the columns + fill any missing keys deterministically.
    rows = [_finalize_row(r) for r in staged]

    # The region_census is an AUDIT metric over the RAW input regions (how much junk the parse
    # produced). The GATE runs over the PUBLISHED silver axis (the region values that actually reach
    # the table): it is green because the malformed tokens were quarantined, not published -- this is
    # the F033 value-census acceptance ("region-junk fraction below floor in the value census").
    census = region_pollution_census(raw_regions)
    gate = region_cleanliness_gate(
        "silver_wasde", [str(r["region"]) for r in rows],
        max_distinct_pollution=region_max_distinct_pollution,
        max_row_prevalence=region_max_row_prevalence,
    )
    return SilverBuildResult(
        rows=rows, quarantined=quarantined, region_gate=gate, region_census=census,
        series_state=series_state, release_date=release_date,
    )


def _stage_one(br: dict, *, source: str):
    """Map ONE bronze row to a staged silver row, or a :class:`QuarantineRecord`."""
    table_name = str(br.get("table_name", ""))
    ct = derive_commodity_table_type(table_name)
    if ct is None:
        return QuarantineRecord("unmapped_commodity", f"heading {table_name!r}", dict(br))
    commodity, table_type = ct

    raw_region = str(br.get("region", ""))
    region_class = classify_region(raw_region)
    if region_class != REGION_CLEAN:
        return QuarantineRecord("malformed_region", f"{raw_region!r} classed {region_class}", dict(br))
    region = normalize_region(raw_region)

    raw_attr = str(br.get("attribute", ""))
    attribute = normalize_attribute(raw_attr)
    if attribute is None:
        return QuarantineRecord("unknown_attribute", f"{raw_attr!r} not in the 19-term vocab", dict(br))

    marketing_year = normalize_marketing_year(str(br.get("market_year", "")))
    if not re.match(r"^\d{4}/\d{2}$", marketing_year):
        return QuarantineRecord("bad_marketing_year", f"{br.get('market_year')!r}", dict(br))

    status = str(br.get("status", ""))
    role = estimate_role_from_status(status)
    proj_month = _norm_month(str(br.get("projection_month", "")))

    my_end = marketing_year_end_date(commodity, marketing_year)
    if my_end is None:
        return QuarantineRecord(
            "unsupported_calendar",
            f"commodity {commodity!r} has no marketing-year calendar (no June fallback)", dict(br))
    release_date = str(br.get("release_date", ""))
    m2e = months_to_marketing_year_end(release_date, commodity, marketing_year)

    return {
        "release_date": release_date,
        "commodity": commodity,
        "table_type": table_type,
        "region": region,
        "marketing_year": marketing_year,
        "attribute": attribute,
        "unit": _blank_to_none(br.get("unit")),
        "estimate": _to_float(br.get("value")),
        "months_to_marketing_year_end": m2e,
        "is_final_or_latest": None,               # DEPRECATED (F036): never re-computed
        "raw_table_name": table_name,
        "raw_region": raw_region,
        "raw_attribute": raw_attr,
        "raw_status": status or None,
        "raw_projection_month": _blank_to_none(br.get("projection_month")),
        "source": source,
        # F036 additive
        "source_table_id": source_table_id(table_name),
        "estimate_role": role,
        "projection_month": proj_month or "",
        "is_projection": role == ROLE_PROJECTION,
        "is_source_final": True if role == ROLE_ACTUAL else None,
        "marketing_year_end_date": my_end.isoformat(),
        # placeholders filled downstream
        "is_current_release_estimate": False,
        "prior_release_date": None,
        "prior_estimate": None,
        "revision": None,
        "revision_direction": None,
        "revision_gap_days": None,
        "release_sequence": 1,
        "is_first_estimate": True,
    }


def _mark_current_release_estimate(rows: Sequence[dict]) -> None:
    """Mark ONE deterministic current-release estimate per (source_table_id, commodity, region,
    attribute) group: the row for the latest marketing year in the release (F034). Comparison rows
    (prior-year Est./Actual) are RETAINED, not discarded -- only the flag distinguishes them."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        gk = (r["source_table_id"], r["commodity"], r["region"], r["attribute"])
        groups.setdefault(gk, []).append(r)
    for members in groups.values():
        current = max(members, key=lambda r: r["marketing_year"])
        for r in members:
            r["is_current_release_estimate"] = (r is current)


def normalize_attribute(raw: str) -> Optional[str]:
    """Map a raw attribute label to a canonical 19-term attribute, or ``None`` (quarantine)."""
    key = (raw or "").strip().lower().rstrip(".")
    key = re.sub(r"\s*\d+/\s*", " ", key)            # strip footnote refs "2/"
    key = re.sub(r"\s+", " ", key).strip()
    if key in WASDE_ATTRIBUTES:
        return key
    if key in _ATTRIBUTE_ALIASES:
        return _ATTRIBUTE_ALIASES[key]
    snake = key.replace(" ", "_").replace("/", "_").replace(",", "")
    if snake in WASDE_ATTRIBUTES:
        return snake
    return None


def _finalize_row(row: dict) -> dict:
    return {c: row.get(c) for c in (PARTITION_KEY,) + SILVER_COLUMNS}


def _norm_month(m: str) -> str:
    return _MONTHS.get((m or "").strip().lower(), "")


def _blank_to_none(v: Any) -> Optional[str]:
    s = ("" if v is None else str(v)).strip()
    return s or None


def _to_float(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


# ---------------------------------------------------------------------------
# F034 -- latest-state view (replaces the deprecated is_final_or_latest row flag).
# ---------------------------------------------------------------------------
def latest_state_view(rows: Sequence[dict]) -> list[dict]:
    """Derive latest state by RELEASE DATE rather than a timeless row flag (F036 compatibility).

    For each natural-key-minus-release-date series, return the row from the LATEST release_date. This
    is the query/view a consumer that used ``is_final_or_latest`` adopts instead."""
    latest: dict[tuple, dict] = {}
    for r in rows:
        key = tuple(str(r.get(k, "")) for k in NATURAL_KEY if k != "release_date")
        cur = latest.get(key)
        if cur is None or str(r.get("release_date", "")) > str(cur.get("release_date", "")):
            latest[key] = r
    return list(latest.values())


# ---------------------------------------------------------------------------
# F036 (INV-2) -- explicit writer arrow schema from the registry contract.
# ---------------------------------------------------------------------------
def arrow_schema_from_contract(contract: dict) -> "pa.Schema":
    """Build the explicit ``pyarrow`` writer schema (INV-2) from a SILVER-F010 registry contract.

    Uses each column's ``target_arrow_type`` (the widen-migration target), in the registry column
    order, PLUS the partition key column (silver parquet carries release_date in-file). NO first-file
    inference -- the schema is the contract."""
    import pyarrow as pa

    builders = {
        "int64": pa.int64, "float64": pa.float64, "string": pa.string,
        "bool": pa.bool_, "date32[day]": pa.date32,
    }
    fields = []
    for pk in contract.get("partition_keys", []):
        fields.append(pa.field(pk["name"], pa.string(), nullable=True))
    for col in contract.get("physical_columns", []):
        target = col.get("target_arrow_type", "string")
        maker = builders.get(target, pa.string)
        fields.append(pa.field(col["name"], maker(), nullable=bool(col.get("nullable", True))))
    return pa.schema(fields)


def to_arrow_table(rows: Sequence[dict], contract: dict) -> "pa.Table":
    """Cast staged silver rows to the explicit contract schema (INV-2). Coerces the boolean/int/float
    columns and leaves date-like columns as ISO strings (the contract types them string)."""
    import pyarrow as pa

    schema = arrow_schema_from_contract(contract)
    columns: dict[str, list] = {f.name: [] for f in schema}
    for r in rows:
        for f in schema:
            columns[f.name].append(_coerce_for(f, r.get(f.name)))
    arrays = []
    for f in schema:
        arrays.append(pa.array(columns[f.name], type=f.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def _coerce_for(field_obj, value):
    import pyarrow as pa

    t = field_obj.type
    if value is None:
        return None
    if pa.types.is_boolean(t):
        return bool(value)
    if pa.types.is_integer(t):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if pa.types.is_floating(t):
        f = _to_float(value)
        return f
    return str(value)
