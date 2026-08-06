"""Event timeline — the Architecture-v2 layer-2 promise, derived free from the prop store.

The reasoner has 279K dated props but no EPISODE structure over them, so on temporal questions it
either fabricates dates or stays timid ("stays fully hypothetical" while the July-2021 frost sits in
our own corpus — the measured failure). This module clusters each slice's props into dated episodes
("frost@arabica: 1994-06..1994-08 (7 props), 2021-06..2021-08 (11 props)") once, offline, with zero
LLM spend and zero re-chunking; serving attaches a one-line episode list per grounded node.

POINT-IN-TIME BY CONSTRUCTION: the artifact stores each episode's PROP DATES, and serving recomputes
span/count from dates <= asof, dropping empty episodes — a future prop can never leak into a shown
count. Kill switch GRAPHRAG_TIMELINE=off; a missing/broken artifact renders nothing and breaks nothing.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os

from leviathan.graphrag import params as _pr

GAP_DAYS = int(_pr.get("serving.timeline.gap_days", 90))
MAX_PER_NODE = int(_pr.get("serving.timeline.max_per_node", 4))

# R3 / D-EI-8 (2026-08-01). THE CORROBORATION FLOOR: an episode must be built from at least this many
# DISTINCT PROP DATES -- distinct dated documents, not props (see cluster(): `ds = sorted({...})`) -- to
# be shown. Measured on the live 638,644-byte artifact: 2,070 of 3,735 episodes (55.4%) are single-date,
# and at 1.17-2.75 props/date a single-date episode is ONE dated document. N>=2 is therefore the
# threshold at which "episode" starts to mean corroborated; it costs 71 of 484 rendered lines (-14.7%)
# and is as-of invariant across all three deck cohorts. N>=3 was REJECTED on a collision, not on taste
# (it darkens coffee_rust_crop, cancelling the rust repair shipped in the same bundle); N>=5 takes 37.8%
# of rendered lines. Set to 0 or 1 to disable.
#
# THE FLOOR IS A READ-TIME KNOB, applied in episodes_for AFTER the PIT recount and never in derive() /
# write_artifact (R3.5): `n` is as-of dependent, so a build-time floor would cut on pre-as-of counts and
# drift with every asof; and keeping the artifact COMPLETE lets the threshold be lowered without a
# rebuild.
MIN_PROPS = int(_pr.get("serving.timeline.min_props", 2))
_ARTIFACT = "timeline/episodes.json"
_CACHE: dict | None = None
_LOG = logging.getLogger(__name__)

# FENCE 2 (incident I-2, 2026-07-31). The artifact envelope version. schema 2 wraps the bare
# {node: [episodes]} map in {"schema": 2, "stamp": {...}, "episodes": {...}} so the artifact CARRIES
# the identity of the store it was derived from. A schema-1 (bare-dict) artifact still SERVES -- no
# serving regression -- but it reports state "legacy" and FAILS check_artifact, because an artifact
# with no stamp cannot prove it still describes the prop store, which is exactly the I-2 hole.
_SCHEMA = 2

# The machine-readable outcome of the LAST artifact read in this process. Serving never raises on a
# dead artifact (see _load), so this status + the fixed log tokens below ARE the observability: the
# eval harness, the CLI check and a CloudWatch log-metric-filter all read one of the two.
#   state: "unread" | "ok" | "legacy" | "absent" | "unreadable"
_STATUS: dict = {"state": "unread", "source": None, "err": None, "stamp": None, "n_nodes": 0}

# Fixed grep tokens. ASCII, no formatting drift, one token per condition -- so a log-metric-filter
# can be hung off the serving log group the same way
# infra/terraform/modules/silver_observability/main.tf:167 does it for Batch failures.
_TOK_DEAD = "TIMELINE_ARTIFACT_DEAD"
_TOK_UNSTAMPED = "TIMELINE_ARTIFACT_UNSTAMPED"

# R7.1 (2026-08-04) -- THE FINGERPRINT-COMPARE TOKENS, and the law they keep alive.
#
# THE LAW: ONE rebuild = ONE full deck re-probe. Every deck "# PROBE" note is an assertion about the
# episodes the artifact carried when the probe ran; when the episodes MOVE, those notes are stale and
# a human must re-probe. R7b puts the rebuild on a weekly cron, and that is exactly what would have
# retired the law silently: build_stamp embeds `built_at`, so a naive weekly `--run` rewrites the
# artifact's BYTES every Sunday even when the episode CONTENT is byte-identical. Bytes-moved would
# then stop meaning content-moved, "every rebuild needs a re-probe" would fire 52 times a year on
# nothing, and a signal that fires on nothing is a signal that gets ignored -- which is how the law
# dies without anyone deciding to kill it.
#
# THE COMPARE IS ON `stamp.fingerprint`, WHICH IS CONTENT-ONLY BY CONSTRUCTION: build_stamp hashes
# `json.dumps(episodes, sort_keys=True)` and NOTHING else -- not built_at, not the counts, not the
# knobs. sort_keys makes it order-invariant, so a dict-iteration reshuffle in derive() cannot forge a
# change. If that hash ever grows a non-content input, `--run-if-changed` silently degrades to
# `--run` and this whole leg is theatre; test_r7_fingerprint_excludes_built_at pins it.
#
# UNKNOWN IS NEVER "UNCHANGED". A legacy/absent/unreadable artifact carries no fingerprint to compare
# against, so it is treated as CHANGED: it writes and it demands a re-probe. Same fail-closed posture
# as check_artifact -- "could not measure" is not evidence of sameness.
_TOK_UNCHANGED = "TIMELINE_UNCHANGED_SKIP"
_TOK_REPROBE = "TIMELINE_REBUILT_REPROBE_REQUIRED"

# W4 / skeptic F-I. The marker rendered IN PLACE of a receipt for an episode the retrieved top-K
# carried no in-window prop for. It is the whole F-I mitigation: the episode is NOT dropped (its `n`
# is a PIT recount of real prop dates, so dropping would make the corpus look THINNER than it is and
# would silently delete exactly the old/thin/single-source episodes W4's honesty leg exists to
# enumerate), it is STATED. Absence stated beats absence hidden. The wording is deliberately an
# instruction, not a label -- it is the last thing the reasoner reads about that episode.
_NO_RECEIPT = "NO CITABLE ITEM IN THIS WINDOW -- state that and do not narrate what happened"

# W4-D3 fix (verifier blocker 2, 2026-07-31). The marker that opens every injected episode line. It is
# PUBLIC because answer.py gates the '## Episodes' persona paragraph on the PRESENCE OF THIS STRING IN
# THE ASSEMBLED VOLATILE PROMPT -- not on the kill-switch alone. The flag being "on" does NOT imply a
# line was injected: _load() fails open to {} on a missing/unreadable artifact, episodes_for() returns
# [] with no asof, and the one-hop body has no episode producer at all. In every one of those states a
# flag-only gate ships a paragraph demanding a section the prompt carries no episodes for, which is the
# +10-hallucination mode the layer was defaulted off for. One constant, one spelling, both sides.
LINE_PREFIX = "DATED EPISODES for "


def _parse(d) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return None


def cluster(dates: list, gap_days: int = GAP_DAYS) -> list[dict]:
    """Sorted date strings -> episodes split where consecutive props are > gap_days apart."""
    ds = sorted({d for d in (_parse(x) for x in dates) if d})
    episodes, cur = [], []
    for d in ds:
        if cur and (d - cur[-1]).days > gap_days:
            episodes.append(cur)
            cur = []
        cur.append(d)
    if cur:
        episodes.append(cur)
    return [{"start": e[0].isoformat(), "end": e[-1].isoformat(),
             "dates": [x.isoformat() for x in e]} for e in episodes]


def derive(*, conn=None, query_fn=None) -> dict:
    """Build {slice: [episodes]} for EVERY slice in the prop store — one SQL over pg (S3 flat is the
    fallback path via evidence.load_index, but pg holds the same 279K props and answers in seconds).
    Uses event_date when the chunker recovered one (WHEN it happened), else the doc date."""
    rows = None
    if query_fn is not None:
        rows = query_fn("SELECT node, COALESCE(CAST(event_date AS varchar), CAST(date AS varchar)) AS d "
                        "FROM evidence_props")
    else:
        from leviathan.graphrag import pgstore as pg
        c = conn or pg.connect()
        with c.cursor() as cur:
            cur.execute("SELECT node, COALESCE(event_date, date) FROM evidence_props")
            rows = [{"node": r[0], "d": r[1]} for r in cur.fetchall()]
    by_node: dict[str, list] = {}
    for r in rows:
        by_node.setdefault(r["node"], []).append(r["d"])
    return {node: cluster(dates) for node, dates in sorted(by_node.items())}


def build_stamp(episodes: dict, *, now: _dt.datetime | None = None) -> dict:
    """The build stamp written INTO the artifact -- the identity of the store it was derived from.

    ``n_prop_dates`` is computed FROM THE EPISODES, not from the SQL row count, and that is
    deliberate: :func:`cluster` de-duplicates and drops unparseable dates, so this is the count of
    distinct (node, date) pairs the artifact ACTUALLY encodes -- recomputable from the artifact alone,
    with no pg and no S3, which is what makes the stamp self-verifying rather than a claim.

    ``gap_days`` rides along as an I-1-class fence for free: if ``serving.timeline.gap_days`` is
    edited in params, the artifact's clustering silently stops matching what serving expects, and
    :func:`check_artifact` fails on the mismatch instead of serving episodes cut at the wrong gap.

    ``min_props`` and ``max_per_node`` join it under D-EI-8 (ratified 2026-08-01). Neither shapes the
    STORED bytes -- both are applied in :func:`episodes_for` at read time -- so unlike ``gap_days``
    a mismatch cannot mean the artifact was cut wrong. What it CAN mean is the thing the fence is for:
    the artifact in front of you was written under a different rendering contract than the one serving
    now applies, so every count quoted about "what the reader sees" (the R3.2 calibration, a deck's
    ``min_episode_lines``, an A/B baseline) was measured against a different threshold. ``gap_days``
    is in the stamp precisely so a silent params edit FAILS :func:`check_artifact` rather than serving
    a surprise; a floor knob outside the stamp reopens that exact class for the new parameter, and
    ``max_per_node`` was already an existing, smaller instance of the same gap."""
    body = json.dumps(episodes, sort_keys=True)
    ts = (now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "built_at": ts,
        # derive() hardcodes `evidence_props` (timeline.py:72/78) rather than routing through
        # pgstore.table_name(), so a shadow-table run still derives from the LIVE table. Recorded
        # here rather than silently fixed -- fixing it is an adjacent lane's call.
        "source_table": "evidence_props",
        "gap_days": GAP_DAYS,
        "min_props": MIN_PROPS,
        "max_per_node": MAX_PER_NODE,
        "n_nodes": len(episodes),
        "n_episodes": sum(len(v) for v in episodes.values()),
        "n_prop_dates": sum(len(ep.get("dates") or [])
                            for eps in episodes.values() for ep in eps),
        "fingerprint": "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def write_artifact(episodes: dict) -> str:
    """Persist to the evidence store (s3://.../graphrag_evidence/timeline/episodes.json).

    Signature unchanged (it builds the stamp itself), so derive()'s return type and every existing
    caller/test are untouched. ONE PutObject carries both stamp and payload -- a sidecar meta.json
    was rejected because a torn two-object write leaves a stamp describing bytes that are no longer
    there, which is a worse lie than no stamp at all."""
    base = os.environ.get("EVIDENCE_S3", "")
    body = json.dumps({"schema": _SCHEMA, "stamp": build_stamp(episodes), "episodes": episodes})
    if base.startswith("s3://"):
        import boto3
        bucket, _, prefix = base[5:].partition("/")
        key = f"{prefix.rstrip('/')}/{_ARTIFACT}"
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
        return f"s3://{bucket}/{key}"
    path = os.path.join(base or ".", _ARTIFACT)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


_HEARTBEAT = "timeline/last_run.json"


def write_heartbeat(outcome: str, old_fp: str, new_fp: str, shape: str) -> str:
    """Record that a scheduled run HAPPENED, beside the artifact it audited.

    THE CALIBRATION GAP THIS CLOSES (the skip branch used to state it and leave it): the freshness
    poller reads max LastModified over ``graphrag_evidence/timeline/``, and a healthy
    ``--run-if-changed`` week writes NOTHING -- so stable episode content ages the measured signal
    past the 10-day SLA while the schedule is perfectly alive, and the R7c alarm becomes a false-alarm
    generator on quiet corpora. This object moves LastModified on EVERY successful run (skip or
    rebuild), which changes the measured semantic to 'the weekly run happened' -- the thing the
    alarm's basis string actually promises ('one missed run breaches'). A dead schedule stops the
    heartbeat and the age grows honestly. The artifact itself keeps the no-write guarantee the skip
    branch documents: built_at and bytes move ONLY on a content change.

    Lives INSIDE the polled prefix on purpose; it is not excluded by freshness._EXCLUDE_SEGMENTS
    (those fence off /_shadow/ /_staging/ /_backup/) nor by the _tasks.json suffix. Failure is
    non-fatal: a run that rebuilt the artifact already refreshed the signal, and a skipped run that
    cannot write the heartbeat should not turn a healthy week into exit 1."""
    body = json.dumps({
        "ran_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outcome": outcome, "old_fingerprint": old_fp, "new_fingerprint": new_fp, "shape": shape,
    })
    base = os.environ.get("EVIDENCE_S3", "")
    try:
        if base.startswith("s3://"):
            import boto3
            bucket, _, prefix = base[5:].partition("/")
            key = f"{prefix.rstrip('/')}/{_HEARTBEAT}"
            boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
            return f"s3://{bucket}/{key}"
        path = os.path.join(base or ".", _HEARTBEAT)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return path
    except Exception as exc:  # noqa: BLE001 -- see docstring: never fail a healthy run over the beat
        print(f"  heartbeat write FAILED ({_err_token(exc)}) -- freshness signal not refreshed")
        return ""


def _err_token(exc: BaseException) -> str:
    """Short ASCII token for the failure: the botocore error code when there is one, else the type."""
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        code = (resp.get("Error") or {}).get("Code")
        if code:
            return str(code)
    return type(exc).__name__


def _is_absent(exc: BaseException) -> bool:
    """True when the artifact is MISSING (vs present-but-unreadable). Both are fatal to the layer;
    they are distinguished because they have different remedies (rebuild vs investigate)."""
    if isinstance(exc, FileNotFoundError):
        return True
    if type(exc).__name__ in ("NoSuchKey", "NoSuchBucket"):
        return True
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        err = resp.get("Error") or {}
        if str(err.get("Code", "")) in ("NoSuchKey", "NoSuchBucket", "404", "NotFound"):
            return True
        if (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode") == 404:
            return True
    return False


def _unpack(raw, source: str) -> tuple[dict, dict]:
    """Envelope (schema 2) or legacy bare dict -> (episodes, status). Legacy still SERVES, loudly."""
    if raw.get("schema") == _SCHEMA and isinstance(raw.get("episodes"), dict):
        eps = raw["episodes"]
        return eps, {"state": "ok", "source": source, "err": None,
                     "stamp": raw.get("stamp"), "n_nodes": len(eps)}
    _LOG.warning(
        "%s state=legacy source=%s n_nodes=%d -- this artifact carries NO build stamp, so whether it "
        "still describes the prop store is UNKNOWABLE; rebuild with "
        "`python -m leviathan.graphrag.timeline --run`",
        _TOK_UNSTAMPED, source, len(raw))
    return raw, {"state": "legacy", "source": source, "err": None, "stamp": None, "n_nodes": len(raw)}


def _load() -> dict:
    """Read the artifact ONCE per process. NEVER raises -- see the tradeoff below.

    FENCE 2 leg 1 (incident I-2). This used to end in a bare `except Exception: _CACHE = {}`, so a
    MISSING or unreadable artifact was byte-indistinguishable from "this corpus has no episodes":
    flag on, zero episodes, exit 0, nobody told. It now CLASSIFIES the failure, records it in
    :data:`_STATUS`, and logs a fixed grep token at ERROR (dead) or WARNING (unstamped).

    IT STILL DOES NOT RAISE, and that is the deliberate tradeoff. This function's only serving call
    site is episodes_for() (below), which planner.ground() invokes in the sequential post-cap
    episode pass (planner.py:441-455, D-DV: episodes are stamped AFTER _dedup_and_cap) -- a raise
    there still kills the WHOLE TURN. Trading a correct answer (the layer is DEFAULT-OFF, experimental, and
    answer._episodes_on() already suppresses the '## Episodes' paragraph when no line was injected)
    for a 500, purely to be noticed, is a bad trade. Fail-CLOSED lives in check_artifact(), whose
    caller is a CLI/CI preflight where a hard stop costs nothing. Strictness is a property of the
    CALLER, not of the environment -- which is also why there is no GRAPHRAG_TIMELINE_STRICT knob
    (it could be mis-set INTO serving and would reintroduce exactly the raise this rejects).

    EVERY BYTE OF THIS IS UNREACHABLE WITH THE FLAG UNSET: episodes_for() returns at its
    GRAPHRAG_TIMELINE gate before _load() is ever called."""
    global _CACHE, _STATUS
    if _CACHE is None:
        source = "?"
        try:
            override = os.environ.get("GRAPHRAG_TIMELINE_PATH")
            base = os.environ.get("EVIDENCE_S3", "")
            if override:
                source = override
                raw = json.load(open(override, encoding="utf-8"))
            elif base.startswith("s3://"):
                import boto3
                bucket, _, prefix = base[5:].partition("/")
                key = f"{prefix.rstrip('/')}/{_ARTIFACT}"
                source = f"s3://{bucket}/{key}"
                obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
                raw = json.loads(obj["Body"].read())
            else:
                source = os.path.join(base or ".", _ARTIFACT)
                raw = json.load(open(source, encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"artifact root is {type(raw).__name__}, expected an object")
            _CACHE, _STATUS = _unpack(raw, source)
        except Exception as exc:  # noqa: BLE001 -- degrade, but SAY SO (never a broken answer)
            state = "absent" if _is_absent(exc) else "unreadable"
            _CACHE = {}
            _STATUS = {"state": state, "source": source, "err": _err_token(exc),
                       "stamp": None, "n_nodes": 0, "detail": str(exc)[:200]}
            _LOG.error(
                "%s state=%s source=%s err=%s flag=%s -- this process will produce ZERO episodes; "
                "rebuild with `python -m leviathan.graphrag.timeline --run`",
                _TOK_DEAD, state, source, _STATUS["err"],
                os.environ.get("GRAPHRAG_TIMELINE", "off"))
    return _CACHE


def load_status() -> dict:
    """The last artifact read's outcome, as data rather than as an absence.

    THE MACHINE CONTRACT of fence 2 leg 1: a silently-dead layer and a correctly-quiet layer produce
    byte-identical OUTPUT, so no output-side assertion can tell them apart. An eval lane or a probe
    asserts on this instead of inferring a dead layer from an empty list."""
    return dict(_STATUS)


def reset_cache() -> None:
    global _CACHE, _STATUS
    _CACHE = None
    _STATUS = {"state": "unread", "source": None, "err": None, "stamp": None, "n_nodes": 0}


class _Episodes(list):
    """The episode list, plus the floor's suppression meta -- a `list` in every way that matters.

    WHY A SUBCLASS AND NOT A TUPLE RETURN. The floor's emitter (R3.4) needs `n_suppressed` at
    `answer._l2_blocks`, but the ONLY production producer of episodes is the post-cap episode
    pass in `planner.ground` (planner.py:441-455, `n.episodes = tl.episodes_for(...)`; moved out
    of `_fill` by D-DV so receipts are stamped against POST-cap evidence) and the only consumer
    is answer.py -- two
    files with an unowned intermediary between them (`GroundedNode.episodes`, planner.py:76) that
    would otherwise have to grow a parallel field to carry the count. Riding the returned list keeps
    the meta ATTACHED TO THE EPISODES IT DESCRIBES rather than beside them, so the two cannot drift.

    It is a `list`: `== []` holds, `bool()` is falsy when empty, `json.dumps` serialises it, slicing
    and `list(x)` degrade to a plain list. Every existing call site is byte-identical. A caller that
    wants the meta EXPLICITLY passes `with_meta=True` and gets `(episodes, meta)`; a caller handed an
    arbitrary list asks :func:`suppression`, which answers None for a list nothing floored.
    """
    __slots__ = ("meta",)


def suppression(eps) -> dict | None:
    """The floor meta ``{n_rendered, n_suppressed, floor}`` for an episode list, or None.

    None means "this list did not come from :func:`episodes_for`" (a hand-built fixture, a future
    producer), NOT "nothing was suppressed" -- those are different facts and the emitter must not
    conflate them: the first has no suppression to report, the second reports zero."""
    m = getattr(eps, "meta", None)
    return dict(m) if isinstance(m, dict) else None


def episodes_for(node: str, asof, *, max_n: int = MAX_PER_NODE, evidence: list | None = None,
                 min_props: int | None = None, with_meta: bool = False):
    """PIT-filtered episodes for a slice: recount from prop dates <= asof, drop empty, biggest first.
    No asof -> nothing (an undated 'now' cannot anchor a timeline honestly).

    DEFAULT OFF (measured 2026-07-04: episode COUNTS without content invited uncited confabulation —
    the reasoner narrated "what happened" in an episode it had no text for; +10 halluc on 19 turns
    while citation-integrity strips stayed flat). Set GRAPHRAG_TIMELINE=on to enable the RECEIPTED
    path: `evidence` (the dated props ground() already fetched for this node) supplies one in-window
    prop per episode as a citable RECEIPT, so the reasoner has text to cite instead of invent.

    THE RECEIPT IS BEST-EFFORT, AND IT FAILS ASYMMETRICALLY (skeptic F-I, 2026-07-29). `evidence` is a
    semantic top-K over the QUERY, so the episodes least likely to contain an in-window prop are the
    old, thin, single-source ones -- Brazil frost 1994 (11 props, wb_cmo_outlook only), USSR 1972-79
    (33), grain-deal suspension 2023 (14). Those are precisely the episodes W4's honesty leg is built
    around, and a counted-but-unreceipted episode IS the original +10-hallucination mode rather than
    the fix for it. MITIGATION CHOSEN: state the absence (`_NO_RECEIPT` in render_line), do NOT drop
    the episode. Dropping was rejected because `n` is a PIT RECOUNT of real prop dates, not a
    retrieval result -- a receipt-less 1994 frost would vanish from the count and the answer's own
    "the record holds N episodes" headline would understate the corpus it is meant to be honest
    about. Every emitted episode therefore carries a receipt OR a rendered statement that it has
    none; nothing is emitted silently.

    THE CORROBORATION FLOOR (R3, ratified D-EI-8). An episode recounted to fewer than ``min_props``
    DISTINCT PROP DATES (default :data:`MIN_PROPS`) is dropped here -- after the PIT recount, so the
    threshold is applied to the count the reader would actually have been shown, and before ``max_n``,
    so a suppressed window does not consume one of the four rendered slots. The floor runs at READ
    time and never at build time: `n` is as-of dependent, and a complete artifact lets the threshold
    move without a rebuild (R3.5).

    A DROPPED EPISODE IS NOT A SILENT ONE. `n_suppressed` rides back on the returned list (see
    :class:`_Episodes` / :func:`suppression`, or pass ``with_meta=True`` for an explicit
    ``(episodes, meta)`` pair) precisely because a floor with no emitter is absence HIDDEN -- a
    fully-floored node would inject nothing at all and be byte-identical to a dead artifact for that
    node, which is exactly the incident I-2 indistinguishability the fences were built to kill.
    answer._l2_blocks turns the count into a stated line (fully floored) or a stated suffix (partially
    floored); see :func:`floored_line` and :func:`floor_suffix`."""
    floor = MIN_PROPS if min_props is None else int(min_props)

    def _done(eps: list, n_suppressed: int):
        out = _Episodes(eps)
        out.meta = {"n_rendered": len(out), "n_suppressed": int(n_suppressed), "floor": floor}
        return (out, dict(out.meta)) if with_meta else out

    if os.environ.get("GRAPHRAG_TIMELINE", "off") != "on":
        return _done([], 0)
    asof_d = _parse(asof)
    if asof_d is None:
        return _done([], 0)
    ev_by_date = sorted(((str(h.get("date") or "")[:10], (h.get("text") or "")) for h in (evidence or [])
                         if _parse(h.get("date"))), key=lambda x: x[0])
    out = []
    for ep in _load().get(node) or []:
        vis = [d for d in ep.get("dates") or [] if (_parse(d) or _dt.date.max) <= asof_d]
        if not vis:
            continue
        start, end = vis[0], vis[-1]
        receipt = None                                             # newest evidence prop inside [start, end]
        for d, txt in ev_by_date:
            if start <= d <= end and txt:
                receipt = {"date": d, "text": txt[:180]}
        out.append({"start": start, "end": end, "n": len(vis), "receipt": receipt})
    n_suppressed = 0
    if floor > 1:                                                  # 0 and 1 are the DISABLED settings:
        kept = [e for e in out if e["n"] >= floor]                 # every surviving episode has n >= 1
        n_suppressed = len(out) - len(kept)
        out = kept
    out.sort(key=lambda e: -e["n"])
    # n_suppressed counts what THE FLOOR took, never what `max_n` truncated -- the emitter's sentence
    # says "below the corroboration floor", and a count that quietly folded in the max_per_node tail
    # would make that sentence false for the 5th-biggest window of a node that has six.
    return _done(out[:max_n], n_suppressed)


def month_span(e: dict) -> str:
    """The `YYYY-MM..YYYY-MM` token for an episode -- ITS LABEL, NEVER AN INTERVAL (OUTCOMES_JOIN
    D-OJ-16).

    ONE definition, three readers, and the reason it is one: `render_line` shows this string to the
    model, `answer._l2_blocks` stamps the same string into `trace['episodes_injected']['spans']`, and
    `eval._line_targets` matches a rendered bullet to an injected episode by ENDPOINT STRING EQUALITY on
    exactly these tokens. Three copies of an f-string is how those three drift apart, and a drift here
    reds `episode_magnitude_or_absence` and `min_episode_lines` together on correctly enumerated prose.

    WHAT IT IS NOT. It is not a window to measure over. Expanding the `[:7]` end token to month-end
    prices up to 30 days past the as-of, and `episodes_for` has already clamped the DAY-GRAIN `end` to
    `<= asof` -- so the day-grain pair is the measurable window and this token is the label pinned
    beside it. Any consumer that measures a price move over an episode reads `e['start']` / `e['end']`,
    never this."""
    return f"{str(e.get('start') or '')[:7]}..{str(e.get('end') or '')[:7]}"


def day_window(e: dict) -> tuple[str, str]:
    """The DAY-GRAIN `(start, end)` an episode was recounted over -- the pair a magnitude is measured on.

    Already as-of clamped at source (`episodes_for` keeps only prop dates `<= asof`, so `end` can never
    postdate the as-of); the outcomes clamp still applies its own `+ survive_days` margin on top, because
    a window whose end is inside that margin was selected against tape the reader does not have."""
    return str(e.get("start") or "")[:10], str(e.get("end") or "")[:10]


def _head(label: str) -> str:
    """The opening of EVERY episode line, floored or not -- one spelling, so the `## Episodes` gate
    (`answer._episodes_on`: LINE_PREFIX in the assembled volatile prompt) sees the same marker on both."""
    return LINE_PREFIX + label + " (report TIMESTAMPS, not descriptions): "


def render_line(label: str, eps: list[dict]) -> str:
    """One prompt line per node. Every episode renders EITHER its citable receipt OR `_NO_RECEIPT` --
    a bare count is never emitted (F-I: the bare count with no marker was the confabulation invitation).

    R3.1 -- THE NOUN. `e['n']` is DISTINCT PROP DATES, not props and not reports: cluster() builds each
    episode from `sorted({...})` over the dates, so `n` counts dated DOCUMENTS. This line used to print
    "(3 reports)", which is a different quantity (measured 1.17-2.75 props per date across seven live
    driver slices), and the floor is a threshold ON THIS NUMBER -- so a wrong noun here would have the
    prompt and the threshold disagreeing about what was counted. "report dates" is used invariantly for
    every n: one string, no pluralisation branch to drift."""
    parts = []
    for e in eps:
        span = f"{month_span(e)} ({e['n']} report dates"
        r = e.get("receipt")
        span += f'; e.g. {r["date"]}: "{r["text"]}")' if r else f"; {_NO_RECEIPT})"
        parts.append(span)
    return _head(label) + ", ".join(parts)


# R3.4 leg 2 -- PARTIAL suppression. The node's block already renders, so the suppression fact is a
# string append at the same seam: zero new gate, zero new paragraph. It is the LARGER half of the floor's
# cost (measured at N>=2 on the live artifact: 8 nodes go fully dark, but 22 more fall from 4 rendered
# lines to 1-3 with no marker of any kind -- including black_sea_corridor, the slice behind six deck rows).
# R6 fold (2026-08-04, adjudicated finding): the old trailing imperative -- "do not enumerate or
# narrate them" -- rode 116 of 125 injected lines and read as a SECTION-level ban: five deck rows
# with live dated windows omitted '## Episodes' entirely (artifact exonerated on all five; P12
# enumerated its windows correctly in prose in the wrong section). The suffix now bans ONLY the
# hidden windows and re-affirms the shown ones in the same breath, so no line can be read as
# permission to skip the section it appears in.
_FLOOR_SUFFIX = ("; {n} further window(s) below the corroboration floor of {floor} report dates and "
                 "NOT shown -- never name or count those hidden windows, and still render every "
                 "window shown on this line as its own bullet")

# R3.4 leg 1 -- FULL suppression. Carries LINE_PREFIX so the '## Episodes' persona gate still fires and
# the reader is told the windows were THIN rather than absent. Phrased as an instruction, not a label,
# for the same reason _NO_RECEIPT is: it is the last thing the reasoner reads about this node.
_FLOOR_ABSENCE = ("every dated window for this node -- {n} of them -- fell below the corroboration floor "
                  "of {floor} report dates, so NONE is shown. The record here is thin and uncorroborated: "
                  "say so plainly. This line carries NO window, so write no bullet for it, and never "
                  "narrate or date an episode for this node.")


def floor_suffix(n_suppressed: int, floor: int = MIN_PROPS) -> str:
    """The suffix appended to a PARTIALLY floored node's existing episode line."""
    return _FLOOR_SUFFIX.format(n=int(n_suppressed), floor=int(floor))


def floored_line(label: str, n_suppressed: int, floor: int = MIN_PROPS) -> str:
    """The whole prompt line for a FULLY floored node -- the one that had windows and shows none."""
    return _head(label) + _FLOOR_ABSENCE.format(n=int(n_suppressed), floor=int(floor))


def check_artifact(*, stamp: dict | None = None, state: str | None = None,
                   live_prop_dates: int | None = None, live_nodes: int | None = None,
                   age_sla_days: float = 10.0, drift_ceiling: float = 0.05,
                   now: _dt.datetime | None = None) -> dict:
    """FENCE 2 leg 2, the FAIL-CLOSED half: does this artifact still describe the store it came from?

    Four legs, worst-first in importance:
      L-a  STAMP     -- an unstamped (legacy) artifact FAILS. Not "probably fine": unknowable.
      L-b  AGE       -- built_at older than ``age_sla_days``. The LIVENESS backstop ("is anything
                        still building this?"), deliberately NOT the primary leg.
      L-c  KNOBS     -- gap_days / min_props / max_per_node: the artifact was clustered, or is being
                        rendered, under a different contract than serving now expects. A MISSING key
                        on a schema-2 stamp fails identically to a mismatched one.
      L-d  DRIFT     -- |live - stamped| / stamped over ``drift_ceiling``, on n_prop_dates AND
                        n_nodes. THE PRIMARY LEG. Incident I-2 was 74% CONTENT growth against a
                        clock that a generous SLA would have called fine (27.4d vs a 30d SLA), and
                        an artifact rewritten byte-identically would look fresh forever while the
                        store underneath doubled. Age cannot see that; drift can.

    Pure + injectable (both live counts are passed in) so it is unit-testable with no pg and no S3.
    NEVER raises -- it returns a verdict; the CLI turns a False into rc=2.

    A MISSING live count is a FAIL, not a skip: "could not measure the store" is not evidence of
    freshness, and a check that quietly passes when its input is absent is the fail-open shape this
    whole fence exists to delete. Ceiling 5% (not exact equality): the prop store grows continuously,
    a gate that fires every day gets muted, and muted is how a fence becomes coverage theatre. 5% is
    ~15x below the incident and its remedy is one command."""
    legs: list[dict] = []
    reasons: list[str] = []

    def _leg(name: str, ok: bool, detail: str) -> None:
        legs.append({"leg": name, "ok": ok, "detail": detail})
        if not ok:
            reasons.append(detail)

    if stamp is None and state is None:                    # not injected -> read the real artifact
        _load()
        st = load_status()
        stamp, state = st.get("stamp"), st.get("state")

    if not isinstance(stamp, dict) or not stamp:
        why = ("the artifact could NOT BE READ at all"
               if state in ("absent", "unreadable")
               else "this artifact predates the stamp fence")
        _leg("stamp", False,
             f"no build stamp (state={state or 'legacy'}) -- {why}, so the store it was derived "
             "from is unknowable; it MUST be treated as stale")
        return {"ok": False, "legs": legs, "reasons": reasons, "stamp": None, "state": state}

    now = now or _dt.datetime.now(_dt.timezone.utc)
    built_raw = str(stamp.get("built_at") or "")
    try:
        built = _dt.datetime.strptime(built_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        built = None
    if built is None:
        _leg("age", False, f"unparseable built_at {built_raw!r} -- the stamp is corrupt")
    else:
        age = (now - built).total_seconds() / 86400.0
        _leg("age", age <= age_sla_days,
             f"built_at {built_raw}  age {age:.1f}d  SLA {age_sla_days:.1f}d")

    # L-c, all three render/cluster knobs. D-EI-8: min_props and max_per_node are asserted THE SAME WAY
    # gap_days is, and a schema-2 stamp MISSING either fails exactly like a mismatch -- there is no
    # back-compat shim, because no schema-2 artifact has been written in production yet, so a tolerated
    # absence would only ever mean "written by a build that predates this fence", which is the unknowable
    # state leg L-a already refuses. A legacy (schema-1) artifact never reaches here: it fails at L-a.
    for field, expect in (("gap_days", GAP_DAYS), ("min_props", MIN_PROPS),
                          ("max_per_node", MAX_PER_NODE)):
        got = stamp.get(field)
        _leg(field, got == expect,
             f"stamp {field} {got} vs serving {field.upper()} {expect}")

    for field, live in (("n_prop_dates", live_prop_dates), ("n_nodes", live_nodes)):
        stamped = stamp.get(field)
        if not isinstance(stamped, int):
            _leg(f"drift:{field}", False, f"stamp carries no {field}")
            continue
        if live is None:
            _leg(f"drift:{field}", False,
                 f"live {field} unavailable -- the store could not be measured, so drift is unknown")
            continue
        pct = 100.0 * (live - stamped) / float(max(stamped, 1))
        ok = abs(pct) <= drift_ceiling * 100.0
        _leg(f"drift:{field}",
             ok,
             f"{field} drift {pct:+.2f}% (stamped {stamped} | live {live}) "
             f"ceiling {drift_ceiling * 100.0:.2f}%")

    return {"ok": not reasons, "legs": legs, "reasons": reasons, "stamp": stamp, "state": state}


def live_counts(*, conn=None, query_fn=None) -> tuple[int, int]:
    """(distinct dated (node,date) pairs, distinct nodes) in the prop store derive() reads.

    Counts DISTINCT (node, date) rather than raw rows so it lines up with what cluster() actually
    encodes (cluster de-duplicates dates), which is what makes the drift comparison apples-to-apples."""
    sql = ("SELECT count(*), count(DISTINCT node) FROM ("
           "SELECT DISTINCT node, COALESCE(event_date, date) AS d FROM evidence_props) t "
           "WHERE d IS NOT NULL")
    if query_fn is not None:
        row = query_fn(sql)
    else:
        from leviathan.graphrag import pgstore as pg
        c = conn or pg.connect()
        with c.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
    return int(row[0]), int(row[1])


def _print_check(res: dict, source: str, live: tuple[int, int] | None) -> None:
    """ASCII-only report (Windows console is cp1252). Every failure prints its remedy verbatim."""
    print(f"=== timeline artifact check: {source} ===")
    print(f"  state           {res.get('state')}")
    if live is not None:
        print(f"  live store      {live[0]} dated (node,date) pairs across {live[1]} nodes")
    for leg in res["legs"]:
        print(f"  {leg['leg']:20s} {'ok    ' if leg['ok'] else 'BREACH'} {leg['detail']}")
    if res["ok"]:
        print("PASS the artifact is stamped, fresh, and still describes the store it was derived from.")
    else:
        print(f"FAIL {len(res['reasons'])} leg(s) breached:")
        for r in res["reasons"]:
            print(f"     - {r}")
        print("  rebuild: python -m leviathan.graphrag.timeline --run")


def _fingerprint_of(stamp) -> str:
    """The CONTENT fingerprint carried by a stamp, or "" when there is none to compare.

    "" is the UNKNOWN sentinel and it is never equal to a fresh fingerprint (which always starts
    "sha256:"), so an artifact that is legacy, absent or unreadable falls to the CHANGED branch by
    construction rather than by a branch someone has to remember to write."""
    if not isinstance(stamp, dict):
        return ""
    fp = stamp.get("fingerprint")
    return str(fp) if isinstance(fp, str) and fp else ""


def _run(args, *, only_if_changed: bool) -> int:
    """`--run` and `--run-if-changed` share EVERY step except the one that differs: whether an
    unchanged fingerprint suppresses the write.

    One function on purpose. The weekly (`--run-if-changed`) and hand-run (`--run`) paths must derive
    from the same SQL, stamp with the same builder and write the same bytes -- a forked implementation
    is how the scheduled path and the smoked path stop being the same configuration, which is the
    failure mode the jobdef's own comments are written around."""
    # Report the drift the OLD artifact had carried before overwriting it, so a rebuild says out loud
    # how far gone the thing it replaced was rather than erasing the evidence.
    reset_cache()
    _load()
    old = load_status()
    old_fp = _fingerprint_of(old.get("stamp"))
    eps = derive()
    fresh = build_stamp(eps)
    new_fp = str(fresh["fingerprint"])
    unchanged = bool(old_fp) and old_fp == new_fp
    shape = (f"n_nodes={fresh['n_nodes']} n_episodes={fresh['n_episodes']} "
             f"n_prop_dates={fresh['n_prop_dates']}")

    if only_if_changed and unchanged:
        # NO WRITE. Not "a cheap write", not "a write with the old built_at" -- none. The artifact in
        # S3 keeps its original built_at and its original bytes, so `bytes moved` continues to mean
        # `episodes moved`, which is the only reason the re-probe token below is worth acting on.
        print(f"{_TOK_UNCHANGED} old={old_fp} new={new_fp} {shape}")
        print("  episode CONTENT is identical to the live artifact; it was NOT rewritten and NO deck "
              "re-probe is required.")
        # The artifact's LastModified deliberately does NOT move on a skip -- but the freshness
        # poller must still see that the RUN happened, or stable content ages the signal into the
        # R7c alarm while the schedule is healthy. The heartbeat closes that gap (see its docstring).
        print("  artifact untouched; writing the run heartbeat so the freshness signal reflects "
              "schedule liveness, not content churn.")
        write_heartbeat(_TOK_UNCHANGED, old_fp, new_fp, shape)
        return 0

    pre = check_artifact(stamp=old.get("stamp"), state=old.get("state"),
                         live_prop_dates=fresh["n_prop_dates"], live_nodes=fresh["n_nodes"],
                         age_sla_days=args.age_sla_days, drift_ceiling=args.drift_ceiling)
    print("--- pre-rebuild state of the artifact being replaced ---")
    _print_check(pre, str(old.get("source")), (fresh["n_prop_dates"], fresh["n_nodes"]))
    reset_cache()
    dest = write_artifact(eps)
    print(f"derived {fresh['n_episodes']} episodes across {fresh['n_nodes']} slices "
          f"({fresh['n_prop_dates']} dated pairs) -> {dest}")
    if unchanged:
        # `--run` only: it rewrote the artifact (built_at moved) over identical episodes. Emitting the
        # re-probe token here would be a false alarm on a bytes-only change -- the precise conflation
        # this leg exists to prevent -- so it says what happened and names the mode that avoids it.
        print(f"  content UNCHANGED (fingerprint {new_fp}) -- bytes were rewritten anyway because "
              "this is --run; use --run-if-changed for the scheduled cadence. No re-probe.")
        return 0
    print(f"{_TOK_REPROBE} old={old_fp or 'none'} new={new_fp} {shape}")
    print("  episode CONTENT moved: every deck '# PROBE' note now describes an artifact that no "
          "longer exists. Re-probe the full deck before quoting any of them.")
    write_heartbeat(_TOK_REPROBE, old_fp, new_fp, shape)
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Derive the prop-store event timeline (free, no LLM)")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--run-if-changed", action="store_true",
                    help="THE SCHEDULED MODE: derive, compare the CONTENT fingerprint against the "
                         "live artifact's, and write ONLY when it moved -- so one rebuild still "
                         "means one deck re-probe")
    ap.add_argument("--check", action="store_true",
                    help="read-only: FAIL-CLOSED staleness/drift check of the live artifact (rc=2)")
    ap.add_argument("--age-sla-days", type=float, default=10.0)
    ap.add_argument("--drift-ceiling", type=float, default=0.05)
    args = ap.parse_args(argv)
    if not args.run and not args.check and not args.run_if_changed:
        print("dry: pass --run to derive + write the artifact, --run-if-changed to write only when "
              "the episode content moved, or --check to verify it")
        return 0
    from leviathan.common import config
    config.load_env()

    if args.check:
        reset_cache()
        _load()
        st = load_status()
        try:
            live = live_counts()
        except Exception as exc:  # noqa: BLE001 -- unmeasurable store => the drift legs FAIL (closed)
            print(f"  WARNING could not measure the prop store: {type(exc).__name__}: {str(exc)[:160]}")
            live = None
        res = check_artifact(stamp=st.get("stamp"), state=st.get("state"),
                             live_prop_dates=live[0] if live else None,
                             live_nodes=live[1] if live else None,
                             age_sla_days=args.age_sla_days, drift_ceiling=args.drift_ceiling)
        _print_check(res, str(st.get("source")), live)
        return 0 if res["ok"] else 2

    # --run-if-changed wins when both are passed: it is the strictly safer of the two (it can only
    # write LESS), so an ambiguous invocation degrades toward the law rather than away from it.
    return _run(args, only_if_changed=bool(args.run_if_changed))


if __name__ == "__main__":
    raise SystemExit(main())
