"""D-HP G1 clause (1b) -- the fixture positive control, arms F1/F2/F3. Scored per 10.24.5.

DESIGN OF RECORD: plans 10.24 / 10.25. CONSUMER: plan 10.29 / M-2. This is the byte-faithful
rescue of the scored instrument: the 15-record `misses_sample` cap and the absence of facet labels
are the M-2 build's business, NOT this file's -- scoring here is unchanged from the run of record.

Isolated injection: ONE handle per replay, on a fresh copy of the answer's postverify prose, scored
against that answer's own F0 baseline replay.

CLI: --root / --corpus-dir / --out (defaults derived from this file's location: repo root three
levels up, corpus + result under ROOT/data/dhp_g1). --census-only stops after the population load
and prints the answer / injection-population counts without running any replay arm.
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dhp_1b_harness as H                                  # noqa: E402

# THE STRUCK-ROW LAW: eval._served_rows caps its projection at _ROWS_PER_RECORD_CAP=400 rows per
# RECORD, spent in call order; this answer exhausts the budget so 51 of its calls project
# row_count>0 with ZERO rows. Struck for a LOSSY INPUT, before injection -- never for its result.
VOID = {("r6_inv8_shape_esc_deep_hp_r2", "shape_esc_episode_us_drought")}
# D-HP-25 V1 (plan 10.30.6): the geo axis' two counters extend BOTH hand-enumerations, exactly as
# `eval.py:2775-2777` extends its own two. A single-sided extension is how a class becomes invisible in
# the one readout a gate is scored on -- M-2's bars ("catch rate per arm", "innocent deletions 0/2899")
# are read on THIS instrument, and without these keys a V1 conviction would still move `sentences_dropped`
# while its FACET ATTRIBUTION read as `binding_refused` alone. `geo_checked` is the DENOMINATOR
# (comparisons, never attempts) and is therefore in the census and NOT in the charges: it moves on turns
# where nothing was convicted, and a charge key that fires without a conviction is a mislabelled catch.
CENSUS_KEYS = ("substituted", "handles_dropped", "sentences_dropped", "unresolvable",
               "grouped_in_slot", "direction_sign_mismatch", "slot_scope_mismatch",
               "binding_refused", "empty_row_addressed", "geo_checked", "geo_mismatch")
CHARGE_KEYS = ("unresolvable", "empty_row_addressed", "binding_refused",
               "slot_scope_mismatch", "direction_sign_mismatch", "grouped_in_slot",
               "geo_mismatch")


def answers():
    for run in H.TREATMENT:
        d = H.load(run)
        for a in d["per_answer"]:
            if (run, a["id"]) in VOID:
                continue
            yield run, a


def run_stack(post, calls, n_uniq):
    st = {"tldr": post[0], "mechanism": post[1]}
    tr = H.render_stack(st, calls, n_uniq)
    return st, tr


_STRIP_TOK = re.compile(r"\[[NE][^\]]*\]")
_NON_ALPHA = re.compile(r"[^a-z]+")
# A sentence terminator standing immediately in front of a comma/semicolon: the reader-visible signature
# of a leading clause severed off the FRONT of a sentence, whose remnant then glues onto its neighbour
# ("... not wheat per se., sitting just below its five-year mean ..."). `_DEBRIS_RULES` closes ",." and
# " ," but has no rule for ".," -- recorded here as its own count, never folded into the deletion count.
_GLUE_RX = re.compile(r"[.!?]\s*[,;]")


def alpha_key(s, vals=()):
    """A sentence's IDENTITY under the render stack.

    THE STACK CAN ONLY ADD ONE KIND OF TEXT: a SPLICED VALUE, drawn from `_number_handle_value` over
    this answer's own call list. Everything else it does is removal or token rewriting. So the key is
    the sentence with (i) every value string this answer could possibly splice removed, (ii) every
    handle token removed, (iii) every non-letter removed. Two renderings of the SAME sentence then key
    identically whichever row was bound to it -- which is what makes the innocent-deletion test a test
    about DELETION rather than about substitution."""
    s = s or ""
    for v in vals:
        if v:
            s = s.replace(v, " ")
    # NO TOKEN REGEX. Stripping `[N..]`/`[E..]` with a closure-requiring pattern is not safe on real
    # prose: the r6 population contains an UNCLOSED token ("... priced at [N1 is absent -- the ARS/USD
    # row carries no value;") whose bracket pairs across a sentence boundary, so a whole-FIELD strip and
    # a per-SENTENCE strip disagree and the key stops being an identity. Dropping every non-letter does
    # the job with no such dependency: "[N7]" and "[N8]" both reduce to "n", "[E10]" and "[E14]" both
    # reduce to "e", so a re-pointed handle is invisible to the key by construction -- which is exactly
    # what a DELETION test wants.
    return _NON_ALPHA.sub(" ", s.lower()).strip()


def sent_keys(st, vals=()):
    """The baseline output's sentences, keyed, per field."""
    out = {}
    for f in ("tldr", "mechanism"):
        out[f] = [k for k in (alpha_key(s, vals) for s in H.sentences(st.get(f))) if k]
    return out


