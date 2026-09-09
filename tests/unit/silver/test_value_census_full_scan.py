"""THE FLOOR LANDMINE and the STATS COIN-FLIP: the V001 census's full-family second opinion.

WHAT THE RCA LEFT ON THE DOCKET, and what was measured before writing any of this.

(1) THE COIN-FLIP. ``evaluate_gate`` raises KIND_STATS_UNAVAILABLE when ``files_with_stats == 0``,
    and the runner feeds it a census built from THREE files -- first, middle, last -- out of a
    partition group that can hold 161. Measured on the real ``silver_nass_annual`` footers before
    the pinned rewrite (2026-09-09): ``area_planted_ha`` was arrow ``null`` in 53 of corn's 161
    objects, 43 of cotton's 161, 34 of rice's 132, 13 of pima's 116 and 7 of upland's 110. Each of
    those five groups passed only because its three-file draw happened to include a typed file --
    "the other six commodities survive on luck", in the RCA's words. Cottonseed, 161 of 161, is the
    one that did not.

(2) THE FLOOR LANDMINE. The same three files decide the non-null FRACTION the floor is compared
    against, so the verdict moves when the group's file COUNT moves, on data that never changed.
    Sweeping every possible middle draw across those footers found THIRTEEN (group, column) pairs
    in the two NASS tables whose verdict is decided by the draw -- canola_ice production_mt and
    yield_t_ha (0.5556 today, 0.2000 at the worst draw, floor 0.5); corn / cotton / rice
    area_planted_ha (0.7259 / 0.7600 / 0.6667 today, 0.3630 / 0.4000 / 0.3182 worst); and seven in
    crop_progress including soft_red_winter_wheat's four pct_* columns, which read 0.0000 if the
    middle draw lands on year=1981.

THE OPTION TAKEN, AND THE HONEST STATEMENT OF WHAT IT DOES (corrected 2026-09-09 after a review
finding, MAJOR: an earlier draft of this header and of the handoff report read as though option (a)
retired the coin-flip of (1). IT DOES NOT.) Option (a) of the RCA: scan ALL files for the null-typed
detection, keep the value sampling at three. ``apply_full_scan`` therefore takes ONLY
``files_with_stats`` from the whole group -- a strictly monotone change, because the sample is a
SUBSET, so it can retire a stats_unavailable row and can never create one. But a file with no
statistics also books ZERO effective non-nulls (``has_stats`` False -> ``has_min_max`` False ->
``effective_nonnull`` 0), so a draw of three such files is ``all_nan`` by construction, and
``evaluate_gate`` tests ``all_nan`` on the very next line. Retiring the first row uncovers the
second. The pass is therefore VERDICT-INERT -- it RELABELS a hard KIND_STATS_UNAVAILABLE as a hard
KIND_ALL_NAN and changes no table's colour -- and ``test_the_full_scan_is_verdict_inert_on_every_
draw`` below pins that on the corn shape across all four draws. Which three objects the sampler
draws still decides (1), exactly as before. What the pass buys is REPORTING: an honest kind, the
whole-family fractions in the artifact, and the straddle WARN of (2) -- paid for with up to
``FULL_SCAN_MAX_FILES`` extra footer GETs per table inside a BLOCKING gate. The floor keeps reading
the sampled fraction ON PURPOSE: the OP-8 / D-SG floors were calibrated against that estimator, and
switching estimators under them refuses honest data. MEASURED: over all 280
``silver_nass_crop_progress`` footers cotton's ``pct_emerged`` reads 0.0305 non-null against its
calibrated 0.05 floor while its three-file sample reads 0.0552 -- a wholesale switch would have
turned a green table red on exactly what NASS published. So the whole-group fraction is COMPUTED
beside the sampled one and REPORTED when the two straddle a floor
(``evaluate_sample_divergence``), which is the live output of the first census run with this armed.
Re-deriving the floors against a full-family estimator is an OP-8 decision with its own evidence.

Options (b) and (c) were measured and rejected, with numbers: (b) rotating the sample by as-of
DETONATES the mine rather than removing it -- the rotation eventually draws mid=43 for corn (0.3630
against a 0.5 floor) and mid=0 for soft_red_winter_wheat (0.0000 against 0.25), turning a latent
accident into a scheduled red; (c) declaring the older-partition absences per (group, year-range)
speaks to the absence KINDS, not to a floor, and could not have reached a below-floor row at all.

Pure + AWS-free: the census functions take footer-derived records, and the sampler tests drive a
fake ``list_objects_v2``.
"""
from __future__ import annotations

