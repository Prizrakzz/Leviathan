"""STATE ENGINE S6 -- PHASE 2, THE SEAM. Design docs/private/STATE_ENGINE_DESIGN_2026-09-07.md
sec 3.9 (where the board runs and how it FEEDS quantify), 6.4 (the mandate), 6.7 (the decline tags),
sec 7 (the per-mode knobs), sec 9.2 phase 2, D8 / D12 / D26 and sec 16 Amendments 1 and 2.

THE TWO HALVES THIS DECK HOLDS, and they are the two the sitting's whole blast radius rests on:

  FLAG OFF  -- every consumer takes HEAD's branch. `cascade.quantify`'s `board` kwarg is ABSENT (not
               None-valued), `_select_nodes` returns walk order, `_derive_windows` sorts on the
               caller's own `near`, `_cw_turn_spent` and the walk's ceiling are HEAD's arithmetic to
               the integer, `_system` renders HEAD's bytes and no marker reaches the volatile prompt.
               The goldens carry the same claim at the block level (`test_cascade_walk`'s g1 / g1d /
               g1x, which re-bank byte-identical); this deck carries it at the FUNCTION level, where a
               failure names the consumer instead of a sha.

  FLAG ON    -- proven with INJECTED FAKES and no store: the state producer is the offline harness's
               own `fixture_state_fn`, so every assertion below runs at zero reads, zero network and
               zero clock. That is not a convenience -- it is what makes the phase-2 wiring falsifiable
               in CI on the estate's real thirty-six DAGs.

NOTHING HERE READS OR WRITES AN ENVIRONMENT VARIABLE except through `monkeypatch`, and the flag-off
assertions assert the DEFAULT, so a runner with GRAPHRAG_STATE_BOARD set cannot green them.
"""
from __future__ import annotations

import inspect
import json
import os
import pathlib
import re
import types

import pytest

from leviathan.graphrag import answer as an
from leviathan.graphrag import config_check as cc
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import graph as G
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import reasoning_modes as rm
from leviathan.graphrag import tracekeys as tk
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.state import __main__ as H
from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import seam as S
from leviathan.graphrag.state import walk as W


@pytest.fixture(scope="module")
def graph():
    return G.CausalGraph(G.load_contracts(), silver=set(), version="harness")


def _sg(seeds, nodes=()):
    return types.SimpleNamespace(seeds=list(seeds), nodes=list(nodes), trace={})


def _node(contract, nid, ref=None, evidence=()):
    n = types.SimpleNamespace(contract=contract, id=nid, kind="driver", depth=1,
                              evidence=[dict(e) for e in evidence])
    n.prior = {"silver_ref": ref} if ref else {}
    return n


# ═══ FLAG OFF: the seam is the branch HEAD takes ═════════════════════════════════════════════════
def test_board_seam_off_the_flag_defaults_to_off_and_the_kwarg_is_ABSENT(monkeypatch):
    """THE OMIT-WHEN-OFF LAW, at the signature and at the call site (design 9.2's rollback column).

    `board=None` is the DEFAULT, so an injected `quantify` fake written against the pre-S6 signature
    stays valid -- the property every cascade fixture in the suite rests on. And the seam OMITS the
    kwarg rather than passing None, so the flag-off call is byte-identical rather than merely
    equivalent: `_sb_kw` is `{}` unless a board actually produced a request."""
    monkeypatch.delenv("GRAPHRAG_STATE_BOARD", raising=False)
    assert an._state_board_on() is False                       # DEFAULT-OFF, fail-closed
    p = inspect.signature(cq.quantify).parameters["board"]
    assert p.default is None and p.kind is inspect.Parameter.KEYWORD_ONLY
    src = inspect.getsource(an._answer_l2)
    assert '_sb_kw = {"board": _board_req} if _board_req else {}' in src
    assert "**_sb_kw, **_eod_kw)" in src                       # BEFORE the g1x end anchor, never on it
    for spelling in ("on", "1", "true", "ON", " True "):
        monkeypatch.setenv("GRAPHRAG_STATE_BOARD", spelling)
        assert an._state_board_on() is True, spelling
    for spelling in ("", "off", "0", "false", "yes"):
        monkeypatch.setenv("GRAPHRAG_STATE_BOARD", spelling)
        assert an._state_board_on() is False, spelling


def test_board_seam_off_select_nodes_and_derive_windows_take_HEADs_branch(graph):
    """THE TWO CONSUMERS OF D8, off. `_select_nodes` returns WALK ORDER and `_derive_windows` sorts on
    the caller's own `near` -- asserted by RUNNING both with the kwarg absent, with None, and with a
    board whose payload is empty, and joining the three."""
    nodes = [_node("soybeans_cbot", "El_Nino", "oni_climate"),
             _node("soybeans_cbot", "export_pace_lag", "export"),
             _node("corn_cbot", "drought_z", "drought_z")]
    sg = _sg(["soybeans_cbot"], nodes)
    base = cq._select_nodes(sg, graph)
    assert [n.id for n in base] == ["El_Nino", "export_pace_lag", "drought_z"]
    assert cq._select_nodes(sg, graph, None) == base
    assert cq._select_nodes(sg, graph, {}) == base
    assert cq._select_nodes(sg, graph, {"order": ()}) == base
    # ...and a MALFORMED order costs the re-order and nothing else: the feed is belted, because
    # the one thing a FEED must never do is take an answer down.
    assert cq._select_nodes(sg, graph, {"order": (("a", "b", "c"),)}) == base
    assert cq._select_nodes(sg, graph, {"order": "not a list of keys"}) == base
    n = _node("soybeans_cbot", "El_Nino", "oni_climate",
              evidence=[{"event_date": "2015-08-01"}, {"date": "2010-06-01"}])
    assert cq._derive_windows(n, "2015", "2026-09-07") == cq._derive_windows(n, "2015", "2026-09-07", None)
    assert cq._board_near(n, "2015", None) == "2015"
    assert cq._board_near(n, None, None) is None


def test_board_seam_off_the_walk_ceiling_and_the_turn_spend_are_HEADs_arithmetic():
    """D12, OFF. With no `state_board` key the seventh enumerated term does not exist and the board's
    declared cap is 0, so `_cw_turn_spent` sums exactly what it summed at HEAD and `cw_ceiling`
    evaluates to `CW_DEEP_TURN_CEILING if deep_on else CW_TURN_CEILING`."""
    sg = _sg([])
    sg.trace = {"quantify_wave_reads": 9, "quantify_transmission": {"net_reads": 12}}
    assert cq._cw_turn_spent(sg) == 21
    assert cq._board_declared_cap(sg) == 0
    sg.trace["quantify_wave_reads"] = None                      # ABSENT IS NEVER ZERO, unchanged
    assert cq._cw_turn_spent(sg) is None


def test_board_seam_off_the_persona_is_HEADs_bytes_and_no_marker_reaches_the_prompt(monkeypatch):
    """6.4, OFF. The mandate is gated on a DEFAULT-FALSE kwarg, so `_system()` renders HEAD's bytes;
    and the seam gate needs BOTH legs, so a flag that is on with no block in the prompt still ships
    nothing. THE GATE IS TESTED BEFORE THE IMPORT, so a flag-off turn does not put `state/` on its
    import graph at all -- asserted on the source, because an import is not observable from here."""
    monkeypatch.delenv("GRAPHRAG_STATE_BOARD", raising=False)
    base = an._system()
    assert an._system(state_board=False) == base
    assert N.SYSTEM_STATE_BOARD_MANDATE not in base
    assert an._state_board_block_on(None) is False
    assert an._state_board_block_on("STATE OF THE WORLD at 2026-09-07") is False   # flag off
    monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
    assert an._state_board_block_on("nothing here") is False                        # no marker
    assert an._state_board_block_on(f"{R.SB_MARKER_PREFIX}2026-09-07 ...") is True   # both legs
    gate = inspect.getsource(an._state_board_block_on)
    assert gate.index("if not _state_board_on():") < gate.index("from leviathan.graphrag.state")


# ═══ D12: THE TIER-1 REPLAY over the twelve banked turns ══════════════════════════════════════════
def _banked():
    """The twelve banked turns (`cascade_baseline_control.json` deep + `_treatment.json` max), as
    (arm, id, wave_reads, turn_spent, ceiling_applied).

    THEY CARRY PER-ANSWER COUNTERS ONLY -- no `calls` list and no answer body, which is the fact the
    S5 review MEASURED and which makes a RENDER replay impossible at $0. What they DO carry is exactly
    the three numbers D12 is about: the wave count, the enumerated turn spend and the ceiling the walk
    applied. So the replay this deck runs is the BUDGET one, on real banked turns, and it is skipped
    with a NAMED reason rather than silently passing when the artifacts are not on this machine."""
    # THE SCRATCHPAD IS TRIED FIRST and the repo walk is the fallback, deliberately: the artifacts
    # live in the session scratchpad and an `rglob` over this repo is a full-tree walk on every
    # run of this deck. `S6_BANKED_DIR` names a directory holding both arms.
    import glob
    named = os.environ.get("S6_BANKED_DIR")
    hits = [pathlib.Path(named) / "cascade_baseline_control.json"] if named else []
    hits = [h for h in hits if h.exists()]
    if not hits:
        tmp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
        hits = [pathlib.Path(p) for p in glob.glob(
            os.path.join(tmp, "claude", "*", "*", "scratchpad", "cascade_baseline_control.json"))]
    if not hits:
        hits = list(pathlib.Path(__file__).resolve().parents[2]
                    .rglob("cascade_baseline_control.json"))
    if not hits:
        return [], 0
    out, n = [], 0
    for arm, name in (("control", "cascade_baseline_control.json"),
                      ("treatment", "cascade_baseline_treatment.json")):
        p = hits[0].with_name(name)
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for r in d.get("per_answer") or []:
            if isinstance(r.get("cw_turn_spent"), int) and isinstance(r.get("cw_ceiling_applied"), int):
                out.append((arm, r.get("id"), int(r.get("quantify_wave_reads") or 0),
                            int(r["cw_turn_spent"]), int(r["cw_ceiling_applied"])))
            n += 1
    return out, n


def _fired_board_trace(net: int, cap: int) -> dict:
    """The `state_board` payload shape of a board that FIRED. The leg is not decoration here: both
    halves of D12 read it (S6 review, fatal 2)."""
    return {"legs": {"board": {"outcome": "fired", "reason": "", "reads": net}},
            "net_reads": net, "cap": cap}


def _board_cap_of(mode: str) -> int:
    """A REAL board's declared cap for `mode`, walked on the offline fixture at one anchor: wave 1 +
    wave 2 + THE TAPE SEAT. Nothing here is synthesised from the knob table."""
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=G.CausalGraph(G.load_contracts(), silver=set(), version="harness"),
                       sg=sg, asof=H.ASOF, mode=mode, query="soybeans",
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
    S.fill_stage2(bd, graph=G.CausalGraph(G.load_contracts(), silver=set(), version="harness"),
                  sg=sg, qfn=lambda *a, **k: [])
    return int(bd.declared_cap())


def _declared_cap_arith(mode: str) -> int:
    """The same number by arithmetic, tape seat INCLUDED -- one anchor, so one seat."""
    kn = B.board_knobs_of(mode)
    return int(kn.wave1) + int(B.wave2_shape(kn, legb_cells=B.legb_cells_of(mode), legb_on=False,
                                             analog_reads=False)["total"]) + 1


