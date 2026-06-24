"""Causal-ontology authoring — mocked unit tests (no network/spend)."""
from __future__ import annotations

from leviathan.causal import author as au
from leviathan.causal import schema as cs


def test_match_silver_token_overlap():
    assert au._match_silver("brazil_frost", {"frost_risk", "price"}) == "frost_risk"
    assert au._match_silver("la_nina_event", {"oni_la_nina_brazil_flag", "price"}) == "oni_la_nina_brazil_flag"
    assert au._match_silver("totally_novel", {"price", "frost_risk"}) is None


def test_tokens_strips_accents_and_case():
    assert au._tokens("La Niña café") == {"nina", "cafe"}      # accents folded, 'la' (len 2) dropped
    assert au._match_silver("La Niña", {"oni_la_nina_brazil_flag", "price"}) == "oni_la_nina_brazil_flag"


def test_complex_neighbours():
    h = {"complexes": {"coffee": ["arabica_coffee", "robusta_coffee"],
                       "soy_complex": ["soybeans", "soybean_meal", "soybean_oil"]}}
    assert au._complex_neighbours("arabica_coffee", h) == ["robusta_coffee"]
    assert au._complex_neighbours("soybeans", h) == ["soybean_meal", "soybean_oil"]
    assert au._complex_neighbours("corn", h) == []


def test_causal_tool_shape():
    t = au._causal_tool()
    props = t["input_schema"]["properties"]
    assert t["name"] == "emit_causal_dag"
    assert {"drivers", "inter_commodity", "convergence", "target_metrics"} <= set(props)
    assert "sign" in props["drivers"]["items"]["properties"]


def test_seed_smoke(monkeypatch):
    monkeypatch.setattr(au.ex, "_vocab", lambda: {
        "nodes": {"hazard": ["brazil_frost", "coffee_rust"], "climate_driver": ["la_nina"]},
        "aliases": {"arabica_coffee": ["arabica", "KC"]}, "edges": {"causes": {}, "affects_yield_of": {}}})
    monkeypatch.setattr(au.cval, "available_silver", lambda: {"frost_risk", "oni_la_nina_brazil_flag", "price"})
    sk = au.seed("arabica_coffee")                       # reads the real (present) commodity_hierarchy.yaml
    ids = {d["id"]: d for d in sk["driver_candidates"]}
    assert {"brazil_frost", "coffee_rust", "la_nina"} <= set(ids)
    assert ids["brazil_frost"]["silver_ref"] == "frost_risk" and ids["brazil_frost"]["silver_status"] == "available"
    assert ids["coffee_rust"]["silver_status"] == "none"             # no matching silver
    assert sk["aliases"] == ["arabica", "KC"]
    assert any(e["driver_commodity"] == "robusta_coffee" for e in sk["inter_commodity_candidates"])


def test_sanitize_drops_dangling_refs_and_extras():
    """The model sometimes names a parent / convergence driver it forgot to declare, adds stray keys, or
    emits bad enums (the real `IOD_negative` failure). _sanitize must make the dict schema-constructible."""
    out = {"drivers": [
        {"id": "frost", "type": "hazard", "sign": "+", "mechanism": "kills trees",
         "parents": ["IOD_negative", "frost"], "silver_status": "bogus", "confidence": "certain",
         "stray_key": "drop me"},                                  # dangling parent + self-parent + junk
        {"id": "drought", "type": "hazard", "sign": "??", "mechanism": "dries cherries",
         "silver_ref": "soil_moisture_z"},                        # bad sign coerced; silver_ref -> available
        {"id": "no_mech", "type": "hazard", "sign": "+"}]}         # missing mechanism -> dropped entirely
    out["convergence"] = [
        {"name": "squeeze", "direction": "+", "requires_any_n_of": 9,
         "drivers": ["frost", "drought", "ghost"],                # 'ghost' undeclared -> pruned; n clamped to 2
         "interactions": [{"when": ["frost", "ghost"], "effect": "boom"}]},
        {"name": "dead", "direction": "+", "drivers": ["ghost"]}]  # all drivers ghost -> whole signal dropped
    out["inter_commodity"] = [{"driver_commodity": "robusta_coffee", "relation": "substitutes_for", "sign": "x"}]

    clean = au._sanitize(out)
    ids = {d["id"] for d in clean["drivers"]}
    assert ids == {"frost", "drought"}                            # no_mech dropped
    frost = next(d for d in clean["drivers"] if d["id"] == "frost")
    assert frost["parents"] == [] and "stray_key" not in frost    # dangling + self parent + junk gone
    assert frost["silver_status"] == "none" and frost["confidence"] == "medium"
    drought = next(d for d in clean["drivers"] if d["id"] == "drought")
    assert drought["sign"] == "0" and drought["silver_status"] == "available"
    assert clean["inter_commodity"][0]["sign"] == "0"
    assert len(clean["convergence"]) == 1                         # 'dead' dropped
    sq = clean["convergence"][0]
    assert sq["drivers"] == ["frost", "drought"] and sq["requires_any_n_of"] == 2
    assert sq["interactions"][0]["when"] == ["frost"] and sq["interactions"][0]["effect"] == "amplifies"


def test_draft_assembles_valid_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(au, "_CAUSAL_DIR", tmp_path)              # don't write raw dump into real configs/
    dag = {"target_metrics": ["price"],
           "drivers": [{"id": "brazil_frost", "type": "hazard", "sign": "+", "mechanism": "kills trees",
                        "parents": [], "silver_ref": "frost_risk", "silver_status": "available"},
                       {"id": "la_nina", "type": "climate_driver", "sign": "+", "mechanism": "dry Brazil"}],
           "inter_commodity": [{"driver_commodity": "robusta_coffee", "relation": "substitutes_for", "sign": "-"}],
           "convergence": [{"name": "squeeze", "direction": "+", "requires_any_n_of": 1, "drivers": ["brazil_frost"]}]}

    class _Block:
        type = "tool_use"; input = dag

    class _Resp:
        content = [_Block()]; usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

    class _Client:
        messages = type("M", (), {"create": staticmethod(lambda **k: _Resp())})()

    seed_dict = {"aliases": ["arabica", "KC"], "target_metrics": ["price"], "edge_types": ["causes"],
                 "driver_candidates": [], "inter_commodity_candidates": [], "available_silver": ["frost_risk"]}
    c = au.draft(_Client(), "arabica_coffee", seed_dict)
    assert isinstance(c, cs.CausalContract)
    assert c.contract == "arabica_coffee" and c.driver_ids() == {"brazil_frost", "la_nina"}
    assert c.provenance["authored_by"] and c.convergence[0].name == "squeeze"
    assert (tmp_path / "arabica_coffee.raw.json").exists()       # paid draft persisted before validation
