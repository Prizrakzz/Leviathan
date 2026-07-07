"""Stdlib near-dup gate (Phase 7 P3 W2.3) — hermetic, synthetic text only (no real DAG/slice IP)."""
from __future__ import annotations

from leviathan.graphrag import novelty as nv

# A synthetic ~80-word passage + a near-dup (same body, one trailing clause) + an unrelated passage.
BASE = ("global coffee production in brazil rose sharply during the season as favorable rainfall "
        "boosted arabica yields across minas gerais and sao paulo while robusta output in espirito santo "
        "also climbed on improved irrigation and higher fertilizer application by growers who expanded "
        "planted area following two years of elevated international prices and strong export demand from "
        "european roasters seeking reliable supply amid tight global inventories reported by major trading "
        "houses tracking shipment volumes through the santos port terminal every single month of the year")
NEAR = BASE + " analysts noted"                          # ~0.99 Jaccard -> above the 0.85 skip threshold
DIST = ("australian wheat farmers faced a severe drought that slashed winter crop tonnage as parched "
        "soils and record heat devastated fields throughout new south wales forcing many producers to "
        "abandon planted hectares and rely on dwindling grain reserves while livestock feed costs surged")


def test_signature_is_deterministic_and_self_jaccard_is_one():
    """blake2b-based sketch: identical input -> byte-identical signature across calls (re-runs must reproduce
    the same skip decisions); a signature is 100% similar to itself."""
    assert nv.signature(BASE) == nv.signature(BASE)
    assert nv.jaccard(nv.signature(BASE), nv.signature(BASE)) == 1.0


def test_jaccard_disjoint_is_zero_and_empty_is_zero():
    assert nv.jaccard(nv.signature(BASE), nv.signature(DIST)) == 0.0
    assert nv.jaccard(nv.signature(""), nv.signature(BASE)) == 0.0    # empty sketch -> 0, never a divide error


def test_near_dup_skipped_distinct_kept():
    """A candidate ~identical to a cached doc's PROP-SPACE signature skips (near_dup); an unrelated candidate
    passes (novel) and is admitted so later candidates dedup against it."""
    gate = nv.NoveltyGate(nv.corpus_signatures({"d1": [{"text": BASE}]}))
    vn = gate.check("k_near", NEAR)
    vd = gate.check("k_dist", DIST)
    assert vn["skip"] is True and vn["reason"] == "near_dup" and vn["score"] >= 0.85 and vn["nearest"] == "d1"
    assert vd["skip"] is False and vd["reason"] == "novel"


def test_exact_dup_md5_short_circuit_is_normalization_insensitive():
    """The first sighting is admitted; a byte-identical (after case/whitespace normalization) re-submit is an
    exact_dup skip via md5 — the verbatim path the prop-space Jaccard would miss."""
    gate = nv.NoveltyGate()
    v1 = gate.check("k1", BASE)
    v2 = gate.check("k2", BASE)
    v3 = gate.check("k3", "  " + BASE.upper() + "  ")
    assert v1["skip"] is False and v1["reason"] == "novel"
    assert v2["skip"] is True and v2["reason"] == "exact_dup" and v2["score"] == 1.0
    assert v3["skip"] is True and v3["reason"] == "exact_dup"           # normalized md5 still matches


def test_long_doc_flagged_partial_and_never_autoskipped_on_tail_novelty():
    """A >FULLTEXT_CAP doc that near-dups the corpus is flagged partial_60k and is NOT skipped on Jaccard
    alone — its head may dup while its tail is genuinely new (only an exact md5 dup would retire it)."""
    long_text = ("brazil coffee arabica robusta exports imports prices weather frost drought harvest "
                 * 1200)                                                # ~84k chars, > 60000
    assert len(long_text) > nv.FULLTEXT_CAP
    gate = nv.NoveltyGate({"d1": nv.signature(long_text)})             # seed an identical-signature "cached" doc
    v = gate.check("k_long", long_text)
    assert v["partial_60k_flag"] is True
    assert v["skip"] is False and v["reason"] == "partial_kept" and v["score"] >= 0.85


def test_gate_verdicts_deterministic_under_fixed_input():
    """Same seeding + same candidate sequence -> identical verdict list (dict iteration is insertion-ordered;
    ties resolve by strict-greater, so the nearest pick is stable)."""
    seq = [("a", NEAR), ("b", DIST), ("c", NEAR)]

    def run():
        g = nv.NoveltyGate(nv.corpus_signatures({"d1": [{"text": BASE}]}))
        return [g.check(k, t) for k, t in seq]

    assert run() == run()


def test_corpus_signatures_are_prop_space_and_join_per_doc():
    """corpus_signatures joins a doc's PROP texts (prop-space; the cache has no full_text) into one signature;
    a doc with only empty props yields an empty signature (not a crash)."""
    sigs = nv.corpus_signatures({"d1": [{"text": "alpha beta"}, {"text": "gamma delta"}],
                                 "d2": [{"text": ""}]})
    assert set(sigs) == {"d1", "d2"}
    assert sigs["d1"] == nv.signature("alpha beta gamma delta")        # per-doc prop texts joined
    assert sigs["d2"] == []


def test_short_text_still_gets_a_signature():
    """A sub-k-word text collapses to one whole-text shingle (a non-empty signature) so it can still be
    compared, rather than reading as Jaccard-0 against everything."""
    assert nv.signature("two words") == nv.signature("two words") and nv.signature("two words")
    assert nv.jaccard(nv.signature("two words"), nv.signature("two words")) == 1.0
