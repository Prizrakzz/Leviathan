"""Hermetic tests for the P2 W1 alias/waiver apply CLI (jobs/utils/apply_dag_aliases.py).

Every case runs against a SYNTHETIC tiny curation JSON + a SYNTHETIC driver_slices.yaml written into
tmp_path — NEVER the real gitignored private config (that carries term/mechanism IP). The synthetic YAML
reproduces only the shape the script depends on: a ``drivers:`` catalogue, a provenance comment block, and
a ``dag_alias:`` header with a couple of existing rows. We assert the four load-bearing contracts:

  * an alias id is appended to its target slice's RHS (existing entries preserved);
  * the new top-level ``waivers:`` block is created with category+note;
  * re-running --apply is byte-identical (idempotence) and never duplicates a present alias;
  * validation aborts (non-zero, file untouched) on a missing alias target and on a cross-slice duplicate.

We also pin comment survival — the whole point of the textual-splice write path (PyYAML would drop it).
"""
from __future__ import annotations

import json

import yaml

from jobs.utils import apply_dag_aliases as mod

# A synthetic driver_slices.yaml. Mirrors the real file's three-region shape (drivers / provenance
# comment / dag_alias) with invented, IP-free slice and id names. The comment line is what the splice
# must preserve; ``existing_slice`` already owns ``existing_id`` so we can prove existing RHS survives.
_DRIVERS_YAML = (
    "# synthetic header comment (must survive the splice)\n"
    "drivers:\n"
    "  existing_slice: {category: test, terms: [alpha]}\n"
    "  target_slice:   {category: test, terms: [beta]}\n"
    "  other_slice:    {category: test, terms: [gamma]}\n"
    "\n"
    "# -- PROVENANCE LAW: this comment block must be byte-preserved across apply --\n"
    "dag_alias:\n"
    "  existing_slice: [existing_id]\n"
)


def _write_yaml(tmp_path, text: str = _DRIVERS_YAML):
    p = tmp_path / "driver_slices.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def _write_curation(tmp_path, assignments: list[dict]):
    p = tmp_path / "curation.json"
    payload = {"basis": "synthetic", "totals": {}, "assignments": assignments}
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_alias_appended_to_target_rhs(tmp_path):
    """An alias assignment appends its id to the target slice's RHS, keeping existing entries."""
    y = _write_yaml(tmp_path)
    c = _write_curation(
        tmp_path,
        [{"id": "new_id", "action": "alias", "target_slice": "target_slice", "rationale": "why; extra"}],
    )
    stats = mod.apply(c, y, write=True)
    assert stats["n_alias_added"] == 1
    doc = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert doc["dag_alias"]["target_slice"] == ["new_id"]
    # Existing row untouched.
    assert doc["dag_alias"]["existing_slice"] == ["existing_id"]


def test_alias_extends_existing_slice(tmp_path):
    """Aliasing onto a slice that already has a RHS appends (does not replace) and preserves order."""
    y = _write_yaml(tmp_path)
    c = _write_curation(
        tmp_path,
        [{"id": "second_id", "action": "alias", "target_slice": "existing_slice", "rationale": "r"}],
    )
    mod.apply(c, y, write=True)
    doc = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert doc["dag_alias"]["existing_slice"] == ["existing_id", "second_id"]


def test_waiver_block_created(tmp_path):
    """Waiver assignments create the third top-level ``waivers:`` key with category + short note."""
    y = _write_yaml(tmp_path)
    c = _write_curation(
        tmp_path,
        [
            {"id": "fx_id", "action": "waiver_silver_only", "target_slice": None,
             "rationale": "FX cross; observed series"},
            {"id": "gap_id", "action": "waiver_deferred", "target_slice": None,
             "rationale": "real gap; needs E1b"},
        ],
    )
    stats = mod.apply(c, y, write=True)
    assert stats["n_waiver_added"] == 2
    doc = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert list(doc.keys()) == ["drivers", "dag_alias", "waivers"]
    assert doc["waivers"]["fx_id"] == {"category": "silver_only", "note": "FX cross"}
    assert doc["waivers"]["gap_id"] == {"category": "deferred", "note": "real gap"}


def test_idempotent_byte_identical(tmp_path):
    """Running --apply twice yields byte-identical text; the second run adds nothing."""
    y = _write_yaml(tmp_path)
    c = _write_curation(
        tmp_path,
        [
            {"id": "new_id", "action": "alias", "target_slice": "target_slice", "rationale": "r"},
            {"id": "fx_id", "action": "waiver_silver_only", "target_slice": None, "rationale": "fx"},
        ],
    )
    mod.apply(c, y, write=True)
    first = y.read_text(encoding="utf-8")
    stats2 = mod.apply(c, y, write=True)
    second = y.read_text(encoding="utf-8")
    assert first == second
    assert stats2["n_alias_added"] == 0
    assert stats2["n_alias_present"] == 1
    assert stats2["written"] is False


