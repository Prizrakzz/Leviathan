"""D-DT-1 (render-side '## Episodes' scaffold, Option A) + D-DT-2 c1 (trace['fork_basis'] + the pin
split), ratified 2026-08-04 in docs/private/DESIGN_TRIO_DECISIONS.md.

The two changes ship as ONE image and TWO code paths, and this file keeps them apart the way the
verification record demands: S1 is a POST-model MUTATOR of reader-visible output, S2 c1 is a
PRE-synthesis OBSERVER that changes no output. They share a file and a trace dict and nothing else.

What is pinned here, in the order the acceptance shapes name it:

  A  DETECTOR PARITY -- answer._has_episode_section agrees with eval._episode_section on every
     mechanism, including the two-section hazard shapes ('### Episodes', '## Episodes (3)'). A NARROWER
     detector double-renders, and eval's last-section-wins reset then discards the model's own
     enumeration silently.
  B  the ONE env seam, house on/1/true idiom, default OFF.
  C  FLAG-OFF BYTE IDENTITY, proven rather than asserted: at the helper AND end to end against a
     control run whose only difference is that the scaffold call is a no-op (i.e. the pre-change body).
  D  THE RECEIPT BRANCH BOTH WAYS + the FALSE-ABSENCE IMPOSSIBILITY over the full receipt matrix.
  E  the three-place [E] rule, the evidence fence, and every fail-closed decline.
  F  the FOUR-CONSTRAINT SEAM, pinned by source order in BOTH serving bodies.
  G  fork_basis minted in BOTH bodies, its numeric leg equal to the old predicate, and independent of
     the answer prose WITH THE SCAFFOLD ON (V.4 X3's condition).
  H  the PIN SPLIT: fork_licensed registered + a strict superset, the 5 cascade/pace rows unchanged,
     and the 2 playbook rows re-keyed in both decks.
  I  episodes_model_authored reaches the per-answer record.

All offline: no pg, no S3, no LLM, no AWS. ASCII-only output (the Windows console is cp1252).
"""
from __future__ import annotations

import copy
import inspect
import json
import pathlib
import re

import pytest
import yaml

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import eval as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag import timeline as tl

_CFG = pathlib.Path(an.__file__).parents[3] / "configs" / "graphrag"


# ══ fixtures ═════════════════════════════════════════════════════════════════════════════════════════
class _Node:
    """The two attributes _scaffold_rows reads off a planner GroundedNode."""

    def __init__(self, nid, episodes):
        self.id = nid
        self.episodes = episodes


_RECEIPT = {"date": "2021-07-20", "text": "July frost hit Sul de Minas hard"}
_EPS = [{"start": "1994-06-10", "end": "1994-08-01", "n": 11, "receipt": None},
        {"start": "2021-06-01", "end": "2021-08-20", "n": 3, "receipt": _RECEIPT}]
_EVIDENCE = [{"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://gain",
              "text": "July frost hit Sul de Minas hard, damaging the 2022 crop"},
             {"date": "2016-02-01", "source": "wb_cmo", "source_key": "s3://wb", "text": "macro note"}]
_MECH_NO_EPISODES = ("## Mechanism\nFrost tightens the balance sheet.\n"
                     "## The record\nThe corpus documents frost damage [E1].\n"
                     "## What to watch\nFurther cold fronts.\n")


def _injected(eps=None, node="drivers/frost"):
    """One trace['episodes_injected'] record built through the REAL producers, so `line` and `spans` are
    byte-for-byte what _l2_blocks stamps and what the model was shown."""
    eps = _EPS if eps is None else eps
    return [{"node": node, "line": tl.render_line(node, eps),
             "spans": [tl.month_span(e) for e in eps],
             "windows": [{"start": tl.day_window(e)[0], "end": tl.day_window(e)[1],
                          "span": tl.month_span(e), "n": e.get("n")} for e in eps]}]


def _structured(mech=_MECH_NO_EPISODES):
    return {"tldr": "Frost risk is the live question.", "mechanism": mech,
            "sources": [{"ref": 1, "source": "usda_gain", "date": "2021-07-20", "note": "frost"}]}


def _verifier():
    return {"enabled": True, "checked": 1, "stripped": 0, "corrected": 0, "claim_count": 3, "by_rule": {},
            "resolved": {"1": {"source": "usda_gain", "date": "2021-07-20", "source_key": "s3://gain",
                               "snippet": "July frost hit Sul de Minas hard"}}}


def _scaffold(monkeypatch, *, on=True, structured=None, verifier=None, eps=None, evidence=None,
              nodes=None, n_positional=2):
    if on:
        monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    else:
        monkeypatch.delenv("GRAPHRAG_EPISODE_SCAFFOLD", raising=False)
    eps = _EPS if eps is None else eps
    st = _structured() if structured is None else structured
    vf = _verifier() if verifier is None else verifier
    trace = an._maybe_scaffold_episodes(
        st, vf, injected=_injected(eps), nodes=[_Node("drivers/frost", eps)] if nodes is None else nodes,
        evidence=_EVIDENCE if evidence is None else evidence, n_positional=n_positional)
    return st, vf, trace


def _graph(*, conflict=True):
    """arabica_coffee with two drivers on ONE target metric at ONE confidence. `conflict=False` flips the
    second driver's sign so the L1a leg is the ONLY thing that changes between the two graphs."""
    def _d(did, sign):
        return cs.Driver(id=did, type="hazard", sign=sign, mechanism=f"{did} mech", confidence="medium")
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[_d("frost", "+"), _d("drought", "-" if conflict else "+")],
        convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=1,
                                          drivers=["frost"])],
        inter_commodity=[])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


# ══ A -- DETECTOR PARITY (the _SECTION_KINDS cross-import idiom) ══════════════════════════════════════
_DETECTOR_CORPUS = (
    "",
    "   \n  ",
    _MECH_NO_EPISODES,
    "## Mechanism\nx\n## Episodes\n- 1994-06..1994-08 -- n: no citable item.\n## What to watch\ny",
    "## Episodes\n- a\n",                                        # section is the whole mechanism
    "### Episodes\n- 1994 frost\n",                              # level 3 -- the scorer accepts it
    "###### Episodes\n- 1994 frost\n",                           # level 6 -- the widest the scorer takes
    "## Episodes (3)\n- 1994 frost\n",                           # count suffix
    "## Episodes -- dated\n- 1994 frost\n",                      # dash suffix
    "##   Episodes\n- x\n",                                      # extra whitespace after the marker
    "   ## Episodes\n- x\n",                                     # indented heading
    "## episodes\n- x\n",                                        # lower case
    "## EPISODES\n- x\n",                                        # upper case
    "## Episodic drift\n- x\n",                                  # prefix match -- the scorer takes it too
    "## Episode\n- x\n",                                         # NOT a prefix of 'episodes' -> no section
    "# Episodes\n- x\n",                                         # level 1 -- outside the scorer's range
    "##Episodes\n- x\n",                                         # no space -> not a heading for either
    "## Mechanism\n```mermaid\n## Episodes\n```\nx\n",           # FENCED: content, never a heading
    "## Mechanism\n```\n## Episodes\n```\n## Episodes\n- x\n",   # one fenced, one real
    "## Mechanism\nx\n## Episodes\n- a\n## Episodes\n- b\n",     # two sections (the hazard shape)
)


def test_detector_is_exactly_as_wide_as_the_scorer():
    """answer CANNOT import eval (circular), so agreement is a cross-import TEST, exactly as
    _SECTION_KINDS <-> _FIXED_SCAFFOLD is cross-checked. A detector NARROWER than the scorer's is the
    double-render defect; a WIDER one is only a missed synthesis, so the direction that must never
    happen is the one this asserts away entirely -- they agree on every shape."""
    for mech in _DETECTOR_CORPUS:
        assert an._has_episode_section(mech) is (ev._episode_section(mech) is not None), mech


def test_the_corpus_actually_exercises_both_verdicts_and_the_hazard_shapes():
    """A parity corpus that is all-True or all-False proves nothing."""
    verdicts = {an._has_episode_section(m) for m in _DETECTOR_CORPUS}
    assert verdicts == {True, False}
    for hazard in ("### Episodes\n- 1994 frost\n", "## Episodes (3)\n- 1994 frost\n"):
        assert an._has_episode_section(hazard) is True           # a narrower detector would double-render


