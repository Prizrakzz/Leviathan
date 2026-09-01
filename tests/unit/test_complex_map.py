"""Unit tests for reroute-v2 lane A: the complex map (loader + resolver + lint) and the palm
marketing-year transform pre-fix.

The real configs/graphrag/numbers/complex_map.yaml is NEVER edited to be bad; every negative lint
case is an inline fixture injected by monkeypatching complex_map.iter_all_pairs so the shipped
config stays the single source of truth (and its own happy-path lint test proves it green).
"""
from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from leviathan.graphrag import complex_map as xcm
from leviathan.graphrag import config_check as cc


# ── loader happy path ─────────────────────────────────────────────────────────────────────────────
class TestLoader:
    def test_loads_twelve_material_pairs(self) -> None:
        # 7 RV-W0 originals + 5 ratified by the RV roster sitting (2026-08-29: corn_sorghum_feed,
        # the three rape_crush rows, palm_sunoil_vegoil -- every sign owner-sitting adjudicated,
        # every leg census-FIRES). The 21 contextual refusal records load INERT by design.
        m = xcm.load_complex_map()
        assert len(m.pairs) == 12
        assert all(p.materiality_tier == "material" for p in m.pairs)

    def test_pair_shape_matches_interface_contract(self) -> None:
        p = xcm.load_complex_map().row("soyoil_palm_vegoil")
        assert p is not None
        assert p.pair == ("soybean_oil_cbot", "malaysian_crude_palm_oil_cme")
        assert isinstance(p.pair, tuple)
        assert p.complex_name == "vegoil_substitution"           # yaml `complex:` -> .complex_name
        assert p.shared_event == "soyoil_palm_premium"
        assert p.direction == "opposing"
        assert p.focus_rule == "query"
        for side in (p.side_a, p.side_b):
            assert side["ref"] == "psd_ending_stock_su_ratio"
            assert side["country_rule"] == "world"
            assert side["contract"] in p.pair

    def test_flagship_and_feed_pairs_present(self) -> None:
        m = xcm.load_complex_map()
        flag = m.row("soymeal_soyoil_crush")
        assert flag is not None and flag.complex_name == "soy_crush"
        feed = m.row("corn_wheat_feed")
        assert feed is not None and feed.pair == ("corn_cbot", "soft_red_winter_wheat_cbot")

    def test_by_pair_is_order_insensitive(self) -> None:
        m = xcm.load_complex_map()
        a, b = "soybean_oil_cbot", "malaysian_crude_palm_oil_cme"
        assert m.by_pair(a, b) is m.by_pair(b, a)
        assert m.by_pair(a, b).id == "soyoil_palm_vegoil"

    def test_row_and_complex_row_miss_returns_none(self) -> None:
        assert xcm.load_complex_map().row("nonexistent_pair") is None
        assert xcm.complex_row("nonexistent_pair") is None

    def test_loader_drops_non_material(self, monkeypatch) -> None:
        base = xcm.iter_all_pairs()[0]
        excluded = dataclasses.replace(base, id="corn_soymeal_excluded", materiality_tier="excluded")
        contextual = dataclasses.replace(base, id="ctx", materiality_tier="contextual")
        monkeypatch.setattr(xcm, "iter_all_pairs", lambda: [base, excluded, contextual])
        xcm.load_complex_map.cache_clear()
        try:
            ids = {p.id for p in xcm.load_complex_map().pairs}
            assert base.id in ids
            assert "corn_soymeal_excluded" not in ids and "ctx" not in ids
        finally:
            xcm.load_complex_map.cache_clear()


