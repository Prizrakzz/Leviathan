"""D-CC-1: the composition mandates (rank-complete / threshold-locate / episode-coverage) + the
deterministic census that drives them.

The wave's premise, restated as pins: D-DV-2 proved the binding constraint is COMPOSITION, and the
judge named the three gaps verbatim. Each mandate is therefore pinned on four properties, not one --
it FIRES on the right contracts, it NAMES what the turn actually holds, it carries an "or say the
record can't" ending, and it is PAID FOR by the word budget. Plus the two structural guarantees the
whole lever rests on:

  * census=None is byte-identical to the pre-D-CC module on every path (the composition lever has its
    own off state, so ONE image serves both D-CC-3 arms and the contract-alone control), proven at
    the function seam AND end-to-end on a captured serving prompt;
  * the three persona needles still exist and are still rewritten with a census in hand -- a mandate
    that silently stopped rewriting would ship an appended directive CONTRADICTING the fixed-four
    mandate, which is D-RC-8's named #1 failure mode.

Hermetic: no API, no S3, no DB.
"""
from __future__ import annotations

import pytest

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag import response_contracts as rc
from leviathan.graphrag import tracekeys as tk

_BASE = an._SYSTEM_MENTOR
# The escape branch, per mandate: the exact phrase the model is given as a first-class ending.
_ESCAPES = ("no dated row at the as-of", "does not locate a switch point",
            "no citable item inside that window")


def _census(**kw) -> dict:
    c = {"entities": (), "n_entities": 0, "n_episode_windows": 0, "n_evidence": 0}
    c.update(kw)
    return c


def _named(n: int) -> dict:
    ents = tuple(f"Origin{i}" for i in range(n))
    return _census(entities=ents, n_entities=n)


# == 1. the fail-open guarantee: census=None changes nothing, anywhere ================================
@pytest.mark.parametrize("name", sorted(rc.valid_names()) + [None, "no_such_contract"])
def test_census_none_is_byte_identical_on_both_seams(name):
    assert rc.apply(_BASE, name, census=None) == rc.apply(_BASE, name)
    assert rc.directive(name, census=None) == rc.directive(name)
    assert rc.composition(name, None) == ""


@pytest.mark.parametrize("name", [None, rc.DEFAULT, "outlook", "no_such_contract"])
def test_default_passthrough_unknown_stay_empty_even_with_a_full_census(name):
    """The D-RC-1 fail-open law is NOT relaxed by D-CC: a selector-miss turn is still byte-identical,
    census or no census. (Consequence, recorded in the module: the two D-DV-2 width rows that produced
    the 'never locates the convexity threshold' verdict select nothing and so cannot be reached by
    threshold-locate without a selector change -- which this wave does not make.)"""
    full = _census(entities=("A", "B", "C"), n_entities=3, n_episode_windows=4, n_evidence=9)
    assert rc.directive(name, census=full) == rc.directive(name)
    assert rc.apply(_BASE, name, census=full) == rc.apply(_BASE, name)


def test_a_malformed_census_yields_no_mandate_rather_than_a_broken_one():
    for bad in ({"entities": None, "n_entities": "seven"}, {"entities": ("", "  ")}, {}):
        assert rc.composition("ranking", bad) == ""
    assert rc.composition("enumeration", {"n_episode_windows": "many"}) == ""


# == 2. rank-complete =================================================================================
def test_rank_complete_fires_only_on_the_ranking_families():
    assert rc.RANK_COMPLETE == frozenset({"ranking", "compare"})
    for name in rc.valid_names():
        got = "RANK-COMPLETE" in rc.composition(name, _named(4))
        assert got is (name in rc.RANK_COMPLETE), name


@pytest.mark.parametrize("n,fires", [(0, False), (1, False), (2, True), (5, True)])
def test_rank_complete_needs_at_least_two_names(n, fires):
    """A one-name roster is not a list -- mandating a 'full ranked list' over it would order the model
    to pad, which is the failure the mandate exists to prevent."""
    assert ("RANK-COMPLETE" in rc.composition("ranking", _named(n))) is fires


