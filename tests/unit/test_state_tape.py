"""THE ANCHOR'S SB-T TAPE ROW -- STATE ENGINE DESIGN sec 6.2 / D19 / bar B19, sitting S1.

ONE read per anchor board: the dated front settle named by the SHIPPED roll rule, the four SAME-CONTRACT
session changes (1 / 5 / 21 / 63) and the level's percentile over the window that read fetched. Every
test here runs OFFLINE -- ``fixture_query_fn`` compiles the real SQL against canned rows -- because a bar
that can only be measured in-VPC is a bar nobody runs.

WHY THIS DECK EXISTS AT ALL: sec 11's S1 row lists "the SB-T read" and the first S1 cut shipped neither
the read nor a not-done line for it. ``feeders.board_map()`` carries no ``silver_futures_eod`` ref and
``series_state`` can only produce a row for a map ref, so there was no path to an anchor tape row.
"""
import datetime as _dt

import pytest
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state.rows import TAPE_STATUS_WITH_DETAIL, TAPE_STATUS_WORDS, status_word

#: A slug whose roll method is ``delivery_cycle`` -- the rule needs NO activity metric, so it selects
#: honestly on the settle-only card the store serves today (``futures_roll.roll_method_for``, measured:
#: the MATIF and MGEX slugs; every GLBX / ICE / DCE slug is front-by-open-interest or front-by-volume).
CYCLE_SLUG = "french_wheat_matif"
#: A slug whose rule reads OPEN INTEREST, which the served card does not carry -- the measured
#: ``front_decline`` of today's estate, and the reason that word is in the closed set.
OI_SLUG = "corn_cbot"


def _sessions(n, last="2026-09-04"):
    end = _dt.date.fromisoformat(last)
    return [(end - _dt.timedelta(days=k)).isoformat() for k in range(n)][::-1]


def _curve(sessions, expiries, base=250.0):
    """A silver_futures_eod SERIES read's shape: one row per (session, expiry), self-identifying.
    ``knowledge_date`` is the alias ``_extras`` emits for this card -- it serves ``trade_date`` as BOTH
    its date and its knowledge column, so there is no ``data_date`` alias on any row of it."""
    return [{"value": str(round(base + i * 0.5 + j * 2.0, 2)), "knowledge_date": d,
             "contract_month": cm, "settle_kind": "official", "currency": "EUR", "unit": "EUR/t"}
            for i, d in enumerate(sessions) for j, cm in enumerate(expiries)]


def test_the_tape_row_is_ONE_read_with_the_front_named_by_the_SHIPPED_rule():
    rows = _curve(_sessions(120), ["2026-12", "2027-03", "2027-05"])
    qfn = F.fixture_query_fn({"silver_futures_eod": rows})
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=qfn)
    assert t.status == "ok" and t.reads == 1
    assert len(qfn.calls) == 1, "D19: one mirror read per anchor board"
    assert t.roll_rule_version == "front_month_v2" and t.roll_method == "delivery_cycle"
    assert t.contract_month == "2026-12" and t.level_date == "2026-09-04"
    assert t.unit == "EUR/t" and t.currency == "EUR" and t.settle_kind == "official"


def test_the_four_changes_are_SAME_CONTRACT_and_name_their_windows_in_SESSIONS():
    """Same-contract is the whole point: a delta spanning a roll is a SPLICE, which is exactly the
    contamination ``levels_only`` fences on the continuous sibling card. The fixture ramps 0.5 per
    session on every expiry and 2.0 per expiry, so a change that had wandered onto a neighbouring
    delivery month could not produce these numbers."""
    rows = _curve(_sessions(120), ["2026-12", "2027-03", "2027-05"])
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert [c["window"] for c in t.changes] == ["1 session", "5 sessions", "21 sessions", "63 sessions"]
    assert [c["delta"] for c in t.changes] == [0.5, 2.5, 10.5, 31.5]
    assert all(c["declined"] is False for c in t.changes)
    assert all(c["to_date"] == "2026-09-04" for c in t.changes)
    assert F.TR.re_execute_all(t.derivation, t.inputs) == [], "every SB-T figure reproduces from its rows"


def test_the_percentile_ranks_the_level_INSIDE_THE_FETCHED_WINDOW_and_prints_that_window():
    """"the level at the {pct}th percentile of its fetched five-year window" (sec 6.2). The window is
    what the read FETCHED, never "full history" and never the contract's whole quoted life, and the row
    says so in sessions and dates so the rank can never claim a span it did not measure."""
    rows = _curve(_sessions(120), ["2026-12", "2027-03"])
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert t.percentile and t.percentile["declined"] is False and t.percentile["n"] == 120
    assert t.percentile["value"] > 99.0, "a monotone ramp puts the newest settle at the top of its window"
    assert t.window_note == "120 sessions on 2026-12, 2026-05-08 to 2026-09-04"
    assert t.coverage["n_obs"] == 120 and t.coverage["truncated"] is False


def test_a_thin_contract_declines_percentile_thin_and_changes_thin_BY_NAME():
    rows = _curve(_sessions(3), ["2026-12"])
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert t.percentile["declined"] is True
    assert status_word(t.status) in ("percentile_thin", "changes_thin")
    assert t.status.split(":", 1)[1] == "3"
    assert [c["declined"] for c in t.changes] == [False, True, True, True]


