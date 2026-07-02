"""Retrieval-quality rankers — hybrid / rerank / MMR (pure + mocked; the cross-encoder is monkeypatched)."""
from __future__ import annotations

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import rankers as rk


def _rec(rid, text, vec, date="2020-01-01", source="usda_wasde"):
    return {"id": rid, "text": text, "vector": vec, "date": date, "source": source,
            "source_key": f"k/{rid}", "backend": "bge_local"}


def test_tokenize_keeps_finance_codes():
    toks = rk.tokenize("Indonesia raised the blend to B40; CIF Rotterdam, ZL up.")
    assert "b40" in toks and "cif" in toks and "zl" in toks          # exact codes survive as single tokens


def test_rrf_fuse_rewards_agreement():
    a, b, c = {"x": 1}, {"x": 2}, {"x": 3}
    fused = rk.rrf_fuse([[a, b, c], [b, a, c]])                      # a,b top of both lists; c last in both
    assert fused[-1] is c and set(map(id, fused[:2])) == {id(a), id(b)}


def test_hybrid_surfaces_exact_token_dense_missed():
    rk._BM25_CACHE.clear()
    b40 = _rec("b40", "Indonesia raised the biodiesel blend to B40.", [0.0, 1.0])
    recs = [_rec("a", "palm oil demand rose", [1.0, 0.0]), _rec("b", "palm exports fell", [1.0, 0.0]), b40]
    dense_top = [recs[0], recs[1], b40]                              # dense ranks the B40 prop LAST
    cand = rk.hybrid_candidates("what did the B40 mandate do", "palm_oil", recs, None, dense_top, fetch_k=3)
    assert b40 in cand and cand.index(b40) < 2                       # BM25 leg lifts the exact-token prop


def test_mmr_drops_near_duplicate_for_diversity():
    d1 = _rec("d1", "dup one", [1.0, 0.0]); d2 = _rec("d2", "dup two", [0.99, 0.01]); x = _rec("x", "other", [0.0, 1.0])
    picked = rk.mmr_select([d1, d2, x], relevance=[1.0, 0.98, 0.5], k=2, lam=0.5)
    assert d1 in picked and x in picked and d2 not in picked        # SAME-source near-duplicate is thinned


def test_mmr_keeps_cross_source_corroboration():
    a = _rec("a", "Brazil soy 155 MMT", [1.0, 0.0], source="usda_wasde")
    b = _rec("b", "Brazil soybean output ~155 mln t", [0.99, 0.01], source="conab")   # near-dupe, DIFFERENT source
    x = _rec("x", "unrelated palm note", [0.0, 1.0], source="usda_gain")
    picked = rk.mmr_select([a, b, x], relevance=[1.0, 0.98, 0.9], k=2, lam=0.5)
    assert a in picked and b in picked                             # cross-source corroboration survives (not penalized)


def test_mmr_balances_across_sources():
    a1 = _rec("a1", "facet one", [1.0, 0.0, 0.0], source="usda_wasde")
    a2 = _rec("a2", "facet two", [0.0, 1.0, 0.0], source="usda_wasde")
    a3 = _rec("a3", "facet three", [0.0, 0.0, 1.0], source="usda_wasde")   # 3 DISTINCT facets, one high-volume source
    b1 = _rec("b1", "other source facet", [0.6, 0.6, 0.0], source="conab")
    cands, rel = [a1, a2, a3, b1], [1.0, 0.95, 0.9, 0.7]
    balanced = rk.mmr_select(cands, rel, k=3, lam=0.5, fairness=0.3)
    agnostic = rk.mmr_select(cands, rel, k=3, lam=0.5, fairness=0.0, same_source=False)
    assert b1 in balanced                                          # fairness lifts the under-represented source in
    assert b1 not in agnostic                                      # ...where plain MMR lets the big source crowd it out


def test_rerank_overrides_dense_order(monkeypatch):
    monkeypatch.setattr(rk, "rerank_scores", lambda q, texts: [0.1 if "noise" in t else 0.9 for t in texts])
    monkeypatch.setattr(ev, "load_index", lambda n: [_rec("noise", "noise", [1.0, 0.0]),
                                                     _rec("good", "the answer", [0.0, 1.0])])
    monkeypatch.setattr(ev, "embed", lambda x, **k: [[1.0, 0.0]])   # dense favours 'noise'
    out = ev.retrieve("q", "node", k=1, rerank=True)
    assert out[0]["text"] == "the answer"                           # cross-encoder overrode the dense order


def test_default_unchanged_and_every_arm_is_leakage_safe(monkeypatch):
    recs = [_rec("old", "old evidence", [1.0, 0.0], date="2018-01-01"),
            _rec("fut", "FUTURE evidence", [1.0, 0.0], date="2025-01-01")]
    monkeypatch.setattr(ev, "load_index", lambda n: recs)
    monkeypatch.setattr(ev, "embed", lambda x, **k: [[1.0, 0.0]])
    monkeypatch.setattr(rk, "rerank_scores", lambda q, texts: [1.0 for _ in texts])
    for arm in ({}, {"mode": "hybrid"}, {"mmr": 0.5}, {"rerank": True}, {"mode": "hybrid", "rerank": True, "mmr": 0.5}):
        rk._BM25_CACHE.clear()
        out = ev.retrieve("q", "node", k=5, asof="2020-01-01", **arm)
        assert "FUTURE evidence" not in [r["text"] for r in out]    # asof excludes the future prop in EVERY arm
        assert all(r["date"] <= "2020-01-01" for r in out)


def test_dense_fast_path_matches_records_arg(monkeypatch):
    # default retrieve == plain cosine top-k (regression lock on the untouched behaviour)
    monkeypatch.setattr(ev, "embed", lambda x, **k: [[1.0, 0.0]])
    recs = [_rec("hit", "on target", [1.0, 0.0]), _rec("miss", "off", [0.0, 1.0])]
    out = ev.retrieve("q", "node", k=1, records=recs)
    assert out == [{"date": "2020-01-01", "source": "usda_wasde", "source_key": "k/hit", "text": "on target"}]
