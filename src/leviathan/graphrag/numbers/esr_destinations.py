"""FAS ESR destination code<->name reference loader (ESR_DESTINATION_PLAN W0).

Reads ``configs/graphrag/numbers/esr_destinations.yaml`` into the two str-normalized maps the numbers
query builder needs to turn ``country='China'`` into a destination-scoped ESR read:

  * ``name_to_codes`` : normalized alias -> [str country codes]   (name -> ``country_code`` IN filter)
  * ``code_to_name``  : str country code -> display name          (post-fetch row label render)

WHY STR-KEYED (ESR_DESTINATION_PLAN 3.3, folded skeptic finding S2). The row's ``country_code`` comes
back as a STRING on BOTH backends -- Athena renders every cell ``VarCharValue`` and the pg mirror
``_stringify``-es its TEXT column -- while the YAML keys codes as YAML integers. A lookup keyed on the
raw int would miss on both. Both maps therefore normalize every code to ``str`` at load, the SAME
discipline the ``CAST(country_code AS varchar) IN (...)`` filter uses on the SQL side, so ``'1220'`` and
``1220`` collapse. Loaded once (lru_cached), like the registry.

CONSUMPTION CONTRACT for the integrator's query.py edits (this module owns none of query.py):
  * name->code (build_sql):  ``resolve_codes(spec.country)`` -> quote each str code into
    ``CAST(country_col AS varchar) IN ('...')``. An EMPTY list means UNRESOLVED -> the caller MUST
    fail CLOSED (force zero rows), never emit a silent national total (the July name-vs-code lesson).
  * code->name (post-fetch):  ``display(row['country_code'])`` -> the label, str-normalized, with a
    bare-code fallback (never raises); the reference-lint makes a probe-present-but-unmapped code a
    hard failure so the fallback only ever fires on genuinely unknown codes.
  * ``is_pseudo(code)`` / ``kind(code)`` gate the aggregate/unknown honesty behavior (a pseudo code is
    never a single-COUNTRY name target; a bloc ask gets a caveat -- ESR_DESTINATION_PLAN 4.3).
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict

from leviathan.graphrag import extract as ex  # ex._CFG -> configs/graphrag

_DEFAULT_REL = ("numbers", "esr_destinations.yaml")

Kind = Literal["country", "territory", "former", "bloc", "region_nec", "unknown"]


class _Entry(BaseModel):
    # extra="forbid": a typoed key must fail at load, not silently disarm the pseudo/alias contract
    # (mirrors registry.Metric / TableSpec discipline).
    model_config = ConfigDict(extra="forbid")
    name: str
    aliases: list[str] = []
    pseudo: bool = False
    kind: Kind = "country"


class _Ref(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    source: str = ""
    source_endpoint: str = ""
    fetched: str = ""
    reference_row_count: int = 0
    audit: dict = {}
    codes: dict[int, _Entry]


def _norm(name: str) -> str:
    """Alias/name normalizer: lowercase, strip, collapse internal whitespace. The same normal form is
    applied to the YAML aliases at load and to the model's ``spec.country`` at resolve time."""
    return re.sub(r"\s+", " ", (name or "").strip().lower())


@dataclass(frozen=True)
class EsrDestinations:
    name_to_codes: dict[str, list[str]]        # normalized alias -> [str codes] (usually 1)
    code_to_name: dict[str, str]               # str code -> display name
    pseudo_codes: frozenset[str]               # str codes flagged pseudo (bloc/region_nec/unknown)
    kind_by_code: dict[str, str]               # str code -> kind
    bloc_watch_codes: tuple[str, ...] = ()     # audit: blocs to exclude from the national sum ONLY if
    #                                            a future vintage makes one additive with its members
    national_exclusion_codes: tuple[str, ...] = ()  # audit: codes the national agg=sum MUST exclude
    #                                            today (empty = W2.2 found no double-count)

    def resolve_codes(self, name: Optional[str]) -> list[str]:
        """Normalized destination name -> sorted list of str country codes. EMPTY when unresolved
        (caller fails closed) or when ``name`` is falsy (national path, no destination filter)."""
        if not name:
            return []
        return list(self.name_to_codes.get(_norm(name), []))

    def display(self, code) -> str:
        """str-normalized code -> display name; bare-code string fallback (never raises)."""
        return self.code_to_name.get(str(code), str(code))

    def is_pseudo(self, code) -> bool:
        return str(code) in self.pseudo_codes

    def kind(self, code) -> Optional[str]:
        return self.kind_by_code.get(str(code))


