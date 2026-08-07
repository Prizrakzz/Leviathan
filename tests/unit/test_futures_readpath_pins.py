"""FUTURES_READPATH wave -- the TIER-1 ACCEPTANCE SURFACE (plan section 6.1), lane P.

WHAT THIS FILE IS
-----------------
`docs/private/FUTURES_READPATH_WAVE_PLAN.md` section 6.1 is a table of deterministic checks, each with an
ANTI-VACUITY twin, that a wave green is supposed to mean. This file is the subset of that table which is
expressible as an offline unit test. Pure/hermetic: no AWS, no LLM, no pg, no eval run.

It is deliberately NOT inside the code lanes' own suites. `test_numbers_query.py`, `test_futures_lite.py`
and `test_futures_eod_curve.py` are edited by whoever lands S0/S1/U1; this file is the acceptance surface
those changes are measured AGAINST, so it follows the `test_register_corpus.py` rule -- if a change needs
an edit here, that edit is a conspicuous diff and has to carry the measurement that justifies it.

WHERE THE TWO-SIDED PINS FOR THE NEW DECLINE PROSE LIVE -- SAID EXPLICITLY, BECAUSE 6.1 REQUIRES IT
---------------------------------------------------------------------------------------------------
6.1's "Two-sided corpus pins" row is conditional and ends *"say which, or the two-sided convention is
silently dropped"*. D-FR-7 was ratified as RECOMMENDED, i.e. the TOOL-RESULT reason, not the preface
variant. So: **the corpus (`tests/unit/test_register_corpus.py`) is NOT the home for these strings, and
the two-sided pins are the fixture assertions in section 1 below.** The reason is structural, not
stylistic -- `test_register_corpus.py` pins prose the RENDERER emits into an answer; a tool-result reason
never reaches `calls`, never reaches a citation and never reaches a preface. It is reader-reachable only
because the model narrates it, so what must be pinned is that the string CANNOT carry register vocabulary
into that narration, on both sides:

  * MUST_NOT_FLAG half -- the three LIVE constants, rendered, are clean through every gate 4.6 names
    (`register_leaks`, `exec_leaks`, `count_valuation_words`, `count_flow_words`, `_is_banned_sentence`)
    under BOTH the FENCED and OUTLOOK registers, survive `sanitize` byte-identically, and never say
    "settle" (the futures census bans the word in decline prose, and a template about futures prices
    reaches for it naturally);
  * MUST_FLAG half -- the same sentences EDITORIALIZED, which is the live failure mode and not a
    hypothetical one (`test_register_corpus.py:411-418` records a real render that put a flow verdict in
    the same paragraph as an absence clause). Without this half, a clean result proves the gates were
    quiet, not that they were watching.

WHAT IS NOT HERE, AND WHY -- so nobody reads this file as covering more than it does
------------------------------------------------------------------------------------
* **U3's trace key**, PARTLY. The orchestrator half landed with the S1 threading wave: `unit_mismatch_guard`
  is now in all three fixed tuples (numbers_only + both hybrid sites) and section 7.5 pins that COUPLING.
  The behavioural non-vacuity twin -- present WITH the two units on a mismatch turn, ABSENT on a
  matched-unit turn, on BOTH lanes -- lives in `test_numbers_stats.py` beside the live guard that mints it,
  where the cross-unit fixture already exists. `eval.py`'s row projection is still NOT landed, so the key
  reaches a trace but not yet an eval column.
* **S5's sentinel re-wording** -- LANDED (D-PQ FIX-1), and no longer this file's gap. `agent.format_provenance`
  and `eval._num_line` said "OLDEST rows kept"; the estate-wide newest-first scope is now the SERVING DEFAULT
  (`answer._series_newest_first_on` inverted to opt-out), which made those strings the exact inverse of the
  truth. Both now say the NEWEST rows survive and the EARLY end of the window is gone, pinned with a negative
  half in `test_numbers_agent.py`. What is still NOT here is D-FR-14's census line, below.
* **D-FR-14's census line.** Exit (1) puts the three strings in a registered template dict that
  `config_check`'s futures_lite census lints. Until that lands, `config_check`'s 6.1 row is NOT evidence
  for U2 -- section 1 carries a tripwire that says so out loud.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import config_check as CC
from leviathan.graphrag import register as REG
from leviathan.graphrag.numbers import agent as NA
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R
from leviathan.graphrag.numbers import stats as ST

EOD = "silver_futures_eod"
WASDE = "silver_wasde"


def _card(table: str) -> dict:
    """The LIVE card out of the raw tables.yaml, read the way test_futures_eod_curve.py reads it."""
    return dict(CC._load("numbers/tables.yaml")["tables"][table])


def _ts(table: str) -> R.TableSpec:
    return R.TableSpec(id=table, **_card(table))


def _units(table: str, metric: str) -> dict:
    return dict(_card(table)["metrics"][metric]["unit_overrides"])


def _h(series, unit, kd: str = "2026-06-05") -> dict:
    """A stat handle in the shape `_exec_stat` mints (agent.py: {series, kd, unit})."""
    return {"series": list(series), "unit": unit, "kd": kd}


# A corn settle history with real magnitudes: 30 points is comfortably above stats.MIN_PERCENTILE_N (8),
# so a decline here can never be a thinness floor wearing a unit reason.
CORN_SERIES = [400.0 + i for i in range(30)]
CORN_UNIT = "US cents/bushel"


# ==================================================================================================
# 1. THE NEW DECLINE PROSE -- TWO-SIDED (D-FR-7 tool-result exit; 4.6's lint list)
# ==================================================================================================
def _rendered() -> dict[str, str]:
    """The three strings AS THE MODEL RECEIVES THEM, rendered off the LIVE constants rather than copied.
    A copy would let an edit to the engine's wording ship past this file, which is the one thing it is
    for -- the `test_the_pinned_addendum_is_the_engines_own_object` discipline."""
    return {
        "unit_mismatch": ST.UNIT_MISMATCH_DECLINE.format(a="$/bu", b="US cents/bushel"),
        "unit_unknown": ST.UNIT_UNKNOWN_DECLINE.format(known="US cents/bushel"),
        "empty_series": ST.EMPTY_SERIES_DECLINE.format(which="history series"),
    }


# The MUST_FLAG half. Each is one of the three declines with a VERDICT bolted on -- the shape a later
# tone edit produces, one gate each so a single over-broad rule cannot make all three pass at once.
TEETH = {
    "valuation": (
        "The two series are quoted in different units ($/bu against US cents/bushel), so no figure is "
        "computed -- but the board screens expensive against the farm price."),
    "flow": (
        "The history series came back with no rows at all, so there is nothing to compute over, but "
        "positioning is stretched all the same."),
    "exec": (
        "One of the two series carries no unit label, so no figure is computed -- go long the December "
        "contract instead."),
}


class TestDeclineProseTwoSided:
    @pytest.mark.parametrize("name", sorted(_rendered()))
    def test_must_not_flag_under_both_registers(self, name):
        s = _rendered()[name]
        assert REG.register_leaks(s) == [], (name, s)
        assert REG.exec_leaks(s) == [], (name, s)
        assert REG.count_valuation_words(s) == 0 and REG.count_flow_words(s) == 0, (name, s)
        for mr in (REG.FENCED, REG.OUTLOOK):
            assert REG._is_banned_sentence(s, market_register=mr) is False, (name, mr)
            # sanitize STRIPS an offending sentence rather than paraphrasing it, so a byte-identical
            # round trip is the only proof the whole reason survives to the model unedited.
            assert REG.sanitize(s, market_register=mr) == s, (name, mr)

    @pytest.mark.parametrize("name", sorted(_rendered()))
    def test_the_futures_census_word_ban_is_respected(self, name):
        # config_check.py's futures_lite census BANS "settle" in decline prose. A template about futures
        # prices reaches for it naturally; neither draft used it and this keeps it that way.
        assert "settle" not in _rendered()[name].lower()

    @pytest.mark.parametrize("name", sorted(TEETH))
    def test_MUST_FLAG_the_editorialized_rewrite(self, name):
        # THE ANTI-VACUITY HALF. Without it the block above proves the gates were quiet, not that they
        # were watching: a register rule that had gone dark would pass every clean assertion.
        s = TEETH[name]
        caught = bool(REG.register_leaks(s)) or REG.count_valuation_words(s) or REG.count_flow_words(s)
        assert caught, f"{name}: the editorialized decline passed every register gate :: {s!r}"
        assert REG._is_banned_sentence(s, market_register=REG.FENCED) is True
        assert REG.sanitize(s, market_register=REG.FENCED) != s, "the offending sentence was not stripped"

    def test_each_teeth_case_targets_a_DIFFERENT_gate(self):
        # Three cases against one gate would be one case wearing three names.
        assert REG.count_valuation_words(TEETH["valuation"]) > 0
        assert REG.count_flow_words(TEETH["flow"]) > 0
        assert REG.exec_leaks(TEETH["exec"]) != []

    def test_the_reason_the_agent_actually_hands_the_model_is_one_of_these_strings(self):
        # Pinned against the LIVE builder, not the constant: `unit_decline` chooses between the mismatch
        # and the asymmetric wording, and that choice is what the model narrates.
        both_known = ST.unit_decline("percentile", 30, "$/bu", CORN_UNIT)["reason"]
        one_known = ST.unit_decline("percentile", 30, None, CORN_UNIT)["reason"]
        assert both_known == ST.UNIT_MISMATCH_DECLINE.format(a="$/bu", b=CORN_UNIT)
        assert one_known == ST.UNIT_UNKNOWN_DECLINE.format(known=CORN_UNIT)
        # and the asymmetric leg never renders the missing side as the literal None -- handing the model
        # "quoted in different units (US cents/bushel against None)" would be a false explanation.
        assert "None" not in one_known

    def test_the_config_check_census_does_NOT_yet_cover_these_strings(self):
        """D-FR-14 exit (1), stated as a tripwire instead of an assumption.

        6.1 carries a `config_check` full-run row. RE-MEASURED: `config_check.py:1437` iterates
        `FUTURES_DECLINE_TEMPLATES` and `:2074+` iterates question SHAPES -- NEITHER enumerates the
        stats-module strings, so that row is green whether these leak register vocabulary or not, and it
        must NOT be counted as evidence for U2 while this holds. The coverage that exists today is the
        block above, in this file.

        This assertion INVERTS when exit (1) lands: register the three strings beside
        `FUTURES_DECLINE_TEMPLATES` and add the census line, then rewrite this test to assert the census
        SEES them. Deleting it instead is the failure mode it exists to prevent."""
        registered = set(NA.FUTURES_DECLINE_TEMPLATES.values())
        assert not (set(_rendered().values()) & registered), (
            "the U1 decline strings are now in FUTURES_DECLINE_TEMPLATES -- D-FR-14 exit (1) has landed. "
            "Add the config_check census line and re-point this test at the census, do not delete it.")


# ==================================================================================================
# 2. U1 -- the unit-compatibility guard (6.1's U1 block, on the live _dispatch_stat)
# ==================================================================================================
class TestU1Guard:
    def test_two_handles_units_differ_declines_and_names_both(self):
        res = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                {"s": _h(CORN_SERIES, CORN_UNIT), "v": _h([4.15], "$/bu")})
        assert res["declined"] is True and res["value"] is None
        assert CORN_UNIT in res["reason"] and "$/bu" in res["reason"]
        assert res["guard"] == ST.UNIT_GUARD

    def test_ANTI_VACUITY_matched_units_compute(self):
        # The R8 (a) idiom: the same fixture with matched units must COMPUTE, so the decline above
        # cannot pass by refusing a call that was never coming.
        res = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                {"s": _h(CORN_SERIES, CORN_UNIT), "v": _h([417.5], CORN_UNIT)})
        assert res["declined"] is False and res["value"] is not None

    def test_matched_unit_path_is_BYTE_IDENTICAL_to_the_guard_free_result(self):
        # Byte equality against the pre-guard result, not a substring. The oracle is stats.percentile
        # itself -- the exact call `_dispatch_stat` makes once the guard passes.
        got = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                {"s": _h(CORN_SERIES, CORN_UNIT), "v": _h([417.5], CORN_UNIT)})
        assert got == ST.percentile(417.5, CORN_SERIES)

    def test_both_unknown_path_is_BYTE_IDENTICAL(self):
        # ~17 of 19 cards declare no unit source at all, so a fail-closed rule here would have been a
        # large unmeasured behaviour change shipped to fix a futures defect (D-FR-5).
        got = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                {"s": _h(CORN_SERIES, None), "v": _h([417.5], None)})
        assert got == ST.percentile(417.5, CORN_SERIES)
        blank = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                  {"s": _h(CORN_SERIES, ""), "v": _h([417.5], None)})
        assert blank == ST.percentile(417.5, CORN_SERIES)

    @pytest.mark.parametrize("a,b", [(None, CORN_UNIT), (CORN_UNIT, None), ("", CORN_UNIT), (CORN_UNIT, "")])
    def test_asymmetric_path_declines(self, a, b):
        res = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                {"s": _h(CORN_SERIES, a), "v": _h([417.5], b)})
        assert res["declined"] is True and res["guard"] == ST.UNIT_GUARD

    def test_EMPTY_handle_declines_for_EMPTINESS_not_units(self):
        # A coverage-declined silver_futures_eod read returns rows: [] -> unit None, series [] -- i.e.
        # this exact shape arrives on the very path the wave exists to fix. Under the three-state rule
        # known-vs-unknown declines, so a unit-first order would hand the model a false explanation.
        res = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                {"s": _h(CORN_SERIES, CORN_UNIT), "v": _h([], None)})
        assert res["declined"] is True and res["guard"] == ST.EMPTY_GUARD
        assert "different units" not in res["reason"]
        assert "None" not in res["reason"]

    def test_EMPTINESS_is_ordered_FIRST(self):
        # An empty handle whose unit ALSO differs still declines with the emptiness reason. Without the
        # ordering this case is indistinguishable from a unit mismatch in every artifact.
        res = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                {"s": _h(CORN_SERIES, CORN_UNIT), "v": _h([], "$/bu")})
        assert res["guard"] == ST.EMPTY_GUARD and "different units" not in res["reason"]

    def test_n_is_the_SERIES_handles_length(self):
        # `n` is positional, required, and REACHES THE MODEL. It must never be a fabricated 0 a reader
        # could mistake for "no data", and never the value handle's length: this refusal is about the
        # comparison, not about thinness.
        res = NA._dispatch_stat("zscore", {"series_handle": "s", "value_handle": "v"},
                                {"s": _h(CORN_SERIES, CORN_UNIT), "v": _h([4.15, 4.24], "$/bu")})
        assert res["n"] == len(CORN_SERIES) == 30
        assert res["n"] != 0 and res["n"] != 2

    @pytest.mark.parametrize("stat,inp", [
        ("streak", {"direction": "up"}),
        ("window_change", {"t1": 0, "t2": -1}),
        ("revision_count", {"direction": "up"}),
        ("extrema", {}),
        ("yoy_delta", {"periods": 1}),
        ("percentile", {}),
        ("zscore", {}),
    ])
    @pytest.mark.parametrize("unit", [None, "", CORN_UNIT, "$/bu", "BRL/60-kg bag"])
    def test_the_guard_does_NOT_fire_on_a_single_handle(self, stat, inp, unit):
        # The trigger is `value_handle is not None`. A one-handle stat has nothing to compare a unit
        # against, so EVERY unit value must leave all seven stats byte-identical to their guard-free
        # result. This is also the boundary of U1's claimed coverage -- see TestUncoveredByU1.
        handles = {"s": _h(CORN_SERIES, unit)}
        got = NA._dispatch_stat(stat, {"series_handle": "s", **inp}, handles)
        assert got.get("guard") is None
        assert got["declined"] is False


# ==================================================================================================
# 3. D-FR-16 -- the four MEASURED false declines, pinned as declines (ratified exit (a))
# ==================================================================================================
class TestFalseDeclineSurface:
    """The recommended rule's OWN cost, censused rather than asserted. The estate's unit vocabulary is
    not normalized across cards, and `strip()`+`casefold()` does not close the gap, so four
    dimensionally and numerically IDENTICAL pairs are refused today. They are pinned as declines because
    a false decline is an honest refusal a reader can act on while a false COMPUTE is a wrong [N].

    IF D-FR-16 EVER TAKES EXIT (b) -- one spelling per (currency, physical unit) in the CARD CONFIG under
    a config_check lint, never a runtime alias -- THIS CLASS INVERTS TO COMPUTE and the lint carries it.
    That is the intended way for these assertions to die: re-authored with the config change, not
    deleted."""

    # (wasde avg_farm_price commodity, futures_eod settle slug) -- the four measured pairs.
    PAIRS = [("wheat", "hard_red_spring_wheat_mgex"),      # $/bu   vs USD/bushel   (the headline slug)
             ("cotton", "cotton"),                          # c/lb   vs US cents/lb
             ("soybean_meal", "soybean_meal_cbot"),         # $/s.t. vs USD/short ton
             ("rice", "rough_rice_cbot")]                   # $/cwt  vs USD/cwt

    def test_the_four_pairs_still_have_the_spellings_that_were_measured(self):
        w, e = _units(WASDE, "avg_farm_price"), _units(EOD, "settle")
        assert [(w[a], e[b]) for a, b in self.PAIRS] == [
            ("$/bu", "USD/bushel"), ("c/lb", "US cents/lb"),
            ("$/s.t.", "USD/short ton"), ("$/cwt", "USD/cwt")]

    @pytest.mark.parametrize("wasde_c,eod_slug", PAIRS)
    def test_each_dimensionally_identical_pair_DECLINES_today(self, wasde_c, eod_slug):
        a = _units(WASDE, "avg_farm_price")[wasde_c]
        b = _units(EOD, "settle")[eod_slug]
        assert ST.unit_compatible(a, b) is False
        res = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                {"s": _h(CORN_SERIES, b), "v": _h([4.15], a)})
        assert res["declined"] is True and res["guard"] == ST.UNIT_GUARD

    def test_ANTI_VACUITY_the_genuine_100x_pair_declines_for_the_RIGHT_reason(self):
        # $/bu vs US cents/bushel is a REAL factor-of-100 mismatch and is correctly refused. Pinned
        # beside the four so the class cannot be read as "the guard refuses everything".
        w, e = _units(WASDE, "avg_farm_price"), _units(EOD, "settle")
        assert ST.unit_compatible(w["corn"], e["corn_cbot"]) is False
        # ... and the SAME-card, same-slug comparison still computes, which is what makes the four above
        # a measurable cost rather than a broken predicate.
        assert ST.unit_compatible(e["corn_cbot"], e["corn_cbot"]) is True
        assert ST.unit_compatible(e["soybean_meal_cbot"], e["soybean_meal_cbot"]) is True


# ==================================================================================================
# 4. D-FR-17 -- the two classes U1 structurally CANNOT reach, pinned as UNCOVERED
# ==================================================================================================
class TestUncoveredByU1:
    """NAMED as outside U1's coverage and pinned as such, so no reviewer reads U1 as closing the
    wrong-number class. Both of these COMPUTE today and must still COMPUTE after U1 -- if either ever
    starts declining, U1 was widened mid-wave and that is a decision, not a bug fix."""

    def test_i_one_handle_over_MIXED_unit_rows_is_structurally_dark(self):
        # The trigger is `value_handle is not None`; `_val()` falls back to series[-1] and the handle's
        # unit is sampled from rows[0] ALONE. On the two unit_col cards a commodity-less lookup returns
        # mixed-unit rows with no DP-1 raise, so a percentile scores one unit's value against a
        # mixed-unit distribution with U1 dark. No widening of the unit VOCABULARY fixes this; the
        # honest closure is a homogeneity check at the MINT, which is its own item.
        res = NA._dispatch_stat("percentile", {"series_handle": "s"}, {"s": _h(CORN_SERIES, "$/bu")})
        assert res["declined"] is False and res.get("guard") is None

    def test_ii_LEVEL_versus_DELTA_computes_at_the_0th_percentile(self):
        # _STAT_UNIT covers streak/revision_count/percentile/zscore ONLY, so window_change / yoy_delta /
        # extrema mint CHAINED handles carrying the RAW price unit. known == known -> COMPUTE, and the
        # +29c delta lands at the 0th percentile of a ~400c distribution, minted as a cited [N].
        assert "window_change" not in NA._STAT_UNIT
        delta = NA._dispatch_stat("window_change", {"series_handle": "s", "t1": 0, "t2": -1},
                                  {"s": _h(CORN_SERIES, CORN_UNIT)})
        chained_unit = NA._STAT_UNIT.get("window_change", CORN_UNIT)
        assert chained_unit == CORN_UNIT                       # the chained handle inherits the LEVEL unit
        res = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "d"},
                                {"s": _h(CORN_SERIES, CORN_UNIT), "d": _h([delta["value"]], chained_unit)})
        assert res["declined"] is False
        assert res["value"] == 0.0, "the wrong number this class produces is a 0th-percentile rank"

    def test_ANTI_VACUITY_the_self_united_stats_ARE_covered(self):
        # The counterpart: percentile/zscore/streak/revision_count DO get a synthetic output unit, so
        # ranking a percentile handle inside a price distribution is known-vs-known-different and
        # DECLINES with no special case. Without this the class above reads as "U1 catches nothing".
        assert NA._STAT_UNIT["percentile"] == "percentile"
        res = NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "p"},
                                {"s": _h(CORN_SERIES, CORN_UNIT), "p": _h([60.0], "percentile")})
        assert res["declined"] is True and res["guard"] == ST.UNIT_GUARD


# ==================================================================================================
# 5. S3 / S4 / S7 -- the shape of a series read, and the two anti-vacuity twins
# ==================================================================================================
CURVE_MONTHS = ("2026-07", "2026-09", "2026-12", "2027-03", "2027-05", "2027-07", "2027-09",
                "2027-12", "2028-03", "2028-05", "2028-07", "2028-12", "2029-12")


def _curve_rows() -> list[dict]:
    """The documented CURVE read: MANY expiries, ONE session -- corn_cbot's 13 delivery months on the
    2026-06-05 session (the shape curve12 pins on five rows), MEASURED 2026-08-04."""
    return [{"contract_month": m, "data_date": "2026-06-05", "value": "440"} for m in CURVE_MONTHS]


def _month_rows() -> list[dict]:
    """The other shape: ONE expiry, MANY sessions -- a single delivery month's own trading history."""
    return [{"contract_month": "2026-12", "data_date": f"2026-06-{d:02d}", "value": "440"}
            for d in range(1, 23)]


