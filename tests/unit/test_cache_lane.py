"""D-CL, the cache lane -- two owner-ratified transport changes, both measured off
scratchpad/cost_census_from_logs.json (3 deep turns, 2026-09-04).

  (1) numbers/agent.py: the tool loop grows a conversation and, until now, marked NO breakpoint on it,
      so every round re-sent the whole thing at full input price (mean 59,484 uncached tokens/turn).
      A MOVING PAIR of cache_control markers on the two most recent user turns makes the conversation
      a cacheable prefix.
  (2) answer.py::_call_opus: the writer's so-called "stable" user block is the per-turn causal-graph
      block, written to cache EVERY turn (54,744 / 47,577 / 39,066 tokens) at the 1.25x premium and
      read back by a repair call that fired 0 of 34 times -- but the census's second arm (the same
      three questions re-asked minutes later) READ that block on 2 of 3 turns, which makes the marker
      14 percent cheaper over all six writer calls. It CAN ship plain (GRAPHRAG_SYNTH_PLAIN_EVIDENCE=on);
      by the owner's word (2026-09-06) it stays CACHED by default.

THE LOAD-BEARING CLAIM OF BOTH HALVES IS THE SAME ONE: `cache_control` is TRANSPORT METADATA. It is
never rendered to the model, so a marked and an unmarked request put the identical tokens in front of
the identical seat. Quality is identical BY CONSTRUCTION, and these pins prove the construction --
each half asserts that the message payload is byte-identical once the markers are stripped, and that
the loop's own outputs do not move.

(1) defaults ON with the one-env-var rollback GRAPHRAG_NUMBERS_INCREMENTAL_CACHE=off; (2) defaults OFF
(HEAD's marked block) with the opt-in GRAPHRAG_SYNTH_PLAIN_EVIDENCE=on. The defaults are pinned here, not
assumed.
"""
from __future__ import annotations

import copy
import json
import types

import anthropic
import httpx
import pytest
import tenacity
from leviathan.graphrag import answer as an
from leviathan.graphrag import providers as pv
from leviathan.graphrag.numbers import agent as A


# ── shared: counting breakpoints and stripping them ──────────────────────────────────────────────────
def _breakpoints(blocks) -> int:
    """cache_control markers carried by one content list (a plain-string content carries none)."""
    if not isinstance(blocks, list):
        return 0
    return sum(1 for b in blocks if isinstance(b, dict) and "cache_control" in b)


def _request_breakpoints(kw: dict) -> int:
    """Every marker in one messages.create request -- the number the API caps at 4."""
    n = _breakpoints(kw.get("system"))
    for m in kw.get("messages") or []:
        n += _breakpoints(m.get("content"))
    return n


def _stripped(messages):
    """The message list with every cache_control key removed -- what the model actually reads."""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = [{k: v for k, v in b.items() if k != "cache_control"} if isinstance(b, dict) else b
                 for b in c]
        out.append({**m, "content": c})
    return out


# ── (1) the numbers loop ─────────────────────────────────────────────────────────────────────────────
_SPEC = {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot", "period": "2023"}


def _use(tid):
    return types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, input=dict(_SPEC), id=tid)


def _txt(t):
    return types.SimpleNamespace(type="text", text=t)


def _resp(content, stop="tool_use"):
    return types.SimpleNamespace(content=content, stop_reason=stop)


class _SnapClient:
    """A fake whose messages.create SNAPSHOTS the request it was handed. The snapshot is deep -- the
    loop mutates ONE `convo` list in place, so a shallow capture would show every round the final
    state and could not see a marker move at all."""

    def __init__(self, script):
        self.queue = list(script)
        self.sent: list[dict] = []
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.sent.append(copy.deepcopy(kw))
        return self.queue.pop(0)


def _script():
    """Three lookup rounds then a final text answer -> four create() calls, three tool-result turns:
    the shortest script in which the pair can be seen MOVING (round 4 must drop round 1's marker)."""
    return [_resp([_use("t1")]), _resp([_use("t2")]), _resp([_use("t3")]),
            _resp([_txt("Argentina corn ending stocks were 2,462,000 MT.")], "end_turn")]


def _run(**env):
    """One full loop against the fixed script; returns (out, the per-round request snapshots)."""
    client = _SnapClient(_script())
    out = A.answer_numbers("What were Argentina corn ending stocks?", asof="2024-06-01",
                           client=client, query_fn=lambda sql: [{"value": "2462000",
                                                                 "knowledge_date": "2024-01-10"}])
    return out, client.sent


