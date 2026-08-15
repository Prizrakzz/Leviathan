"""D-HP G1 clause (1b) -- the fixture positive control, arms F0/F1/F2/F3. Scored per 10.24.5.

DESIGN OF RECORD: plans 10.24 / 10.25 (the original read) and 10.30.7 M-2 (this re-run). The
10.24.5 SCORING RULES ARE UNCHANGED. What M-2 adds is INSTRUMENT:

  * THE 15-RECORD PER-ARM MISS CAP IS LIFTED. Every injection -- caught, missed or ambiguous --
    carries its own record with its FACET LABEL BLOCK. A capped sample cannot produce a
    per-injection denominator, and a denominator borrowed from the recon's upper frame would be a
    number about the recon rather than about the build (10.30.7's own words).
  * PER-INJECTION FACET LABELS. `[N]`: orig-vs-injected `(table, metric)`, the SHIPPED period
    scope check's two-sidedness and verdict (`_receipt_period_text` + `_period_years`), and unit.
    THE GEO FACET IS UNMEASURABLE OFFLINE ON THIS CORPUS and is labelled as such, never faked:
    these artifacts predate tightening T2, so `served_rows` carries no `country` on either the call
    or the row (probed and reported, not assumed). `[E]`: V2's OWN three-clause conjunction,
    decomposed -- claim window owns exactly one geo, orig receipt text contains the claim's geo
    closure, injected receipt text lacks it, injected text positively names another country.
  * THE `[E]` RECEIPT TEXT IS HYDRATED FROM THE SIDECAR (`H.uniq_rows_of`) and V2 is replayed in
    its shipped stack position. Plan 10.30.11(C) residual 1: a replay that scores V2 off the stored
    140-char snippet is measuring TRUNCATION and its number is not V2's.
  * F0 IS AN ARM. The fidelity table of 10.24.3 is recomputed and re-shown beside the arms, so the
    harness is shown to still be the harness on the same read that scores the bars.

Isolated injection: ONE handle per replay, on a fresh copy of the answer's postverify prose, scored
against that answer's own F0 baseline replay.

CLI: --root / --corpus-dir / --out (defaults derived from this file's location: repo root three
levels up, corpus + result under ROOT/data/dhp_g1). --census-only stops after the population load
and prints the answer / injection-population counts without running any replay arm. --f0-only runs
the fidelity anchor and nothing else. AN EXISTING --out IS NEVER OVERWRITTEN (--force to allow).
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


def run_stack(post, calls, uniq):
    st = {"tldr": post[0], "mechanism": post[1]}
    tr = H.render_stack(st, calls, uniq)
    return st, tr


# ---- FACET LABELS (M-2, plan 10.30.7) --------------------------------------------------------
#
# A LABEL IS COMPUTED PER INJECTION AND FROM THE SHIPPED PREDICATES, NEVER FROM A HAND-ROLLED
# RESTATEMENT OF THEM. The `[N]` period label is `_slot_scope_mismatch`'s OWN `(compared, mismatch)`
# pair evaluated against the INJECTED call -- i.e. "would the shipped detector have had two sides to
# compare, and did they differ" -- and the `[E]` label is `_e_geo_contradicts` itself plus its three
# clauses decomposed. That is what makes the 95% denominator a statement about THIS BUILD.

_GEO_OFFLINE = "UNMEASURABLE_OFFLINE_no_country_in_served_rows"


def _call_at(calls, idx):
    return calls[idx - 1] if 1 <= idx <= len(calls) else None


def receipt_years(calls, idx):
    """The RECEIPT side of the shipped period check: `_period_years(_receipt_period_text(call))`.

    On this corpus the query half of `_receipt_period_text` is structurally silent -- `mk_calls` builds
    `query` from the projection, which carries `table`/`metric` and nothing else -- so what this reads
    is the HEADLINE ROW's period. That is 10.24.3's named `scope_checked` gap, re-stated as a label."""
    try:
        return sorted(H.A._period_years(H.A._receipt_period_text(_call_at(calls, idx))))
    except Exception:  # noqa: BLE001
        return []


def receipt_unit(calls, idx):
    try:
        hr = H.A.cit.headline_row(_call_at(calls, idx)) or {}
        return (str(hr.get("unit") or "").strip() or None)
    except Exception:  # noqa: BLE001
        return None


def labels_n(mtext, s, tok, calls, k, j):
    """The `[N]` facet block for one injection, read off the MUTANT prose at the mutated token."""
    s0, s1 = H.A._handle_sentence_span(mtext, s)
    he = s + len(tok)
    try:
        clause = H.A._handle_period_phrase(mtext, s0, s1, s, he)
    except Exception:  # noqa: BLE001
        clause = ""
    try:
        comp_i, mis_i = H.A._slot_scope_mismatch(clause, _call_at(calls, j), j)
    except Exception:  # noqa: BLE001
        comp_i, mis_i = False, False
    try:
        comp_o, mis_o = H.A._slot_scope_mismatch(clause, _call_at(calls, k), k)
    except Exception:  # noqa: BLE001
        comp_o, mis_o = False, False
    ry_o, ry_i = receipt_years(calls, k), receipt_years(calls, j)
    u_o, u_i = receipt_unit(calls, k), receipt_unit(calls, j)
    cid_o, cid_i = call_id(calls, k), call_id(calls, j)
    try:
        cl_years = sorted(H.A._period_years(clause, declared_only=True)
                          | H.A._declared_span_years(clause))
    except Exception:  # noqa: BLE001
        cl_years = []
    return {
        # (i) THE RECEIPT IDENTITY FACET
        "receipt_orig": list(cid_o) if cid_o else None,
        "receipt_inj": list(cid_i) if cid_i else None,
        "f_table_metric_differs": bool(cid_o != cid_i),
        # (ii) THE PERIOD FACET -- the SHIPPED check's own two-sidedness, on the INJECTED call
        "clause_period_phrase": clause.strip()[:120],
        "clause_declared_years": cl_years,
        "receipt_years_orig": ry_o,
        "receipt_years_inj": ry_i,
        "f_period_two_sided_inj": bool(comp_i),
        "f_period_two_sided_differs": bool(comp_i and mis_i),
        "f_period_two_sided_orig": bool(comp_o),
        "f_period_orig_would_convict": bool(comp_o and mis_o),
        "f_receipt_periods_differ": bool(ry_o != ry_i),
        # (iii) THE UNIT FACET
        "unit_orig": u_o, "unit_inj": u_i,
        "f_unit_differs": bool((u_o or None) != (u_i or None)),
        # (iv) THE GEO FACET -- NOT MEASURED, AND SAID SO
        "f_geo": _GEO_OFFLINE,
        # (v) out of range: F3's facet, and it is always catchable
        "f_inj_out_of_range": not (1 <= j <= len(calls)),
    }


def _claim_geo_block(mtext, s, tok):
    """V2's clause (a), decomposed with the SHIPPED core: does the claim window own exactly one geo?"""
    g = H.A._geo
    s0, s1 = H.A._handle_sentence_span(mtext, s)
    sent = mtext[s0:s1]
    a0, b0 = s - s0, s + len(tok) - s0
    out = {"claim_one_geo": False, "claim_slug": None, "claim_window_geos": [],
           "claim_sentinel": False, "claim_owned": False}
    try:
        toks = g.extract_geos(sent)
        sibs = [(mm.start(), mm.end()) for mm in H.A._E_HANDLE_RX.finditer(sent)]
        lo, hi = H.A._sibling_window(sent, a0, b0, siblings=sibs)
        out["claim_sentinel"] = bool(g.sentinel_hit(sent[lo:hi]))
        inw = sorted({sl for (ts, te, sl) in toks if ts >= lo and te <= hi})
        out["claim_window_geos"] = inw
        if not toks or out["claim_sentinel"] or len(inw) != 1 or inw == [g.EU_SLUG]:
            return out, set()
        kk = H.A._owned_token(sent, a0, b0, toks, H.A._GEO_RIGHT_APPOS_RX, siblings=sibs)
        if kk is None:
            return out, set()
        out["claim_owned"] = True
        out["claim_one_geo"] = True
        out["claim_slug"] = toks[kk][2]
        return out, g.canon_closure(toks[kk][2])
    except Exception:  # noqa: BLE001
        return out, set()


