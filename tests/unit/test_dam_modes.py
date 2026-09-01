"""D-AM-9..12 (AGENTIC_MODES_WAVE_PLAN, PHASE 2): the reasoning_modes leaf, the `mode` request
field, the knob threading, and the observability that ships in the same change.

THE ACCEPTANCE BAR, pinned first and hardest: `standard` and every DARK turn (a mode requested but
not in the GRAPHRAG_MODES allowlist) must produce BYTE-IDENTICAL calls at every threaded seam --
the walk, the ground, the retrieval partial, the silver factory, the scaffold, the persona and the
reroute gate. Each of those is asserted by CAPTURING the kwargs an engine actually received, not by
reading the source, so a future refactor that starts passing `mode_knobs={}` reds here.

Also pinned: fail-open (unknown/absent mode -> standard + a mode_invalid stamp, never a 4xx), the
flag value grammar, the honored knob values, the budget-scaling arithmetic, the EMF `mode`
dimension, and the tracekeys registration (which IS the eval registration since D-AM-3).

All offline: no pg, no S3, no LLM, no AWS. ASCII-only output (the Windows console is cp1252)."""
from __future__ import annotations

import inspect
import pathlib
import types

import pytest

from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import emf as emfmod
from leviathan.graphrag import eval as evl
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import planner as pl
from leviathan.graphrag import rankers as _rk
from leviathan.graphrag import reasoning_modes as rm
from leviathan.graphrag import response_contracts as rc
from leviathan.graphrag import silverleg as slv
from leviathan.graphrag import timeline as tl
from leviathan.graphrag import tracekeys as tk


# ══ fixtures ═════════════════════════════════════════════════════════════════════════════════════════
def _graph() -> g.CausalGraph:
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                mechanism="dryness cuts yield")])
    return g.CausalGraph({"corn": corn}, silver=set())


def _force(kind):
    return lambda q, call=None: {"intent": kind, "needs_numbers": kind in ("numbers_only", "hybrid"),
                                 "needs_reasoning": kind in ("reasoning", "hybrid")}


def _reason_call(system, user, *, model, tool, **kw):
    return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}", "text": "note"}]


