"""D-PR-23 (Option E) -- MATIF is DECLARED UNARMED, and the declaration has teeth.

The plan's workstream (a) chose Option E: do not arm the Euronext/MATIF browser leg, do not remove
it, and FORMALIZE the status quo so the absence reads as a decision rather than a gap. The
declaration lives at ``configs/silver/dags/unarmed/futures_eod_browser.json``.

A declaration nobody checks is prose. These tests are what make it a fence, and they fire in both
directions:

  * DRIFT TOWARD ARMING -- if a ``futures_eod_browser`` descriptor, gate entry or tfvars schedule
    appears while the declaration still says ``armed: false``, the arm happened without the
    declaration being retired. The whole point of Option E is that arming is a separate, gated,
    reviewed decision (probe S3 first), so an arm that slips in quietly is the failure this pins.
  * ROT IN THE DECLARATION -- if the declared slug set stops matching CONTRACT_MAP's
    ``euronext_matif`` set, or the mirrored row floors drift from the code that owns them, the file
    has become a stale story about a leg that changed underneath it.

And the behavioural half: MATIF contracts must DECLINE, not ERROR. ``coverage_start_for`` raising
is the fail-closed seam, but the raise must never reach a caller -- ``futures_eod_route`` catches it
and returns ``('uncovered', None)``, which the executor turns into ``status='declined'`` with a
verbatim scope_note before any SQL compiles. That is what "every lookup declines honestly" means,
and it is why arming the ingest and flipping the answer are separable.

Hermetic: JSON + pure functions. No AWS, no Athena, no network.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from leviathan.silver import futures_eod_contracts as FC

_REPO = Path(__file__).resolve().parents[3]
_DAGS = _REPO / "configs" / "silver" / "dags"
_MARKER = _DAGS / "unarmed" / "futures_eod_browser.json"
_TFVARS = _REPO / "infra" / "terraform" / "envs" / "dev" / "dag_schedules.auto.tfvars.json"
_SCHEDULE = "futures_eod_browser"
_MATIF_SOURCE = "euronext_matif"
_TABLE = "silver_futures_eod"


@pytest.fixture(scope="module")
def marker() -> dict:
    return json.loads(_MARKER.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location(
        "futures_eod_gate", _REPO / "scripts" / "silver" / "futures_eod_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "gen_sfn_inputs", _REPO / "scripts" / "silver" / "gen_sfn_inputs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _matif_slugs() -> list[str]:
    return sorted(s for s, rec in FC.CONTRACT_MAP.items() if rec["source"] == _MATIF_SOURCE)


def _q(slug: str, **kw):
    """One MATIF lookup, shaped like the executor's forced spec (tests/unit/test_futures_eod.py)."""
    from leviathan.graphrag.numbers import query as Q
    base = dict(table=_TABLE, metric="settle", asof="2026-07-15", commodity=slug, agg="latest")
    base.update(kw)
    return Q.NumberQuery(**base)


