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


# -- S8 LANE N -- clause 15: NO CHAIN LINT DELETES, and clause 9's chain vocabulary -------------------
# The three correcting lints of DESIGN B.6 land in `answer.py`, which this lane does not own. Clause 15
# is therefore a SOURCE CONTRACT read by path (never by import) and it SKIPS honestly until they land.
# Every rule below is proved to FIRE against a synthetic module, and the fence is proved NOT to fire
# against a conforming one -- which is the half a source lint usually skips and the half that decides
# whether lane A can satisfy it at all. The behavioural half runs the conforming lint over the five
# 2026-09-16 served bodies: UNSEEN real-seat prose, never the author's own case list.
import ast as _ast
import pathlib as _pl
import tempfile as _tf

import pytest as _pt
from leviathan.graphrag.state import narration as _nar


def _smoke_answers():
    """The five 2026-09-16 in-VPC smoke bodies, found by SHAPE rather than by a session id -- the
    scratchpad path carries a session uuid that is stale the moment the session ends, and a corpus
    pinned to one is a corpus that silently stops being read."""
    base = _pl.Path(_tf.gettempdir()) / "claude"
    for d in sorted(base.glob("*/*/scratchpad/prearm_smoke_0916/answers")):
        if len(list(d.glob("*.md"))) == 5:
            return d
    return None


#: A CONFORMING chain lint, written to the shipped `answer._bind_bar_adjectives` idiom: split on
#: `register._SENT_KEEP`, guard for idempotence, APPEND inside the sentence before its terminator,
#: count what it did not correct, never raise. It is the reference clause 15 must ACCEPT, and it is a
#: STRING because clause 15 grades SOURCE -- a contract nobody can satisfy is a fence that gets deleted
#: the first time it blocks a build.
_GOOD_LINT = "\n".join([
    'import re',
    '_KEEP = re.compile(r"([.!?;]\\s+)")',
    '',
    '',
    'def _stamp_chain_hops(structured, chains):',
    '    census = {"chain_hops_skipped": 0, "corrected": 0}',
    '    try:',
    '        for field, text in list((structured or {}).items()):',
    '            toks = _KEEP.split(text or "")',
    '            for i, sent in enumerate(toks):',
    '                if i % 2 or not sent.strip():',
    '                    continue',
    '                clause = " -- the driver model places one hop between these two"',
    '                if clause in sent:',
    '                    continue',
    '                if "hop" not in sent:',
    '                    census["chain_hops_skipped"] += 1',
    '                    continue',
    '                body = sent.rstrip()',
    '                tail = sent[len(body):]',
    '                end = ""',
    '                while body and body[-1] in ".;!?":',
    '                    end, body = body[-1] + end, body[:-1]',
    '                toks[i] = body + clause + end + tail',
    '                census["corrected"] += 1',
    '            structured[field] = "".join(toks)',
    '    except Exception:',
    '        return census',
    '    return census',
    '',
])

_SKIP_LINE = '                    census["chain_hops_skipped"] += 1\n'
_CORR_LINE = '                census["corrected"] += 1\n'
_GUARD = '                if clause in sent:\n                    continue\n'

#: The same lint with ONE rule broken per case -- the negative set clause 15 must REFUSE.
_BAD_LINTS = {
    "del": _GOOD_LINT.replace(_SKIP_LINE, _SKIP_LINE + '                    del toks[i]\n'),
    "remover": _GOOD_LINT.replace(_SKIP_LINE, _SKIP_LINE + '                    toks.pop(i)\n'),
    "blank": _GOOD_LINT.replace(_SKIP_LINE, _SKIP_LINE + '                    toks[i] = ""\n'),
    "no_guard": _GOOD_LINT.replace(_GUARD, ''),
    "no_counter": _GOOD_LINT.replace(_SKIP_LINE, '').replace(_CORR_LINE, ''),
}


#: ROUND 2 (review MAJOR 1) -- THE FOUR DELETION SHAPES THAT PASSED CLAUSE 15 AT ROUND 1. Each one is
#: the SAME conforming reference with ONE edit, each one carries the idempotence guard and the in-place
#: increment the clause asks for, and each one REMOVES served text. MEASURED before the fix
#: (`scratchpad/s8_chain/r2/REV_refute_N.json`, Q1): all four returned ZERO errors.
_JOIN_LINE = '            structured[field] = "".join(toks)\n'
_DELETING_LINTS = {
    # (1) the plainest deletion in Python: rebuild the token list without the sentences you dropped.
    #     ROUND 3 gave the filter a predicate that really drops a sentence (`if t.strip()` drops only
    #     the empty trailing token, so as the review wrote it the case deletes NOTHING -- measured, and
    #     kept as its own refutation below); this one keeps the hop sentences and loses the rest, which
    #     is what the shape is accused of.
    "comprehension": _GOOD_LINT.replace(
        _JOIN_LINE,
        '            keep = [t for t in toks if "hop" in t or t in ".;!? "]\n'
        '            structured[field] = "".join(keep)\n'),
    # (2) the erase spelled as a rewrite
    "re_sub_blank": _GOOD_LINT.replace(
        _SKIP_LINE, _SKIP_LINE + '                    toks[i] = re.sub(r".*", "", sent)\n'),
    # (3) the deletion spelled as the assignment the clause already models, one level up
    "slice_assign": _GOOD_LINT.replace(_JOIN_LINE, '            toks[2:4] = []\n' + _JOIN_LINE),
    # (4) and the plainest of all: cut the sentence out of the served text
    "replace_out": _GOOD_LINT.replace(
        _JOIN_LINE, '            structured[field] = "".join(toks).replace(sent, "")\n'),
}

#: A READER of the counters -- the arm-report assembly threat E2 names ("the counter
#: `chain_unranked_narrated` is read in the arm report"). It PRODUCES nothing and MUTATES nothing, and
#: at round 1 it RED the build with six errors, beside the conforming reference (review MAJOR 2, Q3c).
_COUNTER_READER = "\n".join([
    '',
    '',
    'def _chain_counters_into_record(rec, census):',
    '    """The arm report reads the counters (threat E2). It PRODUCES nothing."""',
    '    for _k in ("chain_hops_unfigured", "chain_hops_skipped", "chain_unranked_narrated"):',
    '        if census.get(_k):',
    '            rec[_k] = int(census[_k])',
    '    return rec',
    ''])

#: ROUND 3 (review MAJOR 1, re-opened) -- THE SAME READER IN THE SPELLING A REPORT ROW IS ACTUALLY
#: WRITTEN IN: a dict LITERAL and a summary line. Round 2 graded it as three chain lints and RED the
#: build with SIX errors (`r2b/rev2/REV2_clause15_readerFP.json`), beside the conforming reference,
#: because the literal declares the counters and the f-string "writes served text". It does neither: it
#: writes a RECORD, and nothing it writes carries anything it read out of the thing it writes into.
_REPORT_ROW_READER = "\n".join([
    '',
    '',
    'def _chain_report_row(census):',
    '    rec = {"chain_hops_unfigured": int(census.get("chain_hops_unfigured") or 0),',
    '           "chain_hops_skipped": int(census.get("chain_hops_skipped") or 0),',
    '           "chain_unranked_narrated": int(census.get("chain_unranked_narrated") or 0)}',
    '    line = f"chains corrected: {rec}"',
    '    return rec, line',
    ''])
#: and the same row with the counter keys spelled as CONSTANTS into a record it was handed.
_CONST_KEY_READER = "\n".join([
    '',
    '',
    'def _chain_counters_const(rec, census):',
    '    rec["chain_hops_unfigured"] = int(census["chain_hops_unfigured"])',
    '    rec["chain_hops_skipped"] = int(census["chain_hops_skipped"])',
    '    return rec',
    ''])

