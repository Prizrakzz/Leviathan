"""``check_state_board()`` -- every lint clause the state board's configs must pass.

STATE ENGINE DESIGN sec 2.3 / 2.4 / 2.6 / 5.2 / 1.4 and the S0 row of sec 11. Run by
``tests/unit/test_state_lint.py`` today and absorbed by ``config_check.check_state_board`` after the K9
lane commits (sec 9.2, phase 2) -- ``config_check.py`` is one of the five K9-held files, so this module
is where the clauses live in the meantime and the absorption is a MOVE, never a rewrite.

WHAT IT GRADES, and the one sentence each clause exists for:

  1. THE LAG TABLE (sec 2.3). Every ``lag`` string declared anywhere in the 36 DAGs is a key of
     ``lag_bands.yaml`` -- FAIL-CLOSED ON A NEW SPELLING, because an unparsed lag is a projection
     horizon nobody declared. Every table row's declared ``kind`` agrees with the kind its own
     ``(min_q, max_q)`` implies, and NO summed band exists anywhere in the ``state/`` package.

  2. THE CONVENTION REGISTRY (sec 2.4). Every ``ref`` is a real ref (a live cascade_map row, a
     ``board_read`` row, or a DAG ``silver_ref``); every ``kind`` is in the closed enum; bands are
     sorted and match their labels one for one; ``oni_climate``'s bands ARE
     ``silverleg._ONI_INTENSITY_BANDS`` -- ONE VOCABULARY, so the board and the firing leg can never
     say "strong" at two different anomalies; and EVERY label and template literal returns zero from
     ``register.count_flow_words`` / ``count_valuation_words`` / ``register_leaks`` / ``_LANE_B_ADJ``.

  3. THE RELEASE CALENDAR (sec 5.2). Every ``tables`` entry is a registered card; every card behind a
     live map ref or a ``board_read`` row appears in EXACTLY ONE source or under ``uncalendared:`` --
     so an absence is a declared row and never a silence; every ``rule.kind`` is in the closed enum,
     its parameters are in range, and NO rule carries a key its own kind cannot mean. The last clause
     is the S0-review fence: ``first_business_day`` (NASS, FGIS) rejects a ``dow`` outright, because a
     hard-coded weekday is exactly the error the kind replaces, and ``published_date`` (the World Bank)
     rejects every computable key, because that publisher states a DATE and follows no rule at all.
     ``verified_against`` and ``verified_on`` are a PAIR: a verification with no date cannot go stale.

  4. THE ``board_read`` ROWS (sec 2.6, D23). Each one carries ``deferred: true`` AND is absent from
     ``cascade.load_map()`` -- the mechanical proof that the serving cascade cannot see it -- and each
     passes ``check_cascade_map``'s OWN clauses, which the shipped check skips by construction because
     it grades ``load_map()`` and ``load_map()`` drops deferred rows.

  5. THE ``year_month`` PUBLICATION LAG (sec 1.4, D21). A card declaring ``ym_publication_lag_days``
     really is ``knowledge_semantics: year_month``; the three cards the board leans on declare it; any
     OTHER year_month card that does not is named as a warning, so the estate's five year_month cards
     are all accounted for rather than three of them being silently the whole story.

  6. THE ``country_name_ref`` PAIRING (S0 finding). Any card declaring a ``country_name_ref`` has a
     loader in ``query._COUNTRY_REF_LOADERS``: ``query._country_ref`` RAISES on a ref no loader serves,
     so a card key landing ahead of its loader turns an honest zero-row read into a hard error on every
     lookup that names a country. The two must land in one commit, and this clause is the fence.

CLOCK-FREE BY DEFAULT. The 180-day staleness warning on a calendar row needs a date, and this module
reads no clock (the ``_cw_first_of_months`` discipline): pass ``asof`` to
:func:`state_board_warnings` to enable it, and it says plainly when it is skipped.

DEGRADES HONESTLY. The clauses that import from the K9-held ``cascade.py`` catch the import and report
it as a clause-level error naming the file, rather than taking the whole lint down while the K9 fix
workflow is mid-edit.
"""
from __future__ import annotations

import datetime as _dt
import functools
import pathlib
import re
from typing import Optional

import yaml

from leviathan.graphrag import extract as ex  # ex._CFG -> configs/graphrag
from leviathan.graphrag.state import lagbands as lb

# ── closed enums (each one is a fence, not a convenience) ────────────────────────────────────────────
CONVENTION_KINDS = ("abs_bands", "z_bands", "percentile_bands", "pace_vs_prior_year")
CADENCE_KEYS = ("daily", "weekly", "biweekly", "monthly", "annual")
RULE_KINDS = ("monthly_window", "weekly_dow", "first_business_day", "daily_sessions",
              "published_date")
