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


# -- W3.3 / acceptance 6: the two decline deck rows STILL pin price_cited=false (no overreach) ----------
def test_decline_deck_rows_still_pin_no_price():
    deck = _yaml.safe_load((_REPO / "configs" / "graphrag" / "eval_queries_v34_combined.yaml")
                           .read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in (deck.get("queries") or []) if isinstance(r, dict) and "id" in r}
    for rid, want_cls in (("futures_corn_change_decline", "change"),
                          ("futures_corn_named_decline", "named")):
        row = rows[rid]                                       # the PERMANENT-decline negatives (W3.3)
        assert row["expect"]["price_cited"] is False
        assert na.futures_scope(row["question"]) == want_cls  # the guard still fires on the deck phrasing
