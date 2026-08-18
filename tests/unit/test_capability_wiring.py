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

# D-LD TRANCHE 2 (2026-08-18) -- the SIX NO-DATE-COLUMN cards. Track 1 could not reach any of these:
# `query._guard` anchors on a knowledge/date column or on BOTH year_col AND month_col, and a crop
# `season bigint`, a `year` partition key and a free-text `week_ending` label satisfy neither, so every
# lookup raised BEFORE any SQL compiled. Each table gained ONE producer-derived column (the WIRING
# WAVE-1 pre-step idiom) and only then could a card exist -- which is why every block below asserts the
# PIT trio first and the notes second.
SAGIS_DELIV = "silver_sagis_weekly_deliveries"
AMS = "silver_ams_cotton_quality"
NASS_ANNUAL = "silver_nass_annual"
FOOD_CPI = "silver_food_cpi"
FNC_AREA = "silver_fnc_colombia_area_department"
MPOC_EXPORTS = "silver_mpoc_exports_by_country"

# D-LD TRANCHE 3 (2026-08-19) -- the UNICA Brazil sugar/ethanol family. STRUCTURALLY UNLIKE Tranche 2:
# nothing here needed a producer pre-step, because all three already carried a usable data date
# (`fortnight_date` is a real Glue DATE, `month_date` a clean ISO string), which is why the DDL regen
# for this tranche is a no-op. What kept them dark was a SERVING judgement about ceilings, so the blocks
# below assert the PIT trio first (as Tranche 2 does) and then the CEILING/DEFECT teaching second,
# rather than the closed-set fences Tranche 2's blocks lead with.
UNICA_HIST = "silver_unica_biweekly_season_history"
UNICA_CORN = "silver_unica_corn_ethanol"
UNICA_SALES = "silver_unica_monthly_ethanol_sales"
# The FOURTH table of the tranche's scope, REFUSED a card and pinned as a refusal below.
UNICA_RELEASE = "silver_unica_biweekly_release_series"


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
    # ── D-LD TRANCHE 2. Each token below is NEW to the purpose string, never one a sibling already
    # earned -- which is the whole point of this map: `("sagis",)` or `("mpoc",)` would pass the
    # coverage property while leaving the new table dark to the router, because the token is already
    # paid for by silver_sagis_cec / silver_mpoc_stock_comparison.
    SAGIS_DELIV: ("producer deliveries", "deliveries"),      # NOT ("sagis",) -- see above
    AMS: ("cotton classing", "tenderable"),                  # the estate's only crop-QUALITY axis
    NASS_ANNUAL: ("acreage",),                               # NOT ("nass",) -- crop progress owns that
    FOOD_CPI: ("consumer price inflation", "cpi"),           # never "food inflation" (FP.CPI.TOTL.ZG)
    FNC_AREA: ("coffee area", "by department"),              # disjoint from the two FNC siblings
    MPOC_EXPORTS: ("by destination country",),               # NOT ("mpoc",) -- the monthly card owns that
    # ── D-LD TRANCHE 3. `ethanol` appeared NOWHERE in the purpose string before this wave, so a bare
    # ("ethanol",) would have advertised whichever of the three landed first and then free-ridden for
    # the other two -- the exact failure this map exists to catch, arriving from a genuinely empty
    # vocabulary rather than from a sibling's. Three disjoint tokens instead.
    UNICA_HIST: ("cane crush",),                             # NOT ("ethanol",) -- see above
    UNICA_CORN: ("corn ethanol",),                           # a different FEEDSTOCK, not a synonym
    UNICA_SALES: ("ethanol sales",),                         # SALES, never production
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
    assert len(expected) == len(reg.tables) - 2             # 33 cards -> 31 visible (D-LD Tranche 2)


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
    # D-LD TRANCHE 2: six tokens, each NEW to this string. Listed here as well as in _ADVERTISED
    # because that map is a COVERAGE property (any tuple member passes) while these are the exact
    # phrases the clauses were written to contribute -- a clause reworded into a sibling's vocabulary
    # would still satisfy coverage and would still leave the router unable to tell the pair apart.
    "producer deliveries",          # the SUPPLY-side SAGIS twin, beside the export-pace card
    "cotton classing", "tenderable",  # the only crop-QUALITY axis in the estate
    "acreage",                      # settled ANNUAL state-level US production
    "consumer price inflation",     # ...and never "food inflation": the table is headline CPI
    "coffee area",                  # Colombian AREA, disjoint from the two FNC siblings
    "by destination country",       # MPOC's ANNUAL export book, beside its MONTHLY sibling
    # D-LD TRANCHE 3: three tokens for the UNICA family. The word "ethanol" was absent from the whole
    # purpose string before this wave -- while `when_to_use` already invited "are ethanol margins
    # squeezing demand" here -- so these three close an advertisement gap the router was being asked
    # to route into blind.
    "cane crush",                   # the Centro-Sul biweekly bulletin, season-to-date
    "corn ethanol",                 # the OTHER feedstock, never a synonym for the cane card
    "ethanol sales",                # the demand side: what left the mills, not what they made
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


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# D-LD TRANCHE 2 (2026-08-18) -- THE SIX NO-DATE-COLUMN CARDS.
#
# WHAT MAKES THIS TRANCHE DIFFERENT FROM TRACK 1, and why every block below leads with the PIT trio:
# none of these six could be carded at all before its producer changed. `TableSpec.knowledge_col()`
# yields a column only for vintage / ingest / data_date, and the year_month branch of `query._guard`
# needs BOTH year_col AND month_col -- so a crop `season bigint`, a `year` partition key, a free-text
# `week_ending` label and a bare `country x year` grain each satisfied NOTHING, and every lookup raised
# "table X has no knowledge/date column to anchor the as-of guard" before any SQL was compiled. Each
# table gained exactly ONE producer-derived column (the WIRING WAVE-1 pre-step idiom: conab
# survey_release_date, sagis week_ending_date), the catalog caught up, and the card followed.
#
# THE SHARED PINS, one per block, so a card cannot land half-wired:
#   *_card_pit_shape                               -- the trio + the axis declarations, byte-exact
#   *_card_reconciles_against_the_f010_registry    -- NUMBERS_TABLES + numbers_ref + consumers=both,
#                                                     and the trio equal on BOTH sides (reconcile.py)
#   *_is_in_the_pg_mirror_list                     -- served must mean mirrored (silent Athena fallback)
#   *_card_columns_resolve_in_the_checked_in_ddl   -- through the real lint, not a copy of it
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _f010(table_id: str):
    from leviathan.silver import registry as SR
    return SR.load_registry().table(table_id)


def _reconciles(table_id: str, trio: tuple):
    """The four things landing a card actually costs, asserted through the REAL reconcile lint."""
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert table_id in RC.NUMBERS_TABLES, "an unenumerated table is STRUCTURALLY UNCHECKED"
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == table_id] == []
    c = reg.table(table_id)
    assert c["numbers_ref"] and c["consumers"] == "both"
    assert (c["knowledge_date_col"], c["knowledge_semantics"], c["publication_lag_days"]) == trio


def test_every_tranche2_card_is_served_and_in_the_tool_enum():
    """All six at once: the registry, the visibility derivation and the agent's tool enum agree."""
    reg = _reg()
    enum = _props()["table"]["enum"]
    visible = nreg.visible_tables(reg)
    for tid in (SAGIS_DELIV, AMS, NASS_ANNUAL, FOOD_CPI, FNC_AREA, MPOC_EXPORTS):
        assert tid in reg.tables, tid
        assert tid in visible, tid
        assert tid in enum, tid


def test_no_tranche2_card_declares_period_required():
    """THE DECISION, PINNED AS A DECISION rather than left as an absence. `period_required` refuses a
    period-less lookup outright and is calibrated to the WAP trap: every release prints MULTIPLE period
    rows side by side, so ONE row comes back and it is the WRONG CROP. Three of these six have no date
    axis at all, and on such a card `_order_col` returns None, so `agg='latest'` is a SERIES read -- the
    whole citable history ascending with the period stamped on every row (the silver_icco_cocoa shape,
    which is the structural twin already in the file and likewise unfenced). That is a READING hazard
    the notes teach, not a wrong single number; declaring the fence would additionally refuse the arc
    reads these cards exist to serve. If a future card in this family DOES print rival periods per
    release, this pin is the place that has to move first."""
    reg = _reg()
    opted_in = {t for t, ts in reg.tables.items() if ts.period_required}
    assert opted_in == {"silver_wap_table01_revisions"}, (
        "period_required is still the WAP-only fence; adding a card here needs the wrong-crop "
        "measurement that justified it, not an analogy")


