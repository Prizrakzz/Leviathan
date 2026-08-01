"""OUTCOMES_JOIN J5 -- the pattern-records OUTCOME axis (plan items 76-85, D-OJ-11/12, AM-1/AM-3).

WHAT THESE TESTS ARE ABOUT, stated so a later reader does not have to reconstruct it:

  * J5 does NOT fix the firing rate, and the first class of tests exists to keep it honest about that.
    `pr_rate_gate` is ordered, NO_VARIANCE is tested before VINTAGE, and a forward-return column
    changes neither `recorded` nor `evaluable` -- so all six rate suppressions must render exactly as
    they did before this wave. Acceptance leg (v) is "pr_rate_gate output is byte-identical", and it
    is pinned here rather than asserted in prose.
  * The outcome sentence is a SEVENTH suppression-or-statement render with its OWN gate, and its
    failure modes are not the rate's: too few closed horizons (the floor, INHERITED from stats.py),
    too few NON-OVERLAPPING windows behind them (a daily sweep firing for three months re-measures ONE
    stretch of tape ninety times), too large a pending share (the closed half is the OLD half), and
    nothing measurable at all.
  * The PIT clamp is per (event, horizon) and it bites TWICE here: a horizon inside the survive-days
    window at the reader's asof must count PENDING and must not surrender a move (acceptance leg
    (viii)), and a backfill verdict WRITTEN after the asof must be invisible even though its firing
    date is old (the ledger's ingest axis, which no card can compile).
  * Every figure any rendered sentence prints must be a `value` on the injected leg, or the engine's
    own correct sentence wears the false-caution banner -- the D1/D1b class this module already paid
    for once. That is checked by running the real orchestrator verifier over the real rendered line.

AWS-free: the same ANSI SQL serving runs on the pg mirror is exercised against in-memory sqlite, and
the builder's compute path runs against synthetic parquet trees.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3

import pandas as pd
import pytest
from leviathan.graphrag import orchestrator as orc
from leviathan.graphrag.numbers import outcomes as OC
from leviathan.graphrag.numbers import pattern_records as pr
from leviathan.graphrag.numbers import stats as st
from leviathan.silver import futures_eod_contracts as FC

CORN = "corn_cbot"
CASH = "brazilian_arabica_coffee"
DRIVER = "export_pace"
KIND = pr.KIND_PACE
PROV = pr.PROV_DAILY_SWEEP
ASOF = "2026-01-01"
SCOPE = {"contract": CORN, "driver_or_chain_id": DRIVER, "kind": KIND, "provenance": PROV,
         "horizon_days": 30}


# ===================================================================================================
# Fixtures -- an in-memory gold_pattern_outcomes built FROM the module's own schema authority, so a
# column added to the join arrives in these fixtures without a second edit.
# ===================================================================================================
_SQLITE_TYPE = {"string": "TEXT", "timestamp": "TEXT", "int": "INTEGER", "double": "REAL",
                "boolean": "INTEGER"}


def _ddl() -> str:
    cols = ", ".join(f"{c} {_SQLITE_TYPE[pr.po_column_types()[c]]}" for c in pr.po_columns())
    return f"CREATE TABLE {pr.PO_TABLE} ({cols})"


def _row(as_of, *, horizon=30, status="closed", move=1.0, slug=CORN, contract=None,
         written=None, endpoint=None, kind=KIND, provenance=PROV, driver=DRIVER):
    """One outcome row in the builder's own shape. `readable_date` is the endpoint on a closed row and
    the firing date on a pending row -- the definition that lets a guarded read RETURN a pending row
    instead of coming back empty (an empty read renders as a COVERAGE gap, which is the judged-30 RCA
    conflation inverted)."""
    contract = contract or slug
    d = _dt.date.fromisoformat(as_of)
    close = (d + _dt.timedelta(days=horizon)).isoformat()
    end = endpoint or close
    out = {c: None for c in pr.po_columns()}
    out.update({
        "record_kind": kind, "contract": contract, "driver_or_chain_id": driver,
        "provenance": provenance, "as_of_date": as_of, "ledger_written_at": written or as_of,
        "leviathan_slug": slug,
        "event_key": pr.po_anchor_key(kind, contract, driver, provenance, as_of),
        "event_date": as_of, "horizon_days": horizon, "horizon_label": OC.horizon_label(horizon),
        "anchor_date": as_of, "anchor_offset_days": 0, "horizon_close_date": close,
        "contract_month_used": "2024-07", "was_front": None,
        "basis": OC.BASIS_CASH if slug in FC.CASH_INDEX_SLUGS else OC.BASIS_SURVIVOR,
        "currency": "USD", "unit": "US cents/bushel", "settle_kind": "settlement",
        "status": status, "decline_reason": None,
        "rule_version": OC.BASIS_SURVIVOR, "survive_days": OC.SURVIVE_DAYS,
        "tape_edge_date": "2026-07-31", "built_at": "2026-08-01T00:00:00",
    })
    if status == "closed":
        out.update({"readable_date": end, "endpoint_date": end, "px0": 100.0,
                    "px1": 100.0 * (1.0 + move / 100.0), "move_abs": move, "move_pct": move,
                    "realized_offset_days": 0, "realized_sessions": 21, "endpoint_dow": "Fri"})
    elif status == "pending":
        out["readable_date"] = as_of
    else:
        out.update({"readable_date": as_of, "decline_reason": OC.DECLINE_PRE_COVERAGE})
    return out


def _conn(rows):
    c = sqlite3.connect(":memory:")
    c.execute(_ddl())
    cols = list(pr.po_columns())
    c.executemany(f"INSERT INTO {pr.PO_TABLE} VALUES (" + ",".join(["?"] * len(cols)) + ")",
                  [tuple(r[k] for k in cols) for r in rows])
    c.commit()
    return c


def _qfn(conn, seen=None):
    def run(sql: str):
        if seen is not None:
            seen.append(sql)
        cur = conn.execute(sql)
        cols = [x[0] for x in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    return run


def _spaced(n: int, *, step: int = 40, start: str = "2024-01-03", horizon: int = 30,
            moves=None, **kw) -> list:
    """n firings spaced `step` days apart -- wide enough that each horizon window stands alone."""
    d0 = _dt.date.fromisoformat(start)
    return [_row((d0 + _dt.timedelta(days=step * i)).isoformat(), horizon=horizon,
                 move=(moves[i] if moves else float(i) - 3.5), **kw) for i in range(n)]


def _serve(rows, scope=None, asof=ASOF, seen=None):
    scope = scope or SCOPE
    legs, sig = pr.pattern_outcome_legs(scope, asof, _qfn(_conn(rows), seen))
    line = pr.pattern_outcome_answer(scope, (1, legs[0]) if legs else None, sig, asof=asof)
    return legs, sig, line


def _grounded(line, legs) -> dict:
    """The REAL verifier the serving lane runs: every figure a rendered line states must match a row
    `value` on some injected call, or the deterministic engine sentence wears the caution banner."""
    return orc._verify_numbers_answer(line or "", legs or [])


# ===================================================================================================
# (1) J5 CHANGES NOTHING ON THE RATE SIDE. Acceptance leg (v).
# ===================================================================================================
class TestTheRateSideIsUntouched:

    def test_the_three_live_pair_shapes_still_suppress_with_the_same_slugs(self):
        # The re-censused ledger: (158,158) x163 cascade, (0,0) x79 cascade, (11,11) x9 pace. A
        # forward-return column changes neither `recorded` nor `evaluable`, so every one of these is
        # exactly the verdict it was before J5 (D-OJ-12).
        assert pr.pr_rate_gate(in_catalog=True, recorded=158, evaluable=158,
                               vintage_depth=99) == pr.PR_SUP_NO_VARIANCE
        assert pr.pr_rate_gate(in_catalog=True, recorded=0, evaluable=0,
                               vintage_depth=99) == pr.PR_SUP_NOTHING_EVALUABLE
        assert pr.pr_rate_gate(in_catalog=True, recorded=11, evaluable=11,
                               vintage_depth=99) == pr.PR_SUP_TOO_THIN

    def test_the_flagship_pace_sentence_is_byte_identical(self):
        """Pinned from the pre-J5 module. The outcome axis is a SECOND sentence; if it ever moves this
        one, it has silently changed an answer it was never supposed to touch."""
        legs = [{"rows": [{"value": 11, "sweeps_total": 158, "first_recorded": "2026-05-18",
                           "last_recorded": "2026-07-27", "first_evaluable": "2026-05-18",
                           "last_evaluable": "2026-07-27"}]}]
        signal = {"recorded_firings": 11, "sweeps_total": 158, "sweeps_evaluable": 11,
                  "in_catalog": True, "provenance": pr.PROV_BACKFILL_GRID, "vintage_depth": None}
        line = pr.pattern_records_answer(
            {"contract": CORN, "driver_or_chain_id": DRIVER}, (1, legs[0]), signal)
        assert line == (
            "For export_pace on corn_cbot, the engine has recorded 11 firings, 2026-05-18 to "
            "2026-07-27 [N1]. Only 11 of the 158 attempted weekly replay asofs carried data it could "
            "evaluate, which is too short a recorded history to state a firing rate.")

    def test_the_outcome_axis_shares_the_too_thin_slug_rather_than_minting_a_second_one(self):
        # AM-3: one floor-constant family with pattern-records `too_thin`. A second slug for the same
        # fact about the same constant would split one fact across two vocabularies.
        assert pr.PO_SUP_TOO_THIN is pr.PR_SUP_TOO_THIN
        assert pr.po_min_closed() == st.MIN_QUANTILE_N == st.MIN_PERCENTILE_N

    def test_the_outcome_detector_never_fires_on_a_ledger_question(self):
        q = "how many times has export pace fired on corn?"
        assert pr.pattern_records_scope(q) is not None        # still a ledger question
        assert pr.pattern_outcome_scope(q) is None            # and NOT an outcome question


# ===================================================================================================
# (2) THE GATE: its order, and that an unknown independence count suppresses.
# ===================================================================================================
class TestTheOutcomeGate:

    def test_nothing_joined_outranks_everything(self):
        assert pr.po_outcome_gate(joined=0, n_closed=0, n_pending=0, n_declined=0,
                                  n_independent=99) == pr.PO_SUP_NOT_JOINED

    def test_all_declined_reads_as_a_coverage_gap_not_as_a_pending_horizon(self):
        assert pr.po_outcome_gate(joined=12, n_closed=0, n_pending=0, n_declined=12,
                                  n_independent=99) == pr.PO_SUP_UNMEASURABLE

    def test_all_pending_is_its_own_fact(self):
        assert pr.po_outcome_gate(joined=12, n_closed=0, n_pending=12, n_declined=0,
                                  n_independent=99) == pr.PO_SUP_ALL_PENDING

    def test_the_floor_is_tested_before_independence_because_shortness_is_more_informative(self):
        thin = pr.po_min_closed() - 1
        assert pr.po_outcome_gate(joined=thin, n_closed=thin, n_pending=0, n_declined=0,
                                  n_independent=1) == pr.PO_SUP_TOO_THIN

    def test_an_unestablished_independence_count_suppresses(self):
        # The 9-of-156 defect in another costume: an unknown denominator is not a permissive one.
        n = pr.po_min_closed()
        assert pr.po_outcome_gate(joined=n, n_closed=n, n_pending=0, n_declined=0,
                                  n_independent=None) == pr.PO_SUP_OVERLAP

    def test_a_majority_pending_share_suppresses_because_the_closed_half_is_the_old_half(self):
        n = pr.po_min_closed()
        assert pr.po_outcome_gate(joined=3 * n, n_closed=n, n_pending=2 * n, n_declined=0,
                                  n_independent=n) == pr.PO_SUP_PENDING_HEAVY

    def test_everything_clear_states_the_distribution(self):
        n = pr.po_min_closed()
        assert pr.po_outcome_gate(joined=n, n_closed=n, n_pending=0, n_declined=0,
                                  n_independent=n) is None


class TestIndependentWindows:

    def test_daily_firings_of_one_condition_are_one_window_not_ninety(self):
        d0 = _dt.date(2024, 1, 1)
        daily = [(d0 + _dt.timedelta(days=i)).isoformat() for i in range(90)]
        assert pr.independent_windows(daily, 90) == 1
        assert pr.independent_windows(daily, 30) == 3

    def test_widely_spaced_firings_each_stand_alone(self):
        d0 = _dt.date(2024, 1, 1)
        spaced = [(d0 + _dt.timedelta(days=40 * i)).isoformat() for i in range(8)]
        assert pr.independent_windows(spaced, 30) == 8

    def test_an_unreadable_date_is_dropped_rather_than_counted(self):
        assert pr.independent_windows(["not-a-date", None, "2024-01-01"], 30) == 1


# ===================================================================================================
# (3) THE PIT CLAMP -- per (event, horizon), on BOTH axes, and it never surrenders a move.
# ===================================================================================================
class TestThePitClamp:

    def test_the_compiled_boundary_is_the_joins_own_arithmetic(self):
        # survive_days(5) + tape lag(1). Not this module's number: it is imported, and the card lint
        # pins the same equality on the served card.
        assert pr.po_readable_asof("2026-01-11") == "2026-01-05"
        assert OC.OUTCOME_PUBLICATION_LAG_DAYS == OC.SURVIVE_DAYS + OC.TAPE_PUBLICATION_LAG_DAYS

    def test_a_read_inside_the_survive_window_returns_pending_not_a_number(self):
        """Acceptance leg (viii), the sharpest single test that the boundary is COMPILED rather than
        written down. The row was materialized `closed` by a later build; read at endpoint + 3 days it
        must count pending, and its move must not leave the database."""
        rows = _spaced(10, moves=[1.0] * 10)
        endpoint = _dt.date.fromisoformat(rows[-1]["endpoint_date"])
        asof = (endpoint + _dt.timedelta(days=3)).isoformat()
        conn = _conn(rows)
        census = _qfn(conn)(pr.po_census_sql(CORN, DRIVER, kind=KIND, asof=asof, horizon_days=30,
                                             provenance=PROV))[0]
        assert census["joined"] == 10
        assert census["n_pending"] >= 1                      # the newest one has not cleared it
        assert census["n_closed"] == 10 - census["n_pending"]
        values = _qfn(conn)(pr.po_values_sql(CORN, DRIVER, kind=KIND, asof=asof, horizon_days=30,
                                             provenance=PROV))
        assert all(v["endpoint_date"] <= pr.po_readable_asof(asof) for v in values)

    def test_a_pending_row_is_counted_never_dropped(self):
        # Dropping pending firings biases every summary toward OLD firings -- survivorship in the
        # denominator (item 49). The census counts them and the leg publishes the count.
        rows = _spaced(6) + [_row("2025-12-20", status="pending")]
        _legs, sig, _line = _serve(rows)
        assert sig["joined"] == 7 and sig["n_pending"] == 1

    def test_a_verdict_written_after_the_asof_is_invisible(self):
        """The ledger's INGEST axis, which no TableSpec can compile: a backfill verdict for a 2023
        as-of was WRITTEN in 2026, and a row guarded only on the firing date would be readable at an
        as-of at which the verdict did not exist."""
        rows = _spaced(10, written="2026-06-01")
        _legs, sig, _line = _serve(rows, asof="2025-06-01")
        assert sig["joined"] == 0 and sig["outcome_suppressed"] == pr.PO_SUP_NOT_JOINED

    def test_the_values_read_can_never_return_a_move_past_the_boundary(self):
        rows = _spaced(10)
        sql = pr.po_values_sql(CORN, DRIVER, kind=KIND, asof=ASOF, horizon_days=30, provenance=PROV)
        assert OC.evaluable_pred("status") in sql
        assert f"<= '{pr.po_readable_asof(ASOF)}'" in sql
        assert "ledger_written_at" in sql and "as_of_date" in sql

    def test_an_unparseable_asof_admits_nothing(self):
        assert pr.po_readable_asof("not-a-date") == ""
        _legs, sig, _line = _serve(_spaced(10), asof="not-a-date")
        assert sig["n_closed"] == 0


# ===================================================================================================
# (4) THE FLOORS ARE INHERITED, AND A SUPPRESSED DISTRIBUTION SHIPS NO NUMBERS.
# ===================================================================================================
class TestFloorsInherited:

    def test_one_below_the_floor_declines_and_carries_counts_only(self):
        rows = _spaced(pr.po_min_closed() - 1)
        legs, sig, line = _serve(rows)
        assert sig["outcome_suppressed"] == pr.PO_SUP_TOO_THIN
        assert sig["median"] is None
        measures = {r["measure"] for r in legs[0]["rows"]}
        assert measures == {"closed_firings", "pending_firings", "joined_firings",
                            "unmeasurable_firings"}
        assert "median" not in (line or "")

    def test_at_the_floor_it_states_a_distribution_with_a_spread_beside_the_centre(self):
        rows = _spaced(pr.po_min_closed())
        legs, sig, line = _serve(rows)
        assert sig["outcome_suppressed"] is None and sig["outcome_stated"] is True
        measures = [r["measure"] for r in legs[0]["rows"]]
        assert measures[0] == "move_pct_median"             # the citation headlines the move
        assert "move_pct_p10" in measures and "move_pct_p90" in measures
        assert "median" in line and "decile" in line

    def test_the_distribution_is_the_calculators_and_not_a_local_reimplementation(self):
        rows = _spaced(10, moves=[float(i) for i in range(10)])
        _legs, sig, _line = _serve(rows)
        want = st.quantiles([float(i) for i in range(10)], pr.PO_PROBS)
        assert sig["median"] == pytest.approx(round(want["quantiles"]["0.5"], pr.PO_ROUND_PCT))
        assert sig["p10"] == pytest.approx(round(want["quantiles"]["0.1"], pr.PO_ROUND_PCT))

    def test_the_values_probe_is_lazy_so_a_suppressed_pair_costs_one_query(self):
        seen = []
        _serve(_spaced(3), seen=seen)
        assert len(seen) == 1 and "COUNT(*)" in seen[0]
        seen2 = []
        _serve(_spaced(pr.po_min_closed()), seen=seen2)
        assert len(seen2) == 2


# ===================================================================================================
# (5) OVERLAP, PENDING SHARE, AND THE COVERAGE-VS-TIMING DISTINCTION.
# ===================================================================================================
class TestSuppressionBranches:

    def test_ninety_daily_firings_are_refused_as_overlapping_windows(self):
        d0 = _dt.date(2024, 1, 3)
        rows = [_row((d0 + _dt.timedelta(days=i)).isoformat(), horizon=90, move=float(i % 7) - 3)
                for i in range(90)]
        scope = {**SCOPE, "horizon_days": 90}
        _legs, sig, line = _serve(rows, scope=scope)
        assert sig["outcome_suppressed"] == pr.PO_SUP_OVERLAP
        # 90 consecutive daily firings span 89 days, so they stand on exactly ONE 90-day window --
        # ninety rows of evidence for one observation.
        assert sig["n_closed"] == 90 and sig["n_independent"] == 1
        assert "non-overlapping" in line and "same stretch of tape" in line

    def test_a_mostly_pending_pair_states_the_bias_rather_than_the_distribution(self):
        rows = _spaced(8) + [_row((_dt.date(2025, 12, 1) + _dt.timedelta(days=i)).isoformat(),
                                  status="pending") for i in range(12)]
        _legs, sig, line = _serve(rows)
        assert sig["outcome_suppressed"] == pr.PO_SUP_PENDING_HEAVY
        assert "oldest firings only" in line

    def test_all_declined_says_coverage_gap_and_all_pending_says_timing(self):
        declined = [_row(f"2024-0{i + 1}-03", status="declined_pre_coverage") for i in range(6)]
        _legs, sig_d, line_d = _serve(declined)
        assert sig_d["outcome_suppressed"] == pr.PO_SUP_UNMEASURABLE
        assert "coverage gap, not a zero move" in line_d

        pend = [_row("2025-12-2%d" % i, status="pending") for i in range(1, 7)]
        _legs, sig_p, line_p = _serve(pend)
        assert sig_p["outcome_suppressed"] == pr.PO_SUP_ALL_PENDING
        assert "has not closed yet" in line_d or "open" in line_p
        assert "coverage" not in line_p                      # a timing fact is never a coverage claim

    def test_a_pair_with_no_joined_row_cites_a_materialized_zero(self):
        legs, sig, line = _serve(_spaced(4, driver="other_driver"))
        assert sig["outcome_suppressed"] == pr.PO_SUP_NOT_JOINED
        assert legs[0]["rows"][0]["value"] == 0 and "0" in line

    def test_an_outlook_turn_does_not_reach_this_axis_at_all(self):
        """D-OJ-17 option (a), applied to J5 -- the gate J6 has and this leg did not.

        The statement branch ships a median, a decile spread and "N of them closed higher": a CITED,
        ARROW-FREE CONDITIONAL PERFORMANCE sentence. Under OUTLOOK `register.py` puts `_FLOW_PHRASES`,
        `_VALUATION_PHRASES`, `_PERSISTENCE` and both Lane-B arms inside `if not outlook:`, so exactly
        that sentence returns False from `_is_banned_sentence` and ships as a setup (item 90b). J6's
        three remedies do not reach here: `gold_pattern_outcomes` is correctly NOT in
        POSITIONING_TABLES, so `quantify`'s node-drop never touches this leg. The gate is at the leg."""
        rows = _spaced(8)
        legs, sig, line = _serve(rows)                       # the fenced turn: a real distribution
        assert sig["outcome_stated"] and "median" in line and "closed higher" in line
        seen: list = []
        o_legs, o_sig = pr.pattern_outcome_legs(SCOPE, ASOF, _qfn(_conn(rows), seen), outlook=True)
        assert o_legs == [] and seen == []                   # no leg, no [N] handle, and NO READ
        assert o_sig["outcome_suppressed"] == pr.PO_SUP_OUTLOOK_HELD
        assert pr.pattern_outcome_answer(SCOPE, None, o_sig, asof=ASOF) is None   # and no sentence
        assert pr.PO_SUP_OUTLOOK_HELD in pr.PO_SUPPRESSIONS


