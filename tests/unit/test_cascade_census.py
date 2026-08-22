"""P9-W0/W1/W2.3 unit tests for the cascade-leg census + pin-realizability lint.

pg is MOCKED throughout (a query_fn is injected). Nothing here touches the live mirror, Athena, or any
AWS/eval job. Covers: verdict classification (FIRES / DECLINES-HONESTLY / DARK country-not-a-psd-title /
probe-error), the Athena source tripwire (pg_query used, Q.athena_query_fn NEVER invoked, Q.STATS empty),
and check_pin_realizability (catches a synthetic true-pin-on-unrealizable query; passes the corrected q6
+ the real v4 fixture)."""
from __future__ import annotations

import types

import pytest

from leviathan.graphrag import config_check as cch
from leviathan.graphrag.numbers import cascade_census as cc
from leviathan.graphrag.numbers import query as Q


@pytest.fixture(autouse=True)
def _clean_athena_stats():
    """The census banner's `athena_calls` is `len(Q.STATS)` -- a MODULE GLOBAL any earlier suite in the
    same process can leave residue in (test_numbers_query did: the pairing failed on clean HEAD
    4570ec35 while each file alone passed). Reset on both sides of every test here so this file's
    `athena_calls == 0` assertions count only what THIS test ran, whatever ran before it."""
    Q.reset_stats()
    yield
    Q.reset_stats()


def _drv(driver_id: str, silver_ref: str, region):
    return types.SimpleNamespace(id=driver_id, silver_ref=silver_ref, region=region)


# One synthetic contract carrying one leg of every verdict class. All silver_refs are REAL mapped refs
# (export / stock), so casc.map_row resolves them and the census's real _scope/_region_row run unchanged.
_SYNTH = types.SimpleNamespace(
    contract="test_soy",
    drivers=[
        _drv("fires_leg", "export", "Russia"),        # region resolves -> 'Russia' -> pg has rows -> FIRES
        _drv("declines_leg", "export", "Global"),     # 'Global' is unresolved -> SKIP_NODE -> DECLINES
        _drv("dark_leg", "export", "Ukraine"),        # resolves -> 'Ukraine' NOT a title + 0 rows -> DARK
        _drv("probe_err_leg", "stock", None),         # primary rule; pg raises -> probe-error
    ],
)


