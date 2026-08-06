"""Reasoning modes (D-AM-9..12) -- the per-turn REASONING-SCALE presets, ONE producer.

A LEAF module by construction, copying `response_contracts.py`'s shape exactly: it imports NOTHING
from leviathan.graphrag (pure data + pure functions), so orchestrator.py, answer.py, server.py and
eval.py can all import it without cycles, and the preset table cannot be hand-copied into a second
module and drift (the COMPAT-9 duplicate-and-pin defect class).

THREE PRESETS -- `quick` / `standard` / `deep`. `standard` is ALL-NONE: `knobs("standard")` is the
EMPTY DICT, every kwarg builder returns `{}`, and every call site therefore stays byte-identical
under the omit-when-default idiom. That empty dict IS the fail-open guarantee (the same role the
`default` response contract's empty directive plays), not a promise anyone has to keep by hand.

FAIL-OPEN, NEVER A 400: an unknown or absent `mode` resolves to `standard` and stamps
`invalid=True`; a desk turn must not die on a typo. `resolve()` is the ONE place that decides, and
it also applies the honor allowlist -- a mode that is accepted and stamped but NOT in the allowlist
runs `standard` knobs (the DARK stage, D-AM-12).

v1 KNOBS ARE CLASS-1 ONLY -- every one is already an accepted keyword of its callee, so this wave
THREADS values, it does not redesign seams:
  walk      node_budget / depth / max_seeds        -> planner.grounded_subgraph
  ground    k_by_depth / evidence_cap / probe_cap  -> planner.ground
  retrieval fetch_k                                -> evidence.retrieve, via a per-call partial rebind
  silver    silver_cap                             -> silverleg.make_silver_lookup(cap=)
  scaffold  scaffold_max_bullets / _max_absence    -> the episode-scaffold caps (params-driven today)
  contract  budget_scale                           -> scales the ACTIVE response contract's word range
  gate      xc_force                               -> the reroute-v2 request gate (force off / force on)

EXCLUDED FROM v1, each with its recorded reason (do NOT add these without a new ratification):
  * rerank pool          -- a module-global read at the slice site; per-request mutation bleeds
                            across the shared threadpool.
  * coalescer window / quiescence -- process singleton; a per-request window re-arms the documented
                            cross-turn quota defect (rankers.py).
  * timeline floors      -- under the artifact-stamp governance fence (timeline.py).
  * recency_days         -- changes which regimes FIRE, i.e. changes FACTS, not depth.
  * synthesis max_tokens -- truncation history; the contract word budget is the length lever.
  * cascade_quant        -- read inside verify.py, so varying it per request moves the strip-rate
                            DEFINITION and makes arms incomparable.
  * the episode/contract FLAGS themselves -- they are the D-RC soak surface.

PIT SAFETY (stated once, for the record -- do not re-derive at the call sites): widening k /
fetch_k / node_budget / evidence and probe caps CANNOT leak post-asof evidence, by construction.
The as-of leakage filter runs BEFORE any width slicing on BOTH evidence backends (evidence.py and
pgstore.py), so a wider read returns MORE of the same already-filtered population, never anything
newer than the turn's horizon. `deep` is therefore PIT-neutral, and `quick` only narrows.
"""
from __future__ import annotations

from dataclasses import dataclass, fields

QUICK = "quick"
STANDARD = "standard"
DEEP = "deep"


@dataclass(frozen=True)
class Mode:
    """One preset. EVERY knob defaults to None = "leave the callee's own default alone"; the
    all-None `standard` entry is the passthrough pin. `k_by_depth` is a TUPLE so the dataclass stays
    hashable and the table stays immutable (planner's own default is a tuple too)."""
    name: str
    # walk (planner.grounded_subgraph)
    node_budget: int | None = None
    depth: int | None = None
    max_seeds: int | None = None
    # ground (planner.ground)
    k_by_depth: tuple | None = None
    evidence_cap: int | None = None
    probe_cap: int | None = None
    # retrieval (evidence.retrieve, rebound per call)
    fetch_k: int | None = None
    # silver leg (silverleg.make_silver_lookup)
    silver_cap: int | None = None
    # episode-scaffold noise caps
    scaffold_max_bullets: int | None = None
    scaffold_max_absence: int | None = None
    # response-contract word budget multiplier (applied only when a contract is ACTIVE)
    budget_scale: float | None = None
    # reroute-v2 cross-commodity gate: None = leave the flag's decision alone; False = force OFF;
    # True = force ON *where the existing realizability gate already allows it* (the gate still
    # decides; this only lets it be consulted on a turn the flag would have skipped).
    xc_force: bool | None = None


