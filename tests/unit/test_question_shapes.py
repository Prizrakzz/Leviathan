"""C2 -- the question-shape -> required-metric table and the honest decline line (D3, 2026-08-01).

WHAT THIS FILE IS FOR. C2's acceptance check is a NEGATIVE one, and it is the reason the item was gated on
a decision at all: "a wrong decline ('we looked and found nothing' where the data exists) must be
structurally impossible". D3 says the same thing from the other side -- if the three-condition guard cannot
be made airtight IN CODE rather than by convention, decline the decline line.

So the load-bearing test here is not that the line renders. It is
`test_no_status_but_no_rows_can_ever_emit_a_decline`, which walks EVERY shape x EVERY requirement x EVERY
status the executor can write and asserts the preface stays empty for all of them but one. The rest of the
file exists to keep that test honest: the status vocabulary is read off `agent._exec`'s own taxonomy, the
shapes are read off the live config, and nothing below restates either.
"""
from __future__ import annotations

import types

import pytest

from leviathan.graphrag import config_check as cc
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers.registry import load_registry

# The executor's whole status vocabulary (agent._exec). Kept as a literal HERE on purpose: this is the one
# place that should fail loudly when a new status appears, because a status nobody classified falls through
# `_STATUS_STATE.get(status, "error")` to 'error' -- safe, but silently unmeasured.
ALL_STATUSES = ("ok", "no_rows", "not_known", "declined", "error")


_SENTINEL = object()
ASOF = "2026-07-21"


def _call(table, metric, status, rows=None, commodity=_SENTINEL):
    """One executed call. F4: a slug-keyed table (commodity_col == leviathan_slug -- silver_cot,
    silver_psd) gets a RESOLVING contract slug by default, because an empty read under a key the table
    cannot serve is no longer evidence of absence and is downgraded to SHAPE_SCOPE_UNRESOLVED. Pass
    commodity= explicitly to exercise the mis-scoped case."""
    if commodity is _SENTINEL:
        commodity = "corn_cbot" if table in A._slug_keyed_tables() else None
    q = {"table": table, "metric": metric, "asof": ASOF}
    if commodity:
        q["commodity"] = commodity
    return {"query": q, "rows": rows or [], "status": status}


def _row():
    return [{"value": "118432"}]


def _live_requirements():
    """(shape, requirement) for every LIVE requirement in the table -- deferred rows are already dropped."""
    return [(shape, req) for shape, spec in sorted(A.load_shape_table().items())
            for req in (spec.get("requires") or [])]


# ==================================================================================================
# Detection -- the sixth "detect the shape ONCE, up front" scope.
# ==================================================================================================
@pytest.mark.parametrize("question,shape", [
    ("what is managed money doing in corn right now", "positioning"),
    ("are the funds net long soybeans", "positioning"),
    ("what does the latest commitments of traders report show", "positioning"),
    ("how does El Nino change the Brazilian coffee crop", "seasonality"),
    ("is the drought in Argentina unusual for this time of year", "seasonality"),
    ("is the export programme running ahead of last year", "pace"),
    ("what are weekly export sales for corn", "pace"),
    ("how high can wheat go from here", "outlook"),
    ("what does the balance sheet say about stocks-to-use", "outlook"),
])
def test_question_shape_scope_detects_the_named_shapes(question, shape):
    assert A.question_shape_scope(question) == shape


@pytest.mark.parametrize("question", [
    # A historical BALANCE-SHEET level ask. It is here because the first draft of the outlook pattern
    # fired on it (measured 2026-08-01): the bare nouns 'ending stocks' / 'carryout' / 'balance sheet'
    # name a quantity the ordinary lookup path serves, not a forward ask, and requiring a stocks-to-use
    # anchor of them would record a dispatch miss that never happened.
    "what were Argentina corn ending stocks in 2019",
    "what was the corn carryout that year",
    "tell me about the palm oil supply chain",
    "who are the largest soybean crushers in Brazil",
    "",
])
def test_shapeless_questions_fail_toward_none(question):
    """Ambiguity fails toward None, the discipline every other scope in agent.py already keeps: an
    unmatched turn must be byte-identical to pre-C2, and it can only be that if nothing matched."""
    assert A.question_shape_scope(question) is None


