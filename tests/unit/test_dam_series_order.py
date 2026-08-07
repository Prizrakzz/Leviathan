"""D-AM-18 -- newest-first ordering for EVERY series read, behind GRAPHRAG_SERIES_NEWEST_FIRST.

THE DEFECT THIS FILE MEASURES. D-FR-2 ratified the newest-first flip FUTURES-SCOPED: `_newest_first_applies`
keys on `ts.contract_month_col`, so silver_futures_eod moved and nothing else did. Every other series read --
PSD, CEPEA/pink_sheet, COT, NASA POWER, the two ONI/IOD cards -- still compiles its ORDER BY ascending, and
`LIMIT 5000` therefore keeps the OLDEST rows. A "long history" z-score or percentile then windows against
rows that stop years before the as-of, and the truncation sentinel (agent._exec's `truncated` stamp,
agent.series_truncated) only ANNOTATES that read -- it never re-aims it.

WHAT IS PINNED, AND IN WHICH DIRECTION
  * OFF is BYTE-IDENTITY, not "roughly the same": with the token absent (or False) every card compiles the
    exact string it compiled before this wave, so the env var is the rollback rather than a redeploy.
  * ON is measured on the CARDS THAT MOVE, with an anti-vacuity twin each time -- an assertion that only
    said "the SQL changed" would pass for a flip that reversed the wrong branch.
  * THE FUTURES SCOPE IS PINNED AS UNMOVED, both ways. D-FR-2's flag keeps its exact meaning, and a futures
    card under the estate-wide token takes the SAME single flip (there is no double-apply to find, and this
    file is where that stays true).
  * THE RE-SORT. The flip changes WHICH rows survive the cap; `resort_rows_chronological` restores the
    ascending presentation every consumer indexes into. Under the widened scope that key finally meets a
    NUMERIC alias (`month` on the three year_month cards with no date axis), which the futures scope could
    never reach -- D-FR-2's docstring parked it as "LIVE the instant the estate-wide alternative is taken".
    It is taken here, so the divergence is pinned here.

D-PQ FIX-1 ADDED SECTION 8, AND CHANGED THE POLARITY OF THE SEAM (section 6). Sections 1-5 are about the
COMPILER GIVEN A TOKEN and are untouched -- `build_sql`'s kwarg still defaults False and "off is
byte-identity" still means exactly what it meant. What moved is which token a SERVING LANE RESOLVES with
no env set: D-AM-18 shipped this opt-in, and the D-CW-4 wired probe then measured the cost of opt-in on a
lane nobody had set the env on (a Nov-2019 MPOB print served as "the same month"; the 5000-cap oldest-kept
read re-measured UNCHANGED) while the model-facing `limit` schema already promised the newest end. The
default is now ON and the flag is the ROLLBACK. Section 8 pins that at the seam resolution; section 6 pins
the inverted fail-closed direction (only a recognised DISABLE disables).

The file is hermetic: no AWS, no LLM, no pg. `tests/unit/test_futures_readpath_pins.py` stays the acceptance
surface for the FUTURES scope; this file must never restate its pins, only the estate-wide ones and the
futures NON-movement that bounds them.
"""
from __future__ import annotations

import inspect

import pytest
from leviathan.graphrag import answer as AN
from leviathan.graphrag import config_check as CC
from leviathan.graphrag.numbers import agent as NA
from leviathan.graphrag.numbers import cascade as CQ
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R

ALL = Q.NEWEST_FIRST_ALL
EOD = "silver_futures_eod"
FLAG = "GRAPHRAG_SERIES_NEWEST_FIRST"


def _ts(table: str) -> R.TableSpec:
    """The LIVE card out of the raw tables.yaml, read the way test_futures_readpath_pins reads it -- never a
    hand-built TableSpec, which would let a card edit ship past every assertion below."""
    return R.TableSpec(id=table, **dict(CC._load("numbers/tables.yaml")["tables"][table]))


def _spec(table: str, metric: str, **kw) -> Q.NumberQuery:
    base = dict(table=table, metric=metric, asof="2026-06-08", agg="series")
    base.update(kw)
    return Q.NumberQuery(**base)


# One series spec per NON-FUTURES shape the defect names. The partition-required cards carry their static
# equalities (nasa_power raises without commodity/country/region -- that guard is not what is under test).
NON_FUTURES = {
    "psd_vintage": _spec("silver_psd", "ending_stocks_mt", commodity="corn"),
    "pink_sheet_cash": _spec("silver_pink_sheet", "palm_oil_cpo_usd_t"),
    "cot_weekly": _spec("silver_cot", "mm_net", commodity="corn"),
    "nasa_power_daily": _spec("silver_nasa_power", "precipitation_mm", commodity="corn",
                              country="united_states", region="us_corn_belt"),
    "noaa_oni_yearmonth": _spec("silver_noaa_oni", "oni_anom"),
}


