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

import ast
import datetime as _dt
import functools
import pathlib
import re
import types as _types
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

    # ── THE WATCH-ONLY OVERLAY (S7b) ────────────────────────────────────────────────────────────────
    # It is graded by exactly the same clauses as `conventions:` -- a ref the estate names, a kind in
    # the enum, bands strictly ascending and unique, labels the same length, a declared window, and
    # every LABEL register-clean. The file's own header records "crowded" / "stretched" failing that
    # last one, which is why it is a clause and not a habit.
    # IT MUST NOT SHADOW A LIVE CONVENTION. An overlay entry for a ref `conventions:` already carries
    # would be a second, unrankable opinion about one series -- and `watch.nonobvious_candidates`
    # merges with the base winning, so the shadow would be dead config that a reader would still
    # believe. The clause makes it a red instead.
    overlay = doc.get("watch_overlay") or {}
    for ref, row in overlay.items():
        row = row or {}
        if ref in convs:
            errs.append("state_conventions watch_overlay %r: the `conventions:` block already declares "
                        "this ref -- the base always wins, so this entry is dead config" % (ref,))
        if ref not in known_refs:
            errs.append("state_conventions watch_overlay %r: not a live cascade_map ref, a board_read "
                        "row, or a DAG silver_ref" % (ref,))
        kind = row.get("kind")
        if kind not in CONVENTION_KINDS:
            errs.append("state_conventions watch_overlay %r: kind %r not in %s"
                        % (ref, kind, list(CONVENTION_KINDS)))
        bands, labels = row.get("bands"), row.get("labels")
        if not isinstance(bands, list) or not bands or not all(isinstance(b, (int, float))
                                                               for b in bands):
            errs.append("state_conventions watch_overlay %r: bands must be a non-empty list of "
                        "numbers, got %r" % (ref, bands))
        elif list(bands) != sorted(bands) or len(set(bands)) != len(bands):
            errs.append("state_conventions watch_overlay %r: bands must be strictly ascending, got %r"
                        % (ref, bands))
        if not isinstance(labels, list) or (isinstance(bands, list) and len(labels or []) != len(bands)):
            errs.append("state_conventions watch_overlay %r: len(labels) must equal len(bands) "
                        "(%r vs %r)" % (ref, labels, bands))
        if row.get("history_window_key") not in windows:
            errs.append("state_conventions watch_overlay %r: history_window_key %r is not a declared "
                        "window" % (ref, row.get("history_window_key")))
        for lbl in (labels or []):
            hits = _register_hits(str(lbl))
            if hits:
                errs.append("state_conventions watch_overlay %r: label %r is NOT register-safe (%s)"
                            % (ref, lbl, "; ".join(hits)))
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

    # ── S7 polish (b): THE STATE LANE PRINTS ONE SERIES IN ONE UNIT ──────────────────────────────────
    # TWO CLASSES RENDER A FIGURE OF A CARD'S SERIES AND BOTH NOW GO THROUGH `rows.shown_value`: the
    # SB-1 state row (`render._level_words`, via `StateRow.level_shown`) and the SB-O analog outcome
    # (`render.sb_analog_outcome`, given the card's scale by `render._series_scales`). A change scales
    # exactly as a level does, so ONE multiplication serves both and a page cannot carry one series at
    # two magnitudes. THE THIRD CONSUMER IS THE ONE THIS CLAUSE GUARDS, because it is the one the state
    # lane does not own:
    # `render._level_words` now prints ``level * scale`` in the card's ``narrate_unit`` (the SB-1 row),
    # while `watch.convention_distance` compares and prints the NATIVE level -- and `watch.DISTANCE_UNITS`
    # falls back to the row's own ``narrate_unit`` for ``abs_bands`` and for ``abs_bands`` ALONE. So an
    # ``abs_bands`` convention declared on a SCALED card would put one series on the page twice, in two
    # magnitudes, under ONE unit word. MEASURED at this landing: 25 of the 49 declared cards carry
    # ``scale != 1``, 23 refs carry a convention, the intersection is exactly ``mpob_ending_stocks`` and
    # ``psd_ending_stock_su_ratio``, and BOTH are ``percentile_bands`` -- which measures its distance in
    # percentile points and never reads ``narrate_unit``. The estate is clean today; this clause is what
    # makes the day it stops being clean a LINT failure rather than a rendered block.
    _convs = (load_conventions().get("conventions") or {})
    for ref, row in board_map().items():
        row = row or {}
        if float(row.get("scale", 1) or 1) == 1:
            continue
        if str((_convs.get(ref) or {}).get("kind") or "") == "abs_bands":
            errs.append("cascade_map %r: scale=%r with an `abs_bands` convention -- the state row "
                        "prints level*scale in %r while watch.convention_distance prints the NATIVE "
                        "level under the SAME unit word, so one series would reach the reader as two "
                        "magnitudes (S7 polish (b))"
                        % (ref, row.get("scale"), row.get("narrate_unit")))

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
    # S8 LANE N: THE CHAIN VOCABULARY IS SEEDED BY NAME AND NOT ONLY THROUGH ITS LEG. `CHAIN_REASONS`
    # reaches the loop above today because `LEG_REASONS["path"]` IS that tuple (the leg deliberately
    # keeps its old name so no census row changes meaning), so this seeds nothing new and every message
    # above keeps its exact provenance string -- it is seeded AFTER the legs for precisely that reason.
    # It is here as a BELT: the day someone renames the leg key, or renders a chain decline off a leg
    # this loop does not walk, the three words would leave the graded set silently and a reader would
    # meet the fallback line where DESIGN B.3's own count sentence was owed. `getattr` because this
    # clause must not red on a tree where lane W's constant has not landed.
    for w in getattr(B, "CHAIN_REASONS", ()) or ():
        seen.setdefault(w, "board.CHAIN_REASONS")
    # 09-24 (CONTRACT K5): THE ANALOG OUTCOME ROW'S OWN DECLINE WORDS, declared at their one producer
    # (``analogs.OUTCOME_DECLINES``) and seeded by name like ``CHAIN_REASONS`` -- a word the render prints
    # as an SB-X absence is graded here in both directions whoever declares it.
    from leviathan.graphrag.state import analogs as _AN
    for w in getattr(_AN, "OUTCOME_DECLINES", ()) or ():
        seen.setdefault(w, "analogs.OUTCOME_DECLINES")
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
    samples = _row_class_samples()
    _check_samples_shape(samples, errs, R)
    return errs


def _row_class_samples() -> dict:
    """THE ONE SAMPLE LINE PER ROW CLASS, each taken VERBATIM off the render (see
    :func:`_check_row_classes` for why the samples are the spec). A module-level producer since the 09-23
    fix round because TWO clauses read them now: disjointness (clause 10) and the desk-register ratchet
    (clause 17)."""
    return {
        "SB-H": "STATE OF THE WORLD at 2026-09-07 for CBOT soybeans: two drivers read on their own "
                "series, one carried as dated receipts; ordered by how far each reading sits from its "
                "own history.",
        # SB-1 IS RE-BANKED ON THE 09-23 ROW IDENTITY (CONTRACT.md C1): the head names the SERIES (the
        # card's declared reading words and the period at its own precision) and the driver rides once
        # as "read here for". Verbatim off the soybeans fixture's first state row, sigma and tag kept.
        # ...AND RE-BANKED ON THE 09-24 FIGURE TOKEN (CONTRACT K2): the period rides the FIGURE the writer
        # copies ("+0.98 degC, August 2026"), and the head names the series once.
        "SB-1": "- [N1] the tropical Pacific sea-surface temperature anomaly, on CBOT soybeans (NOAA "
                "ONI), read here for El Nino: +0.98 degC, August 2026; [N2] +1.2 sigma on its "
                "trailing window of one hundred twenty months [series: CBOT soybeans; table: NOAA ONI]",
        "SB-V": "- [N7] WATCH the level a convention names El Nino on CBOT soybeans: 0.52 degC "
                "under the strong line at 1.5 degC -- 2026-08-31",
        "SB-T": "- [N9] CBOT soybeans front 2026-11 settle on 2026-09-04: 1085.08 USc/bu",
        # SB-O IS RE-BANKED ON THE 09-23 DESK VOCABULARY: the chain outcome's own class spelling ("over the
        # band declared from that state") and the band's two ends said as WHEN the lag opened and closed.
        # ...AND ON THE 09-24 CHANGE ROW (CONTRACT K5): a change carries its sign.
        "SB-O": "- [N11] the soybean monthly benchmark over the band declared from that state, one to "
                "two quarters: moved +46.33 USD/t by the time that lag opened; [N12] moved +68.21 USD/t "
                "by the time it closed",
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
        "SB-F": "- El Nino is a shared driver across thirty-four other markets this estate tracks, "
                "declared in the opposite direction on twenty-eight of them (CBOT corn) and in the "
                "same direction on the rest (CME palm oil)",
        "SB-C": "- biodiesel energy-price floor (price-supportive) on CME palm oil: two of the "
                "three conditions it names are showing here (crude oil price); it asks for two, so "
                "the count here is at or past that number",
        "SB-M": "  amplifier on CME palm oil: crude oil price, biodiesel mandate are all among the "
                "largest moves here; the graph records the effect as amplifies",
        "SB-P": "UPSTREAM crude oil -> soybean crush margin -> board crush -> CBOT soybeans: the graph "
                "places crude oil two hops upstream of the CBOT soybeans price",
        # SB-A's SAMPLE IS RE-BANKED ON THE ANALOG RENDER HALF (the sitting that gave the selection's
        # own facts a reader), AND AGAIN ON ITS ROUND-2 RULING. The old sample's "seventy-five such
        # crossings since 2022" paired the relaxed POOL count with the LOUD SET's raw coverage floor;
        # round 1 swapped the count for HEAD's admitted one, which put a number beside a picked date
        # the number does not count (2013-06-30 against a three-member set beginning 2023-12-31), and
        # left a THIRD year in the reach clause. What this class renders now is the RANKED POOL the
        # pick is a member of, the head-admitted count as a separately named second number, and ONE
        # year for "how far back these dimensions see" (``render.analog_count_floor``,
        # ``max(first_date)`` over ``record_span``) in both clauses that print it. Taken VERBATIM off
        # the served soybeans deep stanza.
        # ...AND RE-BANKED ONCE MORE ON THE 09-23 DESK VOCABULARY (CONTRACT.md C13): "compared with it" for
        # the instrument's "ranked beside it", and the head-admitted count said as the like states that are
        # readable on every dimension -- the same two numbers, the same one floor year.
        "SB-A": "LIKE STATE El Nino on CBOT soybeans: the series sat like this in June 2013; one "
                "hundred fifty-nine past readings on this series could be compared with it, this one "
                "the nearest; three of them are like states, the ones readable on every dimension "
                "since 2023; like on two of the three dimensions compared with it, which together "
                "reach back to 2023; the one it could not read there counts as a full sigma apart; the "
                "state agreed in sign on two of the two a sigma could be read on; the path into it "
                "agreed on zero of the two a direction could be read on; this date precedes the record "
                "of one of the dimensions compared with it",
        # SB-L's sample carried the RETIRED wording (review round 3): "the newest knowledge date on a
        # number row is ..." is the phrasing `narration.recency_rows` replaced in pre-arm round 1 --
        # the block's only source of `knowledge date` and of three `row` charges on the served bodies,
        # and the wording the desk-register mandate beside it now bans. The sample is what the class
        # ACTUALLY renders, taken verbatim off `soybeans_now`.
        "SB-L": "RECENCY numbers: read as of 2026-09-07; the newest number here is known 2026-09-04 "
                "and the oldest 2025-12-31",
        "SB-X": "BOARD ABSENCE crude oil on CBOT soybeans: the read returned no rows for this scope at "
                "this as-of.",
        "SB-JOIN": "BOARD JOIN El Nino and La Nina on CBOT soybeans: these are read on ONE series and "
                   "the rows above print the SAME reading under each name. The graph declares them "
                   "opposite signs on this board, which is what two phases of one series means; they "
                   "are not two readings that disagree.",
        # SB-LEAD, the block's own order made visible (ROUND-2 DOCKET item 12).
        "SB-LEAD": "LARGEST MOVE first of three: export pace lag on CBOT soybeans, past the line the "
                   "desk convention calls behind; its figures are on its own state line below.",
        # SB-ASK, the block's HEAD (09-24, CONTRACT K8 / K21): a seat calculator row cited at the seat's own
        # handle, with its figure token.
        "SB-ASK": "ASKED ROW [N11] Malaysian palm oil closing stocks (change over the window): +10289 MT, "
                  "change from January 2026 to August 2026",
    }


