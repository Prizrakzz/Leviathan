"""The ESR raw -> bronze Batch producer's key selection and VINTAGE LAW (jobs/batch/esr_task.py).

Covers ``--as-of-min`` (the SILVER-F030 BF-W2 targeted re-bronze) and the C-F1 fix that made the
as_of of a bronze partition come from the RAW KEY or the raw_meta sidecar and NEVER from today's
date.

Why the filter exists, measured: bronze is strictly INCREMENTAL. ``_process`` returns "skipped"
whenever the bronze key already exists and ``--force-overwrite`` was not passed, and the scheduled
esr_weekly chain passes ``command: ["jobs/batch/esr_task.py"]`` with no ``--force-overwrite``. So a
bronze TRANSFORM change reaches FUTURE as_of partitions only: the vintages whose RAW already
carries the five net-commitment fields were bronzed by the OLD transform and would stay null in
silver forever.

Why the vintage law exists, measured 2026-09-04 on s3://leviathan-dev-shahem-001: the raw prefix
holds 1,901 JSON objects, 446 of them carrying an ``as_of=`` segment and 1,455 of them carrying
none. The pre-fix code resolved an undated key's as_of to ``today``, so (a) every scheduled run
minted a fabricated point-in-time vintage from static backfill payloads and (b) all 1,455 undated
keys satisfied ANY ``--as-of-min`` bound -- a flag advertised as narrowing a rewrite silently
opened it to the whole history, and the fabricated ``as_of=<today>`` object then read 0.0 on all
five new columns and tripped the rollout's own STOP condition on a self-inflicted artifact.

AWS-free: the key work is pure string work; the sidecar path is exercised through a fake S3 client.
"""
from __future__ import annotations

import ast
import functools
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TASK = _REPO / "jobs" / "batch" / "esr_task.py"

# THE ESR WRITER CENSUS, computed rather than remembered (verify-2 V2-NEW-1). The law shipped as
# holding in "all THREE ESR writers" while a FOURTH -- jobs/ingest/backfill_bronze_usda_esr.py --
# still stamped today onto undated keys with no flags required, because the count was a sentence
# somebody wrote once. These roots and helper names turn it back into a measurement.
_WRITER_SCAN_ROOTS = ("jobs", "dags", "src/leviathan", "scripts")
_PARTITION_KEY_FUNCS = ("bronze_esr_key", "silver_esr_key")
_RAW_KEY_FUNCS = ("raw_esr_backfill_key", "raw_esr_weekly_key")
_KEY_DEFINER = "src/leviathan/storage/paths.py"    # it DEFINES them; it writes nothing