class _Stop(Exception):
    """Sentinel: the seam under test has been reached and its kwargs captured; stop the turn."""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every mode test states its own flag state -- an inherited GRAPHRAG_MODES would make the
    dark-passthrough pins vacuously green."""
    monkeypatch.delenv("GRAPHRAG_MODES", raising=False)
    monkeypatch.delenv("GRAPHRAG_RESPONSE_CONTRACT", raising=False)
    monkeypatch.delenv("GRAPHRAG_REROUTE_V2", raising=False)


# ══ A -- the leaf module ═════════════════════════════════════════════════════════════════════════════
def test_reasoning_modes_is_a_leaf_module():
    """The response_contracts.py discipline: a pure-data table importable from orchestrator, answer,
    server and eval alike. One leviathan import here re-creates the cycle the leaf exists to avoid."""
    import ast
    tree = ast.parse(pathlib.Path(rm.__file__).read_text(encoding="utf-8"))
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
    assert [m for m in mods if m.split(".")[0] == "leviathan"] == [], mods
    assert set(mods) <= {"__future__", "dataclasses"}, mods


def test_the_preset_table_and_nothing_else():
    # D-MW-30: the escalated bundle appends esc / esc_r. valid_names() widens (they are RESOLVABLE by
    # name, which is how the eval arms reach them); serving_names() does NOT -- see the pin below.
    # D-MW-28 (P6): max_cc1 appends the same way -- resolvable BY NAME (the gate's ON arm), dark to the
    # wildcard. Fourth application of the same law, and the serving_names() pin below is still untouched.
    # D-HP-8 (R9): the four `_hp` twins append the same way -- resolvable BY NAME (the gate arms request
    # `--mode deep_hp`), dark to the wildcard. FIFTH application, and the serving_names() pin below is
    # STILL untouched: thirteen presets, three servable.
    # T2-2 (CASCADE_HOME plan): `deep_cc1` appends the same way -- the T2-3 gate's ON arm, resolvable BY
    # NAME, dark to the wildcard. SIXTH application: fourteen presets, three servable.
    # Q-0a (2026-08-28): `max_cc2` appends the same way -- the slot-WIDTH arm, resolvable BY NAME,
    # dark to the wildcard. SEVENTH application: fifteen presets, three servable.
    assert rm.valid_names() == frozenset({"quick", "standard", "deep", "deep_v2", "max", "max_c0",
                                          "esc", "esc_r", "max_cc1", "max_cc2", "deep_cc1",
                                          "quick_hp", "deep_hp", "esc_hp", "esc_r_hp"})
    assert set(rm.MODES) == {rm.QUICK, rm.STANDARD, rm.DEEP, rm.DEEP_V2, rm.MAX, rm.MAX_C0,
                             rm.ESC, rm.ESC_R, rm.MAX_CC1, rm.MAX_CC2, rm.DEEP_CC1,
                             rm.QUICK_HP, rm.DEEP_HP, rm.ESC_HP, rm.ESC_R_HP}
    # Every preset's `name` field agrees with its table key -- the `replace(...)`-constructed twins would
    # otherwise be able to carry their BASE's name and stamp the wrong arm on every artifact.
    assert all(m.name == k for k, m in rm.MODES.items())


def test_deep_v2_is_dark_and_the_wildcard_can_never_sweep_it_in(monkeypatch):
    """D-DV-2 ships the arm's preset in the SAME image as the D-DV-1 fixes, so the eval can run it --
    but an un-adjudicated arm must never become honorable by turning modes on estate-wide. The dark
    set is named in the leaf (one producer), and the wildcard branch reads serving_names()."""
    # D-MW-13: the max bundle joins the dark set at birth. serving_names() is UNCHANGED by that -- the
    # pin below is the proof that two new presets widened valid_names() without widening what
    # GRAPHRAG_MODES=on may sweep in.
    # D-MW-30 (F8): esc / esc_r join the dark set in the SAME commit that mints them. A forgotten entry
    # here would make an UNMETERED max-width + opus turn wildcard-honorable -- the escalated bundle is
    # reachable in serving ONLY through the escalation seam, which stamps honored=deep and prices deep.
    # D-MW-28 (P6): max_cc1 joins DARK_NAMES in the SAME commit that mints it. It carries a PAID slot for
    # a foreign contract block, so a forgotten entry would spend it on every wildcard turn.
    # D-HP-8 (R9): all four `_hp` twins join DARK_NAMES in the SAME commit that mints them, and here the
    # dark set IS the whole control surface -- `quick_hp`/`deep_hp` are the flip ladder's own rungs, so a
    # forgotten entry serves UNGATED handle-only prose (number-free sentences, figures unspliced) to anyone
    # who types the name, before G1 has run a single row.
    # T2-2: `deep_cc1` joins DARK_NAMES in the SAME edit that mints it, and it is the sharpest case of the
    # fence yet -- every earlier dark preset was built on a dark base or an unflipped treatment, while this
    # one is the SHIPPED serving tier plus a paid foreign-contract slot the T2-3 gate has not adjudicated.
    assert rm.DARK_NAMES == frozenset({rm.DEEP_V2, rm.MAX, rm.MAX_C0, rm.ESC, rm.ESC_R, rm.MAX_CC1,
                                       rm.MAX_CC2, rm.DEEP_CC1,
                                       rm.QUICK_HP, rm.DEEP_HP, rm.ESC_HP, rm.ESC_R_HP})
    assert rm.serving_names() == frozenset({"quick", "standard", "deep"})
    assert rm.DEEP_V2 in rm.valid_names()                              # still RESOLVABLE (stamped)
    for on in ("on", "1", "true"):
        monkeypatch.setenv("GRAPHRAG_MODES", on)
        assert rm.DEEP_V2 not in orch._modes_enabled()
        assert rm.MAX not in orch._modes_enabled() and rm.MAX_C0 not in orch._modes_enabled()
        assert rm.ESC not in orch._modes_enabled() and rm.ESC_R not in orch._modes_enabled()
        assert rm.MAX_CC1 not in orch._modes_enabled()
        assert rm.DEEP_CC1 not in orch._modes_enabled()
        assert not (set(rm.HANDLE_PROSE_PRESETS.values()) & orch._modes_enabled())
    assert rm.resolve("deep_v2", orch._modes_enabled())["honored"] == "standard"
    monkeypatch.setenv("GRAPHRAG_MODES", "deep_v2")                    # named EXPLICITLY -> honored
    assert orch._modes_enabled() == frozenset({"deep_v2"})
    assert rm.resolve("deep_v2", orch._modes_enabled())["honored"] == "deep_v2"


def test_standard_is_the_all_none_passthrough_pin():
    """LOAD-BEARING: standard carries no knob at all, so `knobs` is empty, every kwarg builder is
    empty and every call site is byte-identical WITHOUT anyone promising to keep it that way."""
    std = rm.MODES[rm.STANDARD]
    assert all(getattr(std, f) is None for f in rm.KNOB_FIELDS)
    assert rm.knobs(rm.STANDARD) == {}
    assert rm.walk_kwargs(rm.knobs(rm.STANDARD)) == {}
    assert rm.ground_kwargs(rm.knobs(rm.STANDARD)) == {}


def test_the_two_new_policy_fields_default_to_none_on_every_pre_ddv_preset():
    """THE BYTE-IDENTITY LAW for D-DV's two new Mode fields: they exist on every preset and are None
    on all of them except deep_v2, so `knobs()` cannot mint them, `ground_kwargs()` cannot pass
    cap_policy, and answer._render_order returns the walk order unchanged. Nothing to promise by hand
    -- the None default IS the guarantee, exactly as `standard` is for the whole table."""
    # D-MW-13 re-pin: the per-seed quartet appends AFTER order_policy, per_seed_reserve LAST (the
    # appended-last law -- D-MW-28's cascade_contract_slots moves this tail a second time in P6).
    # D-MW-30 re-pin (F7): synth_model then provenance_prompt append AFTER per_seed_reserve, so the
    # quartet's own slice moves left by two. Same law, third application: append, never insert -- the
    # KNOB_FIELDS order IS the trace-stamp column order, and 12f is the record of what a shift costs.
    # D-MW-28 re-pin (P6): `cascade_contract_slots` appends AFTER provenance_prompt, so the tail moves a
    # FOURTH time and every slice below shifts left by one. Same law, same reason: KNOB_FIELDS order IS
    # the trace-stamp column order -- append, never insert.
    # D-HP-8 re-pin (H1): `handle_prose` appends AFTER cascade_contract_slots -- the tail moves a FIFTH
    # time and every slice below shifts left by one. Same law, same reason.
    # Q-0 re-pin (2026-08-29): `synth_effort` appends AFTER handle_prose -- the tail moves a SIXTH
    # time and every slice below shifts left by one. Same law, same reason.
    assert rm.KNOB_FIELDS[-1] == "synth_effort"
    assert rm.KNOB_FIELDS[-2] == "handle_prose"
    assert ("provenance_prompt", "cascade_contract_slots") == rm.KNOB_FIELDS[-4:-2]
    assert rm.KNOB_FIELDS[-5] == "synth_model"
    assert rm.KNOB_FIELDS[-9:-5] == ("per_seed_budget", "per_seed_evidence_cap",
                                     "per_seed_probe_cap", "per_seed_reserve")
    assert rm.KNOB_FIELDS[-11:-9] == ("cap_policy", "order_policy")     # appended, never sorted in
    for name in (rm.QUICK, rm.STANDARD, rm.DEEP):
        m = rm.MODES[name]
        assert m.cap_policy is None and m.order_policy is None, name
        assert "cap_policy" not in rm.knobs(name) and "order_policy" not in rm.knobs(name), name
        assert "cap_policy" not in rm.ground_kwargs(rm.knobs(name)), name
    assert pl._dedup_and_cap.__defaults__ is None                      # both are KEYWORD-only, defaulting
    sig = inspect.signature(pl._dedup_and_cap).parameters              # to the pre-wave behavior
    assert sig["cap_policy"].default is None and sig["k_by_depth"].default is None
    assert inspect.signature(pl.ground).parameters["cap_policy"].default is None


def test_mode_is_frozen():
    with pytest.raises(Exception):
        rm.MODES[rm.QUICK].node_budget = 99          # frozen dataclass: the table cannot be mutated


def test_v1_knob_table_matches_the_ratified_values():
    """D-AM-10's table, transcribed. If the eval retunes a number this test is the one place to
    change it -- and the change is then visible in review, which is the whole point."""
    # P4-ARM COMMIT (2026-08-12, plan 12c): quick/deep converted to the ratified per-seed budgets
    # (Scan 12 / Analysis 32); the flat node_budget is gone -- the walk derives budget x realized seeds.
    assert rm.knobs(rm.QUICK) == {
        "depth": 1, "max_seeds": 2,                            # D-MW-13 (R7): a CEILING, ratified 08-11
        "k_by_depth": (4, 2), "evidence_cap": 12, "probe_cap": 12,
        "fetch_k": 40, "silver_cap": 4,
        "scaffold_max_bullets": 6, "scaffold_max_absence": 3,
        "budget_scale": 0.7, "xc_force": False,
        "per_seed_budget": 12}
    # D-DV-1: deep amended on the forensics. fetch_k 120->60 (>60 deletes the lexical leg outright:
    # RERANK_POOL is 60 and the cut runs after fusion), depth 3->1 + k_by_depth (7,5,3)->(7,5) (DEAD:
    # node_budget saturated 36/36 inside wave 1, wave 2 never ran), xc_force True->None (forced
    # reroute-v2 = number_mismatch dose-response 2/2/11), budget_scale 1.5->None (H-verbosity killed).
    # D-MW-13 (R7): deep's max_seeds 3 -> 4 is its tier CEILING.
    assert rm.knobs(rm.DEEP) == {
        "depth": 1, "max_seeds": 4,
        "k_by_depth": (7, 5), "evidence_cap": 48, "probe_cap": 36,
        "fetch_k": 60, "silver_cap": 12,
        "scaffold_max_bullets": 12, "scaffold_max_absence": 6,
        "per_seed_budget": 32}


def test_deep_v2_preset_matches_the_ratified_values():
    """D-DV-2's arm, transcribed. Same walk as deep (16 nodes, 3 seeds) -- the variables under test are
    the cap SIZE (48->24), the cap POLICY (FIFO->score) and the render ORDER. scaffold caps are absent
    on purpose: deep_v2 inherits the params default rather than pinning deep's."""
    assert rm.knobs(rm.DEEP_V2) == {
        "node_budget": 16, "depth": 1, "max_seeds": 3,
        "k_by_depth": (7, 5), "evidence_cap": 24, "probe_cap": 36,
        "fetch_k": 60, "silver_cap": 8,
        "cap_policy": "score", "order_policy": "relevance"}
    assert an._scaffold_cap_kwargs(rm.knobs(rm.DEEP_V2)) == {}          # inherit, not pin
    assert an._mode_budget("ranking", rm.knobs(rm.DEEP_V2)) is None     # no budget_scale -> untouched


