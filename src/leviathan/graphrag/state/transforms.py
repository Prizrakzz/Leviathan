"""The board's TRANSFORM REGISTRY -- STATE ENGINE DESIGN sec 2.5 (D14), sitting S1.

THE V1 STEPPING STONE toward EXECUTABLE MATH WITH PROVENANCE (the arc's named V2 successor). A registry
of NAMED, PARAMETERISED transforms whose results RENDER WITH THEIR PARAMETERS, every one of them a call
into ``numbers/stats.py`` -- and **this module defines NO stat function**. That sentence is the design
decision, not a style note: revision 1 of the design put four new leaves here, and four leaves outside
``stats.py`` would have been the two-calculator drift sec 1.6 refuses in the same breath it refuses two
z producers. The four leaves (``regime_flag``, ``flag_events``, ``pace_vs_prior``, ``rolling_zscore``)
therefore live IN ``stats.py``, under its floor family and its import-time ``BANNED_PATTERN`` assertion,
and are NAMED here.

``STAT_REGISTRY`` IS NOT WIDENED. That registry is the numbers AGENT's enum-locked tool schema
("the tool-schema source", stats.py:19), and stats.py's own AM-3 rule says widening the enum is never a
side effect of adding an engine function; ``config_check.check_stats_registry`` pins it. This registry is
a SECOND, board-owned surface with a different consumer: the BOARD composes it deterministically, and no
LLM composes anything at answer time in V1. (Whether the agent gets a second enum in V1.1 is a decision
with a measured trigger -- design D29 -- because a second enum is a ~98k-token prompt-cache write on
every hybrid turn, and one arm tests one instrument.)

THE DERIVATION RECORD is the point of the whole module. Every call returns
``{transform, params, n, inputs}`` beside its result: the transform's NAME, the parameters it ran under,
the ``n`` it ran over, and REFERENCES to its inputs -- never the input values themselves. Because the
inputs are references into a bundle of fetched arrays, :func:`re_execute` can run the record again from
the same rows and get the same number, which is the V1 stand-in for V2's verifier rule (lint clause 3).
A figure a reader sees is therefore reproducible, not merely cited.

FOUR LINT CLAUSES (sec 2.5), all enforced by :func:`lint_registry` and pinned by
``tests/unit/test_state_transforms.py``:
  1. every transform's stat name passes ``stats.is_banned_name`` -- no fit/trend/forecast/project/
     extrapolat/predict can enter through this surface either;
  2. every entry that measures against a WINDOW declares which parameter names it, so a rendered figure
     can print its window in the cadence's own noun and its ``n`` beside it (the futures_z precedent);
  3. every derivation re-executes to the same value from the same inputs;
  4. ``stats.STAT_REGISTRY`` is untouched by this module -- asserted, not promised.

PURE: no I/O, no clock, no network. The arrays arrive already fetched and already PIT-guarded.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from leviathan.graphrag.numbers import stats as st

# ---------------------------------------------------------------------------------------------------
# THE INPUT MODEL -- references, never values.
# ---------------------------------------------------------------------------------------------------
#: The closed selector vocabulary. A derivation's input is ``(bundle key, selector)``; the selector says
#: WHICH axis of that key's fetched arrays the argument reads. Five words and no more: a selector that
#: could COMPUTE would make the record un-re-executable without re-implementing the computation, so
#: ``last`` (the newest observation) is the only reduction and it is a pick, not an arithmetic.
SELECTORS: tuple[str, ...] = ("values", "last", "dates", "labels", "unit")


def _select(arrays: dict, selector: str):
    """Resolve one selector against one bundle entry (``{'values': [...], 'dates': [...], ...}``)."""
    if selector == "values":
        return list(arrays.get("values") or [])
    if selector == "last":
        vals = list(arrays.get("values") or [])
        if not vals:
            raise ValueError("selector 'last' on an empty values axis")
        return vals[-1]
    if selector == "dates":
        return list(arrays.get("dates") or [])
    if selector == "labels":
        return list(arrays.get("labels") or [])
    if selector == "unit":
        # the UNIT LABEL of the read, not a number: stats.pair_spread's unit guard is a two-string
        # policy (D-FR-5) and it refuses rather than converts, so the label must reach it from the row
        # that fetched it -- never re-typed at a call site, where a stale copy would fail OPEN.
        return arrays.get("unit")
    raise ValueError(f"unknown selector {selector!r}; the closed set is {SELECTORS}")


@dataclass(frozen=True)
class TransformSpec:
    """One registry entry: a NAME, the ``stats`` function it calls, its declared parameters, and the
    default input wiring (``arg -> selector``) so the ordinary one-series call is one line.

    ``window_param`` names the parameter a rendered figure must print beside its ``n`` (lint clause 2);
    ``None`` means the transform measures over the WHOLE array it was handed, and the row prints the
    array's own span instead -- which is still a stated window, never an unstated one."""

    name: str
    stat: str                                     # the attribute name in stats.py
    params: tuple[str, ...] = ()
    inputs: tuple[tuple[str, str], ...] = (("series", "values"),)   # (arg, default selector)
    window_param: Optional[str] = None
    note: str = ""

    def fn(self) -> Callable[..., dict]:
        f = getattr(st, self.stat, None)
        if not callable(f):
            raise ValueError(f"transform {self.name!r} names stats.{self.stat}, which does not exist")
        return f


