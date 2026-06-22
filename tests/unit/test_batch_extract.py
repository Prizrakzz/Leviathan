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


def test_model_pricing():
    from leviathan.graphrag import extract as ex
    assert ex.price("claude-sonnet-4-6")[0] < ex.price("claude-opus-4-8")[0]   # Sonnet cheaper input


def test_commodity_and_era():
    assert bx._commodity_of("usda_gain_soybean_meal") == "soybean_meal"   # ordered before soybeans
    assert bx._commodity_of("usda_gain_soybeans") == "soybeans"
    assert bx._commodity_of("usda_gain_cocoa") == "cocoa"
    assert bx._commodity_of("conab") == "coffee"
    assert bx._era_of("text/source=usda_wasde/year=1988/document.json") == "ocr_pre95"
    assert bx._era_of("text/source=x/year=2020/document.json") == "recent_10plus"


def test_sample_decider_covers_commodities_and_old_era():
    class FakeS3D:
        def get_paginator(self, _):
            return self

        def paginate(self, **_):
            keys = [f"text/source={s}/year=2018/document.json" for s in bx._DECIDER_TARGETS]
            keys += ["text/source=usda_wasde/year=1988/document.json",
                     "text/source=usda_wap/year=1996/document.json"]
            yield {"Contents": [{"Key": k} for k in keys]}

    picked = bx.sample_decider(FakeS3D(), seed=1)
    coms = {bx._commodity_of(bx._source_of(k)) for k in picked}
    assert {"coffee", "cocoa", "sugar", "palm_oil", "cotton", "rice", "wheat"} <= coms
    assert any(bx._era_of(k) == "ocr_pre95" for k in picked)


def test_relevance_gate():
    from datetime import date
    from leviathan.graphrag.contracts import Chunk

    def mk(text):
        return Chunk(chunk_id="c", proposition=text, verbatim_span=text, source_key="k", page=0,
                     char_start=0, char_end=len(text), document_date=date(2020, 1, 1), source="s",
                     lang="en", translated=False, extraction_method="pdfplumber", ocr=False, text_quality=0.9)
    assert bx._relevant(mk("Brazil arabica production fell sharply due to frost in Minas Gerais this year."))
    assert not bx._relevant(mk("SILVIO PORTO AIRTON SILVA CARLOS BESTATTI ELEDON OLIVEIRA NEGREIROS"))
    assert not bx._relevant(mk("12 34 56 78 90 1.2 3.4 5.6 7.8 9.0 11 22 33 44 55 66 77 88 99 00"))
    assert not bx._relevant(mk("short"))


def test_block_chars_changes_chunk_count():
    from datetime import date
    from leviathan.graphrag.chunking import chunk_document
    text = "\n\n".join(f"Paragraph {i} on commodity markets, weather, and trade flows in some detail here."
                       for i in range(40))
    kw = dict(full_text=text, source_key="k", source="s", document_date=date(2020, 1, 1), lang="en",
              extraction_method="pdfplumber", doc_id="d")
    assert len(chunk_document(**kw, target_chars=200)) > len(chunk_document(**kw, target_chars=5000))


def test_two_hop_chains_over_propagating_edges():
    from leviathan.graphrag import extract as ex
    edges = {("frost", "affects_yield_of", "coffee", "yield"),
             ("coffee", "substitutes_for", "tea", "price"),
             ("Brazil", "produces", "coffee", None)}            # reference edge
    cascade = {e for e in edges if ex._edge_class(e[1]) == "propagating"}
    chains = bx._two_hop_chains(cascade)                        # no prov → no time filter
    assert chains == {("frost", "affects_yield_of", "coffee", "substitutes_for", "tea")}


