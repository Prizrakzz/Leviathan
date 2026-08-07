"""D-CW (CAPABILITY WIRING WAVE) -- the advertisement tier + the new numbers card.

Born from docs/private/DARK_CAPABILITY_CENSUS.md (2026-08-07): three separate capability-ADVERTISEMENT
surfaces each described a strict subset of what the estate already serves, and the gaps did not overlap --
a capability could be dark to the ROUTER (dispatch purpose string: 8 of 19 tables), dark to the USER
(server._SUGGEST_METRICS: 7 fundamentals, zero prices) and dark to the MODEL (numbers tool schema: 11 of
12 NumberQuery fields) independently. Nothing here ingests, re-chunks or re-derives anything; every test
asserts that something already served is now REACHABLE.

The load-bearing test in this file is `test_every_visible_numbers_table_is_advertised_to_the_router`: it
is a COVERAGE property over the live registry, not a list of strings, so the next card that lands without
a purpose clause fails HERE rather than being discovered by a census a year later. AWS-free.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag import config_check as cc
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag.numbers import agent as na
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as nreg

NASS = "silver_nass_crop_progress"


def _purpose() -> str:
    return next(t.purpose for t in dp.REGISTRY if t.name == "numbers").lower()


def _reg():
    return nreg.load_registry()


# ====================================================================================================
# D-CW-1a -- the ROUTER purpose string (dispatch.REGISTRY, the ONLY place the planner learns what the
# numbers agent can do). Census rank order: fertilizer/energy + z-scores, WASDE + farm price with vintage
# stamps, ESR destinations, grindings/palm/CONAB/SAGIS, IOD beside ONI, front month LEVELS-ONLY.
# ====================================================================================================
# One DISTINCTIVE token per served table -- the thing a router would have to see to route that table's
# question. Alternatives inside a tuple are OR'd (any one of them advertises the table).
_ADVERTISED = {
    "silver_psd": ("psd",),
    "silver_wasde": ("wasde", "farm price"),
    "silver_production": ("faostat",),
    "silver_nasa_power": ("weather aggregates",),
    "silver_esr": ("export sales",),
    "silver_fred_fx": ("fx",),
    "silver_noaa_oni": ("oni",),
    "silver_noaa_iod": ("indian ocean dipole", "iod"),
    "gold_weather_z": ("z-anomalies",),
    "silver_icco_cocoa": ("grindings",),
    "silver_mpob": ("mpob", "palm"),
    "silver_mpoc_stock_comparison": ("mpoc",),          # D-PQ tranche 1a: importer-country vegoil stocks
    "silver_sagis_cec": ("sagis",),
    "silver_conab_coffee": ("conab",),
    "silver_sagis_weekly_exports": ("sagis",),
    "silver_pink_sheet": ("urea", "input costs"),
    "silver_cot": ("positioning",),
    "silver_futures_prices": ("front-month",),
    "silver_futures_eod": ("term structure", "curve"),
    NASS: ("nass",),
}


def test_every_visible_numbers_table_is_advertised_to_the_router(monkeypatch):
    """THE CENSUS PROPERTY, as a build fence. Every table the agent can actually see must be findable in
    the router's purpose string, because that string is the only capability advertisement the planner ever
    reads -- a served table it does not name is a table the router keeps routing away from forever.

    gold_pattern_records is excluded by forcing its kill-switch OFF: the ledger card's own flag gates its
    advertisement too, and pinning a static string against a flag-gated card would fail on flag state
    rather than on wiring."""
    monkeypatch.setenv("GRAPHRAG_PATTERN_RECORDS", "off")
    purpose = _purpose()
    visible = nreg.visible_tables(_reg())
    unmapped = [t for t in visible if t not in _ADVERTISED]
    assert not unmapped, (f"{unmapped} is served but this coverage map has no entry -- add the purpose "
                          f"clause AND the entry together (D-CW-1a), or the table is dark to the router")
    dark = [t for t in visible if not any(tok in purpose for tok in _ADVERTISED[t])]
    assert not dark, f"served but UNADVERTISED to the router: {dark}"


@pytest.mark.parametrize("token", [
    # (1) fertilizer + energy input costs and their z-scores -- 32 pink_sheet metrics, all dark before.
    "urea", "dap", "potash", "phosphate rock", "npk", "natural gas", "brent", "5-year z-score",
    # (2) WASDE + the US season-average farm price, WITH the vintage stamp discipline.
    "farm price", "vintage", "projection",
    # (3) ESR per-destination buyers.
    "by destination",
    # (4) grindings / palm / CONAB / SAGIS.
    "grindings", "palm", "conab", "sagis",
    # (5) IOD beside ONI.
    "indian ocean dipole",
    # D-CW-2c: the card that landed with this wave.
    "conditions", "harvest",
])
def test_purpose_names_each_census_unlock(token):
    assert token in _purpose(), f"router purpose string omits {token!r} (D-CW-1a census rank order)"


def test_purpose_carries_the_levels_only_fence_in_its_wording():
    """The R4 / levels_only rule is a WORDING rule here: advertising the continuous front-month series
    without its caveat would manufacture declines -- build_sql RAISES on any change/window/curve read of a
    roll-spliced series, so a purpose that promised one would route asks straight into a refusal."""
    p = _purpose()
    assert "front-month" in p and "roll-spliced" in p
    assert "level" in p and "no change, window or curve" in p


def test_purpose_keeps_the_futures_eod_reachability_trio_green():
    """config_check.check_futures_eod pins 'term structure' AND 'curve' in this exact string (W3.1 item 8).
    The D-CW rewrite is ADDITIVE and must not disturb it -- asserted through the real lint, not a copy."""
    assert cc.check_futures_eod() == []
    assert "term structure" in _purpose() and "curve" in _purpose()


def test_when_to_use_names_the_new_routing_cues():
    w = next(t.when_to_use for t in dp.REGISTRY if t.name == "numbers").lower()
    for token in ("input cost", "condition", "which country bought"):
        assert token in w, token


# ====================================================================================================
# D-CW-1b -- the USER-facing suggester catalog (server._SUGGEST_METRICS).
# ====================================================================================================
def _catalog() -> str:
    from leviathan.graphrag import server
    return server._SUGGEST_METRICS.lower()


@pytest.mark.parametrize("token", [
    "farm price", "urea", "natural gas", "brent", "z-score",   # prices + input costs (were 100% dark)
    "curve",                                                    # the per-expiry / term-structure read
    "destination",                                              # ESR buyers
    "conditions",                                               # the NASS card
])
def test_suggester_catalog_advertises_the_price_half(token):
    assert token in _catalog(), f"suggester catalog omits {token!r} (D-CW-1b)"


def test_suggester_catalog_stays_inside_the_ratified_positioning_fence():
    """D-CW-1b asked for positioning suggestions; config_check R10 (check_cot_register, PRICE_OBSERVABILITY
    W0.2 as amended by D1) FORBIDS positioning vocabulary in this string -- positioning is a driver LANE,
    never a suggestible numbers source. This wave changes no ratified fence, so the clause was dropped and
    the omission is pinned HERE as a decision. The router still advertises COT positioning (see
    _ADVERTISED above), which is the reachable half of the census's item 9."""
    low = _catalog()
    for tok in ("managed money", "managed-money", "net long", "net short", "positioning", "open interest"):
        assert tok not in low, f"{tok!r} in _SUGGEST_METRICS would fail config_check R10"
    assert cc.check_cot_register() == []