import importlib

import pytest

from leviathan.silver.value_census import (
    ColumnCensus,
    FileColumnStat,
    KIND_ALL_NAN,
    KIND_NONNULL_BELOW_FLOOR,
    KIND_SAMPLE_UNREPRESENTATIVE,
    KIND_STATS_UNAVAILABLE,
    apply_full_scan,
    census_column,
    evaluate_gate,
    evaluate_sample_divergence,
)

runner = importlib.import_module("jobs.audit.value_census")

TABLE = "silver_nass_annual"
COL = "area_planted_ha"


def _typed(rows: int, nulls: int) -> FileColumnStat:
    """A file whose column carries the declared type and real statistics."""
    return FileColumnStat(column=COL, total_rows=rows, null_count=nulls,
                          has_min_max=nulls < rows, min_value=1.0, max_value=2.0, has_stats=True)


def _nulltyped(rows: int) -> FileColumnStat:
    """A file written as arrow ``null``: rows counted, NO Statistics struct at all."""
    return FileColumnStat(column=COL, total_rows=rows, null_count=0, has_min_max=False,
                          has_stats=False)


# ---------------------------------------------------------------------------
# 1. THE COIN-FLIP: relabelled, NOT retired.
# ---------------------------------------------------------------------------
def test_the_three_file_sample_can_hard_fail_a_group_that_is_mostly_typed():
    """The defect first, on the corn ``area_planted_ha`` shape: 53 of 161 objects null-typed, and a
    draw that happens to take three of them raises KIND_STATS_UNAVAILABLE on a column that is a
    populated double in 108 files."""
    unlucky = census_column([_nulltyped(20), _nulltyped(20), _nulltyped(20)], COL)
    rows = evaluate_gate(TABLE, {COL: unlucky}, [COL], 0.5)
    assert [r.kind for r in rows] == [KIND_STATS_UNAVAILABLE]


def test_the_full_family_scan_retires_that_row_without_touching_anything_else():
    unlucky = census_column([_nulltyped(20), _nulltyped(20), _nulltyped(20)], COL)
    whole_group = census_column([_nulltyped(20)] * 53 + [_typed(20, 1)] * 108, COL)
    merged = apply_full_scan(unlucky, whole_group)
    assert merged.files_with_stats == 108                 # the ONLY field that moves
    assert merged.total_rows == unlucky.total_rows
    assert merged.null_count == unlucky.null_count
    assert merged.nonnull_fraction == unlucky.nonnull_fraction
    assert merged.files_sampled == unlucky.files_sampled == 3
    # the hard row is gone, and the group is not silently green either -- it is now all_nan on the
    # sampled rows, the honest statement about what those three files hold.
    assert [r.kind for r in evaluate_gate(TABLE, {COL: merged}, [COL], 0.5)] == [KIND_ALL_NAN]


def test_a_real_total_absence_still_fails_after_the_full_scan():
    """Cottonseed: 161 of 161 objects null-typed. 0/3 becomes 0/161 and the row STANDS -- to be
    narrated by the registry declaration, never waved through by this pass."""
    sampled = census_column([_nulltyped(17)] * 3, COL)
    whole_group = census_column([_nulltyped(17)] * 161, COL)
    merged = apply_full_scan(sampled, whole_group)
    assert merged.files_with_stats == 0
    assert [r.kind for r in evaluate_gate(TABLE, {COL: merged}, [COL], 0.5)] == [KIND_STATS_UNAVAILABLE]