def _names_used(path: Path) -> set[str]:
    """Every name the module REFERENCES, by ast.

    Deliberately not a text grep: each refused writer now NARRATES the helper it used to call
    ("it wrote bronze_esr_key(code, year, <--ingest-date>)") in its docstring, and a text grep
    would keep counting a writer that can no longer write. A Name/Attribute node cannot come
    from a docstring or a comment.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):        # pragma: no cover - none in this estate
        return set()
    out = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    out |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return out


@functools.lru_cache(maxsize=1)
def _esr_key_census_scan() -> tuple[tuple[str, frozenset], ...]:
    """The scan itself. Cached because it ast-parses 759 modules (14.6s measured 2026-09-04) and
    four pins below share it; without the cache the eight-suite lane run -- which the runbook's
    own ``--step CHECK`` executes -- grew by ~58s for nothing."""
    out: list[tuple[str, frozenset]] = []
    for root in _WRITER_SCAN_ROOTS:
        base = _REPO / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(_REPO).as_posix()
            if rel == _KEY_DEFINER or "__pycache__" in rel:
                continue
            used = _names_used(path) & set(_PARTITION_KEY_FUNCS + _RAW_KEY_FUNCS)
            if used:
                out.append((rel, frozenset(used)))
    return tuple(out)


def _esr_key_census() -> dict[str, set[str]]:
    """``{relpath: {esr key helpers it references}}`` over the four roots. A fresh dict each call,
    so a pin cannot mutate the shared scan."""
    return {rel: set(used) for rel, used in _esr_key_census_scan()}


@pytest.fixture(scope="module")
def task():
    spec = importlib.util.spec_from_file_location("esr_task_under_test", _TASK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _weekly(code: int, year: int, as_of: str) -> str:
    return (f"raw/production/source=usda_esr/commodity_code={code}/market_year={year}/"
            f"as_of={as_of}/all_countries.json")


def _backfill(code: int, year: int) -> str:
    return (f"raw/production/source=usda_esr/commodity_code={code}/market_year={year}/"
            f"all_countries.json")


# The 12 as_of vintages measured in the live raw prefix on 2026-09-04, corn (401) shaped.
LIVE_VINTAGES = ["20260712", "20260717", "20260723", "20260724", "20260730", "20260806",
                 "20260813", "20260816", "20260820", "20260827", "20260903", "20260904"]
WEEKLIES = [_weekly(401, 2025, v) for v in LIVE_VINTAGES] + [_weekly(801, 2025, "20260903")]
BACKFILLS = [_backfill(401, 2019), _backfill(801, 2019)]
ALL_KEYS = WEEKLIES + BACKFILLS


class _FakeBody:
    def __init__(self, blob: bytes) -> None:
        self._blob = blob

    def read(self) -> bytes:
        return self._blob


class FakeS3:
    """Minimal S3 stand-in: only ``get_object`` on the raw_meta sidecar prefix."""

    def __init__(self, objects: dict) -> None:
        self.objects = dict(objects)
        self.gets: list[str] = []

    def get_object(self, Bucket: str, Key: str):  # noqa: N803 -- boto3's own kwarg spelling
        self.gets.append(Key)
        if Key not in self.objects:
            raise KeyError(f"NoSuchKey: {Key}")
        return {"Body": _FakeBody(self.objects[Key])}


def _args(task, argv: list[str]):
    """Parse argv through the PRODUCER'S OWN parser -- never a hand-built Namespace, or the test
    would pin a CLI that does not exist."""
    return task.build_parser().parse_args(argv)


# ---------------------------------------------------------------------------
# THE VINTAGE LAW: where an as_of may come from.
# ---------------------------------------------------------------------------
class TestVintageLaw:
    def test_a_weekly_key_carries_its_own_vintage(self, task):
        assert task._as_of_from_raw_key(_weekly(401, 2025, "20260813")) == "20260813"

    def test_an_undated_key_carries_none_and_says_so(self, task):
        """None, not today. The whole C-F1 defect was a fallback that turned "this payload has no
        vintage" into "this payload is from today"."""
        assert task._as_of_from_raw_key(_backfill(401, 2019)) is None

    def test_the_key_segment_wins_over_everything(self, task):
        s3 = FakeS3({})
        key = _weekly(401, 2025, "20260813")
        assert task.resolve_as_of(key, s3, "b", "20991231") == ("20260813", "raw_key")
        assert s3.gets == [], "a dated key must not cost a sidecar GET"

    def test_an_explicit_operator_date_dates_an_undated_key(self, task):
        s3 = FakeS3({})
        assert task.resolve_as_of(_backfill(401, 2019), s3, "b", "20260712") == (
            "20260712", "operator")

    def test_the_sidecar_download_timestamp_dates_an_undated_key(self, task):
        """The fetcher writes raw_meta/<raw_key>_meta.json with the UTC ISO-8601 stamp of the
        moment the bytes landed. For a static historical payload that fetch date is the only
        honest vintage there is -- it is what was knowable when the object appeared."""
        key = _backfill(401, 2019)
        s3 = FakeS3({f"raw_meta/{key}_meta.json":
                     json.dumps({"download_timestamp": "2026-06-15T04:11:07.123456+00:00"}).encode()})
        assert task.resolve_as_of(key, s3, "b", None) == ("20260615", "raw_meta")

    def test_no_key_no_operator_no_sidecar_is_a_REFUSAL_never_today(self, task):
        """The fix's core assertion. There is no today's-date branch in resolve_as_of at all: a
        vintage stamped "today" onto an undated payload is a point-in-time that never existed, in
        the table whose entire purpose (INV-3) is point-in-time honesty."""
        as_of, provenance = task.resolve_as_of(_backfill(401, 2019), FakeS3({}), "b", None)
        assert as_of is None
        assert provenance == "unresolvable"

    @pytest.mark.parametrize("blob", [b"{}", b"not json at all", b'{"download_timestamp": 17}',
                                      b'{"download_timestamp": "yesterday"}'])
    def test_a_garbled_sidecar_refuses_rather_than_guessing(self, task, blob):
        key = _backfill(401, 2019)
        s3 = FakeS3({f"raw_meta/{key}_meta.json": blob})
        assert task._as_of_from_raw_meta(s3, "b", key) is None
        assert task.resolve_as_of(key, s3, "b", None)[0] is None

    def test_the_module_has_no_todays_date_fallback_left(self, task):
        """A source-level pin on the ABSENCE the law depends on: main() must not reconstruct a
        backfill_as_of from the clock. `today` may still be read for the INGEST date."""
        src = _TASK.read_text(encoding="utf-8")
        assert 'backfill_as_of = args.backfill_as_of or today' not in src
        assert "backfill_as_of = args.backfill_as_of" in src


