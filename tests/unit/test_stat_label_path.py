"""K9-5 (2026-09-09) -- THE COMPUTED STATISTIC'S LABEL PATH, ITS SCALE, ITS COUNTER, AND THE ?asof= DECLINE.

THE MEASURED DEFECT. `numbers.agent._stat_calls` mints every computed figure under the pseudo-table
`compute_stat` with the stat SLUG as its metric. `compute_stat` is in no registry, has no card and had no
`display_names.yaml` entry, so every seam that renders a number fell through to its fallback: the table id
strip-and-uppered, the metric id raw, no unit (the card fallback `citations._metric_unit` cannot resolve a
pseudo-table), no country and no date. Reproduced on the banked `rv_palm_rapeoil` turn, all seven rows:

    'COMPUTE STAT window_change  = -82,170'

and in the prose the reader actually got: "Window changes on those same stock series: -226,150 [N14],
-170,000 [N13], -82,170 [N11] ..." -- seven magnitudes with no unit, no subject and no window, against the
estate's own doctrine that a figure and its words travel together.

WHAT THIS DECK PINS, clause by clause:
  1. the stat display map is the AGENT'S OWN CLOSED ENUM -- a ninth stat cannot ship unnamed;
  2. every one of the eight renders `<source> <metric label> (<stat words>) <country> = <figure> <unit>`;
  3. ONE SCALE PER QUANTITY: a DIFFERENCE over a percent series is percentage points, a LEVEL is not;
  4. the source unit is resolved from the CARD when the rows carried none, and NEVER from `unit_overrides`
     (no commodity on a handle -> a currency guess across ten currencies);
  5. a rank is an integer in the ROW and an ordinal in the LINE -- one number, `cascade._rv_ordinal`;
  6. THE FOOTER LEAK PIN: no stat id, no dotted `<table>.<metric>` address and no raw table id survives
     into the rendered `## Sources` block. `register.internal_leaks` cannot see this -- it scans reader
     PROSE and its slug set contains none of the eight stat names -- so the class regresses silently
     without this pin;
  7. the two undescribed stats are named in the system prompt, and the prompt is byte-identical flag-OFF;
  8. the `{stat}` counter is derived, enum-bounded, absent when inapplicable, and leaves
     `NumbersTableTouched`'s `compute_stat` exclusion untouched;
  9. `/v1/graph?asof=` STATES an overlay decline instead of rendering an un-dimmed map in silence.
"""
from __future__ import annotations

import re

import pytest
from leviathan.graphrag import citations as C
from leviathan.graphrag import display as DP
from leviathan.graphrag import orchestrator as ORCH
from leviathan.graphrag import register as RG
from leviathan.graphrag.numbers import agent as NA
from leviathan.graphrag.numbers import cascade as CA
from leviathan.graphrag.numbers import stats as ST

PCT_TABLE, PCT_METRIC = "silver_food_cpi", "cpi_yoy_pct"          # a REAL card: unit 'pct', has a data_date
PCT_ROWS = [{"value": v, "unit": None, "data_date": "2025-%02d-01" % i, "country": "brazil"}
            for i, v in enumerate([2.0, 2.4, 2.1, 2.9, 3.4, 3.9, 4.1, 4.0, 4.6, 5.1, 5.4, 6.0], 1)]
PCT_SERIES = [float(r["value"]) for r in PCT_ROWS]


def _mint(stat, res, rows=PCT_ROWS, table=PCT_TABLE, metric=PCT_METRIC, series_unit=None):
    """One stat through the REAL producer, exactly as `_exec_stat` calls it."""
    return NA._stat_calls(stat, res, {"stat": stat, "params": {}, "input_handles": ["L1"]},
                          series_unit if series_unit is not None else rows[0].get("unit"),
                          NA._handle_kd(rows), NA._handle_labels(rows), table, metric)


# ══ 1. THE MAP IS THE ENUM ═══════════════════════════════════════════════════════════════════════════
class TestTheMapIsTheEnum:
    def test_every_agent_stat_has_reader_words(self):
        missing = sorted(set(ST.STAT_NAMES) - set(CA._STAT_DISPLAY))
        assert missing == [], f"stats with no reader words: {missing}"

    def test_the_two_ids_extrema_actually_mints_are_named(self):
        # `extrema` is dispatched once and mints TWO rows; the map must name what the ROW carries.
        assert CA._STAT_DISPLAY["extrema_min"] == "low" and CA._STAT_DISPLAY["extrema_max"] == "high"

    def test_no_stray_names(self):
        # Nothing in the map that is not a stat the agent can actually mint -- a display entry for a name
        # no producer writes is a vocabulary nobody maintains.
        assert set(CA._STAT_DISPLAY) - set(ST.STAT_NAMES) == {"extrema_min", "extrema_max"}

    def test_the_citation_lanes_pseudo_table_constant_is_the_agents_own(self):
        assert C._STATS_TABLE == NA.STATS_TOOL_NAME == CA._STATS_PSEUDO_TABLE == "compute_stat"

    def test_the_pseudo_table_has_a_reader_label_and_it_is_not_in_the_silver_map(self):
        # The fallback for a stat OF a stat, which carries no source card. It lives at the citation seam
        # because `display.check_display_names` fences `tables:` to silver ids -- a build gate this must
        # not turn red, and which is right: that map names silver tables.
        assert C._source_label("compute_stat") == "computed statistic"
        assert "compute_stat" not in DP._tables()
        assert DP.check_display_names() == []

    def test_an_unmapped_stat_renders_its_slug_and_never_raises(self):
        # The family-by-family tightening rule: a name this map does not know renders exactly as today.
        assert CA._metric_display({"table": "compute_stat", "metric": "not_a_stat"}) == "not_a_stat"


