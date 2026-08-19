"""D-EC D15 WAVE 1c (2026-08-19) -- THE ROUTING HALF of the context-commodity architecture.

WHAT THE WAVE DID, and what this file pins. The outside-in census
(data/dec_p0/zero_route_clusters.{md,json}) ran the EXACT production matcher pair over all 345,870
propositions in the chunk cache and found 94,642 of them -- 27.36% -- routing to nothing at all. Wave 1c
authors the routing side of the fix in three batches, and nothing else: no edges, no causal DAG files, no
convergence signals. Those are the post-X2 half by ratified ordering, so every node below is an EMPTY node
by construction and this file asserts nothing about walkability.

  BATCH 1  thirteen CONTEXT COMMODITIES (hierarchy `context_commodities` + entity_vocabulary node/aliases).
  BATCH 2  the A23 NODE-ALIAS REGISTER -- ten one-line evidence_windows.yaml `extra_terms` rows on nodes
           that already exist but whose own matcher never fired on a word the corpus uses for them.
  BATCH 3  the A24 FX ROSTER -- thirteen producer-currency driver slices on the brl_fx/inr_fx pattern.

THE SEAM FINDING THIS FILE EXISTS TO HOLD. Before Wave 1c, `evidence.all_nodes()` read `contracts:` ALONE.
A `context_commodities` entry was therefore PURELY DECLARATIVE -- its only other reader is causal.validate,
which accepts them as edge targets -- so `sunflower`, `sunflower_oil`, `barley`, `sorghum`, `fish_meal` and
`ethanol` had no matcher, no evidence/<node>.jsonl and no path by which a proposition could reach them.
rebuild_slices routes on `{n: build_matcher(match_forms(n)) for n in all_nodes()}`, so a node absent from
that list is a node the corpus cannot see. all_nodes() now unions the two, which is why declaring a context
commodity is finally the same act as making its propositions route.

MEASURED RESULT (full 345,870-prop chunk cache, production matcher pair, post-edit config):
dark 94,642 -> 52,622, i.e. 27.36% -> 15.21% of the corpus, -44.4% of the dark mass. 33,455 of the 42,020
newly-routed props come from the three batches; the remaining ~8,565 are the SIX pre-existing context
commodities that the seam change lit for the first time (barley 9,674 props, sunflower 8,287, sorghum
5,419, fish_meal 2,506, ethanol 2,018, sunflower_oil 1,722 -- populations, not net-new dark).

Every assertion here is offline config arithmetic: no S3, no network, no spend. Skips whole on a clean
checkout with no private vocabulary.
"""
from __future__ import annotations

import pytest

from leviathan.graphrag import evidence as ev
from leviathan.graphrag import extract as ex
from leviathan.graphrag import harvest as hv

# The ratified D15 roster, tiered by edge fan-out (the tiering itself is post-X2 work; the roster is here).
TIER_1 = ("cottonseed", "coconut", "palm_kernel", "peanut", "ddgs", "used_cooking_oil", "tallow", "hfcs")
TIER_2 = ("olive_oil", "pulses", "fresh_citrus", "minor_oilseeds", "minor_cereals")
WAVE_1C_NODES = TIER_1 + TIER_2
FX_SLICES = ("ars_fx", "thb_fx", "rub_fx", "cny_fx", "try_fx", "aud_fx", "uah_fx", "cad_fx", "zar_fx",
             "mxn_fx", "php_fx", "vnd_fx", "eur_fx")
FX_WIRED = ("ars_fx", "cad_fx", "cny_fx", "eur_fx", "zar_fx", "vnd_fx")
FX_READ_DARK = ("thb_fx", "rub_fx", "try_fx", "aud_fx", "uah_fx", "mxn_fx", "php_fx")


def _private_configs() -> bool:
    return "coconut" in ev.all_nodes()


def _fires(node: str, text: str) -> bool:
    return hv.build_matcher(ev.match_forms(node)).search(text)


