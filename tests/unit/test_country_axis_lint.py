"""THE COUNTRY-AXIS NAMESPACE DIFF (B1 recon R4, ratified 2026-08-21) -- the standing lint that stops the
six country rosters drifting apart again.

WHY IT EXISTS, in the recon's own terms (R-7): six rosters spell a country in this estate --
``esr_destinations.yaml`` (211 FAS destination codes), ``numbers.agent._ESR_DESTINATIONS`` (the buyer-scope
guard's 38), ``geo_lexicon._COUNTRIES`` (the binding verifier's 34, and the only one that lives in ``src/``
so a worktree image cannot import it empty), ``entity_vocabulary.nodes.country_origin`` (the canonical
namespace), ``cascade_map.region_map.resolve`` (the cascade's labels) and ``geography.yaml`` (this router)
-- and **no lint compared any adjacent pair**. Adding destinations to some and not others makes the drift
worse, not better, which is why R4 was ratified as a PRECONDITION of the router/vocabulary extensions rather
than as a follow-on to them.

Every assertion here is offline config arithmetic: no S3, no Athena, no network, no spend. The tonnage
weighting -- the only form of the "27.4% of traded flow" headline that means anything -- is an OPTIONAL
argument, because a lint that needs a warehouse to run is a lint that gets switched off.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag import geography as gg


def _wire(monkeypatch, rosters: dict, codes: dict | None = None):
    """Drive country_axis_warnings() from a synthetic six-roster fixture. `codes` (the raw esr_destinations
    table) is only needed by the B1-headline leg, which reads kind/pseudo and the per-code surfaces."""
    base = {k: set() for k in ("esr_destinations", "agent", "geo_lexicon", "country_origin",
                               "region_map", "geography")}
    base.update({k: {gg._ca_norm(x) for x in v} for k, v in rosters.items()})
    monkeypatch.setattr(gg, "country_axis_rosters", lambda: base)
    if codes is not None:
        import yaml as _yaml

        class _P:                                              # a Path stand-in for the ONE read the leg does
            def read_text(self, encoding=None):                # noqa: ARG002
                return _yaml.safe_dump({"codes": codes})

        class _Dir:
            def __truediv__(self, other):                      # noqa: ARG002
                return self

            def read_text(self, encoding=None):                # noqa: ARG002
                return _yaml.safe_dump({"codes": codes})

        monkeypatch.setattr(gg, "_CFG", _Dir())


def test_the_census_line_names_all_six_rosters(monkeypatch):
    # The first line is the census itself. It is not decoration: five of the six rosters live in gitignored
    # configs and the sixth lives in src/, so "how big is each one today" is a number nothing else prints.
    _wire(monkeypatch, {"esr_destinations": ["Mexico", "Japan"], "agent": ["Mexico"],
                        "geo_lexicon": ["Mexico"], "country_origin": ["Mexico"],
                        "region_map": ["Mexico"], "geography": ["Mexico"]}, codes={})
    lines = gg.country_axis_warnings()
    assert lines and lines[0].startswith("country-axis namespace diff (B1 R4):")
    for roster in ("esr_destinations", "agent", "geo_lexicon", "country_origin", "region_map", "geography"):
        assert roster in lines[0]
    assert all(ln.encode("ascii") for ln in lines)             # cp1252 stdout rule


def test_a_buyer_the_scope_guard_detects_but_the_code_table_cannot_name(monkeypatch):
    # LEG 1, and the one with a live consequence. agent.py's ESR guard fires on a buyer-directional phrasing
    # and stamps a scope_note; if that buyer has no destination code, the guard has detected something the
    # numbers lane cannot resolve -- a national total presented as if it answered a destination-scoped ask,
    # which is the exact failure the guard exists to prevent.
    _wire(monkeypatch, {"esr_destinations": ["Mexico"], "agent": ["Mexico", "Atlantis"],
                        "country_origin": ["Mexico"]}, codes={})
    lines = gg.country_axis_warnings()
    assert any("agent->esr_destinations" in ln and "atlantis" in ln for ln in lines)


def test_the_russia_class_surfaces_as_a_finding_not_a_zero_row_join(monkeypatch):
    # LEGS 2+3, the measured live instance: the FAS table says "Russian Federation" and "South Africa,
    # Republic Of" while every other roster says "Russia" and "South Africa". Before this lint that mismatch
    # was a join returning nothing, which reads identically to a country with no trade.
    _wire(monkeypatch, {"esr_destinations": ["Russian Federation", "South Africa, Republic Of"],
                        "geo_lexicon": ["Russia", "South Africa"],
                        "country_origin": ["Russia", "South Africa"]}, codes={})
    lines = gg.country_axis_warnings()
    assert any("geo_lexicon->esr_destinations" in ln and "russia" in ln for ln in lines)
    assert any("country_origin->esr_destinations" in ln and "south africa" in ln for ln in lines)


def test_the_reporter_and_the_eu_synonym_are_recorded_refusals_not_findings(monkeypatch):
    # TWO suppressions, each written down rather than silent. (a) The United States is the ESR REPORTER and
    # numbers/agent.py states verbatim that it "is deliberately absent from the destination vocabulary" --
    # its absence is the schema being right. (b) esr_destinations code 1 declares BOTH "European Union" and
    # the alias "eu" for one bloc, so the canonical token `EU` and the display "European Union" are one
    # entity, measured from the table itself, not a guess.
    _wire(monkeypatch, {"esr_destinations": ["Mexico", "European Union"],
                        "country_origin": ["United_States", "EU", "Mexico"],
                        "geo_lexicon": ["European Union", "Mexico"]}, codes={})
    lines = gg.country_axis_warnings()
    assert not any("united states" in ln for ln in lines)
    assert not any("european union" in ln and "->" in ln for ln in lines)


def test_a_spelling_outside_the_canonical_namespace_is_flagged(monkeypatch):
    # LEG 4: the cascade labelling a country the graph is not keyed on. This is the drift that makes a
    # cascade narration unjoinable to a graph node -- silent, and invisible to every other lint.
    _wire(monkeypatch, {"esr_destinations": ["Turkiye"], "country_origin": ["Turkey"],
                        "region_map": ["Turkiye"], "geography": ["Turkey"]}, codes={})
    lines = gg.country_axis_warnings()
    assert any("region_map->country_origin" in ln and "turkiye" in ln for ln in lines)
    assert not any("geography->country_origin" in ln for ln in lines)


def test_the_b1_headline_counts_and_weighs_only_when_tonnage_is_supplied(monkeypatch):
    # LEG 5. Unweighted it is a COUNT and says so; the recon's own headline ("113 destinations carry measured
    # US-export volume, 3 resolve, 27.4% of flows") is a tonnage statement, and 191 unmapped destinations vs
    # 27.4% unmapped FLOW are very different claims. Pseudo/bloc rows (kind != country) are excluded so a
    # region_nec aggregate is never counted as a missing country.
    codes = {2010: {"name": "Mexico", "aliases": ["mexico"], "kind": "country", "pseudo": False},
             5700: {"name": "Japan", "aliases": ["japan"], "kind": "country", "pseudo": False},
             7640: {"name": "Western Africa (NEC)", "aliases": [], "kind": "region_nec", "pseudo": True}}
    _wire(monkeypatch, {"esr_destinations": ["Mexico", "Japan"], "country_origin": ["Mexico"],
                        "geography": ["Mexico"]}, codes=codes)
    plain = [ln for ln in gg.country_axis_warnings() if "B1 headline" in ln]
    assert len(plain) == 1
    assert "of 2 real ESR destination countries, 1 have no entity_vocabulary" in plain[0]
    assert "counts only" in plain[0] and "TONNAGE-WEIGHTED" not in plain[0]
    # Japan is the unmapped one and it carries 9 of every 10 tonnes: the weighted number is 10%, not 50%.
    weighted = [ln for ln in gg.country_axis_warnings(tonnage={2010: 1000.0, 5700: 9000.0})
                if "B1 headline" in ln][0]
    assert "TONNAGE-WEIGHTED coverage: country_origin 10.0%" in weighted


def test_vacuous_on_a_tree_with_no_private_configs(monkeypatch):
    # The lint doctrine, asserted: a lint that cannot load its input reports NOTHING. Returning "everything
    # drifted" on a clean checkout is how a lint gets ignored, and every roster reader here already fails
    # closed to an empty set rather than raising.
    _wire(monkeypatch, {}, codes={})
    assert gg.country_axis_warnings() == []


def test_the_live_rosters_load_or_the_tree_has_no_private_configs():
    # NON-VACUITY against the real tree. Not a pinned roster size -- those move every wave and pinning them
    # would make this an artifact-staling test rather than a drift detector. What is pinned is that the six
    # readers actually resolve six sets and that the lint returns its census line.
    r = gg.country_axis_rosters()
    if not r["esr_destinations"] and not r["country_origin"]:
        pytest.skip("no private configs in this tree -- the diff is vacuous")
    assert r["geo_lexicon"], "geo_lexicon lives in src/ and must never read empty"
    assert r["esr_destinations"] and r["country_origin"] and r["geography"]
    lines = gg.country_axis_warnings()
    assert lines and "country-axis namespace diff" in lines[0]
    assert all(ln.encode("ascii") for ln in lines)
