"""F14 / R8 -- DECLINE-REGISTER SUPPRESS-ON-OVERLAP (user-ratified, wave-plan addendum 2, 2026-08-01).

WHAT THIS FILE IS FOR. Two decline REGISTERS can co-occur in one answer preface: C2's question-shape
decline (numbers wave, 9db19fac) beside a legacy template -- the R5 price-coverage decline
(DECLINE_TEMPLATES), the SEAM-C futures levels-only decline (FUTURES_DECLINE_TEMPLATES), the ESR
destination decline, the W3.2 coverage decline. The reader then opens the answer on two consecutive
"One limitation to flag before the numbers:" sentences, each refusing a different thing.

The ratified resolution is SUPPRESS-ON-OVERLAP: when any OTHER decline template already fired for the
turn, the C2 line stays silent -- one preface, one decline. The RECONCILE alternative was REJECTED
because it re-pins strings the R5 / futures-lite censuses and the judged decks assert verbatim, so
NOTHING here (or in the change it covers) touches the TEXT of any template.

The acceptance is two-sided and both sides are load-bearing:
  (a) a turn where BOTH registers would fire renders EXACTLY ONE decline line -- the legacy one, with
      C2 silent. Each such test first asserts that C2 WOULD have fired on that turn's finished call
      list, so it can never pass vacuously by suppressing a line that was never coming.
  (b) a turn where ONLY the C2 register fires still renders the C2 line UNCHANGED -- pinned as byte
      equality against the pure renderer, not as a substring.

Plus the two halves the suppression rule itself rests on. Suppression keys on the SHARED LEAD, so this
file censuses BOTH sides of that split: every reader-facing DECLINE opens with SHAPE_DECLINE_LEAD, and
every NOTE preface (scope note, bloc caveat, legacy-provenance note) deliberately does not -- a note is a
statement about a figure the turn IS serving, not a second refusal, and must never silence C2. The
`test_the_preface_emitters_are_all_classified` tripwire fails the moment a new preface appears in the
agent, so a future template cannot join either side unclassified.
"""
from __future__ import annotations

import types

from leviathan.graphrag.numbers import agent as A

ASOF = "2026-07-31"
_COT_CALL = {"table": "silver_cot", "metric": "mm_net", "commodity": "corn_cbot"}
_MODEL_TEXT = "Managed money net length is discussed below."


# ==================================================================================================
# Harness (the test_question_shapes.py fake-client idiom -- an injected client takes no provider and
# no backoff, and query_fn replaces Athena).
# ==================================================================================================
def _tool_use(inp, tid="t1"):
    return types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, input=inp, id=tid)


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


class FakeClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.sent = []
        self.messages = _Msgs(self)


def _run(question, rows, tool_input=None):
    client = FakeClient([
        _resp([_tool_use(dict(tool_input or _COT_CALL))], "tool_use"),
        _resp([_text(_MODEL_TEXT)], "end_turn")])
    return A.answer_numbers(question, asof=ASOF, client=client, query_fn=lambda _sql: rows)


def _c2_would_fire(out) -> bool:
    """Did the C2 register actually reach its decline on THIS turn's finished call list? The guard
    against a vacuous acceptance test: `shape_decline` is the same pure function the agent calls, so a
    True here means the suppressed line was genuinely a line that was coming."""
    _preface, declined, _states = A.shape_decline(out.get("question_shape"), out["calls"])
    return bool(declined)


# ==================================================================================================
# (a) BOTH registers fire -> exactly one decline line, and it is the legacy one.
# ==================================================================================================
def test_price_decline_and_c2_render_exactly_one_decline_line():
    """The DECLINE_TEMPLATES half of F14. A positioning ask that also names a NONE-tier price series:
    the R5 price decline fires on phrasing, the COT lookup comes back empty so C2's would too."""
    out = _run("are funds net long corn, and separately what is the robusta coffee price", rows=[])
    assert out["calls"][0]["status"] == "no_rows"
    assert out["price_decline_guard"] == "robusta"
    assert _c2_would_fire(out), "fixture no longer arms BOTH registers -- the test would pass vacuously"

    # ONE preface, ONE decline.
    assert out["answer"].count(A.SHAPE_DECLINE_LEAD) == 1
    # ...and the survivor is the LEGACY line, verbatim.
    assert A.DECLINE_TEMPLATES["robusta"] in out["answer"]
    assert out["answer"].startswith(A._price_decline_preface("robusta").strip())
    # ...with the C2 sentence gone entirely (not merged, not reworded -- silent).
    assert "the record holds no" not in out["answer"]
    assert _MODEL_TEXT in out["answer"]                      # still a PREPEND, never a replacement