class _MockPg:
    """A pg_query stand-in that routes by SQL content. Records every call so the test can assert pg_query
    was the ONLY executor."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, sql: str):
        self.calls.append(sql)
        if "DISTINCT" in sql:
            return [{"v": "Russia"}, {"v": "European Union"}, {"v": "United States"}]   # NO 'Ukraine'
        if "ending_stocks_mt" in sql:
            raise RuntimeError("mirror gap: stock table hiccup")                        # probe-error leg
        if "'Ukraine'" in sql:
            return []                                                                   # dark leg: 0 rows
        return [{"value": "1.0"}]                                                        # fires leg: has rows


@pytest.fixture
def _synth_index(monkeypatch):
    monkeypatch.setattr(cc, "_contract_index", lambda: {"test_soy": _SYNTH})
    # keep the census verdict test hermetic -- the fixture-derived per-query block is exercised elsewhere
    monkeypatch.setattr(cc, "_per_query_realizability", lambda: [])


def test_census_verdict_classification(_synth_index):
    mock = _MockPg()
    art = cc.census(asof="2026-02-15", query_fn=mock)
    verdicts = {leg["node_id"]: leg for leg in art["legs"]}

    assert verdicts["fires_leg"]["verdict"] == cc.FIRES
    assert verdicts["fires_leg"]["country"] == "Russia"
    assert verdicts["fires_leg"]["pg_rows"] == 1

    assert verdicts["declines_leg"]["verdict"] == cc.DECLINES
    assert verdicts["declines_leg"]["reason"] == "region-unresolved"
    assert verdicts["declines_leg"]["country"] is None

    assert verdicts["dark_leg"]["verdict"] == cc.DARK
    assert verdicts["dark_leg"]["reason"] == "country-not-a-psd-title"     # the France->EU class
    assert verdicts["dark_leg"]["country"] == "Ukraine"
    assert verdicts["dark_leg"]["pg_rows"] == 0

    assert verdicts["probe_err_leg"]["verdict"] == cc.PROBE_ERROR
    assert "mirror gap" in verdicts["probe_err_leg"]["reason"]

    b = art["banner"]
    assert (b["fires"], b["declines"], b["dark"], b["probe_errors"]) == (1, 1, 1, 1)
    assert b["athena_calls"] == 0
    assert art["per_contract_has_firing_leg"]["test_soy"] is True         # the FIRES leg lifts the rollup


def test_dark_leg_names_table_not_registered(_synth_index, monkeypatch):
    """A table missing from the numbers registry is its OWN sub-reason (review fold) -- never conflated
    with 'uncertified-table' (registered but certified-empty)."""
    class _Reg:
        def get(self, t):
            raise KeyError(t)

    monkeypatch.setattr(cc, "load_registry", lambda: _Reg())
    art = cc.census(asof="2026-02-15", query_fn=_MockPg())
    verdicts = {leg["node_id"]: leg for leg in art["legs"]}
    assert verdicts["dark_leg"]["verdict"] == cc.DARK
    assert verdicts["dark_leg"]["reason"] == "table-not-registered"       # silver_psd is not in _UNCERTIFIED


def test_census_non_zero_exit_on_unwaived_dark(_synth_index):
    art = cc.census(asof="2026-02-15", query_fn=_MockPg())
    dark = cc._unwaived_dark(art)
    assert [leg["node_id"] for leg in dark] == ["dark_leg"]               # the exit-gate forcing function


def test_waived_leg_declines_and_skips_probe(_synth_index, monkeypatch):
    """A waivered leg (W2.1: the source genuinely has no data) reports DECLINES-HONESTLY without ever
    probing pg, and does not trip the un-waived-dark exit gate."""
    monkeypatch.setitem(cc._WAIVERS, ("test_soy", "dark_leg"), "no data for this (country, metric)")
    mock = _MockPg()
    art = cc.census(asof="2026-02-15", query_fn=mock)
    leg = next(x for x in art["legs"] if x["node_id"] == "dark_leg")
    assert leg["verdict"] == cc.DECLINES and leg["reason"].startswith("waived:")
    assert leg["pg_rows"] is None                                         # waiver short-circuits the probe
    assert cc._unwaived_dark(art) == []                                   # a green census with the waiver
    assert all("'Ukraine'" not in s for s in mock.calls)                  # the dark leg's SQL never ran


def test_census_uses_pg_query_never_athena(_synth_index, monkeypatch):
    """Source tripwire: the census must execute EVERY query through the injected pg_query and NEVER touch
    Q.athena_query_fn -- the plan's positive, observable ZERO-Athena guarantee."""
    athena_calls = []
    monkeypatch.setattr(Q, "athena_query_fn", lambda *a, **k: athena_calls.append(1))
    Q.reset_stats()

    mock = _MockPg()
    cc.census(asof="2026-02-15", query_fn=mock)

    assert mock.calls, "pg_query (the injected query_fn) was never invoked"
    assert athena_calls == [], "Q.athena_query_fn was invoked -- Athena fallback leaked into the census"
    assert Q.STATS == [], "Q.STATS populated -- an Athena query executed"


def test_athena_firewall_blocks_invocation_and_dirty_stats():
    """_athena_firewall makes athena_query_fn raise-on-invoke and hard-fails on a non-empty Q.STATS."""
    orig = Q.athena_query_fn
    with pytest.raises(RuntimeError, match="ATHENA TRIPWIRE"):
        with cc._athena_firewall():
            Q.athena_query_fn()                                          # blocked at the source
    assert Q.athena_query_fn is orig                                     # restored in finally

    with pytest.raises(RuntimeError, match="Q.STATS is non-empty"):
        with cc._athena_firewall():
            Q.STATS.append({"planning_ms": 1})                          # a leaked Athena stat -> hard fail
    Q.reset_stats()


# -- W2.3 check_pin_realizability -------------------------------------------------------------------------
def test_query_realizable_per_query_vs_contract():
    # the grounded biodiesel chain is all unmapped -> per-query FALSE even though the contract rolls up TRUE
    # (re-cut 2026-08-22: soybean_crush_margin became MAPPED by GN-2 W1.3's cbot_board_crush_margin row, so
    #  it can no longer serve as the all-unmapped fixture; oil_share holds the same seat -- its ref
    #  cbot_crush_oil_share is deliberately PLANNED/unmapped, a ratio awaiting its own metric)
    grounded = ["biodiesel_mandate", "RFS", "RIN", "blend_mandate", "crude_oil", "oil_share"]
    q = {"id": "synth_q6", "contract": "soybean_oil_cbot", "cascade_drivers": grounded,
         "expect": {"cascade_fired": True}}
    assert cc.query_realizable(q) is False
    assert cc.contract_can_any_leg_fire("soybean_oil_cbot") is True       # the wrong-granularity greenlight
    # a query that grounds a mapped export leg IS realizable
    assert cc.query_realizable({"contract": "soybean_oil_cbot", "cascade_drivers": ["export_tax"]}) is True
    # no declaration -> UNKNOWN (None), never the contract rollup (fail-closed; review fold, major)
    assert cc.query_realizable({"contract": "soybean_oil_cbot"}) is None


