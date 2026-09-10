"""THE NUMERIC AND TEXT FEEDERS -- STATE ENGINE DESIGN sec 2.1 / 2.2, and the row schema of 1.2 / 1.3 /
1.4. Sitting S1.

Every test here runs OFFLINE: no pg mirror, no Athena, no network, no clock beyond the as-of it is
handed. That is a property of the design, not of the tests -- the deterministic bars of sec 10.2 run on
the offline harness, and a bar that can only be measured in-VPC is a bar nobody runs.
"""
import pytest
from leviathan.graphrag.numbers.registry import load_registry
from leviathan.graphrag.state import feeders as F
from leviathan.graphrag.state.rows import COVERAGE_TIERS, STATUS_WORDS, SeriesKey, coverage_tier


class _Node:
    """The census's ``_LegNode`` stand-in: exactly what the replayed cascade helpers read."""
    __slots__ = ("contract", "id", "prior", "evidence")

    def __init__(self, contract, driver_id, ref, region=None, evidence=None):
        self.contract, self.id = contract, driver_id
        self.prior = {"silver_ref": ref, "region": region}
        self.evidence = evidence if evidence is not None else []


def _oni_rows(n=140, start=(2015, 1)):
    """A monthly ONI-shaped fixture: (year, month, value), oldest first, one row per month."""
    out, y, m = [], *start
    for i in range(n):
        out.append({"year": y, "month": m, "value": str(round(1.4 * ((i % 23) - 11) / 11.0, 3))})
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _pit_qfn(rows, asof, table="silver_noaa_oni", metric="oni_anom", cadence="monthly",
             commodity="soybeans_cbot", country=None, ym_lag=True):
    """The fixture executor with the SQL's own oracle wired in, so the offline board is filtered by the
    same point-in-time rule the mirror applies. ``ym_lag`` must match what the producer is handed, or
    the fixture would be filtering under one rule while the producer compiled another."""
    ts = load_registry().get(table)
    spec = F.board_spec(table, metric, commodity, country, asof, cadence)
    return F.fixture_query_fn({table: rows}, pit={table: (spec, ts)}, ym_lag=ym_lag)


# ── the pinned cascade surface (sec 2.1, critic G21) ─────────────────────────────────────────────────
def test_every_name_this_package_reads_out_of_cascade_still_resolves():
    """A K9 rename must red at IMPORT, never at serve. The list is frozen in ``feeders.CASCADE_IMPORTS``
    and this is the assertion that gives that freezing teeth."""
    assert F.check_cascade_imports() == []
    assert "map_row" in F.CASCADE_IMPORTS and "_scope_ex" in F.CASCADE_IMPORTS


def test_the_board_reads_the_deferred_board_read_rows_and_the_cascade_still_cannot_see_them():
    """D23's whole mechanism, in one test: ``deferred: true`` keeps the row inert to ``load_map`` (so the
    serving cascade's ``map_row`` returns None and the hop stays qualitative) while ``board_read: true``
    is a key only the board's own accessor honours."""
    from leviathan.graphrag.numbers import cascade as casc
    dark = F.board_read_refs()
    assert dark, "phase 1a landed at least one board-only row"
    for ref in dark:
        assert casc.map_row(ref) is None, f"{ref} is visible to the SERVING cascade -- it must not be"
        assert F.board_map_row(ref) is not None
    assert set(casc.load_map()) <= set(F.board_map())


def test_an_unknown_ref_is_a_ROW_at_zero_reads_and_its_tier_comes_from_the_DAGs_own_word():
    n = _Node("soybeans_cbot", "mississippi_level", "mississippi_stage_z")
    for status, tier in (("planned", "planned_text_only"), ("none", "none_text_only"),
                         ("available", "declared_available_unserved")):
        r = F.series_state("mississippi_stage_z", n, "2026-09-08", qfn=lambda sql: [],
                           silver_status=status)
        assert r.status == "unmapped_ref" and r.reads == 0
        assert r.coverage_tier == tier


def test_the_live_predicate_is_NOT_the_tier():
    """``graph.silver_status()['live']`` is True for the 125 available-but-UNMAPPED instances (it reads
    features.yaml FAMILIES + node_silver_map + live map refs), so reading a tier off it would put
    "measured" on rows nothing measures. The tier comes from the map row plus the read's outcome."""
    assert coverage_tier(map_row=None, silver_status="available", status="ok") == \
        "declared_available_unserved"
    assert coverage_tier(map_row={"table": "t"}, silver_status="available", status="ok", n_obs=40) == \
        "series"
    assert coverage_tier(map_row={"table": "t"}, silver_status="available", status="ok", n_obs=3) == \
        "series_thin"
    assert set(COVERAGE_TIERS) == {
        "series", "series_thin", "declared_available_unserved", "planned_text_only", "none_text_only"}


def _assigned_statuses():
    """Every string the producer can put on a row's ``status``, grouped by the function it is written
    in. GROUPED, because the producer writes TWO closed vocabularies -- the series words and SB-T's own
    -- and a flat set would grade each against the other's enum and pass on the union, which is exactly
    the widening the enums exist to prevent.

    TWO WRITE FORMS, and the second was added at S2 when the zero-read prologue was lifted into
    ``series_key_for``: a status can be ASSIGNED (``out.status = 'read_empty'``) or PASSED as the
    ``status=`` keyword of a constructed record (``KeyPlan(key=None, status='unmapped_ref')``). The
    lift moved four words -- ``unmapped_ref``, ``scope_unresolved:``, ``unmapped_ref:no_registry_card``
    and ``outlook_lane`` -- from the first form to the second, and a scanner that only knew the first
    would have gone quietly blind on them (MEASURED: this file's own
    ``..._the_two_words_the_first_S1_cut_invented_are_gone...`` pin failed on exactly that hole, which
    is the whole reason the fence is written against the AST rather than against a habit)."""
    import ast
    import inspect

    def _words(v):
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            return [v.value]
        if isinstance(v, ast.JoinedStr) and v.values and isinstance(v.values[0], ast.Constant):
            return [str(v.values[0].value)]
        return []

    tree = ast.parse(inspect.getsource(F))
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                targets = [t for t in n.targets if isinstance(t, ast.Attribute) and t.attr == "status"]
                targets += [e for t in n.targets if isinstance(t, ast.Tuple) for e in t.elts
                            if isinstance(e, ast.Attribute) and e.attr == "status"]
                if not targets:
                    continue
                for v in (n.value.elts if isinstance(n.value, ast.Tuple) else [n.value]):
                    for w in _words(v):
                        out.setdefault(fn.name, set()).add(w)
            elif isinstance(n, ast.Call):
                for kw in n.keywords:
                    if kw.arg != "status":
                        continue
                    for w in _words(kw.value):
                        out.setdefault(fn.name, set()).add(w)
    return out


