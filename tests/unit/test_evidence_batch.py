"""Batch-API evidence chunking — mocked (no S3 / Anthropic Batch / spend)."""
from __future__ import annotations

import json
import types

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import evidence_batch as eb
from leviathan.graphrag import extract as ex


def _fake_s3(full="Brazil frost hit arabica coffee hard in 2021."):
    body = types.SimpleNamespace(read=lambda: json.dumps({"full_text": full}).encode())
    return types.SimpleNamespace(get_object=lambda **kw: {"Body": body})


def test_submit_builds_requests_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(eb, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "sample_keys", lambda *a, **k:
                        ["text/source=usda_gain_coffee/publication_date=20210519/document=x/document.json"])
    captured = {}

    class _Batches:
        @staticmethod
        def create(*, requests):
            captured["requests"] = requests
            return types.SimpleNamespace(id="batch_test")

    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=_Batches()))
    bid = eb.submit(_fake_s3(), client, nodes=["arabica_coffee"], n_docs=1)

    assert bid == "batch_test"
    reqs = captured["requests"]
    assert reqs and reqs[0]["params"]["model"] == ex.HAIKU and "tools" not in reqs[0]["params"]   # no tools, no cache
    man = json.loads((tmp_path / "batch_test.json").read_text(encoding="utf-8"))["manifest"]
    cid = reqs[0]["custom_id"]
    assert man[cid]["contract"] == "arabica_coffee" and man[cid]["date"] == "2021-05-19"            # precise date


def test_retrieve_parses_props_embeds_and_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(eb, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path / "ev")
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "_aliases", lambda node: ["arabica"])
    cid = "r000000"
    (tmp_path / "batch_x.json").write_text(json.dumps({"batch_id": "batch_x", "manifest": {
        cid: {"contract": "arabica_coffee", "source_key": "s3://k", "source": "GAIN", "date": "2021-05-19"}}}),
        encoding="utf-8")
    text = ('[{"proposition":"Brazil frost hit arabica coffee","verbatim_span":"x"},'
            '{"proposition":"unrelated bonds note"}]')                       # 2nd prop is off-topic -> dropped
    result = types.SimpleNamespace(custom_id=cid, result=types.SimpleNamespace(
        type="succeeded", message=types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)])))

    class _Batches:
        @staticmethod
        def retrieve(b):
            return types.SimpleNamespace(processing_status="ended")

        @staticmethod
        def results(b):
            return [result]

    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=_Batches()))
    n = eb.retrieve(None, client, "batch_x")

    assert n == 1                                                            # bonds prop dropped by the matcher
    recs = [json.loads(x) for x in (tmp_path / "ev" / "arabica_coffee.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1 and "frost" in recs[0]["text"]
    assert recs[0]["date"] == "2021-05-19" and recs[0]["vector"] == [0.1, 0.2] and recs[0]["backend"]
