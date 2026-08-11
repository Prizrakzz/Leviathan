"""Retrieval-quality rankers — hybrid / rerank / MMR (pure + mocked; the cross-encoder is monkeypatched).

D-MW-1/2/3 (2026-08-11) adds the THIRD backend's contract at the bottom: batch-composition invariance
(a doc's score cannot depend on which chunk it landed in), the deliberate short-count ASYMMETRY between
the two managed leaves, the dual-name key read, and the one-warning-then-bge unknown-backend handling.
Every one of those calls through the real dispatch and stubs only the HTTP / boto3 leaf.
"""
from __future__ import annotations

import logging

import pytest
import requests
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
    # P9-A W0: the projection carries event_date. D-DV-2: ...and `score`, the relevance the row was ranked
    # on -- the fast path picks the SAME rows in the SAME order, it just says why.
    assert out == [{"date": "2020-01-01", "source": "usda_wasde", "source_key": "k/hit", "text": "on target",
                    "event_date": None, "event_date_precision": None, "score": 1.0}]


# ── D-MW: the third rerank backend ───────────────────────────────────────────────────────────────────
class _Resp:
    """The response surface `_cohere_post` actually reads (it handles status manually, never
    raise_for_status, so this is a faithful stand-in and not a convenience fiction)."""

    def __init__(self, payload: dict, status: int = 200):
        self.status_code, self._payload, self.text = status, payload, ""

    def json(self) -> dict:
        return self._payload


class _FakeBedrock:
    """The boto3 bedrock-agent-runtime surface: one `rerank` method. `answer` is a callable over the
    request, so a test can respond PARTIALLY -- which is the whole point of the short-count pins."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def rerank(self, **kw):
        self.calls.append(kw)
        return {"results": self.answer(kw)}


def _lane():
    """Install a turn collector on this thread and hand it back (`_lane_teardown` clears it)."""
    c = rk.RerankLaneCollector()
    rk.install_lane(c)
    return c


@pytest.fixture(autouse=True)
def _lane_teardown():
    """No collector may survive a test: the slot is a thread-local and pytest reuses ONE thread, so a
    leak would attribute the next test's reranks to this one (the same hazard the serving pool has)."""
    yield
    rk.clear_lane()


# -- batch-composition invariance: the score is a property of the (query, doc), not of the request ----
def test_a_docs_score_is_identical_whole_or_chunked(monkeypatch):
    """THE UNIT HALF of the D-MW-8 Layer A assertion (the live half scores 200 docs whole vs as 4x50 and
    agrees to 1e-6). Cross-encoder scoring is POINTWISE, which is the entire licence for the coalescer's
    batching -- if a doc's score moved with its batch mates, every coalesced turn would be scoring
    something other than what an uncoalesced turn scores, and the whole seam would be unsound."""
    docs = ["alpha", "bravo", "charlie", "delta", "echo"]
    truth = {d: 0.9 - i / 10.0 for i, d in enumerate(docs)}       # deterministic per-DOC, recorded-style
    monkeypatch.setenv("COHERE_API", "k-test")

    def fake_post(url, headers=None, json=None, timeout=None):
        # answers in REVERSE rank order, as the vendor does -- realignment is part of what's invariant
        got = json["documents"]
        return _Resp({"results": list(reversed([{"index": i, "relevance_score": truth[d]}
                                                for i, d in enumerate(got)]))})

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 100)
    whole = rk._cohere_rerank_call("q", docs)                    # ONE request
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 2)
    chunked = rk._cohere_rerank_call("q", docs)                  # 2 + 2 + 1
    assert whole == chunked == [truth[d] for d in docs]
    # ...and the same doc keeps its score when the SPLIT moves it to a different chunk position
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 3)
    assert dict(zip(docs, rk._cohere_rerank_call("q", docs))) == dict(zip(docs, whole))