#: MM-DD, both ends inclusive -- the seasonal window a `first_business_day` publisher runs in
#: (NASS Crop Progress is April 1 - November 30 by NASS's own words; a rule with no season
#: promises a January release nobody prints).
_MMDD_RX = re.compile(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
DOWS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
PERIOD_TYPES = ("date", "marketing_year", "year_month")
COUNTRY_RULES = (None, "primary", "none", "region")
NASS_KINDS = ("state", "national")

#: the three ``year_month`` registry cards the board leans on (sec 1.4). The estate has FIVE year_month
#: cards; the other two are named by the warning clause rather than assumed away.
YM_BOARD_CARDS = ("silver_noaa_oni", "silver_noaa_iod", "gold_weather_z")

#: MEASURED at the S0 landing (2026-09-08) and pinned as the inertness proof of the ``board_read`` rows
#: (sec 2.6). A change in either number is a CURATION EVENT to re-bank deliberately, never a surprise.
LOAD_MAP_ROWS_AT_S0 = 46
CAUSAL_DAG_FILES_AT_S0 = 36

_CAUSAL_REL = "causal"
# The band-sum detector, COMPOSED from a part so that the detector's own source lines do not match
# it (the first version of this module tripped on its own regex literal -- a fence that cannot
# describe itself is a fence that lies about the file it lives in).
_Q = r"(?:min_q|max_q)"
_SUM_RX = re.compile(
    _Q + r"\s*\+\s*(?!=)|"                              # a band end, added to something
    r"\+\s*(?:\w+\.)?" + _Q + r"\b|"                    # something, added to a band end
    r"\bsum\s*\(\s*[^)]*\." + _Q                        # a band end summed across a path
)


# ── loaders (each its own lru_cache: the load_region_map precedent) ──────────────────────────────────
def _cfg(*rel: str) -> pathlib.Path:
    return ex._CFG.joinpath(*rel)


@functools.lru_cache(maxsize=1)
def load_conventions() -> dict:
    p = _cfg("numbers", "state_conventions.yaml")
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


@functools.lru_cache(maxsize=1)
def load_release_calendar() -> dict:
    p = _cfg("numbers", "release_calendar.yaml")
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


@functools.lru_cache(maxsize=1)
def load_nass_states() -> dict:
    p = _cfg("numbers", "nass_states.yaml")
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


@functools.lru_cache(maxsize=1)
def _raw_cascade_map() -> dict:
    p = _cfg("numbers", "cascade_map.yaml")
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


@functools.lru_cache(maxsize=1)
def board_map() -> dict:
    """The BOARD's view of ``cascade_map.yaml``: every row live for the cascade PLUS every row carrying
    BOTH ``deferred: true`` and ``board_read: true`` (sec 2.6 (i)).

    A SECOND reader of the same file, exactly as ``cascade.load_region_map`` is -- ``load_map()``
    returns the live ``refs`` rows only, so the board cannot piggyback it. This lives here at S0 because
    ``state/feeders.py`` (which owns it from S1 as ``board_map_row``) is not built yet; when it lands,
    this function MOVES there and the lint imports it, so there is never a second implementation.
    """
    refs = (_raw_cascade_map().get("refs") or {})
    out = {}
    for ref, row in refs.items():
        row = row or {}
        if not row.get("deferred") or row.get("board_read"):
            out[ref] = row
    return out


@functools.lru_cache(maxsize=1)
def board_read_rows() -> dict:
    """Only the rows that are deferred for the cascade and read by the board."""
    return {ref: row for ref, row in (_raw_cascade_map().get("refs") or {}).items()
            if (row or {}).get("board_read")}


@functools.lru_cache(maxsize=1)
def _dag_docs() -> tuple:
    d = _cfg(_CAUSAL_REL)
    out = []
    for p in sorted(d.glob("*.yaml")):
        out.append((p.name, yaml.safe_load(p.read_text(encoding="utf-8")) or {}))
    return tuple(out)


@functools.lru_cache(maxsize=1)
def _dag_silver_refs() -> frozenset:
    return frozenset(dr.get("silver_ref") for _, doc in _dag_docs()
                     for dr in (doc.get("drivers") or []) if dr.get("silver_ref"))


# ── clause 1: the lag table ──────────────────────────────────────────────────────────────────────────
def _check_lag_table() -> list[str]:
    errs: list[str] = []
    doc = lb.load_lag_bands()
    bands = doc.get("bands") or {}
    if not bands:
        return ["lag_bands.yaml: no `bands` block -- the lag vocabulary has no table"]
    if doc.get("schema_default") != "":
        errs.append("lag_bands.yaml: `schema_default` must be the empty string (causal/schema.py "
                    "declares `lag: str = \"\"`), got %r" % (doc.get("schema_default"),))
    if "" not in bands:
        errs.append("lag_bands.yaml: the schema default \"\" is not a key -- an absent `lag` must be a "
                    "table row, not a missing one")
    for key, row in bands.items():
        row = row or {}
        mn, mx = row.get("min_q"), row.get("max_q")
        if not isinstance(mn, int) or mn < 0:
            errs.append("lag_bands.yaml %r: min_q must be a non-negative int, got %r" % (key, mn))
            continue
        if mx is not None and (not isinstance(mx, int) or mx < mn):
            errs.append("lag_bands.yaml %r: max_q must be null or an int >= min_q, got %r" % (key, mx))
            continue
        declared = row.get("kind")
        if declared not in lb.KINDS:
            errs.append("lag_bands.yaml %r: kind %r not in %s" % (key, declared, list(lb.KINDS)))
            continue
        implied = lb.derived_kind(mn, mx, key)
        if declared != implied:
            errs.append("lag_bands.yaml %r: declared kind %r but (min_q=%r, max_q=%r) implies %r"
                        % (key, declared, mn, mx, implied))
        parsed = lb.parse_lag(key)
        if (parsed.min_q, parsed.max_q) != (mn, mx):
            errs.append("lag_bands.yaml %r: parse_lag disagrees with the table (%r vs %r)"
                        % (key, (parsed.min_q, parsed.max_q), (mn, mx)))

    docs = _dag_docs()
    if len(docs) != CAUSAL_DAG_FILES_AT_S0:
        errs.append("configs/graphrag/causal: %d DAG YAMLs, expected %d at the S0 landing -- a curation "
                    "event; re-bank the counts in lag_bands.yaml and in state/lint.py"
                    % (len(docs), CAUSAL_DAG_FILES_AT_S0))
    for name, doc2 in docs:
        for dr in (doc2.get("drivers") or []):
            raw = dr.get("lag", "")
            if lb.parse_lag(raw).unparsed:
                errs.append("%s driver %r: lag %r is not a key of lag_bands.yaml (fail-closed on a new "
                            "spelling)" % (name, dr.get("id"), raw))
        for i, e in enumerate(doc2.get("inter_commodity") or []):
            raw = e.get("lag", "")
            if lb.parse_lag(raw).unparsed:
                errs.append("%s inter_commodity[%d] -> %r: lag %r is not a key of lag_bands.yaml"
                            % (name, i, e.get("driver_commodity"), raw))
    return errs


def _check_no_summed_band() -> list[str]:
    """A path's band is NEVER summed (doctrine M-4). ``LagBand.__add__`` refuses it at runtime; this
    clause refuses it in the SOURCE, because the arithmetic is one character and the horizon it invents
    is one the graph never declared."""
    errs: list[str] = []
    here = pathlib.Path(__file__).resolve().parent
    for p in sorted(here.glob("*.py")):
        src = p.read_text(encoding="utf-8")
        for n, line in enumerate(src.splitlines(), start=1):
            if line.lstrip().startswith("#") or "_SUM_RX" in line or "_Q = " in line:
                continue
            if _SUM_RX.search(line):
                errs.append("state/%s:%d: a summed lag band -- a path's band is never summed "
                            "(sec 2.3, doctrine M-4): %s" % (p.name, n, line.strip()[:90]))
    return errs


# ── clause 2: the convention registry ────────────────────────────────────────────────────────────────
def _register_hits(text: str) -> list[str]:
    """Zero from all four register detectors, or the reasons. Imported lazily: ``register.py`` is FREE
    but the lint must still name the failure rather than crash if the import moves."""
    try:
        from leviathan.graphrag import register as reg
    except Exception as exc:  # noqa: BLE001
        return ["could not import graphrag.register to check register safety: %s" % (exc,)]
    hits = []
    if reg.count_flow_words(text):
        hits.append("count_flow_words=%d" % reg.count_flow_words(text))
    if reg.count_valuation_words(text):
        hits.append("count_valuation_words=%d" % reg.count_valuation_words(text))
    leaks = reg.register_leaks(text)
    if leaks:
        hits.append("register_leaks=%r" % (leaks[:3],))
    if reg._LANE_B_ADJ.search(text):
        hits.append("_LANE_B_ADJ matched %r" % reg._LANE_B_ADJ.search(text).group(0))
    return hits


def _check_conventions() -> list[str]:
    errs: list[str] = []
    doc = load_conventions()
    if not doc:
        return ["state_conventions.yaml: missing or empty"]
    windows = doc.get("windows") or {}
    for k, v in windows.items():
        if k not in CADENCE_KEYS:
            errs.append("state_conventions windows: %r not in the cadence enum %s" % (k, list(CADENCE_KEYS)))
        if not isinstance(v, int) or v <= 0:
            errs.append("state_conventions windows.%s: must be a positive int, got %r" % (k, v))
    semantics = doc.get("band_semantics") or {}
    for kind in CONVENTION_KINDS:
        if not (semantics.get(kind) or "").strip():
            errs.append("state_conventions band_semantics: no rule declared for kind %r -- a consumer "
                        "would have to GUESS how a value becomes a label" % (kind,))

    known_refs = set(board_map()) | _dag_silver_refs()
    convs = doc.get("conventions") or {}
    if not convs:
        errs.append("state_conventions.yaml: no `conventions` block")
    for ref, row in convs.items():
        row = row or {}
        if ref not in known_refs:
            errs.append("state_conventions %r: not a live cascade_map ref, a board_read row, or a DAG "
                        "silver_ref -- a convention on a ref nothing names is dead config" % (ref,))
        kind = row.get("kind")
        if kind not in CONVENTION_KINDS:
            errs.append("state_conventions %r: kind %r not in %s" % (ref, kind, list(CONVENTION_KINDS)))
        bands, labels = row.get("bands"), row.get("labels")
        if not isinstance(bands, list) or not bands or not all(isinstance(b, (int, float)) for b in bands):
            errs.append("state_conventions %r: bands must be a non-empty list of numbers, got %r" % (ref, bands))
        elif list(bands) != sorted(bands) or len(set(bands)) != len(bands):
            errs.append("state_conventions %r: bands must be strictly ascending, got %r" % (ref, bands))
        if not isinstance(labels, list) or (isinstance(bands, list) and len(labels or []) != len(bands)):
            errs.append("state_conventions %r: len(labels) must equal len(bands) (%r vs %r)"
                        % (ref, labels, bands))
        hwk = row.get("history_window_key")
        if hwk not in windows:
            errs.append("state_conventions %r: history_window_key %r is not a declared window" % (ref, hwk))
        hw = row.get("history_window")
        if hw is not None and (not isinstance(hw, int) or hw <= 0):
            errs.append("state_conventions %r: history_window must be a positive int, got %r" % (ref, hw))
        for lbl in (labels or []):
            hits = _register_hits(str(lbl))
            if hits:
                errs.append("state_conventions %r: label %r is NOT register-safe (%s)"
                            % (ref, lbl, "; ".join(hits)))

    # ONE VOCABULARY: the ONI bands ARE silverleg's, read ascending where silverleg stores them descending.
    try:
        from leviathan.graphrag import silverleg as sl
        want_bands = [b for b, _ in reversed(sl._ONI_INTENSITY_BANDS)]
        want_labels = [w for _, w in reversed(sl._ONI_INTENSITY_BANDS)]
        oni = convs.get("oni_climate") or {}
        if [float(x) for x in (oni.get("bands") or [])] != [float(x) for x in want_bands]:
            errs.append("state_conventions oni_climate: bands %r != silverleg._ONI_INTENSITY_BANDS %r -- "
                        "ONE vocabulary, no drift" % (oni.get("bands"), want_bands))
        if list(oni.get("labels") or []) != want_labels:
            errs.append("state_conventions oni_climate: labels %r != silverleg._ONI_INTENSITY_BANDS %r"
                        % (oni.get("labels"), want_labels))
    except Exception as exc:  # noqa: BLE001
        errs.append("could not import graphrag.silverleg to pin the ONI vocabulary: %s" % (exc,))

    # positioning is READ and FENCED (D18): the config must SAY context_only, never leave it to a caller.
    pos = convs.get("cot_mm_positioning") or {}
    if pos and pos.get("context_only") is not True:
        errs.append("state_conventions cot_mm_positioning: `context_only: true` is the whole positioning "
                    "rule (D18) and must be declared on the row")
    if pos and pos.get("history_window") != 156:
        errs.append("state_conventions cot_mm_positioning: history_window must be 156 weeks, got %r"
                    % (pos.get("history_window"),))
    return errs


# ── clause 3: the release calendar ───────────────────────────────────────────────────────────────────
def _registered_cards() -> dict:
    from leviathan.graphrag.numbers.registry import load_registry
    return dict(load_registry().tables)


def _cards_needing_a_rule() -> set:
    """Every card behind a live cascade_map ref or a ``board_read`` row -- the set whose absence from
    the calendar must be DECLARED rather than silent."""
    return {(row or {}).get("table") for row in board_map().values() if (row or {}).get("table")}


def _check_calendar() -> list[str]:
    errs: list[str] = []
    doc = load_release_calendar()
    if not doc:
        return ["release_calendar.yaml: missing or empty"]
    if tuple(doc.get("rule_kinds") or ()) != RULE_KINDS:
        errs.append("release_calendar rule_kinds %r != the closed enum %s"
                    % (doc.get("rule_kinds"), list(RULE_KINDS)))
    cards = _registered_cards()
    seen: dict = {}
    for sid, src in (doc.get("sources") or {}).items():
        src = src or {}
        tables = src.get("tables") or []
        if not tables:
            errs.append("release_calendar %r: no tables -- a source that names no card is dead config" % (sid,))
        for t in tables:
            if t not in cards:
                errs.append("release_calendar %r: table %r is not a registered card" % (sid, t))
            if t in seen:
                errs.append("release_calendar: table %r appears in both %r and %r -- exactly one home"
                            % (t, seen[t], sid))
            seen[t] = sid
        rule = src.get("rule") or {}
        kind = rule.get("kind")
        if kind not in RULE_KINDS:
            errs.append("release_calendar %r: rule.kind %r not in %s" % (sid, kind, list(RULE_KINDS)))
        elif kind == "monthly_window":
            lo, hi = rule.get("day_min"), rule.get("day_max")
            if not (isinstance(lo, int) and isinstance(hi, int) and 1 <= lo <= hi <= 28):
                errs.append("release_calendar %r: monthly_window needs 1 <= day_min <= day_max <= 28 "
                            "(28 so every month has the day), got %r..%r" % (sid, lo, hi))
        elif kind == "weekly_dow":
            if rule.get("dow") not in DOWS:
                errs.append("release_calendar %r: weekly_dow dow %r not in %s" % (sid, rule.get("dow"), list(DOWS)))
        elif kind == "first_business_day":
            # DELTA PASS 1 items B4.6 / B4.7 (design :3119-3131): NASS and FGIS publish on the week's
            # FIRST BUSINESS DAY, which is Monday only until a Monday holiday -- proved live, Labor Day
            # 2026-09-07 pushed the FGIS report to Tuesday 09-08. A weekday key on this kind would be
            # the very mistake the kind exists to make impossible, so it is an ERROR and not a warning.
            for k in ("dow", "day_min", "day_max"):
                if k in rule:
                    errs.append("release_calendar %r: a first_business_day rule carries %r -- the kind "
                                "exists BECAUSE the day is not fixed (a Monday holiday moves it), so a "
                                "weekday or a day-of-month here re-states the error it replaces"
                                % (sid, k))
            sf, st = rule.get("season_from"), rule.get("season_to")
            if (sf is None) != (st is None):
                errs.append("release_calendar %r: season_from and season_to land together or not at all "
                            "-- half a season is a window with no end" % (sid,))
            for k, v in (("season_from", sf), ("season_to", st)):
                if v is not None and not _MMDD_RX.fullmatch(str(v)):
                    errs.append("release_calendar %r: %s must be MM-DD (no year -- a season repeats), "
                                "got %r" % (sid, k, v))
        elif kind == "daily_sessions":
            wd = rule.get("weekdays_only")
            if wd is not None and not isinstance(wd, bool):
                errs.append("release_calendar %r: weekdays_only must be a bool, got %r" % (sid, wd))
        elif kind == "published_date":
            # DELTA PASS 1 item B4.9: the World Bank prints "Next update: <date>" and follows NO rule
            # (Tue 08-04, Wed 09-02, Fri 10-02 -- no shared weekday, no shared day-of-month). The kind
            # computes NOTHING, so any computable key on it is a rule smuggled back in under a name
            # that promises there is none.
            extra = sorted(set(rule) - {"kind", "note"})
            if extra:
                errs.append("release_calendar %r: a published_date rule carries %r -- this kind computes "
                            "nothing by definition; the publisher states its own date and V1.1 scrapes it"
                            % (sid, extra))
        va = src.get("verified_against")
        if va is not None and not isinstance(va, str):
            errs.append("release_calendar %r: verified_against must be null or a string naming what it "
                        "was checked against, got %r" % (sid, va))
        vo = src.get("verified_on")
        if vo is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(vo)):
            errs.append("release_calendar %r: verified_on must be null or an ISO date, got %r" % (sid, vo))
        if va is not None and vo is None:
            errs.append("release_calendar %r: verified_against is set but verified_on is null -- a "
                        "verification with no date cannot go stale, which is how a stale rule survives" % (sid,))
        if not (src.get("derived_from") or "").strip():
            errs.append("release_calendar %r: no `derived_from` -- every rule says where it came from" % (sid,))

    unc = doc.get("uncalendared") or {}
    if isinstance(unc, list):
        unc = {t: "" for t in unc}
    for t, reason in unc.items():
        if t not in cards:
            errs.append("release_calendar uncalendared: %r is not a registered card" % (t,))
        if t in seen:
            errs.append("release_calendar: table %r is both under source %r and uncalendared -- one home"
                        % (t, seen[t]))
        if not str(reason or "").strip():
            errs.append("release_calendar uncalendared %r: no reason -- a declared absence states WHY, "
                        "or it is just a silence with a heading" % (t,))
    covered = set(seen) | set(unc)
    for t in sorted(_cards_needing_a_rule() - covered):
        errs.append("release_calendar: card %r sits behind a live cascade_map ref or a board_read row "
                    "but appears in neither `sources` nor `uncalendared` -- the absence must be a row" % (t,))
    return errs


