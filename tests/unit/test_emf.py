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
