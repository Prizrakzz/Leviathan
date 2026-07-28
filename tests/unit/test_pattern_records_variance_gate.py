"""T2B Lane A -- THE VARIANCE GATE, THE VINTAGE DENOMINATOR, AND THE LEAKAGE FENCE (coverage-plan W2/W4).

The coverage floor shipped in 2026-07-25 gates on how MANY sweeps were evaluable. A re-census of the live
ledger proves that is the wrong QUANTITY, not merely the wrong threshold. Probed today by direct
pyarrow/boto3 read of s3://leviathan-dev-shahem-001/gold/pattern_records/ (zero Athena; `_shadow/` and
`_manifests/` excluded -- counting the shadow copies double-reports every figure):

    158 canonical partitions  ·  39,658 rows  ·  provenance backfill_grid 39,658 / daily_sweep 0
    record_kind: cascade 38,236 · pace 1,422 · chain 0
    251 distinct (record_kind, contract, driver_or_chain_id) pairs, whose (fired, evaluable) takes
    EXACTLY THREE values and every one of them is a CONSTANT:

        (158, 158) -> 163 pairs   cascade   fired on every sweep it could evaluate
        (  0,   0) ->  79 pairs   cascade   never evaluable at all (region-unresolved 70 / waived 9)
        ( 11,  11) ->   9 pairs   pace      fired on every sweep it could evaluate

    Pairs with 0 < fired < evaluable -- the only shape that HAS a rate -- number ZERO, at every floor
    height (>=8 / >=13 / >=20 all admit 163-172 pairs; non-degenerate 0 at each).

    NOTE the census counts rows PRESENT ON S3. A PIT-guarded read sees fewer: the last two partitions
    (2026-07-26/27, the healed nights) carry written_at 2026-07-28, so a query at asof=2026-07-27 honestly
    reports 156 sweeps / 9 firings -- verified against the live pg mirror in-VPC. Both figures are true;
    they answer different questions. The fixtures below stamp an early written_at so the full grid is
    visible, which is what makes the shapes testable.

So a count floor admits 172 pairs and all 172 would print 100%. These tests pin the two predicates that
close that (DISCRIMINATION and VINTAGE DEPTH), pin that every one of the 251 live shapes is suppressed --
so the day the number goes non-zero it is because real variance ARRIVED, not because a threshold drifted --
and pin that the branches the gates do not touch render BYTE-IDENTICALLY to the pre-gate build.

THE VINTAGE INVESTIGATION, recorded here because the implementation is only honest if its limits are:
the ledger does NOT record the resolved source vintage. The physical schema is 19 columns and none of them
is a vintage; `extra` is the only free-form slot and across all 158 partitions it holds exactly three keys
(`collapse`, `metric`, `table`) with ZERO date-like values anywhere. A true COUNT(DISTINCT vintage) is
therefore NOT COMPUTABLE from this ledger. What is implemented is a named approximation -- distinct
RECORDED VALUE-STATES -- whose error is measured rather than assumed: on the one pair whose truth is known
(corn_cbot x export_pace, 11 fired sweeps off 3 ESR vintages, 2026-05-24 serving seven of them) the proxy
returns 2. It UNDER-counts, which is the fail-closed direction. See PR_MIN_DISTINCT_VINTAGES.

AWS-free: the same ANSI SQL serving runs on the pg mirror is exercised against in-memory sqlite.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3

from leviathan.graphrag import orchestrator as orc
from leviathan.graphrag.numbers import pattern_records as pr

import jobs.batch.pattern_records_sweep_task as prs

WRITTEN_AT = "2026-07-25 08:57:27.175221"
ASOF = "2026-07-27"                                   # the newest canonical partition
SCOPE = {"contract": "corn_cbot", "driver_or_chain_id": "export_pace", "kind": pr.KIND_PACE,
         "provenance": pr.PROV_BACKFILL_GRID}

# The probed per-pair census: (fired, evaluable) -> how many of the 251 pairs carry that shape.
LIVE_SHAPES = {(158, 158): 163, (0, 0): 79, (11, 11): 9}


# ── fixtures ───────────────────────────────────────────────────────────────────────────────────────
def _conn(rows, states=None, *, kind=None, provenance="backfill_grid"):
    """rows = [(as_of_date, verdict, decline_reason)]. Carries the VALUE-BEARING columns because the
    production table carries them (they are physical columns of the registered contract and the pg mirror
    loads all of them) and the vintage-depth probe reads them.

    `states` = how many DISTINCT window_change values the fired sweeps take; None = one per fired asof
    (every sweep saw a fresh source snapshot). Declines record no measurement at all -- exactly as the
    writer leaves them -- so they all collapse into one further state. A row may carry an explicit
    window_change as a 4th tuple element, which is how the real probed series is reproduced.

    n_points is deliberately populated with an ASOF-VARYING value: in production it counts down within a
    single vintage, and a fixture that held it constant would hide the very failure that ruled it out of
    PR_VINTAGE_STATE_COLUMNS."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE gold_pattern_records (record_kind TEXT, contract TEXT, "
              "driver_or_chain_id TEXT, verdict TEXT, decline_reason TEXT, as_of_date TEXT, "
              "written_at TEXT, provenance TEXT, window_change REAL, n_points INTEGER, "
              "streak_len INTEGER, streak_dir TEXT, n_rows INTEGER, grain TEXT)")
    out, nfired = [], 0
    for row in rows:
        d, v, r = row[0], row[1], row[2]
        explicit = row[3] if len(row) > 3 else None
        wc = np = gr = None
        nr = 0
        if v == "fired":
            wc = explicit if explicit is not None else float(nfired % states if states else nfired) + 0.5
            np, nr, gr, nfired = 40 - nfired, 1, "week", nfired + 1
        out.append((kind or pr.KIND_PACE, "corn_cbot", "export_pace", v, r, d, WRITTEN_AT,
                    provenance, wc, np, None, None, nr, gr))
    c.executemany("INSERT INTO gold_pattern_records VALUES (" + ",".join(["?"] * 14) + ")", out)
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


