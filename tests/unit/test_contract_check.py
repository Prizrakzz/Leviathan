"""SILVER-C002 unit tests for contract_check -- the numbers-stack I1 vocabulary gate.

pg is MOCKED throughout (a query_fn is injected); nothing touches the mirror/Athena/AWS. Covers the four
plan classes: a wide metric-column absent (WASDE Title-Case), a tall metric absent from the DISTINCT set
(drought_z zero-row), a region-resolved country absent from the DISTINCT country set (France->EU), and the
ZERO-Athena-against-projection guarantee (projection trio excluded + never queried). Also asserts the real
numbers registry's wide metrics resolve to real F010 columns (no vacuous pass)."""
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
def test_real_registry_wide_metrics_resolve_to_f010_columns():
    from leviathan.graphrag.numbers.registry import load_registry
    reg = load_registry()

    # mock pg returns each tall table's declared metrics as its DISTINCT set (so only a wide-column MISS
    # could produce an error); column_fn is the real F010 resolver.
    def pg(sql):
        for tid in reg.tables:
            ts = reg.get(tid)
            if ts.shape == "tall" and ts.metric_col and f"{ts.metric_col} " in sql \
                    and (ts.athena_table or ts.id) in sql:
                return [{"v": m} for m in ts.metrics]
        return []

    errs = cch.check_metric_vocabulary(reg, query_fn=pg)
    assert errs == [], errs


def test_psd_unserved_slugs_are_known_not_drift(monkeypatch):
    """The C002 slug check treats cascade.PSD_UNSERVED_SLUGS as declared-unserved: no drift error
    for cocoa/frozen_orange_juice on silver_psd (the runtime SKIPs those legs at _scope), while any
    OTHER missing slug still fails."""
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


def test_cot_unserved_slugs_pin_the_yaml_not_covered_list():
    """cascade.COT_UNSERVED_SLUGS is a mirror of configs/sources/cftc_cot.yaml `not_covered:` -- the
    authoritative vendor-coverage declaration. A slug added to either side without the other is drift
    in the fence itself; this lint makes the two lists one fact. Line-scan, not safe_load: the file's
    CSV schema block carries `key:{...}` flow tokens the YAML scanner rejects, so the whole document
    does not parse -- the not_covered block itself is plain `- slug  # comment` lines."""
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
