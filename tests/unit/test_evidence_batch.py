"""Batch-API evidence chunking — mocked (no S3 / Anthropic Batch / spend)."""
from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import evidence_batch as eb
from leviathan.graphrag import extract as ex
from leviathan.graphrag import novelty as nv


def _fake_s3(full="Brazil frost hit arabica coffee hard in 2021.", listed=()):
    body = types.SimpleNamespace(read=lambda: json.dumps({"full_text": full}).encode())
    pages = [{"Contents": [{"Key": k} for k in listed]}]                 # store_path_index's LIST of text/
    return types.SimpleNamespace(get_object=lambda **kw: {"Body": body},
                                 get_paginator=lambda op: types.SimpleNamespace(paginate=lambda **kw: pages))


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


# ══ W2.1 char offsets ═══════════════════════════════════════════════════════════════════════════════════
def test_locate_span_exact_block_and_none():
    """_locate_span: 'exact' with absolute offsets when the verbatim span is found; 'block' fallback to the
    block's own span when a rewritten prop isn't verbatim; 'none' when there is no block text (a pre-W2.1
    manifest). The running cursor keeps in-order props from re-matching an earlier occurrence."""
    block = "Brazil frost devastated arabica coffee crops in 2021, and prices rose."
    bstart, bend = 10, 10 + len(block)
    cs, ce, kind, cur = eb._locate_span("arabica coffee", block, bstart, bend, 0)
    assert kind == "exact" and block[cs - bstart:ce - bstart] == "arabica coffee" and cur == block.find("arabica coffee") + len("arabica coffee")
    # rewritten prop, not present verbatim -> the block's own span
    cs, ce, kind, cur = eb._locate_span("Coffee output collapsed after the freeze", block, bstart, bend, 0)
    assert kind == "block" and cs == bstart and ce == bend
    # no block text at all -> none, offsets None
    cs, ce, kind, cur = eb._locate_span("anything", None, None, None, 0)
    assert kind == "none" and cs is None and ce is None
    # cursor advances: the second exact find lands AFTER the first
    _, _, k1, c1 = eb._locate_span("frost", block, bstart, bend, 0)
    cs2, _, k2, _ = eb._locate_span("prices", block, bstart, bend, c1)
    assert k1 == "exact" and k2 == "exact" and cs2 > bstart


