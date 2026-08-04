"""D-PR-6 -- the declared-unserved fence: its derivation, its disaster floor, and the unfenced-leg lint.

WHY THIS FILE EXISTS. Twice in two days a mapped leg pointed at a vendor table that carries no series for
that contract, and both times the whole estate went red: gate rev 11's first Branch-A fire (2026-08-03) red
THREE unrelated families on six `cftc_cot.yaml` `not_covered:` slugs the D1 context lane had just made live,
and the second fire (2026-08-04) found the hand-mirrored fence short by three more. `contract_check` is a
GLOBAL check -- `check_commodity_slug_vocabulary` iterates every mapped leg in the estate and returns one
flat error list (`contract_check.py:174-209`), so one forgotten venue reds every family that runs the gate.
The fence stops the false drift; THIS lint stops the next forgotten venue from ever reaching the gate.

SCOPE SHIPPED: the STATIC config surface only -- the causal DAGs (`configs/graphrag/causal/*.yaml`) x
`configs/graphrag/numbers/cascade_map.yaml` x `configs/sources/cftc_cot.yaml`. That is the full leg
enumeration, not a reduced proxy: `contract_check._mapped_legs()` resolves each leg's scope with the EXACT
production helpers (`map_row`/`_scope`/`_region_row`, docstring at `contract_check.py:114-116`) and every
one of those is a config read -- no pg, no Athena, no AWS, measured 31 mapped cot legs offline on
2026-08-04. What is NOT here, and cannot be: the ROW-EXISTENCE half ("a slug declared COVERED actually has
rows"). That is `DISTINCT leviathan_slug` on the pg mirror and it already has an owner -- C002's live run,
which is what turned `frozen_orange_juice`'s unverified `oi_approx: "verify"` into a measured absence.

VENUE: a pytest, deliberately -- not one of the 10 lints in `_run_config_check`. A `config_check` error is
unattributable to a table, so under D-PR-5 it defaults RED estate-wide; putting this detector there would
re-create the exact blast radius it exists to kill (D-PR-29). Pre-merge is the right side of the fence: a
forgotten venue fails the suite before the image is built, instead of reddening production at 18:00Z.
"""
from __future__ import annotations

import logging

import pytest
from leviathan.graphrag.numbers import cascade as casc
from leviathan.graphrag.numbers import contract_check as cch

COT_YAML_REL = "configs/sources/cftc_cot.yaml"


@pytest.fixture(autouse=True)
def _clean_fence_cache():
    """The fence is `functools.lru_cache`d for the process, so a test that points it at a missing file
    would poison every later test (in any module) with the fallback. Clear on both sides."""
    casc.cot_unserved_slugs.cache_clear()
    yield
    casc.cot_unserved_slugs.cache_clear()


def _cot_yaml_text() -> str:
    return casc._cot_yaml_path().read_text(encoding="utf-8")


def _scan_covered(text: str) -> set[str]:
    """The `target_contracts:` block's KEYS -- the slugs cftc_cot.yaml claims CFTC covers. A test-local
    parser on purpose: the file does not safe_load (its CSV `schema:` block carries `Key:{type: int,...}`
    flow tokens the scanner rejects), and re-using cascade's own scanner would make the assertion vacuous
    if that scanner were the thing that broke."""
    keys, in_block = set(), False
    for line in text.splitlines():
        if line.startswith("target_contracts:"):
            in_block = True
            continue
        if not in_block:
            continue
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            break                                        # the next top-level key ends the block
        head = line.strip().split(":", 1)
        if len(head) == 2 and head[0]:
            keys.add(head[0].strip())
    return keys


def _legs_on(table: str) -> list[tuple]:
    """(contract, driver_id, commodity, country) for every mapped leg whose cascade_map row reads `table`."""
    return [(contract, did, commodity, country)
            for contract, did, row, _node, commodity, country in cch._mapped_legs()
            if (row or {}).get("table") == table]


