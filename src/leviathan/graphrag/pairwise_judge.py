"""D-CC-2: the ceiling-raising instrument -- pairwise BLIND A/B judging + pre-registered checklists +
a deterministic width-conversion counter.

WHY THIS EXISTS. D-DV-2 measured both arms at a flat judged 4 on every width row while the wide arm
demonstrably REACHED material the lean arm structurally cannot (Russia export-tax prose on dv_xorigin,
the corn-side acreage tilt on dv_chain). The absolute 1-5 scale had no room left to say which answer was
better; the judge's free text named the reason verbatim -- "never delivers the FULL ranked list", "never
locates the convexity threshold", "fails to enumerate the dated episodes shown". Pairwise has NO ceiling
(there is always a winner or an explicit tie), needs no cross-run baseline comparability (both arms ride
ONE call), and the checklists turn those three sentences into bounded, auditable, pre-registered binary
metrics.

    python -m leviathan.graphrag.pairwise_judge \
        --a <baseline_arm_a.json> --b <baseline_arm_b.json> \
        --queries configs/graphrag/eval_queries_deepv2_width_v1.yaml \
        --checklists configs/graphrag/eval_checklists_deepv2_width_v1.yaml \
        --a-report <report_arm_a.md> --b-report <report_arm_b.md> \
        --out <report stem>                        # writes <stem>.json + <stem>.md
    ... --dry-run                                  # per-row plan, zero API calls, zero spend

ONE claude-opus-4-8 forced-tool call per row, temperature 0. The judge MODEL is frozen and this template
freezes BEFORE any arm runs (the pre-registration law -- see the checklist yaml's header).

--------------------------------------------------------------------------------------------------
WHAT THE JUDGE IS SHOWN, AND THE TWO PLACES THIS DIVERGES FROM eval.judge -- STATED ONCE, HONESTLY.

(1) THE ANSWER TEXT. eval.judge renders `out['answer']` verbatim (eval.py:1698). A stored baseline does
    NOT carry it: `eval._per_answer_record` (eval.py:1196-1265) is a hard whitelist with no `answer`, no
    `citations` and no `structured`. `render_answer_for_judge` therefore resolves the answer through a
    fidelity ladder (see its docstring) and STAMPS the provenance it used on every row of both reports,
    so no number here can be quoted without knowing which text produced it. The top two rungs are
    byte-exact recoveries of `out['answer']`; the lower rungs are labelled proxies.

(2) THE EVIDENCE PANELS. eval.judge also shows the causal graph, the dated evidence, the injected
    episodes and the observed-numbers panel (eval.py:1680-1698). NONE of those survive into a baseline
    either, so this instrument cannot fact-check against them and does not pretend to: `grounding` here
    is defined in the system prompt as HANDLE DISCIPLINE (does each claim carry a handle, does the
    answer's own cited-sources block support what the prose asserts), never as an external fact-check.
    The absolute 1-5 grounding score from the arm's own judged run stays the authority on that axis.

Both divergences are properties of the STORED ARTIFACT, not choices -- and both apply identically to
both arms, so the comparison stays symmetric (the _judge_episodes_panel symmetry argument, eval.py:1647).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
from pathlib import Path

import yaml

from leviathan.graphrag import eval as gev
from leviathan.graphrag import extract as ex

MODEL = "claude-opus-4-8"                       # frozen for this instrument; never read from env
AXES = ("usefulness", "grounding", "composition_completeness")
ARMS = ("A", "B")
_ORDER_SALT = "dcc2-pairwise-order-v1"          # bump ONLY with a new instrument version, never mid-wave

# The SAME split eval._prose uses (eval.py:546-547) to cut the '## Sources' footer off a rendered answer.
_SOURCES_SPLIT = re.compile(r"\n#{2,6}\s+Sources\b")


# ---------------------------------------------------------------------------------------------------
# Answer-text resolution
# ---------------------------------------------------------------------------------------------------
# provenance -> (is the text byte-identical to what the absolute judge saw?, one-line meaning)
PROVENANCE = {
    "answer": (True, "the baseline row carried out['answer'] verbatim"),
    "report_md": (True, "recovered from the run's report markdown '**A:**' block (eval.py:2243)"),
    "body_pre_sanitize": (True, "raw_draft['body_pre_sanitize'] -- the assembled body one sanitize pass "
                                "before out['answer'] (answer.py:1975); the render-seam pass dropped ZERO "
                                "bytes on all three measured rows 2026-08-04"),
    "verified_fields": (False, "PROXY: raw_draft verified_tldr+verified_mechanism re-rendered -- "
                               "post-verify, pre-humanize, NO cited-sources footer"),
    "raw_fields": (False, "PROXY: raw_draft tldr+mechanism re-rendered -- the PRE-verify PRE-sanitize "
                          "model draft, NO cited-sources footer"),
    "missing": (False, "no answer text recoverable for this row"),
}


def _render_fields(tldr: str, mechanism: str) -> str:
    """The tldr+mechanism half of a rendered answer.

    COPIED, NOT IMPORTED, and deliberately so: answer.render (answer.py:2033) takes the whole structured
    dict and also emits the mermaid block and the model's own '**Sources**' ledger -- neither of which a
    raw_draft carries, so calling it would render a DIFFERENT shape from the two draft strings that exist.
    This is the minimal two-field form of that same line, kept byte-aligned with it by
    tests/unit/test_pairwise_judge.py::test_render_fields_matches_answer_render.
    """
    return "\n".join([f"**TL;DR.** {(tldr or '').strip()}", "", f"**Why.** {(mechanism or '').strip()}"]).strip()


def render_answer_for_judge(row: dict, *, report_answers: dict | None = None) -> tuple[str, str]:
    """(answer_text, provenance) for ONE baseline per_answer row -- the text this instrument judges.

    THE FIDELITY LADDER, best first. Rungs 1-3 are byte-exact recoveries of `out['answer']` (the string
    eval.judge renders at eval.py:1698); rungs 4-5 are PROXIES and are labelled as such everywhere:
      1. row['answer']          -- a producer that stored it outright.
      2. report_answers[id]     -- the run's own report markdown, which renders out['answer'] verbatim
                                   (eval.py:2243). Supplied via --a-report/--b-report; NEVER auto-
                                   discovered, because pairing arm A with arm B's report would silently
                                   invert the whole measurement.
      3. raw_draft['body_pre_sanitize'] -- requires GRAPHRAG_DRAFT_BODY_AUDIT=on on the arm.
      4. raw_draft verified_tldr+verified_mechanism -- requires the same flag; no sources footer.
      5. raw_draft tldr+mechanism -- requires GRAPHRAG_STRIP_AUDIT=on; no sources footer.
    A row with none of them yields ("", "missing") rather than raising: one unreadable row must not lose
    the other five.
    """
    if isinstance(row.get("answer"), str) and row["answer"].strip():
        return row["answer"], "answer"
    rid = str(row.get("id"))
    got = (report_answers or {}).get(rid)
    if isinstance(got, str) and got.strip():
        return got, "report_md"
    rd = row.get("raw_draft") or {}
    if isinstance(rd, dict):
        body = rd.get("body_pre_sanitize")
        if isinstance(body, str) and body.strip():
            return body, "body_pre_sanitize"
        if (rd.get("verified_tldr") or rd.get("verified_mechanism")):
            return _render_fields(rd.get("verified_tldr") or "", rd.get("verified_mechanism") or ""), "verified_fields"
        if (rd.get("tldr") or rd.get("mechanism")):
            return _render_fields(rd.get("tldr") or "", rd.get("mechanism") or ""), "raw_fields"
    return "", "missing"


def parse_report_answers(md_text: str, ids) -> dict[str, str]:
    """{row_id: out['answer']} lifted from an eval report markdown.

    eval.report emits, per row (eval.py:2217 then 2243):
        ## <id>  (<category>)
        ... per-row bullets ...
        <blank>
        **A:**
        <blank>
        <out['answer']>
        <blank>
    The row ids are passed in (from the deck) so the header anchor is exact -- an answer body of its own
    contains '## Mechanism' / '## Sources' headings, so a bare '^## ' scan would shred it.

    RECOVERY IS BYTE-EXACT, with one declared edge: report() appends exactly ONE separator line after the
    answer, which this drops, so the round trip is lossless -- EXCEPT for an answer that itself ends in a
    newline AND is the report's LAST row, where markdown cannot tell that newline from the separator.
    """
    ids = [str(i) for i in ids]
    lines = md_text.splitlines()
    heads: list[tuple[int, str]] = []
    for n, ln in enumerate(lines):
        for rid in ids:
            if ln.startswith(f"## {rid}  ("):
                heads.append((n, rid))
                break
    out: dict[str, str] = {}
    for k, (start, rid) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        try:
            a = next(i for i in range(start, end) if lines[i].strip() == "**A:**")
        except StopIteration:
            continue
        block = lines[a + 2:end]                          # one blank line follows '**A:**' (eval.py:2243)
        if block and block[-1] == "":                     # ... and one separator precedes the next head
            block.pop()
        body = "\n".join(block)
        if body.strip():
            out[rid] = body
    return out


# ---------------------------------------------------------------------------------------------------
# Deterministic presentation order
# ---------------------------------------------------------------------------------------------------
def presentation_order(row_id: str, *, salt: str = _ORDER_SALT) -> tuple[str, str]:
    """(first_shown, second_shown) for a row -- deterministic in the row id, so a re-run reproduces the
    exact presentation the recorded verdicts were formed under. blake2b (not hash()) because CPython
    randomizes str hashing per process, which would make the order irreproducible across runs."""
    h = hashlib.blake2b(f"{salt}|{row_id}".encode("utf-8"), digest_size=8).digest()
    return ("A", "B") if h[0] % 2 == 0 else ("B", "A")


def _to_arm(label: str, order: tuple[str, str]) -> str:
    """'ANSWER_1'/'ANSWER_2'/'tie' -> 'A'/'B'/'tie' under this row's presentation order."""
    if label == "ANSWER_1":
        return order[0]
    if label == "ANSWER_2":
        return order[1]
    return "tie"


