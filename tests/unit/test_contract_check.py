"""SILVER-C002 unit tests for contract_check -- the numbers-stack I1 vocabulary gate.

pg is MOCKED throughout (a query_fn is injected); nothing touches the mirror/Athena/AWS. Covers the four
plan classes: a wide metric-column absent (WASDE Title-Case), a tall metric absent from the DISTINCT set
(drought_z zero-row), a region-resolved country absent from the DISTINCT country set (France->EU), and the
ZERO-Athena-against-projection guarantee (projection trio excluded + never queried). Also asserts the real
numbers registry's wide metrics resolve to real F010 columns (no vacuous pass).

THE CARD_AHEAD_OF_PRODUCER REGISTER (P3 / B2, 2026-09-22) is pinned in the last block: three cases --
REGISTERED-and-inside-its-window becomes a WARNING, everything else (unregistered, expired, unreadable)
stays RED byte-identical, and a caller with no warning sink is HEAD byte for byte. The FAILURE TO FEAR IS
A FALSE GREEN, so every unknown is pinned toward RED; the reviewer's drop-one-at-a-time proof is a pin
here (48 of 51 declared tall metric names RED, exactly the register's 3 WARN) and the warning line is
pinned against the GATE'S OWN attribution parser rather than a copy of it."""
from __future__ import annotations

import types

import pytest
from leviathan.graphrag.numbers import contract_check as cch


