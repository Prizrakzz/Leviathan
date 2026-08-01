"""W4-D3 -- the reserved '## Episodes' section, the PRODUCER half of the W4 deck's two episode pins.

Both pins (eval.min_episode_lines, eval.episode_magnitude_or_absence) read a rendered '## Episodes'
section via eval._episode_section / _episode_lines. Nothing ever rendered one, so both were red BY
CONSTRUCTION on every row that pinned them. This suite pins the fix end to end:

  T1  flag OFF -> _system() is EXACTLY the pre-feature string (byte identity, not a `not in` check)
  T2  the gate, cloned from test_pattern_records_card.py::test_recorded_history_addendum_gated_...
  T3  SPELLING PARITY: the paragraph ships IFF timeline.episodes_for() emits lines. The two gates are
      spelled differently on purpose (timeline.py:140 is an exact "on"); a copy-paste of the house
      on/1/true idiom would tell the model to render '## Episodes' on a turn carrying no episodes.
  T7  THE SEAM GATE (added 2026-07-31 for verifier blocker 2). T3 is NECESSARY BUT NOT SUFFICIENT and
      says so in its own body: it holds an artifact under GRAPHRAG_TIMELINE_PATH, so it can only see
      the SPELLING half. The flag can be exactly "on" with zero episode lines injected -- dead artifact,
      no as-of, one-hop planner -- and the flag-only gate shipped the paragraph in every one of them.
      T7 pins the second leg: _episodes_on() reads the ASSEMBLED VOLATILE PROMPT, and both serving
      bodies call it.
  T8  THE PERSONA'S OWN WORKED EXAMPLES ENUMERATE NOTHING (verifier blocker 3). Pasted verbatim into a
      section body they must score ZERO episode lines, so a green on the deck's episode pins can only
      come from enumerating the injected episodes -- never from copying the instructions.
  T4  PRODUCER/CONSUMER AGREEMENT -- the load-bearing test. A section written to the paragraph's own
      template is parsed by eval._episode_lines and scored by eval._cascade_asserts (eval is CALLED,
      never re-implemented), and BOTH pins come back green.
  T5  one mutation per branch, each of which must RED.
  T6  the rendered section survives register.sanitize in BOTH registers, plus the negative control
      that pins WHY the report count may not be a numeral.

All offline: no pg, no S3, no LLM. ASCII-only output (Windows console is cp1252).
"""
from __future__ import annotations

import json

from leviathan.graphrag import answer as an
from leviathan.graphrag import eval as ev
from leviathan.graphrag import register as reg
from leviathan.graphrag import timeline as tl

_FLAGS = ("GRAPHRAG_TIMELINE", "GRAPHRAG_OUTLOOK", "GRAPHRAG_PATTERN_RECORDS",
          "GRAPHRAG_CASCADE_CHAIN", "GRAPHRAG_TRANSMISSION", "GRAPHRAG_CASCADE_TRANSMISSION",
          "GRAPHRAG_MENTOR_VOICE", "GRAPHRAG_CASCADE_QUANT")


def _clear(monkeypatch) -> None:
    for k in _FLAGS:
        monkeypatch.delenv(k, raising=False)


# -- fixtures: a realistic rendered turn -------------------------------------------------------------
# THE THREE CASES THE CORPUS ACTUALLY PRODUCES, written to _SYSTEM_EPISODES' own two-slot template:
#   (B) receipt-less + pre-price-floor -> BOTH absences stated (the F-I line; backed with no handle
#       at all, which is what makes min_episode_lines retrieval-ROBUST)
#   (A) receipted, no price row -> [E] handle + the turn-scoped no-magnitude marker (the common case)
#   (C) the rare priced episode -> [N] handle AND an [E] handle. The [E] is NOT decoration:
#       eval._cited_evidence filters kind == "evidence", so an [N] handle can never back a line.
_EPISODES_SECTION = (
    "## Episodes\n"
    "- 1994-06..1994-08 -- Brazil frost: no citable item in this window, so what happened is not "
    "narrated; no price record for this window.\n"
    "- 2021-06..2021-08 -- Brazil frost: the corpus documents frost damage in southern Minas Gerais "
    "reported through that window [E3]; no observed magnitude for this window.\n"
    "- 2010-08..2011-09 -- Russian export ban: US season-average farm price 5.70 USD/bu [N2] across "
    "those marketing years, with export commitments rising through the following winter [E5].\n"
)

_MECH = (
    "## Mechanism\n"
    "Frost damage in the Brazilian arabica belt tightens the balance sheet with a lag.\n"
    "## The record\n"
    "The corpus documents frost damage in southern Minas Gerais [E3] and the export ban [E5].\n"
    + _EPISODES_SECTION +
    "## What to watch\n"
    "Further cold-front reports through the Southern Hemisphere winter.\n"
)


