"""The board's TRANSFORM REGISTRY and its DERIVATION RECORD -- STATE ENGINE DESIGN sec 2.5, sitting S1.

The four lint clauses of sec 2.5 are the four sections below: no banned name and a wired signature; a
declared window on every windowed figure; every derivation RE-EXECUTES to the same result; and
``stats.STAT_REGISTRY`` -- the agent's tool enum -- untouched.
"""
import pytest
from leviathan.graphrag.numbers import stats as st
from leviathan.graphrag.state import transforms as TR


@pytest.fixture()
def bundle():
    return {
        "oni|_global|": {"values": [0.2, 0.4, 0.1, -0.3, 0.6, 0.9, 1.2, 1.4, 1.7, 1.9],
                         "dates": ["2025-%02d" % m for m in range(1, 11)], "unit": "degC"},
        "flag|us|": {"values": [0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
                     "dates": ["2025-%02d" % m for m in range(1, 11)], "unit": "flag"},
    }


# ── clause 1 + the wiring ────────────────────────────────────────────────────────────────────────────
def test_the_registry_lints_clean():
    assert TR.lint_registry() == []


def test_every_transform_is_a_stats_call_and_this_module_defines_no_stat():
    """The design's own sentence: ``state/transforms.py`` defines NO stat function. A leaf declared here
    instead of in stats.py would be the second calculator sec 1.6 refuses in the same breath it refuses
    two z producers."""
    import inspect
    src = inspect.getsource(TR)
    assert "\ndef " in src
    for name, spec in TR.TRANSFORM_REGISTRY.items():
        assert spec.fn() is getattr(st, spec.stat)
    module_fns = {n for n, o in vars(TR).items()
                  if inspect.isfunction(o) and not n.startswith("_") and o.__module__ == TR.__name__}
    # the module's own public functions are the RUNNER, the RENDERER and the NULL BOUNDARY -- never a
    # calculation. The boundary (`num_or_none` / `date_or_none` / `is_null_token` / `cell_kind` /
    # `align_axis` / `clean_pairs` / `dated_pairs` and their counted twins) is the S4 null fix: it
    # decides whether a served cell carries a READING at all, WHICH KIND of hole it is when it does not,
    # and how the period axis is made parallel to the values. A cell with no reading leaves the array as
    # a hole. That is a coercion, an admission test and an alignment; it computes no statistic, which is
    # what the clause is about, and the two asserts below hold the line by NAME.
    boundary = {"is_null_token", "num_or_none", "date_or_none", "cell_kind", "align_axis",
                "clean_pairs", "clean_pairs_counted", "dated_pairs", "dated_pairs_counted"}
    assert module_fns == {"run_transform", "re_execute", "re_execute_all", "render_params",
                          "params_hash", "lint_registry"} | boundary
    # the boundary is not a second calculator: it names no stat and it widens no registry
    assert not (boundary & set(st.STAT_REGISTRY))
    assert not (boundary & {s.stat for s in TR.TRANSFORM_REGISTRY.values()})


def test_an_unknown_transform_and_an_unknown_parameter_are_both_loud(bundle):
    with pytest.raises(KeyError):
        TR.run_transform("regress", bundle, key="oni|_global|")
    with pytest.raises(ValueError):
        TR.run_transform("zscore", bundle, key="oni|_global|", params={"windwo": 8})
    with pytest.raises(KeyError):
        TR.run_transform("zscore", bundle, key="absent", params={"window": 8})


# ── clause 2: every windowed figure names its window ─────────────────────────────────────────────────
def test_every_windowed_transform_declares_which_parameter_names_its_window():
    windowed = {"zscore", "rolling_zscore", "rolling_corr", "window_change", "yoy_delta",
                "flag_events", "pace_vs_prior"}
    for name in windowed:
        spec = TR.TRANSFORM_REGISTRY[name]
        assert spec.window_param, f"{name} measures over a window and must name it"
        assert spec.window_param in spec.params


def test_render_params_prints_the_parameters_and_omits_the_unset(bundle):
    _, rec = TR.run_transform("window_change", bundle, key="oni|_global|",
                              params={"t1": -5, "t2": -1, "window_label": "4 weeks"})
    line = TR.render_params(rec)
    assert line == "window_change(t1=-5, t2=-1, window_label=4 weeks)"
    _, rec2 = TR.run_transform("percentile", bundle, key="oni|_global|")
    assert TR.render_params(rec2) == "percentile"          # no parameters, no empty parentheses
    assert line.encode("ascii")                            # ASCII-only, by law


# ── clause 3: the derivation record RE-EXECUTES ──────────────────────────────────────────────────────
def test_the_record_carries_the_designs_four_keys_and_references_its_inputs_by_key(bundle):
    out, rec = TR.run_transform("zscore", bundle, key="oni|_global|", params={"window": 8})
    assert set(rec) >= {"transform", "params", "n", "inputs"}
    assert rec["transform"] == "zscore" and rec["params"] == {"window": 8}
    assert rec["inputs"] == [{"arg": "value", "key": "oni|_global|", "select": "last"},
                             {"arg": "history", "key": "oni|_global|", "select": "values"}]
    # the record holds REFERENCES, never the values themselves
    assert all(isinstance(i["key"], str) for i in rec["inputs"])
    assert out["declined"] is False


def test_every_derivation_re_executes_to_the_same_result(bundle):
    recs = []
    for name, params in [("zscore", {"window": 8}), ("percentile", {}),
                         ("streak", {"direction": "up"}),
                         ("window_change", {"t1": -4, "t2": -1, "window_label": "3 months"}),
                         ("rolling_zscore", {"window": 8}),
                         ("regime_flag", {"kind": "abs_bands", "bands": [0.5, 1.0, 1.5],
                                          "labels": ["elevated", "moderate", "strong"]})]:
        _, rec = TR.run_transform(name, bundle, key="oni|_global|", params=params)
        recs.append(rec)
    _, frec = TR.run_transform("flag_events", bundle, key="flag|us|", params={"window_periods": 6})
    recs.append(frec)
    assert TR.re_execute_all(recs, bundle) == []


def test_a_DECLINE_re_executes_as_the_same_decline(bundle):
    """A window that "could not be measured" on one pass and could on the next would be a
    nondeterminism nobody would ever see, so the decline is part of the reproducible result."""
    _, rec = TR.run_transform("zscore", bundle, key="oni|_global|", params={"window": 250})
    assert rec["_result"]["declined"] is True
    assert TR.re_execute_all([rec], bundle) == []


def test_re_execution_against_DIFFERENT_rows_is_reported_not_swallowed(bundle):
    _, rec = TR.run_transform("percentile", bundle, key="oni|_global|")
    tampered = {**bundle, "oni|_global|": {**bundle["oni|_global|"],
                                           "values": [9.0] * 10}}
    problems = TR.re_execute_all([rec], tampered)
    assert problems and "re-executed to a different result" in problems[0]


# ── the memo-key term ────────────────────────────────────────────────────────────────────────────────
def test_the_params_hash_separates_two_windows_of_one_series(bundle):
    """A z over 250 sessions and a z over 504 days are two states of ONE series. Without this term the
    memo -- IMMORTAL on a historical as-of -- would serve the first to a caller that asked for the
    second, silently and forever."""
    _, a = TR.run_transform("zscore", bundle, key="oni|_global|", params={"window": 8})
    _, b = TR.run_transform("zscore", bundle, key="oni|_global|", params={"window": 10})
    assert TR.params_hash([a]) != TR.params_hash([b])
    # ORDER-INDEPENDENT: the same set of transforms in another order is the same state
    _, c = TR.run_transform("percentile", bundle, key="oni|_global|")
    assert TR.params_hash([a, c]) == TR.params_hash([c, a])
    assert len(TR.params_hash([a])) == 16


# ── clause 4: the agent's tool enum is not this registry's to widen ──────────────────────────────────
def test_the_agent_tool_enum_is_untouched():
    assert tuple(sorted(st.STAT_REGISTRY)) == tuple(sorted(TR.FROZEN_STAT_REGISTRY))
    for name in ("regime_flag", "flag_events", "pace_vs_prior", "rolling_zscore"):
        assert name in TR.TRANSFORM_NAMES
        assert name not in st.STAT_REGISTRY
