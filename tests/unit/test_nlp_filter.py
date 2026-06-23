"""Exp-2 NLP pre-filter — pure unit tests (no network): rule logic, matcher counting, recall/skip math,
and the useful-skip gate."""
from __future__ import annotations

from leviathan.graphrag import harvest as hv
from leviathan.graphrag import nlp_filter as nf


def test_rule_keep_logic():
    r_or = nf.Rule("or", 2, "or")
    r_and = nf.Rule("and", 1, "and")
    r_ig = nf.Rule("ignore", 2, "ignore")
    assert r_or.keep(2, False) and r_or.keep(0, True) and not r_or.keep(1, False)   # ≥2 entities OR a marker
    assert r_and.keep(1, True) and not r_and.keep(3, False)                          # needs both
    assert r_ig.keep(2, False) and not r_ig.keep(1, True)                            # marker ignored


def test_matcher_counts_distinct_entities():
    ent_rx, _ = hv.build_matcher(["soybeans", "corn", "brazil", "soybean oil"])
    assert nf.n_entities("Brazil soybeans and corn rose", ent_rx) == 3
    assert nf.n_entities("soybeans, soybeans, soybeans", ent_rx) == 1                # distinct only
    mrk_rx, _ = hv.build_matcher(["due to", "because"])
    assert nf.has_marker("fell due to drought", mrk_rx) and not nf.has_marker("fell sharply", mrk_rx)


def test_score_rule_recall_and_skip():
    # (valuable, n_ent, marker): 3 valuable, 1 empty
    feats = [(True, 2, False), (True, 1, True), (True, 1, False), (False, 0, False)]
    r = nf.score_rule(feats, nf.Rule("≥2 OR marker", 2, "or"))
    # kept: row0 (2 ent), row1 (marker) → 2 kept, both valuable; valuable total=3
    assert round(r["value_recall"], 3) == round(2 / 3, 3)
    assert round(r["skip_rate"], 3) == 0.5                                           # 2 of 4 skipped


def test_pick_requires_recall_and_useful_skip():
    # passes recall but skips ~0 → not useful; another skips a lot but fails recall
    rows = [
        {"rule": nf.Rule("a", 1, "or"), "value_recall": 1.00, "skip_rate": 0.003},   # recall ok, skip too low
        {"rule": nf.Rule("b", 2, "or"), "value_recall": 0.85, "skip_rate": 0.17},    # skip ok, recall too low
    ]
    assert nf._pick(rows) is None                                                    # → keep all
    rows.append({"rule": nf.Rule("c", 2, "or"), "value_recall": 0.96, "skip_rate": 0.20})
    assert nf._pick(rows)["rule"].name == "c"                                        # clears both → picked


def test_report_keep_all_when_no_useful_rule():
    rows = [{"rule": nf.Rule("a", 1, "or"), "value_recall": 1.0, "skip_rate": 0.003,
             "kept": 100, "kept_precision": 0.5}]
    rep = nf.build_report(rows, n=100, n_val=50)
    assert "keep all chunks (no NLP skip)" in rep and "retired" in rep