def field_keys(st, vals=()):
    """The WHOLE field, keyed. A baseline sentence is PRESENT in this output iff its key is a
    contiguous substring here.

    SUBSTRING, NOT SET MEMBERSHIP, AND THAT IS THE POINT. A remedy that severs a leading clause can
    leave the remnant glued onto the neighbouring sentence, which moves a SENTENCE BOUNDARY without
    deleting one word of the neighbour. Under a set-of-sentences test the neighbour reads as DELETED;
    under this one it reads as PRESENT, which is what the reader experiences. Gluing is recorded
    separately as a render defect -- it is not an innocent DELETION and this clause does not conflate
    the two."""
    return {f: alpha_key(st.get(f), vals) for f in ("tldr", "mechanism")}


def splice_vocab(calls):
    """Every string this answer's renderer could splice, longest first so a longer value is removed
    before one of its own prefixes."""
    out = set()
    for i in range(1, len(calls) + 1):
        for mag in (False, True):
            # BOTH polarity spellings: `_resolve_number_handles` passes `magnitude_only=True` for a
            # metric in the polarity table (D-HP-11's sign clause), so the string on the page can be
            # abs(value) while the raw read is signed. Missing one leaves its UNIT word behind and the
            # key stops being an identity.
            try:
                v = H.A._number_handle_value(calls[i - 1] if 1 <= i <= len(calls) else None, i,
                                             magnitude_only=mag)
            except Exception:  # noqa: BLE001
                v = None
            if v:
                out.add(v)
    return sorted(out, key=len, reverse=True)


def occurrences(post, rx):
    """[(field, start, index)] for every SOLITARY token, in document order."""
    out = []
    for fi, f in enumerate(("tldr", "mechanism")):
        for m in rx.finditer(post[fi] or ""):
            out.append((f, m.start(), m.end(), int(m.group(1))))
    return out


def mutate(post, field, s, e, token):
    p = list(post)
    fi = 0 if field == "tldr" else 1
    p[fi] = p[fi][:s] + token + p[fi][e:]
    return tuple(p)


def value_of(calls, idx):
    try:
        return H.A._number_handle_value(calls[idx - 1] if 1 <= idx <= len(calls) else None, idx)
    except Exception:  # noqa: BLE001
        return None


def call_id(calls, idx):
    if not (1 <= idx <= len(calls)):
        return None
    q = (calls[idx - 1] or {}).get("query") or {}
    return (q.get("table"), q.get("metric"))


