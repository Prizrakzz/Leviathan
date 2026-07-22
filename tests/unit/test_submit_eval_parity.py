"""Unit tests for the submit_eval serving-parity guard (Lane L5, FIX 3).

Covers the PURE diff helper `parity_warnings` + the taskdef env extractor `_graphrag_env_from_taskdef`
+ the `_is_flag_on` value classifier, all without any real boto3 traffic. The guard exists because the
judged-30 submit omitted GRAPHRAG_REROUTE_V2=on, silently making the rv2 eval dimension vacuous while
prod serving (rev-50 taskdef) had the flag ON. `parity_warnings` flags serving-ON GRAPHRAG_* keys that
are ABSENT from the job env (advisory WARN only -- some divergence, e.g. session/provider env, is legit).

jobs/ is not an importable package (pytest pythonpath = ["src"] only), so we load the wrapper by file
path -- mirroring test_submit_evidence_wrappers.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SUBMIT_DIR = Path(__file__).resolve().parents[2] / "jobs" / "submit"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SUBMIT_DIR / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


se = _load("submit_eval")


# --- _is_flag_on ---------------------------------------------------------------------------------

def test_is_flag_on_truthy_values():
    for v in ("on", "1", "true", "yes", "ON", "  True ", "Yes"):
        assert se._is_flag_on(v), v


def test_is_flag_on_falsey_values():
    for v in ("off", "0", "false", "no", "", None, "maybe", "onish"):
        assert not se._is_flag_on(v), v


# --- _graphrag_env_from_taskdef ------------------------------------------------------------------

def test_graphrag_env_extract_filters_prefix_and_joins_containers():
    taskdef = {
        "containerDefinitions": [
            {"environment": [
                {"name": "GRAPHRAG_REROUTE_V2", "value": "on"},
                {"name": "AWS_REGION", "value": "us-east-1"},          # non-GRAPHRAG dropped
                {"name": "GRAPHRAG_CASCADE_QUANT", "value": "on"},
            ]},
            {"environment": [
                {"name": "GRAPHRAG_PROVIDER", "value": "bedrock"},
            ]},
        ]
    }
    assert se._graphrag_env_from_taskdef(taskdef) == {
        "GRAPHRAG_REROUTE_V2": "on",
        "GRAPHRAG_CASCADE_QUANT": "on",
        "GRAPHRAG_PROVIDER": "bedrock",
    }


def test_graphrag_env_extract_tolerates_missing_keys():
    assert se._graphrag_env_from_taskdef({}) == {}
    assert se._graphrag_env_from_taskdef({"containerDefinitions": [{}]}) == {}
    assert se._graphrag_env_from_taskdef({"containerDefinitions": [{"environment": None}]}) == {}


# --- parity_warnings (the load-bearing diff) -----------------------------------------------------

def test_parity_warnings_flags_serving_on_flag_absent_from_job():
    serving = {"GRAPHRAG_REROUTE_V2": "on", "GRAPHRAG_CASCADE_QUANT": "on"}
    job = {"GRAPHRAG_CASCADE_QUANT": "off"}                            # present (even if off) -> not flagged
    assert se.parity_warnings(serving, job) == ["GRAPHRAG_REROUTE_V2"]


def test_parity_warnings_ignores_serving_off_flags():
    # A serving flag that is OFF being absent from the job env is a non-issue (nothing to measure).
    serving = {"GRAPHRAG_REROUTE_V2": "off", "GRAPHRAG_EXPERIMENTAL": "0"}
    assert se.parity_warnings(serving, {}) == []


def test_parity_warnings_present_key_never_flagged_regardless_of_value():
    serving = {"GRAPHRAG_REROUTE_V2": "on"}
    assert se.parity_warnings(serving, {"GRAPHRAG_REROUTE_V2": "on"}) == []
    assert se.parity_warnings(serving, {"GRAPHRAG_REROUTE_V2": "off"}) == []   # divergence != absence


def test_parity_warnings_only_graphrag_prefix():
    serving = {"SOME_OTHER_FLAG": "on", "GRAPHRAG_REROUTE_V2": "on"}
    assert se.parity_warnings(serving, {}) == ["GRAPHRAG_REROUTE_V2"]


def test_parity_warnings_sorted_and_multiple():
    serving = {"GRAPHRAG_ZED": "on", "GRAPHRAG_ALPHA": "on", "GRAPHRAG_MID": "off"}
    assert se.parity_warnings(serving, {}) == ["GRAPHRAG_ALPHA", "GRAPHRAG_ZED"]


def test_parity_warnings_empty_when_serving_env_empty():
    # describe failure yields {} -> no warnings, guard is silent.
    assert se.parity_warnings({}, {"GRAPHRAG_REROUTE_V2": "on"}) == []


def test_default_job_env_ships_reroute_v2_on():
    # Regression: the whole point of FIX 3(a) -- rv2 must be defaulted ON in the submitted job env.
    assert se.DEFAULT_JOB_ENV.get("GRAPHRAG_REROUTE_V2") == "on"
