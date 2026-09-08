"""NASS state-code reference loader -- STATE ENGINE DESIGN sec 2.1 / 2.6 item 3, sitting S1.

Reads ``configs/graphrag/numbers/nass_states.yaml`` (landed inert at S0) into the maps
``query.build_sql`` needs to turn ``country='United States'`` into a real read of
``silver_nass_crop_progress``:

  * ``name_to_codes`` : normalized alias -> [USPS codes]   (name -> ``country_col`` IN filter)
  * ``code_to_display``: USPS code -> display name         (post-fetch row label render)

WHY IT EXISTS. ``silver_nass_crop_progress`` declares ``country_col: state`` -- a 2-letter USPS code,
with ``'US'`` as USDA NASS's own national roll-up -- while every other geo axis in the estate speaks
country NAMES: ``cascade._scope_ex`` resolves a driver's region token through ``region_map`` to a
country name (``'US_Midwest'`` -> ``'United States'``), and the numbers agent types a name. A name
against a USPS column matches ZERO rows, silently -- the July name-vs-code failure class, which
``esr_destinations`` closes for FAS destination codes and ``faostat_areas`` closes for M49 display
strings. This is the third surface and it is the same mechanism.

CONSUMPTION CONTRACT (``query._country_ref`` dispatches on ``TableSpec.country_name_ref``; this module
owns none of query.py). The method NAMES are :mod:`esr_destinations`'s, verbatim, because the query
builder consumes ONE protocol across all three surfaces:
  * name->code (build_sql):  ``resolve_codes(spec.country)`` -> quoted into
    ``CAST(state AS varchar) IN ('IA')``. An EMPTY list means UNRESOLVED and the caller fails CLOSED
    (an IN list matching zero rows), never a silent national total -- which on THIS card would be the
    worst of the three, because a wrong roll-up here reads as a plausible national crop condition.
  * code->label (post-fetch): ``display('IA')`` -> ``'Iowa'``, with a bare-value fallback that never
    raises. Unlike FAOSTAT's identity render, this one is a REAL translation: 'IA' is not a label a
    reader should be handed.
  * ``is_pseudo(code)`` / ``kind(code)``: ``'US'`` is the one PSEUDO entry -- the national roll-up sits
    in the SAME column as its members, exactly as FAOSTAT's aggregates do, so summing this column
    without excluding it double-counts the whole country. ``kind`` is ``{state, national}``.

TWO DIFFERENCES FROM THE ESR MODEL, both from the reference file's own S0 note: the codes are keyed by
STRING (a USPS code), not by int; and ``kind`` is a two-value enum of this surface's own, not the ESR
Kind enum. Every key in the YAML is QUOTED so no code is resolved as a YAML 1.1 boolean.

COVERAGE IS DECLARED, NOT PROBED (S0's note, carried forward as a fact rather than repaired here): the
reference names all 50 states plus DC plus the national roll-up; WHICH of them the card's data holds
needs a live read of the mirror, and the card does not yet declare ``country_name_ref`` at all, so
nothing dispatches here on the serve path today. A code present here but absent from the data resolves
to a real IN filter that returns zero rows -- an honest empty read, never a wrong figure.
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

_DEFAULT_REL = ("numbers", "nass_states.yaml")

#: ``national`` is the AGGREGATE kind (pseudo:true); ``state`` is a single reporting geography.
#: Two values, and the split exists for the same reason FAOSTAT's does: an aggregate sharing a column
#: with its members is the double-count trap, and naming it is what lets a consumer refuse to sum it.
Kind = Literal["state", "national"]

_AGGREGATE_KINDS: frozenset[str] = frozenset({"national"})


class _Entry(BaseModel):
    # extra="forbid": a typoed key must fail at load, not silently disarm the alias/aggregate contract
    # (mirrors registry.Metric / TableSpec / esr_destinations._Entry / faostat_areas._Entry discipline).
    model_config = ConfigDict(extra="forbid")
    name: str                          # the display name ('Iowa', 'United States')
    aliases: list[str] = []
    pseudo: bool = False
    kind: Kind = "state"


class _Ref(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    source: str = ""
    source_endpoint: Optional[str] = None
    fetched: Optional[str] = None
    reference_row_count: int = 0
    audit: dict = {}
    codes: dict[str, _Entry]


def _norm(name: str) -> str:
    """Alias/name normalizer: lowercase, strip, collapse internal whitespace -- the SAME normal form
    ``faostat_areas`` uses, applied to the YAML aliases at load and to ``spec.country`` at resolve."""
    return re.sub(r"\s+", " ", (name or "").strip().lower())


@dataclass(frozen=True)
class NassStates:
    name_to_codes: dict[str, list[str]]        # normalized alias -> [USPS codes] (always 1 today)
    code_to_display: dict[str, str]            # USPS code -> display name ('IA' -> 'Iowa')
    pseudo_codes: frozenset[str]               # the national roll-up; never a single-state target
    kind_by_code: dict[str, str]               # USPS code -> kind

    def resolve_codes(self, name: Optional[str]) -> list[str]:
        """Normalized estate name -> sorted list of USPS codes. EMPTY when unresolved (the caller fails
        CLOSED) or when ``name`` is falsy (no country filter at all)."""
        if not name:
            return []
        return list(self.name_to_codes.get(_norm(name), []))

    def display(self, code) -> str:
        """USPS code -> display name; bare-value fallback (never raises), so an unmapped code renders as
        itself rather than breaking an answer."""
        return self.code_to_display.get(str(code), str(code))

    def is_pseudo(self, code) -> bool:
        """True for the NATIONAL roll-up, which sits in the same column as its member states -- never a
        legitimate single-state name target and never a member of a sum over this column."""
        return str(code) in self.pseudo_codes

    def kind(self, code) -> Optional[str]:
        return self.kind_by_code.get(str(code))


def _ref_path(path: Optional[str]) -> Path:
    return Path(path) if path else (ex._CFG.joinpath(*_DEFAULT_REL))


@functools.lru_cache(maxsize=4)
def load_nass_states(path: Optional[str] = None) -> NassStates:
    p = _ref_path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    ref = _Ref(**raw)
    name_to_codes: dict[str, list[str]] = {}
    code_to_display: dict[str, str] = {}
    kind_by_code: dict[str, str] = {}
    pseudo: set[str] = set()
    for code, e in ref.codes.items():
        c = str(code)
        code_to_display[c] = e.name
        kind_by_code[c] = e.kind
        if e.pseudo:
            pseudo.add(c)
        for a in list(e.aliases) + [e.name]:            # the display NAME is always resolvable by itself
            name_to_codes.setdefault(_norm(a), []).append(c)
    for a in name_to_codes:                             # deterministic order for stable SQL IN-lists
        name_to_codes[a] = sorted(set(name_to_codes[a]))
    return NassStates(
        name_to_codes=name_to_codes,
        code_to_display=code_to_display,
        pseudo_codes=frozenset(pseudo),
        kind_by_code=kind_by_code,
    )


def lint_reference(path: Optional[str] = None) -> list[str]:
    """AWS-free structural lint. Returns a list of problems; empty == clean. Mirrors
    ``faostat_areas.lint_reference`` clause for clause: (1) the file parses under the strict
    ``extra='forbid'`` schema; (2) every alias is globally UNIQUE -- an alias resolving to two codes
    would emit a two-value IN list and mix two geographies into one series, which is the W0-7 class;
    (3) pseudo<->kind consistency; (4) every code is a plausible USPS token (2 upper-case letters), so a
    lower-cased or padded key cannot silently fail to match a column that stores the canonical form."""
    problems: list[str] = []
    p = _ref_path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        ref = _Ref(**raw)
    except Exception as exc:  # noqa: BLE001 -- surfaced as a lint problem, not a crash
        return [f"nass_states.yaml failed strict-schema parse: {exc}"]

    seen: dict[str, str] = {}                                   # (2) global alias uniqueness
    for code, e in ref.codes.items():
        for a in list(e.aliases) + [e.name]:
            na = _norm(a)
            if na in seen and seen[na] != str(code):
                problems.append(f"alias {a!r} maps to BOTH code {seen[na]} and {code}")
            seen[na] = str(code)
    for code, e in ref.codes.items():                           # (3) pseudo <-> kind
        if e.pseudo and e.kind not in _AGGREGATE_KINDS:
            problems.append(
                f"code {code} pseudo=true but kind={e.kind!r} (expected one of {sorted(_AGGREGATE_KINDS)})")
        if (not e.pseudo) and e.kind in _AGGREGATE_KINDS:
            problems.append(f"code {code} kind={e.kind!r} implies pseudo=true but pseudo=false")
    for code in ref.codes:                                      # (4) the token shape
        if not re.fullmatch(r"[A-Z]{2}", str(code)):
            problems.append(f"code {code!r} is not a 2-letter upper-case USPS token")
    return problems


def missing_codes(data_codes, path: Optional[str] = None) -> list[str]:
    """Codes present in the DATA but absent from the reference. A non-empty result is a coverage gap:
    an unmapped code is unreachable by name. Kept separate from :func:`lint_reference` because it needs
    the probed code set -- the live ``country='US'`` probe S0 parked is this function's input."""
    ref = load_nass_states(path)
    return sorted({str(c) for c in data_codes} - set(ref.code_to_display))