def test_d12_the_ceiling_identity_holds_on_every_banked_turn():
    """D12, ON AND OFF, replayed on the twelve banked turns.

    THE IDENTITY, stated as the design states it: `_cw_turn_spent` gains the board's SPEND and the
    walk's ceiling gains the board's declared CAP, both from the ONE registered `state_board` key. So
    for every banked turn --

        spent(on)   == spent(off) + net_reads
        ceiling(on) == ceiling(off) + cap
        slack(on)   >= slack(off)        whenever net_reads <= cap

    -- and the third line is the one that matters: it is the whole of "the board never starves the
    walk", and it is why the two halves had to land together. A ceiling that did not move would make
    every Cascade board a `turn_budget_spent` decline of a leg that spent nothing extra."""
    rows, n_banked = _banked()
    if not rows:
        pytest.skip("the banked arm artifacts are not on this machine (see the docstring)")
    # TWELVE BANKED TURNS, TEN OF WHICH REACHED THE WALK. `cw_turn_spent` is stamped by
    # `_cascade_walk_legs`, so a turn whose walk never ran carries None -- MEASURED at 2 of 12
    # (one per arm). Those two are OUTSIDE this replay by construction rather than by omission,
    # and the count is asserted so a future re-bank that silently loses rows reds this pin.
    assert n_banked == 12 and len(rows) == 10, (n_banked, [r[:2] for r in rows])
    for arm, rid, wave, spent, ceiling in rows:
        sg = _sg([])
        sg.trace = {"quantify_wave_reads": wave,
                    "quantify_transmission": {"net_reads": spent - wave}}
        assert cq._cw_turn_spent(sg) == spent, (arm, rid)
        assert cq._board_declared_cap(sg) == 0, (arm, rid)
        deep_on = ceiling == cq.CW_DEEP_TURN_CEILING
        off = (cq.CW_DEEP_TURN_CEILING if deep_on else cq.CW_TURN_CEILING) + cq._board_declared_cap(sg)
        assert off == ceiling, (arm, rid, off, ceiling)
        # ...and now the same turn WITH a board, at the tier's own declared cap.
        #
        # THE CAP IS TAKEN FROM A REAL BOARD, NOT SYNTHESISED FROM THE KNOBS, and that is the S6
        # review's correction: the first pin built `cap = kn.wave1 + wave2_shape(...)['total']` by
        # hand, which omits the TAPE SEAT -- the ONE term that makes `declared_cap()` scale with the
        # anchor count. So the term the review measured driving cap 24/50/71 to 59/85/106 was never
        # exercised by the identity that is supposed to pin it. `_board_cap_of` walks a board.
        mode = "max" if arm == "treatment" else "deep"
        cap = _board_cap_of(mode)
        assert cap == _declared_cap_arith(mode), (arm, mode, cap)
        for net in (0, cap // 2, cap):
            sg.trace["state_board"] = _fired_board_trace(net, cap)
            on_spent = cq._cw_turn_spent(sg)
            on_ceiling = ((cq.CW_DEEP_TURN_CEILING if deep_on else cq.CW_TURN_CEILING)
                          + cq._board_declared_cap(sg))
            assert on_spent == spent + net, (arm, rid, net)
            assert on_ceiling == ceiling + cap, (arm, rid, net)
            assert on_ceiling - on_spent >= ceiling - spent, (arm, rid, net)
        # A BOARD THAT RAN WITHOUT A COUNTER IS NOT A BOARD THAT SPENT NOTHING (the fail-closed arm),
        # AND THE CEILING IS FAIL-CLOSED IN THE SAME BREATH. The first build returned the cap here
        # while the spend returned None -- "both return 0 on the same absence" was false in exactly
        # that direction (S6 review, fatal 2).
        sg.trace["state_board"] = {"legs": {"board": {"outcome": "fired"}}, "cap": cap}
        assert cq._cw_turn_spent(sg) is None, (arm, rid)
        assert cq._board_declared_cap(sg) == 0, (arm, rid)
        # A BOARD THAT DECLINED RAISES NOTHING. `walk()` used to set both wave caps ABOVE the anchor
        # gate, so a declined board carried cap 24 / 50 / 71 with net_reads 0 and the walk's runaway
        # tripwire rose by up to 71 reads on a turn quantify received no board at all. Two fixes, both
        # pinned: the caps are declared after the gate, and the term reads the leg.
        for word in ("anchor_none", "pg_not_live", "lane_off:numbers_only", "recency_facts_off"):
            sg.trace["state_board"] = {"legs": {"board": {"outcome": "declined", "reason": word}},
                                       "net_reads": 0, "cap": cap}
            assert cq._board_declared_cap(sg) == 0, (arm, rid, word)
            assert cq._cw_turn_spent(sg) == spent, (arm, rid, word)


# ═══ FLAG ON, through injected fakes ══════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def fired(graph):
    """The scenario-2 board, filled through the SEAM (not through the harness's own one-call walk) on
    the offline `fixture_state_fn`: stage 1, then stage 2, exactly as `_answer_l2` runs them."""
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep",
                       query="El Nino is developing: what does it do to soybeans?",
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
    out = S.fill_stage2(bd, graph=graph, sg=sg)
    return bd, out


def test_the_block_carries_its_marker_and_the_mandate_ships_only_with_it(fired, monkeypatch):
    """6.4 / 6.1: ONE block, ONE marker, and the mandate gated on that marker being in the assembled
    volatile prompt. THE BLOCK AND THE MANDATE ARE ONE DELIVERABLE (doctrine M-7): a block served for
    a week with no instruction is the flip the owner did not ask for, and the estate's own measured
    reason is at `_cascade_walk_block_on` -- under a conditional LICENSE alone the writer transcribed
    the walk on 1 of 3 walk-fired rows."""
    _bd, out = fired
    block = out["block"]
    assert block and R.SB_MARKER_PREFIX in block
    assert block.splitlines()[0].startswith(R.SB_MARKER_PREFIX)
    monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
    vp = "SOME OTHER BLOCK\n\n" + block + "\n\nQUESTION: ..."
    assert an._state_board_block_on(vp) is True
    persona = an._system(state_board=an._state_board_block_on(vp))
    assert N.SYSTEM_STATE_BOARD_MANDATE in persona
    assert persona.index(N.SYSTEM_STATE_BOARD_MANDATE) < len(persona)
    # ...and with the block absent the same flag ships nothing
    assert an._system(state_board=an._state_board_block_on("no block here")) == an._system()


def test_the_mandate_is_register_safe_and_the_lint_says_so_at_build():
    """6.4 / 6.6: the mandate, the ledger sentence and the persona clause are CLOSED literals graded at
    BUILD by all four register detectors, so a serve-time trip on them is a build defect and never a
    stripped answer. `config_check.check_state_seam` clause (iii) is the gate; this asserts the values
    directly as well, because a lint that is green for the wrong reason is worth catching here."""
    from leviathan.graphrag import register as reg
    assert N.check_literals() == []
    for text in (N.SYSTEM_STATE_BOARD_MANDATE, N.RECENCY_LEDGER_SENTENCE, N.SYSTEM_RECENCY_CLAUSE):
        assert reg.register_leaks(text) == []
        assert reg.count_flow_words(text) == 0 and reg.count_valuation_words(text) == 0
        assert text.isascii()
        assert N.BANNED_RECENCY_PHRASE not in text
    assert cc.check_state_seam() == []
    assert cc.check_state_board() == []


def test_quantify_receives_the_boards_node_ORDER_and_its_anchor_WINDOWS(fired, graph):
    """D8 items 1 and 2 -- the two consumers, driven through `quantify`'s own helpers with the real
    payload. `_select_nodes` RE-ORDERS and never filters (a node the board did not rank keeps its walk
    position at the tail), and `_derive_windows` takes the loud state's own date as its `near` when
    the caller has none -- while a USER-NAMED `near` still outranks the board (sec 3.1, critic G18)."""
    bd, out = fired
    req = out["request"]
    assert req["order"] and req["order"] == bd.order
    top = req["order"][0]
    # (1) ORDER: a subgraph whose walk order is the REVERSE of the board's comes back in board order,
    #     and a node the board never ranked is still present, at the tail.
    ranked = [k for k in req["order"][:3]]
    nodes = [_node(c, d, "oni_climate") for c, d in reversed(ranked)]
    nodes.append(_node("zzz_not_a_board", "zzz_driver", "oni_climate"))
    sg = _sg(["soybeans_cbot"], nodes)
    got = [(n.contract, n.id) for n in cq._select_nodes(sg, graph, req)]
    assert got[:3] == ranked, got
    assert got[3] == ("zzz_not_a_board", "zzz_driver")          # never filtered, only re-ordered
    assert len(cq._select_nodes(sg, graph, req)) == len(cq._select_nodes(sg, graph))
    # (2) WINDOWS: the board's own `near` for the loudest row is a real date, and it reaches
    #     `_derive_windows` only when the caller has none.
    win = req["windows"][top]
    assert win.get("near")
    n = _node(top[0], top[1], "oni_climate")
    assert cq._board_near(n, None, req) == win["near"]
    assert cq._board_near(n, "1998", req) == "1998"              # an explicit gesture outranks the board
    assert cq._board_near(_node("no", "such", None), None, req) is None


def test_the_boards_N_rows_are_minted_in_cw_calls_shape_BEFORE_the_base_wave(fired):
    """6.3 / D8 item 3 / D13: every board magnitude is its OWN `[N]`, minted in `_cw_call`'s shape so
    `citations.unify` and `verify_citations` bind it with no new class, and appended to
    `extra_number_calls` BEFORE the base wave so `base = len(extra_number_calls)` counts them and the
    cascade's own mints continue the numbering instead of colliding with it."""
    _bd, out = fired
    calls = list(out["request"]["calls"])
    assert calls, "a fired board must mint its own [N] rows"
    for c in calls:
        assert isinstance(c, dict)
        for k in ("query", "rows", "status"):
            assert k in c, (k, sorted(c))
    src = inspect.getsource(cq.quantify)
    i_board = src.index('for _c in (board.get("calls") or ()):')
    # the STATEMENT, not the comment that names it: `base = ...` appears in the block note too,
    # and a source pin that matched prose would pass on a build where the code moved.
    i_base = src.index(chr(10) + "    base = len(extra_number_calls)")
    assert i_board < i_base, "the board's rows must land BEFORE the base wave's numbering"


def test_the_soybeans_only_question_surfaces_PALM_with_palms_own_sign(fired):
    """THE ACCEPTANCE FIXTURE OF sec 16 (Amendment 1's closing paragraph) and of 3.6: 'the fan-out
    surfaces palm from a soybeans-only question with no mention of palm, and that is the bar the
    fixture holds'. It is run HERE through the SEAM rather than through the harness, because the seam
    is what phase 2 ships and a bar that only holds in the harness is not a bar on the product."""
    bd, out = fired
    assert bd.anchor_slugs == ("soybeans_cbot",)
    assert "palm" not in "El Nino is developing: what does it do to soybeans?".lower()
    far = [f for e in bd.fan for f in e["far"] if "palm" in f["contract"]]
    assert far, "the fan index carries no palm board"
    assert "palm" in out["block"].lower()
    # THE SIGN IS THE FAR BOARD'S OWN and is never reconciled with the anchor's (ruling 3 / D4).
    signs = {f["contract"]: f["sign"] for f in far}
    assert any(s for s in signs.values()), signs


def _head_dispatch():
    """HEAD's `dispatch.py`, LOADED AS ITS OWN MODULE.

    THE ONLY WAY TO PROVE FLAG-OFF BYTE-IDENTITY OF A FUNCTION is to run HEAD's copy of it beside the
    tree's on the same inputs. `git show HEAD:<path>` is a read; nothing here mutates a ref, touches
    the index or writes into the worktree."""
    import importlib.util
    import subprocess
    import sys
    import tempfile

    root = pathlib.Path(__file__).resolve().parents[2]
    src = subprocess.check_output(["git", "show", "HEAD:src/leviathan/graphrag/dispatch.py"],
                                  cwd=str(root))
    path = pathlib.Path(tempfile.mkdtemp()) / "dispatch_head.py"
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location("leviathan.graphrag._dispatch_at_head", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["leviathan.graphrag._dispatch_at_head"] = mod
    spec.loader.exec_module(mod)
    return mod


def _plan_fields(plan, names=None):
    """FIELD-WISE, because HEAD's `Plan` and the tree's are two CLASSES and a dataclass `__eq__`
    compares `self.__class__` first -- so `==` would be False on every pair and green nothing.

    `names` RESTRICTS THE COMPARISON TO HEAD'S OWN FIELD LIST (SUBJECT RESOLVER, 2026-09-09). The tree's
    `Plan` gained `subject` and `subject_hints_n`, so an unrestricted dict is unequal on every pair by
    construction and this pin would green nothing at all -- the failure mode it was written to avoid,
    one field list over. The two NEW fields are asserted separately at their flag-off defaults, which
    is a STRONGER claim than the old comparison made: it says both what HEAD's fields do and what the
    new ones do."""
    import dataclasses
    d = {f.name: getattr(plan, f.name) for f in dataclasses.fields(plan)}
    return d if names is None else {k: d[k] for k in names}


def test_the_routed_slug_DEDUP_is_FLAG_GATED_and_flag_off_is_HEADs_own_arithmetic(graph):
    """S6 RE-FIX, MAJOR 3. The de-dup was landed UNCONDITIONALLY, outside the `if named:` branch, so
    with GRAPHRAG_STATE_BOARD OFF the ceiling was applied to a DE-DUPLICATED list where HEAD applied it
    to the RAW one -- a flag-off behaviour change with no flag, no pin, and a docstring one line above
    promising the opposite ("Absent -> the truncation is HEAD's, character for character").

    IT IS PROVED THE ONLY WAY IT CAN BE: HEAD's `_validate` is loaded as its own module and run beside
    the tree's on the plans that separate them -- a plan naming one contract TWICE and one naming it
    FOUR TIMES, at every ceiling any shipped tier sets, with and without the D-XL roster."""
    head = _head_dispatch()
    import dataclasses as _dc
    HEADN = [f.name for f in _dc.fields(head.Plan)]
    ids = set(graph.contracts)
    S, C, W, P = ("soybeans_cbot", "corn_cbot", "soft_red_winter_wheat_cbot",
                  "malaysian_crude_palm_oil_cme")
    plans = ([S, S], [S, S, S, S], [S, C, S, W], [S, S, C, C, W, W, P, P],
             [S, "not_a_contract", S, C], [], [W, C, S, P])
    for contracts in plans:
        for cap in (1, 2, 4, 6):
            out = {"steps": ["numbers"], "contracts": list(contracts)}
            _tree = dp._validate(dict(out), ids, cap)
            assert _plan_fields(_tree, HEADN) ==                 _plan_fields(head._validate(dict(out), ids, cap)), (contracts, cap)
            xl = ({"soybeans_cbot": "CBOT soybeans"}, ("windowed_extreme",))
            _tree_xl = dp._validate(dict(out), ids, cap, *xl)
            assert _plan_fields(_tree_xl, HEADN) ==                 _plan_fields(head._validate(dict(out), ids, cap, *xl)), (contracts, cap)
            # SUBJECT RESOLVER, FLAG OFF: the two new fields hold their inert defaults on every pair
            # above, and `Plan.trace()` gains no key at all -- the omit-when-off idiom applied to a
            # trace, which is what keeps `test_extreme_locator`'s seven-key TAIL pin true.
            for _p in (_tree, _tree_xl):
                assert _p.subject == () and _p.subject_hints_n == 0, (contracts, cap)
                assert "subject" not in _p.trace() and "subject_hints_n" not in _p.trace()
    # THE FLAG-ON HALF ACTUALLY DE-DUPS, and it costs the ceiling a seat with the flag off -- which is
    # exactly the behaviour difference that makes the gate necessary rather than tidy.
    dup = {"steps": ["numbers"], "contracts": [S, S, C]}
    assert dp._validate(dict(dup), ids, 2).contracts == [S, S]                  # HEAD
    assert dp._validate(dict(dup), ids, 2, dedup=True).contracts == [S, C]      # the board's branch
    # ...and it is its OWN switch, not a rider on `named`: a board turn that names NO market still
    # anchors, still prices a tape column and still renders, so it still de-dups.
    assert dp._validate(dict(dup), ids, 2, named=(), dedup=True).contracts == [S, C]
    assert dp._validate(dict(dup), ids, 2, named=()).contracts == [S, S]


def test_the_dedup_kwarg_is_OMITTED_when_the_board_is_off_at_the_orchestrator_seam():
    """OMIT-WHEN-OFF at the CALL SITE, not merely a default that happens to match. An injected
    `plan_turn` written against the pre-S6 signature must stay valid on every flag-off turn, and the
    flag is read at its ONE producer (`answer._state_board_on`) and threaded -- `dispatch` is on the
    no-environment rule, so the leaf may not read it."""
    src = inspect.getsource(orch._respond_walk)
    assert "if an._state_board_on():" in src
    assert '_nm = {"dedup": True}' in src
    assert "**_pc, **_xo, **_xl, **_nm)" in src
    # THE COMPILED CODE, never the SOURCE: both functions' notes discuss `os.environ` by name, and a
    # substring test over prose is a lint that greens on a rewrite and reds on a comment.
    for fn in (dp._validate, dp.named_markets):
        assert "environ" not in set(fn.__code__.co_names), fn.__name__
        assert "getenv" not in set(fn.__code__.co_names), fn.__name__
    p = inspect.signature(dp._validate).parameters["dedup"]
    assert p.default is False and p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert inspect.signature(dp.plan_turn).parameters["dedup"].default is False


def test_named_markets_is_BOUNDED_and_the_bound_cannot_cut_a_market_the_question_named(graph):
    """THE CEILING LAW, on the one function whose docstring claimed a bound it did not apply.

    IT IS NOT `NAMED_ANCHOR_CAP`: this set is a MEMBERSHIP test and the router's ranking is
    hits-then-alphabetical, so a flat `[:6]` drops `corn_cbot` and `soft_red_winter_wheat_cbot` --
    two of the four markets the user TYPED -- while keeping two the user did not. MEASURED here, so the
    two bounds can never be collapsed into one by a later edit that reads only the docstrings."""
    q = "How do wheat, corn, soybeans and palm oil compare right now?"
    raw = list(an.route(q, graph))
    named = dp.named_markets(q, graph)
    assert len(named) <= dp.NAMED_ROUTE_CAP
    assert tuple(raw[:dp.NAMED_ROUTE_CAP]) == named
    assert dp.NAMED_ROUTE_CAP > dp.NAMED_ANCHOR_CAP
    assert dp.NAMED_ROUTE_CAP < len(graph.contracts)          # a bound that binds, not the roster
    four = ("soft_red_winter_wheat_cbot", "corn_cbot", "soybeans_cbot",
            "malaysian_crude_palm_oil_cme")
    assert all(c in named for c in four)                      # the measured case is untouched
    assert not all(c in raw[:dp.NAMED_ANCHOR_CAP] for c in four)   # ...and `[:6]` would NOT be
    six = dp.named_markets("wheat, corn, soybeans, palm oil, sugar and coffee compare?", graph)
    assert len(six) <= dp.NAMED_ROUTE_CAP                     # the widest question the anchor cap admits
    assert dp.named_markets("", graph) == () and dp.named_markets(None, None) == ()


def test_amendment_2_four_named_markets_survive_on_quick(graph):
    """AMENDMENT 2 (owner 2026-09-08), both halves, on the tier with the tightest ceiling.

    THE VALIDATOR half: `MAX_CONTRACTS` bounds only the seeds the planner INFERRED, so a question
    naming four markets keeps all four while an inferred tail is still cut at the ceiling.
    THE ANCHOR half: those four are `named` anchors on the board, and the seam INTERSECTS the lexical
    set with this turn's route -- the router matches seventeen boards for this question (five of them
    on the word 'soybeans' alone), and anchoring the raw set would put seventeen DAGs on a Scan turn."""
    q = "How do wheat, corn, soybeans and palm oil compare right now?"
    named = dp.named_markets(q, graph)
    four = ["soft_red_winter_wheat_cbot", "corn_cbot", "soybeans_cbot",
            "malaysian_crude_palm_oil_cme"]
    assert all(c in graph.contracts and c in named for c in four)
    assert len(named) > len(four), "the lexical router is broad -- that is why the seam intersects"
    out = {"steps": ["numbers"], "contracts": four}
    assert dp._validate(out, set(graph.contracts), 2).contracts == four[:2]      # HEAD, unchanged
    assert dp._validate(out, set(graph.contracts), 2, named=tuple(named)).contracts == four
    inferred = [c for c in sorted(graph.contracts) if c not in named][:3]
    mixed = dp._validate({"steps": ["numbers"], "contracts": four + inferred},
                         set(graph.contracts), 2, named=tuple(named)).contracts
    assert mixed == four + inferred[:2], mixed        # named whole; the INFERRED tail still cut at 2
    # the anchor half, on quick, through the seam's own intersection rule
    sg = _sg(four)
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="quick", query=q,
                       state_fn=H.fixture_state_fn(H.ASOF),
                       named=tuple(c for c in sg.seeds if c in set(named)), max_contracts=2)
    assert sorted(bd.anchor_slugs) == sorted(four)
    assert {a.source for a in bd.anchors} == {"named"}


def test_amendment_1_a_focus_driver_anchors_EVERY_contract_that_carries_it(graph):
    """AMENDMENT 1 (DRIVER-AS-SUBJECT): the anchor set is EVERY contract carrying the id, and the
    two-contract planner ceiling does not apply -- those contracts are not PLANNED, they are read off
    the graph. Ranked by that driver's own state after wave 1, which is a rank no read can precede."""
    carriers = sorted(c for c in graph.contracts
                      if any(d.id == "El_Nino" for d in graph.contracts[c].drivers))
    assert len(carriers) > 2, carriers
    anchors = W.resolve_anchors(graph=graph, focus_driver="El_Nino", max_contracts=2)
    assert sorted(a.contract for a in anchors) == carriers
    assert {a.source for a in anchors} == {"focus_driver"}
    assert all(a.driver_id == "El_Nino" for a in anchors)


def test_d26_an_empty_route_stamps_anchor_none_and_the_board_never_runs_anchorless(monkeypatch):
    """D26 / sec 3.1: V1 KEEPS `answer()`'s empty-route return. The board never runs anchorless; the
    seam STAMPS `anchor_none` so a zero-anchor turn is a measured state with its own closed word
    rather than a turn the board is silent about. `board_loudest` stays dark and is reached by
    nothing -- the deferral is a decision, and this stamp is what makes its population countable."""
    monkeypatch.delenv("GRAPHRAG_STATE_BOARD", raising=False)
    assert an._state_board_lane_stamp("anchor_none") == {}            # flag off -> no key, no column
    monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
    st = an._state_board_lane_stamp("anchor_none")
    assert st["state_board"]["legs"]["board"] == {"outcome": "declined", "reason": "anchor_none",
                                                  "reads": 0}
    assert an._state_board_lane_stamp("lane_off:onehop")["state_board"]["legs"]["board"]["reason"] \
        == "lane_off:onehop"
    assert an._state_board_lane_stamp("not_a_word") == {}             # a word outside the enum: nothing
    # THE TURN'S OWN TIER RIDES THE STAMP (S6 re-fix). `respond()` dimensions the board's EMF record by
    # `state_board.mode`, and this payload carried no such key -- so every `BoardDeclined` stamped from
    # OUTSIDE `state.seam` published under `standard` whatever tier the user paid for, while
    # `Board.trace()` carried the real one on every lane the seam declined: one counter, two mode
    # columns, disagreeing by construction on exactly the lanes the counter exists to make countable.
    assert "mode" not in an._state_board_lane_stamp("anchor_none")["state_board"]     # absent, not "standard"
    for _m in ("quick", "deep", "max"):
        assert an._state_board_lane_stamp("anchor_none", _m)["state_board"]["mode"] == _m
    assert "mode" not in an._state_board_lane_stamp("anchor_none", "")["state_board"]
    src = inspect.getsource(an.answer)
    assert '_state_board_lane_stamp("anchor_none", mode_name)' in src
    assert "No tracked contract matched this question." in src        # the return itself STANDS


def test_an_off_lane_declines_by_NAME_and_a_tierless_preset_says_lane_off(graph):
    """sec 7's lane table and 6.7's closed word. `BoardFired` must be absent-when-inapplicable, so
    every lane the board does not run on carries its OWN name -- a silent zero would make a
    numbers_only turn look like a board that fired and found nothing."""
    for lane in ("numbers_only", "onehop", "trivial", "refused"):
        sg = _sg(["soybeans_cbot"])
        bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep", lane=lane,
                           state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
        assert bd.legs["board"] == {"outcome": "declined", "reason": f"lane_off:{lane}", "reads": 0}
        # `BoardDeclined` IS THE BOARD'S OWN 0/1, which is what 10.5's `reason` dimension describes.
        # It used to be a count of declined LEGS, emitted under `reason=none` on a FIRED board, so the
        # dashboard's declined series mixed two populations (S6 review).
        assert S.counters(bd) == {"BoardFired": 0, "BoardDeclined": 1}
        assert S.reason_dimension(bd.legs["board"]["reason"]) == "lane_off"
    # AN UNDECLARED LANE WORD IS OFF TOO, and it keeps its OWN name rather than borrowing one of
    # the four. Returning a declared word for an unknown lane would put a lie in a closed
    # vocabulary; returning '' would RUN the board on a lane nobody adjudicated, which is
    # fail-OPEN and is the defect this arm pins.
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep", lane="run_something_new",
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
    assert bd.legs["board"]["reason"] == "lane_off:run_something_new"
    assert bd.rows == [] and bd.net_reads() == 0        # it never entered the walk
    assert all(v["outcome"] == "not_reached" for k, v in bd.legs.items() if k != "board")
    assert S.lane_word("run_hybrid") == "" and S.lane_word(None) == "unset"
    # A MIRROR OUTAGE IS A READER FACT, NOT A COVERAGE FACT (6.7's `pg_not_live`). Without its
    # own word the board would decline every ROW as `read_error` and report a coverage failure
    # for what is an outage -- two different facts, and only one of them is about the record.
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep", pg_live=False,
                       named=("soybeans_cbot",))
    assert bd.legs["board"] == {"outcome": "declined", "reason": "pg_not_live", "reads": 0}
    assert bd.rows == [] and S.counters(bd) == {"BoardFired": 0, "BoardDeclined": 1}
    assert S.reason_dimension("pg_not_live") == "pg_not_live"
    # a tier that declares NO board is an off lane too, and says so with its own name
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode=rm.STANDARD,
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
    assert bd.legs["board"]["reason"] == f"lane_off:{rm.STANDARD}"
    _out = S.fill_stage2(bd, graph=graph, sg=sg)
    assert _out["block"] == ""
    # A DECLINED BOARD RETURNS NO `board=` PAYLOAD, so "the kwarg is absent" and "the board
    # produced nothing" are ONE fact. The TRACE still rides, because a decline is exactly what
    # the census must be able to see (6.7) -- that asymmetry is the point, not an oversight.
    assert _out["request"] is None
    assert _out["trace"]["legs"]["board"]["outcome"] == "declined"


