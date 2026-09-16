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
    """Every S0 clause plus S3's three plus S7b's one -- TWELVE. Empty list = green. Absorbed by
    ``config_check.check_state_board`` after K9.

    S3 ADDS THREE CLAUSES, each grading a CONTRACT BETWEEN MODULES that prose alone was carrying: every
    closed decline word has a reader sentence (9), the row-class regexes are pairwise disjoint and
    disjoint from the walk's own line classes (10), and the mandate, the two recency sentences and the
    calendar's rule kinds are clean (11).

    S7b ADDS THE TWELFTH, :func:`_check_nonobvious_watch` -- the non-obvious watch vocabulary, its
    ceilings and the owner's 2026-09-11 release-calendar ban, graded on the closed KIND map. It is
    named here because `config_check.check_state_board`'s docstring is where a reviewer looks to answer
    "is the calendar ban enforced at build", and a roster that stops at eleven answers no."""
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
