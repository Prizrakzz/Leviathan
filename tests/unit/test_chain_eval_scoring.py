"""CHAIN ENGINE -- eval.py pin scoring (CHAIN_ENGINE_PLAN sec 5.2/6.1; writer B).

The chain pins get teeth here: chain_fired (bool of trace.quantify_chain, the pace_fired idiom),
min_chain_hops_cited (distinct chain-hop metrics cited in the structured prose), and chain_decline_reason
(the reasoned-decline enum, with 'absent' accepting a no-match / fired turn). Mirrors the pace_expected test
shape: hand-built `out` dicts, no answer.answer() call."""
from __future__ import annotations

from leviathan.graphrag import eval as ev


def _out(*, fired=True, hops=None, decline=None, cited=("N1", "N2"), locators=None):
    hops = hops if hops is not None else [{"node": "La_Nina", "metric": "oni_anom"},
                                          {"node": "ending_stocks_su_ratio", "metric": "su_ratio"}]
    locators = locators if locators is not None else [("N1", "oni_anom"), ("N2", "su_ratio")]
    trace = {}
    if fired:
        trace["quantify_chain"] = {"chain_id": "c", "contract": "corn_cbot", "window": "w",
                                   "hops": hops, "n_rows": len(locators)}
    if decline is not None:
        trace["quantify_chain_decline"] = {"chain_id": "c", "reason": decline}
    cits = [{"kind": "number", "id": nid, "locator": {"metric": met}, "value": "1"} for nid, met in locators]
    prose = " ".join(f"[{c}]" for c in cited)
    return {"trace": trace, "citations": cits, "structured": {"tldr": "", "mechanism": prose}}


def _score(pins, out):
    return ev._cascade_asserts({"expect": pins, "asof": "2026-02-15"}, out)


# ── chain_fired (the boolean pin; the negative branch is the realizable teeth) ───────────────────────
def test_chain_fired_true_passes_when_trace_present():
    assert _score({"chain_fired": True}, _out(fired=True))["chain_fired"] is True


def test_chain_fired_true_fails_when_absent():
    assert _score({"chain_fired": True}, _out(fired=False))["chain_fired"] is False


def test_chain_fired_false_passes_when_engine_dark():
    # the SA-maize IOD row: no chain matched -> quantify_chain absent -> chain_fired false pins TRUE.
    assert _score({"chain_fired": False}, _out(fired=False))["chain_fired"] is True


# ── min_chain_hops_cited (distinct cited chain-hop metrics) ──────────────────────────────────────────
def test_min_chain_hops_cited_counts_distinct_cited_metrics():
    out = _out(cited=("N1", "N2"))                               # both hop metrics cited
    assert _score({"min_chain_hops_cited": 2}, out)["min_chain_hops_cited"] is True
    assert _score({"min_chain_hops_cited": 3}, out)["min_chain_hops_cited"] is False


def test_min_chain_hops_cited_only_counts_cited():
    out = _out(cited=("N1",))                                    # only hop 1 cited in prose
    assert _score({"min_chain_hops_cited": 2}, out)["min_chain_hops_cited"] is False
    assert _score({"min_chain_hops_cited": 1}, out)["min_chain_hops_cited"] is True


def test_min_chain_hops_cited_strips_delta_pct_suffix_no_double_count():
    # a level + its _delta share ONE base metric -> counts as ONE hop, not two.
    out = _out(hops=[{"node": "area", "metric": "area_harvested_1000ha"},
                     {"node": "ending_stocks", "metric": "su_ratio"}],
               locators=[("N1", "su_ratio"), ("N2", "su_ratio_delta"), ("N3", "area_harvested_1000ha")],
               cited=("N1", "N2", "N3"))
    assert _score({"min_chain_hops_cited": 2}, out)["min_chain_hops_cited"] is True   # {su_ratio, area}, not 3
    assert _score({"min_chain_hops_cited": 3}, out)["min_chain_hops_cited"] is False


# ── chain_decline_reason (the enum pin; 'absent' accepts no-decline) ─────────────────────────────────
def test_decline_reason_absent_accepts_no_match():
    out = _out(fired=False)                                      # neither trace key present -> reason None
    pins = {"chain_decline_reason": ["absent", "root_not_grounded"]}
    assert _score(pins, out)["chain_decline_reason"] is True


def test_decline_reason_matches_root_not_grounded():
    out = _out(fired=False, decline="root_not_grounded")
    assert _score({"chain_decline_reason": ["absent", "root_not_grounded"]}, out)["chain_decline_reason"] is True


def test_decline_reason_rejects_unexpected_reason():
    out = _out(fired=False, decline="hop_dark")                  # a hop_dark decline is NOT absent/root_not_grounded
    assert _score({"chain_decline_reason": ["absent", "root_not_grounded"]}, out)["chain_decline_reason"] is False


def test_decline_reason_single_string_form():
    out = _out(fired=False, decline="cap")
    assert _score({"chain_decline_reason": "cap"}, out)["chain_decline_reason"] is True
