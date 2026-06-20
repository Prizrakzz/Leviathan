"""Phase 1.5 — commodity hierarchy / concept-expansion tests.

The motivating case: "effect of El Niño on all wheat contracts" must expand to the four wheat class
nodes (so the cascade runs per class and divergences are surfaced), not collapse to one `wheat` answer.
"""
from __future__ import annotations

from leviathan.graphrag import hierarchy as h


def test_wheat_complex_expands_to_class_nodes():
    r = h.expand_concept("wheat")
    assert r.kind == "complex"
    assert set(r.nodes) == {"hrw_wheat", "hrs_wheat", "srw_wheat", "french_wheat"}
    assert r.multi and r.policy == "enumerate_divergent"
    # the four tradeable wheat contracts come back as the instruments
    assert {"hard_red_winter_wheat_kcbt", "hard_red_spring_wheat_mgex",
            "soft_red_winter_wheat_cbot", "french_wheat_matif"} <= set(r.contracts)


def test_brazilian_corn_resolves_to_corn_node_with_origin():
    assert h.contract_to_node("campinas_corn_reference_bmf") == ("corn", "Brazil")
    assert h.contract_to_node("corn_cbot") == ("corn", "United_States")


def test_bare_commodity_name_expands_to_all_its_contracts():
    # "corn" is a node (not a suffixed slug) → one causal node, all three origin contracts.
    r = h.expand_concept("corn")
    assert r.kind == "node" and not r.multi and r.policy == "benchmark"
    assert set(r.contracts) == {"corn_cbot", "campinas_corn_reference_bmf", "french_maize_matif"}
    # arabica node → both the ICE and BMF contracts.
    assert set(h.expand_concept("arabica_coffee").contracts) == {"arabica_coffee",
                                                                  "brazilian_arabica_coffee"}


def test_position_slug_resolves_to_single_instrument():
    r = h.expand_concept("soft_red_winter_wheat_cbot")
    assert r.kind == "contract" and r.nodes == ("srw_wheat",) and not r.multi


def test_canola_and_rapeseed_distinct_but_share_complex():
    assert h.expand_concept("canola").nodes == ("canola",)
    assert h.expand_concept("rapeseed").nodes == ("rapeseed",)
    members = set(h.members_of_complex("rapeseed_complex"))
    assert {"canola", "rapeseed"} <= members


def test_group_expansion():
    nodes = set(h.expand_concept("oilseeds").nodes)
    assert {"soybeans", "canola", "rapeseed"} <= nodes


def test_unknown_concept_abstains():
    r = h.expand_concept("platinum")
    assert r.kind == "unknown" and r.policy == "abstain" and r.nodes == ()


def test_coverage_is_clean():
    assert h.coverage_check() == []


def test_all_31_contracts_map_to_real_nodes():
    nodes = h._vocab_nodes()
    for slug in h.ALL_CONTRACTS:
        mapped = h.contract_to_node(slug)
        assert mapped is not None, f"{slug} unmapped"
        assert mapped[0] in nodes, f"{slug} → {mapped[0]} not a vocab node"