# --- tiny synthetic numbers-registry shim (only the attrs the checks read) --------------------------------
def _ts(**kw):
    base = dict(id=None, athena_table=None, shape="tall", metrics={}, metric_col=None,
                commodity_col=None, country_col=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


class _Reg:
    def __init__(self, tables):
        self.tables = tables

    def get(self, tid):
        return self.tables[tid]


class _MockPg:
    """DISTINCT-only pg stand-in routing by (table, column) embedded in the SQL. Records every call so a
    test can assert WHICH tables were queried (the projection-exclusion guarantee)."""

    def __init__(self, distinct):
        self.distinct = distinct          # {(table, col): [values]}
        self.calls: list[str] = []

    def __call__(self, sql: str):
        self.calls.append(sql)
        assert "DISTINCT" in sql, f"contract_check issued a non-DISTINCT query: {sql}"
        for (table, col), vals in self.distinct.items():
            if f"{col} " in sql and table in sql:
                return [{"v": v} for v in vals]
        return []


# ---------------------------------------------------------------------------
# metric vocabulary
# ---------------------------------------------------------------------------
def test_tall_metric_absent_fails_drought_z_class():
    reg = _Reg({"gold_weather_z": _ts(id="gold_weather_z", shape="tall", metric_col="metric",
                                      metrics={"temp_z": None, "precip_z": None, "drought_z": None})})
    pg = _MockPg({("gold_weather_z", "metric"): ["temp_z", "precip_z"]})    # drought_z NOT present
    errs = cch.check_metric_vocabulary(reg, query_fn=pg, column_fn=lambda t: set())
    assert any("drought_z" in e for e in errs), errs
    assert not any("temp_z" in e for e in errs)


def test_wide_metric_column_absent_fails_wasde_titlecase_class():
    # a WIDE table whose declared metric is the Title-Case form while the physical column is snake_case.
    reg = _Reg({"silver_psd": _ts(id="silver_psd", shape="wide",
                                  metrics={"Ending Stocks": None, "production": None})})
    cols = {"production", "ending_stocks", "leviathan_slug", "country"}         # snake_case physical
    errs = cch.check_metric_vocabulary(reg, query_fn=_MockPg({}), column_fn=lambda t: cols)
    assert any("Ending Stocks" in e for e in errs), errs
    assert not any("'production'" in e for e in errs)


def test_healthy_metrics_pass():
    reg = _Reg({
        "silver_wasde": _ts(id="silver_wasde", shape="tall", metric_col="attribute",
                            metrics={"ending_stocks": None, "production": None}),
        "silver_fred_fx": _ts(id="silver_fred_fx", shape="wide", metrics={"brl_usd": None}),
    })
    pg = _MockPg({("silver_wasde", "attribute"): ["ending_stocks", "production", "exports"]})
    errs = cch.check_metric_vocabulary(reg, query_fn=pg, column_fn=lambda t: {"brl_usd", "data_date"})
    assert errs == [], errs


def test_wide_table_never_distinct_queried():
    """A wide table's metric check is a FREE column membership test -- it must issue NO pg query at all."""
    reg = _Reg({"silver_noaa_oni": _ts(id="silver_noaa_oni", shape="wide", metrics={"oni": None})})
    pg = _MockPg({})
    cch.check_metric_vocabulary(reg, query_fn=pg, column_fn=lambda t: {"oni"})
    assert pg.calls == [], "a wide-table metric check must not query the mirror"


# ---------------------------------------------------------------------------
# country vocabulary (France->EU class) -- drive via a mocked leg enumeration
# ---------------------------------------------------------------------------
def _leg(contract, did, table, country, *, country_rule="region", commodity=None):
    row = {"table": table, "metric": "exports", "country_rule": country_rule}
    return (contract, did, row, object(), commodity, country)


def test_region_resolved_country_absent_fails(monkeypatch):
    reg = _Reg({"silver_psd": _ts(id="silver_psd", shape="wide", country_col="country",
                                  commodity_col="leviathan_slug")})
    monkeypatch.setattr(cch, "_mapped_legs",
                        lambda: [_leg("wheat_cbot", "eu_stocks", "silver_psd", "France")])
    pg = _MockPg({("silver_psd", "country"): ["European Union", "United States", "Russia"]})  # NO France
    errs = cch.check_country_vocabulary(reg, query_fn=pg)
    assert any("France" in e for e in errs), errs


def test_region_resolved_country_present_passes(monkeypatch):
    reg = _Reg({"silver_psd": _ts(id="silver_psd", shape="wide", country_col="country")})
    monkeypatch.setattr(cch, "_mapped_legs",
                        lambda: [_leg("wheat_cbot", "ru_export", "silver_psd", "Russia")])
    pg = _MockPg({("silver_psd", "country"): ["Russia", "United States"]})
    assert cch.check_country_vocabulary(reg, query_fn=pg) == []


def test_currency_routed_region_leg_needs_no_country_distinct(monkeypatch):
    """A fred_fx region leg resolves a country for the CURRENCY, but fred_fx has no country_col -> the
    country check must skip it (no DISTINCT), never mislabel it as drift."""
    reg = _Reg({"silver_fred_fx": _ts(id="silver_fred_fx", shape="wide", country_col=None)})
    monkeypatch.setattr(cch, "_mapped_legs",
                        lambda: [_leg("corn_cbot", "fx_leg", "silver_fred_fx", "China")])
    pg = _MockPg({})
    assert cch.check_country_vocabulary(reg, query_fn=pg) == []
    assert pg.calls == []


# ---------------------------------------------------------------------------
# commodity-slug vocabulary (PSD slug-miss class)
# ---------------------------------------------------------------------------
def test_commodity_slug_absent_fails(monkeypatch):
    # robusta_coffee: a slug-miss NOT in cascade.PSD_UNSERVED_SLUGS (cocoa moved there 2026-07-15 --
    # PSD genuinely has no cocoa series, so it is declared-unserved, covered by the dedicated test).
    reg = _Reg({"silver_psd": _ts(id="silver_psd", shape="wide", commodity_col="leviathan_slug")})
    monkeypatch.setattr(cch, "_mapped_legs",
                        lambda: [_leg("robusta_coffee", "grind", "silver_psd", "Ghana",
                                      commodity="robusta_coffee")])
    pg = _MockPg({("silver_psd", "leviathan_slug"): ["corn_cbot", "wheat_cbot"]})  # no robusta
    errs = cch.check_commodity_slug_vocabulary(reg, query_fn=pg)
    assert any("robusta_coffee" in e for e in errs), errs


# ---------------------------------------------------------------------------
# projection exclusion + feature-table exclusion (INV-3 / FR-001 boundary)
# ---------------------------------------------------------------------------
def test_projection_table_excluded_and_never_queried(monkeypatch):
    reg = _Reg({
        "silver_nasa_power": _ts(id="silver_nasa_power", shape="wide", metrics={"t2m": None},
                                 country_col="country", commodity_col="commodity"),
        "silver_psd": _ts(id="silver_psd", shape="wide", metrics={"production": None},
                          country_col="country"),
    })
    assert "silver_nasa_power" not in cch._numbers_table_ids(reg)
    # even a mapped leg pointing at the projection table must issue NO DISTINCT (INV-3)
    monkeypatch.setattr(cch, "_mapped_legs",
                        lambda: [_leg("corn_cbot", "wx", "silver_nasa_power", "United States",
                                      commodity="corn")])
    pg = _MockPg({})
    cch.check_country_vocabulary(reg, query_fn=pg)
    cch.check_commodity_slug_vocabulary(reg, query_fn=pg)
    assert all("silver_nasa_power" not in c for c in pg.calls), pg.calls


def test_feature_only_table_not_in_scope():
    """A features.yaml/feature-only table is NOT in the numbers registry, so C002 never touches it (FR-001
    footer path owns it)."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    ids = cch._numbers_table_ids(reg)
    # NB: silver_icco_cocoa was a feature-only example until the numbers-depth wave wired it into the
    # numbers registry -- dropped; silver_pink_sheet likewise dropped once PRICE_OBSERVABILITY W2 wired it
    # into the numbers registry; silver_cot dropped once PRICE_OBSERVABILITY W4 wired it in (it is now
    # legitimately IN scope -- consumers=both); the rest stay feature-only.
    for feature_only in ("silver_chirps",):
        assert feature_only not in ids
    assert "silver_cot" in ids                                   # W4: now a numbers table, in C002 scope


# ---------------------------------------------------------------------------
# real registry: wide metrics resolve to real F010 columns (guards against a vacuous pass)
# ---------------------------------------------------------------------------
def _tall_distinct_by_physical(reg) -> dict:
    """`(physical_table, metric_col) -> the UNION of every registry table's declared metrics served from
    it` -- which is what a real `SELECT DISTINCT metric FROM <physical>` returns.

    TWO registry tables share one physical table today: `silver_production` and
    `silver_production_livestock` both serve from `silver_production` on metric_col `metric`
    (registry.athena_table), and production code already treats them as one probe -- the DISTINCT cache
    key is `("distinct", phys, metric_col)`, so the second table reuses the first's set. A mock that
    returned the FIRST matching table's metrics instead of the union reported livestock's three metrics
    (`live_animals`, `slaughter_head`, `yield_per_animal`) as drift and left this deck RED at HEAD --
    a mock-ordering artifact, not a vocabulary defect, and exactly the vacuous-red that teaches a reader
    to ignore the check. Keyed by PHYSICAL table, as the production cache is."""
    out: dict = {}
    for tid in cch._numbers_table_ids(reg):
        ts = reg.get(tid)
        if ts.shape == "tall" and ts.metric_col:
            out.setdefault((cch._physical(ts), ts.metric_col), set()).update(ts.metrics)
    return out


def test_real_registry_wide_metrics_resolve_to_f010_columns():
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    by_physical = _tall_distinct_by_physical(reg)

    # mock pg returns each PHYSICAL tall table's union of declared metrics as its DISTINCT set (so only a
    # wide-column MISS could produce an error); column_fn is the real F010 resolver.
    def pg(sql):
        for (phys, mcol), metrics in by_physical.items():
            if f"{mcol} " in sql and phys in sql:
                return [{"v": m} for m in sorted(metrics)]
        return []

    errs = cch.check_metric_vocabulary(reg, query_fn=pg)
    assert errs == [], errs


def test_two_registry_tables_share_one_physical_distinct_probe():
    """The precondition the mock above encodes, asserted rather than assumed: if the collision ever ends,
    this test says so instead of letting the mock quietly become a first-match lookup again."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    shared = [ids for ids in
              {k: [t for t in cch._numbers_table_ids(reg)
                   if reg.get(t).shape == "tall" and reg.get(t).metric_col
                   and (cch._physical(reg.get(t)), reg.get(t).metric_col) == k]
               for k in _tall_distinct_by_physical(reg)}.values() if len(ids) > 1]
    assert shared == [["silver_production", "silver_production_livestock"]], shared


