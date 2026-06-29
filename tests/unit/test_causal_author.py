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


def test_policy_levers_filters_by_commodity(tmp_path, monkeypatch):
    p = tmp_path / "policy_levers.yaml"
    p.write_text(
        "levers:\n"
        "- name: china_state_reserves\n  country: China\n  type: state_reserve\n"
        "  commodities: [corn, soybeans]\n  note: auctions vs accumulation\n"
        "- name: india_export_ban\n  country: India\n  type: export_restriction\n"
        "  commodities: [sugar, wheat, rice]\n  note: ban\n"
        "- name: eudr\n  country: EU\n  type: import_restriction\n"
        "  commodities: [coffee, cocoa]\n  note: deforestation\n"
        "- name: global_tariffs\n  country: US\n  type: import_tariff\n"
        "  commodities: [all]\n  note: 301\n", encoding="utf-8")
    monkeypatch.setattr(au, "_POLICY_PATH", p)
    assert {l["name"] for l in au._policy_levers("corn")} == {"china_state_reserves", "global_tariffs"}
    assert {l["name"] for l in au._policy_levers("arabica_coffee")} == {"eudr", "global_tariffs"}  # token 'coffee'
    monkeypatch.setattr(au, "_POLICY_PATH", tmp_path / "missing.yaml")
    assert au._policy_levers("corn") == []                                # graceful when file absent


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


def test_sanitize_maps_direction_synonyms_and_filters_nodes():
    """The model writes 'bullish'/'bearish' not '+'/'-' and proposes inter-commodity edges outside our universe
    (crude_oil) — map the synonyms (don't silently drop convergence) and node-filter only when nodes are given."""
    out = {"drivers": [{"id": "frost", "type": "hazard", "sign": "bullish", "mechanism": "m"},
                       {"id": "big_crop", "type": "state_marker", "sign": "bearish", "mechanism": "m"}],
           "inter_commodity": [{"driver_commodity": "robusta_coffee", "relation": "substitutes_for", "sign": "down"},
                               {"driver_commodity": "crude_oil", "relation": "feedstock_for", "sign": "+"}],
           "convergence": [{"name": "squeeze", "direction": "bullish", "drivers": ["frost"]},
                           {"name": "glut", "direction": "bearish", "drivers": ["big_crop"]},
                           {"name": "muddle", "direction": "ambiguous", "drivers": ["frost"]}]}  # non-directional → drop

    clean = au._sanitize(out, nodes={"robusta_coffee"})
    assert {d["id"]: d["sign"] for d in clean["drivers"]} == {"frost": "+", "big_crop": "-"}   # sign synonyms
    assert [(e["driver_commodity"], e["sign"]) for e in clean["inter_commodity"]] == [("robusta_coffee", "-")]
    assert [(s["name"], s["direction"]) for s in clean["convergence"]] == [("squeeze", "+"), ("glut", "-")]

    clean_no_nodes = au._sanitize(out)                          # nodes=None → no node filtering, crude_oil survives
    assert {e["driver_commodity"] for e in clean_no_nodes["inter_commodity"]} == {"robusta_coffee", "crude_oil"}


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


def test_scaling_and_draft_order(tmp_path, monkeypatch):
    sc = tmp_path / "contract_scaling.yaml"
    sc.write_text("new: [cocoa, raw_sugar]\nvariants:\n  white_sugar: {base: raw_sugar, overlay: refined}\n",
                  encoding="utf-8")
    monkeypatch.setattr(au, "_SCALING_PATH", sc)
    new, variants = au._draft_order(done={"cocoa"})              # cocoa already done -> excluded
    assert new == ["raw_sugar"] and variants == ["white_sugar"]


def test_base_context_includes_base_yaml(tmp_path, monkeypatch):
    sc = tmp_path / "contract_scaling.yaml"
    sc.write_text("new: [raw_sugar]\nvariants:\n  white_sugar: {base: raw_sugar, overlay: refining premium}\n",
                  encoding="utf-8")
    monkeypatch.setattr(au, "_SCALING_PATH", sc)
    monkeypatch.setattr(au, "_CAUSAL_DIR", tmp_path)
    (tmp_path / "raw_sugar.yaml").write_text("contract: raw_sugar\ndrivers: []\n", encoding="utf-8")
    ctx = au._base_context("white_sugar")
    assert "BASE CONTRACT = raw_sugar" in ctx and "refining premium" in ctx and "contract: raw_sugar" in ctx
    assert au._base_context("cocoa") == ""                       # a 'new' commodity has no base context


def test_draft_threads_base_context_into_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(au, "_CAUSAL_DIR", tmp_path)
    captured = {}
    dag = {"target_metrics": ["price"], "drivers": [{"id": "x", "type": "hazard", "sign": "+", "mechanism": "m"}],
           "inter_commodity": [], "convergence": []}

    class _Block:
        type = "tool_use"; input = dag

    class _Resp:
        content = [_Block()]; usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

    def _create(**kw):
        captured["user"] = kw["messages"][0]["content"]
        return _Resp()

    class _Client:
        messages = type("M", (), {"create": staticmethod(_create)})()

    seed_dict = {"aliases": [], "target_metrics": ["price"], "edge_types": [], "driver_candidates": [],
                 "inter_commodity_candidates": [], "available_silver": [], "policy_candidates": []}
    au.draft(_Client(), "white_sugar", seed_dict, base_context="BASE CONTRACT = raw_sugar. OVERLAYS: refining premium")
    assert "BASE CONTRACT = raw_sugar" in captured["user"] and "OVERLAYS: refining premium" in captured["user"]
