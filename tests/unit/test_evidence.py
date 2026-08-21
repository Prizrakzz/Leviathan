"""graphdev evidence slice — mocked (no S3/Bedrock/spend)."""
from __future__ import annotations

import json
import types
from datetime import date

from leviathan.graphrag import evidence as ev


class _Prop:                                                    # minimal stand-in for contracts.Chunk
    def __init__(self, cid, prop, d, source="GAIN"):
        self.chunk_id, self.proposition, self.document_date, self.source = cid, prop, d, source


def _fake_chunker(**kw):
    return [_Prop("c1", "Brazil frost devastated arabica coffee in 2021.", date(2021, 7, 20)),
            _Prop("c2", "Unrelated macro note about bonds.", date(2021, 7, 20))]


def _bow_embed(texts, **kw):                                    # deterministic bag-of-words vectors
    vocab = ["frost", "drought", "coffee", "bonds", "rain"]
    return [[1.0 if w in t.lower() else 0.0 for w in vocab] for t in texts]


def test_embed_backend_dispatch(monkeypatch):
    import pytest
    monkeypatch.setattr(ev, "_bge_local", lambda texts: [[0.1, 0.2] for _ in texts])
    assert ev.embed(["a", "b"], backend="bge_local") == [[0.1, 0.2], [0.1, 0.2]]
    body = types.SimpleNamespace(read=lambda: json.dumps({"embedding": [1.0, 2.0]}).encode())
    fake_bedrock = types.SimpleNamespace(invoke_model=lambda **kw: {"body": body})
    assert ev.embed(["x"], backend="titan", bedrock=fake_bedrock) == [[1.0, 2.0]]
    assert ev.embed([], backend="titan") == []                       # empty short-circuits before any call
    with pytest.raises(ValueError):
        ev.embed(["x"], backend="nope")


def test_cosine_and_doc_date():
    assert round(ev._cosine([1, 0], [1, 0]), 3) == 1.0 and ev._cosine([1, 0], [0, 1]) == 0.0
    assert ev._doc_date({"document_date": "2021-07-20"}, "k") == date(2021, 7, 20)
    assert ev._doc_date({}, "text/x/2014/y/document.json").year == 2014   # year-from-key fallback


def test_pub_date_parses_exact_dates():
    assert ev._pub_date("text/source=usda_gain_coffee/publication_date=20210519/document=x/document.json") == date(2021, 5, 19)
    assert ev._pub_date("text/.../coffee_annual_mexico_05-15-2021/document.json") == date(2021, 5, 15)
    assert ev._pub_date("text/coffee/2021/x/document.json") is None        # year-only key -> no exact date


def test_near_proximity_breaks_cosine_tie(monkeypatch):
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[1.0, 0.0] for _ in texts])   # identical vectors -> cosine ties
    recs = [{"id": "old", "date": "2012-06-01", "source": "S", "source_key": "k1", "text": "t", "vector": [1.0, 0.0]},
            {"id": "new", "date": "2018-06-01", "source": "S", "source_key": "k2", "text": "t", "vector": [1.0, 0.0]}]
    assert ev.retrieve("q", "node", k=1, near="2018", records=recs)[0]["date"] == "2018-06-01"
    assert ev.retrieve("q", "node", k=1, near="2012", records=recs)[0]["date"] == "2012-06-01"


def test_restamp_updates_dates_from_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    rec = {"id": "a", "date": "2021-01-01", "source": "S", "text": "t", "vector": [0.1], "backend": "x",
           "source_key": "text/source=usda_gain_coffee/publication_date=20210519/document=x/document.json"}
    (tmp_path / "arabica_coffee.jsonl").write_text(json.dumps(rec), encoding="utf-8")
    assert ev.restamp("arabica_coffee") == 1
    assert ev.load_index("arabica_coffee")[0]["date"] == "2021-05-19"


def test_retrieve_cosine_ranking_and_pit(monkeypatch):
    monkeypatch.setattr(ev, "embed", _bow_embed)
    recs = [{"id": i, "date": d, "source": "GAIN", "source_key": f"k{i}", "text": t,
             "vector": _bow_embed([t])[0]}
            for i, (t, d) in enumerate([("frost hit coffee", "2021-07-20"),
                                        ("drought struck later", "2024-01-01"),
                                        ("bonds macro note", "2021-07-20")])]
    hits = ev.retrieve("frost coffee damage", "arabica_coffee", k=2, records=recs)
    assert hits[0]["text"] == "frost hit coffee" and all("bonds" not in h["text"] for h in hits)
    pit = ev.retrieve("drought", "arabica_coffee", k=5, asof="2022-01-01", records=recs)
    assert pit and all(h["date"] <= "2022-01-01" for h in pit)             # the 2024 prop excluded
    # D-DV-2: the DENSE fast path carries the score it ranked on, monotone with the returned order.
    assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)
    assert hits[0]["score"] > 0


def test_build_index_keeps_on_topic_props_and_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    monkeypatch.setattr(ev, "sample_keys", lambda *a, **k: ["text/coffee/2021/x/document.json"])
    body = types.SimpleNamespace(read=lambda: json.dumps(
        {"full_text": "Brazil frost hit arabica coffee hard in 2021."}).encode())
    fake_s3 = types.SimpleNamespace(get_object=lambda **kw: {"Body": body})

    n = ev.build_index(fake_s3, node="arabica_coffee", aliases=["arabica"], year_windows=[(2021, 2021)],
                       n_docs=1, bedrock=object(), chunker=_fake_chunker)
    assert n == 1                                                          # bonds prop dropped (off-topic)
    recs = ev.load_index("arabica_coffee")
    assert len(recs) == 1 and "frost" in recs[0]["text"] and len(recs[0]["vector"]) == 5


def test_parse_event_date_handles_partials_and_garbage():
    from leviathan.graphrag import chunking as ch
    assert ch._parse_event_date("2023-02-01", "day") == (date(2023, 2, 1), "day")
    assert ch._parse_event_date("2023-02", "month") == (date(2023, 2, 1), "month")
    assert ch._parse_event_date("2023", None) == (date(2023, 1, 1), "year")     # precision inferred
    assert ch._parse_event_date("2023-Q2", None) == (date(2023, 4, 1), "quarter")
    assert ch._parse_event_date("", None) == (None, None) and ch._parse_event_date("soon", None) == (None, None)
    assert ch._parse_event_date("2023-13-40", None)[0] == date(2023, 1, 1)       # clamps, never raises


def test_driver_slices_for_routes_cross_cutting_props():
    # membership (not ==) so this survives driver_slices.yaml growing (it's gitignored + curated over time)
    assert "biodiesel_mandate" in ev.driver_slices_for("Indonesia raised the blend to B40")
    assert "freight" in ev.driver_slices_for("Pacific freight rates doubled")
    assert ev.driver_slices_for("the document was published on schedule") == []    # no driver term -> not routed


class _PD:                                                      # prop carrying an event_date (WS-MS6)
    def __init__(self, cid, prop, ev_dt, source="GAIN"):
        self.chunk_id, self.proposition, self.document_date, self.source = cid, prop, date(2023, 8, 11), source
        self.event_date, self.event_date_precision = ev_dt, "month"


