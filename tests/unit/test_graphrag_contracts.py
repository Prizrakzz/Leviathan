"""Phase 1 W2 — GraphRAG data-contract tests (round-trip + invariants + arrow schema)."""
from __future__ import annotations

from datetime import date

import pyarrow as pa
import pytest
from pydantic import ValidationError

from leviathan.graphrag import contracts as c


def _chunk(**over):
    base = dict(
        chunk_id="x1", proposition="Brazil arabica output fell.",
        verbatim_span="a producao de arabica caiu", source_key="raw/conab/2021.pdf",
        page=3, char_start=10, char_end=42, document_date=date(2021, 7, 1),
        source="conab", lang="pt", translated=True, extraction_method="pdfplumber",
        ocr=False, text_quality=0.97,
    )
    base.update(over)
    return c.Chunk(**base)


def _edge(**over):
    # Node-model: node is the commodity (arabica_coffee); the metric the edge moves
    # rides on `metric`, the direction on `sign`.
    base = dict(
        edge_id="e1", src_entity="drought", dst_entity="arabica_coffee",
        relation_type="causes", metric="production", sign="-", confidence=0.8,
        evidence_class="fact", edge_scope="structural",
    )
    base.update(over)
    return c.Relationship(**base)


# ── round-trip fidelity: model → dict → model is identity ─────────────────────────
def test_chunk_round_trip():
    ch = _chunk()
    assert c.Chunk(**ch.model_dump()) == ch


def test_all_contracts_round_trip():
    samples = [
        _chunk(),
        _edge(),
        c.Entity(entity_id="arabica_coffee", type="commodity", canonical_name="arabica_coffee"),
        c.Event(event_id="brazil_drought_2021", event_type="drought", commodity="arabica_coffee",
                country="Brazil", season_or_date="2021", description="flowering drought",
                document_date=date(2021, 7, 1)),
        c.QuantitativeClaim(claim_id="q1", chunk_id="x1", entity_id="arabica_coffee",
                            metric="production", value=-32.0, unit="pct", period="2021",
                            direction="-", document_date=date(2021, 7, 1)),
        c.SourceReliability(source="conab", commodity="arabica_coffee", horizon_months=12,
                            n_obs=20, directional_hit_rate=0.8, reliability_score=0.75),
        c.NodeSilverMap(node_id="arabica_coffee", country="Brazil", silver_table="silver_psd",
                        silver_column="production_mt", as_of_supported=True),
    ]
    for m in samples:
        assert type(m)(**m.model_dump()) == m
        assert m.schema_version == c.SCHEMA_VERSION


# ── invariants are enforced, not documented ──────────────────────────────────────
def test_char_offsets_ordered():
    with pytest.raises(ValidationError):
        _chunk(char_start=50, char_end=10)


def test_ocr_must_match_extraction_method():
    with pytest.raises(ValidationError):
        _chunk(extraction_method="textract", ocr=False)


def test_event_specific_edge_requires_event_id():
    with pytest.raises(ValidationError):
        _edge(edge_scope="event_specific", event_id=None)
    # ...but with an event_id it's fine
    assert _edge(edge_scope="event_specific", event_id="brazil_drought_2021").event_id


def test_ratio_bounds_enforced():
    with pytest.raises(ValidationError):
        _edge(confidence=1.5)


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        _chunk(typo_column="oops")


def test_closed_enums():
    with pytest.raises(ValidationError):
        _edge(evidence_class="rumor")          # not in EvidenceClass


# ── node-model (commodity is the node; metric/direction ride on edge/claim) ───────
def test_edge_carries_metric_and_direction():
    e = _edge(metric="export", sign="+")
    assert c.Relationship(**e.model_dump()) == e
    assert e.metric == "export" and e.dst_entity == "arabica_coffee"


def test_new_metric_members_validate():
    for m in ("import", "consumption", "beginning_stock"):
        e = _edge(metric=m)
        assert e.metric == m
    with pytest.raises(ValidationError):
        _edge(metric="rainfall")               # not in Metric


def test_value_less_directional_claim():
    # "production fell" with no number → value=None, direction carries the signal.
    q = c.QuantitativeClaim(claim_id="q2", chunk_id="x1", entity_id="arabica_coffee",
                            metric="production", unit="", period="2021", direction="-",
                            document_date=date(2021, 7, 1))
    assert q.value is None
    assert c.QuantitativeClaim(**q.model_dump()) == q


# ── arrow schema is derivable for every contract ─────────────────────────────────
def test_arrow_schema_for_every_contract():
    for name, model in c.CONTRACTS.items():
        sch = c.arrow_schema(model)
        assert isinstance(sch, pa.Schema)
        assert "schema_version" in sch.names
    # spot-check scalar typing on chunks
    chunk_sch = c.arrow_schema(c.Chunk)
    assert chunk_sch.field("page").type == pa.int64()
    assert chunk_sch.field("document_date").type == pa.date32()
    assert chunk_sch.field("text_quality").type == pa.float64()
