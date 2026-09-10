"""THE SUBJECT-RESOLVER DECK RUNNER -- D9's two layers and D10's latency bar, one instrument.

Design: docs/private/SUBJECT_RESOLVER_SITTING_2026-09-09.md (D9 the deck and the pre-registered bars,
D10 the latency budget, D11 phase B's scope). Phase A is commit 69b95316; this is phase B's measurer.

THE SHAPE IS `scripts/xc_planner_soak.py`'s, deliberately and to the letter: pre-registered bars graded
IN CODE, a `--dry-run` that prints the exact call plan and the dollar estimate BEFORE anything is spent,
a verdict vocabulary of {LAND-DARK, STOP} that this script cannot widen, ASCII-only stdout, and an
artifact written for offline re-audit. What it adds is a FREE layer and a FREE latency harness, so most
of what it measures costs nothing at all.

  --layer 1      THE DETERMINISTIC TIERS. `subject.exact_ids` + `alias_ids` + `semantic_candidates` on
                 the real vocabulary artifact. No LLM, no network, no spend. This is the instrument
                 that was frozen in phase A, re-run here against whatever deck is handed to it.
  --layer 2      THE PLANNER. `dispatch.plan_turn` with the resolver's two kwargs threaded -- the same
                 wiring `orchestrator.py` does under GRAPHRAG_SUBJECT_RESOLVER -- at the pinned seat
                 (claude-sonnet-4-6, temperature 0 through `dispatch._temp_kw`, `max_contracts` at the
                 deck's own tier). `--draws 3`, a row passes at >= 2 of 3. THIS is the billed half.
  --latency      D10. The ADDED WALL PER TURN, flag off against flag on, over the deck's own phrases.
                 Free.

WHAT LAYER 2 IS FOR, said plainly. Layer 1 measures whether the tiers put the right driver in front of
the planner. It cannot measure what the planner DOES with the list, and the phase-A bank names the open
risk in terms: 12 of 18 held-out decoy rows still put a candidate above CAND_FLOOR in front of the
planner (zero above AMBIG_FLOOR, so the carry is clean). A decoy the PLANNER picks is a board anchored
on a question that named no driver, and that is the one failure this layer exists to price. It is a
FATAL bar, not a rate.

THE D10 MEASUREMENT, AND WHY IT IS A DIFFERENCE AND NOT A DURATION. `resolve()` runs BEFORE
`plan_turn`, so on the first call of a turn `evidence._Q_CACHE` is COLD and the resolver -- not the
walk -- is the caller that fills it (phase A addendum A1, measured p50 351 / p90 387 ms). But the walk
re-embeds the SAME verbatim query one call later and hits the memo the resolver just filled, measured
at 0.007 ms. So the resolver's own wall is mostly a cost the turn was going to pay anyway, and D10's
budget -- "<= 150 ms ADDED per turn, flag on, p90" -- is stated over the difference. Both figures are
banked: `ms_board_subject_ms` is the counter production will see (the resolver's own wall, cold), and
`added_wall_per_turn_ms` is what the flag actually costs a walking lane and what the bar is graded on.
`config_check.check_subject_resolver` clause (13) reads the newest bank and reds above the budget.

NO HELD-OUT PHRASE IS EVER WRITTEN INTO THE TREE. The scratchpad artifact carries per-row detail; the
in-tree bank under `data/subject_resolver/<date>/` carries CLASS-LEVEL COUNTS AND NOTHING ELSE -- no
phrase, no row id, no expected id. The `test_p65`-style absence pin in `tests/unit/test_subject_
resolver.py` stays green by construction.

USAGE (the owner's shell is Windows PowerShell 5.1: chain with `;`, never `&&`)
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --deck configs/graphrag/subject_deck_v1.yaml --layer both --dry-run
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --deck configs/graphrag/subject_deck_v1.yaml --layer 1
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --deck configs/graphrag/subject_deck_v1.yaml --latency
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --deck <heldout> --layer 2

THE INSTRUMENT IS FENCED BEFORE THE MEASUREMENT IS. `artifact: ok` grades THE FILE; the embedder is a
different failure, and when it dies `semantic_candidates` returns `unreadable` with zero candidates on
every phrase while `load_vocab` in the same process still says `ok`. That state scores, verdicts and
banks a VACUOUS run with every class at its lexical floor -- and at layer 2 it BILLS a planner call per
draw on a hint line that is the empty string. So the per-row `vocab_status` census is read after layer
1 and a single decline REFUSES the run: nothing is banked, nothing is spent, and a diagnostic marked
NON-CERTIFYING is written to the scratchpad instead. See :func:`instrument_census`.

ANTHROPIC_API_KEY is read from the environment and NEVER printed, logged or written to an artifact.
Exit codes: 0 = ran, every evaluated bar PASS (verdict LAND-DARK); 1 = a bar STOPped; 2 = refused
before spending (a missing deck, a bad flag, no key, a stale artifact, or a DEAD INSTRUMENT).
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import statistics
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:                    # direct `python scripts/graphrag/...`
    sys.path.insert(0, str(_REPO / "src"))

import yaml  # noqa: E402

# ── the pinned seat (D9 layer 2) ─────────────────────────────────────────────────────────────────
# The SAME seat the xc soak pins and for the same reason: the treatment here is a PROMPT SECTION plus
# a schema enum, so a seat that moves would move with it and nothing would be attributable.
SEAT = "claude-sonnet-4-6"
TEMPERATURE = 0
DEFAULT_MAX_CONTRACTS = 2                                 # dispatch.MAX_CONTRACTS, the shipped tier
PER_CALL_USD = 0.01                                       # the planner's per-call anchor (xc round 3)
HARD_CAP_USD = 12.0                                       # the sitting's stated ceiling
DEFAULT_TODAY = "2026-09-10"

SCRATCH = Path("C:/Users/User/AppData/Local/Temp/claude/"
               "C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad/"
               "subject_run")
BANK = _REPO / "data" / "subject_resolver"

#: D9's LAYER-1 bars, by class. `exact` and `alias` are stated over the FREE tiers (T0/T1), every other
#: class over the top-5 candidate list or the union of all three tiers -- the deck header states which.
L1_BARS = {"exact": 1.00, "alias": 1.00, "synonym": 0.90, "misspelling": 0.85,
           "description": 0.75, "acronym": 1.00}
#: D9's LAYER-2 bars, quoted from the spec. `near_duplicate` and `multi` are GROUP bars, not id bars.
L2_BARS = {"synonym": 0.90, "misspelling": 0.85, "description": 0.70,
           "near_duplicate": 1.00, "multi": 1.00}
#: HOW MANY SEPARATE CAUSES A `multi` ROW NAMES -- the class's own contract, quoted from the deck that
#: declares it: "MULTI -- the owner's 'multiple named drivers -> a list, and the boards union'. Two
#: SEPARATE groups, not two names for one thing (that is near_duplicate, one subject)." The count is a
#: CONSTANT here and not a count of the expect list, because the expect list is a list of ALTERNATIVES
#: (:func:`score_layer2`) and its length says nothing about how many causes the ask names: `mu02` lists
#: three ids for two causes. A deck may override it per row with a `concepts:` key -- a list of the
#: alternative-sets, one per cause -- and neither shipped deck carries one, so both are scored at two.
#: THE LIMITATION IS STATED RATHER THAN HIDDEN: a `multi` row that named THREE causes would be scored
#: against two here and would pass one cause short. Every scored row's `expected_groups` and
#: `groups_reached` ride the per-row record, so the reading is auditable off the bank without a re-run.
MULTI_MIN_CONCEPTS = 2
#: The like-for-like lexical baseline, MEASURED in the recon over its own thirty phrases and reproduced
#: to the row by phase A. Printed beside every result table so the uplift is never quoted from memory.
LEXICAL_BASELINE = {"any_hit_pct": 30.0, "hit_at_1_pct": 23.3,
                    "note": "the shipped driver matcher over the recon's 30 synonym/misspelling/"
                            "description phrases (BRIEF.md sec 6; reproduced 2026-09-10)"}

CLASSES = ("exact", "alias", "synonym", "misspelling", "description", "acronym",
           "near_duplicate", "multi", "decoy")


def _ascii(s) -> str:
    """The owner's console is cp1252: stdout stays ASCII-only (UTF-8 files are fine)."""
    return str(s).encode("ascii", "replace").decode()


def _pct(a: int, b: int) -> float:
    return (100.0 * a / b) if b else 0.0


def _pctile(xs: list, q: float) -> float:
    """The p-th percentile, nearest-rank, on a sorted copy. `statistics.quantiles` needs n >= 2 and
    interpolates; nearest-rank is what every other latency bank in this estate reports."""
    if not xs:
        return 0.0
    s = sorted(float(x) for x in xs)
    i = max(0, min(len(s) - 1, int(round(q * len(s) + 0.5)) - 1))
    return s[i]