class TestSeriesShape:
    def test_S7_ANTI_VACUITY_the_two_shapes_are_both_NON_DEGENERATE(self):
        # 6.1, verbatim: n_expiries == 13 and n_sessions == 1 on a single-session curve fixture;
        # n_expiries == 1 and n_sessions == 22 on a single-expiry month fixture. A shape function that
        # returned (1, 1) for everything would pass a presence check and nothing else.
        curve = Q.series_shape(_curve_rows())
        assert (curve["n_expiries"], curve["n_sessions"], curve["n_rows"]) == (13, 1, 13)
        assert curve["first_date"] == curve["last_date"] == "2026-06-05"
        month = Q.series_shape(_month_rows())
        assert (month["n_expiries"], month["n_sessions"], month["n_rows"]) == (1, 22, 22)
        assert (month["first_date"], month["last_date"]) == ("2026-06-01", "2026-06-22")

    def test_a_cash_index_reads_ZERO_expiries_not_one(self):
        # "" IS absence on both backends, so an all-NULL contract_month column counts ZERO distinct
        # values. That distinction is what stops the two CEPEA cash slugs from being read as a
        # one-expiry curve -- and it is what keeps S4's conjunction honest on them.
        cash = [{"contract_month": None, "data_date": f"2026-06-{d:02d}", "value": "1433.64"}
                for d in range(1, 6)]
        assert Q.series_shape(cash)["n_expiries"] == 0
        assert Q.series_shape([{"contract_month": "", "data_date": "2026-06-05"}])["n_expiries"] == 0

    def test_an_empty_read_returns_zeros_rather_than_raising(self):
        # An empty read is already declined upstream for EMPTINESS; this must not become a second,
        # competing reason.
        assert Q.series_shape([])["n_rows"] == 0

    def test_S4_ANTI_VACUITY_TWIN_1_single_expiry_multi_session_still_computes(self):
        shape = Q.series_shape(_month_rows())
        assert shape["n_expiries"] == 1 and shape["n_sessions"] > 1
        got = NA._dispatch_stat("window_change", {"series_handle": "s", "t1": 0, "t2": -1},
                                {"s": _h(CORN_SERIES, CORN_UNIT)})
        assert got["declined"] is False

    def test_S4_ANTI_VACUITY_TWIN_2_multi_expiry_single_session_still_computes(self):
        # The documented curve read -- the shape curve12 pins on FIVE rows. S4's discriminator is a
        # CONJUNCTION (>1 expiry AND >1 session) precisely so this stays computable: a ">1 distinct
        # contract_month" test alone would have refused the read the deck exists to exercise.
        shape = Q.series_shape(_curve_rows())
        assert shape["n_expiries"] > 1 and shape["n_sessions"] == 1
        curve_levels = [417.5, 427.0, 446.0, 461.5, 470.75, 476.25, 470.5, 478.25, 489.0]
        assert NA._dispatch_stat("extrema", {"series_handle": "s"},
                                 {"s": _h(curve_levels, CORN_UNIT)})["declined"] is False
        assert NA._dispatch_stat("percentile", {"series_handle": "s", "value_handle": "v"},
                                 {"s": _h(curve_levels, CORN_UNIT),
                                  "v": _h([446.0], CORN_UNIT)})["declined"] is False


