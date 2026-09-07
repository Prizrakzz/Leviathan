"""LANE S (SCAN TIER, 2026-09-06): the mode-aware NUMBERS-ROUND budget, and its OFF state.

THE MECHANISM IN ONE LINE. Every turn today -- the FREE Scan notch and the paid Analysis notch alike --
makes 8 Anthropic calls: 1 planner + 6 numbers-agent rounds + 1 writer. With D-CL's moving cache
checkpoint in place the per-round INPUT side is already cheap, so FEWER ROUNDS is the only large lever
left on the free notch. `Mode.numbers_calls` threads an integer into `numbers.agent.answer_numbers`'
already-accepted `max_calls` keyword (Class-1: a value, not a new seam), the agent tells the model how
many rounds it has, and the writer is told when the leg was capped or came back empty.

TWO FLAGS, NOT ONE, and neither implies the other:
  GRAPHRAG_NUMBERS_MODE_BUDGET  the KNOB      -- threads `max_calls`.
  GRAPHRAG_NUMBERS_BUDGET_NOTE  the NARRATION -- the SCOPE NOTE clause, the persona mandate, the trace
                                                stamp. It ALSO requires the mode to carry a budget.

THE ACCEPTANCE BAR, pinned first and hardest, and asserted by CAPTURING kwargs from injected fakes
rather than by reading source: with BOTH flags off nothing moves -- no knob dict grows a key, no
`max_calls` kwarg is sent, the agent's first user turn and system block are byte-identical, the numbers
block and the persona are byte-identical, and `trace.numbers_budget` is ABSENT (never a null column).
With BOTH flags ON, only `quick_n3` moves: `quick`, `standard`, `deep` and `max` carry no
`numbers_calls`, so their numbers leg AND their writer prompt are byte-identical too. P7 is the pin the
whole build exists to protect -- a `deep` turn whose agent honestly reports capped=True must still be
byte-identical, because the consumption gate, not the stamp, is what decides.

P14 (2026-09-07) is THE HEADROOM: the budget line asks for every known lookup in the FIRST round,
so that round is the one that grows, and on the measured arm one row spent the whole 6,000-token
ceiling and stopped on max_tokens with 4 of an intended plan's tool_use blocks -- the refusal fired
and took the entire numbers leg with it (0 lookups, 0 tables read). The ceiling floor therefore
rises to 12,000 for EXACTLY the turns the line renders on, and the refusal is kept: a partial
selection is still never served. The OFF view of that floor lives in P5 beside the prompt's, not in
a second byte-identity test.

All offline: no pg, no S3, no LLM, no AWS. ASCII-only output (the Windows console is cp1252)."""
from __future__ import annotations

import inspect
import types

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import config_check as cc
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import reasoning_modes as rm
from leviathan.graphrag.numbers import agent as na

# THE REAL SIGNATURE, READ AT IMPORT -- before any test's monkeypatch can replace the function. A pin
# that read it inside a test would be reading the injected fake and would pass on an empty stub.
_REAL_SIG = inspect.signature(na.answer_numbers)


# == fixtures =========================================================================================
_ASOF = "2024-06-01"
_Q = "why is corn bid on a drought"


def _graph() -> g.CausalGraph:
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                mechanism="dryness cuts yield")])
    return g.CausalGraph({"corn": corn}, silver=set())


def _reason_call(system, user, *, model, tool, **kw):
    return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}", "text": "note"}]


