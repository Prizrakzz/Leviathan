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
# THE NULL BOUNDARY -- one pair of coercions, applied where an ARRAY IS BUILT and nowhere else
# ---------------------------------------------------------------------------------------------------
#: THE SHAPES A NULL CELL ARRIVES IN. ``numbers/pgnumbers._stringify`` renders a NULL as the EMPTY
#: STRING on purpose -- "Athena's GetQueryResults renders NULL as '' (VarCharValue absent) -- match it"
#: (pgnumbers.py:35) -- so every value and every date a served row carries can be ``""``. The other
#: members are what the same cell looks like once something has already stringified it: ``str(None)``
#: is ``"None"`` and a NaN prints as ``"nan"``. This set is the whole vocabulary of "no reading"; a
#: string that is not in it and does not parse as a number is a DEFECT rather than a null, and
#: :func:`num_or_none` returns ``None`` for it too because a board may not invent a figure either way.
NULL_TOKENS: frozenset = frozenset({"", "none", "nan", "null", "na", "n/a", "-", "--"})


def is_null_token(v) -> bool:
    """Whether ``v`` is one of the shapes a NULL cell reaches this package in."""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip().lower() in NULL_TOKENS
    if isinstance(v, float):
        return v != v                                   # NaN, without importing math for one line
    return False