# ── resolver ──────────────────────────────────────────────────────────────────────────────────────
class TestResolver:
    @pytest.mark.parametrize("bare, slug", [
        ("palm_oil", "malaysian_crude_palm_oil_cme"),
        ("soybean_oil", "soybean_oil_cbot"),
        ("soybean_meal", "soybean_meal_cbot"),
        ("rapeseed_oil", "rapeseed_oil_zce"),
        ("soybeans", "soybeans_cbot"),
        ("corn", "corn_cbot"),
        ("wheat", "soft_red_winter_wheat_cbot"),
    ])
    def test_curated_bare_names_hit(self, bare, slug) -> None:
        assert xcm.resolve_bare_commodity(bare) == slug

    def test_curated_table_wins_over_case(self) -> None:
        assert xcm.resolve_bare_commodity("Palm_Oil") == "malaysian_crude_palm_oil_cme"

    @pytest.mark.parametrize("spoken, slug", [
        # The detector captures NATURAL-LANGUAGE spans; separators fold to the curated underscore keys.
        # Without this fold every multi-word named-target ask resolved None and the gate declined -- the
        # feature only ever fired on single-word names (verify-wave finding, 2026-07-18).
        ("soybean oil", "soybean_oil_cbot"),
        ("palm oil", "malaysian_crude_palm_oil_cme"),
        ("Palm Oil", "malaysian_crude_palm_oil_cme"),
        ("rapeseed oil", "rapeseed_oil_zce"),
        ("soybean meal", "soybean_meal_cbot"),
        ("read-across", None),                       # non-commodity phrase still declines
    ])
    def test_space_and_hyphen_forms_fold_to_curated_keys(self, spoken, slug) -> None:
        assert xcm.resolve_bare_commodity(spoken, frozenset()) == slug

    @pytest.mark.parametrize("spoken, slug", [
        # Trade-shorthand + possessive forms (2026-07-19 positive-pin failure: bare "palm" resolved None
        # and possessive spans from carried state / YAML never folded). Ambiguous shorthands stay None.
        ("palm", "malaysian_crude_palm_oil_cme"),
        ("palm's", "malaysian_crude_palm_oil_cme"),
        ("soyoil", "soybean_oil_cbot"),
        ("soybean oil's", "soybean_oil_cbot"),
        ("soymeal", "soybean_meal_cbot"),
        ("canola", "rapeseed_oil_zce"),
        ("rapeseed", "rapeseed_oil_zce"),
        ("soybean", "soybeans_cbot"),
        ("maize", None),                             # ambiguous: corn_cbot vs SAFEX white/yellow maize
        ("soy", None),                               # ambiguous: beans / meal / oil
    ])
    def test_trade_shorthand_and_possessive_forms(self, spoken, slug) -> None:
        assert xcm.resolve_bare_commodity(spoken, frozenset()) == slug

    def test_loaded_slug_passes_through(self) -> None:
        loaded = frozenset({"corn_cbot", "soybean_oil_cbot"})
        assert xcm.resolve_bare_commodity("corn_cbot", loaded) == "corn_cbot"

    @pytest.mark.parametrize("miss", ["sunflower_oil", "sorghum", "barley", "ddgs", "polyester", "cocoa", ""])
    def test_unknown_or_ambiguous_is_none(self, miss) -> None:
        # An unknown bare name, with an empty loaded set so slug pass-through can't rescue it.
        assert xcm.resolve_bare_commodity(miss, frozenset()) is None

    def test_none_input_is_none(self) -> None:
        assert xcm.resolve_bare_commodity(None) is None


# ── lint: happy path on the shipped config ──────────────────────────────────────────────────────────
class TestLintHappyPath:
    def test_shipped_complex_map_is_clean(self) -> None:
        assert cc.check_complex_map() == []


# ── lint: each rule via inline bad fixtures (the real yaml is never mutated) ─────────────────────────
def _base_pair():
    return xcm.iter_all_pairs()[0]  # soyoil_palm_vegoil -- a known-valid row


def _patch(monkeypatch, *pairs):
    monkeypatch.setattr(xcm, "iter_all_pairs", lambda: list(pairs))