def test_suggester_catalog_names_no_dark_table():
    """Census-gated like the gallery vocab: every subject advertised to the user must be reachable. The
    inverse of the router property -- here the risk is suggesting a question we cannot answer."""
    low = _catalog()
    visible = set(nreg.visible_tables(_reg()))
    # each catalog subject -> the table that answers it
    for subject, table in (("urea", "silver_pink_sheet"), ("brent", "silver_pink_sheet"),
                           ("farm price", "silver_wasde"), ("curve", "silver_futures_eod"),
                           ("conditions", NASS), ("esr", "silver_esr")):
        if subject in low:
            assert table in visible, f"catalog advertises {subject!r} but {table} is not served"


# ====================================================================================================
# D-CW-1c -- NumberQuery.limit, declared in the model-facing tool schema (the oldest-5000 class).
# ====================================================================================================
def _props() -> dict:
    return na.tool_schema(_reg())["input_schema"]["properties"]


def test_limit_is_declared_in_the_tool_schema():
    """The model can only emit parameters the schema NAMES -- while `limit` was absent, EVERY series read
    ran at the default cap with no way to say otherwise (census line: 11 of 12 NumberQuery fields)."""
    assert "limit" in _props()
    assert set(_props()) - {"asof"} <= set(Q.NumberQuery.model_fields), "schema declares a non-field"
    # asof is DELIBERATELY absent (the harness forces it) -- the one field that must never be model-set.
    assert "asof" not in _props()


