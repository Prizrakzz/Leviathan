"""FIX SITTING 4 (2026-09-29), LANE T -- numbers/cascade.py, agent.py, stats.py, registry.py, query.py,
config_check.py, the `unit_spellings` block of tables.yaml (and the decks that pin them). Every pin below guards a
FACT the writer now sees or a CHECK beside it -- never a sentence the writer must copy.

  T4-1 (CONTRACT C4-16, the cascade half of sitting 3's M-B) -- `quantify` reads the numbers ledger off the BOARD
        REQUEST (the key never travels further), a reused figure keeps ONE handle, and an identity the ledger holds
        at another value is NAMED on the call (`identity_conflict`: both figures, the first handle).
  T4-2 (CONTRACT C4-15; OWNER DECISION O-S4-1 at its default) -- (a) "t" and "metric ton" are one quantity, declared
        once in tables.yaml `unit_spellings` and read by `registry.same_quantity`, handed to the calculator; (b) a
        spread only between two legs of ONE product class (`registry.product_class`: contract -> node -> the book's
        declared class group), a seed against an oil declining in the desk's words, decided before units and rates.
  T4-3 -- the currency refusal and the regional one-sided line state the true fact (no exchange rate is applied),
        never "a rate this platform does not hold" (PC-12).
  R4-3 by file (CONTRACT C4-10) -- the basin tail line's share at the footer's own precision under the analyst key.
  R4-4 (b) by file (CONTRACT C4-14) -- the cycle-fallback note in the desk's words where DESK_REGISTER is lit.
"""
from __future__ import annotations

import copy
import inspect
import pickle
import re

import pytest
from leviathan.graphrag import citations as CIT
from leviathan.graphrag import config_check as CC
from leviathan.graphrag import register as RG
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import cascade as CQ
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R
from leviathan.graphrag.numbers import stats as S

#: the classes and words CONTRACT C4-15 declares for the book (`state_conventions.yaml` `product_class_words`, lane R)
WORDS = {"oilseeds": "a seed", "vegetable_oils": "an oil", "oilseed_meals": "a meal", "grains": "a grain"}

# THE BANKED ROWS (arm-A palm/rape board, as-of 2026-09-26; read from the store read-only in sitting 3, lane T
# drive b58_store_reads.json): the shared session 2026-09-24 -- MATIF rapeseed 549.5 EUR/t, ZCE rapeseed oil
# 10,236 CNY/t, CME palm oil 1,181.0 USD/metric ton; the exchange-rate card 0.87974 EUR per USD, 6.7126 CNY per USD.
EUR_ROW = {"metric": "eur_usd", "rate": 0.87974, "date": "2026-09-24",
           "unit": "EUR per USD (ECB via Frankfurter)", "status": "ok"}
CNY_ROW = {"metric": "cny_usd", "rate": 6.7126, "date": "2026-09-24",
           "unit": "CNY per USD (ECB via Frankfurter)", "status": "ok"}
MATIF = ([552.0, 554.0, 549.5, 548.0], ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"], "EUR/t")
ZCE = ([10243.0, 10145.0, 10236.0], ["2026-09-22", "2026-09-23", "2026-09-24"], "CNY/t")
PALM = ([1195.25, 1180.25, 1181.0], ["2026-09-22", "2026-09-23", "2026-09-24"], "USD/metric ton")
CORN = ([527.5, 529.0], ["2026-09-21", "2026-09-22"], "US cents/bushel")
WHEAT = ([707.0, 708.5], ["2026-09-21", "2026-09-22"], "US cents/bushel")


def _lvl(a, b, **kw):
    return S.pair_level_spread(a[0], a[1], a[2], b[0], b[1], b[2], **kw)


def _cls(slug):
    return R.product_class(slug, class_words=WORDS)


def _clean(probe: str) -> None:
    assert not RG.register_leaks(probe), probe
    assert not RG.exec_leaks(probe), probe
    assert not RG.internal_leaks(probe), probe
    assert not RG.desk_register_hits(probe), probe
    assert RG.count_valuation_words(probe) == 0 and RG.count_flow_words(probe) == 0
    assert probe.isascii()
    for mr in (RG.FENCED, RG.OUTLOOK):
        assert RG.sanitize(probe, market_register=mr) == probe


# ═══ T4-2 (b): THE PRODUCT CLASS OF A CONTRACT ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("slug,key,words", [
    ("french_rapeseed_matif", "oilseeds", "a seed"),
    ("canola_ice", "oilseeds", "a seed"),
    ("malaysian_crude_palm_oil_cme", "vegetable_oils", "an oil"),
    ("rapeseed_oil_zce", "vegetable_oils", "an oil"),
    ("soybean_oil_cbot", "vegetable_oils", "an oil"),
    ("soybean_meal_cbot", "oilseed_meals", "a meal"),
    ("rapeseed_meal_zce", "oilseed_meals", "a meal"),
    ("corn_cbot", "grains", "a grain"),
    ("soft_red_winter_wheat_cbot", "grains", "a grain"),
    ("french_wheat_matif", "grains", "a grain"),
])
def test_t42b_a_contract_reads_its_class_off_the_hierarchy_and_the_book(slug, key, words):
    c = _cls(slug)
    assert c == key and isinstance(c, str) and c.words == words
    assert hash(c) == hash(key)                                         # a class compares as its key