def test_the_three_dateless_tranche2_cards_compile_latest_as_a_series():
    """The MEASUREMENT behind the pin above, so it is not an assertion about the compiler's behaviour
    but a reading of it: with no date_col and no (year_col AND month_col), `agg='latest'` carries no
    LIMIT 1 and returns the ascending series -- which is exactly why the notes on all three say the
    HEADLINE row of such a read is the OLDEST, not the newest."""
    for tid, kw in ((AMS, dict(commodity="cotton")),
                    (NASS_ANNUAL, dict(commodity="corn_cbot", country="IA")),
                    (FNC_AREA, dict(commodity="arabica_coffee", country="huila"))):
        ts = _reg().get(tid)
        assert Q._order_col(ts) is None, tid
        sql = Q.build_sql(Q.NumberQuery(table=tid, metric=sorted(ts.metrics)[0], asof="2026-08-18",
                                        **kw), ts)
        assert sql.endswith("LIMIT 5000"), tid          # the series cap, never the single-row collapse
        assert "LIMIT 1" not in sql, tid


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# (1) silver_sagis_weekly_deliveries -- the SUPPLY side of the SAGIS weekly pair.
# The property this block exists to hold beyond the shared four: the two SAGIS weekly cards are NOT
# equally fresh (deliveries runs to 2026-08, the export file stops 2024-04), which makes the fresher
# table the WRONG one for an export question -- the sharpest substitution hazard in the tranche.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _sagis_deliv():
    return _reg().get(SAGIS_DELIV)


def test_sagis_deliveries_card_pit_shape():
    """data_date on the DERIVED week_ending_date + the ratified +5d sibling lag. date_col_type is
    deliberately UNSET: the column is a Glue `date`, not a TIMESTAMP, so the DP-5 substr normalization
    does not apply and CAST(col AS varchar) is the correct compare on both backends."""
    ts = _sagis_deliv()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == \
           ("data_date", "week_ending_date", "week_ending_date")
    assert ts.publication_lag_days == 5
    assert ts.date_col_type == "string"                  # NOT "timestamp" -- see the docstring
    assert ts.shape == "wide" and ts.commodity_col == "crop"
    assert ts.country_col is None                        # single-geography table; the fence is prose
    assert ts.period_col is None and ts.period_type == "date"   # `season` is a 'YYYY-YY' LABEL
    assert ts.partition_cols == [] and ts.year_col is None
    assert set(ts.metrics) == {"prog_total_mt", "prior_prog_total_mt", "pct_of_prior_yr", "z_vs_3yr_avg"}
    assert not ts.levels_only and not ts.quarantined


def test_sagis_deliveries_declares_its_closed_crop_set():
    ts = _sagis_deliv()
    assert list(ts.commodity_values) == ["maize", "wheat", "soybeans", "sunflower"]
    for crop in ts.commodity_values:
        assert crop in ts.notes, f"{crop} is enforced but not taught in the card's notes"


def test_sagis_deliveries_offcard_crop_is_refused_before_any_sql():
    """The routed South African CONTRACT SLUG is the reflex reach, and it is not a value of this
    column -- so the fence turns a silent zero-row read into a teaching refusal naming the four."""
    class _S:
        def __init__(self, table, commodity):
            self.table, self.commodity = table, commodity
    for slug in ("south_african_white_maize_jse", "sorghum", "barley", "corn_cbot"):
        with pytest.raises(na.CommodityOffCard) as e:
            na._check_commodity_class(_S(SAGIS_DELIV, slug), _reg())
        assert "maize" in str(e.value) and "Nothing was queried." in str(e.value)


def test_sagis_deliveries_sql_applies_the_five_day_lag_and_orders_newest_first():
    spec = Q.NumberQuery(table=SAGIS_DELIV, metric="prog_total_mt", asof="2025-09-01", commodity="maize")
    sql = Q.build_sql(spec)
    assert "crop = 'maize'" in sql
    assert "CAST(week_ending_date AS varchar) <= '2025-08-27'" in sql     # asof - 5d
    assert "ORDER BY week_ending_date DESC" in sql and sql.endswith("LIMIT 1")


def test_sagis_deliveries_oracle_agrees_with_the_guard():
    """apply_pit_filter is the pure-Python twin of the SQL guard: the +5d lag must withhold the week
    that is stamped but not yet posted, on BOTH sides."""
    ts = _sagis_deliv()
    rows = [
        {"crop": "maize", "week_ending_date": "2025-08-22", "prog_total_mt": 13_520_800.0},
        {"crop": "maize", "week_ending_date": "2025-08-29", "prog_total_mt": 13_690_000.0},  # +5d -> not yet
        {"crop": "wheat", "week_ending_date": "2025-08-22", "prog_total_mt": 100.0},          # wrong crop
    ]
    spec = Q.NumberQuery(table=SAGIS_DELIV, metric="prog_total_mt", asof="2025-09-01", commodity="maize")
    assert [r["week_ending_date"] for r in Q.apply_pit_filter(rows, spec, ts)] == ["2025-08-22"]
    later = Q.NumberQuery(table=SAGIS_DELIV, metric="prog_total_mt", asof="2025-09-05", commodity="maize")
    assert sorted(r["week_ending_date"] for r in Q.apply_pit_filter(rows, later, ts)) == \
           ["2025-08-22", "2025-08-29"]


def test_sagis_deliveries_notes_name_the_freshness_substitution_trap():
    ts = _sagis_deliv()
    blob = " ".join((ts.description + " " + ts.notes).lower().split())
    for token in ("silver_sagis_weekly_exports",       # the sibling, named rather than implied
                  "deliveries are not exports",        # the definitional split
                  "april 2024",                        # the sibling's ceiling, said out loud
                  "cumulative",                        # prog_total_mt is season-to-date, not a flow
                  "south_african_white_maize_jse",     # the slug that is NOT a value of `crop`
                  "degenerate"):                       # the ratio/z base warning
        assert token in blob, token
    assert "never call a dated reading 'current'" in blob


def test_sagis_deliveries_card_reconciles_against_the_f010_registry():
    _reconciles(SAGIS_DELIV, ("week_ending_date", "data_date", 5))


def test_sagis_deliveries_is_in_the_pg_mirror_list():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert SAGIS_DELIV in P1_TABLES


def test_sagis_deliveries_freshness_ceiling_is_not_widened_by_its_publication_lag():
    """THE BANKED CATEGORY ERROR, pinned on the card that would have re-earned it. `publication_lag_days`
    guards the AS-OF axis; `FreshnessLagDays` measures S3 WRITE recency, and the Friday fire writes
    weekly whatever the content lag. Without the override the sagis FAMILY ceiling moved 14 -> 19 the
    moment this card declared +5d, because this table WAS the family minimum at lag 0."""
    from leviathan.silver import dag_catalog as DC
    assert DC.FRESHNESS_LAG_OVERRIDES[SAGIS_DELIV] == 14
    assert DC.build_catalog()["sagis"].max_sla_lag_days == 14


def test_sagis_deliveries_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# (2) silver_ams_cotton_quality -- the estate's ONLY crop-QUALITY axis (27 rows, annual, vintage on the
# AMS-1 derived release_date, NO date axis at all).
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _ams():
    return _reg().get(AMS)


def test_ams_cotton_card_pit_shape():
    """VINTAGE on the DERIVED release_date with a ZERO lag -- release_date IS the (conservatively
    derived) publication event, the conab_coffee Card B idiom. There is deliberately NO date_col: the
    data axis is the season integer, and pointing date_col at the vintage axis is the canary-banned
    pattern (vintage_dates_real, 2026-07-04)."""
    ts = _ams()
    assert (ts.knowledge_semantics, ts.knowledge_date_col) == ("vintage", "release_date")
    assert ts.publication_lag_days == 0
    assert ts.date_col is None and ts.year_col is None and ts.month_col is None
    assert ts.shape == "wide" and ts.commodity_col == "commodity" and ts.country_col is None
    assert (ts.period_col, ts.period_type, ts.period_sql_type) == ("season", "marketing_year", "int")
    assert ts.partition_cols == [] and not ts.levels_only and not ts.quarantined
    assert ts.grain_cols == ["commodity", "geography", "season"]
    assert set(ts.metrics) == {"percent_tenderable", "avg_staple", "samples_classed"}
    # the two all-null columns are EXCLUDED on purpose (0/27 non-null; the drought_z zero-row class)
    assert "avg_micronaire" not in ts.metrics and "avg_strength" not in ts.metrics


def test_ams_cotton_card_declares_its_closed_slug_set():
    ts = _ams()
    assert list(ts.commodity_values) == ["cotton"]
    for slug in ts.commodity_values:
        assert slug in ts.notes, f"{slug} is enforced but not taught in the card's notes"


def test_ams_cotton_off_card_commodity_is_refused_before_any_sql():
    class _S:
        def __init__(self, table, commodity):
            self.table, self.commodity = table, commodity
    for slug in ("corn_cbot", "cotton_ice", "soybeans_cbot", "arabica_coffee"):
        with pytest.raises(na.CommodityOffCard) as e:
            na._check_commodity_class(_S(AMS, slug), _reg())
        assert "cotton" in str(e.value) and "Nothing was queried." in str(e.value)


def test_ams_cotton_sql_guards_the_as_of_on_the_derived_vintage():
    """Flat table, projection forbidden -- there is no grid to prune, so the whole SQL story is the
    commodity equality plus the vintage guard plus the latest-vintage collapse on the TRUE grain."""
    spec = Q.NumberQuery(table=AMS, metric="percent_tenderable", asof="2025-06-02", commodity="cotton")
    sql = Q.build_sql(spec)
    assert "commodity = 'cotton'" in sql
    assert "CAST(release_date AS varchar) <= '2025-06-02'" in sql
    assert "PARTITION BY commodity, geography, season ORDER BY release_date DESC" in sql
    assert "AS _v WHERE _rn = 1" in sql