# ══ 2. THE LABEL SHAPE ═══════════════════════════════════════════════════════════════════════════════
class TestTheLabelShape:
    @pytest.mark.parametrize("stat,res,words", [
        ("streak", ST.streak(PCT_SERIES, "up"), "run length"),
        ("percentile", ST.percentile(PCT_SERIES[-1], PCT_SERIES), "percentile rank"),
        ("zscore", ST.zscore(PCT_SERIES[-1], PCT_SERIES, window=None), "z-score"),
        ("window_change", ST.window_change(PCT_SERIES, 0, -1), "change over the window"),
        ("revision_count", ST.revision_count(PCT_SERIES, "up"), "consecutive revisions in one direction"),
        ("yoy_delta", ST.yoy_delta(PCT_SERIES, periods=1), "year-over-year change"),
    ])
    def test_source_metric_country_and_words_all_reach_the_line(self, stat, res, words):
        cit = C.from_number(_mint(stat, res)[0], 1)
        assert cit.source == DP.table_label(PCT_TABLE)              # the CARD, never "COMPUTE STAT"
        assert "CPI year-over-year %" in cit.label                  # the metric's own label
        assert f"({words})" in cit.label                            # ...qualified by what was computed
        assert "brazil" in cit.label                                # the subject the seven rows lacked
        assert cit.date == "2025-12-01"                             # PIT inherited from the input rows
        assert cit.unit                                             # never a bare magnitude

    def test_extrema_mints_a_high_and_a_low_and_says_so(self):
        lo, hi = (C.from_number(c, i) for i, c in enumerate(_mint("extrema", ST.extrema(PCT_SERIES)), 1))
        assert "(low)" in lo.label and "(high)" in hi.label

    def test_a_stat_of_a_stat_names_no_card_it_did_not_read(self):
        # The chained handle carries no source card by construction, so the row falls back to the
        # pseudo-table's own display entry rather than attributing a twice-derived figure to a table.
        cit = C.from_number(_mint("window_change", ST.window_change([1.0, 4.0], 0, 1),
                                  rows=[{"unit": "pp"}], table=None, metric=None)[0], 1)
        assert cit.source == "computed statistic" and "change over the window" in cit.label
        assert "compute_stat" not in cit.label

    def test_the_source_card_rides_the_locator_so_the_series_is_drawable(self):
        loc = C.from_number(_mint("window_change", ST.window_change(PCT_SERIES, 0, -1))[0], 1).locator
        assert loc["table"] == "compute_stat"                       # the machine identity is untouched
        assert loc["source_table"] == PCT_TABLE and loc["source_metric"] == PCT_METRIC

    def test_the_row_geography_is_unanimous_or_absent(self):
        # The same refusal the fetched lane makes: a read spanning two destinations names neither.
        rows = [dict(r) for r in PCT_ROWS]
        rows[0]["country"] = "argentina"
        cit = C.from_number(_mint("window_change", ST.window_change(PCT_SERIES, 0, -1), rows=rows)[0], 1)
        assert "brazil" not in cit.label and "argentina" not in cit.label

    def test_a_print_kind_conflict_drops_the_qualifier_not_the_words(self):
        # A settlement-labeled base on a session-close row must lose the BASE, never send the reader
        # back to `window_change` (which is what the shared `_kind_conflict` fence would otherwise do).
        rows = [{"value": v, "unit": "US cents/bushel", "knowledge_date": "2026-09-01",
                 "contract_month": "2026-12", "settle_kind": "close"} for v in (430.0, 442.0)]
        cit = C.from_number(_mint("window_change", ST.window_change([430.0, 442.0], 0, 1),
                                  rows=rows, table="silver_futures_eod", metric="settle")[0], 1)
        assert "change over the window" in cit.label and "window_change" not in cit.label
        assert "settlement price" not in cit.label


# == 2b. THE DESTINATION FENCE (fix-cycle, review MAJOR-1) ============================================
# A stat row is fenced by the card it was COMPUTED OVER, not by the pseudo-table it is minted under.
# `citations._dest_coded` resolves its argument through `load_registry().tables.get()`, which returns None
# for `compute_stat` -- read as "not destination-coded", so the free-axis arm ran on exactly the rows this
# design had just started attributing, and a national flow's label wore ONE BUYER's name. silver_esr is
# the estate's one `destination_coded()` card, so the two lanes of one card are the whole proof.
_ESR_METRIC = "outstanding_sales_1000mt"
_ESR_ROWS = [{"value": 123.0, "unit": "1000 MT", "country": "china", "knowledge_date": "2026-08-28"}]


def _fetched(table, metric, rows):
    return C.from_number({"query": {"table": table, "metric": metric}, "rows": [dict(r) for r in rows],
                          "status": "ok"}, 1)


