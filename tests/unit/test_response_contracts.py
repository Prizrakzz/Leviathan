"""D-RC Phase B: the response_contracts leaf module + the tier-1 selector.

Pins the load-bearing guarantees: the three persona needles exist byte-for-byte in _SYSTEM_MENTOR
(rewrite-by-replacement reds here on persona drift, never silently no-ops); `default` and
`passthrough` apply() are IDENTITY (the fail-open guarantee is structural); every menu entry
satisfies the spine invariant; `enumeration` is the sole '## Episodes' license; and the selector
maps the two calibration corpora (desk-probe + playbook decks) to the expected contracts.
"""
from __future__ import annotations

import pathlib

import pytest

from leviathan.graphrag import answer as an
from leviathan.graphrag import intent as it
from leviathan.graphrag import response_contracts as rc

_CFG = pathlib.Path(an.__file__).parents[3] / "configs" / "graphrag"


# ══ the module ═══════════════════════════════════════════════════════════════════════════════════════
def test_needles_exist_in_mentor_persona():
    for needle in (rc.NEEDLE_STRUCTURE, rc.NEEDLE_BUDGET, rc.NEEDLE_FIELDLIST):
        assert needle in an._SYSTEM_MENTOR, f"persona needle drifted: {needle[:60]}..."


def test_apply_identity_for_default_none_passthrough_unknown():
    base = an._SYSTEM_MENTOR
    assert rc.apply(base, None) is base
    assert rc.apply(base, rc.DEFAULT) is base
    assert rc.apply(base, "outlook") is base          # passthrough: the outlook gate owns that lane
    assert rc.apply(base, "no_such_contract") is base


def test_apply_rewrites_all_three_sites():
    base = an._SYSTEM_MENTOR
    out = rc.apply(base, "ranking")
    assert out != base
    assert rc.NEEDLE_STRUCTURE not in out and rc.NEEDLE_BUDGET not in out
    assert rc.NEEDLE_FIELDLIST not in out
    assert "'## Mechanism', '## The record', '## What to watch'" in out
    assert "target 90-160 words across the 3 sections" in out
    assert "structured under the '## ' headings above" in out


def test_apply_enumeration_carries_episodes_rule():
    out = rc.apply(an._SYSTEM_MENTOR, "enumeration")
    assert "'## Episodes'" in out and "after '## The record' and before '## What to watch'" in out


def test_spine_invariant_every_entry():
    for name in rc.CONTRACTS:
        assert rc.spine_ok(name), f"{name} violates the spine invariant"
        assert set(rc.CONTRACTS[name].sections) <= rc.SECTIONS


def test_default_directive_is_empty_and_others_are_paragraphs():
    assert rc.directive(rc.DEFAULT) == ""             # LOAD-BEARING: the fail-open guarantee
    assert rc.directive(None) == ""
    assert rc.directive("outlook") == ""              # passthrough adds nothing
    for name, c in rc.CONTRACTS.items():
        if c.directive:
            assert c.directive.startswith("\n\n")


def test_enumeration_is_the_sole_episodes_license():
    holders = [n for n in rc.CONTRACTS if rc.licenses_episodes(n)]
    assert holders == ["enumeration"]


def test_default_sections_parity_with_eval_fixed_scaffold():
    from leviathan.graphrag import eval as ev
    assert tuple(rc.CONTRACTS[rc.DEFAULT].sections) == tuple(ev._FIXED_SCAFFOLD)


