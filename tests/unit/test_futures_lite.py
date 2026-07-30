"""SEAM C -- futures v1.5-lite (Option A, LEVELS-ONLY) surface tests. Pure/hermetic -- no AWS, no LLM, no
pg. Covers: the whitelisted-and-served registry load (2026-07-23), the levels-only build_sql guard + DP-5 substr
as-of, the per-contract unit_overrides, the config_check.check_futures_lite lint (card shape + close-only +
unit completeness + gate-state + template register-cleanliness), and the agent's phrasing-based decline
routes (numbers/agent.futures_scope + FUTURES_DECLINE_TEMPLATES prepend)."""
from __future__ import annotations

import pytest

from leviathan.graphrag import config_check as cc
from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import agent as na
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R


# -- registry: WHITELISTED-AND-SERVED (loaded into serving now the gate + freshness fix have passed) -----
def test_futures_whitelisted_and_served():
    # the card is WHITELISTED (removed from WHITELIST_ABSENT_DEFAULT 2026-07-23) so it LOADS into the served
    # registry (the agent tool enum / system-prompt cards) -- the SEAM-C no-judge gate + freshness fix passed.
    assert "silver_futures_prices" not in R.WHITELIST_ABSENT_DEFAULT
    assert "silver_futures_prices" in R.load_registry().tables


def test_futures_card_present_in_raw_yaml():
    # registered in the RAW tables.yaml even while dropped from the loaded registry.
    doc = cc._load("numbers/tables.yaml")
    assert "silver_futures_prices" in (doc.get("tables") or {})


def test_env_kill_switch_still_env_only():
    # WHITELIST_ABSENT_DEFAULT is DISJOINT from _disabled_tables() (env-only) so the env-parse kill-switch
    # semantics are byte-identical -- the union happens only in load_registry.
    assert "silver_futures_prices" not in R._disabled_tables()


# -- levels-only build_sql guard + DP-5 substr as-of -----------------------------------------------------
def _ts() -> R.TableSpec:
    return R.TableSpec(
        id="silver_futures_prices", description="", shape="wide", commodity_col="leviathan_slug",
        period_type="date", date_col="date", date_col_type="timestamp", knowledge_semantics="data_date",
        knowledge_date_col="date", publication_lag_days=1, levels_only=True,
        metrics={"close": R.Metric(unit_overrides={"corn_cbot": "US cents/bushel"})})


def _spec(**kw) -> Q.NumberQuery:
    base = dict(table="silver_futures_prices", metric="close", asof="2026-06-05", commodity="corn_cbot",
                agg="latest")
    base.update(kw)
    return Q.NumberQuery(**base)


def test_levels_only_latest_emits_dp5_substr_and_pub_lag():
    sql = Q.build_sql(_spec(), _ts())
    assert "substr(CAST(date AS varchar), 1, 10) <= '2026-06-04'" in sql   # DP-5 + 1-day pub lag (2026-06-05 -> -04)
    assert "leviathan_slug = 'corn_cbot'" in sql
    assert sql.rstrip().endswith("LIMIT 1")                                 # single most-recent settle


@pytest.mark.parametrize("kw", [
    {"agg": "series"}, {"agg": "mean"}, {"agg": "sum"}, {"agg": "max"}, {"agg": "min"},
    {"agg": "latest", "period_start": "2026-01-01", "period_end": "2026-06-05"},
    {"agg": "latest", "period_start": "2026-01-01"},
])
def test_levels_only_guard_rejects_non_latest_and_windows(kw):
    with pytest.raises(ValueError, match="levels-only"):
        Q.build_sql(_spec(**kw), _ts())


def test_levels_only_commodity_less_still_raises_dp1():
    # a commodity-less unit_overrides query raises the DP-1 guard (unattributable blank-unit rows).
    with pytest.raises(ValueError, match="unit_overrides"):
        Q.build_sql(Q.NumberQuery(table="silver_futures_prices", metric="close", asof="2026-06-05",
                                  agg="latest"), _ts())