# ===================================================================================================
# (6) THE JOIN KEY HAZARD (item 81) AND THE LEAKAGE FENCE.
# ===================================================================================================
class TestSlugResolution:

    def test_a_graph_node_never_resolves_to_a_tape_slug(self):
        # The live ledger carries BOTH (corn, export_pace) and (corn_cbot, export_pace). `corn` could
        # as honestly be MATIF maize or the Campinas cash reference; guessing puts one exchange's move
        # under another's question.
        assert pr.po_resolve_slug("corn") is None
        assert pr.po_resolve_slug(CORN) == CORN
        assert pr.po_resolve_slug(CASH) == CASH

    def test_the_unresolved_pair_renders_its_own_sentence_and_injects_nothing(self):
        legs, sig, line = _serve([], scope={**SCOPE, "contract": "corn"})
        assert legs == [] and sig["outcome_suppressed"] == pr.PO_SUP_SLUG_UNRESOLVED
        assert "graph node" in line and "[N" not in line

    def test_the_anchor_builder_reconciles_resolved_plus_skipped(self):
        rows = [
            {"record_kind": KIND, "contract": CORN, "driver_or_chain_id": DRIVER,
             "provenance": PROV, "as_of_date": "2026-01-05", "verdict": "fired",
             "written_at": "2026-01-05"},
            {"record_kind": KIND, "contract": "corn", "driver_or_chain_id": DRIVER,
             "provenance": PROV, "as_of_date": "2026-01-05", "verdict": "fired",
             "written_at": "2026-01-05"},
            {"record_kind": KIND, "contract": CORN, "driver_or_chain_id": DRIVER,
             "provenance": PROV, "as_of_date": "2026-01-12", "verdict": "declined",
             "decline_reason": "fetch_error", "written_at": "2026-01-12"},
            {"record_kind": pr.KIND_CASCADE, "contract": CORN, "driver_or_chain_id": "psd_stocks",
             "provenance": pr.PROV_BACKFILL_GRID, "as_of_date": "2024-01-05", "verdict": "fired",
             "written_at": "2026-01-05"},
        ]
        got = pr.po_ledger_anchors(rows)
        assert len(got["anchors"]) == 1
        assert len(got["anchors"]) + got["skipped"] == len(rows)
        assert got["skipped_by_reason"] == {"fenced_leaky_asof": 1, "not_a_firing": 1,
                                            "slug_unresolved": 1}

    def test_the_fence_outranks_the_horizon_because_it_is_a_fact_about_the_data(self):
        # A fenced pair has no citable outcome at ANY horizon. Answering "that horizon is unsupported"
        # would name the smaller of two reasons and imply the bigger one away.
        scope = {**SCOPE, "kind": pr.KIND_CASCADE, "provenance": pr.PROV_BACKFILL_GRID,
                 "horizon_days": 365}
        _legs, sig, line = _serve([], scope=scope)
        assert sig["fenced"] == "cascade_backfill_leaky_asof"
        assert sig["outcome_suppressed"] != pr.PO_SUP_UNSUPPORTED_HORIZON
        assert "synthesized" in line

    def test_a_leaked_verdict_is_never_joined_to_price(self):
        # cascade x backfill_grid replays against a SYNTHESIZED as-of axis. The fence is applied at the
        # builder AND at the read seam: two locks on the same door.
        assert pr.pr_read_fenced(pr.KIND_CASCADE, pr.PROV_BACKFILL_GRID)
        scope = {**SCOPE, "kind": pr.KIND_CASCADE, "provenance": pr.PROV_BACKFILL_GRID}
        legs, sig, line = _serve([], scope=scope)
        assert legs == [] and sig["fenced"] == "cascade_backfill_leaky_asof"
        assert "synthesized" in line