def _ref_path(path: Optional[str]) -> Path:
    return Path(path) if path else (ex._CFG.joinpath(*_DEFAULT_REL))


@functools.lru_cache(maxsize=4)
def load_esr_destinations(path: Optional[str] = None) -> EsrDestinations:
    p = _ref_path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    ref = _Ref(**raw)
    name_to_codes: dict[str, list[str]] = {}
    code_to_name: dict[str, str] = {}
    kind_by_code: dict[str, str] = {}
    pseudo: set[str] = set()
    for code_int, e in ref.codes.items():
        sc = str(code_int)
        code_to_name[sc] = e.name
        kind_by_code[sc] = e.kind
        if e.pseudo:
            pseudo.add(sc)
        for a in e.aliases:
            name_to_codes.setdefault(_norm(a), []).append(sc)
    # deterministic order for the (rare) multi-code alias, and for stable SQL IN-lists
    for a in name_to_codes:
        name_to_codes[a] = sorted(set(name_to_codes[a]), key=lambda c: int(c))
    audit = ref.audit or {}
    return EsrDestinations(
        name_to_codes=name_to_codes,
        code_to_name=code_to_name,
        pseudo_codes=frozenset(pseudo),
        kind_by_code=kind_by_code,
        bloc_watch_codes=tuple(str(c) for c in audit.get("bloc_watch_codes", [])),
        national_exclusion_codes=tuple(str(c) for c in audit.get("national_exclusion_required", [])),
    )


def lint_reference(path: Optional[str] = None) -> list[str]:
    """AWS-free structural + cross-seed lint (ESR_DESTINATION_PLAN 5.1). Returns a list of problems;
    empty == clean. Intended to be called by a thin config_check wrapper (the integrator's gate).

    Checks: (1) the file parses under the strict ``extra='forbid'`` schema; (2) every alias is globally
    UNIQUE (no alias maps to two codes); (3) every display name in ``agent._ESR_DESTINATIONS`` resolves
    to a code (the guard vocabulary is fully served); (4) pseudo<->kind consistency."""
    problems: list[str] = []
    p = _ref_path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        ref = _Ref(**raw)
    except Exception as exc:  # noqa: BLE001 -- surfaced as a lint problem, not a crash
        return [f"esr_destinations.yaml failed strict-schema parse: {exc}"]

    # (2) global alias uniqueness
    seen: dict[str, int] = {}
    for code_int, e in ref.codes.items():
        for a in e.aliases:
            na = _norm(a)
            if na in seen and seen[na] != code_int:
                problems.append(f"alias {a!r} maps to BOTH code {seen[na]} and {code_int}")
            seen[na] = code_int
    # (4) pseudo<->kind consistency
    pseudo_kinds = {"bloc", "region_nec", "unknown"}
    for code_int, e in ref.codes.items():
        if e.pseudo and e.kind not in pseudo_kinds:
            problems.append(f"code {code_int} pseudo=true but kind={e.kind!r} (expected one of {sorted(pseudo_kinds)})")
        if (not e.pseudo) and e.kind in pseudo_kinds:
            problems.append(f"code {code_int} kind={e.kind!r} implies pseudo=true but pseudo=false")

    # (3) every guard destination display resolves (cross-seed integrity)
    dst = load_esr_destinations(str(p))
    try:
        from leviathan.graphrag.numbers.agent import _ESR_DESTINATIONS
    except Exception as exc:  # noqa: BLE001
        problems.append(f"could not import guard _ESR_DESTINATIONS for cross-seed check: {exc}")
        return problems
    for disp, names, dems in _ESR_DESTINATIONS:
        forms = [disp] + list(names) + list(dems)
        if not any(dst.resolve_codes(f) for f in forms):
            problems.append(f"guard destination {disp!r} resolves to NO code in esr_destinations.yaml")
    return problems


def missing_codes(data_codes, path: Optional[str] = None) -> list[str]:
    """Codes present in the DATA (the W0.2 / W2.2 S3 probe) but absent from the reference. A non-empty
    result is a coverage gap the §5.1 lint treats as a HARD failure (an unmapped code would render as a
    bare int). Kept separate from ``lint_reference`` because it needs the S3-probed code set, not just
    the YAML."""
    dst = load_esr_destinations(path)
    return sorted({str(c) for c in data_codes} - set(dst.code_to_name), key=lambda c: int(c))
