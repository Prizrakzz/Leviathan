"""RCA 2026-07-24 (cocoa false-fabrication): the judge's OBSERVED-NUMBERS panel rendered only
rows[0] of each call, so a multi-row series call showed an arbitrary old year as THE value and the
judge convicted the answer's correct latest-row figure as fabricated (grounding 2/5 on a right
answer). These tests pin the fixed panel: every row rendered with period + knowledge date, bounded
per call, empty-call honesty, and the cascade-citation merge (P9-AB G3) preserved.
"""
from leviathan.graphrag.eval import _judge_numbers_panel

_SERIES_CALL = {
    "query": {"table": "silver_icco_cocoa", "metric": "grindings_kt", "commodity": "cocoa",
              "period": "", "asof": "2026-07-21"},
    "rows": [
        {"value": 3727.0, "period": "2007/08", "knowledge_date": "2008-02-28"},
        {"value": 5002.0, "period": "2022/23", "knowledge_date": "2023-11-30"},
        {"value": 4818.0, "period": "2023/24", "knowledge_date": "2025-05-30"},
        {"value": 4628.0, "period": "2024/25", "knowledge_date": "2026-05-29"},
    ],
}


def test_series_call_renders_every_row_not_just_first():
    panel = _judge_numbers_panel({"number_calls": [_SERIES_CALL]})
    # the exact cocoa geometry: BOTH the old row and the latest row must be visible
    assert "3727.0" in panel and "4628.0" in panel
    assert "2024/25" in panel and "2026-05-29" in panel
    assert "4 rows retrieved" in panel
    assert "ANY row at its period is grounded" in panel


def test_single_row_and_not_known_render():
    calls = [
        {"query": {"table": "t", "metric": "m", "commodity": "c", "period": "2024", "asof": "2026-01-01"},
         "rows": [{"value": 42.0, "knowledge_date": "2025-12-01"}]},
        {"query": {"table": "t2", "metric": "m2", "commodity": "c", "period": "", "asof": "2026-01-01"},
         "rows": []},
    ]
    panel = _judge_numbers_panel({"number_calls": calls})
    assert "= 42.0" in panel and "[known 2025-12-01]" in panel
    assert "(NOT KNOWN at asof)" in panel


def test_per_call_row_bound_is_tail_biased():
    """Overflow keeps the FIRST 2 + LAST 6 rows (cocoa proof-run 2026-07-24: a head-only bound hid the
    latest rows — exactly what answers cite — and the judge downgraded a correct figure to 'cannot be
    confirmed'). Hidden middle rows are declared UNVERIFIED, never fabricated."""
    big = dict(_SERIES_CALL)
    big["rows"] = [{"value": float(i), "period": str(2000 + i)} for i in range(12)]
    panel = _judge_numbers_panel({"number_calls": [big]}, max_rows_per_call=8)
    # head 2 (2000, 2001) + tail 6 (2006..2011) visible; middle 4 (2002..2005) summarized
    assert "value=0.0" in panel and "value=1.0" in panel
    assert "value=11.0" in panel and "value=6.0" in panel
    assert "value=3.0" not in panel
    assert "+4 middle rows" in panel and "2002..2005" in panel
    assert "UNVERIFIED" in panel and "never 'fabricated'" in panel


def test_cascade_citation_merge_dedups_by_locator():
    out = {
        "number_calls": [_SERIES_CALL],
        "citations": [
            # duplicate locator of the agent call -> must NOT re-render
            {"kind": "number", "id": "N9",
             "locator": {"table": "silver_icco_cocoa", "metric": "grindings_kt",
                         "period": "", "asof": "2026-07-21"}, "value": 4628.0},
            # a genuinely cascade-injected row -> must render with its handle id
            {"kind": "number", "id": "N7",
             "locator": {"table": "silver_psd", "metric": "su_ratio", "commodity": "cocoa",
                         "period": "2025", "asof": "2026-07-21"}, "value": 0.29, "unit": "ratio"},
        ],
    }
    panel = _judge_numbers_panel(out)
    assert "[N7]" in panel and "0.29" in panel
    assert "[N9]" not in panel


# --- PRE-ARM D4 (2026-09-16, coherence audit JP-H): THE MERGED CITATION'S KNOWLEDGE DATE ------------
# The agent branch appends `[known {kd}]` off `row['knowledge_date']`; the MERGE branch dropped
# `Citation.date`, which citations.py:24 documents as "when it was KNOWN". Every board row and every
# cascade-injected row reaches the judge through that branch, the board is the producer that now mints
# a knowledge date PER ROW off the per-metric publication lags (29de55eb), and `point_in_time` graded
# the answer's correct "known 2026-08-29" against a panel line carrying no date at all.
#
# IT IS DECLARED, NOT DARK: no flag sits over the branch, so this moves the judged prompt on BOTH arms
# of every deck carrying a dated merged citation. Shipped as a pure correction of an omission under the
# S7 `scale`-fix precedent, named in the commit body and again in the arm report.

def test_merged_citation_renders_the_knowledge_date_like_the_agent_row_does():
    """ONE PANEL, ONE SPELLING. The `[known ...]` token and its two leading spaces are the AGENT
    branch's, verbatim, so a judge reading both halves of this panel reads one fact one way."""
    out = {"number_calls": [{"query": {"table": "t", "metric": "m", "commodity": "c",
                                       "period": "2026-09", "asof": "2026-09-08"},
                             "rows": [{"value": 0.0013, "knowledge_date": "2026-08-12"}]}],
           "citations": [{"kind": "number", "id": "N31", "value": 31584, "unit": "contracts",
                          "date": "2026-09-05",
                          "locator": {"table": "silver_cot", "metric": "net_noncomm",
                                      "commodity": "corn", "period": "2026-09-01",
                                      "asof": "2026-09-08"}}]}
    panel = _judge_numbers_panel(out)
    assert "= 0.0013  [known 2026-08-12]" in panel                     # the agent row, unchanged
    assert "= 31584 contracts  [known 2026-09-05]" in panel            # the merged row, corrected
    assert panel.count("[known ") == 2


def test_a_merged_citation_with_no_date_is_byte_identical_to_what_shipped():
    """ABSENT IS NEVER ZERO, AND NEVER A GUESSED DATE EITHER. A citation carrying no `date` renders
    exactly the line HEAD rendered -- the correction reaches only rows that HAVE a knowledge date."""
    loc = {"table": "silver_psd", "metric": "ending_stocks", "commodity": "corn",
           "period": "2025/26", "asof": "2026-09-08"}
    dated = {"kind": "number", "id": "N32", "value": 1899, "unit": "kt", "locator": loc}
    panel = _judge_numbers_panel({"citations": [dated]})
    assert panel == "- [N32] silver_psd.ending_stocks corn 2025/26 asof 2026-09-08 = 1899 kt\n"
    assert "[known" not in panel
    # and an EMPTY-STRING date is an absent one, not a rendered blank
    panel2 = _judge_numbers_panel({"citations": [dict(dated, date="")]})
    assert panel2 == panel
