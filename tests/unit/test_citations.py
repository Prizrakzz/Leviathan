"""Unified provenance citations — numbers + document evidence through one schema (pure; no AWS/LLM)."""
from __future__ import annotations

from leviathan.graphrag.citations import from_evidence, from_number, render, unify


def _number_call():
    return {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot",
                      "country": "Argentina", "period": "2023", "asof": "2024-06-01"},
            "rows": [{"value": "2462000.0", "knowledge_date": "2024-01-10", "period": "2023"}]}


def test_number_citation_has_value_unit_and_rerunnable_locator():
    c = from_number(_number_call(), 1)
    assert c.id == "N1" and c.kind == "number"
    assert "PSD" in c.label and "2,462,000" in c.label and "MT" in c.label   # unit MT pulled from the registry
    assert c.date == "2024-01-10" and c.unit == "MT"
    assert c.locator["kind"] == "number" and c.locator["table"] == "silver_psd" and c.locator["asof"] == "2024-06-01"


def test_number_citation_no_rows_says_not_known():
    call = {"query": {"table": "silver_psd", "metric": "ending_stocks_mt", "commodity": "corn_cbot", "period": "2023"},
            "rows": []}
    c = from_number(call, 3)
    assert "(not known at asof)" in c.label and c.value is None


def test_evidence_citation_carries_forward_compatible_page_slots():
    row = {"source": "usda_gain_wheat", "source_key": "text/gain/xyz.json", "date": "2017-04-17",
           "text": "Black Sea wheat export competition with US HRS is limited by quality differences."}
    e = from_evidence(row, 1)
    # source stays the RAW id (join-keyed to evidence rows); official names are applied at display time
    assert e.id == "E1" and e.kind == "evidence" and e.source == "usda_gain_wheat"
    assert e.locator["kind"] == "doc" and e.locator["source_key"] == "text/gain/xyz.json"
    assert "page" in e.locator and e.locator["page"] is None                # slot present, filled by page-recovery later
    # 6.4: the 140-char display snippet rides the locator so a durable turn keeps a receipt after payload trim
    assert e.locator["snippet"].startswith("Black Sea wheat export competition")


def test_evidence_locator_snippet_truncates_at_140():
    long = "x" * 300
    e = from_evidence({"source": "s", "source_key": "k", "date": "2020-01-01", "text": long}, 1)
    assert e.locator["snippet"] == "x" * 140 + "..." and len(e.locator["snippet"]) == 143


def test_unify_numbers_and_evidence_into_one_numbered_list():
    row = {"source": "usda_wasde", "source_key": "text/wasde/1.json", "date": "1997-01-01", "text": "..."}
    cits = unify([row], [_number_call()])
    assert [c.id for c in cits] == ["E1", "N1"]
    block = render(cits)
    assert "[E1]" in block and "[N1]" in block and "known 2024-01-10" in block


def test_agent_to_citations_bridges():
    from leviathan.graphrag.numbers import agent as A
    cits = A.to_citations([_number_call()])
    assert len(cits) == 1 and cits[0].kind == "number" and cits[0].id == "N1"


# ====================================================================================================
# D-PQ RENDER (2026-08-07). The [N] LABEL *IS* THE SYNTHESIS PROMPT: `orchestrator._numbers_block`
# builds the hybrid writer's numbers panel out of `render(unify(None, calls))`, so anything a row
# carries but the label drops is invisible to the model, however correct the read was. Two measured
# losses, both on CORRECT reads:
#   * dpq_probe_v1 row 1 -- an `agg='front_expiry'` anchor served the right settle and the answer quoted
#     it with no delivery month and no unit (`expiry_labeled` + `unit_present` both FAILED). The expiry
#     is not in the QUERY on that read by construction (the roll rule SELECTS it), and the label was
#     built from the query's scope alone.
#   * dcw_probe_v1 row 11 -- a 5000-row-capped series was narrated as "the full-history trading range on
#     record". The truncation stamp existed and was rendered into `format_provenance` and the eval
#     report; the synthesis prompt never saw it.
# ====================================================================================================
_EOD_ROW = {"value": "447.50", "knowledge_date": "2026-06-05", "contract_month": "2026-12",
            "settle_kind": "settlement", "currency": "USD", "unit": "US cents/bushel"}


