"""THE SEMANTIC SUBJECT RESOLVER -- phase A deck.
Design: docs/private/SUBJECT_RESOLVER_SITTING_2026-09-09.md (D1-D14). Recon: scratchpad/recon_resolver/BRIEF.md.

WHAT THIS DECK PROVES, AND WHAT IT DELIBERATELY DOES NOT.

  IT PROVES the four tiers of wiring at zero cost: the deterministic tiers over INJECTED fake vectors
  (no model load -- bge-m3 costs ~120 s to construct and ~350 ms per encode, so a suite that loaded it
  would be a suite nobody runs), the artifact loader's four status words, the subject GROUP census
  banked as NUMBERS, the hint line, the three closed-set registrations, the EMF dimension, the planner's
  four sites, and the FLAG-OFF BYTE IDENTITY of every one of them against HEAD's own module.

  IT DOES NOT PROVE RESOLUTION QUALITY. That is layer 1's job and it needs the real 4,000-row artifact
  and the real embedder; it is run by hand (scratchpad/subjcal/calibrate.py) and banked in the deck
  header and in `state/subject.py`'s calibration table. One test here is the opt-in bridge, and it
  needs BOTH `SUBJECT_RESOLVER_SLOW_TESTS=1` and a current artifact -- artifact presence alone is not
  an opt-in on a box that HAS the artifact, which is how a 70 s model load reached the default suite.

THE ONE ENVIRONMENT NAME IN THIS FILE IS THAT OPT-IN, and it is the TEST's. The resolver itself is
env-free by construction and `config_check.check_subject_resolver` clause (1) grades that from source;
this deck asserts the same property a second way, over the module's text, so a reviewer reading either
file finds it.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

import pytest
import yaml

from leviathan.graphrag import dispatch as dp
from leviathan.graphrag import graph as G
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import seam as S
from leviathan.graphrag.state import subject as SU
from leviathan.graphrag.state import walk as W

ROOT = pathlib.Path(__file__).resolve().parents[2]
DECK = ROOT / "configs" / "graphrag" / "subject_deck_v1.yaml"
DECK2 = ROOT / "configs" / "graphrag" / "subject_deck_v2.yaml"
DIM = 8                                   # the fake vector width; the artifact's real one is 1024


@pytest.fixture(scope="module")
def graph():
    return G.CausalGraph(G.load_contracts(), silver=set(), version="harness")


@pytest.fixture(scope="module")
def deck():
    return yaml.safe_load(DECK.read_text(encoding="utf-8"))


def _fake_vocab(rows, dim: int = DIM):
    """A vocabulary matrix from ``[(id, field, unit_vector), ...]`` -- the injection seat
    :func:`state.subject.semantic_candidates` declares, so this deck never constructs a model."""
    import numpy as np
    V = np.asarray([r[2] for r in rows], dtype="float32")
    V /= np.linalg.norm(V, axis=1, keepdims=True)
    return {"V": V, "ids": [r[0] for r in rows], "fields": [r[1] for r in rows],
            "texts": [f"{r[0]} {r[1]} text" for r in rows],
            "graph_hash": "fake", "model": "fake"}


def _e(i, dim=DIM):
    v = [0.0] * dim
    v[i] = 1.0
    return v


# ---------------------------------------------------------------------------------------------------
# THE TIERS
# ---------------------------------------------------------------------------------------------------
def test_T0_exact_reads_the_id_AND_its_reader_form_through_the_ONE_shipped_matcher(graph):
    """T0 (D3). ``El_Nino`` and ``El Nino`` are the same subject, and the matcher is
    ``harvest.build_matcher`` -- the estate's ONE accent/case-folded word-boundary matcher, never a
    private second copy (the string-identity class this estate has measured three times).

    THE RANKING IS `route_scored`'s: most hits first, then alphabetical. Asserted rather than assumed,
    because the hint line prints in this order and a reader of the trace reads it as a ranking."""
    assert "El_Nino" in SU.exact_ids("what does El Nino do to corn", graph)
    assert "El_Nino" in SU.exact_ids("what does el_nino do to corn", graph)
    assert "El_Nino" in SU.exact_ids("WHAT DOES EL NINO DO", graph)
    hits = SU.exact_ids("how does heat stress hit soybean pod fill", graph)
    assert "heat_stress" in hits and "pod_fill" in hits
    assert SU.exact_ids("", graph) == () and SU.exact_ids("   ", graph) == ()
    # a phrase that names no driver names no driver
    assert SU.exact_ids("what is the ticker for the March contract", graph) == ()


def test_T1_alias_is_INTERSECTED_with_the_live_id_set(graph):
    """T1 (D3, risk 7). ``evidence.driver_alias()`` returns 424 entries and 127 of them point at ids
    that are in NO DAG -- accent folds and curation drift, MEASURED. An unintersected alias hands the
    planner an id its own enum does not carry, and downstream ``walk._driver_of`` swallows an unknown
    id, so the failure would be a board that anchors NOTHING with no word for why."""
    from leviathan.graphrag import evidence as ev
    alive = set(SU.live_ids(graph))
    raw = set(ev.driver_alias())
    assert raw - alive, "the alias map no longer carries ids outside the graph -- re-measure this claim"
    for phrase in ("what do the commitments of traders say about cotton",
                   "what is the DXY doing to ag export competitiveness",
                   "is the nutrient cost squeezing corn acreage"):
        got = SU.alias_ids(phrase, graph)
        assert got, phrase
        assert set(got) <= alive, (phrase, sorted(set(got) - alive))
    assert len(SU.alias_ids("does the blending mandate lift palm demand", graph)) <= SU.HINT_ALIAS_CAP


def test_T2_scores_an_id_by_the_MAX_over_its_rows_and_never_a_mean(graph):
    """T2 (D3). ``El_Nino`` carries 35 distinct blurbs (MEASURED) because the same id sits on 35
    boards with different prose. A MEAN over those rows scores the estate's most-shared driver BELOW a
    driver that appears once, which is the exact inversion the resolver exists to avoid."""
    rows = [("El_Nino", "id", _e(0))] + [("El_Nino", "blurb", _e(1)) for _ in range(34)]
    rows += [("frost", "id", _e(0))]
    vocab = _fake_vocab(rows)
    cands, status = SU.semantic_candidates("q", graph, vocab=vocab, embed_fn=lambda t: [_e(0)],
                                           floor=0.5)
    assert status == "ok"
    got = {c[0]: c[1] for c in cands}
    assert got["El_Nino"] == pytest.approx(1.0), "the max over the id's rows, not the mean"
    assert got["frost"] == pytest.approx(1.0)
    assert [c[2] for c in cands if c[0] == "El_Nino"] == ["id"], "the winning FIELD is reported"


def test_T2_candidates_respect_the_floor_the_topk_and_a_deterministic_order(graph):
    rows = [("El_Nino", "blurb", [1.0, 0.0] + [0] * 6),
            ("La_Nina", "blurb", [0.9, 0.44] + [0] * 6),
            ("frost", "blurb", [0.5, 0.87] + [0] * 6),
            ("drought", "blurb", [0.1, 0.99] + [0] * 6)]
    vocab = _fake_vocab(rows)
    q = [1.0, 0.0] + [0] * 6
    hi, _ = SU.semantic_candidates("q", graph, vocab=vocab, embed_fn=lambda t: [q], floor=0.85)
    assert [c[0] for c in hi] == ["El_Nino", "La_Nina"], hi
    lo, _ = SU.semantic_candidates("q", graph, vocab=vocab, embed_fn=lambda t: [q], floor=-1.0,
                                   top_k=3)
    assert len(lo) == 3 and [c[1] for c in lo] == sorted((c[1] for c in lo), reverse=True)
    # an id the graph does not carry is DROPPED, never handed to a planner enum that lacks it
    ghost = _fake_vocab([("not_a_real_driver_id", "blurb", _e(0))])
    out, _ = SU.semantic_candidates("q", graph, vocab=ghost, embed_fn=lambda t: [_e(0)], floor=0.0)
    assert out == ()


def test_the_floors_are_ORDERED_and_frozen():
    """A score too weak to hint with cannot be strong enough to interrupt a reader over (D5/D9)."""
    assert SU.AMBIG_FLOOR >= SU.CAND_FLOOR
    assert 0.0 < SU.CAND_FLOOR < 1.0 and 0.0 < SU.AMBIG_FLOOR < 1.0
    assert SU.TOP_K == 5


# ---------------------------------------------------------------------------------------------------
# THE ARTIFACT AND ITS FOUR WORDS
# ---------------------------------------------------------------------------------------------------
def test_the_artifact_status_words_are_CLOSED_and_each_one_is_reachable(tmp_path, graph):
    """D7. ``missing`` / ``stale`` / ``unreadable`` / ``ok`` -- and the first three all DECLINE T2
    while T0 and T1 keep running, which is the fail-open floor risk 1 names as the LIKELY case."""
    assert set(SU.VOCAB_STATUS_WORDS) == {"ok", "missing", "stale", "unreadable"}
    p = tmp_path / "v.npz"
    meta = tmp_path / "v.meta.json"
    assert SU.artifact_status(p, graph=graph)[0] == "missing"
    p.write_bytes(b"not an npz")
    meta.write_text('{"graph_hash": "deadbeefcafe"}', encoding="utf-8")
    assert SU.artifact_status(p, graph=graph)[0] == "stale"        # the stamp != 'harness'
    meta.write_text("{ this is not json", encoding="utf-8")
    assert SU.artifact_status(p, graph=graph)[0] == "unreadable"
    meta.write_text('{"graph_hash": "harness"}', encoding="utf-8")
    assert SU.artifact_status(p, graph=graph)[0] == "ok"           # matches graph.version
    SU._reset_caches()
    # ...and an 'ok' stamp over a CORRUPT npz still declines rather than raising on a serving thread
    v, st = SU.load_vocab(p, graph=graph)
    assert v is None and st == "unreadable"
    SU._reset_caches()


def test_a_declined_semantic_tier_still_runs_T0_and_T1(tmp_path, graph):
    """RISK 1, and the resolver's whole fail-open posture in one assertion.

    THE PHRASE HAS TO REACH T2 FOR THE DECLINE TO BE MEASURABLE (D10, 2026-09-10): the tier is
    CONDITIONAL, so a question that names a driver outright is `skipped` no matter what the artifact
    is doing, and 'El Nino' would have measured the gate while claiming to measure the decline."""
    SU._reset_caches()
    hints = SU.resolve("the insect that bores into coffee cherries", graph=graph,
                       path=tmp_path / "absent.npz")
    assert hints.vocab_status == "missing"
    assert hints.candidates == ()
    assert hints.exact == () and hints.alias == ()          # the tiers ran; they found nothing
    assert hints.ambiguous() == (), "a declined tier proposed nothing, so nothing is owed a reader"
    # ...and T0's own output survives a missing artifact, which is the half the phrase above cannot say
    lex = SU.resolve("what does El Nino do to corn", graph=graph, path=tmp_path / "absent.npz")
    assert "El_Nino" in lex.exact and lex.candidates == ()
    SU._reset_caches()


def test_T2_is_CONDITIONAL_and_an_explicit_driver_name_never_pays_an_embed(graph):
    """D10 AT THE CALL SITE. `resolve()` is called BEFORE `plan_turn` -- before the planner and before
    the walk -- so the first call of a turn pays a COLD bge-m3 encode, MEASURED p50 351.34 / p90 387.35
    ms against a 150 ms budget. The banked 13.44 / 16.24 ms was measured with the query ALREADY in
    `evidence._Q_CACHE`, which is the state the WALK leaves behind and not the state the resolver runs
    in. Two gates answer it and both are asserted here: T2 runs only when T0 and T1 found nothing, and
    a caller whose lane will never walk (so nobody pays the embed back) passes `allow_embed=False`.

    THE EMBED SEAT IS THE PROOF, not the wall clock: a test that timed the tiers would measure this
    box. `embed_fn` is the injection seat, so a counting stub says exactly how many encodes each path
    costs -- zero, or one."""
    calls = []

    def _count(texts):
        calls.append(tuple(texts))
        return [[1.0] + [0.0] * (DIM - 1) for _ in texts]

    vocab = _fake_vocab([("El_Nino", "blurb", _e(0)), ("frost", "blurb", _e(1))])
    # (a) the question NAMES a driver. The behaviour is the LITERAL's: with T2_GATE_TIERS == () (the
    #     orchestrator's 2026-09-10 flip on the held-out table: 93.5% vs 78.3% all-tiers hit) T2 still runs
    #     and pays exactly ONE embed beside the exact hit; with a gate naming "exact", T0 answers alone.
    h = SU.resolve("what does El Nino do to corn", graph=graph, embed_fn=_count, vocab=vocab)
    assert h.exact
    if "exact" in SU.T2_GATE_TIERS:
        assert h.vocab_status == SU.STATUS_SKIPPED and h.candidates == ()
        assert calls == [], "an explicit driver name paid an embed under the gate"
    else:
        assert h.vocab_status == "ok" and len(calls) == 1, "T2 must run beside an exact hit when ungated"
    # (b) the question names none: T2 runs and pays exactly one more
    n_before = len(calls)
    h2 = SU.resolve("the insect that bores into coffee cherries", graph=graph, embed_fn=_count,
                    vocab=vocab)
    assert h2.vocab_status == "ok" and len(calls) == n_before + 1
    # (c) the LANE KNOB: a caller that will not walk refuses the embed and still gets T0 and T1
    calls.clear()
    h3 = SU.resolve("what does El Nino do to corn", graph=graph, embed_fn=_count, vocab=vocab,
                    allow_embed=False)
    assert h3.exact == h.exact and h3.vocab_status == SU.STATUS_SKIPPED and h3.candidates == ()
    h4 = SU.resolve("the insect that bores into coffee cherries", graph=graph, embed_fn=_count,
                    vocab=vocab, allow_embed=False)
    assert h4.vocab_status == SU.STATUS_SKIPPED and h4.candidates == ()
    assert calls == [], "allow_embed=False paid an embed"
    # (d) the DEFAULT is on -- phase B opts OUT per lane, it never opts in
    import inspect
    assert inspect.signature(SU.resolve).parameters["allow_embed"].default is True
    assert inspect.signature(SU.resolve).parameters["allow_embed"].kind is (
        inspect.Parameter.KEYWORD_ONLY)


def test_the_SKIPPED_word_is_closed_aggregatable_and_is_NOT_a_decline(graph):
    """A saved embed and a broken artifact must never be the same word. `BoardSubjectDeclined` is the
    counter a deploy gate reads -- it means the shipped artifact and the shipped graph disagree -- and
    a conditional tier that wore one of those three words would page on every fast turn."""
    assert SU.STATUS_SKIPPED not in SU.VOCAB_STATUS_WORDS
    assert set(SU.HINT_STATUS_WORDS) == set(SU.VOCAB_STATUS_WORDS) | {SU.STATUS_NOT_RUN,
                                                                     SU.STATUS_SKIPPED}
    assert len(SU.HINT_STATUS_WORDS) == len(set(SU.HINT_STATUS_WORDS)) == 6
    bd = B.Board(asof="2026-09-09", mode="deep")
    S._stamp_subject(bd, S._subject_payload({"picked": ["El_Nino"],
                                             "hints": {"vocab_status": SU.STATUS_SKIPPED,
                                                       "ms": 6.0}}), graph=graph)
    cnt = S.counters(bd)
    assert "BoardSubjectDeclined" not in cnt and cnt["BoardSubjectResolved"] == 1
    assert cnt["MsBoardSubject"] == 6
    # ...and an EMPTY query is `not_run`, which is a third state again: nothing to run ON
    assert SU.resolve("   ", graph=graph).vocab_status == SU.STATUS_NOT_RUN


def test_the_only_env_name_in_THIS_DECK_is_the_slow_test_OPT_IN_and_it_gates_FIRST():
    """The regression this closes cost 70 s on every default run: the real-artifact test gated on
    artifact PRESENCE, which every box that has the artifact satisfies, so the opt-in opted nobody out
    and bge-m3 loaded in CI. The gate is now an environment name, it is the resolver's OWN name rather
    than an estate-wide slow-test switch, and it is read BEFORE any artifact call -- a gate that runs
    after the expensive thing is a receipt, not a gate."""
    import inspect
    import re
    src = inspect.getsource(sys.modules[__name__])
    names = sorted(set(re.findall(r"os\.environ\.get\(\s*[\"']([A-Za-z0-9_]+)", src)))
    assert names == ["SUBJECT_RESOLVER_SLOW_TESTS"], names
    body = inspect.getsource(test_LAYER_1_on_the_REAL_artifact)
    gate = body.index('os.environ.get("SUBJECT_RESOLVER_SLOW_TESTS"')
    assert gate < body.index("artifact_status"), body[:400]
    assert "pytest.skip" in body[gate:gate + 300]


def test_the_module_reads_NO_environment_at_all():
    """D1 / risk 9. `check_state_seam` clause (i) allows exactly ONE env name across `state/*`; this
    module is allowed ZERO, because its flag is read at the answer seam and threaded."""
    import inspect
    import re
    src = inspect.getsource(SU)
    assert not re.findall(r"os\.environ\.get\(\s*[\"']([A-Za-z0-9_]+)", src)
    assert "os.environ[" not in src
    assert "\nimport os\n" not in src and "\nimport os " not in src


# ---------------------------------------------------------------------------------------------------
# THE SUBJECT GROUPS (D4) -- the census, BANKED
# ---------------------------------------------------------------------------------------------------
def test_the_group_census_is_BANKED_as_numbers(graph):
    """D4: "MEASURE the groups the two keys produce and bank the census in the tests."

    THE NUMBERS ARE THE POINT. A curation commit that merges or splits a slice moves them, and a
    reviewer then sees WHICH number moved instead of a diff of a YAML nobody reads. Measured
    2026-09-09 on graph 99dc11409fe9 (36 contracts, 405 ids, 1,270 instances)."""
    c = SU.group_census(graph)
    assert c["ids"] == 405
    assert c["slice_keyed_ids"] == 297          # the curated dag_alias reach: 73.3%
    assert c["ref_keyed_ids"] == 108            # every uncovered id HAS a silver_ref -- measured
    assert c["self_keyed_ids"] == 0
    assert c["slice_groups"] == 128
    assert c["ref_groups"] == 69
    assert c["groups"] == 197
    assert c["multi_groups"] == 77              # 61 slice groups + 16 ref groups carry >1 id
    assert c["multi_ids"] == 285                # 230 in slice groups + 55 in ref groups
    assert c["singletons"] == 120
    assert c["largest_group"] == 11             # slice:black_sea_corridor
    assert c["widest_group_boards"] == 36       # `drought` and `heat` each reach every board


def test_the_near_duplicate_families_the_wave_exists_for_are_ONE_group_each(graph):
    """RISK 6: four fertilizer ids, three crude ids, three EUDR ids, five positioning ids, four ids for
    one FX pair. Under a margin rule these tie BY CONSTRUCTION, so a CORRECT resolution would be
    reported as a decline on the estate's most-asked subjects. The group is the answer."""
    g = SU.groups(graph)
    for family in (("fertilizer_cost", "fertilizer_costs", "fertilizer_input_cost",
                    "fertilizer_input_costs"),
                   ("EUDR", "EU_EUDR", "eudr_deforestation"),
                   ("crude_oil", "crude_oil_price", "crude_oil_input_cost"),
                   ("cot_positioning", "cot_mm_positioning", "spec_positioning",
                    "speculative_positioning"),
                   ("BRL_FX", "BRL_USD", "BRL_USD_fx", "BRL_weakness"),
                   ("CNY", "CNY_FX", "CNY_USD")):
        keys = {g[i] for i in family}
        assert len(keys) == 1, (family, keys)
        assert set(SU.expand_group((family[0],), graph)) >= set(family)