def _check_samples_shape(samples: dict, errs: list, R) -> None:
    """Clause 10's body over :func:`_row_class_samples` -- unchanged, only lifted."""
    # ── S7 polish (a): NO RENDERED LINE MAY CARRY AN EMPTY ANCHOR ────────────────────────────────────
    # `month_words` returned "" for the bare-year form a marketing-year card writes, so `_anchor_words`
    # interpolated nothing and the block printed "counted from the run's start in , the effect window
    # ...". MEASURED at 95 lines across the 16 banked census blocks (quick 13, deep 26, max 56). The
    # producer is fixed; this is the pin, asserted on the SAMPLES here and by the deck on the fixtures
    # and the banked blocks.
    _EMPTY_SLOT = (" in ,", " in .", " in ;", "from  ", " in  ", "( )", "()")
    for name, line in sorted(samples.items()):
        for bad in _EMPTY_SLOT:
            if bad in line:
                errs.append("row class %s: its sample line carries an empty interpolation slot (%r) -- "
                            "a fence that deleted half a clause and left the punctuation"
                            % (name, bad))
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


# ── clause 17 (09-23 fix round, lane R): THE DESK REGISTER OF THE BOARD'S OWN ROWS ─────────────────────
#: THE MIGRATED CLASSES (OWNER DECISION 7): the chain rows (every ``chain*`` role but the corpus-quoting
#: receipt row), the analog stanza (SB-A) and the outcome rows (SB-O) are spelled in desk English and are
#: held to ZERO charges on the EXTENDED ``register.DESK_REGISTER_TOKENS`` table. A class key is the row's
#: ROLE for the chain family (the chain rows share SB-P with the UPSTREAM row, which is not migrated) and
#: its regex class otherwise (:func:`desk_class_key`).
DESK_MIGRATED_CLASSES: tuple = ("chain", "SB-A", "SB-O")

#: THE RATCHET (threat R-17): per UNMIGRATED class key, the most extended-table charges ONE rendered
#: fixture block carried at this build -- the three fixture anchors (soybeans, palm, corn) x three tiers,
#: rendered through the serving seam with the chain lit (``scratchpad/fix_round_0923/laneR``). A ceiling
#: may only FALL: a block that exceeds one is a build error naming the class, and the class is migrated in
#: a later round rather than re-based here. A key absent from this map has a ceiling of zero.
#: MEASURED at this build over the eighteen fixture cells (three anchors x three tiers x chain on/off,
#: ``laneR/CLASS_CENSUS_TREE.json``); the same census at HEAD ee06f19c read chain 25, SB-A 14 and SB-W 4 --
#: the three the owner's rows moved to zero, zero and two.
DESK_REGISTER_CLASS_CEILINGS: dict = {
    "SB-1": 2, "SB-E": 22, "SB-F": 1, "SB-H": 2, "SB-J": 14, "SB-JOIN": 10, "SB-M": 7, "SB-P": 16,
    "SB-V": 2, "SB-W": 2, "SB-X": 28,
}

#: NO HAND-TYPED SAMPLE OF A MIGRATED ROW IS GRADED HERE (09-23 fix round, the verifier's LEX-2). The first
#: cut banked five chain lines verbatim off one render and graded THOSE -- the author's own case list, which
#: stays green while the live template drifts. The migrated rows are now graded on the RENDER PRODUCER'S OWN
#: OUTPUT: :func:`check_desk_register_migrated` reads a rendered block's manifest (``Block.rows_meta``, one
#: entry per printed row, with its role and line), and the deck renders the fixture boards (three anchors x
#: three tiers, chain lit, the serving seam's own path) and hands it every one.


def desk_class_key(meta: dict) -> str:
    """The ratchet's class key for ONE rendered row (``Block.rows_meta``): ``chain`` for every chain row
    but the receipt (whose quote is corpus prose), the row's regex class otherwise."""
    role = str((meta or {}).get("role") or "")
    if role.startswith("chain") and role != "chain_receipt":
        return "chain"
    return str((meta or {}).get("cls") or "") or "unclassified"


def desk_register_class_census(rows_meta) -> dict:
    """``{class key: extended desk-register charges}`` over ONE rendered block's manifest."""
    from leviathan.graphrag import register as _reg
    out: dict = {}
    for m in (rows_meta or ()):
        k = desk_class_key(m)
        out[k] = out.get(k, 0) + _reg.count_desk_register(str((m or {}).get("line") or ""))
    return out


def check_desk_register_ratchet(census: dict, *, ceilings: Optional[dict] = None) -> list[str]:
    """ONE block's census against the ratchet: a migrated class above zero, or any other class above its
    banked ceiling, is an error naming the class and both numbers."""
    ceil = DESK_REGISTER_CLASS_CEILINGS if ceilings is None else ceilings
    errs: list[str] = []
    for k, n in sorted((census or {}).items()):
        cap = 0 if k in DESK_MIGRATED_CLASSES else int(ceil.get(k, 0))
        if int(n) > cap:
            errs.append("desk register: class %s carries %d charge(s) on one block, above its %s of %d "
                        "-- %s" % (k, int(n), "migrated zero" if k in DESK_MIGRATED_CLASSES else
                                   "banked ceiling", cap,
                                   "the owner-named rows speak desk English" if k in
                                   DESK_MIGRATED_CLASSES else "a ratchet only falls"))
    return errs


def check_desk_register_migrated(rows_meta) -> list[str]:
    """THE MIGRATED ROWS, GRADED ON WHAT THE PRODUCER PRINTED (OWNER DECISION 7, threat R-17; LEX-2): over ONE
    rendered block's manifest, every row of a MIGRATED class key (:data:`DESK_MIGRATED_CLASSES`, read through
    :func:`desk_class_key`) scores ZERO on the EXTENDED desk-register table, and every chain-family row
    classifies exactly as SB-P, the class its role rides. An error names the class, the role and the hits."""
    from leviathan.graphrag import register as _reg
    from leviathan.graphrag.state import render as R
    errs: list[str] = []
    for m in (rows_meta or ()):
        key = desk_class_key(m)
        if key not in DESK_MIGRATED_CLASSES:
            continue
        line = str((m or {}).get("line") or "")
        role = str((m or {}).get("role") or "")
        hits = [w for w, _c in _reg.desk_register_hits(line)]
        if hits:
            errs.append("desk register: a migrated %s row (role %s) carries %s: %r"
                        % (key, role or "-", hits, line[:120]))
        if key == "chain" and R.classify(line) != ("SB-P",):
            errs.append("desk register: a migrated chain row (role %s) classifies as %s, not SB-P: %r"
                        % (role or "-", R.classify(line), line[:120]))
    return errs


def _check_desk_register_classes() -> list[str]:
    """CLAUSE 17 (09-23 fix round, OWNER DECISION 7 / threat R-17): the ratchet's STRUCTURE -- every ceiling
    names a real class key and no migrated class carries one. THE ROWS THEMSELVES ARE GRADED ON THE RENDER
    PRODUCER'S OUTPUT, never on a sample typed here (LEX-2): :func:`check_desk_register_ratchet` over
    :func:`desk_register_class_census` and :func:`check_desk_register_migrated`, both over a rendered block's
    manifest -- the deck renders the fixture boards and runs them on every cell, because a build clause cannot
    afford a board render and a banked line is the author's own case list."""
    from leviathan.graphrag.state import render as R
    errs: list[str] = []
    known = set(R.ROW_CLASSES) | {"chain", "unclassified"}
    for k in sorted(DESK_REGISTER_CLASS_CEILINGS):
        if k not in known:
            errs.append("desk register: ceiling for %r names no row class" % (k,))
        if k in DESK_MIGRATED_CLASSES:
            errs.append("desk register: migrated class %r may not carry a ceiling" % (k,))
    for k in DESK_MIGRATED_CLASSES:
        if k not in known:
            errs.append("desk register: migrated class %r names no row class" % (k,))
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


# -- clause 15 (S8 lane N): NO CHAIN LINT DELETES ---------------------------------------------------
#: THE FOUR COUNTERS ``answer._chain_lints`` ACTUALLY RETURNS, read off the shipped function and not
#: declared beside it. The counter is the right key and the function name is not: the counter is what
#: the arm report reads (threat E2 -- "the counter `chain_unranked_narrated` is read in the arm
#: report"), so it is the name that cannot change without a census row changing meaning, while a
#: private function may be renamed freely by the lane that owns it.
#:
#: ROUND 3 ADDS THE FOURTH. ``chain_hops_ambiguous`` (round 2, review MAJOR A-2) counts the hops that
#: HAD a served figure and were REFUSED it because the sentence names another anchor of a multi-anchor
#: page -- the one counter that records a refusal, and the one counter no build graded.
#: ``tests/unit/test_state_lint.py`` reads all four off ``_chain_lints``'s own tree, so this tuple can
#: never drift from the function again.
#:
#: ``chain_referenced`` IS NOT ONE OF THEM AND MAY NOT BE ADDED (round-2b review MAJOR 4). It is a
#: COVERAGE counter, produced by ``render.board_coverage`` over the block's own chain rows -- how many
#: RENDERED chains the writer's prose reached -- while these four are produced by the correcting pass
#: over the writer's SENTENCES. One census name over two populations is the failure this estate keeps
#: paying for, so the name is spelled where it lives and nowhere else.
#: ROUND 4 ADDS THE FIFTH, AND IT LANDED PRODUCER FIRST. ``chain_fence_closed`` counts the
#: corrections this pass WITHHELD because an instrument it reads could not be read -- a figure not
#: appended because the market fence returned nothing, an L3 stamp not made because the pool came back
#: empty. It is the FAIL-CLOSED counter, and a withholding that is counted is the opposite of a
#: withholding that is silent: "fail-open is the opposite of the doctrine", and a dropped item is
#: COUNTED. Lane A shipped it inside ``_chain_lints`` on this sitting; the roster row follows IN THE
#: SAME COMMIT, which is the rule this tuple was written under -- a counter in the function and not in
#: this tuple is a census column no build grades, and the round-3 pin that reads the roster off the
#: function's own tree is what made the drift visible the moment it happened.
CHAIN_LINT_COUNTERS: tuple = ("chain_hops_unfigured", "chain_hops_skipped",
                              "chain_unranked_narrated", "chain_hops_ambiguous",
                              "chain_fence_closed")
#: The collection methods that REMOVE. A correcting fence may call none of them ON THE SERVED TEXT: the
#: doctrine is "fences CORRECT or COMPUTE, never delete", and the estate has paid for the other reading
#: twice this month -- the citation verifier deleted five sentences on five real 2026-09-16 turns, and
#: the S7b advice cut deleted readings on the first 149 fresh sentences it met. A lint that drops a
#: sentence it cannot check has not corrected the page; it has removed the reader's evidence that
#: anything was wrong.
_CHAIN_LINT_REMOVERS: tuple = ("remove", "pop", "clear", "discard", "popitem")
#: The two calls that ERASE a span when their replacement is the empty string.
_CHAIN_BLANKING_CALLS: tuple = ("replace", "sub", "subn")
#: THE PROBE THE EXECUTED LAW RUNS ON (round 3). Ordinary served prose in the two fields the shipped
#: pass writes, four sentences each, every one of them a sentence a chain lint has a reason to touch --
#: a probe a lint cannot fire on proves nothing, so :func:`chain_append_only_report` returns what it
#: CHANGED beside what it charged and the decks assert on both.
CHAIN_APPEND_PROBE: dict = {
    "tldr": ("Palm stocks sit near the top of their own record and the export hop is the one to "
             "watch. The same hop runs into soybean oil within the quarter. A third sentence names "
             "no hop at all and must survive untouched. Rain in the producing states is the hop "
             "behind both."),
    "mechanism": ("The shipment hop moves first and the crush hop follows it. A sentence with no "
                  "hop in it sits between them. The stocks hop closes the sequence; the reader is "
                  "owed every one of these sentences back."),
}


@functools.lru_cache(maxsize=1)
def _answer_source() -> str:
    """``answer.py``'s TEXT, read by path and never imported.

    THE SOURCE JOIN IS THE POINT (``test_k9_stop_census.py``'s own idiom, which asserts
    ``"def _g1x_sans(" in walk`` over the file's text). This module is imported by a lint, by decks that
    render nothing and by ``config_check``; importing the serving answer module to grade three functions
    inside it would drag a provider stack, a boto session and every registry loader into a config check,
    and would make a build failure in one of them look like a lint failure here."""
    try:
        return (pathlib.Path(__file__).resolve().parents[1] / "answer.py").read_text(encoding="utf-8")
    except Exception:                                   # noqa: BLE001 -- an unreadable file is a SKIP
        return ""                                       #   (the warning names it), never a red build