def score(arm, delta_fn, rx, kind):
    tally = collections.Counter()
    charges = collections.Counter()
    misses = []
    innocent = []
    glued = []
    for run, a in answers():
        rd = a.get("raw_draft") or {}
        post = (rd.get("postverify_tldr") or "", rd.get("postverify_mechanism") or "")
        calls = H.mk_calls(a.get("served_rows"))
        n_uniq = H.n_uniq_of(a)
        emitted = H.emitted_e(a)
        vocab = splice_vocab(calls)
        bst, btr = run_stack(post, calls, n_uniq)
        B = btr["number_handles"] if kind == "N" else btr["prose_handles"]
        Bn = btr["number_handles"]
        bsent = sent_keys(bst, vocab)
        for field, s, e, k in occurrences(post, rx):
            j = delta_fn(k, calls, emitted)
            if j is None or j == k:
                continue
            tally["injected"] += 1
            mpost = mutate(post, field, s, e, "[%s%d]" % (kind, j))
            mst, mtr = run_stack(mpost, calls, n_uniq)
            M = mtr["number_handles"] if kind == "N" else mtr["prose_handles"]
            Mn = mtr["number_handles"]
            d = {key: M.get(key, 0) - B.get(key, 0) for key in CENSUS_KEYS}
            bd = {k2: (mtr["bare_digit_dropped"].get(k2, 0) - btr["bare_digit_dropped"].get(k2, 0))
                  for k2 in ("sentences_dropped", "clauses_severed")}
            es = {k2: (mtr["evidence_slot_dropped"].get(k2, 0) - btr["evidence_slot_dropped"].get(k2, 0))
                  for k2 in ("convicted", "handles_dropped", "sentences_dropped")}
            pre_removed = any(bd.values()) or any(es.values())
            removed = (d["handles_dropped"] + d["sentences_dropped"]) > 0
            if kind == "N":
                # <= -1 rather than == -1: a whole-sentence KILL takes the injected handle's splice AND
                # any sibling splice standing in the same sentence. That is still the ladder firing on
                # the injected case; the collateral is what the innocent-deletion test below reads.
                caught = removed and d["substituted"] <= -1
                missed = (d["substituted"] == 0) and not removed
            else:
                # the [E] half has no splice: caught == the handle left the page
                caught = removed or d["unresolvable"] > 0
                missed = not caught
            if caught:
                tally["caught"] += 1
                named = [c for c in CHARGE_KEYS if d.get(c, 0) > 0]
                charges["+".join(named) or "(none)"] += 1
            elif missed:
                tally["missed"] += 1
                if pre_removed:
                    # sub-count, reported beside the miss: the carrier sentence left the page under an
                    # EARLIER pass (`_drop_bare_digit_sentences` / `_drop_evidence_value_slot`), so the
                    # injected handle did not reach the reader even though the [N] resolver never saw it.
                    tally["missed_but_carrier_removed_earlier"] += 1
                if kind == "N":
                    vr, vw = value_of(calls, k), value_of(calls, j)
                    misses.append({"run": run, "id": a["id"], "field": field, "orig": k, "inj": j,
                                   "right": vr, "wrong": vw,
                                   "value_differs": (vr != vw),
                                   "diff_receipt": call_id(calls, k) != call_id(calls, j),
                                   "removed_by_an_earlier_pass": pre_removed,
                                   "scope_checked_moved": (Mn.get("scope_checked", 0)
                                                           - Bn.get("scope_checked", 0))})
                else:
                    misses.append({"run": run, "id": a["id"], "field": field, "orig": k, "inj": j})
            else:
                tally["ambiguous"] += 1
                misses.append({"run": run, "id": a["id"], "orig": k, "inj": j, "delta": d,
                               "bare_digit_delta": bd, "evidence_slot_delta": es,
                               "removed_by_an_earlier_pass": pre_removed, "AMBIGUOUS": True})
            # innocent-deletion test: sentences lost that did NOT carry the injected handle
            mfield = field_keys(mst, vocab)
            for f2 in ("tldr", "mechanism"):
                extra = len(_GLUE_RX.findall(mst.get(f2) or "")) - len(_GLUE_RX.findall(bst.get(f2) or ""))
                if extra > 0:
                    tally["glued_remnants"] += extra
                    if len(glued) < 25:
                        _hit = _GLUE_RX.search(mst.get(f2) or "")
                        glued.append({"run": run, "id": a["id"], "orig": k, "inj": j,
                                      "text": (mst.get(f2) or "")[max(0, _hit.start() - 90):
                                                                  _hit.start() + 90]})
            lost = [(f2, k2) for f2 in ("tldr", "mechanism")
                    for k2 in bsent[f2] if k2 not in mfield[f2]]
            if lost:
                # THE CARRIER IS EXCLUDED BY IDENTITY, NOT BY BYTES. Its span is taken with the
                # renderer's own `_handle_sentence_span` off the pre-stack text and keyed the same way
                # every other sentence is, so a sentence the remedy SEVERED (its key changes) is still
                # recognised as the carrier and is not miscounted as an innocent loss.
                fi = 0 if field == "tldr" else 1
                bs0, bs1 = H.A._handle_sentence_span(post[fi], s)
                carrier = alpha_key(post[fi][bs0:bs1], vocab)
                strays = [t for t in lost if t[1] != carrier]
                if strays:
                    tally["innocent_deletions"] += len(strays)
                    if len(innocent) < 80:
                        innocent.append({"run": run, "id": a["id"], "orig": k, "inj": j,
                                         "carrier": carrier, "lost": [t[1] for t in strays]})
    return tally, charges, misses, innocent, glued


