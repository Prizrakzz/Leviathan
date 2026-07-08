"""Unit tests for the scanned-WASDE per-page index (6.5 click-to-page, W1b).

Coverage:
- pageindex.build_pages_json: per-page regrouping, Top ordering, LINE filter,
  empty input, page_count semantics.
- pageindex.sidecar_key: document.json -> pages.json derivation (+ fallback).
- wasde_pageindex_task: sidecar key chaining, cost estimate, dry-run
  enumerate + skip-if-exists (mocked S3 listing + fake head_object client).

All tests are hermetic: no real Textract, no real S3, no real PDFs -- Textract
``Blocks`` and S3 listings are synthetic, and the fake S3 client only implements
``head_object``.  The paid ``--apply`` path is never exercised.
"""
from __future__ import annotations

from botocore.exceptions import ClientError
from leviathan.transforms.raw_to_text.pageindex import build_pages_json, sidecar_key

from jobs.batch import wasde_pageindex_task as task

# ---------------------------------------------------------------------------
# Helpers: synthetic Textract blocks + a minimal fake S3 client
# ---------------------------------------------------------------------------

def _make_blocks(*lines: "tuple[int, float, str]") -> "list[dict]":
    """Return LINE blocks from ``(page, top, text)`` tuples.

    ``top`` is a float in [0.0, 1.0] following the Textract BoundingBox
    convention.  Mirrors the helper in ``test_transforms_wasde_scanned``.
    """
    return [
        {
            "BlockType": "LINE",
            "Page": page,
            "Text": text,
            "Geometry": {"BoundingBox": {"Top": top, "Left": 0.0, "Width": 1.0, "Height": 0.01}},
        }
        for page, top, text in lines
    ]


class _FakeS3:
    """Fake S3 client implementing only ``head_object`` for existence checks.

    Keys present in *existing* are treated as live objects; any other key raises
    a 404 ``ClientError`` exactly like real S3, which is what
    ``writer.document_exists`` inspects.
    """

    def __init__(self, existing: "set[str]") -> None:
        self._existing = existing

    def head_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803 (boto3 kwargs)
        if Key in self._existing:
            return {"ContentLength": 1}
        raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")


# ---------------------------------------------------------------------------
# build_pages_json
# ---------------------------------------------------------------------------

def test_build_pages_json_two_pages_ordered_by_top() -> None:
    """Blocks given out of order regroup into 2 pages, each Top-sorted."""
    blocks = _make_blocks(
        (2, 0.30, "Page 2 middle"),
        (1, 0.80, "Page 1 bottom"),
        (2, 0.05, "Page 2 top"),
        (1, 0.10, "Page 1 top"),
    )
    result = build_pages_json(blocks)

    assert result["page_count"] == 2
    assert [p["page"] for p in result["pages"]] == [1, 2]
    assert result["pages"][0]["text"] == "Page 1 top\nPage 1 bottom"
    assert result["pages"][1]["text"] == "Page 2 top\nPage 2 middle"


def test_build_pages_json_ignores_non_line_blocks() -> None:
    """PAGE / WORD blocks must not contribute to any page's text."""
    blocks = [
        {"BlockType": "PAGE", "Page": 1, "Text": "ignore-me", "Geometry": {"BoundingBox": {"Top": 0.0}}},
        {"BlockType": "LINE", "Page": 1, "Text": "real line", "Geometry": {"BoundingBox": {"Top": 0.1}}},
        {"BlockType": "WORD", "Page": 1, "Text": "also-ignore", "Geometry": {"BoundingBox": {"Top": 0.2}}},
    ]
    result = build_pages_json(blocks)
    assert result["page_count"] == 1
    assert result["pages"][0]["text"] == "real line"


def test_build_pages_json_consistent_with_joined_full_text() -> None:
    """Joining per-page text with newlines reproduces the extractor's full_text.

    This is the invariant the resolver depends on: the same sort key + join
    filter as ``extract_wasde_scanned`` means the concatenation of page texts
    equals the single joined string, so a fuzzy match localises correctly.
    """
    blocks = _make_blocks(
        (1, 0.10, "alpha"),
        (1, 0.20, "beta"),
        (2, 0.10, "gamma"),
    )
    result = build_pages_json(blocks)
    rejoined = "\n".join(p["text"] for p in result["pages"])
    assert rejoined == "alpha\nbeta\ngamma"


def test_build_pages_json_empty() -> None:
    """No blocks -> empty index, not an error."""
    result = build_pages_json([])
    assert result == {"page_count": 0, "pages": []}


def test_build_pages_json_skips_empty_text_in_join() -> None:
    """A LINE block with empty Text is dropped from the join (matches extractor)."""
    blocks = [
        {"BlockType": "LINE", "Page": 1, "Text": "", "Geometry": {"BoundingBox": {"Top": 0.05}}},
        {"BlockType": "LINE", "Page": 1, "Text": "kept", "Geometry": {"BoundingBox": {"Top": 0.10}}},
    ]
    result = build_pages_json(blocks)
    assert result["pages"][0]["text"] == "kept"


# ---------------------------------------------------------------------------
# sidecar_key
# ---------------------------------------------------------------------------