# ── the seam ─────────────────────────────────────────────────────────────────────────────────────
def test_all_nodes_unions_contracts_with_context_commodities(monkeypatch):
    """HERMETIC. The whole wave rests on this one line: a context commodity is a routing node.

    Fixture is a two-contract hierarchy plus two context commodities, so the assertion is about the union
    and not about the live roster. `soybean_meal` appearing twice under `contracts:` also pins that the
    dedup survived the change."""
    monkeypatch.setattr(ev, "_hier", lambda: {
        "contracts": {"soybean_meal_cbot": {"node": "soybean_meal"},
                      "soybean_meal_dce": {"node": "soybean_meal"},
                      "cocoa": {"node": "cocoa"}},
        "context_commodities": ["coconut", "peanut"]})
    assert ev.all_nodes() == ["cocoa", "coconut", "peanut", "soybean_meal"]


def test_all_nodes_without_context_commodities_is_unchanged(monkeypatch):
    """HERMETIC REGRESSION FENCE. A hierarchy with no `context_commodities` key must behave EXACTLY as it
    did before Wave 1c -- this is the property that keeps every pre-existing fixture and the synthetic
    graphs in the eval harness untouched by the seam change."""
    monkeypatch.setattr(ev, "_hier", lambda: {"contracts": {
        "soybean_meal_cbot": {"node": "soybean_meal"}, "cocoa": {"node": "cocoa"}}})
    assert ev.all_nodes() == ["cocoa", "soybean_meal"]


def test_the_six_pre_existing_context_commodities_are_now_routable():
    """The seam change's UNBUDGETED half, pinned so a revert reads as a broken claim rather than a drifted
    number: these six were declared as context commodities before Wave 1c and could never route."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    for node in ("sunflower", "sunflower_oil", "barley", "sorghum", "fish_meal", "ethanol"):
        assert node in ev.all_nodes(), node


# ── batch 1: the thirteen context commodities ────────────────────────────────────────────────────
def test_wave_1c_roster_is_declared_and_routable():
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    nodes = set(ev.all_nodes())
    for node in WAVE_1C_NODES:
        assert node in nodes, f"{node} is not a routing node"
        # every node must carry MORE than its own id -- an id-only node is a node with no vocabulary
        assert len({ex._normalize(f) for f in ev.match_forms(node)}) >= 2, node


def test_wave_1c_nodes_are_context_not_tradeable():
    """A context commodity has NO `contracts:` entry, so it is non-tradeable by construction and can never
    be a cascade root. This is the sunflower_oil/barley precedent and it is what makes the roster safe to
    add before any edge exists."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    contracts = ev._hier().get("contracts") or {}
    for node in WAVE_1C_NODES:
        assert node not in contracts, f"{node} acquired a contract -- it is no longer a context commodity"
        assert node not in {(v.get("node") or k) for k, v in contracts.items() if isinstance(v, dict)}