def _chain_stores(node) -> set:
    """The counter names this function STORES -- half of the producer join.

    A STORE is one of exactly two shapes, and both are shapes the shipped reference, lane A's
    ``_chain_lints`` and every one of the review's deletion cases actually write:

      * the constant subscript of an assignment or an augmented assignment TARGET
        (``census["chain_hops_skipped"] += 1``), and
      * a key of a dict LITERAL bound to a name -- the census initialiser
        (``census = {"chain_hops_skipped": 0, ...}``), which is what keeps the "never increments its
        own counter" rule able to fire at all: a function whose increments were deleted still declares
        the counter it owes. It is also the only way two of the four counters are visible at all in
        ``_chain_lints``, which raises them through a VARIABLE key (``census[counter] += weight``).

    A name that appears only inside a tuple, a call argument or a subscript being READ is NOT a store.
    STORING A COUNTER IS NOT ON ITS OWN ENOUGH TO BE GRADED: threat E2 says the arm report READS these
    names, and a report row is written as a dict literal and an f-string. What decides is
    :func:`_chain_served_writes` -- whether the function puts SERVED TEXT BACK."""
    import ast
    out: set = set()
    for n in ast.walk(node):
        targets = []
        if isinstance(n, ast.Assign):
            targets = list(n.targets)
            if isinstance(n.value, ast.Dict):
                out |= {k.value for k in n.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        elif isinstance(n, ast.AugAssign):
            targets = [n.target]
        for t in targets:
            if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                    and isinstance(t.slice.value, str)):
                out.add(t.slice.value)
    return out


def _bound_names(target) -> set:
    """The plain NAMES an assignment or a ``for`` binds -- never the base of a subscript.

    ``structured[field] = ...`` binds nothing: it WRITES. ``for field, text in ...`` binds both."""
    import ast
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        out: set = set()
        for e in target.elts:
            out |= _bound_names(e)
        return out
    return set()


def _chain_served_taint(node) -> dict:
    """``{parameter: every local name carrying something read out of it}`` -- the data-flow half.

    A chain lint is handed the writer's own ``structured`` dict and reads the served text out of it
    (``structured.get(field)``, ``(structured or {}).items()``, ``structured[field]``), splits it,
    walks the pieces and puts them back. THAT ROUND TRIP is what makes a function a producer of served
    text, and following it is what tells a PRODUCER from a READER without asking either to be spelled a
    particular way: the arm-report reader derives its values from the CENSUS and writes them into a
    RECORD, and no name it writes carries anything it read out of the thing it is writing into.

    The walk is a FIXPOINT over assignments and ``for`` targets: a name whose value mentions the
    parameter, or any name already derived from it, is derived from it too, until a pass adds nothing
    (a cap of twelve, which no ordinary lint's chain of intermediates comes near, and the loop leaves
    early). It is deliberately COARSE in the permissive direction -- it can call a name derived when it
    is only adjacent, and the cost of that is a removal rule reaching one name further, never a served
    write being missed."""
    import ast
    a = node.args
    params = [x.arg for x in list(getattr(a, "posonlyargs", [])) + list(a.args) + list(a.kwonlyargs)]
    if a.vararg:
        params.append(a.vararg.arg)
    if a.kwarg:
        params.append(a.kwarg.arg)
    taint = {p: {p} for p in params}
    body = list(ast.walk(node))
    for _ in range(12):
        grew = False
        for n in body:
            if isinstance(n, ast.Assign):
                bound: set = set()
                for t in n.targets:
                    bound |= _bound_names(t)
                src = n.value
            elif isinstance(n, (ast.For, ast.AsyncFor)):
                bound = _bound_names(n.target)
                src = n.iter
            elif isinstance(n, ast.withitem) and n.optional_vars is not None:
                bound = _bound_names(n.optional_vars)
                src = n.context_expr
            else:
                continue
            if not bound:
                continue
            mentioned = {x.id for x in ast.walk(src) if isinstance(x, ast.Name)}
            for p, names in taint.items():
                if mentioned & names and not bound <= names:
                    names |= bound
                    grew = True
        if not grew:
            break
    return taint


def _chain_counter_buckets(node) -> set:
    """``{(base name, constant key)}`` -- every slot this function fills with a BUCKET OF COUNTERS.

    A bucket is a dict LITERAL, bound to a constant subscript of a name, whose keys are all
    :data:`CHAIN_LINT_COUNTERS` and at least one of them: ``report["chain"] = {"chain_hops_skipped":
    0, "chain_hops_unfigured": 0}``. That is the shape an arm-report rollup writes before it fills the
    bucket and totals it, and reading it back is reading counters, never the reader's sentences. The
    ALL clause is what keeps this narrow: a served field is never assigned a literal made only of
    counter names, so no page can be mistaken for a bucket."""
    import ast
    out: set = set()
    for n in ast.walk(node):
        if not (isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict) and n.value.keys):
            continue
        keys = [k.value for k in n.value.keys if isinstance(k, ast.Constant)]
        if len(keys) != len(n.value.keys) or not set(keys) <= set(CHAIN_LINT_COUNTERS):
            continue
        for t in n.targets:
            if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                    and isinstance(t.slice, ast.Constant)):
                out.add((t.value.id, t.slice.value))
    return out


def _chain_counter_raised(node, counter: str) -> bool:
    """Does this function RAISE ``counter`` -- not merely DECLARE it? (round-4 review MAJOR 1.)

    THE RULE IS GRADED PER COUNTER because the number the arm report reads is per counter. Round 3
    asked only whether the function carried ANY ``+=`` anywhere, which the shipped
    ``answer._chain_lints`` satisfies with ``clause += ...`` on a LOCAL STRING: measured by surgery on
    the shipped source (``r2c/rev3/REV3_N_adv3.json``), a ``_chain_lints`` with every one of its five
    counter raises replaced by ``pass`` passed the clause clean and was still named the producer of
    all four. A zero the arm report cannot tell from "nothing happened" is the census-row-with-two-
    meanings failure this estate keeps paying for.

    THREE SPELLINGS COUNT, and each is one the shipped pass or the deck's own reference really writes:

      * ``census["chain_hops_skipped"] += 1`` -- the augmented assignment under the counter's own
        CONSTANT key;
      * ``census["chain_hops_skipped"] = census.get("chain_hops_skipped", 0) + 1`` -- the same number
        off its own previous value, because a clause that knew only the first would charge a
        conforming pass for its punctuation;
      * ``census[counter] += int(weight)`` -- the augmented assignment under a VARIABLE key, over a
        base whose own dict literal DECLARED this counter. ``answer._chain_lints`` raises two of its
        four that way (``chain_hops_skipped`` and ``chain_unranked_narrated``), and it is the only
        reason the loose rule was reached for in the first place."""
    import ast
    declared_by = {n.targets[0].id for n in ast.walk(node)
                   if isinstance(n, ast.Assign) and len(n.targets) == 1
                   and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Dict)
                   and any(isinstance(k, ast.Constant) and k.value == counter for k in n.value.keys)}
    for n in ast.walk(node):
        if isinstance(n, ast.AugAssign):
            t = n.target
            if not (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)):
                continue
            if isinstance(t.slice, ast.Constant):
                if t.slice.value == counter:
                    return True
            elif t.value.id in declared_by:
                return True
        elif isinstance(n, ast.Assign):
            names = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
            for t in n.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and isinstance(t.slice, ast.Constant) and t.slice.value == counter
                        and t.value.id in names):
                    return True
    return False


def _chain_served_writes(node) -> list:
    """Every assignment that PUTS SERVED TEXT BACK -- ``[(written name, parameter, node)]``.

    THE CLASS RULE, and the whole of round 3's answer to three MAJORs at once. A chain lint PRODUCES:
    it assigns into a subscript of the structure it read the served text from -- ``structured[field] =
    "".join(toks)``, or the token list it split out of that field (``toks[i] = sent``), which is the
    same write one level down. A chain lint READER never does: the arm-report assembly threat E2 names
    writes ``rec[counter]`` from ``census[counter]``, and nothing it writes carries anything it read
    out of ``rec``. MEASURED at round 2b (``r2b/rev2/REV2_clause15_readerFP.json``): that reader, in
    the ordinary spelling of a report row -- a dict literal plus an f-string summary -- RED the build
    with six errors, beside the lane's own conforming reference.

    A STORE UNDER A CONSTANT COUNTER KEY IS NEVER A SERVED WRITE. ``census["chain_hops_skipped"] =
    census.get("chain_hops_skipped", 0) + 1`` raises a counter; it does not write a page. That one
    exclusion is what keeps BOTH reader spellings out with no rule about readers at all.

    AND NEITHER IS A READ UNDER ONE (round-4 review MAJOR 2, the same exclusion on the other side of
    the assignment). ``base in reads`` asks "was the written value read out of the structure being
    written into", which is the round trip a producer makes. An arm-report row reads its OWN counters
    back to derive a line -- ``rec["chain_note"] = "%d hops skipped" % rec["chain_hops_skipped"]`` --
    and at round 3 that RED the build TWICE beside the conforming reference, once with the DELETION
    message, on a record holding no sentence at all (``r2c/rev3/REV3_N_adv.json``,
    ``REV3_N_adv2.json``). A counter read back is no more a page than a counter bump is, and a COUNTER
    BUCKET -- a constant key this function bound to a dict literal whose every key is one of
    :data:`CHAIN_LINT_COUNTERS` (``report["chain"] = {"chain_hops_skipped": 0, ...}``) -- is a bucket
    of counters and not a page either; the one-line counter-key exclusion alone left that third
    spelling charged, measured, and it is the rollup every report writes.

    THE RESIDUAL IS DECLARED RATHER THAN LISTED, because a table of spellings is what a later reviewer
    cannot trust: a function that derives a field from a key of its own record that is NEITHER a
    counter NOR a counter bucket IS charged, and a reader written that way must spell the derivation
    off the census it read from rather than off the record it is filling."""
    import ast
    taint = _chain_served_taint(node)
    buckets = _chain_counter_buckets(node)
    out: list = []
    for n in ast.walk(node):
        if isinstance(n, ast.Assign):
            targets = list(n.targets)
        elif isinstance(n, ast.AugAssign):
            targets = [n.target]
        else:
            continue
        mentioned = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
        reads = {x.value.id for x in ast.walk(n.value)
                 if isinstance(x, ast.Subscript) and isinstance(x.value, ast.Name)
                 and not (isinstance(x.slice, ast.Constant)
                          and (x.slice.value in CHAIN_LINT_COUNTERS
                               or (x.value.id, x.slice.value) in buckets))}
        for t in targets:
            if not (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)):
                continue
            if isinstance(t.slice, ast.Constant) and t.slice.value in CHAIN_LINT_COUNTERS:
                continue                                # a counter bump is not a page
            base = t.value.id
            for p, names in taint.items():
                if base not in names:
                    continue
                if (mentioned & (names - {base})) or base in reads:
                    out.append((base, p, n))
                    break
    return out


def _chain_lint_functions(tree, src: str = "") -> dict:
    """``{counter: [(function name, node)]}`` -- every function that PRODUCES one of the counters.

    A function produces a counter when it STORES the counter's exact name (:func:`_chain_stores`) AND
    it writes served text back into the structure it read it from (:func:`_chain_served_writes`). BOTH
    HALVES ARE THE CONTRACT and neither alone is:

      * the name AS A STRING CONSTANT and nothing more is what a comment or a block note carries, and
        lane A writes the note before it writes the function -- a clause that red-flagged the note
        would be a fence firing on its own documentation;
      * the name as a MENTION and nothing more is what the arm report carries. A build gate that reds
        on the conforming implementation of the lane it was written for is a gate that gets deleted,
        which is how the estate lost the T2b write-guard.

    ``src`` is accepted and unused: it is the file's text, which the callers already hold, and the join
    is made on the parsed TREE alone."""
    import ast
    out: dict = {c: [] for c in CHAIN_LINT_COUNTERS}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        stores = _chain_stores(node)
        if not (stores & set(CHAIN_LINT_COUNTERS)) or not _chain_served_writes(node):
            continue
        for c in CHAIN_LINT_COUNTERS:
            if c in stores:
                out[c].append((node.name, node))
    return out


# -- THE LAW ITSELF, EXECUTED ------------------------------------------------------------------------
#: A sentence boundary, spelled as ``register._SENT_KEEP`` spells it. It is repeated here rather than
#: imported because this module is read by ``config_check`` and by decks that render nothing.
_CHAIN_PROBE_SENT = re.compile(r"([.!?;]\s+)")


