"""D-HP G1 clause (1b) -- THE FIXTURE POSITIVE CONTROL, offline replay harness.

DESIGN OF RECORD: plan 10.24 (design + pre-registration, written BEFORE the run) and 10.25 (the
read). CONSUMER: plan 10.29 / M-2 (the facet-labelled rebuild), which extends this harness -- this
file is the byte-faithful rescue of the scored instrument, NOT the M-2 build: the 15-record miss
cap and the absence of facet labels are deliberate and must not be "improved" here.

Imports the REAL render stack from source at HEAD 88090c46 (no src edits, no monkeypatching of
render logic) and replays it over the r6 TREATMENT artifacts' `raw_draft.postverify_*` prose --
the exact seam the live turn feeds the handle passes (answer.py:2813 snapshot -> 2865..2932 stack
-> 2933 `verified_*` snapshot).

ARMS
  F0  baseline, no injection            -- fidelity anchor
  F1  [N] index +1 on solitary handles  -- the clause's [N] half
  F2  [E] swapped to a real-but-wrong EMITTED index -- the clause's [E] half
  F3  [N] index -> len(calls)+50        -- harness liveness (the drop ladder must fire 100%)

Paths: the repo root is derived from THIS FILE's location (jobs/utils/dhp_census/ -> three levels
up), never from the process cwd; `set_paths()` accepts a --root / --corpus-dir override. Scoring
logic is untouched from the scratchpad original.

ASCII only on stdout.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# jobs/utils/dhp_census/<this file>  ->  repo root
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir))
CORPUS_DIR = os.path.join(REPO, "data", "dhp_g1")


def default_out_path(corpus_dir=None):
    return os.path.join(corpus_dir or CORPUS_DIR, "dhp_1b_result.json")


def set_paths(root=None, corpus_dir=None):
    """Point the harness at a repo root / corpus dir other than the file-derived defaults.

    Re-inserts <root>/src on sys.path so the render stack is imported LIVE from that tree."""
    global REPO, CORPUS_DIR
    if root:
        REPO = os.path.abspath(root)
        CORPUS_DIR = os.path.join(REPO, "data", "dhp_g1")
        _arm_src_path(REPO)
    if corpus_dir:
        CORPUS_DIR = os.path.abspath(corpus_dir)
    return REPO, CORPUS_DIR


def _arm_src_path(root):
    p = os.path.join(root, "src")
    if p not in sys.path:
        sys.path.insert(0, p)


_arm_src_path(REPO)

from leviathan.graphrag import answer as A          # noqa: E402  the REAL render stack

TREATMENT = ["r6_inv3_deepv2_width_deep_hp_r1", "r6_inv4_deepv2_width_deep_hp_r2",
             "r6_inv7_shape_esc_deep_hp_r1", "r6_inv8_shape_esc_deep_hp_r2",
             "r6_cov_inv3_deep_hp_r1", "r6_cov_inv4_deep_hp_r2"]

_SOLITARY_N = re.compile(r"\[N(\d+)\]")             # unsuffixed, single-member only
_SOLITARY_E = re.compile(r"\[E(\d+)\]")


def load(run, corpus_dir=None):
    p = os.path.join(corpus_dir or CORPUS_DIR, run + ".json")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def mk_calls(served_rows):
    """Reconstruct the `extra_number_calls` list `_resolve_number_handles` reads, from the artifact's
    `served_rows` projection (eval._served_rows). The projection is positional and 1-indexed the same
    way ([Nk] -> calls[k-1]), which is the anchoring verify.py and the footer both use."""
    calls = []
    for sr in (served_rows or []):
        q = {"table": sr.get("table"), "metric": sr.get("metric")}
        calls.append({"query": q, "status": sr.get("status"),
                      "rows": [dict(r) for r in (sr.get("rows") or []) if isinstance(r, dict)]})
    return calls


def n_uniq_of(ans):
    """Lower bound on len(uniq) that reproduces the recorded resolution exactly: every [E] index that
    appears in the postverify prose resolved live (`prose_handles.unresolvable == 0` on the whole r6
    treatment arm), and every key of `citation_resolved` is a real emitted item."""
    hi = 0
    for k in (ans.get("citation_resolved") or {}):
        m = re.match(r"E(\d+)$", str(k))
        if m:
            hi = max(hi, int(m.group(1)))
    rd = ans.get("raw_draft") or {}
    txt = (rd.get("postverify_tldr") or "") + "\n" + (rd.get("postverify_mechanism") or "")
    for m in A._E_HANDLE_RX.finditer(txt):
        for i in A._e_handle_members(m.group(0)):
            hi = max(hi, i)
    return hi


def emitted_e(ans):
    """The [E] indices the reader ACTUALLY GOT (the footer's own emission decision, as recorded).
    Swap targets are drawn only from here, which is what makes skipping `_prune_orphan_evidence_handles`
    provably harmless: a swapped handle names a row the footer emitted, so the prune's verdict is
    unchanged."""
    out = []
    for k in (ans.get("citation_resolved") or {}):
        m = re.match(r"E(\d+)$", str(k))
        if m:
            out.append(int(m.group(1)))
    return sorted(set(out))


def render_stack(structured, calls, n_uniq, handle_prose=True):
    """answer.py:2865-2932 replayed in order, functions imported from source.

    OMITTED, both stated in the readout and provably inert on this population:
      * `_prune_orphan_evidence_handles` -- keyed on the footer's emission decision, which the artifact
        does not carry. It returned 0 on 76/76 live treatment rows, and F2's swap targets are drawn from
        the EMITTED set, so its verdict cannot differ between baseline and mutant.
      * `_drop_slot_orphan_sentences` / `_tidy_strip_orphans` -- both are licensed ONLY by verifier strip
        seams (`_report_seams`), which the artifact does not carry, so both are no-ops here. The
        injection happens AFTER verify, so the seams are identical in baseline and mutant: neither pass
        can account for an injected case that the passes below do not.
    """
    v = {"enabled": True, "by_rule": {}, "stripped": 0, "seams": [], "resolved": {}}
    trace = {}
    if handle_prose:
        trace["bare_digit_dropped"] = A._drop_bare_digit_sentences(structured, calls, v)
    trace["number_handles"] = A._resolve_number_handles(structured, calls, handle_prose=handle_prose)
    if handle_prose:
        A._fold_render_classes(v, trace["number_handles"])
    trace["number_rows_deduped"] = A._dedup_number_handles(structured, calls)
    uniq = [{"i": i} for i in range(n_uniq)]        # only len(uniq) is read by either [E] pass
    trace["prose_handles"] = A._resolve_evidence_handles(structured, uniq, handle_prose=handle_prose)
    if handle_prose:
        trace["wrong_slot_audit"] = A._wrong_slot_audit(trace["number_handles"])
        _es = A._drop_evidence_value_slot(structured, uniq, v)
        A._fold_ledger_class(v, A._E_VALUE_SLOT_CLASS, _es.get("convicted"))
        trace["evidence_slot_dropped"] = _es
    trace["prose_debris_tidied"] = A._tidy_handle_debris(structured)
    trace["verifier"] = v
    return trace


# ---- injections ------------------------------------------------------------------------------

def inject_n_shift(structured, calls, delta=1, out_of_range=False):
    """Rewrite every SOLITARY unsuffixed [Nk] to [N(k+delta)] (or far out of range).

    Grouped and suffixed tokens are left alone on purpose: the clause names the solitary case, and a
    solitary handle is the only shape that receives the VALUE SPLICE -- i.e. the only shape whose
    mis-binding can put a real, cited, WRONG number in front of the reader."""
    hits = []
    for field in ("tldr", "mechanism"):
        text = structured.get(field)
        if not isinstance(text, str):
            continue

        def _sub(m, field=field):
            k = int(m.group(1))
            j = (len(calls) + 50) if out_of_range else (k + delta)
            hits.append({"field": field, "orig": k, "inj": j})
            return "[N%d]" % j

        structured[field] = _SOLITARY_N.sub(_sub, text)
    return hits


def inject_e_swap(structured, emitted):
    """Rewrite every SOLITARY [Ek] whose index is in the EMITTED set to a DIFFERENT emitted index --
    'pointing at a real-but-wrong item' in the strongest available sense: the target is a row the
    reader demonstrably received."""
    hits = []
    if len(emitted) < 2:
        return hits
    for field in ("tldr", "mechanism"):
        text = structured.get(field)
        if not isinstance(text, str):
            continue

        def _sub(m, field=field):
            k = int(m.group(1))
            if k not in emitted:
                return m.group(0)
            others = [x for x in emitted if x != k]
            j = others[(emitted.index(k) + 1) % len(others)]
            hits.append({"field": field, "orig": k, "inj": j})
            return "[E%d]" % j

        structured[field] = _SOLITARY_E.sub(_sub, text)
    return hits


# ---- scoring ---------------------------------------------------------------------------------

def token_positions(text, rx):
    return [(m.start(), m.group(0)) for m in rx.finditer(text or "")]


def sentences(text):
    """The renderer's own sentence spans, walked end to end -- so 'an innocent sentence' means exactly
    what `_handle_sentence_span` means by a sentence."""
    out, pos = [], 0
    text = text or ""
    while pos < len(text):
        s0, s1 = A._handle_sentence_span(text, pos)
        if s1 <= pos:
            break
        out.append(text[s0:s1])
        pos = max(s1, pos + 1)
    return out


def survives(text, idx, kind="N"):
    """Did the injected handle token survive onto the page (either standing, or as a spliced value)?"""
    return ("[%s%d]" % (kind, idx)) in (text or "")
