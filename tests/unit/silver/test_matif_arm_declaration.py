"""D-PR-24 -- MATIF is ARMED, and the retired D-PR-23 declaration still has teeth.

D-PR-23 chose Option E: do not arm the Euronext/MATIF browser leg, do not remove it, and FORMALIZE
the status quo so the absence read as a decision rather than a gap. D-PR-24 (user-ratified
2026-08-05, 'arm MATIF, smoke the exact command before first fire') RETIRES that choice -- probe S3
resolved the SETTL. semantics that blocked it -- and the leg is now two tasks of
``configs/silver/dags/futures_eod_free.json``: a browser capture and the ordinary shared silver
producer.

The declaration file at ``configs/silver/dags/unarmed/futures_eod_browser.json`` SURVIVES its own
retirement because what it declares is still an absence: there is no ``futures_eod_browser``
SCHEDULE, and there never will be. These tests are what keep the retired declaration honest, and
they fire in three directions:

  * DRIFT TOWARD A SECOND SCHEDULE -- if a ``futures_eod_browser`` descriptor, gate entry or tfvars
    schedule appears, the fold-into-futures_eod_free decision was reversed without the declaration
    being updated. Folding was a reasoned choice (one table, one census baseline, one gate), so a
    second schedule that slips in quietly is the failure this pins.
  * DRIFT BACKWARD -- if the euronext tasks vanish from ``futures_eod_free`` while the declaration
    says ``leg_armed: true``, the arm was rolled back and the record was not.
  * ROT IN THE DECLARATION -- if the declared slug set stops matching CONTRACT_MAP's
    ``euronext_matif`` set, or the mirrored row floors drift from the code that owns them, the file
    has become a stale story about a leg that changed underneath it.

And the behavioural half, which the ARM DELIBERATELY DOES NOT CHANGE: MATIF contracts must
DECLINE, not ERROR, and not serve. ``coverage_start_for`` raising is the fail-closed seam, but the
raise must never reach a caller -- ``futures_eod_route`` catches it and returns
``('uncovered', None)``, which the executor turns into ``status='declined'`` with a verbatim
scope_note before any SQL compiles. Arming the ingest and flipping the answer are separable, and
this file is where that separation is proven rather than claimed: rows may now land, and every
MATIF answer is still byte-identical.

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
_HOST_SCHEDULE = "futures_eod_free"
_MATIF_SOURCE = "euronext_matif"
_TABLE = "silver_futures_eod"
_BROWSER_JOBDEF = "leviathan-dev-browser-runner"


@pytest.fixture(scope="module")
def marker() -> dict:
    return json.loads(_MARKER.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def host() -> dict:
    """The descriptor the leg was armed INSIDE."""
    return json.loads((_DAGS / f"{_HOST_SCHEDULE}.json").read_text(encoding="utf-8"))


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


def _tasks(desc: dict, phase: str) -> list[dict]:
    for ph in desc["phases"]:
        if ph["name"] == phase:
            return ph["tasks"]
    raise AssertionError(f"descriptor has no {phase!r} phase")


def _q(slug: str, **kw):
    """One MATIF lookup, shaped like the executor's forced spec (tests/unit/test_futures_eod.py)."""
    from leviathan.graphrag.numbers import query as Q
    base = dict(table=_TABLE, metric="settle", asof="2026-07-15", commodity=slug, agg="latest")
    base.update(kw)
    return Q.NumberQuery(**base)