# ══ A2 -- D-MW-13: the max bundle (seed CEILINGS + PER-SEED allocations) ═════════════════════════════
def test_max_preset_matches_the_step0_calibrated_values():
    """D-MW-13, STEP-0-CALIBRATED + RATIFIED 2026-08-11 (census 288 routed walks: per-seed cosine demand
    p75 = 63, eligible-ancestor demand p75 = 4). node_budget / evidence_cap / probe_cap are ABSENT on
    purpose -- they are DERIVED from the REALIZED seed count at walk/ground time, and a flat number
    pinned here would silently beat the per-seed arithmetic."""
    assert rm.knobs(rm.MAX) == {
        "depth": 2, "max_seeds": 6,
        "k_by_depth": (7, 5, 3),
        "fetch_k": 60, "silver_cap": 12,
        "scaffold_max_bullets": 12, "scaffold_max_absence": 6,
        "cap_policy": "score", "order_policy": "relevance",
        # reserve 4 -> 0: the P3 gate termination (plan 12c) -- 0/8 upstream cited both runs +
        # strip 1.17x/1.31x at identical width. Reservation OFF, no fix cycle.
        "per_seed_budget": 63, "per_seed_evidence_cap": 24, "per_seed_probe_cap": 24,
        "per_seed_reserve": 0,
        # Q-0 (2026-08-29): the T-pair verdict's winner rides the tier that measured it -- writer
        # effort=max, the whole max family, mode > env at the synthesis seam. Deep stays UNSET
        # (its transfer FAILED non-inferiority; the frozen rule blocked the process-wide flip).
        "synth_effort": "max"}
    for absent in ("node_budget", "evidence_cap", "probe_cap"):
        assert absent not in rm.knobs(rm.MAX), absent
        assert getattr(rm.MODES[rm.MAX], absent) is None, absent


# ══ Q-0 -- the effort knob (T-pair verdict, 2026-08-29) ══════════════════════════════════════════════
def test_synth_effort_rides_the_whole_max_family_and_no_other_preset():
    """One-variable arm pairs survive: max/max_c0 differ [], max/max_cc1 differ [slots], max_cc1/max_cc2
    differ [slots]. Every NON-max preset must not so much as MINT the key (the byte-identity law), and
    DEEP in particular stays unset -- its tier MEASURED AGAINST the flip (non-inferiority failed).
    Review F5/F6 amendments: the negative set is DERIVED (a preset minted tomorrow cannot escape it),
    and the grammar pin binds THE TABLE to providers._EFFORT_WORDS -- an invalid tier on any preset
    would fail OPEN at the seam (no output_config, env nullified: the silent-null-arm class), so it
    must never survive the suite."""
    from leviathan.graphrag import providers as pv
    family = {rm.MAX, rm.MAX_C0, rm.MAX_CC1, rm.MAX_CC2}
    for name in family:
        assert rm.knobs(name).get("synth_effort") == "max", name
    for name in set(rm.MODES) - family:                             # DERIVED, never enumerated (F6)
        assert "synth_effort" not in rm.knobs(name), name
        assert rm.MODES[name].synth_effort is None, name
    for m in rm.MODES.values():                                     # the TABLE-to-grammar bind (F5)
        assert m.synth_effort is None or m.synth_effort in pv._EFFORT_WORDS, m.name


def test_call_opus_effort_mode_beats_env(monkeypatch):
    """The F5 precedence, one rung lower: the threaded kwarg wins over GRAPHRAG_SYNTH_EFFORT; absent,
    the env seam decides exactly as before; an invalid word resolves to NO output_config (fail-open),
    never a 400 at the API."""
    from leviathan.graphrag import answer as an2
    from leviathan.graphrag import providers as pv
    seen: dict = {}

    def fake_call(client, sys_blocks, user, **kw):
        seen.update(kw)
        return {}, None

    monkeypatch.setattr(pv, "make_client", lambda: None)
    monkeypatch.setattr(pv, "serving_call", fake_call)
    monkeypatch.setattr(pv, "provider", lambda: "anthropic")
    monkeypatch.setenv("GRAPHRAG_SYNTH_EFFORT", "low")
    an2._call_opus("s", "u", model="claude-opus-5", tool={}, effort="max")
    assert seen.get("output_config") == {"effort": "max"}           # mode wins
    seen.clear()
    an2._call_opus("s", "u", model="claude-opus-5", tool={})
    assert seen.get("output_config") == {"effort": "low"}           # absent -> env, unchanged
    seen.clear()
    monkeypatch.delenv("GRAPHRAG_SYNTH_EFFORT")
    an2._call_opus("s", "u", model="claude-opus-5", tool={}, effort="turbo")
    assert "output_config" not in seen                              # invalid word -> fail-open, no 400


def test_max_and_max_c0_are_now_byte_identical_twins():
    """P3 ran with the one-variable pair (reserve 4 vs 0). THE 12c TERMINATION zeroed max's own
    reserve, so the twins are now BYTE-IDENTICAL except name: max_c0 is retained as the historical
    P3 arm identity (stored artifacts stamp honored=max_c0), permanently dark, never the shipped
    tier. A reserve re-raise on max would re-open the one-variable pair -- this pin makes that a
    visible decision, not a drift."""
    hot, off = rm.MODES[rm.MAX], rm.MODES[rm.MAX_C0]
    differ = [f for f in rm.KNOB_FIELDS if getattr(hot, f) != getattr(off, f)]
    assert differ == [], differ
    assert hot.per_seed_reserve == 0 and off.per_seed_reserve == 0
    assert off.name == "max_c0" and hot.name == "max"


def test_zero_is_a_value_not_a_default_on_max_c0():
    """0 must SURVIVE the None-filters end to end: `knobs()` drops None, so a per_seed_reserve that
    fell through as None would leave GRAPHRAG_CLOSURE_RESERVE deciding the OFF arm -- the arm would
    silently run the ON mechanism. The kwarg-beats-env precedence is a shipped pin; this is what
    hands the walk a 0 to enforce it with."""
    kn = rm.knobs(rm.MAX_C0)
    assert kn["per_seed_reserve"] == 0 and "per_seed_reserve" in kn
    assert rm.walk_kwargs(kn)["per_seed_reserve"] == 0
    assert rm.walk_kwargs(rm.knobs(rm.MAX))["per_seed_reserve"] == 0   # 12c: max's reserve is OFF too


# ══ D-HP-8 -- THE HANDLE-PROSE CONTROL SURFACE (R9 ratified) ═════════════════════════════════════════
_HP_PAIRS = (("quick", "quick_hp"), ("deep", "deep_hp"), ("esc", "esc_hp"), ("esc_r", "esc_r_hp"))


def test_the_hp_twins_are_their_base_plus_exactly_one_field():
    """THE ARM IS ONE VARIABLE OR IT MEASURES TWO. `deep` vs `deep_hp` is the reference gate arm, so a
    twin that drifted from its base by any other field would make every G1/G2 verdict unattributable.
    The twins are CONSTRUCTED with `dataclasses.replace`, not hand-copied, so the property holds the day
    someone amends a base preset -- which is the copy-and-drift class (COMPAT-9) this module exists to
    kill. The source pin below is what keeps a future editor from re-typing the table."""
    assert dict(_HP_PAIRS) == rm.HANDLE_PROSE_PRESETS
    for base, hp in _HP_PAIRS:
        differ = [f for f in rm.KNOB_FIELDS if getattr(rm.MODES[base], f) != getattr(rm.MODES[hp], f)]
        assert differ == ["handle_prose"], (base, hp, differ)
        assert rm.knobs(hp) == rm.knobs(base) | {"handle_prose": True}, hp
        # THE BYTE-IDENTITY LAW on the base: `knobs()` filters `is not None`, so the control arm must not
        # so much as MINT the key. A literal False on a base preset would move its trace stamp.
        assert "handle_prose" not in rm.knobs(base), base
        assert rm.MODES[base].handle_prose is None and rm.MODES[hp].handle_prose is True
    src = inspect.getsource(rm)
    assert "replace(MODES[base], name=hp, handle_prose=True)" in src   # constructed, never hand-copied


