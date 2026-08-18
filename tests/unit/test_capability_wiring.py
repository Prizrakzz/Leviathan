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

# D-LD TRACK 1 (2026-08-18) -- the six LIGHT-THE-DARK cards. Each id is a module constant so the blocks
# below read the same way the NASS block does, and so a rename is a one-line edit.
FGIS = "silver_fgis"
WAP = "silver_wap_table01_revisions"
FNC_MONTHLY = "silver_fnc_colombia_monthly"
FNC_PORT = "silver_fnc_colombia_exports_port_type"
CITRUS = "silver_nass_citrus"
MPOC_TRADE = "silver_mpoc_trade_stats_monthly"


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
    # RETAINED BUT NO LONGER EXERCISED (D-LD Track 2 #5, 2026-08-18): silver_nasa_power is
    # `quarantined: true` and `visible_tables` now strips it, so it never reaches the loop below. The
    # entry stays so that un-quarantining the card restores a green coverage property in one step
    # instead of failing on a map hole that was deleted for an unrelated reason.
    "silver_nasa_power": ("weather aggregates",),
    "silver_esr": ("export sales",),
    "silver_fred_fx": ("fx",),
    "silver_noaa_oni": ("oni",),
    "silver_noaa_iod": ("indian ocean dipole", "iod"),
    "gold_weather_z": ("z-anomalies",),
    "silver_icco_cocoa": ("grindings",),
    "silver_mpob": ("mpob", "palm"),
    "silver_mpoc_stock_comparison": ("mpoc",),          # D-PQ tranche 1a: importer-country vegoil stocks
    MPOC_TRADE: ("malaysian palm export", "back to 2009"),  # D-LD: pre-2017 export depth
    "silver_sagis_cec": ("sagis",),
    "silver_conab_coffee": ("conab",),
    FNC_MONTHLY: ("fnc", "colombian monthly coffee"),   # D-LD Track 1: FNC origin print
    FNC_PORT: ("fnc", "colombian green-coffee"),        # D-LD Track 1: green coffee out by port
    "silver_sagis_weekly_exports": ("sagis",),
    "silver_pink_sheet": ("urea", "input costs"),
    "silver_cot": ("positioning",),
    "silver_futures_prices": ("front-month",),
    "silver_futures_eod": ("term structure", "curve"),
    NASS: ("nass",),
    FGIS: ("inspections", "loaded"),                    # D-LD: shipments, advertised beside ESR's sales
    WAP: ("world agricultural production", "revision ledger"),  # D-LD
    CITRUS: ("citrus",),                                # D-LD: the FCOJ-side production forecast
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


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# D-LD TRACK 2 #5 -- THE QUARANTINE STRIP (SILVER-F047).
#
# THE CONTRADICTION IT CLOSES: silver_nasa_power's own card says "QUARANTINED from serving -- weather is
# served from gold_weather_z", `check_quarantine` fails the BUILD on any engine-map reference to it, and
# yet it sat in the agent's tool enum and its system-prompt cards -- the model was invited to look up the
# one table the doctrine forbids serving from. It is also the only lit card absent from the pg mirror
# (`load_pg_numbers.P1_TABLES`, excluded for size), so each such lookup fell through to Athena on the
# PROJECTED weather prefix: the ~130-600K-LIST class that cost $134 in Jul-2026.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
_QUARANTINED = "silver_nasa_power"


def test_quarantined_cards_never_reach_the_agent_tool_enum(monkeypatch):
    """VISIBILITY, on all three surfaces the model can read: the tool enum, the system-prompt cards, and
    (through `family_names`) the planner's own family enum."""
    monkeypatch.setenv("GRAPHRAG_PATTERN_RECORDS", "off")
    reg = _reg()
    quarantined = [t for t, ts in reg.tables.items() if ts.quarantined]
    assert _QUARANTINED in quarantined, "the F047 card vanished -- re-point this pin, do not delete it"
    visible = nreg.visible_tables(reg)
    assert not [t for t in quarantined if t in visible]
    enum = na.tool_schema(reg)["input_schema"]["properties"]["table"]["enum"]
    sp = na.system_prompt(reg, stats_tool=False)
    fams = set(dp.family_names())
    for tid in quarantined:
        assert tid not in enum
        assert f"### {tid}" not in sp                       # the card block is gone, not merely the id
        assert dp._FAMILY_PREFIX.sub("", tid) not in fams   # ...and the router cannot steer at it either


def test_quarantined_cards_still_LOAD_so_direct_lookups_stay_legal():
    """THE CARVE-OUT, PINNED. Quarantine is a VISIBILITY verdict, never a LOADING one -- the kill-switch
    (`GRAPHRAG_NUMBERS_DISABLE`) is the other thing entirely and makes `build_sql` raise KeyError. The
    card must stay in `load_registry()` so `reg.get`, the compiler, the F010 reconcile back-pointer and
    the card's own lints all keep reading it; only the model's ability to NAME it was removed."""
    reg = _reg()
    assert _QUARANTINED in reg.tables                       # LOADED, not dropped
    ts = reg.get(_QUARANTINED)
    assert ts.quarantined is True and ts.metrics            # the spec is intact, metrics and all
    # A projected table needs its injected-partition equalities; supplying them is the point -- the
    # compiler is unchanged, INCLUDING the sargable bounds that make such a read safe on this prefix.
    sql = Q.build_sql(Q.NumberQuery(table=_QUARANTINED, metric=sorted(ts.metrics)[0], asof="2024-06-01",
                                    commodity="corn", country="united_states", region="iowa"), ts)
    assert _QUARANTINED in sql                              # a DIRECT, programmatic lookup still compiles
    assert "commodity = 'corn'" in sql and "year <= 2024" in sql


def test_visible_set_is_the_registry_minus_the_ledger_card_and_the_quarantine(monkeypatch):
    """ONE derivation, TWO strips, stated as arithmetic so a third strip cannot land unnoticed."""
    monkeypatch.setenv("GRAPHRAG_PATTERN_RECORDS", "off")
    reg = _reg()
    expected = sorted(t for t, ts in reg.tables.items()
                      if t != "gold_pattern_records" and not ts.quarantined)
    assert nreg.visible_tables(reg) == expected
    assert len(expected) == len(reg.tables) - 2             # 27 cards -> 25 visible today


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
    # D-LD: FGIS shipments named beside ESR sales -- the pair the router has to be able to tell apart.
    # ("by destination" is already in this list from the ESR clause and stays.)
    "inspections",
    # D-LD: the citrus forecast -- "nass" alone would have advertised it off the crop-progress clause.
    "citrus",
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
# D-LD -- the silver_fgis card. FGIS export INSPECTIONS: the physical shipments half of the US export
# program, dark to the agent since the 2026-05 backfill while silver_esr served the bookings half.
# The three properties this block exists to hold: (a) the PIT lag is the MEASURED 13, not a guess;
# (b) the projected marketing_year axis is pinned by an EQUALITY when a season is named and is NEVER
# bounded as a calendar year (the bound would be silently wrong for eight months of every year);
# (c) the notes carry the shipments-vs-sales, uppercase-destination and CTD-summation traps.
# ====================================================================================================
def _fgis():
    return _reg().get(FGIS)


def test_fgis_card_is_served_and_in_the_tool_enum():
    assert FGIS in nreg.visible_tables(_reg())
    assert FGIS in _props()["table"]["enum"]


def test_fgis_card_pit_shape():
    """data_date on the derived week-ending bucket + a MEASURED 13-day publication lag. FGIS's report week
    runs Fri->Thu and our fetch snapshots the rolling CY file every Thursday 12:00 UTC; three consecutive
    2026 snapshots each carried certifications through exactly the PREVIOUS Thursday (as_of 07-30 -> cert
    07-23, 08-06 -> 07-30, 08-13 -> 08-06). Our week_ending_date is a 7-day bucket end anchored to the
    marketing-year start, so its weekday drifts and a cert dated on a bucket end lands between +7 and +13
    days later. 13 is the worst case and the only value that never leaks."""
    ts = _fgis()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == \
           ("data_date", "week_ending_date", "week_ending_date")
    assert ts.publication_lag_days == 13
    assert ts.shape == "wide"
    assert ts.commodity_col == "leviathan_slug" and ts.country_col == "destination_country"
    assert ts.period_col == "marketing_year" and ts.period_sql_type == "int" and ts.period_offset == 0
    assert set(ts.metrics) == {"exports_mt_weekly", "exports_mt_ctd"}
    assert all(m.unit == "MT" for m in ts.metrics.values())      # whole MT -- silver_esr is 1000 MT
    assert not ts.levels_only and not ts.quarantined


