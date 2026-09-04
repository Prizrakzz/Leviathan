"""D-XL -- THE PRICE-EXTREME LOCATOR FAMILY. The build's own pins.

WHAT THE LEG IS. "When was this board's own price highest (or lowest), and what was it then" -- a
SELECTION over ONE board's tape that returns a DATED ROW WHOLE. Two kinds (`extreme`,
`windowed_extreme`) and one ALIAS (a level-ever ask IS that board's extreme, asked with a comparison the
reader will make), one product, one registered trace key.

THE LAWS THESE PINS EXIST TO HOLD, each named where it is asserted below:
  * FLAG-OFF BYTE-IDENTITY on every live surface -- the planner constitution, the schema, the validator,
    the answer seam, the persona. Three GOLDENS hold the same law from the other side
    (test_cascade_walk.py::test_g1x_...); these are the per-surface statements.
  * ONE CLOCK PER ROW. `query.asof` stays the TURN's as-of; the OBSERVATION's date rides as
    `knowledge_date` on the row and `located_date` on the locator. The staleness clause is suppressed
    for this leg alone, and BOTH DIRECTIONS are pinned.
  * DECLINES ARE NAMED AND COUNTED, on a CLOSED enum, first-blocker-wins.
  * A BUDGET MUST NEVER BIND ON A LEGITIMATE SHAPE: XL_CAP is 2 reads, the alias spends 1, and the
    windowed floor's comparator is `<` so a window AT the floor serves.
  * THE ENGINE-ONLY AGGS ARE REFUSED ON THE MODEL LANE, in the same commit that widens the Literal.
  * THE SERVED PROMPT IS THE MEASURED PROMPT: the block's sha is pinned, and an edit voids the freeze.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import inspect
import os
import re

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import config_check as cc
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import eval as EV
from leviathan.graphrag import orchestrator as orc
from leviathan.graphrag import register as reg
from leviathan.graphrag import tracekeys as tk
from leviathan.graphrag.numbers import agent as na
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import stats as ST
from leviathan.graphrag.numbers.registry import load_registry
from leviathan.silver import futures_eod_contracts as FEC

ASOF = "2026-09-02"
SLUG = "soybean_meal_cbot"
CORN = "corn_cbot"

# THE BANKED ROW A SQL, compiled at design time through the SHIPPED helpers and byte-compared here.
ROW_A_SQL = (
    "SELECT settle AS value, substr(CAST(trade_date AS varchar), 1, 10) AS knowledge_date, "
    "trade_year AS year, contract_month AS contract_month, settle_kind AS settle_kind, "
    "currency AS currency, COUNT(settle) OVER () AS _n, "
    "MIN(CASE WHEN settle IS NOT NULL THEN substr(CAST(trade_date AS varchar), 1, 10) END) OVER () "
    "AS _span_start, "
    "MAX(CASE WHEN settle IS NOT NULL THEN substr(CAST(trade_date AS varchar), 1, 10) END) OVER () "
    "AS _span_end FROM leviathan_dev.silver_futures_eod WHERE leviathan_slug = 'soybean_meal_cbot' "
    "AND trade_year <= 2026 AND substr(CAST(trade_date AS varchar), 1, 10) <= '2026-09-01' "
    "ORDER BY value DESC NULLS LAST, year DESC NULLS LAST, knowledge_date DESC NULLS LAST, "
    "contract_month DESC NULLS LAST LIMIT 1")


@pytest.fixture(autouse=True)
def _leave_the_render_cache_as_we_found_it():
    """THIS FILE IS THE ONLY ONE IN THE SUITE THAT RENDERS THE PLANNER WITH A ROSTER, so it is the
    only one that can mint a NEW `_SYS_RENDERS` key. That dict is process-global and carries a
    64-entry LEAK FENCE which CLEARS it wholesale when tripped -- and a cleared cache breaks a
    pre-existing identity pin two files away (`PLANNER_SYS is planner_sys()`), which is an ordering
    latent this file must not be able to feed. Snapshot in, restore out: the entries this file mints
    live exactly as long as the test that needs them.

    (Measured: with this file run immediately before test_xc_open_walk.py the identity pin passes
    either way -- the restore is belt, not the diagnosis.)"""
    before = dict(dp._SYS_RENDERS)
    yield
    dp._SYS_RENDERS.clear()
    dp._SYS_RENDERS.update(before)


def _card(table="silver_futures_eod"):
    return load_registry().get(table)


def _spec(**kw):
    base = dict(table="silver_futures_eod", metric="settle", asof=ASOF, commodity=SLUG)
    base.update(kw)
    return Q.NumberQuery(**base)


def _row(value=554.4, date="2022-04-19", cm="2022-05", kind="settlement", unit="USD/short ton",
         ccy="USD", n=49286, s0="2010-06-06", s1="2026-09-01"):
    return {"value": value, "knowledge_date": date, "year": int(date[:4]), "contract_month": cm,
            "settle_kind": kind, "currency": ccy, "unit": unit,
            "_n": n, "_span_start": s0, "_span_end": s1}


class _SG:
    def __init__(self):
        self.trace, self.nodes, self.seeds = {}, [], []


def _tape(rows_by_key):
    """A qfn over the COMPILED SQL: the fixture keys on (slug, direction, period_start) read out of the
    statement itself, so a compile change that broke the predicate would break the fixture too."""
    seen = []

    def qfn(sql):
        seen.append(sql)
        slug = sql.split("leviathan_slug = '")[1].split("'")[0]
        agg = "max_row" if "value DESC" in sql else "min_row"
        ps = sql.split(") >= '")[1].split("'")[0] if ") >= '" in sql else None
        return list(rows_by_key.get((slug, agg, ps), []))
    qfn.seen = seen
    return qfn


def _code_only(src: str) -> str:
    """Source with comment lines and docstring prose dropped -- a NEGATIVE pin over code must not be
    satisfied, or defeated, by a comment that quotes the thing it forbids."""
    out, in_doc = [], False
    for ln in (src or "").splitlines():
        t = ln.strip()
        if t.startswith('"""') or t.endswith('"""'):
            in_doc = not in_doc if t.count('"""') % 2 else in_doc
            continue
        if in_doc or t.startswith("#"):
            continue
        out.append(ln.split("  # ")[0])
    return chr(10).join(out)


def _plan(**kw):
    base = dict(steps=["reasoning"], contracts=[], price_extreme=True, xl_kind="extreme",
                xl_board=SLUG, xl_direction="max", xl_scope=None, xl_since=None,
                xl_confidence="high")
    base.update(kw)
    return dp.Plan(**base)


# ══ THE PLANNER CONSTITUTION ═══════════════════════════════════════════════════════════════════════
def test_p1_the_planner_surfaces_are_byte_identical_with_no_roster():
    """P1: with `xl_boards=None` -- the ONLY spelling, dict-typed, on all four functions -- the prompt,
    the schema, the validated Plan and the render-cache identity are what they were before this lane.
    The `_xl_block` half is asserted directly: "" on None AND on {}, so an empty roster and an absent
    one are the same fact."""
    assert dp._xl_block(None) == "" and dp._xl_block({}) == ""
    assert dp.PLANNER_SYS == dp.planner_sys()
    assert dp.planner_sys() is dp.planner_sys()                # the render cache returns the SAME object
    off = dp._plan_tool(["corn_cbot"], 2)
    assert not any(k.startswith("xl_") or k == "price_extreme"
                   for k in off["input_schema"]["properties"])
    assert off["input_schema"]["required"] == ["steps", "contracts"]
    # NEGATIVE PIN: no signature anywhere accepts a bare TUPLE for the roster parameter -- v3 carried
    # two incompatible spellings and the pins were written against both.
    for fn in (dp.planner_sys, dp._plan_tool, dp._validate, dp.plan_turn):
        ann = inspect.signature(fn).parameters["xl_boards"].annotation
        assert "dict" in str(ann), (fn.__name__, ann)


def test_p2_the_four_sites_move_together_and_the_section_renders_trailing():
    """P2 + P56: with the roster non-empty the PROMPT carries the section exactly once and IMMEDIATELY
    before the single '## OUTPUT DISCIPLINE' anchor; the SCHEMA carries all seven properties; the
    VALIDATOR returns them on the Plan; and `Plan.trace()` carries all seven AT THE TAIL. A property
    present in the schema but absent from the Plan FAILS here -- that is the silent-discard trap this
    constructor's explicit keywords create."""
    sys_on = dp.planner_sys(2, xl_boards=cq.XL_BOARD_LABEL)
    anchor = "\n## OUTPUT DISCIPLINE\n"
    assert sys_on.count(anchor) == 1
    assert sys_on.count("## PRICE-EXTREME DETECTION") == 1
    head = sys_on[:sys_on.index(anchor)]
    assert head.endswith("in code, never here.\n")            # the block is the LAST section rendered
    props = dp._plan_tool(["corn_cbot"], 2, cq.XL_BOARD_LABEL,
                          cq.XL_KINDS)["input_schema"]["properties"]
    seven = ("price_extreme", "xl_kind", "xl_board", "xl_direction", "xl_since", "xl_scope",
             "xl_confidence")
    assert all(k in props for k in seven)
    assert props["xl_board"]["enum"] == [None] + list(cq.XL_BOARD_SLUGS)
    assert props["xl_kind"]["enum"] == [None] + list(cq.XL_KINDS)
    p = dp._validate({"steps": ["reasoning"], "contracts": [], "price_extreme": True,
                      "xl_kind": "extreme", "xl_board": SLUG, "xl_direction": "max",
                      "xl_scope": "all_time", "xl_confidence": "high"},
                     {SLUG}, 2, cq.XL_BOARD_LABEL, cq.XL_KINDS)
    tr = p.trace()
    assert list(tr)[-7:] == list(seven)
    assert all(k in tr for k in seven)


def test_p3_validation_is_strict_and_an_empty_roster_forces_every_default():
    """P3: `price_extreme` is True only for LITERAL True; an off-roster board, an off-enum direction,
    kind, scope or confidence all yield None. With an EMPTY roster every one of the seven is forced to
    its default even when the raw output sets it -- so a malformed or hostile plan cannot set them."""
    raw = {"steps": ["reasoning"], "contracts": [], "price_extreme": "true", "xl_kind": "threshold",
           "xl_board": "not_a_board", "xl_direction": "high", "xl_scope": "forever",
           "xl_confidence": "certain", "xl_since": "the last five years"}
    p = dp._validate(raw, {SLUG}, 2, cq.XL_BOARD_LABEL, cq.XL_KINDS)
    assert (p.price_extreme, p.xl_kind, p.xl_board, p.xl_direction, p.xl_scope, p.xl_confidence,
            p.xl_since) == (False, None, None, None, None, None, None)
    for truthy in (1, "true", "True", None):
        r2 = dict(raw, price_extreme=truthy, xl_board=SLUG, xl_kind="extreme")
        assert dp._validate(r2, {SLUG}, 2, cq.XL_BOARD_LABEL, cq.XL_KINDS).price_extreme is False
    good = {"steps": ["reasoning"], "contracts": [], "price_extreme": True, "xl_kind": "extreme",
            "xl_board": SLUG, "xl_direction": "max", "xl_scope": "all_time", "xl_confidence": "high"}
    off = dp._validate(good, {SLUG}, 2)                        # NO roster -> every value defaults
    assert (off.price_extreme, off.xl_kind, off.xl_board, off.xl_direction, off.xl_scope,
            off.xl_confidence) == (False, None, None, None, None, None)
    # ...and a roster WITHOUT its kinds is an INCOMPLETE thread that fails closed, never a half-armed one
    half = dp._validate(good, {SLUG}, 2, cq.XL_BOARD_LABEL, ())
    assert half.price_extreme is False and half.xl_kind is None
    assert not any(k.startswith("xl_") for k in
                   dp._plan_tool(["corn_cbot"], 2, cq.XL_BOARD_LABEL, ())["input_schema"]["properties"])


def test_p4_the_sys_render_cache_key_is_a_hashable_tuple_and_the_leak_fence_holds():
    """P4: the key component is `tuple(sorted((xl_boards or {}).items()))` -- derived FROM the dict,
    never the dict. Two rosters produce two entries; the SAME roster returns the SAME OBJECT."""
    a = dp.planner_sys(2, xl_boards=cq.XL_BOARD_LABEL)
    b = dp.planner_sys(2, xl_boards=dict(cq.XL_BOARD_LABEL))
    assert a is b                                             # the dict is not the key; its items are
    assert dp.planner_sys(2, xl_boards={"corn_cbot": "CBOT corn"}) is not a
    assert dp.planner_sys(2) is dp.PLANNER_SYS                # the off render is still the constant
    assert all(isinstance(k, tuple) for k in dp._SYS_RENDERS)
    assert len(dp._SYS_RENDERS) <= 65                          # the 64-entry leak fence still clears


def test_p64_p95_the_shipped_prompt_is_the_measured_prompt():
    """P64 / P95 / K30: the rendered block hashes to the sha the measured probe banked, WITH THIS
    ROSTER substituted -- the roster is part of the measurement, so a board joining it changes the sha.
    A structural proxy for 'no quoted question' rides beside it: the block carries no question mark at
    all, and is ASCII. AN EDIT VOIDS THE FREEZE and consumes the held-out set; re-hashing the constant
    to make this pass is the exact move it exists to refuse."""
    blk = dp._xl_block(cq.XL_BOARD_LABEL)
    assert hashlib.sha256(blk.encode("utf-8")).hexdigest() == cq.XL_BLOCK_SHA256
    assert cq.XL_BLOCK_SHA256 == (
        "b8c32b17f63e26afb8eaec37ea72da3271a8bce5af88cf97a39e71cf57995f5b")
    assert "?" not in blk and all(ord(c) < 128 for c in blk)
    for slug, label in cq.XL_BOARD_LABEL.items():
        assert f"    {slug}  ({label})" in blk


def test_p54_the_v2_regex_grammar_exists_nowhere_in_the_tree():
    """P54: a dead classifier beside a live planner is the drift shape this estate refuses. answer.py
    performs NO classification for this lane -- the engine is gated by the ARGUMENT."""
    src = inspect.getsource(an)
    assert "_xl_dispatch" not in src
    # THERE IS NO _XL_*_RX IN THIS MODULE AT ALL. Every VOCABULARY (the row template, the two markers,
    # the superlative pair) is minted ONCE in cascade.py and imported, and the last local pattern --
    # `_XL_SENTENCE_RX`, the M5 counter's own sentence splitter -- is GONE: it cut inside decimal
    # figures and silenced the counter (fix pass 2, NEW 1), and the boundary is now the estate's own
    # `register._SENT_ITER`. So a producer and a gate can never hold two spellings of one fact.
    assert set(re.findall(r"(_XL_\w+_RX)\s*=", src)) == set()
    assert "_SENT_ITER" in src
    for name in ("_XL_BOARD_RX", "_XL_HIGH_RX", "_XL_LOW_RX", "_XL_WHEN_RX", "_XL_SCOPE_RX",
                 "_XL_NEG_RX", "_XL_PREMISE_RX", "_XL_LEVEL_RX"):
        assert name not in src, name


# ══ THE DECISION ═══════════════════════════════════════════════════════════════════════════════════
def test_p5_p90_the_decision_enum_is_closed_and_first_blocker_wins():
    """P5 / P90: `suppressed_reason` comes from a CLOSED set, first-blocker-wins IN ORDER, and the
    function is PURE -- it mutates neither the plan nor the roster. `direction` is evaluated only for
    kinds that consume it and `since` only for windowed_extreme, which is why `board` sits AHEAD of
    `direction`."""
    R, K = cq.XL_BOARD_LABEL, cq.XL_KINDS
    cases = [
        (None, "reasoning", True, "no_plan"),
        (_plan(), "numbers_only", True, "lane"),
        (_plan(), "reasoning", False, "switch"),
        (_plan(price_extreme=False), "reasoning", True, "shape"),
        (_plan(xl_kind=None), "reasoning", True, "kind"),
        (_plan(xl_confidence="low"), "reasoning", True, "confidence"),
        (_plan(xl_board="not_a_board"), "reasoning", True, "board"),
        (_plan(xl_direction=None), "reasoning", True, "direction"),
        (_plan(xl_kind="windowed_extreme", xl_since=None), "reasoning", True, "since"),
        (_plan(), "reasoning", True, None),
    ]
    for plan, kind, switch, want in cases:
        before = copy.deepcopy(plan.trace()) if plan is not None else None
        d = orc._extreme_locator_decision(plan, kind, R, switch, kinds_served=K)
        assert d["suppressed_reason"] == want, (want, d)
        assert d["fired"] is (want is None)
        assert (d["suppressed_reason"] in orc.XL_SUPPRESSED_REASONS
                or d["suppressed_reason"] is None)
        if plan is not None:
            assert plan.trace() == before                      # PURE: the plan is unmoved
    assert set(orc.XL_SUPPRESSED_REASONS) == {"no_plan", "lane", "switch", "shape", "kind",
                                              "confidence", "board", "direction", "since"}


def test_p6_the_engine_key_is_engine_only_and_a_dispatch_decline_never_writes_it():
    """P6: `quantify_extreme_locator` is written by the ENGINE alone -- its ABSENCE means the leg did
    not run, never that it declined. NEGATIVE PIN: no path in answer.py writes that key."""
    src = inspect.getsource(an)
    assert 'sg.trace["quantify_extreme_locator"]' not in src        # never ASSIGNED here
    assert '.get("quantify_extreme_locator")' in src                # only READ, by the hop
    assert 'sg.trace["quantify_extreme_locator"] = ' in inspect.getsource(cq)
    d = orc._extreme_locator_decision(_plan(), "numbers_only", cq.XL_BOARD_LABEL, True,
                                      kinds_served=cq.XL_KINDS)
    assert d["fired"] is False and d["suppressed_reason"] == "lane"


def test_p50_p91_the_trace_keys_are_the_last_two_and_the_decision_is_the_last_one():
    """P50 / P91: BOTH keys land at the tail, in order, in ONE commit -- so the negative-index tail pins
    across the suite re-anchor ONCE, by two. `kind` rides INSIDE the locator key, which is why two kinds
    cost ONE key."""
    assert tk.TRACE_RECORD_KEYS[-2:] == ("quantify_extreme_locator", "extreme_second_hop")
    assert tk.DECISION_RECORD_KEYS[-1] == ("extreme_locator", "extreme_locator_decision")
    assert not any("windowed" in k or "xl_kind" in k for k in tk.TRACE_RECORD_KEYS)


# ══ THE SQL ════════════════════════════════════════════════════════════════════════════════════════
def test_p7_the_compiled_row_a_is_the_banked_string_byte_for_byte():
    """P7: the branch compiles EXACTLY the string the design banked, including `COUNT(settle) OVER ()`
    and both CASE-guarded span aggregates. NEGATIVE PIN: `COUNT(*) OVER ()` appears nowhere -- it would
    over-claim the population by every unpriced row."""
    sql = Q.build_sql(_spec(agg="max_row"), _card())
    assert sql == ROW_A_SQL
    assert "COUNT(*) OVER ()" not in sql
    mn = Q.build_sql(_spec(agg="min_row"), _card())
    assert mn == ROW_A_SQL.replace("value DESC NULLS LAST", "value ASC NULLS LAST")
    assert sql.count("NULLS LAST") == 4 and mn.count("NULLS LAST") == 4


def test_p8_every_other_agg_compiles_byte_identically():
    """P8: the seven pre-existing aggs are untouched on a data_date card AND a vintage card, at every
    newest_first scope. The branch is keyed on a frozenset membership test no existing agg can enter."""
    ts = _card()
    vt = _card("silver_wasde")
    for agg in ("latest", "series", "sum", "mean", "max", "min"):
        for nf in (False, True, Q.NEWEST_FIRST_ALL):
            a = Q.build_sql(_spec(agg=agg), ts, futures_newest_first=nf)
            assert "_span_start" not in a and "OVER ()" not in a, (agg, nf)
        b = Q.build_sql(Q.NumberQuery(table="silver_wasde", metric="avg_farm_price", asof=ASOF,
                                      commodity="corn", agg=agg), vt)
        assert "_span_start" not in b
    assert Q.build_sql(_spec(agg="front_expiry"), ts).startswith("SELECT value, ")