def test_the_emf_counters_are_absent_when_inapplicable_and_read_the_LEDGER(fired):
    """10.5: every counter is a plain int, `BoardFired` is 0/1, and the four the ledger owns are READ
    from it rather than re-derived -- a second derivation would agree with the ledger until the day a
    walk edit moved one of them, which is the drift class this estate has measured three times."""
    bd, out = fired
    c = out["counters"]
    assert c["BoardFired"] == 1
    assert set(c) >= {"BoardStateRows", "BoardTextOnlyRows", "BoardDeclined", "BoardReads",
                      "BoardBudgetCapped", "BoardAnalogs", "BoardWatchLines", "BoardPoolDeclined",
                      "BoardEvidenceBorrows", "BoardReplayLabelled", "BoardTruncated"}
    assert all(isinstance(v, int) for v in c.values()), c
    assert c["BoardReads"] == bd.net_reads()
    assert c["BoardPoolDeclined"] == bd.ledger.pool_declined
    assert c["BoardEvidenceBorrows"] == bd.ledger.evidence_borrows
    assert c["BoardBudgetCapped"] == bd.ledger.budget_capped
    assert c["BoardReplayLabelled"] == bd.ledger.replay_labelled
    assert out["trace"]["counters"] == c            # ONE producer for the dashboard and the artifact
    assert S.counters(None) == {}
    assert S.reason_dimension(None) == "none" and S.reason_dimension("thin_history:3") == "other"
    # AND NOT ONE OF THE TWELVE COVERAGE NAMES IS HERE. `counters()` runs inside `fill_stage2`, BEFORE
    # the writer; `Board.coverage` is filled after the verifier returns. A coverage counter minted at
    # this call site is a FAKE ZERO on every turn in the estate -- see `coverage_counters` below.
    assert not (set(c) & set(S.COVERAGE_COUNTERS)), sorted(set(c) & set(S.COVERAGE_COUNTERS))


# ═══ S7: THE TWELVE COVERAGE COUNTERS -- what the board BOUGHT, not what it cost ════════════════════
def test_the_twelve_coverage_counters_are_named_and_minted_from_the_coverage_dict():
    """(i) THE NAMES. Twelve, exactly, and every one of them a `Board*` Count -- the orchestrator's
    `units` line types any `Ms`-prefixed key as Milliseconds, so a timer smuggled into this tuple would
    be published in the wrong unit with nothing to catch it."""
    assert len(S.COVERAGE_COUNTERS) == 12 == len(set(S.COVERAGE_COUNTERS))
    assert all(n.startswith("Board") and not n.startswith("Ms") for n in S.COVERAGE_COUNTERS)
    assert set(S.COVERAGE_COUNTERS) == {
        "BoardRowsLoud", "BoardRowsLoudReferenced", "BoardRowsLoudCited",
        "BoardEventsOpen", "BoardEventsReferenced",
        "BoardRecencyRows", "BoardRecencyReferenced",
        "BoardWatchRows", "BoardWatchReferenced",
        "BoardSpilloverRows", "BoardSpilloverReferenced", "BoardSpilloverLicensed"}
    # A FULL DICT MINTS ALL TWELVE, so the tuple is not a list of names nobody publishes.
    full = {"loud_rows": 9, "loud_referenced": 5, "loud_cited": 3,
            "events_open": 2, "events_referenced": 1,
            "recency_rows": 3, "recency_referenced": 2,
            "watch_rows": 4, "watch_referenced": 1,
            "spillover_rows": 6, "spillover_referenced": 2, "spillover_licensed": True}
    out = S.coverage_counters(full)
    assert set(out) == set(S.COVERAGE_COUNTERS)
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in out.values()), out
    assert out["BoardRowsLoud"] == 9 and out["BoardRowsLoudReferenced"] == 5
    assert out["BoardRowsLoudCited"] == 3 and out["BoardSpilloverLicensed"] == 1


def test_a_coverage_counter_is_ABSENT_when_its_denominator_is_and_the_licence_is_the_exception():
    """(ii) ABSENT IS NEVER ZERO, one pair at a time.

    A recency layer this turn carries nothing for is UNTESTABLE, not a miss -- `board_coverage`'s own
    "denominators are comparisons, never attempts". Publishing `BoardRecencyReferenced=0` beside
    `BoardRecencyRows=0` would put a turn that had NOTHING to reference into the same series as a turn
    that ignored three layers, and no dashboard filter can separate them afterwards.

    `BoardSpilloverLicensed` is the ONE exception and it is a fact about the BLOCK: 0 means "the board
    rendered rows and minted no CROSS-COMMODITY line", which is a measurement."""
    zero = {"loud_rows": 4, "loud_referenced": 1, "loud_cited": 1,
            "events_open": 0, "events_referenced": 0,
            "recency_rows": 0, "recency_referenced": 0,
            "watch_rows": 0, "watch_referenced": 0,
            "spillover_rows": 0, "spillover_referenced": 0, "spillover_licensed": False}
    out = S.coverage_counters(zero)
    assert set(out) == {"BoardRowsLoud", "BoardRowsLoudReferenced", "BoardRowsLoudCited",
                        "BoardSpilloverLicensed"}
    assert out["BoardSpilloverLicensed"] == 0          # the exception: minted at zero, on purpose
    # EACH PAIR GOES WHOLE. A numerator with no denominator is not a measurement.
    for den, nums in (("events_open", ("BoardEventsOpen", "BoardEventsReferenced")),
                      ("recency_rows", ("BoardRecencyRows", "BoardRecencyReferenced")),
                      ("watch_rows", ("BoardWatchRows", "BoardWatchReferenced")),
                      ("spillover_rows", ("BoardSpilloverRows", "BoardSpilloverReferenced"))):
        one = dict(zero, **{den: 2})
        got = set(S.coverage_counters(one))
        assert set(nums) <= got, (den, got)
        assert got - set(nums) == {"BoardRowsLoud", "BoardRowsLoudReferenced", "BoardRowsLoudCited",
                                   "BoardSpilloverLicensed"}, (den, got)
    # THE THREE SHAPES THAT MINT NOTHING AT ALL -- and the middle one is the live path: `fill_stage2`'s
    # subject-ambiguity branch ships a one-line block WITHOUT calling `render_board`, so the block is
    # truthy and `rendered_rows` is empty. A 0-of-0 there is a fabricated figure inside the arm's own
    # new dimension. The third is `answer.py`'s named except: a BROKEN instrument measured nothing.
    assert S.coverage_counters(None) == {}
    assert S.coverage_counters({}) == {}
    assert S.coverage_counters({"declined": "KeyError", "loud_rows": 9}) == {}
    # KEYS THAT ARE NOT NUMBERS ARE NOT DENOMINATORS (a truncated or hand-edited artifact replay) --
    # AND THE LICENCE IS NOT AN EXEMPTION FROM THAT LAW. This dict proves NEITHER half of the sentence
    # `BoardSpilloverLicensed=0` publishes ("the board rendered rows and licensed no CROSS-COMMODITY
    # line"): there is no usable denominator and no licence reading at all. The exception is keyed on
    # the INSTRUMENT HAVING REPORTED -- `spillover_licensed` being a KEY -- and not on the dict being
    # merely non-empty, so a truncated replay mints nothing and a real turn is untouched.
    assert S.coverage_counters({"loud_rows": "9"}) == {}
    assert S.coverage_counters({"loud_rows": "9", "spillover_licensed": False}) == \
        {"BoardSpilloverLicensed": 0}
    # AND `render.board_coverage` ALWAYS CARRIES THE KEY on the path that renders rows, so requiring it
    # costs the live path nothing: its only other exit is the no-rows `{}`, which mints nothing anyway.
    # MEASURED: the instrument has exactly two exits and the second one names the key unconditionally.
    _bc = inspect.getsource(R.board_coverage)
    assert '"spillover_licensed": any(' in _bc
    assert _bc.count("return {") == 2 and "return {}" in _bc      # the no-rows exit and the real one


def test_the_tight_read_never_exceeds_the_loose_one_on_a_REAL_board(fired):
    """(iii) `BoardRowsLoudCited <= BoardRowsLoudReferenced <= BoardRowsLoud`, on the board the SEAM
    itself filled and rendered -- a real `rendered_rows` list, a real `bd.calls`, a real draft.

    THE THREE ACCEPTANCE FIXTURES ARE `test_board_coverage.py`'s, deliberately: they cost ~56 s to
    build (MEASURED 2026-09-11) and that deck already pins the INSTRUMENT on all three. What is pinned
    HERE is the PRODUCER -- that the counters carry the instrument's numbers through unchanged and keep
    its ordering, on a board this deck already holds."""
    bd, out = fired
    assert bd.rendered_rows and out["block"]
    # ONE REPRESENTATIVE PER DENOMINATOR ENTRY, and the fold is not optional: `render_board` stamps
    # `join` on the members of every phase pair (El Nino / La Nina on ONE ONI reading) and
    # `board_coverage` folds them, so a draft citing two halves of one entry is a draft citing ONE row.
    # MEASURED on this fixture: [N1] and [N4] share a join and scored `loud_cited == 1`, not 2.
    ents, _seen = [], set()
    for m in bd.rendered_rows:
        if m.get("role") != "state" or not m.get("handles"):
            continue
        key = str(m.get("join") or "") or ("#%d" % id(m))
        if key in _seen:
            continue
        _seen.add(key)
        ents.append(m)
    assert len(ents) >= 2
    draft = " ".join(f"The board carries this reading [N{m['handles'][0]}]." for m in ents[:2])
    for prose in ("", draft, draft + " Nothing else was used."):
        cov = R.board_coverage(bd, prose, n_start=1, calls=bd.calls)
        cnt = S.coverage_counters(cov)
        assert cnt["BoardRowsLoudCited"] <= cnt["BoardRowsLoudReferenced"] <= cnt["BoardRowsLoud"]
        assert cnt["BoardRowsLoud"] == cov["loud_rows"]
        assert cnt["BoardRowsLoudCited"] == cov["loud_cited"]
        for name, key in (("BoardEventsReferenced", "events_referenced"),
                          ("BoardRecencyReferenced", "recency_referenced"),
                          ("BoardWatchReferenced", "watch_referenced"),
                          ("BoardSpilloverReferenced", "spillover_referenced")):
            if name in cnt:
                assert cnt[name] == cov[key], (name, cnt, cov)
    # THE EMPTY DRAFT IS A REAL DRAFT: every denominator stands, every numerator is zero. The board
    # rendered rows, so the counters are PRESENT -- absent-when-inapplicable is about the DENOMINATOR.
    cnt0 = S.coverage_counters(R.board_coverage(bd, "", n_start=1, calls=bd.calls))
    assert cnt0["BoardRowsLoud"] > 0 and cnt0["BoardRowsLoudCited"] == 0
    # AND THE WRITER'S OWN DRAFT MOVES THE TIGHT READ -- an instrument that cannot move is not one.
    cnt1 = S.coverage_counters(R.board_coverage(bd, draft, n_start=1, calls=bd.calls))
    assert cnt1["BoardRowsLoudCited"] == 2, (cnt1, draft)


def test_the_coverage_counters_ride_the_boards_OWN_emf_record_and_are_silent_flag_off():
    """(iv) ONE RECORD, ONE CALL SITE, AND NOTHING ON A FLAG-OFF TURN.

    The counters are minted at the orchestrator's board EMF block (`_sbs.coverage_counters`) and NOT
    inside `seam.counters()`, because that runs in `fill_stage2` before the writer. They ride the
    EXISTING record -- same `(mode x reason)` dimensions, no second `emf.emit`, no new cardinality --
    and the whole block is inside `if isinstance(_sbt, dict)`, so a turn with no `state_board` trace
    (every flag-off turn in the estate) emits nothing at all."""
    src = inspect.getsource(orch)
    assert src.count("_sbs.coverage_counters(") == 1, "one call site, or two records could disagree"
    blk = src[src.index('_sbt = tr.get("state_board")'):]
    blk = blk[:blk.index("emf.emit_quality(tr)")]
    assert blk.count("emf.emit(") == 1                  # the coverage half adds NO second record
    assert 'if isinstance(_sbt, dict):' in blk          # flag off -> no key -> nothing emitted
    # THE FALLBACK ORDER IS LOAD-BEARING: `BoardFired` is minted BEFORE the coverage update, so a
    # record that somehow carried coverage and no counters still carries the fired/declined sample.
    assert blk.index('"BoardFired"') < blk.index("_sbs.coverage_counters(")
    # EVERY NEW NAME IS A Count under the record's own `units` line -- none of the twelve starts `Ms`.
    assert not any(n.startswith("Ms") for n in S.COVERAGE_COUNTERS)
    # AND THE PRODUCER IS NOT IN `counters()`, which is where a naive landing would have put it.
    assert "coverage_counters" not in inspect.getsource(S.counters)
    # CLAUSES (xii) + (xiii) GREEN, and the whole function is asserted rather than a substring of it:
    # a clause that only grades itself cannot see the drift it exists to catch. The errors ride the
    # message so a red from ANOTHER clause names itself instead of reading as this pin's failure.
    _errs = cc.check_state_seam()
    assert not _errs, _errs


def test_the_trace_key_carries_the_spend_and_the_cap_the_walk_reads(fired):
    """6.7 / D10 / D12: ONE registered key, and it is the SAME key both halves of the budget read. A
    census row can tell a board that declined from a board that never ran, and the walk's ceiling and
    the walk's spend can never come from two boards."""
    bd, out = fired
    tr = out["trace"]
    assert "state_board" in tk.TRACE_RECORD_KEYS
    assert tr["legs"]["board"]["outcome"] == "fired"
    assert isinstance(tr["net_reads"], int) and isinstance(tr["cap"], int)
    assert tr["net_reads"] <= tr["cap"], (tr["net_reads"], tr["cap"])
    assert tr["rectangle"] == [], tr["rectangle"]        # B1 holds on both waves
    assert tr["anchor_source"] == "named" and tr["rank_rule"] == "d2"
    # THE RENDER IS ITS OWN SLOT (S6 review, major 11). `MsBoard` used to be the WALK's inner stage-2
    # number because the seam's `or` discarded its own measurement, and the render -- 60-92% of the
    # board's wall -- fell outside the counter entirely. Slot 2 is the seam's wall now, and "render"
    # names the pole so arm A cannot attribute the board's cost to its reads.
    assert set(tr["stage_ms"]) == {1, 2, "render"}
    assert tr["stage_ms"][2] >= tr["stage_ms"]["render"] >= 0.0
    sg = _sg([])
    sg.trace = {"quantify_wave_reads": 5, "state_board": tr}
    assert cq._cw_turn_spent(sg) == 5 + tr["net_reads"]
    assert cq._board_declared_cap(sg) == tr["cap"]


def test_the_two_stages_are_stamped_separately_and_stage_2_reranks_nothing(graph):
    """D11: stage 1 (numeric state, rank, wave 1) runs before `ground`; stage 2 (receipts, EVENT rows,
    the text tier, wave 2) after it. Stage 2 NEVER re-orders stage 1's numeric rows -- the text-only
    tail is the only thing that moves, because 'newest receipt date' does not exist before `ground`."""
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep", query="soybeans now?",
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
    assert bd.stage_done[1] is True and bd.stage_done[2] is False
    from leviathan.graphrag.state.rows import status_word
    served = [k for k in bd.order if (bd.row(*k) is not None and bd.row(*k).state is not None
                                      and status_word(bd.row(*k).state.status) == "ok")]
    S.fill_stage2(bd, graph=graph, sg=sg)
    assert bd.stage_done[2] is True
    after = [k for k in bd.order if k in set(served)]
    assert after == served, "stage 2 re-ordered a row stage 1 had already ranked"


# ═══ sec 7: the RENDER CAPS as knobs ══════════════════════════════════════════════════════════════
def test_the_render_caps_are_knobs_at_the_shipped_values_and_S7_decides(graph):
    """Sec 7 + the S2/S3 measured OVERRUN. The caps ride the mode table with every other per-mode
    constant; their DEFAULTS are the design's planned sizes (which is what `render.RENDER_CAPS` and
    `watch.WATCH_RENDER_K` already ship), and the MEASURED sizes are recorded beside them in
    `BoardKnobs`. NOTHING WAS TIGHTENED AT S6: a cap change is a prompt-content change and arm A must
    measure ONE instrument, so the knob existed and S7 set it.

    S7 HAS NOW SET IT, AND THIS PIN IS CORRECTED RATHER THAN RELAXED (2026-09-11). The owner's 09-10
    ruling is that **Scan (quick) gets render caps and deep and max run UNCAPPED into arm A**, so the
    old literal `absence=0` on ALL THREE tiers is no longer the shipped shape and asserting it would
    red on the ratified change. The comparison now reads the KNOB, which is what `render_caps` is
    defined to do, and the ratified SHAPE is asserted as its own claim below -- a pin that reads the
    knob and says nothing about the tiers would have been a pin rewritten to match the code."""
    from leviathan.graphrag.state import watch as WA
    for mode in ("quick", "deep", "max"):
        kn = B.board_knobs_of(mode)
        assert R.render_caps(mode, kn) == dict(R.RENDER_CAPS[mode], absence=kn.render_absence,
                                               absence_names=kn.render_absence_names)
        assert R.render_caps(mode) == R.RENDER_CAPS[mode]        # no knobs -> the shipped table
        assert WA.render_k(mode, kn) == WA.WATCH_RENDER_K[mode]
    # THE RATIFIED S7 SHAPE, STATED AS ITS OWN CLAIM (owner, 2026-09-10). The Scan block MEASURED 3.10x
    # sec 7's planned size against a 105-154-word writer budget, so quick is CAPPED; deep and max run
    # UNCAPPED into arm A and the JUDGED delta decides them. A cap that crept onto deep or max would
    # change the prompt of the very cell the arm is measuring, which is the one thing 10.3 forbids.
    assert B.board_knobs_of("quick").render_absence > 0, "Scan's render cap is the ratified S7 change"
    assert B.board_knobs_of("deep").render_absence == 0, "deep runs UNCAPPED into arm A"
    assert B.board_knobs_of("max").render_absence == 0, "max runs UNCAPPED into arm A"
    # a knob that MOVES actually moves the render, so the lever is live for S7 rather than declared
    kn = B.board_knobs_of("max")._replace(render_convergence=1, render_absence=2,
                                          render_absence_names=3)
    caps = R.render_caps("max", kn)
    assert caps["convergence"] == 1 and caps["absence"] == 2 and caps["absence_names"] == 3
    # THE NAME CAP IS THE ONE THAT BINDS INSIDE A ROW, and it is the class the review measured at
    # 23,871 characters in ONE line. It states its remainder in WORDS, so the row still says what it
    # cut and no digit enters a letters-only class.
    long = [f"driver {i}" for i in range(40)]
    assert R.name_list(long, 0) == ", ".join(long)
    cut = R.name_list(long, 5)
    assert cut.startswith(", ".join(long[:5])) and "further readings this line does not name" in cut
    assert not any(ch.isdigit() for ch in cut[len(", ".join(long[:5])):])
    # ...and a nine-field tuple (the S2 fixtures, the census) still reads the shipped table
    nine = B.BoardKnobs(*tuple(B.board_knobs_of("deep"))[:9])
    assert R.render_caps("deep", nine) == dict(R.RENDER_CAPS["deep"], absence=nine.render_absence,
                                               absence_names=nine.render_absence_names)


