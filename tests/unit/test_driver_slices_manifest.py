"""G2 / D-EI-1 — the tracked manifest mirror of the untracked driver-slice vocabulary. Hermetic, synthetic.

`configs/graphrag/driver_slices.yaml` is ignored whole-directory by `.gitignore:49` and its `git log` is
EMPTY, so a term edit re-routes populations across the driver layer with no reviewable diff anywhere (class
C1: the cerrado narrowing took `coffee_rust_crop` 505 props -> 20). The ratified fix is a mirror, not the
file: per-slice metadata plus the sha256 of each SORTED term list, and never a term, so 638 private terms
stay out of a PUBLIC repo's permanent history.

These tests use SYNTHETIC vocabularies only — never real slice content.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag import driver_slices_manifest as dsm
from leviathan.graphrag import evidence as ev

_BASE = (
    "drivers:\n"
    "  frost: {category: hazard, terms: [freeze, cold snap]}\n"
    "  tariff: {category: policy, max_props: 4000, terms: [tariff, import duty]}\n"
    "dag_alias:\n"
    "  frost: [hard_freeze]\n"
    "waivers:\n"
    "  EUR_USD: {category: silver_only, note: FX cross}\n"
)


@pytest.fixture()
def wired(tmp_path, monkeypatch):
    """A synthetic driver_slices.yaml at a tmp path; the mirror resolves BESIDE it."""
    src = tmp_path / "driver_slices.yaml"
    src.write_text(_BASE, encoding="utf-8")
    monkeypatch.setattr(ev, "_DRIVER_PATH", src)
    monkeypatch.delenv(dsm._OFF_ENV, raising=False)
    ev._reset()
    try:
        yield src
    finally:
        ev._reset()


def _rewrite(src, text):
    src.write_text(text, encoding="utf-8")
    ev._reset()


def test_mirror_discloses_metadata_and_digests_but_not_one_term(wired):
    doc = dsm.build()
    assert doc["counts"] == {"specs": 2, "dag_aliases": 1, "waivers": 1, "terms": 4}
    assert set(doc["slices"]) == {"frost", "tariff"}
    assert doc["slices"]["tariff"]["max_props"] == 4000 and doc["slices"]["tariff"]["n_terms"] == 2
    rendered = dsm.render(doc)
    for secret in ("freeze", "cold snap", "import duty"):     # the whole point of the mirror
        assert secret not in rendered
    assert "terms_sha256" in rendered and "hard_freeze" not in rendered


def test_round_trip_is_clean_and_a_term_edit_is_a_lint_failure(wired):
    dsm.write()
    assert dsm.check_manifest() == []
    _rewrite(wired, _BASE.replace("[freeze, cold snap]", "[freeze, cold snap, black frost]"))
    errs = dsm.check_manifest()
    assert any("'frost' TERM SET CHANGED" in e for e in errs)
    assert any("stales" in e and "artifact-staling bundle" in e for e in errs)
    dsm.write()
    assert dsm.check_manifest() == []


def test_term_reordering_alone_is_not_a_routing_change(wired):
    dsm.write()
    _rewrite(wired, _BASE.replace("[freeze, cold snap]", "[cold snap, freeze]"))
    errs = dsm.check_manifest()
    # the digest is over the SORTED list -- _Matcher sorts its own keys longest-first, so term ORDER is not
    # load-bearing at runtime and must not be load-bearing here. The file hash still moved, and says so.
    assert not any("TERM SET CHANGED" in e for e in errs)
    assert len(errs) == 1 and "file_sha256 moved" in errs[0] and "every per-slice term digest matched" in errs[0]


def test_added_and_removed_slices_are_both_named(wired):
    dsm.write()
    _rewrite(wired, _BASE.replace("  frost: {category: hazard, terms: [freeze, cold snap]}\n",
                                  "  heat: {category: hazard, terms: [heat wave]}\n"))
    errs = dsm.check_manifest()
    assert any("'heat' exists in the config but NOT in the mirror" in e for e in errs)
    # a DELETED slice matters more than it looks: its S3 file is never rewritten and persists forever
    assert any("'frost' is in the mirror but GONE from the config" in e for e in errs)
    assert any("persists as a census retire orphan" in e for e in errs)


def test_a_silent_max_props_change_is_caught(wired):
    dsm.write()
    _rewrite(wired, _BASE.replace("max_props: 4000", "max_props: 20000"))
    assert any("'tariff' field max_props 4000 -> 20000" in e for e in dsm.check_manifest())


def test_missing_mirror_is_a_hard_failure_that_names_the_fix(wired):
    # The question_shapes lesson (F10): a TRACKED config under a gitignored directory goes missing on any
    # fresh clone or clean-checkout image, and "the file vanished" must not read like "the feature is off".
    errs = dsm.check_manifest()
    assert len(errs) == 1 and "is MISSING" in errs[0]
    assert "git add -f" in errs[0] and "--write" in errs[0] and dsm._OFF_ENV in errs[0]


def test_explicit_env_opt_out_is_the_only_vacuous_pass(wired, monkeypatch):
    monkeypatch.setenv(dsm._OFF_ENV, "off")
    assert dsm.check_manifest() == []


def test_a_tree_with_no_private_vocab_passes_vacuously(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_DRIVER_PATH", tmp_path / "does_not_exist.yaml")
    ev._reset()
    try:
        assert dsm.check_manifest() == []                     # nothing to mirror -> nothing to lint
    finally:
        ev._reset()


def test_check_driver_slices_delegates_to_the_mirror_lint(wired, monkeypatch):
    # The lint has to live where the resolver lives, or it has no runner: there is no CI and no pre-commit,
    # and config_check is a manual CLI. check_driver_slices is what config_check registers and what the
    # maintenance Batch chain invokes ahead of every rebuild.
    from leviathan.graphrag import display as dp
    monkeypatch.setattr(dp, "all_driver_ids", lambda: frozenset())
    assert any("driver_slices manifest" in e and "is MISSING" in e for e in ev.check_driver_slices())
    dsm.write()
    assert ev.check_driver_slices() == []
