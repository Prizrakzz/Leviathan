"""Reroute v2 engine (RV-W2) -- the cross-COMMODITY relative-value fork in numbers.cascade.

Lane C. Every test injects fetch functions (a fake query_fn or a monkeypatched _world_su_ratio); none hits
AWS. Covers: Recipe-B World synthesis (per-country-latest union over DELTA vintages -- the 2026-07-20 fix --
incl. the revised-twice-counts-once proof and the real palm MY2024 placeholder shape), the sign-oppose
fork (fires / same-sign declines / empty-leg declines), crush + feed narration selection, the fail-closed
sides guard, the MY_START_MONTH additions, engine-written trace key on fire, flag-off (xc_request None) parity.
"""
from __future__ import annotations

import re
import types

import pytest
from leviathan.graphrag.numbers import cascade as cq


# ── fixtures / helpers ────────────────────────────────────────────────────────────────────────────────
def _pair(pair_id="soyoil_palm_vegoil", a="soybean_oil_cbot", b="malaysian_crude_palm_oil_cme",
          complex_name="vegoil_substitution", shared_event="soyoil_palm_premium"):
    """A minimal complex_map pair row (the lane-A interface: .id/.pair/.complex_name/.shared_event/.side_a/
    .side_b/.direction/.focus_rule/.materiality_tier), decoupling these tests from lane A's config file."""
    return types.SimpleNamespace(
        id=pair_id, pair=(a, b), complex_name=complex_name, shared_event=shared_event,
        side_a={"contract": a, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        side_b={"contract": b, "ref": "psd_ending_stock_su_ratio", "country_rule": "world"},
        direction="opposing", focus_rule="query", materiality_tier="material")


def _qfn_from(fixture: dict):
    """A fake numbers executor: parses the compiled SQL for (metric, market_year) and returns the fixture rows
    -- so the real fetch_window/build_sql path runs but no backend is touched. Rows carry knowledge_date
    (release_date) + country + value, exactly as Q.run's SELECT aliases them."""
    def qfn(sql: str):
        if "ending_stocks_mt AS value" in sql:
            metric = "ending_stocks_mt"
        elif "consumption_mt AS value" in sql:
            metric = "consumption_mt"
        else:
            metric = None
        m = re.search(r"market_year = (\d+)", sql)
        my = int(m.group(1)) if m else None
        return [dict(r) for r in fixture.get((metric, my), [])]
    return qfn


# A window whose per-leg MY span is [2024, 2025] for the Oct/Sep/Jun-start legs used below (soyoil/palm Oct,
# corn Sep, wheat Jun): Nov-2024 -> Nov-2025 covers MY2024's start and MY2025's start for each.
_W2425 = [("2024-11-01", "2025-11-01")]


def _row(country, value, rd):
    return {"country": country, "value": value, "knowledge_date": rd}


# ── Recipe-B World synthesis (per-country-latest union; PSD vintages are DELTAS) ─────────────────────
def test_world_su_ratio_same_release_aggregates_across_countries():
    # stocks: US 10 + Brazil 6 = 16 ; use: US 80 + Brazil 4 = 84 -> 16/84 * 100 = 19.047...%
    fx = {
        ("ending_stocks_mt", 2025): [_row("United States", 10, "2026-05-10"), _row("Brazil", 6, "2026-05-10")],
        ("consumption_mt", 2025): [_row("United States", 80, "2026-05-10"), _row("Brazil", 4, "2026-05-10")],
    }
    got = cq._world_su_ratio(_qfn_from(fx), "soybean_oil_cbot", 2025, "2026-06-01")
    assert got is not None
    pct, rd, n = got
    assert rd == "2026-05-10" and n == 2
    assert pct == pytest.approx(100.0 * 16 / 84, rel=1e-9)


def test_world_su_ratio_country_revised_twice_counts_once_at_latest():
    """A country's OWN vintages are never mixed with each other: US revised between two releases counts ONCE,
    at its latest value (the within-country half of the per-country-latest rule -- an injected qfn can hand
    back raw multi-vintage rows, the live SQL's ROW_NUMBER dedup notwithstanding)."""
    fx = {
        ("ending_stocks_mt", 2025): [
            _row("United States", 100, "2026-04-01"),   # stale US vintage -- superseded, must be dropped
            _row("United States", 120, "2026-05-01"),   # US latest vintage -> the only US stocks row counted
        ],
        ("consumption_mt", 2025): [
            _row("United States", 900, "2026-04-01"),
            _row("United States", 1000, "2026-05-01"),
        ],
    }
    pct, rd, n = cq._world_su_ratio(_qfn_from(fx), "soybean_oil_cbot", 2025, "2026-06-01")
    assert rd == "2026-05-01" and n == 1
    assert pct == pytest.approx(100.0 * 120 / 1000, rel=1e-9)   # 12.0, NOT (100+120)/(900+1000)


def test_world_su_ratio_delta_vintages_sum_per_country_latest_union():
    """THE 2026-07-20 ROOT CAUSE, reproduced in shape: PSD releases are DELTAS -- each release_date carries
    ONLY revised countries (live palm MY2024: n=30, 40, 5, 2, then ONE zero 'Other' placeholder row). The
    retired rows-at-max-release lock summed only that placeholder -> World su_ratio 0.00%. The fix sums the
    per-country-latest union: Malaysia counts ONCE at its Jan revision (not its Dec print), every country's
    latest row joins regardless of which release stamped it, and release_date returns as the MAX across the
    summed set (a freshness stamp, not a single-vintage claim)."""
    fx = {
        ("ending_stocks_mt", 2024): [
            _row("Indonesia", 2_000_000, "2024-12-10"),   # only ever printed in Dec
            _row("Malaysia", 1_500_000, "2024-12-10"),    # superseded by the Jan revision below
            _row("Malaysia", 1_700_000, "2025-01-10"),    # Malaysia's latest -> the value that counts
            _row("India", 900_000, "2025-01-10"),
            _row("China", 400_000, "2025-02-10"),
            _row("Thailand", 100_000, "2025-04-10"),
            _row("Other", 0.0, "2025-06-10"),             # the latest release: ONE placeholder row, value 0
        ],
        ("consumption_mt", 2024): [
            _row("Indonesia", 6_000_000, "2024-12-10"),
            _row("Malaysia", 3_000_000, "2024-12-10"),
            _row("Malaysia", 3_400_000, "2025-01-10"),
            _row("India", 9_000_000, "2025-01-10"),
            _row("China", 7_000_000, "2025-02-10"),
            _row("Thailand", 600_000, "2025-04-10"),
            _row("Other", 0.0, "2025-06-10"),
        ],
    }
    got = cq._world_su_ratio(_qfn_from(fx), "malaysian_crude_palm_oil_cme", 2024, "2026-06-20")
    assert got is not None
    pct, rd, n = got
    # stocks: 2.0M + 1.7M(Jan, NOT Dec's 1.5M) + 0.9M + 0.4M + 0.1M + 0 = 5.1M
    # use:    6.0M + 3.4M            + 9.0M + 7.0M + 0.6M + 0 = 26.0M -> 19.615...%
    assert pct == pytest.approx(100.0 * 5_100_000 / 26_000_000, rel=1e-9)
    assert pct > 0.0                                             # NEVER the placeholder-only 0.00% again
    assert rd == "2025-06-10"                                    # freshness stamp = max release in the set
    assert n == 6                                                # all six countries, each at its own latest


def test_world_su_ratio_missing_component_declines():
    fx = {("ending_stocks_mt", 2025): [_row("United States", 10, "2026-05-10")]}   # no consumption rows
    assert cq._world_su_ratio(_qfn_from(fx), "soybean_oil_cbot", 2025, "2026-06-01") is None


def test_world_su_ratio_pit_guard_hides_future_vintage():
    # the latest release is AFTER asof -> fetch_window's as-of guard drops it; only the <= asof vintage remains.
    fx = {
        ("ending_stocks_mt", 2025): [_row("United States", 10, "2026-05-10"), _row("United States", 99, "2026-09-01")],
        ("consumption_mt", 2025): [_row("United States", 80, "2026-05-10"), _row("United States", 99, "2026-09-01")],
    }

    def qfn(sql):
        # emulate the SQL as-of guard on the string release_date <= asof (build_sql emits it; a fake executor
        # must honor it or the PIT test is vacuous)
        m = re.search(r"market_year = (\d+)", sql)
        my = int(m.group(1)) if m else None
        metric = "ending_stocks_mt" if "ending_stocks_mt AS value" in sql else "consumption_mt"
        rows = fx.get((metric, my), [])
        return [dict(r) for r in rows if str(r["knowledge_date"]) <= "2026-06-01"]

    pct, rd, n = cq._world_su_ratio(qfn, "soybean_oil_cbot", 2025, "2026-06-01")
    assert rd == "2026-05-10"
    assert pct == pytest.approx(100.0 * 10 / 80, rel=1e-9)


# ── membership-window dedup in the World SUM (the 2026-07-20 UK-backfill fix) ─────────────────────────
def test_world_su_ratio_dedups_uk_inside_eu_aggregate_window():
    """The live case, arithmetic PINNED: MY2019's per-country-latest set has BOTH an EU aggregate row (EU-28,
    still carrying the UK) and a backfilled individual UK row. The UK sits inside its EU_MEMBERSHIP window
    (1973 <= 2019 < 2020), so its individual rows are EXCLUDED from the World SUM -- stocks 20+10 (NOT +5),
    use 100+60 (NOT +30)."""
    fx = {
        ("ending_stocks_mt", 2019): [_row("European Union", 20, "2026-05-10"),
                                     _row("United Kingdom", 5, "2026-05-10"),
                                     _row("United States", 10, "2026-05-10")],
        ("consumption_mt", 2019): [_row("European Union", 100, "2026-05-10"),
                                   _row("United Kingdom", 30, "2026-05-10"),
                                   _row("United States", 60, "2026-05-10")],
    }
    pct, rd, n = cq._world_su_ratio(_qfn_from(fx), "soybean_oil_cbot", 2019, "2026-06-01")
    assert n == 2                                                # EU + US; the UK row never enters the SUM
    assert pct == pytest.approx(100.0 * (20 + 10) / (100 + 60), rel=1e-9)


def test_world_su_ratio_dedup_aggregate_present_across_vintages():
    """aggregate_present is evaluated against the per-country-latest SET, not any one release: the EU
    aggregate's latest print (Apr) is OLDER than the UK's backfilled row (May) -- delta vintages, the EU
    simply wasn't revised in May. The aggregate still counts as PRESENT, so the UK row is still deduped;
    under the retired rows-at-max-release lock the EU row would have vanished and the UK double-counted."""
    fx = {
        ("ending_stocks_mt", 2019): [_row("European Union", 20, "2026-04-10"),
                                     _row("United Kingdom", 5, "2026-05-10"),
                                     _row("United States", 10, "2026-05-10")],
        ("consumption_mt", 2019): [_row("European Union", 100, "2026-04-10"),
                                   _row("United Kingdom", 30, "2026-05-10"),
                                   _row("United States", 60, "2026-05-10")],
    }
    pct, rd, n = cq._world_su_ratio(_qfn_from(fx), "soybean_oil_cbot", 2019, "2026-06-01")
    assert n == 2                                                # EU (Apr latest) + US; UK still excluded
    assert rd == "2026-05-10"                                    # freshness stamp spans the union
    assert pct == pytest.approx(100.0 * (20 + 10) / (100 + 60), rel=1e-9)


def test_world_su_ratio_null_valued_aggregate_never_triggers_dedup():
    """A NULL-valued EU aggregate row must NOT count as aggregate_present: it carries no member tonnage, so
    deduping the UK against it would DROP the UK's numbers from the World SUM entirely (neither the aggregate
    nor the member contributing -- skeptic probe T3, 2026-07-20) and split the engine from the census
    existence probe, whose SQL sum(value) ignores NULLs and keeps the member. The UK stays IN."""
    fx = {
        ("ending_stocks_mt", 2019): [_row("European Union", None, "2026-05-10"),
                                     _row("United Kingdom", 8, "2026-05-10"),
                                     _row("United States", 10, "2026-05-10")],
        ("consumption_mt", 2019): [_row("European Union", None, "2026-05-10"),
                                   _row("United Kingdom", 30, "2026-05-10"),
                                   _row("United States", 60, "2026-05-10")],
    }
    pct, rd, n = cq._world_su_ratio(_qfn_from(fx), "soybean_oil_cbot", 2019, "2026-06-01")
    assert n == 2                                                # UK + US; the NULL EU row joins neither side
    assert pct == pytest.approx(100.0 * (8 + 10) / (30 + 60), rel=1e-9)


def test_world_su_ratio_counts_uk_from_my2020_outside_window():
    """From MY2020 the UK is OUTSIDE its membership window (exit 2020, exclusive) -- post-Brexit PSD reports
    it separately and the EU aggregate no longer carries it, so its individual rows COUNT."""
    fx = {
        ("ending_stocks_mt", 2020): [_row("European Union", 20, "2026-05-10"),
                                     _row("United Kingdom", 5, "2026-05-10"),
                                     _row("United States", 10, "2026-05-10")],
        ("consumption_mt", 2020): [_row("European Union", 100, "2026-05-10"),
                                   _row("United Kingdom", 30, "2026-05-10"),
                                   _row("United States", 60, "2026-05-10")],
    }
    pct, rd, n = cq._world_su_ratio(_qfn_from(fx), "soybean_oil_cbot", 2020, "2026-06-01")
    assert n == 3
    assert pct == pytest.approx(100.0 * (20 + 10 + 5) / (100 + 60 + 30), rel=1e-9)


def test_world_su_ratio_keeps_member_rows_when_no_aggregate_row():
    """No EU aggregate row in the per-country-latest set (the pre-1991 shape: members reported ONLY
    individually) -> the dedup must NOT fire, or the world would be UNDER-counted. UK inside its window but
    nothing carries it."""
    fx = {
        ("ending_stocks_mt", 1985): [_row("United Kingdom", 5, "2026-05-10"),
                                     _row("United States", 10, "2026-05-10")],
        ("consumption_mt", 1985): [_row("United Kingdom", 30, "2026-05-10"),
                                   _row("United States", 60, "2026-05-10")],
    }
    pct, rd, n = cq._world_su_ratio(_qfn_from(fx), "soybean_oil_cbot", 1985, "2026-06-01")
    assert n == 2
    assert pct == pytest.approx(100.0 * (10 + 5) / (60 + 30), rel=1e-9)


def test_world_su_ratio_never_dedups_member_without_explicit_window():
    """A member title with NO curated EU_MEMBERSHIP window (France, a pre-EU-15 founder) is NEVER silently
    dropped from the SUM -- guessing its window could as easily under-count. The census era-overlap lint is
    the guard that DARKs such a pair instead (fail-closed division of labor)."""
    fx = {
        ("ending_stocks_mt", 2005): [_row("European Union", 20, "2026-05-10"),
                                     _row("France", 5, "2026-05-10")],
        ("consumption_mt", 2005): [_row("European Union", 100, "2026-05-10"),
                                   _row("France", 30, "2026-05-10")],
    }
    pct, rd, n = cq._world_su_ratio(_qfn_from(fx), "soybean_oil_cbot", 2005, "2026-06-01")
    assert n == 2                                                # France stays in -- visible, not hidden
    assert pct == pytest.approx(100.0 * (20 + 5) / (100 + 30), rel=1e-9)


# ── the sign-oppose fork ──────────────────────────────────────────────────────────────────────────────
def _patch_world(monkeypatch, table: dict):
    """Stub _world_su_ratio with a {(slug, my): pct} table (rd/n fixed)."""
    def fake(qfn, slug, my, asof):
        if (slug, my) in table:
            return (table[(slug, my)], "2026-05-10", 5)
        return None
    monkeypatch.setattr(cq, "_world_su_ratio", fake)


def test_reroute_xc_sign_oppose_fires(monkeypatch):
    # soyoil tightens (9.4 -> 8.1, -1.3), palm loosens (11.0 -> 12.6, +1.6): opposing -> FIRE.
    _patch_world(monkeypatch, {
        ("soybean_oil_cbot", 2024): 9.4, ("soybean_oil_cbot", 2025): 8.1,
        ("malaysian_crude_palm_oil_cme", 2024): 11.0, ("malaysian_crude_palm_oil_cme", 2025): 12.6,
    })
    calls: list = []
    windows = _W2425
    lines, fired = cq._reroute_xc(_pair(), "soybean_oil_cbot", "malaysian_crude_palm_oil_cme",
                                  windows, qfn=None, asof="2026-06-01", calls=calls, base=len(calls), sg=None)
    assert fired is not None and fired["reroute_v2"] is True
    assert fired["commodityA"] == "soybean_oil_cbot" and fired["commodityB"] == "malaysian_crude_palm_oil_cme"
    assert fired["dA"] == pytest.approx(-1.3) and fired["dB"] == pytest.approx(1.6)
    assert fired["window"] == "MY2024-MY2025"
    body = "\n".join(lines)
    assert "CROSS-COMMODITY on su_ratio" in body and "## Cross-commodity" in body
    assert "labeled BY COMMODITY" in body
    # every narrated magnitude is injected (all-numbers guard): 3 rows per leg
    assert len(calls) == 6
    # W4: each leg line ends with its SERIES scope -- World is a SYNTHESIS of per-country silver_psd rows,
    # so the tag says so and the ratio cannot be narrated as any one country's
    # A1 (2026-08-01): the SOURCE segment renders dp.table_label ("USDA PSD"), never the raw silver_* id --
    # _fmt_line feeds the MODEL's copy-surface and reg.internal_leaks does not match a bare table id.
    assert lines[0] == ("- [N1] world soybean oil stocks-to-use MY2025: 8.1% (vs MY2024 9.4%, -1.3pp over "
                        "the window) [series: soybean_oil_cbot; country: World; table: USDA PSD]")
    assert lines[1] == ("- [N4] world malaysian crude palm oil stocks-to-use MY2025: 12.6% (vs MY2024 11%, "
                        "+1.6pp over the window) [series: malaysian_crude_palm_oil_cme; country: World; "
                        "table: USDA PSD]")
    assert not any("silver_" in ln for ln in lines)
    # W4 A/B RCA (2026-08-01): ONE line prints endpoint + baseline + delta, so the [N] endpoint call is
    # bound to all three; the baseline/delta calls have no line of their own and stay unbound (their single
    # row is already exact). Three shown values = no unambiguous repair source, so a mismatch here drops
    # the sentence rather than guessing which of the three the prose meant.
    assert calls[0]["shown"] == [8.1, 9.4, pytest.approx(-1.3)]
    assert "shown" not in calls[1] and "shown" not in calls[2]
    assert calls[3]["shown"] == [12.6, 11.0, pytest.approx(1.6)]


def test_reroute_xc_same_sign_declines(monkeypatch):
    # both loosen (co-move) -> record NOTHING (the honest backstop).
    _patch_world(monkeypatch, {
        ("soybean_oil_cbot", 2024): 8.0, ("soybean_oil_cbot", 2025): 9.0,
        ("malaysian_crude_palm_oil_cme", 2024): 11.0, ("malaysian_crude_palm_oil_cme", 2025): 12.0,
    })
    calls: list = []
    lines, fired = cq._reroute_xc(_pair(), "soybean_oil_cbot", "malaysian_crude_palm_oil_cme",
                                  _W2425, qfn=None, asof="2026-06-01",
                                  calls=calls, base=0, sg=None)
    assert fired is None and lines == [] and calls == []


def test_reroute_xc_empty_leg_declines(monkeypatch):
    # sibling has no World data in-window -> no delta -> decline (fail-closed), never a one-sided fork.
    _patch_world(monkeypatch, {
        ("soybean_oil_cbot", 2024): 9.4, ("soybean_oil_cbot", 2025): 8.1,
    })
    calls: list = []
    lines, fired = cq._reroute_xc(_pair(), "soybean_oil_cbot", "malaysian_crude_palm_oil_cme",
                                  _W2425, qfn=None, asof="2026-06-01",
                                  calls=calls, base=0, sg=None)
    assert fired is None and lines == [] and calls == []


def test_reroute_xc_flat_leg_records_nothing(monkeypatch):
    # sign(dB) == 0 (palm unchanged) -> not an opposition -> decline.
    _patch_world(monkeypatch, {
        ("soybean_oil_cbot", 2024): 9.4, ("soybean_oil_cbot", 2025): 8.1,
        ("malaysian_crude_palm_oil_cme", 2024): 12.0, ("malaysian_crude_palm_oil_cme", 2025): 12.0,
    })
    calls: list = []
    _lines, fired = cq._reroute_xc(_pair(), "soybean_oil_cbot", "malaysian_crude_palm_oil_cme",
                                   _W2425, qfn=None, asof="2026-06-01",
                                   calls=calls, base=0, sg=None)
    assert fired is None


# ── narration selection (RV-W2.4 / C20) ───────────────────────────────────────────────────────────────
def test_crush_narration_path_selected(monkeypatch):
    _patch_world(monkeypatch, {
        ("soybean_meal_cbot", 2024): 9.0, ("soybean_meal_cbot", 2025): 10.0,
        ("soybean_oil_cbot", 2024): 8.0, ("soybean_oil_cbot", 2025): 7.0,
    })
    calls: list = []
    lines, fired = cq._reroute_xc(_pair("soymeal_soyoil_crush", "soybean_meal_cbot", "soybean_oil_cbot",
                                        complex_name="soy_crush", shared_event="soy_crush_margin"),
                                  "soybean_meal_cbot", "soybean_oil_cbot",
                                  _W2425, qfn=None, asof="2026-06-01",
                                  calls=calls, base=0, sg=None)
    assert fired is not None
    body = "\n".join(lines)
    assert "JOINT products" in body and "DEMAND" in body       # joint-product path, not substitution
    assert "substitut" not in body.lower()


def test_feed_grain_generic_narration_and_wheat_all_classes_label(monkeypatch):
    _patch_world(monkeypatch, {
        ("corn_cbot", 2024): 10.0, ("corn_cbot", 2025): 9.0,
        ("soft_red_winter_wheat_cbot", 2024): 30.0, ("soft_red_winter_wheat_cbot", 2025): 33.0,
    })
    calls: list = []
    lines, fired = cq._reroute_xc(_pair("corn_wheat_feed", "corn_cbot", "soft_red_winter_wheat_cbot",
                                        complex_name="feed_grain", shared_event="wheat_corn_spread"),
                                  "corn_cbot", "soft_red_winter_wheat_cbot",
                                  _W2425, qfn=None, asof="2026-06-01",
                                  calls=calls, base=0, sg=None)   # sg=None -> shared_event NOT matched -> generic
    assert fired is not None
    body = "\n".join(lines)
    assert "world wheat (all classes)" in body                 # C20: never 'soft red winter'
    assert "soft red winter" not in body.lower()
    assert "relative feed-grain balance shifted" in body and "substitution)" not in body


def test_feed_grain_specific_narration_when_shared_event_matched(monkeypatch):
    _patch_world(monkeypatch, {
        ("corn_cbot", 2024): 10.0, ("corn_cbot", 2025): 9.0,
        ("soft_red_winter_wheat_cbot", 2024): 30.0, ("soft_red_winter_wheat_cbot", 2025): 33.0,
    })
    sg = types.SimpleNamespace(nodes=[types.SimpleNamespace(id="wheat_corn_spread", prior={})])
    calls: list = []
    lines, fired = cq._reroute_xc(_pair("corn_wheat_feed", "corn_cbot", "soft_red_winter_wheat_cbot",
                                        complex_name="feed_grain", shared_event="wheat_corn_spread"),
                                  "corn_cbot", "soft_red_winter_wheat_cbot",
                                  _W2425, qfn=None, asof="2026-06-01",
                                  calls=calls, base=0, sg=sg)
    assert fired is not None
    assert "feed-ration substitution" in "\n".join(lines)


# ── fail-closed sides guard ───────────────────────────────────────────────────────────────────────────
def test_sides_guard_rejects_non_material():
    p = _pair()
    p.materiality_tier = "contextual"
    assert cq._xc_sides_ok(p, "soybean_oil_cbot", "malaysian_crude_palm_oil_cme") is False


def test_sides_guard_rejects_non_world_country_rule():
    p = _pair()
    p.side_a = {**p.side_a, "country_rule": "primary"}
    assert cq._xc_sides_ok(p, "soybean_oil_cbot", "malaysian_crude_palm_oil_cme") is False


def test_sides_guard_rejects_slug_not_on_pair():
    assert cq._xc_sides_ok(_pair(), "soybean_oil_cbot", "rapeseed_oil_zce") is False


def test_reroute_xc_declines_when_sides_bad(monkeypatch):
    _patch_world(monkeypatch, {
        ("soybean_oil_cbot", 2024): 9.4, ("soybean_oil_cbot", 2025): 8.1,
        ("malaysian_crude_palm_oil_cme", 2024): 11.0, ("malaysian_crude_palm_oil_cme", 2025): 12.6,
    })
    p = _pair()
    p.materiality_tier = "excluded"
    calls: list = []
    lines, fired = cq._reroute_xc(p, "soybean_oil_cbot", "malaysian_crude_palm_oil_cme",
                                  _W2425, qfn=None, asof="2026-06-01",
                                  calls=calls, base=0, sg=None)
    assert fired is None and lines == []


# ── MY_START_MONTH additions (task 1) ─────────────────────────────────────────────────────────────────
def test_my_start_month_additions():
    assert cq.MY_START_MONTH["malaysian_crude_palm_oil_cme"] == 10   # ADDENDUM P2: Oct, NOT the body's 11
    assert cq.MY_START_MONTH["rapeseed_oil_zce"] == 10
    # each leg picks its OWN marketing year via _my_start (exact-key hit, no default-9 fallthrough)
    assert cq._my_start("malaysian_crude_palm_oil_cme") == 10
    assert cq._my_start("rapeseed_oil_zce") == 10


# ── injected rows value-check against the strip verifier ───────────────────────────────────────────────
def test_injected_rows_back_every_narrated_magnitude(monkeypatch):
    from leviathan.graphrag import verify as V
    _patch_world(monkeypatch, {
        ("soybean_oil_cbot", 2024): 9.4, ("soybean_oil_cbot", 2025): 8.1,
        ("malaysian_crude_palm_oil_cme", 2024): 11.0, ("malaysian_crude_palm_oil_cme", 2025): 12.6,
    })
    calls: list = []
    cq._reroute_xc(_pair(), "soybean_oil_cbot", "malaysian_crude_palm_oil_cme",
                   _W2425, qfn=None, asof="2026-06-01",
                   calls=calls, base=0, sg=None)
    allv = V._all_row_vals(calls)
    # a mentor sentence citing the soyoil endpoint + its baseline + delta value-checks fully
    sent = "World soybean-oil stocks-to-use eased to 8.1% [N1], down from 9.4%, a 1.3pp drop."
    assert V._check_number_handle(sent, 1, calls) is None


# ── engine writes the trace key on fire; flag-off parity ──────────────────────────────────────────────
class _FakeNode:
    def __init__(self, contract, dates):
        self.contract = contract
        self.id = contract + "_seed"
        self.prior = {}
        self.evidence = [{"event_date": d} for d in dates]


class _FakeSG:
    def __init__(self, nodes):
        self.nodes = nodes
        self.trace: dict = {}


def test_quantify_writes_trace_key_on_fire(monkeypatch):
    # exercise the quantify seam: xc_request present + _run_xc fires -> ENGINE writes sg.trace key + block.
    monkeypatch.setattr(cq, "_run_xc",
                        lambda *a, **k: (["CROSS-COMMODITY on su_ratio: ...render '## Cross-commodity'"],
                                         {"pair_id": "p", "reroute_v2": True}))
    sg = _FakeSG([_FakeNode("soybean_oil_cbot", ["2020-05-01", "2020-06-01"])])
    # a mapped-ref node so `groups` is non-empty and quantify reaches the fork (qfn returns no numbers)
    monkeypatch.setattr(cq, "_silver_ref", lambda n: "psd_export")
    monkeypatch.setattr(cq, "map_row", lambda ref: {"table": "silver_psd", "metric": "exports_mt",
                                                    "period_type": "marketing_year", "agg": "latest",
                                                    "country_rule": "none"})
    block, trace, r_trace = cq.quantify(sg, None, qfn=lambda sql: [], asof="2026-06-01", near=None,
                                        extra_number_calls=[],
                                        xc_request={"pair_id": "p", "source_slug": "soybean_oil_cbot",
                                                    "target_slug": "malaysian_crude_palm_oil_cme"})
    assert sg.trace.get("quantify_reroute_v2") == {"pair_id": "p", "reroute_v2": True}
    assert block is not None and "## Cross-commodity" in block


def test_quantify_flag_off_is_inert(monkeypatch):
    # xc_request None -> the v2 branch never runs, the trace key is ABSENT, and _run_xc is never called.
    called = {"n": 0}
    monkeypatch.setattr(cq, "_run_xc", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or ([], None))
    sg = _FakeSG([_FakeNode("soybean_oil_cbot", ["2020-05-01", "2020-06-01"])])
    monkeypatch.setattr(cq, "_silver_ref", lambda n: "psd_export")
    monkeypatch.setattr(cq, "map_row", lambda ref: {"table": "silver_psd", "metric": "exports_mt",
                                                    "period_type": "marketing_year", "agg": "latest",
                                                    "country_rule": "none"})
    out = cq.quantify(sg, None, qfn=lambda sql: [], asof="2026-06-01", near=None, extra_number_calls=[])
    assert len(out) == 3                                        # unchanged 3-tuple arity
    assert "quantify_reroute_v2" not in sg.trace
    assert called["n"] == 0


def test_quantify_run_xc_exception_is_fail_closed(monkeypatch):
    # a raising v2 path must NOT break the v1 answer (fail-closed) -- quantify catches nothing here because
    # _run_xc itself swallows; assert the real _run_xc returns ([],None) on a bad pair rather than propagating.
    sg = _FakeSG([_FakeNode("soybean_oil_cbot", ["2020-05-01", "2020-06-01"])])
    out = cq._run_xc({"pair_id": "does_not_exist", "source_slug": "soybean_oil_cbot",
                      "target_slug": "malaysian_crude_palm_oil_cme"},
                     sg, None, [], qfn=lambda sql: [], asof="2026-06-01", near=None, calls=[])
    assert out == ([], None)


# ── integrator seam: answer -> _answer_l2 -> quantify must carry xc_request (the gate-test mocks an.answer,
# so this is the ONLY unit guard that the real answer() signature threads the kwarg into the engine) ──────
def test_answer_signatures_thread_xc_request():
    import inspect
    from leviathan.graphrag import answer as an
    for fn in (an.answer, an._answer_l2):
        assert "xc_request" in inspect.signature(fn).parameters, f"{fn.__name__} missing xc_request"
    assert "xc_request" in inspect.signature(cq.quantify).parameters


def test_answer_l2_passes_xc_request_to_quantify(monkeypatch):
    # drive the L2 quantify seam directly: a stub quantify records the kwarg it is handed, proving answer.py
    # threads xc_request from _answer_l2's arg into cq.quantify (the gap the integrator closed).
    from leviathan.graphrag import answer as an
    import leviathan.graphrag.planner as pl

    rec = {}

    # `**_kw` (D-PQ FIX-1): `_answer_l2` now always threads `futures_newest_first` (the estate-wide
    # newest-first scope is the serving default), so a pre-wave stub signature no longer survives the
    # omit-when-off idiom. What this test pins is xc_request, not the kwarg census.
    def _stub_quantify(sg, graph, *, qfn, asof, near, extra_number_calls, xc_request=None, comove=False,
                       price_request=None, **_kw):
        rec["xc_request"] = xc_request
        rec["comove"] = comove
        return None, None, None

    # minimal L2 scaffolding: a grounded subgraph with one node + a stub reasoner render so answer returns.
    sg = _FakeSG([_FakeNode("soybean_oil_cbot", ["2020-05-01"])])
    sg.seeds = ["soybean_oil_cbot"]
    sg.fired_regimes = []
    monkeypatch.setattr(pl, "grounded_subgraph", lambda *a, **k: sg)
    monkeypatch.setattr(pl, "ground", lambda *a, **k: None)
    monkeypatch.setattr(an, "_l2_blocks", lambda *a, **k: ([], []))
    monkeypatch.setattr(an, "_pgnumbers_live", lambda: True)
    monkeypatch.setattr(an, "_render_from_sg", lambda *a, **k: {"answer": "ok", "structured": None,
                                                               "evidence": [], "citations": [], "trace": sg.trace},
                        raising=False)
    from leviathan.graphrag.numbers import cascade as _cq
    monkeypatch.setattr(_cq, "quantify", _stub_quantify)
    req = {"pair_id": "p", "source_slug": "soybean_oil_cbot", "target_slug": "malaysian_crude_palm_oil_cme"}
    try:
        an._answer_l2("q", None, model=an.SONNET, asof="2026-06-01", near=None, call=lambda *a, **k: "x",
                      retrieve=lambda *a, **k: [], routed=["soybean_oil_cbot"], numbers_lookup=lambda sql: [],
                      xc_request=req)
    except Exception:  # noqa: BLE001 -- render scaffolding may not be complete; the quantify seam ran first
        pass
    assert rec.get("xc_request") == req
