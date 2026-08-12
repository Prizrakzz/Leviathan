"""D-DR-1 -- the deep-research DOSSIER. A dossier is a JOB, not a turn.

WHAT IT IS. One authenticated question fans out into 5-12 grounded sub-questions, each of which runs
as a NORMAL turn through `orchestrator.respond` under ONE as-of stamped at submission (PIT by
construction). Each sub-answer contributes structured NOTES -- its sections plus its citation pairs.
ONE final synthesis pass composes the document from the NOTES ALONE and lands it as a frozen artifact.

THE SPINE LAW (D-DT item-2, absolute, and the reason this module is shaped the way it is): citations
travel forward as DATA -- (claim, prop_id/handle, as_of) tuples read off each turn's own citation list
and verifier report. NOTHING here re-discovers a span on assembled text. Concretely:
  * notes are built from `result["structured"]` FIELDS and `result["citations"]`, never from
    `result["answer"]` (the assembled body -- the exact surface D-DT item-2 forbids re-reading);
  * the local->global handle remap is a dictionary lookup over CARRIED pairs; a local handle with no
    carried pair is DROPPED rather than guessed;
  * the final verifier pass runs against the UNION evidence list, whose prop text we are HOLDING --
    that is verification with the props in hand, which is allowed, not re-discovery.

THE ENGINE SPLIT (D-CC-3 verdict, amended red branch -- provisional until D-DR-4's judged gate).
R1 measured that the composition mandates are WIDTH-HUNGRY: at quick's 12-row evidence they mandate
enumeration the evidence cannot back (strips/handle 0.1765 vs plain-quick 0.1073). Therefore:
  * quick sub-queries run PLAIN -- census forced OFF, not merely left to the flag;
  * width-hungry sub-queries run deep + contracts (the provisional width engine: pairwise-dominant on
    usefulness 13-2 at the best strip discipline ever measured);
  * the SYNTHESIS pass runs the document-scale composition contract, because it holds every
    sub-answer's notes at once -- width by construction, which is exactly where mandates are affordable.
The census is turned on/off PER CALL through `answer.composition_census_override`, a thread-scoped
ContextVar. Never an os.environ flip: the environment is process-global and a concurrent desk turn on
the same task would silently inherit the dossier's setting.

ROLLOUT PRECONDITION, STATED SO IT CANNOT BE FORGOTTEN (D-DR-5): the sub-queries REQUEST `quick` and
`deep`, and `orchestrator._modes_enabled()` (GRAPHRAG_MODES) still decides whether those requests are
HONORED. On a task where modes are off, every sub-query silently runs `standard` -- the dossier still
composes, but the engine split above is not in force. That is why the honored mode is read back off
each sub-answer and stamped into the sub-query trace in the artifact: a degraded engine is visible in
the delivered document, not inferred from a dashboard.

SEQUENTIAL BY LAW. Sub-queries run one at a time. The Cohere rerank quota is a HARD 3/min cap and the
D-DV chain lesson is explicit: never co-schedule rerank-heavy turns. Latency is the price; a
nondeterministic rerank starvation that changes ANSWERS is not. (The 3/min quota rationale is HISTORICAL
as of D-MW P1 -- the native cohere lane serves 1,000/min -- and the law is RETAINED FOR DETERMINISM until
the parallel-subquery gate: relaxing it is a THROUGHPUT change with its own blast radius (DB pool, census
ContextVar concurrency, wall-clock semantics), and it gets its own gate rather than riding a quota raise.
D-MW-12. Behavior here is unchanged.)

HONEST-PARTIAL. A sub-query failure records its error and the job continues; the dossier lands PARTIAL
with the gap declared in its own mandated section. A failure is never silent and never invisible.

v1 TRADEOFF, STATED (D-DR-1 scope): the job runs IN-PROCESS on a daemon thread and its state is
mirrored into the store after every stage transition, so GET/SSE work across requests on the same
task. A SERVER RESTART MID-JOB therefore orphans the job: the store still says planning/running but no
thread is alive. The next GET detects that (a non-terminal record with no live job) and lands it
FAILED with a refunded quota slot. It cannot RESUME -- resumption needs a durable queue, which is a
bigger decision than this wave funds. The failure is honest and the slot is given back, which is the
property that matters to the user.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass

# ── constants ───────────────────────────────────────────────────────────────────────────────────────
FLAG = "GRAPHRAG_DOSSIER"                 # absent -> every dossier route 404s (dark-first, D-DR-5)
ADMIN_FLAG = "GRAPHRAG_DOSSIER_ADMINS"    # comma-separated Cognito subs that bypass the monthly quota
KIND = "dossier"                          # per-user store collection: pk=user#<sub>, sk=dossier#<id>
ARTIFACT_KIND = "artifact"                # where the frozen result lands (the D-AM-15 seam)
QUOTA_LIMIT = 4                           # dossiers per user per UTC calendar month -- D-DR-2b (2026-08-08),
                                          # was 3 per ISO week (D-DR-2)
QUOTA_PREFIX = "dossier"

MIN_SUBQUERIES = 5
MAX_SUBQUERIES = 12
SYNTH_MAX_TOKENS = 16000     # document-scale synthesis cap; a turn's 6000 truncates a dossier
# D-DR-4 model call (2026-08-07, dual-synthesis from IDENTICAL notes, pairwise blind opus-4-8):
# opus-5 beat sonnet-4-6 on grounding 4-0-1, usefulness 3-2, composition 3-2, checklist
# 0.933 vs 0.867, strips/handle 0.41 vs 0.52 -- at ~$0.10/dossier extra. Sub-queries stay on
# the serving default; ONLY the document composition runs opus.
SYNTH_MODEL = "claude-opus-5"
WALL_CLOCK_S = 1200                       # ~20 min job cap (D-DR-1)
SUBCALL_TIMEOUT_S = 300                   # provider read-timeout per sub-call ONLY (D-DR-1)

PLANNING, RUNNING, SYNTHESIZING = "planning", "running", "synthesizing"
DONE, PARTIAL, FAILED = "done", "partial", "failed"
TERMINAL = frozenset({DONE, PARTIAL, FAILED})

# Sub-query lifecycle, as reported by GET /v1/dossier/{id}.
SQ_PENDING, SQ_RUNNING, SQ_OK, SQ_FAILED, SQ_SKIPPED = "pending", "running", "ok", "failed", "skipped"

_HANDLE_RX = re.compile(r"\[(?P<kind>[NE]?)(?P<idx>\d+)(?:[a-z])?\]")
_PROP_TEXT_CAP = 400                      # chars of prop text carried INTO the synthesis prompt
_RECEIPT_CAP = 140                        # chars kept on the artifact's carried pairs (the locator idiom)
_NOTE_BODY_CAP = 1600                     # chars per note section body in the prompt


# ── flag + allowlist ────────────────────────────────────────────────────────────────────────────────
def _flag_value() -> str:
    return os.environ.get(FLAG, "").strip().lower()


def enabled() -> bool:
    """Is the dossier surface live AT ALL? Absent/''/'off' -> False -> every route 404s. The grammar is
    `_response_contracts_enabled`'s: 'on'/'1'/'true' = everyone, anything else = a comma-separated
    ALLOWLIST of Cognito subs (the D-DR-5 'internal dossiers only' stage, no redeploy to widen)."""
    return _flag_value() not in ("", "off")


def allowed(sub: str | None) -> bool:
    """Is THIS principal inside the flag's allowlist? Wildcard values admit everyone."""
    v = _flag_value()
    if v in ("", "off"):
        return False
    if v in ("on", "1", "true"):
        return True
    return str(sub or "") in {x.strip() for x in v.split(",") if x.strip()}