class TestTheDeclarationExists:
    def test_the_marker_declares_the_schedule_unarmed(self, marker):
        assert marker["schedule"] == _SCHEDULE
        assert marker["kind"] == "declared_unarmed"
        assert marker["armed"] is False
        assert marker["family"] == "futures_eod"

    def test_probe_s3_is_named_as_the_arming_gate(self, marker):
        """The single fact this file exists to carry. Probe S3 (Euronext SETTL. semantics) is
        UNRUN, and settle_kind='settlement' is pinned on the strength of it -- so if SETTL. is T-1
        at capture time the leg is off by one session and no downstream check can see it. A
        declaration that omitted the gate would just be a note saying 'not done yet'."""
        gate_rec = marker["arming_gate"]
        assert gate_rec["probe"] == "S3"
        assert "SETTL." in gate_rec["question"]
        assert "off by one" in gate_rec["why_it_blocks"]
        # And it must not be read as an auto-arm trigger.
        assert "does NOT arm anything by itself" in gate_rec["on_resolution"]

    def test_the_arm_checklist_is_present_and_names_the_census_seed(self, marker):
        """Option A's preconditions are non-negotiable; the census seed is the one whose omission
        is a GUARANTEED self-inflicted alert (silver_rebuild_gate FAILS CLOSED on an absent
        baseline, so an unseeded new schedule REDs on its very first fire)."""
        items = marker["arm_preconditions"]["items"]
        assert len(items) >= 4
        blob = " ".join(items)
        assert f"rolling/{_SCHEDULE}/census.json" in blob
        assert "BEFORE the first fire" in blob
        assert "_DAG_SCHEDULES" in blob

    def test_the_orphan_raw_objects_have_a_written_disposition(self, marker):
        """The three 2026-07-29 captures are the ONLY source=euronext objects, so any future
        'raw present, silver absent' detector reads them as a stalled leg unless the disposition
        is written down."""
        orphans = marker["orphan_raw_objects"]
        assert orphans["count"] == 3
        assert orphans["as_of_date"] == "2026-07-29"
        assert orphans["disposition"].startswith("RETAIN")
        assert "detector" in orphans["detector_note"].lower()

    def test_the_flip_is_declared_a_separate_decision(self, marker):
        """Probe S3 gates the ARM. Adding a PRICE_COVERAGE_START entry is the FLIP (D-PR-24,
        after R6). Conflating them is how a probe result turns into a serving change."""
        assert "D-PR-24" in marker["serving_disposition"]["flip_is_a_separate_decision"]


class TestTheAbsenceIsRealAndStaysReal:
    """The declaration says no schedule is intended. These fire if one appears anyway."""

    def test_there_is_no_top_level_descriptor(self):
        assert not (_DAGS / f"{_SCHEDULE}.json").exists(), (
            f"a {_SCHEDULE} chain descriptor appeared while "
            f"configs/silver/dags/unarmed/{_SCHEDULE}.json still declares armed=false -- either "
            f"the arm skipped its gate (probe S3) or the declaration was never retired")

    def test_the_generator_does_not_enumerate_the_schedule(self, gen):
        """load_descriptors globs dags/*.json NON-recursively, so the marker itself must be
        invisible to it -- a marker at the top level would be linted as a descriptor and, worse,
        rendered into an SFN input."""
        loaded = gen.load_descriptors()
        assert _SCHEDULE not in loaded
        assert _MARKER.parent != _DAGS, "the marker must live in a subdir, out of the descriptor glob"

    def test_there_is_no_rendered_input_or_schedule(self):
        rendered = _DAGS / "_rendered"
        assert not (rendered / f"{_SCHEDULE}.input.json").exists()
        assert not (rendered / f"{_SCHEDULE}.schedule.json").exists()

    def test_the_gate_does_not_carry_the_schedule(self, gate):
        """futures_eod_gate._DAG_SCHEDULES is gate 8's chain list. Option A adds the third entry;
        while the declaration stands there must be exactly the two live chains."""
        assert _SCHEDULE not in gate._DAG_SCHEDULES
        assert set(gate._DAG_SCHEDULES) == {"futures_eod_databento", "futures_eod_free"}

    def test_terraform_arms_no_such_schedule(self):
        """dag_schedules.auto.tfvars.json is what ACTUALLY arms a fire. This is the assertion that
        catches an arm that landed everywhere else quietly."""
        tfvars = json.loads(_TFVARS.read_text(encoding="utf-8"))
        armed = tfvars["dag_schedules"]
        # non-vacuity: the two LIVE futures_eod chains must be here, or this assertion is reading
        # the wrong shape and would pass on an empty dict.
        assert {"futures_eod_databento", "futures_eod_free"} <= set(armed)
        assert _SCHEDULE not in armed


