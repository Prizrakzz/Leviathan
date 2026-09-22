"""THE BOARD CENSUS READS THE CHAIN -- in BOTH directions. S8 lane W, round 2, census blocker 5.

`state/board_census.py` carried ZERO references to the chain leg, so the estate's own block gate could
not see a chain row AT ALL: its REGISTER TRIPS gate (`register_trips_zero`, "must be 0") and its
block-chars table read a chain-OFF block whatever the pass was for. That cuts both ways and both are
defects -- a real trip on a chain line would not have been reported, and a claimed one could not be
reproduced through the instrument the arm's own census uses.

EVERYTHING HERE IS OFFLINE. `state.__main__`'s fixture arrays are the state producer, no executor is
opened, no mirror is reached, nothing is spent. The two cells are the SAME board at the SAME tier with
the leg off and on, which is the only shape in which "the census can see it" is a measurement.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag.state import board_census as BC


def _state_fn(asof="2026-09-07"):
    from leviathan.graphrag.state.__main__ import fixture_state_fn
    return fixture_state_fn(asof)


def _curated():
    from leviathan.graphrag.numbers import cascade as CAS
    return tuple(CAS.load_chain_map()) + tuple(CAS.load_transmission_map())


@pytest.fixture(scope="module")
def graph():
    return BC.load_graph()


@pytest.fixture(scope="module")
def cells(graph):
    off = BC.board_run(graph, "soybeans_cbot", "deep", "2026-09-07", state_fn=_state_fn())
    on = BC.board_run(graph, "soybeans_cbot", "deep", "2026-09-07", state_fn=_state_fn(),
                      state_chain=True, chains=_curated())
    return {"off": off, "on": on}


def test_the_census_record_SAYS_whether_the_chain_leg_was_ARMED(cells):
    """A banked chain-off board and a banked chain-on board were indistinguishable, which is exactly
    the provenance `fixture` was added to carry: a gate read off the wrong one is a chain-off verdict
    wearing a chain-on label."""
    assert cells["off"]["chain"] == {"armed": False, "counts": {}, "rendered": 0}
    on = cells["on"]["chain"]
    assert on["armed"] is True
    assert on["rendered"] >= 1 and on["counts"]["total"] > on["rendered"]
    assert on["counts"]["rendered"] == on["rendered"]


def test_the_BLOCK_CHARS_table_and_the_register_gate_SEE_the_chain_rows(cells):
    """The block the census measures is the block the chain moved: the chain rows are in the chars, in
    the line count and in the per-class table, and the register gate is read over them."""
    off, on = cells["off"]["render"], cells["on"]["render"]
    assert on["lines"] > off["lines"], (off["lines"], on["lines"])
    assert on["chars"] != off["chars"]
    assert sum(on["by_class_lines"].values()) == on["lines"]
    assert on["unclassified"] == [] and on["multi_class"] == []
    # THE GATE IS GREEN AND IT IS GREEN OVER THE CHAIN, which is a different statement from the one
    # this instrument could make before: `trips` is read off the rendered block, chain rows included.
    assert on["trip_count"] == 0 and on["trips"] == []
    assert on["welds"] == 0


def test_the_chain_leg_moves_NO_budget_and_closes_its_rectangle(cells):
    """The chain leg is ZERO READS by construction (it composes what the board already fetched), so
    arming it must not move one cell of the budget rectangle."""
    off, on = cells["off"]["budget"], cells["on"]["budget"]
    assert on["rectangle_closed"], on["rectangle"]
    assert on["net_reads"] == off["net_reads"]
    assert on["declared_cap"] == off["declared_cap"]
    assert cells["on"]["legs"]["board"]["outcome"] == "fired"


def test_the_PATH_leg_is_the_leg_that_carries_the_chain_and_it_stays_closed(cells):
    """The chain re-stamps the PATH leg rather than minting a second one (`board.CHAIN_REASONS`' own
    note), so every banked decline histogram keeps its meaning."""
    from leviathan.graphrag.state import board as B
    leg = cells["on"]["legs"]["path"]
    assert leg["outcome"] in ("fired", "declined", "not_reached")
    if leg["outcome"] == "declined":
        assert leg["reason"] in B.CHAIN_REASONS, leg
    assert set(cells["on"]["legs"]) == set(cells["off"]["legs"]), "no new leg appears"


def test_the_CLI_declares_the_flag_and_it_DEFAULTS_OFF():
    """A census that armed the leg by default would move the baseline every board is compared against."""
    import inspect
    src = inspect.getsource(BC.main)
    assert '"--state-chain"' in src
    assert "state_chain=bool(a.state_chain)" in src
    assert inspect.signature(BC.census).parameters["state_chain"].default is False
    assert inspect.signature(BC.board_run).parameters["state_chain"].default is False
