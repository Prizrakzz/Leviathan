"""TRANSMISSION CHAIN -- eval.py pin scoring + mini-deck shape (TRANSMISSION_CHAIN_PLAN sec 3.1/6.1).

The horizontal pins get teeth here, mirroring test_chain_eval_scoring.py exactly: transmission_fired (bool of
trace.quantify_transmission, the chain_fired idiom), min_transmission_hops_cited (LINKS whose BOTH legs' World
su_ratio [N] rows were cited in the structured prose), and transmission_decline_reason (the shared decline
enum + the horizontal-only `link_comove`, with 'absent' accepting a no-match / fired turn). Hand-built `out`
dicts, no answer.answer() call. The deck section asserts the two mini-decks parse and that every pin they use
is a KNOWN assert key -- a typo'd pin scores nothing and would false-green a gate run."""
from __future__ import annotations

import pathlib

import pytest
import yaml

from leviathan.graphrag import eval as ev

_PALM = "malaysian_crude_palm_oil_cme"
_SBO = "soybean_oil_cbot"
_SBM = "soybean_meal_cbot"
_LEG = "su_ratio_world"                                          # the metric every transmission leg row carries


def _out(*, fired=True, links=None, decline=None, cited=(), legs=None):
    """`legs` = [(citation id, commodity, metric)]; `cited` = the ids the model actually put in prose."""
    links = links if links is not None else [{"pair_id": "soyoil_palm_vegoil", "source": _PALM, "target": _SBO},
                                             {"pair_id": "soymeal_soyoil_crush", "source": _SBO, "target": _SBM}]
    legs = legs if legs is not None else [("N1", _PALM, _LEG), ("N2", _SBO, _LEG), ("N3", _SBM, _LEG)]
    trace = {}
    if fired:
        trace["quantify_transmission"] = {"chain_id": "xmit_palm_soyoil_meal", "focus": _PALM,
                                          "window": "MY2023-MY2024", "links": links, "n_rows": len(legs)}
    if decline is not None:
        trace["quantify_transmission_decline"] = {"chain_id": "xmit_palm_soyoil_meal", "reason": decline}
    cits = [{"kind": "number", "id": nid, "locator": {"commodity": cm, "metric": met}, "value": "1"}
            for nid, cm, met in legs]
    prose = " ".join(f"[{c}]" for c in cited)
    return {"trace": trace, "citations": cits, "structured": {"tldr": "", "mechanism": prose}}


def _score(pins, out):
    return ev._cascade_asserts({"expect": pins, "asof": "2026-02-15"}, out)


# -- transmission_fired (the boolean pin; the negative branch is the realizable teeth) -----------------
def test_transmission_fired_true_passes_when_trace_present():
    assert _score({"transmission_fired": True}, _out(fired=True))["transmission_fired"] is True


def test_transmission_fired_true_fails_when_absent():
    assert _score({"transmission_fired": True}, _out(fired=False))["transmission_fired"] is False


def test_transmission_fired_false_passes_when_engine_dark():
    # the feed_grain row: no chain matches (D3 isolated edge) -> the key stays absent -> the false pin PASSES.
    assert _score({"transmission_fired": False}, _out(fired=False))["transmission_fired"] is True


# -- min_transmission_hops_cited (LINKS whose BOTH legs were cited) ------------------------------------
def test_hops_cited_counts_links_with_both_legs_cited():
    out = _out(cited=("N1", "N2", "N3"))                         # palm + soyoil + meal -> BOTH links cited
    assert _score({"min_transmission_hops_cited": 2}, out)["min_transmission_hops_cited"] is True
    assert _score({"min_transmission_hops_cited": 3}, out)["min_transmission_hops_cited"] is False


def test_hops_cited_link_needs_both_legs():
    # the reached-not-yet shape: link1 (palm, soyoil) cited, the meal leg never narrated -> exactly ONE link.
    out = _out(cited=("N1", "N2"))
    assert _score({"min_transmission_hops_cited": 1}, out)["min_transmission_hops_cited"] is True
    assert _score({"min_transmission_hops_cited": 2}, out)["min_transmission_hops_cited"] is False


def test_hops_cited_shared_hub_alone_credits_nothing():
    # only the hub cited: neither link has both endpoints, so a shared hub can never credit a downstream link.
    out = _out(cited=("N2",))
    assert _score({"min_transmission_hops_cited": 1}, out)["min_transmission_hops_cited"] is False


def test_hops_cited_ignores_non_transmission_rows():
    # a per-country cascade su_ratio row for the SAME commodity is NOT a transmission leg (different metric):
    # counting it would credit a link the horizontal engine never rendered.
    out = _out(legs=[("N1", _PALM, _LEG), ("N2", _SBO, "su_ratio")], cited=("N1", "N2"))
    assert _score({"min_transmission_hops_cited": 1}, out)["min_transmission_hops_cited"] is False


def test_hops_cited_zero_when_engine_dark():
    assert _score({"min_transmission_hops_cited": 1},
                  _out(fired=False, cited=("N1", "N2")))["min_transmission_hops_cited"] is False


# -- transmission_decline_reason ('absent' accepts no-decline; link_comove is HONEST) ------------------
def test_decline_reason_absent_accepts_no_match():
    pins = {"transmission_decline_reason": ["absent"]}
    assert _score(pins, _out(fired=False))["transmission_decline_reason"] is True


