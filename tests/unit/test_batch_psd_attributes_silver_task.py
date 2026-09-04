"""Unit tests for the USDA PSD LONG attributes silver Batch task (Lane 3 publish job).

The task is the long-table sibling of ``jobs/batch/psd_silver_task.py`` and deliberately owns very
little: the bronze load and the F2 fail-closed release_date guard are IMPORTED from that producer,
so the tests here assert the IMPORT (function identity) rather than re-testing the donor's covered
behaviour. What IS new is asserted directly: the declared-grain guard, the wide/long attribute
split, the canonical key, and the three-mode shadow-first publish including the
``--force-overwrite`` default-False skip path.

The F010 ``silver_psd_attributes`` contract lands separately, so this suite STUBS it: a minimal
contract dict on the allowlisted TEST bucket/database, pinned by
``test_stub_columns_match_the_transform_output_schema`` to the transform's own output schema. The
stub is therefore only ever wrong in the same way the real contract would be.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver.publisher import ManifestState
from leviathan.storage.paths import silver_psd_attributes_key, silver_psd_key
from leviathan.transforms.bronze_to_silver.usda_psd import _TARGET_ATTRS
from leviathan.transforms.bronze_to_silver.usda_psd_attributes import (
    _GRAIN_COLS,
    _SILVER_PSD_ATTR_COLS,
)

from jobs.batch import psd_attributes_silver_task as task
from jobs.batch import psd_silver_task as wide_task
from tests.unit.silver.conftest import (
    TEST_BUCKET,
    TEST_DB,
    FakeS3,
    canonical_authorization,
    dryrun_authorization,
    shadow_authorization,
)

_INGEST = "2026-05-20"
_SENTINEL = b"OLD-CANONICAL-PSD-ATTRIBUTES"

# The F010 contract stub. Types are the INV-2 TARGET writer schema (the widen targets, so the two
# small ints the transform emits as Int16/Int8 are written as int64) -- the same shape
# configs/silver/tables/silver_psd.yaml declares for the wide table.
_ARROW = {
    "leviathan_slug":      ("string", False),
    "country":             ("string", False),
    "market_year":         ("int64", False),
    "wasde_release_month": ("int64", True),
    "release_date":        ("string", False),
    "attribute":           ("string", False),
    "attribute_id":        ("int64", False),
    "value":               ("float64", True),
    "unit":                ("string", False),
}
_CONTRACT: dict = {
    "table_name": "silver_psd_attributes",
    "glue_database": TEST_DB,
    "s3_bucket": TEST_BUCKET,
    "s3_prefix": "silver/psd_attributes",
    "s3_root": f"s3://{TEST_BUCKET}/silver/psd_attributes",
    "schema_version": 1,
    "physical_columns": [
        {"name": name, "target_arrow_type": arrow, "nullable": nullable}
        for name, (arrow, nullable) in _ARROW.items()
    ],
    "value_columns": ["value"],
    "min_nonnull_frac": 0.5,
}


def _row(**over) -> dict:
    row = {
        "leviathan_slug": "corn_cbot", "country": "united_states",
        "market_year": 2024, "wasde_release_month": 5, "release_date": "2026-05-10",
        "attribute": "Production", "attribute_id": 28, "value": 380.0, "unit": "(1000 MT)",
    }
    row.update(over)
    return row


def _long_df(*rows: dict) -> pd.DataFrame:
    """A long frame in the transform's OWN dtypes (Int16/Int8), so the encode is proved as shipped."""
    df = pd.DataFrame(list(rows) or [_row()])
    return df[_SILVER_PSD_ATTR_COLS].astype(
        {"market_year": "Int16", "wasde_release_month": "Int8", "attribute_id": "Int16"}
    )


def _empty_long_df() -> pd.DataFrame:
    return pd.DataFrame({c: [] for c in _SILVER_PSD_ATTR_COLS})


# ---------------------------------------------------------------------------
# TestContractStub
# ---------------------------------------------------------------------------

class TestContractStub:
    def test_stub_columns_match_the_transform_output_schema(self) -> None:
        # The stub may differ from the real contract in bucket/db, never in shape.
        assert [c["name"] for c in _CONTRACT["physical_columns"]] == _SILVER_PSD_ATTR_COLS

    def test_task_names_the_long_table(self) -> None:
        assert task._TABLE == "silver_psd_attributes"