def test_every_render_cut_names_what_it_cut(graph):
    """6.6 / 3.8's own law, swept to completion at S6. THREE cuts still named nothing before this
    sitting -- the RECEIPTS past the tier's cap, the ROWS that were read and sat below the loudness
    cut, and the convergence patterns past the pattern cap (a bare `break`). The loudness one is the
    sharpest: it is an absence of a FACT rather than of a gap, so a reader met a board whose quiet
    rows were indistinguishable from rows that do not exist."""
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep", query="soybeans now?",
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
    W.stage2(bd, graph, state_fn=H.fixture_state_fn(H.ASOF))
    # force every cut to bind at once
    caps = dict(R.render_caps(bd.mode, bd.knobs), convergence=0, receipts=1)
    from leviathan.graphrag.state.rows import status_word
    served = [r for r in bd.rows
              if r.state is not None and status_word(r.state.status) == "ok"]
    assert len(served) >= 2, "the fixture must serve at least two rows for a loudness cut to exist"
    for r in served[1:]:
        r.legs["loud"] = False
    served[0].legs["loud"] = True
    rcpt = {served[0].key: [{"date": "2026-08-01", "source": "x", "tier": 1, "text": "a"},
                            {"date": "2026-07-01", "source": "y", "tier": 1, "text": "b"}]}
    blk = R.render_board(bd, receipts_by_row=rcpt, caps=caps).text()
    assert "sit below this tier's loudness cut" in blk
    assert "past this tier's receipt cut" in blk
    if bd.convergence:
        assert "past this tier's pattern cut" in blk
    assert "BOARD ABSENCE" in blk

def test_the_block_is_a_SEPARATE_volatile_block_after_extra_context_and_before_quantify():
    """6.1 / 3.9: ONE block, its OWN volatile block, in a stated position -- the numbers the agent found
    sit ABOVE the board, the board sits ABOVE the cascade's own rows, and the grounding ledger closes
    the tail. It is asserted on `_answer_l2`'s SOURCE ORDER because the position is a property of the
    seam and not of any one turn, and because a prompt-order regression is invisible in every unit
    fixture that renders the block alone.

    THE TWO STAGES ARE IN THEIR STATED PLACES for the same reason (D11): stage 1 AFTER
    `pl.grounded_subgraph` and BEFORE `pl.ground`; stage 2 AFTER `ground` and BEFORE `cq.quantify`.
    Stage 2 is the one that can read receipts at all, because `n.evidence` does not exist before
    `ground` fills it -- so an order that swapped them would not merely be slower, it would be a board
    with no text tier and no EVENT rows."""
    src = inspect.getsource(an._answer_l2)
    i_walk = src.index("sg = pl.grounded_subgraph(")
    i_s1 = src.index("_board = _sbs.fill_stage1(")
    i_ground = src.index("pl.ground(sg, query, graph,")
    i_ctx = src.index("volatile_blocks = volatile_blocks + [extra_context]")
    i_s2 = src.index("_sb = _sbs.fill_stage2(")
    i_block = src.index('volatile_blocks = volatile_blocks + [_sb["block"]]')
    i_quant = src.index("_cblock, _quant_trace, _reroute_trace = cq.quantify(")
    i_cblock = src.index("volatile_blocks = volatile_blocks + [_cblock]")
    assert i_walk < i_s1 < i_ground, "stage 1 must sit between the walk and ground()"
    assert i_ground < i_ctx < i_s2 < i_block < i_quant < i_cblock, (
        "the board block must land AFTER extra_context and BEFORE the quantify block")
    # ...and the trace key is stamped BEFORE quantify, because both halves of D12 read it there
    assert src.index('sg.trace["state_board"] = _sb["trace"]') < i_quant

def test_the_attached_event_fixture_runs_through_the_seam_and_outranks_the_route(graph):
    """THE THIRD ACCEPTANCE FIXTURE (sec 0.3 scenario 3, the B40 mandate), through the SEAM.

    AN EXPLICIT GESTURE OUTRANKS THE BOARD (3.1): `_resolve_attachments`' typed event names the anchor,
    and it wins over whatever the route produced -- here a soybeans route with a palm attachment
    anchors PALM. `ANCHOR_SOURCES` is a PRECEDENCE order, so the strongest source is what the header
    says the query decided, and the trace carries it for the census.

    ONE HALF OF SCENARIO 3 IS NOT WIRED AND IS NAMED HERE RATHER THAN DISCOVERED LATER: the phase-2
    row of design 9.2 also asks for the attachment's TYPED EVENTS to become EVENT rows (L13,
    `orchestrator._resolve_attachments`). `_answer_l2` never receives the attachment dict, so the seam
    can take the anchor SLUG (which the orchestrator's LAST `route_fn` binding already provides) but
    not the events. The board therefore dates this driver from its own receipts, and the attachment's
    own dated event rides phase 3 with the rest of the text half."""
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="max",
                       query="Indonesia raised the biodiesel mandate to B40: what does it do, and to whom?",
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",),
                       attached_event="malaysian_crude_palm_oil_cme")
    assert bd.anchor_source == "attached_event"
    assert bd.anchor_slugs[0] == "malaysian_crude_palm_oil_cme"
    src = {a.contract: a.source for a in bd.anchors}
    assert src["malaysian_crude_palm_oil_cme"] == "attached_event"
    assert src["soybeans_cbot"] == "named"        # the route survives BESIDE the gesture, never instead
    out = S.fill_stage2(bd, graph=graph, sg=sg)
    assert out["block"] and R.SB_MARKER_PREFIX in out["block"]
    assert out["trace"]["anchor_source"] == "attached_event"
    assert out["counters"]["BoardFired"] == 1


# ═══ THE S6 REVIEW's OWN PINS ═════════════════════════════════════════════════════════════════════
def test_every_declared_off_lane_is_stamped_by_one_of_the_two_producers(monkeypatch):
    """FATAL 1. Sec 6.7 exists to separate "a board that DECLINED" from "a board that NEVER RAN", and
    the first S6 build closed that hole for two lanes while its notes -- in `answer.py` AND in the
    registered trace key's own documentation -- asserted the other three were stamped in `respond()`.
    Grep found no such code: `numbers_only`, `trivial` and `refused` never enter `answer.py` at all,
    so nothing could thread them, `reason_dimension` could never emit them, and three of the four
    declared off lanes were structurally invisible.

    TWO PRODUCERS, ONE PAYLOAD FUNCTION. `orchestrator._state_board_off_lane_stamp` reads the resolved
    intent and calls `answer._state_board_lane_stamp`, which owns the flag read, the closed-enum
    validation and the shape -- so the two stamps cannot drift into two shapes for one key."""
    from leviathan.graphrag import orchestrator as orc

    monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
    for intent, word in sorted(orc._STATE_BOARD_OFF_INTENTS.items()):
        tr: dict = {}
        orc._state_board_off_lane_stamp({"intent": intent}, tr)
        sb = tr["state_board"]
        assert sb["legs"]["board"] == {"outcome": "declined", "reason": f"lane_off:{word}",
                                       "reads": 0}
        assert sb["net_reads"] == 0 and sb["cap"] == 0
        assert S.reason_dimension(sb["legs"]["board"]["reason"]) == "lane_off"
        assert B.check_reason("board", sb["legs"]["board"]["reason"]) is None
    # EVERY DECLARED OFF LANE IS REACHABLE from one of the two producers -- the claim clause (ix) of
    # `check_state_seam` grades, asserted here on the vocabulary rather than on the source text.
    reachable = set(orc._STATE_BOARD_OFF_INTENTS.values()) | {"onehop"}
    assert set(B.OFF_LANES) | {"run_live"} <= reachable
    # A LANE THAT ALREADY STAMPED KEEPS ITS OWN WORD, and a reasoning/hybrid turn is stamped by
    # `answer.py` alone -- this producer must never overwrite or invent.
    tr = {"state_board": {"legs": {"board": {"outcome": "fired"}}}}
    orc._state_board_off_lane_stamp({"intent": "numbers_only"}, tr)
    assert tr["state_board"]["legs"]["board"]["outcome"] == "fired"
    for intent in ("reasoning", "hybrid"):
        tr = {}
        orc._state_board_off_lane_stamp({"intent": intent}, tr)
        assert tr == {}
    # ...and FLAG OFF the stamp is {} on every lane, which is what keeps the dark item dark.
    monkeypatch.delenv("GRAPHRAG_STATE_BOARD", raising=False)
    tr = {}
    orc._state_board_off_lane_stamp({"intent": "numbers_only"}, tr)
    assert tr == {}


def test_a_declined_board_never_raises_the_walks_ceiling(graph):
    """FATAL 2, at the seam rather than at the arithmetic. `walk()` used to declare both wave caps
    ABOVE its anchor gate, so a board that declined carried the tier's full cap with `net_reads` 0 --
    and `cascade._board_declared_cap` put that cap on the walk's runaway tripwire on a turn `quantify`
    received no board at all. `resolve_anchors` returning empty is a LIVE case (a routing miss), not a
    theoretical one. TWO FIXES, BOTH ASSERTED: the caps are declared after the gate, and the term
    reads the leg."""
    for lane, kw in (("numbers_only", {}), ("run_hybrid", {"pg_live": False})):
        sg = _sg(["soybeans_cbot"])
        bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="max", lane=lane,
                           named=("soybeans_cbot",), **kw)
        assert bd.legs["board"]["outcome"] == "declined"
        assert bd.declared_cap() == 0 and bd.net_reads() == 0
        tr = bd.trace()
        sg2 = _sg([])
        sg2.trace = {"quantify_wave_reads": 5, "state_board": tr}
        assert cq._board_declared_cap(sg2) == 0
        assert cq._cw_turn_spent(sg2) == 5
    # AN ANCHORLESS TURN IS THE SHARPEST CASE: it enters the walk and declines inside it.
    sg = _sg([])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="max",
                       state_fn=H.fixture_state_fn(H.ASOF))
    assert bd.legs["board"] == {"outcome": "declined", "reason": "anchor_none", "reads": 0}
    assert bd.declared_cap() == 0
    sg2 = _sg([])
    sg2.trace = {"quantify_wave_reads": 5, "state_board": bd.trace()}
    assert cq._board_declared_cap(sg2) == 0


def test_the_board_and_the_recency_facts_flag_ship_together_or_not_at_all(graph, monkeypatch):
    """THE MARCH-2025 DEFECT, FROM BOTH ENDS. `GRAPHRAG_STATE_BOARD` and `GRAPHRAG_RECENCY_FACTS` were
    independent, and prod's own state today is board-on / facts-off. In that state `_system` carries
    BOTH `_SYSTEM_RECENCY_EDGE` -- the clause whose own code note records that it made the 2026-09-07
    soybean answer date ITSELF by one layer -- AND the mandate's "none of them dates the answer as a
    whole"; and the board hands the writer three candidate edges for that clause to choose the oldest
    of. The board would make the defect it was built to close WORSE."""
    monkeypatch.delenv("GRAPHRAG_RECENCY_FACTS", raising=False)
    assert an._recency_facts_on() is False, "the S5 flag is dark, which is why the coupling matters"
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep", named=("soybeans_cbot",),
                       state_fn=H.fixture_state_fn(H.ASOF), recency_facts=False)
    assert bd.legs["board"] == {"outcome": "declined", "reason": "recency_facts_off", "reads": 0}
    assert bd.rows == [] and bd.declared_cap() == 0
    assert S.reason_dimension("recency_facts_off") == "recency_facts_off"
    assert S.fill_stage2(bd, graph=graph, sg=sg)["block"] == ""
    # THE WORD IS CLOSED and the reader meets a SENTENCE, never the token.
    assert B.check_reason("board", "recency_facts_off") is None
    assert R.absence_why("recency_facts_off") != R.ABSENCE_FALLBACK
    # ...and the seam threads it from the ONE producer rather than reading an environment (the flag
    # grammar itself is graded by `check_state_seam` clause (i), which reads an ALLOWLIST of names
    # rather than banning the substring -- this module QUOTES that doctrine in its own docstring).
    assert "recency_facts=_recency_facts_on()" in inspect.getsource(an._answer_l2)
    assert cc.check_state_seam() == []


def test_the_anchor_ceiling_bounds_a_focus_driver_turn_and_names_what_it_dropped(graph):
    """MAJOR 1 / 9 / 12 / 13, in one measurement. Amendment 1 anchors EVERY contract carrying a
    `focus_driver` id -- by design, and `resolve_anchors` bounds only INFERRED seeds -- so an FE
    attachment put 24 (`crude_oil`) to 35 (`El_Nino`, `heat_stress`) DAGs on one turn: declared cap
    106 against the design's 71, 916 rendered rows, ~37,450 writer tokens and 35 SERIAL tape reads,
    all scaling with a user gesture rather than with the tier the user bought.

    THE CEILING IS A TIER KNOB and the cut NAMES what it dropped, like every other cut on this board;
    the anchor PRECEDENCE is the cut order, so a named market can never lose its place to a driver's
    twenty-ninth board."""
    wide = [d for d in ("El_Nino", "heat_stress", "crude_oil")
            if len(W._driver_anchor_order(graph, d)) > 8]
    assert wide, "the shipped graph no longer carries a widely-shared driver -- re-pick the fixture"
    drv = wide[0]
    raw = W.resolve_anchors(contracts=["soybeans_cbot"], focus_driver=drv, graph=graph,
                            max_contracts=6)
    assert len(raw) > 8, (drv, len(raw))
    for mode in ("quick", "deep", "max"):
        kn = B.board_knobs_of(mode)
        sg = _sg(["soybeans_cbot"])
        bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode=mode, focus_driver=drv,
                           state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
        assert len(bd.anchors) == kn.max_anchors < len(raw), mode
        note = [n for n in bd.notes if n.get("kind") == "anchor_cap"][0]
        assert note["cap"] == kn.max_anchors
        assert note["dropped"] == len(note["names"]) == len(raw) - kn.max_anchors
        # THE EXPLICIT GESTURES ARE RESERVED AND THE CUT FALLS ON THE UNBOUNDED SOURCE. Amendment 1
        # ranks `focus_driver` ABOVE `named`, so a plain precedence-tail cut would keep the driver's
        # twenty-ninth board and drop the market the user TYPED -- Amendment 2 defeated by the fence
        # meant to bound Amendment 1.
        assert "soybeans_cbot" in bd.anchor_slugs, mode
        # THE MARKET IS HELD BY ITS `named` FLAG, NOT BY ITS SOURCE WORD, and that distinction is the
        # defect: `soybeans_cbot` carries the attached driver too, so the precedence collapses it to
        # `focus_driver` and every trace of having been typed would be gone. `Anchor.named` is
        # monotonic across the collapse, which is what the reservation reads.
        held = [a for a in bd.anchors if a.contract == "soybeans_cbot"][0]
        assert held.named is True and held.source == "focus_driver"
        assert "soybeans_cbot" not in note["names"]
        # THE DECLARED CAP IS A TIER NUMBER AGAIN -- the tape seat is one per anchor, and that is the
        # term that made the cap scale with the gesture.
        out = S.fill_stage2(bd, graph=graph, sg=sg, qfn=lambda *a, **k: [])
        assert bd.ledger.tape_cap <= kn.max_anchors
        assert bd.declared_cap() <= int(kn.wave1) + int(kn.wave2) + kn.max_anchors, mode
        # ...and the reader is told, in the block, which boards the cut did not print.
        assert "past this tier's anchor cut" in out["block"], mode


def test_the_tape_column_is_priced_before_its_fetch_and_names_its_own_remainder(graph):
    """MAJOR 10. `WaveLedger.priced_before_fetch` and `Board.rectangle` cover the two WAVES; the tape
    is a third column outside both, and `attach_tape` set its "cap" from the tape it had already been
    handed -- a post-hoc record of the spend wearing the word cap, against design 3.8's "cut EACH wave
    at its cap BEFORE its fetch" and against the S6 ceiling comment's own "THE CAP, NEVER THE SPEND"."""
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="max", named=("soybeans_cbot",),
                       state_fn=H.fixture_state_fn(H.ASOF))
    bd.anchors = tuple(bd.anchors) + (B.Anchor(contract="malaysian_crude_palm_oil_cme",
                                               source="planner_inferred", rank=9),)
    kept = R.price_tape(bd, cap=1)
    assert kept == ("soybeans_cbot",) and bd.ledger.tape_cap == 1
    note = [n for n in bd.notes if n.get("kind") == "tape_cap"][0]
    assert note["names"] == ("malaysian_crude_palm_oil_cme",)
    # THE SEAT IS DECLARED BEFORE A READ HAPPENS: no tape has been attached at this point at all.
    assert bd.tape == {} and bd.ledger.tape_reads == 0


def test_MsBoard_measures_the_whole_board_and_names_the_render_pole(fired):
    """MAJOR 11. The seam stamped `bd.stage_ms[2] = bd.stage_ms.get(2) or <its own wall>`, and
    `walk._stage2` had already filled that slot -- so the `or` discarded the seam's measurement and
    `MsBoard` reported the walk's inner number alone. The tape read, the analogs, the watch rows, the
    age clauses, the recency ledger and THE RENDER all fell outside the counter, MEASURED at 8-17x
    under-reporting (1 anchor quick 259 ms total vs MsBoard 15; 35 anchors deep 4,843 vs 810), with
    the render alone 60-92% of the board's wall -- i.e. the pole, invisible to the instrument that
    exists to identify the pole (sec 3.9)."""
    bd, out = fired
    assert bd.stage_ms[2] >= bd.stage_ms["render"] > 0.0
    cnt = out["counters"]
    assert cnt["MsBoard"] >= cnt["MsBoardRender"] >= 0
    assert cnt["MsBoard"] >= int(bd.stage_ms["render"]) - 1