def test_every_status_the_producer_can_assign_is_in_the_CLOSED_set():
    """The closed status enum, enforced against the CODE rather than against a habit. Each of these
    words is rendered to a reader as an SB-X absence line, so a word invented at a call site would be a
    vocabulary nobody declared and the render would have no sentence for it.

    THREE ENUMS, GRADED APART. ``tape_state`` writes SB-T's own words (``no_tape_slug``,
    ``pre_coverage``, ``front_decline``, ``changes_thin``, ``percentile_thin``), ``text_state`` writes
    the text half's three (sec 2.2) and the series producer writes sec 1.3's; a word from any of them
    that is not declared in ITS OWN set fails here. The third set became a CONSTANT at S2 because the
    widened scanner above found it closed only in a docstring -- i.e. graded by nothing."""
    from leviathan.graphrag.state.rows import (
        STATUS_WITH_DETAIL,
        TAPE_STATUS_WITH_DETAIL,
        TAPE_STATUS_WORDS,
        TEXT_STATUS_WORDS,
        status_word,
    )
    by_fn = _assigned_statuses()
    assert by_fn, "the producer assigns no status at all -- the AST walk is looking at the wrong thing"
    for fn, words in by_fn.items():
        tape = fn == "tape_state"
        vocab = (TEXT_STATUS_WORDS if fn == "text_state"
                 else TAPE_STATUS_WORDS if tape else STATUS_WORDS)
        detail = TAPE_STATUS_WITH_DETAIL if tape else STATUS_WITH_DETAIL
        for w in words:
            head = status_word(w)
            assert head in vocab, f"{fn}: {w!r} is not a declared status word"
            if w != head:
                assert head in detail, f"{fn}: {head!r} carries a ':detail' but is not declared to"


def test_the_two_words_the_first_S1_cut_invented_are_gone_from_the_series_enum():
    """A REGRESSION PIN on a review finding. ``undeclared_cross_section`` appears in the design ONCE, as
    the REASON attached to ``read_empty`` (sec 2.6 step 5), and ``no_card`` appears ZERO times -- yet both
    were sitting in the closed set, which is the set the S3 render owes a sentence per word. Each is now
    a design word plus a detail, and the producer's own assignments are what this checks."""
    assert "undeclared_cross_section" not in STATUS_WORDS and "no_card" not in STATUS_WORDS
    assigned = set().union(*_assigned_statuses().values())
    assert "undeclared_cross_section" not in assigned and "no_card" not in assigned
    assert "read_empty:undeclared_cross_section" in assigned
    assert "unmapped_ref:no_registry_card" in assigned


def test_an_unresolved_scope_declines_with_the_RESOLVERS_own_reason_word():
    """The census measured that ONE undifferentiated 'region-unresolved' string mislabelled 37 of 260
    declines. The board never re-guesses the reason: it prints the one ``_scope_ex`` returned."""
    n = _Node("soybeans_cbot", "some_driver", "drought_z", region="a_token_no_map_resolves")
    r = F.series_state("drought_z", n, "2026-09-08", qfn=lambda sql: [], silver_status="available")
    assert r.status.startswith("scope_unresolved:")
    assert r.status.split(":", 1)[1] == "region-token-unresolved"
    assert r.reads == 0


# ── the read (sec 2.1) ───────────────────────────────────────────────────────────────────────────────
def test_the_board_read_is_a_windowed_capped_series_never_a_whole_history_read():
    """``cascade.fetch_window`` takes no ``limit`` and binds ``period_start=None``; on silver_fred_fx
    (5,538 daily rows against a 5,000 cap, ASC) the rows the cap drops are the NEWEST ones.

    THE MONTHLY DATE MOVED AT THE READ-SPAN LANDING, 2016-09-01 -> 2015-09-01, and the move IS the fix:
    the span was 120 months against a 120-month window, so the array arrived short by the publication
    lag and the z declined for ever. It is now ``window + CADENCE_READ_SLACK['monthly']`` = 132.
    ``tests/unit/test_state_read_span.py`` holds the invariant and the reproduction."""
    spec = F.board_spec("silver_noaa_oni", "oni_anom", "soybeans_cbot", None, "2026-09-08", "monthly")
    assert spec.agg == "series"
    assert spec.limit == F.READ_LIMIT == 5000
    assert spec.period_start == "2015-09-01"                 # asof minus the monthly span's 132 months
    daily = F.board_spec("silver_futures_eod", "settle", "corn_cbot", None, "2026-09-08", "daily")
    assert daily.period_start == "2021-09-08"                # five years, never 'full history'
    assert F.board_spec("silver_psd", "su_ratio", "corn", "United States", "2026-09-08",
                        "annual").period_start is None       # ~66 MY rows: a bound would prune nothing


def test_a_full_row_is_produced_end_to_end_from_a_fixture_with_no_store():
    rows = _oni_rows()
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120},
                       conventions={"oni_climate": {"kind": "abs_bands", "bands": [0.5, 1.0, 1.5, 2.0],
                                                    "labels": ["elevated", "moderate", "strong",
                                                               "extreme"], "verified": "silverleg"}},
                       silver_status="available")
    assert r.status == "ok" and r.reads == 1
    assert r.key == SeriesKey("oni_climate", "_global", "")
    assert r.cadence == "monthly" and r.window_note == "120 months"
    assert r.level is not None and r.level_date
    assert r.percentile and r.percentile["declined"] is False
    assert [c["window"] for c in r.changes] == ["1 month", "3 months", "12 months"]
    assert r.convention and r.convention["kind"] == "abs_bands"
    assert F.re_execute_row(r) == []                          # every figure reproduces from its rows


def test_ONE_read_serves_EVERY_board_because_the_key_is_normalised_by_the_CARDS_axes():
    """The line that makes one ONI read serve 35 rows in CODE as it does in prose. ``_scope_ex`` hands
    back the CONTRACT slug and the primary title for ``oni_climate`` -- which declares no country rule at
    all -- so keying on its tuple would mint one ENSO state per board and pay 35 reads for one number."""
    rows = _oni_rows()
    keys = set()
    for contract in ("soybeans_cbot", "corn_cbot", "wheat_cbot", "malaysian_crude_palm_oil_cme"):
        r = F.series_state("oni_climate", _Node(contract, "El_Nino", "oni_climate"), "2026-09-08",
                           qfn=_pit_qfn(rows, "2026-09-08", commodity=contract),
                           windows={"monthly": 120}, silver_status="available")
        keys.add(r.key)
    assert keys == {SeriesKey("oni_climate", "_global", "")}


def test_the_fx_card_keeps_its_GEOGRAPHY_IN_THE_METRIC_and_the_key_must_carry_it():
    """MEASURED at the S1 landing, and the reason the key has a fourth term. ``silver_fred_fx`` is a
    WIDE card with ``commodity_col: null`` and ``country_col: null`` and fourteen currency metrics; the
    map row declares ``brl_usd`` and ``cascade._region_row`` SWAPS it to the resolved region's currency.
    Normalising by the card's axes alone keys every board's FX read as ``('_global', '')`` -- one shared
    entry serving a Brazilian real z to a board reading the yuan, silently, and IMMORTALLY on a
    historical as-of."""
    from leviathan.graphrag.numbers import cascade as casc
    from leviathan.graphrag.numbers.registry import load_registry as _reg
    ts = _reg().get("silver_fred_fx")
    assert ts.commodity_col is None and ts.country_col is None, "the premise of the defect"
    row = casc.map_row("fred_fx_macro")
    seen = {}
    for contract, token in (("soybeans", "Brazil"), ("soybeans_no_1_dce", "China")):
        n = _Node(contract, "fx", "fred_fx_macro", region=token)
        commodity, country, skip = casc._scope_ex(n, row)
        if country is casc.SKIP_NODE:
            pytest.skip(f"region token {token!r} does not resolve in this tree")
        metric = casc._region_row(n, row).get("metric")
        c, k, m = F._scope_for_card(ts, commodity, country, declared_metric=row.get("metric"),
                                    resolved_metric=metric,
                                    country_rule=row.get("country_rule"))
        seen[token] = SeriesKey("fred_fx_macro", c, k, m)
    assert len(set(seen.values())) == len(seen), f"two currencies collapsed onto one key: {seen}"
    # EVERY region carries its currency, including the one the map row was written with -- separating
    # Brazil from China only because 'brl_usd' happens to be the declared default would re-collapse them
    # the day someone edits the map row
    assert all(key.metric for key in seen.values()), seen
    assert {k.metric for k in seen.values()} == {"brl_usd", "cny_usd"}
    # and a card read under a rule that does NOT swap metrics keeps an empty term, so the declared
    # same-series collapse (oni_lag6 -> oni_climate) still holds
    oni_ts = _reg().get("silver_noaa_oni")
    assert F._scope_for_card(oni_ts, "soybeans_cbot", "United States", declared_metric="oni_lag6",
                             resolved_metric="oni_lag6", country_rule="none") == ("_global", "", "")


