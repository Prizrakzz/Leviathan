"""Unified provenance citations — numbers + document evidence through one schema (pure; no AWS/LLM)."""
from __future__ import annotations

from leviathan.graphrag.citations import from_evidence, from_number, render, unify


def _number_call():
    return {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                      "country": "Argentina", "period": "2023", "asof": "2024-06-01"},
            "rows": [{"value": "2462000.0", "knowledge_date": "2024-01-10", "period": "2023"}]}


def test_number_citation_has_value_unit_and_rerunnable_locator():
    c = from_number(_number_call(), 1)
    assert c.id == "N1" and c.kind == "number"
    assert "PSD" in c.label and "2,462,000" in c.label and "MT" in c.label   # unit MT pulled from the registry
    assert c.date == "2024-01-10" and c.unit == "MT"
    assert c.locator["kind"] == "number" and c.locator["table"] == "silver_psd" and c.locator["asof"] == "2024-06-01"


def test_number_citation_no_rows_says_not_known():
    call = {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot", "period": "2023"},
            "rows": []}
    c = from_number(call, 3)
    assert "(not known at asof)" in c.label and c.value is None


def test_evidence_citation_carries_forward_compatible_page_slots():
    row = {"source": "usda_gain_wheat", "source_key": "text/gain/xyz.json", "date": "2017-04-17",
           "text": "Black Sea wheat export competition with US HRS is limited by quality differences."}
    e = from_evidence(row, 1)
    assert e.id == "E1" and e.kind == "evidence" and e.source == "usda_gain_wheat"
    assert e.locator["kind"] == "doc" and e.locator["source_key"] == "text/gain/xyz.json"
    assert "page" in e.locator and e.locator["page"] is None                # slot present, filled by page-recovery later


def test_unify_numbers_and_evidence_into_one_numbered_list():
    row = {"source": "usda_wasde", "source_key": "text/wasde/1.json", "date": "1997-01-01", "text": "..."}
    cits = unify([row], [_number_call()])
    assert [c.id for c in cits] == ["E1", "N1"]
    block = render(cits)
    assert "[E1]" in block and "[N1]" in block and "known 2024-01-10" in block


def test_agent_to_citations_bridges():
    from leviathan.graphrag.numbers import agent as A
    cits = A.to_citations([_number_call()])
    assert len(cits) == 1 and cits[0].kind == "number" and cits[0].id == "N1"