def _cits():
    return [
        {"id": "E3", "kind": "evidence", "source": "wb_cmo_outlook", "date": "2021-07-10",
         "locator": {"kind": "doc"}, "payload": {"text": "frost damage in southern Minas Gerais"}},
        {"id": "E5", "kind": "evidence", "source": "usda_fas_gain", "date": "2011-01-15",
         "locator": {"kind": "doc"}, "payload": {"text": "export commitments rose"}},
        {"id": "N2", "kind": "number", "source": "wasde", "date": "2011-09-01",
         "locator": {"metric": "avg_farm_price"}, "payload": {"rows": [{"v": 5.70}]}},
    ]


# W4-N1: the episodes the ENGINE injected on this turn -- the three windows _EPISODES_SECTION
# enumerates, across the two nodes a real walk would ground. Built through the REAL producer
# (tl.render_line) so the recorded `line` is byte-for-byte what the model would have been shown, and
# `spans` is the same 'YYYY-MM..YYYY-MM' rendering the enumeration pins compare bullets against.
_INJECTED_EPS = [
    ("drivers/frost", [{"start": "1994-06-10", "end": "1994-08-01", "n": 11, "receipt": None},
                       {"start": "2021-06-01", "end": "2021-08-20", "n": 3,
                        "receipt": {"date": "2021-07-10",
                                    "text": "frost damage in southern Minas Gerais"}}]),
    ("drivers/export_ban", [{"start": "2010-08-05", "end": "2011-09-30", "n": 14,
                             "receipt": {"date": "2011-01-15", "text": "export commitments rose"}}]),
]


def _injected():
    return [{"node": node, "line": tl.render_line(node, eps),
             "spans": [f"{e['start'][:7]}..{e['end'][:7]}" for e in eps]}
            for node, eps in _INJECTED_EPS]


def _out(mech: str, cits=None, tldr="Frost risk points toward higher prices.", injected=None):
    """A minimal answer-shaped dict. mech is the STRUCTURED mechanism (what the pins read); the
    out['answer'] footer deliberately re-lists every handle so a pin that cheated by scanning the
    footer instead of structured prose would false-pass here.

    trace['episodes_injected'] defaults to the REAL injected record for this turn, because that is what
    a live ON-arm turn carries and the enumeration pins now check every bullet's window against it. Pass
    `injected=[]` to model a turn on which the engine injected nothing."""
    cits = list(_cits() if cits is None else cits)
    footer = "\n\n## Sources\n" + "\n".join(f"[{c['id']}] x" for c in cits)
    return {"answer": mech + footer, "intent": "reasoning", "evidence": [], "citations": cits,
            "structured": {"tldr": tldr, "mechanism": mech,
                           "sources": [{"ref": int(c["id"][1:])} for c in cits]},
            "trace": {"episodes_injected": _injected() if injected is None else injected}}


def _pins(pins: dict, out: dict) -> dict:
    return ev._cascade_asserts({"contract": "arabica_coffee", "asof": "2026-06-15", "expect": pins}, out)