# ---------------------------------------------------------------------------
# The --as-of-min filter.
# ---------------------------------------------------------------------------
class TestAsOfMinFilter:
    def test_none_is_an_exact_passthrough(self, task):
        """The weekly path does not pass --as-of-min; it must see the identical key list, same
        order, same objects -- a filter that quietly reshaped the default run would change what
        the scheduler does."""
        kept, dropped = task._filter_by_as_of_min(ALL_KEYS, None)
        assert kept is ALL_KEYS
        assert dropped == 0

    def test_it_selects_exactly_the_vintages_at_or_after_the_bound(self, task):
        """MEASURED scope, not a guess: the live raw prefix carries 12 as_of vintages and six of
        them (20260813, 16, 20, 27, 20260903, 20260904) are >= the bound."""
        kept, _ = task._filter_by_as_of_min(WEEKLIES, "20260813")
        assert [k for k in kept if "commodity_code=401" in k] == [
            _weekly(401, 2025, v) for v in
            ("20260813", "20260816", "20260820", "20260827", "20260903", "20260904")
        ]

    def test_the_bound_is_inclusive(self, task):
        kept, _ = task._filter_by_as_of_min([_weekly(401, 2025, "20260813")], "20260813")
        assert len(kept) == 1

    def test_earlier_vintages_are_dropped(self, task):
        kept, _ = task._filter_by_as_of_min(WEEKLIES, "20260813")
        assert _weekly(401, 2025, "20260806") not in kept
        assert _weekly(401, 2025, "20260712") not in kept

    def test_an_undated_key_is_never_admitted_by_a_vintage_bound(self, task):
        """RE-AIMED 2026-09-04 (C-F1). The previous shape asserted the OPPOSITE -- that a backfill
        key is judged on --backfill-as-of, which defaulted to today, so every undated key passed
        every bound. A key with no as_of= segment carries NO vintage; a vintage-bounded re-bronze
        therefore drops it, and counts the drop so the operator sees a refusal rather than a
        silent inclusion."""
        kept, dropped = task._filter_by_as_of_min(BACKFILLS, "20260813")
        assert kept == []
        assert dropped == len(BACKFILLS) == 2

    def test_an_undated_key_enters_only_on_a_DECLARED_vintage(self, task):
        kept, dropped = task._filter_by_as_of_min(
            BACKFILLS, "20260813", include_backfill=True, backfill_as_of="20260904")
        assert kept == BACKFILLS
        assert dropped == 0
        kept, dropped = task._filter_by_as_of_min(
            BACKFILLS, "20260813", include_backfill=True, backfill_as_of="20190101")
        assert kept == []
        assert dropped == 0, "declared-but-out-of-range is a bound miss, not an undated drop"

    def test_include_backfill_alone_still_drops_undated_keys(self, task):
        """The flag says the keys are in SCOPE; it does not invent a vintage for the comparison."""
        kept, dropped = task._filter_by_as_of_min(BACKFILLS, "20260813", include_backfill=True)
        assert kept == []
        assert dropped == 2

    def test_the_comparison_agrees_with_the_bronze_key_builder(self, task):
        """One derivation of as_of, not two: the filter judges on exactly the value
        ``resolve_as_of`` returns for a dated key."""
        for key in WEEKLIES:
            as_of, provenance = task.resolve_as_of(key, FakeS3({}), "b", None)
            assert provenance == "raw_key"
            kept, _ = task._filter_by_as_of_min([key], "20260813")
            assert bool(kept) == (as_of >= "20260813"), key

    @pytest.mark.parametrize("bad", ["2026-08-13", "20260813 ", "202608", "", "abcdefgh",
                                     "2026081", "202608131"])
    def test_a_malformed_bound_raises_instead_of_matching_nothing(self, task, bad):
        """FAIL-CLOSED on the argument. A silently-empty match looks exactly like "the filter
        worked and there was nothing to do" -- and the operator's next action is to read
        ``written=`` and decide whether the shadow measurement downstream is real."""
        with pytest.raises(ValueError, match="YYYYMMDD"):
            task._filter_by_as_of_min(ALL_KEYS, bad)