@pytest.mark.parametrize("slug", ["cocoa", "raw_sugar", "cotton", "arabica_coffee", "soybeans", "", None,
                                  "no_such_contract"])
def test_t42b_no_class_where_the_hierarchy_or_the_book_declares_none(slug):
    """cocoa / sugar / cotton / coffee sit in no declared class; `soybeans` is a graph NODE, not a contract (S4-1's
    generic slug) -- none of them is ever given a guessed class."""
    assert _cls(slug) is None


def test_t42b_a_node_in_two_declared_classes_is_never_a_guess_and_no_book_is_no_class():
    h = {"contracts": {"x_cbot": {"node": "x"}}, "groups": {"g1": ["x"], "g2": ["x"], "g3": ["y"]}}
    assert R.product_class("x_cbot", hierarchy=h, class_words={"g1": "a one", "g2": "a two"}) is None
    assert R.product_class("x_cbot", hierarchy=h, class_words={"g1": "a one", "g3": "a three"}) == "g1"
    assert R.product_class("x_cbot", hierarchy=h, class_words={}) is None
    assert R.product_class("x_cbot", hierarchy=h, class_words={"g1": "  "}) is None     # no words, no class


def test_t42b_the_class_keeps_its_words_through_copy_and_pickle():
    c = _cls("french_rapeseed_matif")
    for d in (copy.copy(c), copy.deepcopy(c), pickle.loads(pickle.dumps(c))):
        assert d == "oilseeds" and d.words == "a seed"


def test_t42b_the_books_key_is_the_contracts_and_the_live_book_agrees_where_it_declares_one():
    """The lint (config_check roster tail) is clean on the tree's book; where lane R's book declares the key, the
    live reader agrees with CONTRACT C4-15's words class for class."""
    assert R.check_product_classes() == [] == CC.check_product_class_words()
    live = R._product_class_words()
    if live:
        assert live == WORDS
        assert R.product_class("french_rapeseed_matif").words == "a seed"
        assert R.product_class("malaysian_crude_palm_oil_cme").words == "an oil"


def test_t42b_the_lint_names_a_foreign_key_a_bad_word_shared_words_and_a_contract_in_two_classes():
    h = {"contracts": {"x_cbot": {"node": "x"}}, "groups": {"g1": ["x"], "g2": ["x"]}}
    errs = R.check_product_classes(hierarchy=h, class_words={"g1": "a one", "g2": "a one", "nope": "a_2"})
    joined = "\n".join(errs)
    assert "'nope' is not a commodity_hierarchy groups key" in joined
    assert "carry a digit or an underscore" in joined
    assert "share the words" in joined
    assert "contract 'x_cbot' (node 'x') sits in 2 declared classes" in joined
    assert R.check_product_classes(hierarchy=h, class_words={"g1": "a one"}) == []


def test_t42b_the_roster_carries_the_lint_at_its_tail():
    labels = re.findall(r'\("([a-z0-9_]+)", (?:check_|lint_)', inspect.getsource(CC.main))
    assert labels[-1] == "product_class_words" and labels[-2] == "wasde_line_map" and len(labels) == 45