def test_the_generic_silver_ref_merges_are_a_DOCKETED_CURATION_FINDING_not_a_threshold(graph):
    """D4's own word: "Any pair that the census shows to be a wrong merge is a curation finding for the
    docket, never a threshold."

    SEVEN of the sixteen multi-id `silver_ref` groups key on a GENERIC balance-sheet attribute, so they
    merge ids that share a MEASUREMENT and not a concept. They are named here so the docket has a list
    and so a curation commit that fixes one moves this test rather than passing unnoticed. THE FENCE
    THAT BOUNDS THE HARM ALREADY EXISTS and is graded on every tier: `BoardKnobs.max_anchors`."""
    g = SU.groups(graph)
    assert g["cbot_corn_price"] == g["cbot_arbitrage"] == "ref:price"
    assert g["stock"] == g["meal_inventory"] == "ref:stock"
    assert g["consumption"] == g["white_food_demand"] == "ref:consumption"
    members = SU.group_members(graph)
    generic = {k: len(v) for k, v in members.items()
               if k in ("ref:export", "ref:import", "ref:stock", "ref:price", "ref:production",
                        "ref:consumption", "ref:area")}
    assert sum(generic.values()) == 28, generic
    # and no generic group is wider than the anchor ceiling can absorb without the walk NAMING the cut
    assert max(generic.values()) <= 6


def test_expand_group_is_deterministic_and_drops_an_id_the_graph_does_not_carry(graph):
    a = SU.expand_group(("fertilizer_cost",), graph)
    b = SU.expand_group(("fertilizer_input_costs", "fertilizer_cost"), graph)
    assert a == b == tuple(sorted(a))
    assert SU.expand_group(("not_a_real_driver_id",), graph) == ()
    assert SU.expand_group((), graph) == ()


# ---------------------------------------------------------------------------------------------------
# THE HINT LINE
# ---------------------------------------------------------------------------------------------------
def test_the_hints_line_is_ASCII_deterministic_and_EMPTY_when_nothing_was_proposed():
    h = SU.SubjectHints()
    assert SU.hints_line(h) == "", "empty hints render nothing -- the caller then omits the line"
    vocab = _fake_vocab([("El_Nino", "blurb", _e(0)), ("La_Nina", "blurb", _e(1))])
    vocab["texts"] = ["Warm ENSO phase shifts rainfall", "Cool ENSO phase shifts rainfall"]
    h = SU.SubjectHints(exact=("El_Nino",), alias=("USD_index",),
                        candidates=(("La_Nina", 0.612345, "blurb"),), vocab_status="ok", ms=2.1)
    line = SU.hints_line(h, vocab=vocab)
    assert line.startswith("subject hints: ")
    assert "\n" not in line and line == " ".join(line.split())
    line.encode("ascii")                                   # never a codec error at the planner seam
    for tok in ("[El_Nino]", "[USD_index]", "[La_Nina]", "0.61"):
        assert tok in line, (tok, line)
    assert SU.hints_line(h, vocab=vocab) == line           # deterministic across calls
    assert SU.hints_line("not a hints object") == ""


def test_the_hint_line_ID_BRACKET_is_the_contract_the_validator_COUNTS_ON():
    """`dispatch._validate` derives `Plan.subject_hints_n` by counting "[<id>]" in the line it was
    handed -- so the census number is what the PLANNER SAW and not what the resolver produced. The
    bracket is a two-sided contract and it is asserted from both sides."""
    vocab = _fake_vocab([("El_Nino", "blurb", _e(0))])
    h = SU.SubjectHints(exact=("El_Nino",), candidates=(("La_Nina", 0.6, "blurb"),))
    line = SU.hints_line(h, vocab=vocab)
    plan = dp._validate({"steps": ["reasoning"], "contracts": []}, {"corn_cbot"}, 2,
                        subject_ids=("El_Nino", "La_Nina", "frost"), subject_hints=line)
    assert plan.subject_hints_n == 2, line
    assert plan.trace()["subject_hints_n"] == 2


def test_the_ambiguity_carry_is_the_AMBIG_FLOOR_and_not_the_candidate_floor():
    """D5. The candidate list is fenced by the PLANNER, which reads it and disposes. The ambiguity row
    interrupts a READER, and nothing but this number fences that."""
    h = SU.SubjectHints(candidates=(("El_Nino", SU.AMBIG_FLOOR + 0.01, "blurb"),
                                    ("La_Nina", SU.AMBIG_FLOOR - 0.01, "blurb")))
    assert [c[0] for c in h.ambiguous()] == ["El_Nino"]
    assert len(h.candidates) == 2, "the candidate list is unchanged -- only the CARRY is fenced"
    assert h.ids() == ("El_Nino", "La_Nina")


# ---------------------------------------------------------------------------------------------------
# THE THREE CLOSED SETS, THE ANCHOR SOURCE, AND THE EMF DIMENSION
# ---------------------------------------------------------------------------------------------------
def test_subject_ambiguous_is_registered_in_ALL_THREE_closed_sets():
    """D5. Two of three is a word that stamps and then renders as the fallback, or one that renders and
    cannot be stamped -- `check_reason` raises AT THE STAMP on an unregistered word."""
    assert "subject_ambiguous" in B.BOARD_REASONS
    assert "subject_ambiguous" in B.REASONS_WITH_DETAIL
    assert "subject_ambiguous" in R.ABSENCE_WHY
    assert B.check_reason("board", "subject_ambiguous") is None
    assert B.check_reason("board", "subject_ambiguous:El_Nino|La_Nina") is None
    assert B.check_reason("board", "subject_ambiguus") is not None
    assert not any(ch.isdigit() for ch in R.ABSENCE_WHY["subject_ambiguous"])


def test_the_EMF_dimension_is_the_BARE_word_and_the_ids_ride_the_trace(graph):
    """RISK 4.3 / D5. Two driver ids joined by a pipe as a CloudWatch dimension VALUE is exactly the
    unbounded cardinality `reason_dimension` exists to refuse, on a metric nobody could then
    aggregate. `reason_word` splits on the colon only, so the pipe survives INTO the trace -- which is
    where it belongs."""
    assert S.reason_dimension("subject_ambiguous:El_Nino|La_Nina") == "subject_ambiguous"
    assert B.reason_word("subject_ambiguous:El_Nino|La_Nina") == "subject_ambiguous"
    assert S.reason_dimension("subject_ambiguous") == "subject_ambiguous"


def test_the_anchor_source_sits_BETWEEN_focus_driver_and_named(graph):
    """D6. An FE `focus_driver` attachment is a CLICK; a subject is an INFERENCE about a typed phrase,
    and an explicit gesture wins. A market the question NAMED is context for the cause it asks about,
    so the subject outranks it."""
    src = B.ANCHOR_SOURCES
    assert src.index("focus_driver") < src.index("subject") < src.index("named")
    with pytest.raises(ValueError):
        B.Anchor(contract="corn_cbot", source="subject_resolved")
    B.Anchor(contract="corn_cbot", source="subject")       # the word IS declared


def test_the_absence_row_names_BOTH_drivers_in_reader_words_and_asks():
    """D5 / RISK 8. `absence_why()` DROPS the detail on purpose -- every other detail is a count, and a
    count in a letters-only class is a digit. A subject's detail is two NAMES and it MUST render."""
    row = R.sb_subject_ambiguous(["El_Nino", "La_Nina"])
    assert R.classify(row) == ("SB-X",), R.classify(row)
    assert "El Nino" in row and "La Nina" in row
    assert "El_Nino" not in row and "La_Nina" not in row, "a raw id trips register.internal_leaks"
    assert "name the one you mean" in row
    row.encode("ascii")
    assert not any(ch.isdigit() for ch in row)
    # the ordinary route still yields a true, complete sentence with no names
    assert R.absence_why("subject_ambiguous:El_Nino|La_Nina") == R.ABSENCE_WHY["subject_ambiguous"]
    assert R.sb_subject_ambiguous([]) == R.sb_absence("subject", "subject_ambiguous")


def test_a_SINGLE_ambiguous_id_renders_in_the_SINGULAR_and_never_counts_to_two():
    """`ABSENCE_WHY['subject_ambiguous']` says 'either of TWO drivers', which is true of the state D5
    usually carries and false of a one-id carry -- and a one-id carry is reachable, because AMBIG_FLOOR
    is a FLOOR and not a pair rule: one candidate can clear it while the planner picks nothing. The
    plural sentence then counted to two and named one, in a row whose whole job is to be read."""
    one = R.sb_subject_ambiguous(("El_Nino",))
    assert R.classify(one) == ("SB-X",), R.classify(one)
    assert "El Nino" in one and "El_Nino" not in one
    assert "either of two" not in one.lower(), one
    assert "it could mean" in one.lower() and "opens on it" in one
    assert not any(ch.isdigit() for ch in one), "SB-X is a letters-only class"
    # ...and the plural is untouched: two ids still count to two and still ASK
    two = R.sb_subject_ambiguous(("El_Nino", "La_Nina"))
    assert "either of two" in two.lower() and "name the one you mean" in two
    # THREE is the estate's ordinary list join, and the seam caps the carry at two regardless
    three = R.sb_subject_ambiguous(("El_Nino", "La_Nina", "frost"))
    assert "El Nino, La Nina or frost" in three, three
    one.encode("ascii")


def test_the_state_lint_and_the_narration_register_stay_CLEAN():
    """`check_state_seam` clause (iii) grades `narration.check_literals()` EMPTY at build, and
    `state/lint.py`'s clause 9 grades every closed word against `ABSENCE_WHY` in both directions -- a
    sentence with no word is a vocabulary nobody can reach."""
    from leviathan.graphrag.state import lint as L
    from leviathan.graphrag.state import narration as N
    assert N.check_literals() == []
    # clause 9 grades the vocabularies against ABSENCE_WHY in BOTH directions -- a word with no
    # sentence renders as the fallback, and a sentence with no word is a vocabulary nobody can reach
    assert L._check_absence_vocabulary() == []
    assert L._check_row_classes() == [], "the new absence row must not break class disjointness"
    assert [e for e in L.check_state_board() if "subject" in e] == []


# ---------------------------------------------------------------------------------------------------
# THE WALK AND THE SEAM
# ---------------------------------------------------------------------------------------------------
def test_a_subject_anchors_its_GROUP_and_is_EXEMPT_from_max_contracts(graph):
    """D6 / Amendment 1's shape. The anchor set is every contract carrying any id of the group, read
    off the graph rather than PLANNED -- so `max_contracts`, which bounds the planner's own
    enumeration, does not apply to it. The TOTAL is still bounded, by `BoardKnobs.max_anchors`, which
    `walk()` applies after this function."""
    anchors = W.resolve_anchors(graph=graph, subject=("fertilizer_cost",), max_contracts=1,
                                contracts=["corn_cbot", "soybeans_cbot", "arabica_coffee"])
    subj = [a for a in anchors if a.source == "subject"]
    assert len(subj) > 1, "one subject id anchored one board -- the group did not expand"
    assert all(a.group for a in subj), "an anchor does not record which group ids it carries"
    for a in subj:
        ids = set(a.group)
        assert ids <= set(SU.expand_group(("fertilizer_cost",), graph))
        assert any(d.id in ids for d in graph.contracts[a.contract].drivers)
    inferred = [a for a in anchors if a.source == "planner_inferred"]
    assert len(inferred) <= 1, "the ceiling still bounds the seeds the planner INFERRED"
    # `Anchor.group` IS READ, not merely written. Its stated purpose is "what lets the render and the
    # trace say which name this board answered under", and until the trace carried the per-board
    # intersection its only reader was the anchor collapse itself: the trace carried the pick -> group
    # map, which is a property of the SUBJECT, and never which of those ids each board actually has.
    bd = B.Board(asof="2026-09-09", mode="deep")
    bd.anchors = anchors
    S._stamp_subject(bd, S._subject_payload(["fertilizer_cost"]), graph=graph)
    carried = bd.trace()["subject"]["carried"]
    assert carried and set(carried) == {a.contract for a in subj}
    for slug, ids in carried.items():
        assert set(ids) == set(bd.subject_ids_on(slug))
        assert set(ids) <= set(SU.expand_group(("fertilizer_cost",), graph))


def test_an_FE_focus_driver_OUTRANKS_a_differing_subject_and_NEVER_silences_it(graph):
    """D6 / RISK 4. A silent override is the exact class `Anchor.named` was added to close. BOTH
    anchor, the precedence orders them, and the seam stamps the disagreement."""
    # `HLB` sits on ONE board and `El_Nino` on thirty-five, so the two gestures overlap on exactly
    # that one -- which is what makes the collapse visible instead of theoretical.
    anchors = W.resolve_anchors(graph=graph, focus_driver="HLB", subject=("El_Nino",),
                                max_contracts=0)
    srcs = [a.source for a in anchors]
    assert "focus_driver" in srcs and "subject" in srcs
    assert srcs.index("focus_driver") < srcs.index("subject"), "the CLICK outranks the inference"
    # THE OVERLAP COLLAPSES TO THE STRONGER WORD -- and keeps the record of having been both, which is
    # the whole reason `Anchor.group` is a field beside `source` rather than folded into it. Without
    # it the anchor ceiling would cut this board while keeping the subject's thirty-fifth.
    both = [a for a in anchors if a.source == "focus_driver"]
    assert both and all("El_Nino" in a.group for a in both), [(a.contract, a.group) for a in both]
    # ...and every board that is ONLY the subject's still says so
    assert all(a.group == ("El_Nino",) for a in anchors if a.source == "subject")