def _front_expiry_call(rows=None, **q):
    query = {"table": "silver_futures_eod", "metric": "settle", "commodity": "corn_cbot",
             "asof": "2026-06-08", "agg": "front_expiry"}
    query.update(q)
    return {"query": query, "rows": [dict(_EOD_ROW)] if rows is None else rows, "status": "ok"}


class TestPerExpiryPriceLabel:
    def test_the_delivery_month_comes_off_the_row_when_the_query_names_none(self):
        c = from_number(_front_expiry_call(), 1)
        assert "2026-12" in c.label          # the ONE fact that makes the number attributable
        assert "delivery 2026-12" in c.label

    def test_the_unit_and_the_kind_of_print_ride_the_same_label(self):
        c = from_number(_front_expiry_call(), 1)
        assert "US cents/bushel" in c.label and c.unit == "US cents/bushel"
        assert "exchange settlement" in c.label       # the settle_kind, in words the writer can quote

    def test_a_session_close_is_never_labelled_a_settlement(self):
        # the ICE class: an ohlcv-1d bar is a session CLOSE, and calling it an official settlement is the
        # exact provenance claim the card forbids -- so the panel must hand the writer the honest phrase.
        row = {**_EOD_ROW, "settle_kind": "close"}
        c = from_number(_front_expiry_call(rows=[row]), 1)
        assert "session close" in c.label and "settlement" not in c.label

    def test_the_expiry_reaches_the_locator_so_the_drilldown_reruns_what_was_quoted(self):
        assert from_number(_front_expiry_call(), 1).locator["contract_month"] == "2026-12"

    def test_the_governing_unit_is_recovered_from_the_card_when_the_row_carries_none(self):
        # unit_overrides is the GOVERNING serving unit for this metric and the card declares no bare
        # `unit:` at all -- a call minted outside Q.run (agg-shaped rows, cascade fixtures, a persisted
        # payload) reaches the renderer unitless, and on a ten-currency table with no conversion layer a
        # bare number is unattributable.
        row = {k: v for k, v in _EOD_ROW.items() if k != "unit"}
        c = from_number(_front_expiry_call(rows=[row]), 1)
        assert c.unit == "US cents/bushel" and "US cents/bushel" in c.label

    def test_a_currency_already_inside_the_unit_is_not_doubled_up(self):
        row = {**_EOD_ROW, "unit": "CNY/t", "currency": "CNY"}
        c = from_number(_front_expiry_call(rows=[row]), 1)
        assert c.label.count("CNY/t") == 1 and "CNY, CNY" not in c.label

    def test_a_card_with_no_delivery_month_is_untouched(self):
        # the CEPEA cash references carry contract_month NULL BY DESIGN, and every non-price card carries
        # none at all -- the label must gain nothing there (the pre-D-PQ render is the baseline).
        assert "delivery" not in from_number(_number_call(), 1).label


class TestTruncationReachesTheWriter:
    def _capped(self, limit=5):
        rows = [{"value": str(400 + i), "knowledge_date": f"2026-08-0{i + 1}"} for i in range(limit)]
        return {"query": {"table": "silver_futures_eod", "metric": "settle", "commodity": "corn_cbot",
                          "asof": "2026-08-03", "agg": "series", "limit": limit},
                "rows": rows, "status": "ok", "truncated": True}

    def test_the_label_says_the_read_is_not_the_complete_record(self):
        label = from_number(self._capped(), 1).label
        assert "TRUNCATED" in label and "not the complete record" in label

    def test_it_states_the_span_the_rows_actually_cover(self):
        assert "covering 2026-08-01..2026-08-05" in from_number(self._capped(), 1).label

    def test_the_label_carries_the_FACT_and_never_an_instruction_to_the_writer(self):
        """THE SPLIT, PINNED. This label renders TWICE: into the model's prompt panel
        (`orchestrator._numbers_block`) AND verbatim into the reader's `## Sources` list
        (`answer._cited_sources_block`). A directive is right for the first and is register leakage in
        the second, so only the provenance fact may live here."""
        label = from_number(self._capped(), 1).label
        for imperative in ("do not ", "state the", "never ", "you must"):
            assert imperative not in label.lower()

    def test_the_directive_rides_the_prompt_only_scope_note_channel(self):
        from leviathan.graphrag import orchestrator as ORCH
        panel = ORCH._numbers_block([self._capped()])
        assert "SCOPE NOTE" in panel
        for banned in ("full history", "all-time", "on record"):
            assert banned in panel
        assert "2026-08-01..2026-08-05" in panel        # the span the writer is told to state

    def test_an_uncapped_read_gains_nothing_in_either_render(self):
        from leviathan.graphrag import orchestrator as ORCH
        call = self._capped()
        call["truncated"] = False
        assert "TRUNCATED" not in from_number(call, 1).label
        assert "SCOPE NOTE" not in ORCH._numbers_block([call])

    def test_the_rule_is_not_re_implemented_here(self):
        # DRY fence: the predicate lives in numbers.agent (the engine stamp beats the row count, and only
        # agg='series' can truncate). A second copy would drift the moment the cap rule moves again.
        from leviathan.graphrag import citations as C
        from leviathan.graphrag.numbers import agent as A
        import inspect
        assert "series_truncated" in inspect.getsource(C._series_truncated)
        assert A.series_truncated(self._capped()) is True