# ═══ T4-2 (b): A SEED AGAINST AN OIL DECLINES BY NAME, BEFORE UNITS AND RATES ════════════════════════════════════
def test_t42b_matif_rapeseed_against_cme_palm_oil_declines_in_the_desks_words_before_any_rate():
    kw = dict(currency_a="EUR", currency_b="USD", label_a="MATIF rapeseed", label_b="CME palm oil",
              class_a=_cls("french_rapeseed_matif"), class_b=_cls("malaysian_crude_palm_oil_cme"))
    want = ("MATIF rapeseed is a seed and CME palm oil is an oil -- a spread is read only between two legs of one "
            "product class, so no figure is computed")
    for extra in ({}, {"fx_a": EUR_ROW, "fx_b": {}}, {"fx_a": EUR_ROW, "same_quantity": R.same_quantity}):
        r = _lvl(MATIF, PALM, **kw, **extra)
        assert r["declined"] is True and r["guard"] == S.CLASS_GUARD and r["value"] is None
        assert r["reason"] == want and "converted" not in r
        assert r["classes"] == "oilseeds vs vegetable_oils"
    # even an EMPTY leg: the class is a property of the pair, decided first
    assert _lvl(([], [], "EUR/t"), PALM, **kw)["guard"] == S.CLASS_GUARD
    # the smoke's copied words never come back on this pair
    assert "unit spellings" not in want and "one quantity" not in want


def test_t42b_the_decline_words_are_register_clean_and_a_class_key_never_prints():
    r = _lvl(MATIF, PALM, currency_a="EUR", currency_b="USD", label_a="MATIF rapeseed", label_b="CME palm oil",
             class_a=_cls("french_rapeseed_matif"), class_b=_cls("malaysian_crude_palm_oil_cme"))
    _clean(S.PRODUCT_CLASS_DECLINE)
    _clean(r["reason"])
    assert "oilseeds" not in r["reason"] and "vegetable_oils" not in r["reason"] and "_" not in r["reason"]


def test_t42b_a_same_class_pair_and_a_classless_pair_are_HEADs_call_dict_for_dict():
    kw = dict(currency_a="USD", currency_b="USD", label_a="CBOT corn", label_b="CBOT srw wheat")
    head = _lvl(CORN, WHEAT, **kw)
    assert head["value"] == pytest.approx(529.0 - 708.5)
    assert _lvl(CORN, WHEAT, class_a=_cls("corn_cbot"), class_b=_cls("soft_red_winter_wheat_cbot"), **kw) == head
    assert _lvl(CORN, WHEAT, class_a=None, class_b=_cls("corn_cbot"), **kw) == head
    assert _lvl(CORN, WHEAT, class_a=_cls("cocoa"), class_b=_cls("corn_cbot"), **kw) == head
    # a class handed WITHOUT its declared words is read as no class: a refusal never prints a class key
    assert _lvl(CORN, WHEAT, class_a="oilseeds", class_b="grains", **kw) == head


# ═══ T4-2 (a): ONE QUANTITY, DECLARED ONCE ═══════════════════════════════════════════════════════════════════════
def test_t42a_the_declaration_is_one_line_of_the_mt_class_and_tons_stays_its_own():
    sp = R.unit_spellings()
    assert sp["mt"] == ("mt", "tonne", "tonnes", "t", "metric ton", "metric tons")
    assert sp["tons"] == ("tons", "ton")                                # a bare "tons" is printed SHORT too
    assert "short ton" not in sp["mt"]


@pytest.mark.parametrize("a,b,same", [
    ("USD/t", "USD/metric ton", True), ("usd/T", "USD/Metric Tons", True), ("CNY/t", "CNY/t", True),
    ("tonnes", "MT", True),
    ("EUR/t", "USD/metric ton", False),           # two currencies: never one price unit
    ("USD/t", "USD/short ton", False),            # a short ton is not a tonne
    ("US cents/bushel", "USD/bushel", False),     # cents are not dollars
    ("USD/tons", "USD/t", False),                 # "tons" is its own class
    ("USD/t", "t", False), ("", "t", False), (None, None, False),
])
def test_t42a_same_quantity_reads_the_declared_classes_and_nothing_else(a, b, same):
    assert R.same_quantity(a, b) is same