def test_the_lagged_palm_row_collapses_onto_the_SAME_series_key_at_a_declared_offset():
    """``oni_lag_climate`` is the SAME ENSO series read at the six-month offset the served column
    carries -- never a second ENSO state and never a second read. The palm author's "state now" is ONI
    six months ago, and BOTH dates print."""
    rows = _oni_rows()
    base = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                          qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120},
                          silver_status="available")
    palm = F.series_state("oni_lag_climate",
                          _Node("malaysian_crude_palm_oil_cme", "El_Nino", "oni_lag_climate"),
                          "2026-09-08", qfn=_pit_qfn(rows, "2026-09-08",
                                                     commodity="malaysian_crude_palm_oil_cme"),
                          windows={"monthly": 120}, silver_status="available")
    assert palm.key == base.key, "the far row must not mint a second ENSO state"
    assert palm.offset_months == 6
    assert palm.level_date != base.level_date                 # the offset reading has its OWN month
    assert palm.coverage["n_obs"] == base.coverage["n_obs"] - 6


def test_THE_FOLD_COSTS_ONE_READ_AND_READS_THE_BASE_METRIC_never_the_lagged_column_twice(monkeypatch):
    """THE REVIEW'S FATAL, pinned with a fixture that can SEE it.

    The first S1 cut read the alias row's OWN metric (``oni_lag_climate`` declares ``metric: oni_lag6``)
    and then applied ``offset_months: 6`` on top. ``bronze_to_silver/noaa_oni.py:125`` defines that column
    as ``df["oni_anom"].shift(n)``, so the palm board's "ENSO state now" was the anomaly from TWELVE
    months ago while the row, the map row's note and design sec 2.6 all say six -- and it cost a SECOND
    read of the one series the whole dark half of phase 1a exists to share. MEASURED before the fix, at
    as-of 2026-09-08 on this very fixture: two ``query_fn`` calls (``oni_anom``, ``oni_lag6``), level
    dates 2026-07 and 2026-01, n_obs 119 and 113.

    THE OLD PINS COULD NOT SEE IT: ``fixture_query_fn`` matched on the TABLE name only and served the same
    canned rows for both metrics, and nothing counted reads. This one serves a DIFFERENT array per metric
    and counts the calls, so the claim ("resolves to the same series key at ONE memoised read") is
    falsifiable by construction.

    AND ITS FIRST CUT COULD ONLY SEE HALF OF IT. The fix above repaired the METRIC and left the COUNT:
    the alias and its base are two STATES of one series, so they miss the memo's state layer by design,
    and that miss went straight to the store -- TWO ``query_fn`` calls (both ``oni_anom``) with
    ``GRAPHRAG_STATE_CACHE=on``, where sec 3.6 says the palm reading is computed on the SAME memoised
    array at ZERO extra reads. This pin now asserts the COUNT, with the memo armed, because a read count
    nobody counts is the claim the fold exists to make."""
    monkeypatch.setenv("GRAPHRAG_STATE_CACHE", "on")
    F.cache_clear()
    anom = _oni_rows()
    lag6 = [dict(r, value=str(float(r["value"]) + 100.0)) for r in anom]      # visibly NOT the same array
    ts = load_registry().get("silver_noaa_oni")
    spec = F.board_spec("silver_noaa_oni", "oni_anom", "soybeans_cbot", None, "2026-09-08", "monthly")
    qfn = F.fixture_query_fn({"silver_noaa_oni:oni_anom": anom, "silver_noaa_oni:oni_lag6": lag6},
                             pit={"silver_noaa_oni": (spec, ts)})
    base = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                          qfn=qfn, windows={"monthly": 120}, silver_status="available")
    palm = F.series_state("oni_lag_climate",
                          _Node("malaysian_crude_palm_oil_cme", "El_Nino", "oni_lag_climate"),
                          "2026-09-08", qfn=qfn, windows={"monthly": 120}, silver_status="available")
    assert base.status == "ok" and palm.status == "ok"
    assert len(qfn.calls) == 1, \
        f"the fold paid a SECOND physical read of the base series (sec 3.6: zero extra): {qfn.calls}"
    assert base.reads == 1 and palm.reads == 0, "the row that PAID carries the 1; the fold's row spent 0"
    assert all("oni_anom AS value" in s for s in qfn.calls), \
        f"the fold must read the BASE metric, never the alias's already-shifted column: {qfn.calls}"
    assert all("oni_lag6" not in s for s in qfn.calls)
    assert palm.metric == "oni_anom" and base.metric == "oni_anom"
    assert palm.key == base.key == SeriesKey("oni_climate", "_global", "")
    assert palm.alias_ref == "oni_lag_climate" and base.alias_ref == ""
    # the palm reading IS the base array shifted six months -- the same numbers, six rows back
    vals = base.inputs[base.key.label()]["values"]
    dates = base.inputs[base.key.label()]["dates"]
    assert palm.level == vals[-7] and palm.level_date == dates[-7]
    assert palm.coverage["n_obs"] == base.coverage["n_obs"] - 6
    assert "declared 6-month offset" in palm.offset_note and "oni_climate" in palm.offset_note
    assert "cost no read of its own" in palm.offset_note
    # BOTH DATES PRINT, AND THE SECOND ONE IS THE PALM READING'S OWN. The knowledge date is read off the
    # served row the LEVEL came from; reading it off the newest row printed the soybean board's
    # 2026-09-05 beside a 2026-01 level -- a date belonging to a different observation.
    assert palm.level_date == "2026-01" and base.level_date == "2026-07"
    assert palm.knowledge_date and palm.knowledge_date < base.knowledge_date
    assert palm.recency["age_days"] > base.recency["age_days"]
    F.cache_clear()