# ==================================================================================================
# 6. S1 -- the canary's scope, and the two orderings that must not touch each other
# ==================================================================================================
def _series_spec(table: str, metric: str, **kw) -> Q.NumberQuery:
    base = dict(table=table, metric=metric, asof="2026-06-08", agg="series")
    base.update(kw)
    return Q.NumberQuery(**base)


class TestS1CanaryScope:
    def test_flag_OFF_is_byte_identical_SQL_on_the_futures_series_branch(self):
        # The rollback comes from the idiom, not from a promise: with the kwarg absent the compiler must
        # emit the string it emitted before the wave.
        spec, ts = _series_spec(EOD, "settle", commodity="corn_cbot"), _ts(EOD)
        assert Q.build_sql(spec, ts) == Q.build_sql(spec, ts, futures_newest_first=False)

    def test_flag_ON_flips_ONLY_the_series_branch_and_carries_NULLS_LAST_on_every_term(self):
        spec, ts = _series_spec(EOD, "settle", commodity="corn_cbot"), _ts(EOD)
        off, on = Q.build_sql(spec, ts), Q.build_sql(spec, ts, futures_newest_first=True)
        assert off != on, "the canary is a no-op on the futures series branch -- S1 did not land"
        order_on = on.split("ORDER BY", 1)[1]
        terms = [t.strip() for t in order_on.split("LIMIT", 1)[0].split(",")]
        assert terms and all(t.endswith("DESC NULLS LAST") for t in terms), terms
        # ...and the ASC form it replaces carried no explicit null placement at all, which is why the
        # flip has to state one: Presto and Postgres disagree on the default for DESC.
        assert "NULLS LAST" not in off.split("ORDER BY", 1)[1]

    def test_agg_latest_is_byte_identical_under_the_flag(self):
        # The named-expiry / latest-value branch is the one D-OJ-8 certified safe; S1 must stay off it.
        ts = _ts(EOD)
        spec = Q.NumberQuery(table=EOD, metric="settle", asof="2026-06-08",
                             commodity="corn_cbot", agg="latest")
        assert Q.build_sql(spec, ts) == Q.build_sql(spec, ts, futures_newest_first=True)
        curve = Q.NumberQuery(table=EOD, metric="settle", asof="2026-06-08", commodity="corn_cbot",
                              agg="latest", contract_month="2026-12,2027-03")
        assert Q.build_sql(curve, ts) == Q.build_sql(curve, ts, futures_newest_first=True)

    def test_a_card_with_no_contract_month_col_is_byte_identical_under_the_flag(self):
        # D-FR-2 ratified the change FUTURES-SCOPED. Every card without contract_month_col compiles
        # unchanged whether the canary is on or off -- the estate-wide alternative is a different
        # decision with a pg-parity soak attached.
        ts = _ts(WASDE)
        assert ts.contract_month_col is None
        spec = _series_spec(WASDE, "avg_farm_price", commodity="corn", country="united_states")
        assert Q.build_sql(spec, ts) == Q.build_sql(spec, ts, futures_newest_first=True)
        assert Q._newest_first_applies(spec, ts, True) is False

    def test_the_scope_guard_is_ONE_predicate_so_sql_and_rows_cannot_drift(self):
        # A flipped SQL whose rows were never re-sorted is the partial failure that leaves every
        # consumer looking right while the cap keeps the wrong end.
        ts = _ts(EOD)
        series = _series_spec(EOD, "settle", commodity="corn_cbot")
        latest = Q.NumberQuery(table=EOD, metric="settle", asof="2026-06-08",
                               commodity="corn_cbot", agg="latest")
        assert Q._newest_first_applies(series, ts, True) is True
        assert Q._newest_first_applies(series, ts, False) is False
        assert Q._newest_first_applies(latest, ts, True) is False


