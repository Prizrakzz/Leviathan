"""SEAM C -- futures v1.5-lite (Option A, LEVELS-ONLY) surface tests. Pure/hermetic -- no AWS, no LLM, no
pg. Covers: the whitelist-absent-until-gate registry drop, the levels-only build_sql guard + DP-5 substr
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


# -- registry: registered-but-WHITELIST-ABSENT (dropped from serving until the gate flips) --------------
def test_futures_whitelist_absent_by_default():
    # the card is in WHITELIST_ABSENT_DEFAULT (intentional gate state) and DROPPED from the served registry
    # (the agent tool enum / system-prompt cards), so it can never serve before the gate + freshness fix.
    assert "silver_futures_prices" in R.WHITELIST_ABSENT_DEFAULT
    assert "silver_futures_prices" not in R.load_registry().tables


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
