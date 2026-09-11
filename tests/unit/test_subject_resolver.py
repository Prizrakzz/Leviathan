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

import collections
import dataclasses
import hashlib
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
DECK3 = ROOT / "configs" / "graphrag" / "subject_deck_v3.yaml"
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
    id, so the failure would be a board that anchors NOTHING with no word for why.

    THE INTERSECTION IS AGAINST ``all_ids`` AND NOT THE ENUM (phase D). The tier's job is to say what
    the phrase NAMED; the own-structure fence is applied at the three seams where an id would reach a
    planner or a reader. Intersecting here instead would delete a T0/T1 hit from the trace, which is
    how a census stops being able to count what the fence had work to do on."""
    from leviathan.graphrag import evidence as ev
    alive = set(SU.all_ids(graph))
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
    flag-off byte-identity pin in this file green.

    PHASE E (2026-09-11) MOVED THE LIVE TEXT TO v3, AND THIS PIN IS CORRECTED RATHER THAN DELETED. What
    it asserts is a fact about v2's relationship to v1, and that fact has not changed -- but the block
    `dispatch` renders is no longer v2, so removing v2's closure from the LIVE text now leaves v1 plus
    the v3 bullet and reproduces nothing. v2 is therefore RECONSTRUCTED from the live text by removing
    the v3 bullet first, and every original assertion below then runs on the text it was always about.
    The reconstruction is not assumed: it is hashed against `_V2_BLOCK_SHA` before anything is read
    from it, which is the same proof `pe1` makes from the other side."""
    import hashlib
    blk = dp._subject_block(("El_Nino",))
    assert hashlib.sha256(blk.encode("utf-8")).hexdigest() == SU.SUBJECT_BLOCK_SHA256
    v2 = blk.replace(_V3_CLOSURE, "")
    assert hashlib.sha256(v2.encode("utf-8")).hexdigest() == _V2_BLOCK_SHA, "v2 did not reconstruct"
    assert _V2_CLOSURE in v2
    assert len(_V2_CLOSURE) <= 350, len(_V2_CLOSURE)
    assert blk.isascii() and "?" not in blk
    v1 = v2.replace(_V2_CLOSURE, "")
    assert len(v2) - len(v1) == len(_V2_CLOSURE) == 349
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
    #
    # PHASE E: the sha this asserts is v2's OWN and no longer the live constant. That is the pin doing
    # exactly its job rather than failing -- v2 is a frozen instrument, it graded the v2 block, and its
    # header must go on saying so after the live text moves to v3. The live constant is asserted
    # against the live deck in `pe3`; reading it here would have made this header's claim follow
    # whatever `dispatch` renders today, which is the one thing a freeze must not do.
    assert "vocabulary_hash: 99dc11409fe9" in text2
    assert "CAND_FLOOR: %s" % SU.CAND_FLOOR in text2
    assert "AMBIG_FLOOR: %s" % SU.AMBIG_FLOOR in text2
    assert _V2_BLOCK_SHA in text2 and _V1_BLOCK_SHA in text2
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


# ---------------------------------------------------------------------------------------------------
# PHASE D -- THE OWN-STRUCTURE ENUM FENCE, THE CARRY RULE, AND THE GROUP-DEDUPED CARRY (2026-09-10)
#
# Phase C measured what the frozen block's prose could not do: with `calendar_spread` and `basis` in
# the enum the planner picked one of them on SIX decoy rows (13 of the 16 decoy draws that picked
# anything at all). The closure therefore moves from the prompt to the ENUM, and the two other seams
# those ids could still have reached a planner or a reader through -- the hint line and the ambiguity
# carry -- move with it.
# ---------------------------------------------------------------------------------------------------
def test_pd1_THE_FENCE_IS_A_CLOSED_SET_AND_live_ids_IS_all_ids_MINUS_IT(graph):
    """THE ENUM IS THE FENCE'S ONE JOB. `live_ids` is what `orchestrator.py` threads as
    `plan_turn(subject_ids=)`, which mints the tool schema's enum AND is what `_validate` re-verifies
    a reply against, so an id absent from it is refused twice over. `all_ids` keeps the whole graph,
    because the TIERS must still be able to match a fenced id or the trace stops recording that a
    phrase named one."""
    assert SU.OWN_STRUCTURE_IDS == frozenset({"calendar_spread", "basis"})
    a, live = set(SU.all_ids(graph)), set(SU.live_ids(graph))
    assert len(a) == 405 and len(live) == 403, (len(a), len(live))    # MEASURED, graph 99dc11409fe9
    assert live == a - set(SU.OWN_STRUCTURE_IDS)
    assert set(SU.OWN_STRUCTURE_IDS) <= a, "the fence names an id the graph does not declare"
    # AND THE TIER STILL SEES IT. `basis` is a driver id in its own reader form, so T0 matches the
    # word wherever a desk types it -- deck v2's dc16 is exactly that row, and its `exact` list is
    # what keeps the fence's work visible in the trace instead of silent.
    assert "basis" in SU.exact_ids("how wide is the gulf basis against the board", graph)


def test_pd2_THE_LINT_FLAGS_THE_SHAPE_AND_NOT_THE_SPELLING(graph):
    """A fence of two string literals over 36 YAMLs under active curation goes stale in silence, so
    the SHAPE is graded: an instrument-type id whose `silver_ref` measures the anchor's own curve or
    its own cash-versus-board relationship. MEASURED on graph 99dc11409fe9 -- the strong leg finds
    exactly the two ids the fence carries, over the whole graph and every type."""
    lint = SU.own_structure_candidates(graph)
    assert lint["fenced"] == ("basis", "calendar_spread")
    assert lint["unfenced"] == (), lint["unfenced"]
    assert lint["absent"] == ()
    assert lint["why"]["basis"] == "silver_ref basis_z"
    assert "kc_calendar_spread" in lint["why"]["calendar_spread"]
    # THE 23 CROSS-MARKET INSTRUMENTS ARE UNTOUCHED, and they are why the lint is a shape test and
    # not "every id typed `instrument`": each is declared as a cause of a DIFFERENT board, with a
    # sign and a lag, and "the soy-palm premium" is a subject a desk asks about.
    for i in ("soybean_crush_margin", "wheat_corn_spread", "soyoil_palm_premium", "oil_share",
              "arabica_robusta_spread", "export_parity_floor", "sugar_ethanol_parity"):
        assert i not in SU.OWN_STRUCTURE_IDS and i in set(SU.live_ids(graph)), i
    # POSITIONING STAYS SUBJECT-ELIGIBLE (D18, and the owner's own scenario: "why are many agri
    # contracts long in managed money"). `cot_mm_positioning` is typed `instrument` on some boards
    # and `positioning` on others, so it is the one id a type-shaped rule would have eaten.
    for i in ("cot_mm_positioning", "cot_positioning", "managed_money_positioning",
              "spec_positioning", "speculative_positioning"):
        assert i in set(SU.live_ids(graph)), i
        assert i not in SU.OWN_STRUCTURE_IDS, i


def test_pd2b_THE_LINT_BITES_ON_A_CURATED_ID_THAT_THE_FENCE_DOES_NOT_CARRY():
    """The property the build gate exists for, DRIVEN rather than described: a synthetic graph that
    declares a third own-structure instrument is flagged, and the same graph carrying a cross-market
    instrument is not. Neither is the shipped graph, so this pin cannot pass by accident of curation."""
    from leviathan.causal import schema as cs

    def _g(did, ref):
        c = cs.CausalContract(contract="corn", aliases=["maize"],
                              drivers=[cs.Driver(id=did, type="instrument", sign="+",
                                                 mechanism="m", silver_ref=ref)])
        return G.CausalGraph({"corn": c}, silver=set())

    assert SU.own_structure_candidates(_g("gulf_basis", "gulf_basis_z"))["unfenced"] == ("gulf_basis",)
    assert SU.own_structure_candidates(_g("front_calendar", "spread"))["unfenced"] \
        == ("front_calendar",)
    assert SU.own_structure_candidates(_g("soyoil_palm_premium", "spread"))["unfenced"] == ()
    # AND A FENCE ENTRY THE GRAPH NO LONGER DECLARES IS `absent` -- advisory and never an error: a
    # curation commit may retire an id, and a fence that outlives one fences nothing at all.
    assert set(SU.own_structure_candidates(_g("soyoil_palm_premium", "spread"))["absent"]) \
        == set(SU.OWN_STRUCTURE_IDS)


def test_pd3_THE_HINT_LINE_AND_THE_CARRY_REFUSE_A_FENCED_ID():
    """THE OTHER TWO SEAMS. The enum refuses the pick; a hint line that still NAMED the id would
    spend a slot advertising something the schema forbids and `_validate` drops, and a carry that
    named it would stop a reader to ask which of two drivers they meant when one of them is the
    board's own curve. Both are asserted by CALLING the shipped producers."""
    h = SU.SubjectHints(exact=("basis", "freight_rates"), alias=("calendar_spread",),
                        candidates=(("basis", 0.99, "id"), ("El_Nino", 0.80, "blurb")),
                        vocab_status="ok")
    line = SU.hints_line(h, vocab=None)
    assert "basis" not in line and "calendar_spread" not in line, line
    assert "freight_rates" in line and "El_Nino" in line
    assert [c[0] for c in h.ambiguous()] == ["El_Nino"]
    # A LINE THAT LOSES EVERY PART RENDERS "" -- the omit-when-empty idiom the caller already
    # honours, never a bare "subject hints:" with nothing after it.
    assert SU.hints_line(SU.SubjectHints(exact=("basis",), alias=("calendar_spread",)),
                         vocab=None) == ""
    # AND THE TIERS' OWN RECORD IS UNTOUCHED: the trace still says the phrase named one.
    assert h.trace()["exact"] == ["basis", "freight_rates"]
    assert [c[0] for c in h.candidates] == ["basis", "El_Nino"]


def test_pd4_THE_CARRY_IS_GROUP_DEDUPED_AND_dc23_IS_THE_ROW_IT_WAS_MEASURED_ON():
    """D4's hazard arriving at D5. `render.ABSENCE_WHY` promises "either of two drivers this estate
    tracks" and the seam's decline gate is `len(amb) >= 2`; both were counting SPELLINGS. MEASURED on
    deck v2's dc23 -- `crush_margin` 0.7962 and `crush_margin_expansion` 0.7803, both above
    AMBIG_FLOOR and both `ref:crush_margin_z` -- so the estate's only measured carry was a row asking
    a reader to choose between two names for one driver. The STRONGEST member of each group survives,
    because `candidates` is score-descending and the strongest is the one the words came closest to."""
    h = SU.SubjectHints(candidates=(("crush_margin", 0.7962, "id"),
                                    ("crush_margin_expansion", 0.7803, "id")),
                        groups=(("crush_margin", "ref:crush_margin_z"),
                                ("crush_margin_expansion", "ref:crush_margin_z")),
                        vocab_status="ok")
    assert [c[0] for c in h.ambiguous()] == ["crush_margin"]
    # TWO GROUPS STILL TIE, which is the state D5 was written for and the only one that renders the
    # sentence truthfully.
    two = SU.SubjectHints(candidates=(("El_Nino", 0.91, "id"), ("La_Nina", 0.83, "id")),
                          groups=(("El_Nino", "slice:enso"), ("La_Nina", "slice:la_nina")),
                          vocab_status="ok")
    assert [c[0] for c in two.ambiguous()] == ["El_Nino", "La_Nina"]
    # NO KEY IS NOT A LICENCE TO MERGE: a hand-built hints object with no group map de-duplicates by
    # ID alone, which is the honest floor.
    bare = SU.SubjectHints(candidates=(("a", 0.91, "id"), ("b", 0.83, "id")), vocab_status="ok")
    assert [c[0] for c in bare.ambiguous()] == ["a", "b"]


def test_pd4b_resolve_STAMPS_THE_GROUP_KEY_SO_THE_CARRY_NEEDS_NO_GRAPH(graph):
    """The key travels WITH the hints because the production caller has no graph: `orchestrator.py`
    calls `hints.ambiguous()` after `plan_turn`, and the D4 key is a property of the resolution and
    not of the caller. `groups()` is process-cached per graph, so the stamp costs a dict lookup."""
    rows = [("crush_margin", "id", _e(0)), ("crush_margin_expansion", "id", _e(0)),
            ("El_Nino", "blurb", _e(1))]
    h = SU.resolve("how is the crush margin computed", graph=graph, vocab=_fake_vocab(rows),
                   embed_fn=lambda xs: [_e(0)])
    assert h.groups, "resolve stamped no group keys"
    assert dict(h.groups)["crush_margin"] == "ref:crush_margin_z"
    assert dict(h.groups)["crush_margin_expansion"] == "ref:crush_margin_z"
    # (`El_Nino` is in the fake vocabulary and scores 0 against this query, so CAND_FLOOR keeps it out
    # of the candidate list entirely -- the two crush spellings are what the tier proposed.)
    assert [c[0] for c in h.candidates] == ["crush_margin", "crush_margin_expansion"]
    # AND THE STAMP IS WHAT `ambiguous()` READS -- no graph passed, and the two spellings collapse.
    stamped = SU.SubjectHints(candidates=h.candidates, groups=h.groups)
    assert [c[0] for c in stamped.ambiguous(floor=-1.0)] == ["crush_margin"]
    # A CALLER THAT HAS A GRAPH MAY PASS ONE INSTEAD, for hints built without the stamp.
    nokey = SU.SubjectHints(candidates=h.candidates)
    assert [c[0] for c in nokey.ambiguous(floor=-1.0, graph=graph)] == ["crush_margin"]
    assert len(nokey.ambiguous(floor=-1.0)) == 2, "no key must not merge"


