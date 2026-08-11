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

D-MW-9/10 (2026-08-11, P2) add the last two sections:
  * CALLER-BOUNDARY PACKING. The chunk boundary moved out of the leaf (offset arithmetic over a
    flattened list, where one node's texts could straddle two requests past 1,000 docs) and up into
    `_fire`, where a CALLER is atomic. The measurement that bought it (P2 entry check, 12 live calls on
    real corpus docs): whole-vs-chunked scores differ by 5.6e-4 and identical CHUNKED requests differ by
    2.9e-4 -- the same magnitude, so the delta is Cohere's cross-request replica noise, not a
    normalization effect. Ordering-invisible across nodes, avoidable within one, so it is avoided.
    Dispatch is per-backend: concurrent on cohere (1,000/min), sequential on bedrock (3/min).
  * THE KNOB CLAMP. The ladder budget was pinned in a CONSTANT, which is exactly what an env override
    replaces -- so the resolver re-derives it and clamps, and the pin below now runs against the
    RESOLVER, not the constants.

Fully offline: the Bedrock call, the boto3 client and `requests.post` are fakes.
"""
from __future__ import annotations

import logging
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


def test_cohere_ladder_fits_under_the_coalescer_member_wait(monkeypatch):
    """THE BUDGET PIN (diff-review): every queued coalescer member waits _COALESCE_MEMBER_WAIT seconds
    before raising TimeoutError and falling back to bge. If the cohere retry ladder's worst case exceeds
    it, a Cohere slowdown times out EVERY member to the 13.88 s/60-doc CPU pool while the leader keeps
    process-global leadership in flight -- the same incident class the 8-attempt adaptive ladder caused
    on the bedrock lane.

    D-MW-10 RE-POINTS THIS PIN AT THE RESOLVER. The constants are now defaults, and what actually runs is
    `_cohere_max_attempts()` x `_cohere_timeout()`; asserting the constants alone would leave the pin
    green while a taskdef env var ran a 240 s ladder. Both are asserted: the shipped defaults, and the
    resolved pair -- and `_cohere_ladder_seconds` is the ONE arithmetic used by both the clamp and this
    pin, so they cannot drift apart."""
    for env in ("GRAPHRAG_COHERE_MAX_ATTEMPTS", "GRAPHRAG_COHERE_TIMEOUT_CONNECT",
                "GRAPHRAG_COHERE_TIMEOUT_READ"):
        monkeypatch.delenv(env, raising=False)
    assert rk._cohere_ladder_seconds(rk._COHERE_MAX_ATTEMPTS, rk._COHERE_TIMEOUT) == 78.0   # 3x25 + 1 + 2
    timeout = rk._cohere_timeout()
    worst = rk._cohere_ladder_seconds(rk._cohere_max_attempts(timeout), timeout)
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
    `_fire`, before the packing -- and since D-MW-9 that ONE resolution also decides the dispatch shape
    (concurrent vs sequential), so a second read could split a batch across two dispatch modes too.
    Three distinct queries = three groups = the CONCURRENT cohere path, hence the sorted comparison."""
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
    assert sorted(cohere_hits) == ["q0", "q1", "q2"] and bedrock_hits == []
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


# ══ D-MW-9: CALLER-BOUNDARY PACKING + PER-BACKEND DISPATCH ══════════════════════════════════════════════
# The pins below drive `_fire` DIRECTLY (the leader/window/expect machinery is pinned above and is
# deliberately not re-tested here): `_fire` is where the request SHAPE is now decided, and shape is the
# whole of D-MW-9. Stubs stay at the leaf, per the signature-parity law.
def _entry(q: str, texts: list[str]) -> dict:
    """A queued caller, exactly as `submit` builds one -- the packing operates on these dicts."""
    return {"q": q, "texts": list(texts), "ev": threading.Event(), "scores": None, "err": None}


def _docs(caller: int, n: int) -> list[str]:
    """`caller#i` texts whose SCORE is decodable from the text. A mis-sliced reassembly is then not
    'some numbers came back' -- it is provably ANOTHER CALLER's numbers, which is the defect worth
    naming (a node ranking its neighbour's props is silent and unfalsifiable in production)."""
    return [f"{caller}#{i}" for i in range(n)]


def _score(doc: str) -> float:
    c, i = doc.split("#")
    return float(c) * 1000.0 + float(i)


def _expected(caller: int, n: int) -> list[float]:
    return [_score(d) for d in _docs(caller, n)]


def test_a_caller_never_straddles_two_requests(monkeypatch, coal):
    """THE D-MW-9 PIN. Three callers x 400 docs against the 1,000 cap: FIRST-FIT in arrival order packs
    400+400 into request 1 and 400 into request 2, and no caller is split.

    Under the old shape this batch was ONE flattened 1,200-doc list chunked at OFFSET 1,000, so caller 3's
    first 200 texts rode request 1 and its last 200 rode request 2 -- two different Cohere replicas
    scoring one node's pool, ~3e-4 apart (P2 entry check), inside the one comparison where the ordering is
    actually used. Nothing in production could have detected it.

    On the COHERE lane (review round 2 gated packing there -- bedrock keeps the pre-P2 flat shape), so
    the two groups dispatch CONCURRENTLY and the request-arrival order is nondeterministic: composition
    is asserted order-insensitively, the caller slices exactly."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    seen: list[list[str]] = []
    lock = threading.Lock()

    def fake(q, docs):
        with lock:
            seen.append(list(docs))
        return [_score(d) for d in docs]

    monkeypatch.setattr(rk, "_cohere_rerank_call", fake)
    entries = [_entry("q", _docs(c, 400)) for c in range(3)]
    coal._fire(entries)

    assert sorted(len(g) for g in seen) == [400, 800]            # 400+400 | 400 -- first-fit packing
    big = next(g for g in seen if len(g) == 800)
    assert big == entries[0]["texts"] + entries[1]["texts"]      # whole callers, concatenated, arrival order
    assert next(g for g in seen if len(g) == 400) == entries[2]["texts"]
    for c, e in enumerate(entries):
        assert e["scores"] == _expected(c, 400), "a caller got another caller's slice"
        assert e["err"] is None and e["ev"].is_set()


def test_a_caller_bigger_than_the_cap_is_its_own_group_and_falls_to_the_leaf_loop(monkeypatch, coal):
    """The guard, and the reason the leaf's internal offset loop SURVIVES. Impossible on today's knobs
    (RERANK_POOL 60 x the widest shipped node_budget 16 = 960 < 1,000, and one caller is one node) but one
    knob away, and without the guard the request is simply oversized and rejected. Cohere lane -- the
    only lane that packs (review round 2)."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 4)
    groups = rk._pack_callers([_entry("q", _docs(0, 9)), _entry("q", _docs(1, 2))], 4)
    assert [len(g) for g in groups] == [1, 1]                    # the oversized caller packs with nobody
    seen: list[list[str]] = []
    lock = threading.Lock()

    def fake(q, docs):
        with lock:
            seen.append(list(docs))
        return [_score(d) for d in docs]

    monkeypatch.setattr(rk, "_cohere_rerank_call", fake)
    big, small = _entry("q", _docs(0, 9)), _entry("q", _docs(1, 2))
    coal._fire([big, small])
    assert sorted(len(g) for g in seen) == [2, 9]                # ONE _fire-level request for the big one...
    assert big["scores"] == _expected(0, 9) and small["scores"] == _expected(1, 2)
    # ...and it is the LEAF that splits an oversized request internally -- asserted directly, on the real
    # leaf, in test_serving_latency.test_bedrock_leaf_chunk_loop_is_the_oversized_caller_guard.


@pytest.mark.parametrize("backend", ["bedrock", "cohere"])
def test_one_group_is_byte_identical_to_the_pre_packing_path(monkeypatch, coal, backend):
    """THE PROPERTY THE SHIPPED PINS REST ON, scoped EXACTLY (review round 2 caught the first wording
    overclaiming): a ONE-QUERY batch at <= _COALESCE_MAX_DOCS is ONE group and both lanes run the
    pre-D-MW-9 shape: one leaf call, one flattened list in arrival order, on the LEADER's own thread
    (no pool is created). 16 x pool-60 = 960 docs is the widest walk this estate ships. A MULTI-QUERY
    batch (cross-turn coalescing) on cohere dispatches concurrently at ANY size -- a deliberate,
    separately-pinned P2 delta (the next test); it is timing, not request composition, that changes."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", backend)
    seen: list[tuple[str, list[str]]] = []
    threads: set[str] = set()

    def fake(q, docs):
        seen.append((q, list(docs)))
        threads.add(threading.current_thread().name)
        return [_score(d) for d in docs]

    monkeypatch.setattr(rk, "_%s_rerank_call" % backend, fake)
    entries = [_entry("q", _docs(c, 60)) for c in range(16)]
    coal._fire(entries)

    assert len(seen) == 1 and seen[0][0] == "q"
    assert seen[0][1] == [t for e in entries for t in e["texts"]] and len(seen[0][1]) == 960
    assert threads == {threading.current_thread().name}          # dispatched inline, not through a pool
    for c, e in enumerate(entries):
        assert e["scores"] == _expected(c, 60) and e["err"] is None


def test_multi_query_batch_on_cohere_dispatches_concurrently_by_design(monkeypatch, coal):
    """THE DELIBERATE P2 DELTA, pinned as intended (review round 2: the byte-identity claim must not
    silently cover this case). Two DISTINCT-QUERY callers -- 4 docs total, 0.4% of the cap -- form two
    groups on the cohere lane and dispatch off the leader's thread. The requests were always separate
    (per-query grouping predates P2); P2 changes their TIMING only. Bedrock in the same shape stays on
    the leader's thread, sequentially."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    seen_threads: set[str] = set()

    def fake(q, docs):
        seen_threads.add(threading.current_thread().name)
        return [_score(d) for d in docs]

    monkeypatch.setattr(rk, "_cohere_rerank_call", fake)
    entries = [_entry("qA", _docs(0, 2)), _entry("qB", _docs(1, 2))]
    coal._fire(entries)
    assert all(e["err"] is None for e in entries)
    assert all(t.startswith("rerank-grp") for t in seen_threads), seen_threads   # pooled, by design

    seen_threads.clear()
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    monkeypatch.setattr(rk, "_bedrock_rerank_call", fake)
    entries = [_entry("qA", _docs(0, 2)), _entry("qB", _docs(1, 2))]
    coal._fire(entries)
    assert seen_threads == {threading.current_thread().name}                     # bedrock: leader inline


def test_bedrock_lane_keeps_the_pre_p2_flat_shape_past_the_cap(monkeypatch, coal):
    """Review round 2, minor 3: caller packing on BEDROCK could emit MORE requests than offset chunking
    (33 x 60 docs: packed [960,960,60] = 3 vs offset 2) -- extra draws on a 3/min NON-ADJUSTABLE bucket
    on the declared rollback lane. So bedrock does NOT pack: one flattened list per query, offset-chunked
    in the leaf, exactly the pre-P2 request count."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    seen: list[int] = []
    monkeypatch.setattr(rk, "_bedrock_rerank_call",
                        lambda q, docs: (seen.append(len(docs)) or [_score(d) for d in docs]))
    entries = [_entry("q", _docs(c, 60)) for c in range(33)]                     # 1,980 docs, one query
    coal._fire(entries)
    assert seen == [1980], seen        # ONE leaf call with the full flat list; the leaf offset-chunks it
    for c, e in enumerate(entries):
        assert e["scores"] == _expected(c, 60) and e["err"] is None


def test_cohere_dispatches_groups_concurrently_and_reassembles_in_group_order(monkeypatch, coal):
    """CONCURRENCY, pinned without a sleep race. Three groups; each leaf call first waits on a BARRIER (so
    all three must be in flight simultaneously -- sequential dispatch breaks it and the group's callers
    come back with an err), then group N blocks until group N+1 has finished, forcing completion order to
    be the exact REVERSE of dispatch order. Every caller must still receive ITS OWN slice: reassembly
    follows the group, never the finishing order."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 2)              # 2 docs per caller -> one caller per group
    n = 3
    barrier = threading.Barrier(n, timeout=5.0)
    done = [threading.Event() for _ in range(n)]
    finished: list[int] = []
    lock = threading.Lock()

    def fake(q, docs):
        c = int(docs[0].split("#")[0])
        barrier.wait()                                            # >1 in flight, or this raises
        if c + 1 < n:
            assert done[c + 1].wait(timeout=5.0)
        scores = [_score(d) for d in docs]
        with lock:
            finished.append(c)
        done[c].set()
        return scores

    monkeypatch.setattr(rk, "_cohere_rerank_call", fake)
    entries = [_entry("q", _docs(c, 2)) for c in range(n)]
    coal._fire(entries)

    assert [e["err"] for e in entries] == [None] * n, \
        "the barrier broke -- the groups were dispatched sequentially, not concurrently"
    assert finished == [2, 1, 0]                                  # completion order was the REVERSE...
    for c, e in enumerate(entries):
        assert e["scores"] == _expected(c, 2)                     # ...and every caller still got its own


def test_cohere_bounds_the_group_pool(monkeypatch, coal):
    """The pool is min(_COALESCE_GROUP_WORKERS, n_groups): a wide walk must not turn one turn into an
    unbounded burst against a shared key. 1,000 req/min is generous, not infinite."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 2)
    live, peak, lock = [], [0], threading.Lock()

    def fake(q, docs):
        with lock:
            live.append(1)
            peak[0] = max(peak[0], len(live))
        time.sleep(0.05)
        with lock:
            live.pop()
        return [_score(d) for d in docs]

    monkeypatch.setattr(rk, "_cohere_rerank_call", fake)
    entries = [_entry("q", _docs(c, 2)) for c in range(10)]       # 10 groups, pool of 4
    coal._fire(entries)
    assert 1 < peak[0] <= rk._COALESCE_GROUP_WORKERS == 4
    assert all(e["scores"] == _expected(c, 2) for c, e in enumerate(entries))


def test_a_failed_group_errors_only_its_own_callers(monkeypatch, coal):
    """PER-GROUP ERROR GRANULARITY. Before D-MW-9 the try/except wrapped a whole query's flattened list,
    so one 500 dropped every coalesced caller of that query to the 13.88 s/60-doc CPU pool together. The
    scope is now the REQUEST: its members fall back, the other groups' members keep their scores. (Within
    one group the broadcast is unchanged and correct -- those callers really did share the request.)"""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 2)
    boom = RuntimeError("cohere rerank HTTP 500: upstream")

    def fake(q, docs):
        if docs[0].startswith("1#"):
            raise boom
        return [_score(d) for d in docs]

    monkeypatch.setattr(rk, "_cohere_rerank_call", fake)
    ok, bad = _entry("q", _docs(0, 2)), _entry("q", _docs(1, 2))
    coal._fire([ok, bad])

    assert ok["err"] is None and ok["scores"] == _expected(0, 2)
    assert bad["err"] is boom and bad["scores"] is None           # this caller alone falls back to bge
    assert ok["ev"].is_set() and bad["ev"].is_set()               # and NOBODY waits out the 90 s member wait


def test_bedrock_keeps_sequential_dispatch(monkeypatch, coal):
    """The 3-req/min account-wide bucket is the entire reason the sequential loop exists; concurrency
    there is the positive-feedback loop `_lead` was corrected to prevent (4 concurrent requests from one
    turn, measured, behind the 410 s worst turn on record). Re-scoped with review round 2's packing gate:
    bedrock no longer packs at all (same-query callers flatten into ONE leaf call, pre-P2 shape), so the
    multi-request bedrock case is a MULTI-QUERY batch -- and those groups go out one at a time, in
    arrival order, on the leader's own thread."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    live, peak, order, lock = [], [0], [], threading.Lock()

    def fake(q, docs):
        with lock:
            live.append(1)
            peak[0] = max(peak[0], len(live))
            order.append(docs[0])
        time.sleep(0.02)
        with lock:
            live.pop()
        return [_score(d) for d in docs]

    monkeypatch.setattr(rk, "_bedrock_rerank_call", fake)
    entries = [_entry("q%d" % c, _docs(c, 2)) for c in range(3)]   # three DISTINCT queries = three groups
    coal._fire(entries)
    assert peak[0] == 1, "two concurrent BEDROCK requests from one batch -- the quota loop was widened"
    assert order == ["0#0", "1#0", "2#0"]                         # arrival order, one request at a time
    assert all(e["err"] is None for e in entries)