# ---------------------------------------------------------------------------
# TestSharedHelpers -- the bronze load + F2 guard are IMPORTED, never copied
# ---------------------------------------------------------------------------

class TestSharedHelpers:
    @pytest.mark.parametrize("name", [
        "_load_bronze", "_snapshot_ingest_date", "_assert_release_dates_not_future",
        "_exists", "_caller_identity",
    ])
    def test_helper_is_the_wide_producers_own_function(self, name: str) -> None:
        """Identity, not equivalence: a copy would pass a behavioural test and still drift."""
        assert getattr(task, name) is getattr(wide_task, name)


# ---------------------------------------------------------------------------
# TestReleaseDateGuard (F2) -- exercised through the long task's binding
# ---------------------------------------------------------------------------

class TestReleaseDateGuard:
    @staticmethod
    def _silver(release_dates: list[str]) -> pd.DataFrame:
        return pd.DataFrame({
            "leviathan_slug": ["corn_cbot"] * len(release_dates),
            "release_date":   release_dates,
        })

    def test_all_historical_passes(self) -> None:
        task._assert_release_dates_not_future(self._silver(["2001-01-10", _INGEST]), _INGEST)

    def test_future_row_raises(self) -> None:
        with pytest.raises(ValueError, match="post-date the bronze snapshot"):
            task._assert_release_dates_not_future(self._silver(["2027-03-10"]), _INGEST)

    def test_bound_derives_from_bronze_then_the_guard_flags_the_bypass(self) -> None:
        bronze = pd.DataFrame({"commodity_code": [440000], "release_date": [_INGEST]})
        ingest = task._snapshot_ingest_date([bronze])
        with pytest.raises(ValueError, match="post-date the bronze snapshot"):
            task._assert_release_dates_not_future(self._silver(["2027-03-10"]), ingest)


# ---------------------------------------------------------------------------
# TestGrainGuard -- the long table's declared grain must be unique at the write
# ---------------------------------------------------------------------------

class TestGrainGuard:
    def test_unique_frame_reports_zero(self) -> None:
        df = _long_df(_row(), _row(attribute="Exports", attribute_id=88))
        assert task._assert_grain_unique(df) == 0

    def test_empty_frame_is_a_noop(self) -> None:
        assert task._assert_grain_unique(_empty_long_df()) == 0

    def test_duplicate_grain_raises_with_count_and_key(self) -> None:
        # Same grain, different value: exactly the shape a bypassed vintage dedup leaves behind.
        df = _long_df(_row(), _row(value=999.0))
        with pytest.raises(ValueError) as exc:
            task._assert_grain_unique(df)
        msg = str(exc.value)
        assert "1 row(s) duplicate the declared grain" in msg
        assert "wasde_release_month" in msg          # the grain is named, not just counted
        assert "corn_cbot" in msg                    # and an offending key is shown

    def test_rows_differing_only_in_release_month_are_not_duplicates(self) -> None:
        """wasde_release_month IS part of the grain -- the silver_wasde collapse it closes."""
        df = _long_df(_row(wasde_release_month=5), _row(wasde_release_month=6))
        assert task._assert_grain_unique(df) == 0


# ---------------------------------------------------------------------------
# TestAttributeSplit -- the declared-vs-total coverage accounting
# ---------------------------------------------------------------------------

