"""IOD re-baseline gate -- unit tests for the PURE logic (ADR_IOD_SOURCE_SWITCH Section 5).

Everything here runs on synthetic frames: no S3, no boto3, no network. What is pinned is the
arithmetic the gate exists to assert, on the exact shapes the ADR ratified:

  * the key-delta math -- drop 960 pre-1950, restate 904, add >= 14 forward, latest >= 2026-06 --
    and each way it can be violated (short tail, a hole at/after 1950, a mis-pointed uri that
    hands the gate the SAME object twice, a non-forward "added" key);
  * the "no NAMED analogue lost" assertion (1961/1994/1997/2006/2012/2019 with non-null Sep-Nov),
    which is the load-bearing justification for accepting the pre-1950 loss;
  * the divergence contract -- bias/MAE/RMS/corr computed ours-minus-candidate, and the fact that
    ONLY corr gates (a ratified material divergence must not fail the gate that certifies it);
  * the phase-reclassification tally, the value-population floor, and the ASCII-only report.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "iod_rebaseline_gate", _REPO / "scripts" / "silver" / "iod_rebaseline_gate.py")
    mod = importlib.util.module_from_spec(spec)
    # register BEFORE exec: @dataclass resolves annotations through sys.modules[cls.__module__]
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


# ---------------------------------------------------------------------------
# synthetic frames
# ---------------------------------------------------------------------------
def _months(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Inclusive monthly key range."""
    (y0, m0), (y1, m1) = start, end
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _base_value(key) -> float:
    """Deterministic DMI-ish value keyed on (year, month) -- NOT on row index, so the frozen and
    shadow frames line up in time on the overlap the way two SST bases of the same index do."""
    t = key[0] * 12 + key[1]
    return round(0.6 * math.sin(t / 9.0) + 0.2 * math.cos(t / 31.0), 4)


def _basis_shift(key) -> float:
    """A stand-in for the ERSSTv5-vs-HadISST basis divergence: material (MAE ~0.1, phase flips at
    the band edges) but strongly correlated -- exactly the shape the ADR ratified."""
    t = key[0] * 12 + key[1]
    return round(0.18 * math.sin(t / 4.0), 4)


def _frame(keys, values=None, source="cpc_iodmi") -> pd.DataFrame:
    """A minimal silver_noaa_iod-shaped frame (the columns the gate reads)."""
    if values is None:
        values = [_base_value(k) for k in keys]
    df = pd.DataFrame({
        "year": [k[0] for k in keys],
        "month": [k[1] for k in keys],
        "dmi_value": list(values),
    })
    df["iod_dmi_3month_avg"] = df["dmi_value"].rolling(3, min_periods=2).mean().round(4)
    df["iod_phase"] = df["dmi_value"].map(gate._band)
    df["source"] = source
    return df


_FROZEN_KEYS = _months((1870, 1), (2025, 4))      # 1864 real HadISST keys
_SHADOW_KEYS = _months((1950, 1), (2026, 6))      # 918 CPC ERSSTv5 keys


def _frozen() -> pd.DataFrame:
    return _frame(_FROZEN_KEYS, source="noaa_iod")


def _shadow(keys=None) -> pd.DataFrame:
    ks = keys if keys is not None else _SHADOW_KEYS
    return _frame(ks, [round(_base_value(k) + _basis_shift(k), 4) for k in ks])


# ---------------------------------------------------------------------------
# (a) key-delta math
# ---------------------------------------------------------------------------
def test_key_delta_matches_the_adr_arithmetic():
    d = gate.key_delta(_FROZEN_KEYS, _SHADOW_KEYS)
    assert len(d.frozen_keys) == 1864
    assert len(d.shadow_keys) == 918
    assert len(d.dropped) == gate.EXPECT_DROPPED == 960
    assert len(d.restated) == gate.EXPECT_RESTATED == 904
    assert len(d.added) == 14                       # 2025-05 .. 2026-06 at ratification
    assert d.dropped[0] == (1870, 1) and d.dropped[-1] == (1949, 12)
    assert d.added[0] == (2025, 5) and d.added[-1] == (2026, 6)
    assert d.latest_shadow_key == (2026, 6)
    assert gate.check_key_delta(d) == []