def test_rank_complete_names_the_count_and_the_roster_and_the_escape():
    out = rc.composition("ranking", _census(entities=("Argentina", "Russia", "Ukraine"), n_entities=3))
    assert "carries 3 candidate names -- Argentina, Russia, Ukraine." in out
    assert "no dated row at the as-of" in out                      # the MANDATORY escape wording
    assert "left out silently" in out                              # non-members are dropped, not ranked
    assert "Never extend the list with a name the evidence does not carry" in out


def test_rank_complete_truncates_the_roster_but_never_the_count():
    n = rc.MAX_NAMED_ENTITIES + 5
    out = rc.composition("ranking", _named(n))
    assert f"carries {n} candidate names" in out                    # the TRUE count is always stated
    assert out.count("Origin") == rc.MAX_NAMED_ENTITIES             # ...only the names are capped
    assert "and 5 more named in the evidence above" in out


def test_rank_complete_states_the_true_count_when_the_roster_was_capped_upstream():
    """answer._composition_census caps `entities` at 40 and keeps `n_entities` true; the clause must
    read the count, never len(entities)."""
    out = rc.composition("ranking", _census(entities=tuple(f"C{i}" for i in range(40)), n_entities=137))
    assert "carries 137 candidate names" in out and "and 125 more named in the evidence above" in out


# == 3. threshold-locate ==============================================================================
def test_threshold_locate_fires_only_on_the_mechanism_families():
    assert rc.THRESHOLD_LOCATE == frozenset({"counterfactual", "compare"})
    for name in rc.valid_names():
        got = "THRESHOLD-LOCATE" in rc.composition(name, _census(n_evidence=6))
        assert got is (name in rc.THRESHOLD_LOCATE), name


def test_threshold_locate_binds_to_the_evidence_count_and_keeps_both_endings():
    out = rc.composition("counterfactual", _census(n_evidence=11))
    assert "the 11 evidence item(s) and number row(s) this turn holds" in out
    assert "the record does not locate a switch point here" in out
    assert "ONLY two endings" in out and "is a fabrication" in out


def test_threshold_locate_on_an_empty_turn_still_offers_the_escape_and_names_no_count():
    out = rc.composition("counterfactual", _census(n_evidence=0))
    assert "the record you were shown" in out and "0 evidence" not in out
    assert "does not locate a switch point" in out


# == 4. episode-coverage ==============================================================================
def test_episode_coverage_rides_the_episodes_license_not_a_second_list():
    """One authority: the contract that owns '## Episodes' owns the mandate to fill it."""
    for name in rc.valid_names():
        got = "EPISODE-COVERAGE" in rc.composition(name, _census(n_episode_windows=3))
        assert got is rc.licenses_episodes(name), name


@pytest.mark.parametrize("n,fires", [(0, False), (1, True), (7, True)])
def test_episode_coverage_needs_an_actually_injected_window(n, fires):
    out = rc.composition("enumeration", _census(n_episode_windows=n))
    assert ("EPISODE-COVERAGE" in out) is fires
    if fires:
        assert f"{n} dated episode window(s) were injected" in out
        assert "no citable item inside that window" in out         # the declared-omission branch


# == 5. every mandate carries an "or say the record can't" branch =====================================
def test_every_mandate_has_an_escape_branch():
    fired = {"ranking": rc.composition("ranking", _named(4)),
             "counterfactual": rc.composition("counterfactual", _census(n_evidence=3)),
             "enumeration": rc.composition("enumeration", _census(n_episode_windows=2))}
    for name, text in fired.items():
        assert text, name
        assert any(e in text for e in _ESCAPES), f"{name}: no refusal-honest branch"


def test_mandate_text_is_ascii_only():
    """Prompt bytes AND stdout bytes: the console is cp1252 and persona dumps are printed."""
    for text in (rc.rank_complete_clause(("A", "B"), 2), rc.threshold_locate_clause(4),
                 rc.episode_coverage_clause(3)):
        text.encode("ascii")


def test_mandates_are_appended_after_the_contracts_own_directive():
    """Order is load-bearing: the mandate reads as the specific obligation of a shape the directive
    has already described, never as a competing instruction ahead of it."""
    out = rc.directive("ranking", census=_named(4))
    assert out.startswith(rc.CONTRACTS["ranking"].directive)
    assert out.index("RANKING EMPHASIS") < out.index("RANK-COMPLETE")