class TestTheDestinationFenceIsKeyedOnTheSourceCard:
    def test_the_card_this_pin_rests_on_is_still_destination_coded(self):
        # Without this the pins below go vacuously green the day the card's declaration changes.
        from leviathan.graphrag.numbers.registry import load_registry
        assert load_registry().tables["silver_esr"].destination_coded()

    def test_a_stat_over_a_destination_coded_series_refuses_the_buyers_name(self):
        # MEASURED before the fix, same card and same country, both lanes:
        #   FETCHED 'USDA FAS Export Sales (ESR) outstanding sales  = 123 1000 MT'   (buyer refused)
        #   STAT    '... outstanding sales (change over the window) china = 45 1000 MT'
        # i.e. "China's outstanding sales" for a fact that is "outstanding sales TO China".
        stat = C.from_number(_mint("window_change", ST.window_change([78.0, 123.0], 0, 1),
                                   rows=_ESR_ROWS, table="silver_esr", metric=_ESR_METRIC)[0], 1)
        assert "china" not in stat.label.lower()
        assert _mint("window_change", ST.window_change([78.0, 123.0], 0, 1), rows=_ESR_ROWS,
                     table="silver_esr", metric=_ESR_METRIC)[0]["rows"][0]["country"] == "china"

    def test_both_lanes_of_that_card_make_the_same_refusal(self):
        fetched = _fetched("silver_esr", _ESR_METRIC, _ESR_ROWS)
        stat = C.from_number(_mint("window_change", ST.window_change([78.0, 123.0], 0, 1),
                                   rows=_ESR_ROWS, table="silver_esr", metric=_ESR_METRIC)[0], 1)
        assert ("china" in fetched.label.lower()) == ("china" in stat.label.lower()) is False
        assert fetched.source == stat.source                       # ...and headline the same institution

    def test_an_explicit_destination_ask_still_names_it_on_both_lanes(self):
        # The refusal is about BORROWING a buyer the read did not ask for. A scoped read keeps its scope.
        scoped = C.from_number({"query": {"table": "silver_esr", "metric": _ESR_METRIC,
                                          "country": "china"}, "rows": _ESR_ROWS, "status": "ok"}, 1)
        assert "china" in scoped.label.lower()

    def test_the_free_axis_card_keeps_its_geography_on_both_lanes(self):
        # The fence must not become a blanket: on a card whose country axis IS the fact's geography, the
        # row's geo is the subject -- the seven unlabelled MPOC magnitudes this design set out to fix.
        rows = [{"value": v, "unit": "MT", "country": "malaysia", "knowledge_date": "2026-07-31"}
                for v in (2_100_000.0, 1_873_850.0)]
        stat = C.from_number(_mint("window_change", ST.window_change([2_100_000.0, 1_873_850.0], 0, 1),
                                   rows=rows, table="silver_mpoc_stock_comparison",
                                   metric="ending_stocks_mt")[0], 1)
        fetched = _fetched("silver_mpoc_stock_comparison", "ending_stocks_mt", rows)
        assert "malaysia" in stat.label and "malaysia" in fetched.label

    def test_a_stat_of_a_stat_is_fenced_like_an_unresolvable_card_exactly_as_before(self):
        # No source card -> the argument is the pseudo-table again -> the free-axis arm, unchanged. This
        # is the one row shape the fix deliberately leaves where it was: its source IS a computed figure.
        rows = [{"value": 1.0, "unit": "pp", "country": "brazil", "knowledge_date": "2025-12-01"}]
        cit = C.from_number(_mint("window_change", ST.window_change([1.0, 4.0], 0, 1),
                                  rows=rows, table=None, metric=None)[0], 1)
        assert cit.source == "computed statistic" and "brazil" in cit.label


