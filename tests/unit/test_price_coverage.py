"""W2b-D2/D3 -- PRICE_COVERAGE_START and the deterministic routing rule.

The map is the per-contract floor of ``silver_futures_eod``, MEASURED from the canonical bytes
rather than transcribed from the plan's per-source prose. These tests pin the two things that
measuring bought (a per-slug floor rather than a per-source one) and the three routing verdicts,
because "straddling declines" is the rule that stops a per-contract series being spliced onto a
roll-spliced continuous one.
"""
from __future__ import annotations

from datetime import date

import pytest
from leviathan.silver import futures_eod_contracts as FC


class TestTheMapIsMeasuredNotAssumed:
    def test_every_covered_slug_is_a_real_contract(self):
        """A floor for a slug that is not in CONTRACT_MAP would be a coverage claim about
        something the estate cannot even name."""
        assert set(FC.PRICE_COVERAGE_START) <= set(FC.CONTRACT_MAP)
        assert FC.PRICE_COVERAGE_START, "the map must not be empty-by-accident"

    def test_kcbt_carries_its_own_floor_not_the_glbx_blanket(self):
        """THE reason this map is per-slug. The plan gives GLBX a blanket 2010-06-06, but KCBT
        joined GLBX later and its first canonical row is 2014-01-02. A per-source floor would have
        claimed three and a half years of coverage that does not exist -- the same shape as the
        CEPEA nine-year hole, which was also a prose claim nobody measured."""
        kcbt = FC.PRICE_COVERAGE_START["hard_red_winter_wheat_kcbt"]
        glbx_siblings = [FC.PRICE_COVERAGE_START[s] for s in
                         ("corn_cbot", "soybeans_cbot", "soft_red_winter_wheat_cbot")]
        assert kcbt == date(2014, 1, 2)
        assert all(kcbt > sib for sib in glbx_siblings)

    def test_the_ice_floor_is_the_measured_day(self):
        # The plan says 2018-12-23; the bytes say the 24th. The bytes win.
        for slug in ("arabica_coffee", "cocoa", "raw_sugar", "cotton"):
            assert FC.PRICE_COVERAGE_START[slug] == date(2018, 12, 24)

    def test_the_cash_references_carry_their_own_long_history(self):
        assert FC.PRICE_COVERAGE_START["brazilian_arabica_coffee"] == date(1996, 9, 2)
        assert FC.PRICE_COVERAGE_START["campinas_corn_reference_bmf"] == date(2004, 8, 2)

    def test_an_unlanded_venue_is_ABSENT_rather_than_permissive(self):
        """The three W1c browser venues have no canonical data, so they must have no floor. An
        entry with an optimistic date would serve a curve for a venue whose bytes never landed."""
        w1c = [s for s, rec in FC.CONTRACT_MAP.items()
               if rec["source"] in ("dce", "euronext_matif", "bursa")]
        assert w1c, "fixture guard: the W1c slugs should exist in CONTRACT_MAP"
        for slug in w1c:
            assert slug not in FC.PRICE_COVERAGE_START


class TestCoverageStartFailsClosed:
    def test_a_known_slug_returns_its_floor(self):
        assert FC.coverage_start_for("corn_cbot") == FC.PRICE_COVERAGE_START["corn_cbot"]

    def test_an_unmapped_slug_raises_rather_than_defaulting(self):
        with pytest.raises(ValueError, match="no PRICE_COVERAGE_START"):
            FC.coverage_start_for("not_a_contract")

    def test_an_unlanded_venue_raises_too(self):
        """The failure mode this prevents: a permissive default would read as 'covered since
        forever' for precisely the venues that have no data at all."""
        w1c = next(s for s, rec in FC.CONTRACT_MAP.items() if rec["source"] == "dce")
        with pytest.raises(ValueError):
            FC.coverage_start_for(w1c)


class TestTheRoutingRule:
    SLUG = "corn_cbot"          # floor 2010-06-06

    def test_a_window_after_the_floor_serves(self):
        assert FC.covers(self.SLUG, date(2020, 1, 1), date(2020, 3, 1)) == "serve"

    def test_a_window_starting_exactly_on_the_floor_serves(self):
        floor = FC.PRICE_COVERAGE_START[self.SLUG]
        assert FC.covers(self.SLUG, floor, date(2011, 1, 1)) == "serve"

    def test_a_window_entirely_before_the_floor_is_legacy(self):
        assert FC.covers(self.SLUG, date(1998, 1, 1), date(1999, 1, 1)) == "legacy"

    def test_a_window_ending_the_day_before_the_floor_is_still_legacy(self):
        floor = FC.PRICE_COVERAGE_START[self.SLUG]
        day_before = date(floor.year, floor.month, floor.day - 1)
        assert FC.covers(self.SLUG, date(2000, 1, 1), day_before) == "legacy"

    def test_a_straddling_window_DECLINES(self):
        """The rule that matters. Splicing a per-contract series onto a roll-spliced continuous one
        yields a number that means neither thing -- the same class of error as an event-study
        magnitude computed across an undocumented roll."""
        assert FC.covers(self.SLUG, date(2009, 1, 1), date(2012, 1, 1)) == "straddle"

    def test_a_window_straddling_by_one_day_still_declines(self):
        floor = FC.PRICE_COVERAGE_START[self.SLUG]
        day_before = date(floor.year, floor.month, floor.day - 1)
        assert FC.covers(self.SLUG, day_before, floor) == "straddle"

    def test_timestamps_are_accepted_as_well_as_dates(self):
        import pandas as pd
        got = FC.covers(self.SLUG, pd.Timestamp("2020-01-01"), pd.Timestamp("2020-03-01"))
        assert got == "serve"
