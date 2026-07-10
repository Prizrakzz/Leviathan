"""Stage-1.5 serving latency fixes — mocked, offline.

Fix A (rerank): the CPU bge cross-encoder is swappable for Bedrock managed Cohere Rerank behind a flag;
scores remap to INPUT order (missing index -> floor), dispatch reads env, and a Bedrock failure falls back
to bge so a turn never breaks. Fix B (streaming): the note synthesis can stream token-by-token
(serving_call_stream / call_opus_stream) and returns the SAME (tool_input, degraded) shape as the buffered
path — with a buffered fallback on any stream-path error.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import tenacity
from leviathan.graphrag import extract as ex
from leviathan.graphrag import providers as pv
from leviathan.graphrag import rankers as rk

_TOOL = {"name": "emit_answer", "input_schema": {"type": "object"}}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setattr(pv, "wait_exponential", lambda **kw: tenacity.wait_none())


# ── Fix A: Bedrock Cohere Rerank ─────────────────────────────────────────────────────────────────────
class _FakeRerankClient:
    def __init__(self, results):
        self.results = results
        self.calls: list[dict] = []

    def rerank(self, **kw):
        self.calls.append(kw)
        return {"results": self.results}


def test_bedrock_rerank_remaps_to_input_order(monkeypatch):
    # results come back OUT of order and index 1 is absent -> it must floor to 0.0, aligned to input order
    fake = _FakeRerankClient([{"index": 2, "relevanceScore": 0.9}, {"index": 0, "relevanceScore": 0.4}])
    monkeypatch.setattr(rk, "_bedrock_rerank_client", fake)
    scores = rk._bedrock_rerank_scores("frost", ["a", "b", "c"])
    assert scores == [0.4, 0.0, 0.9]
    assert len(fake.calls) == 1                       # one call reranks the whole pool
    assert len(fake.calls[0]["sources"]) == 3         # all docs sent inline


def test_rerank_dispatch_uses_bedrock_when_flagged(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    monkeypatch.setattr(rk, "_bedrock_rerank_scores", lambda q, t: [1.0] * len(t))
    monkeypatch.setattr(rk, "_bge_rerank_scores", lambda q, t: pytest.fail("bge must not run on bedrock path"))
    assert rk.rerank_scores("q", ["a", "b"]) == [1.0, 1.0]


def test_rerank_dispatch_defaults_to_bge(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    monkeypatch.setattr(rk, "_bge_rerank_scores", lambda q, t: [0.1] * len(t))
    monkeypatch.setattr(rk, "_bedrock_rerank_scores", lambda q, t: pytest.fail("bedrock must not run on bge path"))
    assert rk.rerank_scores("q", ["a", "b"]) == [0.1, 0.1]


def test_rerank_bedrock_failure_falls_back_to_bge(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")

    def _boom(q, t):
        raise RuntimeError("bedrock rerank down")

    monkeypatch.setattr(rk, "_bedrock_rerank_scores", _boom)
    monkeypatch.setattr(rk, "_bge_rerank_scores", lambda q, t: [0.5] * len(t))
    assert rk.rerank_scores("q", ["a", "b"]) == [0.5, 0.5]   # turn never breaks


def test_rerank_empty_is_noop():
    assert rk.rerank_scores("q", []) == []


# ── the rerank coalescer (3-req/min quota -> ONE Bedrock request per turn) ──────────────────────────
@pytest.fixture()
def fresh_coal(monkeypatch):
    coal = rk._RerankCoalescer()
    monkeypatch.setattr(rk, "_COAL", coal)
    return coal


def test_coalescer_merges_concurrent_same_query_calls(monkeypatch, fresh_coal):
    import threading
    calls: list[tuple[str, list[str]]] = []

    def fake_call(query, docs):
        calls.append((query, list(docs)))
        return [float(i) for i in range(len(docs))]          # position-coded scores

    monkeypatch.setattr(rk, "_bedrock_rerank_call", fake_call)
    fresh_coal.expect(3, window=2.0)
    groups = [["a1", "a2"], ["b1"], ["c1", "c2", "c3"]]
    results: dict[int, list[float]] = {}

    def worker(i):
        results[i] = fresh_coal.submit("q", groups[i])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(calls) == 1                                    # ONE Bedrock request for the whole batch
    assert calls[0][1] == ["a1", "a2", "b1", "c1", "c2", "c3"]  # concatenated in submit order
    # each caller got exactly its own contiguous slice of the flat score list
    flat = [s for i in range(3) for s in results[i]]
    assert flat == [float(i) for i in range(6)]
    assert [len(results[i]) for i in range(3)] == [2, 1, 3]


def test_coalescer_leader_error_reaches_all_and_falls_back(monkeypatch, fresh_coal):
    import threading

    def boom(query, docs):
        raise RuntimeError("throttled hard")

    monkeypatch.setattr(rk, "_bedrock_rerank_call", boom)
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    monkeypatch.setattr(rk, "_bge_rerank_scores", lambda q, t: [9.0] * len(t))
    fresh_coal.expect(2, window=2.0)
    out: dict[int, list[float]] = {}

    def worker(i):
        out[i] = rk.rerank_scores("q", ["x", "y"])            # full path: coalesced fail -> bge fallback

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert out[0] == [9.0, 9.0] and out[1] == [9.0, 9.0]      # both members fell back, neither hung


def test_coalescer_groups_by_query(monkeypatch, fresh_coal):
    import threading
    calls: list[str] = []

    def fake_call(query, docs):
        calls.append(query)
        return [0.5] * len(docs)

    monkeypatch.setattr(rk, "_bedrock_rerank_call", fake_call)
    fresh_coal.expect(2, window=2.0)
    threads = [threading.Thread(target=fresh_coal.submit, args=(q, ["d"])) for q in ("q1", "q2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert sorted(calls) == ["q1", "q2"]                      # one request per distinct query


def test_bedrock_rerank_call_chunks_past_api_cap(monkeypatch):
    fake = _FakeRerankClient([])                              # results filled per call below

    class _Counting:
        def __init__(self):
            self.n = 0

        def rerank(self, **kw):
            self.n += 1
            docs = kw["sources"]
            return {"results": [{"index": i, "relevanceScore": 1.0} for i in range(len(docs))]}

    counting = _Counting()
    monkeypatch.setattr(rk, "_bedrock_rerank_client", counting)
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 2)
    scores = rk._bedrock_rerank_call("q", ["a", "b", "c", "d", "e"])
    assert counting.n == 3 and scores == [1.0] * 5            # 2+2+1 chunks, order preserved
    assert fake is not None


# ── Fix B: streamed synthesis ────────────────────────────────────────────────────────────────────────
def _final_msg(payload=None, stop="tool_use"):
    blk = SimpleNamespace(type="tool_use", input=payload or {"tldr": "t", "mechanism": "m", "sources": []})
    usage = SimpleNamespace(input_tokens=1, output_tokens=1,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(stop_reason=stop, content=[blk], usage=usage)


class _FakeStreamCtx:
    def __init__(self, deltas, final):
        self._deltas, self._final = deltas, final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for d in self._deltas:
            yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(partial_json=d))

    def get_final_message(self):
        return self._final


class _FakeStreamClient:
    def __init__(self, deltas, final):
        self.stream_calls: list[dict] = []
        self.messages = SimpleNamespace(stream=self._stream)
        self._deltas, self._final = deltas, final

    def _stream(self, **kw):
        self.stream_calls.append(kw)
        return _FakeStreamCtx(self._deltas, self._final)


def test_call_opus_stream_relays_deltas_and_returns_tool_input():
    client = _FakeStreamClient(['{"tldr":"', 'hi"}'], _final_msg({"tldr": "hi", "mechanism": "m", "sources": []}))
    got: list[str] = []
    out, _usage = ex.call_opus_stream(client, "sys", "user", model="m", tool=_TOOL, on_token=got.append)
    assert out == {"tldr": "hi", "mechanism": "m", "sources": []}
    assert got == ['{"tldr":"', 'hi"}']                     # deltas relayed in order


def test_call_opus_stream_truncation_raises():
    client = _FakeStreamClient([], _final_msg(stop="max_tokens"))
    with pytest.raises(ValueError):
        ex.call_opus_stream(client, "sys", "user", model="m", tool=_TOOL, on_token=None)


def test_serving_call_stream_matches_buffered_shape():
    client = _FakeStreamClient(['{}'], _final_msg({"tldr": "t", "mechanism": "m", "sources": []}))
    out, degraded = pv.serving_call_stream(client, "sys", "user", model="claude-sonnet-4-6",
                                           tool=_TOOL, on_token=lambda t: None)
    assert degraded is None and out["tldr"] == "t"


# ── Stage 1.6 WS-B: the numbers agent's per-batch tool calls run concurrently ───────────────────────
def test_numbers_agent_batch_parallel_preserves_order_and_errors(monkeypatch):
    import time

    from leviathan.graphrag.numbers import agent as ag

    class _Blk:
        def __init__(self, i, table):
            self.type, self.id, self.input = "tool_use", f"tu_{i}", {"table": table, "metric": "m"}

    class _FakeNumbersClient:
        """One response with 3 independent tool calls, then a final text answer."""
        def __init__(self):
            self.n = 0
            import types
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kw):
            self.n += 1
            import types
            if self.n == 1:
                return types.SimpleNamespace(content=[_Blk(0, "t0"), _Blk(1, "t1"), _Blk(2, "t2")])
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="done")])

    seen: list[str] = []

    def fake_run(spec, query_fn=None):
        time.sleep(0.2)                                        # concurrent: wall ~0.2s, serial would be ~0.6s
        seen.append(spec.table)
        if spec.table == "t1":
            raise RuntimeError("athena hiccup")
        return [{"value": 42, "knowledge_date": "2024-01-01"}]

    monkeypatch.setattr(ag.Q, "run", fake_run)
    monkeypatch.setattr(ag, "_forced_spec", lambda asof, inp: ag.Q.NumberQuery(table=inp["table"], metric="m",
                                                                               asof=asof))
    monkeypatch.setattr(ag, "tool_schema", lambda reg: {"name": "lookup", "input_schema": {"type": "object"}})
    monkeypatch.setattr(ag, "system_prompt", lambda reg: "sys")
    from types import SimpleNamespace
    fake_reg = SimpleNamespace(get=lambda t: (_ for _ in ()).throw(KeyError(t)))
    t0 = time.perf_counter()
    out = ag.answer_numbers("q", "2024-06-01", client=_FakeNumbersClient(), reg=fake_reg)
    wall = time.perf_counter() - t0
    calls = out["calls"]
    assert [c["query"].get("table") for c in calls] == ["t0", "t1", "t2"]   # ORDER preserved (= uses order)
    assert [c["status"] for c in calls] == ["ok", "error", "ok"]            # per-call error taxonomy intact
    assert "athena hiccup" in calls[1]["error"]
    assert wall < 0.5                                                       # batch overlapped, not serial


# ── Stage 1.6 WS-A: numbers ∥ walk via the lazy resolver ────────────────────────────────────────────
def test_run_hybrid_overlaps_numbers_and_resolves_at_synthesis(monkeypatch):
    import time

    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    from leviathan.graphrag import orchestrator as orch

    coffee = cs.CausalContract(contract="arabica_coffee", aliases=["arabica"],
                               drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="m")])
    graph = g.CausalGraph({"arabica_coffee": coffee}, silver=set())
    started = {"numbers": None, "call": None}

    def fake_numbers(query, asof, **kw):
        started["numbers"] = time.perf_counter()
        time.sleep(0.15)
        return {"answer": "n", "calls": [{"query": {"table": "silver_psd"}, "rows": [{"value": 1}],
                                         "status": "ok"}]}

    def fake_retrieve(q, contract, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": "s3://x", "text": "frost"}]

    captured = {}

    def fake_call(system, user, *, model, tool):
        started["call"] = time.perf_counter()
        captured["user"] = user if isinstance(user, str) else str(user)
        return {"tldr": "t", "mechanism": "m", "sources": []}

    monkeypatch.setattr(orch.na, "answer_numbers", fake_numbers)
    stages: list[str] = []
    out = orch.run_hybrid("arabica frost + numbers", "2024-01-01", graph=graph, call=fake_call,
                          retrieve=fake_retrieve, planner=None,
                          on_stage=lambda s, i: stages.append(s))
    assert out["intent"] == "hybrid" and len(out["number_calls"]) == 1     # numbers surfaced as before
    assert "SILVER NUMBERS" in captured["user"]                            # resolver joined before synthesis
    assert "numbers" in stages                                             # stage emitted on completion


def test_run_hybrid_numbers_failure_never_blocks_the_note(monkeypatch):
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    from leviathan.graphrag import orchestrator as orch

    coffee = cs.CausalContract(contract="arabica_coffee", aliases=["arabica"],
                               drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="m")])
    graph = g.CausalGraph({"arabica_coffee": coffee}, silver=set())

    def dead_numbers(query, asof, **kw):
        raise RuntimeError("athena down")

    monkeypatch.setattr(orch.na, "answer_numbers", dead_numbers)
    out = orch.run_hybrid("arabica frost", "2024-01-01", graph=graph,
                          call=lambda s, u, *, model, tool: {"tldr": "t", "mechanism": "m", "sources": []},
                          retrieve=lambda q, c, *, k, asof=None, near=None: [
                              {"date": "2021-07-20", "source": "GAIN", "source_key": "s3://x", "text": "frost"}],
                          planner=None)
    assert out["structured"]["tldr"] == "t"                                # the note still lands
    assert out["number_calls"] == []                                       # no-numbers, same as an error today


def test_serving_call_stream_falls_back_to_buffered_on_stream_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("stream sdk quirk")

    monkeypatch.setattr(pv.ex, "call_opus_stream", _boom)
    monkeypatch.setattr(pv.ex, "call_opus",
                        lambda *a, **k: ({"tldr": "buffered", "mechanism": "m", "sources": []},
                                         SimpleNamespace(input_tokens=1, output_tokens=1,
                                                         cache_creation_input_tokens=0, cache_read_input_tokens=0)))
    out, _degraded = pv.serving_call_stream(object(), "sys", "user", model="claude-sonnet-4-6",
                                            tool=_TOOL, on_token=lambda t: None)
    assert out["tldr"] == "buffered"                        # streaming failure never loses the answer