def _receipt_geo_block(row, claim):
    """V2's clauses (b) and (c) against ONE receipt row's HYDRATED text."""
    g = H.A._geo
    body = str((row or {}).get("text") or "")
    out = {"has_text": bool(body.strip()), "n_chars": len(body),
           "receipt_aggregate": False, "contains_claim_closure": None, "names_other": []}
    if not out["has_text"]:
        return out
    try:
        if g.sentinel_hit(body):
            out["receipt_aggregate"] = True
            return out
        found = g.slugs_in(body)
        out["contains_claim_closure"] = bool(claim & g.closure_of(found)) if claim else None
        out["names_other"] = sorted({sl for sl in found
                                     if sl != g.EU_SLUG and not (g.canon_closure(sl) & claim)}) \
            if claim else []
    except Exception:  # noqa: BLE001
        pass
    return out


def labels_e(mtext, s, tok, rows, k, j):
    """The `[E]` facet block: V2's own conjunction, decomposed, plus the verdict of V2 itself."""
    s0, s1 = H.A._handle_sentence_span(mtext, s)
    claim_b, claim = _claim_geo_block(mtext, s, tok)
    r_o = rows[k - 1] if 1 <= k <= len(rows) else None
    r_i = rows[j - 1] if 1 <= j <= len(rows) else None
    b_o = _receipt_geo_block(r_o, claim)
    b_i = _receipt_geo_block(r_i, claim)
    # V2 ITSELF, on the injected row -- the catchable predicate, not a restatement of it.
    catch = False
    try:
        mm = None
        for cand in H.A._E_HANDLE_RX.finditer(mtext):
            if cand.start() == s:
                mm = cand
                break
        if mm is not None and r_i is not None:
            catch = bool(H.A._e_geo_contradicts(mtext, s0, s1, mm, r_i))
    except Exception:  # noqa: BLE001
        catch = False
    try:
        hgp = sorted(H.A._handle_geo_phrase(mtext, s0, s1, s, s + len(tok)) or ())
    except Exception:  # noqa: BLE001
        hgp = []
    out = dict(claim_b)
    out.update({
        "handle_geo_phrase": hgp,
        "orig_text_hydrated": bool(b_o["has_text"]), "inj_text_hydrated": bool(b_i["has_text"]),
        "orig_text_chars": b_o["n_chars"], "inj_text_chars": b_i["n_chars"],
        "f_orig_contains_claim_closure": b_o["contains_claim_closure"],
        "f_inj_lacks_claim_closure": (None if b_i["contains_claim_closure"] is None
                                      else (not b_i["contains_claim_closure"])),
        "f_inj_names_other_country": bool(b_i["names_other"]),
        "inj_other_countries": b_i["names_other"],
        "inj_receipt_aggregate": b_i["receipt_aggregate"],
        "orig_receipt_aggregate": b_o["receipt_aggregate"],
        "f_v2_catchable": bool(catch),
    })
    return out


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