# ===================================================================================================
# (7) AM-1: the horizon family, and the year that does not exist under this basis.
# ===================================================================================================
class TestHorizonFamily:

    def test_the_family_is_a_subset_of_the_joins_own(self):
        assert set(pr.PO_HORIZONS) <= set(OC.HORIZON_DAYS)
        assert 365 not in pr.PO_HORIZONS and 5 not in pr.PO_HORIZONS

    def test_a_year_ask_renders_the_exclusion_and_is_never_rounded_to_the_quarter(self):
        scope = {**SCOPE, "horizon_days": 365}
        legs, sig, line = _serve([], scope=scope)
        assert legs == [] and sig["outcome_suppressed"] == pr.PO_SUP_UNSUPPORTED_HORIZON
        assert "one-year" in line and "splice" in line
        assert not any(ch.isdigit() for ch in line)          # a figure-free refusal needs no [N] row

    def test_the_detector_routes_a_year_question_to_that_refusal(self):
        scope = pr.pattern_outcome_scope(
            "what did corn prices do in the year after export pace fired?")
        assert scope["horizon_days"] == 365

    def test_each_family_member_is_detected_by_its_own_desk_vocabulary(self):
        base = "what did corn prices do after export pace fired over the next %s?"
        assert pr.pattern_outcome_scope(base % "month")["horizon_days"] == 30
        assert pr.pattern_outcome_scope(base % "two months")["horizon_days"] == 60
        assert pr.pattern_outcome_scope(base % "quarter")["horizon_days"] == 90