def test_compare_carries_both_mandates_in_a_stable_order():
    out = rc.composition("compare", _census(entities=("A", "B", "C"), n_entities=3, n_evidence=8))
    assert out.index("RANK-COMPLETE") < out.index("THRESHOLD-LOCATE")


# == 6. the budget arithmetic that pays for the mandate ===============================================
@pytest.mark.parametrize("n,want", [(0, "90-160"), (2, "90-160"), (3, "90-160"), (4, "104-174"),
                                    (8, "160-230"), (14, "244-314"), (15, "250-320"), (99, "250-320")])
def test_rank_complete_widens_the_budget_by_the_documented_arithmetic(n, want):
    """extra = min(160, 14 * max(0, n - 3)), applied to BOTH ends. n<=3 is free (every ranking-family
    contract already budgets a few ranked lines); the cap binds from n=15."""
    out = rc.apply(_BASE, "ranking", census=_named(n))
    assert f"target {want} words across the 3 sections" in out


def test_only_the_rank_complete_families_widen():
    for name in ("counterfactual", "enumeration", "recency", "verification", "horizon"):
        assert rc.apply(_BASE, name, census=_named(9)) == rc.apply(_BASE, name, census=_named(0))


def test_mode_scale_then_census_widening_compose_in_that_order():
    """D-AM-10 scales the range multiplicatively and hands the SCALED phrase in; D-CC-1 then adds
    words. The order is documented on apply() because it compounds."""
    out = rc.apply(_BASE, "ranking", budget="60-110", census=_named(8))
    assert "target 130-180 words" in out                            # 60-110 + 14*(8-3) = 70


def test_widen_budget_fails_open_on_an_unparseable_range():
    assert rc.widen_budget("about a page", 9) == "about a page"
    assert rc.widen_budget("", 9) == ""
    assert rc.widen_budget("90-160", 2) == "90-160"                 # nothing to buy -> untouched


# == 7. the needles: still present, still rewritten WITH a census in hand =============================
def test_the_three_needles_still_exist_byte_for_byte():
    for needle in (rc.NEEDLE_STRUCTURE, rc.NEEDLE_BUDGET, rc.NEEDLE_FIELDLIST):
        assert needle in an._SYSTEM_MENTOR, f"persona needle drifted: {needle[:60]}..."


@pytest.mark.parametrize("name", ["ranking", "compare", "counterfactual", "enumeration"])
def test_all_three_sites_are_still_rewritten_under_a_census(name):
    out = rc.apply(_BASE, name, census=_census(entities=("A", "B", "C"), n_entities=3,
                                               n_episode_windows=2, n_evidence=7))
    for needle in (rc.NEEDLE_STRUCTURE, rc.NEEDLE_BUDGET, rc.NEEDLE_FIELDLIST):
        assert needle not in out
    assert "structured under the '## ' headings above" in out


# == 8. answer.py: the deterministic census ===========================================================
def _calls(*specs) -> list:
    """Numbers-agent call records in the shipped shape ({query, rows, status})."""
    out = []
    for scope, row_countries in specs:
        out.append({"query": {"table": "silver_psd", "metric": "exports", "country": scope},
                    "rows": [{"country": c, "value": 1} for c in row_countries], "status": "ok"})
    return out


def test_census_reads_countries_from_both_the_query_scope_and_the_rows():
    c = an._composition_census(contracts=["srw_wheat"], number_calls=_calls(("Russia", ["Ukraine", "India"])),
                               trace={}, n_evidence=5)
    assert c["entities"] == ("India", "Russia", "Ukraine", "srw_wheat")
    assert c["n_entities"] == 4 and c["n_evidence"] == 5


def test_census_is_deterministic_and_deduped_countries_sorted_contracts_in_walk_order():
    """Identical turns must produce identical prompt bytes (the prompt-cache discipline)."""
    calls = _calls(("Russia", ["India", "Russia"]), (None, ["India", "Ukraine"]))
    a = an._composition_census(contracts=["b_contract", "a_contract"], number_calls=calls,
                               trace={}, n_evidence=3)
    b = an._composition_census(contracts=["b_contract", "a_contract"], number_calls=list(reversed(calls)),
                               trace={}, n_evidence=3)
    assert a == b
    assert a["entities"] == ("India", "Russia", "Ukraine", "b_contract", "a_contract")


