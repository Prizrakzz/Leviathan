"""D-MW-30 (MOAT_WIDTH_WAVE_PLAN 30b/30c, spec-review fold 30e): the ESCALATED BUNDLE's two presets and
the synthesis/render half of the seam -- the synth seat (F5) and the provenance rendering + invitation
(30c / F14).

THE DOCTRINE UNDER TEST (12e, measured across two writers): width is a QUESTION SHAPE, not a tier. The
user picks the cost envelope (`deep`); the planner picks the shape inside it. So `esc` must be DEEP's
turn in every respect that decides routing, price or pre-plan shape, and MAX's turn only in width -- if
those two halves ever drift, an escalated turn silently becomes a different product than the one the
user paid for, and the gate's read attributes a bundle win to the wrong variable (F13).

THE FOUR THINGS THIS FILE REFUSES TO LET DRIFT:
  1. F9 -- deep/esc/esc_r are IDENTICAL on every pre-plan and non-walk knob (`max_seeds` included: the
     escalation buys evidence DEPTH on a <= 2-seed question, never a wider fan-in).
  2. F8 -- both presets are DARK, and `serving_names()` is unchanged. A forgotten dark entry is an
     UNMETERED max-width + opus turn for anyone who types the name with the wildcard on.
  3. F7 -- the two new Mode fields are None (never False, never "") everywhere else, so `knobs()`
     cannot mint them into another preset's trace stamp.
  4. F14 -- the provenance render touches the PROMPT HEADER and nothing else: the flat evidence list,
     the E-numbering and the verifier's resolution set are built from `n.evidence`, not from the
     rendered block, and this file proves that by comparing both renders row for row.

All offline: no pg, no S3, no LLM, no AWS. ASCII-only output (the Windows console is cp1252)."""
from __future__ import annotations

import inspect

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import planner as pl
from leviathan.graphrag import reasoning_modes as rm
from leviathan.graphrag import response_contracts as rc

# The knobs that MAY differ between deep and the escalated bundle. Everything else is deep's value by
# law (F9) -- silver_cap / max_seeds / xc_force are consumed BEFORE the plan exists, and fetch_k, the
# scaffold caps and budget_scale are not width at all. `node_budget` / `evidence_cap` / `probe_cap` are
# in here for the max preset's own recorded reason: the per-seed quartet REPLACES them (they are derived
# from the realized seed count at walk/ground time), so esc/esc_r leave them absent rather than carry
# deep's flat 48/36 into a trace stamp beside the per-seed numbers that actually ran.
_MAY_DIFFER = frozenset({"depth", "k_by_depth", "cap_policy", "order_policy",
                         "per_seed_budget", "per_seed_evidence_cap", "per_seed_probe_cap",
                         "per_seed_reserve", "synth_model", "provenance_prompt",
                         "node_budget", "evidence_cap", "probe_cap"})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every pin states its own flag state -- an inherited allowlist or synth-model env would make the
    dark-roster and precedence assertions vacuously green."""
    monkeypatch.delenv("GRAPHRAG_MODES", raising=False)
    monkeypatch.delenv("GRAPHRAG_SYNTH_MODEL", raising=False)
    monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
    monkeypatch.delenv("GRAPHRAG_RESPONSE_CONTRACT", raising=False)


# ══ A -- the two presets ═════════════════════════════════════════════════════════════════════════════
def test_esc_preset_matches_the_ratified_12e_bundle():
    """30b, transcribed. The width values are MAX's measured shape (STEP-0: per-seed cosine demand p75
    = 63; ground caps 24/24) and the writer is the 12e width-deck winner. Everything else is deep's."""
    assert rm.knobs(rm.ESC) == {
        "depth": 2, "max_seeds": 4,                       # F9: deep's CEILING -- routing never escalates
        "k_by_depth": (7, 5, 3),
        "fetch_k": 60, "silver_cap": 12,
        "scaffold_max_bullets": 12, "scaffold_max_absence": 6,
        "cap_policy": "score", "order_policy": "relevance",
        "per_seed_budget": 63, "per_seed_evidence_cap": 24, "per_seed_probe_cap": 24,
        "per_seed_reserve": 0,
        "synth_model": "claude-opus-5"}
    # The :204-206 absent-pin pattern, restated for the escalated bundle and load-bearing HERE in a way
    # it was not on max: deep carries FLAT evidence_cap=48 / probe_cap=36, so inheriting "deep's values"
    # literally would have put a stale pair in the artifact beside the per-seed values that ran.
    for absent in ("node_budget", "evidence_cap", "probe_cap"):
        assert absent not in rm.knobs(rm.ESC), absent
        assert getattr(rm.MODES[rm.ESC], absent) is None, absent
    assert rm.MODES[rm.ESC].provenance_prompt is None                  # the invitation rides esc_r ONLY