@pytest.mark.parametrize("sampled_stats,full_stats", [(0, 0), (0, 5), (2, 2), (3, 161)])
def test_the_merge_is_monotone_and_can_never_create_a_hard_row(sampled_stats, full_stats):
    """THE SAFETY ARGUMENT, pinned rather than asserted in prose: the sampled files are a SUBSET of
    the group, so the full count is never smaller, and replacing the smaller with the larger can
    only remove a stats_unavailable row. If this property ever breaks, arming the scan becomes a
    change that can newly refuse a chain -- which is exactly what it must never be."""
    sampled = census_column([_typed(10, 0)] * sampled_stats
                            + [_nulltyped(10)] * (3 - sampled_stats), COL)
    whole = census_column([_typed(10, 0)] * full_stats
                          + [_nulltyped(10)] * max(0, 161 - full_stats), COL)
    merged = apply_full_scan(sampled, whole)
    before = {r.kind for r in evaluate_gate(TABLE, {COL: sampled}, [COL], 0.5)}
    after = {r.kind for r in evaluate_gate(TABLE, {COL: merged}, [COL], 0.5)}
    assert KIND_STATS_UNAVAILABLE not in (after - before)


@pytest.mark.parametrize("drawn_nulltyped,before,after", [
    (0, None, None),                                        # GREEN both sides
    (1, None, None),                                        # GREEN both sides (0.6667 > 0.5)
    (2, KIND_NONNULL_BELOW_FLOOR, KIND_NONNULL_BELOW_FLOOR),  # sampled 0.3333, unchanged
    (3, KIND_STATS_UNAVAILABLE, KIND_ALL_NAN),              # the ONLY move the scan can make
])
def test_the_full_scan_is_verdict_inert_on_every_draw(drawn_nulltyped, before, after):
    """THE CORRECTED CLAIM, pinned (review finding 2026-09-09, MAJOR). Over the corn
    ``area_planted_ha`` shape -- 161 objects, 53 arrow-null, whole-family non-null fraction 0.6708,
    floor 0.5 -- every possible 3-file draw gives the SAME COLOUR before and after the full-family
    scan. The single row that moves is a hard KIND_STATS_UNAVAILABLE becoming a hard KIND_ALL_NAN:
    an honest kind for the same refusal, not a retired refusal. If this parametrization ever needs
    a green/red pair, the scan has stopped being reporting and become a fence, and the handoff
    sentence about it has to be rewritten with it."""
    sampled = census_column([_nulltyped(17)] * drawn_nulltyped
                            + [_typed(17, 0)] * (3 - drawn_nulltyped), COL)
    whole = census_column([_nulltyped(17)] * 53 + [_typed(17, 0)] * 108, COL)
    assert round(whole.nonnull_fraction, 4) == 0.6708
    got_before = [r.kind for r in evaluate_gate(TABLE, {COL: sampled}, [COL], 0.5)]
    got_after = [r.kind for r in
                 evaluate_gate(TABLE, {COL: apply_full_scan(sampled, whole)}, [COL], 0.5)]
    assert got_before == ([] if before is None else [before])
    assert got_after == ([] if after is None else [after])
    assert bool(got_before) == bool(got_after)              # the colour NEVER flips


def test_no_scan_leaves_the_census_exactly_as_it_was():
    """Fail-open: a table past the object cap, or a listing that failed, must behave identically to
    the census before this pass existed."""
    sampled = census_column([_nulltyped(20)] * 3, COL)
    assert apply_full_scan(sampled, None) is sampled


# ---------------------------------------------------------------------------
# 2. THE FLOOR LANDMINE: computed and reported, never decided.
# ---------------------------------------------------------------------------
def _census(fraction: float, files: int, rows: int = 1000) -> ColumnCensus:
    nonnull = int(round(fraction * rows))
    return ColumnCensus(column=COL, total_rows=rows, null_count=rows - nonnull,
                        nonnull_fraction=fraction, all_nan=False, all_constant=False,
                        constant_value=None, sentinel_saturated=False, distinct_lower_bound=2,
                        min_value=0.0, max_value=1.0, files_sampled=files, files_with_stats=files)


