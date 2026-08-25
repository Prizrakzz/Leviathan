"""The PSD ATTRIBUTE AXIS at the SERVING seam (projection wave Lane 3 -- L2-4 dispatch, L2-5 engine).

`silver_psd` pivots eight attributes into MT-denominated COLUMNS and drops the rest; the long companion
`silver_psd_attributes` keeps every published line with the metric as a VALUE of an `attribute` column and
the value in USDA's OWN unit. This file covers the serving half of that: the two shape-keyed engine seams
(`_psd_component_rows`, the World synthesis) and the router advertisement that tells the planner the lines
exist at all.

No AWS: every read injects a fake executor and the compiled SQL is asserted from the string it is handed,
so the real fetch_window -> NumberQuery -> build_sql path runs end to end against nothing.

THE BYTE-PARITY LAW THIS FILE ENFORCES (the silver_wasde Title-Case lesson, `tables.yaml:151-154`): a tall
lookup compiles `attribute = '<spelling>'`, so a spelling that is off by one byte returns ZERO ROWS and
reports "not published". Every attribute name serving references is therefore pinned here against the L2-0
census's own label universe -- as a LITERAL, never a read of the artifact, because the artifact is an
untracked measurement bank and CI must fail on a drifted spelling rather than on a missing file.
"""
from __future__ import annotations

import inspect
import types

import pytest
from leviathan.graphrag import dispatch as dp
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R

# ── the census universe, pinned ───────────────────────────────────────────────────────────────────────
# THE ARTIFACT: data/dec_p0/psd_attribute_census.{json,md} (L2-0, generated 2026-08-25) over
# s3://leviathan-dev-shahem-001/bronze/production/source=usda_psd/release_date=2026-08-13/part-000.parquet
# (etag 660f37a2095247b932baad212fe02604) -- 2,092,687 rows, 69 DISTINCT attribute labels, 11 of which the
# wide producer serves. These are those 69 labels, byte-for-byte as USDA prints them, punctuation and
# spacing included ("Rst,Ground Dom. Consum" has no space after the comma and no trailing 'e';
# "Extr. Rate, 999.9999" and "Milling Rate (.9999)" carry their scale hints in the label itself).
_CENSUS_LABELS_20260813 = frozenset({
    'Annual % Change Per Cap. Cons.', 'Arabica Production', 'Area Harvested', 'Bean Exports',
    'Bean Imports', 'Beef Cows Beg. Stocks', 'Beet Sugar Production', 'Beginning Stocks',
    'Calf Slaughter', 'Cane Sugar Production', 'Catch For Reduction', 'Commercial Production',
    'Cow Slaughter', 'Cows In Milk', 'Cows Milk Production', 'Crush', 'Dairy Cows Beg. Stocks',
    'Domestic Consumption', 'Domestic Use', 'Ending Stocks', 'Exports', 'Extr. Rate, 999.9999',
    'FSI Consumption', 'Factory Use Consum.', 'Feed Dom. Consumption', 'Feed Use Dom. Consum.',
    'Feed Waste Dom. Cons.', 'Fluid Use Dom. Consum.', 'Food Use Dom. Cons.', 'For Processing',
    'Fresh Dom. Consumption', 'Human Dom. Consumption', 'Imports', 'Industrial Dom. Cons.',
    'Loss', 'Loss and Residual', 'Milling Rate (.9999)', 'Non-Comm. Production',
    'Other Disappearance', 'Other Milk Production', 'Other Production', 'Production',
    'Raw Exports', 'Raw Imports', 'Refined Exp.(Raw Val)', 'Refined Imp.(Raw Val)',
    'Roast & Ground Exports', 'Roast & Ground Imports', 'Robusta Production',
    'Rough Production', 'Rst,Ground Dom. Consum', 'SME', 'Seed to Lint Ratio',
    'Soluble Dom. Cons.', 'Soluble Exports', 'Soluble Imports', 'Sow Beginning Stocks',
    'Sow Slaughter', 'Stocks-to-Use', 'TY Exports', 'TY Imp. from U.S.', 'TY Imports',
    'Total Disappearance', 'Total Distribution', 'Total Slaughter', 'Total Supply',
    'Total Use', 'Withdrawal From Market', 'Yield',
})