def test_esc_r_is_esc_plus_the_reserve_bundle_and_nothing_else():
    """30b: the pair differs by the reserve BUNDLE exactly like max/max_c0 differed by the reserve --
    per_seed_reserve 4 AND the provenance prompt, together. They ride together on purpose: 12e's finding
    was that admission works and citation does not follow when the writer cannot tell a structural node
    from a cosine one, so re-testing the reserve without the provenance half would re-run a measurement
    that already returned its verdict (12c)."""
    esc, esc_r = rm.MODES[rm.ESC], rm.MODES[rm.ESC_R]
    differ = [f for f in rm.KNOB_FIELDS if getattr(esc, f) != getattr(esc_r, f)]
    assert differ == ["per_seed_reserve", "provenance_prompt"], differ
    assert esc.per_seed_reserve == 0 and esc_r.per_seed_reserve == 4
    assert esc_r.provenance_prompt is True
    assert esc.name == "esc" and esc_r.name == "esc_r"


def test_zero_is_a_value_on_esc_so_the_off_arm_cannot_run_the_on_mechanism():
    """The max_c0 lesson, re-applied: `knobs()` drops None, so a per_seed_reserve that fell through as
    None would leave GRAPHRAG_CLOSURE_RESERVE deciding esc's reservation -- and the A arm would silently
    run the very mechanism arm B exists to measure. 0 survives the filter and beats the env."""
    kn = rm.knobs(rm.ESC)
    assert kn["per_seed_reserve"] == 0 and "per_seed_reserve" in kn
    assert rm.walk_kwargs(kn)["per_seed_reserve"] == 0
    assert rm.walk_kwargs(rm.knobs(rm.ESC_R))["per_seed_reserve"] == 4


def test_f9_deep_esc_and_esc_r_are_identical_on_every_pre_plan_and_non_walk_knob():
    """THE ESCALATION LAW. silver_cap / max_seeds / xc_force are consumed BEFORE the plan exists
    (orchestrator :1845/:1871/:2032), so an escalation that moved them would change the turn's ROUTING
    and pre-plan shape rather than its width -- two variables in a one-variable arm. fetch_k, the
    scaffold caps and budget_scale are not width at all. Pinned as a SET DIFFERENCE, not a list of
    values: a future knob appended to Mode is caught here on the day it lands."""
    deep, esc, esc_r = rm.MODES[rm.DEEP], rm.MODES[rm.ESC], rm.MODES[rm.ESC_R]
    shared = [f for f in rm.KNOB_FIELDS if f not in _MAY_DIFFER]
    assert shared, "the may-differ set must never swallow the whole table"
    for f in shared:
        assert getattr(deep, f) == getattr(esc, f) == getattr(esc_r, f), f
    assert deep.max_seeds == esc.max_seeds == esc_r.max_seeds == 4      # the headline: routing is FIXED
    assert deep.silver_cap == esc.silver_cap == 12
    assert deep.xc_force is esc.xc_force is None
    # ...and the width half really did move (otherwise the pin above would be vacuously satisfied by an
    # esc that is just deep under another name).
    assert (esc.per_seed_budget, esc.depth, esc.k_by_depth) == (63, 2, (7, 5, 3))
    assert deep.per_seed_budget == 32 and deep.depth == 1