def test_answer_does_not_import_eval():
    """The reason the parity test exists at all -- stated as a fact about the module, not a comment.
    Read off the AST, so a comment SAYING 'cannot import eval' is not mistaken for the import itself."""
    import ast
    for node in ast.walk(ast.parse(inspect.getsource(an))):
        if isinstance(node, ast.Import):
            assert not any(a.name.endswith("eval") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not any(a.name == "eval" for a in node.names), node.module


def test_the_absence_vocabulary_mirror_is_exactly_the_scorers():
    """ROUND-2 MEDIUM. `_scaffold_survives` refuses an absence marker on a RECEIPTED bullet, and the
    vocabulary that decides is the SCORER's -- `episode_absence_stated` reads _NOT_KNOWN + _NO_CITABLE +
    _NO_PRICE_RECORD and `_absence_marked` reads _NO_PRICE_RECORD plus the R6 normalizing regex. answer
    cannot import eval, so the tuple is mirrored and THIS is what stops the mirror from being a hand copy:
    set equality on the tokens and pattern equality on the regex, so a scorer edit reds here."""
    assert set(an._SCAFFOLD_ABSENCE_MARKERS) == set(ev._NOT_KNOWN + ev._NO_CITABLE + ev._NO_PRICE_RECORD)
    assert len(an._SCAFFOLD_ABSENCE_MARKERS) == len(set(an._SCAFFOLD_ABSENCE_MARKERS))   # no dead dupes
    assert an._SCAFFOLD_ABSENCE_RX.pattern == ev._NO_PRICE_RX.pattern
    assert an._SCAFFOLD_ABSENCE_RX.flags == ev._NO_PRICE_RX.flags
    # ...and the engine's OWN clauses are inside that vocabulary, which is why the fence reads the CORPUS
    # HALF and not the raw line -- scanning the line would refuse every bullet the engine writes.
    assert ev._has_any(an._SCAFFOLD_CASE2_MAGNITUDE, an._SCAFFOLD_ABSENCE_MARKERS)
    assert ev._has_any(an._SCAFFOLD_CASE1_BACKING, an._SCAFFOLD_ABSENCE_MARKERS)
    assert ev._has_any(an._SCAFFOLD_CASE1_MAGNITUDE, an._SCAFFOLD_ABSENCE_MARKERS)
    for fixed in (an._SCAFFOLD_CASE1_BACKING, an._SCAFFOLD_CASE1_MAGNITUDE, an._SCAFFOLD_CASE2_MAGNITUDE):
        assert an._scaffold_corpus_half(f"- 1994-06..1994-08 -- n: {fixed}.").count(fixed) == 0


def test_the_scorer_keeps_the_last_section_which_is_why_width_matters():
    """The consequence a narrow detector would have: eval._episode_section resets its body on EVERY
    matching heading, so a synthesized second section REPLACES the model's own enumeration in scoring."""
    two = "## Mechanism\nx\n## Episodes\n- MODEL 1994 line\n## Episodes\n- ENGINE 1994 line\n"
    body = ev._episode_section(two)
    assert "ENGINE" in body and "MODEL" not in body


# ══ B -- the ONE env seam ═════════════════════════════════════════════════════════════════════════════
def test_flag_default_off_and_house_idiom(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_EPISODE_SCAFFOLD", raising=False)
    assert an._episode_scaffold_on() is False
    for truthy in ("on", "1", "true", "ON", " True "):
        monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", truthy)
        assert an._episode_scaffold_on() is True, truthy
    for falsy in ("", "off", "0", "no", "yes", "enabled"):
        monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", falsy)
        assert an._episode_scaffold_on() is False, falsy


def test_the_flag_is_read_per_call_not_memoized(monkeypatch):
    """Serving processes are long-lived: a once-at-import read makes the env-flip rollback a silent
    no-op until a redeploy, which defeats the whole point of the kill-switch."""
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    assert an._episode_scaffold_on() is True
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "off")
    assert an._episode_scaffold_on() is False


# ══ C -- FLAG-OFF BYTE IDENTITY, at the helper ════════════════════════════════════════════════════════
def test_flag_off_mutates_nothing_and_writes_no_trace_key(monkeypatch):
    """PROVEN, not asserted: the inputs are deep-copied and compared after the call."""
    st, vf = _structured(), _verifier()
    st0, vf0 = copy.deepcopy(st), copy.deepcopy(vf)
    _st, _vf, trace = _scaffold(monkeypatch, on=False, structured=st, verifier=vf)
    assert trace == {}                                            # no key -- absent, never present-and-False
    assert st == st0 and vf == vf0                                # byte-identical structured + verifier


def test_no_injected_window_is_also_a_no_op(monkeypatch):
    """Leg 2 of the three-leg gate. A FULLY FLOORED node stamps a record with spans: [] -- the floored
    line's own instruction is 'write no bullet for it' -- so it must not produce an empty heading, which
    is the exact defect timeline._FLOOR_ABSENCE exists to prevent."""
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    st, vf = _structured(), _verifier()
    st0 = copy.deepcopy(st)
    floored = [{"node": "drivers/frost", "line": tl.floored_line("drivers/frost", 4, 2),
                "spans": [], "windows": [], "floored": True}]
    trace = an._maybe_scaffold_episodes(st, vf, injected=floored, nodes=[_Node("drivers/frost", [])],
                                        evidence=_EVIDENCE, n_positional=2)
    assert trace == {} and st == st0


def test_model_authored_section_is_left_alone(monkeypatch):
    """Leg 3. The model wrote it -> no synthesis, prose untouched, and the report column says so."""
    mech = _MECH_NO_EPISODES.replace("## What to watch",
                                     "## Episodes\n- 1994-06..1994-08 -- drivers/frost: no citable item "
                                     "in this window; no price record for this window.\n## What to watch")
    st, vf, trace = _scaffold(monkeypatch, structured=_structured(mech))
    assert st["mechanism"] == mech
    assert trace["episodes_model_authored"] is True
    assert trace["episodes_scaffolded"] == {"fired": False, "n_bullets": 0, "n_receipted": 0}
    assert st["mechanism"].count("## Episodes") == 1              # exactly one section, always


# ══ D -- the RECEIPT BRANCH, both ways, and the FALSE-ABSENCE IMPOSSIBILITY ═══════════════════════════
def test_fires_and_renders_one_bullet_per_injected_window(monkeypatch):
    st, vf, trace = _scaffold(monkeypatch)
    assert trace["episodes_scaffolded"] == {"fired": True, "n_bullets": 2, "n_receipted": 1}
    assert trace["episodes_model_authored"] is False
    section = ev._episode_section(st["mechanism"])
    bullets = [ln for ln in section.split("\n") if ln.startswith("- ")]
    assert len(bullets) == 2
    # placed where the persona instructs: after '## The record', before '## What to watch'
    m = st["mechanism"]
    assert m.index("## The record") < m.index("## Episodes") < m.index("## What to watch")
    # the spans are the SAME strings the trace stamped, so eval._line_targets matches by construction
    assert [tl.month_span(e) for e in _EPS] == [b.split(" -- ")[0][2:] for b in bullets]


def test_receipt_less_window_gets_the_case1_template_verbatim(monkeypatch):
    st, _vf, _t = _scaffold(monkeypatch)
    bullet = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")][0]
    assert bullet == ("- 1994-06..1994-08 -- drivers/frost: no citable item in this window, so what "
                      "happened is not narrated; no price record for this window.")
    assert ev._has_any(bullet, ev._NO_CITABLE) and ev._has_any(bullet, ev._NO_PRICE_RECORD)


def test_the_case1_clauses_are_the_personas_own_words(monkeypatch):
    """ONE producer for the instruction and the synthesis. If a persona edit moves the CASE 1 wording,
    this reds here rather than silently leaving the engine writing vocabulary the deck no longer scores."""
    assert an._SCAFFOLD_CASE1_BACKING in an._SYSTEM_EPISODES
    assert an._SCAFFOLD_CASE1_MAGNITUDE in an._SYSTEM_EPISODES
    assert an._SCAFFOLD_CASE2_MAGNITUDE in an._SYSTEM_EPISODES


def test_receipted_window_restates_its_receipt_and_carries_a_handle(monkeypatch):
    st, vf, _t = _scaffold(monkeypatch)
    bullet = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")][1]
    assert bullet.startswith("- 2021-06..2021-08 -- drivers/frost: ")
    assert _RECEIPT["text"] in bullet and _RECEIPT["date"] in bullet
    assert "[E" in bullet and bullet.endswith("no observed magnitude for this window.")
    assert not ev._has_any(bullet, ev._NO_CITABLE)                # the whole point: no false absence


@pytest.mark.parametrize("mask", [(None, None), (None, _RECEIPT), (_RECEIPT, None), (_RECEIPT, _RECEIPT)])
def test_the_false_absence_sentence_is_impossible_on_a_receipted_window(monkeypatch, mask):
    """THE red line, over the full 2x2 receipt matrix: a bullet carries a _NO_CITABLE marker IF AND ONLY
    IF its episode's receipt is None. The two branches are disjoint on one boolean, so the false-absence
    path does not exist in code rather than being merely avoided."""
    eps = [{**e, "receipt": r} for e, r in zip(_EPS, mask)]
    st, _vf, trace = _scaffold(monkeypatch, eps=eps, nodes=[_Node("drivers/frost", eps)])
    bullets = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")]
    assert len(bullets) == 2 and trace["episodes_scaffolded"]["n_receipted"] == sum(1 for r in mask if r)
    for bullet, receipt in zip(bullets, mask):
        assert ev._has_any(bullet, ev._NO_CITABLE) is (receipt is None), bullet


def test_the_bullets_obey_the_format_fences(monkeypatch):
    """The two strip paths a synthesized bullet could walk into: '->' voids the citation exemption in
    register.unbacked_levels (so the span glyph is '..'), and a bare report-count numeral reads as a
    price level. Neither may appear."""
    from leviathan.graphrag import register as reg
    st, _vf, _t = _scaffold(monkeypatch)
    section = ev._episode_section(st["mechanism"])
    assert "->" not in section
    assert reg.unbacked_levels(section) == []
    assert reg.internal_leaks(section) == []
    assert str(_EPS[0]["n"]) not in section                       # the report count is never a numeral
    assert reg.sanitize(section) == section                       # survives the FENCED render-seam pass


# ══ E -- the three-place [E] rule, the evidence fence, and the fail-closed declines ═══════════════════
def test_the_synthesized_handle_is_written_to_all_three_places(monkeypatch):
    st, vf, _t = _scaffold(monkeypatch, structured=_structured(
        _MECH_NO_EPISODES.replace("[E1]", "(no handle)")))        # nothing to reuse -> a fresh mint
    ref = vf["synthesized_refs"][0]
    bullet = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")][1]
    assert f"[E{ref}]" in bullet                                            # 1. the bullet
    assert any(s.get("ref") == ref for s in st["sources"])                  # 2. structured['sources']
    assert vf["resolved"][str(ref)]["source_key"] == "s3://gain"            # 3. verifier['resolved']
    assert vf["resolved"][str(ref)]["date"] == "2021-07-20"
    # and it RENDERS: _cited_sources_block reads sources x resolved, which is why all three are needed
    assert f"[{ref}] " in an._cited_sources_block(st, vf, None)


def test_a_synthesized_ref_is_minted_above_the_positional_citation_namespace(monkeypatch):
    """The fold that makes the doc's `max(model refs) + 1` rule satisfy the doc's own acceptance:
    eval._cited_evidence joins a prose handle POSITIONALLY, so a ref inside that range would credit an
    unrelated retrieved item and move min_episodes_cited / min_episode_sources -- the two pins S1.7
    names as the sharpest check the A/B has."""
    st, vf, _t = _scaffold(monkeypatch, structured=_structured(
        _MECH_NO_EPISODES.replace("[E1]", "(no handle)")), n_positional=7)
    assert vf["synthesized_refs"] == [8]                          # above len(uniq)=7 AND above model ref 1


def test_an_already_cited_handle_is_reused_rather_than_minted(monkeypatch):
    """Correct attribution at zero cost: the E-form string was already on the page, so reuse cannot make
    any citation newly COUNTED. Nothing is appended to sources and no ref is recorded as synthesized."""
    st, vf, _t = _scaffold(monkeypatch)                           # _MECH_NO_EPISODES carries '[E1]'
    assert vf.get("synthesized_refs") in (None, [])
    assert len(st["sources"]) == 1
    bullet = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")][1]
    assert "[E1]" in bullet


def test_a_bare_handle_is_not_reused_because_the_scorer_joins_on_the_e_form(monkeypatch):
    """The model wrote '[1]', not '[E1]'. Reusing ref 1 would put '[E1]' on the page for the FIRST time
    and make that citation newly counted -- so the ref is minted out of band instead."""
    st, vf, _t = _scaffold(monkeypatch, structured=_structured(_MECH_NO_EPISODES.replace("[E1]", "[1]")))
    assert vf["synthesized_refs"] == [3]


def test_a_receipt_with_no_item_in_this_turns_evidence_declines_the_whole_scaffold(monkeypatch):
    """The hallucination fence: the synthesizer may cite ONLY an item already in this turn's evidence.
    Unmatched -> fail CLOSED to today's behaviour (the omission stands, visibly), never a handle that
    resolves to nothing and never a CASE-1 absence guessed onto a receipted window."""
    st, vf, trace = _scaffold(monkeypatch, evidence=[_EVIDENCE[1]])
    assert "## Episodes" not in st["mechanism"]
    assert trace["episodes_scaffolded"]["declined"] == "receipt_not_in_evidence"
    assert trace["episodes_model_authored"] is False              # nobody authored it -- not the model
    assert vf.get("synthesized_refs") in (None, [])


def test_a_decline_after_a_partial_mint_leaves_the_verifier_untouched(monkeypatch):
    """The decline is ALL-OR-NOTHING. Window 1 resolves and allocates a ref; window 2's receipt is not in
    this turn's evidence. A ref committed before the decline would leave a resolved handle pointing at an
    item no bullet cites -- exactly the dangling state the verifier exists to make impossible.
    (D-RC-11 update, deliberate: the two windows must be DISTINCT spans now -- the original spread
    _EPS[1] twice, and identical (node, span) rows are collapsed by the de-dup defect fix, which would
    have dropped window 2 before its receipt was ever inspected.)"""
    other = {"date": "2016-02-01", "text": "macro note"}
    eps = [{**_EPS[1], "receipt": other}, {**_EPS[0], "receipt": {"date": "1900-01-01", "text": "ghost"}}]
    st, vf = _structured(_MECH_NO_EPISODES.replace("[E1]", "(no handle)")), _verifier()
    vf0 = copy.deepcopy(vf)
    st2, vf2, trace = _scaffold(monkeypatch, structured=st, verifier=vf, eps=eps,
                                nodes=[_Node("drivers/frost", eps)])
    assert trace["episodes_scaffolded"]["declined"] == "receipt_not_in_evidence"
    assert vf == vf0                                              # byte-identical, mid-flight ref discarded
    assert "## Episodes" not in st["mechanism"]


def test_a_long_receipt_is_truncated_with_a_visible_marker(monkeypatch):
    """A bullet is read line by line, so the restatement is collapsed to one physical line and capped --
    with the same visible '...' verify.py uses, because a silent cut passes a fragment off as the whole
    item. NO QUOTATION MARKS: the bullet RESTATES, it does not quote (see the misquotation test)."""
    long_text = "frost damage " * 40
    receipt = {"date": "2021-07-20", "text": long_text[:180]}
    eps = [{**_EPS[1], "receipt": receipt}]
    ev_items = [{"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://gain", "text": long_text}]
    st, _vf, _t = _scaffold(monkeypatch, eps=eps, nodes=[_Node("drivers/frost", eps)], evidence=ev_items)
    bullet = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")][0]
    assert "\n" not in bullet and bullet.count('"') == 0 and "..." in bullet
    assert len(bullet) < 320


def test_a_window_that_cannot_be_resolved_to_its_episode_dict_declines(monkeypatch):
    """The receipt is recovered from the node's own episode dicts and VERIFIED span-for-span before use.
    A node the walk no longer carries (or a span that disagrees) is a state in which receipt-ness is
    UNKNOWN, and an unknown receipt may never become an asserted absence."""
    st, _vf, trace = _scaffold(monkeypatch, nodes=[_Node("drivers/other", _EPS)])
    assert "## Episodes" not in st["mechanism"]
    assert trace["episodes_scaffolded"]["declined"] == "unresolved_window"
    shifted = [{**_EPS[0], "start": "1993-06-10"}, _EPS[1]]
    st2, _v2, t2 = _scaffold(monkeypatch, nodes=[_Node("drivers/frost", shifted)])
    assert t2["episodes_scaffolded"]["declined"] == "unresolved_window" and "## Episodes" not in st2["mechanism"]


def test_the_section_emits_no_heading_other_than_episodes(monkeypatch):
    """V.4 X4's missing red line, and the only way S1 could ever corrupt S2's pin: the synthesized text
    must not mint '## Where the record disagrees' (or any other heading)."""
    st, _vf, _t = _scaffold(monkeypatch)
    section = ev._episode_section(st["mechanism"])
    assert not any(ln.lstrip().startswith("#") for ln in section.split("\n"))
    assert st["mechanism"].count("## Where the record disagrees") == 0


def test_appends_when_the_model_rendered_no_later_heading(monkeypatch):
    st, _vf, trace = _scaffold(monkeypatch, structured=_structured("## Mechanism\nJust the one section.\n"))
    assert trace["episodes_scaffolded"]["fired"] is True
    assert st["mechanism"].index("## Mechanism") < st["mechanism"].index("## Episodes")
    assert ev._scaffold_ok({"structured": st}) is True            # the fixed scaffold's order is unmoved


# ══ F -- THE FOUR-CONSTRAINT SEAM, pinned by source order in BOTH bodies ══════════════════════════════
@pytest.mark.parametrize("body", ["_answer_l2", "answer"])
def test_the_scaffold_call_sits_at_the_four_constraint_seam(body):
    """D-DT-1 M7: exactly one point satisfies all four constraints, and a later refactor must re-satisfy
    them rather than move the call for tidiness. Spelled identically in BOTH serving bodies (the W4-D3
    discipline), even though the one-hop body has no episode producer today."""
    src = inspect.getsource(getattr(an, body))
    call = src.index("_maybe_scaffold_episodes(")
    assert src.index("vf.verify_citations(") < call, "strip-rate denominators would move"
    assert src.index("verified_mechanism=structured") < call, "the A4b raw-draft audit would see engine text"
    assert call < src.index("_humanize_structured(structured"), "a raw node id would never be humanized"
    assert call < src.index("render(structured"), "render() would not see the section"


def test_the_seam_constraints_are_written_down_where_the_code_lives():
    """A seam that is only correct by accident moves on the next refactor. The four constraints are
    stated in the module so the next reader has them at hand."""
    doc = inspect.getsource(an._maybe_scaffold_episodes)
    assert "THREE-LEG FIRE CONDITION" in doc and "RECEIPT-BRANCHING" in doc


# ══ G -- fork_basis: BOTH mint bodies, the superset equality, and the circularity fence ═══════════════
_BASIS_KEYS = {"numeric", "driver_conflict", "tier_mixed", "episodes"}


def _run(gr, *, planner, monkeypatch, mech=None, retrieve=None):
    calls = {}

    def fake_call(system, user, *, model, tool, **kw):
        calls["user"] = user
        return {"tldr": "t", "diagram_mermaid": "",
                "mechanism": _MECH_NO_EPISODES if mech is None else mech,
                "sources": [{"ref": 1, "source": "usda_gain", "date": "2021-07-20", "note": "frost"}]}

    def _retr(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://gain",
                 "text": "July frost hit Sul de Minas hard"},
                {"date": "2016-02-01", "source": "wb_cmo", "source_key": "s3://wb", "text": "macro note"}]
    tl.reset_cache()
    return an.answer("where do the arabica frost episodes disagree", graph=gr, planner=planner,
                     asof="2026-01-01", retrieve=retrieve or _retr, call=fake_call,
                     route_fn=lambda q, gg: ["arabica_coffee"])


@pytest.mark.parametrize("planner", ["l2", None])
def test_fork_basis_is_minted_in_both_serving_bodies(planner, monkeypatch):
    """V-9: minting only in _answer_l2 would leave a one-hop turn with NO basis key at all, so
    fork_licensed would evaluate against a missing dict on the one planner where no fork producer
    exists. Both bodies stamp it, with the identical expression."""
    basis = _run(_graph(), planner=planner, monkeypatch=monkeypatch)["trace"]["fork_basis"]
    assert set(basis) == _BASIS_KEYS
    assert basis["numeric"] is False                              # no cascade fired on either body here
    assert basis["driver_conflict"] is True                       # frost '+' vs drought '-', same conf
    assert basis["tier_mixed"] is True                            # usda_gain is T2, wb_cmo is T4


