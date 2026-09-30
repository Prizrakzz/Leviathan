"""LANE AN -- FIX SITTING 4 (launched 2026-09-29, CONTRACT C4-19): the watch list's own words.

  AN4-1  the three watch absence LABELS read the reason word through ONE map (``watch.WATCH_ABSENCE_LABELS``) in the
         book's words ("here", the register table's own column for "this page") -- never "on this page", which
         was a charged register token on every under-filled block (36 of the 56 rebuilt boards, the live 2026-09-29
         smoke 2024 run-2 block). The coverage instrument reads the manifest's REASON word (sitting 3, lane R), so
         the label is free to move.
  AN4-2  (a) ``watch_core_standing`` -- the fourth absence word -- is stamped where a core stops short because
         EVERY reading the draw could have seated there and did not is STANDING (its period longer than the
         horizon): 10 of the 56 rebuilt boards, where HEAD printed no note; a tail that mixes standing and
         cap-held rows keeps HEAD's silence; the word is stamped only where the board's closed enum declares it
         and the render carries its sentence (the two halves that are not lane AN's files).
         (b) ``horizon_miss_clause(..., window=(opens, closes))`` names a missed WINDOW by its two days, never its
         opening day as the print (4 of 4 live notes on the smoke max block, 47 of 47 on the drive).

THE FACTS these pins guard are the block's served words; nothing here hands the writer a sentence. The harness boards
are the estate's own offline scenarios; the constructed board exists where the banked corpus carries the case only on
a rebuilt board (said in the pin)."""
import pytest
from leviathan.graphrag import register as reg
from leviathan.graphrag.state import __main__ as H
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.feeders import state_from_arrays
from leviathan.graphrag.state.lagbands import parse_lag

ASOF = "2026-09-07"
STANDING = "watch_core_standing"
_MEMO: dict = {}
#: EVERY combination of absence_row's three switches and the word each one stamps -- the producer's own table.
COMBOS = {(False, False, False): "watch_floor_unmet", (True, False, False): "watch_nothing_further",
          (True, True, False): "watch_core_capped", (True, True, True): STANDING}


def _scenario(name):
    if name not in _MEMO:
        _MEMO[name] = H.build_scenario(name)
    return _MEMO[name]


