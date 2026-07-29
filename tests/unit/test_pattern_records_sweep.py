"""T2B pattern-records ledger core: the write-guard, provenance separation, idempotency, backfill
eligibility, pace decline re-derivation, and the chain-kind record from a quantify_chain fixture.

These exercise the PURE record-construction + guard + eligibility surface (fed engine trace entries /
fixtures) -- the pg-driven live sweep is validated at the rollout day-0 gate, not here. AWS-free.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pyarrow.parquet as pq
import pytest

import jobs.batch.pattern_records_sweep_task as prs
from leviathan.graphrag.numbers import cascade as casc
from leviathan.silver.registry import load_registry


# a canonical fired-pace quantify_pace entry (cascade._pace_legs output shape).
_PACE_ENTRY = {
    "node_key": ["corn", "export_pace"], "table": "silver_esr", "metric": "weekly_exports_1000mt",
    "grain": "week", "n_points": 6, "streak": 4, "streak_direction": "up", "window_change": 12.5,
    "collapse": "sum",
}


def _ctx(engine="img:1", graph="gv1:aaaa", provenance=prs.PROV_DAILY_SWEEP, run_id="run-1"):
    return prs.RunContext(engine_version=engine, graph_version=graph, provenance=provenance,
                          run_id=run_id, written_at="2026-07-24T00:00:00+00:00")


# ---------------------------------------------------------------------------
# (F1) the engine_version WRITE-GUARD: a cross-version overwrite is REFUSED, never silent.
# ---------------------------------------------------------------------------
def test_write_guard_refuses_cross_version_overwrite():
    asof = "2026-07-24"
    existing = prs.pace_record("corn_cbot", "export_pace", asof, _ctx(engine="img:1"), entry=_PACE_ENTRY, n_rows=2)
    # a re-run of the SAME (kind, contract, driver, asof) partition under a BUMPED engine_version.
    incoming = prs.pace_record("corn_cbot", "export_pace", asof, _ctx(engine="img:2"), entry=_PACE_ENTRY, n_rows=2)
    res = prs.apply_write_guard([existing], [incoming])
    assert res.writable == [], "a bumped-engine overwrite must NOT be writable"
    assert len(res.refused) == 1
    r = res.refused[0]
    assert r["stored_engine_version"] == "img:1" and r["incoming_engine_version"] == "img:2"
    assert "write-guard" in r["reason"]
    # a bumped GRAPH_version is equally refused (the graph axis of the guard).
    gres = prs.apply_write_guard([existing],
                                 [prs.pace_record("corn_cbot", "export_pace", asof,
                                                  _ctx(engine="img:1", graph="gv1:bbbb"), entry=_PACE_ENTRY, n_rows=2)])
    assert gres.writable == [] and len(gres.refused) == 1


def test_write_guard_idempotent_same_version_rerun():
    """A same-code retry / same-day repair (identical engine + graph version) replaces cleanly -- one
    row per (guard_key), never a duplicate."""
    asof = "2026-07-24"
    first = prs.pace_record("corn_cbot", "export_pace", asof, _ctx(), entry=_PACE_ENTRY, n_rows=2)
    rerun = prs.pace_record("corn_cbot", "export_pace", asof, _ctx(run_id="run-2"), entry=_PACE_ENTRY, n_rows=2)
    res = prs.apply_write_guard([first], [rerun])
    assert len(res.writable) == 1 and res.refused == []
    assert res.writable[0].guard_key() == first.guard_key()  # same key -> a replace, not a second row


# ---------------------------------------------------------------------------
# (COVERAGE_AND_CAPACITY_PLAN sec E) CROSS-PROVENANCE overwrite -- the defect that already destroyed the
# 2026-07-25 day-0 daily_sweep partition at 09:03Z. provenance is a COLUMN, not a partition key, and the
# layout is ONE OBJECT PER ASOF, so a second class at an occupied asof is a destructive rewrite.
# ---------------------------------------------------------------------------
def test_cross_provenance_overwrite_is_refused():
    asof = "2026-07-25"
    daily = prs.pace_record("corn_cbot", "export_pace", asof,
                            _ctx(provenance=prs.PROV_DAILY_SWEEP), entry=_PACE_ENTRY, n_rows=2)
    # the 2026-07-25 incident, replayed: a backfill_grid run at an asof already holding daily_sweep rows.
    backfill = prs.pace_record("corn_cbot", "export_pace", asof,
                               _ctx(engine="img:9", provenance=prs.PROV_BACKFILL_GRID), entry=_PACE_ENTRY, n_rows=2)
    assert daily.natural_key() == backfill.natural_key()
    assert daily.guard_key() != backfill.guard_key()   # the guard_key alone would NOT have caught this
    res = prs.apply_write_guard([daily], [backfill])
    assert res.writable == [], "a cross-provenance write at an occupied asof must NOT be writable"
    assert len(res.refused) == 1 and len(res.cross_provenance) == 1 and res.cross_version == []
    r = res.refused[0]
    assert r["refusal"] == prs.REFUSE_CROSS_PROVENANCE
    assert r["as_of_date"] == asof
    assert r["incoming_provenance"] == prs.PROV_BACKFILL_GRID
    assert r["stored_provenance"] == [prs.PROV_DAILY_SWEEP]
    # the reason must be LOUD and self-explaining -- it is the only thing an operator sees at 09:03Z.
    assert "CROSS-PROVENANCE" in r["reason"] and "DESTROY" in r["reason"]
    assert "ONE OBJECT PER ASOF" in r["reason"] and "2026-07-25" in r["reason"]

    # symmetric: a daily_sweep run at an asof already held by the backfill grid is equally refused.
    rev = prs.apply_write_guard([backfill], [daily])
    assert rev.writable == [] and len(rev.cross_provenance) == 1

    # the refusal is PARTITION-scoped, not key-scoped: an UNRELATED pair at the same occupied asof is
    # refused too (writing the object at all destroys the incumbent rows, whatever their keys).
    other = prs.pace_record("soybeans_cbot", "export_pace_lag", asof,
                            _ctx(provenance=prs.PROV_BACKFILL_GRID), decline_reason=prs.PACE_DECLINE_FETCH)
    assert prs.apply_write_guard([daily], [other]).writable == []

    # ... and it is scoped to the OCCUPIED asof only: a different asof is untouched.
    free = prs.pace_record("corn_cbot", "export_pace", "2026-07-26",
                           _ctx(provenance=prs.PROV_BACKFILL_GRID), entry=_PACE_ENTRY, n_rows=2)
    ok = prs.apply_write_guard([daily], [free])
    assert len(ok.writable) == 1 and ok.refused == []


# ---------------------------------------------------------------------------
# (F2 / sec 3.1) backfill EXCLUDES oni / weather_z legs (period latest-only, not as-of replayable).
# ---------------------------------------------------------------------------
def test_backfill_excludes_oni_and_weather_z():
    assert prs.backfill_eligible(["silver_esr_compact"]) is True     # release-date vintaged
    assert prs.backfill_eligible(["silver_wasde"]) is True
    assert prs.backfill_eligible(["silver_noaa_oni"]) is False        # period latest-only -> EXCLUDED
    assert prs.backfill_eligible(["gold_weather_z"]) is False
    # a MIXED surface (one vintaged leg + one weather leg) is excluded whole (its history is restated).
    assert prs.backfill_eligible(["silver_esr_compact", "gold_weather_z"]) is False
    assert prs.backfill_eligible([]) is False                         # nothing vintaged to replay
    assert prs.backfill_eligible([None]) is False                     # unknown table fails closed

    # end-to-end: the backfill sweep drops an oni-legged verdict but keeps a vintaged one.
    ctx = _ctx(provenance=prs.PROV_BACKFILL_GRID)
    verdicts = [
        prs._EngineVerdict(prs.KIND_PACE, "corn_cbot", "export_pace", True,
                           tables=("silver_esr_compact",), pace_entry=_PACE_ENTRY, n_rows=2),
        prs._EngineVerdict(prs.KIND_PACE, "arabica_coffee", "drought_z", True,
                           tables=("gold_weather_z",), pace_entry=dict(_PACE_ENTRY, table="gold_weather_z")),
    ]
    kept = [prs._to_record(v, "2019-06-07", ctx) for v in verdicts if prs.backfill_eligible(v.tables)]
    assert [r.driver_or_chain_id for r in kept] == ["export_pace"]    # the weather leg is excluded


# ---------------------------------------------------------------------------
# (W4-writer / SV-L2-N2) the LEAKY as-of gate, on the WRITE side. silver_psd carries a release_date
# axis that is SYNTHESIZED in code (_compute_psd_release_dates), so a past-asof replay reads values that
# were not knowable at T -- 739 keys revised under an unchanged computed release_date, and 9,292 keys
# backdated into existence as far as 2020-11-10. That membership is what admitted the 37,752 leaked
# cascade rows. A READ fence alone leaves the write re-earnable by any future backfill run.
# ---------------------------------------------------------------------------
def test_leaky_asof_tables_rejected_by_backfill_eligible():
    assert "silver_psd" in prs.LEAKY_ASOF_TABLES
    # the trap this closes: silver_psd is STILL in VINTAGED_TABLES (it does carry a release_date axis),
    # so eligibility must be decided by the LEAKY set winning, not by the vintaged set being edited.
    assert "silver_psd" in prs.VINTAGED_TABLES
    assert prs.backfill_eligible(["silver_psd"]) is False
    # mixed surfaces are excluded whole -- one leaky leg poisons the whole replay.
    assert prs.backfill_eligible(["silver_esr_compact", "silver_psd"]) is False
    assert prs.backfill_eligible(["silver_psd", "silver_wasde"]) is False
    # the genuinely-vintaged surfaces are untouched (the fence is targeted, not a blanket NO-GO).
    assert prs.backfill_eligible(["silver_esr", "silver_esr_compact", "silver_wasde"]) is True
    # every LEAKY table must be a known table, or the set is a silent no-op typo.
    assert prs.LEAKY_ASOF_TABLES <= (prs.VINTAGED_TABLES | prs.LATEST_ONLY_TABLES)

    # end-to-end through the backfill sweep path: a psd-legged cascade verdict is DROPPED.
    ctx = _ctx(provenance=prs.PROV_BACKFILL_GRID)
    verdicts = [
        prs._EngineVerdict(prs.KIND_CASCADE, "corn_cbot", "ending_stocks", True,
                           tables=("silver_psd",), n_rows=1, cascade_table="silver_psd"),
        prs._EngineVerdict(prs.KIND_PACE, "corn_cbot", "export_pace", True,
                           tables=("silver_esr",), pace_entry=_PACE_ENTRY, n_rows=2),
    ]
    kept = [prs._to_record(v, "2024-01-06", ctx) for v in verdicts if prs.backfill_eligible(v.tables)]
    assert [r.driver_or_chain_id for r in kept] == ["export_pace"]


def test_no_live_psd_legged_surface_is_backfill_replayable():
    """The fence measured against the REAL catalog, not a fixture: every cascade-kind leg that reads
    silver_psd is now ineligible for a past-asof replay. Those 242 legs x 156 asofs are exactly the
    37,752 leaked rows already on S3; this pins that a re-run cannot produce them again.

    Deliberately NOT asserting 'zero cascade legs are eligible' even though that is true today (the
    other cascade tables are gold_weather_z / silver_noaa_oni -- LATEST_ONLY -- and silver_fred_fx,
    which is not in VINTAGED_TABLES at all). The sanctioned silver_wasde repoint would legitimately make
    cascade legs eligible again, and this test must not stand in its way."""
    from leviathan.graphrag.numbers import cascade as casc
    from leviathan.graphrag.numbers import cascade_census as cc
    psd_legs = 0
    for _contract, c in sorted(cc._contract_index().items()):
        for d in c.drivers:
            row = casc.map_row(d.silver_ref)
            if row is None or prs._pace_capable(row):
                continue
            if row.get("table") == "silver_psd":
                psd_legs += 1
                assert prs.backfill_eligible((row.get("table"),)) is False
    assert psd_legs > 0, "the census resolves no psd-legged cascade legs -- the fence is testing nothing"


def test_weekly_backfill_grid_is_bounded_weekly_and_past():
    grid = prs.weekly_backfill_grid("2026-07-24", years=3)
    assert grid[0] == "2026-07-24"
    assert len(grid) == 156                                            # ~52 weeks x 3
    # strictly weekly, strictly descending into the past.
    assert grid[1] == "2026-07-17" and grid[-1] < grid[0]


# ---------------------------------------------------------------------------
# decline-reason recording: the pace decline REASON is re-derived from the engine's inline gates (F6).
# ---------------------------------------------------------------------------
def test_pace_decline_reason_recording():
    # region_unresolved: _scope returned SKIP_NODE (compound/prose region).
    assert prs.classify_pace_decline(None, None, scope_skipped=True) == prs.PACE_DECLINE_REGION
    # fetch_error: the resolution/fetch did not return status=ok.
    assert prs.classify_pace_decline({"status": "error"}, {"table": "silver_esr"}) == prs.PACE_DECLINE_FETCH
    # annual_grain: a marketing-year / event-flag row has no sub-annual pace grain.
    assert prs.classify_pace_decline({"status": "ok", "rows": []},
                                     {"table": "silver_psd", "period_type": "marketing_year"}) == prs.PACE_DECLINE_ANNUAL
    # cross_section_undeclared: a multi-row period on a table with NO declared collapse (silver_cot).
    xsec = {"status": "ok", "rows": [{"value": 1, "week_ending_date": "2026-07-01"},
                                     {"value": 2, "week_ending_date": "2026-07-01"}]}
    assert prs.classify_pace_decline(xsec, {"table": "silver_cot", "period_type": "date"}) == prs.PACE_DECLINE_XSECTION
    # thin_history: only one collapsed period (< MIN_STREAK_N).
    thin = {"status": "ok", "rows": [{"value": 10, "week_ending_date": "2026-07-01"}]}
    assert prs.classify_pace_decline(thin, {"table": "silver_cot", "period_type": "date"}) == prs.PACE_DECLINE_THIN

    # and the declined reason is RECORDED on the row (honest-decline doctrine).
    rec = prs.pace_record("corn_cbot", "export_pace", "2026-07-24", _ctx(),
                          decline_reason=prs.PACE_DECLINE_THIN)
    assert rec.verdict == prs.VERDICT_DECLINED and rec.decline_reason == prs.PACE_DECLINE_THIN
    assert rec.streak_len is None and rec.window_change is None       # no fabricated values on a decline
    with pytest.raises(ValueError):                                   # a declined row without a reason is illegal
        prs.PatternRecord(record_kind=prs.KIND_PACE, contract="c", driver_or_chain_id="d",
                          as_of_date="2026-07-24", verdict=prs.VERDICT_DECLINED, engine_version="e",
                          graph_version="g", provenance=prs.PROV_DAILY_SWEEP, run_id="r",
                          written_at="2026-07-24T00:00:00+00:00")
    with pytest.raises(ValueError):                                   # an unknown pace reason is rejected
        prs.pace_record("c", "d", "2026-07-24", _ctx(), decline_reason="not_a_reason")


def test_fired_declined_split_is_engine_driven_not_re_derived():
    """(F6 drift guard) the fired/declined SPLIT is the engine's own verdict -- read from
    cascade._pace_legs producing a trace entry (fired) or not (declined) -- NOT re-derived. The sweep's
    decline classifier only NAMES a reason among declines, and it agrees with the engine on the split."""
    node_key = ("corn", "export_pace")
    row = {"table": "silver_esr", "period_type": "date", "scale": 1, "narrate_unit": "1000 MT"}
    kept = [{"specs": [{"node_key": node_key}], "row": row}]

    def _rec(rows):
        return [{"leg": ("pace", None), "status": "ok", "node_key": node_key, "rows": rows}]

    # >=2 collapsed periods with a move -> the ENGINE emits a quantify_pace entry (fired).
    fired_rows = [{"value": 100, "week_ending_date": "2026-06-01"},
                  {"value": 150, "week_ending_date": "2026-06-08"}]
    _lines, trace = casc._pace_legs(_rec(fired_rows), kept, 0, [])
    assert trace, "the engine should FIRE on a 2-period monotonic series"

    # a single period -> the engine emits NOTHING (declined); the sweep classifies it thin_history and
    # never overrides the engine's split.
    thin_rows = [{"value": 100, "week_ending_date": "2026-06-01"}]
    _l2, trace2 = casc._pace_legs(_rec(thin_rows), kept, 0, [])
    assert trace2 == [], "the engine should DECLINE a 1-period series"
    thin_rec = {"status": "ok", "rows": thin_rows}
    assert prs.classify_pace_decline(thin_rec, row) == prs.PACE_DECLINE_THIN


# ---------------------------------------------------------------------------
# chain-kind record from a quantify_chain fixture (plan sec 5 / D9).
# ---------------------------------------------------------------------------
def test_chain_record_from_quantify_chain_fixture():
    # a fired sg.trace['quantify_chain'] (cascade._chain_legs fired-trace shape): 2 quantified hops + a
    # collapsed original (sec 2.3), 5 injected [N] rows.
    fired = {
        "chain_id": "corn_lanina_safrinha_su", "contract": "corn_cbot", "window": "2011..2012",
        "hops": [
            {"hop": 0, "node": "La_Nina", "table": "gold_weather_z", "metric": "oni"},
            {"hop": 1, "node": "production", "table": "silver_psd", "metric": "production_mt"},
            {"hop": 2, "collapsed_into": 1},   # a collapsed original -> NOT a quantified hop
        ],
        "n_rows": 5,
    }
    rec = prs.chain_record("corn_cbot", "corn_lanina_safrinha_su", "2026-07-24", _ctx(), fired=fired)
    assert rec.record_kind == prs.KIND_CHAIN and rec.verdict == prs.VERDICT_FIRED
    assert rec.driver_or_chain_id == "corn_lanina_safrinha_su"
    assert rec.n_hops == 2                        # the collapsed original does not count as a hop
    assert rec.n_rows == 5
    assert rec.decline_reason is None
    assert "La_Nina -> production" in (rec.extra or "")

    # a declined sg.trace['quantify_chain_decline'] (D7 enum) -> a declined chain record with the reason.
    decline = {"chain_id": "corn_lanina_safrinha_su", "reason": "hop_dark", "hop": 1}
    drec = prs.chain_record("corn_cbot", "corn_lanina_safrinha_su", "2026-07-24", _ctx(), decline=decline)
    assert drec.verdict == prs.VERDICT_DECLINED and drec.decline_reason == "hop_dark"
    assert drec.n_hops is None
    with pytest.raises(ValueError):                # an unknown chain reason is rejected
        prs.chain_record("c", "id", "2026-07-24", _ctx(), decline={"chain_id": "id", "reason": "bogus"})


def test_v1_kinds_only_fork_kinds_rejected():
    """v1 writes cascade + pace + chain ONLY; the deferred fork kinds are unrepresentable (F4)."""
    for fork in ("comove", "reroute", "price_leg"):
        assert fork in prs.DEFERRED_FORK_KINDS
        with pytest.raises(ValueError):
            prs.PatternRecord(record_kind=fork, contract="c", driver_or_chain_id="d",
                              as_of_date="2026-07-24", verdict=prs.VERDICT_FIRED, engine_version="e",
                              graph_version="g", provenance=prs.PROV_DAILY_SWEEP, run_id="r",
                              written_at="2026-07-24T00:00:00+00:00")


# ---------------------------------------------------------------------------
# schema round-trip: the built rows encode to parquet under the registry contract, byte-faithfully.
# ---------------------------------------------------------------------------
def test_schema_round_trip_matches_registry_contract():
    contract = load_registry().table("gold_pattern_records")
    ctx = _ctx()
    recs = [
        prs.pace_record("corn_cbot", "export_pace", "2026-07-24", ctx, entry=_PACE_ENTRY, n_rows=2),
        prs.pace_record("soybeans_cbot", "export_pace", "2026-07-24", ctx, decline_reason=prs.PACE_DECLINE_THIN),
        prs.cascade_record("corn_cbot", "ending_stocks", "2026-07-24", ctx, fired=True, n_rows=1,
                           table="silver_psd", metric="ending_stocks_mt"),
        prs.chain_record("corn_cbot", "wheat_area_su", "2026-07-24", ctx,
                         decline={"chain_id": "wheat_area_su", "reason": "root_not_grounded"}),
    ]
    objects = prs.build_staged_objects(recs, contract)
    assert len(objects) == 1
    obj = objects[0]
    assert obj.partition_values == ["2026-07-24"]          # registered partition on as_of_date
    assert obj.row_count == 4
    tbl = pq.read_table(io.BytesIO(obj.body))
    # the physical columns match the contract exactly (as_of_date lives in the path, not the parquet).
    assert tbl.column_names == list(prs.COLUMNS)
    contract_cols = [c["name"] for c in contract["physical_columns"]]
    assert tbl.column_names == contract_cols
    assert str(tbl.schema.field("written_at").type) == "timestamp[us]"
    assert str(tbl.schema.field("streak_len").type) == "int64"
    d = tbl.to_pydict()
    assert d["verdict"] == ["fired", "declined", "fired", "declined"]
    assert d["streak_len"] == [4, None, None, None]        # values only on the fired pace row
    assert d["decline_reason"] == [None, "thin_history", None, "root_not_grounded"]


def test_run_context_rejects_unknown_provenance():
    with pytest.raises(ValueError):
        prs.RunContext(engine_version="e", graph_version="g", provenance="live", run_id="r")


# ---------------------------------------------------------------------------
# one-kind-per-pair: a pace-capable pair is recorded under the PACE kind ONLY, never ALSO as cascade
# (plan F3 / sec-8 cap -- double-recording would trip the duplication alarm and understate the cost model).
# ---------------------------------------------------------------------------
def test_pace_capable_predicate():
    assert prs._pace_capable({"leg_mode": "current", "table": "silver_esr"}) is True   # week grain
    assert prs._pace_capable({"leg_mode": "current", "table": "silver_psd"}) is False   # not a pace table
    assert prs._pace_capable({"table": "silver_esr"}) is False                          # not leg_mode=current
    assert prs._pace_capable({"leg_mode": "current", "table": "silver_esr",
                              "period_type": "marketing_year"}) is False                # annual grain
    assert prs._pace_capable(None) is False


def test_cascade_verdicts_excludes_pace_capable_legs(monkeypatch):
    """(finding 2) cascade_verdicts must NOT emit a cascade row for a pace-capable leg -- pace_verdicts owns
    it. The census enumerates EVERY mapped driver (no leg_mode filter), so without the exclusion a
    pace-capable pair like export_pace is double-recorded (one cascade + one pace row)."""
    from leviathan.graphrag.numbers import cascade as casc
    from leviathan.graphrag.numbers import cascade_census as cc
    art = {"legs": [
        {"contract": "corn_cbot", "node_id": "export_pace", "silver_ref": "esr_exports",
         "table": "silver_esr", "metric": "weekly_exports_1000mt", "verdict": cc.FIRES, "reason": None},
        {"contract": "corn_cbot", "node_id": "ending_stocks", "silver_ref": "psd_stocks",
         "table": "silver_psd", "metric": "ending_stocks_mt", "verdict": cc.FIRES, "reason": None},
    ]}
    monkeypatch.setattr(cc, "census", lambda **kw: art)
    rows = {"esr_exports": {"leg_mode": "current", "table": "silver_esr"},   # pace-capable -> EXCLUDED
            "psd_stocks": {"table": "silver_psd", "metric": "ending_stocks_mt"}}
    monkeypatch.setattr(casc, "map_row", lambda ref: rows.get(ref))
    out = prs.cascade_verdicts("2026-07-24", query_fn=lambda sql: [])
    assert [v.driver_or_chain_id for v in out] == ["ending_stocks"]      # the pace-capable leg is dropped
    assert all(v.kind == prs.KIND_CASCADE for v in out)


# ---------------------------------------------------------------------------
# (F1) the WRITE-GUARD is WIRED at runtime: the writer READS existing rows then refuses a cross-version
# overwrite -- it is not dead code. read_existing_guard_rows pins provenance + asof and fails safe.
# ---------------------------------------------------------------------------
def test_read_existing_guard_rows_reads_across_provenance():
    """(sec E) the read must span ALL provenance classes at the target asofs. The old
    `WHERE provenance = <target>` predicate is exactly why the 2026-07-25 backfill saw an empty result
    at an asof that held daily_sweep rows and proceeded as a 'first write'."""
    seen = {}

    def qfn(sql):
        seen["sql"] = sql
        return [{"record_kind": "pace", "contract": "corn_cbot", "driver_or_chain_id": "export_pace",
                 "as_of_date": "2026-07-24", "provenance": prs.PROV_DAILY_SWEEP,
                 "engine_version": "img:1", "graph_version": "gv1:aaaa"}]

    rows = prs.read_existing_guard_rows(qfn, ["2026-07-24"])
    assert len(rows) == 1 and rows[0]["engine_version"] == "img:1"
    assert prs.TABLE in seen["sql"] and "'2026-07-24'" in seen["sql"]
    # the provenance PREDICATE is gone (the column is still SELECTed -- the guard keys on it).
    assert "provenance = " not in seen["sql"] and "provenance" in seen["sql"].split("FROM")[0]
    # a pg date object / timestamp is normalized to the 'YYYY-MM-DD' string the incoming records key on.
    norm = prs.read_existing_guard_rows(
        lambda s: [{"record_kind": "pace", "contract": "c", "driver_or_chain_id": "d",
                    "as_of_date": "2026-07-24T00:00:00", "provenance": prs.PROV_DAILY_SWEEP,
                    "engine_version": "e", "graph_version": "g"}], ["2026-07-24"])
    assert norm[0]["as_of_date"] == "2026-07-24"
    assert prs.read_existing_guard_rows(qfn, []) == []                    # no asofs -> no query
    # defence in depth: an UN-normalized partition value reaching apply_write_guard by any other route
    # must still register as occupancy, or the cross-provenance refusal fails OPEN.
    raw = {"record_kind": "pace", "contract": "corn_cbot", "driver_or_chain_id": "export_pace",
           "as_of_date": "2026-07-24 00:00:00", "provenance": prs.PROV_DAILY_SWEEP,
           "engine_version": "img:1", "graph_version": "gv1:aaaa"}
    incoming = prs.pace_record("corn_cbot", "export_pace", "2026-07-24",
                               _ctx(provenance=prs.PROV_BACKFILL_GRID), entry=_PACE_ENTRY, n_rows=2)
    assert prs.apply_write_guard([raw], [incoming]).writable == []
    # ... and the same holds on the VERSION axis (a same-provenance bumped-engine re-run).
    bumped = prs.pace_record("corn_cbot", "export_pace", "2026-07-24", _ctx(engine="img:2"),
                             entry=_PACE_ENTRY, n_rows=2)
    assert prs.apply_write_guard([raw], [bumped]).writable == []


# ---------------------------------------------------------------------------
# (W6.i) the guard's OTHER fail-open: read_existing_guard_rows used to swallow EVERY pg error and return
# [], which apply_write_guard reads as "first write" -> everything writable. A pg blip during a
# re-publish was therefore a silent full overwrite of a certified canonical partition.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("exc", [
    RuntimeError("connection to server at 10.0.3.7 port 5432 failed: timeout expired"),
    RuntimeError("canceling statement due to statement timeout"),
    RuntimeError('permission denied for table gold_pattern_records'),
    RuntimeError('relation "some_other_table" does not exist'),   # a DIFFERENT missing relation
])
def test_guard_read_failure_aborts_never_proceeds(exc):
    def boom(sql):
        raise exc
    with pytest.raises(prs.GuardReadError) as ei:
        prs.read_existing_guard_rows(boom, ["2026-07-24"])
    assert "ABORTING the publish" in str(ei.value)
    assert ei.value.__cause__ is exc                      # the real pg error is preserved for triage


# the message psycopg ACTUALLY produces (probed in-VPC 2026-07-28), for our table and for another one.
_MISSING_OURS = 'relation "leviathan_dev.gold_pattern_records" does not exist\nLINE 1: ...provenance'
_MISSING_OTHER = 'relation "leviathan_dev.silver_esr" does not exist\nLINE 1: ...provenance'


class _UndefinedTable(Exception):
    """Stands in for psycopg.errors.UndefinedTable -- matched by CLASS NAME."""


def _diag_exc(sqlstate):
    class _Diag:
        pass
    _Diag.sqlstate = sqlstate

    class BySqlState(Exception):
        diag = _Diag()
    return BySqlState


def test_guard_read_missing_table_is_a_legitimate_first_write():
    """The ONLY case allowed to fail open: OUR ledger table does not exist yet (flip day). Recognised by
    class / SQLSTATE / message text -- but every route is AND-ed with 'the message names OUR table'."""
    def by_message(sql):
        raise RuntimeError(_MISSING_OURS)

    def by_class(sql):
        raise _UndefinedTable(_MISSING_OURS)

    def by_sqlstate(sql):
        raise _diag_exc("42P01")(_MISSING_OURS)

    for fn in (by_message, by_class, by_sqlstate):
        assert prs.read_existing_guard_rows(fn, ["2026-07-24"]) == []


def test_guard_read_missing_OTHER_relation_fails_CLOSED():
    """psycopg raises UndefinedTable/42P01 for ANY missing relation, so the class and SQLSTATE tests are
    table-BLIND on their own. A missing *different* relation is somebody else's schema problem: it must
    ABORT, not be mistaken for 'our ledger does not exist yet' and licence a full overwrite."""
    def by_class(sql):
        raise _UndefinedTable(_MISSING_OTHER)

    def by_sqlstate(sql):
        raise _diag_exc("42P01")(_MISSING_OTHER)

    def unhelpful(sql):                      # UndefinedTable with a message naming nothing at all
        raise _UndefinedTable("nope")

    for fn in (by_class, by_sqlstate, unhelpful):
        with pytest.raises(prs.GuardReadError):
            prs.read_existing_guard_rows(fn, ["2026-07-24"])


def test_guard_read_sql_is_SCHEMA_QUALIFIED():
    """An UNQUALIFIED `FROM gold_pattern_records` does not resolve on the mirror: pgstore._acquire()
    sets no search_path, and the loader creates the table inside the schema `leviathan_dev`. Probed
    in-VPC 2026-07-28: to_regclass('gold_pattern_records') IS NULL while the qualified name returned 251
    rows at as_of_date=2026-07-25. Unqualified, EVERY guard read raised UndefinedTable -> classified as
    'table missing' -> [] -> apply_write_guard saw an empty partition and BOTH refusals were dead code.
    This pins the qualification so the guard cannot silently become a no-op again."""
    seen = {}

    def capture(sql):
        seen["sql"] = sql
        return []

    prs.read_existing_guard_rows(capture, ["2026-07-24"])
    assert prs.PG_TABLE == '"leviathan_dev".gold_pattern_records'
    assert f"FROM {prs.PG_TABLE}" in seen["sql"]
    assert f"FROM {prs.TABLE}" not in seen["sql"]   # the bare name is never the FROM target
    assert prs.TABLE == "gold_pattern_records"      # ...but TABLE stays bare: it is the GLUE identity


def test_guard_read_failure_blocks_the_publish_end_to_end(monkeypatch):
    """The abort must reach the CLI: a failed guard read returns a non-zero rc and never gets as far as
    building a publish. Verified by making _load_contract explode -- if we ever reach it, the test fails
    with the wrong exception instead of a clean rc."""
    monkeypatch.setattr(prs, "_assert_pg_only", lambda: None)
    monkeypatch.setattr(prs, "sweep", lambda *a, **k: [])
    monkeypatch.setattr(prs, "read_existing_guard_rows",
                        lambda *a, **k: (_ for _ in ()).throw(prs.GuardReadError("mirror unreadable")))
    monkeypatch.setattr(prs, "_load_contract",
                        lambda: pytest.fail("reached publish setup after a failed guard read"))
    import leviathan.common.config as _cfg
    monkeypatch.setattr(_cfg, "load_env", lambda *a, **k: None)
    from leviathan.graphrag.numbers import pgnumbers
    monkeypatch.setattr(pgnumbers, "pg_query", lambda sql: [])
    assert prs.main(["--publish-mode", "canonical"]) == 3


def _stub_cli_env(monkeypatch):
    """The minimum patching that lets main() run to the write-guard without pg / AWS."""
    monkeypatch.setattr(prs, "_assert_pg_only", lambda: None)
    import leviathan.common.config as _cfg
    monkeypatch.setattr(_cfg, "load_env", lambda *a, **k: None)
    from leviathan.graphrag.numbers import pgnumbers
    monkeypatch.setattr(pgnumbers, "pg_query", lambda sql: [])
    # The stale-mirror cross-check (2026-07-29 incident) is part of the runtime path and stays
    # ARMED under test -- only its S3 transport is stubbed, so the real detector logic runs.
    # _S3Miss = "no object at that asof", i.e. the free-target case these CLI tests are about;
    # a test that wants the stale branch injects _S3Hit itself.
    monkeypatch.setenv("LEVIATHAN_BUCKET", "test-bucket")
    _real_detect = prs.detect_stale_mirror
    monkeypatch.setattr(prs, "detect_stale_mirror",
                        lambda existing, asofs, *, bucket, s3_client=None:
                        _real_detect(existing, asofs, bucket=bucket, s3_client=_S3Miss()))
    monkeypatch.setattr(prs, "sweep", lambda asof, qfn, ctx, **k: [
        prs.pace_record("corn_cbot", "export_pace", asof, ctx, entry=_PACE_ENTRY, n_rows=2)])
    monkeypatch.setattr(prs, "_load_contract",
                        lambda: pytest.fail("reached publish setup after a refused cross-provenance write"))


@pytest.mark.parametrize("argv", [["--publish-mode", "canonical"], ["--dry-run"]])
def test_cli_aborts_on_cross_provenance_collision(monkeypatch, argv):
    """(sec E, end to end) a daily_sweep at an asof the backfill grid already occupies must ABORT with a
    non-zero rc and never reach the publisher -- in --dry-run too, since the dry-run's job is to predict
    the publish. This is the 2026-07-25 incident with the roles reversed."""
    _stub_cli_env(monkeypatch)
    monkeypatch.setattr(prs, "read_existing_guard_rows", lambda qfn, asofs: [
        {"record_kind": "pace", "contract": "corn_cbot", "driver_or_chain_id": "export_pace",
         "as_of_date": a, "provenance": prs.PROV_BACKFILL_GRID,
         "engine_version": "img:0", "graph_version": "gv1:zzzz"} for a in asofs])
    assert prs.main(argv) == 4


def test_cli_publishes_when_the_target_asof_is_free(monkeypatch):
    """The mirror image: an EMPTY target asof is not a collision, so --dry-run stays rc 0. Without this
    the cross-provenance refusal could be trivially satisfied by refusing everything."""
    _stub_cli_env(monkeypatch)
    monkeypatch.setattr(prs, "read_existing_guard_rows", lambda qfn, asofs: [])
    assert prs.main(["--dry-run"]) == 0


def test_write_guard_runtime_composition_read_then_refuse():
    """(F1 wiring) the runtime path composes read_existing_guard_rows -> apply_write_guard: an existing img:1
    row + an incoming img:2 re-run of the SAME key is REFUSED (never a silent overwrite), while a
    same-version re-run through the same read path is a clean idempotent replace."""
    asof = "2026-07-24"
    stored = {"record_kind": "pace", "contract": "corn_cbot", "driver_or_chain_id": "export_pace",
              "as_of_date": asof, "provenance": prs.PROV_DAILY_SWEEP,
              "engine_version": "img:1", "graph_version": "gv1:aaaa"}
    existing = prs.read_existing_guard_rows(lambda s: [stored], [asof])
    bumped = prs.pace_record("corn_cbot", "export_pace", asof, _ctx(engine="img:2"), entry=_PACE_ENTRY, n_rows=2)
    res = prs.apply_write_guard(existing, [bumped])
    assert res.writable == [] and len(res.refused) == 1
    assert res.refused[0]["refusal"] == prs.REFUSE_CROSS_VERSION      # version axis, not provenance
    same = prs.pace_record("corn_cbot", "export_pace", asof, _ctx(engine="img:1", graph="gv1:aaaa"),
                           entry=_PACE_ENTRY, n_rows=2)
    res2 = prs.apply_write_guard(existing, [same])
    assert len(res2.writable) == 1 and res2.refused == []             # idempotent re-run still passes


# ---------------------------------------------------------------------------
# (finding 4) a non-backfill sweep at a BACKDATED asof is refused before any pg/AWS work: it would record
# daily_sweep rows from TODAY's restated data at a past as_of_date that leak into the serving PIT read.
# ---------------------------------------------------------------------------
def test_daily_sweep_refuses_past_asof():
    assert prs.main(["--asof", "1990-01-01"]) == 2          # past asof + not --backfill -> refused (rc 2)


# ---------------------------------------------------------------------------
# (W3) the DAILY path records PACE ONLY. Cascade rows are constant-valued catalog-existence flags
# (242 pairs, per-pair (fired,swept) in {(156,156), (0,156)}, zero variance) and chain rows are 100%
# root_not_grounded for want of a trace_provider. Both resolvability pictures live in cascade_census /
# config_check.check_chain_map. The BACKFILL path is deliberately unchanged.
# ---------------------------------------------------------------------------
def _stub_kind_drivers(monkeypatch, *, n_cascade=242, n_pace=9, n_chain=29):
    """Stand in for the three live pg drivers with the measured production cardinalities."""
    monkeypatch.setattr(prs, "cascade_verdicts", lambda asof, qfn: [
        prs._EngineVerdict(prs.KIND_CASCADE, f"c{i}", f"d{i}", True, tables=("silver_wasde",), n_rows=1,
                           cascade_table="silver_wasde", cascade_metric="m")
        for i in range(n_cascade)])
    monkeypatch.setattr(prs, "pace_verdicts", lambda asof, qfn: [
        prs._EngineVerdict(prs.KIND_PACE, f"p{i}", "export_pace", True, tables=("silver_esr",),
                           pace_entry=_PACE_ENTRY, n_rows=2)
        for i in range(n_pace)])
    monkeypatch.setattr(prs, "chain_verdicts", lambda asof, qfn, trace_provider=None: [
        prs._EngineVerdict(prs.KIND_CHAIN, f"c{i}", f"chain{i}", False,
                           chain_decline={"chain_id": f"chain{i}", "reason": "root_not_grounded"})
        for i in range(n_chain)])


def test_daily_sweep_records_pace_only(monkeypatch):
    _stub_kind_drivers(monkeypatch)
    ctx = _ctx(provenance=prs.PROV_DAILY_SWEEP)
    recs = prs.sweep("2026-07-29", query_fn=lambda sql: [], ctx=ctx)      # default kinds = all of v1
    assert len(recs) == 9, "a day-2 daily partition is the 9 pace rows, not 242+9+29"
    assert {r.record_kind for r in recs} == {prs.KIND_PACE}
    assert prs.DAILY_SWEEP_KINDS == frozenset({prs.KIND_PACE})
    # the narrowing keys on ctx.provenance, NOT on --kinds: an explicit widening request cannot undo it
    # (the deployed jobdef passes no --kinds at all, so the default is the whole v1 set).
    widened = prs.sweep("2026-07-29", query_fn=lambda sql: [], ctx=ctx,
                        kinds={prs.KIND_CASCADE, prs.KIND_PACE, prs.KIND_CHAIN})
    assert len(widened) == 9 and {r.record_kind for r in widened} == {prs.KIND_PACE}
    # narrowing FURTHER still works (--kinds cascade on the daily path yields nothing, not a cascade row).
    assert prs.sweep("2026-07-29", query_fn=lambda sql: [], ctx=ctx, kinds={prs.KIND_CASCADE}) == []


def test_backfill_path_still_records_every_kind(monkeypatch):
    """W3 narrows the DAILY path only -- a provenance=backfill_grid replay is untouched, so the existing
    grid stays reproducible. (Chain still self-excludes there: backfill_eligible(()) is False.)"""
    _stub_kind_drivers(monkeypatch)
    ctx = _ctx(provenance=prs.PROV_BACKFILL_GRID)
    recs = prs.sweep("2024-01-06", query_fn=lambda sql: [], ctx=ctx)
    kinds = {r.record_kind for r in recs}
    assert prs.KIND_CASCADE in kinds and prs.KIND_PACE in kinds and prs.KIND_CHAIN in kinds
    assert len(recs) == 242 + 9 + 29
    # ... and with the vintage fence on, chain drops out on its empty leg set while the rest survive.
    fenced = prs.sweep("2024-01-06", query_fn=lambda sql: [], ctx=ctx, backfill_only_vintaged=True)
    assert {r.record_kind for r in fenced} == {prs.KIND_CASCADE, prs.KIND_PACE}
    assert len(fenced) == 242 + 9


def test_cascade_and_chain_resolvability_pictures_are_not_lost():
    """W3's quality gate: narrowing must RELOCATE the cascade/chain coverage diagnostics, not delete
    them. Both live in richer ops surfaces that the sweep does not own."""
    from leviathan.graphrag import config_check
    from leviathan.graphrag.numbers import cascade_census as cc
    # cascade: the per-leg census carries strictly MORE than the ledger's boolean -- verdict, the
    # DARK-with-reason sub-reason, the per-contract rollup and the counts banner.
    art = cc.census(asof="2026-07-24", query_fn=lambda sql: [])
    assert {"legs", "per_contract_has_firing_leg", "banner"} <= set(art)
    leg = art["legs"][0]
    assert {"contract", "node_id", "table", "metric", "verdict", "reason"} <= set(leg)
    assert {"fires", "declines", "dark", "probe_errors"} <= set(art["banner"])
    # chain: a fail-CLOSED build lint over every hop ref / scope / country pin -- it fails the BUILD
    # rather than accruing a constant root_not_grounded row forever.
    assert callable(config_check.check_chain_map)
    assert config_check.check_chain_map() == []


# ---------------------------------------------------------------------------
# (W5) graph_version was a DEAD guard axis: resolve_graph_version() derived the repo root as
# parents[1] == <repo>/jobs, and jobs/configs/graphrag DOES NOT EXIST, so it hashed the EMPTY STRING on
# all 39,156 rows written so far. A cascade_map / causal-DAG edit was invisible to apply_write_guard.
# ---------------------------------------------------------------------------
_EMPTY_GV = "gv1:" + hashlib.sha256(b"").hexdigest()[:16]


def test_resolve_graph_version_resolves_the_real_repo_configs():
    assert _EMPTY_GV == "gv1:e3b0c44298fc1c14"          # the hash every existing ledger row carries
    repo = Path(prs.__file__).resolve().parents[2]
    assert (repo / "configs" / "graphrag" / "numbers" / "cascade_map.yaml").exists()
    assert (repo / "configs" / "graphrag" / "causal").is_dir()
    assert not (repo / "jobs" / "configs" / "graphrag").exists()   # what parents[1] used to point at
    assert prs.resolve_graph_version() != _EMPTY_GV, "parents[1] regression: graph_version is sha256(b'')"


def test_resolve_graph_version_tracks_config_bytes(tmp_path):
    cfg = tmp_path / "configs" / "graphrag"
    (cfg / "numbers").mkdir(parents=True)
    (cfg / "causal").mkdir(parents=True)
    (cfg / "numbers" / "cascade_map.yaml").write_text("rows: []\n", encoding="utf-8")
    (cfg / "numbers" / "chain_map.yaml").write_text("chains: []\n", encoding="utf-8")
    (cfg / "causal" / "corn.yaml").write_text("drivers: [a]\n", encoding="utf-8")

    h0 = prs.resolve_graph_version(repo=tmp_path)
    assert h0.startswith("gv1:") and h0 != _EMPTY_GV
    assert prs.resolve_graph_version(repo=tmp_path) == h0, "must be stable when nothing changes"

    # ONE byte of a tracked causal DAG.
    (cfg / "causal" / "corn.yaml").write_text("drivers: [b]\n", encoding="utf-8")
    h1 = prs.resolve_graph_version(repo=tmp_path)
    assert h1 != h0 and h1 != _EMPTY_GV

    # the cascade map.
    (cfg / "numbers" / "cascade_map.yaml").write_text("rows: [x]\n", encoding="utf-8")
    h2 = prs.resolve_graph_version(repo=tmp_path)
    assert h2 not in (h0, h1)

    # a NEW causal DAG appearing is also a new graph version.
    (cfg / "causal" / "wheat.yaml").write_text("drivers: [a]\n", encoding="utf-8")
    h3 = prs.resolve_graph_version(repo=tmp_path)
    assert h3 not in (h0, h1, h2)

    # and the old bug's exact signature, pinned so its meaning is unambiguous: a repo root with no
    # configs/graphrag hashes NOTHING and yields the empty-string hash.
    assert prs.resolve_graph_version(repo=tmp_path / "no_such_root") == _EMPTY_GV


# ---------------------------------------------------------------------------
# (2026-07-29 incident) STALE MIRROR -- the third guard-read failure mode.
#
# The guard reads the pg mirror; the mirror's loader is on-demand. A read that SUCCEEDS and
# returns nothing is ambiguous -- genuinely-empty vs simply-behind -- and apply_write_guard
# cannot tell them apart, so every refusal it would have raised is silently disarmed. On
# 2026-07-29 a backfill_grid replay was licensed straight over a certified daily_sweep
# partition on exactly this path. Worse, the deployed loader image did not carry
# gold_pattern_records in P1_TABLES at all, so read_existing_guard_rows had been taking its
# missing-table fail-open branch on EVERY run since T2b shipped. S3 is the authority on
# occupancy (one object per asof), so the cross-check is exact.
# ---------------------------------------------------------------------------
_STALE_DETECT = prs.detect_stale_mirror   # pristine reference for tests that re-arm


class _S3Hit:
    """Every HEAD succeeds -- the object is there."""

    def __init__(self):
        self.heads = []

    def head_object(self, **kw):
        self.heads.append(kw["Key"])
        return {"ContentLength": 1}


class _S3Miss:
    """Every HEAD 404s -- pg and S3 agree the asof is empty."""

    def __init__(self):
        self.heads = []

    def head_object(self, **kw):
        self.heads.append(kw["Key"])
        err = Exception("not found")
        err.response = {"Error": {"Code": "404"}}
        raise err


def _pg_row(asof):
    return {"record_kind": "pace", "contract": "corn_cbot", "driver_or_chain_id": "export_pace",
            "as_of_date": asof, "provenance": prs.PROV_DAILY_SWEEP,
            "engine_version": "img:1", "graph_version": "gv1:aaaa"}


def test_stale_mirror_detected_when_pg_empty_but_object_exists():
    s3 = _S3Hit()
    stale = prs.detect_stale_mirror([], ["2026-07-27", "2026-07-28"], bucket="b", s3_client=s3)
    assert stale == ["2026-07-27", "2026-07-28"], "a pg-empty asof with a live object IS stale"
    # the probe addresses the canonical key, not a guess
    assert s3.heads[0] == f"{prs.S3_PREFIX}/{prs.PARTITION_COL}=2026-07-27/pattern_records.parquet"


def test_current_mirror_costs_zero_s3_calls():
    # every target asof is present in pg -> nothing to disambiguate -> no HEADs, no bucket needed.
    s3 = _S3Hit()
    assert prs.detect_stale_mirror([_pg_row("2026-07-28")], ["2026-07-28"],
                                   bucket=None, s3_client=s3) == []
    assert s3.heads == []


def test_genuinely_empty_asof_is_not_stale():
    # the daily sweep's normal path: today's asof has no object yet. Must NOT trip the check,
    # or the nightly sweep aborts every night.
    s3 = _S3Miss()
    assert prs.detect_stale_mirror([], ["2026-07-29"], bucket="b", s3_client=s3) == []
    assert len(s3.heads) == 1


def test_stale_check_subsumes_the_missing_table_fail_open():
    # read_existing_guard_rows returns [] for a positively-identified missing table ("a legitimate
    # first write"). That is exactly what the deployed loader image produced for MONTHS. When S3
    # says those asofs are occupied, the fail-open must be caught here.
    missing_table_read = []
    assert prs.detect_stale_mirror(missing_table_read, ["2026-07-28"],
                                   bucket="b", s3_client=_S3Hit()) == ["2026-07-28"]


def test_unrunnable_cross_check_is_never_a_passing_one():
    # no bucket -> the check cannot run. It must RAISE, not return [] (which reads as "clean").
    with pytest.raises(RuntimeError, match="bucket"):
        prs.detect_stale_mirror([], ["2026-07-28"], bucket=None)


def test_unverifiable_s3_error_propagates():
    # AccessDenied / throttle / timeout are NOT "the object is absent" -- an unverifiable
    # occupancy picture must abort rather than pass.
    class _S3Boom:
        def head_object(self, **kw):
            err = Exception("denied")
            err.response = {"Error": {"Code": "AccessDenied"}}
            raise err

    with pytest.raises(Exception, match="denied"):
        prs.detect_stale_mirror([], ["2026-07-28"], bucket="b", s3_client=_S3Boom())


def test_cli_aborts_when_the_mirror_is_stale(monkeypatch):
    """(2026-07-29 incident, end to end) pg says the target asof is empty, S3 says it is OCCUPIED.

    This is the exact shape that let a backfill_grid replay overwrite a certified daily_sweep
    partition: the mirror's loader had never run for this ledger, so read_existing_guard_rows
    returned [] and apply_write_guard saw a clean partition. rc 3 (the unreadable-guard class),
    and the publisher is never reached.
    """
    _stub_cli_env(monkeypatch)
    monkeypatch.setattr(prs, "read_existing_guard_rows", lambda qfn, asofs: [])
    # re-arm with an S3 that says "occupied" -- the stale branch
    monkeypatch.setattr(prs, "detect_stale_mirror",
                        lambda existing, asofs, *, bucket, s3_client=None:
                        _STALE_DETECT(existing, asofs, bucket=bucket, s3_client=_S3Hit()))
    assert prs.main(["--dry-run"]) == 3, "a stale mirror must abort, in dry-run too"
    assert prs.main(["--publish-mode", "canonical"]) == 3