def test_unit_overrides_applied_post_fetch():
    rows = [{"value": 417.75, "unit": "junk"}]
    out = Q._apply_unit_overrides(rows, _spec(commodity="corn_cbot"), _ts())
    assert out[0]["unit"] == "US cents/bushel"
    # cotton c/lb via the card's real overrides (round-trip through the live-shape unit map)
    ts = R.TableSpec(id="silver_futures_prices", description="", shape="wide", commodity_col="leviathan_slug",
                     period_type="date", date_col="date", date_col_type="timestamp",
                     knowledge_semantics="data_date", knowledge_date_col="date", levels_only=True,
                     metrics={"close": R.Metric(unit_overrides=cc._FUTURES_UNIT_OVERRIDES)})
    assert Q._apply_unit_overrides([{"value": 74.57}], _spec(commodity="cotton"), ts)[0]["unit"] == "US cents/lb"


# -- config_check.check_futures_lite --------------------------------------------------------------------
def test_check_futures_lite_green_on_live_config():
    assert cc.check_futures_lite() == []


def test_check_futures_lite_flags_a_bad_unit(monkeypatch):
    doc = cc._load("numbers/tables.yaml")
    card = doc["tables"]["silver_futures_prices"]
    card["metrics"]["close"]["unit_overrides"]["corn_cbot"] = "USD/bushel"   # wrong exchange unit
    monkeypatch.setattr(cc, "_load", lambda name: doc)
    errs = cc.check_futures_lite()
    assert any("unit_overrides" in e for e in errs)


def test_check_futures_lite_flags_extra_metric(monkeypatch):
    doc = cc._load("numbers/tables.yaml")
    doc["tables"]["silver_futures_prices"]["metrics"]["log_return"] = {"desc": "x"}   # not close-only
    monkeypatch.setattr(cc, "_load", lambda name: doc)
    assert any("close-ONLY" in e for e in cc.check_futures_lite())


def test_check_futures_lite_flags_missing_card(monkeypatch):
    monkeypatch.setattr(cc, "_load", lambda name: {"tables": {}})
    errs = cc.check_futures_lite()
    assert errs and "absent" in errs[0]


def test_futures_lite_registered_in_main_lints():
    # the SEAM-C lint runs in the config_check gate (it must be one of the enumerated checks).
    import inspect
    assert "check_futures_lite()" in inspect.getsource(cc.main)


# -- agent phrasing-based decline routes ----------------------------------------------------------------
@pytest.mark.parametrize("q,cls", [
    ("What is December corn trading at?", "named"),
    ("what's the March soybeans contract worth", "named"),
    ("what is the December cotton contract price", "named"),
    ("show me the corn futures curve", "curve"),
    ("is coffee in contango or backwardation", "curve"),
    ("what's the soybean oil term structure", "curve"),
    ("how much has corn risen this month", "change"),
    ("how far has cotton moved this week", "change"),
    ("how much has soybean oil rallied year-to-date", "change"),
])
def test_futures_scope_fires(q, cls):
    assert na.futures_scope(q) == cls


@pytest.mark.parametrize("q", [
    "What is the front-month corn futures settle on 2026-06-05?",   # a plain LEVEL ask -> servable, no decline
    "what is the corn settle today",
    "how much corn was produced this month",                        # volume, not price
    "what is corn production this year",
    "how big is the corn crop",
    "cocoa price",                                                  # bare price, no class cue
    "what is soybean stocks-to-use",
])
def test_futures_scope_none_on_level_and_volume(q):
    assert na.futures_scope(q) is None