def test_resolve_anchors_with_NO_subject_is_the_S6_builds_own_output(graph):
    """OMIT-WHEN-OFF, one layer below the planner. Every turn the resolver does not reach takes the
    branch S6 landed, and the anchor tuple is equal field for field."""
    kw = dict(graph=graph, contracts=["corn_cbot", "soybeans_cbot"], named=("corn_cbot",),
              max_contracts=2)
    a = W.resolve_anchors(**kw)
    b = W.resolve_anchors(**kw, subject=())
    c = W.resolve_anchors(**kw, subject=None)
    assert a == b == c
    assert all(x.group == () for x in a)


def test_the_seam_threads_the_subject_and_stamps_the_trace_sub_dict(graph):
    """D8: the subject rides `Board.trace()`'s ALREADY-REGISTERED `state_board` payload. Appending a
    NEW top-level trace key would red SEVEN test files' negative-index tail pins (the S5 measurement),
    so this costs zero registry churn and zero re-pins."""
    bd = B.Board(asof="2026-09-09", mode="deep")
    S._stamp_subject(bd, S._subject_payload({"picked": ["El_Nino"], "hints": {"vocab_status": "ok",
                                                                             "ms": 3.0}}),
                     graph=graph, focus_driver="")
    tr = bd.trace()
    assert "subject" in tr
    assert set(tr["subject"]) == {"hints", "picked", "groups", "source", "vs_focus"}
    assert tr["subject"]["picked"] == ["El_Nino"]
    assert tr["subject"]["groups"]["El_Nino"] == list(SU.expand_group(("El_Nino",), graph))
    # ...and a board the resolver never reached carries NO subject key at all
    assert "subject" not in B.Board(asof="2026-09-09", mode="deep").trace()


def test_vs_focus_says_DIFFER_only_when_the_two_gestures_actually_disagree(graph):
    bd = B.Board(asof="2026-09-09", mode="deep")
    S._stamp_subject(bd, S._subject_payload(["frost"]), graph=graph, focus_driver="El_Nino")
    assert bd.subject["vs_focus"] == "differ"
    bd2 = B.Board(asof="2026-09-09", mode="deep")
    S._stamp_subject(bd2, S._subject_payload(["El_Nino"]), graph=graph, focus_driver="El_Nino")
    assert bd2.subject["vs_focus"] == "same"
    bd3 = B.Board(asof="2026-09-09", mode="deep")
    S._stamp_subject(bd3, S._subject_payload(["El_Nino"]), graph=graph, focus_driver="")
    assert bd3.subject["vs_focus"] == ""


def test_the_ambiguity_declines_ONLY_an_anchorless_board(graph):
    """A turn that anchored on markets the user named has an answer to give; replacing it with a
    question would be a fence that DELETES, which doctrine forbids. An ANCHORLESS board would have
    declined `anchor_none`, and `subject_ambiguous` is strictly more informative about that turn."""
    payload = {"picked": [], "ambiguous": ["El_Nino", "La_Nina"], "hints": {"vocab_status": "ok"}}
    bare = B.Board(asof="2026-09-09", mode="deep")
    S._stamp_subject(bare, S._subject_payload(payload), graph=graph)
    assert bare.legs["board"]["reason"] == "subject_ambiguous:El_Nino|La_Nina"
    assert S.reason_dimension(bare.legs["board"]["reason"]) == "subject_ambiguous"
    anchored = B.Board(asof="2026-09-09", mode="deep")
    anchored.anchors = (B.Anchor(contract="corn_cbot", source="named", named=True),)
    S._stamp_subject(anchored, S._subject_payload(payload), graph=graph)
    assert "board" not in anchored.legs, "an anchored board is never turned into a question"
    assert [n for n in anchored.notes if n.get("kind") == "subject_ambiguous"]


def test_the_ambiguity_is_carried_ONLY_when_the_planner_PICKED_NOTHING(graph):
    """D5's own condition, which the seam did not carry: `SubjectHints.ambiguous()` is what is carried
    'when the planner returns NO subject', and `_stamp_subject` appended the note whenever the tuple
    was non-empty. A board that opened on the planner's pick would then have printed, underneath its
    own answer, a row asking the reader which of two drivers they meant -- an answer and a question
    about the same turn, in the same block.

    NOTHING IS DELETED BY THE FENCE: both ids stay on the trace under `hints`, which is where a census
    reads them. Only the row that INTERRUPTS a reader is fenced, which is AMBIG_FLOOR's own posture."""
    payload = {"picked": ["El_Nino"], "ambiguous": ["El_Nino", "La_Nina"],
               "hints": {"vocab_status": "ok", "ms": 3.0,
                         "candidates": [["El_Nino", 0.81, "blurb"], ["La_Nina", 0.79, "blurb"]]}}
    bd = B.Board(asof="2026-09-09", mode="deep")
    bd.anchors = (B.Anchor(contract="corn_cbot", source="subject", named=True),)
    S._stamp_subject(bd, S._subject_payload(payload), graph=graph)
    assert "ambiguous" not in bd.subject, "a picked subject still asked the reader to choose"
    assert [n for n in bd.notes if n.get("kind") == "subject_ambiguous"] == []
    assert "BoardSubjectAmbiguous" not in S.counters(bd)
    assert bd.subject["picked"] == ["El_Nino"]
    # ...and the two ids are still on the trace, under the tiers' own payload
    assert [c[0] for c in bd.trace()["subject"]["hints"]["candidates"]] == ["El_Nino", "La_Nina"]
    # THE UNPICKED TURN IS UNCHANGED -- the fence is on `picked`, never on the carry itself
    other = B.Board(asof="2026-09-09", mode="deep")
    other.anchors = bd.anchors
    S._stamp_subject(other, S._subject_payload({**payload, "picked": []}), graph=graph)
    assert other.subject["ambiguous"] == ["El_Nino", "La_Nina"]


def test_the_subject_timer_is_ABSENT_below_a_millisecond_and_NEVER_a_literal_zero(graph):
    """`orchestrator.py:2619` types every `Ms`-prefixed key as MILLISECONDS, so `int(0.4)` does not
    publish 'under half a millisecond' -- it publishes a zero-latency SAMPLE, and a p50 built from a
    population of them says the resolver is free on turns where it ran. The tier's RUN is witnessed by
    `BoardSubjectResolved` and by the trace, so the absent key costs no fact."""
    def _counters(ms):
        bd = B.Board(asof="2026-09-09", mode="deep")
        S._stamp_subject(bd, S._subject_payload({"picked": ["El_Nino"],
                                                 "hints": {"vocab_status": "ok", "ms": ms}}),
                         graph=graph)
        return S.counters(bd), bd
    for sub in (0.0, 0.4, 0.99):
        cnt, bd = _counters(sub)
        assert "MsBoardSubject" not in cnt, sub
        assert cnt["BoardSubjectResolved"] == 1              # it RAN, and the census still says so
        assert bd.trace()["subject"]["hints"]["ms"] == sub   # the fraction survives on the trace
    assert _counters(1.0)[0]["MsBoardSubject"] == 1
    assert _counters(6.97)[0]["MsBoardSubject"] == 6


def test_the_counters_are_ABSENT_when_inapplicable_and_the_Ms_prefix_types_the_timer(graph):
    """D8 / 10.5. ABSENT IS NEVER ZERO: on a turn the resolver did not run the keys are missing, so the
    metrics have no zero-population to dilute and a census can tell 'off' from 'ran and found nothing'.
    `orchestrator.py:2619` types any `Ms`-prefixed key as Milliseconds, which is why the timer is
    named `MsBoardSubject` and not `SubjectMs` -- no new EMF record, no new dimension."""
    bd = B.Board(asof="2026-09-09", mode="deep")
    bd.stamp("board", "declined", reason="anchor_none")
    assert not any(k.startswith("BoardSubject") or k == "MsBoardSubject" for k in S.counters(bd))
    S._stamp_subject(bd, S._subject_payload({"picked": ["El_Nino"],
                                             "hints": {"vocab_status": "ok", "ms": 4.7}}),
                     graph=graph)
    cnt = S.counters(bd)
    assert cnt["BoardSubjectResolved"] == 1 and cnt["MsBoardSubject"] == 4
    assert "BoardSubjectAmbiguous" not in cnt and "BoardSubjectDeclined" not in cnt
    stale = B.Board(asof="2026-09-09", mode="deep")
    stale.stamp("board", "declined", reason="anchor_none")
    S._stamp_subject(stale, S._subject_payload({"picked": [],
                                                "hints": {"vocab_status": "stale"}}), graph=graph)
    assert S.counters(stale)["BoardSubjectDeclined"] == 1


def test_the_carried_ambiguity_REACHES_A_READER_on_an_ANCHORED_board(graph):
    """D5's reader half, and it is a REGRESSION PIN before it is a feature test.

    `render.sb_subject_ambiguous` existed, was ASCII, was register-clean and had ZERO production
    callers: `seam._stamp_subject` appended a note of kind `subject_ambiguous` into a loop
    (`render.render_board`, the notes pass) that branched on six kinds and had no case for it and no
    else. The stamp fired, the trace carried both ids, the counter incremented -- and the block said
    nothing, which is the silent-decline class this board's whole closed decline vocabulary exists to
    close. This asserts the ROW, out of the loop that renders it."""
    bd = B.Board(asof="2026-09-09", mode="deep")
    bd.anchors = (B.Anchor(contract="corn_cbot", source="named", named=True),)
    S._stamp_subject(bd, S._subject_payload({"picked": [],
                                             "ambiguous": ["El_Nino", "La_Nina"],
                                             "hints": {"vocab_status": "ok", "ms": 3.0}}),
                     graph=graph)
    blk = R.render_board(bd, anchor_label="corn")
    text = blk.text()
    assert "It could mean" in text and "El Nino" in text and "La Nina" in text, text
    assert "name the one you mean" in text
    assert "El_Nino" not in text, "a raw id in a rendered block trips register.internal_leaks"
    assert blk.trips == [], blk.trips
    # ...and the counter measures what the reader was SHOWN, on the anchored path too
    assert S.counters(bd).get("BoardSubjectAmbiguous") == 1


def test_the_ANCHORLESS_ambiguity_mints_the_one_block_a_DECLINED_board_may_carry(graph):
    """THE OTHER HALF OF THE SAME GAP. `_stamp_subject` takes the decline ONLY on an anchorless board
    -- correct, a board with markets to talk about must not be replaced by a question -- and
    `fill_stage2` gates the ENTIRE render on `bd.anchors`. So the one board that could stamp the word
    was the one board guaranteed to produce no reader text, and D5's absence row held for nobody.

    MEASURED before the fix: `fill_stage2` returned `block=''` (len 0) on exactly this input."""
    out = S.fill_stage2(_declined_ambiguous_board(graph), graph=graph, sg=None)
    assert out.get("block"), "the anchorless ambiguity still renders nothing"
    assert "It could mean" in out["block"] and "El Nino" in out["block"] and "La Nina" in out["block"]
    assert R.classify(out["block"].splitlines()[0]) == ("SB-X",)
    # THE LEG IS STILL A DECLINE and the payload is still absent -- a block is not a board that fired.
    assert out["trace"]["legs"]["board"]["reason"].startswith("subject_ambiguous:")
    assert out["request"] is None
    assert out["counters"]["BoardSubjectAmbiguous"] == 1


def _declined_ambiguous_board(graph):
    bd = B.Board(asof="2026-09-09", mode="deep")
    bd.knobs = B.board_knobs_of("deep")
    bd.stage_done[1] = True
    S._stamp_subject(bd, S._subject_payload({"picked": [], "ambiguous": ["El_Nino", "La_Nina"],
                                             "hints": {"vocab_status": "ok", "ms": 3.0}}),
                     graph=graph)
    return bd


def test_the_ambiguity_carry_survives_the_WHOLE_seam_end_to_end(graph):
    """Both seams, in the order serving runs them, on the shape that produced the gap: a turn that
    named no market and whose planner declined to choose between two drivers. `fill_stage1` walks to
    an anchorless board (which S6 stamps `anchor_none` and says nothing about), `_stamp_subject`
    replaces that word with the strictly more informative one, and `fill_stage2` renders the row."""
    class _SG:
        seeds: list = []
        trace: dict = {}

    bd = S.fill_stage1(graph=graph, sg=_SG(), asof="2026-09-09", mode="deep",
                       query="the warm phase or the cool one",
                       subject={"picked": [], "ambiguous": ["El_Nino", "La_Nina"],
                                "hints": {"vocab_status": "ok", "ms": 2.0}})
    assert bd is not None
    assert bd.legs["board"]["reason"] == "subject_ambiguous:El_Nino|La_Nina"
    out = S.fill_stage2(bd, graph=graph, sg=_SG())
    assert "It could mean" in out["block"] and "El Nino" in out["block"], out.get("block")
    assert out["counters"]["BoardSubjectAmbiguous"] == 1
    assert out["trace"]["subject"]["ambiguous"] == ["El_Nino", "La_Nina"]


def test_the_anchor_ORDER_leads_on_the_NAMED_market_and_the_precedence_is_only_a_LABEL(graph):
    """THE D6 AMENDMENT, which the first build did not implement: "the precedence word is a LABEL, the
    anchor ORDER is a separate rule ... A named market always leads its turn".

    MEASURED before the fix, on the amendment's own example (subject El_Nino, named corn_cbot): the
    block LED ON `robusta_coffee` and `corn_cbot` took the LAST surviving seat at every tier -- quick
    3/4, deep 5/6, max 7/8 -- because `resolve_anchors` sorted by `ANCHOR_SOURCES.index`, where
    `subject` (2) outranks `named` (3). The precedence still decides the WORD and the trim; the ORDER
    is `ANCHOR_ORDER`'s."""
    anchors = W.resolve_anchors(graph=graph, contracts=["corn_cbot"], named=("corn_cbot",),
                                subject=("El_Nino",), max_contracts=2)
    assert anchors[0].contract == "corn_cbot", [a.contract for a in anchors[:3]]
    # THE PRECEDENCE STILL COLLAPSED IT TO THE STRONGER WORD -- which is why the order reads `named`
    # and not `source`: corn_cbot is BOTH, and the word that survives is `subject`.
    assert anchors[0].source == "subject" and anchors[0].named is True
    assert all(not a.named for a in anchors[1:]), "only the typed board carries the named flag"
    # ...AND A NAMED MARKET THAT DOES NOT CARRY THE SUBJECT AT ALL still leads. That is the harder
    # half: no collapse happens, the board is `named` outright, and it sat at seat 5 of 6 behind five
    # subject boards under the source-word order.
    off = [c for c in sorted(graph.contracts)
           if not any(d.id == "El_Nino" for d in graph.contracts[c].drivers)]
    assert off, "every board carries El_Nino -- pick another subject for this leg"
    a2 = W.resolve_anchors(graph=graph, named=(off[0],), subject=("El_Nino",), max_contracts=0)
    assert a2[0].contract == off[0] and a2[0].source == "named"
    # a GESTURE still leads a named market
    withfd = W.resolve_anchors(graph=graph, named=("cocoa",), subject=("El_Nino",),
                               focus_driver="HLB", max_contracts=0)
    assert withfd[0].source == "focus_driver"
    assert withfd[1].contract == "cocoa" and withfd[1].named is True
    # THE TWO TUPLES ARE ONE VOCABULARY IN TWO ORDERS, and the permutation is what makes that safe
    assert sorted(B.ANCHOR_ORDER) == sorted(B.ANCHOR_SOURCES)
    assert B.ANCHOR_ORDER.index("named") < B.ANCHOR_ORDER.index("subject")
    assert B.ANCHOR_SOURCES.index("subject") < B.ANCHOR_SOURCES.index("named")
    # ...and with NO subject on the turn the two orders agree seat for seat
    kw = dict(graph=graph, contracts=["corn_cbot", "soybeans_cbot"], named=("corn_cbot",),
              focus_driver="HLB", max_contracts=2)
    assert ([a.contract for a in W.resolve_anchors(**kw)]
            == [a.contract for a in W.resolve_anchors(**kw, subject=())])


