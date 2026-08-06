"""D-RC-11: the episode RELEVANCE gate + scaffold noise caps + the (node, span) de-dup.

The gate (GRAPHRAG_EPISODE_RELEVANCE, default OFF) suppresses the '## Episodes' surface -- BOTH the
persona mandate and the render-side synthesis, one bool, two consumers -- on questions whose shape is
not episodic. Fail-OPEN everywhere: flag off -> True; non-Latin query -> True (the cue list is
English; illiteracy is not a relevance judgment); a model-authored section is NEVER touched.

Calibration is pinned against two fixed corpora: every playbook deck row must fire TRUE (those rows
pin min_episode_lines/min_episodes_cited -- a miss reds a ratified deck), and the 2026-08-05
desk-probe's non-episodic questions must fire FALSE (the five uninvited 23-35-bullet sections the
gate exists to suppress).
"""
from __future__ import annotations

import pathlib

import pytest

from leviathan.graphrag import answer as an
from leviathan.graphrag import intent as it
from leviathan.graphrag import timeline as tl

_CFG = pathlib.Path(an.__file__).parents[3] / "configs" / "graphrag"


# ══ the cue matcher, calibrated against the two corpora ══════════════════════════════════════════════
def _deck_questions():
    import yaml
    out = []
    for name in ("eval_queries_playbooks_v1.yaml", "eval_queries_playbooks_r6residual.yaml"):
        p = _CFG / name
        if not p.exists():
            continue
        for q in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("queries") or []:
            out.append((q["id"], q["question"]))
    return out


def test_every_playbook_row_fires_true():
    """A gate that misses one playbook row reds a ratified deck's episode pins. All 20 rows."""
    rows = _deck_questions()
    if not rows:
        pytest.skip("playbook decks are gitignored and absent from this clone")
    misses = [(i, q) for i, q in rows if not it.is_episodic_explicit(q)]
    assert not misses, f"episodic cues MISSED playbook rows: {misses}"


_PROBE_NON_EPISODIC = [
    "Who are the 3 largest canola producers and exporters?",
    "How is the S&D and exports looking in Malaysia right now?",
    "How was the weather in cocoa regions in the past 3 weeks? Is it indicating a loss in "
    "production for the coming months or crop year?",
    "The 2015-16 super El Nino reduced Ghanaian cocoa yields sharply, cut Thai sugarcane "
    "production, disrupted Brazilian sugar harvest logistics, and reduced Vietnamese coffee "
    "output. Is this documented, or can we only infer it?",
    "I'm focused on winter wheat. What should I look out for in the next 3 months, and what do "
    "you think the trajectory is, long or short?",
    "What would happen to wheat companies in the US?",
    "Compare cocoa and palm.",
    "Does barley affect any commodity?",
    "What is Australia's ranking in terms of wheat exporting, and what would happen to make it rank lower?",
    "No two El Ninos are the same. How does the SCALE of an El Nino change what happens to sugar and palm oil?",
    "What if Iran restricted the Strait of Hormuz? How would that play out for agricultural commodities?",
]


@pytest.mark.parametrize("q", _PROBE_NON_EPISODIC)
def test_probe_non_episodic_fires_false(q):
    assert not it.is_episodic_explicit(q)


def test_probe_episodic_fires_true():
    """The one probe question that IS an enumeration ask must keep its section."""
    assert it.is_episodic_explicit(
        "When has China done import restrictions, and what commodities were affected each time?")


# ══ _episodes_relevant: FLAGLESS (D-AM stage 3) -> non-Latin True, else the cue match ═══════════════
def test_relevance_kill_switch_is_retired(monkeypatch):
    """D-AM stage 3: the interim GRAPHRAG_EPISODE_RELEVANCE flag is RETIRED -- the env var must be
    inert in BOTH states. Contracts subsume the gate per turn when active; this lexical check is the
    sole authority on the unshaped lane, unconditionally."""
    for state in ("on", None):
        if state:
            monkeypatch.setenv("GRAPHRAG_EPISODE_RELEVANCE", state)
        else:
            monkeypatch.delenv("GRAPHRAG_EPISODE_RELEVANCE", raising=False)
        assert an._episodes_relevant("Who are the 3 largest canola producers and exporters?") is False
        assert an._episodes_relevant("Walk me through the episodes one by one.") is True
    assert not hasattr(an, "_episode_relevance_on")           # the seam itself is gone, not vestigial


def test_relevant_gates_by_shape():
    assert an._episodes_relevant("Walk me through the episodes one by one.") is True
    assert an._episodes_relevant("Who are the 3 largest canola producers and exporters?") is False
    assert an._episodes_relevant("") is False                 # an empty query asks for no enumeration


def test_relevant_non_latin_fails_open(monkeypatch):
    assert an._episodes_relevant("ما الذي يحدث "
                                 "عادة لأسعار "
                                 "القمح؟") is True


# ══ scaffold integration: the relevance decline + model-authored preservation + caps + de-dup ════════
class _Node:
    def __init__(self, nid, episodes):
        self.id = nid
        self.episodes = episodes


_RECEIPT = {"date": "2021-07-20", "text": "July frost hit Sul de Minas hard"}
_EVIDENCE = [{"date": "2021-07-20", "source": "usda_gain", "source_key": "s3://gain",
              "text": "July frost hit Sul de Minas hard, damaging the 2022 crop"}]
_MECH = ("## Mechanism\nFrost tightens the balance sheet.\n"
         "## The record\nThe corpus documents frost damage [E1].\n"
         "## What to watch\nFurther cold fronts.\n")
