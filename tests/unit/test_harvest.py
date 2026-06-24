"""Phase-1 harvest tests — pure functions + the two-level prune (no network/spend)."""
from __future__ import annotations

import collections

from leviathan.graphrag import harvest as h


def test_guess_type():
    assert h._guess_type("stripe rust") == "hazard"
    assert h._guess_type("fall armyworm") == "hazard"
    assert h._guess_type("EUDR") == "policy_event"
    assert h._guess_type("Madden-Julian Oscillation") == "climate_driver"
    assert h._guess_type("flowering") == "state_marker"
    assert h._guess_type("crush margin") == "instrument"
    assert h._guess_type("Mato Grosso do Sul") == "unknown"


def test_build_matcher_recognizes_forms():
    m = h.build_matcher(["stem rust", "drought", "soybean rust"])
    found = m.findall("A severe drought and stem rust hit the crop.")
    assert set(found) == {"drought", "stem rust"}
    assert "soybean rust" not in found                      # absent → no false hit


def test_build_matcher_is_accent_and_case_insensitive():
    m = h.build_matcher(["café", "La Niña", "drought"])
    # text written WITHOUT accents / different case still matches the accented canonical form, and vice versa
    found = m.findall("CAFE prices jumped after the La Nina drought.")
    assert set(found) == {"café", "La Niña", "drought"}     # findall returns the ORIGINAL surface forms
    assert m.search("LA NIÑA") and not m.search("nothing relevant here")
    assert "scafé" not in m.findall("a scafé latte")        # word boundary still holds on normalized text


def test_build_matcher_empty_is_falsy():
    m = h.build_matcher(["a", ""])                          # all forms too short / empty
    assert not m and m.findall("anything") == [] and m.search("anything") is False


def test_prune_two_level_keeps_absent_concept_parks_redundant_alias():
    concepts = {
        "drought": {"type": "hazard", "forms": ["drought", "dryness", "moisture deficit"]},
        "stem_rust": {"type": "hazard", "forms": ["stem rust", "black rust"]},   # 0-hit lone concept
    }
    hits = collections.Counter({"drought": 12, "dryness": 3, "moisture deficit": 0,
                                "stem rust": 0, "black rust": 0})
    v = h.prune_two_level(concepts, hits)
    # redundant 0-hit alias of a COVERED concept → parked
    assert v["drought"]["forms"]["moisture deficit"] == "park"
    assert v["drought"]["forms"]["drought"] == "accept"
    # a 0-hit concept with NO hitting form → every form KEPT (never removed for absence)
    assert v["stem_rust"]["covered"] is False
    assert all(s == "accept" for s in v["stem_rust"]["forms"].values())


def test_mine_extractions_reads_friction_tail(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "_OUT", tmp_path)
    (tmp_path / "friction_report.md").write_text(
        "## Top unmapped entities\n- 7x `peanut (commodity)`\n- 3x `EUDR (policy_event)`\n", encoding="utf-8")
    out = h.mine_extractions()
    assert out["unmapped"]["peanut"] == 7 and out["unmapped"]["EUDR"] == 3   # type-suffix stripped


def test_research_seed_loads_and_is_typed():
    seed = h._seed()
    assert "soybean_rust" in (seed.get("hazard") or {})        # the gap the research filled
    assert "EUDR" in (seed.get("policy_event") or {})
    assert "MJO" in (seed.get("climate_driver") or {})