def _weekly(end: str, n: int) -> list[str]:
    e = _dt.date.fromisoformat(end)
    return [(e - _dt.timedelta(weeks=i)).isoformat() for i in range(n - 1, -1, -1)]


def _answer(rows, states=None, scope=None, seen=None, **conn_kw):
    scope = scope or SCOPE
    legs, sig = pr.pattern_records_legs(scope, ASOF, _qfn(_conn(rows, states, **conn_kw), seen))
    line = pr.pattern_records_answer(scope, (1, legs[0]), sig) if legs else None
    return legs, sig, line


G158 = _weekly(ASOF, 158)


def _flagship_pace() -> list[tuple]:
    """The LIVE pace shape: 158 weekly asofs, the last 11 fired, the other 147 blind on fetch_error
    (the ESR vintage snapshots begin 2026-05-24, so everything before it had nothing to replay against)."""
    return ([(d, "declined", "fetch_error") for d in G158[:-11]]
            + [(d, "fired", None) for d in G158[-11:]])


def _all_fired() -> list[tuple]:
    return [(d, "fired", None) for d in G158]


def _never_evaluable() -> list[tuple]:
    return [(d, "declined", "region-unresolved") for d in G158]


# ── (1) THE HEADLINE PROPERTY: every shape in the live ledger is suppressed ────────────────────────
def test_every_one_of_the_251_live_pair_shapes_is_suppressed():
    """The regression this whole workstream exists to prevent. If this count ever goes non-zero it must be
    because a pair acquired REAL variance, never because a threshold moved."""
    assert sum(LIVE_SHAPES.values()) == 251, "the census must cover every pair, or the pin is partial"
    statable = []
    for (fired, evaluable), n in LIVE_SHAPES.items():
        # generous on the axis NOT under test: hand the gate a fully-resolved vintage depth, so a pair
        # that still fails is failing on discrimination alone rather than on a missing probe.
        gate = pr.pr_rate_gate(in_catalog=True, recorded=fired, evaluable=evaluable,
                               vintage_depth=evaluable)
        if gate is None:
            statable.append(((fired, evaluable), n))
        assert gate in (pr.PR_SUP_NOTHING_EVALUABLE, pr.PR_SUP_TOO_THIN, pr.PR_SUP_NO_VARIANCE), \
            f"shape {(fired, evaluable)} x{n} suppressed for an unexpected reason: {gate}"
    assert statable == [], f"a live pair shape can state a rate: {statable}"


