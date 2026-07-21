"""PRICE_OBSERVABILITY W1 -- v1a WASDE avg_farm_price acceptance gates as CODE (judge-free).

This file is the deterministic W1.4 harness for wiring the USDA WASDE US season-average farm price into
the numbers SQL agent behind the SAME leakage-safe harness as every other registered metric, plus the
DP-1 unit-override / DP-2 provenance / DP-5 timestamp-date mechanisms the registry grew in W1.1.

Per the plan (docs/private/PRICE_OBSERVABILITY_PLAN.md section 2), fixtures here are SYNTHETIC and
hand-authored -- golden real-parquet rows are a W3.1 rider added after the user-gated W3.0 probes, never
now. The WASDE rows below are shaped to the LIVE registry silver_wasde spec (tall; grain
[commodity, table_type, region, marketing_year, attribute]; estimate_role-first vintage tiebreak) so the
PIT oracle (apply_pit_filter) is exercised against the exact spec that ships; the DP-5 timestamp
mechanism is proved against a synthetic timestamp-typed spec (no registered table uses it until
pink_sheet in W2), with SQL-text assertions on BOTH the _extras aliases and the guard/window predicates.

Covered gates (W1.4):
  * forced-asof leakage trap -- an asof before a release serves the PRIOR vintage (or not_known).
  * tiebreak -- 'actual' beats 'projection' at the same release_date at a late asof.
  * unit-override rewrite (DP-1) -- a junk 'Milled Basis' unit serves '$/bu' and the CITATION unit is
    correct (citations.py untouched -- it reads r['unit'] first).
  * AGG-row unit (DP-1) -- a mean over marketing years, which emits NO extras, still carries '$/bu'.
  * blank-unit fallback -- an off-map commodity serves '' (blank beats junk), never a wrong unit.
  * build_sql RAISE -- a commodity-less farm-price query is refused deterministically (DP-1 guard).
  * revision_stamp (DP-2) -- estimate_role surfaces as `revision_stamp` in the SQL and the citation.
  * register cleanliness -- every NEW reader-facing desc / bullet / prompt sentence passes register_leaks.
  * reconcile-gate coupling -- silver_wasde is in reconcile.NUMBERS_TABLES so the new metric is gated.
  * config_check R1/R3 BIND -- the price-register lint is now non-vacuous and PASSES on the edited yaml.
  * DP-5 -- a timestamp date_col emits substr(CAST(col AS varchar),1,10) in extras AND every predicate;
    a string date_col is byte-identical to before.
"""
from __future__ import annotations

import types

import pytest

from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers.registry import Metric, TableSpec, load_registry
from leviathan.graphrag import citations as C
from leviathan.graphrag.register import register_leaks, sanitize

WASDE = "silver_wasde"

# W3.0 PROBE VERDICT (2026-07-21): the physical avg_farm_price series is LABEL-DEAD (every commodity's last
# release_date is 2011-08-11; it is the only price-like attribute in silver), so the metric is EXCLUDED from
# the live whitelist per the ratified honesty rule -- serving would present a 2011 vintage as latest-known.
# The DP-1/DP-2 machinery stays built-and-tested here against the exact live table shape via a synthetic
# re-injection, ready for the restoration wave (bronze alias extension + re-parse task, 2026-07-21).
_FARM_METRIC = Metric(
    desc="US season-average farm price (USDA survey-based; NOT a futures settle); current/future-MY values "
         "are USDA PROJECTIONS -- attribute them",
    unit_overrides={"corn": "$/bu", "wheat": "$/bu", "soybeans": "$/bu", "cotton": "c/lb", "rice": "$/cwt"})


def _wasde_live() -> TableSpec:
    return load_registry().get(WASDE)


def _wasde() -> TableSpec:
    """The LIVE silver_wasde spec CLONED with avg_farm_price re-injected (see the probe-verdict note above)."""
    live = _wasde_live()
    return live.model_copy(update={"metrics": {**live.metrics, "avg_farm_price": _FARM_METRIC}})


@pytest.fixture()
def farm_registry(monkeypatch):
    """Patch load_registry in every consumer module so Q.run / the agent loop resolve the synthetic
    re-injected spec -- the live registry EXCLUDES the metric and would reject these calls."""
    import leviathan.graphrag.numbers.registry as R
    live = R.load_registry()
    reg = R.NumbersRegistry(tables={**live.tables, WASDE: _wasde()})
    monkeypatch.setattr(R, "load_registry", lambda path=None: reg)
    monkeypatch.setattr(Q, "load_registry", lambda path=None: reg)
    monkeypatch.setattr(A, "load_registry", lambda path=None: reg)
    return reg