def test_t42a_palm_against_zce_rapeseed_oil_is_one_class_and_one_tonne_so_the_spread_is_computed():
    """The pair S4-2 seats for "rapeseed oil": both oils; ZCE's CNY/t put in USD by its own rate is "USD/t", palm is
    "USD/metric ton" -- one tonne BY DECLARATION, so the calculator sizes the spread (no arithmetic in the writer's
    head). Without the reader handed, the refusal claims nothing about the declaration."""
    kw = dict(currency_a="USD", currency_b="CNY", label_a="CME palm oil", label_b="ZCE rapeseed oil",
              fx_a={}, fx_b=CNY_ROW, class_a=_cls("malaysian_crude_palm_oil_cme"), class_b=_cls("rapeseed_oil_zce"))
    r = _lvl(PALM, ZCE, same_quantity=R.same_quantity, **kw)
    assert r["declined"] is False and r["date"] == "2026-09-24" and r["unit"] == "USD/metric ton"
    assert r["value"] == pytest.approx(1181.0 - 10236.0 / 6.7126) and r["value"] == pytest.approx(-343.8934839)
    assert set(r["converted"]) == {"b"} and r["converted"]["b"]["from"] == "CNY"
    unread = _lvl(PALM, ZCE, **kw)
    assert unread["declined"] is True and unread["guard"] == S.UNIT_GUARD
    assert unread["reason"] == S.FX_UNIT_UNREAD_DECLINE.format(base="USD", a="USD/metric ton", b="USD/t from CNY/t")
    assert "declared unit spellings" not in unread["reason"]
    _clean(S.FX_UNIT_UNREAD_DECLINE)
    # a genuinely different quantity still refuses, and with the reader handed HEAD's words stand (true)
    meal = _lvl(([420.0], ["2026-09-24"], "USD/short ton"), ([2400.0], ["2026-09-24"], "CNY/t"),
                currency_a="USD", currency_b="CNY", fx_a={}, fx_b=CNY_ROW, same_quantity=R.same_quantity)
    assert meal["declined"] is True and meal["guard"] == S.UNIT_GUARD
    assert meal["reason"] == S.FX_UNIT_DECLINE.format(base="USD", a="USD/short ton", b="USD/t from CNY/t")


def test_t42a_a_reader_that_raises_or_answers_nonsense_is_a_no():
    def boom(a, b):
        raise RuntimeError("x")
    for sq in (boom, lambda a, b: "yes", lambda a, b: 1):
        assert S._units_one("USD/t", "USD/metric ton", sq) is False
    assert S._units_one("USD/t", "usd/t ", None) is True                # HEAD's rule first


def test_t42_stats_stays_a_pure_leaf():
    src = open(S.__file__, encoding="utf-8").read()
    for banned in ("import os", "open(", "import boto3", "numbers import registry", "numbers.registry",
                   "load_registry", "load_conventions", "state import"):
        assert banned not in src, banned


# ═══ T4-3: THE TRUE FACT, NEVER "A RATE THIS PLATFORM DOES NOT HOLD" ═════════════════════════════════════════════
def test_t43_the_currency_refusal_states_that_no_rate_is_applied():
    r = _lvl(MATIF, PALM, currency_a="EUR", currency_b="USD", label_a="MATIF rapeseed", label_b="CME palm oil")
    assert r["guard"] == S.CURRENCY_GUARD
    assert r["reason"] == S.CURRENCY_MISMATCH_DECLINE.format(a="EUR", b="USD")
    assert "does not hold" not in S.CURRENCY_MISMATCH_DECLINE
    assert "no exchange rate is applied to either figure" in S.CURRENCY_MISMATCH_DECLINE
    for probe in (S.CURRENCY_MISMATCH_DECLINE, r["reason"]):
        assert not RG.register_leaks(probe) and not RG.exec_leaks(probe) and RG.sanitize(probe) == probe


