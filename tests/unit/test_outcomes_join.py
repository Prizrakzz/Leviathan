"""OUTCOMES_JOIN J1 (the shared computation) + J2 (the structural PIT clamp). Pure/hermetic.

The fixtures are built to the MEASURED shapes the plan turns on, not to convenient shapes:

  * the roll-crossing fixture carries a splice artifact of ~2.5pp against a ~2pp realized move -- the
    corn median (2.308-2.578% artifact vs 8.01% realized at 90d) compressed into a short window, so a
    test that passed on the naive front chain would be visibly wrong rather than subtly wrong;
  * the price fence sees BOTH tape hazards: `settle = 0.0` exactly (217 live rows, on high-volume front
    contracts) and `settle IS NULL` (9,983 rows);
  * the clamp fixtures cover BOTH terms -- an asof that has not yet cleared `close + survive_days`, and
    a per-slug tape edge four sessions behind the asof (the live 15-Databento-vs-7-free-legs split);
  * the floor fixtures sit ON and BELOW `stats.MIN_QUANTILE_N`, which is `MIN_PERCENTILE_N` by
    definition -- one floor family with pattern-records `too_thin`.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from leviathan.graphrag import config_check as cc
from leviathan.graphrag.numbers import outcomes as OC
from leviathan.graphrag.numbers import stats as st
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver import futures_roll as FR

CORN = "corn_cbot"
CASH = "brazilian_arabica_coffee"          # CEPEA cash index -- the control leg (J1.f)
MGEX = "hard_red_spring_wheat_mgex"        # the delivery-cycle slug (listed months 3/5/7/9/12)


# ===================================================================================================
# Fixtures -- synthetic tape in the silver_futures_eod shape.
# ===================================================================================================
def _series(slug, contract_month, start, end, px_start, px_step, *, oi=None, kind="futures"):
    days = pd.bdate_range(start, end)
    rec = FC.CONTRACT_MAP[slug]
    return pd.DataFrame({
        "leviathan_slug": [slug] * len(days),
        "trade_date": days,
        "contract_month": [contract_month] * len(days),
        "settle": [px_start + px_step * i for i in range(len(days))],
        "unit": [rec["unit"]] * len(days),
        "currency": [rec["currency"]] * len(days),
        "settle_kind": [rec["settle_kind"]] * len(days),
        "open_interest": [oi] * len(days),
        "volume": [None] * len(days),
        "instrument_kind": [kind] * len(days),
    })


def roll_tape(*, oi=False):
    """Two corn contracts. 2024-03 is the FRONT at the anchor and DIES mid-window; 2024-05 lives on and
    trades ~12 cents higher (the carry). A naive front chain differences 2024-05's close against
    2024-03's anchor and books the whole spread as a price move."""
    m3 = _series(CORN, "2024-03", "2023-11-01", "2024-03-08", 480.0, 0.20,
                 oi=90000 if oi else None)
    m5 = _series(CORN, "2024-05", "2023-11-01", "2024-06-14", 492.0, 0.20,
                 oi=40000 if oi else None)
    return pd.concat([m3, m5], ignore_index=True)


def cash_tape():
    days = pd.bdate_range("2023-11-01", "2024-06-14")
    rec = FC.CONTRACT_MAP[CASH]
    return pd.DataFrame({
        "leviathan_slug": [CASH] * len(days), "trade_date": days,
        "contract_month": [None] * len(days),
        "settle": [1000.0 + 0.5 * i for i in range(len(days))],
        "unit": [rec["unit"]] * len(days), "currency": [rec["currency"]] * len(days),
        "settle_kind": [rec["settle_kind"]] * len(days),
        "open_interest": [None] * len(days), "volume": [None] * len(days),
        "instrument_kind": ["cash_index"] * len(days),
    })


ANCHOR = "2024-01-02"        # a corn firing
H = 90                       # -> nominal close 2024-04-01
CLOSE = date(2024, 4, 1)
FAR_ASOF = "2024-06-01"      # long past close + survive_days


def _outcome(tape, **kw):
    kw.setdefault("slug", CORN)
    kw.setdefault("event_key", "ev1")
    kw.setdefault("event_date", ANCHOR)
    kw.setdefault("horizon_days", H)
    kw.setdefault("asof", FAR_ASOF)
    return OC.anchored_outcome(tape, **kw)


