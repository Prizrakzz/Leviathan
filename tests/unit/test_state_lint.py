"""``state/lint.py`` -- every S0 clause green, and each fence proved to FIRE.

STATE ENGINE DESIGN sec 2.3 / 2.4 / 2.6 / 5.2 / 1.4, sitting S0. A lint that has never been seen to
fail is a lint nobody has tested; every clause below is checked twice -- once that the estate passes it
and once that a deliberately broken input trips it.
"""
from __future__ import annotations

import copy
import re

from leviathan.graphrag import register as reg
from leviathan.graphrag import silverleg as sl
from leviathan.graphrag.state import lint as sbl


# EVERY FENCE BELOW IS PROVED TO FIRE BY PATCHING THE LOADER, NEVER BY EDITING THE LOADED DOC. The
# loaders are `lru_cache`d, so an in-place mutation restored in a `finally` is correct only while
# pytest runs these tests one at a time in this process -- it is a landmine under any in-process
# parallel runner, and the S0 review called it. `copy.deepcopy` + `monkeypatch.setattr` costs nothing
# and leaves the cache untouched.
def _patched(monkeypatch, name, mutate):
    """Deep-copy what loader `name` returns, mutate the copy, and serve it in the loader's place."""
    doc = copy.deepcopy(getattr(sbl, name)())
    mutate(doc)
    monkeypatch.setattr(sbl, name, lambda: doc)
    return doc


def test_check_state_board_is_green():
    errs = sbl.check_state_board()
    assert errs == [], "\n".join(errs)


def test_warnings_are_declared_absences_not_silence():
    warns = sbl.state_board_warnings()
    assert warns, "the estate has undeclared year_month lags and unverified calendar rules; a state " \
                  "board that reports NOTHING here has stopped looking"
    assert all(isinstance(w, str) and w.strip() for w in warns)
    # the two MPOC year_month cards are named rather than assumed away
    joined = " ".join(warns)
    assert "silver_mpoc_stock_comparison" in joined
    assert "silver_mpoc_trade_stats_monthly" in joined
    # the clock-free default says so out loud
    assert any("SKIPPED" in w and "no clock" in w for w in warns)


def test_the_staleness_clause_runs_only_when_it_is_handed_a_date():
    assert any("SKIPPED" in w for w in sbl.state_board_warnings())
    assert not any("SKIPPED" in w for w in sbl.state_board_warnings(asof="2026-09-08"))
    assert any("not an ISO date" in w for w in sbl.state_board_warnings(asof="last tuesday"))


def test_every_lint_message_is_ascii():
    for msg in sbl.check_state_board() + sbl.state_board_warnings():
        msg.encode("ascii")            # the Windows console is cp1252; stdout stays ASCII


# ── the ONE-VOCABULARY pin (sec 2.4) ─────────────────────────────────────────────────────────────────
def test_the_oni_bands_are_silverlegs_own():
    oni = sbl.load_conventions()["conventions"]["oni_climate"]
    assert [float(b) for b in oni["bands"]] == [float(b) for b, _ in reversed(sl._ONI_INTENSITY_BANDS)]
    assert list(oni["labels"]) == [w for _, w in reversed(sl._ONI_INTENSITY_BANDS)]
    assert oni["kind"] == "abs_bands", "ONI's z IS the raw anomaly in degC, never a sigma"


def test_a_drifted_oni_vocabulary_would_be_caught(monkeypatch):
    assert sbl._check_conventions() == []
    _patched(monkeypatch, "load_conventions",
             lambda d: d["conventions"]["oni_climate"].__setitem__("bands", [0.5, 1.0, 1.5, 2.5]))
    errs = sbl._check_conventions()
    assert any("_ONI_INTENSITY_BANDS" in e for e in errs), errs
    monkeypatch.undo()
    assert sbl._check_conventions() == []


# ── the REGISTER-SAFETY pin (sec 2.4; anchors F5 / doctrine M-5) ─────────────────────────────────────
def _all_label_text() -> list[str]:
    doc = sbl.load_conventions()
    out = []
    for row in (doc.get("conventions") or {}).values():
        out.extend(str(x) for x in (row.get("labels") or []))
    out.extend(str(v) for v in (doc.get("band_semantics") or {}).values())
    return out


def test_every_label_and_template_literal_is_register_safe():
    for text in _all_label_text():
        assert reg.count_flow_words(text) == 0, text
        assert reg.count_valuation_words(text) == 0, text
        assert reg.register_leaks(text) == [], text
        assert reg._LANE_B_ADJ.search(text) is None, text


