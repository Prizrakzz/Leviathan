"""LANE A / A-1 -- VENUE NO-SETTLEMENT CALENDARS for the databento silver session floor.

WHAT THIS READS. ``configs/silver/venue_holidays.yaml``: per DATASET (the tokens the fetch and
silver legs already use -- GLBX.MDP3, IFUS.IMPACT, IFEU.IMPACT), the trade dates on which that
dataset published NO daily bar for the roots this leg buys. It is NOT a bank-holiday list and NOT
a trading-hours calendar: a venue that trades a shortened session and still settles is not listed.

WHY IT EXISTS, MEASURED FROM THE BANKED FIRES. ``futures_eod_task._session_floor_facts`` counts
expected sessions off ``pd.bdate_range`` -- freq ``B``, Mon-Fri, no holiday awareness. Two fires
are on the record and they say different things, which is the whole reason to write the arithmetic
down rather than the story:

  * 2026-09-02 08:30Z, FAILED. The only two failing units were labelled ``IFEU.IMPACT RC/2026`` and
    ``IFEU.IMPACT W/2026`` -- ``only 1 of 3 expected session(s) present (window
    2026-08-28..2026-09-01)`` -- while all 7 GLBX and all 6 IFUS units on the same fire logged
    healthy lines. That same-fire control attributes the closure to ICE Europe and to nothing else.
    The window ends at T-1 over 3 weekdays, i.e. LAG 1, though this tree declares IFEU lag 2.
  * 2026-09-04 08:36Z, PASSED all 16. IFEU held 2 sessions (D-PR-16's own method: RC 18 rows / 10
    outrights, W 24 / 14) where GLBX held 4 and IFUS 3. At lag 1 that scores expected 4, present 2
    and would have RED-ed; at lag 2 it scores expected 3, present 2 -- green, margin fully
    consumed. So the lag CHANGED between the fires (the 2026-09-03 r2 repin), and the weekday IFEU
    is missing from 2026-08-31 / 09-01 / 09-02 is 2026-08-31 -- a Monday
    (``date.fromisoformat('2026-08-31').strftime('%a')`` -> ``Mon``), the last of August.

So the declared entry buys two different things depending on which fire you are looking at, and
BOTH are worth having: on the 09-02 arithmetic as it actually ran it turns the family-wide red into
a pass (expected 3 -> 2 against present 1), and under the correct lag 2 it hands back the
one-holiday margin (expected 3 -> 2 against present 2). What it does NOT do, stated so the false
premise is not re-derived: under lag 2 alone the closure never red-ed a healthy unit -- the margin
absorbed it, which is what the margin is for. The cost of that absorption is the sensitivity
D-PR-16 refused to give up, and that is what the calendar restores.

TWO SEPARATE CLAIMS, AND CONFLATING THEM IS THE TRAP THIS MODULE AVOIDS.

  * A DECLARED ENTRY is a claim about ONE date: "this dataset published nothing on this day", with
    a name (the mechanism) and a basis (how it was established). It carries its own authority, so
    it subtracts from ``expected`` as soon as it is written -- see ``holidays_for``.
  * ``complete: true`` on a YEAR is a much stronger claim: "this list is EXHAUSTIVE for that year".
    Only that claim ARMS a venue-year (``armed_for``), and only an ARMED venue-year can make the
    run refuse when a later year goes missing (``assert_armed``).

Writing ``complete: true`` over a partial list would be a mis-INFERRED floor -- the 2026-08-18
ALARM RCA class. So a year that cannot be verified exhaustively is left ``complete: false`` and its
individually-verified entries still do their work. A declared entry can only ever REMOVE a false
truncation verdict; it can never create one, because the margin and the predicate are untouched.

THE THREE LOAD RULES, each with the reason it exists (they mirror ``load_declared_gaps``):

  1. An ABSENT file is legal and means "nothing declared" -- behaviour byte-identical to the
     pre-Lane-A arithmetic, and no refusal. This is what makes landing the CODE safe while the
     calendar is still being filled, and makes ARMING a separate deliberate act.
  2. A MALFORMED file is a hard error, never a silently empty set. The difference between
     "declared" and "mistyped" must never be silent -- that is the whole point of a fence.
  3. An UNKNOWN dataset resolves to an EMPTY holiday set, mirroring the lag map's fallback of 1 in
     ``_truncation_error``. Fail-closed lives at ARM time (``assert_armed``), where it can name the
     operator's error, not inside a lookup that tests feed synthetic dataset tokens to.

NO DATE IS WRITTEN FROM MEMORY. Every entry names its basis, and the derivation lane that produces
candidates is ``scripts/silver/derive_venue_sessions.py`` -- which deliberately applies NO frequency
floor, because a once-in-a-decade closure (a state funeral, a national day of mourning) is exactly
the tail a ">= N years" screen would deny.
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

import yaml

from leviathan.silver.registry import CONFIGS_SILVER_DIR

VENUE_HOLIDAYS_PATH = CONFIGS_SILVER_DIR / "venue_holidays.yaml"

# Field discipline copied from configs/silver/futures_gaps.yaml (_GAP_FIELDS): an entry that
# cannot be read is a hard error, and an unknown key is a typo until proven otherwise.
_TOP_FIELDS = ("version", "datasets")
_DATASET_FIELDS = ("venue", "source_url", "years")
_YEAR_FIELDS = ("complete", "verified_on", "verified_by", "holidays")
_ENTRY_FIELDS = ("day", "name", "basis")
SCHEMA_VERSION = 1

# The honesty axis, exactly three values.
#   published      -- from the venue's PUBLISHED calendar only. The only basis available for a
#                     FUTURE year, which has no tape.
#   tape           -- derived from banked canonical rows (or from a fire that measured the
#                     absence) and not yet cross-checked against the published calendar.
#   published+tape -- both agree. The target state for every PAST year.
BASIS_VALUES = ("published", "tape", "published+tape")

# A source_url still carrying a placeholder is legal while a venue is UNARMED and illegal once it
# is armed: an exhaustive-year claim cited to "<fill me in>" is not a citation.
_PLACEHOLDER_MARKERS = ("<", ">", "TO BE FILLED", "TODO")


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that REFUSES a duplicated mapping key instead of keeping the last one.

    A-R8, MEASURED. ``yaml.safe_load`` silently keeps the LAST block when a key repeats, so a
    ``years:`` mapping carrying 2025 twice -- the exact shape produced by the documented workflow
    of appending one derived year block at a time -- loaded only the second and DELETED the first
    year's declared holidays with no error at all. Direction of harm is a false RED (fewer
    subtractions, i.e. straight back to the pre-Lane-A state), so it is bounded; but this file's
    stated contract is rule 2, "the difference between declared and mistyped must never be
    silent", and a silently halved calendar is exactly a mistype read as a declaration.
    """