def test_retrieve_stamps_offsets_and_chunk_version(tmp_path, monkeypatch):
    """W2.1/W2.2: retrieve() locates each prop's offset in its block (exact when verbatim, block on a rewrite)
    and stamps chunk_version; both ride the base dict, so they land in the doc cache AND the commodity slice."""
    monkeypatch.setattr(eb, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path / "ev")
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "_aliases", lambda node: ["arabica"])
    monkeypatch.setattr(ev, "current_chunk_version", lambda: "cv-test-1", raising=False)   # Agent 1 owns the real one
    block = "Brazil frost devastated arabica coffee crops in 2021."
    cid = "r000000"
    (tmp_path / "b.json").write_text(json.dumps({"batch_id": "b", "manifest": {cid: {
        "contract": "arabica_coffee", "source_key": "s3://k", "source": "GAIN", "date": "2021-05-19",
        "block_text": block, "block_start": 10, "block_end": 10 + len(block)}}}), encoding="utf-8")
    text = ('[{"proposition":"Brazil frost devastated arabica coffee crops in 2021.",'
            '"verbatim_span":"Brazil frost devastated arabica coffee crops in 2021."},'
            '{"proposition":"Arabica output fell sharply after the freeze.",'          # a REWRITE -> block fallback
            '"verbatim_span":"Arabica output fell sharply after the freeze."}]')
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
    eb.retrieve(None, client, "b")

    recs = [json.loads(x) for x in (tmp_path / "ev" / "arabica_coffee.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 2
    exact = next(r for r in recs if r["offset_kind"] == "exact")
    blk = next(r for r in recs if r["offset_kind"] == "block")
    assert exact["char_start"] == 10 and exact["char_end"] == 10 + len(block)          # verbatim -> exact absolute span
    assert blk["char_start"] == 10 and blk["char_end"] == 10 + len(block)              # rewrite -> the block's own span
    assert all(r["chunk_version"] == "cv-test-1" for r in recs)                        # vintage stamped on every prop
    cache = list((tmp_path / "ev" / "chunks").glob("*.jsonl"))
    crecs = [json.loads(x) for x in cache[0].read_text(encoding="utf-8").splitlines()]
    assert all({"char_start", "char_end", "offset_kind", "chunk_version"} <= set(r) for r in crecs)  # offsets in the cache too


def test_retrieve_offset_kind_none_without_block_info(tmp_path, monkeypatch):
    """A pre-W2.1 manifest (no block_text) still parses: offsets degrade to none/None, never a crash."""
    monkeypatch.setattr(eb, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path / "ev")
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "_aliases", lambda node: ["arabica"])
    cid = "r000000"
    (tmp_path / "b.json").write_text(json.dumps({"batch_id": "b", "manifest": {cid: {
        "contract": "arabica_coffee", "source_key": "s3://k", "source": "GAIN", "date": "2021-05-19"}}}),
        encoding="utf-8")
    text = '[{"proposition":"Brazil frost hit arabica coffee.","verbatim_span":"x"}]'
    result = types.SimpleNamespace(custom_id=cid, result=types.SimpleNamespace(
        type="succeeded", message=types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)])))
    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=types.SimpleNamespace(
        retrieve=lambda b: types.SimpleNamespace(processing_status="ended"), results=lambda b: [result])))
    eb.retrieve(None, client, "b")
    rec = json.loads((tmp_path / "ev" / "arabica_coffee.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["offset_kind"] == "none" and rec["char_start"] is None and rec["char_end"] is None


# ══ W1.2 dark-at-birth tally ═════════════════════════════════════════════════════════════════════════════
def test_dark_tally_four_way_classification_and_dedup():
    """The four mutually-exclusive states, dedup by (source_key, text), OR-folding of the signals across
    repeated sightings, the neither-queue, and the 60k-truncation count carried in the manifest (law #7)."""
    t = eb.DarkTally(label="x")
    t.add("k1", "corn and freight both rose", commodity_hit=True, driver_hit=True)      # both
    t.add("k2", "corn output rose", commodity_hit=True, driver_hit=False)               # commodity_only ...
    t.add("k2", "corn output rose", commodity_hit=False, driver_hit=True)               # ... OR-folds to both
    t.add("k3", "freight rates doubled", commodity_hit=False, driver_hit=True)          # driver_only
    t.add("k4", "table of contents page 3", commodity_hit=False, driver_hit=False)      # neither
    t.add("k4", "table of contents page 3", commodity_hit=False, driver_hit=False)      # dup -> counted once
    t.note_truncated("k_big")
    assert t.counts() == {"both": 2, "commodity_only": 0, "driver_only": 1, "neither": 1}
    assert t.neither_keys() == ["k4"]
    m = t.manifest()
    assert m["n_props"] == 4 and m["counts"] == t.counts() and m["neither_source_keys"] == ["k4"]
    assert m["n_docs_truncated_at_cap"] == 1 and m["truncated_source_keys"] == ["k_big"]
    assert m["fulltext_cap"] == eb._FULLTEXT_CAP                  # the manifest names the cap it reports on


def test_rebuild_slices_tally_writes_manifest(tmp_path, monkeypatch):
    """rebuild_slices(tally=True) classifies the whole cache GLOBALLY and writes a dark-tally manifest;
    the routing output is unchanged. Driver side is monkeypatched for a fully hermetic 4-way count."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path)                       # manifest lands under tmp_path/eval/
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "all_nodes", lambda: ["corn", "soybeans"])
    monkeypatch.setattr(ev, "match_forms", lambda n: {"corn": ["corn"], "soybeans": ["soybean"]}[n])
    monkeypatch.setattr(ev, "driver_slices_for", lambda text: ["biodiesel_mandate"] if "B40" in text else [])
    (tmp_path / "chunks").mkdir()
    docs = {
        "aaa": [{"id": "aaa#0", "source_key": "D1", "date": "2024-01-01", "source": "WASDE",
                 "text": "US corn and soybean production both rose.", "event_date": None, "event_date_precision": None}],
        "bbb": [{"id": "bbb#0", "source_key": "D2", "date": "2023-02-01", "source": "GAIN",
                 "text": "Indonesia raised the biodiesel blend to B40.", "event_date": None, "event_date_precision": None}],
        "ccc": [{"id": "ccc#0", "source_key": "D3", "date": "2022-06-01", "source": "MISC",
                 "text": "Quarterly logistics summary was filed.", "event_date": None, "event_date_precision": None}],
    }
    for h, recs in docs.items():
        (tmp_path / "chunks" / f"{h}.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")

    eb.rebuild_slices(tally=True)
    manifests = list((tmp_path / "eval").glob("dark_tally_rebuild_*.json"))
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["counts"] == {"both": 0, "commodity_only": 1, "driver_only": 1, "neither": 1}
    assert payload["neither_source_keys"] == ["D3"] and payload["n_docs_truncated_at_cap"] == 0
    # routing still happened (aaa reached both commodity slices)
    assert (tmp_path / "corn.jsonl").exists() and (tmp_path / "soybeans.jsonl").exists()


def test_doc_blocks_records_cap_truncation(tmp_path, monkeypatch):
    """law #7: _doc_blocks flags a doc whose full_text exceeded _FULLTEXT_CAP into the tally (still chunked,
    just capped) — the head-cut is never silent. Sized off the constant, so the D10 raise moves the fixture."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    big = "coffee arabica brazil frost " * (eb._FULLTEXT_CAP // 20)  # comfortably over the cap, whatever it is
    assert len(big) > eb._FULLTEXT_CAP
    key = "text/source=usda_wasde/publication_date=20240101/document=x/document.json"
    t = eb.DarkTally()
    blocks = eb._doc_blocks(None, "_docs", key, matcher=None, doc={"full_text": big}, tally=t)
    assert t.truncated_docs == {key} and blocks                     # flagged, and still produced (capped) blocks


# ══ W2.3 novelty hook ════════════════════════════════════════════════════════════════════════════════════
_KEEP = ("australian wheat farmers faced a severe drought that slashed winter crop tonnage as parched soils "
         "and record heat devastated fields throughout new south wales forcing many producers to abandon "
         "planted hectares and rely on dwindling grain reserves while livestock feed costs surged sharply")
_DUP_BASE = ("global coffee production in brazil rose sharply during the season as favorable rainfall boosted "
             "arabica yields across minas gerais and sao paulo while robusta output in espirito santo also "
             "climbed on improved irrigation and higher fertilizer application by growers who expanded planted "
             "area following two years of elevated international prices and strong export demand from roasters")
_DUP = _DUP_BASE + " analysts noted"                               # ~0.99 Jaccard vs the cached prop-space doc


def test_build_requests_from_docs_novelty_skips_are_logged(monkeypatch):
    """W2.3: with a gate, a near-dup candidate is skipped and logged (source_key/reason/score); a novel
    candidate is chunked. gate reads the body ONCE (monkeypatched _read_doc) — no double GET."""
    monkeypatch.setattr(eb, "_cached_hashes", lambda: set())
    keep_key = "text/source=usda_wap/publication_date=20240101/document=keep/document.json"
    dup_key = "text/source=usda_gain_coffee/publication_date=20240201/document=dup/document.json"
    bodies = {keep_key: {"full_text": _KEEP}, dup_key: {"full_text": _DUP}}
    monkeypatch.setattr(eb, "_read_doc", lambda s3, key, **kw: bodies[key])
    gate = nv.NoveltyGate(nv.corpus_signatures({"c1": [{"text": _DUP_BASE}]}))
    ledger: list = []
    reqs, manifest = eb._build_requests_from_docs(None, [keep_key, dup_key], gate=gate, ledger=ledger)

    assert any(v["source_key"] == dup_key and v["skip"] and v["reason"] == "near_dup" for v in ledger)
    assert reqs and all(m["source_key"] == keep_key for m in manifest.values())        # only the novel doc chunked
    assert all("block_text" in m for m in manifest.values())                           # W2.1 block span still attached


# ══ W2.4 skip-gate idempotency ═══════════════════════════════════════════════════════════════════════════
def test_skip_gate_idempotency_cached_doc_never_reenters_a_batch(monkeypatch):
    """A doc already in chunks/ (its md5 in _cached_hashes) is skipped by EVERY entry path — _build_requests,
    _build_requests_from_docs, and select_docs. Prop ids are batch-relative (rid = f"{custom_id}#{i}", where
    custom_id = f"r{len(requests):06d}"), so re-chunking would RE-NUMBER props; only this key-based skip gate
    makes a re-run safe (correction #2 — the idempotency is the skip, not id stability)."""
    key = "text/source=usda_wasde/publication_date=19950511/document=x/document.json"
    md5 = hashlib.md5(key.encode("utf-8")).hexdigest()
    monkeypatch.setattr(eb, "_cached_hashes", lambda: {md5})

    # (1) node-sampling path
    monkeypatch.setattr(ev, "sample_keys", lambda *a, **k: [key])
    monkeypatch.setattr(ev, "windows_for", lambda n: [])
    monkeypatch.setattr(ev, "n_docs_for", lambda n, d: 1)
    monkeypatch.setattr(ev, "match_forms", lambda n: ["wheat"])
    reqs, _man, sampling = eb._build_requests(_fake_s3(), ["wheat"], 1, 0)
    assert reqs == [] and sampling["wheat"] == [key]               # sampled but NOT re-chunked

    # (2) doc-list fill path
    reqs2, man2 = eb._build_requests_from_docs(_fake_s3(), [key])
    assert reqs2 == [] and man2 == {}

    # (3) selector path
    from leviathan.storage import s3 as st
    monkeypatch.setattr(st, "list_s3_keys", lambda *a, **k: [key])
    assert eb.select_docs(["usda_wasde"]) == []                    # cached key filtered out of the fill selection


# ══ S6 dating fix (cycle-2 W0a): `release=YYYY-MM` keys (wb_cmo_outlook) become selectable ═════════════════
def test_key_year_wb_cmo_now_dated():
    """The wb_cmo blind spot: `release=YYYY-MM` yielded None (100% of 147 docs skipped by select_docs)."""
    assert eb._key_year("text/source=wb_cmo_outlook/release=1994-11/document.json") == 1994


def test_key_year_now_dates_mpoc_the_last_selector_blind_spot():
    """A free consequence of the S1 deriver, and the exact twin of the wb_cmo `release=` bug above.
    `_key_year` asks `_pub_date` first and only then falls back to `_YEAR_RE`, whose alternation is
    (release_date|release_month|publication_date|year|crop_year|release) -- and an mpoc key carries NONE of
    them, only `date=YYYYMMDD`. So `_key_year` returned None and `select_docs`' era filter dropped all 335
    mpoc documents before any fill could see them. The `article_date` rule closes it."""
    k = ("text/source=mpoc/release_type=market_highlights/date=20200313/"
         "slug=crash-of-crude-oil-market-and-its-impact-on-oils-fats/document.json")
    assert eb._YEAR_RE.search(k) is None                            # the old path really did see nothing
    assert eb._key_year(k) == 2020


def test_key_year_existing_formats_unchanged():
    """Every pre-S6 key format parses byte-identically (the fix is purely additive)."""
    assert eb._key_year("text/source=usda_wasde/release_date=1973-09-17/document.json") == 1973
    assert eb._key_year("x/publication_date=20200515/document.json") == 2020
    assert eb._key_year("x/crop_year=2019/document.json") == 2019
    assert eb._key_year("x/release_month=200805/document.json") == 2008
    # gain keys carry no year token in the key itself (dated by inner publication_date only)
    assert eb._key_year("text/source=usda_gain_coffee/country=BR/no_year/document.json") is None


def test_select_docs_now_sees_wb_cmo(monkeypatch):
    """Pre-fix: y is None -> the era-filter `continue` dropped every wb_cmo doc. Post-fix it survives."""
    from leviathan.storage import s3 as st
    monkeypatch.setattr(st, "list_s3_keys",
                        lambda *a, **k: ["text/source=wb_cmo_outlook/release=1999-05/document.json"])
    assert eb.select_docs(["wb_cmo_outlook"], exclude_cached=False) == \
        ["text/source=wb_cmo_outlook/release=1999-05/document.json"]


def test_select_docs_era_filter_on_wb_cmo(monkeypatch):
    """--before/--after era filters now apply to wb_cmo keys (before_year keeps year < N)."""
    from leviathan.storage import s3 as st
    monkeypatch.setattr(st, "list_s3_keys",
                        lambda *a, **k: ["text/source=wb_cmo_outlook/release=1999-05/document.json",
                                         "text/source=wb_cmo_outlook/release=2005-10/document.json"])
    assert eb.select_docs(["wb_cmo_outlook"], before_year=2000, exclude_cached=False) == \
        ["text/source=wb_cmo_outlook/release=1999-05/document.json"]


# ── G1a: the doc-cache overwrite guard (seam C3, the highest-volume staler) ────────────────────────────
# On 2026-07-19T22:00Z, 614 chunks/<md5>.jsonl objects were rewritten -- at least 352 over documents already
# in the cache -- and because rebuild_slices re-derives EVERY slice from the whole cache, the next day's
# promote moved 24,439 driver rows and 48 span endpoints with not one term changing and no run record
# anywhere. A silent re-chunk is the defect; a declared one is not.
def _seed_cache(tmp_path, hash_name, recs):
    (tmp_path / "chunks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "chunks" / f"{hash_name}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs), encoding="utf-8")


def _cached_prop(text, cv):
    return {"id": "x", "date": "2024-01-01", "source": "GAIN", "source_key": "s3://doc-a", "text": text,
            "event_date": None, "chunk_version": cv}


def test_doc_cache_refuses_a_silent_rechunk_and_writes_nothing(tmp_path, monkeypatch):
    import pytest
    from leviathan.graphrag import write_guard as wg
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    h = hashlib.md5(b"s3://doc-a").hexdigest()
    _seed_cache(tmp_path, h, [_cached_prop("old text one", "5228db6450c4-20260709"),
                              _cached_prop("old text two", "5228db6450c4-20260709")])
    before = (tmp_path / "chunks" / f"{h}.jsonl").read_bytes()
    new = {"s3://doc-a": [_cached_prop("rewritten text", "e4b681f37a06-20260719")]}

    with pytest.raises(wg.WriteRefused) as exc:
        eb._write_doc_cache(new, chunk_version="e4b681f37a06-20260719")
    assert (tmp_path / "chunks" / f"{h}.jsonl").read_bytes() == before          # atomic: nothing written
    joined = " ".join(exc.value.lines)
    assert "RE-CHUNK of an already-cached document" in joined and "5228db6450c4-20260709" in joined
    assert "--rechunk" in joined and "versioning is Suspended" in joined        # names the fix AND the risk