def test_decline_reason_absent_accepts_a_fired_turn():
    # a FIRED chain writes no decline key -> the [absent, link_comove] deck pin passes on the fired branch too.
    pins = {"transmission_decline_reason": ["absent", "link_comove"]}
    assert _score(pins, _out(fired=True))["transmission_decline_reason"] is True


def test_decline_reason_matches_link_comove():
    out = _out(fired=False, decline="link_comove")               # the reached-not-yet payoff (D4), not a failure
    pins = {"transmission_decline_reason": ["absent", "link_comove"]}
    assert _score(pins, out)["transmission_decline_reason"] is True


def test_decline_reason_rejects_unexpected_reason():
    out = _out(fired=False, decline="hop_dark")
    pins = {"transmission_decline_reason": ["absent", "link_comove"]}
    assert _score(pins, out)["transmission_decline_reason"] is False


def test_decline_reason_single_string_form():
    assert _score({"transmission_decline_reason": "cap"},
                  _out(fired=False, decline="cap"))["transmission_decline_reason"] is True


# -- the stats record: both engines read uniformly (3.1) ----------------------------------------------
def test_stats_carry_both_chain_engines_independently():
    cs = ev._cascade_stats(_out(fired=True, cited=("N1", "N2", "N3")))
    assert cs["transmission_fired"] is True and cs["n_transmission_hops_cited"] == 2
    assert cs["chain_fired"] is False and cs["chain_decline_reason"] is None   # the VERTICAL keys stay untouched


def test_per_answer_record_carries_transmission_keys():
    rec = ev._per_answer_record({"q": {"id": "x"}, "out": _out(fired=False, decline="link_comove")}, "single")
    assert rec["transmission_fired"] is False
    assert rec["transmission_decline_reason"] == "link_comove"


# -- the mini-decks (gitignored configs: skip when the tree has no synced copy) ------------------------
_CFG = pathlib.Path(__file__).resolve().parents[2] / "configs" / "graphrag"


def _deck(name: str) -> dict:
    p = _CFG / name
    if not p.exists():                                           # gitignored config; a public clone has none
        pytest.skip(f"{name} not present on this tree")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def test_decks_parse_with_unique_ids():
    rows = ((_deck("eval_queries_transmission_on.yaml").get("queries") or [])
            + (_deck("eval_queries_transmission_off.yaml").get("queries") or []))
    assert len(rows) == 6                                        # 4 ON-arm rows + 2 OFF-arm rows
    ids = [r.get("id") for r in rows]
    assert len(ids) == len(set(ids)) and all(ids)
    for r in rows:
        assert r.get("contract") and r.get("question") and r.get("asof") and r.get("expect")


def test_every_deck_pin_is_a_known_assert_key():
    # a typo'd pin key is scored by NOTHING (_cascade_asserts filters on _CASCADE_EXPECT) -- it would silently
    # false-green a gate run, so the deck may only use keys the harness actually implements.
    for name in ("eval_queries_transmission_on.yaml", "eval_queries_transmission_off.yaml"):
        for r in _deck(name).get("queries") or []:
            unknown = sorted(set(r.get("expect") or {}) - set(ev._CASCADE_EXPECT))
            assert not unknown, f"{name}:{r.get('id')} uses unknown pin keys {unknown}"


def test_on_deck_pins_the_transmission_surface():
    rows = {r["id"]: r["expect"] for r in _deck("eval_queries_transmission_on.yaml").get("queries") or []}
    assert rows["xmit_reached_not_yet_pos"]["transmission_fired"] is True
    assert rows["xmit_vegoil_triangle_pos"]["transmission_fired"] is True
    assert rows["xmit_feed_neg"]["transmission_fired"] is False   # engine-dark BY DESIGN (D3)
    # the crush row asserts an HONEST render, so it pins neither a fire nor a nature -- only the register.
    assert "transmission_fired" not in rows["xmit_crush_nature_honest"]
    # REGISTER PINS (2026-07-25 probe). banned_flow: 0 on EVERY row -- the positioning triad is corpus-
    # attainable (1 counting chunk repo-wide), so it is a real minting gate everywhere. banned_valuation: 0
    # on every row EXCEPT the corn feed one: that pin reads the RAW pre-sanitize counter, which includes
    # register.py Lane B (`cheap|rich|expensive` + a price/window noun), and the Lane-B corpus is 14/16
    # usda_gain_corn -- so on a feed-SUBSTITUTION ask it trips on the model QUOTING its own sourced record
    # ("cheap feed wheat ...", "sorghum ... too expensive ... at prices of RMB1930-1950") while sanitize
    # strips the sentence and the served answer stays register-clean. The exception is NAMED rather than
    # loosened to a blanket `.get(...) in (0, None)`: the veg-oil rows' corpus carries no such prose, so a
    # hit there can only have been MINTED, and dropping the pin from one of THEM must still fail here.
    _VAL_PIN_EXEMPT = {"xmit_feed_neg"}                          # corn corpus; see the deck's PROBE note
    for rid, exp in rows.items():
        assert exp.get("banned_flow") == 0, rid
        if rid in _VAL_PIN_EXEMPT:
            assert "banned_valuation" not in exp, rid
        else:
            assert exp.get("banned_valuation") == 0, rid


def test_off_deck_asserts_no_artifacts_and_a_live_vertical_chain():
    rows = {r["id"]: r["expect"] for r in _deck("eval_queries_transmission_off.yaml").get("queries") or []}
    assert all(exp["transmission_fired"] is False for exp in rows.values())
    assert rows["xmit_vertical_chain_unchanged_off"]["chain_fired"] is True
