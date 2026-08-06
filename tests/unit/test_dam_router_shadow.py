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


# ══ (5) D-UX-5 -- the counterfactual cue widening ═════════════════════════════════════════════════════
# The deck measured counterfactual WEAKEST (9/18) with named gaps. The widening adds "let's/let us
# say", clause-anchored "assume"/"imagine"/"say <det>", a bounded multi-word subjunctive subject, and
# the "what would X do to Y" phrasing both REAL store counterfactual rows use. What is pinned here:
# the new cues fire, the near-misses do NOT, the store rows land, the stratum floors do not fall, and
# the Phase-C A/B deck selects exactly what it selected before the widening (ZERO drift).

_CF_NEW_CUE_POSITIVES = [
    "Let's say Indonesia doubles the export levy tomorrow.",
    "Lets say the ringgit weakens 10 percent -- where does palm go?",        # missing apostrophe
    "Let us say Ghana misses half its forward sales this season.",
    "Let’s say the Black Sea corridor lapses again.",                   # curly apostrophe
    "Let's assume the blend mandate is renewed.",
    "Assume Argentina halves its soybean export tax. What happens to crush?",
    "Now assume the biodiesel blend mandate lapses.",
    "Imagine the harmattan runs hot for eight straight weeks.",
    "Then imagine China books 10 million tonnes in a month.",
    "Say the blender credit lapses in December.",
    "Say a frost hits Minas in early July.",
    "Say an export ban lands mid-harvest.",
    "Were the Black Sea corridor to close again, how far does wheat run?",   # 3-word subject
    "Were a second La Nina to land, what breaks first?",
    "Were the West African crop to fail, where does cocoa trade?",           # 4-word subject (the cap)
    "Were Argentina to drop its export tax, how much crush shifts?",         # 1 word: the OLD branch
    "What would a full Hormuz closure do to fertilizer prices?",
]

_CF_NEAR_MISS_NEGATIVES = [
    "Assumption of a 5 percent yield loss is baked in already.",             # 'assume' is word-bounded
    "Assumptions about the levy are doing the work here.",
    "The imagined shortfall never materialised.",                           # 'imagine' is word-bounded
    "Traders say the crop is short.",                                       # 'say <det>' is anchored
    "What do the balance sheets say the market needs?",
    "What yield does the WASDE assume for Brazil?",                         # 'assume' is anchored
    "It is hard to imagine palm below 3500 ringgit.",                       # 'imagine' is anchored
    # the real eval-deck row (eval_queries_v3.yaml::c_coffee_2014_state) the unguarded multi-word
    # subject matched -- 'close to <determiner>' is a comparison, never a subjunctive
    "As known in mid-2014, given the observed ENSO state, were the convergence conditions close to "
    "the convergence set?",
    "Chinese purchases were the largest ever relative to the 5-year average.",
    "What would you do to hedge a short gamma book here?",                  # advice, not a scenario
    "Were all of the west african mid crop cocoa volumes to fall, what then?",   # subject over the cap
]


@pytest.mark.parametrize("q", _CF_NEW_CUE_POSITIVES)
def test_widened_counterfactual_cues_fire(q):
    assert it.select_response_contract(q) == "counterfactual"


@pytest.mark.parametrize("q", _CF_NEAR_MISS_NEGATIVES)
def test_counterfactual_near_misses_do_not_fire(q):
    assert it.select_response_contract(q) != "counterfactual", f"over-wide cue matched: {q!r}"


def test_both_real_store_counterfactual_rows_now_select_counterfactual():
    """The deck's only two REAL user counterfactual questions (source: store). Before D-UX-5 both fell
    open to default -- 'what would <X> do to <Y>' and a leading \"let's say\" were unmatched cues."""
    rows = {r["id"]: r for r in _ROWS if r["source"] == "store" and r["rc_expected"] == "counterfactual"}
    assert set(rows) == {"st_russia_wheat_policy", "st_cocoa_civ_cascade"}
    for rid, row in sorted(rows.items()):
        assert it.select_response_contract(row["question"]) == "counterfactual", rid


# Per-stratum hit FLOORS measured by scripts/router_deck_audit.py right after the widening. The
# counterfactual floor is the RISE (9/18 -> 17/18; sy_cf_08 is the deck's flagged-ambiguous
# conditional-mechanism row and is deliberately still open). Every other floor is the PRE-widening
# number unchanged -- "no other stratum may fall" is exactly a floor, and a floor never reds on a
# later legitimate improvement.
_STRATUM_FLOORS = {
    "counterfactual": 17, "verification": 9, "horizon": 7, "enumeration": 13,
    "ranking": 7, "compare": 10, "recency": 10, "context_node": 7, "default": 39,
}


def test_no_stratum_falls_and_counterfactual_rises():
    aud = _audit()
    scored = [aud.score_row(r) for r in _ROWS]
    hits = {name: sum(1 for s in scored if s["stratum"] == name and s["ok"])
            for name in _STRATUM_FLOORS}
    low = {n: (hits[n], f) for n, f in _STRATUM_FLOORS.items() if hits[n] < f}
    assert not low, f"stratum regression (got, floor): {low}"
    assert hits["counterfactual"] >= 17 > 9                     # the D-UX-5 rise, not just a hold