class TestTheDeclarationIsRetiredAndSaysSo:
    def test_the_marker_declares_the_leg_armed_and_the_schedule_absent(self, marker):
        assert marker["schedule"] == _SCHEDULE
        assert marker["kind"] == "superseded_declaration"
        assert marker["family"] == "futures_eod"
        # The two claims that must never be conflated: no SCHEDULE, but a live LEG.
        assert marker["schedule_armed"] is False
        assert marker["leg_armed"] is True
        assert marker["leg_armed_in"] == _HOST_SCHEDULE

    def test_it_names_what_it_supersedes(self, marker):
        """A retired declaration that does not say what it retires is just a rewritten file."""
        assert "D-PR-23" in marker["supersedes"]
        assert "D-PR-24" in marker["supersedes"]
        assert marker["decision"].startswith("D-PR-24")

    def test_probe_s3_is_recorded_as_RESOLVED_with_its_answer(self, marker):
        """Probe S3 (Euronext SETTL. semantics) was the gate. It is resolved, and the resolution
        has to carry the ANSWER -- a 'status: done' with no finding is how a probe result gets
        re-litigated six months later. The why_it_blocked paragraph is retained as history because
        the hazard it describes is the reason settle_kind is pinned the way it is."""
        rec = marker["arming_gate"]
        assert rec["probe"] == "S3"
        assert rec["status"].startswith("RESOLVED")
        assert "SETTL." in rec["question"]
        assert "same session" in rec["answer"]
        assert "off by one" in rec["why_it_blocked"]

    def test_the_fold_decision_is_argued_not_asserted(self, marker):
        """D-PR-23 explicitly rejected folding into futures_eod_free. Reversing a written decision
        obliges the reversal to answer it, so the marker carries the objection VERBATIM and the
        measurement that defeats it -- the key's date rolls at 00:00Z, not at Paris midnight."""
        rec = marker["why_folded_rather_than_its_own_schedule"]
        assert "CET-local" in rec["the_d_pr_23_objection"]
        assert "00:00Z" in rec["why_it_does_not_hold"]
        # and the seam the fold does NOT fix must stay named rather than quietly dropped.
        assert "86400" in rec["residual_seam_carried_forward"]

    def test_the_arm_checklist_survives_with_a_disposition_per_item(self, marker):
        """Every D-PR-23 precondition is carried forward with what actually happened to it. The
        census-seed item in particular must be answered, not deleted: silver_rebuild_gate FAILS
        CLOSED on an absent baseline, and the reason no seed is owed is that no NEW schedule was
        created -- the rows ride futures_eod_free's existing, advancing baseline."""
        items = marker["arm_preconditions"]["items"]
        assert len(items) >= 8
        assert all({"item", "status"} <= set(i) for i in items)
        blob = " ".join(f"{i['item']} {i['status']}" for i in items)
        assert f"rolling/{_SCHEDULE}/census.json" in blob
        assert f"rolling/{_HOST_SCHEDULE}/census.json" in blob
        # the smoke test is the standing rule and is the OPERATOR's step, so it must still be open.
        smoke = [i for i in items if "smoke test" in i["item"]]
        assert len(smoke) == 1 and smoke[0]["status"].startswith("OWED")

    def test_the_orphan_raw_objects_have_a_written_disposition(self, marker):
        """The three 2026-07-29 captures are the provenance of the row floors. Under the arm they
        also became reachable by a hand-run backfill, which is a consequence worth writing down."""
        orphans = marker["orphan_raw_objects"]
        assert orphans["count"] == 3
        assert orphans["as_of_date"] == "2026-07-29"
        assert orphans["disposition"].startswith("RETAIN")
        assert "backfill" in orphans["reachability_under_the_arm"]

    def test_the_row_floor_runbook_exists_because_the_arm_required_it(self, marker):
        """D-PR-23's hazard clause demanded the delisting runbook be decided BEFORE the arm rather
        than discovered after a red. This is that clause, discharged."""
        rec = marker["row_floors"]
        assert "NEVER lowered" in rec["runbook"]
        assert "delist" in rec["runbook"].lower()

    def test_the_flip_is_still_declared_a_separate_decision(self, marker):
        """The whole point of separability: the arm landed and the serving answer did not move."""
        rec = marker["serving_disposition"]
        assert rec["summary"].startswith("UNCHANGED BY THE ARM")
        assert "NOT carried by D-PR-24's arm" in rec["flip_is_a_separate_decision"]

    def test_the_vocabulary_seams_are_enumerated_rather_than_assumed(self, marker):
        """The 2026-08-03 incident class -- ONE undeclared slug reds EVERY family -- is why this
        section exists. The finding was that W1c pre-declared every seam; recording WHICH seams
        were checked is what makes the next arm a checklist instead of a rediscovery."""
        rec = marker["vocabulary_pre_declaration"]
        assert len(rec["seams_checked_and_already_carrying_the_three_slugs"]) >= 6
        blob = " ".join(rec["seams_checked_and_already_carrying_the_three_slugs"]
                        + rec["seams_that_needed_nothing_by_construction"])
        for seam in ("cftc_cot.yaml", "unit_overrides", "cascade_map.yaml", "futures_roll"):
            assert seam in blob, seam
        assert rec["net"].startswith("ZERO")