# ---------------------------------------------------------------------------------------------------
# THE REGISTRY (sec 2.5). Fourteen shipped stats plus the four leaves S1 added to stats.py.
# ---------------------------------------------------------------------------------------------------
TRANSFORM_REGISTRY: dict[str, TransformSpec] = {
    # -- the state row's own four measures ----------------------------------------------------------
    "window_change": TransformSpec(
        "window_change", "window_change", params=("t1", "t2", "window_label"),
        inputs=(("series", "values"),), window_param="window_label",
        note="the change between two INDICES of the collapsed series; the label is the cadence's noun "
             "('4 weeks'), and it rides the record so the rendered line can never name a window the "
             "indices do not describe"),
    "zscore": TransformSpec(
        "zscore", "zscore", params=("window",),
        inputs=(("value", "last"), ("history", "values")), window_param="window",
        note="EVERY z on the board is this one (D5): population variance, floor 8. silverleg's private "
             "_z (sample variance, floor 5) is a MEASURED divergence carried as a census finding, not a "
             "second producer this registry may reach for"),
    "percentile": TransformSpec(
        "percentile", "percentile", params=(),
        inputs=(("value", "last"), ("history", "values")), window_param=None,
        note="the row's own history is the population; the row prints the span it ranked against"),
    "streak": TransformSpec(
        "streak", "streak", params=("direction",), inputs=(("series", "values"),),
        note="run length in the named direction ending at the latest observation"),

    # -- the same measures at every prefix, and the flag row's substitute for them -------------------
    "rolling_zscore": TransformSpec(
        "rolling_zscore", "rolling_zscore", params=("window",),
        inputs=(("series", "values"),), window_param="window",
        note="S1 leaf: the state vector AS KNOWABLE AT EACH t -- the analog selector's input (sec 4.1). "
             "A None at a position is an honest hole, never a zero"),
    "flag_events": TransformSpec(
        "flag_events", "flag_events", params=("window_periods",),
        inputs=(("series", "values"), ("dates", "dates")), window_param="window_periods",
        note="S1 leaf: a *_flag ref's state. z and percentile DECLINE by name on these rows -- a sigma "
             "over a 0/1 column is a base rate wearing a sigma's clothes"),

    # -- the ordering label -------------------------------------------------------------------------
    "regime_flag": TransformSpec(
        "regime_flag", "regime_flag", params=("kind", "bands", "labels"),
        inputs=(("value", "last"),),
        note="S1 leaf: ORDERING ONLY (ruling 1). It attaches a word; it never excludes a row, gates a "
             "traversal, vetoes a driver or fires a regime. No match is a stated outcome, not a decline"),

    # -- pace, revisions, and the two-part constructions ---------------------------------------------
    "pace_vs_prior": TransformSpec(
        "pace_vs_prior", "pace_vs_prior", params=("periods_per_year",),
        inputs=(("series", "values"),), window_param="periods_per_year",
        note="S1 leaf: yoy_delta over the SHIPPED cross-section collapse (cascade._pace_series), never a "
             "third pace producer beside _pace_legs and _pace_series"),
    "yoy_delta": TransformSpec(
        "yoy_delta", "yoy_delta", params=("periods",), inputs=(("series", "values"),),
        window_param="periods"),
    "revision_count": TransformSpec(
        "revision_count", "revision_count", params=("direction",), inputs=(("vintage_rows", "values"),),
        note="consecutive revisions across VINTAGES of one period -- the release-cadence row's measure, "
             "where a z is meaningless"),
    "ratio": TransformSpec(
        "ratio", "ratio", params=("scale",),
        inputs=(("numerator", "last"), ("denominator", "last")),
        note="the ONE governed quotient. NOT used by any V1 board row: none of the 46 live refs is a "
             "component ratio (psd_ending_stock_su_ratio reads the SERVED su_ratio column). Registered "
             "because the component-ratio read shape is a NAMED V1.1 item and the name should not move"),
    "share": TransformSpec(
        "share", "share", params=(), inputs=(("part", "last"), ("other_parts", "values"))),
    "spread": TransformSpec(
        "spread", "spread", params=("near", "far"),
        inputs=(("series", "values"), ("expiries", "labels")),
        note="the CURVE-axis stat: its two legs are NAMED, never inferred -- there is no front-month "
             "guess in this registry"),
    "pair_spread": TransformSpec(
        "pair_spread", "pair_spread", params=("label_a", "label_b"),
        inputs=(("series_a", "values"), ("dates_a", "dates"), ("unit_a", "unit"),
                ("series_b", "values"), ("dates_b", "dates"), ("unit_b", "unit")),
        note="two legs from TWO reads, joined by observation DATE -- the caller names both bundle keys, "
             "and each leg's UNIT rides from the read that fetched it so the constructor's own unit "
             "guard can refuse rather than convert"),
    "rolling_corr": TransformSpec(
        "rolling_corr", "rolling_corr", params=("window",),
        inputs=(("series_a", "values"), ("labels_a", "dates"),
                ("series_b", "values"), ("labels_b", "dates")),
        window_param="window"),
    "quantiles": TransformSpec(
        "quantiles", "quantiles", params=("probs",), inputs=(("series", "values"),)),
    "sign_agreement": TransformSpec(
        "sign_agreement", "sign_agreement", params=("edge_sign",),
        inputs=(("parent_move", "last"), ("child_move", "last")),
        note="the verdict WORD on one declared hop. The sign is the EDGE's, read at traversal -- this "
             "registry never reconciles two boards' signs (ruling 3)"),
    "extreme_locator": TransformSpec(
        "extreme_locator", "extreme_locator", params=("direction",),
        inputs=(("series", "values"), ("dates", "dates"))),
}