# ===================================================================================================
# J1 -- THE SURVIVOR RULE. Roll-crossing, survival, the price fence, eligibility.
# ===================================================================================================
class TestSurvivorSelection:

    def test_the_fixture_really_does_carry_a_splice_the_naive_chain_would_book(self):
        # Guard the guard: if this assertion ever goes soft, every test below is testing nothing.
        tape = roll_tape()
        front_at_anchor = tape[(tape["contract_month"] == "2024-03")
                               & (tape["trade_date"] == pd.Timestamp("2024-01-02"))]["settle"].iloc[0]
        front_at_close = tape[(tape["contract_month"] == "2024-05")
                              & (tape["trade_date"] == pd.Timestamp("2024-04-01"))]["settle"].iloc[0]
        same_contract_start = tape[(tape["contract_month"] == "2024-05")
                                   & (tape["trade_date"] == pd.Timestamp("2024-01-02"))]["settle"].iloc[0]
        naive_pct = 100.0 * (front_at_close - front_at_anchor) / front_at_anchor
        true_pct = 100.0 * (front_at_close - same_contract_start) / same_contract_start
        assert naive_pct - true_pct > 2.0        # ~2.5pp of pure splice, the measured corn median shape
        assert true_pct < naive_pct

    def test_the_survivor_is_selected_and_the_splice_never_enters_the_move(self):
        row = _outcome(roll_tape())
        assert row["status"] == OC.STATUS_CLOSED
        assert row["contract_month_used"] == "2024-05"       # 2024-03 dies before close + 5d
        assert row["basis"] == FR.OUTCOME_CONTRACT_RULE_VERSION
        # both endpoints on ONE contract: the move is the contract's own, not the chain's
        tape = roll_tape()
        m5 = tape[tape["contract_month"] == "2024-05"].set_index("trade_date")["settle"]
        want = 100.0 * (m5[pd.Timestamp(row["endpoint_date"])] - m5[pd.Timestamp("2024-01-02")]) \
            / m5[pd.Timestamp("2024-01-02")]
        assert row["move_pct"] == pytest.approx(want)
        assert row["px0"] == pytest.approx(m5[pd.Timestamp("2024-01-02")])

    def test_a_contract_that_dies_inside_the_survive_margin_is_not_selected(self):
        # 2024-05 stops printing 3 days after the close -> inside survive_days=5 -> nothing qualifies.
        # The tape_edge is passed explicitly (as the builder always does, measured over the FULL tape)
        # so this isolates the SURVIVAL term: with the edge left to be inferred from this two-contract
        # slice the row would be PENDING on the per-slug term instead, which is a different fact.
        tape = pd.concat([_series(CORN, "2024-03", "2023-11-01", "2024-03-08", 480.0, 0.2),
                          _series(CORN, "2024-05", "2023-11-01", "2024-04-04", 492.0, 0.2)],
                         ignore_index=True)
        row = _outcome(tape, tape_edge=date(2026, 1, 1))
        assert row["status"] == f"{OC.STATUS_DECLINED_PREFIX}{OC.DECLINE_NO_SURVIVING_CONTRACT}"
        assert row["move_pct"] is None

    def test_last_print_is_mandatory_because_the_survival_test_is_the_rule(self):
        tape = roll_tape()
        at_anchor = tape[tape["trade_date"] == pd.Timestamp("2024-01-02")]
        with pytest.raises(ValueError, match="last_print is REQUIRED"):
            FR.outcome_contract(at_anchor, horizon_end=CLOSE)

    def test_the_price_fence_rejects_the_zero_and_the_null_settle(self):
        tape = roll_tape()
        anchor = tape["trade_date"] == pd.Timestamp("2024-01-02")
        # the 217-row hazard: settle = 0.0 EXACTLY on the contract that would otherwise be picked
        z = tape.copy()
        z.loc[anchor & (z["contract_month"] == "2024-05"), "settle"] = 0.0
        assert _outcome(z)["status"].startswith(OC.STATUS_DECLINED_PREFIX)
        # the 9,983-row hazard: settle IS NULL
        n = tape.copy()
        n.loc[anchor & (n["contract_month"] == "2024-05"), "settle"] = None
        assert _outcome(n)["status"].startswith(OC.STATUS_DECLINED_PREFIX)
        # and neither fabricates a move
        assert _outcome(z)["move_pct"] is None and _outcome(n)["move_pct"] is None

    def test_a_contract_already_in_delivery_is_ineligible(self):
        tape = _series(CORN, "2023-12", "2023-11-01", "2024-06-14", 480.0, 0.2)
        at_anchor = tape[tape["trade_date"] == pd.Timestamp("2024-01-02")]
        picked = FR.outcome_contract(at_anchor, horizon_end=CLOSE,
                                     last_print=FR.contract_last_print(tape))
        assert picked.empty        # the D8 eligibility predicate, shared with front_month

    def test_a_delivery_cycle_slug_only_selects_a_listed_month(self):
        listed, unlisted = "2026-05", "2026-04"        # MGEX lists 3/5/7/9/12
        tape = pd.concat([_series(MGEX, unlisted, "2026-01-02", "2026-12-01", 700.0, 0.1),
                          _series(MGEX, listed, "2026-01-02", "2026-12-01", 705.0, 0.1)],
                         ignore_index=True)
        at_anchor = tape[tape["trade_date"] == pd.Timestamp("2026-01-02")]
        picked = FR.outcome_contract(at_anchor, horizon_end=date(2026, 4, 1),
                                     last_print=FR.contract_last_print(tape))
        assert list(picked["contract_month"]) == [listed]

    def test_a_cash_reference_has_no_contract_axis_and_is_dropped_by_the_rule(self):
        tape = cash_tape()
        at_anchor = tape[tape["trade_date"] == pd.Timestamp("2024-01-02")]
        picked = FR.outcome_contract(at_anchor, horizon_end=CLOSE,
                                     last_print=FR.contract_last_print(tape))
        assert picked.empty

    def test_selection_is_deterministic_and_takes_the_nearest_survivor(self):
        tape = pd.concat([roll_tape(),
                          _series(CORN, "2024-07", "2023-11-01", "2024-08-01", 500.0, 0.2)],
                         ignore_index=True)
        at_anchor = tape[tape["trade_date"] == pd.Timestamp("2024-01-02")]
        lp = FR.contract_last_print(tape)
        first = FR.outcome_contract(at_anchor, horizon_end=CLOSE, last_print=lp)
        second = FR.outcome_contract(at_anchor.iloc[::-1], horizon_end=CLOSE, last_print=lp)
        assert list(first["contract_month"]) == ["2024-05"] == list(second["contract_month"])


