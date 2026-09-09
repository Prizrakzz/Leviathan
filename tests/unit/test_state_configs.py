"""The S0 config landing: the `board_read` rows are INERT, the calendar covers every card, and the
NASS reference resolves what `region_map` hands it.

STATE ENGINE DESIGN sec 2.6 (D23), sec 5.2 (D7), sitting S0. The inertness pins here ARE the proof the
design asked for: the deep golden cannot be re-derived offline without a serving run (LLM calls, out of
scope for this sitting), so the proof is taken one layer down, at `cascade.load_map` -- the serving
cascade's own runtime reader of this file -- and at the candidate census the un-defer gate uses.
"""
from __future__ import annotations

import pathlib

import yaml
from leviathan.graphrag import extract as ex
from leviathan.graphrag.numbers import cascade as casc
from leviathan.graphrag.numbers.registry import load_registry
from leviathan.graphrag.state import lint as sbl

# MEASURED at the S0 landing (2026-09-08). A red here is a curation event to re-bank deliberately.
LOAD_MAP_ROWS = 46               # unchanged by S0: the two board_read rows are invisible to load_map
BOARD_READ_REFS = ("oni_lag_climate",)   # `nass_crop_progress_ge_z` is HELD for S1: its silver
#   contract needs a `cascade_ref` back-pointer that only the registry GENERATOR may write, and
#   the card key + query loader + live probe land together there. The reason is written out in
#   full in cascade_map.yaml beside the row that was pulled back out.
# RE-PINNED 2026-09-09 (S2+S3 re-fix), and the CAUSE is D-10 SITTING 9 -- THE SPLIT (commit aa7fa7d7,
# owner ruling 2026-09-07). The two DAG files it edits are GITIGNORED (`configs/graphrag/`), so the
# sitting's tracked half landed in git while the graph itself moved on disk: these two numbers were
# measured at S0 against the pre-split graph and had been red since the split, which is a curation event
# re-banked here rather than a defect.
#
#   drivers   1,267 -> 1,270  = + rough_rice_cbot/India_state_reserves,
#                                rough_rice_cbot/Thailand_state_reserves,
#                                soybean_oil_dce/China_state_reserves
#                                (three sign-0 reserve-level nodes on `beginning_stock_region`)
#   candidates  791 -> 792    = + those three, whose ref IS live, MINUS the two `buffer_stock_release`
#                                nodes the split DETACHED from the carry-in level series (they keep
#                                their curated policy-event node at `silver_status: planned`, so they
#                                narrate from receipts and are no longer cascade candidates). +3 -2 = +1,
#                                and the arithmetic is why the candidate census moved by less than the
#                                driver census did.
DRIVER_INSTANCES = 1270          # 1,266 at HEAD + Argentina_production (decision 10) + the three above
CASCADE_CANDIDATES = 792         # sitting 9's own prediction #14, measured


def test_load_map_never_sees_a_board_read_row():
    live = casc.load_map()
    assert len(live) == LOAD_MAP_ROWS
    for ref in BOARD_READ_REFS:
        assert ref not in live
        assert casc.map_row(ref) is None, "%s reached the serving cascade" % ref


def test_the_board_sees_them_and_nothing_else_extra():
    board = sbl.board_map()
    live = casc.load_map()
    assert set(board) == set(live) | set(BOARD_READ_REFS)
    assert set(sbl.board_read_rows()) == set(BOARD_READ_REFS)
    for ref in BOARD_READ_REFS:
        assert board[ref]["deferred"] is True and board[ref]["board_read"] is True