def test_ams_cotton_period_read_pins_one_season_as_an_int():
    spec = Q.NumberQuery(table=AMS, metric="avg_staple", asof="2025-06-02", commodity="cotton",
                         period="2023")
    assert "season = 2023" in Q.build_sql(spec)          # period_sql_type int -> unquoted literal


def test_ams_cotton_has_no_date_axis_so_a_window_compiles_to_nothing():
    """THE CARD'S SHARPEST CALLER TRAP, pinned as code. With no date_col and no year_col there is
    nothing for period_start/period_end to bind to, so a windowed series read compiles
    BYTE-IDENTICALLY to the un-windowed one -- which is precisely why `notes` tells the caller to pass
    `period` instead."""
    base = Q.NumberQuery(table=AMS, metric="avg_staple", asof="2026-08-18", commodity="cotton",
                         agg="series")
    windowed = Q.NumberQuery(table=AMS, metric="avg_staple", asof="2026-08-18", commodity="cotton",
                             agg="series", period_start="2015-01-01", period_end="2026-08-18")
    assert Q.build_sql(base) == Q.build_sql(windowed)


def test_ams_cotton_oracle_agrees_with_the_guard():
    """A season stays withheld until its DERIVED release date, on BOTH sides. Season 2025's stamp is
    2026-09-01, so it is NOT knowable at an August-2026 as-of -- the conservative pin's cost, asserted
    rather than assumed."""
    ts = _ams()
    rows = [
        {"commodity": "cotton", "geography": "us_total", "season": 2023,
         "release_date": "2024-09-01", "percent_tenderable": 79.3},
        {"commodity": "cotton", "geography": "us_total", "season": 2025,
         "release_date": "2026-09-01", "percent_tenderable": 80.6},
    ]
    spec = Q.NumberQuery(table=AMS, metric="percent_tenderable", asof="2026-08-18", commodity="cotton")
    assert [r["season"] for r in Q.apply_pit_filter(rows, spec, ts)] == [2023]
    later = Q.NumberQuery(table=AMS, metric="percent_tenderable", asof="2026-09-02", commodity="cotton")
    assert sorted(r["season"] for r in Q.apply_pit_filter(rows, later, ts)) == [2023, 2025]


def test_ams_cotton_card_notes_state_the_pit_and_scope_traps():
    """THE BLOB IS description + notes + EVERY METRIC DESC, and that is the correct surface rather than
    a convenience: the model sees id / description / knowledge_semantics / period / metrics / notes, so
    a rule stated in a metric's `unit` or `desc` is as reachable as one stated in `notes`. The staple
    UNIT is literally `avg_staple.unit` -- '32nds of an inch', where a caller reading that one metric
    actually meets it -- and would be invisible to a notes-only assertion; the desc restates it in
    words. Whitespace is normalized because YAML folds these blocks."""
    ts = _ams()
    blob = " ".join((ts.description + " " + ts.notes + " " +
                     " ".join(m.unit + " " + m.desc for m in ts.metrics.values())).lower().split())
    for token in ("32nds of an inch",            # the unit a reader will otherwise report as inches
                  "us cotton",                   # the geography, said out loud
                  "1999-2007",                   # the gap, enumerated rather than hinted
                  "missing report",              # what a gap MEANS
                  "season 2018",                 # the samples_classed coverage floor
                  "not served",                  # micronaire / strength
                  "duplicate of season 2023",    # the measured producer defect
                  "no effect"):                  # period_start/period_end are inert on this card
        assert token in blob, token
    assert "never call a dated reading 'current'" in blob
    for other in ("silver_wasde", "silver_psd", "silver_nass_crop_progress", "silver_futures_prices"):
        assert other in blob, other


def test_ams_cotton_card_reconciles_against_the_f010_registry():
    _reconciles(AMS, ("release_date", "vintage", 0))


def test_ams_cotton_is_in_the_pg_mirror_list():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert AMS in P1_TABLES


def test_ams_cotton_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# (3) silver_nass_annual -- the SETTLED state-level US crop record, and the SILVER-F020 enum defect
# turned into a serving fence.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _nass_annual():
    return _reg().get(NASS_ANNUAL)


def test_nass_annual_card_pit_shape():
    """VINTAGE on the D-LD-9a derived release_date ('<crop year+1>-02-01', +0d): NASS publishes the
    Crop Production ANNUAL SUMMARY for crop year Y in the SECOND WEEK OF JANUARY of Y+1, so
    first-of-the-month-AFTER is always >= the real release -- zero leak, ~3 weeks of withhold."""
    ts = _nass_annual()
    assert (ts.knowledge_semantics, ts.knowledge_date_col) == ("vintage", "release_date")
    assert ts.publication_lag_days == 0
    assert ts.date_col is None and ts.month_col is None
    assert ts.shape == "wide" and ts.commodity_col == "commodity" and ts.country_col == "state"
    assert (ts.period_col, ts.period_type, ts.period_sql_type) == ("year", "year", "int")
    assert ts.year_col == "year" and ts.partition_cols == ["commodity", "year"]
    assert ts.grain_cols == ["commodity", "state", "year"]
    assert set(ts.metrics) == {"production_mt", "yield_t_ha", "area_harvested_ha", "area_planted_ha"}
    assert not ts.levels_only and not ts.quarantined


def test_nass_annual_commodity_values_exclude_the_two_phantom_wheat_slugs_and_hidden_canola():
    """SILVER-F020, RESTATED AS A SERVING FACT. The live projection enum promises six slugs. TWO of
    them (soft_red_winter_wheat_cbot, hard_red_spring_wheat_mgex) have NO physical partition at all, so
    a wheat lookup would compile cleanly and return ZERO rows -- the WASDE Title-Case "silently not yet
    published" class arriving through a partition enum. canola_ice is the OPPOSITE case: 36 objects
    EXIST on S3 and are hidden from Athena by the short enum, so serving it would make the pg mirror
    (which reads the parquet) and Athena (which reads the catalog) DISAGREE. Both are excluded, and the
    fence is engine-independent so a GRAPHRAG_NUMBERS_BACKEND flip cannot change the answer."""
    ts = _nass_annual()
    assert list(ts.commodity_values) == ["corn_cbot", "soybeans_cbot", "cotton", "rough_rice_cbot"]
    for phantom in ("soft_red_winter_wheat_cbot", "hard_red_spring_wheat_mgex", "canola_ice"):
        assert phantom not in ts.commodity_values
    assert "us wheat is not in this\n      table" in ts.notes.lower() or \
           "us wheat is not in this table" in " ".join(ts.notes.lower().split())


def test_nass_annual_off_card_commodity_is_refused_before_any_sql():
    class _S:
        def __init__(self, table, commodity):
            self.table, self.commodity = table, commodity
    for slug in ("soft_red_winter_wheat_cbot", "hard_red_spring_wheat_mgex", "canola_ice",
                 "arabica_coffee"):
        with pytest.raises(na.CommodityOffCard) as e:
            na._check_commodity_class(_S(NASS_ANNUAL, slug), _reg())
        assert "corn_cbot" in str(e.value) and "Nothing was queried." in str(e.value)


def test_nass_annual_sql_prunes_the_projection_and_guards_the_as_of():
    """Partition-PROJECTED (commodity enum x year 1866-2035). The commodity equality plus the sargable
    year bound are what keep Athena from enumerating that grid; a NAMED crop year additionally emits
    the partition equality, which prunes ~170 candidates to one."""
    spec = Q.NumberQuery(table=NASS_ANNUAL, metric="production_mt", asof="2026-08-18",
                         commodity="corn_cbot", country="IA", period="2025")
    sql = Q.build_sql(spec)
    assert "commodity = 'corn_cbot'" in sql
    assert "state = 'IA'" in sql
    assert "year = 2025" in sql and "year <= 2026" in sql
    assert "CAST(release_date AS varchar) <= '2026-08-18'" in sql
    assert "PARTITION BY commodity, state, year ORDER BY release_date DESC" in sql


def test_nass_annual_window_read_emits_bounds_and_never_a_year_equality():
    """The W3.1 rule: `year` is BOTH the projected partition key and the declared year_col, so a WINDOW
    read must bound it (an equality would silently return ZERO rows across a multi-year span)."""
    spec = Q.NumberQuery(table=NASS_ANNUAL, metric="yield_t_ha", asof="2026-08-18",
                         commodity="corn_cbot", country="US", agg="series",
                         period_start="2015-01-01", period_end="2025-12-31")
    sql = Q.build_sql(spec)
    assert "year >= 2015" in sql and "year <= 2025" in sql
    assert "year = " not in sql


def test_nass_annual_oracle_withholds_the_crop_year_whose_january_summary_has_not_published():
    ts = _nass_annual()
    rows = [
        {"commodity": "corn_cbot", "state": "IA", "year": 2025, "release_date": "2026-02-01",
         "production_mt": 70_410_000.0},
        {"commodity": "corn_cbot", "state": "IA", "year": 2026, "release_date": "2027-02-01",
         "production_mt": None},                                     # in-season acreage row, withheld
        {"commodity": "corn_cbot", "state": "IL", "year": 2025, "release_date": "2026-02-01",
         "production_mt": 59_790_000.0},                             # wrong state
    ]
    spec = Q.NumberQuery(table=NASS_ANNUAL, metric="production_mt", asof="2026-08-18",
                         commodity="corn_cbot", country="IA")
    assert [r["year"] for r in Q.apply_pit_filter(rows, spec, ts)] == [2025]