# ── clause 4: the board_read rows ────────────────────────────────────────────────────────────────────
def _check_board_read_rows() -> list[str]:
    errs: list[str] = []
    rows = board_read_rows()
    try:
        from leviathan.graphrag.numbers.cascade import load_map
        live = load_map()
    except Exception as exc:  # noqa: BLE001
        return ["could not import cascade.load_map (the K9 lane holds cascade.py; importing it is a READ, "
                "not an edit): %s" % (exc,)]
    if len(live) != LOAD_MAP_ROWS_AT_S0:
        errs.append("cascade.load_map serves %d rows, %d at the S0 landing -- a change here is a curation "
                    "event to re-bank deliberately, and the board_read rows must NOT be among them"
                    % (len(live), LOAD_MAP_ROWS_AT_S0))
    try:
        from leviathan.graphrag.numbers.cascade_census import UNCERTIFIED_TABLES as uncertified
    except Exception:  # noqa: BLE001
        uncertified = frozenset()
    cards = _registered_cards()
    known = set(board_map())
    for ref, row in rows.items():
        row = row or {}
        if not row.get("deferred"):
            errs.append("cascade_map %r: `board_read: true` without `deferred: true` -- the row would be "
                        "LIVE for the serving cascade with no flag, no arm and no golden (D23)" % (ref,))
        if ref in live:
            errs.append("cascade_map %r: a board_read row is being served by load_map() -- the inertness "
                        "the whole form rests on is broken" % (ref,))
        # check_cascade_map's own clauses, which the shipped check skips on a deferred row
        ts = cards.get(row.get("table"))
        if ts is None:
            errs.append("cascade_map %r: unknown table %r" % (ref, row.get("table")))
        else:
            if row.get("metric") not in ts.metrics:
                errs.append("cascade_map %r: metric %r not in %r" % (ref, row.get("metric"), row.get("table")))
            if row.get("country_rule") == "none" and getattr(ts, "country_col", None):
                errs.append("cascade_map %r: country_rule 'none' on a table declaring a country axis (%r) "
                            "-- an unscoped read is mixed-geography garbage (the W0-7 class)"
                            % (ref, ts.country_col))
        if row.get("table") in uncertified:
            errs.append("cascade_map %r: table %r is uncertified/empty" % (ref, row.get("table")))
        if row.get("period_type") not in PERIOD_TYPES:
            errs.append("cascade_map %r: bad period_type %r" % (ref, row.get("period_type")))
        if float(row.get("scale", 1) or 1) != 1 and not row.get("narrate_unit"):
            errs.append("cascade_map %r: scale != 1 requires narrate_unit" % (ref,))
        if row.get("country_rule") not in COUNTRY_RULES:
            errs.append("cascade_map %r: bad country_rule %r" % (ref, row.get("country_rule")))
        sas = row.get("same_series_as")
        if sas is not None and sas not in known:
            errs.append("cascade_map %r: same_series_as %r is not a live or board_read ref" % (ref, sas))
        off = row.get("offset_months")
        if off is not None and not isinstance(off, int):
            errs.append("cascade_map %r: offset_months must be an int, got %r" % (ref, off))
        if sas is not None and off is None:
            errs.append("cascade_map %r: same_series_as without offset_months -- a collapsed row must say "
                        "by how much it is shifted, or it is silently claiming to BE the other series" % (ref,))

    # `global_state` agrees with the row's own keying prose and with the card's axes
    for ref, row in board_map().items():
        row = row or {}
        if "global_state" not in row:
            continue
        if row.get("global_state") is not True:
            errs.append("cascade_map %r: global_state must be true when present, got %r"
                        % (ref, row.get("global_state")))
        ts = cards.get(row.get("table"))
        if ts is not None and (getattr(ts, "commodity_col", None) or getattr(ts, "country_col", None)):
            errs.append("cascade_map %r: global_state on a card with a commodity/country axis (%r/%r) -- "
                        "a global state is ONE series, and this card has many"
                        % (ref, getattr(ts, "commodity_col", None), getattr(ts, "country_col", None)))
        keying = str(row.get("keying") or "")
        if "global" not in keying.lower() and "NO commodity" not in keying:
            errs.append("cascade_map %r: global_state: true but the `keying:` line does not say the row is "
                        "global -- the key and the prose must agree: %r" % (ref, keying[:80]))
    return errs


