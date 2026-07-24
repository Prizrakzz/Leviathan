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


def test_per_call_row_bound_notes_overflow():
    big = dict(_SERIES_CALL)
    big["rows"] = [{"value": float(i), "period": str(2000 + i)} for i in range(12)]
    panel = _judge_numbers_panel({"number_calls": [big]}, max_rows_per_call=8)
    assert "+4 more rows" in panel
    assert "value=7.0" in panel and "value=8.0" not in panel


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