# ── the deck ─────────────────────────────────────────────────────────────────────────────────────
def load_deck(path: Path) -> dict:
    """Both deck shapes parse the same way: a `rows` list of {id, klass, phrase, expect}. The
    CALIBRATION deck writes its header as YAML comments and its rows flow-style; the HELD-OUT deck
    writes a real header and block-style rows. Neither is normalised here -- what is read is what the
    deck says."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = list(doc.get("rows") or [])
    if not rows:
        raise SystemExit(f"REFUSED: {path} carries no rows -- an empty deck certifies nothing.")
    bad = [r.get("id") for r in rows if not str(r.get("phrase") or "").strip()]
    if bad:
        raise SystemExit(f"REFUSED: rows with no phrase: {bad}")
    for r in rows:
        r["klass"] = str(r.get("klass") or r.get("class") or "").strip()
        r["expect"] = list(r.get("expect") or [])
    unknown = sorted({r["klass"] for r in rows} - set(CLASSES))
    if unknown:
        raise SystemExit(f"REFUSED: unknown class(es) {unknown} -- the bars are stated per class and a "
                         f"class with no bar would be scored silently under someone else's.")
    return {"path": path, "doc": doc, "rows": rows,
            "max_contracts": int(doc.get("max_contracts") or DEFAULT_MAX_CONTRACTS),
            "today": str(doc.get("today") or DEFAULT_TODAY)}


def deck_label(path: Path) -> str:
    """The deck's NAME, never its contents. A held-out deck is identified by its filename and its row
    count and by nothing that could carry a phrase into an artifact."""
    return path.name


# ── the graph and the groups (shared by both layers) ─────────────────────────────────────────────
def load_graph():
    from leviathan.graphrag import graph as G
    g = G.CausalGraph.load()
    if len(getattr(g, "contracts", {}) or {}) < 24:
        raise SystemExit(f"REFUSED: the graph carries {len(g.contracts)} contracts -- a toy enum changes "
                         f"what the planner sees and the deck would certify nothing.")
    return g


def group_index(graph) -> tuple:
    """`(of_id, members_of_group)` -- the D4 subject groups, read from the ONE producer."""
    from leviathan.graphrag.state import subject as SU
    of_id = SU.groups(graph)
    inv: dict = collections.defaultdict(set)
    for i, k in of_id.items():
        inv[k].add(i)
    return of_id, inv


def expand(ids, of_id: dict, inv: dict) -> set:
    """Every id of every group the given ids belong to. A group-less id expands to itself."""
    out: set = set()
    for i in ids:
        k = of_id.get(i)
        out |= (inv.get(k) or {i}) if k else {i}
    return out


def group_keys(ids, of_id: dict) -> set:
    """The GROUP KEYS the ids belong to -- what `near_duplicate` and `multi` are scored over."""
    return {of_id.get(i) or f"id:{i}" for i in ids}


# ── LAYER 1 -- free, deterministic ───────────────────────────────────────────────────────────────
def layer1_rows(rows, *, graph, vocab) -> list:
    """One scoring pass per row. `floor=-1.0, top_k=40` records the FULL ranking so a miss's rank is
    recoverable offline; the FROZEN floors are applied at scoring time, never at collection time."""
    from leviathan.graphrag.state import subject as SU
    out = []
    t0 = time.perf_counter()
    for n, r in enumerate(rows):
        q = r["phrase"]
        ex = SU.exact_ids(q, graph)
        al = tuple(x for x in SU.alias_ids(q, graph) if x not in set(ex))
        cands, status = SU.semantic_candidates(q, graph, vocab=vocab, floor=-1.0, top_k=40)
        out.append({"id": r["id"], "klass": r["klass"], "expect": list(r["expect"]),
                    "exact": list(ex), "alias": list(al), "vocab_status": status,
                    "cands": [[c[0], round(float(c[1]), 6), c[2]] for c in cands]})
        if (n + 1) % 25 == 0:
            print(f"    layer 1: {n + 1}/{len(rows)} ({time.perf_counter() - t0:.1f}s)", flush=True)
    return out


def decline_words() -> frozenset:
    """The `vocab_status` words that mean THE SEMANTIC TIER DID NOT RUN ON THAT ROW.

    DERIVED FROM THE SHIPPED CLOSED SET, never typed out: everything in `HINT_STATUS_WORDS` that is
    not `ok` and not the DELIBERATE skip is a decline. A fifth word invented in `state/subject.py`
    therefore lands here as a decline by default -- fail-closed -- rather than being scored silently
    as if the tier had run."""
    from leviathan.graphrag.state import subject as SU
    return frozenset(w for w in SU.HINT_STATUS_WORDS if w not in ("ok", SU.STATUS_SKIPPED))


def instrument_census(scored: list) -> dict:
    """THE INSTRUMENT'S OWN LIVENESS, read off the PER-ROW status the tiers actually returned.

    WHY THIS EXISTS, and it is not hypothetical -- it was reproduced in this checkout minutes before
    the good run. `evidence.embed` raised inside its `sentence_transformers` import chain;
    `semantic_candidates` caught it (the embedder is allowed to be gone: T0/T1 are the fail-open
    floor) and returned `unreadable` with ZERO candidates on EVERY phrase -- while `load_vocab` in the
    same process returned `ok`, because that word grades THE FILE and the embedder is a different
    failure. The run scored, verdicted and banked itself with `artifact: ok` in its own header, every
    class at its lexical floor. At layer 2 the same state hands the planner `hints_line()` of an empty
    `SubjectHints`, which is the EMPTY STRING, and 312 or 330 calls are BILLED on a blank hint line.

    The held-out deck is a one-shot, spent-on-use asset and layer 2 is its only billed measurement, so
    a transient embed failure during that run would burn the money AND the set and leave behind an
    artifact that looks like a measurement. `run_latency` already embeds a sentinel before it times
    anything; this is the same belt on the deck path, and it is the reason the fence reads the ROWS
    and not the artifact."""
    c = collections.Counter(str(r.get("vocab_status") or "") for r in scored)
    dw = decline_words()
    declined = {w: n for w, n in sorted(c.items()) if w in dw}
    # THE COUNT KEY IS `rows_scanned` AND NOT `rows`: the in-tree bank's phrase-free pin
    # (`test_pb11`) bans the KEY `rows` structurally, because that is what a bar's ROW-ID LIST is
    # called. A count is not a map back into a held-out deck -- but the ban is a key ban on purpose,
    # so the census renames rather than the pin weakening.
    return {"rows_scanned": len(scored), "census": dict(sorted(c.items())),
            "decline_words": sorted(dw), "declined": declined,
            "declined_rows": sum(declined.values()),
            "live": not declined, "certifying": not declined}


def score_layer1(scored: list, *, of_id: dict, inv: dict) -> dict:
    from leviathan.graphrag.state import subject as SU
    fl, am, k = SU.CAND_FLOOR, SU.AMBIG_FLOOR, SU.TOP_K

    def top(r, floor=fl):
        return [c for c in r["cands"] if c[1] >= floor][:k]

    def lex(r):
        return set(r["exact"]) | set(r["alias"])

    per: dict = {}
    agg = collections.Counter()
    for cl in CLASSES:
        rs = [r for r in scored if r["klass"] == cl]
        if not rs:
            continue
        if cl == "decoy":
            carry = [r["id"] for r in rs if top(r, am)]
            per[cl] = {"n": len(rs), "with_candidate": sum(1 for r in rs if top(r)),
                       "carried_at_ambig_floor": len(carry), "carried_ids": carry,
                       "bar": "carry == 0 (FATAL)",
                       "verdict": "PASS" if not carry else "FATAL"}
            continue
        a = h = at = 0
        for r in rs:
            want = expand(r["expect"], of_id, inv)
            t = top(r)
            a += bool(want & {c[0] for c in t})
            h += bool(t and t[0][0] in want)
            at += bool(want & (lex(r) | {c[0] for c in t}))
        bar = L1_BARS.get(cl)
        rate = at / len(rs)
        per[cl] = {"n": len(rs), "any_t2": a, "hit_at_1": h, "all_tiers": at,
                   "all_tiers_pct": round(_pct(at, len(rs)), 1),
                   "bar": (None if bar is None else f">= {bar:.0%}"),
                   "verdict": ("-" if bar is None else
                               ("PASS" if rate >= bar - 1e-9 else "MISS"))}
        agg["n"] += len(rs); agg["a"] += a; agg["h"] += h; agg["at"] += at
    return {"floors": {"CAND_FLOOR": fl, "AMBIG_FLOOR": am, "TOP_K": k},
            "per_class": per,
            "all_non_decoy": {"n": agg["n"], "any_t2": agg["a"], "hit_at_1": agg["h"],
                              "all_tiers": agg["at"],
                              "any_t2_pct": round(_pct(agg["a"], agg["n"]), 1),
                              "hit_at_1_pct": round(_pct(agg["h"], agg["n"]), 1),
                              "all_tiers_pct": round(_pct(agg["at"], agg["n"]), 1)},
            "lexical_baseline": dict(LEXICAL_BASELINE)}


# ── LAYER 2 -- the planner, billed ───────────────────────────────────────────────────────────────
def _usage_call(inner, rec: dict):
    """The `xc_fence.make_call` wrapper, plus the USAGE the dollar report is built from. `_call_opus`
    pop-tags `_usage` onto the returned dict (D-AM-4) and `_validate` ignores unknown keys, so the
    figures are read here rather than estimated from a per-call anchor."""
    def call(system, user, *, model, tool, **kw):
        rec["temperature"] = kw.get("temperature", "ABSENT")
        try:
            out = inner(system, user, model=model, tool=tool, **kw)
        except Exception as e:  # noqa: BLE001 -- recorded then re-raised (plan_turn maps it to fallback)
            rec["error"] = f"{type(e).__name__}: {e}"
            raise
        if isinstance(out, dict) and isinstance(out.get("_usage"), dict):
            rec["usage"] = dict(out["_usage"])
        return out
    return call


def usd(u: dict) -> float:
    """The BILLED dollars for one call, from the usage fields and the estate's own price table."""
    if not u:
        return 0.0
    from leviathan.graphrag import extract as ex
    return ex.Usage(input_tokens=int(u.get("in") or 0), output_tokens=int(u.get("out") or 0),
                    cache_creation=int(u.get("cache_write") or 0),
                    cache_read=int(u.get("cache_read") or 0)).cost_for(str(u.get("model") or SEAT))