#: The frozen name set. A new transform is a reviewed change to this module, never an ad-hoc call.
TRANSFORM_NAMES: frozenset[str] = frozenset(TRANSFORM_REGISTRY)

#: ``stats.STAT_REGISTRY``'s keys as of this landing -- pinned so lint clause 4 can assert that adding a
#: transform here never widened the AGENT's enum there.
FROZEN_STAT_REGISTRY: tuple[str, ...] = (
    "extrema", "percentile", "revision_count", "spread", "streak", "window_change", "yoy_delta", "zscore",
)


# ---------------------------------------------------------------------------------------------------
# RUNNING ONE, AND RUNNING IT AGAIN
# ---------------------------------------------------------------------------------------------------
def run_transform(name: str, bundle: dict, *, key: str = "", params: Optional[dict] = None,
                  inputs: Optional[dict] = None) -> tuple[dict, dict]:
    """Run ONE registered transform over a bundle of already-fetched arrays and return
    ``(result, derivation)``.

    ``bundle`` maps an input KEY (a series key label, or any caller-chosen handle) to
    ``{'values': [...], 'dates': [...], 'labels': [...]}``. ``key`` is the default bundle key for every
    argument the transform declares; ``inputs`` overrides per argument as ``{arg: (key, selector)}`` --
    which is how the two-leg transforms name their second read.

    THE RESULT IS ``stats.py``'s OWN CONTRACT DICT, decline included, unchanged. A decline is a real
    outcome that the row renders in words ("a 156-week window needs 156 weeks; this series holds 41"),
    so it is recorded with its derivation exactly as a success is: a figure that could not be computed
    still has a reproducible reason."""
    spec = TRANSFORM_REGISTRY.get(name)
    if spec is None:
        raise KeyError(f"unknown transform {name!r}; the registry holds {sorted(TRANSFORM_NAMES)}")
    ps = dict(params or {})
    bad = sorted(set(ps) - set(spec.params))
    if bad:
        raise ValueError(f"transform {name!r} accepts {spec.params}, got unknown parameter(s) {bad}")
    wiring: dict = {}
    for arg, default_sel in spec.inputs:
        k, sel = (inputs or {}).get(arg, (key, default_sel))
        if not k:
            raise ValueError(f"transform {name!r} argument {arg!r} has no bundle key")
        if sel not in SELECTORS:
            raise ValueError(f"transform {name!r} argument {arg!r} names selector {sel!r}; "
                             f"the closed set is {SELECTORS}")
        wiring[arg] = (k, sel)
    call = {}
    n_seen = 0
    for arg, (k, sel) in wiring.items():
        arrays = bundle.get(k)
        if arrays is None:
            raise KeyError(f"transform {name!r} argument {arg!r} names bundle key {k!r}, which is absent")
        call[arg] = _select(arrays, sel)
        n_seen = max(n_seen, len(arrays.get("values") or []))
    fn = spec.fn()
    sig = inspect.signature(fn)
    kwonly = {p.name for p in sig.parameters.values() if p.kind is p.KEYWORD_ONLY}
    positional = [call[a] for a, _ in spec.inputs]
    kwargs = {p: v for p, v in ps.items() if p in sig.parameters}
    # a declared parameter the callee does not take is a RENDER-ONLY label (window_label); it rides the
    # record so the line can print it, and it is never smuggled into the call.
    out = fn(*positional, **{k: v for k, v in kwargs.items() if k in kwonly or k in sig.parameters})
    rec = {
        "transform": name,
        "params": {p: ps.get(p) for p in spec.params},
        "n": int(out.get("n", n_seen) or 0),
        "inputs": [{"arg": a, "key": wiring[a][0], "select": wiring[a][1]} for a, _ in spec.inputs],
        # THE RE-EXECUTION WITNESS, under a leading underscore because it is not part of the record's
        # rendered shape (the design's four keys are ``transform``, ``params``, ``n``, ``inputs``). It
        # exists so :func:`re_execute_all` can assert EQUALITY rather than merely assert that the record
        # runs -- "it runs again" and "it produces the same number again" are different claims, and only
        # the second one is worth making about a figure a reader will act on.
        "_result": out,
    }
    return out, rec


