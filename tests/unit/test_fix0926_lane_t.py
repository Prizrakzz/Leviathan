"""THE 09-26 FIX SITTING -- LANE T: THE NUMBERS SEAT'S CEILING IS A RUNG LADDER (T-1) AND A FAILED SEAT IS PRICED (T-2).

MEASURED on the arm-A capture (2026-09-26; the six eval jobs' CloudWatch `[numbers-thinking]` lines, 62 rounds, each
attributed to its turn by elimination against the seventeen healthy traces' own `numbers_usage` rows):
  * three rounds stopped on max_tokens at 6,000 -- tariff TREATMENT round 1 (in 162, out 6,000, cache_read 102,568),
    tariff CONTROL round 2 (in 2, out 6,000, cache_read 102,568, cache_write 16,125; its round 1 finished at 5,327 out),
    palm/rape CONTROL round 1 (in 136, out 6,000, cache_read 102,568);
  * each seat raised the truncation sentinel, `run_hybrid` stamped `numbers_error`, and the seat's spend DIED inside
    the agent's own list: `numbers_usage` None, no `numbers` seat in `turn_cost_by_seat_usd` (D8 / MINOR-4);
  * the two largest rounds that FINISHED were 5,327 (the tariff control's round 1 -- the prompt the treatment truncated
    on) and 5,077 (the palm/rape treatment's round 1 -- the prompt the control truncated on): the need straddles the
    wall on the same prompt from cell to cell.

What this deck pins, through the REAL agent (a scripted client; nothing else stubbed) and, for the priced seats, the
REAL `run_hybrid` (the writer stubbed at `an.answer`, the synthesis-time join driven as the writer seam drives it):
  T-1  `rung_ladder=True` re-runs a truncated ARMED round ONCE, on the SAME messages, at `_next_rung` (6,000 -> 12,000);
       the climbed ceiling holds; a second truncation RAISES with the first truncation's message at its head; the
       ladder's record rides `numbers_budget["rungs"]`, present only when it fired. `rung_ladder=False` (the default,
       and every flag-off turn) is HEAD's raise at the first truncation, byte for byte. The unarmed lane never climbs.
  T-2  `usage_sink` receives each round's usage row under the census gate, BEFORE the sentinel can raise; on a clean
       return `numbers_usage` equals the sink's rows (the orchestrator reads the sink on its exception path only, so
       nothing is double-counted); the three failed arm seats are now priced by the eval's one arithmetic.
REJECTED (named, so no later edit reaches for it): raising `max_tokens` alone (a wall moved is still a wall, and the
adaptive thought bills into it); a retry-until-success loop (unbounded spend); a timeout constant.
"""
from __future__ import annotations

import copy
import inspect
import types

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import eval as ev
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import providers as pv
from leviathan.graphrag.numbers import agent as na

# THE REAL SIGNATURE, read at import -- before any monkeypatch can replace the function.
_REAL_SIG = inspect.signature(na.answer_numbers)

ASOF = "2026-09-25"
TARIFF_Q = ("What has China's tariff on US soybeans done to US export pace and the balance sheet this year, "
            "and what should I watch?")
SEAT = "claude-sonnet-5"
# HEAD's sentinel, to the byte, at the ceiling the arm ran under (numbers/agent.py at 9750ae3e).
HEAD_TRUNC_6000 = ("numbers-thinking turn TRUNCATED at max_tokens=6000 -- refusing to serve a partial selection "
                   "as final (extract.py:557's doctrine)")

# THE ARM'S OWN ROUNDS (CloudWatch, attributed by elimination; see the module docstring).
TARIFF_T_R1 = {"in": 162, "out": 6000, "cache_read": 102568, "cache_write": 0}
TARIFF_C_R1 = {"in": 162, "out": 5327, "cache_read": 102568, "cache_write": 0}
TARIFF_C_R2 = {"in": 2, "out": 6000, "cache_read": 102568, "cache_write": 16125}
PALM_C_R1 = {"in": 136, "out": 6000, "cache_read": 102568, "cache_write": 0}

_PSD_USE = {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "soybeans_cbot", "period": "2025"}


def _usage(u: dict):
    return types.SimpleNamespace(input_tokens=u["in"], output_tokens=u["out"],
                                 cache_read_input_tokens=u["cache_read"],
                                 cache_creation_input_tokens=u["cache_write"])