def test_fgis_marketing_year_is_pinned_by_equality_and_never_bounded_as_a_calendar_year():
    """THE LOAD-BEARING STRUCTURAL PIN. silver_fgis is partition-PROJECTED (slug enum x marketing_year
    1982-2035 = 270 candidates, 223 real). The slug axis is pinned by the commodity equality. The
    marketing_year axis is pinned by the PERIOD equality when a season is named -- and it must NOT be
    declared as year_col, because _filters emits `year_col >= int(period_start[:4])` and a MARKETING year
    is not a calendar year: corn 2025/26 runs Sep 2025 to Aug 2026, so a window opening in 2026 would
    bound `marketing_year >= 2026` against rows that live in 2025 and return ZERO ROWS silently. It must
    also not appear in partition_cols, because it is not a NumberQuery field and _partition_filters would
    then raise on every single lookup."""
    ts = _fgis()
    assert ts.partition_cols == ["leviathan_slug"]
    assert ts.year_col is None and ts.month_col is None
    assert "marketing_year" not in (ts.partition_cols or [])


def test_fgis_card_notes_state_the_shipments_destination_and_ctd_traps():
    ts = _fgis()
    blob = (ts.description + " " + ts.notes).lower()
    for token in ("silver_esr", "loaded", "korea rep", "cumulative", "week ending 2026-08-02"):
        assert token in blob, token
    # the cross-table unit trap: whole MT here, thousands of MT on ESR
    assert "thousands of mt" in blob
    # staleness honesty, the NASS discipline verbatim
    assert "never call a dated reading 'current'" in blob
    # absence is a finding, not a gap
    assert "zero rows" in blob


def test_fgis_sql_prunes_the_projection_and_guards_the_as_of():
    """The commodity equality pins the projected slug axis; the +13d lag shifts the as-of RHS literal
    (sargable, backend-agnostic) and NO calendar-year bound is emitted."""
    spec = Q.NumberQuery(table=FGIS, metric="exports_mt_ctd", asof="2026-08-18",
                         commodity="corn_cbot", country="MEXICO")
    sql = Q.build_sql(spec)
    assert "leviathan_slug = 'corn_cbot'" in sql                  # the projected slug axis, pinned
    assert "destination_country = 'MEXICO'" in sql                # literal compare, no name resolution
    assert "CAST(week_ending_date AS varchar) <= '2026-08-05'" in sql   # 2026-08-18 minus the measured 13d
    assert "marketing_year <=" not in sql and "marketing_year >=" not in sql  # NEVER a calendar-year bound
    assert "ORDER BY week_ending_date DESC" in sql and sql.endswith("LIMIT 1")


def test_fgis_named_season_compiles_to_a_partition_equality():
    """period_sql_type=int makes a named marketing year an exact int equality on the projected partition --
    the pruning the absent year_col would otherwise have provided, without its wrongness."""
    spec = Q.NumberQuery(table=FGIS, metric="exports_mt_ctd", asof="2026-08-18",
                         commodity="corn_cbot", country="MEXICO", period="2025")
    assert "marketing_year = 2025" in Q.build_sql(spec)


def test_fgis_window_read_carries_no_year_bounds_and_both_date_bounds():
    """A season window that OPENS in a later calendar year than the marketing-year label is the exact case
    a year_col would have zeroed out: corn 2025/26 rows dated Jun-Aug 2026 carry marketing_year 2025."""
    spec = Q.NumberQuery(table=FGIS, metric="exports_mt_weekly", asof="2026-08-18",
                         commodity="corn_cbot", country="MEXICO", agg="series",
                         period_start="2026-06-01", period_end="2026-08-18")
    sql = Q.build_sql(spec)
    assert "CAST(week_ending_date AS varchar) >= '2026-06-01'" in sql
    assert "CAST(week_ending_date AS varchar) <= '2026-08-18'" in sql
    assert "marketing_year >= 2026" not in sql          # the silent-zero-rows bound, structurally absent


def test_fgis_requires_a_commodity():
    """leviathan_slug is the projected partition axis: a lookup without a commodity is refused before any
    SQL runs, rather than enumerating the grid."""
    with pytest.raises(ValueError, match="requires commodity"):
        Q.build_sql(Q.NumberQuery(table=FGIS, metric="exports_mt_weekly", asof="2026-08-18"))


def test_fgis_commodity_values_fence_the_five_contracts():
    assert set(_fgis().commodity_values) == {
        "corn_cbot", "soybeans_cbot", "hard_red_winter_wheat_kcbt",
        "hard_red_spring_wheat_mgex", "soft_red_winter_wheat_cbot"}


def test_fgis_oracle_agrees_with_the_guard():
    """apply_pit_filter is the pure-Python twin of the SQL guard. The +13d lag must withhold the newest
    bucket in storage -- which is normally still PARTIAL, since the Thursday run only carries
    certifications through the previous Thursday -- on BOTH sides. Values are the real measured corn ->
    MEXICO season-to-date prints."""
    ts = _fgis()
    rows = [
        {"leviathan_slug": "corn_cbot", "marketing_year": 2025, "destination_country": "MEXICO",
         "week_ending_date": "2026-08-02", "exports_mt_ctd": 21865429.0},
        {"leviathan_slug": "corn_cbot", "marketing_year": 2025, "destination_country": "MEXICO",
         "week_ending_date": "2026-08-09", "exports_mt_ctd": 22361906.0},   # partial week -- not citable
        {"leviathan_slug": "corn_cbot", "marketing_year": 2025, "destination_country": "JAPAN",
         "week_ending_date": "2026-08-02", "exports_mt_ctd": 13884432.0},   # wrong destination
        {"leviathan_slug": "soybeans_cbot", "marketing_year": 2025, "destination_country": "MEXICO",
         "week_ending_date": "2026-08-02", "exports_mt_ctd": 4702558.0},    # wrong commodity
    ]
    spec = Q.NumberQuery(table=FGIS, metric="exports_mt_ctd", asof="2026-08-18",
                         commodity="corn_cbot", country="MEXICO")
    assert [r["exports_mt_ctd"] for r in Q.apply_pit_filter(rows, spec, ts)] == [21865429.0]
    # ...and the withheld week becomes citable exactly 13 days after its own stamp.
    later = Q.NumberQuery(table=FGIS, metric="exports_mt_ctd", asof="2026-08-22",
                          commodity="corn_cbot", country="MEXICO")
    assert sorted(r["exports_mt_ctd"] for r in Q.apply_pit_filter(rows, later, ts)) == \
           [21865429.0, 22361906.0]


def test_fgis_card_reconciles_against_the_f010_registry():
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert FGIS in RC.NUMBERS_TABLES
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == FGIS] == []
    c = reg.table(FGIS)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert (c["knowledge_date_col"], c["knowledge_semantics"], c["publication_lag_days"]) == \
           ("week_ending_date", "data_date", 13)


def test_fgis_is_in_the_pg_mirror_list():
    """A SERVED numbers table must be MIRRORED: unmirrored + GRAPHRAG_NUMBERS_BACKEND=pg raises
    UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA -- here onto a partition-PROJECTED table."""
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert FGIS in P1_TABLES


def test_fgis_stays_out_of_the_projection_distinct_exclusion():
    """NUMBERS_PROJECTION_TABLES is about UNMIRRORED tables, not projected ones -- silver_production and
    silver_nass_crop_progress are both projected, both carded, both mirrored and both absent from it.
    Listing silver_fgis would EXCLUDE its two wide metrics from C002's free existence check (the WASDE
    Title-Case guard) while preventing no probe, because no cascade leg maps to this table."""
    from leviathan.graphrag.numbers.contract_check import NUMBERS_PROJECTION_TABLES
    assert FGIS not in NUMBERS_PROJECTION_TABLES


def test_fgis_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ====================================================================================================
# D-LD -- the silver_wap_table01_revisions card (DARK CAPABILITY CENSUS #2). The estate's only card whose
# SUBJECT is a revision rather than a level, and the first to discharge a recorded D-PQ refusal.
# ====================================================================================================
def _wap():
    return _reg().get(WAP)


def test_wap_card_is_served_and_in_the_tool_enum():
    assert WAP in nreg.visible_tables(_reg())
    assert WAP in _props()["table"]["enum"]


