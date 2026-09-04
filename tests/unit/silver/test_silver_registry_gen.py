"""SILVER-F010: the generator is deterministic and the checked-in tree is byte-identical to a
fresh render from the R0 baseline (first-parquet inference is prohibited; the registry is derived
only from the frozen baseline artifacts). AWS-free.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_GEN = _REPO / "scripts" / "silver" / "gen_registry_from_baseline.py"
_TABLES = _REPO / "configs" / "silver" / "tables"

# ---------------------------------------------------------------------------
# THE CONTRACTS THE F010 GENERATOR DOES NOT OWN (2026-08-20, the four-family wave close).
#
# The rule this file enforces is "the checked-in tree is byte-identical to a fresh render", and it
# stays enforced for every contract the generator owns. The exceptions are ENUMERATED with a written
# removal trigger, NOT a loosened gate -- the estate's PRE_PUBLISH_FAMILIES idiom. There are two
# distinct exception classes and they are deliberately kept apart, because only one of them is a
# thing this file can decide:
#
#   * gen.HAND_AUTHORED_CONTRACTS -- HAS an R0 baseline record (so the generator can render it and
#     it appears in the drift loop below) but its checked-in contract is hand-authored and cannot
#     round-trip. Owned by the GENERATOR, which write-protects those names, and imported here rather
#     than redeclared so the two can never disagree. See that constant for the per-field reasoning.
#   * _NO_R0_BASELINE_RECORD below -- has no baseline record at all, so the generator has never
#     heard of it and it cannot drift against anything.
_NO_R0_BASELINE_RECORD = {
    # Both hand-authored against a LIVE 2026-08-20 probe of a source that post-dates the
    # 20260712_p65impl baseline capture, so there is no R0 record to render them from. REMOVAL
    # TRIGGER: first canonical publish + Glue registration, then re-capture the record
    # (run_census.census_one) and delete the name -- the equality below re-arms automatically.
    "silver_eex_freight",
    "silver_moex_agro_indices",
}


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_registry_from_baseline", _GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_is_deterministic_in_memory(gen):
    ctx = gen._build_context()
    names = sorted(p.stem for p in gen.TABLES_JSON.glob("*.json"))
    first = {n: gen._dump_yaml(gen.build_contract(n, ctx)) for n in names}
    second = {n: gen._dump_yaml(gen.build_contract(n, ctx)) for n in names}
    assert first == second


def test_checked_in_tree_matches_fresh_render(gen):
    """Regenerating produces zero diff for the checked-in contracts (the F011 idempotency gate)."""
    ctx = gen._build_context()
    names = sorted(p.stem for p in gen.TABLES_JSON.glob("*.json"))
    drift = []
    for n in names:
        rendered = gen._dump_yaml(gen.build_contract(n, ctx))
        on_disk = (_TABLES / f"{n}.yaml").read_text(encoding="utf-8")
        if rendered != on_disk:
            drift.append(n)
    # The gate, unchanged in force: every contract the generator OWNS regenerates byte-identically.
    # The generator's own HAND_AUTHORED_CONTRACTS is subtracted by name (it write-protects exactly
    # these), so a contract that leaves that set is re-gated automatically and a NEW drift is fatal.
    owned_drift = [n for n in drift if n not in gen.HAND_AUTHORED_CONTRACTS]
    assert owned_drift == [], f"registry drift; re-run the generator: {owned_drift}"
    # And the exceptions must stay real: a hand-authored contract that HAS started round-tripping is
    # owed its removal from the set, so this fails in that direction too.
    for n in gen.HAND_AUTHORED_CONTRACTS:
        if n in names:
            assert n in drift, (
                f"{n!r} now regenerates byte-identically -- drop it from "
                f"gen_registry_from_baseline.HAND_AUTHORED_CONTRACTS so the byte-identity gate "
                f"covers it again (and the generator stops write-protecting it)")


def test_generator_covers_exactly_the_45_baseline_tables(gen):
    baseline = {p.stem for p in gen.TABLES_JSON.glob("*.json")}
    on_disk = {p.stem for p in _TABLES.glob("*.yaml")}
    # A baseline record with no checked-in contract is a HOLE and stays fatal in that direction --
    # this half of the old `baseline == on_disk` equality is untouched.
    assert baseline - on_disk == set(), f"baseline record with no contract: {baseline - on_disk}"
    # The other half is now an ENUMERATED difference -- see _NO_R0_BASELINE_RECORD for the two
    # live-probe contracts and their removal trigger.
    assert on_disk - baseline == _NO_R0_BASELINE_RECORD
    # 43 R0 tables + two SYNTHETIC R0 records: the T2B gold_pattern_records ledger (T2B plan sec 1.2)
    # and silver_futures_eod (PRICE_AND_PLAYBOOKS W1.0) -- both authored from a ratified schema so the
    # generator can emit their contracts byte-stably before any AWS object exists.
    # D-EC DK-13 (2026-08-20): a THIRD synthetic R0 record, gold_board_crush -- authored from the
    # ratified board-crush schema so its contract renders before the gold producer has ever run.
    # MINAGRO (2026-08-20): a FOURTH synthetic R0 record, silver_minagro_grain_exports --
    # authored from the transform's OUTPUT_COLUMNS so its contract renders before the capture
    # producer has ever run in the cloud.
    # THE WAVE CLOSE (2026-08-20): 47 -> 50, one line per family, and the three sources of the bump
    # are DIFFERENT so they are recorded separately rather than summed:
    #   +1 silver_ams_gtr            -- a FIFTH synthetic R0 record (authored from the transform's
    #                                   OUTPUT_COLUMNS), contract hand-authored on top of it;
    #   +1 silver_moex_agro_indices  -- NO R0 record; hand-authored from a live ISS probe;
    #   +1 silver_eex_freight        -- NO R0 record; hand-authored from a live EEX probe.
    # (silver_minagro_grain_exports is the FOURTH synthetic record named in the paragraph above and
    # is already counted in the 47.)
    #   +1 gold_futures_spreads      -- GN-2 W2.3 (2026-08-22), the second gold derivation on the
    #                                   board-crush template; this pin was not moved in that commit
    #                                   (caught by the projection wave's first sweep 2026-08-25,
    #                                   together with the rebuild-gate trio and the missing DDL).
    #   +1 silver_psd_attributes     -- PROJECTION WAVE Lane 3 (2026-08-25), a SIXTH synthetic R0
    #                                   record, authored from the long transform's
    #                                   _SILVER_PSD_ATTR_COLS + its cast block. Contract GENERATED
    #                                   (not hand-authored, unlike silver_ams_gtr): every fact the
    #                                   renderer could not derive rides CURATION_OVERRIDES /
    #                                   DOMAIN / PRODUCER / TALL_VALUE_COL instead, so this name
    #                                   stays OUT of HAND_AUTHORED_CONTRACTS and the write path
    #                                   keeps owning it.
    #   +1 silver_pink_sheet_vintages -- PINK SHEET VINTAGES lane (a) (2026-09-03), a SEVENTH
    #                                   synthetic R0 record, authored from SILVER_VINTAGE_COLUMNS +
    #                                   the INV-2 cast block. Contract GENERATED (not hand-authored,
    #                                   the silver_psd_attributes disposition), so this name stays
    #                                   OUT of HAND_AUTHORED_CONTRACTS and BOTH halves of the
    #                                   byte-identity gate keep covering it. It is a SIBLING of
    #                                   silver_pink_sheet under its own root, and no numbers card is
    #                                   registered against it in that commit.
    #
    #   THE R0 RECORD ITSELF IS GITIGNORED, AND THAT IS TRUE OF ALL SEVEN. `.gitignore` excludes
    #   `reports/silver_readiness/`, and gen_registry_from_baseline derives its whole name list from
    #   that glob -- so on a CLEAN CHECKOUT `--check` sees zero contracts and the `in baseline`
    #   assertions above are unreachable, not false. This is a PRE-EXISTING property of the seam
    #   (records #1-#6 share it), stated here rather than left for a future reader to rediscover:
    #     * THE COMMITTED ARTIFACT IS THE GENERATED CONTRACT -- configs/silver/tables/<table>.yaml
    #       and its DDL render. Those ARE in git, they are what every consumer reads, and the
    #       byte-identity gate compares the generator's output against them.
    #     * THE R0 RECORD IS AN INPUT, and it rides the same way the gitignored configs/graphrag
    #       subtree does in the flip checklist: through the config mirror / image tar
    #       (scripts/ops/make_worker_context_tar.py overlays it, fingerprinted), never through the
    #       commit.
    #     * SO A GREEN `--check` HERE PROVES the generator still reproduces the committed contracts
    #       from the record on THIS disk. It does not prove a clean checkout can regenerate them,
    #       and it is not read as if it did.
    assert len(on_disk) == 53
    assert "gold_pattern_records" in on_disk
    assert "silver_futures_eod" in on_disk
    assert "gold_board_crush" in on_disk
    assert "silver_minagro_grain_exports" in baseline    # synthetic R0 record #4
    assert "silver_ams_gtr" in baseline                  # synthetic R0 record #5
    assert "silver_psd_attributes" in baseline           # synthetic R0 record #6
    assert "silver_psd_attributes" not in gen.HAND_AUTHORED_CONTRACTS
    assert "silver_pink_sheet_vintages" in baseline      # synthetic R0 record #7
    assert "silver_pink_sheet_vintages" not in gen.HAND_AUTHORED_CONTRACTS


class TestNullableOverrides:
    """PRICE_AND_PLAYBOOKS W1.0: the one column fact ``build_contract`` cannot derive.

    The default ``nullable = cn not in natural_key`` is a heuristic, and silver_futures_eod breaks it
    in BOTH directions at once: ``contract_month`` is a natural-key member that is legitimately NULL
    (the two CEPEA cash references), while instrument_kind / settle_kind / unit / source are non-null
    by contract yet sit outside the key. The flag is load-bearing -- ``pa_schema_from_contract`` turns
    it into ``pa.field(..., nullable=...)`` -- so a wrong value either fails the pyarrow encode on
    legal data or silently admits an illegal null."""

    def test_the_override_beats_the_natural_key_default(self, gen):
        ctx = gen._build_context()
        c = gen.build_contract("silver_futures_eod", ctx)
        by = {col["name"]: col for col in c["physical_columns"]}
        assert "contract_month" in c["natural_key"]
        assert by["contract_month"]["nullable"] is True      # key member, still nullable
        for cn in ("instrument_kind", "settle_kind", "unit", "source"):
            assert by[cn]["nullable"] is False, cn           # non-key, still non-null

    def test_an_unknown_override_column_fails_closed(self, gen):
        # a typo would otherwise be a silent no-op -- exactly the failure mode a nullability knob
        # must not have.
        ctx = gen._build_context()
        overrides = gen.CURATION_OVERRIDES["silver_futures_eod"]["nullable_overrides"]
        overrides["typo_col"] = True
        try:
            with pytest.raises(KeyError, match="not a declared physical column"):
                gen.build_contract("silver_futures_eod", ctx)
        finally:
            overrides.pop("typo_col")


def test_no_yaml_lacks_a_baseline_record(gen):
    # every emitted contract cites its exact source baseline record.
    import yaml
    for p in _TABLES.glob("*.yaml"):
        c = yaml.safe_load(p.read_text(encoding="utf-8"))
        src = c["provenance"]["generated_from"]
        assert (_REPO / src).exists(), src
