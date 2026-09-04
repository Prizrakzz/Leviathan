"""LANE A / A-1 -- the VENUE NO-SETTLEMENT CALENDAR leaf and the tracked file it reads.

The measured incident this pins: on 2026-09-02 and 2026-09-03 the 08:00Z databento chain lost its
GATE and its PROMOTE for all 16 boards because ONE dataset's session count spoke for the whole
family, and that count came off ``pd.bdate_range`` -- freq ``B``, Mon-Fri, no holiday awareness.
The banked log of the 09-02 fire names the two units that failed -- ``IFEU.IMPACT RC/2026`` and
``IFEU.IMPACT W/2026``, "only 1 of 3 expected session(s) present (window 2026-08-28..2026-09-01)"
-- while all 7 GLBX and all 6 IFUS units on the SAME fire logged healthy lines, which is the
control that attributes the closure to ICE Europe. 2026-08-31 is a Monday
(``date.fromisoformat('2026-08-31').strftime('%a')`` -> ``Mon``), the last Monday of August, and
it sits inside the 5-day window of both fires.

Two claims live in this file and they are NOT the same claim: a DECLARED ENTRY is a verified claim
about one date and subtracts as soon as it is written; ``complete: true`` is the far stronger claim
that the year holds no OTHER such date, and only that ARMS a venue-year. Several tests below exist
only to keep those two from collapsing into each other.
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
import yaml
from leviathan.silver import venue_calendar as VC

_REPO = Path(__file__).resolve().parents[3]

GLBX = "GLBX.MDP3"
IFUS = "IFUS.IMPACT"
IFEU = "IFEU.IMPACT"

# The measured incident date and the venue it belongs to.
INCIDENT_DAY = "2026-08-31"

# DATED FORCING FUNCTION. The D-PR-45 January straddle can pull an incremental window into the NEXT
# calendar year from late December, so the calendar must be armed for {Y, Y+1} before then. A month
# of margin puts the deadline at 2026-12-01. Precedent for a dated pin: docs/private/dsg
# spec_jobdefs "dated: must land before 2027-01-01".
ARM_DEADLINE = date(2026, 12, 1)

# The shipped state, asserted EXACTLY and in both directions. NOTHING is armed yet: no exchange
# calendar could be verified from the seat that built this lane, and claiming exhaustiveness on an
# unverified year would be the mis-inferred floor the whole file exists to avoid. IFEU nevertheless
# DECLARES the one date that was measured. Arming a venue reds this test, which is how the arming
# gets reviewed here; un-arming one, or deleting the declared entry, reds it too.
UNARMED_AS_SHIPPED = [GLBX, IFUS, IFEU]
DECLARING_AS_SHIPPED = [IFEU]


@pytest.fixture(autouse=True)
def _clear_calendar_cache():
    """``load_venue_holidays`` is lru_cache'd by path; every test starts from a cold read."""
    VC.load_venue_holidays.cache_clear()
    yield
    VC.load_venue_holidays.cache_clear()