def _order_by(sql: str) -> str:
    return sql.split("ORDER BY")[-1].split("LIMIT")[0].strip()


def _terms(sql: str) -> list[str]:
    return [t.strip() for t in _order_by(sql).split(",")]


# ==================================================================================================
# 1. FLAG OFF -- byte-identical SQL on every non-futures card
# ==================================================================================================
class TestFlagOffIsByteIdentical:
    @pytest.mark.parametrize("name", sorted(NON_FUTURES))
    def test_omitted_kwarg_and_explicit_False_compile_the_same_string(self, name):
        """The rollback comes from the idiom: an absent token and an explicit False are the same compile,
        and both are the pre-wave string (section 3 proves the string itself did not move by pinning that
        the FUTURES token -- which existed before this wave -- leaves these cards alone too)."""
        spec = NON_FUTURES[name]
        ts = _ts(spec.table)
        assert Q.build_sql(spec, ts) == Q.build_sql(spec, ts, futures_newest_first=False)
        assert Q._newest_first_applies(spec, ts, False) is False

    @pytest.mark.parametrize("name", sorted(NON_FUTURES))
    def test_the_off_order_is_ASCENDING_with_no_null_placement(self, name):
        """ANTI-VACUITY for the row above. If the off compile had already carried DESC/NULLS LAST, "off ==
        off" would be true and would pin nothing. Today's order is bare ASC on every term -- which agrees
        across Presto and Postgres by accident, and is exactly why the flipped form has to state NULLS
        LAST explicitly."""
        spec = NON_FUTURES[name]
        off = Q.build_sql(spec, _ts(spec.table))
        assert "DESC" not in _order_by(off) and "NULLS" not in _order_by(off)

    def test_no_module_below_the_seam_names_the_new_env_var(self):
        """The flag grammar, as a census rather than a docstring: the env is read at ONE seam and threaded
        as an argument, so no engine may name it. Mirrors the identical pin the futures flag carries in
        test_futures_readpath_pins section 7.3."""
        import importlib
        for mod in ("leviathan.graphrag.numbers.query", "leviathan.graphrag.numbers.cascade",
                    "leviathan.graphrag.numbers.agent", "leviathan.graphrag.orchestrator",
                    "leviathan.graphrag.server"):
            assert FLAG not in inspect.getsource(importlib.import_module(mod)), \
                f"{mod} names the flag itself -- the seam is no longer the ONE env read"