def layer2_draw(row, *, graph, subject_ids, hints_line, inner_call, max_contracts, today) -> dict:
    """ONE `plan_turn` draw with the resolver's kwargs threaded -- the wiring `orchestrator.py` does
    under the flag, reproduced here argument for argument. A raise, a planner fallback or a degraded
    model marks the draw UNSCORED: an unscored row is never a passed row."""
    from leviathan.graphrag import dispatch as dp
    rec: dict = {}
    plan = dp.plan_turn(row["phrase"], graph=graph, today=today,
                        call=_usage_call(inner_call, rec), model=SEAT,
                        max_contracts=max_contracts,
                        subject_ids=subject_ids, subject_hints=hints_line)
    out = {"usage": rec.get("usage"), "temperature": rec.get("temperature"),
           "usd": round(usd(rec.get("usage") or {}), 6)}
    if rec.get("error"):
        return out | {"errored": rec["error"]}
    if plan.fallback:
        return out | {"errored": "planner_fallback (no raise)"}
    if plan.degraded:
        return out | {"errored": "degraded_model (Sonnet->Haiku)"}
    return out | {"subject": list(plan.subject), "subject_hints_n": int(plan.subject_hints_n),
                  "contracts": list(plan.contracts)}


def run_layer2(rows, *, graph, l1_by_id, draws, max_contracts, today, inner_call,
               meta: dict | None = None, cap_usd: float = HARD_CAP_USD) -> list:
    """THE BILLED PASS, with a RUNNING-TOTAL BREAKER as well as the pre-flight estimate.

    `main` already refuses when `calls x PER_CALL_USD` exceeds the cap -- the estate's "ceiling x
    requests vs balance BEFORE submit" doctrine, and the right first fence. But the anchor is $0.01 a
    call and nothing re-checked it once the run started, so a seat that billed far above the anchor
    would have run to the end of the deck and reported the overspend afterwards. The breaker reads the
    SAME usage fields the dollar report is built from, is checked between rows, and marks the run
    ABORTED so its bars can never be read as a completed measurement."""
    from leviathan.graphrag.state import subject as SU
    subject_ids = SU.live_ids(graph)
    meta = meta if meta is not None else {}
    meta.setdefault("spent", 0.0)
    meta.setdefault("aborted", False)
    out = []
    for row in rows:
        # THE HINT LINE IS REBUILT FROM LAYER 1's OWN SCORES, so the two layers cannot disagree about
        # what the planner was shown: the candidates are the frozen-floor top-5 of the same ranking
        # layer 1 recorded, and the exact/alias tiers are the same tuples.
        r1 = l1_by_id.get(row["id"]) or {}
        cands = tuple((c[0], float(c[1]), c[2]) for c in (r1.get("cands") or [])
                      if c[1] >= SU.CAND_FLOOR)[:SU.TOP_K]
        hints = SU.SubjectHints(exact=tuple(r1.get("exact") or ()), alias=tuple(r1.get("alias") or ()),
                                candidates=cands, vocab_status=str(r1.get("vocab_status") or "ok"))
        line = SU.hints_line(hints)
        reps = [layer2_draw(row, graph=graph, subject_ids=subject_ids, hints_line=line,
                            inner_call=inner_call, max_contracts=max_contracts, today=today)
                for _ in range(draws)]
        out.append({"id": row["id"], "klass": row["klass"], "expect": list(row["expect"]),
                    "hints_n": len(hints.ids()), "draws": reps})
        picks = ["/".join(d.get("subject") or []) or "-" for d in reps]
        meta["spent"] = round(float(meta["spent"])
                              + sum(float(d.get("usd") or 0.0) for d in reps), 6)
        print(f"    {_ascii(row['id']):<10} {row['klass']:<14} picks={_ascii(','.join(picks))}"
              f"  ${meta['spent']:.4f}", flush=True)
        if meta["spent"] > cap_usd:
            meta["aborted"] = True
            print(f"    ABORTED: the running total ${meta['spent']:.4f} passed the "
                  f"${cap_usd:.2f} hard cap after {len(out)} of {len(rows)} rows. The remaining rows "
                  f"are UNSCORED and this run's bars are not a completed measurement.", flush=True)
            break
    return out


def concept_count(row: dict) -> int:
    """HOW MANY SEPARATE CAUSES THE ROW NAMES -- 1 for `near_duplicate` (the class IS one subject under
    several spellings), :data:`MULTI_MIN_CONCEPTS` for `multi`, or the length of a deck-declared
    `concepts:` list where a deck carries one. Every other class is scored on ids and never asks."""
    dec = row.get("concepts")
    if dec:
        return len(dec)
    return 1 if row.get("klass") == "near_duplicate" else MULTI_MIN_CONCEPTS


def _l2_hit(cl: str, got: list, *, want_ids: set, want_grp: set, n_concepts: int,
            of_id: dict, rule: str) -> bool:
    """ONE DRAW, under ONE of the two readings of a row's `expect` list. Both are computed on every
    run and both are reported: `shipped_v1` is what phase B measured, `alternatives` is the corrected
    reading and the one the verdict is taken on."""
    if rule == "shipped_v1":
        if cl == "multi":
            return want_grp <= group_keys(got, of_id)
        if cl == "near_duplicate":
            return bool(got) and group_keys(got, of_id) == want_grp
        return bool(set(got) & want_ids)
    if cl in ("multi", "near_duplicate"):
        return len(group_keys(got, of_id) & want_grp) == n_concepts
    return bool(set(got) & want_ids)