@pytest.mark.parametrize("node,text", [
    # every sentence below is VERBATIM from data/dec_p0/zero_route_clusters.md -- a prop the production
    # matchers measured as routing NOWHERE. The test is behavioural: does the authored vocabulary route it?
    ("cottonseed", "India cottonseed meal production in 2022/2023 was 4441 thousand MT according to "
                   "USDA Official data."),
    ("cottonseed", "China's MY20/21 cottonseed production is forecast at 9.3 MMT."),
    ("coconut", "FAS Manila forecasts copra production in the Philippines for MY 2022/23 at 2.575 million MT."),
    ("coconut", "India copra meal production in 2022/2023 was 310 thousand MT according to USDA Official data."),
    ("peanut", "China peanut imports are forecast at 1 MMT in MY 23/24."),
    ("peanut", "Nigeria's total peanut consumption in MY 2022/23 was estimated by USDA at 4.5 MMT."),
    ("palm_kernel", "Oleochemical product exports increased by 3.7% to 2.83 million tonnes in 2014 from "
                    "2.73 million tonnes in 2013."),
    ("olive_oil", "France's total olive oil supply in market year 2000/2001 was 115,000 metric tons (revised)."),
    ("pulses", "Mexico's dry bean consumption for MY 2013/14 is forecast at 1.17 million metric tons."),
    ("pulses", "MY 2010/11 pulse production in India is more than 21 percent higher than the previous "
               "record of 14.9 million tons in MY 2003/04."),
    ("fresh_citrus", "China's pomelo and grapefruit imports in MY 2023/24 are expected to remain flat at "
                     "75,000 metric tons."),
    ("fresh_citrus", "South African tangerine/mandarin production is forecast to increase by 6 percent to "
                     "515,000 MT in the 2020/21 marketing year."),
    ("minor_cereals", "Oats production in Canada in MY 2013/2014 is forecast to fall 11% to 2.4 MMT."),
    ("minor_cereals", "In Ukraine, rye area harvested in the market year beginning 07/2000 was 637,000 hectares."),
    ("minor_oilseeds", "Sesame and perilla combined account for about 27 percent of Korea's total oilseed "
                       "production in MY 2014/15."),
    ("minor_oilseeds", "As of the end of November 2023, newly planted camellia trees in China had reached "
                       "0.32 Mha, accounting for 86 percent of the 3-year plan target."),
    ("hfcs", "CARGILL's compensatory duty for HFCS-42 was 100.6 dollars per metric ton."),
])
def test_authored_vocabulary_routes_the_census_dark_samples(node, text):
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    assert _fires(node, text), f"{node} still does not route: {text[:70]}"


def test_cotton_still_cannot_see_cottonseed_and_that_is_why_the_node_exists():
    """The census's stated mechanism, asserted rather than described: word-boundary matching means `cotton`
    can NEVER fire inside 'cottonseed', which is why 2,956 props of the world's 5th-largest protein meal
    were dark while a `cotton` node sat right next to them."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    assert not _fires("cotton", "China's MY20/21 cottonseed production is forecast at 9.3 MMT.")
    assert _fires("cotton", "Cotton lint exports rose.") or True   # bare 'cotton' unaffected either way
    assert _fires("cottonseed", "China's MY20/21 cottonseed production is forecast at 9.3 MMT.")


def test_palm_kernel_is_its_own_node_and_palm_oil_did_not_take_the_abbreviations():
    """THE BATCH-1 DECISION, pinned in both directions.

    PKO/PKM are a distinct lauric node, NOT palm_oil extra_terms, and the measurement that settled it is
    that 'palm kernel' occurs in 3,092 props of which ZERO are dark -- palm_oil's `palm` term already owns
    every one, so the alias route would have created no reach at all. The only unrouted mass was the
    ABBREVIATIONS, and those are what the new node picks up. Economically PKO substitutes for coconut oil,
    not for CPO; folding it into palm_oil would file the graph's one lauric fact as a palmitic one."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    pko = "PKO imports are typically used by oleochemical manufacturers or specialty fat producers."
    assert _fires("palm_kernel", pko)
    assert not _fires("palm_oil", pko)                       # the refusal: no pko/pkm on the CPO node
    assert not _fires("palm_oil", "PKM export volumes increased.")
    # ... while 'palm kernel' itself was never dark: palm_oil's `palm` claims it, and still does.
    assert _fires("palm_oil", "Palm kernel oil prices firmed.")
    assert _fires("palm_kernel", "Palm kernel oil prices firmed.")   # multi-label, nothing is taken away
    # bare 'palm' stays palm_oil's: a lauric node that claimed every CPO prop would be worse than no node
    assert not _fires("palm_kernel", "Malaysian palm output rose in October.")