class TestTheSeparateScheduleStaysAbsent:
    """The declaration says no ``futures_eod_browser`` schedule is intended. These fire if one
    appears anyway -- a second schedule against this table would mean a second rolling census, and
    each would read the other's rows as unexplained drift."""

    def test_there_is_no_top_level_descriptor(self):
        assert not (_DAGS / f"{_SCHEDULE}.json").exists(), (
            f"a {_SCHEDULE} chain descriptor appeared while "
            f"configs/silver/dags/unarmed/{_SCHEDULE}.json still declares schedule_armed=false -- "
            f"the leg is armed inside {_HOST_SCHEDULE}, deliberately")

    def test_the_generator_does_not_enumerate_the_schedule(self, gen):
        """load_descriptors globs dags/*.json NON-recursively, so the marker itself must be
        invisible to it -- a marker at the top level would be linted as a descriptor and, worse,
        rendered into an SFN input."""
        loaded = gen.load_descriptors()
        assert _SCHEDULE not in loaded
        assert _HOST_SCHEDULE in loaded, "non-vacuity: the host descriptor must be enumerable"
        assert _MARKER.parent != _DAGS, "the marker must live in a subdir, out of the descriptor glob"

    def test_there_is_no_rendered_input_or_schedule(self):
        rendered = _DAGS / "_rendered"
        assert not (rendered / f"{_SCHEDULE}.input.json").exists()
        assert not (rendered / f"{_SCHEDULE}.schedule.json").exists()

    def test_the_gate_carries_two_chains_and_the_matif_rows_ride_one_of_them(self, gate):
        """futures_eod_gate._DAG_SCHEDULES is gate 8's chain list, and it is also what decides
        which rolling baselines gate 8 emits a silver_rebuild_gate command against. Folding means
        the count stays at two -- and means the MATIF rows are covered by the host chain's."""
        assert _SCHEDULE not in gate._DAG_SCHEDULES
        assert set(gate._DAG_SCHEDULES) == {"futures_eod_databento", _HOST_SCHEDULE}

    def test_terraform_arms_no_such_schedule(self):
        """dag_schedules.auto.tfvars.json is what ACTUALLY arms a fire."""
        tfvars = json.loads(_TFVARS.read_text(encoding="utf-8"))
        armed = tfvars["dag_schedules"]
        # non-vacuity: the two LIVE futures_eod chains must be here, or this assertion is reading
        # the wrong shape and would pass on an empty dict.
        assert {"futures_eod_databento", _HOST_SCHEDULE} <= set(armed)
        assert _SCHEDULE not in armed