_CALLS = [{"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                     "period": "2023"},
           "rows": [{"value": "2462000", "unit": "MT", "knowledge_date": "2024-01-10"}],
           "status": "ok"}]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test states its own flag state. An inherited flag would make the OFF pins vacuously green,
    which is the exact failure the D-AM `_clean_env` fixture was written for."""
    for v in ("GRAPHRAG_MODES", "GRAPHRAG_NUMBERS_MODE_BUDGET", "GRAPHRAG_NUMBERS_BUDGET_NOTE",
              "GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", "GRAPHRAG_NUMBERS_THINKING"):
        monkeypatch.delenv(v, raising=False)


def _flags(monkeypatch, *, knob=None, note=None):
    for name, val in (("GRAPHRAG_NUMBERS_MODE_BUDGET", knob), ("GRAPHRAG_NUMBERS_BUDGET_NOTE", note)):
        if val is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, val)


def _hybrid(monkeypatch, *, mode_knobs=None, nums=None, knob=None, note=None, raise_exc=None):
    """Drive `orch.run_hybrid` with THREE injected fakes and capture what each seam received:
    `answer_numbers`' kwargs, `_numbers_block`'s `budget` kwarg and its rendered string, and the
    finished `out` dict. Nothing here is read off the source -- the whole point of the harness.

    `raise_exc` makes the injected `answer_numbers` RAISE (P12): that is the production shape of a
    numbers-lane outage -- `run_hybrid` swallows it into `{"calls": [], "error": ...}` so a broken
    lookup leg can never take the note down with it -- and it is the case the first sitting's
    narration could not see, because a lane that never returns mints no `numbers_budget` stamp."""
    seen: dict = {}
    real_block = orch._numbers_block

    def _fake_numbers(question, asof, **kw):
        seen["numbers_kw"] = dict(kw)
        if raise_exc is not None:
            raise raise_exc
        return dict(nums if nums is not None else {"calls": list(_CALLS)})

    def _spy_block(calls, **kw):
        seen["block_kw"] = dict(kw)
        seen["block"] = real_block(calls, **kw)
        seen["block_plain"] = real_block(calls)          # what HEAD would have rendered for these calls
        return seen["block"]

    def _fake_answer(query, **kw):
        seen["answer_kw"] = dict(kw)
        kw["extra_resolver"]()
        return {"answer": "a", "trace": {}, "citations": [], "evidence": [], "structured": None,
                "contract": None, "contracts": [], "model": "m"}

    monkeypatch.setattr(na, "answer_numbers", _fake_numbers)
    monkeypatch.setattr(orch, "_numbers_block", _spy_block)
    monkeypatch.setattr(an, "answer", _fake_answer)
    _flags(monkeypatch, knob=knob, note=note)
    kw = {"mode_knobs": mode_knobs} if mode_knobs else {}
    seen["out"] = orch.run_hybrid(_Q, _ASOF, graph=_graph(), **kw)
    return seen


# -- the agent-loop harness (the test_numbers_agent house style, verbatim in shape) --------------------
def _tool_use(inp, tid="t1"):
    return types.SimpleNamespace(type="tool_use", name=na.TOOL_NAME, input=inp, id=tid)


def _text(t):
    return types.SimpleNamespace(type="text", text=t)


def _resp(content, stop):
    return types.SimpleNamespace(content=content, stop_reason=stop)


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


_PSD_USE = {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
            "period": "2023"}
_PSD_ROWS = [{"value": "2462000", "knowledge_date": "2024-01-10"}]


# == P1 -- the knob table is UNCHANGED for every name that exists at HEAD ==============================
def test_p1_every_head_preset_knob_dict_is_unchanged():
    """`knobs()` filters `is not None`, so a field that is None on a preset cannot appear in its dict.
    quick's and deep's dicts are TRANSCRIBED (the test_v1_knob_table discipline: if a later wave retunes
    one, the change is visible in review); every other name is asserted structurally."""
    assert rm.knobs(rm.QUICK) == {
        "depth": 1, "max_seeds": 2,
        "k_by_depth": (4, 2), "evidence_cap": 12, "probe_cap": 12,
        "fetch_k": 40, "silver_cap": 4,
        "scaffold_max_bullets": 6, "scaffold_max_absence": 3,
        "budget_scale": 0.7, "xc_force": False,
        "per_seed_budget": 12}
    assert rm.knobs(rm.DEEP) == {
        "depth": 1, "max_seeds": 4,
        "k_by_depth": (7, 5), "evidence_cap": 48, "probe_cap": 36,
        "fetch_k": 60, "silver_cap": 12,
        "scaffold_max_bullets": 12, "scaffold_max_absence": 6,
        "per_seed_budget": 32}
    assert rm.knobs(rm.STANDARD) == {}                            # the all-None passthrough, still empty
    for name in rm.MODES:
        if name == rm.QUICK_N3:
            continue
        assert "numbers_calls" not in rm.knobs(name), name
        assert rm.MODES[name].numbers_calls is None, name
    assert rm.knobs(rm.QUICK_N3)["numbers_calls"] == 3


# == P2 -- the leak fence and the one-variable law =====================================================
def test_p2_quick_n3_is_dark_and_differs_from_quick_in_exactly_one_field():
    assert rm.QUICK_N3 in rm.DARK_NAMES
    assert rm.serving_names() == frozenset({"quick", "standard", "deep"})
    assert rm.QUICK_N3 in rm.valid_names()                        # resolvable BY NAME (the arm reaches it)
    differ = {f for f in ("name",) + tuple(rm.KNOB_FIELDS)
              if getattr(rm.MODES[rm.QUICK], f) != getattr(rm.MODES[rm.QUICK_N3], f)}
    assert differ == {"name", "numbers_calls"}
    assert rm.KNOB_FIELDS[-1] == "numbers_calls"                  # appended-last, SEVENTH application
    assert cc.check_scan_tier() == []                             # the governing lint agrees, in-process


# == P3 -- FLAGS OFF: no max_calls kwarg reaches the agent, on ANY preset ==============================
def test_p3_both_flags_off_the_kwarg_is_absent_on_every_preset(monkeypatch):
    """The omit-when-absent idiom, proven by capture rather than by reading the call site: with the
    kwarg missing, `max_calls` is 6 by signature default and an injected `answer_numbers` fake carrying
    the pre-LANE-S signature stays valid. quick_n3 is included ON PURPOSE -- the preset alone must move
    nothing; the KNOB FLAG is the second half of the decision."""
    for name in (rm.QUICK, rm.DEEP, rm.QUICK_N3):
        seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(name))
        assert "max_calls" not in seen["numbers_kw"], name
    assert _REAL_SIG.parameters["max_calls"].default == 6


# == P4 -- KNOB FLAG ON: only the preset that carries a budget threads one =============================
def test_p4_the_knob_flag_threads_only_the_preset_that_carries_a_budget(monkeypatch):
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), knob="on")
    assert seen["numbers_kw"]["max_calls"] == 3
    for name in (rm.QUICK, rm.DEEP, rm.MAX, rm.STANDARD):
        s = _hybrid(monkeypatch, mode_knobs=rm.knobs(name), knob="on")
        assert "max_calls" not in s["numbers_kw"], name
    for off in ("", "off", "0", "false", "OFF", "yes"):           # fail-closed: only 'on' enables
        s = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), knob=off)
        assert "max_calls" not in s["numbers_kw"], off


# == P5 -- the agent's PROMPT: the system block is untouched, the user turn moves only when narrowed ===
def test_p5_the_budget_line_is_empty_unless_the_turn_is_actually_narrowed():
    assert na._budget_line(None) == ""
    assert na._budget_line(0) == ""
    assert na._budget_line(na._DEFAULT_MAX_CALLS) == ""            # == 6, the signature default
    assert na._budget_line(7) == ""                               # a WIDER budget narrows nothing
    assert na._DEFAULT_MAX_CALLS == _REAL_SIG.parameters["max_calls"].default
    line = na._budget_line(3)
    assert line.startswith("\nLOOKUP ROUNDS: this turn has 3 rounds")
    assert "the first 2 rounds" in line                            # TRUE AT THE BOUNDARY: N-1 are read


def test_p5_system_block_is_byte_identical_and_only_the_user_turn_and_the_ceiling_move():
    """The system block is where the 98,174-token cache write lives, so the line may not go there --
    THE BANK IS THE CROSS-RUN COMPARISON, not a frozen literal: a banked string would go red the day
    the numbers registry legitimately grows a card, and would then be pinning the registry rather than
    this lane. Both runs' system blocks are compared to each other AND to `system_prompt` directly.

    EXTENDED 2026-09-07 (the headroom sitting) TO THE WHOLE create(), which is where the OFF view of
    LANE S now has to be taken: the narrowed turn moves a SECOND field, `max_tokens`. This test is the
    one off-view pin for both -- the un-narrowed create is HEAD's in every key (ceiling 1,500, no
    thinking, no output_config), and P3/P4 above already prove no preset threads a budget with the
    flags off, so this ONE call is every preset's call and no second byte-identity test is owed.
    The narrowed run then differs in EXACTLY {messages, max_tokens} and nothing else."""
    def _run(**kw):
        c = _FakeClient([_resp([_text("done")], "end_turn")])
        na.answer_numbers("corn stocks?", asof=_ASOF, client=c, query_fn=lambda sql: [], **kw)
        return c.sent[0]

    plain, narrowed = _run(), _run(max_calls=3)
    reg = na.load_registry()
    assert plain["system"] == narrowed["system"]
    assert plain["system"][0]["text"] == na.system_prompt(reg, stats_tool=na._stats_tool_on())
    assert "LOOKUP ROUNDS" not in na.system_prompt(reg, stats_tool=True)
    assert "LOOKUP ROUNDS" not in na.system_prompt(reg, stats_tool=False)
    # the FIRST user turn: byte-identical to what HEAD built when no budget is threaded...
    assert plain["messages"][0] == {"role": "user",
                                    "content": f"As-of date (fixed): {_ASOF}\n\nQuestion: corn stocks?"}
    # ...and the narrowed turn differs by exactly the one line, in the slot between as-of and QUESTION.
    assert narrowed["messages"][0]["content"] == (f"As-of date (fixed): {_ASOF}"
                                                  + na._budget_line(3)
                                                  + "\n\nQuestion: corn stocks?")
    assert narrowed["messages"][0]["content"].endswith("\n\nQuestion: corn stocks?")   # recency slot kept
    # THE OFF VIEW, on the wire: HEAD's kwargs exactly -- no key invented, ceiling still 1,500.
    assert set(plain) == {"model", "max_tokens", "system", "tools", "messages"}
    assert plain["max_tokens"] == 1500
    # ...and the narrowed turn moves the user turn and the CEILING, and nothing else at all.
    assert set(narrowed) == set(plain)   # no key invented on the narrowed create either (mutation N5)
    assert {k for k in plain if plain[k] != narrowed[k]} == {"messages", "max_tokens"}
    assert narrowed["max_tokens"] == na._NARROWED_MAX_TOKENS


# == P6 -- the numbers block: the FACT half ===========================================================
def test_p6_numbers_block_is_byte_identical_without_a_budget():
    """DEFAULT NONE is the whole compatibility story for the seven sibling decks that call this
    function directly -- two of which assert `"SCOPE NOTE" not in _numbers_block([plain])`."""
    assert orch._numbers_block(_CALLS) == orch._numbers_block(_CALLS, budget=None)
    assert "SCOPE NOTE" not in orch._numbers_block(_CALLS)
    assert an.NUMBERS_BUDGET_MARK not in orch._numbers_block(_CALLS, budget=None)


def test_p6_the_capped_clause_is_exactly_one_new_scope_note():
    plain = orch._numbers_block(_CALLS)
    capped = orch._numbers_block(_CALLS, budget={"max_calls": 3, "rounds_used": 3, "lookups": 1,
                                                 "capped": True})
    assert capped.startswith(plain)                               # a pure append, nothing rewritten
    assert capped.count("SCOPE NOTE") == 1 and plain.count("SCOPE NOTE") == 0
    assert capped.count(an.NUMBERS_BUDGET_MARK) == 1
    # ...and an UNcapped, non-empty turn adds nothing at all.
    uncapped = orch._numbers_block(_CALLS, budget={"max_calls": 3, "rounds_used": 2, "lookups": 1,
                                                   "capped": False})
    assert uncapped == plain


def test_p6_the_empty_leg_clause_reads_the_call_list_and_not_the_stamp():
    """DECIDED FROM `calls`, the same list rendered into the block three lines up, so the note and the
    rendered block can never disagree about whether anything was retrieved -- a stamp saying `lookups:
    4` on a turn whose calls all errored would otherwise mint a note contradicting `(none retrieved)`."""
    lying = {"max_calls": 3, "rounds_used": 3, "lookups": 4, "capped": True}
    empty = orch._numbers_block([], budget=lying)
    assert "(none retrieved)" in empty
    assert empty.count(an.NUMBERS_BUDGET_MARK) == 1
    assert "no figures at all" in empty                            # the EMPTY-LEG wording, not the cap one
    assert "round limit" not in empty                              # exactly one clause, never both
    full = orch._numbers_block(_CALLS, budget=lying)
    assert "no figures at all" not in full and "round limit" in full


# == P7 -- THE BLAST-RADIUS PIN (the fatal this build exists to close) ================================
@pytest.mark.parametrize("name", ["deep", "quick"])
def test_p7_both_flags_on_a_paid_or_free_tier_turn_is_byte_identical(monkeypatch, name):
    """The agent stamps `numbers_budget` UNCONDITIONALLY -- it is a fact about the loop, and gating it
    there would put the decision in two places. CONSUMPTION is gated here, on the NOTE flag AND
    `bool(_nc)`. So a `deep` turn whose agent honestly reports capped=True must move NOTHING: no budget
    reaches `_numbers_block`, the block is byte-identical, the persona gate declines, and the trace
    grows no key. If this test ever goes red, every existing golden under data/consequence_leg/ has
    moved with it."""
    stamp = {"max_calls": 6, "rounds_used": 6, "lookups": 9, "capped": True}
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(name), knob="on", note="on",
                   nums={"calls": list(_CALLS), "numbers_budget": stamp})
    assert "max_calls" not in seen["numbers_kw"]                  # the KNOB half: no budget was threaded
    assert seen["block_kw"] == {"budget": None}                   # the FACT half: nothing to narrate
    assert seen["block"] == seen["block_plain"]                   # byte-identical to HEAD's render
    assert an.NUMBERS_BUDGET_MARK not in seen["block"]
    assert an._numbers_budget_note_on(seen["block"]) is False     # ...so the persona gate declines
    assert "numbers_budget" not in (seen["out"].get("trace") or {})


# == P8 -- the persona: DEFAULT FALSE, marker-gated, and BOTH synthesis bodies ========================
def test_p8_system_is_byte_identical_with_numbers_budget_defaulted():
    base = an._system()
    assert an._system(numbers_budget=False) == base
    assert an._SYSTEM_NUMBERS_BUDGET_MANDATE not in base
    assert an._system(numbers_budget=True) == base + an._SYSTEM_NUMBERS_BUDGET_MANDATE
    assert inspect.signature(an._system).parameters["numbers_budget"].default is False


def test_p8_the_gate_needs_the_flag_AND_the_marker(monkeypatch):
    vp_with = "SILVER NUMBERS ...\nSCOPE NOTE (...): " + an.NUMBERS_BUDGET_MARK + " partial read."
    vp_without = "SILVER NUMBERS ...\n- [N1] silver_psd.ending_stocks_mt = 2462000"
    _flags(monkeypatch, note=None)
    assert an._numbers_budget_note_on(vp_with) is False            # flag off -> never
    _flags(monkeypatch, note="on")
    assert an._numbers_budget_note_on(vp_with) is True
    assert an._numbers_budget_note_on(vp_without) is False         # no marker -> no demand
    assert an._numbers_budget_note_on(None) is False
    for off in ("off", "", "1", "true", "yes"):                    # fail-closed: only 'on'
        _flags(monkeypatch, note=off)
        assert an._numbers_budget_note_on(vp_with) is False, off


def test_p8_both_synthesis_bodies_thread_the_gate(monkeypatch):
    """THE BOTH-BODIES LAW: a knob that shapes every L2 turn but vanishes on the documented
    `GRAPHRAG_PLANNER=onehop` rollback lane is the null-arm class, on exactly the path a rollback puts
    every turn on. Asserted by CAPTURING the `_system` kwargs each body actually passed."""
    seen: list = []
    real = an._system

    def _spy(**kw):
        seen.append(dict(kw))
        return real(**kw)

    monkeypatch.setattr(an, "_system", _spy)
    _flags(monkeypatch, note="on")
    marked = an.NUMBERS_BUDGET_MARK + " this turn's lookup leg reached the round limit."
    for planner in ("l2", "onehop"):
        for ctx, want in ((marked, True), ("plain context, no marker", False)):
            seen.clear()
            an.answer(_Q, graph=_graph(), asof=_ASOF, planner=planner, call=_reason_call,
                      retrieve=_retrieve, route_fn=lambda q, gg: ["corn"], extra_context=ctx)
            assert seen, (planner, want)
            assert seen[-1]["numbers_budget"] is want, (planner, want)


# == P9 -- THE EXEMPT LANE, restated here so it cannot be lost if test_dam_modes is edited ============
def test_p9_run_numbers_only_takes_no_budget_and_sends_no_max_calls(monkeypatch):
    """On this lane the agent's PROSE IS THE ANSWER, so a budget-exhausted turn serves the sentinel
    "(stopped: max tool calls reached)" plus a `## Sources` footer to a READER. Narrowing it would turn
    a rare sentinel-as-answer defect into a frequent one."""
    assert "mode_knobs" not in inspect.signature(orch.run_numbers_only).parameters
    assert "max_calls" not in inspect.signature(orch.run_numbers_only).parameters
    seen: dict = {}

    def _fake_numbers(question, asof, **kw):
        seen.update(kw)
        return {"answer": "text", "calls": list(_CALLS), "numbers_budget": {"capped": True}}

    monkeypatch.setattr(na, "answer_numbers", _fake_numbers)
    _flags(monkeypatch, knob="on", note="on")
    out = orch.run_numbers_only(_Q, _ASOF)
    assert "max_calls" not in seen
    assert "numbers_budget" not in out["trace"]                    # its own explicit whitelist, untouched


# == P10 -- the agent stamps the record on ALL THREE turn-ending returns ==============================
def test_p10_capped_true_on_the_budget_exhausted_return():
    """Three rounds handed in, three tool_use responses queued: the loop executes round 3's calls and
    then falls out. `rounds_used == max_calls` and `capped` is True -- the only return that says so."""
    c = _FakeClient([_resp([_tool_use(_PSD_USE, f"t{i}")], "tool_use") for i in range(3)])
    out = na.answer_numbers("corn stocks?", asof=_ASOF, client=c, query_fn=lambda sql: list(_PSD_ROWS),
                            max_calls=3)
    assert out["answer"] == "(stopped: max tool calls reached)"
    assert out["numbers_budget"] == {"max_calls": 3, "rounds_used": 3, "lookups": 3, "capped": True,
                                     "max_tokens": 12000}


def test_p10_capped_false_on_the_natural_text_return():
    c = _FakeClient([_resp([_tool_use(_PSD_USE)], "tool_use"),
                     _resp([_text("Corn ending stocks were 2,462,000 MT.")], "end_turn")])
    out = na.answer_numbers("corn stocks?", asof=_ASOF, client=c, query_fn=lambda sql: list(_PSD_ROWS),
                            max_calls=3)
    assert out["numbers_budget"] == {"max_calls": 3, "rounds_used": 2, "lookups": 1, "capped": False,
                                     "max_tokens": 12000}
    # a turn that answers in ONE round records 1, whatever budget it was handed -- the counter reports
    # what the loop DID, never what it was allowed to do.
    c2 = _FakeClient([_resp([_text("No lookup needed.")], "end_turn")])
    out2 = na.answer_numbers("corn stocks?", asof=_ASOF, client=c2, query_fn=lambda sql: [], max_calls=3)
    assert out2["numbers_budget"] == {"max_calls": 3, "rounds_used": 1, "lookups": 0, "capped": False,
                                      "max_tokens": 12000}


def test_p10_the_esr_aggregate_early_return_carries_the_POST_APPEND_lookups():
    """THE REASON `lookups` IS RE-TAKEN AT EACH RETURN. The ESR-destination-generic path appends its
    aggregate legs to `calls` and then leaves immediately -- the one path that grows the list and does
    not come back -- so a count taken when `result` was built would under-report by exactly the
    deterministic legs the engine injected. Measured here: 1 model lookup + 2 aggregate legs."""
    def _qfn(sql):
        if "sum(value)" in sql:
            return [{"value": "40000"}] if "market_year = 2026" in sql else [{"value": "35000"}]
        return [{"value": "1234.5", "knowledge_date": "20260514", "data_date": "2026-05-07"}]

    esr = _tool_use({"table": "silver_esr", "metric": "gross_new_sales_1000mt",
                     "commodity": "soybean_cbot", "period": "2025", "agg": "latest"})
    out = na.answer_numbers("Give me the destination breakdown of US soybean export sales this year",
                            asof="2026-05-20",
                            client=_FakeClient([_resp([esr], "tool_use"),
                                                _resp([_text("I can't break this out.")], "end_turn")]),
                            query_fn=_qfn, max_calls=3)
    assert out["esr_aggregate_legs"] == 2 and len(out["calls"]) == 3
    assert out["numbers_budget"] == {"max_calls": 3, "rounds_used": 2, "lookups": 3, "capped": False,
                                     "max_tokens": 12000}


# == P11 -- THE TRACE PIN =============================================================================
def test_p11_trace_carries_the_stamp_only_when_both_gates_pass(monkeypatch):
    """ONE WRITE (`holder["numbers_budget"]`, gated on the note flag AND `bool(_nc)`) and ONE GUARDED
    STAMP, modelled on the `ms_numbers` stamp beside it. The key rides NEITHER `_sk` copy tuple: the
    first of those is a bare, unguarded `holder[_sk] = nums.get(_sk)` over a fixed tuple, so adding the
    key there would copy the agent's UNCONDITIONAL stamp onto every hybrid turn and defeat the gate."""
    stamp = {"max_calls": 3, "rounds_used": 3, "lookups": 2, "capped": True}
    nums = {"calls": list(_CALLS), "numbers_budget": stamp}
    off = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), nums=nums)
    assert "numbers_budget" not in (off["out"].get("trace") or {})
    knob_only = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), nums=nums, knob="on")
    assert "numbers_budget" not in (knob_only["out"].get("trace") or {})    # the knob does not narrate
    note_only = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), nums=nums, note="on")
    assert "numbers_budget" not in (note_only["out"].get("trace") or {})    # ...nor does the note alone
    both = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), nums=nums, knob="on", note="on")
    assert both["out"]["trace"]["numbers_budget"] == stamp
    assert both["block_kw"] == {"budget": stamp}
    assert an.NUMBERS_BUDGET_MARK in both["block"]
    assert an._numbers_budget_note_on(both["block"]) is True               # ...and the persona follows