def test_psd_unserved_slugs_are_known_not_drift(monkeypatch):
    """The C002 slug check treats cascade.PSD_UNSERVED_SLUGS as declared-unserved: no drift error
    for cocoa on silver_psd (the runtime SKIPs those legs at _scope), while any OTHER missing slug
    still fails. (frozen_orange_juice was the second member until 2026-08-20, when the PSD widening's
    cloud re-run proved 746 FCOJ rows and it left the fence -- D-EC XC-7.)"""
    import leviathan.graphrag.numbers.contract_check as ck

    legs = [("cocoa", "US_section301_tariffs", {"table": "silver_psd"}, None, "cocoa", "United States"),
            ("wheat", "d1", {"table": "silver_psd"}, None, "unmapped_slug", "United States")]
    monkeypatch.setattr(ck, "_mapped_legs", lambda: legs)

    class _Reg:
        def get(self, tid):
            from leviathan.graphrag.numbers.registry import TableSpec
            return TableSpec(id=tid, description="", shape="wide", commodity_col="leviathan_slug",
                             country_col="country", knowledge_date_col="release_date",
                             knowledge_semantics="vintage")

    calls = []

    def fake_distinct(table, col, query_fn):
        calls.append((table, col))
        return {"corn_cbot", "soybeans_cbot"}

    monkeypatch.setattr(ck.cc, "_distinct_set", fake_distinct)
    errs = ck.check_commodity_slug_vocabulary(_Reg(), query_fn=lambda sql: [])
    assert not any("cocoa" in e for e in errs)         # declared-unserved: silent-known
    assert any("unmapped_slug" in e for e in errs)     # a real miss still fails


def test_cot_unserved_slugs_are_known_not_drift(monkeypatch):
    """The slug check treats cascade.COT_UNSERVED_SLUGS as declared-unserved: no drift error for a
    CFTC-uncovered contract's cot leg on silver_cot (the runtime SKIPs those legs at _scope), while
    any OTHER missing slug still fails. Pins the 2026-08-03 incident class: gate rev 11's first
    Branch-A fire red EVERY family on six not_covered slugs whose cot legs D1 had just made live."""
    import leviathan.graphrag.numbers.contract_check as ck

    legs = [("brazilian_arabica_coffee", "cot_mm_positioning", {"table": "silver_cot"}, None,
             "brazilian_arabica_coffee", None),
            ("french_wheat_matif", "cot_mm_positioning", {"table": "silver_cot"}, None,
             "french_wheat_matif", None),
            ("wheat", "cot_mm_positioning", {"table": "silver_cot"}, None,
             "unmapped_slug", None)]
    monkeypatch.setattr(ck, "_mapped_legs", lambda: legs)

    class _Reg:
        def get(self, tid):
            from leviathan.graphrag.numbers.registry import TableSpec
            return TableSpec(id=tid, description="", shape="wide", commodity_col="leviathan_slug",
                             country_col="country", knowledge_date_col="release_date",
                             knowledge_semantics="vintage")

    def fake_distinct(table, col, query_fn):
        return {"corn_cbot", "arabica_coffee"}          # what silver_cot actually carries

    monkeypatch.setattr(ck.cc, "_distinct_set", fake_distinct)
    errs = ck.check_commodity_slug_vocabulary(_Reg(), query_fn=lambda sql: [])
    assert not any("brazilian_arabica_coffee" in e for e in errs)   # declared-unserved: silent-known
    assert not any("french_wheat_matif" in e for e in errs)
    assert any("unmapped_slug" in e for e in errs)                  # a real miss still fails


def test_cot_unserved_slugs_derive_from_the_yaml_not_covered_list():
    """cascade.COT_UNSERVED_SLUGS IS configs/sources/cftc_cot.yaml `not_covered:` -- the authoritative
    vendor-coverage declaration -- read at first use (D-PR-6), not transcribed. This test re-scans the
    file with its OWN parser rather than calling cascade's, so a bug in `_scan_not_covered` cannot make
    the assertion vacuous. Line-scan, not safe_load: the file's CSV schema block carries `key:{...}` flow
    tokens the YAML scanner rejects, so the whole document does not parse -- the not_covered block itself
    is plain `- slug  # comment` lines."""
    from pathlib import Path

    from leviathan.graphrag.numbers import cascade as casc

    root = Path(__file__).resolve().parents[2]
    text = (root / "configs" / "sources" / "cftc_cot.yaml").read_text(encoding="utf-8")
    slugs, in_block = set(), False
    for line in text.splitlines():
        if line.startswith("not_covered:"):
            in_block = True
            continue
        if in_block:
            stripped = line.strip()
            if stripped.startswith("- "):
                slugs.add(stripped[2:].split("#", 1)[0].strip())
            elif stripped and not stripped.startswith("#"):
                break                                   # next top-level key ends the block
    assert slugs, "not_covered block not found -- the fence lost its authority"
    assert slugs == set(casc.COT_UNSERVED_SLUGS)
    # The module attribute and the accessor are ONE value, not two that happen to agree: the name is
    # served by cascade's PEP-562 __getattr__ hook, so it cannot be an import-time copy while it is
    # absent from the module __dict__. (The staleness properties this implies -- one read per
    # process, re-derivation after cache_clear, fallback on an unreadable file -- are pinned in
    # tests/unit/test_unserved_fence_lint.py:207-251, NOT here.)
    assert set(casc.cot_unserved_slugs()) == slugs
    assert "COT_UNSERVED_SLUGS" not in casc.__dict__, \
        "a module-level copy has appeared -- it would shadow __getattr__ and freeze the fence"


def test_patching_the_cot_fence_moves_both_readers_together(monkeypatch):
    """THE SPLIT-BRAIN SEAM. `COT_UNSERVED_SLUGS` is served by a module `__getattr__`, and a module
    `__getattr__` is NOT consulted for a bare global read inside cascade itself -- so patching the
    module attribute used to move contract_check's reader (`casc.COT_UNSERVED_SLUGS`, contract_check
    .py:197) while `_scope` went on reading the yaml. Measured before the fix: 1 slug for
    contract_check, 18 for `_scope`, same interpreter, same instant. That is a test that passes for
    the wrong reason, and it is one `monkeypatch.setattr` away for the next author fencing a venue --
    this file already patches `ck._mapped_legs` and `ck.cc._distinct_set` in exactly that style."""
    from types import SimpleNamespace

    from leviathan.graphrag.numbers import cascade as casc

    real = set(casc.COT_UNSERVED_SLUGS)
    assert "french_wheat_matif" in real, "fixture assumption: a real fenced venue"

    for patch_target in ("COT_UNSERVED_SLUGS", "_COT_UNSERVED_OVERRIDE"):
        monkeypatch.setattr(casc, patch_target, frozenset({"dutch_barley_matif"}))
        try:
            assert set(casc.COT_UNSERVED_SLUGS) == {"dutch_barley_matif"}, patch_target
            assert set(casc.cot_unserved_slugs()) == {"dutch_barley_matif"}, patch_target
            # ...and the runtime reader agrees: the patched-in venue fences, the real one does not.
            assert casc._scope(SimpleNamespace(contract="dutch_barley_matif"),
                               {"table": "silver_cot"})[1] is casc.SKIP_NODE
            assert casc._scope(SimpleNamespace(contract="french_wheat_matif"),
                               {"table": "silver_cot"})[1] is not casc.SKIP_NODE
        finally:
            monkeypatch.undo()
            casc.reset_cot_fence()
    assert set(casc.COT_UNSERVED_SLUGS) == real
    assert set(casc.cot_unserved_slugs()) == real
    assert "COT_UNSERVED_SLUGS" not in casc.__dict__, \
        "reset_cot_fence must clear the shadow monkeypatch's undo writes into cascade.__dict__"