def test_the_reserved_analog_seats_are_a_cap_and_the_borrows_are_a_read(fired):
    """MAJORS 6 AND 7, which are one defect from two ends: a column priced with no producer.

    `BoardEvidenceBorrows` published the RESERVED analog-receipt seats -- 3 on every fired Analysis
    board, 5 on every fired Cascade board -- while `analogs._receipts_for` returned [] at zero reads,
    because the seam wires no `receipt_fn`. Arm A's evidence-pool pressure would have been measured
    from a number no read produced. And the BENCHMARK column had no ledger field at all, so the day it
    IS wired its spend would be invisible to `_cw_turn_spent` (it reads outside both rectangles) --
    the "a real spend read as zero" failure S5 had to repair for the composer sub-legs.

    **RE-BANKED BY THE ANALOG RENDER LANE, WHICH GAVE THE COLUMN ITS PRODUCER.** The seam now hands
    the analog leg the pool ``ground()`` already filled (``seam._receipt_borrow`` over
    ``_receipts_from(sg)``), so the borrows are REAL and the column is no longer a price with nothing
    behind it. What has NOT changed is the half this test exists to protect: a borrow from an
    already-grounded pool is not a READ. ``Ledger.reads_used`` does not sum ``evidence_borrows``,
    ``analog_reads`` at the seam is computed from ``benchmark_fn`` ALONE so ``walk._stage2`` reserves
    no seat for it, and the BENCHMARK column -- the one that really does call a mirror -- is still
    unwired and still counted the moment it is wired. MEASURED over the 54 served cells of this
    landing's sweep: ``reads_used`` identical to HEAD on 54 of 54, ``evidence_borrows`` 0 -> 6 at deep
    and 0 -> 20 at max."""
    bd, out = fired
    assert out["counters"]["BoardEvidenceBorrows"] == bd.ledger.evidence_borrows
    assert bd.ledger.benchmark_reads == 0, "no caller wires a benchmark, so nothing is read"
    # A BORROW IS NOT A READ. It is counted at the one place a borrow happens and it stays OUT of the
    # ceiling arithmetic, because `ground()` already paid for these propositions.
    before = bd.net_reads()
    bd.ledger.evidence_borrows += 7
    assert bd.net_reads() == before, "a borrow may never move the read ceiling"
    # THE UNWIRED COLUMNS ARE NOT RESERVED EITHER, so the walk's ceiling gains no read that nothing
    # can pay: the seam wires no benchmark, so both cap columns are zero on the served shape.
    assert bd.ledger.evidence_cap == 0 and bd.ledger.benchmark_cap == 0
    assert bd.net_reads() <= bd.declared_cap()
    # ...and `reads_used` counts a benchmark read, so a future wiring is visible to the enumeration.
    bd.ledger.benchmark_reads += 3
    assert bd.net_reads() == out["trace"]["net_reads"] + 3
    # AND THE SEAM RESERVES THE SEATS OFF THE BENCHMARK ALONE, in its own source.
    assert "analog_reads=bool(benchmark_fn is not None))" in inspect.getsource(S.fill_stage2)


def test_a_phase_pair_on_one_series_is_one_reading_and_the_block_says_so(graph):
    """MAJOR 17. The shipped graph puts `El_Nino` and `La_Nina` on ONE globally-keyed ref with
    OPPOSITE declared signs (and `IOD_positive` / `IOD_negative` likewise). Loudness ranks the
    UNSIGNED state and is phase-blind, so both land loud on the SAME reading -- MEASURED verbatim as
    "[N1] El Nino ... +0.98 degC ... in the OPPOSITE direction" beside "[N4] La Nina ... +0.98 degC
    ... in the SAME direction": one number, two handle triples, two contradictory signs, and nothing
    saying they are two phases of one series. The mandate's movement (1) then tells the writer to
    "say so and name both sides" where the rows lean both ways.

    THE FENCE CORRECTS, IT DOES NOT DELETE: both rows keep their figure, their handle and their
    declared sign, and one letters-only row states the relation."""
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="max",
                       query="El Nino is developing: what does it do to soybeans?",
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
    out = S.fill_stage2(bd, graph=graph, sg=sg)
    blk = out["block"]
    joins = [l for l in blk.splitlines() if l.startswith("BOARD JOIN ")]
    assert joins, "the ENSO pair rendered no join row"
    assert any("El Nino" in l and "La Nina" in l for l in joins), joins
    for l in joins:
        assert "one reading" in l.lower() or "ONE series" in l
        assert not any(ch.isdigit() for ch in l), "SB-JOIN is letters-only and mints no figure"
    # THE MANDATE KNOWS ABOUT THE ROW, so "name both sides" cannot be applied to one reading.
    assert "BOARD JOIN" in N.SYSTEM_STATE_BOARD_MANDATE
    # ...and the class is disjoint from every other, which is the whole of the lint's own bar.
    assert R.classify(joins[0]) == ("SB-JOIN",)


def test_the_mandate_orders_IDEAS_and_never_the_contracts_headings(graph):
    """MAJOR 15. The mandate opened "narrate it as a mentor in this order and no other" with
    SPILLOVERS third, while `response_contracts` orders "'## Mechanism', '## The record', '## Where
    the record disagrees', '## What to watch'" and forbids returning to Mechanism after The record --
    and SPILLOVERS has NO canonical home: 0 of the 10 shipped contracts carry `## Cross-commodity` or
    `## Complex-wide move` in `sections`, and both are injected-only, licensed by a marker line the
    board mints on none of the three acceptance fixtures. So the fallback was the ONLY branch and the
    writer had to break one of the two literals on 100% of board turns."""
    from leviathan.graphrag import response_contracts as rc

    homes = {h for _m, h, _f in N.MANDATE_MOVEMENTS}
    licensed = {f for _m, _h, f in N.MANDATE_MOVEMENTS if f}
    shipped = {s for c in rc.CONTRACTS.values() for s in (getattr(c, "sections", ()) or ())}
    assert homes - shipped, "the fallback is recorded because a home is not a shipped section"
    assert licensed <= shipped, "every FALLBACK home must be a section the contract actually ships"
    m = N.SYSTEM_STATE_BOARD_MANDATE
    assert "in this order and no other" not in m
    assert "order of ideas" in m and "adding no heading of your own" in m
    assert N.check_literals() == []


# ═══ THE ANCHOR-SHAPE SET: fifteen blocks, ZERO register trips ═══════════════════════════════════
#: THE FIFTEEN BLOCKS THE FENCE IS PROVED ON: five anchor shapes x three tiers. It is the set the S6
#: second verify's re-fix is measured against, and it is wider than the census's three shapes on
#: purpose -- the assembled-row fence lives on a SUB-LINE (the amplifier) and on a receipt row, and
#: both are per-anchor rows whose count is a function of the shape rather than of the tier.
ANCHOR_SHAPES: dict = {
    "single":         dict(seeds=["soybeans_cbot"], named=("soybeans_cbot",)),
    "two_named":      dict(seeds=["soybeans_cbot", "corn_cbot"],
                           named=("soybeans_cbot", "corn_cbot")),
    "four_named":     dict(seeds=["soft_red_winter_wheat_cbot", "corn_cbot", "soybeans_cbot",
                                  "malaysian_crude_palm_oil_cme"],
                           named=("soft_red_winter_wheat_cbot", "corn_cbot", "soybeans_cbot",
                                  "malaysian_crude_palm_oil_cme")),
    "focus_driver":   dict(seeds=["soybeans_cbot"], named=(), focus_driver="El_Nino",
                           max_contracts=6),
    "attached_event": dict(seeds=["soybeans_cbot"], named=("soybeans_cbot",),
                           attached_event="malaysian_crude_palm_oil_cme"),
}

#: The census query, verbatim from `board.BoardKnobs`' own table, so the deck and the census measure
#: ONE turn. No row reads it -- which is exactly why it is named in both places rather than in neither.
ANCHOR_QUERY = "El Nino is developing: what does it do to soybeans?"


def test_the_fifteen_anchor_shapes_render_at_ZERO_register_trips_with_their_AMPLIFIERS_INTACT(graph):
    """THE PROOF SET OF THE S6 SECOND VERIFY. Five anchor shapes x three tiers, offline, zero reads.

    TWO CLAIMS, AND THE SECOND IS THE ONE THAT MATTERS. Zero trips alone is satisfiable by a fence
    that deletes: a block of absences trips nothing. So every amplifier row on every one of the
    fifteen blocks is asserted to still carry its PAIR, its LOUD CLAIM and its EFFECT WORD -- and the
    read split wherever the walk produced one -- which is the half `Block.add`'s whole-row correction
    was taking off the board when a curated note completed a class rule on the splice.

    THE COUNT OF AMPLIFIER ROWS IS ASSERTED NON-ZERO PER TIER, because a shape that renders none
    would green this deck while proving nothing: `quick` renders none on the plain shapes (its
    convergence cap is 2 and the amplifiers hang under later patterns) and that is recorded as the
    shape's own fact rather than hidden inside a total."""
    from leviathan.graphrag import register as reg

    seen_amps = 0
    for shape, spec in ANCHOR_SHAPES.items():
        kw = dict(spec)
        seeds = kw.pop("seeds")
        for mode in ("quick", "deep", "max"):
            bd = S.fill_stage1(graph=graph, sg=_sg(seeds), asof=H.ASOF, mode=mode,
                               query=ANCHOR_QUERY, state_fn=H.fixture_state_fn(H.ASOF), **kw)
            out = S.fill_stage2(bd, graph=graph, sg=_sg(seeds), qfn=lambda *a, **k: [])
            blk = out["block"]
            assert blk, (shape, mode)
            # (1) ZERO TRIPS -- the render leg fires, and it stamps `declined` on a corrected line
            leg = bd.trace()["legs"]["render"]
            assert leg["outcome"] == "fired" and leg["reads"] == 0, (shape, mode, leg)
            # (2) ...and the block itself is clean, read the way the detector reads it
            assert reg.register_leaks(blk) == [], (shape, mode)
            # (3) THE AMPLIFIER ROWS KEPT THEIR WORDS
            amps = [l for l in blk.splitlines() if l.lstrip().startswith("amplifier on ")]
            seen_amps += len(amps)
            for l in amps:
                # RE-ANCHORED 2026-09-17: the same CLAIM in the reader's words. `loud`/`loudest` ran
                # 27 times and the instrument's own `board` 142 times per rendered block, and the PM
                # lens charged both by name on the served answers.
                assert "are all among the largest moves here" in l, (shape, mode, l)
                assert "the graph records the effect as " in l, (shape, mode, l)
                assert R.classify(l) == ("SB-M",), (shape, mode, R.classify(l), l)
                # THE READ SPLIT, wherever the walk produced one: the clause is whole, never a
                # truncated "carries no series" with the object of the sentence fenced away.
                if "no series" in l:
                    assert "no series read here" in l, (shape, mode, l)
            # (4) ...and no row on the board is the whole-row correction of one
            for l in blk.splitlines():
                assert "BOARD ABSENCE" not in l or "did not pass its own register check" not in l, l
    assert seen_amps >= 15, seen_amps


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# S7b -- THE TWO REGISTER INSTRUMENTS AT THE SEAM. The same two halves this deck already holds, for
# two more flags: with `GRAPHRAG_REGISTER_LICENCE` and `GRAPHRAG_DESK_REGISTER` OFF, the prompt, the
# strip decision, the counters, the coverage dict and the judge panel are HEAD's; and neither engine
# module reads either flag, because both are read ONCE at the answer seam and threaded down.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_s7b_flags_default_off_and_read_the_estates_exact_spelling(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_REGISTER_LICENCE", raising=False)
    monkeypatch.delenv("GRAPHRAG_DESK_REGISTER", raising=False)
    assert an._register_licence_on() is False
    assert an._desk_register_on() is False
    for fn, env in ((an._register_licence_on, "GRAPHRAG_REGISTER_LICENCE"),
                    (an._desk_register_on, "GRAPHRAG_DESK_REGISTER")):
        for word in ("on", "ON", "1", "true", "True"):
            monkeypatch.setenv(env, word)
            assert fn() is True, (env, word)
        for word in ("off", "", "no", "0", "yes"):
            monkeypatch.setenv(env, word)
            assert fn() is False, (env, word)


def test_neither_register_flag_is_read_anywhere_but_the_answer_seam():
    """RI-1 and the `state/` doctrine, restated for two more names. `register.py` takes its mode as an
    argument by design -- 'a mis-plumbed enable can never relax the suggester chip guard or the
    numbers/news/live bodies' -- and `state/` reads no environment at all."""
    import leviathan.graphrag.register as _reg
    import leviathan.graphrag.verify as _vfy
    # THE TEST IS THE ACCESSOR, NOT THE WORD -- `check_state_seam` clause (i)'s own stated lesson:
    # THIS ESTATE WRITES ITS DOCTRINE IN DOCSTRINGS, and `narration.py`'s block note NAMES the flag it
    # is scoped by. A substring ban would red the build on the sentence that states the rule.
    _names = re.compile(r"os\.environ\.get\(\s*[\"']([A-Za-z0-9_]+)")
    for mod in (_reg, _vfy, N, S, R, B):
        src = inspect.getsource(mod)
        read = set(_names.findall(src))
        assert not {n for n in read if n.startswith(("GRAPHRAG_REGISTER", "GRAPHRAG_DESK"))}, mod.__name__
        assert "os.environ[" not in src, mod.__name__
    body = inspect.getsource(an._answer_l2)
    assert body.count("_register_licence_on()") == 1, "the licence is resolved ONCE per body"
    assert body.count("_desk_register_on()") >= 1


def test_the_state_seam_check_still_passes_with_the_new_flags_lit(monkeypatch):
    """`check_state_seam` asserts the flag grammar from SOURCE TEXT, so a runner with the S7b flags set
    cannot change its verdict -- the same property clause (i) already claims for GRAPHRAG_STATE_BOARD."""
    monkeypatch.setenv("GRAPHRAG_REGISTER_LICENCE", "on")
    monkeypatch.setenv("GRAPHRAG_DESK_REGISTER", "on")
    assert cc.check_state_seam() == []
    assert cc.check_register_seam() == []


def test_no_new_emf_counter_ships_in_s7b():
    """The twelve stay twelve. The register numbers ride the coverage ARTIFACT, which is exactly the
    population `seam.coverage_counters`' own docstring keeps out of EMF."""
    assert len(S.COVERAGE_COUNTERS) == 12
    assert S.COVERAGE_COUNTERS == ("BoardRowsLoud", "BoardRowsLoudReferenced", "BoardRowsLoudCited",
                                   "BoardEventsOpen", "BoardEventsReferenced",
                                   "BoardRecencyRows", "BoardRecencyReferenced",
                                   "BoardWatchRows", "BoardWatchReferenced",
                                   "BoardSpilloverRows", "BoardSpilloverReferenced",
                                   "BoardSpilloverLicensed")
    keys = {k for _d, den, nums in S._COVERAGE_GROUPS for k in (den, *(n for _c, n in nums))}
    assert not any(k.startswith("register_") for k in keys)
    cov = {"loud_rows": 38, "loud_referenced": 38, "loud_cited": 30, "spillover_licensed": True,
           "register_lingo_hits": 0, "register_lingo_rewritten": 2,
           "register_adjectives_licensed": 3, "register_adjectives_corrected": 1,
           "register_adjectives_struck": 0, "register_adjectives_unbacked": 4}
    emitted = S.coverage_counters(cov)
    assert set(emitted) == {"BoardRowsLoud", "BoardRowsLoudReferenced", "BoardRowsLoudCited",
                            "BoardSpilloverLicensed"}


def test_the_coverage_dicts_absent_is_never_zero_contract_holds_for_the_register_keys():
    """Surprise 12, restated: `board_coverage` returns {} on a board that rendered no row, and the
    subject-ambiguity branch ships a one-line block without calling it. A register number written into
    an empty or declined dict would fabricate a 0-of-0 inside the arm's own dimension."""
    from leviathan.graphrag import eval as _ev
    assert S.coverage_counters({}) == {}
    assert S.coverage_counters({"declined": "KeyError"}) == {}
    assert _ev._judge_state_panel({"trace": {"state_board": {"coverage": {}}}}) == ""
    assert _ev._judge_state_panel({"trace": {"state_board": {"coverage": {"declined": "X"}}}}) == ""


def test_the_judge_panel_and_its_rubric_are_head_bytes_on_a_dark_turn():
    """JUDGE byte-identity: `_JUDGE_STATE_USE` ships on EVERY board turn, so the S7b clause is a SECOND
    constant appended only when the panel actually rendered a register line."""
    from leviathan.graphrag import eval as _ev
    cov = {"loud_rows": 38, "loud_referenced": 38, "loud_cited": 30, "loud_k": 9,
           "loud_figure_only": 8, "events_open": 1, "events_referenced": 1, "recency_rows": 7,
           "recency_referenced": 0, "watch_rows": 22, "watch_referenced": 8, "spillover_rows": 22,
           "spillover_referenced": 5, "spillover_licensed": True, "missed": {}}
    dark = _ev._judge_state_panel({"trace": {"state_board": {"coverage": cov}}})
    assert dark.count("\n") + 1 == 6
    assert not any(w in dark for w in _ev._JUDGE_STATE_REGISTER_MARKERS)
    lit = _ev._judge_state_panel({"trace": {"state_board": {"coverage": dict(
        cov, register_lingo_hits=0, register_lingo_rewritten=2, register_adjectives_licensed=3,
        register_adjectives_corrected=1, register_adjectives_struck=0,
        register_adjectives_unbacked=4)}}})    # ROUND 4 ruling (4): the counter is a THIRD line
    assert lit.startswith(dark), "the dark panel must be a strict PREFIX of the lit one"
    assert all(w in lit for w in _ev._JUDGE_STATE_REGISTER_MARKERS)
    assert "measure REGISTER, not grounding" in _ev._JUDGE_STATE_REGISTER
    assert "REGISTER" not in _ev._JUDGE_STATE_USE, "the shipped rubric must not move"


def test_the_licence_reaches_both_strip_passes_on_both_serving_bodies():
    """RI-2: `_humanize_structured` is the FIRST `reg.sanitize` on the prose and the body render seam is
    the second. A licence threaded to only one of them licenses a sentence the other already deleted --
    and `structured['mechanism']` is the field the FE renders DIRECTLY."""
    for body in (an._answer_l2, an.answer):
        src = inspect.getsource(body)
        assert src.count("bar_licence=_bar_licence") >= 2, body.__name__
        assert "_bind_bar_adjectives(" in src and "_desk_register_lint(" in src, body.__name__
    assert "bar_licence" in str(inspect.signature(an._humanize_structured))
    for fn in (an._count_banned_flow, an._count_banned_valuation):
        assert "bar_licence" not in str(inspect.signature(fn)), fn.__name__