def test_key_delta_added_count_is_a_floor_not_an_equality():
    """CPC publishes monthly, so the forward block GROWS -- 6 extra months must still pass."""
    d = gate.key_delta(_FROZEN_KEYS, _months((1950, 1), (2026, 12)))
    assert len(d.added) == 20
    assert gate.check_key_delta(d) == []


def test_key_delta_fails_on_a_short_forward_tail():
    """A shadow built from a stale CPC file: 13 forward months, latest 2026-05."""
    d = gate.key_delta(_FROZEN_KEYS, _months((1950, 1), (2026, 5)))
    fails = gate.check_key_delta(d)
    assert len(fails) == 2, fails
    assert any("forward keys added = 13" in f for f in fails)
    assert any("latest served key = 2026-05" in f for f in fails)


def test_key_delta_fails_on_a_hole_at_or_after_the_cutover():
    """A dropped key at/after 1950 is a HOLE in the new series, not the sanctioned pre-1950 loss."""
    keys = [k for k in _SHADOW_KEYS if k != (1980, 5)]
    d = gate.key_delta(_FROZEN_KEYS, keys)
    fails = gate.check_key_delta(d)
    assert any("dropped key(s) at/after 1950" in f and "1980-05" in f for f in fails), fails
    assert any("dropped keys = 961" in f for f in fails), fails
    assert any("restated (overlap) keys = 903" in f for f in fails), fails


def test_key_delta_fails_when_both_uris_point_at_the_same_object():
    """The mis-pointed-arg footgun: gating the frozen object against itself drops/adds nothing."""
    d = gate.key_delta(_FROZEN_KEYS, _FROZEN_KEYS)
    fails = gate.check_key_delta(d)
    assert any("dropped keys = 0" in f for f in fails), fails
    assert any("forward keys added = 0" in f for f in fails), fails
    assert any("latest served key = 2025-04" in f for f in fails), fails


def test_key_delta_fails_on_a_backfilled_added_key():
    """An 'added' key BEHIND the frozen tail means the two series are not aligned in time."""
    d = gate.key_delta(_months((1950, 1), (2025, 4)), _months((1949, 1), (2026, 6)))
    fails = gate.check_key_delta(d)
    assert any("are NOT forward of the frozen tail 2025-04" in f and "1949-01" in f
               for f in fails), fails


def test_check_unique_keys_catches_a_duplicated_natural_key():
    df = _shadow()
    dupe = pd.concat([df, df.iloc[[10]]], ignore_index=True)
    assert gate.check_unique_keys(df, "shadow") == []
    fails = gate.check_unique_keys(dupe, "shadow")
    assert len(fails) == 1 and "duplicated (year, month)" in fails[0]


# ---------------------------------------------------------------------------
# (b) divergence -- recorded, corr-gated only
# ---------------------------------------------------------------------------
def test_divergence_stats_on_a_known_offset():
    """shadow = frozen - 0.1 over the overlap => bias (ours - candidate) = +0.1, MAE = RMS = 0.1,
    corr = 1.0. Sign convention pinned: the ADR tables are ours-minus-candidate."""
    keys = _months((2000, 1), (2009, 12))
    vals = [round(0.4 * ((i % 5) - 2), 4) for i in range(len(keys))]
    frozen = _frame(keys, vals, source="noaa_iod")
    shadow = _frame(keys, [round(v - 0.1, 4) for v in vals])
    d = gate.divergence(frozen, shadow)
    assert d["n"] == 120
    assert d["bias"] == pytest.approx(0.1, abs=1e-9)
    assert d["mae"] == pytest.approx(0.1, abs=1e-9)
    assert d["rms"] == pytest.approx(0.1, abs=1e-9)
    assert d["corr"] == pytest.approx(1.0, abs=1e-9)
    assert d["worst_abs_diff"] == pytest.approx(0.1, abs=1e-9)
    assert gate.check_divergence(d) == []


def test_divergence_ignores_months_where_either_side_is_null():
    keys = _months((2000, 1), (2000, 6))
    frozen = _frame(keys, [0.5, -0.5, 0.2, -0.2, 0.9, -0.9], source="noaa_iod")
    shadow = _frame(keys, [0.5, -0.5, 0.2, -0.2, None, None])
    d = gate.divergence(frozen, shadow)
    assert d["n"] == 4
    assert d["bias"] == pytest.approx(0.0, abs=1e-9)