def test_cl1_the_checkpoint_moves_onto_the_latest_user_turn_and_never_exceeds_three(monkeypatch):
    """Round by round: 0 moving markers on the opening request (nothing has been appended yet), one
    after the first tool-result turn, two thereafter -- and NEVER a third, whatever the round count.
    The API's cap is 4 per request; this loop spends 3 and leaves one slot free."""
    monkeypatch.delenv("GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", raising=False)   # DEFAULT = on
    _, sent = _run()
    assert len(sent) == 4
    assert [_breakpoints(kw["system"]) for kw in sent] == [1, 1, 1, 1]        # the static block, always
    moving = [_request_breakpoints(kw) - 1 for kw in sent]
    assert moving == [0, 1, 2, 2], moving
    assert max(_request_breakpoints(kw) for kw in sent) == 3 <= 4             # the API ceiling holds

    for kw in sent:
        msgs = kw["messages"]
        marked = [i for i, m in enumerate(msgs) if _breakpoints(m.get("content"))]
        assert all(msgs[i]["role"] == "user" for i in marked), "a marker landed off a user turn"
        if marked:
            # the LATEST user turn always carries one, and it sits on that turn's LAST block
            assert marked[-1] == len(msgs) - 1, "the newest marker is not on the latest turn"
            for i in marked:
                blocks = msgs[i]["content"]
                assert "cache_control" in blocks[-1] and blocks[-1]["cache_control"] == \
                    {"type": "ephemeral"}
                assert _breakpoints(blocks) == 1, "a turn carries more than one marker"
        # turn 1's plain-string content is never converted into blocks to carry a marker
        assert isinstance(msgs[0]["content"], str)


def test_cl1_the_marked_conversation_is_byte_identical_to_the_unmarked_one(monkeypatch):
    """THE QUALITY ARGUMENT, made mechanically. Same script, both flag positions: every round's
    message list is identical once the cache_control keys are stripped, and so are the loop's own
    outputs. The model cannot tell the two runs apart because there is nothing to tell apart."""
    monkeypatch.delenv("GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", raising=False)
    on_out, on_sent = _run()
    monkeypatch.setenv("GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", "off")
    off_out, off_sent = _run()

    assert len(on_sent) == len(off_sent) == 4
    for k, (a, b) in enumerate(zip(on_sent, off_sent)):
        assert _stripped(a["messages"]) == _stripped(b["messages"]), f"round {k + 1} payload moved"
        assert a["system"] == b["system"] and a["tools"] == b["tools"]
        assert {k2: v for k2, v in a.items() if k2 != "messages"} == \
               {k2: v for k2, v in b.items() if k2 != "messages"}
    assert on_out == off_out                                   # answer, calls, tables_queried: unmoved
    # ... and the ONLY difference anywhere is the markers themselves
    assert sum(_request_breakpoints(kw) for kw in on_sent) == 4 + 5          # 4 system + 0+1+2+2 moving
    assert sum(_request_breakpoints(kw) for kw in off_sent) == 4             # system only, as at HEAD


def test_cl1_off_restores_the_pre_change_request_and_the_default_is_on(monkeypatch):
    """The rollback is one env var and no deploy: off/0/false/no all disarm, anything else leaves the
    new behaviour standing (the `_stats_tool_on` fail-safe-on idiom -- a marker cannot hurt an answer,
    so an unreadable value must not silently forfeit the saving)."""
    monkeypatch.delenv("GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", raising=False)
    assert A._incremental_cache_on() is True                                  # DEFAULT = the new behaviour
    for word in ("off", "OFF", "0", "false", "False", "no", " off "):
        monkeypatch.setenv("GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", word)
        assert A._incremental_cache_on() is False, word
    for word in ("on", "1", "true", "yes", "banana"):
        monkeypatch.setenv("GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", word)
        assert A._incremental_cache_on() is True, word

    monkeypatch.setenv("GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", "off")
    _, sent = _run()
    assert [_request_breakpoints(kw) for kw in sent] == [1, 1, 1, 1]          # the system block alone