def test_f7_the_two_new_fields_are_none_on_every_other_preset():
    """The byte-identity law for D-MW-30's two Mode fields. None is the ONLY correct absent value:
    `knobs()` filters `is not None`, so a literal False or "" would MINT the key into deep's trace stamp
    and break the identity every dark/standard pin in the suite rests on."""
    for name in (rm.QUICK, rm.STANDARD, rm.DEEP, rm.DEEP_V2, rm.MAX, rm.MAX_C0):
        m = rm.MODES[name]
        assert m.synth_model is None, name
        assert m.provenance_prompt is None, name                        # never False -- None
        assert "synth_model" not in rm.knobs(name), name
        assert "provenance_prompt" not in rm.knobs(name), name
    assert rm.MODES[rm.ESC].provenance_prompt is None                   # esc too: the invitation is esc_r's
    # The all-None `standard` guarantee still covers the new tail by construction (it iterates the fields).
    assert all(getattr(rm.MODES[rm.STANDARD], f) is None for f in rm.KNOB_FIELDS)
    assert rm.knobs(rm.STANDARD) == {}


def test_f8_both_presets_are_dark_and_serving_names_is_unchanged(monkeypatch):
    """THE LEAK FENCE. serving_names() is what `GRAPHRAG_MODES=on` may sweep in; a forgotten DARK entry
    would make the escalated bundle wildcard-honorable, i.e. an UNMETERED max-width + opus turn for
    anyone who types the name. Serving reaches esc/esc_r ONLY through the escalation seam, which stamps
    honored=deep and prices deep -- the preset names are for eval arms."""
    assert {rm.ESC, rm.ESC_R} <= rm.DARK_NAMES
    assert rm.serving_names() == frozenset({"quick", "standard", "deep"})
    for on in ("on", "1", "true"):
        monkeypatch.setenv("GRAPHRAG_MODES", on)
        assert rm.ESC not in orch._modes_enabled() and rm.ESC_R not in orch._modes_enabled()
        assert rm.resolve("esc", orch._modes_enabled())["honored"] == "standard"
        assert rm.resolve("esc_r", orch._modes_enabled())["honored"] == "standard"
    # ...but still RESOLVABLE by name, which is how F11's arms reach them
    # (--env GRAPHRAG_MODES=deep,esc,esc_r).
    monkeypatch.setenv("GRAPHRAG_MODES", "deep,esc,esc_r")
    assert orch._modes_enabled() == frozenset({"deep", "esc", "esc_r"})
    assert rm.resolve("esc", orch._modes_enabled())["honored"] == "esc"
    assert rm.resolve("esc_r", orch._modes_enabled())["honored"] == "esc_r"
    assert rm.resolve("ESC ", orch._modes_enabled())["honored"] == "esc"      # normalized, like any name


def test_the_two_new_knobs_never_leak_onto_a_callee_that_would_reject_them():
    """synth_model and provenance_prompt are consumed in answer.py (like fetch_k and order_policy), NOT
    by the planner. If either rode walk_kwargs/ground_kwargs the first escalated turn would be a
    TypeError, not a subtle regression."""
    for name in (rm.ESC, rm.ESC_R):
        kn = rm.knobs(name)
        wk, gk = rm.walk_kwargs(kn), rm.scaled_ground_kwargs(kn, 2)
        for leaked in ("synth_model", "provenance_prompt"):
            assert leaked not in wk and leaked not in gk, (name, leaked)
        assert set(wk) <= set(inspect.signature(pl.grounded_subgraph).parameters), name
        assert set(gk) <= set(inspect.signature(pl.ground).parameters), name


