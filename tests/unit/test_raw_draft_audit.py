"""A4 -- the RAW pre-sanitize draft snapshot (NUMBERS_FIRING_PLAN section 3, wave A).

Every register red is counted BEFORE the verifier runs, because counting after "would read 0 forever"
(answer.py._count_banned_mood). Only the COUNTS survived into the trace, so a non-zero red named a RULE and
never the sentence -- strip_audit was null on every W5 row and the reds were unauditable. This adds the other
half: the counts say how many, the snapshot says which.

There is NO single choke point. verify_citations is called from `_answer_l2` AND from `answer` (the documented
GRAPHRAG_PLANNER=onehop rollback lane), and run_numbers_only computes its own raw counters on a third draft it
then discards. All THREE sites are pinned here -- snapshotting only the L2 body would leave a silent hole in
the audit exactly on the path a planner rollback puts every turn on.

No S3/Athena/LLM spend: synthesis and the numbers agent are injected fakes.
"""
from __future__ import annotations

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import evidence as ev
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import verify as vf

# A draft the sanitizer WILL rewrite: the mood words are exactly the reds whose sentence A4 exists to recover.
RAW_TLDR = "Arabica is bullish after the frost [1]."
RAW_MECH = "A bearish offset is possible; still bullish overall [1]."

# RE-PINNED 2026-08-16 (suite-debt sweep). CYCLE-9 (2026-08-08) FIX 4 -- "the missing attribution
# boundary", commit d7e9db86 ("fix(cycle9): repair becomes an allowlist -- grouped-handle parsing,
# [E] orphan prune, attributable mutations") -- added TWO more captures on the SAME
# GRAPHRAG_STRIP_AUDIT flag and the same two short prose fields, on BOTH synthesis bodies
# (answer.py:2800/2825 in _answer_l2 and :8932/8937 in the onehop rollback lane). The A4 snapshot's
# shape is therefore these SIX keys, not two.
#
# WHY THIS FILE WENT RED AND THE OTHER DID NOT: d7e9db86 pinned the new keys in the companion file it
# shipped (tests/unit/test_cycle9_repair_allowlist.py:398-404, :618-624) and never re-pinned this
# one. So the keys were always covered; only this file's shape assertion was stale.
#
# The four boundary keys are EXEMPT from raw_draft_snapshot's falsy drop (answer.py:575-576
# `if v or k.startswith(("preverify_", "postverify_"))`), so they cannot fall out of the set when a
# field is empty -- which is why membership here is unconditional.
#
# NOTE what is deliberately NOT asserted as a whole-dict equality below: `postverify_mechanism` is
# NOT equal to RAW_MECH (verify strips the trailing citation), and that DELTA is the entire point of
# FIX 4. Freezing it into an instrumentation test would both misstate the contract and break this
# file on every future verify change. The set closure is kept exact; the values are pinned only
# where the contract says nothing may change.
A4_KEYS = {"tldr", "mechanism",
           "preverify_tldr", "preverify_mechanism",
           "postverify_tldr", "postverify_mechanism"}


def _graph() -> g.CausalGraph:
    coffee = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica", "KC"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost kills trees")])
    return g.CausalGraph({"arabica_coffee": coffee}, silver=set())


def _retrieve(q, node, *, k, asof=None, near=None):
    return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{node}",
             "text": "July frost hit Sul de Minas"}]


def _synth(system, user, *, model, tool, **_kw):
    return {"tldr": RAW_TLDR, "mechanism": RAW_MECH, "diagram_mermaid": "",
            "sources": [{"ref": 1, "source": "GAIN", "date": "2021-07-20", "note": "frost"}]}