def test_p9_the_one_clock_fence_raises_on_every_vintage_card():
    """P9: the branch is legal ONLY on a data_date card. On a VINTAGE card the row's date is a RELEASE
    STAMP and the observation is a PERIOD -- two clocks, not one -- and the message says so."""
    for table in ("silver_wasde", "silver_psd"):
        ts = _card(table)
        metric = sorted(ts.metrics)[0]
        with pytest.raises(ValueError) as e:
            Q.build_sql(Q.NumberQuery(table=table, metric=metric, asof=ASOF, commodity="corn",
                                      agg="max_row"), ts)
        assert "release stamp" in str(e.value) and "data_date" in str(e.value)


def test_p10_p11_p12_the_axis_fence_the_ignored_limit_and_the_series_predicate():
    """P10: a data_date card with NO date_col DECLINES with `extrema_axis_unavailable` in the message
    rather than falling back to the INT (year*100+month) expression, which would render a 6-digit
    `_span_start`. P11: `spec.limit` is IGNORED BY CONSTRUCTION -- LIMIT 1 cannot truncate. P12: the
    branch is not a series branch, so `run()` performs no newest-first re-sort on it."""
    ts = _card()
    assert Q.build_sql(_spec(agg="max_row", limit=1)) == Q.build_sql(_spec(agg="max_row", limit=5000))
    for agg in cq.XL_KINDS and ("max_row", "min_row"):
        assert Q._is_series_branch(_spec(agg=agg), ts) is False
    naked = copy.deepcopy(ts)
    naked.date_col = None
    with pytest.raises(ValueError) as e:
        Q._extreme_window(naked, "settle")
    assert "extrema_axis_unavailable" in str(e.value)
    assert not re.search(r"_span_start=\d{6}\b", Q.build_sql(_spec(agg="max_row")))


def test_p61_p79_the_token_set_is_a_frozenset_and_agent_imports_it():
    """P61 / P79: `EXTREME_ROW_AGGS` is a FROZENSET of exactly two tokens, `agent.py` IMPORTS it rather
    than re-typing them (the symbol IS the join), and `('sum',) + EXTREME_ROW_AGGS` raises TypeError --
    the MEASURED reason `_is_series_branch` joins two `in` tests with `or` instead of concatenating."""
    assert isinstance(Q.EXTREME_ROW_AGGS, frozenset)
    assert Q.EXTREME_ROW_AGGS == {"max_row", "min_row"}
    assert "near_row" not in Q.EXTREME_ROW_AGGS
    with pytest.raises(TypeError):
        ("sum",) + Q.EXTREME_ROW_AGGS
    src = inspect.getsource(na)
    assert "Q.EXTREME_ROW_AGGS" in src and '"max_row"' not in src.split("def _forced_spec")[1][:900]


def test_p59_p60_the_agent_lane_refuses_the_engine_only_aggs_and_the_engine_path_still_compiles():
    """P59 (NEGATIVE): `_forced_spec` RAISES before `NumberQuery` is constructed, on EVERY registered
    card, for BOTH tokens, and the message names the two legal alternatives -- `build_sql` is never
    reached. P60 (POSITIVE): the LOCATOR's own path is untouched, because it builds its NumberQuery
    directly and never calls `_forced_spec`."""
    tables = sorted(load_registry().tables)
    for table in tables[:8]:
        ts = load_registry().get(table)
        metric = sorted(ts.metrics)[0] if ts.metrics else "settle"
        for tok in ("max_row", "min_row"):
            with pytest.raises(ValueError) as e:
                na._forced_spec(ASOF, {"table": table, "metric": metric, "agg": tok})
            msg = str(e.value)
            assert "ENGINE-ONLY" in msg and "agg='max'" in msg and "agg='series'" in msg
    ok = na._forced_spec(ASOF, {"table": "silver_futures_eod", "metric": "settle", "agg": "max",
                                "commodity": SLUG})
    assert ok.agg == "max"
    assert "_forced_spec" not in inspect.getsource(cq._xl_locate)
    assert Q.build_sql(_spec(agg="max_row"), _card()) == ROW_A_SQL   # the engine path, with the fence in


# ══ THE PURE CALCULATOR ════════════════════════════════════════════════════════════════════════════
def test_p13_the_tie_rule_is_one_constant_minted_in_the_leaf():
    """P13: IDENTITY, not equality, and the import edge runs stats -> query. NEGATIVE PIN: stats.py does
    not import the query module -- its own docstring asserts it reads no filesystem, network, clock or
    global state, and query.py drags pydantic + YAML behind it."""
    assert Q.EXTREME_TIE_RULE is ST.EXTREME_TIE_RULE == "last"
    s = inspect.getsource(ST)
    assert "numbers.query" not in s and "numbers import query" not in s
    assert "from leviathan.graphrag.numbers.stats import EXTREME_TIE_RULE" in inspect.getsource(Q)


def test_p14_p15_the_calculator_is_the_sql_branch_s_oracle_and_the_tie_goes_to_the_LAST():
    """P14 / P15: on a tie the calculator picks the LATEST occurrence per EXTREME_TIE_RULE and reports
    `n_ties`; the SQL's own ORDER BY does the same by construction (value DESC then every alias DESC).
    The oracle agrees with the served row on (value, date, label) across three fixture tapes."""
    vals = [500.0, 554.4, 300.0, 554.4]
    dates = ["2021-03-04", "2021-03-05", "2022-01-01", "2022-04-19"]
    r = ST.extreme_locator(vals, dates, "max", labels=["a", "b", "c", "d"])
    assert r["declined"] is False and r["value"] == 554.4
    assert r["date"] == "2022-04-19" and r["n_ties"] == 2 and r["label"] == "d"
    assert r["tie_rule"] == "last" and r["first_date"] == "2021-03-04"
    lo = ST.extreme_locator(vals, dates, "min")
    assert lo["value"] == 300.0 and lo["date"] == "2022-01-01" and lo["n_ties"] == 1
    # the SQL's tiebreak, read off the compiled string: the extreme first, then _order_aliases DESC
    order = Q._extreme_order(Q._extras(_card()), False, agg="max_row")
    assert order.startswith("value DESC NULLS LAST, ")
    assert order.endswith("contract_month DESC NULLS LAST")   # a SAME-SESSION tie -> the FURTHEST month


def test_p16_the_calculator_declines_in_branch_order_and_truncated_is_a_hard_decline():
    """P16: axis-length mismatch, an undated cell and `truncated` each return the standard decline
    contract with value None. `truncated` NEVER returns a value -- WHICH END a saturated series keeps is
    flag-dependent, so its extreme is not the tape's."""
    assert ST.extreme_locator([1, 2], ["2020-01-01"], "max")["reason"].startswith("axis length")
    assert ST.extreme_locator([1, 2], ["2020-01-01", None], "max")["reason"].startswith("undated")
    t = ST.extreme_locator([1, 2], ["2020-01-01", "2020-01-02"], "max", truncated=True)
    assert t["declined"] is True and t["value"] is None and "TRUNCATED" in t["reason"]
    thin = ST.extreme_locator([1.0], ["2020-01-01"], "max")
    assert thin["declined"] is True and "need >=2" in thin["reason"]
    assert ST.MIN_EXTREME_N is ST.MIN_PAIR_SPREAD_N == 2
    assert ST.MIN_EXTREME_N is not ST.MIN_EXTREMA_N
    assert ST.extreme_locator([1, 2], ["2020-01-01", "2020-01-02"], "sideways")["declined"] is True


def test_p17_the_calculator_is_absent_from_the_agent_tool_enum():
    """P17: STAT_REGISTRY is the AGENT TOOL ENUM; this is an ENGINE calculator (the quantiles /
    sign_agreement rulings). Widening the enum is never a side effect of adding an engine function."""
    assert "extreme_locator" not in ST.STAT_NAMES
    assert ST.is_banned_name("extreme_locator") is False
    assert callable(ST.extreme_locator)


# ══ THE ROSTER ═════════════════════════════════════════════════════════════════════════════════════
def test_p33_p34_p94_the_roster_is_a_literal_and_it_is_bound_both_ways():
    """P33 / P34 / P94: a 15-entry LITERAL, never a comprehension over `display._contract_label` (a dict
    BUILT from the producer cannot be LINTED against it). Every label equals the producer's own
    spelling; NO label is its own de-underscored slug -- the one leak shape `register.internal_leaks`
    does NOT catch, which is why the literal, not the register, is the defence."""
    from leviathan.graphrag import display as disp
    assert len(cq.XL_BOARD_LABEL) == 15
    assert cq.XL_BOARD_SLUGS == tuple(cq.XL_BOARD_LABEL)
    src = inspect.getsource(cq)
    assert not re.search(r"XL_BOARD_LABEL\s*=\s*\{[^}]*for\s", src)   # no dict comprehension
    for slug, label in cq.XL_BOARD_LABEL.items():
        assert label == disp._contract_label(slug)
        assert label != slug.replace("_", " ")
        assert slug in FEC.PRICE_COVERAGE_START
        assert slug not in FEC.CASH_INDEX_SLUGS and slug not in cq.XL_DENY_SLUGS
    # THE DIRECTION A COMPREHENSION CAN NEVER CHECK
    today = dt.date.today()
    for slug, floor in FEC.PRICE_COVERAGE_START.items():
        if slug in FEC.CASH_INDEX_SLUGS or slug in cq.XL_DENY_SLUGS:
            continue
        if (today - floor).days >= Q.XL_ROSTER_MIN_SPAN_DAYS:
            assert slug in cq.XL_BOARD_LABEL, slug
    # the raw slug on a reader line IS caught; the de-underscored form is NOT -- both measured
    assert reg.internal_leaks("- [N1] soybean_meal_cbot settle high on 2022-04-19: 554.4")
    assert reg.internal_leaks("- [N1] soybean meal cbot settle high on 2022-04-19: 554.4") == []


def test_p32_the_walk_is_untouched_by_this_lane():
    """P32: `_CW_BOARD_LABEL`, the walk's marker, its span token and its fence are byte-identical, and
    `config_check.check_cascade_walk` is UNEDITED -- the new lint is inserted AFTER it, which is what
    makes that claim true rather than hopeful. Deriving this roster from the walk's would let a WALK
    CURATION CHANGE silently change which questions the locator answers."""
    assert cq.CW_MARKER_PREFIX == "CASCADE EPISODE WALK ("
    assert cq._CW_SPAN_TOKEN_RX.pattern == r"\d{4}-\d{2}\.\.\d{4}-\d{2}"
    assert callable(cq._cw_register_fence) and callable(cc.check_cascade_walk)
    assert "_CW_BOARD_LABEL" not in inspect.getsource(cq._xl_locate)
    assert "XL_BOARD_LABEL" not in inspect.getsource(cc.check_cascade_walk)
    # The two rosters are DIFFERENT SETS and the overlap is measured, not assumed: the walk's is
    # bound to admissible HOPS, which is a different question from "can this board's own extreme be
    # located". Three boards are XL-only for exactly that reason.
    assert len(cq._CW_BOARD_LABEL) == 20
    assert len(set(cq._CW_BOARD_LABEL) & set(cq.XL_BOARD_LABEL)) == 12
    assert set(cq.XL_BOARD_LABEL) - set(cq._CW_BOARD_LABEL) == {"cocoa", "cotton",
                                                                "frozen_orange_juice"}
    for slug in set(cq._CW_BOARD_LABEL) & set(cq.XL_BOARD_LABEL):
        assert cq._CW_BOARD_LABEL[slug] == cq.XL_BOARD_LABEL[slug]


def test_p62_p63_p76_the_two_gates_are_named_and_the_row_gate_is_tape_scoped():
    """P62 (ROSTER GATE): static, import-time, ADMISSION ONLY -- it is the only gate an import-time
    roster can honestly apply, because at import there is NO SERVED TAPE. NEGATIVE PIN: the symbol
    `_tape_clears` exists nowhere; it was undefined and conflated the two.
    P63 / P76 (ROW GATE): the MEASURED `_n` and the MEASURED span, at SERVE time, on ROW A ONLY -- and
    that scope is a MEASUREMENT: the trailing window IS XL_RECENT_DAYS (728d) against a 1095d floor, so
    applied per-row it would decline the recent row on EVERY board by construction."""
    assert Q.XL_ROSTER_MIN_SPAN_DAYS == 1095
    for mod in (Q, cq, an, orc):
        assert "_tape_clears" not in inspect.getsource(mod)
    assert Q.XL_RECENT_DAYS if False else cq.XL_RECENT_DAYS == 730
    assert cq.XL_RECENT_DAYS < Q.XL_MIN_TAPE_SPAN_DAYS         # the measurement that scopes the gate
    body = inspect.getsource(cq._xl_locate)
    assert body.count("XL_MIN_TAPE_ROWS") == 1 and body.count("XL_MIN_TAPE_SPAN_DAYS") == 1
    q = _tape({(SLUG, "max_row", None): [_row(n=100, s0="2026-08-01", s1="2026-09-01")]})
    cands, pay = cq._xl_locate(q, {"board": SLUG, "direction": "max", "kind": "extreme"}, ASOF)
    assert cands == [] and pay["declines"][0]["reason"] == "tape_too_short"
    assert pay["declines"][0]["rows"] == 100 and pay["reads"] == 1


def test_p35_p53_the_lint_is_green_and_enumerates_every_exclusion():
    """P35 / P53: `check_extreme_locator` binds ten facts and is GREEN on the shipped tree; the
    WITH-TAPE-BUT-EXCLUDED set is ENUMERATED in its output so the boundary is visible rather than
    silent. Drift in the frozen-prompt sha is a BUILD FAILURE, checked here by injection."""
    assert cc.check_extreme_locator() == []
    assert cc._check_synthesized_price_legs() == []
    real = cq.XL_BLOCK_SHA256
    try:
        cq.XL_BLOCK_SHA256 = "0" * 64
        errs = cc.check_extreme_locator()
        assert any("MEASURED" in e for e in errs), errs
    finally:
        cq.XL_BLOCK_SHA256 = real
    real_metric = cq.XL_SOURCE_METRIC
    try:
        cq.XL_SOURCE_METRIC = "open_interest"
        assert any("D-XL locator" in e for e in cc._check_synthesized_price_legs())
    finally:
        cq.XL_SOURCE_METRIC = real_metric


# ══ THE RENDERED ROW, THE FENCE AND THE CITATION ═══════════════════════════════════════════════════
def test_p24_p25_p26_p27_p31_the_line_carries_reader_words_and_clears_the_real_vocabulary():
    """P24: the LINE renders the LITERAL's label and the CALL keeps the RAW SLUG in `query.commodity`
    (a display label in the query poisons the citations LOCATOR -- the chart params read it unresolved).
    P25: the three-part quote -- level + unit + delivery month + kind of print -- is on the line.
    P26: the kind is `citations._print_kind` VERBATIM; 'official settlement' appears nowhere.
    P27: ONE formatter. P31: six exemplars across two kinds of print and four currencies, all clean."""
    exemplars = [
        (SLUG, _row(), "max", None, None),
        ("cocoa", _row(11722.0, "2024-12-18", "2025-03", "close", "USD/metric ton", "USD",
                       24310, "2018-12-24"), "max", None, None),
        ("cotton", _row(155.95, "2022-05-04", "2022-07", "close", "US cents/lb", "USD",
                        20117, "2018-12-24"), "max", None, None),
        ("rapeseed_oil_zce", _row(6218.0, "2022-03-08", "2022-05", "close", "CNY/t", "CNY",
                                  33110, "2015-10-08"), "min", None, None),
        ("frozen_orange_juice", _row(533.85, "2023-11-30", "2024-01", "close", "US cents/lb", "USD",
                                     9044, "2018-12-24"), "max", None, None),
        (CORN, _row(818.0, "2022-04-29", "2022-07", "settlement", "US cents/bushel", "USD",
                    1842, "2020-01-02"), "max", "2020", ("2010-06-06", "2026-09-01")),
    ]
    for i, (slug, row, direction, since, tape) in enumerate(exemplars, 1):
        ln = cq._xl_row_line(i, slug, row, direction=direction, since=since, tape_span=tape)
        assert cq._XL_ROW_RX.fullmatch(ln), ln
        assert cq.XL_ROW_LINE_RX.search(ln)
        assert cq.XL_BOARD_LABEL[slug] in ln
        if "_" in slug:                                       # the leak class is the UNDERSCORED id
            assert slug not in ln
        assert reg.internal_leaks(ln) == []
        assert reg.count_valuation_words(ln) == 0 and reg.count_flow_words(ln) == 0
        assert cq.pace_register_ok(ln)
        assert cit._print_kind(row) in ln and "official settlement" not in ln
        assert row["unit"] in ln and cq._xl_fmt(row["value"]) in ln
        assert f"delivery {row['contract_month'][:4]}M{row['contract_month'][5:7]}" in ln
    for v in (554.4, 11722.0, 6218.0, 155.95, 812):
        assert cq._xl_fmt(v) == cit._fmt(v)
    assert cq._xl_fmt(11722.0) == "11,722"                    # NOT the ',.1f' form


def test_p86_no_population_count_reaches_a_rendered_superlative_line():
    """P86: the SPAN carries the superlative's fence and NOTHING ELSE does -- a rendered population
    count is charged `number_unbacked` by the shipped verifier, so `_n` rides the trace payload and the
    eval column instead. Asserted DIRECTLY on the line the engine emits."""
    row = _row()
    ln = cq._xl_row_line(1, SLUG, row, direction="max")
    assert "49,286" not in ln and "49286" not in ln and "priced prints" not in ln
    assert "read from 2010-06-06 to 2026-09-01" in ln
    assert "sessions" not in ln


def test_p29_p30_the_fence_has_two_halves_with_different_atomicity():
    """P30 (REGISTER HALF, WHOLE-BLOCK ATOMIC): a line failing any register scan drops the WHOLE block,
    rolls the ledger back to base and stamps `fenced` -- zero [N] rows leak.
    P29 (TEMPLATE HALF, PER-ROW): a row failing `_XL_ROW_RX` drops ALONE, the survivors renumber
    contiguously from the same base, and the RENUMBERED shipped line re-passes. Per-row dropping is only
    safe under FENCE-BEFORE-MINT, which is why handles are assigned AT APPEND TIME."""
    assert cq._xl_register_fence(["- [N1] CBOT corn settle high on 2020-01-01: 1 US cents/bushel"])
    assert cq._xl_register_fence(["corn is undervalued against wheat"]) is False
    assert cq._xl_register_fence(["- [N1] soybean_meal_cbot settle high on 2022-04-19"]) is False
    sg, calls = _SG(), []
    # the trailing window's lower bound is COMPUTED from the constant, never typed: an off-by-one
    # would silently test the no-rows branch instead of the two-row one.
    _lo = (dt.date.fromisoformat(ASOF) - dt.timedelta(days=cq.XL_RECENT_DAYS)).isoformat()
    q = _tape({(CORN, "max_row", None): [_row(831.25, "2012-08-21", "2012-12", "settlement",
                                              "US cents/bushel", "USD", 60000, "2010-06-06")],
               (CORN, "max_row", _lo): [_row(700.0, "2025-05-05", "2025-07", "settlement",
                                             "US cents/bushel", "USD", 6000, _lo)]})
    lines, pay = cq._extreme_locator_leg_or_nothing(
        sg, None, {"board": CORN, "direction": "max", "kind": "extreme"}, q, ASOF, calls)
    assert pay["outcome"] == "fired" and len(calls) == 2
    assert [ln.split("]")[0] for ln in lines] == ["- [N1", "- [N2"]
    for ln in lines:
        assert cq._XL_ROW_RX.fullmatch(ln)
    # a block whose EVERY row drops ships NOTHING, marker included (the row-less-no-marker law)
    sg2, calls2 = _SG(), []
    real = cq._XL_ROW_RX
    try:
        cq._XL_ROW_RX = re.compile(r"(?!x)x")
        lines2, pay2 = cq._extreme_locator_leg_or_nothing(
            sg2, None, {"board": CORN, "direction": "max", "kind": "extreme"}, q, ASOF, calls2)
    finally:
        cq._XL_ROW_RX = real
    assert lines2 == [] and calls2 == [] and pay2["outcome"] == "declined"
    assert pay2["rows_fenced"] == 2


