"""THE PACE LEG'S OWN INPUT RIDES THE READ -- cascade.fetch_window x query.roll_inputs (2026-09-10).

THE DEFECT, IN ONE SENTENCE. ``_pace_front_expiry`` runs the named, versioned front-month rule
(``futures_roll.front_month``, ROLL_RULE_VERSION front_month_v2) and asks its precondition
``front_month_inputs_present`` FIRST -- and that precondition reads ``open_interest`` / ``volume`` OFF
THE ROWS. Neither is a served metric on the settle-only card, so ``query._extras`` never surfaced them,
``cascade.fetch_window`` never asked for them, and the frame handed to the rule carried NO activity
metric at all. Every front-by-open-interest and every front-by-volume board therefore declined the pace
leg WHOLE -- silently, and by a route that looks exactly like an honest absence. ``_pace_front_expiry``'s
own docstring recorded it as the live state ("the all-missing case is the live state today for every
GLBX / CZCE / JSE / ICE slug ... the delivery-cycle slugs ... select honestly now"). The RULE was never
broken; the READ never projected what the rule reads.

THE POPULATION, MEASURED (S4 board census 2026-09-07, its ``tape`` probe -- whose own read already
carries this projection, so it reads as an EXPOSURE and never as a pace-leg decline rate): 20 of the 26
tape boards run a rule that reads an activity column, 12 front-by-open-interest and 8 front-by-volume.
The other six cannot be refused for want of it -- four delivery-cycle boards, whose rule reads no
metric, and two cash references, which have no delivery-month axis at all.

AND WHAT THE FIX MOVES TODAY: nothing that renders. The pace leg cannot reach this card on the served
path yet (item 16), which was measured over the 12 banked turns rather than assumed and is pinned as a
tripwire in tests/unit/test_cascade_walk.py. What this deck proves is the seam itself: the frame the
rule is handed, the SQL every other card still compiles, and the four roll-method classes landing where
the rule puts them.

THE FIX IS ONE SEAM: ``fetch_window`` passes ``Q.run(roll_inputs=True)`` exactly when the table is a
per-delivery-month price card (``_PACE_EXPIRY_COL``) AND the spec compiles the SERIES arm -- the one
branch the projection can ride. Everything else takes the omit-when-off branch, which is what
``test_every_other_registry_card_compiles_the_SAME_SQL`` pins over the whole registry.

THE FIXTURE IS IMPORTED, NEVER COPIED (``state.__main__.tape_fixture_rows`` + ``mirror_query_fn``): the
physical rows a mirror would hold, behind an executor that OBEYS the compiled SQL's projection, WHERE,
ORDER BY and LIMIT. A fixture that handed back aliases the read never projected would prove the wrong
thing -- and the projection is the entire subject of this deck.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import load_registry
from leviathan.graphrag.state.__main__ import mirror_query_fn, tape_fixture_rows
from leviathan.silver import futures_roll as FR

TABLE = "silver_futures_eod"
ASOF = "2026-09-04"
#: The fixture's listed delivery cycle (the MATIF slugs' own, four months a year). It is what makes a
#: SAME-CONTRACT window possible at all: on a monthly listing the nearest expiry rolls inside any
#: 21-session window and ``_pace_front_expiry`` declines the splice -- correctly, and for a different
#: reason than the one this deck measures.
CYCLE: tuple = (3, 5, 9, 12)
#: The rule reads OPEN INTEREST here, VOLUME here, NO metric here, and has no delivery-month axis at all
#: on the cash reference -- the four classes, one per branch of the precondition.
OI_SLUG = "corn_cbot"
VOL_SLUG = "cocoa"
CYCLE_SLUG = "french_wheat_matif"
CASH_SLUG = "brazilian_arabica_coffee"


def _read(slug: str, *, blank: bool = False, cycle: tuple = CYCLE, sessions: int = 40):
    """ONE pace-shaped read through the shipped seam -> (call-record, the SQL it compiled)."""
    rows = tape_fixture_rows(slug, sessions=sessions, expiries=8, last=ASOF, cycle=cycle,
                             blank_roll_inputs=blank)
    qfn = mirror_query_fn({TABLE: rows})
    t1 = cq._plus_days(ASOF, -cq._PACE_WINDOW_DAYS["day"])
    rec = cq.fetch_window(qfn, table=TABLE, metric="settle", commodity=slug, country=None,
                          t1=t1, t2=ASOF, asof=ASOF, agg="series", period=None, period_type="date")
    return rec, qfn.calls[-1]


def _projection(sql: str) -> str:
    return sql.split(" FROM ")[0].replace("SELECT ", "")


# ── THE REPRODUCTION: the frame the rule used to be handed, and the one it is handed now ────────────
def test_REPRO_the_settle_only_frame_declines_the_named_rule_on_a_front_by_metric_board():
    """THE DEFECT ITSELF, reproduced from the SQL rather than asserted: compile the read WITHOUT the
    projection (which is byte-identically what this seam compiled before the fix -- pinned below), serve
    it, and watch the pace leg decline WHOLE on a board whose rule reads open interest."""
    rows = tape_fixture_rows(OI_SLUG, sessions=40, expiries=8, last=ASOF, cycle=CYCLE)
    qfn = mirror_query_fn({TABLE: rows})
    ts = load_registry().get(TABLE)
    spec = Q.NumberQuery(table=TABLE, metric="settle", asof=ASOF, commodity=OI_SLUG,
                         agg="series", period_start=cq._plus_days(ASOF, -21), period_end=ASOF)
    pre = {"query": {"commodity": OI_SLUG}, "rows": Q.run(spec, query_fn=qfn), "status": "ok"}
    assert pre["rows"], "the pre-fix read served rows -- the decline was never an empty read"
    assert not any("open_interest" in r or "volume" in r for r in pre["rows"]), \
        "the settle-only projection carries NO activity metric: that is the whole defect"
    assert cq._pace_series(pre, TABLE, commodity=OI_SLUG) == ([], None), \
        "front_month_inputs_present refuses the frame -> the pace leg declines whole (front_decline)"


@pytest.mark.parametrize("slug", [OI_SLUG, VOL_SLUG])
def test_THE_FIX_the_front_by_metric_board_names_its_front_month_after_the_projection_lands(slug):
    """The SAME board, the SAME fixture, through the shipped ``fetch_window``: the rule's own input rides
    the SERIES projection, the precondition is satisfied, and the leg fires on ONE delivery month."""
    rec, sql = _read(slug)
    assert rec["status"] == "ok" and rec["rows"]
    assert _projection(sql).endswith(", open_interest, volume"), \
        "the delta is a PROJECTION TAIL and nothing else"
    assert all(r.get("open_interest") not in (None, "") for r in rec["rows"])
    vals, collapse = cq._pace_series(rec, TABLE, commodity=slug)
    assert collapse == "front_expiry" and len(vals) >= 2
    # ONE contract across the window (never a splice) and the fixture's own front-month settles: the
    # nearest listed month carries the highest activity metric, so its settle is the j=0 ramp.
    assert vals == sorted(vals) and vals[-1] - vals[0] == pytest.approx(0.5 * (len(vals) - 1))


@pytest.mark.parametrize("newest_first", [False, True])
def test_the_projection_and_the_NEWEST_FIRST_canary_ride_the_same_read_without_touching_each_other(
        newest_first):
    """TWO THREADED SLOTS ON ONE READ, pinned together because that is where they can only be measured.

    ``futures_newest_first`` (the D-FR-10 / S1 canary) INVERTS this card's series ORDER BY and ``Q.run``
    re-sorts the rows back to ascending before the caller sees them; ``roll_inputs`` appends to the
    SELECT. They are computed from disjoint parts of the spec, so they must compose -- but "must" is the
    word that precedes every silent interaction, and the front-month rule is exactly the consumer that
    would be broken by a reversed frame (it sorts (slug, trade_date) ASC itself and this leg deltas
    across dates). So: the tail rides BOTH arms, the ORDER BY inverts on one, and the selection returns
    the SAME contract and the SAME values either way."""
    rec, sql = _read(OI_SLUG)                                     # the canary off, for the comparison
    base = cq._pace_series(rec, TABLE, commodity=OI_SLUG)
    rows = tape_fixture_rows(OI_SLUG, sessions=40, expiries=8, last=ASOF, cycle=CYCLE)
    qfn = mirror_query_fn({TABLE: rows})
    rec2 = cq.fetch_window(qfn, table=TABLE, metric="settle", commodity=OI_SLUG, country=None,
                           t1=cq._plus_days(ASOF, -cq._PACE_WINDOW_DAYS["day"]), t2=ASOF, asof=ASOF,
                           agg="series", period=None, period_type="date",
                           futures_newest_first=newest_first)
    sql2 = qfn.calls[-1]
    assert _projection(sql2).endswith(", open_interest, volume")   # the tail is canary-agnostic
    assert ("DESC" in sql2.split(" ORDER BY ")[1]) is newest_first  # ...and the order is not
    assert cq._pace_series(rec2, TABLE, commodity=OI_SLUG) == base
    assert base[1] == "front_expiry" and len(base[0]) >= 2


def test_the_two_metric_methods_and_the_two_metric_less_ones_land_where_the_rule_puts_them():
    """The census this fix is measured by, one line per class -- and the two that must NOT move."""
    got = {}
    for slug in (OI_SLUG, VOL_SLUG, CYCLE_SLUG, CASH_SLUG):
        rec, _sql = _read(slug)
        vals, _c = cq._pace_series(rec, TABLE, commodity=slug)
        got[FR.roll_method_for(slug)] = bool(vals)
    assert got == {FR.METHOD_OPEN_INTEREST: True, FR.METHOD_VOLUME: True,
                   FR.METHOD_DELIVERY_CYCLE: True, FR.METHOD_NONE: False}


def test_the_delivery_cycle_board_selects_the_SAME_series_it_selected_before():
    """The metric-LESS rule reads no activity column, so the projection must change its answer by
    nothing at all: same front month, same values. (It is the class that "selects honestly now" -- the
    only one that ever served -- so a moved value here would be the fix breaking what worked.)"""
    rec, _sql = _read(CYCLE_SLUG)
    served = cq._pace_series(rec, TABLE, commodity=CYCLE_SLUG)
    bare = [{k: v for k, v in r.items() if k not in ("open_interest", "volume")} for r in rec["rows"]]
    assert cq._pace_series({**rec, "rows": bare}, TABLE, commodity=CYCLE_SLUG) == served
    assert served[1] == "front_expiry" and len(served[0]) >= 2


def test_a_column_served_EMPTY_still_declines_the_leg_whole():
    """FAIL-CLOSED IS PRESERVED, which is the half a projection fix could quietly undo. The mirror's NULL
    shape is ``""`` (``pgnumbers._stringify``); a column that is projected but served blank is not an
    input the rule can read, and ``front_month`` would fill it with -1 and fall through to a DIFFERENT,
    unnamed rule wearing front_month_v2's name."""
    rec, sql = _read(OI_SLUG, blank=True)
    assert _projection(sql).endswith(", open_interest, volume")     # asked for
    assert all(r.get("open_interest") == "" for r in rec["rows"])    # and served empty
    assert cq._pace_series(rec, TABLE, commodity=OI_SLUG) == ([], None)