def _audit(monkeypatch, val):
    if val is None:
        monkeypatch.delenv("GRAPHRAG_STRIP_AUDIT", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", val)


# -- the helper: ONE flag, read exactly the way verify.py reads it ------------------------------------
def test_snapshot_absent_when_flag_unset(monkeypatch):
    _audit(monkeypatch, None)
    assert an.raw_draft_snapshot(tldr=RAW_TLDR, mechanism=RAW_MECH) is None


def test_snapshot_absent_when_flag_off(monkeypatch):
    _audit(monkeypatch, "off")
    assert an.raw_draft_snapshot(tldr=RAW_TLDR, mechanism=RAW_MECH) is None


def test_snapshot_captures_the_named_fields_verbatim(monkeypatch):
    _audit(monkeypatch, "on")
    snap = an.raw_draft_snapshot(tldr=RAW_TLDR, mechanism=RAW_MECH)
    assert snap == {"tldr": RAW_TLDR, "mechanism": RAW_MECH}     # verbatim: no truncation, no cleaning


def test_snapshot_is_none_when_every_field_is_empty(monkeypatch):
    """A blank draft yields ABSENT, not a dict of empty strings -- the key means 'a draft was captured'."""
    _audit(monkeypatch, "on")
    assert an.raw_draft_snapshot(tldr="", mechanism=None) is None


def test_snapshot_names_its_own_fields(monkeypatch):
    """The two lanes' drafts differ in shape (reasoner: tldr+mechanism; numbers agent: one prose block), so
    the caller names the fields rather than the helper assuming a schema."""
    _audit(monkeypatch, "on")
    assert an.raw_draft_snapshot(answer="plain agent prose") == {"answer": "plain agent prose"}


@pytest.mark.parametrize("val", ["on", "1", "true", "ON", "garbage", ""])
def test_snapshot_flag_read_matches_verify_strip_audit_exactly(monkeypatch, val):
    """ONE flag, ONE meaning ('this run is being audited'): the helper's read must agree with verify.py's
    on EVERY value, or a run could carry stripped-sentence audit and no draft (or the reverse)."""
    _audit(monkeypatch, val)
    import os
    verify_on = os.environ.get("GRAPHRAG_STRIP_AUDIT", "off") != "off"
    assert (an.raw_draft_snapshot(tldr="x") is not None) is verify_on
    assert verify_on is True                                     # every value here but 'off'/unset audits


# -- site 1: the L2 synthesis body --------------------------------------------------------------------
def _l2(monkeypatch):
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[1.0] for _ in texts])
    return an.answer("trace how a coffee frost spikes price", graph=_graph(), planner="l2",
                     asof="2021-08-01", retrieve=_retrieve, call=_synth,
                     route_fn=lambda q, gr: ["arabica_coffee"])


def test_l2_path_snapshots_the_raw_draft(monkeypatch):
    _audit(monkeypatch, "on")
    out = _l2(monkeypatch)
    draft = out["trace"]["raw_draft"]
    assert set(draft) == A4_KEYS
    # verbatim: no truncation, no cleaning
    assert draft["tldr"] == RAW_TLDR and draft["mechanism"] == RAW_MECH
    # FIX 4's first interval contract (answer.py:2818): raw -> preverify, nothing may change.
    assert draft["preverify_tldr"] == RAW_TLDR and draft["preverify_mechanism"] == RAW_MECH
    # the counter and the sentence agree: the trace says HOW MANY, the draft says WHICH
    assert out["trace"]["banned_mood_words"] == 3
    assert "bullish" in draft["tldr"] and "bearish" in draft["mechanism"]


def test_l2_path_draft_survives_a_render_the_sanitizer_rewrote(monkeypatch):
    """The point of the snapshot: the rendered answer no longer contains the words the counter charged."""
    _audit(monkeypatch, "on")
    out = _l2(monkeypatch)
    assert "bullish" not in out["answer"] and "bearish" not in out["answer"]
    assert "bullish" in out["trace"]["raw_draft"]["tldr"]


def test_l2_path_absent_when_not_audited(monkeypatch):
    _audit(monkeypatch, None)
    out = _l2(monkeypatch)
    assert "raw_draft" not in out["trace"]                       # absent, not null -> trace byte-identical
    assert out["trace"]["banned_mood_words"] == 3                # the counters are unconditional, as before


# -- site 2: the one-hop rollback lane (planner != 'l2') ----------------------------------------------
def _onehop():
    return an.answer("arabica coffee frost", graph=_graph(), retrieve=_retrieve, call=_synth)