def test_nass_annual_notes_state_the_us_only_state_axis_and_summary_traps():
    ts = _nass_annual()
    blob = " ".join((ts.description + " " + ts.notes).lower().split())
    for token in ("united states and nothing else",   # the geography fence, prose half
                  "always pass a state",              # the free axis with no default
                  "never add 'us' to a list of states",   # the double-count trap
                  "us wheat is not in this table",    # the F020 enum defect, in caller terms
                  "january",                          # the vintage cadence
                  "5,000-row cap",                    # corn alone exceeds it
                  "silver_nass_crop_progress"):       # the sibling that answers the in-season ask
        assert token in blob, token


def test_nass_annual_card_reconciles_against_the_f010_registry():
    _reconciles(NASS_ANNUAL, ("release_date", "vintage", 0))


def test_nass_annual_is_in_the_pg_mirror_list():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert NASS_ANNUAL in P1_TABLES


def test_nass_annual_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# (4) silver_food_cpi -- the macro pressure gauge, and the ONE card in this tranche whose only enforced
# fence is a DATE rather than a vocabulary.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _food_cpi():
    return _reg().get(FOOD_CPI)


def test_food_cpi_card_pit_shape():
    """data_date on the derived year-end observation date + a MEASURED 195-day publication lag, with
    the WB `lastupdated` stamp riding as provenance_col -> the `revision_stamp` alias (the pink-sheet
    latest_release_ym idiom for the same publisher)."""
    ts = _food_cpi()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == \
           ("data_date", "data_date", "data_date")
    assert ts.publication_lag_days == 195
    assert ts.provenance_col == "release_date"
    assert ts.shape == "wide" and ts.commodity_col is None and ts.country_col == "country_iso"
    assert (ts.period_col, ts.period_type, ts.period_sql_type) == ("year", "year", "int")
    assert ts.partition_cols == [] and ts.year_col is None
    assert set(ts.metrics) == {"cpi_yoy_pct", "cpi_yoy_z_5yr", "cpi_yoy_z_10yr", "cpi_available"}
    assert not ts.levels_only and not ts.quarantined


def test_food_cpi_has_no_commodity_fence_and_the_card_says_why():
    """A LIMITATION, RECORDED, not an omission: the registry offers a closed-set fence only on the
    COMMODITY axis, and this card's closed set is on the COUNTRY axis (four ISO3 codes). Repurposing
    commodity_col for it was considered and REJECTED -- the tool schema would ask the model for a
    'commodity' and get a country, and geography resolution would be pointed at nonsense. So the fence
    is PROSE, twice, with the D-PQ CLASS-1 caveat understood."""
    ts = _food_cpi()
    assert list(ts.commodity_values) == []
    blob = " ".join((ts.description + " " + ts.notes).lower().split())
    for iso in ("ind (india)", "idn (indonesia)", "rus (russian federation)", "ukr (ukraine)"):
        assert iso in blob, iso
    assert "there is no commodity axis" in blob


def test_food_cpi_sql_shifts_the_cutoff_back_by_the_measured_lag():
    """The lag shifts the as-of RHS LITERAL (_pub_lagged_asof), so the guard stays sargable and
    backend-agnostic. At 2026-08-18 the cutoff is 2026-02-04, which admits data year 2025."""
    spec = Q.NumberQuery(table=FOOD_CPI, metric="cpi_yoy_pct", asof="2026-08-18", country="IND")
    sql = Q.build_sql(spec)
    assert "country_iso = 'IND'" in sql
    assert "CAST(data_date AS varchar) <= '2026-02-04'" in sql
    assert "release_date AS revision_stamp" in sql        # every row carries its WB release stamp
    assert "ORDER BY data_date DESC" in sql and sql.endswith("LIMIT 1")


def test_food_cpi_pit_guard_withholds_the_year_whose_release_has_not_landed():
    """THE ONLY ENFORCED FENCE THIS CARD HAS, on both sides. At a March-2026 as-of the cutoff is
    2025-08-18, so data year 2025 (data_date 2025-12-31, published 2026-07-13) is NOT yet knowable and
    the newest citable reading is 2024. This is the eval deck's `dld_food_cpi_pit_prerelease_F` row,
    asserted here deterministically."""
    ts = _food_cpi()
    rows = [
        {"country_iso": "IND", "year": 2024, "data_date": "2024-12-31",
         "release_date": "2025-07-13", "cpi_yoy_pct": 4.953},
        {"country_iso": "IND", "year": 2025, "data_date": "2025-12-31",
         "release_date": "2026-07-13", "cpi_yoy_pct": 2.3988},
    ]
    early = Q.NumberQuery(table=FOOD_CPI, metric="cpi_yoy_pct", asof="2026-03-01", country="IND")
    assert [r["year"] for r in Q.apply_pit_filter(rows, early, ts)] == [2024]
    assert "CAST(data_date AS varchar) <= '2025-08-18'" in Q.build_sql(early)
    later = Q.NumberQuery(table=FOOD_CPI, metric="cpi_yoy_pct", asof="2026-08-18", country="IND")
    assert sorted(r["year"] for r in Q.apply_pit_filter(rows, later, ts)) == [2024, 2025]


def test_food_cpi_notes_refuse_the_food_inflation_and_policy_forecast_readings():
    ts = _food_cpi()
    blob = " ".join((ts.description + " " + ts.notes).lower().split())
    assert "food inflation" in blob                     # named, in order to be REFUSED
    assert "consumer price inflation" in blob
    for token in ("always pass a country",              # the free axis with no default
                  "nulls are published absences",       # pre-1993 RUS/UKR
                  "unwinsorized",                       # the z has no plausibility cap
                  "latest-only",                        # no true as-of replay
                  "revision_stamp",                     # the provenance alias, named for the citation
                  "silver_pink_sheet"):                 # the same publisher's price card
        assert token in blob, token
    assert "never call a dated reading 'current'" in blob
    # THE SHARPEST ONE: a policy claim minted from an inflation number is the invention this card refuses
    assert "it can never say a restriction is coming" in blob


def test_food_cpi_card_reconciles_against_the_f010_registry():
    _reconciles(FOOD_CPI, ("data_date", "data_date", 195))


def test_food_cpi_contract_carries_the_applied_replace_columns_types():
    """The catalog migration was a REPLACE, not an ADD, and BOTH halves are corrections of a live
    defect. The three z/level columns were declared `float` (Athena `real`) over DOUBLE parquet, so
    Athena REFUSED to read every served metric while strings, `year`, `cpi_available` and count(*) all
    succeeded -- the table looked alive and no measure column was readable. Pinned on the GENERATED
    contract so a regeneration that dropped the CURATION_OVERRIDES entry fails here."""
    cols = {c["name"]: c for c in _f010(FOOD_CPI)["physical_columns"]}
    for c in ("cpi_yoy_pct", "cpi_yoy_z_5yr", "cpi_yoy_z_10yr"):
        assert cols[c]["glue_type"] == "double", c
    assert cols["cpi_available"]["glue_type"] == "bigint"
    for c in ("data_date", "release_date"):
        assert cols[c]["glue_type"] == "string" and cols[c]["nullable"] is False, c


def test_food_cpi_is_in_the_pg_mirror_list():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert FOOD_CPI in P1_TABLES


def test_food_cpi_freshness_ceiling_is_not_widened_by_its_publication_lag():
    """195 days of CONTENT lag on an ANNUAL cadence would make the write-recency ceiling 595 days for a
    producer that fires MONTHLY. Same law as fgis and sagis: the two numbers protect different things."""
    from leviathan.silver import dag_catalog as DC
    assert DC.FRESHNESS_LAG_OVERRIDES[FOOD_CPI] == 400
    assert DC.build_catalog()["world_bank"].max_sla_lag_days == 85      # pink_sheet's, unmoved


def test_food_cpi_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# (5) silver_fnc_colombia_area_department -- INGEST semantics, and the only card in the tranche that is
# fail-CLOSED before its own snapshot stamp.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _fnc_area():
    return _reg().get(FNC_AREA)


def test_fnc_area_card_pit_shape():
    """INGEST on the carried-through bronze stamp (the silver_production idiom): FNC republishes the
    whole workbook and the producer overwrites, so there are no vintages to collapse and NO publication
    lag to shift -- publication_lag_days stays 0 on the card and NULL in F010, byte-equal."""
    ts = _fnc_area()
    assert (ts.knowledge_semantics, ts.knowledge_date_col) == ("ingest", "ingest_date")
    assert ts.publication_lag_days == 0
    assert ts.date_col is None and ts.month_col is None
    assert ts.shape == "wide" and ts.commodity_col == "commodity" and ts.country_col == "department"
    assert (ts.period_col, ts.period_type, ts.period_sql_type) == ("year", "year", "int")
    assert ts.year_col == "year" and ts.partition_cols == ["commodity", "year"]
    assert set(ts.metrics) == {"area_ha"}
    assert not ts.levels_only and not ts.quarantined


def test_fnc_area_declares_its_single_slug_and_teaches_it():
    ts = _fnc_area()
    assert list(ts.commodity_values) == ["arabica_coffee"]
    assert "arabica_coffee" in ts.notes


