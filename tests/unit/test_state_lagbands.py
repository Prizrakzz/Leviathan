"""The lag-band table and its parser -- STATE ENGINE DESIGN sec 2.3 (D3), sitting S0.

Every number pinned here was MEASURED over ``configs/graphrag/causal/*.yaml`` on 2026-09-08. A red on
one of the census pins is a CURATION EVENT (a DAG gained a node, or a new lag spelling was authored),
not a bug in this deck: re-measure, re-bank the counts in ``lag_bands.yaml``, and say so in the commit.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml
from leviathan.graphrag import extract as ex
from leviathan.graphrag.state import lagbands as lb

# ── the census, RE-MEASURED 2026-09-09 at HEAD 4fc933e7 (S2+S3 re-fix) ───────────────────────────────
# THE CAUSE OF THE MOVE is D-10 SITTING 9 -- THE SPLIT (commit aa7fa7d7, owner ruling 2026-09-07): three
# sign-0 reserve-level nodes joined the graph -- rough_rice_cbot/India_state_reserves,
# rough_rice_cbot/Thailand_state_reserves and soybean_oil_dce/China_state_reserves -- each declaring
# `0-2 quarters`. The DAG files live under the gitignored `configs/graphrag/`, so the sitting's tracked
# half landed in git while the graph moved on disk and these pins, measured at S0 against the pre-split
# graph, went red. Re-banked, with the delta named rather than the numbers quietly swapped.
N_DAG_FILES = 36
N_DRIVER_INSTANCES = 1270        # 1,267 at S0 + the three D-10 sitting-9 reserve-level nodes
N_INTER_COMMODITY_EDGES = 146    # unmoved: the split added NODES, no inter-commodity edge
N_DECLARATIONS = 1416            # 1,270 node lags + 146 edge lags; NONE is absent
N_NODE_STRINGS = 18              # unmoved: the three new nodes reuse a spelling the table already has
N_EDGE_STRINGS = 8               # every one of them is also one of the 18
N_TABLE_KEYS = 19                # the 18 strings + the schema default ""

#: WHAT THE BANKED TABLE HAS NOT BEEN RE-MEASURED FOR, per key, as ``(node delta, edge delta)``.
#: ``configs/graphrag/numbers/lag_bands.yaml`` carries per-key declaration counts measured at S0, and
#: the three sitting-9 nodes all declare ``0-2 quarters`` -- so the table reads 484 nodes there and the
#: DAGs now declare 487. The table is NOT edited here (this sitting's allowlist is the state package and
#: its decks; the YAML is a curated config with its own sitting), so the delta is DECLARED, and the
#: assertion below still binds every other key exactly. RE-BANKING lag_bands.yaml -- 484 -> 487 on
#: ``0-2 quarters`` -- is an OWNER-APPLY item; when it lands this dict goes back to empty and the pin
#: below tightens itself with no other edit.
TABLE_REBANK_PENDING: dict = {"0-2 quarters": (3, 0)}


def _docs():
    d = ex._CFG / "causal"
    return [(p.name, yaml.safe_load(p.read_text(encoding="utf-8")) or {}) for p in sorted(d.glob("*.yaml"))]


def test_the_dag_census_is_what_the_table_was_built_from():
    docs = _docs()
    drivers = [dr for _, doc in docs for dr in (doc.get("drivers") or [])]
    edges = [e for _, doc in docs for e in (doc.get("inter_commodity") or [])]
    assert len(docs) == N_DAG_FILES
    assert len(drivers) == N_DRIVER_INSTANCES
    assert len(edges) == N_INTER_COMMODITY_EDGES
    node_strings = {dr.get("lag", "") for dr in drivers}
    edge_strings = {e.get("lag", "") for e in edges}
    assert len(node_strings) == N_NODE_STRINGS
    assert len(edge_strings) == N_EDGE_STRINGS
    assert edge_strings <= node_strings, "an edge lag spelling the nodes never use"
    assert len(drivers) + len(edges) == N_DECLARATIONS


def test_every_declared_lag_parses_and_none_is_silently_zero():
    for name, doc in _docs():
        for dr in (doc.get("drivers") or []):
            band = lb.parse_lag(dr.get("lag", ""))
            assert not band.unparsed, "%s %s: lag %r is outside the table" % (name, dr.get("id"), dr.get("lag"))
        for e in (doc.get("inter_commodity") or []):
            band = lb.parse_lag(e.get("lag", ""))
            assert not band.unparsed, "%s edge -> %s: lag %r is outside the table" % (
                name, e.get("driver_commodity"), e.get("lag"))


def test_the_table_shape():
    doc = lb.load_lag_bands()
    bands = doc.get("bands") or {}
    assert len(bands) == N_TABLE_KEYS
    assert doc.get("schema_default") == ""
    assert "" in bands, "the schema default is a table ROW, not a missing key"
    for key, row in bands.items():
        assert row["kind"] in lb.KINDS
        assert row["kind"] == lb.derived_kind(row["min_q"], row["max_q"], key)
        if row["max_q"] is not None:
            assert row["min_q"] <= row["max_q"]


def test_the_two_strings_the_walks_regex_cannot_read_are_in_the_table():
    # `cascade._CW_LAG_RX` is ^(\\d+)-(\\d+)\\s+quarters?$ and fails both of these. The board's
    # projection horizon meets them; the table is where they are declared rather than dropped.
    zero = lb.parse_lag("0 quarters")
    assert (zero.kind, zero.min_q, zero.max_q) == ("point", 0, 0)
    structural = lb.parse_lag("structural")
    assert (structural.kind, structural.min_q, structural.max_q) == ("structural", 8, None)
    assert structural.open_ended and not structural.unparsed


def test_the_measured_counts_ride_the_table():
    """The per-key declaration counts in the YAML equal what the DAGs actually declare, plus the ONE
    named delta the D-10 sitting-9 curation opened and the table has not been re-banked for.

    THE FENCE IS CORRECTED, NOT DELETED. Dropping to "the totals agree" would have let any per-key drift
    through, and skipping the key would have stopped measuring the busiest band in the estate. Every key
    still binds exactly; ``0-2 quarters`` binds to the table's banked count PLUS the three curated nodes
    that moved it, so this deck reds on the next curation exactly as it did on this one -- and it reds
    the moment ``lag_bands.yaml`` IS re-banked, which is the reminder that the owner-apply item is
    still open."""
    bands = lb.load_lag_bands()["bands"]
    node_counts, edge_counts = {}, {}
    for _, doc in _docs():
        for dr in (doc.get("drivers") or []):
            node_counts[dr.get("lag", "")] = node_counts.get(dr.get("lag", ""), 0) + 1
        for e in (doc.get("inter_commodity") or []):
            edge_counts[e.get("lag", "")] = edge_counts.get(e.get("lag", ""), 0) + 1
    for key, row in bands.items():
        dn, de = TABLE_REBANK_PENDING.get(key, (0, 0))
        assert row["counts"]["nodes"] + dn == node_counts.get(key, 0), key
        assert row["counts"]["edges"] + de == edge_counts.get(key, 0), key
    # the declared delta is the WHOLE difference between the banked table and the graph on disk
    assert sum(r["counts"]["nodes"] for r in bands.values()) \
        + sum(d[0] for d in TABLE_REBANK_PENDING.values()) == N_DRIVER_INSTANCES
    assert sum(r["counts"]["edges"] for r in bands.values()) \
        + sum(d[1] for d in TABLE_REBANK_PENDING.values()) == N_INTER_COMMODITY_EDGES


def test_an_unknown_spelling_gets_no_band_and_is_never_zeroed():
    band = lb.parse_lag("2 to 4 quarters")     # a plausible spelling the DAGs do not use
    assert band.kind == "unspecified"
    assert band.unparsed
    assert (band.min_q, band.max_q) == (None, None), "an unknown lag must NOT read as contemporaneous"
    assert band.months() == (None, None)


def test_none_reads_as_the_schema_default():
    band = lb.parse_lag(None)
    assert (band.raw, band.kind, band.min_q, band.max_q) == ("", "unspecified", 0, 0)
    assert not band.unparsed, "the schema default is DECLARED; only an unknown spelling is unparsed"


def test_months_are_three_per_quarter_at_both_ends():
    assert lb.parse_lag("1-3 quarters").months() == (3, 9)
    assert lb.parse_lag("0 quarters").months() == (0, 0)
    assert lb.parse_lag("structural").months() == (24, None)


def test_a_path_band_is_never_summed():
    a, b = lb.parse_lag("1-2 quarters"), lb.parse_lag("0-2 quarters")
    with pytest.raises(TypeError, match="NEVER summed"):
        a + b
    with pytest.raises(TypeError, match="NEVER summed"):
        sum([a, b])


def test_the_parser_is_the_only_reader_of_the_table_file():
    """One table, one parser: no other module in the estate BUILDS the path to lag_bands.yaml.

    The search is for the quoted python literal, so a module that merely NAMES the file in its prose
    (state/__init__.py and state/lint.py both do) is not counted as a second reader."""
    root = pathlib.Path(ex.__file__).resolve().parents[2]
    hits = [p for p in root.rglob("*.py")
            if '"lag_bands.yaml"' in p.read_text(encoding="utf-8", errors="ignore")
            or "'lag_bands.yaml'" in p.read_text(encoding="utf-8", errors="ignore")]
    assert {p.name for p in hits} == {"lagbands.py"}, [str(p) for p in hits]
