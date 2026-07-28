"""T2B pattern-records SERVING surfaces (Writer B): the SQL-lane card, the COALESCE presence semantics
(F8), the OBSERVATION-register fence (D8), the GRAPHRAG_PATTERN_RECORDS kill-switch (byte-identity when
off), the persistence-question dispatch, the eval scoring hooks, and the drift guard vs the sweep task.

AWS-free: the presence/base-rate SQL is exercised against in-memory sqlite (ANSI COUNT/CASE/MIN/substr),
proving the SAME string a pg mirror runs returns a materialized 0 (not an empty set) for a pair with no
recorded firing -- the mechanism the empty-ledger honesty answer depends on.
"""
from __future__ import annotations

import sqlite3

import pytest

import jobs.batch.pattern_records_sweep_task as prs
from leviathan.graphrag import eval as ev
from leviathan.graphrag.numbers import agent as na
from leviathan.graphrag.numbers import pattern_records as pr
from leviathan.graphrag.numbers.registry import load_registry


# ── an in-memory ledger the presence/base-rate SQL runs against (the pg mirror shape) ──────────────
def _ledger_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE gold_pattern_records (record_kind TEXT, contract TEXT, driver_or_chain_id TEXT, "
        "verdict TEXT, decline_reason TEXT, as_of_date TEXT, written_at TEXT, provenance TEXT)")
    # `decline_reason` carries the Lane-A denominator split (2026-07-25 gate defect D1): a decline is a
    # real NON-EVENT only when the engine held data and produced no firing (thin_history); a
    # fetch/resolution failure is BLINDNESS and belongs in no rate's denominator. See
    # pattern_records.PR_NONEVENT_DECLINES / PR_BLIND_DECLINES.
    rows = [
        # corn_cbot/export_pace daily_sweep: 3 fired + 2 declined (a real, MEASURED recorded history).
        ("pace", "corn_cbot", "export_pace", "fired", None, "2026-07-20", "2026-07-20T09:00:00+00:00", "daily_sweep"),
        ("pace", "corn_cbot", "export_pace", "fired", None, "2026-07-21", "2026-07-21T09:00:00+00:00", "daily_sweep"),
        ("pace", "corn_cbot", "export_pace", "fired", None, "2026-07-22", "2026-07-22T09:00:00+00:00", "daily_sweep"),
        ("pace", "corn_cbot", "export_pace", "declined", "thin_history", "2026-07-23", "2026-07-23T09:00:00+00:00", "daily_sweep"),
        ("pace", "corn_cbot", "export_pace", "declined", "thin_history", "2026-07-24", "2026-07-24T09:00:00+00:00", "daily_sweep"),
        # soybeans_cbot/export_pace daily_sweep: in the swept catalog but EVERY sweep declined (F8: a
        # materialized recorded_firings=0, distinct from "not covered").
        ("pace", "soybeans_cbot", "export_pace", "declined", "thin_history", "2026-07-23", "2026-07-23T09:00:00+00:00", "daily_sweep"),
        ("pace", "soybeans_cbot", "export_pace", "declined", "thin_history", "2026-07-24", "2026-07-24T09:00:00+00:00", "daily_sweep"),
        # corn_cbot/export_pace backfill_grid: 8 fired + 6 thin_history (evaluated, did NOT fire) + 6
        # fetch_error (BLIND -- no vintage to replay against) => 8 of 14 EVALUABLE, 20 attempted. One
        # backfill row is written in the FUTURE relative to the query asof -> the PIT guard must drop it.
        *[("pace", "corn_cbot", "export_pace", "fired", None, f"2024-0{i}-01", "2026-07-10T00:00:00+00:00", "backfill_grid")
          for i in range(1, 9)],
        *[("pace", "corn_cbot", "export_pace", "declined", "thin_history", f"2024-0{i}-15", "2026-07-10T00:00:00+00:00", "backfill_grid")
          for i in range(1, 7)],
        *[("pace", "corn_cbot", "export_pace", "declined", "fetch_error", f"2023-0{i}-15", "2026-07-10T00:00:00+00:00", "backfill_grid")
          for i in range(1, 7)],
        ("pace", "corn_cbot", "export_pace", "fired", None, "2019-01-01", "2026-08-01T00:00:00+00:00", "backfill_grid"),
    ]
    conn.executemany(
        "INSERT INTO gold_pattern_records VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


def _qfn(conn):
    def run(sql: str):
        cur = conn.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    return run


# ── (F8) presence semantics: a scalar COUNT/COALESCE returns a materialized 0, never an empty set ──
def test_presence_returns_materialized_zero_for_declined_only_pair():
    qfn = _qfn(_ledger_conn())
    # a real recorded history: 3 fired of 5 daily sweeps.
    r = qfn(pr.presence_sql("corn_cbot", "export_pace", kind="pace", asof="2026-07-24"))[0]
    assert r["recorded_firings"] == 3 and r["sweeps_total"] == 5 and r["first_recorded"] == "2026-07-20"
    # every daily sweep here was EVALUATED, so the evaluable denominator equals the attempted total.
    assert r["sweeps_evaluable"] == 5 and r["first_evaluable"] == "2026-07-20"
    # in-catalog, ALL declined -> ONE row with recorded_firings=0 (NOT an empty set), sweeps_total>0.
    z = qfn(pr.presence_sql("soybeans_cbot", "export_pace", kind="pace", asof="2026-07-24"))[0]
    assert z["recorded_firings"] == 0 and z["sweeps_total"] == 2 and z["first_recorded"] is None
    assert z["sweeps_evaluable"] == 2, "declines that ran and did not fire are REAL non-events"
    # not covered: a pair with no rows STILL returns one scalar row (0/0) -- distinguishable via sweeps_total.
    n = qfn(pr.presence_sql("soft_red_winter_wheat_cbot", "export_pace", kind="pace", asof="2026-07-24"))
    assert len(n) == 1 and n[0]["recorded_firings"] == 0 and n[0]["sweeps_total"] == 0


def test_provenance_never_mixes_and_pit_guard_excludes_future_written_at():
    qfn = _qfn(_ledger_conn())
    # the default presence read (daily_sweep) must NOT fold in the backfill_grid fired rows.
    d = qfn(pr.presence_sql("corn_cbot", "export_pace", kind="pace", asof="2026-07-24"))[0]
    assert d["recorded_firings"] == 3, "daily_sweep read leaked backfill_grid rows (provenance mix)"
    # the labelled backfill base rate: 8 fired of 20 attempted -- the future-written_at row (2026-08-01)
    # is dropped by the written_at PIT guard, so it is 8/20 not 9/21.
    b = qfn(pr.baserate_backfill_sql("corn_cbot", "export_pace", kind="pace", asof="2026-07-24"))[0]
    assert b["recorded_firings"] == 8 and b["sweeps_total"] == 20
    # ...of which only 14 were EVALUABLE: the 6 fetch_error asofs are the engine being blind, not the
    # pair failing to fire (the "9 of 156" inversion the 2026-07-25 gate shipped).
    assert b["sweeps_evaluable"] == 14


def test_presence_sql_pins_one_provenance_class():
    daily = pr.presence_sql("corn_cbot", "export_pace", kind="pace", asof="2026-07-24")
    back = pr.baserate_backfill_sql("corn_cbot", "export_pace", kind="pace", asof="2026-07-24")
    assert "provenance = 'daily_sweep'" in daily and "backfill_grid" not in daily
    assert "provenance = 'backfill_grid'" in back and "daily_sweep" not in back
    # scalar aggregate (no GROUP BY) -> the F8 materialized-0 guarantee.
    assert "GROUP BY" not in daily.upper()


# ── serving dispatch: legs + signal + the OBSERVATION-register answer ──────────────────────────────
def test_legs_materialize_zero_and_signal_marks_it():
    qfn = _qfn(_ledger_conn())
    scope = {"contract": "soybeans_cbot", "driver_or_chain_id": "export_pace", "kind": "pace",
             "provenance": pr.PROV_DAILY_SWEEP}
    legs, sig = pr.pattern_records_legs(scope, "2026-07-24", qfn)
    assert len(legs) == 1 and sig["injected"] == 1
    assert sig["recorded_firings"] == 0 and sig["zero_materialized"] is True and sig["in_catalog"] is True
    line = pr.pattern_records_answer(scope, (1, legs[0]), sig)
    assert "no firing" in line.lower() and "[N1]" in line
    assert pr.pr_register_leaks(line) == []          # the honesty line is register-clean


def test_legs_backfill_baserate_cites_a_real_count():
    qfn = _qfn(_ledger_conn())
    scope = {"contract": "corn_cbot", "driver_or_chain_id": "export_pace", "kind": "pace",
             "provenance": pr.PROV_BACKFILL_GRID}
    legs, sig = pr.pattern_records_legs(scope, "2026-07-24", qfn)
    assert sig["recorded_firings"] == 8 and sig["sweeps_total"] == 20 and sig["zero_materialized"] is False
    assert sig["sweeps_evaluable"] == 14 and sig["rate_stated"] is True
    line = pr.pattern_records_answer(scope, (3, legs[0]), sig)
    # the rate is over what was EVALUABLE, and the incomplete coverage is stated in the same breath.
    assert "8 of the 14" in line and "weekly replay asofs" in line and "[N3]" in line
    assert "only 14 of the 20 attempted carried data" in line
    assert "8 of 20" not in line, "the raw attempted total must never be the rate's denominator"
    assert "daily sweep" not in line.lower()         # a backfill rate is NEVER phrased as daily sweeps
    assert pr.pr_register_leaks(line) == []


def test_legs_fail_closed_on_probe_error():
    def boom(_sql):
        raise RuntimeError("mirror gap")
    scope = {"contract": "corn_cbot", "driver_or_chain_id": "export_pace", "kind": "pace",
             "provenance": pr.PROV_DAILY_SWEEP}
    legs, sig = pr.pattern_records_legs(scope, "2026-07-24", boom)
    assert legs == [] and sig["injected"] == 0       # a mirror gap NEVER fabricates a firing


# ── (D8) OBSERVATION-register fence: the fixed serving strings + the detector ──────────────────────
def test_register_fence_flags_conclusion_vocab_and_serving_strings_are_clean():
    for bad in ("this is a bullish signal", "a clean set-up", "a regime shift", "the trend confirms",
                "a breakout", "momentum is building", "a persistent up-move"):
        assert pr.pr_register_leaks(bad), f"banned vocab not flagged: {bad!r}"
    # the reader-facing / agent-facing strings this module ships are themselves register-clean.
    assert pr.pr_register_leaks(pr.AGENT_CONVENTIONS_BULLET) == []
    assert pr.pr_register_leaks(pr.RECORDED_HISTORY_ADDENDUM) == []
    # honest observation vocabulary must NOT false-flag.
    for ok in ("the engine recorded 9 of 12 sweeps", "first recorded 2026-07-15", "no firing recorded yet"):
        assert pr.pr_register_leaks(ok) == [], f"honest text false-flagged: {ok!r}"


# ── the SQL-lane card: shape + register-clean copy ─────────────────────────────────────────────────
def test_card_shape_and_register_clean():
    ts = load_registry().get(pr.PR_TABLE)
    assert ts.shape == "wide" and ts.commodity_col == "contract"
    assert ts.period_col == "as_of_date" and ts.knowledge_date_col == "written_at"
    assert ts.knowledge_semantics == "ingest" and ts.date_col_type == "timestamp"
    # full natural key as grain_cols -> the latest-vintage ROW_NUMBER never ties across driver/kind.
    assert ts.grain_cols == ["record_kind", "contract", "driver_or_chain_id", "as_of_date"]
    # AGGREGATION-only card: NO declared metrics (so the F010 generator keeps the silver contract an
    # observation ledger -- value_columns=[] / no non-null floor, Writer A's ratified doctrine). The
    # base-rate/run-length reads are COUNT/MIN aggregations, not lookup_number metric reads.
    assert ts.metrics == {}
    from leviathan.silver.registry import load_registry as _silver_reg
    sc = _silver_reg().table("gold_pattern_records")
    assert sc["value_columns"] == [] and sc["min_nonnull_frac"] is None
    # the card copy is OBSERVATION register (no signal/set-up/regime/trend/breakout/persistent/confirms).
    assert pr.pr_register_leaks(ts.description) == [] and pr.pr_register_leaks(ts.notes) == []


# ── kill-switch: byte-identity when OFF, present when ON (agent.py + answer.py) ─────────────────────
def test_card_hidden_from_agent_when_flag_off(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_PATTERN_RECORDS", raising=False)
    reg = load_registry()
    assert pr.PR_TABLE in reg.tables                          # the card LOADS into the registry
    # ...but is filtered out of the tool enum + the system-prompt cards + the bullet when the flag is off.
    assert pr.PR_TABLE not in na._visible_tables(reg)
    schema = na.tool_schema(reg)
    assert pr.PR_TABLE not in schema["input_schema"]["properties"]["table"]["enum"]
    sp = na.system_prompt(reg, stats_tool=False)
    assert pr.PR_TABLE not in sp and pr.AGENT_CONVENTIONS_BULLET not in sp


def test_card_exposed_to_agent_when_flag_on(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_PATTERN_RECORDS", "on")
    reg = load_registry()
    assert pr.PR_TABLE in na._visible_tables(reg)
    schema = na.tool_schema(reg)
    assert pr.PR_TABLE in schema["input_schema"]["properties"]["table"]["enum"]
    sp = na.system_prompt(reg, stats_tool=False)
    assert pr.PR_TABLE in sp and pr.AGENT_CONVENTIONS_BULLET in sp


def test_visible_tables_off_equals_full_registry_minus_card(monkeypatch):
    """The byte-identity guarantee: with the flag OFF the exposed set is EXACTLY the pre-feature set
    (sorted(reg.tables) minus the one new card) -- so tool_schema + system_prompt are unchanged."""
    monkeypatch.delenv("GRAPHRAG_PATTERN_RECORDS", raising=False)
    reg = load_registry()
    assert na._visible_tables(reg) == sorted(t for t in reg.tables if t != pr.PR_TABLE)


def test_recorded_history_addendum_gated_in_answer_system(monkeypatch):
    from leviathan.graphrag import answer as an
    monkeypatch.delenv("GRAPHRAG_PATTERN_RECORDS", raising=False)
    assert pr.RECORDED_HISTORY_ADDENDUM not in an._system()
    monkeypatch.setenv("GRAPHRAG_PATTERN_RECORDS", "on")
    assert pr.RECORDED_HISTORY_ADDENDUM in an._system()


# ── persistence-question detection: fires on the deck asks, never on the existing decks ────────────
def test_scope_detects_persistence_and_picks_provenance():
    pos = pr.pattern_records_scope(
        "Historically, how often has US corn's export-pace leg fired on record -- the base rate across "
        "its weekly replay history?")
    assert pos == {"contract": "corn_cbot", "driver_or_chain_id": "export_pace", "kind": "pace",
                   "provenance": pr.PROV_BACKFILL_GRID}
    neg = pr.pattern_records_scope(
        "For US corn's export-pace leg, is this the first hot week on record or the ninth?")
    assert neg["provenance"] == pr.PROV_DAILY_SWEEP and neg["contract"] == "corn_cbot"
    # fail-closed: no driver keyword, or no persistence intent -> None.
    assert pr.pattern_records_scope("what were US corn ending stocks in 2023?") is None
    assert pr.pattern_records_scope("how many bushels of corn were exported?") is None


def test_scope_never_false_fires_on_existing_v3_deck():
    import yaml
    from leviathan.graphrag import extract as ex
    path = ex._CFG / "eval_queries_v3.yaml"
    rows = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("queries") or []
    for q in rows:
        if str(q.get("id", "")).startswith("pr_"):
            continue                                         # the pattern rows SHOULD match
        assert pr.pattern_records_scope(q.get("question") or "") is None, \
            f"scope false-fired on {q.get('id')!r}"


# ── eval scoring hooks: the pins read trace['pattern_records'] (the pace_fired idiom) ──────────────
def _out(pattern=None, answer="", tldr="", mech=""):
    tr = {}
    if pattern is not None:
        tr["pattern_records"] = pattern
    return {"trace": tr, "answer": answer, "structured": {"tldr": tldr, "mechanism": mech},
            "citations": [], "number_calls": []}


def test_eval_pattern_pins():
    # pos: a real base-rate cite -> pattern_cited true.
    q = {"expect": {"pattern_cited": True}}
    out = _out({"injected": 1, "recorded_firings": 6, "zero_materialized": False})
    assert ev._cascade_asserts(q, out)["pattern_cited"] is True
    # F8: a materialized-0 leg injected + cited -> pattern_zero_cited true.
    qz = {"expect": {"pattern_zero_cited": True}}
    outz = _out({"injected": 1, "recorded_firings": 0, "zero_materialized": True})
    assert ev._cascade_asserts(qz, outz)["pattern_zero_cited"] is True
    # THE F8 REGRESSION: if the card injects NOTHING, pattern_zero_cited must FAIL (not vacuously pass).
    out_nothing = _out({"injected": 0, "recorded_firings": 0, "zero_materialized": False})
    assert ev._cascade_asserts(qz, out_nothing)["pattern_zero_cited"] is False
    # register: a banned word on a pattern line fails the clean pin; a clean answer passes.
    qr = {"expect": {"pattern_register_clean": True}}
    assert ev._cascade_asserts(qr, _out({"injected": 1}, answer="a bullish signal is building"))[
        "pattern_register_clean"] is False
    assert ev._cascade_asserts(qr, _out({"injected": 1}, answer="recorded firing on 6 of 10 replay asofs"))[
        "pattern_register_clean"] is True


# ── drift guard: the serving read's vocabulary MUST equal what the sweep task wrote ────────────────
def test_constants_match_the_sweep_task():
    assert pr.PR_TABLE == prs.TABLE
    assert (pr.KIND_CASCADE, pr.KIND_PACE, pr.KIND_CHAIN) == (prs.KIND_CASCADE, prs.KIND_PACE, prs.KIND_CHAIN)
    assert pr.V1_KINDS == prs.V1_KINDS
    assert (pr.VERDICT_FIRED, pr.VERDICT_DECLINED) == (prs.VERDICT_FIRED, prs.VERDICT_DECLINED)
    assert (pr.PROV_DAILY_SWEEP, pr.PROV_BACKFILL_GRID) == (prs.PROV_DAILY_SWEEP, prs.PROV_BACKFILL_GRID)


# ── pg-mirror + parity membership ──────────────────────────────────────────────────────────────────
def test_pg_mirror_and_parity_membership():
    import jobs.utils.load_pg_numbers as lp
    import jobs.utils.numbers_parity as npar
    assert pr.PR_TABLE in lp.P1_TABLES
    assert npar.SAMPLE_COMMODITY.get(pr.PR_TABLE) == "corn_cbot"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