def test_the_D6_EXAMPLE_ITSELF_corn_leads_and_the_El_Nino_boards_FOLLOW(graph):
    """THE AMENDMENT'S OWN SENTENCE, run from the PHRASE rather than from a hand-built anchor list:
    "what does the pacific warming do to corn" -> corn leads, El Nino's boards follow.

    THE MARKETS COME FROM THE SHIPPED ROUTER (`dispatch.named_markets`), which is what the seam threads
    as `named`, so this pins the two producers together instead of asserting the amendment against a
    literal. THIRTY-FIVE boards carry El_Nino; exactly one of them is the board the question typed.

    AND IT CARRIES THE CURATION FINDING RATHER THAN HIDING IT: this phrase is deck row sy01, the
    measured miss -- 'the pacific warming' does not reach `El_Nino` through T2 at all, because no blurb
    of its 105 rows says Pacific or warming, and it is a one-line `driver_slices.yaml` fix. So the
    SUBJECT here is the id the planner would pick, threaded the way phase B will thread it, and the
    resolver's own tiers are asserted to find nothing on this phrase -- which is the honest state."""
    q = "what does the pacific warming do to corn"
    named = dp.named_markets(q, graph)
    assert named[0] == "corn_cbot", named
    hints = SU.resolve(q, graph=graph, vocab=None, path=ROOT / "nope.npz")
    assert hints.exact == () and hints.alias == (), "sy01 is a SEMANTIC row; the free tiers miss it"
    anchors = W.resolve_anchors(graph=graph, named=named[:1], subject=("El_Nino",), max_contracts=0)
    assert anchors[0].contract == "corn_cbot", [a.contract for a in anchors[:4]]
    assert anchors[0].named is True and anchors[0].group == ("El_Nino",)
    followers = [a.contract for a in anchors[1:]]
    assert followers, "the fan-out disappeared"
    assert all(any(d.id == "El_Nino" for d in graph.contracts[c].drivers) for c in followers)
    assert "robusta_coffee" in followers, followers      # the board that LED before the amendment
    assert len(anchors) == 35, len(anchors)             # every board carrying the id, corn first


def test_the_named_market_SURVIVES_the_anchor_cut_and_leads_the_block(graph):
    """The trim is unchanged -- gestures and named markets are HELD, the rest is cut in precedence
    order -- but which board the reader MEETS FIRST is the amendment's whole point. Measured at all
    three tiers, because the tier is what sizes `max_anchors`."""
    for mode in ("quick", "deep", "max"):
        kn = B.board_knobs_of(mode)
        bd = B.Board(asof="2026-09-09", mode=mode)
        bd.anchors = W.resolve_anchors(graph=graph, contracts=["corn_cbot"], named=("corn_cbot",),
                                       subject=("El_Nino",), max_contracts=2)
        held = [a for a in bd.anchors
                if a.source in ("attached_event", "named") or a.named]
        rest = [a for a in bd.anchors if a not in held][:max(0, kn.max_anchors - len(held))]
        kept = held + rest
        assert kept[0].contract == "corn_cbot", (mode, [a.contract for a in kept[:3]])
        assert len(kept) == max(kn.max_anchors, len(held)), mode


def test_positionings_context_only_EXCEPTION_is_LIVE_on_the_RESOLVED_path(graph):
    """D6: "Positioning as a subject keeps the D18 `context_only` exception." It did not.

    `Board.subject_driver` filtered `a.source == "focus_driver"`, and it is the SECOND reader of that
    predicate (`walk._stage1` reads THIS): MEASURED, the FE `focus_driver` path marked 6 of 6
    `cot_mm_positioning` rows `row.subject=True` and the resolved-subject path marked 0, leaving a row
    `context_only=True` on the very turn whose subject it is. A GROUP is the reason a single
    `driver_id` cannot answer -- five positioning ids are one subject."""
    pos = S._positioning_ids()
    assert pos == ("cot_mm_positioning",), pos
    fe = W.resolve_anchors(graph=graph, focus_driver="cot_mm_positioning", positioning_ids=pos,
                           max_contracts=0)
    sub = W.resolve_anchors(graph=graph, subject=("cot_mm_positioning",), positioning_ids=pos,
                            max_contracts=0)
    assert fe and sub
    assert all(a.subject for a in fe), "the FE path lost the positioning flag"
    # EVERY BOARD THE FE PATH FLAGS, THE RESOLVED PATH FLAGS TOO -- and the resolved set is WIDER,
    # because a pick expands to its group (four cftc ids): the extra boards carry a SIBLING id and not
    # the estate's one positioning ref, so they correctly do not claim the exception.
    _fe_flagged = {a.contract for a in fe if a.subject}
    _sub_flagged = {a.contract for a in sub if a.subject}
    assert _fe_flagged and _fe_flagged == _sub_flagged, (sorted(_fe_flagged), sorted(_sub_flagged))
    assert len(sub) > len(fe), "the group did not expand"
    for anchors in (fe, sub):
        bd = B.Board(asof="2026-09-09", mode="deep")
        bd.anchors = anchors
        one = sorted(_fe_flagged)[0]
        assert "cot_mm_positioning" in bd.subject_ids_on(one), (one, bd.subject_ids_on(one))
    # and the single-valued reader answers for BOTH sources, the CLICK first
    bd = B.Board(asof="2026-09-09", mode="deep")
    bd.anchors = sub
    assert bd.subject_driver == "cot_mm_positioning"
    # ...AND THE ROW ACTUALLY CARRIES IT, end to end through `walk` on the shared fixture harness --
    # `row.subject` is what lifts `context_only`, and marking the anchor without marking the row is
    # exactly the half-wiring this test exists to close.
    import test_state_walk as TSW  # the state deck's own fixture harness
    for anchors in (fe, sub):
        picked = [a for a in anchors if a.contract in _fe_flagged][:2]
        wb = W.walk(graph=graph, asof="2026-09-07", mode="deep", anchors=tuple(picked),
                    state_fn=TSW._flat_state_fn(), key_fn=TSW._key_fn(), receipts={},
                    turn_kind="outlook", positioning_ids=pos)
        rows = [r for r in wb.rows if r.driver_id == "cot_mm_positioning"]
        assert rows, [a.contract for a in picked]
        assert all(r.subject and not r.context_only for r in rows), [
            (r.contract, r.subject, r.context_only) for r in rows]


def test_the_wrong_merge_census_runs_on_BOTH_keys_and_is_BANKED_by_name(graph):
    """D4: "Any pair that the census shows to be a wrong merge is a curation finding for the docket,
    never a threshold" -- and the census that surfaces them must run on the key that PRODUCES them.
    The first docket named the seven generic `silver_ref` merges, which is 108 of 405 ids; the SLICE
    key is the primary one (297 of 405) and it is where the merges with teeth are.

    MEASURED 2026-09-10 on graph 99dc11409fe9. These are CURATION findings, banked so a commit that
    fixes one moves a number rather than passing unnoticed."""
    mc = SU.merge_census(graph)
    assert mc["multi_groups"] == 77
    # OPPOSITE SIGNS ON ONE BOARD -- the class with teeth: a pick anchors under the opposite phase
    assert mc["sign_flip"]["n"] == 14
    assert mc["sign_flip"]["slice"] == 11 and mc["sign_flip"]["ref"] == 3
    for k in ("ref:iod_climate",              # IOD_positive merged with IOD_negative, 18 boards
              "slice:biennial_bearing",       # a coffee cycle's on-year merged with its off-year
              "slice:cocoa_grindings",        # demand_destruction merged with grind_demand
              "slice:cotton_polyester_competition",
              "slice:china_reserve_auctions",
              "slice:black_sea_corridor"):
        assert k in mc["sign_flip"]["names"], k
    assert mc["sign_mixed"]["n"] == 6         # a declared '0' beside a '+' or '-': a weaker reading
    # DIFFERENT DECLARED TYPES -- a REVIEW list and never a defect count: the estate carries 34 type
    # words with many near-synonyms, which the recon measured and warned not to weight.
    assert mc["type_mixed"]["n"] == 43
    assert mc["type_mixed"]["slice"] == 33 and mc["type_mixed"]["ref"] == 10
    # A TOPIC FAMILY RATHER THAN A SYNONYM SET -- four ids or more
    assert mc["wide"]["n"] == 32
    assert mc["wide"]["slice"] == 26 and mc["wide"]["ref"] == 6
    for k in ("slice:rice_blast_pest_complex", "slice:cotton_pest_complex",
              "slice:rapeseed_disease_pest", "slice:sugarcane_disease_pest",
              "slice:black_sea_corridor", "slice:tariff"):
        assert k in mc["wide"]["names"], k
    # THE BLAST RADIUS IS THE REASON THESE ARE DOCKETED, and it is measured rather than asserted
    assert SU.groups(graph)["IOD_positive"] == SU.groups(graph)["IOD_negative"]
    assert SU.expand_group(("IOD_positive",), graph) == ("IOD_negative", "IOD_positive")

    def _boards(ids):
        return sum(1 for c in graph.contracts
                   if any(d.id in set(ids) for d in graph.contracts[c].drivers))

    for pick, own, grp in (("fertilizer_cost", 5, 17), ("cot_mm_positioning", 14, 20),
                           ("soybean_corn_price_ratio", 2, 10)):
        assert _boards((pick,)) == own, (pick, _boards((pick,)))
        assert _boards(SU.expand_group((pick,), graph)) == grp, (pick,
                                                                 _boards(SU.expand_group((pick,),
                                                                                         graph)))


def test_the_hints_line_carries_a_BLURB_by_default_because_the_frozen_block_promises_one(graph):
    """The sha-pinned planner section tells the planner to expect "nearest matches by meaning with
    each driver's one-line description". With `vocab=None` the line carried NO description at all, so
    a caller that forgot the argument would ship a prompt promising a field the line never has -- and
    correcting the PROMPT instead voids the freeze and consumes the held-out set. The default now
    LOADS; `vocab=None` is the explicit request for the names-and-scores floor."""
    import inspect
    sig = inspect.signature(SU.hints_line)
    assert sig.parameters["vocab"].default is SU._LOAD_VOCAB, "the default is not the load"
    h = SU.SubjectHints(exact=("El_Nino",), candidates=(("La_Nina", 0.61, "blurb"),))
    floor = SU.hints_line(h, vocab=None)
    assert "--" not in floor, floor           # the explicit no-prose floor still renders
    assert "[La_Nina]" in floor and "0.61" in floor
    # the DEFAULT reaches the artifact when there is one; when there is not, it degrades to the floor
    status, _stamped, _live = SU.artifact_status()
    line = SU.hints_line(h)
    if status == "ok":
        assert " -- " in line, line
    else:                                      # a checkout that never built the 25 MB binary
        assert line == floor
    # AND AN EMPTY-HINTS CALL NEVER TOUCHES THE ARTIFACT: the load sits inside the candidates branch
    SU._reset_caches()
    assert SU.hints_line(SU.SubjectHints()) == ""
    assert not SU._VOCAB_CACHE, "an empty hint line loaded a 25 MB artifact"


def test_fill_stage1_and_answer_carry_the_kwarg_and_read_NO_flag():
    """D11: phase A is a kwarg thread. The flag reader is phase B's, in the orchestrator."""
    import inspect
    from leviathan.graphrag import answer as an
    assert "subject" in inspect.signature(S.fill_stage1).parameters
    assert "subject" in inspect.signature(an.answer).parameters
    assert "subject" in inspect.signature(an._answer_l2).parameters
    assert "subject=subject" in inspect.getsource(an._answer_l2)
    # THE FLAG IS NAMED IN PROSE AND READ NOWHERE. The assertion is over the READ and not over the
    # WORD, because both files document the seam by name -- a substring ban would red on a comment,
    # which is the same mistake `check_state_seam` clause (i) records having avoided.
    import re
    for name, src in (("answer._answer_l2", inspect.getsource(an._answer_l2)),
                      ("dispatch", inspect.getsource(dp))):
        reads = re.findall(r"os\.environ(?:\.get)?[\(\[]\s*[\"']([A-Za-z0-9_]+)", src)
        assert "GRAPHRAG_SUBJECT_RESOLVER" not in reads, (name, reads)