class TestAttributeSplit:
    def test_wide_served_set_is_the_eight_pivots_plus_three_native_aliases(self) -> None:
        # A count pin that moves with the wide table's population: it is derived from
        # _TARGET_ATTRS, and the +3 is only correct because the aliases are not already in it.
        assert len(task._WIDE_SERVED_ATTRS) == len(_TARGET_ATTRS) + 3
        assert _TARGET_ATTRS <= task._WIDE_SERVED_ATTRS

    def test_a_wide_attribute_counts_as_declared(self) -> None:
        assert task._attribute_split(_long_df(_row(attribute="Production"))) == (1, 1, 1, 1)

    def test_a_native_consumption_alias_counts_as_declared(self) -> None:
        """Sugar's "Total Disappearance" IS silver_psd's consumption column wearing USDA's label."""
        df = _long_df(_row(leviathan_slug="raw_sugar", attribute="Total Disappearance",
                           attribute_id=126))
        assert task._attribute_split(df) == (1, 1, 1, 1)

    def test_an_alias_on_the_wrong_slug_is_not_wide_served(self) -> None:
        """THE SLUG GATE (Lane-3 job review, measured case): the wide producer's remaps are
        slug-gated (usda_psd.py:719-731), so the SAME native labels on OTHER slugs are rows
        silver_psd DROPS -- cottonseed's family emits 142, frozen_orange_juice emits 135, and
        neither is served anywhere but here. A label-alone split read this 3-row frame as 3/3
        already-served when the wide table serves none of it."""
        df = _long_df(
            _row(leviathan_slug="cottonseed", attribute="Total Disappearance", attribute_id=126),
            _row(leviathan_slug="cottonseed_oil", attribute="Domestic Use", attribute_id=142),
            _row(leviathan_slug="frozen_orange_juice", attribute="Fresh Dom. Consumption",
                 attribute_id=135),
        )
        n_declared, n_total, declared_rows, total_rows = task._attribute_split(df)
        assert (n_declared, declared_rows) == (0, 0), \
            "an alias row off its remap slug counted as wide-served -- the over-report the gate closes"
        assert (n_total, total_rows) == (3, 3)

    def test_the_alias_gate_splits_one_label_across_slugs(self) -> None:
        """The row axis is the honest one: the same label in the same frame counts served on its
        remap slug and unserved off it."""
        df = _long_df(
            _row(leviathan_slug="raw_sugar", attribute="Total Disappearance", attribute_id=126),
            _row(leviathan_slug="cottonseed", attribute="Total Disappearance", attribute_id=126),
        )
        n_declared, n_total, declared_rows, total_rows = task._attribute_split(df)
        assert (declared_rows, total_rows) == (1, 2)
        assert (n_declared, n_total) == (1, 1)

    def test_an_unserved_label_counts_only_here(self) -> None:
        df = _long_df(_row(attribute="Crush", attribute_id=57))
        n_declared, n_total, declared_rows, total_rows = task._attribute_split(df)
        assert (n_declared, n_total, declared_rows, total_rows) == (0, 1, 0, 1)

    def test_split_arithmetic_holds_on_a_mixed_frame(self) -> None:
        df = _long_df(
            _row(attribute="Production", attribute_id=28),
            _row(attribute="Crush", attribute_id=57),
            _row(attribute="Extr. Rate, 999.9999", attribute_id=118, unit="(PERCENT)"),
        )
        n_declared, n_total, declared_rows, total_rows = task._attribute_split(df)
        assert (n_declared, n_total) == (1, 3)
        assert (declared_rows, total_rows) == (1, 3)
        assert n_total - n_declared == 2          # the coverage this table exists to add

    def test_empty_frame_reports_zeros(self) -> None:
        assert task._attribute_split(_empty_long_df()) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# TestCanonicalKey
# ---------------------------------------------------------------------------

class TestCanonicalKey:
    def test_key_value(self) -> None:
        assert silver_psd_attributes_key() == "silver/psd_attributes/part-000.parquet"

    def test_is_a_sibling_of_the_wide_root_not_a_child(self) -> None:
        # The wide table's recovery strategy is a bounded full relist under silver/psd/; a long
        # object nested there would be relisted as wide data.
        assert not silver_psd_attributes_key().startswith("silver/psd/")
        assert silver_psd_attributes_key() != silver_psd_key()


# ---------------------------------------------------------------------------
# TestShadowFirstPublish
# ---------------------------------------------------------------------------

def _data_keys(s3: FakeS3) -> list[str]:
    """Every object EXCEPT the control-plane run manifest (which every mode persists)."""
    return [k for k in s3.keys() if "/_manifests/" not in k]