def _append_only_charges(name: str, before: dict, after: dict) -> list:
    """APPEND-ONLY, CHARACTER FOR CHARACTER, on one before/after pair.

    Two readings of one law, because a page can be damaged two ways:

      * EVERY CHARACTER THE WRITER WROTE IS STILL THERE, IN ORDER -- the served text before the pass is
        a SUBSEQUENCE of the served text after it. An append inserts; a deletion removes; and the
        subsequence test does not care WHERE the clause was inserted, which matters because the shipped
        idiom appends INSIDE the sentence, in front of its terminator, so a plain prefix test would
        charge the one shape every conforming lint in this estate uses.
      * EVERY CLAUSE IS STILL A CLAUSE -- each sentence's body, sans its terminator, split at the estate's
        ONE clause grammar (``verify._SEGMENT_BREAK``: a list comma, a semicolon, a colon, a dash -- the
        breaks the citation binding reads), is still a contiguous run of each clause. A pass that kept
        every character but scattered one clause through the others has taken it off the page just as
        surely. FIXER PASS (REVIEW_RA lexical 11 / m4, the integrator's F-12): this reading was "every
        SENTENCE whole", which K16's clause-end L1 append breaks BY DESIGN (the served reading lands at the
        end of the CLAUSE that names its hop); the law is restated at the grain K16 keeps, so the shipped
        grader and the placement rule agree and no deck filters the grader's charges by their message.

    The charge NAMES THE FIRST CHARACTER THAT WENT MISSING, because "a sentence was deleted" is a
    verdict and an offset is evidence."""
    errs: list = []
    for field, old in sorted(before.items()):
        new = after.get(field)
        if not isinstance(new, str):
            errs.append("%s hands back %r as %s and not as text -- the reader's own sentences left "
                        "the page in the shape they were served in" % (name, field, type(new).__name__))
            continue
        if not isinstance(old, str):
            continue
        i = 0
        for ch in new:
            if i < len(old) and ch == old[i]:
                i += 1
        if i < len(old):
            errs.append("%s loses served text in %r: character %d of the writer's own sentence (%r) "
                        "is not in what the reader is handed back -- the law is APPEND-ONLY"
                        % (name, field, i, old[max(0, i - 30):i + 30]))
        try:
            from leviathan.graphrag.verify import _SEGMENT_BREAK as _clause_break
        except Exception:                               # noqa: BLE001 -- no clause grammar: the sentence grain
            _clause_break = None
        for k, sent in enumerate(_CHAIN_PROBE_SENT.split(old)):
            if k % 2 or not sent.strip():
                continue
            body = sent.strip().rstrip(".;!?").strip()
            parts = ([c.strip() for c in _clause_break.split(body)] if _clause_break is not None else [body])
            for clause in parts:
                if clause and clause not in new:
                    errs.append("%s no longer carries the clause %r whole in %r -- a clause broken "
                                "apart is a clause the reader lost" % (name, clause[:60], field))
        if len(new) < len(old):
            errs.append("%s SHORTENS %r (%d characters to %d); an appending pass never shortens"
                        % (name, field, len(old), len(new)))
    return errs


def chain_append_only_report(fn, *args, probe: Optional[dict] = None, **kwargs) -> dict:
    """RUN a chain lint on a known structured dict and GRADE WHAT IT DID -- the append-only law.

    ``{"errors": [...], "changed": [fields], "raised": None or the exception's class name,
    "before": {...}, "after": {...}}``.

    THIS IS THE LAW AND THE SOURCE CLAUSE IS THE BELT, and round 3 turned them around for a measured
    reason. A roster of deletion SHAPES is a roster: at round 2 it charged two conforming APPENDING
    lints (a filtered list joined onto the full text) and it stopped grading a lint that deletes IN
    PLACE and writes the field back as the list it is, because no string was built. Both were found by
    one-edit variants of the lane's own reference. What a FIXTURE answers is neither of those
    questions but the only one that matters: run it, and see whether the reader still has every
    character the writer wrote.

    IT GRADES IDEMPOTENCE THE SAME WAY, by running the pass TWICE. That rule used to be graded as a
    SHAPE (``if <clause> in <sentence>: continue``), which charged the conforming spelling
    ``if clause not in sent:`` for the guard it plainly has; run twice, a pass that appends a second
    clause is charged and a pass that appends nothing is not, whichever way it is written.

    ``fn`` is called as ``fn(box, *args, **kwargs)`` with ``box`` a fresh copy of :data:`CHAIN_APPEND_PROBE`
    (or of ``probe``). A raised exception is reported rather than swallowed: the shipped pass declares
    that it never raises, and a fixture is where that is cheap to check."""
    box = dict(probe if probe is not None else CHAIN_APPEND_PROBE)
    before = dict(box)
    name = getattr(fn, "__name__", "the chain lint")
    out: dict = {"errors": [], "changed": [], "raised": None, "before": before, "after": box}
    try:
        fn(box, *args, **kwargs)
    except Exception as exc:                            # noqa: BLE001 -- named, never re-raised
        out["raised"] = type(exc).__name__
        out["errors"].append("%s raised %s on the append-only probe; a correcting pass over the "
                             "writer's own sentences never raises" % (name, type(exc).__name__))
        return out
    out["after"] = dict(box)
    out["changed"] = sorted(f for f, v in before.items() if box.get(f) != v)
    out["errors"] += _append_only_charges(name, before, box)
    once = dict(box)
    try:
        fn(box, *args, **kwargs)
    except Exception as exc:                            # noqa: BLE001
        out["raised"] = type(exc).__name__
        out["errors"].append("%s raised %s on its SECOND run; a correcting pass that cannot be run "
                             "twice cannot be run at all" % (name, type(exc).__name__))
        return out
    for field, v in sorted(once.items()):
        if box.get(field) != v:
            out["errors"].append("%s is NOT IDEMPOTENT in %r: a second run changes the page again, "
                                 "and a pass that grows the page every time it runs is a deletion's "
                                 "mirror image" % (name, field))
    return out


def _chain_deletion_shapes(node, served: set) -> list:
    """THE BELT: the removals a source can see WITHOUT a fixture, scoped to the SERVED TEXT.

    Each rule below charges only when the thing removed is the served structure itself or a name this
    function derived from it (:func:`_chain_served_taint`) -- a ``.pop()`` off a local options dict is
    nobody's deletion. What is NOT here is as deliberate as what is: the round-2 rule that charged ANY
    filtered list put back into the served text is narrowed to the review's own remedy -- a filtered
    re-join is charged only when the name the comprehension FILTERED OVER is absent from the written
    value, so ``"".join(keep)`` is a rebuild and ``"".join(toks) + ", ".join(named)`` is an append.

    THE BELT DECIDES NOTHING THE LAW DECIDES. :func:`chain_append_only_report` runs the pass and reads
    the page; this reaches the shapes that are a deletion however the fixture falls."""
    import ast
    out: list = []
    filtered: dict = {}
    for n in ast.walk(node):
        if not (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)):
            continue
        v = n.value
        if isinstance(v, (ast.ListComp, ast.SetComp, ast.GeneratorExp)) and any(
                g.ifs for g in v.generators):
            filtered[n.targets[0].id] = {x.id for g in v.generators
                                         for x in ast.walk(g.iter) if isinstance(x, ast.Name)}
        elif isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "filter":
            filtered[n.targets[0].id] = {x.id for a in v.args
                                         for x in ast.walk(a) if isinstance(x, ast.Name)}
    for n in ast.walk(node):
        if isinstance(n, ast.Delete):
            for t in n.targets:
                base = t.value if isinstance(t, (ast.Subscript, ast.Attribute)) else t
                if isinstance(base, ast.Name) and base.id in served:
                    out.append("carries a `del` over the served text (%s) -- a chain lint CORRECTS or "
                               "COMPUTES and never deletes (DESIGN B.6, ruling R2)" % (base.id,))
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in _CHAIN_LINT_REMOVERS
                and isinstance(n.func.value, ast.Name) and n.func.value.id in served):
            out.append("calls %s.%s() on the served text -- a removing method inside a fence whose "
                       "whole contract is that the sentence survives" % (n.func.value.id, n.func.attr))
        if not isinstance(n, ast.Assign):
            continue
        names = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
        blanking = any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                       and x.func.attr in _CHAIN_BLANKING_CALLS
                       and any(isinstance(a, ast.Constant) and a.value == "" for a in x.args)
                       for x in ast.walk(n.value))
        empty = (isinstance(n.value, (ast.List, ast.Tuple, ast.Set)) and not n.value.elts
                 or isinstance(n.value, ast.Dict) and not n.value.keys
                 or isinstance(n.value, ast.Constant) and n.value.value == "")
        for t in n.targets:
            if not (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                    and t.value.id in served):
                continue
            if isinstance(t.slice, ast.Slice) and empty:
                out.append("assigns an EMPTY collection into a slice of the served text -- a deletion "
                           "spelled as an assignment is still a deletion")
            elif empty:
                out.append("blanks a slot of the served text with the empty string -- a deletion "
                           "spelled as an assignment is still a deletion")
            if blanking:
                out.append("writes back a span ERASED with an empty replacement -- an erase spelled "
                           "as a rewrite still takes the reader's sentence off the page")
            back = sorted(f for f in (names & set(filtered)) if not (filtered[f] & names))
            if back:
                out.append("rebuilds the served text from a FILTERED copy (%s) with the list it "
                           "filtered nowhere in the written value -- a sentence the comprehension's "
                           "`if` did not keep is a sentence deleted" % (", ".join(back),))
    seen: set = set()
    return [t for t in out if not (t in seen or seen.add(t))]


#: The state modules clause 16 grades. The list is the package's own serving surface -- every module
#: that could see an analog row between the selection and the page -- and it is read BY PATH, never
#: imported, for :func:`_answer_source`' reason: this module is imported by ``config_check`` and by
#: decks that render nothing.
_ANALOG_ROW_MODULES: tuple = ("render.py", "analogs.py", "walk.py", "watch.py", "board.py",
                              "seam.py", "narration.py")

#: The ONE spelling of the selection flag clause 16 follows. There is no second name for it anywhere
#: in the package, which is what makes a source join over it meaningful at all.
_NEAR_ASOF = "near_asof"


@functools.lru_cache(maxsize=None)
def _state_source(name: str) -> str:
    """One state module's TEXT, read by path and never imported (see :func:`_answer_source`)."""
    try:
        return (pathlib.Path(__file__).resolve().parent / name).read_text(encoding="utf-8")
    except Exception:                                   # noqa: BLE001 -- an unreadable file is a SKIP
        return ""


def _mentions_near(node) -> bool:
    """Does this node reference the flag, under either spelling a Python source can carry it in --
    a NAME (``pick["near_asof"]`` unpacked into a local) or the STRING KEY itself?"""
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id == _NEAR_ASOF:
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == _NEAR_ASOF:
            return True
        if isinstance(n, ast.Attribute) and n.attr == _NEAR_ASOF:
            return True
    return False


#: What a FILTER looks like in a source, as the five shapes a reviewer can see with no fixture: the
#: statements that make a row STOP EXISTING for the reader below them.
_DROPPING = (ast.Continue, ast.Break, ast.Delete, ast.Return, ast.Raise)


def _near_filter_shapes(node, where: str) -> list[str]:
    """Every place this function lets ``near_asof`` REMOVE a row rather than DESCRIBE one."""
    errs: list[str] = []
    for n in ast.walk(node):
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for gen in n.generators:
                for test in (gen.ifs or ()):
                    if _mentions_near(test):
                        errs.append("%s filters a comprehension on `%s` -- the flag DESCRIBES the "
                                    "picked date and may never remove it (fences correct or compute, "
                                    "never delete)" % (where, _NEAR_ASOF))
        elif isinstance(n, ast.If) and _mentions_near(n.test):
            for stmt in ast.walk(n):
                if isinstance(stmt, _DROPPING) and stmt is not n:
                    errs.append("%s branches on `%s` and then %s -- a row the selection PICKED is "
                                "removed on a flag whose whole job is to qualify it"
                                % (where, _NEAR_ASOF, type(stmt).__name__.lower()))
                    break
        elif isinstance(n, ast.Call):
            fn = n.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in ("remove", "pop", "discard", "filter") and _mentions_near(n):
                errs.append("%s calls %s() on `%s` -- the flag may not take a row off the page"
                            % (where, name, _NEAR_ASOF))
    return errs