def test_the_candidate_census_moves_only_by_the_curated_node():
    """The un-defer gate's own number. The two board_read rows add ZERO cascade candidates; the one
    driver decision 10 curated adds exactly one, and it rides a ref that was already live.

    RE-PINNED at the S2+S3 re-fix to the D-10 sitting-9 graph (see the constants above): the driver
    census is 1,270 and the candidate census 792, and the two moved by DIFFERENT amounts because the
    split both added three sign-0 reserve-level nodes on a live ref and detached two release nodes onto
    `planned`. A red here is still a curation event to re-bank deliberately -- and it will red on the
    next sitting that touches a gitignored DAG, which is the point of measuring it from the files."""
    n = 0
    total = 0
    for p in sorted((ex._CFG / "causal").glob("*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for dr in (doc.get("drivers") or []):
            total += 1
            if casc.map_row(dr.get("silver_ref")) is not None:
                n += 1
    assert total == DRIVER_INSTANCES
    assert n == CASCADE_CANDIDATES


def test_the_curated_argentina_child_reads_the_region_ruled_production_row():
    """Decision 10, corrected by measurement: `production` declares NO country_rule, so it defaults to
    `primary` and a foreign-origin supply driver on a CBOT board would read UNITED STATES production
    under an Argentina label -- the D-10 class `production_region` was born (2026-08-27) to close."""
    doc = yaml.safe_load((ex._CFG / "causal" / "soybeans_cbot.yaml").read_text(encoding="utf-8"))
    node = [d for d in doc["drivers"] if d["id"] == "Argentina_production"]
    assert len(node) == 1
    node = node[0]
    assert node["parents"] == ["El_Nino"]
    assert node["silver_ref"] == "production_region"
    assert node["sign"] == "-", "a bigger Argentine crop pressures the CBOT price"
    assert node["region"] == "Argentina"
    assert len(node["blurb"].split()) <= 15
    live = casc.load_map()
    assert live["production_region"]["country_rule"] == "region"
    assert "country_rule" not in live["production"], \
        "if `production` ever declares a country_rule, re-read this node's binding"
    entry = casc.load_region_map()["resolve"].get("Argentina")
    assert entry and entry.get("country") == "Argentina"


def test_global_state_rides_the_two_live_climate_rows_and_no_reader_consumes_it():
    live = casc.load_map()
    assert live["oni_climate"]["global_state"] is True
    assert live["iod_climate"]["global_state"] is True
    # THE SCOPE THE TEST'S NAME CLAIMS. The first landing walked `parents[2]` -- src/ ALONE -- which
    # would have missed a reader in a batch job, an ops script or the terminal's own source just as
    # completely as not looking. `global_state` is a new key on two LIVE map rows, so the honest claim
    # is estate-wide: three Python trees plus the FE, which reads served rows as JSON and could name
    # the key in TypeScript. (Widened at the S0 review; still zero hits.)
    root = pathlib.Path(ex.__file__).resolve().parents[3]
    hunted = []
    for rel, pats in (("src", ("*.py",)), ("jobs", ("*.py",)), ("scripts", ("*.py",)),
                      ("apps/terminal/src", ("*.ts", "*.tsx"))):
        d = root.joinpath(*rel.split("/"))
        if not d.is_dir():
            continue
        for pat in pats:
            hunted.extend(d.rglob(pat))
    assert len(hunted) > 400, "the widened walk found %d files -- it is not walking the estate" % len(hunted)
    readers = []
    for f in hunted:
        if "state" in f.parts and f.name == "lint.py":
            continue                                   # the lint grades the key; it does not consume it
        if "global_state" in f.read_text(encoding="utf-8", errors="ignore"):
            readers.append(str(f))
    assert readers == [], readers


def test_the_calendar_covers_every_card_the_board_can_reach_exactly_once():
    doc = sbl.load_release_calendar()
    in_sources = [t for s in doc["sources"].values() for t in s["tables"]]
    assert len(in_sources) == len(set(in_sources)), "a card with two release rules"
    unc = set(doc["uncalendared"])
    assert not (set(in_sources) & unc)
    need = {row["table"] for row in sbl.board_map().values() if row.get("table")}
    assert need <= (set(in_sources) | unc)
    cards = load_registry().tables
    for t in set(in_sources) | unc:
        assert t in cards, t


def test_every_uncalendared_row_says_why():
    for table, reason in sbl.load_release_calendar()["uncalendared"].items():
        assert isinstance(reason, str) and len(reason.split()) >= 8, table


def test_nass_states_resolves_what_region_map_hands_it():
    """`region_map` turns a US token into the display name 'United States'; the NASS card's geo axis
    holds 'US'. This reference is the bridge, and without the alias every NASS row stays unreachable."""
    codes = sbl.load_nass_states()["codes"]
    alias_to_code = {a: c for c, e in codes.items() for a in (e.get("aliases") or [])}
    resolve = casc.load_region_map()["resolve"]
    us_tokens = [t for t, e in resolve.items() if (e or {}).get("country") == "United States"]
    assert us_tokens, "no region token resolves to the United States"
    assert alias_to_code[str(resolve[us_tokens[0]]["country"]).lower()] == "US"
    assert codes["US"]["kind"] == "national" and codes["US"]["pseudo"] is True
    assert alias_to_code["iowa"] == "IA"
    assert len(codes) == 52          # 50 states + DC + the national roll-up


def test_the_nass_reference_has_its_LOADER_and_still_no_card(): # S1 landing (was: not wired at all)
    """S0 landed the DATA only and pinned that nothing pointed at it. S1 lands the LOADER and stops
    there, on purpose and in that ORDER: ``query._country_ref`` RAISES on a ref no loader serves, so a
    card key arriving first would turn today's honest zero-row NASS lookup into a hard error on every
    lookup that names a country. A loader with no card is INERT -- nothing dispatches to it.

    The card half waits for the commit that can also carry the silver contract's `cascade_ref`
    back-pointer (through its GENERATOR, `scripts/silver/gen_registry_from_baseline.py` -- hand-editing
    the generated card reds the F011 idempotency gate) and the live `country='US'` probe, neither of
    which is reachable from a lane-free sitting."""
    from leviathan.graphrag.numbers.query import _COUNTRY_REF_LOADERS
    assert _COUNTRY_REF_LOADERS["numbers/nass_states.yaml"] == \
        ("leviathan.graphrag.numbers.nass_states", "load_nass_states")
    cards = load_registry().tables
    assert cards["silver_nass_crop_progress"].country_name_ref is None, \
        "the CARD half is the other commit's -- see the docstring"
    assert all(ts.country_name_ref in (None, *_COUNTRY_REF_LOADERS) for ts in cards.values())


def test_the_held_nass_row_is_really_absent_from_the_map():
    """The row was authored, measured and pulled back out; the file carries the reason, not the row."""
    import yaml
    doc = yaml.safe_load((ex._CFG / "numbers" / "cascade_map.yaml").read_text(encoding="utf-8"))
    assert "nass_crop_progress_ge_z" not in doc["refs"]
    assert "crush_margin_z" not in doc["refs"]
    raw = (ex._CFG / "numbers" / "cascade_map.yaml").read_text(encoding="utf-8")
    assert "HELD FOR S1" in raw and "IS **NOT** LANDED" in raw, \
        "a ref pulled back out must leave its measured reason behind, or the next sitting re-derives it"