#: ROUND 4 (review MAJOR 2, re-opened a THIRD time) -- THE THREE SPELLINGS AN ARM-REPORT ROW IS
#: ACTUALLY WRITTEN IN ONCE IT DERIVES ANYTHING. Round 3 RED the build on all three, each beside this
#: lane's own conforming reference, and one of them with the DELETION message -- on a record that
#: holds no sentence at all (`r2c/rev3/REV3_N_adv.json`, `REV3_N_adv2.json`: 2 / 2 / 2 errors). The
#: cause was `base in reads` reading "writes back into the structure it read from" as TRUE of any row
#: that reads its own counters back. THE ARM-REPORT ROW IS THE SURFACE THIS FENCE EXISTS TO PROTECT
#: AND IT IS UNWRITTEN TODAY: whichever lane writes it writes one of these three.
_DERIVED_NOTE_READER = "\n".join([
    '',
    '',
    'def _chain_report_row(rec, census):',
    '    rec["chain_hops_unfigured"] = int(census.get("chain_hops_unfigured") or 0)',
    '    rec["chain_hops_skipped"] = int(census.get("chain_hops_skipped") or 0)',
    '    rec["chain_note"] = "%d hops skipped" % rec["chain_hops_skipped"]',
    '    return rec',
    ''])
#: the same row BUCKETED and totalled -- the one the one-line counter-key exclusion did NOT close,
#: because `report["chain"]` is read under a key that is not a counter. It is a COUNTER BUCKET: a
#: dict literal whose every key is one of the four.
_ROLLUP_READER = "\n".join([
    '',
    '',
    'def _chain_rollup(report, census):',
    '    report["chain"] = {"chain_hops_unfigured": 0, "chain_hops_skipped": 0}',
    '    for k in ("chain_hops_unfigured", "chain_hops_skipped"):',
    '        report["chain"][k] = int(census.get(k) or 0)',
    '    report["chain_total"] = sum(report["chain"].values())',
    '    return report',
    ''])
#: ...and ordinary report hygiene: drop the line you just wrote when the counter is zero. This one
#: drew the DELETION charge ("calls rec.pop() on the served text") on a report row.
_POPPING_READER = "\n".join([
    '',
    '',
    'def _chain_report_row_pop(rec, census):',
    '    rec["chain_hops_skipped"] = int(census.get("chain_hops_skipped") or 0)',
    '    rec["chain_line"] = "skipped=%s" % (rec["chain_hops_skipped"],)',
    '    if not rec["chain_hops_skipped"]:',
    '        rec.pop("chain_line", None)',
    '    return rec',
    ''])

#: THE READER SET, in one place: a fence that closes this class SPELLING BY SPELLING has been re-opened
#: three rounds running, so every spelling any review has produced is graded together and a new one is
#: a row here and nothing else.
_READERS = (_COUNTER_READER, _REPORT_ROW_READER, _CONST_KEY_READER,
            _DERIVED_NOTE_READER, _ROLLUP_READER, _POPPING_READER)

#: ROUND 4 (review MAJOR 2) -- THE FALSE-NEGATIVE HALF OF THE SAME CASE SET. Two of the reviewer's
#: deleting shapes are BUILD-SILENT by declaration (`.update()` is the belt's declared residual, and
#: a truncating slice of the join is the reviewer's own widening of it) and one is charged at build.
#: All three are charged by the EXECUTED LAW, which is what makes the residual a declared limit of the
#: belt rather than a hole in the fence: `{case: (build errors, at least this many law charges)}`.
_REVIEWER_DELETERS = {
    "deleter_via_update": (0, 3),
    "deleter_self_slice": (0, 12),
    "deleter_via_alias": (1, 1),
}
_REVIEWER_DELETER_SRC = {
    "deleter_via_update": _GOOD_LINT.replace(
        _JOIN_LINE,
        '            keep = [t for t in toks if "hop" in t or t in ".;!? "]\n'
        '            structured.update({field: "".join(keep)})\n'),
    "deleter_self_slice": _GOOD_LINT.replace(
        _JOIN_LINE, '            structured[field] = "".join(toks)[:40]\n'),
    "deleter_via_alias": _GOOD_LINT.replace(
        _JOIN_LINE,
        '            box = structured\n'
        '            keep = [t for t in toks if "hop" in t or t in ".;!? "]\n'
        '            box[field] = "".join(keep)\n'),
}
#: ...and the two CONFORMING shapes from the same set, which must stay clean on both readings.
_REVIEWER_CONFORMING = {
    "conforming_via_local_text": _GOOD_LINT.replace(
        _JOIN_LINE, '            out = "".join(toks)\n            structured[field] = out\n'),
    "conforming_local_pop": _GOOD_LINT.replace(
        '    census = {"chain_hops_skipped": 0, "corrected": 0}\n',
        '    census = {"chain_hops_skipped": 0, "corrected": 0}\n'
        '    opts = dict(chains) if isinstance(chains, dict) else {}\n'
        '    opts.pop("verbose", None)\n'),
}

#: ROUND 4 (review MAJOR 1) -- THE COUNTER DECLARED AND NEVER RAISED, with an unrelated `+=` in the
#: function so the round-3 rule ("any AugAssign anywhere") is satisfied. The shipped `_chain_lints`
#: carries `clause += ...` on a LOCAL STRING, which is exactly this shape, and that is why the rule
#: had to be graded PER COUNTER.
_UNRAISED_COUNTER = _GOOD_LINT.replace(
    _SKIP_LINE, '                    _n = 0\n                    _n += 1\n')

#: ROUND 3 (review MAJOR 3) -- THE DELETION DONE IN PLACE, with the served field written back as the
#: LIST it is. Round 2 graded NEITHER: no string is built, so the function was not a "lint" at all, and
#: the skip warning did not name the counter it owns -- the counter read as GRADED. Both shapes are
#: ordinary Python in `answer.py`, where `structured["sections"]` and `structured["sources"]` are
#: list-valued served fields.
_INPLACE_DELETERS = {
    "inplace_del": _GOOD_LINT.replace(
        _SKIP_LINE, _SKIP_LINE + '                    del toks[i]\n').replace(
        _JOIN_LINE, '            structured[field] = toks\n'),
    "inplace_pop": _GOOD_LINT.replace(
        _SKIP_LINE, _SKIP_LINE + '                    toks.pop(i)\n').replace(
        _JOIN_LINE, '            structured[field] = toks\n'),
}

#: ROUND 3 (review MINOR 2) -- THE THREE SHAPES THE ROSTER OF SPELLINGS NEVER REACHED: the filtered
#: rebuild routed through ONE intermediate name, the TRUNCATION, and the filter moved into a helper.
#: A source roster cannot follow any of them; EXECUTION does not have to.
_SILENT_DELETERS = {
    "filtered_via_one_variable": _GOOD_LINT.replace(
        _JOIN_LINE,
        '            keep = [t for t in toks if "hop" in t or t in ".;!? "]\n'
        '            joined = "".join(keep)\n'
        '            structured[field] = joined\n'),
    "truncating_slice_join": _GOOD_LINT.replace(
        _JOIN_LINE, '            structured[field] = "".join(toks[:3])\n'),
    "delete_in_helper": (
        _GOOD_LINT.replace(_JOIN_LINE, '            structured[field] = "".join(_drop(toks))\n')
        + '\n\ndef _drop(toks):\n    return [t for t in toks if "hop" in t or t in ".;!? "]\n'),
}

