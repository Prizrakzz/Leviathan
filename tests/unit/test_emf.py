"""Stage 5.3 R3: CloudWatch EMF turn-metric emitter."""
from __future__ import annotations

import json

from leviathan.graphrag import emf


def _emit_and_parse(capsys, **kwargs) -> dict:
    emf.emit(**kwargs)
    out = capsys.readouterr().out.strip()
    return json.loads(out)


def test_emit_shape(capsys):
    doc = _emit_and_parse(
        capsys,
        metrics={"TurnLatencyMs": 45000, "StripCount": 2},
        dimensions={"intent": "reasoning", "model": "sonnet"},
        units={"TurnLatencyMs": "Milliseconds", "StripCount": "Count"},
    )
    assert doc["TurnLatencyMs"] == 45000 and doc["StripCount"] == 2
    assert doc["intent"] == "reasoning" and doc["model"] == "sonnet"         # dims duplicated as fields
    cw = doc["_aws"]["CloudWatchMetrics"][0]
    assert cw["Namespace"] == "Leviathan/Serving"
    names = {m["Name"] for m in cw["Metrics"]}
    assert names == {"TurnLatencyMs", "StripCount"}
    # both the (intent, model) set AND the empty aggregate set are emitted
    assert ["intent", "model"] in cw["Dimensions"] and [] in cw["Dimensions"]
    assert isinstance(doc["_aws"]["Timestamp"], int)


def test_none_metrics_and_dims_dropped(capsys):
    doc = _emit_and_parse(
        capsys,
        metrics={"TurnLatencyMs": 100, "MsFill": None},                      # None value dropped
        dimensions={"intent": "numbers", "model": None},                     # None dim dropped
    )
    assert "MsFill" not in doc and "model" not in doc
    names = {m["Name"] for m in doc["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert names == {"TurnLatencyMs"}


def test_all_metrics_none_emits_nothing(capsys):
    emf.emit(metrics={"MsFill": None}, dimensions={"intent": "x"})
    assert capsys.readouterr().out.strip() == ""


def test_emit_never_raises():
    # A non-serializable value must not blow up the caller (fail-open); default=str handles it.
    emf.emit(metrics={"TurnLatencyMs": 1}, dimensions={"intent": object()})


# ── D-LD Sitting-A: per-table usage (`NumbersTableTouched`) ─────────────────────────────────────────
def test_table_touch_block_shape(capsys):
    """THE BILL IS THE DESIGN. One record per card, namespace pinned, and the CALLER's dimension set is
    exactly ["table"] -- never the turn emitter's (intent, model, mode), whose cardinality R14 refused to
    multiply. The lane set and the fleet aggregate ride every record, as they do on every emit."""
    emf.emit_table_touches(["silver_psd", "gold_weather_z"])
    docs = [json.loads(ln) for ln in capsys.readouterr().out.strip().splitlines()]
    assert [d["table"] for d in docs] == ["silver_psd", "gold_weather_z"]
    for doc in docs:
        cw = doc["_aws"]["CloudWatchMetrics"][0]
        assert cw["Namespace"] == "Leviathan/Serving"
        assert [{"Name": emf.TABLE_TOUCH_METRIC, "Unit": "Count"}] == cw["Metrics"]
        assert doc[emf.TABLE_TOUCH_METRIC] == 1
        assert ["table"] in cw["Dimensions"] and [] in cw["Dimensions"]
        assert not any("intent" in s or "model" in s or "mode" in s for s in cw["Dimensions"])


def test_table_touch_is_silent_on_an_empty_or_absent_list(capsys):
    emf.emit_table_touches([])
    emf.emit_table_touches(None)
    emf.emit_table_touches(["", "   "])
    assert capsys.readouterr().out.strip() == ""


def test_table_touch_failure_never_propagates(monkeypatch):
    """An instrument must never break a turn -- and this one runs AFTER the answer is finished, so a
    raise here would cost a reader an answer that already exists."""
    def _boom(*_a, **_kw):
        raise RuntimeError("emit is down")
    monkeypatch.setattr(emf, "emit", _boom)
    emf.emit_table_touches(["silver_psd"])              # must not raise
    emf.emit_table_touches("not-a-list-of-ids")         # ...nor on a malformed input


def test_table_touch_dimension_values_are_bounded_by_the_registry(capsys):
    """Review wf_051e926a F1: the call list keeps errored calls, and an errored call's query.table is
    the model's RAW tool input -- so a hallucinated table name is user-mintable prompt text. A CloudWatch
    dimension value mints a billed custom metric, so the METRIC emits only ids the registry loads; the
    trace column (not this emitter) is where raw truth lives. F3 rides the same bound: a string input
    iterates char-wise, and no character is a card id, so a malformed input emits NOTHING -- pinned here
    with emit UNPATCHED, which the failure-never-propagates test cannot observe (its emit raises)."""
    emf.emit_table_touches(["silver_corn_prices_2024", "Silver_PSD", "silver_psd"])
    docs = [json.loads(ln) for ln in capsys.readouterr().out.strip().splitlines()]
    assert [d["table"] for d in docs] == ["silver_psd"]     # the two fakes emit nothing, casing included
    emf.emit_table_touches("silver_psd")                    # malformed non-list input
    assert capsys.readouterr().out.strip() == ""            # char-wise iteration finds no card id
