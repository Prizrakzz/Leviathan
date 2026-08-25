"""F0 lane telemetry (latency RCA 2026-07-25): the `source` + `rerank_backend` EMF dimensions.

The RCA's rank-1 root cause was invalidated by reading a `Leviathan/Serving` aggregate as USER latency when
~99.5% of its samples came from the AWS Batch eval harness -- a lane that reranks on the LOCAL bge
cross-encoder while production reranks on Bedrock Cohere, so no share measured on one transfers to the other.
These pins make that class of error impossible to repeat: every record names WHERE it ran and WHICH backend
scored it, both from closed slug sets, and the pre-existing per-(intent, model) series is left untouched.
No AWS, no LLM: emf.emit only prints.
"""
from __future__ import annotations

import json
import sys
import types

import pytest
from leviathan.graphrag import emf
from leviathan.graphrag import params as prm

_LANE_ENV = ("GRAPHRAG_TELEMETRY_SOURCE", "ECS_CONTAINER_METADATA_URI_V4", "ECS_CONTAINER_METADATA_URI",
             "AWS_BATCH_JOB_ID", "GRAPHRAG_RERANK_BACKEND")


@pytest.fixture(autouse=True)
def _clean_lane_env(monkeypatch):
    """Nothing leaks in from the runner's environment -- an unmarked laptop/pytest process is `local`."""
    for k in _LANE_ENV:
        monkeypatch.delenv(k, raising=False)


def _emit_and_parse(capsys, **kw) -> dict:
    emf.emit(**kw)
    return json.loads(capsys.readouterr().out.strip())


def _dim_sets(doc: dict) -> list[list[str]]:
    return doc["_aws"]["CloudWatchMetrics"][0]["Dimensions"]


# ── source derivation: one row per lane ─────────────────────────────────────────────────────────────
def test_serving_env_labels_source_serving_and_bedrock(capsys, monkeypatch):
    """Taskdef :64 shape: the ECS agent injects the task-metadata URI and the taskdef sets
    GRAPHRAG_RERANK_BACKEND=bedrock -> a production turn is labelled (serving, bedrock)."""
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4/abc")
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "bedrock")
    doc = _emit_and_parse(capsys, metrics={"TurnLatencyMs": 100_400},
                          dimensions={"intent": "hybrid", "model": "claude-sonnet-4-6"})
    assert doc["source"] == "serving" and doc["rerank_backend"] == "bedrock"


def test_ecs_metadata_v3_var_also_counts_as_serving(capsys, monkeypatch):
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI", "http://169.254.170.2/v3/abc")
    doc = _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1}, dimensions={"intent": "reasoning"})
    assert doc["source"] == "serving"


def test_batch_env_labels_source_batch_and_cohere(capsys, monkeypatch):
    """Batch jobdef shape: AWS_BATCH_JOB_ID present, NO rerank env -> the params default decides.

    HISTORY, because this pin flipped ON SCHEDULE and the old wording would read as a regression:
    finding S1's mechanism was the ABSENCE of `serving.retrieval.rerank_backend` from params, which
    made the code default `bge` what actually ran on the batch lane -- and that absence was pinned
    here. The 2026-08-25 owner ratification ("forget bge, focus on cohere api") put the key IN params
    (`cohere`), so the batch lane now resolves cohere by default and the label must say so -- the
    INVARIANT (the label reports what actually ran, params-resolved, not what an env var wished) is
    unchanged; only the resolved value moved with the config."""
    assert prm.get("serving.retrieval.rerank_backend", "__absent__") == "cohere"
    monkeypatch.setenv("AWS_BATCH_JOB_ID", "0115c188-2bae-4431-92f7-c2411ff0e0ca")
    doc = _emit_and_parse(capsys, metrics={"TurnLatencyMs": 213_454}, dimensions={"intent": "hybrid"})
    assert doc["source"] == "batch" and doc["rerank_backend"] == "cohere"


def test_batch_on_fargate_is_batch_not_serving(capsys, monkeypatch):
    """THE REAL Batch container shape, and the reason AWS_BATCH_JOB_ID is tested first.

    `leviathan-dev-queue-ondemand` runs on the FARGATE compute environment
    (leviathan-dev-fargate-ondemand), and a Fargate-backed Batch task is an ECS task -- the agent injects
    ECS_CONTAINER_METADATA_URI_V4 into it exactly as it does on the serving task. Checking the ECS var
    first labelled every non-eval Batch job (a latency probe, an in-VPC parity run) `serving`, i.e. it
    poisoned the one series F0 exists to keep clean, in the same direction as the mistake F0 is fixing."""
    monkeypatch.setenv("AWS_BATCH_JOB_ID", "7fabd82e-f5d5-48ef-9591-ef6027fab2d5")
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4/abc")
    doc = _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1}, dimensions={"intent": "hybrid"})
    assert doc["source"] == "batch"


def test_eval_harness_labels_source_eval(capsys, monkeypatch):
    """`python -m leviathan.graphrag.eval` (submit_eval's command) -> __main__ carries the module spec.
    The eval lane wins over the Batch label: it is the eval lane wherever it runs."""
    fake_main = types.SimpleNamespace(__spec__=types.SimpleNamespace(name="leviathan.graphrag.eval"))
    monkeypatch.setitem(sys.modules, "__main__", fake_main)
    monkeypatch.setenv("AWS_BATCH_JOB_ID", "39881431-2720-4685-ae34-53614e250a8a")
    doc = _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1}, dimensions={"intent": "hybrid"})
    assert doc["source"] == "eval"