# -- synthetic avg_farm_price rows shaped to the LIVE silver_wasde spec (tall). estimate is the value_col,
#    release_date the vintage, estimate_role/projection_month/source_table_id the F036 tiebreak columns,
#    unit deliberately the JUNK section-heading text the DP-1 override must overwrite. ---------------------
def _farm_rows(commodity: str = "corn", my: str = "2024/25") -> list[dict]:
    base = dict(commodity=commodity, table_type="balance_sheet", region="united_states",
                marketing_year=my, attribute="avg_farm_price", unit="Milled Basis",
                projection_month="", source_table_id="w1")
    return [
        {**base, "release_date": "2024-05-10", "estimate": "4.40", "estimate_role": "projection"},
        {**base, "release_date": "2025-05-09", "estimate": "4.55", "estimate_role": "actual"},
    ]


def _pit(rows, asof, **q):
    spec = Q.NumberQuery(table=WASDE, metric="avg_farm_price", asof=asof, commodity=q.get("commodity", "corn"),
                         country="united_states", period=q.get("period", "2024/25"))
    return Q.apply_pit_filter(rows, spec, _wasde())


# -- FakeClient / agent-status oracle (cloned from test_numbers_depth_gates) ----------------------------
def _tool_use(inp, tid="t1"):
    return types.SimpleNamespace(type="tool_use", name=A.TOOL_NAME, input=inp, id=tid)


def _text(t):
    return types.SimpleNamespace(type="text", text=t)


def _resp(content):
    return types.SimpleNamespace(content=content, stop_reason="end_turn")


class _Msgs:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        return self.outer.queue.pop(0)


class FakeClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.messages = _Msgs(self)


def _agent_status(rows, tool_input, asof) -> dict:
    """Drive the REAL agent loop with a mocked LLM (one tool_use) and a query_fn returning apply_pit_filter's
    rows -- so the ok/not_known/no_rows taxonomy is exercised end-to-end, byte-identical to serving except
    for the executor."""
    ts = _wasde()
    spec = Q.NumberQuery(asof=asof, **{k: v for k, v in tool_input.items() if k != "asof"})
    kept = Q.apply_pit_filter(rows, spec, ts)
    out = [{"value": r.get("estimate"), "knowledge_date": r.get("release_date"),
            "revision_stamp": r.get("estimate_role")} for r in kept]
    client = FakeClient([_resp([_tool_use(tool_input)]), _resp([_text("done")])])
    res = A.answer_numbers("q", asof=asof, client=client, query_fn=lambda sql: out)
    return res["calls"][0]


# ======================================================================================================
# LEAKAGE + TIEBREAK -- the PIT contract for the new metric.
# ======================================================================================================
def test_farm_price_forced_asof_serves_prior_vintage():
    """A mid-season asof (2024-12-31) sees the PRIOR vintage 4.40 (release 2024-05-10) -- the 2025-05-09
    'actual' is not yet published -- and a late asof (2025-06-30) sees 4.55."""
    rows = _farm_rows()
    assert [r["estimate"] for r in _pit(rows, "2024-12-31")] == ["4.40"]
    assert [r["estimate"] for r in _pit(rows, "2025-06-30")] == ["4.55"]


def test_farm_price_asof_before_any_release_is_not_known(farm_registry):
    """An asof strictly before the earliest release (2024-04-01) has NO public estimate -> empty
    apply_pit_filter AND the agent's vintage-only not_known status (never a fabricated figure)."""
    rows = _farm_rows()
    assert _pit(rows, "2024-04-01") == []
    call = _agent_status(rows, {"table": WASDE, "metric": "avg_farm_price", "commodity": "corn",
                                "country": "united_states", "period": "2024/25"}, asof="2024-04-01")
    assert call["status"] == "not_known" and call["rows"] == []


def test_farm_price_tiebreak_actual_beats_projection_at_late_asof():
    """Two estimate_role rows at ONE release_date (2025-05-09): at a late asof the role rank
    (actual < estimate < projection) makes the settled 'actual' win the ROW_NUMBER tie -- the DESIRED
    semantics for a season-average price (the settled figure, not a superseded projection)."""
    base = dict(commodity="corn", table_type="balance_sheet", region="united_states",
                marketing_year="2024/25", attribute="avg_farm_price", unit="Milled Basis",
                projection_month="", source_table_id="w1", release_date="2025-05-09")
    tie = [{**base, "estimate": "4.90", "estimate_role": "projection"},
           {**base, "estimate": "4.55", "estimate_role": "actual"}]
    kept = _pit(tie, "2025-12-31")
    assert len(kept) == 1
    assert kept[0]["estimate_role"] == "actual" and kept[0]["estimate"] == "4.55"


