"""ESR destination-scope honesty guard — mocked LLM + injected Athena (no spend).

silver_esr has NO destination filter (raw unmapped FAS codes), so a destination-scoped ask ("corn sales to
China?") would otherwise get a NATIONAL total posing as the destination answer. The guard must: (1) detect
explicit buyer/destination phrasings deterministically, failing toward NOT-destination-scoped on ambiguity;
(2) prepend an honest, register-clean decline of the destination cut when an ESR lookup actually ran; and
(3) leave national ESR asks and non-ESR questions BYTE-identical.
"""
from __future__ import annotations

import json
import types

from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.register import register_leaks, sanitize


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


_ESR_ROWS = [{"value": "1234.5", "knowledge_date": "20260514", "data_date": "2026-05-07"}]


def _esr_use(tid="t1"):
    return _tool_use({"table": "silver_esr", "metric": "weekly_exports_1000mt",
                      "commodity": "corn_cbot", "period": "2025", "agg": "latest"}, tid)


def _run(question, queue, query_fn=None):
    return A.answer_numbers(question, asof="2026-05-20", client=FakeClient(queue),
                            query_fn=query_fn or (lambda sql: list(_ESR_ROWS)))


# ── detection: destination-scoped phrasings fire ──────────────────────────────────────────────────────
def test_destination_scoped_phrasings_detected():
    cases = {
        "How are corn export sales to China pacing?": "China",
        "soybean sales to Mexico this marketing year": "Mexico",
        "Chinese purchases of US corn last week?": "China",
        "What were wheat bookings by Egypt so far?": "Egypt",
        "Is Japanese buying of sorghum picking up?": "Japan",
        "wheat shipments into Vietnam this year": "Vietnam",
        "How much corn has China booked for 2025/26?": "China",
        "Any pickup in demand from South Korea for corn?": "South Korea",
        "Egypt's bookings of wheat vs last year?": "Egypt",
        "corn sales to unknown destinations lately?": "unknown destinations",
        # skeptic-wave regressions: participial directional verbs, possessive+commodity gap, buyer-side 'from'
        "How much corn is booked to China?": "China",
        "How much corn is committed to China this MY?": "China",
        "China's corn purchases this week?": "China",
        "Egypt's wheat bookings vs last year?": "Egypt",
        "Mexico corn commitments so far?": "Mexico",
        "Any cancellations from China this week?": "China",
        "corn sales to Turkey pacing?": "Turkey",               # homonym stays valid in directional position
    }
    for q, want in cases.items():
        assert A.esr_destination_scope(q) == want, q


# ── detection: national / ambiguous asks fail toward None (never degrade a national ask) ──────────────
def test_national_and_ambiguous_asks_not_detected():
    for q in [
        "How are corn export sales pacing this marketing year?",
        "What were weekly soybean export sales last week?",
        "Total US wheat export commitments so far?",
        "US corn sales momentum vs the 5-year average?",
        "Is China a factor in the corn market right now?",      # bare mention, no buyer-directional phrasing
        "china corn balance sheet as of today",                 # PSD-style ask, not a buyer phrasing
        "How do corn sales compare with year-ago levels?",
        "corn purchases from China",                            # 'from' = seller-ambiguous -> fail closed
        # skeptic-wave regressions: comparison idioms are NATIONAL; 'turkey' the bird is poultry not Türkiye
        "How do US corn sales compare to Brazil?",
        "US corn export sales compared to Brazil's program?",
        "Weekly wheat export sales relative to Argentina?",
        "Are corn sales close to China's year-ago pace?",
        "Is turkey demand supporting corn export sales?",
        "feed demand from turkey producers this quarter?",
        "Brazilian export commitments vs US sales?",            # seller-side gap word -> not a buyer ask
    ]:
        assert A.esr_destination_scope(q) is None, q


# ── detection: destination-BREAKDOWN asks (no single named buyer) fire the generic sentinel ───────────
def test_destination_breakdown_asks_detected_generic():
    for q in [
        "Which countries are buying US corn right now?",
        "Top buyers of US soybeans this week?",
        "Can you break corn export sales down by destination?",
        "Who is buying US wheat lately?",
        "destination breakdown for corn sales?",
    ]:
        assert A.esr_destination_scope(q) == A._ESR_DEST_GENERIC, q


def test_breakdown_ask_gets_generic_decline_and_is_register_clean():
    model_text = "Weekly corn exports were 1,234.5 thousand MT (report of 2026-05-14)."
    out = _run("Which countries are buying US corn right now?",
               [_resp([_esr_use()], "tool_use"), _resp([_text(model_text)], "end_turn")])
    ans = out["answer"]
    assert out["esr_destination_guard"] == A._ESR_DEST_GENERIC
    assert ans.startswith("One limitation to flag")
    assert "breakdown by individual destination" in ans and model_text in ans
    assert out["calls"][0]["scope_note"].startswith("NATIONAL TOTAL")
    assert register_leaks(sanitize(ans)) == []