# EVERY attribute spelling the SERVING side names: the cascade legs the L2-5 report proposes for
# china_crush_demand / processing_capacity / us_ethanol_rfs / livestock_feed_demand /
# protein_meal_substitution, and the lines its DE-CONFLATION dispositions turn on (the coffee variety
# split, the sugar raw/refined split, rough_rice_cbot's Rough Production). The legs themselves live in
# cascade_map.yaml, which is owner-applied, so this literal is the ONE place both halves of the wave meet:
# the card the sibling L2-3 change authors must declare these same strings, and the test at the bottom of
# this file cross-checks the two rosters the moment that card registers.
#
# EVERY LABEL BELOW IS SINGLE-UNIT ACROSS THE WHOLE BOOK (census `labels[].units`, measured): '(1000 MT)'
# except the two coffee production lines at '(1000 60 KG BAGS)'. That is a SELECTION CRITERION, not a
# coincidence -- the eight wide-column twins (Production, Exports, Imports, Beginning/Ending Stocks,
# Domestic Consumption, Total Supply, Total Distribution) each span up to SIX units on this axis, and a
# cascade row carries ONE static `scale`, so an attribute-axis leg on one of those would narrate a
# thousandfold error on whichever sheet used the other unit. See the report's parked item.
_LEG_ATTRIBUTES = frozenset({
    'Crush',                    # the crush VOLUME -- processing_capacity / china_crush_demand
    'Feed Dom. Consumption',    # livestock_feed_demand, grain sheets
    'FSI Consumption',          # us_ethanol_rfs -- the combined line the grind hides inside
    'Feed Waste Dom. Cons.',    # protein_meal_substitution, meal sheets
    'Food Use Dom. Cons.',      # the oilseed/oil demand split
    'Industrial Dom. Cons.',    # the oil industrial leg (biodiesel/oleochemical use)
    'TY Exports', 'TY Imports', 'TY Imp. from U.S.',        # the trade-year basis
    'Arabica Production', 'Robusta Production',              # the coffee de-conflation
    'Raw Exports', 'Raw Imports',                            # the sugar de-conflation
    'Refined Exp.(Raw Val)', 'Refined Imp.(Raw Val)',
})

# Attribute lines the DE-CONFLATION DISPOSITIONS turn on but the ratified D-6 roster does NOT declare.
# They are named here so the spellings stay census-checked, and they are DELIBERATELY not asserted
# against the card: a leg that needs one of these first WIDENS the card's declared roster -- a
# deliberate D-6 amendment that moves the pg-mirror footprint (autoscaling is OFF on leviathan-dev-pg),
# never a drive-by. sugar_ethanol_parity's cane half wants the beet/cane split + Human Dom.
# Consumption; the rough_rice_cbot disposition wants Rough Production (each single-unit, measured).
_FUTURE_ADMISSION_ATTRIBUTES = frozenset({
    'Beet Sugar Production', 'Cane Sugar Production',        # sugar_ethanol_parity's cane half
    'Human Dom. Consumption',                                # sugar's food demand, distinct from ethanol
    'Rough Production',                                      # the rough_rice_cbot disposition
})


def test_every_attribute_serving_names_is_a_real_census_label():
    """THE BYTE-PARITY GATE. A spelling serving invents (or fixes a typo in, or Title-Cases) compiles a
    predicate that matches nothing and reports 'not published' -- silently, for as long as nobody probes
    the table. Every name the engine or the proposed legs carry must be a label USDA actually printed."""
    engine = set(cq._PSD_ATTR_OF_COLUMN.values()) | set(cq._PSD_CONSUMPTION_ATTR_BY_SLUG.values())
    stray = sorted((engine | _LEG_ATTRIBUTES | _FUTURE_ADMISSION_ATTRIBUTES) - _CENSUS_LABELS_20260813)
    assert not stray, f"not attribute labels the 2026-08-13 census measured: {stray}"