class TestGeoLabelFallback:
    """D-PQ RENDER-2b. `silver_nass_crop_progress` repurposes `country` as the US STATE and has NO default:
    the card warns that an unscoped latest read "returns ONE arbitrary state's row, which is a state number
    wearing a national label" -- and the label, built from the QUERY, said nothing at all. The row knows."""

    def _nass(self, rows):
        return {"query": {"table": "silver_nass_crop_progress", "metric": "pct_good_excellent",
                          "commodity": "corn_cbot", "asof": "2026-08-07"},
                "rows": rows, "status": "ok"}

    def test_an_unscoped_read_is_labelled_with_the_state_that_actually_came_back(self):
        c = from_number(self._nass([{"value": "71", "data_date": "2026-08-02", "country": "IA"}]), 1)
        assert "IA" in c.label

    def test_a_read_spanning_several_geographies_names_none_of_them(self):
        """THE FENCE. `_extras` emits a country alias for every card with a country_col, so an UNSCOPED
        multi-destination read (an ESR national total spans every destination code) has rows that
        disagree -- borrowing the headline row's geo there would stamp one destination's name on a
        national aggregate, the exact ESR mislabel the agent's own guard refuses."""
        rows = [{"value": "10", "data_date": "2026-08-02", "country": "China"},
                {"value": "12", "data_date": "2026-08-03", "country": "Mexico"}]
        label = from_number(self._nass(rows), 1).label
        assert "China" not in label and "Mexico" not in label

    def test_an_explicit_scope_always_wins_over_the_row(self):
        call = self._nass([{"value": "71", "data_date": "2026-08-02", "country": "IA"}])
        call["query"]["country"] = "US"
        assert " US " in from_number(call, 1).label and "IA" not in from_number(call, 1).label


class TestGeoFallbackDestinationFence:
    """Fix-cycle-2 review blocker: unanimity is trivially satisfied by a LIMIT-1 read, so an
    unscoped ESR latest read stamped one buyer's name on the national leg. Destination-coded
    tables (country_name_ref set) never borrow row geo; free-axis cards keep the fallback."""

    def _cite(self, table, rows, country=None):
        from leviathan.graphrag import citations as ci
        q = {"table": table, "metric": "weekly_sales", "commodity": "corn"}
        if country:
            q["country"] = country
        c = ci.from_number({"query": q, "rows": rows, "value": 123.4, "unit": "mt"}, 1)
        return c.label

    def test_esr_unscoped_single_row_stays_geo_silent(self):
        label = self._cite("silver_esr", [{"country": "1220", "value": 123.4}])
        assert "1220" not in label

    def test_esr_scoped_read_still_names_the_asked_geo(self):
        label = self._cite("silver_esr", [{"country": "5700", "value": 123.4}], country="5700")
        assert "5700" in label

    def test_free_axis_card_keeps_the_row_geo_fallback(self):
        label = self._cite("silver_nass_crop_progress", [{"country": "IA", "value": 27.0}])
        assert "IA" in label