def test_wap_card_pit_shape():
    """VINTAGE on the circular's own 'YYYY-MM' release label + a 12-day publication lag. year_month was
    not merely worse, it was INEXPRESSIBLE: _guard raises without year_col+month_col and this table has
    neither. date_col == knowledge_date_col is what makes agg=latest a single freshest-circular row and a
    release WINDOW expressible at all."""
    ts = _wap()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == \
           ("vintage", "release_month", "release_month")
    assert ts.publication_lag_days == 12
    assert ts.shape == "wide" and ts.commodity_col == "commodity" and ts.country_col == "country"
    assert (ts.period_col, ts.period_sql_type) == ("marketing_year", "string")
    assert ts.provenance_col == "vintage_status"
    assert ts.year_col is None and ts.month_col is None          # why year_month could never compile
    assert set(ts.metrics) == {"value_mmt", "prior_value_mmt", "revision_mmt"}
    assert not ts.levels_only and not ts.quarantined


def test_wap_card_declares_no_partition_cols():
    """Flat / projection-forbidden: there is no projected grid to prune, and a partition_col that is not a
    real Glue partition key is a hard reconcile_numbers failure (SILVER-F047)."""
    from leviathan.silver import registry as SR
    assert _wap().partition_cols == []
    c = SR.load_registry().table(WAP)
    assert c["partition_mode"] == "flat" and c["partition_keys"] == [] and c["projection"] == "forbidden"


def test_wap_card_closes_the_free_axis_in_code_not_in_prose():
    """The D-PQ blocker, discharged twice over: row_filters is the fence that fires on every read, and the
    role_order tiebreak is the deterministic fallback if the filter is ever removed. release_month in
    grain_cols is what keeps the revision SERIES reachable under a vintage collapse."""
    ts = _wap()
    for m in ("value_mmt", "prior_value_mmt", "revision_mmt"):
        rf = ts.metrics[m].row_filters
        assert set(rf) == set(ts.commodity_values)               # every servable commodity is fenced
        assert all(v == {"vintage_type": ["year"]} for v in rf.values())
    assert ts.group_cols() == ["commodity", "country", "marketing_year", "release_month"]
    assert ts.vintage_tiebreak[0].col == "vintage_type"
    assert ts.vintage_tiebreak[0].role_order == ["year", "month"]
    assert ts.vintage_tiebreak[1].col == "row_label" and ts.vintage_tiebreak[1].dir == "asc"


def test_wap_card_fences_the_six_aggregate_groups():
    ts = _wap()
    assert set(ts.commodity_values) == {"coarse_grains", "cotton", "oilseeds", "rice",
                                        "total_grains", "wheat"}
    assert "corn_cbot" not in ts.commodity_values and "soybeans_cbot" not in ts.commodity_values


def test_wap_card_notes_state_the_traps():
    ts = _wap()
    blob = " ".join((ts.description + " " + ts.notes).split()).lower()
    for token in ("always pass a commodity", "always pass a country", "one lookup = one metric",
                  "coarse_grains is corn plus", "million 480-lb bales", "milled",
                  "the may roll is not missing data", "eu27 is dead for grains",
                  "world = total_foreign + us", "production only",
                  "never call a dated reading 'current'"):
        assert token in blob, token
    assert "silver_wasde" in blob and "silver_psd" in blob       # where the balance sheet actually lives


def test_wap_latest_read_fences_the_row_axis_and_guards_the_as_of():
    """Flat table -> no projection to prune; what the SQL must show instead is the vintage_type fence, the
    lag-shifted lexical guard on the 'YYYY-MM' release label, and the per-grain de-duplication."""
    spec = Q.NumberQuery(table=WAP, metric="revision_mmt", asof="2026-08-18",
                         commodity="wheat", country="world", period="2026/27")
    sql = Q.build_sql(spec)
    assert "commodity = 'wheat'" in sql
    assert "vintage_type IN ('year')" in sql                     # the free-axis fence, in the SQL
    assert "country = 'world'" in sql and "marketing_year = '2026/27'" in sql
    assert "CAST(release_month AS varchar) <= '2026-08-06'" in sql        # asof - 12d
    assert "PARTITION BY commodity, country, marketing_year, release_month" in sql
    assert "CASE vintage_type WHEN 'year' THEN 0 WHEN 'month' THEN 1 ELSE 2 END ASC" in sql
    assert "ORDER BY knowledge_date DESC" in sql and sql.endswith("LIMIT 1")


def test_wap_series_read_keeps_one_row_per_circular():
    """THE HALF THE D-PQ REFUSAL SAID WAS UNREACHABLE. The vintage collapse partitions on a grain that
    INCLUDES release_month, so a window returns one row per circular -- the revision path -- rather than
    collapsing the whole window to the newest vintage."""
    spec = Q.NumberQuery(table=WAP, metric="value_mmt", asof="2026-08-18", commodity="wheat",
                         country="world", period="2026/27", agg="series",
                         period_start="2026-01", period_end="2026-08")
    sql = Q.build_sql(spec)
    assert "CAST(release_month AS varchar) >= '2026-01'" in sql
    assert "CAST(release_month AS varchar) <= '2026-08'" in sql
    assert "CAST(release_month AS varchar) <= '2026-08-06'" in sql        # the guard still rides over it
    assert "PARTITION BY commodity, country, marketing_year, release_month" in sql
    assert not sql.endswith("LIMIT 1")


def test_wap_commodity_less_read_raises_before_any_sql():
    """Units are heterogeneous and there is NO unit column: value_mmt is million tonnes for five groups and
    MILLION 480-LB BALES for cotton. unit_overrides is the remedy and its documented consequence is the
    fence -- a commodity-less lookup would serve unattributable rows AND would escape the row_filters
    vintage_type fence, so it must never compile."""
    spec = Q.NumberQuery(table=WAP, metric="value_mmt", asof="2026-08-18", country="world")
    with pytest.raises(ValueError, match="unit_overrides"):
        Q.build_sql(spec)


def test_wap_units_are_declared_per_commodity_including_the_bale_trap():
    ov = _wap().metrics["value_mmt"].unit_overrides
    assert ov["cotton"] == "million 480-lb bales"
    assert ov["rice"] == "MMT, milled basis"
    assert ov["wheat"] == "MMT" and ov["total_grains"] == "MMT"


def test_wap_oracle_agrees_with_the_guard_at_the_publication_boundary():
    """apply_pit_filter is the pure-Python twin of the SQL guard. The +12d lag makes a circular citable on
    the 13TH OF ITS OWN MONTH and withheld through the 12th -- in every calendar month, because asof-12d
    lands on day 1 from the 13th and on the last day of the prior month from the 12th. The monthly-block
    row must be dropped by the row filter on BOTH sides, not merely outranked."""
    ts = _wap()
    rows = [
        {"release_month": "2026-06", "commodity": "wheat", "country": "world",
         "marketing_year": "2026/27", "vintage_type": "year", "vintage_status": "proj.",
         "row_label": "2026/27 proj.", "value_mmt": 844.4, "revision_mmt": 0.6},
        {"release_month": "2026-07", "commodity": "wheat", "country": "world",
         "marketing_year": "2026/27", "vintage_type": "year", "vintage_status": "proj.",
         "row_label": "2026/27 proj.", "value_mmt": 843.8, "revision_mmt": -0.6},
        {"release_month": "2026-07", "commodity": "wheat", "country": "world",     # the monthly block --
         "marketing_year": "2026/27", "vintage_type": "month", "vintage_status": None,   # a DIFFERENT
         "row_label": "Jul", "value_mmt": 820.0, "revision_mmt": None},            # quantity, 23.8 apart
    ]
    kw = dict(table=WAP, metric="value_mmt", commodity="wheat", country="world", period="2026/27")
    early = Q.apply_pit_filter(rows, Q.NumberQuery(asof="2026-07-12", **kw), ts)
    assert [r["value_mmt"] for r in early] == [844.4]             # the July circular is NOT yet citable
    later = Q.apply_pit_filter(rows, Q.NumberQuery(asof="2026-07-13", **kw), ts)
    assert sorted(r["value_mmt"] for r in later) == [843.8, 844.4]
    assert 820.0 not in {r["value_mmt"] for r in later}           # the monthly block never surfaces