def test_p19_p20_p21_p22_p23_one_clock_per_row_and_no_false_staleness():
    """P19: the row's `knowledge_date` IS the located session and `citations.from_number` stamps it.
    P20: `query.asof` stays the TURN's as-of, so the span, the locator and `eval._pit_clean` agree; the
    OBSERVATION rides as `located_date`. NEGATIVE PIN: no path narrows `query.asof`, and the span never
    enters `query.period`.
    P21: with `located_extreme` the staleness clause is SUPPRESSED; WITHOUT it, it FIRES -- both
    directions, because the clause is correct everywhere else and this leg is the one exception.
    P22: `_pit_clean` passes, and FAILS on a hand-mutated located_date beyond the read's own cutoff.
    P23: exactly one row -> no abundance marker, no TRUNCATED marker."""
    row = _row()
    call = cq._shown(cq._xl_call(SLUG, row, ASOF), row["value"])
    assert call["query"]["asof"] == ASOF and call["query"]["period"] is None
    assert call["query"]["commodity"] == SLUG                  # the MACHINE id, in the query
    assert call["query"]["metric"] == "located price extreme"  # a KIND-FREE reader phrase
    assert call["shown"] == [554.4] and len(call["rows"]) == 1
    c = cit.from_number(call, 1)
    assert c.date == "2022-04-19"
    assert c.locator["asof"] == ASOF and c.locator["located_date"] == "2022-04-19"
    assert c.locator["commodity"] == SLUG and c.locator["source_metric"] == "settle"
    assert "period" not in c.locator or not c.locator["period"]
    assert "(latest available" not in c.label
    assert "TRUNCATED" not in c.label and "of 1 " not in c.label
    naked = copy.deepcopy(call)
    naked["rows"][0].pop("located_extreme")
    assert "(latest available 2022-04-19; as-of 2026-09-02)" in cit.from_number(naked, 1).label
    out = {"citations": [c.__dict__ if hasattr(c, "__dict__") else c], "trace": {}}
    good = {"citations": [{"kind": "number", "locator": dict(c.locator),
                           "payload": {"rows": call["rows"]}}], "trace": {}}
    assert EV._pit_clean(good, ASOF) is True
    bad = copy.deepcopy(good)
    bad["citations"][0]["locator"]["located_date"] = "2030-01-01"
    assert EV._pit_clean(bad, ASOF) is False
    assert out is not None


def test_p18_the_unit_comes_off_the_post_run_row_not_the_compiled_select():
    """P18: the compiled SELECT carries FIVE aliases and NO unit -- `_apply_unit_overrides` stamps
    `r['unit']` after the fetch. NEGATIVE PIN, measured: a synthetic row WITHOUT `unit` renders
    '= 554.4 (exchange settlement, USD)' -- the unit gone and the currency promoted into the tag list --
    so the leg must build from the POST-run row."""
    sql = Q.build_sql(_spec(agg="max_row"), _card())
    # the SELECT's OWN aliases, not every " AS " in the string -- the DP-5 timestamp normalizer
    # carries a CAST whose own "AS varchar" is not an alias of anything.
    aliases = re.findall(r" AS (\w+)(?=,| FROM)", sql)
    assert aliases == ["value", "knowledge_date", "year", "contract_month", "settle_kind",
                       "currency", "_n", "_span_start", "_span_end"]
    assert " AS unit" not in sql and " AS data_date" not in sql
    row = _row()
    row.pop("unit")
    lbl = cit.from_number(cq._xl_call(SLUG, row, ASOF), 1).label
    assert "= 554.4 (exchange settlement, USD)" in lbl


def test_p40_verify_charges_the_value_and_shown_binds_it():
    """P40: `_claim_numbers_with_decimals` on the payoff sentence returns the served value, and
    `_mismatch_pool` REPLACES the row pool with `shown` when present -- so a correct transcription is
    not scored a fabrication. The ISO date is fully exempt from claim extraction."""
    from leviathan.graphrag import verify as vf
    row = _row()
    call = cq._shown(cq._xl_call(SLUG, row, ASOF), row["value"])
    sent = "CBOT soybean meal settled at 554.4 on 2022-04-19 [N1]."
    nums, _ = vf._claim_numbers_with_decimals(sent)
    assert nums == [554.4]                                    # the date contributes nothing
    assert vf._mismatch_pool(call, sent) == [554.4]


# ══ THE TWO KINDS, THE ALIAS AND THE BUDGET ════════════════════════════════════════════════════════
def test_p71_p92_the_kind_enum_is_two_members_and_the_windowed_only_state_is_refused(monkeypatch):
    """P71: TWO members, and neither 'threshold' nor 'level_analog' is one of them -- both cuts are
    STRUCTURAL. P92: `_xl_kinds_served` is minted from TWO independent sub-flags over that ONE literal,
    and the windowed-only state RAISES: a lane that answers 'the highest since 2020' and declines 'the
    highest ever' would be shipping a prompt whose positive shape it refuses to serve."""
    assert cq.XL_KINDS == ("extreme", "windowed_extreme")
    for bad in ("threshold", "level_analog", "near_row"):
        assert bad not in cq.XL_KINDS
        assert bad not in str(dp._plan_tool(["c"], 2, cq.XL_BOARD_LABEL, cq.XL_KINDS))
    monkeypatch.delenv("XL_KIND_EXTREME", raising=False)
    monkeypatch.delenv("XL_KIND_WINDOWED", raising=False)
    assert an._xl_kinds_served() == ()
    monkeypatch.setenv("XL_KIND_WINDOWED", "on")
    with pytest.raises(ValueError) as e:
        an._xl_kinds_served()
    assert "xl_kind_flags_invalid" in str(e.value)
    monkeypatch.setenv("XL_KIND_EXTREME", "on")
    # BOTH ON, AND THE LANE STILL DOES NOT ARM: the K32 kill (see the fix-pass pin below) refuses the
    # windowed kind while `XL_MIN_WINDOW_ROWS` is None. With a calibrated floor the pair serves.
    with pytest.raises(ValueError) as e3:
        an._xl_kinds_served()
    assert "xl_window_floor_uncalibrated" in str(e3.value)
    real = cq.XL_MIN_WINDOW_ROWS
    try:
        cq.XL_MIN_WINDOW_ROWS = 20
        assert an._xl_kinds_served() == cq.XL_KINDS
    finally:
        cq.XL_MIN_WINDOW_ROWS = real
    monkeypatch.delenv("XL_KIND_WINDOWED")
    with pytest.raises(ValueError) as e2:
        an._xl_kinds_served()
    assert "xl_kind_rollback_unmeasured" in str(e2.value)      # the S1 block is not measured HERE


def test_p72_p72b_the_since_shape_test_is_not_a_parse():
    """P72: `_XL_SINCE_RX` fullmatches the three legal grains and rejects a phrase, a decade, a
    two-digit year and a one-digit month. P72b: it ALSO fullmatches '2026-13' and '2026-06-31', which
    `date.fromisoformat` rejects -- so the engine's try/except is proven LOAD-BEARING rather than
    decorative, and a real leap day parses."""
    for good in ("2020", "2020-03", "2020-03-15", "1999", "2026-13", "2026-06-31"):
        assert dp._XL_SINCE_RX.fullmatch(good), good
    for bad in ("the last five years", "2020s", "20", "2020-3", "since 2020", "1899"):
        assert not dp._XL_SINCE_RX.fullmatch(bad), bad
    assert cq._xl_parse_since("2020") == dt.date(2020, 1, 1)
    assert cq._xl_parse_since("2020-02") == dt.date(2020, 2, 1)
    assert cq._xl_parse_since("2020-02-29") == dt.date(2020, 2, 29)   # a REAL leap day
    for bad in ("2021-02-29", "2026-13", "2026-06-31", "", None, "the last five years"):
        assert cq._xl_parse_since(bad) is None, bad


def test_p73_p73b_p73c_the_router_is_the_shipped_one_called_with_parsed_dates():
    """P73: four semantic branches, each falling to `extreme` and each COUNTED.
    P73b: the call site passes `datetime.date` on BOTH bounds -- and `covers(slug, str, str)` RAISES
    TypeError, so the coercion is proven load-bearing rather than decorative. NEGATIVE PIN: no
    hand-rolled comparison against `coverage_start_for` anywhere in the branch.
    P73c: the `legacy` verdict is UNREACHABLE FROM THIS CALLER -- it needs `hi < floor` and `hi` is
    always the turn's as-of, while the ROSTER GATE guarantees floor <= asof - 1095. The branch is ALIVE
    off-roster, which is why the decline is a single `!= 'serve'` and not a three-way."""
    with pytest.raises(TypeError):
        FEC.covers(CORN, "1995-01-01", "2026-09-04")
    asof_d = dt.date.fromisoformat(ASOF)
    for slug in cq.XL_BOARD_SLUGS:
        floor = FEC.coverage_start_for(slug)
        assert FEC.covers(slug, floor, asof_d) == "serve"
        assert FEC.covers(slug, floor - dt.timedelta(days=1), asof_d) == "straddle"
        assert FEC.covers(slug, dt.date(1900, 1, 1), asof_d) == "straddle"
        assert FEC.covers(slug, dt.date.min, asof_d) == "straddle"
    assert FEC.covers("french_wheat_matif", dt.date(1900, 1, 1), dt.date(2020, 1, 1)) == "legacy"
    body = inspect.getsource(cq._xl_locate)
    assert 'covers(slug, since_d, asof_d) != "serve"' in body
    assert "window_pre_coverage" not in body and "coverage_start_for" in body
    for mod in (cq, an, orc):
        assert "window_pre_coverage" not in inspect.getsource(mod)


def test_p73_the_four_windowed_declines_each_fall_to_extreme_and_are_counted():
    q = _tape({(CORN, "max_row", None): [_row(831.25, "2012-08-21", "2012-12", "settlement",
                                              "US cents/bushel", "USD", 60000, "2010-06-06")],
               (CORN, "max_row", "2020-01-01"): [_row(818.0, "2022-04-29", "2022-07", "settlement",
                                                      "US cents/bushel", "USD", 1842, "2020-01-02")]})
    def go(since):
        return cq._xl_locate(q, {"board": CORN, "direction": "max", "kind": "windowed_extreme",
                                 "since": since}, ASOF)
    for since, reason in (("the last five years", "since_unparseable"),
                          ("2026-07", "window_too_short"),
                          ("1995", "window_straddles_coverage")):
        cands, pay = go(since)
        assert reason in [d["reason"] for d in pay["declines"]], (since, pay["declines"])
        assert pay["kind"] == "extreme"                        # the kind FALLS, never to nothing
        assert pay["kind_requested"] == "windowed_extreme"     # ...and the ASK's kind is preserved
        assert cands and cands[0]["since"] is None             # the served row is the whole-tape one
        # FIX PASS: the fallback ships ONE row (the latch), spends at most XL_CAP reads, counts its own
        # suppression, and RENDERS a note telling the reader the floor was dropped.
        assert len(cands) == 1 and pay["reads"] <= cq.XL_CAP
        assert "window_fallback_no_row_b" in [d["reason"] for d in pay["declines"]]
        note = cq._xl_notes(pay)
        assert len(note) == 1 and cq.XL_SCOPE_NOTE_TAIL in note[0]
        assert cq.XL_DECLINE_TEMPLATES[reason] in note[0]
    cands, pay = go("2020")
    assert pay["kind"] == "windowed_extreme" and pay["reads"] == 2
    assert [c["since"] for c in cands] == ["2020", None]       # ROW W first, ROW A as the tape anchor


def test_p74_row_w_is_row_a_with_a_lower_bound_and_the_delta_is_interleaved():
    """P74: ZERO new SQL. `_filters` with `period_start` differs from ROW A's by EXACTLY two predicates,
    nothing is removed, and the two additions are INTERLEAVED, not appended -- a byte-equality pin
    written as a tail-append fails on its first run."""
    ts = _card()
    a = Q._filters(_spec(commodity=CORN, agg="max_row"), ts)
    for grain, iso in (("2020", "2020-01-01"), ("2020-03", "2020-03-01"),
                       ("2020-03-15", "2020-03-15")):
        w = Q._filters(_spec(commodity=CORN, agg="max_row", period_start=iso), ts)
        assert len(w) == len(a) + 2 and all(x in w for x in a)
        assert w == ["leviathan_slug = 'corn_cbot'",
                     f"substr(CAST(trade_date AS varchar), 1, 10) >= '{iso}'",
                     "trade_year <= 2026", f"trade_year >= {iso[:4]}"], (grain, w)


def test_p75_p36_the_two_suppressions_and_their_named_counters():
    """P75 (windowed): when ROW A's located date falls INSIDE the window, only ROW W renders,
    `window_contains_alltime` is counted, and ROW W's line gains the tape-span clause.
    P36 (extreme): when the trailing window's located date EQUALS the tape-wide one, only one row
    renders and `recent_equals_alltime` is counted."""
    inside = _tape({(CORN, "max_row", None): [_row(818.0, "2022-04-29", "2022-07", "settlement",
                                                   "US cents/bushel", "USD", 60000, "2010-06-06")],
                    (CORN, "max_row", "2020-01-01"): [_row(818.0, "2022-04-29", "2022-07",
                                                           "settlement", "US cents/bushel", "USD",
                                                           1842, "2020-01-02")]})
    cands, pay = cq._xl_locate(inside, {"board": CORN, "direction": "max",
                                        "kind": "windowed_extreme", "since": "2020"}, ASOF)
    assert [d["reason"] for d in pay["declines"]] == ["window_contains_alltime"]
    assert len(cands) == 1 and cands[0]["tape_span"] == ("2010-06-06", "2026-09-01")
    ln = cq._xl_row_line(1, CORN, cands[0]["row"], direction="max", since="2020",
                         tape_span=cands[0]["tape_span"])
    assert "the whole-record span for this board runs from 2010-06-06 to 2026-09-01" in ln
    assert cq._XL_ROW_RX.fullmatch(ln)
    lo = (dt.date.fromisoformat(ASOF) - dt.timedelta(days=cq.XL_RECENT_DAYS)).isoformat()
    same = _tape({(SLUG, "max_row", None): [_row()], (SLUG, "max_row", lo): [_row()]})
    cands2, pay2 = cq._xl_locate(same, {"board": SLUG, "direction": "max", "kind": "extreme"}, ASOF)
    assert [d["reason"] for d in pay2["declines"]] == ["recent_equals_alltime"]
    assert len(cands2) == 1 and pay2["reads"] == 2


def test_p77_p77b_p77c_the_threshold_alias_is_a_branch_and_it_saves_a_read():
    """P77: the alias adds NO schema field and NO enum member -- a threshold-shaped ask compiles exactly
    ROW A's banked string, and no threshold value appears in the leg's source, its payload or its lines.
    P77b: on `scope == 'all_time'` the leg reads ROW A ALONE -- and the NEGATIVE PIN is asserted on the
    CALL COUNTER, not on the rendered output, because a POST-read suppression would pass an output-only
    assertion while still spending the read.
    P77c: the outcome name is in the decline vocabulary and is register-clean."""
    q = _tape({(SLUG, "max_row", None): [_row()],
               (SLUG, "max_row", "2024-09-03"): [_row(341.2, "2025-11-14", "2026-01")]})
    cands, pay = cq._xl_locate(q, {"board": SLUG, "direction": "max", "kind": "extreme",
                                   "scope": "all_time"}, ASOF)
    assert pay["reads"] == 1 and len(q.seen) == 1              # THE READ IS NOT SPENT
    assert [d["reason"] for d in pay["declines"]] == ["scope_all_time_no_row_b"]
    assert len(cands) == 1 and "recent" not in pay
    assert "scope_all_time_no_row_b" in cq.XL_DECLINE_TEMPLATES
    t = cq.XL_DECLINE_TEMPLATES["scope_all_time_no_row_b"]
    assert reg.internal_leaks(t) == [] and reg.exec_leaks(t) == [] and reg.sanitize(t) == t
    props = dp._plan_tool(["c"], 2, cq.XL_BOARD_LABEL, cq.XL_KINDS)["input_schema"]["properties"]
    assert not any("threshold" in k for k in props)
    assert all("threshold" not in str(v.get("enum") or "") for v in props.values())
    assert not any("threshold" in str(k) for k in pay)      # no field, no payload key, no row key
    assert not any("threshold" in str(k) for c in cands for k in c["row"])


def test_p78_the_alias_scope_rule_makes_the_all_time_branch_unreachable_on_the_windowed_path():
    """The v4.1 fatal, closed IN THE VALIDATOR the engine shares: `xl_scope` is FORCED None whenever the
    kind is `windowed_extreme`. The frozen block orders BOTH kind=windowed on a named floor AND
    scope=all_time on a level-ever ask, and a threshold ask that ALSO names a floor routes to windowed
    -- so windowed + all_time is a DESIGNED route. Applied verbatim the all_time branch would suppress
    the SECOND read, which on that path is ROW W, and the floor-named ask would be served the WHOLE-TAPE
    high. Forcing scope None there makes the branch unreachable BY CONSTRUCTION."""
    p = dp._validate({"steps": ["reasoning"], "contracts": [], "price_extreme": True,
                      "xl_kind": "windowed_extreme", "xl_board": CORN, "xl_direction": "max",
                      "xl_since": "2020", "xl_scope": "all_time", "xl_confidence": "high"},
                     {CORN}, 2, cq.XL_BOARD_LABEL, cq.XL_KINDS)
    assert p.xl_kind == "windowed_extreme" and p.xl_since == "2020" and p.xl_scope is None
    d = orc._extreme_locator_decision(p, "reasoning", cq.XL_BOARD_LABEL, True,
                                      kinds_served=cq.XL_KINDS)
    assert d["fired"] is True and d["scope"] is None
    q = _tape({(CORN, "max_row", None): [_row(831.25, "2012-08-21", "2012-12", "settlement",
                                              "US cents/bushel", "USD", 60000, "2010-06-06")],
               (CORN, "max_row", "2020-01-01"): [_row(818.0, "2022-04-29", "2022-07", "settlement",
                                                      "US cents/bushel", "USD", 1842, "2020-01-02")]})
    cands, pay = cq._xl_locate(q, {"board": CORN, "direction": "max", "kind": "windowed_extreme",
                                   "since": "2020", "scope": None}, ASOF)
    assert pay["reads"] == 2 and len(cands) == 2               # BOTH rows read on the windowed path
    assert "scope_all_time_no_row_b" not in [d["reason"] for d in pay["declines"]]