def test_census_survives_junk_rows_and_empty_inputs():
    assert an._composition_census(contracts=None, number_calls=None, trace=None, n_evidence=0) == {
        "entities": (), "n_entities": 0, "n_episode_windows": 0, "n_evidence": 0}
    junk = ["not-a-dict", {"query": "not-a-dict", "rows": ["nope", {"country": " "}]}]
    assert an._composition_census(contracts=[], number_calls=junk, trace={}, n_evidence=1)["entities"] == ()


def test_census_caps_the_roster_at_forty_and_keeps_the_true_count():
    calls = _calls((None, [f"C{i:03d}" for i in range(137)]))
    c = an._composition_census(contracts=[], number_calls=calls, trace={}, n_evidence=2)
    assert len(c["entities"]) == an._CENSUS_ENTITY_CAP and c["n_entities"] == 137


def test_episode_window_count_has_ONE_producer_shared_with_fork_basis():
    """The mandate that orders N windows enumerated and the flag that licenses the fork over them read
    the same function -- two derivations of one count is how they drift apart."""
    tr = {"episodes_injected": [{"spans": ["1994-06..1994-08", "1999-01..1999-03"]},
                                {"spans": [], "floored": True}, {"spans": ["2011-05..2011-07"]}]}
    assert an._n_episode_windows(tr) == 3
    assert an._n_episode_windows({}) == 0 and an._n_episode_windows(None) == 0
    assert an._fork_basis(None, [], [], tr)["episodes"] is True
    assert an._composition_census(contracts=[], number_calls=[], trace=tr,
                                  n_evidence=0)["n_episode_windows"] == 3


def test_composition_census_flag_grammar(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_COMPOSITION_CENSUS", raising=False)
    assert an._composition_census_on() is False                     # DEFAULT-OFF
    for v in ("on", "1", "TRUE", " on "):
        monkeypatch.setenv("GRAPHRAG_COMPOSITION_CENSUS", v)
        assert an._composition_census_on() is True, v
    for v in ("off", "", "yes"):
        monkeypatch.setenv("GRAPHRAG_COMPOSITION_CENSUS", v)
        assert an._composition_census_on() is False, v


def test_census_is_registered_so_it_reaches_the_eval_artifact():
    assert "composition_census" in tk.TRACE_RECORD_KEYS              # D-AM-3: registration IS the lift


# == 9. _system threading + the end-to-end captured-prompt identity ===================================
@pytest.mark.parametrize("name", sorted(rc.valid_names()) + [None])
def test_system_with_census_none_is_byte_identical(name, monkeypatch):
    monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
    assert an._system(response_contract=name, census=None) == an._system(response_contract=name)


def test_system_carries_the_mandate_when_a_census_is_threaded(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
    out = an._system(response_contract="ranking",
                     census=_census(entities=("India", "Russia"), n_entities=2))
    assert "RANK-COMPLETE" in out and "India, Russia" in out
    assert out.endswith(rc.composition("ranking", _census(entities=("India", "Russia"), n_entities=2)))


def _graph() -> g.CausalGraph:
    wheat = cs.CausalContract(
        contract="srw_wheat", aliases=["wheat"],
        drivers=[cs.Driver(id="export_ban", type="policy", sign="+", mechanism="bans cut shipments")])
    return g.CausalGraph({"srw_wheat": wheat}, silver=set())


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_gain_wheat", "source_key": f"s3://{node}",
             "text": "Russia raised the wheat export tax."}]


def _run(monkeypatch, seen: dict, *, contract="ranking", calls=None, planner="l2"):
    def fake_call(system, user, *, model, tool, **kw):
        seen["system"] = system
        return {"tldr": "t", "mechanism": "## Mechanism\nm\n\n## What to watch\nw",
                "diagram_mermaid": "", "sources": []}
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[1.0] for _ in texts])
    return an.answer("rank the wheat exporters by policy risk", graph=_graph(), planner=planner,
                     asof="2024-06-01", retrieve=_retrieve, call=fake_call,
                     route_fn=lambda q, gg: ["srw_wheat"], response_contract=contract,
                     extra_number_calls=calls)


_LIVE_CALLS = [{"query": {"table": "silver_psd", "metric": "exports", "country": "Russia"},
                "rows": [{"country": "Ukraine", "value": 1}, {"country": "India", "value": 2}],
                "status": "ok"}]