def test_the_engine_map_is_the_whole_engine_roster():
    """ANTI-VACUITY for the gate above: it only measures what the maps happen to hold today. Pinning the
    map's own contents means a NEW component added to the engine without a census check reds here first."""
    assert set(cq._PSD_ATTR_OF_COLUMN) == {
        "beginning_stocks_mt", "ending_stocks_mt", "production_mt", "exports_mt", "imports_mt",
        "area_harvested_1000ha", "yield_mt_ha", "consumption_mt",
    }, "the wide->attribute map moved -- re-check every new spelling against the census literal above"
    assert set(cq._PSD_CONSUMPTION_ATTR_BY_SLUG) == {
        "raw_sugar", "white_sugar", "cotton", "fresh_citrus",
    }, "the consumption remap moved -- census meta.producer_remap_sources is its source of truth"


def test_the_wide_column_names_are_the_wide_card_s_own():
    """The map's KEYS are silver_psd columns; a key the card does not declare would translate a metric the
    engine can never be asked for, and (worse) would look like coverage."""
    metrics = set(R.load_registry().get(cq._PSD_TABLE).metrics)
    assert set(cq._PSD_ATTR_OF_COLUMN) <= metrics, sorted(set(cq._PSD_ATTR_OF_COLUMN) - metrics)


# ── a registered long companion, so the tall path compiles for real ───────────────────────────────────
_TALL_METRICS = ("Crush", "Ending Stocks", "Domestic Consumption", "Total Disappearance",
                 "Feed Dom. Consumption", "TY Exports")


def _companion_spec() -> R.TableSpec:
    """The long companion's card as L2-3 declares it -- shape tall, metric_col `attribute`, value_col
    `value`, unit_col `unit`, and wasde_release_month INSIDE the grain (silver_wasde shipped without its
    full grain and the latest-vintage ROW_NUMBER collapsed across regions for months). Built here rather
    than read from tables.yaml so these seam tests run BEFORE the card's own change lands and keep running
    if its coverage numbers are re-measured."""
    return R.TableSpec(
        id=cq._PSD_ATTR_TABLE,
        description="USDA PSD long companion -- one row per balance-sheet attribute in its native unit.",
        grain="one row per slug x country x market_year x wasde_release_month x attribute x release_date",
        grain_cols=["leviathan_slug", "country", "market_year", "wasde_release_month", "attribute"],
        shape="tall",
        commodity_col="leviathan_slug",
        country_col="country",
        period_col="market_year",
        period_type="marketing_year",
        period_sql_type="int",
        knowledge_date_col="release_date",
        knowledge_semantics="vintage",
        metric_col="attribute",
        value_col="value",
        unit_col="unit",
        metrics={m: R.Metric(desc=m) for m in _TALL_METRICS},
    )


@pytest.fixture
def companion(monkeypatch):
    """Register the companion on BOTH registry readers the fetch path touches -- cascade's shape lookup and
    query.run's own load. Patching one and not the other is the interesting bug: the engine would spell the
    metric tall while the compiler still resolved the card as wide."""
    live = R.load_registry()
    reg = R.NumbersRegistry(tables={**live.tables, cq._PSD_ATTR_TABLE: _companion_spec()})
    monkeypatch.setattr(cq, "_registry", lambda: reg)
    monkeypatch.setattr(Q, "load_registry", lambda *a, **k: reg)
    return reg


def _capture(rows=()):
    """(qfn, sql_log): a fake executor that banks every compiled statement and replays fixed rows."""
    seen: list[str] = []

    def qfn(sql: str):
        seen.append(sql)
        return [dict(r) for r in rows]
    return qfn, seen


def _row(country, value, rd, unit="(1000 MT)"):
    return {"country": country, "value": value, "knowledge_date": rd, "unit": unit}