def test_both_spellings_of_el_nino_are_detected():
    """The ENSO names arrive both ways -- the FE posts NFC, a desk analyst types the ASCII form -- so the
    pattern carries the n-tilde as a \\u escape. Built here with the same escape rather than a literal:
    this repo's source stays ASCII (the Windows console is cp1252)."""
    n_tilde = chr(0xF1)
    assert A.question_shape_scope(f"how does El Ni{n_tilde}o change the Brazilian crop") == "seasonality"
    assert A.question_shape_scope(f"is La Ni{n_tilde}a still in play") == "seasonality"


def test_the_more_specific_shape_wins():
    """One shape per turn, first match in _SHAPE_PATTERNS order. A positioning ask that also says
    'outlook' requires a positioning read -- the vocabulary that names a metric is the one that decides."""
    assert A.question_shape_scope("what is the outlook -- is managed money net long corn?") == "positioning"
    assert A.question_shape_scope("what is the seasonal outlook for the Brazilian crop") == "seasonality"


# ==================================================================================================
# The table itself.
# ==================================================================================================
def test_the_deferred_spot_anchor_is_inert():
    """R4 is UNTOUCHED by D1, so the outlook shape's pink-sheet spot anchor is parked, not live. The
    `deferred` idiom is cascade_map's (load_map drops a deferred row before the seam ever sees it), and
    the point is that a requirement can be RECORDED without being armed."""
    outlook = A.load_shape_table()["outlook"]
    ids = [r["id"] for r in outlook["requires"]]
    assert "su_ratio" in ids
    assert "spot_anchor" not in ids, "the R4-fenced spot anchor is live -- D1 decided positioning, not spot"
    for _shape, req in _live_requirements():
        assert not any(t in cc.PRICE_TABLES for t in req["tables"]), \
            "a live requirement reaches an R4-fenced price table"


def test_the_positioning_requirement_declares_its_doctrine():
    """R9 as amended admits positioning as a past-tense CONTEXT read. The row must say so in the config,
    so the fence is a reviewable diff rather than a remembered conversation."""
    req = A.load_shape_table()["positioning"]["requires"][0]
    assert req["tables"] == ["silver_cot"] and req["doctrine"] == "r9_context"
    assert "open_interest" not in req["metrics"], \
        "open interest is a market-wide figure -- it would satisfy a managed-money requirement it "\
        "does not answer"


def test_the_config_lint_passes_on_the_shipped_table():
    """The whole of check_question_shapes -- coverage, realizability, doctrine, the three-condition bind
    and the register census -- against the table as shipped."""
    assert cc.check_question_shapes() == []


# ==================================================================================================
# Requirement states -- the four miss states (section 2.3), made readable.
# ==================================================================================================
def test_states_cover_the_miss_taxonomy():
    req = A.load_shape_table()["positioning"]["requires"][0]
    assert A._shape_requirement_state(req, []) == "not_attempted"          # 2.3 #1, NEVER FETCHED
    assert A._shape_requirement_state(req, [_call("silver_cot", "mm_net", "ok", _row())]) == "served"
    assert A._shape_requirement_state(req, [_call("silver_cot", "mm_net", "no_rows")]) == "empty"
    assert A._shape_requirement_state(req, [_call("silver_cot", "mm_net", "not_known")]) == "not_known"
    assert A._shape_requirement_state(req, [_call("silver_cot", "mm_net", "declined")]) == "declined"


def test_a_malformed_call_reads_as_an_attempt_at_the_table():
    """Finding 2.4(b): an errored call carries the model's RAW tool input as its query, so the metric key
    can be missing entirely (`silver_cot.?=ERROR`). Matching on metric alone would read that as 'never
    attempted' and hide the class that is 21 of 24 calls on silver_futures_prices."""
    req = A.load_shape_table()["positioning"]["requires"][0]
    malformed = {"query": {"table": "silver_cot"}, "rows": [], "status": "error", "error": "boom"}
    assert A._shape_requirement_state(req, [malformed]) == "error"


