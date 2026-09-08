"""SCAN RUNG 3 (THE HEADLINE ROSTER, 2026-09-08): the deterministic Scan numbers leg, and its OFF state.

THE MECHANISM IN ONE LINE. The Scan tier's numbers leg is ~100% MODEL time -- `timing_ms.numbers` minus
that turn's own summed API-call seconds is p50 0.07 s across 1 to 38 lookups, so one banked row spent
0.1 s EXECUTING 35 lookups and 89.6 s PLANNING them -- and what all that planning rediscovers every turn
is a set of THREE CARDS. `numbers/roster.py` writes that set down: per routed contract, a balance
standing, a production row, a trade row, a board settle and a price standing, each read through
`cascade.fetch_window` with a scope it can PROVE, and every row it cannot prove DECLINED with a written
reason. Zero agent rounds, zero model tokens.

TWO HALVES, NEITHER IMPLYING THE OTHER:
  GRAPHRAG_NUMBERS_ROSTER   the FLAG    -- admits the lane at all.
  Mode.numbers_roster       the PRESET  -- says this turn is on it. Every shipped preset leaves it None.

THE ACCEPTANCE BAR, pinned first and hardest, and asserted by CAPTURING what injected fakes received
rather than by reading source: with the flag off NOTHING moves -- `answer_numbers` is still the callee
and receives HEAD's kwargs byte for byte, the roster module is never entered, `route_fn` is never called
by this seam, the numbers block is byte-identical and `trace.numbers_budget` is ABSENT. With the flag ON
only a preset carrying `numbers_roster` moves: `quick`, `quick_n3`, `standard`, `deep` and `max` take
the agent branch unchanged.

THE FATAL-1 PIN is the one the build exists to protect: a roster turn that returns ZERO rows must put
`NUMBERS_BUDGET_MARK` in the writer's prompt. At HEAD the budget-note gate was `bool(_nc)` -- a ROUND
budget -- and a roster preset carries none by construction, so a refusing roster turn would have shipped
"(none retrieved)" with no marker, no persona mandate and no trace stamp: an absence presented as an
ordinary thin read. One predicate closes it and this file measures the close.

All offline: no pg, no Athena, no S3, no LLM, no AWS. The flag-on roster pins drive the REAL
`build_sql` / `Q.run` stack through an injected `query_fn`, so the specs the roster issues are proven by
the SQL that came out of them and not by reading the call site. ASCII-only output (cp1252 console).
"""
from __future__ import annotations

import re

import pytest
from leviathan.causal import schema as cs
from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import config_check as cc
from leviathan.graphrag import graph as g
from leviathan.graphrag import orchestrator as orch
from leviathan.graphrag import reasoning_modes as rm
from leviathan.graphrag.numbers import agent as na
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import roster as ro
from leviathan.graphrag.numbers import stats as st

_ASOF = "2026-09-07"
_Q = "Set palm oil against rapeseed oil for me"
_MY = 2024                      # cascade._settled_my_ceiling for both palm and rapeseed oil at _ASOF

# ── the fixtures ────────────────────────────────────────────────────────────────────────────────────
_CALLS = [{"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                     "period": "2023"},
           "rows": [{"value": "2462000", "unit": "MT", "knowledge_date": "2024-01-10"}],
           "status": "ok"}]


def _graph() -> g.CausalGraph:
    def _c(name):
        return cs.CausalContract(contract=name, aliases=[],
                                 drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                    mechanism="dryness cuts yield")])
    return g.CausalGraph({n: _c(n) for n in ("corn_cbot", "malaysian_crude_palm_oil_cme",
                                             "rapeseed_oil_zce", "soybeans_cbot",
                                             "soybean_meal_cbot", "cocoa")}, silver=set())


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test states its own flag state. An inherited flag makes an OFF pin vacuously green, which
    is the exact failure the D-AM `_clean_env` fixture was written for."""
    for v in ("GRAPHRAG_MODES", "GRAPHRAG_NUMBERS_ROSTER", "GRAPHRAG_NUMBERS_MODE_BUDGET",
              "GRAPHRAG_NUMBERS_BUDGET_NOTE", "GRAPHRAG_SCOPE_WITHHOLD",
              "GRAPHRAG_FUTURES_NEWEST_FIRST", "GRAPHRAG_SERIES_NEWEST_FIRST",
              "GRAPHRAG_NUMBERS_INCREMENTAL_CACHE", "GRAPHRAG_NUMBERS_THINKING"):
        monkeypatch.delenv(v, raising=False)


def _hybrid(monkeypatch, *, mode_knobs=None, nums=None, roster=None, flag=None, note=None,
            route=None, raise_roster=None, query=_Q):
    """Drive `orch.run_hybrid` with injected fakes and capture what each seam received: the callee that
    actually ran, `answer_numbers`' kwargs, `answer_roster`'s kwargs, `_numbers_block`'s `budget` kwarg
    and the string it rendered, how many times `route_fn` was called, and the finished `out`.

    NOTHING HERE IS READ OFF THE SOURCE -- that is the whole point of the harness, and it is why the
    flag-off pin can claim byte-identity rather than merely asserting a branch exists."""
    seen: dict = {"callee": [], "routes": 0}
    real_block = orch._numbers_block
    real_roster = ro.answer_roster            # BEFORE the patch, or the fake would recurse into itself

    def _fake_numbers(question, asof, **kw):
        seen["callee"].append("agent")
        seen["numbers_kw"] = dict(kw)
        seen["numbers_q"] = question
        return dict(nums if nums is not None else {"calls": list(_CALLS)})

    def _fake_roster(question, asof, **kw):
        seen["callee"].append("roster")
        seen["roster_kw"] = dict(kw)
        seen["roster_q"] = question
        if raise_roster is not None:
            raise raise_roster
        return dict(roster if roster is not None else real_roster(question, asof, **kw))

    def _spy_block(calls, **kw):
        seen["block_kw"] = dict(kw)
        seen["block"] = real_block(calls, **kw)
        seen["block_plain"] = real_block(calls)      # what HEAD would have rendered for these calls
        return seen["block"]

    def _fake_answer(query_, **kw):
        seen["answer_kw"] = dict(kw)
        kw["extra_resolver"]()
        return {"answer": "a", "trace": {}, "citations": [], "evidence": [], "structured": None,
                "contract": None, "contracts": [], "model": "m"}

    def _route(q, gr):
        seen["routes"] += 1
        return list(route if route is not None else [])

    monkeypatch.setattr(na, "answer_numbers", _fake_numbers)
    monkeypatch.setattr(ro, "answer_roster", _fake_roster)
    monkeypatch.setattr(orch, "_numbers_block", _spy_block)
    monkeypatch.setattr(an, "answer", _fake_answer)
    for name, val in (("GRAPHRAG_NUMBERS_ROSTER", flag), ("GRAPHRAG_NUMBERS_BUDGET_NOTE", note)):
        if val is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, val)
    kw = {"mode_knobs": mode_knobs} if mode_knobs else {}
    seen["out"] = orch.run_hybrid(query, _ASOF, graph=_graph(), route_fn=_route, **kw)
    return seen


# ── the injected query_fn: the REAL SQL stack, no pg and no Athena ──────────────────────────────────
_SELECT_RX = re.compile(r"SELECT\s+(\w+)\s+AS value", re.I)
_COUNTRY_RX = re.compile(r"country = '([^']*)'")
_MY_RX = re.compile(r"market_year = (\d+)")
_SLUG_RX = re.compile(r"leviathan_slug = '([^']*)'")

_PSD_VALUES = {"su_ratio": 0.1266,
               "production_mt": 19_000_000.0, "exports_mt": 16_500_000.0,
               "imports_mt": 2_100_000.0}
_WORLD_ROWS = {"ending_stocks_mt": [("Malaysia", 2_000_000.0), ("Indonesia", 3_000_000.0),
                                    ("European Union", 500_000.0)],
               "consumption_mt": [("Malaysia", 9_000_000.0), ("Indonesia", 12_000_000.0),
                                  ("European Union", 4_000_000.0)],
               "production_mt": [("Malaysia", 19_000_000.0), ("Indonesia", 46_000_000.0),
                                 ("European Union", 100_000.0)],
               "exports_mt": [("Malaysia", 16_000_000.0), ("Indonesia", 26_000_000.0),
                              ("European Union", 50_000.0)]}


# The pink-sheet window the fake serves: 60 ASC monthly rows, 800 -> 1,390, ending 2026-09-01.
_PINK_N, _PINK_LO, _PINK_STEP = 60, 800.0, 10.0
_PINK_END = "2026-09-01"


def _pink_month(i: int) -> str:
    """The i-th month of the served window, ASC, ending at `_PINK_END` -- pure string arithmetic, the
    `cascade._months_back` idiom, so the fixture reads no clock either."""
    y, m = int(_PINK_END[:4]), int(_PINK_END[5:7])
    tot = y * 12 + (m - 1) - (_PINK_N - 1 - i)
    return f"{tot // 12:04d}-{tot % 12 + 1:02d}-01"


class _QFn:
    """One injected executor for the whole roster. It answers the SQL the roster's OWN specs compiled,
    so a wrong table, a wrong metric, a mis-cased country or a wrong marketing year comes back EMPTY
    exactly as it does on the served card -- section 12's casing law, reproduced offline."""

    def __init__(self, *, eod_dark=True, kd="2026-08-12", world_kd=None, psd_kd=None,
                 psd_countries=("Malaysia", "China"), scale=None):
        self.sqls: list[str] = []
        self.eod_dark, self.kd = eod_dark, kd
        self.world_kd = world_kd or {}
        # FORM A's per-marketing-year release stamp. silver_psd's group_cols are
        # [leviathan_slug, country, market_year], so EACH year takes its own latest release <= asof --
        # which is the whole reason R1's change row has to prove the two prints share one.
        self.psd_kd = psd_kd or {}
        self.psd_countries = set(psd_countries)
        # PER-SLUG SCALING, because the DEFAULT here is the COLLIDING case: two slugs fanning onto one
        # PSD sheet return the identical float, which is what the fold is about. A pin that needs two
        # DISTINCT world balances (the ordinary pair) passes a scale so the legs differ honestly.
        self.scale = dict(scale or {})

    def __call__(self, sql: str):
        self.sqls.append(sql)
        m = _SELECT_RX.search(sql)
        metric = m.group(1) if m else ""
        if "silver_futures_eod" in sql:
            return []                                   # the OI-gap board-dark path, measured 7/9 live
        if "silver_pink_sheet" in sql:
            # A REAL 60-MONTH ASC WINDOW, and the shape is the pin (fix pass 2026-09-08, FATAL-1).
            # The first fixture repeated twelve month stamps five times, so no test could tell the
            # OLDEST row from the NEWEST and the sign-inverted standing was invisible. This one is what
            # the card serves: ascending monthly `knowledge_date`s ending one publication month before
            # the as-of (the card's 40-day lag), values RISING 800 -> 1,390, so the newest observation
            # is the window's MAXIMUM and any reading that takes rows[0] prints its exact inverse.
            return [{"value": _PINK_LO + _PINK_STEP * i, "knowledge_date": _pink_month(i)}
                    for i in range(_PINK_N)]
        if "silver_psd" not in sql:
            return []
        cm = _COUNTRY_RX.search(sql)
        my = int(_MY_RX.group(1)) if False else (int(_MY_RX.search(sql).group(1))
                                                 if _MY_RX.search(sql) else None)
        if cm is not None:                              # form A: one named country, VERBATIM equality
            if cm.group(1) not in self.psd_countries or metric not in _PSD_VALUES:
                return []
            return [{"value": _PSD_VALUES[metric], "knowledge_date": self.psd_kd.get(my, self.kd),
                     "period": my, "country": cm.group(1)}]
        rows = _WORLD_ROWS.get(metric)                  # form B: every country's own latest vintage
        if not rows:
            return []
        sm = _SLUG_RX.search(sql)
        # The factor is applied to every component EXCEPT the use denominator, or the stocks-to-use
        # RATIO would be scale-invariant and the two legs would still collide -- which is the case the
        # UNSCALED fake is for.
        k = 1.0 if metric == "consumption_mt" else self.scale.get(sm.group(1) if sm else "", 1.0)
        return [{"value": v * k, "knowledge_date": self.world_kd.get(my, self.kd), "period": my,
                 "country": c} for c, v in rows]


