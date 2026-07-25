"""TRANSMISSION CHAIN -- the LIVE-SHAPED regression (TRANSMISSION_CHAIN_PLAN 6.2 gate-1; the P4 pace lesson).

Fixture tests drive cq._transmission_legs directly. The gap the P4 pace lesson warns about is the one this
file closes: fixture tests can pass while the answer.py wiring is dark. This drives the REAL
an.answer -> _answer_l2 -> cq.quantify seam with the omit-when-off `transmission=` kwarg, over the GENUINE
walk -> ground -> quantify path (mocked call/retrieve/embed/qfn, real code path), on the FLAGSHIP
palm -> soyoil -> meal chain:

  * flag ON  + an explicit cross-commodity ask -> the chain fires end to end, trace.quantify_transmission is
               PRESENT with minted per-link [N] rows, and the block carries the TRANSMISSION CHAIN marker;
  * flag ON  + NO cross-commodity ask          -> the RV2 fence holds: BOTH keys absent (never volunteered);
  * flag OFF -> byte-identical: no kwarg, no keys, per-node cascade unchanged.

The PROMPT half rides here too: _SYSTEM_TRANSMISSION is appended inside the QUANT block and gated by the
transmission flag, so QUANT=off or the flag off leaves _system() byte-identical.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag.numbers import cascade as cq

ASOF = "2026-02-15"
PALM = "malaysian_crude_palm_oil_cme"
SBO = "soybean_oil_cbot"
SBM = "soybean_meal_cbot"
QUESTION = ("The palm supply squeeze -- how far did it carry through soyoil into soybean meal on the world "
            "balance sheets?")
XC = {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SBO, "detect_tier": "regex"}

# writer-side CONTENT pinned here (transmission_map.yaml is the curation surface): the flagship row.
_CHAIN = [{"id": "xmit_palm_soyoil_meal",
           "links": [{"pair_id": "soyoil_palm_vegoil", "source": PALM, "target": SBO, "nature": "divergence"},
                     {"pair_id": "soymeal_soyoil_crush", "source": SBO, "target": SBM, "nature": "co_move"}]}]
_SIDES = {"soyoil_palm_vegoil": (SBO, PALM), "soymeal_soyoil_crush": (SBM, SBO)}
_CNAME = {"soyoil_palm_vegoil": "vegoil_substitution", "soymeal_soyoil_crush": "soy_crush"}
# palm TIGHTENS, soyoil and meal LOOSEN -> link 1 opposes (divergence), link 2 agrees (co-move): the
# probe-verified flagship shape, linear in the MY so it holds for whatever anchor the live walk derives.
_STOCKS = {PALM: lambda my: 12.0 - (my - 2020), SBO: lambda my: 4.0 + (my - 2020),
           SBM: lambda my: 6.0 + 2.0 * (my - 2020)}


def _pair_row(pair_id):
    if pair_id not in _SIDES:
        return None
    a, b = _SIDES[pair_id]
    return SimpleNamespace(
        id=pair_id, pair=(a, b), complex_name=_CNAME[pair_id], shared_event="e",
        side_a={"contract": a, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        side_b={"contract": b, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        direction="opposing", focus_rule="query", materiality_tier="material")


def _graph() -> g.CausalGraph:
    palm = cs.CausalContract(
        contract=PALM, aliases=["palm", "cpo"],
        drivers=[
            cs.Driver(id="palm_supply_squeeze", type="supply_driver", sign="+",
                      silver_ref="psd_ending_stock_su_ratio", silver_status="available",
                      mechanism="A Malaysian output shortfall draws down palm stocks and tightens the oil balance."),
        ])
    return g.CausalGraph({PALM: palm}, silver=set())


def _fake_embed(texts, **k):
    return [[1.0, 0.0] for _ in texts]


def _fake_retrieve(q, node, *, k=5, asof=None, near=None):
    return [{"date": "2024-11-05", "source": "usda_gain", "source_key": f"s3://{node}/1", "text": f"{node} note"},
            {"date": "2024-12-10", "source": "usda_gain", "source_key": f"s3://{node}/2", "text": f"{node} more"}]


def _fake_call(system, user, *, model, tool):
    return {"tldr": "observed", "mechanism": "record", "sources": []}


def _qfn(sql):
    """The PSD component stub the World su_ratio synthesis reads (per-country rows + a release stamp), plus a
    plain value row for the per-node su_ratio cascade leg."""
    m = re.search(r"leviathan_slug = '([^']+)'", sql)
    y = re.search(r"market_year = (\d+)", sql)
    if m and y and m.group(1) in _STOCKS and ("ending_stocks_mt AS value" in sql or "consumption_mt AS value" in sql):
        slug, my = m.group(1), int(y.group(1))
        v = _STOCKS[slug](my) if "ending_stocks_mt AS value" in sql else 100.0
        return [{"value": str(v), "knowledge_date": "2026-01-20", "period": my, "country": "United States"}]
    if "su_ratio" in sql.lower():
        return [{"value": "0.21", "release_date": "2026-01-20"}]
    return []


def _wire(monkeypatch):
    from leviathan.graphrag import silverleg as slv
    monkeypatch.setattr(ev, "embed", _fake_embed)
    monkeypatch.setattr(an, "_pgnumbers_live", lambda: True)
    monkeypatch.setattr(slv, "_primary_country", lambda c: "malaysia")
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: {"palm_supply_squeeze"})
    monkeypatch.setattr(ev, "slice_for_driver", lambda did: did if did == "palm_supply_squeeze" else None)
    monkeypatch.setattr(cq, "load_transmission_map", lambda: list(_CHAIN))
    monkeypatch.setattr(cq, "_load_pair_row", _pair_row)
    monkeypatch.setattr(cq, "_xmit_pair_realizable", lambda pid: True)


def _run(xc=XC):
    return an.answer(QUESTION, graph=_graph(), planner="l2", asof=ASOF, retrieve=_fake_retrieve,
                     call=_fake_call, numbers_lookup=_qfn, route_fn=lambda q, gr: [PALM], xc_request=xc)


# ── the seam ────────────────────────────────────────────────────────────────────────────────────────
def test_live_path_transmission_fires_when_flag_on(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_CASCADE_TRANSMISSION", "on")
    monkeypatch.setenv("GRAPHRAG_COMOVE", "on")                    # the crush hop renders via the co-move path
    tr = _run()["trace"]
    xm = tr.get("quantify_transmission")
    assert xm is not None, "transmission dark on the live path (wiring gap)"      # THE gate-1 pin
    assert xm["chain_id"] == "xmit_palm_soyoil_meal" and xm["focus"] == PALM
    assert [(e["link"], e["rendered"]) for e in xm["links"]] == [(1, "divergence"), (2, "comove")]
    assert xm["n_rows"] == 12 and xm["stop_reason"] == "link_comove"
    assert "quantify_transmission_decline" not in tr and "quantify_error" not in tr


def test_live_path_alias_env_name_flips_the_same_switch(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.delenv("GRAPHRAG_CASCADE_TRANSMISSION", raising=False)
    monkeypatch.setenv("GRAPHRAG_TRANSMISSION", "on")              # the plan's D6 spelling, accepted as an alias
    monkeypatch.setenv("GRAPHRAG_COMOVE", "on")
    assert _run()["trace"].get("quantify_transmission") is not None


def test_live_path_no_cross_commodity_ask_never_volunteers(monkeypatch):
    """The RV2 fence: flag ON but no xc_request -> no attempt, BOTH keys absent (the fork is never the
    analyst's own initiative)."""
    _wire(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_CASCADE_TRANSMISSION", "on")
    tr = _run(xc=None)["trace"]
    assert "quantify_transmission" not in tr and "quantify_transmission_decline" not in tr


def test_live_path_flag_off_stays_byte_identical_no_keys(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.delenv("GRAPHRAG_CASCADE_TRANSMISSION", raising=False)     # default OFF, fail-closed
    monkeypatch.delenv("GRAPHRAG_TRANSMISSION", raising=False)
    tr = _run()["trace"]
    assert "quantify_transmission" not in tr and "quantify_transmission_decline" not in tr
    assert tr.get("quantify") is not None                          # the per-node cascade itself is unchanged


def test_live_path_flag_on_adds_exactly_the_chain_rows(monkeypatch):
    """[N]-row accounting across the seam: ON injects the chain block's rows on top of the OFF arm."""
    _wire(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_COMOVE", "on")
    monkeypatch.delenv("GRAPHRAG_CASCADE_TRANSMISSION", raising=False)
    monkeypatch.delenv("GRAPHRAG_TRANSMISSION", raising=False)
    n_off = _run()["trace"]["injected_n"]
    monkeypatch.setenv("GRAPHRAG_CASCADE_TRANSMISSION", "on")
    on = _run()["trace"]
    # [SKEPTIC F5] the fired composer SUBSUMES the standalone RV2 pair (6 rows in the OFF arm), so the
    # ON arm adds the chain's 12 rows but drops the 6 duplicates: OFF 11 - 6 + 12 = 17.
    assert on["injected_n"] == n_off - 6 + on["quantify_transmission"]["n_rows"]


# ── _SYSTEM_TRANSMISSION: the citation/heading-discipline paragraph (5.1) ───────────────────────────
def _isolate_prompt_env(monkeypatch) -> None:
    monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
    monkeypatch.delenv("GRAPHRAG_PATTERN_RECORDS", raising=False)
    monkeypatch.delenv("GRAPHRAG_CASCADE_CHAIN", raising=False)
    monkeypatch.delenv("GRAPHRAG_CASCADE_QUANT", raising=False)
    monkeypatch.delenv("GRAPHRAG_CASCADE_TRANSMISSION", raising=False)
    monkeypatch.delenv("GRAPHRAG_TRANSMISSION", raising=False)


def test_system_prompt_gains_the_paragraph_only_when_the_flag_is_on(monkeypatch):
    _isolate_prompt_env(monkeypatch)
    off = an._system()
    assert "TRANSMISSION CHAIN" not in off
    monkeypatch.setenv("GRAPHRAG_CASCADE_TRANSMISSION", "on")
    on = an._system()
    assert on == off + an._SYSTEM_TRANSMISSION                     # purely appended -> flag-off byte-identical
    assert "TRANSMISSION CHAIN" in on and "TRANSMISSION HANDOFF" in on


def test_system_paragraph_stays_inside_the_quant_block(monkeypatch):
    """QUANT off kills the cascade addendum AND its transmission paragraph (both kill-switches stay live)."""
    _isolate_prompt_env(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_CASCADE_TRANSMISSION", "on")
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "off")
    assert "TRANSMISSION CHAIN" not in an._system()


def test_system_paragraph_carries_no_conclusion_licence():
    """No price-direction verb minted by the paragraph, and the co-move link is explicitly fenced OUT of the
    divergence heading (the register discipline the marker itself encodes)."""
    p = an._SYSTEM_TRANSMISSION
    assert "never volunteer a cross-commodity chain from prose" in p
    assert "NO price-direction licence" in p and "never narrate a co-moving link as a divergence" in p
    assert "never bridge it with your own arithmetic" in p
    assert not re.search(r"\b(bullish|bearish|buy|sell|target)\b", p, re.I)