def test_standard_and_max_are_not_in_the_ladder_and_cannot_be():
    """`standard`'s EMPTY knob dict IS the fail-open guarantee (the module's own opening claim), and
    `test_standard_is_the_all_none_passthrough_pin` reds the moment a field lands on it. The max family
    is out of the ladder for a different reason -- it is not a served tier at all. Neither gets a twin.

    T2-2: `deep_cc1` joins the excluded list. It IS deep-shaped, but it is an EVAL ARM, not a tier -- the
    ladder pairs a served tier with its handle-prose twin, and a cascade arm with an `_hp` twin would be a
    two-variable preset nobody ratified."""
    for excluded in (rm.STANDARD, rm.MAX, rm.MAX_C0, rm.MAX_CC1, rm.DEEP_CC1, rm.DEEP_V2):
        assert rm.handle_prose_variant(excluded) is None, excluded
    assert rm.knobs(rm.STANDARD) == {}                                 # the passthrough pin, untouched
    assert rm.MODES[rm.STANDARD].handle_prose is None


def test_the_matched_set_is_what_survives_an_escalation():
    """THE DECISIVE R9 REASON, expressed as a property. orchestrator.py:2138-2139 swaps the knob dict
    WHOLE ("never a merge"), so a `deep_hp` turn that escalated into `esc` would be handed a dict with NO
    `handle_prose` -- the PROMPT contract, the renderer and the digit-lint all revert mid-turn, silently
    gutting D-HP-23 rung 2 and D-HP-25 (two of the four judged gates). The leaf therefore owns the
    base<->twin join, and every seam that must follow a turn across it reads THIS table."""
    assert rm.handle_prose_on(rm.knobs(rm.ESC)) is False               # the control target strips it
    assert rm.handle_prose_on(rm.knobs(rm.handle_prose_variant(rm.ESC))) is True
    assert rm.handle_prose_variant(rm.DEEP) == rm.DEEP_HP and rm.handle_prose_variant(rm.ESC_R) == rm.ESC_R_HP
    # The inverse join. Its three consumers are named in `base_mode`'s docstring and each is a live defect
    # if it retypes the name instead: the escalation gate's tier test (`honored != DEEP` suppresses every
    # deep_hp turn with reason `tier`), the composition-census mandate set, and the credit price.
    for base, hp in _HP_PAIRS:
        assert rm.base_mode(hp) == base
    for unchanged in (rm.QUICK, rm.DEEP, rm.STANDARD, rm.MAX, "no_such_mode", ""):
        assert rm.base_mode(unchanged) == unchanged
    assert rm.base_mode(None) == ""                                    # fail-open, never raises


def test_the_kill_switch_is_one_way_at_the_leaf(monkeypatch):
    """`GRAPHRAG_HANDLE_PROSE` can force the treatment OFF from any preset and can NEVER turn it on.
    The leaf reads no environment (its own law), so the VALUE is threaded in -- one producer for the eval
    arm stamp and the serving seam alike, which is what stops an artifact from disagreeing with its turn."""
    on_kn, off_kn = rm.knobs(rm.DEEP_HP), rm.knobs(rm.DEEP)
    for kill in ("off", "0", "false", "kill", "OFF", " off "):
        assert rm.handle_prose_on(on_kn, kill) is False, kill
        assert rm.handle_prose_arm(on_kn, kill) == "off", kill
    for noise in ("on", "1", "true", "deep_hp", "yes", "", None):
        assert rm.handle_prose_on(on_kn, noise) is True, noise         # the preset decides, not the env
        assert rm.handle_prose_on(off_kn, noise) is False, noise       # ...and the env cannot enable
        assert rm.handle_prose_arm(off_kn, noise) is None, noise
    assert rm.handle_prose_on(None) is False and rm.handle_prose_arm(None) is None
    # "reads no environment" is not a promise here: `test_reasoning_modes_is_a_leaf_module` pins the
    # module's imports to {__future__, dataclasses}, so an `os.environ` read is unbuildable.
    monkeypatch.setenv("GRAPHRAG_HANDLE_PROSE", "off")
    assert rm.handle_prose_on(on_kn) is True                           # ...the ambient env is INVISIBLE


def test_the_kill_switch_spelling_is_the_same_set_at_every_seam():
    """THE SEAMS MUST NOT DISAGREE ABOUT WHETHER A RUN WAS KILLED. Three places resolve the one-way kill
    today -- the leaf (`HANDLE_PROSE_KILL_VALUES`, the producer), `answer._handle_prose_on` (the BEHAVIOUR)
    and `eval._handle_prose_arm` (the ARM STAMP, which now delegates to the leaf). A spelling accepted by
    one and not another would let an artifact record `off` on a turn that ran the treatment, or the reverse
    -- and that column is the join key D-HP-19's bridge run rides.

    RECORDED HANDOFF (not fixable from this cluster's files): `answer._HANDLE_PROSE_KILL` is a SECOND copy
    of this tuple. It agrees today and this pin keeps it agreeing, but the durable fix is one line in
    answer.py -- `_handle_prose_on` calling `rm.handle_prose_on(mode_knobs, os.environ.get(
    "GRAPHRAG_HANDLE_PROSE"))` (answer.py already imports the leaf as `_rm`)."""
    assert rm.HANDLE_PROSE_KILL_VALUES == frozenset({"off", "0", "false", "kill"})
    assert set(getattr(an, "_HANDLE_PROSE_KILL")) == set(rm.HANDLE_PROSE_KILL_VALUES)
    # and there is NO "on" spelling anywhere, by design: the presets are the only way in.
    assert not (rm.HANDLE_PROSE_KILL_VALUES & {"on", "1", "true", "yes"})


def test_walk_kwargs_carry_the_per_seed_walk_knobs():
    """per_seed_budget / per_seed_reserve are WALK knobs (grounded_subgraph keywords); the two ground
    per-seed caps are NOT, and must never leak onto the walk call."""
    for name in (rm.MAX, rm.MAX_C0):
        wk = rm.walk_kwargs(rm.knobs(name))
        assert wk["per_seed_budget"] == 63 and wk["depth"] == 2 and wk["max_seeds"] == 6, name
        assert "node_budget" not in wk, name                             # derived, never flat
        assert "per_seed_evidence_cap" not in wk and "per_seed_probe_cap" not in wk, name
    # THE CROSS-CLUSTER SEAM PIN (D-MW-13 contract item 4): the per-seed walk knobs are Class-1 only
    # once grounded_subgraph accepts them, so this assertion is RED until the planner half of the same
    # commit lands -- deliberately, because a preset that threads a keyword its callee rejects is a
    # TypeError at the first honored turn, not a test-time nicety.
    walk = set(inspect.signature(pl.grounded_subgraph).parameters)
    assert set(rm.walk_kwargs(rm.knobs(rm.MAX))) <= walk
    # P4-ARM COMMIT: quick/deep now carry their ratified per-seed budgets (12/32) but NO reserve
    # (the reservation is a max-family concept and it is OFF everywhere per 12c).
    assert rm.walk_kwargs(rm.knobs(rm.QUICK))["per_seed_budget"] == 12
    assert rm.walk_kwargs(rm.knobs(rm.DEEP))["per_seed_budget"] == 32
    for name in (rm.QUICK, rm.STANDARD, rm.DEEP, rm.DEEP_V2):
        wk = rm.walk_kwargs(rm.knobs(name))
        assert "per_seed_reserve" not in wk, name
    for name in (rm.STANDARD, rm.DEEP_V2):                               # untouched by construction
        wk = rm.walk_kwargs(rm.knobs(name))
        assert "per_seed_budget" not in wk, name