# ── clause 5: the year_month publication lag ─────────────────────────────────────────────────────────
def _check_ym_lag() -> list[str]:
    errs: list[str] = []
    cards = _registered_cards()
    for tid, ts in sorted(cards.items()):
        v = getattr(ts, "ym_publication_lag_days", None)
        if v is None:
            continue
        if not isinstance(v, int) or v < 0:
            errs.append("registry %r: ym_publication_lag_days must be null or a non-negative int, got %r"
                        % (tid, v))
        if ts.knowledge_semantics != "year_month":
            errs.append("registry %r: ym_publication_lag_days on a %r card -- the key shifts the "
                        "year_month branch of the as-of guard and means nothing anywhere else"
                        % (tid, ts.knowledge_semantics))
    for tid in YM_BOARD_CARDS:
        ts = cards.get(tid)
        if ts is None:
            errs.append("registry: %r is not a registered card, but the board leans on it (sec 1.4)" % (tid,))
        elif getattr(ts, "ym_publication_lag_days", None) is None:
            errs.append("registry %r: no ym_publication_lag_days -- the board's three year_month cards "
                        "each declare one (a value marked UNVERIFIED is a row; silence is not)" % (tid,))
    return errs


# ── clause 6: the country_name_ref pairing, and the NASS reference itself ────────────────────────────
def _check_country_ref_pairing() -> list[str]:
    errs: list[str] = []
    try:
        from leviathan.graphrag.numbers.query import _COUNTRY_REF_LOADERS as loaders
    except Exception as exc:  # noqa: BLE001
        return ["could not import query._COUNTRY_REF_LOADERS: %s" % (exc,)]
    for tid, ts in sorted(_registered_cards().items()):
        ref = getattr(ts, "country_name_ref", None)
        if ref and ref not in loaders:
            errs.append("registry %r: country_name_ref %r has NO loader in query._COUNTRY_REF_LOADERS "
                        "(%s) -- query._country_ref RAISES on it, so every lookup naming a country on "
                        "this card becomes a hard error. The card key and the loader land in ONE commit."
                        % (tid, ref, sorted(loaders)))
    return errs