def test_fnc_area_off_card_commodity_is_refused_before_any_sql():
    class _S:
        def __init__(self, table, commodity):
            self.table, self.commodity = table, commodity
    for slug in ("robusta_coffee", "coffee", "corn_cbot"):
        with pytest.raises(na.CommodityOffCard) as e:
            na._check_commodity_class(_S(FNC_AREA, slug), _reg())
        assert "arabica_coffee" in str(e.value) and "Nothing was queried." in str(e.value)


def test_fnc_area_sql_prunes_the_smallest_projected_grid_in_the_registry():
    spec = Q.NumberQuery(table=FNC_AREA, metric="area_ha", asof="2026-08-18",
                         commodity="arabica_coffee", country="huila", period="2025")
    sql = Q.build_sql(spec)
    assert "commodity = 'arabica_coffee'" in sql
    assert "department = 'huila'" in sql
    assert "year = 2025" in sql and "year <= 2026" in sql
    assert "CAST(ingest_date AS varchar) <= '2026-08-18'" in sql


def test_fnc_area_is_fail_closed_before_its_own_snapshot_stamp():
    """THE COST, ASSERTED RATHER THAN DISCOVERED. An as-of BEFORE the edition's ingest_date returns
    ZERO rows -- it can never leak, and it means this card answers 'where is the area today' and cannot
    answer 'what was believed in 2019'. The notes say exactly that; this is the code half."""
    ts = _fnc_area()
    rows = [{"commodity": "arabica_coffee", "department": "huila", "year": 2025,
             "ingest_date": "2026-06-02", "area_ha": 150_127.28}]
    early = Q.NumberQuery(table=FNC_AREA, metric="area_ha", asof="2025-06-01",
                          commodity="arabica_coffee", country="huila")
    assert Q.apply_pit_filter(rows, early, ts) == []
    now = Q.NumberQuery(table=FNC_AREA, metric="area_ha", asof="2026-08-18",
                        commodity="arabica_coffee", country="huila")
    assert [r["area_ha"] for r in Q.apply_pit_filter(rows, now, ts)] == [150_127.28]


def test_fnc_area_notes_state_the_no_national_row_and_roster_growth_traps():
    ts = _fnc_area()
    blob = " ".join((ts.description + " " + ts.notes).lower().split())
    for token in ("there is no national total row",   # the sum-with-period rule
                  "n_santander",                      # the exact snake_case department vocabulary
                  "roster grows",                     # 16 -> 20 -> 22 -> 23 departments
                  "hectares",                         # the unit, never bags
                  "silver_fnc_colombia_monthly",      # the sibling that carries production/exports
                  "what was believed in 2019"):       # the fail-closed cost, said in caller terms
        assert token in blob, token
    assert "never call a dated reading 'current'" in blob


def test_fnc_area_card_reconciles_against_the_f010_registry():
    _reconciles(FNC_AREA, ("ingest_date", "ingest", None))


def test_fnc_area_declares_no_lag_so_the_fnc_family_ceiling_is_untouched():
    """The mirror image of the sagis pin: NO publication lag means NO grace to add, so no
    FRESHNESS_LAG_OVERRIDES entry is warranted and the fnc family ceiling stays where the D-LD Track-1
    review put it. An override here would be a pin against nothing."""
    from leviathan.silver import dag_catalog as DC
    assert FNC_AREA not in DC.FRESHNESS_LAG_OVERRIDES
    assert DC.build_catalog()["fnc_colombia"].max_sla_lag_days == 45


def test_fnc_area_is_in_the_pg_mirror_list():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert FNC_AREA in P1_TABLES


def test_fnc_area_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# (6) silver_mpoc_exports_by_country -- the annual DESTINATION book. It DISCHARGES the D-PQ tranche-1a
# `_SKIPPED[...] = "guard"` refusal, which was CORRECT at the time: the table has no month column, so
# the D-LD plan's own `wide/year_month` designation could never have compiled.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _mpoc_exports():
    return _reg().get(MPOC_EXPORTS)


def test_mpoc_exports_card_pit_shape_is_data_date_not_the_plans_year_month():
    """THE PLAN WAS WRONG AND THE CORRECTION IS THE PIN. year_month RAISES without BOTH year_col AND
    month_col; this table has neither a month column nor (deliberately) a year_col -- a year_col would
    only duplicate the `period` alias on the same physical column and buy no pruning on a flat table."""
    ts = _mpoc_exports()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == \
           ("data_date", "year_ending_date", "year_ending_date")
    assert ts.publication_lag_days == 60
    assert ts.year_col is None and ts.month_col is None
    assert ts.shape == "wide" and ts.commodity_col is None and ts.country_col == "country"
    assert (ts.period_col, ts.period_type, ts.period_sql_type) == ("year", "year", "int")
    assert ts.partition_cols == []                       # flat, projection forbidden -- nothing to prune
    assert set(ts.metrics) == {"exports_mt"}
    assert not ts.levels_only and not ts.quarantined


def test_mpoc_exports_declares_a_commodity_fence_despite_having_no_commodity_column():
    """D-PQ CLASS-1 applied to a card with NO product axis. `commodity` emits no SQL here -- but an
    EMPTY commodity_values would let a corn or cocoa lookup sail through and return a palm tonnage
    wearing a grain label, because `_check_commodity_class` reads commodity_values ALONE and never
    consults commodity_col. BOTH surface forms are listed on purpose: refusing a caller for picking the
    other of two names for the SAME product would be a manufactured decline."""
    ts = _mpoc_exports()
    assert ts.commodity_col is None
    assert list(ts.commodity_values) == ["palm_oil", "malaysian_crude_palm_oil_cme"]

    class _S:
        def __init__(self, table, commodity):
            self.table, self.commodity = table, commodity
    for ok in ts.commodity_values:
        na._check_commodity_class(_S(MPOC_EXPORTS, ok), _reg())      # no raise
    for bad in ("corn_cbot", "cocoa", "soybean_oil_cbot"):
        with pytest.raises(na.CommodityOffCard):
            na._check_commodity_class(_S(MPOC_EXPORTS, bad), _reg())


def test_mpoc_exports_sql_shifts_the_cutoff_by_sixty_days():
    spec = Q.NumberQuery(table=MPOC_EXPORTS, metric="exports_mt", asof="2026-08-18", country="india")
    sql = Q.build_sql(spec)
    assert "country = 'india'" in sql
    assert "CAST(year_ending_date AS varchar) <= '2026-06-19'" in sql   # asof - 60d
    assert "ORDER BY year_ending_date DESC" in sql and sql.endswith("LIMIT 1")


def test_mpoc_exports_oracle_holds_the_year_until_the_following_march():
    """Calendar year Y becomes citable on (Y+1)-03-01: the Jan-Dec total is complete only after
    December and MPOC's year page carries it the following January."""
    ts = _mpoc_exports()
    rows = [
        {"country": "india", "year": 2022, "year_ending_date": "2022-12-31", "exports_mt": 2_898_770.0},
        {"country": "india", "year": 2023, "year_ending_date": "2023-12-31", "exports_mt": 2_809_956.0},
    ]
    before = Q.NumberQuery(table=MPOC_EXPORTS, metric="exports_mt", asof="2024-02-15", country="india")
    assert [r["year"] for r in Q.apply_pit_filter(rows, before, ts)] == [2022]
    after = Q.NumberQuery(table=MPOC_EXPORTS, metric="exports_mt", asof="2024-03-01", country="india")
    assert sorted(r["year"] for r in Q.apply_pit_filter(rows, after, ts)) == [2022, 2023]


def test_mpoc_exports_notes_state_the_panel_ceiling_and_no_total_traps():
    ts = _mpoc_exports()
    blob = " ".join((ts.description + " " + ts.notes).lower().split())
    for token in ("top-destination panel",     # not a destination LIST -- the easiest way to misread it
                  "did not stop buying",       # a missing year is a shortlist fall-off, never a zero
                  "there is no total and no share",   # the excluded source TOTAL row
                  "reporting change",          # the eu -> netherlands basis break
                  "2023",                      # the archive ceiling, stated
                  "silver_mpob"):              # where the national denominator actually lives
        assert token in blob, token
    assert "never call a dated reading 'current'" in blob


def test_mpoc_exports_card_reconciles_against_the_f010_registry():
    _reconciles(MPOC_EXPORTS, ("year_ending_date", "data_date", 60))


def test_mpoc_exports_anchor_column_is_a_real_catalog_column_post_alter():
    """THE ORDERING FACT THIS PIN GUARDED IS NOW DISCHARGED: the gated ADD COLUMNS was applied
    2026-08-18 AFTER the canonical re-run (runbook order; verify SELECT read d0=2009-12-31
    d1=2023-12-31 null_anchors=0), the R0 snapshot was refreshed to the five-column truth, and the
    hidden staging (glue_type null, the SILVER-F059 sagis precedent) was retired in the same change.
    The anchor is now a REGULAR catalog column -- so the pg mirror load is UNBLOCKED, and this pin
    flips to guard the discharged state: a regression back to hidden would silently drop the column
    from the generated DDL and re-open the four-column mirror hazard the old pin described."""
    cols = {c["name"]: c for c in _f010(MPOC_EXPORTS)["physical_columns"]}
    anchor = cols["year_ending_date"]
    assert anchor["glue_type"] == "date"                 # REAL: renders in the generated DDL
    assert anchor["target_arrow_type"] == "date32[day]"
    assert anchor["nullable"] is False                   # a null would silently defeat the PIT guard