class TestTheForwardMonthFloorReachesTheSpanRead:
    """V2-4 -- `span_outcome` is the walk's and J4's pricing sequence, and it selects through
    `futures_roll.outcome_contract`. The floor therefore has to arrive HERE, through the shared
    predicate, without this module knowing anything about averaging boards."""

    PALM = "malaysian_crude_palm_oil_cme"

    def _palm_tape(self, months, first="2025-10-01"):
        """Sixty listed months in the CPO shape: every contract prints to the LAST BUSINESS DAY OF
        ITS OWN DELIVERY MONTH, which is what makes the endpoint's own month survive t2 + 5 and is
        the whole reason the floor exists."""
        frames = []
        for i, cm in enumerate(months):
            days = pd.bdate_range(first, pd.Timestamp(cm + "-01") + pd.offsets.MonthEnd(1))
            frames.append(pd.DataFrame({
                "leviathan_slug": self.PALM, "trade_date": days, "contract_month": cm,
                "settle": [900.0 + 3.0 * i + 0.05 * j for j in range(len(days))],
                "unit": "USD/metric ton", "currency": "USD", "settle_kind": "settlement",
                "open_interest": [1000 - i] * len(days), "volume": [None] * len(days),
                "instrument_kind": ["futures"] * len(days)}))
        return pd.concat(frames, ignore_index=True)

    def test_the_survivor_sits_at_least_ONE_month_past_the_endpoint_month(self):
        """RE-ANCHORED +2 -> +1 (STEP-12 review MAJ-2). The rule the floor encodes is "never read a
        month that is still accruing", and a contract starts accruing on ITS OWN month's first
        business day -- so the endpoint month + 1 is already a pure forward mark and the second
        month was margin. It was not free margin: it pushed the child two months past a parent the
        MAJOR-8 tenor fence requires to be same-or-adjacent."""
        months = [f"2026-{m:02d}" for m in range(1, 13)] + [f"2027-{m:02d}" for m in range(1, 13)]
        tape = self._palm_tape(months)
        for span_end, want in (("2026-03-04", "2026-04"), ("2026-03-31", "2026-04"),
                               ("2026-06-15", "2026-07"), ("2026-11-02", "2026-12")):
            row = OC.span_outcome(tape, slug=self.PALM, span_start="2026-01-05",
                                  span_end=span_end, asof="2027-06-01")
            assert row["status"] == OC.STATUS_CLOSED, (span_end, row["decline_reason"])
            used = row["contract_month_used"]
            assert used == want, (span_end, used)
            end_m = int(span_end[:4]) * 12 + int(span_end[5:7])
            used_m = int(used[:4]) * 12 + int(used[5:7])
            assert used_m - end_m >= 1, (span_end, used)

    def test_the_move_is_read_on_that_one_forward_contract_at_both_ends(self):
        months = [f"2026-{m:02d}" for m in range(1, 13)]
        tape = self._palm_tape(months)
        row = OC.span_outcome(tape, slug=self.PALM, span_start="2026-01-05",
                              span_end="2026-03-04", asof="2027-06-01")
        m4 = tape[tape["contract_month"] == "2026-04"].set_index("trade_date")["settle"]
        px0, px1 = m4[pd.Timestamp(row["anchor_date"])], m4[pd.Timestamp(row["endpoint_date"])]
        assert row["px0"] == pytest.approx(px0) and row["px1"] == pytest.approx(px1)
        assert row["move_pct"] == pytest.approx(100.0 * (px1 - px0) / px0)

    def test_a_floored_out_window_declines_as_no_spanning_contract_not_as_a_new_reason(self):
        """The absence VOCABULARY is untouched: a board that lists nothing far enough forward is
        the existing 'no ONE contract spans this window' fact, so no reader-facing word is minted.

        RE-CUT for floor 1: the board now lists only through the endpoint's own month, so nothing
        clears endpoint + 1 (at floor 2 the same point needed a tape one month longer)."""
        tape = self._palm_tape(["2026-01", "2026-02"])
        row = OC.span_outcome(tape, slug=self.PALM, span_start="2026-01-05",
                              span_end="2026-02-10", asof="2027-06-01")
        assert row["decline_reason"] == OC.DECLINE_NO_SPANNING_CONTRACT
        assert row["move_pct"] is None

    def test_the_same_shape_on_an_unfloored_board_keeps_the_shipped_answer(self):
        """The control: corn on the identical tape shape takes the endpoint's own month, because
        for a point-in-time settle that IS the right contract."""
        months = ["2026-03", "2026-05", "2026-07", "2026-09"]
        frames = []
        for i, cm in enumerate(months):
            days = pd.bdate_range("2025-10-01", pd.Timestamp(cm + "-01") + pd.offsets.MonthEnd(1))
            frames.append(pd.DataFrame({
                "leviathan_slug": CORN, "trade_date": days, "contract_month": cm,
                "settle": [470.0 + 3.0 * i + 0.05 * j for j in range(len(days))],
                "unit": "US cents/bushel", "currency": "USD", "settle_kind": "settlement",
                "open_interest": [1000 - i] * len(days), "volume": [None] * len(days),
                "instrument_kind": ["futures"] * len(days)}))
        row = OC.span_outcome(pd.concat(frames, ignore_index=True), slug=CORN,
                              span_start="2026-01-05", span_end="2026-03-04", asof="2027-06-01")
        assert row["contract_month_used"] == "2026-03"


class TestRuleVersioning:

    def test_the_survivor_rule_is_a_second_rule_with_its_own_version(self):
        assert FR.OUTCOME_CONTRACT_RULE_VERSION == "survivor_nearest_v1"
        assert FR.OUTCOME_CONTRACT_RULE_VERSION != FR.ROLL_RULE_VERSION
        assert FR.OUTCOME_SURVIVE_DAYS == 5

    def test_pinning_a_foreign_version_raises_rather_than_behaving_differently(self):
        with pytest.raises(ValueError, match="rule_version"):
            FR.outcome_contract(roll_tape(), horizon_end=CLOSE, last_print=pd.DataFrame(),
                                rule_version="front_month_v2")

    def test_the_lint_catches_a_shared_version_string(self, monkeypatch):
        monkeypatch.setattr(FR, "OUTCOME_CONTRACT_RULE_VERSION", FR.ROLL_RULE_VERSION)
        assert any("two rules, two version strings" in e for e in FR.lint_roll_rule())

    def test_the_lint_catches_a_nonsense_survive_margin(self, monkeypatch):
        monkeypatch.setattr(FR, "OUTCOME_SURVIVE_DAYS", 0)
        assert any("OUTCOME_SURVIVE_DAYS" in e for e in FR.lint_roll_rule())

    def test_the_f_l_fence_covers_the_new_rule_too(self):
        toks = cc._ROLL_RULE_FORBIDDEN_TOKENS
        assert "def outcome_contract(" in toks and "OUTCOME_CONTRACT_RULE_VERSION =" in toks
        assert not cc.check_futures_roll()          # and nothing in the tree trips it today


class TestWasFront:

    def test_was_front_is_null_not_false_when_the_roll_rule_has_no_inputs(self):
        assert _outcome(roll_tape(oi=False))["was_front"] is None

    def test_was_front_is_false_when_the_survivor_is_not_the_front(self):
        row = _outcome(roll_tape(oi=True))
        assert row["was_front"] is False            # front = 2024-03 (higher OI), survivor = 2024-05


