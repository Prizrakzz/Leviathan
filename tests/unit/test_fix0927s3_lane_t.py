"""FIX SITTING 3 (09-27 plan, built 09-29), LANE T -- numbers/stats.py, agent.py, cascade.py, registry.py,
config_check.py (and the decks that pin them). Every pin below guards a FACT the writer now sees or a CHECK beside
it -- never a sentence the writer must copy.

  U-8 (engine half, CONTRACT Z13)  -- the cross-currency spread LEVEL: each leg put in one base currency by its OWN
        exchange-rate row, the conversion stated on the result, or a refusal that NAMES the missing rate;
        `registry.fx_metric_for` reads the exchange-rate card's own unit words.
  U-9 (row half, CONTRACT Z7)      -- the declared sign beside the consequence line's relation words and the
        cell's served verdict stamped on its legs' calls, both under the analyst display key only.
  M-2 (CONTRACT Z15)               -- the seat's and the cascade's year_month reads take the publication lag under
        GRAPHRAG_YM_PUBLICATION_LAG (default off -> HEAD's SQL).
  M-3 / OI-3 b (CONTRACT Z16)      -- the base wave asks the board turn's numbers ledger before it mints.
  OI-3 a (CONTRACT Z25, PC-7)      -- a pace row declares its derivation; the label names it.
  ORCH-P4 (CONTRACT Z27)           -- the WASDE line-map lint joins config_check's roster at the tail.
"""
from __future__ import annotations

import copy
import datetime as _dt
import inspect
import os
import re
from types import SimpleNamespace

import pytest
from leviathan.graphrag import citations as CIT
from leviathan.graphrag import config_check as CC
from leviathan.graphrag import register as RG
from leviathan.graphrag.numbers import agent as A
from leviathan.graphrag.numbers import cascade as CQ
from leviathan.graphrag.numbers import query as Q
from leviathan.graphrag.numbers import registry as R
from leviathan.graphrag.numbers import stats as S

# ═══ U-8: THE CROSS-CURRENCY SPREAD LEVEL ════════════════════════════════════════════════════════════════════════
# THE HAND-CHECKED BANKED ROWS, read from the store 2026-09-29 (read-only Athena, lane T drive
# `drives/b58_store_reads.json`): the arm-A palm/rape board (as-of 2026-09-26) printed MATIF rapeseed November 2026
# and ZCE rapeseed oil January 2027; their newest SHARED session is 2026-09-24, where MATIF settled 549.5 EUR/t, ZCE
# 10,236 CNY/t, and the exchange-rate card read 0.87974 EUR per USD and 6.7126 CNY per USD.
EUR_ROW = {"metric": "eur_usd", "rate": 0.87974, "date": "2026-09-24",
           "unit": "EUR per USD (ECB via Frankfurter)", "status": "ok"}
CNY_ROW = {"metric": "cny_usd", "rate": 6.7126, "date": "2026-09-24",
           "unit": "CNY per USD (ECB via Frankfurter)", "status": "ok"}