def test_a_count_floor_alone_would_have_admitted_163_of_them_at_any_height():
    """Anti-vacuity for the test above: the OLD predicate (fired>0 AND enough evaluable sweeps) passes
    163 pairs on this census, so the new predicates are doing the work -- these shapes are not being
    suppressed by the floor they already cleared. And no floor height rescues it: the admitted set is 172
    at a height of 8 and 163 at 12/13/20, non-degenerate ZERO at every one of them."""
    def _old(height):
        return sum(n for (fired, evaluable), n in LIVE_SHAPES.items()
                   if fired > 0 and evaluable >= height)
    assert _old(pr.PR_MIN_EVALUABLE_SWEEPS) == 163      # the SHIPPED height
    assert (_old(8), _old(12), _old(20)) == (172, 163, 163)
    non_degenerate = sum(n for (fired, evaluable), n in LIVE_SHAPES.items() if 0 < fired < evaluable)
    assert non_degenerate == 0, "every admitted pair is a constant -- that is the whole finding"


def test_the_discrimination_gate_is_exactly_the_open_interval():
    """0 < fired < evaluable, and nothing else, once coverage clears the floor."""
    n = pr.PR_MIN_EVALUABLE_SWEEPS + 5
    for fired, want in ((0, pr.PR_SUP_NO_FIRING), (1, None), (n - 1, None), (n, pr.PR_SUP_NO_VARIANCE)):
        assert pr.pr_rate_gate(in_catalog=True, recorded=fired, evaluable=n, vintage_depth=n) == want
    # a malformed mirror claiming MORE firings than evaluable sweeps is a constant, never a >100% rate.
    assert pr.pr_rate_gate(in_catalog=True, recorded=n + 3, evaluable=n,
                           vintage_depth=n) == pr.PR_SUP_NO_VARIANCE


# ── (2) the 100%-of-measurable case SAYS "all", and says it is a constant ──────────────────────────
def test_all_n_sentence_renders_on_the_hundred_percent_of_measurable_shape():
    _legs, sig, line = _answer(_all_fired())
    assert sig["recorded_firings"] == 158 and sig["sweeps_evaluable"] == 158
    assert sig["rate_stated"] is False and sig["rate_suppressed"] == pr.PR_SUP_NO_VARIANCE
    assert "on all 158" in line, "100%-of-measurable must SAY all, not print a fraction"
    assert "158 of the 158" not in line and "158 of 158" not in line
    # ...and must not leave the reader to infer that "all" was a rate.
    assert "this is a constant over the window named, not a firing rate" in line
    assert pr.pr_register_leaks(line) == []


def test_the_constant_branch_never_uses_the_word_rate_as_if_it_had_one():
    """The pre-gate build appended '...so that rate covers only the window named' to the all-fired branch
    when coverage was partial -- the one place the constant was narrated as a rate."""
    rows = ([(d, "declined", "fetch_error") for d in G158[:100]]
            + [(d, "fired", None) for d in G158[100:]])
    _legs, sig, line = _answer(rows)
    assert sig["rate_suppressed"] == pr.PR_SUP_NO_VARIANCE
    assert "so that rate covers only the window named" not in line
    assert "only 58 of the 158 attempted carried data" in line       # the coverage clause SURVIVES
    assert "not a firing rate" in line


# ── (3) THE VINTAGE DENOMINATOR ────────────────────────────────────────────────────────────────────
def test_repeated_source_snapshots_suppress_the_rate_even_with_variance_and_coverage():
    """The 2026-05-24-served-seven-asofs shape, generalised: 20 evaluable sweeps, genuine variance
    (16 of 20 fired), and only a handful of distinct source states behind them."""
    g = _weekly(ASOF, 20)
    rows = [(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None) for i, d in enumerate(g)]
    _legs, sig, line = _answer(rows, states=2)
    assert sig["sweeps_evaluable"] == 20 and sig["recorded_firings"] == 16   # clears floor, non-degenerate
    assert sig["vintage_depth"] == 3, "2 distinct fired states + the one state every decline shares"
    assert sig["rate_stated"] is False and sig["rate_suppressed"] == pr.PR_SUP_VINTAGE
    assert "16 of the 20" not in line, "the ratio must not be rendered anyway"
    assert "16 firings across the 20" in line, "the COUNT and the denominator are facts and stay"
    assert "too few distinct source vintages" in line
    assert pr.pr_register_leaks(line) == []