# ======================================================================================================
# DP-1 -- unit_overrides post-fetch rewrite (the choke point is Q.run; citations.py stays untouched).
# ======================================================================================================
def test_unit_override_rewrites_junk_unit_and_citation_is_correct(farm_registry):
    """A returned row carrying the junk section-heading unit 'Milled Basis' is REWRITTEN to '$/bu' for
    corn, and the number-citation unit built by citations.from_number is '$/bu' (it reads r['unit'] first,
    which the post-fetch set)."""
    junk = [{"value": "4.55", "unit": "Milled Basis", "knowledge_date": "2025-05-09"}]
    spec = Q.NumberQuery(table=WASDE, metric="avg_farm_price", asof="2025-12-31", commodity="corn",
                         country="united_states", period="2024/25")
    out = Q.run(spec, query_fn=lambda sql: junk)
    assert out[0]["unit"] == "$/bu"
    cit = C.from_number({"query": spec.model_dump(exclude_none=True), "rows": out}, 1)
    assert cit.unit == "$/bu"
    assert cit.unit in cit.label


def test_unit_override_cotton_and_rice_distinct_units(farm_registry):
    """The map is per-commodity, not a single unit: cotton serves 'c/lb', rice '$/cwt'."""
    for commodity, unit in (("cotton", "c/lb"), ("rice", "$/cwt")):
        spec = Q.NumberQuery(table=WASDE, metric="avg_farm_price", asof="2025-12-31", commodity=commodity,
                             country="united_states", period="2024/25")
        out = Q.run(spec, query_fn=lambda sql: [{"value": "1", "unit": "junk"}])
        assert out[0]["unit"] == unit


def test_unit_override_on_agg_row_still_carries_unit(farm_registry):
    """An agg-shaped row (SELECT avg(value) AS value -- NO extras, NO unit column) still gets the override:
    a 'mean farm price over 5 MYs' must not cite unitless (S3.F6). The value is untouched."""
    agg = [{"value": "4.60"}]
    spec = Q.NumberQuery(table=WASDE, metric="avg_farm_price", asof="2025-12-31", commodity="wheat",
                         country="united_states", period="2024/25", agg="mean")
    out = Q.run(spec, query_fn=lambda sql: agg)
    assert out[0]["unit"] == "$/bu" and out[0]["value"] == "4.60"


def test_unit_override_blank_fallback_when_commodity_off_map(farm_registry):
    """An off-map commodity (sorghum -- multiplicity-suspect, not in the coverage set) serves BLANK ''
    (blank-on-unresolvable beats serving the junk section-heading unit), never a wrong unit."""
    spec = Q.NumberQuery(table=WASDE, metric="avg_farm_price", asof="2025-12-31", commodity="sorghum",
                         country="united_states", period="2024/25")
    out = Q.run(spec, query_fn=lambda sql: [{"value": "3.9", "unit": "Milled Basis"}])
    assert out[0]["unit"] == ""


def test_non_override_metric_unit_untouched():
    """A metric WITHOUT unit_overrides (ending_stocks) is byte-identical: the row's own unit survives."""
    spec = Q.NumberQuery(table=WASDE, metric="ending_stocks", asof="2024-05-31", commodity="corn",
                         country="united_states", period="2023/24")
    out = Q.run(spec, query_fn=lambda sql: [{"value": "1", "unit": "1000 MT"}])
    assert out[0]["unit"] == "1000 MT"


def test_build_sql_raises_on_commodityless_farm_price():
    """DP-1 GUARD: a farm-price query with NO commodity is refused deterministically at build_sql -- a
    commodity-less query would serve unattributable blank-unit rows. The raise is enforcement; the
    Conventions bullet is only discipline. build_sql for a NON-override metric commodity-less is fine."""
    with pytest.raises(ValueError, match="unit_overrides"):
        Q.build_sql(Q.NumberQuery(table=WASDE, metric="avg_farm_price", asof="2024-05-31"), _wasde())
    # a commodity-carrying farm-price query compiles fine
    ok = Q.build_sql(Q.NumberQuery(table=WASDE, metric="avg_farm_price", asof="2024-05-31", commodity="corn",
                                   country="united_states", period="2023/24"), _wasde())
    assert "attribute = 'avg_farm_price'" in ok and "commodity = 'corn'" in ok