# ---------------------------------------------------------------------------------------------------
# The judge call
# ---------------------------------------------------------------------------------------------------
_PAIRWISE_SYS = (
    "You are a SENIOR QUANTITATIVE RESEARCHER comparing TWO answers from a FUNDAMENTAL CONVEXITY-SHOCK "
    "research tool (NOT a trading system). The tool helps researchers understand HOW supply/demand shocks "
    "propagate through commodity balance sheets and WHERE the price response turns convex (buffer "
    "exhaustion, tipping thresholds, regime switches). You are shown the QUESTION (with any as-of date) "
    "and two answers labelled ANSWER 1 and ANSWER 2, in a randomized order. You do NOT know which system "
    "produced which, the order carries no information, and you must never speculate about it.\n"
    "CRITICAL SCOPE: this is a research tool -- do NOT expect or reward position sizing, price targets, "
    "or 'how much to trade'; that is OUT OF SCOPE and an execution instruction is a defect. Reward "
    "mechanism, convexity/regime insight, point-in-time discipline, enumeration honesty and grounding.\n"
    "\n"
    "Pick a winner on each axis. 'tie' is available and is the CORRECT answer when the two are genuinely "
    "indistinguishable on that axis -- but do not reach for it to avoid a call: length is not quality, and "
    "a shorter answer that covers the record completely beats a longer one that does not.\n"
    "- usefulness: which answer gives a researcher more real insight into the shock's STRUCTURE -- the "
    "mechanism, the drivers that matter, the regime -- rather than vague restatement or textbook filler?\n"
    "- grounding: which answer keeps better HANDLE DISCIPLINE? You are NOT shown the retrieved evidence, "
    "so do NOT fact-check either answer against outside knowledge and do NOT reward a claim merely for "
    "sounding right. Judge only what is visible: does each specific claim (driver, sign, dated number, "
    "policy instrument, episode) carry a citation handle; does the answer's own cited-sources block "
    "support what its prose asserts; are unbacked statements declared as such rather than smuggled in? "
    "An answer that says plainly 'the record shows no dated row for this' is MORE grounded than one that "
    "asserts the same point from nothing.\n"
    "- composition_completeness (the axis this instrument exists for): given the material each answer "
    "itself puts on the page, which one COMPOSES it completely? Three named failure modes, and an answer "
    "is penalized for each one it commits:\n"
    "  (a) RANK-INCOMPLETE -- the question demands an enumerable set and the answer does not cover every "
    "entity it itself raises, one line each with its number/odds, naming any entity it cannot rank ('no "
    "dated row at the as-of'). Collapsing entities into an 'other' bucket is the failure.\n"
    "  (b) THRESHOLD-ABSENT -- the answer never locates WHERE the relationship turns nonlinear (a level, "
    "ratio or buffer with the handle backing it) AND never states plainly that the record cannot locate "
    "it. Saying the record cannot locate the threshold is a PASS on this element, never a hedge; "
    "inventing a threshold with nothing behind it is the worst case and is also a grounding failure.\n"
    "  (c) EPISODES-SMOOTHED -- the answer refers to dated windows and then generalises over them "
    "('multiple windows from the early 2010s onward') instead of enumerating each as its own dated item, "
    "including the thin ones, with any window carrying no citable item stated as such.\n"
    "An answer that reaches wider material and then buries it in prose is WORSE composed than one that "
    "reaches less and lays out everything it has.\n"
    "\n"
    "Then answer the CHECKLIST, if one is supplied, ITEM BY ITEM for BOTH answers independently: true or "
    "false plus one short line of evidence quoting or pointing at the part of that answer which decides "
    "it. The checklist was written before either answer existed; answer exactly what each item asks, do "
    "not soften it, and do not let one answer's result influence the other's. An item whose question "
    "offers a 'or states that the record cannot' branch is TRUE when the answer takes that branch.\n"
    "Keep every rationale to one or two blunt sentences. Emit via pairwise_verdict."
)