# ── guard fires: destination-scoped ESR ask gets the decline preface + payload note ───────────────────
def test_destination_scoped_esr_ask_gets_decline_and_national_caveat():
    model_text = "Weekly corn exports were 1,234.5 thousand MT (report of 2026-05-14)."
    client_queue = [_resp([_esr_use()], "tool_use"), _resp([_text(model_text)], "end_turn")]
    out = _run("How are corn sales to China pacing?", client_queue)
    ans = out["answer"]
    assert out["esr_destination_guard"] == "China"
    assert ans.startswith("One limitation to flag")                 # deterministic preface, prompt-independent
    assert "national total" in ans and "not specific to China" in ans
    assert model_text in ans                                        # national figure carried, WITH the caveat
    assert out["calls"][0]["scope_note"].startswith("NATIONAL TOTAL")


def test_guard_covers_several_phrasings_end_to_end():
    for q, dest in [("soybean sales to Mexico — how do they look?", "Mexico"),
                    ("Chinese purchases of corn this month?", "China"),
                    ("wheat bookings by Egypt vs last year?", "Egypt")]:
        out = _run(q, [_resp([_esr_use()], "tool_use"), _resp([_text("Roughly 1,234.5 thousand MT.")], "end_turn")])
        assert out.get("esr_destination_guard") == dest, q
        assert f"not specific to {dest}" in out["answer"], q


def test_guard_fires_even_when_the_esr_lookup_errors():
    # The destination cut is unavailable regardless of lookup outcome — the decline must not depend on rows.
    def failing(sql):
        raise RuntimeError("Athena FAILED: boom")
    out = _run("How much corn has China booked?", [
        _resp([_esr_use()], "tool_use"),
        _resp([_text("The figure is unavailable due to a lookup error.")], "end_turn")], query_fn=failing)
    assert out["calls"][0]["status"] == "error"
    assert out["esr_destination_guard"] == "China"
    assert out["answer"].startswith("One limitation to flag")


def test_model_sees_the_scope_note_in_the_tool_result():
    out_client = FakeClient([_resp([_esr_use()], "tool_use"), _resp([_text("done")], "end_turn")])
    A.answer_numbers("corn sales to China?", asof="2026-05-20", client=out_client,
                     query_fn=lambda sql: list(_ESR_ROWS))
    sent = json.loads(out_client.sent[-1]["messages"][-1]["content"][0]["content"])
    assert "scope_note" in sent and "China" in sent["scope_note"]   # defense-in-depth: the model is told too


# ── national ESR asks: BYTE-unchanged (>=3 phrasings pinned) ──────────────────────────────────────────
def test_national_esr_answers_byte_unchanged():
    for q in ["How are corn export sales pacing this marketing year?",
              "What were weekly soybean export sales last week?",
              "Total US wheat export commitments so far?"]:
        model_text = "Weekly exports were 1,234.5 thousand MT (report of 2026-05-14)."
        out = _run(q, [_resp([_esr_use()], "tool_use"), _resp([_text(model_text)], "end_turn")])
        assert out["answer"] == model_text, q                        # byte-identical: no preface, no rewrite
        assert "esr_destination_guard" not in out, q
        assert "scope_note" not in out["calls"][0], q                # payload untouched -> model convo unchanged


# ── non-ESR questions: unaffected even with destination language ──────────────────────────────────────
def test_non_esr_question_with_destination_language_unaffected():
    model_text = "China imported 23,000,000 MT of corn in MY2024 (release of 2026-04-10)."
    psd_use = _tool_use({"table": "silver_psd", "metric": "imports_mt", "commodity": "corn_cbot",
                         "country": "China", "period": "2024"})
    out = _run("What are Chinese purchases of corn running at on the balance sheet?",
               [_resp([psd_use], "tool_use"), _resp([_text(model_text)], "end_turn")],
               query_fn=lambda sql: [{"value": "23000000", "knowledge_date": "2026-04-10"}])
    assert out["answer"] == model_text                               # destination words alone never gate non-ESR
    assert "esr_destination_guard" not in out
    assert "scope_note" not in out["calls"][0]


# ── register: the decline text carries no internal tokens/slugs/table names ───────────────────────────
def test_decline_text_is_register_clean():
    out = _run("How are corn sales to China pacing?", [
        _resp([_esr_use()], "tool_use"),
        _resp([_text("Weekly exports were 1,234.5 thousand MT (report of 2026-05-14).")], "end_turn")])
    ans = out["answer"]
    assert register_leaks(sanitize(ans)) == []                       # the standing register-leak harness
    low = ans.lower()
    for token in ("silver_esr", "silver_esr_compact", "corn_cbot", "lookup_number", "table", "sql"):
        assert token not in low, token                               # no internal register in reader prose


# ── hybrid seam: scope_note rides the synthesis numbers block; absent note = byte-identical block ─────
def test_numbers_block_carries_scope_note_for_hybrid():
    call = {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "corn_cbot",
                      "asof": "2026-05-20"}, "rows": list(_ESR_ROWS), "status": "ok",
            "scope_note": A._esr_scope_note("China")}
    block = orch._numbers_block([call])
    assert "SCOPE NOTE" in block and "China" in block
    plain = dict(call)
    plain.pop("scope_note")
    unflagged = orch._numbers_block([plain])
    assert "SCOPE NOTE" not in unflagged                             # national path: block byte-identical
    assert unflagged == block.split("\nSCOPE NOTE")[0]