def test_p76b_the_window_floor_is_charged_on_row_w_s_own_n_with_the_stated_comparator():
    """P76b: the floor is evaluated on ROW W's OWN measured `_n` -- PRICED EXPIRY-ROWS, counted AFTER
    the WHERE -- never on the declared calendar window. THE COMPARATOR IS `<`: a window whose `_n`
    EQUALS the floor SERVES, which is the fail-open direction, chosen because a budget must never bind
    on a legitimate shape. It ships PENDING its own measurement and carries NO candidate default, so it
    is INERT today and says so."""
    assert cq.XL_MIN_WINDOW_ROWS is None                      # PENDING, and no number to mistake
    assert cq.XL_MIN_WINDOW_SESSIONS == 10 and cq.XL_MIN_WINDOW_DAYS == 180
    body = inspect.getsource(cq._xl_locate)
    assert "int(row_w.get(\"_n\") or 0) < XL_MIN_WINDOW_ROWS" in body
    q = _tape({(CORN, "max_row", None): [_row(831.25, "2012-08-21", "2012-12", "settlement",
                                              "US cents/bushel", "USD", 60000, "2010-06-06")],
               (CORN, "max_row", "2020-01-01"): [_row(818.0, "2022-04-29", "2022-07", "settlement",
                                                      "US cents/bushel", "USD", 3, "2020-01-02")]})
    real = cq.XL_MIN_WINDOW_ROWS
    try:
        cq.XL_MIN_WINDOW_ROWS = 3                              # _n EQUALS the floor -> it SERVES
        _c, pay = cq._xl_locate(q, {"board": CORN, "direction": "max",
                                    "kind": "windowed_extreme", "since": "2020"}, ASOF)
        assert "window_too_thin" not in [d["reason"] for d in pay["declines"]]
        cq.XL_MIN_WINDOW_ROWS = 4                              # strictly below -> it DECLINES
        cands, pay2 = cq._xl_locate(q, {"board": CORN, "direction": "max",
                                        "kind": "windowed_extreme", "since": "2020"}, ASOF)
        thin = [d for d in pay2["declines"] if d["reason"] == "window_too_thin"]
        assert thin and thin[0]["n"] == 3 and thin[0]["floor"] == 4
        assert pay2["kind"] == "extreme" and cands[0]["since"] is None
        # FIX PASS (review major 1 / refute major 2): THIS is the fixture the reviewers reproduced a
        # THIRD read on. The ceiling is now asserted here, on the counter, not inferred from the output.
        assert pay2["reads"] <= cq.XL_CAP and len(cands) == 1
    finally:
        cq.XL_MIN_WINDOW_ROWS = real


def test_p70_the_recent_window_straddle_is_declared_inert_on_todays_roster():
    """P70: at XL_RECENT_DAYS the trailing window's lower bound is LATER than every roster floor, so
    `covers()` returns 'serve' for all 15 boards and the branch is unreachable today. It is KEPT -- a
    calibration may move the window and a roster addition with a young tape would make it live -- and
    the pin asserts INERTNESS on the shipped roster rather than pretending to exercise it."""
    asof_d = dt.date.fromisoformat(ASOF)
    lo = asof_d - dt.timedelta(days=cq.XL_RECENT_DAYS)
    for slug in cq.XL_BOARD_SLUGS:
        assert FEC.covers(slug, lo, asof_d) == "serve", slug
    worst = max((asof_d - FEC.coverage_start_for(s)).days for s in cq.XL_BOARD_SLUGS)
    assert worst > cq.XL_RECENT_DAYS                          # the branch needs a much wider window
    assert "recent_window_straddle" in cq.XL_DECLINE_TEMPLATES


def test_the_decline_vocabulary_is_closed_register_clean_and_sanitize_stable():
    """Every counted outcome has a NAME and a reader sentence, and every sentence is register-clean and
    sanitize-stable -- a decline that leaks an internal id is a decline that cannot be rendered."""
    expected = {"board_unresolved", "deny_listed", "label_unresolved", "vintage_card",
                "extrema_axis_unavailable", "no_rows", "tape_too_short", "recent_window_straddle",
                "recent_equals_alltime", "scope_all_time_no_row_b", "window_contains_alltime",
                "since_unparseable", "window_too_short", "window_straddles_coverage",
                "no_rows_in_window", "window_too_thin", "hop_degenerate", "timeline_off", "fenced",
                "error",
                # FIX PASS, and each is a fact the shipped vocabulary could not state:
                #   window_fallback_no_row_b  -- the ROW B latch's own suppression (review major 1)
                #   no_rows_in_recent_window  -- the ENGINE's trailing window, which is NOT the ask's
                #                                named window (review minor 1: one name, two facts)
                "window_fallback_no_row_b", "no_rows_in_recent_window",
                # FIX PASS 2 (re-review NEW 3): `month_only_card`. `build_sql`'s year_month refusal
                # says the card carries NO release stamp and NO per-observation date; the substring
                # classifier filed it as `vintage_card`, whose sentence says it records a release
                # stamp -- the opposite. The fact had no name until now.
                "month_only_card"}
    assert set(cq.XL_DECLINE_TEMPLATES) == expected
    assert set(cq.XL_RENDERED_DECLINES) <= expected             # every rendered name has a sentence
    for reason, text in cq.XL_DECLINE_TEMPLATES.items():
        assert reg.internal_leaks(text) == [], reason
        assert reg.exec_leaks(text) == [], reason
        assert reg.sanitize(text) == text, reason
        assert not any(ch.isdigit() for ch in text), reason


def test_the_deny_list_and_the_cash_references_are_excluded_by_their_own_reasons():
    """The deny/cash test runs FIRST, and the ORDER IS THE DIAGNOSTIC: a deny-listed slug is ALSO
    off-roster, so a roster-membership test placed first would report every one of them as
    `board_unresolved` and the named reason would be structurally unreachable -- absence credited as a
    pass, in the very counter that exists to make the exclusion visible."""
    assert cq.XL_DENY_SLUGS == {"malaysian_crude_palm_oil_cme", "robusta_coffee", "white_sugar"}
    for slug in sorted(cq.XL_DENY_SLUGS | set(FEC.CASH_INDEX_SLUGS)):
        _c, pay = cq._xl_locate(_tape({}), {"board": slug, "direction": "max", "kind": "extreme"},
                                ASOF)
        assert pay["declines"][0]["reason"] == "deny_listed", slug
        assert pay["reads"] == 0
    assert set(FEC.CASH_INDEX_SLUGS) & set(cq.XL_BOARD_LABEL) == set()


# ══ THE SEAM, THE PERSONA AND THE SECOND HOP ═══════════════════════════════════════════════════════
def test_p44_p47_the_two_gates_are_row_shapes_and_the_mandate_splits(monkeypatch):
    """P44: the HOP gate is a ROW SHAPE with a MINTED TOKEN and REFUSES the bare-prefix decoy -- a
    retrieved chunk is rendered raw into the volatile prompt, so a bare prefix would arm a two-clock
    mandate over a block that does not exist. It also never carries `tl.LINE_PREFIX`.
    P47: on a locator-only turn the locator gate is True, the hop gate is False, and `_system()` carries
    the locator mandate and NOT the hop mandate."""
    from leviathan.graphrag import timeline as tl
    row = cq._xl_row_line(1, SLUG, _row(), direction="max")
    hop = f"{cq.XL_HOP_PREFIX}{cq.XL_HOP_TOKEN} corn, 2012-05..2012-09: 4 report dates"
    decoy = cq.XL_HOP_PREFIX + "corn, the 2012 drought was severe."
    assert cq.XL_HOP_LINE_RX.search(hop) and not cq.XL_HOP_LINE_RX.search(decoy)
    assert not hop.startswith(tl.LINE_PREFIX) and tl.LINE_PREFIX not in hop
    monkeypatch.delenv("GRAPHRAG_EXTREME_LOCATOR", raising=False)
    assert an._extreme_locator_block_on(row) is False          # flag off -> both gates dark
    assert an._extreme_hop_block_on(row + "\n" + hop) is False
    monkeypatch.setenv("GRAPHRAG_EXTREME_LOCATOR", "on")
    assert an._extreme_locator_block_on(row) is True
    assert an._extreme_hop_block_on(row) is False              # a locator-only turn
    assert an._extreme_hop_block_on(row + "\n" + hop) is True
    assert an._extreme_hop_block_on(hop) is False              # a hop line CANNOT stand alone
    lic = an._system()
    loc = an._system(extreme_locator=True)
    both = an._system(extreme_locator=True, extreme_hop=True)
    assert an._SYSTEM_EXTREME_LOCATOR in lic
    assert an._SYSTEM_EXTREME_LOCATOR_MANDATE in loc and an._SYSTEM_EXTREME_HOP_MANDATE not in loc
    assert an._SYSTEM_EXTREME_HOP_MANDATE in both
    assert len(lic) < len(loc) < len(both)


def test_p48_flag_off_byte_identity_on_every_persona_and_seam_surface(monkeypatch):
    """P48: with the flag unset, `_system()` output, the two new keyword-only booleans' defaults, the
    planner surfaces and `cq.quantify`'s kwargs are all byte-identical -- and an injected quantify fake
    written against the PRE-D-XL signature stays valid, which is the load-bearing property every
    cascade fixture in the suite rests on."""
    monkeypatch.delenv("GRAPHRAG_EXTREME_LOCATOR", raising=False)
    base = an._system()
    assert an._SYSTEM_EXTREME_LOCATOR not in base
    assert an._system(extreme_locator=True, extreme_hop=True) == base   # the FLAG gates the append
    params = inspect.signature(an._system).parameters
    assert params["extreme_locator"].default is False and params["extreme_hop"].default is False
    assert list(params)[-2:] == ["extreme_locator", "extreme_hop"]
    qs = inspect.signature(cq.quantify).parameters
    assert qs["extreme_locator"].default is None
    # the locator kwarg and the extrema rider are the LAST TWO, in the order they were added -- so
    # the golden's "appended at the TAIL, nothing moved" prefix rule still holds for every caller.
    assert list(qs)[-2:] == ["extreme_locator", "extrema_own_date"]
    for fn, name in ((an.answer, "xl_request"), (an._answer_l2, "xl_request"),
                     (orc.run_reasoning, "xl_request"), (orc.run_hybrid, "xl_request"),
                     (dp.plan_turn, "xl_kinds")):
        assert list(inspect.signature(fn).parameters)[-1] == name, fn.__name__
    assert an._extreme_locator_on() is False and an._xl_lane_promote_on() is False
    assert an._extrema_own_date_on() is False and an._xl_superlative_strip_on() is False


def test_p49_the_lane_promotion_is_dark_and_never_fights_the_price_tiebreak():
    """P49: promotion-only, its own sub-flag, and it NEVER demotes.
    P67 (m3): a turn D-AM-1's PRICE TIEBREAK already demoted to numbers_only is NEVER promoted back --
    without the exclusion the two routers would fight over one turn and `_kind_hist` would carry both
    entries, an audit trail that reads as a routing loop."""
    src = inspect.getsource(orc)
    blk = src.split("XL_LANE_PROMOTE: PROMOTION-ONLY")[1][:2600]
    assert 'kind == "numbers_only"' in blk and 'kind = "hybrid"' in blk
    assert '(decided or {}).get("price_decline_reroute")' in blk
    assert "an._xl_lane_promote_on()" in blk and "an._extreme_locator_on()" in blk
    assert 'kind = "numbers_only"' not in blk                # never a demotion
    assert "plan.contracts" not in blk                       # and never a contract change


def test_p39_the_superlative_strip_is_deferred_and_the_deferral_is_enforced():
    """P39 / M5: the COUNTER ships on BOTH arms and CHANGES NO BYTE. NEGATIVE PINS: no symbol named
    `_drop_unspanned_superlative_sentences` or `_SEAM_SRC_XL_SUPERLATIVE` exists anywhere, and
    `_xl_superlative_strip_on` is defined and read by NO call site in this commit -- the deferral is
    enforced rather than remembered."""
    src = inspect.getsource(an)
    assert "_drop_unspanned_superlative_sentences" not in src
    assert "_SEAM_SRC_XL_SUPERLATIVE" not in src
    assert src.count("_xl_superlative_strip_on") == 1          # its own def, and nothing else
    _st = EV._cascade_stats({"citations": [], "structured": None, "answer": "", "trace": {}})
    assert "xl_unspanned_stripped" not in _st
    assert "xl_unspanned_superlative" in _st                 # the COUNTER ships; the strip does not


def test_p38_the_superlative_counter_passes_its_six_case_oracle():
    """P38: a sentence is CONVICTED iff it claims a record and states no span. The two vocabularies are
    minted in cascade.py so the counter and the deferred strip cannot drift apart."""
    cases = [("Corn hit its all-time high.", 1),
             ("Corn set a record high.", 1),
             ("Corn reached its record.", 1),
             ("The highest settle in the record read from 2010-06-06 to 2026-09-01.", 0),
             ("The widest range in the 2019-2026 window on record here.", 0),
             ("Nothing here was ever derived.", 0)]
    for text, want in cases:
        # SCOPED (refute minor 4): each case is now cited to a locator handle, which is the only scope
        # the counter reads. The oracle's verdicts are unchanged -- the vocabularies did not move.
        got = an._count_unspanned_superlatives({"tldr": text.rstrip(".") + " [N1].", "mechanism": ""},
                                               handles={"[N1]"})
        assert got == want, (text, got, want)
    assert an._count_unspanned_superlatives(
        {"tldr": "Its all-time high [N1]. A record high [N1].", "mechanism": ""},
        handles={"[N1]"}) == 2
    assert an._count_unspanned_superlatives({"tldr": "", "mechanism": ""}, handles={"[N1]"}) == 0


def test_p89_the_hop_is_kind_agnostic_and_appends_nothing_to_episodes_injected():
    """P89: the hop reads `located_date` ALONE -- both kinds write exactly one, so the same D produces
    the same hop block whichever kind found it.
    P43: it appends NOTHING to `episodes_injected`; its windows ride its OWN key, which
    `eval._injected_episodes` reads so a bullet transcribing one is MATCHABLE rather than convicted."""
    body = inspect.getsource(an._extreme_hop_lines)
    code = "\n".join(ln for ln in body.split("\n") if "#" not in ln)
    assert "episodes_injected" not in code.split('"""')[-1]
    assert 'hop.setdefault("spans"' in body
    assert "XL_HOP_PREFIX" in code and "tl.LINE_PREFIX" not in code
    assert "render_line" not in code
    out = {"trace": {"episodes_injected": [{"node": "corn", "spans": ["2012-05..2012-09"]}],
                     "extreme_second_hop": {"spans": {"drought": "1988-04..1988-08"}}}}
    eps = EV._injected_episodes(out)
    assert {e["node"] for e in eps} == {"corn", "drought"}
    assert {e["span"] for e in eps} == {"2012-05..2012-09", "1988-04..1988-08"}
    off = {"trace": {"episodes_injected": [{"node": "corn", "spans": ["2012-05..2012-09"]}]}}
    assert len(EV._injected_episodes(off)) == 1                # the hop adds nothing when absent


def test_p46_the_hop_declines_on_degeneracy_and_on_the_timeline_switch():
    """P46: with (asof - D) inside the floor the hop declines `hop_degenerate` -- `episodes_for(node, D)`
    would return the same windows the turn already rendered at A, and the retrieval the same props: two
    clocks that are one clock. The DEPENDENCY on the timeline switch is DECLARED, never inferred, and
    the decline is COUNTED and never narrated as 'nothing happened'."""
    assert cq.XL_MIN_HOP_DAYS == 45
    assert an._cq_xl_min_hop_days() == 45
    assert an._iso_ord("2026-09-02") - an._iso_ord("2026-08-25") == 8
    body = inspect.getsource(an._answer_l2)
    assert "hop_degenerate" in body and "located_after_asof" in body
    assert "timeline_off" in inspect.getsource(an._extreme_hop_lines)
    assert "GRAPHRAG_TIMELINE" in inspect.getdoc(an._extreme_locator_on)


def test_p45_the_hop_budget_is_one_retrieval_on_the_root_with_rerank_off():
    """P45: `ev.retrieve` is PER NODE and routes to one pg round trip per call, and the turn's own
    retrieval partial carries rerank=True -- so root + three drivers would be four round trips AND four
    cross-encoder passes on the synthesis hot path. EXACTLY ONE retrieval, on the ROOT, rerank OFF."""
    body = inspect.getsource(an._extreme_hop_lines)
    assert body.count("xl_retr(") == 1
    assert 'rerank=False' in body and 'mode="hybrid"' in body
    assert "near=located" in body
    assert cq.XL_DRIVER_FAN == 3 and cq.XL_EV_K == 5
    assert 'hop["ev_reads"] = 1' in body
    # FIX PASS (refute minor 5): the `probe_retr` idiom VERBATIM -- the partial is built only when no
    # retrieval was injected, and the injection is adopted by the sibling's own
    # `probe = probe_retrieve or retrieve` line. The budget claim is only enforceable over the partial
    # THIS function configures, so an injected callable is RECORDED rather than adopted silently.
    assert "None if retrieve" in body and "xl_probe or retrieve" in body
    assert 'hop["retr_injected"]' in body and 'hop["retr_rerank_off"]' in body


def _xl_cit(located="2022-04-19", kd="2022-04-19", value=554.4, cid="N1"):
    """A rendered locator CITATION, the shape `citations.unify` produces from `cascade._xl_call`: the
    `located_date` rider on the locator, the served row under the payload."""
    return {"id": cid, "kind": "number",
            "locator": {"metric": cq.XL_METRIC, "commodity": SLUG, "asof": ASOF,
                        "located_date": located},
            "payload": {"rows": [{"value": value, "knowledge_date": kd}], "status": "ok"}}


def test_p52_the_eval_projections_carry_every_locator_verdict():
    """P52: eval projects `xl_*` on every artifact row, flag-off included (the cw_* precedent), and
    `xl_date_cited` reads the CITATION's own clock against the served row's own date -- the one column
    that makes the defect this leg fixes measurable. NEGATIVE PIN: no `xl_unspanned_stripped`."""
    pay = {"outcome": "fired", "kind": "extreme", "kind_requested": "extreme", "board": SLUG,
           "direction": "max", "scope": None,
           "since": None, "located_date": "2022-04-19", "span_start": "2010-06-06",
           "span_end": "2026-09-01", "n_prints": 49286, "reads": 2, "rows_fenced": 0,
           "declines": [{"reason": "recent_equals_alltime"}], "recent": {}}
    out = {"citations": [_xl_cit()],
           "structured": {"tldr": "peaked on 2022-04-19", "mechanism": ""},
           "answer": "", "trace": {"quantify_extreme_locator": pay,
                                   "extreme_second_hop": {"nodes": ["a"], "gap_days": 1597,
                                                          "episodes_per_node": {"a": 2},
                                                          "receipts": 1, "ev_reads": 1,
                                                          "declines": []},
                                   "xl_unspanned_superlative": 0},
           "intent_decision": {"extreme_locator": {"board": SLUG, "direction": "max",
                                                   "kind": "extreme", "since": None}}}
    st = EV._cascade_stats(out)
    assert st["xl_rendered"] is True and st["xl_outcome"] == "fired"
    assert st["xl_date_cited"] is True and st["xl_located_date"] == "2022-04-19"
    assert st["xl_reads"] == 2 and st["xl_n_prints"] == 49286
    assert st["xl_declines"] == ["recent_equals_alltime"]
    assert st["xl_board_exact"] is True and st["xl_direction_exact"] is True
    assert st["xl_kind_exact"] is True and st["xl_since_exact"] is None
    assert st["xl_date_in_prose"] is True
    assert st["xl_hop_rendered"] is True and st["xl_hop_ev_reads"] == 1
    assert st["xl_unspanned_superlative"] == 0
    assert st["xl_threshold_echo"] == 0 and st["xl_threshold_verdict"] == 0
    assert st["xl_window_duration_gloss"] == 0
    # the SPAN-END defect, caught: a citation whose clock is NOT the served row's own session
    bad = copy.deepcopy(out)
    bad["citations"] = [_xl_cit(located="2026-09-01")]
    assert EV._cascade_stats(bad)["xl_date_cited"] is False
    empty = EV._cascade_stats({"citations": [], "structured": None, "answer": "", "trace": {}})
    assert empty["xl_rendered"] is False and empty["xl_reads"] == 0
    assert empty["xl_board_exact"] is None                     # not fired -> not scored
    assert EV._cascade_asserts({"expect": {"xl_rendered": False}},
                               {"citations": [], "trace": {}, "structured": None,
                                "answer": ""})["xl_rendered"] is True