def test_pd5_THE_CARRY_IS_DECLINED_WHEN_A_FREE_TIER_MATCHED_THE_PHRASE():
    """THE CARRY RULE (phase D). D5 carries an ambiguity when the phrase COULD MEAN two drivers and
    the planner could not choose -- and that reading only holds when the candidates came from the
    SEMANTIC tier alone. A T0 or T1 hit means the planner was shown the driver BY NAME and returned
    nothing anyway, which is a DELIBERATE DECLINE: the how-to case, where a desk types "crush margin"
    literally and asks how the figure is computed and the frozen block tells the planner to name no
    subject. Deck v2's dc23 is that row, and it was the estate's only measured carry."""
    semantic = {"picked": [], "ambiguous": ["El_Nino", "La_Nina"],
                "hints": {"exact": [], "alias": [], "vocab_status": "ok"}}
    bd = _stamped(semantic)
    assert bd.subject["ambiguous"] == ["El_Nino", "La_Nina"]
    assert [n for n in bd.notes if n.get("kind") == "subject_ambiguous"]
    assert bd.legs["board"]["reason"] == "subject_ambiguous:El_Nino|La_Nina"
    assert "ambiguous_declined" not in bd.subject
    for lex in ({"exact": ["crush_margin"], "alias": []}, {"exact": [], "alias": ["crush_margin"]}):
        declined = _stamped({"picked": [], "ambiguous": ["El_Nino", "La_Nina"],
                             "hints": dict(lex, vocab_status="ok")})
        assert "ambiguous" not in declined.subject, lex
        assert [n for n in declined.notes if n.get("kind") == "subject_ambiguous"] == [], lex
        # AND THE BOARD DOES NOT DECLINE. The anchorless decline is minted from the SAME tuple, so
        # the gate that empties it empties both -- one rule, both sides, rather than a note the
        # render suppresses beside a decline word it still stamps.
        assert declined.legs.get("board", {}).get("reason", "") == "", lex
        # NOT DELETED, NAMED: a census must be able to tell "no ambiguity" from "an ambiguity a
        # free-tier hit disqualified", and the two ids stay on the trace through `hints` either way.
        assert declined.subject["ambiguous_declined"] == "lexical_hit", lex
    # A PAYLOAD WITH NO HINTS AT ALL -- the deck's short form -- reports no lexical hit and CARRIES.
    # Absence of evidence that a free tier fired is not evidence that one did.
    assert _stamped({"picked": [], "ambiguous": ["El_Nino", "La_Nina"]}).subject["ambiguous"] \
        == ["El_Nino", "La_Nina"]


def test_pd5b_THE_COUNTER_FOLLOWS_THE_CARRY_AND_NOT_THE_CANDIDATE_LIST():
    """`BoardSubjectAmbiguous` measures WHAT A READER WAS SHOWN (its own comment in `seam.py`), so a
    carry the lexical rule declined must publish none -- otherwise the metric and the block disagree
    by construction on exactly the row the rule exists for."""
    shown = S.counters(_stamped({"picked": [], "ambiguous": ["El_Nino", "La_Nina"],
                                 "hints": {"vocab_status": "ok", "ms": 4.0}}))
    assert shown["BoardSubjectAmbiguous"] == 1
    quiet = S.counters(_stamped({"picked": [], "ambiguous": ["El_Nino", "La_Nina"],
                                 "hints": {"exact": ["crush_margin"], "vocab_status": "ok",
                                           "ms": 4.0}}))
    assert "BoardSubjectAmbiguous" not in quiet, quiet


def test_pd5c_A_FENCED_LEXICAL_HIT_DECLINES_THE_CARRY_AND_IT_IS_A_STATED_SCOPE():
    """THE ONE CASE WHERE THE RULE'S REASON AND ITS COMPUTATION COME APART, PINNED SO IT IS READ AS A
    DECISION. `_stamp_subject`'s reason for the decline is "the planner was shown the driver BY NAME
    and returned nothing" -- and a fenced id is the one thing a free tier can match that the planner
    is NEVER shown: `live_ids` drops it from the enum and `hints_line` drops it from the line. It
    declines the carry anyway, for the ROW's sake and not the planner's: a desk that typed the
    board's own curve or its own cash-versus-board asked a market-structure question, and answering
    one with "did you mean either of these two drivers?" is the decoy noise the enum fence exists to
    kill, one layer further out at the row that stops a reader.

    MEASURED across all 17 banked layer-1 runs of both in-tree decks and the held-out set: 77 rows
    carry a candidate at AMBIG_FLOOR and ZERO have a fenced-only lexical hit, so the clause moves no
    banked number and this pin is the only place the behaviour exists to be read."""
    assert {"basis", "calendar_spread"} <= set(SU.OWN_STRUCTURE_IDS)     # not a pin by accident
    for lex in ({"exact": ["basis"], "alias": []},
                {"exact": [], "alias": ["calendar_spread"]},
                {"exact": ["basis"], "alias": ["withheld_supply"]}):     # fenced beside an unfenced
        declined = _stamped({"picked": [], "ambiguous": ["El_Nino", "La_Nina"],
                             "hints": dict(lex, vocab_status="ok")})
        assert "ambiguous" not in declined.subject, lex
        assert declined.subject["ambiguous_declined"] == "lexical_hit", lex
        assert declined.legs.get("board", {}).get("reason", "") == "", lex
    # AND THE FENCED ID IS STILL ON THE TRACE. Nothing is deleted anywhere in this rule: the hint
    # dict rides `Board.trace()` untouched, so a census can count the phrases the fence had work to
    # do on -- which is the same posture `hints_line` and `ambiguous()` take one layer up.
    kept = _stamped({"picked": [], "ambiguous": ["El_Nino", "La_Nina"],
                     "hints": {"exact": ["basis"], "alias": [], "vocab_status": "ok"}})
    assert kept.subject["hints"]["exact"] == ["basis"]


def test_pd6_THE_PLANNER_CANNOT_PICK_A_FENCED_ID_EVEN_IF_IT_NAMES_ONE(graph):
    """THE FENCE IS REFUSED TWICE. The enum never offers it, and `dispatch._validate` re-verifies the
    reply against the SAME vocabulary -- so a model that names `calendar_spread` anyway has that
    MEMBER dropped and keeps the rest, which is the validator's stated member-failure behaviour and
    not a voided plan."""
    ids = SU.live_ids(graph)
    tool = dp._plan_tool(["corn_cbot"], 2, subject_ids=ids)
    enum = tool["input_schema"]["properties"]["subject"]["items"]["enum"]
    assert "calendar_spread" not in enum and "basis" not in enum
    assert "soybean_crush_margin" in enum and "cot_mm_positioning" in enum
    out = dp._validate({"steps": ["reasoning"], "contracts": ["corn_cbot"],
                        "subject": ["calendar_spread", "El_Nino", "basis"]},
                       set(graph.contracts), 2, subject_ids=ids)
    assert out.subject == ("El_Nino",), out.subject


def test_pd7_THE_FENCE_RE_SCORES_PHASE_CS_OWN_BANKED_DRAWS():
    """THE FREE RE-SCORE, BANKED. Phase C's layer 2 had SEVEN decoy rows pick a subject on at least
    one draw; SIX picked a FENCED id and one -- dc18, an open-interest-as-a-market-fact ask answered
    with two POSITIONING ids -- did not. The fence removes six rows and thirteen of the sixteen decoy
    draws that picked anything; dc18 stays, and it is a planner judgement rather than a fence
    question. Pinned from the phrase-free bank so the next billed run reports a MOVEMENT and not a
    new baseline.

    IT IS A COUNTERFACTUAL AND THE BANK SAYS SO IN A FIELD. The fence makes those picks structurally
    impossible; what a planner does with the SHORTER list on those rows is what the next run
    measures, and no re-read of banked draws can answer it."""
    bank = ROOT / "data" / "subject_resolver" / "2026-09-10" / "subject_deck_v2_fence_rescore.json"
    assert bank.is_file(), "the phase-D re-score bank is missing"
    doc = json.loads(bank.read_text(encoding="utf-8"))
    assert doc["fence"] == ["basis", "calendar_spread"]
    assert doc["counterfactual"] is True
    assert doc["decoy"]["rows_that_picked"] == 7
    assert doc["decoy"]["rows_removed_by_the_fence"] == 6
    assert doc["decoy"]["rows_remaining"] == 1
    assert doc["decoy"]["remaining_rows"] == ["dc18"]
    assert doc["decoy"]["draws_with_a_pick"] == 16
    assert doc["decoy"]["draws_removed_by_the_fence"] == 13
    assert doc["non_decoy"]["rows_losing_an_EXPECTED_id"] == 0
    assert doc["non_decoy"]["rows_losing_a_SPURIOUS_second_pick"] == 2


# ---------------------------------------------------------------------------------------------------
# PHASE E -- THE BLOCK'S v3 (THE CLOSURE AT THE ASK) AND THE DECK'S v3 (THE dc18 RE-LABEL), 2026-09-11
#
# Phase D left exactly two decoy rows firing, and the owner ruled on both. dc18 was never a decoy:
# positioning is a subject when a desk asks about it (D18, and the owner's own scenario), and the
# estate's own curation carries `open interest` as a term of the `cftc_positioning` slice -- so the row
# is re-labelled, in a NEW deck, because a frozen instrument is superseded and never edited. dc22 is a
# real miss that no enum entry can close: the fence took `calendar_spread` and the planner reached for
# `wheat_corn_spread`, an UNFENCED and legitimate cross-market subject. An enum fence removes an id,
# not an ask -- so the closure is stated at the ASK, in one bullet of the frozen block.
# ---------------------------------------------------------------------------------------------------
#: The ONE sentence v3 adds, quoted here so the third freeze is a PIN and not a reader's impression --
#: the `_V2_CLOSURE` idiom exactly. Removing these bytes and hashing to the v2 sha is what proves v3 is
#: v2 PLUS this bullet and nothing else: no reworded closure, no silent tightening elsewhere.
_V3_CLOSURE = (
    "- A SPREAD, CURVE OR BASIS WITHOUT BOTH ITS MARKETS NAMES NOTHING. A spread, a curve or a basis\n"
    "  named without both of its markets is the board's own structure and not a cause: leave it empty.\n")
_V2_BLOCK_SHA = "37900160d21a25445322b01b1420641f9e40398ce3fe6872e66fc522228843bb"
#: The five ids the owner's ruling makes dc18's answer -- `nd03`'s list, and the same shape: FIVE
#: spellings of ONE cause across TWO curated slices.
_POSITIONING = ["cot_positioning", "cot_mm_positioning", "spec_positioning",
                "speculative_positioning", "managed_money_positioning"]
_DC18_AT = 107                            # MEASURED: dc18's parsed index in both v2 and v3
#: `subject_deck_run.deck_identity(DECK3)["deck_rows_sha256"]` -- v3's 118 rows in deck order with
#: `max_contracts` 2 and `today` 2026-09-10, MEASURED 2026-09-11. Spelled here as a literal rather than
#: imported from the runner so that `pe9` grades the runner's PIN against a number this file states
#: independently: a single edit that moved both the deck and the constant would otherwise agree with
#: itself. v2's is `81c8a1f8cbc4...`, and the two decks differ by exactly one row.
_V3_ROWS_SHA = "7b079452fa9652362bcebdeba7441f298642dbfe889399d27c59cdf355ca1c86"


def test_pe1_THE_BLOCK_v3_IS_v2_PLUS_ONE_BULLET_AND_NOTHING_ELSE():
    """THE SECOND AMENDED FREEZE, graded the way the first one was. Phase D's billed layer 2 left dc22
    firing: an ask about a spread that names NEITHER of the markets it spans, answered with
    `wheat_corn_spread` on 2 of 3 draws once `calendar_spread` was fenced out of the enum. A THIRD
    fence entry is the wrong lever -- the graph carries twenty-three legitimate cross-market
    instruments and the resolver's own prose says the soy-palm premium is a subject a desk asks about
    -- so v3 states the TEST that separates them instead, at the ask.

    An amended freeze is only a measurement if the amendment is BOUNDED, so the same five properties
    are pinned together: the bullet is PRESENT and it occurs ONCE, it is at most +200 characters,
    removing it reproduces v2's sha EXACTLY, the v2 closure run is still CONTIGUOUS (which is what
    keeps `pb16` green and is why the bullet goes after that run rather than inside it), and the block
    still renders "" with no vocabulary."""
    import hashlib
    blk = dp._subject_block(("El_Nino",))
    assert _V3_CLOSURE in blk
    assert len(_V3_CLOSURE) <= 200, len(_V3_CLOSURE)
    assert blk.isascii() and "?" not in blk
    assert hashlib.sha256(blk.encode("utf-8")).hexdigest() == SU.SUBJECT_BLOCK_SHA256
    v2 = blk.replace(_V3_CLOSURE, "")
    assert len(blk) - len(v2) == len(_V3_CLOSURE) == 194     # ONE occurrence, and it is bounded
    assert hashlib.sha256(v2.encode("utf-8")).hexdigest() == _V2_BLOCK_SHA
    # THE v2 CLOSURE RUN IS UNBROKEN. `pb16` reads both v2 bullets as ONE contiguous string, so an
    # insertion BETWEEN them would pass every hash pin above and still void the earlier freeze's proof.
    assert _V2_CLOSURE in blk
    # BOTH PREDECESSORS ARE RECORDED WHERE THE PIN IS, never only in a commit message: a reader who
    # finds a moved sha must be able to see which texts it moved from without leaving the module.
    src = pathlib.Path(SU.__file__).read_text(encoding="utf-8")
    assert _V1_BLOCK_SHA in src and _V2_BLOCK_SHA in src and SU.SUBJECT_BLOCK_SHA256 in src
    # AND THE FLAG-OFF RENDER IS UNTOUCHED, which is what keeps every byte-identity pin in this file
    # green through a third freeze.
    assert dp._subject_block(None) == "" and dp._subject_block(()) == ""


@pytest.fixture(scope="module")
def deck3():
    return yaml.safe_load(DECK3.read_text(encoding="utf-8"))