class TestTheArmIsRealAndStaysReal:
    """``leg_armed: true`` is a claim about another file. This is where it is cashed."""

    def test_the_host_descriptor_carries_the_capture_task_on_the_browser_jobdef(self, marker, host):
        """The capture CANNOT ride leviathan-dev-futures-eod-free-fetch: playwright and Chromium
        live in docker/leviathan_browser, not in the worker image. A silent move back to the shared
        fetch jobdef would fail on Fargate at import time, every fire."""
        fetch = [t for t in _tasks(host, "fetch") if t["id"] == marker["leg"]["capture_task_id"]]
        assert len(fetch) == 1, "the euronext capture task is missing from the host descriptor"
        assert fetch[0]["jobdef"] == _BROWSER_JOBDEF == marker["leg"]["jobdef"]
        assert fetch[0]["command"] == ["jobs/ingest/fetch_euronext_eod.py"]
        assert fetch[0]["publishes"] is False

    def test_the_capture_command_carries_no_window(self, marker, host):
        """The page serves TODAY and nothing earlier (it publishes no date at all), so a lookback
        window would be a lie. --skip-existing is the producer's default and a re-run costs no
        browser launch."""
        fetch = [t for t in _tasks(host, "fetch") if t["id"] == marker["leg"]["capture_task_id"]][0]
        assert "--lookback-days" not in fetch["command"]
        assert "--mode" not in fetch["command"]
        assert "--as-of-date" not in fetch["command"]

    def test_the_silver_task_rides_the_shared_publisher_so_self_promotion_stays_legal(
            self, marker, host, gen):
        """The whole self-promotion override rests on there being exactly ONE jobdef every
        shadow_canonical publisher in the descriptor runs on. A euronext silver task on any other
        jobdef would make gen_sfn_inputs.lint_descriptor reject the descriptor outright."""
        silver = [t for t in _tasks(host, "silver") if t["id"] == marker["leg"]["silver_task_id"]]
        assert len(silver) == 1
        assert silver[0]["command"][:3] == ["jobs/batch/futures_eod_task.py", "--source", "euronext"]
        assert silver[0]["publish_mode"] == "shadow_canonical"
        assert gen._shadow_canonical_jobdefs(host) == {host["promote_jobdef"]}
        assert silver[0]["jobdef"] == host["promote_jobdef"]

    def test_the_rendered_tfvars_carries_the_capture_command_verbatim(self, host):
        """The tfvars entry is the ONLY artifact that arms a fire, and its input_json is the
        EventBridge Scheduler body byte-for-byte. Rendering the descriptor is not arming it."""
        tfvars = json.loads(_TFVARS.read_text(encoding="utf-8"))
        body = json.loads(tfvars["dag_schedules"][_HOST_SCHEDULE]["input_json"])
        armed = json.loads(body["Input"])
        capture = [t for t in armed["phases"]["fetch"]["tasks"]
                   if t["command"][0].endswith("fetch_euronext_eod.py")]
        assert len(capture) == 1
        assert capture[0]["jobdef"] == _BROWSER_JOBDEF
        assert capture[0]["queue"] == "leviathan-dev-queue-ondemand"   # never the SPOT queue
        assert capture[0]["command"] == ["jobs/ingest/fetch_euronext_eod.py"]

    def test_the_cron_sits_after_the_publish_and_before_utc_midnight(self, host):
        """The whole cadence argument in one assertion. The producer files the capture under
        datetime.now(UTC).date(), so the date rolls at 00:00Z; the settlement publishes ~18:30
        Paris (16:30Z under CEST, 17:30Z under CET). 22:30Z is inside that window year-round."""
        assert host["cron"] == "cron(30 22 ? * MON-FRI *)"
        note = host["euronext_capture_window_note"]
        assert "00:00Z" in note and "16:30Z" in note and "17:30Z" in note

    def test_the_browser_jobdef_is_still_flagged_untracked_by_terraform(self, marker):
        """The other half of D-PR-23 did NOT land with the arm: the jobdef exists at revision 1
        with retryStrategy and attemptDurationSeconds both null. The declaration is the only place
        that says so, so it must keep saying it until the post-freeze batch adopts it."""
        assert "UNTRACKED BY TERRAFORM" in marker["leg"]["jobdef_note"]
        assert "retryStrategy" in marker["leg"]["jobdef_note"]
        open_items = [i for i in marker["arm_preconditions"]["items"]
                      if _BROWSER_JOBDEF in i["item"]]
        assert len(open_items) == 1 and open_items[0]["status"].startswith("STILL OPEN")