@pytest.mark.parametrize("token", ["newest", "period_start", "truncated", "5000"])
def test_limit_description_carries_the_newest_first_windowing_note(token):
    assert token in str(_props()["limit"]["description"]).lower(), token


def test_limit_schema_bounds_match_the_field_default():
    lim = _props()["limit"]
    assert lim["default"] == Q.NumberQuery.model_fields["limit"].default == na.LIMIT_CEILING
    assert lim["maximum"] == na.LIMIT_CEILING and lim["minimum"] == 1


@pytest.mark.parametrize("raw,want", [
    (10, 10), (1, 1), (5000, 5000),
    (5001, 5000), (10 ** 9, 5000),        # NEVER upward: the cap bounds the scan surface
    (0, 5000), (-3, 5000),                 # nonsense collapses to the default, never to an empty read
    ("40", 40), ("abc", 5000), (None, 5000), (12.7, 12),
])
def test_forced_spec_clamps_a_model_supplied_limit(raw, want):
    spec = na._forced_spec("2026-06-01", {"table": "silver_psd", "metric": "production_mt", "limit": raw})
    assert spec.limit == want
    assert spec.asof == "2026-06-01"                       # the forced-asof contract is untouched


def test_forced_spec_without_limit_keeps_the_default():
    spec = na._forced_spec("2026-06-01", {"table": "silver_psd", "metric": "production_mt"})
    assert spec.limit == na.LIMIT_CEILING


def test_a_clamped_limit_reaches_the_compiled_sql():
    spec = na._forced_spec("2026-06-01", {"table": "silver_cot", "metric": "mm_net", "agg": "series",
                                          "commodity": "corn_cbot", "limit": 25})
    assert Q.build_sql(spec).endswith("LIMIT 25")