#: ROUND 3 (review MAJOR 2) -- TWO CONFORMING APPENDS that round 2 charged as deletions. Nothing is
#: removed in either: the FULL token join is in the written value and the filtered list is joined ONTO
#: it. The second is the shape DESIGN B.6's own L2 lint has (`gap` = the hops the sentence jumped,
#: counted and named back onto the page); the third is the first one with the guard that makes a
#: re-run append nothing twice, and it is the one that must be clean END TO END.
_APPENDING_LINTS = {
    "append_joins_filtered_list": _GOOD_LINT.replace(
        _JOIN_LINE,
        '            named = [t for t in toks if "hop" in t]\n'
        '            structured[field] = "".join(toks) + " Also: " + ", ".join(named[:1])\n'),
    "append_counts_filtered_list": _GOOD_LINT.replace(
        _JOIN_LINE,
        '            gap = [t for t in toks if "hop" not in t]\n'
        '            structured[field] = "".join(toks) + " (%d hops unnamed)" % (len(gap),)\n'),
}
_GUARDED_APPEND = _GOOD_LINT.replace(
    _JOIN_LINE,
    '            named = [t for t in toks if "hop" in t]\n'
    '            _add = " Also: " + ", ".join(named[:1])\n'
    '            _txt = "".join(toks)\n'
    '            structured[field] = _txt if _add in _txt else _txt + _add\n')


def _exec_case(src, name="_stamp_chain_hops"):
    """The case's own source, executed, and the function the law is run on handed back."""
    ns: dict = {}
    exec(compile(src, "<clause15 case>", "exec"), ns)          # noqa: S102 -- the deck's own case
    return ns[name]


def test_clause15_the_negative_set_is_the_conforming_lint_with_ONE_rule_broken():
    """Each case differs from the reference by one edit and by nothing else -- otherwise a case that
    fired for a second reason would be reported as proof of the rule it was built for."""
    for case, src in _BAD_LINTS.items():
        assert src != _GOOD_LINT, case
        assert abs(len(src.splitlines()) - len(_GOOD_LINT.splitlines())) <= 2, case
        compile(src, "<" + case + ">", "exec")           # every case is real Python


def test_clause15_skips_honestly_until_lane_A_lands_and_says_so():
    """A clause that grades nothing because the code it grades has not been written is a DECLARED
    ABSENCE, never a silence -- and never a red build for another lane's work in progress. Once lane
    A lands, the clause GRADES and there is nothing to declare: BOTH STATES are asserted here, on
    their own terms, so neither lane reds the other's deck.

    ROUND 2: this is lane A's own paste (`A_answer_BUILD.md` sec 7.2), landed in the file that owns
    it. The round-1 shape asserted the SKIP unconditionally and went red the moment `_chain_lints`
    landed in `answer.py` -- the census's 24th new red, and the only one of the 24 that was not the
    `_chain_on` shadow."""
    assert sbl._check_chain_lints_append_only() == []
    warns = [w for w in sbl.state_board_warnings() if "clause 15" in w]
    _src = sbl._answer_source()
    _have = sbl._chain_lint_functions(_ast.parse(_src), _src)
    if all(_have.values()):                      # lane A has landed: the clause GRADES
        assert warns == [], warns
        return
    assert warns, "the skip must be named in the warnings, not inferred from a green clause"
    assert "SKIP and not a pass" in warns[0]
    for c in sbl.CHAIN_LINT_COUNTERS:
        assert c in warns[0], c


def test_clause15_counters_are_the_names_the_arm_report_reads():
    """DESIGN B.6 names the counters and threat E2 says the report reads them. The COUNTER is the
    contract's key and the function name is not: a private function may be renamed by the lane that
    owns it, a census column may not.

    ROUND 3 READS THE ROSTER OFF THE SHIPPED FUNCTION rather than beside it. `_chain_lints` returns a
    FOURTH counter (`chain_hops_ambiguous`, round 2 review MAJOR A-2 -- the hops that HAD a served
    figure and were refused it on a multi-anchor page), and it was the one counter no build graded: the
    tuple said three and the function returned four.

    ROUND 4 CAUGHT THE FIFTH THE SAME WAY, ONE SITTING AFTER THE RULE WAS WRITTEN. Lane A landed
    `chain_fence_closed` -- the FAIL-CLOSED counter, the corrections withheld because an instrument
    could not be read -- inside `_chain_lints`, and this assertion RED on the shared worktree within
    the hour, naming the extra key. That is the contract working: the roster row follows the producer
    IN THE SAME COMMIT, and a counter in the function and not in the tuple is a census column no build
    grades."""
    assert sbl.CHAIN_LINT_COUNTERS == ("chain_hops_unfigured", "chain_hops_skipped",
                                       "chain_unranked_narrated", "chain_hops_ambiguous",
                                       "chain_fence_closed")
    from leviathan.graphrag import answer as _an
    assert hasattr(_an, "_chain_lints")                        # the SHIPPED object, never a stand-in
    _node = [n for n in _ast.walk(_ast.parse(sbl._answer_source()))
             if isinstance(n, _ast.FunctionDef) and n.name == "_chain_lints"]
    assert _node, "the producer moved out of answer.py and the roster cannot be read off it"
    declared = {c for c in sbl._chain_stores(_node[0]) if c.startswith("chain_")}
    assert declared == set(sbl.CHAIN_LINT_COUNTERS), sorted(declared ^ set(sbl.CHAIN_LINT_COUNTERS))
    # ... and the FIRST parameter is the served structure the law is executed on
    assert list(_node[0].args.args)[0].arg == "structured"


def test_clause15_does_not_claim_the_COVERAGE_counter_that_lives_in_render():
    """REVIEW MAJOR 4. `chain_referenced` is `render.board_coverage`'s -- how many RENDERED chains the
    writer's prose reached, read off the coverage bucket. It is NOT a lint counter: the lints count
    what the correcting pass did to SENTENCES. Raising a second `chain_referenced` inside the pass and
    adding it here would put one census name over two populations, which is the row-with-two-meanings
    failure this estate keeps paying for -- so the name is asserted WHERE IT LIVES and asserted absent
    where it does not."""
    from leviathan.graphrag.state import render as _R
    assert "chain_referenced" not in sbl.CHAIN_LINT_COUNTERS
    produced = [n.name for n in _ast.walk(_ast.parse(_pl.Path(_R.__file__).read_text(encoding="utf-8")))
                if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                for r in _ast.walk(n) if isinstance(r, _ast.Return) and isinstance(r.value, _ast.Dict)
                and any(isinstance(k, _ast.Constant) and k.value == "chain_referenced"
                        for k in r.value.keys)]
    assert produced, "render no longer returns chain_referenced from any coverage splat"


def test_clause15_accepts_a_conforming_lint(monkeypatch):
    """THE HALF A SOURCE LINT USUALLY SKIPS. A contract nobody can satisfy is a fence that will be
    deleted the first time it blocks a build, so the reference implementation is graded here."""
    monkeypatch.setattr(sbl, "_answer_source", lambda: _GOOD_LINT)
    assert sbl._check_chain_lints_append_only() == []
    assert not [w for w in sbl.state_board_warnings()
                if "clause 15" in w and "chain_hops_skipped" in w]


@_pt.mark.parametrize("case,needle", [
    ("del", "carries a `del` over the served text"),
    ("remover", "calls toks.pop() on the served text"),
    ("blank", "blanks a slot of the served text with the empty string"),
    ("no_counter", "never increments its own counter"),
])
def test_clause15_refuses_every_way_a_chain_lint_could_delete(monkeypatch, case, needle):
    """Each rule proved to FIRE, one broken rule at a time. "Fences CORRECT or COMPUTE, never delete" is
    the doctrine; this is the only place it is enforced on code that does not exist yet.

    ROUND 3 SCOPED EVERY ONE OF THEM TO THE SERVED TEXT -- the structure the pass read the writer's
    sentences out of, and the names it derived from that read. A `.pop()` off a local options dict is
    nobody's deletion, and a fence that charged it would be charging punctuation. The idempotence rule
    left this list and is graded by RUNNING the pass twice (see the executed law below), because as a
    SHAPE it charged `if clause not in sent:` for the guard it plainly has."""
    monkeypatch.setattr(sbl, "_answer_source", lambda: _BAD_LINTS[case])
    errs = sbl._check_chain_lints_append_only()
    assert errs, case
    assert any(needle in e for e in errs), (case, errs)
    assert any("chain_hops_skipped" in e for e in errs), errs