def _artifact(tmp_path, monkeypatch) -> None:
    art = tmp_path / "episodes.json"
    art.write_text(json.dumps({"drivers/frost": [
        {"start": "1994-06-10", "end": "1994-08-01", "dates": ["1994-06-10", "1994-08-01"]},
        {"start": "2021-06-01", "end": "2021-08-20", "dates": ["2021-06-01", "2021-07-10", "2021-08-20"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
    tl.reset_cache()


# -- T1: flag-off byte identity ----------------------------------------------------------------------
def test_system_flag_off_is_byte_identical(monkeypatch):
    """STRONGER than the precedent's `not in`: pin the WHOLE string, not the absence of one substring.
    GRAPHRAG_MENTOR_VOICE and GRAPHRAG_CASCADE_QUANT both default ON, so the pre-feature persona is
    exactly mentor + cascade. If any future addendum leaks past its gate, this reds."""
    _clear(monkeypatch)
    assert an._system() == an._SYSTEM_MENTOR + an._SYSTEM_CASCADE
    assert an._SYSTEM_EPISODES not in an._system()
    # ... and the explicit thread-down argument defaults to the same answer.
    assert an._system(episodes=None) == an._SYSTEM_MENTOR + an._SYSTEM_CASCADE


def test_system_flag_off_unchanged_by_the_injection_seam(monkeypatch):
    """The prompt BODY half of byte identity: with the flag off timeline.episodes_for returns [] at
    timeline.py:140, so answer.py's `if n.episodes:` seam appends no line and there is nothing for the
    (absent) paragraph to talk about. Both halves are off together -- that is the whole design."""
    _clear(monkeypatch)
    assert tl.episodes_for("drivers/frost", "2026-01-01") == []


# -- T2: the gate ------------------------------------------------------------------------------------
def test_episodes_addendum_gated_in_answer_system(monkeypatch):
    _clear(monkeypatch)
    assert an._SYSTEM_EPISODES not in an._system()
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    assert an._SYSTEM_EPISODES in an._system()


def test_episodes_addendum_threads_down_as_an_argument(monkeypatch):
    """The house rule: the flag is read at the seam and threaded DOWN, never re-read deep in the
    renderer. An explicit argument therefore WINS over the environment in both directions."""
    _clear(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    assert an._SYSTEM_EPISODES not in an._system(episodes=False)
    monkeypatch.delenv("GRAPHRAG_TIMELINE", raising=False)
    assert an._SYSTEM_EPISODES in an._system(episodes=True)


def test_episodes_addendum_ordering_is_deterministic(monkeypatch):
    """Ordering is free but must be PINNED, so the cached prefix is a fixed string: Episodes rides
    after the pattern-records card and before the '## Outlook' addendum."""
    _clear(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    s = an._system(outlook=True)
    assert s == an._SYSTEM_MENTOR + an._SYSTEM_CASCADE + an._SYSTEM_EPISODES + an._SYSTEM_OUTLOOK


# -- T3: spelling parity with the ENGINE gate --------------------------------------------------------
def test_paragraph_ships_iff_the_engine_emits_lines(tmp_path, monkeypatch):
    """SPELLING ONLY -- the WEAKER half, and T7 below is the other one. This test injects an artifact via
    GRAPHRAG_TIMELINE_PATH, so `engine_emits` tracks the flag exactly and the equality it asserts is a
    property of THIS FIXTURE, not of the system: with the artifact absent (the fail-open branch at
    timeline.py:109-110) the flag is "on" and the engine emits nothing. Do not read a pass here as
    "the paragraph cannot ship without episodes" -- that is T7's job.

    THE FAIL-CLOSED PIN. timeline.py:140 is an exact-"on" match; _chain_on/_outlook_on/
    _pattern_records_on all accept on/1/true. A copy-paste of the house idiom would create a state
    (GRAPHRAG_TIMELINE=1) where the persona demands a '## Episodes' section on a turn with NO 'DATED
    EPISODES' line in the prompt -- an invitation to mint episodes, i.e. the exact +10-hallucination
    mode the layer was defaulted off for on 2026-07-04. Paragraph and engine must agree on EVERY
    spelling, so this asserts the two booleans are equal, not that either one is true."""
    _clear(monkeypatch)
    _artifact(tmp_path, monkeypatch)
    for v in ("on", "1", "true", "ON", "ON ", "On", "off", ""):
        monkeypatch.setenv("GRAPHRAG_TIMELINE", v)
        engine_emits = bool(tl.episodes_for("drivers/frost", "2026-01-01"))
        paragraph_ships = an._SYSTEM_EPISODES in an._system()
        assert paragraph_ships == engine_emits, f"gate spelling mismatch on GRAPHRAG_TIMELINE={v!r}"
        assert an._timeline_on() == engine_emits
    monkeypatch.delenv("GRAPHRAG_TIMELINE", raising=False)
    monkeypatch.delenv("GRAPHRAG_TIMELINE_PATH", raising=False)
    tl.reset_cache()


# -- T7: THE SEAM GATE -- the flag is NECESSARY, the injected line is the other half ------------------
def _volatile_with(line: str | None) -> str:
    """The volatile prompt EXACTLY as a serving body assembles it: real _l2-shaped blocks joined by the
    real answer._prompt_parts. Built through the shipped function so a change to how blocks are joined
    cannot silently hide the marker from the gate."""
    blocks = ["--- DATED EVIDENCE for arabica_coffee ---\n2021-07-20 GAIN: July frost hit Sul de Minas"]
    if line:
        blocks.append(line)
    blocks.append("GROUNDING LEDGER: 1 dated evidence item(s) and 0 observed number row(s).")
    _stable, volatile = an._prompt_parts("why does frost matter", ["arabica_coffee"], ["ctx"], blocks)
    return volatile


def _real_episode_line() -> str:
    """A REAL producer line -- tl.render_line, not a hand-typed string, so gate and producer share the
    one constant and cannot drift apart."""
    return tl.render_line("arabica_coffee", [{"start": "2021-06-01", "end": "2021-08-20", "n": 3,
                                              "receipt": {"date": "2021-07-10", "text": "frost damage"}}])


def test_seam_gate_needs_the_flag_AND_an_injected_line(monkeypatch):
    """VERIFIER BLOCKER 2, closed. The four states, measured through the shipped seam helper. Only the
    last one may ship the paragraph; the flag-only gate shipped it in all four."""
    _clear(monkeypatch)
    with_line, without = _volatile_with(_real_episode_line()), _volatile_with(None)
    assert tl.LINE_PREFIX in with_line and tl.LINE_PREFIX not in without
    assert an._episodes_on(with_line) is False                     # flag OFF, line present -> closed
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    assert an._timeline_on() is True                               # ... the flag alone says GO
    assert an._episodes_on(without) is False                       # dead artifact / no as-of / one-hop
    assert an._episodes_on(None) is False and an._episodes_on("") is False
    assert an._episodes_on(with_line) is True                      # the ONLY state that ships


def test_both_serving_bodies_resolve_episodes_through_the_seam_gate():
    """The gate is worth nothing if a body reverts to the flag. Pin the CALL SITES: every `_system(`
    in answer.py must take its `episodes=` from `_episodes_on`, and no body may pass `_timeline_on()`
    straight through. A source pin because that is exactly the regression shape -- the code was correct
    on every unit test while both bodies gated on the flag alone."""
    import inspect
    src = inspect.getsource(an)
    calls = [ln for ln in src.split("\n") if "_system(outlook=" in ln]
    assert len(calls) == 2, calls                                  # _answer_l2 + the one-hop legacy body
    assert all("episodes=_episodes" in ln for ln in calls), calls
    for body in (an._answer_l2, an.answer):
        bsrc = inspect.getsource(body)
        assert "_episodes = _episodes_on(vp)" in bsrc, body.__name__
        assert "episodes=_timeline_on()" not in bsrc, body.__name__


# -- T8: the persona's worked examples must enumerate NOTHING -----------------------------------------
def _persona_bullets() -> list[str]:
    return [ln for ln in an._SYSTEM_EPISODES.split("\n") if ln.startswith("- ")]


def test_persona_examples_are_schematic_and_score_zero_lines():
    """VERIFIER BLOCKER 3, closed. The examples used to be three fully-formed bullets over real spans --
    1994/2021 Brazil frost and the 2010-11 Russian export ban -- which are the deck's OWN measurement
    targets, so pasting them verbatim greened min_episode_lines, episode_magnitude_or_absence and
    min_episodes_cited and a green could no longer distinguish "enumerated the injected episodes" from
    "copied the persona". The 2021 span was worse than redundant: it is NOT in the artifact at that
    span, so the example DEMONSTRATED the confabulation P3 exists to catch.

    The examples are now schematic. _EPISODE_YEAR_RX matches a 4-digit year and 'YYYY' is not one, so a
    copied bullet is not an episode line at all -- the enumeration pins cannot be reached by copying."""
    bullets = _persona_bullets()
    assert len(bullets) == 3                                       # one per case that actually occurs
    for b in bullets:
        assert "YYYY" in b and not ev._EPISODE_YEAR_RX.search(b), b
    for span in ("1994-06", "2021-06", "2010-08", "2011-09", "Minas Gerais", "Russian export ban"):
        assert span not in an._SYSTEM_EPISODES, span               # no deck measurement target survives
    mech = ("## Mechanism\nUnrelated prose [E3].\n## The record\nFrost [E3] and the ban [E5].\n"
            "## Episodes\n" + "\n".join(bullets) + "\n## What to watch\nCold fronts.\n")
    out = _out(mech)
    assert ev._episode_lines(out) == []                            # ZERO lines off copied persona text
    res = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True}, out)
    assert res == {"min_episode_lines": False, "episode_magnitude_or_absence": False}


def test_persona_forbids_characterising_a_receiptless_window():
    """W4 A/B (2026-07-31): a NO-CITABLE-ITEM window came back labelled 'Black Sea export disruption
    episode'. Both absence slots underneath it were stated correctly -- the LABEL slot was the leak, and
    '<what the window is, in plain words>' invited exactly that. The label of an unreceipted window is now
    the injected line's own, verbatim, and the event vocabulary is named and banned."""
    s = an._SYSTEM_EPISODES
    assert "LABEL (between the span and the colon)" in s
    assert "the node name the injected line carries, verbatim" in s        # the CASE 1 slot
    assert "<what the window is, in plain words>" not in s.split("CASE 1")[1].split("CASE 2")[0]
    for w in ("disruption", "crisis", "shock", "collapse", "squeeze", "rally"):
        assert w in s, w                                                   # each characterisation banned
    assert "records WHEN reports clustered, not WHAT happened" in s        # the stated ground
    # CASE 2 and CASE 3 are untouched: a receipted window may still restate its receipt
    assert s.count("<what the window is, in plain words>") == 2


def test_persona_states_the_one_physical_line_rule():
    """Advisory A-7's producer half. eval._EPISODE_BULLET_RX never matches a continuation line, so a
    soft-wrapped bullet whose magnitude marker lands on line two reds episode_magnitude_or_absence on a
    CORRECT answer. The scorer is deliberately unchanged (it is shared with the shipped W4 pins); the
    producer is told not to wrap."""
    assert "ONE BULLET IS ONE PHYSICAL LINE" in an._SYSTEM_EPISODES
    wrapped = ("## Episodes\n"
               "- 1994-06..1994-08 -- Brazil frost: no citable item in this window,\n"
               "  so what happened is not narrated; no price record for this window.\n")
    mech = "## The record\nFrost [E3].\n" + wrapped + "## What to watch\nx\n"
    assert len(ev._episode_lines(_out(mech))) == 1                 # the continuation is NOT its own line
    assert _pins({"min_episode_lines": 1, "episode_magnitude_or_absence": True},
                 _out(mech))["episode_magnitude_or_absence"] is False   # the false red A-7 describes


# -- T4: producer/consumer agreement (the load-bearing test) -----------------------------------------
def test_rendered_section_is_parsed_by_eval_episode_lines():
    """eval is CALLED, not re-implemented. Three bullets in, three episode lines out."""
    lines = ev._episode_lines(_out(_MECH))
    assert len(lines) == 3
    assert [ln.split(" -- ")[0].strip("- ") for ln in lines] == [
        "1994-06..1994-08", "2021-06..2021-08", "2010-08..2011-09"]


def test_both_pins_pass_on_the_rendered_answer():
    res = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True,
                 "episode_absence_stated": True, "min_episode_sources": 2,
                 "min_episodes_cited": 1}, _out(_MECH))
    assert res == {"min_episode_lines": True, "episode_magnitude_or_absence": True,
                   "episode_absence_stated": True, "min_episode_sources": True,
                   "min_episodes_cited": True}


def test_both_pins_pass_after_the_real_sanitize_pass():
    """The pins read structured.mechanism POST-sanitize, so score the SANITIZED prose in both
    registers -- OUTLOOK is where the unbacked-level strip goes live over the whole mechanism."""
    for mr in (reg.FENCED, reg.OUTLOOK):
        mech = reg.sanitize(_MECH, market_register=mr)
        res = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True}, _out(mech))
        assert res == {"min_episode_lines": True, "episode_magnitude_or_absence": True}, mr


def test_every_line_is_backed_by_a_different_branch():
    """The three bullets exercise all three _line_backed branches, so the section is not green by
    accident on one of them: (B) declared absence, (A) cited handle, (C) cited handle + cited year."""
    out = _out(_MECH)
    lines = ev._episode_lines(out)
    assert ev._has_any(lines[0], ev._NO_CITABLE)                  # (B) absence branch, no handle at all
    assert not ev._has_any(lines[1], ev._NO_CITABLE) and "[E3]" in lines[1]        # (A) handle branch
    assert "[N2]" in lines[2] and "[E5]" in lines[2]              # (C) magnitude + the MANDATORY backing
    # ... and the (C) trap, stated out loud: an [N] handle is NOT evidence, so it can never back a line.
    assert {c["id"] for c in ev._cited_evidence(out)} == {"E3", "E5"}


def test_magnitude_absence_is_the_default_not_the_exception():
    """There is no per-episode price engine (only the SEAM-B avg_farm_price pair), so at most one or
    two bullets can EVER carry an [N] handle. The marker vocabulary is TURN-scoped, which is why it is
    legitimate on the IN-FLOOR 2021 episode and not only on the pre-floor 1994 one."""
    lines = ev._episode_lines(_out(_MECH))
    assert ev._has_any(lines[0], ev._NO_PRICE_RECORD)             # pre-price-floor
    assert ev._has_any(lines[1], ev._NO_PRICE_RECORD)             # IN-floor, still legitimately absent
    assert ev._N_HANDLE_RX.search(lines[2])
    # _NO_PRICE_RECORD is NOT in _line_backed -- a line marked only "no price record" is UNBACKED. This
    # is exactly why the template makes the BACKING slot mandatory on every bullet, priced ones included.
    assert not any(t in " ".join(ev._NO_CITABLE) for t in ("no price record", "no observed magnitude"))


# -- T5: one mutation per branch, each must RED ------------------------------------------------------
def test_mutation_unbacked_line_reds_min_episode_lines():
    """Drop BOTH the handle and the absence phrase from the 2021 bullet. E3 is then cited nowhere in
    prose, so it is not a cited citation and 2021 is not a cited year either -- the line has none of
    the three backings. min_episode_lines is an ALL-LINES quantifier: one bad bullet reds the row."""
    mech = _MECH.replace("in southern Minas Gerais reported through that window [E3]",
                         "somewhere in the belt at some point").replace(
        "The corpus documents frost damage in southern Minas Gerais [E3] and", "The record covers")
    assert "[E3]" not in mech
    res = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True}, _out(mech))
    assert res == {"min_episode_lines": False, "episode_magnitude_or_absence": True}