def test_the_tapeless_boards_decline_no_tape_slug_at_ZERO_reads():
    """Bar B19: the ten boards absent from ``PRICE_COVERAGE_START`` have no SB-T row and say so. A board
    with no per-contract tape never borrows a neighbour's and never falls back to the continuous card."""
    def _never(sql):
        raise AssertionError("a tape-less board must not spend a read")
    for slug in ("soybeans", "corn", "palm_olein_dce", "barley", "sorghum"):
        t = F.tape_state(slug, "2026-09-08", qfn=_never)
        assert t.status == "no_tape_slug" and t.reads == 0 and t.level is None


def test_an_asof_before_the_slugs_own_coverage_floor_declines_pre_coverage_at_ZERO_reads():
    def _never(sql):
        raise AssertionError("a pre-coverage as-of must not spend a read")
    t = F.tape_state(OI_SLUG, "2005-01-01", qfn=_never)
    assert t.status == "pre_coverage" and t.reads == 0
    assert t.coverage_start == "2010-06-06", "the floor is PRICE_COVERAGE_START's own, printed on the row"


def test_a_slug_whose_ROLL_INPUT_the_card_does_not_serve_declines_front_decline():
    """MEASURED, and it is today's live state for every GLBX / ICE / CZCE / JSE slug: the served card is
    settle-ONLY, so ``front_month_inputs_present`` refuses and ``select_front_expiry`` returns its own
    reasoned ``[]``. The board declines by name rather than falling through to the nearest listed expiry
    -- which would be a DIFFERENT, unnamed rule wearing ``front_month_v2``'s name."""
    rows = _curve(_sessions(90), ["2026-12", "2027-03"])
    t = F.tape_state(OI_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert t.status == "front_decline" and t.reads == 1 and t.level is None
    assert t.coverage["n_obs"] == 180, "the read is still counted: the ledger sees what it spent"


def test_the_tape_read_is_windowed_capped_and_newest_first_like_every_other_board_read():
    spec = F.board_spec(F.TAPE_TABLE, F.TAPE_METRIC, CYCLE_SLUG, None, "2026-09-08", "daily")
    assert spec.agg == "series" and spec.limit == F.READ_LIMIT
    assert spec.period_start == "2021-09-08", "five years, never a whole-history read"
    rows = _curve(_sessions(40), ["2026-12"])
    qfn = F.fixture_query_fn({"silver_futures_eod": rows})
    F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=qfn)
    sql = qfn.calls[0]
    assert "settle AS value" in sql and "LIMIT 5000" in sql
    # the ORDER BY reads the ALIASES `_extras` minted, and this card's session axis is `knowledge_date`
    # (it serves `trade_date` as both its date and its knowledge column, so there is no `data_date`)
    assert "knowledge_date DESC" in sql, "a cap that bites must keep the NEWEST sessions (NEWEST_FIRST_ALL)"


def test_a_truncated_tape_read_says_so_on_the_row():
    rows = _curve(_sessions(30), ["2026-12", "2027-03"])
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=F.fixture_query_fn({"silver_futures_eod": rows}),
                     limit=60)
    assert t.coverage["truncated"] is True and "row cap" in t.window_note


def test_the_tape_handler_NEVER_RAISES_and_names_its_own_resource_declines():
    def _explode(sql):
        raise RuntimeError("the mirror is on fire")

    def _pool(sql):
        raise F.BoardReadDecline("pool_exhausted", "no connection freed in 5s")
    assert F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=_explode).status == "read_error"
    assert F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=_explode).reads == 1
    t = F.tape_state(CYCLE_SLUG, "2026-09-08", qfn=_pool)
    assert t.status == "pool_exhausted" and t.reads == 1


def test_the_tape_never_reads_the_ANCHOR_as_a_DRIVER_ref():
    """``cascade_map.yaml``'s self-reference refusal binds DRIVER refs; SB-T is the anchor's OWN tape.
    The board's map accessor carries no ``silver_futures_eod`` row, so the only path to this table is
    :func:`tape_state` -- which is the design's separation, in code."""
    assert not [r for r, row in F.board_map().items() if (row or {}).get("table") == F.TAPE_TABLE]


def test_every_word_the_tape_row_can_carry_is_in_ITS_OWN_closed_set():
    words = {"ok", "no_tape_slug", "pre_coverage", "front_decline", "changes_thin:3",
             "percentile_thin:3", "pool_exhausted", "pg_timeout", "read_error"}
    for w in words:
        head = status_word(w)
        assert head in TAPE_STATUS_WORDS
        if w != head:
            assert head in TAPE_STATUS_WITH_DETAIL
    assert "read_empty" not in TAPE_STATUS_WORDS, (
        "an empty tape fetch is select_front_expiry's own front_decline, not a second word for it")


@pytest.mark.parametrize("asof", ["2026-09-08", "2024-03-15", "2020-06-30"])
def test_PIT_the_tape_row_never_reads_a_session_after_the_asof(asof):
    """The guard is in the SQL and AGAIN in the selector (``select_front_expiry`` recomputes the cutoff
    from ``spec.asof`` and the card's ``publication_lag_days`` and drops every later session before it
    walks). The fixture hands back rows the real WHERE clause would never have returned, so this pins
    the SECOND belt: a caller that supplies post-cutoff rows cannot make the walk reach one."""
    rows = _curve(_sessions(200, last="2026-09-04"), ["2026-12", "2027-03"])
    t = F.tape_state(CYCLE_SLUG, asof, qfn=F.fixture_query_fn({"silver_futures_eod": rows}))
    assert t.status in ("ok", "front_decline", "pre_coverage") or status_word(t.status) in (
        "changes_thin", "percentile_thin")
    if t.level_date:
        assert t.level_date < asof, "a session at or after the as-of cutoff reached the row"
    for d in (c["from_date"] for c in t.changes):
        if d:
            assert d < asof