def test_p11_the_eval_row_carries_an_ABSENT_column_not_a_null_one():
    """The per-answer projection is a dict LITERAL of always-present keys, so a plain entry would emit
    `numbers_budget: null` on every row of every artifact with the flags off. The conditional splat is
    what gives an explicit column the absent-when-off shape a registered tracekey gets for free."""
    from leviathan.graphrag import eval as evl
    stamp = {"max_calls": 3, "rounds_used": 3, "lookups": 2, "capped": True}
    bare = evl._per_answer_record({"q": {"id": "x"}, "out": {"trace": {}}}, "single")
    assert "numbers_budget" not in bare
    with_it = evl._per_answer_record({"q": {"id": "x"}, "out": {"trace": {"numbers_budget": stamp}}},
                                     "single")
    assert with_it["numbers_budget"] == stamp
    # the run-header arm stamp: None on every preset that carries no budget (an older deck parses
    # unchanged -- the additive-only law), the integer on the arm that does, and it never raises.
    assert evl._numbers_calls_arm(rm.QUICK_N3) == 3
    for name in (None, "quick", "deep", "max", "standard", "no_such_mode"):
        assert evl._numbers_calls_arm(name) is None, name


# == P12 -- THE OUTAGE HALF OF THE ABSENCE DOCKET (review fix, 2026-09-07) ============================
# THE DEFECT THIS DECK EXISTS FOR, measured at mode=quick_n3 with BOTH flags on before the fix: the
# docket says a turn whose numbers leg returned NOTHING must say so in the writer's own words, and the
# empty clause in `_numbers_block` is that sentence -- but it fires only when a budget RECORD arrives,
# and the sole mint of that record was `answer_numbers`' own turn-ending return. The two ways the leg
# most literally returns nothing therefore reached the writer silently: the swallowed lane exception,
# and the 300 s join failure. Both delivered "(none retrieved)" with no marker, no persona mandate and
# no trace stamp -- an outage presented as an ordinary thin read, on the exact tier the docket names.
_OUTAGE_KEYS = {"max_calls", "lookups", "returned", "lane_error"}


