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
    # (_bedrock_rerank_scores rides the SHARED coalescer whose _fire dispatches by the ambient backend --
    # pin the lane or the cohere default routes this to the cohere leaf's key check; see fresh_coal)
    monkeypatch.setattr(rk, "_rerank_backend", lambda: "bedrock")
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
    # These are BEDROCK-LANE tests by construction (their packing shape -- one flattened list per
    # query, offset-chunked in the leaf -- is part of what they pin). The serving DEFAULT flipped to
    # cohere with the 2026-08-25 params ratification (`serving.retrieval.rerank_backend: cohere`), so
    # the lane is pinned HERE rather than inherited: on the ambient default the patched
    # _bedrock_rerank_call never fires and every invariant read as broken (9 reds, caught by the
    # projection wave's first full-suite sweep). The cohere lane's own dispatch behavior is covered by
    # its D-MW tests; the bedrock lane stays the declared rollback lane.
    monkeypatch.setattr(rk, "_rerank_backend", lambda: "bedrock")
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


# ── Phase-2 latency RCA: ONE Bedrock rerank request per turn ────────────────────────────────────────
# The Cohere Rerank quota (3 req/min, L-11512E58, Adjustable=FALSE) is permanent, and serving measured
# 6-8 requests per turn against it. The consequence is not latency: a mid-turn throttle drops the walk onto
# the CPU cross-encoder, the walk then keeps DIFFERENT evidence, and the SAME question answers differently
# run to run. Every test below pins one of the four mechanisms that split the batch. NOTE what the suite
# looked like before: every existing coalescer test starts its threads simultaneously (arrivals microseconds
# apart) with an explicit window=2.0, so a staggered walk, a post-close arrival and in-flight concurrency
# were all uncovered — which is how 6-8 requests/turn shipped green.
def test_coalescer_holds_one_batch_when_arrivals_are_staggered(monkeypatch, fresh_coal):
    """Real walk arrivals are p50 0.142 s apart but p90 0.760 s (pg-pool serialisation, n=212 measured).
    At the SHIPPED quiescence default a 0.4 s stagger must still be ONE request, not three."""
    import threading
    import time
    calls: list[list[str]] = []

    def fake_call(query, docs):
        calls.append(list(docs))
        return [1.0] * len(docs)

    monkeypatch.setattr(rk, "_bedrock_rerank_call", fake_call)
    assert rk._COALESCE_QUIESCENCE >= 1.0, "a sub-second quiescence closes the batch on a normal stagger"
    fresh_coal.expect(3, window=8.0)
    threads = []
    for i in range(3):
        t = threading.Thread(target=fresh_coal.submit, args=("q", [f"d{i}"]))
        t.start()
        threads.append(t)
        time.sleep(0.4)                                       # wider than the OLD 0.3 s serving quiescence
    for t in threads:
        t.join(timeout=20)
    assert len(calls) == 1 and calls[0] == ["d0", "d1", "d2"]


def test_coalescer_never_runs_two_requests_concurrently(monkeypatch, fresh_coal):
    """Leadership must be released AFTER the request. Released before it, arrivals during an in-flight call
    elect a second leader and fire a SECOND concurrent request — a positive feedback loop against a 3/min
    ceiling, reproduced in-VPC at 4 concurrent requests from one turn when the call was slow."""
    import threading
    import time
    live, peak, lk = [0], [0], threading.Lock()

    def slow_call(query, docs):
        with lk:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.6)
        with lk:
            live[0] -= 1
        return [1.0] * len(docs)

    monkeypatch.setattr(rk, "_bedrock_rerank_call", slow_call)
    fresh_coal.expect(1, window=5.0)                          # leader closes on COUNT, then the call is slow
    first = threading.Thread(target=fresh_coal.submit, args=("q", ["d"]))
    first.start()
    time.sleep(0.25)                                          # request #1 is now in flight
    fresh_coal.expect(2, window=5.0)
    later = [threading.Thread(target=fresh_coal.submit, args=("q", ["d"])) for _ in range(2)]
    for t in later:
        t.start()
    for t in [first, *later]:
        t.join(timeout=20)
    assert peak[0] == 1                                       # at most ONE request in flight, ever