def test_two_hop_chains_drops_backward_in_time():
    cascade = {("drought", "affects_yield_of", "soybeans", "yield"),
               ("soybeans", "redirects_to", "Philippines", "export")}
    chain = ("drought", "affects_yield_of", "soybeans", "redirects_to", "Philippines")
    fwd = {("drought", "affects_yield_of", "soybeans"): {("conab", "2013-01-01")},   # cause earlier
           ("soybeans", "redirects_to", "Philippines"): {("usda", "2024-01-01")}}    # effect later → keep
    bwd = {("drought", "affects_yield_of", "soybeans"): {("conab", "2024-01-01")},   # cause later
           ("soybeans", "redirects_to", "Philippines"): {("usda", "2013-01-01")}}    # effect earlier → drop
    assert bx._two_hop_chains(cascade, fwd) == {chain}
    assert bx._two_hop_chains(cascade, bwd) == set()           # 2024→2013 cascade rejected
    assert bx._time_coherent({("a", "2013")}, {("b", "2024")}) and not bx._time_coherent({("a", "2024")}, {("b", "2013")})


def _mb_chunk(cid, source="x", year="2020"):
    from datetime import date
    from leviathan.graphrag.contracts import Chunk
    return Chunk(chunk_id=cid, proposition="p", verbatim_span="p",
                 source_key=f"text/source={source}/year={year}/document.json", page=0, char_start=0,
                 char_end=1, document_date=date(int(year), 1, 1), source=source, lang="en",
                 translated=False, extraction_method="pdfplumber", ocr=False, text_quality=0.9)


def test_crosses_detects_cross_document():
    assert bx._crosses({("conab", "2019")}, {("usda", "2021")})        # different docs
    assert not bx._crosses({("conab", "2019")}, {("conab", "2019")})   # both pinned to one doc
    assert bx._crosses({("conab", "2019")}, {("conab", "2019"), ("usda", "2021")})
    assert not bx._crosses(set(), {("usda", "2021")})


def test_classify_chains_splits_cross_source_and_temporal():
    chain = ("frost", "affects_yield_of", "soybeans", "crushed_into", "soybean_meal")
    prov = {("frost", "affects_yield_of", "soybeans"): {("conab", "2019-05-01")},
            ("soybeans", "crushed_into", "soybean_meal"): {("usda_gain_soybean_meal", "2021-03-01")}}
    out = bx._classify_chains({chain}, prov)
    assert chain in out["xdoc"] and chain in out["xsrc"] and chain in out["xtime"]
    s = bx._chain_prov_str(chain, prov)
    assert "conab@2019-05-01" in s and "usda_gain_soybean_meal@2021-03-01" in s


def test_collect_minibatch_builds_cross_source_temporal_chain(monkeypatch):
    # frost→soybeans from CONAB (2019) joins soybeans→soybean_meal from a USDA doc (2021) at the
    # shared canonical `soybeans` node — a cross-document, cross-source, cross-year cascade.
    monkeypatch.setattr(bx.ex, "vocab_sets", lambda: (
        {"commodity", "hazard"}, {"frost", "soybeans", "soybean_meal"},
        {"affects_yield_of", "crushed_into"}))
    empty = {"entities": [], "events": [], "quantitative_claims": [],
             "unmapped_relations": [], "unmapped_entities": []}
    rel = lambda s, d, rt, m: {"src": s, "dst": d, "relation_type": rt, "metric": m, "sign": "-",
                               "mapped": True, "verbatim": "v"}                            # noqa: E731
    manifest = {"k1-d1": {"chunks": [_mb_chunk("d1#c0", "conab", "2019").model_dump(mode="json")]},
                "k1-d2": {"chunks": [_mb_chunk("d2#c0", "usda_gain_soybean_meal", "2021").model_dump(mode="json")]}}
    rr = [("k1-d1", dict(empty, relationships=[rel("frost", "soybeans", "affects_yield_of", "yield")])),
          ("k1-d2", dict(empty, relationships=[rel("soybeans", "soybean_meal", "crushed_into", "crush")]))]
    out = bx._collect_minibatch(_MBClient(rr), "bid", manifest, bx.ex.SONNET, k=1)
    chain = ("frost", "affects_yield_of", "soybeans", "crushed_into", "soybean_meal")
    assert chain in out["chains"] and chain in out["xsrc"] and chain in out["xtime"]