def test_doc_cache_rechunk_is_permitted_when_declared_and_is_recorded(tmp_path, monkeypatch):
    from leviathan.graphrag import write_guard as wg
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    h = hashlib.md5(b"s3://doc-a").hexdigest()
    _seed_cache(tmp_path, h, [_cached_prop("old one", None), _cached_prop("old two", None)])
    mf = wg.RunManifest("unit")
    n = eb._write_doc_cache({"s3://doc-a": [_cached_prop("new", "e4b681f37a06-20260719")]},
                            chunk_version="e4b681f37a06-20260719", allow_rechunk=True, manifest=mf)
    assert n == 1 and len(eb._read_doc_cache("s3://doc-a")) == 1
    assert mf.docs["overwritten"] == 1 and mf.docs["per_doc_delta"]["s3://doc-a"] == -1
    assert mf.docs["vintage_transitions"] == {"None -> e4b681f37a06-20260719": 1}


def test_doc_cache_same_vintage_and_new_documents_are_never_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    cv = "e4b681f37a06-20260719"
    h = hashlib.md5(b"s3://doc-a").hexdigest()
    _seed_cache(tmp_path, h, [_cached_prop("a", cv)])
    # same vintage over the same doc = a top-up, not a re-chunk; a doc absent from the cache = a fill
    fresh = {"id": "y", "date": "2024-01-01", "source": "GAIN", "source_key": "s3://doc-b", "text": "b",
             "event_date": None, "chunk_version": cv}
    assert eb._write_doc_cache({"s3://doc-a": [_cached_prop("a", cv), _cached_prop("a2", cv)],
                                "s3://doc-b": [fresh]}, chunk_version=cv) == 3


# ── G1d: the COMMODITY wholesale write, and G3a: the routing dry-run ───────────────────────────────────
def _wire_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "all_nodes", lambda: ["corn", "soybeans"])
    monkeypatch.setattr(ev, "match_forms",
                        lambda n: {"corn": ["corn", "maize"], "soybeans": ["soybean", "soy"]}[n])
    (tmp_path / "chunks").mkdir(parents=True, exist_ok=True)


def _seed_corn(tmp_path, n, hash_name="aaa"):
    recs = [{"id": f"{hash_name}#{i}", "date": "2024-01-01", "source": "WASDE", "source_key": f"D{i}",
             "text": f"US corn note {i}", "event_date": None, "event_date_precision": None}
            for i in range(n)]
    (tmp_path / "chunks" / f"{hash_name}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in recs), encoding="utf-8")


def test_commodity_write_is_guarded_and_a_collapse_is_refused(tmp_path, monkeypatch):
    """G1d: the 24 top-level commodity slices are 11.1 GB -- LARGER than the whole drivers/ layer -- and
    supply 24 of the artifact's 125 nodes (arabica_coffee, robusta_coffee, cocoa among them). The plan cited
    their empty guard as the TEMPLATE for the driver one and never gave them coverage of their own."""
    import pytest
    from leviathan.graphrag import write_guard as wg
    _wire_rebuild(tmp_path, monkeypatch)
    _seed_corn(tmp_path, 40)
    assert eb.rebuild_slices() == 40
    before = (tmp_path / "corn.jsonl").read_bytes()
    _seed_corn(tmp_path, 20)                                    # the cache halves -> the slice would halve
    with pytest.raises(wg.WriteRefused):
        eb.rebuild_slices()
    assert (tmp_path / "corn.jsonl").read_bytes() == before      # atomic: the 40-prop slice survives intact
    assert eb.rebuild_slices(allow_churn=0.60) == 20             # declared magnitude lets it through


def test_empty_node_is_skipped_not_clobbered(tmp_path, monkeypatch):
    # The evidence_batch.py:433 behaviour is PRESERVED exactly: a node that routes nothing keeps its prior
    # file. Refusing a whole rebuild over one empty node would be a regression, not a guard.
    _wire_rebuild(tmp_path, monkeypatch)
    _seed_corn(tmp_path, 5)
    assert eb.rebuild_slices() == 5
    assert not (tmp_path / "soybeans.jsonl").exists()            # never written empty
    (tmp_path / "soybeans.jsonl").write_text(json.dumps({"id": "keep", "text": "soy"}), encoding="utf-8")
    eb.rebuild_slices()
    assert json.loads((tmp_path / "soybeans.jsonl").read_text(encoding="utf-8"))["id"] == "keep"


def test_dark_tally_dry_run_routes_classifies_and_writes_nothing(tmp_path, monkeypatch):
    """G3a: --dark-tally is NOT a read-only flag -- its own help text says it applies to
    --retrieve/--reroute/--rebuild-slices, _flush_dark_tally runs AFTER the writes, and on --rebuild-slices
    that means re-embedding ~107K vectors and re-rolling all 125 slices, which (PYTHONHASHSEED unset) is a
    POPULATION CHANGE inside the sequencing law. The dry-run is how the baseline gets established for free:
    there has never been one -- eval/dark_tally* returns zero objects."""
    _wire_rebuild(tmp_path, monkeypatch)
    _seed_corn(tmp_path, 3)
    n = eb.rebuild_slices(tally=True, dry_run=True)
    assert n == 3                                               # routing happened
    assert not (tmp_path / "corn.jsonl").exists()               # ... and NOTHING was written
    assert not (tmp_path / "drivers").exists()
    tallies = list((tmp_path / "cfg" / "eval").glob("dark_tally_rebuild_*.json"))
    assert len(tallies) == 1                                    # the manifest is the whole point
    assert json.loads(tallies[0].read_text(encoding="utf-8"))["n_props"] == 3


# ── F1 + F2: EVERY layer of a pass is planned before ANY of them commits ───────────────────────────────
def _rt_rec(node, i, text=None):
    return {"id": f"{node}-{i}", "date": f"2024-01-{(i % 28) + 1:02d}", "source": "WASDE",
            "source_key": f"D{node}{i}", "text": text or f"US corn note {i} and freight rates",
            "event_date": None, "event_date_precision": None}


def _wire_route(tmp_path, monkeypatch, driver_terms=("freight",)):
    from leviathan.graphrag import display as dp
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "all_nodes", lambda: ["corn"])
    monkeypatch.setattr(ev, "match_forms", lambda n: ["corn", "maize"])
    monkeypatch.setattr(ev, "_driver_raw", lambda: {
        "drivers": {"freight": {"category": "logistics", "terms": list(driver_terms)}},
        "dag_alias": {"freight": ["ocean_freight"]}})
    monkeypatch.setattr(dp, "all_driver_ids", lambda: frozenset({"ocean_freight"}))
    ev._reset()


def test_raw_archive_is_a_guarded_layer_and_a_refusal_leaves_ALL_THREE_byte_identical(tmp_path, monkeypatch):
    """F2 + F1, driven live the way the reviewer drove them.

    F2: `_raw/` was the FOURTH wholesale seam -- 24 objects / 79,974,491 B written inside the node loop
    AHEAD of every guard, with no churn ratio, no span tuple, no empty guard and no manifest line. It also
    SURVIVED a refusal, so a refused pass left the store in a state where the next `--reroute` (which reads
    exactly `_raw/`) derived every downstream slice from new inputs.

    F1: the commodity layer completed all its writes before the driver guard was ever evaluated.

    Synthetic churn: a healthy seed pass, then a pass whose populations collapse. A refusal must now leave
    _raw/, the commodity slice AND the driver slice byte-identical -- all three layers, one raise."""
    import pytest
    from leviathan.graphrag import write_guard as wg
    _wire_route(tmp_path, monkeypatch)
    try:
        by_node = {"corn": [_rt_rec("corn", i) for i in range(40)]}
        assert eb._route_and_write(by_node) == 40
        before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*.jsonl")}
        assert set(before) == {"corn.jsonl", str(Path("_raw/corn.jsonl")), str(Path("drivers/freight.jsonl"))}

        collapsed = {"corn": [_rt_rec("corn", i) for i in range(10)]}     # -75% in every layer at once
        with pytest.raises(wg.WriteRefused) as exc:
            eb._route_and_write(collapsed)
        after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*.jsonl")}
        assert after == before                                  # NOT ONE of the three layers moved
        joined = " ".join(exc.value.lines)
        assert "nothing was written in ANY layer" in joined
        assert "_raw/corn" in joined                            # the archive is guarded in its own right
        assert "commodity/corn" in joined and "drivers/freight" in joined
        # ... and the declared magnitude lets the whole pass through, all three layers together
        assert eb._route_and_write(collapsed, allow_churn=0.80) == 10
        assert len(ev.load_index("_raw/corn")) == 10 and len(ev.load_index("drivers/freight")) == 10
    finally:
        ev._reset()


def test_route_and_write_raw_is_never_clobbered_empty(tmp_path, monkeypatch):
    """The _raw empty-node SKIP, matching the commodity path exactly: a node that archived nothing keeps its
    prior archive rather than being overwritten with an empty object. `by_node` from --retrieve can legally
    carry a node whose sampling gathered nothing, and that used to write `_raw/<node>` empty -- destroying
    the reroute derivation source for that node with no guard anywhere."""
    _wire_route(tmp_path, monkeypatch)
    try:
        assert eb._route_and_write({"corn": [_rt_rec("corn", i) for i in range(5)]}) == 5
        keep = (tmp_path / "_raw" / "corn.jsonl").read_bytes()
        eb._route_and_write({"corn": []})
        assert (tmp_path / "_raw" / "corn.jsonl").read_bytes() == keep
    finally:
        ev._reset()