# ==================================================================================================
# 2. FLAG ON -- newest-first on every series read, PSD-shaped card first
# ==================================================================================================
class TestEstateWideTokenFlipsTheSeriesBranch:
    def test_the_psd_card_flips_to_the_exact_reverse_of_its_total_order(self):
        """The PSD-shaped card is the flagship of the defect: a vintage table with NO date axis, whose
        series branch is `ORDER BY period, knowledge_date, value LIMIT 5000` -- oldest marketing years
        first, newest dropped at the cap. The flipped form must be that order REVERSED TERM FOR TERM (not
        merely "some DESC"), because "keep the newest N" is only exactly true of the exact reverse."""
        spec = NON_FUTURES["psd_vintage"]
        ts = _ts(spec.table)
        off, on = Q.build_sql(spec, ts), Q.build_sql(spec, ts, futures_newest_first=ALL)
        assert off != on, "the estate-wide token is a no-op on the PSD series branch -- D-AM-18 did not land"
        assert _terms(on) == [f"{t} DESC NULLS LAST" for t in _terms(off)]
        assert Q._newest_first_applies(spec, ts, ALL) is True

    @pytest.mark.parametrize("name", sorted(NON_FUTURES))
    def test_every_non_futures_series_card_moves_and_carries_NULLS_LAST_on_every_term(self, name):
        """Presto defaults NULLS LAST regardless of direction; Postgres defaults NULLS LAST on ASC and
        NULLS FIRST on DESC. A bare DESC would place NULLs differently on the two backends for the same
        SQL -- the pg-parity divergence class -- so every term states its placement."""
        spec = NON_FUTURES[name]
        ts = _ts(spec.table)
        on = Q.build_sql(spec, ts, futures_newest_first=ALL)
        assert on != Q.build_sql(spec, ts)
        assert _terms(on) and all(t.endswith("DESC NULLS LAST") for t in _terms(on))
        assert on.rstrip().endswith(f"LIMIT {spec.limit}"), "the cap moved -- only its DIRECTION may change"

    @pytest.mark.parametrize("name", sorted(NON_FUTURES))
    def test_only_the_ORDER_BY_moves_under_the_token(self, name):
        """The scope guard must not reach the SELECT list, the WHERE, the PIT guard or the vintage dedup.
        Everything up to the final ORDER BY is compared byte for byte."""
        spec = NON_FUTURES[name]
        ts = _ts(spec.table)
        off, on = Q.build_sql(spec, ts), Q.build_sql(spec, ts, futures_newest_first=ALL)
        assert off.rsplit("ORDER BY", 1)[0] == on.rsplit("ORDER BY", 1)[0]

    def test_the_scalar_aggs_and_the_latest_with_a_date_axis_never_move(self):
        """`_is_series_branch` is the whole scope beyond the flag: the four scalar aggs collapse to one row
        and `agg='latest'` on a card WITH a chronological axis compiles `... DESC LIMIT 1`. Neither is a
        series and neither can truncate, so neither may compile one byte differently."""
        psd, ts = NON_FUTURES["psd_vintage"], _ts("silver_psd")
        agg = psd.model_copy(update={"agg": "sum"})
        assert Q.build_sql(agg, ts) == Q.build_sql(agg, ts, futures_newest_first=ALL)
        assert Q._newest_first_applies(agg, ts, ALL) is False
        eod_ts = _ts(EOD)
        latest = Q.NumberQuery(table=EOD, metric="settle", asof="2026-06-08", commodity="corn_cbot",
                               agg="latest")
        assert Q.build_sql(latest, eod_ts) == Q.build_sql(latest, eod_ts, futures_newest_first=ALL)
        assert Q._newest_first_applies(latest, eod_ts, ALL) is False

    def test_a_card_with_no_chronological_axis_at_agg_latest_DOES_move(self):
        """ANTI-VACUITY for the row above, and the sharp edge of `_is_series_branch`: a table with no order
        column (PSD/WASDE: no date_col) falls through to the SERIES arm even at `agg='latest'`, so it is a
        capped read and the token must reach it. Scoping on `agg` alone would have missed exactly this."""
        spec = NON_FUTURES["psd_vintage"].model_copy(update={"agg": "latest"})
        ts = _ts("silver_psd")
        assert Q._order_col(ts) is None
        assert Q._newest_first_applies(spec, ts, ALL) is True
        assert Q.build_sql(spec, ts) != Q.build_sql(spec, ts, futures_newest_first=ALL)


# ==================================================================================================
# 3. THE FUTURES SCOPE -- unmoved in both directions
# ==================================================================================================
class TestFuturesScopeUnchanged:
    """D-FR-2's flag keeps its exact meaning; D-AM-18 is a SECOND flag, not a widening of the first."""

    def test_the_futures_token_still_moves_the_futures_series_branch_only(self):
        eod, ts = _spec(EOD, "settle", commodity="corn_cbot"), _ts(EOD)
        assert Q.build_sql(eod, ts) != Q.build_sql(eod, ts, futures_newest_first=True)
        assert Q._newest_first_applies(eod, ts, True) is True

    @pytest.mark.parametrize("name", sorted(NON_FUTURES))
    def test_the_futures_token_still_leaves_every_non_futures_card_byte_identical(self, name):
        """The regression that would matter most: D-AM-18 must not turn GRAPHRAG_FUTURES_NEWEST_FIRST=on
        (LIVE in serving) into an estate-wide flip by accident. Same assertion the futures pins file makes
        on WASDE, extended to the five shapes this wave is about."""
        spec = NON_FUTURES[name]
        ts = _ts(spec.table)
        assert ts.contract_month_col is None
        assert Q.build_sql(spec, ts) == Q.build_sql(spec, ts, futures_newest_first=True)
        assert Q._newest_first_applies(spec, ts, True) is False

    def test_both_tokens_on_is_the_SAME_single_flip_on_a_futures_card(self):
        """The scopes are nested, not parallel -- everything the futures scope moves the estate-wide scope
        moves too. So a futures card under the estate-wide token compiles the string the futures token
        already compiles: one flip, never a double-apply back to ascending."""
        eod, ts = _spec(EOD, "settle", commodity="corn_cbot"), _ts(EOD)
        assert Q.build_sql(eod, ts, futures_newest_first=True) == \
            Q.build_sql(eod, ts, futures_newest_first=ALL)

    def test_the_named_expiry_and_curve_branches_stay_byte_identical_under_the_token(self):
        ts = _ts(EOD)
        curve = Q.NumberQuery(table=EOD, metric="settle", asof="2026-06-08", commodity="corn_cbot",
                              agg="latest", contract_month="2026-12,2027-03")
        assert Q.build_sql(curve, ts) == Q.build_sql(curve, ts, futures_newest_first=ALL)