def test_futures_decline_templates_register_clean_and_class_matched():
    assert set(na.FUTURES_DECLINE_TEMPLATES) == set(na._FUTURES_DECLINE_CLASSES)
    for name, t in na.FUTURES_DECLINE_TEMPLATES.items():
        assert not reg.register_leaks(t), (name, t)
        assert reg.count_valuation_words(t) == 0 and reg.count_flow_words(t) == 0
        assert "front-month" in t


# -- answer_numbers prepends the decline preface (fake client, no lookups) ------------------------------
class _Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, text):
        self._text = text

    def create(self, **kw):
        return _Resp([_Blk(type="text", text=self._text)])


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


def test_answer_numbers_prepends_futures_decline_named():
    out = na.answer_numbers("What is December corn trading at?", "2026-07-21",
                            client=_FakeClient("I can't reach that."), query_fn=lambda sql: [])
    assert out["futures_decline_guard"] == "named"
    assert out["answer"].startswith("One limitation to flag before the numbers:")
    assert "front-month" in out["answer"]


def test_answer_numbers_prepends_futures_decline_change():
    out = na.answer_numbers("How much has corn risen this month?", "2026-07-21",
                            client=_FakeClient("n/a"), query_fn=lambda sql: [])
    assert out["futures_decline_guard"] == "change"
    assert out["answer"].startswith("One limitation to flag before the numbers:")


def test_answer_numbers_level_ask_no_preface():
    # a plain single-date LEVEL ask carries no decline preface -> byte-identical to the model's text.
    out = na.answer_numbers("What is the front-month corn futures settle on 2026-06-05?", "2026-06-05",
                            client=_FakeClient("model text."), query_fn=lambda sql: [])
    assert "futures_decline_guard" not in out
    assert out["answer"] == "model text."


# -- SEAM C on the HYBRID lane: the curve/named decline survives the path that drops the agent's prose ---
# newcap-30 ncap_fut_corn_curve_decline failed because run_hybrid consumes `calls`, never `answer`: the
# agent declined in prose the reasoner never saw, and the served front-month LEVEL (449.5) was narrated as
# the December quote / the curve. The fix is the hybrid-lane twin of the preface, NOT a routing change --
# futures_scope also fires 'change' on genuine reasoning asks ("why has corn fallen this month"), so
# rerouting the class to numbers_only would demote real cascade turns.
_FUT_LEVEL_CALL = {"query": {"table": "silver_futures_prices", "metric": "close", "commodity": "corn_cbot",
                             "asof": "2026-07-21"},
                   "rows": [{"value": 449.5, "unit": "US cents/bushel", "knowledge_date": "2026-07-20"}],
                   "status": "ok", "handle": "L1"}
_PSD_CALL = {"query": {"table": "silver_psd", "metric": "production", "commodity": "corn"},
             "rows": [{"value": 377.0, "unit": "1000 MT"}], "status": "ok"}


@pytest.mark.parametrize("cls", ["curve", "named"])
def test_futures_hybrid_decline_neuters_the_level(cls):
    calls, preface = na.futures_hybrid_decline(cls, [_FUT_LEVEL_CALL, _PSD_CALL])
    assert calls[0]["rows"] == [] and calls[0]["status"] == "declined"     # no citable level survives
    assert calls[0]["scope_note"] == na.FUTURES_DECLINE_TEMPLATES[cls]     # the WHY rides into the prompt
    assert calls[0]["query"] == _FUT_LEVEL_CALL["query"]                   # provenance of the attempt kept
    assert calls[1] is _PSD_CALL                                           # every other table untouched
    assert preface.startswith("One limitation to flag before the numbers:") and "front-month" in preface
    assert _FUT_LEVEL_CALL["rows"][0]["value"] == 449.5                    # caller's record not mutated


@pytest.mark.parametrize("cls", [None, "change"])
def test_futures_hybrid_decline_is_a_noop_for_servable_classes(cls):
    # 'change' keeps the level: the template itself offers it ("I can give the front-month close level on a
    # date, but not how far it travelled"), and levels_only already rejects the windowed read. None = every
    # non-futures turn -> the SAME list object back, so the hybrid join is byte-identical.
    src = [_FUT_LEVEL_CALL, _PSD_CALL]
    calls, preface = na.futures_hybrid_decline(cls, src)
    assert calls is src and preface == ""


