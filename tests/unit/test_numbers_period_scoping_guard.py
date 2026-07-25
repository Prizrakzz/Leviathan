"""year_month PERIOD-SCOPING honesty guard (task #142) -- mocked LLM + injected Athena (no spend).

The month-grained cards (silver_noaa_iod / silver_noaa_oni / gold_weather_z) are as-of-guarded on
(year*100 + month) <= asof_ym, so an UNSCOPED lookup answers "the newest month on or before the as-of date",
NOT "the month you named". The judged newcap30 row ncap_iod_1997_analog is exactly that miss: "the DMI in
October 1997" as-of 1998-06-01 came back with the June-1998 row and the answer invented a "not yet published"
story for a month that was in the lake the whole time. The guard must: (1) resolve the asked month when the
lookup IS scoped; (2) flag the mismatch deterministically -- on the tool_result AND in the reader-facing
answer -- when it is not; (3) ride the trace; and (4) leave un-named-month asks BYTE-identical.
"""
from __future__ import annotations

import json
import re
import types

from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import load_registry
from leviathan.graphrag.register import count_flow_words, count_valuation_words, register_leaks, sanitize

ASOF = "1998-06-01"                                   # the judged row's as-of
ASKED = "October 1997"                                # the month the question names
LATEST = "June 1998"                                  # what an UNSCOPED lookup returns at that as-of


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


# The live IOD record around the 1997 event (CPC ERSSTv5 basis) plus the as-of's newest month. The fake
# executor reads the (year*100+month) bounds back out of the COMPILED SQL, so a scoped call and an unscoped
# one genuinely diverge here exactly as they do on the real backend.
_IOD_SERIES = {199709: "0.85", 199710: "0.99", 199711: "1.05", 199806: "0.147"}