# ══ 3-4. THE SCALE AND THE UNIT ══════════════════════════════════════════════════════════════════════
class TestOneScalePerQuantity:
    def test_a_difference_over_a_percent_series_is_percentage_points(self):
        for stat, res in (("window_change", ST.window_change(PCT_SERIES, 0, -1)),
                          ("yoy_delta", ST.yoy_delta(PCT_SERIES, periods=1))):
            cit = C.from_number(_mint(stat, res)[0], 1)
            assert cit.unit == "pp", (stat, cit.unit)
            assert cit.label.endswith(" pp")

    def test_a_level_over_a_percent_series_keeps_the_series_unit(self):
        # extrema is a READING of the series, not a difference over it -- the one-scale law is per
        # QUANTITY, and a min/max in percentage points would be the same defect mirrored.
        lo, hi = (C.from_number(c, i) for i, c in enumerate(_mint("extrema", ST.extrema(PCT_SERIES)), 1))
        assert lo.unit == hi.unit == "pct"

    def test_the_card_supplies_the_unit_when_the_rows_carry_none(self):
        # The measured cause of seven unitless rows: `silver_mpoc_stock_comparison` rows carry no unit
        # column, so the handle handed the mint None and the pseudo-table had no card to fall back to.
        assert all(r.get("unit") is None for r in PCT_ROWS)
        assert NA._registry_unit(PCT_TABLE, PCT_METRIC) == "pct"

    def test_an_override_only_card_stays_unitless_rather_than_guessing_a_currency(self):
        # silver_futures_eod.settle declares NO `unit:` -- only a per-commodity override map -- and a
        # handle carries no commodity. Fail closed: unitless, exactly as today.
        assert NA._registry_unit("silver_futures_eod", "settle") is None
        assert NA._stat_unit("window_change", None, "silver_futures_eod", "settle") is None

    def test_the_five_kind_labelled_stats_are_untouched(self):
        for stat, unit in NA._STAT_UNIT.items():
            assert NA._stat_unit(stat, "MT", PCT_TABLE, PCT_METRIC) == unit

    def test_a_rank_prints_as_a_rank_without_moving_the_injected_figure(self):
        call = _mint("percentile", ST.percentile(PCT_SERIES[-1], PCT_SERIES))[0]
        assert call["rows"][0]["value"] == pytest.approx(95.8333, abs=1e-3)   # the ROW is UNTOUCHED
        cit = C.from_number(call, 1)
        assert "96th percentile" in cit.label                                 # ...the LINE speaks it

    def test_the_ordinal_is_gated_on_the_verifiers_own_tolerance(self):
        # `stats.percentile`'s smallest possible midrank over its 8-point floor is 6.25. Printing "6th"
        # over a row of 6.25 is 4% apart -- outside `verify._num_matches` -- so a writer quoting the rank
        # it was shown would be STRIPPED. Below the tolerance the line renders exactly as it does today.
        low = ST.percentile(1.0, [1.0] + [9.0] * 7)
        assert low["value"] == pytest.approx(6.25)
        cit = C.from_number(_mint("percentile", low)[0], 1)
        assert "6.25 percentile" in cit.label and "th percentile" not in cit.label

    def test_a_rank_the_ordinal_does_print_agrees_with_its_row_to_the_verifier(self):
        for x, hist in ((6.0, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]),
                        (PCT_SERIES[-1], PCT_SERIES)):
            call = _mint("percentile", ST.percentile(x, hist))[0]
            v = float(call["rows"][0]["value"])
            txt = C._stat_value_text("percentile", v, "percentile")
            if txt is not None:
                shown = float(re.match(r"(\d+)", txt).group(1))
                assert abs(shown - v) <= 0.01 * abs(shown)


# ══ 4b. THE TOOL_RESULT THE NUMBERS-ONLY WRITER ACTUALLY READS ═══════════════════════════════════════
# FIX CYCLE 2026-09-10 (review MAJOR-2). Everything above pins the ROW: the citation label, the numbers
# panel and the `## Sources` footer all read `_stat_unit`'s one string off it. The NUMBERS-ONLY writer
# reads NONE of them -- it is handed the compute_stat tool_result's JSON text, which carried `value`,
# `n`, `provenance` and a note saying "state it with its unit", and no unit. Its only unit for the series
# was therefore the `%` it took off the earlier lookup rows, so it printed "0.6%" under a footer saying
# "0.6 pp": ONE figure, TWO declared scales, across the two surfaces of one answer.
#
# These pins drive the REAL agent loop (mocked client, injected rows -- no spend, no AWS, no model call)
# and read the tool_result the loop actually put on the wire, because a payload assertion made against
# `_exec_stat` in isolation would not prove the key survives `json.dumps(...)[:6000]`.
import json as _json                                                          # noqa: E402
import types as _types                                                        # noqa: E402