class TestS1ResortKey:
    """D-FR-18: the Python re-sort key mirrors `_total_order` MINUS its final `value` term."""

    def test_the_key_does_NOT_contain_value(self):
        # Both backends hand Q.run STRINGS in different textual forms for the same float -- Athena
        # prints 1.5461095E7, psycopg prints 15461095.0 -- so a string-compare on `value` would break
        # ties differently on the two backends AND differently from the SQL, re-introducing the exact
        # divergence `_total_order` exists to prevent.
        keys = Q._order_aliases(Q._extras(_ts(EOD)), False)
        assert "value" not in keys
        assert keys, "the re-sort key is empty -- the re-sort would be a no-op"

    def test_the_E_NOTATION_pair_sorts_identically(self):
        # 6.1's pin, literal: "1.5461095E7" and "15461095.0" must sort identically. They do, because
        # `value` is not a key term at all -- and `sorted` is stable, so the executor's order survives.
        ts, spec = _ts(EOD), _series_spec(EOD, "settle", commodity="corn_cbot")
        base = {"leviathan_slug": "corn_cbot", "contract_month": "2026-12", "data_date": "2026-06-05"}
        a = Q.resort_rows_chronological([{**base, "value": "1.5461095E7"},
                                         {**base, "value": "15461095.0"}], spec, ts)
        b = Q.resort_rows_chronological([{**base, "value": "15461095.0"},
                                         {**base, "value": "1.5461095E7"}], spec, ts)
        assert [r["value"] for r in a] == ["1.5461095E7", "15461095.0"]
        assert [r["value"] for r in b] == ["15461095.0", "1.5461095E7"]

    def test_ANTI_VACUITY_the_key_really_does_reorder_on_its_own_terms(self):
        # If the key were empty or inert, the test above would pass for the wrong reason. Feed it rows
        # in DESC order on a term the key DOES carry and require the ascending restoration.
        ts, spec = _ts(EOD), _series_spec(EOD, "settle", commodity="corn_cbot")
        desc = [{"leviathan_slug": "corn_cbot", "contract_month": m, "data_date": d, "value": "1"}
                for m, d in (("2027-03", "2026-06-05"), ("2026-12", "2026-06-04"),
                             ("2026-07", "2026-06-03"))]
        got = Q.resort_rows_chronological(desc, spec, ts)
        assert [r["data_date"] for r in got] == ["2026-06-03", "2026-06-04", "2026-06-05"]