# ---------------------------------------------------------------------------
# The CLI-level gates -- driven through the producer's OWN parser (C-M4).
# ---------------------------------------------------------------------------
class TestCliRefusals:
    def test_an_empty_as_of_min_is_a_REFUSAL_at_the_CLI(self, task):
        """C-M4. The helper always raised on '', but main()'s gate was ``if args.as_of_min:`` --
        falsy for the empty string -- so the one shell/JSON form that yields a zero-length
        argument skipped the filter entirely and every key survived to a forced rewrite. The gate
        is now ``is not None`` and this test drives the real seam, not the helper."""
        args = _args(task, ["--force-overwrite", "--as-of-min", ""])
        assert args.as_of_min == ""
        with pytest.raises(ValueError, match="YYYYMMDD"):
            task.select_raw_keys(list(ALL_KEYS), args)

    def test_force_overwrite_without_a_bound_is_a_REFUSAL(self, task):
        """"--as-of-min must be REQUIRED for a re-bronze; there is no default bound, because a
        default bound is a default that selects everything."""
        args = _args(task, ["--force-overwrite"])
        with pytest.raises(ValueError, match="requires --as-of-min"):
            task.select_raw_keys(list(ALL_KEYS), args)

    def test_include_backfill_with_a_bound_needs_a_declared_vintage(self, task):
        args = _args(task, ["--force-overwrite", "--as-of-min", "20260813", "--include-backfill"])
        with pytest.raises(ValueError, match="requires an explicit --backfill-as-of"):
            task.select_raw_keys(list(ALL_KEYS), args)

    def test_a_malformed_backfill_as_of_is_a_REFUSAL(self, task):
        args = _args(task, ["--backfill-as-of", ""])
        with pytest.raises(ValueError, match="--backfill-as-of must be YYYYMMDD"):
            task.select_raw_keys(list(ALL_KEYS), args)

    def test_the_default_run_drops_undated_keys_and_keeps_every_dated_one(self, task):
        """What the SCHEDULED chain now does: ``jobs/batch/esr_task.py`` with no flags. Before the
        fix this same invocation admitted all 1,455 undated raw objects and stamped them with the
        run date."""
        selected = task.select_raw_keys(list(ALL_KEYS), _args(task, []))
        assert selected == WEEKLIES
        assert not [k for k in selected if task._as_of_from_raw_key(k) is None]

    def test_include_backfill_admits_them_for_an_unbounded_run(self, task):
        selected = task.select_raw_keys(list(ALL_KEYS), _args(task, ["--include-backfill"]))
        assert selected == ALL_KEYS

    def test_the_targeted_re_bronze_selects_only_dated_vintages(self, task):
        selected = task.select_raw_keys(
            list(ALL_KEYS), _args(task, ["--force-overwrite", "--as-of-min", "20260813"]))
        assert all(task._as_of_from_raw_key(k) >= "20260813" for k in selected)
        assert not set(selected) & set(BACKFILLS)

    def test_limit_still_applies_last(self, task):
        selected = task.select_raw_keys(list(ALL_KEYS), _args(task, ["--limit", "3"]))
        assert selected == WEEKLIES[:3]

    def test_the_cli_exposes_every_flag_main_reads(self, task):
        """The flags have to reach the seam: a helper nobody can call is not a capability."""
        args = _args(task, ["--as-of-min", "20260813", "--include-backfill",
                            "--backfill-as-of", "20260712", "--force-overwrite"])
        assert args.as_of_min == "20260813"
        assert args.include_backfill is True
        assert args.backfill_as_of == "20260712"
        assert args.force_overwrite is True
        assert _args(task, []).as_of_min is None
        assert _args(task, []).include_backfill is False
        assert _args(task, []).backfill_as_of is None