def test_a_different_metric_on_the_same_table_is_not_this_requirement():
    """An open-interest read is a real silver_cot lookup and is none of the managed-money requirement's
    business: it neither satisfies it nor declines it."""
    req = A.load_shape_table()["positioning"]["requires"][0]
    assert A._shape_requirement_state(req, [_call("silver_cot", "open_interest", "ok", _row())]) \
        == "not_attempted"


def test_one_served_row_outranks_an_empty_read_elsewhere():
    """PRECEDENCE, and it is the anti-contradiction rule: a turn that fetched the metric twice and got a
    figure once must never carry a line saying the record holds nothing."""
    req = A.load_shape_table()["positioning"]["requires"][0]
    calls = [_call("silver_cot", "mm_net", "no_rows"),
             _call("silver_cot", "mm_net_z_3yr", "ok", _row())]
    assert A._shape_requirement_state(req, calls) == "served"
    assert A.shape_decline("positioning", calls)[0] == ""


# ==================================================================================================
# THE ACCEPTANCE CHECK -- a wrong decline must be structurally impossible.
# ==================================================================================================
@pytest.mark.parametrize("shape,req", _live_requirements(), ids=lambda x: x if isinstance(x, str) else x["id"])
@pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s != "no_rows"])
def test_no_status_but_no_rows_can_ever_emit_a_decline(shape, req, status):
    """C2's acceptance check, executed exhaustively rather than argued. Every shape x every requirement x
    every executor status but one: the preface stays empty.

    The two that matter most are named, because each is a DIFFERENT wrong claim:
      * 'not_known' -- the vintage tables' empty result, which agent._exec assigns without distinguishing
        "not published at the as-of" from "scope mismatch". Declining there asserts an absence the
        executor never recorded.
      * 'error' -- a malformed or failed lookup. Declining there narrates an outage as data absence,
        which is the most expensive wrong decline of the set: it is indistinguishable, to the reader,
        from a real hole in the record."""
    for metric in req["metrics"]:
        for table in req["tables"]:
            calls = [_call(table, metric, status, _row() if status == "ok" else [])]
            preface, declined, _states = A.shape_decline(shape, calls)
            assert (preface, declined) == ("", []), (
                f"status {status!r} on {table}.{metric} produced a decline for shape {shape!r}: "
                f"{preface!r} -- only a recorded 'no_rows' may")


@pytest.mark.parametrize("shape,req", _live_requirements(), ids=lambda x: x if isinstance(x, str) else x["id"])
def test_the_recorded_empty_fetch_is_the_only_door(shape, req):
    """The positive half: with a recorded 'no_rows' the line DOES render, and it names this requirement's
    subject. Without the positive case the test above would pass on a decline that never fires at all."""
    calls = [_call(req["tables"][0], req["metrics"][0], "no_rows")]
    preface, declined, states = A.shape_decline(shape, calls)
    assert declined == [req["id"]] and states[req["id"]] == "empty"
    assert preface.startswith(A.SHAPE_DECLINE_LEAD) and req["subject"] in preface
    assert preface.endswith("\n\n")


