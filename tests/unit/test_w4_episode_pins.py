"""W4 event playbooks -- the honest receipted-episode path + the deterministic '## Episodes' pins.

All mocked (no pg, no S3, no LLM). Pins:
  F-I     every emitted episode renders a receipt OR states it has none; nothing is dropped
  D6      min_episodes_cited / min_episode_sources / episode_absence_stated
  F-J     min_episodes_cited's BLIND SPOT is pinned as a test (a smoothed answer passes it), and the
          min_episode_lines complement catches both smoothing and confabulation
  W2b-D5  episode_magnitude_or_absence -- a magnitude ([N] handle) or an explicit no-price-record marker
"""
from __future__ import annotations

from leviathan.graphrag import eval as ev
from leviathan.graphrag import timeline as tl


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────────
def _ev_cit(i, date, source="wb_cmo_outlook", text="a report"):
    return {"id": f"E{i}", "kind": "evidence", "source": source, "date": date,
            "locator": {"kind": "doc"}, "payload": {"text": text}}


def _inj(*spans, node="drivers/frost"):
    """The trace record answer._l2_blocks stamps for the episode line it INJECTED into the prompt --
    trace['episodes_injected'] = [{node, line, spans}]. `spans` are the literal 'YYYY-MM..YYYY-MM'
    strings render_line built from e['start'][:7] / e['end'][:7], i.e. the exact windows the model was
    shown. Every enumeration pin now checks a bullet's window against THIS, so a fixture without it is a
    turn on which the engine injected nothing and no bullet can be an enumeration of anything."""
    line = "DATED EPISODES for " + node + " (report TIMESTAMPS, not descriptions): " + ", ".join(spans)
    return [{"node": node, "line": line, "spans": list(spans)}]


def _out(mech: str, cits=None, tldr="", injected=None):
    """A minimal answer-shaped dict. mech is the STRUCTURED mechanism (what the pins read); the
    out['answer'] footer deliberately re-lists EVERY handle so any pin that cheated by scanning the
    footer instead of structured prose would false-pass here. `injected` (W4-N1) is the engine's own
    record of the episode lines this turn's prompt carried; absent = nothing was injected."""
    cits = cits or []
    footer = "\n\n## Sources\n" + "\n".join(f"[{c['id']}] x" for c in cits)
    return {"answer": mech + footer, "intent": "reasoning", "evidence": [], "citations": cits,
            "structured": {"tldr": tldr, "mechanism": mech,
                           "sources": [{"ref": int(c["id"][1:])} for c in cits]},
            "trace": ({"episodes_injected": injected} if injected else {})}


def _pins(pins: dict, out: dict) -> dict:
    return ev._cascade_asserts({"contract": "arabica_coffee", "asof": "2026-06-15", "expect": pins}, out)


_EPISODES_2 = ("## Episodes\n"
               "- 1994-06..1994-08 Brazil frost: arabica settles rose to 248 c/lb [N1].\n"
               "- 2021-06..2021-08 Brazil frost: arabica settles rose to 205 c/lb [N2].\n"
               "The record holds two frost episodes [E1][E2].\n")
_INJ_2 = _inj("1994-06..1994-08", "2021-06..2021-08")            # the windows _EPISODES_2 enumerates