def test_concurrent_groups_still_stamp_the_turns_lane(monkeypatch, coal, key, lane):
    """THE TELEMETRY CONTRACT, unchanged and therefore load-bearing. `_fire` runs on the leader's thread,
    which carries the turn's collector; a pool thread carries NOTHING, and `_lane_record_request` is a
    thread-local read -- so dispatching without adopting the leader's collector would silently drop every
    request/doc/ms from the turn stamp, i.e. D-MW-6's gate instrument going dark exactly when P3's width
    starts producing multi-group turns. Driven through the REAL leaf with only `requests.post` stubbed."""
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    monkeypatch.setattr(rk, "_COALESCE_MAX_DOCS", 2)
    monkeypatch.setattr(requests, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        _Resp(200, _results(len(json["documents"]))))
    entries = [_entry("q", _docs(c, 2)) for c in range(3)]
    coal._fire(entries)
    assert all(e["err"] is None and len(e["scores"]) == 2 for e in entries)
    snap = lane.snapshot()
    assert snap["requests"] == 3 and snap["docs"] == 6            # one lane request per GROUP, all landed
    assert snap["backends"] == ["cohere"] and snap["fallbacks"] == 0


# ══ D-MW-10: the cohere ladder knobs resolve -- and the budget CLAMPS them ══════════════════════════════
@pytest.fixture()
def clean_knobs(monkeypatch):
    """No env, no params.yaml -> the code defaults, and a clean warn-dedupe set (module-global, so a
    leak would make the 'exactly one warning' pin depend on test ORDER)."""
    for env in ("GRAPHRAG_COHERE_MAX_ATTEMPTS", "GRAPHRAG_COHERE_TIMEOUT_CONNECT",
                "GRAPHRAG_COHERE_TIMEOUT_READ"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(rk._pr, "get", lambda path, default: default)
    rk._COHERE_BUDGET_WARNED.clear()
    yield
    rk._COHERE_BUDGET_WARNED.clear()


def test_cohere_knobs_resolve_env_then_params_then_default(monkeypatch, clean_knobs):
    """Same resolution order as every other serving knob, so a Cohere slowdown is tunable on the running
    task without a rebuild. The BEDROCK knobs are deliberately NOT part of this split: their fail-fast 2
    is rationalized against a ~1-token/20 s bucket, and that rationale does not transfer to 1,000/min."""
    assert rk._cohere_timeout() == rk._COHERE_TIMEOUT == (5, 20)
    assert rk._cohere_max_attempts() == rk._COHERE_MAX_ATTEMPTS == 3

    params = {"serving.retrieval.cohere_timeout_connect": 3, "serving.retrieval.cohere_timeout_read": 9,
              "serving.retrieval.cohere_max_attempts": 2}
    monkeypatch.setattr(rk._pr, "get", lambda path, default: params.get(path, default))
    assert rk._cohere_timeout() == (3.0, 9.0) and rk._cohere_max_attempts() == 2

    monkeypatch.setenv("GRAPHRAG_COHERE_TIMEOUT_READ", "11")
    monkeypatch.setenv("GRAPHRAG_COHERE_MAX_ATTEMPTS", "4")
    assert rk._cohere_timeout() == (3.0, 11.0)
    assert rk._cohere_max_attempts() == 4                        # 4x14 + 5 = 61 s, still under the wait
    assert rk._rerank_max_attempts() == 2                        # ...and bedrock's knob is untouched


def test_the_leaf_sends_the_resolved_timeout(monkeypatch, clean_knobs, key):
    monkeypatch.setenv("GRAPHRAG_COHERE_TIMEOUT_CONNECT", "2")
    monkeypatch.setenv("GRAPHRAG_COHERE_TIMEOUT_READ", "7")
    sent: dict = {}
    monkeypatch.setattr(requests, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        (sent.update(timeout=timeout), _Resp(200, _results(1)))[1])
    rk._cohere_rerank_call("q", ["a"])
    assert sent["timeout"] == (2.0, 7.0)                          # resolved, not the constant


def test_an_env_override_can_never_re_create_the_108s_ladder(monkeypatch, clean_knobs, caplog):
    """THE CLAMP. The diff review that caught the first shipped ladder at (5,30)x3 + 3 s = 108 s > the
    90 s member wait caught it in a CONSTANT -- and a constant is exactly what an env override replaces.
    A taskdef edit setting 9 attempts would otherwise run a 240 s ladder inside a 90 s wait: every member
    times out to the CPU pool while the leader holds process-global leadership. So the resolver clamps,
    once, loudly, naming both the ladder it was asked for and the bound it must fit."""
    monkeypatch.setenv("GRAPHRAG_COHERE_MAX_ATTEMPTS", "9")
    with caplog.at_level(logging.WARNING, logger=rk.log.name):
        first, again = rk._cohere_max_attempts(), rk._cohere_max_attempts()
    assert first == again == 3
    # Round-2 correction: the bound a member ACTUALLY has is the wait NET of the leader's pre-fire
    # timers (window + quiescence) -- the ladder must fit the BUDGET, not merely the wait.
    assert rk._cohere_ladder_seconds(first, rk._cohere_timeout()) < rk._cohere_member_budget()

    warns = [r.getMessage() for r in caplog.records if "CLAMPED" in r.getMessage()]
    assert len(warns) == 1, "one warning per distinct clamp, not one per rerank (this is a hot path)"
    assert "9 attempts" in warns[0] and "240" in warns[0] and "90" in warns[0]


def test_the_clamp_bounds_against_the_member_budget_not_the_bare_wait(monkeypatch, clean_knobs):
    """ROUND-2 MAJOR, the exact band the reviewer executed: READ=23 resolves a 3-attempt ladder to
    3x(5+23)+3 = 87 s -- UNDER the bare 90 s wait, but a member's wall clock is window + ladder, and
    87 + 4 > 90 times every member out while the leader is still in flight. The clamp must therefore
    bound against `_cohere_member_budget()` (wait - window - quiescence = 83.5 s at defaults), which
    clamps READ=23 to 2 attempts (59 s)."""
    monkeypatch.setenv("GRAPHRAG_COHERE_TIMEOUT_READ", "23")
    n = rk._cohere_max_attempts()
    assert n == 2, "READ=23 must clamp: a 87s 3-attempt ladder does not fit an 83.5s member budget"
    assert rk._cohere_ladder_seconds(n, rk._cohere_timeout()) < rk._cohere_member_budget()


def test_the_clamp_floors_at_one_attempt_and_still_warns(monkeypatch, clean_knobs, caplog):
    """A zero-attempt ladder is a silent PERMANENT fallback to bge -- strictly worse than a slow one --
    so the floor is 1 even when a single attempt alone busts the budget. ROUND-2 MINOR: the floor case
    must NOT run silently -- the log names the over-budget ladder that is actually running, else the
    defect hides behind a taskdef edit exactly as the resolver's own docstring warns."""
    monkeypatch.setenv("GRAPHRAG_COHERE_TIMEOUT_READ", "200")
    monkeypatch.setenv("GRAPHRAG_COHERE_MAX_ATTEMPTS", "1")       # nothing to lower: the floor case
    with caplog.at_level(logging.WARNING, logger=rk.log.name):
        assert rk._cohere_max_attempts() == 1
    floor_warns = [r.getMessage() for r in caplog.records if "STILL OVER BUDGET" in r.getMessage()]
    assert len(floor_warns) == 1, "an over-budget floor ladder ran with zero log signal"


def test_a_clamped_ladder_is_what_the_leaf_actually_runs(monkeypatch, clean_knobs, key, no_sleep):
    """End to end: the clamp is not advisory. 9 requested, 3 HTTP attempts made."""
    monkeypatch.setenv("GRAPHRAG_COHERE_MAX_ATTEMPTS", "9")
    calls: list[int] = []
    monkeypatch.setattr(requests, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        (calls.append(1), _Resp(429, text="rate limited"))[1])
    with pytest.raises(RuntimeError, match="HTTP 429"):
        rk._cohere_rerank_call("q", ["a"])
    assert len(calls) == 3 and len(no_sleep) == 2