def arms():
    """The three scored arms, in run order. Shared with the census so the population counts are the
    arms' OWN eligibility rule, not a re-statement of it."""
    return [
        ("F3_out_of_range", lambda k, calls, em: len(calls) + 50, H._SOLITARY_N, "N"),
        ("F1_index_plus_1", lambda k, calls, em: k + 1, H._SOLITARY_N, "N"),
        ("F2_e_real_but_wrong", (lambda k, calls, em:
                                 (None if (k not in em or len(em) < 2)
                                  else [x for x in em if x != k][(em.index(k)) % (len(em) - 1)])),
         H._SOLITARY_E, "E"),
    ]


def census():
    """POPULATION ONLY -- load the corpus and count what each arm would inject. No replay, no render
    stack call, no mutation. Reproduces the manifest's population block (answers_scored and the
    per-arm injection populations) as a standalone check that the corpus is intact."""
    per_arm = collections.Counter()
    n_answers = 0
    n_void = 0
    solitary_n = 0
    solitary_e = 0
    for run in H.TREATMENT:
        d = H.load(run)
        for a in d["per_answer"]:
            if (run, a["id"]) in VOID:
                n_void += 1
                continue
            n_answers += 1
            rd = a.get("raw_draft") or {}
            post = (rd.get("postverify_tldr") or "", rd.get("postverify_mechanism") or "")
            calls = H.mk_calls(a.get("served_rows"))
            emitted = H.emitted_e(a)
            solitary_n += len(occurrences(post, H._SOLITARY_N))
            solitary_e += len(occurrences(post, H._SOLITARY_E))
            for name, fn, rx, _kind in arms():
                for _f, _s, _e, k in occurrences(post, rx):
                    j = fn(k, calls, emitted)
                    if j is None or j == k:
                        continue
                    per_arm[name] += 1
    return {"answers_in_arm": n_answers + n_void, "answers_scored": n_answers,
            "answers_struck": n_void, "solitary_N_occurrences": solitary_n,
            "solitary_E_occurrences": solitary_e, "injected_per_arm": dict(per_arm)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="D-HP G1 clause (1b) fixture positive control")
    ap.add_argument("--root", default=None, help="repo root (default: derived from this file)")
    ap.add_argument("--corpus-dir", default=None,
                    help="dir holding the r6 treatment artifacts (default ROOT/data/dhp_g1)")
    ap.add_argument("--out", default=None,
                    help="result path (default ROOT/data/dhp_g1/dhp_1b_result.json)")
    ap.add_argument("--census-only", action="store_true",
                    help="load the population and print counts; run NO replay arm")
    args = ap.parse_args(argv)

    H.set_paths(root=args.root, corpus_dir=args.corpus_dir)
    out_path = args.out or H.default_out_path()

    if args.census_only:
        c = census()
        print("== census (population only, no replay) ==")
        for k in ("answers_in_arm", "answers_scored", "answers_struck",
                  "solitary_N_occurrences", "solitary_E_occurrences"):
            print("   %-24s %s" % (k, c[k]))
        for k in sorted(c["injected_per_arm"]):
            print("   injected[%-20s] %s" % (k, c["injected_per_arm"][k]))
        sys.stdout.flush()
        return c

    out = {}
    for name, fn, rx, kind in arms():
        t, ch, mi, inn, gl = score(name, fn, rx, kind)
        out[name] = {"tally": dict(t), "charges": dict(ch),
                     "n_misses": len(mi), "misses_sample": mi[:15], "innocent_sample": inn,
                     "glued_sample": gl}
        print("== %s ==" % name)
        print("   tally  :", dict(t))
        print("   charges:", dict(ch))
        if kind == "N" and mi:
            vd = sum(1 for m in mi if m.get("value_differs"))
            dr = sum(1 for m in mi if m.get("diff_receipt"))
            print("   misses : %d ; wrong VALUE differs %d ; different (table,metric) %d"
                  % (len(mi), vd, dr))
        sys.stdout.flush()
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("wrote %s" % out_path)
    return out


if __name__ == "__main__":
    main()