class TestS1ResortPlacement:
    """6.1: the re-sort runs BETWEEN the executor and `_apply_unit_overrides`, on the RAW rows.

    `unit` is a real total-order term and `_apply_unit_overrides` CLOBBERS `r["unit"]` on every row of a
    metric carrying overrides -- `silver_wasde.avg_farm_price` declares BOTH `unit_col` and
    `unit_overrides`. A re-sort placed AFTER the override sorts on a unit string the SQL never ordered
    by, producing an order that is neither the DESC SQL's nor today's ASC."""

    ROWS = [{"commodity": "corn", "country": "united_states", "period": "2024/25",
             "knowledge_date": "2026-05-12", "value": "4.24", "unit": ""},
            {"commodity": "corn", "country": "united_states", "period": "2025/26",
             "knowledge_date": "2026-05-12", "value": "4.15", "unit": "Million Bushels"}]

    def test_the_wasde_row_order_survives_Q_run_byte_identically(self):
        spec = _series_spec(WASDE, "avg_farm_price", commodity="corn", country="united_states")
        got = Q.run(spec, query_fn=lambda _sql: [dict(r) for r in self.ROWS])
        assert [r["period"] for r in got] == [r["period"] for r in self.ROWS]

    def test_the_override_really_does_CLOBBER_the_unit_it_would_have_sorted_on(self):
        # ANTI-VACUITY for the row above: if the override were inert, "the order survived" would be
        # trivially true and would pin nothing. The two input rows carry DIFFERENT unit cells and both
        # come back stamped with the one per-commodity override.
        assert {r["unit"] for r in self.ROWS} == {"", "Million Bushels"}
        spec = _series_spec(WASDE, "avg_farm_price", commodity="corn", country="united_states")
        got = Q.run(spec, query_fn=lambda _sql: [dict(r) for r in self.ROWS])
        assert {r["unit"] for r in got} == {_units(WASDE, "avg_farm_price")["corn"]} == {"$/bu"}


# ==================================================================================================
# 7. S1's CALLER GRAPH -- the half a compiled flip is worthless without
# ==================================================================================================
# THE DEFECT THIS SECTION EXISTS FOR. Section 6 proves the COMPILER moves when it is told to. It proves
# nothing about whether anything ever tells it. Before this wave the canary was landed at `query.py` and
# at `answer._futures_newest_first_on`, and NO CALLER passed it -- so every assertion in section 6 was
# green while GRAPHRAG_FUTURES_NEWEST_FIRST=on changed not one byte of any served turn. A flag whose
# enable path is a promise is indistinguishable, from the outside, from a flag that is off.
#
# So the pins below are about REACHABILITY, in the two halves the rest of this file uses:
#   * the ON half -- the seam's bool arrives AT `build_sql` through each chain that can compile a futures
#     series (the cascade legs, the J4 tape, the numbers agent, /v1/series);
#   * the OFF half -- every new signature defaults False, so the env var is the rollback rather than a
#     redeploy, and an omitted kwarg compiles the pre-wave string.
#
# THE DELIBERATE GAPS ARE PINNED TOO, because "unflagged by design" and "forgotten" look identical in a
# diff. Each is pinned by the FACT that makes it structural, never by a comment claiming it is.
from types import SimpleNamespace as _SNS  # noqa: E402

from leviathan.graphrag.numbers import cascade as CQ  # noqa: E402

_THREADED: tuple = (
    ("cascade.quantify", CQ.quantify),
    ("cascade.fetch_window", CQ.fetch_window),
    ("cascade._run_one", CQ._run_one),
    ("cascade._tape_read", CQ._tape_read),
    ("cascade._episode_leg_or_nothing", CQ._episode_leg_or_nothing),
    ("cascade._episode_outcome_legs", CQ._episode_outcome_legs),
    ("cascade._price_pair", CQ._price_pair),
    ("cascade._chain_legs", CQ._chain_legs),
    ("agent.answer_numbers", NA.answer_numbers),
    ("agent._esr_aggregate_legs", NA._esr_aggregate_legs),
    ("query.build_sql", Q.build_sql),
    ("query.run", Q.run),
)