def test_a_roll_INSIDE_the_window_is_still_a_splice_and_still_declines():
    """The other decline this deck must not have widened: on a MONTHLY listing the front month rolls
    inside the 21-session window, and "front expiry first, then delta across dates" is only PIT-safe
    while both endpoints are the same contract."""
    rec, _sql = _read(OI_SLUG, cycle=())
    assert rec["status"] == "ok" and rec["rows"]
    assert cq._pace_series(rec, TABLE, commodity=OI_SLUG) == ([], None)


# ── THE SEAM PREDICATE: which reads arm the projection, and which may never ─────────────────────────
def _spec(agg="series", table=TABLE, **kw):
    return Q.NumberQuery(table=table, metric="settle", asof=ASOF, commodity=OI_SLUG, agg=agg, **kw)


def test_the_seam_arms_on_the_series_branch_of_a_per_expiry_price_card_and_nowhere_else():
    assert cq._roll_inputs_apply(TABLE, _spec("series"), vintage=False) is True
    # every branch `_roll_input_projection` would RAISE on -- and a raise here would be swallowed by
    # fetch_window's R6 degrade path and become status='error' on a leg that serves today.
    for agg in ("front_expiry", "latest", "sum", "mean", "max", "min"):
        assert cq._roll_inputs_apply(TABLE, _spec(agg), vintage=False) is False, agg
    # a vintage card's series arm projects the dedup subquery's aliases and would drop the columns
    assert cq._roll_inputs_apply(TABLE, _spec("series"), vintage=True) is False
    # not a per-delivery-month price table -> not this seam's business
    assert cq._roll_inputs_apply("silver_psd", _spec("series", table="silver_psd"), vintage=False) is False
    # and an unregistered / whitelist-absent card fails CLOSED rather than raising
    assert cq._roll_inputs_apply("no_such_table", _spec("series", table="no_such_table"),
                                 vintage=False) is False