def test_futures_decline_and_c2_render_exactly_one_decline_line():
    """The FUTURES_DECLINE_TEMPLATES half of F14 -- the same overlap through the SEAM-C register."""
    out = _run("is managed money net long corn after the market has risen this month", rows=[])
    assert out["futures_decline_guard"] == "change"
    assert _c2_would_fire(out), "fixture no longer arms BOTH registers -- the test would pass vacuously"

    assert out["answer"].count(A.SHAPE_DECLINE_LEAD) == 1
    assert A.FUTURES_DECLINE_TEMPLATES["change"] in out["answer"]
    assert "the record holds no" not in out["answer"]
    assert _MODEL_TEXT in out["answer"]


def test_the_suppressed_turn_keeps_the_whole_shape_record():
    """Suppression is a RENDER decision, not a measurement one -- so it must cost the RECORD nothing.

    R8's first cut dropped `shape_decline_guard` on the suppressed turn, reading it as a receipt for what
    the reader got. It is not one. orchestrator.py:302-307 states in writing that the shape record is
    LANE-INDEPENDENT and that only the reader-facing preface is numbers_only-only, and eval.py:1160-1163
    calls that same key the reason the four miss states are readable from an artifact at all. Dropping it
    deleted the C2 miss from every artifact on exactly the overlap turns -- worst on HYBRID, where C2's
    prose is discarded before a reader ever sees it, so the record was the only observable half there.

    The verdict therefore rides BOTH branches, and the suppression is named BESIDE it."""
    out = _run("are funds net long corn, and separately what is the robusta coffee price", rows=[])
    assert out["question_shape"] == "positioning"
    assert out["shape_metric_states"] == {"cot_managed_money": "empty"}
    assert out["shape_decline_guard"] == ["cot_managed_money"]          # the verdict: present either way
    assert out["shape_decline_suppressed"] == ["cot_managed_money"]     # ...and the line was withheld


# The three C2 keys the orchestrator copies onto the trace (orchestrator.py:100 on the numbers_only lane,
# :308/:339 on the hybrid lane) and eval.py:1164-1166 projects into a row. A key not in this tuple reaches
# NO artifact -- eval.py:1153-1156 says so of its own projection -- which is why the record has to travel
# on a key already in it rather than on a new one the whitelists do not carry.
_TRACE_C2_KEYS = ("question_shape", "shape_metric_states", "shape_decline_guard")


def test_the_suppressed_turn_reaches_the_trace_through_the_existing_whitelist():
    """The observability leg, tested the way the orchestrator actually works: it copies a FIXED tuple off
    `answer_numbers`' return and drops everything else. A suppressed turn must be fully readable from what
    survives that copy -- shape, per-requirement states, and the decline verdict."""
    out = _run("are funds net long corn, and separately what is the robusta coffee price", rows=[])
    trace = {k: out[k] for k in _TRACE_C2_KEYS if out.get(k) is not None}
    assert set(trace) == set(_TRACE_C2_KEYS), "the suppressed turn is dark in every artifact"
    assert trace["shape_decline_guard"] == ["cot_managed_money"]
    # The suppression fact itself is numbers-lane-local until it joins those tuples; pinned so the day it
    # does, this line is the reminder that the whitelists are where it becomes readable downstream.
    assert "shape_decline_suppressed" not in trace