def _orphan_cot_legs(covered: set[str], unserved: set[str]) -> list[tuple]:
    """Mapped cot legs whose slug is in NEITHER coverage class -- the lint's whole judgement, factored
    out so the negative test below can prove it actually fires."""
    return sorted({(c, did, slug) for c, did, slug, _country in _legs_on("silver_cot")
                   if slug not in covered and slug not in unserved})


# ---------------------------------------------------------------------------
# The headline lint: a D1-style map addition with a forgotten venue fails HERE, not in production.
# ---------------------------------------------------------------------------
def test_every_mapped_cot_leg_is_covered_or_declared_unserved():
    """Every contract that maps a leg through a `silver_cot` cascade_map ref must be EITHER a
    `target_contracts:` key (CFTC covers it -- the leg is expected to return rows) OR in the derived
    unserved fence (`not_covered:` -- the leg SKIPs at `_scope`). A slug in neither is the 2026-08-03
    class exactly: a live leg against a table that will never hold a row for it, reported by C002 as
    estate-wide drift. Measured 2026-08-04: 31 mapped cot legs, 12 covered + 17 fenced + 2 alias
    duplicates (corn->corn_cbot, soybeans->soybeans_cbot), ZERO unclassified."""
    text = _cot_yaml_text()
    covered, unserved = _scan_covered(text), set(casc.cot_unserved_slugs())
    assert covered, f"{COT_YAML_REL}: target_contracts block not found -- the coverage claim vanished"
    assert unserved, f"{COT_YAML_REL}: not_covered block not found -- the fence lost its authority"

    legs = _legs_on("silver_cot")
    assert len(legs) >= 25, (f"only {len(legs)} mapped cot legs enumerated (31 on 2026-08-04) -- the "
                             f"enumeration collapsed, so this lint would pass vacuously")
    orphans = _orphan_cot_legs(covered, unserved)
    assert not orphans, (
        "cot legs mapped against a contract cftc_cot.yaml neither covers nor declares unserved:\n"
        + "\n".join(f"  {c}/{did} -> {slug!r}" for c, did, slug in orphans)
        + f"\nAdd each slug to {COT_YAML_REL} `target_contracts:` (only after a backfill VERIFIED it "
          f"lands rows -- frozen_orange_juice was claimed-covered on an unverified oi_approx and never "
          f"landed one) or to `not_covered:` (the fence, which makes the leg SKIP honestly at _scope).")


def test_the_lint_fires_on_a_forgotten_venue(monkeypatch):
    """The negative half -- without it, the green above proves only that nothing was enumerated. Replay
    the 2026-08-03 shape: a new cot leg mapped for a contract the coverage config never classified (here
    a fictional MATIF venue), and assert the lint names it. Legs are injected at `_mapped_legs`, the same
    seam `contract_check`'s own unit tests use."""
    legs = [("dutch_barley_matif", "cot_mm_positioning", {"table": "silver_cot"}, None,
             "dutch_barley_matif", None),
            ("corn", "cot_mm_positioning", {"table": "silver_cot"}, None, "corn_cbot", None)]
    monkeypatch.setattr(cch, "_mapped_legs", lambda: legs)
    covered, unserved = _scan_covered(_cot_yaml_text()), set(casc.cot_unserved_slugs())
    assert _orphan_cot_legs(covered, unserved) == [
        ("dutch_barley_matif", "cot_mm_positioning", "dutch_barley_matif")]


def test_cot_yaml_never_claims_a_slug_both_covered_and_unserved():
    """A slug in both blocks is a config that contradicts itself, and the contradiction is not
    symmetric: the fence wins at `_scope`, so the leg goes dark and C002 stops reporting drift on a
    contract the same file says is covered -- a suppressed real defect, the failure mode over-fencing
    is feared for."""
    text = _cot_yaml_text()
    both = sorted(_scan_covered(text) & set(casc.cot_unserved_slugs()))
    assert not both, f"{COT_YAML_REL} claims these slugs are both covered and not_covered: {both}"