def test_the_register_fence_fires_on_the_words_revision_1_proposed():
    # "crowded short" / "crowded long" / "stretched" are the flow register's own MUST-FLAG words and
    # were struck from this file for exactly this reason.
    for bad in ("crowded long", "crowded short", "stretched"):
        assert sbl._register_hits(bad), bad


# ── the BAND-SUM fence (sec 2.3, doctrine M-4) ───────────────────────────────────────────────────────
def test_no_summed_band_in_the_state_package():
    assert sbl._check_no_summed_band() == []


def test_the_band_sum_detector_actually_fires():
    for line in ("    horizon = parent.min_q + child.min_q",
                 "    hi = 3 * (a.max_q + b.max_q)",
                 "    total = sum(b.min_q for b in path)"):
        assert sbl._SUM_RX.search(line), line
    for ok in ("    lo, hi = band.months()",
               "    if band.min_q is None:",
               "    min_q += 0"):                       # augmented assignment is not a path sum
        assert not sbl._SUM_RX.search(ok), ok


# ── the BOARD_READ inertness fence (sec 2.6, D23) ────────────────────────────────────────────────────
def test_a_board_read_row_without_deferred_would_be_caught(monkeypatch):
    rows = sbl.board_read_rows()
    assert rows, "S0 landed board_read rows; if they are gone, the whole clause is vacuous"
    ref = sorted(rows)[0]
    _patched(monkeypatch, "board_read_rows", lambda d: d[ref].__setitem__("deferred", False))
    errs = sbl._check_board_read_rows()
    assert any("without `deferred: true`" in e for e in errs), errs
    monkeypatch.undo()
    assert sbl._check_board_read_rows() == []


# ── the CALENDAR coverage fence (sec 5.2) ────────────────────────────────────────────────────────────
def test_an_uncovered_card_would_be_caught(monkeypatch):
    _patched(monkeypatch, "load_release_calendar",
             lambda d: d["sources"]["usda_esr"].__setitem__("tables", []))
    errs = sbl._check_calendar()
    assert any("silver_esr" in e and "neither" in e for e in errs), errs
    assert any("no tables" in e for e in errs), errs
    monkeypatch.undo()
    assert sbl._check_calendar() == []


def test_every_rule_prints_a_window_or_a_day_and_never_a_time():
    doc = sbl.load_release_calendar()
    for sid, src in doc["sources"].items():
        rule = src["rule"]
        assert rule["kind"] in sbl.RULE_KINDS, sid
        assert not any(re.search(r"\d{1,2}:\d{2}", str(v)) for v in rule.values()), \
            "%s: a rule may name a WINDOW or a weekday, never a print TIME" % sid
    # SIX of these publishers state a clock (WASDE 12:00 ET, ESR 08:30, COT 15:30 ET, NASS 16:00,
    # MPOB 12:30, CONAB 19h) and the file records them in PROSE for exactly this reason.


def test_a_verification_is_a_pair_or_neither_half_of_one():
    """The first landing asserted ``verified_against is None`` on EVERY source, reasoning that "every
    rule at S0 is derived". That assertion LOCKED the calendar in its unverified state: it goes red
    the moment anyone applies a publisher read, which is the opposite of what owner decisions 3 and 4
    ask for. What must hold is the PAIR -- a verification with no date cannot go stale."""
    for sid, src in sbl.load_release_calendar()["sources"].items():
        va, vo = src["verified_against"], src["verified_on"]
        assert (va is None) == (vo is None), \
            "%s: verified_against and verified_on land together or not at all" % sid
        if va is not None:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(vo)), sid
            assert len(str(va).split()) >= 3, "%s: name WHAT was read, not just that it was" % sid


def test_the_publisher_reads_the_design_already_made_are_actually_carried():
    """The counterpart fence, and the one the S0 review exists for: DELTA PASS 1 read these publishers
    on 2026-09-08 and the first landing carried none of the reads, re-deriving every value from the
    fetch crons instead. If these rows ever fall back to ``verified_against: null``, a read the estate
    already owns has been thrown away."""
    srcs = sbl.load_release_calendar()["sources"]
    for sid in ("usda_wasde_psd", "usda_esr", "cftc_cot", "cpc_oni", "mpob",
                "world_bank_pink_sheet", "conab", "nass_crop_progress", "usda_fgis"):
        assert srcs[sid]["verified_against"], sid
        assert srcs[sid]["verified_on"] == "2026-09-08", sid