def _check_nass_states() -> list[str]:
    errs: list[str] = []
    doc = load_nass_states()
    if not doc:
        return ["nass_states.yaml: missing or empty"]
    codes = doc.get("codes") or {}
    if not codes:
        return ["nass_states.yaml: no `codes` block"]
    if "US" not in codes:
        errs.append("nass_states.yaml: no 'US' code -- the national roll-up is the value a "
                    "`region_map` token resolving to 'United States' must reach")
    seen_alias: dict = {}
    for code, entry in codes.items():
        entry = entry or {}
        if not (isinstance(code, str) and re.fullmatch(r"[A-Z]{2}", code)):
            errs.append("nass_states.yaml: code %r is not a 2-letter uppercase USPS code (and every key "
                        "is quoted so YAML never resolves one as a boolean)" % (code,))
        if not (entry.get("name") or "").strip():
            errs.append("nass_states.yaml %r: no display name" % (code,))
        if entry.get("kind") not in NASS_KINDS:
            errs.append("nass_states.yaml %r: kind %r not in %s" % (code, entry.get("kind"), list(NASS_KINDS)))
        if not isinstance(entry.get("pseudo"), bool):
            errs.append("nass_states.yaml %r: pseudo must be a bool" % (code,))
        for a in (entry.get("aliases") or []):
            if a != str(a).strip().lower():
                errs.append("nass_states.yaml %r: alias %r is not normalized (lowercase, stripped) -- the "
                            "loader normalizes the model's country the same way" % (code, a))
            if a in seen_alias and seen_alias[a] != code:
                errs.append("nass_states.yaml: alias %r maps to BOTH %r and %r -- an ambiguous alias "
                            "resolves to whichever loads last" % (a, seen_alias[a], code))
            seen_alias[a] = code
    if "united states" not in seen_alias:
        errs.append("nass_states.yaml: no alias 'united states' -- `region_map` resolves a US token to "
                    "that exact display name, and without the alias every NASS row stays unreachable")
    return errs