def test_onehop_path_snapshots_the_raw_draft(monkeypatch):
    """GRAPHRAG_PLANNER=onehop is a documented rollback. A snapshot only in _answer_l2 would leave the whole
    fleet unauditable the moment that rollback is used."""
    _audit(monkeypatch, "on")
    out = _onehop()
    draft = out["trace"]["raw_draft"]
    assert set(draft) == A4_KEYS
    assert draft["tldr"] == RAW_TLDR and draft["mechanism"] == RAW_MECH
    assert draft["preverify_tldr"] == RAW_TLDR and draft["preverify_mechanism"] == RAW_MECH
    assert "planner" not in out["trace"]                         # this really is the non-L2 body


def test_onehop_path_absent_when_not_audited(monkeypatch):
    _audit(monkeypatch, None)
    assert "raw_draft" not in _onehop()["trace"]


def test_both_answer_paths_carry_the_snapshot(monkeypatch):
    """The plan's acceptance check, stated directly: BOTH synthesis paths, not only _answer_l2."""
    _audit(monkeypatch, "on")
    assert _l2(monkeypatch)["trace"]["raw_draft"] == _onehop()["trace"]["raw_draft"]


# -- site 3: the numbers_only mirror (its own raw counters, its own discarded draft) -------------------
class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        return self.outer.q.pop(0)


class FakeAnthropic:
    def __init__(self, q):
        self.q = list(q)
        self.messages = _Msgs(self)


def _ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


AGENT_RAW = "Stocks look bullish at 31,400,000 MT."


def _numbers_client():
    return FakeAnthropic([
        _ns(content=[_ns(type="tool_use", name="lookup_number", id="t1",
                         input={"table": "silver_psd", "metric": "ending_stocks_mt",
                                "commodity": "corn_cbot", "period": "2023"})], stop_reason="tool_use"),
        _ns(content=[_ns(type="text", text=AGENT_RAW)], stop_reason="end_turn")])


def _query_fn(sql):
    return [{"value": "31400000", "knowledge_date": "2024-02-08"}]


def test_numbers_only_snapshots_the_agent_draft(monkeypatch):
    _audit(monkeypatch, "on")
    res = orch.run_numbers_only("us corn ending stocks", "2024-06-01",
                                client=_numbers_client(), query_fn=_query_fn)
    assert res["trace"]["raw_draft"] == {"answer": AGENT_RAW}
    assert "bullish" in res["trace"]["raw_draft"]["answer"]
    assert "bullish" not in res["answer"]                        # sanitize destroyed it on the way out


def test_numbers_only_absent_when_not_audited(monkeypatch):
    _audit(monkeypatch, None)
    res = orch.run_numbers_only("us corn ending stocks", "2024-06-01",
                                client=_numbers_client(), query_fn=_query_fn)
    assert "raw_draft" not in res["trace"]
    assert res["trace"]["banned_valuation_words"] is not None    # the raw counters are unchanged


# -- the pairing A4 exists to restore: strip_audit AND the draft come from the same flag --------------
def test_strip_audit_and_raw_draft_turn_on_together(monkeypatch):
    """W5's rows carried strip_audit=None because the flag was never set. One flag now yields BOTH the
    stripped sentences (verify) and the draft they were stripped from (answer)."""
    _audit(monkeypatch, "on")
    rep = vf.verify_citations({"tldr": "x", "mechanism": "y"}, [], None)
    assert isinstance(rep.get("strip_audit"), list)              # verify's half is armed
    assert an.raw_draft_snapshot(tldr="x") is not None           # A4's half is armed by the same value


# -- A4 half 3 (F9): the snapshot must reach the ARTIFACT, or the acceptance check is unreachable -----
# eval._per_answer_record is the SINGLE source of truth for both the incremental partial JSONL and
# _baseline_json's per_answer entries, and it is a hard WHITELIST: a trace key that is not named there
# reaches no artifact at all. A4's acceptance check is "for every non-zero raw red, the exact offending
# sentence", and it was unmeetable from the baseline even with GRAPHRAG_STRIP_AUDIT on.
def test_the_baseline_record_persists_the_raw_draft_beside_strip_audit():
    from leviathan.graphrag import eval as gev
    out = {"answer": "a", "trace": {"raw_draft": {"tldr": "raw t", "mechanism": "raw m"},
                                    "citation_verifier": {"stripped": 1, "strip_audit": [{"rule": "r"}]}}}
    rec = gev._per_answer_record({"q": {"id": "r1"}, "out": out, "rubric": {}}, "single")
    assert rec["raw_draft"] == {"tldr": "raw t", "mechanism": "raw m"}
    assert rec["strip_audit"] == [{"rule": "r"}]                 # the pairing, in one record