# ── F11: a SAME-DAY re-chunk carries the same vintage, so the vintage check is blind to it ─────────────
def test_same_vintage_text_LOSS_is_refused_but_a_topup_is_not(tmp_path, monkeypatch):
    """G1a refused only when `prior_v != {chunk_version}`, and chunk_version is
    <corpus_fingerprint>-<UTC date> -- so two passes on ONE UTC day share a vintage and the guard was silent
    while prop ids, text and offsets all moved. A retried --retrieve on the day of a re-chunk is the
    likeliest real instance."""
    import pytest
    from leviathan.graphrag import write_guard as wg
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    cv = "e4b681f37a06-20260719"
    h = hashlib.md5(b"s3://doc-a").hexdigest()
    _seed_cache(tmp_path, h, [_cached_prop("old one", cv), _cached_prop("old two", cv)])
    before = (tmp_path / "chunks" / f"{h}.jsonl").read_bytes()

    with pytest.raises(wg.WriteRefused) as exc:                 # same vintage, but the prior texts are GONE
        eb._write_doc_cache({"s3://doc-a": [_cached_prop("rewritten", cv)]}, chunk_version=cv)
    assert (tmp_path / "chunks" / f"{h}.jsonl").read_bytes() == before
    joined = " ".join(exc.value.lines)
    assert "same vintage" in joined and "DROPS 2 of 2" in joined and "--rechunk" in joined

    # a pure ADDITION is a top-up, not a re-chunk -- unchanged behaviour, still silent
    assert eb._write_doc_cache({"s3://doc-a": [_cached_prop("old one", cv), _cached_prop("old two", cv),
                                               _cached_prop("brand new", cv)]}, chunk_version=cv) == 3
    # ... and --rechunk still takes the deliberate loss
    assert eb._write_doc_cache({"s3://doc-a": [_cached_prop("rewritten", cv)]},
                               chunk_version=cv, allow_rechunk=True) == 1


# -- LANE C: the commodity layer's row order (the twin of G5a) -------------------------------------------
# rebuild_slices iterates `for h in _cached_hashes()` over a SET of md5 hex strings and PYTHONHASHSEED is
# set nowhere in docker/, jobs/, src/, infra/, scripts/ or the production jobdef env, so the ROW ORDER of
# all 24 commodity slices (11,119,127,224 B) was per-process randomized. The driver layer stopped being
# order-dependent at G5a (plan_driver_slices -> ev._truncation_order); the commodity layer serialized
# whatever the set handed it. These pin the same doctrine on this side.
def _lane_c_rec(day, key, rid):
    return {"id": rid, "date": f"2024-03-{day:02d}", "source": "WASDE", "source_key": key,
            "text": f"US corn note {rid}", "event_date": None, "event_date_precision": None}


def test_commodity_payload_is_byte_identical_across_shuffled_input_order(tmp_path, monkeypatch):
    """Two SHUFFLED input orders produce byte-identical serialized output -- and the order is
    ev._truncation_order's, not a private copy of it, so the two layers share one convention."""
    import copy
    _wire_rebuild(tmp_path, monkeypatch)
    recs = [_lane_c_rec(5, "kb", "b"), _lane_c_rec(9, "ka", "a"),
            _lane_c_rec(1, "kc", "c"), _lane_c_rec(9, "ka", "z")]

    def _payload(order):
        plan = eb._plan_commodity_write({"corn": copy.deepcopy(order)}, backend="bow")
        return plan.payloads["corn"]()

    forward = _payload(recs)
    reversed_ = _payload(list(reversed(recs)))
    rotated = _payload(recs[2:] + recs[:2])
    assert forward == reversed_ == rotated                       # THE fix, stated as bytes
    ids = [json.loads(line)["id"] for line in forward.splitlines()]
    assert ids == ["a", "z", "b", "c"]                           # date DESC, ties by (source_key, id) ASC
    assert ids == [r["id"] for r in ev._truncation_order(recs)]  # ... i.e. exactly the driver-layer order


def test_rebuild_slices_is_byte_reproducible_across_cached_hash_iteration_order(tmp_path, monkeypatch):
    """End to end through the real seam: the same doc-cache visited in two different orders -- which is what
    an unseeded str hash does to _cached_hashes() between processes -- must write the same corn.jsonl."""
    _wire_rebuild(tmp_path, monkeypatch)
    docs = {"aaa": [_lane_c_rec(2, "D1", "aaa#0")], "bbb": [_lane_c_rec(7, "D2", "bbb#0")],
            "ccc": [_lane_c_rec(4, "D3", "ccc#0")]}
    for h, recs in docs.items():
        (tmp_path / "chunks" / f"{h}.jsonl").write_text("\n".join(json.dumps(r) for r in recs),
                                                        encoding="utf-8")
    order = list(docs)
    monkeypatch.setattr(eb, "_cached_hashes", lambda: list(order))
    assert eb.rebuild_slices() == 3
    first = (tmp_path / "corn.jsonl").read_bytes()
    order.reverse()                                              # a different set-iteration order
    assert eb.rebuild_slices() == 3
    assert (tmp_path / "corn.jsonl").read_bytes() == first
    # and the rows are the most-recent-first order the driver layer already used
    assert [json.loads(x)["id"] for x in first.decode("utf-8").splitlines()] == ["bbb#0", "ccc#0", "aaa#0"]


# ══ DEC-P0c WAVE 1 ═══════════════════════════════════════════════════════════════════════════════════════
# S3/S5 -- offsets. The needle below is a REAL prop-shaped span over a REAL excerpt of the 2026-05-12 WASDE
# text layer (`text/source=usda_wasde/release_date=2026-05-12/document.json`, chars 383-560): the document
# wraps "livestock,\npoultry," mid-sentence, Haiku copies it back with a space, and the raw `find` therefore
# misses a span that is byte-for-byte faithful. Measured over the pilot's 1,141 props: raw find alone =
# 25.7% exact; whitespace-tolerant = 79.8% locatable, 50 of 910 ambiguous, median stored span ~4,900 -> ~90.
_WASDE_RAW = ("prices for the 2026/27 marketing year. Also presented are the first calendar-year 2027 "
              "forecasts of U.S. livestock,\npoultry, and dairy products.")
_WASDE_NEEDLE = "forecasts of U.S. livestock, poultry, and dairy products."


def test_locate_span_recovers_a_line_wrapped_span_and_maps_back_to_raw_offsets():
    """The pdfplumber line break is the whole defect: `exact_ws` returns the RAW span, so the stored offsets
    still address `full_text` and slicing the document reproduces the wrapped original."""
    bstart = 383
    cs, ce, kind, cur = eb._locate_span(_WASDE_NEEDLE, _WASDE_RAW, bstart, bstart + len(_WASDE_RAW), 0)
    assert kind == "exact_ws"
    assert _WASDE_RAW[cs - bstart:ce - bstart] == "forecasts of U.S. livestock,\npoultry, and dairy products."
    assert ce - cs == len(_WASDE_NEEDLE)                           # one wrap: "\n" stands in for " ", same width
    assert cur == ce - bstart                                      # cursor advances past the hit, in block coords
    # ... and the pre-fix behaviour is exactly what it recovers: the raw find alone floors to the block
    assert _WASDE_RAW.find(_WASDE_NEEDLE) == -1


def test_locate_span_prefers_the_raw_find_and_falls_back_to_the_block_on_a_rewrite():
    """`exact` still wins when the span IS verbatim (no regex built, no behaviour change), and a genuine
    propositional rewrite still floors to the block span -- correction #5 is untouched."""
    cs, ce, kind, _ = eb._locate_span("Also presented are the first", _WASDE_RAW, 383, 383 + len(_WASDE_RAW), 0)
    assert kind == "exact" and _WASDE_RAW[cs - 383:ce - 383] == "Also presented are the first"
    cs, ce, kind, _ = eb._locate_span("Livestock output was revised", _WASDE_RAW, 383, 383 + len(_WASDE_RAW), 0)
    assert (cs, ce, kind) == (383, 383 + len(_WASDE_RAW), "block")


def test_locate_span_ambiguous_whitespace_match_keeps_the_block_fallback():
    """50 of 910 pilot hits occurred more than once. Two places it could be means naming neither: the block
    fallback is deterministic and honest where a first-hit guess would be neither."""
    block = "Corn exports\nrose sharply. Wheat fell. Corn exports\nrose sharply again."   # BOTH wrapped
    cs, ce, kind, cur = eb._locate_span("Corn exports rose sharply", block, 0, len(block), 0)
    assert (cs, ce, kind, cur) == (0, len(block), "block", 0)
    _cs, _ce, kind, _cur = eb._locate_span("Wheat fell", block, 0, len(block), 0)
    assert kind == "exact"                                         # one occurrence only -> recovered


def test_block_meta_stores_the_document_substring_not_the_joined_window():
    """S5: chunk_document joins packed atoms with a space (and a blank line for the last window) while
    char_start/char_end come from full_text.find(atom), so only 14 of 72 pilot windows satisfied
    full_text[char_start:char_end] == verbatim_span and 20 of 293 'exact' offsets did not reproduce from the
    document (one by 9,200 chars). _doc_blocks now hands the substring through, so every offset _locate_span
    returns is an offset INTO full_text by construction."""
    full = "Alpha para one.\n\nBeta para two.\n\nGamma para three."
    key = "text/source=usda_wasde/release_date=2024-03-08/document.json"
    blocks = eb._doc_blocks(None, "_docs", key, matcher=None, doc={"full_text": full})
    assert blocks
    for blk, meta, btext in blocks:
        assert btext == full[blk.char_start:blk.char_end]           # THE property, stated as an equality
        m = eb._block_meta(meta, blk, btext)
        assert full[m["block_start"]:m["block_end"]] == m["block_text"]