def test_mpoc_exports_is_in_the_pg_mirror_list():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert MPOC_EXPORTS in P1_TABLES


def test_mpoc_exports_freshness_ceiling_is_not_widened_by_its_publication_lag():
    from leviathan.silver import dag_catalog as DC
    assert DC.FRESHNESS_LAG_OVERRIDES[MPOC_EXPORTS] == 400
    assert DC.build_catalog()["mpoc"].max_sla_lag_days == 45          # unmoved by the +60d card


def test_mpoc_exports_card_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# D-LD TRANCHE 3 (2026-08-19) -- THE UNICA BRAZIL SUGAR/ETHANOL FAMILY.
#
# WHAT MAKES THIS TRANCHE DIFFERENT FROM TRANCHE 2, and why the blocks below are shaped differently:
# Tranche 2 was a PRODUCER wave. Six tables had NO date column of any kind, `query._guard` raised
# before any SQL compiled, and each needed a derived anchor before a card could exist -- so every one
# of those blocks leads with the trio because the trio was the thing that changed.
# These three needed nothing. `fortnight_date` has been a real Glue DATE since the table landed and
# `month_date` a clean ISO string; the DDL regen for this tranche is a NO-OP, and the F010 diff is the
# PIT trio plus the value_columns/consumers that carding any wide table produces. What kept them dark
# was a SERVING JUDGEMENT that had not been made: three tables whose newest reading is months old,
# where the hazard is not a guard that fails but a correctly-guarded old number narrated as the
# current state of the Brazilian crush.
#
# THE OWNER'S RATIFICATION IS THE SPEC (2026-08-18, verbatim): "you can have them but PIT aware with
# its ceiling, so for example if someone asked about something that happened in 2021, it would fetch
# that data but if someone asked a run down over july 2026, it can't use that data." Both halves are
# pinned below, at real as-ofs, against the real stored rows -- and the post-ceiling half is pinned as
# a property of the GUARD (it returns nothing because nothing exists), never as a code fence, because
# there is no fence and inventing one would be a fence against a table's own contents.
#
# THE SHARED PINS, one per block, so a card cannot land half-wired:
#   *_card_pit_shape                               -- the trio + the axis declarations, byte-exact
#   *_card_reconciles_against_the_f010_registry    -- NUMBERS_TABLES + numbers_ref + consumers,
#                                                     and the trio equal on BOTH sides (reconcile.py)
#   *_is_in_the_pg_mirror_list                     -- served must mean mirrored (silent Athena fallback)
#   *_notes_state_the_ceiling_and_its_reason       -- NEW to this tranche and it is the tranche's
#                                                     whole point: a ceiling the notes do not EXPLAIN
#                                                     produces an answer that narrates stale data as
#                                                     current, which is the one outcome the
#                                                     ratification forbids.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
_UNICA_TRIO = {
    UNICA_HIST: ("fortnight_date", "data_date", 14),
    UNICA_CORN: ("fortnight_date", "data_date", 14),
    UNICA_SALES: ("month_date", "data_date", 45),
}
# consumers is NOT uniform across the three and the difference is real, not an oversight: the crush
# history was ALREADY a feature-layer table (consumers=feature_layer) so carding it makes it "both",
# while the other two had no consumer at all and become "numbers_registry". Tranche 2's `_reconciles`
# helper hardcodes "both"; a helper that hardcoded it here would fail on a correct registry.
_UNICA_CONSUMERS = {UNICA_HIST: "both", UNICA_CORN: "numbers_registry", UNICA_SALES: "numbers_registry"}


def _unica_reconciles(table_id: str):
    """The same four things Tranche 2's `_reconciles` asserts, with `consumers` read per table."""
    from leviathan.silver import reconcile as RC
    from leviathan.silver import registry as SR
    reg = SR.load_registry()
    assert table_id in RC.NUMBERS_TABLES, "an unenumerated table is STRUCTURALLY UNCHECKED"
    assert [d.detail for d in RC.reconcile_numbers(reg) if d.table == table_id] == []
    c = reg.table(table_id)
    assert c["numbers_ref"] == f"configs/graphrag/numbers/tables.yaml#{table_id}"
    assert c["consumers"] == _UNICA_CONSUMERS[table_id]
    assert (c["knowledge_date_col"], c["knowledge_semantics"],
            c["publication_lag_days"]) == _UNICA_TRIO[table_id]


def test_every_unica_card_is_served_and_in_the_tool_enum():
    """All three at once: the registry, the visibility derivation and the agent's tool enum agree."""
    reg = _reg()
    enum = _props()["table"]["enum"]
    visible = nreg.visible_tables(reg)
    for tid in (UNICA_HIST, UNICA_CORN, UNICA_SALES):
        assert tid in reg.tables, tid
        assert tid in visible, tid
        assert tid in enum, tid


def test_the_refused_unica_table_is_carded_nowhere():
    """THE REFUSAL, PINNED AS A REFUSAL rather than left as an absence -- the Tranche-3 counterpart of
    Tranche 2's `test_no_tranche2_card_declares_period_required`.

    silver_unica_biweekly_release_series was IN SCOPE for this tranche and is deliberately NOT carded.
    Its only temporal column is `position_date`, a Glue STRING of free-text 'DD/MM/YYYY' bulletin
    stamps, and `TableSpec.knowledge_col()` would hand that to `_guard`, which emits a LEXICOGRAPHIC
    `CAST(position_date AS varchar) <= '<asof>'`. MEASURED against the canonical parquet: that
    predicate admits 119 of 122 rows at EVERY as-of -- including asof 2015-01-01, at which the
    February-2026 stamps ('01/02/2026' -> '0' < '2') pass while March-2025 stamps ('31/03/2025' ->
    '3' > '2') are dropped. A future row citable at a 2015 as-of is a live PIT leak, and the owner's
    ratification is precisely a ratification of the guard holding.
    This test is the place that has to move first if a producer ever emits a real DATE anchor for it;
    until then, carding it would be undoing a measurement."""
    assert UNICA_RELEASE not in _reg().tables, (
        "silver_unica_biweekly_release_series was carded without a real date anchor -- re-read the "
        "refusal in the tranche header of configs/graphrag/numbers/tables.yaml before removing this")
    from leviathan.silver import reconcile as RC
    assert UNICA_RELEASE not in RC.NUMBERS_TABLES
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert UNICA_RELEASE not in P1_TABLES              # nothing served -> nothing to mirror


def test_no_unica_card_declares_period_required():
    """THE DECISION, PINNED AS A DECISION. `period_required` is calibrated to the WAP trap -- every
    release prints MULTIPLE period rows side by side, so a period-less agg=latest returns ONE row and
    it is the WRONG CROP. That trap cannot arise on any of these three, and the measurement is in the
    test below it: each has a real date axis, so `agg=latest` collapses via ORDER BY <date> DESC
    LIMIT 1, and no date value in any of the three maps to more than one harvest_year. Declaring the
    fence would refuse the season-arc reads these cards exist to serve."""
    reg = _reg()
    opted_in = {t for t, ts in reg.tables.items() if ts.period_required}
    assert opted_in == {"silver_wap_table01_revisions"}, (
        "period_required is still the WAP-only fence; adding a card here needs the wrong-crop "
        "measurement that justified it, not an analogy")


def test_every_unica_card_collapses_latest_to_one_row():
    """The MEASUREMENT behind the pin above, and the structural difference from Tranche 2's three
    dateless cards: those compiled `agg='latest'` to an ascending SERIES (no `_order_col`, no LIMIT 1),
    which is why their notes had to teach that the headline row of such a read is the OLDEST. All
    three cards here have a date axis, so `latest` means what a reader assumes it means."""
    for tid, kw in ((UNICA_HIST, dict(country="centro_sul")),
                    (UNICA_CORN, {}),
                    (UNICA_SALES, {})):
        ts = _reg().get(tid)
        assert Q._order_col(ts) == ts.date_col, tid
        sql = Q.build_sql(Q.NumberQuery(table=tid, metric=sorted(ts.metrics)[0], asof="2026-08-19",
                                        **kw), ts)
        assert sql.endswith("LIMIT 1"), tid
        assert f"ORDER BY {ts.date_col} DESC" in sql, tid


def test_every_unica_card_surfaces_its_bulletin_stamp_on_every_row():
    """THE ONE MECHANICAL DEFENCE THIS FAMILY HAS, pinned on all three at once.

    A minority of rows in each table came out of the parser wrong -- column mis-assignment on three
    season_history bulletins, a pt-BR thousands-separator misparse on two more -- and the defect is
    BULLETIN-SCOPED: every affected row shares a `source_position_date`. The registry offers no
    row-level exclusion (`Metric.row_filters` is keyed by commodity and these cards have no commodity
    column), so `provenance_col` is what turns a prose warning into something checkable ON THE ROW:
    every returned row carries its originating bulletin as the `revision_stamp` alias, and each card's
    notes name the bad stamps. That is a CLASS-1 weak fence by the estate's own doctrine and the
    durable fix is a producer re-parse -- this pin exists so the weak fence cannot silently vanish
    before the strong one lands."""
    for tid in (UNICA_HIST, UNICA_CORN, UNICA_SALES):
        ts = _reg().get(tid)
        assert ts.provenance_col == "source_position_date", tid
        assert ("source_position_date", "revision_stamp") in Q._extras(ts), tid
        sql = Q.build_sql(Q.NumberQuery(table=tid, metric=sorted(ts.metrics)[0], asof="2026-08-19",
                                        **({"country": "centro_sul"} if ts.country_col else {})), ts)
        assert "source_position_date AS revision_stamp" in sql, tid