# ── quota (D-DR-2b): 4 per user per UTC calendar month, on the profile-satellite store ───────────────
def month_key(now: _dt.datetime | None = None) -> str:
    """The calendar-month bucket key, UTC: `YYYY-MM`. Months start on the 1st, which is what makes
    `month_reset_at`'s first-of-next-month arithmetic and this key name the SAME window -- a reset date
    that disagreed with the counter's bucket is how a user gets told 'resets September 1' and is still
    refused on September 1. (D-DR-2b, 2026-08-08: this was an ISO-week bucket; the property it had to
    hold -- key and reset naming one window -- is unchanged, only the window is.)"""
    d = now or _dt.datetime.now(_dt.timezone.utc)
    return f"{d.year:04d}-{d.month:02d}"


def month_reset_at(now: _dt.datetime | None = None) -> str:
    """The instant the current bucket rolls over: the FIRST moment of the next calendar month, UTC,
    ISO-8601 with a literal Z. Built by incrementing (year, month) and constructing the 1st -- never by
    adding a fixed delta, because months are 28/29/30/31 days long and a 30-day step would drift the
    reset off the bucket boundary (the exact disagreement `month_key`'s docstring forbids). December
    carries into January of the next year. (D-DR-2b, 2026-08-08.)"""
    d = now or _dt.datetime.now(_dt.timezone.utc)
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return _dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def quota_period(now: _dt.datetime | None = None) -> str:
    """The satellite's sk suffix: `dossier#<UTC month>` -> sk=`quota#dossier#2026-08`. Namespaced like
    the suggester's `suggest#<day>` so the daily turn counter is untouched (same table, same item
    shape, disjoint keys). D-DR-2b changed the BUCKET inside the namespace, not the key family: old
    `quota#dossier#2026-W32` rows are simply never read again and age out (no migration, and the
    one-time effect is a fresh allowance in the user's favour)."""
    return f"{QUOTA_PREFIX}#{month_key(now)}"


def quota_bypass(ident: dict | None) -> bool:
    """Who does NOT spend a monthly slot.

    (1) THE EVAL LANE -- no auth context at all. `auth.auth_on()` False means the whole deployment is
    running without Cognito: dev, tests and the eval harness. There is no principal to charge and no
    paying user to protect. This is SAFE precisely because of the two other gates on these routes: the
    dossier surface 404s unless GRAPHRAG_DOSSIER is set, and every route hangs off `_require_identity`
    -- so on a deployment where auth IS on, this branch is unreachable, and on one where it is off
    there is by definition no signed-in population to meter. The bypass cannot be reached by an
    anonymous CALLER on a live deployment; it is a property of the DEPLOYMENT, not of the request.
    (2) ADMIN/INTERNAL claims -- a sub named in GRAPHRAG_DOSSIER_ADMINS, or a token carrying an
    admin/internal group claim. This is how our own D-DR-4 acceptance runs never consume a real slot."""
    from leviathan.graphrag import auth
    if not auth.auth_on():
        return True
    sub = str((ident or {}).get("sub") or "")
    admins = {x.strip() for x in os.environ.get(ADMIN_FLAG, "").split(",") if x.strip()}
    if sub and sub in admins:
        return True
    groups = (ident or {}).get("groups") or (ident or {}).get("cognito:groups") or ()
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.split(",")]
    return any(str(g).strip().lower() in ("admin", "internal") for g in groups)


def quota_state(store, ident: dict, *, now: _dt.datetime | None = None) -> dict:
    """{remaining, limit, reset_at} for GET /v1/dossier/quota. Bypassed principals always read FULL --
    the badge must not tell an admin they have 0 left when nothing will ever refuse them. FAIL-OPEN on
    any store error (the `_require_identity_quota` law: a counter glitch must never lock a user out)."""
    out = {"remaining": QUOTA_LIMIT, "limit": QUOTA_LIMIT, "reset_at": month_reset_at(now)}
    if quota_bypass(ident):
        out["bypass"] = True
        return out
    try:
        used = int(store.read_quota(ident["sub"], quota_period(now)) or 0)
    except Exception:  # noqa: BLE001 -- fail open
        return out
    out["remaining"] = max(0, QUOTA_LIMIT - used)
    return out


def consume_quota(store, ident: dict, *, now: _dt.datetime | None = None) -> str | None:
    """Spend one slot AT ACCEPTANCE (the 202) -- never at completion, or two racing submissions both
    pass. Returns the period key that was charged (for a later refund), or None when bypassed.
    Raises `store.QuotaExceeded` when the month is spent. FAIL-OPEN on any non-quota store error."""
    from leviathan.graphrag import store as st
    if quota_bypass(ident):
        return None
    period = quota_period(now)
    try:
        store.incr_turn_quota(ident["sub"], period, QUOTA_LIMIT)
    except st.QuotaExceeded:
        raise
    except Exception:  # noqa: BLE001 -- counter glitch -> allow, and charge nothing to refund later
        return None
    return period


def refund_quota(store, user: str, period: str | None) -> None:
    """Give the slot back. Called ONLY on a FAILED dossier: a PARTIAL one delivered a document with its
    gaps declared, which is a product, and it spent real model money. Best-effort by design -- a refund
    that raised would turn one failure into two."""
    if not period:
        return
    try:
        store.refund_quota(user, period)
    except Exception:  # noqa: BLE001
        pass


# ── the plan (D-DR-1 step 2) ────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Shape:
    """One deterministic playbook shape. `config` is the ENGINE choice and it is authored, not guessed:
    a shape whose job is enumeration or cross-market breadth is width-hungry and runs deep+contracts;
    the rest run quick PLAIN (D-CC-3 R1)."""
    id: str
    title: str
    template: str                  # carries exactly one {subject} slot
    config: str                    # "quick" | "deep"
    rationale: str


# THE STANDING DESK CHECKLIST, in the plan's own words ("balance, curve/carry, positioning, episodes,
# co-move, input-cost"). These six run on EVERY dossier and in this order -- that is what makes the
# plan deterministic and what makes two dossiers on the same book comparable. The LLM planner fills
# GAPS after them; it never reorders or removes one. Six shapes also puts the floor above
# MIN_SUBQUERIES by construction, so a dead planner call still yields a legitimate dossier.
PLAYBOOK: tuple[Shape, ...] = (
    Shape(id="balance", title="Balance sheet and tightness", config="quick",
          template=("For {subject}: what do the most recent balance-sheet vintages say about production, "
                    "ending stocks and stocks-to-use, and which way did the latest revisions move?"),
          rationale="The buffer. Every convexity story starts from how much slack the balance sheet holds."),
    Shape(id="curve_carry", title="Curve and carry", config="quick",
          template=("For {subject}: what is the shape of the futures curve at the as-of, and what does the "
                    "carry between the front and the deferred contracts imply about storage and near-term "
                    "tightness?"),
          rationale="The market's own price of time -- the cleanest read on whether tightness is priced."),
    Shape(id="positioning", title="Positioning", config="quick",
          template=("For {subject}: what does the latest reported positioning show -- managed-money net "
                    "length and how it has changed -- and how crowded is the trade already?"),
          rationale="Whether the move still has fuel, or is already owned."),
    Shape(id="episodes", title="Dated analogs", config="deep",
          template=("For {subject}: enumerate the dated historical episodes in the record where this set-up "
                    "occurred -- one entry per occurrence, with its dates and what followed."),
          rationale="Width-hungry: an enumeration is only honest if the turn was SHOWN every window."),
    Shape(id="comove", title="Co-movement and transmission", config="deep",
          template=("For {subject}: which other markets move with it, through which transmission channel, "
                    "and which leg moves first?"),
          rationale="Width-hungry: a cross-commodity chain needs breadth the lean config cannot reach."),
    Shape(id="input_cost", title="Input costs and the cost stack", config="quick",
          template=("For {subject}: what does the record carry on the input-cost stack -- energy, "
                    "fertilizer, freight, currency -- and where does it put the floor under the cost of "
                    "production?"),
          rationale="The floor. A price story with no cost stack has no lower bound to argue about."),
)

