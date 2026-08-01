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
    assert draft == {"tldr": RAW_TLDR, "mechanism": RAW_MECH}
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
    assert out["trace"]["raw_draft"] == {"tldr": RAW_TLDR, "mechanism": RAW_MECH}
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