def _tables(res):
    return res["tables_queried"]


def _by_metric(res):
    return {str((c.get("query") or {}).get("metric")): c for c in res["calls"]}


def _declines(res):
    return {(d.get("row"), d.get("reason")) for d in res["numbers_budget"]["roster_declines"]}


# == P1 -- THE PRESET TABLE: the leak fence, the one-variable law, the tail order ======================
def test_p1_the_pair_is_dark_at_birth_and_differs_by_exactly_one_field():
    """The F8 leak fence, eighth application, and BOTH halves need the entry -- the CONTROL is the one
    that gets forgotten, because it differs from shipped `quick` only in the writer seat, which is the
    least visible thing a leaked preset could change."""
    assert rm.QUICK_R0 in rm.DARK_NAMES and rm.QUICK_S in rm.DARK_NAMES
    assert rm.serving_names() == frozenset({"quick", "standard", "deep"})
    assert rm.QUICK_R0 in rm.valid_names() and rm.QUICK_S in rm.valid_names()
    _all = ("name",) + tuple(rm.KNOB_FIELDS)
    assert {f for f in _all
            if getattr(rm.MODES[rm.QUICK_S], f) != getattr(rm.MODES[rm.QUICK_R0], f)} == {
        "name", "numbers_roster"}
    assert {f for f in _all
            if getattr(rm.MODES[rm.QUICK], f) != getattr(rm.MODES[rm.QUICK_S], f)} == {
        "name", "synth_model"}
    # 1.6(1): a roster preset must carry NO round budget. `numbers_calls=0` is FALSY at run_hybrid's
    # truthiness gate, so expressing the roster that way would silently run the full six rounds.
    assert rm.MODES[rm.QUICK_R0].numbers_calls is None
    assert rm.MODES[rm.QUICK_S].numbers_calls is None


def test_p1b_the_appended_last_law_and_the_byte_identity_fence():
    """KNOB_FIELDS order IS the trace-stamp column order: append, never insert. `numbers_roster` is the
    EIGHTH application and takes the tail; `numbers_calls` (lane S, seventh) moves left by one and every
    slice below it with it."""
    assert rm.KNOB_FIELDS[-1] == "numbers_roster"
    assert rm.KNOB_FIELDS[-2] == "numbers_calls"
    assert rm.KNOB_FIELDS[-3] == "synth_effort"
    for name in rm.MODES:
        if name == rm.QUICK_R0:
            continue
        assert rm.MODES[name].numbers_roster is None, name
        assert "numbers_roster" not in rm.knobs(name), name
    assert rm.knobs(rm.QUICK_R0)["numbers_roster"] is True
    assert rm.knobs(rm.STANDARD) == {}                 # the all-None passthrough, untouched


def test_p1c_the_governing_lint_agrees_in_process():
    assert cc.check_scan_roster() == []
    assert cc.check_scan_tier() == []                  # the sibling did not go red on the tail move


# == P2 -- FLAG OFF: the agent is still the callee, with HEAD's kwargs ================================
def test_p2_flag_off_the_agent_runs_on_every_preset_including_the_roster_one(monkeypatch):
    """Captured, not read: with the flag off the roster module is never entered, `answer_numbers` is,
    and its kwargs are HEAD's exactly -- so an injected fake written against the pre-rung-3 signature
    stays valid and the numbers leg is byte-identical."""
    head = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK), route=["corn_cbot"])["numbers_kw"]
    assert set(head) == {"client", "model", "query_fn", "on_call", "families",
                         "futures_newest_first"}         # HEAD's own set, captured not transcribed
    assert "max_calls" not in head and "contracts" not in head
    for name in (rm.QUICK, rm.DEEP, rm.QUICK_N3, rm.QUICK_R0):
        seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(name), route=["corn_cbot"])
        assert seen["callee"] == ["agent"], name
        assert seen["numbers_kw"] == head, name          # the ROSTER preset's leg is quick's, byte for byte
        assert "roster_kw" not in seen, name
        assert seen["block_kw"] == {"budget": None}, name
        assert seen["block"] == seen["block_plain"], name
        assert "numbers_budget" not in seen["out"]["trace"], name


def test_p2b_flag_on_moves_only_the_preset_that_carries_the_field(monkeypatch):
    for name in (rm.QUICK, rm.DEEP, rm.MAX, rm.STANDARD, rm.QUICK_N3, rm.QUICK_S):
        seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(name), flag="on", route=["corn_cbot"])
        assert seen["callee"] == ["agent"], name
    for off in ("", "off", "0", "false", "OFF", "yes"):        # fail-closed: only 'on' enables
        seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_R0), flag=off, route=["corn_cbot"])
        assert seen["callee"] == ["agent"], off


def test_p2c_the_route_fn_is_never_called_by_this_seam_with_the_flag_off(monkeypatch):
    """THE `_mc` HOIST'S OWN BYTE-IDENTITY PIN, and it is not a micro-optimisation. `route_fn` on a
    session turn is the lexical route plus `an.route_smart` -- real work with its own failure modes
    ("a session route_fn may itself reach for the dead LLM tier") -- so an ungated hoist would move
    EVERY hybrid turn with the flag off. It is gated on `_nr`, and this counts the calls."""
    off = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_R0), route=["corn_cbot"])
    assert off["routes"] == 0
    on = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_R0), flag="on", route=["corn_cbot"])
    assert on["routes"] == 1                            # ONCE per turn; no second routing


# == P3 -- FLAG ON: the roster is the callee, and it gets the routed contracts ========================
def test_p3_the_roster_receives_the_routed_contracts_filtered_on_the_graph(monkeypatch):
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_R0), flag="on",
                   route=["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce", "not_a_contract"])
    assert seen["callee"] == ["roster"]
    assert "numbers_kw" not in seen                      # the agent never ran: zero rounds, zero tokens
    assert seen["roster_kw"]["contracts"] == ["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"]
    assert set(seen["roster_kw"]) == {"contracts", "qfn", "reg", "route_error"}
    assert seen["roster_kw"]["route_error"] is False     # the router ran and answered


def test_p3b_a_routing_failure_is_a_refusal_and_never_a_broken_turn(monkeypatch):
    """`route_fn` may itself reach a dead tier. The exception is swallowed to an empty list, which the
    roster turns into refusal 1.5(a) -- and that refusal NARRATES (P5).

    AND THE CAUSE TRAVELS WITH IT (fix pass 2026-09-08): a router that RAISED is not a turn that routed
    nothing, and this module's own cited law (`_RV_PRICE_ABSENCE`: never one shared reason for two
    causes) applies to its own declines first. `route_error` is threaded, and the two refusals read
    differently -- one says the record was never asked."""
    def _boom(q, gr):
        raise RuntimeError("the session route tier is down")
    seen: dict = {}
    monkeypatch.setattr(ro, "answer_roster", lambda q, a, **kw: seen.setdefault("kw", kw) or
                        {"calls": [], "numbers_budget": {"roster": True, "returned": True}})
    monkeypatch.setattr(an, "answer", lambda q, **kw: (kw["extra_resolver"](),
                                                       {"answer": "a", "trace": {}, "citations": [],
                                                        "evidence": [], "structured": None,
                                                        "contract": None, "contracts": [],
                                                        "model": "m"})[1])
    monkeypatch.setenv("GRAPHRAG_NUMBERS_ROSTER", "on")
    out = orch.run_hybrid(_Q, _ASOF, graph=_graph(), route_fn=_boom,
                          mode_knobs=rm.knobs(rm.QUICK_R0))
    assert out["intent"] == "hybrid"
    assert seen["kw"]["contracts"] == []
    assert seen["kw"]["route_error"] is True


def test_p3c_a_router_that_threw_and_a_turn_that_routed_nothing_are_two_written_refusals():
    """`_RV_PRICE_ABSENCE`'s own law, which this module cites three times, applied to its own declines:
    never ONE shared reason for TWO causes. A router that RAISED never asked the record; a turn that
    routed nothing asked and found no contract to name. The writer's absence sentence has to be true of
    whichever actually happened."""
    thrown = ro.answer_roster(_Q, _ASOF, contracts=[], qfn=_QFn(), route_error=True)
    quiet = ro.answer_roster(_Q, _ASOF, contracts=[], qfn=_QFn())
    assert ("roster", "route_error") in _declines(thrown)
    assert ("roster", "unrouted") in _declines(quiet)
    d_thrown = thrown["numbers_budget"]["roster_declines"][0]["detail"]
    assert "router failed" in d_thrown and "never asked" in d_thrown
    assert d_thrown != quiet["numbers_budget"]["roster_declines"][0]["detail"]
    assert thrown["numbers_budget"]["returned"] is True     # both still stamp; both still narrate