def test_leader_abort_releases_the_flag_and_leaves_the_coalescer_usable(monkeypatch, fresh_coal):
    """Holding leadership across the request means a leader that dies while holding the flag would wedge
    EVERY later rerank in the process behind the 90 s follower timeout. The guard must release it."""
    def boom(_batch):
        raise RuntimeError("leader died holding the flag")

    monkeypatch.setattr(fresh_coal, "_fire", boom)
    fresh_coal.expect(1, window=1.0)
    with pytest.raises(RuntimeError):
        fresh_coal.submit("q", ["d"])
    assert fresh_coal._leading is False and fresh_coal._pending == []
    monkeypatch.undo()                                        # the process is not wedged: next turn works
    # undo() also dropped fresh_coal's bedrock-lane pin -- restore it with the fake, or the retry
    # dispatches to the ambient cohere default and dies on the key check (see the fixture comment)
    monkeypatch.setattr(rk, "_rerank_backend", lambda: "bedrock")
    monkeypatch.setattr(rk, "_bedrock_rerank_call", lambda q, d: [0.5] * len(d))
    fresh_coal.expect(1, window=1.0)
    assert fresh_coal.submit("q", ["d"]) == [0.5]


def test_early_close_decrements_the_hint_so_late_arrivals_still_coalesce(monkeypatch, fresh_coal):
    """`_expect = 0` after a drain pinned every later batch to the hardcoded 0.25 s idle window that NO env
    var can reach (measured as the closer on 10/10 serving-config turns). Decrement instead: whatever the
    walk still owes stays a COUNT, so the stragglers coalesce into one follow-up request."""
    import threading
    import time
    calls: list[list[str]] = []
    expect_after_drain: list[int] = []

    def fake_call(query, docs):
        calls.append(list(docs))
        expect_after_drain.append(fresh_coal._expect)
        return [1.0] * len(docs)

    monkeypatch.setattr(rk, "_coalesce_quiescence", lambda: 0.15)   # force batch 1 to close EARLY
    monkeypatch.setattr(rk, "_bedrock_rerank_call", fake_call)
    fresh_coal.expect(4, window=8.0)
    early = [threading.Thread(target=fresh_coal.submit, args=("q", [f"a{i}"])) for i in range(2)]
    for t in early:
        t.start()
    for t in early:
        t.join(timeout=20)                                    # batch 1 fired on quiescence with 2 of 4
    late = [threading.Thread(target=fresh_coal.submit, args=("q", [f"b{i}"])) for i in range(2)]
    for t in late:
        t.start()
    for t in late:
        t.join(timeout=20)
    assert len(calls) == 2
    assert expect_after_drain[0] == 2                          # NOT 0 — the two stragglers are still owed
    assert sorted(calls[1]) == ["b0", "b1"]                    # so batch 2 closed on COUNT, in ONE request
    assert expect_after_drain[1] == 0


def test_unexpect_closes_a_batch_a_hint_could_never_meet(monkeypatch, fresh_coal):
    """`expect` counts nodes that will RETRIEVE; only the reranker knows which of them actually score (an
    empty candidate set returns before the rerank). Retracting the difference is what keeps the closer a
    count instead of a timer — EXPECT_MET fired ZERO times in 28 measured serving turns without it."""
    import threading
    import time
    calls: list[int] = []

    def fake_call(query, docs):
        calls.append(len(docs))
        return [1.0] * len(docs)

    monkeypatch.setattr(rk, "_coalesce_quiescence", lambda: 60.0)   # neutralise the timer safety net
    monkeypatch.setattr(rk, "_bedrock_rerank_call", fake_call)
    fresh_coal.expect(3, window=60.0)                         # 3 promised, only 2 can ever arrive
    t0 = time.time()
    threads = [threading.Thread(target=fresh_coal.submit, args=("q", ["d"])) for _ in range(2)]
    for t in threads:
        t.start()
    time.sleep(0.3)
    rk.rerank_unexpect()                                      # node 3 found no candidates
    for t in threads:
        t.join(timeout=30)
    assert calls == [2]
    assert time.time() - t0 < 10                              # closed on the COUNT, not the 60 s window


def test_unexpect_never_goes_negative(fresh_coal):
    fresh_coal.expect(1)
    rk.rerank_unexpect(5)
    assert fresh_coal._expect == 0                            # a stray retraction can't poison the next turn