def _check_analog_near_asof() -> list[str]:
    """CLAUSE 16. The analog header READS ``near_asof``, and no module in this package FILTERS on it.

    **WHY IT IS A SOURCE CLAUSE AND NOT A PER-TURN ONE, STATED BECAUSE THE DESIGN ASKED FOR THE OTHER.**
    DESIGN C.4 asks for "a lint that asserts the chosen date is not within ``min_separation_months`` of
    the as-of". This module grades CONFIGS AND SOURCE -- its other fifteen clauses read YAML and
    ``answer.py``'s AST and not one of them has ever seen a rendered turn -- and the design's own
    sentence is, on inspection, a FENCE THAT DELETES: it would have a lint remove a stanza the
    selection picked. Doctrine is the other way round (fences correct or compute, never delete), and
    ``analogs.select_analogs``' own note already says it: "``near_asof`` IS A FLAG AND NEVER A FILTER:
    the selection states it and the render half grades it." So the bar splits in two. The RENDER half
    appends the distance in months (``render.analog_selection_clauses``) and the stanza stays. This
    clause grades the two halves of that contract that a source can actually answer for.

    **THE STATE IT WAS WRITTEN AGAINST IS MEASURED, NOT ASSUMED.** ``near_asof`` was live and silent:
    on the served fixture board ``attached_event`` at deep renders a stanza picked 2026-01-31 against
    an as-of of 2026-09-07 and ``attached_event`` at max's top stanza picks 2025-12-31 -- seven and
    nine months, both flagged True by the selection, both rendered, and the word ``near_asof``
    appeared NOWHERE in ``render.py``, ``watch.py``, ``lint.py``, ``narration.py`` or ``board.py``. A
    reader was shown the present state described as its own precedent with nothing saying so.

    WHAT IT DOES NOT GRADE: whether the MONTHS are right. That is arithmetic over two dates and it has
    one producer (``analogs.select_analogs`` stores ``months_to_asof`` off the same
    ``_months_between`` call that mints the flag, so the figure and the flag can never disagree); it is
    pinned by execution in ``tests/unit/test_state_analogs.py`` and ``tests/unit/test_state_render.py``,
    on rows rather than on a source.

    IT SKIPS HONESTLY. An unreadable or unparsable module returns clean for that module rather than
    reddening a build on a file it could not open -- the same discipline clause 15 keeps."""
    errs: list[str] = []
    src = _state_source("render.py")
    if not src:
        return errs                                     # unreadable: a SKIP, never a red build
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return ["state/lint.py clause 16: state/render.py does not parse (%s)" % (exc,)]
    readers = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _mentions_near(n)}
    if not readers:
        errs.append("state/render.py reads `%s` nowhere -- the selection flags a like date inside the "
                    "separation window of the as-of and the page says nothing about it" % (_NEAR_ASOF,))
    else:
        # AND THE READER HAS TO BE ON THE HEADER'S OWN PATH. A read in a function nothing calls is a
        # field with a reference and still no reader, which is the exact state this clause exists to
        # end -- so the clause joins the reader to `sb_analog_header` by the call the header makes.
        head = next((n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "sb_analog_header"), None)
        if head is None:
            errs.append("state/render.py declares no `sb_analog_header` -- the analog header this "
                        "clause grades is gone")
        else:
            called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
                      for c in ast.walk(head) if isinstance(c, ast.Call)}
            if "sb_analog_header" not in readers and not (readers & called):
                errs.append("state/render.py reads `%s` only in %s, which `sb_analog_header` does not "
                            "call -- the flag has a reference and still no reader on the page"
                            % (_NEAR_ASOF, ", ".join(sorted(readers))))
    for name in _ANALOG_ROW_MODULES:
        s = _state_source(name)
        if not s or _NEAR_ASOF not in s:
            continue
        try:
            t = ast.parse(s)
        except SyntaxError:
            continue                                    # a module that will not parse is not this
        for n in ast.walk(t):                           #   clause's failure to report
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _mentions_near(n):
                errs += _near_filter_shapes(n, "state/%s %s()" % (name, n.name))
    return errs


def _check_chain_lints_append_only() -> list[str]:
    """CLAUSE 15. Every chain lint DESIGN B.6 declares only ever APPENDS -- it never deletes.

    WHO IT GRADES, and round 3 made this a CLASS instead of a list of spellings: a chain lint is a
    function that stores one of :data:`CHAIN_LINT_COUNTERS` AND writes served text back into the
    structure it read that text from (:func:`_chain_served_writes`). A function that only READS the
    counters -- the arm-report assembly threat E2 names -- writes nothing back and is not graded, in
    ANY of the six ordinary spellings measured (a tuple of names with ``rec[k] = int(census[k])``; a
    dict literal with an f-string summary line; constant keys into a record it was handed; a note
    DERIVED off that record; a nested rollup with a total; and a row that drops its own line when the
    counter is zero -- the last three re-opened this at round 3 and are closed by the read-side
    exclusions in :func:`_chain_served_writes`). A function that deletes IN PLACE and writes the field back
    as the LIST it is (``del toks[i]`` ... ``structured[field] = toks``) IS graded, and was not at
    round 2 because it built no string.

    WHAT IT GRADES HERE, on those functions: the removals a source can see with no fixture at all
    (:func:`_chain_deletion_shapes` -- a ``del`` or a removing method over the served text, a slot
    blanked, a slice taking an empty collection, a span erased with an empty replacement, a filtered
    rebuild that left the list it filtered out of the written value), and that a function declaring a
    counter actually RAISES THAT COUNTER (:func:`_chain_counter_raised`), so the number the arm report
    reads is produced rather than only named. ROUND 4 MADE THAT SECOND RULE PER COUNTER: round 3 asked
    whether the function carried any augmented assignment at all, and a ``_chain_lints`` with every one
    of its five counter raises replaced by ``pass`` passed clean while still being named the producer
    of all four (surgery on the shipped source, ``r2c/rev3/REV3_N_adv3.json``).

    WHAT IT DOES NOT GRADE HERE, stated because the claim a docstring makes is the thing a later
    reviewer trusts: THE LAW ITSELF. Append-only is a property of what the pass DOES to a page, and it
    is graded by EXECUTION -- :func:`chain_append_only_report` runs the pass on a known structured dict
    and reads back whether every character the writer wrote is still there, whether every sentence is
    still whole and whether a second run changes anything. It runs in ``tests/unit/test_state_lint.py``
    -- on the lane's conforming reference, on every deletion shape the review measured, on both reader
    spellings, and on the five 2026-09-16 served bodies, which are UNSEEN real-seat prose and not this
    fence's own case list. Beside it ``tests/unit/test_chain_lints.py`` measures the SHIPPED pass
    against a real board on those same five bodies, with its own assertions. IT CANNOT RUN HERE:
    this module is imported by ``config_check`` and by decks that render nothing, importing the serving
    answer module to grade one function inside it would drag a provider stack and every registry loader
    into a config check, and the shipped pass needs a real board before it can fire at all -- a build
    lint that fabricated one would be grading its own fixture.

    IT SKIPS HONESTLY AND SAYS SO. Until a counter has a producer, this clause returns clean and
    :func:`state_board_warnings` NAMES the counter -- a lint that RED the board for a file another lane
    has not written yet would be a fence charging for work in progress."""
    import ast
    errs: list[str] = []
    src = _answer_source()
    if not src or not any(c in src for c in CHAIN_LINT_COUNTERS):
        return errs                                     # lane A has not landed; the warning names it
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:                          # a file that does not parse is a real defect
        return ["state/lint.py clause 15: answer.py does not parse (%s); the chain lints cannot be "
                "graded for the append-only law" % (exc,)]
    for counter, fns in sorted(_chain_lint_functions(tree, src).items()):
        for name, node in fns:
            where = "answer.%s (the %s lint)" % (name, counter)
            taint = _chain_served_taint(node)
            served: set = set()
            for _base, p, _n in _chain_served_writes(node):
                served |= taint.get(p, set())
            errs += [where + " " + t for t in _chain_deletion_shapes(node, served)]
            # THE COUNTER IS RAISED, AND IT IS THIS COUNTER (:func:`_chain_counter_raised`). Round 3
            # asked whether the function carried ANY `+=`, which `clause += ...` on a local string
            # answers -- so a pass that declared four counters and raised none passed clean. The
            # number the arm report reads is per counter, so the rule is graded per counter.
            if not _chain_counter_raised(node, counter):
                errs.append("%s never increments its own counter; the arm report reads %s and a "
                            "counter nothing raises reads zero for free" % (where, counter))
    return errs


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
    """Every S0 clause plus S3's three plus S7b's one -- TWELVE. Empty list = green. Absorbed by
    ``config_check.check_state_board`` after K9.

    S3 ADDS THREE CLAUSES, each grading a CONTRACT BETWEEN MODULES that prose alone was carrying: every
    closed decline word has a reader sentence (9), the row-class regexes are pairwise disjoint and
    disjoint from the walk's own line classes (10), and the mandate, the two recency sentences and the
    calendar's rule kinds are clean (11).

    S7b ADDS THE TWELFTH, :func:`_check_nonobvious_watch` -- the non-obvious watch vocabulary, its
    ceilings and the owner's 2026-09-11 release-calendar ban, graded on the closed KIND map. It is
    named here because `config_check.check_state_board`'s docstring is where a reviewer looks to answer
    "is the calendar ban enforced at build", and a roster that stops at eleven answers no.

    THE ROSTER IS SIXTEEN TODAY and the sentence above is kept rather than renumbered, because each
    clause is named by the sitting that added it: lane D's two reader-word books are 13 and 14, and S8
    lane N adds the FIFTEENTH, :func:`_check_chain_lints_append_only` -- the append-only law over
    DESIGN B.6's three chain lints, graded on ``answer.py``'s SOURCE and SKIPPED, loudly, until they
    land. It is named here for the same reason the twelfth is: a reviewer asking "can a chain lint
    delete a sentence" reads this docstring, and a roster that stops at fourteen answers nothing.

    THE ANALOG RENDER LANE ADDS THE SIXTEENTH, :func:`_check_analog_near_asof` -- DESIGN C.4's bar, in
    the only shape a source clause can carry it: the analog header READS the flag the selection stamps
    on a like date sitting inside the separation window of the as-of, and no module in this package
    FILTERS a picked row on it. A reviewer asking "can a stanza be removed for being too recent" reads
    this docstring, and the answer is no: the header says how many months and the stanza stays.

    THE 09-23 FIX ROUND ADDS THE SEVENTEENTH, :func:`_check_desk_register_classes` -- the desk register
    of the board's OWN rows (OWNER DECISION 7): the owner-named classes held to zero on the extended
    table, every other class under a banked ceiling that may only fall. The build clause grades the
    ratchet's STRUCTURE; the rows are graded on the render producer's own output over the fixture boards
    (:func:`check_desk_register_migrated`, :func:`check_desk_register_ratchet`), never on a typed sample.

    ``config_check.check_state_board`` only DELEGATES here, so a sixteenth clause needs no edit there.
    (Its own docstring still says "twelve"; that was already stale against fifteen and is not this
    lane's file.)"""
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
    errs += _check_nonobvious_watch()
    errs += _check_reading_words()
    errs += _check_phase_pairs()
    errs += _check_chain_lints_append_only()
    errs += _check_analog_near_asof()
    errs += _check_desk_register_classes()
    return errs


# -- clauses 13 and 14 (lane D, 2026-09-17): the two declared reader-word books ---------------------
def _check_reading_words() -> list[str]:
    """CLAUSE 13. ``state_conventions.reading_words`` is COMPLETE over the board map, register-clean,
    and carries no storage token.

    IT FAILS CLOSED ON COMPLETENESS BECAUSE THE PRODUCER FAILS SOFT. ``render.reading_words`` returns
    the empty string for an undeclared metric and the SB-1 clause is then not printed at all -- which
    is exactly what keeps the S7 revert's failure mode unreachable, and exactly why a missing entry
    would otherwise be invisible: the block would simply stop saying what a number is, on the one card
    somebody forgot. The board map is 47 refs over 39 distinct (table, metric) pairs, so the table is
    small enough to be complete and the completeness is the check.

    NO DIGIT AND NO UNDERSCORE. A storage column wearing reader spacing ("exports mt", "su ratio",
    "brent crude usd bbl zscore 5yr") is the defect this book replaces, and a numeral in a phrase that
    lands on a FIGURE class would be a magnitude with no handle behind it."""
    errs: list[str] = []
    doc = load_conventions()
    book = doc.get("reading_words")
    if not isinstance(book, dict) or not book:
        return ["state_conventions.yaml: `reading_words` is missing or empty -- every state line would "
                "stop saying what its number is"]
    for key, words in sorted(book.items()):
        k = str(key)
        if k.count(".") < 1:
            errs.append("reading_words %r is not a `<table>.<metric>` key" % (k,))
        w = str(words or "")
        if not w.strip():
            errs.append("reading_words %r has no words" % (k,))
            continue
        if any(ch.isdigit() for ch in w) or "_" in w:
            errs.append("reading_words %r carries a digit or an underscore (%r) -- a storage token "
                        "wearing reader spacing is what this book replaces" % (k, w))
        if any(ord(ch) > 127 for ch in w):
            errs.append("reading_words %r is not ASCII (%r)" % (k, w))
        hits = _register_hits(w)
        if hits:
            errs.append("reading_words %r is not register-clean: %s" % (k, "; ".join(hits)))
    # COMPLETENESS over the board map's own (table, metric) pairs
    try:
        from leviathan.graphrag.state.feeders import board_map as _bm
        rows = _bm()
    except Exception:                                   # noqa: BLE001 -- S0 ordering: fall back to ours
        rows = board_map()
    missing = sorted({(str((r or {}).get("table") or ""), str((r or {}).get("metric") or ""))
                      for r in rows.values()
                      if (str((r or {}).get("table") or "") + "." + str((r or {}).get("metric") or ""))
                      not in book
                      and (str((r or {}).get("table") or "") + ".*") not in book})
    for t, m in missing:
        if not t and not m:
            continue
        errs.append("reading_words has no entry for %r -- `render.reading_words` fails soft, so the "
                    "block would silently stop naming what that number is" % (f"{t}.{m}",))
    return errs