def test_the_tier_seed_ceilings_are_quick_2_deep_4_max_6():
    """R7's one default-product change, ratified 2026-08-11: max_seeds STOPS being a fan-in number and
    becomes the tier CEILING the dispatch planner picks under. A two-market question on the default
    tier is no longer a one-market answer."""
    assert rm.MODES[rm.QUICK].max_seeds == 2
    assert rm.MODES[rm.DEEP].max_seeds == 4
    assert rm.MODES[rm.MAX].max_seeds == rm.MODES[rm.MAX_C0].max_seeds == 6
    assert rm.MODES[rm.STANDARD].max_seeds is None                       # all-None pin, untouched
    # P4-ARM COMMIT LANDED (2026-08-12, plan 12c): the ratified per-seed budgets are live on the
    # tier presets -- Scan 12 / Analysis 32 / Full-cascade 63.
    assert rm.MODES[rm.QUICK].per_seed_budget == 12
    assert rm.MODES[rm.DEEP].per_seed_budget == 32
    assert rm.MODES[rm.MAX].per_seed_budget == 63


@pytest.mark.parametrize("n,evidence,probe", [(1, 24, 24), (3, 72, 72), (6, 144, 96)])
def test_scaled_ground_kwargs_is_the_one_producer_of_the_seed_scaled_caps(n, evidence, probe):
    """D-MW-13: ground caps scale with the REALIZED seed count and clamp at the module totals -- 24/seed
    hits the 144 evidence ceiling exactly at 6 seeds, while the probe total binds earlier (96 at 4).
    The arithmetic lives HERE, once: a call site that multiplied for itself is the drift class."""
    assert (rm.TOTAL_EVIDENCE_CAP, rm.TOTAL_PROBE_CAP) == (144, 96)
    kn = rm.knobs(rm.MAX)
    out = rm.scaled_ground_kwargs(kn, n)
    assert out["evidence_cap"] == evidence and out["probe_cap"] == probe
    assert out["k_by_depth"] == (7, 5, 3) and out["cap_policy"] == "score"
    assert set(out) == {"k_by_depth", "cap_policy", "evidence_cap", "probe_cap"}
    assert rm.scaled_ground_kwargs(rm.knobs(rm.MAX_C0), n) == out        # the reserve is a WALK knob
    assert kn == rm.knobs(rm.MAX)                                        # the knob dict is not mutated
    assert set(out) <= set(inspect.signature(pl.ground).parameters)      # still Class-1 keywords only


def test_scaled_ground_kwargs_is_byte_identical_where_the_per_seed_fields_are_absent():
    """THE BYTE-IDENTITY LAW for the new producer: on every pre-D-MW preset it IS ground_kwargs(), at
    any seed count -- so threading it at the call site cannot move quick/standard/deep/deep_v2."""
    for name in (rm.QUICK, rm.STANDARD, rm.DEEP, rm.DEEP_V2):
        kn = rm.knobs(name)
        for n in (0, 1, 3, 6, 99):
            assert rm.scaled_ground_kwargs(kn, n) == rm.ground_kwargs(kn), (name, n)
    assert rm.scaled_ground_kwargs(None, 3) == {} and rm.scaled_ground_kwargs({}, 3) == {}


def test_scaled_ground_kwargs_never_grounds_a_turn_at_zero():
    """Fail-open, this module's law: a walk reporting 0 seeds falls back to the ONE-seed allocation,
    never to a cap of 0 (which would ground the turn with no evidence at all)."""
    one = rm.scaled_ground_kwargs(rm.knobs(rm.MAX), 1)
    assert rm.scaled_ground_kwargs(rm.knobs(rm.MAX), 0) == one
    assert rm.scaled_ground_kwargs(rm.knobs(rm.MAX), -3) == one


def test_kwarg_builders_name_only_callee_accepted_keywords():
    """v1 threads, it does not redesign: every walk/ground knob must already be a keyword of its
    callee. A knob that is not is a seam change and belongs in a different wave."""
    walk = set(inspect.signature(pl.grounded_subgraph).parameters)
    ground = set(inspect.signature(pl.ground).parameters)
    assert set(rm.walk_kwargs(rm.knobs(rm.DEEP))) <= walk
    assert set(rm.ground_kwargs(rm.knobs(rm.DEEP))) <= ground
    assert "cap" in inspect.signature(slv.make_silver_lookup).parameters
    assert "fetch_k" in inspect.signature(an.ev.retrieve).parameters


def test_pit_safety_and_the_exclusion_list_are_stated_in_the_module():
    """The ratification record lives beside the code, not only in the plan doc: PIT safety is
    STATED (never re-derived at a call site) and every v1 exclusion carries its reason."""
    doc = rm.__doc__ or ""
    assert "PIT SAFETY" in doc and "leakage filter runs BEFORE any width slicing" in doc.replace(
        "as-of leakage filter runs BEFORE any width slicing", "leakage filter runs BEFORE any width slicing")
    for excluded in ("rerank pool", "coalescer", "timeline floors", "recency_days",
                     "max_tokens", "cascade_quant"):
        assert excluded in doc, excluded


# ══ B -- resolution: fail-open, dark-by-default, flag grammar ════════════════════════════════════════
def test_absent_mode_resolves_to_standard_and_is_not_invalid():
    assert rm.resolve(None, rm.valid_names()) == {"requested": None, "honored": "standard",
                                                  "invalid": False}
    assert rm.resolve("", rm.valid_names())["honored"] == "standard"


def test_unknown_mode_fails_open_with_the_invalid_stamp():
    """A desk turn must not die on a typo: unknown -> standard + invalid, NEVER a raise/400."""
    out = rm.resolve("turbo", rm.valid_names())
    assert out == {"requested": "turbo", "honored": "standard", "invalid": True}


def test_requested_is_normalized_case_and_whitespace():
    assert rm.resolve("  DEEP ", {"deep"})["requested"] == "deep"
    assert rm.resolve("  DEEP ", {"deep"})["honored"] == "deep"


def test_dark_stage_accepts_and_stamps_but_does_not_honor():
    """Stage 0: the request is recorded (the free tally of what users would pick) while the knobs
    stay standard. `requested` survives, `honored` does not."""
    out = rm.resolve("deep", frozenset())
    assert out == {"requested": "deep", "honored": "standard", "invalid": False}
    assert rm.knobs(out["honored"]) == {}


def test_standard_never_needs_the_flag():
    assert rm.resolve("standard", frozenset())["honored"] == "standard"


def test_flag_value_grammar_mirrors_the_contracts_flag(monkeypatch):
    assert orch._modes_enabled() == frozenset()                       # absent
    monkeypatch.setenv("GRAPHRAG_MODES", "off")
    assert orch._modes_enabled() == frozenset()
    for on in ("on", "1", "true", "ON"):
        monkeypatch.setenv("GRAPHRAG_MODES", on)
        assert orch._modes_enabled() == rm.serving_names()             # D-DV: dark presets excluded
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,bogus")
    assert orch._modes_enabled() == frozenset({"quick"})              # unknown names ignored, never fatal
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep")
    assert orch._modes_enabled() == frozenset({"quick", "deep"})