# ==================================================================================================
# F4 -- THE MIS-SCOPED EMPTY READ. The decline claimed something about THE RECORD on the strength of a
# fetch that only proved THE MODEL'S QUERY matched nothing. _exec's own comment says 'no_rows' means
# "the query matched no data (filter/scope mismatch OR a lake gap)", and silver_cot's commodity_col is
# leviathan_slug -- tables.yaml:699 records in as many words that a bare base name matches ZERO rows.
# So a model that passed 'corn' instead of 'corn_cbot' got the reader told the record holds no
# managed-money reading while 12 slugs of weekly data sat in the table. D3's stated flip condition,
# reachable through the front door.
# ==================================================================================================
def test_a_mis_scoped_empty_read_is_not_a_decline():
    """corn vs corn_cbot, the acute case. The state is recorded (the miss is still observable) but no
    reader-facing sentence is emitted, because there is no absence to report."""
    calls = [_call("silver_cot", "mm_net", "no_rows", commodity="corn")]
    preface, declined, states = A.shape_decline("positioning", calls)
    assert (preface, declined) == ("", [])
    assert states["cot_managed_money"] == A.SHAPE_SCOPE_UNRESOLVED
    # ... and the correctly-keyed twin still declines, so this is a SCOPE rule and not a mute button.
    ok_preface, ok_declined, ok_states = A.shape_decline(
        "positioning", [_call("silver_cot", "mm_net", "no_rows", commodity="corn_cbot")])
    assert ok_declined == ["cot_managed_money"] and ok_states["cot_managed_money"] == "empty"
    assert ok_preface.startswith(A.SHAPE_DECLINE_LEAD)


def test_a_per_contract_table_read_with_no_contract_never_declines():
    """A silver_cot read with no commodity at all never scoped the ask, so its empty result is not a
    statement about the record either. Fail-closed means QUIET."""
    calls = [{"query": {"table": "silver_cot", "metric": "mm_net", "asof": ASOF}, "rows": [],
              "status": "no_rows"}]
    assert A.shape_decline("positioning", calls)[:2] == ("", [])


def test_scope_validation_only_claims_what_the_registry_can_back():
    """The validator is deliberately narrow: it fires ONLY on commodity_col == leviathan_slug, whose
    vocabulary (the evidence-hierarchy contract slugs) this module can enumerate offline. gold_weather_z
    keys on a different vocabulary, so a drought read is never downgraded -- a validator that guessed
    there would manufacture the false downgrade it exists to prevent."""
    assert "silver_cot" in A._slug_keyed_tables() and "silver_psd" in A._slug_keyed_tables()
    assert "gold_weather_z" not in A._slug_keyed_tables()
    assert A._scope_resolves("gold_weather_z", "corn") is True
    assert A._scope_resolves("silver_cot", "corn_cbot") is True
    assert A._scope_resolves("silver_cot", "corn") is False
    assert A._scope_resolves("", "corn_cbot") is False            # unknown table -> no decline


def test_the_decline_names_what_was_actually_queried():
    """F4(c). 'the record holds no X' bare is a claim about the record; naming the slug, the window and
    the as-of makes it a claim about a READ, which is the only claim the fetch supports."""
    calls = [_call("silver_cot", "mm_net", "no_rows", commodity="corn_cbot")]
    calls[0]["query"].update({"period_start": "2025-07-01", "period_end": "2026-07-31"})
    preface, _declined, _states = A.shape_decline("positioning", calls)
    assert "for CBOT corn over 2025-07-01..2026-07-31" in preface
    assert "for that window" not in preface                        # never the bare, unscoped form
    # the SLUG is rendered through display._contract_label, so reg.sanitize is a no-op on it and the
    # build-time 'survives sanitize' census means what it says.
    assert "corn_cbot" not in preface
    # with no window the as-of still names the read -- there is always something true to say
    bare = A.shape_decline("positioning", [_call("silver_cot", "mm_net", "no_rows")])[0]
    assert "for CBOT corn" in bare and "for that window" not in bare


def test_a_shape_that_never_matched_declines_nothing():
    """Condition (a): no shape, no requirement, no line -- whatever the calls did."""
    assert A.shape_decline(None, [_call("silver_cot", "mm_net", "no_rows")]) == ("", [], {})


def test_the_decline_state_is_reachable_from_exactly_one_status():
    """The build-time bind, restated as a unit so the failure is readable here as well as in the lint.
    If 'not_known' or 'error' ever mapped to the decline state, every test above would still pass on the
    shapes that happen not to use a vintage table -- this one would not."""
    origins = sorted(k for k, v in A._STATUS_STATE.items() if v == A.SHAPE_DECLINE_STATE)
    assert origins == ["no_rows"]
    assert set(A._STATUS_STATE) == set(ALL_STATUSES), \
        "agent._exec's status vocabulary moved -- classify the new status before it defaults to 'error'"