def test_cl1_the_mover_marks_the_pair_drops_the_rest_and_touches_nothing_else():
    """The mover in isolation, on a hand-built conversation: two markers survive, the third-newest is
    CLEARED as the pair advances (so the count is bounded however long the loop runs), assistant turns
    are never touched, and the only mutation anywhere is the cache_control key."""
    convo = [{"role": "user", "content": "as-of + question"},
             {"role": "assistant", "content": [types.SimpleNamespace(type="tool_use")]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "1"}]},
             {"role": "assistant", "content": [types.SimpleNamespace(type="tool_use")]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "b", "content": "2"}]}]
    before = _stripped(convo)
    A._move_cache_checkpoint(convo)
    assert [_breakpoints(m.get("content")) for m in convo] == [0, 0, 1, 0, 1]
    assert _stripped(convo) == before, "the mover changed something other than a marker"

    convo.append({"role": "assistant", "content": [types.SimpleNamespace(type="tool_use")]})
    convo.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c", "content": "3"}]})
    A._move_cache_checkpoint(convo)
    assert [_breakpoints(m.get("content")) for m in convo] == [0, 0, 0, 0, 1, 0, 1]   # oldest dropped
    assert A.CACHE_CHECKPOINTS == 2 and A.CACHE_CHECKPOINTS + 1 <= 4                  # + system <= the cap


def test_cl1_thinking_blocks_still_ride_the_conversation_wholesale(monkeypatch):
    """The armed thinking lane appends resp.content WHOLESALE (never a text-filtered copy) and this
    change must not become the thing that drops a thinking block: the marker goes on the USER turn's
    last block, so the assistant turn is passed through by reference and untouched."""
    monkeypatch.delenv("GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", raising=False)
    think = types.SimpleNamespace(type="thinking", thinking="weighing two tables")
    client = _SnapClient([_resp([think, _use("t1")]),
                          _resp([_txt("2,462,000 MT.")], "end_turn")])
    A.answer_numbers("corn stocks?", asof="2024-06-01", client=client,
                     query_fn=lambda sql: [{"value": "2462000", "knowledge_date": "2024-01-10"}])
    assistant = [m for m in client.sent[-1]["messages"] if m["role"] == "assistant"]
    assert len(assistant) == 1
    kinds = [getattr(b, "type", None) for b in assistant[0]["content"]]
    assert kinds == ["thinking", "tool_use"], kinds
    assert _breakpoints(assistant[0]["content"]) == 0          # markers never land on an assistant turn


# ── (2) the writer's evidence block ──────────────────────────────────────────────────────────────────
_TOOL = {"name": "emit_answer", "input_schema": {"type": "object"}}


@pytest.fixture(autouse=True)
def _anthropic_lane(monkeypatch):
    """Pin the provider (the site default lives in a gitignored params.yaml) and zero the backoff waits
    so the repair-path pin does not sleep."""
    monkeypatch.setenv("GRAPHRAG_PROVIDER", "anthropic")
    monkeypatch.setattr(pv, "wait_exponential", lambda **kw: tenacity.wait_none())


def _writer_request(monkeypatch, user=("STABLE GRAPH BLOCK", "VOLATILE TAIL + QUESTION")):
    """One _call_opus through a captured serving_call; returns (system_blocks, user_blocks)."""
    seen: list = []

    def fake_serving_call(client, system, user_, **kw):
        seen.append((system, user_))
        return {"tldr": "t", "mechanism": "m"}, None

    monkeypatch.setattr(pv, "serving_call", fake_serving_call)
    monkeypatch.setattr(pv, "make_client", lambda: object())
    an._call_opus("SYS", user, model="claude-opus-5", tool=_TOOL)
    return seen[-1]


def test_cl2_the_writer_request_carries_exactly_one_breakpoint_and_it_is_the_system_block(monkeypatch):
    """The whole of change (2), in one assertion: system marked, evidence plain, order and text
    untouched. The two blocks still ship as two blocks -- nothing is merged or reordered."""
    monkeypatch.setenv("GRAPHRAG_SYNTH_PLAIN_EVIDENCE", "on")                 # the PLAIN arm (opt-in)
    system, user = _writer_request(monkeypatch)
    assert system == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert user == [{"type": "text", "text": "STABLE GRAPH BLOCK"},
                    {"type": "text", "text": "VOLATILE TAIL + QUESTION"}]
    assert _breakpoints(system) == 1 and _breakpoints(user) == 0
    assert _breakpoints(system) + _breakpoints(user) == 1