def test_the_record_keys_are_still_the_ones_the_trace_whitelists_carry():
    """Coupling tripwire. The whitelists are fixed tuples in files this rule does not own, so the moment
    they stop naming `shape_decline_guard` the record above stops reaching an artifact and every assertion
    in this file still passes. Fails loudly instead."""
    import inspect

    from leviathan.graphrag import eval as ev
    from leviathan.graphrag import orchestrator as orch

    tup = '"question_shape", "shape_metric_states", "shape_decline_guard"'
    assert inspect.getsource(orch).count(tup) == 3, "an orchestrator C2 whitelist moved -- see :100/:308/:339"
    assert '(out.get("trace") or {}).get("shape_decline_guard")' in inspect.getsource(ev)


# ==================================================================================================
# (b) ONLY the C2 register fires -> the C2 line is unchanged.
# ==================================================================================================
def test_c2_alone_still_renders_its_line_unchanged():
    """The other side of the acceptance. No legacy template fires, so nothing suppresses, and the
    answer is pinned as BYTE equality against the pure renderer -- 'unchanged' as an identity, not as a
    substring that would survive a reworded sentence."""
    out = _run("what is managed money doing in corn", rows=[])
    assert "price_decline_guard" not in out and "futures_decline_guard" not in out
    expected_preface, declined, _states = A.shape_decline("positioning", out["calls"])
    assert declined == ["cot_managed_money"] and expected_preface
    assert out["answer"] == (expected_preface + _MODEL_TEXT).strip()
    assert out["shape_decline_guard"] == ["cot_managed_money"]
    assert "shape_decline_suppressed" not in out
    assert out["answer"].count(A.SHAPE_DECLINE_LEAD) == 1


def test_a_scope_note_does_not_silence_the_c2_decline():
    """The (b) side, end to end, on the case that would break under a cruder rule ("any preface at all
    suppresses"). The seasonality shape carries two requirements: the month-grained weather lookup SERVES
    a figure -- for the wrong month, so the period-mismatch SCOPE NOTE is prepended -- while the ENSO
    lookup comes back empty. The note is a statement about the figure below it, not a refusal, so the
    turn honestly carries both: one note and one decline, in that order."""
    def _qf(sql):
        return [] if "silver_noaa_oni" in sql else [{"value": "-1.2", "year": "1998", "month": "6"}]

    client = FakeClient([
        _resp([_tool_use({"table": "gold_weather_z", "metric": "drought_z", "commodity": "corn_cbot"}, "t1"),
               _tool_use({"table": "silver_noaa_oni", "metric": "oni_anom"}, "t2")], "tool_use"),
        _resp([_text(_MODEL_TEXT)], "end_turn")])
    out = A.answer_numbers("how unusual was the drought in Argentina in October 1997",
                           asof="1998-06-01", client=client, query_fn=_qf)
    assert out["period_mismatch_guard"] == "1997-10"                  # a NOTE fired
    assert out["shape_metric_states"] == {"oni_climate": "empty", "drought_z": "served"}
    assert out["shape_decline_guard"] == ["oni_climate"]              # ...and C2 still rendered
    assert "shape_decline_suppressed" not in out
    assert out["answer"].startswith("One scope note before the numbers:")
    assert out["answer"].count(A.SHAPE_DECLINE_LEAD) == 1
    assert "the record holds no ENSO reading" in out["answer"]


def test_a_served_positioning_turn_is_untouched_by_r8():
    """No decline of any register -> no preface at all, exactly as before R8."""
    out = _run("what is managed money doing in corn", rows=[{"value": "118432", "knowledge_date": "2026-07-28"}])
    assert out["shape_metric_states"] == {"cot_managed_money": "served"}
    assert "shape_decline_guard" not in out and "shape_decline_suppressed" not in out
    assert out["answer"] == _MODEL_TEXT


# ==================================================================================================
# No OVER-suppression: R8 silences C2 and nothing else.
# ==================================================================================================
def test_two_legacy_declines_still_stack_unchanged():
    """R8 is a rule about the C2 line only. Two LEGACY templates on one turn (a NONE-tier price series
    asked about with a windowed-move framing) still render both, byte-for-byte as before -- the ratified
    behaviour reworded, merged or suppressed none of them."""
    out = _run("how much has the robusta coffee price risen this month", rows=[])
    assert "question_shape" not in out                        # shapeless: C2 is not in this turn at all
    assert out["price_decline_guard"] == "robusta" and out["futures_decline_guard"] == "change"
    assert out["answer"].count(A.SHAPE_DECLINE_LEAD) == 2
    assert A.DECLINE_TEMPLATES["robusta"] in out["answer"]
    assert A.FUTURES_DECLINE_TEMPLATES["change"] in out["answer"]