def test_the_vintage_lane_is_why_not_known_exists():
    """Not a tautology check: it records WHICH shapes are affected. silver_esr and silver_psd are vintage,
    so the pace and outlook shapes' empty reads come back 'not_known' and their decline line is
    unreachable in practice -- the record they leave is the observability half, not a reader-facing one.
    If either table's knowledge_semantics changes, this fails and the claim gets re-read."""
    tables = load_registry().tables
    assert tables["silver_esr"].knowledge_semantics == "vintage"
    assert tables["silver_psd"].knowledge_semantics == "vintage"
    assert tables["silver_cot"].knowledge_semantics == "data_date"
    assert tables["gold_weather_z"].knowledge_semantics == "year_month"


# ==================================================================================================
# The rendered sentence.
# ==================================================================================================
def test_the_decline_states_absence_and_never_effort():
    """D3(iii). The banned register is not a lexicon question -- it is the difference between a claim
    about the RECORD and a claim about what the tool did, and only the first is checkable."""
    line = A.shape_decline_line("positioning", ["managed-money positioning reading"])
    assert "the record holds no managed-money positioning reading" in line
    low = line.lower()
    for effort in ("we looked", "i looked", "we tried", "i tried", "could not find", "unable to find",
                   "search", "attempted"):
        assert effort not in low, f"the decline line narrates EFFORT ({effort!r}): {line!r}"


def test_multiple_empty_subjects_render_one_sentence():
    """The seasonality shape carries two requirements. Two empty reads must be ONE sentence about the
    record, not two stacked caveats -- the reader is told what is missing, once."""
    calls = [_call("silver_noaa_oni", "oni_anom", "no_rows"),
             _call("gold_weather_z", "drought_z", "no_rows")]
    preface, declined, _ = A.shape_decline("seasonality", calls)
    assert declined == ["oni_climate", "drought_z"]
    assert preface.count("One limitation to flag") == 1
    # F4: each subject carries its OWN scope clause -- two requirements are two different reads, and one
    # shared window clause would mis-state at least one of them.
    assert "no ENSO reading for " in preface and " and no drought-index reading for " in preface


def test_a_partially_served_shape_declines_only_the_empty_half():
    calls = [_call("silver_noaa_oni", "oni_anom", "ok", _row()),
             _call("gold_weather_z", "drought_z", "no_rows")]
    preface, declined, _ = A.shape_decline("seasonality", calls)
    assert declined == ["drought_z"] and "ENSO" not in preface


# ==================================================================================================
# End to end through answer_numbers.
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


_COT_CALL = {"table": "silver_cot", "metric": "mm_net", "commodity": "corn_cbot"}


def _run(question, rows, tool_input=None):
    client = FakeClient([
        _resp([_tool_use(dict(tool_input or _COT_CALL))], "tool_use"),
        _resp([_text("Managed money net length is discussed below.")], "end_turn")])
    return A.answer_numbers(question, asof="2026-07-31", client=client, query_fn=lambda _sql: rows)


def test_an_empty_positioning_fetch_prepends_the_decline():
    out = _run("what is managed money doing in corn", rows=[])
    assert out["calls"][0]["status"] == "no_rows"
    assert out["question_shape"] == "positioning"
    assert out["shape_metric_states"] == {"cot_managed_money": "empty"}
    assert out["shape_decline_guard"] == ["cot_managed_money"]
    assert out["answer"].startswith(A.SHAPE_DECLINE_LEAD)
    assert "the record holds no managed-money positioning reading" in out["answer"]
    assert "Managed money net length is discussed below." in out["answer"]   # PREPENDED, never a replacement