# ---------------------------------------------------------------------------------------------------
# THE PLANNER'S FOUR SITES, AND THE FLAG-OFF BYTE IDENTITY
# ---------------------------------------------------------------------------------------------------
def _head_dispatch():
    """HEAD's `dispatch.py`, LOADED AS ITS OWN MODULE. The only way to prove flag-off byte identity of
    a function is to run HEAD's copy of it beside the tree's on the same inputs. `git show HEAD:<path>`
    is a READ: nothing here mutates a ref, touches the index or writes into the worktree."""
    src = subprocess.check_output(["git", "show", "HEAD:src/leviathan/graphrag/dispatch.py"],
                                  cwd=str(ROOT))
    path = pathlib.Path(tempfile.mkdtemp()) / "dispatch_head.py"
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location("leviathan.graphrag._dispatch_head_subj", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fields(plan, names=None):
    d = {f.name: getattr(plan, f.name) for f in dataclasses.fields(plan)}
    return d if names is None else {k: d[k] for k in names}


def test_the_four_sites_move_together_and_the_section_renders_TRAILING(graph):
    """The FOUR-SITE LAW (`dispatch.py:26-31`): `_validate` constructs the Plan with explicit keywords,
    so a property that stops at the schema is SILENTLY DISCARDED on the way out of the module."""
    ids = ("El_Nino", "La_Nina", "frost")
    sys_on = dp.planner_sys(2, subject_ids=ids)
    anchor = "\n## OUTPUT DISCIPLINE\n"
    assert sys_on.count(anchor) == 1
    assert sys_on.count("## SUBJECT DETECTION") == 1
    assert sys_on[:sys_on.index(anchor)].endswith("in code, never here.\n")
    props = dp._plan_tool(list(graph.contracts), 2, subject_ids=ids)["input_schema"]["properties"]
    assert props["subject"]["items"]["enum"] == list(ids)
    assert props["subject"]["maxItems"] == dp.SUBJECT_CAP == 3
    p = dp._validate({"steps": ["reasoning"], "contracts": [], "subject": ["La_Nina", "El_Nino"]},
                     set(graph.contracts), 2, subject_ids=ids)
    assert p.subject == ("La_Nina", "El_Nino"), "the PLANNER's own order is kept"
    assert list(p.trace())[-2:] == ["subject", "subject_hints_n"]


def test_the_validator_is_STRICT_and_every_failure_collapses_to_an_empty_tuple(graph):
    ids = ("El_Nino", "La_Nina", "frost")
    base = {"steps": ["reasoning"], "contracts": []}
    C, N = set(graph.contracts), 2
    for raw in ("El_Nino", 3, None, {"a": 1}, ["not_a_driver"], [None], [""]):
        p = dp._validate(dict(base, subject=raw), C, N, subject_ids=ids)
        assert p.subject == (), raw
    # dedupe, cap, and an unknown id DROPPED rather than failing the plan
    p = dp._validate(dict(base, subject=["El_Nino", "El_Nino", "La_Nina", "frost", "nope"]),
                     C, N, subject_ids=ids)
    assert p.subject == ("El_Nino", "La_Nina", "frost")
    p = dp._validate(dict(base, subject=["El_Nino", "La_Nina", "frost", "El_Nino"]), C, N,
                     subject_ids=ids + ("drought",))
    assert len(p.subject) <= dp.SUBJECT_CAP
    # with NO vocabulary threaded the field cannot be set at all
    assert dp._validate(dict(base, subject=["El_Nino"]), C, N).subject == ()


def test_the_frozen_block_is_ASCII_carries_no_question_mark_and_is_SHA_PINNED():
    """The `_xl_block` discipline. An independent agent authors the held-out asks BLIND to this text,
    so a quoted ask here would grade the prompt against its own answer key. ANY EDIT VOIDS THE FREEZE
    AND CONSUMES THE HELD-OUT SET."""
    import hashlib
    blk = dp._subject_block(("El_Nino",))
    assert hashlib.sha256(blk.encode("utf-8")).hexdigest() == SU.SUBJECT_BLOCK_SHA256
    assert "?" in blk[:0] or "?" not in blk
    blk.encode("ascii")
    assert dp._subject_block(None) == "" and dp._subject_block(()) == "" and dp._subject_block([]) == ""
    # the block is a FIXED text: no roster substitution, so ONE sha pins it for every vocabulary
    assert dp._subject_block(("frost",)) == blk


def test_FLAG_OFF_the_prompt_the_schema_the_validator_and_the_user_message_are_HEADs(graph):
    """D1's central claim, proved the only way it can be: HEAD's module run BESIDE the tree's.
    48 (ceiling x xc_open x roster) prompt pairs, 48 schema pairs, 56 validator pairs, and the whole
    `plan_turn` call including the USER MESSAGE."""
    head = _head_dispatch()
    ids = list(graph.contracts)
    XLB = {"corn_cbot": "CBOT corn", "soybeans_cbot": "CBOT soybeans"}
    XLK = ("extreme", "windowed_extreme")
    n_sys = n_tool = 0
    for n in range(1, 7):
        for xc in (False, True):
            for xl in (None, {"corn_cbot": "CBOT corn"}, XLB, None):
                kw = {"xl_boards": xl} if xl else {}
                assert dp.planner_sys(n, xc_open=xc, **kw) == head.planner_sys(n, xc_open=xc, **kw)
                n_sys += 1
                a = dp._plan_tool(ids, n, xl, XLK if xl else None)
                b = head._plan_tool(ids, n, xl, XLK if xl else None)
                assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
                n_tool += 1
    assert n_sys >= 30 and n_tool >= 30, (n_sys, n_tool)

    HEADN = [f.name for f in dataclasses.fields(head.Plan)]
    S_, C_, W_ = "soybeans_cbot", "corn_cbot", "soft_red_winter_wheat_cbot"
    n_val = 0
    for cs in ([S_, S_], [S_, S_, S_, S_], [S_, C_, S_, W_], [], [W_, C_, S_], [S_, "nope", C_],
               [C_], [S_, C_, W_]):
        for cap in (1, 2, 4, 6):
            out = {"steps": ["numbers"], "contracts": list(cs), "subject": ["El_Nino"]}
            a, b = dp._validate(dict(out), set(ids), cap), head._validate(dict(out), set(ids), cap)
            assert _fields(a, HEADN) == _fields(b), (cs, cap)
            assert a.subject == () and a.subject_hints_n == 0
            assert a.trace() == b.trace(), "an OFF trace gains no key"
            n_val += 1
    assert n_val >= 30, n_val

    seen: dict = {}

    def cap_call(sys_block, user, **kw):
        seen["last"] = (sys_block, user, json.dumps(kw.get("tool"), sort_keys=True))
        return {"steps": ["reasoning"], "contracts": [S_]}

    got = {}
    for mod, tag in ((dp, "tree"), (head, "head")):
        mod.plan_turn("what does El Nino do to corn", graph=graph, today="2026-09-09",
                      call=cap_call, model="m")
        got[tag] = seen["last"]
    assert got["tree"] == got["head"], "the flag-off planner call is not HEAD's"
    assert "subject hints" not in got["tree"][1]


def test_FLAG_ON_the_hint_line_rides_the_USER_message_and_NEVER_the_system_block(graph):
    """D2. The system prompt is the CACHED PREFIX (`_SYS_RENDERS` memoizes an unchanged render to the
    SAME object precisely so an unmoded turn's prefix is byte-identical); per-turn text there would
    bust that prefix on EVERY turn -- a real, recurring bill for a hint."""
    seen: dict = {}

    def cap_call(sys_block, user, **kw):
        seen.update(sys=sys_block, user=user, tool=kw.get("tool"))
        return {"steps": ["reasoning"], "contracts": ["corn_cbot"], "subject": ["El_Nino"]}

    line = "subject hints: exact El Nino [El_Nino]"
    p = dp.plan_turn("what does the pacific warming do to corn", graph=graph, today="2026-09-09",
                     call=cap_call, model="m", subject_ids=("El_Nino", "La_Nina"),
                     subject_hints=line)
    assert line in seen["user"] and line not in seen["sys"]
    assert seen["user"].endswith(line), "the hint is LAST; the head of the message is unmoved"
    assert seen["user"].startswith("TODAY: 2026-09-09\n\n")
    assert "## SUBJECT DETECTION" in seen["sys"]
    assert seen["tool"]["input_schema"]["properties"]["subject"]["items"]["enum"] == \
        ["El_Nino", "La_Nina"]
    assert p.subject == ("El_Nino",) and p.subject_hints_n == 1
    # a vocabulary with NO hints still renders the section and leaves the message otherwise HEAD's
    seen.clear()
    dp.plan_turn("q", graph=graph, today="2026-09-09", call=cap_call, model="m",
                 subject_ids=("El_Nino",))
    assert "subject hints" not in seen["user"]


# ---------------------------------------------------------------------------------------------------
# THE DECK ITSELF
# ---------------------------------------------------------------------------------------------------
def test_every_expect_id_in_the_deck_EXISTS_in_the_live_graph(deck, graph):
    """D9. Unlike the planner decks, whose answer key is a PROMPT, this deck's answer key is the DRIVER
    VOCABULARY -- which changes with every curation commit. An id that left the graph is a row to
    RETIRE by hand, and this is where it surfaces."""
    alive = set(SU.live_ids(graph))
    bad = sorted({e for r in deck["rows"] for e in (r.get("expect") or []) if e not in alive})
    assert bad == [], bad


def test_the_deck_shape_meets_D9s_own_bars(deck):
    import collections
    rows = deck["rows"]
    assert deck["deterministic"] is True, "bge-m3 at fixed weights has no sampling seat"
    assert len(rows) >= 100
    counts = collections.Counter(r["klass"] for r in rows)
    for klass in ("exact", "alias", "synonym", "misspelling", "description", "multi",
                  "near_duplicate", "acronym", "decoy"):
        assert counts[klass] >= 8, (klass, counts[klass])
    assert counts["decoy"] >= 12
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r.get("frozen") is True and r.get("split") == "calibration" for r in rows)
    assert all(r.get("expect") == [] for r in rows if r["klass"] == "decoy")
    assert all(r.get("expect") for r in rows if r["klass"] != "decoy")
    header = DECK.read_text(encoding="utf-8")
    assert "vocabulary_hash: 99dc11409fe9" in header
    assert "CAND_FLOOR: %s" % SU.CAND_FLOOR in header
    assert "AMBIG_FLOOR: %s" % SU.AMBIG_FLOOR in header


def test_the_deterministic_tiers_alone_clear_their_bars_on_the_deck(deck, graph):
    """LAYER 1's T0 and T1 bars: exact 100% in `hints.exact`, alias 100% in exact+alias. Zero embeds,
    zero artifact -- this is the FAIL-OPEN floor measured on the shipped deck, and it runs in CI."""
    miss_ex, miss_al = [], []
    for r in deck["rows"]:
        want = set(SU.expand_group(r["expect"], graph)) | set(r["expect"])
        if r["klass"] == "exact":
            if not (want & set(SU.exact_ids(r["phrase"], graph))):
                miss_ex.append(r["id"])
        elif r["klass"] == "alias":
            got = set(SU.exact_ids(r["phrase"], graph)) | set(SU.alias_ids(r["phrase"], graph))
            if not (want & got):
                miss_al.append(r["id"])
    assert miss_ex == [], miss_ex
    assert miss_al == [], miss_al


def test_LAYER_1_on_the_REAL_artifact(deck, graph):
    """THE OPT-IN BRIDGE, and the OPT-IN IS AN ENVIRONMENT NAME RATHER THAN A FILE.

    It was gated on artifact PRESENCE alone, which is not an opt-in on any box that HAS the artifact
    -- the owner's tree and every serving image -- so it ran in the DEFAULT suite and loaded bge-m3
    there: MEASURED at 77.24 s of this file's 113.08 s (re-measured 2026-09-10 at 70.6 s for the model
    load and first encode alone). The house law is one opt-in slow test at most, and a gate that is
    satisfied by the thing under test is not an opt-in. It now needs `SUBJECT_RESOLVER_SLOW_TESTS=1`
    AND a current artifact; the banked figures come from the calibration harness, and this asserts the
    two a WIRING regression would break: the artifact's own shape, and that a phrase describing a
    driver reaches it semantically.

    THE NAME IS THE RESOLVER'S OWN AND NOT AN ESTATE-WIDE ONE (owner's word 2026-09-10). A
    `LEVIATHAN_SLOW_TESTS` would be a switch every future slow test in the estate inherits, so one box
    setting it to see this measurement would silently arm every other one; the opt-in is scoped to the
    thing it opts into.

    THE ENVIRONMENT READ IS THE TEST'S, NEVER THE RESOLVER'S. `check_subject_resolver` clause (1)
    greps `state/subject.py` for any read at all; a test harness switch is not a serving one."""
    import os
    if os.environ.get("SUBJECT_RESOLVER_SLOW_TESTS", "").strip().lower() not in ("1", "on", "true"):
        pytest.skip("opt-in: set SUBJECT_RESOLVER_SLOW_TESTS=1 (this test loads bge-m3, ~71 s)")
    status, stamped, live = SU.artifact_status(graph=None)
    if status != "ok":
        pytest.skip("subject vocabulary artifact is %s (stamped %r, live %r)" % (status, stamped, live))
    vocab, st = SU.load_vocab()
    assert st == "ok" and vocab["V"].shape[1] == 1024 and vocab["V"].shape[0] == len(vocab["ids"])
    assert len(set(vocab["ids"])) == 405 and vocab["V"].shape[0] == 4000
    # de02 -- a DESCRIPTION row, which is the class the semantic tier exists for and the class the
    # shipped lexical leg scored 1/10 on. NOT a synonym row: the calibration measured that the tier is
    # a PARAPHRASE matcher over the driver's own prose and not a knowledge base, so "the pacific
    # warming" does not reach `El_Nino` at all. That miss is banked in the deck header as a CURATION
    # finding; pinning it here as a pass would be pinning a number the run does not support.
    cands, st2 = SU.semantic_candidates("the insect that bores into coffee cherries", graph,
                                        vocab=vocab)
    assert st2 == "ok"
    assert "coffee_berry_borer" in {c[0] for c in cands}, cands
    assert cands[0][1] >= SU.CAND_FLOOR


# ---------------------------------------------------------------------------------------------------
# PHASE B -- THE ORCHESTRATOR THREAD (D1/D11)
#
# The seam is `orchestrator._respond`'s dispatch tier, and these decks drive it through `orch.respond`
# with `dispatch.plan_turn` and `answer.answer` REPLACED BY RECORDERS. Nothing here loads a model,
# calls an API or touches the network: what is under test is the WIRING -- which kwargs exist, which
# are ABSENT, and what the payload carries -- and the wiring is exactly what a byte-identity claim is
# made of.
# ---------------------------------------------------------------------------------------------------
FLAG = "GRAPHRAG_SUBJECT_RESOLVER"


def _seam_graph():
    """The two-contract fixture `test_orchestrator` uses. Small on purpose: `live_ids` over it is a
    two-id vocabulary, which is what makes the threaded enum readable in an assertion."""
    from leviathan.causal import schema as cs
    coffee = cs.CausalContract(contract="arabica_coffee", aliases=["arabica"],
                               drivers=[cs.Driver(id="frost", type="hazard", sign="+",
                                                  mechanism="frost kills trees")])
    corn = cs.CausalContract(contract="corn", aliases=["maize"],
                             drivers=[cs.Driver(id="drought", type="hazard", sign="+",
                                                mechanism="dryness cuts yield")])
    return G.CausalGraph({"arabica_coffee": coffee, "corn": corn}, silver=set())


def _stamped(payload, graph=None):
    """A Board carrying `payload` through the SHIPPED seam functions -- the one producer of that
    normalisation, never a re-implementation of it."""
    bd = B.Board(asof="2026-09-09", mode="deep")
    S._stamp_subject(bd, S._subject_payload(payload), graph=graph)
    return bd


def _drive_seam(monkeypatch, *, flag=None, plan_subject=(), resolve=None, classify=None,
                plan_fallback=False, query="why is coffee bullish"):
    """Run ONE turn through the dispatch seam and return `{plan_turn: kwargs, answer: kwargs}`.

    `dp.plan_turn` and `an.answer` are the two calls D1's byte-identity claim is stated over, so both
    are replaced by recorders and nothing downstream of them runs. `resolve` overrides
    `state.subject.resolve` -- the seat the exception belt is tested through."""
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import orchestrator as orch
    seen: dict = {}

    def fake_plan_turn(q, **kw):
        seen["plan_turn"] = dict(kw)
        return dp.Plan(steps=["reasoning"], contracts=["arabica_coffee"],
                       subject=tuple(plan_subject), fallback=plan_fallback)

    def fake_answer(q, **kw):
        seen["answer"] = dict(kw)
        return {"answer": "x", "structured": None, "contract": "arabica_coffee", "contracts": [],
                "evidence": [], "model": "m", "trace": {}}

    monkeypatch.setattr(dp, "plan_turn", fake_plan_turn)
    monkeypatch.setattr(an, "answer", fake_answer)
    if resolve is not None:
        monkeypatch.setattr(SU, "resolve", resolve)
    if flag is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, flag)
    kw = {"classify": classify} if classify is not None else {}
    orch.respond(query, graph=_seam_graph(), asof="2024-06-01",
                 call=lambda *a, **k: {"tldr": "x", "mechanism": "y", "diagram_mermaid": "",
                                       "sources": []},
                 retrieve=lambda q, node, *, k, asof=None, near=None: [], **kw)
    return seen


def test_pb1_FLAG_OFF_ADDS_NOTHING_TO_EITHER_CALL(monkeypatch):
    """D1's byte-identity claim, stated where it is actually made: the kwargs are ABSENT, not None.

    `None` would be a behaviour change with no flag. `dispatch.plan_turn` tests `if subject_ids:` and
    would agree -- but `an.answer(subject=None)` reaches `_answer_l2` and `fill_stage1`, and an
    INJECTED answer fake written against the pre-resolver signature raises on the unexpected keyword.
    Every planner and lane fixture in this suite rests on that property."""
    seen = _drive_seam(monkeypatch, flag=None)
    pt, ans = seen["plan_turn"], seen["answer"]
    assert "subject_ids" not in pt and "subject_hints" not in pt, sorted(pt)
    assert "subject" not in ans, sorted(ans)


@pytest.mark.parametrize("value", ["", "off", "yes", "enabled", "0", "false", "On1"])
def test_pb2_THE_FLAG_IS_FAIL_CLOSED_ON_EVERY_VALUE_BUT_THREE(monkeypatch, value):
    """The estate's exact reader spelling: only a case-insensitive on/1/true arms it. 'yes' is in this
    list because it is what a human types when they mean on, and the point of a fail-closed grammar is
    that a near-miss stays DARK rather than half-arming a lane."""
    seen = _drive_seam(monkeypatch, flag=value)
    assert "subject_ids" not in seen["plan_turn"], (value, sorted(seen["plan_turn"]))
    assert "subject" not in seen["answer"], (value, sorted(seen["answer"]))


@pytest.mark.parametrize("value", ["on", "1", "true", "TRUE", " On "])
def test_pb3_FLAG_ON_THREADS_THE_FULL_LIVE_ID_SET_AND_ONE_HINT_LINE(monkeypatch, value):
    """D2: the embedder PROPOSES and the planner DISPOSES, so the ENUM is the whole live vocabulary
    and never the hinted subset. `config_check` clause (9) grades that property from SOURCE; this
    grades it from the CALL, which is the half source-reading cannot reach."""
    seen = _drive_seam(monkeypatch, flag=value)
    pt = seen["plan_turn"]
    assert tuple(pt["subject_ids"]) == SU.live_ids(_seam_graph()) == ("drought", "frost")
    assert isinstance(pt["subject_hints"], str)