def test_doc_blocks_stamps_the_date_kind_and_records_a_floor(tmp_path, monkeypatch):
    """S1's flag half, at the seam that mints it: a parsed key stamps kind=key and NOTHING is tallied; a
    refusing key stamps a floor AND lands in the tally by key + layout (law #7 applied to the PIT field)."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    t = eb.DarkTally()
    wasde = "text/source=usda_wasde/release_date=2026-05-12/document.json"
    _blk, meta, _b = eb._doc_blocks(None, "_docs", wasde, doc={"full_text": "Corn stocks rose."}, tally=t)[0]
    assert meta["date"] == "2026-05-12" and meta["date_kind"] == "key" and meta["date_layout"] == "release_date"
    assert t.date_floors == {}
    conab = "text/source=conab/crop_year=2025_26/survey=01/document.json"
    _blk, meta, _b = eb._doc_blocks(None, "_docs", conab, doc={"full_text": "Cafe arabica."}, tally=t)[0]
    assert meta["date"] == "2025-01-01" and meta["date_kind"] == "year_floor"
    assert t.date_floors == {conab: "year_floor/conab_survey_is_not_a_month"}
    assert t.manifest()["n_docs_date_floored"] == 1


# ── S2: the window-loss tally and its ONE retry ────────────────────────────────────────────────────────
def _msg(text, stop_reason="end_turn"):
    return types.SimpleNamespace(stop_reason=stop_reason,
                                 content=[types.SimpleNamespace(type="text", text=text)])


def _res(cid, text, stop_reason="end_turn", rtype="succeeded"):
    return types.SimpleNamespace(custom_id=cid,
                                 result=types.SimpleNamespace(type=rtype, message=_msg(text, stop_reason)))


class _FakeBatches:
    """A batch API that answers a DIFFERENT result set per created batch id, so the retry leg is exercised
    for real rather than stubbed: `results_by_bid[bid]` is what that batch returns."""

    def __init__(self, results_by_bid, *, next_id="retry_1"):
        self.results_by_bid = results_by_bid
        self.next_id = next_id
        self.created: list = []

    def create(self, *, requests):
        self.created.append(requests)
        return types.SimpleNamespace(id=self.next_id)

    def retrieve(self, bid):
        return types.SimpleNamespace(processing_status="ended")

    def results(self, bid):
        return self.results_by_bid.get(bid, [])


def _wire_retrieve(tmp_path, monkeypatch):
    monkeypatch.setattr(eb, "_OUT", tmp_path)
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path / "ev")
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(ev, "_aliases", lambda node: ["arabica"])


def _one_block_manifest(tmp_path, cids, block):
    man = {cid: {"contract": "arabica_coffee", "source_key": "s3://k", "source": "GAIN", "date": "2021-05-19",
                 "date_kind": "key", "date_layout": "publication_date",
                 "block_text": block, "block_start": 0, "block_end": len(block)} for cid in cids}
    (tmp_path / "b.json").write_text(json.dumps({"batch_id": "b", "manifest": man}), encoding="utf-8")
    return man


def test_window_states_are_counted_and_a_legitimate_empty_is_not_a_loss(tmp_path, monkeypatch):
    """Four windows, four states. The pilot's headline: 15 of 72 windows (20.8%) were BILLED and emitted
    nothing -- 9 truncated at max_tokens (36,864 output tokens discarded) and 6 unparseable -- and NOT ONE
    returned a legitimate empty array, so the silent-`[]` path was carrying pure loss. `_parse_json_array`
    flattens all three cases to the same `[]`; only stop_reason plus a real json.loads separates them."""
    _wire_retrieve(tmp_path, monkeypatch)
    block = "Brazil frost devastated arabica coffee crops in 2021."
    _one_block_manifest(tmp_path, ["r000000", "r000001", "r000002", "r000003"], block)
    results = [_res("r000000", '[{"proposition":"Brazil frost hit arabica coffee.","verbatim_span":"Brazil frost"}]'),
               _res("r000001", "[]"),                                          # a LEGITIMATE empty
               _res("r000002", '[{"proposition":"Arabica out', "max_tokens"),   # truncated mid-object
               _res("r000003", "here are the propositions: {oops")]            # end_turn, unparseable
    client = types.SimpleNamespace(messages=types.SimpleNamespace(
        batches=_FakeBatches({"b": results, "retry_1": []})))

    assert eb.retrieve(None, client, "b", retry_lost=False) == 1               # counting leg only

    assert [eb._classify_result(r)[0] for r in results] == \
        ["ok", "empty_legitimate", "truncated", "unparseable"]
    assert eb._empty_is_legitimate("[]") and not eb._empty_is_legitimate("{oops")


def test_truncated_window_is_retried_as_two_halves_and_recovered(tmp_path, monkeypatch):
    """A truncated window is DETERMINISTIC -- re-submitting it unchanged refills the same 4,096 output tokens
    and cuts in the same place -- so the retry splits it, which reuses the request contract exactly where
    raising max_tokens would move the cost shape of all ~13k requests. The halves' props land under the
    ORIGINAL custom_id, so parent_id and the `#i` ids stay stable and unique across the two halves."""
    _wire_retrieve(tmp_path, monkeypatch)
    block = ("Brazil frost devastated arabica coffee crops in 2021.\n\n"
             "Colombia arabica coffee exports rose in 2022.")
    man = _one_block_manifest(tmp_path, ["r000000"], block)
    first = [_res("r000000", '[{"proposition":"Brazil frost devastated arabica', "max_tokens")]
    retry = [_res("r000000_x0", '[{"proposition":"Brazil frost devastated arabica coffee crops in 2021.",'
                                '"verbatim_span":"Brazil frost devastated arabica coffee crops in 2021."}]'),
             _res("r000000_x1", '[{"proposition":"Colombia arabica coffee exports rose in 2022.",'
                                '"verbatim_span":"Colombia arabica coffee exports rose in 2022."}]')]
    fake = _FakeBatches({"b": first, "retry_1": retry})
    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=fake))

    n = eb.retrieve(None, client, "b")

    assert len(fake.created) == 1 and len(fake.created[0]) == 2                 # ONE retry batch, TWO halves
    halves = [r["params"]["messages"][0]["content"] for r in fake.created[0]]
    assert "".join(halves) == block                                             # no character is dropped
    assert all(r["params"]["max_tokens"] == eb._MAX_OUTPUT_TOKENS for r in fake.created[0])
    recs = [json.loads(x) for x in (tmp_path / "ev" / "arabica_coffee.jsonl").read_text(encoding="utf-8").splitlines()]
    assert n == 2 and {r["id"] for r in recs} == {"r000000#0", "r000000#1"}     # ids unique ACROSS the halves
    second = next(r for r in recs if "Colombia" in r["text"])                   # offsets absolute in the DOC ...
    assert block[second["char_start"]:second["char_end"]] == "Colombia arabica coffee exports rose in 2022."
    assert man["r000000"]["block_end"] == len(block)                            # ... and the manifest untouched


def test_unparseable_window_is_resubmitted_once_and_the_verdict_is_recorded(tmp_path, monkeypatch):
    """The transient-vs-deterministic split for the `end_turn`-but-unparseable class is UNMEASURED (the pilot
    saw 6 and retried none), so the retry IS the measurement: a recovery says transient, a second failure
    says deterministic, and the tally records which without failing the pass over it."""
    _wire_retrieve(tmp_path, monkeypatch)
    block = "Brazil frost devastated arabica coffee crops in 2021."
    _one_block_manifest(tmp_path, ["r000000", "r000001"], block)
    first = [_res("r000000", "sure! here you go: {"), _res("r000001", "also broken <<<")]
    retry = [_res("r000000_x0", '[{"proposition":"Brazil frost hit arabica coffee.","verbatim_span":"Brazil frost"}]'),
             _res("r000001_x0", "still broken <<<")]                            # deterministic: stays lost
    fake = _FakeBatches({"b": first, "retry_1": retry})
    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=fake))

    eb.retrieve(None, client, "b")

    assert len(fake.created[0]) == 2                                            # ONE request each, AS IS
    assert [r["params"]["messages"][0]["content"] for r in fake.created[0]] == [block, block]
    recs = [json.loads(x) for x in (tmp_path / "ev" / "arabica_coffee.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1 and recs[0]["id"] == "r000000#0"                      # the transient one recovered


def test_batch_tally_summary_names_every_state_and_the_survivors():
    """The tally itself, unit-level: five mutually exclusive states, the retry outcomes, and the custom_ids
    still lost AFTER the retry -- which is the line the 3,800-doc run has to be able to read."""
    t = eb.BatchTally(windows_submitted=4)
    for state in ("ok", "empty_legitimate", "truncated", "unparseable"):
        t.note(state)
    t.note_lost("r000002", "truncated")
    t.note_lost("r000003", "unparseable")
    t.props_emitted = 20
    t.note_recovered("r000002", "truncated")
    s = t.summary()
    assert s["counts"] == {"ok": 1, "empty_legitimate": 1, "truncated": 1, "unparseable": 1, "failed": 0}
    assert s["windows_submitted"] == 4 and s["props_emitted"] == 20
    assert s["retries"]["truncated_recovered"] == 1 and s["retries"]["unparseable_recovered"] == 0
    assert s["retries"]["partial_recovery"] == 0 and s["retries"]["retry_batch_failed"] == 0
    assert s["lost_after_retry"] == 1 and s["lost_custom_ids"] == {"r000003": "unparseable"}


def test_a_failing_retry_batch_does_not_discard_the_windows_that_parsed(tmp_path, monkeypatch):
    """The first batch is ALREADY BILLED when the retry leg runs. An API error there must not throw away the
    windows that came back clean -- the loss stays counted, the failure is named, the props survive."""
    _wire_retrieve(tmp_path, monkeypatch)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    block = "Brazil frost devastated arabica coffee crops in 2021."
    _one_block_manifest(tmp_path, ["r000000", "r000001"], block)

    class _Exploding(_FakeBatches):
        def create(self, *, requests):
            raise RuntimeError("overloaded_error")

    from leviathan.graphrag import write_guard as wg
    mf = wg.RunManifest("unit")
    results = [_res("r000000", '[{"proposition":"Brazil frost hit arabica coffee.","verbatim_span":"Brazil frost"}]'),
               _res("r000001", "broken <<<")]
    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=_Exploding({"b": results})))

    assert eb.retrieve(None, client, "b", manifest=mf) == 1                    # the clean window still landed
    w = mf.extraction["windows"]
    assert w["retries"]["retry_batch_failed"] == 1 and w["lost_after_retry"] == 1


def test_a_half_recovered_split_is_counted_as_PARTIAL_not_as_a_recovery(tmp_path, monkeypatch):
    """A truncated window split in two whose SECOND half also fails gives its props back -- some of them.
    Calling that a recovery would re-open the exact hole the tally exists to close, so it is counted
    separately, and there is no second retry."""
    _wire_retrieve(tmp_path, monkeypatch)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    block = ("Brazil frost devastated arabica coffee crops in 2021.\n\n"
             "Colombia arabica coffee exports rose in 2022.")
    _one_block_manifest(tmp_path, ["r000000"], block)
    first = [_res("r000000", '[{"proposition":"Brazil frost devastated arabica', "max_tokens")]
    retry = [_res("r000000_x0", '[{"proposition":"Brazil frost devastated arabica coffee crops in 2021.",'
                                '"verbatim_span":"Brazil frost devastated arabica coffee crops in 2021."}]'),
             _res("r000000_x1", '[{"proposition":"Colombia arabica', "max_tokens")]      # STILL truncated
    from leviathan.graphrag import write_guard as wg
    mf = wg.RunManifest("unit")
    client = types.SimpleNamespace(messages=types.SimpleNamespace(
        batches=_FakeBatches({"b": first, "retry_1": retry})))

    assert eb.retrieve(None, client, "b", manifest=mf) == 1                    # only the first half came back
    r = mf.extraction["windows"]["retries"]
    assert r["truncated_split"] == 1 and r["truncated_recovered"] == 1 and r["partial_recovery"] == 1


def test_retrieve_records_the_window_tally_into_the_run_manifest(tmp_path, monkeypatch):
    """G1c's manifest is where a pass's numbers go, so the window states go there too -- otherwise "the batch
    produced fewer props than the census predicted" stays unanswerable without a re-measurement."""
    from leviathan.graphrag import write_guard as wg
    _wire_retrieve(tmp_path, monkeypatch)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    block = "Brazil frost devastated arabica coffee crops in 2021."
    _one_block_manifest(tmp_path, ["r000000"], block)
    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=_FakeBatches(
        {"b": [_res("r000000", '[{"proposition":"Brazil frost hit arabica coffee.","verbatim_span":"Brazil frost"}]')]})))
    mf = wg.RunManifest("unit")
    eb.retrieve(None, client, "b", manifest=mf)
    assert mf.extraction["windows"]["counts"]["ok"] == 1 and mf.extraction["windows"]["props_emitted"] == 1
    assert mf.payload()["extraction"]["windows"]["windows_submitted"] == 1