class TestShadowFirstPublish:
    def test_dry_run_writes_nothing_but_validates(self) -> None:
        # main() passes s3_client=None in dry-run; the plan reaches VALIDATED with nothing written.
        state = task._publish_psd_attributes(_long_df(), _CONTRACT, dryrun_authorization(), None,
                                             TEST_BUCKET, force_overwrite=True)
        assert state is ManifestState.VALIDATED

    def test_dry_run_handed_a_live_client_still_stages_no_data_object(self) -> None:
        s3 = FakeS3()
        state = task._publish_psd_attributes(_long_df(), _CONTRACT, dryrun_authorization(), s3,
                                             TEST_BUCKET, force_overwrite=True)
        assert state is ManifestState.VALIDATED
        assert _data_keys(s3) == []

    def test_shadow_stages_to_shadow_only_and_leaves_canonical_byte_identical(self) -> None:
        s3 = FakeS3()
        canonical_key = silver_psd_attributes_key()
        s3.store[(TEST_BUCKET, canonical_key)] = _SENTINEL
        etag_before = s3._etag(_SENTINEL)

        state = task._publish_psd_attributes(_long_df(), _CONTRACT, shadow_authorization(), s3,
                                             TEST_BUCKET, force_overwrite=True)

        assert state is ManifestState.VALIDATED
        assert s3.store[(TEST_BUCKET, canonical_key)] == _SENTINEL
        assert s3._etag(s3.store[(TEST_BUCKET, canonical_key)]) == etag_before
        assert any("_shadow" in k for k in s3.keys())
        for key in _data_keys(s3):
            if key == canonical_key:
                continue
            assert "/_shadow/" in key

    def test_canonical_overwrites_the_long_silver_object(self) -> None:
        s3 = FakeS3()
        canonical_key = silver_psd_attributes_key()
        s3.store[(TEST_BUCKET, canonical_key)] = _SENTINEL

        state = task._publish_psd_attributes(_long_df(), _CONTRACT, canonical_authorization(), s3,
                                             TEST_BUCKET, force_overwrite=True)

        assert state is ManifestState.CERTIFIED
        assert s3.store[(TEST_BUCKET, canonical_key)] != _SENTINEL


# ---------------------------------------------------------------------------
# TestForceOverwriteDefault -- store_true, DEFAULTS FALSE, and the default is a no-op
# ---------------------------------------------------------------------------

class TestForceOverwriteDefault:
    def test_canonical_over_an_existing_object_skips_and_writes_nothing(self, caplog) -> None:
        """The burn: SUCCEEDED job, untouched table. Documented in the usage docstring."""
        s3 = FakeS3()
        canonical_key = silver_psd_attributes_key()
        s3.store[(TEST_BUCKET, canonical_key)] = _SENTINEL

        with caplog.at_level("INFO", logger="psd_attributes_silver_task"):
            state = task._publish_psd_attributes(_long_df(), _CONTRACT, canonical_authorization(),
                                                 s3, TEST_BUCKET, force_overwrite=False)

        assert state is None
        assert s3.store[(TEST_BUCKET, canonical_key)] == _SENTINEL
        assert _data_keys(s3) == [canonical_key]          # nothing staged either
        assert "--force-overwrite" in caplog.text          # the skip names its own remedy

    def test_canonical_with_no_existing_object_publishes_without_the_flag(self) -> None:
        s3 = FakeS3()
        state = task._publish_psd_attributes(_long_df(), _CONTRACT, canonical_authorization(), s3,
                                             TEST_BUCKET, force_overwrite=False)
        assert state is ManifestState.CERTIFIED
        assert (TEST_BUCKET, silver_psd_attributes_key()) in s3.store

    def test_shadow_over_an_existing_canonical_object_is_never_skipped(self) -> None:
        """The skip is gated on may_mutate_canonical: shadow must still build its candidate."""
        s3 = FakeS3()
        s3.store[(TEST_BUCKET, silver_psd_attributes_key())] = _SENTINEL

        state = task._publish_psd_attributes(_long_df(), _CONTRACT, shadow_authorization(), s3,
                                             TEST_BUCKET, force_overwrite=False)

        assert state is ManifestState.VALIDATED
        assert any("/_shadow/" in k for k in _data_keys(s3))

    def test_cli_defaults_force_overwrite_to_false(self) -> None:
        parser = task._build_arg_parser()
        assert parser.parse_args([]).force_overwrite is False
        assert parser.parse_args(["--force-overwrite"]).force_overwrite is True

    def test_cli_defaults_publish_mode_to_dry_run(self) -> None:
        args = task._build_arg_parser().parse_args([])
        assert args.publish_mode == "dry-run"
        assert args.on_uncovered == "drop"


# ---------------------------------------------------------------------------
# TestPublisherWiring -- the contract and key the publisher actually receives
# ---------------------------------------------------------------------------