# ── F-I: the receipted path is honest ───────────────────────────────────────────────────────────────
def test_fi_unreceipted_episode_is_kept_and_its_absence_is_stated(tmp_path, monkeypatch):
    """The whole F-I mitigation. The thin/old/single-source episodes are exactly the ones the semantic
    top-K misses, so a receipt-less episode MUST NOT be emitted as a bare count (that IS the original
    +10-halluc mode) and MUST NOT be dropped (n is a PIT recount -- dropping understates the corpus)."""
    import json
    art = tmp_path / "episodes.json"
    art.write_text(json.dumps({"drivers/frost": [
        {"start": "1994-06-10", "end": "1994-08-01", "dates": ["1994-06-10", "1994-08-01"]},
        {"start": "2021-06-01", "end": "2021-08-20", "dates": ["2021-06-01", "2021-07-10", "2021-08-20"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    tl.reset_cache()
    # a top-K that surfaced only the 2021 prop -- the realistic shape (1994 is 11 props, one source)
    eps = tl.episodes_for("drivers/frost", "2026-01-01",
                          evidence=[{"date": "2021-07-10", "text": "frost hit southern Minas Gerais"}])
    by_start = {e["start"]: e for e in eps}
    assert set(by_start) == {"1994-06-10", "2021-06-01"}             # NOT dropped
    assert by_start["1994-06-10"]["n"] == 2 and by_start["1994-06-10"]["receipt"] is None
    assert by_start["2021-06-01"]["receipt"]["date"] == "2021-07-10"
    line = tl.render_line("frost", eps)
    assert line.count(tl._NO_RECEIPT) == 1                           # stated exactly on the thin episode
    assert "Minas Gerais" in line                                    # and the receipted one still cites
    monkeypatch.delenv("GRAPHRAG_TIMELINE")
    monkeypatch.delenv("GRAPHRAG_TIMELINE_PATH")
    tl.reset_cache()


# ── the section parser ──────────────────────────────────────────────────────────────────────────────
def test_episode_lines_counts_bullets_with_years_only():
    out = _out("## Mechanism\nIn 2021 the frost mattered.\n"
               "## Episodes\n"
               "- 1994 frost: no price record.\n"
               "1. 2021 frost: [N1].\n"
               "* 2024 drought: [N2].\n"
               "- a bullet with no year at all\n"
               "Prose mentioning 1975 is not an episode line.\n"
               "## What to watch\n- 2026 crop tour\n")
    lines = ev._episode_lines(out)
    assert len(lines) == 3                                           # 3 dated bullets in ## Episodes only
    assert "1994" in lines[0] and "2021" in lines[1] and "2024" in lines[2]
    assert ev._episode_lines(_out("## Mechanism\n- 2021 frost [N1]\n")) == []   # no section -> nothing


def test_episode_lines_ignores_fenced_headings():
    # answer._sectionize is fence-aware; a '## Episodes' inside a mermaid fence is CONTENT, not a heading
    out = _out("## Mechanism\n```mermaid\n## Episodes\n- 2021 fake [N1]\n```\n")
    assert ev._episode_lines(out) == []


# ── D6: min_episodes_cited, and its documented blind spot (F-J) ──────────────────────────────────────
def test_min_episodes_cited_clusters_cited_evidence_dates():
    mech = _EPISODES_2
    cits = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10", source="conab")]
    assert _pins({"min_episodes_cited": 2}, _out(mech, cits))["min_episodes_cited"] is True
    assert _pins({"min_episodes_cited": 3}, _out(mech, cits))["min_episodes_cited"] is False


def test_min_episodes_cited_is_a_citation_pin_not_a_retrieval_pin():
    # retrieved-but-UNCITED evidence must not count: the model never wrote [E2], so 1994 is not a
    # cited episode class. This is the doctrine distinction the RV2 pins draw.
    mech = "## Episodes\n- 2021 frost [N1] [E1]\n"
    cits = [_ev_cit(1, "2021-07-10"), _ev_cit(2, "1994-07-01")]
    assert _pins({"min_episodes_cited": 2}, _out(mech, cits))["min_episodes_cited"] is False
    assert _pins({"min_episodes_cited": 1}, _out(mech, cits))["min_episodes_cited"] is True


def test_fj_min_episodes_cited_cannot_see_enumeration():
    """The finding, pinned as a test so nobody re-describes this key as 'the deterministic teeth'.
    A fully SMOOTHED answer -- one 'usually', zero enumerated episodes -- passes min_episodes_cited: 3
    purely because its three cited items happen to be dated a decade apart."""
    smoothed = ("## Mechanism\nA Black Sea shock usually lifts wheat for a couple of quarters "
                "[E1][E2][E3].\n")
    cits = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2010-08-01", source="usda_wasde"),
            _ev_cit(3, "2022-03-01", source="conab")]
    out = _out(smoothed, cits)
    assert _pins({"min_episodes_cited": 3}, out)["min_episodes_cited"] is True     # <- the blind spot
    # ...and the F-J complement is what actually catches it: zero enumeration lines.
    assert _pins({"min_episode_lines": 3}, out)["min_episode_lines"] is False


# ── D6: min_episode_sources ─────────────────────────────────────────────────────────────────────────
def test_min_episode_sources_counts_distinct_cited_sources():
    mech = _EPISODES_2
    single = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10")]                 # both wb_cmo_outlook
    assert _pins({"min_episode_sources": 2}, _out(mech, single))["min_episode_sources"] is False
    two = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10", source="conab")]
    assert _pins({"min_episode_sources": 2}, _out(mech, two))["min_episode_sources"] is True


# ── D6: episode_absence_stated ──────────────────────────────────────────────────────────────────────
def test_episode_absence_stated_reads_both_marker_vocabularies():
    q = {"episode_absence_stated": True}
    silent = _out("## Episodes\n- 2021 frost [N1]\n")
    assert _pins(q, silent)["episode_absence_stated"] is False
    for marker in ("the 1975 frost is not in this record",
                   "the 1975 frost is not in the corpus",
                   "1994 has no citable item in this window",
                   "the 1994 move is not in the price record",
                   "the 2026 figure has not been published"):        # the shipped _NOT_KNOWN vocabulary
        out = _out(f"## Episodes\n- 2021 frost [N1]\n- 1994 frost: {marker}.\n")
        assert _pins(q, out)["episode_absence_stated"] is True, marker
    # the pin is an EQUALITY on want, so a false-pin catches an answer that hedges when it shouldn't
    assert _pins({"episode_absence_stated": False}, silent)["episode_absence_stated"] is True


def test_no_citable_does_not_fire_on_loose_prose():
    """The broad 'not in the record' earned a min_episode_lines absence allowance on any line that used it
    loosely ('the 1975 freeze is not in the record books'). Tightened to 'not in this record'."""
    loose = "## Episodes\n- 1975 frost: the great freeze, though it is not in the record books.\n"
    assert _pins({"episode_absence_stated": True}, _out(loose))["episode_absence_stated"] is False


# ── F-J complement: min_episode_lines ───────────────────────────────────────────────────────────────
def test_min_episode_lines_passes_a_clean_two_episode_enumeration():
    cits = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10", source="conab")]
    res = _pins({"min_episode_lines": 2}, _out(_EPISODES_2, cits, injected=_INJ_2))
    assert res["min_episode_lines"] is True


def test_min_episode_lines_fails_smoothing_and_confabulation():
    cits = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10", source="conab")]
    # SMOOTHING: two cited episode classes, one enumerated line
    smoothed = "## Episodes\n- Brazilian frosts (1994 and 2021 alike) usually lift prices [E1][E2].\n"
    assert _pins({"min_episode_lines": 2},
                 _out(smoothed, cits, injected=_INJ_2))["min_episode_lines"] is False
    # CONFABULATION: a third episode minted from nothing, with no absence marker on it
    minted = (_EPISODES_2 + "- 1975-07..1975-08 Brazil frost: the great freeze halved the crop.\n")
    assert _pins({"min_episode_lines": 2},
                 _out(minted, cits, injected=_INJ_2))["min_episode_lines"] is False


def test_min_episode_lines_allows_the_honesty_leg_line_by_line():
    """The deliberate deviation from F-J's literal equality. An episode the top-K missed has no cited
    citation and therefore no cluster; under strict equality the CORRECT honest answer would score as
    confabulation. The allowance is earned per line by DECLARING the absence."""
    cits = [_ev_cit(2, "2021-07-10", source="conab")]                # only 2021 survived retrieval
    honest = ("## Episodes\n"
              "- 2021-06..2021-08 Brazil frost: arabica rose to 205 c/lb [N1] [E2].\n"
              "- 1994-06..1994-08 Brazil frost: the corpus is silent -- no citable item in this window.\n")
    assert _pins({"min_episode_lines": 2},
                 _out(honest, cits, injected=_INJ_2))["min_episode_lines"] is True
    # the same shape WITHOUT the declaration is confabulation and must fail
    silent = honest.replace("the corpus is silent -- no citable item in this window",
                            "the freeze cut output sharply")
    assert _pins({"min_episode_lines": 2},
                 _out(silent, cits, injected=_INJ_2))["min_episode_lines"] is False


def test_min_episode_lines_survives_context_citations():
    """FOLD-PASS 2026-07-30. The old aggregate bound equated a PROSE line count with a CITATION-DATE
    cluster count. A correct 3-line enumeration that ALSO cites today's balance sheet and a background
    item yields FIVE clusters against THREE lines and red -- on a correct answer. Citing extra context
    evidence is desirable behaviour, not confabulation."""
    mech = ("## Episodes\n"
            "- 1994-06..1994-08 Brazil frost [E1].\n"
            "- 2010-07..2011-05 Russia export ban [E2].\n"
            "- 2022-02..2022-06 Black Sea invasion [E3].\n"
            "The current balance sheet is tighter than any of them [E4], and the 2018 review agrees [E5].\n")
    cits = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2010-08-01", source="usda_wasde"),
            _ev_cit(3, "2022-03-01", source="conab"), _ev_cit(4, "2026-06-12", source="usda_wasde"),
            _ev_cit(5, "2018-05-01", source="wb_cmo_outlook")]
    out = _out(mech, cits, injected=_inj("1994-06..1994-08", "2010-07..2011-05", "2022-02..2022-06"))
    assert len(ev._episode_lines(out)) == 3 and len(ev._cited_episode_clusters(out)) == 5
    assert _pins({"min_episode_lines": 3}, out)["min_episode_lines"] is True


def test_min_episode_lines_survives_two_citations_inside_one_episode_window():
    """The mirror direction: two cited items a month apart collapse to ONE cluster, so a correct 2-line
    enumeration used to fail the upper bound too."""
    mech = ("## Episodes\n"
            "- 2022-02 Black Sea invasion [E1].\n"
            "- 2010-07 Russia export ban [E3].\n")
    cits = [_ev_cit(1, "2022-02-25"), _ev_cit(2, "2022-03-30", source="conab"),
            _ev_cit(3, "2010-08-01", source="usda_wasde")]
    out = _out(mech, cits, injected=_inj("2022-02..2022-06", "2010-07..2011-05"))
    assert len(ev._cited_episode_clusters(out)) == 2                 # E1+E2 collapse into one episode class
    assert _pins({"min_episode_lines": 2}, out)["min_episode_lines"] is True


def test_min_episode_lines_accepts_a_line_backed_only_by_its_handle():
    """An [N]-row-evidenced episode carries no [E] date, so a year match is impossible; the handle the
    model actually cited is what backs the line. Note the bullet renders a bare YEAR, not the injected
    'YYYY-MM..YYYY-MM' span -- the injected-window check falls back to the year for exactly this shape,
    because a correctly enumerated window written coarsely is not confabulation (the A-7 false-red class)."""
    mech = "## Episodes\n- the 2022 Black Sea shock lifted wheat sharply [E1].\n"
    out = _out(mech, [_ev_cit(1, "2021-11-02")],                     # cited, but dated OUTSIDE the year
               injected=_inj("2022-02..2022-06", node="drivers/export_ban"))
    assert _pins({"min_episode_lines": 1}, out)["min_episode_lines"] is True


def test_min_episode_lines_still_fails_a_minted_episode_amid_many_citations():
    """The teeth the aggregate bound was supposed to provide, kept: a line with no matching cited year, no
    handle and no absence marker is confabulation however many unrelated items the answer cites."""
    mech = (_EPISODES_2 + "- 1975-07..1975-08 Brazil frost: the great freeze halved the crop.\n")
    cits = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10", source="conab"),
            _ev_cit(3, "2026-06-12", source="usda_wasde")]
    assert _pins({"min_episode_lines": 3},
                 _out(mech, cits, injected=_INJ_2))["min_episode_lines"] is False


def test_episode_section_heading_is_matched_on_a_prefix_and_any_level():
    """'## Episodes (3)', '## Episodes -- dated' and '### Episodes' scored ZERO lines under the exact-match
    form, reding min_episode_lines and episode_magnitude_or_absence on a correctly enumerated answer."""
    body = "- 1994 frost [E1].\n- 2021 frost [E2].\n"
    for head in ("## Episodes", "## Episodes (2)", "## Episodes -- dated", "### Episodes",
                 "#### Episodes enumerated"):
        out = _out(f"{head}\n{body}")
        assert len(ev._episode_lines(out)) == 2, head
    assert ev._episode_lines(_out("## Episodic drivers\n" + body)) == []      # prefix, not substring


def test_min_episode_lines_fails_when_the_section_is_absent():
    cits = [_ev_cit(1, "2021-07-10")]
    out = _out("## Mechanism\nFrost tightens the balance sheet [E1].\n", cits)
    assert _pins({"min_episode_lines": 1}, out)["min_episode_lines"] is False


# ── W2b-D5: episode_magnitude_or_absence ────────────────────────────────────────────────────────────
def test_episode_magnitude_or_absence_accepts_a_handle_or_a_marker():
    cits = [_ev_cit(1, "2021-07-10")]
    both = ("## Episodes\n"
            "- 2021-06..2021-08 frost: front-month arabica settled 205.10 c/lb [N1].\n"
            "- 1994-06..1994-08 frost: no per-contract price record reaches 1994.\n")
    assert _pins({"episode_magnitude_or_absence": True}, _out(both, cits, injected=_INJ_2))[
        "episode_magnitude_or_absence"] is True


def test_episode_magnitude_or_absence_rejects_a_silent_or_uncited_magnitude():
    cits = [_ev_cit(1, "2021-07-10")]
    silent = ("## Episodes\n"
              "- 2021-06..2021-08 frost: arabica settled 205.10 c/lb [N1].\n"
              "- 1994-06..1994-08 frost: a damaging freeze.\n")               # no magnitude, no marker
    # injected on purpose: both windows are REAL here, so the pin must red on the missing magnitude
    # marker alone -- not incidentally because nothing was injected.
    assert _pins({"episode_magnitude_or_absence": True}, _out(silent, cits, injected=_INJ_2))[
        "episode_magnitude_or_absence"] is False
    # an UNCITED numeral is a fabrication wearing a magnitude -- handle discipline, not a numeral scan
    uncited = silent.replace("a damaging freeze", "prices roughly doubled to 248 c/lb")
    assert _pins({"episode_magnitude_or_absence": True}, _out(uncited, cits, injected=_INJ_2))[
        "episode_magnitude_or_absence"] is False


def test_episode_magnitude_or_absence_cannot_vacuously_pass():
    # all([]) is True -- an answer that never renders '## Episodes' must NOT satisfy a true-pin
    out = _out("## Mechanism\nFrost tightens the balance sheet [E1].\n", [_ev_cit(1, "2021-07-10")])
    assert _pins({"episode_magnitude_or_absence": True}, out)["episode_magnitude_or_absence"] is False
    assert _pins({"episode_magnitude_or_absence": False}, out)["episode_magnitude_or_absence"] is True


# ── harness wiring ──────────────────────────────────────────────────────────────────────────────────
def test_new_pins_are_registered_and_scored():
    # a pin key absent from _CASCADE_EXPECT is scored by NOTHING and silently false-greens a gate run.
    for k in ("min_episodes_cited", "min_episode_sources", "episode_absence_stated",
              "min_episode_lines", "episode_magnitude_or_absence"):
        assert k in ev._CASCADE_EXPECT
    res = _pins({"min_episodes_cited": 1, "min_episode_sources": 1, "episode_absence_stated": False,
                 "min_episode_lines": 2, "episode_magnitude_or_absence": True},
                _out(_EPISODES_2, [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10", source="conab")],
                     injected=_INJ_2))
    assert res == {"min_episodes_cited": True, "min_episode_sources": True,
                   "episode_absence_stated": True, "min_episode_lines": True,
                   "episode_magnitude_or_absence": True}


def test_pins_read_structured_prose_not_the_sources_footer():
    # the primary-gate trap: the '## Sources' footer re-lists every ledgered handle including ones
    # verify stripped from prose. [E2] survives only in the footer, so it must not count.
    cits = [_ev_cit(1, "2021-07-10"), _ev_cit(2, "1994-07-01", source="conab")]
    out = _out("## Episodes\n- 2021-06..2021-08 frost [N1] [E1].\n", cits)
    assert "[E2]" in out["answer"] and "[E2]" not in out["structured"]["mechanism"]
    assert _pins({"min_episodes_cited": 2}, out)["min_episodes_cited"] is False
    assert _pins({"min_episode_sources": 2}, out)["min_episode_sources"] is False


# -- D-4 (2026-07-31): the VACUITY exploit -- an invented window is not an episode --------------------
# MEASURED, then fixed. Every case below is the adversarial gate's own reproduction, run through the real
# `expect` blocks of the playbooks deck. Before the fix, all three were GREEN. The fix is not a new
# vocabulary and not a weakening of the honesty allowance (which must stay -- see the controls at the
# bottom): every bullet must now also name a window the ENGINE ACTUALLY INJECTED into this turn's prompt,
# and `want` DISTINCT injected episodes must be enumerated.
_REAL_INJ = _inj("2010-07..2011-05", "2019-02..2019-06", "2022-02..2022-06", node="drivers/export_ban")

_INVENTED_3 = (
    "## Mechanism\n"
    "Black Sea corridor risk transmits through the export corridor [E9], the 2010 ban precedent [E4], "
    "and the 2019 export tax [E7]; the balance sheet is [N1].\n"
    "## Episodes\n"
    "- 1873-04..1873-09 -- the Sumatra pepper panic: no citable item in this window; no price record.\n"
    "- 1911-02..1911-08 -- the Penang pepper panic: no citable item in this window; no price record.\n"
    "- 1962-05..1962-11 -- the Sarawak pepper panic: no citable item in this window; no price record.\n")


def _blacksea_cits():
    return [_ev_cit(9, "2022-04-01", source="wb_cmo_outlook"),
            _ev_cit(4, "2010-08-15", source="usda_wasde"),
            _ev_cit(7, "2019-02-10", source="igc_gmr"),
            {"id": "N1", "kind": "number", "source": "wasde", "date": "2026-06-12",
             "locator": {"metric": "stocks_to_use"}, "payload": {"rows": [{"v": 1}]}}]


def test_three_invented_windows_no_longer_green_the_enumeration_pins():
    """CASE D, verbatim. Three windows that exist in no corpus, carry no price record and are cited
    nowhere -- the real handles appear only in '## Mechanism'. They used to green ALL FIVE episode pins
    through _line_backed's absence branch: a minted window that merely SAYS 'no citable item' scored as
    BACKED. Now every bullet must ALSO match an injected window, and 1873/1911/1962 match none.

    The three CITATION pins stay green and that is CORRECT, not a residual hole: min_episodes_cited /
    min_episode_sources / episode_absence_stated are citation-date-spread pins that cannot see
    enumeration at all (eval.py's own docstring says so), and this answer really did cite three sources
    across two episode classes. The two ENUMERATION pins are the ones that claimed to grade the section,
    and they are the ones that now red."""
    pins = {"min_episodes_cited": 2, "min_episode_sources": 3, "min_episode_lines": 3,
            "episode_absence_stated": True, "episode_magnitude_or_absence": True}
    res = _pins(pins, _out(_INVENTED_3, _blacksea_cits(), injected=_REAL_INJ))
    assert len(ev._episode_lines(_out(_INVENTED_3, _blacksea_cits()))) == 3   # still three bullets ...
    assert res["min_episode_lines"] is False                                  # ... enumerating nothing
    assert res["episode_magnitude_or_absence"] is False
    assert res["min_episodes_cited"] is True and res["min_episode_sources"] is True


def test_invented_windows_red_even_with_no_injected_record():
    """FAIL-CLOSED. On a turn where the engine injected nothing (OFF arm, one-hop, dead artifact) a
    '## Episodes' section can be an enumeration of NOTHING by construction, so both pins must red rather
    than fall back to the old backing-only test."""
    res = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True},
                _out(_INVENTED_3, _blacksea_cits()))
    assert res == {"min_episode_lines": False, "episode_magnitude_or_absence": False}


def test_the_same_bullet_three_times_cannot_reach_the_count():
    """CASE E. One bullet repeated to satisfy `min_episode_lines: 3`. Even when the window is REAL, three
    copies enumerate ONE episode -- the distinctness bound is a maximum matching of bullets to injected
    episodes, so repeats collapse."""
    bullet = ("- 2010-07..2011-05 -- Russian export ban: no citable item in this window; "
              "no price record for this window.\n")
    mech = "## Mechanism\nThe corridor [E4].\n## Episodes\n" + bullet * 3
    out = _out(mech, _blacksea_cits(), injected=_REAL_INJ)
    assert len(ev._episode_lines(out)) == 3                       # three physical bullets ...
    _lines, adj, distinct = ev._episode_enumeration(out)
    assert all(adj) and distinct == 1                             # ... one distinct injected episode
    assert _pins({"min_episode_lines": 3}, out)["min_episode_lines"] is False
    assert _pins({"min_episode_lines": 1}, out)["min_episode_lines"] is True   # honest count still green


def test_four_invented_windows_with_zero_citations_red_the_magnitude_pin():
    """CASE F (pb_covid_demand_shock's shape): four minted windows, NO citations at all. 'no price
    record' is trivially true of a window that never existed, which is why this pin needed the same
    injected-window requirement rather than a richer marker vocabulary."""
    mech = ("## Episodes\n"
            + "".join("- {y}-04..{y}-09 -- an invented panic: no citable item in this window; "
                      "no price record.\n".format(y=y) for y in (1873, 1911, 1962, 1988)))
    res = _pins({"min_episode_lines": 2, "episode_magnitude_or_absence": True},
                _out(mech, [], injected=_REAL_INJ))
    assert res == {"min_episode_lines": False, "episode_magnitude_or_absence": False}


# -- the HONEST shapes that must stay green (the fold-pass allowance is intact) -----------------------
def test_honest_receipted_and_receiptless_bullets_both_stay_green():
    """The two shapes W4 exists to reward, on REAL injected windows:
      (a) an injected episode enumerated with its receipt's handle and a cited magnitude;
      (b) an injected episode with NO citable item and NO price row, stating BOTH absences.
    (b) is the F-I line, and it is precisely the one the vacuity fix must not break -- deleting
    _line_backed's absence branch would have red it."""
    cits = [_ev_cit(1, "2021-07-10", source="conab")]
    honest = ("## Episodes\n"
              "- 2021-06..2021-08 -- Brazil frost: frost damage reported through that window [E1]; "
              "arabica settled 205.10 c/lb [N1].\n"
              "- 1994-06..1994-08 -- Brazil frost: no citable item in this window, so what happened is "
              "not narrated; no price record for this window.\n")
    res = _pins({"min_episode_lines": 2, "episode_magnitude_or_absence": True},
                _out(honest, cits, injected=_INJ_2))
    assert res == {"min_episode_lines": True, "episode_magnitude_or_absence": True}


def test_a_coarsely_written_window_still_matches_its_injected_episode():
    """The A-7 false-red class, refused. A model that writes '- 1994 Brazil frost: ...' instead of the
    full ISO span is enumerating a real injected window in a coarser hand; the year fallback accepts it,
    and it cannot launder an invented window because 1873 matches no injected year either."""
    inj = ev._injected_episodes(_out("x", injected=_INJ_2))
    assert ev._line_targets("- 1994 Brazil frost: no citable item in this window.", inj) == {0}
    assert ev._line_targets("- 1873 pepper panic: no citable item in this window.", inj) == set()


def test_a_window_minted_INSIDE_a_real_injected_span_is_still_minted():
    """The residual the year fallback would otherwise launder, closed. Shown 2001-11..2003-04, a model that
    writes a NARROWER window of its own -- '2002-06..2002-09 -- the great drought' -- has invented a window
    and narrated it, which is exactly the confabulation P3 exists to catch. A bullet precise enough to
    render year-months must render year-months the engine actually showed it; the coarse bare-year hand
    (no year-month at all) keeps its year-level acceptance."""
    inj = ev._injected_episodes(_out("x", injected=_inj("2001-11..2003-04")))
    assert ev._line_targets("- 2002-06..2002-09 -- the great drought: no citable item in this window; "
                            "no price record.", inj) == set()
    assert ev._line_targets("- 2001-11..2003-04 -- a cold run: no citable item in this window.", inj) == {0}
    assert ev._line_targets("- 2002 the drought year: no citable item in this window.", inj) == {0}
    mech = ("## Episodes\n- 2002-06..2002-09 -- the great drought: no citable item in this window; "
            "no price record.\n")
    res = _pins({"min_episode_lines": 1, "episode_magnitude_or_absence": True},
                _out(mech, [], injected=_inj("2001-11..2003-04")))
    assert res == {"min_episode_lines": False, "episode_magnitude_or_absence": False}


def test_two_bullets_whose_year_sets_overlap_still_count_as_two():
    """Why the distinctness bound is a MATCHING and not 'one best target per line'. Two adjacent injected
    windows sharing a calendar year must not collapse two honest bullets into one enumerated episode."""
    inj = _inj("2000-11..2001-07", "2001-11..2003-04")
    mech = ("## Episodes\n"
            "- 2000-11..2001-07 -- an early window: no citable item in this window; no price record.\n"
            "- 2001-11..2003-04 -- a later window: no citable item in this window; no price record.\n")
    out = _out(mech, [], injected=inj)
    _lines, _adj, distinct = ev._episode_enumeration(out)
    assert distinct == 2
    assert _pins({"min_episode_lines": 2}, out)["min_episode_lines"] is True


# -- the ENGINE'S OWN RECEIPT STAMP is not a window claim (D-EC P0 axis fix, remedy (b)) --------------
# `answer._scaffold_section` signs a receipted bullet `the dated item [E<k>] recorded <date>`, and since
# the receipt axis was corrected that date is a PAIR whenever the two axes disagree: `recorded
# <in-window date> (reported <publication date>)`. Both are the CITATION's timestamps, not windows the
# bullet is claiming -- and reading them as claims widens the adjacency `_max_matching` consumes, in the
# FALSE-GREEN direction. Reproduced below exactly: one bullet's targets go {0} -> {0,1} on the stamp
# alone, and two IDENTICAL copies of it then match two distinct episodes -- the repeat-bullet exploit
# `_max_matching` exists to close, re-opened by a rendering change.
_STAMP_INJ = _inj("1978-08..1980-10", node="yellow_maize") + _inj("1979-06..1979-09", node="drivers/frost")
_STAMP_BULLET = ("- 1978-08..1980-10 -- yellow_maize: the dated item [E7] recorded 1979-06-11 "
                 "(reported 2020-03-15) reports a freeze cut the belt harvest; "
                 "no observed magnitude for this window.")
_PRE_STAMP_BULLET = ("- 1978-08..1980-10 -- yellow_maize: the dated item [E7] recorded 2020-03-15 "
                     "reports a freeze cut the belt harvest; "
                     "no observed magnitude for this window.")


def test_the_engine_receipt_stamp_does_not_widen_the_adjacency():
    """The bullet enumerates ONE injected window (1978-08..1980-10). Its receipt's in-window date lands
    in a SECOND injected episode's endpoint month (1979-06) purely by corpus coincidence, and its
    publication date lands in neither. Both stamp halves must be invisible to the match, so the bullet
    targets exactly the window it wrote -- identically before and after the rendering change."""
    inj = ev._injected_episodes(_out("x", injected=_STAMP_INJ))
    assert len(inj) == 2
    assert ev._line_targets(_PRE_STAMP_BULLET, inj) == {0}
    assert ev._line_targets(_STAMP_BULLET, inj) == {0}               # WAS {0,1}: the stamp widened it


def test_two_identical_stamped_bullets_are_still_ONE_enumerated_episode():
    """THE EXPLOIT THE WIDENING RE-OPENED, stated as the number `min_episode_lines` reads. Two copies of
    one bullet are one enumerated episode; with the stamp inside the adjacency they matched TWO, so a
    section that repeats a single window would have satisfied `min_episode_lines: 2`."""
    inj = ev._injected_episodes(_out("x", injected=_STAMP_INJ))
    adj = [ev._line_targets(_STAMP_BULLET, inj), ev._line_targets(_STAMP_BULLET, inj)]
    assert ev._max_matching(adj) == 1                                # WAS 2
    # ...and the unsubtracted tokenization is what the 2 came from -- the defect, reproduced in place so
    # this pin cannot pass merely because the fixture stopped exercising it.
    raw = [{i for i, e in enumerate(inj)
            if {f"{y}-{m}" for y, m in ev._YM_RX.findall(b)} & {e["start"], e["end"]}}
           for b in (_STAMP_BULLET, _STAMP_BULLET)]
    assert raw == [{0, 1}, {0, 1}] and ev._max_matching(raw) == 2
    # end to end, through the scorer the deck actually reads
    mech = "## Episodes\n" + _STAMP_BULLET + "\n" + _STAMP_BULLET + "\n"
    out = _out(mech, [], injected=_STAMP_INJ)
    _lines, _adj, distinct = ev._episode_enumeration(out)
    assert distinct == 1
    assert _pins({"min_episode_lines": 2}, out)["min_episode_lines"] is False


def test_the_stamp_subtraction_leaves_a_model_authored_date_alone():
    """The other direction of the same failure. The subtraction requires the engine's literal lead word
    AND a full day-grain ISO date, so a window the MODEL wrote -- and the coarser shapes a model reaches
    for -- are still read as claims. Over-stripping would manufacture false reds on honest bullets."""
    inj = ev._injected_episodes(_out("x", injected=_STAMP_INJ))
    # a bare year-month the model wrote itself, with no stamp anywhere on the line
    assert ev._line_targets("- 1979-06..1979-09 -- drivers/frost: no citable item in this window.",
                            inj) == {1}
    # 'recorded' WITHOUT a day-grain date is not the engine's stamp and is not subtracted
    assert ev._line_targets("- the frost recorded 1979-06 through 1979-09 was severe.", inj) == {1}
    # the stamp is subtracted, the model's own second window on the same line is NOT
    assert ev._line_targets("- 1978-08..1980-10 -- yellow_maize: the dated item [E7] recorded "
                            "1979-06-11 (reported 2020-03-15) reports it was milder than "
                            "1979-06..1979-09.", inj) == {0, 1}
    # tier 2 (no year-month at all once the stamp is gone) still falls back to the YEAR overlap
    assert ev._line_targets("- 1979 frost: the dated item [E7] recorded 1979-06-11 "
                            "(reported 2020-03-15) reports a freeze.", inj) == {0, 1}


# -- W4-N1: the judge can SEE the injected episodes ---------------------------------------------------
def _judge_user(out, query=None):
    """Capture the verbatim user string eval.judge() builds -- the same technique that MEASURED the
    defect (the injected lines were in none of the four blocks it assembled)."""
    seen = {}

    def fake_call(client, system, user, *, model, max_tokens, tool):
        seen["user"] = user
        seen["sys"] = system if isinstance(system, str) else system[0]["text"]
        return {"usefulness": 4, "gaps": [], "verdict": "ok"}, None

    ev.judge(query or {"question": "what does the record show", "asof": "2026-07-01"},
             out, call=fake_call)
    return seen


def _real_line():
    return tl.render_line("drivers/frost", [
        {"start": "2001-11-06", "end": "2003-04-24", "n": 20, "receipt": None},
        {"start": "2021-06-01", "end": "2021-08-20", "n": 3,
         "receipt": {"date": "2021-07-10", "text": "frost damage in southern Minas Gerais"}}])


def test_judge_is_shown_the_injected_episode_lines():
    """THE BLOCKER, closed. The judge's user block was built from graph + evidence + numbers + answer,
    and the injected episode lines were in NONE of them. A receipt-less episode is BY CONSTRUCTION one
    with no evidence prop in its window, so a CORRECTLY enumerated window read to the judge as an
    unsupported date claim -- the ON arm's hallucination count was pushed up by instrumentation, on the
    exact metric the A/B acceptance rule uses."""
    line = _real_line()
    out = {"answer": "## Episodes\n- 2001-11..2003-04 -- a cold run: no citable item in this window.\n",
           "evidence": [], "number_calls": [], "citations": [],
           "trace": {"episodes_injected": [{"node": "drivers/frost", "line": line,
                                            "spans": ["2001-11..2003-04", "2021-06..2021-08"]}]}}
    cap = _judge_user(out)
    assert "=== DATED EPISODES THE TOOL WAS SHOWN" in cap["user"]
    assert line in cap["user"]                                    # the VERBATIM injected line
    assert tl.LINE_PREFIX in cap["user"] and tl._NO_RECEIPT in cap["user"]
    block = cap["user"].split("=== DATED EPISODES")[1].split("=== OBSERVED")[0]
    assert "2001-11..2003-04" in block


def test_the_judge_block_is_rendered_on_both_arms_with_one_rubric():
    """SYMMETRY -- how the fix avoids replacing one bias with another. The block and the rubric are
    rendered on EVERY judged turn of BOTH arms; only the CONTENT differs, and on the OFF arm '(none)' is
    the true statement. An arm-conditional block would be a second instrument, not a fix."""
    off = _judge_user({"answer": "a smoothed note", "evidence": [], "number_calls": [], "citations": [],
                       "trace": {}})
    assert "=== DATED EPISODES THE TOOL WAS SHOWN" in off["user"]
    assert "no dated-episode lines were injected on this turn" in off["user"]
    on = _judge_user({"answer": "a", "evidence": [], "number_calls": [], "citations": [],
                      "trace": {"episodes_injected": [{"node": "n", "line": _real_line(),
                                                       "spans": ["2001-11..2003-04"]}]}})
    assert off["sys"] == on["sys"]                                # ONE rubric, byte-identical


def test_judge_rubric_treats_the_injected_block_as_ground_truth():
    """The hallucination axis is what the acceptance rule reads, so the clause has to live there and not
    only in the panel header: an enumerated window that appears in the block is SUPPORTED even when no
    evidence item is dated inside it, and one that appears nowhere is still a hallucination."""
    assert "DATED EPISODES BLOCK IS GROUND TRUTH" in ev._JUDGE_SYS
    assert "the DATED EPISODES block, NOR the looked-up numbers" in ev._JUDGE_SYS
    assert "A dated window in NONE of the four sources IS a hallucination" in ev._JUDGE_SYS


def test_episode_enumeration_axis_exists_and_is_optional():
    """eval.py:802 and the deck's :497/:1498 deferred enumeration quality to an `episode_enumeration`
    axis that was never built, so enumeration honesty had no grader on ANY surface. It exists now --
    and is OPTIONAL (the directional_traceability precedent), so no existing deck is forced to score it
    and no existing baseline moves."""
    schema = ev._judge_tool()["input_schema"]
    assert "episode_enumeration" in schema["properties"]
    assert "episode_enumeration" not in schema["required"]
    assert "episode_enumeration" in ev._JUDGE_SYS
    # ... and _per_answer_record's projection is a HARD WHITELIST: an axis absent from that tuple is
    # silently dropped from every baseline JSON, so the deck would score an axis nobody can read back.
    row = {"q": {"id": "p1", "contract": "wheat"}, "out": {"trace": {}, "structured": {}},
           "rubric": {"routed_right": True, "intent_ok": None},
           "judge": {"usefulness": 4, "episode_enumeration": 5}}
    assert ev._per_answer_record(row, "single")["judge"]["episode_enumeration"] == 5


def test_the_injected_record_reaches_the_judge_end_to_end(monkeypatch):
    """PRODUCER -> TRACE -> JUDGE in ONE test, every leg through the shipped function.

    The two tests above hand-build `trace['episodes_injected']`, and the stamping half is pinned by a
    source-inspection test in test_w4_episode_section.py. Between them sits the leg the whole fix rests
    on -- `_answer_l2` spreading **sg.trace into out['trace'] -- and a hand-built fixture cannot see it
    break. This drives the REAL answer._l2_blocks, spreads the REAL sg.trace exactly as the return does,
    and asserts the VERBATIM line the model was sent lands inside the judge's DATED EPISODES block."""
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import planner as pl
    monkeypatch.setattr(an, "_context_block", lambda g, c: f"CTX {c}")
    eps = [{"start": "2001-11-06", "end": "2003-04-24", "n": 20, "receipt": None},
           {"start": "2021-06-01", "end": "2021-08-20", "n": 3,
            "receipt": {"date": "2021-07-10", "text": "frost damage in southern Minas Gerais"}}]
    node = pl.GroundedNode(kind="driver", id="drivers/frost", contract="arabica_coffee", depth=1,
                           relevance=0.9, episodes=eps)
    sg = pl.Subgraph(seeds=["arabica_coffee"], nodes=[node])
    _stable, volatile = an._l2_blocks(sg, None, "2026-07-01")
    line = tl.render_line("drivers/frost", eps)
    assert any(line in b for b in volatile)                       # what the MODEL was sent ...
    out = {"answer": "## Episodes\n- 2001-11..2003-04 -- a cold run: no citable item in this window.\n",
           "evidence": [], "number_calls": [], "citations": [],
           "trace": {"planner": "l2", **sg.trace}}                # ... the exact _answer_l2 spread
    cap = _judge_user(out)
    block = cap["user"].split("=== DATED EPISODES THE TOOL WAS SHOWN")[1].split("=== OBSERVED NUMBERS")[0]
    assert line in block                                          # ... is what the JUDGE is shown
    assert "2001-11..2003-04" in block and "2021-06..2021-08" in block
    # and the SAME record is what the deterministic pins grade against -- one ground truth, not two
    assert [e["span"] for e in ev._injected_episodes(out)] == ["2001-11..2003-04", "2021-06..2021-08"]


def test_the_scorer_and_the_judge_read_ONE_record():
    """ANTI-DRIFT. The judge panel and the enumeration pins must never disagree about which windows the
    engine injected -- a second derivation is how a grader starts scoring a different turn from the one
    that ran. Pinned as a source fact: both consumers read trace['episodes_injected'], and neither
    re-derives episodes from the timeline artifact."""
    import ast
    import inspect
    for fn in (ev._injected_episodes, ev._judge_episodes_panel):
        tree = ast.parse(inspect.getsource(fn).strip())
        fn_node = tree.body[0]
        if ast.get_docstring(fn_node) is not None:                # grade the CODE, not the commentary
            fn_node.body = fn_node.body[1:]
        code = ast.unparse(fn_node)
        assert "trace" in code and "episodes_injected" in code
        assert "episodes_for" not in code and "timeline" not in code   # no re-derivation from the artifact
