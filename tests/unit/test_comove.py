"""SEAM A -- co-move (same-sign) quantified rendering (ENGINE_SEAMS_PLAN rev-52).

Lane SEAM-A. Pure/hermetic -- no AWS, no LLM, no pg. Drives cascade._reroute_xc / quantify on synthetic
da_by/db_by dicts (the sanctioned branch-split fixture) + hand-built out dicts. Covers: the two-pass split
([SKEPTIC F1] -- opposite-sign keeps absolute first-fire priority; same-sign renders only if no era diverges),
the flag-off/flag-on BYTE-IDENTITY guarantee for opposite-sign, the CO-MOVE marker -> '## Complex-wide move'
(never '## Cross-commodity'), the tightened/loosened SAFE verb, the trace discriminator routing to
quantify_comove ([SKEPTIC F3]), and the SAFEST-frame register clearance (0 fences).
"""
from __future__ import annotations

import types

import pytest
from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq


# ── fixtures / helpers ────────────────────────────────────────────────────────────────────────────────
def _pair(pair_id="soyoil_palm_vegoil", a="soybean_oil_cbot", b="malaysian_crude_palm_oil_cme",
          complex_name="vegoil_substitution", shared_event="soyoil_palm_premium"):
    """A minimal complex_map pair row (the lane-A interface), material + both legs world su_ratio sides."""
    return types.SimpleNamespace(
        id=pair_id, pair=(a, b), complex_name=complex_name, shared_event=shared_event,
        side_a={"contract": a, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        side_b={"contract": b, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        direction="opposing", focus_rule="query", materiality_tier="material")


def _entry(my0, p0, my1, p1, rd="2026-05-10"):
    """One _leg_world_deltas era entry: {'d': delta_pp, 'a': (my, pct, rd), 'b': (my, pct, rd)}."""
    return {"d": p1 - p0, "a": (my0, p0, rd), "b": (my1, p1, rd)}


def _patch_deltas(monkeypatch, by_slug: dict):
    """Stub _leg_world_deltas to return a synthetic per-era dict keyed by leg slug (the branch-split fixture --
    full control over era indices + signs with no _world_su_ratio / window plumbing)."""
    monkeypatch.setattr(cq, "_leg_world_deltas",
                        lambda qfn, slug, windows, asof: dict(by_slug.get(slug, {})))


_A = "soybean_oil_cbot"
_B = "malaysian_crude_palm_oil_cme"
_WINDOWS = [("2024-11-01", "2025-11-01")]      # opaque here: _leg_world_deltas is stubbed


def _run(monkeypatch, da, db, *, comove, base=0):
    _patch_deltas(monkeypatch, {_A: da, _B: db})
    calls: list = []
    lines, fired = cq._reroute_xc(_pair(), _A, _B, _WINDOWS, qfn=None, asof="2026-06-01",
                                  calls=calls, base=base, sg=None, comove=comove)
    return lines, fired, calls


# ── the branch split (same-sign renders; flat continues) ──────────────────────────────────────────────
def test_comove_same_sign_tightening_renders_when_flag_on(monkeypatch):
    # both tighten (su_ratio falls): soyoil 9.0->8.0 (-1.0), palm 11.0->9.5 (-1.5) -> a co-move.
    da = {0: _entry(2024, 9.0, 2025, 8.0)}
    db = {0: _entry(2024, 11.0, 2025, 9.5)}
    lines, fired, calls = _run(monkeypatch, da, db, comove=True)
    assert fired is not None
    assert fired["comove"] is True and "reroute_v2" not in fired
    assert fired["commodityA"] == _A and fired["commodityB"] == _B
    assert fired["dA"] == pytest.approx(-1.0) and fired["dB"] == pytest.approx(-1.5)
    assert fired["window"] == "MY2024-MY2025"
    body = "\n".join(lines)
    # the dedicated marker + heading -- NEVER the CROSS-COMMODITY/divergence one
    assert "CO-MOVE on su_ratio" in body and "## Complex-wide move" in body
    assert "CROSS-COMMODITY" not in body and "## Cross-commodity" not in body
    # SAFEST frame shape, labeled BY COMMODITY (the world-basis labels), su_ratio %->% + tightened
    assert "both world soybean oil and world malaysian crude palm oil tightened" in body
    assert "(stocks-to-use 9%->8% and 11%->9.5%)" in body
    assert "tightened" in body and "not a relative-value divergence" in body
    assert "labeled BY COMMODITY" in body
    # every narrated magnitude is injected (all-numbers guard): 3 rows per leg
    assert len(calls) == 6


def test_comove_same_sign_declines_when_flag_off(monkeypatch):
    # flag OFF -> same-sign eras drop exactly as the pre-co-move engine (byte-identical): nothing rendered.
    da = {0: _entry(2024, 9.0, 2025, 8.0)}
    db = {0: _entry(2024, 11.0, 2025, 9.5)}
    lines, fired, calls = _run(monkeypatch, da, db, comove=False)
    assert fired is None and lines == [] and calls == []


def test_comove_loosening_uses_loosened_verb(monkeypatch):
    # both loosen (su_ratio rises) -> the SAFE verb is 'loosened', not 'tightened'.
    da = {0: _entry(2024, 8.0, 2025, 9.0)}
    db = {0: _entry(2024, 11.0, 2025, 12.0)}
    lines, fired, _ = _run(monkeypatch, da, db, comove=True)
    body = "\n".join(lines)
    assert "loosened" in body and "tightened" not in body
    assert fired["comove"] is True


def test_comove_flat_leg_never_fires(monkeypatch):
    # sign(dB) == 0 (palm unchanged) -> neither divergence nor co-move -> honest decline even with flag on.
    da = {0: _entry(2024, 9.0, 2025, 8.0)}
    db = {0: _entry(2024, 12.0, 2025, 12.0)}
    lines, fired, calls = _run(monkeypatch, da, db, comove=True)
    assert fired is None and lines == [] and calls == []


def test_comove_absent_intersection_leg_no_render(monkeypatch):
    """[SKEPTIC F2] The realizable NO-RENDER path: one leg is ABSENT from the era intersection (it has NO
    entry for that era), so set(da)&set(db) excludes it and the co-move never renders -- comove_fired stays
    false. This is the branch the negative deck pin exercises (intersection exclusion), not the sa==0 test."""
    da = {0: _entry(2024, 9.0, 2025, 8.0)}     # soyoil has era 0
    db = {1: _entry(2024, 11.0, 2025, 9.5)}    # palm has era 1 only -> intersection {0} & {1} == empty
    lines, fired, calls = _run(monkeypatch, da, db, comove=True)
    assert fired is None and lines == [] and calls == []


# ── [SKEPTIC F1] two-pass: opposite-sign keeps ABSOLUTE first-fire priority ────────────────────────────
def _opp_da_db():
    # soyoil tightens (-1.3), palm loosens (+1.6): opposing -> divergence.
    return {0: _entry(2024, 9.4, 2025, 8.1)}, {0: _entry(2024, 11.0, 2025, 12.6)}


def test_opposite_sign_byte_identical_flag_off_and_on(monkeypatch):
    """THE HARD TEST: an opposite-sign (divergence) render is byte-identical with GRAPHRAG_COMOVE off AND on --
    the co-move path can never suppress or alter a would-be divergence."""
    da, db = _opp_da_db()
    lines_off, fired_off, calls_off = _run(monkeypatch, da, db, comove=False)
    da, db = _opp_da_db()
    lines_on, fired_on, calls_on = _run(monkeypatch, da, db, comove=True)
    assert lines_off == lines_on                                   # byte-identical block
    assert fired_off == fired_on                                   # byte-identical trace dict
    assert calls_off == calls_on                                   # byte-identical injected rows
    # and it IS the divergence fork, not a co-move
    assert fired_on["reroute_v2"] is True and "comove" not in fired_on
    assert "CROSS-COMMODITY on su_ratio" in "\n".join(lines_on)


def test_lower_idx_comove_never_preempts_a_divergence(monkeypatch):
    """[SKEPTIC F1]: era 0 is a same-sign co-move, era 1 diverges. With the flag ON the divergence at era 1
    MUST fire (co-move never preempts) -- byte-identical to flag OFF."""
    da = {0: _entry(2024, 9.0, 2025, 8.0), 1: _entry(2015, 10.0, 2016, 8.7)}   # era1 soyoil tightens
    db = {0: _entry(2024, 11.0, 2025, 9.5), 1: _entry(2015, 12.0, 2016, 13.4)}  # era1 palm loosens
    lines_off, fired_off, calls_off = _run(monkeypatch, da, db, comove=False)
    lines_on, fired_on, calls_on = _run(monkeypatch, da, db, comove=True)
    assert lines_off == lines_on and fired_off == fired_on and calls_off == calls_on
    body = "\n".join(lines_on)
    assert "CROSS-COMMODITY on su_ratio" in body and "CO-MOVE" not in body   # divergence, not co-move
    assert fired_on["window"] == "MY2015-MY2016"                  # the era-1 divergence, not era-0 co-move


def test_first_same_sign_era_renders_when_no_divergence(monkeypatch):
    """Multi-era all same-sign (no divergence anywhere) -> the FIRST (lowest-idx) co-move renders."""
    da = {0: _entry(2024, 9.0, 2025, 8.0), 1: _entry(2015, 10.0, 2016, 9.2)}
    db = {0: _entry(2024, 11.0, 2025, 9.5), 1: _entry(2015, 12.0, 2016, 11.1)}
    lines, fired, _ = _run(monkeypatch, da, db, comove=True)
    assert fired is not None and fired["comove"] is True
    assert fired["window"] == "MY2024-MY2025"                     # era 0, the first same-sign co-move
    assert "## Complex-wide move" in "\n".join(lines)


# ── [SKEPTIC F3] the trace discriminator routes co-move to its OWN key ─────────────────────────────────
class _FakeSG:
    def __init__(self, nodes):
        self.nodes = nodes
        self.trace: dict = {}


class _FakeNode:
    def __init__(self, contract, dates):
        self.contract = contract
        self.id = contract + "_seed"
        self.prior = {}
        self.evidence = [{"event_date": d} for d in dates]


def _seam_groups(monkeypatch):
    """Give quantify one mapped-ref group so it reaches the xc seam (mirrors the rv2 engine test): a node
    with a psd_export ref + a stub map_row; qfn returns no numbers so the v1 body is inert."""
    monkeypatch.setattr(cq, "_silver_ref", lambda n: "psd_export")
    monkeypatch.setattr(cq, "map_row", lambda ref: {"table": "silver_psd", "metric": "exports_mt",
                                                    "period_type": "marketing_year", "agg": "latest",
                                                    "country_rule": "none"})


def _run_quantify_xc(monkeypatch, fired_dict):
    sg = _FakeSG([_FakeNode(_A, ["2020-05-01", "2020-06-01"])])
    _seam_groups(monkeypatch)
    monkeypatch.setattr(cq, "_run_xc", lambda *a, **k: (["- [N1] x"], fired_dict) if fired_dict else ([], None))
    cq.quantify(sg, None, qfn=lambda sql: [], asof="2026-06-01", near=None, extra_number_calls=[],
                xc_request={"pair_id": "p", "source_slug": _A, "target_slug": _B}, comove=True)
    return sg.trace


def test_comove_trace_routes_to_quantify_comove_key(monkeypatch):
    tr = _run_quantify_xc(monkeypatch, {"pair_id": "p", "comove": True})
    assert "quantify_comove" in tr and "quantify_reroute_v2" not in tr


def test_reroute_v2_trace_stays_on_its_own_key(monkeypatch):
    tr = _run_quantify_xc(monkeypatch, {"pair_id": "p", "reroute_v2": True})
    assert "quantify_reroute_v2" in tr and "quantify_comove" not in tr


def test_quantify_threads_comove_kwarg_into_run_xc(monkeypatch):
    """quantify passes its `comove` kwarg through to _run_xc (the [SKEPTIC F3] thread, no env read below)."""
    seen: dict = {}
    sg = _FakeSG([_FakeNode(_A, ["2020-05-01", "2020-06-01"])])
    _seam_groups(monkeypatch)
    monkeypatch.setattr(cq, "_run_xc", lambda *a, **k: seen.update(k) or ([], None))
    cq.quantify(sg, None, qfn=lambda sql: [], asof="2026-06-01", near=None, extra_number_calls=[],
                xc_request={"pair_id": "p", "source_slug": _A, "target_slug": _B}, comove=True)
    assert seen.get("comove") is True


def test_run_xc_defaults_comove_false(monkeypatch):
    """A legacy call (no comove kwarg) defaults to False -> same-sign eras drop (byte-identical rollback)."""
    _patch_deltas(monkeypatch, {_A: {0: _entry(2024, 9.0, 2025, 8.0)},
                                _B: {0: _entry(2024, 11.0, 2025, 9.5)}})
    monkeypatch.setattr(cq, "_load_pair_row", lambda pid: _pair())
    monkeypatch.setattr(cq, "_xc_focus_windows", lambda *a, **k: _WINDOWS)
    block, fired = cq._run_xc({"pair_id": "p", "source_slug": _A, "target_slug": _B},
                              None, None, [], None, "2026-06-01", None, [])
    assert block == [] and fired is None


# ── register: the SAFEST frame text passes 0 fences ───────────────────────────────────────────────────
def test_comove_frame_passes_zero_fences(monkeypatch):
    """The injected CO-MOVE block (per-leg [N] lines + the SAFEST-frame marker) trips NO valuation/flow fence
    -- su_ratio percentages + tightened/loosened only, no valuation adjective, no positioning/price-direction."""
    da = {0: _entry(2024, 9.0, 2025, 8.0)}
    db = {0: _entry(2024, 11.0, 2025, 9.5)}
    lines, _, _ = _run(monkeypatch, da, db, comove=True)
    body = "\n".join(lines)
    assert reg.count_valuation_words(body) == 0
    assert reg.count_flow_words(body) == 0
    # the loosening variant is equally clean (both SAFE verbs)
    lines2, _, _ = _run(monkeypatch, {0: _entry(2024, 8.0, 2025, 9.0)},
                        {0: _entry(2024, 11.0, 2025, 12.0)}, comove=True)
    body2 = "\n".join(lines2)
    assert reg.count_valuation_words(body2) == 0 and reg.count_flow_words(body2) == 0