def _pairwise_tool(items: list[dict] | None) -> dict:
    verd = {"type": "string", "enum": ["ANSWER_1", "ANSWER_2", "tie"]}
    props: dict = {}
    required: list[str] = []
    for ax in AXES:
        props[ax] = verd
        props[f"{ax}_rationale"] = {"type": "string"}
        required += [ax, f"{ax}_rationale"]
    if items:
        props["checklist"] = {
            "type": "array",
            "description": "one entry per supplied checklist item, in the order given",
            "items": {"type": "object",
                      "properties": {"item_id": {"type": "string"},
                                     "answer_1": {"type": "boolean"}, "evidence_1": {"type": "string"},
                                     "answer_2": {"type": "boolean"}, "evidence_2": {"type": "string"}},
                      "required": ["item_id", "answer_1", "answer_2"]}}
        required.append("checklist")
    return {"name": "pairwise_verdict",
            "description": "A senior quant RESEARCHER's blind head-to-head verdict on two answers.",
            "input_schema": {"type": "object", "properties": props, "required": required}}


def build_prompt(question: str, asof, text_first: str, text_second: str, items: list[dict] | None) -> str:
    """The user turn: question, both answers under neutral labels, then the checklist."""
    lines = [f"QUESTION: {question}",
             f"(as-of date: {asof or 'none'})",
             "",
             "=== ANSWER 1 ===",
             text_first or "(no answer text recoverable for this arm)",
             "",
             "=== ANSWER 2 ===",
             text_second or "(no answer text recoverable for this arm)",
             ""]
    if items:
        lines += ["=== CHECKLIST (answer EVERY item for BOTH answers, independently) ==="]
        lines += [f"- {it['id']}: {str(it['ask']).strip()}" for it in items]
        lines += [""]
    return "\n".join(lines)