def test_deep_vintages_let_the_same_slice_state_its_rate():
    """Anti-vacuity: the ONLY difference from the test above is how many distinct source states the same
    16-of-20 slice stands on. The gate must be measuring that, not silently suppressing everything."""
    g = _weekly(ASOF, 20)
    rows = [(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None) for i, d in enumerate(g)]
    _legs, sig, line = _answer(rows)                     # default: a fresh state per fired sweep
    assert sig["vintage_depth"] == 17 and sig["rate_stated"] is True
    assert sig["rate_suppressed"] is None
    assert "16 of the 20" in line


def test_the_estimate_is_never_printed_because_it_is_an_approximation():
    """Only RECORDED OBSERVATIONS are stated as figures. The depth is a proxy, so it rides the signal and
    never the prose -- which is also what keeps the verifier able to ground every stated figure."""
    g = _weekly(ASOF, 20)
    rows = [(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None) for i, d in enumerate(g)]
    _legs, sig, line = _answer(rows, states=2)
    assert sig["vintage_depth"] == 3
    assert " 3 " not in line and "3 distinct" not in line and "3 source" not in line


def test_an_unknowable_vintage_depth_suppresses_the_rate_but_never_the_leg():
    """A mirror that predates the value columns cannot answer the depth probe. That must cost the RATE and
    nothing else: the citable count is the anti-fabrication mechanism and it always survives."""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE gold_pattern_records (record_kind TEXT, contract TEXT, "
              "driver_or_chain_id TEXT, verdict TEXT, decline_reason TEXT, as_of_date TEXT, "
              "written_at TEXT, provenance TEXT)")     # NO value columns -- the depth probe will raise
    g = _weekly(ASOF, 20)
    c.executemany("INSERT INTO gold_pattern_records VALUES (?,?,?,?,?,?,?,?)",
                  [(pr.KIND_PACE, "corn_cbot", "export_pace",
                    "declined" if i % 5 == 0 else "fired", "thin_history" if i % 5 == 0 else None,
                    d, WRITTEN_AT, "backfill_grid") for i, d in enumerate(g)])
    c.commit()
    legs, sig = pr.pattern_records_legs(SCOPE, ASOF, _qfn(c))
    assert len(legs) == 1 and sig["injected"] == 1               # the leg SURVIVES
    assert sig["recorded_firings"] == 16 and sig["sweeps_evaluable"] == 20
    assert sig["vintage_depth"] is None
    assert sig["rate_stated"] is False and sig["rate_suppressed"] == pr.PR_SUP_VINTAGE


def test_unknown_depth_is_suppressive_in_the_gate_itself():
    n = pr.PR_MIN_EVALUABLE_SWEEPS + 5
    assert pr.pr_rate_gate(in_catalog=True, recorded=3, evaluable=n,
                           vintage_depth=None) == pr.PR_SUP_VINTAGE
    assert pr.pr_rate_gate(in_catalog=True, recorded=3, evaluable=n,
                           vintage_depth=pr.PR_MIN_DISTINCT_VINTAGES - 1) == pr.PR_SUP_VINTAGE
    assert pr.pr_rate_gate(in_catalog=True, recorded=3, evaluable=n,
                           vintage_depth=pr.PR_MIN_DISTINCT_VINTAGES) is None


def test_the_cadence_cap_bounds_the_proxys_one_fail_open_mode():
    """A single vintage read at many asofs could in principle yield many distinct values and inflate the
    state count. It cannot inflate it past the number of weeks that elapsed."""
    assert pr._cadence_cap("2026-05-30", "2026-07-27", 60) == 9      # 58 days -> 8 whole weeks + 1
    assert pr._cadence_cap("2026-07-27", "2026-07-27", 40) == 1      # one day, one possible vintage
    # unparseable dates make the cap INERT rather than zeroing the estimate: the proxy is already the
    # fail-closed half, and a broken date must not silently kill an otherwise-legitimate rate.
    assert pr._cadence_cap(None, None, 22) == 22


def test_the_depth_probe_is_lazy_so_it_costs_nothing_on_todays_ledger():
    """Every one of the 251 live pairs is suppressed by a cheaper gate, so the widened-schema query is
    never issued at all. Serving keeps its one-query-per-turn cost exactly."""
    seen = []
    _answer(_flagship_pace(), seen=seen)                        # too_thin -- decided from the row in hand
    assert len(seen) == 1 and "distinct_value_states" not in seen[0]
    seen = []
    _answer(_all_fired(), seen=seen)                            # no_variance -- likewise
    assert len(seen) == 1 and "distinct_value_states" not in seen[0]
    seen = []
    g = _weekly(ASOF, 20)                                       # the ONLY shape that pays for the probe
    _answer([(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None)
             for i, d in enumerate(g)], seen=seen)
    assert len(seen) == 2 and "distinct_value_states" in seen[1]


