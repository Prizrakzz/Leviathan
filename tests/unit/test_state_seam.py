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
    `BoardKnobs`. NOTHING IS TIGHTENED HERE: a cap change is a prompt-content change and arm A must
    measure ONE instrument, so the knob exists and S7 sets it."""
    from leviathan.graphrag.state import watch as WA
    for mode in ("quick", "deep", "max"):
        kn = B.board_knobs_of(mode)
        assert R.render_caps(mode, kn) == dict(R.RENDER_CAPS[mode], absence=0,
                                               absence_names=kn.render_absence_names)
        assert R.render_caps(mode) == R.RENDER_CAPS[mode]        # no knobs -> the shipped table
        assert WA.render_k(mode, kn) == WA.WATCH_RENDER_K[mode]
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
    assert cut.startswith(", ".join(long[:5])) and "further rows this line does not name" in cut
    assert not any(ch.isdigit() for ch in cut[len(", ".join(long[:5])):])
    # ...and a nine-field tuple (the S2 fixtures, the census) still reads the shipped table
    nine = B.BoardKnobs(*tuple(B.board_knobs_of("deep"))[:9])
    assert R.render_caps("deep", nine) == dict(R.RENDER_CAPS["deep"], absence=0,
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
    the "a real spend read as zero" failure S5 had to repair for the composer sub-legs."""
    bd, out = fired
    assert out["counters"]["BoardEvidenceBorrows"] == 0
    assert bd.ledger.evidence_borrows == 0 and bd.ledger.benchmark_reads == 0
    # THE UNWIRED COLUMNS ARE NOT RESERVED EITHER, so the walk's ceiling gains no read that nothing
    # can pay: the seam wires neither producer, so both columns are zero on the served shape.
    assert bd.ledger.evidence_cap == 0 and bd.ledger.benchmark_cap == 0
    assert bd.net_reads() <= bd.declared_cap()
    # ...and `reads_used` counts a benchmark read, so a future wiring is visible to the enumeration.
    bd.ledger.benchmark_reads += 3
    assert bd.net_reads() == out["trace"]["net_reads"] + 3


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
                assert "all sit among this board's loudest rows" in l, (shape, mode, l)
                assert "the graph records the effect as " in l, (shape, mode, l)
                assert R.classify(l) == ("SB-M",), (shape, mode, R.classify(l), l)
                # THE READ SPLIT, wherever the walk produced one: the clause is whole, never a
                # truncated "carries no series" with the object of the sentence fenced away.
                if "no series" in l:
                    assert "no series this board could read" in l, (shape, mode, l)
            # (4) ...and no row on the board is the whole-row correction of one
            for l in blk.splitlines():
                assert "BOARD ABSENCE" not in l or "did not pass its own register check" not in l, l
    assert seen_amps >= 15, seen_amps