def test_p58_the_cascade_quant_dependency_is_declared_not_silently_inherited(monkeypatch):
    """P58: the persona appends sit INSIDE the `GRAPHRAG_CASCADE_QUANT != 'off'` branch, so with that
    flag off a turn would ship locator rows with NO licensing clause. The walk has exactly the same
    shape, so it is a PRECEDENT -- and it is DECLARED in the flag helper's own docstring rather than
    discovered in an arm."""
    monkeypatch.setenv("GRAPHRAG_EXTREME_LOCATOR", "on")
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "off")
    s = an._system(extreme_locator=True, extreme_hop=True)
    assert an._SYSTEM_EXTREME_LOCATOR not in s
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "on")
    assert an._SYSTEM_EXTREME_LOCATOR in an._system(extreme_locator=True)
    assert "GRAPHRAG_CASCADE_QUANT" in inspect.getdoc(an._extreme_locator_on)


def test_the_leg_writes_its_one_key_on_every_path_it_ran_and_never_on_a_path_it_did_not():
    """The J4 `fired == bool(key)` precedent: `outcome` in {fired, declined, fenced} rides INSIDE the
    key, so an ABSENT key means the leg did not run. The belt rolls the LEDGER back on an exception --
    an orphan call record would widen the verifier's acceptance pool and stretch the [N] index range."""
    sg, calls = _SG(), []
    q = _tape({(SLUG, "max_row", None): [_row()]})
    cq._extreme_locator_leg_or_nothing(sg, None, {"board": SLUG, "direction": "max",
                                                  "kind": "extreme"}, q, ASOF, calls)
    assert sg.trace["quantify_extreme_locator"]["outcome"] == "fired"
    sg2, calls2 = _SG(), [{"query": {}}]
    def boom(sql):
        raise RuntimeError("pg is down")
    lines, pay = cq._extreme_locator_leg_or_nothing(
        sg2, None, {"board": SLUG, "direction": "max", "kind": "extreme"}, boom, ASOF, calls2)
    assert lines == [] and len(calls2) == 1                    # the pre-existing call survives
    assert sg2.trace["quantify_extreme_locator"]["outcome"] == "declined"
    # FIX PASS (refute major 6): a RAISE is `error`, never `no_rows`. The distinction is the whole point
    # -- `no_rows`' reader sentence says no priced print was returned for this board at this cutoff,
    # which is a COVERAGE claim, and a throttled read is not one.
    assert [d["reason"] for d in pay["declines"]] == ["error"]


def test_the_quantify_seam_omits_the_kwarg_when_off_and_both_return_paths_carry_the_leg():
    """E32: the leg is appended LAST at BOTH quantify return sites -- it owns NO groups (its input is a
    request dict, not a grounded node), so it must not die on the early return, which is exactly the
    branch the modal thin turn takes."""
    src = inspect.getsource(cq.quantify)
    assert src.count("_extreme_locator_leg_or_nothing") == 2
    early, main = src.split("if not groups and not chain and not transmission:")[1].split(
        "units, pairs = _pair_units(groups)")
    assert "_extreme_locator_leg_or_nothing" in early and "_extreme_locator_leg_or_nothing" in main
    seam = inspect.getsource(an._answer_l2)
    assert "_xl_kw = {}" in seam and "**_xl_kw," in seam
    assert '_xl_kw = {"extreme_locator": _xl_req}' in seam
    assert seam.index("_xl_kw = {}") > seam.index("_cw_kw = {}")   # appended LAST, nothing moved


# ══ THE EXTREMA-CLOCK REPAIR, BUILT DARK (its own flag, its own commit, its own arm) ═══════════════
def test_g11_the_extrema_clock_repair_is_reachable_flag_gated_and_byte_inert_when_off():
    """THE STANDING DEFECT, and why it is BUILT HERE and FLIPPED ELSEWHERE. `stats.extrema` computes
    first-occurrence `argmin`/`argmax` that NOTHING has ever read, and its live mint sites stamp a
    DIFFERENT date on the cited row -- the series end, or the handle's latest knowledge date. 'One clock
    per row' is an estate law, and an extreme row stamped with the series end asserts that the peak was
    observed on a date it was not. Shipping the locator beside it would leave the estate holding TWO
    extreme rows that disagree about what an extreme's date means.

    IT IS DARK, AND THAT IS THE POINT: it changes LIVE rendered bytes on serving surfaces the locator
    does not depend on, so flipping it in this lane's arm would make that arm measure its own
    instrument -- the same reason the superlative strip is deferred. The flag is read at the ANSWER
    SEAM and threaded DOWN as an argument; no module below it reads the environment for it."""
    assert an._extrema_own_date_on() is False                  # DEFAULT-OFF, fail-closed
    qs = inspect.signature(cq.quantify).parameters
    assert list(qs)[-1] == "extrema_own_date" and qs["extrema_own_date"].default is False
    # the ENGINE reads no env for it -- an os.environ read, never a docstring naming the flag
    assert "os.environ" not in inspect.getsource(cq)
    assert 'os.environ.get("GRAPHRAG_EXTREMA_OWN_DATE"' in inspect.getsource(an)
    seam = inspect.getsource(an._answer_l2)
    assert '_eod_kw = {"extrema_own_date": True} if _extrema_own_date_on() else {}' in seam
    assert "**_eod_kw)" in seam
    # SITE 2 (the RV reading's ordinal-when-thin rung) is REPAIRED: the extreme's own date, off the
    # SAME axis the value axis was built from, by the SAME drop rule.
    rung = inspect.getsource(cq._rv_price_reading)
    assert "_ex_hi_d = _ex_lo_d = dates[-1]" in rung           # the OFF value is today's, exactly
    assert 'ex.get("argmax")' in rung and 'ex.get("argmin")' in rung
    assert "extrema_own_date_declines" in rung                 # a misaligned axis DECLINES, never guesses
    # SITE 3 (the derived lane's ordinal-when-thin rung) DECLINES, and the design predicted it: a
    # marketing-year history read off a VINTAGE card has no per-observation date axis at all, so "the
    # extreme's own date" is not defined on it. Counted rather than silently skipped, so the per-site
    # measurement can tell "nothing moved" from "nothing was attempted".
    from leviathan.graphrag.numbers import derived as dv
    su = inspect.getsource(dv.su_standing)
    assert "extrema_axis_unavailable" in su and "su_standing_ordinal_thin" in su
    assert list(inspect.signature(dv.su_standing).parameters)[-1] == "extrema_own_date"
    # SITE 4 is DELIBERATELY OUT OF THE BYTE-CHANGE SET: `outcomes.outcome_distribution` returns
    # UNDATED extremes to a distribution summary, so there is no cited row and no clock to repair.
    from leviathan.graphrag.numbers import outcomes as oc
    assert "knowledge_date" not in inspect.getsource(oc.outcome_distribution)


def test_p37_the_two_floors_ride_side_by_side_and_the_error_path_credits_no_read():
    """P37: the rendered span start is the row's OWN MEASURED `_span_start`; the shipped coverage map's
    declared floor rides BESIDE it as a cross-check only -- never rendered, never substituted -- so a
    disagreement between the map and the served tape is visible in the artifact instead of silently
    deciding what a reader is told. The TAPE floor and the COVERAGE floor are different facts.

    AND THE `_cw_turn_spent` DOCTRINE, applied to the belt: the error path leaves `reads` ABSENT rather
    than stamping 0. It cannot know how many reads the raising call had already spent, and a 0 there
    would let an UNKNOWN decline CREDIT the turn's ceiling -- absent-never-zero."""
    q = _tape({(SLUG, "max_row", None): [_row()]})
    _c, pay = cq._xl_locate(q, {"board": SLUG, "direction": "max", "kind": "extreme",
                                "scope": "all_time"}, ASOF)
    assert pay["span_start"] == "2010-06-06"                   # the ROW's own measured first print
    assert pay["coverage_floor"] == str(FEC.coverage_start_for(SLUG))
    ln = cq._xl_row_line(1, SLUG, _row(), direction="max")
    assert pay["span_start"] in ln and "coverage" not in ln    # cross-check only, never rendered
    sg, calls = _SG(), []

    def boom(sql):
        raise RuntimeError("pg is down")
    _l, p2 = cq._extreme_locator_leg_or_nothing(
        sg, None, {"board": SLUG, "direction": "max", "kind": "extreme"}, boom, ASOF, calls)
    # FIX PASS: the raise is classified `error` INSIDE the leg now, so the read IS counted (it may have
    # been billed) -- and it is the BELT's own error payload, reached only when the leg itself raises,
    # that leaves `reads` absent. Both halves are asserted rather than accepted as either.
    assert [d["reason"] for d in p2["declines"]] == ["error"] and p2["reads"] == 1
    _real = cq._xl_locate
    try:
        def _raise(*a, **k):
            raise RuntimeError("the leg itself failed")
        cq._xl_locate = _raise
        sg3, calls3 = _SG(), []
        _l3, p3 = cq._extreme_locator_leg_or_nothing(
            sg3, None, {"board": SLUG, "direction": "max", "kind": "extreme"}, boom, ASOF, calls3)
        assert p3["declines"] == [{"reason": "error"}]
        assert "reads" not in p3, "an unknown decline must never credit the ceiling"
        assert p3["kind_requested"] == "extreme"                # the ASK's kind survives the belt
    finally:
        cq._xl_locate = _real


def test_the_hop_renders_its_own_lines_and_arms_its_own_gate_end_to_end(monkeypatch):
    """The hop EXECUTED, not merely inspected: a grounded driver + the contract root, a timeline that
    returns one window, and one retrieval that returns one prop -- and the assertion is that the block
    it produces ARMS the hop gate (so the mandate can ship) while carrying zero [N] handles and no
    engine-minted magnitude beyond dates and report counts.

    THE PUBLICATION-AXIS PRE-FILTER IS THE LOAD-BEARING PART: `episodes_for` selects its receipt on the
    WINDOW axis but stores the receipt's PUBLICATION date, and its own leakage argument holds only
    against the as-of the evidence was retrieved at -- so the evidence list is cut on the publication
    axis BEFORE the call, and the pin reads it back off the arguments the hop actually passed."""
    from leviathan.graphrag import timeline as tl

    class _N:
        def __init__(self, nid, kind, ev):
            self.id, self.kind, self.contract, self.evidence = nid, kind, CORN, ev
    seen = {}

    def fake_eps(node, asof, *, evidence=None, **kw):
        seen[node] = {"asof": asof, "dates": [str((h or {}).get("date"))[:10] for h in (evidence or [])]}
        return [{"start": "2012-05-01", "end": "2012-09-01", "n": 4,
                 "receipt": {"date": "2012-07-14", "text": "drought spread across the belt"}}]

    def fake_retr(query, node, *, k, asof, near, **kw):
        seen["retr"] = {"node": node, "k": k, "asof": asof, "near": near}
        return [{"date": "2012-06-01", "source": "wb_cmo", "text": "a dated report"},
                {"date": "2099-01-01", "source": "future", "text": "must be dropped"}]

    monkeypatch.setattr(tl, "episodes_for", fake_eps)
    monkeypatch.setenv("GRAPHRAG_TIMELINE", "on")
    monkeypatch.setenv("GRAPHRAG_EXTREME_LOCATOR", "on")
    sg = _SG()
    sg.nodes = [_N("us_drought", "driver", [{"date": "2012-06-01", "text": "x"},
                                            {"date": "2099-01-01", "text": "leak"}]),
                _N(CORN, "contract", [{"date": "2012-05-01", "text": "y"}])]
    hop: dict = {"nodes": [], "episodes_per_node": {}, "receipts": 0, "ev_reads": 0, "declines": []}
    lines = an._extreme_hop_lines(sg, None, "when did corn peak", {"board": CORN},
                                  "2012-08-21", ASOF, retrieve=fake_retr, hop=hop)
    assert lines and lines[0].startswith("THE RECORD AROUND 2012-08-21")
    assert "never what was known then" in lines[0]             # the honesty sentence, on the block
    body = "\n".join(lines)
    assert cq.XL_HOP_LINE_RX.search(body)                      # the gate's own row shape is present
    assert "[N" not in body                                    # ZERO handles: the hop cites nothing
    assert tl.LINE_PREFIX not in body                          # and never wears the episodes prefix
    assert hop["ev_reads"] == 1 and hop["retrieved"] == 1       # one read; the future prop is dropped
    # TWO nodes render (the grounded driver FIRST, then the contract root as one labelled extra
    # whose window is EXPECTED to be a mega-window and is allowed to be), each with its own receipt.
    assert hop["nodes"] == ["us_drought", CORN] and hop["receipts"] == 2
    assert hop["spans"][CORN] == "2012-05..2012-09"
    # THE PIT PIN, read off what the hop actually passed: every evidence date it handed the timeline is
    # <= the located date, on the PUBLICATION axis, and the retrieval ran AT the located date.
    for node, call in seen.items():
        if node == "retr":
            assert call["asof"] == "2012-08-21" and call["near"] == "2012-08-21"
            continue
        assert call["asof"] == "2012-08-21"
        assert all(d <= "2012-08-21" for d in call["dates"]), (node, call["dates"])
    row = cq._xl_row_line(1, CORN, _row(818.0, "2012-08-21", "2012-12", "settlement",
                                        "US cents/bushel", "USD", 60000, "2010-06-06"),
                          direction="max")
    assert an._extreme_hop_block_on(row + "\n" + body) is True
    assert an._extreme_hop_block_on(body) is False             # never without a locator row