def _months(n, start_year=2010, start_month=1):
    out, y, m = [], start_year, start_month
    for _ in range(n):
        last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        out.append(f"{y:04d}-{m:02d}-{last:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _decile_row(ref, *, table="silver_psd", driver_id="export_pace", contract="soybeans_cbot", cadence="monthly"):
    """A loud row whose reading sits in its own record's top decile, with NO convention (the floor's record_tail) --
    sitting 3's lane AN deck's own builder."""
    vals = [float(i) for i in range(60)] + [500.0]
    st = state_from_arrays(ref, vals, _months(len(vals)), cadence=cadence, asof=ASOF, unit="1000 MT",
                           narrate_unit="1000 MT", windows={"monthly": 60, "annual": 60, "weekly": 60},
                           convention=None, table=table, metric="value")
    r = B.NodeRow(contract=contract, driver_id=driver_id, lag_band=parse_lag("1-2 quarters"), state=st,
                  receipts={"n": 0, "newest_date": None, "oldest_date": None, "top": []})
    r.legs["loud"] = True
    return r


def _board(rows, *, mode="deep", horizon=None):
    bd = B.Board(asof=ASOF, mode=mode, knobs=B.board_knobs_of(mode),
                 anchors=(B.Anchor(contract=rows[0].contract, source="named", named=True),))
    bd.rows = list(rows)
    bd.order = tuple(r.key for r in rows)
    bd.horizon_months = horizon
    for r in rows:
        st = r.state
        bd.windows[r.key] = {"near": st.level_date, "reading": st.level_date, "state_date": st.level_date,
                             "knowledge_date": st.knowledge_date, "analog_dates": ()}
        bd.series[st.key.label()] = st
    return bd


def _standing_board(*, mixed: bool = False):
    """CONSTRUCTED -- the banked corpus carries this case only on REBUILT boards (the 10 of the drive, B56-S4): a
    three-month deep board whose one monthly decile reading turns inside the horizon and whose two ANNUAL decile
    readings (365 days > 91.2) are standing. ``mixed`` adds three more monthly readings, so a non-standing reading
    is held back by the kind cap as well (a third of a five-item core is two of a kind)."""
    rows = [_decile_row("m_ref_0", driver_id="m_driver_0"),
            _decile_row("psd_ref_a", driver_id="annual_a", cadence="annual"),
            _decile_row("psd_ref_b", driver_id="annual_b", cadence="annual")]
    if mixed:
        rows += [_decile_row(f"m_ref_{i}", driver_id=f"m_driver_{i}") for i in (1, 2, 3)]
    return _board(rows, horizon=3)


def _declare(monkeypatch, on: bool):
    """THE TWO CROSS-LANE HALVES OF C4-19 THAT ARE NOT LANE AN'S FILES, set explicitly either way so the pin reads
    the same on every integration order: ``board.WATCH_REASONS`` declaring the word (board.py) and
    ``render.ABSENCE_WHY`` carrying a sentence for it (lane R). The sentence is a PIN STAND-IN, never shipped."""
    words = tuple(w for w in B.WATCH_REASONS if w != STANDING) + ((STANDING,) if on else ())
    monkeypatch.setattr(B, "WATCH_REASONS", words)
    monkeypatch.setitem(B.LEG_REASONS, "watch", words)
    if on:
        monkeypatch.setitem(R.ABSENCE_WHY, STANDING, "a pin stand-in sentence for the standing core")
    else:
        monkeypatch.delitem(R.ABSENCE_WHY, STANDING, raising=False)


def _notes(rows):
    return [w for w in rows if w.get("form") == "absence" and w.get("kind") != "release_footnote"]


# ═══ AN4-1: the labels, read by the reason word, in the book's words ════════════════════════════════════════
def test_AN41_every_absence_word_takes_its_label_from_ONE_map_keyed_by_the_word():
    assert tuple(WA.WATCH_ABSENCE_LABELS) == ("watch_floor_unmet", "watch_nothing_further", "watch_core_capped",
                                              STANDING)                 # APPEND-NEVER-SORT
    for (partial, alternates, standing), word in COMBOS.items():
        row = WA.absence_row(partial=partial, alternates=alternates, standing=standing)
        assert row["reason"] == row["declined"] == row["kind"] == word
        assert row["label"] == WA.WATCH_ABSENCE_LABELS[word]
    # HEAD's two graded calls (state/lint.py) keep their words
    assert WA.absence_row(partial=True, alternates=True)["reason"] == "watch_core_capped"
    assert WA.absence_row(partial=True)["reason"] == "watch_nothing_further"
    # `standing` alone never stamps the fourth word: it names a SHORT core that HAS alternates
    assert WA.absence_row(standing=True)["reason"] == "watch_floor_unmet"
    assert WA.absence_row(partial=True, standing=True)["reason"] == "watch_nothing_further"


def test_AN41_no_label_talks_about_the_page_and_every_SB_X_line_is_register_clean():
    """HEAD's three labels said "... on this page" -- the register table's own charged token ("this page" ->
    "here, in this note"), printed on 36 of the 56 rebuilt boards' absence lines and on the live smoke block."""
    for word, label in WA.WATCH_ABSENCE_LABELS.items():
        assert "page" not in label and label.isascii() and not any(ch.isdigit() for ch in label)
        assert reg.desk_register_hits(label) == [] and reg.register_leaks(label) == []
        assert label.endswith(" here")                                 # the table's own column for the token
    for word in ("watch_floor_unmet", "watch_nothing_further", "watch_core_capped"):
        line = R.sb_absence(WA.WATCH_ABSENCE_LABELS[word], word)
        assert R.classify(line) == ("SB-X",), line
        assert "this page" not in line and not any(ch.isdigit() for ch in line)
        assert [h for h in reg.desk_register_hits(line) if h[0] != "board"] == [], line   # "BOARD ABSENCE" is the class head


def test_AN41_the_coverage_instrument_reads_the_REASON_word_and_never_the_label():
    """THREAT AN-a: `watch_admitted_zero` keys on the manifest's `watch_absence` (render.py, sitting 3 lane R), so
    the same manifest under HEAD's label and under the book's label reads the same numbers."""
    nom = R.sb_watch({"kind_words": WA.NONOBVIOUS_KIND_WORDS["tail_reading"], "label": "export pace on CBOT soybeans",
                      "backing_handle": 7, "slot": "ceiling", "slot_size": 1, "slot_index": 1, "what": "w",
                      "dates": ""})
    nom_m = {"role": "watch", "line": nom, "handles": (), "tokens": (("export pace",),)}
    for word in ("watch_floor_unmet", "watch_nothing_further", "watch_core_capped"):
        old = WA.WATCH_ABSENCE_LABELS[word].replace(" here", " on this page")
        covs = []
        for label in (old, WA.WATCH_ABSENCE_LABELS[word]):
            ab = {"role": "watch", "line": R.sb_absence(label, word), "handles": (), "tokens": (),
                  "watch_absence": word}
            covs.append(R._nomination_coverage([nom_m, ab], [], lambda m: False, ASOF, text=""))
        assert covs[0] == covs[1], word
        assert covs[1]["watch_admitted_zero"] is (word == "watch_floor_unmet")


# ═══ AN4-2 (a): the standing core, said where it is whole ══════════════════════════════════════════════════
def test_AN42_the_standing_word_is_stamped_where_EVERY_further_reading_is_standing(monkeypatch):
    _declare(monkeypatch, True)
    bd = _standing_board()
    rows = WA.nonobvious_rows(bd, analogs=())
    core = [w for w in rows if w.get("slot") == "ceiling"]
    alts = [w for w in rows if w.get("slot") == "nomination"]
    assert len(core) < WA.nonobvious_k("deep") and core and alts
    assert all(w["standing"] and w["horizon_miss"] == "cadence" for w in alts)
    notes = _notes(rows)
    assert [(n["reason"], n["label"]) for n in notes] == [(STANDING, WA.WATCH_ABSENCE_LABELS[STANDING])]
    assert rows.index(notes[0]) > rows.index(alts[-1])                 # the note closes the list, as HEAD's do
    assert WA.watch_leg(bd, rows)["outcome"] == "fired"                # a note beside rows never votes a decline


def test_AN42_a_tail_that_MIXES_standing_and_cap_held_readings_keeps_HEADs_silence(monkeypatch):
    """Neither sentence is true of the whole tail: the caps' note would deny the standing rows' own reason and the
    standing note would deny the cap. The harness's soybeans_now (max, three months) is the estate's own case; the
    constructed board is the same shape on a deep board."""
    _declare(monkeypatch, True)
    bd = _standing_board(mixed=True)
    rows = WA.nonobvious_rows(bd, analogs=())
    alts = [w for w in rows if w.get("slot") == "nomination"]
    assert any(w["standing"] for w in alts)
    cands = WA.nonobvious_candidates(bd, analogs=())
    assert any(not WA._row_clock(bd, bd.row(*c["row"]).state)["standing"] and c["row"] not in
               {tuple(w["row"]) for w in rows if w.get("slot") == "ceiling"} for c in cands)
    assert not _notes(rows)
    ctx = _scenario("soybeans_now")
    rows = WA.nonobvious_rows(ctx["board"], analogs=ctx["analogs"])
    assert any(w.get("standing") for w in rows if w.get("slot") == "nomination")
    assert not _notes(rows)


def test_AN42_the_word_is_never_stamped_where_the_estate_cannot_say_it(monkeypatch):
    """The board's closed enum (board.py) and the render's sentence (lane R) are read DEFENSIVELY: with either half
    missing the draw keeps HEAD's line (no note), never `render.ABSENCE_FALLBACK` under an undeclared word."""
    for board_on, render_on in ((False, False), (True, False), (False, True)):
        _declare(monkeypatch, False)
        if board_on:
            words = tuple(B.WATCH_REASONS) + (STANDING,)
            monkeypatch.setattr(B, "WATCH_REASONS", words)
            monkeypatch.setitem(B.LEG_REASONS, "watch", words)
        if render_on:
            monkeypatch.setitem(R.ABSENCE_WHY, STANDING, "a pin stand-in sentence for the standing core")
        assert WA._absence_word_declared(STANDING) is False
        assert not _notes(WA.nonobvious_rows(_standing_board(), analogs=()))
    _declare(monkeypatch, True)
    assert WA._absence_word_declared(STANDING) is True
    for word in ("watch_floor_unmet", "watch_nothing_further", "watch_core_capped"):
        assert WA._absence_word_declared(word) is True                 # HEAD's three words are declared on HEAD


def test_AN42_the_standing_word_moves_no_drawn_row_and_no_other_note(monkeypatch):
    """The note is APPENDED: every drawn row -- slot, place, kind, row, stamps, marks -- is the same with the word
    declared and without it, on the three harness boards and the constructed one."""
    boards = [(_scenario(n)["board"], _scenario(n)["analogs"]) for n in H.SCENARIOS] + [(_standing_board(), ())]
    keys = ("slot", "slot_index", "slot_size", "kind", "row", "call_leg", "turns_inside", "standing",
            "horizon_miss", "next_print", "next_print_opens", "next_print_closes")
    for bd, ana in boards:
        seen = []
        for on in (False, True):
            _declare(monkeypatch, on)
            rows = WA.nonobvious_rows(bd, analogs=ana)
            seen.append(([[w.get(k) for k in keys] for w in rows if w.get("slot")],
                         [n["reason"] for n in _notes(rows) if n["reason"] != STANDING]))
        assert seen[0] == seen[1]


# ═══ AN4-2 (b): a missed window is named by its window ═════════════════════════════════════════════════════
def test_AN42_a_missed_WINDOW_is_named_by_its_two_days_never_its_opening_day():
    for cause in ("print", "cadence"):
        head = WA.horizon_miss_clause(cause, next_print="2026-10-09", faster="X")
        win = WA.horizon_miss_clause(cause, next_print="2026-10-09", faster="X", window=("2026-10-09", "2026-10-12"))
        assert "its next scheduled print is 2026-10-09," in head         # HEAD's words: the opening day as the print
        assert "between 2026-10-09 and 2026-10-12" in win
        assert "print is 2026-10-09" not in win
        # ONLY the print words move: the rest of the clause is the cause's own sentence, byte for byte
        assert win == head.replace(WA.HORIZON_PRINT_WORDS["dated"].format(date="2026-10-09"),
                                   WA.HORIZON_PRINT_WORDS["window"].format(opens="2026-10-09",
                                                                           closes="2026-10-12"), 1)
        stripped = win.replace("2026-10-09", "").replace("2026-10-12", "")
        assert not any(ch.isdigit() for ch in stripped) and win.isascii()
        assert reg.desk_register_hits(win) == [] and reg.register_leaks(win) == []


def test_AN42_no_window_or_a_one_day_window_is_HEADs_clause_byte_for_byte():
    for cause in ("print", "cadence", "not-a-cause"):
        for kw in ({}, {"next_print": "2026-10-09"}, {"next_print": "2026-10-09", "faster": "X"}):
            head = WA.horizon_miss_clause(cause, **kw)
            for window in (None, (), ("2026-10-09", "2026-10-09"), ("2026-10-09", ""), ("", "2026-10-12")):
                assert WA.horizon_miss_clause(cause, window=window, **kw) == head, (cause, kw, window)
    # the two HEAD words and their templates are untouched; the third is APPENDED
    assert tuple(WA.HORIZON_PRINT_WORDS) == ("dated", "undated", "window")
    assert set(WA.HORIZON_MISS_CLAUSES) == {"print", "cadence"}


def test_AN42_the_window_the_draw_carries_is_the_calendars_own():
    """The row's `next_print_opens` / `_closes` are `calendar.next_release`'s window ends (sitting 3 Z19); the clause
    fed them names exactly that window -- on a harness row whose rule is a window and which misses the horizon."""
    ctx = _scenario("soybeans_now")
    rows = WA.nonobvious_rows(ctx["board"], analogs=ctx["analogs"])
    missed = [w for w in rows if w.get("horizon_miss") and w.get("next_print_opens") and w.get("next_print_closes")]
    assert missed
    for w in missed:
        assert w["next_print"] == w["next_print_opens"] < w["next_print_closes"]
        clause = WA.horizon_miss_clause(w["horizon_miss"], next_print=w["next_print"], faster=w.get("horizon_faster"),
                                        window=(w["next_print_opens"], w["next_print_closes"]))
        assert "between %s and %s" % (w["next_print_opens"], w["next_print_closes"]) in clause


if __name__ == "__main__":                                  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
