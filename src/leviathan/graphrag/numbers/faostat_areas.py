"""FAOSTAT QCL area-surface reference loader (D-EC projection wave FAO-3).

Reads ``configs/graphrag/numbers/faostat_areas.yaml`` into the two str maps the numbers query builder
needs to turn ``country='United States'`` into a real read of ``silver_production``:

  * ``name_to_areas``  : normalized alias -> [raw FAOSTAT area strings]  (name -> ``country`` IN filter)
  * ``area_to_display``: raw area string -> display label                (post-fetch row label render)

WHY IT EXISTS. ``silver_production.country`` holds FAOSTAT's RAW M49 DISPLAY STRINGS, not a governed
estate name and not a code: ``'United States of America'``, ``'Russian Federation'``, ``'Viet Nam'``,
``'Türkiye'``, ``"Côte d'Ivoire"``, ``'China, mainland'``. ``query.build_sql`` emits ``country = 'X'``
verbatim, so a ``country='United States'`` ask compiled clean SQL and returned ZERO rows, silently,
against a table that holds the series -- the July name-vs-code failure class on a different surface.
``country_key`` is no better: ``faostat_production.standardize_country_name`` strips accents, spaces,
hyphens, apostrophes and parens but NOT commas, so the governed key for China's mainland row ships as
``'china,_mainland'``.

THE AGGREGATE LADDER IS PART OF THE CONTRACT, NOT DECORATION. 34 of the 244 areas are aggregates that
sit in the SAME column as their members -- World, the five continents and their sub-regions, European
Union (27), and the LDC / LLDC / SIDS / LIFDC / NFIDC country groups -- plus one aggregate that hides
BELOW the 5000 aggregate-code band: bare ``'China'`` (area code 351) is mainland + Hong Kong SAR +
Macao SAR + Taiwan Province of. That last one is MEASURED, not assumed -- as a ROUNDING roll-up, not
an exact float identity: on the 2026-05-11 QCL ZIP, across 13,771 comparable Production (Item, Year)
cells the four members sum to the 351 row within 1e-6 relative on 13,738 (max residual 0.02 t, FAO's
own printed rounding). Any sum over this column
that does not exclude the aggregates double-counts, and ``'China'`` is the trap a reader is most
likely to walk into, which is why the alias ``china`` resolves to ``'China, mainland'`` and the bare
aggregate is reachable only under an explicit aggregate alias.

CONSUMPTION CONTRACT (``query._country_ref`` dispatches on ``TableSpec.country_name_ref``; this module
owns none of query.py). The method NAMES are :mod:`esr_destinations`'s, verbatim, because the query
builder consumes ONE protocol across both surfaces -- a FAOSTAT "code" is the raw area STRING, which is
exactly what the physical column stores:
  * name->area (build_sql):  ``resolve_codes(spec.country)`` -> quote each string into
    ``CAST(country_col AS varchar) IN (...)``. An EMPTY list means UNRESOLVED -> the caller MUST fail
    CLOSED (force zero rows), never widen to the world row.
  * area->label (post-fetch): ``display(row['country'])`` -> IDENTITY for every mapped area (FAOSTAT's
    own string is the honest label) with a bare-value fallback that never raises.
  * ``is_pseudo(area)`` / ``kind(area)`` gate the aggregate honesty behavior: a pseudo area is never a
    single-COUNTRY name target, and ``members(area)`` names what an aggregate is made of.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict

from leviathan.graphrag import extract as ex  # ex._CFG -> configs/graphrag

_DEFAULT_REL = ("numbers", "faostat_areas.yaml")

# world/continent/subregion/bloc/group/country_aggregate are the AGGREGATE kinds (pseudo:true);
# country and former are single reporting areas (pseudo:false). ``former`` is called out separately
# from ``country`` because a dissolved reporting area (USSR, Czechoslovakia, Sudan (former), ...) is a
# real single area whose series must never be summed with its successors -- the ESR reference draws
# the same line for the same reason.
Kind = Literal[
    "country", "former", "world", "continent", "subregion", "bloc", "group", "country_aggregate",
]

_AGGREGATE_KINDS: frozenset[str] = frozenset(
    {"world", "continent", "subregion", "bloc", "group", "country_aggregate"}
)


class _Entry(BaseModel):
    # extra="forbid": a typoed key must fail at load, not silently disarm the aggregate/alias contract
    # (mirrors registry.Metric / TableSpec / esr_destinations._Entry discipline).
    model_config = ConfigDict(extra="forbid")
    name: str                          # the RAW area string as the data column carries it
    m49: str = ""                      # M49 code, documentation only (the column stores no code)
    aliases: list[str] = []
    pseudo: bool = False
    kind: Kind = "country"
    members: list[int] = []            # aggregate composition, by FAOSTAT area code (China 351 only)


class _Ref(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    source: str = ""
    source_file: str = ""
    source_member: str = ""
    fetched: str = ""
    reference_row_count: int = 0
    audit: dict = {}
    areas: dict[int, _Entry]


def _norm(name: str) -> str:
    """Alias/name normalizer: lowercase, strip, collapse internal whitespace. The same normal form is
    applied to the YAML aliases at load and to the model's ``spec.country`` at resolve time."""
    return re.sub(r"\s+", " ", (name or "").strip().lower())