_EOD_SPEC_DICT = {"table": EOD, "metric": "settle", "commodity": "corn_cbot", "country": None,
                  "t1": "2011-01-01", "t2": "2011-12-31", "asof": "2026-06-08", "agg": "series",
                  "period": None, "period_type": "date", "node_key": None, "leg": None,
                  "era_idx": None, "my": None}


def _sql_spy(monkeypatch) -> list:
    """Wrap `query.build_sql` and record the canary each compile was ACTUALLY given.

    The spy sits AT THE COMPILER, not at an intermediate signature, deliberately: an intermediate spy
    proves a parameter was accepted, and the failure this section exists to catch is a parameter that is
    accepted and then dropped one frame lower. It delegates to the real compiler so the SQL a caller
    receives is unchanged and a spec that would raise still raises."""
    seen: list = []
    real = Q.build_sql

    def _spy(spec, ts=None, *, db=Q.ATHENA_DB, futures_newest_first=False):
        seen.append(futures_newest_first)
        return real(spec, ts, db=db, futures_newest_first=futures_newest_first)

    monkeypatch.setattr(Q, "build_sql", _spy)
    return seen


def _cascade_node(contract: str = "wheat", ref: str = "export"):
    """The test_cascade.py node shape: an id-based GroundedNode stand-in whose `prior` carries a MAPPED
    silver_ref and whose evidence is dated, which is what `_derive_windows` needs to build era legs."""
    ev = [{"date": d, "source": "usda_gain", "source_key": f"k{i}", "text": "t", "event_date": None}
          for i, d in enumerate(("2010-08-05", "2010-11-20"))]
    return _SNS(contract=contract, id=ref, prior={"silver_ref": ref, "region": "US"}, evidence=ev)


def _cascade_sg(nodes):
    return _SNS(nodes=nodes, trace={}, fired_regimes=[])


class _AgentMsgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.sent.append(kw)
        return self.outer.queue.pop(0)


class _FakeAgentClient:
    """The test_question_shapes fake-client idiom: an INJECTED client takes no provider and no backoff,
    so `answer_numbers` runs its real loop with zero network."""

    def __init__(self, tool_input: dict, text: str = "ok"):
        self.queue = [
            _SNS(content=[_SNS(type="tool_use", name=NA.TOOL_NAME, input=dict(tool_input), id="t1")],
                 stop_reason="tool_use"),
            _SNS(content=[_SNS(type="text", text=text)], stop_reason="end_turn")]
        self.sent: list = []
        self.messages = _AgentMsgs(self)


# A table with no coverage router in front of it, so the lookup ALWAYS reaches the compiler: what these
# tests measure is that the agent THREADS the canary, not which card it happened to be pointed at.
_PLAIN_LOOKUP = {"table": "silver_pink_sheet", "metric": "palm_oil_cpo_usd_t", "agg": "series"}


# -- 7.1 the OFF half: every new signature defaults False, keyword-only ------------------------------
class TestS1ThreadingDefaultsOff:
    def test_every_threaded_signature_defaults_False_and_is_keyword_only(self):
        """The rollback IS the default, so it is pinned as one. Keyword-only matters as much as the
        default: these are long positional signatures (`fetch_window` alone takes ten), and a positional
        bool threaded through them would eventually land in the wrong slot from a caller that never meant
        to enable anything."""
        import inspect
        for name, fn in _THREADED:
            p = inspect.signature(fn).parameters.get("futures_newest_first")
            assert p is not None, f"{name} lost the canary kwarg"
            assert p.default is False, f"{name} defaults ON -- the env var is no longer the rollback"
            assert p.kind is inspect.Parameter.KEYWORD_ONLY, f"{name} takes the canary positionally"

    def test_omitting_the_kwarg_compiles_the_pre_wave_sql_through_a_real_caller(self, monkeypatch):
        """The idiom's whole claim, measured at a CALLER rather than at build_sql: a fetch_window that
        never mentions the canary compiles the byte-identical ASC string."""
        seen = _sql_spy(monkeypatch)
        CQ.fetch_window(lambda _sql: [], table=EOD, metric="settle", commodity="corn_cbot",
                        country=None, t1="2011-01-01", t2="2011-12-31", asof="2026-06-08", agg="series")
        CQ._run_one(lambda _sql: [], dict(_EOD_SPEC_DICT))
        CQ._tape_read(lambda _sql: [], slug="corn_cbot", t1="2021-02-15", t2="2021-08-15",
                      asof="2026-06-08")
        NA.answer_numbers("palm?", asof="2024-07-01", client=_FakeAgentClient(_PLAIN_LOOKUP),
                          query_fn=lambda _sql: [])
        assert seen == [False, False, False, False]


# -- 7.2 the ON half, chain by chain -----------------------------------------------------------------
class TestS1ReachesTheCompiler:
    """Each test drives ONE mapped chain and reads the canary off the compiler at the far end."""

    def test_the_cascade_leg_chain_through_fetch_window(self, monkeypatch):
        seen = _sql_spy(monkeypatch)
        for flag in (False, True):
            CQ.fetch_window(lambda _sql: [], table=EOD, metric="settle", commodity="corn_cbot",
                            country=None, t1="2011-01-01", t2="2011-12-31", asof="2026-06-08",
                            agg="series", futures_newest_first=flag)
        assert seen == [False, True]

    def test_the_cascade_leg_chain_through_run_one(self, monkeypatch):
        # `_run_one` is the frame both pool.map waves call, and it UNPACKS a dict spec -- exactly the
        # shape where a dropped kwarg leaves no trace at the call site.
        seen = _sql_spy(monkeypatch)
        CQ._run_one(lambda _sql: [], dict(_EOD_SPEC_DICT), futures_newest_first=True)
        assert seen == [True]

    def test_the_J4_tape_chain_through_tape_read(self, monkeypatch):
        # The one read in cascade.py that is UNCONDITIONALLY futures: table and agg are both module
        # constants, so `_newest_first_applies` is True the moment the canary is.
        assert CQ._TAPE_TABLE == EOD
        seen = _sql_spy(monkeypatch)
        for flag in (False, True):
            CQ._tape_read(lambda _sql: [], slug="corn_cbot", t1="2021-02-15", t2="2021-08-15",
                          asof="2026-06-08", futures_newest_first=flag)
        assert seen == [False, True]

    def test_quantify_hands_the_canary_to_EVERY_leg_helper(self, monkeypatch):
        """The fan-out frame, and the one worth a dedicated test. `quantify` reaches four read helpers;
        a partial thread here is worse than no thread at all, because the cascade block would then mix
        two read shapes inside a single answer with nothing on the page saying so."""
        got: dict = {}
        for name in ("_run_one", "_price_pair", "_chain_legs", "_episode_leg_or_nothing"):
            def _rec(*_a, _n=name, futures_newest_first=False, **_kw):
                got[_n] = futures_newest_first
                if _n == "_run_one":
                    return {"query": {}, "rows": [], "status": "error"}
                return ([], None, None) if _n == "_chain_legs" else ([], None)
            monkeypatch.setattr(CQ, name, _rec)
        CQ.quantify(_cascade_sg([_cascade_node()]), None, qfn=lambda _sql: [], asof="2011-06-01",
                    near="2010", extra_number_calls=[], price_request={"focus_contract": "wheat"},
                    chain=True, episode_outcomes=True, futures_newest_first=True)
        for helper in ("_run_one", "_price_pair", "_chain_legs", "_episode_leg_or_nothing"):
            assert got.get(helper) is True, f"quantify dropped the canary on the way to {helper}"

    def test_quantify_flag_off_hands_the_same_helper_False(self, monkeypatch):
        got: dict = {}

        def _rec(_qfn, _spec, *, futures_newest_first=False):
            got["_run_one"] = futures_newest_first
            return {"query": {}, "rows": [], "status": "error"}

        monkeypatch.setattr(CQ, "_run_one", _rec)
        CQ.quantify(_cascade_sg([_cascade_node()]), None, qfn=lambda _sql: [], asof="2011-06-01",
                    near="2010", extra_number_calls=[])
        assert got.get("_run_one") is False

    def test_the_episode_leg_carries_it_to_all_THREE_tape_reads(self):
        """All three or none. The lazy EDGE read exists to re-measure the slug's tape edge with the SAME
        shape the deep read used; a canary reaching two of the three would compare a newest-first frame
        against an oldest-first edge and could flip a PENDING verdict on ordering alone."""
        import inspect
        src = inspect.getsource(CQ._episode_outcome_legs)
        assert src.count("_tape_read(") == 3
        assert src.count("futures_newest_first=futures_newest_first") == 3

    def test_the_numbers_agent_chain_through_answer_numbers(self, monkeypatch):
        seen = _sql_spy(monkeypatch)
        for flag in (False, True):
            NA.answer_numbers("palm?", asof="2024-07-01", client=_FakeAgentClient(_PLAIN_LOOKUP),
                              query_fn=lambda _sql: [], futures_newest_first=flag)
        assert seen == [False, True]

    def test_the_esr_aggregate_legs_carry_it_too(self, monkeypatch):
        # The ESR decline-WITH-aggregate branch mints REAL [N] handles through its own Q.run calls, so it
        # is a read site like any other even though agg='sum' can never move under the futures scope.
        seen = _sql_spy(monkeypatch)
        NA._esr_aggregate_legs({"commodity": "corn", "metric": "gross_new_sales_1000mt",
                                "period": "2025"}, "2026-06-08", lambda _sql: [],
                               futures_newest_first=True)
        assert seen and all(s is True for s in seen)


