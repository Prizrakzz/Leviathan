"""Exp-1 caching — mocked unit tests (no network). Covers the cost math, the cached call shape,
the sequential write-then-read tally, and the prime-then-fan-out concurrency contract."""
from __future__ import annotations

import threading

import pytest
from leviathan.graphrag import cache_probe as cp
from leviathan.graphrag import extract as ex

PREFIX_TOK = 2481   # the measured static prefix
CHUNK_TOK = 114


# ── a fake Anthropic client that simulates prefix caching ────────────────────────────
class _Block:
    type = "tool_use"
    input = {"entities": [], "relationships": [], "events": [], "quantitative_claims": [],
             "unmapped_relations": [], "unmapped_entities": []}


class _Usage:
    def __init__(self, input_tokens, output_tokens, cache_creation, cache_read):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation
        self.cache_read_input_tokens = cache_read


class _Resp:
    def __init__(self, usage):
        self.content = [_Block()]
        self.usage = usage


class FakeMessages:
    """Models the one invariant: a cache_control'd prefix is WRITTEN on first sight (cache_creation) and
    READ afterwards (cache_read). The check-and-set is locked so a concurrent fan-out is deterministic:
    exactly one writer, the rest readers."""

    def __init__(self):
        self.warm: set[str] = set()
        self.lock = threading.Lock()
        self.calls: list[dict] = []

    def create(self, **kw):
        self.calls.append(kw)
        sys = kw["system"]
        cached = isinstance(sys, list) and sys[0].get("cache_control") is not None
        if not cached:                                   # arm A: full prefix at full price, no buckets
            return _Resp(_Usage(PREFIX_TOK + CHUNK_TOK, 50, 0, 0))
        key = sys[0]["text"]
        with self.lock:
            warm = key in self.warm
            self.warm.add(key)
        if kw.get("max_tokens") == 0:                    # warm_cache prefill: write only, no output
            return _Resp(_Usage(0, 0, PREFIX_TOK, 0))
        if warm:
            return _Resp(_Usage(CHUNK_TOK, 50, 0, PREFIX_TOK))     # read
        return _Resp(_Usage(CHUNK_TOK, 50, PREFIX_TOK, 0))         # write


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()


# ── Usage cost math ──────────────────────────────────────────────────────────────────
def test_cost_for_prices_cache_buckets():
    pin, _ = ex.price(ex.SONNET)
    read = ex.Usage(input_tokens=CHUNK_TOK, output_tokens=0, cache_read=PREFIX_TOK)
    assert read.cost_for(ex.SONNET, "5m") == pytest.approx(CHUNK_TOK * pin + PREFIX_TOK * pin * 0.1)
    write5 = ex.Usage(cache_creation=PREFIX_TOK)
    assert write5.cost_for(ex.SONNET, "5m") == pytest.approx(PREFIX_TOK * pin * 1.25)
    write1h = ex.Usage(cache_creation=PREFIX_TOK)
    assert write1h.cost_for(ex.SONNET, "1h") == pytest.approx(PREFIX_TOK * pin * 2.0)
    # a warm read is cheaper than the 1-hour write of the same prefix
    assert read.cost_for(ex.SONNET, "5m") < write1h.cost_for(ex.SONNET, "1h")


def test_usage_from_reads_cache_fields():
    u = ex._usage_from(_Usage(10, 5, 2000, 300))
    assert (u.input_tokens, u.output_tokens, u.cache_creation, u.cache_read) == (10, 5, 2000, 300)
    assert u.total_input == 10 + 2000 + 300
    assert ex._usage_from(None).total_input == 0


# ── call_extract / warm_cache request shape ──────────────────────────────────────────
def test_call_extract_cache_sends_breakpoint_and_forces_tool():
    c = FakeClient()
    _, u = ex.call_extract(c, "SYS", "user", model=ex.SONNET, cache=True, tool=ex.extraction_tool())
    kw = c.messages.calls[-1]
    assert isinstance(kw["system"], list) and kw["system"][0]["cache_control"]["type"] == "ephemeral"
    assert kw["tool_choice"]["name"] == "emit_extraction"          # still forced
    assert u.cache_creation == PREFIX_TOK and u.cache_read == 0     # first sight → write