# ══ C -- BYTE IDENTITY at every threaded seam (the acceptance bar) ═══════════════════════════════════
def _capture_l2(monkeypatch, *, mode_knobs=None):
    """Drive answer(planner='l2') far enough to capture the walk kwargs, the ground kwargs and the
    retrieval partial the body built, then stop. Nothing downstream of ground() runs."""
    seen: dict = {}

    def _gs(query, graph, **kw):
        seen["walk"] = dict(kw)
        return types.SimpleNamespace(nodes=[], seeds=[], trace={}, fired_regimes=[], mermaid="")

    def _ground(sg, query, graph, **kw):
        seen["ground"] = dict(kw)
        raise _Stop
    monkeypatch.setattr(pl, "grounded_subgraph", _gs)
    monkeypatch.setattr(pl, "ground", _ground)
    kw = {"mode_knobs": mode_knobs} if mode_knobs else {}
    with pytest.raises(_Stop):
        an.answer("why is corn bid", graph=_graph(), asof="2024-06-01", planner="l2",
                  call=_reason_call, route_fn=lambda q, gg: ["corn"], **kw)
    return seen


def test_walk_and_ground_kwargs_are_untouched_on_standard_and_dark(monkeypatch):
    """The passthrough pin, proven by capture: with no honored mode the walk call carries ONLY
    route_fn and the ground call carries ONLY the pre-existing keywords."""
    base = _capture_l2(monkeypatch)
    dark = _capture_l2(monkeypatch, mode_knobs=rm.knobs("standard"))   # dark resolves to {} upstream
    assert set(base["walk"]) == {"route_fn"}
    assert set(base["ground"]) == {"retrieve", "silver_lookup", "asof", "near", "probe_retrieve", "on_stage"}
    assert set(dark["walk"]) == set(base["walk"]) and set(dark["ground"]) == set(base["ground"])


def test_honored_mode_threads_walk_and_ground_knobs(monkeypatch):
    # P4-ARM COMMIT (plan 12c): the tiers thread per_seed_budget, never a flat node_budget --
    # the walk derives budget x realized seeds.
    seen = _capture_l2(monkeypatch, mode_knobs=rm.knobs("deep"))
    assert seen["walk"]["per_seed_budget"] == 32 and "node_budget" not in seen["walk"]
    assert seen["walk"]["depth"] == 1
    assert seen["walk"]["max_seeds"] == 4                      # D-MW-13: deep's tier ceiling
    assert seen["ground"]["k_by_depth"] == (7, 5)
    assert seen["ground"]["evidence_cap"] == 48 and seen["ground"]["probe_cap"] == 36
    quick = _capture_l2(monkeypatch, mode_knobs=rm.knobs("quick"))
    assert quick["walk"]["per_seed_budget"] == 12 and "node_budget" not in quick["walk"]
    assert quick["ground"]["k_by_depth"] == (4, 2)


def test_cap_policy_rides_the_seam_evidence_cap_already_rides(monkeypatch):
    """cap_policy is a planner.ground KEYWORD, so it threads through ground_kwargs beside evidence_cap
    -- no new plumbing path. order_policy is NOT: it is consumed in answer.py (like fetch_k and the
    scaffold caps), so it must stay OFF the ground call or the callee would 400 on it."""
    deep_v2 = _capture_l2(monkeypatch, mode_knobs=rm.knobs("deep_v2"))
    assert deep_v2["ground"]["cap_policy"] == "score" and deep_v2["ground"]["evidence_cap"] == 24
    assert "order_policy" not in deep_v2["ground"] and "order_policy" not in deep_v2["walk"]
    for name in ("standard", "quick", "deep"):                         # absent, not None -- omit-when-default
        assert "cap_policy" not in _capture_l2(monkeypatch, mode_knobs=rm.knobs(name))["ground"]


def test_fetch_k_rides_a_per_call_partial_rebind(monkeypatch):
    """Concurrency-safe by construction: the width lives on the LOCAL partial, never on a module
    global, so two concurrent turns on different modes cannot see each other's fetch_k."""
    base = _capture_l2(monkeypatch)
    assert "fetch_k" not in base["ground"]["retrieve"].keywords          # standard: untouched
    deep = _capture_l2(monkeypatch, mode_knobs=rm.knobs("deep"))
    # D-DV-1a: a fetch_k ABOVE RERANK_POOL deleted the BM25 leg outright (the pool cut runs after fusion),
    # so this is not a taste pin -- it is the retrieval leg's precondition.
    assert deep["ground"]["retrieve"].keywords["fetch_k"] == 60
    assert deep["ground"]["retrieve"].keywords["fetch_k"] <= _rk.RERANK_POOL
    quick = _capture_l2(monkeypatch, mode_knobs=rm.knobs("quick"))
    assert quick["ground"]["retrieve"].keywords["fetch_k"] == 40
    assert an.ev.retrieve.__module__                                     # the partial still wraps ev.retrieve
    assert deep["ground"]["retrieve"].func is an.ev.retrieve