# ── clause 9 (S3): every closed word a reader can meet has a SENTENCE ────────────────────────────────
def _check_absence_vocabulary() -> list[str]:
    """Every word in every closed enum this package renders has a plain sentence in
    ``render.ABSENCE_WHY``. Empty list == clean.

    THIS IS THE CONTRACT BETWEEN THE VOCABULARIES AND THE RENDER, and it fails at BUILD for a measured
    reason: ``rows.STATUS_WORDS``' own docstring says "EVERY word here is rendered to a reader as an
    SB-X absence line the S3 render must carry a sentence for, so a word added here is work assigned to
    a later sitting, and adding one silently is the failure this docstring exists to prevent". Prose
    cannot enforce that. This clause can: a word without a sentence renders as the fallback, and a
    reader would meet a generic line where a specific fact was owed."""
    errs: list[str] = []
    from leviathan.graphrag.state import board as B
    from leviathan.graphrag.state import render as R
    from leviathan.graphrag.state import rows as ROWS
    seen: dict = {}
    for leg, words in B.LEG_REASONS.items():
        for w in words:
            seen.setdefault(w, f"board.LEG_REASONS[{leg!r}]")
    for w in ROWS.STATUS_WORDS:
        seen.setdefault(w, "rows.STATUS_WORDS")
    for w in ROWS.TAPE_STATUS_WORDS:
        seen.setdefault(w, "rows.TAPE_STATUS_WORDS")
    seen.pop("ok", None)
    for w, where in sorted(seen.items()):
        if w not in R.ABSENCE_WHY:
            errs.append("render.ABSENCE_WHY has no sentence for the closed word %r (declared in %s): "
                        "a reader would meet the fallback line instead of the fact the word names"
                        % (w, where))
    for w in sorted(R.ABSENCE_WHY):
        if w not in seen:
            errs.append("render.ABSENCE_WHY carries a sentence for %r, which no closed enum declares "
                        "-- a sentence with no word is a vocabulary nobody can reach" % (w,))
        if any(ch.isdigit() for ch in R.ABSENCE_WHY[w]):
            errs.append("render.ABSENCE_WHY[%r] carries a digit; SB-X is a letters-only class" % (w,))
    return errs


