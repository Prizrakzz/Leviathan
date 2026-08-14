"""L1 citations presentation fix — status-aware empty labels, latest-row headline, staleness clause.

RCA of the judged-30 worst row (COT window, June-2026 asof against silver_cot ending 2025-12-30):
(a) the empty branch flattened the agent's status taxonomy to one '(not known at asof)' string, so a
    scope/coverage gap read as a vintage-timing claim and the answer was declared unanswerable;
(b) a series headlined rows[0] — the OLDEST print (query sorts ASC) — surfacing a stale value as current;
(c) no affordance told the synthesizer the freshest knowable date trailed the asof, so it conflated dates.

Pure — no AWS / LLM / registry writes (registry read for unit is tolerated, falls back to "").
"""
from __future__ import annotations

from leviathan.graphrag.citations import from_number, render, unify


# --- (a) status-aware empty labels -------------------------------------------------------------

def _empty_call(status):
    return {"query": {"table": "silver_cot", "metric": "net_long", "commodity": "cocoa",
                      "period": "2026-06-01..2026-06-30", "asof": "2026-07-21"},
            "rows": [], "status": status}


def test_no_rows_says_coverage_gap_not_timing():
    c = from_number(_empty_call("no_rows"), 1)
    assert "scope/coverage gap" in c.label and "not a timing claim" in c.label
    assert "not yet published" not in c.label and "not known at asof" not in c.label
    assert c.value is None


def test_not_known_says_not_yet_published_with_asof():
    c = from_number(_empty_call("not_known"), 1)
    assert "not yet published as of 2026-07-21" in c.label
    assert "scope/coverage gap" not in c.label


def test_error_status_says_lookup_error():
    c = from_number(_empty_call("error"), 1)
    assert "(lookup error)" in c.label


def test_cascade_status_variants_map_to_the_same_taxonomy():
    assert "not yet published" in from_number(_empty_call("future_unpublished"), 1).label
    assert "scope/coverage gap" in from_number(_empty_call("record_silent"), 1).label


def test_absent_status_preserves_legacy_text():
    # the pre-existing empty-call shape (no status key) MUST still render the legacy string so the
    # existing test_citations.py::test_number_citation_no_rows_says_not_known stays green.
    call = {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                      "period": "2023"}, "rows": []}
    c = from_number(call, 3)
    assert "(not known at asof)" in c.label and c.value is None


# --- (b) latest-row headline (series arrives ASC; headline must be the newest) ------------------

def _series_call():
    # three annual prints, oldest first (as the series SQL returns them, ORDER BY ... ASC)
    return {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                      "country": "Argentina", "asof": "2026-01-15"},
            "rows": [
                {"value": "1000000.0", "knowledge_date": "2023-05-10", "year": 2023},
                {"value": "2000000.0", "knowledge_date": "2024-05-10", "year": 2024},
                {"value": "3000000.0", "knowledge_date": "2025-05-10", "year": 2025},
            ]}


def test_series_headlines_latest_not_first_row():
    c = from_number(_series_call(), 1)
    assert "3,000,000" in c.label            # newest print, not the 1,000,000 oldest
    assert "1,000,000" not in c.label
    assert c.date == "2025-05-10"            # citation date = the headline (latest) row's date
    assert c.value == "3000000.0"


def test_series_headline_robust_to_unsorted_rows():
    call = _series_call()
    call["rows"] = list(reversed(call["rows"]))   # DESC on input -> headline is still the newest
    c = from_number(call, 1)
    assert "3,000,000" in c.label and c.date == "2025-05-10"


def test_payload_keeps_full_series_order_untouched():
    c = from_number(_series_call(), 1)
    # rows[:3] preserved in call order (drill-down contract) — the headline pick does not reorder rows
    assert [r["value"] for r in c.payload["rows"]] == ["1000000.0", "2000000.0", "3000000.0"]


# --- (c) staleness clause --------------------------------------------------------------------

def test_stale_headline_appends_latest_available_clause():
    # freshest knowable = 2025-12-30, asof = 2026-07-21 -> ~7 months behind -> clause fires
    call = {"query": {"table": "silver_cot", "metric": "net_long", "commodity": "cocoa",
                      "asof": "2026-07-21"},
            "rows": [{"value": "12345", "knowledge_date": "2025-12-30", "data_date": "2025-12-30"}]}
    c = from_number(call, 1)
    assert "latest available 2025-12-30" in c.label and "as-of 2026-07-21" in c.label


def test_fresh_headline_has_no_staleness_clause():
    # headline date within ~30 days of asof -> no clause (avoid crying stale on current data)
    call = {"query": {"table": "silver_cot", "metric": "net_long", "commodity": "cocoa",
                      "asof": "2026-07-21"},
            "rows": [{"value": "12345", "knowledge_date": "2026-07-10", "data_date": "2026-07-10"}]}
    c = from_number(call, 1)
    assert "latest available" not in c.label