def test_scope_skips_cot_unserved_leg():
    """_scope returns SKIP_NODE for a silver_cot leg on a CFTC-uncovered contract, so quantify drops
    it (same rendered outcome as the zero-row decline it always produced) and the census records it
    as declines-honestly, never DARK -- which is what keeps the gate's census diff clean."""
    from types import SimpleNamespace

    from leviathan.graphrag.numbers import cascade as casc

    commodity, country = casc._scope(SimpleNamespace(contract="brazilian_arabica_coffee"),
                                     {"table": "silver_cot"})
    assert commodity == "brazilian_arabica_coffee"
    assert country is casc.SKIP_NODE
    # a covered contract keeps its normal scoping path
    commodity, country = casc._scope(SimpleNamespace(contract="cotton"),
                                     {"table": "silver_cot", "country_rule": "none"})
    assert (commodity, country) == ("cotton", None)


# ---------------------------------------------------------------------------
# CARD_AHEAD_OF_PRODUCER (P3 / B2, 2026-09-22) -- the declared, dated, EXPIRING register.
#
# THE INCIDENT. f2aabf90 (2026-09-15) declared three preliminary-stamp metrics on gold_weather_z
# (configs/graphrag/numbers/tables.yaml:1221-1223). Their rows can only reach the pg mirror through a
# canonical silver_chirps promote, and the only writer of canonical silver_chirps is the promote the
# resulting RED blocks. Measured: six consecutive weather SFN FAILs 2026-09-17..22
# ("FAIL gold_weather_z (branch A): contract_check=3 vocab drift(s)"), chirps/cpc/nasa frozen at
# 2026-09-16 against a 3-day ceiling, drought_z stuck at 2026-07.
#
# THE RULE (round 3). Round 2 graded on the metric's ALL-TIME COUNT(*), and that was the DISTINCT probe
# RESTATED -- DISTINCT(col) IS the set of values with >= 1 row, so its RED branch was dead code (measured
# on a consistent mirror over the real registry: HEAD reds 51 of 51 dropped metrics, round 2 reds 0).
# The warrant is now a DECLARATION -- dated, argued per entry, in cascade_census._WAIVERS' own shape:
#     REGISTERED and today <= declared + PENDING_WINDOW_DAYS -> WARN / global_drift
#     not registered, or the window has passed               -> RED, HEAD's words byte for byte
#     the entry cannot be read (bad date/shape/reason)       -> RED, fail-closed, naming the class
# A false GREEN is the failure to fear, so every unknown resolves to RED -- and the yellow DIES BY
# ITSELF, which is the property an all-time count could never have.
# ---------------------------------------------------------------------------
_PRELIM = ("drought_z_is_preliminary", "drought_z_preliminary_share", "drought_z_is_preliminary_cells")
_WHY = "a test justification"


class _Mirror:
    """A pg stand-in that answers the DISTINCT vocabulary probe and ASSERTS THAT NOTHING ELSE IS EVER
    ASKED. The register grade issues no SQL, so any statement other than a DISTINCT reaching this mock is
    a regression toward the round-2 design and fails the test that is running."""

    def __init__(self, distinct):
        self.distinct = distinct          # {(table, col): [values]}
        self.calls: list[str] = []

    def __call__(self, sql: str):
        self.calls.append(sql)
        assert sql.startswith("SELECT DISTINCT"), f"the grade must issue no query; got: {sql}"
        for (table, col), vals in self.distinct.items():
            if f"{col} " in sql and table in sql:
                return [{"v": v} for v in vals]
        return []


def _weather_reg(metrics=("drought_z", "heat_stress_z") + _PRELIM):
    return _Reg({"gold_weather_z": _ts(id="gold_weather_z", shape="tall", metric_col="metric",
                                       metrics={m: None for m in metrics})})


def _register(monkeypatch, entries):
    """Swap the whole register for the duration of one test -- never mutate the shipped dict in place."""
    monkeypatch.setattr(cch, "CARD_AHEAD_OF_PRODUCER", dict(entries))


def _clock(monkeypatch, y, m, d):
    from datetime import date
    monkeypatch.setattr(cch, "_today", lambda: date(y, m, d))


def _tall(errs):
    """The TALL declared-but-zero-row lines only. On the REAL registry a `column_fn` returning nothing
    makes every WIDE metric an error too, and those lines are not what the register grades."""
    return [e for e in errs if "not in DISTINCT" in e]


# --- THE PIN SPEC, driven straight on the grade contract ---------------------------------------------
def test_the_grade_contract_is_registered_warn_unregistered_red_expired_red(monkeypatch):
    """THE WHOLE RULE, on the register alone with an EXPLICIT today and nothing else in the loop.

    Registered and inside the window -> WARN. The SAME entry one day past its window -> RED. A name
    nobody registered -> RED however long it has been absent. The suffix on a RED is EMPTY, so the error
    string is HEAD's byte for byte; the suffix on a WARN names the declaration, the reason and the day
    the yellow dies."""
    from datetime import date
    _register(monkeypatch, {("gold_weather_z", "drought_z_is_preliminary"): ("2026-09-15", _WHY)})

    g = cch.grade_zero_row_metrics("gold_weather_z", ["drought_z_is_preliminary"],
                                   today=date(2026, 9, 22))
    grade, suffix, reason = g["drought_z_is_preliminary"]
    assert grade == cch.GRADE_WARN, g
    assert "2026-09-15" in suffix and _WHY in suffix and "2026-10-30" in suffix, suffix
    assert reason == "registered 2026-09-15, expires 2026-10-30", reason

    # the last day inside the window is still yellow; the day after is red. 45 days, both sides pinned.
    last = cch.grade_zero_row_metrics("gold_weather_z", ["drought_z_is_preliminary"],
                                      today=date(2026, 10, 30))["drought_z_is_preliminary"]
    assert last[0] == cch.GRADE_WARN, last
    expired = cch.grade_zero_row_metrics("gold_weather_z", ["drought_z_is_preliminary"],
                                         today=date(2026, 10, 31))["drought_z_is_preliminary"]
    assert expired[0] == cch.GRADE_RED and expired[1] == "", expired
    assert "EXPIRED 2026-10-30" in expired[2], expired

    # never registered -> RED, empty suffix, on any date
    unreg = cch.grade_zero_row_metrics("gold_weather_z", ["drought_z"], today=date(2026, 9, 22))
    assert unreg["drought_z"] == (cch.GRADE_RED, "", "NOT REGISTERED"), unreg

    # the register is keyed by (card, metric): the right metric on the WRONG card is not registered
    other = cch.grade_zero_row_metrics("silver_wasde", ["drought_z_is_preliminary"],
                                       today=date(2026, 9, 22))
    assert other["drought_z_is_preliminary"][0] == cch.GRADE_RED, other