# == P4 -- THE PER-SLUG ROSTER, FORM A (a named country, the settled marketing year) ==================
def test_p4_the_primary_form_issues_the_four_balance_rows_at_the_settled_year():
    """FORM A on a single-market ask. The scope is `cascade._primary_title` -- silver_psd's OWN surface
    spelling -- and the marketing year is `_settled_my_ceiling`, NOT `max(period)`: measured, the
    su_ratio periods served across the banked arm include MY2026, which is USDA's PROJECTION year at a
    2026-08-12 knowledge date, and `estimate_role` is null on all 371 rows served, so the row carries no
    role to declare. A projection cannot be served under a settled label.

    FOUR READS: su_ratio at the settled year AND at MY-1 (the year-on-year change is computed from those
    two served levels -- see P4e), production and the trade leg at the settled year."""
    q = _QFn()
    res = ro.answer_roster("where does Malaysian palm oil's balance sheet stand",
                           _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=q)
    by = _by_metric(res)
    assert set(by) >= {"su_ratio", "production_mt", "exports_mt"}
    for metric in ("su_ratio", "production_mt", "exports_mt"):
        qd = by[metric]["query"]
        assert qd["table"] == "silver_psd"
        assert qd["country"] == "Malaysia"              # the TABLE surface title, never 'malaysia'
        assert qd["asof"] == _ASOF
    psd_rows = [c for c in res["calls"] if c["query"]["table"] == "silver_psd"]
    assert {str(c["query"]["metric"]) for c in psd_rows} == {
        "su_ratio", "production_mt", "exports_mt", "stocks-to-use ratio change (YoY)"}
    # the settled year on every LEVEL row, and MY-1 present exactly once (the change row's second input)
    levels = [c for c in psd_rows if c["query"]["metric"] == "su_ratio"]
    assert sorted(str(c["query"]["period"]) for c in levels) == [f"MY{_MY - 1}", f"MY{_MY}"]
    for metric in ("production_mt", "exports_mt"):
        assert by[metric]["query"]["period"] == f"MY{_MY}"
    # the SQL is the proof, not the call site: verbatim country equality and the pinned marketing year
    psd = [s for s in q.sqls if "silver_psd" in s and "su_ratio AS value" in s]
    assert len(psd) == 2 and all("country = 'Malaysia'" in s for s in psd)
    assert f"market_year = {_MY}" in psd[0] and f"market_year = {_MY - 1}" in psd[1]
    assert res["numbers_budget"]["roster_form"] == "primary"
    assert res["tables_queried"] == sorted(set(res["tables_queried"]))


def test_p4e_the_form_A_yoy_row_is_window_change_under_the_vintage_fence_never_the_cards_column():
    """REVIEW FATAL-2, CLOSED. The build reviewed served silver_psd's OWN `su_ratio_yoy_delta` column as
    R1's change row and dropped MAJOR-4's fence on two written claims -- that it is "the PUBLISHER's own
    vintage-coherent delta" and that it "cannot span two knowledge dates by construction". THE CARD SAYS
    THE OPPOSITE, in the comment block directly above that metric (tables.yaml:72-83): those are "four
    columns the PRODUCER has ALWAYS written" (our own silver transform, not USDA), and the
    apples-to-apples reading "was true only BY CONSTRUCTION under the retired clock ... Under the honest
    clock wasde_release_month is a CALENDAR month, so THE TWO COMPARED PRINTS CAN BE SEVERAL CALENDAR
    YEARS APART." The fence could not be restored over that column either -- its two endpoints are
    INSIDE it, invisible to any test on the served rows.

    So R1 is design 1.2's shape again: two served levels, `stats.window_change` between them, minted
    only behind `stats.same_vintage`. On a split the change is WITHHELD with its own written reason and
    BOTH levels still stand -- fences correct or compute, never delete."""
    q = _QFn()
    res = ro.answer_roster("where does Malaysian palm oil's balance sheet stand",
                           _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=q)
    # THE COLUMN IS NOT READ AT ALL, on the SQL and in the module's own source.
    assert not [s for s in q.sqls if "su_ratio_yoy_delta" in s]
    assert "su_ratio_yoy_delta" not in open(ro.__file__, encoding="utf-8").read().split(
        "THE YEAR-ON-YEAR ROW")[0]
    yoy = [c for c in res["calls"] if c["query"]["metric"] == "stocks-to-use ratio change (YoY)"]
    assert len(yoy) == 1
    row, qd = yoy[0]["rows"][0], yoy[0]["query"]
    assert qd["period"] == f"MY{_MY - 1}..MY{_MY}" and qd["country"] == "Malaysia"
    assert row["unit"] == ro._card_unit(None, "silver_psd", "su_ratio",
                                        "malaysian_crude_palm_oil_cme") == "ratio"
    assert row["value"] == 0.0                     # the fake serves ONE su_ratio value at both years
    # THE MINT RENDERS IN READER WORDS beside the levels it spans -- no raw slug on the copy surface.
    assert "CME palm oil" in cit.render([cit.from_number(yoy[0], 1)])
    assert "malaysian_crude_palm_oil_cme" not in cit.render([cit.from_number(yoy[0], 1)])
    # ...AND THE FENCE BINDS. Two prints that do not share a release mint NO change, and both levels
    # keep their own stamps.
    split = _QFn(psd_kd={_MY: "2026-08-12", _MY - 1: "2026-05-31"})
    res2 = ro.answer_roster("where does Malaysian palm oil's balance sheet stand",
                            _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=split)
    assert ("su_ratio_yoy", "vintage_split") in _declines(res2)
    assert not [c for c in res2["calls"] if "YoY" in str(c["query"]["metric"])]
    assert len([c for c in res2["calls"] if c["query"]["metric"] == "su_ratio"]) == 2


def test_p4f_a_leg_the_roster_is_about_to_refuse_by_name_never_decides_the_scope_form():
    """REVIEW MAJOR-1. `corn` and `soybeans` are graph base-YAML duplicates that `_mc` reaches, both
    have no `_primary_title`, and both are ALREADY on `_ROSTER_PSD_ABSENT` -- so before the fix a routed
    slug the roster was about to decline by name flipped a single-market US ask onto the WORLD sheet,
    which is the branch design 1.4 reserves for world-relative asks. It is also the exact deck row
    section 5 adds to MEASURE the primary branch, so the arm could land on the wrong branch for its own
    scope-form measurement. The form is decided from the legs that will actually issue balance rows."""
    ask = "where does US corn's balance sheet stand this year"
    assert cq._primary_title("corn") is None and "corn" in ro._ROSTER_PSD_ABSENT
    assert ro.scope_form(ask, ["corn_cbot"]) == "primary"
    assert ro.scope_form(ask, ["corn_cbot", "corn"]) == "primary"       # the screened slug does not vote
    assert ro.scope_form(ask, ["corn_cbot", "soybeans_cbot"]) == "world"  # two REAL legs still do
    q = _QFn(psd_countries=("United States",))
    res = ro.answer_roster(ask, _ASOF, contracts=["corn_cbot", "corn"], qfn=q)
    assert res["numbers_budget"]["roster_form"] == "primary"
    assert ("balance", "psd_absent") in _declines(res)
    assert [s for s in q.sqls if "country = 'United States'" in s]
    assert not [s for s in q.sqls if "silver_psd" in s and "country = " not in s]


def test_p4b_a_miscased_or_absent_scope_serves_nothing_and_is_declined_on_ROWS(monkeypatch):
    """SECTION 12'S CASING LAW, reproduced: `build_sql` emits the caller's country string VERBATIM, so
    only the table surface title serves -- 'united_states' returned ZERO rows on 137 measured reads
    while 'United States' served on 42. AND a mis-cased scope is INDISTINGUISHABLE FROM AN ABSENT ONE
    BY STATUS (every casing control came back `not_known`, never `error`), so the roster's emptiness
    test keys on ROWS and never on status."""
    monkeypatch.setattr(cq, "_primary_title", lambda c: "malaysia")     # the wrong surface form
    res = ro.answer_roster("where does palm stand", _ASOF,
                           contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    assert not [c for c in res["calls"] if (c["query"]["table"] == "silver_psd")]
    assert ("su_ratio", "empty_card") in _declines(res)


def test_p4c_an_unresolved_scope_issues_no_balance_row_at_all(monkeypatch):
    """1.5(c), and it is the K9-2 fix taken at the roster. The judged "manufactured ranking" was a query
    that NAMED NO COUNTRY, served every PSD country and headlined one arbitrary row; the shape is LIVE
    on this deck -- 7 of the 25 arm rows' silver_psd reads carry `country=None` and returned 3,750 to
    4,759 rows apiece, all `ok`. A roster spec is written once and reviewed once, so 'scope is bound' is
    a property of the table rather than a model's habit."""
    # FIRST, THE DECISION ITSELF, and it is PURE (a config read, no lookup): a slug with no primary
    # country never reaches form A at all -- `scope_form` sends the whole turn to the world synthesis,
    # which is section 12's BIND_WORLD_ONLY three (barley, sorghum, sunflower_oil) measured live.
    for slug in ("barley", "sorghum", "sunflower_oil"):
        assert cq._primary_title(slug) is None, slug
        assert ro.scope_form("where does it stand", [slug]) == "world", slug
    # THEN THE BELT BEHIND IT. One form per turn is what keeps the two scales apart, so form A is only
    # entered with a resolvable primary; this fences the case where that ceases to be true.
    monkeypatch.setattr(ro, "scope_form", lambda q_, s_: "primary")
    monkeypatch.setattr(cq, "_primary_title", lambda c: None)
    q = _QFn()
    res = ro.answer_roster("where does palm stand", _ASOF,
                           contracts=["malaysian_crude_palm_oil_cme"], qfn=q)
    assert ("balance", "scope_unresolved") in _declines(res)
    assert not [s2 for s2 in q.sqls if "silver_psd" in s2]  # refused BEFORE any read was spent


def test_p4d_a_slug_psd_does_not_carry_is_screened_by_name_before_any_read():
    """SECTION 12, MEASURED: a per-slug census found 63 distinct silver_psd slugs and NOT cocoa, corn or
    soybeans at any country or period. Screened by NAME, before the reads, exactly as
    `_RV_PRICE_ABSENCE` screens the price leg -- and it is a BALANCE-ROW refusal, never a whole-slug
    one: cocoa IS in `_RV_PRICE_SERIES`, so its price standing still renders."""
    q = _QFn()
    res = ro.answer_roster("where does cocoa stand", _ASOF, contracts=["cocoa"], qfn=q)
    assert ("balance", "psd_absent") in _declines(res)
    assert not [s for s in q.sqls if "silver_psd" in s]
    assert "silver_pink_sheet" in res["tables_queried"]      # R5 renders while R1-R3 refuse
    assert "cocoa" in ro._ROSTER_PSD_ABSENT and "corn" in ro._ROSTER_PSD_ABSENT


# == P5 -- THE FATAL-1 BAR: a ZERO-ROW roster turn puts the marker in the writer's prompt =============
def test_p5_a_zero_row_roster_turn_carries_NUMBERS_BUDGET_MARK_into_the_prompt(monkeypatch):
    """THE PIN THE WHOLE BUILD EXISTS TO PROTECT. At HEAD `_bn = _numbers_budget_note_on() and
    bool(_nc)` -- a ROUND budget -- and 1.6(1) forbids a roster preset from carrying one, so `_nb` was
    None, `_numbers_block` skipped its `if budget is not None` branch, no marker reached the prompt and
    `answer.py`'s marker gate plus its persona mandate never fired. A refusing roster turn would have
    shipped "(none retrieved)" silently. `or _nr` admits the lane; the CLAUSE is rung 1's, verbatim."""
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_R0), flag="on", note="on", route=[])
    assert seen["callee"] == ["roster"]
    assert seen["block_kw"]["budget"]["roster"] is True
    assert seen["block_kw"]["budget"]["returned"] is True     # it ASKED and got nothing; not an outage
    assert an.NUMBERS_BUDGET_MARK in seen["block"]
    assert "SCOPE NOTE" in seen["block"] and "(none retrieved)" in seen["block"]
    assert seen["block"] != seen["block_plain"]               # HEAD would have rendered no clause
    assert seen["out"]["trace"]["numbers_budget"]["lookups"] == 0