def test_futures_hybrid_decline_handles_empty_calls():
    calls, preface = na.futures_hybrid_decline("named", [])
    assert calls == [] and preface                                         # caveat still lands with no lookups


def test_declined_status_labels_as_a_decline_not_a_timing_claim():
    from leviathan.graphrag import citations as cit
    calls, _ = na.futures_hybrid_decline("curve", [_FUT_LEVEL_CALL])
    c = cit.from_number(calls[0], 1)
    assert c.value is None                                                 # eval price_cited filters on this
    assert "declined" in c.label and "not yet published" not in c.label


# -- run_hybrid end-to-end (fake numbers agent + fake reasoner) -----------------------------------------
def _corn_graph():
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    corn = cs.CausalContract(contract="corn", aliases=["corn"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+", mechanism="m")])
    return g.CausalGraph({"corn": corn}, silver=set())


def _fake_retrieve(q, contract, *, k, asof=None, near=None):
    return [{"date": "2012-07-20", "source": "GAIN", "source_key": "s3://x", "text": "drought"}]


_CURVE_Q = "What is December corn trading at, and what does the futures curve look like across the months?"


def _run_hybrid(monkeypatch, nums: dict, query: str) -> tuple[dict, dict]:
    from leviathan.graphrag import orchestrator as orch
    captured: dict = {}

    def fake_call(system, user, *, model, tool):
        captured["user"] = user if isinstance(user, str) else str(user)
        return {"tldr": "t", "mechanism": "m", "sources": []}

    monkeypatch.setattr(orch.na, "answer_numbers", lambda q, a, **kw: nums)
    out = orch.run_hybrid(query, "2026-07-21", graph=_corn_graph(), call=fake_call,
                          retrieve=_fake_retrieve, planner=None)
    return out, captured


def test_run_hybrid_curve_ask_declines(monkeypatch):
    nums = {"answer": "prose the hybrid path throws away", "calls": [dict(_FUT_LEVEL_CALL)],
            "futures_decline_guard": "named"}
    out, captured = _run_hybrid(monkeypatch, nums, _CURVE_Q)
    assert out["answer"].startswith("One limitation to flag before the numbers:")   # deterministic prepend
    assert out["trace"]["futures_decline_guard"] == "named"
    assert "449.5" not in captured["user"]                                  # the reasoner never sees the level
    assert "SCOPE NOTE" in captured["user"] and "FRONT-MONTH close only" in captured["user"]
    assert out["number_calls"][0]["status"] == "declined"
    fut = [c for c in out["citations"]
           if (c.get("locator") or {}).get("table") == "silver_futures_prices" and c.get("value") is not None]
    assert fut == []                                                        # eval price_cited -> false


def test_run_hybrid_level_ask_still_serves(monkeypatch):
    # no guard -> the front-month level reaches the reasoner and stays a valued citation, exactly as today.
    nums = {"answer": "model text.", "calls": [dict(_FUT_LEVEL_CALL)]}
    out, captured = _run_hybrid(monkeypatch, nums, "What is the front-month corn futures settle?")
    assert not out["answer"].startswith("One limitation")
    assert "futures_decline_guard" not in (out.get("trace") or {})
    assert "449.5" in captured["user"] and "SCOPE NOTE" not in captured["user"]
    assert out["number_calls"][0]["status"] == "ok" and out["number_calls"][0]["rows"]
    assert [c["value"] for c in out["citations"] if c["kind"] == "number"] == ["449.5"]


def test_run_hybrid_change_ask_keeps_the_level(monkeypatch):
    # 'change' is not neutered (the level is the honest partial serve) -- only the two unservable classes are.
    nums = {"answer": "x", "calls": [dict(_FUT_LEVEL_CALL)], "futures_decline_guard": "change"}
    out, captured = _run_hybrid(monkeypatch, nums, "How much has corn risen this month?")
    assert "449.5" in captured["user"]
    assert out["number_calls"][0]["status"] == "ok"
    assert "futures_decline_guard" not in (out.get("trace") or {})


def test_run_numbers_only_decline_lane_is_untouched(monkeypatch):
    # the numbers_only lane is BYTE-IDENTICAL: the agent's own preface is the whole decline there, the served
    # rows are not neutered, and no futures key is copied onto the trace (the guard list is unchanged).
    from leviathan.graphrag import orchestrator as orch
    nums = {"answer": na._futures_decline_preface("named") + "model text.",
            "calls": [dict(_FUT_LEVEL_CALL)], "futures_decline_guard": "named"}
    monkeypatch.setattr(orch.na, "answer_numbers", lambda q, a, **kw: nums)
    out = orch.run_numbers_only(_CURVE_Q, "2026-07-21")
    assert out["answer"].startswith("One limitation to flag before the numbers:")
    assert out["number_calls"][0]["status"] == "ok" and out["number_calls"][0]["rows"][0]["value"] == 449.5
    assert "futures_decline_guard" not in out["trace"]


# =======================================================================================================
# FUTURES v1.5 (ratified 2026-07-23, docs/private/FUTURES_V15_PLAN.md): W1 unit column single-sourced +
# W2 versioned roll policy + W2.3 roll-straddle regression + W4 provenance label + W3 no-overreach proof.
# =======================================================================================================
from pathlib import Path

import yaml as _yaml

from leviathan.transforms.bronze_to_silver.yfinance_futures import (
    SILVER_COLUMNS,
    build_futures_silver,
)
from leviathan.transforms.raw_to_bronze.yfinance_futures import TICKER_MAP, UNIT_MAP

_REPO = Path(__file__).resolve().parents[2]


# -- W1.2 single-source unit map: three-way equality + slug coverage ------------------------------------
def test_unit_map_three_way_equality():
    # transform UNIT_MAP == tracked lint constant == card unit_overrides -- the three historical copies
    # (card / _FUTURES_UNIT_OVERRIDES / transform) can never drift (check_futures_lite blocks b + b2).
    assert UNIT_MAP == cc._FUTURES_UNIT_OVERRIDES
    doc = cc._load("numbers/tables.yaml")
    ov = doc["tables"]["silver_futures_prices"]["metrics"]["close"]["unit_overrides"]
    assert ov == UNIT_MAP
    assert set(UNIT_MAP) == set(TICKER_MAP)          # every fetched slug carries a curated unit


# -- W1.2 transform emits the physical unit column (all rows non-null, == UNIT_MAP) ---------------------
def _bronze(slug: str, n: int = 8) -> "object":
    import pandas as pd
    dates = pd.date_range("2025-07-01", periods=n, freq="B")
    return pd.DataFrame({
        "date": dates.date, "leviathan_slug": slug,
        "close": [100.0 + i for i in range(n)],
        "log_return": [0.01] * n,
    })


def test_transform_emits_unit_from_unit_map():
    out = build_futures_silver([_bronze("corn_cbot"), _bronze("cocoa")])
    assert SILVER_COLUMNS[-1] == "unit" and "unit" in out.columns
    assert not out["unit"].isna().any()              # widen acceptance: all rows non-null
    per_slug = dict(out.groupby("leviathan_slug")["unit"].first())
    assert per_slug == {"corn_cbot": "US cents/bushel", "cocoa": "USD/metric ton"}


def test_transform_fails_closed_on_unknown_slug():
    import pytest as _pt
    with _pt.raises(ValueError, match="missing from UNIT_MAP"):
        build_futures_silver([_bronze("not_a_contract")])


# -- W1.1 registry contract: additive unit column + schema_version 2 + W2.2 roll policy ------------------
def _contract() -> dict:
    p = _REPO / "configs" / "silver" / "tables" / "silver_futures_prices.yaml"
    return _yaml.safe_load(p.read_text(encoding="utf-8"))


def test_registry_contract_unit_column_and_v2():
    c = _contract()
    names = [col["name"] for col in c["physical_columns"]]
    assert names[-1] == "unit" and len(names) == 11          # additive tail widen, nothing else moved
    ucol = c["physical_columns"][-1]
    assert (ucol["glue_type"], ucol["arrow_type"], ucol["target_arrow_type"], ucol["nullable"]) == (
        "string", "string", "string", True)                  # byte-matches the silver_wasde unit shape
    assert c["schema_version"] == 2                          # additive 1 -> 2 (D6: no consumer pins ==1)
    assert c["fingerprint"]["glue_nonpartition_cols"] == 11
    assert c["fingerprint"]["physical_parquet_cols"] == 11


def test_registry_roll_policy_versioned_note():
    rp = _contract()["provenance"]["roll_policy"]
    assert rp["roll_policy_version"] == 1
    for tok in ("chained UNADJUSTED", "vendor-undocumented", "NaN-masked"):
        assert tok in rp["policy"], tok


def test_card_notes_carry_roll_policy_and_provenance_label():
    card = cc._load("numbers/tables.yaml")["tables"]["silver_futures_prices"]
    notes = str(card.get("notes") or "")
    assert "roll_policy_version: 1" in notes                 # W2.2: the SAME versioned note, both places
    assert "vendor-undocumented" in notes
    # W4.2 (D4a): the verbatim provenance label a served futures [N] is framed with.
    assert "Yahoo Finance continuous front-month close (not official exchange settlement)" in notes


# -- FIX-LEG 2026-07-24: no surface may CALL the value a settle (W4.2 self-contradiction guard) ----------
def test_check_futures_lite_flags_settle_wording_in_card(monkeypatch):
    doc = cc._load("numbers/tables.yaml")
    card = doc["tables"]["silver_futures_prices"]
    card["description"] = str(card.get("description")) + " The served value is the front-month settle."
    monkeypatch.setattr(cc, "_load", lambda name: doc)
    assert any("calls the served value a settle" in e for e in cc.check_futures_lite())


def test_check_futures_lite_flags_settle_wording_in_template(monkeypatch):
    bad = dict(na.FUTURES_DECLINE_TEMPLATES)
    first = next(iter(bad))
    bad[first] = bad[first] + " -- the front-month settle only"
    monkeypatch.setattr(na, "FUTURES_DECLINE_TEMPLATES", bad)
    assert any("calls the value a settle" in e for e in cc.check_futures_lite())


def test_live_surfaces_never_say_settle_outside_label():
    # the LIVE surfaces themselves: templates carry NO settle token; the card's only settle token sits
    # inside the verbatim honest label (strip it -> no settle remains in the model-facing fields).
    import re as _re
    for t in na.FUTURES_DECLINE_TEMPLATES.values():
        assert not _re.search(r"(?i)settle", t)
    card = cc._load("numbers/tables.yaml")["tables"]["silver_futures_prices"]
    label = "Yahoo Finance continuous front-month close (not official exchange settlement)"
    text = " ".join([str(card.get("description") or ""), str(card.get("grain") or ""),
                     str(card["metrics"]["close"].get("desc") or ""), str(card.get("notes") or "")])
    assert label in text
    assert not _re.search(r"(?i)settle", text.replace(label, " "))


# -- W2.3 splice-boundary regression: a window straddling a KNOWN corn roll date raises ------------------
# Corn rolls ~July 14-15 each year (Jul->Dec handoff, raw_to_bronze docstring; 113 rolls 2000-2026).
# NOTE (plan skeptic F3, D3): the levels-only guard is deliberately roll-AGNOSTIC -- it rejects EVERY
# window/non-latest agg, which is exactly what makes a splice-crossing read unservable. This test pins
# the blanket rejection AT a concrete roll boundary, not a (nonexistent) roll-aware window path.
@pytest.mark.parametrize("kw", [
    {"agg": "latest", "period_start": "2025-07-01", "period_end": "2025-07-31"},   # straddles the Jul roll
    {"agg": "mean", "period_start": "2025-07-01", "period_end": "2025-07-31"},
    {"agg": "series", "period_start": "2025-06-30", "period_end": "2025-08-01"},
])
def test_levels_only_window_straddling_known_corn_roll_raises(kw):
    with pytest.raises(ValueError, match="levels-only"):
        Q.build_sql(_spec(**kw), _ts())


# -- The futures decline rows: the PHRASING guard still fires, and no pin outlives its data -------------
# REPLACES test_decline_deck_rows_still_pin_no_price (2026-07-31). That test asserted the pin TEXT
# (price_cited is False) and the futures_scope class -- both of which stayed GREEN through the whole W3
# flip while the pin itself went STALE: silver_futures_eod joined eval.py's price-table filter set the day
# it was whitelisted, corn_cbot's measured floor (2010-06-06) sits well before these rows' 2026-07-21
# as-of, and the ask is now SERVED. Six shipped rows across three decks would have RED-ed on correct
# behaviour with nothing in the suite to catch it. The invariant worth fencing is not the pin text, it is
# the AGREEMENT between the pin and the measured coverage route.
_DECLINE_DECK_ROWS = (
    ("eval_queries_v34_combined.yaml", "futures_corn_change_decline", "change"),
    ("eval_queries_v34_combined.yaml", "futures_corn_named_decline", "named"),
    ("eval_queries_v4_cascade.yaml", "futures_corn_change_decline", "change"),
    ("eval_queries_v4_cascade.yaml", "futures_corn_named_decline", "named"),
    ("eval_queries_newcap30.yaml", "ncap_fut_corn_change_decline", "change"),
    ("eval_queries_newcap30.yaml", "ncap_fut_corn_curve_decline", "named"),
)


@pytest.mark.parametrize("deck_name,rid,want_cls", _DECLINE_DECK_ROWS)
def test_decline_deck_rows_track_the_measured_coverage_route(deck_name, rid, want_cls):
    """A row may pin `price_cited: false` ONLY while the per-delivery-month table cannot serve its ask.

    The guard is the MEASURED floor, read through the same futures_eod_route the engine uses -- so the day
    a slug's canonical bytes reach a deck row's as-of, a stale no-price pin fails the BUILD instead of
    failing the run. The phrasing assertion is kept: futures_scope is a separate, still-live guard (the
    continuous card's caveat rides on it regardless of what the EOD table serves)."""
    deck = _yaml.safe_load((_REPO / "configs" / "graphrag" / deck_name).read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in (deck.get("queries") or []) if isinstance(r, dict) and "id" in r}
    row = rows[rid]
    assert na.futures_scope(row["question"]) == want_cls   # the phrasing guard still fires on the deck text
    spec = Q.NumberQuery(table="silver_futures_eod", metric="settle", asof=str(row["asof"]),
                         commodity="corn_cbot")
    route = na.futures_eod_route(spec)[0]
    if row["expect"].get("price_cited") is False:
        assert route != "serve", (
            f"{deck_name}:{rid} pins price_cited:false but silver_futures_eod routes {route!r} at "
            f"asof {row['asof']} -- the ask is SERVED and the pin is stale (re-pin or retire it)")
    else:                                                  # a served row must actually be servable
        assert route == "serve", (
            f"{deck_name}:{rid} does not pin price_cited:false but the slug routes {route!r} -- a served "
            f"pin on an unservable ask is the mirror-image staleness")