def test_sidecar_key_from_document_json() -> None:
    src = "text/source=usda_wasde/release_date=1976-07-12/document.json"
    assert (
        sidecar_key(src)
        == "text/source=usda_wasde/release_date=1976-07-12/pages.json"
    )


def test_sidecar_key_non_document_basename_fallback() -> None:
    """Defensive: a non-document.json key still yields a sibling pages.json."""
    assert sidecar_key("text/foo/bar/other.json") == "text/foo/bar/pages.json"


def test_sidecar_key_bare_name() -> None:
    assert sidecar_key("document.json") == "pages.json"


# ---------------------------------------------------------------------------
# wasde_pageindex_task._sidecar_for_raw_key
# ---------------------------------------------------------------------------

def test_sidecar_for_raw_key_chains_derivations() -> None:
    raw_key = "raw/production/source=usda_wasde/release_date=1976-07-12/wasde0776.pdf"
    assert (
        task._sidecar_for_raw_key(raw_key)
        == "text/source=usda_wasde/release_date=1976-07-12/pages.json"
    )


# ---------------------------------------------------------------------------
# wasde_pageindex_task.estimate_cost
# ---------------------------------------------------------------------------

def test_estimate_cost_upper_bound() -> None:
    pages, cost = task.estimate_cost(251)
    # 251 docs * 8 pages = 2008 pages; 2008 * 1.5 / 1000 = 3.012
    assert pages == 251 * 8
    assert abs(cost - (251 * 8 * 1.5 / 1000.0)) < 1e-9


def test_estimate_cost_zero_docs() -> None:
    pages, cost = task.estimate_cost(0)
    assert pages == 0
    assert cost == 0.0


# ---------------------------------------------------------------------------
# wasde_pageindex_task.discover_pending / run_dry_run (mocked S3 listing)
# ---------------------------------------------------------------------------

# A synthetic raw listing: 3 scanned .pdf (year < 1999), plus non-scanned noise
# that the discriminator must exclude (a 1997 .txt and a 2014 digital .pdf).
_RAW_LISTING = [
    "raw/production/source=usda_wasde/release_date=1976-07-12/wasde0776.pdf",  # scanned
    "raw/production/source=usda_wasde/release_date=1994-12-09/wasde1294.pdf",  # scanned
    "raw/production/source=usda_wasde/release_date=1998-03-11/wasde0398.pdf",  # scanned
    "raw/production/source=usda_wasde/release_date=1997-06-12/wasde0697.txt",  # txt -> excluded
    "raw/production/source=usda_wasde/release_date=2014-01-10/wasde0114.pdf",  # digital -> excluded
]


def test_discover_pending_filters_and_skips(monkeypatch) -> None:
    """Only scanned keys are considered; keys whose sidecar exists are skipped."""
    monkeypatch.setattr(task, "list_s3_keys", lambda *a, **k: list(_RAW_LISTING))

    # Pretend the 1994 sidecar already landed -> it must be skipped, not pending.
    existing = {
        "text/source=usda_wasde/release_date=1994-12-09/pages.json",
    }
    fake = _FakeS3(existing)

    scanned, pending, skipped = task.discover_pending("bucket", s3_client=fake)

    assert len(scanned) == 3  # 3 scanned pdfs, txt + digital excluded
    assert skipped == 1
    assert pending == [
        "raw/production/source=usda_wasde/release_date=1976-07-12/wasde0776.pdf",
        "raw/production/source=usda_wasde/release_date=1998-03-11/wasde0398.pdf",
    ]


def test_discover_pending_all_present(monkeypatch) -> None:
    """When every sidecar exists, nothing is pending (idempotent no-op)."""
    monkeypatch.setattr(task, "list_s3_keys", lambda *a, **k: list(_RAW_LISTING))
    # The exact set of sidecars for the 3 scanned pdfs (derived via the task's
    # own chaining so the test tracks the real key derivation).
    existing = {
        task._sidecar_for_raw_key(k) for k in _RAW_LISTING if task._is_scanned_key(k)
    }
    fake = _FakeS3(existing)

    scanned, pending, skipped = task.discover_pending("bucket", s3_client=fake)
    assert len(scanned) == 3
    assert pending == []
    assert skipped == 3


def test_run_dry_run_reports_and_submits_nothing(monkeypatch, capsys) -> None:
    """Dry-run prints an ASCII cost report and returns a correct summary."""
    monkeypatch.setattr(task, "list_s3_keys", lambda *a, **k: list(_RAW_LISTING))
    fake = _FakeS3(set())  # nothing indexed yet -> all 3 pending

    summary = task.run_dry_run("bucket", s3_client=fake)

    assert summary["scanned"] == 3
    assert summary["pending"] == 3
    assert summary["skipped"] == 0
    assert summary["pages"] == 3 * task._MAX_NARRATIVE_PAGES
    assert abs(summary["cost_usd"] - (3 * 8 * 1.5 / 1000.0)) < 1e-9

    out = capsys.readouterr().out
    assert "submitting NOTHING" in out
    assert "--apply" in out
    # stdout must be ASCII-only (Windows cp1252 console guard).
    out.encode("ascii")