def test_a_sample_that_reads_better_than_its_family_is_reported():
    """THE LIVE ONE, from the first run with the scan armed: crop_progress cotton ``pct_emerged``
    reads 0.0552 over its 3 sampled files and 0.0305 over all 46, against a 0.05 floor. The gate
    verdict does not move; the row says so, and carries both numbers."""
    rows = evaluate_sample_divergence(
        "silver_nass_crop_progress", {COL: _census(0.0552, 3)}, {COL: _census(0.0305, 46)},
        [COL], 0.5, floor_overrides={COL: 0.05})
    assert len(rows) == 1
    r = rows[0]
    assert r.kind == KIND_SAMPLE_UNREPRESENTATIVE
    assert "0.0552" in r.detail and "0.0305" in r.detail and "BELOW" in r.detail
    assert r.threshold == 0.05


def test_a_sample_that_reads_worse_than_its_family_is_reported_too():
    """The false-RED direction. The instrument is symmetric on purpose: a group refused because its
    three files were the thin ones is the same defect wearing the other sign."""
    rows = evaluate_sample_divergence(TABLE, {COL: _census(0.36, 3)}, {COL: _census(0.65, 161)},
                                      [COL], 0.5)
    assert len(rows) == 1 and "ABOVE" in rows[0].detail


def test_agreement_says_nothing():
    """Corn's real numbers today: 0.7259 sampled, 0.6499 over all 161, floor 0.5. Both sides of the
    same verdict -- a divergence row here would be noise, and noise is how a warn list stops being
    read."""
    assert evaluate_sample_divergence(TABLE, {COL: _census(0.7259, 3)},
                                      {COL: _census(0.6499, 161)}, [COL], 0.5) == []


def test_the_divergence_row_is_a_warning_and_never_reaches_the_gate():
    """The hard gate is ``evaluate_gate`` and it has never heard of this kind. A group whose whole
    family sits below the floor while its sample sits above still PASSES -- that is the point:
    the measurement is published, the calibration decision stays with OP-8."""
    sampled = _census(0.0552, 3)
    assert evaluate_gate("silver_nass_crop_progress", {COL: sampled}, [COL], 0.5,
                         floor_overrides={COL: 0.05}) == []
    below = evaluate_gate("silver_nass_crop_progress", {COL: _census(0.0305, 46)}, [COL], 0.5,
                          floor_overrides={COL: 0.05})
    assert [r.kind for r in below] == [KIND_NONNULL_BELOW_FLOOR]   # ...had we switched estimators


def test_no_second_opinion_produces_no_row():
    """Past the cap there is no full census, and a 'full' scan no larger than the sample is not a
    second opinion -- neither may invent a divergence."""
    assert evaluate_sample_divergence(TABLE, {COL: _census(0.6, 3)}, {}, [COL], 0.5) == []
    assert evaluate_sample_divergence(TABLE, {COL: _census(0.6, 3)}, {COL: _census(0.2, 3)},
                                      [COL], 0.5) == []


def test_a_column_with_no_floor_at_all_is_not_censused_for_divergence():
    assert evaluate_sample_divergence(TABLE, {COL: _census(0.6, 3)}, {COL: _census(0.2, 161)},
                                      [COL], None) == []


