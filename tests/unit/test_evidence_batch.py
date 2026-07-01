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
    raw = [json.loads(x) for x in (tmp_path / "ev" / "_raw" / "palm_oil.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(raw) == 2 and all("vector" not in r for r in raw)                # _raw keeps EVERY prop, unembedded


def test_retrieve_writes_doc_cache_and_sampling_gathers(tmp_path, monkeypatch):
    """retrieve writes a doc-keyed chunk cache (chunks/<hash>) deduped across the nodes that sampled the same
    doc; a `sampling` manifest then gathers each node's props FROM that cache (chunk once, route many)."""
    monkeypatch.setattr(eb, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path / "ev")
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "_aliases", lambda node: {"corn": ["maize"], "soybeans": ["soy"]}.get(node, []))
    man = {"r000000": {"contract": "corn", "source_key": "D", "source": "WASDE", "date": "2024-01-01"},
           "r000001": {"contract": "soybeans", "source_key": "D", "source": "WASDE", "date": "2024-01-01"}}
    (tmp_path / "b.json").write_text(json.dumps({"batch_id": "b", "manifest": man,
        "sampling": {"corn": ["D"], "soybeans": ["D"]}}), encoding="utf-8")               # same doc, two nodes
    text = '[{"proposition":"US corn and soybeans production rose.","verbatim_span":"x"}]'

    def _res(cid):
        return types.SimpleNamespace(custom_id=cid, result=types.SimpleNamespace(
            type="succeeded", message=types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)])))

    class _B:
        @staticmethod
        def retrieve(b):
            return types.SimpleNamespace(processing_status="ended")

        @staticmethod
        def results(b):
            return [_res("r000000"), _res("r000001")]

    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=_B()))
    eb.retrieve(None, client, "b")

    cache = list((tmp_path / "ev" / "chunks").glob("*.jsonl"))
    assert len(cache) == 1                                                                 # ONE doc cached
    crecs = [json.loads(x) for x in cache[0].read_text(encoding="utf-8").splitlines()]
    assert len(crecs) == 1                                                                 # prop deduped across the 2 nodes
    corn = [json.loads(x) for x in (tmp_path / "ev" / "corn.jsonl").read_text(encoding="utf-8").splitlines()]
    soy = [json.loads(x) for x in (tmp_path / "ev" / "soybeans.jsonl").read_text(encoding="utf-8").splitlines()]
    assert corn[0]["contract"] == "corn" and soy[0]["contract"] == "soybeans"              # gathered from cache into both


def test_rebuild_slices_routes_whole_doc_cache(tmp_path, monkeypatch):
    """WS-MS7: rebuild_slices reads the chunks/ doc-cache and routes EACH prop to EVERY matching commodity slice
    (a multi-commodity WASDE prop lands in BOTH) plus its driver slice — free, no chunking, no Anthropic."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "all_nodes", lambda: ["corn", "soybeans"])
    monkeypatch.setattr(ev, "match_forms",
                        lambda n: {"corn": ["corn", "maize"], "soybeans": ["soybean", "soy"]}[n])
    (tmp_path / "chunks").mkdir()
    docs = {
        "aaa": [{"id": "aaa#0", "date": "2024-01-01", "source": "WASDE", "source_key": "D1",
                 "text": "US corn and soybean production both rose.", "event_date": None, "event_date_precision": None}],
        "bbb": [{"id": "bbb#0", "date": "2023-02-01", "source": "GAIN", "source_key": "D2",
                 "text": "Indonesia raised the biodiesel blend to B40.", "event_date": "2023-02-01",
                 "event_date_precision": "day"}],
    }
    for h, recs in docs.items():
        (tmp_path / "chunks" / f"{h}.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")

    n = eb.rebuild_slices()
    corn = [json.loads(x) for x in (tmp_path / "corn.jsonl").read_text(encoding="utf-8").splitlines()]
    soy = [json.loads(x) for x in (tmp_path / "soybeans.jsonl").read_text(encoding="utf-8").splitlines()]
    assert n == 2 and len(corn) == 1 and len(soy) == 1           # SAME prop routed to BOTH commodity slices
    drecs = [json.loads(x) for x in
             (tmp_path / "drivers" / "biodiesel_mandate.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any("B40" in r["text"] for r in drecs)               # pure-driver prop captured from the cache too


def test_retrieve_doclist_only_caches_no_slices(tmp_path, monkeypatch):
    """WS-MS7 doc-list fill: a doclist batch retrieve writes ONLY the chunks/ cache and returns early — it does
    NOT write commodity/driver slices (routing is deferred to a free --rebuild-slices)."""
    monkeypatch.setattr(eb, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path / "ev")
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    cid = "r000000"
    (tmp_path / "b.json").write_text(json.dumps({"batch_id": "b", "doclist": True, "manifest": {
        cid: {"contract": "_docs", "source_key": "s3://k", "source": "WASDE", "date": "1995-05-11"}}}),
        encoding="utf-8")
    text = '[{"proposition":"World wheat ending stocks were revised lower.","verbatim_span":"x"}]'
    result = types.SimpleNamespace(custom_id=cid, result=types.SimpleNamespace(
        type="succeeded", message=types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)])))

    class _B:
        @staticmethod
        def retrieve(b):
            return types.SimpleNamespace(processing_status="ended")

        @staticmethod
        def results(b):
            return [result]

    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=_B()))
    n = eb.retrieve(None, client, "b")

    assert n == 1 and list((tmp_path / "ev" / "chunks").glob("*.jsonl"))   # one prop cached to chunks/
    assert not (tmp_path / "ev" / "_docs.jsonl").exists()                  # NO commodity slice written
    assert not (tmp_path / "ev" / "drivers").exists()                     # NO driver slice written (deferred)


def test_reroute_rederives_slices_from_raw_without_rechunk(tmp_path, monkeypatch):
    """reroute reads the persisted _raw archive (incl. a 'neither' boilerplate prop) and re-derives the
    commodity + driver slices with NO Anthropic call — the 'chunk once, route forever' guarantee."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "_aliases", lambda node: ["palm"])
    raw = [
        {"id": "a", "contract": "palm_oil", "date": "2023-08-11", "source": "GAIN", "source_key": "k",
         "text": "Palm oil exports rose.", "event_date": None, "event_date_precision": None},
        {"id": "b", "contract": "palm_oil", "date": "2023-08-11", "source": "GAIN", "source_key": "k",
         "text": "Indonesia raised the blend to B40.", "event_date": "2023-02-01", "event_date_precision": "day"},
        {"id": "c", "contract": "palm_oil", "date": "2023-08-11", "source": "GAIN", "source_key": "k",
         "text": "Table of contents, page 3.", "event_date": None, "event_date_precision": None},
    ]
    (tmp_path / "_raw").mkdir()
    (tmp_path / "_raw" / "palm_oil.jsonl").write_text("\n".join(json.dumps(r) for r in raw), encoding="utf-8")

    n = eb.reroute(nodes=["palm_oil"])
    crecs = [json.loads(x) for x in (tmp_path / "palm_oil.jsonl").read_text(encoding="utf-8").splitlines()]
    assert n == 1 and len(crecs) == 1 and "exports" in crecs[0]["text"]         # commodity slice re-derived
    drecs = [json.loads(x) for x in (tmp_path / "drivers" / "biodiesel_mandate.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any("B40" in r["text"] for r in drecs)                              # driver slice re-derived from _raw
    assert "Table of contents" not in (tmp_path / "palm_oil.jsonl").read_text(encoding="utf-8")   # boilerplate stays archived-only
