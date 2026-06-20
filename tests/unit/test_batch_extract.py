"""GraphRAG cloud Batch runner tests — fully mocked S3 + Anthropic (no network, no spend)."""
from __future__ import annotations

import io
import json

import pytest

from leviathan.graphrag import batch_extract as bx

_DOCS = {
    "text/source=usda_gain_coffee/crop_year=2019_20/document.json":
        {"full_text": "Frost hit Brazil in June. Arabica production fell sharply. Prices rose.",
         "extraction_method": "pdfplumber"},
    "text/source=usda_gain_wheat/year=2021/document.json":
        {"full_text": "Dry weather cut US wheat yields. Exports declined for the season.",
         "extraction_method": "pdfplumber"},
    "text/source=usda_gain_soybeans/year=2023/document.json":
        {"full_text": "Argentine soybean output dropped on drought. The crush margin widened.",
         "extraction_method": "pdfplumber"},
}


class FakeS3:
    def __init__(self):
        self.puts: dict[str, bytes] = {}

    def get_paginator(self, _):
        return self

    def paginate(self, **_):
        yield {"Contents": [{"Key": k} for k in _DOCS]}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(json.dumps(_DOCS[Key]).encode("utf-8"))}

    def put_object(self, Bucket, Key, Body):
        self.puts[Key] = Body


def _result(custom_id, tool_input):
    blk = type("Blk", (), {"type": "tool_use", "input": tool_input})()
    usage = type("U", (), {"input_tokens": 8, "output_tokens": 4})()
    msg = type("Msg", (), {"content": [blk], "usage": usage})()
    res = type("R", (), {"type": "succeeded", "message": msg})()
    return type("Wrap", (), {"custom_id": custom_id, "result": res})()


class FakeBatches:
    def __init__(self):
        self.requests = None

    def create(self, requests):
        self.requests = requests
        return type("B", (), {"id": "batch_test", "processing_status": "in_progress"})()

    def retrieve(self, bid):
        return type("B", (), {"processing_status": "ended"})()

    def results(self, bid):
        empty = {"entities": [], "relationships": [], "events": [], "quantitative_claims": [],
                 "unmapped_relations": [], "unmapped_entities": []}
        first = dict(empty, entities=[{"id": "arabica_coffee", "type": "commodity",
                                       "canonical_name": "arabica_coffee", "mapped": True}],
                     relationships=[{"src": "frost", "dst": "arabica_coffee", "relation_type": "causes",
                                     "metric": "production", "sign": "-", "evidence_class": "fact",
                                     "marker": "due to", "verbatim": "Frost hit Brazil", "mapped": True}])
        for i, r in enumerate(self.requests):
            yield _result(r["custom_id"], first if i == 0 else empty)


class FakeClient:
    def __init__(self):
        self.messages = type("M", (), {"batches": FakeBatches()})()


# ── pure helpers (always run) ──────────────────────────────────────────────────────
def test_custom_id_sanitizes():
    assert bx._custom_id("conab-12#c3") == "conab-12-c3"


def test_year_and_domain():
    assert bx._year_of("text/source=conab/crop_year=2011_12/x/document.json") == "2011"
    assert bx._year_of("text/source=usda_gain_wheat/year=2021/document.json") == "2021"
    assert bx._domain_of("usda_gain_coffee") == "softs"
    assert bx._domain_of("usda_gain_wheat") == "grains"
    assert bx._domain_of("usda_gain_soybeans") == "oilseeds"


def test_sample_picks_three_distinct_years_with_softs():
    keys = bx.sample_3(FakeS3(), seed=1)
    assert len(keys) == 3
    years = {bx._year_of(k) for k in keys}
    assert len(years) == 3
    assert any(bx._domain_of(bx._source_of(k)) == "softs" for k in keys)


# ── submit + retrieve round-trip (needs the local vocab; skipped in CI) ────────────
def _vocab_present():
    return (bx.ex._CFG / "entity_vocabulary.yaml").exists()


def test_submit_builds_forced_tool_requests(monkeypatch, tmp_path):
    if not _vocab_present():
        pytest.skip("private vocab not present")
    monkeypatch.setattr(bx, "_OUT", tmp_path)
    s3, client = FakeS3(), FakeClient()
    bid = bx.submit(s3, client, seed=1, chunker="deterministic")
    assert bid == "batch_test"
    reqs = client.messages.batches.create.__self__.requests
    assert reqs and all(r["params"]["tool_choice"]["name"] == "emit_extraction" for r in reqs)
    assert all(re_ok(r["custom_id"]) for r in reqs)
    assert any(k.startswith("graphragv2/chunks/") for k in s3.puts)       # chunks persisted at submit
    assert any(k.startswith("graphragv2/_batches/") for k in s3.puts)     # manifest persisted


def re_ok(cid: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid))


def test_retrieve_writes_full_records(monkeypatch, tmp_path):
    if not _vocab_present():
        pytest.skip("private vocab not present")
    monkeypatch.setattr(bx, "_OUT", tmp_path)
    s3, client = FakeS3(), FakeClient()
    bid = bx.submit(s3, client, seed=1, chunker="deterministic")
    bx.retrieve(s3, client, bid)
    # the seeded arabica_coffee/causes extraction must land as FULL records in graphragv2/
    rel_keys = [k for k in s3.puts if k.startswith("graphragv2/relationships/")]
    assert rel_keys, "no relationships persisted"
    rel = json.loads(s3.puts[rel_keys[0]].decode("utf-8").splitlines()[0])
    assert rel["relation_type"] == "causes" and rel["metric"] == "production"
    assert rel["edge_id"] and rel["sources"]            # full provenance, not a trimmed view
    assert (tmp_path / "friction_report.md").exists()