# ==================================================================================================
# 4. THE RE-SORT -- the half a compiled flip is worthless without
# ==================================================================================================
class TestResortUnderTheWidenedScope:
    """`run()` re-sorts the DESC fetch back to ascending before any consumer sees a row, so
    `_series_from_rows`, `stats.streak`/`window_change`/`yoy_delta`, `_val()`'s `series[-1]` and
    `_pace_synth`'s `rows[-1]` keep meaning the last term of the ASCENDING order."""

    ONI = _spec("silver_noaa_oni", "oni_anom")
    # A DESC fetch off a year_month card, as the flipped SQL returns it: 2026-01 first, then 2025-12..09.
    DESC_ROWS = ([{"value": "1", "year": "2026", "month": "1"}] +
                 [{"value": "1", "year": "2025", "month": m} for m in ("12", "11", "10", "9")])

    def test_the_month_alias_is_restored_NUMERICALLY_not_lexically(self):
        """THE DIVERGENCE D-FR-2 PARKED, now live. `month` is 1..12 unpadded: '10' < '9' as text but
        9 < 10 as SQL, and on this card it LEADS the order (no date axis at all). A text re-sort would end
        the series at September and every `series[-1]` consumer would read September as the latest."""
        got = Q.resort_rows_chronological(self.DESC_ROWS, self.ONI, _ts("silver_noaa_oni"))
        assert [(r["year"], r["month"]) for r in got] == [
            ("2025", "9"), ("2025", "10"), ("2025", "11"), ("2025", "12"), ("2026", "1")]

    def test_ANTI_VACUITY_a_plain_text_key_really_would_get_it_wrong(self):
        """If `month` happened to sort the same way under both keys, the row above would pass for the
        wrong reason. It does not: the naive text key puts October before September."""
        naive = sorted(self.DESC_ROWS, key=lambda r: (r["year"], r["month"]))
        assert [r["month"] for r in naive] == ["10", "11", "12", "9", "1"]

    def test_the_numeric_cell_keeps_absence_LAST_and_junk_comparable(self):
        """NULL/"" is absence on both backends and must stay LAST in the ASC restoration (never first,
        where a naive text compare puts it). A junk cell in a numeric column is a data defect, and it must
        not raise mid-answer."""
        assert Q._sort_cell(None, numeric=True) == (1, "")
        assert Q._sort_cell("", numeric=True) == (1, "")
        assert Q._sort_cell("n/a", numeric=True) == (0, "n/a")
        assert Q._sort_cell("9", numeric=True) < Q._sort_cell("10", numeric=True)
        assert Q._sort_cell("9") > Q._sort_cell("10")            # the text relation it replaces

    def test_the_futures_resort_is_byte_identical_to_before_this_wave(self):
        """silver_futures_eod surfaces no numeric alias, so `_NUMERIC_ALIASES` cannot touch the one scope
        that is already LIVE in serving. Same fixture shape as the futures pins file's re-sort test."""
        assert not (set(Q._order_aliases(Q._extras(_ts(EOD)), False)) & set(Q._NUMERIC_ALIASES))
        eod, ts = _spec(EOD, "settle", commodity="corn_cbot"), _ts(EOD)
        desc = [{"leviathan_slug": "corn_cbot", "contract_month": m, "data_date": d, "value": "1"}
                for m, d in (("2027-03", "2026-06-05"), ("2026-12", "2026-06-04"),
                             ("2026-07", "2026-06-03"))]
        got = Q.resort_rows_chronological(desc, eod, ts)
        assert [r["data_date"] for r in got] == ["2026-06-03", "2026-06-04", "2026-06-05"]

    def test_run_flips_the_fetch_and_restores_the_order_in_one_gate(self):
        """SQL and rows are gated by the SAME predicate, so a flipped compile whose rows were never
        re-sorted is unreachable -- that partial failure leaves every consumer looking right while the cap
        keeps the wrong end."""
        seen: list = []

        def _qfn(sql):
            seen.append(sql)
            return [dict(r) for r in self.DESC_ROWS]

        got = Q.run(self.ONI, query_fn=_qfn, futures_newest_first=ALL)
        assert all(t.endswith("DESC NULLS LAST") for t in _terms(seen[0]))
        assert [r["month"] for r in got] == ["9", "10", "11", "12", "1"]

    def test_run_with_the_token_off_touches_neither_the_sql_nor_the_row_order(self):
        seen: list = []

        def _qfn(sql):
            seen.append(sql)
            return [dict(r) for r in self.DESC_ROWS]

        got = Q.run(self.ONI, query_fn=_qfn)
        assert "DESC" not in _order_by(seen[0])
        assert [r["month"] for r in got] == ["1", "12", "11", "10", "9"]   # executor order, untouched