def _write(tmp_path: Path, doc: dict, name: str = "venue_holidays.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


def _year_block(days, *, complete=True, verified_on="2026-09-04", verified_by="test"):
    return {"complete": complete, "verified_on": verified_on, "verified_by": verified_by,
            "holidays": [{"day": d, "name": "a named closure", "basis": "published"}
                         for d in days]}


def _doc(datasets: dict, version: int = 1) -> dict:
    return {"version": version, "datasets": datasets}


def _dataset(years: dict, *, source_url="https://example.invalid/calendar") -> dict:
    return {"venue": "a venue", "source_url": source_url, "years": years}


class TestLoadRules:
    """The three load rules, each pinned with the reason it exists."""

    def test_an_absent_file_is_not_armed_and_is_not_a_refusal(self, tmp_path):
        """RULE 1. An absent file is legal and means "nothing declared".

        This is what makes landing the CODE safe while the calendar is still being filled, and it
        is ``load_declared_gaps``' own rule. Behaviour with no file is byte-identical to the
        pre-Lane-A arithmetic: no holidays subtract and no run refuses.
        """
        missing = tmp_path / "does_not_exist.yaml"
        assert VC.load_venue_holidays(missing) == {}
        assert VC.holidays_for(IFEU, missing) == frozenset()
        assert VC.armed_for(IFEU, 2026, missing) is False
        assert VC.assert_armed([GLBX, IFUS, IFEU], [2026], path=missing) == []

    @pytest.mark.parametrize("mutate,why", [
        (lambda d: d.__setitem__("version", 2), "an unsupported schema version"),
        (lambda d: d.__setitem__("datasets", []), "datasets is not a mapping"),
        (lambda d: d["datasets"][IFEU].__setitem__("years", []), "years is not a mapping"),
        (lambda d: d["datasets"][IFEU]["years"][2026].__setitem__("holidays", "2026-08-31"),
         "holidays is not a list"),
        (lambda d: d["datasets"][IFEU]["years"][2026].__setitem__("complete", "true"),
         "complete is the STRING 'true', not a boolean"),
        (lambda d: d["datasets"][IFEU]["years"][2026].__setitem__("verified_by", "  "),
         "verified_by is blank"),
        (lambda d: d["datasets"][IFEU]["years"][2026]["holidays"][0].__setitem__("day", "31/08/26"),
         "a non-ISO date"),
        (lambda d: d["datasets"][IFEU]["years"][2026]["holidays"][0].__setitem__("name", ""),
         "an entry that names no mechanism"),
        (lambda d: d["datasets"][IFEU]["years"][2026]["holidays"][0].__setitem__("basis", "guess"),
         "a basis outside the three-value vocabulary"),
        (lambda d: d["datasets"][IFEU]["years"][2026]["holidays"][0].pop("basis"),
         "an entry missing a required field"),
        (lambda d: d["datasets"][IFEU]["years"][2026]["holidays"][0].__setitem__("why", "x"),
         "an unknown entry field, i.e. a typo"),
        (lambda d: d["datasets"][IFEU].pop("source_url"), "a venue with no citation at all"),
        (lambda d: d["datasets"][IFEU]["years"][2026]["holidays"].append(
            {"day": "2025-12-25", "name": "wrong year", "basis": "published"}),
         "an entry filed under the wrong year block"),
        (lambda d: d["datasets"][IFEU]["years"][2026]["holidays"].append(
            {"day": "2026-08-31", "name": "again", "basis": "published"}),
         "the same day declared twice"),
    ])
    def test_a_malformed_entry_fails_closed(self, tmp_path, mutate, why):
        """RULE 2. A present-but-broken file is a HARD ERROR, never a silently empty set.

        The difference between "declared" and "mistyped" must never be silent: a silently empty
        calendar would put the arithmetic back to the state that produced the incident, with no
        line in the log saying so. Same discipline as ``load_declared_gaps``.
        """
        doc = _doc({IFEU: _dataset({2026: _year_block([INCIDENT_DAY])})})
        mutate(doc)
        path = _write(tmp_path, doc)
        with pytest.raises(ValueError):
            VC.load_venue_holidays(path)

    def test_an_unknown_dataset_resolves_to_an_empty_holiday_set(self, tmp_path):
        """RULE 3, and it guards an existing pin.

        ``_truncation_error`` stays PURE, so tests feed it synthetic dataset tokens; the lag map
        falls back to 1 for an unknown token and the calendar must fall back the same way. If this
        raised instead, the existing pin in TestExpectedLagSessions that an undeclared dataset
        falls back to lag one would go red.
        """
        path = _write(tmp_path, _doc({IFEU: _dataset({2026: _year_block([INCIDENT_DAY])})}))
        assert VC.holidays_for("NOT.A.DATASET", path) == frozenset()
        assert VC.holidays_for("", path) == frozenset()
        assert VC.armed_for("NOT.A.DATASET", 2026, path) is False


class TestArming:
    def test_a_year_without_complete_true_is_treated_as_missing(self, tmp_path):
        """ARMING is an EXHAUSTIVENESS claim; a declared ENTRY is not.

        A year marked ``complete: false`` does not arm -- but its individually verified entries
        still subtract, because each carries its own name, basis and verifier. Collapsing the two
        would force an operator to either claim exhaustiveness they cannot verify (a mis-INFERRED
        floor) or leave a measured absence unusable.
        """
        path = _write(tmp_path, _doc({
            IFEU: _dataset({2026: _year_block([INCIDENT_DAY], complete=False)})}))
        assert VC.armed_for(IFEU, 2026, path) is False
        assert VC.holidays_for(IFEU, path) == frozenset({INCIDENT_DAY})
        assert VC.armed_datasets(path) == []
        assert VC.declaring_datasets(path) == [IFEU]

    def test_the_lint_refuses_when_an_armed_venue_stops_covering_the_window(self, tmp_path):
        """THE LINT-REFUSAL PIN. An armed venue that goes stale is DRIFT and must refuse by name.

        A venue nobody has armed is NOT a refusal -- that is the pre-Lane-A world for that venue,
        carried by the one-holiday margin, and it is what makes landing this code safe. But once a
        venue IS armed, a year the run's window touches going missing means someone is relying on a
        fence that has quietly stopped covering the window.
        """
        path = _write(tmp_path, _doc({
            GLBX: _dataset({}),
            IFEU: _dataset({2026: _year_block([INCIDENT_DAY])})}))
        # armed and covering: no reason
        assert VC.assert_armed([IFEU], [2026], path=path) == []
        # armed and NOT covering 2027: refuses, naming the dataset and the year
        reasons = VC.assert_armed([IFEU], [2026, 2027], path=path)
        assert len(reasons) == 1 and IFEU in reasons[0] and "2027" in reasons[0]
        # never armed: silence, not a refusal
        assert VC.assert_armed([GLBX], [2026, 2027], path=path) == []
        assert VC.assert_armed(["NOT.A.DATASET"], [2026], path=path) == []

    def test_require_armed_names_every_unarmed_venue_and_every_placeholder_citation(self,
                                                                                    tmp_path):
        """The CI half of the same function: ``require_armed=True`` is the forcing function."""
        path = _write(tmp_path, _doc({
            GLBX: _dataset({}),
            IFEU: _dataset({2026: _year_block([INCIDENT_DAY])},
                           source_url="TO BE FILLED -- the venue calendar")}))
        reasons = VC.assert_armed([GLBX, IFEU], [2026], require_armed=True, path=path)
        joined = " | ".join(reasons)
        assert any("NOT ARMED" in r and GLBX in r for r in reasons), joined
        assert any("placeholder" in r and IFEU in r for r in reasons), joined

    def test_a_placeholder_citation_is_detected_as_a_stub(self):
        """Anti-vacuity for the citation check: it must actually recognise the stubs we ship."""
        for stub in ("TO BE FILLED -- ICE Futures Europe published holiday calendar",
                     "<CME Group holiday calendar>", "TODO"):
            assert VC.has_placeholder(stub), stub
        assert not VC.has_placeholder("https://example.invalid/holiday-calendar")

    def test_holidays_union_across_years_and_ignore_weekend_dating(self, tmp_path):
        """Every declared year contributes. Weekend dating is inert -- proved in the arithmetic
        test (the window iterates weekdays), asserted here only as a loading fact."""
        path = _write(tmp_path, _doc({IFEU: _dataset({
            2025: _year_block(["2025-08-25"]),
            2026: _year_block([INCIDENT_DAY, "2026-07-04"]),          # 2026-07-04 is a SATURDAY
        })}))
        assert VC.holidays_for(IFEU, path) == frozenset(
            {"2025-08-25", INCIDENT_DAY, "2026-07-04"})
        assert date.fromisoformat("2026-07-04").weekday() == 5, "the fixture's premise"


class TestTheTrackedFile:
    """The file this repo actually ships, judged on its own terms."""

    def test_the_shipped_calendar_exists_and_parses(self):
        """It must EXIST: deleting it to dodge a refusal would otherwise be silent."""
        assert VC.VENUE_HOLIDAYS_PATH.exists(), VC.VENUE_HOLIDAYS_PATH
        doc = VC.load_venue_holidays()
        assert sorted(doc) == [GLBX, IFEU, IFUS]

    def test_2026_08_31_is_declared_for_ice_europe_and_not_for_the_two_us_venues(self):
        """The measured incident date, with the negative half that keeps it from leaking.

        2026-08-31 is a UK bank holiday, not a US one: CME and ICE US both settled that Monday.
        Declaring it against GLBX or IFUS would silently drop a real expected session from those
        two venues' arithmetic -- a mis-inferred floor with a US-shaped blast radius.
        """
        assert INCIDENT_DAY in VC.holidays_for(IFEU)
        assert INCIDENT_DAY not in VC.holidays_for(GLBX)
        assert INCIDENT_DAY not in VC.holidays_for(IFUS)
        assert date.fromisoformat(INCIDENT_DAY).strftime("%a") == "Mon", \
            "the measurement the entry rests on: the LAST Monday of August"

    def test_every_declared_entry_names_a_mechanism_a_basis_and_a_verifier(self):
        """A named mechanism needs a NARRATING pin, never a count. Every shipped entry carries
        one, and the year block it sits in carries who checked it and when."""
        doc = VC.load_venue_holidays()
        seen = 0
        for dataset, block in doc.items():
            assert block["source_url"], dataset
            for year, yb in block["years"].items():
                assert yb["verified_by"] and yb["verified_on"], f"{dataset} {year}"
                for entry in yb["entries"]:
                    assert entry["name"].strip(), f"{dataset} {year} {entry['day']}"
                    assert entry["basis"] in VC.BASIS_VALUES, entry
                    seen += 1
        assert seen >= 1, "a calendar with no entry at all would make every pin here vacuous"

    def test_an_armed_venue_year_carries_a_real_citation(self):
        """Placeholders are legal only while a venue is UNARMED. This is vacuous today, by
        construction -- nothing is armed yet -- so it is paired with the roster pin below, which
        reds the moment that changes."""
        armed = VC.armed_datasets()
        assert VC.assert_armed(armed, [], require_armed=True) == []

    def test_the_calendar_must_be_armed_before_the_deadline(self):
        """THE ANNUAL FORCING FUNCTION, and it is deliberately DATE-SENSITIVE.

        Before ARM_DEADLINE it asserts the roster of unarmed venues EXACTLY: arming a venue reds
        this test so the arming is reviewed here, and un-arming one (or deleting the file) reds it
        too. From ARM_DEADLINE it becomes the hard assertion -- every venue armed for this year and
        next -- which is the D-PR-45 January straddle's precondition. It fires in CI, which is the
        whole point: a fire at 08:00Z must never be the thing that discovers a stale calendar.
        """
        today = date.today()
        if today >= ARM_DEADLINE:
            reasons = VC.assert_armed([GLBX, IFUS, IFEU], [today.year, today.year + 1],
                                      require_armed=True)
            assert reasons == [], (
                f"the venue calendar is past its {ARM_DEADLINE.isoformat()} arming deadline: "
                + "; ".join(reasons))
        else:
            assert VC.VENUE_HOLIDAYS_PATH.exists()
            unarmed = [d for d in [GLBX, IFUS, IFEU] if d not in VC.armed_datasets()]
            assert unarmed == UNARMED_AS_SHIPPED, (
                f"the unarmed roster moved to {unarmed}: update UNARMED_AS_SHIPPED in this test "
                f"and say in the commit which venue-years were verified and against what")
            assert VC.declaring_datasets() == DECLARING_AS_SHIPPED, (
                "the roster of venues carrying a declared entry moved -- an entry appearing or "
                "disappearing is a fence change and is reviewed here")


class TestDeriveVenueSessions:
    """The candidate generator, and the ONE law it must not break."""

    @staticmethod
    def _script():
        spec = importlib.util.spec_from_file_location(
            "derive_venue_sessions", _REPO / "scripts" / "silver" / "derive_venue_sessions.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_it_applies_no_frequency_floor(self):
        """FREQUENCY FLOORS DENY THE TAIL, and this is the exact place one would be tempting.

        A once-in-a-decade closure -- a state funeral, a national day of mourning -- appears in
        exactly ONE banked year. A ">= N years" screen would drop precisely that entry. So a
        one-year candidate is printed alongside a seven-year one; the recurrence count rides as
        INFORMATION, never as a filter.
        """
        mod = self._script()
        # 2024 and 2025: every weekday banked EXCEPT 2024-08-26 (a Monday, absent once) and
        # 2024-01-01 / 2025-01-01 (absent in both).
        sessions = {}
        for year, drop in ((2024, {"2024-08-26", "2024-01-01"}), (2025, {"2025-01-01"})):
            sessions[year] = set(mod.weekdays_in(year)) - drop
        cands = mod.candidate_dates(sessions, [2024, 2025])
        assert cands["2024-08-26"] == [2024], "the ONE-year candidate survives"
        assert cands["2024-01-01"] == [2024] and cands["2025-01-01"] == [2025]
        assert len(cands) == 3

    def test_an_unbanked_year_nominates_nothing(self):
        """A year with no banked rows would otherwise nominate all ~261 of its weekdays -- noise,
        not candidates. It is skipped and the header says so."""
        mod = self._script()
        assert mod.candidate_dates({2024: set()}, [2024]) == {}
        assert mod.candidate_dates({}, [2024]) == {}

    def test_the_year_range_parser_and_the_weekday_domain(self):
        mod = self._script()
        assert mod.parse_years("2019-2021") == [2019, 2020, 2021]
        assert mod.parse_years("2024") == [2024]
        assert mod.parse_years("2019,2021-2022") == [2019, 2021, 2022]
        with pytest.raises(ValueError):
            mod.parse_years("2025-2019")
        days = mod.weekdays_in(2026)
        assert INCIDENT_DAY in days and "2026-07-04" not in days, "Sat 2026-07-04 is not a session"
        assert all(date.fromisoformat(d).weekday() < 5 for d in days)


class TestFixPassLoader:
    """FIX PASS -- A-R8, the one way a mistyped calendar was still silent."""

    def test_a_duplicated_key_is_refused_rather_than_silently_keeping_the_last(self, tmp_path):
        """A-R8, MEASURED. ``yaml.safe_load`` keeps the LAST block when a mapping key repeats.

        The shape is not hypothetical: the documented workflow for filling this file is to run the
        derivation for one year at a time and append a year block, and appending 2025 twice loaded
        only the second -- ``holidays_for`` returned the December date and the August one was gone,
        with no error at all. Direction of harm is a FALSE RED (fewer subtractions, i.e. straight
        back to the pre-Lane-A arithmetic), so it is bounded; but rule 2 of this module is that the
        difference between "declared" and "mistyped" must never be silent, and a silently halved
        calendar is a mistype read as a declaration.
        """
        raw = (
            "version: 1\n"
            "datasets:\n"
            "  IFEU.IMPACT:\n"
            "    venue: a venue\n"
            "    source_url: https://example.invalid/calendar\n"
            "    years:\n"
            "      2025:\n"
            "        complete: true\n"
            "        verified_on: '2026-09-04'\n"
            "        verified_by: test\n"
            "        holidays:\n"
            "          - {day: 2025-08-25, name: a named closure, basis: published}\n"
            "      2025:\n"
            "        complete: true\n"
            "        verified_on: '2026-09-04'\n"
            "        verified_by: test\n"
            "        holidays:\n"
            "          - {day: 2025-12-25, name: another closure, basis: published}\n")
        path = tmp_path / "venue_holidays.yaml"
        path.write_text(raw, encoding="utf-8")
        # what the PERMISSIVE loader would have returned, shown rather than asserted about:
        permissive = yaml.safe_load(raw)
        assert list(permissive["datasets"][IFEU]["years"][2025]["holidays"])[0]["day"] \
            == date(2025, 12, 25), "safe_load keeps the LAST block -- the August date is gone"
        with pytest.raises(ValueError) as exc:
            VC.load_venue_holidays(path)
        assert "duplicate key" in str(exc.value)

    def test_a_duplicated_dataset_key_is_refused_too(self, tmp_path):
        raw = (
            "version: 1\n"
            "datasets:\n"
            "  IFEU.IMPACT:\n"
            "    venue: a venue\n"
            "    source_url: https://example.invalid/calendar\n"
            "    years: {}\n"
            "  IFEU.IMPACT:\n"
            "    venue: a second block\n"
            "    source_url: https://example.invalid/calendar\n"
            "    years: {}\n")
        path = tmp_path / "venue_holidays.yaml"
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(ValueError):
            VC.load_venue_holidays(path)

    def test_unparseable_yaml_is_the_same_named_refusal(self, tmp_path):
        """Rule 2 again: a file that is not YAML at all must arrive as the ValueError every caller
        of this module already handles, naming the file, not as a bare yaml.YAMLError from inside
        a fence's loader."""
        path = tmp_path / "venue_holidays.yaml"
        path.write_text("version: 1\ndatasets:\n  IFEU.IMPACT:\n   - [unbalanced\n",
                        encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            VC.load_venue_holidays(path)
        assert "venue_holidays.yaml" in str(exc.value)


class TestFixPassDeriveVenueSessions:
    """FIX PASS -- A-R5. The derivation lane the whole A-1b doctrine rests on had never run."""

    @staticmethod
    def _script():
        return TestDeriveVenueSessions._script()

    def test_the_registry_lookup_is_the_api_the_registry_actually_has(self):
        """A-R5, THE PLAIN BROKEN LINE. ``_sessions_from_s3`` read
        ``load_registry()["silver_futures_eod"]``; ``SilverRegistry`` is a frozen dataclass with
        ``.table(name)`` and no ``__getitem__``, so every invocation that named a bucket died with
        ``TypeError: 'SilverRegistry' object is not subscriptable`` BEFORE the first S3 call. The
        three pins the script had all sat above that line, and so did the recorded --help and
        missing-bucket runs: the measurement covered everything except the part that runs.
        """
        from leviathan.silver.registry import load_registry
        reg = load_registry()
        with pytest.raises(TypeError):
            reg["silver_futures_eod"]                                     # the shipped defect
        table = reg.table("silver_futures_eod")
        assert str(table["s3_root"]).split("/", 3)[-1].rstrip("/") == "silver/futures_eod"

    def test_it_runs_end_to_end_against_a_fake_tape_and_nominates_the_missing_weekday(
            self, monkeypatch, tmp_path):
        """A-R5's second half: PROVE IT RUNS. A fake S3 client serves one real parquet object per
        slug-year, paged, and the script is driven from ``main`` -- argument parsing, the registry
        lookup, the prefix build, the pager loop, the parquet column read and the candidate print,
        in one call, with no AWS in the room.

        The fixture bank two weekdays of 2026 for both IFEU slugs and omit 2026-08-31, so the one
        date the shipped calendar declares is the one date the derivation nominates.
        """
        import io

        import pandas as pd
        mod = self._script()
        banked = ["2026-08-28", "2026-09-01", "2026-09-02"]
        parquet: dict[str, bytes] = {}
        for slug in ("robusta_coffee", "white_sugar"):
            buf = io.BytesIO()
            pd.DataFrame({"trade_date": pd.to_datetime(banked),
                          "value": [1.0] * len(banked)}).to_parquet(buf, index=False)
            parquet[(f"silver/futures_eod/leviathan_slug={slug}/trade_year=2026/part-0.parquet")] \
                = buf.getvalue()

        class _FakeS3:
            def __init__(self):
                self.prefixes = []

            def list_objects_v2(self, **kw):
                self.prefixes.append(kw["Prefix"])
                keys = [k for k in parquet if k.startswith(kw["Prefix"])]
                return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

            def get_object(self, Bucket, Key):        # noqa: N803 -- boto3's own kwarg names
                return {"Body": io.BytesIO(parquet[Key])}

        fake = _FakeS3()
        monkeypatch.setattr("leviathan.storage.s3.get_thread_local_s3_client", lambda r: fake)
        rc = mod.main(["--dataset", "IFEU.IMPACT", "--years", "2026",
                       "--bucket", "leviathan-dev-shahem-001"])
        assert rc == 0, "the script runs end to end"
        assert any("leviathan_slug=robusta_coffee/trade_year=2026/" in p for p in fake.prefixes)
        assert any("leviathan_slug=white_sugar/trade_year=2026/" in p for p in fake.prefixes)
        sessions = mod._sessions_from_s3("leviathan-dev-shahem-001", "IFEU.IMPACT", [2026],
                                         "us-east-1")
        assert sessions[2026] == set(banked)
        cands = mod.candidate_dates(sessions, [2026])
        assert INCIDENT_DAY in cands and cands[INCIDENT_DAY] == [2026], \
            "the derivation nominates the one date the shipped calendar declares"
        assert "2026-08-29" not in cands, "a Saturday is not a weekday candidate"


class TestFixPassWheelBundle:
    """FIX PASS -- A-R9. In a wheel install the calendar resolved to ABSENT, which is not an error.

    ``registry.CONFIGS_SILVER_DIR`` falls back to the bundled ``_contract_configs`` directory when
    the repo tree is not beside the package (the Glue Python Shell family installs a wheel), and
    the build hook copied exactly the schema, known_drift.yaml and tables/*.yaml. A file left out
    of that list does not raise there: ``VENUE_HOLIDAYS_PATH`` simply does not exist, rule 1 says
    an absent file means "nothing declared", and the session floor is silently back to the
    arithmetic that lost the 08:00Z chain its gate. ``futures_gaps.yaml`` -- the gap ledger, read
    through the same constant -- has carried the identical exposure since it was written, which is
    why nothing red-ed and nobody noticed.

    Impact TODAY is zero and it is stated rather than implied: no futures_eod leg runs from a
    wheel. Batch runs from /app, where docker/leviathan_worker/Dockerfile COPYs the tracked
    configs/ tree in, so the tree copy is what a fire reads.
    """

    def test_the_wheel_hook_bundles_both_files_that_resolve_through_the_silver_config_dir(self):
        source = (_REPO / "setup.py").read_text(encoding="utf-8")
        assert "venue_holidays.yaml" in source, \
            "the calendar must ride the wheel, or a wheel consumer is silently unarmed"
        assert "futures_gaps.yaml" in source, \
            "the gap ledger has the identical exposure and is fixed in the same breath"

    def test_both_files_exist_in_the_tree_the_hook_copies_from(self):
        from leviathan.silver.registry import CONFIGS_SILVER_DIR
        assert (CONFIGS_SILVER_DIR / "venue_holidays.yaml").exists()
        assert (CONFIGS_SILVER_DIR / "futures_gaps.yaml").exists()
        assert VC.VENUE_HOLIDAYS_PATH.parent == CONFIGS_SILVER_DIR, \
            "same constant, same fallback, same exposure"