@_pt.mark.parametrize("case,needle", [
    ("comprehension", "FILTERED copy"),
    ("re_sub_blank", "ERASED with an empty replacement"),
    ("slice_assign", "assigns an EMPTY collection into a slice"),
    ("replace_out", "ERASED with an empty replacement"),
])
def test_clause15_refuses_the_four_deletions_a_builder_actually_writes(monkeypatch, case, needle):
    """REVIEW MAJOR 1, closed with its own measurement. The round-1 clause modelled `del`, five removing
    METHOD calls and `x[i] = ""` -- and a rebuild of the token list from a filtering comprehension, an
    `re.sub(..., "")`, a slice taking `[]` and a `.replace(sent, "")` are none of those. All four
    carried the guard and the increment and all four PASSED. A fence bypassed by the first idiom a
    builder reaches for is worse than an absent one, because the next reviewer stops looking."""
    src = _DELETING_LINTS[case]
    assert src != _GOOD_LINT, case
    compile(src, "<" + case + ">", "exec")                # every case is real Python
    monkeypatch.setattr(sbl, "_answer_source", lambda: src)
    errs = sbl._check_chain_lints_append_only()
    assert errs, case
    assert any(needle in e for e in errs), (case, errs)
    assert any("chain_hops_skipped" in e for e in errs), errs


@_pt.mark.parametrize("case", sorted(_INPLACE_DELETERS))
def test_clause15_grades_the_deleter_that_writes_the_field_back_as_the_LIST_it_is(monkeypatch, case):
    """REVIEW MAJOR 3, closed. `del toks[i]` ... `structured[field] = toks` deletes a sentence and
    BUILDS NO STRING, so round 2's "does it write prose?" half said it was not a lint at all: zero
    errors, zero producers, and -- worse -- the skip warning stopped naming `chain_hops_skipped`, so
    the counter the deleter owns read as GRADED. The class rule asks a different question (does it
    write back into the structure it read the served text from?) and both spellings answer yes."""
    src = _INPLACE_DELETERS[case]
    compile(src, "<" + case + ">", "exec")
    monkeypatch.setattr(sbl, "_answer_source", lambda: src)
    found = sbl._chain_lint_functions(_ast.parse(src), src)
    assert [n for n, _ in found["chain_hops_skipped"]] == ["_stamp_chain_hops"], case
    errs = sbl._check_chain_lints_append_only()
    assert errs and any("served text" in e for e in errs), (case, errs)
    # and the LAW says the same thing by running it: the field comes back as a list, sentences short
    rep = sbl.chain_append_only_report(_exec_case(src), ())
    assert rep["errors"], case


def test_clause15_is_not_silent_when_a_deleter_sits_BESIDE_a_conforming_producer(monkeypatch):
    """THE COMPOSITION THAT MATTERS (review MAJOR 3's second half). A conforming lint and an in-place
    deleter that stores the SAME counter: round 2 returned no error, and the skip warning named the
    OTHER counters -- so the one counter with a deleting producer was the one counter that read as
    graded. Both functions are producers now and the deleter is charged by name."""
    src = _GOOD_LINT + "\n".join([
        '',
        '',
        'def _drop_unranked(structured, census):',
        '    for field, toks in list((structured or {}).items()):',
        '        for i, sent in enumerate(list(toks)):',
        '            if "hop" not in sent:',
        '                del toks[i]',
        '                census["chain_hops_skipped"] = census.get("chain_hops_skipped", 0) + 1',
        '        structured[field] = toks',
        '    return census',
        ''])
    compile(src, "<composition>", "exec")
    monkeypatch.setattr(sbl, "_answer_source", lambda: src)
    found = sbl._chain_lint_functions(_ast.parse(src), src)
    assert sorted(n for n, _ in found["chain_hops_skipped"]) == ["_drop_unranked", "_stamp_chain_hops"]
    errs = sbl._check_chain_lints_append_only()
    assert any("_drop_unranked" in e and "`del` over the served text" in e for e in errs), errs
    assert not any("_stamp_chain_hops" in e for e in errs), errs


# -- THE LAW ITSELF, EXECUTED (round 3) ---------------------------------------------------------------
def test_clause15_the_law_is_EXECUTED_and_the_conforming_reference_passes_it():
    """APPEND-ONLY IS A PROPERTY OF WHAT THE PASS DOES TO A PAGE, and round 3 grades it by running the
    pass on a known structured dict: every character the writer wrote is still there in order, every
    sentence is still whole, nothing shortens, and a second run changes nothing. NON-VACUITY IS PART OF
    THE ASSERTION -- a probe a lint cannot fire on proves nothing, so the report says what it CHANGED
    and this asserts both fields moved."""
    rep = sbl.chain_append_only_report(_exec_case(_GOOD_LINT), ())
    assert rep["errors"] == [], rep["errors"]
    assert rep["raised"] is None
    assert rep["changed"] == sorted(sbl.CHAIN_APPEND_PROBE), rep["changed"]
    for field, before in rep["before"].items():
        assert len(rep["after"][field]) > len(before), field


@_pt.mark.parametrize("case", sorted(_DELETING_LINTS) + sorted(_SILENT_DELETERS)
                      + sorted(_INPLACE_DELETERS))
def test_clause15_the_executed_law_charges_every_deletion_however_it_is_spelled(case):
    """REVIEW MINOR 2, and the reason the law had to stop being a roster of spellings. Three of these
    shapes no source clause in this file reaches: the filtered rebuild routed through ONE intermediate
    name, the TRUNCATION (`"".join(toks[:3])`), and the filter moved into a HELPER. A fixture does not
    have to follow a name anywhere -- it reads the page back and counts what is missing."""
    src = dict(_DELETING_LINTS, **_SILENT_DELETERS, **_INPLACE_DELETERS)[case]
    rep = sbl.chain_append_only_report(_exec_case(src), ())
    assert rep["errors"], case
    assert rep["changed"], (case, "the probe never fired -- the case proves nothing")


def test_clause15_the_reviewers_own_no_op_filter_really_deletes_NOTHING():
    """REFUTED, WITH THE MEASUREMENT. The review's FN1 filters `if t.strip()`, which on a split of real
    prose drops only the EMPTY trailing token -- so the served page comes back character for character
    identical. It is not a deletion this fence missed; it is not a deletion. The one with a filter that
    does drop a sentence is graded above."""
    src = _GOOD_LINT.replace(
        _JOIN_LINE,
        '            keep = [t for t in toks if t.strip()]\n'
        '            joined = "".join(keep)\n'
        '            structured[field] = joined\n')
    rep = sbl.chain_append_only_report(_exec_case(src), ())
    assert rep["errors"] == [], rep["errors"]
    assert rep["changed"], "the case never fired"


@_pt.mark.parametrize("case", sorted(_APPENDING_LINTS))
def test_clause15_never_calls_a_CONFORMING_APPEND_a_deletion(monkeypatch, case):
    """REVIEW MAJOR 2, closed at BUILD and at EXECUTION. Both cases join a filtered list ONTO the full
    served text; nothing is removed in either, and round 2 charged both with "rebuilds the served text
    from a FILTERED copy" -- a message naming a defect that is not there, beside the lane's own
    reference. What the executed law says about them instead is TRUE and is a different charge: they
    carry no guard, so a second run appends a second clause."""
    src = _APPENDING_LINTS[case]
    compile(src, "<" + case + ">", "exec")
    monkeypatch.setattr(sbl, "_answer_source", lambda: src)
    assert sbl._check_chain_lints_append_only() == [], case
    rep = sbl.chain_append_only_report(_exec_case(src), ())
    assert not any("FILTERED" in e or "loses served text" in e or "SHORTENS" in e
                   for e in rep["errors"]), (case, rep["errors"])
    assert all("NOT IDEMPOTENT" in e for e in rep["errors"]), (case, rep["errors"])