def test_cl2_the_default_and_off_are_the_head_request_byte_for_byte(monkeypatch):
    """The default pin, and it is a BYTE pin, not a shape pin: json.dumps preserves insertion order,
    so this fails if the restored block ever grows its key in a different position than HEAD's literal
    `{"type": ..., "text": ..., "cache_control": ...}` put it."""
    monkeypatch.setenv("GRAPHRAG_SYNTH_PLAIN_EVIDENCE", "off")
    system, user = _writer_request(monkeypatch)
    head_shape = [{"type": "text", "text": "STABLE GRAPH BLOCK", "cache_control": {"type": "ephemeral"}},
                  {"type": "text", "text": "VOLATILE TAIL + QUESTION"}]
    assert json.dumps(user) == json.dumps(head_shape)
    assert _breakpoints(system) + _breakpoints(user) == 2                     # HEAD's two breakpoints

    monkeypatch.delenv("GRAPHRAG_SYNTH_PLAIN_EVIDENCE", raising=False)      # UNSET = the same HEAD bytes
    _, dflt = _writer_request(monkeypatch)
    assert json.dumps(dflt) == json.dumps(head_shape)
    monkeypatch.setenv("GRAPHRAG_SYNTH_PLAIN_EVIDENCE", "on")
    _, plain = _writer_request(monkeypatch)
    assert [{k: v for k, v in b.items() if k != "cache_control"} for b in user] == plain


def test_cl2_the_default_is_cached_and_the_switch_takes_the_house_words(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_SYNTH_PLAIN_EVIDENCE", raising=False)
    assert an._synth_plain_evidence_on() is False              # DEFAULT = HEAD's marked block (owner 09-06)
    for word in ("off", "OFF", "0", "false", "False", "no", " off "):
        monkeypatch.setenv("GRAPHRAG_SYNTH_PLAIN_EVIDENCE", word)
        assert an._synth_plain_evidence_on() is False, word
    for word in ("on", "1", "true", "yes", "banana"):
        monkeypatch.setenv("GRAPHRAG_SYNTH_PLAIN_EVIDENCE", word)
        assert an._synth_plain_evidence_on() is True, word


def test_cl2_the_string_user_path_is_untouched(monkeypatch):
    """Injected fakes (and route_llm's borrowed haiku call) hand `user` as a plain string -- there is no
    tuple to unpack, no block list to mark, and this change must not invent one."""
    monkeypatch.delenv("GRAPHRAG_SYNTH_PLAIN_EVIDENCE", raising=False)
    system, user = _writer_request(monkeypatch, user="one plain string")
    assert user == "one plain string"
    assert _breakpoints(system) == 1


def test_cl2_the_repair_call_still_works_and_merely_pays_plain_input(monkeypatch):
    """THE CONSUMER THE PREMIUM WAS BOUGHT FOR. providers.serving_call's backoff re-attempt is the
    second writer call that reuses the evidence; it fired 0 of 34 times on 2026-09-04, which is why
    the standing premium is a loss. It must still WORK -- so drive the real serving_call with a
    scripted transient 429 and assert the retry re-sends the identical unmarked blocks and the answer
    comes back. Under the opt-in, unmarked, the retry pays plain input twice instead of 1.25x + 0.1x."""
    monkeypatch.setenv("GRAPHRAG_SYNTH_PLAIN_EVIDENCE", "on")
    req = httpx.Request("POST", "https://fake")
    limited = anthropic.RateLimitError("rate limited", response=httpx.Response(429, request=req),
                                       body=None)
    usage = types.SimpleNamespace(input_tokens=47129, output_tokens=4599,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=10398)
    ok = types.SimpleNamespace(stop_reason="tool_use", usage=usage,
                               content=[types.SimpleNamespace(type="tool_use",
                                                              input={"tldr": "t", "mechanism": "m"})])
    script = [limited, ok]
    seen: list[dict] = []

    class _Client:
        def __init__(self):
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kw):
            seen.append(copy.deepcopy(kw))
            item = script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(pv, "make_client", _Client)
    out = an._call_opus("SYS", ("STABLE GRAPH BLOCK", "VOLATILE TAIL"), model="claude-opus-5",
                        tool=_TOOL)
    assert out["tldr"] == "t"                                     # the repair path served the answer
    assert len(seen) == 2, "the retry did not re-send the request"
    first, second = (kw["messages"][0]["content"] for kw in seen)
    assert first == second, "the repair call did not reuse the same evidence blocks"
    assert _breakpoints(first) == 0 and _breakpoints(second) == 0  # plain on BOTH attempts
    assert [b["text"] for b in second] == ["STABLE GRAPH BLOCK", "VOLATILE TAIL"]
    assert all(_breakpoints(kw["system"]) == 1 for kw in seen)     # the system block keeps its marker
    # the usage tag still rides the pop-channel, so the census that measured this can keep measuring it
    assert out["_usage"]["cache_write"] == 0 and out["_usage"]["cache_read"] == 10398