def test_vintage_sql_is_ansi_scalar_and_pins_provenance_and_both_pit_axes():
    sql = pr.vintage_depth_sql("corn_cbot", "export_pace", kind=pr.KIND_PACE, asof=ASOF,
                               provenance=pr.PROV_BACKFILL_GRID)
    assert "COUNT(DISTINCT" in sql and "GROUP BY" not in sql.upper()   # scalar: always exactly one row
    assert "'backfill_grid'" in sql and "'daily_sweep'" not in sql     # provenance NEVER mixes
    assert sql.count("substr(cast(") == 2            # as_of_date AND written_at PIT guards, as presence_sql
    for col in pr.PR_VINTAGE_STATE_COLUMNS:
        assert f"CAST({col} AS varchar)" in sql
    for r in sorted(pr.PR_NONEVENT_DECLINES):        # the count is over EVALUABLE sweeps only
        assert f"'{r}'" in sql


def test_the_proxy_uses_only_the_vintage_stable_measurement():
    """THE COLUMN CHOICE, pinned -- it was decided by measuring the live ledger, and the first attempt was
    wrong in the dangerous direction. Probed over corn_cbot x export_pace's 11 fired sweeps, whose true
    vintages are known (2026-05-24 served seven, 07-17 one, 07-24 three):

        window_change  2 distinct  ONE VALUE PER VINTAGE on all three  -> vintage-stable
        n_points       8 distinct  counts DOWN 8,7,6,5,4,3,2 across the seven asofs ONE snapshot served
        streak_len / streak_dir / n_rows  follow n_points and also vary inside a single vintage
        grain          1 distinct  constant, no information

    window_change is stable by construction (computed on the terminal windows of a fixed series); the
    others slide with the asof. Including them turned 3 true vintages into NINE states -- a FAIL-OPEN
    gate, the one direction this must never fail."""
    assert pr.PR_VINTAGE_STATE_COLUMNS == ("window_change",)
    for asof_varying in ("n_points", "streak_len", "streak_dir", "n_rows"):
        assert asof_varying not in pr.PR_VINTAGE_STATE_COLUMNS, \
            f"{asof_varying} varies WITHIN a vintage -- counting it inflates the depth estimate"


def test_the_real_probed_series_yields_the_measured_under_count():
    """The investigation's headline number, reproduced from the actual recorded values. The 11 fired
    sweeps carry exactly two distinct window_change values (-217.637 for every asof vintage 2026-05-24
    served, -251.438 for the rest) against THREE true vintages, because 2026-07-17 and 2026-07-24 collide.
    2 < 3 -- the proxy under-counts, which is the fail-closed direction."""
    real_wc = {"2026-05-30": -217.637, "2026-06-06": -217.637, "2026-06-13": -217.637,
               "2026-06-20": -217.637, "2026-06-27": -217.637, "2026-07-04": -217.637,
               "2026-07-11": -217.637, "2026-07-18": -251.438, "2026-07-25": -251.438,
               "2026-07-26": -251.438, "2026-07-27": -251.438}
    fired = [(d, "fired", None, wc) for d, wc in sorted(real_wc.items())]
    blind = [(d, "declined", "fetch_error") for d in G158[:-11]]
    conn = _conn(blind + fired)
    # The estimator is exercised DIRECTLY: end to end this pair is suppressed by the coverage floor first
    # (11 < 13) and the lazy probe never runs, so the signal's depth is None. That is correct behaviour --
    # and it is exactly why the measured property needs its own pin here.
    depth = pr._vintage_depth("corn_cbot", "export_pace", kind=pr.KIND_PACE, asof=ASOF,
                              provenance=pr.PROV_BACKFILL_GRID, evaluable=11,
                              first_evaluable="2026-05-30", last_evaluable="2026-07-27",
                              query_fn=_qfn(conn))
    assert depth == 2, "the measured proxy value on the real recorded series"
    assert depth < 3, "under-counts the 3 true vintages -- fail-closed, by measurement"
    _legs, sig, _line = _answer(blind + fired)
    assert sig["recorded_firings"] == 11 and sig["sweeps_evaluable"] == 11
    assert sig["rate_suppressed"] == pr.PR_SUP_TOO_THIN and sig["vintage_depth"] is None