def test_mutation_missing_magnitude_marker_reds_the_magnitude_pin():
    mech = _MECH.replace("; no observed magnitude for this window.", ".")
    res = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True}, _out(mech))
    assert res == {"min_episode_lines": True, "episode_magnitude_or_absence": False}


def test_mutation_demoted_heading_reds_both_pins():
    """The consumer matches the heading on a NORMALISED PREFIX, so '## Episodes (3)' and '### Episodes'
    still count -- but '## Episode notes' is a different section and scores zero lines."""
    ok = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True},
               _out(_MECH.replace("## Episodes", "### Episodes (3) -- dated")))
    assert ok == {"min_episode_lines": True, "episode_magnitude_or_absence": True}
    bad = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True},
                _out(_MECH.replace("## Episodes", "## Episode notes")))
    assert bad == {"min_episode_lines": False, "episode_magnitude_or_absence": False}


def test_mutation_fenced_section_reds_both_pins():
    """Fence-awareness: a '## Episodes' inside a ``` block is CONTENT, not a heading."""
    mech = _MECH.replace(_EPISODES_SECTION, "```mermaid\n" + _EPISODES_SECTION + "```\n")
    res = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True}, _out(mech))
    assert res == {"min_episode_lines": False, "episode_magnitude_or_absence": False}