def _tool_use(tid="t1"):
    return types.SimpleNamespace(type="tool_use", name=na.TOOL_NAME, input=dict(_PSD_USE), id=tid)


def _resp(stop, u, *, tools=0, text=""):
    content = [types.SimpleNamespace(type="thinking", thinking="...")]
    content += [_tool_use("t%d" % i) for i in range(tools)]
    if text:
        content.append(types.SimpleNamespace(type="text", text=text))
    return types.SimpleNamespace(content=content, stop_reason=stop, usage=_usage(u))


class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        # the messages are SNAPSHOTTED at call time: `convo` is mutated in place by later rounds
        self.outer.sent.append(dict(kw, messages=copy.deepcopy(kw["messages"])))
        return self.outer.queue.pop(0)


class _FakeClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.sent = []
        self.messages = _Msgs(self)


def _row(u: dict) -> dict:
    return {"model": SEAT, **u}


def _usd(*rows) -> float:
    return sum(pv.serving_cost_usd(SEAT, r["in"], r["out"], r["cache_read"], r["cache_write"]) for r in rows)


@pytest.fixture()
def armed(monkeypatch):
    """The arm's seat, armed: claude-sonnet-5 with adaptive thinking on the anthropic provider, census on."""
    for k in ("GRAPHRAG_STATE_BOARD", "GRAPHRAG_NUMBERS_MODE_BUDGET", "GRAPHRAG_NUMBERS_BUDGET_NOTE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GRAPHRAG_NUMBERS_THINKING", "adaptive")
    monkeypatch.setenv("GRAPHRAG_NUMBERS_MODEL", SEAT)
    monkeypatch.setenv("GRAPHRAG_COST_CENSUS", "on")
    monkeypatch.setattr(pv, "provider", lambda: "anthropic")
    monkeypatch.setattr(pv, "supports_adaptive", lambda m: True)
    return monkeypatch


def _qfn(counter: list):
    def _q(sql):
        counter.append(sql)
        return []
    return _q


# == T-1 THE RUNG LADDER ===============================================================================================
def test_T1_the_rungs_are_the_two_measured_floors_and_the_next_rung_is_read_off_the_ladder():
    assert na._NUMBERS_RUNGS == (na._THINKING_MAX_TOKENS, na._NARROWED_MAX_TOKENS) == (6000, 12000)
    assert na._next_rung(6000) == 12000                 # the arm's wall climbs to the narrowed floor
    assert na._next_rung(8000) == 12000                 # a caller ceiling between rungs climbs to the next one
    assert na._next_rung(12000) is None                 # the top rung climbs nowhere -> the sentinel stands
    assert na._next_rung(20000) is None                 # a caller ceiling above the ladder is never lowered


def test_T1_ladder_on_the_truncated_round_reruns_ONCE_on_the_SAME_messages_at_the_next_rung_and_serves(armed):
    """The tariff treatment's round 1, verbatim in usage; the truncated response even carries a partial tool_use
    block, and it is NEVER executed nor appended -- the re-run reads exactly the messages the truncated round read."""
    fin = {"in": 162, "out": 7400, "cache_read": 102568, "cache_write": 0}
    c = _FakeClient([_resp("max_tokens", TARIFF_T_R1, tools=1),
                     _resp("tool_use", fin, tools=2),
                     _resp("end_turn", {"in": 2, "out": 900, "cache_read": 110000, "cache_write": 3000},
                           text="read.")])
    sink: list = []
    seen: list = []
    out = na.answer_numbers(TARIFF_Q, ASOF, client=c, query_fn=_qfn(seen), usage_sink=sink, rung_ladder=True)
    assert [k["max_tokens"] for k in c.sent] == [6000, 12000, 12000]           # climbed, and the climb holds
    assert c.sent[0]["messages"] == c.sent[1]["messages"]                       # T1-c: the SAME convo
    assert len(c.sent[0]["messages"]) == 1                                      # nothing of the truncation added
    assert len(seen) == 2                                                       # only the re-run's two lookups ran
    bud = out["numbers_budget"]
    assert list(bud)[-1] == "rungs"                                             # appended LAST
    assert bud["rungs"] == [{"max_tokens": 6000, "stop": "max_tokens", "out": 6000},
                            {"max_tokens": 12000, "stop": "tool_use", "out": 7400}]
    assert bud["max_tokens"] == 12000 and bud["rounds_used"] == 2               # the re-run is not a new round
    # T2-b: ONE list across the ladder -- the truncated round is priced beside its re-run
    assert out["numbers_usage"] == sink == [_row(TARIFF_T_R1), _row(fin), _row(
        {"in": 2, "out": 900, "cache_read": 110000, "cache_write": 3000})]
    assert abs(_usd(TARIFF_T_R1) - 0.1212564) < 1e-12                           # the truncated round's own dollars
    assert "numbers_error" not in out