def test_clause15_passes_the_guarded_append_END_TO_END(monkeypatch):
    """The same append with the guard that makes a re-run append nothing twice: clean at build and
    clean under the law. A contract nobody can satisfy is a fence that gets deleted the first time it
    blocks a build, so the satisfying implementation is graded here."""
    compile(_GUARDED_APPEND, "<guarded_append>", "exec")
    monkeypatch.setattr(sbl, "_answer_source", lambda: _GUARDED_APPEND)
    assert sbl._check_chain_lints_append_only() == []
    rep = sbl.chain_append_only_report(_exec_case(_GUARDED_APPEND), ())
    assert rep["errors"] == [], rep["errors"]
    assert rep["changed"], "the case never fired"


def test_clause15_charges_a_pass_that_grows_the_page_every_time_it_runs():
    """IDEMPOTENCE, GRADED BY RUNNING IT TWICE and no longer by the shape of an `if`. The reference
    with its guard removed appends a second clause on the second run, which is a deletion's mirror
    image: the page nobody asked for grows without bound."""
    rep = sbl.chain_append_only_report(_exec_case(_BAD_LINTS["no_guard"]), ())
    assert rep["errors"] and all("NOT IDEMPOTENT" in e for e in rep["errors"]), rep["errors"]


def test_clause15_does_not_charge_the_ORDINARY_filtered_list_a_lint_builds(monkeypatch):
    """THE OTHER HALF OF MAJOR 1's FIX, and the half that decides whether lane A can satisfy it. A
    chain lint SELECTS all the time -- lane A's shipped `_chain_lints` builds `named` (the rendered
    hops this sentence mentions) and `gap` (the hops it jumped) with filtering comprehensions, and
    JOINS one of them into a sentence. Neither is a deletion: what is charged is a filtered copy put
    BACK into the served text, and nothing else."""
    ok = _GOOD_LINT.replace(
        _JOIN_LINE,
        '            named = [t for t in toks if "hop" in t]\n'
        '            clause = " -- also " + ", ".join(named[:1])\n' + _JOIN_LINE)
    compile(ok, "<ordinary_filter>", "exec")
    monkeypatch.setattr(sbl, "_answer_source", lambda: ok)
    assert sbl._check_chain_lints_append_only() == []


def test_clause15_grades_PRODUCERS_and_never_the_arm_report_that_READS_the_counters(monkeypatch):
    """REVIEW MAJOR 2, closed with its own measurement (Q3 / Q3c). A function that copies the three
    counters into the arm-report record -- the surface threat E2 names by name -- was graded as three
    chain lints and RED the build with SIX errors, and it did it BESIDE the lane's own conforming
    reference. A build gate that reds on the conforming implementation of the lane it was written for
    is a gate that gets deleted, which is how the estate lost the T2b write-guard.

    THE JOIN IS NOW A CLASS: a lint stores a counter name AND writes served text back into the
    structure it read that text from. A reader writes a RECORD, and nothing it writes carries anything
    it read out of the thing it writes into -- which is true of every spelling of a report row, so it
    needs no rule of its own.

    ROUND 3 ADDS THE SPELLING THAT RE-OPENED THIS: a dict LITERAL plus an f-string summary
    (`r2b/rev2/REV2_clause15_readerFP.json` -- six errors, beside the conforming reference), and the
    one that writes the counters into a record it was HANDED, under constant keys.

    ROUND 4 ADDS THE THREE THAT RE-OPENED IT AGAIN, all measured at 2 build errors each beside this
    same reference (`r2c/rev3/REV3_N_adv.json`, `REV3_N_adv2.json`): the row that DERIVES a note off
    its own record, the nested ROLLUP with a total, and the row that DROPS its own line when the
    counter is zero -- that last one charged with the DELETION message, on a record holding no
    sentence at all. Three rounds of closing a class spelling by spelling is the measurement that
    says the rule was wrong, not the roster: a counter READ BACK is no more a page than a counter
    BUMP is, and the exclusion now runs on both sides of the assignment."""
    for reader in _READERS:
        both = _GOOD_LINT + reader
        compile(both, "<reader beside the reference>", "exec")
        monkeypatch.setattr(sbl, "_answer_source", lambda _s=both: _s)
        assert sbl._check_chain_lints_append_only() == [], reader.splitlines()[2]
        found = sbl._chain_lint_functions(_ast.parse(both), both)
        assert [n for n, _ in found["chain_hops_skipped"]] == ["_stamp_chain_hops"]
        assert found["chain_unranked_narrated"] == [], "the READER is not a producer of anything"
        # and the reader ALONE leaves the clause with nothing to grade -- a SKIP, said out loud
        monkeypatch.setattr(sbl, "_answer_source", lambda _s=reader: _s)
        assert sbl._check_chain_lints_append_only() == []
        warns = [w for w in sbl.state_board_warnings() if "clause 15" in w]
        assert warns and "SKIP and not a pass" in warns[0]
        for c in sbl.CHAIN_LINT_COUNTERS:
            assert c in warns[0], c


@_pt.mark.parametrize("case", sorted(_REVIEWER_DELETERS))
def test_clause15_keeps_the_DELETING_shapes_verdicts_while_the_readers_go_quiet(monkeypatch, case):
    """THE FALSE-NEGATIVE HALF OF ROUND 4's MAJOR 2, and the reason a FP fix is measured on the whole
    case set. A read-side exclusion that quietened the arm-report row by quietening the belt would
    have bought the reader's silence with a deleter's: all three of the reviewer's deleting shapes
    keep EXACTLY the verdict they had before it (`r2c/rev3/REV3_N_adv3.json`, the `with_SHIPPED_rule`
    column) -- the aliased filtered rebuild charged at build, and the two the belt declares it cannot
    see (`.update()`, and the truncating slice of the join) charged by the EXECUTED LAW instead, which
    is what makes that residual a declared limit and not a hole."""
    src = _REVIEWER_DELETER_SRC[case]
    n_build, n_law = _REVIEWER_DELETERS[case]
    compile(src, "<" + case + ">", "exec")
    monkeypatch.setattr(sbl, "_answer_source", lambda _s=src: _s)
    errs = sbl._check_chain_lints_append_only()
    assert len(errs) == n_build, (case, errs)
    rep = sbl.chain_append_only_report(_exec_case(src), ())
    assert len(rep["errors"]) >= n_law, (case, rep["errors"][:2])
    assert rep["changed"], (case, "the probe never fired -- the case proves nothing")


@_pt.mark.parametrize("case", sorted(_REVIEWER_CONFORMING))
def test_clause15_leaves_the_reviewers_two_CONFORMING_shapes_clean_on_both_readings(monkeypatch, case):
    """The other half of the same set: the reference written through one intermediate name, and the
    reference that pops a LOCAL options dict. Neither is a deletion of anything the reader was served,
    and both must stay clean at build AND under the executed law -- a fence that charges the shape a
    builder reaches for is a fence that gets deleted."""
    src = _REVIEWER_CONFORMING[case]
    compile(src, "<" + case + ">", "exec")
    monkeypatch.setattr(sbl, "_answer_source", lambda _s=src: _s)
    assert sbl._check_chain_lints_append_only() == [], case
    rep = sbl.chain_append_only_report(_exec_case(src), ())
    assert rep["errors"] == [], (case, rep["errors"])
    assert rep["changed"], (case, "the case never fired")