def test_wap_window_bounds_compare_against_the_release_LABEL():
    """The documented footgun, pinned so it stays documented: period_start/end are byte-compared against a
    'YYYY-MM' label, so a full ISO date at period_start EXCLUDES that month (a 7-char label sorts before
    its own 10-char first-of-month). Conservative (it narrows), deterministic, and identical on both
    backends -- but it is why the card says to window with 'YYYY-MM'."""
    ts = _wap()
    rows = [{"release_month": rm, "commodity": "wheat", "country": "world", "marketing_year": "2026/27",
             "vintage_type": "year", "vintage_status": "proj.", "row_label": "2026/27 proj.",
             "value_mmt": v} for rm, v in (("2026-05", 843.8), ("2026-06", 844.4), ("2026-07", 843.8))]
    kw = dict(table=WAP, metric="value_mmt", asof="2026-08-18", commodity="wheat", country="world",
              period="2026/27", agg="series")
    ym = Q.apply_pit_filter(rows, Q.NumberQuery(period_start="2026-05", period_end="2026-08", **kw), ts)
    assert [r["release_month"] for r in ym] == ["2026-05", "2026-06", "2026-07"]
    iso = Q.apply_pit_filter(rows, Q.NumberQuery(period_start="2026-05-01", period_end="2026-08-31",
                                                 **kw), ts)
    assert [r["release_month"] for r in iso] == ["2026-06", "2026-07"]     # 2026-05 silently excluded


def test_wap_card_reconciles_against_the_f010_registry():
    """Landing a card is never a one-file edit. Note the trio here is a REWRITE, not a mint: the contract
    said year_month on a table with no year/month column, which build_sql would have raised on."""
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert WAP in RC.NUMBERS_TABLES
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == WAP] == []
    c = reg.table(WAP)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert (c["knowledge_date_col"], c["knowledge_semantics"], c["publication_lag_days"]) == \
           ("release_month", "vintage", 12)
    assert not ({"year", "month"} <= {pc["name"] for pc in c["physical_columns"]})


def test_wap_is_in_the_pg_mirror_list():
    """A SERVED numbers table must be MIRRORED: unmirrored + GRAPHRAG_NUMBERS_BACKEND=pg raises
    UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA."""
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert WAP in P1_TABLES


def test_wap_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


def test_wap_tiebreak_and_filter_columns_resolve_in_the_ddl():
    """check_numbers_schema_pins does NOT cover grain_cols / vintage_tiebreak.col / row_filters columns,
    and this card is the estate's heaviest user of all three -- a silver rename of vintage_type or
    row_label would otherwise surface only as a live Athena COLUMN_NOT_FOUND (the silver_nasa_power class
    that lint was born from). Closed here for this card until the lint is widened."""
    ddl = (cc._DDL / f"{WAP}.sql").read_text(encoding="utf-8")
    ts = _wap()
    cols = set(ts.group_cols()) | {t.col for t in ts.vintage_tiebreak}
    for m in ts.metrics.values():
        for per_commodity in (m.row_filters or {}).values():
            cols |= set(per_commodity)
    for col in sorted(cols):
        assert col in ddl, f"{col} referenced by the card but absent from {WAP}.sql"


def test_wap_is_advertised_to_the_router():
    purpose = next(t.purpose for t in dp.REGISTRY if t.name == "numbers").lower()
    assert "world agricultural production" in purpose and "revision ledger" in purpose
    assert WAP.removeprefix("silver_") in dp.family_names()


def test_wap_enters_no_engine_map():
    """No cascade leg and no pace leg, both deliberate: a monthly ESTIMATE-REVISION ledger is not a flow
    surface, and a pace [N] rendered off it would narrate USDA's editing as production momentum."""
    from leviathan.graphrag.numbers import cascade as casc
    assert WAP not in casc.PACE_TABLES
    assert all((row or {}).get("table") != WAP for row in casc.load_map().values())


def test_wap_period_less_lookup_is_refused_by_code_not_prose():
    """D-LD review FATAL (wf_31e951c7), the CODE half: every WAP circular prints the prior crop's
    prel. beside the current crop's proj., and a period-less agg=latest tiebreaks to the LOWEST
    marketing year -- the WRONG CROP (measured: 799.7 served where the desk means 843.8). The
    notes teach always-pass-period; period_required ENFORCES it pre-SQL with a teaching error
    (the CommodityOffCard idiom on the period axis). Both halves or the CLASS-1 lesson repeats."""
    from leviathan.graphrag.numbers import agent as A, registry as R
    reg = R.load_registry()
    assert reg.get(WAP).period_required is True

    class _Spec:
        table = WAP
        period = None
        commodity = "wheat"
    with pytest.raises(A.PeriodRequiredOffCard, match="WRONG CROP"):
        A._check_period_required(_Spec(), reg)
    _Spec.period = "2026/27"
    A._check_period_required(_Spec(), reg)   # a pinned period passes

    # the fence is opt-in: no other card declares it, so no other card's behaviour moves
    assert [t for t, ts in reg.tables.items() if getattr(ts, "period_required", False)] == [WAP]


# ====================================================================================================
# D-LD TRACK 1 -- the silver_fnc_colombia_monthly card (LIGHT-THE-DARK census row 10). Colombia is the
# largest washed-arabica origin and the monthly FNC print was silver-only: no card, no router clause, no
# way for any answer to reach it. Everything below asserts that something already SERVED is now
# REACHABLE, and that the card's measured content ceilings are stated where the model can read them.
#
# PLACEMENT NOTE (orchestrator, D-LD splice): the drafted block named its constant FNC and its helper
# _fnc(). Its sibling card silver_fnc_colombia_exports_port_type landed in the SAME file in the same
# wave with the same two names, so both were disambiguated to *_MONTHLY / *_PORT. Names only -- no
# assertion in either block was changed.
# ====================================================================================================
def _fnc_monthly():
    return _reg().get(FNC_MONTHLY)


def test_fnc_monthly_card_is_served_and_in_the_tool_enum():
    assert FNC_MONTHLY in nreg.visible_tables(_reg())
    assert FNC_MONTHLY in _props()["table"]["enum"]


def test_fnc_monthly_card_pit_shape():
    """data_date on the FIRST-OF-MONTH data date + a conservative 45-day publication lag: the stamp
    precedes the month's own end by up to 31 days and the family's bulk workbook is picked up on the
    15th of the following month (dag_schedules fnc_colombia, cron(0 12 15 * ? *)) -- 31 + 14 = 45,
    never early, at most ~2 weeks late, and equal to the freshness SLA the estate already carries for
    this family."""
    ts = _fnc_monthly()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == ("data_date", "date", "date")
    assert ts.publication_lag_days == 45
    assert ts.shape == "wide" and ts.commodity_col == "commodity"
    assert ts.country_col is None          # SINGLE-GEOGRAPHY: no geo axis exists to select
    assert ts.partition_cols == ["commodity", "year"] and ts.year_col == "year"
    assert ts.date_col_type == "string"    # `date` is a physical DATE, not a TIMESTAMP -- the registry
    #                                        default; DP-5 substr normalization must NOT be declared here
    assert list(ts.commodity_values) == ["arabica_coffee"]
    assert set(ts.metrics) == {"production_bags_60kg", "exports_bags_60kg", "exports_value_usd_m",
                               "ex_dock_price_usd_cents_per_lb", "internal_price_cop_per_125kg"}
    assert all((m.unit or "").strip() for m in ts.metrics.values())   # every metric declares a unit
    assert not ts.levels_only and not ts.quarantined


def test_fnc_monthly_card_notes_state_the_scope_unit_and_ceiling_traps():
    """The invisible-field law: commodity_values, partition_cols and publication_lag_days never reach the
    model, so every caller-facing rule has to be restated in description/notes. These are the four that
    a wrong answer would come from."""
    ts = _fnc_monthly()
    blob = " ".join((ts.description + " " + ts.notes).split()).lower()
    for token in ("colombia only", "60-kg bags", "one lookup = one metric",
                  "conab", "silver_psd", "arabica_coffee"):
        assert token in blob, token
    # the measured content ceilings, both of them -- the export series is a month shorter than the rest
    assert "april-2026" in blob and "march-2026" in blob
    # the nominal-COP era trap (decade medians span 92 -> 1.91 million)
    assert "nominal" in blob and "never compare cop levels across eras" in blob
    # the physical-vs-exchange price fence
    assert "not the ice arabica" in blob
    # staleness honesty: the recency stamp does the talking, never a 'current' claim
    assert "never call a dated reading 'current'" in blob