@pytest.mark.parametrize("planner", ["l2", "onehop"])
def test_flag_off_turn_is_byte_identical_to_the_pre_change_prompt(planner, monkeypatch):
    """PROVEN on the captured serving prompt, not asserted. The control replaces the census builder
    with a raiser: flag off, it is never called, and the prompt the model receives is the pre-D-CC
    prompt because nothing else in either body moved."""
    monkeypatch.setenv("GRAPHRAG_RESPONSE_CONTRACT", "on")
    monkeypatch.delenv("GRAPHRAG_COMPOSITION_CENSUS", raising=False)
    live: dict = {}
    out = _run(monkeypatch, live, calls=_LIVE_CALLS, planner=planner)
    monkeypatch.setattr(an, "_composition_census",
                        lambda **kw: pytest.fail("census computed on a dark turn"))
    control: dict = {}
    _run(monkeypatch, control, calls=_LIVE_CALLS, planner=planner)
    assert live["system"] == control["system"]
    assert "RANK-COMPLETE" not in live["system"]
    assert "composition_census" not in out["trace"]                 # OFF-arm trace stays clean
    assert out["trace"]["response_contract"] == "ranking"           # ...and the turn WAS susceptible


@pytest.mark.parametrize("planner", ["l2", "onehop"])
def test_flag_on_turn_shapes_the_prompt_from_what_the_turn_actually_holds(planner, monkeypatch):
    monkeypatch.setenv("GRAPHRAG_RESPONSE_CONTRACT", "on")
    monkeypatch.setenv("GRAPHRAG_COMPOSITION_CENSUS", "on")
    seen: dict = {}
    out = _run(monkeypatch, seen, calls=_LIVE_CALLS, planner=planner)
    cen = out["trace"]["composition_census"]
    assert cen["entities"] == ("India", "Russia", "Ukraine", "srw_wheat")
    assert cen["n_entities"] == 4 and cen["n_evidence"] >= 1
    assert "carries 4 candidate names -- India, Russia, Ukraine, srw_wheat." in seen["system"]
    assert "no dated row at the as-of" in seen["system"]
    assert "target 104-174 words" in seen["system"]                 # the budget paid for the 4th line


def test_the_l2_seam_censuses_the_RENDERED_contract_set_not_just_the_seeds():
    """D-DV-1c, re-applied: _l2_blocks renders a block for EVERY walk contract, hops included, so a
    seeds-only census would bind the mandate to a strict subset of what the model was shown. Pinned at
    the source seam because a two-seed walk is the only turn where the two spellings differ."""
    import inspect
    body = inspect.getsource(an._answer_l2)
    assert "_composition_census(contracts=sorted({n.contract for n in sg.nodes})" in body
    assert "_composition_census(contracts=contracts" not in body


def test_the_census_cannot_read_the_answer_it_shapes():
    """The circularity fence as an ORDERING invariant (the fork_basis precedent, V.4 X3): the census
    is minted before the model call in both bodies and its builder cannot see `structured` at all."""
    import inspect
    src = inspect.getsource(an._composition_census)
    assert "structured" not in src and "mechanism" not in src
    for body, mint in ((an._answer_l2, "_composition_census("), (an.answer, "_composition_census(")):
        text = inspect.getsource(body)
        assert text.index(mint) < text.index("structured = call("), body.__name__


def test_flag_on_with_nothing_to_say_is_still_byte_identical(monkeypatch):
    """A census that fires no mandate must not move a single byte: the lever is width-driven, so a
    lean turn on a non-ranking contract is the same prompt with the flag either way."""
    monkeypatch.setenv("GRAPHRAG_RESPONSE_CONTRACT", "on")
    monkeypatch.delenv("GRAPHRAG_COMPOSITION_CENSUS", raising=False)
    off: dict = {}
    _run(monkeypatch, off, contract="recency")
    monkeypatch.setenv("GRAPHRAG_COMPOSITION_CENSUS", "on")
    on: dict = {}
    out = _run(monkeypatch, on, contract="recency")
    assert off["system"] == on["system"]
    assert out["trace"]["composition_census"]["n_entities"] == 1     # the census ran and stamped
