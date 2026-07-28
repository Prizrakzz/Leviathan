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

Fully offline: the Bedrock call and the boto3 client are fakes.
"""
from __future__ import annotations

import threading
import time

import pytest
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