def test_clause15_grades_the_RAISE_PER_COUNTER_and_not_any_augassign_anywhere(monkeypatch):
    """REVIEW MAJOR 1 (round 4), closed with the reviewer's own control. Round 3 asked whether the
    function carried ANY augmented assignment (`any(isinstance(n, ast.AugAssign) ...)`), which
    `clause += ...` on a LOCAL STRING satisfies -- so the rule reds only on a function containing no
    `+=` at all, and the deck's `no_counter` case fired for a reason it could not fail.

    THE CONTROL IS THE REFERENCE WITH ITS ONE COUNTER RAISE REPLACED BY `_n = 0; _n += 1`: the counter
    is still DECLARED in the census literal, the function still carries an augmented assignment, and
    the number the arm report reads is never produced. Measured at round 3: ZERO build errors
    (`r2c/rev3/REV3_N_adv2.json`, `counter_never_raised_but_an_unrelated_augassign_exists`)."""
    compile(_UNRAISED_COUNTER, "<unraised>", "exec")
    assert "_n += 1" in _UNRAISED_COUNTER and _SKIP_LINE not in _UNRAISED_COUNTER
    assert 'census["corrected"] += 1' in _UNRAISED_COUNTER, "the unrelated raise must still be there"
    monkeypatch.setattr(sbl, "_answer_source", lambda: _UNRAISED_COUNTER)
    errs = sbl._check_chain_lints_append_only()
    assert len(errs) == 1, errs
    assert "never increments its own counter" in errs[0] and "chain_hops_skipped" in errs[0], errs
    # ...and the reference itself, whose raise is under the counter's own constant key, stays clean
    monkeypatch.setattr(sbl, "_answer_source", lambda: _GOOD_LINT)
    assert sbl._check_chain_lints_append_only() == []


def test_clause15_reds_the_SHIPPED_pass_when_every_counter_raise_is_taken_out_of_it(monkeypatch):
    """THE SURGERY PIN, on the SHIPPED function and never a stand-in (`r2c/rev3/REV3_N_adv3.json`).
    The reviewer took `answer._chain_lints`, replaced all five of its counter raises with `pass`, and
    re-graded: the clause returned `[]` and `_chain_lint_functions` still named it the producer of all
    four counters. A counter nothing raises reads zero for free, and a zero the arm report cannot tell
    from "nothing happened" is the census-row-with-two-meanings failure this estate keeps paying for.

    IT IS PINNED PER COUNTER because the number is per counter: FOUR errors, one naming each. The cut
    is asserted NON-VACUOUS -- a surgery that removed nothing would pass this test by doing nothing --
    and the surgical source is asserted to still DECLARE all four, so what the pin measures is the
    RAISE half and not the declaration half."""
    src = sbl._answer_source()
    node = [n for n in _ast.walk(_ast.parse(src))
            if isinstance(n, _ast.FunctionDef) and n.name == "_chain_lints"][0]
    seg = _ast.get_source_segment(src, node)
    kept, cut = [], []
    for ln in seg.splitlines(True):
        s = ln.strip()
        if re.match(r"^census\[[^\]]+\]\s*\+=", s) or re.match(r"^census\[[^\]]+\]\s*=\s*census", s):
            cut.append(s)
            kept.append(ln[:len(ln) - len(ln.lstrip())] + "pass\n")
        else:
            kept.append(ln)
    surgery = "".join(kept)
    assert len(cut) >= 4, cut            # NON-VACUITY: the surgery really took the raises out
    compile(surgery, "<surgery>", "exec")
    _sn = [n for n in _ast.walk(_ast.parse(surgery))
           if isinstance(n, _ast.FunctionDef) and n.name == "_chain_lints"]
    declared = {c for c in sbl._chain_stores(_sn[0]) if c.startswith("chain_")}
    assert declared == set(sbl.CHAIN_LINT_COUNTERS), sorted(declared)
    monkeypatch.setattr(sbl, "_answer_source", lambda: surgery)
    found = sbl._chain_lint_functions(_ast.parse(surgery), surgery)
    for counter in sbl.CHAIN_LINT_COUNTERS:
        assert [n for n, _ in found[counter]] == ["_chain_lints"], counter
    errs = sbl._check_chain_lints_append_only()
    assert len(errs) == len(sbl.CHAIN_LINT_COUNTERS), errs
    for counter in sbl.CHAIN_LINT_COUNTERS:
        assert any("never increments its own counter" in e and counter in e for e in errs), counter


def test_clause15_names_the_SHIPPED_pass_as_the_producer_of_all_four_counters():
    """THE CROSS-LANE PIN, against the producer's own object and never a stand-in. `answer._chain_lints`
    must be the function this clause grades, for every counter in the roster, and the served write it
    is graded on must be the one it really makes -- `structured[field]` and the token list split out of
    it. A pin that asserted against invented names is how four owner-ordered surfaces rendered nothing
    while every deck was green."""
    src = sbl._answer_source()
    found = sbl._chain_lint_functions(_ast.parse(src), src)
    for counter in sbl.CHAIN_LINT_COUNTERS:
        assert [n for n, _ in found[counter]] == ["_chain_lints"], counter
    node = [n for n in _ast.walk(_ast.parse(src))
            if isinstance(n, _ast.FunctionDef) and n.name == "_chain_lints"][0]
    assert sorted({b for b, _p, _n in sbl._chain_served_writes(node)}) == ["structured", "toks"]
    assert sbl._check_chain_lints_append_only() == []


def test_clause15_reads_the_counter_as_code_and_never_as_prose(monkeypatch):
    """A counter named in a BLOCK NOTE is documentation, not a producer. A clause that red-flagged the
    note would be a fence firing on its own documentation -- and lane A writes the note first."""
    monkeypatch.setattr(sbl, "_answer_source",
                        lambda: "# the chain_hops_skipped counter is produced below\n"
                                "def f():\n    return 1\n")
    assert sbl._check_chain_lints_append_only() == []
    assert [w for w in sbl.state_board_warnings() if "clause 15" in w]


def test_clause15_names_an_unparseable_answer_rather_than_swallowing_it(monkeypatch):
    monkeypatch.setattr(sbl, "_answer_source", lambda: 'x = ("chain_hops_skipped"\n')
    errs = sbl._check_chain_lints_append_only()
    assert errs and "does not parse" in errs[0]


def test_clause15_reads_answer_py_by_path_and_never_imports_it():
    """The source join is the point: this module is imported by `config_check` and by decks that render
    nothing, and importing the serving answer module to grade three functions inside it would drag a
    provider stack and every registry loader into a config check."""
    src = _pl.Path(sbl.__file__).read_text(encoding="utf-8")
    body = src.split("def _check_chain_lints_append_only")[1].split("\ndef ")[0]
    assert "import answer" not in body and "graphrag.answer" not in body
    reader = src.split("def _answer_source")[1].split("\ndef ")[0]
    assert 'read_text' in reader and '"answer.py"' in reader
    assert "answer.py" in sbl._answer_source()[:200] or len(sbl._answer_source()) > 1000