# ==================================================================================================
# 5. THE TRUNCATION SENTINEL -- still reachable, and now pointed at the newest end
# ==================================================================================================
class TestSentinelStillReachable:
    """The sentinel ANNOTATES a capped read; D-AM-18 changes WHICH end the cap keeps. Both must hold at
    once -- a re-sort that dropped or duplicated a row would silently change the count the stamp reads."""

    def test_a_read_at_the_cap_still_counts_as_truncated_after_the_flip(self):
        spec = NON_FUTURES["psd_vintage"].model_copy(update={"limit": 3})
        rows = [{"value": str(i), "period": f"202{i}/2{i + 1}", "knowledge_date": "2026-05-12"}
                for i in range(3)]
        got = Q.run(spec, query_fn=lambda _sql: [dict(r) for r in rows], futures_newest_first=ALL)
        assert len(got) == len(rows) == spec.limit
        assert NA.series_truncated({"query": spec.model_dump(exclude_none=True), "rows": got}) is True

    def test_the_engine_stamp_still_wins_and_a_short_read_is_still_untruncated(self):
        spec = NON_FUTURES["psd_vintage"].model_copy(update={"limit": 3})
        assert NA.series_truncated({"query": spec.model_dump(exclude_none=True), "rows": [{"value": "1"}],
                                    "truncated": True}) is True
        assert NA.series_truncated({"query": spec.model_dump(exclude_none=True),
                                    "rows": [{"value": "1"}]}) is False


# ==================================================================================================
# 6. THE SEAM -- one env read, exact-'on', folded into the token the existing thread already carries
# ==================================================================================================
class TestSeam:
    def test_the_default_is_ON_and_only_an_explicit_disable_rolls_it_back(self, monkeypatch):
        """D-PQ FIX-1 INVERTED THIS SEAM'S POLARITY, and this test is where that is stated.

        D-AM-18 shipped it opt-in and exact-'on'. The D-CW-4 wired probe then measured the cost of opt-in
        on a lane where nobody set the env: a Nov-2019 MPOB row served as "the same month" under a
        model-chosen small `limit` (R3), and the 5000-cap oldest-kept read re-measured UNCHANGED (row 11) --
        while the model-facing `limit` schema had already been written to promise the newest end. So the
        DEFAULT is now on and the flag is the ROLLBACK.

        The fail-closed direction moves with it. It is no longer "only 'on' enables"; it is "only a
        recognised DISABLE disables", so a stray or misspelled value leaves the CORRECT ordering in place
        rather than silently restoring the defect."""
        monkeypatch.delenv(FLAG, raising=False)
        assert AN._series_newest_first_on() is True
        for val, want in (("off", False), ("OFF", False), (" off ", False), ("0", False),
                          ("false", False), ("no", False),
                          ("on", True), ("1", True), ("true", True), ("", True), ("maybe", True)):
            monkeypatch.setenv(FLAG, val)
            assert AN._series_newest_first_on() is want, val

    def test_the_scope_fold_is_pure_and_nests_the_two_flags(self):
        """No env read of its own -- both bools are read AT THE LANE and passed in, so one turn cannot
        disagree with itself. The estate-wide token WINS over the futures bool because the scopes nest."""
        assert AN._newest_first_scope(False, False) is False
        assert AN._newest_first_scope(True, False) is True
        assert AN._newest_first_scope(False, True) == ALL
        assert AN._newest_first_scope(True, True) == ALL
        assert FLAG not in inspect.getsource(AN._newest_first_scope)

    def test_the_seam_names_the_flag_and_is_read_per_call(self, monkeypatch):
        """A rename that orphaned the seam would leave the flag permanently off with nothing red; a
        memoized read would make the rollback need a redeploy."""
        assert FLAG in inspect.getsource(AN._series_newest_first_on)
        monkeypatch.setenv(FLAG, "off")
        assert AN._series_newest_first_on() is False
        monkeypatch.setenv(FLAG, "on")
        assert AN._series_newest_first_on() is True


# ==================================================================================================
# 7. REACHABILITY -- the token rides the caller graph the futures canary already threads
# ==================================================================================================
# WHY THIS SECTION EXISTS AT ALL. D-FR-10 shipped a compiler and a seam with NO caller in between: the flag
# was green in every unit test and changed not one byte of a served turn. D-AM-18 carries its scope in that
# same (now threaded) slot precisely so it inherits the fix -- but "inherits" is a claim, so it is measured
# at the compiler, through the real frames, exactly as section 7 of the futures pins file does.
_PLAIN_LOOKUP = {"table": "silver_pink_sheet", "metric": "palm_oil_cpo_usd_t", "agg": "series"}


