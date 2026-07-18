"""CEC W2/W3 -- raw->silver-direct wiring (D6=(a)): per-file quarantine, D5 dedup, D2a idempotency.

Task #118. W2/W3 folds the era-aware W1 parser into the silver read path
(``jobs/batch/sagis_cec_silver_task``): the task now reads intact RAW workbooks, parses them
in-process, reconciles estimate numbers across the corpus (D2), and publishes shadow-first -- no
bronze hop, so the live-bronze correction gap that DEFERRED this task is gone by construction.

These tests lock the load-path contract on the committed real raw fixtures + synthetic edge cases:
  * ``parse_raw_reports`` fail-closes PER FILE (a bad object is quarantined + named, the rest parse);
  * byte-identical re-fetched duplicates (the D5 renamed-duplicate hazard) are deduped, never
    double-counted;
  * the full raw->reconcile->transform->parquet pipeline is BYTE-IDENTICAL across input orderings
    (the W2 idempotency claim), exercising the D2a equal-release_date source_key tie-break;
  * ``load_observations`` filters the admin ``CEC_Dates_*`` schedule files and reads ``_RAW_PREFIX``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from jobs.batch import sagis_cec_silver_task as task
from jobs.batch.sagis_cec_silver_task import parse_raw_reports
from leviathan.silver.flat_producer import encode_parquet, null_metrics_for
from leviathan.silver.registry import load_registry
from leviathan.transforms.bronze_to_silver.sagis_cec import (
    CecObservation,
    transform_sagis_cec,
)
from leviathan.transforms.raw_to_bronze.sagis_cec import reconcile_estimate_numbers

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sagis_cec"
_FILES = [
    "CEC_2025-09.pdf",
    "CEC-2006-05-b-S.doc",
    "CEC-2024-05-b.doc",
    "CEC_2002_-_2005S.xls",
    "CEC-1999-10-20.pdf",
]


def _key(name: str) -> str:
    return f"raw/production/source=sagis_cec/{name}"


def _items(names: list[str]) -> list[tuple[str, bytes]]:
    return [(_key(n), (_FIXTURES / n).read_bytes()) for n in names]


def _silver_bytes(items: list[tuple[str, bytes]]) -> bytes:
    obs, _ = parse_raw_reports(items)
    df = transform_sagis_cec(reconcile_estimate_numbers(obs))
    contract = load_registry().table("silver_sagis_cec")
    return encode_parquet(df, contract)


# --------------------------------------------------------------------------- census / happy path
def test_parse_raw_reports_census_over_all_eras() -> None:
    """All five committed fixtures parse cleanly: 46 observations, one report per era, zero
    quarantine, zero dedup. Pins the raw-load census the W2 quantify step reports."""
    obs, census = parse_raw_reports(_items(_FILES))

    assert len(obs) == 46
    assert census.n_files == 5
    assert census.n_parsed == 5
    assert census.quarantined_files == []
    assert census.deduped_files == []
    # one report per distinct era signature (early_pdf / modern_pdf / old_doc / modern_doc / xls).
    assert sum(census.era_counts.values()) == 5
    assert len(census.era_counts) == 5


# --------------------------------------------------------------------------- fail-closed per file
def test_bad_magic_object_is_quarantined_not_fatal() -> None:
    """A raw object whose bytes match NO era signature (garbage magic) hits the parser's ratified
    fail-closed path (:class:`CecEraError`): it is quarantined (counted + named) while every good
    report in the same batch still parses -- the run is never killed."""
    good = _items(["CEC_2025-09.pdf"])
    bad = [(_key("CEC_2099-01-garbage.bin"), b"GARBAGE this is not a workbook of any recognised era")]
    obs, census = parse_raw_reports(good + bad)

    assert len(obs) == 10                    # the good report's rows survived
    assert census.n_parsed == 1
    assert len(census.quarantined_files) == 1
    q_key, q_type, _detail = census.quarantined_files[0]
    assert q_key.endswith("CEC_2099-01-garbage.bin")
    assert q_type == "CecEraError"           # ratified fail-closed name, not a raw library exception


def test_corrupt_source_is_quarantined_not_fatal() -> None:
    """A CORRUPT object with valid magic (a truncated ``%PDF`` that the library cannot open) must NOT
    crash the corpus run: it is quarantined under an ``unreadable:*`` reason (the library exception is
    caught at the load layer, never propagated), and a genuine Python bug would still surface."""
    good = _items(["CEC_2025-09.pdf"])
    corrupt = [(_key("CEC_2099-02-truncated.pdf"), b"%PDF-1.4 truncated junk with no /Root object " * 20)]
    obs, census = parse_raw_reports(good + corrupt)

    assert len(obs) == 10                    # the good report's rows survived
    assert census.n_parsed == 1
    assert len(census.quarantined_files) == 1
    q_key, q_type, _detail = census.quarantined_files[0]
    assert q_key.endswith("CEC_2099-02-truncated.pdf")
    assert q_type.startswith("unreadable:")


# --------------------------------------------------------------------------- D5 dedup
def test_byte_identical_duplicate_is_deduped() -> None:
    """The 2026-07-16 renamed-duplicate raw (same bytes, new filename) must NOT double-count. A
    byte-identical second copy is deduped by content hash, keeping the first source_key in order."""
    base = _items(["CEC_2025-09.pdf"])
    dup_bytes = base[0][1]
    dup = [(_key("CEC_2025-09-Summer-RENAMED.pdf"), dup_bytes)]

    obs, census = parse_raw_reports(base + dup)

    assert len(obs) == 10                     # NOT 20 -- the duplicate contributed nothing
    assert census.n_files == 2
    assert census.n_parsed == 1
    assert len(census.deduped_files) == 1
    dropped, kept = census.deduped_files[0]
    assert dropped.endswith("CEC_2025-09-Summer-RENAMED.pdf")
    assert kept.endswith("CEC_2025-09.pdf")


# --------------------------------------------------------------------------- W2 idempotency
def test_silver_parquet_byte_identical_across_input_order() -> None:
    """W2 idempotency: the raw->reconcile->transform->parquet pipeline is a pure function of the raw
    set, INDEPENDENT of the order the objects arrive in. Parsing the fixtures forward vs reversed
    yields byte-identical silver parquet (the reconcile total-order + transform NATURAL_KEY sort +
    explicit INV-2 schema make the write deterministic)."""
    forward = _silver_bytes(_items(_FILES))
    reverse = _silver_bytes(_items(list(reversed(_FILES))))
    assert forward == reverse
    assert len(forward) > 0


def test_d2a_tie_break_deterministic_on_equal_release_date() -> None:
    """D2a: within a (production_year, crop, scope) group, two estimates with the SAME release_date
    must be ordered by source_key so the derived estimate_number is stable on byte-identical re-runs.
    reconcile_estimate_numbers must assign the same numbers regardless of input order."""
    a = CecObservation(production_year=2024, report_month=5, crop="white_maize", scope="commercial",
                       estimate_number=-1, current_estimate_t=1000.0, release_date="2024-05-28",
                       source_key="raw/production/source=sagis_cec/CEC-2024-05-a.doc")
    b = CecObservation(production_year=2024, report_month=6, crop="white_maize", scope="commercial",
                       estimate_number=-1, current_estimate_t=1100.0, release_date="2024-05-28",
                       source_key="raw/production/source=sagis_cec/CEC-2024-05-b.doc")

    fwd = {o.source_key: o.estimate_number for o in reconcile_estimate_numbers([a, b])}
    rev = {o.source_key: o.estimate_number for o in reconcile_estimate_numbers([b, a])}

    assert fwd == rev                                       # order-independent
    # "-a" sorts before "-b" -> gets estimate 1, "-b" gets estimate 2, regardless of input order.
    assert fwd[a.source_key] == 1
    assert fwd[b.source_key] == 2


# --------------------------------------------------------------------------- D4 census input
def test_fixture_value_nonnull_fractions_are_the_d4_input() -> None:
    """The value-column non-null fractions the task logs for the D4 floor decision. On this
    deliberately-disjoint 5-fixture set (no two reports share a (year, crop, scope) with sequential
    estimates), revision_t / revision_surprise are STRUCTURALLY sparse -- a lower bound, NOT the
    full-corpus fraction. current_estimate_t is always populated. This documents WHY the floor is not
    recalibrated from the fixture census (the D4 override is left for the full-corpus shadow run)."""
    obs, _ = parse_raw_reports(_items(_FILES))
    df = transform_sagis_cec(reconcile_estimate_numbers(obs))
    metrics = null_metrics_for(df, ["current_estimate_t", "revision_t", "revision_surprise"])

    assert metrics["current_estimate_t"] == pytest.approx(1.0)
    assert metrics["revision_t"] == pytest.approx(0.0)          # no in-set sequential estimates
    assert metrics["revision_surprise"] < 0.5                    # only the 2024->2025 maize overlap


# --------------------------------------------------------------------------- load_observations wiring
def test_load_observations_filters_admin_and_reads_raw_prefix(monkeypatch) -> None:
    """load_observations lists ``_RAW_PREFIX``, drops the admin ``CEC_Dates_*`` schedule object, and
    parses the report objects in-process. Patches the S3 list/download seams (imported at call time)."""
    listed = [
        _key("CEC_2025-09.pdf"),
        _key("CEC_Dates_2025.pdf"),          # admin schedule file -- must be filtered out
        _key("CEC-1999-10-20.pdf"),
    ]
    blobs = {_key(n): (_FIXTURES / n).read_bytes() for n in ("CEC_2025-09.pdf", "CEC-1999-10-20.pdf")}
    blobs[_key("CEC_Dates_2025.pdf")] = b"%PDF-1.4 admin schedule, never parsed"

    monkeypatch.setattr("leviathan.storage.s3.get_thread_local_s3_client", lambda region: object())
    monkeypatch.setattr("leviathan.storage.s3.list_s3_keys",
                        lambda bucket, prefix, aws_region="us-east-1": list(listed))
    monkeypatch.setattr("leviathan.storage.s3.s3_download_with_retry",
                        lambda bucket, key, s3: blobs[key])

    obs = task.load_observations("leviathan-test", "us-east-1")

    # 10 (modern PDF) + 2 (early PDF wheat/barley) = 12; the admin file was never parsed.
    assert len(obs) == 12
    assert {o.crop for o in obs} & {"wheat", "barley"}       # early-PDF winter cereals present
    assert all(o.source_key != _key("CEC_Dates_2025.pdf") for o in obs)