# ===================================================================================================
# (8) THE RENDER: grounded figures, bound `shown`, observation register.
# ===================================================================================================
def _all_branches() -> dict:
    """One fixture per rendered branch, so the properties below are checked on ALL of them rather than
    on the happy path."""
    return {
        "stated": (_spaced(pr.po_min_closed()), SCOPE),
        "too_thin": (_spaced(3), SCOPE),
        "overlap": ([_row((_dt.date(2024, 1, 3) + _dt.timedelta(days=i)).isoformat(), horizon=90,
                          move=float(i % 5) - 2) for i in range(90)], {**SCOPE, "horizon_days": 90}),
        "pending_heavy": (_spaced(8) + [_row("2025-12-%02d" % (i + 1), status="pending")
                                        for i in range(12)], SCOPE),
        "all_pending": ([_row("2025-12-2%d" % i, status="pending") for i in range(1, 7)], SCOPE),
        "unmeasurable": ([_row("2024-0%d-03" % (i + 1), status="declined_pre_coverage")
                          for i in range(6)], SCOPE),
        "not_joined": ([], SCOPE),
    }


class TestTheRenderedLine:

    def test_every_stated_figure_is_a_row_value_on_every_branch(self):
        """The D1/D1b false-caution class: `orchestrator._verify_numbers_answer` grounds a stated
        number only against row `value`s, so an engine sentence whose own figures are ungrounded fires
        the caution banner on a correct answer."""
        for name, (rows, scope) in _all_branches().items():
            legs, _sig, line = _serve(rows, scope=scope)
            nv = _grounded(line, legs)
            assert nv["mismatched"] == 0, (name, line, nv)

    def test_the_line_binds_what_it_printed_as_shown(self):
        for name, (rows, scope) in _all_branches().items():
            legs, _sig, line = _serve(rows, scope=scope)
            if not legs:
                continue
            shown = legs[0].get("shown") or []
            assert shown, name
            # every bound magnitude appears in the rendered text, and nothing else is bound
            for v in shown:
                token = str(int(v)) if float(v).is_integer() else f"{v:+.1f}"
                assert token in line or f"{v:+.1f}" in line, (name, v, line)

    def test_no_branch_leaks_the_observation_register(self):
        for name, (rows, scope) in _all_branches().items():
            _legs, _sig, line = _serve(rows, scope=scope)
            assert pr.pr_register_leaks(line or "") == [], (name, line)

    def test_the_leg_carries_the_series_a_tag_would_name(self):
        """`cascade._series_tag` builds its segments from the call's own query dict, so a leg that does
        not carry the SERIES cannot be tagged with it -- and an untagged outcome row is exactly the
        scope mis-attribution the tag was built to stop."""
        legs, _sig, _line = _serve(_spaced(pr.po_min_closed()))
        q = legs[0]["query"]
        assert q["commodity"] == CORN and q["table"] == pr.PO_TABLE
        assert q["horizon_days"] == 30 and q["provenance"] == PROV

    def test_the_statement_names_the_basis_the_move_was_measured_on(self):
        _legs, _sig, line = _serve(_spaced(pr.po_min_closed()))
        assert "single delivery month" in line and "roll splice" in line

    def test_the_cash_basis_says_it_has_no_delivery_month_rather_than_claiming_one(self):
        rows = _spaced(pr.po_min_closed(), slug=CASH, contract=CASH)
        scope = {**SCOPE, "contract": CASH}
        _legs, sig, line = _serve(rows, scope=scope)
        assert sig["basis"] == OC.BASIS_CASH
        assert "no delivery month" in line

    def test_a_pending_count_rides_the_statement_with_its_close_date(self):
        rows = _spaced(pr.po_min_closed()) + [_row("2025-12-20", status="pending")]
        _legs, sig, line = _serve(rows)
        assert sig["outcome_suppressed"] is None
        assert "has not closed yet" in line and sig["first_pending_close"] in line

    def test_the_statement_refuses_to_wear_the_grammar_of_a_rate_or_a_forecast(self):
        _legs, _sig, line = _serve(_spaced(pr.po_min_closed()))
        assert "neither a firing rate nor a statement about the next one" in line
        assert "forecast" not in line and "expect" not in line