@pytest.mark.parametrize("n,evidence,probe", [(1, 24, 24), (2, 48, 48)])
def test_the_escalated_ground_caps_scale_at_the_seed_counts_it_can_actually_fire_on(n, evidence, probe):
    """F1 bounds firing at <= 2 PLANNED contracts and `_seed_contracts` de-dups + truncates, so a live
    escalation grounds at 1-2 realized seeds. The one producer's arithmetic at exactly those counts --
    nowhere near the 144/96 totals, so the clamps are not what shapes an escalated turn."""
    out = rm.scaled_ground_kwargs(rm.knobs(rm.ESC), n)
    assert out["evidence_cap"] == evidence and out["probe_cap"] == probe
    assert out["k_by_depth"] == (7, 5, 3) and out["cap_policy"] == "score"
    assert rm.scaled_ground_kwargs(rm.knobs(rm.ESC_R), n) == out        # the reserve is a WALK knob


# ══ B -- F5: the synthesis seat ══════════════════════════════════════════════════════════════════════
def _graph() -> g.CausalGraph:
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                mechanism="dryness cuts yield")])
    return g.CausalGraph({"corn": corn}, silver=set())


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2024-01-01", "source": "usda_wasde", "source_key": f"s3://{node}", "text": "note"}]


def _model_seen(monkeypatch, **kw):
    seen: list = []

    def _call(system, user, *, model, tool, **_kw):
        seen.append(model)
        return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}
    an.answer("why is corn bid", graph=_graph(), asof="2024-06-01", call=_call, retrieve=_retrieve, **kw)
    return seen[-1]


def test_the_mode_synth_model_fills_the_default_and_outranks_the_env(monkeypatch):
    """F5: ONE seam (the default-only branch), ranked mode > env > params. The mode outranks the env
    because a per-request escalation must beat a process-wide default -- otherwise a task env pinning
    sonnet would silently strip the writer half off a bundle that was MEASURED with it (12e)."""
    assert _model_seen(monkeypatch) == an.SONNET                             # nothing set: untouched
    assert _model_seen(monkeypatch, mode_knobs=rm.knobs(rm.ESC)) == "claude-opus-5"
    assert _model_seen(monkeypatch, mode_knobs=rm.knobs(rm.ESC_R)) == "claude-opus-5"
    monkeypatch.setenv("GRAPHRAG_SYNTH_MODEL", "claude-sonnet-5")
    assert _model_seen(monkeypatch) == "claude-sonnet-5"                     # env still fills the default
    assert _model_seen(monkeypatch, mode_knobs=rm.knobs(rm.ESC)) == "claude-opus-5"   # ...mode outranks it
    assert _model_seen(monkeypatch, mode_knobs=rm.knobs(rm.DEEP)) == "claude-sonnet-5"  # no knob -> env


def test_an_explicit_caller_model_still_beats_the_mode(monkeypatch):
    """THE PRECEDENCE LAW IS UNTOUCHED (test_dam_phase0:151 is its other half): the new rank lives
    INSIDE the `model == SONNET` guard, so eval --model, a test, or an operator override always wins.
    ARM HYGIENE (F5) depends on exactly this: the esc arms also pass --model claude-opus-5 so the
    artifact names the real writer, and that must not fight the preset."""
    monkeypatch.setenv("GRAPHRAG_SYNTH_MODEL", "claude-sonnet-5")
    assert _model_seen(monkeypatch, model="claude-haiku-4-5",
                       mode_knobs=rm.knobs(rm.ESC)) == "claude-haiku-4-5"
    assert _model_seen(monkeypatch, model="claude-opus-5",
                       mode_knobs=rm.knobs(rm.ESC)) == "claude-opus-5"       # the arm's own --model: agrees


# ══ C -- 30c / F14: the provenance render ════════════════════════════════════════════════════════════
def _prov_graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost kills trees"),
                 cs.Driver(id="freight", type="cost", sign="+", mechanism="freight costs"),
                 cs.Driver(id="diesel", type="cost", sign="+", mechanism="diesel prices")])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


def _node(nid, adm=None, rel=0.5):
    n = pl.GroundedNode(kind="driver", id=nid, contract="arabica_coffee", depth=1, relevance=rel)
    n.evidence = [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{nid}",
                   "text": f"row-{nid}"}]
    if adm is not None:
        n.admission = adm
    return n