def test_fnc_monthly_sql_prunes_the_projection_and_guards_the_as_of():
    """The table is partition-PROJECTED (commodity enum x year 1913-2035). The commodity equality plus the
    sargable year bounds are what keep Athena from enumerating that grid -- the Jul-2026 LIST-storm class,
    pruned exactly the way silver_nass_crop_progress is."""
    spec = Q.NumberQuery(table=FNC_MONTHLY, metric="production_bags_60kg", asof="2026-08-18",
                         commodity="arabica_coffee")
    sql = Q.build_sql(spec)
    assert "commodity = 'arabica_coffee'" in sql                 # the projected commodity axis, pinned
    assert "year <= 2026" in sql                                 # sargable bound, never an equality
    assert "year = " not in sql                                  # an equality would zero out any window
    assert "CAST(date AS varchar) <= '2026-07-04'" in sql        # first-of-month + 45d publication lag
    assert "ORDER BY date DESC" in sql and sql.endswith("LIMIT 1")


def test_fnc_monthly_lookup_without_a_commodity_is_refused_before_any_sql():
    """`commodity` is a PARTITION column, so build_sql RAISES rather than enumerating the projected grid
    (query.py:355). The single-value card does NOT make the argument optional."""
    spec = Q.NumberQuery(table=FNC_MONTHLY, metric="production_bags_60kg", asof="2026-08-18")
    with pytest.raises(ValueError, match="requires commodity"):
        Q.build_sql(spec)


def test_fnc_monthly_window_read_carries_both_year_bounds():
    spec = Q.NumberQuery(table=FNC_MONTHLY, metric="exports_bags_60kg", asof="2026-08-18",
                         commodity="arabica_coffee", agg="series",
                         period_start="2025-01-01", period_end="2026-06-30")
    sql = Q.build_sql(spec)
    assert "year >= 2025" in sql and "year <= 2026" in sql
    assert "CAST(date AS varchar) >= '2025-01-01'" in sql
    assert "CAST(date AS varchar) <= '2026-06-30'" in sql


def test_fnc_monthly_oracle_agrees_with_the_guard():
    """apply_pit_filter is the pure-Python twin of the SQL guard: the +45d lag must withhold the month
    that is stamped but not yet published, on BOTH sides. The rows below are the real measured tail."""
    ts = _fnc_monthly()
    rows = [
        {"commodity": "arabica_coffee", "date": "2026-03-01", "year": 2026,
         "production_bags_60kg": 754470.036813},
        {"commodity": "arabica_coffee", "date": "2026-04-01", "year": 2026,     # +45d -> not citable
         "production_bags_60kg": 697058.417617},                                 # until 2026-05-16
    ]
    early = Q.NumberQuery(table=FNC_MONTHLY, metric="production_bags_60kg", asof="2026-05-15",
                          commodity="arabica_coffee")
    assert [r["production_bags_60kg"] for r in Q.apply_pit_filter(rows, early, ts)] == [754470.036813]
    later = Q.NumberQuery(table=FNC_MONTHLY, metric="production_bags_60kg", asof="2026-05-16",
                          commodity="arabica_coffee")
    assert sorted(r["production_bags_60kg"] for r in Q.apply_pit_filter(rows, later, ts)) == \
        [697058.417617, 754470.036813]


def test_fnc_monthly_card_reconciles_against_the_f010_registry():
    """Landing a card is never a one-file edit: reconcile_numbers binds the card's PIT fields to the
    silver registry contract and requires the numbers_ref back-pointer, and the drift test requires
    NUMBERS_TABLES to enumerate every tables.yaml id (an unenumerated table is STRUCTURALLY UNCHECKED)."""
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert FNC_MONTHLY in RC.NUMBERS_TABLES
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == FNC_MONTHLY] == []
    c = reg.table(FNC_MONTHLY)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert (c["knowledge_date_col"], c["knowledge_semantics"], c["publication_lag_days"]) == \
           ("date", "data_date", 45)
    # partition_cols must be real Glue partition keys on a PROJECTED table (reconcile.py:211-226)
    assert [pk["name"] for pk in c["partition_keys"]] == ["commodity", "year"]


def test_fnc_monthly_is_in_the_pg_mirror_list():
    """A SERVED numbers table must be MIRRORED: unmirrored + GRAPHRAG_NUMBERS_BACKEND=pg raises
    UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA -- here onto a partition-PROJECTED table."""
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert FNC_MONTHLY in P1_TABLES


def test_fnc_monthly_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ====================================================================================================
# D-LD (2026-08-18) -- the silver_fnc_colombia_exports_port_type card. PROJECTED tranche of the dark
# census: Colombian green-coffee exports BY PORT, monthly, silver-CERTIFIED since 2026-07 with no card.
# The load-bearing property here is the SECOND-AXIS PIN: the physical grain carries port AND coffee_type
# and a TableSpec has one geo slot, so coffee_type is fenced in CODE (Metric.row_filters) rather than in
# prose -- the D-PQ CLASS-1 lesson and the silver_wasde arbitrary-region incident, both at once.
# ====================================================================================================
def _fnc_port():
    return _reg().get(FNC_PORT)


def test_fnc_port_card_is_served_and_in_the_tool_enum():
    assert FNC_PORT in nreg.visible_tables(_reg())
    assert FNC_PORT in _props()["table"]["enum"]


def test_fnc_port_card_pit_shape():
    """data_date on the FIRST-OF-MONTH `date` + a conservative 45-day publication lag: FNC restates the
    month inside the following month's workbook edition, so +45d makes month M citable from roughly the
    15th-18th of M+1 -- never early. (The silver_pink_sheet +40 idiom on the same first-of-month stamp.)"""
    ts = _fnc_port()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == ("data_date", "date", "date")
    assert ts.publication_lag_days == 45
    assert ts.shape == "wide" and ts.commodity_col == "commodity" and ts.country_col == "port"
    assert ts.partition_cols == ["commodity", "year"] and ts.year_col == "year"
    assert set(ts.metrics) == {"exports_bags_60kg", "exports_value_usd"}
    assert ts.date_col_type == "string"      # the DEFAULT: `date` is a physical DATE, not a TIMESTAMP,
    #                                          so no DP-5 substr normalization is declared (NASS precedent)
    assert not ts.levels_only and not ts.quarantined


def test_fnc_port_card_declares_its_one_slug_and_teaches_it():
    """CLOSED set of exactly one. The notes say the same fact the fence enforces -- a slug in one and not
    the other is how a prose fence rots into a lie (the NASS class-fence property)."""
    ts = _fnc_port()
    assert list(ts.commodity_values) == ["arabica_coffee"]
    for slug in ts.commodity_values:
        assert slug in ts.notes


def test_fnc_port_off_card_commodity_is_refused_before_any_sql():
    class _S:
        def __init__(self, t, c):
            self.table, self.commodity = t, c
    na._check_commodity_class(_S(FNC_PORT, "arabica_coffee"), _reg())      # must not raise
    for slug in ("robusta_coffee", "brazilian_arabica_coffee", "coffee", "cocoa"):
        with pytest.raises(na.CommodityOffCard):
            na._check_commodity_class(_S(FNC_PORT, slug), _reg())


def test_fnc_port_metrics_declare_units_and_the_green_coffee_row_fence():
    """The second-axis pin, as CODE. coffee_type cannot be a card dimension, so both metrics carry the
    same row_filter -- and both carry a unit, because nothing on this table has a unit column."""
    ts = _fnc_port()
    assert ts.unit_col is None
    for name in ("exports_bags_60kg", "exports_value_usd"):
        m = ts.metrics[name]
        assert (m.unit or "").strip(), f"{name} has no unit"
        assert m.row_filters == {"arabica_coffee": {"coffee_type": ["cafe_verde"]}}, name
    assert ts.metrics["exports_bags_60kg"].unit == "60-kg bags"
    assert ts.metrics["exports_value_usd"].unit == "USD"


def test_fnc_port_card_notes_state_the_traps():
    ts = _fnc_port()
    blob = " ".join((ts.description + " " + ts.notes).split()).lower()
    for token in ("green coffee only", "cafe_verde", "always pass a port",
                  "one lookup = one metric and one port", "colombia only",
                  "buenaventura", "cartagena", "60-kg bags", "no destination"):
        assert token in blob, token
    # the three types the card REFUSES are named, so a decline is possible instead of a substitution
    for excluded in ("soluble", "tostados", "extractos"):
        assert excluded in blob, excluded
    # staleness honesty: the reading's own stamp does the talking, never a 'current' claim
    assert "never call a dated reading 'current'" in blob