# ===================================================================================================
# (9) THE SCHEMA + THE CARD.
# ===================================================================================================
class TestSchemaAuthority:

    def test_every_column_declares_a_type_and_the_join_half_is_not_re_declared(self):
        assert set(pr.po_column_types()) == set(pr.po_columns())
        assert set(OC.OUTCOME_COLUMNS) < set(pr.po_columns())
        assert set(pr.PO_PARTITION_TYPES) == set(pr.PO_PARTITIONS)
        assert pr.PO_PARTITION_TYPES["as_of_year"] == "int"

    def test_the_staged_card_is_coherent_with_the_module(self):
        assert pr.lint_pattern_outcome_card() == []

    def test_the_card_lint_is_BOUND_INTO_THE_BUILD_not_merely_defined(self):
        # A lint nothing runs is a comment. `check_futures_outcomes` was bound in config_check.main()
        # and its twin here was not, so a drifted publication_lag on THIS card -- the half of the PIT
        # boundary that compiles into SQL -- would have shipped green (adversarial finding 14).
        from leviathan.graphrag import config_check as cc
        assert cc.check_pattern_outcomes() == []
        real = pr.lint_pattern_outcome_card
        try:                                   # the binding is real: an error reaches the build label
            pr.lint_pattern_outcome_card = lambda card=None: ["publication_lag_days drifted"]
            errs = cc.check_pattern_outcomes()
            assert errs and errs[0].startswith("pattern_outcomes: ")
        finally:
            pr.lint_pattern_outcome_card = real
        # ... and it is VACUOUS where no card exists at all, like every sibling check: the configs are
        # gitignored, so a hard error there would make a fresh clone red on an untracked file.
        real_read = pr._po_read_card
        try:
            pr._po_read_card = lambda: (None, "none")
            assert cc.check_pattern_outcomes() == []
        finally:
            pr._po_read_card = real_read

    def test_the_card_is_STAGED_and_not_yet_served(self):
        """It must not reach the agent tool enum before its second PIT axis has somewhere to compile:
        a registry-composed lookup would guard the horizon close and ignore when the VERDICT became
        knowable. When it is pasted into tables.yaml it goes into WHITELIST_ABSENT_DEFAULT in the same
        change -- the staged card's header carries that recipe."""
        assert pr._po_read_card()[1] == "staged"

    def test_a_forward_looking_metric_name_is_refused_on_the_card(self):
        errs = pr.lint_pattern_outcome_card({**pr.PO_CARD_FIELDS,
                                             "publication_lag_days": OC.OUTCOME_PUBLICATION_LAG_DAYS,
                                             "partitions": list(pr.PO_PARTITIONS),
                                             "metrics": {"move_pct": {}, "move_abs": {},
                                                         "move_forecast": {}}})
        assert any("forward-looking ban" in e for e in errs)

    def test_a_drifted_publication_lag_is_caught_because_it_IS_the_clamp(self):
        errs = pr.lint_pattern_outcome_card({**pr.PO_CARD_FIELDS, "publication_lag_days": 1,
                                             "partitions": list(pr.PO_PARTITIONS),
                                             "metrics": {"move_pct": {}, "move_abs": {}}})
        assert any("publication_lag_days" in e for e in errs)