def test_pe2_THE_v3_DECK_IS_THE_v2_DECK_MINUS_THE_dc18_RE_LABEL(deck2, deck3):
    """D9 AGAIN, AND THE SAME IDIOM `pb17` USES ON v2: a frozen instrument is never EDITED, it is
    SUPERSEDED by a file that carries it. v2 keeps grading phase D and is not touched; v3 carries all
    118 rows in v2's order and exactly ONE of them says something different.

    The re-label is bounded from both sides: every OTHER row is v2's row object identically, and on
    dc18 itself the id, the split, the frozen flag and -- above all -- the PHRASE are v2's bytes. A
    re-labelled row is only comparable across the two runs if the ASK did not move; what moved is the
    answer key. The only key added is `concepts`, which DECLARES the count the class rules would
    otherwise infer (see `pe5`)."""
    rows2, rows3 = deck2["rows"], deck3["rows"]
    assert len(rows3) == len(rows2) == 118
    assert [r["id"] for r in rows3] == [r["id"] for r in rows2], "a row moved position"
    assert [i for i in range(len(rows2)) if rows2[i] != rows3[i]] == [_DC18_AT]
    a, b = rows2[_DC18_AT], rows3[_DC18_AT]
    assert a["id"] == b["id"] == "dc18"
    for k in ("id", "split", "frozen", "phrase"):
        assert a[k] == b[k], k
    assert (a["klass"], b["klass"]) == ("decoy", "alias")
    assert a["expect"] == [] and b["expect"] == _POSITIONING
    assert sorted(set(b) - set(a)) == ["concepts"] and not set(a) - set(b)
    # THE BYTES, NOT ONLY THE PARSE. v1's row region is still a literal substring -- a reflowed row is
    # a row someone touched, and the carry has to survive two supersessions rather than one.
    text1, text3 = DECK.read_text(encoding="utf-8"), DECK3.read_text(encoding="utf-8")
    assert text1[text1.index("deterministic: true"):] in text3, "the carried rows were reflowed"
    assert text3.isascii()


def test_pe3_THE_v3_HEADER_PINS_THE_INSTRUMENTS_THREE_INPUTS(deck3):
    """`pb17`'s header half, on v3: the vocabulary the deck was scored against, the floors it was
    scored under, and the PROMPT it grades -- plus BOTH predecessor shas, because the figures banked
    against v1 and v2 are figures about those texts and a reader must be able to tell which run
    measured which prompt without leaving the file.

    AND NO BLOCK SENTENCE REACHES A ROW. The block is graded blind by a held-out deck; a phrase lifted
    from the block's own wording would grade the prompt against its own answer key. `pb17` ran this
    over the fourteen rows it added; here it runs over ALL 118, because the block itself gained new
    prose this time and the risk runs in that direction too.

    EACH SHA IS PINNED ON ITS OWN KEY, NOT MERELY 'PRESENT IN THE FILE'. This header carries THREE
    shas -- the live one and both predecessors -- so a bare `sha in text` assertion is satisfied by
    any of the three and would stay green through the exact failure it exists to catch: a pin that
    slid back to v2's text while the header still advertised v3's. The assertions therefore read the
    LABELLED line, which is the only place the deck says which prompt it grades."""
    text3 = DECK3.read_text(encoding="utf-8")
    assert "vocabulary_hash: 99dc11409fe9" in text3
    assert "CAND_FLOOR: %s" % SU.CAND_FLOOR in text3
    assert "AMBIG_FLOOR: %s" % SU.AMBIG_FLOOR in text3
    assert "planner_block_sha256: %s" % SU.SUBJECT_BLOCK_SHA256 in text3
    assert "v2  %s" % _V2_BLOCK_SHA in text3 and "v1  %s" % _V1_BLOCK_SHA in text3
    assert "ZERO picks on ANY draw" in text3
    blk = dp._subject_block(("El_Nino",)).lower()
    for r in deck3["rows"]:
        assert r["phrase"].lower() not in blk, r["id"]
        assert "?" not in r["phrase"], r["id"]


def test_pe4_EVERY_v3_EXPECT_ID_EXISTS_AND_THE_DECOY_ROWS_STILL_NAME_NONE(deck3, graph):
    """The v1 rule applied to v3: an id that left the graph is a row to RETIRE BY HAND and this is
    where it surfaces. `pb17b`'s second half is CARRIED FORWARD rather than deleted -- it asserted that
    every v2 row after the carried 104 expects nothing, and that is still true of v2; on v3 the same
    assertion is made with dc18 named as the ONE stated exception, so a curation commit still cannot
    quietly turn another one of them into a scored row.

    The counts are pinned because the FATAL decoy bar is a COUNT and not a rate: twenty-seven decoy
    rows, ninety-one non-decoy, eleven of them alias."""
    alive = set(SU.live_ids(graph))
    bad = sorted({e for r in deck3["rows"] for e in (r.get("expect") or []) if e not in alive})
    assert bad == [], bad
    new = deck3["rows"][104:]
    assert len(new) == 14
    silent = [r for i, r in enumerate(new, start=104) if i != _DC18_AT]
    assert len(silent) == 13
    assert all(r["klass"] == "decoy" and not r["expect"] for r in silent)
    assert all(r.get("frozen") is True and r.get("split") == "calibration" for r in new)
    by_class = collections.Counter(r["klass"] for r in deck3["rows"])
    assert by_class["decoy"] == 27
    assert sum(n for k, n in by_class.items() if k != "decoy") == 91
    assert by_class["alias"] == 11
    assert all(not r["expect"] for r in deck3["rows"] if r["klass"] == "decoy")
    assert len({r["id"] for r in deck3["rows"]}) == 118


def test_pe5_dc18_IS_ONE_CAUSE_WITH_FIVE_SPELLINGS_AND_NOT_A_near_duplicate(deck3, graph):
    """WHY THE ROW IS AN `alias` ROW CARRYING A DECLARED CONCEPT COUNT, and why "concept count 1" could
    NOT have been spelled as `klass: near_duplicate`.

    The five positioning ids sit in TWO curated slices -- `slice:cftc_positioning` holds four of them
    and `managed_money_positioning` is a slice of its own -- which is `nd03`'s exact shape. On an ID
    class the alternatives reading asks only that a pick REACH an expected id or its group, so the
    owner's ruling ("any pick reaching the positioning group passes") is what the scorer already does.
    On `near_duplicate` the rule is an EQUALITY on the count of expected groups reached, so phase D's
    own picks -- `cot_positioning` and `managed_money_positioning`, one from each slice -- reach TWO
    groups against a concept count of one and the row would score ZERO. The class is therefore chosen
    by measurement rather than by taste, and `alias` is also the deck's own definition of it: `open
    interest` IS a curated `driver_slices.yaml` term of the positioning slice, which is exactly why the
    free T1 tier fires on this phrase.

    No model and no API call: the picks below are phase D's banked ones, and nothing here spends."""
    mod = _runner()
    row = deck3["rows"][_DC18_AT]
    assert mod.concept_count(row) == 1, "the row must declare ONE cause"
    of_id = SU.groups(graph)
    inv = collections.defaultdict(set)
    for i, k in of_id.items():
        inv[k].add(i)
    assert len(mod.group_keys(_POSITIONING, of_id)) == 2, "the five ids are TWO curated slices"
    assert mod.expand(_POSITIONING, of_id, inv) >= set(_POSITIONING)
    # PHASE D's OWN PICKS, one id from each of the two slices, scored under both readings of the class.
    picks = _draws(*[["cot_positioning", "managed_money_positioning"]] * 3)
    as_alias = dict(row, draws=picks)
    as_nd = dict(row, klass="near_duplicate", draws=picks)
    as_nd.pop("concepts")
    sc_a = mod.score_layer2([as_alias], of_id=of_id, inv=inv)["per_class"]["alias"]
    sc_n = mod.score_layer2([as_nd], of_id=of_id, inv=inv)["per_class"]["near_duplicate"]
    assert (sc_a["scored"], sc_a["passed"]) == (1, 1), sc_a
    assert (sc_n["scored"], sc_n["passed"]) == (1, 0), sc_n
    # AND THE ROW STILL ENTERS THE POPULATION THE GATE READS. `L2_BARS` carries no `alias` key, so the
    # class draws no per-class verdict of its own -- `all_non_decoy` is where it counts, and that is
    # the number the held-out one-shot's gate is stated over.
    assert "alias" not in mod.L2_BARS
    assert sc_a["verdict"] == "-"
    assert mod.score_layer2([as_alias], of_id=of_id, inv=inv)["all_non_decoy"]["passed"] == 1


def test_pe6_THE_POSITIONING_GROUP_IS_NOT_EATEN_BY_ANYTHING(graph):
    """config_check clause 14(d), pinned from the DECK's side. The own-structure fence is the one
    mechanism that could make the owner's ruling unanswerable -- a fenced id is refused twice over, so
    a positioning id inside it would turn dc18 into a row no planner could pass however it is classed.
    `cot_mm_positioning` is typed as an instrument on some boards and is exactly the id a type-shaped
    fence rule would have eaten; the fence is a closed set of two literals for that reason."""
    for i in _POSITIONING:
        assert i not in SU.OWN_STRUCTURE_IDS, i
        assert i in set(SU.live_ids(graph)), i
    assert SU.OWN_STRUCTURE_IDS == frozenset({"calendar_spread", "basis"})


def test_pe7_THE_RUNS_OWN_CEILING_IS_A_FENCE_AND_NOT_ONLY_A_PRINTED_ESTIMATE(tmp_path, capsys):
    """`HARD_CAP_USD` is the SITTING's ceiling and a single run's is often tighter -- phase E's law is
    $4 for the calibration re-run and $4 for the held-out one-shot, both well inside $12. Until now
    that tighter number lived nowhere in the code: the runner printed an ESTIMATE and an operator read
    it, so the law was WATCHED rather than fenced, and a run that mis-estimated would have spent
    against $12 with nothing to stop it.

    `--cap-usd` threads one number through both fences -- the pre-flight refusal and `run_layer2`'s
    running-total breaker -- and it can only TIGHTEN: a value above the sitting's own ceiling is
    refused, because a flag that widens a stated ceiling is not a fence at all. Nothing here spends;
    every path below returns before a key is read."""
    mod = _runner()
    # THE DEFAULT IS THE SITTING'S CEILING and the dry run still reads $12.00 (`pb12`'s figures move
    # for nobody).
    assert mod.main(["--deck", str(DECK), "--layer", "both", "--draws", "3", "--dry-run"]) == 0
    assert "$12.00 hard cap" in capsys.readouterr().out
    # IT TIGHTENS, AND THE PLAN SAYS SO IN THE LINE THAT NAMES THE EXPOSURE.
    assert mod.main(["--deck", str(DECK), "--layer", "both", "--draws", "3", "--dry-run",
                     "--cap-usd", "4"]) == 0
    out = capsys.readouterr().out
    assert "$4.00 hard cap" in out and "the sitting ceiling is $12.00" in out
    # IT NEVER WIDENS.
    assert mod.main(["--deck", str(DECK), "--layer", "2", "--cap-usd", "20",
                     "--out-dir", str(tmp_path)]) == 2
    assert "never widens it" in capsys.readouterr().out
    assert mod.main(["--deck", str(DECK), "--layer", "2", "--cap-usd", "0",
                     "--out-dir", str(tmp_path)]) == 2
    assert "must be positive" in capsys.readouterr().out
    # AND IT REFUSES BEFORE IT SPENDS, on the run's own number rather than the sitting's: 312 calls at
    # the anchor is $3.12, which is inside $12 and outside $1.
    assert mod.main(["--deck", str(DECK), "--layer", "2", "--draws", "3", "--cap-usd", "1",
                     "--no-bank", "--out-dir", str(tmp_path)]) == 2
    assert "exceeds this run's $1.00 cap" in capsys.readouterr().out


def test_pe8_EVERY_SHIPPED_DECK_IS_COMMITTABLE_BY_ITS_OWN_PATH():
    """D9 REQUIRES THE CALIBRATION DECK TO BE FORCE-TRACKED, and until phase E that requirement was
    carried by a `git add -f` somebody typed once and nobody could read afterwards. `.gitignore`
    ignores `configs/graphrag/` wholesale (the private-IP fence), v1 and v2 are in the repository on
    the D9 exception, and v3 -- authored, headed, and pinned by `pe2`..`pe5` -- was NOT: the commit
    that carried phase E would have refused the path, and `pe2`..`pe5` would have ERRORED on a
    missing file in a tree whose own memory index reads 'Lost gitignored files recover VERBATIM from
    Claude Code transcripts'. A deck that four tests read is not an ephemeral config.

    So the exception is now a RULE (`configs/graphrag/*` plus one negation per shipped deck) and this
    is the pin that keeps it one. It is stated over the PATHS THE INSTRUMENT READS rather than over
    the text of `.gitignore`, so a v4 authored the same way goes red HERE -- before its commit -- and
    not in whatever run first fails to find it.

    `git check-ignore -q --no-index` is a READ: no ref moves, no index is touched, nothing is
    written. `--no-index` is load-bearing -- without it a TRACKED path is reported as un-ignored
    whatever the rules say, so v1 and v2 would pass on their tracking alone and the rule they depend
    on would go ungraded. `-q` is load-bearing too: with `-v` the exit status is 0 when ANY pattern
    matches, a negation included, and the assertion would invert."""
    for deck in (DECK, DECK2, DECK3):
        rel = deck.relative_to(ROOT).as_posix()
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel],
                           cwd=str(ROOT), capture_output=True)
        assert r.returncode == 1, (
            f"{rel} is IGNORED by a .gitignore rule -- `git add {rel}` will refuse it and the commit "
            f"will not carry the deck")
        assert deck.is_file(), rel


