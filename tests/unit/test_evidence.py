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
# The guard inverts driver_alias() into the set of slice names >=1 DAG id reaches; a sink slice outside that
# set is WARNED (ASCII line + optional collector) but STILL written (soft, never refuses -- the E1b flow).
# Hermetic: a synthetic _driver_raw so backed_slice_names() is fully determined by the fixture, every driver
# cache reset in try/finally (a leaked _DRIVER_ALIAS would poison unrelated tests).
_ORPHAN_DRIVERS = {
    "drivers": {"freight": {"category": "logistics", "terms": ["freight"]}},
    "dag_alias": {"freight": ["ocean_freight"]},              # freight backed by identity + an aliased dag id
}


def test_write_driver_slices_warns_on_orphan_but_still_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    monkeypatch.setattr(ev, "_driver_raw", lambda: _ORPHAN_DRIVERS)
    ev._reset()
    try:
        assert ev.backed_slice_names() == {"freight"}         # inversion of driver_alias(): only the backed slice
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


def test_write_driver_slices_no_warn_collector_still_writes(tmp_path, monkeypatch):
    # warnings=None (the default, unchanged call sites) must not raise and must still write the orphan.
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    monkeypatch.setattr(ev, "_driver_raw", lambda: _ORPHAN_DRIVERS)
    ev._reset()
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
    """`release=` must NOT fire on `release_date=` (char after `release` there is `_`), nor on undated keys."""
    assert ev._pub_date("text/source=usda_wasde/release_date=1973-09-17/d.json") is None
    assert ev._pub_date("x/no_date/d.json") is None
    # the two pre-existing branches still win their own formats
    assert ev._pub_date("x/publication_date=20200515/d.json") == date(2020, 5, 15)
    assert ev._pub_date("x/report_05-15-2021/d.json") == date(2021, 5, 15)