# ---------------------------------------------------------------------------
# 3. THE VACUOUS SAMPLE: a census that read nothing passed everything.
# ---------------------------------------------------------------------------
class _FakeS3:
    """A ``list_objects_v2`` over a fixed key list, paged at the caller's MaxKeys."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.calls = 0

    def list_objects_v2(self, **kw):
        self.calls += 1
        start = int(kw.get("ContinuationToken") or 0)
        n = kw["MaxKeys"]
        page = [k for k in self.keys[start:start + n] if k.startswith(kw["Prefix"])]
        out = {"Contents": [{"Key": k} for k in page]}
        if start + n < len(self.keys):
            out["NextContinuationToken"] = str(start + n)
        return out


def test_a_prefix_whose_first_pages_are_all_control_plane_used_to_sample_nothing():
    """MEASURED ON THE LIVE ESTATE, 2026-09-09. ``silver_modis_ndvi`` publishes under
    ``silver/weather/source=modis_ndvi/``, whose ``_manifests/`` and ``_shadow/`` children sort
    BEFORE ``commodity=`` ('_' is 0x5F, 'c' is 0x63), and hold 10,525 hidden parquets. The 6-page x
    400-key LIST window was entirely consumed by them, ``_parquets_under`` returned [], and that
    table's value census printed "PASS files=0 gate_rows=0" every run -- a census that reads
    nothing passes anything, on the LARGEST silver table in the estate (10,532 canonical objects).
    Same vacuity class as the parity gate's SPEC-INVALID panel in this same RCA.

    Of all 52 registry tables, exactly four sampled zero files and three of those
    (silver_ams_gtr, silver_eex_freight, silver_moex_agro_indices) hold no canonical objects at
    all. modis was the only false green."""
    pfx = "silver/weather/source=modis_ndvi/"
    hidden = [f"{pfx}_shadow/commodity=c/region=r{i}/part-000.parquet" for i in range(2400)]
    real = [f"{pfx}commodity=corn_cbot/region=r{i}/part-000.parquet" for i in range(40)]
    s3 = _FakeS3(hidden + real)
    got = runner._parquets_under(s3, pfx, per_group=4)
    assert len(got) == 4, "the window must keep paging while it has found NOTHING"
    assert all(not runner._is_hidden(k) for k in got)
    assert got[0] == real[0] and got[-1] == real[-1]      # still first .. last, era-spread


def test_the_extension_is_inert_wherever_the_window_already_found_data():
    """The safety argument for touching a sampler every gate depends on: a prefix that yields at
    least one parquet inside the first six pages gets the BYTE-IDENTICAL key list, so the spread
    indices and the sampled objects do not move. Verified against the live estate as well --
    sample_groups returned identical keys for 51 of 52 tables, modis being the one that moved
    (0 -> 4 files)."""
    pfx = "silver/nass_annual/"
    keys = [f"{pfx}commodity=corn_cbot/year={1866 + i}/part-000.parquet" for i in range(3000)]
    s3 = _FakeS3(keys)
    got = runner._parquets_under(s3, pfx, per_group=3)
    assert got == [keys[0], keys[1200], keys[2399]]       # exactly the 6 x 400 window's spread
    assert s3.calls == 6                                  # ...and it stopped at the page cap


# ---------------------------------------------------------------------------
# 4. The full-family listing is bounded, or it does not happen.
# ---------------------------------------------------------------------------
def test_a_family_past_the_cap_is_not_scanned_at_all():
    """Whole or not at all: a half-scanned group's ``files_with_stats`` would be neither the
    sample's claim nor the family's -- a third estimator, which is what this pass exists to remove.
    Measured cap rationale: 2,000 covers 50 of 52 tables and 8,218 objects estate-wide; the two that
    fall back (modis 10,532, production 4,478) are the only ones that could make it expensive."""
    pfx = "silver/big/"
    s3 = _FakeS3([f"{pfx}commodity=c/year={i}/part-000.parquet" for i in range(5000)])
    assert runner.full_scan_groups(s3, {"commodity=c": ["x"]}, pfx, cap=2000) == {}


def test_a_family_under_the_cap_is_scanned_whole():
    pfx = "silver/small/"
    keys = [f"{pfx}commodity=c/year={i}/part-000.parquet" for i in range(300)]
    s3 = _FakeS3(keys)
    out = runner.full_scan_groups(s3, {"commodity=c": [keys[0]]}, pfx, cap=2000)
    assert out == {"commodity=c": keys}


def test_the_scan_never_invents_a_group_the_gate_does_not_evaluate():
    """Keyed off the sampler's own groups, so a prefix the projection enum excludes can never
    acquire a verdict through this back door."""
    pfx = "silver/t/"
    keys = ([f"{pfx}commodity=declared/year={i}/part-000.parquet" for i in range(5)]
            + [f"{pfx}commodity=undeclared/year={i}/part-000.parquet" for i in range(5)])
    s3 = _FakeS3(keys)
    out = runner.full_scan_groups(s3, {"commodity=declared": [keys[0]]}, pfx, cap=2000)
    assert list(out) == ["commodity=declared"] and len(out["commodity=declared"]) == 5