# ── seam 1: _psd_component_rows is shape-keyed ────────────────────────────────────────────────────────
def test_the_wide_path_is_unchanged_and_still_names_the_column():
    """Byte-identity of the default call: same table, and the metric is still a COLUMN, not a predicate."""
    qfn, seen = _capture()
    cq._psd_component_rows(qfn, "soybean_oil_cbot", "ending_stocks_mt", 2025, "2026-06-01")
    assert len(seen) == 1
    assert "silver_psd" in seen[0] and "ending_stocks_mt AS value" in seen[0]
    assert "attribute =" not in seen[0]


def test_the_tall_path_compiles_the_attribute_as_a_predicate(companion):
    qfn, seen = _capture([_row("Brazil", 47.0, "2026-05-10")])
    got = cq._psd_component_rows(qfn, "soybeans_cbot", "Crush", 2025, "2026-06-01",
                                 table=cq._PSD_ATTR_TABLE)
    assert len(got) == 1 and got[0]["value"] == 47.0
    assert len(seen) == 1
    sql = seen[0]
    assert "silver_psd_attributes" in sql and "attribute = 'Crush'" in sql
    assert "value AS value" in sql and "unit AS unit" in sql      # the native unit rides every row
    # the grain the card declares IS the latest-vintage partition -- wasde_release_month included, which is
    # the silver_wasde bug (a vintage pick collapsing across release months) not being re-created here.
    assert "PARTITION BY leviathan_slug, country, market_year, wasde_release_month, attribute" in sql


def test_an_undeclared_attribute_declines_BEFORE_any_sql(companion):
    """THE FENCE. `attribute = 'ending_stocks_mt'` is perfectly valid SQL that matches nothing, so a wide
    column name reaching the tall card would return an empty result indistinguishable from 'not published'
    -- exactly the silver_wasde Title-Case failure. It is refused here, and the proof is that the executor
    is never called at all."""
    qfn, seen = _capture([_row("Brazil", 47.0, "2026-05-10")])
    got = cq._psd_component_rows(qfn, "soybeans_cbot", "ending_stocks_mt", 2025, "2026-06-01",
                                 table=cq._PSD_ATTR_TABLE)
    assert got == [] and seen == []


def test_an_unregistered_card_declines_without_raising(monkeypatch):
    """Shape None -- no card answers for the table -- takes NEITHER branch: the compile fails inside
    fetch_window's belt and the leg gets rows=[]. A decline, never an exception out of a leg, and never a
    guess about which spelling the metric should have taken. Forced with a name no card will ever hold, so
    the property is measured whether or not the companion has landed."""
    absent = "silver_psd_attributes_unregistered"
    assert cq._table_shape(absent) is None
    qfn, seen = _capture()
    assert cq._psd_component_rows(qfn, "soybeans_cbot", "Crush", 2025, "2026-06-01", table=absent) == []
    assert seen == []


# ── the consumption component is the one that is not a rename ─────────────────────────────────────────
@pytest.mark.parametrize(("slug", "label"), [
    ("corn_cbot", "Domestic Consumption"),
    ("soybean_oil_cbot", "Domestic Consumption"),
    ("raw_sugar", "Total Disappearance"),
    ("white_sugar", "Total Disappearance"),
    ("cotton", "Domestic Use"),
    ("fresh_citrus", "Fresh Dom. Consumption"),
])
def test_consumption_keeps_usda_s_own_label_per_slug(slug, label):
    """The wide producer normalises four source labels onto one column; the long companion does not,
    because a label spanning four attribute_ids cannot be joined to the source's stable key. A single-string
    swap would compile 'Domestic Consumption' for sugar and return zero rows -- on the DENOMINATOR of the
    World stocks-to-use ratio, which is the one place a zero-row read becomes a missing answer rather than
    a visible one."""
    assert cq._psd_attr_label("consumption_mt", slug) == label