def test_the_state_columns_are_real_columns_of_the_writers_contract():
    """DRIFT GUARD. If the writer renames or drops one of these, the depth probe raises, depth goes None
    and EVERY rate is suppressed forever -- silently, because fail-closed failures are quiet. Pin the
    dependency so the writer's change breaks a test instead of the feature."""
    assert set(pr.PR_VINTAGE_STATE_COLUMNS) <= set(prs.COLUMNS), \
        f"not writer columns: {sorted(set(pr.PR_VINTAGE_STATE_COLUMNS) - set(prs.COLUMNS))}"


def test_the_ledger_records_no_vintage_which_is_why_the_proxy_exists():
    """The finding this design rests on, pinned against the writer rather than against a comment: NOTHING
    the writer emits names the resolved source vintage. `extra` is the only free-form slot and the three
    builders put table/metric/collapse/window/path/hop in it -- never a vintage. The day a vintage IS
    recorded, this test fails and the honest COUNT(DISTINCT vintage) replaces the approximation."""
    import inspect
    src = "".join(inspect.getsource(f) for f in (prs.pace_record, prs.cascade_record, prs.chain_record))
    for token in ("vintage", "release_date", "as_of_vintage", "source_vintage"):
        assert token not in src, f"the writer now records {token!r} -- replace the proxy with the truth"
    assert "vintage" not in " ".join(prs.COLUMNS)


# ── (4) THE LEAKAGE FENCE (W4, read side) ──────────────────────────────────────────────────────────
def test_cascade_backfill_grid_is_refused_at_the_read_seam():
    """The silver_psd as-of axis those verdicts were replayed against is synthesized, so they are audit
    bytes, not citable history. Serving has no cascade path today -- this is a ratchet, not a fix."""
    scope = {"contract": "corn_cbot", "driver_or_chain_id": "psd_ending_stock_su_ratio",
             "kind": pr.KIND_CASCADE, "provenance": pr.PROV_BACKFILL_GRID}
    seen = []
    legs, sig = pr.pattern_records_legs(
        scope, ASOF, _qfn(_conn(_all_fired(), kind=pr.KIND_CASCADE), seen))
    assert legs == [], "a fenced pair must inject NO citable row"
    assert sig["injected"] == 0 and sig["rate_stated"] is False
    assert sig["fenced"] == "cascade_backfill_leaky_asof"
    assert seen == [], "the refusal must not depend on what the ledger holds -- no query is issued"
    assert pr.pattern_records_answer(scope, None, sig) is None


def test_the_fence_is_narrow_and_deliberate():
    """Only the REPLAY over a manufactured axis is leaked. A verdict recorded on the day it was reached
    has a real as-of, and the pace lane's ESR vintages are genuine."""
    assert pr.pr_read_fenced(pr.KIND_CASCADE, pr.PROV_BACKFILL_GRID) == "cascade_backfill_leaky_asof"
    assert pr.pr_read_fenced(pr.KIND_CASCADE, pr.PROV_DAILY_SWEEP) is None
    assert pr.pr_read_fenced(pr.KIND_PACE, pr.PROV_BACKFILL_GRID) is None
    assert pr.pr_read_fenced(pr.KIND_PACE, pr.PROV_DAILY_SWEEP) is None
    assert pr.pr_read_fenced(pr.KIND_CHAIN, pr.PROV_BACKFILL_GRID) is None


def test_the_fenced_class_is_the_bulk_of_the_ledger():
    """Scale of what the fence covers, from the census: 37,752 of the 39,658 rows are cascade x
    backfill_grid (242 pairs x 156 of the partitions), i.e. 96.4% of the ledger by row."""
    assert (pr.KIND_CASCADE, pr.PROV_BACKFILL_GRID) in pr.PR_FENCED_READS
    assert len(pr.PR_FENCED_READS) == 1, "widening the fence is a decision, not a drive-by"


def test_the_unfenced_pace_path_still_injects_its_leg():
    legs, sig, line = _answer(_flagship_pace())
    assert len(legs) == 1 and sig["injected"] == 1 and sig["fenced"] is None and line