def test_p12_a_raising_numbers_lane_narrates_its_own_absence(monkeypatch):
    """CASE B of the review probe, and the one the fix closes: `answer_numbers` RAISES. `run_hybrid`
    swallows it (`nums = {"calls": [], "error": ...}`), so nothing downstream can tell an outage from
    a reasoning turn -- except this record."""
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), knob="on", note="on",
                   raise_exc=RuntimeError("athena boom"))
    bud = seen["block_kw"]["budget"]
    assert set(bud) == _OUTAGE_KEYS                      # NOT _budget_stamp's shape, and deliberately
    assert bud["returned"] is False and bud["lookups"] == 0 and bud["max_calls"] == 3
    assert "athena boom" in bud["lane_error"]            # WHY it was empty rides the record
    assert "rounds_used" not in bud and "capped" not in bud   # unknowable from the consumer's side
    # ...and the writer is actually told, in the two places the docket names.
    assert "(none retrieved)" in seen["block"]
    assert seen["block"].count(an.NUMBERS_BUDGET_MARK) == 1
    # THE OUTAGE'S OWN SENTENCE (2026-09-07), not the empty leg's and not the cap's. The record that
    # says `returned: False` and the clause the writer reads must agree about which absence this was.
    assert "was unavailable" in seen["block"]
    assert "no figures at all" not in seen["block"] and "round limit" not in seen["block"]
    assert an._numbers_budget_note_on(seen["block"]) is True    # the persona mandate is now reachable
    assert seen["out"]["trace"]["numbers_budget"] == bud