def test_every_cot_fence_slug_is_a_real_contract():
    """A fence member that is not a loaded causal contract can never match a leg, so it fences nothing
    -- a typo here fails OPEN and silently, and the estate only learns at the next gate fire. All 18
    members are loaded contracts as of 2026-08-04."""
    from leviathan.graphrag.numbers import cascade_census as cc

    contracts = set(cc._contract_index())
    assert contracts, "no causal contracts loaded -- the assertion below would be vacuous"
    ghosts = sorted(s for s in casc.cot_unserved_slugs() if s not in contracts)
    assert not ghosts, (f"{COT_YAML_REL} not_covered lists slugs that are not loaded contracts (they "
                        f"fence nothing): {ghosts}")


# ---------------------------------------------------------------------------
# The fence reaches the runtime (bookkeeping that never fires is not a fence).
# ---------------------------------------------------------------------------
def test_declared_unserved_cot_legs_skip_and_covered_ones_do_not():
    """Both directions, because both have cost a fire: a fenced leg must resolve to SKIP_NODE at
    `_scope` (it declines honestly instead of reading zero rows and reporting drift), and a COVERED
    contract's cot leg must still scope normally -- an over-broad fence would turn a live leg dark,
    which is the same silence as the bug, only quieter."""
    unserved = set(casc.cot_unserved_slugs())
    covered = _scan_covered(_cot_yaml_text())
    fenced = [(c, did, slug, country) for c, did, slug, country in _legs_on("silver_cot")
              if slug in unserved]
    live = [(c, did, slug, country) for c, did, slug, country in _legs_on("silver_cot")
            if slug in covered]
    assert fenced and live, f"expected both fenced and covered cot legs; got {len(fenced)}/{len(live)}"
    assert all(country is casc.SKIP_NODE for _c, _d, _s, country in fenced), \
        [(c, did, s) for c, did, s, country in fenced if country is not casc.SKIP_NODE]
    assert all(country is not casc.SKIP_NODE for _c, _d, _s, country in live), \
        [(c, did, s) for c, did, s, country in live if country is casc.SKIP_NODE]


def test_psd_fence_members_are_real_contracts_and_skip_at_scope():
    """The PSD half, and the limit of what a static lint can say about it. `PSD_UNSERVED_SLUGS`
    (`cascade.py:337`) is NOT derived from a config and must not become derived: its truth is the TABLE
    (a `DISTINCT leviathan_slug` probe, C002-verified 2026-07-15), and minting a yaml for it would
    create a file that can drift from `silver_psd` silently -- the exact failure the fence prevents
    (revised D-PR-6). So the coverage half of psd is NOT lintable here; what IS lintable is that every
    fence member is a real contract and actually SKIPs. The row-existence half stays in C002's live run."""
    from leviathan.graphrag.numbers import cascade_census as cc

    contracts = set(cc._contract_index())
    ghosts = sorted(s for s in casc.PSD_UNSERVED_SLUGS if s not in contracts)
    assert not ghosts, f"PSD_UNSERVED_SLUGS members that are not loaded contracts: {ghosts}"
    fenced = [(c, did, slug, country) for c, did, slug, country in _legs_on("silver_psd")
              if slug in casc.PSD_UNSERVED_SLUGS]
    assert fenced, "no mapped psd leg hits the fence -- assertion below would be vacuous"
    assert all(country is casc.SKIP_NODE for _c, _d, _s, country in fenced), \
        [(c, did, s) for c, did, s, country in fenced if country is not casc.SKIP_NODE]