def score_layer2(rows: list, *, of_id: dict, inv: dict) -> dict:
    """A row PASSES at >= 2 of 3 SCORED draws (D9). Three different questions are asked of three
    different classes and they are not interchangeable:
      the id classes   -- the pick lands inside the expected id's GROUP (a near-duplicate id is the
                          same subject; D4 is the reason the group and not the id is the unit);
      near_duplicate   -- the pick's group equals ANY expected id's group, and only one of them;
      multi            -- every expected CONCEPT covered by some pick, and no cause named twice;
      decoy            -- ANY non-empty pick on ANY draw is a FIRE, and the bar is zero. FATAL.

    A ROW'S `expect` LIST IS A LIST OF ALTERNATIVES, AND THE FIRST CUT READ IT AS A CONJUNCTION. That
    is the correction this function carries, and it is a SCORER defect and never a resolver one --
    phase B's own draws prove it. The deck lists, for each cause the ask names, the ids that would all
    be RIGHT answers for it; the group index (`state.subject.groups`) merges most of those into one
    group but not all, because a group is a curated slice and two curated slices can hold two spellings
    of one cause. So:

      `near_duplicate` was scored `group_keys(pick) == group_keys(expect)`. On `nd03` the four
      positioning spellings sit in `slice:cftc_positioning` while `managed_money_positioning` sits in
      its own, and on `nd10` `India_export_ban` sits apart from the other three -- so the expected side
      was TWO groups and equality asked the planner to name a single subject with two group keys at
      once, which no pick can do. MEASURED: 4 of 10 under the old reading, 10 of 10 under this one, and
      the six that moved include three rows the planner answered with the single right id on 3 of 3
      draws. It was also failing rows for a SECOND pick outside the expected family (`nd01` adding
      `acreage_competition` to `fertilizer_costs` on a phrase that says 'next year acreage'), which is
      the MULTI class's question asked of a row that is not in it.

      `multi` was scored `group_keys(expect) <= group_keys(pick)` -- EVERY listed group. On `mu02`
      (`Argentina_export_tax` and `export_tax`, two spellings of one export-tax cause in two slices),
      `mu05` and `mu06` that demanded the planner name two spellings of ONE cause as two subjects,
      which the frozen block forbids in as many words ("Two names for ONE cause are not two subjects").
      MEASURED: 5 of 8 under the old reading, 8 of 8 under this one.

    THE CORRECTED READING IS NOT THE LOOSE ONE, and the equality is deliberate: the picks must reach
    EXACTLY `concept_count(row)` of the expected groups. One expected group for a `near_duplicate`
    means a planner that hedges across two alternative families still fails; exactly two for a `multi`
    means a planner that names one cause twice (three expected groups reached for two causes) fails
    too. What it stops charging for is a pick outside the expected families entirely -- which the
    per-row `foreign_picks` count records rather than scores, because on these classes it is a
    different question and one this deck does not bar."""
    per: dict = {}
    agg = collections.Counter()
    for cl in CLASSES:
        rs = [r for r in rows if r["klass"] == cl]
        if not rs:
            continue
        if cl == "decoy":
            fired = [r["id"] for r in rs
                     if any((d.get("subject") or []) for d in r["draws"] if not d.get("errored"))]
            per[cl] = {"n": len(rs), "fired": len(fired), "fired_ids": fired,
                       "bar": "0 picks on ANY draw (FATAL)",
                       "verdict": "PASS" if not fired else "FATAL"}
            continue
        passed, unscored, passed_v1, detail = [], [], [], []
        for r in rs:
            ok = [d for d in r["draws"] if not d.get("errored")]
            if not ok:
                unscored.append(r["id"])
                continue
            want_ids = expand(r["expect"], of_id, inv)
            want_grp = group_keys(r["expect"], of_id)
            n_con = concept_count(r)
            hits = {"alternatives": 0, "shipped_v1": 0}
            reached, foreign = set(), 0
            for d in ok:
                got = list(d.get("subject") or [])
                gk = group_keys(got, of_id)
                reached |= (gk & want_grp)
                foreign += len(gk - want_grp)
                for rule in hits:
                    hits[rule] += int(_l2_hit(cl, got, want_ids=want_ids, want_grp=want_grp,
                                              n_concepts=n_con, of_id=of_id, rule=rule))
            if hits["alternatives"] * 3 >= 2 * len(ok):
                passed.append(r["id"])
            if hits["shipped_v1"] * 3 >= 2 * len(ok):
                passed_v1.append(r["id"])
            if cl in ("multi", "near_duplicate"):
                detail.append({"id": r["id"], "concepts": n_con,
                               "expected_groups": len(want_grp), "groups_reached": len(reached),
                               "foreign_picks": foreign})
        n = len(rs) - len(unscored)
        bar = L2_BARS.get(cl)
        rate = (len(passed) / n) if n else 0.0
        per[cl] = {"n": len(rs), "scored": n, "passed": len(passed),
                   "passed_pct": round(_pct(len(passed), n), 1), "unscored": unscored,
                   # BOTH READINGS ON EVERY RUN. The verdict is taken on `passed` (the corrected
                   # ALTERNATIVES reading); `passed_shipped_v1` is what phase B's scorer would have
                   # said on the same draws, so a reader comparing this run against the banked one is
                   # never comparing two rules without being told.
                   "passed_shipped_v1": len(passed_v1),
                   "passed_shipped_v1_pct": round(_pct(len(passed_v1), n), 1),
                   "failed_ids": [r["id"] for r in rs
                                  if r["id"] not in passed and r["id"] not in unscored],
                   "bar": (None if bar is None else f">= {bar:.0%}"),
                   "verdict": ("-" if bar is None else
                               ("PASS" if (n and rate >= bar - 1e-9) else "MISS"))}
        if detail:
            per[cl]["group_detail"] = detail
        agg["n"] += n; agg["p"] += len(passed); agg["p1"] += len(passed_v1)
    calls = [d for r in rows for d in r["draws"]]
    # ── THE SEAT PIN, READ BACK RATHER THAN PRINTED. The report writes "temperature 0" from the module
    #    constant while `_usage_call` records what was ACTUALLY passed per draw, and nothing compared
    #    them: an assertion about the seat that never reads the seat is the exact class the
    #    TEMP_DEPRECATED_SEATS RCA exists to catch (a silent 14-of-14 fallback whose report still
    #    quoted the pin). The MODEL is read back the same way, from the usage the bill is computed on.
    _temps = sorted({repr(d.get("temperature")) for d in calls
                     if d.get("temperature") is not None}) or ["<none>"]
    _models = sorted({str((d.get("usage") or {}).get("model") or "") for d in calls
                      if d.get("usage")}) or ["<none>"]
    return {"per_class": per,
            "scoring_rule": {"reading": "alternatives", "also_reported": "shipped_v1",
                             "multi_min_concepts": MULTI_MIN_CONCEPTS,
                             "note": "a row's expect list is a list of ALTERNATIVES; the picks must "
                                     "reach EXACTLY concept_count(row) of the expected groups "
                                     "(near_duplicate 1, multi 2 unless the deck declares concepts)"},
            "all_non_decoy": {"scored": agg["n"], "passed": agg["p"],
                              "passed_pct": round(_pct(agg["p"], agg["n"]), 1),
                              "passed_shipped_v1": agg["p1"],
                              "passed_shipped_v1_pct": round(_pct(agg["p1"], agg["n"]), 1)},
            "calls": len(calls), "errored_calls": sum(1 for d in calls if d.get("errored")),
            "usd_measured": round(sum(float(d.get("usd") or 0.0) for d in calls), 4),
            "seat_pin": {"temperature_declared": TEMPERATURE, "temperature_observed": _temps,
                         "seat_declared": SEAT, "model_observed": _models,
                         "verdict": ("PASS" if (_temps == [repr(TEMPERATURE)]
                                                and all(SEAT in m for m in _models))
                                     else "STOP")},
            "lexical_baseline": dict(LEXICAL_BASELINE)}