# ══ the tier-1 selector, calibrated on the desk probe ════════════════════════════════════════════════
_PROBE_EXPECT = [
    ("Who are the 3 largest canola producers and exporters?", "ranking"),
    ("How is the S&D and exports looking in Malaysia right now?", "recency"),
    ("How was the weather in cocoa regions in the past 3 weeks? Is it indicating a loss in "
     "production for the coming months or crop year?", "recency"),
    ("The 2015-16 super El Nino reduced Ghanaian cocoa yields sharply, cut Thai sugarcane "
     "production, disrupted Brazilian sugar harvest logistics, and reduced Vietnamese coffee "
     "output. Is this documented, or can we only infer it?", "verification"),
    ("What if Iran restricted the Strait of Hormuz? How would that play out for agricultural "
     "commodities?", "counterfactual"),
    ("Compare cocoa and palm.", "compare"),
    ("Does barley affect any commodity?", "context_node"),
    ("When has China done import restrictions, and what commodities were affected each time?", "enumeration"),
    ("What is Australia's ranking in terms of wheat exporting, and what would happen to make it "
     "rank lower?", "ranking"),
    # fail-open rows: no narrow cue -> None -> default shape downstream
    ("What would happen to wheat companies in the US?", None),
    ("No two El Ninos are the same. How does the SCALE of an El Nino change what happens to sugar "
     "and palm oil?", None),
    ("I'm focused on winter wheat. What should I look out for in the next 3 months, and what do "
     "you think the trajectory is, long or short?", None),   # outlook is tier-0's call, never tier-1's
    ("ما الذي يحدث عادة لأسعار القمح؟", None),               # non-Latin: cues are English, fail open
]


@pytest.mark.parametrize("q,want", _PROBE_EXPECT)
def test_selector_probe_calibration(q, want):
    assert it.select_response_contract(q) == want


def test_selector_every_playbook_row_is_enumeration():
    import yaml
    rows = []
    for name in ("eval_queries_playbooks_v1.yaml", "eval_queries_playbooks_r6residual.yaml"):
        p = _CFG / name
        if p.exists():
            rows += [(q["id"], q["question"]) for q in
                     (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("queries") or []]
    if not rows:
        pytest.skip("playbook decks are gitignored and absent from this clone")
    wrong = [(i, it.select_response_contract(q)) for i, q in rows
             if it.select_response_contract(q) != "enumeration"]
    assert not wrong, f"playbook rows must select enumeration: {wrong}"


def test_selector_names_are_valid_contracts():
    for name, _rx in it._RC_PATTERNS:
        assert name in rc.valid_names()


# ── Phase B: threading + the exemption pins ──────────────────────────────────────────────────────────
def test_system_contract_rewrite_and_directive(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
    base = an._system()
    assert an._system(response_contract=None) == base
    assert an._system(response_contract="default") == base
    assert an._system(response_contract="outlook") == base          # passthrough
    ranked = an._system(response_contract="ranking")
    assert ranked != base
    assert "RANKING EMPHASIS" in ranked and ranked.endswith(rc.CONTRACTS["ranking"].directive)
    assert rc.NEEDLE_STRUCTURE not in ranked


def test_enabled_flag_value_grammar(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_RESPONSE_CONTRACT", raising=False)
    assert an._response_contracts_enabled() == frozenset()
    monkeypatch.setenv("GRAPHRAG_RESPONSE_CONTRACT", "off")
    assert an._response_contracts_enabled() == frozenset()
    monkeypatch.setenv("GRAPHRAG_RESPONSE_CONTRACT", "on")
    assert an._response_contracts_enabled() == rc.valid_names()
    monkeypatch.setenv("GRAPHRAG_RESPONSE_CONTRACT", "verification,ranking,context_node,bogus")
    assert an._response_contracts_enabled() == frozenset({"verification", "ranking", "context_node"})


def test_exempt_lanes_have_no_response_contract_param():
    """Tier-0 exemption is DECLARED, not discovered: run_live and run_numbers_only must never grow
    the kwarg silently -- numbers has no answer.py seam (cache_control'd byte-stable system block)
    and live has its own kw dict + a legacy early-return above the decision point."""
    import inspect
    from leviathan.graphrag import orchestrator as orch
    assert "response_contract" not in inspect.signature(orch.run_live).parameters
    assert "response_contract" not in inspect.signature(orch.run_numbers_only).parameters
    assert "response_contract" in inspect.signature(orch.run_reasoning).parameters
    assert "response_contract" in inspect.signature(orch.run_hybrid).parameters