# ── the Phase-C A/B deck: ZERO selector drift ────────────────────────────────────────────────────────
# The 25-row no-tautology deck the D-RC Phase-C judged A/B ran on lives in S3
# (leviathan-dev-shahem-001 graphrag_evidence/eval/decks/eval_queries_contracts_ab_v1.yaml) and, when
# present, at configs/graphrag/ -- which is gitignored, so the deck cannot be a test dependency. The
# expected column below was captured by running select_response_contract on every row BEFORE the
# D-UX-5 edit; the pin therefore asserts pre/post identity even in a clone with no deck. When the deck
# IS present the questions are cross-checked against it, so the pin cannot rot silently.
_AB_DECK = _CFG / "eval_queries_contracts_ab_v1.yaml"
_AB_PRE_DUX5 = [
    ("ab_verif_palm_levy", "Palm's strength this year is mostly down to Indonesia's export levy changes, right?", "verification"),
    ("ab_verif_cocoa_disease", "I keep hearing swollen shoot virus has already cut Ivorian output by a fifth. Is that documented, or is it trade talk?", "verification"),
    ("ab_verif_wheat_premise", "Russia's wheat crop failed this year, isn't it? That's what the rally is.", "verification"),
    ("ab_cf_india_rice", "What if India banned rice exports again tomorrow -- what does that do to CBOT rough rice?", "counterfactual"),
    ("ab_cf_panama_canal", "Suppose the Panama Canal went down to half capacity for six months. How would US corn exports wear that?", "counterfactual"),
    ("ab_cf_brl_deval", "What would happen if the real devalued 30% -- does Brazilian selling bury CBOT beans?", "counterfactual"),
    ("ab_enum_arg_tax", "Has Argentina ever hiked its soybean export tax mid-crisis, and what did the market do?", "enumeration"),
    ("ab_enum_sugar_brazil", "When has Brazil's ethanol policy pulled cane away from sugar production before?", "enumeration"),
    ("ab_enum_cotton_china", "Every time China has released state cotton reserves, how did prices react?", "enumeration"),
    ("ab_rank_cocoa_origin", "Who supplies most of the world's cocoa these days, and by how much?", None),
    ("ab_rank_wheat_importers", "Which countries are the biggest wheat importers right now?", "ranking"),
    ("ab_cmp_vegoils", "Soyoil versus palm into year-end -- which one has the tighter story?", "compare"),
    ("ab_cmp_wheat_classes", "How do KC and Chicago wheat stack up against each other at these levels?", "compare"),
    ("ab_cmp_coffee", "Compare arabica and robusta fundamentals for me.", "compare"),
    ("ab_ctx_ddg", "Does DDG pricing matter for corn at all?", "context_node"),
    ("ab_ctx_sunflower", "Does sunflower oil move the other vegoils, or is it too small to matter?", "context_node"),
    ("ab_rec_blacksea", "What's the latest on the Black Sea corridor -- anything I should know from the past month?", "recency"),
    ("ab_rec_malaysia_stocks", "Where are Malaysian palm stocks sitting right now versus normal?", "recency"),
    ("ab_mech_kc_spread", "Why does the KC-Chicago spread blow out in drought years?", None),
    ("ab_mech_crush", "Walk me through how the crush margin transmits a meal rally into bean demand.", None),
    ("ab_mech_frost", "What makes a July frost in Minas so much worse than a September one?", None),
    ("ab_out_cotton", "Where do cotton prices go from here into Q1?", None),
    ("ab_amb_elnino", "How worried should I be about this El Nino for my softs book?", None),
    ("ab_ar_wheat", "ما هي أهم العوامل التي تحرك أسعار القمح حالياً؟", None),
    ("ab_pt_soy", "Como a seca no Rio Grande do Sul costuma afetar os precos da soja em Chicago?", None),
]


@pytest.mark.parametrize("rid,q,want", _AB_PRE_DUX5, ids=[r[0] for r in _AB_PRE_DUX5])
def test_ab_deck_selector_zero_drift(rid, q, want):
    assert it.select_response_contract(q) == want, f"{rid}: A/B deck selection drifted"


def test_ab_deck_pin_matches_the_real_deck_when_it_is_present():
    if not _AB_DECK.exists():
        pytest.skip("contracts A/B deck is gitignored/S3-side and absent from this clone")
    rows = (yaml.safe_load(_AB_DECK.read_text(encoding="utf-8")) or {}).get("queries") or []
    live = {r["id"]: " ".join((r["question"] or "").split()) for r in rows}
    pinned = {rid: " ".join(q.split()) for rid, q, _w in _AB_PRE_DUX5}
    assert live == pinned, "the A/B deck moved -- re-capture the pre-change selections, do not retro-fit"