# Exchange/venue tokens dropped when a contract slug is turned into a reader phrase. A LOCAL copy of
# server._XC_EXCHANGE_TOKENS on purpose: server imports THIS module, so importing back would be a
# cycle. Divergence is harmless here (it only ever changes wording inside a sub-question) and the set
# is pinned by test.
_EXCHANGE_TOKENS = frozenset({"cbot", "cme", "dce", "zce", "ice", "matif", "mcpo", "nybot", "liffe",
                              "bmd", "crude", "malaysian", "mcx", "kcbt"})
_SUBJECT_CAP = 160


def _leg_word(slug: str) -> str:
    return " ".join(w for w in str(slug or "").lower().split("_") if w and w not in _EXCHANGE_TOKENS)


def subject(question: str, graph=None) -> str:
    """The phrase each playbook template is instantiated with -- DETERMINISTIC, zero model calls.

    A tracked contract matches when EVERY distinguishing token of its reader phrase appears in the
    question ('soybean oil' needs both words), which is the same >=3-char distinguishing-token rule the
    suggester's pair gate uses. Matches are taken in sorted slug order and capped at two, so the same
    question always yields the same subject. No match -> the question's own leading clause, trimmed:
    a sub-question must stand alone as a grounded turn, so it may never say 'the subject above'."""
    q = " " + re.sub(r"[^a-z0-9]+", " ", str(question or "").lower()) + " "
    names: list[str] = []
    for slug in sorted((getattr(graph, "contracts", None) or {})):
        phrase = _leg_word(slug)
        toks = [w for w in phrase.split() if len(w) >= 3]
        if toks and all(f" {t} " in q for t in toks):
            if phrase not in names:
                names.append(phrase)
    if names:
        return " and ".join(names[:2])
    clause = re.sub(r"\s+", " ", str(question or "").strip()).rstrip("?.!")
    return clause[:_SUBJECT_CAP] or "this market"


PLANNER_SYS = (
    "You extend a commodity research desk's STANDING dossier checklist. The six standing sub-questions "
    "(balance sheet, curve and carry, positioning, dated analogs, co-movement, input costs) have ALREADY "
    "been written and will run -- do NOT repeat, rephrase or reorder them.\n"
    "Your job is two things:\n"
    "1. TITLE the dossier: a terse, specific noun phrase, 3-9 words, no quotes, ASCII only.\n"
    "2. Add the sub-questions the standing six MISS for this particular question -- what a desk would "
    "still have to look up. Zero is a valid answer; never pad. Each must be a self-contained question "
    "that a research turn could answer on its own (never 'and what about it?'), about markets, "
    "fundamentals, policy, logistics or history -- never about prices to come, never a trade "
    "recommendation, never a request for a level or a target.\n"
    "Mark a sub-question width_hungry ONLY when answering it well requires BREADTH: ranking or "
    "enumerating many origins/members, a cross-commodity chain, or enumerating dated episodes. A "
    "focused single-market lookup is not width-hungry."
)


def _planner_tool(max_new: int) -> dict:
    return {"name": "set_dossier_plan",
            "description": "Title the dossier and add the sub-questions the standing checklist misses.",
            "input_schema": {"type": "object", "properties": {
                "title": {"type": "string", "description": "3-9 word ASCII noun phrase naming the dossier."},
                "subqueries": {"type": "array", "maxItems": max(0, max_new), "items": {
                    "type": "object", "properties": {
                        "title": {"type": "string", "description": "2-6 word section title."},
                        "question": {"type": "string", "description": "The self-contained sub-question."},
                        "width_hungry": {"type": "boolean",
                                         "description": "True only for rank/enumerate/cross-chain breadth."},
                        "rationale": {"type": "string", "description": "One clause: why the desk needs it."}},
                    "required": ["title", "question"]}}},
                "required": ["title"]}}


def _entry(i: int, title: str, question: str, config: str, rationale: str, *,
           shape: str | None, source: str) -> dict:
    return {"i": i, "title": str(title)[:80], "question": str(question).strip(),
            "config": config if config in ("quick", "deep") else "quick",
            "rationale": str(rationale or "")[:200], "shape": shape, "source": source,
            "width_hungry": config == "deep", "status": SQ_PENDING}


def _fallback_title(question: str) -> str:
    q = re.sub(r"\s+", " ", str(question or "").strip()).rstrip("?.!")
    return (q[:80] or "Deep research dossier")


def plan(question: str, *, asof: str | None = None, graph=None, call=None,
         model: str | None = None, today: str | None = None) -> dict:
    """Decompose one question into 5-12 sub-questions. Returns PLAN DATA -- it is stored, rendered into
    the artifact (the Gemini lesson: a visible plan) and replayed into the trace; it is never prose.

    DETERMINISTIC SHAPES FIRST, exactly as ratified: the six standing playbook rows are built with no
    model call at all, so a dead planner, a throttled provider or GRAPHRAG_DISPATCH=rules all still
    yield a legitimate 6-row plan. The ONE planner call then TITLES the dossier and fills gaps, capped
    so the total can never exceed MAX_SUBQUERIES. Any planner failure is swallowed (the dispatch law:
    routing must never break an answer) and leaves the deterministic plan standing."""
    subj = subject(question, graph)
    rows = [_entry(0, s.title, s.template.format(subject=subj), s.config, s.rationale,
                   shape=s.id, source="playbook") for s in PLAYBOOK]
    title = _fallback_title(question)
    planner_ok = False
    room = MAX_SUBQUERIES - len(rows)
    if room > 0 and os.environ.get("GRAPHRAG_DISPATCH", "llm") != "rules":
        try:
            from leviathan.graphrag import answer as an
            from leviathan.graphrag import dispatch as dsp
            c = call if call is not None else an._call_opus
            mdl = model or os.environ.get("GRAPHRAG_DISPATCH_MODEL") or dsp.SONNET
            user = "\n\n".join(x for x in (
                f"TODAY: {today or _dt.date.today().isoformat()}",
                f"AS-OF (every sub-question is answered at this cutoff): {asof}" if asof else "",
                "STANDING SUB-QUESTIONS ALREADY PLANNED:\n" + "\n".join(
                    f"{n + 1}. {r['title']} -- {r['question']}" for n, r in enumerate(rows)),
                f"QUESTION: {question}") if x)
            out = c(PLANNER_SYS, user, model=mdl, tool=_planner_tool(room), **dsp._temp_kw(c)) or {}
            t = str(out.get("title") or "").strip().strip('"')[:80]
            if t:
                title, planner_ok = t, True
            for r in (out.get("subqueries") or [])[:room]:
                if not isinstance(r, dict):
                    continue
                q = str(r.get("question") or "").strip()
                if not q:
                    continue
                wide = r.get("width_hungry") is True          # strict, the xc_explicit idiom
                rows.append(_entry(0, r.get("title") or q[:60], q, "deep" if wide else "quick",
                                   r.get("rationale") or "", shape=None, source="planner"))
                planner_ok = True
        except (Exception, SystemExit):  # noqa: BLE001 -- planning must never break the dossier
            # SystemExit is named on purpose and is not paranoia: providers.make_client() reaches
            # batch_extract._api_key(), which raises SystemExit when no Anthropic key is configured.
            # A bare `except Exception` would let that kill the job thread, and a job thread that dies
            # without landing a status is the one failure this module is built to make impossible.
            pass
    rows = rows[:MAX_SUBQUERIES]
    n = len(rows)
    for i, r in enumerate(rows, 1):
        r["i"], r["n"] = i, n
    return {"title": title, "asof": asof, "subject": subj, "n": n,
            "planner": "llm" if planner_ok else "playbook", "subqueries": rows}