def test_the_seam_membership_is_the_pace_expiry_declaration_itself():
    """No second list: the arming set IS ``_PACE_EXPIRY_COL``, the same membership ``lint_pace_collapse``
    binds both ways to the front_expiry collapse. A per-expiry card added there arms with it."""
    for table in cq._PACE_EXPIRY_COL:
        assert cq._PACE_COLLAPSE.get(table) == "front_expiry"
        assert cq._roll_inputs_apply(table, _spec("series", table=table), vintage=False) is True


def test_a_per_expiry_card_WITHOUT_roll_inputs_on_its_card_neither_arms_NOR_errors(monkeypatch):
    """THE CLAUSE-(1)-ALONE TRAP, closed by asking the compiler rather than restating it.

    ``_PACE_EXPIRY_COL`` is a HAND-KEPT set; ``roll_input_cols`` is a REGISTRY declaration, and
    ``lint_pace_collapse`` binds the first to the front_expiry collapse but says nothing about the
    second. So a per-expiry card can be added to the set whose card declares no roll inputs -- and a
    seam that tested only "is this the series branch" would arm it, ``_roll_input_projection`` would
    RAISE inside ``Q.run``, and ``fetch_window``'s R6 degrade path would turn a leg that serves today
    into ``status='error'``: the exact failure the seam exists to avoid, arriving through the seam.
    Asking ``_roll_input_projection`` itself makes the predicate agree with the compiler by
    construction -- it declines the projection, and the read serves."""
    monkeypatch.setitem(cq._PACE_EXPIRY_COL, "silver_psd", "contract_month")
    assert cq._roll_inputs_apply("silver_psd", _spec("series", table="silver_psd"),
                                 vintage=False) is False
    rec = cq.fetch_window(lambda sql: [], table="silver_psd", metric="exports_mt", commodity="wheat",
                          country="Russia", t1=None, t2=None, asof=ASOF, agg="series", period=None,
                          period_type="marketing_year")
    assert rec["status"] != "error"


