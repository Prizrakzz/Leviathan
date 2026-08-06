"""D-AM-20: the selector SHADOW stamp + the router measurement deck.

Two things are pinned here.

(1) THE SHADOW SELECTOR. `intent.select_response_contract_all` returns EVERY tier-1 match in
    _RC_PATTERNS priority order, and `select_response_contract` is now its first element. The
    load-bearing property is that the OLD function's behaviour is byte-identical: the D-RC-6
    calibration corpora (the 13-row desk probe + the playbook decks, both pinned in
    test_response_contracts.py) must return exactly what they returned before delegation, and on
    EVERY row of the new deck the two functions must agree by construction
    (`select_response_contract(q) == all(q)[0] if all(q) else None`).

(2) THE STAMP. orchestrator.py's ONE response-contract decision point carries `also_matched` --
    the non-winner matches -- inside the existing `response_contract` decision dict. That dict is
    lifted WHOLE into the eval record by tracekeys.DECISION_RECORD_KEYS, so the shadow reaches
    artifacts with NO new eval column; the test asserts the registry mapping rather than a column.

Plus the deck's own structural pins (ids unique, labels in the vocabularies, every rc_expected a
real contract name, store rows never fabricated) and a smoke run of the offline scorer.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest
import yaml

from leviathan.graphrag import answer as an
from leviathan.graphrag import intent as it
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import response_contracts as rc
from leviathan.graphrag import tracekeys as tk

_REPO = pathlib.Path(an.__file__).parents[3]
_CFG = _REPO / "configs" / "graphrag"
DECK = _CFG / "eval_queries_router_v2.yaml"
_PRIORITY = tuple(name for name, _rx in it._RC_PATTERNS)
_INTENTS = {"numbers_only", "reasoning", "hybrid", "live"}
_SOURCES = {"store", "synthetic"}


def _load(path: pathlib.Path, name: str):
    """Import a sibling module by PATH (independent of pytest's import mode / rootdir insertion)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RCTEST = _load(pathlib.Path(__file__).with_name("test_response_contracts.py"), "_dam20_rc_fixtures")
_DECK_DOC = yaml.safe_load(DECK.read_text(encoding="utf-8")) or {}
_ROWS = _DECK_DOC.get("rows") or []


# ══ (1a) select_response_contract_all -- ordering ═════════════════════════════════════════════════════
def test_all_returns_matches_in_priority_order():
    """A contested query returns its matches in _RC_PATTERNS order, not match order in the string."""
    q = "How do the drivers rank short run versus long run for palm?"
    got = it.select_response_contract_all(q)
    assert got == ("horizon", "ranking", "compare")
    assert got[0] == it.select_response_contract(q)


@pytest.mark.parametrize("row", _ROWS, ids=[r["id"] for r in _ROWS])
def test_all_order_is_always_a_subsequence_of_the_priority_tuple(row):
    got = it.select_response_contract_all(row["question"])
    idx = [_PRIORITY.index(n) for n in got]
    assert idx == sorted(idx), f"{row['id']}: {got} is not in _RC_PATTERNS priority order"
    assert len(set(got)) == len(got), f"{row['id']}: duplicate names in the match tuple"


def test_all_names_are_real_contracts():
    for row in _ROWS:
        for name in it.select_response_contract_all(row["question"]):
            assert name in rc.valid_names()


# ══ (1b) emptiness ═══════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("q", [
    "", "   ", None,
    "Why did cocoa rally in early 2024?",                       # plain mechanism: no narrow cue
    "ما الذي يحدث لأسعار"
    " القمح؟",                    # non-Latin: the cue list is English
])
def test_all_is_empty_tuple_not_none(q):
    got = it.select_response_contract_all(q)
    assert got == () and isinstance(got, tuple)
    assert it.select_response_contract(q) is None


# ══ (1c) delegation byte-identity -- the D-RC-6 calibration corpora are UNCHANGED ═════════════════════
@pytest.mark.parametrize("q,want", _RCTEST._PROBE_EXPECT)
def test_old_selector_unchanged_on_the_13_probe_fixtures(q, want):
    assert it.select_response_contract(q) == want