def test_p12_a_lane_that_returns_no_result_at_all_narrates_it_too(monkeypatch):
    """The 300 s join failure's shape (`nums = {}`), reached here by a fake that returns an empty
    dict: no calls, no error, no stamp. The default `lane_error` says exactly that and invents
    nothing about rounds."""
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), knob="on", note="on", nums={})
    bud = seen["block_kw"]["budget"]
    assert bud == {"max_calls": 3, "lookups": 0, "returned": False,
                   "lane_error": "the numbers lane returned no result"}
    assert an._numbers_budget_note_on(seen["block"]) is True
    assert seen["out"]["trace"]["numbers_budget"]["returned"] is False
    # the join failure and the raised exception are ONE state and get ONE sentence
    assert "was unavailable" in seen["block"] and "no figures at all" not in seen["block"]


@pytest.mark.parametrize("knob,note", [(None, None), ("on", None), (None, "on")])
def test_p12_the_outage_record_needs_BOTH_gates_exactly_like_the_stamp(monkeypatch, knob, note):
    """The fix widens WHAT can be narrated, never WHEN. A raising lane with either flag missing is
    byte-identical to HEAD: no budget, no marker, no trace column."""
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), knob=knob, note=note,
                   raise_exc=RuntimeError("athena boom"))
    assert seen["block_kw"] == {"budget": None}
    assert seen["block"] == seen["block_plain"]
    assert an.NUMBERS_BUDGET_MARK not in seen["block"]
    assert "numbers_budget" not in (seen["out"].get("trace") or {})


@pytest.mark.parametrize("name", ["deep", "quick", "standard", "max"])
def test_p12_an_outage_on_a_tier_with_no_budget_is_still_byte_identical(monkeypatch, name):
    """P7's blast-radius law, restated for the outage path: a numbers lane can fail on ANY tier, and
    on a tier carrying no `numbers_calls` that failure must still move nothing with both flags on.
    `bool(_nc)` is the fence, and the fix conjoins it."""
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(name), knob="on", note="on",
                   raise_exc=RuntimeError("athena boom"))
    assert seen["block_kw"] == {"budget": None}
    assert seen["block"] == seen["block_plain"] == orch._numbers_block([])
    assert an._numbers_budget_note_on(seen["block"]) is False
    assert "numbers_budget" not in (seen["out"].get("trace") or {})