def test_check_pin_realizability_catches_true_pin_and_passes_corrected(monkeypatch):
    grounded = ["biodiesel_mandate", "RFS"]                               # unmapped -> unrealizable per-query
    fixture = {"queries": [
        {"id": "bad_true_pin", "contract": "soybean_oil_cbot", "cascade_drivers": grounded,
         "expect": {"cascade_fired": True}},                             # ERROR: true pin on unrealizable
        {"id": "corrected_q6", "contract": "soybean_oil_cbot", "cascade_drivers": grounded,
         "expect": {"cascade_fired": False}},                            # OK: false pin on unrealizable
        {"id": "fine_true", "contract": "soybean_oil_cbot", "cascade_drivers": ["export_tax"],
         "expect": {"cascade_fired": True}},                             # OK: realizable + true pin
    ]}
    monkeypatch.setattr(cch, "_load", lambda name: fixture)
    errs = cch.check_pin_realizability()
    assert len(errs) == 1
    assert "bad_true_pin" in errs[0] and "cascade_fired:true" in errs[0]


def test_check_pin_realizability_fails_closed_on_undeclared(monkeypatch):
    """The MAJOR review finding: an undeclared cascade_fired pin must ERROR, never silently fall back to
    the contract rollup (which computes TRUE for soybean_oil_cbot and would greenlight the original q6)."""
    fixture = {"queries": [
        {"id": "undeclared_pin", "contract": "soybean_oil_cbot",
         "expect": {"cascade_fired": True}},                             # NO cascade_drivers declared
    ]}
    monkeypatch.setattr(cch, "_load", lambda name: fixture)
    errs = cch.check_pin_realizability()
    assert len(errs) == 1 and "cascade_drivers" in errs[0] and "fail-closed" in errs[0]


def test_check_pin_realizability_catches_stale_negative(monkeypatch):
    fixture = {"queries": [
        {"id": "stale_neg", "contract": "soybean_oil_cbot", "cascade_drivers": ["export_tax"],
         "expect": {"cascade_fired": False}},                            # ERROR: false pin on a fireable leg
    ]}
    monkeypatch.setattr(cch, "_load", lambda name: fixture)
    errs = cch.check_pin_realizability()
    assert len(errs) == 1 and "stale-negative" in errs[0]


def test_real_v4_fixture_pins_are_clean():
    """The shipped fixture (q6 re-pinned to false + cascade_drivers) passes the lint end-to-end."""
    assert cch.check_pin_realizability() == []