def test_p5b_a_roster_turn_that_minted_rows_leaves_the_block_byte_identical(monkeypatch):
    """The other half of 1.6(3): a stamp carrying `returned: True` and no `capped` appends nothing, so
    the writer prompt of a SERVING roster turn is exactly what the same calls render today."""
    served = {"calls": list(_CALLS),
              "numbers_budget": {"roster": True, "lookups": 1, "returned": True, "roster_rows": 1,
                                 "roster_declines": []},
              "tables_queried": ["silver_psd"]}
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_R0), flag="on", note="on",
                   roster=served, route=["corn_cbot"])
    assert seen["block"] == seen["block_plain"]
    assert an.NUMBERS_BUDGET_MARK not in seen["block"]


def test_p5c_the_note_flag_off_keeps_the_refusing_turn_silent_and_unstamped(monkeypatch):
    """TWO FLAGS, NEITHER IMPLYING THE OTHER. The roster flag admits the lane; the NOTE flag is what
    lets the refusal reach the writer. With the note off a refusing roster turn renders HEAD's block
    and stamps no trace column -- never a null column."""
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_R0), flag="on", route=[])
    assert seen["block_kw"] == {"budget": None}
    assert seen["block"] == seen["block_plain"]
    assert "numbers_budget" not in seen["out"]["trace"]


def test_p5d_a_roster_outage_narrates_as_an_outage_and_never_raises(monkeypatch):
    """The outage record's first field is CONDITIONAL for a reachability reason: on this lane `_nc` is
    empty, so HEAD's `int(_nc["max_calls"])` would raise KeyError inside `extra_resolver` and take the
    turn down on exactly the path the branch exists to narrate. `{"roster": True}` states what IS
    known, and the writer gets the OUTAGE sentence -- "the lookup could not be completed" -- rather
    than the EMPTY one, because a leg that never got to ask is not a record that answered with
    nothing."""
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_R0), flag="on", note="on",
                   raise_roster=RuntimeError("the roster lane fell over"), route=["corn_cbot"])
    nb = seen["block_kw"]["budget"]
    assert nb["roster"] is True and nb["returned"] is False and "max_calls" not in nb
    assert "the roster lane fell over" in nb["lane_error"]
    assert an.NUMBERS_BUDGET_MARK in seen["block"] and "could not be completed" in seen["block"]


# == P6 -- THE TWO-COMMODITY UNION, THE WORLD FORM, AND THE SHARED AGGREGATE ==========================
def test_p6_a_two_commodity_question_gets_both_rosters_on_the_world_form():
    """1.4: the roster runs ONCE PER ROUTED SLUG, in the router's order, and the two rosters are
    INDEPENDENT -- leg B's refusal never suppresses leg A's rows. A relative-value ask binds the WORLD
    synthesis on BOTH legs (design 1.4; section 12 measured form B resolving on 33 of 36 slugs against
    form A's 30, so the world branch is the WIDE one and not the special case)."""
    res = ro.answer_roster(_Q, _ASOF,
                           contracts=["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"],
                           qfn=_QFn(scale={"rapeseed_oil_zce": 1.4}))   # two DISTINCT sheets
    assert res["numbers_budget"]["roster_form"] == "world"
    assert not [d for d in res["numbers_budget"]["roster_declines"]
                if d["row"] == "shared_aggregate"]           # distinct aggregates are never folded
    su = [c for c in res["calls"] if c["query"]["metric"] == "stocks-to-use ratio"]
    assert len(su) == 2
    assert {c["query"]["commodity"] for c in su} == {cq._xc_label("malaysian_crude_palm_oil_cme"),
                                                     cq._xc_label("rapeseed_oil_zce")}
    for c in su:
        assert c["rows"][0]["unit"] == "%"              # form B is PRE-SCALED; form A is a bare ratio
        assert c["query"]["country"] is None            # a literal country='World' is never issued
        assert "WORLD total" in c["scope_note"]


def test_p6b_the_world_form_never_issues_the_scope_free_read_that_returns_every_country():
    """SECTION 13'S CORRECTION (refuter MAJOR-1). The world form at design 1.2's literal shape --
    `agg=latest, period=MY, country=None` -- does NOT bind scope: measured, it returns every PSD country
    (67 rows on barley, 74 on sorghum), and a headline row is then one arbitrary country's figure
    wearing a world label. Every world row rides the per-country-latest synthesis instead."""
    q = _QFn()
    ro.answer_roster("how does world palm oil stand", _ASOF,
                     contracts=["malaysian_crude_palm_oil_cme"], qfn=q)
    scope_free = [s for s in q.sqls
                  if "silver_psd" in s and "country = " not in s and "_rn = 1" in s and "LIMIT 1" in s]
    assert scope_free == []


def test_p6c_one_aggregate_two_contracts_is_stated_once(monkeypatch):
    """SECTION 12, MEASURED: world stocks-to-use ratios are NOT slug-distinct -- six collision groups
    cover 19 of the 33 resolving slugs (five corn slugs all 22.911 %, four wheat slugs 34.277 %, canola
    equals french rapeseed at 12.012 %) because those slugs fan onto ONE PSD aggregate sheet. Printing
    it twice is not redundancy: on a relative-value question two identical figures read as a measured
    convergence."""
    res = ro.answer_roster(_Q, _ASOF,
                           contracts=["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"],
                           qfn=_QFn())
    shared = [d for d in res["numbers_budget"]["roster_declines"] if d["row"] == "shared_aggregate"]
    assert shared and shared[0]["reason"] == "one_aggregate_two_contracts"
    # THE ROWS ARE REMOVED, not merely noted: leg B's four balance rows are gone and leg A's stand.
    assert shared[0]["folded"] == 4
    psd = [c for c in res["calls"] if c["query"]["table"] == "silver_psd"]
    assert {c["_roster_slug"] for c in psd} == {"malaysian_crude_palm_oil_cme"}
    assert len(psd) == 4
    note = [c["scope_note"] for c in psd if c.get("scope_note")]
    assert note and "ONE AGGREGATE, TWO CONTRACTS" in note[0]
    assert "make no comparison" in note[0] and "world rapeseed oil" in note[0]
    # ...and R1's own world-basis sentence SURVIVES beside it -- appended, never substituted.
    assert "WORLD total" in note[0]