def test_p12_a_lane_that_returned_FIGURES_is_never_given_an_outage_record(monkeypatch):
    """THE THIRD FENCE. The synthesis requires `not calls` as well as a missing stamp, so a leg that
    came back with rows but minted no record (an older injected fake, a future return path) is left
    alone rather than described as having returned nothing -- the record would say `lookups: 0` over a
    block that renders one."""
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), knob="on", note="on",
                   nums={"calls": list(_CALLS)})
    assert seen["block_kw"] == {"budget": None}
    assert seen["block"] == seen["block_plain"]
    assert "numbers_budget" not in (seen["out"].get("trace") or {})


def test_p12_the_agents_own_empty_return_still_wins_over_the_synthesised_one(monkeypatch):
    """THE SECOND FENCE, and the precedence that matters: when the agent DID return -- case A of the
    review probe, a leg that ran and found nothing -- its own stamp is what rides, rounds and all. The
    synthesised record is for the lane that never got to speak, never a replacement for one that did."""
    stamp = {"max_calls": 3, "rounds_used": 2, "lookups": 0, "capped": False}
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_N3), knob="on", note="on",
                   nums={"calls": [], "numbers_budget": stamp})
    assert seen["block_kw"] == {"budget": stamp}                  # the agent's shape, untouched
    assert "returned" not in seen["out"]["trace"]["numbers_budget"]
    assert "no figures at all" in seen["block"]                   # ...and the same sentence is served
    # ...THE SAME sentence, i.e. the one about the RECORD: a leg that ran and found nothing is not an
    # outage, and the 2026-09-07 split must not have quietly moved this state onto the outage clause.
    assert "the record produced no number for this question" in seen["block"]
    assert "was unavailable" not in seen["block"]


def test_p12_the_eval_row_carries_the_outage_record_verbatim():
    """The trace column is a splat of whatever the trace holds, so the outage shape has to survive it
    unchanged -- an eval reader must be able to tell a 3-round read that found nothing from a lane
    that never ran, and `returned` is the only field that says which."""
    from leviathan.graphrag import eval as evl
    rec = {"max_calls": 3, "lookups": 0, "returned": False, "lane_error": "athena boom"}
    row = evl._per_answer_record({"q": {"id": "x"}, "out": {"trace": {"numbers_budget": rec}}},
                                 "single")
    assert row["numbers_budget"] == rec


# == P13 -- ONE CLAUSE PER STATE: the outage sentence is NOT the empty sentence =======================
# THE VERIFY MAJOR (2026-09-07), and it is the artifact-lies class moved from the trace into the
# ANSWER. The first outage fix gave the lane its own record -- `returned: False`, `lane_error` -- and
# then handed it to the ONE clause that could not tell the two absences apart: "Say plainly that THE
# RECORD PRODUCED NO NUMBER for this question." That sentence is TRUE of a leg that asked the record
# and got nothing back. It is FALSE of a leg that never got to ask: the reader is told the record is
# empty when the truth is that the lookup could not be completed. Newly reachable the moment the
# synthesis landed -- before it, an outage rendered no clause at all -- so the pin belongs beside it.
# THE SPLIT IS ON `returned`, the one field only `run_hybrid._resolve` mints: `agent._budget_stamp`
# returns exactly {max_calls, rounds_used, lookups, capped}, so every agent record still takes the
# empty branch it has always taken. THREE clauses now, still mutually exclusive, still at most one.
_OUTAGE = {"max_calls": 3, "lookups": 0, "returned": False, "lane_error": "athena boom"}
_EMPTY_STAMP = {"max_calls": 3, "rounds_used": 2, "lookups": 0, "capped": False}
_CAPPED_STAMP = {"max_calls": 3, "rounds_used": 3, "lookups": 1, "capped": True}


def test_p13_the_three_clauses_are_three_different_strings():
    """The whole finding in one assertion: an OUTAGE, an EMPTY read and a CAPPED read must reach the
    writer as three distinct sentences. Two of them sharing a string is what put a false claim about
    the record into an outage turn's answer."""
    out = orch._numbers_block([], budget=_OUTAGE)
    emp = orch._numbers_block([], budget=_EMPTY_STAMP)
    cap = orch._numbers_block(_CALLS, budget=_CAPPED_STAMP)
    assert out != emp and out != cap and emp != cap
    # ...and each is a PURE APPEND to the block HEAD would have rendered for the same calls
    assert out.startswith(orch._numbers_block([]))
    assert emp.startswith(orch._numbers_block([]))
    assert cap.startswith(orch._numbers_block(_CALLS))
    for blk in (out, emp, cap):                       # exactly one clause, exactly one marker
        assert blk.count(an.NUMBERS_BUDGET_MARK) == 1 and blk.count("SCOPE NOTE") == 1


def test_p13_the_outage_clause_makes_no_claim_about_what_the_record_carries():
    """THE SENTENCE THE FIX EXISTS FOR. The outage clause states what the CONSUMER'S SIDE knows -- the
    leg was unavailable, nothing came back -- and hands the reader the honest consequence, that what
    the record holds here is unknown from this answer. It borrows neither sibling's wording."""
    out = orch._numbers_block([], budget=_OUTAGE)
    assert "the record produced no number" not in out      # the empty leg's claim, and it is false here
    assert "no figures at all" not in out                  # the empty leg's wording
    assert "round limit" not in out                        # the cap's wording
    assert "was unavailable" in out and "could not be completed" in out
    assert "unknown here" in out                           # the honest consequence, stated positively
    for idiom in ("do not", "don't", "never", "avoid", "must not", "refrain"):
        assert idiom not in out.lower(), idiom             # J6: the clause names no forbidden phrase


def test_p13_the_empty_and_capped_clauses_keep_their_meaning():
    """The split WIDENS the vocabulary and changes neither existing sentence. Pinned to the shipped
    words so a future edit to the outage branch cannot quietly reword its neighbours."""
    emp = orch._numbers_block([], budget=_EMPTY_STAMP)
    cap = orch._numbers_block(_CALLS, budget=_CAPPED_STAMP)
    assert "returned no figures at all" in emp
    assert "the record produced no number for this question" in emp
    assert "reached the round limit set for this tier" in cap
    assert "PARTIAL read of the record" in cap
    for blk in (emp, cap):
        assert "was unavailable" not in blk                # neither one claims an outage