class TestTheDeclarationMatchesTheCode:
    """A stale declaration is worse than none -- it asserts a state that has moved."""

    def test_the_declared_slugs_are_exactly_the_matif_contracts(self, marker):
        assert sorted(marker["leg"]["slugs"]) == _matif_slugs()
        assert _matif_slugs(), "fixture guard: CONTRACT_MAP must carry the euronext_matif slugs"

    def test_the_declared_slugs_are_lint_bound_contracts(self, marker):
        """'Built and lint-bound' is half the claim: the contracts EXIST and are auditable; only
        the data does not."""
        for slug in marker["leg"]["slugs"]:
            rec = FC.contract_for(slug)
            assert rec["source"] == _MATIF_SOURCE
            assert rec["unit"] in FC.UNITS and rec["currency"] == "EUR"

    def test_the_mirrored_row_floors_match_their_owning_module(self, marker):
        """The marker mirrors EURONEXT_MIN_ROWS for readability. A mirror that drifts is a lie, so
        it is pinned to the module that owns it."""
        from leviathan.transforms.raw_to_bronze.euronext_eod import EURONEXT_MIN_ROWS
        assert marker["row_floors_if_armed"]["per_product_bronze"] == EURONEXT_MIN_ROWS

    def test_the_mirrored_per_day_silver_floor_matches_the_producer(self, marker):
        from jobs.batch import futures_eod_task as T
        assert (marker["row_floors_if_armed"]["per_day_silver"]
                == T._MIN_SILVER_ROWS_PER_DAY_EURONEXT)


class TestMatifDeclinesRatherThanErrors:
    """The behavioural half of Option E: the status quo is not 'broken', it is HONEST."""

    def test_no_matif_slug_has_a_coverage_floor(self):
        for slug in _matif_slugs():
            assert slug not in FC.PRICE_COVERAGE_START, (
                f"{slug} gained a PRICE_COVERAGE_START entry -- that is the D-PR-24 FLIP, which is "
                f"deferred and gated after R6, not something the arm carries with it")

    def test_coverage_start_for_fails_closed_on_every_matif_slug(self):
        """The fail-closed seam. It must RAISE (never return a permissive default), because a
        default would read as 'covered since forever' for the one venue with zero rows."""
        for slug in _matif_slugs():
            with pytest.raises(ValueError, match="no PRICE_COVERAGE_START"):
                FC.coverage_start_for(slug)

    def test_the_route_declines_instead_of_propagating_the_raise(self):
        """THE PIN. The ValueError above must never reach a caller: futures_eod_route catches it
        and returns ('uncovered', None). A MATIF ask is a decline, not a 500."""
        from leviathan.graphrag.numbers import agent as na
        for slug in _matif_slugs():
            assert na.futures_eod_route(_q(slug)) == ("uncovered", None), slug

    def test_the_uncovered_route_is_a_declining_class_with_a_verbatim_note(self):
        """The executor declines on any route in FUTURES_EOD_COVERAGE_CLASSES -- BEFORE any SQL
        compiles -- and stamps the model-facing note on the payload."""
        from leviathan.graphrag.numbers import agent as na
        assert "uncovered" in na.FUTURES_EOD_COVERAGE_CLASSES
        note = na.futures_eod_coverage_note("uncovered", None)
        assert note.startswith("COVERAGE DECLINE --")
        assert "no per-delivery-month record" in note

    def test_a_windowed_matif_ask_declines_the_same_way(self):
        """Every window shape lands on the same verdict while the floor is absent -- there is no
        window that accidentally serves."""
        from leviathan.graphrag.numbers import agent as na
        slug = _matif_slugs()[0]
        for kwargs in ({"agg": "series", "period_start": "2020-01-02", "period_end": "2020-03-02"},
                       {"agg": "series", "period_start": "1990-01-02", "period_end": "1991-01-02"},
                       {"asof": "2026-07-29"}):
            assert na.futures_eod_route(_q(slug, **kwargs)) == ("uncovered", None), kwargs