# ===================================================================================================
# J2 -- THE CLAMP. Both terms, both shapes, and the pending rendering.
# ===================================================================================================
class TestClamp:

    def test_survive_days_is_part_of_the_boundary_not_only_of_the_selection(self):
        tape = roll_tape()
        edge = date(2026, 1, 1)                     # tape edge far ahead: isolate the asof term
        # asof inside [close+1, close+survive+lag): the SELECTION would have used tape past the boundary
        inside = (CLOSE + timedelta(days=OC.SURVIVE_DAYS)).isoformat()
        assert OC.clamp_anchored(ANCHOR, H, inside, edge)["status"] == OC.STATUS_PENDING
        just_out = (CLOSE + timedelta(days=OC.SURVIVE_DAYS + OC.TAPE_PUBLICATION_LAG_DAYS)).isoformat()
        assert OC.clamp_anchored(ANCHOR, H, just_out, edge)["status"] == OC.STATUS_CLOSED
        assert _outcome(tape, asof=inside, tape_edge=edge)["status"] == OC.STATUS_PENDING
        assert _outcome(tape, asof=just_out, tape_edge=edge)["status"] == OC.STATUS_CLOSED

    def test_the_clamp_is_per_slug_the_databento_vs_free_leg_split(self):
        # asof far ahead, but THIS slug's tape ends four sessions early (the live 07-27 vs 07-31 shape)
        behind = CLOSE + timedelta(days=2)
        row = _outcome(roll_tape(), asof=FAR_ASOF, tape_edge=behind)
        assert row["status"] == OC.STATUS_PENDING
        assert OC.clamp_anchored(ANCHOR, H, FAR_ASOF, behind)["pending_reason"] == "edge"
        # a GLOBAL edge (four sessions later) would have called the same row closed -- the bug this
        # test exists to catch
        assert _outcome(roll_tape(), asof=FAR_ASOF,
                        tape_edge=CLOSE + timedelta(days=30))["status"] == OC.STATUS_CLOSED

    def test_a_pending_horizon_renders_with_its_close_date_and_no_measurement(self):
        row = _outcome(roll_tape(), asof="2024-03-20", tape_edge=date(2026, 1, 1))
        assert row["status"] == OC.STATUS_PENDING
        assert row["horizon_close_date"] == CLOSE.isoformat()          # it says WHEN it closes
        assert row["decline_reason"] is None                            # NOT a coverage gap
        for k in ("px1", "move_abs", "move_pct", "endpoint_date", "contract_month_used", "px0"):
            assert row[k] is None
        assert row["readable_date"] == ANCHOR                           # readable, and it states timing
        assert not OC.lint_outcome_row_invariants([row])

    def test_pending_and_declined_are_different_vocabularies(self):
        pending = _outcome(roll_tape(), asof="2024-03-20", tape_edge=date(2026, 1, 1))
        declined = _outcome(roll_tape(), event_date="2010-05-03")       # straddles the coverage floor
        assert pending["status"] == OC.STATUS_PENDING
        assert declined["status"].startswith(OC.STATUS_DECLINED_PREFIX)
        assert declined["decline_reason"] in OC.DECLINE_REASONS
        assert pending["status"] != declined["status"]

    def test_a_closed_row_guards_on_its_horizon_close(self):
        row = _outcome(roll_tape())
        assert row["readable_date"] == row["endpoint_date"] is not None
        assert not OC.lint_outcome_row_invariants([row])

    def test_the_row_invariants_catch_a_move_readable_before_its_close(self):
        row = dict(_outcome(roll_tape()))
        row["readable_date"] = row["event_date"]                        # the leak D-OJ-13 closes
        assert any("readable before its horizon closes" in e
                   for e in OC.lint_outcome_row_invariants([row]))

    def test_the_row_invariants_catch_a_pending_row_carrying_a_price(self):
        row = dict(_outcome(roll_tape(), asof="2024-03-20", tape_edge=date(2026, 1, 1)))
        row["px1"] = 500.0
        assert any("no forward measurement" in e for e in OC.lint_outcome_row_invariants([row]))

    def test_the_span_clamp_is_day_grain_and_was_never_stated_for_shape_ii(self):
        tape = roll_tape()
        # a span ending 2024-03-29 with an asof of 2024-04-01: t2 + 5 > asof - 1 -> PENDING
        pend = OC.span_outcome(tape, slug=CORN, span_start="2024-01-02", span_end="2024-03-29",
                               asof="2024-04-01", tape_edge=date(2026, 1, 1))
        assert pend["status"] == OC.STATUS_PENDING
        ok = OC.span_outcome(tape, slug=CORN, span_start="2024-01-02", span_end="2024-03-29",
                             asof=FAR_ASOF, tape_edge=date(2026, 1, 1))
        assert ok["status"] == OC.STATUS_CLOSED and ok["move_pct"] is not None
        # a MONTH token expanded to month-end (2024-03-31) would price 2 days further -- the day-grain
        # end is what the clamp reads, and the two verdicts differ at exactly that boundary
        assert (OC.clamp_span("2024-03-29", "2024-04-04", date(2026, 1, 1))["status"]
                != OC.clamp_span("2024-03-31", "2024-04-04", date(2026, 1, 1))["status"])

    def test_reclamping_a_stale_closed_row_at_an_earlier_asof_restores_pending(self):
        row = _outcome(roll_tape())
        assert row["status"] == OC.STATUS_CLOSED
        again = OC.clamp_row(row, "2024-03-20", date(2026, 1, 1))
        assert again["status"] == OC.STATUS_PENDING
        assert again["move_pct"] is None and again["endpoint_date"] is None
        assert again["horizon_close_date"] == CLOSE.isoformat()
        assert not OC.lint_outcome_row_invariants([again])

    def test_the_reclamp_strips_the_SELECTION_not_only_the_measurement(self):
        # The reviewer's C-row: a closed row carrying px0=404.0 / contract=2024-05 / was_front, re-clamped
        # to an asof inside the window, kept BOTH future-conditioned selection values and the lint passed
        # it. `anchored_outcome` refuses to publish exactly those two on a pending row (it runs the clamp
        # BEFORE the selection, and says why in its own comment) -- and the re-clamp is the path EVERY
        # pinned-asof replay takes (pattern_records.pattern_outcome_legs).
        row = _outcome(roll_tape())
        assert row["px0"] and row["contract_month_used"] == "2024-05"
        again = OC.clamp_row(row, "2024-03-20", date(2026, 1, 1))
        for k in ("px0", "contract_month_used", "was_front", "anchor_date", "anchor_offset_days",
                  "unit", "currency", "settle_kind", "basis"):
            assert again[k] is None, k
        assert again["readable_date"] == pd.Timestamp(ANCHOR).date().isoformat()
        # ... and the MIRROR: a hand-built pending row that kept them is now a lint error, so the strip
        # cannot silently regress.
        leaky = dict(again, px0=404.0, contract_month_used="2024-05")
        errs = OC.lint_outcome_row_invariants([leaky])
        assert any("px0" in e for e in errs) and any("contract_month_used" in e for e in errs)
        assert all("SELECTED with tape past this boundary" in e for e in errs)

    def test_a_zero_length_window_declines_instead_of_measuring_plus_zero(self):
        # A window whose endpoint snaps back onto the anchor session has NO elapsed session, so px1 IS
        # px0 and the "move" is +0.0% across nothing. `timeline.episodes_for` builds start,end from the
        # AS-OF-CLAMPED visible prop dates, so a single visible date MANUFACTURES start == end -- and
        # `cascade._episode_outcome_legs` rejects only `move_pct is None`, so that fabricated magnitude
        # reached an [N] handle as "- [N4] corn_cbot settle change ... : +0 %".
        tape = roll_tape()
        one_day = OC.span_outcome(tape, slug=CORN, span_start="2024-03-11", span_end="2024-03-11",
                                  asof=FAR_ASOF, tape_edge=date(2026, 1, 1))
        assert one_day["status"] == f"{OC.STATUS_DECLINED_PREFIX}{OC.DECLINE_NO_ENDPOINT_SESSION}"
        assert one_day["move_pct"] is None
        assert one_day["basis"] == OC.BASIS_SURVIVOR and one_day["horizon_label"] == "span"
        # the same shape on the anchored side: a horizon whose whole span is dark past the anchor
        dark = pd.concat([roll_tape(),
                          _series(CORN, "2024-05", "2024-06-17", "2024-09-30", 500.0, 0.0)],
                         ignore_index=True)
        assert OC.span_outcome(dark, slug=CORN, span_start="2024-06-14", span_end="2024-06-14",
                               asof=FAR_ASOF, tape_edge=date(2026, 1, 1))["move_pct"] is None
        # and a hand-built closed row claiming a move over zero sessions is a lint error
        bad = dict(_outcome(roll_tape()), realized_sessions=0)
        assert any("realized_sessions" in e for e in OC.lint_outcome_row_invariants([bad]))

    def test_the_prior_path_read_takes_the_boundary_like_every_other_tape_read(self):
        # AM-2's percentile default re-measures prior paths at query time, and this was the one
        # tape-reading function in the module with no asof and no boundary: PIT-safety rested entirely
        # on the caller having pre-clamped `tape`, which nothing enforced.
        tape = roll_tape()
        unclamped = OC.path_move_pct_at(tape, slug=CORN, contract_month="2024-05",
                                        anchor_date="2024-01-02", elapsed_sessions=40)
        assert unclamped is not None
        clamped = OC.path_move_pct_at(tape, slug=CORN, contract_month="2024-05",
                                      anchor_date="2024-01-02", elapsed_sessions=40,
                                      asof="2024-02-01")
        assert clamped is None                       # 40 sessions are not readable at that asof
        assert OC.path_move_pct_at(tape, slug=CORN, contract_month="2024-05",
                                   anchor_date="2024-01-02", elapsed_sessions=40,
                                   boundary=date(2024, 2, 1)) is None
        # an unmeasured current instance is a NAMED refusal, never a TypeError out of stats.percentile
        priors = [{"leviathan_slug": CORN, "contract_month_used": "2024-05",
                   "anchor_date": "2024-01-02"}] * 6
        out = OC.elapsed_percentile(None, priors, elapsed_sessions=5, tape=tape,
                                    mode=OC.MILESTONE_MODE_QUERY_TIME)
        assert out["declined"] and out["reason"] == OC.DECLINE_NO_ENDPOINT_SESSION

    def test_pending_state_is_computed_from_the_event_never_inferred_from_absence(self):
        assert OC.pending_state(ANCHOR, H, "2024-03-20", date(2026, 1, 1)) is True
        assert OC.pending_state(ANCHOR, H, FAR_ASOF, date(2026, 1, 1)) is False

    def test_the_evaluable_denominator_is_stated_positively(self):
        assert OC.OUTCOME_EVALUABLE_STATUSES == (OC.STATUS_CLOSED,)
        assert OC.evaluable_pred() == "(status IN ('closed'))"