# -- 7.3 the top of each chain: ONE env read, threaded omit-when-off ---------------------------------
class TestS1SeamIsTheOnlyEnvRead:
    """D-FR-10's core claim, kept as a census rather than as a docstring."""

    _BELOW_THE_SEAM = ("leviathan.graphrag.numbers.query", "leviathan.graphrag.numbers.cascade",
                       "leviathan.graphrag.numbers.agent", "leviathan.graphrag.orchestrator",
                       "leviathan.graphrag.server")

    def test_no_module_below_the_seam_names_the_env_var(self):
        import importlib
        import inspect
        for mod in self._BELOW_THE_SEAM:
            src = inspect.getsource(importlib.import_module(mod))
            assert "GRAPHRAG_FUTURES_NEWEST_FIRST" not in src, \
                f"{mod} names the flag itself -- the seam is no longer the ONE env read"

    def test_every_lane_above_the_seam_reaches_it_BY_NAME(self):
        # A rename that orphaned one lane would leave that lane permanently off with nothing red.
        import inspect

        from leviathan.graphrag import answer as AN
        from leviathan.graphrag import orchestrator as ORCH
        from leviathan.graphrag import server as SV
        assert "GRAPHRAG_FUTURES_NEWEST_FIRST" in inspect.getsource(AN._futures_newest_first_on)
        assert inspect.getsource(ORCH).count("_futures_newest_first_on()") == 2   # numbers_only + hybrid
        assert "_futures_newest_first_on()" in inspect.getsource(SV.series_route)

    def test_the_orchestrator_threads_it_OMIT_WHEN_OFF(self, monkeypatch):
        """Mirrors answer.py's `_epo_kw` exactly. Flag off -> the kwarg is ABSENT, not False: that is what
        keeps the off-turn byte-identical AND keeps an injected answer_numbers fake with the pre-wave
        signature valid, which is how most of this estate's numbers fixtures are built."""
        from leviathan.graphrag import orchestrator as ORCH
        seen: list = []

        def _fake(question, asof, **kw):
            seen.append(kw.get("futures_newest_first", "ABSENT"))
            return {"answer": "x", "calls": []}

        monkeypatch.setattr(ORCH.na, "answer_numbers", _fake)
        # D-PQ FIX-1: the ESTATE-WIDE seam now defaults ON, so this futures-scoped pin holds its meaning
        # only with that one explicitly disabled -- otherwise the fold resolves to the estate-wide token
        # and this test would be measuring the other flag. Held here so the coupling is visible.
        monkeypatch.setenv("GRAPHRAG_SERIES_NEWEST_FIRST", "off")
        monkeypatch.delenv("GRAPHRAG_FUTURES_NEWEST_FIRST", raising=False)
        ORCH.run_numbers_only("q", "2026-06-08", query_fn=lambda _sql: [])
        monkeypatch.setenv("GRAPHRAG_FUTURES_NEWEST_FIRST", "on")
        ORCH.run_numbers_only("q", "2026-06-08", query_fn=lambda _sql: [])
        assert seen == ["ABSENT", True]

    def test_the_hybrid_lane_reads_the_seam_on_the_CALLING_thread(self):
        """Not a style point. `_numbers` runs on a worker thread; an env read inside it would let the
        numbers lane and the walk lane disagree about the read shape within one turn, and would make the
        rollback racy against an in-flight turn. Pinned by position: the read is above the closure."""
        import inspect
        src = inspect.getsource(__import__("leviathan.graphrag.orchestrator",
                                           fromlist=["x"]).run_hybrid)
        assert src.index("_futures_newest_first_on()") < src.index("def _numbers()")

    def test_answer_computes_it_ONCE_at_the_quantify_seam(self):
        """The cascade seam, read off SOURCE: the body is behind `_pgnumbers_live()`, so a live-path
        harness here would pin the pg breaker rather than the threading.

        EDITED BY D-AM-18, AND THE MEASUREMENT IS UNCHANGED -- this file's header requires that be said
        out loud. The threaded VALUE is no longer the literal `True`; it is the scope token
        (`answer._newest_first_scope`: False / True futures-scoped / "all" estate-wide), because a second
        flag now widens the same flip to every card. The two properties this test has always pinned are
        the ones re-expressed below and they are strictly stronger, not weaker: the value is computed
        ONCE (one assignment, so a turn cannot disagree with itself) and the kwarg is OMIT-WHEN-OFF (a
        falsy scope sends nothing, so the flag-off call stays byte-identical and an injected `quantify`
        fake with the pre-wave signature stays valid). The literal-`True` form could not survive the
        widening: with only the estate-wide flag on, keying the omit on `_futures_newest_first_on()`
        would have dropped the kwarg and left the new flag dead on this lane -- the exact D-FR-10 defect
        section 7 exists to catch."""
        import inspect
        import re

        from leviathan.graphrag import answer as AN
        src = inspect.getsource(AN)
        assert re.search(r'_nf_scope\s*=\s*_newest_first_scope\(\s*_futures_newest_first_on\(\)\s*,\s*'
                         r'_series_newest_first_on\(\)\s*\)', src), \
            "answer no longer folds the two seams into ONE scope value at the quantify seam"
        assert re.search(r'_fnf_kw\s*=\s*\{"futures_newest_first":\s*_nf_scope\}\s*'
                         r'if\s*_nf_scope\s*else\s*\{\}', src), \
            "answer no longer threads the canary once, omit-when-off, at the quantify seam"
        # The DEFINITION plus exactly ONE call site. A second call site inside this file would be a second
        # env read per turn, and two reads can disagree -- which is the whole reason the flag has a seam.
        assert src.count("_futures_newest_first_on()") == 2, \
            "answer gained (or lost) a seam call site -- expected the def plus exactly one read"
        assert "**_fnf_kw" in src, "the computed kwarg never reaches cq.quantify"