# ── S9: _read_doc counts and retries, and a run that under-covers its corpus REFUSES ───────────────────
class _FlakyS3:
    """Fails the first `fail_times` GETs of each key, then succeeds -- the transient blip the pilot hit twice
    in fourteen documents."""

    def __init__(self, bodies, fail_times=0, always_fail=(), listed=()):
        self.bodies, self.fail_times, self.always_fail = bodies, fail_times, set(always_fail)
        self.listed = list(listed)
        self.seen: dict = {}

    def get_paginator(self, _op):                                       # store_path_index's LIST of text/
        return types.SimpleNamespace(
            paginate=lambda **kw: [{"Contents": [{"Key": k} for k in self.listed]}])

    def get_object(self, *, Bucket, Key):
        self.seen[Key] = self.seen.get(Key, 0) + 1
        if Key in self.always_fail or self.seen[Key] <= self.fail_times:
            raise RuntimeError("transient S3 blip")
        return {"Body": types.SimpleNamespace(read=lambda: json.dumps(self.bodies[Key]).encode())}


def test_read_doc_retries_once_and_records_the_recovery(monkeypatch):
    monkeypatch.setattr(eb.time, "sleep", lambda s: None)
    key = "text/source=usda_wasde/release_date=2026-05-12/document.json"
    s3 = _FlakyS3({key: {"full_text": "Corn stocks rose."}}, fail_times=1)
    reads = eb.DocReadTally()
    assert eb._read_doc(s3, key, reads=reads)["full_text"] == "Corn stocks rose."
    assert s3.seen[key] == 2 and reads.retried == {key: 1} and reads.dropped == {}
    assert reads.summary()["recovered_on_retry"] == 1 and reads.drop_rate() == 0.0


def test_read_doc_drop_is_counted_by_key_not_swallowed(monkeypatch):
    """It used to catch Exception and return None; _doc_blocks returned [] and the document vanished from
    the batch with no tally line anywhere."""
    monkeypatch.setattr(eb.time, "sleep", lambda s: None)
    key = "text/source=usda_wap/release_month=2026-07/document.json"
    reads = eb.DocReadTally()
    assert eb._read_doc(_FlakyS3({}, always_fail=[key]), key, reads=reads) is None
    assert list(reads.dropped) == [key] and "transient S3 blip" in reads.dropped[key]
    assert reads.drop_rate() == 1.0


def test_a_run_dropping_over_one_percent_of_its_documents_refuses_before_it_bills():
    """FAIL-CLOSED. The refusal is raised BEFORE batches.create, so a pass that could not read its corpus
    exits nonzero having billed nothing -- an under-covering run is not a smaller run, it is a wrong one."""
    import pytest
    reads = eb.DocReadTally()
    for i in range(200):
        reads.note_read(f"k{i}")
    for j in range(3):
        reads.note_dropped(f"k_bad_{j}", RuntimeError("blip"))             # 3/203 = 1.48% > 1%
    with pytest.raises(SystemExit) as exc:
        reads.raise_if_over()
    assert "REFUSED" in str(exc.value) and "nothing was billed" in str(exc.value)
    ok = eb.DocReadTally()
    for i in range(200):
        ok.note_read(f"k{i}")
    ok.note_dropped("k_bad", RuntimeError("blip"))                         # 1/201 = 0.50% -> under the ceiling
    ok.raise_if_over()


def test_submit_refuses_a_read_starved_pass_and_creates_no_batch(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(eb, "_OUT", tmp_path)
    monkeypatch.setattr(eb.time, "sleep", lambda s: None)
    monkeypatch.setattr(eb, "_cached_hashes", lambda: set())
    keys = [f"text/source=usda_wasde/release_date=2026-05-{d:02d}/document.json" for d in range(1, 6)]
    monkeypatch.setattr(ev, "sample_keys", lambda *a, **k: keys)
    monkeypatch.setattr(ev, "windows_for", lambda n: [])
    monkeypatch.setattr(ev, "n_docs_for", lambda n, d: 5)
    monkeypatch.setattr(ev, "match_forms", lambda n: ["corn"])
    fake = _FakeBatches({})
    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=fake))
    with pytest.raises(SystemExit):
        eb.submit(_FlakyS3({}, always_fail=keys), client, nodes=["corn"], n_docs=5)
    assert fake.created == []                                          # not one request was ever submitted


# ── the chunk-once DEDUP gate: two layers, one alias record ────────────────────────────────────────────
_GAIN_A = ("text/source=usda_gain_soybean_meal/country=AR/publication_date=20000605/"
           "document=oilseeds_and_products_annual_buenos_aires_argentina_05-31-2000/document.json")
_GAIN_B = ("text/source=usda_gain_soybeans/country=AR/publication_date=20000605/"
           "document=oilseeds_and_products_annual_buenos_aires_argentina_05-31-2000/document.json")


def test_path_fingerprint_is_the_key_minus_its_source_segment():
    """doc_census verified BY GET that co-filed rows carry byte-identical full_text, so this is a real
    identity. These two REAL keys are the store's own proof case: one 35,697-char text, both in chunks/
    under different md5 names, carrying 103 and 140 props -- Haiku paid twice, two different answers."""
    assert eb._path_fingerprint(_GAIN_A) == eb._path_fingerprint(_GAIN_B)
    assert eb._path_fingerprint(_GAIN_A).startswith("text/country=AR/")
    assert eb._path_fingerprint("text/source=usda_wasde/release_date=2026-05-12/document.json") != \
        eb._path_fingerprint("text/source=usda_wasde/release_date=2026-06-11/document.json")