def _sql_spy(monkeypatch) -> list:
    """Wrap `query.build_sql` and record the token each compile was ACTUALLY given. At the COMPILER, not at
    an intermediate signature: the failure being caught is a value accepted and then dropped a frame lower."""
    seen: list = []
    real = Q.build_sql

    def _spy(spec, ts=None, *, db=Q.ATHENA_DB, futures_newest_first=False):
        seen.append(futures_newest_first)
        return real(spec, ts, db=db, futures_newest_first=futures_newest_first)

    monkeypatch.setattr(Q, "build_sql", _spy)
    return seen


class _AgentMsgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.sent.append(kw)
        return self.outer.queue.pop(0)


class _FakeAgentClient:
    """The test_question_shapes fake-client idiom: an INJECTED client takes no provider and no backoff, so
    `answer_numbers` runs its real loop with zero network."""

    def __init__(self, tool_input: dict):
        from types import SimpleNamespace as _SNS
        self.queue = [
            _SNS(content=[_SNS(type="tool_use", name=NA.TOOL_NAME, input=dict(tool_input), id="t1")],
                 stop_reason="tool_use"),
            _SNS(content=[_SNS(type="text", text="ok")], stop_reason="end_turn")]
        self.sent: list = []
        self.messages = _AgentMsgs(self)


