"""PRICE_AND_PLAYBOOKS W3 -- the JUDGED CURVE DECK and its three new eval pins (plan item 23, :1014,
gates :1040-1050). Pure/hermetic: no AWS, no LLM, no pg, no eval run.

W3 changes PROSE, so the wave needs a judged deck. A deck is only worth running if two things are true
before it costs a dollar, and both are testable offline:

  * every ROW IS REALIZABLE -- its coverage verdict is what the MEASURED floors
    (futures_eod_contracts.PRICE_COVERAGE_START, min(trade_date) per slug over the canonical bytes) say
    it is, not what the deck author hoped. The pre-coverage row is pre-coverage, the uncovered venue has
    no floor at all, and the served rows sit entirely inside coverage;
  * every PIN IS SPELLED CORRECTLY -- eval._cascade_asserts silently IGNORES an expect key it does not
    recognise (`keys = [k for k in _CASCADE_EXPECT if k in exp]`), so a typo does not fail the row, it
    DELETES the assertion. A deck can be green and testing nothing.

The rest pins the pins themselves: what curve_cited / expiry_labeled / settle_kind_stated /
futures_coverage_route actually assert, in both directions, including the two failure classes the wave
exists to refuse (an expiry label invented for a cash index that has none, and an ICE session close
narrated as an official exchange settlement).

EXTENDED 2026-08-04 (FUTURES_READPATH D-FR-13, plan 6.2 run B): the deck grew from twelve rows to
fifteen with the U1 unit-compatibility block. The realizability rule is inherited, not forked -- a
unit-guard row's REALIZABILITY is the pair of unit strings the LIVE registry actually serves for its two
legs, so `TestUnitGuardRowsRealizable` reads `unit_overrides` off the cards and asserts through
`stats.unit_compatible` itself. A row that claims to probe a mismatch the config does not produce is the
same failure class as a pre-coverage row that turns out to be covered: green, and testing nothing.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import yaml as _yaml

from leviathan.graphrag import config_check as CC
from leviathan.graphrag import eval as EV
from leviathan.graphrag.numbers import stats as ST
from leviathan.silver import futures_eod_contracts as FC

_REPO = Path(__file__).resolve().parents[2]
_DECK = _REPO / "configs" / "graphrag" / "eval_queries_curve12.yaml"
EOD = "silver_futures_eod"
FLAT = "silver_futures_prices"


def _deck() -> list[dict]:
    return _yaml.safe_load(_DECK.read_text(encoding="utf-8"))["queries"]


def _rows() -> dict[str, dict]:
    return {r["id"]: r for r in _deck()}


# ── synthetic turn builders (the two lanes' out-dict shapes) ──────────────────────────────────────────
def _eod_row(month: str | None, value: str, kind: str = "settlement",
             unit: str = "US cents/bushel") -> dict:
    return {"value": value, "unit": unit, "contract_month": month or "", "settle_kind": kind,
            "currency": "USD", "data_date": "2026-06-05"}


def _cit(table: str, rows: list[dict], idx: int = 1) -> dict:
    val = rows[0]["value"] if rows else None
    return {"id": f"N{idx}", "kind": "number", "label": "x", "source": "FUTURES EOD",
            "value": val, "unit": (rows[0]["unit"] if rows else None),
            "locator": {"kind": "number", "table": table, "metric": "settle"},
            "payload": {"query": {"table": table, "metric": "settle"}, "rows": rows[:3]}}


def _out(rows: list[dict], prose: str, *, table: str = EOD, lane: str = "numbers",
         route: str | None = None, full_rows: list[dict] | None = None) -> dict:
    """A turn as the eval scorer sees it. lane='hybrid' renders STRUCTURED prose and carries NO
    number_calls -- the answer.answer()-direct shape, where the citation payload's rows[:3] slice is the
    only row surface; lane='numbers' carries structured=None plus the full call list. (A --via-orchestrator
    hybrid turn is the union of the two: structured prose AND number_calls, run_hybrid:296.)"""
    cits = [_cit(table, rows)] if rows else []
    out: dict = {"citations": cits, "trace": {}}
    if route:
        out["trace"]["futures_coverage_guard"] = route
    if lane == "hybrid":
        out["structured"] = {"tldr": prose, "mechanism": ""}
        out["answer"] = prose + "\n\n## Sources\n[N1] FUTURES EOD settle corn_cbot = 446 US cents/bushel"
    else:
        out["structured"] = None
        out["answer"] = prose + "\n\n## Sources\n[N1] FUTURES EOD settle corn_cbot = 446 US cents/bushel"
        out["number_calls"] = [{"query": {"table": table, "metric": "settle"},
                                "rows": (full_rows if full_rows is not None else rows), "status": "ok"}]
    return out


def _assert(expect: dict, out: dict, asof: str = "2026-06-08") -> dict:
    return EV._cascade_asserts({"expect": expect, "asof": asof}, out)


# ── 1. the deck: shape, realizability, and the typo fence ─────────────────────────────────────────────
class TestDeckShape:
    def test_fifteen_rows_unique_ids_and_the_newcap30_row_shape(self):
        # 12 W3 rows + the 3 U1 unit-compatibility rows (D-FR-13 run B). The count is asserted, not
        # inferred: the wave's own precondition census (plan 6.1) reads a PIN COUNT off this file and
        # treats an unexplained move as evidence that a deck shifted underneath the analysis, so the
        # deck's size has to be a pinned fact somewhere.
        rows = _deck()
        assert len(rows) == 15
        ids = [r["id"] for r in rows]
        assert len(set(ids)) == 15
        for r in rows:
            assert set(("id", "contract", "category", "expected_intent", "asof", "question", "expect")) <= set(r)
            assert r["expected_intent"] in ("numbers_only", "hybrid")
            dt.date.fromisoformat(r["asof"])                     # a real ISO as-of, not a year or a label
            assert len(r["question"].strip()) > 20      # a real desk ask (imperatives allowed: "Give me ...")
            assert r["expect"], "a row with no expect is a judged-only row -- not in this deck"

    def test_every_expect_key_is_a_REAL_pin(self):
        # eval._cascade_asserts intersects with _CASCADE_EXPECT, so an unrecognised key is DROPPED
        # silently: the row still passes, having asserted nothing. This is that fence.
        for r in _deck():
            unknown = sorted(set(r["expect"]) - set(EV._CASCADE_EXPECT))
            assert not unknown, f"{r['id']} pins non-existent key(s) {unknown}"

    def test_the_plan_named_pins_are_all_present_somewhere(self):
        pinned = set()
        for r in _deck():
            pinned |= set(r["expect"])
        for k in ("curve_cited", "expiry_labeled", "settle_kind_stated", "banned_valuation"):
            assert k in pinned, f"gate :1046 names {k} and the deck never pins it"

    def test_strip_count_has_a_denominator(self):
        # STRIP COUNT is the wave's primary metric and the verifier panel is built only from turns
        # carrying trace.citation_verifier -- i.e. the STRUCTURED lane. An all-numbers_only deck would
        # score the primary gate against an empty panel.
        hybrid = [r["id"] for r in _deck() if r["expected_intent"] == "hybrid"]
        assert len(hybrid) >= 4, f"only {len(hybrid)} structured turns -- strip rate would be noise"
        # D-FR-13 / 6.2, non-optional: "any rows added must include hybrid ones as the denominator".
        # A unit-mismatch row is naturally numbers_only, so a U1 block added entirely on that lane would
        # have grown the deck by 25% while contributing NOTHING to the metric the wave is judged on.
        assert any(r["expected_intent"] == "hybrid" for r in _deck()
                   if r["category"] == "futures_unit_guard"), (
            "the U1 block is all numbers_only -- it adds rows to the deck and nothing to the strip panel")

    def test_coverage_negatives_and_cash_refs_are_all_represented(self):
        rows = _rows()
        assert rows["legacy_kcbt_pre2014"]["expect"]["futures_coverage_route"] == "legacy"
        assert rows["straddle_corn_2009_2010"]["expect"]["futures_coverage_route"] == "straddle"
        assert rows["uncovered_matif_wheat"]["expect"]["futures_coverage_route"] == "uncovered"
        for rid in ("cepea_arabica_cash_curve", "cepea_campinas_cash_curve"):
            assert rows[rid]["expect"]["curve_cited"] is False       # a cash index has no delivery month
            assert rows[rid]["expect"]["expiry_labeled"] is False    # and none may be invented for it

    def test_every_row_pins_the_coverage_route(self):
        # Pin coverage was UNEVEN: six of twelve rows carried no route pin at all, so a row that silently
        # routed 'legacy' or 'uncovered' instead of serving would have passed the deterministic layer
        # entirely. The pin is free -- both lanes already stamp trace.futures_coverage_guard -- and
        # 'absent' is the affirmative form for a served row.
        missing = [r["id"] for r in _deck() if "futures_coverage_route" not in r["expect"]]
        assert not missing, f"rows with no coverage-route pin: {missing}"

    def test_the_hard_decline_rows_forbid_a_price_citation(self):
        # A row that declines the curve and then quotes an UNRELATED served price (a pink_sheet or
        # continuous-card level) satisfied every other pin on these two rows. price_cited:false is the
        # deterministic tooth that catches it.
        rows = _rows()
        for rid in ("straddle_corn_2009_2010", "uncovered_matif_wheat"):
            assert rows[rid]["expect"]["price_cited"] is False

    def test_no_hybrid_row_pins_a_verifier_only_the_numbers_lane_stamps(self):
        # numbers_mismatched reads trace.numbers_verifier, which ONLY run_numbers_only stamps
        # (orchestrator.py:84); eval.py treats an absent verifier as 0. Pinned on a hybrid row it is a
        # GUARANTEED PASS -- a pin that cannot fail, reading as coverage it does not provide.
        offenders = [r["id"] for r in _deck()
                     if r["expected_intent"] == "hybrid" and "numbers_mismatched" in r["expect"]]
        assert not offenders, (
            f"{offenders} pin numbers_mismatched on the hybrid lane, where trace.numbers_verifier is "
            f"never stamped -- the pin is vacuous")


class TestDeckRealizable:
    """Every row is checked against the MEASURED floors, not against prose. This is the check that would
    have caught the plan's blanket GLBX floor: hard_red_winter_wheat_kcbt begins 2014-01-02, three and a
    half years after its GLBX siblings, so a 2012 as-of is pre-coverage and a blanket floor would have
    scored the row as servable."""

    def test_pre_coverage_row_really_is_pre_coverage(self):
        row = _rows()["legacy_kcbt_pre2014"]
        floor = FC.coverage_start_for(row["contract"])
        assert floor == dt.date(2014, 1, 2)
        asof = dt.date.fromisoformat(row["asof"])
        assert asof < floor
        assert FC.covers(row["contract"], asof, asof) == "legacy"
        # 'legacy' rather than 'uncovered' only because the retiring continuous card serves this slug --
        # it is one of its 12 unit_overrides. That is what makes price_cited:true realizable here.
        assert row["expect"]["price_cited"] is True

    def test_straddle_row_window_really_crosses_the_floor(self):
        row = _rows()["straddle_corn_2009_2010"]
        floor = FC.coverage_start_for(row["contract"])
        assert floor == dt.date(2010, 6, 6)
        lo, hi = dt.date(2009, 12, 31), dt.date.fromisoformat(row["asof"])
        assert lo < floor <= hi
        assert FC.covers(row["contract"], lo, hi) == "straddle"
        assert FC.covers(row["contract"], lo, lo) == "legacy"        # the halves route differently, which
        assert FC.covers(row["contract"], hi, hi) == "serve"         # is exactly why the join is refused

    def test_uncovered_row_has_no_floor_at_all(self):
        row = _rows()["uncovered_matif_wheat"]
        assert row["contract"] not in FC.PRICE_COVERAGE_START
        with pytest.raises(ValueError):
            FC.coverage_start_for(row["contract"])                   # fail-closed, never a permissive default

    def test_every_served_row_sits_entirely_inside_its_slugs_coverage(self):
        for r in _deck():
            if r["expect"].get("futures_coverage_route") in ("legacy", "straddle", "uncovered"):
                continue
            asof = dt.date.fromisoformat(r["asof"])
            assert FC.covers(r["contract"], asof, asof) == "serve", f"{r['id']} is not servable"

    def test_the_two_cash_refs_are_covered_but_have_no_expiry_to_serve(self):
        # Covered slugs (so NOT a coverage decline) whose contract_month is NULL by construction -- the
        # distinction the deck's two CEPEA rows exist to keep apart.
        for rid in ("cepea_arabica_cash_curve", "cepea_campinas_cash_curve"):
            row = _rows()[rid]
            asof = dt.date.fromisoformat(row["asof"])
            assert FC.covers(row["contract"], asof, asof) == "serve"
            assert row["expect"].get("futures_coverage_route") == "absent"   # covered -> nothing routed


def _card_units(table: str, metric: str) -> dict:
    """The LIVE per-commodity unit vocabulary a card actually serves, read RAW out of tables.yaml -- the
    same discipline test_futures_eod_curve.py uses. These strings ARE the deck rows' realizability: a
    unit-guard row is only probing a mismatch if the registry still spells the two legs differently."""
    return dict(CC._load("numbers/tables.yaml")["tables"][table]["metrics"][metric]["unit_overrides"])


class TestUnitGuardRowsRealizable:
    """The U1 block (D-FR-13 run B) gets the same treatment the coverage rows get: its premise is checked
    against the LIVE config, not against the plan's prose. The premise here is a UNIT PAIR, and the oracle
    is `stats.unit_compatible` itself -- not a re-implementation of the three-state rule, which would let
    the deck and the guard drift apart and still agree with each other."""

    IDS = ("unit_cross_card_corn_board_vs_farm", "unit_false_decline_cotton_cents",
           "unit_matched_dec26_corn_own_history")

    def test_the_block_is_present_and_categorised(self):
        rows = _rows()
        for rid in self.IDS:
            assert rows[rid]["category"] == "futures_unit_guard"

    def test_the_genuine_mismatch_row_really_is_a_mismatch(self):
        # corn: the WASDE farm price is DOLLARS per bushel and the board is CENTS per bushel -- a real
        # factor of 100. This is the audit's defect, and if the registry ever normalizes these two the
        # row stops probing anything and must be re-authored rather than left green.
        wasde, eod = _card_units("silver_wasde", "avg_farm_price"), _card_units("silver_futures_eod", "settle")
        a, b = wasde["corn"], eod["corn_cbot"]
        assert (a, b) == ("$/bu", "US cents/bushel")
        assert ST.unit_compatible(a, b) is False

    def test_the_false_decline_row_really_is_the_ratified_FALSE_one(self):
        # cotton: both legs are cents per pound. The guard refuses it anyway (strip+casefold and nothing
        # else), and D-FR-16(a) ratified ACCEPTING that cost this wave. The row is pinned as a decline
        # DELIBERATELY -- so the day the card vocabulary is normalized under a lint, this assertion is
        # the thing that goes red and forces the deck comment to be rewritten instead of the row
        # silently flipping meaning.
        wasde, eod = _card_units("silver_wasde", "avg_farm_price"), _card_units("silver_futures_eod", "settle")
        a, b = wasde["cotton"], eod["cotton"]
        assert (a, b) == ("c/lb", "US cents/lb")
        assert "lb" in a and "lb" in b, "the pair is no longer dimensionally identical -- re-author the row"
        assert ST.unit_compatible(a, b) is False

    def test_the_anti_vacuity_row_really_does_compute(self):
        # Both handles come off ONE card and ONE slug, so the known==known branch must stay COMPATIBLE.
        # Without this the other two rows cannot distinguish a working guard from a broken percentile.
        eod = _card_units("silver_futures_eod", "settle")
        assert ST.unit_compatible(eod["corn_cbot"], eod["corn_cbot"]) is True

    def test_the_lanes_are_assigned_so_no_pin_is_vacuous(self):
        # numbers_mismatched reads trace.numbers_verifier, stamped by run_numbers_only ONLY. The two
        # REFUSAL rows carry it and are numbers_only (the turn returns rows, so _verify_numbers_answer
        # does not short-circuit and the counter is live); the COMPUTE row is the hybrid strip-count
        # denominator and does not carry it.
        rows = _rows()
        for rid in ("unit_cross_card_corn_board_vs_farm", "unit_false_decline_cotton_cents"):
            assert rows[rid]["expected_intent"] == "numbers_only"
            assert rows[rid]["expect"]["numbers_mismatched"] == 0
        compute = rows["unit_matched_dec26_corn_own_history"]
        assert compute["expected_intent"] == "hybrid"
        assert "numbers_mismatched" not in compute["expect"]
        assert compute["expect"]["curve_cited"] is False    # single-expiry: the S4 twin this row carries

    def test_every_unit_guard_row_is_inside_coverage(self):
        # None of the three is a coverage probe: a coverage decline returns zero rows, which the guard
        # refuses for EMPTINESS (a different reason, checked first) -- so a U1 row that accidentally sat
        # outside coverage would be measuring the wrong refusal entirely.
        rows = _rows()
        for rid in self.IDS:
            r = rows[rid]
            asof = dt.date.fromisoformat(r["asof"])
            assert FC.covers(r["contract"], asof, asof) == "serve"
            assert r["expect"]["futures_coverage_route"] == "absent"


# ── 2. curve_cited ────────────────────────────────────────────────────────────────────────────────────
class TestCurveCited:
    def test_two_distinct_expiries_is_a_curve(self):
        rows = [_eod_row("2026-07", "417.5"), _eod_row("2026-09", "427.0"), _eod_row("2026-12", "446.0")]
        assert _assert({"curve_cited": True}, _out(rows, "July 2026 corn settled at 417.5."))["curve_cited"]

    def test_one_expiry_across_three_dates_is_NOT_a_curve(self):
        rows = [_eod_row("2026-12", "444.0"), _eod_row("2026-12", "445.0"), _eod_row("2026-12", "446.0")]
        assert _assert({"curve_cited": False}, _out(rows, "December 2026 corn."))["curve_cited"]

    def test_a_declined_turn_serves_no_curve(self):
        assert _assert({"curve_cited": False}, _out([], "There is no per-delivery-month record here.",
                                                    route="uncovered"))["curve_cited"]

    def test_null_month_cash_index_rows_are_not_a_curve(self):
        rows = [_eod_row(None, "1433.64", kind="cash_index", unit="BRL/60-kg bag"),
                _eod_row(None, "1425.10", kind="cash_index", unit="BRL/60-kg bag")]
        assert _assert({"curve_cited": False}, _out(rows, "A cash index."))["curve_cited"]

    def test_the_3_row_payload_slice_still_sees_a_curve(self):
        # answer.answer() returns citations only and the payload keeps rows[:3]; _total_order puts
        # data_date first and contract_month ahead of unit, so those three rows are three EXPIRIES.
        full = [_eod_row(m, "1.0") for m in ("2026-07", "2026-09", "2026-12", "2027-03", "2027-05")]
        out = _out(full, "July 2026 corn and December 2026 corn.", lane="hybrid")
        assert "number_calls" not in out
        assert _assert({"curve_cited": True}, out)["curve_cited"]


# ── 3. expiry_labeled ─────────────────────────────────────────────────────────────────────────────────
class TestExpiryLabeled:
    ROWS = [_eod_row("2026-07", "417.5"), _eod_row("2026-12", "446.0")]

    @pytest.mark.parametrize("prose", [
        "The December 2026 corn contract settled at 446.0 US cents/bushel.",
        "Dec-26 settled at 446.0, against 417.5 for the nearby.",
        "The 2026-12 delivery month settled at 446.0.",
        "The December contract settled at 446.0 while July settled at 417.5.",
    ])
    def test_naming_the_served_expiry_passes(self, prose):
        assert _assert({"expiry_labeled": True}, _out(self.ROWS, prose))["expiry_labeled"]

    def test_a_bare_level_with_no_expiry_fails(self):
        # the card's "never quote a bare level as 'the price'": nearest-listed is a tie-break, not front month
        got = _assert({"expiry_labeled": True}, _out(self.ROWS, "Corn settled at 446.0 US cents/bushel."))
        assert got["expiry_labeled"] is False

    def test_an_expiry_that_was_never_served_is_an_invention(self):
        got = _assert({"expiry_labeled": True},
                      _out(self.ROWS, "Mar-27 settled at 461.5, and December 2026 at 446.0."))
        assert got["expiry_labeled"] is False

    def test_payload_truncation_does_not_convict_a_correct_answer(self):
        # With only the citation payload to read (an answer.answer()-direct turn), a five-expiry curve
        # arrives with two of its months INVISIBLE to the scorer. Naming one of them is correct behaviour,
        # not invention -- the invention half stands down exactly here, the positive half does not.
        full = [_eod_row(m, "1.0") for m in ("2026-07", "2026-09", "2026-12", "2027-03", "2027-05")]
        out = _out(full, "July 2026 corn settled at 417.5 and May-27 at 470.75.", lane="hybrid")
        assert EV._eod_rows_truncated(out) is True
        assert _assert({"expiry_labeled": True}, out)["expiry_labeled"]

    def test_a_requested_month_that_returned_no_row_is_not_an_invention(self):
        out = _out(self.ROWS, "December 2026 settled at 446.0; nothing came back for Mar-27.")
        out["number_calls"][0]["query"]["contract_month"] = "2026-07,2026-12,2027-03"
        assert _assert({"expiry_labeled": True}, out)["expiry_labeled"]

    def test_false_branch_is_clean_when_no_month_is_labelled(self):
        out = _out([], "The figure is from the roll-spliced continuous series; a per-contract curve does "
                       "not exist before 2014-01-02. On 29 June 2012 it closed at 738.50 US cents/bushel.",
                   table=FLAT, route="legacy")
        assert _assert({"expiry_labeled": False}, out)["expiry_labeled"]

    def test_false_branch_catches_a_month_invented_for_a_cash_index(self):
        rows = [_eod_row(None, "1433.64", kind="cash_index", unit="BRL/60-kg bag")]
        out = _out(rows, "The Jul-26 contract is quoted at 1433.64 BRL per 60-kg bag.")
        assert _assert({"expiry_labeled": False}, out)["expiry_labeled"] is False

    def test_a_calendar_date_is_not_an_expiry_label(self):
        # 'in June 2012 the continuous close was 738.50' dates a sentence; it does not label an expiry.
        # The adjacency rule is what keeps the two apart -- see _expiry_tokens for the limit this admits.
        hard, bare, _soft = EV._expiry_tokens("In June 2012 the continuous close was 738.50, and between "
                                              "December 2009 and December 2010 the series ran 414.50 to 629.00.")
        assert not hard and not bare

    def test_iso_month_scanner_does_not_fire_inside_a_full_date(self):
        hard, _b, _s = EV._expiry_tokens("a per-contract curve does not exist before 2014-01-02")
        assert not hard

    def test_the_modal_verb_may_is_not_a_delivery_month(self):
        # 'prices may close higher' would otherwise register a May contract and red every `false` row
        # whose answer used the modal. A YEAR beside it removes the ambiguity, so May survives there.
        hard, bare, soft = EV._expiry_tokens("Prices may close higher, and the board may settle wider.")
        assert not hard and not bare and not soft
        _h, _b, soft2 = EV._expiry_tokens("May 2027 corn settled at 470.75.")
        assert soft2 == {"2027-05"}

    def test_four_digit_ticker_form_is_still_a_hard_label(self):
        hard, _b, _s = EV._expiry_tokens("Dec-2026 is the reference expiry.")
        assert hard == {"2026-12"}


# ── 4. settle_kind_stated ─────────────────────────────────────────────────────────────────────────────
class TestSettleKindStated:
    def test_a_glbx_settlement_narrated_as_a_settlement(self):
        rows = [_eod_row("2026-12", "446.0")]
        out = _out(rows, "December 2026 corn settled at 446.0 US cents/bushel (exchange settlement).")
        assert _assert({"settle_kind_stated": True}, out)["settle_kind_stated"]

    def test_an_ice_close_narrated_as_a_session_close(self):
        rows = [_eod_row("2026-07", "3744", kind="close", unit="USD/metric ton")]
        out = _out(rows, "The July 2026 cocoa session close was 3744 USD per metric ton.")
        assert _assert({"settle_kind_stated": True}, out)["settle_kind_stated"]

    def test_an_ice_close_called_an_official_settlement_FAILS(self):
        # the card, verbatim: never call an ICE number an official settlement (the `statistics` settlement
        # schema was deliberately not purchased -- these are ohlcv-1d session closes).
        rows = [_eod_row("2026-07", "3744", kind="close", unit="USD/metric ton")]
        out = _out(rows, "The July 2026 official settlement was 3744 USD per metric ton, the session close.")
        assert _assert({"settle_kind_stated": True}, out)["settle_kind_stated"] is False

    def test_a_cash_index_narrated_as_a_cash_index(self):
        rows = [_eod_row(None, "1433.64", kind="cash_index", unit="BRL/60-kg bag")]
        out = _out(rows, "CEPEA publishes a cash index, not a futures curve: 1433.64 BRL per 60-kg bag.")
        assert _assert({"settle_kind_stated": True}, out)["settle_kind_stated"]

    def test_nothing_served_cannot_state_a_kind(self):
        assert _assert({"settle_kind_stated": False}, _out([], "Declined.", route="uncovered"))["settle_kind_stated"]

    # -- the mislabel test is a CLAIM test, not a keyword scan (fold 2026-07-31) ------------------------
    # ice_cocoa_settlement_trap ASKS for "the official settlement price", so the most correct possible
    # answer must SAY the words in order to deny them. The bare keyword scan RED-ed exactly that answer
    # and passed the evasive one that never says them: the row rewarded evasion and punished the honest
    # denial, on the deck's designated provenance trap.
    @pytest.mark.parametrize("prose", [
        "There is no official settlement series for ICE cocoa in this data; what it carries is the "
        "ohlcv-1d session close, and July 2026 closed at 3744 USD per metric ton.",
        "This is not an official exchange settlement, it is a session close: July 2026 at 3744 USD per "
        "metric ton.",
        "The ICE settlement schema was never purchased, so there is no official settlement here -- the "
        "July 2026 session close was 3744 USD per metric ton.",
    ])
    def test_the_HONEST_DENIAL_of_an_official_settlement_passes(self, prose):
        rows = [_eod_row("2026-07", "3744", kind="close", unit="USD/metric ton")]
        assert _assert({"settle_kind_stated": True}, _out(rows, prose))["settle_kind_stated"]

    def test_a_denial_in_one_sentence_does_not_excuse_a_claim_in_another(self):
        # sentence-scoped, so an answer that denies and then asserts is still convicted.
        rows = [_eod_row("2026-07", "3744", kind="close", unit="USD/metric ton")]
        prose = ("There is no official settlement series here. The official settlement was 3744 USD per "
                 "metric ton, the session close.")
        assert _assert({"settle_kind_stated": True}, _out(rows, prose))["settle_kind_stated"] is False

    # -- the cash_index vocabulary must not require the settle_kind token verbatim ----------------------
    # CEPEA's own published name for the series is the *Indicador*; both CEPEA deck rows pin
    # settle_kind_stated:true, so a five-phrase list made two of twelve rows ride on the model echoing
    # 'cash index' literally while a correct 'indicator' / 'spot reference' rendering RED-ed.
    @pytest.mark.parametrize("prose", [
        "The CEPEA arabica indicator stood at 1433.64 BRL per 60-kg bag -- a physical-market benchmark, "
        "not a futures contract, so it has no delivery month.",
        "CEPEA publishes a daily spot reference rather than a listed contract: 1433.64 BRL per 60-kg bag, "
        "a physical quotation.",
        "This is a cash index: 1433.64 BRL per 60-kg bag.",
    ])
    def test_the_cash_index_kind_is_stated_in_the_desks_own_words(self, prose):
        rows = [_eod_row(None, "1433.64", kind="cash_index", unit="BRL/60-kg bag")]
        assert _assert({"settle_kind_stated": True}, _out(rows, prose))["settle_kind_stated"]

    def test_the_widened_cash_index_vocabulary_still_excludes_futures_words(self):
        # the ONLY separation this pin needs: nothing in the cash_index set may match futures prose.
        import re as _re
        futures_prose = "The December 2026 contract settled at 446.0; the exchange settlement stands."
        assert not any(_re.search(p, futures_prose, _re.I)
                       for p in EV._SETTLE_KIND_PHRASES["cash_index"])


# ── 5. futures_coverage_route + the price-table whitelist ─────────────────────────────────────────────
class TestCoverageRoutePin:
    def test_equality_list_and_absent(self):
        out = _out([], "declined", route="straddle")
        assert _assert({"futures_coverage_route": "straddle"}, out)["futures_coverage_route"]
        assert _assert({"futures_coverage_route": ["straddle", "uncovered"]}, out)["futures_coverage_route"]
        assert _assert({"futures_coverage_route": "legacy"}, out)["futures_coverage_route"] is False
        served = _out([_eod_row("2026-12", "446.0")], "December 2026 corn settled at 446.0.")
        assert _assert({"futures_coverage_route": "absent"}, served)["futures_coverage_route"]
        assert _assert({"futures_coverage_route": "straddle"}, served)["futures_coverage_route"] is False

    def test_eod_citations_now_satisfy_price_cited_and_unit_present(self):
        # the SEAM-C precedent: a price table with GOVERNED units joins the filter set the day it serves.
        out = _out([_eod_row("2026-12", "446.0")], "December 2026 corn settled at 446.0.")
        got = _assert({"price_cited": True, "unit_present": True}, out)
        assert got == {"price_cited": True, "unit_present": True}

    def test_every_deck_row_scores_without_raising(self):
        # the pins are exercised end-to-end against an empty turn: no KeyError, no crash, just False.
        for r in _deck():
            res = EV._cascade_asserts(r, {"citations": [], "trace": {}, "structured": None, "answer": ""})
            assert set(res) == set(r["expect"]) & set(EV._CASCADE_EXPECT)
