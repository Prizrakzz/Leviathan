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


def test_retrieve_keeps_pure_driver_props_and_parses_event_date(tmp_path, monkeypatch):
    """WS-MS6: a pure-driver prop (names NO commodity) must SURVIVE into its driver slice, not be dropped by the
    commodity filter; event_date is parsed onto every record."""
    monkeypatch.setattr(eb, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path / "ev")
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "_aliases", lambda node: ["palm"])
    cid = "r000000"
    (tmp_path / "b.json").write_text(json.dumps({"batch_id": "b", "manifest": {
        cid: {"contract": "palm_oil", "source_key": "s3://k", "source": "GAIN", "date": "2023-08-11"}}}),
        encoding="utf-8")
    text = ('[{"proposition":"Palm oil demand rose in Indonesia.","verbatim_span":"x","event_date":"2023-02","event_date_precision":"month"},'
            '{"proposition":"Indonesia raised the blend to B40.","verbatim_span":"y","event_date":"2023-02-01","event_date_precision":"day"}]')
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
    n = eb.retrieve(None, client, "b")

    crecs = [json.loads(x) for x in (tmp_path / "ev" / "palm_oil.jsonl").read_text(encoding="utf-8").splitlines()]
    assert n == 1 and len(crecs) == 1 and crecs[0]["event_date"] == "2023-02-01"        # commodity slice + event date
    drecs = [json.loads(x) for x in
             (tmp_path / "ev" / "drivers" / "biodiesel_mandate.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any("B40" in r["text"] for r in drecs) and drecs[0]["event_date"] == "2023-02-01"   # pure-driver prop SURVIVED