def test_dedup_gate_catches_both_layers_and_records_an_alias(tmp_path, monkeypatch):
    """(a) the PATH layer is intra-run, which is exactly what `_cached_hashes` structurally cannot cover --
    it is built once, before the loop, so two co-filings sampled in ONE run both miss it (279 such rows sit
    inside the never-chunked work set). (b) the CONTENT layer catches a byte-identical twin under a
    different path, against this run AND the persisted store index."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    text = "Argentina soybean meal crush rose in 2000."
    g = eb.DedupGate(content_index={}, alias_map={})
    assert g.check(_GAIN_A, text) is None                              # first sighting: not a dup
    g.claim(_GAIN_A, text)
    assert g.check(_GAIN_B, text) == _GAIN_A                           # (a) same fingerprint, other source
    # (b) different path, identical bytes -- and an EARLIER publication_date, so the keeper rule folds it
    # into _GAIN_A rather than deposing it (see _canonical_twin and the both-orders test below).
    other = "text/source=usda_gain_palm_oil/country=ID/publication_date=20000318/document=x/document.json"
    assert g.check(other, text) == _GAIN_A
    assert g.check("text/source=usda_gain_rice/country=VN/publication_date=20110401/document=y/document.json",
                   "a genuinely different document") is None
    assert g.by_layer == {"path": 1, "store_path": 0, "content": 1} and len(g.aliases) == 2
    g.flush()
    assert eb.load_alias_map()[_GAIN_B] == _GAIN_A                     # persisted, and readable by retrieve()
    rows = {r["source_key"]: r for r in ev.load_index(eb._ALIAS_NODE)}
    assert rows[other]["folded_date"] == "2000-03-18"                  # the record says WHAT was folded ...
    assert rows[other]["canonical_date"] == "2000-06-05" and rows[other]["layer"] == "content"
    # ... and the content index survives the process, which is the only way a CROSS-RUN twin is catchable:
    # chunks/ holds no full_text, so a cached document's sha1 is not recomputable from the cache. It is only
    # HONOURED once the canonical really has props, though -- an index row is written at SUBMIT, before any
    # prop exists, so a cancelled batch would otherwise alias every future twin into permanent emptiness.
    assert eb.DedupGate().check(other, text) is None                   # canonical not in chunks/ yet: WITHHELD
    eb._write_doc_cache({_GAIN_A: [{"id": "x", "date": "2000-06-05", "source": "GAIN", "source_key": _GAIN_A,
                                    "text": "Argentina soybeans crush rose.", "event_date": None}]})
    assert eb.DedupGate().check(other, text) == _GAIN_A                # the canonical is real: aliased


def test_store_path_index_catches_the_straddlers_with_two_lists_and_no_gets(tmp_path, monkeypatch):
    """The 162 measured STRADDLERS: a never-chunked row whose twin was chunked in an EARLIER pass.
    `_cached_hashes` is keyed on md5(source_key) and the twin's key differs by exactly the `source=` segment,
    so it cannot see them; the intra-run path set cannot either. The join is md5(corpus key) against the
    chunks/ listing -- the same 0-GET join x2_cost used to rebuild the 7,056/2,815/4,241 split."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(eb, "_cached_hashes", lambda: {hashlib.md5(_GAIN_A.encode("utf-8")).hexdigest()})
    s3 = _FlakyS3({}, listed=[_GAIN_A, _GAIN_B, "text/source=usda_wasde/release_date=2026-05-12/document.json"])
    idx = eb.store_path_index(s3)
    assert idx == {eb._path_fingerprint(_GAIN_A): _GAIN_A}             # only the CHUNKED key is canonical
    assert s3.seen == {}                                              # ... and not one GET was taken
    g = eb.DedupGate(content_index={}, alias_map={}, store_paths=idx)
    assert g.check(_GAIN_B, "any text at all") == _GAIN_A              # the straddler is aliased, not chunked
    assert g.by_layer["store_path"] == 1
    assert g.check(_GAIN_A, "any text at all") is None                 # the canonical never aliases to itself


def test_build_requests_aliases_a_twin_instead_of_billing_it_twice(tmp_path, monkeypatch):
    """End to end through the real seam: two nodes sample the two co-filings of ONE document in ONE run.
    Before the gate both were chunked; now the second is aliased and only the first is billed."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(eb, "_cached_hashes", lambda: set())
    monkeypatch.setattr(ev, "windows_for", lambda n: [])
    monkeypatch.setattr(ev, "n_docs_for", lambda n, d: 1)
    monkeypatch.setattr(ev, "match_forms", lambda n: ["soybean", "soy"])
    monkeypatch.setattr(ev, "sample_keys",
                        lambda s3, *, node, **k: [_GAIN_A] if node == "soybean_meal" else [_GAIN_B])
    body = {"full_text": "Argentina soybean meal and soybeans crush rose in 2000."}
    s3 = _FlakyS3({_GAIN_A: body, _GAIN_B: body})
    dedup = eb.DedupGate(content_index={}, alias_map={})
    _reqs, man, sampling = eb._build_requests(s3, ["soybean_meal", "soybeans"], 1, 0, dedup=dedup)

    assert {m["source_key"] for m in man.values()} == {_GAIN_A}        # ONE document chunked, not two
    assert dedup.aliases == {_GAIN_B: _GAIN_A} and dedup.by_layer["path"] == 1
    assert sampling["soybeans"] == [_GAIN_B]                          # the node still SAMPLED its own key ...
    dedup.flush()
    # ... and the alias is what lets retrieve()'s gather still hand that node the twin's props
    eb._write_doc_cache({_GAIN_A: [{"id": "x", "date": "2000-06-05", "source": "GAIN", "source_key": _GAIN_A,
                                    "text": "Argentina soybeans crush rose.", "event_date": None}]})
    aliases = eb.load_alias_map()
    assert [p["text"] for p in eb._read_doc_cache(aliases.get(_GAIN_B, _GAIN_B))] == \
        ["Argentina soybeans crush rose."]


def test_retrieve_gather_resolves_a_sampled_key_through_the_alias_map(tmp_path, monkeypatch):
    """The fan-out, proven at the routing seam rather than asserted in a comment: the node that sampled the
    ALIASED key still gets a slice, because the gather resolves through `_index/doc_aliases` first."""
    _wire_retrieve(tmp_path, monkeypatch)
    monkeypatch.setattr(ev, "_aliases", lambda node: {"soybeans": ["soy"], "soybean_meal": ["soymeal"]}.get(node, []))
    ev._evid_write(eb._ALIAS_NODE, json.dumps({"source_key": _GAIN_B, "canonical_key": _GAIN_A}))
    man = {"r000000": {"contract": "soybean_meal", "source_key": _GAIN_A, "source": "GAIN",
                       "date": "2000-06-05", "block_text": None, "block_start": None, "block_end": None}}
    (tmp_path / "b.json").write_text(json.dumps({"batch_id": "b", "manifest": man,
        "sampling": {"soybean_meal": [_GAIN_A], "soybeans": [_GAIN_B]}}), encoding="utf-8")
    text = '[{"proposition":"Argentina soybeans and soybean meal crush rose.","verbatim_span":"x"}]'
    client = types.SimpleNamespace(messages=types.SimpleNamespace(batches=_FakeBatches({"b": [_res("r000000", text)]})))

    eb.retrieve(None, client, "b")

    soy = (tmp_path / "ev" / "soybeans.jsonl")
    assert soy.exists() and "crush rose" in soy.read_text(encoding="utf-8")     # the ALIASED node still routed


# ── the content layer's THREE obligations: PIT order, liveness, and counting once ──────────────────────
# The reviewer's reproduction, pinned. Two REAL keys: one document, byte-identical text, filed under two
# publication_date partitions 19 days apart -- and the document's own name says 06-19-2000, so the 06-01
# partition is the wrong one. 997 such groups / 2,226 rows were measured across the corpus.
_COFFEE_EARLY = ("text/source=usda_gain_coffee/country=BR/publication_date=20000601/"
                 "document=coffee_annual_sao_paulo_ato_brazil_06-19-2000/document.json")
_COFFEE_LATE = ("text/source=usda_gain_coffee/country=BR/publication_date=20000620/"
                "document=coffee_annual_sao_paulo_ato_brazil_06-19-2000/document.json")


def test_the_content_twin_that_survives_is_the_latest_dated_one_in_both_orders(tmp_path, monkeypatch):
    """THE PIT REGRESSION, closed. `claim()` was first-writer-wins, so which of two byte-identical twins
    survived -- and therefore which `date` every one of its props carried -- was decided by node/sample
    ITERATION ORDER. It was reproduced in BOTH directions on this pair: one order stamps every prop
    2000-06-01, nineteen days before the document existed, in exactly the field retrieve()'s asof filter
    and the pg WHERE compare, i.e. leakage-permissive.

    The rule is the estate's own, already ratified for this population one layer down:
    jobs/utils/deduplicate_gain_s3.py keeps the copy with the LATEST publication_date when byte-identical
    GAIN copies sit in two partitions. Same question, same answer, plus a tie-break on the key so the
    outcome depends on nothing at all except the two keys."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    assert eb._canonical_twin(_COFFEE_EARLY, _COFFEE_LATE) == _COFFEE_LATE      # symmetric, by construction
    assert eb._canonical_twin(_COFFEE_LATE, _COFFEE_EARLY) == _COFFEE_LATE
    text = "Brazil coffee production is forecast higher for 2000/01."
    for order in ([_COFFEE_EARLY, _COFFEE_LATE], [_COFFEE_LATE, _COFFEE_EARLY]):
        g = eb.DedupGate(content_index={}, alias_map={}, cached=set())
        for key in order:                                          # the real build-loop shape: check, then
            if not g.check(key, text):                             # claim only what was not aliased away
                g.claim(key, text)
        assert g.aliases == {_COFFEE_EARLY: _COFFEE_LATE}, f"order {order} folded the wrong way"
        row = g.alias_rows[_COFFEE_EARLY]
        assert row["canonical_key"] == _COFFEE_LATE and row["layer"] == "content"
        assert row["folded_date"] == "2000-06-01"                  # the record carries WHAT was folded ...
        assert row["canonical_date"] == "2000-06-20"               # ... and what it was folded into