def test_mutation_prose_instead_of_bullets_reds_both_pins():
    """The enumeration contract: prose sentences that merely mention a year are NOT episode lines."""
    mech = _MECH.replace(_EPISODES_SECTION,
                         "## Episodes\nThe corpus documents frost in 1994 and again in 2021, and the "
                         "2010 export ban.\n")
    res = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True}, _out(mech))
    assert res == {"min_episode_lines": False, "episode_magnitude_or_absence": False}


def test_smoothed_answer_with_no_episodes_section_reds_min_episode_lines():
    """THE NEGATIVE THE WHOLE PIN EXISTS FOR: the confident 'usually' answer that cites the same
    evidence but never enumerates. `all([])` is vacuously true, so both pins must require a NON-EMPTY
    section -- an un-rendered '## Episodes' must not false-green."""
    mech = ("## Mechanism\nFrosts usually tighten the arabica balance sheet [E3].\n"
            "## The record\nThe corpus documents frost damage [E3] and the export ban [E5].\n"
            "## What to watch\nCold fronts.\n")
    out = _out(mech)
    assert ev._episode_lines(out) == []
    assert ev._episode_section(mech) is None
    res = _pins({"min_episode_lines": 2, "episode_magnitude_or_absence": True}, out)
    assert res == {"min_episode_lines": False, "episode_magnitude_or_absence": False}