_MECH_WITH_EPISODES = _MECH.replace("## What to watch", "## Episodes\n- 2021: frost [E1]\n## What to watch")


def _eps(n, receipted=()):
    return [{"start": f"{2000 + i}-06-01", "end": f"{2000 + i}-08-01", "n": 3,
             "receipt": (dict(_RECEIPT) if i in receipted else None)} for i in range(n)]


def _injected(eps, node="drivers/frost"):
    return [{"node": node, "line": tl.render_line(node, eps),
             "spans": [tl.month_span(e) for e in eps],
             "windows": [{"start": tl.day_window(e)[0], "end": tl.day_window(e)[1],
                          "span": tl.month_span(e), "n": e.get("n")} for e in eps]}]


def _structured(mech=_MECH):
    return {"tldr": "Frost risk is the live question.", "mechanism": mech,
            "sources": [{"ref": 1, "source": "usda_gain", "date": "2021-07-20", "note": "frost"}]}


def _verifier():
    return {"enabled": True, "checked": 1, "stripped": 0, "corrected": 0, "claim_count": 3, "by_rule": {},
            "resolved": {"1": {"source": "usda_gain", "date": "2021-07-20", "source_key": "s3://gain",
                               "snippet": "July frost hit Sul de Minas hard"}}}


def _run(monkeypatch, *, eps, relevant=True, relevance_flag=False, mech=_MECH, injected=None, nodes=None):
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    if relevance_flag:
        monkeypatch.setenv("GRAPHRAG_EPISODE_RELEVANCE", "on")
    else:
        monkeypatch.delenv("GRAPHRAG_EPISODE_RELEVANCE", raising=False)
    st, vf = _structured(mech), _verifier()
    trace = an._maybe_scaffold_episodes(
        st, vf, injected=_injected(eps) if injected is None else injected,
        nodes=[_Node("drivers/frost", eps)] if nodes is None else nodes,
        evidence=_EVIDENCE, n_positional=2, relevant=relevant)
    return st, vf, trace


def test_not_episodic_declines_with_its_own_reason(monkeypatch):
    st, vf, trace = _run(monkeypatch, eps=_eps(3, receipted=(0,)), relevant=False)
    assert "## Episodes" not in st["mechanism"]
    assert trace["episodes_scaffolded"]["declined"] == "not_episodic"
    assert trace["episodes_model_authored"] is False
    assert vf.get("synthesized_refs") in (None, [])


def test_model_authored_section_survives_a_non_episodic_verdict(monkeypatch):
    """D-RC-9: the gate removes the MANDATE and the SYNTHESIS, never model freedom -- a section the
    model chose to write is kept even when relevant=False."""
    st, vf, trace = _run(monkeypatch, eps=_eps(3, receipted=(0,)), relevant=False, mech=_MECH_WITH_EPISODES)
    assert "## Episodes" in st["mechanism"]
    assert trace["episodes_model_authored"] is True
    assert trace["episodes_scaffolded"]["fired"] is False


def test_default_relevant_true_is_byte_identical_to_legacy(monkeypatch):
    """Every legacy caller omits `relevant` -> the scaffold fires exactly as before the change."""
    st, vf, trace = _run(monkeypatch, eps=_eps(2, receipted=(0,)))
    assert trace["episodes_scaffolded"]["fired"] is True
    assert "n_capped" not in trace["episodes_scaffolded"]          # caps never run flag-off


def test_caps_flag_on_bounds_the_section_receipted_first(monkeypatch):
    """9 windows (2 receipted at the EDGES, 7 absence) under max_bullets=4/max_absence=2 -> both
    receipted rows kept (the late one included -- receipted-first, not first-N), 2 absence rows fill,
    5 dropped and REPORTED via n_capped."""
    monkeypatch.setattr(an._prm, "get",
                        lambda key, default=None: {"serving.scaffold.max_bullets": 4,
                                                   "serving.scaffold.max_absence": 2}.get(key, default))
    st, vf, trace = _run(monkeypatch, eps=_eps(9, receipted=(0, 8)), relevance_flag=True)
    stamp = trace["episodes_scaffolded"]
    assert stamp["fired"] is True
    assert stamp["n_bullets"] == 4 and stamp["n_receipted"] == 2 and stamp["n_capped"] == 5
    bullets = [ln for ln in st["mechanism"].split("\n") if ln.startswith("- ")]
    assert len(bullets) == 4


def test_caps_run_flaglessly(monkeypatch):
    """D-AM stage 3 re-expression of the old flag-off exemption: caps are UNCONDITIONAL now (the
    interim kill-switch is retired). 9 rows = 2 receipted + 7 absence; the absence cap (6) drops
    exactly one row with the env var ABSENT -- the capping the old test proved could NOT happen
    flag-off is now the always-on behavior, receipted-first preserved."""
    st, vf, trace = _run(monkeypatch, eps=_eps(9, receipted=(0, 8)))
    stamp = trace["episodes_scaffolded"]
    assert stamp["fired"] is True and stamp["n_bullets"] == 8   # 2 receipted + 6 absence
    assert stamp["n_capped"] == 1


def test_scaffold_rows_dedup_by_node_span():
    """The Arabic-probe defect: TWO injected records for one node (one per routed contract) emitted
    every span twice. One bullet per (node, span), flagless -- a defect fix."""
    eps = _eps(3, receipted=(0,))
    two_records = _injected(eps) + _injected(eps)
    rows = an._scaffold_rows(two_records, [_Node("drivers/frost", eps)])
    assert rows is not None and len(rows) == 3
    assert len({(n, s) for n, s, _r in rows}) == 3