def test_p6c2_the_fold_note_can_always_name_the_legs_it_folded():
    """REVIEW MAJOR, CLOSED. Both label producers speak the AGGREGATE's name -- which is precisely why
    the two slugs collided -- so `", ".join(...)` printed the SAME STRING TWICE on every collision group
    section 12 measured (soybean_oil_cbot / soybean_oil_dce both 'world soybean oil'; corn_cbot /
    corn_dce / corn_matif all 'world corn'). Six groups over 19 of 33 resolving slugs: the ordinary
    case, on the one prompt-side sentence whose whole job is to say a row was DROPPED.

    `_fold_note` now tries three ordered spellings -- the surface names when they already separate the
    legs, else the CONTRACT-level label where the estate holds one, else the aggregate ONCE plus the
    count. NEVER the same name twice, on any branch."""
    # (a) the collision groups that motivated it -- the surface names ARE identical at HEAD
    assert cq._xc_label("soybean_oil_cbot") == cq._xc_label("soybean_oil_dce") == "world soybean oil"
    assert (ro._leg_label("soybean_oil_cbot", "price")
            == ro._leg_label("soybean_oil_dce", "price") == "world soybean oil")
    # (b) ...and the note separates the legs anyway, because one of them has a contract label -- and
    # the OTHER one is named at the same ALTITUDE (re-fix 2026-09-09, review minor): the nine-board
    # roster is a SUBSET, so the ordinary collision pair has a board label for one leg and not the
    # other, and the missing half used to fall back to `surf[i]` -- the AGGREGATE's own name, the exact
    # string spelling (2) exists to stop using. Seven (pair, surface) cases over five distinct pairs
    # read 'the CBOT soybean oil contract, world soybean oil': one leg a contract, the other apparently
    # the aggregate itself, in the one sentence whose job is to say the two are ONE observation.
    assert cq._RV_EOD_FRESH["soybean_oil_cbot"][1] == "the CBOT soybean oil contract"
    assert "soybean_oil_dce" not in cq._RV_EOD_FRESH          # the half with no board label
    res = ro.answer_roster("soybean oil in Chicago against Dalian", _ASOF,
                           contracts=["soybean_oil_cbot", "soybean_oil_dce"], qfn=_QFn())
    note = [c["scope_note"] for c in res["calls"] if "ONE AGGREGATE" in str(c.get("scope_note"))]
    assert note
    who = note[0].split("ONE AGGREGATE, TWO CONTRACTS: ")[1].split(" resolve to")[0]
    assert who == "the CBOT soybean oil contract, DCE soybean oil"
    assert ro._leg_label("soybean_oil_dce", "price") not in who   # never the shared aggregate's name
    # ...and the same at the OTHER five: a board label where the estate holds one, else the
    # contract-level display name, and NEVER the aggregate both legs share.
    for pair in (("french_wheat_matif", "hard_red_spring_wheat_mgex"),
                 ("hard_red_spring_wheat_mgex", "hard_red_winter_wheat_kcbt"),
                 ("hard_red_spring_wheat_mgex", "soft_red_winter_wheat_cbot"),
                 ("soybean_meal_cbot", "soybean_meal_dce")):
        s = ro._fold_note(list(pair), "world")
        assert "routed for this turn" not in s                 # spelling (2) resolved it
        assert s.count(ro._leg_label(pair[0], "world")) == 0    # ...on neither leg's aggregate name
    # (c) AND WHEN NO LEG HAS ONE, the aggregate is stated ONCE with the count -- never twice.
    for pair in (("corn_dce", "corn_matif"), ("soybean_meal_dce", "soybean_meal_zce")):
        assert ro._leg_label(pair[0], "world") == ro._leg_label(pair[1], "world")
        s = ro._fold_note(list(pair), "world")
        assert s.count(ro._leg_label(pair[0], "world")) == 1
        assert "TWO CONTRACTS" in s and "routed for this turn" in s


def test_p6e_the_fold_is_scoped_to_the_surface_that_collided():
    """The fence that keeps the fold from deleting a real observation. A WORLD collision is evidence
    that two slugs share ONE PSD sheet and says NOTHING about their price benchmarks: palm reads the
    World Bank CPO series and rapeseed oil reads the rapeseed-oil series, two distinct facts whose
    figures may coincide. Without the surface scope a balance collision would delete one of them."""
    res = ro.answer_roster(_Q, _ASOF,
                           contracts=["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"],
                           qfn=_QFn())
    pink = [c for c in res["calls"] if c["query"]["table"] == "silver_pink_sheet"]
    assert {c["_roster_slug"] for c in pink} == {"malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"}
    assert (cq._RV_PRICE_SERIES["malaysian_crude_palm_oil_cme"][0]
            != cq._RV_PRICE_SERIES["rapeseed_oil_zce"][0])


def test_p6f_one_benchmark_two_contracts_folds_the_price_surface_too():
    """SECTION 13's own half of the law, MEASURED: `_RV_PRICE_SERIES` maps 17 slugs onto 15 metrics, so
    soybean_oil_cbot and soybean_oil_dce read the SAME World Bank series (both 1,660.0 on the probe) and
    soybean_meal_cbot and soybean_meal_dce the same (both 398.0). Two contracts, one benchmark."""
    assert (cq._RV_PRICE_SERIES["soybean_oil_cbot"][0]
            == cq._RV_PRICE_SERIES["soybean_oil_dce"][0] == "soybean_oil_usd_t")
    res = ro.answer_roster("soybean oil in Chicago against Dalian", _ASOF,
                           contracts=["soybean_oil_cbot", "soybean_oil_dce"], qfn=_QFn())
    pink = [c for c in res["calls"] if c["query"]["table"] == "silver_pink_sheet"]
    assert {c["_roster_slug"] for c in pink} == {"soybean_oil_cbot"}
    shared = [d for d in res["numbers_budget"]["roster_declines"] if d["row"] == "shared_aggregate"]
    assert any("benchmark" in d["detail"] for d in shared)


def test_p6d_the_world_yoy_row_is_withheld_when_the_two_years_split_their_vintage():
    """MAJOR-4, applied where it actually binds. `TableSpec.group_cols` resolves for silver_psd to
    [leviathan_slug, country, market_year], so EACH marketing year takes its own latest release
    independently, and cascade states it outright -- "PSD vintages are DELTAS, so no single shared
    vintage exists". The two world totals are two independent per-country-latest unions, so
    `stats.same_vintage` (exact string equality, fail-closed on an unstamped input) decides whether a
    change between them may be minted at all. The LEVELS still render with their own stamps."""
    wq = "how does world palm oil's stocks position stand"
    assert ro.scope_form(wq, ["malaysian_crude_palm_oil_cme"]) == "world"
    split = _QFn(world_kd={_MY: "2026-08-12", _MY - 1: "2026-05-31"})
    res = ro.answer_roster(wq, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=split)
    assert ("su_ratio_yoy", "vintage_split") in _declines(res)
    assert not [c for c in res["calls"] if "YoY" in str(c["query"]["metric"])]
    assert [c for c in res["calls"] if c["query"]["metric"] == "stocks-to-use ratio"]
    same = _QFn()
    ok = ro.answer_roster(wq, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=same)
    yoy = [c for c in ok["calls"] if "YoY" in str(c["query"]["metric"])]
    assert len(yoy) == 1 and yoy[0]["rows"][0]["unit"] == "percentage points"