# ======================================================================================================
# DP-2 -- provenance_col surfaced as revision_stamp (row + citation meta).
# ======================================================================================================
def test_revision_stamp_in_sql_and_row_and_citation():
    """provenance_col=estimate_role surfaces as `revision_stamp` in the SELECT, travels on the row, and
    lands in the citation payload so a projection-vs-actual attribution is visible."""
    ts = _wasde()
    assert ts.provenance_col == "estimate_role"
    sql = Q.build_sql(Q.NumberQuery(table=WASDE, metric="avg_farm_price", asof="2025-12-31", commodity="corn",
                                    country="united_states", period="2024/25"), ts)
    assert "estimate_role AS revision_stamp" in sql
    row = {"value": "4.55", "unit": "$/bu", "knowledge_date": "2025-05-09", "revision_stamp": "actual"}
    cit = C.from_number({"query": {"table": WASDE, "metric": "avg_farm_price", "commodity": "corn",
                                   "country": "united_states", "period": "2024/25", "asof": "2025-12-31"},
                         "rows": [row]}, 2)
    assert cit.payload["rows"][0]["revision_stamp"] == "actual"


# ======================================================================================================
# REGISTER CLEANLINESS -- every NEW reader-facing prose sentence passes register_leaks.
# ======================================================================================================
def test_new_metric_desc_is_register_clean():
    desc = _FARM_METRIC.desc
    assert register_leaks(desc) == []
    assert "PROJECTION" in desc.upper() and "NOT a futures settle" in desc


def test_new_agent_bullets_are_register_clean():
    """The two new Conventions bullets (farm-price data semantics + the price/premium/spread REGISTER
    bullet) are register-clean -- the REGISTER bullet is worded to forbid the convergence/valuation
    vocabulary WITHOUT tripping the fence detector on itself (no futurity modal beside the spread verb)."""
    from leviathan.graphrag.numbers.agent import system_prompt
    sp = system_prompt(load_registry())
    for marker in ("NO governed US farm-gate price series is live",
                   "State prices, premiums, discounts, and spreads as an observed level"):
        assert marker in sp, f"bullet missing: {marker}"
        seg = sp[sp.find(marker):sp.find(marker) + 400]
        assert register_leaks(seg) == [], f"new bullet leaks: {register_leaks(seg)}"


def test_new_answer_prompt_sentences_are_register_clean():
    """The W1.5 fence relocation (cascade) and the mentor valuation addition are register-clean as new
    prose -- the mentor's full sentence retains the PRE-EXISTING 'price target' fence wording (an
    instruction that quotes a banned phrase, exactly like the prior codebase), so only the NEW clause is
    asserted clean here."""
    from leviathan.graphrag import answer as AN
    casc_marker = "observed price LEVELS now arrive as [N] rows"
    assert casc_marker in AN._SYSTEM_CASCADE
    seg = AN._SYSTEM_CASCADE[AN._SYSTEM_CASCADE.find(casc_marker):AN._SYSTEM_CASCADE.find(casc_marker) + 220]
    assert register_leaks(seg) == []
    ment_marker = "nor a valuation judgment (cheap/rich/attractive) nor a forecast that a spread narrows or normalizes"
    assert ment_marker in AN._SYSTEM_MENTOR
    assert register_leaks(ment_marker) == []


def test_example_farm_price_answer_is_register_clean():
    """A representative reader answer that cites a farm-price level + its projection attribution passes
    the strip invariant register_leaks(sanitize(x)) == []."""
    ans = ("US season-average corn farm price is projected at $4.55/bu for 2024/25 [N1] (USDA projection, "
           "not a settle); it was $4.40/bu at the May vintage [N2].")
    assert register_leaks(sanitize(ans)) == []


# ======================================================================================================
# GATE COUPLING -- reconcile + config_check R1/R3 now BIND on the edited tables.yaml.
# ======================================================================================================
def test_reconcile_gate_covers_silver_wasde():
    """reconcile.NUMBERS_TABLES iterates a hardcoded tuple; silver_wasde must be in it so the new
    avg_farm_price metric rides the existing reconcile gate rather than shipping green-but-unchecked."""
    from leviathan.silver import reconcile
    assert "silver_wasde" in reconcile.NUMBERS_TABLES