def test_already_present_alias_not_duplicated(tmp_path):
    """An id already on the target RHS is counted as present, never re-appended."""
    y = _write_yaml(tmp_path)
    c = _write_curation(
        tmp_path,
        [{"id": "existing_id", "action": "alias", "target_slice": "existing_slice", "rationale": "r"}],
    )
    stats = mod.apply(c, y, write=True)
    assert stats["n_alias_added"] == 0
    assert stats["n_alias_present"] == 1
    doc = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert doc["dag_alias"]["existing_slice"] == ["existing_id"]  # no duplicate


def test_comment_block_preserved(tmp_path):
    """The provenance comment above dag_alias survives the splice (PyYAML dump would drop it)."""
    y = _write_yaml(tmp_path)
    c = _write_curation(
        tmp_path,
        [{"id": "new_id", "action": "alias", "target_slice": "target_slice", "rationale": "r"}],
    )
    mod.apply(c, y, write=True)
    out = y.read_text(encoding="utf-8")
    assert "# synthetic header comment (must survive the splice)" in out
    assert "PROVENANCE LAW" in out


def test_missing_target_slice_aborts(tmp_path):
    """An alias whose target_slice is not a drivers: key aborts with ApplyError and writes nothing."""
    y = _write_yaml(tmp_path)
    before = y.read_text(encoding="utf-8")
    c = _write_curation(
        tmp_path,
        [{"id": "x", "action": "alias", "target_slice": "no_such_slice", "rationale": "r"}],
    )
    try:
        mod.apply(c, y, write=True)
        assert False, "expected ApplyError"
    except mod.ApplyError as exc:
        assert "no_such_slice" in str(exc)
    assert y.read_text(encoding="utf-8") == before  # file untouched


def test_duplicate_across_slices_aborts(tmp_path):
    """The same id aliased onto two DISTINCT slices is a hard cross-ownership error (file untouched)."""
    y = _write_yaml(tmp_path)
    before = y.read_text(encoding="utf-8")
    c = _write_curation(
        tmp_path,
        [
            {"id": "dup", "action": "alias", "target_slice": "target_slice", "rationale": "r"},
            {"id": "dup", "action": "alias", "target_slice": "other_slice", "rationale": "r"},
        ],
    )
    try:
        mod.apply(c, y, write=True)
        assert False, "expected ApplyError"
    except mod.ApplyError as exc:
        assert "dup" in str(exc)
    assert y.read_text(encoding="utf-8") == before


def test_self_alias_not_flagged_as_duplicate(tmp_path):
    """A RHS entry equal to its own slice name (benign self-alias) is NOT a cross-ownership error."""
    # existing_slice already has [existing_id]; add a self-alias existing_slice -> existing_slice.
    y = _write_yaml(tmp_path)
    c = _write_curation(
        tmp_path,
        [{"id": "existing_slice", "action": "alias", "target_slice": "existing_slice", "rationale": "r"}],
    )
    stats = mod.apply(c, y, write=True)  # must not raise
    assert stats["n_alias_added"] == 1
    doc = yaml.safe_load(y.read_text(encoding="utf-8"))
    assert doc["dag_alias"]["existing_slice"] == ["existing_id", "existing_slice"]


def test_dry_run_writes_nothing(tmp_path):
    """--dry-run (write=False) computes stats but leaves the file byte-identical."""
    y = _write_yaml(tmp_path)
    before = y.read_text(encoding="utf-8")
    c = _write_curation(
        tmp_path,
        [{"id": "new_id", "action": "alias", "target_slice": "target_slice", "rationale": "r"}],
    )
    stats = mod.apply(c, y, write=False)
    assert stats["n_alias_added"] == 1
    assert stats["written"] is False
    assert y.read_text(encoding="utf-8") == before


def test_short_note_trims_and_ascii(tmp_path):
    """_short_note takes the lead clause, strips non-ASCII, and caps length."""
    assert mod._short_note("Lead clause; trailing detail") == "Lead clause"
    assert mod._short_note("El Nino accent café test") == "El Nino accent caf test"
    long = "w" * 200
    assert len(mod._short_note(long)) <= 80
    assert mod._short_note(long).endswith("...")