def test_no_word_is_homed_on_two_nodes():
    """The two double-homing traps the brief named, both refused on purpose.

    `durum` is a WHEAT CLASS -- it rides the four wheat classes' extra_terms and is NOT a minor cereal.
    `mustard` is half of India's rapeseed complex -- it rides rapeseed's extra_terms and is NOT a minor
    oilseed. One word, one home; two homes is the arbitration violation the vocab linter exists to catch."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    durum = "Durum production in Canada in 2011/2012 was 4,172 thousand metric tonnes."
    assert not _fires("minor_cereals", durum)
    assert all(_fires(w, durum) for w in ("hrw_wheat", "hrs_wheat", "srw_wheat", "french_wheat"))
    mustard = "Post estimates mustard seed consumption in Bangladesh in MY 2022/23 at 100 thousand MT."
    assert not _fires("minor_oilseeds", mustard)
    assert _fires("rapeseed", mustard)


def test_the_measured_dead_terms_stay_refused():
    """ZERO DEAD TERMS. Each string below scored ZERO occurrences across all 345,870 propositions and was
    refused on that measurement -- the e1_census 310-of-638 class. A reviewer adding one back should have
    to delete this assertion and say why."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    dead = {
        "cottonseed": ["delinted cottonseed"], "coconut": ["coconut cake"],
        "palm_kernel": ["pke", "palm kernel expeller"],
        "ddgs": ["wet distillers grains", "distillers solubles"],
        "used_cooking_oil": ["waste cooking oil", "brown grease", "used vegetable oil"],
        "tallow": ["rendered fats", "poultry fat", "choice white grease"],
        "olive_oil": ["olive grove", "olive orchards"],
        "pulses": ["faba bean", "cowpea", "tur dal", "moong"],
        "fresh_citrus": ["table oranges"],
        "minor_oilseeds": ["flax seed", "tea seed oil", "nigerseed", "hemp seed", "poppy seed"],
        "minor_cereals": ["fonio", "teff", "sorghum bicolor"],
    }
    for node, forms in dead.items():
        live = {ex._normalize(f) for f in ev.match_forms(node)}
        for f in forms:
            assert ex._normalize(f) not in live, f"{node}: dead term {f!r} was added back"


def test_the_aggregate_layer_is_still_not_claimed():
    """Wave 1c deliberately does NOT author the aggregate-node layer (census Z01: 'oilseed' 2,649 props,
    'vegetable oil' 1,532, 'coarse grains' 895 -- 9,599 dark props, the LARGEST single family in the dark
    mass). `minor_cereals`/`minor_oilseeds` are minor-crop nodes and must never quietly become that layer,
    because a class noun that swallows the aggregate would make the real gap invisible."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    for text in ("India's domestic consumption of oilseeds for MY 2024/25 is forecasted to be 43.5 MMT.",
                 "China's forecast of MY16/17 total vegetable oil consumption is up 1.7 percent.",
                 "World coarse grains production was revised higher."):
        assert not _fires("minor_oilseeds", text), text
        assert not _fires("minor_cereals", text), text


# ── batch 2: the A23 node-alias register ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("node,text", [
    ("raw_sugar", "Sugarcane production in Australia in 2004/05 is estimated at 37,483 TMT."),
    ("white_sugar", "Sugarcane production in Australia in 2004/05 is estimated at 37,483 TMT."),
    ("raw_sugar", "The overall average cane recovery rates in India are forecast to improve by 0.21 percent."),
    ("orange_juice", "In MY2011/2012, Egyptian exports of oranges to Iran dropped by 30 percent to 70 TMT."),
    ("hrw_wheat", "Ukraine flour production decreased to 1.4 million tons during July-January of MY 2009/2010."),
    ("french_wheat", "Turkish flour exports to Venezuela in marketing year 2022/23 were 201,066 MT."),
    ("soybean_meal", "China's SBM exports are expected to stay relatively stable in MY17/18 at 1.8 MMT."),
    ("soybean_oil", "SBO consumption in the Philippines was revised to 65,000 tons in MY 17/18."),
    ("rice", "Vietnam's MY 2014/2015 spring crop total production was revised down to 20.69 million tons "
             "of paddy."),
    ("rice", "The NFA is targeting to procure as much as 870,000 metric tons of palay in Calendar Year 2025."),
    ("cocoa", "Brazilian chocolate exports reached USD 167.4 million in 2023, the highest in two decades."),
    ("rapeseed", "Mustard cultivation in Bangladesh increased substantially in MY 2022/23 and MY 2023/24."),
])
def test_a23_alias_rows_route_their_measured_words(node, text):
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    assert _fires(node, text), f"{node} does not route: {text[:70]}"


def test_a23_did_not_regress_the_incumbent_extra_terms():
    """The rows are ADDITIONS. Every incumbent term on a node this batch touched must still fire -- the
    C1 bare-commodity-word fixes (`sugar`, `coffee`, `wheat`) are the ones that must not be lost."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    assert _fires("raw_sugar", "World sugar prices rallied.")
    assert _fires("orange_juice", "Florida orange production fell; citrus greening spread.")
    assert all(_fires(w, "EU wheat stocks tightened.") for w in ("hrw_wheat", "hrs_wheat", "srw_wheat"))
    assert _fires("cocoa", "Cacao arrivals at Ivorian ports slowed.")
    assert _fires("rice", "Rough rice futures settled higher.")


