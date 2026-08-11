"""W10 (accumulate half): the rerank coalescer's `expect()` hint is CROSS-TURN ADDITIVE.

`_RerankCoalescer` is a module singleton whose `_expect` is shared by every turn in the process, and it
used to ASSIGN. At concurrency >= 2 that is a clobber, and the damaging direction is a hint that LOWERS
the count: turn A hints 4, three of A's callers are queued, turn B hints 2 -> `_expect` becomes 2, the
leader's `n >= exp` closer passes immediately, it fires a PARTIAL batch, and A's stragglers form a SECOND
Bedrock request. Two requests for one turn against a 3-req/min ACCOUNT-WIDE, non-adjustable quota
(L-11512E58) is the exact thing the coalescer exists to prevent -- so the clobber is a quota/correctness
defect, not the "latency-only" one an earlier record claimed.

NOT changed, and pinned here as such: leadership stays a process-global singleton. Per-turn leadership
would put N leaders against the same bucket at once (measured burst: 3 of 8 succeed, 4-8 throttle) and a
leader error propagates to every member, so one throttle drops a whole turn to the ~100x slower bge path.

Also closes SV-Q4-2: the managed-rerank botocore client must build its retry ladder from the knob
(default 2), never a hardcoded max_attempts=8 -- eight adaptive retries against a ~1-token/20 s bucket
can outlast the 90 s member wait and drop EVERY coalesced caller to bge simultaneously.

D-MW-2 (2026-08-11) adds the NATIVE cohere client pins at the bottom of the file, including THE
LEAF-DISPATCH PIN: `_RerankCoalescer._fire` used to name `_bedrock_rerank_call` LITERALLY, so a `cohere`
branch in rerank_scores alone would still have sent every COALESCED request -- i.e. every walk rerank --
to Bedrock's 3/min bucket. That test drives the coalesced path through the REAL `rerank_scores` dispatch
with BOTH leaves stubbed (the signature-parity law: stub the HTTP/boto3 leaves, never the dispatch).

Fully offline: the Bedrock call, the boto3 client and `requests.post` are fakes.
"""
from __future__ import annotations

import threading
import time
import types

import pytest
import requests
from leviathan.graphrag import rankers as rk


@pytest.fixture()
def coal(monkeypatch):
    """A private coalescer, installed as the module singleton (rerank_expect/unexpect route to it)."""
    c = rk._RerankCoalescer()
    monkeypatch.setattr(rk, "_COAL", c)
    return c


def _wait_until(pred, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


# -- the state contract -------------------------------------------------------------------------------
def test_expect_accumulates_and_never_lowers_an_outstanding_hint(coal):
    coal.expect(4, window=60.0)
    coal.expect(2, window=60.0)                    # a SECOND turn's hint arrives mid-flight
    assert coal._expect == 6                       # 6 callers are promised process-wide, not 2

    coal.unexpect(1)                               # retraction still applies to the pooled count
    assert coal._expect == 5
    coal.unexpect(99)
    assert coal._expect == 0                       # and still cannot go negative


def test_expect_ignores_negative_and_keeps_the_running_total(coal):
    coal.expect(3, window=60.0)
    coal.expect(-5, window=60.0)                   # a garbage hint must not subtract
    assert coal._expect == 3


# -- the behaviour the state contract exists for ------------------------------------------------------
def test_second_turn_hint_does_not_split_the_first_turns_batch(monkeypatch, coal):
    """THE REGRESSION FIXTURE. Turn A (4 callers) is mid-arrival when turn B hints 2.

    Accumulate  -> _expect 6, the leader closes on the COUNT once all 6 are in, `_fire` groups by
                   distinct query -> exactly ONE request per turn, A's four docs together.
    Assign (old)-> _expect 2, the leader breaks at n=3 and fires a partial batch -> A is split across
                   two requests and the run makes >2 requests in total.
    """
    monkeypatch.setattr(rk, "_coalesce_quiescence", lambda: 60.0)   # neutralise the timer safety net
    calls: list[tuple[str, list[str]]] = []
    fired = threading.Lock()

    def fake_call(query, docs):
        with fired:
            calls.append((query, list(docs)))
        return [1.0] * len(docs)

    monkeypatch.setattr(rk, "_bedrock_rerank_call", fake_call)

    coal.expect(4, window=60.0)                                    # turn A promises 4
    threads = [threading.Thread(target=coal.submit, args=("qA", [f"a{i}"])) for i in range(3)]
    for t in threads:
        t.start()
    assert _wait_until(lambda: len(coal._pending) == 3), "turn A's first three callers never queued"
    assert not calls, "the leader must still be waiting on the hint, not firing early"

    coal.expect(2, window=60.0)                                    # turn B lands its hint mid-flight
    # The leader polls every 50 ms, so it must be given a chance to OBSERVE the second hint while turn A
    # is still incomplete -- that observation is the whole defect. Without this pause the stragglers land
    # inside the same poll interval and the old assigning code passes by luck. Nothing here can go
    # flaky-red: a slow machine only makes the control weaker, never the fixed behaviour wrong.
    time.sleep(0.3)
    assert not calls, "the lowered hint closed turn A's batch early -- expect() is assigning, not accumulating"

    threads += [threading.Thread(target=coal.submit, args=("qB", [f"b{i}"])) for i in range(2)]
    threads += [threading.Thread(target=coal.submit, args=("qA", ["a3"]))]   # A's straggler
    for t in threads[3:]:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads)

    assert len(calls) == 2, f"one request per distinct query, not {len(calls)}: {calls}"
    by_query = dict(calls)
    assert sorted(by_query["qA"]) == ["a0", "a1", "a2", "a3"]      # turn A never split
    assert sorted(by_query["qB"]) == ["b0", "b1"]
    assert coal._expect == 0                                       # both hints fully consumed on drain