# ==================================================================================================
# The split the rule keys on: DECLINE prefaces share the lead, NOTE prefaces do not.
# ==================================================================================================
def _decline_prefaces() -> list[tuple[str, str]]:
    """(label, rendered preface) for every reader-facing DECLINE the numbers agent can prepend."""
    out = [("esr_destination_generic", A._esr_destination_preface(A._ESR_DEST_GENERIC)),
           ("esr_destination_named", A._esr_destination_preface("China"))]
    out += [(f"price:{k}", A._price_decline_preface(k)) for k in sorted(A.DECLINE_TEMPLATES)]
    out += [(f"futures:{c}", A._futures_decline_preface(c)) for c in A._FUTURES_DECLINE_CLASSES]
    out += [(f"coverage:{r}", A.futures_eod_coverage_preface(r, "2020-01-02"))
            for r in A.FUTURES_EOD_COVERAGE_CLASSES]
    return out


def _note_prefaces() -> list[tuple[str, str]]:
    """(label, rendered preface) for every reader-facing NOTE -- a statement about a figure the turn IS
    serving. None of these may silence C2: a scope note next to an honest absence is not a duplicate."""
    return [("period_mismatch", A._period_mismatch_preface((199710, 199710), 199806)),
            ("esr_bloc_caveat", A._esr_bloc_caveat_preface("the EU")),
            ("coverage_legacy", A.futures_eod_coverage_preface("legacy", "2020-01-02"))]


def test_every_decline_preface_opens_with_the_shared_lead():
    for label, text in _decline_prefaces():
        assert text.startswith(A.SHAPE_DECLINE_LEAD), f"{label} does not open with the decline lead"
        assert A.other_decline_fired(text), f"{label} would not suppress the C2 line"
    # C2's own line is a member of the same register -- which is exactly why the overlap reads as a
    # duplicate to a human and why the suppression is keyed here.
    assert A.shape_decline_line("positioning", ["managed-money positioning reading"]) \
        .startswith(A.SHAPE_DECLINE_LEAD)


def test_the_note_prefaces_never_read_as_a_decline():
    for label, text in _note_prefaces():
        assert text and not text.startswith(A.SHAPE_DECLINE_LEAD), f"{label} opens with the decline lead"
        assert not A.other_decline_fired(text), f"{label} would wrongly silence the C2 decline"


def test_the_preface_emitters_are_all_classified():
    """The tripwire that keeps the census honest. Suppression reads the accumulated preface STRING, so a
    new emitter that opens with the decline lead joins the rule for free -- but one that invents its own
    lead would silently re-open the double preface. This fails the moment the emitter set moves: classify
    the newcomer into _decline_prefaces or _note_prefaces above."""
    assert sorted(n for n in dir(A) if n.endswith("_preface")) == [
        "_esr_bloc_caveat_preface", "_esr_destination_preface", "_futures_decline_preface",
        "_period_mismatch_preface", "_price_decline_preface", "futures_eod_coverage_preface"]


def test_other_decline_fired_is_total():
    """Empty / absent prefaces are the common case (most turns have none) and must be cheap and safe."""
    assert A.other_decline_fired("") is False
    assert A.other_decline_fired(None) is False
    assert A.other_decline_fired("One scope note before the numbers: nothing to see") is False
    assert A.other_decline_fired(A.SHAPE_DECLINE_LEAD + "x") is True
    # ...and it sees a decline that is not the FIRST line of the preface: the ordering in answer_numbers
    # puts the period-mismatch scope note ahead of every decline, so a substring test is required.
    stacked = A._period_mismatch_preface((199710, 199710), 199806) + A._price_decline_preface("robusta")
    assert A.other_decline_fired(stacked) is True
