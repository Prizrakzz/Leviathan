"""D-RC-14: profile facts -> answer context (GRAPHRAG_PROFILE_CONTEXT, default OFF).

The block is PREFERENCES, never evidence: labeled non-citable, rides sblock -> extra_context ->
the volatile tail (reasoning+hybrid lanes only), handle-shaped tokens stripped, reg.sanitize'd,
hard-capped. Flag off = the server never reads the profile store on the turn path and the
orchestrator concat reads nothing -- byte-identical turns.
"""
from __future__ import annotations

from leviathan.graphrag import orchestrator as orch


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_PROFILE_CONTEXT", raising=False)
    assert orch._profile_context_on() is False
    monkeypatch.setenv("GRAPHRAG_PROFILE_CONTEXT", "on")
    assert orch._profile_context_on() is True
    monkeypatch.setenv("GRAPHRAG_PROFILE_CONTEXT", "1")           # fail-closed: only exact 'on'
    assert orch._profile_context_on() is False


def test_profile_block_shape_and_label():
    b = orch._profile_block({"seat": "softs desk", "markets": ["winter wheat", "cocoa"],
                             "regions": ["Black Sea"], "notes": ["prefers episode detail"]})
    assert b is not None
    assert b.startswith("=== RESEARCHER PROFILE")
    assert "NOT evidence" in b and "never cite" in b
    assert "- seat: softs desk" in b and "winter wheat, cocoa" in b


def test_profile_block_empty_cases():
    assert orch._profile_block(None) is None
    assert orch._profile_block({}) is None
    assert orch._profile_block({"markets": []}) is None
    assert orch._profile_block("not a dict") is None
    assert orch._profile_block({"unknown_key": "x"}) is None       # only the sanctioned keys render


def test_profile_block_strips_handle_tokens_and_caps():
    """User-authored text is a prompt-injection surface: a fact carrying '[E1]'/'[N2]' must not put
    handle-shaped tokens into the prompt (they could collide with the grounding ledger's ranges)."""
    b = orch._profile_block({"notes": ["watch [E1] and [N2] closely", "x" * 500]})
    assert "[E1]" not in b and "[N2]" not in b
    assert len(b) < 1700                                           # label + capped body


def test_profile_block_long_lists_bounded():
    b = orch._profile_block({"markets": [f"commodity_{i}" for i in range(40)]})
    assert b.count("commodity_") <= 12                             # the write-side cap, re-applied on read