def test_a_served_positioning_fetch_declines_nothing():
    out = _run("what is managed money doing in corn",
               rows=[{"value": "118432", "knowledge_date": "2026-07-28"}])
    assert out["calls"][0]["status"] == "ok"
    assert out["shape_metric_states"] == {"cot_managed_money": "served"}
    assert "shape_decline_guard" not in out
    assert not out["answer"].startswith(A.SHAPE_DECLINE_LEAD)


def test_a_positioning_ask_the_agent_never_fetched_records_the_miss_without_a_line():
    """The miss state this plan is about (2.3 #1, NEVER FETCHED), and the one the decline line must NOT
    cover: nothing was attempted, so there is no empty fetch to report and no honest sentence to write.
    What C2 adds here is the RECORD -- previously a turn like this was byte-identical, in trace and in
    telemetry, to a turn where positioning was served."""
    out = _run("what is managed money doing in corn",
               rows=[{"value": "2462000"}],
               tool_input={"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot"})
    assert out["question_shape"] == "positioning"
    assert out["shape_metric_states"] == {"cot_managed_money": "not_attempted"}
    assert "shape_decline_guard" not in out
    assert not out["answer"].startswith(A.SHAPE_DECLINE_LEAD)


def test_a_shapeless_turn_is_byte_identical():
    """No shape -> no keys, no preface. The pre-C2 contract for every question the table does not name."""
    out = _run("what were Argentina corn ending stocks", rows=[{"value": "2462000"}],
               tool_input={"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot"})
    assert "question_shape" not in out and "shape_metric_states" not in out
    assert "shape_decline_guard" not in out
    assert out["answer"] == "Managed money net length is discussed below."


def test_a_lookup_error_never_becomes_a_data_absence_claim():
    """End to end, on the class finding 2.4(b) measured: the lookup raises, the turn is honest about
    having no figure, and the answer says nothing about the record holding nothing."""
    def failing(_sql):
        raise RuntimeError("Unable to verify/create output bucket")
    client = FakeClient([
        _resp([_tool_use(dict(_COT_CALL))], "tool_use"),
        _resp([_text("The figure is unavailable due to a lookup error.")], "end_turn")])
    out = A.answer_numbers("is managed money net long corn", asof="2026-07-31",
                           client=client, query_fn=failing)
    assert out["calls"][0]["status"] == "error"
    assert out["shape_metric_states"] == {"cot_managed_money": "error"}
    assert "shape_decline_guard" not in out
    assert "the record holds no" not in out["answer"]


# ==================================================================================================
# The lint's own teeth -- a config that breaks a fence must FAIL the build.
# ==================================================================================================
_BAD_CONFIGS = {
    "an R4-fenced price table, live": ("""
shapes:
  outlook:
    omission: "so the balance-sheet anchor is not quantified here"
    requires:
      - id: spot_anchor
        subject: "spot price anchor"
        tables: [silver_pink_sheet]
        metrics: [soybeans_usd_t]
""", "R4-fenced price table"),
    "positioning without its doctrine declaration": ("""
shapes:
  positioning:
    omission: "so positioning is not narrated here"
    requires:
      - id: cot_managed_money
        subject: "managed-money positioning reading"
        tables: [silver_cot]
        metrics: [mm_net]
""", "doctrine: r9_context"),
    "a metric that is not whitelisted": ("""
shapes:
  pace:
    omission: "so export pace is not quantified here"
    requires:
      - id: esr_exports
        subject: "weekly export-sales reading"
        tables: [silver_esr]
        metrics: [not_a_real_metric]
""", "whitelisted on none of"),
    "a parked requirement with no reason": ("""
shapes:
  pace:
    omission: "so export pace is not quantified here"
    requires:
      - id: esr_exports
        deferred: true
        subject: "weekly export-sales reading"
        tables: [silver_esr]
        metrics: [weekly_exports_1000mt]
""", "deferred_reason"),
}