def _one_sided_body(monkeypatch):
    KC, MATIF_W = "hard_red_winter_wheat_kcbt", "french_wheat_matif"
    pink = [{"knowledge_date": f"{2021 + (i + 8) // 12}-{(i + 8) % 12 + 1:02d}-01", "value": str(240 + i)}
            for i in range(60)]

    def fake_fetch(qfn, **kw):
        if kw.get("table") == CQ._RV_EOD_TABLE:
            return {"query": {"table": CQ._RV_EOD_TABLE, "metric": "settle", "commodity": kw.get("commodity"),
                              "asof": kw.get("asof")},
                    "rows": [{"value": "215.25", "unit": "EUR/t", "knowledge_date": "2026-08-28",
                              "contract_month": "2026-09", "currency": "EUR"}], "status": "ok"}
        return {"query": {"table": kw.get("table"), "metric": kw.get("metric"), "asof": kw.get("asof")},
                "rows": pink, "status": "ok"}

    monkeypatch.setattr(CQ, "fetch_window", fake_fetch)
    fired = {"window": "MY2023-MY2024", "commodityA": KC, "commodityB": MATIF_W, "dA": -2.0, "dB": 1.0,
             "regional": True}
    era = [("2023-06-01", "2024-05-31")]
    lines, tr = CQ._rv_price_reading(None, KC, MATIF_W, fired, None, "2026-09-01", [], 0, era, regional=True)
    return lines, tr


def test_t43_PC12_the_regional_one_sided_line_states_no_rate_is_applied(monkeypatch):
    lines, tr = _one_sided_body(monkeypatch)
    if not lines:
        pytest.skip(f"the one-sided rung did not render on this fixture: {tr}")
    body = "\n".join(lines)
    assert tr["eod_level"] is True
    assert "does not hold" not in body
    assert ("no cross-currency comparison is made between the two boards -- a difference needs one unit, and no "
            "exchange rate is applied to either figure.") in body
    assert RG.register_leaks(body) == [] and not CQ._RV_REGIONAL_BANNED_RX.search(body)


def test_t43_PC12_the_source_carries_no_does_not_hold_claim_on_any_served_line():
    src = inspect.getsource(CQ)
    assert "exchange rate this platform does not hold" not in src


# ═══ T4-1: THE LEDGER ON THE BOARD REQUEST; A CONFLICT NAMED ═════════════════════════════════════════════════════
def _erec(value, my, era_idx, key):
    return {"query": {"commodity": "wheat", "country": "Russia", "period": f"MY{my}", "metric": "exports_mt",
                      "asof": f"{my}-06-01", "table": "silver_psd"},
            "rows": [{"value": str(value), "release_date": f"{my}-05-12"}], "status": "ok",
            "node_key": key, "leg": ("era", era_idx), "era_idx": era_idx, "my": my}


def _kept(*keys):
    row = {"table": "silver_psd", "metric": "exports_mt", "scale": 1, "narrate_unit": "MMT",
           "period_type": "marketing_year"}
    return [{"specs": [{"node_key": k}], "row": row} for k in keys]


def test_t41_an_identity_at_another_value_keeps_its_handle_and_is_named_with_both_figures():
    k1, k2 = ("wheat", "export"), ("wheat", "policy")
    recs = [_erec(10, 2020, 0, k1), _erec(14, 2021, 0, k1), _erec(10, 2020, 0, k2), _erec(15, 2021, 0, k2)]
    calls: list = []
    led = CIT.NumbersLedger([], n_start=1)
    lines, _t, _d = CQ._assemble(copy.deepcopy(recs), _kept(k1, k2), 0, calls, numbers_ledger=led)
    assert len(calls) == 7 and led.stamp()["reused"] == 1 and led.stamp()["identity_value_conflict"] == 3
    conf = [(i + 1, c[CQ.IDENTITY_CONFLICT_KEY]) for i, c in enumerate(calls) if CQ.IDENTITY_CONFLICT_KEY in c]
    assert len(conf) == 3                                              # every conflict the ledger counted is named
    level = [(h, c) for h, c in conf if c["values"] == [14.0, 15.0]]
    assert len(level) == 1
    h, c = level[0]
    assert c["with"] == 2 and h == 5                                   # MY2021 at 14 is [N2]; at 15 it is [N5]
    assert calls[c["with"] - 1]["rows"][0]["value"] == 14.0 and calls[h - 1]["rows"][0]["value"] == 15.0
    assert c["row_id"] and "silver_psd" in c["row_id"] and "exports_mt" in c["row_id"]
    for h, c in conf:                                                  # the first handle is always EARLIER, never a merge
        assert 1 <= c["with"] < h and c["values"][0] != c["values"][1]
    # both handles print on the lines: nothing struck, nothing merged
    printed = {int(x) for ln in lines for x in re.findall(r"\[N(\d+)\]", ln)}
    assert printed == set(range(1, 8))