# ── D10 -- the latency harness, free ─────────────────────────────────────────────────────────────
def run_latency(rows, *, graph, n: int) -> dict:
    """FLAG OFF vs FLAG ON over the deck's own phrases, at the seat the resolver actually occupies.

    THE TWO ARMS, and the arithmetic is the whole point:
      OFF  the walk embeds the verbatim query itself, COLD -- the turn pays that either way;
      ON   `resolve()` (which fills the same `evidence._Q_CACHE` key, so it pays the cold embed) plus
           `hints_line()` plus the walk's now-WARM embed of the same key.
    ADDED = ON - OFF, which is what D10's "<= 150 ms added per turn" is stated over. The resolver's own
    wall is banked beside it as `ms_board_subject_ms` -- that is the counter production sees, and it is
    dominated by an embed the walking lane was going to pay one call later.

    THE MEMO IS CLEARED BETWEEN EVERY DRAW. Phase A's first bank was measured warm and read 15 ms at
    p90; the same code measured cold reads 387. Clearing is what makes the two arms comparable.
    """
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag.state import subject as SU
    phrases = [r["phrase"] for r in rows][:max(1, int(n))]
    # THE MODEL LOAD AND THE ARTIFACT LOAD ARE PAID BEFORE THE FIRST DRAW, on a sentinel phrase that is
    # in no deck. Both are ONCE PER PROCESS (the bge-m3 weights; the 25 MB np.load and its blurb index)
    # and both are declared OUTSIDE every figure here -- leaving them inside draw 1 would put a
    # thirty-second one-time cost into the OFF arm and make the mean of `added` negative, which is a
    # number no reader can use even when the percentiles are unharmed.
    ev._Q_CACHE.clear()
    _sentinel = "a warm-up phrase that belongs to no deck row"
    try:
        ev.embed([_sentinel])
    except Exception as e:  # noqa: BLE001 -- a clean refusal, never a traceback with timings behind it
        raise SystemExit(f"REFUSED: the embedder is unavailable ({type(e).__name__}: {e}) -- the OFF "
                         f"arm is a cold embed and the ON arm is that same embed plus resolve(), so "
                         f"a dead embedder measures nothing. Nothing was banked.")
    # AND THE SENTINEL'S OWN STATUS IS READ, the deck path's instrument fence in one row: `resolve()`
    # swallows an embed failure by contract (T0/T1 are the fail-open floor), so a tier that declined
    # here would otherwise be timed as if it had run and banked as a 0 ms addition.
    _h = SU.resolve(_sentinel, graph=graph)
    if _h.vocab_status in decline_words():
        raise SystemExit(f"REFUSED: the sentinel resolve declined with vocab_status "
                         f"{_h.vocab_status!r} -- the semantic tier is not running, so the ON arm is "
                         f"the OFF arm and the added wall would bank as ~0. Nothing was banked.")
    SU.hints_line(_h)
    off, on, added, resolver_ms, hints_ms = [], [], [], [], []
    for i, q in enumerate(phrases):
        ev._Q_CACHE.clear()                                # the OFF arm: the walk pays the cold embed
        t = time.perf_counter()
        ev.embed([q])
        d_off = (time.perf_counter() - t) * 1000.0
        ev._Q_CACHE.clear()                                # the ON arm: the resolver pays it first
        t = time.perf_counter()
        h = SU.resolve(q, graph=graph)
        d_res = (time.perf_counter() - t) * 1000.0
        t = time.perf_counter()
        SU.hints_line(h)
        d_hint = (time.perf_counter() - t) * 1000.0
        t = time.perf_counter()
        ev.embed([q])                                      # the walk's own embed, now a memo hit
        d_warm = (time.perf_counter() - t) * 1000.0
        d_on = d_res + d_hint + d_warm
        off.append(d_off); on.append(d_on); added.append(d_on - d_off)
        resolver_ms.append(float(h.ms)); hints_ms.append(d_hint)
        if (i + 1) % 10 == 0:
            print(f"    latency: {i + 1}/{len(phrases)}  added p90 so far "
                  f"{_pctile(added, 0.90):.1f} ms", flush=True)

    def stat(xs):
        return {"p50": round(_pctile(xs, 0.50), 2), "p90": round(_pctile(xs, 0.90), 2),
                "mean": round(statistics.fmean(xs), 2) if xs else 0.0, "n": len(xs)}

    # THE BUDGET IS READ FROM THE GRADER, NOT TYPED HERE. `config_check.SUBJECT_LATENCY_BUDGET_MS` is
    # the one place D10's 150 ms lives; clause (13) grades the banked p90 against it AND reds when the
    # bank's own `budget_ms` disagrees with it. Writing the figure from that constant is what makes the
    # disagreement check a tripwire for drift rather than a second chance to invent a threshold.
    from leviathan.graphrag.config_check import SUBJECT_LATENCY_BUDGET_MS as _BUDGET
    return {"budget_ms": float(_BUDGET), "n": len(phrases),
            "flag_off_turn_embed_ms": stat(off), "flag_on_total_ms": stat(on),
            "added_wall_per_turn_ms": stat(added),
            "ms_board_subject_ms": stat(resolver_ms), "hints_line_ms": stat(hints_ms),
            "bar": {"metric": "added_wall_per_turn_ms.p90", "budget_ms": float(_BUDGET),
                    "measured_ms": round(_pctile(added, 0.90), 2),
                    "verdict": "PASS" if _pctile(added, 0.90) <= float(_BUDGET) else "STOP"},
            "note": ("OFF = the walk's own cold embed of the verbatim query, which the turn pays "
                     "either way. ON = resolve() (cold, it fills the same _Q_CACHE key) + hints_line() "
                     "+ the walk's now-warm embed. ADDED is the difference and is what D10 budgets. "
                     "ms_board_subject_ms is the resolver's OWN wall -- the production counter -- and "
                     "is dominated by that shared embed. THE LANE SPLIT IS STATED AND NOT HIDDEN: "
                     "these figures are a WALKING lane's. A lane that never walks (numbers_only, "
                     "trivial) pays ms_board_subject_ms in full and nobody pays it back, which is "
                     "what resolve(allow_embed=False) is for -- and which the orchestrator cannot "
                     "decide at this call site, because the lane is plan_turn's own output (D10 "
                     "addendum A1). The model load and the artifact load are once per process and "
                     "sit outside every figure here: both are paid on a sentinel phrase first."),
            "lane_split": {"walking_lane_added_p90": round(_pctile(added, 0.90), 2),
                           "never_walking_lane_added_p90": round(_pctile(resolver_ms, 0.90), 2)}}


# ── the report ───────────────────────────────────────────────────────────────────────────────────
def markdown(doc: dict) -> str:
    L = []
    L.append(f"# SUBJECT RESOLVER DECK RUN -- {doc['deck']}")
    L.append("")
    L.append(f"- generated: {doc['generated_utc']}")
    L.append(f"- rows: {doc['rows_total']}  graph: {doc['graph_hash']}  "
             f"artifact: {doc['vocab_status']}")
    # THE INSTRUMENT, BESIDE THE ARTIFACT AND NOT INSTEAD OF IT. `artifact: ok` grades the FILE; this
    # line grades whether the semantic tier actually RAN, row by row, which is the half a dead embedder
    # takes away while the header above still reads 'ok'.
    _inst = doc.get("instrument")
    if _inst:
        L.append(f"- instrument: {'LIVE' if _inst['live'] else 'DEAD'} -- per-row vocab_status "
                 f"{_inst['census']} over {_inst['rows_scanned']} rows"
                 + ("" if _inst["live"] else "  **NON-CERTIFYING**"))
    L.append(f"- layers run: {', '.join(doc['layers_run']) or 'none'}")
    L.append(f"- verdict vocabulary: {{LAND-DARK, STOP}} -- this deck cannot flip anything")
    L.append("")
    l1 = doc.get("layer1")
    if l1:
        L.append("## LAYER 1 -- the deterministic tiers (free)")
        L.append("")
        L.append(f"floors FROZEN: CAND {l1['floors']['CAND_FLOOR']}  "
                 f"AMBIG {l1['floors']['AMBIG_FLOOR']}  TOP_K {l1['floors']['TOP_K']}")
        L.append("")
        L.append("| class | n | anyT2 | hit@1 | all-tiers | bar | verdict |")
        L.append("|---|---|---|---|---|---|---|")
        for cl, v in l1["per_class"].items():
            if cl == "decoy":
                L.append(f"| decoy | {v['n']} | cand={v['with_candidate']} | "
                         f"carry={v['carried_at_ambig_floor']} | - | {v['bar']} | {v['verdict']} |")
            else:
                L.append(f"| {cl} | {v['n']} | {v['any_t2']}/{v['n']} | {v['hit_at_1']}/{v['n']} | "
                         f"{v['all_tiers']}/{v['n']} ({v['all_tiers_pct']}%) | {v['bar'] or '-'} | "
                         f"{v['verdict']} |")
        a = l1["all_non_decoy"]
        L.append(f"| ALL non-decoy | {a['n']} | {a['any_t2_pct']}% | {a['hit_at_1_pct']}% | "
                 f"{a['all_tiers_pct']}% | - | - |")
        L.append("")
        L.append(f"lexical baseline, like for like: {LEXICAL_BASELINE['any_hit_pct']}% any-hit / "
                 f"{LEXICAL_BASELINE['hit_at_1_pct']}% hit@1 -- {LEXICAL_BASELINE['note']}")
        L.append("")
        # WHICH COLUMN THE BARS ARE GRADED ON, said once and in the report rather than left to the
        # reader of `score_layer1`. D9's sentence for synonym/misspelling/description/acronym says "in
        # the top-5 candidates"; the graded column is the union of ALL THREE TIERS (T0 exact, T1 alias,
        # and that top-5), which is more permissive than the literal wording. Both columns are printed
        # above precisely so the difference is visible: on the calibration deck they coincide on every
        # graded class; on the held-out deck they differ on synonym and description, and NO bar's
        # verdict changes under either reading (checked on both decks).
        L.append("BARS ARE GRADED ON THE `all-tiers` COLUMN -- T0 exact UNION T1 alias UNION the "
                 "frozen-floor top-5 -- which is wider than D9's literal 'in the top-5 candidates'. "
                 "The `anyT2` column beside it is the strict top-5 reading; no bar's verdict differs "
                 "between the two on either deck.")
        L.append("")
    l2 = doc.get("layer2")
    if l2:
        L.append("## LAYER 2 -- the planner (billed)")
        L.append("")
        L.append(f"seat {SEAT}  temperature {TEMPERATURE}  max_contracts {doc['max_contracts']}  "
                 f"draws {doc['draws']}  (a row passes at >= 2 of {doc['draws']})")
        L.append("")
        L.append("| class | n | scored | passed (alternatives) | passed (shipped v1) | bar | verdict |")
        L.append("|---|---|---|---|---|---|---|")
        for cl, v in l2["per_class"].items():
            if cl == "decoy":
                L.append(f"| decoy | {v['n']} | - | fired={v['fired']} | fired={v['fired']} | "
                         f"{v['bar']} | {v['verdict']} |")
            else:
                L.append(f"| {cl} | {v['n']} | {v['scored']} | {v['passed']} ({v['passed_pct']}%) | "
                         f"{v['passed_shipped_v1']} ({v['passed_shipped_v1_pct']}%) | "
                         f"{v['bar'] or '-'} | {v['verdict']} |")
        a = l2["all_non_decoy"]
        L.append(f"| ALL non-decoy | - | {a['scored']} | {a['passed']} ({a['passed_pct']}%) | "
                 f"{a['passed_shipped_v1']} ({a['passed_shipped_v1_pct']}%) | - | - |")
        L.append("")
        # BOTH READINGS, AND WHICH ONE THE VERDICT IS TAKEN ON. The two columns differ only on
        # `near_duplicate` and `multi`, whose `expect` lists are ALTERNATIVES rather than conjunctions;
        # every other class is scored identically under both, which is why the difference is a scorer
        # correction and not a re-grading of the wave.
        _sr = l2.get("scoring_rule") or {}
        L.append("THE VERDICT COLUMN IS `alternatives` -- a row's `expect` list names, for each cause "
                 "the ask carries, the ids that would each be a right answer for it, and the picks "
                 "must reach EXACTLY the row's concept count among the expected groups "
                 f"(near_duplicate 1, multi {_sr.get('multi_min_concepts', MULTI_MIN_CONCEPTS)} "
                 "unless the deck declares `concepts:`). `shipped v1` is the same draws under phase "
                 "B's scorer, which read the list as a CONJUNCTION and so asked one pick to carry two "
                 "group keys at once; the two columns coincide on every class but those two.")
        L.append("")
        L.append(f"calls {l2['calls']} (errored {l2['errored_calls']}), "
                 f"MEASURED ${l2['usd_measured']:.4f} from the usage fields")
        _sp = l2.get("seat_pin")
        if _sp:
            L.append("")
            L.append(f"SEAT PIN, read back from the draws (never only printed): temperature "
                     f"declared {_sp['temperature_declared']} / observed "
                     f"{', '.join(_sp['temperature_observed'])}; seat declared {_sp['seat_declared']} "
                     f"/ billed {', '.join(_sp['model_observed'])} -- {_sp['verdict']}")
        if l2.get("aborted_on_cost"):
            L.append("")
            L.append("**ABORTED ON COST**: the running total passed the hard cap mid-run, the "
                     "remaining rows are unscored, and these bars are not a completed measurement.")
        L.append("")
    lat = doc.get("latency")
    if lat:
        L.append("## D10 -- the latency bar (free)")
        L.append("")
        L.append("| population | p50 ms | p90 ms | n |")
        L.append("|---|---|---|---|")
        for k in ("flag_off_turn_embed_ms", "flag_on_total_ms", "added_wall_per_turn_ms",
                  "ms_board_subject_ms", "hints_line_ms"):
            v = lat[k]
            L.append(f"| {k} | {v['p50']} | {v['p90']} | {v['n']} |")
        L.append("")
        L.append(f"BAR {lat['bar']['metric']} <= {lat['bar']['budget_ms']:.0f} ms: measured "
                 f"{lat['bar']['measured_ms']} ms -- {lat['bar']['verdict']}")
        L.append("")
        L.append(lat["note"])
        L.append("")
    L.append("## BARS")
    L.append("")
    for b in doc["bars"]:
        L.append(f"- **{b['verdict']}** {b['bar']} -- {b['detail']}"
                 + (f" [rows: {', '.join(b['rows'])}]" if b.get("rows") else ""))
    L.append("")
    L.append(f"## VERDICT: {doc['verdict']}")
    if doc.get("failing_bars"):
        L.append("")
        L.append("failing bars: " + "; ".join(doc["failing_bars"]))
    return "\n".join(L) + "\n"