def _respond_capture(monkeypatch, *, mode=None, flag=None, kind="reasoning", call=_reason_call,
                     query="why is corn bid on a drought", **extra):
    """Run a turn with the lane runner replaced by a kwarg recorder."""
    seen: dict = {}
    # The flag is set EXPLICITLY on every call (never inherited from an earlier call in the same
    # test): a leaked allowlist would make the dark-passthrough assertions vacuously green.
    if flag is None:
        monkeypatch.delenv("GRAPHRAG_MODES", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_MODES", flag)

    def _runner(q, asof, **kw):
        seen.update(kw)
        return {"answer": "a", "intent": kind, "trace": {}, "citations": [], "evidence": [],
                "number_calls": [], "structured": None, "contract": None, "contracts": []}
    monkeypatch.setattr(orch, "run_reasoning", _runner)
    monkeypatch.setattr(orch, "run_hybrid", _runner)
    kw = {"mode": mode} if mode is not None else {}
    out = orch.respond(query, graph=_graph(), asof="2024-06-01", classify=_force(kind),
                       call=call, retrieve=_retrieve, **kw, **extra)
    return out, seen


def test_orchestrator_omits_the_mode_knobs_kwarg_on_standard_and_dark(monkeypatch):
    """The omit-when-default idiom at the lane seam: no honored mode => the kwarg is ABSENT, so an
    injected fake runner with the pre-D-AM signature keeps working and the call is byte-identical."""
    _o, none_kw = _respond_capture(monkeypatch)
    assert "mode_knobs" not in none_kw
    _o, std_kw = _respond_capture(monkeypatch, mode="standard", flag="on")
    assert "mode_knobs" not in std_kw
    _o, dark_kw = _respond_capture(monkeypatch, mode="deep")           # requested, NOT allowlisted
    assert "mode_knobs" not in dark_kw
    _o, bad_kw = _respond_capture(monkeypatch, mode="turbo", flag="on")
    assert "mode_knobs" not in bad_kw


def test_orchestrator_threads_resolved_knobs_when_honored(monkeypatch):
    _o, kw = _respond_capture(monkeypatch, mode="quick", flag="quick")
    assert kw["mode_knobs"] == rm.knobs("quick")
    _o, kw2 = _respond_capture(monkeypatch, mode="deep", flag="quick")   # deep not yet allowlisted
    assert "mode_knobs" not in kw2


def test_hybrid_lane_threads_the_same_kwarg(monkeypatch):
    _o, kw = _respond_capture(monkeypatch, mode="deep", flag="on", kind="hybrid")
    assert kw["mode_knobs"] == rm.knobs("deep")


def test_run_reasoning_and_run_hybrid_omit_the_kwarg_downstream(monkeypatch):
    """One hop lower: the two lane runners use the same idiom into answer()."""
    seen: dict = {}

    def _answer(q, **kw):
        seen.clear()
        seen.update(kw)
        return {"answer": "a", "trace": {}, "citations": [], "evidence": [], "structured": None,
                "contract": None, "contracts": [], "model": "m"}
    monkeypatch.setattr(an, "answer", _answer)
    orch.run_reasoning("q", "2024-06-01", graph=_graph())
    assert "mode_knobs" not in seen
    orch.run_reasoning("q", "2024-06-01", graph=_graph(), mode_knobs={})
    assert "mode_knobs" not in seen                                   # empty is not a decision
    orch.run_reasoning("q", "2024-06-01", graph=_graph(), mode_knobs=rm.knobs("deep"))
    assert seen["mode_knobs"] == rm.knobs("deep")


def test_silver_cap_rides_the_existing_kwarg_only_when_honored(monkeypatch):
    """The silver factory seam sits ABOVE the contract decision point, which is why the mode is
    resolved at the top of the turn -- captured here so that ordering stays load-bearing."""
    seen: list = []

    def _mk(graph, query_fn=None, **kw):
        seen.append(dict(kw))
        return None
    monkeypatch.setattr(slv, "make_silver_lookup", _mk)
    _o, _kw = _respond_capture(monkeypatch, call=None, query_fn=lambda *a, **k: None)
    assert seen and "cap" not in seen[-1]
    seen.clear()
    _o, _kw = _respond_capture(monkeypatch, mode="quick", flag="quick", call=None,
                               query_fn=lambda *a, **k: None)
    assert seen[-1]["cap"] == 4


def test_xc_gate_force_off_and_the_deep_arms_leave_the_flag_alone(monkeypatch):
    """quick suppresses the REQUEST only (the detect attribution still stamps). deep's xc_force was
    True and is now None (D-DV-1d): forcing the reroute-v2 leg widened the [N] namespace and mis-paired
    indices -- number_mismatch 2/2/11 with a clean off/flag/forced-on dose-response. Both deep arms
    therefore follow the flag exactly as standard does, in BOTH directions."""
    calls: list = []

    def _gate(query, **kw):
        calls.append(query)
        return {"pair": ["corn", "wheat"]}
    monkeypatch.setattr(orch, "_xc_request", _gate)

    monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")
    out, kw = _respond_capture(monkeypatch, mode="quick", flag="quick")
    assert calls == [] and kw.get("xc_request") is None                # force OFF beats the flag
    assert out["intent_decision"]["xc_detect"]["tier"] == "none"       # attribution still stamped

    for mode in ("deep", "deep_v2"):
        calls.clear()
        monkeypatch.delenv("GRAPHRAG_REROUTE_V2", raising=False)       # flag OFF -> no request...
        out, kw = _respond_capture(monkeypatch, mode=mode, flag=mode)
        assert calls == [] and kw.get("xc_request") is None, mode
        calls.clear()
        monkeypatch.setenv("GRAPHRAG_REROUTE_V2", "on")                # ...flag ON -> the gate decides
        out, kw = _respond_capture(monkeypatch, mode=mode, flag=mode)
        assert len(calls) == 1 and kw["xc_request"] == {"pair": ["corn", "wheat"]}, mode

    calls.clear()
    monkeypatch.delenv("GRAPHRAG_REROUTE_V2", raising=False)
    out, kw = _respond_capture(monkeypatch)                            # standard + flag off: untouched
    assert calls == [] and kw.get("xc_request") is None


def test_exempt_lanes_never_grow_the_kwarg():
    """DECLARED, not discovered (the D-RC precedent): live runs no walk/ground/contract/scaffold and
    numbers_only has no answer.py seam, so no v1 knob can land there."""
    assert "mode_knobs" not in inspect.signature(orch.run_live).parameters
    assert "mode_knobs" not in inspect.signature(orch.run_numbers_only).parameters
    assert "mode_knobs" in inspect.signature(orch.run_reasoning).parameters
    assert "mode_knobs" in inspect.signature(orch.run_hybrid).parameters
    assert "mode_knobs" in inspect.signature(an.answer).parameters
    assert "mode_knobs" in inspect.signature(an._answer_l2).parameters


# ══ D -- the contract word budget ════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("budget,scale,want", [
    ("150-220", 0.7, "110-150"), ("150-220", 1.5, "230-330"),
    ("120-200", 0.7, "80-140"), ("120-200", 1.5, "180-300"),
    ("90-160", 0.7, "60-110"), ("220-320", 1.5, "330-480"),
    ("60-120", 0.7, "40-80"),
])
def test_budget_scaling_arithmetic(budget, scale, want):
    """Half-up to the nearest 10 at BOTH ends -- deterministic on purpose (round() is banker's
    rounding, which would send 105 to 100 and make the two ends round by different rules)."""
    assert rm.scale_budget(budget, scale) == want


def test_budget_scaling_is_fail_open():
    assert rm.scale_budget("150-220", None) is None                   # no mode -> leave it alone
    assert rm.scale_budget(None, 0.7) is None
    assert rm.scale_budget("about two hundred", 0.7) is None          # unparseable -> untouched
    assert rm.scale_budget("5-8", 0.1) == "10-10"                     # floor 10, hi never below lo


def test_mode_budget_needs_an_ACTIVE_contract():
    """The default persona's own range is a pinned needle of _SYSTEM_MENTOR and is never mode-varied;
    only the CONTRACT's range scales."""
    assert an._mode_budget(None, rm.knobs("quick")) is None
    assert an._mode_budget("ranking", {}) is None
    assert an._mode_budget("ranking", rm.knobs("standard")) is None
    assert an._mode_budget("ranking", rm.knobs("quick")) == rm.scale_budget(
        rc.CONTRACTS["ranking"].budget, 0.7)