def re_execute(rec: dict, bundle: dict) -> dict:
    """Run a DERIVATION RECORD again from the same bundle. Lint clause 3, and the V1 stand-in for V2's
    verifier rule: a rendered board's every derivation must reproduce its own value from its own rows.

    It goes back through :func:`run_transform` rather than calling ``stats`` directly on purpose -- an
    oracle that takes a different path than the producer verifies the path, not the producer."""
    out, _ = run_transform(rec["transform"], bundle,
                           params=dict(rec.get("params") or {}),
                           inputs={i["arg"]: (i["key"], i["select"]) for i in (rec.get("inputs") or [])})
    return out


def re_execute_all(derivations, bundle: dict) -> list[str]:
    """Re-run EVERY derivation of a row (or of a whole board) against the arrays it was computed from,
    and return the mismatches by name; empty == every figure reproduces. Lint clause 3, and the shape a
    unit test asserts on: "a unit test RE-EXECUTES every derivation of a rendered board from the same
    fetched rows and asserts equality" (sec 2.5).

    A DECLINE MUST REPRODUCE TOO. A record whose result was a decline is re-executed like any other and
    must decline again with the same reason -- otherwise a window that "could not be measured" on one
    pass and could on the next would be a nondeterminism nobody would ever see."""
    problems: list[str] = []
    for i, rec in enumerate(derivations or []):
        try:
            out = re_execute(rec, bundle)
        except Exception as exc:                      # noqa: BLE001 -- reported, never raised onward
            problems.append(f"derivation[{i}] {rec.get('transform')!r} did not re-execute: {exc}")
            continue
        want = rec.get("_result")
        if want is not None and out != want:
            problems.append(f"derivation[{i}] {rec.get('transform')!r} re-executed to a different "
                            f"result: {out!r} != {want!r}")
    return problems