# -- T6: register + strip survival -------------------------------------------------------------------
def test_section_survives_sanitize_in_both_registers():
    assert reg.sanitize(_EPISODES_SECTION) == _EPISODES_SECTION
    assert reg.sanitize(_EPISODES_SECTION, market_register=reg.OUTLOOK) == _EPISODES_SECTION
    assert reg.unbacked_levels(_EPISODES_SECTION) == []
    assert reg.internal_leaks(_EPISODES_SECTION) == []


def test_span_glyph_must_not_be_an_arrow():
    """Rule (i). register._DERIV_OUTPUT reads '->' as a derived-output marker, which VOIDS the citation
    exemption in unbacked_levels -- so an ARROWED bullet loses its handle's protection and the priced
    bullet's level goes unbacked. '..' is the glyph precisely because of this."""
    assert "->" not in _EPISODES_SECTION
    arrowed = _EPISODES_SECTION.replace("2010-08..2011-09", "2010-08 -> 2011-09")
    assert reg.unbacked_levels(arrowed) != []
    assert reg.unbacked_levels(_EPISODES_SECTION) == []


def test_report_count_as_a_numeral_is_stripped_under_outlook():
    """Rule (ii), the NEGATIVE CONTROL that pins WHY the paragraph forbids the count numeral.
    _level_tokens classifies any >=2-digit bare integer as a price level, so '(11 reports)' on an
    UNCITED bullet is an unbacked level -- and under OUTLOOK the strip deletes the whole line, reding
    both pins on an otherwise perfect answer. The ISO span itself is safe: _NUM_NOISE scrubs it."""
    bad = _EPISODES_SECTION.replace("-- Brazil frost: no citable item",
                                    "-- Brazil frost (11 reports): no citable item")
    assert reg.unbacked_levels(bad) != []
    stripped = reg.sanitize(bad, market_register=reg.OUTLOOK)
    assert "11 reports" not in stripped
    assert len(ev._episode_lines(_out(stripped))) < 3               # the line is GONE, both pins red
    res = _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True}, _out(stripped))
    assert res["min_episode_lines"] is False