def test_pb4_THE_PLANNERS_PICK_REACHES_ANSWER_AS_THE_PAYLOAD(monkeypatch):
    """The payload shape `state.seam._subject_payload` reads: picked ids, the hint trace, the carried
    ambiguity. `picked` is the PLANNER's field and never the resolver's -- D2's whole point -- and the
    board stamps what the orchestrator built, through the shipped seam function."""
    hints = SU.SubjectHints(exact=("frost",), vocab_status="ok", ms=3.0)
    seen = _drive_seam(monkeypatch, flag="on", plan_subject=("frost",), resolve=lambda q, **kw: hints)
    sub = seen["answer"]["subject"]
    assert sub["picked"] == ["frost"]
    assert sub["hints"]["exact"] == ["frost"] and sub["hints"]["vocab_status"] == "ok"
    assert sub["ambiguous"] == []
    assert _stamped(sub).subject["picked"] == ["frost"]


def test_pb5_AMBIGUITY_IS_CARRIED_ONLY_WHEN_THE_PLANNER_PICKED_NOTHING(monkeypatch):
    """D5's own condition, held at the ORCHESTRATOR as well as at the seam. Two rows of one table: the
    same hints, once with a pick and once without."""
    hints = SU.SubjectHints(candidates=(("frost", 0.91, "id"), ("drought", 0.83, "id")),
                            vocab_status="ok", ms=4.0)
    picked = _drive_seam(monkeypatch, flag="on", plan_subject=("frost",),
                         resolve=lambda q, **kw: hints)
    assert picked["answer"]["subject"]["ambiguous"] == []
    none = _drive_seam(monkeypatch, flag="on", plan_subject=(), resolve=lambda q, **kw: hints)
    amb = none["answer"]["subject"]["ambiguous"]
    # THE IDS, NOT THE TRIPLES. `SubjectHints.ambiguous()` yields (id, score, field); handing the seam
    # the triples would stringify a tuple into the trace and into the rendered row.
    assert amb == ["frost", "drought"] and all(isinstance(x, str) for x in amb)
    assert _stamped(none["answer"]["subject"]).subject["ambiguous"] == ["frost", "drought"]


def test_pb5b_A_PLANNER_FALLBACK_MINTS_NO_AMBIGUITY_ROW(monkeypatch):
    """THE THIRD ROW OF THE SAME TABLE, and it is the one the first cut got wrong. `plan` is
    `None if p.fallback else p`, so a 429, a timeout or a malformed tool body leaves the pick empty --
    and the carry fired on it, minting a rendered "name one of these" row out of a TRANSPORT FAILURE
    rather than out of a planner that declined. D5's condition presumes a planner that answered."""
    hints = SU.SubjectHints(candidates=(("frost", 0.91, "id"), ("drought", 0.83, "id")),
                            vocab_status="ok", ms=4.0)
    seen = _drive_seam(monkeypatch, flag="on", plan_subject=(), plan_fallback=True,
                       resolve=lambda q, **kw: hints)
    sub = seen["answer"]["subject"]
    assert sub["picked"] == [] and sub["ambiguous"] == [], sub
    # THE HINTS STILL RIDE: the resolver RAN and its census must not be silently dropped just because
    # the planner never answered -- that is the difference between `subject_resolver_error` and this.
    assert sub["hints"]["vocab_status"] == "ok" and "error" not in sub["hints"], sub["hints"]
    # AND THE PLANNER WAS STILL OFFERED THE LIST: the fallback is downstream of the thread.
    assert sorted(seen["plan_turn"]["subject_ids"]) == sorted(SU.live_ids(_seam_graph()))


def test_pb6_A_RESOLVER_THAT_RAISES_LEAVES_THE_TURN_INTACT_AND_SAYS_SO(monkeypatch):
    """`resolve()` never raises by contract; this is the belt for the case where the contract is wrong
    (`state/seam.py`'s own precedent). The turn PROCEEDS, both planner kwargs stay ABSENT -- so that
    turn is byte-identical to a flag-off one -- and `subject_resolver_error` rides
    `Board.trace()["subject"]["hints"]`, an EXISTING key: no `tracekeys.py` edit, no new top-level
    key, no second trace channel."""
    def boom(q, **kw):
        raise RuntimeError("the artifact went away mid-turn")
    seen = _drive_seam(monkeypatch, flag="on", resolve=boom)
    pt, sub = seen["plan_turn"], seen["answer"]["subject"]
    assert "subject_ids" not in pt and "subject_hints" not in pt, sorted(pt)
    assert sub["hints"] == {"error": "subject_resolver_error"}
    assert sub["picked"] == [] and sub["ambiguous"] == []
    assert _stamped(sub).trace()["subject"]["hints"]["error"] == "subject_resolver_error"
    # AND IT IS NOT A `vocab_status` WORD: that field is the CLOSED set a census partitions on, and an
    # error is not an artifact state.
    assert "subject_resolver_error" not in SU.HINT_STATUS_WORDS


def test_pb7_AN_INJECTED_CLASSIFY_NEVER_REACHES_THE_SEAM(monkeypatch):
    """The legacy path takes no plan, so it proposes no subject -- and it must not thread one either.
    The flag is ON here: what keeps the resolver out is the SEAT, not the switch."""
    def never(q, **kw):
        raise AssertionError("the resolver ran on a legacy-classify turn")
    seen = _drive_seam(monkeypatch, flag="on", resolve=never,
                       classify=lambda q, call=None: {"intent": "reasoning", "needs_numbers": False,
                                                      "needs_reasoning": True})
    assert "plan_turn" not in seen
    assert "subject" not in seen["answer"], sorted(seen["answer"])


def test_pb8_THE_COUNTERS_RIDE_THE_EXISTING_BOARD_RECORD():
    """D8's four counters, from the ONE producer (`state.seam.counters`) and typed by the `Ms` prefix
    at `orchestrator.py`'s EXISTING board EMF line -- no new record, no new dimension, no tail re-pin.
    ABSENT-WHEN-INAPPLICABLE is the property under test: a turn the resolver did not run carries no
    subject key at all, so these metrics have no zero population to dilute."""
    ok = S.counters(_stamped({"picked": ["El_Nino"], "hints": {"vocab_status": "ok", "ms": 12.4}}))
    assert ok["BoardSubjectResolved"] == 1 and ok["MsBoardSubject"] == 12
    assert "BoardSubjectAmbiguous" not in ok and "BoardSubjectDeclined" not in ok
    bad = S.counters(_stamped({"picked": [], "ambiguous": ["El_Nino", "La_Nina"],
                               "hints": {"vocab_status": "stale", "ms": 0.4}}))
    assert bad["BoardSubjectAmbiguous"] == 1 and bad["BoardSubjectDeclined"] == 1
    assert "MsBoardSubject" not in bad      # a literal zero is not a measurement anyone can aggregate
    assert not [k for k in S.counters(B.Board(asof="2026-09-09", mode="deep"))
                if k.startswith("BoardSubject") or k == "MsBoardSubject"]
    # THE UNITS LINE THEY ARE EMITTED UNDER, read from the orchestrator's OWN source rather than
    # restated here: `Ms`-prefixed keys type as Milliseconds automatically, which is why the timer is
    # `MsBoardSubject` and not `SubjectMs`.
    from leviathan.graphrag import orchestrator as orch
    osrc = pathlib.Path(orch.__file__).read_text(encoding="utf-8")
    assert 'Milliseconds" if k.startswith("Ms")' in osrc


def test_pb9_THE_FLAG_IS_READ_ONCE_AND_THE_IMPORT_SITS_UNDER_IT():
    """`check_subject_resolver` clauses (11) and (12), asserted a second way so a reviewer reading
    either file finds the property. THE SCAN IS OVER THE READ AND NOT THE WORD -- five files document
    this seam by name in prose, and a substring ban would red on a comment, which is the mistake
    `check_state_seam` clause (i) records having avoided.

    THE CLAUSE ITSELF IS THE PRODUCER HERE, and that is the fix rather than a shortcut. This test used
    to COPY the clause's regex, so the two shared one blind spot instead of covering for each other:
    the copied pattern graded ONE spelling (`os.environ[.get](\"NAME\"` on one line) and five other
    ways to write a second read -- `os.getenv`, a wrapped call, a bare `environ`, an aliased module,
    a bracket subscript -- walked past both. Driving `check_subject_resolver` and then MUTATING a copy
    of the package below is what proves the property instead of restating the pattern."""
    from leviathan.graphrag import config_check as cc
    assert not [e for e in cc.check_subject_resolver() if "is read at" in e]
    pkg = pathlib.Path(dp.__file__).resolve().parent
    osrc = (pkg / "orchestrator.py").read_text(encoding="utf-8")
    assert osrc.count(FLAG + '", "")') == 1, "the one read is not where clause (11) says it is"
    imports = [ln for ln in osrc.splitlines()
               if "from leviathan.graphrag.state import subject" in ln
               and not ln.lstrip().startswith("#")]
    assert imports, "phase B's import is gone"
    for ln in imports:
        assert ln.startswith(" "), ln       # indented => inside the flag's block, never module level


@pytest.fixture(scope="module")
def _pkg_copy(tmp_path_factory):
    """ONE copy of `src/leviathan` for the whole mutation deck, plus the probe that runs the clause in
    a fresh interpreter. The tree itself is NEVER written -- every mutation lands on this copy, and it
    is restored between parameters. Module-scoped because copying 386 modules eight times is a minute
    of wall clock for a property that one copy proves."""
    import shutil
    root = tmp_path_factory.mktemp("clause11")
    src = pathlib.Path(dp.__file__).resolve().parents[1]        # src/leviathan
    shutil.copytree(src, root / "leviathan",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "probe.py").write_text(
        "import sys\nsys.path.insert(0, sys.argv[1])\n"
        "from leviathan.graphrag import config_check as cc\n"
        "print(len([e for e in cc.check_subject_resolver() if 'is read at' in e]))\n",
        encoding="utf-8")
    walk = root / "leviathan" / "graphrag" / "state" / "walk.py"
    return root, walk, walk.read_text(encoding="utf-8")


@pytest.mark.parametrize("spelling,reds", [
    ('    _x = os.environ.get("' + FLAG + '", "")\n', True),          # the plain estate idiom
    ('    _x = os.getenv("' + FLAG + '")\n', True),                   # the second-most-likely spelling
    ('    _x = os.environ.get(\n        "' + FLAG + '", "")\n', True),  # wrapped across two lines
    ('    _x = os.environ["' + FLAG + '"]\n', True),                  # the bracket subscript
    ('    _x = environ.get("' + FLAG + '", "")\n', True),             # `from os import environ`
    ('    _x = _os2.environ.get("' + FLAG + '", "")\n', True),        # an aliased module
    ('    _x = 1  # os.environ.get("' + FLAG + '")\n', False),        # a COMMENT is not a read
    ('    _x = ""\n', False),                                          # the unmutated baseline
])
def test_pb9b_CLAUSE_11_BITES_ON_A_SECOND_READ_HOWEVER_IT_IS_SPELLED(_pkg_copy, spelling, reds):
    """THE MUTATION HALF, on a COPY of `src/leviathan` -- the tree is never written.

    A "read once" lint is only worth its sentence if a second read RED it, and the first cut was
    measured against these eight bodies: the plain idiom red it and FIVE of the others left
    `check_subject_resolver() == []`. The comment row is here for the other direction: `tokenize`
    strips comments, so a trailing comment naming the read can neither hide one nor invent one."""
    import subprocess
    root, walk, base = _pkg_copy
    try:
        walk.write_text(base + "\n\ndef _probe():\n    import os  # noqa: F401\n"
                               "    from os import environ  # noqa: F401\n"
                               "    import os as _os2  # noqa: F401\n" + spelling + "    return _x\n",
                        encoding="utf-8", newline="")
        r = subprocess.run([sys.executable, str(root / "probe.py"), str(root)],
                           capture_output=True, text=True, cwd=str(root))
        assert r.returncode == 0, r.stderr[-2000:]
        assert int(r.stdout.strip().splitlines()[-1]) == (1 if reds else 0), (spelling, r.stdout)
    finally:
        walk.write_text(base, encoding="utf-8", newline="")


def test_pb10_THE_D10_BAR_IS_GRADED_AGAINST_A_BANKED_RUN():
    """Clause (13). The bank is `data/subject_resolver/<date>/latency*.json` and the figure the bar is
    stated over is the ADDED WALL PER TURN -- not the resolver's own wall, most of which is a cold
    `evidence._Q_CACHE` fill the walking lane pays one call later for the same verbatim key.

    THE THRESHOLD IS PINNED HERE, IN THE TREE, AND IT IS 150. This is the assertion the first cut did
    not have: both the clause and this test read `budget_ms` OUT OF THE BANK they were grading, so the
    bar travelled with the artifact and D10's stated number was written down nowhere. `test_pb10c`
    below measures what that cost."""
    from leviathan.graphrag import config_check as cc
    assert cc.SUBJECT_LATENCY_BUDGET_MS == 150.0                 # D10's number, pinned in the tree
    bank = cc._subject_latency_bank()
    if not bank:
        assert any("no banked subject-resolver latency run" in w
                   for w in cc.subject_resolver_warnings())
        pytest.skip("no latency bank in this checkout (the advisory covers it)")
    assert bank["added_wall_per_turn_ms"]["p90"] <= cc.SUBJECT_LATENCY_BUDGET_MS
    assert bank["bar"]["verdict"] == "PASS"
    # AND THE BANK AGREES WITH THE GRADER: the runner writes `budget_ms` FROM the constant, so a
    # disagreement is drift and clause (13) reds on it.
    assert float(bank["budget_ms"]) == cc.SUBJECT_LATENCY_BUDGET_MS
    assert not [e for e in cc.check_subject_resolver() if "D10" in e]


@pytest.mark.parametrize("p90,banked_budget,errors", [
    (19.66, 150.0, 0),        # the banked run as it stands
    (150.0, 150.0, 0),        # exactly on the budget is not over it
    (150.01, 150.0, 1),       # one hundredth of a millisecond over reds
    (999.0, 150.0, 1),        # a two-thirds-of-a-second regression reds
    (999.0, 10000.0, 2),      # THE SELF-CERTIFYING BANK: green before this fix, two errors now
    (19.66, 10000.0, 1),      # a fast run that still disagrees about the rule reds on the rule
])
def test_pb10c_THE_D10_THRESHOLD_IS_NOT_THE_ARTIFACTS_OWN(monkeypatch, p90, banked_budget, errors):
    """MEASURED, with the bank stubbed: the fifth row is the defect this closes.

    Clause (13) used to read `float(_lat.get("budget_ms") or 150.0)` -- the threshold out of the file
    it was grading -- so a bank writing its OWN `budget_ms: 10000` beside `p90: 999` produced ZERO
    errors and a silently green build. It now reds twice there: once on the figure against
    `SUBJECT_LATENCY_BUDGET_MS`, once because a bank that disagrees with the bar was measured against
    a different rule."""
    from leviathan.graphrag import config_check as cc
    monkeypatch.setattr(cc, "_subject_latency_bank",
                        lambda: {"_path": "data/subject_resolver/stub/latency_stub.json",
                                 "budget_ms": banked_budget,
                                 "added_wall_per_turn_ms": {"p50": 1.0, "p90": p90},
                                 "ms_board_subject_ms": {"p50": 1.0, "p90": 2.0}})
    got = [e for e in cc.check_subject_resolver()
           if "D10 FAILS" in e or "states its own budget_ms" in e]
    assert len(got) == errors, got