def test_fnc_port_sql_prunes_the_projection_guards_the_as_of_and_pins_green():
    """PROJECTED (commodity enum x year 2017-2035). The commodity equality plus sargable YEAR BOUNDS are
    what keep Athena off the projected grid; the coffee_type IN(...) is the second-axis fence."""
    spec = Q.NumberQuery(table=FNC_PORT, metric="exports_bags_60kg", asof="2026-06-15",
                         commodity="arabica_coffee", country="buenaventura")
    sql = Q.build_sql(spec)
    assert "commodity = 'arabica_coffee'" in sql                 # the projected commodity axis, pinned
    assert "year <= 2026" in sql                                 # sargable bound, never an equality
    assert "year =" not in sql                                   # an equality would return ZERO rows
    assert "coffee_type IN ('cafe_verde')" in sql                # GREEN ONLY, in the query
    assert "port = 'buenaventura'" in sql                        # the geo axis
    assert "CAST(date AS varchar) <= '2026-05-01'" in sql        # month stamp + 45d publication lag
    assert "ORDER BY date DESC" in sql and sql.endswith("LIMIT 1")


def test_fnc_port_window_read_carries_both_year_bounds():
    spec = Q.NumberQuery(table=FNC_PORT, metric="exports_value_usd", asof="2026-06-15",
                         commodity="arabica_coffee", country="cartagena", agg="series",
                         period_start="2025-01-01", period_end="2026-03-31")
    sql = Q.build_sql(spec)
    assert "year >= 2025" in sql and "year <= 2026" in sql
    assert "CAST(date AS varchar) >= '2025-01-01'" in sql
    assert "coffee_type IN ('cafe_verde')" in sql


def test_fnc_port_commodity_is_mandatory_because_it_is_a_projected_partition():
    with pytest.raises(ValueError, match="requires commodity"):
        Q.build_sql(Q.NumberQuery(table=FNC_PORT, metric="exports_bags_60kg", asof="2026-06-15"))


def test_fnc_port_a_portless_latest_read_is_the_trap_the_notes_name():
    """MEASURED, and the reason `notes` says ALWAYS PASS A PORT: with no port the total-order tiebreak
    falls through to `value` ASC, so agg=latest returns the SMALLEST row of the newest month -- an
    airport shipment of a few hundred bags wearing a national label. Pinned so the shape cannot drift
    away from the sentence that teaches it."""
    sql = Q.build_sql(Q.NumberQuery(table=FNC_PORT, metric="exports_bags_60kg", asof="2026-06-15",
                                    commodity="arabica_coffee"))
    assert "port = " not in sql
    assert sql.endswith("ORDER BY date DESC, year, knowledge_date, value LIMIT 1")


def test_fnc_port_oracle_agrees_with_the_guard_and_mirrors_the_row_fence():
    """apply_pit_filter is the pure-Python twin of the SQL: the +45d lag must withhold the month that is
    stamped but not yet restated, and the coffee_type fence must drop the processed rows on BOTH sides."""
    ts = _fnc_port()
    rows = [
        {"commodity": "arabica_coffee", "port": "buenaventura", "coffee_type": "cafe_verde",
         "date": "2026-01-01", "year": 2026, "exports_bags_60kg": 517802.0},
        {"commodity": "arabica_coffee", "port": "buenaventura", "coffee_type": "cafe_verde",
         "date": "2026-03-01", "year": 2026, "exports_bags_60kg": 381859.0},   # +45d -> citable 04-15
        {"commodity": "arabica_coffee", "port": "buenaventura", "coffee_type": "soluble",
         "date": "2026-03-01", "year": 2026, "exports_bags_60kg": 9242.0},     # processed: never served
        {"commodity": "arabica_coffee", "port": "cartagena", "coffee_type": "cafe_verde",
         "date": "2026-03-01", "year": 2026, "exports_bags_60kg": 276259.0},   # wrong port
    ]
    early = Q.NumberQuery(table=FNC_PORT, metric="exports_bags_60kg", asof="2026-04-14",
                          commodity="arabica_coffee", country="buenaventura")
    assert [r["exports_bags_60kg"] for r in Q.apply_pit_filter(rows, early, ts)] == [517802.0]
    later = Q.NumberQuery(table=FNC_PORT, metric="exports_bags_60kg", asof="2026-04-15",
                          commodity="arabica_coffee", country="buenaventura")
    assert sorted(r["exports_bags_60kg"] for r in Q.apply_pit_filter(rows, later, ts)) == \
        [381859.0, 517802.0]
    assert 9242.0 not in [r["exports_bags_60kg"] for r in Q.apply_pit_filter(rows, later, ts)]


def test_fnc_port_card_reconciles_against_the_f010_registry():
    """Landing a card is never a one-file edit: reconcile_numbers binds the card's PIT fields to the
    silver registry contract and requires the numbers_ref back-pointer, and the drift test requires
    NUMBERS_TABLES to enumerate every tables.yaml id."""
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert FNC_PORT in RC.NUMBERS_TABLES
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == FNC_PORT] == []
    c = reg.table(FNC_PORT)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert (c["knowledge_date_col"], c["knowledge_semantics"], c["publication_lag_days"]) == \
           ("date", "data_date", 45)


def test_fnc_port_is_in_the_pg_mirror_list():
    """A SERVED numbers table must be MIRRORED: unmirrored + GRAPHRAG_NUMBERS_BACKEND=pg raises
    UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA -- here onto a partition-PROJECTED table."""
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert FNC_PORT in P1_TABLES


def test_fnc_port_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []
    # ...and the row_filter column too, which check_numbers_schema_pins does NOT walk: `refs` is built
    # from the card's column FIELDS plus wide metric names, so a rename of coffee_type would only
    # surface as a live COLUMN_NOT_FOUND -- the silver_nasa_power incident that lint was born from.
    import re as _re
    from pathlib import Path
    ddl = Path(cc.__file__).parents[3] / "sql" / "athena" / "ddl" / f"{FNC_PORT}.sql"
    text = ddl.read_text(encoding="utf-8")
    for name in ("coffee_type", "port", "date", "exports_bags_60kg", "exports_value_usd"):
        assert _re.search(rf"\b{_re.escape(name)}\b", text), name


# ====================================================================================================
# D-LD -- the silver_nass_citrus card (LIGHT THE DARK): the numbers home of frozen_orange_juice, which
# has no PSD balance sheet (PSD_UNSERVED_SLUGS) and no CFTC positioning, and whose four dark cascade
# legs are WAIVED as honest data absence. A vintage table with two free axes and a paused source.
# ====================================================================================================
def _citrus():
    return _reg().get(CITRUS)


def test_citrus_card_is_served_and_in_the_tool_enum():
    assert CITRUS in nreg.visible_tables(_reg())
    assert CITRUS in _props()["table"]["enum"]


def test_citrus_card_pit_shape():
    """VINTAGE on release_date with NO publication lag -- release_date IS the printed publication event.
    Flat table: no partition_cols, no year_col (declaring either would make reconcile_numbers demand real
    Glue partition keys). No date_col: this card has no data-date axis separate from its vintage."""
    ts = _citrus()
    assert (ts.knowledge_semantics, ts.knowledge_date_col) == ("vintage", "release_date")
    assert ts.publication_lag_days == 0
    assert ts.date_col is None and ts.year_col is None and ts.month_col is None
    assert ts.shape == "wide" and ts.commodity_col == "crop" and ts.country_col == "state"
    assert (ts.period_col, ts.period_sql_type) == ("season", "string")
    assert ts.partition_cols == [] and not ts.quarantined and not ts.levels_only
    assert ts.grain_cols == ["crop", "state", "season"]
    assert ts.group_cols() == ["crop", "state", "season"]
    assert set(ts.metrics) == {"forecast_1000_boxes", "revision_1000_boxes"}
    assert all(m.unit == "1000 boxes" for m in ts.metrics.values())


def test_citrus_card_declares_the_closed_crop_set_as_code_not_prose():
    """D-PQ CLASS-1: the six crop labels are the CODE fence (CommodityOffCard, pre-SQL). They are NOT
    contract slugs -- an `orange_juice` / `frozen_orange_juice` ask must be refused, not widened."""
    ts = _citrus()
    assert set(ts.commodity_values) == {"all_orange", "valencia_orange", "non_valencia_orange",
                                        "grapefruit", "tangerine_mandarin", "tangelo"}
    assert "frozen_orange_juice" not in ts.commodity_values
    assert "orange_juice" not in ts.commodity_values


