"""NEWCAP TRIAGE 2026-07-24: three harness/serving false-positive classes pinned.

(1) The numbers-verifier caution banner fired on CORRECT CONAB survey answers: prose dates
    ('published June 1, 2025' -> stated 1.0), hyphen-glued unit descriptors ('60-kg bags' -> 60.0),
    and a correct bags->tonnes conversion ('~2.376 million metric tonnes' from 39,598.4 thousand
    60-kg bags) all counted as fabricated figures — and orchestrator.run_numbers_only PREPENDS a
    served 'treat figures with caution' banner on any mismatch, so this degraded live answers.
(2) eval's price_cited/unit_present asserts counted levels_only PIT-guard raises (kind=number
    citations with value=None + empty unit) as price citations — failing served-correct futures rows
    and scoring a correct decline as a price leak.
(3) report() printed 'N judge call(s) FAILED' on every no-judge run (judge never requested).
"""
from __future__ import annotations

from leviathan.graphrag.orchestrator import _verify_numbers_answer


_CONAB_CALLS = [
    {"query": {"table": "silver_conab_coffee", "metric": "production_thousand_bags",
               "period": "2025", "asof": "2026-03-01"},
     "rows": [{"value": 39598.4, "knowledge_date": "2026-02-02"}]},
]


def test_conab_midsafra_geometry_no_false_mismatch():
    # the exact newcap30 answer shapes that fired the banner on a CORRECT serve
    answer = ("Brazil's 2025 arabica production is estimated at 39,598.4 thousand 60-kg bags "
              "(~2.376 million metric tonnes), per the CONAB survey published June 1, 2025.")
    nv = _verify_numbers_answer(answer, _CONAB_CALLS)
    assert nv["mismatched"] == 0, nv


def test_conab_vintage_tiebreak_prose_dates_scrubbed():
    answer = ("As of 1 March 2026, the latest CONAB survey (published on 2 February 2026) puts "
              "production at 39,598.4 thousand bags, roughly 39.6 million bags.")
    nv = _verify_numbers_answer(answer, _CONAB_CALLS)
    assert nv["mismatched"] == 0, nv


def test_real_fabrication_still_flags():
    answer = "CONAB puts production at 43,000 thousand bags."
    nv = _verify_numbers_answer(answer, _CONAB_CALLS)
    assert nv["mismatched"] == 1, nv


def test_bag_conversion_only_for_bag_metrics():
    # a non-bag metric must NOT gain the x60 derived value: 60x restatement of a tonne figure flags
    calls = [{"query": {"table": "silver_psd", "metric": "production", "period": "2025",
                        "asof": "2026-03-01"},
              "rows": [{"value": 100.0}]}]
    nv = _verify_numbers_answer("Production is 6,000 units.", calls)
    assert nv["mismatched"] == 1, nv


def test_round2_classes_no_year_dates_durations_list_markers():
    # the three residual classes the v2 no-judge run surfaced (iod/provenance/empty-persistence rows)
    calls = [{"query": {"metric": "dmi_value"}, "rows": [{"value": 0.149}]}]
    answer = ("The latest reading is +0.149 degC for April 2025, more than 14 months old. "
              "The June 5 trading session had not settled.\n"
              "1. WASDE does not track this\n2. PSD is annual only\n3. SAGIS covers South Africa")
    nv = _verify_numbers_answer(answer, calls)
    assert nv["mismatched"] == 0, nv


def test_eval_price_asserts_ignore_error_citations():
    from leviathan.graphrag.eval import _cascade_asserts
    q = {"expect": {"price_cited": True, "unit_present": True}}
    out = {"citations": [
        # the served, correct level read — unit-stamped
        {"kind": "number", "id": "N1", "value": 424.5, "unit": "US cents/bushel",
         "locator": {"table": "silver_futures_prices", "metric": "close"}},
        # a levels_only PIT-guard raise surfaced as an error citation: value None, empty unit
        {"kind": "number", "id": "N2", "value": None, "unit": "",
         "locator": {"table": "silver_futures_prices", "metric": "close"}},
    ], "trace": {}, "structured": None}
    res = _cascade_asserts(q, out)
    assert res["price_cited"] is True and res["unit_present"] is True, res


def test_eval_decline_row_not_leaked_by_error_citations():
    from leviathan.graphrag.eval import _cascade_asserts
    q = {"expect": {"price_cited": False}}
    out = {"citations": [
        {"kind": "number", "id": "N1", "value": None, "unit": "",
         "locator": {"table": "silver_futures_prices", "metric": "close"}},
    ], "trace": {}, "structured": None}
    res = _cascade_asserts(q, out)
    assert res["price_cited"] is True, res       # True = the expect (False) was satisfied


def test_report_no_judge_run_prints_no_failed_banner():
    from leviathan.graphrag.eval import report, score
    q = {"id": "r1", "question": "?", "contract": "corn_cbot"}
    out = {"answer": "x", "contract": "corn_cbot", "citations": [], "evidence": [],
           "number_calls": [], "trace": {}, "structured": None, "intent": "numbers_only"}
    rows = [{"q": q, "out": out, "rubric": score(q, out), "judge": None}]
    md_off = report(rows, model="m", judge_requested=False)
    assert "judge call(s) FAILED" not in md_off
    md_on = report(rows, model="m", judge_requested=True)
    assert "judge call(s) FAILED" in md_on