def test_divergence_does_not_gate_on_a_material_bias_but_gates_on_corr():
    """A ratified material divergence must PASS (only corr gates); an anti-correlated series must
    FAIL -- that is a mis-pointed uri or a broken parse, not an SST-basis shift."""
    keys = _months((2000, 1), (2009, 12))
    vals = [round(0.4 * ((i % 5) - 2), 4) for i in range(len(keys))]
    big_shift = _frame(keys, [round(v - 0.6, 4) for v in vals])
    d = gate.divergence(_frame(keys, vals, source="noaa_iod"), big_shift)
    assert abs(d["bias"]) > 0.5 and d["mae"] > 0.5      # far worse than the ADR's ~0.22
    assert gate.check_divergence(d) == []               # ... and still not a gate failure

    flipped = _frame(keys, [round(-v, 4) for v in vals])
    d2 = gate.divergence(_frame(keys, vals, source="noaa_iod"), flipped)
    fails = gate.check_divergence(d2)
    assert len(fails) == 1 and "sanity floor" in fails[0]


def test_divergence_reports_no_overlap_as_a_failure():
    frozen = _frame(_months((1870, 1), (1900, 12)), source="noaa_iod")
    shadow = _frame(_months((1950, 1), (1960, 12)))
    d = gate.divergence(frozen, shadow)
    assert d["n"] == 0
    assert gate.check_divergence(d) == ["(b) divergence has no comparable months -- "
                                        "the two frames do not overlap"]


# ---------------------------------------------------------------------------
# (c) phase reclassification tally
# ---------------------------------------------------------------------------
def test_phase_reclassification_tallies_transitions_over_the_overlap():
    keys = _months((2000, 1), (2000, 4))
    frozen = _frame(keys, [0.9, -0.9, 0.0, 0.5], source="noaa_iod")
    shadow = _frame(keys, [0.1, -0.9, 0.7, 0.5])
    ph = gate.phase_reclassification(frozen, shadow)
    assert ph["n"] == 4
    assert ph["changed"] == 2
    assert ph["changed_frac"] == pytest.approx(0.5)
    assert ph["transitions"] == {"neutral->positive": 1, "positive->neutral": 1}
    assert ph["shadow_phase_mix"] == {"negative": 1, "neutral": 1, "positive": 2}


# ---------------------------------------------------------------------------
# (d) no NAMED analogue lost
# ---------------------------------------------------------------------------
def test_named_analogues_all_survive_on_a_complete_shadow():
    rep = gate.analogue_report(_shadow())
    assert sorted(rep) == ["1961", "1994", "1997", "2006", "2012", "2019"]
    assert all(rec["months_nonnull"] == [9, 10, 11] for rec in rep.values())
    assert gate.check_analogues(rep) == []


def test_named_analogue_lost_when_its_son_months_are_absent():
    keys = [k for k in _SHADOW_KEYS if not (k[0] == 1994 and k[1] in (9, 10, 11))]
    fails = gate.check_analogues(gate.analogue_report(_shadow(keys)))
    assert len(fails) == 1
    assert "named analogue 1994 lost" in fails[0]
    assert "1994-09, 1994-10, 1994-11" in fails[0]


def test_named_analogue_lost_when_a_son_value_is_null():
    """Present-but-NaN is the sneaky case: the key exists, the analogue does not."""
    df = _shadow()
    df.loc[(df["year"] == 2019) & (df["month"] == 10), "dmi_value"] = None
    rep = gate.analogue_report(df)
    assert rep["2019"]["months_nonnull"] == [9, 11]
    assert rep["2019"]["missing_months"] == [10]
    fails = gate.check_analogues(rep)
    assert len(fails) == 1 and "2019-10" in fails[0]


def test_analogue_son_peak_is_the_max_over_the_window():
    keys = _months((1997, 1), (1997, 12))
    vals = [0.0] * 12
    vals[8], vals[9], vals[10] = 0.74, 0.99, 1.55      # ADR Section 3.1 ERSSTv5 1997 SON
    rep = gate.analogue_report(_frame(keys, vals), years=(1997,))
    assert rep["1997"]["son_peak"] == pytest.approx(1.55)