# -- 7.4 the DELIBERATE gaps, pinned so they stay decisions ------------------------------------------
class TestS1UnflaggedByDesign:
    """Three CONSTANT-TABLE read sites and two offline tools are NOT threaded. Every omission is pinned by
    the fact that makes it structural, so the day that fact changes this reds instead of going quietly
    wrong. `silverleg._rows` is on this list and was NOT on the wave's mapped-sites list -- it is the only
    serving `Q.run` outside agent/cascade/server, so an audit would flag it first and should find it
    classified here rather than unexplained."""

    # (site, the tables its callers can actually pass). Every one is a LITERAL at the call site.
    _CONSTANT_TABLE_SITES = {
        "cascade._psd_component_rows": ("silver_psd",),
        "cascade._cot_outcome_read": ("gold_cot_outcomes",),
        "silverleg._rows": ("silver_psd", "silver_fred_fx", "silver_noaa_oni"),
    }

    def test_the_constant_table_read_sites_cannot_compile_a_futures_series(self):
        """`_newest_first_applies` keys on `contract_month_col`. None of the cards these sites can reach
        declares one, so a threaded canary could not move one byte of their SQL. If any of them grows a
        delivery-month axis, thread it."""
        reg = R.load_registry()
        checked = 0
        for site, tables in sorted(self._CONSTANT_TABLE_SITES.items()):
            for table in tables:
                ts = reg.get(table) if table in reg.tables else None
                if ts is None:
                    continue          # gold_cot_outcomes is unregistered until the builder wave lands
                checked += 1
                assert getattr(ts, "contract_month_col", None) is None, \
                    f"{table} now carries a delivery-month axis -- thread the canary to {site}"
        assert checked >= 3, "the constant-table cards did not resolve -- the pin measured nothing"

    def test_silverleg_really_does_only_read_those_three_tables(self):
        """ANTI-VACUITY for silverleg's entry above. `_rows` takes `table` as a PARAMETER, so the pin is
        only true while every caller passes one of the three literals. A fourth caller handing it a
        futures card would make the pin above vacuously green while the site silently needed the kwarg."""
        import inspect
        import re

        from leviathan.graphrag import silverleg as SL
        src = inspect.getsource(SL)
        passed = set(re.findall(r'_rows\(query_fn,\s*"([a-z_]+)"', src))
        assert passed == set(self._CONSTANT_TABLE_SITES["silverleg._rows"]), passed
        # ...and it really is a single read site, so the census above covers the whole module.
        assert src.count("Q.run(") == 1

    def test_those_are_the_only_unthreaded_fetch_window_callers(self):
        """ANTI-VACUITY for the pin above: it is a complete statement of the gap only while no OTHER
        caller quietly joins it. Every `fetch_window(` call site either passes the canary or is one of
        the two named constant-table reads."""
        import inspect
        src = inspect.getsource(CQ)
        calls = src.count("fetch_window(qfn,") - 1        # minus the `def fetch_window(qfn, *, ...)` line
        assert calls == 3, f"a new fetch_window call site appeared ({calls} now) -- classify it"
        # ...and the two that skip the canary are exactly the two constant-table reads named above.
        assert 'table="silver_psd"' in src and "table=COT_OUTCOME_TABLE" in src

    def test_the_serving_Q_run_census_is_complete(self):
        """THE PIN THAT WOULD HAVE CAUGHT silverleg. Every `Q.run(` in the serving tree is either threaded
        or on the classified list -- counted from SOURCE, so a new read site anywhere reds this until
        someone decides which it is. That is the whole difference between 'unflagged' and 'forgotten'."""
        import inspect

        from leviathan.graphrag import server as SV
        from leviathan.graphrag import silverleg as SL
        threaded, unthreaded = [], []
        for name, mod in (("agent", NA), ("cascade", CQ), ("server", SV), ("silverleg", SL)):
            src = inspect.getsource(mod)
            i = 0
            while (i := src.find("Q.run(", i)) != -1:
                # Balanced-paren scan to the end of the CALL, so a wrapped argument list is read whole --
                # a line-based census would misread agent.py's wrapped legacy-level read as unthreaded.
                j, depth = i + len("Q.run("), 1
                while j < len(src) and depth:
                    depth += (src[j] == "(") - (src[j] == ")")
                    j += 1
                (threaded if "futures_newest_first" in src[i:j] else unthreaded).append(name)
                i = j
        assert sorted(threaded) == ["agent", "agent", "agent", "cascade", "cascade", "server"], threaded
        assert unthreaded == ["silverleg"], (f"an UNCLASSIFIED serving Q.run site exists ({unthreaded}) "
                                             f"-- thread it, or classify it in 7.4 as silverleg is")

    def test_the_raw_build_sql_tools_stay_unflagged_and_the_contract_says_why(self):
        """numbers_parity / cascade_census compile with `build_sql` and execute the raw string
        themselves, so they never reach `run()`'s re-sort. Flagging either without also calling
        `resort_rows_chronological` would measure the un-re-sorted DESC surface -- which is why the
        obligation is written into the re-sorter's own docstring rather than into a plan."""
        doc = Q.resort_rows_chronological.__doc__ or ""
        assert "numbers_parity" in doc and "cascade_census" in doc


# -- 7.5 U3's trace key: the COUPLING half ----------------------------------------------------------
class TestU3TraceKeyReachesTheWhitelists:
    """6.1's U3 row. The per-turn behaviour (PRESENT with the two units on a mismatch, ABSENT on a
    matched-unit turn) is pinned in test_numbers_stats.py against the live guard. What belongs HERE is
    the coupling: the key reaches an artifact only because three fixed tuples in orchestrator.py name it,
    and those tuples live in a file this lane does not own -- the exact shape of the C2 defect one wave
    earlier, where a record was written to a dict nobody read."""

    def test_all_three_orchestrator_whitelists_carry_the_key(self):
        import inspect

        from leviathan.graphrag import orchestrator as ORCH
        src = inspect.getsource(ORCH)
        assert src.count('"unit_mismatch_guard"') == 3, \
            "an orchestrator whitelist dropped U3's key -- the guard is dark in every artifact again"

    def test_the_key_is_the_one_the_agent_actually_stamps(self):
        # A whitelist naming a key the engine never writes measures nothing at all.
        assert NA.UNIT_MISMATCH_TRACE_KEY == "unit_mismatch_guard"