class TestRowInvariants:

    def _built(self, **kw):
        row = _row("2024-03-01", **kw)
        return row

    def test_a_clean_row_passes(self):
        assert pr.lint_pattern_outcome_rows([self._built()]) == []

    def test_a_row_whose_key_does_not_trace_back_to_a_verdict_is_refused(self):
        row = self._built()
        row["event_key"] = "made-up"
        assert any("event_key" in e for e in pr.lint_pattern_outcome_rows([row]))

    def test_a_row_missing_the_ledger_ingest_stamp_is_refused(self):
        row = self._built()
        row["ledger_written_at"] = None
        assert any("ledger_written_at" in e for e in pr.lint_pattern_outcome_rows([row]))

    def test_a_row_built_from_a_fenced_verdict_is_refused(self):
        row = self._built(kind=pr.KIND_CASCADE, provenance=pr.PROV_BACKFILL_GRID)
        assert any("FENCED" in e for e in pr.lint_pattern_outcome_rows([row]))

    def test_a_pending_row_carrying_a_move_is_refused_by_the_joins_own_lint(self):
        row = self._built(status="pending")
        row["move_pct"] = 3.0
        assert pr.lint_pattern_outcome_rows([row])

    def test_the_reconcile_identity_names_its_third_term(self):
        rows = [_row("2024-01-03"), _row("2024-02-03", status="pending"),
                _row("2024-03-03", status="declined_pre_coverage")]
        census = pr.po_reconcile(rows)
        assert census["n_closed"] + census["n_pending"] + census["n_declined"] == census["n_firings"]