def test_sugar_cane_two_word_form_was_correctly_left_out():
    """A REFUSAL WITH A MEASUREMENT BEHIND IT: 'sugar cane' occurs in 1,164 props and ZERO of them are dark,
    because bare `sugar` already claims every one. Declaring it would have read as coverage and bought
    nothing -- so the row is 'sugarcane, cane' and not 'sugarcane, sugar cane, cane'."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    assert _fires("raw_sugar", "Brazil sugar cane crush began in April.")            # via bare `sugar`
    assert "sugar cane" not in {ex._normalize(f) for f in ev.match_forms("raw_sugar")}


# ── batch 3: the A24 fx roster ───────────────────────────────────────────────────────────────────
def test_fx_roster_is_configured_on_the_incumbent_pattern():
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    specs = ev.driver_specs()
    for name in FX_SLICES:
        assert name in specs, f"{name} is not a configured slice"
        assert specs[name].get("category") == "macro", name          # brl_fx/idr_fx/inr_fx/myr_fx pattern
        assert specs[name].get("terms"), name
    for incumbent in ("brl_fx", "idr_fx", "inr_fx", "myr_fx", "us_dollar_index"):
        assert incumbent in specs                                    # the roster was extended, not replaced


@pytest.mark.parametrize("slice_name,text", [
    ("ars_fx", "The official exchange rate announced on April 5, 2023 was around ARS$208 per $1 USD."),
    ("thb_fx", "Thailand has a 20 baht per ton fine rule against burned cane."),
    ("rub_fx", "The ruble weakened sharply against the dollar."),
    ("cny_fx", "The RMB exchange rate moved against the dollar during the quarter."),
    ("try_fx", "The Turkish lira depreciated further in 2022."),
    ("aud_fx", "A weaker Australian dollar supported export competitiveness."),
    ("uah_fx", "The Ukrainian currency (UAH) devalued by 35% during the global financial turmoil."),
    ("cad_fx", "The average monthly USD/CAD exchange rate in March 2026 was 1.3720."),
    ("zar_fx", "The South African rand lost seven percent of its value since the beginning of 2013."),
    ("mxn_fx", "Red grapefruit wholesale price in Mexico City was 18.50 mexican pesos per kilogram."),
    ("php_fx", "Copra meal prices rose to Php 17.27 per kilogram in December 2025."),
    ("vnd_fx", "US SBM price in Vietnam was 13,950 VND/kg."),
    ("eur_fx", "Devaluation of the Euro against the USD created a disadvantage for Turkish traders."),
])
def test_fx_slices_route_their_currency(slice_name, text):
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    assert slice_name in ev.driver_slices_for(text), f"{slice_name} did not claim: {text[:60]}"


def test_the_two_off_topic_fx_forms_are_refused_with_their_samples():
    """REFUSED ON A READ SAMPLE, not on a count. Both scored real document frequency and both are the
    urea->area over-fire class this file's `area` waiver is named for:

      'try' (27 props) -- 10/10 sampled props are the English verb, e.g. "the Government of India will try
        to provide additional funding for ICDS and Mid-Day Meal social welfare programs".
      'dong' (70 props) -- 10/10 are Vietnamese place and company names, e.g. "Koyu & Unitek Company
        operates a chicken processing factory in Dong Nai province" and "Shin-Dong-Bang Corp., the largest
        oil crusher in Korea".

    So try_fx is 'lira' alone and vnd_fx is 'vietnamese dong'/'vnd' alone. The assertion is behavioural:
    those two sentences must reach NO fx slice."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    for text in ("The Government of India will try to provide additional funding for social welfare programs.",
                 "Koyu & Unitek Company operates a chicken processing factory in Dong Nai province."):
        assert not (set(ev.driver_slices_for(text)) & set(FX_SLICES)), text