# ── clause 10 (S3): the row-class regexes are pairwise disjoint and disjoint from the walk's ─────────
def _check_row_classes() -> list[str]:
    """Sec 6.2's regexes compile, are pairwise disjoint on a SAMPLE line per class, and do not match the
    walk's own line classes (``CW_CONTEXT_LINE_RX``, ``CW_FX_LINE_RX``) or the extreme locator's.

    THE SAMPLES ARE THE SPEC, and they live here rather than in a deck for one reason: the disjointness
    claim is about the REGEXES, which are code, while a deck's corpus is about the RENDER, which is
    behaviour. Both are graded -- the deck asserts exactly one class matches every line the three
    acceptance fixtures produce -- and this clause is the half that fails without a board."""
    errs: list[str] = []
    from leviathan.graphrag.state import render as R
    samples = {
        "SB-H": "STATE OF THE WORLD at 2026-09-07 for CBOT soybeans: two drivers read on their own "
                "series, one carried as dated receipts; ordered by how far each reading sits from its "
                "own history.",
        "SB-1": "- [N1] El Nino on CBOT soybeans, NOAA ONI for 2026-08-31: +0.98 degC; [N2] +1.2 sigma "
                "on its trailing window of one hundred twenty months [series: CBOT soybeans; table: "
                "NOAA ONI]",
        "SB-V": "- [N7] WATCH the level a convention names El Nino on CBOT soybeans: 0.52 degC "
                "under the strong line at 1.5 degC -- 2026-08-31",
        "SB-T": "- [N9] CBOT soybeans front 2026-11 settle on 2026-09-04: 1085.08 USc/bu",
        "SB-O": "- [N11] the soybean monthly benchmark over the band the graph declares from that "
                "state, one to two quarters: moved 46.33 USD/t by the near end; [N12] moved 68.21 "
                "USD/t by the far end",
        "SB-W": "- WATCH the next scheduled print El Nino on CBOT soybeans (NOAA ONI): scheduled "
                "between 2026-10-01 and 2026-10-05 -- 2026-10-01 to 2026-10-05",
        "SB-R": "- [E1][T1] (Indonesia Ministry of Energy, reported 2026-05-02; event 2026-05-01) "
                "{driver: biodiesel mandate} the blend mandate moved",
        "SB-E": "- El Nino is declared to move CBOT soybeans in the opposite direction with a lag the "
                "graph states as one to two quarters, at medium confidence",
        "SB-J": "- conditional on the lag the graph states, counted from the run's start in April "
                "2026, the effect window on CBOT soybeans opens around July 2026 and closes around "
                "October 2026",
        "SB-D": "- biodiesel mandate dated 2026-05-01 by [E1] (published 2026-05-02): the CME palm oil "
                "graph records it in the same direction with a lag of zero to two quarters",
        "SB-F": "- the same reading is declared on thirty-four other boards: in the opposite direction "
                "on twenty-eight (CBOT corn) and in the same direction on the rest (CME palm oil)",
        "SB-C": "- biodiesel energy-price floor (price-supportive) on CME palm oil: two of its three "
                "declared drivers sit among this board's twenty-four loudest rows (crude oil price); "
                "the pattern's own threshold is two",
        "SB-M": "  amplifier on CME palm oil: crude oil price, biodiesel mandate all sit among this "
                "board's loudest rows; the graph records the effect as amplifies",
        "SB-P": "UPSTREAM crude oil -> soybean crush margin -> board crush -> CBOT soybeans: the graph "
                "places crude oil two hops upstream of the CBOT soybeans price",
        "SB-A": "LIKE STATE El Nino on CBOT soybeans: the series sat like this in June 2013; the "
                "record carries seventy-five such crossings since 2022",
        "SB-L": "RECENCY numbers: read as of 2026-09-07; the newest knowledge date on a number row is "
                "2026-09-04",
        "SB-X": "BOARD ABSENCE crude oil on CBOT soybeans: the read returned no rows for this scope at "
                "this as-of.",
        "SB-JOIN": "BOARD JOIN El Nino and La Nina on CBOT soybeans: these are read on ONE series and "
                   "the rows above print the SAME reading under each name. The graph declares them "
                   "opposite signs on this board, which is what two phases of one series means; they "
                   "are not two readings that disagree.",
    }
    missing = sorted(set(R.ROW_CLASSES) - set(samples))
    if missing:
        errs.append("state/lint.py has no sample line for row class(es) %s -- a class with no sample "
                    "is a class whose disjointness nobody graded" % (missing,))
    for name, line in sorted(samples.items()):
        hit = R.classify(line)
        if hit != (name,):
            errs.append("row class %s: its own sample line classifies as %s, not exactly (%r,)"
                        % (name, hit or "no class", name))
    for rx_name, rx in _walk_line_rxs().items():
        for name, line in sorted(samples.items()):
            if rx.search(line):
                errs.append("row class %s's sample line also matches the walk's %s -- the two blocks "
                            "would be indistinguishable to a consumer" % (name, rx_name))
    return errs