def test_p65_no_shipped_path_reads_a_held_out_ask_file_and_no_held_out_text_is_in_the_tree():
    """P55 / P65: THE HELD-OUT SET IS NOT MINE AND IT IS NOT LEAKED. The graded asks were authored by an
    independent agent blind to the frozen block; nothing in the shipped tree may read them, and no
    held-out question text may appear in the build, the tests or the prompt. The CALIBRATION corpus is a
    different object -- the designer may read it -- but it lives outside the repo too, so this pin is
    written as an ABSENCE over the whole shipped tree rather than as a load of either file."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    needle = "asks_" + "holdout"          # split so THIS file is not its own counter-example
    hits = []
    for sub in ("src", "tests"):
        for p in (root / sub).rglob("*.py"):
            t = p.read_text(encoding="utf-8", errors="ignore")
            if needle in t or ("asks_" + "calibration") in t:
                hits.append(str(p.relative_to(root)))
    assert hits == [], hits
    # ...and the frozen block itself carries no quoted question, by the cheap structural proxy the
    # freeze was measured under: not one question mark anywhere in it.
    assert "?" not in dp._xl_block(cq.XL_BOARD_LABEL)


# ══ THE FIX PASS (2026-09-04): ONE PIN PER REVIEWED FINDING ════════════════════════════════════════
# Each pin below NAMES its finding and REPRODUCES the measurement that found it, so the finding is
# closed by an assertion rather than by a claim. The order is the findings' own.
def test_fix_review_major_1_and_refute_major_2_the_windowed_fallback_never_spends_a_third_read():
    """REVIEW MAJOR 1 / REFUTE MAJOR 2 -- "XL_CAP BREACH, AND IT VIOLATES AN ARM THRESHOLD".

    MEASURED BEFORE THE FIX, with a counting `Q.run`: a windowed ask whose ROW W returned nothing
    (cascade.py:8950) or whose window was too thin (:8956) set `kind = 'extreme'`, so control FELL INTO
    the ROW B branch at :8972 and spent a THIRD read -- reads == 3, outcome 'fired' -- against a stated
    cap of 2 and a G9(l) threshold pinning `xl_reads <= 2` on EVERY fired row. Reachable on any stalled
    board and on any `since` after the last print. No pin covered it: the 850 fixture exercised exactly
    that path without counting.

    CLOSED BY TWO FENCES: `row_b_allowed`, latched from the kind AT ENTRY (the product half -- a
    trailing-window row is a scope the windowed ask never named), and `pay['reads'] < XL_CAP` on the ROW
    B branch (the budget half, deliberately redundant). Both are asserted here, on the CALL COUNTER."""
    q = _tape({(CORN, "max_row", None): [_row(831.25, "2012-08-21", "2012-12", "settlement",
                                              "US cents/bushel", "USD", 60000, "2010-06-06")]})
    cands, pay = cq._xl_locate(q, {"board": CORN, "direction": "max", "kind": "windowed_extreme",
                                   "since": "2020"}, ASOF)
    assert pay["reads"] == 2 and len(q.seen) == 2               # the READ is not spent, not just unused
    assert pay["reads"] <= cq.XL_CAP and cq.XL_CAP == 2
    assert len(cands) == 1 and cands[0]["since"] is None        # ROW A alone: the whole-record row
    assert [d["reason"] for d in pay["declines"]] == ["no_rows_in_window", "window_fallback_no_row_b"]
    # ...and the SAME latch on the thin-window fallback, the other branch that used to fall through
    real = cq.XL_MIN_WINDOW_ROWS
    q2 = _tape({(CORN, "max_row", None): [_row(831.25, "2012-08-21", "2012-12", "settlement",
                                               "US cents/bushel", "USD", 60000, "2010-06-06")],
                (CORN, "max_row", "2020-01-01"): [_row(818.0, "2022-04-29", "2022-07", "settlement",
                                                       "US cents/bushel", "USD", 3, "2020-01-02")]})
    try:
        cq.XL_MIN_WINDOW_ROWS = 4
        c2, p2 = cq._xl_locate(q2, {"board": CORN, "direction": "max",
                                    "kind": "windowed_extreme", "since": "2020"}, ASOF)
        assert p2["reads"] == 2 <= cq.XL_CAP and len(c2) == 1 and len(q2.seen) == 2
    finally:
        cq.XL_MIN_WINDOW_ROWS = real
    # THE CAP IS ENFORCED IN src, NOT ONLY IN A TEST DOCSTRING -- the review's own words.
    body = inspect.getsource(cq._xl_locate)
    assert "row_b_allowed = (kind == \"extreme\")" in body
    assert 'pay["reads"] < XL_CAP' in body
    # LATCHED BEFORE THE FIRST MUTATION SITE -- that ordering IS the fix
    assert body.index("row_b_allowed = ") < body.index('pay["kind"] = kind = "extreme"')
    # ...and on EVERY path the leg can take, the ceiling holds
    for req in ({"kind": "extreme"}, {"kind": "extreme", "scope": "all_time"},
                {"kind": "windowed_extreme", "since": "2020"},
                {"kind": "windowed_extreme", "since": "the last five years"},
                {"kind": "windowed_extreme", "since": "1995"}):
        _c, p = cq._xl_locate(q2, dict({"board": CORN, "direction": "max"}, **req), ASOF)
        assert p["reads"] <= cq.XL_CAP, (req, p["reads"])


def test_fix_review_major_2_the_window_floor_kill_is_enforced_not_remembered(monkeypatch):
    """REVIEW MAJOR 2 -- "A KILL CONDITION IS CLAIMED ENFORCED AND IS NOT".

    MEASURED BEFORE THE FIX: `cascade.py:8545` asserted that `answer._xl_kinds_served()` REFUSES to arm
    the windowed sub-flag while `XL_MIN_WINDOW_ROWS` is None (the K32 kill). It read only
    XL_KIND_EXTREME / XL_KIND_WINDOWED and never looked at the constant -- with both sub-flags on and the
    floor None it returned ('extreme', 'windowed_extreme'), so the windowed lane armed with
    `window_too_thin` INERT, which is the exact flip-time kill the docstring promised to block.

    CLOSED: a third named refusal, `xl_window_floor_uncalibrated`, beside the two that already raise.
    Both halves are pinned -- it raises while the floor is None, and it serves once the floor exists."""
    monkeypatch.setenv("XL_KIND_EXTREME", "on")
    monkeypatch.setenv("XL_KIND_WINDOWED", "on")
    assert cq.XL_MIN_WINDOW_ROWS is None                       # the shipped state, PENDING G0b
    with pytest.raises(ValueError) as e:
        an._xl_kinds_served()
    assert "xl_window_floor_uncalibrated" in str(e.value)
    real = cq.XL_MIN_WINDOW_ROWS
    try:
        cq.XL_MIN_WINDOW_ROWS = 20                             # the census has run -> the pair serves
        assert an._xl_kinds_served() == cq.XL_KINDS
    finally:
        cq.XL_MIN_WINDOW_ROWS = real
    # THE CALLERS READ THE RAISE AS "THE LANE DOES NOT ARM", never as a turn failure -- fail-closed, so
    # the flip-time kill costs a dark lane and not a broken turn.
    src = inspect.getsource(orc)
    assert src.count("except ValueError:") >= 2 and "_xlk = ()" in src
    assert "xl_window_floor_uncalibrated" in inspect.getdoc(an._xl_kinds_served)


def test_fix_review_major_3_and_refute_major_3_the_threshold_alias_ships_its_fence():
    """REVIEW MAJOR 3 / REFUTE MAJOR 3 -- "K27c IS NEITHER BUILT NOR DECLARED MISSING" and "THE
    THRESHOLD ALIAS SHIPS WITH ITS ONLY FENCE MISSING, UNDISCLOSED".

    MEASURED BEFORE THE FIX: `_SYSTEM_EXTREME_LOCATOR_MANDATE` carried no clause banning the echoed
    numeral or the yes/no verdict (K27b), and no `xl_threshold_echo` / `xl_threshold_verdict` /
    `xl_window_duration_gloss` column existed anywhere in eval.py (K27c) -- so G9(m/m2/n) could not
    compute its own kills, and the alias's whole safety argument was a structural cut plus nothing on the
    one surface the cut cannot reach. The refuter's sentence 'It has: CBOT corn settled at 849 on
    2012-08-21 [N1].' returned None from `_check_number_handle`: the shipped verifier does not charge it.

    CLOSED: the two prohibitions in the PERSONA mandate (which leaves the planner's frozen block, and
    its measurement, untouched) and the three counters, SCOPED to locator-cited sentences via
    `verify._claim_numbers_in` + `_num_backed` at scale 1 -- the scoping K27c specifies."""
    m = an._SYSTEM_EXTREME_LOCATOR_MANDATE
    assert "never write that level as a number" in m
    assert "never state a yes-or-no verdict" in m
    assert "let the reader make the comparison" in m
    # the FROZEN PLANNER BLOCK is untouched by this clause -- persona text, not prompt text
    assert hashlib.sha256(dp._xl_block(cq.XL_BOARD_LABEL).encode("utf-8")).hexdigest() == (
        cq.XL_BLOCK_SHA256)
    cit_row = {"id": "N1", "kind": "number",
               "locator": {"metric": cq.XL_METRIC, "located_date": "2012-08-21"},
               "payload": {"rows": [{"value": 849.0, "knowledge_date": "2012-08-21"}]}}
    bad = {"citations": [cit_row], "answer": "", "trace": {}, "intent_decision": {},
           "structured": {"tldr": "It has: CBOT corn settled at 849 on 2012-08-21 [N1]. "
                                  "Yes, it has been above 800 [N1].",
                          "mechanism": "Over the past five years it never went above 800 [N1]."}}
    st = EV._cascade_stats(bad)
    assert st["xl_threshold_echo"] == 2                        # the 800s; the served 849 is NOT charged
    assert st["xl_threshold_verdict"] == 2
    assert st["xl_window_duration_gloss"] == 1
    good = {"citations": [cit_row], "answer": "", "trace": {}, "intent_decision": {},
            "structured": {"tldr": "CBOT corn's highest settle was 849 on 2012-08-21 [N1], read from "
                                   "2010-06-06 to 2026-09-01.", "mechanism": ""}}
    sg_ = EV._cascade_stats(good)
    assert (sg_["xl_threshold_echo"], sg_["xl_threshold_verdict"],
            sg_["xl_window_duration_gloss"]) == (0, 0, 0)
    # SCOPED: the same prose with NO locator citation charges nothing to this lane, on either arm
    un = copy.deepcopy(bad)
    un["citations"] = []
    un2 = EV._cascade_stats(un)
    assert (un2["xl_threshold_echo"], un2["xl_threshold_verdict"],
            un2["xl_window_duration_gloss"]) == (0, 0, 0)
    # ...and all three REACH THE ARTIFACT: a counter that reaches no record cannot compute a kill
    rec = inspect.getsource(EV).split("D-XL (E34): the SAME hard-whitelist projection")[1][:4000]
    for col in ("xl_threshold_echo", "xl_threshold_verdict", "xl_window_duration_gloss"):
        assert f'"{col}": cs.get("{col}")' in rec, col


def test_fix_refute_major_1_the_hop_anchors_on_the_row_the_answer_leads_with():
    """REFUTE MAJOR 1 -- "THE HOP ANCHORS THE WRONG ROW ON THE WINDOWED KIND".

    MEASURED BEFORE THE FIX: ask 'highest since 2020', ROW W = 818 on 2022-04-29 renders [N1] and ROW A
    = 849 on 2012-08-21 renders [N2], but `pay['located_date']` is ROW A's 2012-08-21 and answer.py:3491
    read that key alone -- so the hop block was headed 'THE RECORD AROUND 2012-08-21' and the mandate
    made the writer narrate 'AT THAT TIME' for a date that is not the answer's. `window_located_date`
    already held the right date and was never used.

    CLOSED: the seam prefers `window_located_date` and falls back to `located_date`. The fallback needs
    no branch -- the windowed declines never write that key, so a fallback keeps ROW A's date."""
    q = _tape({(CORN, "max_row", None): [_row(849.0, "2012-08-21", "2012-12", "settlement",
                                              "US cents/bushel", "USD", 60000, "2010-06-06")],
               (CORN, "max_row", "2020-01-01"): [_row(818.0, "2022-04-29", "2022-07", "settlement",
                                                      "US cents/bushel", "USD", 1842, "2020-01-02")]})
    cands, pay = cq._xl_locate(q, {"board": CORN, "direction": "max", "kind": "windowed_extreme",
                                   "since": "2020"}, ASOF)
    assert [c["since"] for c in cands] == ["2020", None]        # ROW W is [N1], ROW A the tape anchor
    assert pay["window_located_date"] == "2022-04-29" and pay["located_date"] == "2012-08-21"
    seam = inspect.getsource(an._answer_l2)
    assert '_xl_pay.get("window_located_date") or _xl_pay.get("located_date")' in seam
    assert '_xl_hop["anchor"]' in seam
    # ...and on a FALLBACK there is no window date, so the anchor is ROW A's -- by construction
    q2 = _tape({(CORN, "max_row", None): [_row(849.0, "2012-08-21", "2012-12", "settlement",
                                               "US cents/bushel", "USD", 60000, "2010-06-06")]})
    _c2, p2 = cq._xl_locate(q2, {"board": CORN, "direction": "max", "kind": "windowed_extreme",
                                 "since": "2020"}, ASOF)
    assert "window_located_date" not in p2 and p2["located_date"] == "2012-08-21"


def test_fix_refute_major_4_every_windowed_fallback_tells_the_reader_the_floor_was_dropped():
    """REFUTE MAJOR 4 -- "A NAMED WINDOW DECLINE NEVER REACHES THE READER".

    MEASURED BEFORE THE FIX: only `window_straddles_coverage` rendered. On `since_unparseable`,
    `window_too_short`, `no_rows_in_window` and `window_too_thin` the kind fell to 'extreme' and the
    WHOLE-TAPE row shipped with `since=None` -- so the mandate's 'echo the starting point the question
    gave' clause was vacuous and nothing told the reader the floor had been dropped. A compliant writer
    answers 'highest since 2020' with the 2012 tape-wide high.

    CLOSED: `XL_RENDERED_DECLINES` plus `_xl_notes`, whose test is the payload's OWN pair of kinds --
    so the guarantee is TOTAL (every fallback renders exactly one note, including a fallback whose cause
    was a raise, which renders the scope sentence alone) rather than per-reason."""
    for reason in cq.XL_RENDERED_DECLINES:
        pay = {"label": "CBOT corn", "kind_requested": "windowed_extreme", "kind": "extreme",
               "declines": [{"reason": reason, "floor": "2010-06-06"}]}
        n = cq._xl_notes(pay)
        assert len(n) == 1 and n[0].startswith("PRICE EXTREME NOTE CBOT corn: ")
        assert cq.XL_DECLINE_TEMPLATES[reason] in n[0] and n[0].endswith(cq.XL_SCOPE_NOTE_TAIL)
        assert cq._xl_register_fence(n), reason                 # it must clear the fence it rides
    # a fallback whose cause is a RAISE still tells the reader the scope moved
    n_err = cq._xl_notes({"label": "CBOT corn", "kind_requested": "windowed_extreme",
                          "kind": "extreme", "declines": [{"reason": "error"}]})
    assert n_err == [f"PRICE EXTREME NOTE CBOT corn: {cq.XL_SCOPE_NOTE_TAIL}"]
    # ...and NOTHING renders when the windowed row SERVED, or on a plain extreme ask
    assert cq._xl_notes({"label": "x", "kind_requested": "windowed_extreme",
                         "kind": "windowed_extreme", "declines": []}) == []
    assert cq._xl_notes({"label": "x", "kind_requested": "extreme", "kind": "extreme",
                         "declines": [{"reason": "recent_equals_alltime"}]}) == []
    # END TO END: the rendered block carries the note ABOVE exactly one row
    q = _tape({(CORN, "max_row", None): [_row(849.0, "2012-08-21", "2012-12", "settlement",
                                              "US cents/bushel", "USD", 60000, "2010-06-06")]})
    sg, calls = _SG(), []
    lines, pay = cq._extreme_locator_leg_or_nothing(
        sg, None, {"board": CORN, "direction": "max", "kind": "windowed_extreme", "since": "1995"},
        q, ASOF, calls)
    assert lines[0].startswith("PRICE EXTREME NOTE") and lines[0].endswith(cq.XL_SCOPE_NOTE_TAIL)
    assert sum(1 for ln in lines if ln.startswith("- [N")) == 1        # SINGULAR, as the note says
    assert pay["outcome"] == "fired"
    # AND THE LINT CLAUSE THAT GUARDS IT HAS TEETH, both legs, injected and read back red
    real_tail, real_set = cq.XL_SCOPE_NOTE_TAIL, cq.XL_RENDERED_DECLINES
    try:
        cq.XL_SCOPE_NOTE_TAIL = "see corn_cbot for the figure below."  # a RAW SLUG: internal_leaks
        assert any("does not clear the register fence" in e for e in cc.check_extreme_locator())
        cq.XL_SCOPE_NOTE_TAIL = real_tail
        cq.XL_RENDERED_DECLINES = real_set + ("not_a_reason",)
        assert any("has no reader sentence" in e for e in cc.check_extreme_locator())
        # ...and the producer FAILS SOFT on that same drift rather than costing the reader the block
        assert cq._xl_notes({"label": "x", "kind_requested": "windowed_extreme", "kind": "extreme",
                             "declines": [{"reason": "not_a_reason"}]}) == [
            f"PRICE EXTREME NOTE x: {cq.XL_SCOPE_NOTE_TAIL}"]
    finally:
        cq.XL_SCOPE_NOTE_TAIL, cq.XL_RENDERED_DECLINES = real_tail, real_set
    assert cc.check_extreme_locator() == []


def test_fix_refute_major_5_xl_date_cited_no_longer_convicts_a_fresh_record():
    """REFUTE MAJOR 5 -- "xl_date_cited CONVICTS A LEGITIMATE FRESH RECORD".

    MEASURED BEFORE THE FIX: the column was `located_date != span_end`, and eval.py:1176/1319 pin it as
    'the FATAL this leg exists to prevent'. A cocoa payload with located_date == span_end == 2026-09-01
    -- the board's extreme IS its newest print, a common shape at record highs -- returned False, so a
    CORRECT turn failed the deck pin. Two payload fields that are legitimately equal cannot tell 'the
    clock was stamped as the series end' from 'the extreme is the last print'.

    CLOSED: the column reads the CITATION's own `located_date` rider against the SERVED ROW's own
    `knowledge_date` -- which is the defect's actual shape, and is False exactly when the clock is
    wrong."""
    fresh = {"citations": [_xl_cit(located="2026-09-01", kd="2026-09-01", value=500.0)],
             "answer": "", "structured": {"tldr": "", "mechanism": ""}, "intent_decision": {},
             "trace": {"quantify_extreme_locator": {"outcome": "fired", "kind": "extreme",
                                                    "kind_requested": "extreme",
                                                    "located_date": "2026-09-01",
                                                    "span_end": "2026-09-01"}}}
    st = EV._cascade_stats(fresh)
    assert st["xl_located_date"] == st["xl_span_end"] == "2026-09-01"
    assert st["xl_date_cited"] is True                         # the record IS the last print: correct
    # the defect itself, still caught: the citation clock is NOT the served row's own session
    wrong = copy.deepcopy(fresh)
    wrong["citations"] = [_xl_cit(located="2026-09-01", kd="2012-08-21", value=500.0)]
    assert EV._cascade_stats(wrong)["xl_date_cited"] is False
    # an absent rider is the PRE-D-XL shape and is not credited (fail-closed)
    bare = copy.deepcopy(fresh)
    bare["citations"][0]["locator"].pop("located_date")
    assert EV._cascade_stats(bare)["xl_date_cited"] is False
    assert EV._cascade_stats({"citations": [], "structured": None, "answer": "",
                              "trace": {}})["xl_date_cited"] is False


def test_fix_refute_major_6_an_outage_is_never_worded_as_a_coverage_fact():
    """REFUTE MAJOR 6 -- "AN OUTAGE IS COUNTED AND WORDED AS A COVERAGE FACT".

    MEASURED BEFORE THE FIX: `_xl_read` swallowed every exception and returned None, and the caller then
    declined `no_rows`, whose reader sentence is 'no priced print was returned for this board at this
    cutoff'. With a qfn raising RuntimeError('athena throttled'), declines == ['no_rows'] -- an outage
    counted and worded as a tape gap, in the census the 'declines are named and counted' law exists to
    make trustworthy.

    CLOSED: `_xl_read` returns a `_XlReadFailure` sentinel for a RAISE and None for NO ROWS, and every
    call site branches on the sentinel FIRST. The raise is CLASSIFIED against the query layer's own
    messages, so the two card-axis names are surfaced rather than demoted to `error`."""
    def throttled(sql):
        raise RuntimeError("athena throttled")
    _c, pay = cq._xl_locate(throttled, {"board": SLUG, "direction": "max", "kind": "extreme"}, ASOF)
    assert [d["reason"] for d in pay["declines"]] == ["error"]
    assert pay["declines"][0]["at"] == "row_a" and pay["reads"] == 1   # attempted, so charged
    # ...and NO ROWS is still `no_rows`: the two states are distinguished, not merged the other way
    _c2, pay2 = cq._xl_locate(_tape({}), {"board": SLUG, "direction": "max", "kind": "extreme"},
                              ASOF)
    assert [d["reason"] for d in pay2["declines"]] == ["no_rows"]
    assert cq._xl_read(_tape({}), slug=SLUG, asof=ASOF, agg="max_row") is None
    r = cq._xl_read(throttled, slug=SLUG, asof=ASOF, agg="max_row")
    assert isinstance(r, cq._XlReadFailure) and r.reason == "error"


def test_fix_review_minor_1_the_two_window_misses_carry_two_names():
    """REVIEW MINOR 1 -- "ONE DECLINE NAME, TWO DIFFERENT FACTS".

    MEASURED BEFORE THE FIX: `no_rows_in_window` was appended by BOTH the ROW W miss and the ROW B miss,
    distinguished only by payload key (`since` vs `window_start`) -- so on a windowed fallback one turn
    recorded it twice and the counted, closed decline enum could not separate 'the ask's named window was
    empty' from 'the trailing recency window was empty'.

    CLOSED: `no_rows_in_recent_window` for the ROW B branch, in the templates and in the closed-vocabulary
    pin. (The two can no longer co-occur at all, because the latch stops ROW B on a fallback -- so the
    pin asserts each name on its own branch.)"""
    q = _tape({(CORN, "max_row", None): [_row(849.0, "2012-08-21", "2012-12", "settlement",
                                              "US cents/bushel", "USD", 60000, "2010-06-06")]})
    _c, p_b = cq._xl_locate(q, {"board": CORN, "direction": "max", "kind": "extreme"}, ASOF)
    assert [d["reason"] for d in p_b["declines"]] == ["no_rows_in_recent_window"]
    assert p_b["declines"][0]["window_start"] == (
        dt.date.fromisoformat(ASOF) - dt.timedelta(days=cq.XL_RECENT_DAYS)).isoformat()
    _c2, p_w = cq._xl_locate(q, {"board": CORN, "direction": "max", "kind": "windowed_extreme",
                                 "since": "2020"}, ASOF)
    assert "no_rows_in_window" in [d["reason"] for d in p_w["declines"]]
    assert "no_rows_in_recent_window" not in [d["reason"] for d in p_w["declines"]]
    assert cq.XL_DECLINE_TEMPLATES["no_rows_in_window"] != (
        cq.XL_DECLINE_TEMPLATES["no_rows_in_recent_window"])


def test_fix_review_minor_3_the_omit_when_none_idiom_holds_at_both_call_sites():
    """REVIEW MINOR 3 -- "THE OMIT-WHEN-NONE IDIOM IS BROKEN AT TWO CALL SITES".

    MEASURED BEFORE THE FIX: orchestrator.py:2789 and :2796 passed `xl_request=xl_request`
    UNCONDITIONALLY, while the same commit calls that idiom load-bearing for `plan_turn` -- 'an injected
    planner_sys fake written against the pre-D-XL signature must stay valid'. So an injected
    `run_hybrid` / `run_reasoning` fake with the older signature broke EVEN FLAG-OFF, and the g1x
    golden's `signatures` section is prefix-only and cannot see a call site at all.

    CLOSED: one conditional kwarg dict resolved beside `_rck`, expanded at both sites. REPRODUCED here
    by calling a PRE-D-XL-signature fake with the kwargs the seam builds."""
    src = inspect.getsource(orc)
    assert '_xlr = {"xl_request": xl_request} if xl_request is not None else {}' in src
    assert "xl_request=xl_request" not in src.split("_xlr = ")[1]   # neither call site passes it raw
    assert src.count("**_xlr") == 2

    def pre_dxl_fake(query, asof, **kw):                       # the older signature, verbatim in shape
        assert "xl_request" not in kw, "the pre-D-XL fake was handed a D-XL keyword"
        return {"ok": True}
    for xl_request in (None,):
        _xlr = {"xl_request": xl_request} if xl_request is not None else {}
        assert pre_dxl_fake("q", ASOF, **_xlr) == {"ok": True}
    on = {"xl_request": {"board": CORN}}
    _xlr_on = {"xl_request": on["xl_request"]} if on["xl_request"] is not None else {}
    assert list(_xlr_on) == ["xl_request"]                     # ...and present when a request exists