class TestCoverageFloor:

    def test_a_window_before_the_measured_floor_declines(self):
        row = _outcome(roll_tape(), event_date="2009-01-05")
        assert row["decline_reason"] == OC.DECLINE_PRE_COVERAGE

    def test_a_window_straddling_the_floor_declines_rather_than_splicing(self):
        row = _outcome(roll_tape(), event_date="2010-05-03")     # corn floor = 2010-06-06
        assert row["decline_reason"] == OC.DECLINE_COVERAGE_STRADDLE

    def test_an_unmapped_slug_is_never_given_a_permissive_default(self):
        row = _outcome(roll_tape(), slug="not_a_slug")
        assert row["decline_reason"] == OC.DECLINE_UNMAPPED_SLUG


# ===================================================================================================
# AM-1 -- the horizon family, and the year exclusion stated rather than substituted.
# ===================================================================================================
class TestHorizonFamily:

    def test_the_family_is_exactly_the_four_anchored_horizons(self):
        assert OC.HORIZON_DAYS == (5, 30, 60, 90)
        assert set(OC.HORIZON_LABELS) == set(OC.HORIZON_DAYS)

    def test_a_year_horizon_declines_honestly_and_is_never_rounded_to_90(self):
        d = OC.horizon_decline(365)
        assert d["declined"] and d["reason"] == OC.DECLINE_UNSUPPORTED_HORIZON
        assert "EXCLUDED" in d["detail"] and "252 sessions" in d["detail"]
        row = _outcome(roll_tape(), horizon_days=365)
        assert row["status"] == f"{OC.STATUS_DECLINED_PREFIX}{OC.DECLINE_UNSUPPORTED_HORIZON}"
        assert row["move_pct"] is None

    def test_every_horizon_in_the_family_measures_on_the_same_basis(self):
        tape = roll_tape()
        for h in OC.HORIZON_DAYS:
            row = _outcome(tape, horizon_days=h, asof="2024-07-01")
            assert row["status"] == OC.STATUS_CLOSED
            assert row["basis"] == FR.OUTCOME_CONTRACT_RULE_VERSION
            assert row["contract_month_used"]


class TestContractToken:

    def test_the_render_token_cannot_match_the_eval_year_month_regex(self):
        import re
        ym = re.compile(r"(?<!\d)((?:1[6-9]\d{2}|20\d{2}))-(0[1-9]|1[0-2])(?!\d)")
        assert OC.contract_token("2024-03") == "2024M03"
        assert not ym.search(OC.contract_token("2024-03"))
        assert ym.search("2024-03")            # the form that would red the episode pins
        assert OC.contract_token(None) is None


# ===================================================================================================
# AM-3 / the standing stats-tools directive -- distributions compute through stats.py and inherit its
# floors; below the floor the answer is a thin-coverage DECLINE, never a distribution.
# ===================================================================================================
def _closed_rows(n, base=1.0):
    return [{"status": OC.STATUS_CLOSED, "move_pct": base + i} for i in range(n)]


