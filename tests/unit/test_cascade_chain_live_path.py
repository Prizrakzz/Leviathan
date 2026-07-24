"""CHAIN ENGINE -- the LIVE-SHAPED regression (CHAIN_ENGINE_PLAN.md 6.2 gate-1; the P4 pace lesson).

Fixture tests drive cq._chain_legs directly. The live gap the P4 lesson warns about: fixture tests can
pass while the answer.py wiring is dark. This test drives the REAL an.answer -> _answer_l2 -> the
cq.quantify seam with the omit-when-off `chain` kwarg, over the GENUINE walk -> ground -> quantify chain
(mocked call/retrieve/embed/qfn, real code path), on an ACCENTED-contract root (La_Nina) so selection must
accent-fold to fire -- gate-1's "an accented-contract fixture must FIRE" (S2). chain_map.yaml is writer B's
CONTENT surface, so the curated list is monkeypatched at the loader seam (pinning the shape under test):

  * flag ON  -> the accented ENSO root is folded-matched, the 2-hop chain (oni -> su_ratio) fires end to
               end, and trace.quantify_chain is PRESENT with minted per-hop [N] rows;
  * flag OFF -> byte-identical to today: no chain kwarg, no quantify_chain key, per-node cascade unchanged.
"""
from __future__ import annotations

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag.numbers import cascade as cq

ASOF = "2011-06-01"
NINA = "La_Niña"                                              # ACCENTED in 8/14 v1 DAGs (S2)
QUESTION = ("How would a La Nina and the drought it drives feed through to the Brazil arabica coffee "
            "balance sheet and its stocks-to-use?")
# the curated chain under test (writer B's chain_map.yaml content, pinned here): oni_climate -> su_ratio,
# both ACTIVE cascade_map refs, ASCII node names -- the accent-fold must bridge them to the accented DAG root.
_CHAIN = [{"id": "coffee_lanina_su", "contracts": ["arabica_coffee"],
           "hops": [{"node": "La_Nina", "ref": "oni_climate"},
                    {"node": "ending_stocks_su_ratio", "ref": "psd_ending_stock_su_ratio"}]}]


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica", "coffee"],
        drivers=[
            cs.Driver(id=NINA, type="climate_driver", sign="+", silver_ref="oni_climate",
                      silver_status="available",
                      mechanism="A La Nina shifts rainfall over the Brazil arabica belt and stresses the crop."),
            cs.Driver(id="ending_stocks_su_ratio", type="balance_sheet", sign="+",
                      silver_ref="psd_ending_stock_su_ratio", silver_status="available", parents=[NINA],
                      mechanism="A short Brazil crop draws down ending stocks and tightens the coffee balance sheet."),
        ])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


def _fake_embed(texts, **k):
    out = []
    for t in texts:
        tl = (t or "").lower()
        if "nina" in tl or "nino" in tl or "enso" in tl:
            out.append([1.0, 0.0])
        elif "stock" in tl or "balance" in tl or "su" in tl:
            out.append([0.97, 0.03])
        else:
            out.append([0.9, 0.1])                                # query + contract profile: both drivers score high
    return out


def _fake_retrieve(q, node, *, k=5, asof=None, near=None):
    return [{"date": "2010-09-05", "source": "usda_gain", "source_key": f"s3://{node}/1", "text": f"{node} note"},
            {"date": "2010-10-10", "source": "usda_gain", "source_key": f"s3://{node}/2", "text": f"{node} more"}]


def _fake_call(system, user, *, model, tool):
    return {"tldr": "observed", "mechanism": "record", "sources": []}


def _qfn(sql):
    """oni (year_month) + su_ratio (marketing_year, silver_psd) rows; distinct per MY so a within-hop delta
    exists. Every hop returns >=1 ok endpoint -> the chain fires all-hops-or-nothing."""
    import hashlib
    s = sql.lower()
    h = int(hashlib.md5(sql.encode("utf-8")).hexdigest()[:6], 16)
    if "noaa_oni" in s or "oni_anom" in s:
        return [{"value": str(round(0.6 + (h % 20) / 10.0, 3)), "year": 2010, "month": 11}]
    if "su_ratio" in s:
        return [{"value": str(round(0.15 + (h % 25) / 100.0, 4)), "release_date": "2011-05-09"}]
    return [{"value": "1.0"}]


def _wire(monkeypatch):
    from leviathan.graphrag import silverleg as slv
    monkeypatch.setattr(ev, "embed", _fake_embed)
    monkeypatch.setattr(an, "_pgnumbers_live", lambda: True)
    monkeypatch.setattr(slv, "_primary_country", lambda c: "brazil")
    monkeypatch.setattr(ev, "backed_dag_ids", lambda: {NINA, "ending_stocks_su_ratio"})
    monkeypatch.setattr(ev, "slice_for_driver", lambda did: did if did in {NINA, "ending_stocks_su_ratio"} else None)
    monkeypatch.setattr(cq, "load_chain_map", lambda: _CHAIN)


def _run():
    return an.answer(QUESTION, graph=_graph(), planner="l2", asof=ASOF, retrieve=_fake_retrieve,
                     call=_fake_call, numbers_lookup=_qfn, route_fn=lambda q, gr: ["arabica_coffee"])


def test_live_path_chain_fires_on_accented_root_when_flag_on(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setenv("GRAPHRAG_CASCADE_CHAIN", "on")
    tr = _run()["trace"]
    ch = tr.get("quantify_chain")
    assert ch is not None, "chain dark on the live path (accent-fold or wiring gap)"   # THE gate-1 pin
    assert ch["chain_id"] == "coffee_lanina_su" and ch["contract"] == "arabica_coffee"
    # accent-fold bridged the ASCII chain_map name to the ACCENTED DAG/walk root; both hops quantified.
    assert [hp["node"] for hp in ch["hops"] if "collapsed_into" not in hp] == ["La_Nina", "ending_stocks_su_ratio"]
    assert ch["n_rows"] > 0 and ch["hops"][1]["country"] == "Brazil"
    assert "quantify_chain_decline" not in tr and "quantify_error" not in tr


def test_live_path_flag_off_stays_byte_identical_no_chain_key(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.delenv("GRAPHRAG_CASCADE_CHAIN", raising=False)     # default OFF, fail-closed
    tr = _run()["trace"]
    assert "quantify_chain" not in tr and "quantify_chain_decline" not in tr   # absent, not null
    assert tr.get("quantify")                                       # the per-node cascade itself is unchanged


def test_live_path_flag_on_adds_chain_rows_over_off(monkeypatch):
    """[N]-row accounting across the seam: ON injects the chain block's rows on top of the OFF arm; the OFF
    arm's injected_n is a strict floor."""
    _wire(monkeypatch)
    monkeypatch.delenv("GRAPHRAG_CASCADE_CHAIN", raising=False)
    n_off = _run()["trace"]["injected_n"]
    monkeypatch.setenv("GRAPHRAG_CASCADE_CHAIN", "on")
    out_on = _run()["trace"]
    assert out_on["injected_n"] > n_off
    assert out_on["injected_n"] == n_off + out_on["quantify_chain"]["n_rows"]   # exactly the chain block's rows