class TestLintRules:
    def test_unloaded_pair_slug_flags(self, monkeypatch) -> None:
        bad = dataclasses.replace(_base_pair(), id="bad_loaded",
                                  pair=("soybean_oil_cbot", "not_a_real_contract"),
                                  side_b={"contract": "not_a_real_contract", "ref": "psd_ending_stock_su_ratio",
                                          "country_rule": "world"})
        _patch(monkeypatch, bad)
        errs = cc.check_complex_map()
        assert any("not a loaded contract" in e for e in errs)

    def test_same_psd_code_ban(self, monkeypatch) -> None:
        # soybean_oil_cbot (4232000) and soybean_oil_dce (4232000) share a PSD code -> vacuous fork.
        # RV-REGIONAL re-anchor (2026-08-29): B1 is FORK-KEYED now -- (code, scope) -- so two world
        # legs on one code still red (both keys (code,'world')) under the amended message; a same-code
        # pair whose two REGIONAL scopes differ is B1c-admitted (pinned below).
        bad = dataclasses.replace(_base_pair(), id="bad_samecode",
                                  pair=("soybean_oil_cbot", "soybean_oil_dce"),
                                  side_b={"contract": "soybean_oil_dce", "ref": "psd_ending_stock_su_ratio",
                                          "country_rule": "world"})
        _patch(monkeypatch, bad)
        errs = cc.check_complex_map()
        assert any("same-fork ban" in e for e in errs)

    def test_bad_ref_flags(self, monkeypatch) -> None:
        b = _base_pair()
        bad = dataclasses.replace(b, id="bad_ref",
                                  side_a={"contract": b.pair[0], "ref": "not_a_ref", "country_rule": "world"})
        _patch(monkeypatch, bad)
        errs = cc.check_complex_map()
        assert any("is not a live cascade_map ref" in e for e in errs)

    def test_non_world_country_rule_flags(self, monkeypatch) -> None:
        # RV-REGIONAL re-anchor (2026-08-29): the grammar widened to {world, regional}; anything else
        # (the refused `primary` shape included) still reds under the amended message, and a MIXED
        # world/regional pair reds its own C20 error (pinned in test_rv_regional).
        b = _base_pair()
        bad = dataclasses.replace(b, id="bad_country",
                                  side_a={"contract": b.pair[0], "ref": "psd_ending_stock_su_ratio",
                                          "country_rule": "primary"})
        _patch(monkeypatch, bad)
        errs = cc.check_complex_map()
        assert any("accepted values are 'world' and 'regional'" in e for e in errs)

    def test_bad_materiality_enum_flags(self, monkeypatch) -> None:
        bad = dataclasses.replace(_base_pair(), id="bad_mat", materiality_tier="bogus")
        _patch(monkeypatch, bad)
        errs = cc.check_complex_map()
        assert any("bad materiality_tier" in e for e in errs)

    def test_bad_direction_enum_flags(self, monkeypatch) -> None:
        bad = dataclasses.replace(_base_pair(), id="bad_dir", direction="sideways")
        _patch(monkeypatch, bad)
        errs = cc.check_complex_map()
        assert any("bad direction" in e for e in errs)

    def test_unresolvable_shared_event_flags(self, monkeypatch) -> None:
        # A pair between two REAL contracts with NO curated edge between them and a bogus shared_event.
        # rough_rice_cbot <-> cotton: distinct PSD codes, no inter_commodity edge either direction.
        bad = dataclasses.replace(_base_pair(), id="bad_event",
                                  pair=("rough_rice_cbot", "cotton"),
                                  shared_event="not_a_driver_or_edge",
                                  side_a={"contract": "rough_rice_cbot", "ref": "psd_ending_stock_su_ratio",
                                          "country_rule": "world"},
                                  side_b={"contract": "cotton", "ref": "psd_ending_stock_su_ratio",
                                          "country_rule": "world"})
        _patch(monkeypatch, bad)
        errs = cc.check_complex_map()
        assert any("shared_event" in e for e in errs)

    def test_shared_event_via_edge_passes(self, monkeypatch) -> None:
        # corn_cbot <-> soft_red_winter_wheat_cbot: no driver id 'x' but a curated edge exists between
        # them (bare->slug resolved), so rule 6 passes on the EDGE branch.
        ok = dataclasses.replace(_base_pair(), id="edge_ok",
                                 pair=("corn_cbot", "soft_red_winter_wheat_cbot"),
                                 shared_event="wheat_corn_spread",
                                 side_a={"contract": "corn_cbot", "ref": "psd_ending_stock_su_ratio",
                                         "country_rule": "world"},
                                 side_b={"contract": "soft_red_winter_wheat_cbot",
                                         "ref": "psd_ending_stock_su_ratio", "country_rule": "world"})
        _patch(monkeypatch, ok)
        assert cc.check_complex_map() == []


