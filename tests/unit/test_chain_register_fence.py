"""CHAIN ENGINE -- sec 5.1 register fences on engine-emitted chain lines (writer B).

Three fences at BUILD time (before any line reaches the prompt): momentum class (pace_register_ok), valuation/
flow class (DP-6 counters), and the no-conclusion template (the marker + _chain_fmt_* clean by construction).
A tripping line is DROPPED with its [N] handle and the chain tail renumbered contiguously -- no orphan handle,
the ledger count stays honest. In the clean path NOTHING drops (byte-identical)."""
from __future__ import annotations

from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq


def _clean(text: str) -> bool:
    return (cq.pace_register_ok(text)
            and reg.count_valuation_words(text) == 0 and reg.count_flow_words(text) == 0)


# ── fence 3: every template LITERAL passes all three fences (clean by construction) ──────────────────
def test_all_chain_templates_pass_all_three_fences():
    rec = {"query": {"commodity": "corn_cbot", "metric": "production_mt", "period": "MY2020",
                     "asof": "2020-08-31"}, "rows": [{"value": "91200000", "unit": "MT"}]}
    row = {"metric": "production_mt", "narrate_unit": "MMT", "scale": 0.000001}
    for names, meta in ((["safrinha"], {"country": "Brazil", "metric": "production_mt"}),
                        (["exp_a", "exp_b"], {"country": "United States", "metric": "exports_mt"}),
                        (["ending_stocks"], {"country": "United States", "metric": "su_ratio"})):
        label = cq._chain_hop_label(2, 3, names, meta)
        lines = [cq._chain_fmt_line(rec, row, 5, label=label),
                 cq._chain_fmt_delta(row, -2.3, 6, label=label),
                 cq._chain_fmt_pct(row, -11.0, 7, label=label),
                 cq._chain_fmt_line(rec, row, 8, label=label, current=True),
                 cq._chain_marker(" -> ".join(names), "2020-06-01..2021-02-15")]
        for ln in lines:
            assert _clean(ln), f"template line trips a fence: {ln!r}"


def test_marker_carries_no_price_direction_or_threshold():
    m = cq._chain_marker("La_Nina -> safrinha -> ending_stocks_su_ratio", "2020-06-01..2021-02-15")
    assert _clean(m)
    low = m.lower()
    for banned in ("therefore", "implies", "so the price", "bullish", "bearish", "should", "will rise"):
        assert banned not in low


# ── clean path: byte-identical, calls untouched ─────────────────────────────────────────────────────
def test_clean_lines_are_byte_identical_calls_untouched():
    calls = [{"a": 0}, {"a": 1}, {"a": 2}]                      # base=1 -> chain owns calls[1],calls[2]
    before = [dict(c) for c in calls]
    lines = ["- [N2] (chain hop 1/2: area -> United States area_harvested_1000ha) wheat area_harvested_1000ha "
             "MY2010 (as-of 2010-08-31): 34 M ha",
             "- [N3] (chain hop 2/2: ending_stocks -> United States su_ratio) wheat su_ratio MY2010 "
             "(as-of 2010-08-31): 36 %",
             cq._chain_marker("area -> ending_stocks", "2010-06-01..2011-02-15")]
    out = cq._chain_register_fence(list(lines), calls, 1)
    assert out == lines                                        # nothing dropped -> same lines
    assert calls == before                                    # calls untouched (byte-identical path)


# ── fence 1: a momentum line is dropped + its handle removed + tail renumbered ──────────────────────
def test_momentum_line_dropped_and_renumbered():
    calls = [{"pre": True}, {"h2": True}, {"h3": True}, {"h4": True}]   # base=1: chain owns calls[1..3] -> N2,N3,N4
    lines = ["- [N2] hop one clean level",
             "- [N3] this hop is accelerating fast into the season",       # MOMENTUM -> dropped
             "- [N4] hop three clean level",
             cq._chain_marker("a -> b -> c", "w")]
    out = cq._chain_register_fence(lines, calls, 1)
    # the momentum line is gone; survivors renumbered contiguously from base+1 (N2, N3); marker kept.
    assert "accelerating" not in " ".join(out)
    handles = [ln.split("]")[0] for ln in out if ln.startswith("- [N")]
    assert handles == ["- [N2", "- [N3"]                       # contiguous, no gap
    assert calls == [{"pre": True}, {"h2": True}, {"h4": True}]  # dropped handle's call removed, others kept
    assert any(ln.startswith("QUANTIFIED CHAIN") for ln in out)


# ── fence 2: a valuation/flow line is dropped ───────────────────────────────────────────────────────
def test_valuation_flow_line_dropped():
    calls = [{"h2": True}, {"h3": True}]                       # base=0 -> chain owns calls[0],calls[1] -> N1,N2
    dirty = "- [N2] the crop screens cheap versus the balance sheet spread"    # valuation (Lane B: cheap + spread)
    assert not _clean(dirty)                                    # sanity: the counters actually flag it
    lines = ["- [N1] hop one clean level", dirty]
    out = cq._chain_register_fence(lines, calls, 0)
    assert out == ["- [N1] hop one clean level"]
    assert calls == [{"h2": True}]                             # the flagged handle's call dropped


def test_dropped_handle_leaves_no_orphan_and_count_matches():
    # After a drop, len(calls[base:]) == number of surviving chain [N] lines (the honest-ledger invariant).
    calls = [{"x": 0}, {"a": 1}, {"b": 2}, {"c": 3}]           # base=1: 3 chain handles
    lines = ["- [N2] clean", "- [N3] momentum picking up here", "- [N4] clean", cq._chain_marker("p", "w")]
    out = cq._chain_register_fence(lines, calls, 1)
    n_handle_lines = sum(1 for ln in out if ln.startswith("- [N"))
    assert len(calls) - 1 == n_handle_lines                    # base=1 -> surviving tail length == handle lines