def collect_bars(doc: dict) -> list:
    """Every EVALUATED bar as {bar, verdict, detail, rows}. A layer that did not run yields no bar --
    a bar that was never measured is never reported as passed.

    `detail` IS COUNTS ONLY AND `rows` IS THE ROW IDS, and the split is the phrase-free rule applied to
    its nearest neighbour: a held-out row id beside its class and its verdict is a map back into a deck
    that must stay outside the tree. The scratchpad artifact and stdout carry `rows`; the in-tree bank
    drops it. Naming the failing rows on the console is what makes a MISS actionable, so the split is
    where the artifact is written and not where the measurement is made."""
    bars = []
    l1 = doc.get("layer1")
    if l1:
        for cl, v in l1["per_class"].items():
            if cl == "decoy":
                bars.append({"bar": "L1 DECOY CARRY (0 at AMBIG_FLOOR, FATAL)",
                             "verdict": "PASS" if v["verdict"] == "PASS" else "STOP",
                             "detail": f"{v['carried_at_ambig_floor']} of {v['n']} decoys carried "
                                       f"({v['with_candidate']} put a candidate above CAND_FLOOR in "
                                       f"front of the planner)",
                             "rows": list(v["carried_ids"])})
            elif v["bar"]:
                bars.append({"bar": f"L1 {cl.upper()} {v['bar']}",
                             "verdict": "PASS" if v["verdict"] == "PASS" else "MISS",
                             "detail": f"{v['all_tiers']}/{v['n']} = {v['all_tiers_pct']}% all-tiers",
                             "rows": []})
    l2 = doc.get("layer2")
    if l2:
        for cl, v in l2["per_class"].items():
            if cl == "decoy":
                bars.append({"bar": "L2 DECOY PICKS (0 on ANY draw, FATAL)",
                             "verdict": "PASS" if v["verdict"] == "PASS" else "STOP",
                             "detail": f"{v['fired']} of {v['n']} decoy rows had the planner pick a "
                                       f"subject on at least one draw",
                             "rows": list(v["fired_ids"])})
            elif v["bar"]:
                bars.append({"bar": f"L2 {cl.upper()} {v['bar']}",
                             "verdict": "PASS" if v["verdict"] == "PASS" else "MISS",
                             "detail": f"{v['passed']}/{v['scored']} = {v['passed_pct']}% at "
                                       f">= 2 of {doc['draws']} draws",
                             "rows": list(v["failed_ids"])})
        # THE SEAT PIN AS A BAR, because the report used to ASSERT it and never READ it. A seat that
        # moved would move the treatment with it and nothing measured here would be attributable.
        _sp = l2.get("seat_pin")
        if _sp:
            bars.append({"bar": "L2 SEAT PIN (temperature and model, read back from every draw)",
                         "verdict": _sp["verdict"],
                         "detail": f"temperature observed {', '.join(_sp['temperature_observed'])} "
                                   f"against a declared {_sp['temperature_declared']}; billed model "
                                   f"{', '.join(_sp['model_observed'])} against a declared "
                                   f"{_sp['seat_declared']}",
                         "rows": []})
        if l2.get("aborted_on_cost"):
            bars.append({"bar": "L2 COST BREAKER (the run completed inside the hard cap)",
                         "verdict": "STOP",
                         "detail": f"the running total ${l2.get('running_usd', 0.0):.4f} passed the "
                                   f"${HARD_CAP_USD:.2f} cap mid-run; the remaining rows are UNSCORED "
                                   f"and every rate above is over a truncated population",
                         "rows": []})
    lat = doc.get("latency")
    if lat:
        bars.append({"bar": f"D10 ADDED WALL p90 <= {lat['bar']['budget_ms']:.0f} ms",
                     "verdict": lat["bar"]["verdict"],
                     "detail": f"{lat['bar']['measured_ms']} ms added per turn at p90 "
                               f"(the resolver's own wall is "
                               f"{lat['ms_board_subject_ms']['p90']} ms at p90)",
                     "rows": []})
    return bars


def verdict_of(bars: list) -> tuple:
    """{LAND-DARK, STOP} and nothing else (D9). A FATAL bar STOPs; a rate bar that MISSes is reported
    by name and does not on its own STOP -- phase A's own held-out run missed two rate bars by a row
    each and landed dark under this same vocabulary. STOP is reserved for a bar whose failure means
    the wiring must not be armed at all."""
    stops = [b["bar"] for b in bars if b["verdict"] == "STOP"]
    misses = [b["bar"] for b in bars if b["verdict"] == "MISS"]
    return ("STOP" if stops else "LAND-DARK"), stops, misses