# ── (5) BYTE-IDENTITY where the new gates do not fire ──────────────────────────────────────────────
# Rendered from the pre-gate module at commit 598c2cba and pinned verbatim. Anything that moves one of
# these strings is changing an answer the gates were never supposed to touch.
HEAD_FLAGSHIP = (
    "For export_pace on corn_cbot, the engine has recorded 11 firings, 2026-05-18 to 2026-07-27 [N1]. "
    "Only 11 of the 158 attempted weekly replay asofs carried data it could evaluate, which is too short "
    "a recorded history to state a firing rate.")
HEAD_NOTHING_EVALUABLE = (
    "For export_pace on corn_cbot, the engine attempted 158 weekly replay asofs and could not evaluate "
    "any of them [N1] -- no firing history has been measured for this pair yet, so I cannot state a run "
    "length or a rate.")
HEAD_HONEST_ZERO = (
    "For export_pace on corn_cbot, the engine has recorded no firing on any of the 11 weekly replay asofs "
    "it could evaluate, 2026-05-18 to 2026-07-27 [N1] -- only 11 of the 158 attempted carried data. There "
    "is no recorded firing history for this pair yet, so I cannot state a run length, and that history is "
    "too short to read as a rate.")
HEAD_NOT_COVERED = (
    "The engine has not recorded this pair in the swept ledger yet [N1], so there is no recorded firing "
    "history to cite.")
HEAD_RATE = (
    "For export_pace on corn_cbot, the engine has recorded firing on 16 of the 20 weekly replay asofs it "
    "could evaluate, 2026-03-16 to 2026-07-27 [N1], first recorded 2026-03-23.")


def test_the_live_pace_shape_renders_byte_identically():
    """The 11-of-11 flagship lands BELOW the coverage floor, which is tested before the variance
    predicate, so the sentence a desk would see today is unchanged to the byte."""
    _legs, sig, line = _answer(_flagship_pace())
    assert sig["rate_suppressed"] == pr.PR_SUP_TOO_THIN
    assert line == HEAD_FLAGSHIP


def test_the_honest_zero_and_not_covered_branches_render_byte_identically():
    g = G158
    _l1, _s1, blind = _answer([(d, "declined", "region-unresolved") for d in g])
    assert blind == HEAD_NOTHING_EVALUABLE
    _l2, _s2, zero = _answer([(d, "declined", "fetch_error") for d in g[:-11]]
                             + [(d, "declined", "thin_history") for d in g[-11:]])
    assert zero == HEAD_HONEST_ZERO
    _l3, _s3, none_covered = _answer([])
    assert none_covered == HEAD_NOT_COVERED


def test_a_genuinely_statable_rate_renders_byte_identically():
    g = _weekly(ASOF, 20)
    _legs, sig, line = _answer([(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None)
                                for i, d in enumerate(g)])
    assert sig["rate_stated"] is True
    assert line == HEAD_RATE


# ── (6) the wordings are DISTINCT: six facts, six sentences ────────────────────────────────────────
def _one_of_each() -> dict:
    g20, g40 = _weekly(ASOF, 20), _weekly(ASOF, 40)
    out = {}
    out[pr.PR_SUP_NOT_COVERED] = _answer([])[2]
    out[pr.PR_SUP_NOTHING_EVALUABLE] = _answer(_never_evaluable())[2]
    out[pr.PR_SUP_NO_FIRING] = _answer([(d, "declined", "thin_history") for d in g20])[2]
    out[pr.PR_SUP_TOO_THIN] = _answer(_flagship_pace())[2]
    out[pr.PR_SUP_NO_VARIANCE] = _answer(_all_fired())[2]
    out[pr.PR_SUP_VINTAGE] = _answer(
        [(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None)
         for i, d in enumerate(g20)], states=2)[2]
    out[None] = _answer([(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None)
                         for i, d in enumerate(g40)])[2]
    return out


def test_each_suppression_reason_gets_its_own_distinguishable_sentence():
    """Not covered / nothing measured / measured-and-never-fired / too short / a constant / too few
    vintages are SIX DIFFERENT FACTS. If any two shared wording, a reader could not tell 'we never looked'
    from 'we looked and it was always true' -- the exact confusion this card exists to end."""
    lines = _one_of_each()
    assert len(set(lines.values())) == len(lines), "two suppression facts render the same sentence"
    marker = {
        pr.PR_SUP_NOT_COVERED: "not recorded this pair in the swept ledger yet",
        pr.PR_SUP_NOTHING_EVALUABLE: "could not evaluate any of them",
        pr.PR_SUP_NO_FIRING: "recorded no firing on any of the",
        pr.PR_SUP_TOO_THIN: "too short a recorded history to state a firing rate",
        pr.PR_SUP_NO_VARIANCE: "not a firing rate",
        pr.PR_SUP_VINTAGE: "too few distinct source vintages",
    }
    for slug, phrase in marker.items():
        assert phrase in lines[slug], f"{slug}: missing its own marker {phrase!r}"
        for other, line in lines.items():
            if other != slug:
                assert phrase not in line, f"{slug}'s marker {phrase!r} also appears in {other}"