# ====================================================================================================
# D-CW-1e -- entity vocabulary: the cost-stack + macro-context nodes (config-only).
# ====================================================================================================
def _vocab() -> dict:
    import yaml
    from leviathan.graphrag import extract as ex
    return yaml.safe_load((ex._CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("ntype,members", [
    ("fertilizer", {"urea", "DAP", "potash", "phosphate_rock", "NPK_blend"}),
    ("energy", {"crude_oil", "natural_gas", "diesel"}),
    ("freight", {"baltic_dry_index", "panamax_freight"}),
    ("logistics_chokepoint", {"panama_canal", "suez_canal"}),
    ("metal", {"copper", "aluminium", "iron_ore", "zinc", "nickel", "steel"}),
])
def test_cost_stack_node_types_exist_with_their_members(ntype, members):
    nodes = _vocab()["nodes"]
    assert ntype in nodes, f"{ntype} node type missing (D-CW-1e)"
    assert members <= set(nodes[ntype] or []), sorted(members - set(nodes[ntype] or []))


def test_vocab_lint_stays_green_with_the_new_nodes():
    """The lint is STRUCTURAL: no term is both a node and an edge, every alias resolves to a real canonical
    node, and no alias surface form is itself a node term (the two-identities collision)."""
    assert cc.lint_vocab() == []


def test_cost_stack_nodes_are_non_tradeable_by_construction():
    """A context node must have NO entry in commodity_hierarchy.contracts -- that is what makes it a real
    edge endpoint that can never become a cascade root (the sunflower_oil/barley precedent)."""
    import yaml
    from leviathan.graphrag import extract as ex
    h = yaml.safe_load((ex._CFG / "commodity_hierarchy.yaml").read_text(encoding="utf-8"))
    mapped = {spec["node"] for spec in (h.get("contracts") or {}).values()}
    nodes = _vocab()["nodes"]
    new = set().union(*(set(nodes[t] or []) for t in
                        ("fertilizer", "energy", "freight", "logistics_chokepoint", "metal")))
    assert not (new & mapped), sorted(new & mapped)


def test_new_aliases_point_at_the_new_nodes():
    v = _vocab()
    aliases = v.get("aliases") or {}
    for canon, form in (("urea", "granular urea"), ("DAP", "diammonium phosphate"),
                        ("potash", "muriate of potash"), ("crude_oil", "Brent"),
                        ("natural_gas", "natural gas"), ("diesel", "gasoil"),
                        ("baltic_dry_index", "baltic dry index"), ("suez_canal", "red sea"),
                        ("aluminium", "aluminum")):
        assert form in (aliases.get(canon) or []), f"{canon} is missing the alias {form!r}"


# ====================================================================================================
# D-CW-2a -- the silver_nass_crop_progress card (census item 6: a SHIPPED eval already graded its
# citation key while the registry had no card for it).
# ====================================================================================================
def _nass():
    return _reg().get(NASS)


def test_nass_card_is_served_and_in_the_tool_enum():
    assert NASS in nreg.visible_tables(_reg())
    assert NASS in _props()["table"]["enum"]


def test_nass_card_pit_shape():
    """data_date on the WEEK-ENDING date + a conservative 2-day publication lag: NASS publishes the week
    ending Sunday on the FOLLOWING Monday ~16:00 ET, so a same-day cutoff would leak by hours and a
    Monday-holiday slip lands on Tuesday."""
    ts = _nass()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == ("data_date", "date", "date")
    assert ts.publication_lag_days == 2
    assert ts.shape == "wide" and ts.commodity_col == "commodity" and ts.country_col == "state"
    assert ts.partition_cols == ["commodity", "year"] and ts.year_col == "year"
    assert set(ts.metrics) == {"pct_good_excellent", "pct_poor_very_poor", "pct_planted",
                               "pct_emerged", "pct_harvested"}
    assert not ts.levels_only and not ts.quarantined


def test_nass_card_notes_state_the_pit_and_scope_traps():
    ts = _nass()
    blob = (ts.description + " " + ts.notes).lower()
    for token in ("week-ending", "'us'", "cumulative", "six"):
        assert token in blob, token
    # staleness honesty: the recency stamp does the talking, never a 'current' claim
    assert "never call a dated reading 'current'" in blob


def test_nass_sql_prunes_the_projection_and_guards_the_as_of():
    """The table is partition-PROJECTED (commodity enum x year 1979-2035). The commodity equality plus the
    sargable year bounds are what keep Athena from enumerating that grid -- the Jul-2026 LIST-storm class,
    three orders of magnitude smaller here but pruned the same way."""
    spec = Q.NumberQuery(table=NASS, metric="pct_good_excellent", asof="2026-06-15",
                         commodity="corn_cbot", country="US")
    sql = Q.build_sql(spec)
    assert "commodity = 'corn_cbot'" in sql                      # the projected commodity axis, pinned
    assert "year <= 2026" in sql                                 # sargable bound, never an equality
    assert "state = 'US'" in sql                                 # the geo axis
    assert "CAST(date AS varchar) <= '2026-06-13'" in sql        # week-ending + 2d publication lag
    assert "ORDER BY date DESC" in sql and sql.endswith("LIMIT 1")


def test_nass_window_read_carries_both_year_bounds():
    spec = Q.NumberQuery(table=NASS, metric="pct_planted", asof="2026-06-15", commodity="corn_cbot",
                         country="IA", agg="series", period_start="2025-04-01", period_end="2026-06-15")
    sql = Q.build_sql(spec)
    assert "year >= 2025" in sql and "year <= 2026" in sql
    assert "CAST(date AS varchar) >= '2025-04-01'" in sql


def test_nass_oracle_agrees_with_the_guard(monkeypatch):
    """apply_pit_filter is the pure-Python twin of the SQL guard: the +2d lag must withhold the week that
    is stamped but not yet published, on BOTH sides."""
    ts = _nass()
    rows = [
        {"commodity": "corn_cbot", "state": "US", "date": "2026-06-07", "year": 2026,
         "pct_good_excellent": 71.0},
        {"commodity": "corn_cbot", "state": "US", "date": "2026-06-14", "year": 2026,     # +2d -> not yet
         "pct_good_excellent": 73.0},                                                      # citable at 06-15
        {"commodity": "corn_cbot", "state": "IA", "date": "2026-06-07", "year": 2026,     # wrong state
         "pct_good_excellent": 80.0},
        {"commodity": "soybeans_cbot", "state": "US", "date": "2026-06-07", "year": 2026,  # wrong commodity
         "pct_good_excellent": 68.0},
    ]
    spec = Q.NumberQuery(table=NASS, metric="pct_good_excellent", asof="2026-06-15",
                         commodity="corn_cbot", country="US")
    kept = Q.apply_pit_filter(rows, spec, ts)
    assert [r["pct_good_excellent"] for r in kept] == [71.0]
    # ...and the freshest week becomes citable two days later, exactly as the SQL cutoff moves.
    later = Q.NumberQuery(table=NASS, metric="pct_good_excellent", asof="2026-06-16",
                          commodity="corn_cbot", country="US")
    assert sorted(r["pct_good_excellent"] for r in Q.apply_pit_filter(rows, later, ts)) == [71.0, 73.0]


def test_nass_card_reconciles_against_the_f010_registry():
    """Landing a card is never a one-file edit: reconcile_numbers binds the card's PIT fields to the silver
    registry contract and requires the numbers_ref back-pointer, and the drift test requires NUMBERS_TABLES
    to enumerate every tables.yaml id (an unenumerated table is STRUCTURALLY UNCHECKED)."""
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert NASS in RC.NUMBERS_TABLES
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == NASS] == []
    c = reg.table(NASS)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert (c["knowledge_date_col"], c["knowledge_semantics"], c["publication_lag_days"]) == \
           ("date", "data_date", 2)


def test_nass_is_in_the_pg_mirror_list():
    """A SERVED numbers table must be MIRRORED: unmirrored + GRAPHRAG_NUMBERS_BACKEND=pg raises
    UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA -- here onto a partition-PROJECTED table."""
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert NASS in P1_TABLES


def test_nass_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ====================================================================================================
# D-CW-4 / D-PQ RE-RUN CORRECTIONS (2026-08-07) -- three cues the WIRED-v2 probe proved were missing.
# Each one is prompt-side and none of them is verifiable offline, so what these tests pin is that the
# cue is PRESENT AT THE SEAM THAT BINDS -- which is the half the first attempt got wrong.
# ====================================================================================================
class TestNassCardTeachesTheShapeItsOwnAxes_Invite:
    """`dcw_nass_conditions_split`: EIGHT of sixteen lookups on one turn failed with `metric` omitted,
    and a US winter-wheat condition (27.0 pct good/excellent) was read on a turn routed to
    french_wheat_matif. Five metrics plus a free state axis is the shape that invites a metric-less
    state sweep, and a US-only card with no geography sentence is the shape that invites a US number
    being narrated as a French crop. The card is the only place the model reads before choosing."""

    def _notes(self) -> str:
        return " ".join(str(cc._load("numbers/tables.yaml")["tables"][NASS]["notes"]).split()).lower()

    def test_the_card_states_the_one_metric_per_call_rule(self):
        n = self._notes()
        assert "one lookup = one metric" in n
        assert "one call per" in n and "(metric, state)" in n     # the east-vs-west comparison, spelled out
        assert "rejected before anything is queried" in n         # and what a metric-less call COSTS

    def test_the_card_states_that_it_is_the_united_states_and_nothing_else(self):
        n = self._notes()
        assert "united states and nothing else" in n
        assert "matif" in n                                       # the measured cross-contract read, named
        assert "not a proxy" in n or "not proxies" in n

    def test_the_five_metrics_the_refusal_offers_are_the_five_the_card_serves(self):
        # the refusal text (agent._spec_error) lists the card's metrics; a drift between the two would
        # hand the model a name that does not exist, which is worse than the bare pydantic dump was.
        served = set(_reg().get(NASS).metrics)
        err = na._spec_error({"table": NASS}, ValueError("x"), _reg())
        assert served and all(m in err for m in served)


class TestMarginCueLandsOnTheLaneThatActuallyRuns:
    """R1 (`dcw_us_ethanol_margin`): SIX lookups before the wiring wave, ZERO in both wired arms.

    D-PQ FIX-2's first remedy put the margin cue in `dispatch.ToolSpec.when_to_use`. THE RE-RUN
    FALSIFIED THAT HYPOTHESIS STRUCTURALLY, not statistically: the row routed HYBRID in both arms, and
    `run_hybrid` calls `answer_numbers` UNCONDITIONALLY -- so no wording in the router's registry block
    could have caused the loss or can cure it. The cue therefore has to exist in the NUMBERS AGENT's own
    system prompt, where it does not depend on the planner having spoken. The planner-side rule stays as
    the second belt (it drives the B1 ROUTING HINT, which is the mechanism the new hypothesis blames)."""

    def test_the_numbers_agent_itself_is_told_a_margin_is_a_multi_table_lookup(self):
        sp = na.system_prompt(_reg())
        assert "MARGIN, CRUSH, GRIND or PROCESSING-ECONOMICS" in sp
        for leg in ("silver_pink_sheet", "silver_wasde", "silver_futures_eod"):
            assert leg in sp
        assert "front_expiry" in sp                       # the output-price leg is REACHABLE by name
        assert "no margin metric and no margin table" in sp   # so it states legs, never a computed level

    def test_the_hybrid_lane_runs_the_numbers_agent_whatever_the_router_said(self):
        # the falsifier itself, pinned: if this ever stops being true the hypothesis above must be re-argued.
        import inspect
        from leviathan.graphrag import orchestrator as ORCH
        src = inspect.getsource(ORCH.run_hybrid)
        assert "na.answer_numbers(" in src and "pool.submit(_numbers)" in src

    def test_the_planner_is_told_a_margin_implicates_several_families_not_one(self):
        sysp = dp.PLANNER_SYS
        assert "PROCESSING MARGIN, CRUSH or GRIND" in sysp
        assert "pink_sheet" in sysp and "wasde" in sysp and "futures_eod" in sysp
        assert "never one" in sysp

    def test_the_when_to_use_cue_from_the_first_attempt_is_kept_not_replaced(self):
        # It was not WRONG, it was insufficient -- and it is the only thing steering a numbers_only route,
        # where the router's verdict really is the whole decision.
        w = next(t for t in dp.REGISTRY if t.name == "numbers").when_to_use.lower()
        assert "margin" in w and "crush" in w


class TestTruncatedReadsMayNotWearASuperlative:
    """Row 11 (`dcw_full_record_range`): the engine stamped a 5000-row cap correctly, `format_provenance`
    and the eval report both rendered it, and the answer still opened "the full-history trading range on
    record" with no date span. The stamp never reached the synthesis prompt, which is built from the [N]
    labels -- so the render half is pinned in test_citations.py and the RULE is pinned here."""

    def test_the_agent_prompt_forbids_the_superlative_and_names_the_remedy(self):
        sp = na.system_prompt(_reg())
        assert "NOT the complete history" in sp
        assert "state the covered span" in sp
        for banned in ("full history", "all-time", "on record"):
            assert banned in sp
        assert "WINDOWED (period_start / period_end)" in sp    # the remedy is windowing, never a bigger cap

    def test_the_limit_knob_still_says_the_cap_is_not_a_cost_lever(self):
        # D-PQ FIX-1/FIX-2 wording that the new bullet must not contradict.
        d = na.tool_schema(_reg())["input_schema"]["properties"]["limit"]["description"]
        assert "never describe a truncated read as the complete record" in d
        assert "not a cost lever" in d