def _is_subseq(sub, sup):
    """Are `sub`'s words a SUBSEQUENCE of `sup`'s (order preserved, gaps allowed)?"""
    it = iter(sup)
    return all(w in it for w in sub)


def carrier_remnant(k2, carrier_key):
    """Is the lost BASELINE-OUTPUT sentence `k2` a REMNANT OF THE CARRIER?

    [M-2 INSTRUMENT DEFECT, FOUND AND FIXED HERE 2026-08-15 -- IT IS THE INSTRUMENT, NOT THE
    RENDERER.] The rescued exclusion compared the carrier's PRE-STACK key against the BASELINE
    OUTPUT's sentence keys and excluded only on EXACT equality. That silently breaks whenever the
    BASELINE stack itself already edited the carrier sentence -- `_drop_evidence_value_slot` severing
    an `[E]` standing in a value slot, or the debris pass closing a frame. The baseline output then
    carries a SHORTER carrier, whose key no longer equals the pre-stack key, so when the mutant's
    remedy kills that same sentence it is counted as an INNOCENT loss. Six F3 cases and one F1 case
    on this corpus are exactly that, hand-read one by one:
      * `ab_cf_india_rice`: pre-stack "... in my to n in my as documented at the may as of e",
        baseline output "... in my to n in my" -- the same sentence with its as-of clause severed.
      * `shape_esc_vintage_palm_stocks`: "... near the as of e e is one watch list item ..." ->
        "... near the as e is one watch list item ...".
    THE RULE IS FOUNDED ON A PROPERTY `alpha_key`'s OWN DOCSTRING ALREADY ASSERTS: the stack can only
    REMOVE text or rewrite tokens (the one thing it ADDS -- a spliced value -- is keyed away). So any
    baseline rendering of the carrier must have a word sequence that is a SUBSEQUENCE of the carrier's
    pre-stack word sequence. Exclusions are COUNTED and RECORDED, never silent, so the correction can
    be read as a number beside the raw one."""
    if not k2 or not carrier_key:
        return False
    if k2 == carrier_key:
        return True
    return _is_subseq(k2.split(), carrier_key.split())


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
    """One arm. 10.24.5's verdict rules, UNCHANGED; the cap on what is RECORDED is lifted."""
    tally = collections.Counter()
    charges = collections.Counter()
    records = []                      # EVERY injection, caught or missed, with its facet block
    innocent = []                     # UNCAPPED (bar B is read on this list)
    remnants = []                     # carrier remnants the exact-key rule miscounted, ALL recorded
    glued = []
    hyd = collections.Counter()
    for run, a in answers():
        rd = a.get("raw_draft") or {}
        post = (rd.get("postverify_tldr") or "", rd.get("postverify_mechanism") or "")
        calls = H.mk_calls(a.get("served_rows"))
        rows, hst = H.uniq_rows_of(a)
        for hk, hv in hst.items():
            hyd[hk] += hv
        emitted = H.emitted_e(a)
        vocab = splice_vocab(calls)
        bst, btr = run_stack(post, calls, rows)
        B = btr["number_handles"] if kind == "N" else btr["prose_handles"]
        Bn = btr["number_handles"]
        bsent = sent_keys(bst, vocab)
        for field, s, e, k in occurrences(post, rx):
            j = delta_fn(k, calls, emitted)
            if j is None or j == k:
                continue
            tally["injected"] += 1
            tok = "[%s%d]" % (kind, j)
            mpost = mutate(post, field, s, e, tok)
            mst, mtr = run_stack(mpost, calls, rows)
            M = mtr["number_handles"] if kind == "N" else mtr["prose_handles"]
            Mn = mtr["number_handles"]
            d = {key: M.get(key, 0) - B.get(key, 0) for key in CENSUS_KEYS}
            bd = {k2: (mtr["bare_digit_dropped"].get(k2, 0) - btr["bare_digit_dropped"].get(k2, 0))
                  for k2 in ("sentences_dropped", "clauses_severed")}
            es = {k2: (mtr["evidence_slot_dropped"].get(k2, 0) - btr["evidence_slot_dropped"].get(k2, 0))
                  for k2 in ("convicted", "handles_dropped", "sentences_dropped")}
            # D-HP-25 V2's own removal census. It is part of the SHIPPED ladder now, so an [E] handle
            # it severs LEFT THE PAGE in exactly the sense 10.24.5's [E] rule means -- and it is read
            # from its own key rather than folded into `prose_handles`, so the [N] arms cannot be
            # moved by it and the charge stays attributable.
            eg = {k2: ((mtr.get("evidence_geo_dropped") or {}).get(k2, 0)
                       - (btr.get("evidence_geo_dropped") or {}).get(k2, 0))
                  for k2 in ("convicted", "handles_dropped", "sentences_dropped")}
            pre_removed = any(bd.values()) or any(es.values())
            removed = (d["handles_dropped"] + d["sentences_dropped"]) > 0
            if kind == "E":
                removed = removed or (eg["handles_dropped"] + eg["sentences_dropped"]) > 0
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
            fi = 0 if field == "tldr" else 1
            mtext = mpost[fi]
            # THE READER-SIDE TEST, ADDED AT M-2 AND SCORED BY NOTHING -- it is what turns a delta
            # into a statement about the PAGE. 10.24.5's CAUGHT/MISSED rules are census DELTAS, and a
            # delta is blind to a removal that happened IDENTICALLY in both arms: on this corpus four
            # F3 cases have every census column equal because `_drop_bare_digit_sentences` took the
            # carrier sentence in BASELINE AND MUTANT ALIKE. Under the delta rule they read as
            # MISSED/AMBIGUOUS; on the page the injected handle is GONE. That is precisely the
            # "1,054 (100%) off the page (1,050 by the handle ladder)" split 10.25 reported, and this
            # label is the column that makes it re-readable instead of re-argued.
            bs0, bs1 = H.A._handle_sentence_span(post[fi], s)
            carrier_key = alpha_key(post[fi][bs0:bs1], vocab)
            mout = mst.get(field) or ""
            on_page = (tok in mout) or any(carrier_remnant(x, carrier_key)
                                           for x in (alpha_key(y, vocab) for y in H.sentences(mout))
                                           if x)
            if kind == "N":
                lab = labels_n(mtext, s, tok, calls, k, j)
                vr, vw = value_of(calls, k), value_of(calls, j)
                lab["value_orig"] = vr
                lab["value_inj"] = vw
                lab["f_value_differs"] = (vr != vw)
                lab["scope_checked_moved"] = (Mn.get("scope_checked", 0) - Bn.get("scope_checked", 0))
                lab["geo_checked_moved"] = (Mn.get("geo_checked", 0) - Bn.get("geo_checked", 0))
                # THE FACET-CATCHABLE PREDICATE, PER INJECTION AND PER ARM.
                #   F3 -- an index that CANNOT EXIST is catchable by definition (no facet needed).
                #   F1 -- the SHIPPED period check had two sides and they differed. The geo axis is
                #         excluded because it is UNMEASURABLE on this corpus, not because it is clean.
                lab["FACET_CATCHABLE"] = bool(lab["f_inj_out_of_range"]
                                              or lab["f_period_two_sided_differs"])
                # THE FACET-IDENTICAL RESIDUAL: no facet this instrument can read distinguishes the
                # two receipts. Reported as a named number, per 10.30.7's honesty clause.
                lab["FACET_IDENTICAL"] = not (lab["f_table_metric_differs"]
                                              or lab["f_receipt_periods_differ"]
                                              or lab["f_unit_differs"]
                                              or lab["f_inj_out_of_range"])
            else:
                lab = labels_e(mtext, s, tok, rows, k, j)
                # V2's OWN CONJUNCTION is the catchable predicate for F2.
                lab["FACET_CATCHABLE"] = bool(lab["f_v2_catchable"])
                lab["FACET_IDENTICAL"] = not (lab["claim_one_geo"]
                                              and lab["f_inj_names_other_country"])
            lab["injected_token_literal_on_page"] = (tok in mout)
            lab["carrier_sentence_on_page_in_mutant"] = bool(on_page)
            if not on_page:
                tally["off_the_page"] += 1
            rec = {"run": run, "id": a["id"], "field": field, "orig": k, "inj": j,
                   "verdict": ("caught" if caught else ("missed" if missed else "ambiguous")),
                   "removed_by_an_earlier_pass": pre_removed, "labels": lab}
            if caught:
                tally["caught"] += 1
                named = [c for c in CHARGE_KEYS if d.get(c, 0) > 0]
                if kind == "E" and eg["convicted"] > 0:
                    named.append("evidence_geo_contradiction")
                if kind == "E" and d.get("unresolvable", 0) > 0 and "unresolvable" not in named:
                    named.append("unresolvable")
                rec["charge"] = "+".join(named) or "(none)"
                charges[rec["charge"]] += 1
                if lab["FACET_CATCHABLE"]:
                    tally["caught_and_facet_catchable"] += 1
            elif missed:
                tally["missed"] += 1
                if pre_removed:
                    # sub-count, reported beside the miss: the carrier sentence left the page under an
                    # EARLIER pass (`_drop_bare_digit_sentences` / `_drop_evidence_value_slot`), so the
                    # injected handle did not reach the reader even though the [N] resolver never saw it.
                    tally["missed_but_carrier_removed_earlier"] += 1
                if lab["FACET_CATCHABLE"]:
                    tally["missed_and_facet_catchable"] += 1
                if lab["FACET_IDENTICAL"]:
                    tally["missed_and_facet_identical"] += 1
                if not on_page:
                    tally["missed_but_off_the_page"] += 1
            else:
                tally["ambiguous"] += 1
                rec["delta"] = d
                rec["bare_digit_delta"] = bd
                rec["evidence_slot_delta"] = es
                rec["evidence_geo_delta"] = eg
                if lab["FACET_CATCHABLE"]:
                    tally["ambiguous_and_facet_catchable"] += 1
                if not on_page:
                    tally["ambiguous_but_off_the_page"] += 1
            if lab["FACET_CATCHABLE"]:
                tally["facet_catchable"] += 1
            if lab["FACET_IDENTICAL"]:
                tally["facet_identical"] += 1
            records.append(rec)
            # innocent-deletion test: sentences lost that did NOT carry the injected handle
            mfield = field_keys(mst, vocab)
            for f2 in ("tldr", "mechanism"):
                extra = len(_GLUE_RX.findall(mst.get(f2) or "")) - len(_GLUE_RX.findall(bst.get(f2) or ""))
                if extra > 0:
                    tally["glued_remnants"] += extra
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
                carrier = carrier_key
                raw = [t for t in lost if t[1] != carrier]           # the EXACT-KEY rule alone
                strays = [t for t in lost if not carrier_remnant(t[1], carrier)]
                tally["innocent_deletions_raw_exact_key_rule"] += len(raw)
                tally["carrier_remnants_excluded"] += len(raw) - len(strays)
                for t in raw:
                    if t not in strays:
                        remnants.append({"run": run, "id": a["id"], "orig": k, "inj": j,
                                         "carrier": carrier, "remnant": t[1]})
                if strays:
                    tally["innocent_deletions"] += len(strays)
                    innocent.append({"run": run, "id": a["id"], "orig": k, "inj": j,
                                     "carrier": carrier, "lost": [t[1] for t in strays]})
    return tally, charges, records, innocent, glued, dict(hyd), remnants