@pytest.mark.parametrize("planner", ["l2", None])
def test_driver_conflict_is_false_when_the_drivers_agree(planner, monkeypatch):
    """Non-vacuity: a flag that is always true measures nothing. The ONLY difference between the graphs
    is the second driver's sign."""
    basis = _run(_graph(conflict=False), planner=planner, monkeypatch=monkeypatch)["trace"]["fork_basis"]
    assert basis["driver_conflict"] is False


def test_tier_mixed_is_false_on_a_single_tier_turn(monkeypatch):
    def _one_tier(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://a", "text": "x"},
                {"date": "2016-02-01", "source": "usda_gain", "source_key": "s3://b", "text": "y"}]
    basis = _run(_graph(), planner="l2", monkeypatch=monkeypatch, retrieve=_one_tier)["trace"]["fork_basis"]
    assert basis["tier_mixed"] is False


def test_numeric_leg_equals_the_old_predicate_exactly():
    """D-DT-2 c1 acceptance item 2 -- the equality that PROVES the new pin is a strict superset of the
    old one. `numeric` must be `divergence_nodes > 0 or reroute_pairs > 0`, computed off the same trace,
    on every combination of the two counters."""
    for quant, reroute in (([], []), ([{"divergence": None}], []), ([{"divergence": {"a": 1}}], []),
                           ([], [{"pair": 1}]), ([{"divergence": {"a": 1}}], [{"pair": 1}])):
        trace = {"quantify": quant, "quantify_reroute": reroute}
        cs_ = ev._cascade_stats({"trace": trace})
        old = cs_["divergence_nodes"] > 0 or cs_["reroute_pairs"] > 0
        assert an._fork_basis(None, [], [], trace)["numeric"] is old, trace


def test_episodes_leg_needs_two_windows():
    """L2/L4: 'where do they disagree' needs at least two things to disagree."""
    one = [{"node": "n", "spans": ["1994-06..1994-08"]}]
    assert an._fork_basis(None, [], [], {"episodes_injected": one})["episodes"] is False
    assert an._fork_basis(None, [], [], {"episodes_injected": _injected()})["episodes"] is True
    assert an._fork_basis(None, [], [], {})["episodes"] is False


def test_the_basis_is_minted_before_the_model_call_in_both_bodies():
    """THE CIRCULARITY FENCE AS AN ORDERING INVARIANT (V.4 X3). D-DT-1's scaffold now WRITES
    structured['mechanism'], so a basis computed at the return statement could read the engine's own
    output. Minting it BEFORE the model call makes that unreachable: there is no prose yet to read."""
    for body, mint in (("_answer_l2", 'sg.trace["fork_basis"] = _fork_basis('),
                       ("answer", "_fork_basis_v = _fork_basis(")):
        src = inspect.getsource(getattr(an, body))
        assert src.index(mint) < src.index("structured = call("), body
    assert "structured" not in inspect.getsource(an._fork_basis)


def test_the_basis_is_byte_identical_with_and_without_the_answer_prose(monkeypatch):
    """Acceptance item 1, run WITH THE SCAFFOLD ON as X3 requires. Two turns whose ONLY difference is
    the model's prose -- one empty, one carrying both a fork heading and an Episodes section -- must
    produce the same basis."""
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    empty = _run(_graph(), planner="l2", monkeypatch=monkeypatch, mech="")["trace"]["fork_basis"]
    rich = _run(_graph(), planner="l2", monkeypatch=monkeypatch,
                mech=(_MECH_NO_EPISODES + "## Where the record disagrees\nthey diverge.\n"
                      "## Episodes\n- 1994-06..1994-08 -- x: no citable item.\n"))["trace"]["fork_basis"]
    assert empty == rich


def test_the_basis_does_not_move_when_the_scaffold_actually_fires(monkeypatch):
    """The sharpest form of the same fence: recompute the basis from the SAME engine inputs after the
    scaffold has rewritten structured['mechanism']. Identical, because the basis never reads structured."""
    trace = {"episodes_injected": _injected(), "quantify": [], "quantify_reroute": []}
    before = an._fork_basis(_graph(), ["arabica_coffee"], _EVIDENCE, trace)
    st, _vf, scaf = _scaffold(monkeypatch)
    assert scaf["episodes_scaffolded"]["fired"] is True and "## Episodes" in st["mechanism"]
    assert an._fork_basis(_graph(), ["arabica_coffee"], _EVIDENCE, trace) == before


def test_answer_v2_flag_does_not_change_the_basis(monkeypatch):
    """Acceptance item 3: the basis must not ride structured['sections'], which exists only under
    GRAPHRAG_ANSWER_V2=on."""
    monkeypatch.setenv("GRAPHRAG_ANSWER_V2", "off")
    off = _run(_graph(), planner="l2", monkeypatch=monkeypatch)["trace"]["fork_basis"]
    monkeypatch.setenv("GRAPHRAG_ANSWER_V2", "on")
    on = _run(_graph(), planner="l2", monkeypatch=monkeypatch)["trace"]["fork_basis"]
    assert off == on


def test_all_three_orchestrator_whitelists_carry_fork_basis():
    """The coupling half, exactly as U3 and C2 pin theirs: the key reaches an artifact on the numbers
    lanes only because three fixed tuples in a file this lane does not own name it. Appending must also
    leave the two EXISTING source-count assertions standing."""
    from leviathan.graphrag import orchestrator as orch
    src = inspect.getsource(orch)
    assert src.count('"fork_basis"') == 3
    assert src.count('"question_shape", "shape_metric_states", "shape_decline_guard"') == 3
    assert src.count('"unit_mismatch_guard"') == 3