def test_importing_eval_is_not_the_harness(capsys, monkeypatch):
    """A test or script that merely IMPORTS the eval module must not be labelled `eval` (only __main__'s
    own spec counts), else a serving turn in a process that touched eval would be mislabelled."""
    fake_main = types.SimpleNamespace(__spec__=types.SimpleNamespace(name="pytest"))
    monkeypatch.setitem(sys.modules, "__main__", fake_main)
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4/abc")
    doc = _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1}, dimensions={"intent": "hybrid"})
    assert doc["source"] == "serving"


def test_unmarked_process_is_local(capsys):
    doc = _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1}, dimensions={"intent": "hybrid"})
    assert doc["source"] == "local"


# ── cardinality discipline: closed slug sets ────────────────────────────────────────────────────────
def test_override_must_be_a_known_slug(capsys, monkeypatch):
    monkeypatch.setenv("GRAPHRAG_TELEMETRY_SOURCE", "batch")
    assert _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1})["source"] == "batch"
    monkeypatch.setenv("GRAPHRAG_TELEMETRY_SOURCE", "probe-run-2026-07-25")   # unknown -> derived, not minted
    assert _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1})["source"] == "local"


def test_unknown_rerank_backend_is_bounded(capsys, monkeypatch):
    """An arbitrary env value must never become a dimension value (billed per distinct combination)."""
    # D-MW-6 housekeeping: the fixture string must be genuinely OUTSIDE the closed set, or this test
    # silently becomes a passthrough pin the day that slug is added (it was checked against 'cohere').
    assert "some-new-reranker-v9" not in emf._RERANK_BACKENDS
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "some-new-reranker-v9")
    assert _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1})["rerank_backend"] == "other"


def test_cohere_is_a_first_class_lane_dim_not_other(capsys, monkeypatch):
    """D-MW-6: the NATIVE lane is a member of the closed set. Left out, every native-lane record would
    collapse to `other` -- and `other` is exactly where an unknown/typo'd backend lands, so the prod alarm
    feed could not tell the production reranker apart from a misconfiguration."""
    assert emf._RERANK_BACKENDS == ("bge", "bedrock", "cohere")     # closed set, cardinality-bounded
    monkeypatch.setenv("GRAPHRAG_RERANK_BACKEND", "cohere")
    doc = _emit_and_parse(capsys, metrics={"RerankRequests": 1, "RerankFallbacks": 0},
                          units={"RerankRequests": "Count", "RerankFallbacks": "Count"})
    assert doc["rerank_backend"] == "cohere" and doc["source"] == "local"
    assert ["source", "rerank_backend"] in _dim_sets(doc)           # the new rerank metrics ride lane dims


def test_rerank_backend_reads_rankers_resolution(capsys, monkeypatch):
    """ONE resolution path: emf reports whatever rankers._rerank_backend() says -- a second copy of the
    env>params>default precedence is how the two lanes drifted apart unnoticed."""
    from leviathan.graphrag import rankers as rk
    monkeypatch.setattr(rk, "_rerank_backend", lambda: "bedrock")
    assert _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1})["rerank_backend"] == "bedrock"


# ── dimension-set shape: the existing series is preserved ───────────────────────────────────────────
def test_lane_dims_are_their_own_set_and_intent_model_survives(capsys, monkeypatch):
    monkeypatch.setenv("AWS_BATCH_JOB_ID", "j-1")
    doc = _emit_and_parse(capsys, metrics={"TurnLatencyMs": 1, "StripCount": 0},
                          dimensions={"intent": "hybrid", "model": "m"},
                          units={"TurnLatencyMs": "Milliseconds"})
    sets = _dim_sets(doc)
    assert ["intent", "model"] in sets                       # the 5.2 dashboard series is untouched
    assert ["source", "rerank_backend"] in sets              # the new lane series
    assert [] in sets                                        # fleet aggregate
    assert len(sets) == 3
    assert "source" not in sets[sets.index(["intent", "model"])]   # never merged into the caller's set


def test_no_caller_dims_yields_lane_set_plus_aggregate(capsys):
    doc = _emit_and_parse(capsys, metrics={"MsRollup": 2_500}, units={"MsRollup": "Milliseconds"})
    assert _dim_sets(doc) == [["source", "rerank_backend"], []]     # deduped: no empty caller set twice
    assert doc["source"] == "local" and doc["MsRollup"] == 2_500


def test_lane_derivation_failure_never_costs_the_record(capsys, monkeypatch):
    """Fail-open ordering pin: if lane derivation itself raises, the metrics still emit (unlabelled)."""
    monkeypatch.setattr(emf, "_source", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    doc = _emit_and_parse(capsys, metrics={"TurnLatencyMs": 42}, dimensions={"intent": "hybrid"})
    assert doc["TurnLatencyMs"] == 42 and "source" not in doc
    assert _dim_sets(doc) == [["intent"], []]