_F0_N_KEYS = ("substituted", "unresolvable", "handles_dropped", "sentences_dropped",
              "slot_scope_mismatch", "direction_sign_mismatch", "grouped_in_slot",
              "binding_refused", "empty_row_addressed", "direction_checked", "scope_checked")
_F0_E_KEYS = ("substituted", "handles_dropped", "sentences_dropped", "unresolvable")


def f0():
    """ARM F0 -- 10.24.3's FIDELITY ANCHOR, recomputed on THIS build and re-shown beside the arms.

    The un-mutated replay over the surviving population, scored against the artifacts' OWN recorded
    censuses. Also carries three M-2 additions, each a statement the bars depend on:
      * V2's BASELINE convictions -- a non-zero here would mean the new pass deletes real prose on
        un-mutated text, which is M-1's bar arriving through M-2's door.
      * the HYDRATION census -- how many `[E]` receipts the sidecar could address.
      * THE GEO-FACET PROBE -- whether `served_rows` carries a `country` anywhere. It is what
        licenses the `f_geo = UNMEASURABLE_OFFLINE` label instead of a fabricated comparison."""
    rep_n, art_n = collections.Counter(), collections.Counter()
    rep_e, art_e = collections.Counter(), collections.Counter()
    per_inv = collections.defaultdict(lambda: [0, 0])
    hyd = collections.Counter()
    exact_rows, exact_rows_bar_scope, n_ans = 0, 0, 0
    v2_baseline = collections.Counter()
    geo_calls, geo_rows, tot_calls, tot_rows = 0, 0, 0, 0
    byte_exact = 0
    for run, a in answers():
        n_ans += 1
        rd = a.get("raw_draft") or {}
        post = (rd.get("postverify_tldr") or "", rd.get("postverify_mechanism") or "")
        calls = H.mk_calls(a.get("served_rows"))
        for sr in (a.get("served_rows") or []):
            tot_calls += 1
            if str(sr.get("country") or "").strip():
                geo_calls += 1
            for r in (sr.get("rows") or []):
                tot_rows += 1
                if isinstance(r, dict) and str(r.get("country") or "").strip():
                    geo_rows += 1
        rows, hst = H.uniq_rows_of(a)
        for hk, hv in hst.items():
            hyd[hk] += hv
        st, tr = run_stack(post, calls, rows)
        rn, an = tr["number_handles"], (a.get("number_handles") or {})
        re_, ae = tr["prose_handles"], (a.get("prose_handles") or {})
        for k in _F0_N_KEYS:
            rep_n[k] += int(rn.get(k) or 0)
            art_n[k] += int(an.get(k) or 0)
        for k in _F0_E_KEYS:
            rep_e[k] += int(re_.get(k) or 0)
            art_e[k] += int(ae.get(k) or 0)
        per_inv[run][0] += int(rn.get("substituted") or 0)
        per_inv[run][1] += int(an.get("substituted") or 0)
        same = all(int(rn.get(k) or 0) == int(an.get(k) or 0) for k in _F0_N_KEYS)
        same_bs = all(int(rn.get(k) or 0) == int(an.get(k) or 0)
                      for k in _F0_N_KEYS if k != "scope_checked")
        exact_rows += int(same)
        exact_rows_bar_scope += int(same_bs)
        for k in ("convicted", "handles_dropped", "sentences_dropped"):
            v2_baseline[k] += int((tr.get("evidence_geo_dropped") or {}).get(k) or 0)
        if (st.get("tldr") or "") == (rd.get("verified_tldr") or "") and \
           (st.get("mechanism") or "") == (rd.get("verified_mechanism") or ""):
            byte_exact += 1
    return {"answers_scored": n_ans,
            "number_handles": {k: {"replay": rep_n[k], "artifact": art_n[k],
                                   "delta": rep_n[k] - art_n[k]} for k in _F0_N_KEYS},
            "prose_handles": {k: {"replay": rep_e[k], "artifact": art_e[k],
                                  "delta": rep_e[k] - art_e[k]} for k in _F0_E_KEYS},
            "substituted_per_invocation": {r: {"replay": v[0], "artifact": v[1]}
                                           for r, v in sorted(per_inv.items())},
            "answers_exact_on_all_number_handles_keys": exact_rows,
            "answers_exact_bar_scope_checked": exact_rows_bar_scope,
            "verified_text_byte_exact": byte_exact,
            "v2_baseline_convictions": dict(v2_baseline),
            "e_receipt_hydration": dict(hyd),
            "geo_facet_probe": {"served_rows_calls": tot_calls, "calls_with_country": geo_calls,
                                "projected_rows": tot_rows, "rows_with_country": geo_rows}}


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
    ap.add_argument("--f0-only", action="store_true",
                    help="run the F0 fidelity anchor and nothing else")
    ap.add_argument("--force", action="store_true",
                    help="allow overwriting an existing --out (default: REFUSE)")
    args = ap.parse_args(argv)

    H.set_paths(root=args.root, corpus_dir=args.corpus_dir)
    out_path = args.out or H.default_out_path()
    # NEVER OVERWRITE A PRIOR ARTIFACT. A gate whose input can be silently replaced by a re-run is a
    # gate that cannot be re-read later, and the run of record at 10.25 lives at the default path.
    if os.path.exists(out_path) and not (args.census_only or args.force):
        print("REFUSING to overwrite an existing artifact: %s" % out_path)
        print("   pass a different --out (or --force, which this gate does not use).")
        return None

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

    out = {"_meta": {"gate": "M-2 (plan 10.30.7) -- the fixture re-run with facet-labeled misses",
                     "scoring": "10.24.5, UNCHANGED; per-arm miss cap LIFTED",
                     "e_receipt_text": "HYDRATED from data/dhp_g1/e_text_sidecar.json "
                                       "(plan 10.30.11(C) residual 1)",
                     "geo_facet": _GEO_OFFLINE}}

    print("== F0 (fidelity anchor, 10.24.3 re-shown) ==")
    z = f0()
    out["F0_fidelity"] = z
    for k, v in z["number_handles"].items():
        print("   number_handles.%-24s replay %-6d artifact %-6d delta %+d"
              % (k, v["replay"], v["artifact"], v["delta"]))
    for k, v in z["prose_handles"].items():
        print("   prose_handles.%-25s replay %-6d artifact %-6d delta %+d"
              % (k, v["replay"], v["artifact"], v["delta"]))
    print("   answers scored %d ; exact on ALL keys %d ; exact bar scope_checked %d"
          % (z["answers_scored"], z["answers_exact_on_all_number_handles_keys"],
             z["answers_exact_bar_scope_checked"]))
    print("   V2 baseline convictions:", z["v2_baseline_convictions"])
    print("   [E] hydration          :", z["e_receipt_hydration"])
    print("   geo facet probe        :", z["geo_facet_probe"])
    sys.stdout.flush()
    if args.f0_only:
        return out

    for name, fn, rx, kind in arms():
        t, ch, recs, inn, gl, hyd, rem = score(name, fn, rx, kind)
        cat = sum(1 for r in recs if r["labels"].get("FACET_CATCHABLE"))
        cat_caught = sum(1 for r in recs
                         if r["labels"].get("FACET_CATCHABLE") and r["verdict"] == "caught")
        out[name] = {"tally": dict(t), "charges": dict(ch),
                     "bar_A": {"facet_catchable": cat, "caught_of_catchable": cat_caught,
                               "rate": (round(cat_caught / cat, 6) if cat else None),
                               "bar": 0.95, "pass": (cat_caught >= 0.95 * cat) if cat else None},
                     "bar_B_innocent_deletions": int(t.get("innocent_deletions", 0)),
                     "bar_B_raw_exact_key_rule": int(t.get("innocent_deletions_raw_exact_key_rule", 0)),
                     "carrier_remnants_excluded": int(t.get("carrier_remnants_excluded", 0)),
                     "carrier_remnants": rem,
                     "facet_identical_residual": {
                         "all_injections": int(t.get("facet_identical", 0)),
                         "misses_only": int(t.get("missed_and_facet_identical", 0))},
                     "e_receipt_hydration": hyd,
                     "n_records": len(recs), "records": recs,
                     "innocent_deletions_all": inn, "glued_all": gl}
        print("== %s ==" % name)
        print("   tally  :", dict(t))
        print("   charges:", dict(ch))
        print("   bar A  : catchable %d ; caught-of-catchable %d ; rate %s"
              % (cat, cat_caught, ("%.4f" % (cat_caught / cat)) if cat else "n/a"))
        print("   bar B  : innocent deletions %d (raw exact-key rule %d ; carrier remnants excluded %d)"
              % (int(t.get("innocent_deletions", 0)),
                 int(t.get("innocent_deletions_raw_exact_key_rule", 0)),
                 int(t.get("carrier_remnants_excluded", 0))))
        print("   residual: facet-identical %d (of which misses %d)"
              % (int(t.get("facet_identical", 0)), int(t.get("missed_and_facet_identical", 0))))
        print("   on-page : off-the-page %d of %d ; non-caught but off the page %d"
              % (int(t.get("off_the_page", 0)), int(t.get("injected", 0)),
                 int(t.get("missed_but_off_the_page", 0))
                 + int(t.get("ambiguous_but_off_the_page", 0))))
        sys.stdout.flush()
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    print("wrote %s" % out_path)
    return out


if __name__ == "__main__":
    main()