def _prov_sg():
    """A seed + a COSINE driver + an UPSTREAM reserved driver + a DOWNSTREAM one with convergence --
    the four admission shapes a real escalated walk can produce, on one contract."""
    seed = pl.GroundedNode(kind="contract", id="arabica_coffee", contract="arabica_coffee",
                           depth=0, relevance=1.0)
    seed.evidence = [{"date": "2021-07-01", "source": "GAIN", "source_key": "s3://seed",
                      "text": "row-seed"}]
    seed.admission = dict(pl._ADMIT_COSINE)
    return pl.Subgraph(seeds=["arabica_coffee"], nodes=[
        seed,
        _node("frost", dict(pl._ADMIT_COSINE)),
        _node("freight", {"reason": pl.REASON_CLOSURE, "ancestor_of": "frost", "chain_depth": 1}),
        _node("diesel", {"reason": pl.REASON_DOWNSTREAM, "ancestor_of": "frost", "chain_depth": 2,
                         "convergence": True, "anchors": ["frost", "freight"]})])


def test_admission_note_reads_the_audit_record_the_walk_already_wrote():
    """The string is BUILT FROM planner's admission record, never recomputed -- so it can never disagree
    with the trace an artifact carries. Membership in _STRUCTURAL_REASONS, never a literal (D-MW-15):
    P6's third structural reason must annotate on the day it lands."""
    up = _node("freight", {"reason": pl.REASON_CLOSURE, "ancestor_of": "frost", "chain_depth": 1})
    assert an._admission_note(up) == " [graph admission: upstream ancestor of frost]"
    down = _node("diesel", {"reason": pl.REASON_DOWNSTREAM, "ancestor_of": "frost", "chain_depth": 2,
                            "convergence": True, "anchors": ["frost", "freight"]})
    assert an._admission_note(down) == (" [graph admission: downstream of frost, "
                                        "converges from 2 anchors]")
    assert pl.REASON_CLOSURE in pl._STRUCTURAL_REASONS and pl.REASON_DOWNSTREAM in pl._STRUCTURAL_REASONS


def test_admission_note_is_empty_for_every_non_structural_node():
    """Cosine nodes, seeds, the focus_driver inject and a node with no record at all render EXACTLY as
    before -- the annotation is a claim about HOW a node was reached and must never be minted for one
    that was reached the ordinary way."""
    assert an._admission_note(_node("frost", dict(pl._ADMIT_COSINE))) == ""
    assert an._admission_note(_node("frost")) == ""                          # no record -> nothing
    assert an._admission_note(_node("frost", {"reason": "focus_driver", "ancestor_of": None,
                                              "chain_depth": 0})) == ""
    assert an._admission_note(_node("frost", {})) == ""
    assert an._admission_note(object()) == ""                    # malformed -> fail-open, never raise
    # A structural record with no anchor still annotates (the DIRECTION is the useful half) and a
    # convergence flag with no anchor list adds no count rather than "converges from 0 anchors".
    assert an._admission_note(_node("x", {"reason": pl.REASON_CLOSURE, "ancestor_of": None})) == (
        " [graph admission: upstream structural admission]")
    assert an._admission_note(_node("x", {"reason": pl.REASON_CLOSURE, "ancestor_of": "frost",
                                          "convergence": True, "anchors": []})) == (
        " [graph admission: upstream ancestor of frost]")


def test_l2_blocks_is_byte_identical_with_provenance_off_even_on_a_reserved_walk():
    """THE OFF STATE, proven on the shape that would exercise the lever -- not on an empty walk. Default
    False, so every existing caller (the one-hop body, the eval harness, every test) is unchanged."""
    sg, gr = _prov_sg(), _prov_graph()
    base = an._l2_blocks(sg, gr, asof="2021-08-01")
    assert an._l2_blocks(sg, gr, asof="2021-08-01", provenance=False) == base
    assert "graph admission" not in "\n".join(base[0] + base[1])
    assert inspect.signature(an._l2_blocks).parameters["provenance"].default is False