def test_old_selector_unchanged_on_the_playbook_decks():
    rows = []
    for name in ("eval_queries_playbooks_v1.yaml", "eval_queries_playbooks_r6residual.yaml"):
        p = _CFG / name
        if p.exists():
            rows += [(q["id"], q["question"]) for q in
                     (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("queries") or []]
    if not rows:
        pytest.skip("playbook decks are gitignored and absent from this clone")
    horizon_rows = {"pb_watch_horizons"}
    wrong = [(i, it.select_response_contract(q)) for i, q in rows
             if it.select_response_contract(q) != ("horizon" if i in horizon_rows else "enumeration")]
    assert not wrong, f"delegation changed the playbook calibration: {wrong}"


@pytest.mark.parametrize("row", _ROWS, ids=[r["id"] for r in _ROWS])
def test_delegation_identity_on_every_deck_row(row):
    q = row["question"]
    matches = it.select_response_contract_all(q)
    assert it.select_response_contract(q) == (matches[0] if matches else None)


def test_first_match_wins_is_still_first_match_wins():
    """Re-derive the OLD implementation inline and require agreement on every deck row -- the
    delegation must not have changed which pattern wins, only what else is reported."""
    def old(query):
        q = query or ""
        for name, rx in it._RC_PATTERNS:
            if rx.search(q):
                return name
        return None
    for row in _ROWS:
        assert it.select_response_contract(row["question"]) == old(row["question"]), row["id"]


# ══ (2) the stamp at the ONE decision point ══════════════════════════════════════════════════════════
CORN = "corn_cbot"
SOY = "soybeans_cbot"


def _graph():
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    corn = cs.CausalContract(contract=CORN, aliases=["corn", "maize"],
                             drivers=[cs.Driver(id="export_pace", type="demand", sign="+", mechanism="exports")])
    soy = cs.CausalContract(contract=SOY, aliases=["soybeans", "beans"],
                            drivers=[cs.Driver(id="fund_flow", type="positioning", sign="+", mechanism="mm")])
    return g.CausalGraph({CORN: corn, SOY: soy}, silver=set())


def _planner_call(steps=("reasoning",)):
    def call(system, user, *, model, tool, **kw):
        if tool["name"] == "set_plan":
            return {"steps": list(steps), "contracts": []}
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}
    return call


def _decide(monkeypatch, query, *, steps=("reasoning",)):
    """Drive respond() to its decision record with every engine stubbed (no API, no evidence)."""
    def mk(kind):
        def run(*a, **k):
            return {"answer": "stub", "intent": kind, "structured": None, "evidence": [],
                    "citations": [], "number_calls": [], "contract": None, "contracts": []}
        return run
    monkeypatch.setattr(orch, "run_reasoning", mk("reasoning"))
    monkeypatch.setattr(orch, "run_hybrid", mk("hybrid"))
    monkeypatch.setattr(orch, "run_numbers_only", mk("numbers_only"))
    monkeypatch.delenv("GRAPHRAG_RESPONSE_CONTRACT", raising=False)
    out = orch.respond(query, graph=_graph(), asof="2026-06-01", call=_planner_call(steps))
    return (out.get("intent_decision") or {}).get("response_contract")


def test_also_matched_stamped_for_a_contested_turn(monkeypatch):
    dec = _decide(monkeypatch, "How do the drivers rank short run versus long run for corn?")
    assert dec["selected"] == "horizon" and dec["resolved"] == "horizon"
    assert dec["also_matched"] == ["ranking", "compare"]
    assert dec["tier"] == "lexical" and dec["outlook_preempt"] is False


def test_also_matched_is_empty_list_when_the_winner_is_unopposed(monkeypatch):
    dec = _decide(monkeypatch, "Compare corn and soybeans balance sheets for 2025-26.")
    assert dec["selected"] == "compare"
    assert dec["also_matched"] == []


def test_also_matched_is_empty_list_when_nothing_matches(monkeypatch):
    dec = _decide(monkeypatch, "Why did corn rally in early 2024?")
    assert dec["selected"] is None and dec["resolved"] is None
    assert dec["tier"] == "none" and dec["also_matched"] == []


def test_decision_dict_is_json_serializable_lists_not_tuples(monkeypatch):
    dec = _decide(monkeypatch, "How do the drivers rank short run versus long run for corn?")
    assert isinstance(dec["also_matched"], list)
    assert json.loads(json.dumps(dec))["also_matched"] == ["ranking", "compare"]


def test_shadow_rides_the_existing_decision_lift_no_new_eval_column():
    """The stamp reaches eval artifacts through the WHOLE-dict lift that already exists -- so the
    registry entry is the pin, and adding an eval column would be the defect, not the fix."""
    assert ("response_contract", "response_contract_decision") in tk.DECISION_RECORD_KEYS
    assert not any(col == "also_matched" for _dk, col in tk.DECISION_RECORD_KEYS)
    assert "also_matched" not in tk.TRACE_RECORD_KEYS
    lifted = {col: {"response_contract": {"selected": "horizon", "also_matched": ["ranking"]}}.get(dk)
              for dk, col in tk.DECISION_RECORD_KEYS}
    assert lifted["response_contract_decision"]["also_matched"] == ["ranking"]