def test_T1_ladder_on_a_SECOND_truncation_raises_with_the_FIRST_message_at_its_head_and_both_rounds_priced(armed):
    c = _FakeClient([_resp("max_tokens", TARIFF_T_R1),
                     _resp("max_tokens", {"in": 162, "out": 12000, "cache_read": 102568, "cache_write": 0})])
    sink: list = []
    with pytest.raises(RuntimeError) as exc:
        na.answer_numbers(TARIFF_Q, ASOF, client=c, query_fn=lambda sql: [], usage_sink=sink, rung_ladder=True)
    msg = str(exc.value)
    assert msg.startswith(HEAD_TRUNC_6000)                                     # numbers_error keeps the first
    assert msg == HEAD_TRUNC_6000 + "; re-run once at max_tokens=12000, and round 1 TRUNCATED at it"
    assert msg[:200] == msg                                                    # the orchestrator's cut keeps it whole
    assert [k["max_tokens"] for k in c.sent] == [6000, 12000]                  # ONE re-run, never a loop (T1-d)
    assert [r["out"] for r in sink] == [6000, 12000]
    assert abs(_usd(*sink) - (0.1212564 + 0.2112564)) < 1e-12                  # the ladder's worst case, priced


def test_T1_a_later_round_that_truncates_after_the_climb_raises_naming_its_own_round(armed):
    """The ladder fires at most once per turn: round 1 climbs and serves, round 2 truncates at the climbed rung and
    the turn raises -- the head is still the turn's first truncation, the tail names the round that ended it."""
    c = _FakeClient([_resp("max_tokens", TARIFF_T_R1),
                     _resp("tool_use", {"in": 162, "out": 7000, "cache_read": 102568, "cache_write": 0}, tools=1),
                     _resp("max_tokens", {"in": 2, "out": 12000, "cache_read": 102568, "cache_write": 9000})])
    with pytest.raises(RuntimeError) as exc:
        na.answer_numbers(TARIFF_Q, ASOF, client=c, query_fn=lambda sql: [], rung_ladder=True)
    assert str(exc.value) == HEAD_TRUNC_6000 + "; re-run once at max_tokens=12000, and round 2 TRUNCATED at it"
    assert [k["max_tokens"] for k in c.sent] == [6000, 12000, 12000]


def test_T1_ladder_OFF_is_HEADs_raise_byte_for_byte_and_the_sink_still_keeps_the_spend(armed):
    c = _FakeClient([_resp("max_tokens", TARIFF_T_R1),
                     _resp("end_turn", {"in": 1, "out": 1, "cache_read": 0, "cache_write": 0}, text="never read")])
    sink: list = []
    with pytest.raises(RuntimeError) as exc:
        na.answer_numbers(TARIFF_Q, ASOF, client=c, query_fn=lambda sql: [], usage_sink=sink)
    assert str(exc.value) == HEAD_TRUNC_6000                                   # the default is HEAD
    assert len(c.sent) == 1 and c.sent[0]["max_tokens"] == 6000
    assert sink == [_row(TARIFF_T_R1)]                                         # T-2: the spend survives the raise


def test_T1_a_narrowed_turn_already_at_the_top_rung_raises_as_HEAD_and_stamps_no_rungs(armed):
    c = _FakeClient([_resp("max_tokens", {"in": 300, "out": 12000, "cache_read": 102568, "cache_write": 0})])
    with pytest.raises(RuntimeError) as exc:
        na.answer_numbers(TARIFF_Q, ASOF, client=c, query_fn=lambda sql: [], max_calls=3, rung_ladder=True)
    assert str(exc.value) == HEAD_TRUNC_6000.replace("max_tokens=6000", "max_tokens=12000")
    assert len(c.sent) == 1