@pytest.mark.parametrize("label", sorted(_BAD_CONFIGS), ids=lambda s: s)
def test_the_lint_refuses_a_broken_shape_table(label, tmp_path, monkeypatch):
    """check_question_shapes runs inside jobs/audit/silver_rebuild_gate's config_check stage, where a
    lint error is a RED gate for every family -- so its teeth are worth pinning rather than assuming.
    Each config below breaks exactly one rule and must be named in the error text."""
    body, expected = _BAD_CONFIGS[label]
    (tmp_path / "numbers").mkdir()
    (tmp_path / "numbers" / "question_shapes.yaml").write_text("version: 1\n" + body, encoding="utf-8")
    monkeypatch.setattr(cc, "_CFG", tmp_path)
    errs = cc.check_question_shapes()
    assert any(expected in e for e in errs), f"expected {expected!r} in {errs!r}"


def test_the_lint_refuses_a_decline_state_reachable_from_a_second_status(monkeypatch):
    """The (d) bind. Widening _STATUS_STATE so a vintage miss counts as an empty read is the single edit
    that would turn every C2 decline into a possible false claim, and it would pass every other check in
    this file on the shapes that do not use a vintage table."""
    monkeypatch.setattr(A, "_STATUS_STATE", {**A._STATUS_STATE, "not_known": A.SHAPE_DECLINE_STATE})
    errs = cc.check_question_shapes()
    assert any("reachable from executor status" in e for e in errs), errs


# ==================================================================================================
# F10 -- THE MISSING FILE. configs/graphrag/ is gitignored (.gitignore:49) and question_shapes.yaml is
# NOT force-added, so a fresh clone / CI / any image built from a clean checkout used to get a silently
# dead C2 lane AND a green lint: the check printed "not authored yet -- vacuous pass" and returned [].
# "The file vanished" and "the feature is off" must be distinguishable.
# ==================================================================================================
def test_a_missing_shape_table_is_a_build_error(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "_CFG", tmp_path)                  # no numbers/question_shapes.yaml at all
    monkeypatch.delenv("GRAPHRAG_QUESTION_SHAPES", raising=False)
    errs = cc.check_question_shapes()
    assert errs and any("MISSING" in e for e in errs), errs
    assert any("git add -f" in e for e in errs), "the error must say how to fix it"


def test_an_explicitly_disabled_lane_still_passes_vacuously(tmp_path, monkeypatch):
    """The escape hatch is EXPLICIT, which is the whole point: someone has to say the lane is off."""
    monkeypatch.setattr(cc, "_CFG", tmp_path)
    monkeypatch.setenv("GRAPHRAG_QUESTION_SHAPES", "off")
    assert cc.check_question_shapes() == []


# ==================================================================================================
# F5 -- context_ref RESOLVABILITY. `context_ref: cot_mm_positioning` named C1's cascade_map context leg
# while cascade_map held no such row: the config asserted an engine lane that did not exist and nothing
# said so. It resolves now (C1 landed the ref), and a dangling one is a build error.
# ==================================================================================================
def test_the_live_context_ref_resolves_in_cascade_map():
    from leviathan.graphrag.numbers import cascade as cq
    req = A.load_shape_table()["positioning"]["requires"][0]
    ref = req["context_ref"]
    row = (cq.load_map() or {}).get(ref)
    assert row is not None, f"{ref!r} is a dangling pointer -- C1's cascade_map row is missing"
    assert row["table"] in req["tables"]
    assert cq.positioning_context_violations(row) == []        # and it is the CONTEXT shape, not an engine one
    assert cc.check_question_shapes() == []


def test_the_lint_refuses_a_dangling_context_ref(monkeypatch):
    from leviathan.graphrag.numbers import cascade as cq
    monkeypatch.setattr(cq, "load_map", lambda: {})            # the pre-C1 world: the ref does not exist
    errs = cc.check_question_shapes()
    assert any("context_ref" in e and "dangling" in e for e in errs), errs


def test_the_lint_refuses_a_context_ref_on_a_table_the_requirement_does_not_declare(monkeypatch):
    from leviathan.graphrag.numbers import cascade as cq
    monkeypatch.setattr(cq, "load_map", lambda: {"cot_mm_positioning": {
        "table": "silver_psd", "metric": "exports_mt", "period_type": "marketing_year"}})
    errs = cc.check_question_shapes()
    assert any("context_ref" in e and "does not declare" in e for e in errs), errs


