"""D-10 SITTING 9 -- THE SPLIT (owner ruling 2026-09-07 ~15:50Z; built 2026-09-09).

THE PROBLEM THE SPLIT SOLVES. Two curated nodes -- rough_rice_cbot/buffer_stock_release and
soybean_oil_dce/buffer_stock_release -- each carried TWO jobs on one row and could do neither
honestly. Each is a RELEASE-FLOW policy event (sign '-': a government auction ADDS supply and
pressures price) that was bound to a CARRY-IN LEVEL series a release DRAINS. That is the
sign-identity law's exact violation, and on soyoil it came with the D-10 wrong-geography class on
top: a China reserve claim riding the PRIMARY-ruled `beginning_stock` fired with BRAZIL's soyoil
carry-in (measured FIRES, 50 marketing years, in the 2026-08-26 census artifact). Sitting 8
(2026-09-07) could only make the rice half decline honestly, because fixing the geography alone
would have shipped a correctly-located inversion.

THE RULING, and it is a SPLIT rather than a re-type -- the palm precedent deliberately NOT extended
(palm's `China_reserve_release` text was two-sided so a sign two-edit was honest; rice's and
soyoil's are one-sided release language and re-typing them would have put words in a curator's
mouth):

  (1) KEEP the release node whole -- type, sign '-', mechanism, evidence_query, region -- and DETACH
      it from the level by naming its own unserved instrument: `silver_ref: buffer_stock_release` at
      `silver_status: planned`. That name is the register's DECLARED DEAD REF (no carrier, pinned in
      tests/unit/test_cascade.py's negative roster), because no source serves a release VOLUME. An
      unmapped ref is not a leg, so the node leaves CENSUS SCOPE ENTIRELY rather than becoming a
      decline: it declines on numbers by construction and narrates from receipts. A planned node is
      a row, never an absence.

  (2) ADD the LEVEL beside it as sign-0 reserve-level nodes with RESOLVED geography on the
      region-ruled `beginning_stock_region` -- one China node for soyoil, and for rice two per-origin
      CHILDREN (India + Thailand), the sunflower ukraine_/russia_ split precedent of 2026-08-27. They
      join the China_state_reserves sign-0 family (corn, corn_cbot, campinas, cotton, soybeans_cbot,
      soybeans_no_1_dce, soybeans_no_2_dce) field for field. Sign '0' is what licenses quantifying a
      level whose direction depends on which way the reserve is moving, and the estate's own measured
      justification for it stands: the engine never computes off the curated sign (it reaches only
      the prompt drivers table, a +/- coherence counter that ignores '0', and a conflict detector
      needing both '+' and '-').

WHAT THIS DECK PINS. The overlay halves of both DAGs are GITIGNORED and reach prod only inside the
worker context tar, so a lost or un-shipped overlay reds HERE rather than three weeks later in an
eval -- the same reason sitting 8's leg (d) exists. Beyond the node shapes: the detach is REAL (the
ref has no map row), the new tokens RESOLVE on the live region_map, the two new driver ids are
accounted for in driver_slices, and the census arithmetic prediction #14 rests on is reproduced from
the production helpers rather than remembered.

WHAT IT DOES NOT PIN, said out loud. Whether silver_psd carries beginning_stocks_mt x
soybean_oil_dce x CHINA. That cell was never probed -- the build seat has no pg mirror -- while the
rice pair's cells were value-proved on Athena at the 2026-09-04 vintage (India 67 MY 1960-2026,
Thailand 67 MY, all non-null). If the soyoil cell is empty the leg reads DARK-WITH-REASON, which is
the ONE verdict the rolling-baseline diff reds on, estate-wide. The read-only census preflight in
scripts/ops/psd_clock_runbook.py is what catches that, and prediction #14 names it as the sitting's
one unmeasured cell.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from leviathan.graphrag.numbers import cascade as cq
from leviathan.graphrag.numbers import cascade_census as ccz

# The two boards' release nodes and the three level nodes the split mints.
_RELEASE = (("rough_rice_cbot", "India/Thailand"), ("soybean_oil_dce", "China"))
_LEVEL = (("rough_rice_cbot", "India_state_reserves", "India"),
          ("rough_rice_cbot", "Thailand_state_reserves", "Thailand"),
          ("soybean_oil_dce", "China_state_reserves", "China"))
# The family the level nodes join, read live rather than transcribed (a family that drifts must drag
# its new members with it or this deck names the drift).
_FAMILY = ("corn_cbot", "China_state_reserves")


def _node(contract, ref, region):
    return SimpleNamespace(contract=contract, id=ref, prior={"silver_ref": ref, "region": region},
                           evidence=[])


def _dag(contract, driver):
    d = ccz._driver(contract, driver)
    assert d is not None, f"{contract}/{driver} is not in the DAG -- overlay lost?"
    return d


def _require_overlay():
    if not ccz._contract_index():
        pytest.skip("no private causal DAGs in this tree")


# ── (1) the release nodes: kept whole, detached from the level ───────────────────────────────────
def test_the_release_nodes_keep_their_curation_and_leave_census_scope():
    """The DETACH half. Every curated field the ruling said to keep is asserted present and
    unchanged in KIND (type/sign/region), the mechanism and evidence_query are asserted to still
    NAME the release mechanism rather than having been quietly rewritten into a level claim, and the
    binding is the planned unserved instrument.

    THE LOAD-BEARING ASSERTION IS THE LAST ONE. `map_row('buffer_stock_release') is None` is what
    makes this a detach rather than a relabel: cascade_census enumerates a leg for every driver whose
    ref MAPS and never consults silver_status (cascade_census.py census(): `row = map_row(...)`, `if
    row is None: continue`), and the runtime engine reads silver_status no more than the census does
    (cascade._select_nodes -> _silver_ref -> map_row). So `silver_status: planned` alone would have
    changed NOTHING about what these two legs quantify -- they would have gone on citing US rice
    carry-in and Brazilian soyoil carry-in under India and China labels while wearing a label that
    says they do not. The status is the DECLARATION; the unmapped ref is the MECHANISM."""
    _require_overlay()
    assert cq.map_row("buffer_stock_release") is None, \
        "the release ref acquired a map row -- a release FLOW would quantify off a carry-in LEVEL"
    for contract, region in _RELEASE:
        d = _dag(contract, "buffer_stock_release")
        assert d.type == "policy_event", contract
        assert d.sign == "-", contract                      # the release direction, NOT re-typed
        assert d.region == region, contract                 # geography untouched by the split
        assert d.silver_ref == "buffer_stock_release", contract
        assert d.silver_status == "planned", contract
        # the curated text still describes a RELEASE of stock, not the level of it
        text = f"{d.mechanism} {d.evidence_query}".lower()
        assert "release" in text or "auction" in text, contract
        assert d.evidence_query.strip(), contract           # receipts still have a query to fetch


def test_the_rice_release_node_still_names_both_origins_it_declines_to_pick_between():
    """The compound token STAYS on the release node on purpose -- it is the honest geography of a
    two-origin policy claim, and it is why the split had to mint per-origin children rather than
    re-token this node. The resolver's verdict on that compound is pinned as a live fact (it is what
    sitting 8's decline rested on), and the token stays listed `unresolved` in the region_map because
    a driver on this board still carries it: the Peru/Chile removal precedent applies to a token NO
    driver claims any more, which is not this one."""
    _require_overlay()
    assert _dag("rough_rice_cbot", "buffer_stock_release").region == "India/Thailand"
    res = cq.load_map()["beginning_stock_region"]
    assert cq._scope_ex(_node("rough_rice_cbot", "beginning_stock_region", "India/Thailand"), res) \
        == ("rough_rice_cbot", cq.SKIP_NODE, "region-token-unresolved")
    assert "India/Thailand" in set((cq.load_region_map() or {}).get("unresolved") or [])


# ── (2) the level nodes: the sign-0 family, at a geography that resolves ─────────────────────────
def test_the_new_reserve_level_nodes_mirror_the_sign0_family_field_for_field():
    """Read the family member LIVE and require the new nodes to match it on every field the ruling
    named (parents / edge_type / lag / target_metric / type / sign / silver_ref / silver_status).
    Transcribing the family's values as literals here would let the family move without the children,
    which is the drift this shape exists to prevent."""
    _require_overlay()
    fam = _dag(*_FAMILY)
    assert (fam.type, fam.sign, fam.silver_ref, fam.silver_status) == \
        ("policy_event", "0", "beginning_stock_region", "available")   # the family itself, unmoved
    for contract, driver, _region in _LEVEL:
        d = _dag(contract, driver)
        for field in ("type", "sign", "lag", "edge_type", "target_metric",
                      "silver_ref", "silver_status", "parents"):
            assert getattr(d, field) == getattr(fam, field), f"{contract}/{driver}.{field}"
        assert d.parents == [], f"{contract}/{driver} acquired a parent the family does not have"
        assert d.blurb and d.evidence_query.strip(), f"{contract}/{driver}"


def test_the_level_nodes_text_is_two_sided_which_is_what_licenses_sign_zero():
    """A sign-0 node on a LEVEL is only honest while its own text says the level moves both ways --
    that is the whole difference between this split and the one-sided release nodes it was carved
    from, and it is the ground the palm two-edit stood on. Asserted on the mechanism, because that is
    the field a future curator would edit."""
    _require_overlay()
    bearish = ("release", "auction", "sales", "sale")
    bullish = ("accumulat", "procurement", "rebuild", "purchase", "pledg", "absorb")
    for contract, driver, _region in _LEVEL:
        m = _dag(contract, driver).mechanism.lower()
        assert any(t in m for t in bearish), f"{contract}/{driver}: no release side"
        assert any(t in m for t in bullish), f"{contract}/{driver}: no accumulation side"


def test_every_new_level_leg_resolves_to_the_country_its_own_token_names():
    """THE POINT OF THE WHOLE D-10 LANE, in three lines: on the region-ruled row the driver's OWN
    token scopes the read. Run through the production resolver against the REAL region_map -- not a
    fixture -- so a region_map edit that dropped India, Thailand or China would red here."""
    _require_overlay()
    res = cq.load_map()["beginning_stock_region"]
    assert res.get("country_rule") == "region"
    for contract, driver, region in _LEVEL:
        d = _dag(contract, driver)
        assert d.region == region, f"{contract}/{driver}"
        assert cq._scope_ex(_node(contract, d.silver_ref, d.region), res) == (contract, region, None), \
            f"{contract}/{driver}"
        assert ccz.driver_fireable(contract, driver), f"{contract}/{driver}"


# ── (3) the evidence layer: every new id accounted for ───────────────────────────────────────────
def test_the_new_driver_ids_are_accounted_for_in_driver_slices():
    """check_driver_slices leg (a) fails the build on a DAG id that neither resolves to a slice nor
    carries a waiver -- the lint that went red on 2026-09-08 when a node landed without its waiver.

    THE TWO RICE IDS ARE WAIVED `silver_only` RATHER THAN ALIASED, and the choice is the finding, not
    an omission. The obvious alias target was the `buffer_stock_release` slice (buffer stock / food
    corporation of india / open market sale scheme) -- topically exact for India. It was REFUSED
    because the release node that owns those receipts by IDENTITY is still on the SAME BOARD: routing
    the level nodes onto that slice would hand one prop population to two nodes of one subgraph and
    give the narrator the same receipt twice. The split's own shape is the answer -- the release node
    reads the text, the level nodes read the number.

    soyoil's `China_state_reserves` needed NO driver_slices edit at all: the id is already owned by
    the `china_reserve_auctions` dag_alias row (it is the family's own spelling on seven other
    boards), so it resolves the day the node lands. That is a fact worth pinning, because a future
    reader looking for a third waiver would otherwise read its absence as the 09-08 defect."""
    _require_overlay()
    from leviathan.graphrag import evidence as ev
    waivers = (ev._driver_raw().get("waivers") or {})
    backed = ev.backed_dag_ids()
    for did in ("India_state_reserves", "Thailand_state_reserves"):
        assert did in waivers, did
        assert waivers[did].get("category") == "silver_only", did
        assert did not in backed, f"{did} is both waived and slice-backed -- pick one"
    assert "China_state_reserves" in backed, "the family id lost its china_reserve_auctions alias"
    assert ev.check_driver_slices() == []


def test_the_tracked_manifest_mirrors_the_waiver_bump():
    """driver_slices.yaml is gitignored with an empty git log, so the two new waivers are invisible to
    review except through the tracked mirror -- and the mirror is the only guard that fires BEFORE
    compute is spent. counts.waivers 107 -> 109 and the file digest moved; no slice's term hash moved,
    which is the executable statement that this sitting changed NO routing and re-populated NO slice."""
    from leviathan.graphrag import driver_slices_manifest as dsm
    live, mirror = dsm.build(), dsm.load()
    assert mirror is not None, "the tracked manifest is missing from this tree"
    assert live["counts"]["waivers"] == 109
    assert mirror["counts"] == live["counts"]
    assert mirror["file_sha256"] == live["file_sha256"]
    assert mirror["slices"] == live["slices"]                 # no term hash moved


# ── (4) the census arithmetic prediction #14 rests on ────────────────────────────────────────────
def test_census_prediction_14_leg_arithmetic_is_reproducible_from_the_configs():
    """PREDICTION #14 = 792 legs = 544 FIRES / 248 DECLINES / 0 dark / 0 probe errors, DERIVED here
    rather than remembered. This replays the census's own leg enumeration -- map_row for scope
    membership, then _scope_ex for the verdict, plus cascade_census._WAIVERS, exactly as census()
    orders them -- over the live 36 DAGs. It is the pg-free HALF of the census: the resolved count is
    the FIRES prediction and holds only while the mirror carries each resolved (table, metric,
    country), which is the preflight's job, not this deck's.

    The numbers are stated absolutely so a drift names itself: 1,270 driver instances / 405 distinct
    ids / 792 mapped legs / 9 waived / 239 scope-declines / 248 declines / 544 resolved. The pre-split
    overlay reproduced #13 exactly on the same predicate (1,267 / 403 / 791 / 9 / 240 / 249 / 542),
    which is what licenses quoting this delta as arithmetic rather than as an estimate."""
    _require_overlay()
    idx = ccz._contract_index()
    assert len(idx) == 36
    instances = ids = legs = waived = 0
    seen_ids, scope_declines, resolved = set(), {}, []
    for contract, c in sorted(idx.items()):
        for d in c.drivers:
            instances += 1
            seen_ids.add(d.id)
            row = cq.map_row(d.silver_ref)
            if row is None:
                continue                                       # unmapped -> out of census scope
            legs += 1
            if ccz._WAIVERS.get((contract, d.id)):
                waived += 1
                continue                                       # census() waives BEFORE it scopes
            n = ccz._LegNode(contract, d.id, d.silver_ref, d.region)
            _commodity, country, reason = cq._scope_ex(n, row)
            if country is cq.SKIP_NODE:
                scope_declines[reason] = scope_declines.get(reason, 0) + 1
            else:
                resolved.append((contract, d.id))
    ids = len(seen_ids)
    assert (instances, ids, legs) == (1270, 405, 792)
    assert waived == 9
    assert sum(scope_declines.values()) == 239
    assert waived + sum(scope_declines.values()) == 248         # the DECLINES prediction
    assert len(resolved) == 544                                 # the FIRES prediction, pg permitting
    # region-token-unresolved returns to 189: sitting 8 pushed it to 190 with the rice compound, and
    # the split takes that leg out of scope rather than leaving it to decline.
    assert scope_declines["region-token-unresolved"] == 189
    # the three new legs are IN the resolved set and the two detached ones are in NO set at all
    for contract, driver, _region in _LEVEL:
        assert (contract, driver) in resolved
    for contract, _region in _RELEASE:
        assert (contract, "buffer_stock_release") not in resolved
        assert not ccz.driver_fireable(contract, "buffer_stock_release")


def test_the_runbook_carries_prediction_14_above_13():
    """The prediction is an OPERATOR artifact, not a commit-message claim: the preflight banner is
    read against it before the advance runs. Pinned by address and by ORDER -- #14 must sit above #13
    the way #13 sits above #12, so the operator reads the current one first."""
    import pathlib
    text = pathlib.Path("scripts/ops/psd_clock_runbook.py").read_text(encoding="utf-8")
    i14, i13 = text.find("CENSUS PREDICTION #14"), text.find("CENSUS PREDICTION #13")
    assert i14 != -1 and i13 != -1 and i14 < i13
    for token in ("792 legs", "544 FIRES", "248 DECLINES", "India_state_reserves",
                  "Thailand_state_reserves", "soybean_oil_dce/China_state_reserves"):
        assert token in text, token


# ── (5) the lints the sitting is required to leave green ─────────────────────────────────────────
def test_the_region_map_and_cascade_map_lints_stay_green_over_the_split():
    """The two config_check legs this sitting can actually break: the region_map census (every token
    on a region-ruled ref resolves or is listed unresolved -- three new tokens landed) and the
    cascade_map lint (no row moved, and the pin proves the split needed none)."""
    _require_overlay()
    from leviathan.graphrag import config_check as cc
    from leviathan.graphrag.numbers.registry import load_registry
    assert cc._check_region_map(load_registry()) == []
    assert cc.check_cascade_map() == []