# ── knob resolution order: env > params > code default ──────────────────────────────────────────────
@pytest.mark.parametrize(("fn", "env", "key", "code_default"), [
    (lambda: rk._coalesce_window(), "GRAPHRAG_COALESCE_WINDOW",
     "serving.retrieval.coalesce_window", 4.0),
    (lambda: rk._coalesce_quiescence(), "GRAPHRAG_COALESCE_QUIESCENCE",
     "serving.retrieval.coalesce_quiescence", 2.5),
    (lambda: rk._rerank_max_attempts(), "GRAPHRAG_RERANK_MAX_ATTEMPTS",
     "serving.retrieval.rerank_max_attempts", 2),
])
def test_coalescer_knob_resolution_order(monkeypatch, fn, env, key, code_default):
    """Serving's taskdef env is the authority, params.yaml is the reviewable default, and a public clone
    with no params.yaml runs on the code default. All three legs asserted so a params edit can never be
    silently inert (the RCA's S8 finding: the doc tuned 0.8/4.0 while serving ran 0.3/1.5 from env)."""
    monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(rk._pr, "get", lambda path, default: default)      # no params.yaml -> code default
    assert fn() == code_default
    monkeypatch.setattr(rk._pr, "get", lambda path, default, _k=key: 9 if path == _k else default)
    assert fn() == 9                                                       # params beats the code default
    monkeypatch.setenv(env, "7")
    assert fn() == 7                                                       # env beats params


def test_params_yaml_carries_the_measured_coalescer_defaults():
    """The shipped params.yaml must actually declare the values the RCA measured — otherwise the code
    default is silently the only thing in play and a taskdef env change has nothing to match."""
    from leviathan.graphrag import params as pr
    assert pr.get("serving.retrieval.coalesce_window", None) == 4.0
    assert pr.get("serving.retrieval.coalesce_quiescence", None) == 2.5
    assert pr.get("serving.retrieval.rerank_max_attempts", None) == 2


# ── F1b: fail fast to bge instead of burning the adaptive ladder ────────────────────────────────────
def test_bedrock_client_retry_ladder_is_capped(monkeypatch):
    """max_attempts=8 adaptive meant a throttled call burned the whole ladder — while HOLDING the quota it
    was waiting for — before the caller-level bge fallback was even reached. 2 = one retry, then fall back."""
    boto3 = pytest.importorskip("boto3")
    captured: dict = {}

    def fake_client(service, **kw):
        captured["service"] = service
        captured["retries"] = kw["config"].retries
        raise RuntimeError("stop here — the client is all we wanted to inspect")

    monkeypatch.setattr(rk, "_bedrock_rerank_client", None)
    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.delenv("GRAPHRAG_RERANK_MAX_ATTEMPTS", raising=False)
    with pytest.raises(RuntimeError):
        rk._bedrock_rerank_call("q", ["a"])
    assert captured["service"] == "bedrock-agent-runtime"
    assert captured["retries"]["max_attempts"] == 2 and captured["retries"]["mode"] == "adaptive"


def test_bedrock_leaf_chunk_loop_is_the_oversized_caller_guard(monkeypatch):
    """The leaf's internal OFFSET loop still exists, and this pin is now explicitly scoped to what it is
    FOR after D-MW-9: one caller whose own texts exceed the per-request cap.

    It used to be the normal chunker — `_fire` handed it one flattened list per query and it split at
    offsets, so past 1,000 docs a single node's pool could straddle two requests. Packing moved up to
    `_fire` at CALLER boundaries (see the pin below and test_coalescer_cross_turn), and the loop stayed
    as the safety net for the one case packing cannot fix: a caller bigger than the cap, which `_fire`
    hands over whole rather than rejecting or splitting between nodes. Impossible on today's knobs
    (RERANK_POOL 60 x node_budget 16 = 960 < 1,000) and one knob away from possible."""
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


def test_fire_packs_at_caller_boundaries_not_offsets(monkeypatch):
    """THE COMPANION PIN (D-MW-9): the request boundary the WALK sees is a caller boundary, decided in
    `_fire` — the leaf loop above never sees a multi-caller list it could split mid-node.

    Three callers of 2 docs at a cap of 3: the flattened list is 6 docs, so offset chunking would have
    produced [3, 3] and cut caller 2 in half. Caller packing refuses to co-pack a second caller into a
    3-doc request that already holds 2, so it produces three whole-caller requests instead — a request
    MORE than the offset split, deliberately, because on the 1,000/min lane the extra request is cheap
    and the split ranking is not. COHERE lane: review round 2 gated packing there (bedrock keeps the
    pre-P2 flat shape precisely because its 3/min bucket makes extra requests expensive), and the
    multi-group cohere dispatch is concurrent, so composition is asserted order-insensitively."""
    import threading
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 3)
    seen: list[list[str]] = []
    lock = threading.Lock()

    def fake(q, docs):
        with lock:
            seen.append(list(docs))
        return [float(d) for d in docs]

    monkeypatch.setattr(rk, "_cohere_rerank_call", fake)
    coal = rk._RerankCoalescer()
    entries = [{"q": "q", "texts": [f"{c}1", f"{c}2"], "ev": threading.Event(),
                "scores": None, "err": None} for c in (1, 2, 3)]
    coal._fire(entries)
    assert sorted(seen) == [["11", "12"], ["21", "22"], ["31", "32"]]  # never [11,12,21] + [22,31,32]
    assert [e["scores"] for e in entries] == [[11.0, 12.0], [21.0, 22.0], [31.0, 32.0]]
    assert all(e["err"] is None and e["ev"].is_set() for e in entries)


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