def test_unica_family_freshness_ceiling_is_not_widened_by_the_cards():
    """THE BANKED CATEGORY ERROR, and this tranche re-earned it on its first card. MEASURED with
    build_catalog before and after: the `unica` family ceiling moved 14 -> 28 the moment
    season_history declared publication_lag_days 14, because that table WAS the family minimum at
    lag 0. publication_lag_days guards the AS-OF axis; FreshnessLagDays measures S3 WRITE recency; the
    unica DAG fires cron(0 12 ? * WED *) and rewrites canonical with --force-overwrite every week
    whatever the content lag. Each pin equals its table's own cadence default -- it cancels the grace
    and arms nothing tighter."""
    from leviathan.silver import dag_catalog as DC
    assert DC.FRESHNESS_LAG_OVERRIDES[UNICA_HIST] == 14        # weekly cadence default
    assert DC.FRESHNESS_LAG_OVERRIDES[UNICA_CORN] == 14        # weekly cadence default
    assert DC.FRESHNESS_LAG_OVERRIDES[UNICA_SALES] == 45       # MONTHLY default, deliberately not 14
    assert DC.build_catalog()["unica"].max_sla_lag_days == 14   # held exactly where it was


def test_unica_cards_columns_resolve_in_the_checked_in_ddl():
    assert cc.check_numbers_schema_pins() == []


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# (1) silver_unica_biweekly_season_history -- the Centro-Sul crush bulletin.
# Beyond the shared pins, this block holds the two properties that are unique to it: the region axis is
# a SUM plus its parts (not three peers), and the metrics are CUMULATIVE (so a cross-season difference
# is nonsense). Both are measured off the canonical parquet, not asserted.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _unica_hist():
    return _reg().get(UNICA_HIST)


def test_unica_hist_card_pit_shape():
    """data_date on the fortnight POSITION date -- a REAL Glue `date` that needed no producer pre-step,
    which is the structural difference from every Tranche-2 card. date_col_type stays "string": the
    column is a Glue `date`, not a TIMESTAMP, so the DP-5 substr normalization does not apply and
    CAST(col AS varchar) is the correct compare on both backends (the sagis week_ending_date idiom)."""
    ts = _unica_hist()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == \
           ("data_date", "fortnight_date", "fortnight_date")
    assert ts.publication_lag_days == 14
    assert ts.date_col_type == "string"                  # NOT "timestamp" -- see the docstring
    assert ts.shape == "wide" and ts.commodity_col is None
    assert ts.country_col == "region"                    # the GEO axis, the fnc-area idiom
    assert (ts.period_col, ts.period_type, ts.period_sql_type) == \
           ("harvest_year", "marketing_year", "string")  # '2025_2026', UNDERSCORE
    assert ts.partition_cols == [] and ts.year_col is None and ts.month_col is None
    assert set(ts.metrics) == {"cane_crushed_t", "sugar_produced_t", "ethanol_total_m3",
                               "ethanol_anhydrous_m3", "ethanol_hydrous_m3"}
    assert not ts.levels_only and not ts.quarantined


def test_unica_hist_declares_its_closed_sugar_set():
    ts = _unica_hist()
    assert list(ts.commodity_values) == ["raw_sugar", "white_sugar"]
    for slug in ts.commodity_values:
        assert slug in ts.notes, f"{slug} is enforced but not taught in the card's notes"


def test_unica_hist_offcard_commodity_is_refused_before_any_sql():
    """The reflex reaches this fence turns into a teaching refusal: corn (because the family's OTHER
    ethanol card is corn-fed) and palm/cocoa/coffee (because this is a tropical-softs neighbourhood)."""
    class _S:
        def __init__(self, table, commodity):
            self.table, self.commodity = table, commodity
    for slug in ("corn_cbot", "campinas_corn_reference_bmf", "malaysian_crude_palm_oil_cme", "cocoa"):
        with pytest.raises(na.CommodityOffCard) as e:
            na._check_commodity_class(_S(UNICA_HIST, slug), _reg())
        assert "raw_sugar" in str(e.value) and "Nothing was queried." in str(e.value)


def test_unica_hist_sql_applies_the_fourteen_day_lag_and_pins_the_region():
    spec = Q.NumberQuery(table=UNICA_HIST, metric="cane_crushed_t", asof="2021-11-01",
                         country="centro_sul")
    sql = Q.build_sql(spec)
    assert "region = 'centro_sul'" in sql
    assert "CAST(fortnight_date AS varchar) <= '2021-10-18'" in sql       # asof - 14d
    assert "ORDER BY fortnight_date DESC" in sql and sql.endswith("LIMIT 1")


def test_unica_hist_oracle_agrees_with_the_guard_at_the_publication_boundary():
    """apply_pit_filter is the pure-Python twin of the SQL guard: the +14d lag must withhold the
    position that is stamped but whose bulletin has not printed, on BOTH sides."""
    ts = _unica_hist()
    rows = [
        {"region": "centro_sul", "fortnight_date": "2026-01-16", "cane_crushed_t": 601_035_365.0},
        {"region": "centro_sul", "fortnight_date": "2026-02-01", "cane_crushed_t": 601_644_297.0},
        {"region": "sao_paulo", "fortnight_date": "2026-01-16", "cane_crushed_t": 341_213_448.0},
    ]
    early = Q.NumberQuery(table=UNICA_HIST, metric="cane_crushed_t", asof="2026-02-10",
                          country="centro_sul")
    assert [r["fortnight_date"] for r in Q.apply_pit_filter(rows, early, ts)] == ["2026-01-16"]
    later = Q.NumberQuery(table=UNICA_HIST, metric="cane_crushed_t", asof="2026-02-15",
                          country="centro_sul")
    assert sorted(r["fortnight_date"] for r in Q.apply_pit_filter(rows, later, ts)) == \
        ["2026-01-16", "2026-02-01"]


def test_unica_hist_notes_state_the_ceiling_and_its_reason():
    """THE TRANCHE-3 PIN. A ceiling the notes do not EXPLAIN produces exactly the answer the owner's
    ratification forbids -- the February reading narrated as the current crush -- because the guard
    returning nothing looks identical to a table that is merely quiet. The tokens below are the four
    things the answer agent needs in order to say WHY the series stops."""
    ts = _unica_hist()
    blob = " ".join((ts.description + " " + ts.notes).lower().split())
    for token in ("2026-02-01",                   # the ceiling itself, as a date
                  "2026/27",                      # the season that has no bulletin
                  "zero parseable bulletins",     # the reason, said out loud
                  "prunes superseded bulletins",  # the MECHANISM behind the reason
                  "not answerable here",          # the instruction, not merely the fact
                  "cumulative",                   # the metrics are season-to-date
                  "centro_sul is the sum",        # the region trap
                  "16/07/2022",                   # a named corrupt bulletin stamp
                  "revision_stamp"):              # ...and how to spot one on a returned row
        assert token in blob, token
    assert "never call a dated reading 'current'" in blob


def test_unica_hist_notes_name_every_measured_bad_bulletin():
    """The defect census, pinned so a notes rewrite cannot quietly drop one. These four stamps are the
    MEASURED bad bulletins: excluding exactly them leaves 252 rows on which
    ethanol_anhydrous + ethanol_hydrous == ethanol_total to a maximum relative error of 0.0, while 43
    of the full table's 300 rows breach that identity by more than 1%."""
    blob = _unica_hist().notes
    for stamp in ("16/07/2022", "01/02/2013", "16/03/2013", "10/16/2025"):
        assert stamp in blob, stamp


def test_unica_hist_card_reconciles_against_the_f010_registry():
    _unica_reconciles(UNICA_HIST)


def test_unica_hist_is_in_the_pg_mirror_list():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert UNICA_HIST in P1_TABLES


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# (2) silver_unica_corn_ethanol -- the OTHER feedstock.
# The property this block holds beyond the shared pins: this card serves a FLOW and a CUMULATIVE side
# by side, which no other card in the estate does, and the two differ by ~19x late in a season.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _unica_corn():
    return _reg().get(UNICA_CORN)


def test_unica_corn_card_pit_shape():
    ts = _unica_corn()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == \
           ("data_date", "fortnight_date", "fortnight_date")
    assert ts.publication_lag_days == 14
    assert ts.date_col_type == "string"
    assert ts.shape == "wide" and ts.commodity_col is None
    assert ts.country_col is None                        # NO region axis -- unlike the cane card
    assert (ts.period_col, ts.period_type, ts.period_sql_type) == \
           ("harvest_year", "marketing_year", "string")
    assert ts.partition_cols == [] and ts.year_col is None
    assert set(ts.metrics) == {"total_quinzenal_kl", "anhydrous_quinzenal_kl", "hydrous_quinzenal_kl",
                               "total_accum_kl", "anhydrous_accum_kl", "hydrous_accum_kl"}
    assert not ts.levels_only and not ts.quarantined