def test_t41_where_the_ledger_keeps_its_own_record_the_call_carries_that_record():
    """ONE producer for the stamp and the call: a ledger that answers `conflict_of` (lane V's reader, C4-16) hands the
    call its own record; a ledger without it (HEAD's) is named by this lane's reading of the same identity."""
    k1, k2 = ("wheat", "export"), ("wheat", "policy")
    recs = [_erec(14, 2021, 0, k1), _erec(15, 2021, 0, k2)]

    class _Rec(CIT.NumbersLedger):
        def conflict_of(self, handle):
            return {"with": 1, "values": ["first", "second"], "row_id": "the ledger's own words"} if handle == 2 else None

    calls: list = []
    CQ._assemble(copy.deepcopy(recs), _kept(k1, k2), 0, calls, numbers_ledger=_Rec([], n_start=1))
    assert calls[1][CQ.IDENTITY_CONFLICT_KEY] == {"with": 1, "values": ["first", "second"],
                                                  "row_id": "the ledger's own words"}

    class _Broken(CIT.NumbersLedger):
        def conflict_of(self, handle):
            raise RuntimeError("x")

    calls2: list = []
    CQ._assemble(copy.deepcopy(recs), _kept(k1, k2), 0, calls2, numbers_ledger=_Broken([], n_start=1))
    c = calls2[1][CQ.IDENTITY_CONFLICT_KEY]
    assert c["with"] == 1 and c["values"] == [14.0, 15.0] and "silver_psd" in c["row_id"]


def test_t41_the_conflict_key_never_perturbs_a_later_reuse():
    """A THIRD read of the conflicting value (15) reuses [N5] -- the stamped key is provenance, not identity."""
    k1, k2, k3 = ("wheat", "export"), ("wheat", "policy"), ("wheat", "stocks")
    recs = [_erec(14, 2021, 0, k1), _erec(15, 2021, 0, k2), _erec(15, 2021, 0, k3)]
    calls: list = []
    led = CIT.NumbersLedger([], n_start=1)
    lines, _t, _d = CQ._assemble(copy.deepcopy(recs), _kept(k1, k2, k3), 0, calls, numbers_ledger=led)
    assert len(calls) == 2 and CQ.IDENTITY_CONFLICT_KEY in calls[1] and led.stamp()["reused"] == 1
    assert "[N2]" in lines[-1]


def test_t41_no_ledger_is_HEADs_assemble_and_no_conflict_key_is_ever_written():
    k1, k2 = ("wheat", "export"), ("wheat", "policy")
    recs = [_erec(10, 2020, 0, k1), _erec(14, 2021, 0, k1), _erec(10, 2020, 0, k2), _erec(15, 2021, 0, k2)]
    a_calls, b_calls = [], []
    a = CQ._assemble(copy.deepcopy(recs), _kept(k1, k2), 0, a_calls)
    b = CQ._assemble(copy.deepcopy(recs), _kept(k1, k2), 0, b_calls, numbers_ledger=None)
    assert a == b and a_calls == b_calls and len(a_calls) == 8
    assert not any(CQ.IDENTITY_CONFLICT_KEY in c for c in a_calls)


class _SG:
    def __init__(self):
        self.trace = {}


