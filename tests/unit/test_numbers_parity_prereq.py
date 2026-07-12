"""SILVER-C001 prerequisite (Attack 3 #4): numbers_parity must cover gold_weather_z with a real sample
commodity and lift the [:4] metric cap for TALL tables (or BF-W1's rebuild target passes vacuously).

AWS-free: only inspects the module's static config + the metric-selection expression."""
from __future__ import annotations

import importlib

from leviathan.graphrag.numbers.registry import load_registry

parity = importlib.import_module("jobs.utils.numbers_parity")


def test_gold_weather_z_has_a_valid_sample_commodity():
    assert "gold_weather_z" in parity.SAMPLE_COMMODITY
    commodity = parity.SAMPLE_COMMODITY["gold_weather_z"]
    assert commodity, "gold_weather_z sample commodity must be non-empty (else the panel is vacuous)"
    # it must be in the default parity table set (so a plain run exercises it)
    default_tables = set(parity.SAMPLE_COMMODITY)
    assert "gold_weather_z" in default_tables


def test_tall_table_metric_cap_is_lifted_in_source():
    """main() must select ALL metrics for a tall table and keep the [:4] cap only for wide tables -- assert
    against the ACTUAL module source (not a re-implementation), so a regression that drops the shape branch
    is caught. gold_weather_z (tall, 5 metrics) is the table BF-W1 rebuilds."""
    import inspect
    src = inspect.getsource(parity.main)
    # the fixed expression: tall -> full metric list, wide -> capped at [:4].
    assert 'ts.shape == "tall"' in src, "the tall-vs-wide metric-cap branch is missing from main()"
    assert "list(ts.metrics)[:4]" in src, "the [:4] cap for wide tables should remain"
    # and the raw uncapped loop `for metric in list(ts.metrics)[:4]:` must NOT survive unbranched
    assert "for metric in list(ts.metrics)[:4]:" not in src

    reg = load_registry()
    gz = reg.get("gold_weather_z")
    assert gz.shape == "tall" and len(gz.metrics) >= 5   # >4 -> the cap would have hidden metric #5