def test_priced_bullets_cited_level_is_not_unbacked():
    """The counterpart: '5.70 USD/bu [N2]' is a level in a sentence carrying a handle and no derivation
    operator, so it is backed BY the citation and survives the OUTLOOK strip."""
    assert "5.70 USD/bu [N2]" in reg.sanitize(_EPISODES_SECTION, market_register=reg.OUTLOOK)


# -- T9 (W4-N1): the injected episodes must LEAVE the prompt -----------------------------------------
def test_l2_blocks_exports_the_injected_episode_record(monkeypatch):
    """THE PRODUCER HALF OF THE JUDGE FIX, run through the shipped function.

    Before this, tl.render_line's output existed ONLY inside the volatile prompt: `n.episodes` is never
    copied into _answer_l2's return dict, so no grader downstream could tell an ENUMERATED window from a
    MINTED one. Assert the record is stamped, that its `line` is the SAME STRING the model is sent (not a
    re-render), and that `spans` matches the prompt line's own span rendering."""
    from leviathan.graphrag import planner as pl
    monkeypatch.setattr(an, "_context_block", lambda g, c: f"CTX {c}")
    eps = [{"start": "1994-06-10", "end": "1994-08-01", "n": 11, "receipt": None},
           {"start": "2021-06-01", "end": "2021-08-20", "n": 3,
            "receipt": {"date": "2021-07-10", "text": "frost damage in southern Minas Gerais"}}]
    node = pl.GroundedNode(kind="driver", id="drivers/frost", contract="arabica_coffee", depth=1,
                           relevance=0.9, episodes=eps)
    sg = pl.Subgraph(seeds=["arabica_coffee"], nodes=[node])
    _stable, volatile = an._l2_blocks(sg, None, "2026-06-15")
    line = tl.render_line("drivers/frost", eps)
    assert any(line in b for b in volatile)                        # the model is sent it ...
    rec = sg.trace["episodes_injected"]                            # ... and the trace now carries it
    assert rec == [{"node": "drivers/frost", "line": line,
                    "spans": ["1994-06..1994-08", "2021-06..2021-08"]}]
    # the recorded spans are exactly what render_line writes into the prompt line, not a parallel format
    for sp in rec[0]["spans"]:
        assert sp in line


def test_no_episodes_no_record(monkeypatch):
    """FLAG-OFF / dead-artifact / no-as-of all reduce to `n.episodes == []`, and then the key must be
    ABSENT -- not present-and-empty. The OFF arm of the A/B must carry no episode record at all."""
    from leviathan.graphrag import planner as pl
    monkeypatch.setattr(an, "_context_block", lambda g, c: f"CTX {c}")
    node = pl.GroundedNode(kind="driver", id="drivers/frost", contract="arabica_coffee", depth=1,
                           relevance=0.9)
    sg = pl.Subgraph(seeds=["arabica_coffee"], nodes=[node])
    an._l2_blocks(sg, None, "2026-06-15")
    assert "episodes_injected" not in sg.trace


def test_answer_l2_spreads_the_trace_into_the_returned_dict():
    """The record rides the EXISTING plumbing: _answer_l2's return spreads **sg.trace into out['trace'],
    so no new return key was added and no consumer needs re-wiring. Pinned at the source because the
    whole judge fix depends on this one spread surviving."""
    import inspect
    src = inspect.getsource(an._answer_l2)
    assert "**sg.trace" in src
    assert 'sg.trace.setdefault("episodes_injected"' in inspect.getsource(an._l2_blocks)


# -- the shipped surfaces the fifth heading deliberately does NOT touch -------------------------------
def test_episodes_is_not_a_section_kind_and_not_in_the_fixed_scaffold():
    """None of the four shipped reserved headings ('## Cross-commodity', '## Complex-wide move',
    '## Recorded history', '## Outlook') is in _SECTION_KINDS or _FIXED_SCAFFOLD; they all sectionize
    to kind "other". Episodes follows that precedent exactly. Adding it to _SECTION_KINDS would break
    test_answer.py::test_section_kind_map_pins_to_eval_fixed_scaffold, and adding it to
    _FIXED_SCAFFOLD would impose a global ordering constraint on every deck for zero gain."""
    assert "Episodes" not in an._SECTION_KINDS
    assert not any("Episodes" in h for h in ev._FIXED_SCAFFOLD)
    secs = {s["heading"]: s["kind"] for s in an._sectionize(_MECH)}
    assert secs["Episodes"] == "other"
    assert ev._scaffold_ok(_out(_MECH)) is True                    # an extra heading is invisible to it