def test_the_baseline_record_carries_none_on_an_unaudited_row():
    """Absent-when-off stays absent-when-off: an unaudited run records None, never a fabricated draft."""
    from leviathan.graphrag import eval as gev
    rec = gev._per_answer_record({"q": {"id": "r2"}, "out": {"answer": "a"}, "rubric": {}}, "single")
    assert rec["raw_draft"] is None


# =====================================================================================================
# A4b -- the SANITIZE-INPUT snapshot: what each cleaning pass was GIVEN
#
# A4 recovered what the model WROTE. That was not enough to adjudicate the 2026-08-04 R6 report's three
# `banned_valuation` reds, because `register.count_valuation_words` over all 15 RENDERED answers was 0
# and nothing in the artifact said which pass ate the sentence. The render path runs reg.sanitize TWICE
# (per-field in `_humanize_structured`, then on the assembled body at the render seam), so the input to
# EACH pass is the evidence that attributes a scar to it.
# =====================================================================================================

# A Lane-B valuation slip: a windowed adjective ("expensive") in a sentence carrying a window noun
# ("spread"). Counted RAW by `answer._count_banned_valuation`; destroyed before the reader sees it.
VAL_TLDR = "Frost cut the Sul de Minas crop [1]."
VAL_MECH = ("A July frost hit Sul de Minas [1]. The spread makes Brazilian coffee expensive versus "
            "Vietnamese robusta [1]. Arrivals slowed into August [1].")