class TestFloors:

    def test_the_floor_is_the_stats_module_floor_not_a_second_number(self):
        assert OC.OUTCOME_MIN_N == st.MIN_QUANTILE_N == st.MIN_PERCENTILE_N
        assert OC.OUTCOME_THIN_REASON == "too_thin"        # one vocabulary with pattern-records

    def test_below_the_floor_it_declines_and_publishes_counts_only(self):
        rows = _closed_rows(OC.OUTCOME_MIN_N - 1) + [{"status": OC.STATUS_PENDING}]
        out = OC.outcome_distribution(rows)
        assert out["declined"] is True and out["reason"] == "too_thin"
        assert out["n_closed"] == OC.OUTCOME_MIN_N - 1 and out["n_pending"] == 1
        for leaked in ("quantiles", "min", "max"):
            assert leaked not in out                       # a decline carries NO magnitudes

    def test_at_the_floor_it_computes_through_stats(self):
        rows = _closed_rows(OC.OUTCOME_MIN_N) + [{"status": OC.STATUS_PENDING}] * 2
        out = OC.outcome_distribution(rows, probs=(0.5,))
        assert out["declined"] is False and out["n_closed"] == OC.OUTCOME_MIN_N
        assert out["n_pending"] == 2                       # published BESIDE n_closed, always
        want = st.quantiles([r["move_pct"] for r in rows if "move_pct" in r], (0.5,))
        assert out["quantiles"] == want["quantiles"]
        assert out["n_up"] + out["n_down"] + out["n_flat"] == OC.OUTCOME_MIN_N

    def test_declines_are_counted_by_reason_and_never_swell_the_denominator(self):
        rows = _closed_rows(3) + [
            {"status": f"{OC.STATUS_DECLINED_PREFIX}{OC.DECLINE_NO_SURVIVING_CONTRACT}",
             "decline_reason": OC.DECLINE_NO_SURVIVING_CONTRACT}]
        out = OC.outcome_distribution(rows)
        assert out["n_closed"] == 3 and out["n_declined"] == 1
        assert out["declined_by_reason"] == {OC.DECLINE_NO_SURVIVING_CONTRACT: 1}

    def test_the_quantile_calculator_is_not_an_agent_tool(self):
        # AM-3 gates NEW agent-callable stats; an engine calculator must not widen the tool enum.
        assert "quantiles" not in st.STAT_REGISTRY
        assert st.quantiles([1.0, 2.0], (0.5,))["declined"] is True
        assert not cc.check_stats_registry()


class TestOpenInstanceAM2:

    def test_the_realized_so_far_read_is_observed_data_and_says_its_basis_is_provisional(self):
        tape = roll_tape()
        out = OC.realized_so_far(tape, slug=CORN, event_key="ev1", event_date=ANCHOR,
                                 horizon_days=H, asof="2024-02-15", tape_edge=date(2024, 2, 14))
        assert out["declined"] is False and out["status"] == "open"
        assert out["basis_provisional"] is True             # selected against the KNOWN edge
        assert out["pending"] is True                       # ... and the horizon is still open
        assert out["move_pct"] is not None and out["elapsed_sessions"] > 0
        assert out["px_asof"] is not None and out["asof_date"] <= "2024-02-14"

    def test_the_default_milestone_mode_adds_no_storage(self, monkeypatch):
        monkeypatch.delenv("GRAPHRAG_OUTCOME_MILESTONES", raising=False)
        assert OC.milestone_mode() == OC.MILESTONE_MODE_QUERY_TIME
        monkeypatch.setenv("GRAPHRAG_OUTCOME_MILESTONES", "stored")
        assert OC.milestone_mode() == OC.MILESTONE_MODE_STORED
        monkeypatch.setenv("GRAPHRAG_OUTCOME_MILESTONES", "junk")
        assert OC.milestone_mode() == OC.MILESTONE_MODE_QUERY_TIME     # fail-safe to the default

    def test_the_elapsed_percentile_inherits_the_refusal_floor(self):
        tape = roll_tape()
        priors = [{"leviathan_slug": CORN, "contract_month_used": "2024-05",
                   "anchor_date": d} for d in ("2023-11-06", "2023-11-13", "2023-11-20")]
        out = OC.elapsed_percentile(1.0, priors, elapsed_sessions=5, tape=tape,
                                    mode=OC.MILESTONE_MODE_QUERY_TIME)
        assert out["declined"] is True and out["reason"] == "too_thin"
        assert out["floor"] == st.MIN_PERCENTILE_N

    def test_the_elapsed_percentile_computes_through_stats_when_covered(self):
        tape = roll_tape()
        anchors = [f"2023-11-{d:02d}" for d in (6, 7, 8, 9, 10, 13, 14, 15, 16, 17)]
        priors = [{"leviathan_slug": CORN, "contract_month_used": "2024-05", "anchor_date": a}
                  for a in anchors]
        out = OC.elapsed_percentile(0.0, priors, elapsed_sessions=5, tape=tape,
                                    mode=OC.MILESTONE_MODE_QUERY_TIME)
        assert out["declined"] is False and out["n"] >= st.MIN_PERCENTILE_N
        assert 0.0 <= out["percentile"] <= 100.0
        assert out["mode"] == OC.MILESTONE_MODE_QUERY_TIME

    def test_the_stored_path_is_implemented_and_names_its_own_cost(self):
        priors = [{"milestone_move_pct_5": float(i)} for i in range(st.MIN_PERCENTILE_N)]
        out = OC.elapsed_percentile(3.0, priors, elapsed_sessions=5, mode=OC.MILESTONE_MODE_STORED)
        assert out["declined"] is False
        # the coarseness IS the cost: an arbitrary k has no stored column and says so
        miss = OC.elapsed_percentile(3.0, priors, elapsed_sessions=7, mode=OC.MILESTONE_MODE_STORED)
        assert miss["declined"] is True and miss["reason"] == "milestone_not_stored"
        assert OC.milestone_columns() == tuple(f"milestone_move_pct_{k}" for k in (5, 10, 21, 42, 63))


# ===================================================================================================
# The builder core: full rebuild, materialized pending, no episode-derived row, rebuild-and-diff.
# ===================================================================================================
class TestBuild:

    def _anchors(self):
        return [{"leviathan_slug": CORN, "event_key": "ev1", "event_date": ANCHOR},
                {"leviathan_slug": CORN, "event_key": "ev2", "event_date": "2024-03-01"}]

    def test_one_row_per_event_and_horizon_with_pending_materialized(self):
        frame = OC.build_outcomes(self._anchors(), roll_tape(), asof="2024-04-15",
                                  built_at="2024-04-15T00:00:00")
        assert len(frame) == 2 * len(OC.HORIZON_DAYS)
        statuses = set(frame["status"])
        assert OC.STATUS_CLOSED in statuses and OC.STATUS_PENDING in statuses
        # ev2's 90d horizon closes 2024-05-30, well past the asof -> pending WITH its close date
        pend = frame[(frame["event_key"] == "ev2") & (frame["horizon_days"] == 90)].iloc[0]
        assert pend["status"] == OC.STATUS_PENDING and pend["horizon_close_date"] == "2024-05-30"
        assert not OC.lint_outcome_row_invariants(frame.to_dict("records"))
        assert list(frame["event_year"].unique()) == [2024]

    def test_no_episode_derived_row_is_ever_written(self):
        anchors = [{"leviathan_slug": CORN, "event_key": "ep1", "event_date": ANCHOR,
                    "span_start": "2024-01-02", "span_end": "2024-03-01"}]
        with pytest.raises(ValueError, match="stores no .*episode-derived row|episode-derived row"):
            OC.build_outcomes(anchors, roll_tape(), asof=FAR_ASOF, built_at="x")

    def test_two_rebuilds_at_the_same_tape_edge_are_identical(self):
        a = OC.build_outcomes(self._anchors(), roll_tape(), asof=FAR_ASOF, built_at="2026-01-01T00:00:00")
        b = OC.build_outcomes(self._anchors(), roll_tape(), asof=FAR_ASOF, built_at="2026-08-01T09:30:00")
        assert OC.outcomes_fingerprint(a) == OC.outcomes_fingerprint(b)   # built_at is provenance
        assert list(a["built_at"]) != list(b["built_at"])                 # ... and it IS carried

    def test_the_stored_milestone_mode_adds_its_columns_and_nothing_else(self):
        frame = OC.build_outcomes(self._anchors(), roll_tape(), asof=FAR_ASOF, built_at="x",
                                  milestones=OC.MILESTONE_MODE_STORED)
        for col in OC.milestone_columns():
            assert col in frame.columns
        base = OC.build_outcomes(self._anchors(), roll_tape(), asof=FAR_ASOF, built_at="x")
        assert not set(OC.milestone_columns()) & set(base.columns)


