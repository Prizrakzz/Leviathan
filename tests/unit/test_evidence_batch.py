"""Batch-API evidence chunking — mocked (no S3 / Anthropic Batch / spend)."""
from __future__ import annotations

import hashlib
import json
import types

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import evidence_batch as eb
from leviathan.graphrag import extract as ex
from leviathan.graphrag import novelty as nv


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
    assert m["n_docs_truncated_60k"] == 1 and m["truncated_source_keys"] == ["k_big"]


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
    assert payload["neither_source_keys"] == ["D3"] and payload["n_docs_truncated_60k"] == 0
    # routing still happened (aaa reached both commodity slices)
    assert (tmp_path / "corn.jsonl").exists() and (tmp_path / "soybeans.jsonl").exists()


def test_doc_blocks_records_60k_truncation(tmp_path, monkeypatch):
    """law #7: _doc_blocks flags a doc whose full_text exceeded _FULLTEXT_CAP into the tally (still chunked,
    just capped) — the head-cut is never silent."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    big = "coffee arabica brazil frost " * 6000                     # ~168k chars, > 60000
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
    monkeypatch.setattr(eb, "_read_doc", lambda s3, key: bodies[key])
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