def test_p6g_a_world_R1_failure_still_attempts_the_production_and_trade_rows(monkeypatch):
    """REVIEW MAJOR, CLOSED. `_balance_world` returned early when `_world_su_ratio` came back None, so
    R2 and R3 were never attempted and never counted -- although each is an INDEPENDENT synthesis
    through `_psd_component_rows` + `_world_sum` that could have served. That breaks 1.5(d)'s PER-ROW
    refusal law, and it corrupts the ONE signal this lane offers in exchange for the C2 shape record it
    loses (1.6(4): "`roster_declines` (S2) is the replacement signal") -- two of three balance rows
    vanishing UNCOUNTED on exactly the turns the signal exists to observe."""
    wq = "how does world palm oil's stocks position stand"
    monkeypatch.setattr(cq, "_world_su_ratio", lambda *a, **k: None)
    res = ro.answer_roster(wq, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    d = _declines(res)
    assert ("su_ratio", "world_synthesis_declined") in d
    assert ("su_ratio_yoy", "no_current_year") in d            # its own reason, not R1's
    minted = {c["query"]["metric"] for c in res["calls"] if c["query"]["table"] == "silver_psd"}
    assert minted == {"production", "exports"}                 # R2 and R3 SURVIVED R1's decline
    # ...and the leg still states that its figures are WORLD SUMS: R1 normally carries that sentence,
    # so when R1 declines the first surviving row carries it instead.
    note = [c.get("scope_note") for c in res["calls"] if c.get("scope_note")]
    assert note and any("WORLD totals" in str(n) for n in note)


# == P7 -- THE PRICE ROWS: the board, the benchmark, and their two DIFFERENT refusals =================
def test_p7_a_dark_board_declines_in_its_own_words_and_never_borrows_the_benchmark_reason():
    """MAJOR-3. `_RV_EOD_FRESH` and `_RV_PRICE_ABSENCE` are ORTHOGONAL, not complementary: canola and
    french wheat appear in BOTH, `rapeseed_oil_zce` in NEITHER while the futures card declares its unit
    outright ('CNY/t'). Lending sorghum's "the World Bank discontinued its benchmark after 2020-08" to
    a FUTURES decline would state a false cause -- sorghum has no futures contract on the card at all.
    R4's decline is a SCOPE sentence, and a board whose front-expiry rule cannot run gets its own."""
    res = ro.answer_roster(_Q, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    dark = [d for d in res["numbers_budget"]["roster_declines"] if d["row"] == "settle"]
    assert dark and dark[0]["reason"] == "board_dark" and "open-interest" in dark[0]["detail"]
    off = ro.answer_roster("rapeseed oil", _ASOF, contracts=["rapeseed_oil_zce"], qfn=_QFn())
    d2 = [d for d in off["numbers_budget"]["roster_declines"] if d["row"] == "settle"]
    assert d2 and d2[0]["reason"] == "off_eod_roster"
    assert "World Bank" not in d2[0]["detail"] and "2020-08" not in d2[0]["detail"]
    assert "malaysian_crude_palm_oil_cme" in cq._RV_EOD_FRESH
    assert "rapeseed_oil_zce" not in cq._RV_EOD_FRESH and "rapeseed_oil_zce" in cq._RV_PRICE_SERIES


def test_p7b_the_price_standing_mints_a_level_a_percentile_and_a_sigma_from_ONE_read():
    """R5: one windowed pink-sheet read over `cascade._RV_PRICE_MONTHS` months, then the level (the
    call-record itself) plus a MINTED percentile and sigma computed against that SAME window -- no
    second fetch, each declared in its own unit."""
    q = _QFn()
    res = ro.answer_roster("palm", _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=q)
    pink = {c["query"]["metric"]: c for c in res["calls"]
            if c["query"]["table"] == "silver_pink_sheet"}
    assert set(pink) == {"palm_oil_cpo_usd_t", "benchmark percentile", "benchmark sigma"}
    # THE SERVED LEVEL IS NOT MUTATED. Measured (section 13), the pink-sheet payload carries no unit,
    # and `citations.from_number` already falls back to the CARD for exactly that case -- so the roster
    # declares the unit by REFUSING the row when the card names none (P8), never by writing one onto a
    # served read. The MINTED rows, which have no card row behind them, carry theirs explicitly.
    assert ro._card_unit(None, cq._RV_PRICE_TABLE, "palm_oil_cpo_usd_t") == "USD/mt"
    assert pink["palm_oil_cpo_usd_t"]["rows"][0].get("unit") is None
    assert pink["benchmark percentile"]["rows"][0]["unit"] == "percentile"
    assert pink["benchmark sigma"]["rows"][0]["unit"] == "sigma"
    assert len([s for s in q.sqls if "silver_pink_sheet" in s]) == 1
    label = cq._RV_PRICE_SERIES["malaysian_crude_palm_oil_cme"][1]
    assert all(c["query"]["commodity"] == label for c in res["calls"]
               if c["query"]["metric"] in ("benchmark percentile", "benchmark sigma"))


def test_p7d_the_standing_ranks_the_ROW_THE_LABEL_PRINTS_and_no_process_global_can_move_it():
    """REVIEW FATAL-1, CLOSED, AND THIS IS THE PIN THAT WAS MISSING: P7b asserted the three metric names
    and their unit strings and never the ARITHMETIC against the level.

    The build reviewed took R5's observation through `cascade._headline_row`, which is KILL-SWITCHED on
    the module global `cascade._HEADLINE_ON` -- False by default, returning `rows[0]`, the OLDEST month
    of an ASC 60-month window -- while `citations.from_number` renders the level from
    `max(rows, key=_row_order_key)`, the NEWEST. On this fixture (60 ASC monthly rows rising 800 ->
    1,390) the block handed to the writer read `= 1,390 USD/mt` beside `0.8 percentile` and
    `-1.7 sigma`: the exact inverse of that level's true standing, labelled as this contract's.

    AND IT WAS A RACE, not merely a default. `_HEADLINE_ON` is a PROCESS global written by the walk's
    `quantify()` on the CALLING thread while the roster runs on the numbers pool thread, and serving
    submissions carry `GRAPHRAG_CASCADE_HEADLINE=on` -- so a cold worker's first roster turn read False
    and a warm one True: the same question, two different percentile and sigma figures, on the one lane
    whose entire claim is determinism. Both halves are pinned here."""
    top = _PINK_LO + _PINK_STEP * (_PINK_N - 1)                     # the NEWEST month = the maximum

    def _standing(q):
        res = ro.answer_roster("palm", _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=q)
        return {c["query"]["metric"]: c["rows"][0]["value"] for c in res["calls"]
                if c["query"]["table"] == "silver_pink_sheet"}, res

    got, res = _standing(_QFn())
    # (a) THE LEVEL THE LABEL PRINTS IS THE NEWEST ROW...
    lvl = [c for c in res["calls"] if c["query"]["metric"] == "palm_oil_cpo_usd_t"][0]
    assert ro._shown_row(lvl)["value"] == top
    assert f"{top:,.0f}" in cit.render([cit.from_number(lvl, 1)])
    # (b) ...AND THE TWO STANDINGS RANK THAT SAME ROW. Rising series, newest = maximum, so the
    # percentile is at the TOP of its window and the sigma is POSITIVE. The inverted build printed
    # 0.8 and -1.7 here.
    assert got["benchmark percentile"] > 95.0 and got["benchmark sigma"] > 1.0
    assert got["benchmark percentile"] == round(
        st.percentile(top, [_PINK_LO + _PINK_STEP * i for i in range(_PINK_N)])["value"], 1)
    # (c) NO PROCESS GLOBAL MOVES IT: the two settings of the cascade kill-switch are byte-identical.
    prev = cq._HEADLINE_ON
    try:
        cq._set_headline(False)
        off, _ = _standing(_QFn())
        cq._set_headline(True)
        on, _ = _standing(_QFn())
    finally:
        cq._set_headline(prev)
    assert off == on == got
    # (d) AND THE WINDOW THE STANDINGS NAME IS THE SERVED ROWS' OWN SPAN, not the request's (m2): the
    # card carries a 40-day publication lag, so the request window overstated it at BOTH ends.
    per = [c["query"]["period"] for c in res["calls"] if c["query"]["metric"] == "benchmark sigma"][0]
    assert per == f"{_pink_month(0)}..{_PINK_END}"
    assert per != f"{cq._months_back(_ASOF, cq._RV_PRICE_MONTHS)}..{_ASOF}"
    assert ".." in per                       # citations._period_label would MY-prefix it otherwise
    # (e) ...AND SO DOES THE LEVEL ROW BESIDE THEM -- ONE READ, ONE WINDOW, ONE SPAN IN THE PANEL
    # (review minor, closed in the re-fix 2026-09-09). The level kept `_rv_price_series`'s REQUEST
    # window while the two rows minted OFF IT carried the served one, so R5's three rows named TWO
    # windows and the level's own line contradicted itself inside one sentence: "2021-09-01..2026-09-07
    # = 1,390 USD/mt [60 rows served, covering 2021-10-01..2026-09-01]". A reader comparing the level
    # to its own percentile could not tell whether the two were ranked over the same months.
    assert lvl["query"]["period"] == per
    assert {c["query"]["period"] for c in res["calls"]
            if c["query"]["table"] == "silver_pink_sheet"} == {per}
    block = orch._numbers_block(res["calls"])
    assert f"{cq._months_back(_ASOF, cq._RV_PRICE_MONTHS)}..{_ASOF}" not in block
    assert block.count(f"covering {per}") == 1          # the served label still states its own coverage


def test_p7c_an_off_benchmark_slug_declines_in_the_price_tables_own_written_words():
    """1.5(b): R5 IS the World Bank row, so it keeps `_RV_PRICE_ABSENCE` -- eight slugs, each with a
    reason written for THAT table. It may never be stretched over a second card."""
    res = ro.answer_roster("barley", _ASOF, contracts=["barley"], qfn=_QFn())
    d = [x for x in res["numbers_budget"]["roster_declines"] if x["row"] == "price_standing"]
    assert d and d[0]["reason"] == "no_benchmark"
    assert d[0]["detail"] == cq._RV_PRICE_ABSENCE["barley"]
    assert len(cq._RV_PRICE_ABSENCE) == 8


def test_p7f_a_board_level_absence_names_a_BOARD_and_never_a_world_aggregate():
    """REVIEW MINOR, CLOSED (re-fix 2026-09-09). `_decline_label`'s OWN docstring forbids this sentence
    -- "'no exchange settle for CME palm oil' is exactly true; the same sentence over `_xc_label`'s
    'world malaysian crude palm oil' would attach a world scope to a board's settle" -- and the code
    then did it for every slug off the nine-board roster, which is the ORDINARY case: `off_eod_roster`
    fires precisely when `_RV_EOD_FRESH` holds no label, so the fallback was ALWAYS the world one.
    Measured at HEAD: "no exchange settle for world rapeseed oil". A settle is a board's figure; the
    absence of one is a board's fact; the sentence now names a BOARD."""
    res = ro.answer_roster("rapeseed oil", _ASOF, contracts=["rapeseed_oil_zce"], qfn=_QFn())
    note = [c["scope_note"] for c in res["calls"] if "WITHHELD ON THIS TURN" in str(c.get("scope_note"))]
    assert note and "no exchange settle for ZCE rapeseed oil" in note[0]
    assert cq._xc_label("rapeseed_oil_zce") == "world rapeseed oil"
    assert "no exchange settle for world rapeseed oil" not in note[0]
    # THE OTHER TWO ALTITUDES ARE UNTOUCHED, and that is the fence: a BALANCE row's world label and a
    # BENCHMARK row's series name ARE the scope those rows would have carried, so they keep it.
    assert ro._decline_label("settle", "malaysian_crude_palm_oil_cme") == "CME palm oil"   # board first
    assert ro._decline_label(ro._SU, "rapeseed_oil_zce") == "world rapeseed oil"
    assert ro._decline_label("price_standing", "soybean_oil_dce") == "world soybean oil"
    # ...and an unresolvable name is "" rather than a de-underscored slug reaching reader prose.
    assert ro._contract_name("corn_dce") == "" and ro._decline_label("settle", "corn_dce") == "world corn"


# == P8 -- THE UNIT FENCE (1.3 UNIT / 1.5(e)) ========================================================
def test_p8_a_row_whose_card_declares_no_unit_is_refused_not_scaled(monkeypatch):
    """MEASURED (section 13, 90 primary + 9 world reads): the silver_psd PAYLOAD carries NO unit on ANY
    metric, so the CARD's declaration is the whole of the roster's unit knowledge. A row it cannot name
    a unit for is declined rather than printed on a bare scale, and the refusal is observable --
    `unit_mismatch_guard` is the trace key whose PRESENCE means a fire."""
    ask = "where does Malaysian palm stand"
    clean = ro.answer_roster(ask, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    assert clean["unit_mismatch_guard"] is None      # absent, never a null column, when it did not fire
    assert [c for c in clean["calls"] if c["query"]["metric"] == "production_mt"]
    real = ro._card_unit

    def _blind(reg, table, metric, slug=None):
        return "" if metric == "production_mt" else real(reg, table, metric, slug)
    monkeypatch.setattr(ro, "_card_unit", _blind)
    res = ro.answer_roster(ask, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    assert ("production_mt", "unit_undeclared") in _declines(res)
    assert not [c for c in res["calls"] if c["query"]["metric"] == "production_mt"]
    assert any("declares no unit" in x for x in res["unit_mismatch_guard"])


def test_p8b_the_roster_never_re_mints_a_served_read_through_the_derived_render_table():
    """MAJOR-1: `derived._dv_call` indexes `DV_RENDER_METRICS` directly and that dict has exactly
    THIRTEEN keys, none of them production, exports/imports, a pink-sheet LEVEL or a YoY delta -- so
    four of this roster's rows would raise KeyError -- and it additionally stamps `country: None` and
    `table: "derived"` over the served payload, erasing the very scope binding 1.5(c) exists to make.
    The roster keeps its `fetch_window` records and declares units itself."""
    src = (ro.__file__ or "")
    body = open(src, encoding="utf-8").read()
    assert "_dv_call" not in body.replace("_dv_call`", "").replace("`_dv_call", "")
    res = ro.answer_roster("where does Malaysian palm stand", _ASOF,
                           contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    assert all(c["query"]["table"] != "derived" for c in res["calls"])


# == P9 -- THE RETURN SHAPE `_resolve` READS =========================================================
def test_p9_the_roster_returns_the_full_shape_and_None_only_where_it_is_by_design():
    """1.6(4). `_resolve` copies `pattern_records`, then a fixed six-key tuple, then `numbers_budget`
    and `_ms_numbers`. The roster MINTS `calls`, `tables_queried`, `unit_mismatch_guard` and
    `numbers_budget`. It reads None BY DESIGN for `fork_basis` (`answer_numbers` mints none either, and
    the copy-back is guarded `is not None`), `pattern_records` (no ledger leg here) and the three C2
    shape keys -- and THAT LAST ONE IS A REAL LOSS, not a null column: the question-shape record goes
    dark on every roster turn, which is why `roster_declines` is stamped as the replacement signal."""
    res = ro.answer_roster(_Q, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    for k in ("calls", "tables_queried", "numbers_budget", "unit_mismatch_guard", "_ms_roster",
              "fork_basis", "pattern_records", "question_shape", "shape_metric_states",
              "shape_decline_guard"):
        assert k in res, k
    for k in ("fork_basis", "pattern_records", "question_shape", "shape_metric_states",
              "shape_decline_guard"):
        assert res[k] is None, k
    b = res["numbers_budget"]
    assert b["roster"] is True and b["returned"] is True and b["lookups"] == len(res["calls"])
    assert isinstance(b["roster_declines"], list) and isinstance(b["roster_rows"], int)


def test_p9b_the_hybrid_join_copies_the_census_and_stamps_the_lane(monkeypatch):
    seen = _hybrid(monkeypatch, mode_knobs=rm.knobs(rm.QUICK_R0), flag="on", note="on",
                   roster={"calls": list(_CALLS), "tables_queried": ["silver_psd"],
                           "unit_mismatch_guard": None,
                           "numbers_budget": {"roster": True, "lookups": 1, "returned": True}},
                   route=["corn_cbot"])
    tr = seen["out"]["trace"]
    assert tr["tables_queried"] == ["silver_psd"]
    assert tr["numbers_budget"]["roster"] is True
    assert seen["out"]["number_calls"] == list(_CALLS)


# == P10 -- THE TWO-SLUG CUT =========================================================================
def test_p10_the_roster_takes_the_routed_pair_and_no_more():
    """SECTION 13, refuter MAJOR-2, MEASURED over all 14 deck rows: `_mc` filters on contract membership
    only and returns 4-11 slugs per relative-value question (p50 8). At 5-8 reads a slug that is a
    40-read wave and ~125 s sequential on the Athena column -- WORSE than the 65 s agent leg this rung
    replaces. The node-diverse cut to two lives on the ANSWER path, not on the hoisted `_mc` block, so
    the roster takes it itself or it is a regression."""
    assert ro.ROSTER_CONTRACT_CAP == 2
    res = ro.answer_roster(_Q, _ASOF, qfn=_QFn(),
                           contracts=["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce",
                                      "soybeans_cbot", "corn_cbot"])
    labels = {c["query"]["commodity"] for c in res["calls"]}
    assert cq._xc_label("soybeans_cbot") not in labels and cq._xc_label("corn_cbot") not in labels


def test_p10b_one_slug_routed_TWICE_serves_exactly_what_one_leg_serves(monkeypatch):
    """THE STANDING DEFECT (verifier, re-fix 2026-09-09), and it was a fence DELETING the only copy of a
    figure -- the one outcome the fold doctrine forbids.

    `_mc` filters on contract MEMBERSHIP and promises no SET, so one slug can arrive here twice. The
    roster then built a collision group of [x, x], took `keep, drop = group[0], set(group[1:])` -- which
    puts the KEEPER in the drop set -- and the twin filter removed the keeper's own rows. MEASURED on
    the palm leg: `contracts=[palm, palm]` SERVED six pink-sheet rows (three per leg) and shipped ZERO,
    `_numbers_block` rendered "(none retrieved)" for a leg that had rows, and the fold note was never
    written either (it hangs on a surviving call whose `_roster_slug` is the keeper, and none survived).
    The world half inverted the other way: `_collide` keys by SLUG, so the duplicate collapsed to ONE
    key, no group of two ever formed, and the identical world balance rows printed TWICE unfolded --
    one fact stated as two, on exactly the relative-value question the fold exists for.

    THE FIX IS AT THE ENTRY: the routed slugs are de-duplicated ONCE, order-preserving, BEFORE the
    two-slug cut, and the fold's drop set excludes the keeper by construction as the belt."""
    a_q, b_q = _QFn(), _QFn()
    one = ro.answer_roster(_Q, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=a_q)
    two = ro.answer_roster(_Q, _ASOF, contracts=["malaysian_crude_palm_oil_cme",
                                                 "malaysian_crude_palm_oil_cme"], qfn=b_q)
    # (a) THE SAME READS, THE SAME ROWS, THE SAME BLOCK -- byte for byte, not merely non-empty.
    assert b_q.sqls == a_q.sqls
    assert orch._numbers_block(two["calls"]) == orch._numbers_block(one["calls"])
    assert _declines(two) == _declines(one)
    assert two["tables_queried"] == one["tables_queried"] == ["silver_pink_sheet", "silver_psd"]
    # (b) THE ROWS THE DEFECT DELETED: the pink-sheet leg the fold used to empty out.
    pink = [c for c in two["calls"] if c["query"]["table"] == "silver_pink_sheet"]
    assert len(pink) == 3 and {c["_roster_slug"] for c in pink} == {"malaysian_crude_palm_oil_cme"}
    assert "(none retrieved)" not in orch._numbers_block(two["calls"])
    # (c) ...and no fold is claimed over a leg that was never a second leg.
    assert not [d for d in two["numbers_budget"]["roster_declines"] if d["row"] == "shared_aggregate"]
    assert not [c for c in two["calls"] if "ONE AGGREGATE" in str(c.get("scope_note"))]
    # (d) THE WORLD SURFACE, the half that printed one fact twice: one set of rows, not two.
    wq = "how do world palm oil's stocks stand"
    w = ro.answer_roster(wq, _ASOF, contracts=["malaysian_crude_palm_oil_cme",
                                               "malaysian_crude_palm_oil_cme"], qfn=_QFn())
    psd = [c for c in w["calls"] if c["query"]["table"] == "silver_psd"]
    assert len(psd) == 4 and len({(c["query"]["metric"], c["query"]["period"]) for c in psd}) == 4
    # (e) A GENUINE PAIR SHARING ONE AGGREGATE STILL FOLDS, and the note still names BOTH legs.
    pair = ro.answer_roster("soybean oil in Chicago against Dalian", _ASOF,
                            contracts=["soybean_oil_cbot", "soybean_oil_dce"], qfn=_QFn())
    note = [c["scope_note"] for c in pair["calls"] if "ONE AGGREGATE" in str(c.get("scope_note"))]
    assert note and "the CBOT soybean oil contract, DCE soybean oil" in note[0]
    assert len([c for c in pair["calls"] if c["query"]["table"] == "silver_pink_sheet"]) == 3
    # (f) THE CUT APPLIES AFTER THE DE-DUP, so a duplicate never spends the pair on one contract.
    both = ro.answer_roster(_Q, _ASOF, qfn=_QFn(),
                            contracts=["malaysian_crude_palm_oil_cme",
                                       "malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"])
    assert {c["_roster_slug"] for c in both["calls"]} == {"malaysian_crude_palm_oil_cme",
                                                          "rapeseed_oil_zce"}


# == P11 -- 1.5(f): THE UNSETTLED MARKETING YEAR, AND THE NEVER-RAISES FLOOR ==========================
def test_p11_a_projection_year_ask_is_refused_by_name_and_never_answered_with_another_year():
    """1.5(f), and it is FATAL-2's product half. The roster serves `_settled_my_ceiling` and only that,
    so a question ABOUT the projection year would otherwise be handed the previous year under its own
    label -- the same substitution the marketing-year law exists to stop, one seam later. MEASURED: at
    a 2026-08-12 knowledge date silver_psd serves MY2026 (USDA's projection) and `estimate_role` is
    NULL on all 371 rows served across the five arms, so the row carries no field that could declare
    it. The refusal says so in words and the escalation is the product answer.

    AMBIGUITY FAILS TOWARD SERVING, the `asked_month_window` law: a bare "this year" is not a
    marketing-year token -- it routinely means the settled year in trade prose -- so refusing on it
    would decline the roster's most ordinary ask."""
    assert cq._settled_my_ceiling("corn_cbot", _ASOF) == 2025
    for q in ("how does the 2026/27 corn balance look", "what does MY2026 look like for corn",
              "the new-crop corn balance sheet", "what is the current marketing year balance"):
        assert ro.asks_projection_year(q, "corn_cbot", _ASOF), q
    for q in ("where does US corn's balance sheet stand", "how did corn do in 2024/25",
              "where does corn stand this year", _Q):
        assert not ro.asks_projection_year(q, "corn_cbot", _ASOF), q
    # REVIEW m6, CLOSED: the split form is a MARKETING YEAR only when the second half is the SUCCESSOR
    # of the first. Before the fix a bare ISO 'YYYY-MM' matched -- '2026-09' parsed as year 2026,
    # second '09' -- so a question merely QUOTING a month at or after the covering year took the 1.5(f)
    # refusal on a token that is not a marketing year, i.e. it failed toward REFUSING, which is the
    # wrong side of the `asked_month_window` law the matcher's own note cites.
    for q in ("what happened to corn on 2026-09-01", "corn prices since 2026-09",
              "the 2026-01 print for corn"):
        assert not ro.asks_projection_year(q, "corn_cbot", _ASOF), q
    for q in ("the 2026/27 corn balance", "the 2026-2027 corn balance"):
        assert ro.asks_projection_year(q, "corn_cbot", _ASOF), q
    fake = _QFn()
    res = ro.answer_roster("how does the 2026/27 corn balance look", _ASOF,
                           contracts=["corn_cbot"], qfn=fake)
    d = [x for x in res["numbers_budget"]["roster_declines"] if x["row"] == "balance"]
    assert d and d[0]["reason"] == "projection_year"
    assert "has not closed" in d[0]["detail"] and "MY2025" in d[0]["detail"]
    assert not [s for s in fake.sqls if "silver_psd" in s]      # refused BEFORE any read was spent


def test_p11b_the_roster_never_raises_and_always_stamps_a_record():
    """THE FLOOR. Every read is `cascade.fetch_window`, which degrades to `rows=[]` on any failure, and
    every synthesis is wrapped -- so a lookup layer that is entirely broken produces a REFUSAL with a
    written reason, not an exception. That matters beyond tidiness: `numbers_budget` is what makes the
    empty-leg SCOPE NOTE reachable at all (P5), so a roster that raised instead of stamping would take
    the narration down with it."""
    def _boom(sql):
        raise RuntimeError("the query layer is down")
    res = ro.answer_roster(_Q, _ASOF, contracts=["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"],
                           qfn=_boom)
    assert res["calls"] == [] and res["tables_queried"] == []
    assert res["numbers_budget"]["returned"] is True and res["numbers_budget"]["lookups"] == 0
    assert res["numbers_budget"]["roster_declines"]
    # ...and the block that refusal renders carries the marker, which is the whole of P5's claim
    assert an.NUMBERS_BUDGET_MARK in orch._numbers_block(res["calls"],
                                                         budget=res["numbers_budget"])


def test_p11c_the_never_raises_floor_covers_the_TWO_PATHS_THAT_SAT_OUTSIDE_IT(monkeypatch):
    """REVIEW m1, CLOSED. `answer_roster`'s floor said "NEVER RAISES" absolutely and P11b tested only a
    raising `qfn` -- which `fetch_window` already swallows by contract, so the pin could not fail for
    the property it named. MEASURED: two paths sat outside every guard and propagated.

      (a) `reg = reg or _registry()` -- an unloadable registry raised RuntimeError.
      (b) an `asof` that does not parse -- `cascade._months_back` (via `_settled_my_ceiling` and
          `_rv_price_series`) raised ValueError.

    Both now land on a written `lane_error` decline with the budget record stamped, which is what keeps
    the writer's absence sentence reachable at all."""
    bad = ro.answer_roster(_Q, "not-a-date", contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    assert ("roster", "lane_error") in _declines(bad)
    assert bad["numbers_budget"]["returned"] is True and bad["calls"] == []
    assert an.NUMBERS_BUDGET_MARK in orch._numbers_block(bad["calls"], budget=bad["numbers_budget"])

    def _no_registry():
        raise RuntimeError("the registry cannot be loaded")
    monkeypatch.setattr(ro, "_registry", _no_registry)
    res = ro.answer_roster(_Q, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    assert ("roster", "lane_error") in _declines(res)
    assert res["numbers_budget"]["returned"] is True


# == P12 -- THE PARTIAL REFUSAL REACHES THE WRITER ====================================================
def test_p12_a_partial_refusal_is_narrated_and_not_only_counted():
    """REVIEW MAJOR, CLOSED. `_numbers_block` reads `budget['returned']`, `budget['capped']` and the
    calls' `scope_note`; `roster_declines` is rendered NOWHERE, so only the ALL-EMPTY turn narrated.
    MEASURED before the fix: a turn that minted rows AND carried declines rendered a block BYTE-IDENTICAL
    to `_numbers_block(calls)` -- no marker, no absence sentence. The design's own worked example is that
    shape: cocoa refuses R1-R3 by NAME and R5 renders, so a cocoa turn shipped a price standing and never
    told the writer the balance sheet was refused. Design 1.5 opens "six refusals, each with its own
    written reason SO THE WRITER'S ABSENCE NARRATION FIRES ON A TRUE SENTENCE".

    NO NEW PROMPT SEAM: the sentence rides the EXISTING `scope_note` channel the fold already uses."""
    res = ro.answer_roster("where does cocoa stand", _ASOF, contracts=["cocoa"], qfn=_QFn())
    assert res["calls"]                                    # R5 rendered...
    assert ("balance", "psd_absent") in _declines(res)     # ...while R1-R3 refused by name
    block = orch._numbers_block(res["calls"])
    assert "SCOPE NOTE" in block and "WITHHELD ON THIS TURN" in block
    assert "no balance-sheet rows at all" in block
    assert "no balance sheet is published for it on this sheet" in block
    assert "put no estimate, no proxy" in block
    # READER WORDS ONLY -- no raw slug ever reaches the writer's copy surface through this sentence.
    assert "_cme" not in block and "_cbot" not in block
    # AND A TURN WITH NOTHING TO WITHHOLD IS BYTE-IDENTICAL: the note fires on a refusal, never as decor.
    clean = [c for c in res["calls"]]
    for c in clean:
        c.pop("scope_note", None)
    assert orch._numbers_block(clean) == "SILVER NUMBERS (observed values, as-known at asof):\n" + \
        cit.render(cit.unify(None, clean))


def test_p12b_the_absence_sentence_never_fires_without_a_narratable_refusal():
    """The other half: `_carry_absences` appends nothing when nothing was withheld, and nothing at all
    when there is no call to hang it on (the empty leg already narrates through the budget clause)."""
    calls: list = [dict(_CALLS[0])]
    ro._carry_absences(calls, [])
    assert "scope_note" not in calls[0]
    # the two trace-only records are NOT absences: the fold carries its own sentence, and a vintage
    # split withheld no figure -- every row already prints its own stamp.
    ro._carry_absences(calls, [{"row": "shared_aggregate", "reason": "one_aggregate_two_contracts"},
                               {"row": "balance_vintage", "reason": "vintage_split"}])
    assert "scope_note" not in calls[0]
    ro._carry_absences([], [{"row": "settle", "slug": "corn_cbot", "reason": "board_dark"}])  # no crash


def test_p12c_the_duration_rides_the_record_that_is_actually_surfaced():
    """REVIEW minor. `_ms_roster` was DEAD telemetry: `_resolve` copies a fixed six-key tuple plus
    `numbers_budget` and `_ms_numbers`, and `_numbers()` stamps `_ms_numbers` itself with the thread
    duration on every path -- so section 12's owed `ms_roster` instrument was unreadable by the arm.
    It now rides `numbers_budget`, which IS surfaced, and both stamps are the same measurement."""
    res = ro.answer_roster(_Q, _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=_QFn())
    assert res["numbers_budget"]["roster_ms"] == res["_ms_roster"]
    assert isinstance(res["numbers_budget"]["roster_ms"], int)


def test_p13_the_read_count_is_measured_and_not_asserted():
    """DESIGN 1.2 states 5 reads per leg and 10-16 on the pessimistic two-commodity case; review m5
    asked for the band to be measured rather than repeated. Form A now issues FOUR PSD reads -- su_ratio
    at the settled year AND at MY-1, which is what pays for the year-on-year vintage fence -- so it is
    SIX per leg, one over. It is also a SINGLE-leg form by construction: `scope_form` takes the world
    branch on any second balance-eligible leg, so the overage never doubles."""
    q = _QFn()
    ro.answer_roster("where does Malaysian palm oil's balance sheet stand", _ASOF,
                     contracts=["malaysian_crude_palm_oil_cme"], qfn=q)
    assert len(q.sqls) == 6                                    # 4 PSD + the board + the benchmark
    assert len([s for s in q.sqls if "silver_psd" in s]) == 4
    q2 = _QFn(scale={"rapeseed_oil_zce": 1.4})
    ro.answer_roster(_Q, _ASOF, contracts=["malaysian_crude_palm_oil_cme", "rapeseed_oil_zce"], qfn=q2)
    assert 10 <= len(q2.sqls) <= 16                            # the design's own pessimistic band
    q3 = _QFn(psd_countries=("United States",))
    ro.answer_roster("where does US corn stand against soybeans", _ASOF,
                     contracts=["corn_cbot", "soybeans_cbot"], qfn=q3)
    assert 10 <= len(q3.sqls) <= 16                            # ...with R6's lane firing too


def test_p14_every_refusal_carries_a_written_reason_and_a_narratable_one():
    """DESIGN 1.5's PREMISE, pinned structurally rather than case by case: "six refusals, each with its
    own written reason SO THE WRITER'S ABSENCE NARRATION FIRES ON A TRUE SENTENCE rather than a shared
    one". Two properties, both of which a new decline site could silently break --

      (a) EVERY decline the module can emit carries a `detail` sentence (review minor: four sites did
          not, and were trace-only shrugs), and
      (b) every REASON it can emit has reader words in `_ABSENCE_WHY`, or the absence would be counted
          and never narrated -- the very defect P12 closes.

    Read off the SOURCE, so a decline site added tomorrow without either is caught the day it lands.
    ONE-SIDED BY CONSTRUCTION and said so rather than left to be discovered: the row half matches only
    LITERAL row names, so a site that names its row through a variable (`{"row": metric, ...}`) is not
    seen by it. It is a tripwire on the ordinary shape, not an exhaustive census -- the REASON half,
    which is a literal at every site, is the exhaustive one."""
    body = open(ro.__file__, encoding="utf-8").read()
    appends = re.findall(r"declines\.append\(\{(.*?)\}\)", body, re.S)
    assert len(appends) >= 20
    assert not [a for a in appends if '"detail"' not in a]
    reasons = set(re.findall(r'"reason":\s*"([a-z_]+)"', body))
    assert len(reasons) >= 15
    assert reasons - set(ro._ABSENCE_WHY) - ro._ABSENCE_SKIP == set()
    # ...and every ROW name the module declines under is spoken in reader words too.
    rows = set(re.findall(r'declines\.append\(\{"row":\s*"([a-z_]+)"', body))
    assert rows - set(ro._ABSENCE_ROWS) - ro._ABSENCE_SKIP == set()


def test_p7e_the_standing_is_INDEPENDENT_of_the_order_the_rows_arrive_in():
    """The second-order half of FATAL-1. `cascade._rv_axes` returns rows AS FETCHED, and the ASC total
    order it relies on is `fetch_window`'s DEFAULT rather than its only behaviour -- `futures_newest_first`
    compiles a DESC order, and no call in this module threads it, so a later wave that did would silently
    invert this standing. `cascade._regional_series` already took this decision on this ground ("Rows are
    SORTED by the `period` extra rather than trusting fetch order (a defensive improvement over
    _rv_axes, pinned)"). Same read, reversed: the same three figures."""
    class _Rev(_QFn):
        def __call__(self, sql: str):
            rows = super().__call__(sql)
            return list(reversed(rows)) if "silver_pink_sheet" in sql else rows

    def _figs(q):
        res = ro.answer_roster("palm", _ASOF, contracts=["malaysian_crude_palm_oil_cme"], qfn=q)
        return {c["query"]["metric"]: (c["rows"][0]["value"], c["query"]["period"])
                for c in res["calls"] if c["query"]["table"] == "silver_pink_sheet"
                and c["query"]["metric"] != "palm_oil_cpo_usd_t"}
    asc, desc = _figs(_QFn()), _figs(_Rev())
    assert asc == desc and asc["benchmark sigma"][0] > 1.0