@pytest.mark.parametrize("entry", [
    ("not-a-date", _WHY),                      # a date nobody can parse
    ("2026-13-45", _WHY),                      # a date-shaped string that is not a day
    ("2026-09-15", "   "),                     # a declaration with no argument behind it
    ("2026-09-15",),                           # the wrong shape entirely
    "2026-09-15",                              # a bare string where a pair belongs
])
def test_an_unreadable_register_entry_is_red_and_says_why(entry, monkeypatch):
    """AN ENTRY NOBODY CAN READ IS AN UNKNOWN, and every unknown here resolves toward RED. It is not
    red-by-luck through the not-registered branch: the failure CLASS is named in the line, so the next
    operator repairs the register instead of hunting a producer that was never the problem."""
    _register(monkeypatch, {("gold_weather_z", "m1"): entry})
    g = cch.grade_zero_row_metrics("gold_weather_z", ["m1"])
    grade, suffix, reason = g["m1"]
    assert grade == cch.GRADE_RED, g
    assert cch.UNREADABLE_NOTE in suffix and "unreadable" in reason, (suffix, reason)


# --- case 1: a REGISTERED metric -> WARNING, and the ERROR list goes empty ----------------------------
def test_a_registered_metric_grades_warn_not_red():
    """THE SHIPPED REGISTER ON THE SHIPPED CLOCK: today the three preliminary stamps clear the weather
    gate. No monkeypatch anywhere in this test -- when the window expires this test goes red, and that
    red IS the reminder. That is the design, not a fragility."""
    reg = _weather_reg()
    pg = _Mirror({("gold_weather_z", "metric"): ["drought_z", "heat_stress_z"]})  # the three PRELIM absent
    warns: list = []
    errs = cch.check_metric_vocabulary(reg, query_fn=pg, column_fn=lambda t: set(), warnings=warns)
    assert errs == [], errs
    assert len(warns) == 3, warns
    for m in _PRELIM:
        assert any(repr(m) in w for w in warns), (m, warns)
    assert len(pg.calls) == 1, "one DISTINCT probe and not one statement more"


def test_the_warning_keeps_the_whole_head_text_and_only_appends(monkeypatch):
    """A fence CORRECTS or COMPUTES, never deletes: the warning line is HEAD's error string plus a
    bracketed note naming the declaration that decided it, so nothing a reader had before is lost."""
    _register(monkeypatch, {("gold_weather_z", "drought_z_is_preliminary"): ("2026-09-15", _WHY)})
    _clock(monkeypatch, 2026, 9, 22)
    reg = _weather_reg(metrics=("drought_z", "drought_z_is_preliminary"))
    d = {("gold_weather_z", "metric"): ["drought_z"]}
    head = cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set())
    assert len(head) == 1
    warns: list = []
    errs = cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set(),
                                       warnings=warns)
    assert errs == []
    assert warns[0].startswith(head[0]), (warns[0], head[0])
    assert warns[0] == head[0] + " [" + cch.REGISTERED_NOTE.format(
        declared="2026-09-15", why=_WHY, expires="2026-10-30") + "]"


# --- case 2: UNREGISTERED -> RED, byte-identical to HEAD ---------------------------------------------
def test_an_unregistered_zero_row_metric_keeps_the_red_byte_identical(monkeypatch):
    """THE CLASS ROUND 2 LOST. A declared tall metric that stops reaching the mirror -- a producer
    regression, a partial load, a loader filter -- is in nobody's register, so it keeps stopping the
    promote with the SAME error string HEAD printed. Not 'also red': BYTE-IDENTICAL."""
    _register(monkeypatch, {("gold_weather_z", "drought_z_is_preliminary"): ("2026-09-15", _WHY)})
    _clock(monkeypatch, 2026, 9, 22)
    reg = _weather_reg(metrics=("drought_z", "heat_stress_z"))
    d = {("gold_weather_z", "metric"): ["heat_stress_z"]}                       # drought_z has vanished
    head = cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set())
    warns: list = []
    graded = cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set(),
                                         warnings=warns)
    assert graded == head, (graded, head)          # byte-identical, not merely "also red"
    assert warns == []


def test_an_expired_registration_reds_byte_identically_to_head(monkeypatch):
    """THE YELLOW DIES BY ITSELF. The same three entries, read one day past their window, red the gate
    with HEAD's exact strings. This is the property the round-1 baseline could not have (age made it
    SAFER-looking) and the round-2 count could not have (there was no age at all)."""
    from datetime import date, timedelta
    _register(monkeypatch, {("gold_weather_z", m): ("2026-09-15", _WHY) for m in _PRELIM})
    reg = _weather_reg()
    d = {("gold_weather_z", "metric"): ["drought_z", "heat_stress_z"]}
    head = cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set())

    monkeypatch.setattr(cch, "_today",
                        lambda: date(2026, 9, 15) + timedelta(days=cch.PENDING_WINDOW_DAYS))
    warns: list = []
    last_day = cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set(),
                                           warnings=warns)
    assert last_day == [] and len(warns) == 3, (last_day, warns)       # the last yellow day

    monkeypatch.setattr(cch, "_today",
                        lambda: date(2026, 9, 15) + timedelta(days=cch.PENDING_WINDOW_DAYS + 1))
    warns = []
    errs = cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set(),
                                       warnings=warns)
    assert errs == head, (errs, head)
    assert warns == []