def test_the_fold_is_ORDER_INDEPENDENT_and_two_children_of_one_parent_still_cost_ONE_read(monkeypatch):
    """The read layer is keyed on the SERIES key, so which row asks first cannot change what a turn pays.

    THE THIRD CASE IS THE ONE THE SCOPE NORMALISATION CARRIES: two palm boards ask for the same alias on
    a card with NEITHER a commodity column nor a country column, so ``_scope_ex`` hands back two
    different contract slugs and only ``_scope_for_card``'s ``('_global', '')`` makes them one key -- and
    one read.

    THE FOURTH IS THE ROLLBACK, MEASURED: with the memo unarmed every call reads for itself, exactly as
    it did before this fix. The fold's zero-extra-read property is a property of the MEMO -- as is the
    design's own "2 reads serving 65 + 24 rows on 33 + 18 boards"."""
    anom = _oni_rows()
    lag6 = [dict(r, value=str(float(r["value"]) + 100.0)) for r in anom]
    ts = load_registry().get("silver_noaa_oni")
    spec = F.board_spec("silver_noaa_oni", "oni_anom", "soybeans_cbot", None, "2026-09-08", "monthly")

    def _qfn():
        return F.fixture_query_fn({"silver_noaa_oni:oni_anom": anom, "silver_noaa_oni:oni_lag6": lag6},
                                  pit={"silver_noaa_oni": (spec, ts)})

    def _base(q):
        return F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"),
                              "2026-09-08", qfn=q, windows={"monthly": 120},
                              silver_status="available")

    def _palm(q, contract="malaysian_crude_palm_oil_cme"):
        return F.series_state("oni_lag_climate", _Node(contract, "El_Nino", "oni_lag_climate"),
                              "2026-09-08", qfn=q, windows={"monthly": 120},
                              silver_status="available")

    monkeypatch.setenv("GRAPHRAG_STATE_CACHE", "on")
    F.cache_clear()
    q = _qfn()
    palm, base = _palm(q), _base(q)                      # THE CHILD FIRST
    assert len(q.calls) == 1 and palm.reads == 1 and base.reads == 0
    assert palm.metric == base.metric == "oni_anom", "the child's read is the BASE series either way"
    assert palm.coverage["n_obs"] == base.coverage["n_obs"] - 6

    F.cache_clear()
    q = _qfn()
    p1, p2 = _palm(q), _palm(q, contract="palm_oil_bursa")   # TWO CHILDREN OF ONE PARENT
    assert len(q.calls) == 1
    assert p1.key == p2.key and p1.level == p2.level and p1.level_date == p2.level_date

    monkeypatch.delenv("GRAPHRAG_STATE_CACHE", raising=False)
    F.cache_clear()
    q = _qfn()
    base, palm = _base(q), _palm(q)                       # THE MEMO OFF: the declared cost
    assert len(q.calls) == 2, "unarmed, every call reads for itself -- byte-identical to before the fix"
    assert base.level != palm.level and palm.metric == "oni_anom"
    F.cache_clear()


def test_an_offset_LONGER_THAN_THE_FETCHED_HISTORY_is_not_applied_and_the_row_says_so():
    """Fences CORRECT or COMPUTE, never delete -- and never silently skip. The shift is guarded by
    ``len(values) > n``, and before this fix a history shorter than the offset fell through that guard
    with the note still claiming a six-month reading: an UNSHIFTED level wearing a shifted label."""
    rows = _oni_rows(n=5, start=(2026, 1))
    r = F.series_state("oni_lag_climate",
                       _Node("malaysian_crude_palm_oil_cme", "El_Nino", "oni_lag_climate"),
                       "2026-09-08",
                       qfn=_pit_qfn(rows, "2026-09-08", commodity="malaysian_crude_palm_oil_cme"),
                       windows={"monthly": 120}, silver_status="available")
    assert r.offset_months == 6 and r.coverage["n_obs"] == 5, "the guard's own branch must be the one run"
    assert r.offset_note == ("a declared 6-month offset is NOT applied: the fetched history is "
                             "5 monthly periods, no longer than the offset")
    assert r.level is not None and r.level_date == "2026-05", \
        "the row still serves its UNSHIFTED reading -- with the offset named, never silently dropped"


def test_the_read_key_splits_on_the_WHERE_CLAUSE_never_on_the_slug_that_was_asked_for():
    """``series_read_key``'s ``row_filter_sig`` term, and the shipped card that makes it concrete.

    The read layer is keyed on the SERIES key, whose scope is normalised by the card's axes -- which is
    what lets one ONI read serve every board. ``query._metric_commodity_filters`` is the one thing that
    can put the ASKED-FOR SLUG into a WHERE clause on a card with no commodity axis, and one live board
    ref sits exactly there: ``cbot_board_crush_margin`` -> ``gold_board_crush.crush_margin_usd_bu``
    (``commodity_col: null``, ``country_col: null``), with ``row_filters`` keyed for five slugs. Those
    five entries are the SAME roll-boundary fence, so they compile ONE SQL and share ONE read -- and this
    term is what makes the sharing FOLLOW that fact instead of assuming it."""
    from leviathan.graphrag.numbers import query as Q
    ts = load_registry().get("gold_board_crush")
    assert not ts.commodity_col and not ts.country_col, "the card that makes the term load-bearing"
    slugs = ("soybeans_cbot", "soybean_oil_cbot", "soybean_meal_cbot", "soy_complex")
    sigs = {c: F._row_filter_sig(ts, "crush_margin_usd_bu", c) for c in slugs}
    assert all(sigs.values()) and len(set(sigs.values())) == 1, sigs
    sqls = {c: Q.build_sql(F.board_spec("gold_board_crush", "crush_margin_usd_bu", c, None,
                                        "2026-09-08", "daily"), ts, ym_lag=True) for c in slugs}
    assert len(set(sqls.values())) == 1, "one series key, one WHERE clause -- measured, not assumed"
    # every other board read carries an EMPTY term, so no other read key moves
    assert F._row_filter_sig(load_registry().get("silver_noaa_oni"), "oni_anom", "soybeans_cbot") == ""
    # and two DIFFERENT clauses are two reads: the key splits rather than sharing one array
    kw = dict(key=SeriesKey("x", "_global", ""), table="t", metric="m", asof_s="2026-09-08",
              cadence="monthly", read_shape="nf_all", ym_lag=True)
    assert F.series_read_key(row_filter_sig="a", **kw) != F.series_read_key(row_filter_sig="b", **kw)
    assert F.series_read_key(**kw)[-1] == F.mirror_epoch(), \
        "a fetched array may not outlive a mirror reload any more than a computed state may"


def test_the_fold_REFUSES_an_alias_whose_base_is_a_different_series_and_says_so(monkeypatch):
    """THE FENCE, and the review finding it answers: the memo key separated two alias rows only by their
    offset, so an alias resolving to a DIFFERENT physical series would have served one metric's array
    under another's key -- silently, and immortally on a historical as-of. Nothing checked the alias's
    table against the base's (``state/lint.py`` requires the offset to be DECLARED, never that the two
    rows name one series).

    Failing this way costs one extra read on a misconfigured row and can never mislabel an array."""
    real = F.board_map_row
    alias = {"table": "silver_noaa_oni", "metric": "oni_lag6", "country_rule": "none",
             "same_series_as": "not_the_same_series", "offset_months": 6,
             "native_unit": "degC", "narrate_unit": "degC", "scale": 1}
    other = {"table": "silver_psd", "metric": "su_ratio", "country_rule": "primary",
             "native_unit": "ratio", "narrate_unit": "%", "scale": 100}
    monkeypatch.setattr(F, "board_map_row",
                        lambda ref: {"bad_alias": alias, "not_the_same_series": other}.get(ref)
                        or real(ref))
    rows = _oni_rows()
    r = F.series_state("bad_alias", _Node("malaysian_crude_palm_oil_cme", "El_Nino", "bad_alias"),
                       "2026-09-08", qfn=_pit_qfn(rows, "2026-09-08", metric="oni_lag6",
                                                  commodity="malaysian_crude_palm_oil_cme"),
                       windows={"monthly": 120}, silver_status="available")
    assert r.key.ref == "bad_alias", "an unfoldable alias keeps its OWN key rather than borrowing one"
    assert r.alias_ref == "" and r.metric == "oni_lag6"
    assert "NOT folded" in r.offset_note and "different table" in r.offset_note
    base = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                          qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120},
                          silver_status="available")
    assert r.coverage["n_obs"] == base.coverage["n_obs"], "the offset is the column's own; not applied twice"