# ===================================================================================================
# J1.f -- the CEPEA control leg. The one path where a bug cannot hide behind a roll argument.
# ===================================================================================================
class TestCashControlLeg:

    def test_the_cash_index_uses_its_own_basis_and_no_contract(self):
        row = OC.anchored_outcome(cash_tape(), slug=CASH, event_key="c1", event_date=ANCHOR,
                                  horizon_days=H, asof=FAR_ASOF)
        assert row["status"] == OC.STATUS_CLOSED
        assert row["basis"] == OC.BASIS_CASH and row["contract_month_used"] is None
        assert row["move_pct"] > 0
        assert not OC.lint_outcome_row_invariants([row])

    def test_the_two_bases_agree_in_sign_on_the_same_window(self):
        cash = OC.anchored_outcome(cash_tape(), slug=CASH, event_key="c1", event_date=ANCHOR,
                                   horizon_days=H, asof=FAR_ASOF)
        fut = _outcome(roll_tape())
        assert (cash["move_pct"] > 0) == (fut["move_pct"] > 0)

    def test_the_endpoint_records_its_day_of_week_and_its_stretch(self):
        row = _outcome(roll_tape())
        assert row["endpoint_dow"] in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        assert 0 <= row["realized_offset_days"] <= OC.OUTCOME_LOOKBACK_DAYS
        assert row["realized_sessions"] > 0


# ===================================================================================================
# D-OJ-13 -- the card. The clamp compiles from exactly two fields plus one arithmetic identity.
# ===================================================================================================
class TestCard:

    def test_the_card_lints_clean_wherever_it_currently_lives(self):
        card, source = OC._read_card()
        assert source in ("served", "staged") and card
        assert OC.lint_outcome_card() == []
        assert cc.check_futures_outcomes() == []

    def test_the_publication_lag_carries_survive_days_into_the_compiled_sql(self):
        assert OC.OUTCOME_PUBLICATION_LAG_DAYS == FR.OUTCOME_SURVIVE_DAYS + 1 == 6
        card = dict(OC._read_card()[0])
        card["publication_lag_days"] = 1
        errs = OC.lint_outcome_card(card)
        assert any("publication_lag_days" in e for e in errs)

    def test_the_guard_column_is_never_the_event_date(self):
        card = dict(OC._read_card()[0])
        assert card["knowledge_date_col"] == card["date_col"] == "readable_date"
        card["knowledge_date_col"] = "event_date"
        card["date_col"] = "event_date"
        assert len(OC.lint_outcome_card(card)) >= 2

    def test_the_card_refuses_a_forward_looking_metric(self):
        card = dict(OC._read_card()[0])
        card["metrics"] = dict(card["metrics"])
        card["metrics"]["forecast_move_pct"] = {"unit": "%", "desc": "x"}
        assert any("forward-looking ban" in e for e in OC.lint_outcome_card(card))

    def test_the_card_is_fenced_out_of_serving_until_its_producer_exists(self):
        from leviathan.graphrag.numbers import registry as R
        assert OC.OUTCOME_TABLE_ID in R.WHITELIST_ABSENT_DEFAULT
        assert OC.OUTCOME_TABLE_ID not in R.load_registry().tables

    def test_all_three_wave_ids_are_fenced_and_the_fence_stays_env_disjoint(self):
        # The same argument that armed `gold_futures_outcomes` ahead of its producer arms the other
        # two. `gold_pattern_outcomes` needs it MOST: its ledger carries a second PIT axis
        # (`ledger_written_at`) that `TableSpec.knowledge_col()` cannot express, so a paste without the
        # fence is a live PIT hole rather than a scheduling detail. `gold_cot_outcomes` is in both
        # POSITIONING_TABLES constants and was in no whitelist at all (adversarial finding 14).
        from leviathan.graphrag.numbers import pattern_records as PR
        from leviathan.graphrag.numbers import registry as R
        for tid in (OC.OUTCOME_TABLE_ID, PR.PO_TABLE, cc.POSITIONING_TABLES[1]):
            assert tid in R.WHITELIST_ABSENT_DEFAULT
            assert tid not in R.load_registry().tables
        assert not (R.WHITELIST_ABSENT_DEFAULT & R._disabled_tables())    # env lane stays separate
        # ... and fencing the J6 id does NOT blind its own R7b unit lint: config_check reads that card
        # from the RAW registry file, not through load_registry (which drops whitelisted ids).
        bad = cc._check_cot_outcome_metrics(
            type("_S", (), {"metrics": {"move_pct": type("_M", (), {"unit": "US cents/bushel",
                                                                    "desc": "x"})()}})(),
            __import__("leviathan.graphrag.register", fromlist=["x"]),
            __import__("leviathan.graphrag.numbers.stats", fromlist=["x"]))
        assert any("admitted set" in e for e in bad)

    def test_an_absent_card_is_vacuous_rather_than_a_red_build_on_an_untracked_file(self):
        # configs/graphrag/numbers/{tables.yaml,cards/*.yaml} are BOTH gitignored, so a hard error on
        # absence makes a fresh clone fail a lint about a card it was never given -- unlike every
        # sibling check, which is vacuous until its table is registered. What keeps serving safe in
        # that state is the whitelist fence, not this lint (adversarial finding 13).
        import leviathan.graphrag.numbers.outcomes as _oc
        real = _oc._read_card
        try:
            _oc._read_card = lambda: (None, "none")
            assert _oc.lint_outcome_card() == []
            assert cc.check_futures_outcomes() == []
        finally:
            _oc._read_card = real
        assert cc.check_futures_outcomes() == []        # and non-vacuous again with the card present

    def test_the_staged_card_carries_the_landing_recipe_rather_than_assuming_it(self):
        from leviathan.graphrag import extract as ex
        staged = ex._CFG / "numbers" / "cards" / f"{OC.OUTCOME_TABLE_ID}.yaml"
        if not staged.exists():
            pytest.skip("the card has landed in tables.yaml; the staged copy is retired")
        text = staged.read_text(encoding="utf-8")
        for needle in ("configs/silver/tables/gold_futures_outcomes.yaml",
                       "generate_ddls_from_registry.py", "NUMBERS_TABLES",
                       "WHITELIST_ABSENT_DEFAULT"):
            assert needle in text        # the four things that must land WITH it, named on the file

    def test_the_compiled_guard_is_the_ratified_rule(self):
        # E + H + survive_days <= asof - tape_lag   <=>   readable_date <= asof - 6
        from leviathan.graphrag.numbers.query import _pub_lagged_asof
        assert _pub_lagged_asof("2024-04-08", OC.OUTCOME_PUBLICATION_LAG_DAYS) == "2024-04-02"
        closed = OC.clamp_anchored(ANCHOR, H, "2024-04-07", date(2026, 1, 1))
        assert closed["status"] == OC.STATUS_CLOSED
        assert CLOSE.isoformat() <= _pub_lagged_asof("2024-04-07", OC.OUTCOME_PUBLICATION_LAG_DAYS)