def _quantify_spy(monkeypatch, board, **kw):
    """Drive the REAL `quantify` to its base wave with one fake grounded node, spying on what `_select_nodes` /
    `_derive_windows` see and what `_assemble` is handed."""
    seen: dict = {"select": [], "derive": [], "assemble": []}

    class _N:
        id, contract, node = "drv", "wheat_x", "drv"

    def sel(sg, graph, b=None):
        seen["select"].append(b)
        return [_N()]

    def der(n, near, asof, b=None):
        seen["derive"].append(b)
        return [("2020-06-01", "2021-05-31")]

    def asm(records, kept, base, calls, **k):
        seen["assemble"].append(dict(k))
        return [], [], {}

    monkeypatch.setattr(CQ, "_select_nodes", sel)
    monkeypatch.setattr(CQ, "_derive_windows", der)
    monkeypatch.setattr(CQ, "_silver_ref", lambda n: "psd:exports")
    monkeypatch.setattr(CQ, "map_row", lambda ref: {"table": "silver_psd", "metric": "exports_mt"})
    monkeypatch.setattr(CQ, "_scope", lambda n, row: ("wheat", "Russia"))
    monkeypatch.setattr(CQ, "_region_row", lambda n, row: row)
    monkeypatch.setattr(CQ, "_node_specs", lambda *a, **k: [{"node_key": ("wheat", "drv"), "table": "silver_psd"}])
    monkeypatch.setattr(CQ, "_run_one", lambda qfn, s, **k: {"status": "silent", "rows": [], "node_key": s["node_key"],
                                                             "leg": ("era", 0)})
    monkeypatch.setattr(CQ, "_assemble", asm)
    extra: list = []
    CQ.quantify(_SG(), None, qfn=None, asof="2026-09-26", near=None, extra_number_calls=extra, board=board, **kw)
    return seen


def test_t41_quantify_reads_the_ledger_off_the_board_request_and_the_key_goes_no_further(monkeypatch):
    led = CIT.NumbersLedger([], n_start=1)
    board = {"order": (), "windows": {}, "calls": [], "display": "analyst", "numbers_ledger": led}
    seen = _quantify_spy(monkeypatch, board)
    assert seen["assemble"] and seen["assemble"][0].get("numbers_ledger") is led
    for b in seen["select"] + seen["derive"]:
        assert isinstance(b, dict) and "numbers_ledger" not in b and b.get("display") == "analyst"
    assert "numbers_ledger" in board                                   # the caller's dict is never mutated


def test_t41_a_callers_kwarg_wins_and_a_board_without_the_key_is_HEADs_request(monkeypatch):
    led_kw, led_board = CIT.NumbersLedger([], n_start=1), CIT.NumbersLedger([], n_start=1)
    seen = _quantify_spy(monkeypatch, {"order": (), "numbers_ledger": led_board}, numbers_ledger=led_kw)
    assert seen["assemble"][0].get("numbers_ledger") is led_kw
    plain = {"order": (), "windows": {}, "calls": []}
    seen2 = _quantify_spy(monkeypatch, plain)
    assert "numbers_ledger" not in seen2["assemble"][0]                # omit-when-off: HEAD's call
    assert seen2["select"][0] is plain                                 # the very dict HEAD passed, untouched


# ═══ R4-3 (by file): THE TAIL SHARE AT THE FOOTER'S OWN PRECISION ════════════════════════════════════════════════
def _tail():
    key = ("cocoa", "heat")
    r = {"query": {"table": "gold_weather_z", "metric": "tmax_anomaly_tail_share", "commodity": "cocoa",
                   "country": "West Africa", "asof": "2026-04-15", "start": "2025-04-15", "end": "2026-04-15"},
         "rows": [{"value": 0.09090909090909091, "country": "West Africa"}], "status": "ok",
         "leg": ("tail", None), "node_key": key}
    kept = [{"specs": [{"node_key": key}], "row": {"table": "gold_weather_z", "metric": "tmax_anomaly", "scale": 1,
                                                    "narrate_unit": "z"}}]
    return r, kept


def test_r43_off_the_analyst_key_the_tail_line_is_HEADs_bytes():
    r, kept = _tail()
    lines, _tr = CQ._tail_legs([copy.deepcopy(r)], kept, 75, [])
    assert lines == ["- [N76] share of the basin's cells at or beyond +2 sigma in max-temperature anomaly (as-of "
                     "2026-04-15): 9.09091 % [series: cocoa; country: West Africa; table: GOLD WEATHER Z]"]
    assert CQ._tail_legs([copy.deepcopy(r)], kept, 75, [], display="not_analyst")[0] == lines