def test_a_marketing_year_vintage_row_is_labelled_by_its_PERIOD_not_by_the_release_stamp():
    """Found in review, and it is the kind of defect a plausible-looking axis hides: every row of ONE
    PSD release shares one ``release_date``, so labelling the series by the knowledge date would print
    the release stamp where the reader expects the marketing year -- and every change window would then
    name a span it never measured. The axis mirrors ``cascade._pace_period_key``'s own preference order,
    with the ``period`` label ahead of ``knowledge_date`` for exactly this card class."""
    rows = [{"value": str(10.0 + i), "period": f"{2016 + i}/{17 + i}", "knowledge_date": "2026-08-13",
             "country": "United States"} for i in range(12)]
    r = F.series_state("psd_ending_stock_su_ratio",
                       _Node("corn_cbot", "us_stocks", "psd_ending_stock_su_ratio"), "2026-09-08",
                       qfn=F.fixture_query_fn({"silver_psd": rows}), windows={"annual": 10},
                       silver_status="available")
    assert r.cadence == "annual" and r.status == "ok"
    assert r.level_date == "2027/28", "the newest MARKETING YEAR, never the release stamp"
    assert r.coverage["history_start"] == "2016/17"
    assert [c["window"] for c in r.changes] == ["1 marketing year", "5 marketing years"]
    # the release stamp still drives the KNOWLEDGE date -- the two are different facts and both print
    assert r.knowledge_date == "2026-08-13"
    assert "the vintage served at this as-of" in r.knowledge_basis


def test_the_provenance_role_is_read_off_the_ALIAS_the_store_actually_serves():
    """``query._extras`` surfaces ``provenance_col`` under the alias ``revision_stamp``. Reading the
    card's physical column name off the row finds nothing, and the role would be silently None on all
    nine cards that declare one -- the K9-4 fact the vintage-role fence is built on."""
    from leviathan.graphrag.numbers import query as Q
    ts = load_registry().get("silver_wasde")
    aliases = {alias for _expr, alias in Q._extras(ts)}
    assert ts.provenance_col and "revision_stamp" in aliases
    assert ts.provenance_col not in aliases, "the physical column name is NOT what the row carries"


def test_the_truncation_detector_fires_by_name():
    """``len(rows) == limit`` is the detector (bar B3). A silently truncated history is a z against a
    window the row never had."""
    rows = _oni_rows(n=F.READ_LIMIT + 5)
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=F.fixture_query_fn({"silver_noaa_oni": rows[:F.READ_LIMIT]}),
                       windows={"monthly": 120}, silver_status="available")
    assert r.status == f"history_truncated:{F.READ_LIMIT}"
    assert r.coverage["truncated"] is True


def test_an_empty_read_is_a_row_that_says_so():
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=lambda sql: [], silver_status="available")
    assert r.status == "read_empty" and r.reads == 1 and r.level is None


def test_a_pool_decline_is_the_boards_OWN_word_and_never_an_athena_fallback():
    """The board declines ``pool_exhausted`` / ``pg_timeout`` BY NAME. ``pgnumbers.query_fn``'s
    per-request Athena fallback would re-run the same series SQL at a 2-3 s planning floor and log a
    warning naming no caller -- and ``_NUM_BORROWS`` is one lane-wide counter, so it could not even be
    attributed to the board afterwards."""
    def _boom(sql):
        raise F.BoardReadDecline("pool_exhausted", "no connection freed in 5s")
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=_boom, silver_status="available")
    assert r.status == "pool_exhausted" and r.reads == 1
    assert r.status in STATUS_WORDS


def test_the_handler_never_raises_and_a_CRASHED_read_is_not_an_EMPTY_one():
    """``cascade._run_one``'s own contract: a silver miss may never break an answer.

    AND THE WORD IS ``read_error``, not ``read_empty`` (sec 6.7's own series vocabulary). The render
    fronts an empty read with "NO ROWS RETURNED" -- a false sentence about a read that crashed -- and the
    LEDGER must see the attempt: a raised read spent the same slot a declined one did, so ``reads`` is 1
    exactly as it is on the ``BoardReadDecline`` path, and the rectangle closes."""
    def _explode(sql):
        raise RuntimeError("the mirror is on fire")
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=_explode, silver_status="available")
    assert r.status == "read_error" and "on fire" in r.recency["read_error"]
    assert r.reads == 1, "the ledger rectangle is short by the attempted read"


# ── POINT-IN-TIME (sec 1.4) ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("asof", ["2026-09-08", "2024-03-15", "2020-06-30"])
def test_PIT_PIN_a_row_at_asof_T_never_reads_a_knowledge_date_after_T(asof):
    """THE PIN. The fixture executor runs ``apply_pit_filter`` -- build_sql's own oracle -- over the
    canned rows, so the offline board is filtered by the same rule the mirror applies. Every row the
    producer then reads must have been KNOWABLE at the as-of: no future data month, and no derived
    knowledge date past the as-of."""
    rows = _oni_rows(n=200, start=(2012, 1))
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), asof,
                       qfn=_pit_qfn(rows, asof), windows={"monthly": 120}, silver_status="available")
    assert r.status in ("ok", "read_empty") or r.status.startswith("thin_history")
    if r.level_date:
        assert r.level_date <= asof[:7], "a data month later than the as-of month reached the row"
    if r.knowledge_date:
        assert r.knowledge_date <= asof, "a row was read that nobody could have known at the as-of"
    for d in (r.coverage.get("history_start"), r.coverage.get("history_end")):
        if d:
            assert d <= asof[:7]


def test_the_ym_lag_is_ON_for_the_boards_own_reads_from_day_one():
    """The board's reads are its OWN and move nothing else, so it does not wait for the estate-wide
    flag. With the lag armed, the newest ONI month at 2026-09-08 is 2026-07 (month-end plus 36 days),
    not 2026-09."""
    rows = _oni_rows(n=200, start=(2012, 1))
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120},
                       silver_status="available")
    assert r.level_date == "2026-07"
    unlagged = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"),
                              "2026-09-08", qfn=_pit_qfn(rows, "2026-09-08", ym_lag=False),
                              windows={"monthly": 120}, ym_lag=False, silver_status="available")
    assert unlagged.level_date == "2026-09"                  # the defect, reproduced under the flag off


def test_the_knowledge_date_is_DERIVED_PER_CARD_CLASS_and_says_which_derivation_ran():
    reg = load_registry()
    ym = reg.get("silver_noaa_oni")
    kd, basis = F.derive_knowledge_date(ym, {"year": 2026, "month": 7})
    assert kd == "2026-09-05"                                # 2026-07-31 plus the declared 36 days
    assert "data month 2026-07, knowable from 2026-09-05" in basis
    # a card with no lag declared says so rather than inventing one
    stripped = ym.model_copy(update={"ym_publication_lag_days": None})
    kd2, basis2 = F.derive_knowledge_date(stripped, {"year": 2026, "month": 7})
    assert kd2 == "2026-07-31" and "no publication lag declared" in basis2


def test_the_replay_LABEL_rides_a_latest_only_card_at_a_historical_asof_and_the_row_still_SERVES():
    """Revision 1 of the design DECLINED those refs' series half at zero reads. That is a fence that
    deletes where a label already exists -- it would have darkened the ENSO state on 33 boards in every
    replayed census, every harness render and every backdated question."""
    rows = _oni_rows(n=200, start=(2012, 1))
    past = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2020-06-30",
                          qfn=_pit_qfn(rows, "2020-06-30"), windows={"monthly": 120},
                          silver_status="available", today="2026-09-08")
    assert past.status == "ok", "the row SERVES; the label is not a decline"
    assert past.vintage_note and "revised in place" in past.vintage_note
    assert "2020-06-30" in past.vintage_note and "2026-09-08" in past.vintage_note
    live = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                          qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120},
                          silver_status="available", today="2026-09-08")
    assert live.vintage_note is None                          # a live as-of carries no replay label