def test_provenance_annotates_the_structural_headers_and_only_those():
    """30c: the reserved rows stop being anonymous. The COSINE driver's header and the contract header
    are untouched, because the annotation is the whole signal -- if everything carried one, nothing
    would."""
    sg, gr = _prov_sg(), _prov_graph()
    _stable, volatile = an._l2_blocks(sg, gr, asof="2021-08-01", provenance=True)
    blob = "\n".join(volatile)
    assert "--- DATED EVIDENCE for driver freight [graph admission: upstream ancestor of frost] ---" in blob
    assert ("--- DATED EVIDENCE for driver diesel [graph admission: downstream of frost, "
            "converges from 2 anchors] ---") in blob
    assert "--- DATED EVIDENCE for driver frost ---" in blob                 # cosine: untouched
    assert "--- DATED EVIDENCE for arabica_coffee ---" in blob               # contract header: untouched
    assert blob.count("graph admission") == 2


def test_the_header_text_is_invisible_to_citations_and_the_verifier():
    """F14's verified positive, PINNED rather than trusted. The flat evidence list _answer_l2 builds
    (answer.py :2104) walks `n.evidence` -- the dicts the header does not touch -- so E-numbering,
    the citation labels and the verifier's resolution set are identical with the lever on and off.
    If a future refactor ever built the citation set by parsing the rendered block, this reds."""
    sg, gr = _prov_sg(), _prov_graph()
    off = an._l2_blocks(sg, gr, asof="2021-08-01", provenance=False)
    on = an._l2_blocks(sg, gr, asof="2021-08-01", provenance=True)
    flat = [{**h, "contract": n.contract} for n in sg.nodes for h in n.evidence]
    assert all("graph admission" not in str(h) for h in flat)                # the ROWS are untouched
    cits = cit.unify(flat, None)
    assert [c.id for c in cits] == [f"E{i}" for i in range(1, len(flat) + 1)]
    assert all("graph admission" not in c.label for c in cits)
    # ...and the only textual difference between the two renders is the two headers.
    added = [ln for ln in "\n".join(on[1]).splitlines() if ln not in "\n".join(off[1]).splitlines()]
    assert len(added) == 2 and all("graph admission" in ln for ln in added), added
    for texts in (["row-frost"], ["row-freight"], ["row-diesel"], ["row-seed"]):
        for t in texts:                                                      # every row still rendered once
            assert "\n".join(on[1]).count(t) == 1 and "\n".join(off[1]).count(t) == 1


# ══ D -- 30c: the invitation ═════════════════════════════════════════════════════════════════════════
def test_system_appends_the_invitation_before_the_contract_directive_tail():
    """The emphasis paragraph stays LAST (the D-RC Phase B law); the invitation lands just before it,
    beside the other threaded addenda. Default False -> byte-identical, on the default persona AND
    under an active contract."""
    assert an._system() == an._system(provenance=False)
    assert an._system(response_contract="ranking") == an._system(response_contract="ranking",
                                                                 provenance=False)
    plain = an._system(response_contract="ranking")
    with_prov = an._system(response_contract="ranking", provenance=True)
    assert an._SYSTEM_PROVENANCE not in plain and an._SYSTEM_PROVENANCE in with_prov
    tail = rc.directive("ranking")
    assert tail and with_prov.endswith(tail)                                 # the emphasis is still LAST
    assert with_prov.index(an._SYSTEM_PROVENANCE) < with_prov.rindex(tail)
    assert with_prov.replace(an._SYSTEM_PROVENANCE, "") == plain             # nothing else moved
    assert inspect.signature(an._system).parameters["provenance"].default is False


def test_the_invitation_invites_and_never_mandates():
    """THE ANTI-RULE-ENGINE COVENANT (30c), asserted on the text itself. A mandate would buy citations
    by compulsion and measure nothing about whether the structural channel is USEFUL -- which is the
    only question read (3) asks. Also <= 4 lines: it rides every escalated turn's cached prefix."""
    txt = an._SYSTEM_PROVENANCE
    assert txt.strip().count("\n") == 0                                      # ONE paragraph, no line list
    assert len(txt) < 700                                        # smaller than every other addendum
    low = txt.lower()
    assert "invited" in low and "never required" in low
    for mandate in ("must", "at least one", "always cite", "you have to", "required to"):
        assert mandate not in low, mandate
    assert "graph admission" in low                                          # names the marker it explains


