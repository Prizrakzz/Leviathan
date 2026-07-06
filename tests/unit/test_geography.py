"""Geography routing index (5.8 W2) — hermetic: loader, resolver, origin-derive, config validation.
No network, no model, no graph load beyond a tiny fake."""
from __future__ import annotations

from leviathan.graphrag import geography as geo


class _FakeGraph:
    # a subset of real graph.contracts ids (causal DAG stems)
    contracts = {
        "rough_rice_cbot": 1, "cotton": 1, "raw_sugar": 1, "white_sugar": 1, "soybean_oil_cbot": 1,
        "malaysian_crude_palm_oil_cme": 1, "palm_olein_dce": 1, "hard_red_winter_wheat_kcbt": 1,
        "soybeans_cbot": 1, "corn_cbot": 1, "canola_ice": 1, "french_wheat_matif": 1,
    }


def test_check_geography_passes():
    assert geo.check_geography() == []


def test_resolve_country_word_boundary():
    assert geo.resolve_country("anything from the news on India?") == "india"
    assert geo.resolve_country("Black Sea wheat out of Russia and Ukraine") in ("russia", "ukraine")
    assert geo.resolve_country("Malaysian palm oil output") == "malaysia"
    # word-boundary: 'india' must NOT match inside 'indiana'; a bare commodity names no country
    assert geo.resolve_country("Indiana corn basis") is None
    assert geo.resolve_country("soybean crush margins") is None
    assert geo.resolve_country("") is None


def test_contracts_for_curated_plus_origin_derived_and_graph_filtered():
    c = geo.contracts_for("india", graph=_FakeGraph())
    # curated India contracts that exist in the fake graph
    assert "rough_rice_cbot" in c and "cotton" in c and "malaysian_crude_palm_oil_cme" in c
    # India has NO home contract (origin-derive yields nothing extra) — still fine
    assert all(x in _FakeGraph.contracts for x in c)      # graph filter drops anything unknown


def test_contracts_for_us_includes_origin_home_contracts():
    # United_States IS a hierarchy origin → origin-derive contributes home contracts (corn_cbot etc.)
    c = geo.contracts_for("united_states", graph=_FakeGraph())
    assert "corn_cbot" in c and "soybeans_cbot" in c


def test_drivers_and_country_ids():
    assert "inr_fx" in geo.drivers_for("india") and "monsoon" in geo.drivers_for("india")
    ids = geo.all_country_ids()
    assert "india" in ids and "china" in ids and "brazil" in ids and len(ids) >= 12