def test_r43_under_the_analyst_key_the_tail_line_prints_the_footers_own_figure():
    """The probe page's [N76]: the line printed 9.09091 while its footer printed 9.09; the writer spelled the line."""
    r, kept = _tail()
    calls: list = []
    lines, _tr = CQ._tail_legs([copy.deepcopy(r)], kept, 75, calls, display=CQ.CW_DISPLAY_ANALYST)
    assert ": 9.09 % [series:" in lines[0] and "9.09091" not in lines[0]
    foot = CIT.from_number(dict(calls[0], display="analyst"), 76).label
    assert foot.endswith("= 9.09 %")
    assert calls[0]["shown"] == [pytest.approx(9.090909090909092)]     # the bound magnitude is NOT moved


# ═══ R4-4 (b) (by file): THE CYCLE-FALLBACK NOTE IN THE DESK'S WORDS ═════════════════════════════════════════════
FALLBACK_ROW = {"roll_method": Q.CYCLE_FALLBACK_METHOD, "contract_month": "2026-11",
                "roll_method_fallback": "open_interest->" + Q.CYCLE_FALLBACK_METHOD,
                "front_expiry_session": "2026-09-28"}


def test_r44b_desk_off_is_HEADs_note_byte_for_byte():
    head = ("the front-month rule could not run on this session because the activity figure it reads (open "
            "interest) is not published for it yet, so this row is the nearest listed delivery that is not in its "
            "delivery month, November 2026 -- quote it as that delivery month and never as 'the front month' or "
            "'the price'")
    assert Q.cycle_fallback_note(FALLBACK_ROW) == head == Q.cycle_fallback_note(FALLBACK_ROW, desk=False)
    assert Q.cycle_fallback_note({"roll_method": "open_interest"}, desk=True) == ""


def test_r44b_desk_on_states_the_store_fact_and_names_no_machine():
    s = Q.cycle_fallback_note(FALLBACK_ROW, desk=True)
    assert s == ("open interest for the 28 September 2026 session is not in the store yet, so this figure is for the "
                 "November 2026 delivery, the nearest listed that is not in its delivery month -- quote it as that "
                 "delivery month, never as 'the front month' or 'the price'")
    assert "rule" not in s and "could not run" not in s
    assert not RG.desk_register_hits(s) and not RG.register_leaks(s) and not RG.internal_leaks(s)
    assert RG.sanitize(s) == s and s.isascii()
    # the metric is the stamp's own (a volume venue is told volume), and no session means HEAD's words
    vol = dict(FALLBACK_ROW, roll_method_fallback="volume->" + Q.CYCLE_FALLBACK_METHOD)
    assert Q.cycle_fallback_note(vol, desk=True).startswith("volume for the 28 September 2026 session")
    for bad in (None, "", "2026-9-28", "yesterday"):
        assert Q.cycle_fallback_note(dict(FALLBACK_ROW, front_expiry_session=bad), desk=True) == \
            Q.cycle_fallback_note(FALLBACK_ROW)


def test_r44b_the_seat_reads_the_desk_flag_in_the_estates_one_grammar(monkeypatch):
    from leviathan.graphrag import answer as AN
    read = 'os.environ.get("GRAPHRAG_DESK_REGISTER", "").strip().lower() in ("on", "1", "true")'
    assert read in inspect.getsource(A._desk_register_on) and read in inspect.getsource(AN._desk_register_on)
    for v, on in (("on", True), ("1", True), ("TRUE", True), ("", False), ("off", False), ("yes", False)):
        monkeypatch.setenv("GRAPHRAG_DESK_REGISTER", v)
        assert A._desk_register_on() is on is AN._desk_register_on()
    monkeypatch.delenv("GRAPHRAG_DESK_REGISTER", raising=False)
    assert A._desk_register_on() is False
    src = inspect.getsource(A)
    assert 'Q.cycle_fallback_note(vals[0], **({"desk": True} if _desk_register_on() else {}))' in src