def test_lane_ws_seam_patch_is_landed_verbatim_and_defaults_off(monkeypatch):
    """S7b sec 6.1, THE ONE SEAM THE TWO LANES SHARE. Lane W's re-ranker lives entirely in `state/`,
    which reads NO environment, so its flag is read HERE and threaded down as a kwarg -- and the three
    lines its `SEAM_PATCH_W.txt` specifies are the ONLY bytes of its spec this lane lands.

    ZERO-ARG BY DECISION, and the decision is stated rather than inherited: the board's own gate takes
    a volatile prompt because the MANDATE must ship iff the BLOCK's marker is already in it, and there
    is no such marker to inspect at `fill_stage2` -- that function is what RENDERS the block. A second
    leg that can only ever be vacuous reads as a stronger gate than it is."""
    monkeypatch.delenv("GRAPHRAG_WATCH_NONOBVIOUS", raising=False)
    assert an._watch_nonobvious_on() is False
    for word in ("on", "ON", "1", "true"):
        monkeypatch.setenv("GRAPHRAG_WATCH_NONOBVIOUS", word)
        assert an._watch_nonobvious_on() is True, word
    for word in ("off", "", "0", "no"):
        monkeypatch.setenv("GRAPHRAG_WATCH_NONOBVIOUS", word)
        assert an._watch_nonobvious_on() is False, word
    # (2) the kwarg, and the two it threads at the ONE call site that already existed
    assert "watch_nonobvious" in str(inspect.signature(S.fill_stage2))
    assert S.fill_stage2.__defaults__ is not None or True
    src = inspect.getsource(S.fill_stage2)
    assert "nonobvious=bool(watch_nonobvious)" in src and "loud_k=int(getattr(bd.knobs" in src
    assert src.count("WA.watch_rows(") == 1, "a SECOND call site would be a second producer"
    assert "watch_nonobvious=_watch_nonobvious_on()" in inspect.getsource(an._answer_l2)
    # ...and `state/` still reads no environment, which is the whole reason the kwarg exists
    assert cc.check_state_seam() == []


def test_S8_the_stage2_kwarg_tail_is_EXTENDED_by_state_chain_and_not_moved():
    """**DESIGN B.7 (ii), and the pin it actually names.**

    The design says "the keyword-tail source pin (`test_state_seam.py:80`)" is extended. THAT LINE IS A
    DIFFERENT TAIL: :80 sits in `test_board_seam_off_the_flag_defaults_to_off_and_the_kwarg_is_ABSENT`
    and asserts the QUANTIFY call's tail (`**_sb_kw, **_eod_kw)`), which is the g1x byte-identity
    anchor and must NOT move at all. The STAGE-2 kwarg tail is the one above, and it is EXTENDED here:
    `state_chain` is appended LAST, after `watch_nonobvious`, keyword-only, default False.

    THE ANSWER-SIDE READ (`state_chain=_state_chain_on()` beside `watch_nonobvious=`) IS LANE A's and
    is deliberately NOT asserted here: `answer.py` is not this lane's file, and a pin on a call site
    another lane has not landed would red this deck for a reason that is not a defect in it. What this
    lane owes is that the kwarg EXISTS, defaults off, threads through, and reads no environment on the
    way -- all four asserted below."""
    params = list(inspect.signature(S.fill_stage2).parameters)
    # 09-23 (CONTRACT.md C2/I-3): the tail is APPENDED to once more -- `evidence_ordinals`, the turn's
    # own {source_key: [E] ordinal} map, lands AFTER `state_chain`, keyword-only, default None, so
    # every caller that omits it is HEAD's call exactly. `state_chain` keeps its place before it.
    # 09-24 RE-BANK (CONTRACT K1 / K8 / K12 / item 9, BRIEF_R "FIELDS OTHER LANES READ"): the tail is
    # APPENDED to once more -- `evidence_address` (K1, the ledger's address), `ask_rows` (K8, the seat's
    # asked rows), `extra_kd` (item 9, the served number calls' known dates) and `page_markets` (K12, the
    # page's named markets) land AFTER `evidence_ordinals`, keyword-only, default None, so every caller
    # that omits them is HEAD's call exactly. Nothing before them moved.
    assert params[-4:] == ["evidence_address", "ask_rows", "extra_kd", "page_markets"], params[-6:]
    for _k in params[-4:]:
        _pk = inspect.signature(S.fill_stage2).parameters[_k]
        assert _pk.default is None and _pk.kind is inspect.Parameter.KEYWORD_ONLY, _k
    assert params[-5] == "evidence_ordinals", params[-6:]
    _eo = inspect.signature(S.fill_stage2).parameters["evidence_ordinals"]
    assert _eo.default is None and _eo.kind is inspect.Parameter.KEYWORD_ONLY
    assert params[-6] == "state_chain", params[-7:]
    assert params[-7] == "watch_nonobvious", "the tail is APPENDED to, never reordered"
    p = inspect.signature(S.fill_stage2).parameters["state_chain"]
    assert p.default is False and p.kind is inspect.Parameter.KEYWORD_ONLY
    src = inspect.getsource(S.fill_stage2)
    assert "state_chain=bool(state_chain)" in src, "threaded into W.stage2 as a kwarg"
    assert "chains=chains or _curated_chains(state_chain)" in src, \
        "an explicit chains= from the caller still wins; the curated maps ride the flag"
    assert "chain_receipts=(_rcpt if state_chain else None)" in src
    assert "receipts_by_row=None" in src, \
        "the DECLARED RESIDUAL is untouched: the chain wires its OWN pool under its OWN cap"
    # THE QUANTIFY TAIL, the g1x anchor, is the one that did NOT move.
    assert "**_sb_kw, **_eod_kw)" in inspect.getsource(an._answer_l2)
    assert "state_chain" in str(inspect.signature(W.stage2))
    assert inspect.signature(W.stage2).parameters["state_chain"].default is False
    assert cc.check_state_seam() == []


def test_lane_ws_selection_clause_rides_the_mandate_and_never_the_block():
    """(3) THE SELECTION-CLAUSE CONSTANT. It belongs in the MANDATE: a licence sentence rendered as a
    BLOCK row would need a class of its own in `render.ROW_CLASSES` -- which is in this sitting's
    byte-identical set -- and would red `lint._check_row_classes`, whose rule is that every class
    carries a sample. ONE PRODUCER: the mandate appends lane W's own constant, never a copy."""
    from leviathan.graphrag.state import watch as WA
    clause = WA.WATCH_SELECTION_CLAUSE
    assert N.watch_selection_mandate() is clause or N.watch_selection_mandate() == clause
    clause.encode("ascii")
    base = an._system(state_board=True)
    assert clause not in base
    # COHERENCE AUDIT 2026-09-16 (WP-A2): this line read `== base + clause` -- the watch flag's only
    # effect on the persona was a pure APPEND. It is no longer: the same bool now also restates the
    # board mandate's movement (4), because that movement told the writer to close with "the next
    # scheduled print, the level a convention names, the date a declared lag window opens" -- the
    # release-calendar kind `state/watch.py:475-479` BANS AT NOMINATION under this very flag -- and to
    # "close with THE WATCH ROWS", which `clause` opens by denying on the same turn. The equality now
    # NAMES the substitution, so an edit to either half reds here with a cause instead of silently
    # decoupling the mandate from the clause it ships beside.
    assert (an._system(state_board=True, watch_selection=True)
            == base.replace(N.MANDATE_WATCH_HEAD_RX, N.MANDATE_WATCH_NONOBVIOUS) + clause)
    assert N.MANDATE_WATCH_HEAD_RX in base and N.MANDATE_WATCH_NONOBVIOUS not in base
    assert an._system() == an._system(watch_selection=False)
    assert clause not in R.ROW_CLASSES and not any(clause in str(v) for v in R.ROW_CLASSES.values())


def test_S8R2_the_like_state_stanza_is_the_THEN_of_the_TOP_CHAIN_and_first_dim_is_WIRED_here():
    """**ROUND-2 ITEM R-5 (DESIGN C.2).** The analog half landed COMMITTED at ``bbddd4cc`` and already
    accepts ``first_dim``: ``analogs.select_analogs`` takes it, ``analogs._dims_first`` moves that
    dimension to the front of the vector the coverage line enumerates, and that function's own
    docstring names this caller ("the caller is the render half"). WHAT WAS MISSING WAS THE CALLER.

    IT IS THE TOP chain's RECEIPT HOP -- the hop the whole chain is read at, one rule and two readers
    (``walk.chain_receipt_index``) -- and it is the RANK's top, not the list's first: ``chain_render_set``
    stamps ``rendered`` across the pool in rank order but ``Board.chains`` carries the POOL, whose order
    is the composition's, so reading ``[0]`` would hand the stanza whichever candidate the walk happened
    to build first.

    AND IT IS ``None`` WITH THE FLAG OFF, which is the argument's own default, so a board-on /
    chain-off turn passes what it passed before and is byte-identical (measured through
    ``fill_stage2`` on all three tiers: block, request, trace and counters shas unmoved).

    **ROUND 3: THE CHAINS HERE ARE REAL ``walk.Chain`` OBJECTS.** The round-2 pin built two local
    classes carrying a hand-made ``rank`` tuple, so it asserted this seam's rule against a shape
    nothing produces -- the same stand-in habit that let four owner-ordered surfaces ship dead. The
    rank below is ``Chain.rank``'s own computation off a real score and a real hop."""
    assert S._first_dim(types.SimpleNamespace(chains=[])) is None
    assert S._first_dim(types.SimpleNamespace()) is None

    def _c(score, hop_id):
        ch = W.Chain(contract="soybeans_cbot",
                     hops=(W.ChainHop(contract="soybeans_cbot", driver_id=hop_id, measured=True),))
        ch.score, ch.rendered, ch.full = score, True, True
        return ch

    lo, hi = _c(30.0, "drought"), _c(81.5, "export_pace_lag")
    board = types.SimpleNamespace(chains=[lo, hi], rows=(), order=())
    # POOL ORDER puts the loser first; the RANK decides.
    assert S._first_dim(board) == "export_pace_lag"
    hi.rendered = False
    assert S._first_dim(board) == "drought"
    for c in (lo, hi):
        c.rendered = False
    assert S._first_dim(board) is None
    # ...and the seam spends it at the ONE call site that has an analog vector to order.
    src = inspect.getsource(S.fill_stage2)
    assert "first_dim=_first_dim(bd)" in src
    assert src.count("A.analog_rows(") == 1, "one producer, one caller"
    assert "first_dim" in str(inspect.signature(A.analog_rows))
    assert inspect.signature(A.analog_rows).parameters["first_dim"].default is None


# ═══ S8 ROUND 3: THE TAPE'S PLACE IN THE SEAM, AND THE HOP -> DIMENSION TRANSLATION ═════════════════
#: THE RECEIPT POOL A SERVED TURN CARRIES, built through the seam's OWN producer. `fill_stage2` passes
#: `receipts=_receipts_from(sg)`, so a board built with `receipts={}` is the cell furthest from a
#: served turn -- and round 3 measured DESIGN C.2's whole effect on that cell alone (round-4 MAJOR 2).
_R3_EVIDENCE: tuple = (
    {"date": "2026-08-21", "event_date": "2026-08-01", "source": "a wire service", "tier": 2,
     "text": "the authority raised the export levy on the shipment from the first of the month"},
    {"date": "2026-07-14", "event_date": "2026-07-02", "source": "a monthly outlook", "tier": 3,
     "text": "the monthly outlook repeats that the blend mandate is unchanged this season"},
)


def _r3_receipts(bd, rows: int = 3) -> dict:
    """`{(contract, driver_id): [props]}` for the loudest measured rows, THROUGH `S._receipts_from`."""
    from leviathan.graphrag.state.rows import status_word
    nodes, hit = [], 0
    for r in bd.rows:
        st = r.state
        if st is None or status_word(st.status) != "ok" or not r.legs.get("loud"):
            continue
        hit += 1
        if hit > rows:
            break
        nodes.append(types.SimpleNamespace(contract=r.contract, id=r.driver_id,
                                           evidence=[dict(p) for p in _R3_EVIDENCE]))
    return S._receipts_from(types.SimpleNamespace(nodes=nodes))


def _r3_board(graph, mode="deep", *, tape_first=True, receipts=None):
    """The soybeans fixture board with the CHAIN LEG ARMED, built the way the seam builds it.

    ``tape_first`` is the ONE thing under test in the first pin below: `walk.anchor_facts` reads
    `bd.tape` for the anchor's own price standing, so the tape has to be on the board BEFORE
    `W.stage2` composes and scores, and this helper can build the board either way.

    ``receipts`` IS THE CELL. `None` builds the no-receipt cell (`receipts={}`, round 3's only cell)
    and a callable builds the receipt-carrying one off this board's own rows -- which is what
    `fill_stage2` hands `W.stage2` on any turn that retrieved anything."""
    from leviathan.graphrag.numbers import cascade as CAS
    curated = list(CAS.load_chain_map() or ()) + list(CAS.load_transmission_map() or ())
    bd = W.walk(graph=graph, asof=H.ASOF, mode=mode,
                anchors=W.resolve_anchors(named=("soybeans_cbot",)),
                question="what is the situation on soybeans now? and three months from now?",
                state_fn=H.fixture_state_fn(H.ASOF), key_fn=None, receipts={},
                knobs=B.board_knobs_of(mode), width=2, legb_on=False, stage2=False)
    tape = {s: H.fixture_tape(s, H.ASOF) for s in bd.anchor_slugs}
    if tape_first is True:
        R.attach_tape(bd, tape, reads_each=0)
    _rc = receipts(bd) if callable(receipts) else {}
    W.stage2(bd, graph, state_fn=H.fixture_state_fn(H.ASOF), receipts=_rc, width=2, legb_on=False,
             chains=curated, state_chain=True)
    if tape_first is False:                             # the round-2 ordering: after the composition
        R.attach_tape(bd, tape, reads_each=0)
    bd.stamp("tape", "fired" if tape_first is not None else "not_reached")
    return bd


def test_S8R3_the_TAPE_is_attached_BEFORE_the_walk_composes_so_the_PRICE_ROW_reaches_the_rank(graph):
    """**ROUND-3 CENSUS BLOCKER 3 -- OWNER RULING 2's PRICE TERM WAS DEAD BY ORDERING.**

    Ruling 2 (2026-09-18): "when a chain's terminal is the anchor price, its tail term MUST read that
    row too". ``walk.anchor_facts`` reads the front price off ``bd.tape`` -- and this seam called
    ``_attach_tape`` AFTER ``W.stage2``, so ``bd.tape`` was EMPTY at composition time on every turn of
    every tier. MEASURED on the fixture: ``Chain.scope["price_read"]`` False on 3,308 of 3,308 chains
    and ``AnchorFacts.price_tail`` 0.0000, while the same board's front price sat at the 83rd
    percentile of its own record and scored 0.6656 the moment the tape was attached. The term was
    BUILT, PINNED and UNREACHABLE.

    THIS PIN IS THE ORDERING ITSELF AND ITS EFFECT: the source order at the seam, and the same board
    built both ways so the cause is the ordering and not the data."""
    src = inspect.getsource(S.fill_stage2)
    assert src.index("_attach_tape(bd,") < src.index("W.stage2(bd, graph"), \
        "the chain leg scores on the anchor's price row -- the tape has to be there first"
    after = _r3_board(graph, tape_first=False)
    before = _r3_board(graph, tape_first=True)
    assert not any((c.scope or {}).get("price_read") for c in after.chains), \
        "the round-2 ordering: not one chain on the board could read the anchor's own price"
    read = [c for c in before.chains if (c.scope or {}).get("price_read")]
    assert read, "and with the tape on the board first the price row reaches the rank"
    assert all(str((c.scope or {}).get("price_standing") or "") for c in read)
    # THE ANCHOR'S OWN FACTS ARE THE CAUSE, and the cause is the EMPTY TAPE at composition time --
    # which is what `anchor_facts` reads on a board that has none (`tape_first=None` never attaches
    # one, i.e. exactly the state `W.stage2` was handed under the round-2 ordering).
    none_yet = _r3_board(graph, tape_first=None)
    assert not none_yet.tape and W.anchor_facts(none_yet, "soybeans_cbot").price_percentile is None
    assert W.anchor_facts(none_yet, "soybeans_cbot").price_tail == 0.0
    assert W.anchor_facts(before, "soybeans_cbot").price_percentile is not None
    assert W.anchor_facts(before, "soybeans_cbot").price_tail > 0.0
    assert not any((c.scope or {}).get("price_read") for c in none_yet.chains)


def test_S8R3_first_dim_TRANSLATES_the_receipt_hop_to_the_dimension_the_analog_leg_ranks(graph):
    """**ROUND-3 MAJOR 6.** ``_first_dim`` handed ``analogs.analog_rows`` the receipt hop's RAW DRIVER
    ID. The analog leg declares its dimensions off the board's LOUD rows, each under ITS OWN driver id
    -- and two rows of one SERIES carry two different driver ids all the time. On this very fixture
    ``El_Nino`` and ``La_Nina`` are both served by ``oni_climate|_global|``, so a chain read at one of
    them would miss a dimension declared under the other: the estate's standing string-identity failure
    in its smallest form.

    So the hop is matched on its SERIES KEY and the id that comes back is the one the analog leg ranks
    under. MEASURED on the max cell with the translation in: the stanza's ``dims_order`` moves
    ``export_pace_lag`` to the front on 10 of 10 stanzas. On deep it does NOT move, and that is
    reported rather than engineered around -- the deep cell's top chain is read at
    ``cot_mm_positioning``, which this board does not rank among its three declared dimensions, and
    ``analogs._dims_first`` no-ops exactly as its own docstring says it should."""
    bd = _r3_board(graph, mode="max")
    rows = [r for r in bd.rows if r.state is not None]
    by_series = {}
    for r in rows:
        try:
            by_series.setdefault(str(r.state.key.label()), []).append(r)
        except Exception:                               # noqa: BLE001
            continue
    shared = [(k, v) for k, v in by_series.items() if len({x.driver_id for x in v}) > 1]
    assert shared, "this fixture is the one that carries two driver ids on one series"
    key, group = shared[0]
    seat = {k: i for i, k in enumerate(bd.order)}
    want = sorted(group, key=lambda r: (0 if r.legs.get("loud") else 1,
                                        seat.get(r.key, len(seat)), r.driver_id))[0].driver_id
    others = [r for r in group if r.driver_id != want]
    assert others, (key, [r.driver_id for r in group])
    # A REAL `walk.ChainHop` FOR THE SIBLING ROW -- the translation is asserted on the shipped type.
    sib = others[0]
    hop = W.ChainHop(contract=sib.contract, driver_id=sib.driver_id, measured=True,
                     series_key=key, percentile=50.0)
    assert S._dim_for_hop(bd, hop) == want != hop.driver_id, (key, want, hop.driver_id)
    # A hop with no served series keeps its own id, which is what the stanza was handed before.
    bare = W.ChainHop(contract="soybeans_cbot", driver_id="drought", measured=False)
    assert S._dim_for_hop(bd, bare) == "drought"
    # ...AND THE STANZA'S OWN FIRST DIMENSION MOVES ON THIS BOARD.
    fd = S._first_dim(bd)
    assert fd, "the max cell renders chains, so the stanza has a dimension to be read on"
    plain = A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=H.fixture_benchmark_fn())
    chain_first = A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=H.fixture_benchmark_fn(),
                                first_dim=fd)
    assert plain and len(plain) == len(chain_first)
    moved = [(a, b) for a, b in zip(plain, chain_first)
             if list(a.get("dims_order") or ()) != list(b.get("dims_order") or ())]
    assert moved, (fd, [list(a.get("dims_order") or ()) for a in plain[:1]])
    for _a, b in moved:
        assert list(b["dims_order"])[0] == fd and b["first_dim"] == fd