def test_citrus_card_needs_no_vintage_tiebreak_because_the_grain_cannot_tie():
    """The engine-order tie hazard (the F2 Branch-A break) needs >1 row per grain at one knowledge_date.
    (season, release_date, crop, state) is the F010 NATURAL KEY, the tracked producer raises on a
    duplicate of it, and the physical parquet carries zero duplicates on it across 2,450 rows."""
    from leviathan.silver import registry as SR
    ts = _citrus()
    assert ts.vintage_tiebreak == []
    nk = SR.load_registry().table(CITRUS)["natural_key"]
    assert set(ts.group_cols()) | {ts.knowledge_date_col} == set(nk)


def test_citrus_card_notes_state_the_scope_units_and_staleness_traps():
    ts = _citrus()
    blob = " ".join((ts.description + " " + ts.notes).split()).lower()
    for token in ("one lookup = one metric", "one call per", "(metric, crop, state)",
                  "united states and nothing else", "brazil",
                  "'united_states'", "never reconstruct the national figure by adding states",
                  "all_orange is valencia_orange plus non_valencia_orange",
                  "tangelo is florida only", "'2024-25'", "thousand boxes",
                  "never be converted to tonnes", "the source is paused",
                  "silver_nass_crop_progress"):
        assert token in blob, token
    # staleness honesty: the release stamp does the talking, never a 'current' claim
    assert "never call a dated reading 'current'" in blob
    # the cross-card vocabulary trap, both halves
    assert "2-letter usps code" in blob and "lower_snake full names" in blob


def test_citrus_sql_collapses_to_the_latest_release_and_guards_the_as_of():
    """Flat table -> no projection to prune and no partition equality to satisfy; what must be present is
    the vintage ROW_NUMBER over the declared grain and the as-of guard on release_date."""
    spec = Q.NumberQuery(table=CITRUS, metric="forecast_1000_boxes", asof="2025-04-15",
                         commodity="all_orange", country="florida", period="2024-25")
    sql = Q.build_sql(spec)
    assert "crop = 'all_orange'" in sql
    assert "state = 'florida'" in sql
    assert "season = '2024-25'" in sql                                    # string period, hyphen form
    assert "CAST(release_date AS varchar) <= '2025-04-15'" in sql         # no publication lag
    assert ("ROW_NUMBER() OVER (PARTITION BY crop, state, season "
            "ORDER BY release_date DESC) AS _rn") in sql
    assert "WHERE _rn = 1" in sql
    assert "year <=" not in sql                                          # flat: no sargable year bound


def test_citrus_latest_is_as_known_not_a_single_row():
    """No date_col -> agg=latest keeps the deduped-SET shape (the PSD/WASDE branch), one row per season.
    The card says so in notes; this pins that the compiler agrees, so 'latest' is never sold as one row."""
    spec = Q.NumberQuery(table=CITRUS, metric="forecast_1000_boxes", asof="2025-04-15",
                         commodity="all_orange", country="florida")
    sql = Q.build_sql(spec)
    assert not sql.endswith("LIMIT 1")
    assert "ORDER BY period, country, knowledge_date, value" in sql
    assert sql.endswith("LIMIT 5000")


def test_citrus_oracle_agrees_with_the_vintage_guard():
    """apply_pit_filter is the pure-Python twin of the SQL: only the newest release on/before the as-of
    survives per (crop, state, season), and a later release becomes citable only once it is published."""
    ts = _citrus()
    rows = [
        {"crop": "all_orange", "state": "florida", "season": "2024-25",
         "release_date": "2025-03-11", "forecast_1000_boxes": 11600.0},
        {"crop": "all_orange", "state": "florida", "season": "2024-25",
         "release_date": "2025-04-10", "forecast_1000_boxes": 11600.0},
        {"crop": "all_orange", "state": "florida", "season": "2024-25",     # not yet published
         "release_date": "2025-05-12", "forecast_1000_boxes": 11630.0},     # at a 2025-04-15 as-of
        {"crop": "all_orange", "state": "california", "season": "2024-25",  # wrong state
         "release_date": "2025-04-10", "forecast_1000_boxes": 47500.0},
        {"crop": "valencia_orange", "state": "florida", "season": "2024-25",  # wrong crop
         "release_date": "2025-04-10", "forecast_1000_boxes": 7000.0},
    ]
    spec = Q.NumberQuery(table=CITRUS, metric="forecast_1000_boxes", asof="2025-04-15",
                         commodity="all_orange", country="florida")
    assert [r["forecast_1000_boxes"] for r in Q.apply_pit_filter(rows, spec, ts)] == [11600.0]
    later = Q.NumberQuery(table=CITRUS, metric="forecast_1000_boxes", asof="2025-05-20",
                          commodity="all_orange", country="florida")
    assert [r["forecast_1000_boxes"] for r in Q.apply_pit_filter(rows, later, ts)] == [11630.0]
    # ...and with no state the read spans states -- the exact "state number wearing a national label"
    # hazard the notes forbid, pinned so the card's ALWAYS-PASS-A-STATE sentence is not decoration.
    stateless = Q.NumberQuery(table=CITRUS, metric="forecast_1000_boxes", asof="2025-04-15",
                              commodity="all_orange")
    assert sorted(r["forecast_1000_boxes"]
                  for r in Q.apply_pit_filter(rows, stateless, ts)) == [11600.0, 47500.0]


def test_citrus_card_reconciles_against_the_f010_registry():
    """The PIT trio was ALREADY on the F010 contract before this card -- which is exactly the trio that
    drifts silently, because nothing about the card's arrival looks like a field being minted."""
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert CITRUS in RC.NUMBERS_TABLES
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == CITRUS] == []
    c = reg.table(CITRUS)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert (c["knowledge_date_col"], c["knowledge_semantics"], c["publication_lag_days"]) == \
           ("release_date", "vintage", 0)
    # the card serves BOTH F010 value_columns and no others (hlb_trend_factor is a diagnostic whose
    # original definition the tracked transform records as unreconstructible)
    assert set(_citrus().metrics) == set(c["value_columns"])
    assert "hlb_trend_factor" not in _citrus().metrics


def test_citrus_is_in_the_pg_mirror_list():
    """A SERVED numbers table must be MIRRORED: unmirrored + GRAPHRAG_NUMBERS_BACKEND=pg raises
    UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA."""
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert CITRUS in P1_TABLES


def test_citrus_is_not_excluded_from_c002():
    """NUMBERS_PROJECTION_TABLES exists to keep INV-3 off PROJECTED partition columns. This table is
    flat/projection-forbidden with one object, so excluding it would only blind C002 to a real table."""
    from leviathan.graphrag.numbers import contract_check as cch
    assert CITRUS not in cch.NUMBERS_PROJECTION_TABLES


def test_citrus_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ====================================================================================================
# D-LD (2026-08-18) -- the silver_mpoc_trade_stats_monthly card. The D-PQ tranche-1a review RANKED and
# REFUSED this table ("stale"); the refusal is discharged here by re-measurement, and the discharge is
# itself pinned -- a closed archive is servable, a corrupt column is not.
# ====================================================================================================
def _mpoc_trade():
    return _reg().get(MPOC_TRADE)


def test_mpoc_trade_card_is_served_and_in_the_tool_enum():
    assert MPOC_TRADE in nreg.visible_tables(_reg())
    assert MPOC_TRADE in _props()["table"]["enum"]


def test_mpoc_trade_card_pit_shape():
    """year_month on year+month -- the ONI/IOD/stock-comparison idiom. publication_lag_days stays at the
    model default because the year_month branch of _guard RETURNS BEFORE the publication-lag shift is
    applied: a lag declared here would be inert decoration the F010 reconcile then carries as real."""
    ts = _mpoc_trade()
    assert ts.knowledge_semantics == "year_month"
    assert (ts.year_col, ts.month_col) == ("year", "month")
    assert ts.knowledge_date_col is None and ts.date_col is None
    assert ts.publication_lag_days == 0
    assert ts.shape == "wide"
    assert ts.commodity_col is None and ts.country_col is None and ts.period_col is None
    assert set(ts.metrics) == {"exports_mt"}, "imports_mt is CORRUPT on 2020-2022 and must not be served"
    assert ts.metrics["exports_mt"].unit == "MT"
    assert not ts.levels_only and not ts.quarantined


def test_mpoc_trade_card_declares_no_partition_cols():
    """SARGABLE PARTITION DISCIPLINE in its NEGATIVE form: flat / projection-forbidden, so there is no
    projected grid to prune -- and a partition_col that is not a real Glue partition key is a hard
    reconcile_numbers failure (SILVER-F047)."""
    from leviathan.silver import registry as SR
    assert _mpoc_trade().partition_cols == []
    c = SR.load_registry().table(MPOC_TRADE)
    assert c["partition_mode"] == "flat" and c["partition_keys"] == [] and c["projection"] == "forbidden"