class TestTokenReachesTheCompiler:
    def test_through_the_cascade_leg_chain(self, monkeypatch):
        seen = _sql_spy(monkeypatch)
        CQ.fetch_window(lambda _sql: [], table="silver_pink_sheet", metric="palm_oil_cpo_usd_t",
                        commodity=None, country=None, t1="2011-01-01", t2="2011-12-31",
                        asof="2026-06-08", agg="series", futures_newest_first=ALL)
        assert seen == [ALL]

    def test_through_run_one_which_unpacks_a_dict_spec(self, monkeypatch):
        seen = _sql_spy(monkeypatch)
        CQ._run_one(lambda _sql: [], {"table": "silver_pink_sheet", "metric": "palm_oil_cpo_usd_t",
                                      "commodity": None, "country": None, "t1": "2011-01-01",
                                      "t2": "2011-12-31", "asof": "2026-06-08", "agg": "series",
                                      "period": None, "period_type": "date", "node_key": None,
                                      "leg": None, "era_idx": None, "my": None},
                    futures_newest_first=ALL)
        assert seen == [ALL]

    def test_through_the_numbers_agent(self, monkeypatch):
        seen = _sql_spy(monkeypatch)
        NA.answer_numbers("palm?", asof="2024-07-01", client=_FakeAgentClient(_PLAIN_LOOKUP),
                          query_fn=lambda _sql: [], futures_newest_first=ALL)
        assert seen and all(s == ALL for s in seen)

    def test_the_orchestrator_lane_threads_the_token_OMIT_WHEN_OFF(self, monkeypatch):
        """Both halves, with the D-PQ FIX-1 polarity. DEFAULT (no env at all) -> the estate-wide token,
        because the correct ordering is what a forgotten env block now produces; the explicit DISABLE ->
        the kwarg is ABSENT, which is what keeps the rollback byte-identical and keeps an injected
        answer_numbers fake with the pre-wave signature valid. The futures bool alone still yields the
        futures-scoped True, and the estate-wide token still wins over it."""
        from leviathan.graphrag import orchestrator as ORCH
        seen: list = []

        def _fake(question, asof, **kw):
            seen.append(kw.get("futures_newest_first", "ABSENT"))
            return {"answer": "x", "calls": []}

        monkeypatch.setattr(ORCH.na, "answer_numbers", _fake)
        monkeypatch.delenv("GRAPHRAG_FUTURES_NEWEST_FIRST", raising=False)
        monkeypatch.delenv(FLAG, raising=False)
        ORCH.run_numbers_only("q", "2026-06-08", query_fn=lambda _sql: [])       # default -> ALL
        monkeypatch.setenv(FLAG, "off")
        ORCH.run_numbers_only("q", "2026-06-08", query_fn=lambda _sql: [])       # rollback -> ABSENT
        monkeypatch.setenv("GRAPHRAG_FUTURES_NEWEST_FIRST", "on")
        ORCH.run_numbers_only("q", "2026-06-08", query_fn=lambda _sql: [])       # futures-scoped only
        monkeypatch.setenv(FLAG, "on")
        ORCH.run_numbers_only("q", "2026-06-08", query_fn=lambda _sql: [])
        assert seen == [ALL, "ABSENT", True, ALL]  # the estate-wide token wins over the futures bool

    def test_every_lane_above_the_seam_reaches_the_fold_BY_NAME(self):
        """The three lanes that compile a series read. A lane that never called the fold would be
        permanently futures-only with nothing red."""
        from leviathan.graphrag import orchestrator as ORCH
        from leviathan.graphrag import server as SV
        assert inspect.getsource(ORCH).count("_newest_first_scope(") == 2   # numbers_only + hybrid
        assert "_newest_first_scope(" in inspect.getsource(SV.series_route)
        assert "_newest_first_scope(" in inspect.getsource(AN._answer_l2)   # the cascade/quantify seam

    def test_the_three_unthreaded_read_sites_stay_DECISIONS(self):
        """The gaps D-FR-10 left because the FUTURES scope could not reach them: cascade's
        `_psd_component_rows` and `_cot_outcome_read`, and silverleg's `_rows`. The estate-wide token drops
        the `contract_month_col` key those omissions rested on, so each is now a decision rather than a
        structural fact -- and each carries its own bound in its own source (single marketing year / one
        slug over a horizon window / per-leg caps, plus silverleg's shared cache whose key carries no
        read-shape term). Pinned BOTH ways: still unthreaded, and still explained. Threading one of them is
        a fine change -- it just has to come with this record updated, which is what this reds for."""
        import inspect

        from leviathan.graphrag import silverleg as SLV
        for name, fn in (("cascade._psd_component_rows", CQ._psd_component_rows),
                         ("cascade._cot_outcome_read", CQ._cot_outcome_read),
                         ("silverleg._rows", SLV._rows)):
            assert "futures_newest_first" not in inspect.signature(fn).parameters, \
                f"{name} was threaded -- update the D-AM-18 gap record at answer._series_newest_first_on"
            assert "D-AM-18" in inspect.getsource(fn), f"{name} lost its D-AM-18 decision record"

    def test_the_v1_series_route_hands_the_token_to_the_compiler(self, monkeypatch):
        """/v1/series is the ONE user-facing surface that compiles an UNBOUNDED agg='series' read on ANY
        card -- the exact shape whose LIMIT 5000 keeps the oldest rows."""
        from fastapi.testclient import TestClient
        from leviathan.graphrag import server as sv
        from leviathan.graphrag.numbers.registry import load_registry
        monkeypatch.setitem(sv._STATE, "graph", None)
        seen: list = []

        def _run(spec, query_fn=None, *, futures_newest_first=False):
            seen.append(futures_newest_first)
            return []

        monkeypatch.setattr(Q, "run", _run)      # the route imports the module lazily -> patch the module
        reg = load_registry()
        table = next(t for t in reg.tables if reg.get(t).metrics)
        metric = next(iter(reg.get(table).metrics))
        client = TestClient(sv.app)
        monkeypatch.delenv("GRAPHRAG_FUTURES_NEWEST_FIRST", raising=False)
        monkeypatch.setenv(FLAG, "off")                       # D-PQ FIX-1: the DISABLE, not the absence
        assert client.get(f"/v1/series/{table}/{metric}").status_code == 200
        monkeypatch.delenv(FLAG, raising=False)               # ... and the default is the token
        assert client.get(f"/v1/series/{table}/{metric}").status_code == 200
        assert seen == [False, ALL]


# ==================================================================================================
# 8. D-PQ FIX-1 -- ANY BOUNDED SERVING READ KEEPS THE NEWEST ROWS, AT THE DEFAULT
# ==================================================================================================
# WHY THIS SECTION EXISTS ON TOP OF SECTIONS 1-7. Everything above measures the compiler and the
# threading GIVEN a token. What went un-measured -- and what the D-CW-4 wired probe then measured in
# production shape -- is which token a lane resolves when NOBODY SETS THE ENV. D-AM-18 shipped opt-in, so
# the answer was "none": R3 caught a Nov-2019 MPOB print served as "the same month" under a model-chosen
# small `limit`, and row 11 re-measured the 5000-cap oldest-kept read UNCHANGED. Meanwhile the tool
# schema's own `limit` description (D-CW-1c) already PROMISED the model the newest end.
#
# So these tests are written at the SEAM RESOLUTION, not at a hand-passed token: they ask what a serving
# lane compiles today, with the environment as a forgotten env block leaves it.
def _serving_scope() -> object:
    """The token a serving lane resolves this call -- the same one-line fold `orchestrator`, `server` and
    `answer._answer_l2` each perform. Read through the real seams so a polarity change cannot pass here."""
    return AN._newest_first_scope(AN._futures_newest_first_on(), AN._series_newest_first_on())