def _walk_line_rxs() -> dict:
    """The walk's own rendered-line regexes, imported lazily and skipped (with no error) when the K9
    lane has moved them: a lint that CRASHED on a rename would red the board for a change in a file
    this package does not own."""
    out: dict = {}
    try:
        from leviathan.graphrag.numbers import cascade as casc
        for n in ("CW_CONTEXT_LINE_RX", "CW_FX_LINE_RX"):
            rx = getattr(casc, n, None)
            if rx is not None and hasattr(rx, "search"):
                out[n] = rx
    except Exception:  # noqa: BLE001
        pass
    return out


# ── clause 11 (S3): the narration literals and the calendar's rule kinds ────────────────────────────
def _check_narration_and_calendar() -> list[str]:
    """``narration.check_literals()`` (the mandate and the two recency sentences, bar B15) plus
    ``calendar.check_rule_kinds()`` (every declared rule kind is one the consumer computes)."""
    errs: list[str] = []
    from leviathan.graphrag.state import calendar as CAL
    from leviathan.graphrag.state import narration as NAR
    errs += NAR.check_literals()
    errs += CAL.check_rule_kinds()
    return errs


# ── entry points ─────────────────────────────────────────────────────────────────────────────────────
def check_state_board() -> list[str]:
    """Every S0 clause plus S3's three. Empty list = green. Absorbed by
    ``config_check.check_state_board`` after K9.

    S3 ADDS THREE CLAUSES, each grading a CONTRACT BETWEEN MODULES that prose alone was carrying: every
    closed decline word has a reader sentence (9), the row-class regexes are pairwise disjoint and
    disjoint from the walk's own line classes (10), and the mandate, the two recency sentences and the
    calendar's rule kinds are clean (11)."""
    errs: list[str] = []
    errs += _check_lag_table()
    errs += _check_no_summed_band()
    errs += _check_conventions()
    errs += _check_calendar()
    errs += _check_board_read_rows()
    errs += _check_ym_lag()
    errs += _check_country_ref_pairing()
    errs += _check_nass_states()
    errs += _check_absence_vocabulary()
    errs += _check_row_classes()
    errs += _check_narration_and_calendar()
    return errs


def state_board_warnings(asof: Optional[str] = None) -> list[str]:
    """Non-blocking observations. ``asof`` (ISO) enables the 180-day calendar staleness check; without
    it the check is SKIPPED and says so, because this module reads no clock."""
    warns: list[str] = []
    cards = _registered_cards()
    for tid, ts in sorted(cards.items()):
        if ts.knowledge_semantics == "year_month" and getattr(ts, "ym_publication_lag_days", None) is None:
            warns.append("registry %r is a year_month card with NO ym_publication_lag_days: its data month "
                         "stays citable from its FIRST DAY when the `ym_lag` kwarg arms. Undeclared, named "
                         "here rather than assumed to be zero." % (tid,))
    doc = load_release_calendar()
    for sid, src in (doc.get("sources") or {}).items():
        src = src or {}
        if src.get("verified_against") is None:
            warns.append("release_calendar %r: verified_against is null -- the rule prints WINDOW words "
                         "only and never a print time until it is read off the publisher." % (sid,))
    if asof is None:
        warns.append("release_calendar: the 180-day staleness check was SKIPPED -- this module reads no "
                     "clock; pass asof=YYYY-MM-DD to run it.")
    else:
        try:
            a = _dt.date.fromisoformat(str(asof))
        except ValueError:
            warns.append("release_calendar: asof %r is not an ISO date; staleness check skipped." % (asof,))
            return warns
        for sid, src in (doc.get("sources") or {}).items():
            vo = (src or {}).get("verified_on")
            if not vo:
                continue
            try:
                d = _dt.date.fromisoformat(str(vo))
            except ValueError:
                continue
            if (a - d).days > 180:
                warns.append("release_calendar %r: last verified %s, more than 180 days before %s"
                             % (sid, vo, asof))
    return warns


def main() -> int:
    """ASCII-only stdout by law (the Windows console is cp1252); files stay UTF-8."""
    errs = check_state_board()
    warns = state_board_warnings()
    for w in warns:
        print(("WARN  " + w).encode("ascii", "backslashreplace").decode("ascii"))
    for e in errs:
        print(("ERROR " + e).encode("ascii", "backslashreplace").decode("ascii"))
    print("check_state_board: %d error(s), %d warning(s)" % (len(errs), len(warns)))
    return 1 if errs else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