# -- the deliberate short-count asymmetry (D-MW-2) ----------------------------------------------------
def test_cohere_raises_on_a_short_count_and_records_no_short(monkeypatch):
    """A truncated native response yields a floored, mostly-TIED score vector -- retrieval that looks
    like it ran and did not. The NEW leaf therefore RAISES (-> one warning -> bge fallback). It records
    no `short_counts`: on this lane a truncation surfaces as a FALLBACK, and the two counters must not
    both fire for one event or the gate double-counts."""
    lane = _lane()
    monkeypatch.setenv("COHERE_API", "k-test")
    monkeypatch.setattr(requests, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        _Resp({"results": [{"index": 0, "relevance_score": 0.5}]}))
    with pytest.raises(RuntimeError, match="returned 1 results for 3 documents"):
        rk._cohere_rerank_call("q", ["a", "b", "c"])
    assert lane.snapshot()["short_counts"] == 0


def test_bedrock_keeps_the_floor_and_counts_it_instead(monkeypatch):
    """The LIVE leaf keeps its 0.0 floor -- arming a raise there rests on an unverified assumption about
    Bedrock's response contract at 200-1000 docs, and if Bedrock caps results the raise converts today's
    silent partial scoring into a bge fallback on EVERY production turn. So the floor is MEASURED: the
    unreturned indices are counted into the turn's lane stamp, which is what makes the honesty gap
    computable from an artifact instead of from a log grep."""
    lane = _lane()
    monkeypatch.setattr(rk, "_bedrock_rerank_client",
                        _FakeBedrock(lambda kw: [{"index": 0, "relevanceScore": 0.8}]))
    assert rk._bedrock_rerank_call("q", ["a", "b", "c"]) == [0.8, 0.0, 0.0]
    snap = lane.snapshot()
    assert snap["short_counts"] == 2 and snap["fallbacks"] == 0     # floored, counted, turn intact
    assert snap["backends"] == ["bedrock"] and snap["requests"] == 1


def test_bedrock_short_counts_accumulate_across_chunks(monkeypatch):
    lane = _lane()
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 2)
    monkeypatch.setattr(rk, "_bedrock_rerank_client",
                        _FakeBedrock(lambda kw: [{"index": 0, "relevanceScore": 0.4}]))
    assert rk._bedrock_rerank_call("q", ["a", "b", "c", "d"]) == [0.4, 0.0, 0.4, 0.0]
    assert lane.snapshot()["short_counts"] == 2 and lane.snapshot()["requests"] == 2


# -- D-MW-3: the dual-name key read, and what a missing key costs --------------------------------------
def test_cohere_key_reads_both_env_names_and_raises_when_neither_is_set(monkeypatch):
    """batch_extract._api_key's exact idiom: the local .env carries COHERE_API while the ECS/Batch
    secret injects COHERE_API_KEY, and ONE code path must satisfy both lanes (a keyless cloud arm would
    otherwise silently measure bge wearing a cohere label)."""
    monkeypatch.delenv("COHERE_API", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="COHERE_API / COHERE_API_KEY is unset"):
        rk._cohere_api_key()
    monkeypatch.setenv("COHERE_API_KEY", "  cloud-secret  ")
    assert rk._cohere_api_key() == "cloud-secret"                   # trimmed
    monkeypatch.setenv("COHERE_API", "local-dotenv")
    assert rk._cohere_api_key() == "local-dotenv"                   # local name wins, as batch_extract does
    # RECORDED EDGE, pinned as-is because it is the SHARED idiom (`A or B` then strip, batch_extract:53-57):
    # a whitespace-only COHERE_API SHADOWS a good COHERE_API_KEY and raises rather than falling through.
    # Safe by construction -- the raise is caught one frame up into one warning + a bge fallback -- and
    # forking the idiom here to "fix" it would put two different key readers in the estate.
    monkeypatch.setenv("COHERE_API", "   ")
    with pytest.raises(RuntimeError, match="is unset"):
        rk._cohere_api_key()