# ---------------------------------------------------------------------------------------------------
# THE GATE THAT DECIDES WHETHER THE ONE-SHOT IS SPENT
# ---------------------------------------------------------------------------------------------------
def _gate_doc(**over):
    """A synthetic v3-shaped run whose every pre-registered check passes. No deck is read, no call is
    made: the gate is arithmetic over the run's own fields and this is those fields -- the decoy
    class's `n`/`scored`/`fired`, the non-decoy `scored`/`passed`, the run's `errored_calls`, the seat
    pin and the cost breaker, against the deck's own `class_counts` census; and then the five that say
    WHAT RAN rather than what happened -- the block sha these draws were made under, the digest of the
    deck they were drawn on, the hash of the graph they were drawn against, the run's three-draw shape
    (118 rows x 3 = 354 calls), and the absence of a re-score marker.

    THE PROVENANCE FIELDS ARE THE LIVE ONES, deliberately. `SU.SUBJECT_BLOCK_SHA256` is read from the
    module rather than spelled, because the gate compares a run against THIS TREE and a frozen literal
    here would turn a block change into a red test in a file that is not the block's pin (`pe1` is).
    `SU.live_graph_hash()` is read the same way and for a stronger reason: the deck and the block are
    FROZEN for the certification and the graph is deliberately not -- it is meant to move between
    sittings, so the gate compares a run to the live hash and never to a pin, and a literal here would
    grade the opposite discipline. The deck digest is the one spelled case: see `_V3_ROWS_SHA`."""
    doc = {"class_counts": {"exact": 10, "alias": 11, "synonym": 14, "misspelling": 14,
                            "description": 14, "acronym": 10, "near_duplicate": 10, "multi": 8,
                            "decoy": 27},
           "planner_block_sha256": SU.SUBJECT_BLOCK_SHA256,
           "graph_hash": SU.live_graph_hash(),
           "deck": "subject_deck_v3.yaml", "deck_rows_sha256": _V3_ROWS_SHA,
           "rows_total": 118, "draws": 3,
           "layer2": {"per_class": {"decoy": {"n": 27, "scored": 27, "fired": 0}},
                      "all_non_decoy": {"scored": 91, "passed": 91},
                      "calls": 354, "errored_calls": 0,
                      "seat_pin": {"verdict": "PASS"},
                      "aborted_on_cost": False}}
    for k, v in over.items():
        if k in ("fired", "n_decoy", "dec_scored"):
            doc["layer2"]["per_class"]["decoy"][
                {"fired": "fired", "n_decoy": "n", "dec_scored": "scored"}[k]] = v
        elif k == "no_dec_scored":                       # the KEY absent, not the count at zero
            doc["layer2"]["per_class"]["decoy"].pop("scored")
        elif k in ("scored", "passed"):
            doc["layer2"]["all_non_decoy"][k] = v
        elif k == "errored":
            doc["layer2"]["errored_calls"] = v
        elif k == "no_errored_census":
            doc["layer2"].pop("errored_calls")
        elif k == "pin":
            doc["layer2"]["seat_pin"] = v
        elif k == "aborted":
            doc["layer2"]["aborted_on_cost"] = v
        elif k == "calls":
            doc["layer2"]["calls"] = v
        elif k == "drop":                                # a bank written before a field existed
            for name in ([v] if isinstance(v, str) else list(v)):
                doc.pop(name, None)
                doc["layer2"].pop(name, None)
        else:
            doc[k] = v
    return doc


def _gate_record(mod, **over):
    """THE DOCUMENT THE GATE IS ACTUALLY HANDED: the IMMUTABLE PER-RUN RECORD a layer-2 run banks,
    built from the synthetic run doc above by the runner's own producer.

    The gate stopped taking a run doc when the bank was found to transplant provenance: the dated
    `<deck>_summary.json` is a fixed path that MERGES, so a later run's `planner_block_sha256` and
    `graph_hash` could sit over an earlier run's preserved `layer2` -- the two checks this arc exists
    for, asserting on the durable artifact the opposite of what they were built to prevent. The record
    carries provenance INSIDE the layer-2 document, is written once at a path that carries the run's
    own stamp, and is the only artifact class the gate will certify. Building it here through
    `layer2_record` rather than by hand is deliberate: every direction below is then driven against
    the shape the runner actually banks."""
    return mod.layer2_record(_gate_doc(**over))


def test_pe9_THE_ONE_SHOT_GATE_IS_GRADED_IN_CODE_AND_IS_FAIL_CLOSED():
    """THE MOST LIKELY OPERATOR ERROR ON THE BILLED RUN, closed in code. The runner's exit code grades
    EVERY evaluated bar together and the calibration decks carry a FATAL layer-1 decoy carry (dc23)
    that the deck header explicitly authorises reading past, because the block is graded on the
    LAYER-2 bar -- so a v3 run whose gate passes in full still exits 1. An operator reading the exit
    code reads a STOP and holds a gate that opened; an operator reading the console prose reads
    whichever line he reaches first. `oneshot_gate` reads the layer-2 fields the gate is
    pre-registered over, and this is the pin on that reading.

    IT IS FAIL-CLOSED IN EVERY DIRECTION, and every direction is driven here: a decoy that fired, a
    decoy population that was never asked, a draw that errored anywhere on the run, a population one
    row short of the deck's own census, one row that scored and did not pass, a seat pin that moved,
    a run the cost breaker truncated, and -- the case no bar would have caught -- a layer 2 that never
    ran at all, which yields NO gate rather than an open one.

    AND THE FIVE THAT GRADE WHAT RAN. The outcome checks certify that SOMETHING was measured
    cleanly, never that THIS was, and five clean-looking runs proved it: one whose draws were made
    under the block's v2 text (the deck header says in as many words that such a run's decoy figures do
    not carry across, and nothing read the sha), one shaped like deck v2 (28 decoys, 90 non-decoy --
    internally consistent, and the denominators came from the doc's own census so it opened), one made
    against a GRAPH this tree no longer loads (the block is substitution-free, so its sha names the
    prompt and carries none of the enum; what the planner may pick is `live_ids` of the graph minus
    the own-structure fence, and `graph_hash` is the field that names the graph half), one at
    `--draws 1`, which has no ">= 2 of 3" reading in it at all, and one that is a `--rescore` -- a
    re-read of banked picks under today's scorer and not the run it would certify. Each is driven
    below, from both sides: the WRONG value and the ABSENT key, because a bank written before the
    field existed must hold the one-shot rather than skip the check.

    AND TWO MORE, ADDED 2026-09-11 WHEN THE BANK ITSELF WAS FOUND WANTING. THE ARTIFACT CLASS: the
    gate is handed a per-run RECORD and refuses a merged summary, a run doc or an unreadable path by
    name, because the summary is a fixed path that merges and its top-level provenance names the
    LATEST run on the deck rather than the layer 2 beneath it. THE CENSUS: the denominators are read
    from the certifying DECK FILE, because `class_counts` carried by the document made "all 91 rows
    were SCORED" a statement the document could satisfy by agreeing with itself -- a forged 28/90
    census beside the TRUE v3 rows digest passed three checks with figures deck v3 does not contain.
    Every count is also read as a COUNT: a present-but-null field is an absence, never a zero."""
    mod = _runner()
    g = mod.oneshot_gate(_gate_record(mod))
    assert g["verdict"] == "OPEN" and g["failing"] == []
    assert [c["pass"] for c in g["checks"]] == [True] * 14
    # THE GRAPH IS COMPARED LIVE AND NOT TO A PIN, which is the one place this gate deliberately
    # differs from the deck and the block. The helper must agree with the module's own producer, and
    # it must read as an ABSENCE rather than as "" when the graph cannot be read at all.
    assert mod.live_graph_hash_or_none() == SU.live_graph_hash() and mod.live_graph_hash_or_none()
    # THE PIN IS THE LIVE DECK'S, IN BOTH DIRECTIONS. The runner's constant is what the gate compares a
    # run against, so it is graded here against the file itself and against the deck it must NOT
    # accept: v2 and v3 differ by one row, which is the collision a filename check would have missed.
    assert mod.CERTIFYING_DECK_ROWS_SHA256 == _V3_ROWS_SHA
    assert mod.deck_identity(DECK3, mod.load_deck(DECK3))["deck_rows_sha256"] == _V3_ROWS_SHA
    assert mod.deck_identity(DECK2, mod.load_deck(DECK2))["deck_rows_sha256"] != _V3_ROWS_SHA
    assert mod.deck_identity(DECK, mod.load_deck(DECK))["deck_rows_sha256"] != _V3_ROWS_SHA
    # AND THE FILE DIGEST IS A DIFFERENT NUMBER FROM THE ROWS DIGEST -- the header is comments, so a
    # deck written up after the run it certifies moves one and not the other. That is why the gate is
    # stated over the rows.
    _ident = mod.deck_identity(DECK3, mod.load_deck(DECK3))
    assert _ident["deck_sha256"] != _ident["deck_rows_sha256"]
    assert _ident["deck"] == "subject_deck_v3.yaml" == mod.CERTIFYING_DECK
    # A GATE THAT WAS NEVER MEASURED IS NEVER REPORTED AS OPEN. Silence is the answer to a document
    # that is not an artifact this gate has anything to say about -- no layer 2, no run index, no
    # record kind.
    assert mod.oneshot_gate({"class_counts": {"decoy": 27}}) is None
    # BUT A PER-RUN RECORD IS ANSWERED IN THE SAME WORDS THROUGH EITHER DOOR. A record carrying
    # `kind: subject_resolver_layer2_run_v1` with an EMPTY `layer2` used to read HELD from a path and
    # None from a dict -- one document, two readings -- and a caller taking None for "nothing to
    # grade" would have missed "this RECORD recorded no measurement". It is HELD, on the measurement
    # checks, and its artifact CLASS is not among the failures: the class is right, the content is not.
    _empty = mod.oneshot_gate(mod.layer2_record({"deck": "subject_deck_v3.yaml"}))
    assert _empty is not None and _empty["verdict"] == "HELD"
    assert not any(c.startswith("THE ARTIFACT CLASS") for c in _empty["failing"]), _empty["failing"]
    assert any(c.startswith("DECOYS") for c in _empty["failing"]), _empty["failing"]
    # ── THE ARTIFACT CLASS. The gate certifies ONE document class and every other one is REFUSED by
    #    name rather than graded on its contents: the merged summary (whose top-level provenance names
    #    the LATEST run on the deck and date and not the layer 2 beneath it), a bare run doc, and a
    #    path that cannot be read at all. Each is HELD, and the artifact-class check is among the
    #    failing ones.
    for _wrong, _why in (
            ({"kind": mod.SUMMARY_KIND, "layer2_runs": [],
              "layer2": (_gate_doc()["layer2"])}, "a merged summary with a preserved layer 2"),
            ({"layer2_runs": [{"file": "x.json"}]}, "a summary written with no `kind`"),
            (_gate_doc(), "a run doc is not the record the run banks"),
            ("no_such_record_20260911T000000Z.json", "a path that cannot be read")):
        _g = mod.oneshot_gate(_wrong)
        assert _g is not None and _g["verdict"] == "HELD", _why
        assert any(c.startswith("THE ARTIFACT CLASS") for c in _g["failing"]), (_why, _g["failing"])
    for over, why in (({"fired": 1}, "one decoy fired"),
                      ({"scored": 90}, "a row went unscored"),
                      ({"passed": 90}, "a scored row failed"),
                      ({"pin": {"verdict": "STOP"}}, "the seat moved"),
                      ({"pin": {}}, "no seat pin was recorded"),
                      ({"aborted": True}, "the cost breaker truncated the run"),
                      ({"n_decoy": 26}, "the deck's decoy class was not scored whole"),
                      # THE FAIL-OPEN THE FIRST CUT SHIPPED WITH, driven from both sides: a decoy
                      # class that fired zero times because it was never asked, and a run that
                      # errored a single draw on a row whose other two landed -- invisible to every
                      # per-population count and still a two-draw row read as a three-draw one.
                      ({"dec_scored": 0, "errored": 81}, "every decoy draw errored"),
                      ({"dec_scored": 26}, "one decoy row had every draw error"),
                      ({"errored": 1}, "one draw errored anywhere on the run"),
                      ({"no_errored_census": True}, "the run recorded no errored-call census"),
                      ({"no_dec_scored": True}, "the decoy class recorded no scored census"),
                      # THE PROMPT. The v2 sha is the exact shape the verifier drove: an otherwise
                      # clean layer 2 whose draws were made under a different text.
                      ({"planner_block_sha256": _V2_BLOCK_SHA}, "the draws were made under block v2"),
                      ({"planner_block_sha256": _V1_BLOCK_SHA}, "the draws were made under block v1"),
                      ({"drop": "planner_block_sha256"}, "the run recorded no block sha"),
                      # THE DECK. A v2-shaped census with v2's digest, and the same census with the
                      # digest simply absent -- the bank shape that predates the field.
                      ({"deck_rows_sha256": "81c8a1f8cbc412d643ca5f111decd000"
                                            "5944b0f9e324945272c8c3269f78cc92",
                        "deck": "subject_deck_v2.yaml",
                        "class_counts": {"exact": 10, "alias": 10, "synonym": 14, "misspelling": 14,
                                         "description": 14, "acronym": 10, "near_duplicate": 10,
                                         "multi": 8, "decoy": 28},
                        "n_decoy": 28, "dec_scored": 28, "scored": 90, "passed": 90},
                       "a clean run on deck v2 is not a run on deck v3"),
                      ({"drop": "deck_rows_sha256"}, "the run recorded no deck identity"),
                      # THE GRAPH. The exact doc the verifier drove: a stale hash beside a stale
                      # `vocab_status` and a four-month-old stamp, every outcome clean. The enum the
                      # planner picks from is the GRAPH's and the block sha cannot stand in for it.
                      ({"graph_hash": "deadbeefdeadbeef", "vocab_status": "stale",
                        "generated_utc": "20260511T000000Z"},
                       "the draws were made against a graph this tree does not load"),
                      ({"drop": "graph_hash"}, "the run recorded no graph hash"),
                      # THE MEASUREMENT. A re-score is a re-read of banked picks under today's
                      # scorer; both the structural field and the label decoration hold the gate, so
                      # a doc written before the field existed is recognised by the decoration alone.
                      ({"rescored_from": "subject_v3_20260911T000000Z.json"},
                       "a re-score is not the run it would certify"),
                      ({"deck": "subject_deck_v3.yaml (RE-SCORED from a_bank.json)"},
                       "a re-score is recognised by its label when the field is absent"),
                      # THE DECOY DENOMINATOR IS POSITIVE. At zero the FATAL bar reads
                      # "0 of 0 fired ... and all 0 SCORED -- PASS" and the gate opens on a deck with
                      # no decoys in it: the one asymmetry left beside checks 2 and 3, both of which
                      # have carried their positivity guard from the start.
                      ({"class_counts": {"decoy": 0, "synonym": 118}, "n_decoy": 0, "dec_scored": 0,
                        "scored": 118, "passed": 118},
                       "a deck with no decoys does not satisfy the FATAL decoy bar"),
                      # THE SHAPE. One draw per row has no 2-of-3 reading in it, and a call census
                      # short of rows x draws is a population that was never fully asked.
                      ({"draws": 1, "calls": 118}, "a one-draw run has no >= 2 of 3 bar"),
                      ({"calls": 353}, "one row x draw was never called"),
                      ({"drop": "draws"}, "the run recorded no draw count"),
                      ({"drop": "rows_total"}, "the run recorded no row count"),
                      ({"drop": "calls"}, "the run recorded no call census"),
                      # THE CENSUS, WHICH IS THE DECK FILE'S AND NOT THE RECORD'S. A forged census
                      # beside the TRUE v3 rows digest is the shape that passed three checks with
                      # figures deck v3 does not contain -- v2's 28/90 wearing v3's identity.
                      ({"class_counts": {"exact": 10, "alias": 10, "synonym": 14,
                                         "misspelling": 14, "description": 14, "acronym": 10,
                                         "near_duplicate": 10, "multi": 8, "decoy": 28},
                        "n_decoy": 28, "dec_scored": 28, "scored": 90, "passed": 90},
                       "a v2-shaped census forged beside a TRUE v3 deck digest"),
                      ({"class_counts": {"exact": 10, "alias": 11, "synonym": 14,
                                         "misspelling": 14, "description": 14, "acronym": 10,
                                         "near_duplicate": 10, "multi": 8, "decoy": 27},
                        "rows_total": 117},
                       "a census that does not sum to the record's own row count"),
                      ({"drop": "class_counts"}, "the record carries no class census"),
                      # A PRESENT-BUT-NULL COUNT IS AN ABSENCE AND NOT A ZERO. `int(x or 0)` read
                      # `null` as a clean census, which is the one reading a gate may never take.
                      ({"errored": None}, "a null errored_calls is not zero errors"),
                      ({"fired": None}, "a null decoy fire census is not zero fires"),
                      ({"scored": None}, "a null non-decoy scored census is not a scored population"),
                      ({"dec_scored": None}, "a null decoy scored census is not a scored class")):
        g = mod.oneshot_gate(_gate_record(mod, **over))
        assert g["verdict"] == "HELD", why
        assert len(g["failing"]) >= 1, why
    # THE DENOMINATORS ARE THE CERTIFYING DECK FILE'S AND NOT THE RECORD'S: a record whose census is
    # not the deck's fails on THE CENSUS however internally consistent it is.
    assert mod.oneshot_gate(
        _gate_record(mod, class_counts={"exact": 95, "decoy": 27}))["verdict"] == "HELD"
    _census = mod.certifying_census()
    assert _census["class_counts"]["decoy"] == 27 and _census["rows_total"] == 118
    assert sum(_census["class_counts"].values()) == 118
    assert _census["deck_rows_sha256"] == _V3_ROWS_SHA
    # AND THE v2 RUN FAILS ON ITS IDENTITY -- the point of the check. It now fails on FOUR checks
    # rather than one, and that is the tightening rather than a blunting: with the denominators taken
    # from the deck FILE, a record naming another deck has no denominators at all, so the two SCORED
    # checks and the census go with the identity instead of passing beside it.
    _v2 = mod.oneshot_gate(_gate_record(
        mod,
        deck_rows_sha256="81c8a1f8cbc412d643ca5f111decd0005944b0f9e324945272c8c3269f78cc92",
        deck="subject_deck_v2.yaml",
        class_counts={"exact": 10, "alias": 10, "synonym": 14, "misspelling": 14,
                      "description": 14, "acronym": 10, "near_duplicate": 10, "multi": 8,
                      "decoy": 28},
        n_decoy=28, dec_scored=28, scored=90, passed=90))
    assert _v2["verdict"] == "HELD"
    assert any(c.startswith("THE DECK") for c in _v2["failing"]), _v2["failing"]
    assert any(c.startswith("THE CENSUS") for c in _v2["failing"]), _v2["failing"]
    # AND EACH OF THESE DIRECTIONS FAILS ON ITS OWN CHECK AND ON NO OTHER -- which is what makes each
    # of them a measurement of the thing it names rather than a doc that happens to be wrong in
    # several places at once. The stale-graph doc is the verifier's own: every outcome check passes on
    # it, and the graph hash is the only one that does not.
    _stale = mod.oneshot_gate(_gate_record(mod, graph_hash="deadbeefdeadbeef", vocab_status="stale",
                                           generated_utc="20260511T000000Z"))
    assert _stale["failing"] == [c["check"] for c in _stale["checks"]
                                 if c["check"].startswith("THE GRAPH")]
    _resc = mod.oneshot_gate(_gate_record(mod, rescored_from="subject_v3_20260911T000000Z.json"))
    assert _resc["failing"] == [c["check"] for c in _resc["checks"]
                                if c["check"].startswith("THE MEASUREMENT")]
    # THE PROMPT, ALONE. The block sha reaches no other check -- the prompt is substitution-free, so
    # it names the text and carries none of the enum -- and a run under block v2 with every outcome
    # clean is exactly the document the verifier drove.
    _v2blk = mod.oneshot_gate(_gate_record(mod, planner_block_sha256=_V2_BLOCK_SHA))
    assert _v2blk["failing"] == [c["check"] for c in _v2blk["checks"]
                                 if c["check"].startswith("PROVENANCE")]
    # AND THE SHAPE, ALONE. A one-draw run's counts are all internally consistent -- 118 rows, 118
    # calls, every row scored and passed -- and there is no ">= 2 of 3" reading anywhere in it.
    _one = mod.oneshot_gate(_gate_record(mod, draws=1, calls=118))
    assert _one["failing"] == [c["check"] for c in _one["checks"]
                               if c["check"].startswith("THE SHAPE")]
    # THE DECOY DENOMINATOR IS POSITIVE, and with the census now taken from the deck file a record
    # claiming a decoy-free deck fails on BOTH the census it forged and the bar that census was
    # forged to satisfy vacuously.
    _nodec = mod.oneshot_gate(_gate_record(mod, class_counts={"decoy": 0, "synonym": 118},
                                           n_decoy=0, dec_scored=0, scored=118, passed=118))
    assert _nodec["verdict"] == "HELD"
    assert any(c.startswith("DECOYS") for c in _nodec["failing"]), _nodec["failing"]
    assert any(c.startswith("THE CENSUS") for c in _nodec["failing"]), _nodec["failing"]