# ══ E -- the threading, captured at the REAL seam ════════════════════════════════════════════════════
def _run_l2(monkeypatch, sg, *, mode_knobs=None):
    """Drive the real _answer_l2 with the walk replaced by a fixed subgraph and ground() a no-op, and
    capture the system prompt + the user payload the synthesis call actually received."""
    seen: dict = {}
    monkeypatch.setattr(pl, "grounded_subgraph", lambda q, gr, **kw: sg)
    monkeypatch.setattr(pl, "ground", lambda *a, **kw: None)

    def _call(system, user, *, model, tool, **kw):
        seen["system"], seen["user"], seen["model"] = system, user, model
        return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}
    kw = {"mode_knobs": mode_knobs} if mode_knobs else {}
    out = an.answer("why is arabica bid", graph=_prov_graph(), asof="2021-08-01", planner="l2",
                    call=_call, route_fn=lambda q, gg: ["arabica_coffee"], **kw)
    return out, seen


def _blob(user) -> str:
    """The user payload is either a string or the (stable, volatile) content-block list."""
    if isinstance(user, str):
        return user
    return "\n".join(str(b.get("text", b)) if isinstance(b, dict) else str(b) for b in user)


def test_esc_r_lights_both_halves_and_esc_lights_neither(monkeypatch):
    """THE BUNDLE IS ONE DECISION, read once from `provenance_prompt` and threaded to BOTH seams. esc
    (no reserve, no prompt) must be indistinguishable from deep here -- otherwise the A/B's single
    variable is not single."""
    _o, esc_r = _run_l2(monkeypatch, _prov_sg(), mode_knobs=rm.knobs(rm.ESC_R))
    assert an._SYSTEM_PROVENANCE in esc_r["system"]
    assert "graph admission: upstream ancestor of frost" in _blob(esc_r["user"])
    for name in (rm.ESC, rm.DEEP, rm.STANDARD):
        _o, other = _run_l2(monkeypatch, _prov_sg(), mode_knobs=rm.knobs(name))
        assert an._SYSTEM_PROVENANCE not in other["system"], name
        assert "graph admission" not in _blob(other["user"]), name
    _o, bare = _run_l2(monkeypatch, _prov_sg())                              # no knobs at all
    assert an._SYSTEM_PROVENANCE not in bare["system"]
    assert "graph admission" not in _blob(bare["user"])


def test_the_escalated_turn_writes_with_the_bundle_s_model(monkeypatch):
    """The synth seat and the render half are ONE bundle in serving too: the same knob dict that lights
    the provenance also seats opus, and the seat is visible at the synthesis call, not merely resolved."""
    _o, esc = _run_l2(monkeypatch, _prov_sg(), mode_knobs=rm.knobs(rm.ESC))
    assert esc["model"] == "claude-opus-5"
    _o, deep = _run_l2(monkeypatch, _prov_sg(), mode_knobs=rm.knobs(rm.DEEP))
    assert deep["model"] == an.SONNET


def test_the_one_hop_body_is_untouched_on_defaults(monkeypatch):
    """F14: the GRAPHRAG_PLANNER=onehop rollback lane keeps its byte-identical persona call -- it passes
    no `provenance`, so the default False governs and the rollback cannot silently change the prompt."""
    seen: list = []

    def _call(system, user, *, model, tool, **kw):
        seen.append(system)
        return {"tldr": "x", "mechanism": "y", "diagram_mermaid": "", "sources": []}
    an.answer("why is corn bid", graph=_graph(), asof="2024-06-01", call=_call, retrieve=_retrieve,
              mode_knobs=rm.knobs(rm.ESC_R))
    assert seen and an._SYSTEM_PROVENANCE not in seen[-1]