def test_the_signal_slug_and_the_rendered_sentence_can_never_disagree():
    """One gate call decides both. A drift here would let the eval score a suppression the reader never
    saw (or the reverse), which is how a quality regression becomes invisible."""
    for rows, states in ((_flagship_pace(), None), (_all_fired(), None), (_never_evaluable(), None),
                         ([], None), ([(d, "fired", None) for d in _weekly(ASOF, 20)], None),
                         ([(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None)
                           for i, d in enumerate(_weekly(ASOF, 20))], 2)):
        legs, sig, line = _answer(rows, states=states)
        recomputed = pr.pr_rate_gate(in_catalog=bool(sig["in_catalog"]),
                                     recorded=sig["recorded_firings"],
                                     evaluable=sig["sweeps_evaluable"],
                                     vintage_depth=sig["vintage_depth"])
        assert sig["rate_suppressed"] == recomputed
        assert sig["rate_stated"] is (recomputed is None)
        if line is not None:
            has_rate_phrase = f"on {sig['recorded_firings']} of the {sig['sweeps_evaluable']}" in line
            assert has_rate_phrase is (recomputed is None)


# ── (7) the two properties that must hold on EVERY branch, new ones included ───────────────────────
def test_register_stays_clean_on_the_new_branches():
    for slug, line in _one_of_each().items():
        assert pr.pr_register_leaks(line) == [], f"{slug}: OBSERVATION register leaked -> {line!r}"


def test_verifier_grounds_every_figure_the_new_branches_state():
    """The D1/D1b property: the engine's OWN deterministic sentence must never wear the caution banner.
    The new branches state only recorded_firings / sweeps_evaluable / sweeps_total (all leg row values)
    and ISO dates (scrubbed) -- the vintage estimate is deliberately not among them."""
    g20, g40 = _weekly(ASOF, 20), _weekly(ASOF, 40)
    cases = {
        "no_variance_full": (_all_fired(), None),
        "no_variance_partial": ([(d, "declined", "fetch_error") for d in G158[:100]]
                                + [(d, "fired", None) for d in G158[100:]], None),
        "vintage_full_coverage": ([(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None)
                                   for i, d in enumerate(g20)], 2),
        "vintage_partial": ([(d, "declined", "fetch_error") for d in g40[:20]]
                            + [(d, "declined", "thin_history") if i % 5 == 0 else (d, "fired", None)
                               for i, d in enumerate(g40[20:])], 2),
    }
    for name, (rows, states) in cases.items():
        legs, _sig, line = _answer(rows, states=states)
        v = orc._verify_numbers_answer(line, legs)
        assert v["mismatched"] == 0, f"{name}: ungrounded figure(s) {v['mismatch_values']} in {line!r}"


def test_the_verifier_check_above_is_not_vacuous():
    legs, _sig, line = _answer(_all_fired())
    assert orc._verify_numbers_answer(line + " The run length was 37.", legs)["mismatched"] == 1


# ── (8) the constants themselves ───────────────────────────────────────────────────────────────────
def test_the_vintage_floor_is_named_and_tied_to_the_independent_observation_argument():
    assert isinstance(pr.PR_MIN_DISTINCT_VINTAGES, int)
    # equal BY DESIGN: the coverage floor's justification is an argument about independent observations,
    # and sweeps were only ever a proxy for those. Separate constants so they can be tuned apart.
    assert pr.PR_MIN_DISTINCT_VINTAGES == pr.PR_MIN_EVALUABLE_SWEEPS
    # the live pace lane's TRUE vintage depth is 3 (11 evaluable asofs, ESR snapshots 2026-05-24 x7 /
    # 07-17 / 07-24). It must not clear the floor.
    assert pr.PR_MIN_DISTINCT_VINTAGES > 3