def test_pe9c_AN_ALL_ERRORED_DECOY_CLASS_IS_NOT_A_CLEAN_DECOY_BAR(capsys):
    """THE FAIL-OPEN CLOSED END TO END -- the scorer, the bar, the console and the gate, on ONE
    synthetic run in which every decoy draw errored.

    `fired` is computed over the NON-ERRORED draws, so before this the decoy class read
    `{n: 27, fired: 0, verdict PASS}` on a run that had asked nothing: the FATAL bar printed PASS,
    the console printed `picks=-` for an errored draw exactly as it prints for a decoy the planner
    correctly declined, and the pre-registered gate -- whose non-decoy side has always required
    `scored == n` -- OPENED. Eighty-one billed errors and no measurement at all would have spent the
    one-shot. Four things are driven here because all four were silent: the scorer's `scored` /
    `unscored` split, the class verdict, the bar's own detail line, and the gate."""
    mod = _runner()
    graph = _seam_graph()
    of_id, inv = mod.group_index(graph)
    rows = [{"id": f"d{i}", "klass": "decoy", "expect": [],
             "draws": [{"errored": "planner_fallback (no raise)", "usd": 0.01,
                        "temperature": 0, "usage": {"model": mod.SEAT}} for _ in range(3)]}
            for i in range(27)]
    sc = mod.score_layer2(rows, of_id=of_id, inv=inv)
    dec = sc["per_class"]["decoy"]
    # THE SCORER. Zero fired -- and zero SCORED, which is the half that was missing.
    assert dec["n"] == 27 and dec["fired"] == 0
    assert dec["scored"] == 0 and len(dec["unscored"]) == 27
    assert dec["verdict"] == "FATAL", "an unasked decoy population is not a passed FATAL bar"
    assert sc["calls"] == 81 and sc["errored_calls"] == 81
    # THE BAR. It STOPs, and its detail says WHY rather than printing a clean-looking '0 of 27'.
    bar = [b for b in mod.collect_bars({"layer2": sc, "draws": 3})
           if b["bar"].startswith("L2 DECOY")][0]
    assert bar["verdict"] == "STOP" and "0 of 27 rows were SCORED" in bar["detail"]
    # AND THE THIRD READING OF THE SAME FIELD: ABSENT, which is neither 27 nor 0. A bank written before
    # `scored` existed rendered the bare "0 of 27 decoy rows picked a subject" line -- the exact
    # sentence a PERFECT decoy bar prints -- with nothing saying the denominator was never recorded.
    # Silence and a clean bar are opposite claims and they rendered identically.
    _old = {"per_class": {"decoy": {"n": 27, "fired": 0, "verdict": "PASS", "fired_ids": []}}}
    _bar_old = [b for b in mod.collect_bars({"layer2": _old, "draws": 3})
                if b["bar"].startswith("L2 DECOY")][0]
    assert "UNKNOWN denominator" in _bar_old["detail"], _bar_old["detail"]
    assert "rows were SCORED" not in _bar_old["detail"]
    # THE GATE. Both new checks fail, and the one-shot is NOT spent.
    doc = {"class_counts": {"exact": 91, "decoy": 27},
           "layer2": dict(sc, all_non_decoy={"scored": 91, "passed": 91},
                          seat_pin={"verdict": "PASS"}, aborted_on_cost=False)}
    g = mod.oneshot_gate(mod.layer2_record(doc))
    assert g["verdict"] == "HELD"
    assert any("SCORED" in c and "DECOYS" in c for c in g["failing"]), g["failing"]
    assert any(c.startswith("EVERY DRAW WAS SCORED") for c in g["failing"]), g["failing"]
    # AND THE PROVENANCE CHECKS FAIL ON THE SAME DOC, because a synthetic run records no block sha,
    # no deck digest, no graph hash and no draw census -- the shape of every bank written before those
    # fields existed. Absent is not a pass: the gate holds on all four as well.
    assert any(c.startswith("PROVENANCE") for c in g["failing"]), g["failing"]
    assert any(c.startswith("THE DECK") for c in g["failing"]), g["failing"]
    assert any(c.startswith("THE GRAPH") for c in g["failing"]), g["failing"]
    assert any(c.startswith("THE SHAPE") for c in g["failing"]), g["failing"]
    # AND THE CENSUS, which on this doc is a census of nothing the certifying deck contains.
    assert any(c.startswith("THE CENSUS") for c in g["failing"]), g["failing"]
    mod.print_gate(g)
    out = capsys.readouterr().out
    assert out.isascii() and "GATE: HELD" in out and "0 of 27 scored" in out
    assert "81 of 81 calls errored" in out
    # AND THE CONSOLE, WHICH IS WHAT AN OPERATOR ACTUALLY WATCHES WHILE THE MONEY IS BEING SPENT. An
    # errored draw and a decoy the planner correctly declined both rendered `-`, so twenty-seven
    # broken rows scrolled past looking exactly like twenty-seven clean ones. The transport RAISES
    # here -- `_usage_call` records it and `plan_turn` maps it to a fallback -- which is the shape a
    # real outage takes, and the row must print ERR.
    def boom(system, user, *, model, tool, **kw):
        raise RuntimeError("the seat refused")

    rows2 = [{"id": "d1", "klass": "decoy", "phrase": "who won the league", "expect": []}]
    l1 = {"d1": {"id": "d1", "exact": [], "alias": [], "vocab_status": "ok", "cands": []}}
    out2 = mod.run_layer2(rows2, graph=graph, l1_by_id=l1, draws=3, max_contracts=2,
                          today="2026-09-11", inner_call=boom, meta={})
    console = capsys.readouterr().out
    assert console.isascii() and "picks=ERR,ERR,ERR" in console, console
    assert "picks=-" not in console, console
    assert all(d.get("errored") for d in out2[0]["draws"])


