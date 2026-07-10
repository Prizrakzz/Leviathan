"""Stage-C bake-off tests — fully mocked (no network, no spend)."""
from __future__ import annotations

from datetime import date

import pytest
from leviathan.graphrag import bakeoff as bo
from leviathan.graphrag.contracts import Relationship, SourceRef


def _rel(src, rt, dst, metric, source="usda", year=2020):
    return Relationship(edge_id=f"{src}{rt}{dst}{metric}{source}{year}", src_entity=src, relation_type=rt,
                        dst_entity=dst, metric=metric, sign="+", confidence=0.9, evidence_class="fact",
                        edge_scope="structural",
                        sources=[SourceRef(chunk_id="c", source=source, document_date=date(year, 1, 1),
                                           verbatim_span="v")])


def test_converse_toolspec_shape():
    spec = bo._converse_toolspec()["toolSpec"]
    assert spec["name"] == "emit_extraction"
    props = spec["inputSchema"]["json"]["properties"]
    assert {"entities", "relationships", "events", "quantitative_claims",
            "unmapped_relations", "unmapped_entities"} <= set(props)


def test_converse_extract_parses_tooluse_and_usage():
    class _RT:
        def converse(self, **kw):
            assert kw["toolConfig"]["toolChoice"]["tool"]["name"] == "emit_extraction"   # forced tool
            assert kw["system"][0]["text"] == "sys"
            return {"output": {"message": {"content": [
                        {"toolUse": {"input": {"entities": [], "relationships": []}}}]}},
                    "usage": {"inputTokens": 11, "outputTokens": 7}}
    ti, itok, otok = bo.converse_extract(_RT(), "m", "sys", "user")
    assert ti == {"entities": [], "relationships": []} and itok == 11 and otok == 7


def test_converse_extract_no_tooluse_returns_none():
    class _RT:
        def converse(self, **kw):
            return {"output": {"message": {"content": [{"text": "sorry"}]}}, "usage": {}}
    ti, itok, otok = bo.converse_extract(_RT(), "m", "sys", "user")
    assert ti is None and itok == 0 and otok == 0


def test_with_backoff_retries_throttle_then_succeeds(monkeypatch):
    monkeypatch.setattr(bo.time, "sleep", lambda *_: None)

    class ThrottlingException(Exception):
        pass
    n = {"i": 0}

    def fn():
        n["i"] += 1
        if n["i"] < 3:
            raise ThrottlingException("Rate exceeded")
        return "ok"
    assert bo._with_backoff(fn) == "ok" and n["i"] == 3


def test_with_backoff_reraises_non_throttle(monkeypatch):
    monkeypatch.setattr(bo.time, "sleep", lambda *_: None)

    def fn():
        raise ValueError("bad schema")
    with pytest.raises(ValueError):
        bo._with_backoff(fn)


def test_derive_builds_cascade_collapses_produces_and_costs():
    r = dict(bo._blank(), rels=[_rel("frost", "affects_yield_of", "soybeans", "yield"),
                                _rel("Brazil", "produces", "soybeans", "production"),
                                _rel("Brazil", "produces", "soybeans", "area")], **{"in": 1000, "out": 200})
    d = bo._derive(r, "qwen")
    assert ("frost", "affects_yield_of", "soybeans", "yield") in d["cascade"]
    assert ("Brazil", "produces", "soybeans", None) in d["edges"]          # produces collapsed, metric dropped
    assert sum(e[1] == "produces" for e in d["edges"]) == 1                # flood collapsed to one
    pin, pout = bo.PRICES["qwen"]
    assert abs(d["cost"] - (1000 * pin + 200 * pout) / 1e6) < 1e-12


def test_cascade_recall_precision_math():
    son = bo._derive(dict(bo._blank(), rels=[_rel("frost", "affects_yield_of", "soybeans", "yield"),
                                             _rel("drought", "causes", "corn", "production")]), "sonnet")
    kimi = bo._derive(dict(bo._blank(), rels=[_rel("frost", "affects_yield_of", "soybeans", "yield"),
                                              _rel("heat", "causes", "wheat", "yield")]), "kimi")
    rec = len(kimi["cascade"] & son["cascade"]) / len(son["cascade"])
    prec = len(kimi["cascade"] & son["cascade"]) / len(kimi["cascade"])
    assert rec == 0.5 and prec == 0.5                                      # 1 shared of 2 each side


def test_bakeoff_report_writes_frontier(monkeypatch, tmp_path):
    monkeypatch.setattr(bo, "_OUT", tmp_path)
    res = {"sonnet": dict(bo._blank(), rels=[_rel("frost", "affects_yield_of", "soybeans", "yield")], ok=1),
           "kimi": dict(bo._blank(), rels=[_rel("frost", "affects_yield_of", "soybeans", "yield")], ok=1),
           "qwen": dict(bo._blank(), rels=[_rel("heat", "causes", "wheat", "yield")], ok=1)}
    bo._bakeoff_report(res, ["text/source=usda_gain_soybeans/year=2020/document.json"], 1)
    txt = (tmp_path / "bakeoff_report.md").read_text(encoding="utf-8")
    assert "casc-recall" in txt and "sonnet" in txt and "kimi" in txt and "qwen" in txt