def test_T1_the_UNARMED_lane_never_climbs(monkeypatch):
    """T1-f: HEAD has no sentinel on the thought-free lane, so there is nothing to re-run: one create at HEAD's 1,500,
    the historic pass-through, with the ladder lit or not."""
    monkeypatch.delenv("GRAPHRAG_NUMBERS_THINKING", raising=False)
    for ladder in (False, True):
        c = _FakeClient([types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="cut")],
                                               stop_reason="max_tokens", usage=None)])
        out = na.answer_numbers(TARIFF_Q, ASOF, client=c, query_fn=lambda sql: [], rung_ladder=ladder)
        assert [k["max_tokens"] for k in c.sent] == [1500] and "thinking" not in c.sent[0]
        assert "rungs" not in out["numbers_budget"]


def test_T1_a_turn_the_ladder_never_fired_on_keeps_HEADs_five_key_stamp(armed):
    c = _FakeClient([_resp("end_turn", {"in": 150, "out": 800, "cache_read": 102568, "cache_write": 0},
                           text="nothing to read.")])
    out = na.answer_numbers(TARIFF_Q, ASOF, client=c, query_fn=lambda sql: [], rung_ladder=True)
    assert set(out["numbers_budget"]) == {"max_calls", "rounds_used", "lookups", "capped", "max_tokens"}
    assert na._budget_stamp(3, 1, [], capped=False, max_tokens=6000, rungs=[]) == \
        na._budget_stamp(3, 1, [], capped=False, max_tokens=6000)


# == T-2 THE CALLER-OWNED USAGE SINK ===================================================================================
def test_T2_the_kwargs_are_appended_at_the_TAIL_with_HEADs_defaults():
    names = list(_REAL_SIG.parameters)
    assert names[-2:] == ["usage_sink", "rung_ladder"]
    assert names[names.index("usage_sink") - 1] == "closed_year"             # HEAD's own tail, untouched
    assert _REAL_SIG.parameters["usage_sink"].default is None
    assert _REAL_SIG.parameters["rung_ladder"].default is False
    assert _REAL_SIG.parameters["usage_sink"].kind is inspect.Parameter.KEYWORD_ONLY
    assert _REAL_SIG.parameters["rung_ladder"].kind is inspect.Parameter.KEYWORD_ONLY


def test_T2_the_sink_is_filled_ONLY_under_the_census_gate_and_equals_numbers_usage_on_a_clean_return(armed):
    rounds = [_resp("tool_use", {"in": 140, "out": 2000, "cache_read": 102568, "cache_write": 0}, tools=1),
              _resp("end_turn", {"in": 2, "out": 700, "cache_read": 104000, "cache_write": 1500}, text="ok")]
    sink: list = []
    out = na.answer_numbers(TARIFF_Q, ASOF, client=_FakeClient(rounds), query_fn=lambda sql: [], usage_sink=sink)
    assert len(sink) == 2 and out["numbers_usage"] == sink                   # T2-a: equal content, one truth
    armed.setenv("GRAPHRAG_COST_CENSUS", "off")
    sink_off: list = []
    out_off = na.answer_numbers(TARIFF_Q, ASOF, client=_FakeClient(rounds), query_fn=lambda sql: [],
                                usage_sink=sink_off)
    assert sink_off == [] and "numbers_usage" not in out_off                  # census dark -> HEAD's shape


def test_T2_the_orchestrator_now_passes_the_sink_to_the_real_agent():
    assert orch._numbers_takes_usage_sink() is True


def _writer_stub(seen: dict):
    def _writer(query, *, extra_resolver=None, **kw):
        ctx, calls = extra_resolver()
        seen["context"], seen["calls"] = ctx, calls
        return {"answer": "(writer stubbed)", "trace": {}}
    return _writer


def _ladder_wired() -> bool:
    """ORCHESTRATOR SEAM EDIT S-1 (CONTRACT P12), read DEFENSIVELY: present -> a board turn threads the ladder."""
    probe = getattr(orch, "_numbers_takes_rung_ladder", None)
    return bool(probe and probe())


# seat -> (board lit in its cell, the question, the arm's logged rounds (the last one truncated), their dollars)
_SEATS = {
    "tariff_treatment": (True, TARIFF_Q, [TARIFF_T_R1], 0.1212564),
    "tariff_control": (False, TARIFF_Q, [TARIFF_C_R1, TARIFF_C_R2], 0.29240655),
    "palm_rape_control": (False, "Palm oil versus rapeseed oil: whose stocks moved more this year, and which way "
                                 "does that lean the spread?", [PALM_C_R1], 0.1211784),
}


