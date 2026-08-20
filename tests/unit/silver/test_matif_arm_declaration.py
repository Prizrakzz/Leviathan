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

And the behavioural half. THE ARM (2026-08-05) DELIBERATELY DID NOT MOVE IT: for two weeks rows
landed in ``silver_futures_eod`` and every MATIF answer stayed byte-identical, because a slug absent
from ``PRICE_COVERAGE_START`` makes ``coverage_start_for`` raise, ``futures_eod_route`` catch, and
the executor return ``status='declined'`` before any SQL compiles. That separation was the point,
and it held.

THE ANSWER FLIP (2026-08-20, owner word -- "what's stopping us from flipping it already?") is the
second decision, executed after two clean weeks of nightly fires: 108 / 90 / 90 rows measured on
the canonical bytes for wheat / maize / rapeseed, trade_dates 2026-08-06..2026-08-19 continuous,
zero red fires. All three slugs gained a floor of **2026-08-06** -- the FIRST BANKED TRADE DATE,
measured, never the arm date and never the 2026-07-29 orphan captures (never promoted to
canonical). No route code changed; only the map did.

So this file now asserts BOTH DIRECTIONS, which is the only honest shape for a floored slug:

  * ON OR AFTER the floor -- ``('serve', '2026-08-06')``. The per-delivery-month curve answers.
  * ENTIRELY BEFORE it -- ``('uncovered', '2026-08-06')``. ``covers()`` says 'legacy', but MATIF is
    not one of the continuous card's 12 ``unit_overrides``, so there is no legacy level to fall
    back on and the route degrades to an honest decline that NAMES the floor instead of raising.
    This is exactly the ``rapeseed_meal_zce`` / JSE shape (a floor with no legacy lane).
  * STRADDLING it -- ``('straddle', '2026-08-06')``. Splicing a per-expiry series onto a
    roll-spliced continuous one is refused by lint, not left to judgement.

What survives unchanged is the fail-closed seam itself: an UNMAPPED slug still raises, and the
raise still never reaches a caller. The DCE and Bursa browser slugs are the live proof.

Hermetic: JSON + pure functions. No AWS, no Athena, no network.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date
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

    def test_the_flip_is_recorded_as_a_separate_decision_that_has_now_HAPPENED(self, marker):
        """The whole point of separability: the arm landed and the serving answer did not move --
        for two weeks. The record must keep BOTH halves. Dropping 'the arm did not carry it' would
        rewrite history into 'arming a leg serves it', which is the exact conflation the two-gate
        design exists to prevent; dropping the flip date would leave a marker asserting a decline
        the code no longer performs."""
        rec = marker["serving_disposition"]
        assert rec["summary"].startswith("UNCHANGED BY THE ARM")
        assert "FLIPPED 2026-08-20" in rec["summary"]
        assert "NOT carried by D-PR-24's arm" in rec["flip_is_a_separate_decision"]
        assert "EXECUTED 2026-08-20" in rec["flip_is_a_separate_decision"]
        # the floor's provenance is the load-bearing half: first BANKED trade date, not the arm date
        assert "FIRST BANKED TRADE DATE" in rec["flip_is_a_separate_decision"]
        assert "2026-08-06" in rec["flip_is_a_separate_decision"]

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

    def test_the_browser_jobdef_is_declared_tracked_AND_applied_and_the_source_agrees(self, marker):
        """RE-KEYED 2026-08-20 (owner word). The prior pin asserted 'UNTRACKED BY TERRAFORM ...
        rev 1 ... both null' -- and that had ROTTED: modules/batch/main.tf declares
        aws_batch_job_definition.browser_runner (ADOPTED 2026-08-05) and apply HAS run (tfstate
        serial 1366 holds revision 3; live ACTIVE rev 3 = timeout 900 + producer retry matrix).
        This test was pinning the rot it was written to catch. It now asserts the new truth in
        BOTH directions: the declaration claims tracked-and-applied, the retired claim is gone,
        and the terraform SOURCE actually contains the resource with the two properties the
        adoption existed to add (source-level -- no cloud call; the cloud fact was verified once,
        read-only, at re-key time). The eventbridge 86400 retry-past-midnight seam is deliberately
        NOT claimed closed -- the precondition item must still name it open."""
        note = marker["leg"]["jobdef_note"]
        assert "TRACKED BY TERRAFORM -- DECLARED AND APPLIED" in note
        # The retired CLAIM must be gone; the note may still QUOTE it as history (it does, in the
        # re-key parenthesis), so pin the claim's own phrasing rather than the bare token.
        assert "still UNTRACKED BY TERRAFORM" not in note
        assert "revision 3" in note and "deregister_on_new_revision" in note
        items = [i for i in marker["arm_preconditions"]["items"] if _BROWSER_JOBDEF in i["item"]]
        assert len(items) == 1 and items[0]["status"].startswith("CLOSED 2026-08-05")
        assert "maximum_event_age_in_seconds=86400" in items[0]["status"]
        assert "stays open" in items[0]["status"]
        tf = (_REPO / "infra" / "terraform" / "modules" / "batch" / "main.tf").read_text(encoding="utf-8")
        assert 'resource "aws_batch_job_definition" "browser_runner"' in tf
        assert "attempt_duration_seconds = 900" in tf
        assert "producer_retry_attempts" in tf


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