def test_an_attribute_only_component_passes_through_unchanged():
    """A leg may name a line the wide card has no column for at all; translation must not eat it."""
    for name in ("Crush", "TY Exports", "Feed Dom. Consumption"):
        assert cq._psd_attr_label(name, "soybeans_cbot") == name


# ── seam 2: the World synthesis over tall rows ────────────────────────────────────────────────────────
def test_world_sum_carries_the_native_unit_and_the_freshness_stamp():
    rows = [_row("Brazil", 50.0, "2026-05-10"), _row("Argentina", 42.0, "2026-05-12")]
    tot, n, rd, unit = cq._world_sum(rows, 2025)
    assert (tot, n, rd, unit) == (92.0, 2, "2026-05-12", "(1000 MT)")


def test_world_sum_refuses_a_mixed_native_unit_set():
    """The wide table was MT everywhere by construction; the companion is not. Adding a '(1000 MT)' row to
    an '(MT)' row is a manufactured number 1000x wrong, so the set is refused rather than summed."""
    rows = [_row("Brazil", 50.0, "2026-05-10"), _row("Argentina", 42.0, "2026-05-12", unit="(MT)")]
    assert cq._world_sum(rows, 2025) is None


def test_world_sum_on_unitless_wide_rows_is_the_old_arithmetic():
    """silver_psd declares no unit column, so its rows carry no `unit` extra: the guard is inert and the
    returned unit is None -- which is what keeps the wide su_ratio byte-identical."""
    rows = [{"country": "Brazil", "value": 10, "knowledge_date": "2026-05-10"},
            {"country": "Argentina", "value": 6, "knowledge_date": "2026-05-10"}]
    assert cq._world_sum(rows, 2025) == (16.0, 2, "2026-05-10", None)


def test_world_attribute_total_sums_the_per_country_latest_union(companion):
    """The tall World synthesis: one row per country at its OWN latest vintage (PSD releases are DELTAS),
    summed, with the unit riding the total."""
    rows = [_row("Brazil", 50.0, "2026-04-10"), _row("Brazil", 55.0, "2026-05-10"),
            _row("Argentina", 42.0, "2026-05-12"), _row("China", 96.0, "2026-05-12")]
    qfn, seen = _capture(rows)
    got = cq._world_attribute_total(qfn, "soybeans_cbot", "Crush", 2025, "2026-06-01")
    assert got == (193.0, "(1000 MT)", "2026-05-12", 3)          # 55 + 42 + 96, Brazil's April row dropped
    assert "attribute = 'Crush'" in seen[0]


def test_world_attribute_total_dedups_an_eu_member_inside_its_window(companion):
    """The 2026-07-20 UK-backfill fix is arithmetic the two surfaces SHARE (`_world_sum`): the UK's own row
    is excluded for the marketing years it sits inside the EU aggregate, on the attribute axis too."""
    rows = [_row("European Union", 100.0, "2026-05-10"), _row("United Kingdom", 9.0, "2026-05-10"),
            _row("Brazil", 20.0, "2026-05-10")]
    qfn, _ = _capture(rows)
    got = cq._world_attribute_total(qfn, "soybeans_cbot", "Crush", 2019, "2026-06-01")
    assert got == (120.0, "(1000 MT)", "2026-05-10", 2)


def test_world_attribute_total_declines_on_an_undeclared_attribute(companion):
    qfn, seen = _capture([_row("Brazil", 50.0, "2026-05-10")])
    assert cq._world_attribute_total(qfn, "soybeans_cbot", "Rough Production", 2025, "2026-06-01") is None
    assert seen == []


def test_world_attribute_total_declines_on_mixed_units(companion):
    qfn, _ = _capture([_row("Brazil", 50.0, "2026-05-10"),
                       _row("Argentina", 42.0, "2026-05-10", unit="(MT)")])
    assert cq._world_attribute_total(qfn, "soybeans_cbot", "Crush", 2025, "2026-06-01") is None