def num_or_none(v) -> Optional[float]:
    """A served cell as a FLOAT, or ``None`` when it carries no reading.

    THE ONE PLACE A BLANK BECOMES A HOLE. ``stats._floats`` raises TypeError on a ``None`` and
    ``float("")`` raises ValueError, so a blank cell that reaches an array reaches a raise -- which is
    exactly what the in-VPC S4 census measured (140 of 144 board runs). The fix is not a try/except at
    each of the twenty-odd parse sites; it is that an array is BUILT through this function, so the
    arrays the transforms and the analog selector read are numeric by construction.

    A HOLE IS NEVER A ZERO. This returns ``None`` and the caller DROPS the observation (the same thing
    ``numbers.cascade._pace_series`` already does on the served path -- cited by FUNCTION, because that
    file is held by another lane and a line number is a citation that rots); substituting ``0.0`` would
    move a mean, a z and a percentile by a number nobody read off a card."""
    if is_null_token(v):
        return None
    if isinstance(v, bool):
        return None                                     # a flag column is not a reading
    try:
        f = float(v if not isinstance(v, str) else v.strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


#: The three ways a served cell can fail to be a reading, kept APART because they are three different
#: facts about the source. ``null`` is an absence the source DECLARED; ``unparseable`` is a DEFECT (a
#: stray unit suffix, a footnote marker, a thousands separator this function does not eat); ``bool`` is
#: a FLAG column served as ``True``/``False``, which is not a reading at all.
DROP_KINDS: tuple = ("null", "unparseable", "bool")


def cell_kind(v) -> str:
    """Which of :data:`DROP_KINDS` a served cell is, or ``"reading"``.

    WHY THE THREE ARE NOT ONE COUNT. :func:`num_or_none` returns ``None`` for all three and the ARRAY
    is right either way -- a hole is a hole. The LEDGER is not: a systematically malformed column
    (``"1,234 MT"``, ``"n.a.(p)"``) drops every observation and would report under a key whose word is
    ``null``, so a BROKEN read reads as a SPARSE one and nobody can raise the defect; and a flag column
    served as ``True``/``False`` would report as an empty read rather than as the 1/0 series it is. A
    count that cannot tell an absence from a defect cannot raise the defect, so this names which.

    Nothing on the estate serves a Python bool today (flag cards carry 0/1 and ``pgnumbers`` stringifies
    every cell), which is exactly why the hole would be silent if one ever did."""
    if is_null_token(v):
        return "null"
    if isinstance(v, bool):
        return "bool"
    return "reading" if num_or_none(v) is not None else "unparseable"


def date_or_none(v) -> Optional[str]:
    """A served period label as a STRING, or ``None`` when the row carries no date.

    ``feeders._period_dates`` used to write ``""`` for an unplaceable label and its own docstring gave
    the reason ("a blank date on a rendered row is visible, and a plausible wrong one is not"). The
    reason still holds and the VALUE changes: ``None`` is the absence every consumer in this package
    already tests for, while ``""`` is a string that reaches ``int(iso[0:4])`` and raises. The label is
    NOT parsed here -- ``analogs.axis_date`` owns the calendar and this function owns the null."""
    if is_null_token(v):
        return None
    s = v if isinstance(v, str) else str(v)
    s = s.strip()
    return s or None


def align_axis(values, dates) -> list:
    """The period axis made PARALLEL to ``values`` -- ONE alignment rule, stated once, for both builders.

    THERE WERE TWO. ``feeders._period_dates`` trimmed a too-long label axis from the FRONT
    (``out[-len(values):]``) while :func:`clean_pairs` truncated one from the END (it indexed
    ``ds[i]`` for ``i < len(vs)``), and the two therefore disagreed about which observation a surplus
    label belongs to. Unreachable on the served path -- ``_period_dates`` normalises before
    ``clean_pairs`` ever sees the pair -- and a disagreement about which end is the safe one is still
    a disagreement, so both callers now take this function and there is one rule to read.

    THE RULE, AND WHY THE TWO CASES ACT ON DIFFERENT ENDS.
      * TOO FEW LABELS: pad at the BACK with ``None``. A label the builder could not mint cannot be
        invented, and the nulls land where the axis ran out rather than shifting every value one
        period along -- ``_period_dates``' own measured defect (110 of 118 observations relabelled by
        ONE blank cell) is exactly the shift this refuses.
      * TOO MANY LABELS: drop from the FRONT. Surplus labels are labels the collapse did not use, and
        the newest observation is the one the row PRINTS (``level`` / ``level_date`` are ``[-1]``), so
        the end that must keep its own label is the newest one.
    Neither case guesses: nothing is renamed, only appended or dropped."""
    vs = list(values or [])
    ds = list(dates or [])
    if len(ds) == len(vs):
        return ds
    if len(ds) < len(vs):
        return ds + [None] * (len(vs) - len(ds))
    return ds[len(ds) - len(vs):]


def clean_pairs(values, dates) -> tuple:
    """``(values, dates, n_dropped)`` -- one numeric array and its period axis, built together.

    THE PAIR IS THE UNIT, and that is the whole point of doing this once instead of per call site: an
    array cleaned without its axis is an array whose dates no longer say what its values are values
    OF. A position whose VALUE is null is dropped (the transforms cannot hold a hole -- ``_floats``
    raises on one); a position whose DATE is null KEEPS its value and carries ``None`` as its label,
    because the reading is real and only its placement is missing.

    The two axes are made parallel by :func:`align_axis` first and the missing labels are ``None``, so
    a date axis shorter than the values (``_period_dates``' own pad case) never shifts a value onto
    another period's date.

    ``n_dropped`` is the TOTAL of the three drop kinds; :func:`clean_pairs_counted` returns the same
    two arrays with the breakdown, and the callers that keep a coverage ledger take that one."""
    vs, ds, counts = clean_pairs_counted(values, dates)
    return vs, ds, sum(counts[k] for k in DROP_KINDS)


def clean_pairs_counted(values, dates) -> tuple:
    """:func:`clean_pairs` with the drop LEDGER: ``(values, dates, counts)``.

    ``counts`` carries one key per :data:`DROP_KINDS` entry plus ``undated`` (positions that KEPT their
    reading and lost only their label). :func:`cell_kind` says why an absence, a defect and a flag are
    three counts rather than one."""
    vs = list(values or [])
    ds = align_axis(vs, dates)
    out_v: list = []
    out_d: list = []
    counts = {k: 0 for k in DROP_KINDS}
    counts["undated"] = 0
    for i, raw in enumerate(vs):
        kind = cell_kind(raw)
        if kind != "reading":
            counts[kind] += 1
            continue
        out_v.append(num_or_none(raw))
        d = date_or_none(ds[i])
        if d is None:
            counts["undated"] += 1
        out_d.append(d)
    return out_v, out_d, counts


def dated_pairs(values, dates) -> tuple:
    """:func:`clean_pairs` plus the DATE side: a position with no label is dropped as well.

    THE TWO ARE DIFFERENT QUESTIONS AND THE CALLERS ARE DIFFERENT. A ROW keeps an undated observation
    -- the level is real, only its label is missing, and the row prints the level and says the date is
    absent. A HISTORY cannot: every consumer of an analog history places its positions on a calendar
    (the knowledge axis, the candidate's own closable window, the join between two cadences), and an
    observation that cannot be placed would be compared against dates it has no relation to. So the
    selectors take this one, and the row builders take :func:`clean_pairs`."""
    vs, ds, counts = dated_pairs_counted(values, dates)
    return vs, ds, sum(counts[k] for k in DROP_KINDS) + counts["undated"]


def dated_pairs_counted(values, dates) -> tuple:
    """:func:`dated_pairs` with the drop LEDGER: ``(values, dates, counts)``.

    ``undated`` here counts positions this function DROPPED for having no label -- the same word the
    row builder uses for positions it KEPT -- so the two ledgers say what each caller did with a hole
    rather than both saying 'a hole was seen'."""
    vs, ds, counts = clean_pairs_counted(values, dates)
    keep = [i for i, d in enumerate(ds) if d is not None]
    if len(keep) == len(ds):
        return vs, ds, counts
    return [vs[i] for i in keep], [ds[i] for i in keep], counts


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