@dataclass(frozen=True)
class FaostatAreas:
    name_to_areas: dict[str, list[str]]        # normalized alias -> [raw area strings] (usually 1)
    area_to_display: dict[str, str]            # raw area string -> display label (identity today)
    pseudo_areas: frozenset[str]               # areas that are AGGREGATES, never a single country
    kind_by_area: dict[str, str]               # raw area string -> kind
    members_by_area: dict[str, tuple[str, ...]]  # aggregate -> its member area strings (declared only)
    code_by_area: dict[str, int]               # raw area string -> FAOSTAT area code (the STABLE id)

    def resolve_codes(self, name: Optional[str]) -> list[str]:
        """Normalized estate name -> sorted list of raw FAOSTAT area strings. EMPTY when unresolved
        (caller fails closed) or when ``name`` is falsy (no country filter)."""
        if not name:
            return []
        return list(self.name_to_areas.get(_norm(name), []))

    def display(self, area) -> str:
        """Raw area string -> display label; bare-value fallback (never raises)."""
        return self.area_to_display.get(str(area), str(area))

    def is_pseudo(self, area) -> bool:
        """True for a FAOSTAT AGGREGATE area (World / continent / sub-region / EU-27 / a country group
        / the bare 'China' four-way roll-up) -- never a legitimate single-country name target."""
        return str(area) in self.pseudo_areas

    def kind(self, area) -> Optional[str]:
        return self.kind_by_area.get(str(area))

    def members(self, area) -> tuple[str, ...]:
        """The member area strings an aggregate rolls up, where the reference declares them. EMPTY for
        every area whose composition this reference does not state -- an empty tuple is 'not declared',
        never 'has no members'."""
        return tuple(self.members_by_area.get(str(area), ()))

    def code(self, area) -> Optional[int]:
        """FAOSTAT area code for a raw area string -- the source's STABLE identity. The display string
        is the join key only because it is the one the physical column stores; a FAOSTAT rename would
        move the string and keep the code, which is what makes ``missing_areas`` a tripwire."""
        return self.code_by_area.get(str(area))


def _ref_path(path: Optional[str]) -> Path:
    return Path(path) if path else (ex._CFG.joinpath(*_DEFAULT_REL))


@functools.lru_cache(maxsize=4)
def load_faostat_areas(path: Optional[str] = None) -> FaostatAreas:
    p = _ref_path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    ref = _Ref(**raw)
    by_code: dict[int, str] = {c: e.name for c, e in ref.areas.items()}
    name_to_areas: dict[str, list[str]] = {}
    area_to_display: dict[str, str] = {}
    kind_by_area: dict[str, str] = {}
    code_by_area: dict[str, int] = {}
    members_by_area: dict[str, tuple[str, ...]] = {}
    pseudo: set[str] = set()
    for code, e in ref.areas.items():
        area_to_display[e.name] = e.name          # identity: FAOSTAT's own string IS the honest label
        kind_by_area[e.name] = e.kind
        code_by_area[e.name] = code
        if e.pseudo:
            pseudo.add(e.name)
        if e.members:
            members_by_area[e.name] = tuple(by_code[m] for m in e.members if m in by_code)
        for a in e.aliases:
            name_to_areas.setdefault(_norm(a), []).append(e.name)
    # deterministic order for the (rare) multi-area alias, and for stable SQL IN-lists
    for a in name_to_areas:
        name_to_areas[a] = sorted(set(name_to_areas[a]))
    return FaostatAreas(
        name_to_areas=name_to_areas,
        area_to_display=area_to_display,
        pseudo_areas=frozenset(pseudo),
        kind_by_area=kind_by_area,
        members_by_area=members_by_area,
        code_by_area=code_by_area,
    )


def lint_reference(path: Optional[str] = None) -> list[str]:
    """AWS-free structural lint. Returns a list of problems; empty == clean. Mirrors
    ``esr_destinations.lint_reference``: (1) the file parses under the strict ``extra='forbid'`` schema;
    (2) every alias is globally UNIQUE (no alias maps to two areas -- the 'china' collision between the
    mainland row and the four-way aggregate is exactly what this catches); (3) pseudo<->kind
    consistency; (4) every declared aggregate member resolves to a declared area."""
    problems: list[str] = []
    p = _ref_path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        ref = _Ref(**raw)
    except Exception as exc:  # noqa: BLE001 -- surfaced as a lint problem, not a crash
        return [f"faostat_areas.yaml failed strict-schema parse: {exc}"]

    # (2) global alias uniqueness
    seen: dict[str, int] = {}
    for code, e in ref.areas.items():
        for a in e.aliases:
            na = _norm(a)
            if na in seen and seen[na] != code:
                problems.append(f"alias {a!r} maps to BOTH area {seen[na]} and {code}")
            seen[na] = code
    # (3) pseudo<->kind consistency
    for code, e in ref.areas.items():
        if e.pseudo and e.kind not in _AGGREGATE_KINDS:
            problems.append(
                f"area {code} pseudo=true but kind={e.kind!r} (expected one of {sorted(_AGGREGATE_KINDS)})"
            )
        if (not e.pseudo) and e.kind in _AGGREGATE_KINDS:
            problems.append(f"area {code} kind={e.kind!r} implies pseudo=true but pseudo=false")
    # (4) aggregate members resolve, and only an aggregate declares them
    for code, e in ref.areas.items():
        if e.members and not e.pseudo:
            problems.append(f"area {code} declares members but is not an aggregate (pseudo=false)")
        for m in e.members:
            if m not in ref.areas:
                problems.append(f"area {code} declares member {m}, which is not a declared area")
    return problems


def missing_areas(data_areas, path: Optional[str] = None) -> list[str]:
    """Area strings present in the DATA but absent from the reference. A non-empty result is a coverage
    gap the lint treats as a HARD failure: an unmapped area is unreachable by name, and -- because the
    join key is the DISPLAY STRING and only the area CODE is stable -- it is also how a FAOSTAT rename
    announces itself. Kept separate from :func:`lint_reference` because it needs the probed area set."""
    ref = load_faostat_areas(path)
    return sorted({str(a) for a in data_areas} - set(ref.area_to_display))