# ── the World stocks-to-use ratio, computed on the TALL surface ───────────────────────────────────────
def _su_qfn(stocks: list, use: list):
    """A fake executor that answers by which ATTRIBUTE predicate the compiled statement carries."""
    seen: list[str] = []

    def qfn(sql: str):
        seen.append(sql)
        if "attribute = 'Ending Stocks'" in sql:
            return [dict(r) for r in stocks]
        if "attribute = 'Domestic Consumption'" in sql or "attribute = 'Total Disappearance'" in sql:
            return [dict(r) for r in use]
        return []
    return qfn, seen


def test_world_su_ratio_runs_on_the_tall_surface(companion):
    """The same Recipe-B ratio, read off the long companion: both components re-spelled from their wide
    column names by shape, both summed by the shared arithmetic. 16/84 -> 19.047...%."""
    qfn, seen = _su_qfn([_row("United States", 10, "2026-05-10"), _row("Brazil", 6, "2026-05-10")],
                        [_row("United States", 80, "2026-05-10"), _row("Brazil", 4, "2026-05-10")])
    got = cq._world_su_ratio(qfn, "soybean_oil_cbot", 2025, "2026-06-01", table=cq._PSD_ATTR_TABLE)
    assert got is not None
    pct, rd, n = got
    assert pct == pytest.approx(100.0 * 16 / 84, rel=1e-9) and rd == "2026-05-10" and n == 2
    assert any("attribute = 'Ending Stocks'" in s for s in seen)
    assert any("attribute = 'Domestic Consumption'" in s for s in seen)


def test_world_su_ratio_on_the_tall_surface_spells_sugar_s_own_use_label(companion):
    """raw_sugar's use line is 'Total Disappearance' on the companion. Spelling it 'Domestic Consumption'
    would return no denominator and the leg would report the balance sheet as unpublished."""
    qfn, seen = _su_qfn([_row("Brazil", 10, "2026-05-10")], [_row("Brazil", 40, "2026-05-10")])
    got = cq._world_su_ratio(qfn, "raw_sugar", 2025, "2026-06-01", table=cq._PSD_ATTR_TABLE)
    assert got is not None and got[0] == pytest.approx(25.0)
    assert any("attribute = 'Total Disappearance'" in s for s in seen)


def test_world_su_ratio_declines_when_the_two_components_disagree_on_unit(companion):
    """A quotient of a 1000-MT sum over an MT sum is not a stocks-to-use ratio; it is a number 1000x wrong
    that looks entirely plausible as a percent. The leg declines instead."""
    qfn, _ = _su_qfn([_row("Brazil", 10, "2026-05-10")],
                     [_row("Brazil", 40, "2026-05-10", unit="(MT)")])
    assert cq._world_su_ratio(qfn, "soybean_oil_cbot", 2025, "2026-06-01",
                              table=cq._PSD_ATTR_TABLE) is None


# ── the declared-unserved fence is about the SOURCE, not about a shape ────────────────────────────────
def _node(contract, region="Brazil"):
    return types.SimpleNamespace(contract=contract, prior={"region": region})


@pytest.mark.parametrize("table", ["silver_psd", "silver_psd_attributes"])
def test_cocoa_skips_on_both_psd_surfaces(table):
    """USDA publishes no cocoa balance sheet at all, so the companion is exactly as empty of cocoa as the
    wide card. A table-literal fence would have let an attribute-axis cocoa leg fetch its way to the same
    zero rows and the census would have read that as drift rather than as the declared absence it is."""
    _c, country, why = cq._scope_ex(_node("cocoa"), {"table": table, "country_rule": "region"})
    assert country is cq.SKIP_NODE and why == "psd-unserved-slug"


def test_the_fence_still_lets_a_served_slug_through():
    """ANTI-VACUITY: the parametrised skip above would also pass if the fence had swallowed everything."""
    _c, country, why = cq._scope_ex(_node("soybeans_cbot"), {"table": "silver_psd_attributes",
                                                             "country_rule": "region"})
    assert country == "Brazil" and why is None


