"""Lag-band parsing over the DAGs' declared lag vocabulary -- STATE ENGINE DESIGN sec 2.3 (D3).

ONE table (``configs/graphrag/numbers/lag_bands.yaml``), one parser, no second opinion. Every ``lag``
string the 36 curated causal DAGs declare -- 1,416 declarations as re-measured 2026-09-09 (1,270 node
lags + 146 edge lags; the D-10 sitting-9 split added three) in 18 distinct node strings, 8 of which
are also edge strings, plus the schema default ``""`` -- resolves through :func:`parse_lag` to a
:class:`LagBand` of ``(min_q, max_q)`` QUARTERS. A string outside the table parses to kind
``unspecified`` with NO band and ``unparsed`` True, so a caller counts it (``lag_unparsed``) rather than
silently treating an unknown spelling as contemporaneous.

THE ONE LAW WORTH REPEATING (sec 2.3, doctrine M-4). A driver's ``lag`` is ITS OWN lag onto the
contract's ``target_metric`` -- the same convention ``sign`` carries (causal/schema.py:9-11) -- never a
parent-to-child lag. An ancestor three hops upstream therefore declares its own band onto the ANCHOR
price, and **a path's band is never summed**. :class:`LagBand` refuses ``+`` at runtime and
``state/lint.py`` greps the package for a summed band, because the arithmetic is easy to write and the
horizon it produces is one the graph never declared.

THREE CONSUMERS, ONE TABLE: the projection horizon, the analog outcome window (read at BOTH ends), and
the watch window. Each states the BAND, never a point; a ``structural`` band opens at eight quarters
and never closes (``max_q is None``).

TWO STRINGS THE WALK'S OWN REGEX CANNOT READ. ``cascade._CW_LAG_RX`` is ``^(\\d+)-(\\d+)\\s+quarters?$``
and fails both ``"0 quarters"`` and ``"structural"``. MEASURED at this landing: both occur on DRIVER
nodes only and never on an inter-commodity edge, so the walk's child gate has never met them -- the
board's projection horizon does, and this module is where they are declared rather than dropped.

Pure: no clock, no I/O beyond one lru_cached YAML read, no network.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Optional

import yaml

from leviathan.graphrag import extract as ex  # ex._CFG -> configs/graphrag

_REL = ("numbers", "lag_bands.yaml")

#: the closed kind enum (sec 2.3). `unspecified` covers BOTH the schema default (declared in the table,
#: band (0, 0)) and a spelling the table does not know (no band, `unparsed` True) -- `unparsed` is what
#: tells them apart, never the kind word.
KINDS = ("band", "point", "structural", "unspecified")

QUARTER_MONTHS = 3


@dataclass(frozen=True)
class LagBand:
    """An OFFSET BAND in quarters, never a gate and never a point.

    ``max_q is None`` means open-ended (``structural``): the window opens and does not close.
    ``min_q is None`` means the string was not in the table: there is NO band, and a consumer must
    decline by name rather than assume zero.
    """

    raw: str
    kind: str
    min_q: Optional[int]
    max_q: Optional[int]

    @property
    def unparsed(self) -> bool:
        """True when the declared string is outside the table -- count it, never zero it."""
        return self.min_q is None

    @property
    def open_ended(self) -> bool:
        return self.min_q is not None and self.max_q is None

    def months(self) -> tuple[Optional[int], Optional[int]]:
        """The band in MONTHS -- ``(3*min_q, 3*max_q)``; either end stays None when it is None."""
        lo = None if self.min_q is None else self.min_q * QUARTER_MONTHS
        hi = None if self.max_q is None else self.max_q * QUARTER_MONTHS
        return lo, hi

    def __add__(self, other):  # noqa: D105 -- the refusal IS the documentation
        raise TypeError(
            "a path's lag band is NEVER summed (STATE ENGINE sec 2.3, doctrine M-4): each node declares "
            "its OWN band onto the contract's target metric, so adding two bands invents a horizon the "
            "graph never declared. Use the node's own band, or decline `lag_undeclared_between_nodes`."
        )

    __radd__ = __add__


@functools.lru_cache(maxsize=1)
def load_lag_bands() -> dict:
    """The raw ``lag_bands.yaml`` document (lru_cached, the registry convention)."""
    p = ex._CFG / _REL[0] / _REL[1]
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


@functools.lru_cache(maxsize=1)
def _bands() -> dict:
    return dict((load_lag_bands().get("bands") or {}))


def table_keys() -> tuple[str, ...]:
    """Every lag string the table declares, in file order."""
    return tuple(_bands())


def parse_lag(s: Optional[str]) -> LagBand:
    """``lag`` string -> :class:`LagBand`. Fail-closed: an unknown spelling gets NO band.

    ``None`` is read as the schema default ``""`` (causal/schema.py declares ``lag: str = ""``), which
    the table declares explicitly -- so an absent lag is a table row, not a missing one.
    """
    raw = "" if s is None else str(s)
    row = _bands().get(raw)
    if row is None:
        return LagBand(raw=raw, kind="unspecified", min_q=None, max_q=None)
    kind = row.get("kind") or "band"
    if kind not in KINDS:
        kind = "unspecified"
    return LagBand(raw=raw, kind=kind, min_q=row.get("min_q"), max_q=row.get("max_q"))


def derived_kind(min_q: Optional[int], max_q: Optional[int], raw: str) -> str:
    """The kind a ``(min_q, max_q, raw)`` triple IMPLIES -- the second opinion ``state/lint.py`` pins
    the table's declared ``kind`` against, so a hand-edited row cannot claim to be something it is not."""
    if raw == "":
        return "unspecified"
    if min_q is None:
        return "unspecified"
    if max_q is None:
        return "structural"
    if min_q == max_q:
        return "point"
    return "band"
