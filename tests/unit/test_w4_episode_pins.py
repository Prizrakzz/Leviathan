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


def _out(mech: str, cits=None, tldr=""):
    """A minimal answer-shaped dict. mech is the STRUCTURED mechanism (what the pins read); the
    out['answer'] footer deliberately re-lists EVERY handle so any pin that cheated by scanning the
    footer instead of structured prose would false-pass here."""
    cits = cits or []
    footer = "\n\n## Sources\n" + "\n".join(f"[{c['id']}] x" for c in cits)
    return {"answer": mech + footer, "intent": "reasoning", "evidence": [], "citations": cits,
            "structured": {"tldr": tldr, "mechanism": mech,
                           "sources": [{"ref": int(c["id"][1:])} for c in cits]},
            "trace": {}}


def _pins(pins: dict, out: dict) -> dict:
    return ev._cascade_asserts({"contract": "arabica_coffee", "asof": "2026-06-15", "expect": pins}, out)


_EPISODES_2 = ("## Episodes\n"
               "- 1994-06..1994-08 Brazil frost: arabica settles rose to 248 c/lb [N1].\n"
               "- 2021-06..2021-08 Brazil frost: arabica settles rose to 205 c/lb [N2].\n"
               "The record holds two frost episodes [E1][E2].\n")


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
    res = _pins({"min_episode_lines": 2}, _out(_EPISODES_2, cits))
    assert res["min_episode_lines"] is True


def test_min_episode_lines_fails_smoothing_and_confabulation():
    cits = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10", source="conab")]
    # SMOOTHING: two cited episode classes, one enumerated line
    smoothed = "## Episodes\n- Brazilian frosts (1994 and 2021 alike) usually lift prices [E1][E2].\n"
    assert _pins({"min_episode_lines": 2}, _out(smoothed, cits))["min_episode_lines"] is False
    # CONFABULATION: a third episode minted from nothing, with no absence marker on it
    minted = (_EPISODES_2 + "- 1975-07..1975-08 Brazil frost: the great freeze halved the crop.\n")
    assert _pins({"min_episode_lines": 2}, _out(minted, cits))["min_episode_lines"] is False


def test_min_episode_lines_allows_the_honesty_leg_line_by_line():
    """The deliberate deviation from F-J's literal equality. An episode the top-K missed has no cited
    citation and therefore no cluster; under strict equality the CORRECT honest answer would score as
    confabulation. The allowance is earned per line by DECLARING the absence."""
    cits = [_ev_cit(2, "2021-07-10", source="conab")]                # only 2021 survived retrieval
    honest = ("## Episodes\n"
              "- 2021-06..2021-08 Brazil frost: arabica rose to 205 c/lb [N1] [E2].\n"
              "- 1994-06..1994-08 Brazil frost: the corpus is silent -- no citable item in this window.\n")
    assert _pins({"min_episode_lines": 2}, _out(honest, cits))["min_episode_lines"] is True
    # the same shape WITHOUT the declaration is confabulation and must fail
    silent = honest.replace("the corpus is silent -- no citable item in this window",
                            "the freeze cut output sharply")
    assert _pins({"min_episode_lines": 2}, _out(silent, cits))["min_episode_lines"] is False


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
    out = _out(mech, cits)
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
    out = _out(mech, cits)
    assert len(ev._cited_episode_clusters(out)) == 2                 # E1+E2 collapse into one episode class
    assert _pins({"min_episode_lines": 2}, out)["min_episode_lines"] is True


def test_min_episode_lines_accepts_a_line_backed_only_by_its_handle():
    """An [N]-row-evidenced episode carries no [E] date, so a year match is impossible; the handle the
    model actually cited is what backs the line."""
    mech = "## Episodes\n- the 2022 Black Sea shock lifted wheat sharply [E1].\n"
    out = _out(mech, [_ev_cit(1, "2021-11-02")])                     # cited, but dated OUTSIDE the year
    assert _pins({"min_episode_lines": 1}, out)["min_episode_lines"] is True


def test_min_episode_lines_still_fails_a_minted_episode_amid_many_citations():
    """The teeth the aggregate bound was supposed to provide, kept: a line with no matching cited year, no
    handle and no absence marker is confabulation however many unrelated items the answer cites."""
    mech = (_EPISODES_2 + "- 1975-07..1975-08 Brazil frost: the great freeze halved the crop.\n")
    cits = [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10", source="conab"),
            _ev_cit(3, "2026-06-12", source="usda_wasde")]
    assert _pins({"min_episode_lines": 3}, _out(mech, cits))["min_episode_lines"] is False


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
    assert _pins({"episode_magnitude_or_absence": True}, _out(both, cits))[
        "episode_magnitude_or_absence"] is True


def test_episode_magnitude_or_absence_rejects_a_silent_or_uncited_magnitude():
    cits = [_ev_cit(1, "2021-07-10")]
    silent = ("## Episodes\n"
              "- 2021-06..2021-08 frost: arabica settled 205.10 c/lb [N1].\n"
              "- 1994-06..1994-08 frost: a damaging freeze.\n")               # no magnitude, no marker
    assert _pins({"episode_magnitude_or_absence": True}, _out(silent, cits))[
        "episode_magnitude_or_absence"] is False
    # an UNCITED numeral is a fabrication wearing a magnitude -- handle discipline, not a numeral scan
    uncited = silent.replace("a damaging freeze", "prices roughly doubled to 248 c/lb")
    assert _pins({"episode_magnitude_or_absence": True}, _out(uncited, cits))[
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
                _out(_EPISODES_2, [_ev_cit(1, "1994-07-01"), _ev_cit(2, "2021-07-10", source="conab")]))
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