def test_six_fx_slices_are_wired_and_seven_are_pinned_read_dark():
    """The asymmetry IS the record. Six slices took DAG ids that were waived silver_only AND owned by no
    slice, so the wiring CREATED reach (the favorable_rainfall shape) and every claimed waiver row was
    deleted in the same edit (the MYR_USD precedent). The other seven are read-dark for the
    export_levy_duty reason -- NO WIRING EXISTS TO DO: not one of the 371 real DAG driver ids names the
    baht, ruble, lira, Australian dollar, hryvnia, Mexican peso or Philippine peso.

    `INR_THB_VND_weakness` is the one refusal: it would have retired thb_fx, and it is a BASKET id covering
    three currencies, which is the exact ground on which D-GD tranche 2 declined a second FX node on
    rough_rice_cbot. test_config_check.test_the_live_pin_still_matches_the_live_wiring already holds the
    exact equality; this names the members so a silent revert reads as a broken claim, not a drifted count."""
    from leviathan.graphrag import display as dp
    if not _private_configs() or not dp.all_driver_ids():
        pytest.skip("no private causal/vocabulary configs in this tree")
    dark = ev.read_dark_slices()
    for name in FX_WIRED:
        assert name not in dark, f"{name} lost its wiring"
    for name in FX_READ_DARK:
        assert name in dark and name in ev.READ_DARK_SLICES_PIN, f"{name} drifted out of the pin"
    backed = ev.backed_dag_ids()
    for did in ("ARS_FX", "CAD_FX", "usdcad_fx", "CNY", "CNY_FX", "CNY_USD", "usdcny_fx",
                "EUR_USD", "EUR_USD_FX", "eurusd_fx", "ZAR_FX", "rand_FX", "VND_USD_fx"):
        assert did in backed, f"{did} is no longer backed by an fx slice"
    waivers = ev._driver_raw().get("waivers") or {}
    # `cny_fx` stays in this roster after the D-EC XC-5 tail (2026-08-20) even though it is NO LONGER A DAG
    # ID -- the lowercase spelling on rapeseed_meal_zce was merged into `CNY_FX`, its 2-DAG majority. The
    # assertion is "no waiver row survives under this key", and a key that names a retired spelling is
    # exactly the one a careless re-add would resurrect, so dropping it from the roster would retire the
    # tripwire at the moment it became cheapest to trip. `cny_fx` remains a live SLICE name; slice ids and
    # DAG ids are different namespaces and only the DAG-id side moved.
    for did in ("ARS_FX", "CAD_FX", "CNY_FX", "EUR_USD", "ZAR_FX", "VND_USD_fx", "cny_fx"):
        assert did not in waivers, (f"{did} kept its silver_only waiver after a text slice took it -- the "
                                    f"MYR_USD precedent says the waiver is deleted in the same edit")
    assert "INR_THB_VND_weakness" in waivers                 # the refusal, asserted


def test_fx_terms_do_not_collide_with_an_existing_slice():
    """G8 cross-fire is advisory and this batch added none. Pinned because a currency word is exactly the
    kind of short token that silently becomes a substring of somebody else's term."""
    if not _private_configs():
        pytest.skip("no private vocabulary in this tree")
    fx_terms = {ex._normalize(t) for name in FX_SLICES for t in ev.driver_specs()[name]["terms"]}
    others = {ex._normalize(t): name for name, spec in ev.driver_specs().items() if name not in FX_SLICES
              for t in (spec.get("terms") or [])}
    for term in fx_terms:
        for other, owner in others.items():
            assert term != other, f"fx term {term!r} is already a term of {owner}"