class TestTheServingDefaultKeepsTheNewestRows:
    @pytest.fixture(autouse=True)
    def _no_env(self, monkeypatch):
        """A forgotten env block, exactly: neither flag set anywhere."""
        monkeypatch.delenv(FLAG, raising=False)
        monkeypatch.delenv("GRAPHRAG_FUTURES_NEWEST_FIRST", raising=False)

    def test_the_default_resolution_is_the_estate_wide_token(self):
        assert _serving_scope() == ALL

    @pytest.mark.parametrize("name", sorted(NON_FUTURES))
    @pytest.mark.parametrize("limit", [1, 12, 5000])
    def test_every_bounded_read_compiles_newest_first_at_the_default(self, name, limit):
        """SMALL limit and the 5000 DEFAULT, on every non-futures shape the defect names. The cap is
        unchanged -- only which end it keeps -- so the LIMIT clause is asserted intact beside the order."""
        spec = NON_FUTURES[name].model_copy(update={"limit": limit})
        ts = _ts(spec.table)
        sql = Q.build_sql(spec, ts, futures_newest_first=_serving_scope())
        assert _terms(sql) and all(t.endswith("DESC NULLS LAST") for t in _terms(sql))
        assert sql.rstrip().endswith(f"LIMIT {limit}")

    def test_the_oldest_5000_class_is_dead_on_the_corn_settle_series(self):
        """THE NAMED CLASS. An unwindowed per-slug corn_cbot settle series is ~49k rows against a 5000 cap;
        ascending, the surviving rows stopped in 2011 and the answer narrated a fifteen-year-old price at
        today's as-of. At the default the same read now keeps the newest 5000."""
        spec = _spec(EOD, "settle", commodity="corn_cbot")
        assert spec.limit == 5000
        sql = Q.build_sql(spec, _ts(EOD), futures_newest_first=_serving_scope())
        assert all(t.endswith("DESC NULLS LAST") for t in _terms(sql))
        assert sql.rstrip().endswith("LIMIT 5000")

    def test_the_rows_still_arrive_ASCENDING_so_no_consumer_moved(self):
        """The half a flip is worthless without, taken through `run()` at the DEFAULT: the fetch is
        newest-first, the presentation is the ascending order every `series[-1]` consumer indexes into."""
        rows = [{"value": str(v), "period": f"{y}/{str(y + 1)[2:]}", "knowledge_date": "2026-05-12"}
                for v, y in ((3, 2025), (2, 2024), (1, 2023))]           # a DESC fetch, as the SQL returns it
        seen: list = []

        def _qfn(sql):
            seen.append(sql)
            return [dict(r) for r in rows]

        got = Q.run(NON_FUTURES["psd_vintage"], query_fn=_qfn, futures_newest_first=_serving_scope())
        assert all(t.endswith("DESC NULLS LAST") for t in _terms(seen[0]))
        assert [r["period"] for r in got] == ["2023/24", "2024/25", "2025/26"]

    def test_the_front_expiry_anchor_is_UNAFFECTED_in_both_halves(self):
        """D-PQ A' is not a series branch, so the re-sort must stay inert on it -- a front-expiry read
        reversed as though it were a truncated series would reverse the very rows the roll rule is about
        to be handed. And its cap is `CURVE_ROW_CAP`, never `spec.limit` (FIX-1b), so a model-emitted
        `limit=1` can no longer hand the rule a one-row frame."""
        ts = _ts(EOD)
        fe = Q.NumberQuery(table=EOD, metric="settle", asof="2026-06-08", commodity="corn_cbot",
                           agg=Q.FRONT_EXPIRY_AGG, limit=1)
        assert Q._is_series_branch(fe, ts) is False
        assert Q._newest_first_applies(fe, ts, _serving_scope()) is False
        sql = Q.build_sql(fe, ts, futures_newest_first=_serving_scope())
        assert "DESC NULLS LAST" not in sql
        assert sql.rstrip().endswith(f"LIMIT {Q.CURVE_ROW_CAP}")

    def test_the_rollback_still_restores_the_pre_wave_compile_everywhere(self, monkeypatch):
        """ANTI-VACUITY plus the lever. One env value returns every card above to the byte-identical
        ascending string -- otherwise this section would be pinning an unrollbackable change."""
        monkeypatch.setenv(FLAG, "off")
        assert _serving_scope() is False
        for name in sorted(NON_FUTURES):
            spec, ts = NON_FUTURES[name], _ts(NON_FUTURES[name].table)
            assert Q.build_sql(spec, ts, futures_newest_first=_serving_scope()) == Q.build_sql(spec, ts)
