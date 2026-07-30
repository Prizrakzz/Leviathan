"""PRICE_AND_PLAYBOOKS W1.0 -- silver_futures_eod surface tests. Pure/hermetic: no AWS, no LLM, no pg.

Covers the things W1.0 shipped and that a later wave could silently break:
  * the SERVING STATE -- since the W3 flip (2026-07-30) the table is whitelisted and LOADS, so these
    tests pin the INVERSE of what they pinned through W1/W2: served, reachable from the tool schema
    and the router, with the env kill-switch as the fail-closed rollback lever;
  * the COVERAGE GUARD -- what makes the flip safe. Every window is routed against the MEASURED
    per-contract floor before any SQL compiles: serve / a legacy level carrying the provenance
    sentence / a VERBATIM decline for a straddling window or an uncovered contract;
  * the THREE-WAY unit bind -- CONTRACT_MAP projection == the tracked lint constant == the card's
    unit_overrides, with drift in EACH of the three directions proven to fail the build;
  * the DAG-catalog mapping -- build_catalog raises on an unmapped table, so D1 without D2 is a
    build break, and the new family must not swallow the live yfinance table;
  * the F010 contract shape -- natural key, registered/forbidden/registered-partition, the INV-2
    column ORDER (declaration order IS writer order), and the nullability pair that makes a NULL
    contract_month legal only for the CEPEA cash references.
"""
from __future__ import annotations

import copy
from datetime import date

import pytest

from leviathan.graphrag import config_check as cc
from leviathan.graphrag.numbers import agent as na
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R
from leviathan.silver import futures_eod_contracts as FC

TABLE = "silver_futures_eod"


# -- the serving state (the W1/W2 FENCE, inverted at the 2026-07-30 flip) --------------------------
# These four tests pinned the fence -- whitelist-absent, unserved, every build_sql lookup raising
# KeyError -- for as long as no producer had written a row. They were INVERTED rather than deleted (the
# arming-pin precedent): the protective intent is unchanged, it just points at the post-flip invariant.
# What must stay true is not "the card is hidden" but "the card cannot serve an unattributable or
# unreachable answer", so each one now pins its half of that: served AND reachable, still fail-closed
# where it always was (an unattributable lookup, and the env rollback lever), and a re-added fence
# entry failing the build instead of silently force-dropping a live table.
class TestServedAndReachable:
    def test_registered_in_raw_yaml_and_whitelist_present(self):
        # the card EXISTS (so the lint, the F010 reconcile and the DDL pins all have something to
        # bind) and is no longer fenced out of serving. Both halves still matter -- a whitelist entry
        # over an absent card would be a no-op symbol either way.
        doc = cc._load("numbers/tables.yaml")
        assert TABLE in (doc.get("tables") or {})
        assert TABLE not in R.WHITELIST_ABSENT_DEFAULT

    def test_present_in_the_served_registry_and_the_tool_enum(self):
        reg = R.load_registry()
        assert TABLE in reg.tables
        # the agent's tool enum IS sorted(reg.tables) -- so the table can now be named in a tool call.
        assert TABLE in na._visible_tables(reg)
        assert TABLE in na.tool_schema(reg)["input_schema"]["properties"]["table"]["enum"]

    def test_the_delivery_month_dimension_is_reachable_from_the_model(self):
        # THE reason the flip was one atomic change: a served card whose delivery month the schema
        # never names answers every December ask with the nearest listed expiry, silently.
        props = na.tool_schema(R.load_registry())["input_schema"]["properties"]
        desc = props["contract_month"]["description"]
        assert "YYYY-MM" in desc                       # the single-expiry form
        assert "comma-separated" in desc               # ...and the CURVE form
        assert "the price" in desc                     # a bare level is never quoted as "the price"

    def test_the_router_knows_the_capability_exists(self):
        from leviathan.graphrag import dispatch as dp
        purpose = next(t.purpose for t in dp.REGISTRY if t.name == "numbers")
        assert "TERM STRUCTURE" in purpose or "term structure" in purpose.lower()
        assert "curve" in purpose.lower()
        assert "futures_eod" in dp.family_names()      # DERIVED from the registry, never hardcoded

    def test_build_sql_still_fails_closed_where_it_always_did(self):
        # The registry-routed lookup now COMPILES (that IS the flip) -- but the two fail-closed paths
        # this test was born to protect are untouched: an unattributable lookup (no contract, so the
        # 31-slug unit_overrides cannot be resolved) still raises, and the env kill-switch still
        # restores the KeyError for a single-table rollback with no redeploy.
        sql = Q.build_sql(Q.NumberQuery(table=TABLE, metric="settle", asof="2026-07-01",
                                        commodity="corn_cbot", agg="latest"))
        assert "leviathan_slug = 'corn_cbot'" in sql
        with pytest.raises(ValueError, match="unit_overrides"):
            Q.build_sql(Q.NumberQuery(table=TABLE, metric="settle", asof="2026-07-01", agg="latest"))

    def test_the_env_kill_switch_is_the_post_flip_rollback_lever(self, monkeypatch):
        monkeypatch.setenv("GRAPHRAG_NUMBERS_DISABLE", TABLE)
        R.load_registry.cache_clear()
        try:
            assert TABLE in R._disabled_tables()
            assert TABLE not in R.load_registry().tables
            with pytest.raises(KeyError):
                Q.build_sql(Q.NumberQuery(table=TABLE, metric="settle", asof="2026-07-01",
                                          commodity="corn_cbot", agg="latest"))
        finally:
            monkeypatch.undo()
            R.load_registry.cache_clear()

    def test_the_fence_set_survives_the_flip_empty(self):
        # the set is EMPTIED, not deleted: the next table registered ahead of its producer needs it,
        # and the (a)-(d) flip checklist recorded at that site is the part worth keeping. It also
        # stays DISJOINT from the env kill-switch -- the union happens once, in load_registry.
        assert R.WHITELIST_ABSENT_DEFAULT == frozenset()
        assert TABLE not in R._disabled_tables()


# =================================================================================================
# W3.2 -- THE COVERAGE GUARD. This is what makes the whitelist flip safe: a served table answers
# whatever window it is handed, including one that begins before its first per-contract row exists.
# The floors are MEASURED (PRICE_COVERAGE_START) and the verdict comes from ONE function, covers(),
# which the served path CALLS -- so serve / legacy-level-with-the-provenance-sentence / DECLINE is
# decided before any SQL compiles, and an uncovered contract or date declines VERBATIM.
# =================================================================================================
def _q(**kw) -> Q.NumberQuery:
    base = dict(table=TABLE, metric="settle", asof="2026-07-15", commodity="corn_cbot", agg="latest")
    base.update(kw)
    return Q.NumberQuery(**base)