class TestTheLawHoldsInAllFourWriters:
    """RE-REVIEW NEW-2, widened by VERIFY-2 V2-NEW-1: the law is a law about PARTITIONS, so it
    binds every writer of them -- and the number of writers is a MEASUREMENT, not a sentence.

    The estate has FOUR ESR writers into the two prefixes this lane measures. ``esr_task.py``
    (everything above) resolves the vintage in four branches with no clock branch. The other
    three stamped a run date, and one of them was RECOMMENDED BY NAME in the migration artifact:

      jobs/glue/raw_to_bronze_usda_esr.py       backfill mode (its DEFAULT) paired every undated
                                                raw key with --ingest_date and wrote
                                                bronze_esr_key(code, year, <that date>) into the
                                                same bronze prefix -- the mechanism behind 8,474
                                                of the 8,920 bronze objects.
      jobs/ingest/backfill_bronze_usda_esr.py   the LOCAL TWIN of that Glue mode, and the path an
                                                operator reaches for FIRST (its own first line
                                                advertised it as the way around Glue quota
                                                limits). --ingest-date DEFAULTED TO TODAY and
                                                every key it read was UNDATED, so a bare
                                                `python jobs/ingest/backfill_bronze_usda_esr.py`
                                                -- no flags at all -- minted a whole vintage
                                                across 44 codes x 1990..<this year>.
      jobs/ingest/backfill_silver_usda_esr.py   --as-of-date defaulted to today, and that one
                                                argument is BOTH the bronze partition read and
                                                the silver partition written.

    A law with an unguarded back door into the same prefix is a half-closed finding, so all three
    now refuse. The two bronze writers refuse because neither has a route to a raw_meta sidecar
    and so cannot honestly date an undated key; the silver backfill refuses because only the
    operator knows which vintage is being re-derived.

    The fourth was missed for a whole review round because the closure was written down ("all
    THREE ESR writers") instead of measured. :func:`_esr_key_census` is the repair: the pin below
    recomputes the list from the tree every run, so the next writer someone adds either appears in
    it or the pin goes red.

    The law-abiding FIFTH, dags/airflow/esr_weekly_ingest_dag.py, writes bronze inline at the raw
    key's OWN as_of and needed no change; it is pinned here so it is not re-discovered.
    """

    @staticmethod
    def _glue_src() -> str:
        return (_REPO / "jobs" / "glue" / "raw_to_bronze_usda_esr.py").read_text(encoding="utf-8")

    @staticmethod
    def _silver_backfill():
        return importlib.import_module("jobs.ingest.backfill_silver_usda_esr")

    @staticmethod
    def _local_bronze():
        return importlib.import_module("jobs.ingest.backfill_bronze_usda_esr")

    @staticmethod
    def _local_bronze_src() -> str:
        return (_REPO / "jobs" / "ingest" / "backfill_bronze_usda_esr.py").read_text(
            encoding="utf-8")

    # -- the FOURTH writer (V2-NEW-1) ---------------------------------------------------------

    def test_the_local_bronze_writer_REFUSES_the_undated_rebronze_BY_NAME(self):
        """Driven through the real seam, not read off the source: the message must name the law,
        carry its own measurement, and name the law-abiding writer WITH the flags that make it
        law-abiding. A refusal that does not say where to go next is only an obstacle."""
        mod = self._local_bronze()
        with pytest.raises(RuntimeError) as exc:
            mod.refuse_undated_backfill()
        message = str(exc.value)
        assert message.startswith("REFUSING (ESR VINTAGE LAW)")
        assert message.isascii(), "the Windows console is cp1252"
        assert "jobs/batch/esr_task.py --include-backfill --backfill-as-of" in message
        assert "8,474 of 8,920" in message, "the refusal carries its own measurement"
        assert "jobs/glue/raw_to_bronze_usda_esr.py" in message, "it names its Glue twin"

    @pytest.mark.parametrize("argv", [
        [],                                                     # the file's own first usage line
        ["--skip-existing"],
        ["--dry-run"],
        ["--commodity-codes", "401", "--start-year", "2025", "--end-year", "2025"],
        ["--ingest-date", "2026-09-04"],
    ])
    def test_every_historical_invocation_shape_now_EXITS_NON_ZERO(self, argv, monkeypatch):
        """The failing input was ``python jobs/ingest/backfill_bronze_usda_esr.py`` with no
        arguments -- the file's own first documented usage. Every shape it ever documented must
        now refuse, --dry-run included: a dry run of an unlawful writer teaches the recipe. The
        LOG LINE is captured too, because an exit status alone tells an operator nothing."""
        mod = self._local_bronze()
        logged: list[str] = []
        monkeypatch.setattr(sys, "argv", ["backfill_bronze_usda_esr.py", *argv])
        monkeypatch.setattr(mod.logger, "error", lambda fmt, *a: logged.append(str(fmt) % a))
        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 2, "the same exit status the sibling local writer uses"
        assert len(logged) == 1 and logged[0].startswith("REFUSING (ESR VINTAGE LAW)")

    def test_the_local_bronze_writer_can_no_longer_DATE_A_KEY_or_READ_A_CLOCK(self):
        """The absence of the MECHANISM, not of a comment. The defect was two expressions --
        ``raw_esr_backfill_key(code, year)`` (an UNDATED key) paired with
        ``args.ingest_date.replace("-", "")`` where --ingest-date defaulted to today. The module
        can no longer name either helper NOR read a clock, so no argument shape can revive it.
        Measured by ast, so the docstring that NARRATES the old defect does not satisfy the pin.
        """
        used = _names_used(_REPO / "jobs" / "ingest" / "backfill_bronze_usda_esr.py")
        assert not used & set(_PARTITION_KEY_FUNCS + _RAW_KEY_FUNCS), sorted(used)
        assert "today" not in used and "now" not in used, "no clock seam survives"
        src = self._local_bronze_src()
        assert "args.ingest_date.replace" not in src
        assert "import datetime" not in src, "the module imports no clock at all"
        assert "_BACKFILL_REFUSAL" in src

    def test_the_local_bronze_writer_still_IMPORTS_the_fetchers_universe(self):
        """The refusal must not take the D-EC 2026-08-20 remediation down with it: this file used
        to hold a private 10-code copy of the 44-code universe, and --help still advertises the
        flag's default."""
        mod = self._local_bronze()
        from jobs.ingest import fetch_usda_esr as fetcher
        assert mod._DEFAULT_COMMODITY_CODES == list(fetcher._TARGET_COMMODITY_CODES)

    # -- the census itself (V2-NEW-1's repair) -------------------------------------------------

    def test_the_ESR_WRITER_CENSUS_is_a_GREP_and_this_is_the_measured_list(self):
        """MEASURED 2026-09-04 by ast over jobs/, dags/, src/leviathan/ and scripts/. Five modules
        name an ESR key helper; FOUR of them write a partition. backfill_bronze_usda_esr.py is
        absent from the census by construction now -- that absence IS its refusal."""
        census = _esr_key_census()
        assert set(census) == {
            "jobs/batch/esr_task.py",
            "jobs/glue/raw_to_bronze_usda_esr.py",
            "jobs/ingest/backfill_silver_usda_esr.py",
            "jobs/ingest/fetch_usda_esr.py",
            "dags/airflow/esr_weekly_ingest_dag.py",
        }, sorted(census)
        partition_writers = sorted(rel for rel, used in census.items()
                                   if used & set(_PARTITION_KEY_FUNCS))
        assert partition_writers == [
            "dags/airflow/esr_weekly_ingest_dag.py",
            "jobs/batch/esr_task.py",
            "jobs/glue/raw_to_bronze_usda_esr.py",
            "jobs/ingest/backfill_silver_usda_esr.py",
        ]
        assert census["jobs/ingest/fetch_usda_esr.py"] == {"raw_esr_backfill_key",
                                                           "raw_esr_weekly_key"}, (
            "the fetcher writes RAW only -- it is where undated keys COME FROM, not a partition "
            "writer")
        assert "jobs/ingest/backfill_bronze_usda_esr.py" not in census

    def test_no_ESR_writer_pairs_an_UNDATED_key_with_a_PARTITION_write(self):
        """THE LAW, as a property of the tree rather than a sentence about it. The whole defect
        class is one co-occurrence: a module that can name ``raw_esr_backfill_key`` (a key with no
        as_of= segment of its own) AND write ``bronze_esr_key`` / ``silver_esr_key`` has to invent
        the vintage from somewhere, and the somewhere was always the clock. Nothing in the estate
        does both."""
        for rel, used in _esr_key_census().items():
            if "raw_esr_backfill_key" in used:
                assert not used & set(_PARTITION_KEY_FUNCS), (
                    f"{rel} names the UNDATED backfill key AND writes a partition")

    def test_no_ESR_writer_carries_a_TODAYS_DATE_default(self):
        """The three literal forms this estate has actually shipped, swept over the census plus
        the refused writer. A clock default that yields a YEAR survives on purpose --
        ``--end-year`` is a RANGE, not a point-in-time -- and is asserted present below so the pin
        cannot be satisfied by deleting the wrong thing."""
        files = sorted(set(_esr_key_census()) | {"jobs/ingest/backfill_bronze_usda_esr.py"})
        for rel in files:
            src = (_REPO / rel).read_text(encoding="utf-8")
            for defect in ("default=datetime.date.today().isoformat()",
                           "date.today().strftime",
                           "args.as_of_date or datetime",
                           "INGEST_DATE.replace("):
                assert defect not in src, f"{rel} carries {defect!r}"
        silver = (_REPO / "jobs" / "ingest" / "backfill_silver_usda_esr.py").read_text(
            encoding="utf-8")
        assert "datetime.date.today().year" in silver, "a YEAR RANGE is not a vintage"

    def test_the_LAW_ABIDING_FIFTH_the_airflow_DAG_takes_as_of_from_the_RAW_KEY(self):
        """It writes bronze inline (transform_all_to_bronze) and never needed a change, but it
        must be NAMED: the last review round lost a whole writer to an unenumerated census."""
        dag = (_REPO / "dags" / "airflow" / "esr_weekly_ingest_dag.py").read_text(encoding="utf-8")
        assert 'as_of    = item["as_of"]' in dag, "the as_of is the uploaded raw key's own segment"
        assert "b_key = bronze_esr_key(code, year, as_of)" in dag
        assert "ingest_date=today_iso" in dag, "today reaches the INGEST date and stops there"

    def test_the_glue_bronze_writer_REFUSES_a_backfill_rebronze_by_name(self):
        src = self._glue_src()
        assert "raise RuntimeError(_BACKFILL_REFUSAL)" in src
        assert "REFUSING (ESR VINTAGE LAW)" in src
        assert "jobs/batch/esr_task.py --include-backfill" in src, (
            "a refusal must name the law-abiding writer, or it is only an obstacle")
        assert "8,474 of 8,920" in src, "the refusal carries its own measurement"

    def test_the_glue_bronze_writer_can_no_longer_DATE_a_key_from_the_run(self):
        """The defect was one expression -- ``INGEST_DATE.replace("-", "")`` paired with an
        undated backfill key. The pin is the absence of the MECHANISM, not of a comment: the
        ingest date can no longer reach a bronze as_of, and the module can no longer even NAME an
        undated backfill key. ``ingest_date=INGEST_DATE`` stays, because that IS the ingest date.
        """
        src = self._glue_src()
        assert "INGEST_DATE.replace(" not in src
        assert "raw_esr_backfill_key" not in src
        assert "ingest_date=INGEST_DATE" in src

    def test_the_glue_weekly_mode_was_always_law_abiding_and_still_works(self):
        """Weekly reads ``raw_esr_weekly_key(code, year, AS_OF)`` and writes
        ``bronze_esr_key(..., AS_OF)``: the bronze vintage IS the raw key's own as_of segment,
        provenance ``raw_key``. The refusal must not have taken it down with it."""
        src = self._glue_src()
        assert "raw_esr_weekly_key(code, year, AS_OF)" in src
        assert "pairs.append((code, year, raw_key, AS_OF))" in src

    def test_the_silver_backfill_writer_REFUSES_a_defaulted_vintage(self):
        mod = self._silver_backfill()
        for missing in (None, "", "   "):
            with pytest.raises(ValueError) as exc:
                mod.resolve_as_of_date(missing)
            assert "--as-of-date is REQUIRED" in str(exc.value)
            assert "THE VINTAGE LAW" in str(exc.value)

    def test_the_silver_backfill_writer_refuses_a_malformed_vintage_and_accepts_a_real_one(self):
        mod = self._silver_backfill()
        for bad in ("2026-07-12", "202607", "2026071a", "0", "202607123"):
            with pytest.raises(ValueError):
                mod.resolve_as_of_date(bad)
        assert mod.resolve_as_of_date("20260712") == "20260712"
        assert mod.resolve_as_of_date(" 20260712 ") == "20260712"

    def test_the_silver_backfill_writer_reads_no_clock_for_a_VINTAGE(self):
        """``--end-year`` still defaults off the clock and that is fine: a YEAR RANGE is not a
        point-in-time. What is gone is every path from today's date to an as_of."""
        src = (_REPO / "jobs" / "ingest" / "backfill_silver_usda_esr.py").read_text(
            encoding="utf-8")
        assert "date.today().strftime" not in src
        assert "args.as_of_date or datetime" not in src
        assert "resolve_as_of_date(args.as_of_date)" in src
        assert "datetime.date.today().year" in src