def test_pe9b_THE_GATE_READOUT_IS_ASCII_AND_SAYS_WHICH_WAY_IT_WENT(capsys):
    """THE ONE HALF OF THE RUNNER A FREE RUN NEVER REACHES. The gate exists only when layer 2 ran, so
    the readout the PAID seat reads is the one line of this script that would otherwise ship having
    never been executed -- which is why it is a function rather than four statements inside `main`.

    Both directions are printed here, and the ASCII assertion is the owner's console law (this box's
    stdout is cp1252 and a box-drawing character in a report is a crash, not a cosmetic)."""
    mod = _runner()
    mod.print_gate(mod.oneshot_gate(_gate_record(mod, generated_utc="20260911T090000Z")))
    out = capsys.readouterr().out
    assert out.isascii() and "GATE: OPEN" in out and "may be run ONCE" in out
    assert "NOT the VERDICT line above and NOT the exit code" in out
    assert out.count("PASS ") == 14 and "FAIL " not in out
    # AND IT NAMES THE DOCUMENT THE VERDICT IS ABOUT. The operator's next act is to hand a per-run
    # record's PATH to the one-shot agent, so the stamp the gate was computed on is printed with the
    # verdict rather than matched up afterwards from a directory listing.
    assert "record stamped 20260911T090000Z" in out
    # THE READOUT NAMES WHAT RAN AND NOT ONLY WHAT HAPPENED: the prompt at twelve characters, the deck
    # it was measured on, the graph it was drawn against, the run's shape, and that it is a run rather
    # than a re-score. An operator reading this line can tell a v3 run from a v2 one without opening
    # the artifact.
    assert SU.SUBJECT_BLOCK_SHA256[:12] in out and _V3_ROWS_SHA[:12] in out
    assert f"{SU.live_graph_hash()} against the live {SU.live_graph_hash()}" in out
    assert "3 draws x 118 rows = 354 calls" in out
    assert "a run, not a re-score" in out
    # AND THE SEAT PIN'S READOUT NAMES THE TEST IT PASSED. The model half is a FAMILY test -- the
    # declared seat must be a SUBSTRING of every billed model id -- and the line used to read like an
    # equality, which is a different and stronger claim than the one the scorer makes.
    assert "model FAMILY by substring" in out
    mod.print_gate(mod.oneshot_gate(_gate_record(mod, fired=2)))
    out = capsys.readouterr().out
    assert out.isascii() and "GATE: HELD" in out and "The one-shot is NOT spent." in out
    assert "FAIL " in out and "2 fired" in out
    # AND AN ABSENT FIELD PRINTS AS AN ABSENCE RATHER THAN AS A ZERO OR A BLANK.
    mod.print_gate(mod.oneshot_gate(_gate_record(mod, no_dec_scored=True,
                                                 drop=("planner_block_sha256", "deck_rows_sha256",
                                                       "graph_hash", "draws"))))
    out = capsys.readouterr().out
    assert out.isascii() and "GATE: HELD" in out
    assert "no scored census for the decoy class" in out
    assert "recorded no planner block sha" in out and "recorded no deck identity" in out
    assert "recorded no graph hash" in out
    assert "no draw, row or call census" in out
    # AND A RE-SCORE SAYS SO IN THE READOUT AND NOT ONLY IN THE VERDICT, because the line an operator
    # acts on is this one and "a re-read of banked picks" is the whole of the reason.
    mod.print_gate(mod.oneshot_gate(_gate_record(mod,
                                                 rescored_from="subject_v3_20260911T000000Z.json")))
    out = capsys.readouterr().out
    assert out.isascii() and "GATE: HELD" in out
    assert "a RE-SCORE of subject_v3_20260911T000000Z.json" in out
    assert "not the run it would certify" in out
    # AND THE WRONG ARTIFACT CLASS SAYS WHICH CLASS IT WAS AND WHERE THE RIGHT ONE IS. A merged
    # summary is the document most likely to be handed to this gate by mistake -- it is the file in
    # the dated bank with the deck's name on it -- and "REFUSED" plus the pointer is what stops that
    # being a silent HELD on some other check.
    mod.print_gate(mod.oneshot_gate({"kind": mod.SUMMARY_KIND, "layer2_runs": [],
                                     "layer2": _gate_doc()["layer2"]}))
    out = capsys.readouterr().out
    assert out.isascii() and "GATE: HELD" in out
    assert "REFUSED -- a MERGED DECK SUMMARY" in out and "layer2_runs" in out


# ---------------------------------------------------------------------------------------------------
# THE BANK THAT CANNOT TRANSPLANT PROVENANCE -- one immutable record per layer-2 run, and a summary
# that only POINTS at them (2026-09-11, the round-3 MAJOR closed)
#
# The defect, MEASURED before the fix on a doctored bank and free: `data/subject_resolver/<date>/
# <deck>_summary.json` is a FIXED path per deck per date, merged with `_merged = dict(_prev);
# _merged.update(summary)`. The preserve loop kept an earlier run's `layer2` and its `oneshot_gate`
# -- which is what stops a free layer-1 re-run erasing a billed measurement -- while every provenance
# field in the LATER run's summary overwrote the banked one. So one ordinary `--layer 1` pass left an
# earlier layer 2 and an earlier OPEN gate sitting under a fresh `planner_block_sha256`, a fresh
# `graph_hash` and a fresh stamp: the three checks this arc exists to add, asserting on the durable
# artifact the opposite of what they were built to prevent. The same site replaced a first calibration
# with a second outright, so the tree kept the LAST attempt and no count of attempts at all.
# ---------------------------------------------------------------------------------------------------
def _pe10_deck(tmp_path):
    """A TWO-ROW DECK OF THIS TEST'S OWN. It is deliberately not a shipped deck: what is under test is
    the BANK, and a two-row deck makes the billed path two calls of a fake transport. Its rows carry
    ids, which is exactly what must not reach the in-tree record."""
    p = tmp_path / "pe10_deck.yaml"
    p.write_text("today: 2026-09-10\nmax_contracts: 2\nrows:\n"
                 "  - {id: r1, klass: synonym, expect: [frost], "
                 "phrase: a cold snap in the growing region}\n"
                 "  - {id: d1, klass: decoy, expect: [], phrase: who won the league}\n",
                 encoding="utf-8", newline="\n")
    return p


def _pe10_wire(mod, monkeypatch, *, stamps):
    """THE ZERO-COST SEAT. `dp.plan_turn` is the REAL planner and only the TRANSPORT is faked (the
    `pb14` idiom), the graph is the two-contract fixture, the vocabulary artifact is stubbed `ok` and
    the semantic tier is stubbed LIVE so the instrument fence passes. `_utc_stamp` is driven from a
    list because the record's NAME is the run's stamp at one-second resolution: two runs inside one
    second are a collision the writer REFUSES, and a test that slept would be measuring the clock."""
    from leviathan.graphrag import answer as an
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used-the-transport-is-fake")
    monkeypatch.delenv("GRAPHRAG_DISPATCH", raising=False)
    monkeypatch.setattr(mod, "load_graph", _seam_graph)
    monkeypatch.setattr(SU, "load_vocab", lambda *a, **kw: ({}, "ok"))
    monkeypatch.setattr(mod, "layer1_rows", lambda rows, *, graph, vocab: [
        {"id": r["id"], "klass": r["klass"], "expect": list(r["expect"]), "exact": [], "alias": [],
         "vocab_status": "ok",
         "cands": ([["frost", 0.81, "id"]] if r["klass"] != "decoy" else [])} for r in rows])
    _seq = list(stamps)
    monkeypatch.setattr(mod, "_utc_stamp", lambda: _seq.pop(0) if _seq else "20260911T235959Z")

    def transport(system, user, *, model, tool, **kw):
        pick = ["frost"] if "cold snap" in str(user) else []
        return {"steps": ["reasoning"], "contracts": ["arabica_coffee"], "subject": pick,
                "_usage": {"in": 1000, "out": 40, "cache_read": 0, "cache_write": 0,
                           "model": mod.SEAT}}

    monkeypatch.setattr(an, "_call_opus", transport)


def test_pe10_A_LAYER_2_RUN_BANKS_ONE_IMMUTABLE_RECORD_AND_THE_SUMMARY_ONLY_POINTS_AT_IT(
        monkeypatch, tmp_path, capsys):
    """THE FOUR DIRECTIONS THE FIX IS STATED OVER, DRIVEN END TO END THROUGH `main` AT ZERO COST.

    (1) A layer-2 run writes ONE file whose name carries the run's own stamp, carrying provenance,
        the measurement, the bars and the gate computed over THAT SAME document; the dated summary
        keeps a POINTER to it and no layer-2 block of its own.
    (2) A FREE `--layer 1` re-run afterwards leaves that file BYTE-IDENTICAL and the pointer list
        unchanged -- the transplant, driven in the direction it actually occurred.
    (3) A SECOND layer-2 run adds a SECOND file and touches neither the first file nor its pointer,
        so two calibrations are two entries: the attempt count nothing in the tree had.
    (4) The gate REFUSES the merged summary by its artifact class, and grades the per-run record by
        PATH, which is how the one-shot's operator will be handed it.
    (5) AND THE CARRIED FREE LAYER IS STAMPED WITH THE RUN THAT MEASURED IT. The same transplant
        survives on the free side of the merge: `_merged.update(summary)` replaces the header's
        `generated_utc` / `planner_block_sha256` / `graph_hash` while the preserve loop carries a
        predecessor's `layer1` unchanged, so the report printed a full provenance header over a LAYER 1
        table measured by an earlier run. No money and no gate ride on it -- the gate refuses this
        document by artifact class and layer 1 is free and re-derivable -- so the block is STAMPED
        (`layer1_generated_utc`) and the report says so, rather than moved into a record of its own.

    AND THE RECORD IS PHRASE-FREE AND ID-FREE, which `pb11` grades over the whole bank directory and
    this grades over the new file: the deck's row ids are `r1` and `d1` and neither may appear."""
    mod = _runner()
    deck = _pe10_deck(tmp_path)
    bank, out = tmp_path / "bank", tmp_path / "out"
    _pe10_wire(mod, monkeypatch, stamps=["20260911T101010Z", "20260911T101010Z"])
    rc = mod.main(["--deck", str(deck), "--layer", "2", "--draws", "1", "--cap-usd", "1",
                   "--bank-dir", str(bank), "--out-dir", str(out)])
    console = capsys.readouterr().out
    assert rc == 0, console[-2000:]
    assert console.isascii()
    # -- (1) ONE RECORD, NAMED BY THE RUN'S OWN STAMP, AND IT CARRIES EVERYTHING TOGETHER.
    recs = sorted(bank.glob("pe10_deck_layer2_*.json"))
    assert [p.name for p in recs] == ["pe10_deck_layer2_20260911T101010Z.json"], recs
    rec = json.loads(recs[0].read_text(encoding="utf-8"))
    assert rec["kind"] == mod.RECORD_KIND
    prov = rec["provenance"]
    for k in ("generated_utc", "planner_block_sha256", "graph_hash", "deck", "deck_sha256",
              "deck_rows_sha256", "rows_total", "class_counts", "draws", "seat",
              "temperature", "own_structure_fence", "live_ids_count", "runner_sha256"):
        assert k in prov, k
    assert prov["planner_block_sha256"] == SU.SUBJECT_BLOCK_SHA256
    assert prov["own_structure_fence"] == sorted(SU.OWN_STRUCTURE_IDS)
    assert prov["live_ids_count"] == len(SU.live_ids(_seam_graph()))
    assert prov["class_counts"] == {"synonym": 1, "decoy": 1} and prov["rows_total"] == 2
    # THE DECK'S VERSION IS A FIELD RATHER THAN A FILENAME FOR A READER TO PARSE -- v1, v2 and v3 are
    # three instruments and a record should say which one it names. This deck carries no version in
    # its name and correctly gets none: an invented one would be provenance the run never had.
    assert "deck_version" not in prov
    assert mod.layer2_record({"deck": "subject_deck_v3.yaml", "layer2": {"calls": 1}}
                             )["provenance"]["deck_version"] == "v3"
    assert rec["layer2"]["calls"] == 2 and rec["layer2"]["errored_calls"] == 0
    assert rec["layer2"]["per_class"]["decoy"]["fired"] == 0
    assert rec["layer2"]["per_class"]["synonym"]["passed"] == 1
    assert rec["layer2"]["seat_pin"]["verdict"] == "PASS"
    assert rec["bars"] and all("rows" not in b for b in rec["bars"])
    # THE GATE IS INSIDE THE DOCUMENT IT WAS COMPUTED ON, and it HOLDS -- this is not the certifying
    # deck, and a run on any other deck holds the gate by construction.
    assert rec["oneshot_gate"]["verdict"] == "HELD"
    assert any(c.startswith("THE DECK") for c in rec["oneshot_gate"]["failing"])
    assert not any(c.startswith("THE ARTIFACT CLASS") for c in rec["oneshot_gate"]["failing"])
    # AND IT IS PHRASE-FREE AND ID-FREE: `pb11`'s rule, applied to the new file.
    _text = recs[0].read_text(encoding="utf-8")
    assert "cold snap" not in _text and '"r1"' not in _text and '"d1"' not in _text
    assert "unscored_n" in _text and '"unscored"' not in _text
    # THE SUMMARY POINTS AND DOES NOT CERTIFY.
    _sum_path = bank / "pe10_deck_summary.json"
    summary = json.loads(_sum_path.read_text(encoding="utf-8"))
    assert summary["kind"] == mod.SUMMARY_KIND
    assert "layer2" not in summary and "oneshot_gate" not in summary
    assert [r["file"] for r in summary["layer2_runs"]] == [recs[0].name]
    assert summary["layer2_runs"][0]["planner_block_sha256"] == SU.SUBJECT_BLOCK_SHA256
    assert summary["layer2_runs"][0]["gate_verdict"] == "HELD"
    assert summary["oneshot_gate_latest"]["file"] == recs[0].name
    assert "THE ATTEMPT COUNT IS THE LENGTH OF THIS LIST" in (
        bank / "pe10_deck_summary.md").read_text(encoding="utf-8")
    _before = recs[0].read_bytes()
    _sum_before = json.loads(_sum_path.read_text(encoding="utf-8"))

    # -- (2) THE FREE LAYER-1 RE-RUN. This is the exact pass that transplanted provenance: it makes no
    #    draw, it costs nothing, and it used to rewrite the block sha and the graph hash sitting over
    #    a banked layer 2.
    _pe10_wire(mod, monkeypatch, stamps=["20260911T111111Z", "20260911T111111Z"])
    rc1 = mod.main(["--deck", str(deck), "--layer", "1", "--bank-dir", str(bank),
                    "--out-dir", str(out)])
    capsys.readouterr()
    assert rc1 in (0, 1)
    assert recs[0].read_bytes() == _before, "the free re-run rewrote a banked layer-2 record"
    _sum2 = json.loads(_sum_path.read_text(encoding="utf-8"))
    assert _sum2["layer2_runs"] == _sum_before["layer2_runs"], "the pointer list moved"
    assert _sum2["oneshot_gate_latest"] == _sum_before["oneshot_gate_latest"]
    assert _sum2["generated_utc"] == "20260911T111111Z", "the summary names the LATEST run"
    assert _sum2["layer2_runs"][0]["generated_utc"] == "20260911T101010Z", (
        "the pointer still names the run that made the draws")
    assert _sum2["layers_run"] == ["1", "2"] and "layer1" in _sum2
    # THIS RUN MEASURED LAYER 1, so the header stamp IS the layer-1 stamp and there is nothing to
    # carry: an inherited `layer1_generated_utc` here would itself be the lie.
    assert "layer1_generated_utc" not in _sum2

    # -- (3) THE SECOND LAYER-2 RUN. A second attempt is a second FILE and a second POINTER, and the
    #    first of each is untouched -- the tree can now say how many calibrations were run.
    _pe10_wire(mod, monkeypatch, stamps=["20260911T121212Z", "20260911T121212Z"])
    rc2 = mod.main(["--deck", str(deck), "--layer", "2", "--draws", "1", "--cap-usd", "1",
                    "--bank-dir", str(bank), "--out-dir", str(out)])
    capsys.readouterr()
    assert rc2 == 0
    recs2 = sorted(bank.glob("pe10_deck_layer2_*.json"))
    assert [p.name for p in recs2] == ["pe10_deck_layer2_20260911T101010Z.json",
                                       "pe10_deck_layer2_20260911T121212Z.json"], recs2
    assert recs[0].read_bytes() == _before, "the second run overwrote the first record"
    _sum3 = json.loads(_sum_path.read_text(encoding="utf-8"))
    assert [r["file"] for r in _sum3["layer2_runs"]] == [p.name for p in recs2]
    assert len(_sum3["layer2_runs"]) == 2, "the attempt count is the pointer list's length"
    assert _sum3["oneshot_gate_latest"]["file"] == recs2[1].name
    # -- (5) THE CARRIED LAYER 1 IS STAMPED WITH THE RUN THAT MEASURED IT, AND THE REPORT SAYS SO.
    #    This run measured layer 2 only; the layer-1 table below the header was measured at 111111Z
    #    and the header names 121212Z, which is exactly the pair that used to be printed silently.
    assert "layer1" in _sum3 and _sum3["layers_run"] == ["1", "2"]
    assert _sum3["layer1_generated_utc"] == "20260911T111111Z", (
        "the carried layer-1 table is not stamped with the run that measured it")
    _md3 = (bank / "pe10_deck_summary.md").read_text(encoding="utf-8")
    assert "- generated: 20260911T121212Z" in _md3
    assert "LAYER 1 was MEASURED at 20260911T111111Z" in _md3
    assert "nor the layer 2 in any of the files above" in _md3
    # AND A COLLISION IS REFUSED RATHER THAN RESOLVED: the same record written twice STOPs, which is
    # the only safe answer when a path already holds a measurement.
    with pytest.raises(SystemExit) as _ex:
        mod.write_layer2_record(bank, "pe10_deck", json.loads(_before.decode("utf-8")))
    assert _ex.value.code == 2
    assert "written ONCE" in capsys.readouterr().out
    assert recs[0].read_bytes() == _before

    # -- (4) THE ARTIFACT CLASS, ON THE REAL FILES. The summary is REFUSED by name; the record is
    #    graded by PATH, which is how the one-shot's operator will hand it on.
    _g_sum = mod.oneshot_gate(_sum3)
    assert _g_sum["verdict"] == "HELD"
    assert any(c.startswith("THE ARTIFACT CLASS") for c in _g_sum["failing"]), _g_sum["failing"]
    _g_rec = mod.oneshot_gate(recs2[1])
    assert _g_rec["verdict"] == "HELD"                      # not the certifying deck
    assert not any(c.startswith("THE ARTIFACT CLASS") for c in _g_rec["failing"]), _g_rec["failing"]
    assert _g_rec["certifies"] == "20260911T121212Z"
    # AND THE SAME QUESTION AS A COMMAND, because the operator's instruction is to read the gate off
    # the record BY NAME: a door that only opens from Python is a door nobody uses at the seat, and
    # "read the gate off the file" would quietly become "trust the console line from an hour ago".
    # It costs nothing, it decides one thing, and its exit code IS the gate (0 OPEN / 1 HELD / 2 not
    # a gradable record) -- which is the one place in this script where the exit code may be read as
    # the gate, precisely because no bar is being graded beside it.
    assert mod.main(["--grade-record", str(recs2[1])]) == 1
    _out = capsys.readouterr().out
    assert _out.isascii() and "GATE: HELD" in _out and recs2[1].name in _out
    assert mod.main(["--grade-record", str(bank / "pe10_deck_summary.json")]) == 1
    assert "REFUSED -- a MERGED DECK SUMMARY" in capsys.readouterr().out
    # A DOCUMENT THAT CANNOT BE READ AS A RECORD IS A REFUSED CLASS AND NOT A SILENCE; a NAME that is
    # not a file is the one refusal, because it is a typo and not a verdict.
    assert mod.main(["--grade-record", str(bank / "pe10_deck_summary.md")]) == 1
    assert "could not be read as a per-run record" in capsys.readouterr().out
    assert mod.main(["--grade-record", str(bank / "no_such_record.json")]) == 2
    assert "no such record" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------------