def test_check_analogues_flags_an_omitted_named_year():
    rep = gate.analogue_report(_shadow(), years=(1997, 2019))
    fails = gate.check_analogues(rep)
    assert len(fails) == 1
    assert "omits named year(s): 1961, 1994, 2006, 2012" in fails[0]


# ---------------------------------------------------------------------------
# (e) value-population floor
# ---------------------------------------------------------------------------
def test_value_population_floor_boundary():
    keys = _months((2000, 1), (2008, 4))            # 100 served keys
    vals = [0.3] * 99 + [None]                      # exactly 0.99
    pop = gate.value_population(_frame(keys, vals))
    assert pop["dmi_value"] == {"nonnull": 99, "total": 100, "frac": 0.99}
    assert gate.check_value_population(pop) == []

    pop2 = gate.value_population(_frame(keys, [0.3] * 98 + [None, None]))
    fails = gate.check_value_population(pop2)
    assert len(fails) == 1 and "0.9800 < floor 0.99" in fails[0]


def test_value_population_refuses_an_empty_frame():
    empty = _frame([]).astype({"year": "int64", "month": "int64"})
    fails = gate.check_value_population(gate.value_population(empty))
    assert len(fails) == 1 and "EMPTY" in fails[0]


# ---------------------------------------------------------------------------
# evaluate() + the report
# ---------------------------------------------------------------------------
def test_evaluate_passes_on_an_adr_shaped_pair_and_the_report_is_ascii():
    art = gate.evaluate(_shadow(), _frozen(), shadow_uri="s3://b/_shadow/p.parquet",
                        frozen_uri="s3://b/p.parquet")
    assert art["verdict"] == "PASS"
    assert art["failures"] == []
    assert art["key_delta"]["dropped"] == 960
    assert art["key_delta"]["restated"] == 904
    assert art["key_delta"]["added"] == 14
    assert art["key_delta"]["shadow_last"] == "2026-06"
    assert art["shadow_source_stamps"] == ["cpc_iodmi"]
    assert art["frozen_source_stamps"] == ["noaa_iod"]

    report = gate.render_report(art)
    report.encode("ascii")                           # cp1252 console: non-ASCII must never appear
    assert "VERDICT: PASS" in report
    assert "no NAMED analogue lost" in report


def test_evaluate_fails_closed_and_lists_every_failure():
    """One frame, three simultaneous defects: short forward tail, a lost analogue, a thin column."""
    keys = [k for k in _months((1950, 1), (2026, 5)) if not (k[0] == 2012 and k[1] == 10)]
    df = _shadow(keys)
    df.loc[df.index[:40], "dmi_value"] = None
    art = gate.evaluate(df, _frozen())
    assert art["verdict"] == "FAIL"
    joined = " | ".join(art["failures"])
    assert "forward keys added = 13" in joined
    assert "named analogue 2012 lost" in joined
    assert "non-null frac" in joined
    report = gate.render_report(art)
    report.encode("ascii")
    assert "VERDICT: FAIL" in report and "FAILURES:" in report


def test_report_does_not_read_an_empty_shadow_as_a_fresh_one():
    """Regression: 'none' sorts above '2026-06' lexicographically -- the latest-key line must not
    print PASS for a zero-row shadow."""
    empty = _frame([]).astype({"year": "int64", "month": "int64"})
    art = gate.evaluate(empty, _frozen())
    assert art["verdict"] == "FAIL"
    line = [ln for ln in gate.render_report(art).splitlines() if "latest served key" in ln][0]
    assert "[FAIL]" in line


# ---------------------------------------------------------------------------
# uri handling / read-only posture
# ---------------------------------------------------------------------------
def test_split_s3_uri_rejects_non_s3():
    assert gate.split_s3_uri("s3://bucket/a/b.parquet") == ("bucket", "a/b.parquet")
    with pytest.raises(ValueError):
        gate.split_s3_uri("/local/path.parquet")


def test_readonly_client_refuses_a_mutating_method(monkeypatch):
    monkeypatch.setattr(gate._ReadOnlyClient, "__init__", lambda self, region: None)
    c = gate._ReadOnlyClient("us-east-1")
    with pytest.raises(RuntimeError, match="READ-ONLY"):
        _ = c.put_object