# ── notes (D-DR-1 step 4): what a sub-answer contributes, as DATA ───────────────────────────────────
def _pairs_from(result: dict) -> list[dict]:
    """The sub-turn's citation pairs, carried forward verbatim. Read off `result['citations']` -- the
    machine-readable Citation list the turn already produced -- NEVER by scanning the assembled body.

    Each pair is (handle, prop_id, as_of) plus the prop TEXT, which is what lets the synthesis cite
    without re-retrieving and lets the final verifier check with the props in hand:
      handle    the sub-turn's own [E<i>]/[N<i>] token (LOCAL to that sub-query)
      prop_id   source_key for a document; the leakage-safe query locator for a number row
      as_of     the citation's knowledge date -- when the item was KNOWN, not when we read it
      label     the one-line rendering (a number citation's label carries its headline VALUE, which is
                the figure the synthesis is allowed to restate)"""
    out = []
    for c in (result.get("citations") or []):
        if not isinstance(c, dict):
            continue
        pay = c.get("payload") or {}
        kind = c.get("kind")
        if kind == "number":
            prop_id = json.dumps(pay.get("query") or {}, sort_keys=True, ensure_ascii=True)
            text = str(c.get("label") or "")
        else:
            prop_id = str(pay.get("source_key") or "")
            text = str(pay.get("text") or "")
        out.append({"handle": str(c.get("id") or ""), "kind": kind, "prop_id": prop_id,
                    "as_of": c.get("date"), "source": c.get("source"),
                    "label": str(c.get("label") or "")[:300], "prop_text": text})
    return out


def notes_from_result(result: dict, entry: dict) -> dict:
    """Structured notes for ONE sub-answer: its sections + its citation pairs, carried as data.

    SECTIONS come from `answer._sectionize(structured['mechanism'])` -- the model's OWN field, split by
    the one existing producer for that split (a DERIVED VIEW, the same one GRAPHRAG_ANSWER_V2 ships).
    The assembled `result['answer']` -- which carries the rendered sources footer -- is never touched:
    that is the surface D-DT item-2 forbids, and all four of its discovery rules leaked when it was.

    Per section we record which handles the section's own prose wrote. That is a token scan over a
    MODEL FIELD, not a span discovery over assembled text, and it is exactly what the verifier itself
    reads; the handles are then resolved through the carried pairs, never re-derived from evidence."""
    from leviathan.graphrag import answer as an
    structured = result.get("structured") or {}
    pairs = _pairs_from(result)
    known = {p["handle"] for p in pairs}

    def _handles(text: str) -> list[str]:
        out = []
        for m in _HANDLE_RX.finditer(text or ""):
            h = f"{m.group('kind') or 'E'}{m.group('idx')}"
            if h in known and h not in out:
                out.append(h)
        return out

    tldr = str(structured.get("tldr") or "").strip()
    sections = []
    for s in an._sectionize(str(structured.get("mechanism") or "")):
        body = str(s.get("body") or "").strip()
        if not body:
            continue
        sections.append({"kind": s.get("kind"), "heading": str(s.get("heading") or "").strip(),
                         "body": body, "handles": _handles(body)})
    # The handles this sub-answer actually STOOD BEHIND. `citations` is the turn's whole retrieved set
    # (cit.unify enumerates every deduped evidence row and every number call, cited or not), so without
    # this the dossier would inherit the raw retrieval of 5-12 turns as its citable pool -- receipts with
    # no claim behind them, which is the prose-to-evidence hazard from the demand side. The union is
    # built from THIS set: a pair may be cited in the document only if a carried claim already used it.
    used = list(dict.fromkeys(_handles(tldr) + [h for s in sections for h in s["handles"]]))
    tr = result.get("trace") or {}
    verifier = tr.get("citation_verifier") or {}
    return {
        "i": entry.get("i"), "title": entry.get("title"), "question": entry.get("question"),
        "config": entry.get("config"), "shape": entry.get("shape"),
        "asof": result.get("asof"), "tldr": tldr,
        "sections": sections, "pairs": pairs, "used": used,
        "contracts": list(result.get("contracts") or []),
        "mode": ((result.get("intent_decision") or {}).get("mode") or {}).get("honored"),
        "response_contract": tr.get("response_contract"),
        "checked": int(verifier.get("checked", 0) or 0),
        "strips": int(verifier.get("stripped", 0) or 0),
        "n_episode_windows": an._n_episode_windows(tr),
        "usage": tr.get("synth_usage") or {},
    }


# ── the union (D-DR-1 step 5 inputs): one global handle namespace over every note ───────────────────
def build_union(notes: list[dict], results: list[dict] | None = None) -> dict:
    """Fold every sub-answer's pairs into ONE global [E]/[N] namespace + the verifier's inputs.

    De-dup key is the PROP, not the handle: the same WASDE chunk cited by three sub-queries is one
    global E-handle, which is what stops the document carrying three numbers for one source. First-seen
    order (sub-query order, then citation order within it) makes the numbering deterministic.

    ONLY the pairs a carried CLAIM stood behind are folded in (`note['used']`): a turn's citation list
    is its whole retrieved set, and admitting the uncited remainder would hand the synthesis 5-12 turns
    of raw retrieval as its citable pool.

    Returns the global pair list, the per-sub-query LOCAL->GLOBAL remap, and the two lists the verifier
    consumes -- `evidence` rows in E order and `number_calls` in N order -- reconstructed from the
    carried props. `results` (when supplied) contributes the FULL evidence row and the FULL number-call
    record where available; a Citation payload truncates number rows to three, and a truncated row set
    would let the verifier charge number_mismatch against a figure that is in fact backed."""
    ev_by_key: dict[str, dict] = {}
    if results:
        for res in results:
            for row in (res.get("evidence") or []):
                if isinstance(row, dict) and row.get("source_key"):
                    ev_by_key.setdefault(str(row["source_key"]), row)
    calls_by_key: dict[str, dict] = {}
    if results:
        for res in results:
            for c in (res.get("number_calls") or []):
                if isinstance(c, dict):
                    k = json.dumps(c.get("query") or {}, sort_keys=True, ensure_ascii=True)
                    calls_by_key.setdefault(k, c)

    pairs: list[dict] = []
    remap: dict[int, dict] = {}
    seen_ev: dict[str, str] = {}
    seen_num: dict[str, str] = {}
    evidence: list[dict] = []
    number_calls: list[dict] = []
    for note in notes:
        local: dict[str, str] = {}
        used = set(note.get("used") or ())
        for p in (note.get("pairs") or []):
            key, kind = p.get("prop_id") or "", p.get("kind")
            if not key or p.get("handle") not in used:   # only pairs a carried claim stood behind
                continue
            if kind == "number":
                g = seen_num.get(key)
                if g is None:
                    number_calls.append(calls_by_key.get(key)
                                        or {"query": json.loads(key) if key.startswith("{") else {},
                                            "rows": [], "status": "carried"})
                    g = f"N{len(number_calls)}"
                    seen_num[key] = g
                    pairs.append({**p, "handle": g, "local": p.get("handle"), "from": note.get("i")})
            else:
                g = seen_ev.get(key)
                if g is None:
                    evidence.append(ev_by_key.get(key) or {"source_key": key, "source": p.get("source"),
                                                           "date": p.get("as_of"),
                                                           "text": p.get("prop_text") or ""})
                    g = f"E{len(evidence)}"
                    seen_ev[key] = g
                    pairs.append({**p, "handle": g, "local": p.get("handle"), "from": note.get("i")})
            local[str(p.get("handle"))] = g
        remap[note.get("i")] = local
    return {"pairs": pairs, "remap": remap, "evidence": evidence, "number_calls": number_calls}