def test_no_warning_sink_means_head_verdict_and_the_same_statements(monkeypatch):
    """The grade can only move a finding INTO a list the caller asked for, and it never runs for a caller
    that did not ask. jobs/audit/feature_readiness.py calls the family checks with no sink and gets HEAD
    exactly -- correct for a readiness probe ("the card is ahead" is what a readiness report should say).
    AND the two modes issue THE SAME STATEMENTS, character for character: the register costs no query,
    which is what makes this wave invisible to pg."""
    _register(monkeypatch, {("gold_weather_z", m): ("2026-09-15", _WHY) for m in _PRELIM})
    _clock(monkeypatch, 2026, 9, 22)
    reg = _weather_reg()
    d = {("gold_weather_z", "metric"): ["drought_z", "heat_stress_z"]}
    ungraded_pg, graded_pg = _Mirror(d), _Mirror(d)
    ungraded = cch.check_metric_vocabulary(reg, query_fn=ungraded_pg, column_fn=lambda t: set())
    warns: list = []
    cch.check_metric_vocabulary(reg, query_fn=graded_pg, column_fn=lambda t: set(), warnings=warns)
    assert len(ungraded) == 3 and len(warns) == 3
    assert graded_pg.calls == ungraded_pg.calls, (graded_pg.calls, ungraded_pg.calls)


def test_the_grade_issues_no_sql_on_the_real_registry_in_either_mode():
    """THE STATEMENT SET IS HEAD'S, measured on the REAL registry with EVERY declared tall metric absent
    at once -- the state no mirror has ever been in, and the state round 2 costed at 5 extra grouped
    counts per walk and 46 per full day of schedules. The register reads a dict in this module: the
    marginal cost is ZERO queries, for the ungraded caller and for the gate alike."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    by_physical = _tall_distinct_by_physical(reg)
    empty = {k: [] for k in by_physical}
    ungraded_pg, graded_pg = _Mirror(empty), _Mirror(empty)
    head = _tall(cch.check_metric_vocabulary(reg, query_fn=ungraded_pg, column_fn=lambda t: set()))
    warns: list = []
    graded = _tall(cch.check_metric_vocabulary(reg, query_fn=graded_pg, column_fn=lambda t: set(),
                                               warnings=warns))
    declared = sum(len(reg.get(t).metrics) for t in cch._numbers_table_ids(reg)
                   if reg.get(t).shape == "tall" and reg.get(t).metric_col)
    print(f"\nGRADE COST: {declared} declared tall metrics, EVERY ONE absent -> "
          f"{len(graded_pg.calls) - len(ungraded_pg.calls)} extra quer(ies); "
          f"{len(graded)} RED, {len(warns)} WARN")
    assert graded_pg.calls == ungraded_pg.calls
    assert len(graded) + len(warns) == len(head) == declared
    assert len(warns) == len(cch.CARD_AHEAD_OF_PRODUCER), "only the register may soften a line"


# --- the grade is confined to the TALL declared-but-zero-row family ----------------------------------
def test_the_grade_never_reaches_the_wide_country_or_slug_families(monkeypatch):
    reg = _Reg({"silver_psd": _ts(id="silver_psd", shape="wide", country_col="country",
                                  commodity_col="leviathan_slug",
                                  metrics={"Ending Stocks": None})})
    monkeypatch.setattr(cch, "_mapped_legs",
                        lambda: [_leg("wheat_cbot", "eu_stocks", "silver_psd", "France",
                                      commodity="unmapped_slug")])
    # even if somebody registered those names, the grade must never be consulted for them
    _register(monkeypatch, {("silver_psd", "Ending Stocks"): ("2026-09-15", _WHY),
                            ("silver_psd", "France"): ("2026-09-15", _WHY),
                            ("silver_psd", "unmapped_slug"): ("2026-09-15", _WHY)})
    pg = _Mirror({("silver_psd", "country"): ["European Union"],
                  ("silver_psd", "leviathan_slug"): ["corn_cbot"]})
    warns: list = []
    errs = cch.contract_check(reg, query_fn=pg, column_fn=lambda t: {"country"}, warnings=warns)
    assert warns == [], "only the tall declared-but-zero-row family is graded"
    assert any("Ending Stocks" in e for e in errs)          # wide metric column: RED as ever
    assert any("France" in e for e in errs)                 # France->EU: RED as ever
    assert any("unmapped_slug" in e for e in errs)          # slug miss: RED as ever


def test_contract_check_ex_returns_both_lists():
    reg = _weather_reg()
    d = {("gold_weather_z", "metric"): ["drought_z", "heat_stress_z"]}
    errs, warns = cch.contract_check_ex(reg, query_fn=_Mirror(d), column_fn=lambda t: set())
    assert errs == [] and len(warns) == 3
    # ...and the ungraded one-list form is HEAD: the same three lines, graded differently.
    ungraded = cch.contract_check(reg, query_fn=_Mirror(d), column_fn=lambda t: set())
    assert ungraded == [w[:w.rindex(" [")] for w in warns]


# --- the warning must survive the GATE'S OWN attribution parser --------------------------------------
def test_the_warning_attributes_to_exactly_the_tables_head_did(monkeypatch):
    """THE SUFFIX IS A PARSER HAZARD, so it is pinned against the REAL parser, not a copy of it.
    silver_rebuild_gate.implicated_tables reads every `of <lowercase_token>` as an implicated TABLE and
    treats an UNATTRIBUTABLE error as RED for every family. A note reading '...ahead of its producer'
    would have entered `its` into the attribution set, and the gate would have redded all 28 families on
    the very line this wave exists to stop redding one. Both suffixes are pinned, the warn and the
    fail-closed red, because both reach the same parser -- and so is every JUSTIFICATION the SHIPPED
    register carries, because a reason is prose a human writes and prose is where `of` lives."""
    from jobs.audit.silver_rebuild_gate import implicated_tables

    reg = _weather_reg(metrics=("drought_z", "drought_z_is_preliminary"))
    d = {("gold_weather_z", "metric"): ["drought_z"]}
    head = cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set())
    warns: list = []
    cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set(), warnings=warns)
    assert implicated_tables(warns[0]) == implicated_tables(head[0]) == frozenset({"gold_weather_z"})

    for note in (cch.REGISTERED_NOTE, cch.UNREADABLE_NOTE):
        assert " of " not in note, "the note must not mint a phantom table token"
    for (_tid, _metric), entry in cch.CARD_AHEAD_OF_PRODUCER.items():
        assert " of " not in entry[1], f"a justification must not mint a phantom table token: {entry!r}"

    _register(monkeypatch, {("gold_weather_z", "drought_z_is_preliminary"): ("bad", _WHY)})
    unread: list = []
    reds = cch.check_metric_vocabulary(reg, query_fn=_Mirror(d), column_fn=lambda t: set(),
                                       warnings=unread)
    assert unread == [] and len(reds) == 1, (reds, unread)
    assert implicated_tables(reds[0]) == frozenset({"gold_weather_z"}), reds


# --- the register is keyed by the CARD, and two cards share one physical -----------------------------
def test_the_register_is_keyed_by_the_card_not_the_physical(monkeypatch):
    """silver_production and silver_production_livestock BOTH serve from the physical silver_production on
    metric_col `metric`, and they share the DISTINCT probe. A declaration belongs to the CARD that made
    it, so registering a name on one card must not soften the other card's line -- otherwise one team's
    argued yellow would silently cover a second team's regression."""
    reg = _Reg({"silver_production": _ts(id="silver_production", shape="tall", metric_col="metric",
                                         metrics={"shared_metric": None}),
                "silver_production_livestock": _ts(id="silver_production_livestock",
                                                   athena_table="silver_production", shape="tall",
                                                   metric_col="metric",
                                                   metrics={"shared_metric": None})})
    _register(monkeypatch, {("silver_production", "shared_metric"): ("2026-09-15", _WHY)})
    _clock(monkeypatch, 2026, 9, 22)
    warns: list = []
    errs = cch.check_metric_vocabulary(reg, query_fn=_Mirror({("silver_production", "metric"): []}),
                                       column_fn=lambda t: set(), warnings=warns)
    assert len(warns) == 1 and warns[0].startswith("silver_production: "), warns
    assert len(errs) == 1 and errs[0].startswith("silver_production_livestock: "), errs


