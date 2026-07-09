"""W1.5 blurb pipeline — schema round-trip + apply mapping (pure; the billed submit is gated, not unit-tested)."""
from __future__ import annotations

import json

from leviathan.causal import blurb as bl
from leviathan.causal import schema as cs


def _contract() -> cs.CausalContract:
    return cs.CausalContract(
        contract="arabica_coffee",
        drivers=[cs.Driver(id="frost", type="hazard", sign="+",
                           mechanism="Radiative frost in Brazil's arabica belt kills buds and cuts the next crop"),
                 cs.Driver(id="drought", type="hazard", sign="+", mechanism="Dryness cuts yield",
                           blurb="dry weather cuts the coffee crop")],
        inter_commodity=[cs.InterCommodityEdge(driver_commodity="robusta_coffee", relation="substitutes_for",
                                               sign="-", mechanism="Roasters swap blends toward robusta")],
    )


def test_blurb_schema_roundtrip_and_exclude_none(tmp_path):
    """An unset blurb writes NO yaml key (safe partial rollout); a set one round-trips."""
    p = tmp_path / "c.yaml"
    cs.dump(_contract(), p)
    text = p.read_text(encoding="utf-8")
    assert text.count("blurb:") == 1                       # only the pre-set one; None is omitted
    c2 = cs.load(p)
    assert c2.drivers[1].blurb == "dry weather cuts the coffee crop"
    assert c2.drivers[0].blurb is None


def test_targets_skip_already_blurbed(tmp_path, monkeypatch):
    p = tmp_path / "arabica_coffee.yaml"
    cs.dump(_contract(), p)
    monkeypatch.setattr(bl, "_CAUSAL_DIR", tmp_path)
    ts = bl._targets()
    ids = {(t["kind"], t["id"]) for t in ts}
    assert ("driver", "frost") in ids                      # no blurb yet -> a target
    assert ("driver", "drought") not in ids                # already blurbed -> skipped (idempotent)
    assert ("inter", "robusta_coffee") in ids


def test_apply_sets_ratified_blurbs_and_skips_over_limit(tmp_path, monkeypatch):
    p = tmp_path / "arabica_coffee.yaml"
    cs.dump(_contract(), p)
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    drafts = [
        {"contract": "arabica_coffee", "kind": "driver", "id": "frost",
         "mechanism": "x", "blurb": "Brazil frost kills coffee buds, cutting next year's crop", "words": 9,
         "over_limit": False},
        {"contract": "arabica_coffee", "kind": "inter", "id": "robusta_coffee",
         "mechanism": "x", "blurb": " ".join(["word"] * 20), "words": 20, "over_limit": True},  # must be skipped
    ]
    monkeypatch.setattr(bl, "_CAUSAL_DIR", tmp_path)
    monkeypatch.setattr(bl, "_PILOT", pilot)
    monkeypatch.setattr(bl, "_DRAFTS_FILE", pilot / "blurb_drafts.json")
    bl._DRAFTS_FILE.write_text(json.dumps(drafts), encoding="utf-8")
    assert bl.apply() == 0
    c2 = cs.load(p)
    assert c2.drivers[0].blurb == "Brazil frost kills coffee buds, cutting next year's crop"
    assert c2.inter_commodity[0].blurb is None             # over-limit draft never lands
    # the safety archive was written before the mutation
    archives = list(pilot.glob("blurb_archive_*"))
    assert archives and (archives[0] / "arabica_coffee.yaml").exists()