# ── the card the sibling authors, cross-checked the moment it lands ───────────────────────────────────
def test_the_long_companion_card_agrees_with_this_file_when_it_lands():
    """L2-3 and L2-5 are two changes that must name the SAME strings, and 'byte-for-byte' is not a promise
    a report can keep. While the card is absent this states the honest current position -- the tall path is
    unreachable and every attribute read declines -- and the day the card registers, the assertions below
    start binding without anyone remembering to come back."""
    reg = R.load_registry()
    if cq._PSD_ATTR_TABLE not in reg.tables:
        assert cq._table_shape(cq._PSD_ATTR_TABLE) is None
        return
    ts = reg.get(cq._PSD_ATTR_TABLE)
    assert ts.shape == "tall" and ts.metric_col == "attribute" and ts.value_col == "value"
    assert ts.unit_col, "native units without a unit column is the (1000 HEAD) collision, unguarded"
    # THE LANE-3 REVIEW'S FATAL #1, pinned in the fixed direction: the card declares NO grain_cols,
    # so group_cols() falls back to [slug, country, market_year, attribute] and the latest-vintage
    # ROW_NUMBER actually collapses the ~13 WASDE vintages per marketing year. Declaring the
    # PHYSICAL grain (with wasde_release_month) here would partition the ROW_NUMBER by the table's
    # own uniqueness key -- _rn = 1 filters nothing, every ask fans ~13 vintages. The physical
    # grain lives in the F010 contract's natural_key, where the vintage axis belongs.
    assert not ts.grain_cols, \
        "grain_cols on this card makes the as-of vintage collapse a structural no-op"
    assert ts.group_cols() == ["leviathan_slug", "country", "market_year", "attribute"]
    declared = set(ts.metrics)
    stray = sorted(declared - _CENSUS_LABELS_20260813)
    assert not stray, f"the card declares labels the 2026-08-13 census never measured: {stray}"
    missing = sorted(_LEG_ATTRIBUTES - declared)
    assert not missing, f"the legs reference lines the card does not declare (invisible to serving): {missing}"


# ── L2-4: the router advertisement ────────────────────────────────────────────────────────────────────
# THE TWO-STATE POSTURE (the whitelist fence, Lane-3 review fatal #2): the card is parked behind
# registry.WHITELIST_ABSENT_DEFAULT until the first canonical publish, and the dispatch clause ships
# AT THE FLIP, never before -- a purpose string that advertises a fenced card converts an honest
# decline into a confident mis-route (the arabica-vs-robusta ask would route to the wide card, which
# prints ONE number under three slug names). These tests therefore pin BOTH states: while the card is
# fenced, the clause and its tokens must be ABSENT from the string; the moment it turns visible, every
# ceiling must be present. Neither direction can rot silently.
def _purpose() -> str:
    return next(t.purpose for t in dp.REGISTRY if t.name == "numbers").lower()


def _card_is_visible() -> bool:
    return cq._PSD_ATTR_TABLE in R.load_registry().tables


def test_the_attribute_axis_is_advertised_with_every_ceiling_it_needs():
    """A purpose string is the ONLY capability advertisement the planner reads, and on this axis a
    near-miss reads as a hit: a crush VOLUME quoted as a margin, a trade-year figure netted against a
    marketing-year one, a coffee variety split extended to trade it does not cover. Each ceiling is
    asserted individually so deleting one to shorten the string reds rather than passing. While the
    card is FENCED the clause must be absent -- see the two-state posture above."""
    p = _purpose()
    if not _card_is_visible():
        assert "oilseed crush" not in p, \
            "the attribute-axis clause is advertised while the card is fenced -- a prose route to a table nothing can reach"
        return
    assert "oilseed crush" in p and "volume and never a margin" in p
    assert "no cane crush and no corn grind" in p
    assert "food-seed-industrial" in p and "never a separable figure" in p
    assert "no sheet carries both decompositions" in p
    assert "trade-year basis" in p and "not the marketing" in p
    assert "arabica" in p and "robusta" in p and "production only" in p
    assert "raw-value equivalent" in p or "raw-value" in p
    assert "native unit" in p and "no unit ever summed across" in p


