"""SILVER-F082: the DAG catalog family derivation.

Every registry table must map to exactly one orchestration family (completeness both ways), the
generation-only model_output family must be flagged non-backfillable, and the interim freshness
ceiling must fold in the publication-lag grace.
"""
from __future__ import annotations

import pytest

from leviathan.silver.dag_catalog import (
    build_catalog,
    effective_sla_lag_days,
    family_of,
)
from leviathan.silver.registry import load_registry


@pytest.fixture(scope="module")
def registry():
    return load_registry()


@pytest.fixture(scope="module")
def catalog(registry):
    return build_catalog(registry)


class TestCompleteness:
    def test_every_registry_table_maps_to_exactly_one_family(self, registry, catalog):
        mapped = [t for f in catalog.values() for t in f.tables]
        # exactly once each
        assert sorted(mapped) == registry.names()
        assert len(mapped) == len(set(mapped)), "a table appears in two families"

    def test_family_of_is_total_over_the_registry(self, registry):
        for name in registry.names():
            assert family_of(name)  # never raises

    def test_unknown_table_raises(self):
        with pytest.raises(KeyError):
            family_of("silver_not_a_real_table_xyz")

    def test_expected_family_groupings(self, catalog):
        assert catalog["usda_esr"].tables == ("silver_esr", "silver_esr_compact")
        assert "gold_weather_z" in catalog["weather"].tables
        assert "silver_nasa_power" in catalog["weather"].tables
        assert set(catalog["noaa_climate"].tables) == {"silver_noaa_iod", "silver_noaa_oni"}


class TestBackfillFlag:
    def test_model_output_is_generation_only(self, catalog):
        assert catalog["model_output"].backfillable is False
        assert catalog["model_output"].tables == ("silver_model_predictions",)

    def test_source_families_are_backfillable(self, catalog):
        for key in ("usda_esr", "weather", "usda_wasde", "mpoc"):
            assert catalog[key].backfillable is True


class TestFreshnessSla:
    def test_esr_folds_publication_lag_grace(self, registry):
        # BF-W2 SILVER-F031: ESR runs per-week vintage semantics with publication_lag_days 0 (the
        # as_of stamp IS the publication event), so the grace term vanishes and the ceiling is the
        # bare weekly cadence default (14). Pre-flip: 14 + 7 = 21 -- the freshness alarm TIGHTENS
        # (mirrored in infra/.../silver_observability.auto.tfvars.json usda_esr).
        esr = registry.table("silver_esr")
        assert esr["publication_lag_days"] == 0            # the grace input this derivation folds
        lag, basis = effective_sla_lag_days(esr)
        assert lag == 14
        assert basis == "cadence_default:weekly"

    def test_catalog_family_takes_tightest_member(self, catalog):
        # weather mixes daily + monthly members -> tightest (daily=3) wins.
        assert catalog["weather"].max_sla_lag_days == 3

    def test_futures_carries_explicit_weekend_grace_ceiling(self, registry, catalog):
        # SEAM-C prerequisite: the yfinance futures chain is a MON-FRI 23:00 cron, so the bare
        # daily cadence default (3d) false-fires over a weekend (a Fri-close write is ~3d old by
        # Monday). The explicit max_lag_days=5 spans a weekend + one missed weekday while still
        # tripping a genuine multi-day stall (the class of the 2026-06-05 dark-chain stall).
        # SEAM-C numbers wiring (2026-07-22): the futures card was wired into the numbers registry with
        # publication_lag_days=1 (the settle for trading date D is public D+1). effective_sla_lag_days
        # ADDS the publication lag as grace (so the alarm never fires on the normal +1 publish delay), so
        # the EFFECTIVE ceiling is now 5 (explicit) + 1 (numbers pub-lag grace) = 6. The explicit
        # freshness_sla.max_lag_days stays 5; only the effective/family ceiling picks up the grace.
        c = registry.table("silver_futures_prices")
        assert c["freshness_sla"]["max_lag_days"] == 5
        lag, basis = effective_sla_lag_days(c)
        assert lag == 6                               # 5 explicit + 1 numbers publication_lag_days grace
        assert basis == "registry.max_lag_days"      # explicit, not the daily cadence default (3)
        assert catalog["futures"].max_sla_lag_days == 6

    def test_every_backfillable_family_has_a_positive_ceiling(self, catalog):
        for f in catalog.values():
            assert f.max_sla_lag_days > 0