class TestMatifAnswersOnOrAfterTheFloorAndDeclinesBeforeIt:
    """The behavioural half, re-keyed by the 2026-08-20 ANSWER FLIP.

    The arm (2026-08-05) left this dark on purpose and the separation held for two weeks. The flip
    is the second decision and it moves the answer in ONE direction only: a window on or after the
    measured floor now serves the per-delivery-month curve. Everything before it still declines,
    and a window across it still declines -- so this class asserts BOTH directions rather than
    swapping one blanket claim for its opposite. Nothing was deleted; the pre-floor half is the
    same assertion it always was, now keyed to a floor instead of to an absence."""

    # MEASURED on the canonical bytes 2026-08-20: first banked trade date, all three slugs.
    FLOOR = date(2026, 8, 6)
    FLOOR_ISO = "2026-08-06"
    # inside the banked span 2026-08-06..2026-08-19; the day before the floor is the pre-floor twin.
    POST = "2026-08-19"
    PRE = "2026-08-05"

    def test_every_matif_slug_carries_the_measured_floor(self):
        """The FLIP itself. The floor is the first banked trade date -- never the 2026-08-05 arm
        date, and never the 2026-07-29 orphan captures, which were never promoted to canonical.
        Claiming either would be the CEPEA nine-year-hole shape in miniature: a coverage claim
        wider than the bytes."""
        assert _matif_slugs(), "fixture guard: CONTRACT_MAP must carry the euronext_matif slugs"
        for slug in _matif_slugs():
            assert FC.PRICE_COVERAGE_START[slug] == self.FLOOR, slug
            assert FC.coverage_start_for(slug) == self.FLOOR, slug

    def test_the_fail_closed_seam_still_raises_for_an_UNMAPPED_slug(self):
        """The flip adds three entries; it does NOT soften coverage_start_for. The seam must still
        RAISE rather than return a permissive default, or 'no entry' would silently read as
        'covered since forever' for the venues whose bytes still have not landed. The DCE and
        Bursa browser slugs are the live proof, and they are asserted here so the seam keeps a
        non-vacuous witness after MATIF stopped being one."""
        unlanded = sorted(s for s, rec in FC.CONTRACT_MAP.items()
                          if rec["source"] in ("dce", "bursa"))
        assert unlanded, "fixture guard: some browser venue must still be unlanded"
        for slug in unlanded:
            assert slug not in FC.PRICE_COVERAGE_START
            with pytest.raises(ValueError, match="no PRICE_COVERAGE_START"):
                FC.coverage_start_for(slug)

    def test_an_ask_at_or_after_the_floor_is_ANSWERED(self):
        """THE FLIP'S AFFIRMATIVE HALF. A point read inside the banked span, and the boundary day
        itself, both SERVE -- the route compiles SQL against the per-delivery-month table instead
        of declining before it."""
        from leviathan.graphrag.numbers import agent as na
        for slug in _matif_slugs():
            assert na.futures_eod_route(_q(slug, asof=self.POST)) == ("serve", self.FLOOR_ISO), slug
            # the floor DAY itself serves (covers() is >=, not >)
            assert na.futures_eod_route(_q(slug, asof=self.FLOOR_ISO))[0] == "serve", slug
            # and a window sitting wholly inside the banked span serves as a series too. The as-of
            # moves WITH the window on purpose: futures_eod_window caps `hi` at the as-of (the
            # leakage guard would anyway), so a window read at the fixture's July as-of would
            # collapse back below the floor and route pre-coverage -- correctly, but it would be
            # asserting the wrong thing.
            assert na.futures_eod_route(_q(slug, asof=self.POST, agg="series",
                                           period_start=self.FLOOR_ISO,
                                           period_end=self.POST)) == ("serve", self.FLOOR_ISO), slug

    def test_an_ask_entirely_before_the_floor_still_DECLINES_and_names_the_floor(self):
        """THE PIN THAT SURVIVES THE FLIP, in its new form. covers() calls a wholly-pre-floor
        window 'legacy', but the retiring continuous card serves 12 of the 31 contracts and MATIF
        is not among them -- so futures_eod_route degrades it to 'uncovered' rather than offering a
        level that does not exist. Same shape as rapeseed_meal_zce (tests/unit/test_futures_eod.py
        test_a_pre_coverage_ask_with_no_legacy_series_is_uncovered). Note what CHANGED: the floor
        is now REPORTED instead of None, so the decline names the date the record begins."""
        from leviathan.graphrag.numbers import agent as na
        for slug in _matif_slugs():
            assert FC.covers(slug, date(2020, 1, 2), date(2020, 3, 2)) == "legacy", slug
            assert not na._legacy_serves(slug), f"{slug} joined the continuous card -- re-key this"
            for kwargs in ({"agg": "series", "period_start": "2020-01-02", "period_end": "2020-03-02"},
                           {"agg": "series", "period_start": "1990-01-02", "period_end": "1991-01-02"},
                           {"asof": self.PRE},
                           {"asof": "2026-07-29"}):     # the orphan-capture day is NOT coverage
                assert na.futures_eod_route(_q(slug, **kwargs)) == ("uncovered", self.FLOOR_ISO), \
                    (slug, kwargs)

    def test_a_window_STRADDLING_the_floor_declines_as_a_straddle(self):
        """The straddle rule, unchanged and now reachable for MATIF for the first time: a window
        crossing 2026-08-06 spans a per-expiry series and nothing, and joining the two would give a
        series that means neither thing. It is refused by lint, never left to judgement."""
        from leviathan.graphrag.numbers import agent as na
        for slug in _matif_slugs():
            assert FC.covers(slug, date(2026, 7, 1), date(2026, 8, 19)) == "straddle", slug
            # as-of moves with the window: `hi` is capped at the as-of, so a straddle only exists
            # for a read whose as-of actually reaches past the floor.
            assert na.futures_eod_route(_q(slug, asof=self.POST, agg="series",
                                           period_start="2026-07-01",
                                           period_end=self.POST)) == ("straddle", self.FLOOR_ISO)
            # straddling by ONE DAY is still a straddle -- the boundary is not a tolerance band
            assert na.futures_eod_route(_q(slug, asof=self.FLOOR_ISO, agg="series",
                                           period_start=self.PRE,
                                           period_end=self.FLOOR_ISO)) == ("straddle", self.FLOOR_ISO)

    def test_both_declining_routes_stay_declining_classes_with_verbatim_notes(self):
        """The executor declines on any route in FUTURES_EOD_COVERAGE_CLASSES -- BEFORE any SQL
        compiles -- and stamps the model-facing note on the payload. Both routes MATIF can now
        reach are in that set, and the straddle note renders its floor rather than leaking a
        '{floor}' placeholder at the reader."""
        from leviathan.graphrag.numbers import agent as na
        assert {"uncovered", "straddle"} <= set(na.FUTURES_EOD_COVERAGE_CLASSES)
        note = na.futures_eod_coverage_note("uncovered", self.FLOOR_ISO)
        assert note.startswith("COVERAGE DECLINE --")
        assert "no per-delivery-month record" in note
        straddle = na.futures_eod_coverage_note("straddle", self.FLOOR_ISO)
        assert straddle.startswith("COVERAGE DECLINE --")
        assert "{floor}" not in straddle and self.FLOOR_ISO in straddle