def test_call_extract_1h_sets_beta_header_and_ttl():
    c = FakeClient()
    ex.call_extract(c, "SYS", "user", cache=True, ttl="1h", tool=ex.extraction_tool())
    kw = c.messages.calls[-1]
    assert kw["system"][0]["cache_control"]["ttl"] == "1h"
    assert kw["extra_headers"]["anthropic-beta"] == ex._EXT_CACHE_BETA


def test_call_extract_nocache_sends_plain_system():
    c = FakeClient()
    _, u = ex.call_extract(c, "SYS", "user", cache=False, tool=ex.extraction_tool())
    assert isinstance(c.messages.calls[-1]["system"], str)
    assert u.cache_creation == 0 and u.cache_read == 0


def test_warm_cache_omits_tool_choice_and_writes():
    c = FakeClient()
    u = ex.warm_cache(c, "SYS", model=ex.SONNET, tool=ex.extraction_tool())
    kw = c.messages.calls[-1]
    assert kw["max_tokens"] == 0 and "tool_choice" not in kw     # max_tokens:0 rejects forced tool_choice
    assert u.cache_creation == PREFIX_TOK and u.output_tokens == 0


# ── arm tallies ──────────────────────────────────────────────────────────────────────
def test_sequential_cache_writes_first_then_reads():
    c = FakeClient()
    arm = cp.run_sequential(c, "SYS", ex.extraction_tool(), [f"m{i}" for i in range(5)],
                            cache=True, ttl=None, name="C")
    assert arm.usages[0].cache_creation == PREFIX_TOK and arm.usages[0].cache_read == 0
    assert all(u.cache_read == PREFIX_TOK and u.cache_creation == 0 for u in arm.usages[1:])
    assert arm.read_hit_rate() == pytest.approx(4 / 5)


def test_primed_fanout_beats_cold_hit_rate():
    msgs = [f"m{i}" for i in range(6)]
    k = 4
    cold = cp.run_concurrent(FakeClient(), "SYS", ex.extraction_tool(), msgs, ttl=None,
                             concurrency=k, primed=False, name="D_cold")
    primed = cp.run_concurrent(FakeClient(), "SYS", ex.extraction_tool(), msgs, ttl=None,
                               concurrency=k, primed=True, name="D_primed")
    assert cold.read_hit_rate() == pytest.approx((k - 1) / k)   # one writer, rest read (locked fake)
    assert primed.read_hit_rate() == pytest.approx(1.0)         # prime wrote → all fan-out read
    assert primed.read_hit_rate() > cold.read_hit_rate()
    assert "write=" in primed.note


# ── report: silent-miss check ────────────────────────────────────────────────────────
def _arm(name, usages, ttl=None):
    a = cp.Arm(name=name, ttl=ttl)
    a.usages = usages
    return a


def test_report_flags_silent_cache_miss():
    healthy = [ex.Usage(cache_creation=PREFIX_TOK)] + [ex.Usage(cache_read=PREFIX_TOK) for _ in range(3)]
    missed = [ex.Usage(input_tokens=PREFIX_TOK + CHUNK_TOK) for _ in range(4)]   # never wrote
    base = {"A": _arm("A", [ex.Usage(input_tokens=2595, output_tokens=50)]),
            "C_1h": _arm("C_1h", healthy, "1h"),
            "D_cold": _arm("D_cold", healthy), "D_primed": _arm("D_primed", healthy)}
    ok = cp.build_report({**base, "C_5m": _arm("C_5m", healthy)}, 0.003, 0.012, "OK", n=4, concurrency=4)
    bad = cp.build_report({**base, "C_5m": _arm("C_5m", missed)}, 0.003, 0.012, "OK", n=4, concurrency=4)
    assert "pass" in ok and "FAIL" not in ok
    assert "FAIL — cache_creation==0" in bad