MODES: dict[str, Mode] = {m.name: m for m in (
    Mode(name=QUICK,
         node_budget=6, depth=1, max_seeds=1,
         k_by_depth=(4, 2), evidence_cap=12, probe_cap=12,
         fetch_k=40, silver_cap=4,
         scaffold_max_bullets=6, scaffold_max_absence=3,
         budget_scale=0.7, xc_force=False),
    Mode(name=STANDARD),          # LOAD-BEARING: all-None IS the byte-identical passthrough guarantee
    Mode(name=DEEP,
         node_budget=16, depth=3, max_seeds=3,
         k_by_depth=(7, 5, 3), evidence_cap=48, probe_cap=36,
         fetch_k=120, silver_cap=12,
         scaffold_max_bullets=12, scaffold_max_absence=6,   # == today's params default (deep = today)
         budget_scale=1.5, xc_force=True),
)}

# The knob field names, in declaration order (the trace-stamp column order; append, never sort).
KNOB_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(Mode) if f.name != "name")

_WALK_KNOBS = ("node_budget", "depth", "max_seeds")
_GROUND_KNOBS = ("k_by_depth", "evidence_cap", "probe_cap")


def valid_names() -> frozenset:
    return frozenset(MODES)


def resolve(requested: str | None, allowed) -> dict:
    """THE one resolution. Returns the stamp `{requested, honored, invalid}`:

      * `requested` -- the normalized name the caller asked for (None when absent).
      * `invalid`   -- True iff a non-empty request named no known mode (the `mode_invalid` stamp).
      * `honored`   -- the mode whose knobs actually run. `standard` always (it needs no flag and
        changes nothing); any other mode only when it is in `allowed`, else `standard`.

    `allowed` is the caller's already-parsed allowlist (the env read lives at the orchestrator seam;
    this module reads no environment). Never raises, never returns an unknown name."""
    req = (requested or "").strip().lower() or None
    invalid = bool(req) and req not in MODES
    name = req if (req and not invalid) else STANDARD
    honored = name if (name == STANDARD or name in (allowed or ())) else STANDARD
    return {"requested": req, "honored": honored, "invalid": invalid}


def get(name: str | None) -> Mode:
    """The preset, `standard` for None/unknown (fail-open, same as resolve())."""
    return MODES.get((name or "").strip().lower(), MODES[STANDARD])


def knobs(name: str | None) -> dict:
    """The RESOLVED non-None knob values for a mode -- {} for standard/None/unknown.

    This dict is what the orchestrator threads DOWN as one argument and stamps on the trace, so the
    "what depth ran" chip and the eval artifact read exactly the values the engines received. Empty
    => every kwarg builder below is empty => every call site is byte-identical."""
    m = get(name)
    return {k: getattr(m, k) for k in KNOB_FIELDS if getattr(m, k) is not None}


def walk_kwargs(kn: dict | None) -> dict:
    """`planner.grounded_subgraph` kwargs present in `kn` ({} when standard/absent)."""
    return {k: kn[k] for k in _WALK_KNOBS if kn and kn.get(k) is not None}


def ground_kwargs(kn: dict | None) -> dict:
    """`planner.ground` kwargs present in `kn` ({} when standard/absent)."""
    return {k: kn[k] for k in _GROUND_KNOBS if kn and kn.get(k) is not None}


def scale_budget(budget: str | None, scale: float | None) -> str | None:
    """Scale a response contract's word-range phrase ('150-220' -> '110-150' at x0.7), rounding each
    end HALF-UP to the nearest 10 (deterministic: Python's round() is banker's rounding, which would
    make 105 -> 100 and the arithmetic un-reproducible across ends).

    Returns None when there is nothing to do (no scale, no budget, or a phrase that is not the
    `lo-hi` shape) -- the caller then leaves the contract's own budget untouched. Fail-open: this
    function never raises and never widens a range to zero (floor 10, and hi >= lo always)."""
    if not budget or not scale:
        return None
    parts = str(budget).split("-")
    if len(parts) != 2:
        return None
    try:
        lo, hi = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None
    def _r(v: float) -> int:
        return max(10, (int(v) + 5) // 10 * 10)
    slo, shi = _r(lo * scale), _r(hi * scale)
    return f"{slo}-{max(slo, shi)}"