def test_the_grade_ledger_records_the_register_fact_per_metric(monkeypatch):
    """The gate PRINTS this ledger, so the reason a line was yellow -- or red -- survives in a container
    log without a git checkout. Emission order; a caller with no caches gets an empty list."""
    _register(monkeypatch, {("gold_weather_z", "drought_z_is_preliminary"): ("2026-09-15", _WHY)})
    _clock(monkeypatch, 2026, 9, 22)
    reg = _weather_reg()
    caches: dict = {}
    warns: list = []
    cch.check_metric_vocabulary(reg, query_fn=_Mirror({("gold_weather_z", "metric"): ["drought_z"]}),
                                column_fn=lambda t: set(), caches=caches, warnings=warns)
    ledger = cch.grade_ledger(caches)
    assert [(t, m, g) for t, m, g, _r in ledger] == [
        ("gold_weather_z", "heat_stress_z", cch.GRADE_RED),
        ("gold_weather_z", "drought_z_is_preliminary", cch.GRADE_WARN),
        ("gold_weather_z", "drought_z_preliminary_share", cch.GRADE_RED),
        ("gold_weather_z", "drought_z_is_preliminary_cells", cch.GRADE_RED),
    ], ledger
    assert ledger[0][3] == "NOT REGISTERED", ledger[0]
    assert ledger[1][3] == "registered 2026-09-15, expires 2026-10-30", ledger[1]
    assert cch.grade_ledger(None) == [] and cch.grade_ledger({}) == []


# --- THE REVIEWER'S FATAL, AS A DECK PIN --------------------------------------------------------------
def test_every_declared_tall_metric_the_register_does_not_name_reds_the_gate():
    """THE FATAL ROUND 2 SHIPPED, TURNED INTO A PIN. Round 2's grade could not red ANY of the 51 declared
    tall metric names: dropping each one alone from a CONSISTENT mirror (one store answering both the
    DISTINCT probe and its all-time count, which is the only state postgres can occupy) graded all 51
    WARN, `drought_z` -- the weather family's flagship -- included, so the family would have promoted
    canonical with a green gate.

    On the register, drop-one-at-a-time over the REAL registry must red every name the register does not
    hold, and warn EXACTLY the names it does. Prints both numbers so the fix report quotes this test's
    output rather than a claim standing beside it."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    by_physical = _tall_distinct_by_physical(reg)
    all_names = sorted({m for v in by_physical.values() for m in v})
    registered = {m for _t, m in cch.CARD_AHEAD_OF_PRODUCER}
    reds, warned = [], []
    for name in all_names:
        pg = _Mirror({k: sorted(v - {name}) for k, v in by_physical.items()})
        sink: list = []
        errs = _tall(cch.check_metric_vocabulary(reg, query_fn=pg, column_fn=lambda t: set(),
                                                 warnings=sink))
        (reds if errs else warned).append(name)
        assert errs or sink, name
    print(f"\nDROP-ONE OVER THE REAL REGISTRY: {len(all_names)} declared tall metric name(s) -> "
          f"RED {len(reds)}, WARN-only {len(warned)} (register holds {len(registered)})")
    assert set(warned) == registered, (sorted(set(warned) ^ registered))
    assert len(reds) == len(all_names) - len(registered) == 48, (len(reds), len(all_names))


# --- the shipped register itself ----------------------------------------------------------------------
def test_every_register_entry_is_readable_dated_and_argued():
    """THE `_WAIVERS` DISCIPLINE, APPLIED TO THE REGISTER. Every entry parses, carries a justification,
    was declared in the PAST (a future date would buy a longer window by typo), and is still inside its
    window TODAY -- because an entry past its window is a red the gate is already serving and a line
    somebody owes a decision on."""
    assert cch.PENDING_WINDOW_DAYS == 45
    today = cch._today()
    assert cch.CARD_AHEAD_OF_PRODUCER, "an empty register is legal; delete this assert when it empties"
    for (tid, metric) in sorted(cch.CARD_AHEAD_OF_PRODUCER):
        declared, expires, why = cch.register_window(tid, metric)
        assert declared <= today, f"{tid}.{metric} was declared in the future: {declared}"
        assert len(why) > 30, f"{tid}.{metric} carries no real argument: {why!r}"
        assert today <= expires, (f"{tid}.{metric} EXPIRED {expires}: the gate is red on it -- land the "
                                  f"rows, or re-declare with today's date and a fresh argument")


def test_every_register_entry_names_a_metric_its_card_still_declares():
    """A DEAD ENTRY IS A DEFECT (five `_WAIVERS` entries have been deleted on dead premises). An entry
    whose card no longer declares the metric can never grade anything, so it is silent rot sitting in a
    fence -- refused here, at build time, where it costs nothing to notice."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    for (tid, metric) in sorted(cch.CARD_AHEAD_OF_PRODUCER):
        assert tid in reg.tables, f"register entry names an unknown card: {tid}"
        ts = reg.get(tid)
        assert ts.shape == "tall" and ts.metric_col, f"register entry names a non-tall card: {tid}"
        assert metric in ts.metrics, f"{tid} no longer declares {metric!r} -- delete the register entry"