def _body(monkeypatch, val):
    if val is None:
        monkeypatch.delenv("GRAPHRAG_DRAFT_BODY_AUDIT", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_DRAFT_BODY_AUDIT", val)


def _val_synth(system, user, *, model, tool, **_kw):
    return {"tldr": VAL_TLDR, "mechanism": VAL_MECH, "diagram_mermaid": "",
            "sources": [{"ref": 1, "source": "GAIN", "date": "2021-07-20", "note": "frost"}]}


def _l2_val(monkeypatch):
    monkeypatch.setattr(ev, "embed", lambda texts, **k: [[1.0] for _ in texts])
    return an.answer("trace how a coffee frost spikes price", graph=_graph(), planner="l2",
                     asof="2021-08-01", retrieve=_retrieve, call=_val_synth,
                     route_fn=lambda q, gr: ["arabica_coffee"])


# -- the helper: its OWN flag, default off ------------------------------------------------------------
def test_sanitize_input_snapshot_absent_when_flag_unset(monkeypatch):
    _body(monkeypatch, None)
    assert an.sanitize_input_snapshot(body_pre_sanitize="rendered body") is None


@pytest.mark.parametrize("val", ["off", "0", "false", "", "garbage"])
def test_sanitize_input_snapshot_is_fail_closed(monkeypatch, val):
    """The house `_chain_on` spelling: ONLY on/1/true arms it. Anything else -- including a typo -- is
    OFF, because this field is whole rendered bodies and the failure mode of a permissive read is a
    silently fattened payload on every live answer."""
    _body(monkeypatch, val)
    assert an.sanitize_input_snapshot(body_pre_sanitize="rendered body") is None


@pytest.mark.parametrize("val", ["on", "1", "true", "ON", "  True  "])
def test_sanitize_input_snapshot_captures_verbatim_when_on(monkeypatch, val):
    _body(monkeypatch, val)
    assert an.sanitize_input_snapshot(body_pre_sanitize="rendered body") == {"body_pre_sanitize": "rendered body"}


def test_sanitize_input_snapshot_is_none_when_every_part_is_empty(monkeypatch):
    _body(monkeypatch, "on")
    assert an.sanitize_input_snapshot(body_pre_sanitize="", verified_tldr=None) is None


def test_sanitize_input_snapshot_does_not_ride_the_strip_audit_flag(monkeypatch):
    """The two flags are INDEPENDENT and this is the containment. GRAPHRAG_STRIP_AUDIT is ON in serving
    (leviathan-dev-serving:73 -- measured 2026-08-04), so a shared switch would have put a full rendered
    body on the wire of every live /v1/respond."""
    _audit(monkeypatch, "on")
    _body(monkeypatch, None)
    assert an.raw_draft_snapshot(tldr=RAW_TLDR) is not None       # A4 armed
    assert an.sanitize_input_snapshot(body_pre_sanitize="b") is None   # A4b NOT armed


# -- _fold_draft: absent-when-off survives the merge ---------------------------------------------------
def test_fold_draft_keeps_the_key_absent_when_both_halves_are_off():
    assert an._fold_draft(None, None) is None


def test_fold_draft_merges_without_mutating_the_earlier_snapshot():
    early = {"tldr": "t"}
    out = an._fold_draft(early, {"body_pre_sanitize": "b"})
    assert out == {"tldr": "t", "body_pre_sanitize": "b"}
    assert early == {"tldr": "t"}                                # a NEW dict, the caller's is untouched


def test_fold_draft_returns_the_earlier_snapshot_when_the_later_part_is_off():
    assert an._fold_draft({"tldr": "t"}, None) == {"tldr": "t"}


def test_fold_draft_yields_a_dict_when_only_the_later_part_is_on():
    assert an._fold_draft(None, {"body_pre_sanitize": "b"}) == {"body_pre_sanitize": "b"}


# -- the seams, on BOTH synthesis paths ----------------------------------------------------------------
def test_l2_path_carries_both_sanitize_inputs(monkeypatch):
    _audit(monkeypatch, "on")
    _body(monkeypatch, "on")
    draft = _l2_val(monkeypatch)["trace"]["raw_draft"]
    assert set(draft) == A4_KEYS | {"verified_tldr", "verified_mechanism", "body_pre_sanitize"}
    assert draft["body_pre_sanitize"].startswith("**TL;DR.**")   # the ASSEMBLED body, not a field


def test_onehop_path_carries_both_sanitize_inputs(monkeypatch):
    """The GRAPHRAG_PLANNER=onehop rollback lane gets the identical seams -- an audit that goes blind on
    the rollback path is an audit that goes blind exactly when it is needed."""
    _audit(monkeypatch, "on")
    _body(monkeypatch, "on")
    draft = an.answer("arabica coffee frost", graph=_graph(), retrieve=_retrieve,
                      call=_val_synth)["trace"]["raw_draft"]
    assert set(draft) == A4_KEYS | {"verified_tldr", "verified_mechanism", "body_pre_sanitize"}


def test_the_body_snapshot_is_the_exact_string_the_sanitizer_consumed(monkeypatch):
    """`body_pre_sanitize` must be the ASSEMBLED PAGE at the render seam, not a re-render: reconstructing
    the seam from it must reproduce the served answer byte for byte, or the diff the adjudicator reads is
    fiction.

    CYCLE-10-AMEND (2026-08-08), REVIEW MAJOR 1+2: the seam is now `reg.sanitize(prose) + footer`. The
    validated `## Sources` block is assembled from rows already cleared through the register at ROW scope
    and is appended AFTER the body pass, because the body pass read a row's own `[10]` marker as an
    unbacked price level (`register._CIT_HANDLE` does not match a bare `[10]`, `register._level_tokens`
    does) and deleted every row from ref 10 up on an outlook turn. The snapshot still carries the WHOLE
    page -- the judge and the numeral adjudicators read it as the answer -- so the identity is stated on
    its two halves: the prose half must still sanitize to the answer's prose half, and the footer half
    must cross the seam UNCHANGED. With no validated footer the partition is empty and this is the
    original assertion, unchanged."""
    from leviathan.graphrag import register as reg
    _audit(monkeypatch, "on")
    _body(monkeypatch, "on")
    out = _l2_val(monkeypatch)
    pre = out["trace"]["raw_draft"]["body_pre_sanitize"]
    prose, sep, footer = pre.partition("\n\n## Sources\n")
    assert reg.sanitize(prose) + sep + footer == out["answer"]


# -- the regression this exists to close: attribute a banned_valuation red to a PASS ------------------
def test_the_snapshot_attributes_a_valuation_slip_the_rendered_answer_reads_zero_on(monkeypatch):
    """R6 finding F5, reproduced end to end. The pin charges a RAW red; the reader's answer scores 0; the
    two intermediate captures say which pass closed the gap and hand over the exact sentence."""
    from leviathan.graphrag import register as reg
    _audit(monkeypatch, "on")
    _body(monkeypatch, "on")
    out = _l2_val(monkeypatch)
    draft = out["trace"]["raw_draft"]
    assert out["trace"]["banned_valuation_words"] == 1           # the counter: HOW MANY
    assert reg.count_valuation_words(out["answer"]) == 0         # the reader's surface: nothing to see
    # WHICH: the slip is still countable on the raw draft and on the humanize pass's input ...
    assert reg.count_valuation_words(draft["mechanism"]) == 1
    assert reg.count_valuation_words(draft["verified_mechanism"]) == 1
    assert "expensive" in draft["verified_mechanism"]
    # ... and gone from the render seam's input, which localises the kill to _humanize_structured.
    assert reg.count_valuation_words(draft["body_pre_sanitize"]) == 0
    assert "expensive" not in draft["body_pre_sanitize"]


def test_the_body_seam_still_sees_leaks_that_live_outside_tldr_and_mechanism(monkeypatch):
    """Seam 2 is not redundant: the render-seam pass is the ONLY one that sees the cited-sources block and
    the numbers footer, which the raw counters (tldr+mechanism only) never scan."""
    _audit(monkeypatch, "on")
    _body(monkeypatch, "on")
    body = _l2_val(monkeypatch)["trace"]["raw_draft"]["body_pre_sanitize"]
    assert "## Sources" in body or "Sources" in body


# -- containment: the serving payload is untouched unless a run opts in -------------------------------
def test_serving_shape_is_unchanged_when_only_strip_audit_is_on(monkeypatch):
    """Serving rev 73's exact env: GRAPHRAG_STRIP_AUDIT=on, no body flag. The trace must carry the A4
    draft and NOTHING new -- this is the byte-for-byte no-op that lets A4b ship without a serving cost."""
    _audit(monkeypatch, "on")
    _body(monkeypatch, None)
    draft = _l2_val(monkeypatch)["trace"]["raw_draft"]
    assert set(draft) == A4_KEYS      # exactly A4 + the cycle-9 boundaries; nothing from A4b


def test_nothing_is_snapshotted_when_neither_flag_is_on(monkeypatch):
    _audit(monkeypatch, None)
    _body(monkeypatch, None)
    assert "raw_draft" not in _l2_val(monkeypatch)["trace"]      # absent, not null


def test_the_body_flag_alone_still_yields_a_draft(monkeypatch):
    """The flags are independent in BOTH directions: a body-only run is a legal audit configuration and
    must not silently produce nothing."""
    _audit(monkeypatch, None)
    _body(monkeypatch, "on")
    draft = _l2_val(monkeypatch)["trace"]["raw_draft"]
    assert set(draft) == {"verified_tldr", "verified_mechanism", "body_pre_sanitize"}


def test_the_served_answer_is_byte_identical_with_the_flag_on_and_off(monkeypatch):
    """A diagnostic that changes the product is not a diagnostic. The two-branch render refactor that
    hoisted `_pre_sanitize` out of the sanitize call is pinned here, not just asserted in review."""
    _audit(monkeypatch, "on")
    _body(monkeypatch, None)
    off = _l2_val(monkeypatch)
    _body(monkeypatch, "on")
    on = _l2_val(monkeypatch)
    assert on["answer"] == off["answer"]
    assert on["structured"] == off["structured"]


# -- and it must REACH the artifact (the F9 lesson: eval's projection is a hard whitelist) ------------
def test_the_sanitize_inputs_reach_the_eval_record_inside_raw_draft(monkeypatch):
    """The parts land INSIDE `raw_draft` deliberately. `eval._per_answer_record` names that key already,
    so the whole dict rides through; a NEW top-level trace key would have reached no artifact at all."""
    from leviathan.graphrag import eval as gev
    _audit(monkeypatch, "on")
    _body(monkeypatch, "on")
    out = _l2_val(monkeypatch)
    rec = gev._per_answer_record({"q": {"id": "r3"}, "out": out, "rubric": {}}, "single")
    assert rec["raw_draft"]["body_pre_sanitize"] == out["trace"]["raw_draft"]["body_pre_sanitize"]
    assert rec["raw_draft"]["verified_mechanism"] == out["trace"]["raw_draft"]["verified_mechanism"]