def test_unica_corn_declares_a_corn_only_closed_set():
    """CORN, and the refused slug is the one the PUBLISHER trades in: UNICA is a sugarcane body, so
    raw_sugar is the reflex reach at exactly the card that has no cane in it."""
    ts = _unica_corn()
    assert list(ts.commodity_values) == ["corn_cbot", "campinas_corn_reference_bmf"]
    for slug in ts.commodity_values:
        assert slug in ts.notes


def test_unica_corn_sugar_lookup_is_refused_before_any_sql():
    class _S:
        def __init__(self, table, commodity):
            self.table, self.commodity = table, commodity
    for slug in ("raw_sugar", "white_sugar"):
        with pytest.raises(na.CommodityOffCard) as e:
            na._check_commodity_class(_S(UNICA_CORN, slug), _reg())
        assert "corn_cbot" in str(e.value) and "Nothing was queried." in str(e.value)


def test_unica_corn_card_separates_the_flow_from_the_cumulative_in_both_places():
    """The card's primary hazard, held in CODE where it can be held: every `_quinzenal_` metric's desc
    must say the fortnight alone and every `_accum_` metric's desc must say season-to-date, so the
    distinction survives a notes rewrite. The registry cannot enforce the arithmetic -- only the
    labelling -- so this is the strongest available pin, and the notes carry the rest."""
    ts = _unica_corn()
    for name, m in ts.metrics.items():
        d = m.desc.lower()
        if name.endswith("_quinzenal_kl"):
            assert "in that fortnight alone" in d, name
            assert "not cumulative" in d, name
        else:
            assert "since the season opened" in d or "season-to-date" in d, name
            assert "cumulative" in d, name


def test_unica_corn_sql_applies_the_fourteen_day_lag():
    spec = Q.NumberQuery(table=UNICA_CORN, metric="total_accum_kl", asof="2026-03-15")
    sql = Q.build_sql(spec)
    assert "CAST(fortnight_date AS varchar) <= '2026-03-01'" in sql       # asof - 14d
    assert "ORDER BY fortnight_date DESC" in sql and sql.endswith("LIMIT 1")


def test_unica_corn_notes_state_the_ceiling_the_history_floor_and_the_bad_bulletins():
    ts = _unica_corn()
    blob = " ".join((ts.description + " " + ts.notes).lower().split())
    for token in ("2026-02-01",                   # the ceiling
                  "2026/27",                      # the season with no bulletin
                  "zero parseable bulletins",     # the reason
                  "not answerable here",          # the instruction
                  "2021_2022",                    # the history FLOOR: nothing before 2021/22 exists
                  "09/01/2022", "10/16/2025",     # the two measured bad bulletins
                  "2024-04-01",                   # the year-early date stamp on 2024_2025 position 24
                  "no region axis"):              # must not borrow the cane card's regions
        assert token in blob, token
    assert "never call a dated reading 'current'" in blob


def test_unica_corn_card_reconciles_against_the_f010_registry():
    _unica_reconciles(UNICA_CORN)


def test_unica_corn_is_in_the_pg_mirror_list():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert UNICA_CORN in P1_TABLES


# ════════════════════════════════════════════════════════════════════════════════════════════════════
# (3) silver_unica_monthly_ethanol_sales -- the demand side, and the estate's only TWO-CEILING card.
# The newest ROW the guard admits (2025-11-01) is not the newest row carrying a NUMBER (2024-11-01),
# and the gap between them is the failure mode this block exists to pin.
# ════════════════════════════════════════════════════════════════════════════════════════════════════
def _unica_sales():
    return _reg().get(UNICA_SALES)


def test_unica_sales_card_pit_shape():
    """data_date on month_date, which is a Glue STRING already in ISO 'YYYY-MM-01' form in 58/58 rows
    (probed) -- so the plain CAST-as-varchar compare orders correctly on both backends with no render
    step, and date_col_type stays "string" for the ordinary reason rather than the Glue-date one."""
    ts = _unica_sales()
    assert (ts.knowledge_semantics, ts.knowledge_date_col, ts.date_col) == \
           ("data_date", "month_date", "month_date")
    assert ts.publication_lag_days == 45                 # month end (~30d) + the following bulletin
    assert ts.date_col_type == "string"
    assert ts.shape == "wide" and ts.commodity_col is None and ts.country_col is None
    assert (ts.period_col, ts.period_type, ts.period_sql_type) == \
           ("harvest_year", "marketing_year", "string")
    assert set(ts.metrics) == {"total_current_m3", "total_prior_m3", "internal_current_m3",
                               "internal_prior_m3", "external_current_m3", "external_prior_m3"}
    assert "is_partial" not in ts.metrics                # MEASURED unreliable -- see the test below
    assert not ts.levels_only and not ts.quarantined


def test_unica_sales_excludes_the_unreliable_partial_flag_and_says_why():
    """The mpoc_trade `imports_mt` idiom: a physical column left OFF the card because it is MEASURED
    WRONG, with the verdict recorded in the notes rather than as a silent omission. `is_partial` flags
    exactly ONE row (October 2020) while at least three other part-months are flagged False -- November
    2020 reads 143,814 m3 against a prior-year 2,847,663; October 2021 358,018 against 3,049,853;
    November 2021 240,529 against 2,731,050."""
    ts = _unica_sales()
    assert "is_partial" not in ts.metrics
    blob = ts.notes.lower()
    assert "is_partial is present and is not served" in blob
    assert "143,814" in ts.notes                         # the measured counter-example, not a claim


def test_unica_sales_sql_applies_the_forty_five_day_lag():
    spec = Q.NumberQuery(table=UNICA_SALES, metric="total_current_m3", asof="2025-03-01")
    sql = Q.build_sql(spec)
    assert "CAST(month_date AS varchar) <= '2025-01-15'" in sql           # asof - 45d
    assert "ORDER BY month_date DESC" in sql and sql.endswith("LIMIT 1")


def test_unica_sales_oracle_agrees_with_the_guard():
    ts = _unica_sales()
    rows = [
        {"month_date": "2024-10-01", "total_current_m3": 3_082_621.0},
        {"month_date": "2024-11-01", "total_current_m3": 2_935_757.0},
        {"month_date": "2024-12-01", "total_current_m3": 1.0},   # +45d -> not yet citable
    ]
    # asof chosen at the BOUNDARY: 2024-12-01 + 45d == 2025-01-15, so an asof of 2025-01-10 is the
    # last day on which December is still withheld -- the pin fails if the lag is dropped OR shortened.
    spec = Q.NumberQuery(table=UNICA_SALES, metric="total_current_m3", asof="2025-01-10")
    assert sorted(r["month_date"] for r in Q.apply_pit_filter(rows, spec, ts)) == \
        ["2024-10-01", "2024-11-01"]


def test_unica_sales_notes_state_BOTH_ceilings_and_the_null_is_not_zero_rule():
    """THE PIN THIS CARD EXISTS FOR. `agg=latest` at a 2026 as-of returns the 2025-11-01 row and every
    metric on it is NULL -- so the guard is behaving correctly, a row IS returned, and the only thing
    standing between that and a fabricated zero is what the notes teach. Both ceilings must be stated
    or the answer picks one and is wrong either way."""
    ts = _unica_sales()
    blob = " ".join((ts.description + " " + ts.notes).lower().split())
    for token in ("2025-11-01",                       # the newest ROW the guard admits
                  "2024-11-01",                       # the newest POPULATED month
                  "two different ceilings",           # said as a structure, not left to be inferred
                  "do not present a null row as a zero",
                  "2026/27", "zero parseable bulletins", "not answerable",
                  "only april through november exist",   # the four missing months per season
                  "not answerable for any month after 2013"):   # the export-channel gap
        assert token in blob, token
    assert "never call a dated reading 'current'" in blob


def test_unica_sales_card_reconciles_against_the_f010_registry():
    _unica_reconciles(UNICA_SALES)


def test_unica_sales_is_in_the_pg_mirror_list():
    from jobs.utils.load_pg_numbers import P1_TABLES
    assert UNICA_SALES in P1_TABLES


def test_unica_sales_export_columns_carry_a_measured_floor_not_the_uniform_one():
    """CARDING A TABLE IS WHAT FIRST SUBJECTS ITS METRICS TO A NON-NULL FLOOR, and on this table that
    would have turned the unica family gate red by an act of documentation. value_columns was EMPTY
    before the card, so no floor applied; the card makes it the six-metric set and every one inherits
    the uniform provisional 0.5. MEASURED 2026-08-19 over 58 rows: external_current_m3 and
    external_prior_m3 are each populated in exactly 10 (0.1724), structurally -- the export column was
    only captured for seasons 2012_2013 and 2013_2014. Floor 0.12 is measured-minus-margin (the
    ams-cotton precedent) with headroom for the gate sampler's known undershoot (the D-LD
    nass_crop_progress lesson). The gate stays live: KIND_ALL_NAN still hard-fails an all-null column
    and losing the ten populated rows still trips it."""
    c = _f010(UNICA_SALES)
    assert c["min_nonnull_frac"] == 0.5                    # the table floor is UNCHANGED
    ov = c["min_nonnull_frac_overrides"]
    assert ov == {"external_current_m3": 0.12, "external_prior_m3": 0.12}
    for col in ov:
        assert col in c["value_columns"], "an override key that is not a value_column is orphaned"
    # the four columns that clear the table floor on their own are deliberately NOT pinned down
    assert "internal_current_m3" not in ov                 # 0.6724 measured -- clears 0.5 unaided
