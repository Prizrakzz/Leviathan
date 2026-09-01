"""HORIZONTAL TRANSMISSION CHAIN v1 -- hermetic unit tests (TRANSMISSION_CHAIN_PLAN.md D1-D12).

Lane: transmission ENGINE core. Pure/hermetic -- no AWS, no LLM, no pg. Two layers:
  * REAL-PATH tests drive cq._transmission_legs over a SQL-text-keyed stub qfn, so every link rides the
    genuine _world_su_ratio -> _psd_component_rows -> fetch_window -> Q.run -> build_sql path (the prewarm and
    the memo are therefore measured, not asserted-by-fiat);
  * BRANCH-SPLIT tests stub _leg_world_deltas (the sanctioned test_comove fixture) for the sign forks that
    would otherwise need contrived balance sheets.

Coverage: loader schema + the fail-closed structural rules (D1) + the SHIPPED v1 catalog; first-fire selection
+ the RV2 fence (never volunteered) + the census gate; the fire path (divergence -> divergence) and the
FLAGSHIP shape (divergence -> co-move, the "reached soyoil, not yet meal" payoff); the crush hop rendering its
OBSERVED sign against a co_move HINT (the fold-pass HIGH finding); every decline path (root_not_grounded,
hop_dark, hop_thin, link_comove, degenerate, cap) with ZERO injected rows; the truncation handoff; the
transmission-scoped cap priced BEFORE any fetch; the two-phase prewarm -> verbatim-serial memo (ZERO repeat
SQL); D11 mutual exclusion in BOTH directions; and flag-off byte-identity at the quantify seam.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from leviathan.graphrag import register as reg
from leviathan.graphrag.numbers import cascade as cq

ASOF = "2026-02-15"
PALM = "malaysian_crude_palm_oil_cme"
SBO = "soybean_oil_cbot"
SBM = "soybean_meal_cbot"
RSO = "rapeseed_oil_zce"
WINDOWS = [("2024-11-01", "2025-11-01")]                       # every veg-oil/crush slug starts its MY in Oct

FLAGSHIP = {"id": "xmit_palm_soyoil_meal",
            "links": [{"pair_id": "soyoil_palm_vegoil", "source": PALM, "target": SBO, "nature": "divergence"},
                      {"pair_id": "soymeal_soyoil_crush", "source": SBO, "target": SBM, "nature": "co_move"}]}
CONTROL = {"id": "xmit_vegoil_triangle",
           "links": [{"pair_id": "soyoil_palm_vegoil", "source": SBO, "target": PALM, "nature": "divergence"},
                     {"pair_id": "palm_rapeoil_vegoil", "source": PALM, "target": RSO, "nature": "divergence"}]}

_COMPLEX = {"soyoil_palm_vegoil": ("vegoil_substitution", (SBO, PALM)),
            "palm_rapeoil_vegoil": ("vegoil_substitution", (PALM, RSO)),
            "soyoil_rapeoil_vegoil": ("vegoil_substitution", (SBO, RSO)),
            "soymeal_soyoil_crush": ("soy_crush", (SBM, SBO))}


# ── builders ────────────────────────────────────────────────────────────────────────────────────────
def _pair_row(pair_id):
    """The curated complex_map row for a pair id (the lane-A interface), material + both legs world su_ratio."""
    if pair_id not in _COMPLEX:
        return None
    cname, (a, b) = _COMPLEX[pair_id]
    return SimpleNamespace(
        id=pair_id, pair=(a, b), complex_name=cname, shared_event="e",
        side_a={"contract": a, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        side_b={"contract": b, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        direction="opposing", focus_rule="query", materiality_tier="material")


# Per-slug World balance sheets, LINEAR in the marketing year so the signs hold for ANY window the anchor
# derives: palm TIGHTENS (su_ratio falls), soyoil and meal LOOSEN (rise). => link PALM-SBO opposes
# (DIVERGENCE) and link SBO-SBM agrees (CO-MOVE) -- the probe-verified flagship shape (plan 6.1).
_STOCKS = {PALM: lambda my: 12.0 - (my - 2020), SBO: lambda my: 4.0 + (my - 2020),
           SBM: lambda my: 6.0 + 2.0 * (my - 2020), RSO: lambda my: 9.0 + 0.5 * (my - 2020)}


def _qfn_factory(seen: list, *, stocks=None, dark=()):
    """SQL-text-keyed PSD stub: one country row per (slug, MY, component) so the REAL _world_su_ratio
    arithmetic runs (per-country-latest + EU dedup + the stocks/use ratio). `dark` slugs return no rows."""
    st = stocks or _STOCKS

    def qfn(sql):
        seen.append(sql)
        m = re.search(r"leviathan_slug = '([^']+)'", sql)
        y = re.search(r"market_year = (\d+)", sql)
        if not m or not y or m.group(1) in dark or m.group(1) not in st:
            return []
        slug, my = m.group(1), int(y.group(1))
        value = st[slug](my) if "ending_stocks_mt AS value" in sql else 100.0
        return [{"value": str(value), "knowledge_date": "2026-01-20", "period": my, "country": "United States"}]
    return qfn


def _wire(monkeypatch, chains, *, realizable=True):
    monkeypatch.setattr(cq, "load_transmission_map", lambda: list(chains))
    monkeypatch.setattr(cq, "_load_pair_row", _pair_row)
    monkeypatch.setattr(cq, "_xmit_pair_realizable", lambda pid: realizable)


def _sg(seeds=(SBO,), nodes=()):
    return SimpleNamespace(seeds=list(seeds), nodes=list(nodes), trace={}, fired_regimes=[])


def _walk_node(contract):
    """A grounded walk node with DATED evidence and no mapped ref: it never enters `groups`, so the SEAM tests
    exercise the `_xc_focus_windows` FALLBACK (derive the one anchor from the source node itself)."""
    ev = [{"date": d, "source": "usda_gain", "source_key": f"k{i}", "text": "t", "event_date": None}
          for i, d in enumerate(("2024-11-05", "2024-12-10"))]
    return SimpleNamespace(contract=contract, id=f"{contract}_shock", prior={}, evidence=ev)


_NO_XC = object()                                                  # sentinel: `xc=None` must mean NO request


def _groups(source):
    return [{"commodity": source, "eras": WINDOWS}]


def _run(monkeypatch, chains, *, source=PALM, comove=True, chain_fired=False, xc=_NO_XC, realizable=True,
         qfn=None, seen=None, calls=None):
    _wire(monkeypatch, chains, realizable=realizable)
    seen = [] if seen is None else seen
    calls = [] if calls is None else calls
    req = {"pair_id": "soyoil_palm_vegoil", "source_slug": source, "target_slug": SBO} if xc is _NO_XC else xc
    lines, fired, decline = cq._transmission_legs(
        _sg(), SimpleNamespace(contracts={}), _groups(source), req, qfn or _qfn_factory(seen), ASOF, None,
        calls, comove=comove, chain_fired=chain_fired)
    return lines, fired, decline, calls, seen


def _patch_deltas(monkeypatch, by_slug: dict):
    monkeypatch.setattr(cq, "_leg_world_deltas",
                        lambda qfn, slug, windows, asof: dict(by_slug.get(slug, {})))


def _entry(my0, p0, my1, p1, rd="2026-01-20"):
    return {"d": p1 - p0, "a": (my0, p0, rd), "b": (my1, p1, rd)}


# ── loader: schema + the fail-closed structural rules (D1) ──────────────────────────────────────────
def test_load_transmission_map_absent_file_is_empty(monkeypatch, tmp_path):
    from leviathan.graphrag import extract as ex
    monkeypatch.setattr(ex, "_CFG", tmp_path)
    cq.load_transmission_map.cache_clear()
    assert cq.load_transmission_map() == []
    cq.load_transmission_map.cache_clear()


def test_load_transmission_map_skips_deferred_and_invalid_rows(monkeypatch, tmp_path):
    from leviathan.graphrag import extract as ex
    (tmp_path / "numbers").mkdir()
    (tmp_path / "numbers" / "transmission_map.yaml").write_text(
        "chains:\n"
        f"  - {{id: live, links: [{{pair_id: p1, source: {PALM}, target: {SBO}}},"
        f" {{pair_id: p2, source: {SBO}, target: {SBM}}}]}}\n"
        f"  - {{id: parked, deferred: true, links: [{{pair_id: p1, source: {PALM}, target: {SBO}}},"
        f" {{pair_id: p2, source: {SBO}, target: {SBM}}}]}}\n"
        f"  - {{id: one_link, links: [{{pair_id: p1, source: {PALM}, target: {SBO}}}]}}\n"
        f"  - {{id: broken_hub, links: [{{pair_id: p1, source: {PALM}, target: {SBO}}},"
        f" {{pair_id: p2, source: {RSO}, target: {SBM}}}]}}\n", encoding="utf-8")
    monkeypatch.setattr(ex, "_CFG", tmp_path)
    cq.load_transmission_map.cache_clear()
    assert [c["id"] for c in cq.load_transmission_map()] == ["live"]
    cq.load_transmission_map.cache_clear()


def test_transmission_row_rules_reject_drift():
    ok = {"id": "x", "links": [{"pair_id": "p1", "source": PALM, "target": SBO},
                               {"pair_id": "p2", "source": SBO, "target": SBM}]}
    assert cq._transmission_row_ok(ok)
    assert not cq._transmission_row_ok({"links": ok["links"]})                       # no id
    assert not cq._transmission_row_ok({"id": "x", "links": ok["links"][:1]})        # 1 link -> an RV2 pair
    deep = ok["links"] + [{"pair_id": "p3", "source": SBM, "target": RSO}]
    assert not cq._transmission_row_ok({"id": "x", "links": deep})                   # 3 links > depth cap 2
    assert cq.TRANSMISSION_DEPTH_CAP == 2
    loop = [{"pair_id": "p1", "source": PALM, "target": SBO},
            {"pair_id": "p2", "source": SBO, "target": PALM}]
    assert not cq._transmission_row_ok({"id": "x", "links": loop})                   # repeated node: not simple
    same = [{"pair_id": "p1", "source": PALM, "target": PALM},
            {"pair_id": "p2", "source": PALM, "target": SBM}]
    assert not cq._transmission_row_ok({"id": "x", "links": same})                   # source == target
    nopair = [{"source": PALM, "target": SBO}, {"pair_id": "p2", "source": SBO, "target": SBM}]
    assert not cq._transmission_row_ok({"id": "x", "links": nopair})                 # no pair_id


def test_shipped_v1_catalog_is_the_two_ratified_rows():
    """The CONTENT pin on the tracked config: exactly the flagship + the vegoil-triangle control (D1), each 2
    links, hub-continuous, and NO feed_grain / crush-only / 3-4 link row."""
    cq.load_transmission_map.cache_clear()
    rows = cq.load_transmission_map()
    assert [c["id"] for c in rows] == ["xmit_palm_soyoil_meal", "xmit_vegoil_triangle"]
    assert [[lk["pair_id"] for lk in c["links"]] for c in rows] == [
        ["soyoil_palm_vegoil", "soymeal_soyoil_crush"], ["soyoil_palm_vegoil", "palm_rapeoil_vegoil"]]
    assert [[lk["source"], lk["target"]] for lk in rows[0]["links"]] == [[PALM, SBO], [SBO, SBM]]
    assert [[lk["source"], lk["target"]] for lk in rows[1]["links"]] == [[SBO, PALM], [PALM, RSO]]
    assert all("corn" not in str(c) and "wheat" not in str(c) for c in rows)          # D3: no feed_grain
    assert all(len(c["links"]) == 2 for c in rows)


# ── FIRE: the flagship shape (divergence -> co-move) = the reached-not-yet payoff ────────────────────
def test_fire_flagship_divergence_then_comove(monkeypatch):
    lines, fired, decline, calls, seen = _run(monkeypatch, [FLAGSHIP])
    assert decline is None and fired is not None
    body = "\n".join(lines)
    # link 1 = a relative-value DIVERGENCE, link 2 = a complex-wide CO-MOVE, each under its own marker
    assert f"TRANSMISSION LINK 1/2: world malaysian crude palm oil -> world soybean oil" in body
    assert "TRANSMISSION LINK 2/2: world soybean oil -> world soybean meal" in body
    assert "CROSS-COMMODITY on su_ratio" in body and "CO-MOVE on su_ratio" in body
    assert "TRANSMISSION CHAIN world malaysian crude palm oil -> world soybean oil -> world soybean meal" in body
    assert "TRANSMISSION HANDOFF" not in body                     # a co-move on the LAST link leaves nothing
    # the trace records the map HINT next to the OBSERVED sign (D9: the hint never gates)
    assert fired["chain_id"] == "xmit_palm_soyoil_meal" and fired["focus"] == PALM
    assert [(e["link"], e["nature"], e["observed"], e["rendered"]) for e in fired["links"]] == [
        (1, "divergence", "divergence", "divergence"), (2, "co_move", "comove", "comove")]
    assert fired["stopped_at"] == 2 and fired["stop_reason"] == "link_comove"
    assert fired["n_rows"] == len(calls) == 12                    # 2 links x 2 legs x (endpoint+baseline+delta)
    assert all(c["rows"][0]["unit"] in ("%", "pp") for c in calls)


def test_fire_control_triangle_two_divergences(monkeypatch):
    """The ROBUST primary gate: the pure-vegoil triangle, nature-agnostic -- both links render and the chain
    runs to the end (no handoff, no stop)."""
    lines, fired, decline, calls, _ = _run(
        monkeypatch, [CONTROL], source=SBO,
        xc={"pair_id": "soyoil_palm_vegoil", "source_slug": SBO, "target_slug": PALM})
    assert decline is None and fired["chain_id"] == "xmit_vegoil_triangle"
    assert [e["rendered"] for e in fired["links"]] == ["divergence", "divergence"]
    assert "stopped_at" not in fired and "TRANSMISSION HANDOFF" not in "\n".join(lines)
    assert "\n".join(lines).count("CROSS-COMMODITY on su_ratio") == 2
    assert fired["n_rows"] == len(calls) == 12


def test_crush_link_renders_its_OBSERVED_divergence_against_a_comove_hint(monkeypatch):
    """The fold-pass HIGH finding, encoded: the map's `nature: co_move` is an EXPECTATION, not a gate. When the
    crush legs OPPOSE (a demand split -- SBO-SBM at MY2024->2025 in the real record) the link renders a full
    DIVERGENCE with the soy_crush demand frame, and the trace shows hint != observed."""
    stocks = dict(_STOCKS)
    stocks[SBM] = lambda my: 20.0 - 2.0 * (my - 2020)             # meal TIGHTENS while soyoil LOOSENS: oppose
    seen: list = []
    lines, fired, decline, calls, _ = _run(monkeypatch, [FLAGSHIP], qfn=_qfn_factory(seen, stocks=stocks))
    assert decline is None
    assert [(e["nature"], e["observed"]) for e in fired["links"]][1] == ("co_move", "divergence")
    assert "\n".join(lines).count("CROSS-COMMODITY on su_ratio") == 2
    assert "the crush shifted toward one product on DEMAND" in "\n".join(lines)
    assert "stopped_at" not in fired                              # both links quantified, chain ran to the end


def test_comove_at_the_first_hub_truncates_with_an_honest_handoff(monkeypatch):
    """D4: a co-move at ANY hub ends the DIVERGENCE chain -- the co-move still renders, the downstream link is
    a narrative handoff, and nothing downstream is imputed."""
    stocks = dict(_STOCKS)
    stocks[PALM] = lambda my: 3.0 + (my - 2020)                   # palm now LOOSENS with soyoil -> link 1 agrees
    lines, fired, decline, calls, _ = _run(monkeypatch, [FLAGSHIP], qfn=_qfn_factory([], stocks=stocks))
    body = "\n".join(lines)
    assert decline is None and [e["rendered"] for e in fired["links"]] == ["comove"]
    assert fired["stopped_at"] == 1 and fired["stop_reason"] == "link_comove"
    assert "CO-MOVE on su_ratio" in body and "CROSS-COMMODITY" not in body
    assert ("TRANSMISSION HANDOFF at link 2/2 (world soybean oil -> world soybean meal): that link is a "
            "same-sign complex-wide move") in body
    assert "TRANSMISSION CHAIN world malaysian crude palm oil -> world soybean oil over" in body   # span only
    assert fired["n_rows"] == len(calls) == 6                     # ONE link's rows, never the un-rendered one


def test_dark_downstream_link_truncates_and_still_fires(monkeypatch):
    """2.4: the rendered upstream STAYS; the dark downstream becomes prose. THIS is the reached-not-yet payoff,
    not a decline -- the chain fires with one quantified link + the honest handoff."""
    seen: list = []
    lines, fired, decline, calls, _ = _run(monkeypatch, [FLAGSHIP],
                                           qfn=_qfn_factory(seen, dark=(SBM,)))
    body = "\n".join(lines)
    assert decline is None and fired["stop_reason"] == "hop_dark" and fired["stopped_at"] == 2
    assert [e["rendered"] for e in fired["links"]] == ["divergence", "truncated"]
    assert "TRANSMISSION HANDOFF at link 2/2" in body and "no resolved World stocks-to-use pair" in body
    assert fired["n_rows"] == len(calls) == 6


# ── DECLINE paths: reasoned, bounded, and ZERO injected rows ────────────────────────────────────────
def test_no_xc_request_is_no_attempt_zero_trace(monkeypatch):
    """The RV2 fence: the fork is NEVER volunteered. No cross-commodity ask -> no attempt, BOTH keys absent."""
    lines, fired, decline, calls, seen = _run(monkeypatch, [FLAGSHIP], xc=None)
    assert (lines, fired, decline, calls, seen) == ([], None, None, [], [])


def test_focus_without_a_curated_row_is_no_attempt(monkeypatch):
    lines, fired, decline, calls, seen = _run(
        monkeypatch, [FLAGSHIP], source=RSO,
        xc={"pair_id": "soyoil_rapeoil_vegoil", "source_slug": RSO, "target_slug": SBO})
    assert (lines, fired, decline) == ([], None, None) and calls == [] and seen == []


def test_census_unrealizable_link_declines_before_any_fetch(monkeypatch):
    lines, fired, decline, calls, seen = _run(monkeypatch, [FLAGSHIP], realizable=False)
    assert (lines, fired, decline) == ([], None, None) and calls == [] and seen == []


def test_real_census_gate_fails_closed_without_pg(monkeypatch):
    """cascade_census.pair_realizable returns None off pg -> the link is NOT realizable (fail closed)."""
    from leviathan.graphrag.numbers import cascade_census as cc
    monkeypatch.setattr(cc, "pair_realizable", lambda pid: None)
    assert cq._xmit_pair_realizable("soyoil_palm_vegoil") is False
    monkeypatch.setattr(cc, "pair_realizable", lambda pid: True)
    assert cq._xmit_pair_realizable("soyoil_palm_vegoil") is True


def test_sides_drift_declines_the_whole_chain(monkeypatch):
    """_xc_sides_ok is the fail-closed leg guard: a link whose curated pair does not carry EXACTLY its two
    legs never fires -- no guessed comparison."""
    drift = {"id": "x", "links": [{"pair_id": "soyoil_palm_vegoil", "source": PALM, "target": SBM},
                                  {"pair_id": "soymeal_soyoil_crush", "source": SBM, "target": SBO}]}
    lines, fired, decline, calls, seen = _run(monkeypatch, [drift])
    assert (lines, fired, decline) == ([], None, None) and seen == []


def test_ungrounded_root_declines_root_not_grounded(monkeypatch):
    _wire(monkeypatch, [FLAGSHIP])
    calls: list = []
    lines, fired, decline = cq._transmission_legs(
        _sg(), SimpleNamespace(contracts={}), [], {"source_slug": PALM, "pair_id": "soyoil_palm_vegoil"},
        _qfn_factory([]), ASOF, None, calls, comove=True)         # no groups, no walk nodes -> no anchor window
    assert (lines, fired) == ([], None) and decline == {"chain_id": "xmit_palm_soyoil_meal",
                                                        "reason": "root_not_grounded"}
    assert calls == []


def test_dark_head_link_declines_the_whole_chain_with_zero_rows(monkeypatch):
    seen: list = []
    lines, fired, decline, calls, _ = _run(monkeypatch, [FLAGSHIP], qfn=_qfn_factory(seen, dark=(PALM,)))
    assert (lines, fired) == ([], None)
    assert decline == {"chain_id": "xmit_palm_soyoil_meal", "reason": "hop_dark", "link": 1}
    assert calls == []                                            # nothing reader-facing, no orphan handles


def test_head_comove_with_the_comove_flag_off_declines_link_comove(monkeypatch):
    """GRAPHRAG_COMOVE off -> a same-sign link renders nothing, but the LEDGER stays honest: the decline reason
    is link_comove (an observed complex-wide move), never a fabricated hop_dark."""
    stocks = dict(_STOCKS)
    stocks[PALM] = lambda my: 3.0 + (my - 2020)
    lines, fired, decline, calls, _ = _run(monkeypatch, [FLAGSHIP], comove=False,
                                           qfn=_qfn_factory([], stocks=stocks))
    assert (lines, fired) == ([], None) and calls == []
    assert decline == {"chain_id": "xmit_palm_soyoil_meal", "reason": "link_comove", "link": 1}
    assert decline["reason"] in cq._XMIT_DECLINE_REASONS


def test_flat_leg_declines_hop_thin(monkeypatch):
    """A flat leg (sign 0) is neither a divergence nor a co-move -- the honest `hop_thin` truncation."""
    _wire(monkeypatch, [FLAGSHIP])
    _patch_deltas(monkeypatch, {PALM: {0: _entry(2024, 9.0, 2025, 8.0)},
                                SBO: {0: _entry(2024, 5.0, 2025, 5.0)},          # flat
                                SBM: {0: _entry(2024, 7.0, 2025, 9.0)}})
    calls: list = []
    lines, fired, decline = cq._transmission_legs(
        _sg(), SimpleNamespace(contracts={}), _groups(PALM),
        {"source_slug": PALM, "pair_id": "soyoil_palm_vegoil"}, _qfn_factory([]), ASOF, None, calls,
        comove=True)
    assert (lines, fired) == ([], None) and calls == []
    assert decline == {"chain_id": "xmit_palm_soyoil_meal", "reason": "hop_thin", "link": 1}


def test_degenerate_chain_declines(monkeypatch):
    """3.2: two links collapsing to the SAME (slug, metric, World, period) identity leave <2 distinct links --
    a 1-link 'chain' is just an RV2 pair. (The loader also rejects this shape; the engine belts it.)"""
    _wire(monkeypatch, [FLAGSHIP])
    monkeypatch.setattr(cq, "_transmission_row_ok", lambda c: True)
    dup = {"id": "dup", "links": [{"pair_id": "soyoil_palm_vegoil", "source": PALM, "target": SBO},
                                  {"pair_id": "soyoil_palm_vegoil", "source": SBO, "target": PALM}]}
    monkeypatch.setattr(cq, "load_transmission_map", lambda: [dup])
    calls: list = []
    lines, fired, decline = cq._transmission_legs(
        _sg(), SimpleNamespace(contracts={}), _groups(PALM),
        {"source_slug": PALM, "pair_id": "soyoil_palm_vegoil"}, _qfn_factory([]), ASOF, None, calls)
    assert (lines, fired) == ([], None) and decline == {"chain_id": "dup", "reason": "degenerate"}


def test_decline_reasons_are_the_shared_enum_plus_one():
    """D7: the vertical engine's vocabulary VERBATIM + the horizontal-only reasons, so the T2b ledger
    reads both chain engines with one enum. D-XT (2026-08-29, P1): `open_ask_pair_precedence` joins
    `link_comove` -- on an OPEN ask the pair engine wins and the composer declines with a reasoned
    trace instead of a silent absence (cascade.py a5.4)."""
    assert cq._XMIT_DECLINE_REASONS - cq._CHAIN_DECLINE_REASONS == {"link_comove",
                                                                    "open_ask_pair_precedence"}
    assert cq._CHAIN_DECLINE_REASONS <= cq._XMIT_DECLINE_REASONS


# ── CAP: transmission-scoped, priced BEFORE any fetch, ATOMIC ───────────────────────────────────────
def test_cap_is_atomic_and_priced_before_any_fetch(monkeypatch):
    monkeypatch.setattr(cq, "TRANSMISSION_CAP", 4)
    seen: list = []
    lines, fired, decline, calls, _ = _run(monkeypatch, [FLAGSHIP], seen=seen, qfn=_qfn_factory(seen))
    assert (lines, fired) == ([], None) and calls == []
    assert decline == {"chain_id": "xmit_palm_soyoil_meal", "reason": "cap", "net": 12}
    assert seen == []                                             # NOT ONE fetch paid on the capped turn


def test_cap_is_its_own_key_never_the_vertical_chain_cap():
    """D5 / fold-pass finding 3: the horizontal engine owns serving.cascade.transmission.cap ALONE. No shared
    counter with the ratified vertical CHAIN_CAP -- the two engines stay budget-INDEPENDENT."""
    assert cq.TRANSMISSION_CAP == 18 and cq.CHAIN_CAP == 12
    src = open(cq.__file__, encoding="utf-8").read()
    assert 'serving.cascade.transmission.cap' in src and 'chain_family' not in src


# ── the two-phase prewarm -> verbatim-serial memo (3.3 control-3) ───────────────────────────────────
def test_phase2_reuses_the_hot_memo_and_pays_zero_repeat_sql(monkeypatch):
    """The latency lever, MEASURED: phase 1 warms every distinct (slug, MY) World su_ratio in one pooled wave;
    phase 2 then runs _reroute_xc/_leg_world_deltas VERBATIM and issues ZERO new pg round-trips. The hub
    (soyoil) is fetched ONCE even though BOTH links need it."""
    seen: list = []
    _, fired, decline, calls, _ = _run(monkeypatch, [FLAGSHIP], seen=seen, qfn=_qfn_factory(seen))
    assert decline is None and fired is not None
    assert len(seen) == len(set(seen)) == 12                      # 3 slugs x 2 MYs x 2 components, NO repeats
    assert sum(1 for s in seen if f"'{SBO}'" in s) == 4           # the hub: 2 MYs x 2 components, once each


def test_su_keys_dedupe_the_shared_hub():
    keys = cq._xmit_su_keys(FLAGSHIP["links"], WINDOWS)
    assert keys == sorted(set(keys)) and len(keys) == 6
    assert {k[0] for k in keys} == {PALM, SBO, SBM}


def test_memo_qfn_passes_none_through_and_caches_otherwise():
    assert cq._xmit_memo_qfn(None) is None
    hits: list = []
    q = cq._xmit_memo_qfn(lambda sql: hits.append(sql) or [{"value": "1"}])
    assert q("SELECT 1") == q("SELECT 1") == [{"value": "1"}] and hits == ["SELECT 1"]


# ── D11 mutual exclusion, BOTH directions ───────────────────────────────────────────────────────────
def test_vertical_chain_fired_makes_transmission_yield(monkeypatch):
    """Direction A: the vertical engine fired THIS turn -> the horizontal yields to the ratified, earlier-
    shipping engine and declines (traced), before any fetch."""
    seen: list = []
    lines, fired, decline, calls, _ = _run(monkeypatch, [FLAGSHIP], chain_fired=True, seen=seen,
                                           qfn=_qfn_factory(seen))
    assert (lines, fired) == ([], None) and calls == [] and seen == []
    assert decline == {"chain_id": "xmit_palm_soyoil_meal", "reason": "cap", "yielded_to": "quantify_chain"}


def test_seam_transmission_fire_suppresses_the_vertical_chain(monkeypatch):
    """Direction B, at the quantify seam: when the horizontal engine FIRES the vertical one is not run at all
    -- so a turn carries at most ONE chain engine and the two budgets never sum."""
    _wire(monkeypatch, [FLAGSHIP])
    ran: list = []
    monkeypatch.setattr(cq, "_chain_legs",
                        lambda *a, **k: (ran.append(1), ([], None, None))[1])
    sg = _sg(nodes=[_walk_node(PALM)])
    calls: list = []
    cq.quantify(sg, SimpleNamespace(contracts={}), qfn=_qfn_factory([]), asof=ASOF, near=None,
                extra_number_calls=calls,
                xc_request={"source_slug": PALM, "pair_id": "soyoil_palm_vegoil"},
                comove=True, chain=True, transmission=True)
    assert sg.trace.get("quantify_transmission") is not None and ran == []
    assert "quantify_chain" not in sg.trace and "quantify_chain_decline" not in sg.trace


def test_seam_reads_a_fired_vertical_chain_from_the_trace(monkeypatch):
    """Direction A at the seam: sg.trace['quantify_chain'] IS the record that the vertical engine fired this
    turn, so the horizontal yields on it (the literal D11 reading, robust to seam re-ordering)."""
    _wire(monkeypatch, [FLAGSHIP])
    sg = _sg()
    sg.trace["quantify_chain"] = {"chain_id": "corn_lanina_safrinha_su"}
    calls: list = []
    cq.quantify(sg, SimpleNamespace(contracts={}), qfn=_qfn_factory([]), asof=ASOF, near=None,
                extra_number_calls=calls,
                xc_request={"source_slug": PALM, "pair_id": "soyoil_palm_vegoil"},
                comove=True, transmission=True)
    assert "quantify_transmission" not in sg.trace and calls == []
    assert sg.trace["quantify_transmission_decline"]["yielded_to"] == "quantify_chain"


# ── the seam: fired/decline keys + flag-off byte-identity ───────────────────────────────────────────
def _quantify(monkeypatch, sg, calls, **kw):
    return cq.quantify(sg, SimpleNamespace(contracts={}), qfn=_qfn_factory([]), asof=ASOF, near=None,
                       extra_number_calls=calls,
                       xc_request={"source_slug": PALM, "pair_id": "soyoil_palm_vegoil"}, comove=True, **kw)


def test_seam_writes_the_fired_key_and_appends_the_block(monkeypatch):
    _wire(monkeypatch, [FLAGSHIP])
    sg, calls = _sg(nodes=[_walk_node(PALM)]), []
    block, _trace, _rr = _quantify(monkeypatch, sg, calls, transmission=True)
    assert sg.trace["quantify_transmission"]["chain_id"] == "xmit_palm_soyoil_meal"
    assert "quantify_transmission_decline" not in sg.trace
    assert "TRANSMISSION CHAIN" in block and len(calls) == 12


def test_seam_writes_the_decline_key_when_attempted_and_declined(monkeypatch):
    _wire(monkeypatch, [FLAGSHIP])
    sg, calls = _sg(nodes=[_walk_node(PALM)]), []
    cq.quantify(sg, SimpleNamespace(contracts={}), qfn=_qfn_factory([], dark=(PALM,)), asof=ASOF, near=None,
                extra_number_calls=calls,
                xc_request={"source_slug": PALM, "pair_id": "soyoil_palm_vegoil"},
                comove=True, transmission=True)
    assert "quantify_transmission" not in sg.trace
    assert sg.trace["quantify_transmission_decline"]["reason"] == "hop_dark"


def test_seam_fired_transmission_subsumes_the_standalone_rv2_pair(monkeypatch):
    """[SKEPTIC F5] DEDUP: a fired composer's link-1 render IS the xc pair, so the standalone RV2 pair
    block is SKIPPED on a transmission-firing turn -- one 'CROSS-COMMODITY' render, no duplicate [N] rows,
    and quantify_reroute_v2 stays absent (the composer owns the pair this turn). The engine ran BEFORE the
    standalone seam; its lines still append at the chain-engines position."""
    _wire(monkeypatch, [FLAGSHIP])
    sg, calls = _sg(nodes=[_walk_node(PALM)]), []
    block, _t, _rr = cq.quantify(sg, SimpleNamespace(contracts={}), qfn=_qfn_factory([]), asof=ASOF, near=None,
                                 extra_number_calls=calls,
                                 xc_request={"source_slug": PALM, "target_slug": SBO,
                                             "pair_id": "soyoil_palm_vegoil"},
                                 comove=True, transmission=True)
    assert sg.trace.get("quantify_transmission")
    assert "quantify_reroute_v2" not in sg.trace          # the composer subsumed the standalone pair
    assert len(calls) == 12 == sg.trace["quantify_transmission"]["n_rows"]
    assert block.count("CROSS-COMMODITY on su_ratio") == 1


def test_seam_declined_transmission_keeps_the_standalone_rv2_pair(monkeypatch):
    """[SKEPTIC F5] the dedup must NOT eat the ratified RV2 surface on a DECLINED-composer turn: with no
    curated row matching the ask, the composer declines and the standalone pair renders exactly as today."""
    _wire(monkeypatch, [])                                 # empty map -> composer declines (no_curated_row)
    sg, calls = _sg(nodes=[_walk_node(PALM)]), []
    block, _t, _rr = cq.quantify(sg, SimpleNamespace(contracts={}), qfn=_qfn_factory([]), asof=ASOF, near=None,
                                 extra_number_calls=calls,
                                 xc_request={"source_slug": PALM, "target_slug": SBO,
                                             "pair_id": "soyoil_palm_vegoil"},
                                 comove=True, transmission=True)
    assert "quantify_transmission" not in sg.trace
    assert sg.trace.get("quantify_reroute_v2")             # standalone pair survives the decline
    assert block.count("CROSS-COMMODITY on su_ratio") == 1


def test_flag_off_is_byte_identical_and_never_consults_the_map(monkeypatch):
    """Flag-off fail-closed: the kwarg is omitted at the seam, so the engine is inert -- identical block,
    identical [N] rows, BOTH trace keys absent, and the transmission map is never even loaded."""
    _wire(monkeypatch, [FLAGSHIP])
    def _boom():                                                  # any consult on the off path = a bug
        raise AssertionError("transmission map consulted with the flag off")
    monkeypatch.setattr(cq, "load_transmission_map", _boom)
    sg_a, calls_a = _sg(), []
    block_a, trace_a, rr_a = _quantify(monkeypatch, sg_a, calls_a)                    # kwarg OMITTED
    sg_b, calls_b = _sg(), []
    block_b, trace_b, rr_b = _quantify(monkeypatch, sg_b, calls_b, transmission=False)
    assert (block_a, trace_a, rr_a, calls_a) == (block_b, trace_b, rr_b, calls_b)
    for sg in (sg_a, sg_b):
        assert "quantify_transmission" not in sg.trace and "quantify_transmission_decline" not in sg.trace


# ── 5.1 register fences: every engine literal is clean by construction ──────────────────────────────
def _clean(text: str) -> bool:
    return (cq.pace_register_ok(text) and reg.count_valuation_words(text) == 0
            and reg.count_flow_words(text) == 0)


def test_every_engine_literal_passes_all_three_fences(monkeypatch):
    lits = [cq._xmit_marker("world palm -> world soybean oil -> world soybean meal", "MY2024-MY2025"),
            cq._xmit_link_header(1, 2, PALM, SBO, "soyoil_palm_vegoil"),
            cq._xmit_link_header(2, 2, SBO, SBM, "soymeal_soyoil_crush")]
    lits += [cq._xmit_handoff(2, 2, SBO, SBM, r) for r in ("link_comove", "hop_dark", "hop_thin", "other")]
    for ln in lits:
        assert _clean(ln), ln
        assert not re.search(r"\b(therefore|implies|bullish|bearish|rally|sell|buy)\b", ln, re.I), ln
    # and the FULL rendered block (engine literals + the reused RV2 templates) clears them too
    lines, fired, _d, _c, _s = _run(monkeypatch, [FLAGSHIP])
    assert fired is not None and all(_clean(ln) for ln in lines)


def test_register_trip_declines_the_whole_chain_atomically(monkeypatch):
    """The fence is fail-closed and ATOMIC: a drifted template drops the chain and rolls its rows back (never a
    renumbered survivor, which the RV2 3-calls-per-line shape would corrupt)."""
    monkeypatch.setattr(cq, "_xmit_marker", lambda p, w: "TRANSMISSION CHAIN: momentum is accelerating")
    lines, fired, decline, calls, _ = _run(monkeypatch, [FLAGSHIP])
    assert (lines, fired) == ([], None) and calls == []
    assert decline == {"chain_id": "xmit_palm_soyoil_meal", "reason": "error", "detail": "register_fence"}


def test_engine_never_reads_the_env_and_never_mints_a_threshold():
    """[SKEPTIC F3]: the flag is read at the answer.py SEAM and threaded as a kwarg -- cascade.py owns no
    os.environ read. And no minted transmission metric: no pass-through / elasticity / crush margin."""
    src = open(cq.__file__, encoding="utf-8").read()
    assert "os.environ" not in src and "import os" not in src
    xmit = src[src.index("def _transmission_legs"):]
    for banned in ("pass_through", "passthrough", "elasticity", "crush_margin", "oil_share"):
        assert banned not in xmit


# ── [SKEPTIC] the ONE anchor window (2.3) is LITERAL -- the cross-lane audit's regression ────────────
# `_derive_windows` returns eps[:2]: typically an ANALOGUE era PLUS the current rhyme, whose MYs are
# DISJOINT. Every test above hands the engine a single window, so the suite was blind to what two do.
_TWO_ERAS = [("2015-08-01", "2016-06-01"), ("2024-11-01", "2025-11-01")]    # analogue era + current rhyme


def _legs_over(monkeypatch, eras, *, chains=(FLAGSHIP,), seen=None, calls=None):
    _wire(monkeypatch, list(chains))
    seen = [] if seen is None else seen
    calls = [] if calls is None else calls
    lines, fired, decline = cq._transmission_legs(
        _sg(), SimpleNamespace(contracts={}), [{"commodity": PALM, "eras": list(eras)}],
        {"pair_id": "soyoil_palm_vegoil", "source_slug": PALM, "target_slug": SBO},
        _qfn_factory(seen), ASOF, None, calls, comove=True)
    return lines, fired, decline, calls, seen


def test_two_derived_eras_would_overflow_the_cap_if_both_were_carried():
    """The arithmetic the fix exists for: 3 slugs x 2 disjoint eras x 2 MYs x 2 PSD components = net 24, which
    is > TRANSMISSION_CAP (18). Carrying both eras would decline the FLAGSHIP `cap` on the commonest real
    window shape -- and 3.3 sizes the cap for ONE window (~3 World su_ratios), so the cap is not the bug."""
    both = cq._xmit_su_keys(FLAGSHIP["links"], _TWO_ERAS)
    assert 2 * len(both) == 24 > cq.TRANSMISSION_CAP
    one = cq._xmit_su_keys(FLAGSHIP["links"], _TWO_ERAS[:1])
    assert 2 * len(one) == 12 <= cq.TRANSMISSION_CAP


def test_anchor_is_clamped_to_one_window_so_the_flagship_still_fires(monkeypatch):
    """With the clamp the two-era turn is priced and rendered EXACTLY like the one-era turn: same net cost,
    same links, same [N] rows -- no `cap` decline, and the second era is never fetched."""
    lines2, fired2, decline2, calls2, seen2 = _legs_over(monkeypatch, _TWO_ERAS)
    lines1, fired1, decline1, calls1, seen1 = _legs_over(monkeypatch, _TWO_ERAS[:1])
    assert decline2 is None and fired2 is not None
    assert (lines2, calls2) == (lines1, calls1) and len(seen2) == len(seen1) == 12
    assert [(e["link"], e["rendered"]) for e in fired2["links"]] == [(1, "divergence"), (2, "comove")]
    # the HEAD window is the anchor (that ordering is `_derive_windows`' own nearest/densest-first choice);
    # the TAIL window's marketing years are never fetched at all.
    assert not any("market_year = 2024" in s or "market_year = 2025" in s for s in seen2)


def test_every_link_fires_on_the_same_era_as_the_marker_names(monkeypatch):
    """The honesty half: one anchor means `_reroute_xc`'s INDEPENDENT per-link first-fire cannot land link 1 on
    the analogue era and link 2 on the current one while the marker calls them 'the SHARED anchor window'."""
    lines, fired, _d, _c, _s = _legs_over(monkeypatch, _TWO_ERAS)
    marker = next(ln for ln in lines if ln.startswith("TRANSMISSION CHAIN "))
    assert f"over {fired['window']}:" in marker
    assert all(f"over {fired['window']} " in ln or not ln.startswith("CROSS-COMMODITY")
               for ln in lines)                                   # every rendered link names the ONE anchor
    assert "MY2024" not in "\n".join(lines) and "MY2025" not in "\n".join(lines)