# -- THE NEGATIVE CORPUS: UNSEEN REAL-SEAT PROSE, never the author's own case list --------------------
#: THE TWO OF THE FIVE SERVED BODIES THE CONFORMING REFERENCE CORRECTS NOTHING IN (round-4 review
#: MINOR 2, ruled a REQUIREMENT). Measured on the five 2026-09-16 in-VPC smoke notes: 120 / 1, 78 / 2,
#: **63 / 0**, **68 / 0**, 94 / 1 sentences and corrections. A law that ran on a body and changed
#: nothing has graded nothing there, so the two are NAMED rather than counted -- and naming them is
#: what makes the count drift loud: a body that stops firing joins this tuple by a deliberate edit or
#: reds the deck.
_VACUOUS_SERVED_BODIES: tuple = ("quick_rv_corn_wheat.md", "quick_rv_palm_rapeoil.md")
def test_a_conforming_chain_lint_loses_no_sentence_of_the_five_served_bodies():
    """The BEHAVIOURAL half of the append-only law, measured on prose nobody wrote for this fence: the
    five 2026-09-16 in-VPC smoke bodies (standing memory --
    `feedback_negative_corpus_must_be_unseen_prose`). A conforming lint may APPEND; it may not shorten,
    drop or reorder a sentence, and a second run must change nothing.

    ROUND 4 (review MINOR 2, ruled a REQUIREMENT) MAKES THE VACUITY A STATEMENT AND NOT A SILENCE. The
    law's pass on a body it never fired on proves nothing about the law, and two of these five bodies
    are exactly that -- `quick_rv_corn_wheat.md` and `quick_rv_palm_rapeoil.md`, 63 and 68 sentences,
    ZERO corrections, `changed == []`. The other three carry a correction and their pass is real, so
    the law is asserted NON-VACUOUS on them (`rep["changed"]` names the field the lint moved) and the
    two are NAMED here as vacuous rather than counted as evidence. The same clause every synthetic pin
    in this deck already carries: a case that proves nothing cannot pass as a case that proves
    something."""
    d = _smoke_answers()
    if d is None:
        _pt.skip("the five 2026-09-16 served bodies are not on this machine")
    lint = _exec_case(_GOOD_LINT)
    n_sent = fired = 0
    vacuous: list = []
    for b in sorted(d.glob("*.md")):
        text = b.read_text(encoding="utf-8", errors="replace")
        before = [t for i, t in enumerate(reg._SENT_KEEP.split(text)) if i % 2 == 0]
        # THE SAME LAW, ON THE SAME RULE, over prose nobody wrote for this fence: the executed
        # report is what the deck's synthetic cases are graded by, and it is what grades the
        # corpus -- one rule with two populations, never two rules.
        rep = sbl.chain_append_only_report(lint, (), probe={"body": text})
        assert rep["errors"] == [], (b.name, rep["errors"][:2])
        box = {"body": text}
        here = lint(box, ())["corrected"]
        fired += here
        # THE NON-VACUITY CLAUSE, per body: where the lint corrected a sentence the law must have
        # SEEN a page move, and where it corrected nothing the body is named as vacuous by name.
        if here:
            assert rep["changed"] == ["body"], (b.name, here, rep["changed"])
        else:
            assert rep["changed"] == [], (b.name, rep["changed"])
            vacuous.append(b.name)
        after = [t for i, t in enumerate(reg._SENT_KEEP.split(box["body"])) if i % 2 == 0]
        assert len(after) == len(before), b.name
        for x, y in zip(before, after):
            assert len(y) >= len(x), (b.name, x[:80])
            assert y.startswith(x.rstrip().rstrip(".;!?")), (b.name, x[:80])
        n_sent += len(before)
    # MEASURED 2026-09-17 on the five served bodies: 423 sentences (120 / 78 / 63 / 68 / 94), 4
    # corrected = 0.95%. The floor keeps this a REAL corpus rather than a fixture; the ceiling is
    # DESIGN E's own rule for every lint in this movement -- "any lint that fires on more than 10% of
    # the sentences in the five notes is too broad and goes back".
    assert n_sent >= 400, n_sent
    assert fired <= n_sent // 10, (fired, n_sent)
    assert fired, "the whole corpus is vacuous -- the law never fired on any of the five bodies"
    assert sorted(vacuous) == sorted(_VACUOUS_SERVED_BODIES), sorted(vacuous)


# -- clause 9: the chain's own closed vocabulary ------------------------------------------------------
def test_clause9_grades_the_chain_decline_words_and_each_has_a_reader_sentence():
    """DESIGN B.3's count line names a reason per chain it did not render in full, and a word without a
    sentence renders the fallback -- a reader would meet a generic line where a specific fact was
    owed."""
    from leviathan.graphrag.state import board as B
    from leviathan.graphrag.state import render as R
    assert B.CHAIN_REASONS == ("render_cap", "edge_hop_cap", "below_print_line", "no_measured_hop",
                               "cross_unpriced")
    assert B.PATH_REASONS is B.CHAIN_REASONS, "one vocabulary, not two -- the leg keeps its name"
    for w in B.CHAIN_REASONS:
        assert w in R.ABSENCE_WHY, w
        assert R.ABSENCE_WHY[w].strip()
        assert not any(ch.isdigit() for ch in R.ABSENCE_WHY[w]), w   # SB-X is letters-only
    assert sbl._check_absence_vocabulary() == []


def test_clause9_fires_when_a_chain_word_loses_its_sentence(monkeypatch):
    from leviathan.graphrag.state import render as R
    trimmed = {k: v for k, v in R.ABSENCE_WHY.items() if k != "below_print_line"}
    monkeypatch.setattr(R, "ABSENCE_WHY", trimmed)
    errs = sbl._check_absence_vocabulary()
    assert any("below_print_line" in e for e in errs), errs


def test_clause9_grades_the_chain_vocabulary_even_if_the_leg_is_renamed(monkeypatch):
    """THE BELT. `CHAIN_REASONS` reaches clause 9 through `LEG_REASONS['path']` today, so seeding it by
    name adds no word and moves no message. The day someone renames that key the three chain words
    would leave the graded set SILENTLY -- which is how a closed vocabulary loses its reader sentence
    without anybody deciding to."""
    from leviathan.graphrag.state import board as B
    from leviathan.graphrag.state import render as R
    legs = {k: v for k, v in B.LEG_REASONS.items() if k != "path"}
    monkeypatch.setattr(B, "LEG_REASONS", legs)
    trimmed = {k: v for k, v in R.ABSENCE_WHY.items() if k != "cross_unpriced"}
    monkeypatch.setattr(R, "ABSENCE_WHY", trimmed)
    errs = sbl._check_absence_vocabulary()
    assert any("cross_unpriced" in e and "board.CHAIN_REASONS" in e for e in errs), errs


# -- the narration literal reaches the lint roster ----------------------------------------------------
def test_clause11_carries_the_chain_movements_own_grade():
    """`check_literals` is clause 11's payload and the chain movement's desk-register grade rides it --
    so a register trip in a flag-scoped literal is a BUILD failure and never a stripped answer."""
    assert _nar.check_literals() == []
    assert _nar._check_chain_movement() == []
    assert sbl.check_state_board() == []


# === CLAUSE 16: near_asof IS READ ON THE PAGE AND FILTERS NOWHERE (DESIGN C.4) ======================
#: The one spelling. There is no second name for the flag anywhere in the state package, which is what
#: makes a source join over it mean anything at all.
_NEAR = "near_asof"

#: FOUR SURGICAL FILTERS, each one a shape a real edit could take, written against the source this
#: clause reads. A lint that has never been shown failing is a lint nobody has graded.
_FILTERED_SOURCES = {
    "comprehension": (
        "def analog_selection_clauses(a):\n"
        "    rows = [r for r in a if not r.get('near_asof')]\n"
        "    return rows\n"
        "def sb_analog_header(a, *, chain_dims=()):\n"
        "    return analog_selection_clauses(a)\n"),
    "continue": (
        "def analog_selection_clauses(a):\n"
        "    out = []\n"
        "    for r in a:\n"
        "        if r.get('near_asof'):\n"
        "            continue\n"
        "        out.append(r)\n"
        "    return out\n"
        "def sb_analog_header(a, *, chain_dims=()):\n"
        "    return analog_selection_clauses(a)\n"),
    "return": (
        "def analog_selection_clauses(a):\n"
        "    if a.get('near_asof'):\n"
        "        return ''\n"
        "    return 'x'\n"
        "def sb_analog_header(a, *, chain_dims=()):\n"
        "    return analog_selection_clauses(a)\n"),
    "remove": (
        "def analog_selection_clauses(a, rows):\n"
        "    rows.remove(a['near_asof'])\n"
        "    return rows\n"
        "def sb_analog_header(a, *, chain_dims=()):\n"
        "    return analog_selection_clauses(a, [])\n"),
}