def _check_phase_pairs() -> list[str]:
    """CLAUSE 14. Every ``phase_pairs`` entry names a ``conventions:`` row that exists, is
    ``abs_bands`` and declares at least one band -- because the THRESHOLD is that row's first band and
    is never re-typed beside the pair. Its two sides name DIFFERENT drivers and carry ASCII,
    register-clean, digit-free words.

    The book may be EMPTY (nothing declares a phase and the join renders exactly as it did at HEAD);
    what it may not be is INCONSISTENT with the band table the SB-1 row above it prints from."""
    errs: list[str] = []
    doc = load_conventions()
    pairs = doc.get("phase_pairs") or {}
    if not isinstance(pairs, dict):
        return ["state_conventions.yaml: `phase_pairs` is not a mapping"]
    convs = doc.get("conventions") or {}
    for key, ent in sorted(pairs.items()):
        ent = ent or {}
        cname = str(ent.get("convention") or "")
        conv = convs.get(cname)
        if not conv:
            errs.append("phase_pairs %r names convention %r, which this file does not declare"
                        % (str(key), cname))
        elif str(conv.get("kind")) != "abs_bands" or not (conv.get("bands") or []):
            errs.append("phase_pairs %r names convention %r, which is not an `abs_bands` row with a "
                        "band -- the phase threshold IS that row's first band" % (str(key), cname))
        sides = [(side, ent.get(side) or {}) for side in ("positive", "negative")]
        for side, val in sides:
            if not str(val.get("driver") or "").strip():
                errs.append("phase_pairs %r/%s names no driver" % (str(key), side))
            w = str(val.get("words") or "")
            if not w.strip():
                errs.append("phase_pairs %r/%s has no words" % (str(key), side))
                continue
            if any(ch.isdigit() for ch in w) or any(ord(c) > 127 for c in w):
                errs.append("phase_pairs %r/%s words %r carry a digit or non-ASCII -- SB-JOIN is "
                            "letters-only" % (str(key), side, w))
            hits = _register_hits(w)
            if hits:
                errs.append("phase_pairs %r/%s words are not register-clean: %s"
                            % (str(key), side, "; ".join(hits)))
        if (str((ent.get("positive") or {}).get("driver") or "")
                == str((ent.get("negative") or {}).get("driver") or "")):
            errs.append("phase_pairs %r names ONE driver on both sides -- a phase pair is two names"
                        % (str(key),))
    return errs