def test_p13_returned_is_the_discriminator_and_only_this_seam_mints_it():
    """`_budget_stamp` is the agent's ONE producer and its four turn-ending returns carry exactly the
    five keys below -- so `budget.get("returned") is None` on every agent record and the empty branch
    is unreachable-by-accident from the agent's side. A record that carried a TRUTHY `returned` (no
    such producer exists; the pin says the branch is `is False`, not truthiness) takes the empty
    branch. `max_tokens` (P14, the headroom) joined the shape and changes NONE of that: it is a fact
    about the ceiling, no clause reads it, and the two shapes still share only `max_calls`/`lookups`."""
    stamp = na._budget_stamp(3, 2, [], capped=False, max_tokens=12000)
    assert set(stamp) == {"max_calls", "rounds_used", "lookups", "capped", "max_tokens"}
    assert stamp.get("returned") is None
    assert orch._numbers_block([], budget=stamp) == orch._numbers_block([], budget=_EMPTY_STAMP)
    truthy = dict(_EMPTY_STAMP, returned=True)
    assert orch._numbers_block([], budget=truthy) == orch._numbers_block([], budget=_EMPTY_STAMP)
    assert set(_OUTAGE) & set(stamp) == {"max_calls", "lookups"}   # the two shapes share only facts


def test_p13_nothing_came_back_is_read_off_calls_for_the_outage_clause_too():
    """THE EMPTY CLAUSE'S OWN LAW, EXTENDED TO ITS NEW SIBLING. The outage sentence asserts that
    nothing came back, so that half is decided from `calls` -- the same list rendered into the block --
    and `returned` chooses only WHICH absence sentence. `run_hybrid._resolve` fences on `not calls` so
    an outage record over a block that renders rows cannot be minted; passed in by hand it takes the
    capped test like any other record and adds nothing, which is exactly HEAD's behaviour."""
    over_rows = orch._numbers_block(_CALLS, budget=dict(_OUTAGE))
    assert over_rows == orch._numbers_block(_CALLS)                # no clause, byte-identical to HEAD
    assert an.NUMBERS_BUDGET_MARK not in over_rows
    # ...and the note can never contradict the body: whenever the outage clause IS served, the block
    # really did render nothing.
    served = orch._numbers_block([], budget=dict(_OUTAGE))
    assert "(none retrieved)" in served and "was unavailable" in served


def test_p13_the_persona_mandate_enumerates_all_three_states():
    """The mandate tells the writer to say WHAT THE NOTE SAYS and then enumerates the states. With
    only two alternatives on a turn whose note states a third, the mandate hands the writer the wrong
    sentence to repeat -- the same falsity, one seam later. It is still J6-clean and still dark."""
    m = an._SYSTEM_NUMBERS_BUDGET_MANDATE
    assert "could not be completed at all" in m            # the OUTAGE state
    assert "stopped at the round limit set for this tier" in m   # the CAPPED state
    assert "came back with no figure" in m                 # the EMPTY state
    for idiom in ("do not", "don't", "never", "avoid", "must not", "refrain"):
        assert idiom not in m.lower(), idiom
    assert an._system() == an._system(numbers_budget=False)       # still default-off
    assert m not in an._system()


@pytest.mark.parametrize("name", sorted(rm.MODES))
def test_p13_every_preset_is_byte_identical_on_every_lane_shape_with_the_flags_unset(monkeypatch, name):
    """THE OFF-STATE BAR, restated over the WHOLE mode table and all four numbers-lane shapes -- rows,
    an agent stamp with no rows, a RAISING lane and a lane that returns nothing at all. With both
    flags unset, every one of the 16 presets must render the block HEAD renders, carry no marker,
    decline the persona gate (so `_system` is the base persona byte-for-byte) and grow no trace key.
    P3/P7/P12 each pin a slice of this; this walks the table, because the outage branch is new code on
    a path every preset can reach -- any numbers lane can fail on any tier."""
    shapes = {"rows": {"calls": list(_CALLS)},
              "stamped_empty": {"calls": [], "numbers_budget": dict(_EMPTY_STAMP)},
              "empty_dict": {}}
    for label, nums in shapes.items():
        seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(name), knob=None, note=None, nums=nums)
        assert seen["block_kw"] == {"budget": None}, (name, label)
        assert seen["block"] == seen["block_plain"], (name, label)
        assert an.NUMBERS_BUDGET_MARK not in seen["block"], (name, label)
        assert an._numbers_budget_note_on(seen["block"]) is False, (name, label)
        assert an._system(numbers_budget=an._numbers_budget_note_on(seen["block"])) == an._system()
        assert "numbers_budget" not in (seen["out"].get("trace") or {}), (name, label)
        assert "max_calls" not in seen["numbers_kw"], (name, label)
    raised = _hybrid(monkeypatch, mode_knobs=rm.knobs(name), knob=None, note=None,
                     raise_exc=RuntimeError("athena boom"))
    assert raised["block_kw"] == {"budget": None}, name
    assert raised["block"] == raised["block_plain"] == orch._numbers_block([]), name
    assert an.NUMBERS_BUDGET_MARK not in raised["block"], name
    assert "numbers_budget" not in (raised["out"].get("trace") or {}), name


@pytest.mark.parametrize("name", sorted(set(rm.MODES) - {rm.QUICK_N3}))
def test_p13_every_budgetless_preset_is_byte_identical_with_BOTH_flags_on(monkeypatch, name):
    """...and the same walk with BOTH flags ON. `quick_n3` is the only preset carrying
    `numbers_calls`, so `bool(_nc)` must hold every other name -- including on the RAISING shape,
    which is the branch this sitting touched."""
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(name), knob="on", note="on",
                   raise_exc=RuntimeError("athena boom"))
    assert seen["block_kw"] == {"budget": None}, name
    assert seen["block"] == seen["block_plain"] == orch._numbers_block([]), name
    assert an._numbers_budget_note_on(seen["block"]) is False, name
    assert "numbers_budget" not in (seen["out"].get("trace") or {}), name
    assert rm.MODES[name].numbers_calls is None, name        # ...and WHY: the preset carries no budget