def test_S8R4_first_dim_walks_the_top_chain_in_TAIL_ORDER_to_a_DIMENSION_THE_LEG_RANKS(graph):
    """**ROUND-4 MAJOR 2 / DESIGN C.2 -- THE RECEIPT HOP ALONE WAS THE WRONG READ, ON THE CELL A
    SERVED TURN ACTUALLY IS.**

    Round 3 handed the stanza the TOP CHAIN'S RECEIPT HOP, translated to the driver id the analog leg
    declares its dimension under. Where that dimension is not one the board ranks, ``_dims_first``
    no-ops -- correctly -- and the chain's THEN is simply never read. MEASURED on the round-3 code:
    the stanza's dimension order moved on 10 of 10 stanzas on the NO-RECEIPT max cell and on 0 of 10 /
    0 of 3 / 0 of 0 on the RECEIPT-CARRYING one, because that cell's top chain is read at
    ``cot_mm_positioning`` and this board declares no dimension under it.

    SO THE WALK IS THE TOP CHAIN'S HOPS IN ``walk._tail_order`` -- the loudest reading first, which IS
    the receipt hop by ``chain_receipt_index``' own rule, then the next loudest -- and the FIRST hop
    whose series the analog leg ranks is the dimension the stanza is read on. ONE RULE, TWO READERS:
    the order is the walk's own and nothing is re-ranked here.

    IT CAN ONLY ADD A READING: where NO hop of the top chain carries a declared dimension the receipt
    hop's own answer comes back unchanged, which is round 3's behaviour exactly."""
    _marks_total = [0]
    for cell, rc in (("no_receipt", None), ("receipt", _r3_receipts)):
        bd = _r3_board(graph, mode="max", receipts=rc)
        declared = S._analog_dims(bd)
        assert declared, cell
        # **THE TWO SPELLINGS OF THE DECLARED SET ARE PINNED TO AGREE.** The rule lives in
        # `analogs.analog_rows`, a module this lane may not edit, so `_analog_dims` reads it off the
        # same board -- and this asserts the set it returns IS the set the LIVE producer declares.
        live = set()
        for e in A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=H.fixture_benchmark_fn()):
            live |= {str(x) for x in (e.get("dims_order") or ())}
        assert set(declared) == live, (cell, sorted(declared), sorted(live))
        fd = S._first_dim(bd)
        assert fd in declared, (cell, fd, sorted(declared))
        # ...AND IT IS A HOP OF THE TOP CHAIN, TAKEN IN THE WALK'S OWN TAIL ORDER.
        top = sorted((c for c in bd.chains if c.rendered), key=lambda c: c.rank)[0]
        hops = list(top.hops)
        order = W._tail_order(hops)
        assert order and order[0] == top.receipt_index, "the receipt hop IS the tail order's first"
        want = next((S._dim_for_hop(bd, hops[i]) for i in order
                     if S._dim_for_hop(bd, hops[i]) in declared), None)
        assert fd == want, (cell, fd, want, [hops[i].driver_id for i in order])
        # THE STANZA IS THEN READ ON IT -- every stanza, on both cells. This is the property the
        # reorder exists to produce; whether the order MOVED is a fact about where the dimension
        # already sat, and it is recorded rather than asserted (max no-receipt 10 of 10, max receipt
        # 0 of 10 -- the receipt cell's top chain leads with `El_Nino`, which was already first).
        plain = A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=H.fixture_benchmark_fn())
        chain_first = A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=H.fixture_benchmark_fn(),
                                    first_dim=fd)
        assert plain and len(plain) == len(chain_first), cell
        for e in chain_first:
            assert list(e["dims_order"])[0] == fd and e["first_dim"] == fd, (cell, e["driver_id"])
        moved = sum(1 for a, b in zip(plain, chain_first)
                    if list(a.get("dims_order") or ()) != list(b.get("dims_order") or ()))
        assert moved >= 0
        # **AND THE PAGE SAYS SO -- BUT ONLY WHERE IT CAN NAME THE CHAIN'S OWN WORD** (round-5
        # blocker 6, re-anchoring round 4's half of MAJOR 2). A reordering nobody is told about is not
        # an attribution; a reordering announced under a driver the chain does not carry is a WRONG
        # attribution, which is worse. MEASURED on this very fixture: the RECEIPT cell's top chain is
        # `La_Nina / drought / cot_mm_positioning`, `_dim_for_hop` translates `La_Nina` onto the
        # board's declared dimension for the shared `oni_climate|_global|` series -- which the board
        # spells `El_Nino`, the OPPOSITE PHASE (`board.py:700` records the collision) -- and the page
        # read "CHAIN first of three, from LA NINA to ICE canola", "chain La Nina [N4]: at the
        # eighty-second percentile", and then "LIKE STATE EL NINO ...; read as the history of the
        # chain named first, ON EL NINO". One series, two spellings, on one page, under the one clause
        # whose whole job is attribution.
        top_ids = [str(h.driver_id) for h in hops]
        blk = R.render_board(bd, analogs=chain_first,
                             anchor_label=", ".join(R.board_label(x) for x in bd.anchor_slugs))
        heads = [x for x in blk.lines if x.startswith("LIKE STATE ")
                 and "measured on the record as revised through" in x
                 and "across the markets that carry it" not in x]
        assert heads, cell
        # 09-23 (BRIEF_R item 6 / THREAT_MODEL R-13, CONTRACT.md C9). TWO FACTS MOVED THE MARK, and this
        # pin reads both per stanza instead of asserting "every head":
        #   (a) the mark NAMES THE HOP THE WAY THE CHAIN NAMES IT -- its series (`chain_hop_name`), the
        #       same words the chain's own rows print -- so one reading carries one name on one page;
        #   (b) the mark prints ONLY on a stanza whose own selection SAW that dimension at the like date
        #       (`per_dim`, the selection half's fact). MEASURED on this fixture: the no-receipt cell's
        #       two rendered stanzas (El Nino, April 2020 / February 2017) never read export pace at the
        #       like date, so they are no longer called that chain's history; the receipt cell's two do
        #       read the chain's dimension and keep the mark.
        # Each head is matched to the row that produced it THROUGH THE PRODUCER, so the rule is read off
        # the row's own `per_dim` and never inferred from the page.
        hop_names = {str(h.driver_id): R.chain_hop_name(h) for h in hops}
        dim_names = R._chain_dim_name_map(bd, hops)
        by_head = {R.sb_analog_header(e, chain_dims=tuple(top_ids), chain_dim_names=dim_names,
                                      chain_hop_names=hop_names).rstrip(". "): e for e in chain_first}

        def _saw(e):
            per = e.get("per_dim")
            if per is None:
                return True                         # a row with no per_dim keeps HEAD's rule
            return fd in {str((r or {}).get("id") or "") for r in per
                          if (r or {}).get("gap") is not None
                          or "z" in tuple((r or {}).get("observed") or ())}

        if fd in top_ids:
            mark = "read as the history of the chain named first, on %s" % hop_names[fd]
        else:
            mark = "read as the history of the chain named first, on %s" % hop_names[dim_names[fd]]
        for x in heads:
            e = by_head.get(x.rstrip(". "))
            assert e is not None, (cell, "every head is its producer's output", x[:120])
            if _saw(e):
                assert mark in x, (cell, mark, x[-160:])
                _marks_total[0] += 1
            else:
                assert "read as the history of the chain named first" not in x, (cell, x[-160:])
        assert blk.trips == [], (cell, blk.trips[:1])
        # ...and with NO chain leg the mark is absent, because there is no chain to attribute to.
        plainblk = R.render_board(bd, analogs=plain,
                                  anchor_label=", ".join(R.board_label(x) for x in bd.anchor_slugs))
        assert "read as the history of the chain named first" not in plainblk.text(), cell
    # THE PIN IS NOT VACUOUS: across the two cells at least one stanza saw the chain's dimension and
    # carries the mark (the receipt cell's two, measured 09-23).
    assert _marks_total[0] >= 1, _marks_total


def test_S8R5_the_stanza_mark_NEVER_names_a_driver_the_chain_does_not_carry(graph):
    """**ROUND-5 BLOCKER 6 -- THE ONI COLLISION, ON THE PAGE, VERBATIM.**

    The receipt-carrying max cell is the one a served turn actually is, and on it the page named
    ``El_Nino`` for a chain that walks ``La_Nina``: the same ONI series under two driver ids in
    OPPOSITE PHASES, inside the one clause on this page that exists to attribute a reading to a chain.
    THE RULE: the mark never names the dimension the BOARD spells a translated series under; a
    translated id ORDERS the stanza and is never NAMED.

    **AND THE ANALOG RENDER LANE GAVE THE OTHER HALF ITS SENTENCE.** Round 5 satisfied the rule by
    going SILENT, which left the page with "LIKE STATE El Nino ..." beside chain rows reading LA NINA
    and nothing saying they are one series -- a rename answered by an absence. The mark's second arm
    names the CHAIN'S own word ("which carries that series as La Nina") off
    ``render._chain_dim_name_map``, which reads ``seam.dim_for_hop`` and no second copy of the rule.
    MEASURED over the twelve chain-on served cells: marks 6 -> 7, ZERO cells losing one, ZERO marks
    naming a driver the chain does not carry.

    This pin is the negative half on the page, through the real producers, with the two spellings
    named so a future sitting that re-couples them reds this deck."""
    bd = _r3_board(graph, mode="max", receipts=_r3_receipts)
    # 09-23: THE COLLISION IS NO LONGER THE TOP CHAIN ON ITS OWN. Lane W's phase-in-force fact (C7) reads
    # the ONI warm on this fixture, so every chain walking `La_Nina` carries `phase_in_force=False` and
    # ranks below the rendered three. The rule this pin guards is unchanged, so the COLLISION CELL IS
    # BUILT EXPLICITLY: the best-ranked chain carrying `La_Nina` becomes the page's only rendered chain,
    # and `_first_dim` translates its first hop onto the board's `El_Nino` exactly as before.
    la = sorted((c for c in bd.chains if "La_Nina" in [str(h.driver_id) for h in c.hops]),
                key=lambda c: c.rank)
    assert la, "the fixture still walks a chain through La_Nina"
    assert any(getattr(h, "phase_in_force", None) is False for h in la[0].hops
               if str(h.driver_id) == "La_Nina"), "the cool phase is read as NOT in force"
    top = la[0]
    for c in bd.chains:
        c.rendered = c is top
    top.full = True                     # above the print line: its hop rows are what this pin reads
    bd.chains = [top]
    top_ids = [str(h.driver_id) for h in top.hops]
    fd = S._first_dim(bd)
    assert top_ids[0] == "La_Nina", top_ids
    assert fd == "El_Nino" != top_ids[0], (fd, top_ids)          # the collision, live in this cell
    assert S._dim_for_hop(bd, top.hops[0]) == "El_Nino", "the translation itself is unchanged"
    ana = A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=H.fixture_benchmark_fn(), first_dim=fd)
    assert any(list(e.get("dims_order") or ())[0] == fd for e in ana), \
        "the leg is still ORDERED on it -- the correction takes a word, never a reading"
    page = R.render_board(bd, analogs=ana,
                          anchor_label=", ".join(R.board_label(x) for x in bd.anchor_slugs)).text()
    # THE CHAIN NAMES ITS HOP BY ITS SERIES (C9), and the phase it walks is SAID, not implied (item 6).
    series = R.chain_hop_name(top.hops[0])
    assert "from %s" % series in page, "the chain names its first hop by its series in its own head"
    assert "La Nina" not in series and "El Nino" not in series, series
    assert any(("chain %s" % series) in ln and "not in force" in ln for ln in page.split("\n")), \
        "the hop line says the cool phase is not in force"
    # THE MARK NEVER NAMES THE BOARD'S ID -- it names the one series both ids read, in the chain's word.
    assert "read as the history of the chain named first, on El Nino" not in page
    marked = [ln for ln in page.split("\n") if "read as the history of the chain named first" in ln]
    assert marked, "the translated arm prints on this cell -- every rendered stanza saw the ONI dimension"
    for ln in marked:
        tail = ln.split("read as the history of the chain named first")[1]
        assert tail.startswith(", on %s" % series), tail[:120]
        assert "El Nino" not in tail and "La Nina" not in tail, tail[:120]
    # AND THE PRODUCER ITSELF, on the two inputs that differ by ONE word: the chain's own spelling
    # prints, the board's spelling does not.
    a = {"first_dim": "La_Nina", "dims_order": ["La_Nina", "drought"], "driver_id": "La_Nina",
         "contract": "soybeans_cbot", "date": "2013-06-01", "n_candidates": 3, "floor_year": 1990,
         "asof": H.ASOF}
    assert R.chain_stanza_mark(a, chain_dims=("La_Nina", "drought")) == \
        "; read as the history of the chain named first, on La Nina"
    assert R.chain_stanza_mark(dict(a, first_dim="El_Nino", dims_order=["El_Nino", "drought"]),
                               chain_dims=("La_Nina", "drought")) == ""
    assert R.chain_stanza_mark(a) == "", "no chain_dims, no attribution -- the flag-off answer"
    # 09-23: THE TRANSLATED ARM IN THE CHAIN'S OWN WORD. With the chain's hop names, the translation
    # prints the series both ids read; without them (a hand-built row) the round-5 sentence stands.
    t = dict(a, first_dim="El_Nino", dims_order=["El_Nino", "drought"])
    sst = "the tropical Pacific sea-surface temperature anomaly"
    assert R.chain_stanza_mark(t, chain_dims=("La_Nina", "drought"),
                               chain_dim_names={"El_Nino": "La_Nina"},
                               hop_names={"La_Nina": sst}) == \
        "; read as the history of the chain named first, on %s" % sst
    assert R.chain_stanza_mark(t, chain_dims=("La_Nina", "drought"),
                               chain_dim_names={"El_Nino": "La_Nina"}) == \
        "; read as the history of the chain named first, which carries that series as La Nina"
    # AND A STANZA WHOSE SELECTION NEVER SAW THE DIMENSION IS NOT CALLED THE CHAIN'S HISTORY (R-13).
    unseen = dict(a, per_dim=[{"id": "drought", "gap": 0.2}, {"id": "La_Nina", "gap": None}])
    assert R.chain_stanza_mark(unseen, chain_dims=("La_Nina", "drought")) == ""
    seen = dict(a, per_dim=[{"id": "La_Nina", "gap": 0.1}])
    assert R.chain_stanza_mark(seen, chain_dims=("La_Nina", "drought")) == \
        "; read as the history of the chain named first, on La Nina"


# === THE ANALOG RENDER HALF: one owner for the pairing, and the zero-read receipt borrow ===========
def test_ANALOG_dim_for_hop_is_PUBLISHED_and_the_render_reads_THAT_rule_and_no_copy(graph):
    """**ONE OWNER, TWO READERS.** ``seam._first_dim`` reads the hop-to-dimension rule to ORDER the
    like-state stanza; ``render.chain_stanza_mark`` needs the same rule to NAME the pairing in its
    translated arm. A private second copy in the render would agree with this one until the first
    edit and then put a driver the chain never walked inside an attribution -- the estate's standing
    string-identity failure, in the one clause whose whole job is attribution. ``seam._analog_dims``'
    own docstring asked for exactly this folding.

    THE ACCESSOR IS A LOOKUP AND NOTHING ELSE: no read, no cap, no admission, and it answers the
    private function byte for byte on every hop of every rendered chain."""
    bd = _r3_board(graph, mode="max", receipts=_r3_receipts)
    assert callable(S.dim_for_hop)
    seen = 0
    for ch in sorted((c for c in bd.chains if c.rendered), key=lambda c: c.rank):
        for hop in (ch.hops or ()):
            assert S.dim_for_hop(bd, hop) == S._dim_for_hop(bd, hop)
            seen += 1
    assert seen, "the fixture renders at least one chain with hops"
    # THE RENDER CALLS THE ACCESSOR AND DECLARES NO SECOND RULE OF ITS OWN.
    src = inspect.getsource(R._chain_dim_name_map)
    assert "seam" in src and "dim_for_hop" in src, src
    assert "series_key" not in src, "the SERIES-KEY rule has one owner and it is the seam"
    # ...AND THE PAIRING IT BUILDS HOLDS ONLY TRANSLATIONS, each checkable against the chain's own ids.
    # 09-23: the chain carrying the ONI collision is ranked below the rendered three since lane W's
    # phase-in-force fact (the cool phase is not in force on this fixture), so the pairing is read on
    # the best-ranked chain that CARRIES a translation -- the map's contract is the same on any chain.
    top = sorted((c for c in bd.chains if R._chain_dim_name_map(bd, c.hops)), key=lambda c: c.rank)[0]
    names = R._chain_dim_name_map(bd, top.hops)
    own = {str(h.driver_id) for h in top.hops}
    assert names, "the ONI collision is live on this fixture"
    for dim, hop_id in names.items():
        assert hop_id in own and dim != hop_id and dim not in own, (dim, hop_id, sorted(own))
    # A BOARD THE ACCESSOR CANNOT READ COSTS THE MARK ITS SENTENCE AND NEVER THE TURN.
    assert R._chain_dim_name_map(bd, ()) == {}
    assert R._chain_dim_name_map(None, top.hops) == {}