# ── palm marketing-year transform pre-fix (addendum P2) ─────────────────────────────────────────────
class TestPalmMarketingYear:
    def test_palm_mys_is_october(self) -> None:
        from leviathan.transforms.bronze_to_silver.usda_psd import _PSD_COMMODITY_TO_MYS
        assert _PSD_COMMODITY_TO_MYS[4243000] == 10          # was 11 (Nov); GAIN prints "Begins Oct"

    def test_palm_release_date_shifts_one_month_earlier(self) -> None:
        # Palm (4243000), month_code=1, market_year=2024:
        #   MYS=10 -> total = 10 + 1 - 2 = 9 -> cal_month = 9 % 12 + 1 = 10 (Oct), cal_year = 2024
        # (the prior MYS=11 gave Nov -- one month LATE).
        from leviathan.transforms.bronze_to_silver.usda_psd import _compute_psd_release_dates
        bronze = pd.DataFrame({
            "commodity_code": [4243000],
            "month_code":     [1],
            "market_year":    [2024],
        })
        out = _compute_psd_release_dates(bronze)
        assert out.iloc[0] == "2024-10-10"


class TestB1bCrossRowForkUniqueness:
    """RV roster phase 3 (2026-08-29): two MATERIAL rows on the same unordered PSD-code fork resolve to
    the SAME two World su_ratio series -- one print under two pair ids. Scoped to material on purpose:
    the contextual tier exists to RECORD refused duplicates (campinas_sorghum_feed vs corn_sorghum_feed)."""

    def test_cross_row_fork_duplicate_flags(self, monkeypatch) -> None:
        # Two MATERIAL rows on the SAME unordered fork (4232000, 4243000): soyoil_palm_vegoil and a
        # second row reaching the identical pair of World sheets through the DCE/olein slugs.
        base = _base_pair()
        dup = dataclasses.replace(
            base, id="dup_fork",
            pair=("soybean_oil_dce", "palm_olein_dce"),
            side_a={"contract": "soybean_oil_dce", "ref": "psd_ending_stock_su_ratio",
                    "country_rule": "world"},
            side_b={"contract": "palm_olein_dce", "ref": "psd_ending_stock_su_ratio",
                    "country_rule": "world"})
        _patch(monkeypatch, base, dup)
        errs = cc.check_complex_map()
        assert any("cross-row fork uniqueness (B1b)" in e and "dup_fork" in e for e in errs)

    def test_cross_row_fork_duplicate_exempt_when_deferred(self, monkeypatch) -> None:
        # The SAME collision at contextual tier is LEGAL -- how a refused duplicate is recorded.
        base = _base_pair()
        dup = dataclasses.replace(
            base, id="dup_fork_inert", materiality_tier="contextual",
            pair=("soybean_oil_dce", "palm_olein_dce"),
            side_a={"contract": "soybean_oil_dce", "ref": "psd_ending_stock_su_ratio",
                    "country_rule": "world"},
            side_b={"contract": "palm_olein_dce", "ref": "psd_ending_stock_su_ratio",
                    "country_rule": "world"})
        _patch(monkeypatch, base, dup)
        assert not any("B1b" in e for e in cc.check_complex_map())

    def test_authored_rows_have_unique_material_forks(self) -> None:
        # Whole-file guard on the REAL yaml (no monkeypatch): the shipped map must be B1b-clean.
        assert not any("B1b" in e for e in cc.check_complex_map())