MATIF = ([552.0, 554.0, 549.5, 548.0], ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"], "EUR/t")
ZCE = ([10243.0, 10145.0, 10236.0], ["2026-09-22", "2026-09-23", "2026-09-24"], "CNY/t")
PALM = ([1195.25, 1180.25, 1181.0], ["2026-09-22", "2026-09-23", "2026-09-24"], "USD/metric ton")
KW_MZ = dict(currency_a="EUR", currency_b="CNY", label_a="MATIF rapeseed", label_b="ZCE rapeseed oil")
KW_MP = dict(currency_a="EUR", currency_b="USD", label_a="MATIF rapeseed", label_b="CME palm oil")


def _lvl(a, b, **kw):
    return S.pair_level_spread(a[0], a[1], a[2], b[0], b[1], b[2], **kw)


def test_u8_no_exchange_rate_row_is_HEADs_call_byte_for_byte_on_every_guard():
    """Both rows None -> HEAD's function exactly, the currency refusal included (the SEAT never passes a row, so
    its words stay HEAD's -- the seat-path wording is docketed, LEFTOVERS E)."""
    cases = [
        (([], [], "EUR/t"), PALM, KW_MP),                                          # empty leg
        (MATIF, PALM, KW_MP),                                                      # currency
        (([1.0], ["2026-09-24"], "USD/t"), ([2.0], ["2026-09-24"], "USD/metric ton"),
         dict(currency_a="USD", currency_b="USD")),                                # units
        (([1.0], ["2026-09-23"], "USD/t"), ([2.0], ["2026-09-24"], "USD/t"),
         dict(currency_a="USD", currency_b="USD")),                                # no shared period
        (([5.0, 6.0], ["a", "b"], "USD/t"), ([1.0, 2.0], ["a", "b"], "USD/t"), {}),  # computes
    ]
    for a, b, kw in cases:
        assert _lvl(a, b, **kw) == _lvl(a, b, fx_a=None, fx_b=None, **kw)
    head = _lvl(MATIF, PALM, **KW_MP)
    # MOVED 2026-09-29 (FIX SITTING 4, LANE T, T4-3 -- "the seat-path 'does not hold' words"): the currency refusal's
    # last clause said an exchange rate "this platform does not hold" -- false (the card holds fourteen crosses); it
    # now states the true fact, in the CW_XCCY_CLAUSE precedent's words. The claim kept: both rows None is the
    # function the seat calls, byte for byte (the equality above), and the refusal is the currency guard's.
    assert head["guard"] == S.CURRENCY_GUARD and "does not hold" not in head["reason"]
    assert "no exchange rate is applied to either figure" in head["reason"]


def test_u8_a_rate_row_on_a_pair_whose_currencies_agree_changes_nothing():
    a, b = ([100.0, 101.0], ["2026-09-21", "2026-09-22"], "US cents/bushel"), \
           ([90.0, 95.0], ["2026-09-21", "2026-09-22"], "US cents/bushel")
    kw = dict(currency_a="USD", currency_b="USD", label_a="CBOT corn", label_b="CBOT srw wheat")
    base = _lvl(a, b, **kw)
    for fa, fb in (({}, {}), (EUR_ROW, None), ({"status": "fx_stale"}, CNY_ROW)):
        assert _lvl(a, b, fx_a=fa, fx_b=fb, **kw) == base
    assert base["value"] == 6.0 and "converted" not in base


def test_u8_the_converted_level_is_value_over_rate_on_the_hand_checked_banked_rows():
    """U8-a: a rate quoted "<quote> per <base>" converts by DIVISION, read off the card's own words. U8-c: each
    non-base leg by its OWN rate, no cross rate. The level is the calculator's row, never the writer's."""
    r = _lvl(MATIF, ZCE, fx_a=EUR_ROW, fx_b=CNY_ROW, **KW_MZ)
    assert r["declined"] is False and r["date"] == "2026-09-24" and r["unit"] == "USD/t" and r["n"] == 3
    assert r["a_value"] == pytest.approx(549.5 / 0.87974) and r["a_value"] == pytest.approx(624.6163639)
    assert r["b_value"] == pytest.approx(10236.0 / 6.7126) and r["b_value"] == pytest.approx(1524.8934839)
    assert r["value"] == pytest.approx(549.5 / 0.87974 - 10236.0 / 6.7126)
    assert r["value"] == pytest.approx(-900.2771199702515)
    assert r["converted"] == {
        "a": {"from": "EUR", "rate": 0.87974, "rate_date": "2026-09-24",
              "rate_unit": "EUR per USD (ECB via Frankfurter)", "metric": "eur_usd"},
        "b": {"from": "CNY", "rate": 6.7126, "rate_date": "2026-09-24",
              "rate_unit": "CNY per USD (ECB via Frankfurter)", "metric": "cny_usd"}}
    assert r["value"] != pytest.approx(549.5 * 0.87974 - 10236.0 * 6.7126)      # never the rate the wrong way
    # one leg already in the base: only the other converts, and the unit is the base leg's OWN spelling
    usd_t = ([640.0], ["2026-09-24"], "USD/t")
    one = _lvl(MATIF, usd_t, fx_a=EUR_ROW, fx_b={}, currency_a="EUR", currency_b="USD")
    assert one["value"] == pytest.approx(549.5 / 0.87974 - 640.0) and one["unit"] == "USD/t"
    assert set(one["converted"]) == {"a"}


def test_u8_palm_against_MATIF_rapeseed_refuses_by_unit_and_names_both_units():
    """The banked palm/rape pair (MATIF rapeseed EUR/t against CME palm oil USD/metric ton). Put in USD the MATIF
    leg is quoted per "t", the palm leg per "metric ton": the estate's declared unit vocabulary does not equate the
    two spellings, and this module never maps a unit (U8-b, U8-f), so the refusal NAMES both -- and it no longer
    claims the platform holds no exchange rate (it holds fourteen). Also fences U8-d: no seed-versus-oil spread."""
    # MOVED 2026-09-29 (FIX SITTING 4, LANE T, T4-2 -- the spread's two laws ruled together): tables.yaml now declares
    # "t" and "metric ton" members of the "mt" class, so the clause "which the declared unit spellings do not show to
    # be one quantity" is true only where the declaration was READ. With no reader handed (this call) the refusal
    # names both units and claims nothing about the declaration (FX_UNIT_UNREAD_DECLINE); with the reader handed the
    # two are one tonne, and the seed-versus-oil fence (U8-d) is now the PRODUCT-CLASS decline, decided before any
    # unit or rate step. The claims kept: both units named, never "they differ", never "does not hold", and no
    # seed-versus-oil spread on the board (which passes the classes).
    r = _lvl(MATIF, PALM, fx_a=EUR_ROW, fx_b={}, **KW_MP)
    assert r["declined"] is True and r["guard"] == S.UNIT_GUARD and r["value"] is None
    assert r["reason"] == S.FX_UNIT_UNREAD_DECLINE.format(base="USD", a="USD/t from EUR/t", b="USD/metric ton")
    assert "USD/t from EUR/t" in r["reason"] and "USD/metric ton" in r["reason"] and "differ" not in r["reason"]
    assert "does not hold" not in r["reason"] and "declared unit spellings" not in r["reason"]
    words = {"oilseeds": "a seed", "vegetable_oils": "an oil"}
    ca = R.product_class("french_rapeseed_matif", class_words=words)
    cb = R.product_class("malaysian_crude_palm_oil_cme", class_words=words)
    board = _lvl(MATIF, PALM, fx_a=EUR_ROW, fx_b={}, class_a=ca, class_b=cb, same_quantity=R.same_quantity, **KW_MP)
    assert board["declined"] is True and board["guard"] == S.CLASS_GUARD and "converted" not in board
    assert board["reason"] == ("MATIF rapeseed is a seed and CME palm oil is an oil -- a spread is read only between "
                               "two legs of one product class, so no figure is computed")


@pytest.mark.parametrize("fx,why", [
    ({"status": "no_fx_series", "metric": None}, "no_fx_series"),
    ({"status": "fx_stale", "metric": "eur_usd"}, "fx_stale"),
    ({"status": "read_error", "metric": "eur_usd"}, "read_error"),
    ({"status": "something_new"}, "unusable"),
    (dict(EUR_ROW, rate=0.0), "unusable"),
    (dict(EUR_ROW, rate="n/a"), "unusable"),
    (dict(EUR_ROW, unit="CNY per USD (ECB via Frankfurter)"), "unusable"),       # a rate for ANOTHER currency
    (dict(EUR_ROW, unit="pct"), "unusable"),
    (dict(EUR_ROW, date="September 24"), "unusable"),
])
def test_u8_a_leg_without_a_usable_rate_declines_naming_its_currency_and_why(fx, why):
    usd_t = ([640.0], ["2026-09-24"], "USD/t")
    r = _lvl(MATIF, usd_t, fx_a=fx, fx_b={}, currency_a="EUR", currency_b="USD", label_a="MATIF rapeseed")
    assert r["declined"] is True and r["guard"] == S.FX_GUARD
    assert r["reason"] == S.FX_SERIES_MISSING_DECLINE.format(which="MATIF rapeseed", ccy="EUR",
                                                             why=S.FX_UNAVAILABLE_WHY[why])


def test_u8_the_other_refusals_name_what_is_missing():
    usd_t = ([640.0], ["2026-09-24"], "USD/t")
    none = _lvl(MATIF, usd_t, fx_a={}, fx_b={}, currency_a="EUR", currency_b="USD")
    assert none["guard"] == S.FX_GUARD and none["reason"] == S.FX_NONE_SERVED_DECLINE.format(a="EUR", b="USD")
    # ZCE's CNY leg has no usable row while MATIF's EUR row is fine: the CNY leg is named, never a cross rate built
    half = _lvl(MATIF, ZCE, fx_a=EUR_ROW, fx_b={"status": "no_fx_series"}, **KW_MZ)
    assert half["guard"] == S.FX_GUARD and "ZCE rapeseed oil is priced in CNY" in half["reason"]
    two = _lvl(MATIF, ZCE, fx_a=EUR_ROW, fx_b=dict(CNY_ROW, unit="CNY per GBP"), **KW_MZ)
    assert two["guard"] == S.FX_GUARD and two["reason"] == S.FX_TWO_BASES_DECLINE.format(
        qa="EUR", ba="USD", qb="CNY", bb="GBP")
    # the rate is dated AFTER the session both legs share: one day's figure is never priced at another day's rate
    late = _lvl(MATIF, ZCE, fx_a=dict(EUR_ROW, date="2026-09-25", rate=0.87696), fx_b=CNY_ROW, **KW_MZ)
    assert late["guard"] == S.FX_GUARD and late["reason"] == S.FX_RATE_AFTER_SESSION_DECLINE.format(
        ccy="EUR", rate_date="2026-09-25", date="2026-09-24")
    # HEAD's own refusals keep their order: an empty leg is an empty read before any currency question
    empty = _lvl(([], [], "EUR/t"), ZCE, fx_a=EUR_ROW, fx_b=CNY_ROW, **KW_MZ)
    assert empty["guard"] == S.EMPTY_GUARD
    nosh = _lvl(([549.5], ["2026-09-25"], "EUR/t"), ([10236.0], ["2026-09-24"], "CNY/t"),
                fx_a=EUR_ROW, fx_b=CNY_ROW, **KW_MZ)
    assert nosh["guard"] == S.THIN_GUARD


def test_u8_the_legs_and_the_rate_rows_are_never_touched():
    """U8-e: the conversion lives on the derived level alone -- the served legs' own series and the feeder's rows
    reach the caller exactly as they were handed in."""
    a, b, fa, fb = copy.deepcopy(MATIF), copy.deepcopy(ZCE), copy.deepcopy(EUR_ROW), copy.deepcopy(CNY_ROW)
    _lvl(a, b, fx_a=fa, fx_b=fb, **KW_MZ)
    assert (a, b, fa, fb) == (MATIF, ZCE, EUR_ROW, CNY_ROW)


@pytest.mark.parametrize("name", ["FX_SERIES_MISSING_DECLINE", "FX_NONE_SERVED_DECLINE", "FX_UNIT_DECLINE",
                                  "FX_TWO_BASES_DECLINE", "FX_RATE_AFTER_SESSION_DECLINE"])
def test_u8_the_refusal_proses_are_register_clean_under_both_registers(name):
    """Held to the bar agent.STAT_DECLINE_TEMPLATES is held to, plus the internal-leak register: the board prints
    a refusal verbatim on its ASKED SPREAD line."""
    t = getattr(S, name)
    rendered = t.format(which="MATIF rapeseed", ccy="EUR", why=S.FX_UNAVAILABLE_WHY["fx_stale"], a="EUR",
                        b="USD", base="USD", qa="EUR", ba="USD", qb="CNY", bb="GBP", rate_date="2026-09-25",
                        date="2026-09-24")
    for probe in (t, rendered):
        assert not RG.register_leaks(probe), (name, probe)
        assert not RG.exec_leaks(probe), (name, probe)
        assert not RG.internal_leaks(probe), (name, probe)
        assert not RG.desk_register_hits(probe), (name, probe)          # no machinery word ("row", "page", ...)
        assert RG.count_valuation_words(probe) == 0 and RG.count_flow_words(probe) == 0
        assert not re.search(r"(?i)settle", probe) and probe.isascii()
        for mr in (RG.FENCED, RG.OUTLOOK):
            assert RG.sanitize(probe, market_register=mr) == probe, (name, mr)
    for why in S.FX_UNAVAILABLE_WHY.values():
        assert not RG.register_leaks(why) and not RG.internal_leaks(why) and why.isascii()
        assert not RG.desk_register_hits(why)


def test_u8_fx_quote_parts_reads_the_cards_own_unit_words():
    assert S.fx_quote_parts("EUR per USD (ECB via Frankfurter)") == ("EUR", "USD")
    assert S.fx_quote_parts("CNY per USD") == ("CNY", "USD")
    for bad in ("pct", "", None, "per USD", "EUR per", "USD per USD"):
        assert S.fx_quote_parts(bad) is None


def test_u8_fx_metric_for_is_the_cascade_cross_map_on_its_four_currencies():
    """CONTRACT Z13 / W8-c: the ONE currency -> exchange-rate metric answer, read off the card; it must agree with
    the cascade walk's own map wherever that map speaks (the map is not touched this sitting)."""
    for ccy, (metric, _label) in CQ._CW_FX_CROSS.items():
        assert R.fx_metric_for(ccy) == metric
    assert R.fx_base_currency() == "usd"
    for none in ("USD", "", "XYZ", None):
        assert R.fx_metric_for(none) is None
    assert R.FX_TABLE == CQ._CW_FX_TABLE


def test_u8_fx_metric_for_reads_the_unit_words_never_the_iso_code():
    """The rejected lexical form is `code.lower() + '_usd'`: a metric whose NAME says eur but whose declared unit
    says another currency is never the euro's rate; a card quoting two bases names no conversion target."""
    def reg(metrics):
        ts = SimpleNamespace(metrics={k: SimpleNamespace(unit=u) for k, u in metrics.items()})
        return SimpleNamespace(get=lambda _t: ts)
    r1 = reg({"eur_usd": "GBP per USD", "zzz": "EUR per USD (x)"})
    assert R.fx_metric_for("EUR", reg=r1) == "zzz" and R.fx_metric_for("GBP", reg=r1) == "eur_usd"
    r2 = reg({"a": "EUR per USD", "b": "CNY per GBP"})
    assert R.fx_metric_for("EUR", reg=r2) is None and R.fx_base_currency(reg=r2) is None
    r3 = reg({"a": "EUR per USD", "b": "EUR per USD (dup)"})
    assert R.fx_metric_for("EUR", reg=r3) is None                            # two claimants: never a guess


def test_u8_TRIPWIRE_the_declared_unit_vocabulary_equates_no_two_contract_quantities():
    """MOVED 2026-09-29 (FIX SITTING 4, LANE T, T4-2 a -- the tripwire FIRED as designed): tables.yaml `unit_spellings`
    now joins "t" and "metric ton" in the "mt" class, and the remedy this pin named is taken -- the equality is routed
    through the declared vocabulary: `registry.same_quantity` is its reader and `stats.pair_level_spread` takes it as
    an argument (`same_quantity`), still importing no registry. The claim kept, restated for the new state: over
    every per-delivery-month contract quantity the board can seat, the stats rule WITH the reader handed agrees with
    the declared classes pair for pair, and exactly ONE pair of different spellings is joined today (t, metric ton)
    -- a second join reds here and is read before it ships."""
    from leviathan.silver import futures_eod_contracts as FC
    quantities = sorted({str(r.get("unit") or "").partition("/")[2].strip().casefold()
                         for r in FC.CONTRACT_MAP.values() if "/" in str(r.get("unit") or "")} - {""})
    assert "t" in quantities and "metric ton" in quantities                  # the two the palm/rape pair meets
    cls = {}
    for canon, members in (R.unit_spellings() or {}).items():
        for m in members:
            cls[R.normalise_unit_phrase(m)] = canon
    classes = {q: cls.get(R.normalise_unit_phrase(q), q) for q in quantities}
    joined = set()
    for q1 in quantities:
        for q2 in quantities:
            if q1 == q2:
                continue
            same = classes[q1] == classes[q2]
            assert S._units_one("USD/" + q1, "USD/" + q2, R.same_quantity) is same, (q1, q2)
            assert S._units_one("USD/" + q1, "USD/" + q2) is False, (q1, q2)           # no reader: HEAD's rule
            if same:
                joined.add(tuple(sorted((q1, q2))))
    assert joined == {("metric ton", "t")}, joined


def test_u8_stats_stays_a_pure_leaf_and_the_engine_tuple_is_unchanged():
    src = open(S.__file__, encoding="utf-8").read()
    for banned in ("import os", "open(", "import boto3", "numbers import registry", "numbers.registry",
                   "load_registry"):
        assert banned not in src, banned
    assert "pair_level_spread" in S.ENGINE_STAT_NAMES and "fx_quote_parts" not in S.STAT_REGISTRY
    sig = inspect.signature(S.pair_level_spread).parameters
    # MOVED 2026-09-29 (FIX SITTING 4, LANE T, CONTRACT C4-15): the tail gains `class_a` / `class_b` (the product
    # class decline) and `same_quantity` (the declared unit vocabulary's reader, handed in -- never imported). The
    # claim kept: a pure leaf whose every added keyword defaults to None, so a caller that passes none is HEAD's.
    assert list(sig)[-5:] == ["fx_a", "fx_b", "class_a", "class_b", "same_quantity"]
    assert all(sig[k].default is None for k in ("fx_a", "fx_b", "class_a", "class_b", "same_quantity"))


# ═══ U-9: THE DECLARED SIGN BESIDE THE CONSEQUENCE VERDICT ═══════════════════════════════════════════════════════
def test_u9_off_the_analyst_key_the_relation_words_are_HEADs():
    for rel, words in CQ._CW_RELATION_WORDS.items():
        for sign in ("+", "-", "0", "", None, "?"):
            assert CQ.cw_relation_words(rel, sign) == words
            assert CQ.cw_relation_words(rel, sign, display="not_analyst") == words


def test_u9_under_the_analyst_key_each_relation_carries_its_declared_sign_from_the_one_vocabulary():
    from leviathan.graphrag.state import rows as SR
    for rel, words in CQ._CW_RELATION_WORDS.items():
        for sign, sw in SR.SIGN_WORDS.items():
            assert CQ.cw_relation_words(rel, sign, display=CQ.CW_DISPLAY_ANALYST) == f"{words}, declared to move {sw}"
        assert CQ.cw_relation_words(rel, "?", display=CQ.CW_DISPLAY_ANALYST) == words     # never a guessed sign
    # the max page's defect: one relation, two declared signs, two different facts
    plus = CQ.cw_relation_words("competes_with", "+", display=CQ.CW_DISPLAY_ANALYST)
    minus = CQ.cw_relation_words("competes_with", "-", display=CQ.CW_DISPLAY_ANALYST)
    assert plus != minus and "opposite direction" in minus and "same direction" in plus
    with pytest.raises(KeyError):
        CQ.cw_relation_words("no_such_relation", "+", display=CQ.CW_DISPLAY_ANALYST)


def test_u9_the_verdict_line_keeps_HEADs_bytes_off_the_key():
    """`_cw_verdict_mid` is lifted VERBATIM out of `_cw_verdict_line`; the flag-off line is HEAD's string."""
    ln = CQ._cw_verdict_line
    tail = "; the moves above are the record, in-sample on the named window only, never extended beyond it."
    assert ln("A", "B", "aligned") == "CONSEQUENCE READ A and B: the declared relation held on this firing" + tail
    assert ln("A", "B", "at_odds") == ("CONSEQUENCE READ A and B: the two moves sat at odds with the declared "
                                       "relation on this firing" + tail)
    assert ln("A", "B", "undetermined") == ("CONSEQUENCE READ A and B: the record declines to read a direction on "
                                            "this firing -- state that plainly" + tail)
    assert ln("A", "B", "undetermined", reason="fx_flips_sign").startswith(
        "CONSEQUENCE READ A and B: the exchange rate between the two settlement currencies moved further over "
        "this window than the board priced in it did, and it moved the same way, so the record declines to read "
        "a direction on this firing -- state that plainly")


def test_u9_the_episode_verdict_is_the_cells_served_fact_in_the_lines_own_words():
    an = CQ.CW_DISPLAY_ANALYST
    ev = CQ.cw_episode_verdict("soybean_meal_cbot", "soybean_oil_cbot", ["competes_with"], "-", "at_odds",
                               display=an, handles=("N246", "N247"))
    assert ev == {"legs": ["soybean_meal_cbot", "soybean_oil_cbot"], "relation": "competes_with", "sign": "-",
                  "verdict": "at_odds",
                  "verdict_words": {"aligned": CQ._cw_verdict_mid("aligned", display=an),
                                    "at_odds": CQ._cw_verdict_mid("at_odds", display=an)},
                  "handles": ["N246", "N247"]}
    assert ev["verdict_words"]["at_odds"] in CQ._cw_verdict_line("x", "y", "at_odds", display=an)
    assert "handles" not in CQ.cw_episode_verdict("a", "b", ["r"], "+", "aligned", handles=(None, "N2"))


# the walk harness (the test_cascade_walk convention: a hermetic tape through an injected qfn, a shaped graph over
# REAL slugs, the REAL shipped slice resolver) -- copied, not imported, so this deck owns what it pins.
_ASOF = "2026-07-31"
_ROOT, _CHILD = "corn_cbot", "soft_red_winter_wheat_cbot"
_WS, _WE, _SPAN = "2021-03-05", "2021-06-25", "2021-03..2021-06"
_LIFE = {"2021-05": ("2021-02-15", "2021-05-10"), "2021-07": ("2021-02-15", "2021-07-12"),
         "2021-09": ("2021-02-15", "2021-08-15"), "2021-12": ("2021-02-15", "2021-08-15")}


def _tape(px0=500.0, px1=575.0):
    d, end, out = _dt.date.fromisoformat("2021-02-15"), _dt.date.fromisoformat("2021-08-15"), []
    while d <= end:
        iso = d.isoformat()
        for cm, (first, last) in _LIFE.items():
            if first <= iso <= last:
                settle = (px0 if iso <= _WS else px1) if cm == "2021-07" else 400.0
                out.append({"value": settle, "knowledge_date": iso, "contract_month": cm,
                            "unit": "US cents/bushel", "currency": "USD", "settle_kind": "settlement"})
        d += _dt.timedelta(days=1)
    return out


def _walk(sign="-", display=None):
    edge = {"seed": _ROOT, "contract": _CHILD, "relation": "competes_with", "sign": sign, "lag": "0-1 quarters",
            "blurb": "one board's demand spills into the other", "mechanism": "m"}
    nodes = {_ROOT: "corn", _CHILD: "srw_wheat"}
    graph = SimpleNamespace(
        contracts={_ROOT: SimpleNamespace(drivers=[SimpleNamespace(id="heat")])},
        rev_cross_links=lambda c: [dict(edge)] if nodes.get(c, c) == "corn" else [],
        contract_node=lambda c: nodes.get(c, c))
    sg = SimpleNamespace(nodes=[], fired_regimes=[], trace={
        "episodes_injected": [{"node": "heat", "line": "DATED EPISODES for heat ...", "spans": [_SPAN],
                               "windows": [{"start": _WS, "end": _WE, "span": _SPAN, "n": 7}]}],
        "quantify_wave_reads": 0})
    rows = {_ROOT: _tape(), _CHILD: _tape()}

    def qfn(sql):
        return next((list(r) for s, r in rows.items() if s in (sql or "")), [])
    calls: list = []
    lines, payload = CQ._cascade_walk_leg_or_nothing(sg, graph, {"focus_contract": _ROOT}, qfn, _ASOF, calls,
                                                     **({"display": display} if display else {}))
    return lines, payload, calls


def test_u9_the_walk_stamps_both_legs_and_prints_the_sign_under_the_analyst_key_only():
    off_lines, off_payload, off_calls = _walk("-")
    assert off_payload["outcome"] == "fired" and len(off_calls) == 2
    assert not any("episode_verdict" in c for c in off_calls)                 # off the key: no call gains a key
    hop = next(ln for ln in off_lines if ln.startswith("CONSEQUENCE HOP"))
    assert "compete for the same demand;" not in hop and "declared to move" not in hop
    assert "compete for the same demand -- " in hop                         # HEAD's words, then the blurb
    an = CQ.CW_DISPLAY_ANALYST
    lines, payload, calls = _walk("-", display=an)
    assert payload["outcome"] == "fired" and len(calls) == 2
    hop = next(ln for ln in lines if ln.startswith("CONSEQUENCE HOP"))
    assert "compete for the same demand, declared to move in the opposite direction" in hop
    read = next(ln for ln in lines if ln.startswith("CONSEQUENCE READ"))
    # both boards rose +15 % against a relation declared to run the OPPOSITE way: the served verdict is at odds
    for c in calls:
        ev = c["episode_verdict"]
        assert ev["legs"] == [_ROOT, _CHILD] and ev["sign"] == "-" and ev["verdict"] == "at_odds"
        assert ev["relation"] == "competes_with" and ev["handles"] == ["N1", "N2"]
        assert ev["verdict_words"]["at_odds"] in read
    # the same pair declared '+' reads aligned, and says so in the stamp
    _l, _p, calls_p = _walk("+", display=an)
    assert {c["episode_verdict"]["verdict"] for c in calls_p} == {"aligned"}


def test_u9_config_check_holds_the_analyst_words_orientation_free():
    """U9-a: the composed words stay under config_check's directional-verb lint (clause ii-b); the walk clause is
    green on the tree."""
    src = inspect.getsource(CC.check_cascade_walk)
    assert "cw_relation_words(rel, sg_, display=_cq.CW_DISPLAY_ANALYST)" in src
    assert CC.check_cascade_walk() == []


# ═══ M-2: THE SEAT'S PUBLICATION LAG ════════════════════════════════════════════════════════════════════════════
def test_m2_the_switch_is_off_by_default_and_reads_the_opt_in_grammar(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_YM_PUBLICATION_LAG", raising=False)
    assert A._ym_lag_on() is False and A._ym_lag_kw() == {} and CQ._seat_ym_lag_kw() == {}
    for v, on in (("on", True), ("1", True), ("TRUE", True), ("yes", False), ("off", False), ("", False)):
        monkeypatch.setenv("GRAPHRAG_YM_PUBLICATION_LAG", v)
        assert A._ym_lag_on() is on
        assert CQ._seat_ym_lag_kw() == ({"ym_lag": True} if on else {})


def test_m2_every_seat_read_spreads_the_one_kwarg_and_the_cascade_owns_no_env_read():
    src_a = open(A.__file__, encoding="utf-8").read()
    body = src_a[src_a.index("def _esr_aggregate_legs"):]
    assert body.count("Q.run(") == body.count("**_ym_lag_kw()") == 6
    src_c = open(CQ.__file__, encoding="utf-8").read()
    assert "os.environ" not in src_c and "import os" not in src_c          # [SKEPTIC F3], unchanged
    fw = inspect.getsource(CQ.fetch_window)
    assert "**_roll, **_seat_ym_lag_kw()" in fw


def test_m2_the_kwarg_is_ABSENT_off_and_True_on_at_the_seat_and_the_cascade(monkeypatch):
    seen: list = []

    def spy(spec, **kw):
        seen.append(("ym_lag" in kw, kw.get("ym_lag")))
        return []
    monkeypatch.setattr(Q, "run", spy)
    for flag, want in ((None, (False, None)), ("on", (True, True))):
        if flag:
            monkeypatch.setenv("GRAPHRAG_YM_PUBLICATION_LAG", flag)
        else:
            monkeypatch.delenv("GRAPHRAG_YM_PUBLICATION_LAG", raising=False)
        seen.clear()
        CQ.fetch_window(None, table="gold_weather_z", metric="drought_z", commodity="soybeans_cbot",
                        country="United States", t1="2025-09-24", t2="2026-09-24", asof="2026-09-24")
        A._esr_aggregate_legs({"commodity": "soybeans_cbot", "metric": "weekly_exports_1000mt", "period": "2026"},
                              "2026-09-24", None)
        assert seen and set(seen) == {want}


def test_m2_the_measured_chirps_leak_is_withheld_under_the_switch():
    """resmoke_0924 deep_rv [N249] / deep_state_rice [N15]: an August 2026 drought_z (the metric's declared lag, 25
    days -> knowable 2026-09-25) served at as-of 2026-09-24. Under the switch the month bound is July; off it,
    HEAD's September bound. A card whose metric declares no lag, and every other card class, compiles HEAD's SQL."""
    ts = R.load_registry().get("gold_weather_z")
    spec = Q.NumberQuery(table="gold_weather_z", metric="drought_z", asof="2026-09-24", commodity="rough_rice_cbot",
                         country="United States", agg="latest")
    off, on = Q.build_sql(spec, ts), Q.build_sql(spec, ts, ym_lag=True)
    bound = re.compile(r"\(\s*\w+\s*\*\s*100\s*\+\s*\w+\s*\)\s*<=\s*(\d{6})")
    assert bound.findall(off) == ["202609"] and bound.findall(on) == ["202607"]
    assert bound.sub("B", off) == bound.sub("B", on)
    esr = R.load_registry().get("silver_esr")
    e = Q.NumberQuery(table="silver_esr", metric="weekly_exports_1000mt", asof="2026-09-24",
                      commodity="soybeans_cbot", agg="latest", period="2026")
    assert Q.build_sql(e, esr) == Q.build_sql(e, esr, ym_lag=True)


# ═══ OI-3 a: THE PACE ROW DECLARES ITS DERIVATION (PC-7, declared in sitting 2) ═══════════════════════════════════
def _pace_rec():
    return {"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt", "commodity": "soybeans_cbot",
                      "country": None, "start": "2026-07-18", "end": "2026-09-26", "asof": "2026-09-26"},
            "rows": [{"value": "700", "data_date": "2026-09-10"}, {"value": "775.4", "data_date": "2026-09-17"}],
            "status": "ok"}


def test_oi3a_the_pace_row_declares_kind_of_and_grain_beside_the_slug_it_keeps():
    row = {"table": "silver_esr", "metric": "weekly_exports_1000mt", "narrate_unit": "1000 MT", "scale": 1}
    c = CQ._pace_synth(_pace_rec(), row, 75.4, 1, kind="pace_change", unit="1000 MT")
    assert c["query"]["metric"] == "weekly_exports_1000mt_pace_change"        # the slug is kept
    assert c["query"]["derived"] == {"kind": "pace_change", "of": "weekly_exports_1000mt", "grain": "week"}
    s = CQ._pace_synth(_pace_rec(), row, 3, 2, kind="pace_streak", unit="weeks")
    assert s["query"]["derived"] == {"kind": "pace_streak", "of": "weekly_exports_1000mt", "grain": "week"}
    assert set(c["query"]["derived"]) == set(("kind", "of", "grain"))
    assert c["query"]["derived"]["kind"] in CIT.PACE_DERIVED_KINDS
    # a map row with no pace grain (a marketing-year card) declares nothing: HEAD's label
    my = dict(row, table="silver_psd", period_type="marketing_year")
    assert "derived" not in CQ._pace_synth(_pace_rec(), my, 1.0, 1, kind="pace_change", unit="MMT")["query"]


def test_oi3a_PC7_the_label_names_the_derivation_and_its_own_week_never_the_slug():
    row = {"table": "silver_esr", "metric": "weekly_exports_1000mt", "narrate_unit": "1000 MT", "scale": 1}
    c = CQ._pace_synth(_pace_rec(), row, 75.4, 1, kind="pace_change", unit="1000 MT")
    label = CIT.from_number(c, 1).label
    assert "change from the prior week" in label and "week to 17 September 2026" in label
    assert "_pace_change" not in label and "2026-07-18" not in label


# ═══ M-3 / OI-3 b: THE BASE WAVE ASKS THE NUMBERS LEDGER ═════════════════════════════════════════════════════════
def _erec(value, my, era_idx, key):
    return {"query": {"commodity": "wheat", "country": "Russia", "period": f"MY{my}", "metric": "exports_mt",
                      "asof": f"{my}-06-01", "table": "silver_psd"},
            "rows": [{"value": str(value), "release_date": f"{my}-05-12"}], "status": "ok",
            "node_key": key, "leg": ("era", era_idx), "era_idx": era_idx, "my": my}


def _kept(*keys):
    row = {"table": "silver_psd", "metric": "exports_mt", "scale": 1, "narrate_unit": "MMT",
           "period_type": "marketing_year"}
    return [{"specs": [{"node_key": k}], "row": row} for k in keys]


def _two_drivers_one_series():
    """The same PSD series read for two drivers: two groups, identical records -- the measured duplicate class."""
    k1, k2 = ("wheat", "export"), ("wheat", "policy")
    recs = [_erec(10, 2020, 0, k1), _erec(14, 2021, 0, k1), _erec(10, 2020, 0, k2), _erec(14, 2021, 0, k2)]
    return recs, _kept(k1, k2)


def test_oi3b_quantify_takes_the_ledger_at_its_tail_and_None_is_HEAD():
    p = inspect.signature(CQ.quantify).parameters
    assert list(p)[-1] == "numbers_ledger" and p["numbers_ledger"].default is None
    assert list(p)[-2] == "board"
    recs, kept = _two_drivers_one_series()
    head_calls, tree_calls = [], []
    head = CQ._assemble(copy.deepcopy(recs), kept, 0, head_calls)
    tree = CQ._assemble(copy.deepcopy(recs), kept, 0, tree_calls, numbers_ledger=None)
    assert head == tree and head_calls == tree_calls and len(head_calls) == 8   # 2 levels + delta + pct, twice


def test_oi3b_one_series_read_for_two_drivers_is_ONE_handle_when_the_ledger_is_asked():
    recs, kept = _two_drivers_one_series()
    calls: list = []
    led = CIT.NumbersLedger([], n_start=1)
    lines, _t, _d = CQ._assemble(copy.deepcopy(recs), kept, 0, calls, numbers_ledger=led)
    assert len(calls) == 4                                     # two levels + delta + pct, minted ONCE
    handles = [re.findall(r"\[N(\d+)\]", ln) for ln in lines]
    printed = sorted({int(h) for hs in handles for h in hs})
    assert printed == [1, 2, 3, 4]                             # every printed handle is a real call
    assert led.stamp()["reused"] == 4 and led.stamp()["issued"] == 4
    assert lines[:4] == lines[4:]                              # the second driver's lines print the same handles
    # every reused handle's call IS the same served row (identity and value), never a neighbour
    for ln in lines:
        for h in re.findall(r"\[N(\d+)\]", ln):
            assert 1 <= int(h) <= len(calls)


def test_oi3b_different_facts_are_never_merged_and_an_out_of_step_ledger_is_never_asked():
    k1, k2 = ("wheat", "export"), ("wheat", "policy")
    recs = [_erec(10, 2020, 0, k1), _erec(14, 2021, 0, k1), _erec(10, 2020, 0, k2), _erec(15, 2021, 0, k2)]
    calls: list = []
    led = CIT.NumbersLedger([], n_start=1)
    CQ._assemble(copy.deepcopy(recs), _kept(k1, k2), 0, calls, numbers_ledger=led)
    # MY2020 at 10 is one fact (reused); MY2021 at 14 vs 15, the delta 4 vs 5 and the pct 40 vs 50 are the value
    # fence (an equal identity at an unequal value is never merged: a new handle, counted)
    assert len(calls) == 7 and led.stamp()["reused"] == 1 and led.stamp()["identity_value_conflict"] == 3
    # a ledger whose next handle is not the next position (seeded with other calls) is never consulted
    stale = CIT.NumbersLedger([{"query": {"table": "x"}, "rows": [{"value": 1}]}], n_start=1)
    calls2: list = []
    recs2, kept2 = _two_drivers_one_series()
    CQ._assemble(copy.deepcopy(recs2), kept2, 0, calls2, numbers_ledger=stale)
    assert len(calls2) == 8 and stale.stamp()["reused"] == 0 and stale.stamp()["issued"] == 0


# ═══ ORCH-P4: THE ROSTER ═════════════════════════════════════════════════════════════════════════════════════════
def test_orchp4_the_wasde_line_map_lint_is_the_rosters_tail_and_clean():
    src = inspect.getsource(CC.main)
    labels = re.findall(r'\("([a-z0-9_]+)", (?:check_|lint_)', src)
    # MOVED 2026-09-29 (FIX SITTING 4, LANE T, CONTRACT C4-15, DECLARED): `product_class_words` APPENDED at the tail
    # (45); `wasde_line_map` is second-to-last, in its own place. The claim kept: append-never-insert, and the map
    # lint rides the roster and is clean.
    assert labels[-2] == "wasde_line_map" and labels[-3] == "numbers_card_fields" and len(labels) == 45
    assert labels[-1] == "product_class_words"
    assert '("wasde_line_map", check_wasde_line_map())' in src
    assert CC.check_wasde_line_map() == [] == R.check_wasde_line_map()


def test_oi6_DOCKETED_silver_fgis_declares_no_national_fold_this_sitting():
    """OI-6 / PC-11 is DOCKETED (BUILD_T): a card-wide `axis_national: sum` would fold `exports_mt_ctd` -- a
    per-destination running total with rows only in weeks a buyer received grain -- into the newest week's sum over
    the buyers that shipped that week, the 10.8 % undercount the card's own notes measured. The compiler has no
    per-metric fold declaration, so the declaration would trade one false national figure for another. This pin
    holds the docket's state: the card is HEAD's."""
    ts = R.load_registry().get("silver_fgis")
    assert getattr(ts, "axis_national", None) is None
    assert "NEVER SUM IT ACROSS DESTINATIONS" in str(getattr(ts, "notes", "") or "")
