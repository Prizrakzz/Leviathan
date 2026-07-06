"""Display-name registry (6.1) — deterministic, no spend. Guards that internal ids resolve to official /
plain-English names, that the fallback is always readable (never a raw slug), and — the guarantee — that
EVERY convergence regime in the causal DAGs has a curated label so no internal id can leak to the reader.
"""
from __future__ import annotations

from leviathan.graphrag import display as dp


def test_source_name_maps_known_and_falls_back():
    assert dp.source_name("usda_gain_corn") == "USDA FAS GAIN Report — Corn"
    assert dp.source_name("wb_cmo_outlook") == "World Bank Commodity Markets Outlook"
    # unmapped id -> readable Title-Cased de-underscore, never a raw slug
    out = dp.source_name("some_new_source_id")
    assert out == "Some New Source ID" or "_" not in out
    # an already-official string (has spacing) is returned unchanged
    assert dp.source_name("USDA WASDE") == "USDA WASDE"


def test_table_label_maps_and_falls_back():
    assert dp.table_label("silver_noaa_oni") == "NOAA ONI"
    assert dp.table_label("silver_psd") == "USDA PSD"
    assert dp.table_label("silver_unknown_table") == "UNKNOWN TABLE"   # legacy strip+upper fallback


def test_regime_label_maps_and_infers_direction():
    assert dp.regime_label("bullish_drought_squeeze") == "drought squeeze (bullish)"
    # unmapped id -> strip prefix, de-underscore, infer direction from the prefix
    assert dp.regime_label("bullish_made_up_regime").endswith("(bullish)")
    assert dp.regime_label("bearish_made_up_regime").endswith("(bearish)")
    assert "made" in dp.regime_label("bullish_made_up_regime").lower()


def test_all_regime_ids_reads_causal_dir():
    ids = dp.all_regime_ids()
    assert "bullish_drought_squeeze" in ids and len(ids) > 30       # real regimes across the DAGs
    # longest-first so substitution never leaves a partial
    lens = [len(x) for x in ids]
    assert lens == sorted(lens, reverse=True)


def test_check_display_names_clean_every_regime_labelled():
    # the load-bearing guarantee: no causal regime lacks a label, no label is stale
    assert dp.check_display_names() == []


def test_curated_regime_set_matches_causal_exactly():
    curated = set(dp._regimes())
    causal = set(dp.all_regime_ids())
    assert curated == causal                                        # symmetric: no missing, no stale