def test_mpoc_trade_notes_state_the_closed_archive_and_the_mpob_pairing():
    """The three traps a bare national tonnage invites, each pinned where a future editor would soften
    it: (1) a 2023 number narrated as current, (2) MPOC and MPOB cited as two independent readings of
    what is measurably ONE republished series, (3) an import/re-export answer off a corrupt column."""
    ts = _mpoc_trade()
    blob = (ts.description + " " + ts.notes).lower()
    for token in ("2023-12", "2009-01", "silver_mpob", "closed historical archive",
                  "imports are not served by this card", "malaysia only, palm oil only, exports only"):
        assert token in blob, token
    assert "never call a dated reading 'current'" in blob
    assert "never cite both as independent confirmation" in blob
    # ...and the claim the ceiling must NEVER be dressed up as: this card has no present tense.
    assert "the latest" in blob and "will never extend" in blob


def test_mpoc_trade_latest_read_guards_the_as_of():
    spec = Q.NumberQuery(table=MPOC_TRADE, metric="exports_mt", asof="2026-08-18")
    sql = Q.build_sql(spec)
    assert "(year * 100 + month) <= 202608" in sql     # the year_month leakage guard
    assert "year <= 2026" in sql                       # the bare-column bound that rides beside it
    assert "ORDER BY (year * 100 + month) DESC" in sql and sql.endswith("LIMIT 1")
    assert "commodity" not in sql and "country" not in sql   # no such axes exist on this table


def test_mpoc_trade_window_read_carries_both_ym_bounds():
    spec = Q.NumberQuery(table=MPOC_TRADE, metric="exports_mt", asof="2026-08-18", agg="series",
                         period_start="2011-01", period_end="2011-12")
    sql = Q.build_sql(spec)
    assert "(year * 100 + month) >= 201101" in sql and "(year * 100 + month) <= 201112" in sql
    assert "year >= 2011" in sql and "year <= 2011" in sql   # sargable bare-column bounds ride along
    assert "(year * 100 + month) <= 202608" in sql           # the guard still rides over the window


def test_mpoc_trade_card_states_the_annual_page_leak_instead_of_understating_it():
    """The stock-comparison card's leak is 'the data month plus the print lag, up to ~45 days'. THIS
    series was published one ANNUAL PAGE PER YEAR (15 stat_urls in configs/sources/mpoc_archive.yaml),
    so a month is not knowable until its YEAR'S page exists -- up to ~12 months. Inheriting the sibling's
    ~45-day wording would be an understatement, which is the D-PQ FIX-4 failure class.

    Pinned as TEXT because that is where the claim lives, and ANTI-VACUOUSLY because the oracle proves
    the guard really does hand back a month nobody could have read."""
    ts = _mpoc_trade()
    blob = (ts.description + " " + ts.notes).lower()
    assert "admits the current, incomplete month" in blob
    assert "twelve months" in blob and "annual page" in blob
    assert "not yet published" in blob
    assert "45 days" not in blob and "~2 weeks" not in blob   # the sibling's number is WRONG here

    rows = [{"year": 2015, "month": 6, "exports_mt": 1.0}]
    spec = Q.NumberQuery(table=MPOC_TRADE, metric="exports_mt", asof="2015-06-30")
    assert Q.apply_pit_filter(rows, spec, ts), (
        "the incomplete current month is withheld after all -- the card's leak paragraph is now "
        "overstated, re-measure it")


def test_mpoc_trade_oracle_agrees_with_the_guard():
    """apply_pit_filter is the pure-Python twin of the SQL guard: a month whose LABEL is later than the
    as-of's is withheld on both sides. (Label, not publication -- the row above pins that the current
    month is admitted, which is the card's stated leak.)"""
    ts = _mpoc_trade()
    rows = [
        {"year": 2015, "month": 6, "exports_mt": 1.0},
        {"year": 2015, "month": 7, "exports_mt": 2.0},     # later LABEL -> withheld
        {"year": 2014, "month": 12, "exports_mt": 3.0},
    ]
    spec = Q.NumberQuery(table=MPOC_TRADE, metric="exports_mt", asof="2015-06-30")
    assert sorted(r["exports_mt"] for r in Q.apply_pit_filter(rows, spec, ts)) == [1.0, 3.0]


def test_mpoc_trade_commodity_fence_is_spec_level_and_compiles_to_nothing():
    """commodity_values on a card with NO commodity_col. It refuses an off-subject lookup BEFORE any SQL
    (the D-PQ CLASS-1 mechanism), and because query._filters emits the equality only when commodity_col
    is set, an ON-list commodity changes the compiled SQL not at all. Both halves are pinned: without
    the second, a future commodity_col would silently turn this list into a zero-row WASDE-Title-Case
    filter."""
    ts = _mpoc_trade()
    assert ts.commodity_values == ["malaysian_crude_palm_oil_cme", "palm_oil"]
    assert ts.commodity_col is None

    on_list = Q.NumberQuery(table=MPOC_TRADE, metric="exports_mt", asof="2026-08-18",
                            commodity="malaysian_crude_palm_oil_cme")
    bare = Q.NumberQuery(table=MPOC_TRADE, metric="exports_mt", asof="2026-08-18")
    assert Q.build_sql(on_list) == Q.build_sql(bare)      # the fence is spec-level, never SQL

    with pytest.raises(na.CommodityOffCard) as e:
        na._check_commodity_class(
            Q.NumberQuery(table=MPOC_TRADE, metric="exports_mt", asof="2026-08-18",
                          commodity="soybean_oil"), _reg())
    assert "malaysian_crude_palm_oil_cme" in str(e.value)  # the message IS the remedy


def test_mpoc_trade_card_reconciles_against_the_f010_registry():
    """Landing a card is never a one-file edit: reconcile_numbers binds the card's PIT fields to the
    silver contract and requires the numbers_ref back-pointer, and the drift test requires
    NUMBERS_TABLES to enumerate every tables.yaml id (an unenumerated table is STRUCTURALLY UNCHECKED)."""
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert MPOC_TRADE in RC.NUMBERS_TABLES
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == MPOC_TRADE] == []
    c = reg.table(MPOC_TRADE)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert (c["knowledge_date_col"], c["knowledge_semantics"], c["publication_lag_days"]) == \
           (None, "year_month", None)
    # SPLICE-TIME CONFLICT, RESOLVED THE PIN'S WAY (D-LD orchestrator, 2026-08-18). The F010
    # regeneration initially dropped imports_mt from value_columns because the generator coupled
    # value_columns to CARD metrics -- i.e. a serving exclusion silently narrowed the WRITER
    # contract, exactly the class the drafted pin forbids. Fixed at the source: the generator's
    # _WRITER_EXTRAS override (gen_registry_from_baseline.py, value_columns block) keeps
    # imports_mt declared for as long as the producer writes it, and the drafted equality is
    # re-armed below. The card still serves only exports_mt (imports_mt is MEASURED CORRUPT --
    # prior-year exports on data years 2020-2022); when the producer fix lands and the card
    # re-adds the metric, the override becomes a no-op and can be removed.
    assert c["value_columns"] == ["exports_mt", "imports_mt"]
    assert "imports_mt" in {pc["name"] for pc in c["physical_columns"]}
    assert set(_mpoc_trade().metrics) == {"exports_mt"}


def test_mpoc_trade_is_in_the_pg_mirror_list():
    """A SERVED numbers table must be MIRRORED: unmirrored + GRAPHRAG_NUMBERS_BACKEND=pg raises
    UndefinedTable per query and SILENTLY FALLS BACK TO ATHENA."""
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert MPOC_TRADE in P1_TABLES


def test_mpoc_trade_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


def test_mpoc_trade_is_advertised_to_the_router():
    """The D-CW coverage property is the general fence; this is the specific clause it forces. Note the
    token is NOT the bare 'mpoc' that already advertises the stock-comparison card -- a shared token
    would keep the coverage test green over a table the router still cannot find."""
    purpose = next(t.purpose for t in dp.REGISTRY if t.name == "numbers").lower()
    assert "malaysian palm export" in purpose
    assert "2023" in purpose, "the advertisement must carry the CEILING, not just the depth"
    assert MPOC_TRADE.removeprefix("silver_") in dp.family_names()


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