# ── the call plan ────────────────────────────────────────────────────────────────────────────────
def print_plan(deck: dict, *, layer: str, draws: int, latency: bool, latency_n: int) -> float:
    rows = deck["rows"]
    by_class = collections.Counter(r["klass"] for r in rows)
    calls = len(rows) * draws if layer in ("2", "both") else 0
    est = calls * PER_CALL_USD
    print("CALL PLAN")
    print(f"  deck        {deck_label(deck['path'])}  ({len(rows)} rows)")
    print(f"  classes     " + "  ".join(f"{k}={by_class[k]}" for k in CLASSES if by_class[k]))
    print(f"  seat        {SEAT}  temperature={TEMPERATURE}  "
          f"max_contracts={deck['max_contracts']}  today={deck['today']}")
    print(f"  layer 1     {'RUN ' if layer in ('1', 'both') else 'skip'}  "
          f"{len(rows) if layer in ('1', 'both') else 0} deterministic scorings, 0 API calls, $0.00")
    print(f"  layer 2     {'RUN ' if layer in ('2', 'both') else 'skip'}  "
          f"{calls} plan_turn calls ({len(rows)} rows x {draws} draws)")
    print(f"  latency     {'RUN ' if latency else 'skip'}  "
          f"{min(latency_n, len(rows)) if latency else 0} phrases x 3 embeds, 0 API calls, $0.00")
    print(f"  ESTIMATE    {calls} calls x ${PER_CALL_USD:.2f}/call (the planner's per-call anchor) "
          f"= ${est:.2f}")
    print(f"  EXPOSURE, said before and not after: the CEILING is the budget number. "
          f"{calls} calls at the anchor is ${est:.2f} against a ${HARD_CAP_USD:.2f} hard cap; the "
          f"BILLED figure is read back from the usage fields and reported as measured dollars.")
    return est