def remap_body(body: str, local: dict) -> str:
    """Rewrite a note body's LOCAL handles into the global namespace. Pure dictionary substitution over
    CARRIED pairs -- a handle with no carried pair is DROPPED (it cannot be rendered from a pair, and
    the spine law does not permit guessing one)."""
    def _sub(m):
        h = f"{m.group('kind') or 'E'}{m.group('idx')}"
        g = local.get(h)
        return f"[{g}]" if g else ""
    return _HANDLE_RX.sub(_sub, body or "")


def union_census(notes: list[dict], union: dict) -> dict:
    """The DOCUMENT-scale composition census, minted by the SAME producer a turn uses
    (`answer._composition_census`) so a mandate cannot mean one thing on a turn and another on a
    document -- countries-first-then-contracts ordering, the same roster cap, the same true-count rule.

    Two arguments differ because the scale does: `contracts` is the de-duped union of every
    sub-answer's routed contracts, and `n_evidence` is the size of the union evidence list. The one
    field the shared producer cannot compute here is n_episode_windows -- it reads a single turn's
    `episodes_injected` -- so it is SUMMED over the notes, each of which already recorded its own count
    through that same one producer (`answer._n_episode_windows`) at note time."""
    from leviathan.graphrag import answer as an
    ents: list[str] = []
    for n in notes:
        for c in (n.get("contracts") or []):
            if c and str(c) not in ents:
                ents.append(str(c))
    census = an._composition_census(contracts=ents, number_calls=union.get("number_calls") or [],
                                    trace={}, n_evidence=len(union.get("evidence") or []))
    census["n_episode_windows"] = sum(int(n.get("n_episode_windows") or 0) for n in notes)
    return census


# ── synthesis (D-DR-1 step 5) ───────────────────────────────────────────────────────────────────────
_SYSTEM_DOSSIER = (
    "You are a commodity research analyst composing a RESEARCH DOSSIER for a professional desk.\n"
    "You are given NOTES: several separately researched sub-answers, each with its own claims and its "
    "own citation handles. You have NO other source. You may not retrieve, recall or assume anything "
    "that is not in the notes -- if the notes do not carry it, the dossier says so.\n"
    "Write for a reader who knows the market: mechanism first, no throat-clearing, no hedged mush. "
    "Plain ASCII. Never a price target, a trade recommendation, an entry/exit level or a stop. Never "
    "present-tense a dated item -- every 'currently' must be backed by the newest date you actually "
    "hold.\n"
    "Every claim that carries a number, a date or an assertion of fact ends with the citation handle "
    "of the pair that backs it, written exactly as listed (for example [E4] or [N2]). A number you "
    "cannot pin to a listed pair does not appear. Handles are listed FOR you -- never invent, "
    "renumber or reuse one for a different claim.\n"
    "Put the whole document in the `mechanism` field under the headings below; `tldr` is 2-4 sentences "
    "of the dossier's finding, not a summary of its structure. `sources` lists one entry per handle you "
    "actually cited: {ref: <the integer of the handle>, source, date, note}."
)


def system_prompt(census: dict | None) -> str:
    """The dossier synthesis system prompt: the persona above + the document contract from the leaf.
    Assembled here rather than needle-rewritten because there is no mentor persona in this lane to
    rewrite -- `response_contracts.apply()` exists to edit the TURN persona and has nothing to edit
    here; the section plan, the budget and the mandates still come from the ONE leaf producer."""
    from leviathan.graphrag import response_contracts as rc
    return "\n".join([_SYSTEM_DOSSIER, "", rc.dossier_structure_clause(),
                      f"LENGTH DISCIPLINE: target {rc.dossier_budget(census)} words across the "
                      f"{len(rc.DOSSIER_SECTIONS)} sections.", rc.dossier_directive(census)])


def notes_block(question: str, asof: str | None, plan_data: dict, notes: list[dict],
                union: dict) -> str:
    """The synthesis USER message: the plan, then every note with its handles already remapped to the
    global namespace, then the global pair list. RAW EVIDENCE NEVER APPEARS -- the props reach the model
    only as the receipt text attached to a carried pair, which is what 'compose from the notes, not the
    evidence' means operationally (and is pinned by test)."""
    remap = union.get("remap") or {}
    lines = [f"DOSSIER QUESTION: {question}", f"AS-OF (every sub-answer was produced at this cutoff): {asof}",
             "", "PLAN (this ran; it is part of the delivered document):"]
    for r in plan_data.get("subqueries") or []:
        lines.append(f"  {r['i']}/{r['n']} [{r['config']}] {r['title']} -- {r['question']}"
                     f"  ({r.get('status', SQ_PENDING)})")
    by_i = {n.get("i"): n for n in notes}
    lines += ["", "NOTES FROM THE SUB-ANSWERS (your ONLY source):"]
    for r in plan_data.get("subqueries") or []:
        note = by_i.get(r["i"])
        lines.append("")
        lines.append(f"--- SUB-QUESTION {r['i']}: {r['title']} [{r['config']}] ---")
        if note is None:
            lines.append(f"STATUS: {r.get('status', SQ_FAILED)} -- {r.get('error') or 'no answer produced'}")
            lines.append("This sub-question produced NOTHING. Name it in "
                         "'## What the record cannot answer'.")
            continue
        local = remap.get(r["i"]) or {}
        lines.append(f"FINDING: {remap_body(note.get('tldr') or '', local)}")
        for s in note.get("sections") or []:
            head = s.get("heading") or "(untitled)"
            lines.append(f"  ## {head}")
            lines.append("  " + remap_body(s.get("body") or "", local)[:_NOTE_BODY_CAP])
    lines += ["", "CITATION PAIRS -- the complete set of handles you may write, and what each one is:"]
    for p in union.get("pairs") or []:
        txt = re.sub(r"\s+", " ", str(p.get("prop_text") or p.get("label") or "")).strip()[:_PROP_TEXT_CAP]
        lines.append(f"  [{p['handle']}] {p.get('source') or '?'} ({p.get('as_of') or 'undated'}): {txt}")
    return "\n".join(lines)


def synthesize(question: str, asof: str | None, plan_data: dict, notes: list[dict], union: dict, *,
               call=None, model: str | None = None) -> dict:
    """ONE composition pass over the NOTES. Returns {structured, verifier, body, usage, census}.

    The tool schema is `answer._answer_tool()` -- reused, not re-declared, because the SAME verifier
    has to read this output; a bespoke schema is how a document quietly stops being verifiable.
    The verifier then runs over the final body against the UNION evidence list. The prop text is in
    hand (we carried it), so this is verification, not re-discovery."""
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import register as reg
    from leviathan.graphrag import verify as vf
    census = union_census(notes, union)
    c = call if call is not None else an._call_opus
    # DOCUMENT-scale output cap. A turn's 6000 default truncated ALL FIVE D-DR-4 dossiers at the
    # synthesis step (stop_reason=max_tokens -> the extract guard raised -> job FAILED after every
    # sub-query had already run and billed). A dossier composes 5-12 sub-answers under mandated
    # sections; its ceiling is a document's, not a turn's. The turn-side max_tokens exclusion
    # (reasoning_modes.py:35) is about TURN length levers and does not govern this call.
    out = c(system_prompt(census),
            notes_block(question, asof, plan_data, notes, union),
            model=model or SYNTH_MODEL, tool=an._answer_tool(), max_tokens=SYNTH_MAX_TOKENS)
    structured = out if isinstance(out, dict) else {}
    usage = structured.pop("_usage", None)
    structured.pop("_degraded_model", None)
    verifier = vf.verify_citations(structured, union.get("evidence") or [],
                                   union.get("number_calls") or [])
    body = reg.sanitize(an.render(structured, include_ledger=False)
                        + _sources_block(structured, union))
    return {"structured": structured, "verifier": verifier, "body": body,
            "usage": usage or {}, "census": census}