def test_build_index_routes_driver_props_and_carries_event_date(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    monkeypatch.setattr(ev, "sample_keys", lambda *a, **k: ["text/palm/2023/x/document.json"])
    body = types.SimpleNamespace(read=lambda: json.dumps(
        {"full_text": "Indonesia raised the biodiesel blend to B40, lifting palm oil demand."}).encode())
    fake_s3 = types.SimpleNamespace(get_object=lambda **kw: {"Body": body})

    def _chunker(**kw):
        return [_PD("c1", "Palm oil demand rose in Indonesia.", date(2023, 2, 1)),
                _PD("c2", "Indonesia raised the biodiesel blend to B40.", date(2023, 2, 1))]

    sink: dict = {}
    n = ev.build_index(fake_s3, node="palm_oil", aliases=["palm"], year_windows=[(2023, 2023)], n_docs=1,
                       bedrock=object(), chunker=_chunker, max_props=None, driver_sink=sink)
    crecs = ev.load_index("palm_oil")
    assert n == 1 and crecs[0]["event_date"] == "2023-02-01"                  # commodity prop carries the event date
    assert "biodiesel_mandate" in sink                                       # B40 prop (names no commodity) -> driver
    assert sink["biodiesel_mandate"][0]["text"].startswith("Indonesia") and sink["biodiesel_mandate"][0]["event_date"] == "2023-02-01"


def test_write_driver_slices_dedups_exact_repeats_keeps_cross_source(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    rec = lambda src, key: {"id": "x", "driver": "freight", "date": "2023-01-01", "source": src,
                            "source_key": key, "text": "freight rates doubled", "event_date": None,
                            "event_date_precision": None}
    sink = {"freight": [rec("WB", "k1"), rec("WB", "k1"), rec("CONAB", "k2")]}   # 1st two identical, 3rd cross-source
    n = ev.write_driver_slices(sink)
    recs = ev.load_index("drivers/freight")
    assert n == 2 and len(recs) == 2 and {r["source"] for r in recs} == {"WB", "CONAB"}
    assert all("vector" in r for r in recs)


def test_build_index_concurrent_workers_aggregate_all_docs(tmp_path, monkeypatch):
    """workers>1 (cloud Fargate path): per-doc Haiku chunking fans out over thread-local S3 clients and the
    props from EVERY sampled doc are aggregated; off-topic props still dropped; max_props=None lifts the cap."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    monkeypatch.setattr(ev, "sample_keys", lambda *a, **k: ["text/coffee/2021/a/document.json",
                                                            "text/coffee/2022/b/document.json"])
    body = types.SimpleNamespace(read=lambda: json.dumps(
        {"full_text": "Brazil frost hit arabica coffee."}).encode())
    fake_s3 = types.SimpleNamespace(get_object=lambda **kw: {"Body": body})
    import leviathan.storage.s3 as s3mod
    monkeypatch.setattr(s3mod, "get_thread_local_s3_client", lambda region: fake_s3, raising=False)

    def _chunker(**kw):                                            # one on-topic + one off-topic per doc, ids by doc
        did = kw["doc_id"].split("/")[-2]
        return [_Prop(f"{did}-on", "Frost devastated arabica coffee.", date(2021, 7, 20)),
                _Prop(f"{did}-off", "Unrelated bonds macro note.", date(2021, 7, 20))]

    n = ev.build_index(fake_s3, node="arabica_coffee", aliases=["arabica"], year_windows=[(2021, 2021)],
                       n_docs=2, bedrock=object(), chunker=_chunker, max_props=None, workers=2,
                       aws_region="us-east-1")
    assert n == 2                                                          # both docs' on-topic props kept
    recs = ev.load_index("arabica_coffee")
    assert {r["id"] for r in recs} == {"a-on", "b-on"} and all("frost" in r["text"].lower() for r in recs)


def test_node_resolution_dedups_variants(monkeypatch):
    monkeypatch.setattr(ev, "_hier", lambda: {"contracts": {
        "soybean_meal_cbot": {"node": "soybean_meal"}, "soybean_meal_dce": {"node": "soybean_meal"},
        "cocoa": {"node": "cocoa"}}})
    assert ev.node_for("soybean_meal_cbot") == ev.node_for("soybean_meal_dce") == "soybean_meal"  # variants share
    assert ev.node_for("cocoa") == "cocoa"
    assert ev.node_for("not_a_contract") == "not_a_contract"        # unknown id -> unchanged
    assert ev.all_nodes() == ["cocoa", "soybean_meal"]              # distinct + deduped


def test_windows_for_config_then_default_then_broad(monkeypatch):
    monkeypatch.setattr(ev, "_windows", lambda: {"cocoa": [(2024, 2024)]})
    assert ev.windows_for("cocoa") == [(2024, 2024)]               # from the config
    assert ev.windows_for("arabica_coffee") == ev._WINDOWS["arabica_coffee"]   # baked-in pilot default
    assert ev.windows_for("nonesuch") == ev._BROAD                 # broad fallback


def test_sample_keys_uses_commodity_tokens_not_exchange(monkeypatch):
    import leviathan.graphrag.corpus_recon as cr
    monkeypatch.setattr(cr, "_source_of", lambda k: "usda_gain_oilseeds_meal", raising=False)
    # node 'soybean_meal' -> tokens {soybean, meal}; an exchange-suffixed id would have matched nothing useful
    keys = ["text/x/2022/oilseeds/document.json", "text/x/2022/wheat/document.json"]

    class _S3:
        def get_paginator(self, _):
            return types.SimpleNamespace(paginate=lambda **kw: [{"Contents": [{"Key": k} for k in keys]}])
    got = ev.sample_keys(_S3(), node="soybean_meal", year_windows=[(2022, 2022)], n=2)
    assert all(g in keys for g in got) and got                     # samples within window, biased by commodity token


def test_match_forms_and_n_docs_override(tmp_path, monkeypatch):
    cfg = tmp_path / "evidence_windows.yaml"
    cfg.write_text("extra_terms:\n  white_maize: [maize, corn]\nn_docs:\n  cocoa: 150\n", encoding="utf-8")
    monkeypatch.setattr(ev, "_WINDOWS_PATH", cfg)
    forms = ev.match_forms("white_maize")
    assert "maize" in forms and "corn" in forms and "white_maize" in forms     # parent-commodity broadening
    assert ev.n_docs_for("cocoa", 40) == 150 and ev.n_docs_for("rice", 40) == 40   # override vs default


def test_sample_keys_keeps_all_relevant_when_fewer_than_n(monkeypatch):
    import leviathan.graphrag.corpus_recon as cr
    # 3 cocoa-source docs + 20 other in-window docs; ask for n=10 -> all 3 cocoa MUST be kept, then fill to 10
    cocoa = [f"text/x/2025/cocoa{i}/document.json" for i in range(3)]
    other = [f"text/x/2025/grain{i}/document.json" for i in range(20)]
    monkeypatch.setattr(cr, "_source_of",
                        lambda k: "usda_gain_cocoa" if "cocoa" in k else "usda_gain_grain", raising=False)

    class _S3:
        def get_paginator(self, _):
            return types.SimpleNamespace(paginate=lambda **kw: [{"Contents": [{"Key": k} for k in cocoa + other]}])
    got = ev.sample_keys(_S3(), node="cocoa", year_windows=[(2025, 2025)], n=10, seed=0)
    assert len(got) == 10 and set(cocoa) <= set(got)               # all 3 relevant retained (old code would dilute)


def test_sample_keys_relevance_includes_extra_terms(monkeypatch):
    import leviathan.graphrag.corpus_recon as cr
    monkeypatch.setattr(ev, "_extra_terms", lambda node: ["rapeseed"])   # canola broadens to its rapeseed source
    monkeypatch.setattr(cr, "_source_of",
                        lambda k: "usda_gain_rapeseed" if "rape" in k else "usda_gain_grain", raising=False)
    rape = [f"text/x/2021/rape{i}/document.json" for i in range(5)]
    other = [f"text/x/2021/grain{i}/document.json" for i in range(20)]

    class _S3:
        def get_paginator(self, _):
            return types.SimpleNamespace(paginate=lambda **kw: [{"Contents": [{"Key": k} for k in rape + other]}])
    got = ev.sample_keys(_S3(), node="canola", year_windows=[(2021, 2021)], n=8, seed=0)
    assert set(rape) <= set(got)        # canola's rapeseed-source docs prioritized via extra_terms (was random before)


def test_covering_sources_includes_allcommodity_and_specialized():
    all_src = {"usda_gain_coffee", "wb_cmo_outlook", "usda_wasde", "fnc", "usda_fas_coffee_wmt", "usda_gain_sugar"}
    cov = ev.covering_sources("arabica_coffee", all_src)
    assert "usda_gain_coffee" in cov                       # dedicated (name-match)
    assert "wb_cmo_outlook" in cov and "usda_wasde" in cov  # all-commodity sources
    assert "fnc" in cov and "usda_fas_coffee_wmt" in cov    # specialized coffee sources
    assert "usda_gain_sugar" not in cov                     # an unrelated commodity's source stays out


def test_sample_keys_is_source_agnostic(monkeypatch):
    import collections

    import leviathan.graphrag.corpus_recon as cr
    # raw_sugar: a FAT dedicated source (usda_gain_sugar) + all-commodity wb_cmo + wasde that discuss sugar.
    # The result must NOT be 100% gain_sugar — the other sources have to get in (the whole point).
    sugar = [f"text/x/2020/gain_sugar_{i}/document.json" for i in range(50)]
    wb = [f"text/x/2020/wbcmo_{i}/document.json" for i in range(15)]
    wasde = [f"text/x/2020/wasde_{i}/document.json" for i in range(15)]
    def src(k):
        return ("usda_gain_sugar" if "gain_sugar" in k else "wb_cmo_outlook" if "wbcmo" in k
                else "usda_wasde" if "wasde" in k else "other")
    monkeypatch.setattr(cr, "_source_of", src, raising=False)
    monkeypatch.setattr(ev, "_extra_terms", lambda node: [])

    class _S3:
        def get_paginator(self, _):
            return types.SimpleNamespace(paginate=lambda **kw: [{"Contents": [{"Key": k} for k in sugar + wb + wasde]}])
    got = ev.sample_keys(_S3(), node="raw_sugar", year_windows=[(2020, 2020)], n=20, seed=0)
    cnt = collections.Counter(src(k) for k in got)
    assert cnt["usda_gain_sugar"] >= 1                                    # dedicated source still contributes (depth)
    assert cnt["wb_cmo_outlook"] >= 1 and cnt["usda_wasde"] >= 1          # but NOT single-source — others get IN
    assert cnt["usda_gain_sugar"] <= round(20 * ev._DEDICATED_FRAC) + 1   # dedicated capped ~60%, not 100%


def test_evidence_store_s3_mode(monkeypatch):
    # EVIDENCE_S3 set -> _evid_write/_evid_read hit S3 (mocked boto3), not local disk (WS-MS2.1 cloud store).
    monkeypatch.setattr(ev, "_evid_s3", lambda: "s3://mybucket/graphrag/evidence/")
    store = {}

    class _S3:
        def put_object(self, *, Bucket, Key, Body):
            store[(Bucket, Key)] = Body.decode()

        def get_object(self, *, Bucket, Key):
            return {"Body": types.SimpleNamespace(read=lambda: store[(Bucket, Key)].encode())}
    monkeypatch.setattr("boto3.client", lambda svc, *a, **k: _S3(), raising=False)
    ev._evid_write("cocoa", '{"x": 1}\n{"x": 2}')
    assert ("mybucket", "graphrag/evidence/cocoa.jsonl") in store          # wrote to S3, not local
    assert ev.load_index("cocoa") == [{"x": 1}, {"x": 2}]                   # reads back from S3


def test_evid_write_accepts_str_or_bytes_and_writes_identical_content(tmp_path, monkeypatch):
    """The local (F6) branch. write_guard.commit_write encodes each slice body exactly once and hands the
    resulting BYTES here; a str stays accepted for the direct callers (restamp, the doc-cache writer). Both
    forms must land the SAME bytes on disk -- and both must go through write_BYTES, never write_text, or the
    Windows "\\n" -> "\\r\\n" translation puts the on-disk size above the manifest's after_bytes again."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    body = (json.dumps({"x": "café"}, ensure_ascii=False) + "\n"
            + json.dumps({"y": "El Niño"}, ensure_ascii=False))
    assert len(body) != len(body.encode("utf-8"))              # genuinely multi-byte

    ev._evid_write("drivers/multibyte", body)                              # str in
    from_str = (tmp_path / "drivers" / "multibyte.jsonl").read_bytes()
    ev._evid_write("drivers/multibyte", body.encode("utf-8"))              # bytes in
    from_bytes = (tmp_path / "drivers" / "multibyte.jsonl").read_bytes()

    assert from_str == from_bytes == body.encode("utf-8")      # byte-identical, and to today's bytes
    assert b"\r\n" not in from_bytes                           # F6: one bytes sink, no newline translation
    assert ev.load_index("drivers/multibyte") == [{"x": "café"}, {"y": "El Niño"}]


def test_evid_write_s3_branch_puts_identical_bytes_for_str_and_bytes(monkeypatch):
    """The cloud branch -- the one the 1.03 GB soybeans PUT runs on. A bytes body is PUT as-is (that
    re-encode is the copy that OOM-killed the 2026-08-02 pass); a str body is encoded once, here."""
    monkeypatch.setattr(ev, "_evid_s3", lambda: "s3://mybucket/graphrag/evidence/")
    puts: list = []

    class _S3:
        def put_object(self, *, Bucket, Key, Body):
            puts.append((Bucket, Key, bytes(Body)))
    monkeypatch.setattr("boto3.client", lambda svc, *a, **k: _S3(), raising=False)
    body = json.dumps({"x": "café"}, ensure_ascii=False)
    ev._evid_write("cocoa", body)
    ev._evid_write("cocoa", body.encode("utf-8"))
    assert puts[0] == puts[1] == ("mybucket", "graphrag/evidence/cocoa.jsonl", body.encode("utf-8"))


def test_evid_write_is_marked_as_a_bytes_writer():
    """The zero-copy hand-off is opt-in PER write_fn, so this pins that the four shipped plan_write call
    sites -- all of which pass _evid_write -- actually take it. An unmarked callable keeps the str path."""
    from leviathan.graphrag import write_guard as wg
    assert getattr(ev._evid_write, wg.BYTES_WRITER_ATTR, False) is True
    assert wg._accepts_bytes(ev._evid_write) and not wg._accepts_bytes(lambda node, body: None)


def test_embed_memoizes_single_text_calls(monkeypatch):
    # WS-0 profiling: the L2 walk re-embedded the SAME query for every node it grounded (26% of wall time).
    # Single-text calls memoize; bulk (build-time) calls never do.
    from leviathan.graphrag import evidence as ev
    calls = {"n": 0}

    def fake_raw(texts, **kw):
        calls["n"] += 1
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(ev, "_embed_raw", fake_raw)
    ev._Q_CACHE.clear()
    try:
        ev.embed(["same query"]); ev.embed(["same query"]); ev.embed(["same query"])
        assert calls["n"] == 1                                   # one raw call for three identical queries
        ev.embed(["a", "b"]); ev.embed(["a", "b"])
        assert calls["n"] == 3                                   # bulk path untouched (no memo)
    finally:
        ev._Q_CACHE.clear()


def test_slice_for_driver_annotation_resolves():
    # P7-P0.4: evidence.py used Optional in an annotation without importing it -- latent NameError under
    # typing.get_type_hints (masked by `from __future__ import annotations`). Pin that hints now resolve.
    import typing

    from leviathan.graphrag import evidence as ev
    hints = typing.get_type_hints(ev.slice_for_driver)
    assert hints["return"] == typing.Optional[str]


# ── accent-fold registration (Phase 7 P2 W1) ─────────────────────────────────────────────────────────
# driver_alias() folds accented DAG ids (El_Nino/La_Nina) onto their ASCII slice names so slice_for_driver
# resolves them without a per-id YAML entry. These are hermetic: a synthetic causal dir (so
# display.all_driver_ids() sees the accented id) + a synthetic driver_slices.yaml, with EVERY cache reset in
# try/finally (mirrors test_e1_census._wire — a leaked fixture cache would poison other tests).
_FOLD_CAUSAL = (
    "contract: test_contract\n"
    "drivers:\n"
    "- id: exact_slice\n"
    "- id: "
    "El_Niño\n"                                            # accented id, byte-disjoint from the ASCII slice
)
_FOLD_DRIVERS = (
    "drivers:\n"
    "  exact_slice: {category: hazard, terms: [frost]}\n"
    "  el_nino: {category: teleconnection, terms: [enso]}\n"   # ASCII slice the accented id folds onto
    "dag_alias:\n"
    "  el_nino: [El_Nino]\n"                                   # the ASCII case-variant that El_Nino folds onto
)


def _wire_fold(monkeypatch, tmp_path, *, causal_yaml=_FOLD_CAUSAL, driver_yaml=_FOLD_DRIVERS):
    """Point display at a synthetic causal dir and evidence at a synthetic driver_slices.yaml, caches cleared.
    Returns the evidence dir. Caller MUST reset in a finally (see the try/finally in each test)."""
    from leviathan.graphrag import display as dp
    from leviathan.graphrag import evidence as ev
    causal = tmp_path / "causal"
    causal.mkdir()
    (causal / "fixture.yaml").write_text(causal_yaml, encoding="utf-8")
    monkeypatch.setattr(dp, "_CFG", tmp_path)                 # display globs _CFG/causal/*.yaml
    drv = tmp_path / "driver_slices.yaml"
    drv.write_text(driver_yaml, encoding="utf-8")
    monkeypatch.setattr(ev, "_DRIVER_PATH", drv)
    ev._reset()
    dp.all_driver_ids.cache_clear()
    return ev


def test_driver_alias_accent_folds_accented_ids(tmp_path, monkeypatch):
    from leviathan.graphrag import display as dp
    from leviathan.graphrag import evidence as ev
    _wire_fold(monkeypatch, tmp_path)
    try:
        # the accented id resolves onto the ASCII 'el_nino' slice via the fold pass (was None pre-W1)
        assert ev.slice_for_driver("El_Niño") == "el_nino"
        assert "El_Niño" in ev.backed_dag_ids()          # now counted backed by the census
        # an exact-name slice still resolves by identity; a non-existent id is still None
        assert ev.slice_for_driver("exact_slice") == "exact_slice"
        assert ev.slice_for_driver("nonesuch_driver") is None
    finally:
        ev._reset()
        dp.all_driver_ids.cache_clear()


def test_reset_nulls_the_three_driver_globals(tmp_path, monkeypatch):
    from leviathan.graphrag import evidence as ev
    _wire_fold(monkeypatch, tmp_path)
    try:
        ev.driver_specs(); ev.driver_alias(); ev.driver_matchers()   # populate all three caches
        assert ev._DRIVER_CACHE is not None and ev._DRIVER_ALIAS is not None
        assert ev._DRIVER_MATCHERS is not None
        ev._reset()
        assert ev._DRIVER_CACHE is None and ev._DRIVER_ALIAS is None and ev._DRIVER_MATCHERS is None
    finally:
        ev._reset()
        from leviathan.graphrag import display as dp
        dp.all_driver_ids.cache_clear()


def test_fold_importable_from_both_modules():
    # import hygiene: fold() lives in evidence and is re-exported from e1_census (the reverse import cycles).
    from leviathan.graphrag import e1_census as ec
    from leviathan.graphrag import evidence as ev
    assert ev.fold is ec.fold                                 # ONE implementation, not two copies
    assert ev.fold("El_Niño") == "El_Nino" and ev.fold("frost") == "frost"


# ── W1.1 write-time orphan guard + W2.2 chunk_version plumbing (Phase 7 P3) ───────────────────────────
# G7.1 REPAIRED THE PREDICATE. The guard used to test backed_slice_names(), which is driver_alias() inverted
# -- and driver_alias() seeds `{name: name for name in specs}`, so EVERY configured slice is in it by
# construction (measured at HEAD: 109 specs, 109 "backed", empty difference). The guard could therefore never
# fire for anything and read as coverage in every review. It now tests dag_backed_slice_names(), which
# INTERSECTS that inversion with the real causal driver ids -- so the fixture must supply a causal registry
# too, or the test is measuring the repo's live DAG instead of itself. It still WARNS and never refuses.
_ORPHAN_DRIVERS = {
    "drivers": {"freight": {"category": "logistics", "terms": ["freight"]}},
    "dag_alias": {"freight": ["ocean_freight"]},              # freight backed by identity + an aliased dag id
}


def _wire_orphan_fixture(monkeypatch, *, real_ids=("ocean_freight",)):
    """Synthetic driver config + synthetic causal driver-id registry, both fully determining the guard."""
    from leviathan.graphrag import display as dp
    monkeypatch.setattr(ev, "_driver_raw", lambda: _ORPHAN_DRIVERS)
    monkeypatch.setattr(dp, "all_driver_ids", lambda: frozenset(real_ids))
    ev._reset()


def test_write_driver_slices_warns_on_orphan_but_still_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    _wire_orphan_fixture(monkeypatch)
    try:
        assert ev.backed_slice_names() == {"freight"}         # identity-seeded inversion: every spec name
        assert ev.dag_backed_slice_names() == {"freight"}     # ... intersected with the ONE real dag id
        rec = lambda drv: {"id": "x", "driver": drv, "date": "2023-01-01", "source": "WB", "source_key": "k1",
                           "text": "freight rates doubled", "event_date": None, "event_date_precision": None}
        sink = {"freight": [rec("freight")], "ghost_slice": [rec("ghost_slice")]}
        warns: list = []
        n = ev.write_driver_slices(sink, warnings=warns)
        assert n == 2                                         # BOTH slices written -- the guard never refuses
        assert len(ev.load_index("drivers/ghost_slice")) == 1 and len(ev.load_index("drivers/freight")) == 1
        assert len(warns) == 1 and "ghost_slice" in warns[0]  # only the orphan warned; the backed slice silent
        assert "freight" not in warns[0] and warns[0].startswith("WARN")
        assert warns[0].encode("ascii")                       # WARN line is ASCII-safe (cp1252 stdout rule)
    finally:
        ev._reset()


def test_orphan_guard_fires_when_no_real_dag_id_reaches_the_slice(tmp_path, monkeypatch):
    """G7.1 -- the regression the old predicate could not express: a slice that IS in the alias map (by
    identity) but that no REAL causal driver id reaches. Under backed_slice_names() 'freight' was 'backed'
    and silent; under dag_backed_slice_names() it is correctly named as unreachable."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    _wire_orphan_fixture(monkeypatch, real_ids=("some_other_driver",))
    try:
        assert "freight" in ev.backed_slice_names()           # the old predicate: silent, by construction
        assert ev.dag_backed_slice_names() == set()           # the repaired one: nothing is reachable
        assert ev.read_dark_slices() == {"freight"}
        rec = {"id": "x", "driver": "freight", "date": "2023-01-01", "source": "WB", "source_key": "k1",
               "text": "freight rates doubled", "event_date": None, "event_date_precision": None}
        warns: list = []
        assert ev.write_driver_slices({"freight": [rec]}, warnings=warns) == 1     # still written
        assert len(warns) == 1 and "freight" in warns[0] and "no backing DAG id" in warns[0]
    finally:
        ev._reset()


def test_dag_backed_slice_names_is_vacuous_without_a_causal_dir(monkeypatch):
    """A clean checkout with no private causal configs has an empty all_driver_ids(); declaring all 109
    slices dark there would be 109 spurious warnings per pass, so it falls back to the identity inversion."""
    _wire_orphan_fixture(monkeypatch, real_ids=())
    try:
        assert ev.dag_backed_slice_names() == {"freight"} == ev.backed_slice_names()
        assert ev.read_dark_slices() == set()
    finally:
        ev._reset()


def test_write_driver_slices_no_warn_collector_still_writes(tmp_path, monkeypatch):
    # warnings=None (the default, unchanged call sites) must not raise and must still write the orphan.
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    _wire_orphan_fixture(monkeypatch)
    try:
        rec = {"id": "x", "driver": "ghost_slice", "date": "2023-01-01", "source": "WB", "source_key": "k1",
               "text": "freight rates doubled", "event_date": None, "event_date_precision": None}
        n = ev.write_driver_slices({"ghost_slice": [rec]})     # no collector passed -> None branch
        assert n == 1 and len(ev.load_index("drivers/ghost_slice")) == 1
    finally:
        ev._reset()


def test_prop_record_chunk_version_optional():
    # W2.2: _prop_record stamps chunk_version ONLY when provided; default omits the field (byte-identical).
    p = _PD("c1", "Palm oil demand rose.", date(2023, 2, 1))
    base = ev._prop_record(p, key="k1")
    assert "chunk_version" not in base                        # default -> field absent (not written as null)
    stamped = ev._prop_record(p, key="k1", chunk_version="cafebabe1234-20260707")
    assert stamped["chunk_version"] == "cafebabe1234-20260707"
    assert {k: v for k, v in stamped.items() if k != "chunk_version"} == base   # ONLY the new field added


def test_current_chunk_version_str_or_none(monkeypatch):
    # W2.2: current_chunk_version() = corpus_fingerprint + UTC date, or None when the fingerprint is unavailable.
    import re

    from leviathan.graphrag import eval as gev
    monkeypatch.setattr(gev, "corpus_fingerprint", lambda: "abcdef012345")
    v = ev.current_chunk_version()
    assert isinstance(v, str) and re.match(r"^abcdef012345-\d{8}$", v)   # <fp>-YYYYMMDD, deterministic shape
    assert v.encode("ascii") and v == ev.current_chunk_version()        # ASCII-safe + stable within a UTC day
    monkeypatch.setattr(gev, "corpus_fingerprint", lambda: "unknown")
    assert ev.current_chunk_version() is None                          # LIST/import-failure sentinel -> None
    monkeypatch.setattr(gev, "corpus_fingerprint", lambda: "")
    assert ev.current_chunk_version() is None                          # empty fingerprint -> None (omit stamp)


# ══ S6 dating fix (cycle-2 W0a): _pub_date gains the wb_cmo `release=YYYY-MM` branch ═══════════════════════
def test_pub_date_release_branch():
    """wb_cmo props now date to the release month (day 1), not the year->Jan-1 fallback."""
    assert ev._pub_date("text/source=wb_cmo_outlook/release=2020-05/document.json") == date(2020, 5, 1)


def test_pub_date_release_branch_no_false_match():
    """`release=` must not CLAIM a `release_date=` key: the wasde key below is now parsed, but by the
    release_date rule at DAY precision, never by the month-precision release= rule. (Before DEC-P0c S1 this
    key returned None outright and every one of the 616 wasde documents took a Jan-1 floor.)"""
    assert ev.pub_date_layout("text/source=usda_wasde/release_date=1973-09-17/d.json") == \
        (date(1973, 9, 17), "release_date")
    assert ev._pub_date("x/no_date/d.json") is None
    # the two pre-existing branches still win their own formats
    assert ev._pub_date("x/publication_date=20200515/d.json") == date(2020, 5, 15)
    assert ev._pub_date("x/report_05-15-2021/d.json") == date(2021, 5, 15)


# ══ DEC-P0c S1: one rule per key layout doc_census names ═════════════════════════════════════════════════
# Every key below is a REAL key from `data/dec_p0/doc_census.json` sample_keys (or the pilot's own T5b
# table). Before this fix `_pub_date` matched only three shapes and 2,036 of 7,056 corpus documents (28.9%)
# fell through to year -> Jan-1 -- an error that is ALWAYS backwards in time, i.e. leakage-permissive
# against the very `asof` filter this field feeds. Measured after the fix over a fresh LIST of all 7,056
# `document.json` keys: 6,994 parse, 62 refuse (55 conab + 7 mpob), 0 unknown.
_REAL_KEYS = [
    # (key, expected date, expected layout)
    ("text/source=usda_wasde/release_date=2026-05-12/document.json", date(2026, 5, 12), "release_date"),
    ("text/source=usda_wasde/release_date=1973-09-17/document.json", date(1973, 9, 17), "release_date"),
    ("text/source=usda_wap/release_month=2026-07/document.json", date(2026, 7, 1), "release_month"),
    ("text/source=usda_wap/release_month=1988-01/document.json", date(1988, 1, 1), "release_month"),
    ("text/source=wb_cmo_outlook/release=1994-11/document.json", date(1994, 11, 1), "release_ym"),
    ("text/source=icco_qbcs_summary/release_date=2008-02-28/doc=c6a2f397/document.json",
     date(2008, 2, 28), "release_date"),
    ("text/source=icco_ewg_stocks/release_date=2022-01-27/doc=9178daf1/document.json",
     date(2022, 1, 27), "release_date"),
    ("text/source=sagis_cec/release_date=1999-10-20/doc=c6cd1554/document.json",
     date(1999, 10, 20), "release_date"),
    ("text/source=mpoc/release_type=market_highlights/date=20200313/"
     "slug=crash-of-crude-oil-market-and-its-impact-on-oils-fats/document.json", date(2020, 3, 13), "article_date"),
    ("text/source=fnc/monthly_reports/report_type=cifras/publisher=fnc_informe_mensual/"
     "publication_date=2025-03-01/document.json", date(2025, 3, 1), "publication_date_iso"),
    ("text/source=usda_fas_coffee_wmt/publication_date=20040612/document.json", date(2004, 6, 12), "publication_date"),
    ("text/source=usda_gain_cocoa/country=GH/publication_date=19980924/"
     "document=ghana_annual_cocoa_report_accra_ghana_09-17-1998/document.json", date(1998, 9, 24), "publication_date"),
    ("text/source=usda_gain_sugar/country=MX/publication_date=20141103/"
     "document=mexico_announces_sugar_cane_reference_price_mexico_mexico_10-31-2014/document.json",
     date(2014, 11, 3), "publication_date"),
]
_REFUSING_KEYS = [
    ("text/source=conab/crop_year=2025_26/survey=01/document.json", "conab_survey_is_not_a_month"),
    ("text/source=conab/crop_year=2009_10/survey=12/document.json", "conab_survey_is_not_a_month"),
    ("text/source=mpob/release_type=overview_pdf/year=2010/document.json", "year_only"),
]


def test_pub_date_parses_every_layout_doc_census_names():
    """13 layouts, real keys, one assertion each. The GAIN pair also pins precedence: those keys carry BOTH
    an inner `publication_date=YYYYMMDD` and an MM-DD-YYYY fragment in the document leaf, and the compact
    stamp must win (they disagree -- 1998-09-24 vs 1998-09-17, 2014-11-03 vs 2014-10-31)."""
    for key, want, layout in _REAL_KEYS:
        assert ev.pub_date_layout(key) == (want, layout), key
        assert ev._pub_date(key) == want, key


def test_pub_date_refuses_rather_than_guesses_where_the_key_carries_no_date():
    """CONAB's `survey=NN` is a survey ordinal in the modern bulletins and a publication MONTH in the
    pre-2013 era (paths.raw_conab_bulletin_key says so, and the live keys carry both shapes), and mpob's
    overview PDFs are keyed by `year=` alone. Both refuse to a NAMED layout instead of guessing a month --
    and the refusal is what makes the surviving Jan-1 attributable."""
    for key, layout in _REFUSING_KEYS:
        assert ev.pub_date_layout(key) == (None, layout), key
    assert ev.pub_date_layout("text/source=brand_new_source/whatever/document.json") == (None, "unknown")


def test_pub_date_lookbehinds_keep_the_four_date_families_apart():
    """The whole guard between `date=`, `publication_date=`, `release=`, `release_date=` and
    `release_month=` is a lookbehind on the preceding `_`. A leak in either direction re-dates a whole
    source, so it is asserted directly rather than inferred from the layout table above."""
    assert ev.pub_date_layout("x/release_date=2020-05-15/d.json")[1] == "release_date"     # not release_ym
    assert ev.pub_date_layout("x/release_month=2020-05/d.json")[1] == "release_month"      # not release_ym
    assert ev.pub_date_layout("x/publication_date=20200515/d.json")[1] == "publication_date"  # not article_date
    assert ev.pub_date_layout("x/download_date=20200515/d.json")[0] is None                # not a publication date
    assert ev.pub_date_layout("x/release_type=t/date=20200515/d.json")[1] == "article_date"


def test_pub_date_ignores_a_malformed_stamp_instead_of_raising():
    """A stamp that is well-shaped but not a date (month 13) falls THROUGH to the next layout and finally to
    the documented refusal — never a ValueError out of a chunking pass, and never a coerced date."""
    assert ev.pub_date_layout("x/release_date=2021-13-40/d.json") == (None, "unknown")


def test_doc_date_detail_names_how_the_date_was_obtained():
    """The flag half of the fix: `kind` separates a parsed publication date from a FLOOR, so a Jan-1 in the
    store is never again indistinguishable from a real January 1st publication."""
    assert ev.doc_date_detail({}, "text/source=usda_wasde/release_date=2026-05-12/document.json") == \
        (date(2026, 5, 12), "key", "release_date")
    assert ev.doc_date_detail({}, "text/source=usda_wap/release_month=2026-07/document.json") == \
        (date(2026, 7, 1), "key_month", "release_month")            # day 1 of a REAL month, flagged as such
    d, kind, layout = ev.doc_date_detail({}, "text/source=mpob/release_type=overview_pdf/year=2016/document.json")
    assert (d, kind, layout) == (date(2016, 1, 1), "year_floor", "year_only")
    assert ev.doc_date_detail({"document_date": "2019-04-02"}, "text/source=x/nothing/document.json") == \
        (date(2019, 4, 2), "doc_field", "unknown")
    assert ev.doc_date_detail({}, "text/source=x/nothing/document.json") == \
        (date(1970, 1, 1), "epoch_floor", "unknown")
    assert ev._doc_date({}, "text/source=usda_wasde/release_date=2026-05-12/document.json") == date(2026, 5, 12)


def test_restamp_picks_up_every_new_layout(tmp_path, monkeypatch):
    """`restamp` re-derives a slice's dates from the stored source_key and was the one existing consumer of
    _pub_date: a wasde slice stamped 2026-01-01 restamps to the real release with no re-chunk and no embed."""
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    recs = [{"id": "a", "date": "2026-01-01", "source": "usda_wasde", "text": "t",
             "source_key": "text/source=usda_wasde/release_date=2026-05-12/document.json"},
            {"id": "b", "date": "2025-01-01", "source": "conab", "text": "u",
             "source_key": "text/source=conab/crop_year=2025_26/survey=01/document.json"}]
    (tmp_path / "corn.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    assert ev.restamp("corn") == 2
    out = [json.loads(x) for x in (tmp_path / "corn.jsonl").read_text(encoding="utf-8").splitlines()]
    assert out[0]["date"] == "2026-05-12"                           # the wasde Jan-1 floor is gone
    assert out[1]["date"] == "2025-01-01"                           # conab REFUSED -> its floor is untouched


def test_out_projection_carries_event_date():
    """P9-A W0: the retrieval projection surfaces event_date (the answer layer's lag narration and the
    Phase-B window derivation read it); a prop lacking the field stays None, never KeyError."""
    from leviathan.graphrag import evidence as ev
    recs = [{"date": "2010-09-01", "source": "usda_gain", "source_key": "k1", "text": "t",
             "event_date": "2010-08-05", "event_date_precision": "day"},
            {"date": "2011-01-01", "source": "usda_wasde", "source_key": "k2", "text": "u"}]
    out = ev._out(recs)
    assert out[0]["event_date"] == "2010-08-05" and out[0]["event_date_precision"] == "day"
    assert out[1]["event_date"] is None and out[1]["event_date_precision"] is None
    # Phase F widened the projection with the three span keys (char_start/char_end/offset_kind) --
    # additive, None on pre-offset vintages, same discipline as `score`.
    assert set(out[0]) == {"date", "source", "source_key", "text", "event_date", "event_date_precision",
                           "char_start", "char_end", "offset_kind", "score"}


def test_out_projection_carries_span_offsets():
    """Phase F: flat JSONL records hold char offsets inline; _out must pass them through (they were
    dropped here since 6.5, which kept the citation locator's offsets permanently null)."""
    from leviathan.graphrag import evidence as ev
    recs = [{"date": "2010-09-01", "source": "usda_gain", "source_key": "k1", "text": "t",
             "char_start": 1200, "char_end": 1240, "offset_kind": "exact_ws"},
            {"date": "2011-01-01", "source": "usda_wasde", "source_key": "k2", "text": "u"}]
    out = ev._out(recs)
    assert out[0]["char_start"] == 1200 and out[0]["char_end"] == 1240
    assert out[0]["offset_kind"] == "exact_ws"
    assert out[1]["char_start"] is None and out[1]["offset_kind"] is None


def test_out_projection_carries_the_retrieval_score():
    """D-DV-2: `score` crosses the retrieve boundary so the planner's score-aware cap can triage. Keyed
    by id() of the SAME record objects, so a reordered/subset selection still pairs row to value; a row
    the caller supplied no score for is None (present-and-null, never a missing key)."""
    from leviathan.graphrag import evidence as ev
    a = {"date": "2010-09-01", "source": "s", "source_key": "k1", "text": "t"}
    b = {"date": "2011-01-01", "source": "s", "source_key": "k2", "text": "u"}
    out = ev._out([b, a], {id(a): 0.9, id(b): 0.2})
    assert [o["score"] for o in out] == [0.2, 0.9]
    assert ev._out([a])[0]["score"] is None


# ── G5 (max_per honest fix) + G1b (the C2 wholesale-write guard) ───────────────────────────────────────
# The value 4000 existed at exactly ONE place in the repo (the default arg) and was applied as a bare
# `uniq = uniq[:max_per]` -- no print, no warning, no count. rebuild_slices iterates `for h in
# _cached_hashes()` over a SET of md5 hex strings with PYTHONHASHSEED unset anywhere, so the surviving 4,000
# differed on every run: MEASURED at the 2026-07-20 promote, 5,809 of the 16,000 rows in the four capped
# slices were swapped for a different 5,809 with all four counts frozen at exactly 4000. No counts-based or
# bytes-based guard can see that; determinism is the only thing that closes it.
_G5_DRIVERS = {
    "drivers": {"freight": {"category": "logistics", "terms": ["freight"], "max_props": 3},
                "tariff": {"category": "policy", "terms": ["tariff"]}},
    "dag_alias": {"freight": ["ocean_freight"], "tariff": ["import_tariff"]},
}


def _g5_wire(monkeypatch, tmp_path):
    from leviathan.graphrag import display as dp
    from leviathan.graphrag import extract as ex
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    monkeypatch.setattr(ev, "embed", _bow_embed)
    monkeypatch.setattr(ev, "_driver_raw", lambda: _G5_DRIVERS)
    monkeypatch.setattr(dp, "all_driver_ids", lambda: frozenset({"ocean_freight", "import_tariff"}))
    ev._reset()


def _g5_rec(day, key, rid):
    return {"id": rid, "date": f"2024-01-{day:02d}", "source": "WB", "source_key": key,
            "text": f"freight {rid}", "event_date": None, "event_date_precision": None}


def test_truncation_order_is_deterministic_and_keeps_the_most_recent(tmp_path, monkeypatch):
    _g5_wire(monkeypatch, tmp_path)
    try:
        recs = [_g5_rec(5, "kb", "b"), _g5_rec(9, "ka", "a"), _g5_rec(1, "kc", "c"), _g5_rec(9, "ka", "z")]
        ordered = [r["id"] for r in ev._truncation_order(recs)]
        assert ordered == ["a", "z", "b", "c"]                # date DESC, then source_key/id ASC
        # the SAME records in any input order produce the SAME survivors -- this is the whole fix
        assert ev._truncation_order(list(reversed(recs))) == ev._truncation_order(recs)
    finally:
        ev._reset()


def test_per_slice_max_props_truncates_deterministically_and_records_it(tmp_path, monkeypatch):
    _g5_wire(monkeypatch, tmp_path)
    try:
        from leviathan.graphrag import write_guard as wg
        sink = {"freight": [_g5_rec(d, f"k{d}", f"i{d}") for d in (2, 8, 4, 6, 9)]}   # 5 props, cap 3
        warns, mf = [], wg.RunManifest("unit")
        n = ev.write_driver_slices(sink, warnings=warns, manifest=mf)
        kept = [r["id"] for r in ev.load_index("drivers/freight")]
        assert n == 3 and kept == ["i9", "i8", "i6"]          # the three most recent, in order
        assert any("TRUNCATED 2 props at max_props=3" in w for w in warns)
        assert mf.slices["drivers"]["freight"]["truncated_n"] == 2
        # G5c: the declared cap wins over the pass default, and an undeclared slice inherits it
        assert ev.slice_cap("freight", 4000) == 3 and ev.slice_cap("tariff", 4000) == 4000
        assert ev.slice_cap("unknown_slice", 4000) == 4000
    finally:
        ev._reset()


def test_declared_null_max_props_means_uncapped(tmp_path, monkeypatch):
    _g5_wire(monkeypatch, tmp_path)
    try:
        _G5_DRIVERS["drivers"]["freight"]["max_props"] = None
        assert ev.slice_cap("freight", 4000) is None
    finally:
        _G5_DRIVERS["drivers"]["freight"]["max_props"] = 3
        ev._reset()


def test_write_driver_slices_refuses_a_ten_percent_drop_and_writes_nothing(tmp_path, monkeypatch):
    """G1b/C2 end to end: the seam that overwrote each slice wholesale with no read, no merge, no delta and
    no empty guard now refuses a population drop past the trip line -- BEFORE any byte is written."""
    import pytest
    _g5_wire(monkeypatch, tmp_path)
    try:
        from leviathan.graphrag import write_guard as wg
        seed = {"tariff": [_g5_rec(1, f"k{i}", f"i{i}") for i in range(40)]}
        assert ev.write_driver_slices(seed) == 40
        before = (tmp_path / "drivers" / "tariff.jsonl").read_bytes()
        shrunk = {"tariff": [_g5_rec(1, f"k{i}", f"i{i}") for i in range(20)]}      # -50%
        with pytest.raises(wg.WriteRefused) as exc:
            ev.write_driver_slices(shrunk)
        assert (tmp_path / "drivers" / "tariff.jsonl").read_bytes() == before       # untouched
        assert any("50.0% drop" in line for line in exc.value.lines)
        # ... and the declared-magnitude escape hatch lets it through, still recorded
        warns: list = []
        assert ev.write_driver_slices(shrunk, warnings=warns, allow_churn=0.60) == 20
        assert any("50.0% drop" in w for w in warns)
        assert len(ev.load_index("drivers/tariff")) == 20
    finally:
        ev._reset()


# ── F3: build_index is the LIVE cloud commodity write, and it was unguarded ────────────────────────────
def _bi_props(n, day=lambda i: 1):
    return [_Prop(f"c{i}", f"Arabica coffee note {i}", date(2021, 7, day(i))) for i in range(n)]


def _wire_build_index(tmp_path, monkeypatch, props):
    from leviathan.graphrag import extract as ex
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    monkeypatch.setattr(ev, "sample_keys", lambda *a, **k: ["text/coffee/2021/x/document.json"])
    body = types.SimpleNamespace(read=lambda: json.dumps(
        {"full_text": "Brazil frost hit arabica coffee hard in 2021."}).encode())
    return types.SimpleNamespace(get_object=lambda **kw: {"Body": body}), (lambda **kw: props)


def test_build_index_write_is_guarded_and_a_collapse_is_refused(tmp_path, monkeypatch):
    """F3 -- the FIFTH seam. `evidence.build_index`'s final `_evid_write(node, ...)` is the PRODUCTION cloud
    commodity write (jobs/batch/build_evidence_task.py -> jobdef leviathan-dev-evidence-build), writing the
    same 24 top-level slices `_commodity_guarded_write` protects, and it had no churn ratio, no span tuple,
    no empty guard and no manifest line. The wave shipped a store where one path refused a collapse and
    another rewrote the same object silently."""
    import pytest
    from leviathan.graphrag import write_guard as wg
    s3, chunker = _wire_build_index(tmp_path, monkeypatch, _bi_props(40))
    assert ev.build_index(s3, node="arabica_coffee", aliases=["arabica"], year_windows=[(2021, 2021)],
                          n_docs=1, bedrock=object(), chunker=chunker, max_props=None) == 40
    before = (tmp_path / "arabica_coffee.jsonl").read_bytes()

    s3, chunker = _wire_build_index(tmp_path, monkeypatch, _bi_props(10))          # -75%
    with pytest.raises(wg.WriteRefused) as exc:
        ev.build_index(s3, node="arabica_coffee", aliases=["arabica"], year_windows=[(2021, 2021)],
                       n_docs=1, bedrock=object(), chunker=chunker, max_props=None)
    assert (tmp_path / "arabica_coffee.jsonl").read_bytes() == before              # atomic
    assert any("commodity/arabica_coffee" in line and "drop" in line for line in exc.value.lines)
    assert ev.build_index(s3, node="arabica_coffee", aliases=["arabica"], year_windows=[(2021, 2021)],
                          n_docs=1, bedrock=object(), chunker=chunker, max_props=None,
                          allow_churn=0.80) == 10                                  # declared magnitude


def test_build_index_truncation_is_deterministic_and_recorded(tmp_path, monkeypatch):
    """F3's second half. `records[:max_props]` was applied to a list assembled by ThreadPoolExecutor.map --
    an unrecorded, ORDER-NONDETERMINISTIC cut on the commodity side, the exact defect G5a closed for the
    driver side and nothing more."""
    from leviathan.graphrag import write_guard as wg
    props = [_Prop(f"c{i}", f"Arabica coffee note {i}", date(2021, 7, (i % 20) + 1)) for i in range(20)]
    s3, chunker = _wire_build_index(tmp_path, monkeypatch, props)
    mf = wg.RunManifest("unit")
    n = ev.build_index(s3, node="arabica_coffee", aliases=["arabica"], year_windows=[(2021, 2021)],
                       n_docs=1, bedrock=object(), chunker=chunker, max_props=5, manifest=mf)
    kept = [r["date"] for r in ev.load_index("arabica_coffee")]
    assert n == 5 and kept == ["2021-07-20", "2021-07-19", "2021-07-18", "2021-07-17", "2021-07-16"]
    assert mf.slices["commodity"]["arabica_coffee"]["truncated_n"] == 15
    assert any("TRUNCATED 15 props at max_props=5" in w for w in mf.warnings)


def test_a_multi_node_build_accumulates_one_manifest_and_never_calls_a_written_slice_unwritten(
        tmp_path, monkeypatch):
    """build_index is called ONCE PER NODE against the SHARED commodity layer, so one pass plans that layer
    many times. Two things must not happen: the last node's verdict silently replacing the previous ones
    (the manifest would read as a record of the pass while holding one node), and a slice an EARLIER node in
    this same pass wrote being reported as "present in the store but not written by this pass"."""
    from leviathan.graphrag import write_guard as wg
    mf = wg.RunManifest("cloud_build")
    for node, props in (("arabica_coffee", _bi_props(6)), ("robusta_coffee", _bi_props(4))):
        s3, chunker = _wire_build_index(tmp_path, monkeypatch, props)
        ev.build_index(s3, node=node, aliases=[node.split("_")[0]], year_windows=[(2021, 2021)], n_docs=1,
                       bedrock=object(), chunker=chunker, max_props=None, manifest=mf)
    assert set(mf.slices["commodity"]) == {"arabica_coffee", "robusta_coffee"}   # BOTH nodes recorded
    assert mf.guard["commodity"]["n_plans"] == 2                                 # both verdicts, not the last
    assert mf.unwritten.get("commodity", {}) == {}          # arabica is not "unwritten" when robusta runs


def test_build_index_never_clobbers_a_slice_with_an_empty_write(tmp_path, monkeypatch):
    s3, chunker = _wire_build_index(tmp_path, monkeypatch, _bi_props(4))
    ev.build_index(s3, node="arabica_coffee", aliases=["arabica"], year_windows=[(2021, 2021)],
                   n_docs=1, bedrock=object(), chunker=chunker, max_props=None)
    keep = (tmp_path / "arabica_coffee.jsonl").read_bytes()
    s3, chunker = _wire_build_index(tmp_path, monkeypatch, [])
    assert ev.build_index(s3, node="arabica_coffee", aliases=["arabica"], year_windows=[(2021, 2021)],
                          n_docs=1, bedrock=object(), chunker=chunker, max_props=None) == 0
    assert (tmp_path / "arabica_coffee.jsonl").read_bytes() == keep


# ── F6: a local slice's bytes must EQUAL what the manifest recorded ────────────────────────────────────
def test_local_slice_bytes_equal_the_manifest_after_bytes_no_crlf_drift(tmp_path, monkeypatch):
    """Path.write_text translated "\\n" -> "\\r\\n" on Windows, so a local slice was ALWAYS larger than the
    recorded after_bytes by exactly its newline count (measured: 3201 recorded, 3220 on disk, delta 19 = the
    19 newlines). resolve_prior's stale-mirror fence compares those two for EQUALITY, so on the laptop the
    exact branch never matched: every span went None and the manifest stamped "prior manifest STALE (bytes
    moved since)" -- claiming an unguarded write had invalidated a baseline when nothing had written."""
    from leviathan.graphrag import extract as ex
    from leviathan.graphrag import write_guard as wg
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ex, "_CFG", tmp_path / "cfg")
    monkeypatch.setattr(ev, "_evid_s3", lambda: None)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    monkeypatch.setattr(ev, "_driver_raw", lambda: _G5_DRIVERS)
    ev._reset()
    try:
        mf = wg.RunManifest("unit")
        ev.write_driver_slices({"tariff": [_g5_rec(d, f"k{d}", f"i{d}") for d in range(1, 21)]},
                               manifest=mf)
        on_disk = (tmp_path / "drivers" / "tariff.jsonl").stat().st_size
        assert mf.slices["drivers"]["tariff"]["after_bytes"] == on_disk       # was off by 19 newlines
        # ... so the very next pass takes the EXACT branch instead of the size estimate + STALE stamp
        mf.flush()
        prior = wg.resolve_prior("drivers/", ["tariff"], layer="drivers")["tariff"]
        assert prior["exact"] is True and prior["n"] == 20 and "STALE" not in prior["source"]
    finally:
        ev._reset()


# ── F12: the G7.4 never-written census pin ─────────────────────────────────────────────────────────────
def test_never_written_pin_names_its_members_and_is_advisory_only(tmp_path, monkeypatch):
    """G7.4's "8 never-written slices (census pin)" had no pin: grep over src/ returned nothing. The
    109-specs-vs-101-files gap stayed a hand-derived number in a document, which is the thing a census pin
    exists to stop. It is ADVISORY on purpose -- write-darkness is STORE state, and a config lint that
    cannot see the store must never fail a build on it.

    D-EC POST-X2 GRAPH-COMPLETION WAVE (2026-08-21): 8 -> 7. `barley_yellow_dwarf_virus` left, and the
    REASON is the point of re-cutting this number rather than loosening the assertion: it did not become
    written, it stopped being CONFIGURED (the spec was retired from driver_slices.yaml on zero measured
    props, with no S3 object ever written and no waiver or dag_alias row to unpick). Had the pin entry
    stayed, this module's own staleness branch -- `gone = NEVER_WRITTEN_SLICES_PIN - set(specs)` -- would
    have emitted a "pin STALE" line on every lint run, which is precisely the symptom this pin exists to
    produce and precisely why the config retirement and the pin edit are one edit."""
    assert len(ev.NEVER_WRITTEN_SLICES_PIN) == 7
    assert {"corn_tar_spot", "managed_money_positioning", "india_import_duty"} <= ev.NEVER_WRITTEN_SLICES_PIN
    assert "barley_yellow_dwarf_virus" not in ev.NEVER_WRITTEN_SLICES_PIN   # spec retired, not written
    assert ev.NEVER_WRITTEN_SLICES_PIN != ev.READ_DARK_SLICES_PIN          # a DIFFERENT darkness
    monkeypatch.setattr(ev, "_driver_raw", lambda: {"drivers": {n: {"terms": ["t"]} for n in
                                                                ev.NEVER_WRITTEN_SLICES_PIN}})
    ev._reset()
    try:
        lines = ev.never_written_slice_warnings()
        assert lines and "7 of 7" in lines[0] and "corn_tar_spot" in lines[0]
        assert not any("STALE" in ln for ln in lines)
        monkeypatch.setattr(ev, "_driver_raw", lambda: {"drivers": {"corn_tar_spot": {"terms": ["t"]}}})
        ev._reset()
        stale = ev.never_written_slice_warnings()
        assert any("STALE" in ln and "managed_money_positioning" in ln for ln in stale)
    finally:
        ev._reset()
    assert ev.check_driver_slices.__doc__                                   # the pin is NOT a hard-lint leg
