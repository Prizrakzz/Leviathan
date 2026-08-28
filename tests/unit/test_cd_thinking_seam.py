"""The c/d THINKING seam (2026-08-27) — env-parity pins for both halves.

The numbers half: GRAPHRAG_NUMBERS_THINKING=adaptive must add thinking={"type": "adaptive"} AND
raise max_tokens to 6000 on every create in the numbers lane; unset (or any other value) must be
BYTE-IDENTICAL to the pre-seam call shape — no thinking key, max_tokens 1500 — because the
rollback is unsetting one var with no deploy. Review wf_e16bbcd3 added two fail-closed gates and
an armed-lane sentinel, all pinned here: the SEAT gate (adaptive is 4.6+; the lane's default
seat is haiku-4-5, so an armed thinking var must go inert rather than 400 every call when the
model var rolls back), the PROVIDER gate (anthropic only), and the max_tokens truncation
sentinel (extract.py:557's never-serve-a-truncated-result doctrine, armed lane only — unset
keeps the historic silent pass-through, byte-identical). The writer half
(providers.synth_thinking, landed 2026-08-25) is pinned too so the resolvers never drift on the
arming word. Hermetic: injected fake client, no provider, no network.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag.numbers import agent as NA


class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.sent.append(kw)
        return self.outer.queue.pop(0)


class _FakeClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.sent = []
        self.messages = _Msgs(self)


class _Txt:
    type = "text"

    def __init__(self, t):
        self.text = t


class _Resp:
    def __init__(self, blocks, stop_reason=None):
        self.content = blocks
        self.stop_reason = stop_reason
        self.usage = None


def _run(monkeypatch, env, *, seat="claude-sonnet-5", provider=None, stop_reason=None):
    if env is None:
        monkeypatch.delenv("GRAPHRAG_NUMBERS_THINKING", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_NUMBERS_THINKING", env)
    if seat is None:
        monkeypatch.delenv("GRAPHRAG_NUMBERS_MODEL", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_NUMBERS_MODEL", seat)
    if provider is None:
        monkeypatch.delenv("GRAPHRAG_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_PROVIDER", provider)
    client = _FakeClient([_Resp([_Txt("no numbers needed.")], stop_reason=stop_reason)])
    NA.answer_numbers("hello there", asof="2026-06-08", client=client, query_fn=lambda sql: [])
    assert client.sent, "the loop made no call at all"
    return client.sent


def test_unset_is_byte_identical_no_thinking_key_and_1500(monkeypatch):
    for kw in _run(monkeypatch, None):
        assert "thinking" not in kw
        assert kw["max_tokens"] == 1500


def test_adaptive_on_a_capable_seat_adds_thinking_and_raises_the_budget(monkeypatch):
    # The arm design's PAIR: a thought budget inside 1,500 tokens would strangle the tool call it
    # exists to improve, so the seam moves both or neither.
    for kw in _run(monkeypatch, "adaptive", seat="claude-sonnet-5"):
        assert kw["thinking"] == {"type": "adaptive"}
        assert kw["max_tokens"] == 6000


def test_any_other_value_reads_as_off(monkeypatch):
    # Only the exact arming word counts — same fail-closed convention as synth_thinking.
    for kw in _run(monkeypatch, "on"):
        assert "thinking" not in kw
        assert kw["max_tokens"] == 1500


def test_the_seat_gate_keeps_the_default_haiku_seat_thought_free(monkeypatch):
    # Review wf_e16bbcd3 finding 1: the two env vars must not be a coupled rollback trap. With the
    # model var rolled back (lane default = haiku-4-5, pre-4.6, no adaptive), an armed thinking
    # var goes INERT instead of sending adaptive to a seat that 400s unretryably.
    for kw in _run(monkeypatch, "adaptive", seat=None):
        assert "thinking" not in kw
        assert kw["max_tokens"] == 1500


def test_the_provider_gate_keeps_bedrock_thought_free(monkeypatch):
    # Review wf_e16bbcd3 finding 4: adaptive on the bedrock InvokeModel path is unverified and the
    # 5-family seats are unmapped there — fail closed, anthropic only.
    for kw in _run(monkeypatch, "adaptive", seat="claude-sonnet-5", provider="bedrock"):
        assert "thinking" not in kw
        assert kw["max_tokens"] == 1500


def test_armed_truncation_raises_instead_of_serving_a_partial_final(monkeypatch):
    # Review wf_e16bbcd3 finding 2: with thinking billing into the same ceiling, a max_tokens stop
    # has no tool_use block and the empty text would ship as a FINAL answer. Fail closed.
    with pytest.raises(RuntimeError, match="TRUNCATED"):
        _run(monkeypatch, "adaptive", seat="claude-sonnet-5", stop_reason="max_tokens")


def test_unset_truncation_keeps_the_historic_pass_through(monkeypatch):
    # The parity promise cuts both ways: the sentinel is ARMED-LANE ONLY, so unset behaviour on a
    # truncated response stays byte-identical to the pre-seam lane (silently served, as before).
    sent = _run(monkeypatch, None, stop_reason="max_tokens")
    assert sent and "thinking" not in sent[0]


def test_the_writer_half_resolver_agrees_on_the_arming_word(monkeypatch):
    from leviathan.graphrag import providers as pv
    monkeypatch.delenv("GRAPHRAG_SYNTH_THINKING", raising=False)
    assert pv.synth_thinking() is None
    monkeypatch.setenv("GRAPHRAG_SYNTH_THINKING", "adaptive")
    assert pv.synth_thinking() == {"type": "adaptive"}
    monkeypatch.setenv("GRAPHRAG_SYNTH_THINKING", "on")
    assert pv.synth_thinking() is None


def test_the_effort_seam_numbers_half_parity(monkeypatch):
    # Dark plumbing (2026-08-27): GRAPHRAG_NUMBERS_EFFORT=<ladder word> adds output_config on a
    # capable seat; unset/garbage/haiku-seat = byte-identical (the API default is already high).
    monkeypatch.delenv("GRAPHRAG_NUMBERS_THINKING", raising=False)
    monkeypatch.setenv("GRAPHRAG_NUMBERS_EFFORT", "xhigh")
    monkeypatch.setenv("GRAPHRAG_NUMBERS_MODEL", "claude-sonnet-5")
    monkeypatch.delenv("GRAPHRAG_PROVIDER", raising=False)
    client = _FakeClient([_Resp([_Txt("no numbers needed.")])])
    NA.answer_numbers("hello", asof="2026-06-08", client=client, query_fn=lambda sql: [])
    assert client.sent[0]["output_config"] == {"effort": "xhigh"}
    monkeypatch.setenv("GRAPHRAG_NUMBERS_EFFORT", "turbo")      # not a ladder word -> off
    client = _FakeClient([_Resp([_Txt("no numbers needed.")])])
    NA.answer_numbers("hello", asof="2026-06-08", client=client, query_fn=lambda sql: [])
    assert "output_config" not in client.sent[0]
    monkeypatch.setenv("GRAPHRAG_NUMBERS_EFFORT", "low")
    monkeypatch.delenv("GRAPHRAG_NUMBERS_MODEL", raising=False)  # haiku seat -> gate holds
    client = _FakeClient([_Resp([_Txt("no numbers needed.")])])
    NA.answer_numbers("hello", asof="2026-06-08", client=client, query_fn=lambda sql: [])
    assert "output_config" not in client.sent[0]


def test_the_effort_seam_writer_half_resolver(monkeypatch):
    from leviathan.graphrag import providers as pv
    monkeypatch.delenv("GRAPHRAG_SYNTH_EFFORT", raising=False)
    assert pv.synth_effort() is None
    for w in ("low", "medium", "high", "xhigh", "max"):
        monkeypatch.setenv("GRAPHRAG_SYNTH_EFFORT", w)
        assert pv.synth_effort() == {"effort": w}
    monkeypatch.setenv("GRAPHRAG_SYNTH_EFFORT", "ultra")
    assert pv.synth_effort() is None


def test_the_writer_seam_never_arms_a_borrowed_haiku_call(monkeypatch):
    # The arm-d null-arm RCA (2026-08-27, measured on the first armed fire): _call_opus is NOT
    # writer-only -- route_llm borrows it with model=HAIKU (answer.py:1951). An armed synth
    # seam must go inert on that call instead of 400ing the ROUTER and killing the answer
    # before the writer runs. The writer's own opus call must still arm.
    from leviathan.graphrag import answer as an, providers as pv, extract as ex
    monkeypatch.setenv("GRAPHRAG_SYNTH_THINKING", "adaptive")
    seen = []

    def fake_serving_call(client, system, user, **kw):
        seen.append(kw)
        return {"contracts": []}, None

    monkeypatch.setattr(pv, "serving_call", fake_serving_call)
    monkeypatch.setattr(pv, "make_client", lambda: object())
    an._call_opus("s", "u", model=ex.HAIKU, tool={"name": "pick_contracts"})
    assert "thinking" not in seen[-1], "armed seam reached a pre-4.6 seat"
    an._call_opus("s", "u", model="claude-opus-5", tool={"name": "emit"})
    assert seen[-1].get("thinking") == {"type": "adaptive"}


def test_the_writer_seams_carry_the_provider_gate_too(monkeypatch):
    # Q-0 refuter catch (2026-08-28): the writer seams gated on SEAT only -- a bedrock arm would
    # ship thinking/output_config onto the legacy InvokeModel path (unretryable 400, not a null).
    from leviathan.graphrag import answer as an, providers as pv
    monkeypatch.setenv("GRAPHRAG_SYNTH_THINKING", "adaptive")
    monkeypatch.setenv("GRAPHRAG_SYNTH_EFFORT", "xhigh")
    monkeypatch.setenv("GRAPHRAG_PROVIDER", "bedrock")
    seen = []

    def fake_serving_call(client, system, user, **kw):
        seen.append(kw)
        return {"ok": True}, None

    monkeypatch.setattr(pv, "serving_call", fake_serving_call)
    monkeypatch.setattr(pv, "make_client", lambda: object())
    an._call_opus("s", "u", model="claude-opus-5", tool={"name": "emit"})
    assert "thinking" not in seen[-1] and "output_config" not in seen[-1]
    monkeypatch.setenv("GRAPHRAG_PROVIDER", "anthropic")
    an._call_opus("s", "u", model="claude-opus-5", tool={"name": "emit"})
    assert seen[-1].get("thinking") == {"type": "adaptive"}
    assert seen[-1].get("output_config") == {"effort": "xhigh"}
