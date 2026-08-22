"""GN-2 W1.1 -- the basin calm/tail narration, pinned (owner directive: "we're talking to analysts").

The basin rows gave the engine real reads for multi-country belts; this seam gives the reads a voice:
a magnitude word on the weather-z mean line, and the TAIL RIDER -- one sibling `<metric>_tail_share`
read so a calm mean can still say a fifth of the belt is in the tail. Everything here is additive and
fail-closed: the tail spec exists only for gold_weather_z z-rows, only basin surfaces return rows, and
a silent tail renders nothing.

Pure Python -- map rows injected as plain dicts (the cascade test convention); no S3, no pg.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from leviathan.graphrag.numbers import cascade as cq

_ERAS = [("2012-06-01", "2012-11-01"), ("2020-03-01", "2020-08-01")]

_WEATHER_ROW = {"table": "gold_weather_z", "metric": "drought_z", "agg": "latest",
                "period_type": "date", "leg_mode": "current", "country_rule": "region",
                "native_unit": "z", "narrate_unit": "z", "scale": 1}
_PSD_ROW = {"table": "silver_psd", "metric": "exports_mt", "agg": "latest",
            "period_type": "marketing_year", "country_rule": "primary",
            "native_unit": "MT", "narrate_unit": "MMT", "scale": 0.000001}


def _node(contract="cocoa", ref="drought_z", nid="drought"):
    return SimpleNamespace(contract=contract, id=nid, prior={"silver_ref": ref, "region": "West Africa"},
                           evidence=[])


# ── the vocabulary set is BOUND to the transform's, never imported at runtime ─────────────────────────
def test_basin_tail_metrics_mirror_the_transform_z_metrics():
    from leviathan.transforms.gold import weather_z as wz
    assert cq._BASIN_TAIL_METRICS == frozenset(wz.Z_METRICS)
    assert cq._TAIL_SUFFIX == wz.TAIL_SHARE_SUFFIX


# ── the calm word ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v, word", [
    (0.03, "near normal"), (-0.6, "near normal"),
    (1.4, "notably above normal"), (-1.4, "notably below normal"),
    (2.3, "extreme (>= 2 sigma above normal)"), (-2.3, "extreme (>= 2 sigma below normal)"),
])
def test_z_word(v, word):
    assert cq._z_word(v) == word


def test_fmt_line_carries_the_calm_word_for_weather_only():
    rec = {"query": {"commodity": "cocoa", "asof": "2026-08-22"},
           "rows": [{"value": "0.03"}], "status": "ok"}
    line = cq._fmt_line(rec, _WEATHER_ROW, 4, era="current")
    assert "(near normal)" in line and "0.03" in line
    line2 = cq._fmt_line(rec, _PSD_ROW, 4, era="current")
    assert "near normal" not in line2                       # words are WEATHER vocabulary only


# ── the tail spec: exists exactly where it should ─────────────────────────────────────────────────────
def test_tail_spec_rides_weather_z_rows_only():
    specs = cq._node_specs(_node(), _WEATHER_ROW, "cocoa", "West Africa", _ERAS, asof="2026-08-22")
    tails = [s for s in specs if s["leg"][0] == "tail"]
    assert len(tails) == 1
    assert tails[0]["metric"] == "drought_z_tail_share"
    assert tails[0]["agg"] == "latest" and tails[0]["table"] == "gold_weather_z"

    frost_row = {**_WEATHER_ROW, "metric": "frost_event_flag"}
    assert all(s["leg"][0] != "tail" for s in
               cq._node_specs(_node(ref="frost"), frost_row, "cocoa", "West Africa", _ERAS,
                              asof="2026-08-22"))           # a flag has no tail sibling
    assert all(s["leg"][0] != "tail" for s in
               cq._node_specs(_node(ref="export"), _PSD_ROW, "cocoa", "Ghana", _ERAS,
                              asof="2026-08-22"))           # never on a non-weather table
    assert all(s["leg"][0] != "tail" for s in
               cq._node_specs(_node(), _WEATHER_ROW, "cocoa", "West Africa", _ERAS, asof=None))


# ── grouping: a tail record is quarantined from the era buckets, like pace ────────────────────────────
def test_group_by_node_quarantines_tail_records():
    kept = [{"specs": [{"node_key": ("cocoa", "drought")}], "row": _WEATHER_ROW}]
    recs = [{"node_key": ("cocoa", "drought"), "leg": ("tail", None), "status": "ok",
             "rows": [{"value": "0.18"}]}]
    grp = cq._group_by_node(recs, kept)[("cocoa", "drought")]
    assert grp["tail"] is recs[0] and grp["eras"] == {}


# ── the tail line: quotes the RAW share off a real record; silence renders nothing ───────────────────
def test_tail_legs_render_and_silence():
    kept = [{"specs": [{"node_key": ("cocoa", "drought")}], "row": _WEATHER_ROW}]
    ok = {"node_key": ("cocoa", "drought"), "leg": ("tail", None), "status": "ok",
          "rows": [{"value": "0.1818"}], "query": {"asof": "2026-08-22", "table": "gold_weather_z"}}
    calls: list = []
    lines, trace = cq._tail_legs([ok], kept, 7, calls)
    assert len(lines) == 1 and len(calls) == 1 and len(trace) == 1
    # the su_ratio normalizer: stored 0.1818 -> served "18.18 %" -- an ANALYST figure, value-checked
    # against the pre-scaled headline row (figures AND plain language, per the owner's word)
    assert "[N8]" in lines[0] and "18.18 %" in lines[0] and "0.1818" not in lines[0]
    # the line speaks the LABEL, never the slug (the _metric_display layer, owner's word)
    assert "share of the basin's cells at or beyond +2 sigma in drought z-score" in lines[0]
    assert "drought_z " not in lines[0]
    assert trace[0]["metric"] == "drought_z_tail_share"
    assert trace[0]["share"] == 0.1818                       # the trace keeps the raw stored fraction

    silent = {**ok, "status": "record_silent", "rows": []}
    lines2, trace2 = cq._tail_legs([silent], kept, 7, [])
    assert lines2 == [] and trace2 == []                     # honest absence: no line, no call, no trace


# ── the registry declares the basin metrics (undeclared metrics are refused at the query layer) ──────
def test_registry_declares_the_basin_metrics():
    from leviathan.graphrag.numbers.registry import load_registry
    ts = load_registry().get("gold_weather_z")
    for m in ("drought_z_tail_share", "heat_stress_z_tail_share", "gdd_z_tail_share",
              "tmax_anomaly_tail_share", "frost_event_share"):
        assert m in ts.metrics, m


# ── metric display labels: internal ids never reach prose (owner's word 2026-08-22) ──────────────────
def test_metric_display_resolves_the_card_label_and_falls_back():
    assert cq._metric_display(_WEATHER_ROW) == "drought z-score"          # labeled -> the analyst name
    assert cq._metric_display({"table": "silver_psd", "metric": "exports_mt"}) == "exports_mt"
    assert cq._metric_display({"table": "no_such_table", "metric": "x_y"}) == "x_y"   # never raises


def test_fmt_line_prints_the_label_never_the_slug():
    rec = {"query": {"commodity": "cocoa", "asof": "2026-08-22"},
           "rows": [{"value": "0.03"}], "status": "ok"}
    line = cq._fmt_line(rec, _WEATHER_ROW, 4, era="current")
    assert "drought z-score" in line and "drought_z" not in line


def test_internal_leaks_flags_labeled_slugs_only():
    from leviathan.graphrag import register as rg
    hits = rg.internal_leaks("The drought_z reading was benign.")
    assert any(tok == "drought_z" for tok, _ in hits)                     # labeled -> a leak is a bug
    hits2 = rg.internal_leaks("Exports rose sharply against exports_mt history.")
    assert not any(tok == "exports_mt" for tok, _ in hits2)               # unlabeled -> today's accepted state
    assert rg.internal_leaks("Drought stress stayed near normal in the basin.") == []