# ==================================================================================================
# F5 -- THE OBSERVABILITY HALF. question_shape / shape_metric_states / shape_decline_guard are "the
# record the four miss states need". They lived on answer_numbers' return dict and were DROPPED by both
# orchestrator lanes (run_numbers_only copies a fixed whitelist; hybrid discarded the dict entirely) and
# by eval's per-answer projection -- so no deck pin, no EMF counter and no baseline column could read
# them. The reader-facing DECLINE is numbers_only-only by construction (it rides nums['answer'], which
# the hybrid join never reads); the RECORD must not be, because all three measured positioning rows pin
# expected_intent: [reasoning, hybrid].
# ==================================================================================================
def _shape_client(tool_input=None):
    return FakeClient([_resp([_tool_use(dict(tool_input or _COT_CALL))], "tool_use"),
                       _resp([_text("Managed money net length is discussed below.")], "end_turn")])


def test_the_shape_record_rides_the_numbers_only_trace():
    from leviathan.graphrag import orchestrator as orch
    out = orch.run_numbers_only("what is managed money doing in corn", "2026-07-31",
                                client=_shape_client(), query_fn=lambda _sql: [])
    tr = out["trace"]
    assert tr["question_shape"] == "positioning"
    assert tr["shape_metric_states"] == {"cot_managed_money": "empty"}
    assert tr["shape_decline_guard"] == ["cot_managed_money"]


def test_a_shapeless_numbers_only_turn_leaves_the_trace_byte_identical():
    from leviathan.graphrag import orchestrator as orch
    out = orch.run_numbers_only("what were Argentina corn ending stocks", "2026-07-31",
                                client=_shape_client({"table": "silver_psd",
                                                      "metric": "ending_stocks_mt",
                                                      "commodity": "corn_cbot"}),
                                query_fn=lambda _sql: [{"value": "2462000"}])
    for k in ("question_shape", "shape_metric_states", "shape_decline_guard"):
        assert k not in out["trace"]


def test_the_shape_record_rides_the_hybrid_trace(monkeypatch):
    """The hybrid join already carries pattern_records / the futures decline / the period guard across
    this exact lane asymmetry; the shape record is carried the same way."""
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import orchestrator as orch

    def _fake_answer(query, **kw):
        kw["extra_resolver"]()                       # drive the numbers join exactly as answer() does
        return {"answer": "note", "trace": {}, "citations": [], "evidence": [], "structured": {}}

    monkeypatch.setattr(an, "answer", _fake_answer)
    out = orch.run_hybrid("what is managed money doing in corn", graph=None, asof="2026-07-31",
                          client=_shape_client(), query_fn=lambda _sql: [])
    tr = out["trace"]
    assert tr["question_shape"] == "positioning"
    assert tr["shape_metric_states"] == {"cot_managed_money": "empty"}
    assert tr["shape_decline_guard"] == ["cot_managed_money"]


def test_the_shape_record_is_persisted_in_the_eval_baseline():
    """eval._per_answer_record is a hard whitelist and the SINGLE source of truth for both the partial
    JSONL and _baseline_json -- a key absent from it reaches no artifact."""
    from leviathan.graphrag import eval as gev
    out = {"answer": "a", "trace": {"question_shape": "positioning",
                                    "shape_metric_states": {"cot_managed_money": "not_attempted"},
                                    "shape_decline_guard": None}}
    rec = gev._per_answer_record({"q": {"id": "s1"}, "out": out, "rubric": {}}, "single")
    assert rec["question_shape"] == "positioning"
    assert rec["shape_metric_states"] == {"cot_managed_money": "not_attempted"}
    assert rec["shape_decline_guard"] is None
    empty = gev._per_answer_record({"q": {"id": "s2"}, "out": {"answer": "a"}, "rubric": {}}, "single")
    assert empty["question_shape"] is None