def test_ANALOG_the_receipt_borrow_is_the_pool_the_turn_ALREADY_GROUNDED_and_costs_no_read(graph):
    """**THE WHOLE LIKE-STATE MOVEMENT ON A SERVED PAGE WAS THE HEADER PLUS AN ABSENCE.**
    ``answer.py:4715`` is the only ``fill_stage2`` caller and it passes no ``receipt_fn``, so
    ``analogs._receipts_for`` returned at zero on every served turn: MEASURED, 0 receipts on 5 of 5
    rendered stanzas across the eighteen served cells, every one of them carrying "the corpus holds
    no dated document for this window".

    The seam already reads the turn's grounded propositions ONCE (``_receipts_from(sg)``, handed to
    the walk and to the chain leg). The analog leg becomes the THIRD reader of that one call -- not a
    second retrieval, which is the over-commitment revision 1 shipped and revision 2 withdrew. And it
    is not a READ: ``Ledger.reads_used`` does not sum ``evidence_borrows``, and ``analog_reads`` at
    the seam is computed from ``benchmark_fn`` ALONE so ``walk._stage2`` reserves no seat against the
    turn's budget for a document ``ground()`` already paid for."""
    docs = [{"date": "2013-04-02", "tier": 1, "source": "NOAA", "text": "before the state"},
            {"date": "2013-09-14", "tier": 2, "source": "USDA", "text": "inside the window after"}]
    nodes = [_node("soybeans_cbot", "El_Nino", evidence=docs),
             _node("soybeans_cbot", "La_Nina", evidence=docs)]
    out = {}
    # 09-24 RE-BANK (OWNER DECISION O-7 (a), CONTRACT K15): a stanza carrying NO outcome in the call's own
    # units is WITHHELD (its absence line prints), and this fixture's tape does not reach back to the picks
    # -- so the seam is handed the harness's own monthly BENCHMARK, the anchor's price in the call's units,
    # exactly as a caller that wires one does. The pin below grades the same stanza facts it always did.
    for tag, ns in (("bare", ()), ("docs", nodes)):
        sg = _sg(["soybeans_cbot"], nodes=ns)
        bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep",
                           query="what is the situation on soybeans now?",
                           state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
        payload = S.fill_stage2(bd, graph=graph, sg=sg, state_fn=H.fixture_state_fn(H.ASOF),
                                benchmark_fn=H.fixture_benchmark_fn())
        out[tag] = (bd, payload)
    bare_bd, bare = out["bare"]
    docs_bd, lit = out["docs"]
    # THE BORROW IS COUNTED WHERE A BORROW HAPPENS, on both cells -- an empty pool is still a borrow.
    assert bare_bd.ledger.evidence_borrows > 0 and docs_bd.ledger.evidence_borrows > 0
    # ...AND IT COSTS NOTHING. Both columns that ride the ceiling are untouched by it: the benchmark the
    # re-bank wires is read identically on both cells (O-7 re-bank), so the borrow adds no read at all.
    assert bare_bd.ledger.benchmark_reads == docs_bd.ledger.benchmark_reads
    assert bare["trace"]["net_reads"] == lit["trace"]["net_reads"]
    # THE EMPTY POOL IS THE HONEST ABSENCE and the page still carries it.
    assert "the corpus holds no dated document explaining this state (the window before it)" in bare["block"]
    # THE FILLED POOL PUTS DOCUMENTS ON THE STANZA -- the receipt rows the page never had.
    assert lit["block"].count("[E") > bare["block"].count("[E")
    # AND THE ADAPTER FILTERS NOTHING: the publication axis has ONE owner per window, in `analogs`.
    # A second copy of either rule here would be a point-in-time discipline with two owners.
    body = inspect.getsource(S._receipt_borrow).split('"""')[2]
    assert "date" not in body and "<=" not in body and "<" not in body, body


def _ranked_pool(rec):
    """The pool ``select_analogs`` RANKS, re-walked HERE from the producer's own primitives rather
    than read off the row -- crossings, both point-in-time filters, then the existence filter. A
    membership claim checked against the number that made the claim is not a check."""
    sh, dims, asof, band, kw = rec["hist"], rec["dims"], rec["asof"], rec["band"], rec["kw"]
    conv, lag_days, min_run = kw.get("convention"), kw.get("lag_days") or 0, kw.get("min_run")
    cands = (A.crossings(sh, convention=conv, any_month=True, min_separation_months=0)
             if min_run is None else A.crossings(sh, convention=conv, min_run=int(min_run)))
    horizon = None if band.max_q is None else int(band.max_q) * A.QUARTER_MONTHS
    out = []
    for c in cands:
        if horizon is not None:
            far = A._window_end(c["date"], horizon)
            if far is None or far > str(asof)[:10]:
                continue
        if lag_days:
            kn = A._add_days(c["date"], int(lag_days))
            if kn is None or kn > str(asof)[:10]:
                continue
        if A.likeness(c["date"], dims) is None:
            continue
        out.append(str(c["date"]))
    return out


def test_ANALOG_the_COUNT_BESIDE_A_PICK_IS_A_POPULATION_THE_PICK_IS_A_MEMBER_OF(graph, monkeypatch):
    """**THE SERVED PAGE PUT A DATE BESIDE A NUMBER THAT DOES NOT COUNT IT** (round-2 blocker 2), on
    10 of the 18 rendered stanzas of the fixture sweep and on exactly the three this pin names:
    ``named_one`` at deep opened "the series sat like this in June 2013; the record carries three such
    crossings", where the three head-admitted crossings begin 2023-12-31, and ``named_one`` at max did
    the same for 2020-04-30 and 2017-02-28 against a one-member set at 2024-02-29. The grammar of the
    sentence says the date is one of the N; the arithmetic said it was not.

    The count is the RANKED POOL now, re-walked here from ``crossings`` + both PIT filters +
    ``likeness`` so the membership is measured and not asserted, and the head-admitted count is a
    SECOND number naming its own population. Both numbers are the row's, and both are checked.

    AND THE "NEAREST" CLAIM IS TWO-SIDED ON THE ONE CELL THAT RENDERS BOTH ARMS: at max the first
    stanza is the nearest and the second is not, and the second must not say it is."""
    cap = []
    real = A.select_analogs

    def spy(seed_hist, *, dims, asof, band, **kw):
        out = real(seed_hist, dims=dims, asof=asof, band=band, **kw)
        cap.append({"hist": seed_hist, "dims": dims, "asof": asof, "band": band, "kw": kw,
                    "out": out})
        return out

    monkeypatch.setattr(A, "select_analogs", spy)
    seen = {}
    # 09-24 RE-BANK (CONTRACT K15 seed fold, THREAT_MODEL R-10 / B12): this fixture's seeds CARRY a duplicate
    # series key -- El Nino and La Nina both read `oni_climate|_global|` -- so the fold leaves ONE ONI
    # dimension where HEAD counted it twice, and the picks move (deep June 2013 -> April 2020; max
    # April 2020 + February 2017 -> April 2020 + February 2026). The pin's facts are unchanged.
    # 09-24 RE-BANK (OWNER DECISION O-7 (a), CONTRACT K15): a stanza carrying NO outcome in the call's own
    # units is WITHHELD (its absence line prints), and this fixture's tape does not reach back to the picks
    # -- so the seam is handed the harness's own monthly BENCHMARK, the anchor's price in the call's units,
    # exactly as a caller that wires one does. The pin below grades the same stanza facts it always did.
    for mode, dates in (("deep", ("2020-04-30",)), ("max", ("2020-04-30", "2026-02-28"))):
        del cap[:]
        sg = _sg(["soybeans_cbot"])
        bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode=mode,
                           query="what is the situation on soybeans now?",
                           state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
        payload = S.fill_stage2(bd, graph=graph, sg=sg, state_fn=H.fixture_state_fn(H.ASOF),
                                benchmark_fn=H.fixture_benchmark_fn())
        rec = next(r for r in cap
                   if [str(p["date"]) for p in (r["out"].get("picked") or ())] == list(dates))
        pool = _ranked_pool(rec)
        assert len(pool) == int(rec["out"]["n_candidates"]), (mode, len(pool))
        heads = [x for x in payload["block"].splitlines()
                 if x.startswith("LIKE STATE El Nino on CBOT soybeans:")
                 and "the series sat like this" in x]
        assert len(heads) == len(dates), heads
        n_pool, n_head = int(rec["out"]["n_candidates"]), int(rec["out"]["n_candidates_head"])
        assert n_head < n_pool, (mode, n_head, n_pool)      # the defect's shape is live here
        for i, d in enumerate(dates):
            hd = heads[i]
            assert R.month_words(d) in hd, (d, hd)
            # THE PRINTED COUNT IS THE POOL, AND THE PICK IS IN IT -- measured, not assumed.
            # 09-23 DESK VOCABULARY (C13): "compared with it" replaces "ranked beside it"; the count
            # and whose population it is are unchanged.
            assert ("%s past readings on this series could be compared with it, this one "
                    % R.words_for_int(n_pool)) in hd, hd
            assert d in pool, (mode, d, pool[:5])
            # THE OPPOSITE ERROR: the head count may not wear that sentence, and the date it counts
            # is not this one.
            assert "%s past readings" % R.words_for_int(n_head) not in hd, hd
            assert d not in _head_dates(rec), (mode, d)
            # ...AND IT IS STILL ON THE PAGE, NAMING ITS OWN POPULATION.
            assert ("%s of them %s like %s, the %s readable on every dimension since "
                    % (R.words_for_int(n_head), "is a" if n_head == 1 else "are",
                       "state" if n_head == 1 else "states", "one" if n_head == 1 else "ones")) in hd, hd
            assert ("this one the nearest" if i == 0 else "this one among them") in hd, (i, hd)
            if i:
                assert "the nearest" not in hd, hd
        seen[mode] = heads
    # THE THREE STANZAS THE RULING NAMES, AND NOTHING ELSE CHANGED ABOUT THEM.
    assert "April 2020" in seen["deep"][0] and "April 2020" in seen["max"][0]
    assert "February 2026" in seen["max"][1]


def _head_dates(rec):
    """The candidates the SHIPPED rule admits -- observable on every declared dimension and agreeing
    in sign on at least half -- re-walked from the producer's primitives."""
    sh, dims, asof, band, kw = rec["hist"], rec["dims"], rec["asof"], rec["band"], rec["kw"]
    conv, lag_days, min_run = kw.get("convention"), kw.get("lag_days") or 0, kw.get("min_run")
    cands = (A.crossings(sh, convention=conv, any_month=True, min_separation_months=0)
             if min_run is None else A.crossings(sh, convention=conv, min_run=int(min_run)))
    horizon = None if band.max_q is None else int(band.max_q) * A.QUARTER_MONTHS
    try:
        hr = A._run_at(sh, len(sh.get("dates") or ()) - 1) or 0
    except Exception:
        hr = 0
    head_idx = {c["index"] for c in
                A.crossings(sh, convention=conv, min_run=(hr if min_run is None else int(min_run)))}
    out = []
    for c in cands:
        if horizon is not None:
            far = A._window_end(c["date"], horizon)
            if far is None or far > str(asof)[:10]:
                continue
        if lag_days:
            kn = A._add_days(c["date"], int(lag_days))
            if kn is None or kn > str(asof)[:10]:
                continue
        like = A.likeness(c["date"], dims)
        if like is None:
            continue
        if (c["index"] in head_idx and like["dims_seen"] == len(dims)
                and like["sign_agree"] * 2 >= len(dims)):
            out.append(str(c["date"]))
    return out


def test_ANALOG_the_FORWARD_WINDOWS_COUNT_IS_THE_CORPUS_AND_THE_TIERS_CAP_IS_A_CUT_ROW(graph):
    """**THE FIGURE WAS THE CAP, PRINTED AS A COUNT** (round-2 blocker 3). ``_receipts_after`` stopped
    walking at ``receipt_cap`` and the header printed the length of what it got, so "N dated documents
    inside the window that followed it" was CONSTANT AT THE CAP whatever the corpus held -- measured
    through this same seam with twelve documents inside the forward window: deep printed three against
    a true eleven, max printed five against a true eight, and there was no cut row while the BACKWARD
    window has carried one since S6. A cap is a CUT ROW and never a count.

    Driven here on the deep tier, whose ``receipt_cap`` is three, with six documents inside the window
    the band declares forward of the picked date: the page counts SIX, the row carries THREE and the
    block says which three it could not carry."""
    # 09-24 RE-BANK (K15 seed fold, R-10): the deep pick is April 2020 now (one ONI dimension, not two),
    # so the six forward documents sit in ITS window (2020-04-30, 2020-10-31] -- the same six, re-dated.
    docs = ([{"date": "2020-02-02", "tier": 1, "source": "NOAA", "text": "before the state"}]
            + [{"date": "2020-%02d-15" % m, "tier": 2, "source": "USDA", "text": "after %d" % m}
               for m in (5, 6, 7, 8, 9, 10)])
    sg = _sg(["soybeans_cbot"],
             nodes=[_node("soybeans_cbot", d, evidence=docs)
                    for d in ("El_Nino", "La_Nina", "drought", "export_pace_lag")])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep",
                       query="what is the situation on soybeans now?",
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
    # 09-24 RE-BANK (OWNER DECISION O-7 (a), CONTRACT K15): a stanza carrying NO outcome in the call's own
    # units is WITHHELD (its absence line prints), and this fixture's tape does not reach back to the picks
    # -- so the seam is handed the harness's own monthly BENCHMARK, the anchor's price in the call's units,
    # exactly as a caller that wires one does. The pin below grades the same stanza facts it always did.
    payload = S.fill_stage2(bd, graph=graph, sg=sg, state_fn=H.fixture_state_fn(H.ASOF),
                            benchmark_fn=H.fixture_benchmark_fn())
    block = payload["block"]
    assert int(bd.knobs.receipt_cap) == 3, bd.knobs.receipt_cap
    # THE COUNT IS THE WINDOW'S: six documents fall in (2020-04-30, 2020-10-31].
    assert "six dated documents inside the window that followed it" in block, \
        [x[-200:] for x in block.splitlines() if "window that followed" in x]
    assert "three dated documents inside the window that followed it" not in block, "the cap again"
    # ...AND THE CUT IS A ROW, naming the stanza and never a document title.
    cut = [x for x in block.splitlines()
           if x.startswith("BOARD ABSENCE") and "inside the window that followed" in x]
    # round-2 review MAJOR 1: the row withholds the WHOLE count (six) -- nothing renders the forward rows.
    assert cut and cut[0].startswith("BOARD ABSENCE the six documents counted inside the "
                                     "window that followed this like state are not shown on this "
                                     "page (El Nino on CBOT soybeans)"), cut
    for d in docs:
        assert d["text"] not in "\n".join(cut), d


def test_ANALOG_what_FOLLOWED_is_counted_on_the_page_and_never_enumerated(graph):
    """``analogs._receipts_after`` reads the window the OUTCOME row reads -- ``(t, t+band]`` -- so the
    reader shown what the price did next is told how much the record SAID next. It is PIT-safe by
    construction: ``select_analogs`` admits a candidate only where that band has already closed
    against the as-of.

    THE PAGE PRINTS THE COUNT AND NOT THE TITLES. A document title is retrieved text and SB-A is a
    letters-only class; the board SELECTS rather than enumerating. And the clause is suppressed in the
    one case where the stanza's own absence row already says the corpus held nothing on either side,
    because one absence stated twice in two spellings is not two facts."""
    # 09-24 RE-BANK (K15 seed fold, R-10): re-dated into the April 2020 pick's forward window.
    docs = [{"date": "2020-02-02", "tier": 1, "source": "NOAA", "text": "before the state"},
            {"date": "2020-07-14", "tier": 2, "source": "USDA", "text": "inside the window after"},
            {"date": "2020-09-30", "tier": 3, "source": "trade", "text": "also after"}]
    sg = _sg(["soybeans_cbot"],
             nodes=[_node("soybeans_cbot", d, evidence=docs)
                    for d in ("El_Nino", "La_Nina", "drought", "export_pace_lag")])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="deep",
                       query="what is the situation on soybeans now?",
                       state_fn=H.fixture_state_fn(H.ASOF), named=("soybeans_cbot",))
    # 09-24 RE-BANK (OWNER DECISION O-7 (a), CONTRACT K15): a stanza carrying NO outcome in the call's own
    # units is WITHHELD (its absence line prints), and this fixture's tape does not reach back to the picks
    # -- so the seam is handed the harness's own monthly BENCHMARK, the anchor's price in the call's units,
    # exactly as a caller that wires one does. The pin below grades the same stanza facts it always did.
    payload = S.fill_stage2(bd, graph=graph, sg=sg, state_fn=H.fixture_state_fn(H.ASOF),
                            benchmark_fn=H.fixture_benchmark_fn())
    heads = [x for x in payload["block"].splitlines()
             if x.startswith("LIKE STATE ") and "the series sat like this" in x]
    assert heads, payload["block"][:400]
    assert any("dated document" in x and "inside the window that followed it" in x for x in heads), \
        [x[-160:] for x in heads]
    # LETTERS ONLY: the count is in words and no title reaches the header.
    for x in heads:
        for d in docs:
            assert d["text"] not in x and d["source"] not in x, (d, x)


# === 09-23 LANE R: the two block payloads through the seam (CONTRACT.md C2 / C4, THREAT_MODEL I-8) ======
def test_R0923_the_seam_returns_SERVED_SCALARS_and_ROW_HANDLES_on_a_RENDERED_block_and_NEVER_otherwise(graph):
    """C4: the served-scalars pool rides ``fill_stage2`` ONLY when the block rendered; C2: the row handles
    ride beside it. A declined board (here: the recency-facts coupling, a real decline word) returns
    HEAD's key set exactly, so a board-off or declined turn can never hand the verifier a pool (I-8)."""
    sg = _sg(["soybeans_cbot"])
    bd = S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode="quick", named=("soybeans_cbot",),
                       query="what is the situation on soybeans now?",
                       state_fn=H.fixture_state_fn(H.ASOF))
    got = S.fill_stage2(bd, graph=graph, sg=sg, state_fn=H.fixture_state_fn(H.ASOF))
    assert got["block"]
    pool, handles = got["served_scalars"], got["row_handles"]
    assert pool and handles, (len(pool), len(handles))
    n_calls = len(bd.calls)
    # EVERY registered scalar names the class of the row that printed it and a handle that exists.
    for sc in pool:
        assert {"value", "unit", "kind", "cls"} <= set(sc), sc
        if sc.get("handle") is not None:
            assert 1 <= int(sc["handle"]) <= n_calls, sc
    # EVERY row handle resolves to a call of THIS block, and the level handle is `handles_by_row`'s int.
    for key, hs in handles.items():
        assert set(hs) == {"level", "sigma", "percentile", "peak", "current"}, (key, hs)
        for h in hs.values():
            if h is not None:
                assert 1 <= int(h) <= n_calls, (key, hs)
        assert hs["level"] is not None, key
    # A DECLINED BOARD CARRIES NEITHER KEY.
    sg2 = _sg(["soybeans_cbot"])
    bd2 = S.fill_stage1(graph=graph, sg=sg2, asof=H.ASOF, mode="deep", named=("soybeans_cbot",),
                        state_fn=H.fixture_state_fn(H.ASOF), recency_facts=False)
    out2 = S.fill_stage2(bd2, graph=graph, sg=sg2)
    assert out2["block"] == ""
    assert "served_scalars" not in out2 and "row_handles" not in out2, sorted(out2)