def test_apply_and_system_carry_the_scaled_budget(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
    plain = rc.apply(an._SYSTEM_MENTOR, "ranking")
    scaled = rc.apply(an._SYSTEM_MENTOR, "ranking", budget="60-110")
    assert "target 90-160 words across the 3 sections" in plain
    assert "target 60-110 words across the 3 sections" in scaled
    assert rc.apply(an._SYSTEM_MENTOR, "ranking", budget=None) == plain      # None = untouched
    # ...and the persona builder threads it (both serving bodies call _system the same way).
    assert an._system(response_contract="ranking", budget="60-110") != an._system(
        response_contract="ranking")
    assert an._system(response_contract="ranking", budget=None) == an._system(
        response_contract="ranking")


def test_budget_override_never_leaks_onto_the_default_persona():
    base = an._system()
    assert an._system(budget="10-20") == base                          # no contract -> apply() is identity
    assert an._system(response_contract="outlook", budget="10-20") == base   # passthrough too


# ══ E -- the episode-scaffold caps ═══════════════════════════════════════════════════════════════════
def test_scaffold_cap_kwargs_omit_when_absent():
    assert an._scaffold_cap_kwargs(None) == {}
    assert an._scaffold_cap_kwargs({}) == {}
    assert an._scaffold_cap_kwargs(rm.knobs("standard")) == {}
    assert an._scaffold_cap_kwargs(rm.knobs("quick")) == {"max_bullets": 6, "max_absence": 3}
    assert an._scaffold_cap_kwargs(rm.knobs("deep")) == {"max_bullets": 12, "max_absence": 6}


class _Node:
    def __init__(self, nid, episodes):
        self.id = nid
        self.episodes = episodes


def _scaffold(monkeypatch, n_eps, **caps):
    monkeypatch.setenv("GRAPHRAG_EPISODE_SCAFFOLD", "on")
    eps = [{"start": f"20{10 + i:02d}-06-10", "end": f"20{10 + i:02d}-08-01", "n": 3, "receipt": None}
           for i in range(n_eps)]
    injected = [{"node": "drivers/frost", "line": tl.render_line("drivers/frost", eps),
                 "spans": [tl.month_span(e) for e in eps],
                 "windows": [{"start": tl.day_window(e)[0], "end": tl.day_window(e)[1],
                              "span": tl.month_span(e), "n": e.get("n")} for e in eps]}]
    structured = {"tldr": "t", "mechanism": "## Mechanism\nFrost tightens the sheet.\n"
                                            "## What to watch\nCold fronts.\n", "sources": []}
    verifier = {"enabled": True, "checked": 1, "stripped": 0, "corrected": 0, "claim_count": 3,
                "by_rule": {}, "resolved": {}}
    return an._maybe_scaffold_episodes(structured, verifier, injected=injected,
                                       nodes=[_Node("drivers/frost", eps)], evidence=[],
                                       n_positional=0, **caps)


def test_scaffold_caps_default_to_params_and_are_overridden_by_the_mode(monkeypatch):
    """The params value stays the authority when no override arrives (standard/dark byte-identity);
    the mode's integers win when they do. Both directions, on the same fixture."""
    default = _scaffold(monkeypatch, 8)
    assert default["episodes_scaffolded"]["fired"] is True
    quick = _scaffold(monkeypatch, 8, **an._scaffold_cap_kwargs(rm.knobs("quick")))
    assert quick["episodes_scaffolded"]["fired"] is True
    assert quick["episodes_scaffolded"]["n_bullets"] == 3              # quick's absence cap
    assert default["episodes_scaffolded"]["n_bullets"] == 6            # the params default
    assert _scaffold(monkeypatch, 8, **an._scaffold_cap_kwargs(rm.knobs("standard"))) == default


# ══ F -- observability, IN THE SAME CHANGE ═══════════════════════════════════════════════════════════
def test_decided_mode_is_stamped_on_every_turn(monkeypatch):
    out, _kw = _respond_capture(monkeypatch)
    assert out["intent_decision"]["mode"] == {"requested": None, "honored": "standard",
                                              "invalid": False}
    out, _kw = _respond_capture(monkeypatch, mode="deep")              # DARK: stamped, not honored
    assert out["intent_decision"]["mode"] == {"requested": "deep", "honored": "standard",
                                              "invalid": False}
    out, _kw = _respond_capture(monkeypatch, mode="deep", flag="on")
    assert out["intent_decision"]["mode"]["honored"] == "deep"


def test_decided_mode_rides_the_exempt_lanes_too(monkeypatch):
    """'Every turn' means EVERY turn: the live lane runs no knobs but still records what was asked
    for, so the stage-0 tally is not silently blind to a whole lane."""
    def _fake_live(q, a, **k):
        return {"answer": "hx", "intent": "live", "trace": {}, "citations": [], "evidence": [],
                "number_calls": [], "structured": None, "contract": None, "contracts": []}
    monkeypatch.setattr(orch, "run_live", _fake_live)
    monkeypatch.setenv("GRAPHRAG_MODES", "deep")
    out = orch.respond("any news on corn today?", graph=_graph(), mode="deep",
                       classify=_force("live"))
    assert out["intent_decision"]["mode"]["requested"] == "deep"
    assert out["intent_decision"]["mode"]["honored"] == "deep"
    # ...and the trace does NOT claim a depth that never ran: the live lane consumes no knob, so
    # `mode_knobs` stays absent. Asked-for and actually-ran are different facts, kept apart.
    assert "mode_knobs" not in (out.get("trace") or {})


def test_invalid_mode_never_raises_and_stamps_the_flag(monkeypatch):
    out, kw = _respond_capture(monkeypatch, mode="ultra", flag="on")
    assert out["intent_decision"]["mode"] == {"requested": "ultra", "honored": "standard",
                                              "invalid": True}
    assert "mode_knobs" not in kw and out["answer"]                    # the turn ANSWERED


def test_trace_carries_the_resolved_knobs_only_when_honored(monkeypatch):
    out, _kw = _respond_capture(monkeypatch, mode="deep", flag="deep")
    knobs = out["trace"]["mode_knobs"]
    assert knobs["fetch_k"] == 60 and knobs["evidence_cap"] == 48
    assert knobs["k_by_depth"] == [7, 5]                               # listed for JSON/DDB fidelity
    out, _kw = _respond_capture(monkeypatch, mode="deep_v2", flag="deep_v2")
    knobs = out["trace"]["mode_knobs"]                                 # the two policy strings must be
    assert knobs["cap_policy"] == "score" and knobs["order_policy"] == "relevance"   # READABLE in the
    assert knobs["evidence_cap"] == 24                                 # eval artifact, or no arm is
                                                                       # attributable after the fact
    out, _kw = _respond_capture(monkeypatch, mode="deep")              # dark
    assert "mode_knobs" not in (out.get("trace") or {})                # OFF-arm clean
    out, _kw = _respond_capture(monkeypatch)
    assert "mode_knobs" not in (out.get("trace") or {})


def test_tracekeys_registration_is_the_eval_registration():
    """D-AM-3: registering here IS registering in the eval artifact (eval loops these tuples)."""
    assert "mode_knobs" in tk.TRACE_RECORD_KEYS
    assert dict(tk.DECISION_RECORD_KEYS)["mode"] == "mode_decision"
    assert len(set(tk.TRACE_RECORD_KEYS)) == len(tk.TRACE_RECORD_KEYS)
    cols = [c for _k, c in tk.DECISION_RECORD_KEYS]
    assert len(set(cols)) == len(cols)


def test_the_eval_record_actually_carries_the_mode_columns():
    rec = evl._per_answer_record(
        {"q": {"id": "q1"}, "out": {"answer": "a", "structured": None, "evidence": [],
                                    "citations": [], "trace": {"mode_knobs": {"fetch_k": 120}},
                                    "intent_decision": {"mode": {"requested": "deep",
                                                                 "honored": "deep",
                                                                 "invalid": False}}}},
        "single")
    assert rec["mode_knobs"] == {"fetch_k": 120}
    assert rec["mode_decision"]["honored"] == "deep"


def test_emf_dimensions_carry_mode(monkeypatch):
    """Without this dimension StripCount/TurnLatencyMs mix populations the moment a mode is honored,
    and every dashboard series becomes uninterpretable after the fact."""
    seen: list = []
    monkeypatch.setattr(emfmod, "emit",
                        lambda metrics, **kw: seen.append((metrics, kw.get("dimensions") or {})))
    _respond_capture(monkeypatch, mode="deep", flag="deep")
    dims = [d for _m, d in seen if "TurnLatencyMs" in _m]
    assert dims and dims[0]["mode"] == "deep"
    assert dims[0]["intent"] == "reasoning"                            # the pre-existing keys survive
    seen.clear()
    _respond_capture(monkeypatch)
    dims = [d for _m, d in seen if "TurnLatencyMs" in _m]
    assert dims and dims[0]["mode"] == "standard"                      # true by construction: no knobs ran


def test_eval_arm_identity_learns_the_request_level_mode():
    """D-AM-11: the arm stamp read PROCESS ENV only, so two mode arms would have been identical in
    every reproducibility key except ts."""
    assert "mode" in inspect.signature(evl._baseline_json).parameters
    assert "mode" in inspect.signature(evl.run).parameters
    b = evl._baseline_json([], run_kind="single", model="m", judged=False, eval_set="s",
                           graph_version="v", corpus_fp="f", mode="deep")
    assert b["mode"] == "deep"
    assert evl._baseline_json([], run_kind="single", model="m", judged=False, eval_set="s",
                              graph_version="v", corpus_fp="f")["mode"] is None


# ══ G -- the request field ═══════════════════════════════════════════════════════════════════════════
def test_ask_model_and_sse_query_string_carry_mode():
    from leviathan.graphrag import server as sv
    assert "mode" in sv.Ask.model_fields
    assert sv.Ask(question="q").mode is None
    assert sv.Ask(question="q", mode="turbo").mode == "turbo"          # NOT an enum: no 422 on a typo
    assert "mode" in inspect.signature(sv.respond_stream).parameters
    assert "mode" in inspect.signature(orch._respond).parameters