_CORN_FLOOR = "2010-06-06"


class TestCoverageRouting:
    def test_a_covered_read_serves_untouched(self):
        assert na.futures_eod_route(_q()) == ("serve", _CORN_FLOOR)
        assert na.futures_eod_route(_q(agg="series", period_start="2020-01-02",
                                       period_end="2020-03-02")) == ("serve", _CORN_FLOOR)

    def test_a_window_entirely_before_the_floor_routes_to_the_legacy_level(self):
        assert na.futures_eod_route(_q(agg="series", period_start="2005-01-03",
                                       period_end="2005-06-30")) == ("legacy", _CORN_FLOOR)

    def test_a_straddling_window_declines(self):
        # the rule that matters: joining a per-expiry series onto a roll-spliced continuous one gives a
        # series that means neither thing, and the join is invisible in the output.
        assert na.futures_eod_route(_q(agg="series", period_start="2009-01-02",
                                       period_end="2012-01-03")) == ("straddle", _CORN_FLOOR)

    def test_an_unlanded_venue_is_uncovered_never_permissive(self):
        # the three W1c browser venues have no measured floor at all; coverage_start_for RAISES rather
        # than defaulting, so "no entry" can never be read as "covered since forever".
        assert na.futures_eod_route(_q(commodity="palm_olein_dce")) == ("uncovered", None)

    def test_a_pre_coverage_ask_with_no_legacy_series_is_uncovered(self):
        # CZCE begins 2015-10-08 and the retiring continuous card carries 12 contracts, none of them
        # CZCE -- so there is no legacy level to fall back to. Declining beats a silent empty read.
        assert na.futures_eod_route(_q(commodity="rapeseed_meal_zce", agg="series",
                                       period_start="2005-01-03", period_end="2006-01-03")) == (
            "uncovered", "2015-10-08")

    def test_every_other_table_is_a_no_op(self):
        other = Q.NumberQuery(table="silver_psd", metric="production", asof="2026-07-15",
                              commodity="corn", period="2024")
        assert na.futures_eod_route(other) == ("serve", None)

    def test_a_commodity_less_lookup_is_left_to_the_builders_own_fail_closed_guards(self):
        assert na.futures_eod_route(Q.NumberQuery(table=TABLE, metric="settle",
                                                  asof="2026-07-15")) == ("serve", None)

    def test_an_unwindowed_read_is_a_point_at_the_asof(self):
        assert na.futures_eod_window(_q()) == (date(2026, 7, 15), date(2026, 7, 15))
        assert na.futures_eod_route(_q(asof="2005-06-01")) == ("legacy", _CORN_FLOOR)

    def test_the_window_is_capped_at_the_asof(self):
        # a coverage verdict must describe the read that will ACTUALLY run, and the leakage guard caps
        # it at the as-of regardless of what the model asked for.
        assert na.futures_eod_window(_q(period_start="2026-01-02", period_end="2027-12-31")) == (
            date(2026, 1, 2), date(2026, 7, 15))

    def test_the_floor_boundary_day_itself_serves(self):
        assert na.futures_eod_route(_q(asof=_CORN_FLOOR))[0] == "serve"
        assert na.futures_eod_route(_q(asof="2010-06-05"))[0] == "legacy"

    def test_a_supplied_but_unreadable_bound_declines_rather_than_collapsing_to_a_point(self):
        # absent and unparseable must stay apart: collapsing them would make a malformed period_start
        # look like an unwindowed latest read and quietly route a pre-coverage question to 'serve'.
        assert na.futures_eod_window(_q(agg="series", period_start="not-a-date")) is None
        assert na.futures_eod_route(_q(agg="series", period_start="not-a-date"))[0] == "uncovered"
        assert na.futures_eod_window(_q(agg="series", period_end="2020-13-45")) is None

    def test_a_bare_year_month_bound_is_widened_to_the_whole_month(self):
        assert na.futures_eod_window(_q(agg="series", period_start="2020-02", period_end="2020-02")) == (
            date(2020, 2, 1), date(2020, 2, 29))
        assert na.futures_eod_window(_q(agg="series", period_start="2019-12", period_end="2019-12")) == (
            date(2019, 12, 1), date(2019, 12, 31))


class TestCoverageDeclinesAreVerbatim:
    def test_the_provenance_sentence_is_the_ratified_one(self):
        assert na.futures_eod_legacy_provenance(_CORN_FLOOR) == (
            "from the roll-spliced continuous series; a per-contract curve does not exist before "
            "2010-06-06")

    def test_the_straddle_template_names_the_measured_floor_and_renders_fully(self):
        t = na.futures_eod_coverage_template("straddle", _CORN_FLOOR)
        assert "{floor}" not in t and t.count(_CORN_FLOOR) == 2

    def test_the_templates_are_register_clean_and_carry_no_internal_slugs(self):
        from leviathan.graphrag import register as rg
        for cls in na.FUTURES_EOD_COVERAGE_CLASSES:
            t = na.futures_eod_coverage_template(cls, _CORN_FLOOR)
            assert not rg.register_leaks(t), (cls, t)
            assert rg.count_valuation_words(t) == 0 and rg.count_flow_words(t) == 0
            assert "silver_" not in t and "leviathan_slug" not in t

    def test_the_note_and_the_preface_carry_the_same_verbatim_text(self):
        for cls in na.FUTURES_EOD_COVERAGE_CLASSES:
            body = na.futures_eod_coverage_template(cls, _CORN_FLOOR)
            assert body in na.futures_eod_coverage_note(cls, _CORN_FLOOR)
            assert body in na.futures_eod_coverage_preface(cls, _CORN_FLOOR)
        prov = na.futures_eod_legacy_provenance(_CORN_FLOOR)
        assert prov in na.futures_eod_coverage_note("legacy", _CORN_FLOOR)
        assert prov in na.futures_eod_coverage_preface("legacy", _CORN_FLOOR)

    def test_a_covered_route_says_nothing_at_all(self):
        assert na.futures_eod_coverage_note("serve", _CORN_FLOOR) == ""
        assert na.futures_eod_coverage_preface("serve", _CORN_FLOOR) == ""
        assert na.futures_eod_coverage_guard([]) is None