def test_pb10d_A_SECOND_DECKS_LATENCY_RUN_ADDS_A_MEASUREMENT_AND_ERASES_NONE(tmp_path, monkeypatch):
    """The bank is ONE FILE PER DECK and the WORST is graded.

    `latency.json` was written unconditionally at a fixed name, so a `--latency` pass over the
    HELD-OUT deck would have replaced the calibration bank `config_check` reads -- silently, with the
    expensive half of the evidence gone. The name now carries the deck stem and the reader globs, so
    two decks measured on one date are two measurements and the one that VIOLATES the budget is the
    one the clause grades (the population that passes is not the population)."""
    from leviathan.graphrag import config_check as cc
    root = tmp_path / "data" / "subject_resolver" / "2026-09-11"
    root.mkdir(parents=True)
    for tag, p90 in (("subject_deck_v1", 19.66), ("subject_heldout_v1", 402.4)):
        (root / f"latency_{tag}.json").write_text(json.dumps(
            {"deck": tag, "budget_ms": cc.SUBJECT_LATENCY_BUDGET_MS,
             "added_wall_per_turn_ms": {"p50": 1.0, "p90": p90},
             "ms_board_subject_ms": {"p50": 1.0, "p90": 2.0}}), encoding="utf-8")
    # THE SHIPPED SELECTION RULE, DRIVEN -- not restated. `_subject_latency_bank(root=)` is a test
    # seat on the real body, so what this grades is the rule production reads.
    bank = cc._subject_latency_bank(root=tmp_path)
    assert bank["deck"] == "subject_heldout_v1" and bank["added_wall_per_turn_ms"]["p90"] == 402.4
    assert bank["_path"].endswith("latency_subject_heldout_v1.json"), bank["_path"]
    # THE OLD FIXED NAME IS STILL READ, so a bank written before the split is not orphaned.
    (root / "latency.json").write_text(json.dumps(
        {"deck": "legacy", "budget_ms": cc.SUBJECT_LATENCY_BUDGET_MS,
         "added_wall_per_turn_ms": {"p50": 1.0, "p90": 999.0},
         "ms_board_subject_ms": {"p50": 1.0, "p90": 2.0}}), encoding="utf-8")
    assert cc._subject_latency_bank(root=tmp_path)["deck"] == "legacy"
    # AND THE CLAUSE REDS ON IT: the worst of the date's banks is the one D10 is graded on. (The
    # substitution is LAST because it retires the real reader for the rest of this test.)
    monkeypatch.setattr(cc, "_subject_latency_bank", lambda: bank)
    assert [e for e in cc.check_subject_resolver() if "D10 FAILS" in e]


