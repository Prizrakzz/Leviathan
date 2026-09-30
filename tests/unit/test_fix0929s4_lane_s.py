"""FIX SITTING 4 (2026-09-29), LANE S -- THE PRICED ANCHOR (S4-1, S4-2; CONTRACT C4-18).

S4-1 (smoke N-1, recon A-6): the max page anchored the graph's generic ``soybeans`` DAG -- a product with no
per-contract price record -- so every price read on the page declined at zero reads (front_decline 8, reads 0),
where arm A had anchored ``soybeans_cbot``. S4-2 (S3 S3-4c): "rapeseed oil" seated MATIF rapeseed, the SEED.

``board.priced_anchor`` resolves an anchor through the contract registry (``futures_eod_contracts.
PRICE_COVERAGE_START`` + ``commodity_hierarchy.yaml``) and ``subject.named_product_class`` reads the product class the
question's own words name. Every fact below is a registry row, a hierarchy row, or a banked question; nothing here is a
word list. The measured drive is ``scratchpad/fix_sitting_4_0929/verify/S/b17_s4_drive.out`` (the 63 banked turns) and
the refutation ``b17_s4_counterfactual.out`` (C4-18 read literally: 12 false moves on the 63, each dropping a board).
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest

from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import subject as S

_CFG = Path(__file__).resolve().parents[2] / "configs" / "graphrag"
pytestmark = pytest.mark.skipif(not (_CFG / "commodity_hierarchy.yaml").exists(),
                                reason="commodity_hierarchy.yaml is gitignored IP; the registry reads it")

#: C4-15's declared class keys (the book's ``product_class_words`` keys), injected through the seat so the deck does not
#: depend on the book's load order; one pin below asserts the book declares exactly these.
CLASSES = ("oilseeds", "vegetable_oils", "oilseed_meals", "grains")

#: The banked questions, verbatim from configs/graphrag/eval_queries_state_resmoke_v1.yaml (the smoke's deck).
Q_PALM_RAPE = ("Set palm oil against rapeseed oil for me -- whose stocks position moved more this year, and how do "
               "the two read against each other from here?")
Q_SOY_NOW = "what is the situation on soybeans now? how is it looking 3 months from now?"
Q_SOY_2024 = ("As of the first of March 2024, what was the situation on soybeans, and how was it looking three months "
              "out from there? Read it as it was known then, not with hindsight.")
Q_SOYOIL_PALM = ("Palm oil's supply picture has been shifting. How does that reach soybean oil, and where does the "
                 "balance between the two sheets stand this marketing year?")
Q_COCOA = ("How tight is cocoa after this season -- where do stocks sit against grindings, and what does the record "
           "say about a market this stretched, the last times it looked like this?")

PALM, MATIF_RAPE, ZCE_RAPEOIL = "malaysian_crude_palm_oil_cme", "french_rapeseed_matif", "rapeseed_oil_zce"


# --------------------------------------------------------------------------------------------------- the vocabulary
def test_reasons_are_the_contract_five_then_the_appended_word():
    # APPEND-NEVER-SORT: C4-18's five in its own order, then lane S's one appended word.
    assert B.ANCHOR_RESOLUTION_REASONS[:5] == ("priced", "one_priced_contract", "class_named", "several_priced",
                                               "no_priced_contract")
    assert B.ANCHOR_RESOLUTION_REASONS[5:] == ("contract_unpriced",)


def test_anchor_resolution_fields_are_appended_with_empty_defaults_and_closed():
    a = B.Anchor(contract="soybeans_cbot", source="named")
    assert (a.seed, a.reason) == ("", "")
    ok = B.Anchor(contract="soybeans_cbot", source="named", seed="soybeans", reason="one_priced_contract")
    assert ok.reason == "one_priced_contract"
    with pytest.raises(ValueError):
        B.Anchor(contract="soybeans_cbot", source="named", reason="because_i_said_so")


def test_trace_omits_anchor_resolution_unless_an_anchor_carries_a_non_priced_reason():
    plain = B.Board(anchors=(B.Anchor(contract="soybeans_cbot", source="named"),
                             B.Anchor(contract="corn_cbot", source="planner_inferred", reason="priced")))
    assert "anchor_resolution" not in plain.trace()
    bd = B.Board(anchors=(B.Anchor(contract="soybeans_cbot", source="named", seed="soybeans",
                                   reason="one_priced_contract"),
                          B.Anchor(contract="corn", source="subject", reason="several_priced"),
                          B.Anchor(contract="cocoa", source="named", reason="priced")))
    tr = bd.trace()
    assert tr["anchor_resolution"] == [
        {"seed": "soybeans", "contract": "soybeans_cbot", "reason": "one_priced_contract"},
        {"seed": "corn", "contract": "corn", "reason": "several_priced"}]
    assert list(tr)[-1] == "anchor_resolution"           # APPENDED LAST


# --------------------------------------------------------------------------------------------------- S4-1
def test_s41_the_generic_soybeans_dag_resolves_to_its_one_priced_contract():
    r = B.priced_anchor("soybeans")
    assert (r["contract"], r["reason"], r["candidates"]) == ("soybeans_cbot", "one_priced_contract",
                                                             ("soybeans_cbot",))
    assert "soybeans" in r["note"] and "soybeans_cbot" not in r["note"]


def test_s41_a_resolved_contract_must_carry_a_dag_on_the_graph():
    class _G:                                            # a graph that carries no soybeans_cbot DAG
        contracts = {"soybeans": object(), "corn_cbot": object()}
    r = B.priced_anchor("soybeans", graph=_G())
    assert (r["contract"], r["reason"]) == ("soybeans", "no_priced_contract")


def test_s41_several_priced_contracts_keep_the_slug_and_name_every_candidate():
    r = B.priced_anchor("corn")                          # threat S4-b: never picks one of three
    assert r["contract"] == "corn" and r["reason"] == "several_priced"
    assert r["candidates"] == ("campinas_corn_reference_bmf", "corn_cbot", "french_maize_matif")
    assert r["note"] == ("corn trades on several contracts with a price record, BMF corn, CBOT corn and MATIF corn, "
                         "so no single price stands for corn")


@pytest.mark.parametrize("slug", ["barley", "sunflower_oil", "sorghum", "palm_olein_dce"])
def test_s41_a_product_with_no_priced_contract_is_kept_and_said(slug):
    r = B.priced_anchor(slug)
    assert (r["contract"], r["reason"], r["candidates"]) == (slug, "no_priced_contract", ())
    assert "no contract with a price record" in r["note"]


@pytest.mark.parametrize("slug,priced", [("soybean_oil_dce", "soybean_oil_cbot"),
                                         ("soybeans_no_1_dce", "soybeans_cbot"),
                                         ("soybean_meal_dce", "soybean_meal_cbot")])
def test_s41_a_contract_with_no_record_is_a_market_of_its_own_and_never_moved(slug, priced):
    # C4-18 read literally would resolve DCE soybean oil onto CBOT soybean oil and drop the China board (measured on
    # the 0924 soyoil/palm turn). A far market is never dropped for lack of data.
    r = B.priced_anchor(slug)
    assert (r["contract"], r["reason"], r["candidates"]) == (slug, "contract_unpriced", (priced,))


@pytest.mark.parametrize("slug", ["soybeans_cbot", "corn_cbot", "cocoa", PALM, MATIF_RAPE, ZCE_RAPEOIL,
                                  "campinas_corn_reference_bmf"])
def test_s41_a_priced_slug_anchors_as_itself_with_no_note(slug):
    assert B.priced_anchor(slug) == {"contract": slug, "reason": "priced", "note": "", "candidates": ()}


def test_priced_anchor_never_raises():
    for bad in (None, "", "   ", "no_such_market"):
        r = B.priced_anchor(bad, graph=object(), question_class=object(), seated=object())
        assert set(r) == {"contract", "reason", "note", "candidates"}
        assert r["reason"] in B.ANCHOR_RESOLUTION_REASONS


def test_every_note_is_register_clean_on_the_books_own_grader():
    # the render prints the note in the block header (lane R's anchor_resolution_words), so it is graded like a book
    # value: ASCII, no digit, no underscore, the four register detectors and the desk register (lint._row_word_errs)
    from leviathan.graphrag.state import lint as L
    from leviathan.silver import futures_eod_contracts as FC
    reg = B._anchor_registry()
    slugs = set(reg["node_of"]) | set(reg["contracts_of"]) | set(FC.PRICE_COVERAGE_START)
    qc = S.NamedClass("vegetable_oils", ("palm_oil", "rapeseed_oil"))
    notes = set()
    for s in sorted(slugs):
        for r in (B.priced_anchor(s), B.priced_anchor(s, question_class=qc, seated=(PALM, s), classes=CLASSES),
                  B.priced_anchor(s, question_class="vegetable_oils", seated=(s,), classes=CLASSES)):
            if r["note"]:
                notes.add(r["note"])
    assert len(notes) >= 10
    for n in sorted(notes):
        assert L._row_word_errs("anchor note", n) == [], n


def test_every_note_is_reader_words():
    # a note is a served fact's reader words: ASCII, no digit, no underscore (no raw slug), never a sentence to copy
    from leviathan.silver import futures_eod_contracts as FC
    reg = B._anchor_registry()
    slugs = set(reg["node_of"]) | set(reg["contracts_of"]) | set(FC.PRICE_COVERAGE_START) | {"barley", "sorghum"}
    qc = S.NamedClass("vegetable_oils", ("palm_oil", "rapeseed_oil"))
    for s in sorted(slugs):
        for r in (B.priced_anchor(s), B.priced_anchor(s, question_class=qc, seated=(PALM, s), classes=CLASSES)):
            n = r["note"]
            assert n.isascii() and "_" not in n and not any(ch.isdigit() for ch in n), (s, n)
            assert r["reason"] in B.ANCHOR_RESOLUTION_REASONS


# --------------------------------------------------------------------------------------------------- S4-2
def test_s42_the_book_declares_the_class_keys_this_deck_injects():
    from leviathan.graphrag.state.lint import load_conventions
    words = (load_conventions() or {}).get("product_class_words")
    if not words:
        pytest.skip("lane R's product_class_words has not landed in the book")
    assert tuple(words) == CLASSES


def test_s42_the_palm_rape_question_names_the_oil_class_and_its_two_oils():
    qc = S.named_product_class(Q_PALM_RAPE, classes=CLASSES)
    assert isinstance(qc, str) and qc == "vegetable_oils"
    assert qc.nodes == ("palm_oil", "rapeseed_oil")      # "rapeseed oil" is ONE longest match, never "rapeseed"


@pytest.mark.parametrize("q,want", [
    ("palm oil against rapeseed", None),                 # threat S4-c: a bare "rapeseed" names the SEED node
    ("canola against palm oil", None),                   # a seed and an oil: two classes
    (Q_COCOA, None),                                     # cocoa belongs to no product class
    (Q_SOY_NOW, "oilseeds"),
    (Q_SOYOIL_PALM, "vegetable_oils"),
    ("soymeal against rapeseed meal", "oilseed_meals"),
    ("", None),
])
def test_s42_named_product_class(q, want):
    assert S.named_product_class(q, classes=CLASSES) == want


def test_s42_no_declared_class_means_no_class_read():
    assert S.named_product_class(Q_PALM_RAPE, classes=()) is None


def test_s42_named_class_is_a_str_that_survives_serialisation():
    qc = S.NamedClass("vegetable_oils", ("rapeseed_oil", "palm_oil", "palm_oil"), seated=(PALM, MATIF_RAPE, PALM))
    assert qc.nodes == ("palm_oil", "rapeseed_oil") and qc.seated == (PALM, MATIF_RAPE)
    assert S.NamedClass("vegetable_oils").seated is None
    assert json.dumps({"c": qc}) == '{"c": "vegetable_oils"}'
    back = pickle.loads(pickle.dumps(qc))
    assert back == "vegetable_oils" and back.nodes == qc.nodes and back.seated == qc.seated


def test_s42_the_class_word_carries_the_seats_through_the_one_argument_call():
    # lane W's anchor pass calls priced_anchor(slug, graph=..., question_class=...) with no `seated`: the seats ride
    # the class word the caller read against them, so the contracted one-argument call closes S4-2 ...
    seats = (PALM, MATIF_RAPE)
    qc = S.named_product_class(Q_PALM_RAPE, classes=CLASSES, seated=seats)
    assert qc.seated == seats
    r = B.priced_anchor(MATIF_RAPE, question_class=qc, classes=CLASSES)
    assert (r["contract"], r["reason"]) == (ZCE_RAPEOIL, "class_named")
    # ... and keeps every crush seat of a named bean on the same call shape
    crush = ("soybeans_cbot", "soybean_meal_cbot", "soybean_oil_cbot")
    qc2 = S.named_product_class(Q_SOY_2024, classes=CLASSES, seated=crush)
    for s in crush:
        assert B.priced_anchor(s, question_class=qc2, classes=CLASSES)["contract"] == s
    # the explicit kwarg wins over the carried seats
    assert B.priced_anchor(MATIF_RAPE, question_class=qc, seated=(PALM,), classes=CLASSES)["contract"] == MATIF_RAPE


def test_s42_rapeseed_oil_moves_the_matif_seed_seat_onto_the_zce_oil():
    qc = S.named_product_class(Q_PALM_RAPE, classes=CLASSES)
    r = B.priced_anchor(MATIF_RAPE, question_class=qc, seated=(PALM, MATIF_RAPE), classes=CLASSES)
    assert (r["contract"], r["reason"], r["candidates"]) == (ZCE_RAPEOIL, "class_named", (ZCE_RAPEOIL,))
    assert "rapeseed oil" in r["note"] and "MATIF rapeseed" in r["note"]
    # the palm seat is of the named class already: itself
    assert B.priced_anchor(PALM, question_class=qc, seated=(PALM, MATIF_RAPE), classes=CLASSES)["reason"] == "priced"


def test_s42_without_the_turns_seats_no_seat_is_moved():
    qc = S.named_product_class(Q_PALM_RAPE, classes=CLASSES)
    assert B.priced_anchor(MATIF_RAPE, question_class=qc, classes=CLASSES)["contract"] == MATIF_RAPE


def test_s42_a_fan_out_board_is_never_moved_by_the_class():
    # canola ICE rode the palm/rape turns as a subject fan-out board; C4-18 read literally moves it onto ZCE rapeseed
    # oil and drops it (armA, 0925, smoke run 1).
    qc = S.named_product_class(Q_PALM_RAPE, classes=CLASSES)
    r = B.priced_anchor("canola_ice", question_class=qc, seated=(PALM, MATIF_RAPE), classes=CLASSES)
    assert (r["contract"], r["reason"]) == ("canola_ice", "priced")


def test_s42_the_crush_seats_of_a_named_bean_stay():
    # the 2024 soybeans turns seed the bean AND its meal and oil; the question names the bean only. C4-18 read
    # literally collapses the meal and the oil into the bean (0925 and smoke run 1).
    qc = S.named_product_class(Q_SOY_2024, classes=CLASSES)
    assert qc == "oilseeds"
    seats = ("soybeans_cbot", "soybean_meal_cbot", "soybean_oil_cbot")
    for s in seats:
        assert B.priced_anchor(s, question_class=qc, seated=seats, classes=CLASSES)["contract"] == s


def test_s42_a_class_moves_a_seat_only_onto_a_product_the_question_named():
    # a palm-oil-only question with a planner soybean seat: soybean OIL is of the named class and in the bean's
    # complex, but the question never named it -> the seat stays.
    qc = S.named_product_class("where is palm oil heading", classes=CLASSES)
    assert qc == "vegetable_oils" and qc.nodes == ("palm_oil",)
    r = B.priced_anchor("soybeans_cbot", question_class=qc, seated=(PALM, "soybeans_cbot"), classes=CLASSES)
    assert (r["contract"], r["reason"]) == ("soybeans_cbot", "priced")


def test_s42_a_named_product_already_seated_is_never_seated_twice():
    qc = S.named_product_class(Q_PALM_RAPE, classes=CLASSES)
    r = B.priced_anchor(MATIF_RAPE, question_class=qc, seated=(PALM, MATIF_RAPE, ZCE_RAPEOIL), classes=CLASSES)
    assert r["contract"] == MATIF_RAPE


def test_s42_two_seats_standing_in_for_one_named_product_move_neither():
    # MATIF rapeseed AND ICE canola seated for "rapeseed oil": which one stood in is not a registry fact -> neither
    # moves, neither board is dropped
    seats = (PALM, MATIF_RAPE, "canola_ice")
    qc = S.named_product_class(Q_PALM_RAPE, classes=CLASSES, seated=seats)
    for s in (MATIF_RAPE, "canola_ice"):
        assert B.priced_anchor(s, question_class=qc, classes=CLASSES)["contract"] == s


def test_s42_a_class_never_bridges_through_a_cross_crop_complex_to_a_seated_product():
    # feed_demand_complex holds corn AND soybean meal; a soymeal question whose planner seated the meal keeps its corn
    seats = ("soybean_meal_cbot", "corn_cbot")
    qc = S.named_product_class("where is soymeal heading", classes=CLASSES, seated=seats)
    assert qc == "oilseed_meals"
    assert B.priced_anchor("corn_cbot", question_class=qc, classes=CLASSES)["contract"] == "corn_cbot"


def test_s42_a_bare_class_word_moves_the_seat_on_the_class_alone():
    # C4-18's literal call (a plain class word, no named nodes) keeps the contract's meaning for a SEAT
    r = B.priced_anchor(MATIF_RAPE, question_class="vegetable_oils", seated=(MATIF_RAPE,), classes=CLASSES)
    assert (r["contract"], r["reason"]) == (ZCE_RAPEOIL, "class_named")


def test_s42_node_class_is_the_one_group_that_holds_the_node():
    cls = B.product_classes(CLASSES)
    assert B.node_class("rapeseed", cls) == "oilseeds"
    assert B.node_class("rapeseed_oil", cls) == "vegetable_oils"
    assert B.node_class("soybean_meal", cls) == "oilseed_meals"
    assert B.node_class("corn", cls) == "grains"
    assert B.node_class("vegetable_oils", cls) == "vegetable_oils"   # a class noun names its own class
    assert B.node_class("cocoa", cls) is None
    assert B.node_class("rapeseed", {}) is None


def test_s42_registry_product_class_agrees_where_lane_t_ships_it():
    try:
        from leviathan.graphrag.numbers import registry as R
    except Exception:                                    # noqa: BLE001
        pytest.skip("registry unimportable")
    pc = getattr(R, "product_class", None)
    if pc is None:
        pytest.skip("lane T's registry.product_class has not landed")
    reg = B._anchor_registry()
    cls = B.product_classes(None)
    if not cls:
        pytest.skip("the book declares no product_class_words")
    for slug, node in sorted(reg["node_of"].items()):
        assert pc(slug) == B.node_class(node, cls), slug


# --------------------------------------------------------------------------------------------------- the forms
def test_node_match_forms_equals_the_evidence_node_matcher_node_for_node():
    # the one-pass composition is PINNED EQUAL to evidence.match_forms, so it cannot drift from the router's forms
    from leviathan.graphrag import evidence as ev
    h = ev._hier()
    nodes = set(ev.all_nodes())
    for block in ("groups", "complexes"):
        for members in (h.get(block) or {}).values():
            nodes |= set(members or ())
    nodes |= set(h.get("groups") or {})
    mine = S.node_match_forms(sorted(nodes), None)
    for n in sorted(nodes):
        assert mine[n] == ev.match_forms(n), n


def test_node_match_forms_reads_a_dag_alias_off_the_graph_when_it_carries_that_dag():
    class _C:
        aliases = ["alias from the graph"]

    class _G:
        contracts = {"soybeans": _C()}
    forms = S.node_match_forms(["soybeans"], _G())["soybeans"]
    assert "alias from the graph" in forms and forms[:2] == ["soybeans", "soybeans"]