# ── the flag row's two feeder rules (sec 2.1) ────────────────────────────────────────────────────────
def test_a_flag_ref_carries_flag_state_and_declines_z_and_percentile_BY_NAME():
    r = F.state_from_arrays("frost_event_flag", [0, 0, 1, 0, 0, 0, 0, 1, 0, 0],
                            ["2025-%02d" % m for m in range(1, 11)], cadence="monthly",
                            asof="2026-09-08", is_flag=True, windows={"monthly": 120})
    assert r.flag_state["last_event_date"] == "2025-08"
    assert r.flag_state["periods_since"] == 2
    assert r.z["declined"] is True and "base rate" in r.z["reason"]
    assert r.percentile["declined"] is True
    assert F.re_execute_row(r) == []


# ── the offline harness (item g) ─────────────────────────────────────────────────────────────────────
def test_the_harness_builds_a_row_from_fixture_arrays_with_no_sql_at_all():
    vals = [10.0, 10.5, 11.0, 10.2, 9.8, 10.9, 11.4, 12.0, 12.6, 13.1]
    dates = ["2026-%02d-01" % m for m in range(1, 11)]
    r = F.state_from_arrays("cbot_board_crush_margin", vals, dates, cadence="monthly",
                            asof="2026-10-15", unit="USD/bu", windows={"monthly": 10},
                            convention={"kind": "percentile_bands", "bands": [10, 90],
                                        "labels": ["low", "high"], "verified": None})
    assert r.level == 13.1 and r.level_date == "2026-10-01"
    assert r.z and r.z["declined"] is False                   # 10 points, a 10-month window
    assert r.convention["label"] == "high"                    # the newest value is the series maximum
    # hand-computed: the trailing up-run is 9.8 -> 10.9 -> 11.4 -> 12.0 -> 12.6 -> 13.1, five moves, so
    # the run STARTED at the 9.8 print in May
    assert r.run == {"direction": "up", "length": 5, "since_date": "2026-05-01"}
    assert F.re_execute_row(r) == []


def test_the_harness_and_the_read_path_write_the_SAME_derivations_in_the_SAME_order():
    """It is not a second producer: every measure is the same registry call, in the same order."""
    rows = _oni_rows()
    live = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                          qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120},
                          silver_status="available")
    vals = live.inputs[live.key.label()]["values"]
    dates = live.inputs[live.key.label()]["dates"]
    off = F.state_from_arrays("oni_climate", vals, dates, cadence="monthly", asof="2026-09-08",
                              windows={"monthly": 120})
    assert [d["transform"] for d in off.derivation] == [d["transform"] for d in live.derivation]
    assert off.level == live.level and off.percentile["value"] == live.percentile["value"]


# ── the memo (sec 1.1) ───────────────────────────────────────────────────────────────────────────────
def test_the_memo_key_is_silverlegs_key_plus_the_terms_the_board_needs():
    k1 = F.state_cache_key(SeriesKey("oni_climate", "_global", ""), "2026-09-08", "nf_all", "aaaa")
    k2 = F.state_cache_key(SeriesKey("oni_climate", "_global", ""), "2026-09-08", "nf_all", "bbbb")
    k3 = F.state_cache_key(SeriesKey("oni_climate", "_global", ""), "2026-09-08", "asc", "aaaa")
    k4 = F.state_cache_key(SeriesKey("oni_climate", "_global", ""), "2026-09-08", "nf_all", "aaaa", 6)
    k5 = F.state_cache_key(SeriesKey("oni_climate", "_global", ""), "2026-09-08", "nf_all", "aaaa", 6,
                           "oni_lag_climate")
    k6 = F.state_cache_key(SeriesKey("oni_climate", "_global", ""), "2026-09-08", "nf_all", "aaaa", 6,
                           "some_other_alias")
    assert k1 != k2, "two transform parameter sets are two states of one series"
    assert k1 != k3, "two orderings are two reads"
    assert k1 != k4, "a declared same-series OFFSET is a different STATE of the same read"
    assert k4 != k5 != k6 and k5 != k6, \
        "two aliases folding onto one base at one offset must not share an entry -- the second reader " \
        "would be handed the first one's label"
    assert k1[-1] == F.mirror_epoch(), "a historical entry may not outlive a mirror reload"


def test_the_lagged_palm_row_is_NOT_served_the_unlagged_boards_state_from_the_memo(monkeypatch):
    """The offset is not on the SERIES key -- that is why it costs no read -- but it IS on the MEMO key,
    because the palm board's state is a different state: same array, shifted six months, so a different
    level, level date, z and run."""
    monkeypatch.setenv("GRAPHRAG_STATE_CACHE", "on")
    F.cache_clear()
    rows = _oni_rows()
    base = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                          qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120},
                          silver_status="available")
    palm = F.series_state("oni_lag_climate",
                          _Node("malaysian_crude_palm_oil_cme", "El_Nino", "oni_lag_climate"),
                          "2026-09-08",
                          qfn=_pit_qfn(rows, "2026-09-08", commodity="malaysian_crude_palm_oil_cme"),
                          windows={"monthly": 120}, silver_status="available")
    assert palm.key == base.key
    assert palm.offset_months == 6 and base.offset_months == 0
    assert palm.level_date != base.level_date and palm.level != base.level
    F.cache_clear()


def test_the_cache_is_LRU_BOUNDED_because_it_holds_ARRAYS_not_scalars(monkeypatch):
    """silverleg's shared cache holds scalar verdicts and is unbounded; this one holds whole arrays, and
    an immortal entry (a historical as-of) never expires on its own -- an eval deck at fixed as-ofs or
    the offline harness would grow it without limit."""
    monkeypatch.setenv("GRAPHRAG_STATE_CACHE", "on")
    F.cache_clear()
    for i in range(F.STATE_CACHE_MAX + 25):
        F.cache_put((f"k{i}",), {"v": i}, "2020-01-01")
    assert len(F._SHARED) == F.STATE_CACHE_MAX
    assert F.cache_get(("k0",)) is None                       # the oldest were evicted
    assert F.cache_get((f"k{F.STATE_CACHE_MAX + 24}",)) == {"v": F.STATE_CACHE_MAX + 24}
    F.cache_clear()


