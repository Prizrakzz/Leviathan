"""T2B pattern-records ledger core: the write-guard, provenance separation, idempotency, backfill
eligibility, pace decline re-derivation, and the chain-kind record from a quantify_chain fixture.

These exercise the PURE record-construction + guard + eligibility surface (fed engine trace entries /
fixtures) -- the pg-driven live sweep is validated at the rollout day-0 gate, not here. AWS-free.
"""
from __future__ import annotations

import io

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
# (F5 / sec 3.3) provenance separation: daily_sweep and backfill_grid never overwrite each other.
# ---------------------------------------------------------------------------
def test_provenance_separation_no_overwrite():
    asof = "2026-07-24"
    daily = prs.pace_record("corn_cbot", "export_pace", asof,
                            _ctx(provenance=prs.PROV_DAILY_SWEEP), entry=_PACE_ENTRY, n_rows=2)
    # a backfill re-derivation of the SAME natural key under a DIFFERENT engine -- it must NOT be refused
    # (different provenance class) and must NOT overwrite the daily_sweep row.
    backfill = prs.pace_record("corn_cbot", "export_pace", asof,
                               _ctx(engine="img:9", provenance=prs.PROV_BACKFILL_GRID), entry=_PACE_ENTRY, n_rows=2)
    assert daily.natural_key() == backfill.natural_key()
    assert daily.guard_key() != backfill.guard_key()   # provenance distinguishes them
    res = prs.apply_write_guard([daily], [backfill])
    assert len(res.writable) == 1 and res.refused == []


# ---------------------------------------------------------------------------
# (F2 / sec 3.1) backfill EXCLUDES oni / weather_z legs (period latest-only, not as-of replayable).
# ---------------------------------------------------------------------------
def test_backfill_excludes_oni_and_weather_z():
    assert prs.backfill_eligible(["silver_esr_compact"]) is True     # release-date vintaged
    assert prs.backfill_eligible(["silver_wasde"]) is True
    assert prs.backfill_eligible(["silver_psd"]) is True
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
def test_read_existing_guard_rows_pins_predicate_and_failsafe():
    seen = {}

    def qfn(sql):
        seen["sql"] = sql
        return [{"record_kind": "pace", "contract": "corn_cbot", "driver_or_chain_id": "export_pace",
                 "as_of_date": "2026-07-24", "provenance": prs.PROV_DAILY_SWEEP,
                 "engine_version": "img:1", "graph_version": "gv1:aaaa"}]

    rows = prs.read_existing_guard_rows(qfn, ["2026-07-24"], prs.PROV_DAILY_SWEEP)
    assert len(rows) == 1 and rows[0]["engine_version"] == "img:1"
    assert prs.TABLE in seen["sql"]
    assert "provenance = 'daily_sweep'" in seen["sql"] and "'2026-07-24'" in seen["sql"]
    # a pg date object / timestamp is normalized to the 'YYYY-MM-DD' string the incoming records key on.
    norm = prs.read_existing_guard_rows(
        lambda s: [{"record_kind": "pace", "contract": "c", "driver_or_chain_id": "d",
                    "as_of_date": "2026-07-24T00:00:00", "provenance": prs.PROV_DAILY_SWEEP,
                    "engine_version": "e", "graph_version": "g"}], ["2026-07-24"], prs.PROV_DAILY_SWEEP)
    assert norm[0]["as_of_date"] == "2026-07-24"
    # fail-safe: a missing table / mirror gap -> [] (a first write is NEVER blocked), never an Athena retry.
    def boom(sql):
        raise RuntimeError("relation gold_pattern_records does not exist")
    assert prs.read_existing_guard_rows(boom, ["2026-07-24"], prs.PROV_DAILY_SWEEP) == []
    assert prs.read_existing_guard_rows(qfn, [], prs.PROV_DAILY_SWEEP) == []   # no asofs -> no query


def test_write_guard_runtime_composition_read_then_refuse():
    """(F1 wiring) the runtime path composes read_existing_guard_rows -> apply_write_guard: an existing img:1
    row + an incoming img:2 re-run of the SAME key is REFUSED (never a silent overwrite), while a
    same-version re-run through the same read path is a clean idempotent replace."""
    asof = "2026-07-24"
    stored = {"record_kind": "pace", "contract": "corn_cbot", "driver_or_chain_id": "export_pace",
              "as_of_date": asof, "provenance": prs.PROV_DAILY_SWEEP,
              "engine_version": "img:1", "graph_version": "gv1:aaaa"}
    existing = prs.read_existing_guard_rows(lambda s: [stored], [asof], prs.PROV_DAILY_SWEEP)
    bumped = prs.pace_record("corn_cbot", "export_pace", asof, _ctx(engine="img:2"), entry=_PACE_ENTRY, n_rows=2)
    res = prs.apply_write_guard(existing, [bumped])
    assert res.writable == [] and len(res.refused) == 1
    same = prs.pace_record("corn_cbot", "export_pace", asof, _ctx(engine="img:1", graph="gv1:aaaa"),
                           entry=_PACE_ENTRY, n_rows=2)
    res2 = prs.apply_write_guard(existing, [same])
    assert len(res2.writable) == 1 and res2.refused == []


# ---------------------------------------------------------------------------
# (finding 4) a non-backfill sweep at a BACKDATED asof is refused before any pg/AWS work: it would record
# daily_sweep rows from TODAY's restated data at a past as_of_date that leak into the serving PIT read.
# ---------------------------------------------------------------------------
def test_daily_sweep_refuses_past_asof():
    assert prs.main(["--asof", "1990-01-01"]) == 2          # past asof + not --backfill -> refused (rc 2)