# THE CERTIFICATE NAMES ITS BYTES, AND THE RUN MEASURES ITS PROMPT (2026-09-11, the round-4 findings)
#
# Two defects of the same shape, one MAJOR and one minor, both under the certificate's own claims.
#
# THE MAJOR. `planner_block_sha256` was the one provenance input that was DECLARED rather than
# MEASURED: `main` wrote `SU.SUBJECT_BLOCK_SHA256` (the module CONSTANT) onto the record and
# `live_block_sha()` read the SAME constant back, so the gate's PROVENANCE check was a constant against
# itself at both ends and nothing in the runner ever hashed the block text the run actually sends.
# MEASURED free and in-process: with `dispatch._subject_block` returning a text hashing to 14703c0a77c8
# while the pin stayed d7ed2de860fc, the run RECORDED d7ed2de860fc, the readout printed
# `PASS  PROVENANCE ... d7ed2de860fc against the live d7ed2de860fc`, and the GATE read OPEN with zero
# failing checks on 354 clean calls. That is the exact fail-open this arc closed for THE DECK (hashed
# off the file) and THE GRAPH (stamped off the DAG bytes).
#
# THE MINOR. The record's FILE NAME was not bound to the stamp inside it. MEASURED: copying
# `<deck>_layer2_20260911T110000Z.json` to `<deck>_layer2_20261231T000000Z.json` graded OPEN, beside a
# readout saying "computed on the per-run layer-2 record stamped 20260911T110000Z" -- a file in the
# tree named for a run that did not happen.
# ---------------------------------------------------------------------------------------------------
def test_pe11_THE_RUN_MEASURES_ITS_PROMPT_AND_THE_GATE_NAMES_THE_BYTES_IT_GRADED(
        monkeypatch, tmp_path, capsys):
    """FOUR DIRECTIONS, ALL AT ZERO COST THROUGH THE SAME FAKE TRANSPORT `pe10` uses.

    (1) THE PROMPT IS MEASURED. With `_subject_block` rendering a text whose digest is NOT the pin, the
        run REFUSES before a call is made and before anything is banked -- and the refusal names both
        digests, because "the block moved" and "the pin is stale" are different repairs.
    (2) AND A LEGITIMATE RE-FREEZE RUNS AND BANKS ITS OWN DIGEST. With the render moved AND the pin
        moved with it, the fence is satisfied, the run proceeds, and the record carries that digest --
        which is not the one this tree's real constant carries. (1) is the direction that FALSIFIES
        the old code, which recorded the pin whatever the renderer did and ran on; this one pins that
        the field follows the render rather than being a literal, and that the fence tightens nothing
        for a block that was re-frozen properly.
    (3) THE FILE NAME IS BOUND TO THE STAMP INSIDE IT. A hand-copy at a foreign name is HELD on THE
        FILE NAME, and the readout prints the graded file's own sha256 so the certificate names its
        BYTES and not only its stamp. The real record passes the same check.
    (4) `--rescore` ANSWERS WITH ITS OWN VERDICT. It returned 0 unconditionally -- a $0 diagnostic
        whose exit code could not fail, which is the "READ EVERY EXIT CODE" law from the other side."""
    mod = _runner()
    deck = _pe10_deck(tmp_path)
    bank, out = tmp_path / "bank", tmp_path / "out"
    # THE REAL PIN, READ BEFORE ANYTHING IS MOVED -- it is the value the OLD code recorded whatever the
    # renderer did, and step (2) is stated against it.
    _real_pin = SU.SUBJECT_BLOCK_SHA256

    # ── (1) THE PROMPT IS MEASURED, AND A MOVED BLOCK REFUSES BEFORE ANY SPEND.
    _pe10_wire(mod, monkeypatch, stamps=["20260911T140000Z", "20260911T140000Z"])
    monkeypatch.setattr(dp, "_subject_block",
                        lambda ids=None: "" if not ids else "A DIFFERENT PROMPT ENTIRELY.\n")
    rc = mod.main(["--deck", str(deck), "--layer", "2", "--draws", "1", "--cap-usd", "1",
                   "--bank-dir", str(bank), "--out-dir", str(out)])
    console = capsys.readouterr().out
    assert rc == 2, console[-2000:]
    assert console.isascii()
    assert "NOT THE PROMPT THIS TREE PINS" in console
    _fake_sha = hashlib.sha256(b"A DIFFERENT PROMPT ENTIRELY.\n").hexdigest()
    assert _fake_sha in console and _real_pin in console
    assert "NOTHING WAS BANKED" in console
    # NOTHING WAS BANKED AND NOTHING WAS ASKED -- the refusal sits before the layer-2 loop's own rows.
    assert not bank.exists() or not list(bank.glob("*.json"))
    assert "[layer 2] the planner" not in console

    # ── (2) A LEGITIMATE RE-FREEZE RUNS, AND THE RECORD CARRIES THE DIGEST THAT WAS RENDERED. Move
    #    the pin WITH the render: the fence is satisfied, the run proceeds, and what lands on the
    #    record is the digest of the text that was rendered -- which the real constant is not. The
    #    FALSIFYING direction is (1) above; this one pins that the fence does not tighten anything for
    #    a block that was re-frozen properly, and that the banked field follows the render.
    _pe10_wire(mod, monkeypatch, stamps=["20260911T141500Z", "20260911T141500Z"])
    monkeypatch.setattr(dp, "_subject_block",
                        lambda ids=None: "" if not ids else "A DIFFERENT PROMPT ENTIRELY.\n")
    monkeypatch.setattr(SU, "SUBJECT_BLOCK_SHA256", _fake_sha)
    rc2 = mod.main(["--deck", str(deck), "--layer", "2", "--draws", "1", "--cap-usd", "1",
                    "--bank-dir", str(bank), "--out-dir", str(out)])
    console = capsys.readouterr().out
    assert rc2 == 0, console[-2000:]
    assert "MEASURED from dispatch._subject_block" in console
    _rec_path = bank / "pe10_deck_layer2_20260911T141500Z.json"
    _rec = json.loads(_rec_path.read_text(encoding="utf-8"))
    assert _rec["provenance"]["planner_block_sha256"] == _fake_sha
    assert _rec["provenance"]["planner_block_sha256"] != _real_pin
    monkeypatch.undo()

    # ── (3) THE FILE NAME AGAINST THE STAMP INSIDE IT, AND THE BYTES NAMED IN THE READOUT.
    _copy = bank / "pe10_deck_layer2_20261231T000000Z.json"
    _copy.write_bytes(_rec_path.read_bytes())
    _g_copy = mod.oneshot_gate(_copy)
    assert _g_copy["verdict"] == "HELD"
    assert any(c.startswith("THE FILE NAME") for c in _g_copy["failing"]), _g_copy["failing"]
    assert _g_copy["graded_file"] == _copy.name
    assert _g_copy["graded_file_sha256"] == hashlib.sha256(_copy.read_bytes()).hexdigest()
    mod.print_gate(_g_copy)
    _out = capsys.readouterr().out
    assert _out.isascii()
    assert "is NAMED for a run it does not carry" in _out
    assert _g_copy["graded_file_sha256"] in _out
    # THE REAL RECORD PASSES THE SAME CHECK, and a document graded in memory has no name to disagree
    # with anything -- the runner derives one from the other, so the check is vacuous there and says so.
    _g_real = mod.oneshot_gate(_rec_path)
    assert not any(c.startswith("THE FILE NAME") for c in _g_real["failing"]), _g_real["failing"]
    _g_mem = mod.oneshot_gate(_rec)
    assert not any(c.startswith("THE FILE NAME") for c in _g_mem["failing"]), _g_mem["failing"]
    assert "graded_file" not in _g_mem
    # AND THE COMMAND DOOR ANSWERS THE SAME WAY, which is the door the one-shot's operator uses.
    assert mod.main(["--grade-record", str(_copy)]) == 1
    assert "THE FILE NAME" in capsys.readouterr().out

    # ── (4) `--rescore` FOLLOWS THE RUN IT RE-READ. The banked artifact's decoy row is doctored to
    #    FIRE, which is the FATAL bar -- the re-score must print STOP and EXIT 1.
    _art = out / "pe10_deck_20260911T141500Z.json"
    _banked = json.loads(_art.read_text(encoding="utf-8"))
    monkeypatch.setattr(mod, "load_graph", _seam_graph)
    assert mod.main(["--rescore", str(_art)]) == 0, capsys.readouterr().out[-2000:]
    capsys.readouterr()
    for _r in _banked["layer2_rows"]:
        if _r["klass"] == "decoy":
            for _d in _r["draws"]:
                _d["subject"] = ["frost"]
    _fired = out / "pe10_deck_FIRED.json"
    _fired.write_text(json.dumps(_banked, indent=2), encoding="utf-8", newline="\n")
    assert mod.main(["--rescore", str(_fired)]) == 1
    _out = capsys.readouterr().out
    assert _out.isascii() and "VERDICT: STOP" in _out