class TestPublisherWiring:
    def test_build_flat_publish_receives_the_long_contract_and_canonical_key(self, monkeypatch) -> None:
        seen: dict = {}

        class _Plan:
            def run(self):
                class _M:
                    state = ManifestState.VALIDATED
                return _M()

        def _capture(**kw):
            seen.update(kw)
            return _Plan()

        monkeypatch.setattr(task, "build_flat_publish", _capture)
        task._publish_psd_attributes(_long_df(), _CONTRACT, dryrun_authorization(), None,
                                     TEST_BUCKET, force_overwrite=True)

        assert seen["contract"]["table_name"] == "silver_psd_attributes"
        assert seen["canonical_key"] == silver_psd_attributes_key()
        assert seen["job"] == "psd_attributes_silver"
        assert seen["s3_client"] is None


# ---------------------------------------------------------------------------
# TestSubmitWrapper -- the pure command builder (no boto3 traffic)
# ---------------------------------------------------------------------------

_SUBMIT_DIR = Path(__file__).resolve().parents[2] / "jobs" / "submit"


def _load_submit():
    spec = importlib.util.spec_from_file_location(
        "submit_batch_psd_attributes_silver",
        _SUBMIT_DIR / "submit_batch_psd_attributes_silver.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


submit = _load_submit()


class TestSubmitWrapper:
    def test_command_is_module_form(self) -> None:
        """Script form cannot resolve the task's `jobs.batch.psd_silver_task` import."""
        cmd = submit.build_command(publish_mode="shadow", force_overwrite=False)
        assert cmd[:2] == ["-m", "jobs.batch.psd_attributes_silver_task"]

    def test_publish_mode_is_forwarded(self) -> None:
        cmd = submit.build_command(publish_mode="canonical", force_overwrite=True)
        assert cmd[cmd.index("--publish-mode") + 1] == "canonical"

    def test_force_overwrite_is_absent_unless_asked_for(self) -> None:
        assert "--force-overwrite" not in submit.build_command(
            publish_mode="shadow", force_overwrite=False)
        assert "--force-overwrite" in submit.build_command(
            publish_mode="canonical", force_overwrite=True)

    def test_on_uncovered_default_is_not_emitted(self) -> None:
        # Keeps the submitted command byte-comparable with the job definition's baked one.
        assert "--on-uncovered" not in submit.build_command(
            publish_mode="shadow", force_overwrite=False)
        assert submit.build_command(publish_mode="shadow", force_overwrite=False,
                                    on_uncovered="raise")[-2:] == ["--on-uncovered", "raise"]

    def test_default_queue_is_on_demand(self) -> None:
        """leviathan-dev-queue is SPOT; a reclaimed publisher is a half-run write path."""
        source = (_SUBMIT_DIR / "submit_batch_psd_attributes_silver.py").read_text(encoding="utf-8")
        assert '{project}-{env}-queue-ondemand' in source
        assert 'default_queue = f"{project}-{env}-queue"' not in source


# ---------------------------------------------------------------------------
# P19 / T14 -- THE TWO PRODUCERS SHARE ONE CALENDAR READ
# ---------------------------------------------------------------------------

class TestTheLongTaskSharesTheWideTasksCalendarRead:
    """Two copies of the calendar read are two producers that date the same rows
    differently. The long task IMPORTS the wide task's reader and its counter log,
    exactly as it already imports the bronze load and the F2 guard -- one-way, and
    never re-implemented."""

    def test_it_imports_the_reader_rather_than_re_implementing_it(self) -> None:
        import inspect

        from jobs.batch import psd_attributes_silver_task as long_task
        from jobs.batch import psd_silver_task as wide_task

        assert long_task.wasde_release_calendar is wide_task.wasde_release_calendar
        assert long_task.log_clock_counters is wide_task.log_clock_counters
        src = inspect.getsource(long_task)
        assert "get_partitions" not in src, "the calendar read must live in ONE module"
        assert "gen_wasde_release_calendar" not in src

    def test_the_long_transform_refuses_to_run_without_a_calendar(self) -> None:
        import pandas as pd
        import pytest as _pytest
        from leviathan.transforms.bronze_to_silver.usda_psd_attributes import (
            transform_psd_attributes_bronze_to_silver,
        )

        with _pytest.raises(TypeError, match="calendar"):
            transform_psd_attributes_bronze_to_silver([pd.DataFrame()])