# ── W4: fine-grained-tool-streaming beta ────────────────────────────────────────────────────────────
def test_call_opus_stream_sends_fgt_beta_on_anthropic_lane(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_FGT_STREAM", raising=False)      # default-on lane; fake client != Bedrock
    client = _FakeStreamClient(['{}'], _final_msg({"tldr": "t", "mechanism": "m", "sources": []}))
    ex.call_opus_stream(client, "sys", "user", model="m", tool=_TOOL, on_token=None)
    assert ex._FGT_BETA in client.stream_calls[0]["extra_headers"]["anthropic-beta"]


def test_call_opus_stream_ragged_escape_boundary_relays_and_parses_whole(monkeypatch):
    # deltas split mid-escape (\\ | n) and mid-key ("mech" | "anism"). The fake DERIVES the final message
    # from json.loads(''.join(deltas)) (review fold) so the parses-whole assertion has teeth — the ragged
    # chunks genuinely reassemble to the payload, not a canned duplicate.
    import json as _json

    monkeypatch.delenv("GRAPHRAG_FGT_STREAM", raising=False)
    deltas = ['{"tldr":"a\\', 'nb","mech', 'anism":"m","sources":[]}']
    payload = {"tldr": "a\nb", "mechanism": "m", "sources": []}
    client = _FakeStreamClient(deltas, _final_msg(_json.loads("".join(deltas))))
    got: list[str] = []
    out, _usage = ex.call_opus_stream(client, "sys", "user", model="m", tool=_TOOL, on_token=got.append)
    assert got == deltas                                          # every ragged chunk relayed, in order
    assert out == payload                                         # deltas reassemble to the exact payload


def test_call_opus_stream_gate_off_omits_extra_headers(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_FGT_STREAM", "off")
    client = _FakeStreamClient(['{}'], _final_msg({"tldr": "t", "mechanism": "m", "sources": []}))
    ex.call_opus_stream(client, "sys", "user", model="m", tool=_TOOL, on_token=None)
    assert "extra_headers" not in client.stream_calls[0]         # gate off -> no beta header


class AnthropicBedrock(_FakeStreamClient):
    """Class NAME is load-bearing: _fgt_stream_headers reads the lane from type(client).__name__."""


def test_call_opus_stream_bedrock_lane_defaults_off(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_FGT_STREAM", raising=False)      # unset -> Bedrock default is OFF (probe-gated)
    client = AnthropicBedrock(['{}'], _final_msg({"tldr": "t", "mechanism": "m", "sources": []}))
    ex.call_opus_stream(client, "sys", "user", model="m", tool=_TOOL, on_token=None)
    assert "extra_headers" not in client.stream_calls[0]


def test_call_opus_stream_bedrock_explicit_on_wins(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_FGT_STREAM", "on")               # explicit env wins for either lane
    client = AnthropicBedrock(['{}'], _final_msg({"tldr": "t", "mechanism": "m", "sources": []}))
    ex.call_opus_stream(client, "sys", "user", model="m", tool=_TOOL, on_token=None)
    assert ex._FGT_BETA in client.stream_calls[0]["extra_headers"]["anthropic-beta"]


def test_call_opus_stream_empty_env_keeps_anthropic_default_on(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_FGT_STREAM", "")                 # declared-but-empty (CI/.env) == unset
    client = _FakeStreamClient(['{}'], _final_msg({"tldr": "t", "mechanism": "m", "sources": []}))
    ex.call_opus_stream(client, "sys", "user", model="m", tool=_TOOL, on_token=None)
    assert ex._FGT_BETA in client.stream_calls[0]["extra_headers"]["anthropic-beta"]


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
    canary: list = []

    # FUTURES_READPATH S1: the agent now hands Q.run the threaded `futures_newest_first` bool, so the stub
    # takes it. RECORDED rather than swallowed with `**_`: the batch path is the one place a threaded kwarg
    # could be dropped per-worker instead of per-call, and a stub that ignored it would never say so.
    def fake_run(spec, query_fn=None, *, futures_newest_first=False):
        time.sleep(0.2)                                        # concurrent: wall ~0.2s, serial would be ~0.6s
        seen.append(spec.table)
        canary.append(futures_newest_first)
        if spec.table == "t1":
            raise RuntimeError("athena hiccup")
        return [{"value": 42, "knowledge_date": "2024-01-01"}]

    monkeypatch.setattr(ag.Q, "run", fake_run)
    monkeypatch.setattr(ag, "_forced_spec", lambda asof, inp: ag.Q.NumberQuery(table=inp["table"], metric="m",
                                                                               asof=asof))
    monkeypatch.setattr(ag, "tool_schema", lambda reg: {"name": "lookup", "input_schema": {"type": "object"}})
    monkeypatch.setattr(ag, "system_prompt", lambda reg, **kwargs: "sys")   # stub tolerates stats_tool= kwarg
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
    assert canary == [False, False, False]      # S1 threaded to EVERY worker in the batch, defaulting off


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


# ── Phase-2: the coalescer hint must be PHYSICALLY satisfiable ──────────────────────────────────────
@pytest.fixture()
def _spy_pool(monkeypatch):
    """Capture the max_workers _parallel_fill actually asks for."""
    import concurrent.futures as cf
    seen: dict = {}
    real = cf.ThreadPoolExecutor

    class _Spy(real):                                          # type: ignore[misc,valid-type]
        def __init__(self, max_workers=None, **kw):
            seen["max_workers"] = max_workers
            super().__init__(max_workers=max_workers, **kw)

    monkeypatch.setattr(cf, "ThreadPoolExecutor", _Spy)
    return seen


@pytest.mark.parametrize(("n_nodes", "expected", "walk_workers", "want_workers"), [
    (11, 10, 8, 10),      # the real serving shape: node budget 10 (+focus driver) vs 8 walk workers
    (11, 4, 8, 8),        # hint below the pool -> pool unchanged, no widening
    (3, 3, 8, 3),         # never more workers than nodes
])
def test_parallel_fill_pool_is_never_narrower_than_the_hint(monkeypatch, _spy_pool, n_nodes, expected,
                                                            walk_workers, want_workers):
    """A worker frees only when its _fill returns, and _fill returns only when its rerank resolves — so a
    pool narrower than the promised batch blocks the last arrivals BEHIND the request they were meant to
    join. Measured in-VPC: the floor is ceil(n_arrivals / workers) requests per turn at EVERY timer setting.
    Widening here does not widen DB concurrency (pgstore caps that at EVIDENCE_PG_POOL and releases the
    connection before the rerank)."""
    from leviathan.graphrag import evidence as evd
    from leviathan.graphrag import planner as pl
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    monkeypatch.setattr(pl, "_WALK_WORKERS", walk_workers)
    monkeypatch.setattr(evd, "embed", lambda *a, **k: [[0.0]])           # no bge load in a unit test
    hints: list[int] = []
    monkeypatch.setattr(rk, "rerank_expect", lambda n, window=None: hints.append(n))
    done: list[int] = []
    pl._parallel_fill(list(range(n_nodes)), done.append, "q", evd.retrieve, expected=expected)
    assert hints == [expected]
    assert _spy_pool["max_workers"] == want_workers
    assert sorted(done) == list(range(n_nodes))                          # every node still ran, exactly once


def test_parallel_fill_does_not_hint_or_widen_on_the_bge_backend(monkeypatch, _spy_pool):
    """bge never enters the coalescer (rankers._bedrock_rerank_scores is the only submit path), so the
    offline/eval lane keeps its byte-identical 8-wide pool."""
    from leviathan.graphrag import evidence as evd
    from leviathan.graphrag import planner as pl
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bge")
    monkeypatch.setattr(pl, "_WALK_WORKERS", 8)
    monkeypatch.setattr(evd, "embed", lambda *a, **k: [[0.0]])
    monkeypatch.setattr(rk, "rerank_expect", lambda n, window=None: pytest.fail("bge must not hint"))
    pl._parallel_fill(list(range(11)), lambda n: None, "q", evd.retrieve, expected=10)
    assert _spy_pool["max_workers"] == 8


def test_parallel_fill_retracts_the_hint_when_a_node_raises(monkeypatch):
    """A promised arrival that dies must retract, or the leader waits out the entire window for a caller
    that can never come."""
    from leviathan.graphrag import evidence as evd
    from leviathan.graphrag import planner as pl
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    monkeypatch.setattr(pl, "_WALK_WORKERS", 4)
    monkeypatch.setattr(evd, "embed", lambda *a, **k: [[0.0]])
    monkeypatch.setattr(rk, "rerank_expect", lambda n, window=None: None)
    retracted: list[int] = []
    monkeypatch.setattr(rk, "rerank_unexpect", lambda n=1: retracted.append(n))

    def boom(n):
        if n == 2:
            raise RuntimeError("pg fetch died")

    with pytest.raises(RuntimeError):
        pl._parallel_fill(list(range(4)), boom, "q", evd.retrieve, expected=4)
    assert retracted == [1]


def test_pg_retrieve_retracts_the_hint_on_an_empty_candidate_set(monkeypatch):
    """The hint counts nodes that will RETRIEVE. A node whose slice has no asof-legal candidates returns
    before the reranker, so it must give its slot back."""
    from leviathan.graphrag import pgstore
    monkeypatch.setattr(pgstore, "fetch_candidates", lambda *a, **k: [])
    retracted: list[int] = []
    monkeypatch.setattr(rk, "rerank_unexpect", lambda n=1: retracted.append(n))
    assert pgstore.pg_retrieve("q", "n", rerank=True, embed=lambda t: [[0.0]]) == []
    assert retracted == [1]
    retracted.clear()
    assert pgstore.pg_retrieve("q", "n", rerank=False, embed=lambda t: [[0.0]]) == []
    assert retracted == []                                   # the probe path never hinted, never retracts


def test_flat_retrieve_retracts_the_hint_on_an_empty_slice(monkeypatch):
    from leviathan.graphrag import evidence as evd
    retracted: list[int] = []
    monkeypatch.setattr(rk, "rerank_unexpect", lambda n=1: retracted.append(n))
    assert evd.retrieve("q", "n", rerank=True, records=[]) == []
    assert retracted == [1]
    retracted.clear()
    assert evd.retrieve("q", "n", rerank=False, records=[]) == []
    assert retracted == []


def test_floor_coalesces_its_contract_retrieves_and_keeps_contract_order(monkeypatch):
    """The deterministic floor retrieves with rerank=True over <=2 contracts. Serially that is TWO
    uncoalesced Bedrock requests on the slowest population in the fleet (p50 242.6 s / p95 1,163.6 s).
    Hint + overlap = one request; results are re-assembled in CONTRACT order so the banner is unchanged."""
    from leviathan.causal import schema as cs
    from leviathan.graphrag import evidence as evd
    from leviathan.graphrag import graph as g
    from leviathan.graphrag import orchestrator as orch
    mk = (lambda name: cs.CausalContract(contract=name, aliases=[name],
                                         drivers=[cs.Driver(id="d", type="hazard", sign="+", mechanism="m")]))
    graph = g.CausalGraph({"palm_oil": mk("palm_oil"), "soybean_oil": mk("soybean_oil")}, silver=set())
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    hints: list[int] = []
    monkeypatch.setattr(rk, "rerank_expect", lambda n, window=None: hints.append(n))
    order: list[str] = []

    def fake_retrieve(query, node, **kw):
        order.append(node)
        assert kw.get("rerank") is True                       # the floor really is on the rerank path
        return [{"date": "2026-01-0" + str(len(order)), "source": "GAIN",
                 "source_key": f"s3://{node}", "text": f"{node} text"}]

    monkeypatch.setattr(evd, "retrieve", fake_retrieve)
    out = orch._evidence_only("palm and soyoil", "2026-07-21", graph=graph, kind="hybrid",
                              exc=RuntimeError("tier dead"),
                              route_fn=lambda q, gr: ["palm_oil", "soybean_oil"])
    assert hints == [2]                                       # ONE coalesced request, not two serial ones
    assert [e["contract"] for e in out["evidence"]] == ["palm_oil", "soybean_oil"]   # contract order kept
    assert out["model"] == "(unavailable)" and out["contracts"] == ["palm_oil", "soybean_oil"]


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
