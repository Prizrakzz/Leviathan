"""RV2 W3 -- the fence deck + harness, mock lane only (no LLM calls, no spend). Pins the deck's
STRUCTURE (lint, split discipline, frozen heldout hash) and its PREMISES against the real regex floor
(every pos_llm row is a genuine tier-1 miss, every floor row a genuine hit, every gating negative
outside neg_c8_context a genuine miss -- a regex change that moves any of these shifts what the deck
certifies and must be caught here, hermetically). The harness is exercised end-to-end through --mock:
the S3-F6 import-identity assert (score through the IMPORTED orchestrator composite, never a
reimplementation), the S2-3 ERRORED-row machinery (raise / silent-fallback / degraded all mark the
repeat unscored; any errored gating negative INVALIDATES the run), the D13 gate arithmetic (0
would-fires; >=2/3-of-repeats row rule; floor = every repeat; chips PENDING until sampled), the D18
temperature=0 proof, the GRAPHRAG_DISPATCH=rules refusal, and tune/heldout subset filtering."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from leviathan.graphrag import intent as it
from leviathan.graphrag import orchestrator as orch

_REPO = Path(__file__).resolve().parents[2]

# configs/graphrag/ is the PRIVATE config layer (gitignored; repo is public) -- mirror the
# test_graph.py tolerance: a checkout without the private configs skips this module wholesale.
if not (_REPO / "configs" / "graphrag" / "xc_fence_deck_v1.yaml").exists():
    pytest.skip("gitignored fence deck absent (private configs layer)", allow_module_level=True)


def _load_harness():
    spec = importlib.util.spec_from_file_location("xc_fence", _REPO / "scripts" / "xc_fence.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


xcf = _load_harness()
DECK = xcf.load_deck()
_ROWS = DECK["rows"]


def _cat(c):
    return [r for r in _ROWS if r["category"] == c]


def _gating_negatives():
    return [r for r in _ROWS if r["expect"] == "nofire" and r.get("gating", True)]


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# Deck structure lint
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_deck_composition_matches_d5_d13():
    assert len(_gating_negatives()) >= 50                        # D5: ~50 negatives, all gating
    assert len(_cat("pos_llm")) == 15                            # D13: >=12/15 LLM-only gate base
    assert len(_cat("pos_regex_floor")) == 4                     # D13: 4/4 floor proof
    chips = _cat("pos_chip")
    assert len(chips) == 10 and all(r.get("pending_sample") for r in chips)
    law = _cat("law_decline_expected")
    assert len(law) == 1 and law[0].get("gating") is False       # honest re-label: never a 0-fire gate row


def test_deck_split_is_roughly_half_per_category():
    cats = {r["category"] for r in _ROWS}
    for c in cats:
        rows = _cat(c)
        if len(rows) < 2:
            continue                                             # single-row categories can't split
        splits = {r["split"] for r in rows}
        assert splits == {"tune", "heldout"}, f"category {c} is not split across tune/heldout"
        n_h = sum(1 for r in rows if r["split"] == "heldout")
        assert abs(len(rows) - 2 * n_h) <= 1, f"category {c} split is not ~50/50"


def test_deck_heldout_rows_are_frozen():
    for r in _ROWS:
        if r["split"] == "heldout" and not r.get("pending_sample"):
            assert r.get("frozen") is True, r["id"]


@pytest.mark.parametrize("mutate,err", [
    (lambda d: d["rows"].append(dict(d["rows"][0])), "duplicate row id"),
    (lambda d: d["rows"][0].pop("expect"), "missing required field"),
    (lambda d: d["rows"][0].update(expect="maybe"), "expect must be"),
    (lambda d: d["rows"][0].update(split="holdout"), "split must be"),
    (lambda d: d["rows"][0].update(expect_tier="sonnet"), "expect_tier must be"),
    (lambda d: d["rows"][0].pop("question"), "missing question"),
])
def test_lint_rejects_malformed_decks(mutate, err):
    deck = copy.deepcopy(DECK)
    mutate(deck)
    with pytest.raises(ValueError, match=err):
        xcf.lint_deck(deck)


def test_lint_rejects_unfrozen_heldout():
    deck = copy.deepcopy(DECK)
    row = next(r for r in deck["rows"] if r["split"] == "heldout" and not r.get("pending_sample"))
    row.pop("frozen")
    with pytest.raises(ValueError, match="frozen"):
        xcf.lint_deck(deck)


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# Deck premises vs the REAL regex floor (hermetic: pure regex, no LLM)
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_pos_llm_rows_are_genuine_regex_misses():
    # the LLM-only gate is honest only if tier-1 truly misses every one of these (else tier=regex fires
    # them and the deck certifies nothing about the LLM).
    for r in _cat("pos_llm"):
        assert it.is_cross_commodity_explicit(r["question"]) == (False, None), r["id"]


def test_floor_rows_are_genuine_regex_hits():
    for r in _cat("pos_regex_floor"):
        matched, span = it.is_cross_commodity_explicit(r["question"])
        assert matched is True and span, r["id"]


def test_gating_negatives_outside_c8_are_regex_misses():
    # the c8 rows regex-match BY DESIGN (necessary-not-sufficient floor; the LAW C8-declines them);
    # every OTHER gating negative must be a floor miss -- a regex change that starts matching one is a
    # floor regression this pin catches before the deck mis-attributes it.
    for r in _gating_negatives():
        if r["category"] == "neg_c8_context":
            continue
        assert it.is_cross_commodity_explicit(r.get("question") or "") == (False, None), r["id"]


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# Heldout hash: frozen, order-insensitive, tune/pending-insensitive
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_heldout_hash_stable_across_loads_and_row_order():
    h1 = xcf.heldout_hash(DECK)
    h2 = xcf.heldout_hash(xcf.load_deck())
    assert h1 == h2 and len(h1) == 16
    reordered = copy.deepcopy(DECK)
    reordered["rows"] = list(reversed(reordered["rows"]))
    assert xcf.heldout_hash(reordered) == h1


def test_heldout_hash_moves_only_on_heldout_content():
    base = xcf.heldout_hash(DECK)
    d = copy.deepcopy(DECK)
    next(r for r in d["rows"] if r["split"] == "heldout" and not r.get("pending_sample"))["question"] = "EDITED"
    assert xcf.heldout_hash(d) != base                           # frozen half moved -> hash moved
    d = copy.deepcopy(DECK)
    next(r for r in d["rows"] if r["split"] == "tune")["question"] = "EDITED"
    assert xcf.heldout_hash(d) == base                           # TUNE iteration never moves the frozen hash
    d = copy.deepcopy(DECK)
    next(r for r in d["rows"] if r.get("pending_sample") and r["split"] == "heldout")["question"] = "EDITED"
    assert xcf.heldout_hash(d) == base                           # placeholders join the hash when sampled


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# S3-F6 import identity: the harness scores through THE orchestrator symbol
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def test_composite_is_the_imported_orchestrator_symbol():
    assert xcf._COMPOSITE is orch.xc_detect_two_tier
    xcf.assert_composite_identity()                              # must not raise


def test_composite_identity_assert_catches_reimplementation(monkeypatch):
    monkeypatch.setattr(xcf, "_COMPOSITE", lambda plan: (lambda q: (False, None)))
    with pytest.raises(AssertionError, match="reimplementation"):
        xcf.assert_composite_identity()


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# Mock run end-to-end + gate arithmetic
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _run(deck=None, factory=None, **kw):
    kw.setdefault("repeats_neg", 1)
    kw.setdefault("repeats_pos", 3)
    deck = deck or DECK
    results = xcf.run_deck(deck, graph=xcf.mock_graph(), call_factory=factory or xcf.mock_call_factory, **kw)
    return results, xcf.score(results, deck, subset=kw.get("subset"))


def test_mock_full_run_passes_all_gates(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    results, scored = _run()
    agg = scored["aggregates"]
    assert agg["run_valid"] is True and agg["invalid_negatives"] == []
    assert agg["neg_gate"] == "PASS" and agg["neg_failed"] == []
    assert agg["pos_llm_gate"] == "PASS" and agg["pos_llm_passed"] == 15
    assert agg["floor_gate"] == "PASS" and agg["floor_passed"] == 4
    assert agg["chip_gate"].startswith("PENDING")                # 10 placeholders unsampled
    assert agg["temperature_ok"] is True                         # D18: every call saw temperature=0
    ran_ids = {item["row"]["id"] for item in results}
    assert not any(i.startswith("chip_pending") for i in ran_ids)   # placeholders never run
    # the c8 rows report their by-design regex hits informationally, and still PASS at the plan level
    c8 = [s for s in scored["per_row"] if s["category"] == "neg_c8_context"]
    assert sum(s["regex_hits"] for s in c8) == 2 and all(s["pass"] for s in c8)
    # the law-decline row is informational: fires, but can neither fail nor pass a gate
    law = next(s for s in scored["per_row"] if s["category"] == "law_decline_expected")
    assert law["pass"] is None and law["fires"] == 3


def test_errored_gating_negative_invalidates_run(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)

    def factory(row):
        if row["id"] == "neg_nonxc_why_did_palm_rally":
            def boom(system, user, *, model, tool, **kw):
                raise RuntimeError("429 throttled")
            return boom
        return xcf.mock_call_factory(row)

    _, scored = _run(factory=factory)
    agg = scored["aggregates"]
    assert agg["run_valid"] is False
    assert agg["invalid_negatives"] == ["neg_nonxc_why_did_palm_rally"]
    assert agg["neg_gate"] == "FAIL"                             # an unscored negative is not a passed one
    row = next(s for s in scored["per_row"] if s["id"] == "neg_nonxc_why_did_palm_rally")
    assert row["errored"] == 1 and "RuntimeError" in row["errors"][0] and row["pass"] is False


def test_errored_positive_does_not_invalidate_but_floor_gate_fails(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)

    def factory(row):
        if row["id"] == "floor_possessive_bare_palm":
            def boom(system, user, *, model, tool, **kw):
                raise RuntimeError("timeout")
            return boom
        return xcf.mock_call_factory(row)

    _, scored = _run(factory=factory)
    agg = scored["aggregates"]
    assert agg["run_valid"] is True                              # only NEGATIVE errors invalidate (S2-3)
    assert agg["floor_gate"] == "FAIL" and agg["floor_passed"] == 3   # floor demands every repeat clean


def test_silent_fallback_and_degraded_are_errored(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    tiny = {"today": "2026-02-15", "rows": [
        {"id": "n1", "category": "neg_nonxc", "expect": "nofire", "split": "tune",
         "question": "why did palm rally?"},
        {"id": "n2", "category": "neg_nonxc", "expect": "nofire", "split": "tune",
         "question": "how is palm doing today?"},
    ]}

    def factory(row):
        if row["id"] == "n1":
            return lambda system, user, *, model, tool, **kw: {"steps": []}          # -> _FALLBACK, no raise
        return lambda system, user, *, model, tool, **kw: {
            "steps": ["reasoning"], "contracts": [], "_degraded_model": True}        # -> Plan.degraded (D2)

    results = xcf.run_deck(tiny, graph=xcf.mock_graph(), call_factory=factory, repeats_neg=1)
    scored = xcf.score(results, tiny)
    by_id = {s["id"]: s for s in scored["per_row"]}
    assert by_id["n1"]["errors"] == ["planner_fallback (no raise)"]
    assert by_id["n2"]["errors"] == ["degraded_model (Sonnet->Haiku)"]
    assert scored["aggregates"]["run_valid"] is False
    assert sorted(scored["aggregates"]["invalid_negatives"]) == ["n1", "n2"]


def test_negative_would_fire_fails_row_and_gate_but_run_stays_valid(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)

    def factory(row):
        if row["id"] == "neg_inj_q_ignore_prior":                # the injection succeeded in this scenario
            return lambda system, user, *, model, tool, **kw: {
                "steps": ["reasoning"], "contracts": [], "xc_explicit": True, "xc_target": "soybean oil"}
        return xcf.mock_call_factory(row)

    _, scored = _run(factory=factory)
    agg = scored["aggregates"]
    assert agg["run_valid"] is True                              # scored cleanly -- just a FENCE failure
    assert agg["neg_gate"] == "FAIL" and agg["neg_failed"] == ["neg_inj_q_ignore_prior"]
    row = next(s for s in scored["per_row"] if s["id"] == "neg_inj_q_ignore_prior")
    assert row["llm_would_fires"] == 1 and row["pass"] is False


@pytest.mark.parametrize("fires,passes", [(3, True), (2, True), (1, False), (0, False)])
def test_two_thirds_repeat_rule_on_llm_rows(monkeypatch, fires, passes):
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    tiny = {"today": "2026-02-15", "rows": [
        {"id": "p1", "category": "pos_llm", "expect": "fire", "expect_tier": "llm", "split": "tune",
         "question": "how does a palm export ban affect soybean oil?"}]}

    def factory(row):
        n = {"i": 0}

        def inner(system, user, *, model, tool, **kw):
            n["i"] += 1
            hit = n["i"] <= fires
            return {"steps": ["reasoning"], "contracts": [],
                    "xc_explicit": hit, "xc_target": ("soybean oil" if hit else None)}
        return inner

    results = xcf.run_deck(tiny, graph=xcf.mock_graph(), call_factory=factory, repeats_pos=3)
    scored = xcf.score(results, tiny)
    row = scored["per_row"][0]
    assert row["fires"] == fires and row["pass"] is passes


def test_llm_row_fire_requires_llm_tier_attribution(monkeypatch):
    # an open (null-target) emission is traced but NEVER routed (D19): the composite attributes tier=none
    # and the row must NOT count as fired even though xc_explicit came back true.
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    tiny = {"today": "2026-02-15", "rows": [
        {"id": "p1", "category": "pos_llm", "expect": "fire", "expect_tier": "llm", "split": "tune",
         "question": "how does a palm export ban affect soybean oil?"}]}

    def factory(row):
        return lambda system, user, *, model, tool, **kw: {
            "steps": ["reasoning"], "contracts": [], "xc_explicit": True, "xc_target": None}

    results = xcf.run_deck(tiny, graph=xcf.mock_graph(), call_factory=factory, repeats_pos=3)
    row = xcf.score(results, tiny)["per_row"][0]
    assert row["fires"] == 0 and row["pass"] is False
    assert all(x["tier"] == "none" and x["llm_consulted"] for x in results[0]["reps"])


def test_subset_filters_and_marks_gates_subset(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    ran: list[str] = []

    def factory(row):
        ran.append(row["id"])
        return xcf.mock_call_factory(row)

    _, scored = _run(factory=factory, subset="tune")
    assert ran and all(next(r for r in _ROWS if r["id"] == i)["split"] == "tune" for i in ran)
    agg = scored["aggregates"]
    assert agg["neg_gate"] == "SUBSET (not a gate run)"          # D13 gates score FULL runs only
    assert agg["pos_llm_gate"] == "SUBSET (not a gate run)"


def test_rules_dispatch_refused(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_DISPATCH", "rules")
    with pytest.raises(RuntimeError, match="rules"):
        xcf.run_deck(DECK, graph=xcf.mock_graph(), call_factory=xcf.mock_call_factory)
    assert xcf.main(["--mock"]) == 2                             # CLI refuses before any call


def test_non_toy_enum_refused():
    with pytest.raises(SystemExit, match="toy"):
        xcf._assert_non_toy({f"c{i}": None for i in range(5)})


def test_run_deck_restores_detect_flag(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    tiny = {"today": "2026-02-15", "rows": [
        {"id": "n1", "category": "neg_nonxc", "expect": "nofire", "split": "tune",
         "question": "why did palm rally?"}]}
    import os
    monkeypatch.delenv("GRAPHRAG_XC_LLM_DETECT", raising=False)
    xcf.run_deck(tiny, graph=xcf.mock_graph(), call_factory=xcf.mock_call_factory, repeats_neg=1)
    assert "GRAPHRAG_XC_LLM_DETECT" not in os.environ            # unset stays unset after the run
    monkeypatch.setenv("GRAPHRAG_XC_LLM_DETECT", "off")
    xcf.run_deck(tiny, graph=xcf.mock_graph(), call_factory=xcf.mock_call_factory, repeats_neg=1)
    assert os.environ["GRAPHRAG_XC_LLM_DETECT"] == "off"         # prior value restored


def test_cli_mock_end_to_end(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    rpt = tmp_path / "fence_mock.json"
    assert xcf.main(["--mock", "--report", str(rpt)]) == 0
    out = capsys.readouterr().out
    assert "HELDOUT CONTENT HASH" in out and xcf.heldout_hash(DECK) in out
    assert "MOCK RUN" in out                                     # stamped non-certifying
    doc = json.loads(rpt.read_text(encoding="utf-8"))
    assert doc["mock"] is True and doc["provider"] == "mock" and doc["temperature"] == 0
    assert doc["heldout_hash"] == xcf.heldout_hash(DECK)
    assert doc["n_contracts"] == len(xcf._MOCK_ENUM) and doc["enum_hash"]
    assert doc["scores"]["aggregates"]["neg_gate"] == "PASS"