@pytest.mark.parametrize("seat", sorted(_SEATS))
def test_T2_the_three_failed_arm_seats_are_PRICED_through_the_real_run_hybrid(seat, armed):
    """The arm's three failed seats, replayed with their CloudWatch usage through the real agent and the real
    `run_hybrid`: `numbers_usage` now carries the rounds the seat spent before it raised, and the eval's ONE pricing
    arithmetic gives the seat its dollars (HEAD: no `numbers` seat at all)."""
    board, q, rows, usd = _SEATS[seat]
    if board:
        armed.setenv("GRAPHRAG_STATE_BOARD", "on")
    queue = [(_resp("tool_use", r, tools=1) if i < len(rows) - 1 else _resp("max_tokens", r))
             for i, r in enumerate(rows)]
    # a scripted re-run for the board turn, consumed only once S-1 threads the ladder: it truncates too, so the seat
    # still fails and the record must carry BOTH rounds
    rerun = {"in": 162, "out": 12000, "cache_read": 102568, "cache_write": 0}
    queue.append(_resp("max_tokens", rerun))
    armed.setattr(an, "answer", _writer_stub({}))
    out = orch.run_hybrid(q, ASOF, graph=None, client=_FakeClient(queue), numbers_model=SEAT,
                          query_fn=lambda sql: [])
    tr = out.get("trace") or {}
    laddered = board and _ladder_wired()
    spent = [_row(r) for r in rows] + ([_row(rerun)] if laddered else [])
    assert tr["numbers_usage"] == spent
    assert tr["numbers_error"]["kind"] == "RuntimeError"
    assert tr["numbers_error"]["error"].startswith(HEAD_TRUNC_6000)            # numbers_error keeps the first
    total, seats = ev._turn_cost_total_usd(tr)
    want = usd + (_usd(rerun) if laddered else 0.0)
    assert seats is not None and abs(seats["numbers"] - want) < 1e-9, seats
    assert abs(_usd(*rows) - usd) < 1e-12                                       # the pinned dollars ARE the rows'


def test_T2_a_healthy_seat_is_counted_ONCE_through_run_hybrid(armed):
    """T2-a: the sink and the return carry the same rows; the orchestrator reads the sink only on its exception
    path, so a clean seat's trace holds each round exactly once."""
    rounds = [_resp("tool_use", {"in": 140, "out": 2000, "cache_read": 102568, "cache_write": 0}, tools=1),
              _resp("end_turn", {"in": 2, "out": 700, "cache_read": 104000, "cache_write": 1500}, text="ok")]
    armed.setattr(an, "answer", _writer_stub({}))
    tr = orch.run_hybrid(TARIFF_Q, ASOF, graph=None, client=_FakeClient(rounds), numbers_model=SEAT,
                         query_fn=lambda sql: []).get("trace") or {}
    assert len(tr["numbers_usage"]) == 2 and "numbers_error" not in tr


@pytest.mark.parametrize("board", [False, True])
def test_T1_S1_the_ladder_reaches_ONLY_a_board_turn(board, armed):
    """The integration half (ORCHESTRATOR SEAM EDIT S-1), read defensively. Before S-1 lands the ladder never fires
    (safe: HEAD, the seat raises); after it, a BOARD turn climbs and serves while a flag-off turn raises exactly as
    HEAD (S-5: the control cell never moves)."""
    if board:
        armed.setenv("GRAPHRAG_STATE_BOARD", "on")
    fin = {"in": 162, "out": 7400, "cache_read": 102568, "cache_write": 0}
    queue = [_resp("max_tokens", TARIFF_T_R1), _resp("end_turn", fin, text="read.")]
    armed.setattr(an, "answer", _writer_stub({}))
    tr = orch.run_hybrid(TARIFF_Q, ASOF, graph=None, client=_FakeClient(queue), numbers_model=SEAT,
                         query_fn=lambda sql: []).get("trace") or {}
    if board and _ladder_wired():
        assert "numbers_error" not in tr
        assert tr["numbers_usage"] == [_row(TARIFF_T_R1), _row(fin)]
    else:
        assert tr["numbers_error"]["error"] == HEAD_TRUNC_6000
        assert tr["numbers_usage"] == [_row(TARIFF_T_R1)]