# ===================================================================================================
# (10) THE BUILDER SHELL. It computes nothing -- these pin what IS its own: the ledger read, the
# resolve-or-skip reconcile, the offline build, rebuild-and-diff, and an honest publish refusal.
# ===================================================================================================
def _job():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "jobs" / "batch" / "gold_pattern_outcomes_task.py"
    spec = importlib.util.spec_from_file_location("gold_pattern_outcomes_task_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tape(slug=CORN, start="2023-11-01", end="2025-06-30"):
    days = pd.bdate_range(start, end)
    rec = FC.CONTRACT_MAP[slug]
    frames = []
    for i, month in enumerate(("2024-07", "2024-12", "2025-07")):
        frames.append(pd.DataFrame({
            "leviathan_slug": [slug] * len(days), "trade_date": days,
            "contract_month": [month] * len(days),
            "settle": [400.0 + 10.0 * i + 0.25 * k for k in range(len(days))],
            "unit": [rec["unit"]] * len(days), "currency": [rec["currency"]] * len(days),
            "settle_kind": [rec["settle_kind"]] * len(days),
            "open_interest": [None] * len(days), "volume": [None] * len(days),
            "instrument_kind": ["futures"] * len(days),
        }))
    return pd.concat(frames, ignore_index=True)


def _ledger(n=6, *, contract=CORN, start="2024-01-03", step=40):
    d0 = _dt.date.fromisoformat(start)
    return pd.DataFrame([{
        "record_kind": KIND, "contract": contract, "driver_or_chain_id": DRIVER,
        "provenance": PROV, "as_of_date": (d0 + _dt.timedelta(days=step * i)).isoformat(),
        "verdict": "fired", "decline_reason": None, "written_at": "2024-01-01",
    } for i in range(n)])


class TestBuilderJob:

    def _stage(self, tmp_path, ledger=None, tape=None):
        ld = tmp_path / "ledger"
        ld.mkdir()
        (ledger if ledger is not None else _ledger()).to_parquet(ld / "part-000.parquet", index=False)
        td = tmp_path / "tape"
        td.mkdir()
        (tape if tape is not None else _tape()).to_parquet(td / "part-000.parquet", index=False)
        return str(ld), str(td)

    def test_the_offline_build_writes_the_registered_partition_layout(self, tmp_path):
        job = _job()
        ld, td = self._stage(tmp_path)
        out = tmp_path / "out"
        rc = job.main(["--asof", "2026-01-01", "--ledger-dir", ld, "--tape-dir", td,
                       "--out-dir", str(out), "--publish-mode", "dry-run", "--rebuild-diff"])
        assert rc == 0
        written = sorted(p.as_posix() for p in out.rglob("*.parquet"))
        assert written and "leviathan_slug=corn_cbot/as_of_year=2024" in written[0]

    def test_the_built_frame_carries_the_ledger_key_and_passes_the_row_lint(self, tmp_path):
        job = _job()
        frame, resolved = job.build(_ledger(), _tape(), asof="2026-01-01", built_at="x",
                                    horizons=pr.PO_HORIZONS)
        assert list(frame.columns) == list(pr.po_columns()) + ["as_of_year"]
        assert len(frame) == 6 * len(pr.PO_HORIZONS)
        assert pr.lint_pattern_outcome_rows(frame.to_dict("records")) == []
        assert resolved["skipped"] == 0
        census = job.summarize(frame, resolved)
        assert census["closed"] > 0
        assert census["closed"] + census["pending"] + census["declined"] == census["rows"]

    def test_node_named_contracts_are_skipped_counted_and_reconciled(self, tmp_path):
        job = _job()
        ledger = pd.concat([_ledger(3), _ledger(3, contract="corn")], ignore_index=True)
        frame, resolved = job.build(ledger, _tape(), asof="2026-01-01", built_at="x",
                                    horizons=pr.PO_HORIZONS)
        assert resolved["skipped"] == 3 and resolved["skipped_by_reason"]["slug_unresolved"] == 3
        assert len(frame) == 3 * len(pr.PO_HORIZONS)
        census = job.summarize(frame, resolved)
        assert census["anchors_resolved"] + census["anchors_skipped"] == len(ledger)

    def test_a_ledger_that_resolves_to_nothing_refuses_rather_than_building_empty(self, tmp_path):
        job = _job()
        ld, td = self._stage(tmp_path, ledger=_ledger(4, contract="corn"))
        assert job.main(["--asof", "2026-01-01", "--ledger-dir", ld, "--tape-dir", td,
                         "--publish-mode", "dry-run"]) == 3

    def test_an_empty_ledger_read_refuses(self, tmp_path):
        job = _job()
        ld = tmp_path / "ledger"
        ld.mkdir()
        _ledger(0).to_parquet(ld / "part-000.parquet", index=False)
        td = tmp_path / "tape"
        td.mkdir()
        _tape().to_parquet(td / "part-000.parquet", index=False)
        assert job.main(["--asof", "2026-01-01", "--ledger-dir", str(ld), "--tape-dir", str(td),
                         "--publish-mode", "dry-run"]) == 3

    def test_a_year_horizon_is_refused_at_the_command_line(self, tmp_path):
        job = _job()
        ld, td = self._stage(tmp_path)
        assert job.main(["--asof", "2026-01-01", "--ledger-dir", ld, "--tape-dir", td,
                         "--horizons", "365", "--publish-mode", "dry-run"]) == 2

    def test_the_shadow_copies_are_never_counted_twice(self, tmp_path):
        job = _job()
        ld = tmp_path / "ledger"
        (ld / "_shadow").mkdir(parents=True)
        _ledger(6).to_parquet(ld / "part-000.parquet", index=False)
        _ledger(6).to_parquet(ld / "_shadow" / "part-000.parquet", index=False)
        assert len(job.read_ledger_local(str(ld))) == 6

    def test_two_builds_at_the_same_tape_edge_are_byte_identical(self, tmp_path):
        job = _job()
        a, _r = job.build(_ledger(), _tape(), asof="2026-01-01", built_at="A",
                          horizons=pr.PO_HORIZONS)
        b, _r2 = job.build(_ledger(), _tape(), asof="2026-01-01", built_at="B",
                           horizons=pr.PO_HORIZONS)
        assert OC.outcomes_fingerprint(a) == OC.outcomes_fingerprint(b)

    def test_publishing_says_the_f010_contract_does_not_exist_yet(self):
        job = _job()
        if job.CONTRACT_PATH.exists():
            pytest.skip("the F010 contract has landed; the publish path is live")
        with pytest.raises(FileNotFoundError, match="no SILVER-F010 contract"):
            job._load_contract()

    def test_the_join_never_sees_the_measurement_the_verdict_was_made_from(self):
        job = _job()
        for col in ("streak_len", "window_change", "n_points", "n_rows", "n_hops"):
            assert col not in job.LEDGER_COLUMNS