# == P14 -- THE HEADROOM: the ceiling the narrowed PLANNING round gets (2026-09-07) ==================
# THE DEFECT THIS SECTION EXISTS FOR, measured on the Scan rung-1 arm (treatment-N = mode quick_n3 +
# GRAPHRAG_NUMBERS_BUDGET_NOTE=on, numbers seat claude-sonnet-5 with GRAPHRAG_NUMBERS_THINKING=adaptive,
# 2026-09-07 07:00Z, capture scan_arm_treatment-N.json). The budget line asks for every known lookup in
# the FIRST round, so round 1 is the round that grows: four rows' round 1 finished on tool_use at 2,295
# / 3,030 / 3,659 / 4,660 output tokens carrying 10 / 9 / 16 / 10 tool_use blocks -- the largest already
# 78% of the 6,000 ceiling -- and the fifth (rv_palm_rapeoil) spent the FULL 6,000, emitted 4 blocks and
# stopped on max_tokens. The truncation refusal fired exactly as designed and took the whole numbers leg
# with it: {max_calls: 3, lookups: 0, returned: False}, writer answered from evidence alone, 0 tables
# read. The ceiling moves; the refusal does not.
def test_p14_the_ceiling_ladder_has_two_floors_and_the_budget_LINE_is_what_buys_the_top_one():
    """The ONE producer, unit-pinned. `_numbers_max_tokens` reads the LINE, never `max_calls` re-derived,
    so the instruction that fills the round and the room it is given cannot drift apart."""
    assert (na._THINKING_MAX_TOKENS, na._NARROWED_MAX_TOKENS) == (6000, 12000)
    assert na._numbers_max_tokens(1500, thinking=False, budget_line="") == 1500     # HEAD, untouched
    assert na._numbers_max_tokens(1500, thinking=True, budget_line="") == 6000      # the c/d seam floor
    narrowed = na._budget_line(3)
    assert narrowed
    assert na._numbers_max_tokens(1500, thinking=False, budget_line=narrowed) == 12000
    assert na._numbers_max_tokens(1500, thinking=True, budget_line=narrowed) == 12000
    # the line's own EMPTINESS is the gate, so an un-narrowed budget can never buy the headroom
    for n in (None, 0, na._DEFAULT_MAX_CALLS, 7):
        assert na._numbers_max_tokens(1500, thinking=False, budget_line=na._budget_line(n)) == 1500, n
        assert na._numbers_max_tokens(1500, thinking=True, budget_line=na._budget_line(n)) == 6000, n
    # a caller ceiling ALREADY above a floor is never lowered -- max(), never assignment
    assert na._numbers_max_tokens(20000, thinking=True, budget_line=narrowed) == 20000


def test_p14_the_narrowed_create_carries_the_new_floor_on_EVERY_round():
    """PIN (ii), captured off the wire rather than read off the source: the ceiling is decided ONCE
    before the loop, so every round of a narrowed turn -- not only the planning round -- is sent at
    12,000. Thinking is UNSET here on purpose: the floor follows the line, not the thought."""
    c = _FakeClient([_resp([_tool_use(_PSD_USE, f"t{i}")], "tool_use") for i in range(3)])
    na.answer_numbers("corn stocks?", asof=_ASOF, client=c, query_fn=lambda sql: list(_PSD_ROWS),
                      max_calls=3)
    assert len(c.sent) == 3
    assert [k["max_tokens"] for k in c.sent] == [na._NARROWED_MAX_TOKENS] * 3
    assert all("thinking" not in k for k in c.sent)


def test_p14_a_round_that_still_stops_on_max_tokens_still_REFUSES(monkeypatch):
    """PIN (iii). The headroom moves the wall; it does not remove it. A scripted armed-lane round that
    comes back stop_reason=max_tokens raises exactly as it did at HEAD -- a partial selection is never
    served as final (extract.py:557's doctrine) -- and the message names the ceiling the round actually
    ran under, which is what makes the NEXT rung a measurement instead of a guess."""
    monkeypatch.setenv("GRAPHRAG_NUMBERS_THINKING", "adaptive")
    monkeypatch.setenv("GRAPHRAG_NUMBERS_MODEL", "claude-sonnet-5")
    monkeypatch.delenv("GRAPHRAG_PROVIDER", raising=False)
    c = _FakeClient([_resp([_tool_use(_PSD_USE)], "max_tokens")])
    with pytest.raises(RuntimeError, match="TRUNCATED") as exc:
        na.answer_numbers("corn stocks?", asof=_ASOF, client=c, query_fn=lambda sql: [], max_calls=3)
    assert "max_tokens=12000" in str(exc.value)
    assert c.sent[0]["max_tokens"] == 12000 and c.sent[0]["thinking"] == {"type": "adaptive"}
    # ...and the SAME scripted truncation on an UN-narrowed armed turn still refuses at the c/d floor.
    c2 = _FakeClient([_resp([_tool_use(_PSD_USE)], "max_tokens")])
    with pytest.raises(RuntimeError, match="TRUNCATED") as exc2:
        na.answer_numbers("corn stocks?", asof=_ASOF, client=c2, query_fn=lambda sql: [])
    assert "max_tokens=6000" in str(exc2.value)
    assert c2.sent[0]["max_tokens"] == 6000


def test_p14_the_stamp_records_the_CEILING_THE_ROUNDS_RAN_UNDER():
    """PIN (iv), on the record itself. APPENDED LAST -- the additive-only law the trace column and
    eval's per-answer projection both rest on -- and it reports what `_numbers_max_tokens` returned,
    never the caller's argument, so a turn that never earned a floor says 1,500 and says it honestly."""
    c = _FakeClient([_resp([_text("No lookup needed.")], "end_turn")])
    plain = na.answer_numbers("corn stocks?", asof=_ASOF, client=c, query_fn=lambda sql: [])
    assert plain["numbers_budget"] == {"max_calls": 6, "rounds_used": 1, "lookups": 0,
                                       "capped": False, "max_tokens": 1500}
    assert list(plain["numbers_budget"])[-1] == "max_tokens"          # appended, never inserted
    c2 = _FakeClient([_resp([_text("No lookup needed.")], "end_turn")])
    narrowed = na.answer_numbers("corn stocks?", asof=_ASOF, client=c2, query_fn=lambda sql: [],
                                 max_calls=3)
    assert narrowed["numbers_budget"]["max_tokens"] == 12000
    assert c2.sent[0]["max_tokens"] == 12000                          # the stamp and the wire agree


def test_p14_the_budget_line_asks_for_compact_planning_and_forbids_nothing():
    """THE COMPLEMENT, and the half that still works when the ceiling half cannot: the ceiling cannot
    help a thought that grows again, and this clause cannot promise that it will not. POSITIVE wording
    (J6): it says what the round is FOR and names no idiom, so it teaches nothing by prohibition."""
    line = na._budget_line(3)
    assert "spend the round on the calls themselves" in line
    assert "a brief plan followed by all the lookups in the same turn is the shape that fits" in line
    for banned in ("do not", "don't", "never", "avoid", "must not"):
        assert banned not in line.lower(), banned
    assert na._budget_line(na._DEFAULT_MAX_CALLS) == ""               # still "" when not narrowed