def test_a_missing_key_degrades_the_turn_to_bge_and_never_breaks_it(monkeypatch, caplog):
    """D-MW-3: missing key when backend==cohere -> warning + bge fallback, never a crash. The fallback is
    recorded on the CALLER's collector, naming the lane it MEANT to run (`cohere` joins `backends` even
    though no request was ever issued) -- that is what tells a gate the arm was mis-provisioned rather
    than simply configured for bge."""
    lane = _lane()
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.delenv("COHERE_API", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.setattr(rk, "_COAL", rk._RerankCoalescer())
    monkeypatch.setattr(rk, "_bge_rerank_scores", lambda q, t: [0.25] * len(t))
    with caplog.at_level(logging.WARNING, logger="leviathan.graphrag.rankers"):
        assert rk.rerank_scores("q", ["a", "b"]) == [0.25, 0.25]
    assert any("cohere rerank failed" in r.getMessage() for r in caplog.records)
    snap = lane.snapshot()
    assert snap["fallbacks"] == 1 and snap["backends"] == ["cohere"] and snap["requests"] == 0


# -- D-MW-1: an unknown backend string is loud ONCE, then runs bge -------------------------------------
def test_unknown_backend_warns_once_per_string_then_runs_bge(monkeypatch, caplog):
    """Before D-MW-1 a typo in GRAPHRAG_RERANK_BACKEND was a SILENT ~100 s/walk latency regression with
    zero signal -- the fallback it degrades into is the same code path a healthy bge deployment runs.
    Deduped PER STRING (not once per process): a second, different typo must still be named."""
    monkeypatch.setattr(rk, "_UNKNOWN_BACKENDS_WARNED", set())
    hits: list[list[str]] = []
    monkeypatch.setattr(rk, "_bge_rerank_scores", lambda q, t: (hits.append(list(t)), [1.0] * len(t))[1])

    def _warnings(sub):
        return [r for r in caplog.records if sub in r.getMessage()]

    with caplog.at_level(logging.WARNING, logger="leviathan.graphrag.rankers"):
        monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohre")      # the typo
        assert rk.rerank_scores("q", ["a"]) == [1.0]
        assert rk.rerank_scores("q", ["b"]) == [1.0]
        assert len(_warnings("'cohre'")) == 1                       # loud once...
        monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrok")     # ...per distinct string
        assert rk.rerank_scores("q", ["c"]) == [1.0]
        assert len(_warnings("'bedrok'")) == 1
    assert hits == [["a"], ["b"], ["c"]]                            # every one of them still ran bge
    assert "bge|bedrock|cohere" in caplog.text                      # the message names the legal set


def test_the_three_known_backends_never_warn(monkeypatch, caplog):
    monkeypatch.setattr(rk, "_UNKNOWN_BACKENDS_WARNED", set())
    monkeypatch.setattr(rk, "_bge_rerank_scores", lambda q, t: [1.0] * len(t))
    monkeypatch.setattr(rk, "_bedrock_rerank_scores", lambda q, t: [0.5] * len(t))
    monkeypatch.setattr(rk, "_cohere_rerank_scores", lambda q, t: [0.6] * len(t))
    with caplog.at_level(logging.WARNING, logger="leviathan.graphrag.rankers"):
        for backend, want in (("bge", 1.0), ("bedrock", 0.5), ("cohere", 0.6), ("  COHERE ", 0.6)):
            monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", backend)  # case/space-insensitive resolution
            assert rk.rerank_scores("q", ["a"]) == [want]
    assert [r for r in caplog.records if r.name == "leviathan.graphrag.rankers"] == []
    assert rk._UNKNOWN_BACKENDS_WARNED == set()


def test_empty_text_list_short_circuits_before_any_backend(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setattr(rk, "_cohere_rerank_scores",
                        lambda q, t: pytest.fail("an empty pool must never reach a vendor"))
    assert rk.rerank_scores("q", []) == []