def test_a_content_alias_is_refused_when_neither_twin_carries_a_parseable_date(tmp_path, monkeypatch):
    """CHUNK-ONCE YIELDS TO PIT. `conab_survey_is_not_a_month` and `year_only` are documented refusals, so
    those documents floor to Jan-1 of their year -- a SENTINEL that can sit on either side of a twin's real
    date. There is no "latest" to keep, so the alias is refused and both documents are chunked, each
    carrying its own honest date: two Haiku bills over one date nobody can defend. 62 of 7,056 documents
    are in this class after the D-EC pub-date deriver."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    conab = "text/source=conab/crop_year=2024_25/survey=03/document.json"
    mpob = "text/source=mpob/release_type=overview_pdf/year=2016/document.json"
    gain = "text/source=usda_gain_palm_oil/country=MY/publication_date=20160131/document=z/document.json"
    assert ev.pub_date_layout(conab)[1] == "conab_survey_is_not_a_month"
    assert ev.pub_date_layout(mpob)[1] == "year_only"
    text = "Palm oil closing stocks fell month on month."
    g = eb.DedupGate(content_index={}, alias_map={}, cached=set())
    assert g.check(conab, text) is None
    g.claim(conab, text)
    assert g.check(mpob, text) is None                              # sentinel vs sentinel: no dominance
    assert g.check(gain, text) is None                              # a real date vs a sentinel: still none
    assert g.aliases == {} and g.by_layer == {"path": 0, "store_path": 0, "content": 0}
    assert g.pit_refusals == {mpob: conab, gain: conab}
    assert g.summary()["pit_refusals"] == {gain: conab, mpob: conab}
    assert eb._canonical_twin(conab, mpob) is None and eb._canonical_twin(gain, conab) is None


def test_a_canonical_with_no_props_is_never_aliased_into(tmp_path, monkeypatch):
    """THE SILENT PERMANENT DROP, closed. The content index is persisted at SUBMIT -- before a single prop
    exists -- so a cancelled or expired batch used to poison it forever: every future twin was skipped
    silently, its alias resolved to a `chunks/` object that was never written, `ev._evid_read` returned ''
    for the missing key, `_read_doc_cache` yielded [] and the node printed `SKIPPED (empty)`. The content
    layer now fires only when the canonical is already in chunks/ or has been queued by this same pass, and
    the withheld twin is COUNTED rather than skipped."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    text = "Argentina soybean meal crush rose in 2000."
    twin = "text/source=usda_gain_palm_oil/country=ID/publication_date=19990318/document=x/document.json"
    poisoned = {eb._content_hash(text): _GAIN_A}                    # a submit whose batch never retrieved
    g = eb.DedupGate(content_index=dict(poisoned), alias_map={})    # ... and an EMPTY chunks/
    assert g.check(twin, text) is None                              # withheld: it gets chunked on its own
    assert g.aliases == {} and g.unchunked_canonicals == {twin: _GAIN_A}
    assert g.summary()["unchunked_canonicals"] == {twin: _GAIN_A}
    eb._write_doc_cache({_GAIN_A: [{"id": "x", "date": "2000-06-05", "source": "GAIN", "source_key": _GAIN_A,
                                    "text": "Argentina soybeans crush rose.", "event_date": None}]})
    assert eb.DedupGate(content_index=dict(poisoned), alias_map={}).check(twin, text) == _GAIN_A


def test_the_gather_counts_a_sampled_key_that_resolves_to_an_empty_doc_cache(tmp_path, monkeypatch):
    """The READ half of the same law. An alias that resolves to emptiness must be LOUD: the sampled key's
    own cache is tried as a fallback (a twin later chunked on its own account still routes), and a key that
    still resolves to nothing is a whole DOCUMENT lost from the pass, counted by name instead of vanishing
    into a downstream `SKIPPED (empty)`."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    eb._write_doc_cache({_GAIN_A: [{"id": "x", "date": "2000-06-05", "source": "GAIN", "source_key": _GAIN_A,
                                    "text": "Argentina soybeans crush rose.", "event_date": None}]})
    dead = "text/source=usda_gain_rice/country=VN/publication_date=20110401/document=y/document.json"
    wt = eb.BatchTally(windows_submitted=0)
    out = eb._gather_by_node({"soybeans": [_GAIN_B], "rice": [dead]},
                             {_GAIN_B: _GAIN_A, dead: "text/source=x/publication_date=20110401/never/document.json"},
                             tally=wt)
    assert [p["text"] for p in out["soybeans"]] == ["Argentina soybeans crush rose."]   # the alias still routes
    assert out["soybeans"][0]["contract"] == "soybeans"
    assert out["rice"] == [] and wt.summary()["gather_empty_doc_cache"] == 1
    assert wt.gather_empty == {f"rice {dead}": "text/source=x/publication_date=20110401/never/document.json"}
    # ... and a STALE alias (a canonical that was never chunked) falls back to the sampled key's own cache
    out2 = eb._gather_by_node({"soybean_meal": [_GAIN_A]}, {_GAIN_A: dead}, tally=wt)
    assert [p["text"] for p in out2["soybean_meal"]] == ["Argentina soybeans crush rose."]
    assert wt.summary()["gather_alias_fallbacks"] == 1 and wt.summary()["gather_empty_doc_cache"] == 1


def test_a_deposition_is_withdrawn_when_the_later_twin_never_got_chunked(tmp_path, monkeypatch):
    """The PIT fix's own liveness hole, closed from the other side. `check()` hands the crown to a
    later-dated newcomer BEFORE the build loop discovers the newcomer is off-topic for the node that read
    it and never queues it. Persisting THAT alias would point a document that IS chunked at one that never
    will be -- the silent permanent drop, minted by the fix for the PIT defect. The crown goes back to the
    twin that was actually chunked, and the withdrawn row is counted rather than written."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    text = "Brazil coffee production is forecast higher for 2000/01."
    g = eb.DedupGate(content_index={}, alias_map={}, cached=set())
    g.claim(_COFFEE_EARLY, text)                                   # the only twin this pass ever queues
    assert g.check(_COFFEE_LATE, text) is None                     # deposes the incumbent on date ...
    assert g.aliases == {_COFFEE_EARLY: _COFFEE_LATE} and g.deposed == {_COFFEE_EARLY: _COFFEE_LATE}
    g.flush()                                                      # ... but LATE was never claimed
    assert g.aliases == {} and g.deposed == {}
    assert g.unchunked_canonicals == {_COFFEE_EARLY: _COFFEE_LATE}
    assert ev.load_index(eb._ALIAS_NODE) == []                     # no alias into an unchunked document
    assert eb._load_index_map(eb._CONTENT_NODE, "sha1", "source_key") == {
        eb._content_hash(text): _COFFEE_EARLY}                     # the index keeps the twin that WAS chunked


def test_by_layer_counts_a_duplicate_once_however_many_nodes_sample_it(tmp_path, monkeypatch):
    """COSMETIC, but it broke the one arithmetic a reader checks: `check()` incremented `by_layer` on every
    call, so a duplicate sampled by three nodes counted three times and report()'s per-layer breakdown did
    not sum to its own headline."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    g = eb.DedupGate(content_index={}, alias_map={}, cached=set())
    g.claim(_GAIN_A, "Argentina soybean meal crush rose in 2000.")
    for _ in range(3):                                             # three nodes sample the same co-filing
        assert g.check(_GAIN_B, "Argentina soybean meal crush rose in 2000.") == _GAIN_A
    assert g.by_layer == {"path": 1, "store_path": 0, "content": 0}
    assert sum(g.by_layer.values()) == len(g.aliases) == g.summary()["aliased_docs"] == 1


# ── D10: the 150k cap, and its mirrors ────────────────────────────────────────────────────────────────
def test_fulltext_cap_is_150k_and_every_mirror_moved_with_it():
    """cron_readiness: +$13.45 ONE-TIME, residual truncation 1.3% of chars, 26 of 28 sources stop truncating.
    The two mirrors are not decoration -- pdfpage refuses any offset at or past ITS copy of the cap, so a
    stale mirror would null every legitimate offset an X2 pass mints in the 60k-150k band."""
    from leviathan.graphrag import pdfpage
    assert eb._FULLTEXT_CAP == 150000
    assert nv.FULLTEXT_CAP == eb._FULLTEXT_CAP == pdfpage._FULLTEXT_CAP


def test_doc_blocks_chunks_past_60k_and_still_flags_the_cap_cut(tmp_path, monkeypatch):
    """A 100k document used to be silently halved at 60k; it now chunks whole and is NOT flagged, while a
    200k one is still cut AND still tallied (law #7 -- the raise moves the cut, it does not remove it)."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    key = "text/source=wb_cmo_outlook/release=2026-04/document.json"
    mid = "coffee arabica brazil frost price outlook. " * 2400            # ~100k chars: over 60k, under 150k
    assert 60000 < len(mid) < eb._FULLTEXT_CAP
    t = eb.DarkTally()
    blocks = eb._doc_blocks(None, "_docs", key, doc={"full_text": mid}, tally=t)
    assert t.truncated_docs == set()
    assert sum(len(b) for _blk, _m, b in blocks) > 60000                 # the 60k-100k band is no longer dark
    big = "coffee arabica brazil frost price outlook. " * 5000           # ~210k chars: still over the cap
    eb._doc_blocks(None, "_docs", key, doc={"full_text": big}, tally=t)
    assert t.truncated_docs == {key} and t.manifest()["fulltext_cap"] == 150000


def test_dry_run_estimator_uses_the_measured_output_token_constant():
    """The rider: `:984` assumed 500 output tokens/request against a MEASURED ~1,537 (19.44 props/request x
    79.1 output tokens/prop), a ~3.4x underestimate -- $27 against the corrected $61.71 on the X2 work set,
    and it sat directly beneath the module's own "$70 lesson" comment."""
    src = Path(eb.__file__).read_text(encoding="utf-8")           # the FILE, not inspect.getsource: the latter
    assert "1537 * 2.5 / 1e6" in src                              # slices by line number and misreads a file
    assert "500 * 2.5 / 1e6" not in src                           # being edited in another process
    per_request = 1500 * 0.5 / 1e6 + 1537 * 2.5 / 1e6
    assert round(per_request, 5) == 0.00459                              # x2_cost_check's corrected $/request