# ── main ─────────────────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Subject-resolver deck runner (D9 layers 1/2 + D10)")
    ap.add_argument("--deck", help="deck YAML (calibration or held-out)")
    ap.add_argument("--rescore", default="",
                    help="re-score a BANKED run's draws offline under the current scorer and exit. "
                         "Spends nothing, reads no deck and makes no call: the draws are the "
                         "measurement and the scorer is the thing that moved.")
    ap.add_argument("--layer", default="both", choices=("1", "2", "both", "none"),
                    help="1 = the free tiers, 2 = the billed planner, both (default), none")
    ap.add_argument("--draws", type=int, default=3, help="layer-2 draws per row (default 3)")
    ap.add_argument("--latency", action="store_true", help="run the D10 latency harness (free)")
    ap.add_argument("--latency-n", type=int, default=40, help="phrases for the latency harness")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the call plan and the dollar estimate; spend nothing")
    ap.add_argument("--out-dir", default=str(SCRATCH), help="scratchpad artifact directory")
    ap.add_argument("--bank-dir", default="", help="in-tree phrase-free summary dir (default by date)")
    ap.add_argument("--no-bank", action="store_true", help="skip the in-tree summary")
    args = ap.parse_args(argv)

    # ── THE OFFLINE RE-SCORE. A banked run carries every draw's picks, so a scorer correction is a
    #    RE-READ of one measurement and never a second run -- the same discipline the T2 gate's
    #    decision table is recomputed under. It loads the graph (the group index is the scorer's other
    #    input and it must be the LIVE one), and it makes no API call and reads no deck.
    if args.rescore:
        src = Path(args.rescore)
        if not src.is_file():
            print(f"REFUSED: banked run not found: {src}")
            return 2
        banked = json.loads(src.read_text(encoding="utf-8"))
        rows2 = list(banked.get("layer2_rows") or [])
        if not rows2:
            print(f"REFUSED: {src} carries no layer2_rows -- there are no draws to re-score.")
            return 2
        graph = load_graph()
        of_id, inv = group_index(graph)
        sc = score_layer2(rows2, of_id=of_id, inv=inv)
        doc = {k: banked.get(k) for k in ("generated_utc", "deck", "rows_total", "graph_hash",
                                          "vocab_status", "draws", "max_contracts")}
        doc["deck"] = f"{banked.get('deck')} (RE-SCORED from {src.name})"
        doc["layers_run"] = ["2"]
        doc["layer2"] = dict(sc, aborted_on_cost=bool((banked.get("layer2") or {})
                                                      .get("aborted_on_cost")))
        doc["bars"] = collect_bars(doc)
        doc["verdict"], _stops, _misses = verdict_of(doc["bars"])
        doc["failing_bars"] = _stops + _misses
        print(_ascii(markdown(doc)))
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dst = out_dir / f"{src.stem}_RESCORED_{stamp}.json"
        dst.write_text(json.dumps(dict(doc, layer2_rows=rows2), indent=2, ensure_ascii=False),
                       encoding="utf-8", newline="\n")
        print(f"artifact: {dst}")
        return 0

    if not args.deck:
        print("REFUSED: --deck is required (or --rescore a banked run).")
        return 2
    deck_path = Path(args.deck)
    if not deck_path.exists():
        print(f"REFUSED: deck not found: {deck_path}")
        return 2
    deck = load_deck(deck_path)
    if args.draws < 1:
        print("REFUSED: --draws must be >= 1")
        return 2
    if args.layer == "none" and not args.latency:
        print("REFUSED: nothing to run (--layer none and no --latency)")
        return 2

    est = print_plan(deck, layer=args.layer, draws=args.draws, latency=args.latency,
                     latency_n=args.latency_n)
    if args.dry_run:
        print("DRY RUN: no API call made, nothing spent.")
        return 0
    if est > HARD_CAP_USD:
        print(f"REFUSED: the estimate ${est:.2f} exceeds the ${HARD_CAP_USD:.2f} hard cap.")
        return 2
    if args.layer in ("2", "both"):
        if os.environ.get("GRAPHRAG_DISPATCH", "llm") == "rules":
            print("REFUSED: GRAPHRAG_DISPATCH=rules -- every row would fall back (vacuous run).")
            return 2
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("REFUSED: ANTHROPIC_API_KEY is not set in this environment.")
            return 2

    from leviathan.graphrag.state import subject as SU
    t0 = time.perf_counter()
    graph = load_graph()
    vocab, vstatus = SU.load_vocab(graph=graph)
    print(f"graph {SU.live_graph_hash(graph)}  contracts {len(graph.contracts)}  "
          f"driver ids {len(SU.live_ids(graph))}  artifact {vstatus}  "
          f"({time.perf_counter() - t0:.1f}s)")
    # THE ARTIFACT FENCE (the FILE). The INSTRUMENT fence -- whether the tier actually ran, which is a
    # different failure and the one that reproduced in this checkout -- is below, after layer 1.
    # `--latency` is fenced here too: a harness that times a declining tier times the free tiers.
    if (args.layer in ("1", "2", "both") or args.latency) and vstatus != "ok":
        print(f"REFUSED: the vocabulary artifact is '{vstatus}' -- the semantic tier would decline and "
              f"a run would measure the two free tiers while reporting three.")
        return 2
    of_id, inv = group_index(graph)

    doc: dict = {"generated_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                 "deck": deck_label(deck_path), "deck_path": str(deck_path),
                 "rows_total": len(deck["rows"]),
                 "class_counts": dict(collections.Counter(r["klass"] for r in deck["rows"])),
                 "graph_hash": SU.live_graph_hash(graph), "vocab_status": vstatus,
                 "seat": SEAT, "temperature": TEMPERATURE, "draws": args.draws,
                 "max_contracts": deck["max_contracts"], "layers_run": []}

    l1_scored: list = []
    rows2: list = []
    l2_meta: dict = {}
    if args.layer in ("1", "2", "both"):
        print("[layer 1] the deterministic tiers"
              if args.layer in ("1", "both")
              else "[layer 1] (required to build the hint lines layer 2 sends)")
        l1_scored = layer1_rows(deck["rows"], graph=graph, vocab=vocab)
        # ── THE INSTRUMENT FENCE. Read `instrument_census` for what this is protecting against; the
        #    short form is that `load_vocab` grades the FILE and the EMBEDDER is a different failure,
        #    so an `artifact: ok` header is NOT evidence the semantic tier ran. This refuses BEFORE
        #    layer 2 spends and BEFORE anything is banked -- a non-certifying run must never leave a
        #    summary in `data/subject_resolver/` that a later reader takes for a measurement.
        doc["instrument"] = instrument_census(l1_scored)
        _inst = doc["instrument"]
        print(f"instrument: {'LIVE' if _inst['live'] else 'DEAD'}  "
              f"per-row vocab_status {_inst['census']}")
        if not _inst["live"]:
            _calls = len(deck["rows"]) * args.draws if args.layer in ("2", "both") else 0
            print("")
            print(f"REFUSED: THE INSTRUMENT IS DEAD, NOT THE DECK. The semantic tier declined on "
                  f"{_inst['declined_rows']} of {_inst['rows_scanned']} rows ({_inst['declined']}) while the "
                  f"artifact loaded '{vstatus}' -- load_vocab grades the FILE and the embedder is a "
                  f"different failure.")
            print(f"         A run scored in this state measures two tiers while reporting three: "
                  f"every class lands at its lexical floor and the report's own header still reads "
                  f"'artifact: {vstatus}'.")
            if _calls:
                print(f"         Layer 2 would have BILLED {_calls} planner calls on a hint line that "
                      f"is the empty string, and on the held-out deck that spends a ONE-SHOT set.")
            print(f"         NOTHING WAS BANKED and no call was made. Diagnose the embedder "
                  f"(leviathan.graphrag.evidence.embed), then re-run.")
            _diag = Path(args.out_dir)
            _diag.mkdir(parents=True, exist_ok=True)
            _dp = _diag / (f"{deck_path.stem}_"
                           f"{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
                           f"_REFUSED_instrument_dead.json")
            _dp.write_text(json.dumps(dict(doc, certifying=False, layer1_rows=l1_scored),
                                      indent=2, ensure_ascii=False),
                           encoding="utf-8", newline="\n")
            print(f"diagnostic (NOT a measurement): {_dp}")
            return 2
        if args.layer in ("1", "both"):
            doc["layer1"] = score_layer1(l1_scored, of_id=of_id, inv=inv)
            doc["layers_run"].append("1")
    if args.layer in ("2", "both"):
        print("[layer 2] the planner")
        from leviathan.graphrag import answer as an
        rows2 = run_layer2(deck["rows"], graph=graph,
                           l1_by_id={r["id"]: r for r in l1_scored}, draws=args.draws,
                           max_contracts=deck["max_contracts"], today=deck["today"],
                           inner_call=an._call_opus, meta=l2_meta)
        doc["layer2"] = score_layer2(rows2, of_id=of_id, inv=inv)
        doc["layer2"]["aborted_on_cost"] = bool(l2_meta.get("aborted"))
        doc["layer2"]["running_usd"] = round(float(l2_meta.get("spent") or 0.0), 4)
        doc["layers_run"].append("2")
    if args.latency:
        print("[D10] the latency harness")
        doc["latency"] = run_latency(deck["rows"], graph=graph, n=args.latency_n)
        doc["layers_run"].append("latency")

    doc["bars"] = collect_bars(doc)
    doc["verdict"], stops, misses = verdict_of(doc["bars"])
    doc["failing_bars"] = stops + misses

    # ── the artifacts. The SCRATCHPAD copy carries per-row detail; the IN-TREE bank carries class
    #    counts and nothing else -- no phrase, no row id, no expected id, so a held-out deck's rows
    #    cannot reach the tree through this path.
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = deck_path.stem
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    full = dict(doc)
    if l1_scored:
        full["layer1_rows"] = l1_scored
    if doc.get("layer2"):
        full["layer2_rows"] = rows2
    # LF, EXPLICITLY, ON EVERY ARTIFACT THIS SCRIPT WRITES. `write_text` translates "\n" to the
    # platform's line ending, and the estate's tracked text is LF on every platform -- a
    # Windows-authored bank would otherwise land CRLF in a repository whose every other data artifact
    # is LF, and the diff would be the whole file.
    (out_dir / f"{tag}_{stamp}.json").write_text(json.dumps(full, indent=2, ensure_ascii=False),
                                                 encoding="utf-8", newline="\n")
    (out_dir / f"{tag}_{stamp}.md").write_text(markdown(doc), encoding="utf-8", newline="\n")
    print(f"artifact: {out_dir / (tag + '_' + stamp + '.json')}")

    if not args.no_bank:
        bank_dir = Path(args.bank_dir) if args.bank_dir else (
            BANK / _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d"))
        bank_dir.mkdir(parents=True, exist_ok=True)
        summary = {k: doc[k] for k in ("generated_utc", "deck", "rows_total", "class_counts",
                                       "graph_hash", "vocab_status", "seat", "temperature",
                                       "draws", "max_contracts", "layers_run", "verdict",
                                       "failing_bars")}
        # THE INSTRUMENT CENSUS RIDES THE BANK. It is a count of status WORDS over rows -- no phrase,
        # no row id -- and it is what tells a later reader that the semantic tier was alive when these
        # figures were taken. A bank without it is a bank whose floors cannot be distinguished from a
        # dead embedder's.
        if doc.get("instrument"):
            summary["instrument"] = doc["instrument"]
        # THE BARS LOSE THEIR ROW LISTS HERE. Counts and verdicts are the measurement; the row ids are
        # the map back into a deck that must stay outside the tree.
        summary["bars"] = [{k: v for k, v in b.items() if k != "rows"} for b in doc["bars"]]
        for k in ("layer1", "layer2"):
            if doc.get(k):
                # THE ROW IDS ARE DROPPED HERE, and that is the phrase-free rule applied to its
                # nearest neighbour: a held-out row id plus a class plus a verdict is a map back into
                # a deck that must stay outside the tree. `group_detail` is named explicitly beside
                # the `_ids` suffix rule because it is the same map wearing a different key: one entry
                # per near_duplicate/multi row, carrying that row's id.
                _DROP = ("unscored", "group_detail")
                v = {kk: vv for kk, vv in doc[k].items() if kk != "per_class"}
                v["per_class"] = {cl: {kk: vv for kk, vv in d.items()
                                       if not kk.endswith("_ids") and kk not in _DROP}
                                  for cl, d in doc[k]["per_class"].items()}
                summary[k] = v
        if doc.get("latency"):
            summary["latency"] = doc["latency"]              # already phrase-free: percentiles only
        # THE DATED BANK IS CUMULATIVE, NEVER CLOBBERING. Two runs of the same deck on the same date
        # measure different layers (layer 1 is free and runs often; layer 2 is billed and runs once),
        # and a plain write would silently replace a banked layer-2 result with a layer-1 re-run --
        # the reader would see a deck whose most expensive measurement had vanished with no error.
        # An existing summary for the same deck is READ and the new run's layers are merged onto it,
        # with `layers_run` the union in canonical order.
        _prev_path = bank_dir / f"{tag}_summary.json"
        if _prev_path.is_file():
            try:
                _prev = json.loads(_prev_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 -- an unreadable predecessor is replaced, not merged
                _prev = {}
            if isinstance(_prev, dict):
                _merged = dict(_prev)
                _merged.update(summary)
                _merged["layers_run"] = [x for x in ("1", "2", "latency")
                                         if x in set(_prev.get("layers_run") or [])
                                         | set(summary.get("layers_run") or [])]
                for _k in ("layer1", "layer2", "latency"):     # a layer this run did not measure
                    if _k not in summary and _k in _prev:      # keeps its banked figures
                        _merged[_k] = _prev[_k]
                _seen = {b["bar"] for b in summary.get("bars") or []}
                _merged["bars"] = list(summary.get("bars") or []) + [
                    b for b in (_prev.get("bars") or []) if b["bar"] not in _seen]
                _merged["failing_bars"] = sorted({b["bar"] for b in _merged["bars"]
                                                  if b["verdict"] in ("STOP", "MISS")})
                _merged["verdict"] = ("STOP" if any(b["verdict"] == "STOP" for b in _merged["bars"])
                                      else "LAND-DARK")
                summary = _merged
        (bank_dir / f"{tag}_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
        # THE BANKED MARKDOWN IS RENDERED FROM THE SANITISED SUMMARY, never from `doc`: one producer
        # for the phrase-free rule, so a future column added to the full artifact cannot leak through
        # the prose half while the JSON half stays clean.
        (bank_dir / f"{tag}_summary.md").write_text(markdown(summary), encoding="utf-8",
                                                    newline="\n")
        if doc.get("latency"):
            # THE D10 BANK, ONE FILE PER DECK. The fixed name `latency.json` was a CLOBBER: the
            # summaries merge (a layer-1 re-run cannot erase a banked layer 2) but this file was
            # written unconditionally, so a `--latency` pass over the HELD-OUT deck would have
            # silently replaced the calibration bank `config_check` grades. The name now carries the
            # deck, and `config_check.SUBJECT_LATENCY_GLOB` reads every one of them and grades the
            # WORST -- so a second deck's harness run adds a measurement instead of erasing one.
            (bank_dir / f"latency_{tag}.json").write_text(
                json.dumps(dict(doc["latency"], deck=doc["deck"], graph_hash=doc["graph_hash"],
                                generated_utc=doc["generated_utc"]), indent=2, ensure_ascii=False),
                encoding="utf-8", newline="\n")
        print(f"bank:     {bank_dir}")

    print("")
    print("PRE-REGISTERED BARS")
    for b in doc["bars"]:
        print(f"  {b['verdict']:<5} {_ascii(b['bar']):<44} {_ascii(b['detail'])}"
              + (f"  rows: {_ascii(', '.join(b['rows']))}" if b.get("rows") else ""))
    if doc.get("layer2"):
        print(f"  MEASURED DOLLARS: ${doc['layer2']['usd_measured']:.4f} over "
              f"{doc['layer2']['calls']} calls (usage fields, not the anchor)")
    print(f"VERDICT: {doc['verdict']}"
          + (f" -- failing: {'; '.join(_ascii(x) for x in doc['failing_bars'])}"
             if doc["failing_bars"] else ""))
    return 1 if doc["verdict"] == "STOP" else 0


if __name__ == "__main__":
    sys.exit(main())