def render_params(rec: dict) -> str:
    """The parameters of one derivation, as ASCII a line can print. "Results render WITH THEIR
    PARAMETERS" is the owner's own wording of the stepping stone, so this is the renderer's single
    source for that half and not an f-string at a call site.

    A parameter whose value is None is OMITTED rather than printed as "None": an unset parameter is not
    a value, and "window=None" reads to a human as a measured window of nothing."""
    ps = {k: v for k, v in (rec.get("params") or {}).items() if v is not None}
    if not ps:
        return rec.get("transform", "")
    body = ", ".join(f"{k}={_fmt(v)}" for k, v in sorted(ps.items()))
    return f"{rec.get('transform', '')}({body})"


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return str(v)


def params_hash(derivations) -> str:
    """The ``transform_params_hash`` term of the board's memo key (sec 1.1).

    WHY THE KEY NEEDS IT: a z over 250 sessions and a z over 504 days are two different states of one
    series, and a memo keyed only on ``(ref, scope, asof, read_shape)`` would serve the first to a caller
    that asked for the second -- silently, and IMMORTALLY on a historical as-of. The hash covers the
    transform NAMES and their PARAMETERS in sorted order; it deliberately does NOT cover the input keys,
    because those are the series key the memo is already keyed on."""
    payload = sorted(
        (str(d.get("transform", "")), json.dumps(d.get("params") or {}, sort_keys=True, default=str))
        for d in (derivations or []))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------------
# THE LINT (sec 2.5's four clauses)
# ---------------------------------------------------------------------------------------------------
def lint_registry() -> list[str]:
    """Structural lint over the registry. Returns a list of problems; empty == clean."""
    problems: list[str] = []
    for name, spec in sorted(TRANSFORM_REGISTRY.items()):
        if name != spec.name:
            problems.append(f"registry key {name!r} does not match spec.name {spec.name!r}")
        if st.is_banned_name(name) or st.is_banned_name(spec.stat):          # clause 1
            problems.append(f"transform {name!r} -> stats.{spec.stat} is a BANNED forward-looking name")
        fn = getattr(st, spec.stat, None)
        if not callable(fn):
            problems.append(f"transform {name!r} names stats.{spec.stat}, which does not exist")
            continue
        sig = inspect.signature(fn)
        pos = [p.name for p in sig.parameters.values()
               if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        args = [a for a, _ in spec.inputs]
        # THE INPUTS ARE THE CALLEE'S LEADING POSITIONAL PARAMETERS, BY NAME. Arity alone would pass a
        # spec whose two arrays were wired to the wrong two legs; names are what actually bind, and a
        # renamed stats parameter must red HERE rather than silently subtract the wrong pair.
        if pos[:len(args)] != args:
            problems.append(f"transform {name!r} inputs {args} are not stats.{spec.stat}'s leading "
                            f"positional parameters {pos[:len(args)]}")
        for arg, sel in spec.inputs:
            if sel not in SELECTORS:
                problems.append(f"transform {name!r} input {arg!r} names selector {sel!r}")
        for p in sig.parameters.values():          # every REQUIRED parameter is an input or declared
            if p.name in args or p.default is not p.empty or p.kind is p.VAR_KEYWORD:
                continue
            if p.name not in spec.params:
                problems.append(f"stats.{spec.stat} requires {p.name!r}, which transform {name!r} "
                                f"neither wires as an input nor declares as a parameter")
        for p in spec.params:                                                # clause 2's half: declared
            if p not in sig.parameters and p != spec.window_param:
                problems.append(f"transform {name!r} declares parameter {p!r}, which stats.{spec.stat} "
                                f"does not take and which is not its render-only window label")
        if spec.window_param and spec.window_param not in spec.params:
            problems.append(f"transform {name!r} names window_param {spec.window_param!r}, which is not "
                            f"among its declared parameters")
    frozen = tuple(sorted(FROZEN_STAT_REGISTRY))                             # clause 4
    if tuple(sorted(st.STAT_REGISTRY)) != frozen:
        problems.append(f"stats.STAT_REGISTRY moved: {sorted(st.STAT_REGISTRY)} != {list(frozen)} -- the "
                        f"agent's tool enum is not this registry's to widen (AM-3)")
    return problems