def _no_duplicate_keys(loader, node, deep=False):
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate key {key!r} -- a repeated mapping key silently keeps "
                             f"only the LAST block, which would delete declared dates without "
                             f"an error")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def _fail(src_name: str, where: str, msg: str) -> None:
    raise ValueError(f"{src_name} {where}: {msg}")


def _iso_day(value, src_name: str, where: str) -> str:
    """One ISO ``YYYY-MM-DD`` date out of a field (PyYAML may hand back a ``date``)."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        _fail(src_name, where, f"{value!r} is not an ISO YYYY-MM-DD date")
    return ""                                            # unreachable; keeps the type checker calm


def has_placeholder(text: str) -> bool:
    """True when a citation is still a stub rather than a citation."""
    up = str(text or "").upper()
    return any(m.upper() in up for m in _PLACEHOLDER_MARKERS)


def _parse_year_block(src_name: str, dataset: str, year: int, block) -> dict:
    where = f"datasets.{dataset}.years.{year}"
    if not isinstance(block, dict):
        _fail(src_name, where, f"expected a mapping, got {type(block).__name__}")
    unknown = sorted(set(block) - set(_YEAR_FIELDS))
    missing = sorted(set(_YEAR_FIELDS) - set(block))
    if missing or unknown:
        _fail(src_name, where, f"missing {missing}, unknown {unknown} "
                               f"(required: {list(_YEAR_FIELDS)})")
    if not isinstance(block["complete"], bool):
        _fail(src_name, where, "complete must be a BOOLEAN -- 'yes'/'true' as a string is exactly "
                               "the ambiguity an exhaustiveness claim must not have")
    _iso_day(block["verified_on"], src_name, f"{where}.verified_on")
    if not str(block["verified_by"] or "").strip():
        _fail(src_name, where, "verified_by is empty -- a venue year is declared with who checked "
                               "it, never on its own authority")
    entries = block["holidays"]
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        _fail(src_name, where, f"holidays is a LIST of entries, got {type(entries).__name__}")
    days: dict[str, dict] = {}
    for i, rec in enumerate(entries):
        ewhere = f"{where}.holidays[{i}]"
        if not isinstance(rec, dict):
            _fail(src_name, ewhere, f"expected a mapping, got {type(rec).__name__}")
        eunknown = sorted(set(rec) - set(_ENTRY_FIELDS))
        emissing = sorted(set(_ENTRY_FIELDS) - set(rec))
        if emissing or eunknown:
            _fail(src_name, ewhere, f"missing {emissing}, unknown {eunknown} "
                                    f"(required: {list(_ENTRY_FIELDS)})")
        day = _iso_day(rec["day"], src_name, f"{ewhere}.day")
        if int(day[:4]) != int(year):
            _fail(src_name, ewhere, f"{day} does not belong to the {year} block")
        if not str(rec["name"] or "").strip():
            _fail(src_name, ewhere, "name is empty -- an entry NAMES the mechanism (the frequency "
                                    "floor this estate refuses is replaced by a narrating pin)")
        basis = str(rec["basis"] or "").strip()
        if basis not in BASIS_VALUES:
            _fail(src_name, ewhere, f"basis {basis!r} is not one of {list(BASIS_VALUES)}")
        if day in days:
            _fail(src_name, ewhere, f"{day} is declared twice")
        days[day] = {"day": day, "name": str(rec["name"]).strip(), "basis": basis}
    return {
        "complete": bool(block["complete"]),
        "verified_on": _iso_day(block["verified_on"], src_name, f"{where}.verified_on"),
        "verified_by": str(block["verified_by"]).strip(),
        "days": frozenset(days),
        "entries": tuple(days[d] for d in sorted(days)),
    }


@lru_cache(maxsize=None)
def load_venue_holidays(path: Optional[Path] = None) -> dict[str, dict]:
    """``{dataset: {venue, source_url, years: {year: {...}}}}`` from the tracked calendar.

    FAIL CLOSED on anything malformed (rule 2). An absent file returns ``{}`` (rule 1).
    """
    src = Path(path) if path is not None else VENUE_HOLIDAYS_PATH
    if not src.exists():
        return {}
    name = src.name
    # A-R8 + rule 2: a duplicated key and unparseable YAML are BOTH hard errors here, and both
    # arrive as the ValueError every caller of this module already expects.
    try:
        doc = yaml.load(src.read_text(encoding="utf-8"), Loader=_StrictLoader)
    except ValueError as exc:
        _fail(name, "top level", str(exc))
    except yaml.YAMLError as exc:
        _fail(name, "top level", f"is not parseable YAML: {exc}")
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        _fail(name, "top level", f"expected a mapping, got {type(doc).__name__}")
    unknown = sorted(set(doc) - set(_TOP_FIELDS))
    missing = sorted(set(_TOP_FIELDS) - set(doc))
    if missing or unknown:
        _fail(name, "top level", f"missing {missing}, unknown {unknown} "
                                 f"(required: {list(_TOP_FIELDS)})")
    if doc["version"] != SCHEMA_VERSION:
        _fail(name, "top level", f"version {doc['version']!r} is not the supported "
                                 f"{SCHEMA_VERSION} -- a fence must never be read by a reader that "
                                 f"does not understand its shape")
    datasets = doc["datasets"]
    if not isinstance(datasets, dict):
        _fail(name, "datasets", f"expected a mapping of dataset -> block, got "
                                f"{type(datasets).__name__}")
    out: dict[str, dict] = {}
    for dataset, block in datasets.items():
        where = f"datasets.{dataset}"
        if not isinstance(block, dict):
            _fail(name, where, f"expected a mapping, got {type(block).__name__}")
        dunknown = sorted(set(block) - set(_DATASET_FIELDS))
        dmissing = sorted(set(_DATASET_FIELDS) - set(block))
        if dmissing or dunknown:
            _fail(name, where, f"missing {dmissing}, unknown {dunknown} "
                               f"(required: {list(_DATASET_FIELDS)})")
        for field in ("venue", "source_url"):
            if not str(block[field] or "").strip():
                _fail(name, where, f"{field} is empty")
        years_raw = {} if block["years"] is None else block["years"]
        if not isinstance(years_raw, dict):
            _fail(name, f"{where}.years", f"expected a mapping of year -> block, got "
                                          f"{type(years_raw).__name__}")
        years: dict[int, dict] = {}
        for year_key, year_block in years_raw.items():
            try:
                year = int(year_key)
            except (TypeError, ValueError):
                _fail(name, f"{where}.years", f"{year_key!r} is not a calendar year")
                continue
            years[year] = _parse_year_block(name, str(dataset), year, year_block)
        out[str(dataset)] = {
            "venue": str(block["venue"]).strip(),
            "source_url": str(block["source_url"]).strip(),
            "years": years,
        }
    return out


def holidays_for(dataset: str, path: Optional[Path] = None) -> frozenset[str]:
    """The declared no-settlement ISO dates for ``dataset``, across every declared year.

    Rule 3: an UNKNOWN dataset resolves to an EMPTY set, never a refusal -- ``_truncation_error``
    stays pure and the existing pin ``test_an_undeclared_dataset_falls_back_to_lag_one`` is
    untouched. INCOMPLETE years contribute their entries: an entry is an individually verified
    claim about one date, while ``complete`` is the separate, stronger claim that the year holds no
    OTHER such date (see the module docstring).
    """
    block = load_venue_holidays(path).get(dataset or "")
    if not block:
        return frozenset()
    days: set[str] = set()
    for year in block["years"].values():
        days |= set(year["days"])
    return frozenset(days)


def armed_for(dataset: str, year: int, path: Optional[Path] = None) -> bool:
    """True when ``dataset`` declares ``year`` EXHAUSTIVELY (``complete: true``).

    A year block without ``complete: true`` is treated as MISSING for arming purposes, exactly as
    an absent block is: a partial list is not an exhaustiveness claim.
    """
    block = load_venue_holidays(path).get(dataset or "")
    if not block:
        return False
    year_block = block["years"].get(int(year))
    return bool(year_block and year_block["complete"])


def armed_datasets(path: Optional[Path] = None) -> list[str]:
    """Datasets carrying at least one exhaustively declared year, sorted."""
    doc = load_venue_holidays(path)
    return sorted(ds for ds, block in doc.items()
                  if any(y["complete"] for y in block["years"].values()))


def declaring_datasets(path: Optional[Path] = None) -> list[str]:
    """Datasets carrying at least one declared holiday entry, armed or not, sorted."""
    doc = load_venue_holidays(path)
    return sorted(ds for ds, block in doc.items()
                  if any(y["days"] for y in block["years"].values()))


def assert_armed(datasets: Iterable[str], years: Iterable[int], *,
                 require_armed: bool = False, path: Optional[Path] = None) -> list[str]:
    """Reasons the calendar cannot be trusted for these datasets over these years; ``[]`` == ok.

    Runtime (``require_armed=False``): a dataset that has NEVER been armed is not a refusal -- it
    is the pre-Lane-A world for that venue and is covered by the one-holiday margin exactly as it
    is today. A dataset that HAS been armed and is then missing (or non-exhaustive for) a year the
    run's window actually touches IS a refusal: that is calendar DRIFT on a fence someone is
    relying on, and it must never be silent.

    CI (``require_armed=True``): the dated forcing function. Every named dataset must be armed for
    every named year, and an armed year must carry a real citation rather than a placeholder.
    """
    doc = load_venue_holidays(path)
    want_years = sorted({int(y) for y in years})
    reasons: list[str] = []
    for dataset in sorted({str(d) for d in datasets if d}):
        block = doc.get(dataset)
        armed_years = sorted(y for y, b in (block or {}).get("years", {}).items() if b["complete"])
        if not block or not armed_years:
            if require_armed:
                reasons.append(f"{dataset}: NOT ARMED -- no year is declared complete in "
                               f"{VENUE_HOLIDAYS_PATH.name}")
            continue
        for year in want_years:
            if year not in armed_years:
                reasons.append(f"{dataset}: {year} is missing or not complete: true, but "
                               f"{sorted(armed_years)} is/are declared -- an armed venue calendar "
                               f"that stops covering the window is DRIFT, not a default")
        if require_armed and has_placeholder(block["source_url"]):
            reasons.append(f"{dataset}: source_url is still a placeholder "
                           f"({block['source_url']!r}) -- an armed year needs a real citation")
    return reasons