def test_the_memo_serves_the_second_ask_without_a_second_read(monkeypatch):
    """The read count of a turn is the DISTINCT SERIES-KEY count, not the row count -- one ONI read
    serving 35 boards is the whole arithmetic the wave pricer is built on."""
    monkeypatch.setenv("GRAPHRAG_STATE_CACHE", "on")
    F.cache_clear()
    rows = _oni_rows()
    calls = {"n": 0}
    inner = _pit_qfn(rows, "2026-09-08")

    def _counting(sql):
        calls["n"] += 1
        return inner(sql)

    kw = dict(qfn=_counting, windows={"monthly": 120}, silver_status="available")
    a = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08", **kw)
    b = F.series_state("oni_climate", _Node("corn_cbot", "El_Nino", "oni_climate"), "2026-09-08", **kw)
    assert calls["n"] == 1, "the second board paid a read for a state the first already computed"
    assert a.key == b.key and a.level == b.level and b.reads == 1
    # DIFFERENT PARAMETERS ARE A DIFFERENT STATE: a 60-month window may not be served a 120-month z.
    # IT IS NOT A DIFFERENT READ, and that distinction is the memo's two layers (sec 1.1 + the read
    # layer). This assertion USED to be `calls["n"] == 2` -- it counted reads to prove a STATE was
    # recomputed, so it also froze the second read the same-series fold's fix removes. The state is
    # proved recomputed by the transform it RAN, which is the thing that was actually at stake.
    c = F.series_state("oni_climate", _Node("wheat_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=_counting, windows={"monthly": 60}, silver_status="available")
    assert calls["n"] == 1, "a second transform plan over an array already in memory pays no read"
    assert c.reads == 0 and c.key == a.key
    zs = [d for d in c.derivation if d["transform"] == "zscore"]
    assert zs and zs[0]["params"]["window"] == 60, "the 60-month ask was served a 120-month z"
    assert c.z != a.z, "two windows are two states of one series"
    F.cache_clear()


def test_a_cache_hit_is_deep_copied_so_one_consumer_cannot_poison_the_next(monkeypatch):
    monkeypatch.setenv("GRAPHRAG_STATE_CACHE", "on")
    F.cache_clear()
    rows = _oni_rows()
    kw = dict(qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120}, silver_status="available")
    a = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08", **kw)
    a.inputs[a.key.label()]["values"].clear()
    a.changes.clear()
    b = F.series_state("oni_climate", _Node("corn_cbot", "El_Nino", "oni_climate"), "2026-09-08", **kw)
    assert b.inputs[b.key.label()]["values"], "an in-place trim reached the shared entry"
    assert b.changes and F.re_execute_row(b) == []
    F.cache_clear()


def test_the_memo_plan_matches_what_the_producer_actually_runs():
    """The plan hashed into the key must equal the transforms the row runs, or two different states
    would key the same way -- immortally, on a historical as-of."""
    rows = _oni_rows()
    conv = {"kind": "abs_bands", "bands": [0.5, 1.0], "labels": ["elevated", "moderate"],
            "verified": None}
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120},
                       conventions={"oni_climate": conv}, silver_status="available")
    plan = F._transform_plan("monthly", 120, False, conv)
    ran = [{"transform": d["transform"], "params": d["params"]} for d in r.derivation]
    # the plan enumerates BOTH streak directions because the producer may stop after the first that
    # fires; every other entry must appear exactly as planned, in order
    planned = [p for p in plan if not (p["transform"] == "streak" and p not in ran)]
    assert planned == ran, f"plan {planned} != ran {ran}"