class TestTheDeclarationMatchesTheCode:
    """A stale declaration is worse than none -- it asserts a state that has moved."""

    def test_the_declared_slugs_are_exactly_the_matif_contracts(self, marker):
        assert sorted(marker["leg"]["slugs"]) == _matif_slugs()
        assert _matif_slugs(), "fixture guard: CONTRACT_MAP must carry the euronext_matif slugs"

    def test_the_declared_slugs_are_lint_bound_contracts(self, marker):
        for slug in marker["leg"]["slugs"]:
            rec = FC.contract_for(slug)
            assert rec["source"] == _MATIF_SOURCE
            assert rec["unit"] in FC.UNITS and rec["currency"] == "EUR"

    def test_the_declared_products_are_exactly_the_curated_map(self, marker):
        """All three are armed. The claim is only honest if the transform actually maps all three
        -- a product armed in the descriptor but absent from EURONEXT_PRODUCT_MAP would fail
        closed at slug_for_product, which is correct but is not what the marker says happens."""
        from leviathan.transforms.raw_to_bronze.euronext_eod import EURONEXT_PRODUCT_MAP
        assert sorted(marker["leg"]["products_armed"]) == sorted(EURONEXT_PRODUCT_MAP)
        assert sorted(EURONEXT_PRODUCT_MAP.values()) == _matif_slugs()

    def test_the_mirrored_row_floors_match_their_owning_module(self, marker):
        """The marker mirrors EURONEXT_MIN_ROWS for readability. A mirror that drifts is a lie, so
        it is pinned to the module that owns it."""
        from leviathan.transforms.raw_to_bronze.euronext_eod import EURONEXT_MIN_ROWS
        assert marker["row_floors"]["per_product_bronze"] == EURONEXT_MIN_ROWS

    def test_the_mirrored_per_day_silver_floor_matches_the_producer(self, marker):
        from jobs.batch import futures_eod_task as T
        assert marker["row_floors"]["per_day_silver"] == T._MIN_SILVER_ROWS_PER_DAY_EURONEXT

    def test_the_day_floor_reds_on_a_single_missing_product(self, marker):
        """Why 24 and not 32 or 12: three independent page renders in one run, and the floor has to
        sit BELOW a full day and ABOVE any two-product day. This is that arithmetic, asserted."""
        from leviathan.transforms.raw_to_bronze.euronext_eod import EURONEXT_MIN_ROWS
        floor = marker["row_floors"]["per_day_silver"]
        full = sum(EURONEXT_MIN_ROWS.values())
        worst_two = full - max(EURONEXT_MIN_ROWS.values())
        assert worst_two < floor <= full, (
            f"day floor {floor} must red a two-product day (max {worst_two}) and pass a full day "
            f"({full})")


class TestMatifStillDeclinesRatherThanErrors:
    """The behavioural half the arm deliberately did not touch: rows may land, and the answer does
    not move. This is what makes 'arm' and 'flip' two decisions instead of one."""

    def test_no_matif_slug_has_a_coverage_floor(self):
        for slug in _matif_slugs():
            assert slug not in FC.PRICE_COVERAGE_START, (
                f"{slug} gained a PRICE_COVERAGE_START entry -- that is the FLIP, which the D-PR-24 "
                f"arm explicitly does not carry and which is its own reviewed change")

    def test_coverage_start_for_fails_closed_on_every_matif_slug(self):
        """The fail-closed seam. It must RAISE (never return a permissive default), because a
        default would read as 'covered since forever' for a venue whose series has just begun."""
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
        window that accidentally serves, including one that covers the newly-armed sessions."""
        from leviathan.graphrag.numbers import agent as na
        slug = _matif_slugs()[0]
        for kwargs in ({"agg": "series", "period_start": "2020-01-02", "period_end": "2020-03-02"},
                       {"agg": "series", "period_start": "1990-01-02", "period_end": "1991-01-02"},
                       {"agg": "series", "period_start": "2026-08-01", "period_end": "2026-08-31"},
                       {"asof": "2026-07-29"}):
            assert na.futures_eod_route(_q(slug, **kwargs)) == ("uncovered", None), kwargs