def judge_pair(question: str, asof, text_first: str, text_second: str, items: list[dict] | None, *,
               client=None, model: str = MODEL, call=None, max_tokens: int = 4096):
    """ONE forced-tool call. `call` defaults to ex.call_opus -- the SAME helper eval.judge uses
    (eval.py:1665), with the same cached-system-block idiom (eval.py:1699) so the two instruments share
    prompt-cache behaviour. temperature is pinned 0 (call_opus forwards it only when provided,
    extract.py:499). Returns (verdict_dict, usage)."""
    call = call or ex.call_opus
    sys_blocks = [{"type": "text", "text": _PAIRWISE_SYS, "cache_control": {"type": "ephemeral"}}]
    # temperature deliberately NOT sent: claude-opus-4-8 rejects the parameter with a 400
    # (deprecated on 4.8+; measured live 2026-08-07 on all 18 rows). Verdict determinism rests on
    # the forced-tool schema + the frozen template, same as eval.judge, which also sends none.
    return call(client, sys_blocks, build_prompt(question, asof, text_first, text_second, items),
                model=model, max_tokens=max_tokens, tool=_pairwise_tool(items))


# ---------------------------------------------------------------------------------------------------
# Deterministic width-conversion counter (no LLM)
# ---------------------------------------------------------------------------------------------------
def split_sources_block(answer_text: str) -> tuple[str, str]:
    """(body, cited_sources_block) for a rendered answer, cut on the same '## Sources' header
    eval._prose splits on (eval.py:546-547). An answer with no footer yields (whole_text, "")."""
    parts = _SOURCES_SPLIT.split(str(answer_text or ""), maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _entry_hit(hay: str, markers: list[str], context: list[str]) -> bool:
    if not markers:
        return False
    if not any(m in hay for m in markers):
        return False
    return (not context) or any(c in hay for c in context)


def count_conversion(answer_text: str, entries: list[dict]) -> dict:
    """Per-arm width-conversion count against a row's documented beyond-quick source families.

    THIS IS A LEXICAL PROXY AND SAYS SO IN ITS OWN OUTPUT (`proxy: True`). The honest counter the plan
    asks for -- cited handles hitting the beyond-reach set -- needs the turn's citation source_keys, and
    those are NOT in a stored baseline: eval._per_answer_record (eval.py:1196-1265) is a hard whitelist
    carrying no `citations` and no `structured.sources`, and the rendered '## Sources' footer prints human
    labels ("USDA FAS GAIN Report - Wheat (2026-04-02)") plus the cited prop's TEXT, never the slice id.
    So each family's own vocabulary (`markers`, optionally AND-gated by `context_markers`) is matched:
      * cited_hits -- against the cited-sources footer, which IS the text of the props the answer cited.
        This is the headline conversion number.
      * body_hits  -- against everything before that footer. A family present in the body but absent from
        the footer is reported under `asserted_uncited`: the material was narrated without a citation,
        which is a finding in its own right and must never be counted as conversion.
    Matching runs on ex._normalize'd text (NFKD -> ascii -> lower, whitespace/underscore/hyphen collapsed),
    so 'stocks-to-use' and 'La Nina' match their normalized markers.
    """
    body, srcs = split_sources_block(answer_text)
    nb, ns = ex._normalize(body), ex._normalize(srcs)
    per: dict[str, dict] = {}
    for e in entries or []:
        mk = [ex._normalize(m) for m in (e.get("markers") or [])]
        cx = [ex._normalize(m) for m in (e.get("context_markers") or [])]
        per[str(e.get("key"))] = {"width_basis": e.get("width_basis"),
                                  "cited": _entry_hit(ns, mk, cx), "body": _entry_hit(nb, mk, cx)}
    cited = sorted(k for k, v in per.items() if v["cited"])
    inbody = sorted(k for k, v in per.items() if v["body"])
    return {"proxy": True, "scope": "cited_sources_block",
            "n_documented": len(per), "cited_hits": len(cited), "body_hits": len(inbody),
            "cited": cited, "asserted_uncited": sorted(set(inbody) - set(cited)), "per_source": per,
            "has_sources_block": bool(srcs.strip())}


# ---------------------------------------------------------------------------------------------------
# Config loading + schema validation
# ---------------------------------------------------------------------------------------------------
def load_checklists(path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def validate_checklists(cfg: dict, queries: list[dict]) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors abort the run: an instrument that does not schema-match the deck it was
    pre-registered against is not the instrument that was pre-registered."""
    errs: list[str] = []
    warns: list[str] = []
    for k in ("checklist_version", "deck", "rows"):
        if not cfg.get(k):
            errs.append(f"checklists: missing top-level key '{k}'")
    deck_ids = [str(q.get("id")) for q in queries]
    rows = cfg.get("rows") or []
    if not isinstance(rows, list):
        return errs + ["checklists: 'rows' must be a list"], warns
    seen: set[str] = set()
    for r in rows:
        rid = str((r or {}).get("id"))
        if rid in seen:
            errs.append(f"checklists: duplicate row id '{rid}'")
        seen.add(rid)
        if rid not in deck_ids:
            errs.append(f"checklists: row '{rid}' is not a deck row id")
        items = r.get("items") or []
        if not 3 <= len(items) <= 6:
            errs.append(f"checklists[{rid}]: {len(items)} items (the pre-registration law says 3-6)")
        iseen: set[str] = set()
        for it in items:
            iid = str((it or {}).get("id") or "")
            if not iid or not str((it or {}).get("ask") or "").strip():
                errs.append(f"checklists[{rid}]: an item is missing 'id' or 'ask'")
            if iid in iseen:
                errs.append(f"checklists[{rid}]: duplicate item id '{iid}'")
            iseen.add(iid)
        kseen: set[str] = set()
        for e in r.get("beyond_quick_sources") or []:
            key = str((e or {}).get("key") or "")
            if not key:
                errs.append(f"checklists[{rid}]: a beyond_quick_sources entry is missing 'key'")
            if key in kseen:
                errs.append(f"checklists[{rid}]: duplicate beyond_quick_sources key '{key}'")
            kseen.add(key)
            if not (e or {}).get("markers"):
                errs.append(f"checklists[{rid}]: beyond_quick_sources '{key}' has no markers "
                            "(the counter would score it 0 for every arm)")
    for qid in deck_ids:
        if qid not in seen:
            warns.append(f"deck row '{qid}' has no checklist entry -- it contributes no checklist or "
                         "conversion numbers")
    return errs, warns


def rows_by_id(baseline: dict) -> dict[str, dict]:
    return {str(r.get("id")): r for r in (baseline.get("per_answer") or [])}


def arm_identity(path, baseline: dict) -> dict:
    """The reproducibility keys that say WHICH arm a baseline is (see eval._baseline_json)."""
    return {"path": str(path),
            "eval_set": baseline.get("eval_set"), "ts": baseline.get("ts"), "mode": baseline.get("mode"),
            "model": baseline.get("model"), "provider": baseline.get("provider"),
            "git_commit": baseline.get("git_commit"), "corpus_fingerprint": baseline.get("corpus_fingerprint"),
            "graph_version": baseline.get("graph_version"), "n_answers": baseline.get("n_answers"),
            "strip_rate": baseline.get("strip_rate"), "handle_strip_rate": baseline.get("handle_strip_rate")}


# ---------------------------------------------------------------------------------------------------
# Plan (shared by --dry-run and the live run so they can never diverge)
# ---------------------------------------------------------------------------------------------------
def build_plan(queries: list[dict], a_rows: dict, b_rows: dict, checks: dict, *,
               a_report: dict | None = None, b_report: dict | None = None,
               salt: str = _ORDER_SALT) -> list[dict]:
    by_check = {str(r.get("id")): r for r in (checks.get("rows") or [])}
    plan: list[dict] = []
    for q in queries:
        rid = str(q.get("id"))
        ta, pa = render_answer_for_judge(a_rows.get(rid) or {"id": rid}, report_answers=a_report)
        tb, pb = render_answer_for_judge(b_rows.get(rid) or {"id": rid}, report_answers=b_report)
        c = by_check.get(rid) or {}
        order = presentation_order(rid, salt=salt)
        plan.append({"id": rid, "question": q.get("question"), "asof": q.get("asof"),
                     "order": {"first": order[0], "second": order[1]},
                     "text": {"A": ta, "B": tb}, "provenance": {"A": pa, "B": pb},
                     "items": c.get("items") or [],
                     "beyond_quick_sources": c.get("beyond_quick_sources") or [],
                     "width_class": c.get("width_class")})
    return plan


def _dry_run_lines(plan: list[dict], model: str) -> list[str]:
    lines = ["PAIRWISE DRY RUN -- no API calls, no spend", ""]
    for p in plan:
        o = p["order"]
        lines.append(f"{p['id']}: shows {o['first']} first, then {o['second']} | "
                     f"A text {len(p['text']['A'])} chars via {p['provenance']['A']} | "
                     f"B text {len(p['text']['B'])} chars via {p['provenance']['B']} | "
                     f"{len(p['items'])} checklist items | "
                     f"{len(p['beyond_quick_sources'])} documented beyond-quick sources")
        for arm in ARMS:
            if not PROVENANCE.get(p["provenance"][arm], (False, ""))[0]:
                lines.append(f"    WARN {arm}: {PROVENANCE.get(p['provenance'][arm], (False, 'unknown'))[1]}")
    pin, pout = gev._PRICE.get(model, gev._PRICE[MODEL])
    est = sum((len(p["text"]["A"]) + len(p["text"]["B"])) / 4.0 + 1200 for p in plan) * pin \
        + len(plan) * 900 * pout
    lines += ["", f"{len(plan)} rows x 1 {model} call, est ~${est:.2f}"]
    return lines


# ---------------------------------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------------------------------
def _tally(results: list[dict]) -> dict:
    t = {ax: {"A": 0, "B": 0, "tie": 0} for ax in AXES}
    for r in results:
        for ax in AXES:
            w = (r.get("verdicts") or {}).get(ax, {}).get("winner")
            if w in t[ax]:
                t[ax][w] += 1
    return t


def _checklist_rates(results: list[dict]) -> dict:
    out = {}
    for arm in ARMS:
        n = sum(len(r.get("checklist") or []) for r in results)
        p = sum(1 for r in results for it in (r.get("checklist") or []) if it.get(arm) is True)
        out[arm] = {"passed": p, "answered": n, "pass_rate": round(p / n, 4) if n else None}
    return out


def _conversion_totals(results: list[dict]) -> dict:
    out = {}
    for arm in ARMS:
        cited = sum((r.get("conversion") or {}).get(arm, {}).get("cited_hits", 0) for r in results)
        docd = sum((r.get("conversion") or {}).get(arm, {}).get("n_documented", 0) for r in results)
        out[arm] = {"cited_hits": cited, "n_documented": docd,
                    "rate": round(cited / docd, 4) if docd else None,
                    # a turn that rendered no '## Sources' footer scores 0 for the trivial reason that
                    # there was nothing citable to match against -- never read as failed conversion
                    "rows_without_sources_block": sum(
                        1 for r in results
                        if (r.get("conversion") or {}).get(arm, {}).get("has_sources_block") is False)}
    out["rows_arm_ahead"] = {
        arm: sum(1 for r in results
                 if (r.get("conversion") or {}).get(arm, {}).get("cited_hits", 0)
                 > (r.get("conversion") or {}).get("B" if arm == "A" else "A", {}).get("cited_hits", 0))
        for arm in ARMS}
    return out


def run_rows(plan: list[dict], *, client=None, model: str = MODEL, max_tokens: int = 4096,
             call=None) -> list[dict]:
    """One judged row per plan entry. The deterministic conversion count is computed FIRST and outside
    the try, so a failed judge call still yields the row's counter (a partial read stays readable), and
    one bad row can never lose the other five."""
    results: list[dict] = []
    for p in plan:
        first, second = p["order"]["first"], p["order"]["second"]
        row = {"id": p["id"], "question": p["question"], "asof": p["asof"], "order": p["order"],
               "provenance": p["provenance"], "width_class": p.get("width_class"),
               "conversion": {arm: count_conversion(p["text"][arm], p["beyond_quick_sources"])
                              for arm in ARMS},
               "verdicts": {}, "checklist": []}
        try:
            v, usage = judge_pair(p["question"], p["asof"], p["text"][first], p["text"][second],
                                  p["items"], client=client, model=model, max_tokens=max_tokens,
                                  call=call)
            order = (first, second)
            row["verdicts"] = {ax: {"winner": _to_arm(str(v.get(ax)), order),
                                    "shown_label": v.get(ax),
                                    "rationale": v.get(f"{ax}_rationale")} for ax in AXES}
            asked = {str(it["id"]) for it in p["items"]}
            got: set[str] = set()
            for e in (v.get("checklist") or []):
                iid = str(e.get("item_id"))
                got.add(iid)
                if iid not in asked:                       # a fabricated item never enters the pass-rate
                    continue
                row["checklist"].append({"item_id": iid,
                                         first: bool(e.get("answer_1")), second: bool(e.get("answer_2")),
                                         f"evidence_{first}": e.get("evidence_1"),
                                         f"evidence_{second}": e.get("evidence_2")})
            if asked - got:
                row["missing_items"] = sorted(asked - got)
            row["usage"] = {"in": getattr(usage, "input_tokens", None),
                            "out": getattr(usage, "output_tokens", None)} if usage else None
            print(f"  judged {p['id']} (first={first})", flush=True)
        except Exception as e:                             # noqa: BLE001 -- one bad row must not lose the rest
            row["error"] = str(e)[:300]
            print(f"  WARN pairwise {p['id']} failed -- {str(e)[:120]}", flush=True)
        results.append(row)
    return results


def build_report(results: list[dict], *, arms: dict, deck: str, checklist_version: str | None,
                 model: str, salt: str) -> dict:
    return {"kind": "pairwise_judge", "instrument": "dcc2_pairwise_v1",
            "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "judge_model": model, "temperature": 0, "deck": deck,
            "checklist_version": checklist_version, "order_salt": salt,
            "arms": arms, "axes": list(AXES),
            "totals": _tally(results), "checklist": _checklist_rates(results),
            "conversion": _conversion_totals(results),
            # the blind is per-row-id deterministic, NOT balanced -- record the split so a reader can see
            # how much residual position bias the run carries (6 rows will rarely come out 3/3)
            "order_balance": {arm: sum(1 for r in results if r["order"]["first"] == arm) for arm in ARMS},
            "order_log": [{"id": r["id"], "first": r["order"]["first"], "second": r["order"]["second"]}
                          for r in results],
            "provenance_log": [{"id": r["id"], "A": r["provenance"]["A"], "B": r["provenance"]["B"]}
                               for r in results],
            "rows": results}


def report_md(rep: dict) -> str:
    L: list[str] = ["# D-CC-2 pairwise blind judge -- " + str(rep.get("deck")), ""]
    a, b = rep["arms"]["A"], rep["arms"]["B"]
    L += [f"- judge `{rep['judge_model']}` temperature 0 | instrument `{rep['instrument']}` | "
          f"checklists `{rep.get('checklist_version')}` | order salt `{rep['order_salt']}`",
          f"- **arm A**: `{a.get('path')}` (mode={a.get('mode')}, ts={a.get('ts')}, "
          f"commit={a.get('git_commit')}, s/h={a.get('handle_strip_rate')})",
          f"- **arm B**: `{b.get('path')}` (mode={b.get('mode')}, ts={b.get('ts')}, "
          f"commit={b.get('git_commit')}, s/h={b.get('handle_strip_rate')})", ""]
    L += ["## Pairwise tallies (per axis, non-tie = a decided row)", "",
          "| axis | A | B | tie |", "|---|---|---|---|"]
    for ax in AXES:
        t = rep["totals"][ax]
        L.append(f"| {ax} | {t['A']} | {t['B']} | {t['tie']} |")
    L += ["", "## Per-row verdicts", "",
          "| row | shown first | usefulness | grounding | composition_completeness |", "|---|---|---|---|---|"]
    for r in rep["rows"]:
        v = r.get("verdicts") or {}
        L.append(f"| {r['id']} | {r['order']['first']} | "
                 + " | ".join(str(v.get(ax, {}).get("winner", "-")) for ax in AXES) + " |")
    ck = rep["checklist"]
    L += ["", "## Checklist pass-rate (the headline metric -- pre-registered, binary, bounded)", "",
          "| arm | passed | answered | pass rate |", "|---|---|---|---|"]
    for arm in ARMS:
        c = ck[arm]
        L.append(f"| {arm} | {c['passed']} | {c['answered']} | "
                 f"{'-' if c['pass_rate'] is None else format(c['pass_rate'] * 100, '.1f') + '%'} |")
    L += ["", "### Per-row checklist detail", ""]
    for r in rep["rows"]:
        if not (r.get("checklist") or []):
            continue
        L += [f"**{r['id']}**", "", "| item | A | B |", "|---|---|---|"]
        for it in r["checklist"]:
            L.append(f"| {it['item_id']} | {'PASS' if it.get('A') else 'fail'} | "
                     f"{'PASS' if it.get('B') else 'fail'} |")
        L.append("")
    cv = rep["conversion"]
    L += ["## Width-conversion counter (DETERMINISTIC, no LLM -- LEXICAL PROXY, see module docstring)", "",
          "| arm | cited hits | documented | rate | rows ahead |", "|---|---|---|---|---|"]
    for arm in ARMS:
        c = cv[arm]
        L.append(f"| {arm} | {c['cited_hits']} | {c['n_documented']} | "
                 f"{'-' if c['rate'] is None else format(c['rate'] * 100, '.1f') + '%'} | "
                 f"{cv['rows_arm_ahead'][arm]} |")
    L += ["", f"Rows whose answer rendered NO cited-sources footer (conversion unmeasurable, not failed): "
              f"A {cv['A']['rows_without_sources_block']}, B {cv['B']['rows_without_sources_block']}.", "",
          "| row | A cited | B cited | documented | A footer | B footer | A asserted-uncited | "
          "B asserted-uncited |", "|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        c = r.get("conversion") or {}
        ca, cb = c.get("A") or {}, c.get("B") or {}
        L.append(f"| {r['id']} | {ca.get('cited_hits', 0)} | {cb.get('cited_hits', 0)} | "
                 f"{ca.get('n_documented', 0)} | {'yes' if ca.get('has_sources_block') else 'NONE'} | "
                 f"{'yes' if cb.get('has_sources_block') else 'NONE'} | "
                 f"{', '.join(ca.get('asserted_uncited') or []) or '-'} | "
                 f"{', '.join(cb.get('asserted_uncited') or []) or '-'} |")
    L += ["", "## Presentation order + answer-text provenance", "",
          f"Blind split: A shown first on {rep['order_balance']['A']} rows, B on "
          f"{rep['order_balance']['B']} (deterministic per row id, not balanced).", "",
          "| row | shown first | A text from | B text from |", "|---|---|---|---|"]
    for r in rep["rows"]:
        L.append(f"| {r['id']} | {r['order']['first']} | {r['provenance']['A']} | {r['provenance']['B']} |")
    L += ["", "Provenance meanings (exact = byte-identical to the text the absolute judge saw):", ""]
    for k, (exact, meaning) in PROVENANCE.items():
        L.append(f"- `{k}` -- {'EXACT' if exact else 'PROXY'}: {meaning}")
    L += ["", "## Rationales", ""]
    for r in rep["rows"]:
        L.append(f"### {r['id']}")
        for ax in AXES:
            v = (r.get("verdicts") or {}).get(ax, {})
            L.append(f"- **{ax}: {v.get('winner', '-')}** -- {v.get('rationale', '')}")
        if r.get("error"):
            L.append(f"- **ERROR:** {r['error']}")
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="D-CC-2 pairwise blind judge (A/B, checklists, conversion)")
    ap.add_argument("--a", required=True, help="arm A baseline json")
    ap.add_argument("--b", required=True, help="arm B baseline json")
    ap.add_argument("--queries", required=True, help="the deck yaml both arms ran")
    ap.add_argument("--checklists", default=None, help="pre-registered checklist yaml")
    ap.add_argument("--out", required=True, help="report stem -- writes <stem>.json and <stem>.md")
    ap.add_argument("--a-report", default=None, help="arm A's eval report md (exact answer-text recovery)")
    ap.add_argument("--b-report", default=None, help="arm B's eval report md (exact answer-text recovery)")
    ap.add_argument("--model", default=MODEL, help="judge model (frozen -- change only with a new instrument)")
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--order-salt", default=_ORDER_SALT)
    ap.add_argument("--dry-run", action="store_true", help="print the per-row plan; no API calls, no spend")
    args = ap.parse_args()

    queries = gev.load_queries(Path(args.queries))
    a_base = json.loads(Path(args.a).read_text(encoding="utf-8"))
    b_base = json.loads(Path(args.b).read_text(encoding="utf-8"))
    checks = load_checklists(args.checklists) if args.checklists else {"rows": []}
    if args.checklists:
        errs, warns = validate_checklists(checks, queries)
        for w in warns:
            print(f"  WARN {w}", flush=True)
        if errs:
            for e in errs:
                print(f"  ERROR {e}", flush=True)
            raise SystemExit("checklist validation failed -- refusing to judge against a mismatched instrument")
    ids = [str(q.get("id")) for q in queries]
    a_rep = parse_report_answers(Path(args.a_report).read_text(encoding="utf-8"), ids) if args.a_report else None
    b_rep = parse_report_answers(Path(args.b_report).read_text(encoding="utf-8"), ids) if args.b_report else None
    plan = build_plan(queries, rows_by_id(a_base), rows_by_id(b_base), checks,
                      a_report=a_rep, b_report=b_rep, salt=args.order_salt)

    if args.dry_run:
        print("\n".join(_dry_run_lines(plan, args.model)), flush=True)
        return 0

    import anthropic

    from leviathan.graphrag import batch_extract as bx
    from leviathan.graphrag import providers as pv

    # SAME client construction as eval's judge lane (eval.py:2678): the key is read from the environment
    # at call time (ANTHROPIC_API / ANTHROPIC_API_KEY) and never stored anywhere in this module.
    client = anthropic.Anthropic(api_key=bx._api_key(), timeout=pv._client_timeout(), max_retries=0)

    results = run_rows(plan, client=client, model=args.model, max_tokens=args.max_tokens)
    rep = build_report(results, arms={"A": arm_identity(args.a, a_base), "B": arm_identity(args.b, b_base)},
                       deck=Path(args.queries).stem, checklist_version=checks.get("checklist_version"),
                       model=args.model, salt=args.order_salt)
    stem = Path(args.out)
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    stem.with_suffix(".md").write_text(report_md(rep), encoding="utf-8")
    t = rep["totals"]
    print(f"wrote {stem.with_suffix('.json')} + {stem.with_suffix('.md')}", flush=True)
    for ax in AXES:
        print(f"  {ax}: A {t[ax]['A']} / B {t[ax]['B']} / tie {t[ax]['tie']}", flush=True)
    ck = rep["checklist"]
    print(f"  checklist pass-rate: A {ck['A']['pass_rate']} B {ck['B']['pass_rate']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