def _sources_block(structured: dict, union: dict) -> str:
    """ONE validated source list for the document, numbered by the handles the model actually wrote --
    rendered FROM THE CARRIED PAIRS. The turn path builds this from the verifier's `resolved` map; here
    the pairs ARE the resolution (they were carried for exactly this), so no lookup can drift.

    THE PROSE KIND IS THE DISCRIMINATOR, and it has to be: the emit_answer schema types a ledger `ref`
    as a BARE INTEGER, so the E and N namespaces collide on it (verify.py's own T2b RCA). Resolving a
    bare `1` against both would list an [E1] the document never cited whenever it cited [N1]. So a
    ledger ref counts only for the KINDS the prose actually wrote at that index."""
    prose = (structured.get("tldr") or "") + "\n" + (structured.get("mechanism") or "")
    kinds: dict[str, set] = {}
    for m in _HANDLE_RX.finditer(prose):
        kinds.setdefault(m.group("idx"), set()).add(m.group("kind") or "E")
    cited = {f"{k}{idx}" for idx, ks in kinds.items() for k in ks}
    for s in (structured.get("sources") or []):
        ref = str(s.get("ref", "")).strip().strip("[]")
        if not ref:
            continue
        if ref.isdigit():
            cited |= {f"{k}{ref}" for k in kinds.get(ref, {"E"})}
        else:
            cited.add(ref.upper())
    lines = []
    for p in union.get("pairs") or []:
        if p["handle"] not in cited:
            continue
        txt = re.sub(r"\s+", " ", str(p.get("prop_text") or p.get("label") or "")).strip()[:_RECEIPT_CAP]
        lines.append(f"[{p['handle']}] {p.get('source') or '?'} ({p.get('as_of') or 'undated'}): {txt}")
    return ("\n\n## Sources\n" + "\n".join(lines)) if lines else ""