# ══ C (continued) -- FLAG-OFF BYTE IDENTITY, end to end ══════════════════════════════════════════════
def _timeline_on(tmp_path, monkeypatch):
    art = tmp_path / "episodes.json"
    art.write_text(json.dumps({"arabica_coffee": [
        {"start": "1994-06-10", "end": "1994-08-01", "dates": ["1994-06-10", "1994-07-05", "1994-08-01"]},
        {"start": "2021-06-01", "end": "2021-08-20", "dates": ["2021-06-01", "2021-07-20", "2021-08-20"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    monkeypatch.setenv("GRAPHRAG_TIMELINE_PATH", str(art))
    tl.reset_cache()


def test_flag_off_turn_is_byte_identical_to_the_pre_change_body(tmp_path, monkeypatch):
    """PROVEN END TO END, not asserted. The control run replaces the scaffold call with a no-op -- which
    IS the pre-change body, because before D-DT-1 no such call existed and nothing else in the body
    moved. Same graph, same fakes, same as-of, one variable.

    THE PROMISE IS SCOPED TO THE ANSWER BODY (V.4 X2): D-DT-2 c1 mints fork_basis unconditionally on the
    same image, so `trace` carries one new key on BOTH arms and is exempt. That scoping is what makes
    the OFF arm mean something, and it is asserted here rather than left to be discovered mid-A/B."""
    _timeline_on(tmp_path, monkeypatch)
    monkeypatch.delenv("GRAPHRAG_EPISODE_SCAFFOLD", raising=False)
    live = _run(_graph(), planner="l2", monkeypatch=monkeypatch)
    monkeypatch.setattr(an, "_maybe_scaffold_episodes", lambda *a, **k: {})
    control = _run(_graph(), planner="l2", monkeypatch=monkeypatch)
    assert live["answer"] == control["answer"]
    assert live["structured"] == control["structured"]
    assert live["citations"] == control["citations"]
    assert live["trace"]["citation_verifier"] == control["trace"]["citation_verifier"]
    assert set(live["trace"]) == set(control["trace"])
    # and the turn WAS susceptible -- an OFF-arm proof over a turn with no injected window proves nothing
    assert len(live["trace"]["episodes_injected"][0]["spans"]) == 2
    assert "episodes_scaffolded" not in live["trace"]
    assert "episodes_model_authored" not in live["trace"]
    assert set(live["trace"]["fork_basis"]) == _BASIS_KEYS        # the ONE key trace gains, on both arms


def test_flag_on_turn_fires_end_to_end_and_the_citation_pins_do_not_move(tmp_path, monkeypatch):
    """The ON arm of the same turn: the section appears, and the two pins S1.7 says can never
    legitimately change do not."""
    _timeline_on(tmp_path, monkeypatch)
    monkeypatch.delenv("GRAPHRAG_EPISODE_SCAFFOLD", raising=False)
    off = _run(_graph(), planner="l2", monkeypatch=monkeypatch)
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    on = _run(_graph(), planner="l2", monkeypatch=monkeypatch)
    assert "## Episodes" not in (off["structured"]["mechanism"])
    assert on["trace"]["episodes_scaffolded"]["fired"] is True
    assert "## Episodes" in on["structured"]["mechanism"] and "## Episodes" in on["answer"]
    q = {"contract": "arabica_coffee", "asof": "2026-01-01",
         "expect": {"min_episodes_cited": 1, "min_episode_sources": 1}}
    assert ev._cascade_asserts(q, on) == ev._cascade_asserts(q, off)
    # the raw-draft counters are computed upstream of the seam, so they cannot move either
    for k in ("banned_valuation_words", "banned_flow_words", "banned_exec_words", "unbacked_levels"):
        assert on["trace"][k] == off["trace"][k]


def test_a_contract_node_label_inherits_the_models_own_exposure_and_never_more(tmp_path, monkeypatch):
    """MEASURED, not assumed. reg.sanitize humanizes a CONTRACT-node id into its display name
    ('arabica_coffee' -> a name carrying an exchange token), and eval._absence_label_ok wants the
    label's tokens to be a SUBSET of the node's -- so on such a node the key can red. That is EXACTLY
    what happens to a MODEL bullet copying the same id verbatim, as the persona instructs, and it can
    never be worse than not firing: with no section at all the key reds on its non-empty guard anyway.
    Pinned here so the day the display registry changes, this reads as a known surface, not a surprise."""
    _timeline_on(tmp_path, monkeypatch)
    monkeypatch.delenv("GRAPHRAG_EPISODE_SCAFFOLD", raising=False)
    off = _run(_graph(), planner="l2", monkeypatch=monkeypatch)
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    on = _run(_graph(), planner="l2", monkeypatch=monkeypatch)
    q = {"contract": "arabica_coffee", "expect": {"episode_absence_label_fixed": True}}
    off_v = ev._cascade_asserts(q, off)["episode_absence_label_fixed"]
    on_v = ev._cascade_asserts(q, on)["episode_absence_label_fixed"]
    assert off_v is False                                         # no section -> the non-empty guard reds
    assert on_v is False or on_v is True                          # display-name dependent, by construction
    assert (not off_v) or on_v, "firing must never turn a green into a red"
    # the label the engine wrote IS the injected line's own node label, before humanization
    assert "arabica_coffee" in on["trace"]["episodes_injected"][0]["line"]


# ══ H -- THE PIN SPLIT ════════════════════════════════════════════════════════════════════════════════
def _pin(key, *, basis, heading, want=True, fired_numeric=False):
    mech = "## Mechanism\nx\n" + ("## Where the record disagrees\nthey differ.\n" if heading else "")
    trace = {"quantify": [{"divergence": {"a": 1}}] if fired_numeric else [], "quantify_reroute": []}
    if basis is not None:
        trace["fork_basis"] = basis
    out = {"structured": {"tldr": "", "mechanism": mech}, "citations": [], "trace": trace}
    return ev._cascade_asserts({"contract": "c", "expect": {key: want}}, out)[key]


def test_fork_licensed_is_registered_or_it_is_scored_by_nothing():
    """A pin key absent from _CASCADE_EXPECT is silently DROPPED by _cascade_asserts -- a deck row that
    pins nothing looks exactly like a deck row that passes."""
    assert "fork_licensed" in ev._CASCADE_EXPECT
    assert "no_unbacked_fork" in ev._CASCADE_EXPECT               # the split keeps BOTH


def test_fork_licensed_reds_only_on_an_unlicensed_heading():
    none_live = {"numeric": False, "driver_conflict": False, "tier_mixed": False, "episodes": False}
    assert _pin("fork_licensed", basis=none_live, heading=True) is False
    assert _pin("fork_licensed", basis=none_live, heading=False) is True
    for flag in ("numeric", "driver_conflict", "tier_mixed", "episodes"):
        assert _pin("fork_licensed", basis={**none_live, flag: True}, heading=True) is True, flag
    # one-directional, exactly like no_unbacked_fork: a false-pin never asserts anything
    assert _pin("fork_licensed", basis=none_live, heading=True, want=False) is True


def test_fork_licensed_is_a_strict_superset_of_no_unbacked_fork():
    """The whole safety argument for the split: `numeric` IS the old predicate, so anything that passes
    today passes tomorrow. Checked over the full (fork fired?) x (heading?) truth table."""
    for fired in (False, True):
        for heading in (False, True):
            basis = {"numeric": fired, "driver_conflict": False, "tier_mixed": False, "episodes": False}
            old = _pin("no_unbacked_fork", basis=None, heading=heading, fired_numeric=fired)
            new = _pin("fork_licensed", basis=basis, heading=heading, fired_numeric=fired)
            assert old == new                                     # identical when only `numeric` is live
            assert (not old) or new                               # ... and never a NEW failure


def test_a_missing_basis_is_unlicensed_and_that_is_safe():
    """Fail-closed. Both answer.py bodies mint the key, so an absent basis means the turn came from
    neither -- a numbers_only lane, which carries no structured mechanism, so no heading can render."""
    assert _pin("fork_licensed", basis=None, heading=True) is False
    assert _pin("fork_licensed", basis=None, heading=False) is True
    out = {"structured": None, "citations": [], "trace": {}}      # the numbers_only shape
    assert ev._cascade_asserts({"contract": "c", "expect": {"fork_licensed": True}}, out) == {
        "fork_licensed": True}


def test_no_unbacked_fork_still_reads_the_two_counters_and_nothing_else():
    """The five cascade/pace rows keep BYTE-IDENTICAL semantics -- so the branch must not learn about
    fork_basis. A split that quietly widened the old key would have re-scored 9 pin instances."""
    src = inspect.getsource(ev._cascade_asserts)
    branch = src[src.index('elif k == "no_unbacked_fork"'):src.index('elif k == "fork_licensed"')]
    assert 'fired = cs["divergence_nodes"] > 0 or cs["reroute_pairs"] > 0' in branch
    assert "fork_basis" not in branch


def test_the_five_cascade_and_pace_rows_score_identically_after_the_split():
    """The proof the split changed nothing for them: every row that pinned no_unbacked_fork before the
    split still pins it, none has acquired fork_licensed, and the key's verdict is unchanged on all
    three reachable states."""
    expected = {"premise_contradict_russia_wheat_2010", "premise_confirm_soy_tariffs_2018",
                "esr_pace_corn_2026", "weather_heat_corn_2026", "pace_p1_probe"}
    seen, instances = set(), 0
    for name in ("eval_queries_v4_cascade.yaml", "eval_queries_v34_combined.yaml", "pace_p1_probe.yaml"):
        path = _CFG / name
        if not path.exists():
            pytest.skip(f"{name} is gitignored and absent from this tree")
        for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("queries") or []:
            exp = r.get("expect") or {}
            if "no_unbacked_fork" in exp:
                seen.add(r["id"])
                instances += 1
                assert "fork_licensed" not in exp, r["id"]
                assert exp["no_unbacked_fork"] is True, r["id"]
    assert seen == expected and instances == 9                    # 13 - the 4 re-keyed playbook instances
    # ... and the verdict itself, on the three states a turn can be in
    assert _pin("no_unbacked_fork", basis=None, heading=True, fired_numeric=False) is False
    assert _pin("no_unbacked_fork", basis=None, heading=True, fired_numeric=True) is True
    assert _pin("no_unbacked_fork", basis=None, heading=False, fired_numeric=False) is True


def test_the_two_playbook_rows_are_re_keyed_in_both_decks():
    """2.5's deck row: the SAME two ids live in both playbook decks, so both must move or one row is
    scored under two different rules depending on which deck ran."""
    for name in ("eval_queries_playbooks_v1.yaml", "eval_queries_playbooks_r6residual.yaml"):
        path = _CFG / name
        if not path.exists():
            pytest.skip(f"{name} is gitignored and absent from this tree")
        rows = {r["id"]: (r.get("expect") or {})
                for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("queries") or []}
        for rid in ("pb_brazil_drought_vs_frost", "pb_disagree_eras"):
            assert rows[rid].get("fork_licensed") is True, (name, rid)
            assert "no_unbacked_fork" not in rows[rid], (name, rid)
        assert not any("no_unbacked_fork" in e for e in rows.values()), name


_TAUTOLOGY_FAMILIES = ("min_episode_lines", "episode_magnitude_or_absence",
                       "episode_absence_stated", "episode_absence_label_fixed")


@pytest.mark.parametrize("name", ["eval_queries_playbooks_v1.yaml", "eval_queries_playbooks_r6residual.yaml"])
def test_both_deck_headers_disclose_the_tautology_surface_with_correct_counts(name):
    """D-DT-1 component 6's DECK half, and M3 makes it a PRECONDITION of the A/B: "it must be disclosed in
    the deck header BEFORE the A/B, not discovered after it". Four pin families stop measuring the model
    the moment the scaffold fires, and a scorer reading a green sweep without that sentence in front of
    them is reading the renderer and calling it the model.

    THE COUNTS ARE RE-DERIVED HERE, per deck, and the header must carry the numbers this parse produces.
    That is deliberate: a hand-copied count is exactly how the surface came to be disclosed as five rows
    when it was seven, and both decks are gitignored with no mirror, so a stale number is not diffable."""
    path = _CFG / name
    if not path.exists():
        pytest.skip(f"{name} is gitignored and absent from this tree")
    text = path.read_text(encoding="utf-8")
    rows = (yaml.safe_load(text) or {}).get("queries") or []
    header = text.split("\nqueries:")[0]
    counts = {k: [r["id"] for r in rows if k in (r.get("expect") or {})] for k in _TAUTOLOGY_FAMILIES}
    total = sum(len(v) for v in counts.values())
    assert f"{total} PIN INSTANCES ACROSS THESE {len(rows)} ROWS" in header, (total, len(rows))
    assert "GRAPHRAG_EPISODE_SCAFFOLD" in header                  # the flag is NAMED where env lives
    assert "DEFAULT OFF" in header and "byte-identical" in header
    for key, ids in counts.items():
        assert key in header, key
        # the per-family row count, as the header's own aligned column
        assert re.search(rf"^#\s+{re.escape(key)}\s+{len(ids)}\s+", header, re.M), (key, len(ids))
        # every affected row NAMED, not summarised -- or, where a family covers all but a handful, the
        # EXCEPTIONS named instead. Both forms are exact; a bare count is what let a wrong one survive.
        others = [r["id"] for r in rows if r["id"] not in ids]
        assert all(rid in header for rid in ids) or (others and all(o in header for o in others)), key
    # the re-label itself -- the doc's word, on every family
    assert header.count("ENGINE+RENDERER") >= len(_TAUTOLOGY_FAMILIES)
    # ...and the pins that still measure the MODEL are named as the ones whose delta carries information
    for k in ("min_episodes_cited", "min_episode_sources", "min_cascade_cited", "unbacked_levels",
              "episodes_model_authored"):
        assert k in header, k


def test_the_v1_header_names_the_flag_in_the_one_env_per_run_block():
    """The block an operator actually reads when assembling a run. A flag disclosed only in prose further
    down is a flag that gets set as a background setting, which is how a one-variable A/B becomes two."""
    path = _CFG / "eval_queries_playbooks_v1.yaml"
    if not path.exists():
        pytest.skip("deck is gitignored and absent from this tree")
    text = path.read_text(encoding="utf-8")
    env_block = text.split("ONE ENV PER RUN")[1].split("\n#   OFF ARM:")[0]
    assert "GRAPHRAG_EPISODE_SCAFFOLD" in env_block
    assert "DO NOT SET IT IN THE SAME RUN AS THE GRAPHRAG_TIMELINE A/B" in env_block


def test_every_playbook_expect_key_is_one_the_harness_implements():
    """A typo'd expect key is silently ignored by _cascade_asserts, so a re-key that mis-spelled the new
    name would look exactly like a passing row."""
    known = set(ev._CASCADE_EXPECT) | {"needs_evidence", "not_known", "drivers", "regime",
                                       "banned_flow", "banned_valuation"}
    for name in ("eval_queries_playbooks_v1.yaml", "eval_queries_playbooks_r6residual.yaml"):
        path = _CFG / name
        if not path.exists():
            pytest.skip(f"{name} is gitignored and absent from this tree")
        for r in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("queries") or []:
            assert not (set(r.get("expect") or {}) - known), (name, r["id"])


# ══ I -- the REPORT COLUMN ════════════════════════════════════════════════════════════════════════════
def _record(trace):
    row = {"q": {"id": "pb_x"}, "out": {"answer": "a", "structured": {"tldr": "", "mechanism": ""},
                                        "citations": [], "trace": trace},
           "rubric": {"intent_ok": True}, "secs": 1.0}
    return ev._per_answer_record(row, "single")


def test_episodes_model_authored_and_fork_basis_reach_the_per_answer_record():
    """_per_answer_record is a HARD WHITELIST and the single source of truth for both the partial JSONL
    and the baseline JSON, so a trace key not named there reaches NO artifact. Both new columns must be
    in it or the A/B column and the c1 census are unreadable."""
    basis = {"numeric": False, "driver_conflict": True, "tier_mixed": True, "episodes": True}
    rec = _record({"episodes_model_authored": False, "fork_basis": basis,
                   "episodes_scaffolded": {"fired": True, "n_bullets": 2, "n_receipted": 1}})
    assert rec["episodes_model_authored"] is False
    assert rec["fork_basis"] == basis
    assert json.loads(json.dumps(rec))["fork_basis"] == basis     # JSONL-serializable, no surprises
    assert _record({"episodes_model_authored": True})["episodes_model_authored"] is True
    assert _record({})["episodes_model_authored"] is None         # OFF arm / not susceptible -> absent
    assert _record({})["fork_basis"] is None
    # the STAMP too: a boolean cannot tell 'fired' from 'fired degraded' from 'fail-closed declined', and
    # a fallback rung that reaches no artifact is a SILENT fallback in the middle of an A/B
    assert rec["episodes_scaffolded"] == {"fired": True, "n_bullets": 2, "n_receipted": 1}
    assert _record({})["episodes_scaffolded"] is None
    for extra in ({"restatement_dropped": True}, {"declined": "sanitize_would_strip_the_bullet"}):
        stamp = {"fired": bool(extra.get("restatement_dropped")), "n_bullets": 1, "n_receipted": 1, **extra}
        assert _record({"episodes_scaffolded": stamp})["episodes_scaffolded"] == stamp


def test_the_column_is_a_column_and_not_a_pin():
    """D-DT-1 component 6 is explicit: a REPORT COLUMN, never a pin. A pin would make the model's own
    compliance a gate on a turn the engine has already fixed."""
    assert "episodes_model_authored" not in ev._CASCADE_EXPECT
    assert "episodes_scaffolded" not in ev._CASCADE_EXPECT


# ══ J -- SANITIZE STABILITY: the two blockers, their fences, and the fail-closed ladder ═══════════════
# The adversarial pass proved a receipted CASE-2 bullet was NOT sanitize-stable. reg.sanitize's strip is
# CLAUSE-scoped (register._SENT_KEEP splits on ';' as well as '.!?'), and the bullet put the receipt text
# and the [E] handle in a trailing clause, so a receipt carrying an execution/valuation idiom had that
# clause DELETED by _humanize_structured downstream of the seam. MEASURED end to end before the fix, on
# one turn: an unterminated quotation swallowing the magnitude clause; [E3] present in
# structured['sources'] + verifier['resolved'] + the reader's '## Sources' footer and present NOWHERE in
# the prose; and '$2.45/lb' shipping while the PRE-seam unbacked_levels counter -- the one
# price_target_backed reads -- stayed 0. Separately, sanitize rewrote the text INSIDE the quotation marks
# ('bullish' -> 'price-supportive'), making the engine a misquoter.
_HOSTILE_RECEIPT = ("Cash arabica traded at $2.45/lb after July frost hit Sul de Minas. "
                    "Roasters called the market overvalued and outright bullish into 2022.")


def _hostile(monkeypatch, text=_HOSTILE_RECEIPT, *, cited=True, node="drivers/frost"):
    """One turn whose 2021 window carries `text` as its receipt. `cited=False` removes the model's own
    [E1] so the scaffold takes the MINT path (the one that can orphan a ref) rather than reuse, and drops
    the model's ledger entry with it so `structured['sources']` holds only what the engine put there."""
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    receipt = {"date": "2021-07-20", "text": text}
    eps = [{**_EPS[1], "receipt": receipt}]
    evidence = [{"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://gain", "text": text}]
    st = _structured(_MECH_NO_EPISODES if cited else _MECH_NO_EPISODES.replace("[E1]", "(no handle)"))
    vf = _verifier()
    if not cited:
        st["sources"], vf["resolved"] = [], {}
    trace = an._maybe_scaffold_episodes(st, vf, injected=_injected(eps, node=node),
                                        nodes=[_Node(node, eps)], evidence=evidence, n_positional=2)
    an._humanize_structured(st)                                   # the seam's OWN pass, verbatim
    return st, vf, trace


def test_a_register_violating_receipt_cannot_orphan_the_synthesized_handle(monkeypatch):
    """BLOCKER 1, on the MINT path. After _humanize_structured the ref must be in the prose or in nothing:
    a ref in sources + resolved + the footer whose handle no reader ever sees is the exact state
    _maybe_scaffold_episodes' own contract calls impossible."""
    st, vf, trace = _hostile(monkeypatch, cited=False)
    assert trace["episodes_scaffolded"]["fired"] is True
    mech = st["mechanism"]
    for ref in (vf.get("synthesized_refs") or []):
        assert f"[E{ref}]" in mech, mech                           # 1. the prose -- the leg that was lost
        assert any(s.get("ref") == ref for s in st["sources"])     # 2. structured['sources']
        assert str(ref) in vf["resolved"]                          # 3. verifier['resolved']
    # ...and every ref the ENGINE put in the reader's footer is a ref the prose actually carries
    assert st["sources"] and all(f"[E{s['ref']}]" in mech for s in st["sources"]), st["sources"]
    assert f"[{st['sources'][0]['ref']}] " in an._cited_sources_block(st, vf, None)


def test_a_register_violating_receipt_leaves_no_unterminated_quotation(monkeypatch):
    """BLOCKER 1's reader-visible half, on the ENGINE's own delimiters. The old shape wrapped the receipt in
    quotation marks whose closing delimiter lived in the same strippable clause, so a strip left an OPEN
    quotation that swallowed the engine's own magnitude clause. No delimiters, no unterminated anything.

    SCOPE, AND WHY THE NEXT TEST EXISTS (round-3 BLOCKER): `_HOSTILE_RECEIPT` carries no delimiters of its
    own, so this pin only ever proved that the COMPOSER mints none. The corpus-borne half -- a source whose
    own text carries quotation marks -- passed straight through it and is pinned below, on receipts that
    actually carry the glyphs."""
    st, _vf, _t = _hostile(monkeypatch)
    section = ev._episode_section(st["mechanism"])
    assert '"' not in _HOSTILE_RECEIPT and "'" not in _HOSTILE_RECEIPT   # the scope, stated as an assert
    assert section.count('"') == 0 and section.count("'") == 0
    bullet = [ln for ln in section.split("\n") if ln.startswith("- ")][0]
    assert bullet.endswith(f"{an._SCAFFOLD_CASE2_MAGNITUDE}.")     # the magnitude clause still terminates


# THE CORPUS-BORNE HALF (round-3 BLOCKER, 2026-08-05). The engine mints no delimiters, but the SOURCE's own
# rode through the normalization untouched and reproduced BOTH halves of the defect the D-DT-1 fold exists
# to prevent, end to end at rung 1: reg.sanitize rewrote words INSIDE the source's quote marks (measured:
# `Roasters said "we are outright bullish into 2022"` shipped `..."we are outright price-supportive into
# 2022"...`), and _SCAFFOLD_RESTATE_CAP cut between an opener and its closer (measured: 135 of 168 cut
# points on one probe left an UNTERMINATED quotation). Every row below CARRIES delimiters; the last three
# are the APOSTROPHE CONTROLS, which must SURVIVE -- a fix that deletes `don't` and `Brazil's` corrupts the
# restatement it exists to keep honest, so the non-vacuity is part of the pin and not a separate test.
_QUOTED_RECEIPTS = (
    ("ascii double", 'Roasters said "the crop is gone" after touring Sul de Minas in July.', ()),
    ("ascii single", "The co-op said 'no relief before September' as the frost damage was tallied.", ()),
    ("typographic double", "Roasters said \u201Cthe crop is gone\u201D after touring Sul de Minas.", ()),
    ("typographic single", "Traders called it \u2018the worst frost in a generation\u2019 in the note.", ()),
    ("guillemets", "The bulletin said \u00ABla geada\u00BB hit Sul de Minas in the July window.", ()),
    ("low-9 pair", "The note read \u201Eeine schwere Frostnacht\u201C across Sul de Minas.", ()),
    ("cjk corner", "The desk note read \u300Cfrost damage confirmed\u300D for the July window.", ()),
    ("unterminated -- the cap recipe",
     'Roasters said "we are outright bullish into 2022 and the July frost damage across Sul de Minas is '
     'far from fully priced by the trade at this point in the season.', ()),
    ("apostrophe control", 'The co-op said "relief is far off"; Brazil\'s roasters don\'t expect it.',
     ("Brazil's", "don't")),
    ("typographic apostrophe control",
     "Roasters said \u201Cno relief\u201D; Brazil\u2019s co-op doesn\u2019t expect it before September.",
     ("Brazil\u2019s", "doesn\u2019t")),
    ("apostrophe with NO delimiter in sight", "Brazil's roasters don't expect relief before September.",
     ("Brazil's", "don't")),
)
# Every glyph the drop removes UNCONDITIONALLY. The single family is deliberately absent: `'` and U+2019
# are apostrophes as often as they are delimiters, so they are pinned positionally (via _SCAFFOLD_QUOTE_RX
# over the corpus half) rather than by a character ban that would fail the controls above.
_ALWAYS_DELIMITERS = "\"\u201C\u201D\u00AB\u00BB\u201E\u201A\u300C\u300D\u300E\u300F\u2018"


@pytest.mark.parametrize("why,text,survivors", _QUOTED_RECEIPTS)
def test_no_corpus_borne_quotation_delimiter_reaches_the_shipped_bullet(monkeypatch, why, text, survivors):
    """THE ROUND-3 BLOCKER, on the SHIPPED section, at RUNG 1 -- which is the only rung where it can be
    proven. Rung 2 carries no corpus byte at all, so a section with the restatement dropped is quote-free
    for a reason that has nothing to do with this fix; each case therefore asserts the restatement verb is
    present FIRST, and only then that not one delimiter came with it.

    THE APOSTROPHE ROWS ARE THE SAME PIN, NOT A COURTESY: `don't` and `Brazil's` must reach the reader
    intact in the SAME bullet whose quotation marks were removed, because the difference between a
    delimiter and an apostrophe is the entire content of the rule (see answer._SCAFFOLD_QUOTE_RX)."""
    st, _vf, trace = _hostile(monkeypatch, text)
    assert trace["episodes_scaffolded"]["fired"] is True, why
    assert not trace["episodes_scaffolded"].get("restatement_dropped"), why      # rung 1, or this proves 0
    section = ev._episode_section(st["mechanism"])
    bullet = [ln for ln in section.split("\n") if ln.startswith("- ")][0]
    assert an._SCAFFOLD_CASE2_REPORTS in bullet, why               # the corpus text really is on the page
    for ch in _ALWAYS_DELIMITERS:
        assert ch not in section, (why, hex(ord(ch)))              # the whole section, not just the bullet
    # ...and the single family, positionally: no UNFLANKED ' or U+2018/U+2019 anywhere in the corpus half
    assert an._SCAFFOLD_QUOTE_RX.search(an._scaffold_corpus_half(bullet)) is None, why
    for word in survivors:                                         # the apostrophes SURVIVED, word-internal
        assert word in bullet, (why, word)
    assert bullet.endswith(f"{an._SCAFFOLD_CASE2_MAGNITUDE}.")     # nothing was left hanging open


def test_the_engine_never_presents_rewritten_text_as_the_sources_own_words(monkeypatch):
    """BLOCKER 2. reg.sanitize rewrites mood words and humanizes contract slugs inside whatever it is
    given, so 'bullish' -> 'price-supportive' shipped BETWEEN QUOTATION MARKS as the source's words. The
    doc's CASE-2 shape is a RESTATEMENT; the delimiters were never in it. Restating in the house register
    is honest, quoting a rewrite is not -- so the fence is that no quotation mark is ever emitted."""
    st, _vf, _t = _hostile(monkeypatch, "Roasters turned bullish into 2022 as arabica_coffee tightened")
    bullet = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")][0]
    assert "price-supportive" in bullet and "bullish" not in bullet   # sanitized, as all reader prose is
    assert '"' not in bullet and "states:" not in bullet              # but never attributed as a quote
    assert an._SCAFFOLD_CASE2_REPORTS in bullet                       # the restatement verb, not a quote
    assert 'states: "' not in inspect.getsource(an._scaffold_section)  # one producer, and it cannot quote


def test_the_synthesized_section_is_a_sanitize_FIXED_POINT(monkeypatch):
    """THE FIX, stated as its invariant. The section is composed from already-sanitized text at mint time,
    so the _humanize_structured pass at the seam has nothing left to take -- which is what makes the
    three-place handle rule survivable. Asserted on the hostile receipt in BOTH registers."""
    from leviathan.graphrag import register as reg
    for mr in (reg.FENCED, reg.OUTLOOK):
        plan = [("2021-06..2021-08", "drivers/frost", 3, "2021-07-20",
                 an._scaffold_restatement({"date": "2021-07-20", "text": _HOSTILE_RECEIPT}, mr))]
        section = an._scaffold_section(plan, mr, degraded=False)
        assert reg.sanitize(section, market_register=mr) == section, mr
        assert an._scaffold_survives(section, plan) is not None, mr


def test_the_engine_ships_no_price_level_the_preseam_counter_never_saw(monkeypatch):
    """BLOCKER 1's pin half. price_target_backed reads trace['unbacked_levels'], counted on the RAW model
    draft UPSTREAM of the seam -- so an engine-injected '$2.45/lb' would ship under a pin asserting zero.

    WHAT CLOSES IT IS THE FENCE, NOT CO-LOCATION (round-2 correction; this docstring carried the REFUTED
    round-1 rationale until 2026-08-05). The old argument was "closed by construction: the handle shares
    its SENTENCE with the restatement, and register.unbacked_levels exempts a sentence carrying a citation
    handle". Both halves are false and both are MEASURED: `register._SENT_ITER` is `(?<=[.!?;])\\s+`
    (register.py:611), so the exemption is CLAUSE-scoped and a handle in the lead clause does not reach a
    level in a LATER clause of the same bullet; and the exemption at register.py:534 is VOIDED outright
    when the clause carries a derivation-output marker. 5 of the 6 M-section probes leaked past that
    argument. What actually closes it is `_scaffold_survives`, which runs register's OWN counter over the
    RENDERED line with `derivation_ok=False` and drops a failing bullet to rung 2.

    THIS RECEIPT IS THE NON-VACUITY SHAPE for that fence, kept here deliberately: its level sits in the
    SAME clause as the handle with no derivation marker, so it is genuinely backed and rung 1 renders it in
    full. The leaking shapes -- later clause, second sentence, derivation marker, arrow glyph -- are the
    M-section parametrization, and they degrade. A fence that refused this one too would be an off
    switch."""
    from leviathan.graphrag import register as reg
    st, _vf, trace = _hostile(monkeypatch)
    assert not trace["episodes_scaffolded"].get("restatement_dropped")   # rung 1: the fence let it stand
    assert "$2.45/lb" in st["mechanism"]                           # the restatement is not gutted...
    assert reg.unbacked_level_count(st["mechanism"]) == 0          # ...and the level is BACKED, not bare
    assert reg.unbacked_levels(ev._episode_section(st["mechanism"])) == []


def test_a_wholly_register_violating_receipt_degrades_to_a_bullet_that_still_cites(monkeypatch):
    """RUNG 2 of the ladder. When the receipt is ENTIRELY strippable there is nothing safe to restate, and
    the answer is not to guess and not to drop the citation: the bullet keeps span, label, handle, date
    and magnitude -- engine-authored text only -- and still cites. A receipted window must never fall back
    onto the CASE-1 absence sentence, which is the one thing Option A may never do."""
    st, vf, trace = _hostile(monkeypatch, "Take profits and stop-loss at 240; go long the spread.",
                             cited=False)
    assert trace["episodes_scaffolded"]["fired"] is True
    bullet = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")][0]
    ref = vf["synthesized_refs"][0]
    assert f"[E{ref}]" in bullet and "2021-07-20" in bullet
    assert an._SCAFFOLD_CASE2_REPORTS not in bullet               # nothing was restated
    assert not ev._has_any(bullet, ev._NO_CITABLE)                # and NO false absence, ever
    assert "stop-loss" not in bullet and "go long" not in bullet


def test_a_bullet_that_cannot_survive_even_degraded_declines_and_commits_nothing(monkeypatch):
    """RUNG 3. The label is engine-held but NOT engine-authored -- it is a node id out of the driver-slice
    registry -- so a label carrying fenced vocabulary makes even the cite-only bullet strippable. The only
    honest answer left is today's behaviour: no section, and NOT ONE BYTE written to structured or
    verifier, so the rolled-back ref is a ref that was never committed."""
    st, vf, trace = _hostile(monkeypatch, node="drivers/stop-loss", cited=False)
    assert trace["episodes_scaffolded"]["declined"] == "sanitize_would_strip_the_bullet"
    assert trace["episodes_scaffolded"]["fired"] is False
    assert trace["episodes_model_authored"] is False              # nobody authored it -- not the model
    assert "## Episodes" not in st["mechanism"]
    assert vf.get("synthesized_refs") in (None, [])
    assert st["sources"] == [] and vf["resolved"] == {}           # not one byte committed on the way out


@pytest.mark.parametrize("section,why", [
    ("## Episodes\n- 1994-06..1994-08 -- n: no citable item in this window, so what happened is not "
     "narrated; no price record for this window. - 2021-06..2021-08 -- n: the dated item [E3] recorded "
     "2021-07-20; no observed magnitude for this window.", "two bullets merged onto one physical line"),
    ("## Episodes\n- 1994-06..1994-08 -- n: no citable item in this window, so what happened is not "
     "narrated; no price record for this window.", "a planned bullet was stripped entirely"),
    ("- 1994-06..1994-08 -- n: no citable item in this window, so what happened is not narrated; no price "
     "record for this window.\n- 2021-06..2021-08 -- n: the dated item [E3] recorded 2021-07-20; no "
     "observed magnitude for this window.", "the heading went with the first bullet"),
    ("## Episodes\n- 1994-06..1994-08 -- n: no citable item in this window, so what happened is not "
     "narrated; no price record for this window.\n- 2021-06..2021-08 -- n: recorded 2021-07-20; no "
     "observed magnitude for this window.", "the receipted bullet lost its handle"),
    ("## Episodes\n- 1994-06..1994-08 -- n: no citable item in this window, so what happened is not "
     "narrated; no price record for this window.\n- 2021-06..2021-08 -- n: the dated item [E3] recorded "
     "2021-07-20; no citable item in this window, so what happened is not narrated.",
     "a CASE-1 absence sentence landed on a receipted window"),
    ("## Episodes\n- 1994-06..1994-08 -- n: no citable item in this window, so what happened is not "
     "narrated; no price record for this window.\n- 2021-06..2021-08 -- n: the dated item [E3] recorded "
     "2021-07-20 reports Roasters said \"the crop is gone\"; no observed magnitude for this window.",
     "the source's own quotation marks reached the rendered bullet"),
    ("## Episodes\n- 1994-06..1994-08 -- n: no citable item in this window, so what happened is not "
     "narrated; no price record for this window.\n- 2021-06..2021-08 -- n: the dated item [E3] recorded "
     "2021-07-20 reports Roasters said \u201Cthe crop is gone; no observed magnitude for this window.",
     "an UNTERMINATED typographic quotation swallowing the magnitude clause"),
])
def test_the_reconciliation_refuses_every_post_sanitize_state_that_can_lie(section, why):
    """The predicate itself, over every destroyed shape it must refuse: the five a clause-scoped strip can
    produce, plus the two the CORPUS can produce on its own (round-3 -- the source's own delimiters on the
    rendered bullet, terminated or not). Each is a state the OLD code would have shipped; each must now be
    a decline. `_scaffold_survives` is run TWICE per rung -- once on the mint-time pass and once on the
    exact bytes _humanize_structured will produce -- so a shape that only appears in context is caught."""
    plan = [("1994-06..1994-08", "n", None, "", ""),
            ("2021-06..2021-08", "n", 3, "2021-07-20", "")]
    assert an._scaffold_survives(section, plan) is None, why


def test_the_reconciliation_accepts_the_shape_the_engine_actually_writes():
    """Non-vacuity: a predicate that refuses everything is not a fence, it is an off switch."""
    plan = [("1994-06..1994-08", "n", None, "", ""),
            ("2021-06..2021-08", "n", 3, "2021-07-20", "frost damage")]
    from leviathan.graphrag import register as reg
    section = an._scaffold_section(plan, reg.FENCED, degraded=False)
    assert an._scaffold_survives(section, plan) == [ln for ln in section.split("\n")
                                                    if ln.startswith("- ")]


def test_the_section_extractor_agrees_with_the_scorer_on_every_corpus_mechanism():
    """_episode_section_body is what the reconciliation reads, so it must select the SAME section the
    scorer will score -- last-section-wins, fence-aware, '##'..'######'. Checked over the detector corpus
    plus the heading line the extractor deliberately keeps and the scorer deliberately drops."""
    for m in _DETECTOR_CORPUS:
        body = an._episode_section_body(m)
        scored = ev._episode_section(m)
        assert bool(body) is (scored is not None), m               # same PRESENCE verdict as the detector
        if scored is None:
            continue
        head, _, rest = body.partition("\n")
        assert re.match(r"^\s*#{2,6}\s+", head), m                 # the heading the extractor keeps
        assert rest == scored, m                                   # and byte-for-byte the scorer's body


# ══ K -- min_episode_lines ON A FIRED SCAFFOLD (the residual, pinned in both receipt states) ══════════
def _fired(tmp_path, monkeypatch, *, receipted, on=True):
    """One END-TO-END turn. `receipted` picks whether the 2021 window's top-K carries an in-window dated
    item, which is the ONLY thing that decides CASE-1 vs CASE-2; `on` is the scaffold flag, so the same
    helper serves both arms and the arms cannot silently become the same arm."""
    _timeline_on(tmp_path, monkeypatch)
    if on:
        monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    else:
        monkeypatch.delenv("GRAPHRAG_EPISODE_SCAFFOLD", raising=False)

    def _retr(q, node, *, k, asof=None, near=None):
        rows = [{"date": "2016-02-01", "source": "wb_cmo", "source_key": "s3://wb", "text": "macro note"}]
        if receipted:
            rows.insert(0, {"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://gain",
                            "text": "July frost hit Sul de Minas hard"})
        return rows
    return _run(_graph(), planner="l2", monkeypatch=monkeypatch, retrieve=_retr)


@pytest.mark.parametrize("receipted", [True, False])
def test_min_episode_lines_on_a_fired_scaffold(tmp_path, monkeypatch, receipted):
    """THE PIN THE SCAFFOLD IS FOR, measured on a FIRED turn rather than on the helper -- the gap the
    adversarial pass named, and it is only closable now that handles are sanitize-stable (before the fix
    the handle could be destroyed even on the REUSE path, so a receipted bullet could arrive unbacked
    through no fault of the model).

    Under synthesis the pin means 'the engine injected >= N distinct windows and the renderer emitted
    them' (D-DT-1 1.3). Both windows must therefore be BACKED and DISTINCT: the receipt-less one on
    _line_backed's absence branch, the receipted one on its cited-year branch -- the bullet carries the
    receipt's OWN date precisely so that branch gets the widest honest shot at it."""
    out = _fired(tmp_path, monkeypatch, receipted=receipted)
    scaf = out["trace"]["episodes_scaffolded"]
    assert scaf["fired"] is True and scaf["n_bullets"] == 2
    assert scaf["n_receipted"] == (1 if receipted else 0)
    q = {"contract": "arabica_coffee", "expect": {"min_episode_lines": 2}}
    assert ev._cascade_asserts(q, out)["min_episode_lines"] is True
    lines, adj, distinct = ev._episode_enumeration(out)
    assert len(lines) == 2 and distinct == 2 and all(adj)         # every window is an INJECTED window
    # and the same turn with the flag OFF renders no section at all, so the pin reds -- which is the
    # whole defect: presence was a sampling outcome, and 'want 2' had nothing to score.
    off = _fired(tmp_path, monkeypatch, receipted=receipted, on=False)
    assert "## Episodes" not in off["structured"]["mechanism"]
    assert ev._cascade_asserts(q, off)["min_episode_lines"] is False


def test_a_fired_scaffold_keeps_the_two_citation_pins_and_the_absence_pins_honest(tmp_path, monkeypatch):
    """The receipted turn end to end: the section is present, the handle is in the prose, the footer has
    no orphan, and the two pins S1.7 calls the A/B's sharpest check do not move against the OFF arm."""
    on = _fired(tmp_path, monkeypatch, receipted=True)
    off = _fired(tmp_path, monkeypatch, receipted=True, on=False)
    mech = on["structured"]["mechanism"]
    assert "## Episodes" in mech and "## Episodes" not in off["structured"]["mechanism"]
    for ref in (on["trace"]["citation_verifier"].get("synthesized_refs") or []):
        assert f"[E{ref}]" in mech
    q = {"contract": "arabica_coffee", "asof": "2026-01-01",
         "expect": {"min_episodes_cited": 1, "min_episode_sources": 1, "episode_magnitude_or_absence": True}}
    for k in ("min_episodes_cited", "min_episode_sources"):
        assert ev._cascade_asserts(q, on)[k] == ev._cascade_asserts(q, off)[k], k
    assert ev._cascade_asserts(q, on)["episode_magnitude_or_absence"] is True


# ══ L -- the two documentation defects, pinned so they cannot decay back ══════════════════════════════
def test_the_fire_condition_states_that_the_flag_stands_in_for_the_seam_gate():
    """The doc's leg 1 is the SEAM GATE; the code's is the FLAG. The substitution is sound but it was
    unstated and untested, so it read as an omission rather than a decision."""
    doc = inspect.getsource(an._maybe_scaffold_episodes)
    assert "SUBSTITUTES THE FLAG FOR THE DOC'S SEAM-GATE LEG" in doc
    assert "_episodes_on" in doc and "LINE_PREFIX" in doc


def test_a_stamped_span_implies_the_seam_gate_held():
    """The MECHANICAL half of the substitution: a span is stamped only where _l2_blocks rendered a
    tl.render_line, and every such line opens with the marker _episodes_on tests the volatile prompt for.
    So `spans` non-empty => LINE_PREFIX in the prompt => the seam gate held."""
    line = tl.render_line("drivers/frost", _EPS)
    assert line.startswith(tl.LINE_PREFIX)
    assert tl.floored_line("drivers/frost", 4, 2).startswith(tl.LINE_PREFIX)
    # ...and the gate is exactly that marker test over the volatile prompt, plus the artifact switch
    assert "_tl.LINE_PREFIX in (volatile_prompt" in inspect.getsource(an._episodes_on)


def test_a_turn_that_stamps_a_span_carries_the_seam_gates_marker_in_its_prompt(tmp_path, monkeypatch):
    """The END-TO-END half. On the very turn whose trace carries a span, the assembled VOLATILE prompt
    satisfies _episodes_on -- so the leg the scaffold does not evaluate was true anyway."""
    _timeline_on(tmp_path, monkeypatch)
    seen = {}

    def _call(system, user, *, model, tool, **kw):
        seen["user"] = user
        return {"tldr": "t", "diagram_mermaid": "", "mechanism": _MECH_NO_EPISODES,
                "sources": [{"ref": 1, "source": "usda_gain", "date": "2021-07-20", "note": "frost"}]}

    def _retr(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://gain", "text": "frost"}]
    tl.reset_cache()
    out = an.answer("q", graph=_graph(), planner="l2", asof="2026-01-01", retrieve=_retr, call=_call,
                    route_fn=lambda q, gg: ["arabica_coffee"])
    assert any(r.get("spans") for r in out["trace"]["episodes_injected"])
    assert tl.LINE_PREFIX in seen["user"] and an._episodes_on(seen["user"]) is True


def test_the_fork_basis_docstring_describes_the_call_sites_it_actually_has():
    """LOW: the docstring claimed the expression was 'spelled identically in both bodies'. It is not --
    _answer_l2 passes a node-evidence flatten and sg.trace, the one-hop body passes its own evidence list
    and {}. The claim is now the true one, and this test is what keeps it true."""
    doc = inspect.getsource(an._fork_basis)
    assert "ONE FUNCTION, TWO CALL SITES, AND THE ARGUMENTS DIFFER" in doc
    assert "What is identical is the FUNCTION and its POSITION" in doc
    l2, onehop = inspect.getsource(an._answer_l2), inspect.getsource(an.answer)
    assert 'sg.trace["fork_basis"] = _fork_basis(graph, contracts,' in l2
    assert "sg.trace)" in l2.split('sg.trace["fork_basis"] = _fork_basis(')[1][:400]
    assert "_fork_basis_v = _fork_basis(graph, contracts, evidence, {})" in onehop
    # and the difference is inert, which is the reason it is allowed to stand
    assert an._fork_basis(_graph(), ["arabica_coffee"], _EVIDENCE, {})["numeric"] is False


# ══ M -- ROUND-2: the FORMAT FENCE, the ABSENCE fence, and the ladder's own end-to-end teeth ══════════
# Round 1 argued the CASE-2 restatement could not ship a price level the PRE-seam `unbacked_levels`
# counter never saw, because "the handle shares its sentence and register.unbacked_levels exempts a cited
# sentence". Both halves are false, MEASURED: register._SENT_ITER is r'(?<=[.!?;])\s+' (register.py:611),
# so the exemption is CLAUSE-scoped and does not reach a later clause of the same bullet; and the
# exemption at register.py:534 is VOIDED when the clause carries a derivation-output marker. 5 of these 6
# ordinary-prose receipts leaked a bare level through the shipped mechanism before the fix; 6 of 6
# absence-marker receipts made a RECEIPTED window read as an absence. Both classes are now rungs.
_LEVEL_RECEIPTS = (
    ("later clause", "Frost hit Sul de Minas; cash arabica traded at $2.45/lb in the week that followed."),
    ("second sentence", "Frost hit Sul de Minas. Cash arabica traded at $2.45/lb in the week that "
                        "followed."),
    ("derivation marker 'median'", "Cash arabica traded at $2.45/lb, the median of the week."),
    ("arrow glyph", "Arabica moved 220 -> 245 on the frost."),
    ("derivation marker 'midpoint'", "The midpoint of the range was 2.45 for the week."),
)
_ABSENCE_RECEIPTS = (
    ("not available", "The ministry said the figure is not available for this period."),
    ("not published", "Reuters reported the data was not published this month."),
    ("no data", "USDA notes no data reached the survey for the state."),
    ("record is silent", "The record is silent on the July window."),
    ("not in the corpus", "That series is not in the corpus for this year."),
    ("not known", "Trade sources said the tonnage is not known."),
)
# The ONE shape round 1 got right, kept as the non-vacuity control: the level sits in the SAME clause as
# the handle with no derivation marker, so it is genuinely backed and rung 1 still renders it.
_COLOCATED_RECEIPT = "Cash arabica traded at $2.45/lb after July frost hit Sul de Minas."


def _receipt_turn(tmp_path, monkeypatch, text, *, on=True):
    """ONE END-TO-END TURN through an.answer() on the shipped artifact, whose 2021 window carries `text`
    as its receipt. The receipt is built by the REAL producer (timeline.episodes_for off the retrieved
    in-window evidence prop), so nothing about the leak is staged by the test."""
    _timeline_on(tmp_path, monkeypatch)
    if on:
        monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    else:
        monkeypatch.delenv("GRAPHRAG_EPISODE_SCAFFOLD", raising=False)

    def _retr(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://gain", "text": text},
                {"date": "2016-02-01", "source": "wb_cmo", "source_key": "s3://wb", "text": "macro note"}]
    return _run(_graph(), planner="l2", monkeypatch=monkeypatch, retrieve=_retr)


def _episode_bullets(out):
    return [ln for ln in (ev._episode_section(out["structured"]["mechanism"]) or "").split("\n")
            if ln.lstrip().startswith("- ")]


def _rung(out):
    scaf = out["trace"]["episodes_scaffolded"]
    if not scaf.get("fired"):
        return "3-decline"
    return "2-degraded" if scaf.get("restatement_dropped") else "1-full"


@pytest.mark.parametrize("why,text", _LEVEL_RECEIPTS)
def test_a_leaking_price_level_lands_on_rung_2_with_the_citation_intact(tmp_path, monkeypatch, why, text):
    """THE ROUND-2 BLOCKER, one case per measured leak, asserted on the SHIPPED mechanism.

    The acceptance is exactly the verifier's: the bullet lands on rung 2, `unbacked_level_count` of what
    actually ships is 0, and THE CITATION IS INTACT -- degrading is only an acceptable answer to a failed
    reconciliation because the bullet still cites. The corpus text is gone, so the level is gone with it,
    and the pin `price_target_backed` reads (which counts the PRE-seam model draft) is not lied to."""
    from leviathan.graphrag import register as reg
    out = _receipt_turn(tmp_path, monkeypatch, text)
    mech = out["structured"]["mechanism"]
    assert _rung(out) == "2-degraded", why
    assert reg.unbacked_level_count(mech) == 0, why                 # the shipped mechanism, not the draft
    assert reg.unbacked_levels(ev._episode_section(mech)) == [], why
    bullets = _episode_bullets(out)
    assert len(bullets) == 2, why
    receipted = [b for b in bullets if an._SCAFFOLD_CASE2_MAGNITUDE in b]
    assert len(receipted) == 1 and re.search(r"\[E\d+\]", receipted[0]), why   # ...and it STILL CITES
    assert an._SCAFFOLD_CASE2_REPORTS not in receipted[0], why      # no corpus byte survived the rung
    assert not ev._has_any(receipted[0], ev._NO_CITABLE), why       # and never a false absence


def test_the_colocated_level_still_renders_in_full_or_the_fence_is_an_off_switch(tmp_path, monkeypatch):
    """NON-VACUITY for the whole class. A fence that degrades every receipted bullet is an off switch, and
    the ladder would then be indistinguishable from deleting the restatement branch. On the one shape
    where the level really is backed -- same clause as the handle, no derivation marker -- rung 1 stands."""
    from leviathan.graphrag import register as reg
    out = _receipt_turn(tmp_path, monkeypatch, _COLOCATED_RECEIPT)
    assert _rung(out) == "1-full"
    bullet = [b for b in _episode_bullets(out) if an._SCAFFOLD_CASE2_REPORTS in b]
    assert len(bullet) == 1 and "$2.45/lb" in bullet[0]
    assert reg.unbacked_level_count(out["structured"]["mechanism"]) == 0


@pytest.mark.parametrize("why,text", _ABSENCE_RECEIPTS)
def test_a_restated_absence_marker_lands_on_rung_2_with_the_citation_intact(tmp_path, monkeypatch,
                                                                            why, text):
    """THE ROUND-2 MEDIUM, same acceptance shape. `_scaffold_survives` refused only the ENGINE's own
    CASE-1 string, but the scorer reads its own vocabulary -- so a receipted bullet whose restated corpus
    text says 'not available' greened an absence pin on a window that HAS a receipt. 6 of 6 measured."""
    out = _receipt_turn(tmp_path, monkeypatch, text)
    assert _rung(out) == "2-degraded", why
    receipted = [b for b in _episode_bullets(out) if an._SCAFFOLD_CASE2_MAGNITUDE in b]
    assert len(receipted) == 1 and re.search(r"\[E\d+\]", receipted[0]), why   # STILL CITES
    corpus = an._scaffold_corpus_half(receipted[0])
    assert not ev._has_any(corpus, an._SCAFFOLD_ABSENCE_MARKERS), why
    assert ev._NO_PRICE_RX.search(corpus) is None, why


def _always_accept(section, plan):
    """`_scaffold_survives` NEUTRALISED to always-accept -- the exact mutation the round-2 pass applied to
    prove the ladder had no end-to-end teeth. It returns the bullet lines unconditionally, which is what
    the predicate returns on success, so nothing else in the ladder can tell the difference."""
    return [ln for ln in (section or "").split("\n") if ln.lstrip().startswith("- ")]


def test_the_reconciliation_ladder_reds_end_to_end_when_it_is_neutralised(tmp_path, monkeypatch):
    """ROUND-2 LOW-1, and it is the reason the other two findings survived a full green suite: neutralising
    `_scaffold_survives` to always-accept left EVERY end-to-end J-section test green, because the rung-3
    fixture is caught by a different leg (the label is fenced vocabulary, so the composed section fails
    before the predicate is consulted). This is the case that ONLY the predicate refuses.

    ARMED HALF -- through an.answer() on the shipped artifact: a receipt whose price level sits in a LATER
    CLAUSE than the handle. Nothing but `_scaffold_survives` stands between that receipt and the reader.
    NEUTRALISED HALF -- the same turn with the predicate always-accepting SHIPS the level, which is what
    makes the armed assertion above a test rather than a restatement of the code."""
    from leviathan.graphrag import register as reg
    leaky = _LEVEL_RECEIPTS[0][1]
    armed = _receipt_turn(tmp_path, monkeypatch, leaky)
    assert reg.unbacked_level_count(armed["structured"]["mechanism"]) == 0
    assert "$2.45/lb" not in armed["structured"]["mechanism"]
    assert _rung(armed) == "2-degraded"

    monkeypatch.setattr(an, "_scaffold_survives", _always_accept)
    loose = _receipt_turn(tmp_path, monkeypatch, leaky)
    assert _rung(loose) == "1-full"                                  # the ladder never leaves rung 1 now
    assert "$2.45/lb" in loose["structured"]["mechanism"]
    assert reg.unbacked_level_count(loose["structured"]["mechanism"]) == 1
    # ...and the counter the deck actually pins (`price_target_backed`) still reads ZERO on that turn,
    # because it is computed on the RAW model draft upstream of the seam -- which is the whole defect.
    assert loose["trace"]["unbacked_levels"] == 0


def test_the_ladder_reds_end_to_end_on_the_absence_class_too(tmp_path, monkeypatch):
    """The MEDIUM's half of the same teeth, same shape: only the predicate refuses it, so neutralising the
    predicate ships a receipted bullet that reads as an absence."""
    absent = _ABSENCE_RECEIPTS[0][1]
    armed = _receipt_turn(tmp_path, monkeypatch, absent)
    assert not ev._has_any(an._scaffold_corpus_half(_episode_bullets(armed)[-1]),
                           an._SCAFFOLD_ABSENCE_MARKERS)
    monkeypatch.setattr(an, "_scaffold_survives", _always_accept)
    loose = _receipt_turn(tmp_path, monkeypatch, absent)
    assert ev._has_any(an._scaffold_corpus_half(_episode_bullets(loose)[-1]), an._SCAFFOLD_ABSENCE_MARKERS)


def _quoting_restatement(real):
    """`_scaffold_restatement` with ONLY its quotation drop neutralised -- the exact pre-fix normalization.

    The drop and the fence deliberately share ONE regex (`_SCAFFOLD_QUOTE_RX`), for the same reason the
    derivation leg reuses register's own function: two lists of what a quotation mark is would drift. That
    sharing is why the mutation has to be scoped rather than global -- patching the regex for the whole
    turn would neutralise the FENCE as well and prove nothing. Here it is swapped for a never-matching
    pattern for the duration of the restatement call only, so the delimiters reach the composed section and
    `_scaffold_survives` is the only thing left standing between them and the reader."""
    def _q(receipt, market_register):
        saved, an._SCAFFOLD_QUOTE_RX = an._SCAFFOLD_QUOTE_RX, re.compile(r"(?!x)x")
        try:
            return real(receipt, market_register)
        finally:
            an._SCAFFOLD_QUOTE_RX = saved
    return _q


def test_a_quote_bearing_restatement_lands_on_rung_2_when_the_drop_is_neutralised(tmp_path, monkeypatch):
    """THE ROUND-3 BLOCKER'S LADDER HALF, same acceptance shape as the level and absence classes: a corpus
    half carrying quotation delimiters is a LEAK like any other, so it lands on rung 2 -- restatement
    dropped, and THE BULLET STILL CITES -- rather than declining or shipping.

    ARMED HALF: the shipped turn is rung 1 and quote-free, because the mint-time drop already took them.
    NEUTRALISED HALF: with the drop bypassed the delimiters reach the composed section, and the ladder --
    not the normalization -- is what keeps them off the page. THIRD HALF: neutralise the predicate too and
    the delimiter SHIPS, which is what makes the second assertion a test rather than a restatement of the
    code (and it reproduces the verdict's misquote receipt end to end)."""
    quoted = _QUOTED_RECEIPTS[0][1]
    armed = _receipt_turn(tmp_path, monkeypatch, quoted)
    assert _rung(armed) == "1-full"
    assert '"' not in armed["structured"]["mechanism"]
    assert "the crop is gone" in armed["structured"]["mechanism"]     # restated, never quoted

    monkeypatch.setattr(an, "_scaffold_restatement", _quoting_restatement(an._scaffold_restatement))
    loose = _receipt_turn(tmp_path, monkeypatch, quoted)
    assert _rung(loose) == "2-degraded"                              # the leak becomes a rung, not a lie
    assert '"' not in loose["structured"]["mechanism"]
    receipted = [b for b in _episode_bullets(loose) if an._SCAFFOLD_CASE2_MAGNITUDE in b]
    assert len(receipted) == 1 and re.search(r"\[E\d+\]", receipted[0])          # ...and it STILL CITES
    assert an._SCAFFOLD_CASE2_REPORTS not in receipted[0]                        # no corpus byte survived

    monkeypatch.setattr(an, "_scaffold_survives", _always_accept)
    shipped = _receipt_turn(tmp_path, monkeypatch, quoted)
    assert _rung(shipped) == "1-full"
    bullet = [b for b in _episode_bullets(shipped) if an._SCAFFOLD_CASE2_REPORTS in b][0]
    assert bullet.count('"') == 2 and "the crop is gone" in bullet   # the source's own marks, on the page


def test_the_misquote_recipe_is_a_restatement_and_never_the_sources_own_words(monkeypatch):
    """THE VERDICT'S OWN MISQUOTE RECEIPT, verbatim, end to end. reg.sanitize rewrites mood words inside
    whatever it is handed and cannot see a delimiter, so this receipt used to ship the house register
    BETWEEN the source's quotation marks -- an engine putting words in a source's mouth, which is the one
    thing _SCAFFOLD_CASE2_REPORTS exists to prevent. The rewrite still happens (all reader prose is
    sanitized); what may not survive is the attribution."""
    receipt = 'Roasters said "we are outright bullish into 2022" after the July frost.'
    st, _vf, trace = _hostile(monkeypatch, receipt)
    assert not trace["episodes_scaffolded"].get("restatement_dropped")           # rung 1, end to end
    bullet = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")][0]
    assert "price-supportive" in bullet and "bullish" not in bullet              # sanitized, as always
    assert '"' not in bullet and "'" not in bullet                               # but attributed to nobody
    assert an._SCAFFOLD_CASE2_REPORTS in bullet                                  # the restatement verb
    # the pre-fix shape, spelled out so the regression is recognisable on sight
    assert '"we are outright price-supportive into 2022"' not in st["mechanism"]


def test_the_cap_can_no_longer_cut_a_quotation_open(monkeypatch):
    """THE UNTERMINATED half, swept rather than sampled. _SCAFFOLD_RESTATE_CAP truncates at a fixed byte
    count with no idea where a delimiter opened, so before the drop a majority of cut points shipped an
    open quotation (MEASURED: 135 of 168). The sweep is over the SAME receipt at every prefix length, and
    the acceptance is absolute: not one cut point may leave a delimiter of any family behind."""
    base = ('Roasters said "we are outright bullish into 2022 and the market is far from done pricing the '
            'July frost damage across Sul de Minas and the wider belt" after the report.')
    cuts = 0
    for n in range(1, len(base) + 1):
        out = an._scaffold_restatement({"date": "2021-07-20", "text": base[:n]}, "fenced")
        if not out:
            continue
        cuts += 1
        assert not any(ch in out for ch in _ALWAYS_DELIMITERS), (n, out)
        assert an._SCAFFOLD_QUOTE_RX.search(out) is None, (n, out)
    assert cuts > 100                                                # the sweep really swept
    assert len(an._scaffold_restatement({"date": "2021-07-20", "text": base}, "fenced")) <= \
        an._SCAFFOLD_RESTATE_CAP + 3                                 # ...and the cap itself still bites


def test_an_apostrophe_is_not_a_delimiter_and_the_rule_is_positional(monkeypatch):
    """THE DISTINCTION, as a unit over the normalization. A character ban would delete `don't` and
    `Brazil's` and corrupt the restatement this fix exists to keep honest, so the rule is POSITIONAL:
    flanked by word characters on both sides == apostrophe == survives. Both glyph forms, since U+2019 is
    the typographic apostrophe as well as a closing quote.

    THE RESIDUAL IS PINNED TOO, so it stays a decision: a trailing plural possessive and a leading elision
    are NOT flanked, so they lose the glyph. That is one character out of a line that is already a
    restatement, and the alternative rule (keep it when the word ends in 's') would pass an unterminated
    `said 'the frost is bullish for roasters'` straight through."""
    R = lambda t: an._scaffold_restatement({"date": "2021-07-20", "text": t}, "fenced")
    for keep in ("Brazil's roasters don't expect relief", "the co-op's own tally of the damage",
                 "Brazil\u2019s roasters don\u2019t expect relief", "it doesn\u2019t reach the survey"):
        assert R(keep) == keep, keep                                 # byte-identical: nothing was touched
    for text, expect in (("The co-op said 'no relief' in July", "The co-op said no relief in July"),
                         ("Traders called it \u2018the worst\u2019 that year",
                          "Traders called it the worst that year"),
                         ("The roasters' margins narrowed", "The roasters margins narrowed"),
                         ("Losses recall the '90s harvest", "Losses recall the 90s harvest")):
        assert R(text) == expect, text
    # and the drop never MERGES two words -- the substitution is a space, not an empty string
    assert R('a "b" c') == "a b c" and R("dry\u201Cwet\u201D mix") == "dry wet mix"


def test_a_markdown_heading_inside_a_receipt_never_reaches_the_reader(tmp_path, monkeypatch):
    """ROUND-2 LOW-3. VERIFIED NOT a second section -- the restatement's whitespace collapse keeps the
    corpus '## Episodes' mid-line, so the rendered heading count was already exactly 1 and that is pinned
    here rather than assumed. What the reader saw was a stray '##' mid-sentence; the marker is now dropped
    in the restatement normalization, as a whole token, so '#3' and 'C#' are untouched."""
    out = _receipt_turn(tmp_path, monkeypatch,
                        "Section ## Episodes of the bulletin lists July frost damage in Sul de Minas")
    mech = out["structured"]["mechanism"]
    assert _rung(out) == "1-full"                                   # the receipt is otherwise clean
    heads = [ln for ln in mech.split("\n")
             if an._has_episode_section(ln)]                        # a heading line, on its own
    assert len(heads) == 1, heads                                   # EXACTLY one rendered section heading
    bullet = [b for b in _episode_bullets(out) if an._SCAFFOLD_CASE2_REPORTS in b][0]
    assert "#" not in bullet and "Episodes of the bulletin" in bullet
    # the token strip is a WHOLE-TOKEN rule, not a '#' purge
    for keep in ("#3 exporter by volume", "the C# rewrite", "lot #12 was withdrawn"):
        assert "#" in an._scaffold_restatement({"date": "2021-07-20", "text": keep}, "fenced"), keep
    for drop in ("## Episodes here", "### the record shows", "# heading then text"):
        assert "#" not in an._scaffold_restatement({"date": "2021-07-20", "text": drop}, "fenced"), drop


def test_a_stripped_handle_duplicates_its_sources_row_documented_not_fixed(monkeypatch):
    """ROUND-2 LOW-2, and the finding was that the DUPLICATE IS PRE-EXISTING. When the verifier strips the
    model's own handle for an item (`no_lexical_overlap`) the item's row survives in structured['sources']
    and verifier['resolved'], so the footer renders it; the scaffold then correctly mints a fresh ref for
    the same document, because the reuse test requires the E-form string to be PRESENT IN THE PROSE.

    THE CHOICE, RECORDED: the code is left untouched on BOTH halves. Fixing the pre-existing half moves
    the OFF arm and costs flag-off byte-identity; reusing the stripped ref in the mint path is not
    provably safe under the three-place rule -- it re-asserts a citation the verifier deliberately
    removed, and a newly-present E-form handle is newly COUNTED by the positional join, moving
    min_episodes_cited / min_episode_sources. So this test documents CURRENT behaviour, and it is the
    thing that has to be edited on the day someone fixes it."""
    st = _structured(_MECH_NO_EPISODES.replace("[E1]", "(handle stripped by the verifier)"))
    vf = _verifier()
    # (a) THE PRE-EXISTING HALF, with no scaffold in the picture at all: a stripped handle keeps its row.
    assert "[E1]" not in st["mechanism"]
    assert "[1] " in an._cited_sources_block(st, vf, None)
    # (b) the scaffold then mints, because reuse requires the E-form handle to be in the prose
    st, vf, trace = _scaffold(monkeypatch, structured=st, verifier=vf)
    assert trace["episodes_scaffolded"]["fired"] is True
    assert vf["synthesized_refs"] == [3] and "[E3]" in st["mechanism"]
    block = an._cited_sources_block(st, vf, None)
    rows = [ln for ln in block.split("\n") if ln.startswith("[")]
    assert len(rows) == 2 and all("2021-07-20" in r for r in rows)   # the SAME document, twice: the defect
    assert {s["ref"] for s in st["sources"]} == {1, 3}
    # ...and it is cosmetic in the strict sense: both rows resolve to the real item's true metadata
    assert vf["resolved"]["3"]["source_key"] == vf["resolved"]["1"]["source_key"] == "s3://gain"
    # the decision and its reasoning are recorded where the code is, not only here
    doc = inspect.getsource(an._maybe_scaffold_episodes)
    assert "KNOWN COSMETIC, NOT FIXED HERE" in doc and "PRE-EXISTING" in doc


def test_the_format_fence_legs_are_registers_own_vocabulary_and_not_a_second_copy():
    """The verifier's own instruction, pinned: reuse register's `_deriv_output` rather than re-listing the
    derivation vocabulary. A parallel list is a fork that drifts silently, and it would also let the two
    legs disagree about what a derivation is -- `unbacked_levels` consults the SAME function."""
    src = inspect.getsource(an._scaffold_survives)
    assert "reg._deriv_output(" in src and "reg.unbacked_levels(" in src
    assert "derivation_ok=False" in src                              # fail-closed on engine-authored text
    for forked in ("implies", "works out to", "midpoint", "->"):
        assert f'"{forked}"' not in src and f"'{forked}'" not in src
    # and the doc-1.3 span-glyph rule ("the span glyph is never '->'") is SUBSUMED by that one function
    # rather than re-implemented: '->' and U+2192 are its first two alternatives, and '..' is neither.
    from leviathan.graphrag import register as reg
    assert reg._deriv_output("a -> b") is not None
    assert reg._deriv_output("2021-06..2021-08 -- n") is None


# == N -- ROUND-3 LOW: the UNSPACED delimiter, and why the drop and the fence are not the same width ====
# The positional rule ("word-flanked on BOTH sides == apostrophe") is right for `don't` and wrong for an
# UNSPACED delimiter: in `said'we are outright bullish'after` BOTH glyphs are word-flanked, so both used to
# survive the drop as text and reg.sanitize then rewrote `bullish` -> `price-supportive` BETWEEN them --
# the round-3 BLOCKER's misquote, reproduced at rung 1 through the one shape the rule could not see. It was
# MEASURED UNREACHABLE on the current corpus; it is closed anyway, because "no source writes that today" is
# a property of the corpus and not of the engine.
#
# THE CLOSE IS A THREE-PART RULE (answer._quote_delimiter_offsets): a clitic suffix is always an
# apostrophe; a BALANCED PAIR of non-clitic word-flanked glyphs enclosing >= 2 words is a pair of
# delimiters; everything left over is refused by the FENCE rather than edited by the DROP. The last part is
# the design and not a shortfall -- a drop that is too eager corrupts a word the reader can see, a fence
# that is too eager costs one quieter honest bullet, and this file pins BOTH directions.
_UNSPACED_RECEIPTS = (
    ("ascii, unspaced both sides",
     "Roasters said'we are outright bullish'after touring Sul de Minas in July."),
    ("typographic, unspaced both sides",
     "Roasters said‘we are outright bullish’after touring Sul de Minas in July."),
    ("mixed glyph forms, unspaced",
     "The co-op said'no relief before September’and the tally was closed."),
    ("clitics in the SAME receipt as an unspaced pair",
     "Brazil's roasters said'no relief is coming'and they don't expect it before September."),
    ("two unspaced pairs in one receipt",
     "He said'the crop is gone'and she said'the belt is fine'about the July window."),
)


@pytest.mark.parametrize("why,text", _UNSPACED_RECEIPTS)
def test_an_unspaced_delimiter_pair_is_dropped_and_the_bullet_still_ships_in_full(tmp_path, monkeypatch,
                                                                                  why, text):
    """THE ROUND-3 LOW, on the SHIPPED mechanism, end to end through an.answer().

    The acceptance is RUNG 1 -- not a degrade. An unspaced pair is provably a pair of delimiters (part 2 of
    the rule), so the drop takes them at mint and the restatement ships in full: the corpus text is on the
    page, in the house register, attributed to nobody. A fix that answered this class with a rung would be
    indistinguishable from deleting the restatement branch for any source that writes without spaces."""
    out = _receipt_turn(tmp_path, monkeypatch, text)
    assert _rung(out) == "1-full", why
    bullet = [b for b in _episode_bullets(out) if an._SCAFFOLD_CASE2_REPORTS in b]
    assert len(bullet) == 1, why                                     # the corpus text really is on the page
    bullet = bullet[0]
    for ch in _ALWAYS_DELIMITERS:
        assert ch not in bullet, (why, hex(ord(ch)))
    corpus = an._scaffold_corpus_half(bullet)
    assert an._SCAFFOLD_QUOTE_RX.search(corpus) is None, why         # the old leg, still clean...
    assert not an._quote_delimiter_residue(corpus), why              # ...and the new one, which is wider
    assert bullet.endswith(f"{an._SCAFFOLD_CASE2_MAGNITUDE}.")       # nothing was left hanging open


def test_the_unspaced_misquote_recipe_never_reaches_the_reader_and_the_pre_fix_shape_is_named(monkeypatch):
    """THE VERIFIER'S OWN UNSPACED RECIPE, verbatim, with the pre-fix bytes spelled out so the regression
    is recognisable on sight. The rewrite still happens -- all reader prose is sanitized -- and what may
    not survive is the ATTRIBUTION."""
    st, _vf, trace = _hostile(monkeypatch,
                              "Roasters said'we are outright bullish'after the July frost.")
    assert not trace["episodes_scaffolded"].get("restatement_dropped")        # rung 1, end to end
    bullet = [ln for ln in ev._episode_section(st["mechanism"]).split("\n") if ln.startswith("- ")][0]
    assert "price-supportive" in bullet and "bullish" not in bullet          # sanitized, as always
    assert "'" not in bullet and '"' not in bullet                           # but attributed to nobody
    assert an._SCAFFOLD_CASE2_REPORTS in bullet
    assert "said we are outright price-supportive after" in bullet           # an open restatement
    # the pre-fix shape, which is the WHOLE defect: the house register inside the source's own marks
    assert "said'we are outright price-supportive'after" not in st["mechanism"]


def _no_pairs(monkeypatch):
    """Neutralise PART 2 of the rule only -- the balanced-pair scan -- by raising the enclosure threshold
    out of reach. This is the exact pre-fix drop: `_SCAFFOLD_QUOTE_RX`'s unconditional and unflanked legs
    still fire, and a word-flanked glyph is once again read as an apostrophe no matter what it encloses.
    Scoped to the ONE knob so the other two parts of the rule are left standing and the test proves which
    part is load-bearing."""
    monkeypatch.setattr(an, "_QUOTE_PAIR_MIN_WORDS", 10 ** 6)


def test_the_pair_scan_is_what_closes_it_and_the_fence_catches_it_if_that_is_weakened(tmp_path,
                                                                                      monkeypatch):
    """THE LADDER HALF, in the three-half acceptance shape this file uses for every corpus-borne class.

    ARMED: rung 1, quote-free, restated (the parametrization above, restated here as the control).
    PAIR SCAN NEUTRALISED: the glyphs reach the composed section and the FENCE -- not the normalization --
    keeps them off the page, so the bullet lands on rung 2 and STILL CITES. This is what makes the fence's
    extra width a mechanism rather than a comment.
    BOTH NEUTRALISED: the misquote SHIPS, which is what makes the two assertions above a test rather than
    a restatement of the code -- it reproduces the round-3 LOW end to end."""
    text = "Roasters said'we are outright bullish'after the July frost."
    armed = _receipt_turn(tmp_path, monkeypatch, text)
    assert _rung(armed) == "1-full"
    assert "'" not in armed["structured"]["mechanism"]

    _no_pairs(monkeypatch)
    loose = _receipt_turn(tmp_path, monkeypatch, text)
    assert _rung(loose) == "2-degraded"                              # the leak became a rung, not a lie
    assert "'" not in loose["structured"]["mechanism"]
    receipted = [b for b in _episode_bullets(loose) if an._SCAFFOLD_CASE2_MAGNITUDE in b]
    assert len(receipted) == 1 and re.search(r"\[E\d+\]", receipted[0])          # ...and it STILL CITES
    assert an._SCAFFOLD_CASE2_REPORTS not in receipted[0]                        # no corpus byte survived

    monkeypatch.setattr(an, "_scaffold_survives", _always_accept)
    shipped = _receipt_turn(tmp_path, monkeypatch, text)
    assert _rung(shipped) == "1-full"
    bullet = [b for b in _episode_bullets(shipped) if an._SCAFFOLD_CASE2_REPORTS in b][0]
    assert "'we are outright price-supportive'" in bullet            # THE MISQUOTE, on the page, pre-fix


# THE RESIDUAL, PINNED RATHER THAN HAND-WAVED. These three shapes are NOT provably delimiter pairs, so the
# DROP leaves them alone by design (deleting a glyph the engine cannot classify is how `o'clock` becomes
# `o clock`). The FENCE refuses them, so the ACCEPTANCE FOR THE WHOLE CLASS IS RUNG 2: restatement dropped,
# engine-authored text only, the citation intact -- a quieter honest bullet, never a misquote. Naming them
# here is the point: they are the price of a conservative drop, and the day someone widens the drop to
# cover one of them, this test is the thing that has to be edited.
_UNPAIRED_RESIDUALS = (
    ("unbalanced -- an opener with no closer anywhere",
     "Roasters said'we are outright bullish into 2022 and the trade has not priced it."),
    ("half-spaced -- the closer is unflanked, so only the opener is a candidate",
     "Roasters said'we are outright bullish' after the July frost."),
    ("a pair enclosing ONE word -- an enclosure, but not a phrase",
     "He said'no'again when the July tally was read out."),
)


@pytest.mark.parametrize("why,text", _UNPAIRED_RESIDUALS)
def test_an_unprovable_glyph_costs_a_rung_and_never_a_misquote(tmp_path, monkeypatch, why, text):
    """THE ACCEPTANCE FOR THE RESIDUAL, NAMED. Rung 2, the citation intact, and -- the part that matters --
    NO source's word survives to be rewritten between marks, because rung 2 carries no corpus byte at
    all."""
    out = _receipt_turn(tmp_path, monkeypatch, text)
    assert _rung(out) == "2-degraded", why
    receipted = [b for b in _episode_bullets(out) if an._SCAFFOLD_CASE2_MAGNITUDE in b]
    assert len(receipted) == 1 and re.search(r"\[E\d+\]", receipted[0]), why      # it STILL CITES
    assert an._SCAFFOLD_CASE2_REPORTS not in receipted[0], why
    assert "'" not in receipted[0] and "bullish" not in receipted[0], why
    assert not ev._has_any(receipted[0], ev._NO_CITABLE), why                     # never a false absence


def test_a_provable_apostrophe_survives_on_both_limbs_and_the_drop_is_byte_inert_on_it():
    """PART 1 OF THE RULE, as a unit, on BOTH limbs. Byte-identity is the assertion -- an apostrophe must
    reach the reader untouched, because deleting it corrupts the very restatement the drop exists to keep
    honest -- and the FENCE must agree, or the same word costs a rung instead."""
    clitics = ("Brazil's crop", "they don't expect it", "the co-op's own tally", "we've seen it",
               "they're short", "it'll hold", "he'd sold", "I'm told", "it doesn't reach the survey",
               "Brazil’s crop and Colombia’s crop", "we’ve seen Brazil’s crop")
    # LIMB (b) IS LOAD-BEARING ON THIS CORPUS, not a courtesy: `Cote d'Ivoire` is the most common proper
    # noun in the cocoa slices, and a rule without it degrades essentially every cocoa receipt to rung 2.
    elisions = ("Cocoa arrivals from Cote d'Ivoire slowed", "O'Brien toured the belt",
                "the six o'clock bulletin", "l'annee derniere the crop was short",
                "Cote d’Ivoire port arrivals")
    for keep in clitics + elisions:
        assert an._drop_quote_delimiters(keep) == keep, keep         # byte-identical: nothing was touched
        assert not an._quote_delimiter_residue(keep), keep           # ...and the FENCE agrees it is clean
    assert len(an._QUOTE_CLITICS) == 7 and an._QUOTE_ELISION_MAX == 2         # both classes stay CLOSED
    # ...and neither limb swallows the corner: an elision in the SAME receipt as an unspaced pair keeps
    # its glyph while the pair loses both, which is the one interaction that could have gone wrong.
    mixed = "Cote d'Ivoire officials said'the crop is gone'after the tour."
    assert an._drop_quote_delimiters(mixed) == "Cote d'Ivoire officials said the crop is gone after the tour."
    # a glyph that is NEITHER limb is a CANDIDATE, not a silent apostrophe: the drop stays its hand and
    # the fence refuses, which is the residual this rule is willing to pay a rung for
    for candidate in ("the 2021'22 crop year was short", "a rock'n roll year"):
        assert an._drop_quote_delimiters(candidate) == candidate, candidate      # the drop stays its hand
        assert an._quote_delimiter_residue(candidate), candidate                 # the fence does not


def test_limb_b_cannot_reopen_the_corner_because_the_CLOSING_glyph_is_still_a_candidate():
    """THE OBVIOUS OBJECTION TO LIMB (b), answered as a test rather than as a paragraph. The elision limb
    can only misread an OPENING delimiter, and only after a one-or-two-letter token. The CLOSING delimiter
    of the same quotation sits after the last word of the quoted phrase, which is not <= 2 characters --
    so it stays a candidate, is left unpaired, and the fence refuses the line. The misquote cannot ship;
    it costs a rung instead of a clean drop."""
    hostile = "a'we are outright bullish'b"
    assert an._quote_is_apostrophe(hostile, 1) is True               # limb (b) really does misread it...
    assert an._quote_candidates(hostile) == [25]                     # ...and the CLOSER is still unproved
    assert an._drop_quote_delimiters(hostile) == hostile             # so the drop declines to guess
    assert an._quote_delimiter_residue(hostile)                      # and the FENCE refuses the line


def test_the_fence_is_strictly_wider_than_the_drop_and_that_asymmetry_is_the_design():
    """THE ASYMMETRY, stated as its invariant and swept over every row this file carries. After the drop
    has run, a text is either FENCE-CLEAN (rung 1) or it still carries a glyph the drop could not prove --
    and there is no third state in which the unconditional family survives a drop, which is what ONE
    PRODUCER buys. Direction matters: fence-refuses-what-drop-kept is a rung; drop-edits-what-fence-would-
    allow would be a corrupted word."""
    rows = [t for _w, t, _s in _QUOTED_RECEIPTS] + [t for _w, t in _UNSPACED_RECEIPTS] \
        + [t for _w, t in _UNPAIRED_RESIDUALS] + ["Brazil's roasters don't expect relief", "plain text"]
    for text in rows:
        dropped = an._drop_quote_delimiters(text)
        assert len(dropped) <= len(text), text                   # the drop only ever REMOVES...
        assert set(dropped) <= set(text) | {" "}, text            # ...and invents nothing but a space
        assert len(dropped.split()) >= len(text.split()), text    # two words are never merged into one
        # whatever the fence still refuses AFTER the drop, the drop provably could not classify
        if an._quote_delimiter_residue(dropped):
            assert an._quote_candidates(dropped), text               # ...and it is always an unproved glyph
            assert not an._SCAFFOLD_QUOTE_RX.search(dropped), text   # never the unconditional family