def test_staleness_clause_skipped_when_dates_unparseable():
    call = {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                      "asof": "2026-07-21"},
            "rows": [{"value": "12345", "period": "2020"}]}   # no knowledge/data date on the row
    c = from_number(call, 1)
    assert "latest available" not in c.label and "12,345" in c.label


# --- render-path integrity (numbers footer + hybrid block both consume render()) ----------------

def test_render_path_joins_status_and_stale_labels_cleanly():
    stale = {"query": {"table": "silver_cot", "metric": "net_long", "asof": "2026-07-21"},
             "rows": [{"value": "9", "knowledge_date": "2025-01-01"}]}
    empty = _empty_call("no_rows")
    block = render(unify(None, [stale, empty]))
    assert "[N1]" in block and "[N2]" in block          # handle table format intact for the verifier
    assert "latest available 2025-01-01" in block
    assert "scope/coverage gap" in block
    # one line per citation, no crash on the multi-clause label
    assert len([ln for ln in block.splitlines() if ln.strip()]) == 2


# --- (d) D-HP G1 REMEDIATION-2 R2-b: "ok + all-blank values" is an ABSENCE, everywhere ----------------

def _blank_call(rows, status="ok"):
    return {"query": {"table": "silver_fred_fx", "metric": "ars_usd", "asof": "2026-06-01"},
            "rows": rows, "status": status}


def test_ok_with_a_single_blank_value_row_renders_the_no_rows_marker():
    """THE THIRD EMPTY SHAPE (G1 decision-1 r3, `dv_sub_ddg_floor` [N1]): status `ok`, one row, value ''.
    It took the rows-bearing branch and rendered `... ars_usd = ` -- a menu line ending in a bare "="
    with nothing behind it, in the prompt panel AND the reader's `## Sources` list. The writer cited it.
    It is an absence and now says so, under the SAME `NO ROWS RETURNED` prefix every other empty branch
    carries (that prefix is what the directive and every existing assertion key on)."""
    c = from_number(_blank_call([{"value": ""}]), 1)
    assert c.label.rstrip().endswith(")") and "= NO ROWS RETURNED" in c.label
    assert "carries no value at all" in c.label and "blank field as of 2026-06-01" in c.label
    assert c.value is None and c.unit is None          # ...and no unit with no value behind it
    assert c.payload["rows"] == [{"value": ""}]        # the drill-down still re-runs the real read


def test_the_blank_shape_does_not_borrow_a_timing_or_coverage_parenthetical():
    """The taxonomy is the point of `_empty_label` and this shape belongs to none of its four branches:
    a row DID come back (not "no matching rows") and nothing is pending publication (not a timing claim).
    Erasing that distinction is the judged-30 RCA (a) defect with a new shape in it."""
    lbl = from_number(_blank_call([{"value": None}, {"value": "   "}]), 1).label
    assert "scope/coverage gap" not in lbl and "not yet published" not in lbl
    assert "not known at asof" not in lbl and "lookup error" not in lbl


def test_a_measured_zero_is_never_read_as_blank():
    """THE WHOLE SAFETY OF THE PREDICATE. `0`, `0.0` and `"0"` are MEASURED quantities; the test is
    written against `is None` / `str(...).strip()` and never against truthiness, because `0 or ""` is
    `""` and a truthy test would erase every measured zero on the estate."""
    for v in (0, 0.0, "0", "0.00"):
        c = from_number(_blank_call([{"value": v, "unit": "MMT"}]), 1)
        assert "NO ROWS RETURNED" not in c.label and c.value is not None
    # a PARTIALLY blank series is a series: one blank row does not make the read an absence.
    c = from_number(_blank_call([{"value": ""}, {"value": 1.62, "unit": "MMT"}]), 1)
    assert "NO ROWS RETURNED" not in c.label


def test_is_empty_read_is_the_one_producer_the_three_consumers_share():
    """ONE PRODUCER, NEVER COPIED -- the `_series_truncated` / `_is_zero_esr_aggregate` discipline. The
    label, `orchestrator._numbers_block`'s empty-read directive and `answer._addresses_empty_row`'s charge
    all key on this predicate, so they cannot disagree about which reads are empty. The r3 defect was
    exactly that disagreement: the label said "a figure", the directive never fired, and the resolver
    knew the truth only after the model had already cited the row."""
    from leviathan.graphrag import citations as cit
    from leviathan.graphrag import orchestrator as orch
    blank = _blank_call([{"value": ""}])
    assert cit.is_empty_read(blank) and cit.is_empty_read(_blank_call([], "no_rows"))
    assert not cit.is_empty_read(_blank_call([{"value": 1.62}]))
    assert not cit.is_empty_read(None) and not cit.is_empty_read({"rows": "junk"})
    # the DIRECTIVE now fires on the blank shape, and still does not fire on a turn that has figures.
    assert "Do NOT cite the empty row" in orch._numbers_block([blank])
    assert "Do NOT cite the empty row" not in orch._numbers_block([_blank_call([{"value": 0}])])
