"""Multi-turn conversation eval harness — all mocked (no LLM/S3/Dynamo).

Pins: turns run SEQUENTIALLY per conversation while conversations parallelize without state bleed
(distinct session ids), the deterministic mechanics checks (carry/override/trap/vague-resolution),
the judge's conversation-history assembly, and the report's cache/speed panels.
"""
from __future__ import annotations

import contextlib
import io
import threading

from leviathan.graphrag import eval as gev
from leviathan.graphrag import session as ss

# Load-independence (2026-07-26). These turns are mocked and finish in microseconds, so nothing here should
# ever be near a wall-clock ceiling -- but run_conversations otherwise reads its deadline from the ambient
# env (GRAPHRAG_EVAL_TURN_DEADLINE, default 4200s), which makes the harness's watchdog an implicit input to
# a unit test. Pinning it explicitly removes that variable: no env, no box speed, and no co-tenant process
# can move it. Deliberately absurd relative to the work so it can never false-fire, and low enough that a
# genuine hang still ends the suite rather than parking it for 70 minutes.
_DEADLINE = 600.0


def _run(convos, **kw):
    """Run the harness with a pinned deadline, capturing its stdout so a failure is DIAGNOSABLE.

    run_conversations reports trouble by printing (`WARN drain convo ...` when a convo's future raised,
    `WATCHDOG ...` when one is orphaned) and then returns fewer rows -- eval.py:1444-1462 stores rows per
    convo index and `_drain` swallows a raising `_complete` with only a print. A bare `len(rows) == N`
    failure therefore tells you nothing about WHICH convo vanished or why; this hands the captured output to
    the assertion instead of leaving the next person to re-derive it.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rows = gev.run_conversations(None, convos, respond_fn=kw.pop("respond_fn"),
                                     store=kw.pop("store"), deadline=_DEADLINE, **kw)
    return rows, buf.getvalue()


def _census(rows):
    """Rows-per-convo, for the assertion message."""
    out: dict = {}
    for r in rows:
        out[r["convo"]] = out.get(r["convo"], 0) + 1
    return out


def _sid_is(sid: str | None, cid: str) -> bool:
    """Does this session id belong to convo `cid`? EXACT field match, never a substring.

    THE FLAKE (root-caused 2026-07-26). run_conversations builds `sid = f"eval-{cv['id']}-{run_tag}"` with
    `run_tag = uuid.uuid4().hex[:6]` (eval.py:1396). This file used to test membership with `cid in sid`,
    which also matches the RANDOM TAG: a run_tag of e.g. 'abc1ef' makes `"c1" in "eval-c2-abc1ef"` true, so
    c2's turns get attributed to c1 and the scripted-order assertion fails with c2's questions spliced into
    c1's list. Measured collision rate: **3.92% per run** (either 'c1' or 'c2' landing in 6 hex chars) --
    which is the whole flake, and it matches the reported ~1-in-15 to 1-in-25 rate.

    It is NOT load-sensitive: uuid4 does not care how busy the box is. The reported correlation with a
    concurrent pytest process was coincidence -- confirmed by 20/20 passes under 4-way CPU load and 300
    clean in-process repetitions, against a deterministic failure the moment the tag collides.
    """
    return (sid or "").startswith(f"eval-{cid}-")


CONVOS = [
    {"id": "c1", "turns": [
        {"q": "how does frost hit arabica?", "asof": "2021-08-01", "expected_intent": "reasoning",
         "contracts_any_of": ["arabica_coffee"]},
        {"q": "and the convexity?", "expected_intent": "reasoning", "carries_contracts": True,
         "carries_asof": True, "uses_state": True},
        {"q": "same but as of 2019", "asof": "2019-06-01", "overrides_asof": True},
    ]},
    {"id": "c2", "turns": [
        {"q": "brazil soy production?", "asof": "2024-02-15", "expected_intent": "numbers_only"},
        {"q": "what does the May 2024 WASDE say?", "carries_asof": True, "not_known": True},
    ]},
]


def _fake_respond_factory(log):
    lock = threading.Lock()
    asof_by_sid: dict = {}                 # closure state, guarded -- see below

    def respond(q, *, graph, asof=None, model=None, numbers_client=None, call=None,
                session_id=None, session_store=None):
        # `workers=2` runs the two convos on separate threads, so this carry-forward state is touched
        # concurrently. It used to live on the function object and be read-modify-written unguarded
        # (`getattr(respond,'asof_by_sid',{})` -> assign -> mutate): if both threads reached the getattr
        # before either assigned, both built a fresh dict and one silently clobbered the other's entry,
        # dropping a session's carried as-of. The window is only a few bytecodes -- 300 stress runs never
        # hit it -- but it is a genuine lost update whose odds rise exactly when the box is loaded and the
        # scheduler preempts mid-sequence, which is the class of flake this file is being hardened against.
        # One lock now covers the whole log-and-carry critical section.
        with lock:
            log.append((session_id, q))
            prev_asof = asof_by_sid.get(session_id)
            eff_asof = asof or prev_asof or "2026-07-03"
            asof_by_sid[session_id] = eff_asof
        nk = "was not published at the as-of date" if "May 2024" in q else ""
        return {"answer": f"ans: {q} {nk}".strip(), "intent": ("numbers_only" if "production" in q or "WASDE" in q
                                                               else "reasoning"),
                # exact field match, not `"c1" in session_id` -- the random run_tag can contain "c1"/"c2"
                # and would silently route c2's turns to arabica (same bug class as _sid_is documents)
                "contract": "arabica_coffee" if _sid_is(session_id, "c1") else "soybeans",
                "contracts": ["arabica_coffee"] if _sid_is(session_id, "c1") else ["soybeans"],
                "asof": eff_asof, "structured": {"tldr": f"tldr for {q[:30]}"}, "evidence": [],
                "number_calls": [], "trace": {}}
    return respond


def test_turns_sequential_per_convo_and_no_state_bleed():
    log = []
    rows, harness_out = _run(CONVOS, workers=2, respond_fn=_fake_respond_factory(log),
                             store=ss.InMemoryStore())
    # Unchanged assertion, now self-diagnosing: a convo whose future raises is dropped SILENTLY by
    # eval._drain (it catches the re-raise from `_complete` and only prints `WARN drain convo ...`), so a
    # bare count mismatch hides both which convo vanished and why. Surface the census and the harness's own
    # output in the message.
    assert len(rows) == 5, (
        f"expected 5 rows (c1=3 + c2=2), got {len(rows)}; per-convo census={_census(rows)}; "
        f"harness stdout:\n{harness_out}")
    # per convo, turn order is strictly the scripted order (state dependency respected)
    for cid in ("c1", "c2"):
        qs = [q for sid, q in log if _sid_is(sid, cid)]
        assert qs == [t["q"] for c in CONVOS if c["id"] == cid for t in c["turns"]], (
            f"convo {cid} turn order/attribution wrong; sids seen={sorted({s for s, _ in log})}")
    # distinct session ids per convo -> no cross-convo state bleed
    sids = {sid for sid, _ in log}
    assert len(sids) == 2 and all(_sid_is(s, "c1") ^ _sid_is(s, "c2") for s in sids), f"sids={sorted(sids)}"


def test_mechanics_carry_override_trap_and_resolution():
    log = []
    rows, harness_out = _run(CONVOS, workers=2, respond_fn=_fake_respond_factory(log),
                             store=ss.InMemoryStore())
    by = {(r["convo"], r["turn"]): r["mech"] for r in rows}
    assert len(rows) == 5, (f"census={_census(rows)}; harness stdout:\n{harness_out}")
    assert by[("c1", 0)]["intent_ok"] and by[("c1", 0)]["contract_ok"]
    assert by[("c1", 1)]["carry_contracts_ok"] and by[("c1", 1)]["carry_asof_ok"] and by[("c1", 1)]["resolved_ok"]
    assert by[("c1", 2)]["override_asof_ok"]                     # explicit 2019 as-of won
    assert by[("c2", 1)]["not_known_ok"]                         # the mid-convo PIT trap phrasing detected


def test_convo_history_only_prior_turns_of_same_convo():
    log = []
    rows, _ = _run(CONVOS, workers=1, respond_fn=_fake_respond_factory(log),
                   store=ss.InMemoryStore())
    r_c1t2 = next(r for r in rows if r["convo"] == "c1" and r["turn"] == 2)
    hist = gev._convo_history(rows, r_c1t2)
    assert "how does frost hit arabica?" in hist and "and the convexity?" in hist
    assert "brazil soy" not in hist                              # other convo never leaks into history
    assert "same but as of 2019" not in hist                     # current turn not in its own history


def test_convo_report_renders_mechanics_cache_and_judge():
    log = []
    rows, _ = _run(CONVOS, workers=1, respond_fn=_fake_respond_factory(log),
                   store=ss.InMemoryStore())
    rows[1]["usage"] = {"read": 2000, "write": 0, "input": 500, "output": 100}   # simulate a cache hit
    rows[1]["judge"] = {"usefulness": 4, "convexity": 4, "point_in_time": 5, "grounding": 4,
                        "continuity": 5, "hallucinations": [], "gaps": [], "verdict": "solid follow-up"}
    md = gev.convo_report(rows, model="claude-sonnet-4-6")
    assert "Session mechanics" in md and "carry_asof_ok" in md
    assert "prompt-cache HIT: **1/" in md
    assert "continuity 5" in md.replace("**", "")
    assert "## c1" in md and "## c2" in md


def test_judge_tool_continuity_field_gated():
    assert "continuity" not in gev._judge_tool()["input_schema"]["properties"]
    t = gev._judge_tool(continuity=True)
    assert "continuity" in t["input_schema"]["properties"] and "continuity" in t["input_schema"]["required"]


def test_convo_attribution_survives_a_run_tag_that_contains_a_convo_id(monkeypatch):
    """REGRESSION (the 2026-07-26 flake). run_conversations stamps sids as `eval-{cid}-{uuid4().hex[:6]}`.
    A 6-hex tag contains 'c1' or 'c2' about **3.92%** of the time, and the old substring test
    (`cid in sid`) then attributed BOTH convos to one id -- the scripted-order assert failed with c2's
    questions spliced into c1's list, and the fake routed c2's turns to arabica. Force the collision so the
    bug is deterministic instead of a 1-in-25 surprise; it is a pure-logic defect, unrelated to machine load.
    """
    class _FixedUUID:
        hex = "abc1ef"                                  # contains 'c1' -> poisons 'c2' under substring match

    monkeypatch.setattr("uuid.uuid4", lambda: _FixedUUID())
    log = []
    rows, harness_out = _run(CONVOS, workers=2, respond_fn=_fake_respond_factory(log),
                             store=ss.InMemoryStore())
    sids = sorted({s for s, _ in log})
    assert sids == ["eval-c1-abc1ef", "eval-c2-abc1ef"], sids       # the collision really is in play
    assert "c1" in sids[1], "precondition: the c2 sid must contain 'c1' or this test proves nothing"

    assert len(rows) == 5, f"census={_census(rows)}; harness stdout:\n{harness_out}"
    for cid in ("c1", "c2"):
        qs = [q for sid, q in log if _sid_is(sid, cid)]
        assert qs == [t["q"] for c in CONVOS if c["id"] == cid for t in c["turns"]], f"convo {cid} mis-attributed"
    # the fake's contract routing must not leak either
    by_convo = {r["convo"]: r["out"]["contracts"] for r in rows}
    assert by_convo["c1"] == ["arabica_coffee"] and by_convo["c2"] == ["soybeans"], by_convo