# ---------------------------------------------------------------------------
# The derivation itself: the scanner, the cache, and the disaster floor.
# ---------------------------------------------------------------------------
def test_scan_not_covered_reads_items_through_comments_and_stops_at_the_next_key():
    """The block's real shape: `- slug  # rationale` items, WRAPPED comment lines that continue a
    rationale (cftc_cot.yaml:110-112 does exactly this for frozen_orange_juice) and must not end the
    block, and a following top-level key that must."""
    doc = ("not_covered:\n"
           "  - alpha_matif        # Euronext\n"
           "  #   a wrapped rationale line, still inside the block\n"
           "  - beta_dce\n"
           "\n"
           "ml_priority: P8\n"
           "other_list:\n"
           "  - not_a_fence_slug\n")
    assert casc._scan_not_covered(doc) == frozenset({"alpha_matif", "beta_dce"})


def test_fence_falls_back_to_the_frozen_set_when_the_yaml_is_unreadable(monkeypatch, caplog, tmp_path):
    """An image without the config must NOT turn the fence empty. An empty fence un-SKIPs every cot leg
    at once and hands the gate 17 fresh 'slug not in DISTINCT' errors -- the estate-wide red this whole
    item exists to end -- so the read fails OPEN to the last measured set, loudly."""
    monkeypatch.setattr(casc, "_cot_yaml_path", lambda: tmp_path / "no_such_cftc_cot.yaml")
    casc.cot_unserved_slugs.cache_clear()
    with caplog.at_level(logging.WARNING, logger="leviathan.graphrag.numbers.cascade"):
        got = casc.cot_unserved_slugs()
    assert got == casc._COT_NOT_COVERED_FALLBACK
    assert any("FALLING BACK" in r.getMessage() for r in caplog.records), \
        "the fallback must announce itself -- a silent stale fence is how the transcription drifted"


def test_fence_falls_back_when_the_block_is_present_but_empty(monkeypatch, caplog, tmp_path):
    """A truncated/mangled config reads as 'no fenced venues', which is indistinguishable from a real
    empty declaration and far more likely. Treat an empty scan exactly like an unreadable file."""
    p = tmp_path / "cftc_cot.yaml"
    p.write_text("source: cftc_cot\nnot_covered:\nml_priority: P8\n", encoding="utf-8")
    monkeypatch.setattr(casc, "_cot_yaml_path", lambda: p)
    casc.cot_unserved_slugs.cache_clear()
    with caplog.at_level(logging.WARNING, logger="leviathan.graphrag.numbers.cascade"):
        assert casc.cot_unserved_slugs() == casc._COT_NOT_COVERED_FALLBACK
    assert any("FALLING BACK" in r.getMessage() for r in caplog.records)


def test_fence_reads_the_yaml_once_per_process():
    """`load_map`'s idiom: the read is lazy at first use and cached, so the serving hot path pays one
    file read per process and the gate cannot be slowed by re-scanning per leg."""
    reads = {"n": 0}
    real = casc._cot_yaml_path

    def counting():
        reads["n"] += 1
        return real()

    casc.cot_unserved_slugs.cache_clear()
    original, casc._cot_yaml_path = casc._cot_yaml_path, counting
    try:
        first = casc.cot_unserved_slugs()
        for _ in range(5):
            casc.cot_unserved_slugs()
        assert casc.COT_UNSERVED_SLUGS is first          # the module attribute reads the same cache
    finally:
        casc._cot_yaml_path = original
    assert reads["n"] == 1, f"fence re-read the yaml {reads['n']} times"


def test_the_disaster_floor_still_equals_the_yaml():
    """`_COT_NOT_COVERED_FALLBACK` is a lint target, not a second source of truth: it is only ever used
    when the yaml is unreachable, so it can rot invisibly. If this fails, the yaml was edited -- copy
    the new set into the fallback (that is the whole maintenance burden the derivation left behind)."""
    assert set(casc._COT_NOT_COVERED_FALLBACK) == set(casc.cot_unserved_slugs()), \
        "cftc_cot.yaml not_covered moved; update cascade._COT_NOT_COVERED_FALLBACK to match"