def test_the_advertised_tokens_are_not_free_rides():
    """TOKEN DISCIPLINE (the MINAGRO/BOARD_CRUSH idiom). `crush` alone was already paid for three times
    over and `attribute` free-rides on 'attributed', so either would pass the coverage map while the
    companion stayed dark to the router. The two tokens the coverage entry uses have to be ones no sibling
    clause had already earned. The free-rider facts hold in BOTH states, so they are asserted outside
    the visibility gate -- they are what makes the chosen tokens the only workable ones."""
    p = _purpose()
    # the free-riders, kept here as the record of WHY they were rejected rather than as live tokens
    assert p.count("crush") > 1, "'crush' is shared vocabulary -- it can never identify this table"
    assert "attributed" in p, "'attribute' free-rides on this word; that is why it is not the token"
    if not _card_is_visible():
        return
    for tok in ("oilseed crush", "arabica"):
        assert tok in p, f"{tok!r} is the advertised token and it is not in the string"


def test_the_grind_fence_moved_with_the_axis_and_stayed_true():
    """The citrus law applied to the OTHER standing PSD fence: 'there is no such table for the corn
    ethanol grind' is a routing fence made of prose. While the card is FENCED that sentence is still
    TRUE and must still stand -- nothing serves crush. At the flip, half of it stops being true: the
    corn half survives and says WHY (one combined line), the oilseed half becomes a lookup."""
    flat = " ".join(dp.planner_sys(dp.MAX_CONTRACTS).split())
    if not _card_is_visible():
        assert "no such table for the corn ethanol grind" in flat, \
            "the standing grind fence was edited while the card is still fenced -- the old sentence is still true"
        return
    assert "There is still no MARGIN table for the corn ethanol grind or for rapeseed/canola" in flat
    assert "psd's attribute axis serves the oilseed CRUSH VOLUME itself" in flat
    assert "psd folds corn-for-ethanol into one combined food-seed-industrial figure" in flat
    assert "nothing serves the US grind on its own (unica_corn_ethanol is BRAZILIAN corn ethanol" in flat


def test_the_advertisement_and_the_card_land_together():
    """THE COUPLING, stated where it can be read. The coverage-map entry is INERT for a fenced card
    (test_capability_wiring iterates visible tables only -- the nasa_power precedent), so it lands
    ahead of the flip; the clause does NOT. If the card is visible, the clause's tokens must be in the
    purpose string; if it is fenced, they must not be -- either mismatch is the coupling lost."""
    from tests.unit.test_capability_wiring import _ADVERTISED
    assert cq._PSD_ATTR_TABLE in _ADVERTISED, \
        "the coverage entry is the flip's precondition and it is inert while fenced -- do not remove it"
    toks = _ADVERTISED[cq._PSD_ATTR_TABLE]
    if _card_is_visible():
        assert all(tok in _purpose() for tok in toks)
    else:
        assert not any(tok in _purpose() for tok in toks), \
            "advertised tokens present while the card is fenced -- the clause shipped ahead of the flip"


# ── the seam owns no environment read (SKEPTIC F3) ────────────────────────────────────────────────────
def test_the_attribute_axis_added_no_engine_side_configuration():
    """F3: config enters the engine at the answer.py seam or as a parameter, never as an engine-owned
    environment read. The axis is selected by the registry's declared SHAPE and by a caller's kwarg -- both
    arguments -- so this file's additions could not have introduced one."""
    src = inspect.getsource(cq)
    assert "os.environ" not in src and "import os" not in src
    for fn in (cq._psd_component_rows, cq._world_attribute_total, cq._world_su_ratio, cq._table_shape):
        body = inspect.getsource(fn)
        assert "environ" not in body and "getenv" not in body