# -- the ADVERSARIAL rows: the guard on the real executor, not just the pure router -----------------
class _Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content):
        self.content = content


class _ToolThenText:
    """One tool_use turn, then plain text -- the minimum needed to drive answer_numbers' executor."""

    def __init__(self, tool_input: dict, text: str = "model text."):
        self._inp, self._text, self._n = tool_input, text, 0

    def create(self, **kw):
        self._n += 1
        if self._n == 1:
            return _Resp([_Blk(type="tool_use", id="t1", name="lookup_number", input=self._inp)])
        return _Resp([_Blk(type="text", text=self._text)])


class _FakeClient:
    def __init__(self, msgs):
        self.messages = msgs


def _drive(question: str, tool_input: dict, rows: list, asof: str = "2026-07-15"):
    """(result, sqls) -- sqls records EVERY compiled query, so a decline can be proven to have run none."""
    sqls: list[str] = []

    def qf(sql):
        sqls.append(sql)
        return [dict(r) for r in rows]

    out = na.answer_numbers(question, asof, client=_FakeClient(_ToolThenText(tool_input)), query_fn=qf)
    return out, sqls


class TestAdversarialCoverageDeclines:
    def test_a_curve_ask_for_an_uncovered_contract_declines_verbatim(self):
        # the adversarial row: a well-formed CURVE ask -- two named expiries, a real slug, a query_fn
        # standing ready with plausible rows -- for a venue whose canonical bytes never landed.
        out, sqls = _drive("what does the palm olein curve look like",
                           {"table": TABLE, "metric": "settle", "commodity": "palm_olein_dce",
                            "contract_month": "2026-09,2027-01", "agg": "latest"},
                           [{"value": 4200.0, "contract_month": "2026-09"}])
        call = out["calls"][0]
        assert call["status"] == "declined" and call["rows"] == []
        assert call["coverage_route"] == "uncovered"
        assert sqls == []                                        # nothing was ever queried
        body = na.FUTURES_EOD_COVERAGE_TEMPLATES["uncovered"]
        assert body in call["scope_note"]                        # the hybrid lane reads THIS
        assert body in out["answer"]                             # ...and the reader gets it verbatim
        assert out["futures_coverage_guard"] == "uncovered"

    def test_a_curve_ask_across_the_coverage_floor_declines_verbatim(self):
        out, sqls = _drive("corn curve from 2009 through 2012",
                           {"table": TABLE, "metric": "settle", "commodity": "corn_cbot",
                            "contract_month": "2010-12", "agg": "series",
                            "period_start": "2009-06-01", "period_end": "2012-06-01"},
                           [{"value": 400.0, "contract_month": "2010-12"}])
        call = out["calls"][0]
        assert (call["status"], call["coverage_route"], call["coverage_floor"]) == (
            "declined", "straddle", _CORN_FLOOR)
        assert call["rows"] == [] and sqls == []
        assert na.futures_eod_coverage_template("straddle", _CORN_FLOOR) in out["answer"]

    def test_a_named_expiry_before_the_floor_declines_rather_than_answering_with_another(self):
        # the sharpest adversarial case: a December-2005 ask that the table CANNOT answer, at an as-of
        # where the whole curve exists. Widening it to the nearest listed expiry would answer with a
        # number that is not that contract's -- the failure the delivery-month guard exists to prevent.
        out, sqls = _drive("what did the December 2005 corn contract settle at",
                           {"table": TABLE, "metric": "settle", "commodity": "corn_cbot",
                            "contract_month": "2005-12", "agg": "series",
                            "period_start": "2005-01-03", "period_end": "2005-12-30"},
                           [{"value": 200.0, "contract_month": "2005-12"}])
        call = out["calls"][0]
        assert call["coverage_route"] == "legacy"                # corn IS on the retiring continuous card
        assert call["query"]["table"] == "silver_futures_prices"
        assert "contract_month" not in call["query"]             # no expiry may ride a continuous level
        assert na.futures_eod_legacy_provenance(_CORN_FLOOR) in call["scope_note"]

    def test_a_pre_coverage_ask_serves_a_labelled_legacy_level(self):
        out, sqls = _drive("what was the corn price in May 2005",
                           {"table": TABLE, "metric": "settle", "commodity": "corn_cbot",
                            "agg": "series", "period_start": "2005-05-02", "period_end": "2005-05-31"},
                           [{"value": 213.5, "unit": "junk", "knowledge_date": "2005-05-31"}])
        call = out["calls"][0]
        assert call["coverage_route"] == "legacy"
        assert call["query"]["metric"] == "close" and call["query"]["agg"] == "latest"
        # the as-of is NARROWED to the era asked about -- strictly PIT-safe (it can only remove rows),
        # and the only lever available, because the continuous card is levels_only (no windowed read).
        assert call["query"]["asof"] == "2005-05-31"
        assert call["status"] == "ok" and call["rows"][0]["value"] == 213.5
        assert len(sqls) == 1 and "silver_futures_prices" in sqls[0] and TABLE not in sqls[0]
        assert out["futures_coverage_guard"] == "legacy"
        assert na.futures_eod_legacy_provenance(_CORN_FLOOR) in out["answer"]

    def test_a_covered_curve_read_is_served_and_carries_no_caveat(self):
        # the coherence half of the flip: FUTURES_DECLINE_TEMPLATES say the curve is "not in this
        # lookup" -- true of the continuous card, FALSE once this table answers the same ask. A served
        # curve under a verbatim denial that it exists would be the flip's own self-contradiction.
        out, sqls = _drive("show me the corn futures curve",
                           {"table": TABLE, "metric": "settle", "commodity": "corn_cbot",
                            "contract_month": "2026-12,2027-03", "agg": "series"},
                           [{"value": 431.0, "contract_month": "2026-12", "knowledge_date": "2026-07-14"},
                            {"value": 447.0, "contract_month": "2027-03", "knowledge_date": "2026-07-14"}])
        assert na.futures_scope("show me the corn futures curve") == "curve"   # the guard still detects
        assert out["calls"][0]["status"] == "ok" and len(out["calls"][0]["rows"]) == 2
        assert "coverage_route" not in out["calls"][0]
        assert "futures_decline_guard" not in out and "futures_coverage_guard" not in out
        assert out["answer"] == "model text."                    # byte-identical: no preface at all
        assert len(sqls) == 1 and TABLE in sqls[0]

    def test_the_continuous_card_caveat_still_fires_when_nothing_was_served(self):
        # the escape is NARROW: a coverage-declined EOD call has not served the curve, so the honest
        # continuous-card caveat still lands (both prefaces, in the numbers_only order).
        out, _ = _drive("show me the palm olein futures curve",
                        {"table": TABLE, "metric": "settle", "commodity": "palm_olein_dce",
                         "contract_month": "2026-09,2027-01", "agg": "latest"}, [])
        assert out["futures_coverage_guard"] == "uncovered"
        assert not na.futures_eod_served(out["calls"])


