"""Stage-D prioritization tests — pure scoring/selection, no network or spend."""
from __future__ import annotations

from leviathan.graphrag import prioritize as pr

MARKERS = ["due to", "because", "led to", "as a result"]
W = {"alpha": 0.4, "sentence": 0.2, "marker": 0.3, "digit": 0.1}


def test_density_prose_beats_table_and_floors_short():
    prose = ("Brazil's coffee output fell sharply because a severe frost hit Minas Gerais. As a result, "
             "arabica prices rose and exporters scrambled to secure supply, due to slow replanting. ") * 4
    table = "12 34 56 78 90 1.2 3.4 5.6 100 200 300 2019 2020 11 22 33 44 55 66 77 88 99 " * 8
    assert pr.density(prose, MARKERS, W) > pr.density(table, MARKERS, W)
    assert pr.density("short", MARKERS, W) == 0.0


def test_recency_curve():
    curve = [[2015, 1.0], [2010, 0.8], [2000, 0.5], [0, 0.25]]
    assert pr.recency("2023", curve) == 1.0
    assert pr.recency("2012", curve) == 0.8
    assert pr.recency("2005", curve) == 0.5
    assert pr.recency("1990", curve) == 0.25
    assert pr.recency("unknown", curve) == 0.25


def test_liquidity_lookup_with_default():
    t = {"soybeans": 1.0, "rice": 0.7, "_default": 0.5}
    assert pr.liquidity("soybeans", t) == 1.0
    assert pr.liquidity("rice", t) == 0.7
    assert pr.liquidity("oats", t) == 0.5


def test_score_doc_priority_and_cost():
    p = {"density_weights": W, "liquidity": {"soybeans": 1.0, "_default": 0.5},
         "recency": [[2015, 1.0], [0, 0.25]], "chars_per_prop": 100, "usd_per_prop": 0.01}
    text = "Soybeans fell because drought hit Argentina. Prices rose as a result of the shortfall. " * 6
    r = pr._score_doc("text/source=usda_gain_soybeans/year=2020/document.json", text, p, MARKERS)
    assert r["commodity"] == "soybeans" and r["year"] == "2020"
    assert r["liquidity"] == 1.0 and r["recency"] == 1.0
    assert abs(r["priority"] - round(r["density"] * 1.0 * 1.0, 5)) < 1e-9
    assert r["est_cost"] == round(r["est_props"] * 0.01, 4)


def test_knapsack_respects_budget_and_value_order():
    rows = [{"priority": 1.0, "est_cost": 1.0},   # value/$ 1.0
            {"priority": 0.9, "est_cost": 0.3},   # 3.0 (best)
            {"priority": 0.5, "est_cost": 1.0},   # 0.5
            {"priority": 0.8, "est_cost": 0.4}]   # 2.0
    picked, cost = pr.knapsack(rows, 1.0)
    assert cost <= 1.0
    assert {round(r["est_cost"], 1) for r in picked} == {0.3, 0.4}   # the two best value/$ that fit


def test_year_cutoff_contiguous_newest_first_with_floor():
    rows = [{"year": "2022", "density": 0.5, "est_cost": 1.0},
            {"year": "2021", "density": 0.5, "est_cost": 1.0},
            {"year": "2010", "density": 0.5, "est_cost": 1.0},
            {"year": "2005", "density": 0.1, "est_cost": 1.0}]    # below floor
    cut, chosen, cost = pr.year_cutoff(rows, 2.0, 0.3)
    assert cut == 2021 and len(chosen) == 2 and cost == 2.0