# ── clause 12 (S7b): the non-obvious watch vocabulary, its bans and its ceilings ─────────────────────
def _check_nonobvious_watch() -> list[str]:
    """The 09-11 watch ruling's own contracts, graded on the CODE rather than argued about in prose.

    THE CALENDAR BAN IS THE CLAUSE THAT MATTERS and it is keyed on the CLOSED MAP rather than on a
    regex. "Never release-calendar items" cannot be enforced by banning the word "report" -- every
    SB-W row ends in an ISO date by design and the expiry kind prints two, so a regex over
    ``report|release|print|scheduled`` would strike honest rows. The ban is: no non-obvious kind is a
    calendar kind, and no non-obvious kind's WORDS come from ``calendar.KIND_WORDS`` /
    ``calendar.RULE_WORDS``, whose eleven-of-thirty DECLINED release forms ("the venue calendar is not
    read here, so no day is named") are then covered by construction."""
    errs: list[str] = []
    from leviathan.graphrag.state import calendar as CAL
    from leviathan.graphrag.state import watch as WA

    # THE COVERAGE IS A SUPERSET CHECK BECAUSE A KIND MAY CARRY VARIANT SENTENCES (review round 3),
    # and the variants are graded as their own clause below -- every key here is still a phrase a
    # reader meets, and every one is graded for calendar vocabulary, register and ASCII by the loop.
    _missing = set(WA.NONOBVIOUS_KINDS) - set(WA.NONOBVIOUS_KIND_WORDS)
    if _missing:
        errs.append("watch.NONOBVIOUS_KIND_WORDS %r does not cover watch.NONOBVIOUS_KINDS %r -- a kind "
                    "with no words renders a code token to a reader"
                    % (sorted(WA.NONOBVIOUS_KIND_WORDS), list(WA.NONOBVIOUS_KINDS)))
    _stray = (set(WA.NONOBVIOUS_KIND_WORDS) - set(WA.NONOBVIOUS_KINDS)
              - set(getattr(WA, "NONOBVIOUS_VARIANTS", {}) or {}))
    if _stray:
        errs.append("watch.NONOBVIOUS_KIND_WORDS carries %r, which is neither a kind nor a declared "
                    "variant" % (sorted(_stray),))
    overlap = set(WA.NONOBVIOUS_KINDS) & set(WA.WATCH_KINDS)
    if overlap:
        errs.append("watch: %r is declared as BOTH a shipped watch kind and a non-obvious kind -- the "
                    "non-obvious list REPLACES the shipped one and a shared name makes the two "
                    "indistinguishable on the trace" % (sorted(overlap),))
    cal_words = {str(w).lower() for w in
                 (list(CAL.KIND_WORDS.values()) + list(CAL.RULE_WORDS.values()))}
    for kind, words in sorted(WA.NONOBVIOUS_KIND_WORDS.items()):
        low = str(words).lower()
        if low in cal_words or any(low in cw for cw in cal_words):
            errs.append("watch.NONOBVIOUS_KIND_WORDS[%r] = %r is release-calendar vocabulary; the "
                        "09-11 ruling bans a calendar item as a watch item outright" % (kind, words))
        for bad in ("met", "fires", "the regime is"):
            if bad in low.split() or (" " in bad and bad in low):
                errs.append("watch.NONOBVIOUS_KIND_WORDS[%r] carries %r -- walk.CONVERGENCE_BANNED_WORDS "
                            "bars it on a row that narrates a declared pattern" % (kind, bad))
        hits = _register_hits(str(words))
        if hits:
            errs.append("watch.NONOBVIOUS_KIND_WORDS[%r] is NOT register-safe (%s)"
                        % (kind, "; ".join(hits)))
        if not str(words).isascii():
            errs.append("watch.NONOBVIOUS_KIND_WORDS[%r] is not ASCII" % (kind,))
    if "next_release" in WA.NONOBVIOUS_KINDS:
        errs.append("watch.NONOBVIOUS_KINDS declares `next_release` -- a scheduled print is banned as a "
                    "nominated item and rides the one-line footnote instead")
    want = {"quick": 3, "deep": 5, "max": 7}
    if dict(WA.WATCH_NONOBVIOUS_K) != want:
        errs.append("watch.WATCH_NONOBVIOUS_K %r != the owner's 2026-09-11 ceilings %r"
                    % (dict(WA.WATCH_NONOBVIOUS_K), want))
    if dict(WA.WATCH_RENDER_K) != {"quick": 3, "deep": 6, "max": 8}:
        errs.append("watch.WATCH_RENDER_K moved to %r -- it is the SHIPPED cap, it is pinned against "
                    "reasoning_modes' knob table by two decks, and the non-obvious ceiling is a "
                    "SEPARATE constant" % (dict(WA.WATCH_RENDER_K),))
    # THE RANK IS THE 09-11 RULING'S SEVEN TERMS IN THE RULING'S ORDER, and the ORDER is what this
    # grades: the first cut declared eight with T_NOVELTY leading, which demoted T_AMPLIFIER behind a
    # term the ruling names as a measurement clause rather than a rank position. Novelty is the
    # tie-break and is graded as one.
    want_terms = ("T_AMPLIFIER", "T_NONLINEAR", "T_TAIL", "T_RUN", "T_PATHS", "T_BREADTH", "T_WINDOW")
    if tuple(WA.RANK_TERMS) != want_terms:
        errs.append("watch.RANK_TERMS is %r; the 09-11 ruling's order is %r"
                    % (tuple(WA.RANK_TERMS), want_terms))
    # THE RULING'S NAMES AND THE STAMPED KEYS ARE TWO LISTS (review round 3, minor). `T_PATHS` is the
    # ruling's one word for the pair the record stamps as `T_PATHS_DEPTH` / `T_PATHS_N`, so indexing
    # `cand['terms']` by RANK_TERMS is a KeyError; RANK_TERM_KEYS is the set that is safe to index and
    # it is graded against what `rank_terms` actually stamps rather than against a comment.
    _stamped = set(WA.rank_terms({"kind": "tail_reading"}, frozenset()))
    if set(getattr(WA, "RANK_TERM_KEYS", ())) != _stamped:
        errs.append("watch.RANK_TERM_KEYS %r is not the key set watch.rank_terms stamps %r"
                    % (sorted(getattr(WA, "RANK_TERM_KEYS", ())), sorted(_stamped)))
    for _name in tuple(WA.RANK_TERMS):
        if _name not in _stamped and _name != "T_PATHS":
            errs.append("watch.RANK_TERMS names %r, which watch.rank_terms does not stamp and which is "
                        "not the declared T_PATHS pair -- a reader indexing the record by this tuple "
                        "would raise" % (_name,))
    if tuple(WA.RANK_TIEBREAK)[:1] != ("T_NOVELTY",):
        errs.append("watch.RANK_TIEBREAK %r does not lead with T_NOVELTY -- the ruling computes novelty "
                    "on the rendered sentence and places the eight terms above ahead of it"
                    % (tuple(WA.RANK_TIEBREAK),))
    # THE TUPLE ITSELF, not only the declaration: a rank_key whose first element is not T_AMPLIFIER is
    # the defect this clause exists to catch, and a comment cannot be graded.
    _hi = {"terms": {"T_AMPLIFIER": 0, "T_NONLINEAR": 3, "T_NOVELTY": 0}, "driver_id": "", "kind": ""}
    _lo = {"terms": {"T_AMPLIFIER": 2, "T_NONLINEAR": 0, "T_NOVELTY": 99}, "driver_id": "", "kind": ""}
    if not WA.rank_key(_hi) < WA.rank_key(_lo):
        errs.append("watch.rank_key does not sort T_AMPLIFIER ahead of T_NONLINEAR and T_NOVELTY -- "
                    "the 09-11 rank order is not the one the tuple implements")
    # ── T_AMPLIFIER'S VALUE DOMAIN (review round 2, MAJOR 3) ─────────────────────────────────────────
    # THE TERM LEADS THE TUPLE AND SORTS ASCENDING, so a value the ruling does not name is not a
    # rounding error -- it is a rank. The shipped term carried a FOURTH value (3, "in no pattern at
    # all"), which put membership of an UNMET pattern ahead of past-the-line, the tail, the run and
    # path depth on every board. This clause grades the domain itself: exactly the three levels the
    # ruling names, a no-pattern row landing on the neutral one, and the tuple's own default agreeing
    # with it. A fourth value can come back only by naming itself here first.
    want_levels = {"met_with_amplifier": 0, "met": 1, "neutral": 2}
    if dict(getattr(WA, "AMPLIFIER_LEVELS", {})) != want_levels:
        errs.append("watch.AMPLIFIER_LEVELS is %r; the 09-11 ruling names exactly three levels %r -- a "
                    "pattern at its threshold with a declared amplifier line, a pattern at its "
                    "threshold, and neutral (a pattern SHORT of its threshold and no pattern at all "
                    "are the same statement about asymmetry)"
                    % (dict(getattr(WA, "AMPLIFIER_LEVELS", {})), want_levels))
    else:
        _none = WA._pattern_facts(None, None, ())
        if int(_none.get("rank")) != want_levels["neutral"]:
            errs.append("watch._pattern_facts returns rank %r for a row in NO declared pattern; the "
                        "term's leading position makes that a rank ahead of every other term -- it "
                        "must be AMPLIFIER_LEVELS['neutral'] (%d)"
                        % (_none.get("rank"), want_levels["neutral"]))
        _default = WA.rank_key({"terms": {}, "driver_id": "", "kind": ""})[0]
        if int(_default) != want_levels["neutral"]:
            errs.append("watch.rank_key defaults T_AMPLIFIER to %r rather than the neutral level %d -- "
                        "a candidate with no stamped term would sort behind an unmet pattern"
                        % (_default, want_levels["neutral"]))
    # ── THE TAIL SENTENCE MAY NOT ASSERT A LINE FACT IT HAS NOT READ (review round 2, MAJOR 1) ───────
    # The body ended unconditionally "no desk line is declared for this series" on a kind that fires for
    # every decile row whose floor is not `past_a_declared_line` -- which includes every one of the
    # fifteen overlay refs (their bands are [10, 90] and TAIL_DECILE is 10.0, so clearing `record_tail`
    # IS crossing the overlay's own line). The clause is now chosen from the row's fact, and the four
    # choices are graded here so a future edit cannot fold them back into the body.
    _tail_body = str(WA.NONOBVIOUS_BODIES.get("tail_reading") or "")
    if "no desk line is declared" in _tail_body:
        errs.append("watch.NONOBVIOUS_BODIES['tail_reading'] asserts `no desk line is declared` in the "
                    "BODY -- the kind fires on rows whose ref DOES carry a declared line, so the clause "
                    "has to be chosen from watch._declared_line and the crossed line NAMED")
    if "{line}" not in _tail_body:
        errs.append("watch.NONOBVIOUS_BODIES['tail_reading'] has no {line} slot -- the line fact is a "
                    "property of the row and cannot be a fixed sentence")
    for _c in ("tail_no_line", "tail_past_line", "tail_line_uncrossed", "tail_line_unplaced"):
        if _c not in WA.NONOBVIOUS_CLAUSES:
            errs.append("watch.NONOBVIOUS_CLAUSES is missing %r -- the tail sentence's line fact is "
                        "tri-state plus the no-line case, and every state needs its own sentence"
                        % (_c,))
    if "{label}" not in str(WA.NONOBVIOUS_CLAUSES.get("tail_past_line") or ""):
        errs.append("watch.NONOBVIOUS_CLAUSES['tail_past_line'] does not NAME the crossed line")
    # ── A LINE FROM THIS LANE'S OWN BOOK SAYS SO (review round 3, minor) ─────────────────────────────
    # Every `watch_overlay` entry is `percentile_bands [10, 90]` against a TAIL_DECILE of 10.0, so a
    # tail row whose line comes from the overlay has crossed that line BY CONSTRUCTION -- 180 of the 196
    # past-the-line tail sentences on the 108-seat replay. The served clause reads as a second,
    # independent desk fact; the overlay's own must name its book and disclose the arithmetic.
    _ov = str(WA.NONOBVIOUS_CLAUSES.get("tail_past_overlay_line") or "")
    if not _ov:
        errs.append("watch.NONOBVIOUS_CLAUSES has no `tail_past_overlay_line` -- a line taken from the "
                    "watch-only overlay would be narrated as a served desk line")
    else:
        if "{label}" not in _ov:
            errs.append("watch.NONOBVIOUS_CLAUSES['tail_past_overlay_line'] does not NAME the band")
        if "watch book" not in _ov:
            errs.append("watch.NONOBVIOUS_CLAUSES['tail_past_overlay_line'] does not name the BOOK the "
                        "line came from, which is the whole correction")
        if "the desk convention calls" in _ov:
            errs.append("watch.NONOBVIOUS_CLAUSES['tail_past_overlay_line'] calls this lane's own "
                        "overlay a desk convention")
        if "same decile" not in _ov:
            errs.append("watch.NONOBVIOUS_CLAUSES['tail_past_overlay_line'] does not disclose that the "
                        "overlay band and the tail are one measurement")
    # THE THRESHOLD-ONE PATTERN IS NOT A CONVERGENCE, and the body has to be able to say so.
    if "{alone}" not in str(WA.NONOBVIOUS_BODIES.get("convergence_amplified") or ""):
        errs.append("watch.NONOBVIOUS_BODIES['convergence_amplified'] has no {alone} slot -- a pattern "
                    "whose declared threshold is ONE is satisfied by a single driver and may not be "
                    "narrated in the same words as a three-driver pattern at its threshold")
    _one = str(WA.NONOBVIOUS_CLAUSES.get("threshold_one") or "")
    if not _one or "on its own" not in _one:
        errs.append("watch.NONOBVIOUS_CLAUSES['threshold_one'] does not say that one reading satisfies "
                    "the threshold on its own")
    for _bad in ("met", "fires", "regime is"):
        if _bad in _one.lower().split() or (" " in _bad and _bad in _one.lower()):
            errs.append("watch.NONOBVIOUS_CLAUSES['threshold_one'] carries %r -- "
                        "walk.CONVERGENCE_BANNED_WORDS bars it on a pattern sentence" % (_bad,))
    # ── A KIND'S VARIANT SENTENCES ARE DECLARED, COMPLETE, AND NOT KINDS (review round 3, MAJOR 1) ───
    # A variant owns four reader-facing strings and nothing else. It may never enter NONOBVIOUS_KINDS
    # (the draw's per-kind cap, `T_NONLINEAR` and the trace all key on the kind), it may never be
    # missing one of the four (a KeyError inside a render, or a sentence introduced by another
    # sentence's words), and it may never be a body no builder can reach.
    _variants = dict(getattr(WA, "NONOBVIOUS_VARIANTS", {}) or {})
    for _v, _parent in sorted(_variants.items()):
        if _parent not in WA.NONOBVIOUS_KINDS:
            errs.append("watch.NONOBVIOUS_VARIANTS[%r] = %r is not a non-obvious kind" % (_v, _parent))
        if _v in WA.NONOBVIOUS_KINDS:
            errs.append("watch.NONOBVIOUS_VARIANTS declares %r, which is ALSO a non-obvious kind -- a "
                        "variant is a second sentence of one kind and never an eighth kind" % (_v,))
        for _map, _name in ((WA.NONOBVIOUS_BODIES, "NONOBVIOUS_BODIES"),
                            (WA.NONOBVIOUS_KIND_WORDS, "NONOBVIOUS_KIND_WORDS"),
                            (WA.NONOBVIOUS_MECHANISMS, "NONOBVIOUS_MECHANISMS"),
                            (WA.NONOBVIOUS_FALSIFIERS, "NONOBVIOUS_FALSIFIERS")):
            if _v not in _map:
                errs.append("watch.%s has no entry for the declared variant %r" % (_name, _v))
    _bodies = set(WA.NONOBVIOUS_BODIES) - set(WA.NONOBVIOUS_KINDS) - set(_variants)
    if _bodies:
        errs.append("watch.NONOBVIOUS_BODIES carries %r, which is neither a kind nor a declared "
                    "variant -- an unreachable sentence is a sentence nothing grades"
                    % (sorted(_bodies),))
    # ── THE RUN-DIRECTION CLAIM IS TESTED, NOT ASSERTED (review round 3, MAJOR 1) ────────────────────
    # `approaching_line` says "its run points at it" and the builder gated on the run's LENGTH: 10 of
    # 42 drawn rows on the 144 banked seats ran AWAY from the line they named, 10 of 10 in a core slot.
    # The three sentences, the function that chooses between them, the floor clause that made the same
    # mistake in the other direction, and the rank credit are all graded here.
    _appr = str(WA.NONOBVIOUS_BODIES.get("approaching_line") or "")
    _away = str(WA.NONOBVIOUS_BODIES.get("approaching_line_away") or "")
    _unpl = str(WA.NONOBVIOUS_BODIES.get("approaching_line_unplaced") or "")
    if "points at it" not in _appr:
        errs.append("watch.NONOBVIOUS_BODIES['approaching_line'] no longer makes the run claim the "
                    "09-11 ruling's kind rests on")
    if "points AWAY from it" not in _away:
        errs.append("watch.NONOBVIOUS_BODIES['approaching_line_away'] does not say the run points AWAY "
                    "from the line it names -- which is the whole correction")
    if "cannot place its run" not in _unpl:
        errs.append("watch.NONOBVIOUS_BODIES['approaching_line_unplaced'] does not say that the run "
                    "cannot be placed against the line")
    for _k, _t in (("approaching_line_away", _away), ("approaching_line_unplaced", _unpl)):
        if "points at it" in _t:
            errs.append("watch.NONOBVIOUS_BODIES[%r] still asserts that the run points AT the line"
                        % (_k,))
    if "running at" in str(WA.NONOBVIOUS_KIND_WORDS.get("approaching_line_away") or ""):
        errs.append("watch.NONOBVIOUS_KIND_WORDS['approaching_line_away'] introduces the row as one "
                    "RUNNING AT the line its own sentence says it runs away from")
    # THE FUNCTION ITSELF, on the two shapes the census reproduced.
    if WA._run_with_the_line("percentile_bands", 25.0, 20.1, "up") is not False:
        errs.append("watch._run_with_the_line calls a RISING run on a reading at the 20.1st percentile "
                    "a move further past a `tight` line at the 25th -- a band under 50 is a LOW line")
    if WA._run_with_the_line("percentile_bands", 25.0, 20.1, "down") is not True:
        errs.append("watch._run_with_the_line does not credit a FALLING run under a low percentile line")
    if WA._run_with_the_line("z_bands", 1.5, -0.617, "up") is not False:
        errs.append("watch._run_with_the_line calls a RISING run on a NEGATIVE z a move toward a "
                    "magnitude band -- a magnitude line's side is the reading's own sign")
    if WA._run_with_the_line("z_bands", 1.5, None, "up") is not None:
        errs.append("watch._run_with_the_line decides a magnitude band with NO signed reading -- an "
                    "unplaceable run is a third state and may not be guessed")
    # THE FLOOR CLAUSE, on the row the census drew (ICE arabica stocks-to-use, 20.1st percentile, past
    # a `tight` line at the 25th, RISING): a run pointing back at the line is not "still going deeper".
    _st = _types.SimpleNamespace(
        convention={"kind": "percentile_bands", "band": 25.0, "label": "tight", "matched": True,
                    "reading": 20.1}, z=None, percentile={"value": 20.1, "declined": None},
        run={"length": 2, "direction": "up", "declined": None}, level=None)
    _row = _types.SimpleNamespace(state=_st, driver_id="d", contract="c", sign="+")
    if "past_a_declared_line" in WA._floor_of(_row):
        errs.append("watch._floor_of admits `past_a_declared_line` for a reading RISING out of a low "
                    "percentile band -- the floor's own words are `and the run is still going deeper`")
    _st.run = {"length": 2, "direction": "down", "declined": None}
    if "past_a_declared_line" not in WA._floor_of(_row):
        errs.append("watch._floor_of refuses `past_a_declared_line` for a reading FALLING further "
                    "under a low percentile band -- the convex state the 09-11 ruling names first")
    # THE RANK CREDIT.
    if WA.rank_terms({"kind": "approaching_line", "run_n": 4, "run_toward": False}, frozenset())["T_RUN"]:
        errs.append("watch.rank_terms credits T_RUN to a run MEASURED to point away from the line the "
                    "sentence names -- the 09-15 ruling withholds it")
    if WA.rank_terms({"kind": "approaching_line", "run_n": 4, "run_toward": True},
                     frozenset())["T_RUN"] != 4:
        errs.append("watch.rank_terms no longer credits T_RUN to a run pointing at its own line")
    # ── THE SPILLOVER SPLIT MAY NOT FOLD AN AMBIGUOUS EDGE (review round 3, MAJOR 2) ─────────────────
    # `rows.SIGN_WORDS` declares THREE signs and the split had two buckets, so every `0` edge went into
    # one of them: 88 edges narrated "in the same direction" on 11 of 430 drawn rows, against a block
    # whose own edge line calls them "with no committed direction" two lines away.
    _sp = str(WA.NONOBVIOUS_BODIES.get("spillover_reach") or "")
    if "{n_undirected}" not in _sp:
        errs.append("watch.NONOBVIOUS_BODIES['spillover_reach'] has no {n_undirected} slot -- a "
                    "two-way split has to put every declared-ambiguous edge into a direction")
    if "no committed direction" not in _sp:
        errs.append("watch.NONOBVIOUS_BODIES['spillover_reach'] does not carry the estate's own third "
                    "sign word (rows.SIGN_WORDS['0'])")
    _spu = str(WA.NONOBVIOUS_BODIES.get("spillover_reach_unplaced") or "")
    for _slot in ("{n_far}", "{n_directed}", "{n_undirected}"):
        if _slot not in _spu:
            errs.append("watch.NONOBVIOUS_BODIES['spillover_reach_unplaced'] has no %s slot -- its "
                        "arithmetic has to close on the page too" % (_slot,))
    # AND THE PRODUCER, on the two shapes the census reproduced.
    _far = [{"sign": "0", "contract": "x", "confidence": "low", "lag_band": None},
            {"sign": "+", "contract": "y", "confidence": "low", "lag_band": None}]
    _bd = _types.SimpleNamespace(fan=[{"contract": "c", "driver_id": "d", "far": _far}])
    _fa = WA._fan_facts(_bd, _types.SimpleNamespace(contract="c", driver_id="d", sign="+"))
    if _fa["same"] != 1 or _fa["opposite"] != 0 or _fa.get("undirected") != 1:
        errs.append("watch._fan_facts folds a `0` edge into a direction for a SIGNED near row (%r)"
                    % (_fa,))
    _fa0 = WA._fan_facts(_bd, _types.SimpleNamespace(contract="c", driver_id="d", sign="0"))
    if _fa0["same"] or _fa0["opposite"] or _fa0.get("unplaced") != 1 or _fa0.get("near_signed"):
        errs.append("watch._fan_facts places far edges against a near row whose OWN edge carries no "
                    "committed direction (%r)" % (_fa0,))
    for _f in (_fa, _fa0):
        if _f["same"] + _f["opposite"] + int(_f.get("undirected") or 0) + int(_f.get("unplaced") or 0) \
                != _f["n"]:
            errs.append("watch._fan_facts' four counts do not sum to the fan (%r)" % (_f,))
    # ── NO WATCH SENTENCE CARRIES RELEASE-CALENDAR VOCABULARY (review round 3, minor) ────────────────
    # The ban above is graded on the KIND WORDS only; the ruling's words are that a calendar item is
    # never a watch item, and the sentences are where that could come back. The fixed fragments of the
    # calendar's own two maps are the test, taken from those maps rather than from a hand list.
    _cal_frag = set()
    for _phrase in (list(CAL.KIND_WORDS.values()) + list(CAL.RULE_WORDS.values())):
        for _piece in re.split(r"\{[a-z_]+\}", str(_phrase)):
            _piece = _piece.strip().lower()
            if len(_piece) >= 12:
                _cal_frag.add(_piece)
    for _name, _map in (("NONOBVIOUS_BODIES", WA.NONOBVIOUS_BODIES),
                        ("NONOBVIOUS_CLAUSES", WA.NONOBVIOUS_CLAUSES),
                        ("NONOBVIOUS_MECHANISMS", WA.NONOBVIOUS_MECHANISMS),
                        ("NONOBVIOUS_FALSIFIERS", WA.NONOBVIOUS_FALSIFIERS),
                        ("FLOOR_WORDS", WA.FLOOR_WORDS)):
        for _k, _text in sorted(_map.items()):
            _low = str(_text).lower()
            for _frag in sorted(_cal_frag):
                if _frag in _low:
                    errs.append("watch.%s[%r] carries release-calendar vocabulary %r -- the 09-11 "
                                "ruling bans a calendar item as a watch item" % (_name, _k, _frag))
    # ── A FALSIFIER IS A READING THAT TURNS, OF A SERIES THE ROW NAMES (09-24, CONTRACT K14) ──────────────
    # The class rule, graded on the map and never on a phrase list: EVERY falsifier -- every kind and every
    # variant -- carries the ``{series}`` slot the producer fills from the backing row's own identity, so no
    # falsifier can state a fact about the MODEL ("the paths share a single upstream cause ... one route
    # counted twice", served on the 09-24 palm/rape page) that no print could ever show wrong.
    for _k, _f in sorted(WA.NONOBVIOUS_FALSIFIERS.items()):
        if "{series}" not in str(_f):
            errs.append("watch.NONOBVIOUS_FALSIFIERS[%r] names no series ({series} slot) -- a falsifier is "
                        "a reading of a series the row prints, never a fact about the model" % (_k,))
        _probe = str(_f).replace("{series}", "the reading")
        _hits = _register_hits(_probe)
        if _hits:
            errs.append("watch.NONOBVIOUS_FALSIFIERS[%r] is NOT register-safe (%s)"
                        % (_k, "; ".join(_hits)))
    # ── THE FLOOR FACT RIDES THE SENTENCE (review round 2, minor a) ──────────────────────────────────
    if set(WA.FLOOR_WORDS) != set(WA.FLOOR_CLAUSES):
        errs.append("watch.FLOOR_WORDS %r does not cover watch.FLOOR_CLAUSES %r -- a row admitted by a "
                    "clause with no reader words cannot state what admitted it"
                    % (sorted(WA.FLOOR_WORDS), list(WA.FLOOR_CLAUSES)))
    for _k, _clause in sorted(WA.FLOOR_STATED_BY_KIND.items()):
        if _k not in WA.NONOBVIOUS_KINDS:
            errs.append("watch.FLOOR_STATED_BY_KIND names %r, which is not a non-obvious kind" % (_k,))
        if _clause not in WA.FLOOR_CLAUSES:
            errs.append("watch.FLOOR_STATED_BY_KIND[%r] = %r is not an admission-floor clause"
                        % (_k, _clause))
    for _text in list(WA.FLOOR_WORDS.values()):
        hits = _register_hits(_text)
        if hits:
            errs.append("watch.FLOOR_WORDS %r is NOT register-safe (%s)" % (_text, "; ".join(hits)))
    # ── THE CEILING REACHES THE WRITER (review round 2, MAJOR 2) ─────────────────────────────────────
    if "core item" not in WA.WATCH_SELECTION_CLAUSE:
        errs.append("watch.WATCH_SELECTION_CLAUSE does not bind the writer to the block's own CORE "
                    "marks -- a 2N list with no named ceiling is 2N items to the writer")
    # THE NUMBER THE LICENCE NAMES IS A BOUND AND NOT A COUNT (review round 3, minor). 36 of 108
    # replayed seats drew a core SHORTER than the tier's ceiling -- two of seven at Cascade on barley --
    # so a flat "the core is seven items" is false of the very block the writer is holding. Both forms
    # must carry "at most", and both must point the writer at the block's own marks for the true count.
    for _form in (WA.WATCH_SELECTION_CLAUSE, WA.selection_clause("max")):
        if "at most" not in _form:
            errs.append("watch's selection licence states the core size without a bound -- an "
                        "under-filled block makes that sentence false")
        if "how many this list actually drew" not in _form:
            errs.append("watch's selection licence does not point the writer at the block's own core "
                        "marks, which are the only true count of THIS list")
    from leviathan.graphrag.state import render as _RW
    for _mode, _n in sorted(WA.WATCH_NONOBVIOUS_K.items()):
        _c = WA.selection_clause(_mode)
        if _RW.words_for_int(_n) not in _c:
            errs.append("watch.selection_clause(%r) does not name the tier's ceiling %d" % (_mode, _n))
        if "at most %s items" % (_RW.words_for_int(_n),) not in _c:
            errs.append("watch.selection_clause(%r) does not state its ceiling as a BOUND" % (_mode,))
        # AND THE SWAP HAS TO HAVE HAPPENED (review round 3, minor). `selection_clause` is a literal
        # `.replace()` of one exact sentence, so a reworded constant turns it into a no-op -- and the
        # two clauses above pass VACUOUSLY at quick, because the UNREPLACED three-tier sentence already
        # contains "at most three items" inside "at most three items on a Scan". Proved by mutation:
        # `selection_clause -> lambda mode, cap=None: WATCH_SELECTION_CLAUSE` reddened at deep and max
        # and stayed green at quick. The tier's own sentence is what is graded now.
        if _c == WA.WATCH_SELECTION_CLAUSE:
            errs.append("watch.selection_clause(%r) returns the three-tier constant UNCHANGED -- the "
                        "swap is a literal replace and this one matched nothing" % (_mode,))
        if ("The core of this list is at most %s items" % (_RW.words_for_int(_n),)) not in _c:
            errs.append("watch.selection_clause(%r) does not carry the tier's own core sentence -- the "
                        "writer is holding ONE list and the licence has to name ITS bound" % (_mode,))
        if _register_hits(_c) or not _c.isascii():
            errs.append("watch.selection_clause(%r) is not prompt-clean" % (_mode,))
    hits = _register_hits(WA.WATCH_SELECTION_CLAUSE)
    if hits:
        errs.append("watch.WATCH_SELECTION_CLAUSE is NOT register-safe (%s) -- it reaches a prompt"
                    % ("; ".join(hits),))
    if not WA.WATCH_SELECTION_CLAUSE.isascii():
        errs.append("watch.WATCH_SELECTION_CLAUSE is not ASCII")
    from leviathan.graphrag.state import board as B
    from leviathan.graphrag.state import render as _R
    for word in ("watch_floor_unmet", "watch_nothing_further", "watch_core_capped",
                 "release_dates_only"):
        if word not in B.WATCH_REASONS:
            errs.append("board.WATCH_REASONS does not declare %r, which the non-obvious producer "
                        "stamps" % (word,))
        # A CLOSED WORD WITH NO SENTENCE RENDERS THE WORD ITSELF TO A READER, and the partial-fill case
        # is why this clause exists: the first cut reused `watch_floor_unmet`'s sentence under a list
        # that HAD rows, so the two cases need two sentences and both need grading.
        if word not in (_R.ABSENCE_WHY or {}):
            errs.append("render.ABSENCE_WHY has no sentence for %r -- the reason word would render "
                        "raw" % (word,))
    # THE TWO ABSENCE SENTENCES MUST NOT AGREE. One says nothing cleared the bar, the other says
    # nothing FURTHER did; identical text is the contradiction review reproduced.
    if (_R.ABSENCE_WHY or {}).get("watch_floor_unmet") == (_R.ABSENCE_WHY or {}).get(
            "watch_nothing_further"):
        errs.append("render.ABSENCE_WHY gives `watch_floor_unmet` and `watch_nothing_further` the same "
                    "sentence -- a partial fill would then deny the rows printed above it")
    # ── THE CAPPED CORE'S NOTE MAY NOT DENY THE ALTERNATES IT SITS OVER (review round 3, MAJOR) ──────
    # The three watch-list notes are three different facts and need three different sentences; and the
    # capped one, which is the ONLY one that prints on a page carrying alternates, may not make the
    # exhausted note's claim about the admission bar. Measured before the repair: 36 of 108 replayed
    # seats printed "nothing further ... clears the bar this list sets" directly under alternates.
    _capped = str((_R.ABSENCE_WHY or {}).get("watch_core_capped") or "")
    _three = {str((_R.ABSENCE_WHY or {}).get(w) or "")
              for w in ("watch_floor_unmet", "watch_nothing_further", "watch_core_capped")}
    if len(_three) != 3:
        errs.append("render.ABSENCE_WHY does not give the three watch-list notes three distinct "
                    "sentences -- nothing cleared the bar, nothing FURTHER cleared it, and the core "
                    "was bounded by this list's own caps are three facts")
    if "clears the bar" in _capped or "nothing further" in _capped:
        errs.append("render.ABSENCE_WHY['watch_core_capped'] makes the admission-bar claim -- the note "
                    "prints over alternates that cleared that bar, and the caps are what bounded the "
                    "core")
    for _need in ("alternates", "cap"):
        if _need not in _capped:
            errs.append("render.ABSENCE_WHY['watch_core_capped'] does not name %r -- the note has to "
                        "state the true reason and point at the items it holds back" % (_need,))
    # AND THE PRODUCER HAS TO CHOOSE BETWEEN THEM. A partial fill WITH alternates takes the capped word
    # and one WITHOUT takes the exhausted word; graded on the function rather than on its comment.
    if WA.absence_row(partial=True, alternates=True)["reason"] != "watch_core_capped":
        errs.append("watch.absence_row(partial=True, alternates=True) does not stamp "
                    "`watch_core_capped` -- a page offering alternates would deny them")
    if WA.absence_row(partial=True)["reason"] != "watch_nothing_further":
        errs.append("watch.absence_row(partial=True) no longer stamps `watch_nothing_further` for an "
                    "exhausted list")
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
    # S8 LANE N -- CLAUSE 15'S SKIP, STATED OUT LOUD. A clause that grades nothing because the code it
    # grades has not landed is a DECLARED ABSENCE here and never a silence, which is the same law the
    # calendar's own skip obeys three lines down.
    try:
        import ast as _ast
        _src = _answer_source()
        _have = (_chain_lint_functions(_ast.parse(_src), _src) if _src
                 else {c: [] for c in CHAIN_LINT_COUNTERS})
    except Exception:                                   # noqa: BLE001 -- a skip, never a raised warning
        _have = {c: [] for c in CHAIN_LINT_COUNTERS}
    _no_producer = sorted(c for c, fns in _have.items() if not fns)
    if _no_producer:
        warns.append("state/lint.py clause 15 (no chain lint deletes) graded NOTHING for %r: no "
                     "function in answer.py produces those counters yet, so the append-only law is "
                     "UNENFORCED for them. It is a SKIP and not a pass." % (_no_producer,))
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