# ══ (3) the deck ═════════════════════════════════════════════════════════════════════════════════════
def test_deck_parses_and_is_the_expected_size():
    assert _DECK_DOC.get("deck") == "router_v2"
    assert len(_ROWS) >= 100
    assert isinstance(_DECK_DOC.get("store_rows_true_count"), int)


def test_deck_ids_unique():
    ids = [r["id"] for r in _ROWS]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate deck ids: {dupes}"


def test_deck_questions_unique_after_casefold_dedupe():
    keys = [" ".join((r["question"] or "").split()).casefold() for r in _ROWS]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, f"duplicate questions survived dedupe: {dupes}"


@pytest.mark.parametrize("row", _ROWS, ids=[r["id"] for r in _ROWS])
def test_deck_row_shape(row):
    assert row["question"] and isinstance(row["question"], str)
    assert row["source"] in _SOURCES
    assert row["expected_intent"] in _INTENTS
    assert isinstance(row["ambiguous"], bool)
    assert "rc_expected" in row


@pytest.mark.parametrize("row", _ROWS, ids=[r["id"] for r in _ROWS])
def test_every_rc_expected_is_a_valid_contract_name(row):
    want = row["rc_expected"]
    assert want is None or want in rc.valid_names(), f"{row['id']}: {want!r} not a contract name"


def test_rc_expected_never_names_outlook_or_default():
    """Tier 1 can return neither: `outlook` is tier-0's (the selector never emits it) and `default`
    is expressed as null. A label using either would silently guarantee a miss."""
    named = {r["rc_expected"] for r in _ROWS if r["rc_expected"] is not None}
    assert not (named & {"outlook", rc.DEFAULT})
    assert named <= set(_PRIORITY)


def test_store_rows_match_the_declared_true_count_and_are_never_fabricated():
    """The header states the TRUE number of real user questions found in the durable stores. If a
    later edit adds `source: store` rows, this reds -- padding a measurement deck with invented
    rows labelled real is the failure this pin exists to prevent."""
    store = [r for r in _ROWS if r["source"] == "store"]
    assert len(store) == _DECK_DOC["store_rows_true_count"] == 5
    assert all(r["id"].startswith("st_") for r in store)
    assert all(r["id"].startswith("sy_") for r in _ROWS if r["source"] == "synthetic")


def test_deck_covers_every_tier1_contract_plus_the_default_bucket():
    labelled = {r["rc_expected"] for r in _ROWS}
    assert None in labelled                                   # the fail-open / default stratum exists
    assert set(_PRIORITY) <= labelled                          # every family is measured
    for name in _PRIORITY:
        n = sum(1 for r in _ROWS if r["rc_expected"] == name)
        assert n >= 10, f"stratum {name} has only {n} rows -- too thin to bound"


def test_deck_shares_no_rows_with_the_tuned_calibration_corpus():
    """The 13-row desk probe is the TUNED corpus; this deck is the measurement corpus. Overlap
    would smuggle a fitted row into the measurement."""
    tuned = {" ".join(q.split()).casefold() for q, _w in _RCTEST._PROBE_EXPECT}
    deck = {" ".join(r["question"].split()).casefold() for r in _ROWS}
    assert not (tuned & deck)


# ══ (4) the offline scorer ═══════════════════════════════════════════════════════════════════════════
def _audit():
    return _load(_REPO / "scripts" / "router_deck_audit.py", "_dam20_router_audit")


def test_audit_scores_the_deck_and_wilson_bound_is_sane():
    aud = _audit()
    assert aud.wilson_lb(0, 10) == 0.0
    assert 0.0 < aud.wilson_lb(10, 10) < 1.0                   # never degenerate at the boundary
    assert aud.wilson_lb(9, 10) < 9 / 10                       # a LOWER bound, always below the point
    assert aud.wilson_lb(5, 0) == 0.0
    scored = [aud.score_row(r) for r in _ROWS]
    assert len(scored) == len(_ROWS)
    assert all(s["stratum"] for s in scored)
    assert any(s["also_matched"] for s in scored)               # the deck really does contest rows
    assert all(s["ok"] == (s["got"] == s["want"]) for s in scored)


def test_audit_runs_end_to_end_ascii_only(capsys):
    aud = _audit()
    assert aud.main([]) == 0
    out = capsys.readouterr().out
    assert out.encode("ascii", "strict")                        # cp1252 console safety
    assert "SELECTOR ACCURACY" in out and "CONTESTED ROWS" in out and "MISSES" in out