def test_the_real_card_grades_exactly_the_three_prelim_metrics():
    """THE INSTANCE, on the REAL registry and the REAL register: with a mirror carrying every declared
    gold_weather_z metric EXCEPT the three preliminary stamps (what the 2026-09-22 gate log actually read
    -- the producer emitted metrics=['drought_z','frost_event_flag','gdd_z','heat_stress_z',
    'tmax_anomaly'] and the mirror was last hand-loaded before the card edit), the graded run has ZERO
    errors and exactly three warnings, and the ungraded run has the three errors HEAD printed."""
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()
    ts = reg.get("gold_weather_z")
    served = sorted(set(ts.metrics) - set(_PRELIM))
    distinct = {k: sorted(v) for k, v in _tall_distinct_by_physical(reg).items()}
    distinct[("gold_weather_z", "metric")] = served

    head = cch.check_metric_vocabulary(reg, query_fn=_Mirror(distinct))
    assert len(head) == 3 and all(any(repr(m) in e for e in head) for m in _PRELIM), head

    warns: list = []
    graded = cch.check_metric_vocabulary(reg, query_fn=_Mirror(distinct), warnings=warns)
    assert graded == [], graded
    assert len(warns) == 3 and all(w.startswith(h) for w, h in zip(sorted(warns), sorted(head)))


def test_no_tall_card_runs_ahead_of_its_producer():
    """THE REGISTER'S PAIR, AND THE HONEST SIZE OF IT (the round-2 reviewer's MAJOR 1; docket H-L2-2).

    The register answers "was this absence DECLARED". It cannot answer "does a producer exist that will
    ever emit this name" -- a human can register a metric no producer will ever emit and buy a
    PENDING_WINDOW_DAYS yellow for it. That second question belongs to a BUILD-TIME binding, and this is
    it; but READ THE NUMBERS BEFORE CALLING IT A FENCE. It binds ONE card, `gold_weather_z`, which is 18
    of the 51 declared tall metric names. The other 33 are NAMED below and have no producer roster to
    bind to yet, so for them the register is the only fence and it is a human one. That is 65 percent of
    the surface and it is why H-L2-2 is BLOCKING for the next wave, not a nice-to-have.

    What the 33 do NOT lose: an UNREGISTERED zero-row metric still reds, byte for byte as HEAD did,
    including through fence (A) for the orphan card `silver_production_livestock` (pinned in
    tests/unit/test_silver_rebuild_gate.py)."""
    from leviathan.graphrag.numbers.registry import load_registry

    def _weather_z_roster():
        from leviathan.transforms.gold.weather_z import ALL_METRICS, DERIVED_METRICS
        return set(ALL_METRICS) | set(DERIVED_METRICS)

    bound = {"gold_weather_z": _weather_z_roster}
    # tall cards whose producer exposes no readable metric roster yet (H-L2-2, BLOCKING).
    unbound = {"silver_production", "silver_production_livestock", "silver_psd_attributes",
               "silver_wasde"}

    reg = load_registry()
    tall = {tid for tid in cch._numbers_table_ids(reg)
            if reg.get(tid).shape == "tall" and reg.get(tid).metric_col}
    assert tall == set(bound) | unbound, (
        "a tall card arrived or left without a producer-binding decision: "
        + str(sorted(tall ^ (set(bound) | unbound))))
    for tid, roster in bound.items():
        card, emitted = set(reg.get(tid).metrics), roster()
        assert card - emitted == set(), f"{tid} declares metrics no producer emits: {sorted(card - emitted)}"
        assert emitted - card == set(), f"{tid} producer emits metrics the card hides: {sorted(emitted - card)}"
    # the honest coverage number, printed rather than asserted-and-forgotten
    names = {m for tid in tall for m in reg.get(tid).metrics}
    covered = {m for tid in bound for m in reg.get(tid).metrics}
    print(f"\nH-L2-2 COVERAGE: the card-vs-producer binding holds {len(covered)} of {len(names)} "
          f"declared tall metric name(s); unbound cards: {sorted(unbound)}")
    assert len(covered) == 18 and len(names) == 51


def test_the_grade_api_carries_no_baseline_and_no_alltime_channel_at_all():
    """TWO DEAD DESIGNS, BOTH GONE, not merely unused. A dead keyword is a loaded gun.

    ROUND 1 (baseline): its evidence was the rolling census's per-LEG pg_rows, blind to any declared
    metric no causal driver resolves to (30 of the 42 gradeable tall metrics, 27 of them carrying rows on
    the real mirror), and it got SAFER-looking as it got STALER because rows accrete and a red family
    never advances its baseline.
    ROUND 2 (all-time count): `SELECT metric, COUNT(*) ... GROUP BY metric` is `SELECT DISTINCT metric`
    restated, so its RED branch was dead code -- 0 of 51 dropped metrics could red. If either name comes
    back into this module, it comes back with an argument, not by accident."""
    import inspect
    for fn in (cch.check_metric_vocabulary, cch.contract_check, cch.contract_check_ex, cch.run_live):
        assert "baseline" not in inspect.signature(fn).parameters, fn.__name__
    for gone in ("baseline_metric_evidence", "grade_zero_row_metric", "load_baseline",
                 "metric_alltime_rows", "grade_query_count", "NEVER_HAD_ROWS_NOTE"):
        assert not hasattr(cch, gone), gone
    with pytest.raises(SystemExit):
        cch.main(["--baseline-uri", "s3://b/k"])


def test_the_gate_stage_calls_the_graded_path_and_passes_the_query_fn():
    """THE WIRING, WHICH IS WHERE THE DEADLOCK ACTUALLY LIVED. Round 1 shipped the graded check and
    NOTHING CALLED IT: jobs/audit/silver_rebuild_gate.py::stage_contract_check still called
    cch.contract_check(...), so the grading was inert on the scheduled path and the six-fail streak
    would have continued through the deploy. Asserted on the SOURCE (an AST read of the real function),
    so a future edit that reverts to the one-list call fails here rather than in production."""
    import ast
    import inspect

    from jobs.audit import silver_rebuild_gate as gate

    src = inspect.getsource(gate.stage_contract_check)
    tree = ast.parse(src.lstrip())
    called = {f"{getattr(n.func.value, 'id', '')}.{n.func.attr}"
              for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "cch.contract_check_ex" in called, called
    assert "cch.contract_check" not in called, "the gate must not call the UNGRADED one-list form"
    ex = [n for n in ast.walk(tree)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
          and n.func.attr == "contract_check_ex"][0]
    kw = {k.arg for k in ex.keywords}
    assert "query_fn" in kw and "caches" in kw, kw
    assert "baseline" not in kw, "the baseline channel is gone -- see the module docstring"