# ===================================================================================================
# The builder SHELL. It computes nothing -- these pin the parts that are its own: input validation,
# the offline compute path, the rebuild-and-diff gate, and an honest error where the F010 contract
# for this table does not exist yet.
# ===================================================================================================
def _job():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "jobs" / "batch" / "gold_futures_outcomes_task.py"
    spec = importlib.util.spec_from_file_location("gold_futures_outcomes_task_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBuilderJob:

    def _stage(self, tmp_path, tape):
        tape_dir = tmp_path / "tape"
        tape_dir.mkdir()
        tape.to_parquet(tape_dir / "part-000.parquet", index=False)
        anchors = tmp_path / "anchors.json"
        anchors.write_text(
            '[{"leviathan_slug": "corn_cbot", "event_key": "ev1", "event_date": "2024-01-02"}]',
            encoding="utf-8")
        return str(tape_dir), str(anchors)

    def test_an_anchor_without_an_event_date_is_refused_not_defaulted(self, tmp_path):
        job = _job()
        p = tmp_path / "bad.json"
        p.write_text('[{"leviathan_slug": "corn_cbot", "event_key": "ev1"}]', encoding="utf-8")
        with pytest.raises(ValueError, match="event_date"):
            job.load_anchors(str(p))

    def test_the_offline_build_writes_the_registered_partition_layout(self, tmp_path):
        job = _job()
        tape_dir, anchors = self._stage(tmp_path, roll_tape())
        out = tmp_path / "out"
        rc = job.main(["--asof", FAR_ASOF, "--anchors", anchors, "--tape-dir", tape_dir,
                       "--out-dir", str(out), "--publish-mode", "dry-run", "--rebuild-diff"])
        assert rc == 0
        written = sorted(p.as_posix() for p in out.rglob("*.parquet"))
        assert written and "leviathan_slug=corn_cbot/event_year=2024" in written[0]

    def test_a_year_horizon_is_refused_at_the_command_line(self, tmp_path):
        job = _job()
        tape_dir, anchors = self._stage(tmp_path, roll_tape())
        assert job.main(["--asof", FAR_ASOF, "--anchors", anchors, "--tape-dir", tape_dir,
                         "--horizons", "365", "--publish-mode", "dry-run"]) == 2

    def test_an_empty_tape_read_refuses_rather_than_building_nothing(self, tmp_path):
        job = _job()
        tape_dir, anchors = self._stage(tmp_path, cash_tape())     # no corn rows at all
        assert job.main(["--asof", FAR_ASOF, "--anchors", anchors, "--tape-dir", tape_dir,
                         "--publish-mode", "dry-run"]) == 3

    def test_publishing_says_the_f010_contract_does_not_exist_yet(self, tmp_path):
        job = _job()
        if job.CONTRACT_PATH.exists():
            pytest.skip("the F010 contract has landed; the publish path is live")
        with pytest.raises(FileNotFoundError, match="no SILVER-F010 contract"):
            job._load_contract()

    def test_the_census_publishes_pending_beside_closed(self, tmp_path):
        job = _job()
        frame = OC.build_outcomes(
            [{"leviathan_slug": CORN, "event_key": "ev1", "event_date": "2024-03-01"}],
            roll_tape(), asof="2024-04-15", built_at="x")
        census = job.summarize(frame)
        assert census["pending"] > 0 and "closed" in census and census["fingerprint"]


class TestSchemaAuthority:
    """One source for the physical schema. The F010 contract + the generated DDL are derived FROM these
    constants when the table is registered, so a column added to the builder without a type is caught
    here rather than as a live COLUMN_NOT_FOUND (the silver_nasa_power incident's shape)."""

    def test_every_output_column_declares_a_type(self):
        assert set(OC.OUTCOME_COLUMN_TYPES) == set(OC.OUTCOME_COLUMNS)
        assert set(OC.OUTCOME_PARTITION_TYPES) == set(OC.OUTCOME_PARTITIONS)
        assert "leviathan_slug" in OC.OUTCOME_PARTITIONS      # pruned by the ordinary commodity equality
        assert OC.OUTCOME_PARTITION_TYPES["event_year"] == "int"

    def test_the_built_frame_is_exactly_the_declared_columns_plus_the_partition(self):
        frame = OC.build_outcomes(
            [{"leviathan_slug": CORN, "event_key": "ev1", "event_date": ANCHOR}],
            roll_tape(), asof=FAR_ASOF, built_at="x")
        assert list(frame.columns) == list(OC.OUTCOME_COLUMNS) + ["event_year"]

    def test_the_card_names_only_columns_the_builder_writes(self):
        card = OC._read_card()[0]
        declared = set(OC.OUTCOME_COLUMNS) | set(OC.OUTCOME_PARTITIONS)
        for field in ("commodity_col", "period_col", "date_col", "knowledge_date_col", "year_col",
                      "contract_month_col", "settle_kind_col", "currency_col"):
            assert card[field] in declared, f"card.{field}={card[field]!r} is not a written column"
        for metric in card["metrics"]:
            assert metric in declared, f"card metric {metric!r} is not a written column"