def test_fix_review_minor_4_the_lint_clause_can_fail_in_both_directions(monkeypatch):
    """REVIEW MINOR 4 -- "A LINT CLAUSE THAT CANNOT FAIL".

    MEASURED BEFORE THE FIX: `if not an._extreme_locator_block_on(_hop_ok) is False:` is vacuous in BOTH
    flag states -- `_hop_ok` is a HOP line, so `XL_ROW_LINE_RX` never matches it and the gate returns
    False whether or not GRAPHRAG_EXTREME_LOCATOR is on. Its message named a fact it did not test.

    CLOSED: the two legs are asserted separately on the ENGINE'S OWN rendered ROW line -- OFF must be
    False, ON must be True -- with the hop-line case kept as a third, distinct clause. The lint restores
    the ambient flag in a finally, so it is safe to call from any runner."""
    lint = _code_only(inspect.getsource(cc.check_extreme_locator))
    assert "not an._extreme_locator_block_on(_hop_ok) is False" not in lint
    assert 'os.environ["GRAPHRAG_EXTREME_LOCATOR"] = "on"' in lint and "_row_probe" in lint
    monkeypatch.setenv("GRAPHRAG_EXTREME_LOCATOR", "on")
    assert cc.check_extreme_locator() == []
    assert os.environ["GRAPHRAG_EXTREME_LOCATOR"] == "on"       # the ambient value is RESTORED
    monkeypatch.delenv("GRAPHRAG_EXTREME_LOCATOR")
    assert cc.check_extreme_locator() == []
    assert "GRAPHRAG_EXTREME_LOCATOR" not in os.environ
    # ...and the clause has TEETH: break the gate's evidence leg and the lint reds
    real = cq.XL_ROW_LINE_RX
    try:
        cq.XL_ROW_LINE_RX = re.compile(r"^(?!x)x")             # matches nothing at all
        errs = cc.check_extreme_locator()
        assert any("did NOT arm" in e for e in errs), errs
    finally:
        cq.XL_ROW_LINE_RX = real


def test_fix_review_minor_6_the_seam_re_anchor_cuts_named_line_sets():
    """REVIEW MINOR 6 -- "THE SEAM RE-ANCHOR CUTS A RANGE, NOT A LINE SET".

    MEASURED BEFORE THE FIX: the producer recovered the pre-build seam block by deleting everything from
    the XL comment through the `_eod_kw = ...` line as ONE span -- so anything inserted ANYWHERE inside
    that range escaped the `sans_xl_sha256` join, and 'E16 inserted a kwarg and moved nothing else' was
    measured only at the range's two edges.

    CLOSED: two named cuts, each from its own leading comment to its own final assignment, each anchor
    asserted unique and ordered. The two are contiguous in the shipped source, so `sans` is byte-identical
    and the bank is UNMOVED -- a tightening, not a re-banking (verified: sans_xl_sha256 still 2b4407f4)."""
    import pathlib
    prod = (pathlib.Path(__file__).resolve().parents[2] / "data" / "consequence_leg"
            / "xl_golden_seam_bank.py").read_text(encoding="utf-8")
    assert "XL_INSERTS = (" in prod and "XL_INSERT_START" not in prod
    assert prod.count("for _start, _end in XL_INSERTS:") == 1
    assert "XL insert start anchor is not unique" in prod and "anchors are inverted" in prod
    assert '"xl_insert_cuts": n_cuts' in prod
    # BOTH insertions are named, and BOTH are present in the shipped seam -- so both cuts fire
    seam = inspect.getsource(an._answer_l2)
    for start, end in (("# D-XL: the seam CONSUMES the request the orchestrator already resolved",
                        '_xl_kw = {"extreme_locator": _xl_req}'),
                       ("# THE EXTREMA-CLOCK REPAIR, BUILT DARK",
                        '_eod_kw = {"extrema_own_date": True} if _extrema_own_date_on() else {}')):
        assert seam.count(start) == 1 and seam.count(end) == 1
        assert seam.index(start) < seam.index(end)


def test_fix_refute_minor_2_the_exactness_columns_read_the_asks_own_kind():
    """REFUTE MINOR 2 -- "xl_kind_exact CONFOUNDS A DECLINE WITH A PLANNER MISMATCH".

    MEASURED BEFORE THE FIX: eval.py:574 compared the ENGINE payload's `kind` against the dispatch
    decision's, but the fallback MUTATES `pay['kind']` to 'extreme' -- so a legitimate
    `window_straddles_coverage` turn scored xl_kind_exact False while xl_since_exact went None, and an
    arm gating either at 1.0 failed on EVERY straddle.

    CLOSED: `kind_requested` is preserved at entry to `_xl_locate` and both columns read it. The
    fallback stays visible in `xl_kind` and in `xl_declines`, where it belongs."""
    pay = {"outcome": "fired", "kind": "extreme", "kind_requested": "windowed_extreme",
           "board": CORN, "direction": "max", "since": "2020", "located_date": "2012-08-21",
           "span_end": "2026-09-01", "reads": 2,
           "declines": [{"reason": "window_straddles_coverage"},
                        {"reason": "window_fallback_no_row_b"}]}
    out = {"citations": [], "answer": "", "structured": {"tldr": "", "mechanism": ""},
           "trace": {"quantify_extreme_locator": pay},
           "intent_decision": {"extreme_locator": {"board": CORN, "direction": "max",
                                                   "kind": "windowed_extreme", "since": "2020"}}}
    st = EV._cascade_stats(out)
    assert st["xl_kind_exact"] is True                          # the PLANNER did not mismatch
    assert st["xl_since_exact"] is True                         # ...and the floor was echoed exactly
    assert st["xl_kind"] == "extreme" and st["xl_kind_requested"] == "windowed_extreme"
    assert "window_straddles_coverage" in st["xl_declines"]
    # a REAL planner mismatch is still caught
    bad = copy.deepcopy(out)
    bad["intent_decision"]["extreme_locator"]["kind"] = "extreme"
    assert EV._cascade_stats(bad)["xl_kind_exact"] is False


def test_fix_refute_minor_3_the_alias_scope_rule_is_enforced_on_both_sides():
    """REFUTE MINOR 3 -- "THE ALIAS SCOPE RULE IS ENFORCED ON ONE SIDE ONLY".

    MEASURED BEFORE THE FIX: `dispatch._validate` forces `xl_scope=None` on `windowed_extreme` and the
    engine relied on that BY COMMENT -- calling `_xl_locate` directly with kind='windowed_extreme',
    scope='all_time' and an empty ROW W left the request's scope live, so `scope_all_time_no_row_b` fired
    after the fallback. The family amendment required the rule on BOTH the emission and the expectation
    side.

    CLOSED: `scope` is forced None at the top of `_xl_locate`, before any branch can read it."""
    q = _tape({(CORN, "max_row", None): [_row(849.0, "2012-08-21", "2012-12", "settlement",
                                              "US cents/bushel", "USD", 60000, "2010-06-06")]})
    _c, pay = cq._xl_locate(q, {"board": CORN, "direction": "max", "kind": "windowed_extreme",
                                "since": "2020", "scope": "all_time"}, ASOF)
    assert pay["scope"] is None
    assert "scope_all_time_no_row_b" not in [d["reason"] for d in pay["declines"]]
    # ...and the EMISSION side still forces it too -- one rule, both sides
    p = dp._validate({"steps": ["reasoning"], "contracts": [], "price_extreme": True,
                      "xl_kind": "windowed_extreme", "xl_board": CORN, "xl_direction": "max",
                      "xl_since": "2020", "xl_scope": "all_time", "xl_confidence": "high"},
                     {CORN}, 2, cq.XL_BOARD_LABEL, cq.XL_KINDS)
    assert p.xl_scope is None
    # the EXTREME kind is untouched: all_time still suppresses ROW B there, before the read
    _c2, p2 = cq._xl_locate(q, {"board": CORN, "direction": "max", "kind": "extreme",
                                "scope": "all_time"}, ASOF)
    assert p2["scope"] == "all_time" and p2["reads"] == 1
    assert [d["reason"] for d in p2["declines"]] == ["scope_all_time_no_row_b"]


def test_fix_refute_minor_6_a_contentless_hop_block_never_ships(monkeypatch):
    """REFUTE MINOR 6 -- "A CONTENTLESS HOP BLOCK CAN STILL SHIP".

    MEASURED BEFORE THE FIX: `_extreme_hop_lines` returned `lines` when `len(lines) > 1`, and the RECORD
    FLOOR sentence appended at the tail IS a second line -- so with zero episodes and zero retrieved
    props the block entered the volatile prompt as a header plus a floor sentence, un-fenced and carrying
    no hop row at all.

    CLOSED: a content counter incremented at the APPEND SITES (a hop row, or a retrieved report), so the
    gate cannot drift from what was actually appended. A REPORTS-only block is content and ships -- it
    recounts real dated reports, and the hop MANDATE stays off there anyway because
    `_extreme_hop_block_on` keys on the hop ROW SHAPE."""
    class _N:
        def __init__(self, nid, kind, ev):
            self.id, self.kind, self.contract, self.evidence = nid, kind, CORN, ev
    monkeypatch.delenv("GRAPHRAG_TIMELINE", raising=False)      # no episodes...
    sg = _SG()
    sg.nodes = [_N(CORN, "contract", [{"date": "2011-01-01", "text": "x"}])]
    hop = {"nodes": [], "episodes_per_node": {}, "receipts": 0, "ev_reads": 0, "declines": []}
    lines = an._extreme_hop_lines(sg, None, "q", {"board": CORN}, "2012-08-21", ASOF,
                                  retrieve=lambda *a, **k: [], hop=hop)   # ...and no props
    assert lines == []
    assert "no_hop_content" in [d["reason"] for d in hop["declines"]]
    assert "timeline_off" in [d["reason"] for d in hop["declines"]]
    # ONE retrieved report IS content, and it ships without arming the hop mandate
    hop2 = {"nodes": [], "episodes_per_node": {}, "receipts": 0, "ev_reads": 0, "declines": []}
    lines2 = an._extreme_hop_lines(
        sg, None, "q", {"board": CORN}, "2012-08-21", ASOF, hop=hop2,
        retrieve=lambda *a, **k: [{"date": "2012-06-01", "source": "wb_cmo", "text": "a report"}])
    assert len(lines2) == 2 and lines2[1].startswith("REPORTS AROUND")
    assert cq.XL_HOP_LINE_RX.search("\n".join(lines2)) is None      # no hop row -> no hop mandate
    body = inspect.getsource(an._extreme_hop_lines)
    assert "n_content += 1" in body and "if not n_content:" in body
    assert "len(lines) > 1" not in _code_only(body)      # the old gate is GONE from the code


def test_fix_refute_minor_7_the_two_card_axis_declines_are_surfaced_not_swallowed():
    """REFUTE MINOR 7 -- "TWO DECLINE NAMES ARE STRUCTURALLY UNREACHABLE".

    MEASURED BEFORE THE FIX: `vintage_card` and `extrema_axis_unavailable` were in the templates but
    XL_TABLE is fixed to silver_futures_eod, so `build_sql`'s knowledge_semantics raise and
    `_extreme_window`'s date_col raise were caught by `_xl_read` and reported as `no_rows` -- absence
    credited as a pass, inside the counter whose stated job is a visible boundary.

    CLOSED by the remedy's FIRST option -- surface `build_sql`'s raise reason. `_xl_read_reason`
    classifies against the messages the SHIPPED query layer actually raises (both are driven here, so a
    message edit reds this pin rather than silently demoting a named boundary to `error`), and the whole
    path is exercised end to end by pointing XL_TABLE at a vintage card."""
    ts = _card("silver_wasde")
    with pytest.raises(ValueError) as e1:
        Q.build_sql(Q.NumberQuery(table="silver_wasde", metric=sorted(ts.metrics)[0], asof=ASOF,
                                  commodity="corn", agg="max_row"), ts)
    assert cq._xl_read_reason(e1.value) == "vintage_card"
    naked = copy.deepcopy(_card())
    naked.date_col = None
    with pytest.raises(ValueError) as e2:
        Q._extreme_window(naked, "settle")
    assert cq._xl_read_reason(e2.value) == "extrema_axis_unavailable"
    assert cq._xl_read_reason(RuntimeError("athena throttled")) == "error"
    # END TO END: the leg declines by NAME, spends its one read, and never says `no_rows`
    real = cq.XL_TABLE
    try:
        cq.XL_TABLE = "silver_wasde"
        _c, pay = cq._xl_locate(_tape({}), {"board": SLUG, "direction": "max", "kind": "extreme"},
                                ASOF)
        assert [d["reason"] for d in pay["declines"]] == ["vintage_card"]
        assert pay["reads"] == 1
    finally:
        cq.XL_TABLE = real
    # `extrema_axis_unavailable` has a SECOND producer, named at the mint: the extrema-clock rider's
    # own decline at the derived lane's ordinal-when-thin rung. One name, one reader sentence.
    from leviathan.graphrag.numbers import derived as dv
    assert "extrema_axis_unavailable" in inspect.getsource(dv.su_standing)


def test_fix_refute_minor_8_the_suppressed_reason_enum_is_bound_to_its_producer():
    """REFUTE MINOR 8 -- "suppressed_reason IS A CLOSED ENUM WITH NO CONSTANT".

    MEASURED BEFORE THE FIX: `_extreme_locator_decision` spells nine reasons as inline literals, and
    nothing in `check_extreme_locator` or the suite bound the set -- so a tenth could appear with no lint
    noticing, while eval lifts the dict WHOLE through DECISION_RECORD_KEYS and a drifted name reaches the
    artifact silently.

    CLOSED: the constant is PUBLIC (`orchestrator.XL_SUPPRESSED_REASONS`) and clause (11) of the lint
    parses the producer's own source for its literals, asserting SET and FIRST-BLOCKER ORDER. The pin
    injects a drift and reads the lint back red."""
    src = inspect.getsource(orc._extreme_locator_decision)
    spelled = re.findall(r'out\["suppressed_reason"\]\s*=\s*"([a-z_]+)"', src)
    assert list(dict.fromkeys(spelled)) == list(orc.XL_SUPPRESSED_REASONS)
    assert len(orc.XL_SUPPRESSED_REASONS) == 9
    assert cc.check_extreme_locator() == []
    real = orc.XL_SUPPRESSED_REASONS
    try:
        orc.XL_SUPPRESSED_REASONS = real + ("a_tenth_reason",)     # the drift the clause exists for
        errs = cc.check_extreme_locator()
        assert any("XL_SUPPRESSED_REASONS" in e for e in errs), errs
        orc.XL_SUPPRESSED_REASONS = ("lane",) + tuple(r for r in real if r != "lane")
        assert any("ORDER" in e for e in cc.check_extreme_locator())   # order is bound too
    finally:
        orc.XL_SUPPRESSED_REASONS = real


def test_fix_the_flag_off_artifact_shape_is_declared_key_by_key():
    """REVIEW MINOR 5 / REFUTE MINOR 9 -- "FLAG-OFF ARTIFACT SHAPE MOVES, DECLARED BUT NOT IN THE LAW".

    NO CODE FIX, BY BOTH REVIEWERS' OWN REMEDY ('none needed if the deviation is accepted -- state it in
    the flip note'). What this pin adds is the thing a prose declaration cannot give: the EXACT key list,
    enumerated from the shipped projection, so a banked-artifact diff on these keys can be read against a
    checked list rather than against a memory. SERVING BYTES ARE UNMOVED -- that is what the three
    goldens hold; only the eval ROW SHAPE gains keys, on every run, flag-off included."""
    row = EV._cascade_stats({"citations": [], "structured": None, "answer": "", "trace": {}})
    xl_keys = sorted(k for k in row if k.startswith("xl_"))
    assert xl_keys == [
        "xl_board", "xl_board_exact", "xl_date_cited", "xl_date_in_prose", "xl_declines",
        "xl_direction", "xl_direction_exact", "xl_hop_declines", "xl_hop_episodes",
        "xl_hop_ev_reads", "xl_hop_gap_days", "xl_hop_nodes", "xl_hop_receipts",
        "xl_hop_rendered", "xl_hop_retr_injected",
        "xl_kind", "xl_kind_exact", "xl_kind_requested", "xl_located_date", "xl_n_prints",
        "xl_outcome", "xl_reads", "xl_recent_rendered", "xl_rendered", "xl_rows_fenced", "xl_scope",
        "xl_since", "xl_since_exact", "xl_span_end", "xl_span_start", "xl_threshold_echo",
        "xl_threshold_verdict", "xl_unspanned_superlative", "xl_window_duration_gloss"], xl_keys
    assert len(xl_keys) == 34
    # ...and every one of them is projected onto the RECORD too (the hard-whitelist law): a counter that
    # reaches no artifact cannot compute a kill.
    rec = inspect.getsource(EV).split("D-XL (E34): the SAME hard-whitelist projection")[1][:5000]
    for k in xl_keys:
        assert f'"{k}": cs.get("{k}")' in rec, k
    # THE FLAG-OFF ROW IS ALL-NEUTRAL: no key asserts anything about a lane that did not run.
    assert row["xl_rendered"] is False and row["xl_outcome"] is None and row["xl_reads"] == 0
    assert row["xl_threshold_echo"] == 0 and row["xl_unspanned_superlative"] == 0


# == FIX PASS 2 -- THE RE-REVIEW'S THREE NEW FINDINGS =================================================
def test_fix2_new_1_the_sentence_boundary_never_cuts_a_decimal_figure():
    r"""RE-REVIEW NEW 1 (MAJOR) -- "THE D-XL SENTENCE SPLITTER CUTS INSIDE A DECIMAL FIGURE, AND BOTH
    NEW COUNTERS RIDE ON IT".

    MEASURED BEFORE THE FIX, on the suite's OWN canonical row (soybean_meal_cbot, value 554.4, rendered
    '554.4' by the shipped `citations._fmt`). Both `eval._XL_SENT_RX` and `answer._XL_SENTENCE_RX` were
    `re.compile(r"[^.!?]+[.!?]?")`, which needs no whitespace after the terminator:
      (a) EVAL. The FULLY COMPLIANT transcription "CBOT soybean meal's highest settle was 554.4
          USD/short ton on 2022-04-19 [N1], read from 2010-06-06 to 2026-09-01." split at the decimal
          point; the in-scope sentence became "4 USD/short ton ..."; no served row backs 4.0; and
          `xl_threshold_echo` -- the alias's declared ZERO-TOLERANCE kill -- scored 1 ON A CORRECT
          ANSWER. Gating G9(m2) at 0 would have redded a compliant turn.
      (b) ANSWER. "Soybean meal's record high settle was 554.4 on 2022-04-19 [N1]." split into
          ["...was 554.", "4 on 2022-04-19 [N1]."] -- the SUPERLATIVE in the fragment with no handle and
          the HANDLE in the fragment with no superlative -- so the scoped `_count_unspanned_superlatives`
          read 0 while the SAME claim with an integer figure read 1. M5 went silent on the rows it
          polices, and `_fmt` keeps the decimal on every sub-1000 fractional board.

    CLOSED by deleting both hand-rolled regexes for the estate's own boundary: `verify._SENT_SPLIT` in
    eval and `register._SENT_ITER` in answer, which are the SAME pattern `(?<=[.!?;])\s+` and require
    WHITESPACE after the terminator -- the rule `verify._BOUND` states in the shipped verifier ("never a
    decimal point"). One mint site, the `_XL_SUPERLATIVE_RX` discipline applied to the splitter."""
    from leviathan.graphrag import verify as VF
    assert VF._SENT_SPLIT.pattern == reg._SENT_ITER.pattern == r"(?<=[.!?;])\s+"
    assert not hasattr(EV, "_XL_SENT_RX") and not hasattr(an, "_XL_SENTENCE_RX")
    # THE FORMATTER'S OWN REACH: which rendered figures the old regex would have cut
    assert [cit._fmt(v) for v in (554.4, 339.75, 68.42, 0.5)] == ["554.4", "339.75", "68.42", "0.5"]
    assert [cit._fmt(v) for v in (849.0, 1234.5, 11722.0)] == ["849", "1,234", "11,722"]

    # (a) EVAL -- the re-review's exact compliant sentence scores 0/0/0, and a real echo still scores
    prose = ("CBOT soybean meal's highest settle was 554.4 USD/short ton on 2022-04-19 [N1], read "
             "from 2010-06-06 to 2026-09-01.")
    row = {"id": "N1", "kind": "number",
           "locator": {"metric": cq.XL_METRIC, "located_date": "2022-04-19"},
           "payload": {"rows": [{"value": 554.4, "knowledge_date": "2022-04-19"}]}}
    good = {"citations": [row], "answer": "", "trace": {}, "intent_decision": {},
            "structured": {"tldr": prose, "mechanism": ""}}
    st = EV._cascade_stats(good)
    assert (st["xl_threshold_echo"], st["xl_threshold_verdict"],
            st["xl_window_duration_gloss"]) == (0, 0, 0)
    _c, _v, sents, _p = EV._xl_cited(good, prose)
    assert len(sents) == 1 and sents[0].startswith("CBOT soybean meal")   # WHOLE, not a fragment
    echo = copy.deepcopy(good)
    echo["structured"]["tldr"] = ("Corn has been above 800 before: soybean meal settled at 554.4 on "
                                  "2022-04-19 [N1].")
    assert EV._cascade_stats(echo)["xl_threshold_echo"] == 1        # the unserved 800 still convicts

    # (b) ANSWER -- the decimal claim and the integer claim now read the SAME, and a spanned one is 0
    dec = {"tldr": "Soybean meal's record high settle was 554.4 on 2022-04-19 [N1].", "mechanism": ""}
    whole = {"tldr": "Soybean meal's record high settle was 554 on 2022-04-19 [N1].", "mechanism": ""}
    spanned = {"tldr": "Soybean meal's highest settle in the record read from 2010-06-06 to "
                       "2026-09-01 was 554.4 [N1].", "mechanism": ""}
    assert an._count_unspanned_superlatives(dec, handles={"[N1]"}) == 1
    assert an._count_unspanned_superlatives(whole, handles={"[N1]"}) == 1
    assert an._count_unspanned_superlatives(spanned, handles={"[N1]"}) == 0
    assert an._count_unspanned_superlatives(dec, handles=set()) == 0        # the scope still holds