def _tool_result_for(stat_input, *, rows_unit="pct", table=PCT_TABLE, metric=PCT_METRIC):
    """One lookup (rows quoted in `rows_unit`) then one compute_stat, through `answer_numbers`; returns
    the DECODED tool_result payload the model was handed for the stat call."""
    def _tu(name, inp, tid):
        return _types.SimpleNamespace(type="tool_use", name=name, input=inp, id=tid)

    class _Msgs:
        def __init__(self, outer):
            self.outer = outer

        def create(self, **kw):
            self.outer.sent.append(kw)
            return self.outer.queue.pop(0)

    class _FakeClient:
        def __init__(self, queue):
            self.queue, self.sent = list(queue), []
            self.messages = _Msgs(self)

    rows = [{"value": str(v), "knowledge_date": "2025-%02d-01" % i, "unit": rows_unit}
            for i, v in enumerate(PCT_SERIES, 1)]
    client = _FakeClient([
        _types.SimpleNamespace(content=[_tu(NA.TOOL_NAME, {"table": table, "metric": metric,
                                                           "agg": "series"}, "t1")], stop_reason="x"),
        _types.SimpleNamespace(content=[_tu(NA.STATS_TOOL_NAME, stat_input, "t2")], stop_reason="x"),
        _types.SimpleNamespace(content=[_types.SimpleNamespace(type="text", text="No figure here.")],
                               stop_reason="x"),
    ])
    NA.answer_numbers("cpi change?", asof="2026-01-01", client=client, query_fn=lambda sql: rows)
    # The whole conversation is re-sent every round, so the SAME block rides several create() calls --
    # deduped by content, which also pins that the payload never changes between rounds.
    blocks = {b["content"] for kw in client.sent for m in kw.get("messages", [])
              if isinstance(m.get("content"), list) for b in m["content"]
              if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") == "t2"}
    assert len(blocks) == 1, blocks
    return _json.loads(next(iter(blocks)))


class TestTheToolResultCarriesTheDerivedScale:
    def test_a_difference_over_a_percent_series_tells_the_writer_pp(self):
        for inp in ({"stat": "window_change", "series_handle": "L1", "t1": 0, "t2": -1},
                    {"stat": "yoy_delta", "series_handle": "L1", "periods": 1}):
            payload = _tool_result_for(inp)
            assert payload["status"] == "ok"
            assert payload["unit"] == "pp", (inp["stat"], payload.get("unit"))

    def test_a_level_over_that_same_series_tells_the_writer_the_series_unit(self):
        # The one-scale law is per QUANTITY: extrema is a READING, so `pp` here would be the same defect
        # mirrored -- and the pair shares one unit, so rows[0] speaks for both.
        payload = _tool_result_for({"stat": "extrema", "series_handle": "L1"})
        assert payload["unit"] == "pct"

    def test_the_kind_labelled_stats_state_their_own_word(self):
        for stat, unit in (("percentile", "percentile"), ("zscore", "sigma")):
            assert _tool_result_for({"stat": stat, "series_handle": "L1"})["unit"] == unit

    def test_the_payload_unit_is_the_injected_rows_unit_and_never_a_second_derivation(self):
        # ONE PRODUCER: the payload key must be the row's own string, not a re-run of `_stat_unit` that
        # could drift from it. Proven on the card-fallback arm, where the rows carry NO unit and the unit
        # exists only because the mint resolved it from the card.
        payload = _tool_result_for({"stat": "window_change", "series_handle": "L1", "t1": 0, "t2": -1},
                                   rows_unit=None)
        assert payload["unit"] == "pp" == NA._stat_unit("window_change", None, PCT_TABLE, PCT_METRIC)

    def test_an_honest_decline_still_carries_no_figure_and_no_unit(self):
        # A decline injects no row, so there is no unit to state -- and the payload must say `declined`,
        # exactly as before this key existed.
        payload = _tool_result_for({"stat": "spread", "series_handle": "L1",
                                    "near_month": "2026-12", "far_month": "2027-03"})
        assert payload["status"] == "declined" and payload.get("unit") is None

    def test_the_rest_of_the_payload_is_unchanged(self):
        payload = _tool_result_for({"stat": "window_change", "series_handle": "L1", "t1": 0, "t2": -1})
        assert payload["provenance"] == {"stat": "window_change", "params": {"t1": 0, "t2": -1},
                                         "input_handles": ["L1"]}
        assert payload["value"] == pytest.approx(4.0) and payload["handle"] == "L2"
        assert "state it with its unit" in payload["note"]


# ══ 6. THE FOOTER LEAK PIN ═══════════════════════════════════════════════════════════════════════════
_SNAKE_STATS = tuple(s for s in (set(ST.STAT_NAMES) | {"extrema_min", "extrema_max"}) if "_" in s)


def _every_stat_footer() -> str:
    cases = [("streak", ST.streak(PCT_SERIES, "up")),
             ("percentile", ST.percentile(PCT_SERIES[-1], PCT_SERIES)),
             ("zscore", ST.zscore(PCT_SERIES[-1], PCT_SERIES, window=None)),
             ("window_change", ST.window_change(PCT_SERIES, 0, -1)),
             ("revision_count", ST.revision_count(PCT_SERIES, "up")),
             ("extrema", ST.extrema(PCT_SERIES)),
             ("yoy_delta", ST.yoy_delta(PCT_SERIES, periods=1))]
    cits, i = [], 0
    for stat, res in cases:
        for call in _mint(stat, res):
            i += 1
            cits.append(C.from_number(call, i))
    prows = [{"value": v, "unit": "US cents/bushel", "knowledge_date": "2026-09-01",
              "contract_month": m, "settle_kind": "settlement"}
             for v, m in ((430.25, "2026-12"), (442.75, "2027-03"))]
    i += 1
    cits.append(C.from_number(_mint("spread", ST.spread([430.25, 442.75], ["2026-12", "2027-03"],
                                                        "2026-12", "2027-03"),
                                    rows=prows, table="silver_futures_eod", metric="settle")[0], i))
    i += 1
    cits.append(C.from_number({"query": {"table": "compute_stat", "metric": "zscore"},
                               "rows": [{"value": 2.13, "unit": "sigma", "knowledge_date": "2026-09-01",
                                         "z_window": 250, "z_series": "silver_futures_eod.settle"}],
                               "status": "ok"}, i))
    return C.render(cits)


class TestTheSourcesFooterCarriesNoMachineIds:
    """`register.internal_leaks` scans reader PROSE and its 237-slug set contains NONE of the eight stat
    names, so nothing in the estate could see this class. Extending the real detector is an owner-apply
    item (register.py is outside this lane); this deck is the standing pin in the meantime."""

    def test_no_snake_case_stat_id_survives(self):
        f = _every_stat_footer()
        hits = [s for s in sorted(_SNAKE_STATS) if re.search(r"(?<![\w.])" + re.escape(s) + r"\b", f)]
        assert hits == [], f"stat ids in the reader's Sources block: {hits}\n{f}"

    def test_no_dotted_table_metric_address_survives(self):
        f = _every_stat_footer()
        assert re.findall(r"\b[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\b", f) == []

    def test_no_raw_silver_table_id_survives(self):
        assert "silver_" not in _every_stat_footer()

    def test_the_pseudo_table_id_never_reaches_the_reader(self):
        f = _every_stat_footer()
        assert "compute_stat" not in f and "COMPUTE STAT" not in f

    def test_the_existing_prose_detector_still_reads_clean(self):
        assert RG.internal_leaks(_every_stat_footer()) == []

    def test_the_stat_names_are_still_invisible_to_the_prose_detector(self):
        # Stated so the next reader does not mistake the pin above for a detector change: this is WHY
        # the footer needs its own pin at all.
        assert not (set(ST.STAT_NAMES) & set(RG._labeled_metric_slugs()))


# ══ 7. THE PROMPT ════════════════════════════════════════════════════════════════════════════════════
class TestThePromptNamesAllEight:
    @pytest.fixture(scope="class")
    def prompts(self):
        from leviathan.graphrag.numbers.registry import load_registry
        reg = load_registry()
        return NA.system_prompt(reg, stats_tool=True), NA.system_prompt(reg, stats_tool=False)

    def test_every_stat_is_named_in_the_bullet(self, prompts):
        on, _ = prompts
        missing = [s for s in sorted(ST.STAT_NAMES) if s not in on]
        assert missing == [], f"stats the model must reverse-engineer from an enum token: {missing}"

    def test_the_two_new_sentences_carry_when_to_use_guidance(self, prompts):
        on, _ = prompts
        assert "is extrema" in on and "is revision_count over a vintage read" in on

    def test_the_derived_scale_rule_reaches_the_numbers_only_writer(self, prompts):
        # FIX-CYCLE (review MAJOR-2). The mint derives the row's unit and the label, the panel and the
        # `## Sources` footer all read that one string -- but the NUMBERS-ONLY writer reads none of them.
        # It sees the compute_stat tool_result, which carries no unit key at all, so its only unit for
        # the series is the `%` it took off the earlier lookup rows: untold, it prints "0.6%" under a
        # footer that says "0.6 pp". ONE figure, TWO declared scales, on the one lane no flag covers.
        on, off = prompts
        assert "percentage POINTS" in on and "'pp'" in on
        assert "percentage POINTS" not in off                        # the rule leaves with the tool
        # ...and the words agree with what the producer actually mints, so the two cannot drift apart.
        assert NA._stat_unit("window_change", "pct", PCT_TABLE, PCT_METRIC) == "pp"
        assert NA._stat_unit("yoy_delta", "%", PCT_TABLE, PCT_METRIC) == "pp"

    def test_the_prompt_delta_is_confined_to_the_flag_on_arm(self, prompts):
        # A prompt edit is a MEASURED change: the numbers system block is one ephemeral-cached block,
        # byte-stable per (registry, flags), so a byte moved here is a cache re-write. The property this
        # pin holds is that the WHOLE delta is the stats bullet and nothing else.
        #
        # RELATIVE, NOT ABSOLUTE (fix cycle 2026-09-10, review MINOR-B). This assertion used to be
        # `len(off) == 243483` -- an absolute byte length on a string that is a pure function of the
        # REGISTRY (39 cards, 219 metrics, every label and desc rendered whole). Any card edit anywhere
        # in the estate -- a new metric, a re-worded desc, a row_count refresh -- reds this deck while
        # saying "flag-OFF prompt moved", which is the opposite of the truth and trains the next reader
        # to re-baseline a number rather than read it. The measured property is the SHAPE of the delta,
        # so it is measured that way: the flag-OFF arm is the flag-ON arm with exactly ONE contiguous
        # block removed, and that block is the stats bullet. A card edit moves both arms together and
        # this pin does not notice; a byte added or removed OUTSIDE the bullet splits the delta in two
        # and this pin fails, which is precisely the regression it exists to catch.
        on, off = prompts
        pre = 0
        while pre < len(off) and on[pre] == off[pre]:
            pre += 1
        suf = 0
        while suf < len(off) - pre and on[len(on) - 1 - suf] == off[len(off) - 1 - suf]:
            suf += 1
        assert pre + suf == len(off), (
            "the flag-ON delta is no longer ONE contiguous block: something outside the stats bullet "
            f"moved (common prefix {pre} + common suffix {suf} != flag-OFF length {len(off)})")
        block = on[pre:len(on) - suf]
        # ...and the one block IS the stats steering: its own words, none of which survive flag-OFF.
        assert "PERCENTILE, STREAK, Z-SCORE" in block and "percentage POINTS" in block
        assert block not in off
        # The cache-write cost, stated as the delta rather than as a total: a literal-derived number
        # that moves ONLY when this bullet is edited. Measured 2026-09-10 (the K9-5 fix cycle).
        assert len(on) - len(off) == len(block) == 2310, (
            "the stats bullet changed size; re-measure the flag-ON cache-write cost "
            f"(now +{len(on) - len(off)} chars)")

    def test_kill_switch_parity_is_byte_exact(self, prompts):
        on, off = prompts
        assert NA.STATS_TOOL_NAME not in off
        for s in ST.STAT_NAMES:                      # the steering leaves with the tool, entirely
            assert f"'{s}'" not in off
        assert len(off) < len(on)


# ══ 8. THE COUNTER ═══════════════════════════════════════════════════════════════════════════════════
def _stat_call(metric):
    return {"query": {"table": "compute_stat", "metric": metric}, "rows": [{"value": 1.0}], "status": "ok"}


class TestTheStatCounter:
    def test_it_counts_by_stat_and_folds_extremas_two_rows_into_one_call(self):
        # FIX CYCLE 2026-09-10 (review MINOR-A): this test's NAME was always the contract and the
        # assertion contradicted it -- `extrema: 2` for a single extrema call. The counter incremented
        # once per injected ROW, and extrema is the one stat that mints two rows per call, so the belt's
        # busiest-looking stat was an artifact of its row shape. One call, one count.
        calls = [_stat_call("window_change"), _stat_call("window_change"),
                 _stat_call("extrema_min"), _stat_call("extrema_max"), _stat_call("zscore"),
                 {"query": {"table": "silver_psd", "metric": "ending_stocks"}, "rows": []}]
        assert ORCH._stat_touches(calls) == {"window_change": 2, "extrema": 1, "zscore": 1}

    def test_two_extrema_calls_count_two(self):
        # The fold is by PAIRS, not a collapse to one: N calls -> N.
        calls = [_stat_call("extrema_min"), _stat_call("extrema_max"),
                 _stat_call("extrema_min"), _stat_call("extrema_max")]
        assert ORCH._stat_touches(calls) == {"extrema": 2}

    def test_a_half_pair_still_records_the_fire(self):
        # A leg dropped downstream (a filtered call list, a truncated artifact) must not erase the call:
        # `max` of the two ids, never their sum and never a silent zero.
        assert ORCH._stat_touches([_stat_call("extrema_max")]) == {"extrema": 1}

    def test_the_seven_one_row_stats_are_unchanged_by_the_pairing(self):
        for s in sorted(set(ST.STAT_NAMES) - {"extrema"}):
            assert ORCH._stat_touches([_stat_call(s), _stat_call(s)]) == {s: 2}

    def test_a_name_outside_the_enum_cannot_mint_a_dimension_value(self):
        assert ORCH._stat_touches([_stat_call("'; DROP"), _stat_call("not_a_stat")]) == {}

    def test_absent_when_inapplicable(self):
        assert ORCH._stat_touches(None) == {} and ORCH._stat_touches([]) == {}
        assert ORCH._stat_touches([{"query": {"table": "silver_psd", "metric": "x"}}]) == {}

    def test_the_series_count_stays_inside_its_bill(self):
        # 8 stat values x 1 metric + 1 declines-by-floor series; the dimension is bounded by a closed
        # enum asserted at stats.py and gated by config_check.check_stats_registry.
        assert len(ST.STAT_NAMES) == 8
        assert len(ST.STAT_NAMES) + 1 <= 16

    def test_the_per_card_census_still_excludes_the_pseudo_table(self):
        # The sibling metric must not have quietly widened `NumbersTableTouched` -- a per-CARD panel
        # topped by a pseudo-table is exactly what that exclusion exists to prevent.
        assert NA.tables_queried([_stat_call("window_change"),
                                  {"query": {"table": "silver_psd"}}]) == ["silver_psd"]


# ══ 9. THE ?asof= OVERLAY DECLINE ════════════════════════════════════════════════════════════════════
class TestTheGraphOverlayStatesItsDecline:
    """The map dimmed identically for two OPPOSITE facts -- "the record says none of these drivers is
    active" and "the record could not be read" -- with no counter, no log line and no field anywhere to
    tell them apart. The decline is additive: the map still renders, always."""

    def _client(self, monkeypatch, lookup, *, dark=False):
        from fastapi.testclient import TestClient
        from leviathan.causal import schema as cs
        from leviathan.graphrag import graph as g
        from leviathan.graphrag import server as sv
        from leviathan.graphrag.store import InMemoryStore
        drivers = [cs.Driver(id="frost", type="hazard", sign="+", mechanism="m",
                             silver_status=("none" if dark else "available"), silver_ref="frost"),
                   cs.Driver(id="low_stocks", type="hazard", sign="+", mechanism="m",
                             silver_status="available", silver_ref="su")]
        contract = cs.CausalContract(
            contract="arabica_coffee", aliases=["arabica"], drivers=drivers,
            convergence=[cs.ConvergenceSignal(name="squeeze", direction="+", requires_any_n_of=2,
                                              drivers=["frost", "low_stocks"])])
        monkeypatch.setitem(sv._STATE, "graph", g.CausalGraph({"arabica_coffee": contract},
                                                              silver=set(), version="gtest12ab34cd"))
        monkeypatch.setitem(sv._STATE, "store", InMemoryStore())
        monkeypatch.setattr(sv, "_silver_lookup", lambda cap=256: lookup)
        # THROUGH monkeypatch, never a bare assignment: `dependency_overrides` is process-global on the
        # app object, so a bare write leaks an authenticated identity into every later test in the
        # session -- measured, it red three `test_api_contract` pins (the two 401-anon routes and the
        # watchlist CRUD) that pass on their own. monkeypatch restores the mapping at teardown.
        monkeypatch.setitem(sv.app.dependency_overrides, sv._require_identity, lambda: {"sub": "u"})
        monkeypatch.setattr(sv, "_OVERLAY_DECLINES_SEEN", set())
        return TestClient(sv.app)

    @staticmethod
    def _read(**extra):
        def lk(contract, did, asof):
            return {"live": True, "verdict": "observed", "z": -2.0, "value": 0.09,
                    "unit": "ratio", "ref": did, **extra}
        return lk

    def test_a_swallowed_silver_miss_is_stated_and_the_map_still_renders(self, monkeypatch):
        # THE REAL PRODUCTION SHAPE: `silverleg.make_silver_lookup` catches everything and returns
        # {"live": False, "ref": None, "reason": "error"} -- nothing raises, so the route's own `except`
        # never sees it. A driver DECLARED available that comes back with no ref was not read.
        def lk(contract, did, asof):
            return ({"live": False, "ref": None, "reason": "error"} if did == "frost"
                    else {"live": True, "verdict": "observed", "ref": did})
        body = self._client(monkeypatch, lk).get("/v1/graph/arabica_coffee?asof=2026-01-01").json()
        assert body["fired_overlay"] == "declined:silver_unread:1/2"
        assert [n["id"] for n in body["nodes"]]                       # the map is intact
        assert any(n.get("active") for n in body["nodes"])            # ...and what WAS read still dims

    def test_a_driver_declared_dark_is_a_stated_absence_not_a_decline(self, monkeypatch):
        # `silver_status: none` (the schema's own word for a driver with no series) returns no
        # ref by design. That is the map saying what it knows, which is the one thing this field
        # must not cry wolf about.
        def lk(contract, did, asof):
            return ({"live": False, "ref": None} if did == "frost"
                    else {"live": True, "verdict": "observed", "ref": did})
        body = self._client(monkeypatch, lk, dark=True).get("/v1/graph/arabica_coffee?asof=2026-01-01").json()
        assert body["fired_overlay"] == "ok"

    def test_a_clean_overlay_says_ok(self, monkeypatch):
        body = self._client(monkeypatch, self._read()).get("/v1/graph/arabica_coffee?asof=2026-01-01").json()
        assert body["fired_overlay"] == "ok"
        assert [n["id"] for n in body["nodes"] if n.get("active")] == ["frost", "low_stocks"]

    def test_a_seam_failure_states_the_class_never_the_message(self, monkeypatch):
        def boom(contract, did, asof):
            raise RuntimeError("s3://bucket/secret-prefix unreachable")
        body = self._client(monkeypatch, boom).get("/v1/graph/arabica_coffee?asof=2026-01-01").json()
        assert body["fired_overlay"] == "declined:RuntimeError"
        assert "secret-prefix" not in str(body) and "s3://" not in str(body)
        assert [n["id"] for n in body["nodes"]]

    def test_no_asof_declines_nothing(self, monkeypatch):
        body = self._client(monkeypatch, self._read()).get("/v1/graph/arabica_coffee").json()
        assert "fired_overlay" not in body            # no overlay asked for, so there is none to decline
        assert all(n.get("active") is None for n in body["nodes"])

    def test_the_decline_is_logged_once_per_contract_and_reason(self, monkeypatch, capsys):
        def lk(contract, did, asof):
            return {"live": False, "ref": None}
        c = self._client(monkeypatch, lk)
        for _ in range(3):
            c.get("/v1/graph/arabica_coffee?asof=2026-01-01")
        assert capsys.readouterr().out.count("GRAPH_OVERLAY_DECLINED") == 1

    def test_a_moving_unread_count_does_not_re_log_the_same_card(self, monkeypatch, capsys):
        # FIX-CYCLE (review MINOR): the silver_unread reason embeds a live `N/M`, so a seen-set keyed on
        # the whole string re-logged on every request whose coverage drifted -- the log-group-as-incident
        # this block exists to avoid. The KEY is the reason's class; the LINE still carries the counts.
        state = {"n": 1}
        def lk(contract, did, asof):
            if did == "frost" or state["n"] > 1:
                return {"live": False, "ref": None}
            return {"live": True, "verdict": "observed", "ref": did}
        c = self._client(monkeypatch, lk)
        c.get("/v1/graph/arabica_coffee?asof=2026-01-01")
        state["n"] = 2                                     # the card degrades further between requests
        c.get("/v1/graph/arabica_coffee?asof=2026-01-01")
        out = capsys.readouterr().out
        assert out.count("GRAPH_OVERLAY_DECLINED") == 1
        assert "silver_unread:1/2" in out                  # ...and the one line still states a count

    def test_two_different_reason_classes_each_log_once(self, monkeypatch):
        # The collapse must not go so far that an exception class hides behind an unread count.
        from leviathan.graphrag import server as sv
        monkeypatch.setattr(sv, "_OVERLAY_DECLINES_SEEN", set())
        for r in ("declined:silver_unread:1/2", "declined:silver_unread:2/2",
                  "declined:RuntimeError", "declined:KeyError"):
            sv._OVERLAY_DECLINES_SEEN.add(("c", ":".join(r.split(":")[:2])))
        assert len(sv._OVERLAY_DECLINES_SEEN) == 3

    def test_the_openapi_schema_name_the_frontend_binds_to_survives(self):
        # `apps/terminal/src/api/client.ts:79` types getGraph as Schemas['GraphTopology']. The route
        # declares its 200 through `responses=` precisely so that name stays in the document: swapping
        # `response_model` for a widened subclass would leave GraphTopology unreferenced and drop it.
        from leviathan.graphrag import server as sv
        spec = sv.app.openapi()
        assert "GraphTopology" in spec["components"]["schemas"]
        ref = spec["paths"]["/v1/graph/{contract}"]["get"]["responses"]["200"]["content"]
        assert ref["application/json"]["schema"]["$ref"].endswith("/GraphTopology")