def test_the_two_publishers_that_do_not_use_a_weekday_do_not_declare_one():
    """DELTA PASS 1 B4.6 / B4.7. NASS Crop Progress is released "on the first business day of each
    week" and FGIS behaves identically -- proved live, the Labor Day holiday moved the 2026-09-08 FGIS
    report off Monday. The first landing declared MON for NASS (off the CARD's prose) and THU for FGIS
    (off our own FETCH cron and the card's DATA week), and both are wrong on every holiday week."""
    srcs = sbl.load_release_calendar()["sources"]
    for sid in ("nass_crop_progress", "usda_fgis"):
        rule = srcs[sid]["rule"]
        assert rule["kind"] == "first_business_day", sid
        assert "dow" not in rule, sid
    # NASS's season is the publisher's too: April 1 - November 30, so no January row is ever promised
    assert srcs["nass_crop_progress"]["rule"]["season_from"] == "04-01"
    assert srcs["nass_crop_progress"]["rule"]["season_to"] == "11-30"
    # ... the ONI TABLE's clock is the 5th, not the Diagnostic Discussion's second Thursday
    assert srcs["cpc_oni"]["rule"] == {"kind": "monthly_window", "day_min": 1, "day_max": 5}
    # ... the World Bank states a DATE and follows no rule at all
    assert srcs["world_bank_pink_sheet"]["rule"] == {"kind": "published_date"}
    # ... and WASDE is the publisher's 9th-12th, not the 8th-13th our own cron brackets
    assert srcs["usda_wasde_psd"]["rule"] == {"kind": "monthly_window", "day_min": 9, "day_max": 12}


def test_a_first_business_day_rule_may_not_smuggle_a_weekday_back_in(monkeypatch):
    _patched(monkeypatch, "load_release_calendar",
             lambda d: d["sources"]["usda_fgis"]["rule"].__setitem__("dow", "THU"))
    errs = sbl._check_calendar()
    assert any("first_business_day" in e and "'dow'" in e for e in errs), errs
    monkeypatch.undo()
    assert sbl._check_calendar() == []


def test_a_first_business_day_season_is_a_pair_of_mm_dd_or_neither(monkeypatch):
    _patched(monkeypatch, "load_release_calendar",
             lambda d: d["sources"]["nass_crop_progress"]["rule"].pop("season_to"))
    assert any("together or not at all" in e for e in sbl._check_calendar())
    monkeypatch.undo()
    _patched(monkeypatch, "load_release_calendar",
             lambda d: d["sources"]["nass_crop_progress"]["rule"].__setitem__("season_from", "2026-04-01"))
    assert any("must be MM-DD" in e for e in sbl._check_calendar())
    monkeypatch.undo()
    assert sbl._check_calendar() == []


def test_a_published_date_rule_may_not_carry_a_computable_key(monkeypatch):
    _patched(monkeypatch, "load_release_calendar",
             lambda d: d["sources"]["world_bank_pink_sheet"]["rule"].update({"day_min": 2, "day_max": 8}))
    errs = sbl._check_calendar()
    assert any("published_date" in e and "computes" in e for e in errs), errs
    monkeypatch.undo()
    assert sbl._check_calendar() == []


# ── the country_name_ref PAIRING fence (the S0 finding) ──────────────────────────────────────────────
def test_no_card_declares_a_country_name_ref_without_its_loader():
    assert sbl._check_country_ref_pairing() == []


def test_the_pairing_fence_fires(monkeypatch):
    """Loader-patched for the same reason as the rest: ``object.__setattr__`` on a card handed out by
    the lru_cached registry writes THROUGH to every other test in the process.

    S1 UPDATE: the unserved ref used to be ``numbers/nass_states.yaml`` -- S0 landed that reference file
    INERT, with no loader, which made it the perfect fixture for this fence. S1 landed the loader (and
    deliberately NOT the card key), so the fixture had to become a ref nothing serves. The FENCE is
    unchanged; only the thing it is pointed at moved."""
    cards = dict(sbl._registered_cards())
    cards["silver_nass_crop_progress"] = cards["silver_nass_crop_progress"].model_copy(
        update={"country_name_ref": "numbers/no_such_reference.yaml"})
    monkeypatch.setattr(sbl, "_registered_cards", lambda: cards)
    errs = sbl._check_country_ref_pairing()
    assert any("no_such_reference.yaml" in e and "_COUNTRY_REF_LOADERS" in e for e in errs), errs
    monkeypatch.undo()
    assert sbl._check_country_ref_pairing() == []
    assert sbl._registered_cards()["silver_nass_crop_progress"].country_name_ref is None, \
        "the real registry card was written through -- the very leak this form avoids"