def test_the_front_expiry_SELECTION_is_untouched_and_projects_its_own_inputs_ONCE():
    """The roster's board rows read ``agg='front_expiry'``, whose OWN branch already projects the roll
    inputs (inside the DENSE_RANK subquery) and strips them off the one row it returns. The seam must
    not double-arm it -- that branch is not a series read, and ``_roll_input_projection`` would raise on
    it, which fetch_window's R6 path would turn into ``status='error'`` on a leg that serves today.

    ASSERTED ON THE COMPILED SQL, not on served rows: the fixture executor obeys a flat
    SELECT/WHERE/ORDER BY/LIMIT and cannot evaluate this branch's window function, so a row assertion
    here would be grading the fixture rather than the compiler."""
    seen: list = []
    rec = cq.fetch_window(seen.append, table=TABLE, metric="settle", commodity=CYCLE_SLUG, country=None,
                          t1=None, t2=None, asof=ASOF, agg="front_expiry", period=None,
                          period_type="date")
    assert rec["status"] != "error" and seen
    sql = seen[0]
    assert cq._roll_inputs_apply(TABLE, _spec("front_expiry"), vintage=False) is False
    # the branch projects the columns itself (twice: the inner rank subquery and the outer alias list),
    # and the seam adds NOTHING -- the string is the omit-when-off compile, byte for byte.
    assert "DENSE_RANK" in sql and "open_interest, volume" in sql
    assert sql == Q.build_sql(
        Q.NumberQuery(table=TABLE, metric="settle", asof=ASOF, commodity=CYCLE_SLUG,
                      agg="front_expiry"), load_registry().get(TABLE))