def test_the_coverage_verdict_rides_the_calls_into_the_hybrid_lane(monkeypatch):
    """#144, applied to coverage: run_hybrid consumes `calls` and throws the agent's prose away, so a
    decline that lived only in the agent's answer would vanish on exactly the lane where a reasoner is
    about to narrate the rows. The verdict is stamped ON the payload, so both lanes carry it."""
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    from leviathan.graphrag import orchestrator as orch
    declined = {"query": {"table": TABLE, "metric": "settle", "commodity": "corn_cbot"},
                "rows": [], "status": "declined", "coverage_route": "straddle",
                "coverage_floor": _CORN_FLOOR,
                "scope_note": na.futures_eod_coverage_note("straddle", _CORN_FLOOR)}
    assert na.futures_eod_coverage_guard([declined]) == ("straddle", _CORN_FLOOR)
    corn = cs.CausalContract(contract="corn", aliases=["corn"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+", mechanism="m")])
    graph = g.CausalGraph({"corn": corn}, silver=set())
    monkeypatch.setattr(orch.na, "answer_numbers",
                        lambda q, a, **kw: {"answer": "prose the hybrid path throws away",
                                            "calls": [dict(declined)],
                                            "futures_coverage_guard": "straddle"})
    out = orch.run_hybrid("what did the corn curve look like from 2009 through 2012", "2026-07-15",
                          graph=graph, call=lambda system, user, **kw: {"tldr": "t", "mechanism": "m",
                                                                       "sources": []},
                          retrieve=lambda q, contract, *, k, asof=None, near=None: [
                              {"date": "2012-07-20", "source": "GAIN", "source_key": "s3://x",
                               "text": "drought"}],
                          planner=None)
    assert out["trace"]["futures_coverage_guard"] == "straddle"
    assert na.futures_eod_coverage_template("straddle", _CORN_FLOOR) in out["answer"]
    assert out["number_calls"][0]["status"] == "declined" and out["number_calls"][0]["rows"] == []


# -- the three fold fixes of 2026-07-31 -------------------------------------------------------------
class TestHybridLaneDoesNotNeuterTheLegacyRewrite:
    """On a curve/named-phrased PRE-COVERAGE ask the coverage guard REWRITES the lookup to a continuous
    LEVEL -- whose table is silver_futures_prices, exactly what futures_hybrid_decline neuters. The two
    collided: the rewritten level was dropped, its status flipped to 'declined', and its scope_note (the
    coverage provenance sentence) was OVERWRITTEN with the SEAM-C template -- after which run_hybrid
    prepended "the figure below is from the roll-spliced continuous series" to an answer with no figure
    below it. The neuter's #144 intent survives: it exists so no BARE front-month level is minted for a
    curve ask, and a coverage-routed level is not bare -- it is labelled and provenance-carrying, which
    is the legacy route's whole point."""

    @staticmethod
    def _legacy_call() -> dict:
        return {"query": {"table": "silver_futures_prices", "metric": "close", "commodity": "corn_cbot",
                          "asof": "2005-05-31", "agg": "latest"},
                "rows": [{"value": 213.5, "unit": "US cents/bushel"}], "status": "ok",
                "scope_note": na.futures_eod_coverage_note("legacy", _CORN_FLOOR),
                "coverage_route": "legacy", "coverage_floor": _CORN_FLOOR}

    def test_a_coverage_routed_level_survives_the_curve_neuter(self):
        out, pref = na.futures_hybrid_decline("curve", [self._legacy_call()])
        assert out[0]["status"] == "ok" and out[0]["rows"], "the labelled legacy level was neutered"
        assert na.futures_eod_legacy_provenance(_CORN_FLOOR) in out[0]["scope_note"]
        assert pref                                           # the SEAM-C caveat still rides back

    def test_the_coverage_provenance_note_is_not_overwritten(self):
        out, _ = na.futures_hybrid_decline("named", [self._legacy_call()])
        assert na.FUTURES_DECLINE_TEMPLATES["named"] not in out[0]["scope_note"]
        assert out[0]["coverage_route"] == "legacy"           # and the verdict still rides for both lanes

    def test_a_BARE_front_month_level_is_still_neutered(self):
        # the #144 intent, unchanged: a continuous level with NO coverage stamp, minted for a curve ask,
        # is a different number wearing the ask's label and must not reach the reasoner's block.
        bare = {"query": {"table": "silver_futures_prices", "metric": "close", "commodity": "corn_cbot"},
                "rows": [{"value": 449.5}], "status": "ok"}
        out, pref = na.futures_hybrid_decline("curve", [bare])
        assert out[0]["status"] == "declined" and out[0]["rows"] == []
        assert out[0]["scope_note"] == na.FUTURES_DECLINE_TEMPLATES["curve"] and pref


class TestCoverageGuardReachesAnUnwindowedEraAsk:
    """The guard was driven by the WINDOW the model expressed, never by the era the question NAMED, so it
    did not reach an unwindowed pre-coverage ask: futures_eod_window collapses absent bounds to a POINT at
    the as-of, and with serving's as-of = today "what was corn trading at back in May 2005" emitted as
    {commodity, agg: latest} routed 'serve', compiled real SQL and returned TODAY's nearest-expiry settle
    carrying no coverage stamp and no preface. That is the failure _legacy_level_spec was written to
    prevent, reachable on the serve path where nothing equivalent existed."""

    def test_an_unwindowed_pre_coverage_ask_now_routes_legacy_at_the_asked_era(self):
        out, sqls = _drive("what was corn trading at back in May 2005",
                           {"table": TABLE, "metric": "settle", "commodity": "corn_cbot",
                            "agg": "latest"},
                           [{"value": 213.5, "unit": "US cents/bushel"}], asof="2026-07-15")
        call = out["calls"][0]
        assert call["coverage_route"] == "legacy"
        assert call["query"]["table"] == "silver_futures_prices"
        assert call["query"]["asof"] == "2005-05-31"          # the ERA asked about, not the harness as-of
        assert len(sqls) == 1 and TABLE not in sqls[0]
        assert na.futures_eod_legacy_provenance(_CORN_FLOOR) in out["answer"]

    def test_an_unwindowed_ask_naming_a_COVERED_era_is_untouched(self):
        out, sqls = _drive("where did corn settle in May 2026",
                           {"table": TABLE, "metric": "settle", "commodity": "corn_cbot",
                            "agg": "latest"},
                           [{"value": 431.0, "contract_month": "2026-07"}], asof="2026-07-15")
        assert "coverage_route" not in out["calls"][0]
        assert len(sqls) == 1 and TABLE in sqls[0]

    def test_an_ask_naming_NO_era_is_byte_identical(self):
        out, sqls = _drive("what is corn doing",
                           {"table": TABLE, "metric": "settle", "commodity": "corn_cbot",
                            "agg": "latest"},
                           [{"value": 431.0, "contract_month": "2026-07"}], asof="2026-07-15")
        assert "coverage_route" not in out["calls"][0] and TABLE in sqls[0]

    def test_an_EXPRESSED_window_still_wins_over_the_named_era(self):
        # the model's own bounds ARE the read that will run; the era narrowing must never override them.
        spec = Q.NumberQuery(table=TABLE, metric="settle", asof="2026-07-15", commodity="corn_cbot",
                             period_start="2020-01-01", period_end="2020-12-31")
        floor = FC.coverage_start_for("corn_cbot")
        assert na.futures_eod_read_window(spec, floor, (200505, 200505)) == na.futures_eod_window(spec)

    def test_an_uncovered_venue_named_pre_coverage_still_declines(self):
        # legacy is only available for the 12 slugs the continuous card serves; the rest DECLINE.
        out, sqls = _drive("what was palm olein trading at in May 2005",
                           {"table": TABLE, "metric": "settle", "commodity": "palm_olein_dce",
                            "agg": "latest"}, [{"value": 4200.0}], asof="2026-07-15")
        assert out["calls"][0]["coverage_route"] == "uncovered" and sqls == []


def test_the_seam_c_caveat_is_muted_when_it_would_offer_a_fallback_that_does_not_exist():
    """Every FUTURES_DECLINE_TEMPLATE ends by offering the continuous front-month level. On an UNCOVERED
    venue that offer is FALSE -- the retiring card serves 12 of 31 contracts -- so the reader was told a
    fallback is available that would raise if asked for, stacked immediately in front of a decline saying
    there is no record for that contract at all. The coverage template alone is the honest statement."""
    q = "what does the Euronext milling wheat futures curve look like"
    out, _ = _drive(q, {"table": TABLE, "metric": "settle", "commodity": "french_wheat_matif",
                        "contract_month": "2026-12,2027-03", "agg": "latest"}, [])
    assert na.futures_scope(q) == "curve"                     # the phrasing guard still detects the class
    assert out["futures_coverage_guard"] == "uncovered"
    assert "futures_decline_guard" not in out                 # MUTED: no fallback to advertise
    assert na.FUTURES_DECLINE_TEMPLATES["curve"] not in out["answer"]
    assert na.futures_eod_coverage_template("uncovered", None) in out["answer"]   # the honest half stays


def test_the_seam_c_mute_is_narrow():
    # corn IS on the continuous card, so an uncovered-route turn for it keeps the offer; and only the
    # 'uncovered' route mutes anything at all.
    calls = [{"query": {"table": TABLE, "metric": "settle", "commodity": "corn_cbot"},
              "rows": [], "status": "declined", "coverage_route": "uncovered"}]
    assert na.futures_eod_seam_c_muted(calls) is False
    calls[0]["query"]["commodity"] = "french_wheat_matif"
    assert na.futures_eod_seam_c_muted(calls) is True
    for route in ("legacy", "straddle", "serve"):
        calls[0]["coverage_route"] = route
        assert na.futures_eod_seam_c_muted(calls) is False
    assert na.futures_eod_seam_c_muted([]) is False


# -- the single-source map ------------------------------------------------------------------------
class TestContractMap:
    def test_covers_exactly_the_31_contract_slugs(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parents[2]
        slugs = {p.stem for p in (repo / "configs" / "commodities").glob("*.yaml")}
        assert set(FC.CONTRACT_MAP) == slugs
        assert len(FC.CONTRACT_MAP) == 31

    def test_vocabularies_are_clean(self):
        assert FC.lint_map() == []
        assert {r["settle_kind"] for r in FC.CONTRACT_MAP.values()} <= FC.SETTLE_KINDS
        assert {r["source"] for r in FC.CONTRACT_MAP.values()} <= FC.SOURCES

    def test_source_to_settle_kind_is_one_to_one(self):
        # the cross-tab the plan's post-ship verification asserts on real rows, enforced on the MAP so
        # a mislabeled row can never be authored: ICE is `close`, never `settlement`.
        by_source: dict[str, set] = {}
        for rec in FC.CONTRACT_MAP.values():
            by_source.setdefault(rec["source"], set()).add(rec["settle_kind"])
        assert all(len(v) == 1 for v in by_source.values()), by_source
        assert by_source["databento_glbx_mdp3"] == {"settlement"}
        assert by_source["databento_ifus_impact"] == {"close"}
        assert by_source["databento_ifeu_impact"] == {"close"}
        assert by_source["jse_safex"] == {"mark_to_market"}
        assert by_source["cepea"] == {"cash_index"}

    def test_cash_index_is_exactly_the_two_cepea_references(self):
        # only these rows may carry contract_month IS NULL (instrument_kind = cash_index).
        assert FC.CASH_INDEX_SLUGS == frozenset(
            {"brazilian_arabica_coffee", "campinas_corn_reference_bmf"})

    def test_contract_for_fails_closed_on_an_unmapped_slug(self):
        assert FC.contract_for("corn_cbot")["unit"] == "US cents/bushel"
        with pytest.raises(ValueError, match="missing from CONTRACT_MAP"):
            FC.contract_for("not_a_contract")


# -- the three-way unit bind ----------------------------------------------------------------------
def test_unit_map_three_way_equality():
    # single-source map projection == tracked lint constant == card unit_overrides. Three copies of
    # one fact, provably identical -- the FUTURES v1.5 lesson, at 31 slugs and ten currencies.
    assert FC.UNIT_MAP == cc._FUTURES_EOD_UNIT_OVERRIDES
    ov = cc._load("numbers/tables.yaml")["tables"][TABLE]["metrics"]["settle"]["unit_overrides"]
    assert ov == FC.UNIT_MAP


def test_check_futures_eod_green_on_the_live_config():
    assert cc.check_futures_eod() == []


def test_futures_eod_registered_in_main_lints():
    import inspect
    assert "check_futures_eod()" in inspect.getsource(cc.main)


class TestThreeWayDriftFails:
    """Each leg edited ALONE must fail the build. This is the whole point of the bind."""

    def test_card_only_drift_fails(self, monkeypatch):
        doc = cc._load("numbers/tables.yaml")
        doc["tables"][TABLE]["metrics"]["settle"]["unit_overrides"]["corn_cbot"] = "USD/bushel"
        monkeypatch.setattr(cc, "_load", lambda name: doc)
        assert any("unit_overrides" in e for e in cc.check_futures_eod())

    def test_map_only_drift_fails(self, monkeypatch):
        patched = dict(cc._FUTURES_EOD_UNIT_OVERRIDES)
        patched["rapeseed_oil_zce"] = "USD/metric ton"      # an FX conversion smuggled into the map
        monkeypatch.setattr(FC, "UNIT_MAP", patched)
        assert any("three-way drift" in e for e in cc.check_futures_eod())

    def test_lint_constant_only_drift_fails(self, monkeypatch):
        patched = dict(cc._FUTURES_EOD_UNIT_OVERRIDES)
        patched.pop("cocoa")
        monkeypatch.setattr(cc, "_FUTURES_EOD_UNIT_OVERRIDES", patched)
        errs = cc.check_futures_eod()
        assert any("unit_overrides" in e for e in errs) and any("three-way drift" in e for e in errs)

    def test_extra_served_metric_fails(self, monkeypatch):
        doc = cc._load("numbers/tables.yaml")
        doc["tables"][TABLE]["metrics"]["close"] = {"desc": "x"}
        monkeypatch.setattr(cc, "_load", lambda name: doc)
        assert any("settle-ONLY" in e for e in cc.check_futures_eod())

    def test_missing_card_fails(self, monkeypatch):
        monkeypatch.setattr(cc, "_load", lambda name: {"tables": {}})
        errs = cc.check_futures_eod()
        assert errs and "absent" in errs[0]

    def test_whitelist_regression_fails(self, monkeypatch):
        # INVERTED at the flip, same protective intent: re-adding the entry would force-drop a table
        # whose producers, gates and coverage guard are all live. That must fail the build loudly, not
        # quietly delete a served card from the tool enum on the next deploy.
        monkeypatch.setattr(R, "WHITELIST_ABSENT_DEFAULT", frozenset({TABLE}))
        assert any("WHITELIST_ABSENT_DEFAULT" in e for e in cc.check_futures_eod())

    def test_an_undeclared_contract_month_parameter_fails(self, monkeypatch):
        # the reachability trio, leg 1: serving the card while the tool schema omits the delivery
        # month is the SILENT failure the flip's atomicity exists to prevent -- so the lint refuses it.
        def _no_month(reg):
            sch = _real_schema(reg)
            sch["input_schema"]["properties"].pop("contract_month", None)
            return sch
        _real_schema = na.tool_schema
        monkeypatch.setattr(na, "tool_schema", _no_month)
        assert any("declares no `contract_month`" in e for e in cc.check_futures_eod())

    def test_a_contract_month_description_missing_the_curve_form_fails(self, monkeypatch):
        def _thin(reg):
            sch = _real_schema(reg)
            sch["input_schema"]["properties"]["contract_month"] = {"type": "string",
                                                                   "description": "delivery month"}
            return sch
        _real_schema = na.tool_schema
        monkeypatch.setattr(na, "tool_schema", _thin)
        errs = cc.check_futures_eod()
        assert any("comma-separated" in e for e in errs) and any("YYYY-MM" in e for e in errs)

    def test_a_router_purpose_that_never_names_the_curve_fails(self, monkeypatch):
        # leg 2: the dispatch purpose is the ONLY place the planner learns the capability exists.
        from leviathan.graphrag import dispatch as dp
        import dataclasses
        patched = tuple(dataclasses.replace(t, purpose="leakage-safe SQL over OBSERVED values.")
                        if t.name == "numbers" else t for t in dp.REGISTRY)
        monkeypatch.setattr(dp, "REGISTRY", patched)
        assert any("term structure" in e for e in cc.check_futures_eod())

    def test_REMOVING_the_numbers_toolspec_entirely_also_fails(self, monkeypatch):
        # leg 2 used to fail OPEN on REMOVAL and catch only REWORDING: `if _purpose and not (...)` reads
        # a missing ToolSpec as ''. Deleting it from dispatch.REGISTRY yielded ZERO errors while the
        # capability it asserts is reachable was as unreachable as under a reworded purpose. Empty is an
        # ERROR (the (b3) reasoning, applied here).
        from leviathan.graphrag import dispatch as dp
        monkeypatch.setattr(dp, "REGISTRY", tuple(t for t in dp.REGISTRY if t.name != "numbers"))
        assert any("no ToolSpec('numbers')" in e for e in cc.check_futures_eod())

    def test_an_EMPTY_family_enum_also_fails(self, monkeypatch):
        # the same fail-open on the other half: family_names() returning () yielded ZERO errors.
        from leviathan.graphrag import dispatch as dp
        monkeypatch.setattr(dp, "family_names", lambda: ())
        assert any("family_names() is EMPTY" in e for e in cc.check_futures_eod())

    def test_dropping_a_served_dimension_or_the_partition_layout_fails(self, monkeypatch):
        # check_futures_eod is the ONLY lint that reads the RAW card while the table is registry-fenced
        # (check_numbers_schema_pins iterates load_registry(), which DROPS a whitelist-absent table), so
        # these five keys can only be pinned here pre-flip. Dropping settle_kind_col would otherwise
        # leave every lint green while an ICE session CLOSE started being cited as a settlement.
        for key in ("contract_month_col", "settle_kind_col", "currency_col", "partition_cols",
                    "year_col"):
            doc = cc._load("numbers/tables.yaml")
            doc["tables"][TABLE].pop(key)
            monkeypatch.setattr(cc, "_load", lambda name, _d=doc: _d)
            assert any(key in e for e in cc.check_futures_eod()), key
            monkeypatch.undo()

    def test_settle_kind_vocabulary_drift_fails(self, monkeypatch):
        bad = copy.deepcopy(FC.CONTRACT_MAP)
        bad["corn_cbot"]["settle_kind"] = "official"
        monkeypatch.setattr(FC, "CONTRACT_MAP", bad)
        assert any("settle_kind" in e for e in cc.check_futures_eod())

    def test_source_settle_kind_crosstab_drift_fails(self, monkeypatch):
        # an ICE row relabeled as a settlement -- the exact dishonesty settle_kind exists to prevent.
        bad = copy.deepcopy(FC.CONTRACT_MAP)
        bad["cocoa"]["settle_kind"] = "settlement"
        monkeypatch.setattr(FC, "CONTRACT_MAP", bad)
        assert any("1:1" in e for e in cc.check_futures_eod())


# -- the DAG catalog (D2) -------------------------------------------------------------------------
class TestDagCatalog:
    def test_build_catalog_maps_the_table_without_raising(self):
        from leviathan.silver.dag_catalog import FAMILY_LABELS, build_catalog, family_of
        assert family_of(TABLE) == "futures_eod"
        catalog = build_catalog()
        assert catalog["futures_eod"].tables == (TABLE,)
        assert FAMILY_LABELS["futures_eod"]                     # a runbook-facing label exists
        assert catalog["futures_eod"].backfillable is True

    def test_the_new_rule_does_not_swallow_the_live_yfinance_table(self):
        # the ordering hazard: a ("silver_futures", ...) prefix would re-home silver_futures_prices.
        from leviathan.silver.dag_catalog import family_of
        assert family_of("silver_futures_prices") == "futures"

    def test_family_ceiling_folds_the_publication_lag_grace(self):
        from leviathan.silver.dag_catalog import build_catalog, effective_sla_lag_days
        from leviathan.silver.registry import load_registry
        c = load_registry().table(TABLE)
        assert c["freshness_sla"] == {"cadence": "daily", "max_lag_days": 5}
        lag, basis = effective_sla_lag_days(c)
        assert (lag, basis) == (6, "registry.max_lag_days")     # 5 explicit + 1 publication lag
        assert build_catalog()["futures_eod"].max_sla_lag_days == 6


# -- the F010 contract shape ----------------------------------------------------------------------
class TestRegistryContract:
    @pytest.fixture(scope="class")
    def contract(self):
        from leviathan.silver.registry import load_registry
        return load_registry().table(TABLE)

    def test_identity_and_storm_safe_layout(self, contract):
        assert contract["layer"] == "silver" and contract["lifecycle_class"] == "source"
        assert contract["s3_root"] == "s3://leviathan-dev-shahem-001/silver/futures_eod"
        assert contract["layout"] == "partitioned"
        assert contract["partition_mode"] == "registered"
        assert contract["projection"] == "forbidden"           # NEVER the LIST-storm grid
        assert contract["write_mode"] == "registered-partition"
        assert [pk["name"] for pk in contract["partition_keys"]] == ["leviathan_slug", "trade_year"]
        assert not any(pk["projected"] for pk in contract["partition_keys"])
        assert contract["vintage_retention"] == "latest-only"  # prices do not revise

    def test_natural_key_and_value_columns(self, contract):
        assert contract["natural_key"] == ["leviathan_slug", "contract_month", "trade_date"]
        assert contract["value_columns"] == ["settle"]
        assert contract["min_nonnull_frac"] == 0.5
        # required_nonnull is deliberately NOT the natural key: contract_month is a KEY member that is
        # legitimately NULL on the CEPEA cash rows (the WASDE 7-of-9 precedent).
        assert "contract_month" not in contract["required_nonnull"]
        assert set(contract["required_nonnull"]) == {
            "leviathan_slug", "trade_date", "instrument_kind", "settle_kind", "unit", "source"}

    def test_inv2_column_order_is_the_ratified_writer_order(self, contract):
        assert [c["name"] for c in contract["physical_columns"]] == [
            "trade_date", "contract_month", "instrument_kind", "raw_symbol", "settle", "settle_kind",
            "open", "high", "low", "close", "volume", "open_interest", "unit", "currency",
            "expiry_date", "source", "dataset"]
        # partition keys live ONLY in partition_keys -- declaring them physically too is the
        # silver_esr_compact clash that forced load_pg_numbers to grow a per-load footer probe.
        assert "leviathan_slug" not in [c["name"] for c in contract["physical_columns"]]
        assert "trade_year" not in [c["name"] for c in contract["physical_columns"]]

    def test_nullability_pins_the_two_facts_the_key_cannot_express(self, contract):
        by = {c["name"]: c for c in contract["physical_columns"]}
        # a NULL delivery month is LEGAL (the CEPEA cash refs) despite contract_month being in the key
        assert by["contract_month"]["nullable"] is True
        # ...while four non-key label columns are non-null by contract
        for cn in ("instrument_kind", "settle_kind", "unit", "source"):
            assert by[cn]["nullable"] is False, cn
        assert by["trade_date"]["nullable"] is False
        assert by["settle"]["nullable"] is True

    def test_no_roll_or_continuous_column_ever(self, contract):
        import re
        names = [c["name"] for c in contract["physical_columns"]]
        assert not [n for n in names
                    if re.search(r"(?i)front_month|roll|log_return|adjusted|continuous", n)]

    def test_pit_fields_match_the_card(self, contract):
        card = cc._load("numbers/tables.yaml")["tables"][TABLE]
        assert contract["knowledge_date_col"] == card["knowledge_date_col"] == "trade_date"
        assert contract["knowledge_semantics"] == card["knowledge_semantics"] == "data_date"
        assert contract["publication_lag_days"] == card["publication_lag_days"] == 1
        assert card["date_col_type"] == "timestamp"            # DP-5, the pg-parity requirement
        assert contract["consumers"] == "both"
        assert contract["numbers_ref"].endswith(f"#{TABLE}")

    def test_arrow_writer_schema_round_trips_from_the_contract(self, contract):
        import pyarrow as pa
        from leviathan.silver.flat_producer import pa_schema_from_contract
        sch = pa_schema_from_contract(contract)
        assert sch.names[0] == "trade_date" and sch.names[-1] == "dataset"
        assert sch.field("trade_date").type == pa.timestamp("us")
        assert sch.field("settle").type == pa.float64()
        assert sch.field("volume").type == pa.int64()
        assert sch.field("contract_month").nullable is True
        assert sch.field("unit").nullable is False


# -- D7 / D8 wiring -------------------------------------------------------------------------------
def test_pg_mirror_deferral_is_recorded_not_implied():
    # D7 / probe P8: absence from P1_TABLES IS the exclusion mechanism (there is no named exclusion
    # set), so the deferral has to be WRITTEN DOWN or it reads as an oversight. Load the module by
    # path (jobs/ is not an importable package) and assert both halves.
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "jobs" / "utils" / "load_pg_numbers.py"
    spec = importlib.util.spec_from_file_location("load_pg_numbers_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert TABLE not in mod.P1_TABLES                       # DEFERRED until the W2 size check
    assert TABLE in path.read_text(encoding="utf-8")        # ...and the reason is recorded there


def test_parity_sample_entry_present_and_fence_guarded():
    # D8: the entry lands with the schema so the panel is never vacuous at the flip, and the loop
    # must SKIP (not crash on) a table that is registered-but-fenced.
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "jobs" / "utils" / "numbers_parity.py"
    src = p.read_text(encoding="utf-8")
    assert '"silver_futures_eod": "corn_cbot"' in src
    assert "SKIP-FENCED" in src
    assert "if tid not in reg.tables:" in src


def test_parity_skips_a_sampled_table_that_has_no_pg_mirror():
    # The D7/D8 SEQUENCING guard: the W3 whitelist flip is a one-line registry edit, while the
    # P1_TABLES addition is a separate decision gated on a measured size check. Without this branch
    # the flip alone would point every leg at a pg relation that was never created -- _cmp books each
    # as a PG-ERR MISMATCH and main() returns 1, i.e. one deferred table reddens the WHOLE gate.
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "jobs" / "utils" / "numbers_parity.py"
    src = p.read_text(encoding="utf-8")
    assert "SKIP-UNMIRRORED" in src
    assert "if tid not in PG_MIRROR_TABLES:" in src
    spec = importlib.util.spec_from_file_location("numbers_parity_probe", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # imported from load_pg_numbers, so the allowlist and the guard can never drift...
    assert TABLE in mod.SAMPLE_COMMODITY and TABLE not in mod.PG_MIRROR_TABLES
    # ...and every OTHER sampled table IS mirrored, so the guard changes nothing else today.
    assert set(mod.SAMPLE_COMMODITY) - mod.PG_MIRROR_TABLES == {TABLE}


def test_gate_baseline_seed_d6_is_deferred_in_writing():
    # D6 is the one W1.0 deliverable NOT shipped: a rolling gate baseline is a census of legs that
    # exist, and this table has zero objects, zero registered partitions and cascade_ref: null. The
    # deferral is RECORDED at the site the plan names (the D7 discipline), never implied by silence.
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "jobs" / "audit" / "advance_rolling_census.py"
    src = p.read_text(encoding="utf-8")
    assert "W1.0 / D6" in src and "deferred to W1a" in src
    assert "cascade_census/rolling/futures_eod/census.json" in src


# -- the conditional invariant the schema cannot express ------------------------------------------
class TestLintFrame:
    """contract_month IS NULL if and ONLY if instrument_kind == 'cash_index'.

    ``required_nonnull`` is unconditional, so the contract can only say ``nullable: true`` -- which
    makes a dropped delivery month LEGAL. It is not: contract_month is part of the natural key
    [leviathan_slug, contract_month, trade_date], so N futures rows with a NULL month collapse to ONE
    key, and source_contracts ``duplicate_check: full`` cannot flag it (SQL treats each NULL as
    distinct). lint_frame is the enforcement, wired in as build_partitioned_publish(row_validator=)."""

    @staticmethod
    def _frame(**over):
        import pandas as pd
        base = {"leviathan_slug": ["corn_cbot", "brazilian_arabica_coffee"],
                "instrument_kind": ["futures", "cash_index"],
                "contract_month": ["2026-12", None],
                "unit": ["US cents/bushel", "BRL/60-kg bag"],
                "currency": ["USD", "BRL"],
                "settle_kind": ["settlement", "cash_index"],
                "source": ["databento_glbx_mdp3", "cepea"]}
        base.update(over)
        return pd.DataFrame(base)

    def test_a_mixed_futures_plus_cash_frame_is_clean(self):
        assert FC.lint_frame(self._frame()) == []

    def test_a_futures_row_with_a_null_contract_month_is_rejected(self):
        errs = FC.lint_frame(self._frame(contract_month=[None, None]))
        assert any("NULL contract_month" in e for e in errs)

    def test_a_cash_index_row_with_a_contract_month_is_rejected(self):
        errs = FC.lint_frame(self._frame(contract_month=["2026-12", "2026-12"]))
        assert any("NON-NULL contract_month" in e for e in errs)

    def test_a_blank_string_counts_as_null(self):
        # '' / '   ' are how a CSV-ish producer expresses "no month"; they must not sneak past.
        errs = FC.lint_frame(self._frame(contract_month=["   ", None]))
        assert any("NULL contract_month" in e for e in errs)

    def test_instrument_kind_must_match_the_maps_cash_index_slugs(self):
        errs = FC.lint_frame(self._frame(instrument_kind=["cash_index", "cash_index"],
                                         contract_month=[None, None]))
        assert any("corn_cbot: instrument_kind" in e for e in errs)

    def test_instrument_kind_vocabulary_is_closed(self):
        errs = FC.lint_frame(self._frame(instrument_kind=["future", "cash_index"]))
        assert any("vocabulary drift" in e for e in errs)

    def test_an_unmapped_slug_is_rejected(self):
        errs = FC.lint_frame(self._frame(leviathan_slug=["not_a_slug", "brazilian_arabica_coffee"]))
        assert any("unmapped leviathan_slug" in e for e in errs)

    def test_a_row_unit_that_disagrees_with_the_map_is_rejected(self):
        # the ROW-level end of the three-way unit bind: a producer cannot write a guessed unit.
        errs = FC.lint_frame(self._frame(unit=["USD/bushel", "BRL/60-kg bag"]))
        assert any("do not match" in e for e in errs)

    def test_missing_columns_and_empty_frames_are_handled(self):
        import pandas as pd
        assert FC.lint_frame(self._frame().iloc[0:0]) == []
        errs = FC.lint_frame(pd.DataFrame({"leviathan_slug": ["corn_cbot"]}))
        assert len(errs) == 1 and "missing required column" in errs[0]