def test_the_cache_is_OFF_unless_its_own_flag_is_armed(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_STATE_CACHE", raising=False)
    F.cache_clear()
    F.cache_put(("x",), {"v": 1}, "2020-01-01")
    assert F.cache_get(("x",)) is None and F._SHARED == {}


# ── the TEXT feeder (sec 2.2) ────────────────────────────────────────────────────────────────────────
def test_receipts_rank_by_specificity_and_recency_with_the_named_bonus():
    recs = [
        {"date": "2019-01-05", "source": "old", "text": "El Nino conditions dried Argentine soybeans"},
        {"date": "2026-08-20", "source": "new", "text": "a routine market note about shipping"},
        {"date": "2026-07-01", "source": "both", "text": "El Nino dried Argentine soybean yields sharply"},
    ]
    ts = F.text_state(_Node("soybeans_cbot", "El_Nino", "oni_climate", evidence=recs),
                      asof="2026-09-08", evidence_query="El Nino Argentine soybean yields")
    assert ts.n == 3 and ts.status == "ok"
    assert ts.newest_date == "2026-08-20" and ts.oldest_date == "2019-01-05"
    assert ts.top[0].source == "both", "specific AND recent outranks each half alone"
    assert ts.top[0].named is True
    assert all(0.0 <= r.rank <= 1.0 for r in ts.top)
    assert ts.top[0].rank > ts.top[1].rank >= ts.top[2].rank


def test_the_weights_are_constants_and_the_horizon_flattens_old_receipts():
    assert (F.SPECIFICITY_WEIGHT, F.RECENCY_WEIGHT) == (0.6, 0.4)
    assert F.RECENCY_HORIZON_DAYS == 730 and F.NAMED_BONUS == 0.25
    a = F.rank_receipt({"date": "2016-01-01", "text": "x"}, evidence_query="x", node_id="n",
                       asof="2026-09-08")
    b = F.rank_receipt({"date": "2021-01-01", "text": "x"}, evidence_query="x", node_id="n",
                       asof="2026-09-08")
    assert a.recency == b.recency == 0.0                      # both past the horizon: separated by WHAT
    #                                                           they say, never by which is less ancient


def test_a_node_with_zero_receipts_is_a_ROW_that_says_so_and_the_TWO_absences_are_different():
    """The rank never decides whether a node is on the board -- every node is -- and never gates a
    mechanism on a receipt COUNT. One mechanism-narrating receipt is enough.

    THE TWO ABSENCES ARE DIFFERENT FACTS AND BOTH WORDS ARE REACHABLE. ``no_receipts`` is the stronger
    claim -- a fill RAN and the corpus had nothing -- and only the caller knows whether it ran:
    ``ground()`` fills the 5-slice cap of ``_active_drivers`` and ``GroundedNode.evidence`` defaults to
    ``[]``, so an empty list alone cannot tell "looked and found none" from "never looked". The first S1
    cut tested ``if recs is None`` after a ``or []`` that can never be None, so ``no_receipt_fetched`` was
    advertised on the dataclass and unreachable in the code."""
    unfetched = F.text_state(_Node("soybeans_cbot", "El_Nino", "oni_climate"), asof="2026-09-08")
    assert unfetched.n == 0 and unfetched.status == "no_receipt_fetched" and unfetched.top == []
    assert unfetched.summary() == {"n": 0, "newest_date": None, "oldest_date": None, "top": [],
                                   "status": "no_receipt_fetched"}
    looked = F.text_state(_Node("soybeans_cbot", "El_Nino", "oni_climate"), asof="2026-09-08",
                          fetched=True)
    assert looked.status == "no_receipts", "a fill that ran and found nothing is a different fact"


def test_the_text_feeder_performs_NO_retrieval():
    """ZERO new retrieval in phase 1b, and it is a costed decision: under ``EVIDENCE_BACKEND=pg``,
    ``evidence.retrieve`` embeds the query and borrows the EVIDENCE pool -- the pool that owns the ~2 s
    warm fill every turn depends on."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(F))
    # the AST, not the text: the module's own docstring EXPLAINS the retrieval it does not perform, and
    # a substring check would grade the explanation instead of the code
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    called |= {n.func.id for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "retrieve" not in called and "pg_retrieve" not in called
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            imported |= {f"{n.module}.{a.name}" for a in n.names}
        elif isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
    assert not any(m.endswith(("evidence", "pgstore")) for m in imported), sorted(imported)


# -- the review's remaining findings, each with the pin it asked for -----------------------------------
def test_an_undeclared_cross_section_is_read_empty_WITH_ITS_REASON_not_a_word_of_its_own():
    """Design sec 2.6 step 5 in the design's own words: ``_pace_series`` returning ``([], None)`` is
    ``status: read_empty`` with reason ``undeclared_cross_section``. The word the render owes a sentence
    for is ``read_empty``; the cross-section is the DETAIL after the colon.

    The decline itself is the measured one: the ESR fixture that narrated '+565 1000 MT from the prior
    week' against a true weekly change of -45 -- direction inverted, on a real minted [N] row."""
    from leviathan.graphrag.state.rows import STATUS_WITH_DETAIL, status_word
    rows = [{"value": "10", "data_date": "2026-08-28", "country": "China"},
            {"value": "20", "data_date": "2026-08-28", "country": "Japan"},
            {"value": "12", "data_date": "2026-09-04", "country": "China"},
            {"value": "22", "data_date": "2026-09-04", "country": "Japan"}]
    r = F.series_state("cot_mm_positioning", _Node("corn_cbot", "spec_positioning",
                                                  "cot_mm_positioning"), "2026-09-08",
                       qfn=F.fixture_query_fn({"silver_cot": rows}), silver_status="available")
    if r.status.startswith("scope_unresolved"):
        pytest.skip("the positioning row's scope does not resolve in this tree")
    assert r.status == "read_empty:undeclared_cross_section"
    assert status_word(r.status) == "read_empty" and "read_empty" in STATUS_WITH_DETAIL


def test_positionings_series_half_declines_outlook_lane_BY_NAME_at_zero_reads():
    """R9's shipped drop, in the board's own vocabulary (cascade.py skips a POSITIONING_TABLES row on an
    outlook turn). The word was in the closed enum and assigned NOWHERE, so the render owed a sentence
    for a state nothing could produce. The turn kind is the WALK's knowledge and is PASSED IN: a caller
    that does not know it cannot silently assert a lane."""
    def _never(sql):
        raise AssertionError("an outlook-lane decline must cost ZERO reads")
    r = F.series_state("cot_mm_positioning", _Node("corn_cbot", "spec_positioning",
                                                  "cot_mm_positioning"), "2026-09-08",
                       qfn=_never, silver_status="available", turn_kind="outlook")
    assert r.status == "outlook_lane" and r.status in STATUS_WORDS
    assert r.reads == 0 and r.context_only is True


def test_the_row_carries_the_cards_own_first_obs_and_an_age_in_the_cadences_PERIODS():
    """Sec 1.2's schema, both fields, and neither is bookkeeping. ``first_obs`` is what the CARD holds
    and ``history_start`` is what THIS read fetched -- the gap between them is the history the row did
    not rank against (silver_fred_fx: a 2004 first_obs under a five-year fetched window). ``age_periods``
    is the sentence a monthly card's reader needs: "two months stale", not "76 days"."""
    rows = _oni_rows()
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=_pit_qfn(rows, "2026-09-08"), windows={"monthly": 120},
                       silver_status="available")
    ts = load_registry().get("silver_noaa_oni")
    assert r.coverage["first_obs"] == ts.first_obs
    assert r.coverage["history_start"] != r.coverage["first_obs"] or ts.first_obs is None
    assert r.recency["age_periods"] is not None
    assert r.recency["age_periods"] == int(r.recency["age_days"] // F.CADENCE_DAYS["monthly"])


def test_a_year_month_card_with_NO_declared_lag_still_admits_the_CURRENT_month_from_day_one():
    """A TRIPWIRE, not a passing grade. ``ym_lag=True`` is the IDENTITY on a card that declares no
    ``ym_publication_lag_days`` ("undeclared means NO SHIFT and a consumer that says so"), so such a card
    admits its data month from the month's FIRST DAY and ``derive_knowledge_date`` returns a month-end
    LATER than the as-of. The PIT pin above covers ONE card (``oni_climate``), which declares 36 days, so
    it would not catch the day one of these lands on a board.

    MEASURED at this landing: the two no-lag ``year_month`` cards are ``silver_mpoc_stock_comparison``
    and ``silver_mpoc_trade_stats_monthly``, and NEITHER carries a ``cascade_map`` ref the board can
    read. When one does, this reds and the lag becomes a decision rather than a discovery."""
    reg = load_registry()
    no_lag = {i for i, ts in reg.tables.items()
              if ts.knowledge_semantics == "year_month" and not ts.ym_publication_lag_days}
    assert no_lag, "the premise: cards may declare year_month semantics with no publication lag"
    # the leak itself, on the card class rather than on a live board row
    for tid in sorted(no_lag):
        kd, basis = F.derive_knowledge_date(reg.tables[tid], {"year": 2026, "month": 9})
        assert kd == "2026-09-30" and kd > "2026-09-08", basis
        assert "no publication lag declared" in basis, "the row must SAY the derivation was unlagged"
    board_tables = {(r or {}).get("table") for r in F.board_map().values()}
    assert not (no_lag & board_tables), (
        "a no-lag year_month card reached a board ref: decide its ym_publication_lag_days, or the "
        f"board's reads admit the current month from its first day -- {sorted(no_lag & board_tables)}")


def test_ONE_SERIES_KEY_IS_ONE_READ_over_the_WHOLE_estate_from_the_configs_alone():
    """THE CLAIM THE WAVE PRICER IS BUILT ON, and the review was right that it did not hold as stated:
    the memo counts DISTINCT SERIES KEYS and calls that the read count, so a key that could resolve to
    two different physical reads would price a wave short and -- worse -- serve one metric's array under
    the other's name. Before the fold fix it did: ``oni_lag_climate`` and ``oni_climate`` folded onto ONE
    key while compiling ``oni_lag6`` and ``oni_anom``.

    This walks every (contract, driver) instance in the 33 curated DAGs, resolves each scope with the
    SHIPPED resolver and asks what key and what read ``series_state`` would build -- from the configs
    alone, at zero reads and zero dollars -- and asserts the map is one-to-one.

    MEASURED at this landing: 1,267 instances / 24 with no ``silver_ref`` / 795 on the board's own map /
    550 resolve / 245 ``scope_unresolved`` (190 ``region-token-unresolved``, 17 ``cot-unserved-slug``,
    13 ``global-token-fenced``, 11 ``fx-no-currency``, 8 ``psd-unserved-slug``, 6
    ``no-geography-primary``) -> 284 distinct series keys and 284 distinct reads."""
    import collections

    from leviathan.graphrag.graph import CausalGraph
    from leviathan.graphrag.numbers import cascade as casc
    reg = load_registry()
    bmap = F.board_map()
    by_key = collections.defaultdict(set)
    resolved = 0
    for contract, cc in CausalGraph.load().contracts.items():
        for d in cc.drivers:
            ref = (getattr(d, "silver_ref", "") or "").strip()
            row = bmap.get(ref)
            if not ref or row is None:
                continue
            node = _Node(contract, d.id, ref, region=getattr(d, "region", None))
            commodity, country, _skip = casc._scope_ex(node, row)
            if country is casc.SKIP_NODE:
                continue
            row2 = casc._region_row(node, row)
            table = row2.get("table", "")
            if table not in reg.tables:
                continue
            ts = reg.tables[table]
            fold = F._resolve_same_series(ref, row, row2, node, casc)
            metric = fold.read_row.get("metric", "")
            c, k, m = F._scope_for_card(ts, commodity, country,
                                        declared_metric=str(fold.src_row.get("metric") or ""),
                                        resolved_metric=metric,
                                        country_rule=str(fold.src_row.get("country_rule") or ""))
            resolved += 1
            by_key[(fold.base_ref, c, k, m)].add(
                (table, metric, c if ts.commodity_col else "", k if ts.country_col else ""))
    assert resolved > 500, f"the estate collapsed to {resolved} resolving instances -- check the DAG load"
    ambiguous = {key: reads for key, reads in by_key.items() if len(reads) != 1}
    assert not ambiguous, (
        "a series key that resolves to more than one physical read prices the wave wrong AND can serve "
        f"one metric's array under another's name: {sorted(ambiguous)[:3]}")


def test_an_ALL_BLANK_frame_is_an_empty_read_and_NOT_a_cross_section_defect():
    """``citations.is_empty_read``'s own rule (:338): "zero rows OR rows that are all blank". Without
    this the all-blank frame reached ``_pace_series``, which hands back ``([], None)``, and the row
    declined ``undeclared_cross_section`` -- naming a cross-section defect for a frame that simply
    carried no numbers. The read is still COUNTED: the ledger sees what it spent."""
    rows = [{"value": "", "year": 2026, "month": m} for m in range(1, 9)]
    r = F.series_state("oni_climate", _Node("soybeans_cbot", "El_Nino", "oni_climate"), "2026-09-08",
                       qfn=F.fixture_query_fn({"silver_noaa_oni": rows}), windows={"monthly": 120},
                       silver_status="available")
    assert r.status == "read_empty:all_blank" and r.reads == 1 and r.level is None