def test_avg_farm_price_excluded_from_live_whitelist():
    """W3.0 PROBE VERDICT PIN: the live registry does NOT whitelist avg_farm_price (label-dead series;
    serving would present the 2011-08-11 vintage as latest-known). A restoration re-whitelist must come
    with the bronze alias extension + fresh probes -- this pin makes a premature re-add loud."""
    from leviathan.graphrag import config_check as CCK
    assert "avg_farm_price" not in _wasde_live().metrics
    assert CCK.check_price_register() == []                   # R1/R3 vacuous-by-exclusion, R2/R8/R4/R5 green
    # the curated set constant stays staged for the restoration wave
    assert CCK._FARM_PRICE_COMMODITIES == {"corn", "wheat", "soybeans", "cotton", "rice"}


def test_config_check_r1_fails_on_coverage_drift(farm_registry, monkeypatch):
    """R1 is a real gate: with the metric (synthetically) whitelisted, unit_overrides keys drifting from
    the curated set FAIL the lint -- proven by narrowing the curated set under the check."""
    from leviathan.graphrag import config_check as CCK
    monkeypatch.setattr(CCK, "_FARM_PRICE_COMMODITIES", frozenset({"corn", "wheat"}))
    errs = CCK.check_price_register()
    assert any("avg_farm_price" in e and "curated coverage" in e for e in errs)


# ======================================================================================================
# DP-5 -- timestamp date_col normalization (mechanism only; no registered table uses it until W2).
# ======================================================================================================
def _ts_spec() -> TableSpec:
    """A synthetic pink_sheet-shaped wide data_date table with a TIMESTAMP date column + a provenance
    stamp -- the shape W2 registers, exercised here so the DP-5 mechanism ships tested in W1."""
    return TableSpec(id="synth_pink_sheet", description="", shape="wide", period_type="date",
                     date_col="date", knowledge_date_col="date", knowledge_semantics="data_date",
                     date_col_type="timestamp", provenance_col="latest_release_ym",
                     metrics={"palm_oil_cpo_usd_t": Metric(unit="USD/mt", desc="x")})


def test_dp5_timestamp_normalizes_extras_and_predicates():
    """A timestamp date_col emits substr(CAST(date AS varchar),1,10) in BOTH the _extras alias (the [N]
    meta) AND every guard/window predicate -- so Athena's timestamp(3) render and the pg TEXT mirror agree
    (parity) and a window boundary month is not silently excluded."""
    ts = _ts_spec()
    sql = Q.build_sql(Q.NumberQuery(table="synth_pink_sheet", metric="palm_oil_cpo_usd_t", asof="2026-06-15",
                                    period_start="2026-06-01", period_end="2026-06-30"), ts)
    sub = "substr(CAST(date AS varchar), 1, 10)"
    assert f"{sub} AS knowledge_date" in sql          # extras alias normalized
    assert f"{sub} <= '2026-06-15'" in sql            # the as-of guard predicate normalized
    assert f"{sub} >= '2026-06-01'" in sql            # window start predicate normalized
    assert f"{sub} <= '2026-06-30'" in sql            # window end predicate normalized (boundary included)
    assert "latest_release_ym AS revision_stamp" in sql   # DP-2 provenance rides the same table


def test_dp5_boundary_end_predicate_uses_substr_not_raw_cast():
    """The window END predicate is the substr form, NOT a bare CAST -- a raw-timestamp compare
    ('2026-06-01 00:00:00.000' > '2026-06-01') would EXCLUDE the boundary month; substr normalizes it in."""
    ts = _ts_spec()
    sql = Q.build_sql(Q.NumberQuery(table="synth_pink_sheet", metric="palm_oil_cpo_usd_t", asof="2026-07-01",
                                    period_end="2026-06-01"), ts)
    assert "substr(CAST(date AS varchar), 1, 10) <= '2026-06-01'" in sql
    assert "CAST(date AS varchar) <= '2026-06-01'" not in sql.replace("substr(CAST(date AS varchar), 1, 10)", "")


def test_dp5_string_datecol_is_byte_identical():
    """A STRING date_col (the default, every existing table) keeps the plain CAST-as-varchar text compare
    -- no substr appears -- so DP-5 is additive and zero-behavior-change off the timestamp path."""
    ts = TableSpec(id="synth_str", description="", shape="wide", period_type="date", date_col="date",
                   knowledge_date_col="date", knowledge_semantics="data_date",
                   metrics={"x": Metric(unit="u", desc="d")})
    sql = Q.build_sql(Q.NumberQuery(table="synth_str", metric="x", asof="2026-06-15",
                                    period_start="2026-06-01", period_end="2026-06-30"), ts)
    assert "substr(" not in sql
    assert "CAST(date AS varchar) <= '2026-06-15'" in sql
    assert "CAST(date AS varchar) >= '2026-06-01'" in sql


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