# == A5 -- episode_absence_label_fixed: the LABEL slot, scored deterministically ======================
# The shape line used to declare a UNIVERSAL '<plain-words label>' slot, which CASE 1 then contradicts.
# A model reading the universal rule first was being told to write words the record cannot support --
# and it did: "earlier Black Sea disruption window", "post-ban window", "early corpus window", all three
# observed in the W4 ON arm on windows whose two ABSENCE slots were stated correctly underneath. The
# prompt half is the carve-out below; the harness half is the pin, so the change is scored by the
# harness rather than by the panel (plan section 12's "five reader-facing changes, zero new pins").
def test_the_shape_line_carves_out_case_1():
    s = an._SYSTEM_EPISODES
    assert "BOTH slots -- BACKING and MAGNITUDE -- are REQUIRED" in s      # still both, named
    assert "EXCEPT in CASE 1" in s                                          # ... and the label carve-out
    assert "and BOTH slots are REQUIRED:" not in s                          # the old universal claim is gone
    # the two absence statements are what FILL those slots on a receipt-less window -- the carve-out is
    # about the LABEL, never a licence to leave a slot empty
    assert "never left empty" in s


_ABSENCE_SECTION = (
    "## Episodes\n"
    "- 1994-06..1994-08 -- drivers/frost: no citable item in this window, so what happened is not "
    "narrated; no price record for this window.\n")


def _absence_out(label: str):
    mech = ("## Mechanism\nm\n## The record\nr\n"
            + _ABSENCE_SECTION.replace("drivers/frost", label)
            + "## What to watch\nw\n")
    return _out(mech, cits=[])


def test_the_injected_label_copied_verbatim_passes():
    assert _pins({"episode_absence_label_fixed": True}, _absence_out("drivers/frost")) == \
        {"episode_absence_label_fixed": True}


def test_a_shortened_label_still_passes():
    """Containment, not equality: dropping a word is a shortening, not an invention, and equality would
    red an honest bullet. Every observed leak ADDED a word."""
    assert _pins({"episode_absence_label_fixed": True}, _absence_out("frost"))["episode_absence_label_fixed"]


def test_an_invented_characterisation_reds_the_pin():
    """The measured shape: the label acquires a word the injected line never carried."""
    for bad in ("earlier frost crisis window", "drivers/frost collapse", "catastrophic frost"):
        assert _pins({"episode_absence_label_fixed": True},
                     _absence_out(bad)) == {"episode_absence_label_fixed": False}, bad


def test_a_receipted_bullet_is_none_of_this_pins_business():
    """CASE 2/3 keep their plain-words label -- there the label IS read off a cited receipt, so the pin
    scores ONLY bullets that declare no citable item."""
    receipted = ("## Mechanism\nm\n## The record\nr\n## Episodes\n"
                 "- 2021-06..2021-08 -- Brazil frost: the corpus documents frost damage in southern "
                 "Minas Gerais reported through that window [E3]; no observed magnitude for this "
                 "window.\n## What to watch\nw\n")
    assert _pins({"episode_absence_label_fixed": True}, _out(receipted))["episode_absence_label_fixed"]


def test_a_plain_words_label_on_a_receiptless_bullet_reds_the_pin():
    """THE STRICTNESS, stated rather than discovered. `_MECH` above -- this file's own model of an
    honest render -- labels its receipt-less 1994 window 'Brazil frost' while the injected node is
    'drivers/frost'. That predates the verbatim rule (7dcdc918) and the pin reds it, deliberately: on a
    window with no citable item there is no receipt to read 'Brazil' off, and "the label may add a word
    the record does not carry" is exactly the licence the four measured leaks used. A false RED on a
    deterministic pin is visible in the row table; a false GREEN is not."""
    assert _pins({"episode_absence_label_fixed": True}, _out(_MECH)) ==         {"episode_absence_label_fixed": False}
    # ... and it is the LABEL alone that reds it: the same answer passes the two shipped enumeration pins
    assert _pins({"min_episode_lines": 3, "episode_magnitude_or_absence": True}, _out(_MECH)) ==         {"min_episode_lines": True, "episode_magnitude_or_absence": True}


def test_an_unrendered_section_cannot_pass_a_true_pin():
    """Anti-vacuity, the episode_magnitude_or_absence rule: `all([])` is true, so a turn that never
    rendered '## Episodes' must not green a true-pin."""
    mech = "## Mechanism\nm\n## The record\nr\n## What to watch\nw\n"
    assert _pins({"episode_absence_label_fixed": True}, _out(mech, cits=[])) == \
        {"episode_absence_label_fixed": False}


def test_a_minted_window_cannot_pass_the_label_pin():
    """A bullet that matches NO injected episode has no label it could have copied. Same refusal the
    other two enumeration pins make with `all(_adj)`, reached independently here."""
    out = _absence_out("drivers/frost")
    out["structured"]["mechanism"] = out["structured"]["mechanism"].replace("1994-06..1994-08",
                                                                            "1873-01..1873-04")
    assert _pins({"episode_absence_label_fixed": True}, out) == {"episode_absence_label_fixed": False}