def _iod_qfn(sql: str) -> list[dict]:
    lo, hi = 0, 999912
    m = re.search(r"\(year \* 100 \+ month\) >= (\d+)", sql)
    if m:
        lo = int(m.group(1))
    for m in re.finditer(r"\(year \* 100 \+ month\) <= (\d+)", sql):
        hi = min(hi, int(m.group(1)))
    keep = sorted(ym for ym in _IOD_SERIES if lo <= ym <= hi)
    if not keep:
        return []
    ym = keep[-1]                                     # ORDER BY (year*100+month) DESC LIMIT 1 (agg=latest)
    return [{"value": _IOD_SERIES[ym], "year": ym // 100, "month": ym % 100}]


def _iod_use(scoped: bool, tid="t1"):
    inp = {"table": "silver_noaa_iod", "metric": "dmi_value", "agg": "latest"}
    if scoped:
        inp.update({"period_start": "1997-10", "period_end": "1997-10"})
    return _tool_use(inp, tid)


QUESTION = ("As of 1 June 1998, what was the Indian Ocean Dipole (DMI) reading in October 1997, "
            "during that big El Nino?")


def _run(question, queue, query_fn=None):
    return A.answer_numbers(question, asof=ASOF, client=FakeClient(queue),
                            query_fn=query_fn or _iod_qfn)


# -- detection: a NAMED historical month fires; a date / as-of framing does not -------------------------
def test_named_month_window_detected():
    cases = {
        QUESTION: (199710, 199710),
        "what was the DMI in Oct 1997?": (199710, 199710),
        "the DMI reading for October of 1997": (199710, 199710),
        "ONI anomaly in March 2016": (201603, 201603),
        "heat stress from June 2012 through August 2012": (201206, 201208),
    }
    for q, want in cases.items():
        assert A.asked_month_window(q) == want, q


def test_dates_and_asof_framing_are_not_a_named_month():
    for q in [
        "As of 1 July 2026, what is the latest DMI reading available?",   # day-prefixed date
        "as of June 2026, where does the IOD sit?",                       # as-of framing
        "as at June 2026 what is the DMI?",
        "What is the latest Indian Ocean Dipole reading?",                # no month at all
        "How has the DMI moved over the last three months?",              # relative window, no named month
        "What was the DMI in 1997?",                                      # bare year, no month
    ]:
        assert A.asked_month_window(q) is None, q


# -- (a) a PERIOD-SCOPED call resolves the asked month -------------------------------------------------
def test_period_scoped_query_binds_the_asked_month():
    ts = load_registry().get("silver_noaa_iod")
    spec = Q.NumberQuery(table="silver_noaa_iod", metric="dmi_value", asof=ASOF,
                         period_start="1997-10", period_end="1997-10")
    sql = Q.build_sql(spec, ts)
    assert "(year * 100 + month) >= 199710" in sql and "(year * 100 + month) <= 199710" in sql
    rows = [{"year": y, "month": m, "dmi_value": 0.1} for y in (1997, 1998) for m in range(1, 13)]
    kept = Q.apply_pit_filter(rows, spec, ts)
    assert [(r["year"], r["month"]) for r in kept] == [(1997, 10)]        # exactly the month asked about


def test_period_scoped_turn_serves_the_asked_month_and_never_fires_the_guard():
    model_text = "The DMI in October 1997 was 0.99 degC."
    out = _run(QUESTION, [_resp([_iod_use(scoped=True)], "tool_use"),
                          _resp([_text(model_text)], "end_turn")])
    assert out["calls"][0]["rows"][0]["value"] == "0.99"                  # the asked month, not the latest
    assert out["answer"] == model_text                                    # no preface: nothing to flag
    assert "period_mismatch_guard" not in out
    assert "scope_note" not in out["calls"][0]


# -- (b) an UNSCOPED call on a named-month ask is FLAGGED ----------------------------------------------
def test_unscoped_named_month_ask_is_flagged_in_the_answer():
    # the judged failure replay: the model narrates the June-1998 row as an unavailability story
    model_text = ("The October 1997 DMI is not yet available -- the reconstruction lags, so the most recent "
                  "published value is 0.147 degC.")
    out = _run(QUESTION, [_resp([_iod_use(scoped=False)], "tool_use"),
                          _resp([_text(model_text)], "end_turn")])
    ans = out["answer"]
    assert out["period_mismatch_guard"] == "1997-10"
    assert ans.startswith("One scope note before the numbers:")           # deterministic, prompt-independent
    assert f"returned {LATEST}, not {ASKED}" in ans                       # both months named, plainly
    assert "missing or unpublished" in ans                                # the invented-lag story is refused
    assert model_text in ans                                              # the model's prose is carried, caveated


def test_span_ask_flags_with_the_window_label():
    out = _run("What did the DMI do from October 1997 through December 1997?",
               [_resp([_iod_use(scoped=False)], "tool_use"), _resp([_text("0.147 degC.")], "end_turn")])
    assert out["period_mismatch_guard"] == "1997-10..1997-12"
    assert "October 1997 to December 1997" in out["answer"]


def test_model_sees_the_period_mismatch_note_in_the_tool_result():
    client = FakeClient([_resp([_iod_use(scoped=False)], "tool_use"), _resp([_text("done")], "end_turn")])
    A.answer_numbers(QUESTION, asof=ASOF, client=client, query_fn=_iod_qfn)
    sent = json.loads(client.sent[-1]["messages"][-1]["content"][0]["content"])
    note = sent["scope_note"]
    assert note.startswith("PERIOD MISMATCH")
    assert "period_start='1997-10'" in note and "period_end='1997-10'" in note   # the exact repair call
    assert "NEVER explain the asked month as not-yet-published" in note


def test_a_resolved_month_beside_a_latest_leg_is_not_flagged():
    # "how does the latest reading compare with October 1997" legitimately needs BOTH months: once the named
    # month IS resolved by some leg, the closing guard is a no-op (only the off-window leg carries a note).
    out = _run("How does the latest DMI compare with October 1997?",
               [_resp([_iod_use(scoped=True, tid="t1"), _iod_use(scoped=False, tid="t2")], "tool_use"),
                _resp([_text("0.99 degC then, 0.147 degC latest.")], "end_turn")])
    assert "period_mismatch_guard" not in out
    assert not out["answer"].startswith("One scope note")
    scoped, latest = out["calls"][0], out["calls"][1]
    assert "scope_note" not in scoped                                     # in-window leg untouched
    assert latest["scope_note"].startswith("PERIOD MISMATCH")             # off-window leg still told the truth


# -- byte-identical when no month is named, and on non-month-grained cards -----------------------------
def test_no_named_month_is_byte_identical():
    model_text = "The latest DMI reading is 0.147 degC for June 1998."
    out = _run("What is the latest Indian Ocean Dipole reading?",
               [_resp([_iod_use(scoped=False)], "tool_use"), _resp([_text(model_text)], "end_turn")])
    assert out["answer"] == model_text
    assert "period_mismatch_guard" not in out
    assert "scope_note" not in out["calls"][0]                            # payload untouched -> convo unchanged


def test_a_future_month_ask_is_not_flagged():
    # A month AFTER the as-of is genuinely not knowable at the as-of, so the not-yet-published explanation
    # this guard exists to ban is the CORRECT one there -- the guard must disarm rather than contradict it.
    out = _run("What was the DMI in December 1999?",
               [_resp([_iod_use(scoped=False)], "tool_use"),
                _resp([_text("That month was not yet published as of the as-of date.")], "end_turn")])
    assert "period_mismatch_guard" not in out
    assert "scope_note" not in out["calls"][0]


def test_non_month_grained_table_unaffected_by_a_named_month():
    model_text = "US corn ending stocks were 31,400,000 t for 1997/98 (release of 1998-05-12)."
    psd = _tool_use({"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                     "country": "United States", "period": "1997"})
    out = _run("Where did US corn ending stocks sit for the crop harvested in October 1997?",
               [_resp([psd], "tool_use"), _resp([_text(model_text)], "end_turn")],
               query_fn=lambda sql: [{"value": "31400000", "knowledge_date": "1998-05-12"}])
    assert out["answer"] == model_text                                    # a named month alone gates nothing
    assert "period_mismatch_guard" not in out
    assert "scope_note" not in out["calls"][0]


# -- the guard key rides the trace ---------------------------------------------------------------------
def test_guard_key_rides_the_orchestrator_trace():
    client = FakeClient([_resp([_iod_use(scoped=False)], "tool_use"),
                         _resp([_text("The most recent value is 0.147 degC.")], "end_turn")])
    out = orch.run_numbers_only(QUESTION, ASOF, client=client, query_fn=_iod_qfn)
    assert out["trace"]["period_mismatch_guard"] == "1997-10"
    assert int(out["trace"]["numbers_verifier"]["mismatched"]) == 0       # month labels are not stated figures
    # a scoped turn leaves the trace byte-identical (no key at all)
    clean = FakeClient([_resp([_iod_use(scoped=True)], "tool_use"),
                        _resp([_text("The October 1997 DMI was 0.99 degC.")], "end_turn")])
    assert "period_mismatch_guard" not in orch.run_numbers_only(QUESTION, ASOF, client=clean,
                                                                query_fn=_iod_qfn)["trace"]


def test_scope_note_rides_the_hybrid_numbers_block():
    call = {"query": {"table": "silver_noaa_iod", "metric": "dmi_value", "asof": ASOF},
            "rows": [{"value": "0.147", "year": 1998, "month": 6}], "status": "ok",
            "scope_note": A._period_mismatch_scope_note((199710, 199710), 199806)}
    block = orch._numbers_block([call])
    assert "SCOPE NOTE" in block and ASKED in block and LATEST in block
    plain = {k: v for k, v in call.items() if k != "scope_note"}
    assert "SCOPE NOTE" not in orch._numbers_block([plain])               # unflagged path: block unchanged


# -- register / prose fence: the guard line is reader-clean --------------------------------------------
def test_guard_prose_is_register_clean():
    out = _run(QUESTION, [_resp([_iod_use(scoped=False)], "tool_use"),
                          _resp([_text("The most recent value is 0.147 degC.")], "end_turn")])
    ans = out["answer"]
    assert register_leaks(sanitize(ans)) == []                            # the standing register-leak harness
    assert count_valuation_words(ans) == 0 and count_flow_words(ans) == 0
    low = ans.lower()
    for token in ("silver_noaa_iod", "gold_weather_z", "lookup_number", "year_month", "period_start", "sql"):
        assert token not in low, token                                    # no internal register in reader prose


# -- (a) prompt: the GENERAL month-grain rule covers oni + iod + weather_z ------------------------------
def test_system_prompt_carries_the_general_month_grain_rule():
    sp = A.system_prompt(load_registry())
    line = next(ln for ln in sp.split("\n") if ln.startswith("- MONTH-GRAINED tables"))
    for tbl in ("silver_noaa_oni", "silver_noaa_iod", "gold_weather_z"):
        assert tbl in line, tbl                                           # not an iod-only accident
    assert "period_start AND period_end" in line and "'YYYY-MM'" in line
    assert "NEVER explain the difference as a publication lag" in line    # the fabricated-story ban