# ── the job ─────────────────────────────────────────────────────────────────────────────────────────
def new_id() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Job:
    """One dossier's live state + its SSE fan-out. Every stage transition goes through `emit`, which
    stamps it, appends it to a replayable log and pushes it to every subscriber -- so a client that
    connects LATE gets the history and then the live tail, and never a hole in between. The log is
    structurally bounded (accepted + plan + 2 per sub-question + synthesis + terminal, so <= 2 *
    MAX_SUBQUERIES + 4), which is what makes it safe to persist inside one store item."""

    def __init__(self, dossier_id: str, user: str, question: str, asof: str | None, *,
                 quota_period: str | None = None):
        self.id = dossier_id
        self.user = user
        self.question = question
        self.asof = asof
        self.quota_period = quota_period
        self.graph_version: str | None = None
        self.created_at = _now()
        self.status = PLANNING
        self.stage = PLANNING
        self.plan: dict | None = None
        self.subqueries: list[dict] = []
        self.artifact_id: str | None = None
        self.error: str | None = None
        self.notes: list[dict] = []
        self.usage: dict = {"calls": 0, "in": 0, "out": 0, "cost_usd": 0.0}
        self.events: list[dict] = []
        self._subs: list[queue.Queue] = []
        self._lock = threading.RLock()

    # -- events -------------------------------------------------------------------------------------
    def emit(self, kind: str, **info) -> dict:
        ev = {"type": kind, "ts": _now(), **info}
        with self._lock:
            self.events.append(ev)
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except Exception:  # noqa: BLE001 -- a dead subscriber never stalls the job
                pass
        return ev

    def subscribe(self) -> tuple[list[dict], queue.Queue]:
        """(replay, live queue) taken under ONE lock, so an event fired between the two can neither be
        missed nor delivered twice."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            replay = list(self.events)
            self._subs.append(q)
        return replay, q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    # -- state --------------------------------------------------------------------------------------
    def set_stage(self, stage: str) -> None:
        with self._lock:
            self.stage = stage

    def add_usage(self, usage: dict | None) -> None:
        if not usage:
            return
        from leviathan.graphrag import providers as pv
        cost = pv.serving_cost_usd(usage.get("model") or "", usage.get("in") or 0, usage.get("out") or 0,
                                   usage.get("cache_read") or 0, usage.get("cache_write") or 0)
        with self._lock:
            self.usage["calls"] += 1
            self.usage["in"] += int(usage.get("in") or 0)
            self.usage["out"] += int(usage.get("out") or 0)
            if cost:
                self.usage["cost_usd"] = round(self.usage["cost_usd"] + cost, 6)

    def snapshot(self) -> dict:
        """The GET /v1/dossier/{id} body. `subqueries` is projected to the LOCKED wire shape
        ({i, n, title, status}) -- the full plan row (question, config, rationale) is delivered in the
        artifact, which is where a plan is meant to be read."""
        with self._lock:
            out = {"dossier_id": self.id, "status": self.status, "stage": self.stage,
                   "question": self.question, "asof": self.asof, "created_at": self.created_at,
                   "subqueries": [{"i": r.get("i"), "n": r.get("n"), "title": r.get("title"),
                                   "status": r.get("status", SQ_PENDING)} for r in self.subqueries]}
            if self.plan:
                out["title"] = self.plan.get("title")
            if self.artifact_id:
                out["artifact_id"] = self.artifact_id
            if self.error:
                out["error"] = self.error
            return out

    def record(self) -> dict:
        """The persisted store body -- the snapshot plus everything a cross-request reader needs
        (the full plan, the event log for a late SSE replay, the usage tally, the quota period to
        refund). NOT the notes: they carry prop text and belong in the frozen artifact, which is the
        surface that owns a full payload (the `_freeze_artifact` posture)."""
        with self._lock:
            return {**self.snapshot(), "plan": self.plan, "events": list(self.events),
                    "usage": dict(self.usage), "quota_period": self.quota_period,
                    "updated_at": _now()}


_JOBS: dict[str, Job] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_KEEP = 64                 # finished jobs retained in memory; older ones fall back to the store


def register(job: Job) -> None:
    """Register a job and evict the OLDEST TERMINAL ones past the cap. Terminal only, and that is
    load-bearing: evicting a job that is still RUNNING would make `reap_orphan` (which fires on a
    non-terminal record with no live job) declare a healthy dossier dead and refund its slot. A
    terminal job evicted here loses nothing -- GET reads the mirror and SSE replays the persisted log."""
    with _JOBS_LOCK:
        _JOBS[job.id] = job
        if len(_JOBS) > _JOBS_KEEP:
            for jid, j in list(_JOBS.items()):
                if len(_JOBS) <= _JOBS_KEEP:
                    break
                if j.status in TERMINAL and jid != job.id:
                    _JOBS.pop(jid, None)


def get_job(dossier_id: str) -> Job | None:
    with _JOBS_LOCK:
        return _JOBS.get(dossier_id)


def forget(dossier_id: str) -> None:
    with _JOBS_LOCK:
        _JOBS.pop(dossier_id, None)


def persist(store, job: Job) -> None:
    """Mirror the job into the store after every stage transition. Best-effort: a store blip must not
    kill a running dossier, it only costs cross-request visibility until the next transition."""
    try:
        store.put_item(job.user, KIND, job.id, job.record())
    except Exception:  # noqa: BLE001
        pass


# ── sub-query execution (D-DR-1 step 3) ─────────────────────────────────────────────────────────────
def _with_deadline(fn, timeout: float):
    """Run `fn()` on a daemon thread and give up after `timeout` seconds.

    This is the PER-SUB-CALL provider read-timeout, and it is per sub-call ON PURPOSE: a hung provider
    socket must cost one sub-question, not the whole 20-minute job. The abandoned thread cannot be
    killed (no such thing in CPython) -- it is a daemon, it holds no lock of ours, and its late result
    is discarded, so the cost is bounded and invisible. Stated rather than hidden: this is the v1
    tradeoff, and the alternative (a cooperative cancel token threaded through respond) is a much
    larger seam than this wave funds."""
    box: dict = {}

    def _run():
        try:
            box["ok"] = fn()
        except BaseException as e:  # noqa: BLE001 -- carried across the thread boundary and re-raised
            box["err"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"sub-query exceeded {int(timeout)}s")
    if "err" in box:
        raise box["err"]
    return box.get("ok")


def run_subquery(entry: dict, *, asof: str | None, graph, respond=None, on_stage=None,
                 timeout: float = SUBCALL_TIMEOUT_S) -> dict:
    """Run ONE sub-question as a normal grounded turn (via-orchestrator semantics: same respond(), same
    verifier, same citation pins, same numbers legs -- a dossier buys no special engine).

    THE ENGINE CHOICE, per the D-CC-3 amended red branch:
      config=quick -> mode=quick, census forced OFF. Forced, not left to the flag: R1 measured the
                      mandates actively harmful at quick width, so a serving env that ever turns the
                      census on globally must not reach these calls.
      config=deep  -> mode=deep, census forced ON. The provisional width engine, pending D-DR-4.
    The override is thread-scoped (see answer.composition_census_override), so a concurrent desk turn
    on this task is untouched in both directions.

    THE SHAPE ESCALATION IS OPTED OUT AT THIS BOUNDARY (D-MW-30, 30f review). `allow_shape_escalation
    =False` rides EVERY respond() call this lane makes, on both configs. Without it, turning
    GRAPHRAG_SHAPE_ESC on for the desk would silently change the DOSSIER too: a deep sub-question is a
    decomposed narrow ask -- exactly the 1-2 contract evidence-hungry shape the detector flags -- so the
    expected escalation rate on this lane is HIGH, and every escalated sub-turn would double the walk
    (per_seed_budget 63 vs deep's 32) and swap the writer for claude-opus-5, N times per job. Plan 12e
    leaves the dossier's Opus seat "untouched -- its own measured verdict, different task", and the 30d
    deck measures SINGLE TURNS only, so an escalated dossier would be both unmeasured and outside the
    gate that decides the flip. The opt-out is recorded per sub-turn as
    `trace.escalation_decision.suppressed_reason == 'caller'`, never as a silent absence. This is the
    boundary to move -- deliberately, with its own measurement -- if the dossier ever wants the width.

    THE D-HP NUMBERED RECEIPT MENU IS OPTED OUT AT THIS SAME BOUNDARY (D-HP-16, H0 review).
    `an.handle_menu_override(False)` rides EVERY respond() call this lane makes, on both configs, so a
    sub-answer renders the PRE-D-HP prompt -- unnumbered evidence rows and the pre-D-HP ledger sentence,
    byte for byte. WHY, in one line: an addressable dense menu is the strongest available nudge toward
    multi-citation GROUPING, and `_HANDLE_RX` (:95) below does not match a grouped token at all, so
    `remap_body` neither remaps nor drops it and a stale LOCAL index reaches a DELIVERED document inside
    the GLOBAL namespace. The plan already pins this lane's GRAMMAR to the control preset (never
    `deep_hp`/`quick_hp`) until D-HP-28's own gate opens; the menu is the same class of input change and
    is held at the same boundary rather than raising the input density before the output fix lands."""
    from leviathan.graphrag import answer as an
    from leviathan.graphrag import orchestrator as orch
    fn = respond if respond is not None else orch.respond
    deep = entry.get("config") == "deep"

    def _go():
        with an.composition_census_override(deep), an.handle_menu_override(False):
            return fn(entry["question"], graph=graph, asof=asof,
                      mode="deep" if deep else "quick", on_stage=on_stage,
                      allow_shape_escalation=False)

    return _with_deadline(_go, timeout) or {}


# ── landing (D-DR-1 step 6) ─────────────────────────────────────────────────────────────────────────
def artifact_payload(job: Job, synth: dict, notes: list[dict], union: dict) -> dict:
    """The frozen artifact's payload -- the DELIVERED DOSSIER.

    Everything D-DR-1 requires is a first-class key, not prose to be parsed back out: the PLAN
    (visible), the composed body, the per-section sources, the sub-query trace, and the carried pairs
    that every rendered citation resolves against (the deterministic spine gate D-DR-4 checks: every
    handle in the body must appear here)."""
    verifier = synth.get("verifier") or {}
    pairs = [{k: p.get(k) for k in ("handle", "kind", "prop_id", "as_of", "source", "label", "from")}
             | {"receipt": str(p.get("prop_text") or "")[:_RECEIPT_CAP]}
             for p in (union.get("pairs") or [])]
    sections = _section_sources(synth.get("structured") or {}, union)
    return {
        "kind": "dossier", "dossier_id": job.id, "question": job.question, "asof": job.asof,
        "title": (job.plan or {}).get("title"), "status": job.status,
        "answer": synth.get("body"), "structured": synth.get("structured"),
        "plan": job.plan, "sections": sections, "citations": pairs,
        "subquery_trace": [{"i": r.get("i"), "title": r.get("title"), "question": r.get("question"),
                            "config": r.get("config"), "shape": r.get("shape"),
                            "source": r.get("source"), "rationale": r.get("rationale"),
                            "status": r.get("status"), "error": r.get("error"),
                            "strips": r.get("strips"), "checked": r.get("checked"),
                            "mode": r.get("mode"), "contracts": r.get("contracts")}
                           for r in job.subqueries],
        "composition_census": synth.get("census"),
        "citation_verifier": {k: verifier.get(k) for k in ("enabled", "checked", "stripped",
                                                           "corrected", "claim_count", "by_rule")},
        "usage": dict(job.usage),
        # `trace.graph_version` is where `store.make_share` reads the pin from, so a dossier artifact is
        # tied to the exact graph that produced it -- the same reproducibility guarantee a shared turn has.
        "trace": {"graph_version": job.graph_version, "dossier": True},
    }


def _section_sources(structured: dict, union: dict) -> list[dict]:
    """Per-section sources for the artifact: each document section with the handles ITS OWN prose wrote,
    resolved through the carried pairs. Read off the `mechanism` FIELD (the model's own output), never
    off the assembled body -- the same field-level rule the notes follow."""
    from leviathan.graphrag import answer as an
    by_handle = {p["handle"]: p for p in (union.get("pairs") or [])}
    out = []
    for s in an._sectionize(str(structured.get("mechanism") or "")):
        body = str(s.get("body") or "")
        handles, seen = [], set()
        for m in _HANDLE_RX.finditer(body):
            h = f"{m.group('kind') or 'E'}{m.group('idx')}"
            if h in by_handle and h not in seen:
                seen.add(h)
                handles.append(h)
        out.append({"heading": str(s.get("heading") or "").strip(), "kind": s.get("kind"),
                    "sources": [{"handle": h, "prop_id": by_handle[h].get("prop_id"),
                                 "as_of": by_handle[h].get("as_of"),
                                 "source": by_handle[h].get("source")} for h in handles]})
    return out


def land_artifact(store, job: Job, payload: dict) -> str:
    """Freeze the dossier through the D-AM-15 artifacts seam: `store.make_share` mints the snapshot (the
    SAME freeze the public share link uses -- never a second one) and it lands as a per-user `artifact`
    item, so it opens in the existing artifact tab with no new collection, no new route and no new
    privacy story. Body keys are `server._freeze_artifact`'s, pinned by test."""
    from leviathan.graphrag import store as st
    snap = st.make_share(job.question, job.asof, payload)
    name = str((job.plan or {}).get("title") or job.question or "dossier")[:200]
    store.put_item(job.user, ARTIFACT_KIND, snap.id,
                   {"name": name, "snapshot": snap.to_dict(),
                    "created_at": snap.created_at, "updated_at": snap.created_at})
    return snap.id


# ── the driver ──────────────────────────────────────────────────────────────────────────────────────
def execute(job: Job, *, graph, store, respond=None, call=None, synth_call=None,
            wall_clock_s: float = WALL_CLOCK_S, subcall_timeout_s: float = SUBCALL_TIMEOUT_S) -> Job:
    """Run one dossier to a terminal state. Never raises: every exit lands a status, an event and a
    persisted record, because a job that dies silently is indistinguishable from one still running."""
    deadline = time.monotonic() + wall_clock_s
    results: list[dict] = []
    try:
        # -- plan ------------------------------------------------------------------------------------
        job.graph_version = getattr(graph, "version", None)
        job.set_stage(PLANNING)
        job.emit("stage", stage=PLANNING)
        p = plan(job.question, asof=job.asof, graph=graph, call=call)
        job.plan = p
        job.subqueries = p["subqueries"]
        job.status = RUNNING
        job.set_stage(RUNNING)
        job.emit("plan", title=p.get("title"), n=p.get("n"), planner=p.get("planner"),
                 subqueries=[{"i": r["i"], "n": r["n"], "title": r["title"], "question": r["question"],
                              "config": r["config"], "rationale": r["rationale"]} for r in job.subqueries])
        persist(store, job)

        # -- sub-queries: SEQUENTIAL BY LAW (the Cohere 3/min rationale is HISTORICAL as of D-MW P1;
        #    retained for determinism until the parallel-subquery gate -- D-MW-12) --------------------
        for entry in job.subqueries:
            if time.monotonic() >= deadline:
                entry["status"] = SQ_SKIPPED
                entry["error"] = "job wall-clock cap reached before this sub-question ran"
                job.emit("subquery", i=entry["i"], n=entry["n"], title=entry["title"],
                         status=SQ_SKIPPED, error=entry["error"])
                continue
            entry["status"] = SQ_RUNNING
            job.set_stage(f"subquery {entry['i']}/{entry['n']}")
            job.emit("subquery", i=entry["i"], n=entry["n"], title=entry["title"],
                     config=entry["config"], status=SQ_RUNNING)
            try:
                res = run_subquery(entry, asof=job.asof, graph=graph, respond=respond,
                                   timeout=min(subcall_timeout_s, max(1.0, deadline - time.monotonic())))
                note = notes_from_result(res, entry)
                results.append(res)
                job.notes.append(note)
                entry.update(status=SQ_OK, strips=note["strips"], checked=note["checked"],
                             mode=note.get("mode"), contracts=note.get("contracts"))
                job.add_usage(note.get("usage"))
                job.emit("subquery", i=entry["i"], n=entry["n"], title=entry["title"],
                         status=SQ_OK, strips=note["strips"], pairs=len(note.get("pairs") or []))
            except (Exception, SystemExit) as e:  # noqa: BLE001 -- a failure is a GAP, not the end
                entry["status"] = SQ_FAILED
                entry["error"] = f"{type(e).__name__}: {str(e)[:200]}"
                job.emit("subquery", i=entry["i"], n=entry["n"], title=entry["title"],
                         status=SQ_FAILED, error=entry["error"])
            persist(store, job)

        if not job.notes:
            raise RuntimeError("every sub-question failed; nothing to compose")

        # -- synthesis -------------------------------------------------------------------------------
        job.status = SYNTHESIZING
        job.set_stage(SYNTHESIZING)
        job.emit("synthesis", notes=len(job.notes),
                 gaps=sum(1 for r in job.subqueries if r.get("status") != SQ_OK))
        persist(store, job)
        union = build_union(job.notes, results)
        synth = synthesize(job.question, job.asof, job.plan, job.notes, union, call=synth_call)
        job.add_usage(synth.get("usage"))

        # -- landing ---------------------------------------------------------------------------------
        job.status = DONE if all(r.get("status") == SQ_OK for r in job.subqueries) else PARTIAL
        payload = artifact_payload(job, synth, job.notes, union)
        job.artifact_id = land_artifact(store, job, payload)
        job.set_stage(job.status)
        job.emit(job.status, artifact_id=job.artifact_id, strips=(synth.get("verifier") or {}).get("stripped"),
                 gaps=[r["i"] for r in job.subqueries if r.get("status") != SQ_OK],
                 cost_usd=job.usage.get("cost_usd"))
    # (Exception, SystemExit) and not BaseException: a provider call can raise SystemExit (see plan()),
    # and a job thread that dies without landing a status is the failure this module exists to prevent.
    # KeyboardInterrupt still propagates -- an operator stopping the process is not a dossier failure.
    except (Exception, SystemExit) as e:  # noqa: BLE001 -- the job owns its own failure
        job.status = FAILED
        job.error = f"{type(e).__name__}: {str(e)[:200]}"
        job.set_stage(FAILED)
        refund_quota(store, job.user, job.quota_period)              # a FAILED dossier never spent its slot
        job.emit(FAILED, error=job.error)
    finally:
        persist(store, job)
        job.notes = []          # the notes are frozen into the artifact; holding prop text after the
        register(job)           # job is terminal is pure memory. Re-register to trigger the eviction sweep.
    return job


def start(store, ident: dict, question: str, asof: str | None, *, graph, respond=None,
          quota_period: str | None = None, thread: bool = True) -> Job:
    """Accept a dossier: mint the job, register it, persist the accepted record, run it. `thread=False`
    runs it inline (tests, and any caller that wants the finished job back)."""
    job = Job(new_id(), ident["sub"], question, asof, quota_period=quota_period)
    register(job)
    job.emit("stage", stage="accepted")
    persist(store, job)
    if thread:
        threading.Thread(target=lambda: execute(job, graph=graph, store=store, respond=respond),
                         daemon=True).start()
    else:
        execute(job, graph=graph, store=store, respond=respond)
    return job


# ── cross-request reads (GET works after the accepting request is gone) ─────────────────────────────
def load(store, user: str, dossier_id: str) -> dict | None:
    """The persisted record for a dossier, or None. Reads the LIVE job first: an in-process job is
    always at least as fresh as its mirror (the mirror is written after transitions, the job IS the
    transition)."""
    job = get_job(dossier_id)
    if job is not None and job.user == user:
        return job.record()
    try:
        return store.get_item(user, KIND, dossier_id)
    except Exception:  # noqa: BLE001
        return None


def reap_orphan(store, user: str, rec: dict) -> dict:
    """v1 restart semantics, applied on READ: a persisted record in a NON-terminal state with no live
    job in this process can only be a job whose process died. Land it FAILED and refund the slot.

    On read rather than on boot BY DESIGN -- the task that restarted may not be the task that took the
    submission (an ECS replacement is a NEW task, and it has no way to enumerate another task's
    in-flight work). The read is where the truth is needed and where the user is waiting."""
    if rec.get("status") in TERMINAL or get_job(rec.get("dossier_id") or "") is not None:
        return rec
    rec = {**rec, "status": FAILED, "stage": FAILED,
           "error": "server restarted while this dossier was running; the monthly slot was refunded"}
    rec["events"] = list(rec.get("events") or []) + [{"type": FAILED, "ts": _now(),
                                                      "error": rec["error"]}]
    refund_quota(store, user, rec.get("quota_period"))
    try:
        store.put_item(user, KIND, rec.get("dossier_id"), {**rec, "updated_at": _now()})
    except Exception:  # noqa: BLE001
        pass
    return rec


def wire_snapshot(rec: dict) -> dict:
    """The GET body from a persisted record: the locked wire keys only (the stored record also carries
    the full plan, the event log and the quota period, which are not the client's business)."""
    out = {k: rec.get(k) for k in ("dossier_id", "status", "stage", "question", "asof", "created_at",
                                   "title") if rec.get(k) is not None}
    out["subqueries"] = [{"i": r.get("i"), "n": r.get("n"), "title": r.get("title"),
                          "status": r.get("status", SQ_PENDING)}
                         for r in (rec.get("subqueries") or [])]
    for k in ("artifact_id", "error"):
        if rec.get(k):
            out[k] = rec[k]
    return out