class _MBClient:
    """Minimal fake exposing only client.messages.batches.results(bid) for _collect_minibatch."""
    def __init__(self, rr):
        batches = type("B", (), {"results": lambda self, bid: (_result(c, t) for c, t in rr)})()
        self.messages = type("M", (), {"batches": batches})()


def test_collect_minibatch_maps_indices_collapses_and_chains(monkeypatch):
    # closed vocab via monkeypatch so this runs in CI without the private IP configs
    monkeypatch.setattr(bx.ex, "vocab_sets", lambda: (
        {"commodity", "hazard"}, {"frost", "coffee", "tea", "Brazil"},
        {"affects_yield_of", "substitutes_for", "produces"}))
    manifest = {"k5-d-c0-g2": {"chunks": [_mb_chunk("d#c0").model_dump(mode="json"),
                                          _mb_chunk("d#c1").model_dump(mode="json")]}}
    rel = lambda s, d, rt, m: {"src": s, "dst": d, "relation_type": rt, "metric": m, "sign": "+",
                               "mapped": True, "verbatim": "v"}                            # noqa: E731
    ti = {"results": [
        {"prop_index": 1, "relationships": [rel("frost", "coffee", "affects_yield_of", "yield"),
                                            rel("Brazil", "coffee", "produces", "production"),
                                            rel("Brazil", "coffee", "produces", "area")]},   # produces flood
        {"prop_index": 2, "relationships": [rel("coffee", "tea", "substitutes_for", "price")]}]}
    out = bx._collect_minibatch(_MBClient([("k5-d-c0-g2", ti)]), "bid", manifest, bx.ex.SONNET, k=5)
    assert out["n_props"] == 2                                                   # both indices mapped
    assert ("frost", "affects_yield_of", "coffee", "yield") in out["cascade"]
    assert ("Brazil", "produces", "coffee", None) in out["edges"]               # produces collapsed: metric=None
    assert sum(e[1] == "produces" for e in out["edges"]) == 1                    # flood collapsed to one
    assert out["chains"] == {("frost", "affects_yield_of", "coffee", "substitutes_for", "tea")}


def test_collect_minibatch_counts_missing_index_as_friction(monkeypatch):
    monkeypatch.setattr(bx.ex, "vocab_sets", lambda: ({"commodity"}, {"coffee"}, {"causes"}))
    manifest = {"k5-d-c0-g2": {"chunks": [_mb_chunk("d#c0").model_dump(mode="json"),
                                          _mb_chunk("d#c1").model_dump(mode="json")]}}
    ti = {"results": [{"prop_index": 1, "relationships": []}]}                   # only 1 of 2 props returned
    out = bx._collect_minibatch(_MBClient([("k5-d-c0-g2", ti)]), "bid", manifest, bx.ex.SONNET, k=5)
    assert out["n_props"] == 1 and out["fails"] == 1                            # the dropped prop is friction


def test_build_minibatch_reqs_groups_props(monkeypatch):
    if not _vocab_present():
        pytest.skip("private vocab not present")
    chunks = {"k": [_mb_chunk(f"d#c{i}") for i in range(7)]}
    r1, m1 = bx._build_minibatch_reqs(chunks, bx.ex.SONNET, "k1", k=1)
    assert len(r1) == 7 and all(r["params"]["tool_choice"]["name"] == "emit_extraction" for r in r1)
    r5, m5 = bx._build_minibatch_reqs(chunks, bx.ex.SONNET, "k5", k=5)
    assert len(r5) == 2                                                          # 7 props → ceil(7/5)=2 requests
    assert all(r["params"]["tool_choice"]["name"] == "emit_minibatch_extraction" for r in r5)
    assert all("[P1]" in r["params"]["messages"][0]["content"] for r in r5)
    assert sum(len(v["chunks"]) for v in m5.values()) == 7                       # every prop accounted for


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