# ── THE BYTE-IDENTITY PIN: every other card compiles what it compiled yesterday ─────────────────────
_AGGS = ("series", "latest", "sum", "mean", "max", "min", "front_expiry")
_SHAPES = (("date", {"t1": "2026-08-14", "t2": ASOF, "period": None}),
           ("date", {"t1": None, "t2": None, "period": None}),
           ("year_month", {"t1": "2025-01", "t2": "2026-09", "period": None}),
           ("marketing_year", {"t1": None, "t2": None, "period": "2025/2026"}))


def test_every_other_registry_card_compiles_the_SAME_SQL():
    """THE ROLLBACK, FROM THE IDIOM RATHER THAN FROM A PROMISE. Compile every card in the registry at
    every agg this seam can issue and every window shape, and assert that the ONLY string that differs
    from the settle-only form is the per-expiry price card's SERIES arm, whose delta is EXACTLY the two
    columns the rule reads. Nothing else on the estate can move: the kwarg is omitted at the call site
    for every other read, so the compiler sees the call it saw before this change."""
    reg = load_registry()
    moved, checked = {}, 0
    for tid, ts in sorted(reg.tables.items()):
        for metric in (sorted(ts.metrics)[:2] or [None]):
            for agg in _AGGS:
                for pt, kw in _SHAPES:
                    seen: list = []
                    cq.fetch_window(seen.append, table=tid, metric=metric,
                                    commodity=("corn_cbot" if ts.commodity_col else None),
                                    country=None, asof=ASOF, agg=agg, period_type=pt,
                                    t1=kw["t1"], t2=kw["t2"], period=kw["period"])
                    if not seen:
                        continue                       # a shape this card refuses (declines, no SQL)
                    checked += 1
                    spec = Q.NumberQuery(table=tid, metric=metric, asof=ASOF, agg=agg,
                                         commodity=("corn_cbot" if ts.commodity_col else None),
                                         **cq._window_kwargs(pt, kw["t1"], kw["t2"], kw["period"]))
                    bare = Q.build_sql(spec, ts)       # the omit-when-off form, byte for byte
                    if seen[0] != bare:
                        moved.setdefault((tid, agg), set()).add(seen[0][len(bare):]
                                                                if seen[0].startswith(bare[:40]) else "?")
    assert checked > 1000, f"the pin must actually sweep the registry (compiled {checked})"
    assert set(moved) == {(TABLE, "series")}, f"tables/aggs that moved: {sorted(moved)}"
    # and the move is a PROJECTION TAIL: same SQL with ', open_interest, volume' inside the SELECT
    for (tid, agg) in moved:
        seen = []
        cq.fetch_window(seen.append, table=tid, metric="settle", commodity=OI_SLUG, country=None,
                        asof=ASOF, agg=agg, period_type="date", t1="2026-08-14", t2=ASOF, period=None)
        spec = Q.NumberQuery(table=tid, metric="settle", asof=ASOF, commodity=OI_SLUG, agg=agg,
                             period_start="2026-08-14", period_end=ASOF)
        bare = Q.build_sql(spec, load_registry().get(tid))
        assert seen[0] == bare.replace(" FROM ", ", open_interest, volume FROM ", 1)


def test_the_read_never_raises_on_a_card_that_cannot_serve_the_projection():
    """R6 is unchanged: the seam decides BEFORE the compiler, so no read acquires a new error path. A
    card outside the per-expiry set, and the per-expiry card at an agg the projection cannot ride, both
    return their ordinary record."""
    rec = cq.fetch_window(lambda sql: [], table="silver_psd", metric="exports_mt", commodity="wheat",
                          country="Russia", t1=None, t2=None, asof="2011-02-01", agg="series",
                          period=2010, period_type="marketing_year")
    assert rec["status"] != "error"
    rows = tape_fixture_rows(OI_SLUG, sessions=4, expiries=4, last=ASOF, cycle=CYCLE)
    for agg in ("latest", "front_expiry"):
        qfn = mirror_query_fn({TABLE: rows})
        rec = cq.fetch_window(qfn, table=TABLE, metric="settle", commodity=OI_SLUG, country=None,
                              t1=None, t2=None, asof=ASOF, agg=agg, period=None, period_type="date")
        assert rec["status"] != "error", agg