# -- RV-W4.2 per-PAIR realizability (Recipe-B World synthesis probe) ---------------------------------------
def _pair(pid, a_slug, b_slug, tier="material"):
    """A minimal complex_map pair matching the interface contract (.id/.pair/.side_a/.side_b/...)."""
    return types.SimpleNamespace(
        id=pid, pair=(a_slug, b_slug), complex_name="veg_oil_complex", shared_event="palm_export_ban",
        side_a={"contract": a_slug, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        side_b={"contract": b_slug, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        direction="opposing", focus_rule="open", materiality_tier=tier)


class _PairPg:
    """pg_query stand-in for the pair probes. Routes by SQL: the per-(country, market_year) era-set query
    (identified by the 'market_year AS y' alias), then the agg=sum World consumption/ending-stock existence
    probes. Order matters -- the era-set SQL ALSO contains 'consumption_mt', so 'market_year AS y' is matched
    FIRST. `year_sets` ({country: [years]}, GAP-capable) takes precedence over `ranges` (contiguous lo..hi,
    kept for the legacy call sites)."""

    def __init__(self, ranges=None, year_sets=None, cons="100", stk="10"):
        self.ranges = ranges if ranges is not None else [{"c": "United States", "lo": 1990, "hi": 2026}]
        self.year_sets = year_sets
        self.cons, self.stk = cons, stk
        self.calls: list[str] = []

    def _year_rows(self):
        if self.year_sets is not None:
            return [{"c": c, "y": y} for c, ys in self.year_sets.items() for y in ys]
        return [{"c": r["c"], "y": y} for r in self.ranges for y in range(int(r["lo"]), int(r["hi"]) + 1)]

    def __call__(self, sql: str):
        self.calls.append(sql)
        if "market_year AS y" in sql:
            return self._year_rows()
        if "consumption_mt" in sql:
            return [] if self.cons is None else [{"value": self.cons}]
        if "ending_stocks_mt" in sql:
            return [] if self.stk is None else [{"value": self.stk}]
        return []


def test_pair_verdict_fires_when_both_legs_synth_and_disjoint():
    p = _pair("veg_oil_soy_palm", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
    rec = cc._pair_verdict(p, asof="2026-02-15", query_fn=_PairPg())
    assert rec["verdict"] == cc.PAIR_FIRES and rec["warn"] is None
    assert rec["slugs"] == ["soybean_oil_cbot", "malaysian_crude_palm_oil_cme"]


def test_pair_verdict_dark_when_world_synth_empty():
    p = _pair("veg_oil_soy_palm", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
    rec = cc._pair_verdict(p, asof="2026-02-15", query_fn=_PairPg(cons=None))   # no world consumption -> empty
    assert rec["verdict"] == cc.PAIR_DARK and rec["reason"].startswith("world-synth-empty")


def test_pair_verdict_dark_and_warns_on_eu_era_overlap():
    """The double-count tripwire: an EU aggregate row whose MY range overlaps a member row -> not-realizable
    + a VISIBLE warn (never silent)."""
    overlap = [{"c": "European Union", "lo": 1999, "hi": 2026}, {"c": "France", "lo": 1975, "hi": 2005}]
    p = _pair("veg_oil_soy_palm", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
    rec = cc._pair_verdict(p, asof="2026-02-15", query_fn=_PairPg(ranges=overlap))
    assert rec["verdict"] == cc.PAIR_DARK and rec["reason"] == "era-overlap"
    assert rec["warn"] and "double-count" in rec["warn"]


def test_pair_verdict_disjoint_eu_ranges_pass():
    disjoint = [{"c": "European Union", "lo": 1999, "hi": 2026}, {"c": "France", "lo": 1975, "hi": 1990}]
    p = _pair("veg_oil_soy_palm", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
    rec = cc._pair_verdict(p, asof="2026-02-15", query_fn=_PairPg(ranges=disjoint))
    assert rec["verdict"] == cc.PAIR_FIRES


def test_pair_verdict_post_brexit_uk_and_accession_states_not_flagged():
    """Regression (adversarial finding 2): the era lint must NOT false-positive on legitimate EU-membership
    CHANGES. Post-Brexit UK is reported separately (2020+) while the EU aggregate (now sans UK) continues, and
    Poland was reported individually BEFORE it joined in 2004 -- neither is double-counted, so the flagship
    pair must FIRE, not go PAIR_DARK. The old min/max RANGE test flagged both (UK's 1964..2026 span overlaps
    EU 1999..2026); the year-set + membership-window fix clears them."""
    ys = {
        "European Union": list(range(1999, 2027)),
        # pre-EEC accession (<1973) + post-Brexit (2020+), with a GAP the range test used to fill in:
        "United Kingdom": list(range(1964, 1973)) + list(range(2020, 2027)),
        "Poland": list(range(1992, 2004)),                       # individual rows BEFORE the 2004 accession
        "United States": list(range(1964, 2027)),
    }
    p = _pair("veg_oil_soy_palm", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
    rec = cc._pair_verdict(p, asof="2026-02-15", query_fn=_PairPg(year_sets=ys))
    assert rec["verdict"] == cc.PAIR_FIRES, rec
    assert rec["warn"] is None


def test_pair_verdict_genuine_double_count_still_flagged():
    """The tripwire must STILL catch a real re-baseline the dedup CANNOT resolve: France (a pre-EU-15 founder
    with NO explicit casc.EU_MEMBERSHIP window -- eu_member_deduped refuses to guess it) reported individually
    in years the aggregate also covers -> those years stay double-counted in the SUM -> PAIR_DARK, fail-closed
    until a window is curated."""
    ys = {"European Union": list(range(1999, 2027)),
          "France": list(range(1999, 2011))}                     # individual 1999-2010 while inside the aggregate
    p = _pair("veg_oil_soy_palm", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
    rec = cc._pair_verdict(p, asof="2026-02-15", query_fn=_PairPg(year_sets=ys))
    assert rec["verdict"] == cc.PAIR_DARK and rec["reason"] == "era-overlap"
    assert rec["warn"] and "double-count" in rec["warn"]
    assert "NO explicit membership window" in rec["warn"]        # names WHY the dedup can't resolve it


def test_pair_verdict_fires_on_backfilled_uk_rows_dedup_resolves_overlap():
    """THE LIVE 2026-07-20 DARK, reproduced exactly: USDA PSD backfills individual 'United Kingdom' rows for
    MY2016-2019 while the EU aggregate for those same MYs still includes the UK (EU-28 until 2020) -- the old
    lint darked ALL 7 curated pairs on this warn ("member 'United Kingdom' reported individually in
    MY[2016-2019] while inside the EU aggregate"). Under the ratified fix the membership window makes the SUM
    disjoint BY CONSTRUCTION (casc.eu_member_deduped excludes UK's individual rows from the World SUM for
    MY2016-2019; from MY2020 -- outside the window -- they count), so the pair must FIRE with NO warn."""
    ys = {
        "European Union": list(range(1999, 2027)),
        "United Kingdom": list(range(2016, 2027)),               # backfilled 2016-2019 + separate post-Brexit 2020+
        "United States": list(range(1964, 2027)),
    }
    p = _pair("veg_oil_soy_palm", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
    rec = cc._pair_verdict(p, asof="2026-02-15", query_fn=_PairPg(year_sets=ys))
    assert rec["verdict"] == cc.PAIR_FIRES, rec
    assert rec["warn"] is None


def test_eu_membership_tables_are_single_source_with_engine():
    """The census aliases must BE the engine's tables (moved to cascade.py so the SUM dedup and the lint read
    one source and cannot drift)."""
    from leviathan.graphrag.numbers import cascade as casc
    assert cc._EU_AGGREGATE_TITLES is casc.EU_AGGREGATE_TITLES
    assert cc._EU_MEMBER_TITLES is casc.EU_MEMBER_TITLES
    assert cc._EU_MEMBERSHIP is casc.EU_MEMBERSHIP
    assert cc._in_eu_aggregate is casc._in_eu_aggregate
    # the dedup rule and the lint agree on the live case: UK deduped 2016-2019, counted from 2020
    assert casc.eu_member_deduped("United Kingdom", 2019, aggregate_present=True) is True
    assert casc.eu_member_deduped("United Kingdom", 2020, aggregate_present=True) is False
    assert casc.eu_member_deduped("United Kingdom", 2019, aggregate_present=False) is False   # no aggregate row
    assert casc.eu_member_deduped("France", 2019, aggregate_present=True) is False            # no curated window


def test_world_synth_probe_sql_sums_per_country_latest_union():
    """Census/engine SEMANTICS COHERENCE (the 2026-07-20 delta-vintage fix): the existence probe's compiled
    SQL must sum the per-country-latest union -- ROW_NUMBER vintage dedup per (slug, country, MY) then SUM
    over the _rn=1 survivors -- with NO lock to any single release_date. PSD vintages are deltas (a release
    carries only revised countries), so a single-vintage lock would probe a revision subset; this is the
    SAME construction the engine's _world_su_ratio computes, so probe and quantify cannot disagree."""
    sql = Q.build_sql(Q.NumberQuery(table="silver_psd", metric="consumption_mt", asof="2026-02-15",
                                    commodity="malaysian_crude_palm_oil_cme", country=None, agg="sum"))
    assert "ROW_NUMBER() OVER (PARTITION BY" in sql              # per-(country x MY) vintage dedup...
    assert "release_date DESC" in sql and "_rn = 1" in sql       # ...keeping each country's OWN latest
    assert "sum(value)" in sql                                   # summed ACROSS the deduped union
    assert "release_date =" not in sql                           # never pinned to one shared vintage


def test_pair_verdict_declines_on_unserved_leg():
    """A leg with no PSD balance sheet DECLINES HONESTLY -- never a DARK bug.

    cocoa is the whole example now: USDA PSD publishes no cocoa sheet at all. FCOJ used to be the
    second member of this set and is NOT one any more -- D-EC XC-7 bound frozen_orange_juice to PSD
    code 585100 on 2026-08-20, so it is a SERVED leg. The assertion below is cocoa-only and always
    was."""
    p = _pair("bad", "soybean_oil_cbot", "cocoa")
    rec = cc._pair_verdict(p, asof="2026-02-15", query_fn=_PairPg())
    assert rec["verdict"] == cc.PAIR_DECLINES and "cocoa" in rec["reason"]


def test_pair_verdict_probe_error_on_pg_raise():
    class _Boom:
        def __call__(self, sql):
            if "market_year AS y" in sql:
                return [{"c": "United States", "y": 2026}]
            raise RuntimeError("mirror gap")
    p = _pair("veg_oil_soy_palm", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
    rec = cc._pair_verdict(p, asof="2026-02-15", query_fn=_Boom())
    assert rec["verdict"] == cc.PROBE_ERROR and "mirror gap" in rec["reason"]


def test_pair_census_and_unwaived_dark_includes_pair_darks(monkeypatch):
    """census() runs the pair pass when a cmap is injected; a DARK pair trips the un-waived-dark exit gate
    alongside dark legs."""
    monkeypatch.setattr(cc, "_contract_index", lambda: {})            # no causal legs -> pair pass only
    monkeypatch.setattr(cc, "_per_query_realizability", lambda: [])
    cm = types.SimpleNamespace(pairs=[_pair("good", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme"),
                                      _pair("bad", "soybean_oil_cbot", "rapeseed_oil_zce")])

    class _Mixed:
        def __call__(self, sql):
            if "market_year AS y" in sql:
                return [{"c": "United States", "y": 2026}]
            if "rapeseed_oil_zce" in sql and "consumption_mt" in sql:
                return []                                             # the 'bad' pair's leg has no world rows
            if "consumption_mt" in sql:
                return [{"value": "100"}]
            if "ending_stocks_mt" in sql:
                return [{"value": "10"}]
            return []

    art = cc.census(asof="2026-02-15", query_fn=_Mixed(), cmap=cm)
    verdicts = {p["pair_id"]: p["verdict"] for p in art["pairs"]}
    assert verdicts == {"good": cc.PAIR_FIRES, "bad": cc.PAIR_DARK}
    assert art["banner"]["pairs_fire"] == 1 and art["banner"]["pairs_dark"] == 1
    dark_ids = [d["pair_id"] for d in cc._unwaived_dark(art) if "pair_id" in d]
    assert dark_ids == ["bad"]


def test_census_no_pairs_when_map_absent(monkeypatch):
    """Byte-identical fence: with lane-A's complex_map absent, the pair pass is a no-op (pairs=[], no pair
    darks) and the legs census is unchanged."""
    monkeypatch.setattr(cc, "_load_complex_map", lambda: None)
    art = cc.census(asof="2026-02-15", query_fn=_MockPg())
    assert art["pairs"] == [] and art["banner"]["pairs_fire"] == 0 and art["banner"]["pairs_dark"] == 0


def test_pair_realizable_public_true_false_none(monkeypatch):
    """The interface-contract predicate: True (FIRES) / False (DARK) / None (pair absent or pg unavailable)."""
    from leviathan.graphrag.numbers import pgnumbers
    cm = types.SimpleNamespace(pairs=[_pair("good", "soybean_oil_cbot", "malaysian_crude_palm_oil_cme")])
    monkeypatch.setattr(cc, "_load_complex_map", lambda: cm)
    monkeypatch.setattr(pgnumbers, "enabled", lambda: True)
    monkeypatch.setattr(pgnumbers, "pg_query", _PairPg())
    cc.pair_realizable.cache_clear()
    assert cc.pair_realizable("good") is True
    assert cc.pair_realizable("no_such_pair") is None                # pair not curated -> fail-closed
    cc.pair_realizable.cache_clear()
    monkeypatch.setattr(pgnumbers, "enabled", lambda: False)          # pg down -> fail-closed None
    assert cc.pair_realizable("good") is None
    cc.pair_realizable.cache_clear()


def test_dark_reason_probes_the_physical_served_table():
    """T2b backfill RCA 2026-07-25: silver_esr serves from silver_esr_compact (ts.athena_table); the
    census DISTINCT probes crashed pg with UndefinedTable because they f-stringed the LOGICAL id. The
    probe must hit the physical name."""
    from types import SimpleNamespace
    from leviathan.graphrag.numbers import cascade_census as cc
    seen = []
    def qfn(sql):
        seen.append(sql)
        return [{"v": "corn_cbot"}]
    ts = SimpleNamespace(country_col=None, commodity_col="commodity_name", athena_table="silver_esr_compact")
    reason = cc._dark_reason("silver_esr", "soybeans_cbot", None, ts, {}, qfn)
    assert reason == "commodity-slug-miss"
    assert seen and "silver_esr_compact" in seen[0] and "FROM" in seen[0]
    assert ".silver_esr " not in seen[0] and not seen[0].rstrip().endswith(".silver_esr")
