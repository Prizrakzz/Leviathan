"""GraphRAG extraction-core tests — mapping + friction capture, fully mocked (no network, no spend)."""
from __future__ import annotations

from datetime import date

import pytest

from leviathan.graphrag import extract as ex
from leviathan.graphrag.contracts import Chunk

NODE_TYPES = {"commodity", "hazard"}
NODE_MEMBERS = {"arabica_coffee", "frost"}
EDGES = {"causes", "affects_yield_of"}


def _chunk() -> Chunk:
    return Chunk(chunk_id="d#c0", proposition="frost cut output", verbatim_span="frost cut output",
                 source_key="text/source=conab/x/document.json", page=0, char_start=0, char_end=15,
                 document_date=date(2021, 7, 1), source="conab", lang="pt", translated=False,
                 extraction_method="pdfplumber", ocr=False, text_quality=0.9)


def test_to_contracts_maps_valid_and_routes_unmapped():
    x = ex.ChunkExtraction(
        entities=[ex.XEntity(id="arabica_coffee", type="commodity", canonical_name="arabica_coffee"),
                  ex.XEntity(id="urea_cost", type="input", canonical_name="urea", mapped=False)],
        relationships=[
            ex.XRel(src="frost", dst="arabica_coffee", relation_type="causes", metric="production",
                    sign="-", evidence_class="fact", marker="due to", verbatim="frost cut output"),
            ex.XRel(src="x", dst="y", relation_type="OTHER", mapped=False, verbatim="weird link"),
            ex.XRel(src="frost", dst="arabica_coffee", relation_type="affects_yield_of", sign="-",
                    marker=None, verbatim="hurt yield")],
        quantitative_claims=[ex.XClaim(entity="arabica_coffee", metric="production", value=-32,
                                       unit="pct", period="2021", direction="-")])
    out, fr = ex.to_contracts(x, _chunk(), node_types=NODE_TYPES, node_members=NODE_MEMBERS, edges=EDGES)
    assert len(out["relationships"]) == 2 and out["relationships"][0].metric == "production"
    assert len(out["entities"]) == 1                       # non-node entity routed to friction
    assert any("urea_cost" in u for u in fr.unmapped_entities)
    assert any("OTHER" in u for u in fr.unmapped_relations)
    assert fr.causal_without_marker == 1                   # affects_yield_of with marker=None
    assert len(out["quantitative_claims"]) == 1


def test_metric_smuggled_as_entity_is_rejected():
    x = ex.ChunkExtraction(entities=[ex.XEntity(id="arabica_production", type="commodity",
                                                canonical_name="arabica_production")])
    out, fr = ex.to_contracts(x, _chunk(), node_types=NODE_TYPES, node_members=NODE_MEMBERS, edges=EDGES)
    assert out["entities"] == []
    assert any("arabica_production" in u for u in fr.unmapped_entities)


def test_call_opus_with_fake_client_then_parse():
    class _Block:
        type = "tool_use"
        input = {"entities": [], "relationships": [], "events": [], "quantitative_claims": [],
                 "unmapped_relations": [], "unmapped_entities": []}

    class _Usage:
        input_tokens, output_tokens = 10, 5

    class _Resp:
        content, usage = [_Block()], _Usage()

    class _Messages:
        @staticmethod
        def create(**kw):
            assert kw["tool_choice"]["name"] == "emit_extraction"   # forced tool use
            return _Resp()

    class _Client:
        messages = _Messages()

    tool_input, usage = ex.call_opus(_Client(), "sys", "user")
    assert usage.input_tokens == 10 and usage.cost > 0
    assert ex.parse_extraction(tool_input).entities == []


def test_metric_normalization():
    assert ex._norm_metric("harvested_area") == "area"
    assert ex._norm_metric("ending_stocks") == "stock"
    assert ex._norm_metric("demand") == "consumption"
    assert ex._norm_metric("production") == "production"   # canonical passes through
    assert ex._norm_metric(None) is None


def test_endpoint_check_flags_but_keeps_dangling_edge():
    x = ex.ChunkExtraction(relationships=[
        ex.XRel(src="Narnia", dst="arabica_coffee", relation_type="causes", sign="-", verbatim="x")])
    out, fr = ex.to_contracts(x, _chunk(), node_types=NODE_TYPES, node_members=NODE_MEMBERS, edges=EDGES)
    assert len(out["relationships"]) == 1                  # kept, not dropped
    assert any("Narnia" in d for d in fr.dangling_endpoints)


def test_region_canonicalizer():
    if not (ex._CFG / "regions.yaml").exists():
        pytest.skip("harvested regions.yaml not present")
    assert ex._canon_region("free state") == "Free_State"  # case/space-insensitive harvest match
    assert ex._canon_region("Nowhere_Region_XYZ") is None


def test_lean_tool_schema_has_all_fields():
    props = ex.extraction_tool(lean=True)["input_schema"]["properties"]
    assert set(props) >= {"entities", "relationships", "events", "quantitative_claims",
                          "unmapped_relations", "unmapped_entities"}


def test_lean_prompt_shorter_keeps_drivers():
    if not (ex._CFG / "entity_vocabulary.yaml").exists():
        pytest.skip("private vocab not present")
    full, lean = ex.build_system_prompt(lean=False), ex.build_system_prompt(lean=True)
    assert len(lean) < len(full) * 0.75                       # materially shorter
    for keep in ("NODE-MODEL", "arabica_coffee", "produces", "EXAMPLES"):
        assert keep in lean, f"lean prompt dropped recall-driver: {keep}"


def test_system_prompt_has_node_model_rule():
    if not (ex._CFG / "entity_vocabulary.yaml").exists():
        pytest.skip("private vocab not present (CI without IP configs)")
    p = ex.build_system_prompt()
    assert "NODE-MODEL RULE" in p and "causes" in p and "emit_extraction" in p
    assert "CASCADE" in p                      # mission framing present
    # the softs/tropicals nodes must NOT be truncated out of the prompt
    for node in ("arabica_coffee", "cocoa", "raw_sugar", "palm_oil", "biodiesel"):
        assert node in p, f"{node} missing from prompt (truncation regressed)"