def test_pb11_THE_IN_TREE_BANK_IS_PHRASE_FREE_AND_ID_FREE():
    """`test_p65`'s rule applied to phase B's own artifacts: the runner banks CLASS COUNTS in-tree and
    per-row detail only in the scratchpad. Row IDS are dropped too -- a held-out row id beside its
    class and its verdict is a map back into a deck that must stay outside the tree."""
    bank = ROOT / "data" / "subject_resolver"
    if not bank.is_dir():
        pytest.skip("no bank in this checkout")
    banned = {"phrase", "expect", "rows", "layer1_rows", "layer2_rows", "cands", "id",
              "fired_ids", "carried_ids", "failed_ids", "unscored",
              # `group_detail` is the near_duplicate/multi per-row reading the corrected scorer adds.
              # It does not end in `_ids` and it carries one entry PER ROW, each with that row's id --
              # the same map back into a held-out deck wearing a different key, so it is named here
              # as well as dropped by name in the runner's bank filter.
              "group_detail"}

    def keys(node):
        """Every KEY in the document tree. The test is structural rather than a substring ban: the
        banked prose legitimately contains the WORD 'phrases' (the baseline note says what it was
        measured over), and a substring ban would red on that while missing a row list nested three
        levels down."""
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    for f in sorted(bank.rglob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert not (banned & set(keys(doc))), (f, sorted(banned & set(keys(doc))))


def test_pb12_THE_RUNNER_REFUSES_BEFORE_IT_SPENDS(monkeypatch, tmp_path, capsys):
    """The `xc_planner_soak` contract: `--dry-run` prints the exact call plan and the estimate and
    returns 0 having spent nothing, and a layer-2 run with no key REFUSES with exit 2 rather than
    failing row by row. Loaded by FILE LOCATION because `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "subject_deck_run", ROOT / "scripts" / "graphrag" / "subject_deck_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SEAT == "claude-sonnet-4-6" and mod.TEMPERATURE == 0
    assert mod.HARD_CAP_USD == 12.0
    rc = mod.main(["--deck", str(DECK), "--layer", "both", "--draws", "3", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0 and "DRY RUN: no API call made, nothing spent." in out
    assert "312 calls" in out and "$3.12" in out and mod.SEAT in out
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert mod.main(["--deck", str(DECK), "--layer", "2", "--no-bank",
                     "--out-dir", str(tmp_path)]) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out


def _runner():
    """The runner module, loaded by FILE LOCATION -- `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location(
        "subject_deck_run", ROOT / "scripts" / "graphrag" / "subject_deck_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pb13_A_DEAD_EMBEDDER_IS_A_REFUSAL_AND_NOT_A_MEASUREMENT(monkeypatch, tmp_path, capsys):
    """THE VACUOUS-INSTRUMENT FENCE, driven on the shape that actually happened in this checkout.

    `evidence.embed` raised inside its `sentence_transformers` import chain; `semantic_candidates`
    caught it (T0/T1 are the fail-open floor, by design) and returned `unreadable` with ZERO
    candidates on every phrase -- while `load_vocab` in the same process returned `ok`, because that
    word grades THE FILE. The run scored, verdicted and BANKED itself with `artifact: ok` in its own
    header and every class at its lexical floor; at layer 2 the same state hands the planner an EMPTY
    hint line and bills a call per draw. The held-out deck is a one-shot, so that is the money AND the
    set. The fence reads the ROWS, refuses before layer 2, banks NOTHING, and writes a diagnostic
    marked NON-CERTIFYING instead.

    Layer 2 is asserted with the key PRESENT, because the point is that the refusal happens BEFORE the
    key check that pb12 covers -- a run with a key and a dead embedder is exactly the billed one."""
    mod = _runner()
    from leviathan.graphrag.state import subject as SU
    # THE DECLINE WORDS ARE DERIVED, NEVER TYPED: everything in the closed set that is not `ok` and not
    # the deliberate skip. A fifth status word is a decline by default -- fail-closed.
    assert mod.decline_words() == {"missing", "stale", "unreadable", "not_run"}
    assert "skipped" not in mod.decline_words() and SU.STATUS_SKIPPED == "skipped"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used-the-fence-fires-first")
    # THE GRAPH AND THE ARTIFACT ARE STUBBED so this deck loads no 25 MB matrix and no 2 GB model: what
    # is under test is the FENCE, and the fence reads the per-row status the tiers returned.
    monkeypatch.setattr(mod, "load_graph", lambda: _seam_graph())
    monkeypatch.setattr(SU, "load_vocab", lambda *a, **kw: ({}, "ok"))
    monkeypatch.setattr(mod, "layer1_rows", lambda rows, *, graph, vocab: [
        {"id": r["id"], "klass": r["klass"], "expect": list(r["expect"]), "exact": [], "alias": [],
         "vocab_status": "unreadable", "cands": []} for r in rows])
    rc = mod.main(["--deck", str(DECK), "--layer", "both", "--out-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 2, out[-3000:]
    assert "THE INSTRUMENT IS DEAD" in out and "instrument: DEAD" in out
    assert "NOTHING WAS BANKED" in out and "BILLED" in out
    diag = sorted(tmp_path.glob("*_REFUSED_instrument_dead.json"))
    assert len(diag) == 1, sorted(p.name for p in tmp_path.iterdir())
    doc = json.loads(diag[0].read_text(encoding="utf-8"))
    assert doc["certifying"] is False and doc["instrument"]["live"] is False
    assert doc["instrument"]["declined"] == {"unreadable": doc["instrument"]["rows_scanned"]}
    assert "layer1" not in doc and "layer2" not in doc, "a refused run scores nothing"
    # AND THE `skipped` WORD IS NOT A DECLINE: a tier the resolver chose not to run saved a turn
    # 350-550 ms on purpose, and a census that could not tell the two apart would read every fast turn
    # as a broken build.
    monkeypatch.setattr(mod, "layer1_rows", lambda rows, *, graph, vocab: [
        {"id": r["id"], "klass": r["klass"], "expect": list(r["expect"]), "exact": ["frost"],
         "alias": [], "vocab_status": "skipped", "cands": []} for r in rows])
    assert mod.instrument_census(mod.layer1_rows(
        [{"id": "x", "klass": "exact", "expect": []}], graph=None, vocab=None))["live"] is True


def test_pb14_THE_BILLED_PATH_RUNS_END_TO_END_OFFLINE(monkeypatch, capsys):
    """THE ONE-SHOT'S OWN CODE PATH, driven with a FAKE transport and no network.

    Layer 2 is the billed half and the held-out deck is spent on use, so the run seat gets ONE
    attempt: every line of `run_layer2` -> `score_layer2` -> `collect_bars` -> `markdown` has to be
    known to run before it is fired, including the two fences added after the review (the seat pin
    read back from the draws, and the running-total breaker). `dp.plan_turn` is the REAL planner here
    -- only the transport is faked -- so the kwargs, the schema and the validator are the shipped
    ones."""
    mod = _runner()
    graph = _seam_graph()
    rows = [{"id": "r1", "klass": "synonym", "phrase": "a cold snap in the growing region",
             "expect": ["frost"]},
            {"id": "d1", "klass": "decoy", "phrase": "who won the league", "expect": []}]
    l1 = {"r1": {"id": "r1", "exact": [], "alias": [], "vocab_status": "ok",
                 "cands": [["frost", 0.81, "id"]]},
          "d1": {"id": "d1", "exact": [], "alias": [], "vocab_status": "ok", "cands": []}}

    def transport(system, user, *, model, tool, **kw):
        """The planner's tool body, plus the `_usage` pop-tag `_call_opus` attaches (D-AM-4)."""
        pick = ["frost"] if "cold snap" in str(user) else []
        return {"steps": ["reasoning"], "contracts": ["arabica_coffee"], "subject": pick,
                "_usage": {"in": 1000, "out": 40, "cache_read": 0, "cache_write": 0,
                           "model": mod.SEAT}}

    meta: dict = {}
    out = mod.run_layer2(rows, graph=graph, l1_by_id=l1, draws=3, max_contracts=2,
                         today="2026-09-10", inner_call=transport, meta=meta)
    of_id, inv = mod.group_index(graph)
    sc = mod.score_layer2(out, of_id=of_id, inv=inv)
    assert sc["calls"] == 6 and sc["errored_calls"] == 0, sc
    assert sc["per_class"]["synonym"]["passed"] == 1
    assert sc["per_class"]["decoy"]["fired"] == 0 and sc["per_class"]["decoy"]["verdict"] == "PASS"
    # THE SEAT PIN IS READ BACK, not printed. `dispatch._temp_kw` forwards temperature=0 only when the
    # callee declares it, and `providers.TEMP_DEPRECATED_SEATS` drops it for the Claude 5 family -- a
    # silent 14-of-14 fallback is exactly what this bar exists to catch.
    assert sc["seat_pin"]["temperature_observed"] == ["0"], sc["seat_pin"]
    assert sc["seat_pin"]["model_observed"] == [mod.SEAT] and sc["seat_pin"]["verdict"] == "PASS"
    doc = {"generated_utc": "x", "deck": "d", "rows_total": 2, "graph_hash": "h",
           "vocab_status": "ok", "draws": 3, "max_contracts": 2, "layers_run": ["2"],
           "layer2": dict(sc, aborted_on_cost=False, running_usd=meta["spent"])}
    bars = mod.collect_bars(doc)
    doc["bars"] = bars
    doc["verdict"], stops, misses = mod.verdict_of(bars)
    doc["failing_bars"] = stops + misses
    assert any(b["bar"].startswith("L2 SEAT PIN") and b["verdict"] == "PASS" for b in bars), bars
    assert "SEAT PIN, read back from the draws" in mod.markdown(doc)
    # AND A MOVED SEAT STOPS. One draw at a different temperature is enough: the treatment is a prompt
    # section plus a schema enum, so a seat that moved would move with it and nothing is attributable.
    out[0]["draws"][0]["temperature"] = 1
    assert mod.score_layer2(out, of_id=of_id, inv=inv)["seat_pin"]["verdict"] == "STOP"


def test_pb15_THE_RUNNING_TOTAL_IS_A_BREAKER_AND_NOT_ONLY_AN_ESTIMATE(monkeypatch):
    """The $12 cap was PRE-FLIGHT only: `calls x PER_CALL_USD` against the ceiling before submit (the
    estate's own doctrine, and the right first fence) with nothing re-checking it once the run began.
    A seat that billed far above the $0.01 anchor would have run to the end of the deck. The breaker
    reads the SAME usage fields the dollar report is built from, and an aborted run's bars STOP so a
    truncated population can never be read as a completed measurement."""
    mod = _runner()
    graph = _seam_graph()
    rows = [{"id": f"r{i}", "klass": "synonym", "phrase": "a cold snap", "expect": ["frost"]}
            for i in range(6)]
    l1 = {r["id"]: {"id": r["id"], "exact": [], "alias": [], "vocab_status": "ok",
                    "cands": [["frost", 0.81, "id"]]} for r in rows}

    def spendy(system, user, *, model, tool, **kw):
        return {"steps": ["reasoning"], "contracts": ["arabica_coffee"], "subject": ["frost"],
                "_usage": {"in": 10_000_000, "out": 0, "cache_read": 0, "cache_write": 0,
                           "model": mod.SEAT}}

    meta: dict = {}
    out = mod.run_layer2(rows, graph=graph, l1_by_id=l1, draws=1, max_contracts=2,
                         today="2026-09-10", inner_call=spendy, meta=meta, cap_usd=mod.HARD_CAP_USD)
    assert meta["aborted"] is True and meta["spent"] > mod.HARD_CAP_USD
    assert len(out) < len(rows), "the breaker did not stop the run"
    of_id, inv = mod.group_index(graph)
    sc = dict(mod.score_layer2(out, of_id=of_id, inv=inv), aborted_on_cost=True,
              running_usd=meta["spent"])
    bars = mod.collect_bars({"layer2": sc, "draws": 1})
    assert any(b["bar"].startswith("L2 COST BREAKER") and b["verdict"] == "STOP" for b in bars), bars
    assert mod.verdict_of(bars)[0] == "STOP"


_ORCH = "src/leviathan/graphrag/orchestrator.py"


def _pre_resolver_rev(path: str = _ORCH, needle: str = "GRAPHRAG_SUBJECT_RESOLVER") -> str:
    """THE BASELINE THIS PIN COMPARES AGAINST, RESOLVED RATHER THAN SPELLED `HEAD`.

    The claim is flag-off byte identity against the seam AS IT WAS BEFORE THE RESOLVER, and while the
    wave was uncommitted that revision was simply `HEAD`. Phase B then landed (856869b6) and `HEAD`
    became the resolver seam itself, so the literal `HEAD` silently stopped being the baseline: the
    guard below (`the flag is not in the baseline`) is what caught it rather than the comparison
    quietly passing against a copy of the tree.

    So the baseline is DERIVED: the parent of the OLDEST commit that introduced `needle` into `path`.
    `git log -S` and `git show` are READS -- nothing here mutates a ref, touches the index or writes
    into the worktree -- and the answer moves with the history instead of ageing into a wrong one."""
    try:
        out = subprocess.check_output(
            ["git", "log", "--format=%H", "-S", needle, "--", path], cwd=str(ROOT)).decode().split()
        return (out[-1] + "^") if out else "HEAD"
    except Exception:                                   # noqa: BLE001 -- a shallow clone has no parent
        return "HEAD"


def _head_orchestrator():
    """The PRE-RESOLVER `orchestrator.py`, LOADED AS ITS OWN MODULE -- `_head_dispatch`'s idiom one
    file over. The only way to prove flag-off byte identity of a CALL is to make that copy of the seam
    make it on the same inputs. See :func:`_pre_resolver_rev` for which revision that is and why it is
    no longer spelled `HEAD`."""
    src = subprocess.check_output(["git", "show", f"{_pre_resolver_rev()}:{_ORCH}"],
                                  cwd=str(ROOT))
    path = pathlib.Path(tempfile.mkdtemp()) / "orchestrator_head.py"
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location("leviathan.graphrag._orch_head_subj", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_pb1b_FLAG_OFF_IS_BYTE_IDENTICAL_TO_HEAD_AT_BOTH_CALLS(monkeypatch):
    """THE OFF-EQUALITY, proved rather than asserted: HEAD's own `_respond_walk` runs beside the
    tree's on the same turn with the same recorders, and the two kwarg dicts are compared key for key.

    `if subject_ids:` inside `plan_turn` makes the LEAF agree whatever the seam passes, so a seam that
    passed `subject_ids=None` would look identical from inside dispatch and would still have changed
    `an.answer`'s signature contract. This compares the CALLS, which is where the claim is made.

    HEAD's copy binds the SAME `answer` module object (its `import ... as an` resolves through
    `sys.modules`), so one `monkeypatch.setattr(an, "answer", ...)` covers both copies."""
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import orchestrator as orch
    head = _head_orchestrator()
    assert "GRAPHRAG_SUBJECT_RESOLVER" not in pathlib.Path(head.__file__).read_text(encoding="utf-8")
    seen: dict = {}

    def rec(tag, ret):
        def f(q, **kw):
            seen.setdefault(tag, []).append(dict(kw))
            return ret
        return f

    plan = dp.Plan(steps=["reasoning"], contracts=["arabica_coffee"])
    ans = {"answer": "x", "structured": None, "contract": "arabica_coffee", "contracts": [],
           "evidence": [], "model": "m", "trace": {}}
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.setattr(dp, "plan_turn", rec("plan_turn", plan))
    monkeypatch.setattr(an, "answer", rec("answer", ans))
    kw = dict(graph=_seam_graph(), asof="2024-06-01",
              call=lambda *a, **k: {"tldr": "x", "mechanism": "y", "diagram_mermaid": "",
                                    "sources": []},
              retrieve=lambda q, node, *, k, asof=None, near=None: [])
    head.respond("why is coffee bullish", **kw)
    orch.respond("why is coffee bullish", **kw)
    def canon(v):
        """A CALLABLE compares by its QUALIFIED NAME, never by its repr. `route_fn` is a closure the
        seam mints per turn, so its repr carries a memory address that differs between ANY two
        invocations -- HEAD's and the tree's included. Its identity for this comparison is which
        function the seam built, which is what a byte-identity claim about the CALL is about."""
        return getattr(v, "__qualname__", None) or repr(v)

    for tag in ("plan_turn", "answer"):
        head_kw, tree_kw = seen[tag]
        assert sorted(head_kw) == sorted(tree_kw), (tag, sorted(head_kw), sorted(tree_kw))
        assert ({k: canon(v) for k, v in head_kw.items()}
                == {k: canon(v) for k, v in tree_kw.items()}), tag


# ---------------------------------------------------------------------------------------------------
# THE BLOCK'S v2, THE DECK'S v2, AND THE SCORER CORRECTION (2026-09-10)
# ---------------------------------------------------------------------------------------------------
#: The two sentences v2 adds to the frozen block, quoted here so the difference between the two freezes
#: is a PIN and not a reader's impression. The v1 sha below is the one `state/subject.py` records beside
#: the new one; reconstructing v1 by removing exactly these bytes and hashing to it is what proves v2 is
#: v1 PLUS this closure and nothing else -- no reworded bullet, no silent tightening elsewhere.
_V2_CLOSURE = (
    "- HOW A MARKET BEHAVES IS NOT A CAUSE. Its own price, spread, curve, basis, roll or front month\n"
    "  names no subject, even where the enum carries an id by that name: leave it empty.\n"
    "- READING A FIGURE IS NOT A CAUSE EITHER. How to read or compute a table, a ratio or a figure,\n"
    "  and a question about this tool itself, name no subject: leave it empty.\n")
_V1_BLOCK_SHA = "39188d42d075f73db9c76a29bed95a53e8dc2442b06bd26e61f5d261a66a2489"


def test_pb16_THE_BLOCK_v2_IS_v1_PLUS_TWO_CLOSURES_AND_NOTHING_ELSE():
    """THE ONE AMENDED FREEZE. Phase B's billed layer 2 stopped on the FATAL decoy bar with the planner
    picking `calendar_spread` on a market-structure ask (3 of 3 draws) and `ending_stocks_su_ratio` on
    a how-to-read ask (2 of 3): v1 said a market and a table are never subjects, but the enum CARRIES
    ids spelled like both, so "names no cause at all" was satisfiable by the id.

    An amended freeze is only a measurement if the amendment is BOUNDED, so all four properties are
    pinned together: the closure is PRESENT, it is at most +350 characters, removing it reproduces v1's
    sha EXACTLY, and the block still renders "" with no vocabulary -- which is what keeps every
    flag-off byte-identity pin in this file green."""
    import hashlib
    blk = dp._subject_block(("El_Nino",))
    assert _V2_CLOSURE in blk
    assert len(_V2_CLOSURE) <= 350, len(_V2_CLOSURE)
    assert blk.isascii() and "?" not in blk
    assert hashlib.sha256(blk.encode("utf-8")).hexdigest() == SU.SUBJECT_BLOCK_SHA256
    v1 = blk.replace(_V2_CLOSURE, "")
    assert len(blk) - len(v1) == len(_V2_CLOSURE) == 349
    assert hashlib.sha256(v1.encode("utf-8")).hexdigest() == _V1_BLOCK_SHA
    # THE PREDECESSOR IS RECORDED WHERE THE PIN IS, never only in a commit message: a reader who finds
    # a moved sha has to be able to see WHICH text it moved from without leaving the module.
    src = pathlib.Path(SU.__file__).read_text(encoding="utf-8")
    assert _V1_BLOCK_SHA in src and SU.SUBJECT_BLOCK_SHA256 in src
    # AND THE FLAG-OFF RENDER IS UNTOUCHED. `_subject_block` is the omit-when-off idiom's producer.
    assert dp._subject_block(None) == "" and dp._subject_block(()) == ""


def test_pb16b_THE_HINT_FLOOR_DECISION_IS_STATED_WITH_ITS_PRICE():
    """D9's discipline on a constant: a lever considered and REFUSED is banked with the arithmetic that
    refused it, so the next reader does not re-open it from memory. The floors themselves are UNMOVED
    -- that is the decision -- and `CALIBRATION_NOTE` carries the cost table both decks were priced on
    plus the reason the lever could not have reached the second decoy pick at all (an ALIAS-tier pick,
    which no candidate floor fences)."""
    assert (SU.CAND_FLOOR, SU.AMBIG_FLOOR, SU.TOP_K) == (0.52, 0.78, 5)
    note = SU.CALIBRATION_NOTE
    assert "HINT FLOOR" in note and "NOT TAKEN" in note
    for f in ("0.58", "0.60", "0.62"):
        assert f in note, f
    assert note.isascii()
    # THE MODULE STILL DECLARES NO SUCH CONSTANT. A note that says "refused" beside a constant that
    # exists is a lever half-pulled; the decision is that there is no HINT_FLOOR to read.
    assert not hasattr(SU, "HINT_FLOOR")


@pytest.fixture(scope="module")
def deck2():
    return yaml.safe_load(DECK2.read_text(encoding="utf-8"))


def test_pb17_THE_v2_DECK_IS_v1_VERBATIM_PLUS_ONE_DECOY_SUB_CLASS(deck, deck2):
    """D9: a frozen instrument is never EDITED, it is superseded by a file that carries it. v2's first
    one hundred and four rows must be v1's rows -- not equivalent, IDENTICAL, and identical as BYTES in
    the file as well as after the parse, because a reflowed row is a row someone touched. What v2 adds
    is one decoy sub-class of the two shapes the FATAL bar named, every row of it expecting nothing."""
    rows1, rows2 = deck["rows"], deck2["rows"]
    assert len(rows1) == 104 and len(rows2) >= 114
    assert rows2[:104] == rows1, "v2's carried rows are not v1's"
    text1, text2 = DECK.read_text(encoding="utf-8"), DECK2.read_text(encoding="utf-8")
    assert text1[text1.index("deterministic: true"):] in text2, "the carried rows were reflowed"
    assert text2.isascii()
    new = rows2[104:]
    assert len(new) >= 10, len(new)
    assert all(r["klass"] == "decoy" and r["expect"] == [] for r in new)
    assert all(r.get("frozen") is True and r.get("split") == "calibration" for r in new)
    assert len({r["id"] for r in rows2}) == len(rows2)
    # NO PROMPT SENTENCE REACHES A ROW. The block is graded blind by a held-out deck; a decoy phrase
    # lifted from the block's own wording would grade the prompt against its own answer key, and the
    # same reasoning runs in this direction too.
    blk = dp._subject_block(("El_Nino",)).lower()
    for r in new:
        assert r["phrase"].lower() not in blk and "?" not in r["phrase"]
    # THE HEADER PINS THE INSTRUMENT'S THREE INPUTS: the vocabulary it was scored against, the floors
    # it was scored under, and the PROMPT it grades. A deck run whose block sha is not this one is
    # measuring a different text and its decoy figures do not carry across.
    assert "vocabulary_hash: 99dc11409fe9" in text2
    assert "CAND_FLOOR: %s" % SU.CAND_FLOOR in text2
    assert "AMBIG_FLOOR: %s" % SU.AMBIG_FLOOR in text2
    assert SU.SUBJECT_BLOCK_SHA256 in text2 and _V1_BLOCK_SHA in text2
    assert "ZERO picks on ANY draw" in text2


def test_pb17b_EVERY_v2_EXPECT_ID_EXISTS_AND_THE_NEW_ROWS_NAME_NONE(deck2, graph):
    """The v1 rule applied to v2: an id that left the graph is a row to RETIRE by hand and this is
    where it surfaces. And the new sub-class is a DECOY class -- its rows assert nothing at all, so a
    curation commit can never quietly turn one of them into a scored row."""
    alive = set(SU.live_ids(graph))
    bad = sorted({e for r in deck2["rows"] for e in (r.get("expect") or []) if e not in alive})
    assert bad == [], bad
    assert all(not r["expect"] for r in deck2["rows"][104:])


def _alt_index():
    """A hand-built group index: `a1`/`a2` are two ALTERNATIVE spellings of one cause that the slice
    index happens to put in two groups -- `nd03`, `nd10` and `mu02`'s real shape, reproduced without a
    graph so the pin measures the SCORER and not the curation."""
    of_id = {"a1": "g1", "a2": "g2", "b1": "g3", "c1": "g4"}
    inv = {"g1": {"a1"}, "g2": {"a2"}, "g3": {"b1"}, "g4": {"c1"}}
    return of_id, inv


def _draws(*picks):
    return [{"subject": list(p), "temperature": 0, "usd": 0.0,
             "usage": {"model": "claude-sonnet-4-6", "in": 1, "out": 1,
                       "cache_read": 0, "cache_write": 0}} for p in picks]


def test_pb18_THE_SCORER_READS_expect_AS_ALTERNATIVES_AND_REPORTS_BOTH_READINGS():
    """THE CORRECTION, AND IT IS A SCORER DEFECT RATHER THAN A RESOLVER ONE. A row's `expect` list
    names, for each cause the ask carries, the ids that would EACH be a right answer for it. Phase B's
    scorer read it as a CONJUNCTION: `near_duplicate` demanded the pick's group set EQUAL the expected
    group set, and `multi` demanded every listed group -- so a row whose alternatives fall in two
    curated slices asked ONE pick to carry two group keys at once, and a `multi` row listing two
    spellings of one cause asked the planner to name it twice, which the frozen block forbids in as
    many words. Both readings are computed on every run so the two can never be confused."""
    mod = _runner()
    of_id, inv = _alt_index()
    rows = [{"id": "nd", "klass": "near_duplicate", "expect": ["a1", "a2"],
             "draws": _draws(["a1"], ["a1"], ["a1"])},
            {"id": "mu", "klass": "multi", "expect": ["a1", "a2", "b1"],
             "draws": _draws(["a1", "b1"], ["a1", "b1"], ["a1", "b1"])}]
    sc = mod.score_layer2(rows, of_id=of_id, inv=inv)
    nd, mu = sc["per_class"]["near_duplicate"], sc["per_class"]["multi"]
    assert (nd["passed"], nd["passed_shipped_v1"]) == (1, 0), nd
    assert (mu["passed"], mu["passed_shipped_v1"]) == (1, 0), mu
    assert sc["scoring_rule"]["reading"] == "alternatives"
    assert sc["scoring_rule"]["multi_min_concepts"] == mod.MULTI_MIN_CONCEPTS == 2
    assert sc["all_non_decoy"]["passed"] == 2 and sc["all_non_decoy"]["passed_shipped_v1"] == 0
    # THE PER-ROW READING RIDES THE SCRATCHPAD RECORD so a bar can be audited without a re-run.
    assert {d["id"]: (d["concepts"], d["expected_groups"], d["groups_reached"])
            for d in nd["group_detail"] + mu["group_detail"]} == {"nd": (1, 2, 1), "mu": (2, 3, 2)}


def test_pb18b_THE_CORRECTED_READING_IS_NOT_THE_LOOSE_ONE():
    """The equality is deliberate and it keeps both classes' teeth. `near_duplicate` is ONE subject
    under several spellings, so a planner that hedges across two of its alternative families has not
    resolved it; `multi` is two SEPARATE causes, so a planner that names one cause twice has not found
    the second. And a pick in no expected family at all still fails."""
    mod = _runner()
    of_id, inv = _alt_index()
    hedged = [{"id": "nd", "klass": "near_duplicate", "expect": ["a1", "a2"],
               "draws": _draws(["a1", "a2"], ["a1", "a2"], ["a1", "a2"])}]
    assert mod.score_layer2(hedged, of_id=of_id, inv=inv)["per_class"]["near_duplicate"]["passed"] == 0
    wrong = [{"id": "nd", "klass": "near_duplicate", "expect": ["a1", "a2"],
              "draws": _draws(["c1"], ["c1"], ["c1"])}]
    assert mod.score_layer2(wrong, of_id=of_id, inv=inv)["per_class"]["near_duplicate"]["passed"] == 0
    twice = [{"id": "mu", "klass": "multi", "expect": ["a1", "a2", "b1"],
              "draws": _draws(["a1", "a2", "b1"], ["a1", "a2", "b1"], ["a1", "a2", "b1"])}]
    assert mod.score_layer2(twice, of_id=of_id, inv=inv)["per_class"]["multi"]["passed"] == 0
    # A DECK MAY DECLARE THE PARTITION where two causes is not the shape. Neither shipped deck does,
    # and the default is the `multi` class's own contract, so the override is the stated way out.
    three = [{"id": "mu", "klass": "multi", "expect": ["a1", "a2", "b1"],
              "concepts": [["a1"], ["a2"], ["b1"]],
              "draws": _draws(["a1", "a2", "b1"], ["a1", "a2", "b1"], ["a1", "a2", "b1"])}]
    assert mod.score_layer2(three, of_id=of_id, inv=inv)["per_class"]["multi"]["passed"] == 1
    assert mod.concept_count({"klass": "near_duplicate"}) == 1
    assert mod.concept_count({"klass": "multi"}) == 2


def test_pb18c_THE_REPORT_PRINTS_BOTH_COLUMNS_AND_NAMES_THE_ONE_IT_GRADES():
    """A number whose RULE moved between two runs must never be printed as if it had not. The layer-2
    table carries both columns and one sentence saying which the verdict is taken on."""
    mod = _runner()
    of_id, inv = _alt_index()
    rows = [{"id": "nd", "klass": "near_duplicate", "expect": ["a1", "a2"],
             "draws": _draws(["a1"], ["a1"], ["a1"])}]
    sc = mod.score_layer2(rows, of_id=of_id, inv=inv)
    doc = {"generated_utc": "x", "deck": "d", "rows_total": 1, "graph_hash": "h",
           "vocab_status": "ok", "draws": 3, "max_contracts": 2, "layers_run": ["2"],
           "layer2": dict(sc, aborted_on_cost=False, running_usd=0.0)}
    doc["bars"] = mod.collect_bars(doc)
    doc["verdict"], _s, _m = mod.verdict_of(doc["bars"])
    doc["failing_bars"] = _s + _m
    md = mod.markdown(doc)
    assert "passed (alternatives)" in md and "passed (shipped v1)" in md
    assert "THE VERDICT COLUMN IS `alternatives`" in md
    assert md.isascii()


def test_pb19_THE_OFFLINE_RESCORE_READS_BANKED_DRAWS_AND_SPENDS_NOTHING(tmp_path, capsys):
    """A scorer correction is a RE-READ of one measurement and never a second run: the draws are
    banked, so re-scoring them costs nothing and consumes no one-shot. The mode reads no deck and makes
    no call, and it REFUSES a bank that carries no draws rather than reporting an empty table."""
    mod = _runner()
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"deck": "d.yaml"}), encoding="utf-8")
    assert mod.main(["--rescore", str(empty), "--out-dir", str(tmp_path)]) == 2
    assert "carries no layer2_rows" in capsys.readouterr().out
    assert mod.main(["--rescore", str(tmp_path / "nope.json"), "--out-dir", str(tmp_path)]) == 2
    assert "banked run not found" in capsys.readouterr().out
    assert mod.main([]) == 2
    assert "--deck is required" in capsys.readouterr().out