def test_leadership_stays_process_global(monkeypatch, coal):
    """SV-Q4-1: per-turn leadership is REJECTED. While one leader holds the queue, a caller from another
    turn must join its batch -- never elect a second leader and fire a concurrent request."""
    monkeypatch.setattr(rk, "_coalesce_quiescence", lambda: 60.0)
    in_flight: list[int] = []
    peak = [0]
    lock = threading.Lock()

    def fake_call(query, docs):
        with lock:
            in_flight.append(1)
            peak[0] = max(peak[0], len(in_flight))
        time.sleep(0.2)                                            # hold the "request" open
        with lock:
            in_flight.pop()
        return [1.0] * len(docs)

    monkeypatch.setattr(rk, "_bedrock_rerank_call", fake_call)
    coal.expect(2, window=60.0)
    ts = [threading.Thread(target=coal.submit, args=(f"q{i}", [f"d{i}"])) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    assert peak[0] == 1, "two concurrent Bedrock requests from one process -- leadership was not global"


# -- SV-Q4-2: the retry ladder comes from the knob ----------------------------------------------------
def test_bedrock_client_retry_ladder_uses_the_knob_not_a_hardcoded_eight(monkeypatch):
    import boto3

    captured: dict = {}

    class _FakeClient:
        def rerank(self, **kw):
            return {"results": [{"index": 0, "relevanceScore": 0.5}]}

    def fake_boto_client(name, **kw):
        captured["name"] = name
        captured["retries"] = kw["config"].retries
        return _FakeClient()

    monkeypatch.setattr(boto3, "client", fake_boto_client)
    monkeypatch.setattr(rk, "_bedrock_rerank_client", None)
    monkeypatch.delenv("GRAPHRAG_RERANK_MAX_ATTEMPTS", raising=False)

    assert rk._bedrock_rerank_call("q", ["d"]) == [0.5]
    assert captured["name"] == "bedrock-agent-runtime"
    assert captured["retries"]["mode"] == "adaptive"
    assert captured["retries"]["max_attempts"] == 2          # fail fast; NOT the old 8
    assert rk._RERANK_MAX_ATTEMPTS == 2

    monkeypatch.setattr(rk, "_bedrock_rerank_client", None)   # env override still reaches the client
    monkeypatch.setenv("GRAPHRAG_RERANK_MAX_ATTEMPTS", "3")
    rk._bedrock_rerank_call("q", ["d"])
    assert captured["retries"]["max_attempts"] == 3


# ── D-MW-2: the NATIVE cohere client, pinned the same way the bedrock client is above ────────────────
class _Resp:
    """The whole response surface the leaf reads: `status_code`, `.text`, `.json()`. `_cohere_post`
    handles status MANUALLY (never raise_for_status) precisely so a stub this small is faithful -- if the
    leaf ever starts calling a requests-only method, this class stops standing in and the pin goes red."""

    def __init__(self, status: int = 200, payload: dict | None = None, text: str = ""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def _results(n: int, base: float = 0.50) -> dict:
    """A well-formed native payload for `n` documents: one result per input index, ascending scores."""
    return {"results": [{"index": i, "relevance_score": round(base + i / 100.0, 4)} for i in range(n)]}


@pytest.fixture()
def key(monkeypatch):
    """A key in the LOCAL env name. Never a real one; the leaf only ever puts it in a header."""
    monkeypatch.setenv("COHERE_API", "k-test")
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.delenv("GRAPHRAG_RERANK_MODEL_COHERE", raising=False)


@pytest.fixture()
def no_sleep(monkeypatch):
    """Swap the MODULE's `time` for a shim -- real perf_counter (the lane records ms), instant recorded
    sleep. Patched on the module attribute, so the coalescer's own local `import time` (the leader's
    50 ms poll) is untouched and the backoff ladder is asserted rather than waited out."""
    slept: list[float] = []
    monkeypatch.setattr(rk, "time", types.SimpleNamespace(perf_counter=time.perf_counter,
                                                          sleep=slept.append))
    return slept


@pytest.fixture()
def lane(monkeypatch):
    """A turn's collector on THIS thread, torn down after (the slot is a thread-local and pytest's
    thread is reused across tests -- a leak would attribute the next test's reranks to this one)."""
    c = rk.RerankLaneCollector()
    rk.install_lane(c)
    yield c
    rk.clear_lane()


def test_cohere_client_pins_endpoint_headers_timeout_and_body(monkeypatch, key):
    sent: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, body=json, timeout=timeout)
        return _Resp(200, _results(len(json["documents"])))

    monkeypatch.setattr(requests, "post", fake_post)
    assert rk._cohere_rerank_call("q", ["a", "b"]) == [0.50, 0.51]
    assert sent["url"] == rk._COHERE_RERANK_URL == "https://api.cohere.com/v2/rerank"
    assert sent["headers"]["Authorization"] == "Bearer k-test"       # never logged, never traced
    assert sent["headers"]["Content-Type"] == "application/json"
    # EXPLICIT timeouts (connect, read). The Bedrock leaf never set any, and botocore's 60 s default read
    # timeout inside a 90 s coalescer member wait leaves no room for the bge fallback -- a recorded gotcha.
    # (5, 20) not (5, 30) -- diff review caught the first ladder at 108 s worst case ABOVE the 90 s
    # member wait; the budget pin below is the durable form of that catch.
    assert sent["timeout"] == rk._COHERE_TIMEOUT == (5, 20)
    assert sent["body"] == {"model": "rerank-v3.5", "query": "q", "documents": ["a", "b"], "top_n": 2}


def test_cohere_ladder_fits_under_the_coalescer_member_wait():
    """THE BUDGET PIN (diff-review): every queued coalescer member waits _COALESCE_MEMBER_WAIT seconds
    before raising TimeoutError and falling back to bge. If the cohere retry ladder's worst case exceeds
    it, a Cohere slowdown times out EVERY member to the 13.88 s/60-doc CPU pool while the leader keeps
    process-global leadership in flight -- the same incident class the 8-attempt adaptive ladder caused
    on the bedrock lane. The arithmetic is pinned so the constants cannot drift apart silently."""
    worst = rk._COHERE_MAX_ATTEMPTS * sum(rk._COHERE_TIMEOUT) + sum(rk._COHERE_BACKOFF)
    assert worst < rk._COALESCE_MEMBER_WAIT, (
        "cohere ladder worst case %.0f s must stay under the %d s member wait"
        % (worst, rk._COALESCE_MEMBER_WAIT))


def test_cohere_model_is_env_then_param_then_default(monkeypatch, key):
    seen: list[str] = []
    monkeypatch.setattr(requests, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        (seen.append(json["model"]), _Resp(200, _results(1)))[1])
    rk._cohere_rerank_call("q", ["a"])
    monkeypatch.setenv("GRAPHRAG_RERANK_MODEL_COHERE", "rerank-v9-preview")
    rk._cohere_rerank_call("q", ["a"])
    assert seen == [rk._DEFAULT_COHERE_RERANK_MODEL, "rerank-v9-preview"]   # env flips it without a rebuild


def test_cohere_retry_ladder_recovers_within_three_attempts(monkeypatch, key, no_sleep, lane):
    """429 -> 503 -> 200. THE LADDER IS INSIDE ONE LEAF CALL: three HTTP attempts, ONE lane request
    (requests count CHUNKS, not attempts), and the 429 is counted as a throttle."""
    seq = [_Resp(429, text="rate limited"), _Resp(503, text="upstream"), _Resp(200, _results(1, 0.77))]
    calls: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return seq[len(calls) - 1]

    monkeypatch.setattr(requests, "post", fake_post)
    assert rk._cohere_rerank_call("q", ["a"]) == [0.77]
    assert len(calls) == 3
    assert no_sleep == [1.0, 2.0] == list(rk._COHERE_BACKOFF)       # 1 s then 2 s, in that order
    snap = lane.snapshot()
    assert snap["requests"] == 1 and snap["docs"] == 1 and snap["throttles"] == 1
    assert snap["backends"] == ["cohere"] and snap["fallbacks"] == 0


def test_cohere_ladder_stops_at_three_and_raises_for_the_caller_level_fallback(monkeypatch, key,
                                                                               no_sleep, lane):
    calls: list[int] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        return _Resp(429, text="rate limited")

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        rk._cohere_rerank_call("q", ["a"])
    assert len(calls) == rk._COHERE_MAX_ATTEMPTS == 3               # no fourth attempt
    assert len(no_sleep) == 2                                       # ...and no sleep after the last one
    assert lane.snapshot()["throttles"] == 3                        # every 429 observed is counted


def test_cohere_retries_timeouts_and_connection_errors_only(monkeypatch, key, no_sleep):
    calls: list[int] = []

    def flaky(url, headers=None, json=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError("reset by peer")
        if len(calls) == 2:
            raise requests.exceptions.Timeout("read timed out")
        return _Resp(200, _results(1, 0.3))

    monkeypatch.setattr(requests, "post", flaky)
    assert rk._cohere_rerank_call("q", ["a"]) == [0.3] and len(calls) == 3


def test_cohere_4xx_raises_immediately_without_burning_the_ladder(monkeypatch, key, no_sleep, lane):
    """A rejected request (401 bad key, 400 bad body) is not a transient: retrying it only DELAYS the bge
    fallback. One attempt, no backoff, no throttle."""
    calls: list[int] = []
    monkeypatch.setattr(requests, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        (calls.append(1), _Resp(401, text="invalid api token"))[1])
    with pytest.raises(RuntimeError, match="HTTP 401"):
        rk._cohere_rerank_call("q", ["a"])
    assert len(calls) == 1 and no_sleep == []
    assert lane.snapshot()["throttles"] == 0


def test_cohere_chunks_at_the_coalesce_cap_and_realigns_to_input_order(monkeypatch, key, lane):
    """1,000 is ALSO the native per-request document cap, so the SAME chunk loop applies. Monkeypatched to
    2 (the test_serving_latency.py:367 pattern) so 5 docs = 3 requests; each stub answers OUT of order, so
    the pin is the realignment to INPUT order, not the vendor's ranking."""
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 2)
    seen: list[list[str]] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        docs = json["documents"]
        seen.append(list(docs))
        assert json["top_n"] == len(docs)                            # top_n tracks the CHUNK, not the pool
        out = [{"index": i, "relevance_score": float(d)} for i, d in enumerate(docs)]
        return _Resp(200, {"results": list(reversed(out))})

    monkeypatch.setattr(requests, "post", fake_post)
    assert rk._cohere_rerank_call("q", ["1", "2", "3", "4", "5"]) == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert seen == [["1", "2"], ["3", "4"], ["5"]]
    snap = lane.snapshot()
    assert snap["requests"] == 3 and snap["docs"] == 5               # one lane request per CHUNK


def test_cohere_truncates_and_never_sends_an_empty_document(monkeypatch, key):
    """Shape-mirrored on the bedrock leaf: the same rerank_max_chars truncation and the same empty->' '
    guard, so a whitespace-only prop cannot 400 the whole batch out to the bge fallback."""
    from leviathan.graphrag import params as pr
    monkeypatch.setattr(pr, "get", lambda k, d=None: 4 if k == "serving.retrieval.rerank_max_chars" else d)
    sent: dict = {}
    monkeypatch.setattr(requests, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        (sent.update(body=json), _Resp(200, _results(len(json["documents"]))))[1])
    rk._cohere_rerank_call("  a very long query  ", ["  ", "abcdefgh"])
    assert sent["body"]["query"] == "a ve" and sent["body"]["documents"] == [" ", "abcd"]


# ── THE LEAF-DISPATCH PIN (the review catch this whole seam turns on) ────────────────────────────────
def test_cohere_backend_drives_the_coalesced_path_and_never_touches_the_bedrock_leaf(monkeypatch, coal):
    """With GRAPHRAG_RERANK_BACKEND=cohere, TWO concurrent callers go through the REAL `rerank_scores`
    dispatch -> `_cohere_rerank_scores` -> the coalescer -> `_fire`. Both leaves are stubbed; the bedrock
    one must NEVER be entered, and bge must never be reached either (that would be a silent fallback
    wearing a cohere label -- the recon's worst trap).

    Before D-MW-2 this test fails on the bedrock counter: `_fire` named `_bedrock_rerank_call` literally,
    so every coalesced request -- i.e. every walk rerank -- went to the 3-req/min bucket regardless."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setattr(rk, "_coalesce_quiescence", lambda: 60.0)
    fired: list[tuple[str, list[str]]] = []
    bedrock_hits, bge_hits = [], []

    def fake_cohere(query, docs):
        fired.append((query, list(docs)))
        return [0.7] * len(docs)

    monkeypatch.setattr(rk, "_cohere_rerank_call", fake_cohere)
    monkeypatch.setattr(rk, "_bedrock_rerank_call",
                        lambda q, d: (bedrock_hits.append(q), [0.0] * len(d))[1])
    monkeypatch.setattr(rk, "_bge_rerank_scores", lambda q, t: (bge_hits.append(q), [0.0] * len(t))[1])

    out: dict = {}

    def one(name, q, texts):
        out[name] = rk.rerank_scores(q, texts)

    rk.rerank_expect(2, window=60.0)
    ts = [threading.Thread(target=one, args=("A", "qA", ["a0", "a1"])),
          threading.Thread(target=one, args=("B", "qB", ["b0"]))]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in ts)

    assert bedrock_hits == [], "the coalescer fired the BEDROCK leaf under GRAPHRAG_RERANK_BACKEND=cohere"
    assert bge_hits == [], "a silent bge fallback wearing a cohere label"
    assert out == {"A": [0.7, 0.7], "B": [0.7]}                      # each caller got its OWN slice back
    assert sorted(q for q, _ in fired) == ["qA", "qB"]               # batches stay per-query


def test_fire_resolves_the_leaf_once_per_batch(monkeypatch, coal):
    """A mid-fire env flip must not split ONE batch across two vendors: the leaf is resolved ONCE per
    `_fire`, before the per-query loop."""
    n = {"i": 0}

    def flipping():
        n["i"] += 1
        return "cohere" if n["i"] == 1 else "bedrock"

    monkeypatch.setattr(rk, "_rerank_backend", flipping)
    bedrock_hits, cohere_hits = [], []
    monkeypatch.setattr(rk, "_bedrock_rerank_call",
                        lambda q, d: (bedrock_hits.append(q), [0.0] * len(d))[1])
    monkeypatch.setattr(rk, "_cohere_rerank_call",
                        lambda q, d: (cohere_hits.append(q), [0.5] * len(d))[1])
    batch = [{"q": f"q{i}", "texts": ["t"], "ev": threading.Event(), "scores": None, "err": None}
             for i in range(3)]
    coal._fire(batch)
    assert n["i"] == 1                                               # resolved once, not once per group
    assert cohere_hits == ["q0", "q1", "q2"] and bedrock_hits == []
    assert all(e["scores"] == [0.5] and e["err"] is None and e["ev"].is_set() for e in batch)


def test_bedrock_stays_the_leaf_for_every_other_backend_value(monkeypatch, coal):
    """The dispatch is a cohere-vs-else test, so `bedrock` (and anything reaching `_fire` at all) keeps
    the managed leaf -- the flip is one env value in ONE direction, never a silent re-route."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    bedrock_hits, cohere_hits = [], []
    monkeypatch.setattr(rk, "_bedrock_rerank_call",
                        lambda q, d: (bedrock_hits.append(q), [0.2] * len(d))[1])
    monkeypatch.setattr(rk, "_cohere_rerank_call",
                        lambda q, d: (cohere_hits.append(q), [0.9] * len(d))[1])
    assert rk.rerank_scores("q", ["a"]) == [0.2]
    assert bedrock_hits == ["q"] and cohere_hits == []