# ---------------------------------------------------------------------------------------------------
# THE LEGACY PREDECESSOR BANK, AND THE ORDER THE THREE ARTIFACTS LAND IN (2026-09-11, round 5)
#
# THE MAJOR IT CLOSES. `markdown()` renders BANKED documents as well as live ones, and its layer-2
# TOTAL row indexed five fields bare (`scored`, `passed`, `passed_pct`, `passed_shipped_v1`,
# `passed_shipped_v1_pct`) while every per-class row above it had already been taught `.get`. The real
# `data/subject_resolver/2026-09-10/subject_deck_v1_summary.json` carries an `all_non_decoy` of
# {scored, passed, passed_pct} -- written before the `shipped v1` column existed -- and the dated
# summary's MERGE carries a predecessor's `layer2` block onto every later run (layer 2 never rides a
# new run's summary, so the preserve loop always fires). MEASURED end to end through the fake
# transport, `--deck subject_deck_v1.yaml --layer 2 --bank-dir <copy of that directory>`:
# `KeyError: 'passed_shipped_v1'` out of `markdown(summary)`, with the immutable record ALREADY on
# disk and the pointer entry never written. Twice over: two runs, two records, ZERO pointers -- two
# real layer-2 attempts that the attempt count (the pointer list's length) did not count, beside a
# summary whose two halves still described the predecessor's run.
#
# AND THE ORDER IS HALF THE FIX. `write_layer2_record` sat AHEAD of `markdown(summary)`, which put the
# one artifact the one-shot is spent against outside the render-before-write rule the scratchpad
# artifact and the summary both obey. The KeyError is closed by `.get`; the ORDER is what makes the
# NEXT rendering defect lose all three halves together instead of banking one of them. The record
# still precedes the summary that points at it, so a refused write never leaves a dangling pointer.
# ---------------------------------------------------------------------------------------------------
def test_pe12_A_LEGACY_PREDECESSOR_BANK_STILL_LANDS_THE_RECORD_THE_POINTER_AND_BOTH_HALVES(
        monkeypatch, tmp_path, capsys):
    """THE LEGACY `layer2` BLOCK IS THE REAL ONE, lifted from the tracked 2026-09-10 v1 bank rather
    than invented here: an older shape a test made up would prove only that the test can imagine a
    missing key, and the defect is about a shape that actually exists in this repository.

    FOUR THINGS MUST LAND, and before the fix exactly one of them did: the per-run RECORD, the
    POINTER entry inside the summary, and BOTH summary halves (.json and .md). Plus two properties of
    the carried block itself -- it is CARRIED and not deleted (it is somebody's banked figures) and it
    is rendered under the stamp of the run that measured it."""
    mod = _runner()
    deck = _pe10_deck(tmp_path)
    bank, out = tmp_path / "bank", tmp_path / "out"
    bank.mkdir()

    # THE PREDECESSOR: a summary written by an OLDER runner, carrying the real legacy layer-2 block.
    _legacy_src = ROOT / "data" / "subject_resolver" / "2026-09-10" / "subject_deck_v1_summary.json"
    _legacy = json.loads(_legacy_src.read_text(encoding="utf-8"))
    _l2 = _legacy["layer2"]
    # THE SHAPE THAT BREAKS IT, ASSERTED RATHER THAN ASSUMED -- if a later bank gains these keys this
    # test is measuring nothing and must say so instead of passing quietly.
    assert "passed_shipped_v1" not in _l2["all_non_decoy"], (
        "the legacy fixture no longer carries the missing-key shape this test is stated over")
    _prev = {"kind": mod.SUMMARY_KIND, "generated_utc": "20260910T124733Z",
             "deck": "pe10_deck.yaml", "rows_total": 2, "layers_run": ["2"],
             "graph_hash": "legacy", "vocab_status": "ok", "verdict": "LAND-DARK",
             "failing_bars": [], "bars": [], "layer2": _l2}
    (bank / "pe10_deck_summary.json").write_text(json.dumps(_prev, indent=2), encoding="utf-8",
                                                 newline="\n")
    (bank / "pe10_deck_summary.md").write_text("# the predecessor report\n", encoding="utf-8",
                                               newline="\n")

    _pe10_wire(mod, monkeypatch, stamps=["20260911T160000Z", "20260911T160000Z"])
    rc = mod.main(["--deck", str(deck), "--layer", "2", "--draws", "1", "--cap-usd", "1",
                   "--bank-dir", str(bank), "--out-dir", str(out)])
    console = capsys.readouterr().out
    assert rc == 0, console[-3000:]                  # it RAISED KeyError here before the fix
    assert console.isascii()

    # (1) THE RECORD.
    _rec_path = bank / "pe10_deck_layer2_20260911T160000Z.json"
    assert _rec_path.is_file()
    # (2) THE POINTER -- the attempt count, which read zero on a real attempt.
    _sum = json.loads((bank / "pe10_deck_summary.json").read_text(encoding="utf-8"))
    assert [r["file"] for r in _sum["layer2_runs"]] == [_rec_path.name]
    # (3) AND (4) BOTH SUMMARY HALVES, REWRITTEN BY THIS RUN.
    assert _sum["generated_utc"] == "20260911T160000Z"
    _md = (bank / "pe10_deck_summary.md").read_text(encoding="utf-8")
    assert "- generated: 20260911T160000Z" in _md and "the predecessor report" not in _md
    # THE CARRIED BLOCK IS RENDERED, NOT DELETED, AND IT IS STAMPED WITH THE RUN THAT MEASURED IT.
    assert _sum["layer2"] == _l2 and _sum["layer2_generated_utc"] == "20260910T124733Z"
    assert "LAYER 2 -- the planner (billed)" in _md
    assert "| ALL non-decoy | - | 90 | 78 (86.7%) | - (-%) | - | - |" in _md, (
        "the legacy total row must render its absences as absences, not raise")

    # THE POINTER CARRIES A DIGEST OF THE BYTES THAT LANDED, and it is the digest of THIS file.
    _ptr = _sum["layer2_runs"][0]
    assert _ptr["record_sha256"] == hashlib.sha256(_rec_path.read_bytes()).hexdigest()
    assert _ptr["gate_verdict"] == "HELD"            # not the certifying deck

    # AND `--grade-record` PUTS THE RECORD BACK AGAINST THAT POINTER. A clean record agrees; the same
    # record hand-edited IN PLACE -- at its own name, keeping its own stamp, which is the one edit no
    # check INSIDE the document can see -- is REFUSED by field name with exit 2.
    assert mod.main(["--grade-record", str(_rec_path)]) == 1
    _out = capsys.readouterr().out
    assert _out.isascii() and "`record_sha256` agrees" in _out and "`gate_verdict` agrees" in _out
    _doctored = json.loads(_rec_path.read_text(encoding="utf-8"))
    _doctored["oneshot_gate"]["verdict"] = "OPEN"     # the certificate, edited to certify itself
    _rec_path.write_text(json.dumps(_doctored, indent=2), encoding="utf-8", newline="\n")
    assert mod.main(["--grade-record", str(_rec_path)]) == 2
    _out = capsys.readouterr().out
    assert _out.isascii() and "REFUSED on `record_sha256`" in _out
    assert "CROSS-CHECK: REFUSED" in _out


# ---------------------------------------------------------------------------------------------------
# THE SCRATCHPAD ARTIFACT IS THE FENCE ANOTHER FENCE'S HONESTY DEPENDS ON, AND WHERE THE PER-ROW
# DETAIL LIVES AFTER THE SESSION (2026-09-11, round 5, minors (b) and (e))
#
# `write_layer2_record` has refused a stamp collision since the record existed, and its refusal text
# says "the run's own full artifact is in the scratchpad and nothing was lost". The scratchpad artifact
# was written with `write_text`, which OVERWRITES -- so the sentence the record's refusal leans on was
# not true of the file it leans on. And the scratchpad is session-temp, which left the one-shot's
# per-row picks with no durable home at all once the in-tree bank is phrase-free and id-free by law.
# ---------------------------------------------------------------------------------------------------
def test_pe13_THE_SCRATCHPAD_REFUSES_A_CLOBBER_AND_THE_FULL_ARTIFACT_HAS_A_DURABLE_HOME(
        monkeypatch, tmp_path, capsys):
    """THREE DIRECTIONS, ALL FREE.

    (1) A second run of one deck into one out-dir inside one UTC second REFUSES rather than replacing
        the first run's artifact -- and the refusal lands AHEAD of every bank write, so the tree gains
        no record, no summary and no pointer from the run that was stopped.
    (2) `--full-artifact-dir` copies the UNFILTERED artifact (every draw and every per-row pick, by
        ROW ID) to a durable home, while the in-tree bank stays phrase-free and id-free.
    (3) A `--full-artifact-dir` inside this repository that git does not call IGNORED is refused
        before the deck is even read -- because "point it somewhere untracked" is an instruction and
        this is a fence."""
    mod = _runner()
    deck = _pe10_deck(tmp_path)
    bank, out = tmp_path / "bank", tmp_path / "out"
    durable = tmp_path / "durable"

    # (2) THE DURABLE COPY, on the first run.
    _pe10_wire(mod, monkeypatch, stamps=["20260911T170000Z", "20260911T170000Z"])
    rc = mod.main(["--deck", str(deck), "--layer", "2", "--draws", "1", "--cap-usd", "1",
                   "--bank-dir", str(bank), "--out-dir", str(out),
                   "--full-artifact-dir", str(durable)])
    console = capsys.readouterr().out
    assert rc == 0, console[-2000:]
    assert console.isascii() and "durable:" in console
    _scratch = out / "pe10_deck_20260911T170000Z.json"
    _durable = durable / "pe10_deck_20260911T170000Z.json"
    assert _scratch.is_file() and _durable.is_file()
    assert _durable.read_bytes() == _scratch.read_bytes(), "the durable copy is the same artifact"
    assert (durable / "pe10_deck_20260911T170000Z.md").is_file()
    # IT IS A COPY AND NOT A MOVE, and it carries what the tree may never carry: the PER-ROW PICKS,
    # keyed by ROW ID. MEASURED HERE AND STATED BECAUSE IT IS NOT WHAT "full artifact" sounds like:
    # neither `layer1_rows` nor `layer2_rows` carries the ASK -- both are keyed by `id` and the deck's
    # phrases never enter any artifact this script writes. So the durable home is complete only
    # because THE HELD-OUT DECK LIVES IN IT TOO: the deck is the id -> phrase join, and it is the
    # reason that directory and not some other one.
    _dtext = _durable.read_text(encoding="utf-8")
    assert '"r1"' in _dtext and '"layer2_rows"' in _dtext
    assert "cold snap" not in _dtext, (
        "the artifact is id-keyed; if it ever carries phrases, say so where durability is described")
    _rec_text = (bank / "pe10_deck_layer2_20260911T170000Z.json").read_text(encoding="utf-8")
    assert "cold snap" not in _rec_text and '"r1"' not in _rec_text

    # (1) THE CLOBBER, REFUSED. Same deck, same out-dir, same stamp: the first run's artifact is
    # another run's bytes and this run may not replace them.
    _before = _scratch.read_bytes()
    _bank_before = sorted(p.name for p in bank.iterdir())
    _pe10_wire(mod, monkeypatch, stamps=["20260911T170000Z", "20260911T170000Z"])
    with pytest.raises(SystemExit) as _ex:
        mod.main(["--deck", str(deck), "--layer", "2", "--draws", "1", "--cap-usd", "1",
                  "--bank-dir", str(bank), "--out-dir", str(out)])
    assert _ex.value.code == 2
    _out_txt = capsys.readouterr().out
    assert _out_txt.isascii()
    assert "already exists and is NOT being overwritten" in _out_txt
    assert "this run has banked nothing" in _out_txt
    assert _scratch.read_bytes() == _before, "the earlier run's artifact was replaced"
    assert sorted(p.name for p in bank.iterdir()) == _bank_before, (
        "the stopped run still banked something")

    # (3) A TRACKED DURABLE HOME IS REFUSED BEFORE ANYTHING IS READ. `src/` is tracked; nothing is
    # written to it and the refusal names why.
    assert mod.main(["--deck", str(deck), "--layer", "2", "--draws", "1", "--cap-usd", "1",
                     "--bank-dir", str(bank), "--out-dir", str(tmp_path / "out3"),
                     "--full-artifact-dir", str(ROOT / "src" / "leviathan")]) == 2
    _out_txt = capsys.readouterr().out
    assert _out_txt.isascii() and "git does not report it as IGNORED" in _out_txt
    assert "Nothing was read, nothing was spent" in _out_txt
    assert not (tmp_path / "out3").exists()
    # AND THE PHASE-E HOME IS ACCEPTED, because it is gitignored in this tree -- the fence must not be
    # a fence against the thing it was built for.
    assert mod.main(["--deck", str(deck), "--layer", "both", "--draws", "1", "--cap-usd", "1",
                     "--dry-run",
                     "--full-artifact-dir", str(ROOT / "docs" / "private" / "subject_heldout")]) == 0
    assert capsys.readouterr().out.isascii()