def _with_render_source(monkeypatch, src: str):
    """Point clause 16's reader at a STATED source, leaving every other module the tree's."""
    real = sbl._state_source
    monkeypatch.setattr(sbl, "_state_source",
                        lambda name: src if name == "render.py" else real(name))


def test_CLAUSE16_is_GREEN_on_the_tree_and_the_whole_roster_is_SIXTEEN():
    """The roster grew by one and ``check_state_board()`` is still empty. ``config_check`` only
    DELEGATES here, so a sixteenth clause needs no edit in a file this lane may not touch."""
    import inspect
    assert sbl._check_analog_near_asof() == []
    assert sbl.check_state_board() == []
    src = inspect.getsource(sbl.check_state_board)
    assert "_check_analog_near_asof()" in src
    assert src.count("errs += _check") == 16, src.count("errs += _check")


def test_the_SB_A_SAMPLE_IS_WHAT_THE_PRODUCER_RENDERS_AND_CARRIES_ONE_FLOOR_YEAR():
    """**THE BANKED SAMPLE IS THE CLASS'S OWN OUTPUT OR IT GRADES NOTHING.** ``_check_row_classes``
    asserts disjointness on these lines, so a sample that drifts from the producer greens a clause
    about a page that no longer exists. This pin joins the two: the SB-A sample is re-composed HERE
    by ``render.sb_analog_header`` off a row carrying exactly the fields the sample states, and it
    has to come back word for word.

    AND IT CARRIES ONE YEAR (round-2 blockers 1 and 4). The round-1 sample printed "three such
    crossings since 1999" and "which together reach back to 2022" -- two answers to one question on
    one line, which is the defect the ruling closed. A sample with two different years fails here."""
    import re as _re

    from leviathan.graphrag.state import render as _R

    line = [s for s in _sb_a_samples() if s.startswith("LIKE STATE El Nino on CBOT soybeans:")]
    assert len(line) == 1, line
    years = set(_re.findall(r"(?:since|reach back to) (\d{4})", line[0]))
    assert years == {"2023"}, years
    row = {"driver_id": "El_Nino", "contract": "soybeans_cbot", "date": "2013-06-30",
           "asof": "2026-09-07", "floor_year": "2022", "n_candidates": 159,
           "n_candidates_head": 3, "pool_rank": 1, "dims_declared": 3, "dims_seen": 2,
           "dims_unread": 1, "sign_agree": 2, "sign_seen": 2, "dir_agree": 0, "dir_seen": 2,
           "precedes_dims": 1, "near_asof": False, "months_to_asof": 158,
           "record_span": ({"id": "El_Nino", "first_date": "1999-12-31"},
                           {"id": "La_Nina", "first_date": "1999-12-31"},
                           {"id": "export_pace_lag", "first_date": "2023-11-03"})}
    composed = _R.sb_analog_header(row)
    assert composed.startswith(line[0]), (line[0], composed[:len(line[0]) + 60])


def _sb_a_samples():
    """The sample lines ``lint._check_row_classes`` banks, read off its own source -- the function
    builds them in a local dict, so this is the one way to see them without re-declaring them."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(sbl._check_row_classes).lstrip())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "SB-A" and isinstance(v, ast.Constant):
                    out.append(v.value)
    return out


def test_CLAUSE16_REDS_a_render_that_FILTERS_a_picked_row_on_near_asof(monkeypatch):
    """**THE DESIGN ASKED FOR A FENCE THAT DELETES AND THIS IS THE CLAUSE THAT REFUSES IT.** DESIGN
    C.4 asks for a lint asserting the chosen date is not inside ``min_separation_months`` of the
    as-of -- which would take a stanza the selection PICKED off the page. Doctrine is the other way
    round, and ``analogs.select_analogs`` already says so: "``near_asof`` IS A FLAG AND NEVER A
    FILTER". So the render APPENDS the distance in months and this clause reds every shape that
    would remove the row instead."""
    for shape, src in sorted(_FILTERED_SOURCES.items()):
        _with_render_source(monkeypatch, src)
        errs = sbl._check_analog_near_asof()
        assert errs, shape
        assert all(_NEAR in e for e in errs), (shape, errs)


def test_CLAUSE16_REDS_a_render_that_STOPPED_READING_the_flag_at_all(monkeypatch):
    """The state it was written against: ``near_asof`` was live and SILENT. On the served fixture
    board ``attached_event`` at deep renders a stanza picked 2026-01-31 against an as-of of
    2026-09-07 and at max picks 2025-12-31 -- both flagged True by the selection, both rendered, and
    the word appeared nowhere in ``render.py``, ``watch.py``, ``lint.py``, ``narration.py`` or
    ``board.py``. A reader was shown the present state described as its own precedent."""
    _with_render_source(monkeypatch,
                        "def sb_analog_header(a, *, chain_dims=()):\n    return 'LIKE STATE'\n")
    errs = sbl._check_analog_near_asof()
    assert errs and "reads `near_asof` nowhere" in errs[0], errs
    # AND A READER THE HEADER DOES NOT CALL IS A REFERENCE WITHOUT A READER -- the same defect.
    _with_render_source(monkeypatch,
                        "def somewhere_else(a):\n    return a['near_asof']\n"
                        "def sb_analog_header(a, *, chain_dims=()):\n    return 'LIKE STATE'\n")
    errs = sbl._check_analog_near_asof()
    assert errs and "still no reader on the page" in errs[0], errs
    # AN UNREADABLE MODULE IS A SKIP, never a red build on a file it could not open; an UNPARSABLE one
    # is a single, named error rather than a silent pass.
    _with_render_source(monkeypatch, "")
    assert sbl._check_analog_near_asof() == []
    _with_render_source(monkeypatch, "def f(:\n")
    errs = sbl._check_analog_near_asof()
    assert len(errs) == 1 and "does not parse" in errs[0], errs


def test_CLAUSE16_reads_the_flag_WHERE_THE_SHIPPED_RENDER_READS_IT():
    """The join is to ``render.sb_analog_header``'s own call graph, so a read in a function nothing
    calls cannot satisfy it. On the tree the reader is ``analog_selection_clauses``, which the header
    calls and which APPENDS -- no ``continue``, no ``return``, no ``del``, no comprehension filter."""
    import ast
    import inspect

    from leviathan.graphrag.state import analogs as A
    from leviathan.graphrag.state import render as R
    src = inspect.getsource(R.analog_selection_clauses)
    assert _NEAR in src
    body = src.split('"""')[2]
    assert "continue" not in body and "del " not in body
    assert "before the as-of this page is read at" in body, "it APPENDS the distance"
    assert "months_to_asof" in body, "and the distance is the SELECTION's, not a second calendar"
    assert "analog_selection_clauses(a)" in inspect.getsource(R.sb_analog_header)
    # AND THE SELECTION STILL STAMPS IT AS A FLAG, never as a filter -- the other half of the contract.
    sel = inspect.getsource(A.select_analogs)
    assert '"near_asof"' in sel and "months_to_asof" in sel
    assert sbl._near_filter_shapes(ast.parse(sel).body[0], "analogs.select_analogs()") == []
    # EVERY STATE MODULE THE CLAUSE GRADES IS ONE THIS PACKAGE ACTUALLY SHIPS.
    import pathlib
    here = pathlib.Path(A.__file__).resolve().parent
    for name in sbl._ANALOG_ROW_MODULES:
        assert (here / name).exists(), name