def test_fix2_new_2_the_echo_backs_a_numeral_against_the_handles_its_sentence_cites():
    """RE-REVIEW NEW 2 (MAJOR) -- "xl_threshold_echo CHARGES A FIGURE SERVED BY A NON-LOCATOR HANDLE,
    in a multi-handle sentence the mandate EXPLICITLY PERMITS".

    MEASURED BEFORE THE FIX: `_xl_cited` scoped to any sentence CITING a locator handle but backed its
    numerals against LOCATOR ROW VALUES ALONE. With two locator rows (849, 500) and one ordinary SILVER
    NUMBERS row (soybean meal 554.4), the sentence "CBOT corn's highest settle was 849 on 2012-08-21
    [N1], read from 2010-06-06 to 2026-09-01, while CBOT soybean meal settled at 554.4 [N3]." scored
    xl_threshold_echo = 1 -- the soybean-meal figure is correctly transcribed from ITS OWN served row
    and was charged anyway. The mandate INSTRUCTS that shape ("When a sentence cites more than one
    handle AND states any figure, state a figure from EVERY handle it cites"), and a locator turn is a
    hybrid turn that also carries SILVER NUMBERS rows, so the convicted shape is the ordinary one.

    CLOSED by the remedy's first option: the backing pool is PER SENTENCE and is the union of the rows
    every handle THAT SENTENCE cites served -- locator rows for locator handles, the numbers rows for
    their own. The kill's actual target is untouched: the level the QUESTION named is served by no
    handle on the turn, so no pool backs it."""
    loc1 = {"id": "N1", "kind": "number",
            "locator": {"metric": cq.XL_METRIC, "located_date": "2012-08-21"},
            "payload": {"rows": [{"value": 849.0, "knowledge_date": "2012-08-21"}]}}
    loc2 = {"id": "N2", "kind": "number",
            "locator": {"metric": cq.XL_METRIC, "located_date": "2024-09-04"},
            "payload": {"rows": [{"value": 500.0, "knowledge_date": "2024-09-04"}]}}
    plain = {"id": "N3", "kind": "number", "locator": {"metric": "settle"},
             "payload": {"rows": [{"value": 554.4, "knowledge_date": "2026-09-01"}]}}
    two = ("CBOT corn's highest settle was 849 on 2012-08-21 [N1], read from 2010-06-06 to "
           "2026-09-01, while CBOT soybean meal settled at 554.4 [N3].")
    out = {"citations": [loc1, loc2, plain], "answer": "", "trace": {}, "intent_decision": {},
           "structured": {"tldr": two, "mechanism": ""}}
    assert EV._cascade_stats(out)["xl_threshold_echo"] == 0
    _c, vals, sents, pools = EV._xl_cited(out, two)
    assert vals == [849.0, 500.0]                       # the LOCATOR rows are still what `vals` means
    assert len(sents) == 1 and sorted(pools[0]) == [554.4, 849.0]   # ...the POOL is what it CITES
    # A TRUE ECHO still convicts: 800 is served by NO handle on the turn
    echo = copy.deepcopy(out)
    echo["structured"]["tldr"] = ("Corn has been above 800 before: its highest settle was 849 on "
                                  "2012-08-21 [N1].")
    assert EV._cascade_stats(echo)["xl_threshold_echo"] == 1
    # ...and an UNCITED handle's rows back nothing: 554.4 stated without [N3] is still charged
    uncited = copy.deepcopy(out)
    uncited["structured"]["tldr"] = ("CBOT corn's highest settle was 849 on 2012-08-21 [N1], while "
                                     "soybean meal settled at 554.4.")
    assert EV._cascade_stats(uncited)["xl_threshold_echo"] == 1


def test_fix2_new_3_every_shipped_read_refusal_carries_its_own_name():
    """RE-REVIEW NEW 3 (MINOR) -- "THE NEW READ-ERROR CLASSIFIER FOLDS A THIRD SHIPPED RAISE INTO A
    NAME THAT STATES THE OPPOSITE OF WHAT THAT RAISE SAYS".

    MEASURED BEFORE THE FIX: `XL_READ_ERROR_REASONS` was a SUBSTRING table and `build_sql`'s extreme
    branch raises FOUR distinct messages, not two. The `year_month` refusal -- "...declares
    knowledge_semantics='year_month', which carries no release stamp and no per-observation date at all
    -- an extreme cannot be DATED on it" -- CONTAINS "release stamp" while saying the card has none, so
    it classified as `vintage_card`, whose reader sentence is "this source records a release stamp
    rather than an observation date". The exact opposite, in a decline the reader can be shown.

    CLOSED with an EXPLICIT MARKER: `query._extreme_refusal(reason, msg)` stamps the name on the
    exception (`query.XL_REFUSAL_ATTR`), the type stays ValueError so no caller's behaviour moves, and
    `_xl_read_reason` reads that attribute against the CLOSED set and nothing else. FOUR RAISES, THREE
    NAMES: `month_only_card` is minted here; both axis refusals share `extrema_axis_unavailable`, which
    already documents itself as one reader sentence with several producers. ALL FOUR shipped messages
    are driven below, from the SHIPPED registry's own cards where one exists."""
    assert cq.XL_READ_ERROR_REASONS == ("vintage_card", "month_only_card", "extrema_axis_unavailable")
    assert set(cq.XL_READ_ERROR_REASONS) <= set(cq.XL_DECLINE_TEMPLATES)
    R = load_registry()
    # RAISE 1 -- the VINTAGE card, from the shipped registry
    ts_v = R.get("silver_wasde")
    assert ts_v.knowledge_semantics == "vintage"
    with pytest.raises(ValueError) as e1:
        Q.build_sql(Q.NumberQuery(table="silver_wasde", metric=sorted(ts_v.metrics)[0], asof=ASOF,
                                  commodity="corn", agg="max_row"), ts_v)
    assert cq._xl_read_reason(e1.value) == "vintage_card"
    # RAISE 2 -- the YEAR_MONTH card, the one the substring table mis-filed
    ym = sorted(n for n, t in R.tables.items()
                if getattr(t, "knowledge_semantics", None) == "year_month")
    assert ym, "the registry must carry a year_month card for this raise to be reachable"
    ts_y = R.get(ym[0])
    with pytest.raises(ValueError) as e2:
        Q.build_sql(Q.NumberQuery(table=ym[0], metric=sorted(ts_y.metrics)[0], asof=ASOF,
                                  commodity="corn", agg="max_row"), ts_y)
    assert "release stamp" in str(e2.value)              # the SUBSTRING that caused the mis-filing
    assert cq._xl_read_reason(e2.value) == "month_only_card"
    # RAISE 3 -- `_extreme_window`, no date_col
    naked = copy.deepcopy(_card())
    naked.date_col = None
    with pytest.raises(ValueError) as e3:
        Q._extreme_window(naked, "settle")
    assert cq._xl_read_reason(e3.value) == "extrema_axis_unavailable"
    # RAISE 4 -- `build_sql`, no chronological column: the SAME fact, the SAME reader sentence
    with pytest.raises(ValueError) as e4:
        Q.build_sql(Q.NumberQuery(table=cq.XL_TABLE, metric=cq.XL_SOURCE_METRIC, asof=ASOF,
                                  commodity=SLUG, agg="max_row"), naked)
    assert "no chronological column" in str(e4.value)
    assert cq._xl_read_reason(e4.value) == "extrema_axis_unavailable"
    # THE NEGATIVES: an outage is never a coverage fact, and the vocabulary is CLOSED
    assert cq._xl_read_reason(RuntimeError("athena throttled")) == "error"
    assert cq._xl_read_reason(Q._extreme_refusal("not_a_reason", "x")) == "error"
    # END TO END on the year_month card: the leg declines by the HONEST name and spends its one read
    real = cq.XL_TABLE
    try:
        cq.XL_TABLE = ym[0]
        _c, pay = cq._xl_locate(_tape({}), {"board": SLUG, "direction": "max", "kind": "extreme"},
                                ASOF)
        assert [d["reason"] for d in pay["declines"]] == ["month_only_card"]
        assert pay["reads"] == 1
    finally:
        cq.XL_TABLE = real
    # ...and the LINT binds the producer to the vocabulary, both directions (clause 13)
    assert cc.check_extreme_locator() == []


# == FIX PASS 3 -- THE VERIFY PASS'S TWO NEW FINDINGS ================================================
def test_fix3_new_1_the_per_sentence_pool_is_the_handles_full_served_set():
    """VERIFY-2 NEW 1 (MAJOR) -- "THE PER-SENTENCE POOL IS THE CITATION PAYLOAD'S rows[:3], SO
    RE-REVIEW NEW 2'S CLASS SURVIVES FOR EVERY CITATION WHOSE CALL SERVED MORE THAN THREE ROWS".

    MEASURED BEFORE THE FIX, on a five-row series [500, 400, 300, 200, 100] served beside a locator
    row. `citations.from_number` truncates the payload to `rows[:3]` (citations.py:658), so the pool
    fix pass 2 built saw only [500, 400, 300] and a COMPLIANT transcription of the fifth print --
    "...up from 100 in January [N3]." -- scored `xl_threshold_echo` = 1, the alias's declared
    ZERO-TOLERANCE kill, on an answer the SHIPPED verifier does not touch (`verify._num_backed(100.0,
    verify._all_row_vals(number_calls))` is True). "the series ran 100 to 500 [N3]" scored 1 in BOTH
    orientations, because with n > 3 one end is always outside the prefix; under the documented
    `GRAPHRAG_SERIES_NEWEST_FIRST=off` rollback the charged figure was the citation's OWN RENDERED
    HEADLINE. A figure from row 3, INSIDE the prefix, scored 0 -- which isolates the truncation as the
    cause rather than the scoping.

    CLOSED with this file's own two-source idiom, ~800 lines below the counter: `_eod_rows` unions
    `citations[].payload.rows` with the untruncated `out['number_calls']` and says why. `_xl_served_pool`
    makes the same union keyed by HANDLE, preferring `number_calls_full` (the hybrid lane's own list;
    the orchestrator's `number_calls` is its PREFIX), joined on POSITION -- the producer's rule, the one
    `answer._xl_locator_handles` already keys on ("the k-th entry is [Nk]")."""
    loc_call = {"query": {"table": "silver_futures_eod", "metric": cq.XL_METRIC},
                "rows": [{"value": 849.0, "knowledge_date": "2012-08-21",
                          "located_extreme": "2012-08-21"}], "status": "ok"}
    other = {"query": {"table": "silver_wasde", "metric": "ending_stocks"},
             "rows": [{"value": 1750.0, "knowledge_date": "2026-08-12"}], "status": "ok"}
    desc = [{"value": v, "knowledge_date": d} for v, d in
            [(500.0, "2026-05-04"), (400.0, "2026-04-01"), (300.0, "2026-03-01"),
             (200.0, "2026-02-01"), (100.0, "2026-01-05")]]

    def _turn(series):
        calls = [loc_call, other,
                 {"query": {"table": "silver_futures_eod", "metric": "settle"}, "rows": series,
                  "status": "ok"}]
        cits = [{"id": "N1", "kind": "number",
                 "locator": {"metric": cq.XL_METRIC, "located_date": "2012-08-21"},
                 "payload": {"query": calls[0]["query"], "rows": calls[0]["rows"][:3]}},
                {"id": "N2", "kind": "number", "locator": {"metric": "ending_stocks"},
                 "payload": {"query": calls[1]["query"], "rows": calls[1]["rows"][:3]}},
                {"id": "N3", "kind": "number", "locator": {"metric": "settle"},
                 "payload": {"query": calls[2]["query"], "rows": series[:3]}}]
        return {"citations": cits, "number_calls_full": calls, "number_calls": calls[:1],
                "answer": "", "trace": {}, "intent_decision": {},
                "structured": {"tldr": "", "mechanism": ""}}

    def _echo(out, prose):
        o = copy.deepcopy(out)
        o["structured"] = {"tldr": prose, "mechanism": ""}
        return EV._cascade_stats(o)["xl_threshold_echo"]

    from leviathan.graphrag import verify as VF
    t = _turn(desc)
    LEAD = ("CBOT corn's highest settle was 849 on 2012-08-21 [N1], read from 2010-06-06 to "
            "2026-09-01, ")
    # THE TRUNCATION IS REAL, and the SHIPPED verifier does not charge the fifth print
    assert sorted(EV._xl_cite_values(t["citations"][2])) == [300.0, 400.0, 500.0]
    assert VF._num_backed(100.0, VF._all_row_vals(t["number_calls_full"])) is True
    # ...and the pool this counter reads now carries all five
    assert sorted(EV._xl_served_pool(t)["[N3]"]) == [100.0, 200.0, 300.0, 400.0, 500.0]

    # THE BRIEF'S PIN, all three legs
    assert _echo(t, LEAD + "up from 100 in January [N3].") == 0          # was 1
    assert _echo(t, LEAD + "up from 100 in January.") == 1              # no handle -> no pool
    assert _echo(t, LEAD + "up from 175 in January [N3].") == 1         # fabricated -> convicted
    # ORDINARY SERIES NARRATION, both ends, and the row already inside the prefix
    assert _echo(t, LEAD + "and the series ran 100 to 500 [N3].") == 0   # was 1
    assert _echo(t, LEAD + "up from 300 in March [N3].") == 0            # 0 before AND after
    # THE DOCUMENTED ROLLBACK (ascending series): the citation's OWN RENDERED HEADLINE is outside
    # rows[:3], and it was the charged figure
    asc = _turn(list(reversed(desc)))
    assert sorted(EV._xl_cite_values(asc["citations"][2])) == [100.0, 200.0, 300.0]
    assert _echo(asc, LEAD + "and the latest print is 500 [N3].") == 0   # was 1
    # NO AMNESTY: the kill's target is untouched, and a handle the sentence does NOT cite backs nothing
    assert _echo(t, "Corn has been above 800 before: its highest settle was 849 on "
                    "2012-08-21 [N1].") == 1
    assert _echo(t, LEAD + "while stocks stood at 1750.") == 1
    # THE POSITION JOIN IS THE PRODUCER'S OWN RULE, and a letter-suffixed extra reads its call's set
    assert cit.from_number(loc_call, 7).id == "N7"
    extra = copy.deepcopy(t)
    extra["citations"][2]["id"] = "N3b"
    assert sorted(EV._xl_served_pool(extra)["[N3b]"]) == [100.0, 200.0, 300.0, 400.0, 500.0]
    # THE PAYLOAD-ONLY SURFACE STILL WORKS: a direct answer.answer() consumer has no call list
    payload_only = copy.deepcopy(t)
    payload_only.pop("number_calls_full")
    payload_only.pop("number_calls")
    assert sorted(EV._xl_served_pool(payload_only)["[N3]"]) == [300.0, 400.0, 500.0]
    assert _echo(payload_only, LEAD + "up from 300 in March [N3].") == 0


def test_fix3_new_2_the_semicolon_evasion_rides_the_sibling():
    """VERIFY-2 NEW 2 (MINOR) -- "THE SPLITTER SWAP SHRANK THE K27b ECHO'S OWN REACH ON THE SEMICOLON
    SHAPE, AND THE REPORT DECLARES THE CLAUSE-SCOPE CONSEQUENCE FOR M5 ONLY".

    MEASURED: one K27b violation under four punctuations, everything else held fixed. On the OLD
    hand-rolled splitter the semicolon shape scored `xl_threshold_echo` = 1; on the estate's boundary
    (`verify._SENT_SPLIT`, which breaks on ';') it scores 0, because the clause stating the unserved
    threshold cites no handle and is out of scope.

    THE REACH IS NOT RESTORED, AND THAT IS THE ESTATE'S LAW RATHER THAN A CONVENIENCE. A clause-aware
    pool admitting a handle from a PRECEDING clause would contradict the rule the writer is graded on
    and the persona states to the model in as many words -- "every clause after a semicolon that states
    a level carries its own handle inside it" -- and answer.py's own CASE-2 note records the same fact
    MEASURED: "a handle in the lead clause does not reach a level in a LATER clause of the same physical
    line". So the consequence is DECLARED instead, here and in `_xl_threshold_echo`'s docstring.

    THE SHAPE IS NOT INVISIBLE TO THE ESTATE: `register.unbacked_levels`, the deterministic sibling
    behind `price_target_backed`, charges exactly what the echo cannot see. The two columns are
    COMPLEMENTARY and an arm must read them TOGETHER."""
    row = {"id": "N1", "kind": "number",
           "locator": {"metric": cq.XL_METRIC, "located_date": "2012-08-21"},
           "payload": {"rows": [{"value": 849.0, "knowledge_date": "2012-08-21"}]}}
    base = {"citations": [row], "answer": "", "trace": {}, "intent_decision": {},
            "structured": {"tldr": "", "mechanism": ""}}
    tail = "its highest settle was 849 on 2012-08-21 [N1]."
    shapes = {"semicolon": f"Corn has been above 800 before; {tail}",
              "colon": f"Corn has been above 800 before: {tail}",
              "comma": f"Corn has been above 800 before, {tail}",
              "period": f"Corn has been above 800 before. {tail[0].upper()}{tail[1:]}"}

    def _echo(prose):
        o = copy.deepcopy(base)
        o["structured"] = {"tldr": prose, "mechanism": ""}
        return EV._cascade_stats(o)["xl_threshold_echo"]

    got = {k: (_echo(v), len(reg.unbacked_levels(v))) for k, v in shapes.items()}
    # (echo, unbacked_levels): exactly ONE of the two columns charges each shape, and none escapes
    assert got == {"semicolon": (0, 1), "colon": (1, 0), "comma": (1, 0), "period": (0, 1)}
    assert reg.unbacked_levels(shapes["semicolon"])[0][0] == "800"
    assert all(sum(v) >= 1 for v in got.values())        # every shape is charged by SOMETHING
    # THE DECLARATION IS IN THE COUNTER'S OWN DOCSTRING, naming the sibling and this pin
    doc = EV._xl_threshold_echo.__doc__
    assert "register.unbacked_levels" in doc and "semicolon" in doc
    assert "test_fix3_new_2_the_semicolon_evasion_rides_the_sibling" in doc
    assert "register.unbacked_levels" in EV._xl_sentences.__doc__
