"""Deterministic citation verifier (GRAPHRAG_PLAN section 6 step 6, built at last).

The judge kept catching the same defect class: the reasoner attaches a citation handle to a claim its
source never made (the enso answer pinned a tariff narrative on a Mexico-meal prop). A judge costs
money and runs after the fact; these checks are free, deterministic, and run before the reader sees
the answer. Zero LLM calls.

ANCHORING: the prompt's evidence blocks are UNNUMBERED — the model assigns its own [n] handles and
declares the mapping in the structured `sources` ledger ({ref, source, date}). So verification anchors
through that ledger: an entry must resolve to a REAL provided evidence item (same source + compatible
date) or it is a fabricated citation; a prose sentence must share content with the item its handle
resolves to. Numbers handles [Nn] ARE positional (the numbers block renders N1.. in call order), so
they get exact value checks.

Policy: a violation NEVER triggers a paid retry — the handle is STRIPPED (an uncited model claim is
more honest than a fabricated attribution) and counted in the report the trace carries; ledger dates
that merely mistype a real item are corrected in place. ONE exception, and it is why the handle-only
strip is not universal: a fabricated NUMBER survives the loss of its handle, so number_mismatch is
fail-closed -- THE WHOLE SENTENCE GOES.

══ CYCLE-10 (2026-08-08) -- THIS MODULE NO LONGER REWRITES PROSE. THE TERMINATION BRANCH, EXECUTED ══════
The fail-closed remedy used to have two arms: rewrite the figure from the cited row when that was
"unambiguous", else delete the sentence. The rewrite arm is DELETED. It is not re-fenced, not narrowed
and not flag-gated -- the code that could write a numeral into a sentence is gone, and every case that
used to repair now takes the drop.

THE RECORD THAT DECIDED IT: three corrupt rewrites out of three recorded ops across gates 6-7.
    gate-6  "rising toward the 1.5 degC threshold [N1]"   ->  "toward the 0 degC threshold"
    gate-6  "The ONI anomaly is at 0.98 degC [N5,N10,N12]" ->  "is at 1 degC"   (a 0/1 flag row)
    gate-7  "roughly 0.6 z higher [N3]"                    ->  "roughly -0.6267 z higher [N3]"
The gate-7 op is why no further fence was admissible. It passed ALL FOUR clauses of the cycle-9
allowlist on inspection -- one solitary [N] handle, both unit classes known and EQUAL (z into z), no
threshold noun or conditional lead, inside one order of magnitude with no contradicted sign -- and still
corrupted a CORRECT sentence: the slot's own word "higher" already carried the direction while the cited
row was a signed delta metric (`*_pace_change`), so the "equal unit class" the fence compared was a unit
LABEL agreement over two different quantities. A fence that compares labels cannot see semantics, and
every widening of it has produced the next corruption. The allowlist is not repairable by adding a fifth
clause; the capability is.

WHAT SURVIVES, UNCHANGED: the CHARGE (what is flagged number_mismatch), the counters and `by_rule`, the
audit record, the sibling-backed rescue (r5), and the two prior sanctioned amendments -- reader-precision
matching (cycle-6), the ordinal/duration extraction exemptions (cycle-8) and grouped-handle parsing
(cycle-9). `report["repaired"]` / `report["repairs"]` remain as schema-stable fields that are now always
0 / [] on a new run, so every consumer (eval.verifier_panel, orchestrator, the gate artifacts) keeps
working and gate-to-gate comparability is preserved.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import unicodedata

# The optional trailing letter consumes model-minted variants like [E1b]: unmatched they LEAK to the
# reader as literal text (Stage-1 RCA q7); matched they resolve by idx and strip like any other handle.
#
# ══ CYCLE-9 (2026-08-08) -- THE THIRD SANCTIONED AMENDMENT, PART (3a): GROUPED / RANGED HANDLES ══════
# SCOPE, AS RATIFIED: BACKING VISIBILITY ONLY, AND IT IS STRICTLY ERROR-REDUCING. The renderer emits
# GROUPED citations -- `[N5, N10, N12]`, `[N1-N4]`, `[E2, E5]` -- and the solitary shape above could not
# match one, so every row cited that way was INVISIBLE to this module: invisible to `_sibling_backed`,
# to the `_kinds` prose-kind map, to the evidence backing pools, and to `answer._orphan_has_content`.
#
# THE MEASURED CORRUPTION (gate-6 `ab_amb_elnino`, covenant pass 2, reproduced from the recorded draft).
#     draft  "The ONI anomaly is at 0.98 degC and has risen for five consecutive months [N5, N10, N12],
#             putting the ENSO signal firmly in El Nino territory [N2]"
#     page   "... is at 1 degC ..."
# [N5] IS the 0.98 degC ONI row -- it materializes the figure -- but the group was unmatched, so the only
# handle this module could see was [N2] (el_nino_flag = 1). `_sibling_backed` iterated the sentence's
# handles, found no backer, and the sentence was handed to the repair path as single-handle-mismatched.
# The charge itself was the artifact: with the group parsed, [N5] backs 0.98 and the correct remedy is
# the r5 one -- strip the mis-citing handle, leave the corroborated figure standing.
#
# WHAT THIS AMENDMENT DOES *NOT* DO, deliberately: a grouped token is NEVER newly CHARGEABLE. It is not
# counted in `checked`, it never adds a strip, it never adds a drop span. It contributes BACKING and
# nothing else -- which is why the change can only ever convert a false charge into no charge. Making
# grouped members chargeable is a separate, non-error-reducing decision and is not taken here.
#
# A CONTINUATION MEMBER IS BARE ONLY BEHIND A PREFIXED LEAD -- CYCLE-9 REVIEW (2026-08-08), MEDIUM 8.
# The first cut of this pattern required the `N`/`E` prefix on EVERY member, because without SOME such
# requirement the widened pattern swallows an ordinary bracketed YEAR RANGE (`[1980-1990]`) and silently
# removes two magnitudes from claim extraction -- a verification LOSS inside an amendment sanctioned as
# loss-free. The prefix-on-every-member rule bought that safety with a DISAGREEMENT: `answer._N_HANDLE_RX`
# reads `N?\d+` continuations, so the renderer's own `[N5, 10, 12]` spelling was a handle to the renderer
# and ordinary prose here. "Verify sees fewer groups" is not free, and the review measured the price: on
# the bare-continuation spelling `_sibling_backed` cannot see the backing member, the r5 rescue cannot
# fire, and the sentence is DROPPED WHOLE where the prefixed spelling of the same sentence keeps its
# figure. It escaped corruption only because the unmasked continuation digits inflated the claim-span
# count past the ambiguity fence -- correct by accident, not by design.
# THE CONDITION IS THE FIX: the LEADING member must carry the prefix, and only then may continuations go
# bare. `[N5, 10, 12]` is a handle (the lead says so); `[1980-1990]` and `[5900-9999]` are not, because
# their lead is bare and a bare lead still demands prefixed continuations. The two readers now agree on
# every form either can produce, and the year-range hazard stays closed. `(?(kind)...)` is a re
# CONDITIONAL on group participation, so `kind` is now an OPTIONAL GROUP (None when absent, where it used
# to be ""); the one reader of it compares against "N" and is unaffected.
# ASCII SOURCE: the dash variants are built from CODEPOINTS, the discipline `_QUOTE_EDGE` states.
_H_DASHES = "-" + "".join(chr(c) for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212))
_H_SEP = r"(?:,|;|&|/|and|[" + _H_DASHES + r"])"
_H_MEMBER = r"[NE]\d+[a-z]?"                      # continuation behind a BARE lead: prefix required
_H_MEMBER_ANY = r"[NE]?\d+[a-z]?"                 # continuation behind a PREFIXED lead: prefix optional
_HANDLE = re.compile(r"\[(?P<kind>[NE])?(?P<idx>\d+)(?:[a-z])?"
                     r"(?P<more>(?:\s*" + _H_SEP + r"\s*"
                     r"(?(kind)" + _H_MEMBER_ANY + r"|" + _H_MEMBER + r"))*)\]")
_H_MEMBER_RX = re.compile(r"([NE]?)(\d+)[a-z]?")
# A RANGE is exactly two indices joined by a dash -- `[N1-N4]` cites four handles, `[N13, N14]` two. The
# expansion is capped and never inverted (`answer._N_RANGE_MAX`, restated -- answer does not import this).
_H_RANGE_RX = re.compile(r"\A([NE])(\d+)[a-z]?\s*[" + _H_DASHES + r"]\s*[NE]?(\d+)[a-z]?\Z")
_H_RANGE_MAX = 24


def _handle_members(token: str) -> list[tuple[str, int]]:
    """The (kind, index) pairs one handle TOKEN cites, in written order, de-duplicated. A solitary `[N5]`
    returns `[("N", 5)]` and a bare `[3]` returns `[("E", 3)]` -- the pre-CYCLE-9 reading, byte for byte
    (an absent kind has always meant the evidence namespace; see `_kinds` in `verify_citations`). A member
    that omits its own kind inherits the token's LEADING kind, which is the only reading a group admits."""
    inner = (token or "")[1:-1].strip()
    rng = _H_RANGE_RX.match(inner)
    if rng:
        lo, hi = int(rng.group(2)), int(rng.group(3))
        if 0 < lo < hi <= lo + _H_RANGE_MAX:
            return [(rng.group(1), i) for i in range(lo, hi + 1)]
    out: list[tuple[str, int]] = []
    lead = ""
    for k, d in _H_MEMBER_RX.findall(inner):
        lead = lead or k
        pair = (k or lead or "E", int(d))
        if pair not in out:
            out.append(pair)
    return out


# ══ 09-23 FIX ROUND (lane V, BRIEF item 7) -- A BRACKET THAT OPENS AS A HANDLE AND CONTINUES AS PROSE ══
# THE MEASURED ESCAPE (09-23 re-smoke, quick corn/wheat): the writer put its gloss INSIDE the bracket --
#     "corn's harvested area reads 35.82 M ha [N42, the 98th percentile of its own record]"
# `_HANDLE` requires every member after the lead to be a handle member, so the whole bracket matched
# nothing: 35.82 and 98 were checked against nothing, [N42] never reached the footer, and
# `bare_handle_escapes` did not count it (0 on that turn).
# THE RULE IS THE HANDLE GRAMMAR ITSELF, NOT A PATTERN FOR THE GLOSS. The bracket's HEAD is read with
# `_HANDLE`'s own member grammar (a prefixed lead, then `_H_SEP` + `_H_MEMBER_ANY` continuations, each
# member ending at a non-word character so "98th" can never be half-read as the member "98t"); the split
# fires only when (i) the head is a prefixed `[N`/`[E` lead, (ii) the head is followed by the LIST
# punctuation a gloss is written with (",", ";", ":"), (iii) what follows is NOT itself a continuation
# `_HANDLE` accepts (the whole bracket fails `_HANDLE.fullmatch`), and (iv) that remainder carries a letter
# -- so `[N5, 10, 12]`, `[N1-N4]`, `[E2, E5]` and a bracketed year range `[1980-1990]` (bare lead) are
# untouched by construction. (ii) is MEASURED on unseen banked prose: a writer's NOTE about a handle --
# "[E31 is area only; the trade and credit items sit in ...]", "[N27 is seed -- see record]" -- names the
# handle to DISCLAIM it, and splitting it would turn the disclaimer into a live citation of the very row
# the writer said does not back the claim (the 112-answer replay found both; neither is split now). The remainder keeps its own separator and words verbatim:
#     "[N42, the 98th percentile of its own record]" -> "[N42], the 98th percentile of its own record"
# Nothing is deleted and no character is written but the moved bracket.
_CANON_MEMBER = r"[NE]?\d+[a-z]?(?![\w.])"
_MALFORMED_HANDLE = re.compile(
    r"\[(?P<head>[NE]\d+[a-z]?(?![\w.])(?:\s*" + _H_SEP + r"\s*" + _CANON_MEMBER + r")*)"
    r"(?P<tail>\s*[,;:][^\[\]\n]*?)\]")


def _canonicalise_handles(text: str) -> tuple[str, int]:
    """(text with every malformed handle bracket split to its canonical handle + its own words, count)."""
    n = 0

    def _fix(m):
        nonlocal n
        tok = m.group(0)
        tail = m.group("tail")
        if _HANDLE.fullmatch(tok) or not re.search(r"[A-Za-z]", tail):
            return tok
        n += 1
        return "[" + m.group("head") + "]" + tail

    out = _MALFORMED_HANDLE.sub(_fix, str(text or ""))
    return out, n
# CYCLE-5 TIDY-1: how much of the text FOLLOWING a strip is read to build the seam key. Long enough that a
# renderer-side prefix match is unambiguous against ordinary prose, short enough that nothing grows a
# second copy of the answer.
_SEAM_LOOKAHEAD = 120
# FIX-CYCLE-2 (2026-08-07), review major 7. TIDY-1 originally put `{"field", "after"}` -- up to 120 chars of
# RAW, PRE-SANITIZE prose per strip -- on the returned report, UNCONDITIONALLY. That report is stamped onto
# `trace["citation_verifier"]` and `/v1/respond` returns `result` whole, so the register-leak / valuation
# text `reg.sanitize` exists to remove reached the browser through the verifier's own audit key. The file's
# established precedent for a raw-text carrier is an ENV GATE (`strip_audit` above, `raw_draft` likewise).
# TWO CHANGES, and both are needed:
#   * the SERIALIZED form is gated on GRAPHRAG_STRIP_AUDIT, exactly like `strip_audit`; and
#   * what it PUBLISHES is a NORMALIZED KEY CUT TO 40 CHARACTERS (whitespace-collapsed, case-folded), not
#     the prose. The renderer join was always a normalized-prefix compare capped at 32 chars, so 40
#     characters is everything the join can use and nothing it cannot.
# The tidy pass must still work in PRODUCTION with the gate off, so the seams also ride an INTERNAL,
# NON-SERIALIZED carrier: `_VerifyReport.strip_seams`, an attribute on the returned dict subclass. It is
# invisible to json.dumps, to `dict(...)`, to every projection and whitelist -- so no client, artifact or
# durable record can ever see it -- while `answer._tidy_strip_orphans`, which is handed the report OBJECT
# two lines after `verify_citations` returns, reads it directly.
#
# H1 FOLD ROUND 5 (2026-08-13) -- FIX W-A/W-B: THE 40 IS THE *PROJECTION'S* BOUND, SO IT IS APPLIED AT THE
# PROJECTION. Round 4 cut the key inside `_seam_key`, i.e. AT THE MINT, which put one number in front of
# two different questions and answered both of them wrong:
#   * TOO NARROW FOR THE LICENCE -- a measured false NEGATIVE, and the fold's own root cause reached by a
#     third route. The consumer canonicalizes both sides (`answer._licence_canon`) and then compares 32
#     NORMALIZED characters. Canon DELETES characters, so a key cut at 40 RAW characters can carry fewer
#     than 32 canonical ones, and its last character is then a truncation artefact -- most often the lone
#     "-" left when a "--" run is split at char 40, which `-{2,}` cannot erase. The compare diverges at
#     that boundary and a cut a producer really made goes unlicensed. DRIVEN END TO END on
#     "The December contract were ( [E9] ) --.  The December contract sits at -- [E4] --." (recorded key
#     ") --. the december contract sits at -- -", canon 33 chars, against a 32-char tail canon, differing
#     at index 31 -- 0 sentences dropped and the reader got the fragment) and on
#     "Brazilian output were [E8],.  Exports hit -- [E8] --.  Exports reads -- [N6] --.". Reach measured
#     by the round-4 verifier: 95 of 122,470 synthetic house-shaped fragments (0.078%), and ZERO on the
#     estate's own stored prose -- small, which is why it is a minor, but it is the SAME staleness class
#     Y1 and Y2 closed.
#   * AND IT NEVER BOUND WHAT ACTUALLY NEEDED BOUNDING. `answer._seam_key` has no cut, so once
#     `answer._mint_strip_seam` began MIRRORING this projection (round-4 FIX Y5), the audit published
#     render-side keys at the full `_SEAM_LOOKAHEAD` width -- measured at 119 characters per seam on
#     `data/dmw_p4/tier_20260812T051533Z.json`'s mechanism, three times the class this very note bounds,
#     on the browser-visible channel, under a flag the repo's config-of-record says is live in serving.
# SO, AND THE SPLIT IS THE WHOLE FIX: the MINT keeps the full `_SEAM_LOOKAHEAD` width on the in-memory
# carrier, which no serializer can see and which only the licence and TIDY-2 read; `_projected_seam` cuts
# a COPY to `_SEAM_KEY_CHARS` for the projection, for EVERY producer (`answer._mint_strip_seam` calls the
# same helper). Do not re-unify them: the two sides answer opposite questions.
_SEAM_KEY_CHARS = 40


def _seam_key(s: str) -> str:
    """The normalized comparison form of a seam's successor text, at the FULL width the caller hands in
    (every mint site bounds its input at `_SEAM_LOOKAHEAD`). `answer._seam_key` is the same normalization
    on the renderer side (whitespace-collapsed, case-folded) -- applying it here is what makes the join
    possible without shipping prose, and re-applying it there is idempotent.

    DELIBERATELY NOT LENGTH-BOUNDED (H1 FOLD ROUND 5). The 40-character `_SEAM_KEY_CHARS` class belongs to
    the browser-visible PROJECTION and is applied there, by `_projected_seam`. A `[:_SEAM_KEY_CHARS]` on
    this line puts the bound inside the LICENCE path, where the consumer's canon deletes characters before
    comparing 32 of them -- read the note above for the two driven reproductions, and do not restore it."""
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _projected_seam(seam: dict) -> dict:
    """The GRAPHRAG_STRIP_AUDIT copy of one seam: a COPY of the record whose `key` is cut to
    `_SEAM_KEY_CHARS`. Both producers project through here.

    THAT IT IS A COPY IS THE POINT. The in-memory carrier must keep the full-width key (the licence
    compare needs it), and the projection must not have it (it is up-to-120-character PRE-SANITIZE prose
    on `trace["citation_verifier"]`, which `/v1/respond` returns whole). Appending the SAME dict object to
    both -- which is what round 4 did on both producers -- collapses those two requirements into one and
    the wider one wins. The bound is a property of the projection SITE, not of any caller's key."""
    out = dict(seam or {})
    out["key"] = str(out.get("key") or "")[:_SEAM_KEY_CHARS]
    return out


# H1 FOLD ROUND 4 (2026-08-13) -- FIX Y1, THE TWO CLEANUPS THIS FILE APPLIES TO ITS OWN OUTPUT, NAMED.
# `_verify_field` used to spell these inline on its `return`, ten lines AFTER it minted its seam keys off
# the pre-cleanup text -- so every key it recorded described a string the renderer would never see. See the
# seam loop at the end of `_verify_field` for the reproduction and for why the fix is window-local.
def _strip_cleanup(text: str) -> str:
    """The whitespace repair a positional strip needs: collapse runs of spaces, then close the space a
    removed span left in front of `.`/`,`/`;`. Order matters ("  ." -> " ." -> ".").

    IDEMPOTENT and PURELY SUBTRACTIVE ON WHITESPACE: it never inserts, never crosses a newline (`" "`,
    not `\\s`), and never touches a character that is not a space. That is what makes it safe to apply to
    a WINDOW of the text as well as to the whole of it (FIX Y1)."""
    return re.sub(r" +([.,;])", r"\1", re.sub(r"  +", " ", str(text or "")))


class _VerifyReport(dict):
    """The verifier report: a plain dict to every consumer, plus ONE attribute (`strip_seams`) that no
    serializer, projection or whitelist can see. See the seam note above for why the carrier must be
    off-dict rather than a gated key."""

    __slots__ = ("strip_seams",)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.strip_seams: list[dict] = []
# CYCLE-10 (2026-08-08): the UNIT-CLASS tables, the scale-word fence and the streak COUNT tell lived here
# to guard a REWRITE -- "a repair may only splice a value whose unit belongs to the same class as the
# numeral it replaces". With the rewrite deleted they guard nothing, so they are gone rather than left
# loaded. Nothing in the charging or minting path ever read them: `citations` carries its own
# `_UNIT_CLASSES` for the footer/completion lane and does not import this module.
_QUOTE = re.compile(r"[\"“”]([^\"“”]{15,})[\"“”]")
# D-DV-0(2) forensics (2026-08-06): the punctuation American style puts INSIDE the closing quote mark is
# captured by _QUOTE as part of the SPAN -- '"Widespread crop disease," the report said' quotes a comma the
# source never wrote. 3 of deep's 6 quote_mismatch strips were spans that match their cited row verbatim
# once that comma is off. Stripped from BOTH sides of the comparison (span AND row text) so the match stays
# substantive: interior punctuation, wording and the existing case-folding are untouched.
# Curly marks as escapes so this addition stays ASCII source (the same rule as _RANGE_TAIL's dashes).
_QUOTE_EDGE = ",.;:!?" + chr(34) + chr(39) + " " + "\u201c\u201d\u2018\u2019"
_NUM = re.compile(r"\d[\d,]*\.?\d*")
_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+")
_STOP = {"about", "after", "against", "along", "among", "around", "because", "before", "being",
         "between", "could", "during", "their", "there", "these", "those", "through", "under",
         "which", "while", "would", "should", "since", "where", "whose", "market", "markets",
         "price", "prices", "driver", "drivers", "commodity", "evidence", "documented", "report",
         "reported", "reports"}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{5,}", (s or "").lower()) if t not in _STOP}


def _non_latin(s: str) -> bool:
    """True when the string carries letters outside the Latin repertoire (Arabic, CJK, Cyrillic, ...).
    Latin-Extended accents (Cote d'Ivoire, Sao Paulo) stay False -- the gate is for scripts where a
    shared [a-z]{5,} token with English evidence is impossible BY CONSTRUCTION, never a looser bar for
    accented European text. 0x024F is the end of Latin Extended-B."""
    return any(ch.isalpha() and ord(ch) > 0x024F for ch in s or "")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _norm_quote(s: str) -> str:
    """_norm plus the EDGE punctuation strip a quoted span needs (see _QUOTE_EDGE). Applied to the span
    AND to the row text it is searched in, so the containment test is the same test on both sides -- this
    is punctuation normalization, never fuzzy matching: nothing inside the span is touched."""
    return _norm(s).strip(_QUOTE_EDGE)


def _same_source_items(entry: dict, evidence: list[dict]) -> list[dict]:
    """Every provided item whose source matches the entry's (substring either way), date ignored."""
    src = _norm(str(entry.get("source") or "")).replace(" ", "_")
    if not src:
        return []
    out = []
    for e in evidence or []:
        es = _norm(str(e.get("source") or "")).replace(" ", "_")
        if es and (src in es or es in src):
            out.append(e)
    return out


def _match_ledger_entry(entry: dict, evidence: list[dict]) -> list[dict]:
    """Provided evidence items compatible with a ledger entry: source must match (substring either
    way — the model shortens 'usda_gain_soybean_oil' to 'USDA GAIN'); date must equal when both given.

    09-23 FIX ROUND (lane V, BRIEF item 8, THREAT_MODEL V-11) -- THE DATE-MISMATCH RETRY CORRECTS ONLY
    WHEN THE SOURCE NAMES ONE DOCUMENT. MEASURED on the rice turn: the writer declared [E41] as a
    December-2025 USDA WASDE the turn did not hold; the retry matched on the source alone, took the FIRST
    of several WASDE items and re-dated the entry to it, so the footer bound "USDA raised 2025/26 global
    beginning stocks ... reported 9 December 2025" to a September-2023 WASDE about a parboiled export tax.
    "A mistyped date becomes a CORRECTION" is true only when the source leaves exactly ONE candidate; with
    several, choosing one is a guess, and a guessed provenance is worse than none. So: one same-source
    item -> the correction, exactly as before; several -> no match here, and the ledger loop records the
    entry as `ledger_ambiguous` (counted, handle kept, NEVER re-dated) rather than as a fabrication."""
    src = _norm(str(entry.get("source") or "")).replace(" ", "_")
    when = str(entry.get("date") or "")[:10]
    out = []
    for e in evidence:
        es = _norm(str(e.get("source") or "")).replace(" ", "_")
        if not es or not src or (src not in es and es not in src):
            continue
        if when and e.get("date") and when != str(e.get("date"))[:10]:
            continue
        out.append(e)
    if not out and src:                                   # date was the lie; retry on source alone so a
        same = _same_source_items(entry, evidence)        # mistyped date becomes a CORRECTION, not a strip
        if len(_ledger_documents(same)) == 1:             # ...but ONLY when the source names ONE document
            out = same
    return out


def _ledger_documents(items: list[dict]) -> set:
    """The distinct DOCUMENTS a list of evidence items is: (source, date). Two chunks of one release are
    one document, so they never make a retry ambiguous."""
    return {(_norm(str(e.get("source") or "")), str(e.get("date") or "")[:10]) for e in items or []}


def _numbers_in(s: str) -> list[float]:
    out = []
    for m in _NUM.findall(s or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


# The CLAIM extractor: digit runs a data row could plausibly back. It drops time/name tokens that the
# raw _NUM sweeps up but that are NOT magnitudes, so the strip DECISION and the strip_audit numbers list
# agree (W3 F1 RCA: legit citations stripped for a bare year, a range tail, or a letter-glued code).
# The leading lookbehind rejects a digit glued to a letter OR to another already-rejected digit -- so a
# code like B40/T2/MY2021/CO2 is skipped whole, never re-entered one digit in. Citation-handle digits
# ([N3], [E1b]) are still removed UPSTREAM by the caller's _HANDLE.sub -- this is additional, not a
# replacement for that exclusion.
_CLAIM_NUM = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*\.?\d*")
# A YEAR-range separator immediately before a SHORT token: 1998-99, 1998/99, en-dash, em-dash -> the
# tail '99'. Prefix is year-scoped (19xx/20xx) and the tail capped at 1-2 digits by the caller (guards
# a former bug: the unscoped \d{4} form exempted the upper bound of ANY hyphenated range -- 'ranged
# 5900-9999 MT' let a fabricated 9999 ride uncited). Dashes as \u escapes to keep this source ASCII.
_RANGE_TAIL = re.compile(r"(?:19|20)\d{2}[-/" + "\u2013\u2014" + r"]\Z")
# A magnitude unit immediately after a 4-digit token flips it from year to CLAIM ('exports hit 1950
# MMT' is a tonnage wearing a year costume -- the unit is the tell).
_UNIT_AFTER = re.compile(r"\s*(?:MMT|MT|KT|kt|MMbu|bu|%|percent|ha|bales|cwt|tonnes|tons)\b")
# T2b Lane-B RCA (2026-07-28): the DAY component of a date is not a magnitude. _RANGE_TAIL only exempts
# the FIRST short tail after a year, so an ISO date shed its day ('2026-05-30' -> 30) and a long-form
# date shed its day too ('as of 25 July 2026' -> 25) -- and the all-numbers guard then killed the whole
# sentence as number_unbacked. Measured on the T2b deck: 25.0 was the offending magnitude in 4 of the
# 10 audited strips, from the deck's own as-of phrasing. The numbers-lane verifier
# (orchestrator._verify_numbers_answer) already scrubs exactly these tokens before extraction; this is
# the same rule, applied where the citation verifier extracts.
_MONTHS = (r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
           r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?")
_DATE_DAY_TAIL = re.compile(r"(?:19|20)\d{2}[-/]\d{1,2}[-/]\Z")           # '2026-05-' before the day
_MONTH_AFTER = re.compile(r"\s+(?:" + _MONTHS + r")\b", re.I)             # '25 July 2026'
_MONTH_BEFORE = re.compile(r"\b(?:" + _MONTHS + r")\s+\Z", re.I)          # 'July 25, 2026'

# -- CYCLE-8 (2026-08-08) -- THE SECOND SANCTIONED AMENDMENT TO THE STRIP RULES ----------------------
# SCOPE, AS RATIFIED: FALSE-POSITIVE REDUCTION IN CLAIM EXTRACTION ONLY. Two shapes stop being claim
# magnitudes -- an ORDINAL suffix and a digit-form DURATION MODIFIER -- and nothing else in this module's
# rules moves. Cycle-6's reader-precision arm is frozen exactly as shipped.
#
# THE MEASURED DEFECT (gate-5, reproduced end-to-end from the artifact drafts through the SHIPPED code).
# "5" in "below the 5-year mean [N9]" was extracted as a CLAIM magnitude, charged number_mismatch against
# [N9]'s pool, and -- because it was the sentence's ONLY claim numeral and the pool held exactly one value
# -- handed to `_num_repair`, which OVERWROTE IT WITH THE ROW VALUE. Three answers shipped the result:
#     dcw_us_ethanol_margin     "below the 5-year mean [N9]"   -> "below the 0.344931-year mean [N9]"
#     dcw_gas_nitrogen_squeeze  "above its 5-year mean"        -> "above its 453.1-year mean"
#     dcw_palm_stocks_print     "roughly 2 percent below ..."  -> "roughly 1,629,801 percent below ..."
# The first two are THIS amendment's class; the third is a percent slot and is fixed at the repair fence
# (see `_num_repair`), NOT here -- "2 percent below the average" is a real quantitative claim about
# magnitude and must keep stripping when it is wrong.
# THE COLLATERAL, MEASURED (strip_audit rows whose sentence carries a digit-form duration AND whose audited
# claim numbers include that digit): gate-4 = 4 (3 dcw, 1 dpq), gate-5 = 31, ALL 31 in dcw_probe. The
# covenant deck carries ZERO -- its 42 strips are 22 number_mismatch + 10 number_unbacked + 10
# no_lexical_overlap with no duration sentence among them -- so the covenant band miss (42 vs 25.6..38.4)
# is NOT this class and cycle-8 does not move it. Replayed strips: gate-5 404 -> 378, gate-4 799 -> 796.
#
# THE RULE IS "MODIFIER", NOT "DURATION WORD", and that distinction is load-bearing in BOTH directions:
#   * "5-year mean", "90-day change", "12-week moving average", "36-month window" -- the numeral names the
#     LENGTH OF A REFERENCE WINDOW for a statistic that is stated elsewhere in the sentence. No served row
#     can ever equal it except by coincidence, so charging it is a false positive by construction.
#   * "risen in each of the last 5 months [N11]" -- the duration noun is the HEAD, the numeral IS the
#     quantity the cited pace_streak row carries, and it stays a claim. Losing that would un-verify the
#     streak lane, which is the one place a duration numeral is genuinely checkable.
# The test for "modifier" is orthographic and deterministic: a duration noun immediately after the digits
# (hyphen or space, singular or plural) that is ITSELF followed by another WORD. Punctuation, a citation
# handle, or the end of the clause after the duration noun = head position = still a claim.
# HONEST COST, RECORDED: "a 5-month consecutive rise [N10]" reads as a modifier under this test and stops
# being charged. That is a real (narrow) verification loss on the streak lane's adjectival phrasing; the
# head-noun phrasing above keeps it, and `_num_repair`'s COUNT fence already refused to repair that shape.
#
# CYCLE-8 REVIEW (2026-08-08), BLOCKER 2 -- "FOLLOWED BY ANOTHER WORD" IS NOT THE MODIFIER TEST. The rule
# above is right; its first spelling was not. "a duration noun followed by any word" exempts every
# PREPOSITIONAL continuation, which is exactly the head-position shape the note swears it preserves. The
# builder's own head-position pin survived only because a '[' followed the noun. MEASURED LOSSES on the
# shipped spelling -- every one of these returned [] where the numeral IS the claim:
#     "prices have risen for 5 months in a row [N10]"        the pace_streak lane
#     "ending stocks cover 21 days of use [N6]"              a days-of-use quantity
#     "US corn is 12 days ahead of the pace [N4]"            a pace gap
#     "the crush ran 3 weeks behind schedule [N5]"
#     "exports rose in each of the last 5 months of the marketing year [N1]"
# and in the REAL corpus, gate-4 + gate-5 `dcw_positioning_beans` de-charged "10 days before the as-of date"
# and "within 6 days prior to the 2026-08-07 as-of" -- the D-RC-13 recency-honesty lane, where a fabricated
# staleness gap would have shipped unchecked.
# THE TEST IS NOW ORTHOGRAPHIC ON BOTH AXES, and it is deliberately ASYMMETRIC between the two separators:
#   * HYPHEN ('5-year mean', '90-day change', '12-week moving average') -- the compound-modifier
#     orthography IS the writer declaring the numeral is a window length. Any following word will do.
#   * SPACE ('5 year mean') -- no orthographic declaration at all, so the exemption must be EARNED by the
#     following head being a STATISTIC noun (`_STAT_HEAD`). "5 months in a row" and "21 days of use" are
#     the same shape and must stay claims.
# and BOTH forms additionally refuse the exemption when the very next token is a PREPOSITION/ADVERB
# (`_DUR_STOP`): "of / in / before / after / ahead / behind / prior ..." never introduce a statistic, they
# continue a head-position quantity. Punctuation, a citation handle, or the end of the clause after the
# duration noun is still head position and still a claim.
_DURATION_NOUN = r"(?:year|yr|month|week|wk|day|quarter|qtr|season)s?"
# The separator set is hyphen / non-breaking hyphen / plain space only -- an en-dash between a digit and a
# word is a RANGE, not a compound modifier, and `_RANGE_TAIL` already owns that reading. The two exotic
# hyphens are built with chr() to keep this source ASCII (the same rule `_RANGE_TAIL` states).
_DUR_HYPH = "[-" + chr(0x2010) + chr(0x2011) + "]"
_DUR_SEP = "[-" + chr(0x2010) + chr(0x2011) + r" ]"
# The words that may never be read as a statistic head: they continue a quantity, they do not name a window.
_DUR_STOP = (r"(?:of|in|on|to|into|from|since|before|after|ahead|behind|prior|out|up|down|back|away|"
             r"apart|running|straight|consecutively|now|ago|earlier|later|old|worth|left|remaining)")
# The heads that DO name a statistic computed over a window. Only these earn the exemption on the SPACE
# spelling; the hyphen spelling is its own declaration and takes any head that is not a `_DUR_STOP`.
_STAT_HEAD = (r"(?:mean|average|avg|median|mode|window|lookback|trailing|horizon|lag|history|historical|"
              r"moving|rolling|change|chg|delta|high|low|max|min|range|band|percentile|quantile|"
              r"z|zscore|z-score|sigma|stdev|std|deviation|vol|volatility|sma|ema|ma|basis|norm|normal|"
              r"seasonal|seasonality|comparison|comparable|span|period|windowed)")
_DURATION_MOD = re.compile(
    r"\A(?:" + _DUR_HYPH + _DURATION_NOUN + _DUR_SEP + r"+(?!" + _DUR_STOP + r"\b)[A-Za-z]"
    + r"|[ ]" + _DURATION_NOUN + r"[ ]+(?!" + _DUR_STOP + r"\b)" + _STAT_HEAD + r"\b)", re.I)
# A bare ordinal suffix glued to the digits: '3rd consecutive month', '1st of the month', '2nd half'. An
# ordinal is a POSITION in a sequence, not a magnitude. `\b` after the suffix keeps '5 thousand' a claim
# (the 'th' of 'thousand' is not a token boundary) and the no-space \A keeps '85 th' a claim.
# THE PERCENTILE FAMILY IS EXCLUDED FROM THE EXEMPTION, and that exclusion is MEASURED, not defensive:
# this estate serves percentile_rank metrics, so "at the 76.8th percentile [N3]" states the CITED ROW'S OWN
# VALUE -- an ordinal in spelling and a magnitude in fact. Exempting it cost 3 legitimately-cited handles
# across the gate-4/gate-5 replay (gate-4 `ab_rec_malaysia_stocks` x2, gate-5 `dcw_urea_zscore` x1): the
# numeral stopped backing its handle, the sentence flipped to number_mismatch, and the handle was stripped.
# CYCLE-8 REVIEW (2026-08-08), BLOCKER 3: the carve-out let only WHITESPACE separate the suffix from the
# percentile word, so the HYPHENATED spelling defeated it -- and the counter-example was already inside the
# measured corpus. Gate-5 `dcw_urea_zscore` writes, verbatim, "The 65.9th-percentile rank [N4] on the longer
# distribution", and the shipped spelling de-charged it: the one non-duration numeral in the reviewer's
# 93-numeral sweep, and precisely the class this carve-out exists to protect. An OPTIONAL hyphen (plain /
# U+2010 / U+2011, chr()-built to keep the source ASCII) now sits inside the lookahead, and `pctl` joins the
# spelling list.
_PCTILE_WORD = r"(?:percentile|pctile|pctl|quantile|quartile|decile)"
_ORDINAL_AFTER = re.compile(
    r"\A(?:st|nd|rd|th)\b(?!\s*" + _DUR_HYPH + r"?\s*" + _PCTILE_WORD + r")", re.I)

# -- D-EC PRE-ARM (2026-09-17) -- THE FOURTH SANCTIONED AMENDMENT TO CLAIM EXTRACTION ----------------
# SCOPE, AS RATIFIED: FALSE-POSITIVE REDUCTION IN CLAIM EXTRACTION ONLY, exactly the cycle-8 and D-DA
# scope. ONE shape stops being a claim magnitude -- the LENGTH OF THE OBSERVATION WINDOW a statistic is
# read against -- and nothing else in this module's rules moves. Cycle-6's reader-precision arm, cycle-8's
# ordinal/duration arm and D-DA's unit-scale arm are frozen exactly as shipped.
#
# THE MEASURED DEFECT (the in-VPC pre-arm smoke, 2026-09-16, five real-seat turns at commit 17fed3e4;
# `prearm_smoke_0916/answers/*.trace.json`, field `strip_audit`). FIVE of the smoke's fifteen charges --
# every `number_unbacked` it made -- are a WINDOW LENGTH read as a claim figure:
#     deep  "- Tropical Pacific +1.8 degC [N23], +2.4 sigma on 120 months [N24], 93rd percentile [N25]"
#           claims [1.8, 2.4, 120.0, 93.0]; 120 matches no served row; ALL THREE handles stripped.
#     max   "The board crush reads 2.6 USD/bu [N36], 92nd percentile of its own 250-session record [N38]"
#           claims [2.6, 92.0, 250.0]; 250 matches no served row; BOTH handles stripped.
# `120` and `250` are the SAME quantity the estate's own citation lines print as scope, never as value:
# `[N44] NOAA ONI ONI anomaly global MY2026-07 vs 120 points of its own history = 2.4 sigma`. The row's
# VALUE is 2.4; the 120 is the window it was computed over. No served row can equal it except by
# coincidence, so charging it is a false positive by construction -- the identical argument cycle-8 made
# for "5-year mean". The consequence measured on the smoke: SEVEN correct figures (1.8, 2.4, 93, 2.6, 92
# and their handles) were served BARE, with every citation removed from two sentences whose every
# statement was right.
#
# WHY CYCLE-8 RULE (f) MISSES THEM, read off its own definition -- two independent reasons:
#   * the SPACE spelling requires the duration noun to be followed by a `_STAT_HEAD` word, and in this
#     estate a duration noun is followed by a CITATION HANDLE ("on 120 months [N24]"). Rule (f)'s own note
#     says so in terms: "Punctuation, a citation handle, or the end of the clause after the duration noun
#     is still head position and still a claim."
#   * `_DURATION_NOUN` carries no OBSERVATION-window unit at all -- `session` is not `season` -- so the
#     hyphen spelling "250-session record" never reached rule (f) either.
#
# THE RULE IS TWO NARROW SHAPES, AND EACH EARNS ITS EXEMPTION FROM SOMETHING ORTHOGRAPHIC:
#   (h-i)  HYPHEN + an observation-window unit + a WINDOW HEAD NOUN: "250-session record",
#          "320-session window", "60-print history". The compound modifier is the writer declaring the
#          numeral is a length, and the head noun says what it is the length OF.
#   (h-ii) SPACE spelling, ONLY when the numeral is the object of a WINDOW PREPOSITION that itself
#          follows a STATISTIC word -- "sigma on 120 months", "percentile of 320 sessions" -- and the
#          head after the unit is punctuation, a citation handle or the clause end.
# THE LEFT CONTEXT IN (h-ii) IS THE WHOLE FENCE, and it is what keeps the eight cycle-8 head-position
# counter-examples claims: "prices have risen for 5 months in a row [N10]", "ending stocks cover 21 days
# of use [N6]", "US corn is 12 days ahead of the pace [N4]", "the crush ran 3 weeks behind schedule [N5]",
# "exports rose in each of the last 5 months of the marketing year [N1]", "10 days before the as-of date",
# "within 6 days prior to the 2026-08-07 as-of", "stocks are 12 months of use [N8]". NONE has a statistic
# word in front of its preposition, and six of the eight additionally fail the tail (a preposition, not a
# terminator, follows their duration noun). Measured: 0 of 8 flip, and they stay pinned by
# `test_cycle8_repair_integrity.py::test_fix1_duration_noun_in_HEAD_position_is_still_a_claim` and
# `::test_b2_head_position_duration_quantities_are_still_claims`.
#
# DELIBERATELY TIGHTER THAN THE THREAT MODEL'S OWN PROPOSAL (`THREAT_MODEL_FIXES.md` B.4, B-i), AND THE
# REASON IS MEASURED. That proposal put the observation-window units straight into `_DURATION_NOUN`, which
# arms rule (f)'s HYPHEN branch for ANY following word -- and rule (f)'s hyphen branch takes any head that
# is not a `_DUR_STOP`. That would de-charge "a 12-point drop [N3]" and "a 5-point move", where the numeral
# IS the magnitude. Requiring a WINDOW HEAD NOUN in (h-i) keeps every measured flip (11 of 11 over the case
# list and the 14-answer unseen corpus -- see the build report) and closes that class by construction.
# `_DURATION_NOUN` DOES NOT MOVE, so every rule-(f) verdict in the estate is byte-identical.
#
# IT RIDES THE `cycle8` FLAG, like rule (g) and for the same reason (review MINOR-7, 2026-09-04): the
# frozen pre-amendment view `_claim_number_spans(s, cycle8=False)` must stay exactly what HEAD extracted.
# NOT COVERED, DELIBERATELY: a window length spelled with NO statistic and NO head noun ("over 120 months
# the pace fell") stays a claim -- under-claiming the exemption is the safe direction, and no measured
# sentence needs it.
_WINDOW_UNIT = r"(?:session|print|observation|obs|reading|point|row|marketing[ ]year)s?"
# The nouns a window length can be the length OF. Read off what the estate's own prose and citation lines
# write ("of its own 250-session record", "the 320-session window", "vs 156 points of its own history").
# ROUND-2 REVIEW, MINOR-1: `range` and `span` are REMOVED from this set. They read as window heads in
# "a 320-session range", but they are also the heads of an ORTHOGRAPHIC MAGNITUDE -- "the front spread
# traded in a 12-point range [N3]", "a 40-point span [N9]" -- where the numeral IS the quantity, and (h-i)
# was exempting those. 0 window lengths in 85,133 unseen real-seat sentences are spelled with either head,
# so the exemption cost nothing and the hole was real; `record|history|window|lookback|sample|series|
# distribution` carry every measured one.
_WINDOW_HEAD = r"(?:record|history|window|lookback|sample|series|distribution)"
# The words that make the numeral after a window preposition a LENGTH rather than a quantity. Statistic
# words only: `record` / `history` are deliberately ABSENT here (they are HEAD words in (h-i), and as
# leads they also introduce ordinary quantities -- "a record of 12 months").
# ROUND-2 REVIEW, MINOR-2: `mean`, `average`, `median` and `rank` are REMOVED. They are not DISPERSION
# statistics read AGAINST a window, they are CENTRES read OVER one, and as leads they re-open exactly the
# class CYCLE-8 BLOCKER 2 protects: "Stocks cover an average of 21 days [N6]", "Inventory turns at a
# median of 45 days [N12]" and "Shipments lag by an average of 6 weeks [N7]" all stopped being claims
# although the numeral IS the quantity. 0 measured window lengths are led by any of the four.
_WINDOW_STAT = (r"(?:sigma|z|z-score|zscore|percentile|pctile|pctl|decile|quantile|quartile|"
                r"window|lookback)")
# (h-i) the hyphen spelling: '-session record', '-print history'. The exotic hyphens come from `_DUR_HYPH`.
_WINDOW_HYPH = re.compile(r"\A" + _DUR_HYPH + _WINDOW_UNIT + _DUR_SEP + r"+" + _WINDOW_HEAD + r"\b", re.I)
# (h-ii) the LEFT context: a statistic word, then a window preposition, then the numeral.
_WINDOW_LEAD = re.compile(r"\b" + _WINDOW_STAT + r"[ ]*(?:" + _DUR_HYPH + r"|[ ])?[ ]*"
                          r"(?:on|over|across|against|of)[ ]+\Z", re.I)
# (h-ii) the RIGHT shape: one space, a duration OR observation-window unit, then HEAD POSITION -- a
# citation handle, punctuation, a dash or the clause end. The handle is admitted in all three spellings a
# caller can hand this extractor: written (`[N24]`), masked to spaces (`_mask_handles`) and removed
# outright (`_HANDLE.sub("")`), which is why the terminator set carries the bracket, the blank-then-comma
# and the bare end. Dashes as \u escapes to keep this source ASCII (`_RANGE_TAIL`'s discipline).
_WINDOW_TAIL = re.compile(r"\A[ ]+(?:" + _DURATION_NOUN + r"|" + _WINDOW_UNIT + r")"
                          r"[ ]*(?:\[[NE]?\d|[,;.:)\]]|-{2}|[" + "\u2013\u2014" + r"]|\n|\Z)", re.I)
# ROUND-2 DOCKET item B-2 (2026-09-17) -- (h-iii), THE `of` SPELLING, and it needs NO left context
# because its RIGHT context is the whole declaration. Two shapes, both read off the estate's own prose:
#   "vs 120 points of its own history"   an OBSERVATION unit + `of` + a WINDOW HEAD noun
#   "the newest of 53 rows covering 2026-06-01..2026-08-20"   an OBSERVATION unit + a window CONTINUATION
# `row` joins `_WINDOW_UNIT` for the second, which is what the estate calls a record's members when it
# counts them ("53 rows"). The units are OBSERVATION units only -- `_DURATION_NOUN` is deliberately NOT
# admitted here, so "exports rose in each of the last 5 months of the marketing year [N1]" and "stocks are
# 12 months of use [N8]" stay claims (neither `marketing year` nor `use` is a `_WINDOW_HEAD` noun, and
# neither takes a continuation). MEASURED, the shape this closes: the banked
# `da_baseline_control/rv_meal_oil` sentence "- The window series shows meal at 7.1236 USD/bushel [N5] and
# oil at 7.8452 USD/bushel [N6] as the newest of 53 rows covering 2026-06-01..2026-08-20." -- both real
# figures ARE backed, only the RECORD LENGTH 53 is not, and HEAD strips BOTH handles and serves all three
# figures bare. It is the same false positive as `120` and `250`, one spelling further out.
_WINDOW_OF = re.compile(r"\A[ ]+" + _WINDOW_UNIT + r"[ ]+"
                        r"(?:of[ ]+(?:its[ ]+own[ ]+|the[ ]+|this[ ]+|our[ ]+)?" + _WINDOW_HEAD + r"\b"
                        r"|(?:covering|spanning|back[ ]to)\b)", re.I)

# -- D-DA UNIT-SCALE (2026-09-04) -- THE THIRD SANCTIONED AMENDMENT TO CLAIM EXTRACTION --------------
# SCOPE, AS RATIFIED: FALSE-POSITIVE REDUCTION IN CLAIM EXTRACTION ONLY, exactly the cycle-8 scope. ONE
# shape stops being a claim magnitude -- the SCALE PART of a UNIT LABEL that the sentence writes
# immediately after a figure -- and nothing else in this module's rules moves. Cycle-6's reader-precision
# arm and cycle-8's ordinal/duration arm are frozen exactly as shipped.
#
# THE MEASURED DEFECT (arm da-arm-CONTROL, 7 answers, 2026-09-04,
# `data/batch_runs/da_baseline_control_20260904T141206Z.json`, field `strip_audit`). 33 of the 35
# `number_unbacked` charges are sentences that TRANSCRIBE A SERVED ROW'S OWN UNIT LABEL. The served PSD
# ATTRIBUTES row prints `= 154,947 (1000 MT)`; the model quotes it verbatim and this extractor returned
#     [154947.0, 1000.0, 161297.0, 1000.0]
# -- the label's thousand-scale read as a fourth MAGNITUDE. No served row is ever equal to 1000 (it is the
# UNIT, not a quantity), so `number_unbacked` fired on a sentence in which every figure was right, and it
# fired on the correct transcription of the honest-clock PSD rows serving rev 128 in production. The class
# is not PSD-specific: it is every label whose scale word is spelled as a NUMERAL rather than as
# "Thousand"/"Million" -- the WASDE spelling "Thousand Short Tons" carries no digit and was never charged,
# while the identical quantity in the PSD spelling "(1000 MT)" was charged every time.
#
# THE SHAPES ARE ENUMERATED FROM WHAT THE ESTATE RENDERS, NEVER GUESSED. A citation line is built in
# `citations.render` / `citations._agg_citation` as `f"{src} {mdisp} {scope} = {_fmt(value)} {unit}"`,
# where `unit` is the ROW's own `unit` column when it has one and otherwise `citations._metric_unit`'s
# registry lookup. The labels that carry a numeral, read off both producers:
#     registry (configs/graphrag/numbers/tables.yaml)   "1000 MT"  "1000 ha"  "1000 HEAD"  "1000 boxes"
#                                                       "1000 60 KG BAGS"  "1000 60-kg bags"
#                                                       "1000 480 lb. Bales"
#                                                       "60-kg bags"  "COP per 125-kg carga"
#                                                       "MMT (cotton: million 480-lb bales)"
#                                                       "MMT change (cotton: million 480-lb-bale change)"
#     PSD unit_desc, carried VERBATIM by the long        "(1000 MT)"  "(1000 MT CWE)"  "(1000 HA)"
#     attributes table (usda_psd_attributes: "value in   "(1000 HEAD)"  "(1000 60 KG BAGS)"
#     its NATIVE unit plus unit_desc")                   "1000 480 lb. Bales"
# Every one of them is the SAME grammar: one or more SCALE tokens, then a UNIT WORD, optionally wrapped in
# the source's own parentheses and optionally introduced by the label words those strings themselves use
# ("per", "million", "cotton", "change", the COP currency code). `_UL_UNIT` is the set of unit words that
# stand DIRECTLY after a scale token in those labels and `_UL_QUAL` the words the labels put between the
# figure and its scale -- both read off the census above and nothing wider (review MINOR-3, 2026-09-04:
# the first cut carried KT / TONNES / CWT / BUSHELS / ACRES and thirteen currency codes no label prints,
# each one a bridge for MAJOR-1 below, and missed "1000 boxes"). Neither is a general-purpose unit list
# and neither may grow past the labels the estate renders.
#
# THE RULE HAS A LEFT CONTEXT, AND THAT IS THE WHOLE FENCE. A scale numeral is exempt ONLY when it stands
# immediately after a numeral this extractor has ALREADY ACCEPTED as a claim -- the figure the label scales
# -- separated by nothing but blanks, one opening bracket and those label words. So:
#     "feed use at 154,947 (1000 MT)"     -> 1000 is the label's scale     EXEMPT
#     "about 1000 tonnes"                 -> no figure in front of it      STILL A CLAIM, still charged
#     "corn 62,196 (1000 MT), soy 66,546" -> the comma breaks the lead     66,546 STILL A CLAIM
# and the fabricated-figure case is untouched by construction: the figure itself is never what this rule
# exempts, so "feed use at 199,999 (1000 MT)" still charges 199,999 and still strips.
# THE EXEMPTED NUMERAL MUST BE A BARE DIGIT RUN (review MAJOR-1, 2026-09-04): no thousands comma, no decimal
# point. Every scale in the corpus is written 1000 / 480 / 125 / 60 and every real magnitude this estate
# writes is 154,947 / 42.5 / -83.476 / 49,401,000, so the lead -- which has to admit the label words
# between a figure and its scale -- can no longer bridge two FORMATTED figures: "Exports 154,947 MT
# 161,297 MT" charges both, "Exports were 42.5 (999,999 MT)" charges 999,999, "freight was 45 USD per
# 1,250 MT" charges 1,250. Measured at zero cost by the review: the same 135 value-1000 removals over the
# 431 banked artifacts and the control replay byte-identical (number_unbacked 3 / mismatch 6 / undeclared 41).
# THE LABEL IS CONSUMED WHOLE AND AN EXEMPTED TOKEN NEVER ANCHORS (review MINOR-5): a rendered label carries
# at most TWO scale tokens ("1000 60 KG BAGS", "1000 480 lb. Bales"), so `_UL_TAIL` admits ONE further bare
# token of at most three digits before the unit word, the whole label is skipped in one read, and the
# exempted token is never the figure a following label may grow from. One accepted figure therefore
# shields the label grammar's own reach and nothing beyond it: "154,947 1000 777777 888888 MT" charges
# 1000 and 777777 (only the bare run directly before the unit word reads as a scale).
# THE LEAD DELIBERATELY REFUSES A DASH. `_RANGE_TAIL`'s note records the measured hazard it closes --
# "ranged 5900-9999 MT let a fabricated 9999 ride uncited" -- and a dash in this lead would re-open exactly
# that: 5900 is an accepted claim and "MT" follows 9999, so a dash separator would exempt the upper bound
# of every hyphenated range. Blanks, one "(" or "[" and the ":" the cotton label prints -- only; no "/".
# NOT COVERED, DELIBERATELY: "32nds of an inch" (the scale wears an ORDINAL suffix and is glued to a
# denominator, which is cycle-8 rule (e)'s class, not this one) and "0/1" (a flag label with NO unit word
# at all -- exempting it would be exempting a bare numeral pair, the very thing the bare-'1000' pin says
# must keep stripping). Both stay charged, and that is stated rather than quietly left out.
# THE THIRD TRANSITION, strip -> HARDER strip (review MINOR-4): `_num_matches` is an ANY-of predicate, so
# against a served row whose VALUE is 1000 the label's scale used to count as the sentence's one match and
# a fabricated figure beside it ("The pace was 42.5 (1000 MT)") was charged number_unbacked -- handle
# removed, sentence kept. The rule reads no match there and the sentence dies as number_mismatch. That is
# the honest verdict (the 'match' was a scale coinciding with a row value; the sentence's only real
# figure is fabricated), it is pinned, and it did not occur on the control arm (mismatch 6 -> 6).
# NO VALUE GATE, DELIBERATELY, AND THE RESIDUAL THAT LEAVES IS STATED (review MAJOR-2): the rule is
# STRUCTURAL ("this numeral is a label's scale"), not a whitelist of {1000, 480, 125, 60}. The price is
# that a MIS-TRANSCRIBED scale is caught by NOTHING in this module today: "feed use at 154,947 (9999 MT)"
# exempts 9999 exactly as it exempts 1000; `quote_mismatch` (`_unbacked_quote`) inspects QUOTED spans only,
# and the footer lane reads the engine's own unit column, never the model's prose. The same shape covers a
# bare second figure before a unit word ("5900 9999 MT"), which no structural reading can tell from
# "-83.476 1000 MT". Charging either as an unbacked MAGNITUDE and killing the sentence would be the
# disproportionate instrument this amendment exists to remove; the proportionate catcher is a
# UNIT-VOCABULARY gate at the charge site (the exempted token must be a scale the sentence's own served
# rows print in their unit strings), and that is the DOCKETED follow-up, pinned in the open, not a
# catcher this note pretends already fires.
_UL_UNIT = r"(?:MT|HA|HEAD|KG|LB|BOXES)"
# The words the enumerated labels put BETWEEN the figure and its scale, and nothing else: "MMT (cotton:
# million 480-lb bales)", "MMT change (cotton: million 480-lb-bale change)", "COP per 125-kg carga".
_UL_QUAL = r"(?:MMT|PER|MILLION|COTTON|CHANGE|COP)"
# The separator a lead may carry between those words: blanks plus ONE of "(" / "[" / ":". No comma (a
# comma is a LIST, and a list's second figure is a claim); no dash (see the range hazard above); no "/"
# (no rendered label carries one, and every admitted separator is one more bridge for MAJOR-1).
_UL_SEP = r"[ \t]*(?:[(\[:][ \t]*)?"
_UL_LEAD = re.compile(r"\A" + _UL_SEP + r"(?:" + _UL_QUAL + r"\b" + _UL_SEP + r")*\Z", re.I)
# THE EXEMPTED NUMERAL ITSELF: a BARE digit run -- no thousands comma, no decimal point (MAJOR-1).
_UL_BARE = re.compile(r"\d+")
# What must FOLLOW a scale token for it to be one: blank-or-hyphen glue, then AT MOST ONE further bare
# scale token of at most three digits (the sub-unit weight of "1000 60 KG BAGS" / "1000 480 lb. Bales";
# no label carries a third -- MINOR-5), then a unit word. The exotic hyphens are chr()-built so this
# source stays ASCII, the discipline `_RANGE_TAIL` and `_DUR_HYPH` both state.
_UL_GLUE = "[ \t" + chr(0x2010) + chr(0x2011) + "-]"
_UL_TAIL = re.compile(r"\A" + _UL_GLUE + r"+(?:\d{1,3}" + _UL_GLUE + r"+)?" + _UL_UNIT + r"\b", re.I)


# ══ 09-23 FIX ROUND (lane V, BRIEF items 3 + 4, CONTRACT C6; FIX round: review FATAL-1 + M2) ══════════════
# THE UNIT VOCABULARY IS DECLARED DATA, AND A UNIT LABEL IS READ FROM ITS OWN START
# THE MEASURED DEFECT (09-23 re-smoke, cotton): all 13 of the turn's charges were ONE false positive. The
# served WASDE rows print their own unit "Million 480 Pound Bales"; the writer transcribed it as
# "3.6 million 480-pound bales [N14]"; rule (g)'s unit words were a hand-typed six, "pound" was not one of
# them, so 480 became a claim magnitude no row carries and `number_unbacked` took every handle of four
# correct balance-sheet sentences. The rice turn is the same class through `_UNIT_AFTER` ("net long 1992
# contracts [N37]" read 1992 as a YEAR).
# WHERE THE VOCABULARY COMES FROM -- DATA ONLY, NO WORD LIST IN THIS MODULE:
#   * CARDS -- every metric `unit`, `unit_overrides` value and `display_unit` across the loaded numbers
#     registry (`registry.card_unit_phrases()`), each read as the ALTERNATIVES its own bracket grammar
#     declares ("MMT (cotton: million 480-lb bales)" is the unit "MMT" and, for cotton, "million 480-lb
#     bales");
#   * SPELLINGS -- the other spellings of those units ("tonnes" for MT, "percent" for %, "bps", "cwt", the
#     durations' "yr" / "wk" / "qtr"), declared ONCE as data in tables.yaml's `unit_spellings` /
#     `duration_spellings` / `unit_scale_words` (registry.unit_spellings & co.). Each key and its list is
#     ONE equivalence class -- how "the unit the writer wrote is the unit the row carries" is decided
#     (`_unit_equal`), with no morphology rule: a plural is declared like any other spelling;
#   * ROWS -- the `unit` string of every row the sentence's own [N] handles SERVED, ROW-GRANULAR (a row that
#     recorded no unit contributes nothing and voids nothing);
#   * THE RENDER -- the board's own period nouns (`render.PERIOD_NOUNS`) for the duration rules.
# FATAL-1 (the fix-round review): the first cut expanded every declared phrase into ALL its contiguous
# sub-runs and masked any of them after a figure, so the function words inside card units -- "sigma VS 3 yr
# mean", "sigma vs PRIOR 5 yrs", "COP PER 125-kg carga" -- became global maskers: "3.6 million 480-pound
# bales vs 5 in MY2025/26 [N14]" kept its false 5 with its handle. And rule (g)'s word bags, "derived" from
# the same strings, added "vs" / "prior" / "sigma" as LEAD words and "yr" as a UNIT word: "4.1 vs 3 yr ago"
# lost its 3. THE STRUCTURAL READING: a unit label written after a figure is the declared phrase written
# FROM ITS OWN START -- a PREFIX of one declared phrase that runs through a scale numeral AND the word it
# scales (a scale numeral always scales the word written after it). "million 480-pound bales" is the
# prefix of "Million 480 Pound Bales"; "vs 5" and "per 125" start in the middle of a phrase and are never a
# label. At a CHARGE SITE rule (g) is therefore SUBSUMED by this one phrase-prefix rule (i) over the
# declared data; rule (g)'s bags (HEAD's `_UL_UNIT` / `_UL_QUAL`) keep serving only the default extractor
# and the frozen cycle-8 view, byte for byte. `_claim_number_spans(s, cycle8=False)` sees NONE of this.
_UNIT_PUNCT = "()[]{}:;,\"'" + "".join(chr(c) for c in (0x201c, 0x201d, 0x2018, 0x2019))
_UNIT_SPACE_RX = re.compile(r"[\s" + chr(0x00a0) + chr(0x2010) + chr(0x2011) + r"\-]+")
_UNIT_NUMERAL = re.compile(r"\d[\d,]*")
_UNIT_TOKEN_RX = re.compile(r"[^\s" + chr(0x00a0) + chr(0x2010) + chr(0x2011) + r"\-]+")
# A declared unit string's OWN grammar for alternatives: a bracketed gloss, a ':' naming what the gloss is
# for, a ',' adding a basis ("MMT (cotton: million 480-lb bales)", "MMT change, milled basis").
_UNIT_ALT_SPLIT = re.compile(r"[(),]")


def _unit_tokens(s) -> tuple:
    """A unit string as its normalised TOKENS: lower-case, hyphen / non-breaking space / NB-hyphen folded
    to a blank, the label's own brackets and list punctuation dropped, a token's trailing '.' dropped
    ("lb." is "lb"). "Million 480 Pound Bales" -> ('million', '480', 'pound', 'bales'); "MMT (cotton:
    million 480-lb bales)" -> ('mmt', 'cotton', 'million', '480', 'lb', 'bales')."""
    out = []
    for t in _UNIT_SPACE_RX.split(str(s or "").lower()):
        t = t.strip(_UNIT_PUNCT).rstrip(".").strip(_UNIT_PUNCT)
        if t:
            out.append(t)
    return tuple(out)


def _is_unit_numeral(tok: str) -> bool:
    return bool(_UNIT_NUMERAL.fullmatch(tok or ""))


def _phrase_alternatives(s) -> set:
    """The token tuples ONE declared unit string declares: the whole string, and each segment its own
    bracket / comma grammar separates (the part after a ':' inside a segment is the gloss's unit)."""
    out = {_unit_tokens(s)}
    for seg in _UNIT_ALT_SPLIT.split(str(s or "")):
        seg = seg.rsplit(":", 1)[-1]
        out.add(_unit_tokens(seg))
    return {t for t in out if t}


#: THE DECLARED HALF, memoised per resolved config root (the `_BAR_*_CACHE` discipline: six unit files
#: repoint `extract._CFG`).
_CARD_UNIT_CACHE: dict = {}
_VOCAB_CACHE: dict = {}


def _card_unit_phrases() -> tuple:
    """Every unit string the loaded numbers registry declares (`registry.card_unit_phrases`, CONTRACT C6),
    as token tuples, each with its declared alternatives. An unreadable registry is an EMPTY card half --
    never an error on an answer, and never memoised (a transient failure must not pin an empty half)."""
    key = _bar_cfg_key()
    if key in _CARD_UNIT_CACHE:
        return _CARD_UNIT_CACHE[key]
    try:
        from leviathan.graphrag.numbers import registry as _nreg
        raw = list(_nreg.card_unit_phrases() or ())
    except Exception:  # noqa: BLE001 -- no registry is an empty card half, never a broken answer
        return ()
    out: set = set()
    for u in raw:
        out |= _phrase_alternatives(u)
    res = tuple(sorted(out))
    _CARD_UNIT_CACHE[key] = res
    return res


class _DeclaredVocab:
    """The declared, sentence-independent vocabulary: `phrases` (cards + spellings, token tuples), `cls`
    (joined phrase -> equivalence-class id), `scales` (the declared scale words), `durations` (every
    declared duration spelling)."""

    __slots__ = ("phrases", "cls", "scales", "durations", "spell_only")

    def __init__(self, phrases, cls, scales, durations, spell_only=frozenset()):
        self.phrases, self.cls, self.scales, self.durations = phrases, cls, scales, durations
        #: the phrases ONLY a declared spelling (or a render noun) contributes -- no card prints them
        self.spell_only = spell_only


def _declared_vocab() -> _DeclaredVocab:
    key = _bar_cfg_key()
    v = _VOCAB_CACHE.get(key)
    if v is not None:
        return v
    ok = True
    cards = _card_unit_phrases()
    spell: dict = {}
    dur: dict = {}
    scales: set = set()
    try:
        from leviathan.graphrag.numbers import registry as _nreg
        spell = dict(_nreg.unit_spellings() or {})
        dur = dict(_nreg.duration_spellings() or {})
        scales = {str(w) for w in (_nreg.unit_scale_words() or ())}
    except Exception:  # noqa: BLE001 -- no declared spellings: the cards and the rows still stand
        ok = False
    cls: dict = {}
    phrases: set = set(cards)
    durations: set = set()
    for group, is_dur in ((spell, False), (dur, True)):
        for canon, members in group.items():
            for m in members:
                t = _unit_tokens(m)
                if not t:
                    continue
                phrases.add(t)
                cls[" ".join(t)] = ("dur:" + canon) if is_dur else canon
                if is_dur:
                    durations.add(" ".join(t))
    # THE RENDER'S OWN PERIOD NOUNS (session / week / fortnight / month / marketing year / release, and the
    # plural the board prints beside a count -- `render.period_noun`) are units a board figure is written
    # in ("8 sessions"), each its own class; they are never declared durations (`_duration_rx`'s split).
    try:
        from leviathan.graphrag.state import render as _rnd
        pn = getattr(_rnd, "period_noun", None)
        for cad, noun in (getattr(_rnd, "PERIOD_NOUNS", None) or {}).items():
            forms = {str(noun)} | ({str(pn(cad, 2))} if callable(pn) else set())
            for f in forms:
                t = _unit_tokens(f)
                if t and " ".join(t) not in cls:
                    phrases.add(t)
                    cls[" ".join(t)] = "period:" + str(noun)
    except Exception:  # noqa: BLE001 -- no render, no board period nouns
        ok = False
    v = _DeclaredVocab(tuple(sorted(phrases)), cls, frozenset(scales), frozenset(durations),
                       frozenset(set(phrases) - set(cards)))
    if ok and cards:
        _VOCAB_CACHE[key] = v
    return v


def _declared_unit_key(toks) -> str:
    """The declared equivalence class of a unit phrase (its tokens), or the phrase itself: "months" and
    "month" are one class, "tonnes" and "MT" are one class -- by DECLARATION (tables.yaml), never by a
    morphology rule."""
    p = " ".join(t for t in (toks or ()) if t)
    return _declared_vocab().cls.get(p, p)


def _unit_equal(a, b) -> bool:
    """Is unit phrase `a` (tokens) the SAME unit as `b`? Exact after normalisation, or one declared class."""
    a, b = tuple(a or ()), tuple(b or ())
    return bool(a) and bool(b) and (a == b or _declared_unit_key(a) == _declared_unit_key(b))


def _cited_number_idx(sent: str, number_calls: list) -> list[int]:
    """Every in-range [N] member the sentence writes, grouped members included, in written order."""
    out: list[int] = []
    for m in _HANDLE.finditer(sent or ""):
        for kind, j in _handle_members(m.group(0)):
            if kind == "N" and 1 <= j <= len(number_calls or ()) and j not in out:
                out.append(j)
    return out


def _row_unit_strings(number_calls: list, cited) -> tuple:
    """The `unit` strings the cited calls' rows SERVED, row-granular: a unit-less row contributes nothing."""
    out: list[str] = []
    for j in cited or ():
        if not (1 <= j <= len(number_calls or ())):
            continue
        for r in ((number_calls[j - 1] or {}).get("rows") or []):
            u = str((r or {}).get("unit") or "").strip()
            if u and u not in out:
                out.append(u)
    return tuple(out)


def _unit_phrases_for(sent: str, number_calls: list, cited: list | None = None) -> tuple:
    """CONTRACT C6 -- the unit phrases a sentence is read against: the declared vocabulary (cards and their
    spellings) UNION the cited calls' own served row `unit` strings (row-granular, each with its declared
    alternatives), as normalised token tuples. `cited` defaults to the sentence's own in-range [N] members."""
    idx = _cited_number_idx(sent, number_calls) if cited is None else list(cited)
    rows: set = set()
    for u in _row_unit_strings(number_calls, idx):
        rows |= _phrase_alternatives(u)
    return tuple(sorted(set(_declared_vocab().phrases) | rows))


class _UnitGrammar:
    """The declared unit vocabulary one sentence is extracted with, at a CHARGE SITE. Built from phrase
    token tuples (declared + the sentence's own rows) and the rows' raw unit strings (for the year rule).
    `prefixes` is rule (i)'s whole vocabulary: every PREFIX of a declared phrase that runs through a scale
    numeral and at least the word after it. Immutable; memoised."""

    __slots__ = ("prefixes", "maxrun", "row_after", "phrases", "shapes", "printed")

    def __init__(self, phrases: tuple, row_units: tuple = ()):
        self.phrases = tuple(phrases or ())
        # THE PHRASES A READER SAW PRINTED beside a figure: the cards' and the cited rows' own unit strings
        # -- never a spelling-only word. The FIGURE CUT's unit tail reads these (the round-2 ladder's own
        # scope: a cut ordinal leaves its word "percentile", pinned in test_verifier_correct_not_delete).
        _rows = set()
        for u in row_units or ():
            _rows |= _phrase_alternatives(u)
        _spell = _declared_vocab().spell_only
        self.printed = tuple(p for p in self.phrases if p not in _spell or p in _rows)
        # RULE (g)'s LABEL SHAPES, DERIVED PHRASE BY PHRASE (fix-round FATAL-1 + M2): each declared phrase
        # whose first numeral is preceded only by words declares the shape "<those leading words, from the
        # phrase's OWN START> <a bare scale numeral> [<one <=3-digit scale>] <the word the numeral scales>"
        # -- ('1000 mt') -> ((), mt); ('cop per 125 kg carga') -> ((cop, per), kg); ('sigma vs 3 yr mean')
        # -> ((sigma, vs), yr). A label POSITION after a figure is one of these shapes; its SCALE is then the
        # D-DA gate's to judge against the served rows. The leading words are a phrase PREFIX, never a bag:
        # "4.1 vs 3 yr ago" has no shape (no declared phrase STARTS "vs"), so its 3 stays a claim.
        shapes: dict = {}
        for p in self.phrases:
            i = next((k for k, t in enumerate(p) if _is_unit_numeral(t)), None)
            if i is None or any(_is_unit_numeral(t) for t in p[:i]):
                continue
            j = i + 1
            if j < len(p) and _is_unit_numeral(p[j]) and len(p[j]) <= 3:
                j += 1
            if j < len(p) and not _is_unit_numeral(p[j]):
                shapes.setdefault(tuple(p[:i]), set()).add(p[j])
        self.shapes = {k: frozenset(v) for k, v in shapes.items()}
        prefixes: set = set()
        for p in self.phrases:
            seen_num = False
            for k in range(1, len(p) + 1):
                if _is_unit_numeral(p[k - 1]):
                    seen_num = True
                    continue
                # a prefix ending on a WORD after at least one numeral: "1000 mt", "million 480 pound",
                # "cop per 125 kg" -- never one ending on the numeral, never one with no numeral
                if seen_num and k >= 2:
                    prefixes.add(p[:k])
            if seen_num and len(p) >= 2:
                prefixes.add(tuple(p))                # the WHOLE declared phrase, written out in full
        self.prefixes = frozenset(prefixes)
        self.maxrun = max((len(r) for r in prefixes), default=0)
        # THE YEAR RULE reads the sentence's OWN rows only (the rice grader's structural fix: "take the
        # un-exempting unit from the cited handle's own served-row unit ('contracts' on N37), never from a
        # longer list"); the cards' units would turn "in 2025 an El Nino" into a claim through the
        # registry's per-animal "An".
        alts = []
        for u in row_units or ():
            toks = [re.escape(t) for t in re.split(r"[\s" + chr(0x00a0) + r"]+", str(u).strip()) if t]
            if toks and re.search(r"[A-Za-z%]", u):
                alts.append(r"[\s\-]*".join(toks))
        self.row_after = (re.compile(r"\s*(?:" + "|".join(sorted(set(alts), key=lambda a: (-len(a), a)))
                                     + r")(?![A-Za-z])", re.I) if alts else None)


_GRAMMAR_CACHE: dict = {}


def _unit_grammar(phrases: tuple, row_units: tuple = ()) -> _UnitGrammar:
    key = (phrases, row_units)
    g = _GRAMMAR_CACHE.get(key)
    if g is None:
        if len(_GRAMMAR_CACHE) > 512:
            _GRAMMAR_CACHE.clear()
        g = _GRAMMAR_CACHE[key] = _UnitGrammar(phrases, row_units)
    return g


def _grammar_for(sent: str, number_calls: list) -> _UnitGrammar:
    """The declared grammar a CHARGE-SITE extraction of `sent` reads (CONTRACT C6)."""
    idx = _cited_number_idx(sent, number_calls)
    rows = _row_unit_strings(number_calls, idx)
    return _unit_grammar(_unit_phrases_for(sent, number_calls, idx), rows)


def _as_grammar(units) -> _UnitGrammar | None:
    """`units` as a grammar: an existing `_UnitGrammar`, or a tuple of phrases (strings or token tuples),
    each read with its declared alternatives."""
    if units is None or isinstance(units, _UnitGrammar):
        return units
    phrases: set = set()
    for p in units:
        if isinstance(p, tuple):
            phrases.add(p)
        else:
            phrases |= _phrase_alternatives(p)
    return _unit_grammar(tuple(sorted(phrases - {()})), ())


# ── `_DURATION_NOUN`, REBUILT FROM DECLARED DATA AND THE RENDER'S OWN PERIOD NOUNS (BRIEF item 4) ────────
# The board writes window lengths in its cadence's nouns (`render.period_noun`: session, week, fortnight,
# month, marketing year, release; "period" for an undeclared cadence; "quarter" in its lag bands). The noun
# set is the render's vocabulary UNION the DECLARED duration spellings (tables.yaml `duration_spellings`:
# day, week/wk, month, quarter/qtr, year/yr, season), read lazily and memoised; with neither readable the
# extractor keeps HEAD's own rule-(f)/(h) regexes, and the cycle8=False view never sees any of it.
_DUR_CACHE: dict = {}


def _duration_rx() -> tuple:
    """(rule (f)'s modifier regex, rule (h-ii)'s tail regex) over the derived duration nouns."""
    if "rx" in _DUR_CACHE:
        return _DUR_CACHE["rx"]
    declared = set(_declared_vocab().durations)
    nouns = set(declared)
    rendered_ok = False
    try:
        from leviathan.graphrag.state import render as _rnd
        for v in (getattr(_rnd, "PERIOD_NOUNS", None) or {}).values():
            if isinstance(v, str) and v.strip():
                nouns.add(v.strip().lower())
        pn = getattr(_rnd, "period_noun", None)
        if callable(pn):
            nouns.add(str(pn("", 1)).strip().lower())
        q = getattr(_rnd, "_quarters", None)
        if callable(q):
            nouns.add(str(q(1)).strip().lower())
        rendered_ok = True
    except Exception:  # noqa: BLE001 -- an unreadable render leaves the declared nouns, never an error
        pass
    if not nouns:
        return (_DURATION_MOD, _WINDOW_TAIL)          # nothing declared, nothing rendered: HEAD's own
    # THE RENDER'S NOUNS SPLIT BY WHAT THEY COUNT, AND RULE (h) ALREADY OWNS ONE HALF. A cadence noun that
    # counts OBSERVATIONS ("session", "marketing year" -- members of `_WINDOW_UNIT`) is a window length only
    # before a window HEAD noun or after a statistic lead (rule (h), D-EC round 2); arming rule (f)'s hyphen
    # branch with it would de-charge "a 3-session rally [N4]", where the numeral IS the magnitude. So rule
    # (f) takes the declared durations and the render's CALENDAR nouns, and rule (h) keeps the observation
    # units: every render noun is recognised, each by the rule whose left/right context fits what it counts.
    rendered = set(nouns)
    nouns = {n for n in nouns if n in declared or not re.fullmatch(_WINDOW_UNIT, n, re.I)}
    _DUR_CACHE["window_units"] = frozenset(rendered - nouns)
    alt = "|".join(re.escape(n).replace(r"\ ", "[ ]") for n in sorted(nouns, key=lambda n: (-len(n), n)) if n)
    dnoun = r"(?:" + alt + r")s?"
    mod = re.compile(
        r"\A(?:" + _DUR_HYPH + dnoun + _DUR_SEP + r"+(?!" + _DUR_STOP + r"\b)[A-Za-z]"
        + r"|[ ]" + dnoun + r"[ ]+(?!" + _DUR_STOP + r"\b)" + _STAT_HEAD + r"\b)", re.I)
    tail = re.compile(r"\A[ ]+(?:" + dnoun + r"|" + _WINDOW_UNIT + r")"
                      r"[ ]*(?:\[[NE]?\d|[,;.:)\]]|-{2}|[" + chr(0x2013) + chr(0x2014) + r"]|\n|\Z)", re.I)
    if not (rendered_ok and declared):                # never memoise a partial vocabulary (the one-way memo)
        _DUR_CACHE["nouns"] = frozenset(nouns)
        return (mod, tail)
    _DUR_CACHE["rx"] = (mod, tail)
    _DUR_CACHE["nouns"] = frozenset(nouns)
    return _DUR_CACHE["rx"]


def _derived_unit_words() -> frozenset:
    """Every unit WORD and PHRASE the declared vocabulary recognises with no sentence context: the cards'
    tokens and phrases, the declared spellings and durations, and the render's period nouns. The superset
    pin (HEAD's closed sets, listed in the deck -- not in this module) reads this."""
    _duration_rx()
    words: set = set()
    for p in _declared_vocab().phrases:
        words.update(p)
        words.add(" ".join(p))
    words.update(_DUR_CACHE.get("nouns") or ())
    words.update(_DUR_CACHE.get("window_units") or ())
    return frozenset(words)


def _phrase_run(s: str, pos: int, g: _UnitGrammar) -> int:
    """RULE (i): the end offset of the longest declared-phrase PREFIX written right after an accepted figure
    ending at `pos` (blanks and at most one "(" / "[" / ":" in between -- never a dash, never a comma), or
    -1. The run must be a PREFIX of one declared phrase running through a scale numeral and the word it
    scales (`_UnitGrammar.prefixes`) -- a run that starts mid-phrase ("vs 5", "per 125") is never a label."""
    if not g.prefixes:
        return -1
    lead = re.match(r"[ \t]*(?:[(\[:][ \t]*)?", s[pos:])
    start = pos + (lead.end() if lead else 0)
    if start >= len(s) or not (s[start].isalnum()):
        return -1
    toks: list[tuple[str, int]] = []                  # (normalised token, end offset in s)
    for m in _UNIT_TOKEN_RX.finditer(s, start):
        if len(toks) >= g.maxrun or "\n" in s[(toks[-1][1] if toks else start):m.start()]:
            break
        raw = m.group()
        t = raw.lower().strip(_UNIT_PUNCT).rstrip(".").strip(_UNIT_PUNCT)
        if not t:
            break
        toks.append((t, m.end()))
        if any(c in raw for c in ",;") and not _is_unit_numeral(raw.rstrip(",;")):
            break                                     # a list comma ends the run (a list's next figure is a claim)
    for k in range(len(toks), 1, -1):
        if tuple(t for t, _e in toks[:k]) in g.prefixes:
            return toks[k - 1][1]
    return -1


#: What may stand between an accepted figure and a label's scale numeral: blanks, the label's own
#: brackets / colon, and WORDS -- never a digit, a comma or a dash (the range hazard "5900-1000 MT").
_LABEL_LEAD_OK = re.compile(r"\A[\sA-Za-z(\[:.]*\Z")
_LABEL_TAIL_RX = re.compile(r"\A(?:" + _UL_GLUE + r"+(\d{1,3}))?" + _UL_GLUE + r"+([A-Za-z][A-Za-z0-9./]*)")


def _label_shape_end(s: str, anchor: int, n0: int, n1: int, g) -> int:
    """RULE (g) AT A CHARGE SITE: the end of a declared label SHAPE (`_UnitGrammar.shapes`) whose scale
    numeral is `s[n0:n1]`, written after the accepted figure ending at `anchor` -- or -1."""
    lead_text = s[anchor:n0]
    if not getattr(g, "shapes", None) or not _LABEL_LEAD_OK.match(lead_text):
        return -1
    units = g.shapes.get(_unit_tokens(lead_text))
    if not units:
        return -1
    mt = _LABEL_TAIL_RX.match(s[n1:])
    if not mt:
        return -1
    word = mt.group(2).lower().strip(_UNIT_PUNCT).rstrip(".")
    return n1 + mt.end() if word in units else -1


def _claim_number_spans(s: str, *, cycle8: bool = True, units=None) -> list[tuple[int, int, float]]:
    """The claim spans -- see `_claim_scan`. `units` (a `_UnitGrammar` or a tuple of unit phrases) arms the
    09-23 derived vocabulary at a CHARGE SITE; omitted, the extractor is HEAD's plus the rebuilt duration
    nouns, and `cycle8=False` is HEAD's (a)-(d) view byte for byte."""
    return _claim_scan(s, cycle8=cycle8, units=units)[0]


def _claim_scan(s: str, *, cycle8: bool = True, units=None) -> tuple:
    """(start, end, value) per claim magnitude, positions into `s`. EXEMPT (never a claim): (a) a bare
    4-digit calendar year 1900-2099 with no decimal/comma ('2,021' and '2010.5' keep their punctuation and
    stay magnitudes) -- UNLESS a unit token follows ('exports hit 1950 MMT' IS a claim); (b) the 1-2 digit
    tail of a YEAR range ('1998-99' -> the '99'); (c) any digit run immediately preceded by a letter (B40,
    T2, MY2021, CO2), handled by _CLAIM_NUM's lookbehind; (d) the 1-2 digit DAY of a date, ISO
    ('2026-05-30') or long-form on either side of the month name ('25 July 2026', 'July 25, 2026');
    CYCLE-8 (2026-08-08), the SECOND SANCTIONED AMENDMENT -- (e) a digit run wearing an ORDINAL suffix
    ('85th percentile', '3rd consecutive month'), and (f) a digit-form DURATION MODIFIER, i.e. a duration
    noun glued to the digits AND itself followed by another word ('5-year mean', '90-day change',
    '12-week moving average'). Both are POSITION/WINDOW slots, never magnitudes. See the block note above
    for the measured corruption they close and for the deliberate limit: the duration noun in HEAD position
    ('the last 5 months [N11]') is still a claim, and a percent numeral ('2 percent below the average',
    'grew 5 percent') is untouched by every rule here.
    D-DA UNIT-SCALE (2026-09-04), the THIRD SANCTIONED AMENDMENT -- (g) the SCALE PART of a UNIT LABEL
    written immediately after an already-accepted figure ('154,947 (1000 MT)', '-83.476 1000 MT',
    '12,345 60-kg bags'). The scale is the label, never a magnitude; see the block note above for the
    measured 33-of-35 false-positive class and for the left-context fence that keeps a bare 'about 1000
    tonnes' a claim.
    D-EC PRE-ARM (2026-09-17), the FOURTH SANCTIONED AMENDMENT -- (h) the LENGTH OF AN OBSERVATION WINDOW,
    in exactly three shapes: a hyphenated observation-window unit in front of a window head noun
    ('250-session record', '320-session window'), a window preposition governed by a STATISTIC word
    ('+2.4 sigma on 120 months [N24]', 'the 29th percentile of 320 sessions') and -- ROUND-2 DOCKET B-2 --
    an observation unit taking a possessive window head or a window continuation ('vs 120 points of its
    own history', 'the newest of 53 rows covering 2026-06-01..'). A window length is what a
    statistic was read AGAINST, never a figure a row can carry; see the block note for the measured
    5-of-15 smoke class and for the eight head-position sentences the left context keeps as claims.
    A fabricated magnitude ('23.5 MMT' with no such row) is untouched by all eight rules and still strips.
    The span ENDS at the token core, so the sentence punctuation _CLAIM_NUM sweeps up is never part of it.

    `cycle8=False` returns the PRE-AMENDMENT view -- rules (a)-(d) only, exactly as HEAD extracted before
    cycle 8 -- and rules (g) and (h) ride under the SAME flag so that view stays what it was (review MINOR-7,
    2026-09-04: a frozen extractor's off-view must not move either). Its one caller was `_num_repair`'s
    ambiguity gate (CYCLE-8 REVIEW MAJOR 4), which CYCLE-10 deleted along with the rest of the rewrite
    path, so the flag has NO caller in this module and none outside it. It is KEPT, deliberately: this
    function is the cycle-8 charge-side amendment, which the termination branch freezes EXACTLY as
    shipped, and dropping a parameter of a frozen extractor would be a change to that amendment's
    surface for no behavioural gain. The default (`True`) is the shipped view and is what every caller
    gets."""
    s = s or ""
    out = []
    scales: list[float] = []       # 09-23: every scale token rule (g) or rule (i) exempted, in order
    # 09-23 (C6): the derived vocabulary, ONLY on the shipped view. `cycle8=False` is HEAD's (a)-(d)
    # exactly and reads HEAD's closed sets; the default view with no `units` reads HEAD's (g) floor and the
    # rebuilt duration nouns; a CHARGE SITE passes `units` and gets the cards + the sentence's own rows.
    g = _as_grammar(units) if cycle8 else None
    dur_mod, win_tail = _duration_rx() if cycle8 else (_DURATION_MOD, _WINDOW_TAIL)
    # D-DA (g): the end of the figure that a unit label may grow from. None everywhere else, so a label
    # can only ever follow a numeral this extractor ACCEPTED: an exempted year, ordinal, duration,
    # date-day or scale token clears it and never anchors a label.
    anchor: int | None = None
    skip_until = -1                # (g) the end of a label consumed whole -- its second scale token
    for m in _CLAIM_NUM.finditer(s):
        if m.start() < skip_until:
            _c = m.group().rstrip(".,")
            if _UNIT_NUMERAL.fullmatch(_c):
                try:
                    scales.append(float(_c.replace(",", "")))
                except ValueError:
                    pass
            continue                                            # (g)/(i) inside a consumed label
        tok = m.group()
        try:
            v = float(tok.replace(",", ""))
        except ValueError:
            continue
        # rstrip the SENTENCE punctuation _CLAIM_NUM sweeps into the token ('2026-05-30.' -> '30.',
        # 'July 25, 2026' -> '25,', 'in January 2026, but' -> '2026,') so a token at a clause/sentence
        # end still reaches the exemptions below instead of silently falling through as a magnitude.
        # T2b Lane-B: this cost the YEAR exemption too -- '2026,' failed fullmatch(\d{4}) and the audit
        # shows a bare year charged as an unbacked magnitude ("for January 2026" -> 2026.0). An INTERIOR
        # comma still disqualifies ('2,021' stays a magnitude) because rstrip only touches the tail.
        core = tok.rstrip(".,")
        # CYCLE-8 (2026-08-08): what FOLLOWS the token CORE -- the two new exemptions read the glue, and
        # reading it from `m.end()` would see the stripped '.'/',' instead of the shape it is glued to.
        after_core = s[m.start() + len(core):]
        # D-DA (g) -- decided FIRST, and it is the only rule here with a LEFT context. The order is not
        # a preference: (g) reads a shape none of (a)-(f) can see. The label is consumed WHOLE, so its
        # SECOND scale token ('1000 60 KG BAGS') is skipped, never anchored (MINOR-5); the exempted
        # numeral must be a BARE digit run (MAJOR-1); and it rides under `cycle8` so the frozen flag's
        # off-view stays HEAD's (MINOR-7). 09-23 FIX ROUND (FATAL-1 / M2): at a CHARGE SITE (`units`
        # given) this bag rule is SUBSUMED by rule (i) below -- a declared phrase written from its own
        # start -- so no bag of lead / unit words is ever read there; the default extractor keeps it.
        if cycle8 and g is None and anchor is not None and _UL_BARE.fullmatch(core):
            _tail = _UL_TAIL.match(after_core)
            if _tail and _UL_LEAD.match(s[anchor:m.start()]):
                skip_until = m.start() + len(core) + _tail.end()  # (g) a UNIT LABEL's scale: '(1000 MT)'
                scales.append(float(core))
                anchor = None                                    # consumed whole; never an anchor
                continue
        if cycle8 and g is not None and anchor is not None and _UL_BARE.fullmatch(core):
            _lend = _label_shape_end(s, anchor, m.start(), m.start() + len(core), g)
            if _lend > 0:
                skip_until = _lend                               # (g) at a charge site: a DECLARED shape
                scales.append(float(core))
                anchor = None
                continue
        if cycle8:
            if _ORDINAL_AFTER.match(after_core):
                anchor = None
                continue                                        # (e) an ORDINAL slot: '85th percentile'
            if dur_mod.match(after_core):
                anchor = None
                continue                                        # (f) a DURATION MODIFIER: '5-year mean'
            # D-EC PRE-ARM (h) -- the LENGTH of the observation window a statistic is read against. Three
            # shapes, and (h-ii) is the only rule here besides (g) with a LEFT context: see the block note
            # for the measured 5-of-15 false-positive class and for the eight head-position
            # counter-examples the left context keeps as claims. (h-iii) is the round-2 docket's `of`
            # spelling ("vs 120 points of its own history", "the newest of 53 rows covering ...").
            if (_WINDOW_HYPH.match(after_core) or _WINDOW_OF.match(after_core)
                    or (win_tail.match(after_core) and _WINDOW_LEAD.search(s[:m.start()]))):
                anchor = None
                continue                                        # (h) a WINDOW LENGTH: 'sigma on 120 months'
        # 09-23 (C6, V-7): the year rule's unit tell is HEAD's rule (a) (`_UNIT_AFTER`) PLUS the sentence's
        # OWN served-row units at a charge site -- "net long 1992 contracts [N37]" is a claim in the row's
        # own unit.
        _unit_after = _UNIT_AFTER.match(s[m.end():]) or (g is not None and g.row_after is not None
                                                         and g.row_after.match(s[m.end():]))
        if (re.fullmatch(r"\d{4}", core) and 1900 <= v <= 2099
                and not _unit_after):                           # (a) year -- unless unit-suffixed
            anchor = None
            continue
        if re.fullmatch(r"\d{1,2}", core):
            before, after = s[:m.start()], s[m.end():]
            if _RANGE_TAIL.search(before):
                anchor = None
                continue                                        # (b) year-range SHORT tail only
            if (_DATE_DAY_TAIL.search(before) or _MONTH_BEFORE.search(before)
                    or (_MONTH_AFTER.match(after) and not _UNIT_AFTER.match(after))):
                anchor = None
                continue                                        # (d) the DAY of a date
        out.append((m.start(), m.start() + len(core), v))
        anchor = m.start() + len(core)
        # 09-23 (C6) RULE (i) -- a numeral INSIDE a declared unit phrase that directly follows this
        # accepted figure is the phrase's, never a claim ("3.6 million 480 pound bales"). The run is
        # consumed whole and never anchors, exactly like a rule-(g) label.
        if g is not None and g.prefixes:
            _run_end = _phrase_run(s, anchor, g)
            if _run_end > anchor:
                skip_until = _run_end
                anchor = None
    return out, scales


def _claim_numbers_in(s: str) -> list[float]:
    """The claim magnitudes, values only -- the historical extractor, now a thin view on the span core."""
    return [v for _a, _b, v in _claim_number_spans(s)]


def _token_decimals(tok: str) -> int:
    """CYCLE-6 (2026-08-08): decimal places the prose ACTUALLY WROTE for one claim token. '15.17' -> 2,
    '-0.20' -> 2 (the trailing zero is written precision, not noise), '446' -> 0, '1,486,837' -> 0.
    Load-bearing that this reads the TOKEN and not the parsed float: float('0.20') is 0.2 and a float
    cannot remember how many places its author committed to, which is the whole quantity the reader-
    precision arm in `_num_matches` needs."""
    core = (tok or "").rstrip(".,")
    return len(core.split(".", 1)[1]) if "." in core else 0


def _claim_numbers_with_decimals(s: str) -> tuple[list[float], list[int]]:
    """The claim magnitudes AND, positionally parallel, the decimal places each was written to. Two lists
    rather than a list of pairs so every existing `_claim_numbers_in` call site keeps its exact shape and
    only the two matchers that need the precision take the second list."""
    spans = _claim_number_spans(s)
    return ([v for _a, _b, v in spans], [_token_decimals((s or "")[a:b]) for a, b, _v in spans])


def _mask_handles(s: str) -> str:
    """Blank every citation handle to SPACES of its own length. The callers that only need the VALUES use
    _HANDLE.sub("", ...), but a repair needs the numeral's position in the sentence AS WRITTEN, so the
    handle digits have to stop being claim numbers without any offset moving."""
    return _HANDLE.sub(lambda m: " " * (m.end() - m.start()), s or "")


def _stripped_offsets(sent: str) -> list:
    """Index map from `_HANDLE.sub("", sent)` back into `sent` (one entry per stripped character, plus the
    end), so a span the handle-stripped extraction found is the same span in the sentence AS WRITTEN."""
    out: list = []
    last = 0
    for m in _HANDLE.finditer(sent or ""):
        out.extend(range(last, m.start()))
        last = m.end()
    out.extend(range(last, len(sent or "")))
    out.append(len(sent or ""))
    return out


def _row_vals(call: dict) -> list[float]:
    """Every parseable row value on ONE call record."""
    out = []
    for r in ((call or {}).get("rows") or []):
        try:
            out.append(float(str(r.get("value")).replace(",", "")))
        except (TypeError, ValueError):
            continue
    return out


def _mismatch_pool(call: dict, row_vals: list[float]) -> list[float]:
    """What a cited [N] figure is checked AGAINST: the magnitudes the panel LINE printed, when the engine
    recorded them (cascade._shown), else every row on the call.

    W4 A/B RCA (2026-08-01): pooling all rows was the hole. A cascade era-window call carries the WHOLE
    window -- a Jan-Jun ONI leg holds ~6 monthly rows -- while its rendered line prints ONE endpoint, so a
    prose figure matching ANY member row cleared. Jan-2012 ONI is ~-0.72; the model quoted member rows
    (-0.693675 is a real row value, not an invention) and narrated them as the window's headline stat, and
    all four measured fabrications on pb_seasonality_aware were never charged at all. Binding the check to
    the SHOWN value is the fix: what the reader was given is what a citation may claim.
    GRAPHRAG_VERIFY_NUM_POOL=all restores the all-rows pool exactly; anything else, unset included, is
    shown-when-present. The fallback keeps agent-lane calls and legacy fixtures (no `shown` key) working."""
    if os.environ.get("GRAPHRAG_VERIFY_NUM_POOL", "") == "all":
        return row_vals
    shown = []
    for v in ((call or {}).get("shown") or []):
        try:
            shown.append(float(str(v).replace(",", "")))
        except (TypeError, ValueError):
            continue
    return shown or row_vals


# ══ 09-23 FIX ROUND (lane V, BRIEF item 1, CONTRACT C4) -- THE SERVED-SCALARS POOL ════════════════════
# THE MEASURED DEFECT (09-23 re-smoke): every figure the BOARD printed in words or digits and minted no call
# for was, to this module, a figure nobody served. The board prints a chain hop's window PEAK ("peaked at
# the ninety-eighth percentile in April 2026"), a row's percentile beside its LEVEL handle, a run length, a
# card threshold; the writer re-digitises what it read, and the verifier then (i) killed the soyoil/palm
# TL;DR's relative-value call because "94th" and "1st" -- the palm-stocks and soyoil-S/U percentiles, both
# printed on the board -- had no cited backer, (ii) struck the max turn's crush hop because "96th" (the
# crush window peak, 95.6) matched no row, and (iii) cut "98th"/"96th" peaks to "a level this page could
# not back" on three pages. 0 of the writer's figures were wrong.
# THE FIX IS THE BOARD'S OWN RECORD OF WHAT IT PRINTED, never a list of "board words". `Block.scalar`
# registers each figure AT THE MOMENT the template formats it (lane R); the seam hands the list over only
# when the block rendered; answer threads it here as `served_scalars` (None on every board-off turn, so
# this arm is inert there by construction).
# THE RULES ARE BINDING-SCOPED (fix-round review FATAL-4). The first cut asked "does the SENTENCE cite a
# handle of this row?", so in a two-row chain sentence one row's printed figure backed a numeral the writer
# had put in the OTHER row's clause ("the second sits at the 99th percentile [N3]" backed by the first
# link's window peak), a run length backed its neighbour row's duration, and an analog's outcome move
# backed any percent on the page. A numeral now reaches the pool ONLY through the handle group it BINDS TO
# (`_bind`, the one attribution this module reads -- "figure [N]" adjacency first), and:
#   (1) EVERY scalar that carries a `row_id` is ROW-BEARING: it backs a numeral only when the group that
#       numeral binds to cites a call of the SAME `_row_id`. Where the writer ADDRESSED the figure -- wrote
#       it straight into a handle -- only what that ADDRESS printed can back it: a handled scalar only
#       through its own handle, a handle-less one only when it is a row COUNT the row prints with no handle
#       of its own (run length, window length; `_ROW_COUNT_KINDS`). The match is the scale-1 backstop's
#       own (`_num_backed`, reader precision included) and the unit the writer wrote must be the scalar's.
#   (2) A HANDLED scalar with no row (an outcome move) backs only through its own handle.
#   (3) A scalar with neither (a lag band, a firing count, a card threshold) backs a numeral ONLY when the
#       numeral's OWN unit tail is the scalar's unit ("8 quarters" against a band of eight quarters).
#   (4) Pool backing counts ONLY for the `number_unbacked` backstop and the every-numeral sibling rescue
#       (and so, by the same token, a pool-backed figure is never cut by the orphan ladder). It never
#       creates a charge and never removes a handle by itself; the `number_mismatch` headline check -- does
#       the CITED handle back a figure in its sentence -- never reads it.
_ROW_SCALAR_KINDS: tuple = ("level", "sigma", "percentile", "window_peak_percentile", "current_level")
#: The row facts a board line prints WITHOUT a handle of their own (C4): a writer can only cite them
#: through the row's handles, so an addressed figure may be one of them.
_ROW_COUNT_KINDS: tuple = ("run_length", "window_length")
_POOL_KINDS_FALLBACK: tuple = _ROW_SCALAR_KINDS + ("window_length", "run_length", "lag_band_quarters",
                                                   "firings_count", "firings_aligned", "card_threshold",
                                                   "outcome_move")


def _scalar_kinds() -> tuple:
    """`rows.SCALAR_KINDS` (lane R, CONTRACT C4) -- the pool's closed kind roster; the contract's spelling
    when the leaf does not carry it yet. A scalar of any other kind backs nothing."""
    try:
        from leviathan.graphrag.state import rows as _rows
        k = getattr(_rows, "SCALAR_KINDS", None)
        if isinstance(k, tuple) and k:
            return k
    except Exception:  # noqa: BLE001 -- an unreadable leaf falls back to the contract's own spelling
        pass
    return _POOL_KINDS_FALLBACK


def _pool_entries(served_scalars) -> tuple:
    """The pool as (value, unit tokens, kind, row_id, handle) tuples; malformed entries dropped."""
    if not served_scalars:
        return ()
    kinds = set(_scalar_kinds())
    out = []
    for sc in served_scalars:
        if not isinstance(sc, dict):
            continue
        kind = str(sc.get("kind") or "")
        if kind not in kinds:
            continue
        try:
            val = float(sc.get("value"))
        except (TypeError, ValueError):
            continue
        if val != val:
            continue
        rid = sc.get("row_id")
        try:
            hd = int(sc.get("handle")) if sc.get("handle") else None
        except (TypeError, ValueError):
            hd = None
        if kind == "outcome_move" and not hd:
            continue                              # an outcome move is minted WITH its call (C4): no handle, no backing
        out.append((val, _unit_tokens(sc.get("unit") or ""), kind, str(rid) if rid else "", hd))
    return tuple(out)


def _unit_tail_is(s: str, b: int, utoks: tuple, g=None) -> bool:
    """Does the text directly after the numeral ending at `b` spell `utoks` (a scalar's unit)? Token for
    token, or -- through the declared vocabulary -- a spelling of the same declared unit (`_unit_equal`).
    Blanks only in between, or nothing ("3.2%")."""
    if not utoks:
        return False
    if re.match(r"(?:st|nd|rd|th)\b", s[b:b + 3] or ""):
        b += 2                                        # an ordinal suffix is the numeral's own
    pos, i = b, 0
    for m in _UNIT_TOKEN_RX.finditer(s, b):
        if s[pos:m.start()].strip():
            break
        t = m.group().lower().strip(_UNIT_PUNCT).rstrip(".").strip(_UNIT_PUNCT)
        if t != utoks[i]:
            break
        i, pos = i + 1, m.end()
        if i == len(utoks):
            return True
    return _unit_equal(_unit_written_at(s, b, g), utoks)


class _VCtx:
    """One `verify_citations` run's charge-site context: the calls, the served-scalars pool, the
    per-sentence declared unit grammar and the per-sentence BINDING (both memoised on the sentence). Every
    charge-site predicate takes it as an optional keyword, so a caller that passes nothing (a deck, a
    grader's repro) gets the same vocabulary with no pool -- the board-off reading."""

    __slots__ = ("calls", "pool", "_g", "_b", "pool_hits")

    def __init__(self, number_calls, served_scalars=None):
        self.calls = number_calls or []
        self.pool = _pool_entries(served_scalars)
        self._g: dict = {}
        self._b: dict = {}
        self.pool_hits: set = set()

    def grammar(self, sent: str) -> _UnitGrammar:
        idx = tuple(_cited_number_idx(sent, self.calls))
        g = self._g.get(idx)
        if g is None:
            rows = _row_unit_strings(self.calls, idx)
            g = self._g[idx] = _unit_grammar(_unit_phrases_for(sent, self.calls, list(idx)), rows)
        return g

    def binding(self, sent: str) -> tuple:
        """(groups, figures, {group index: [figure + (how,)]}) for `sent` -- `_bind`'s one reading."""
        b = self._b.get(sent)
        if b is None:
            groups = _handle_groups(sent)
            masked = _mask_handles(sent)
            g = self.grammar(sent)
            figs = _written_figures(masked, g)
            b = self._b[sent] = (groups, figs, _bind(sent, groups, figs, self.calls, g))
        return b

    def pool_backs(self, sent: str, a: int, b: int, v: float, dec, key=None, count: bool = True,
                   rowed_only: bool = False) -> bool:
        """C4 rules (1)-(3) for ONE numeral at `sent[a:b]` (offsets into the sentence AS WRITTEN, handles
        included -- `_mask_handles` keeps every offset). `key` names the sentence so a figure the pool
        alone backs is counted once (`pool_backed`)."""
        if not self.pool:
            return False
        groups, _figs, bound = self.binding(sent)
        where = next(((gi, f[5]) for gi, fs in bound.items() for f in fs if f[0] == a and f[1] == b), None)
        members: set = set()
        rids: set = set()
        how = "loose"
        if where is not None:
            gi, how = where
            for m in groups[gi]:
                for kind, j in _handle_members(m.group(0)):
                    if kind == "N" and 1 <= j <= len(self.calls):
                        members.add(j)
                        rid = (self.calls[j - 1] or {}).get("_row_id")
                        if rid:
                            rids.add(str(rid))
        masked = _mask_handles(sent)
        g = self.grammar(sent)
        written = _unit_written_at(masked, b, g)
        for val, utoks, kind, rid, hd in self.pool:
            if rid:
                if rid not in rids:
                    continue
                if how == "adjacent" and not (hd in members if hd else kind in _ROW_COUNT_KINDS):
                    continue                      # an ADDRESSED figure: only what that address printed
                if kind in _ROW_COUNT_KINDS:
                    ok = bool(written) and _unit_equal(written, utoks) and _num_matches([v], [val], [dec])
                else:
                    ok = (_num_backed(v, [val], dec=dec)
                          and (not written or not utoks or _unit_equal(written, utoks)))
            elif hd:
                ok = (hd in members and _num_backed(v, [val], dec=dec)
                      and (not written or not utoks or _unit_equal(written, utoks)))
            elif rowed_only:
                continue                          # a row-less scalar is nobody's row: it backs no ADDRESS
            else:
                ok = _unit_tail_is(masked, b, utoks, g) and _num_matches([v], [val], [dec])
            if ok:
                if count:
                    self.pool_hits.add((key, a, v))
                return True
        return False


def _unit_written_at(s: str, b: int, g) -> tuple:
    """The DECLARED unit the text right after the numeral ending at `b` spells (its ordinal suffix skipped,
    one declared scale word allowed in front -- "622.69 thousand MT"), as normalised tokens: the longest
    phrase of the sentence's grammar (cards, their declared spellings, the cited rows' own units) written
    token for token from its start -- or () when it spells none."""
    if re.match(r"(?:st|nd|rd|th)\b", s[b:b + 3] or ""):
        b += 2
    toks: list = []
    start = None
    for m in _UNIT_TOKEN_RX.finditer(s, b):
        if start is None:
            if s[b:m.start()].strip():
                return ()
            start = m.start()
        elif s[toks[-1][1]:m.start()].strip() or len(toks) >= 8:
            break
        raw = m.group()
        core = raw.rstrip(".,;:)]*").rstrip(".")
        t = core.lower().strip(_UNIT_PUNCT)
        if not t:
            break
        toks.append((t, m.end()))
        if core != raw:
            break
    if not toks:
        return ()
    words = [t for t, _e in toks]
    phrases = list(getattr(g, "phrases", ()) or ()) or list(_declared_vocab().phrases)
    scales = _declared_vocab().scales
    best: tuple = ()
    for off in ((0, 1) if len(words) > 1 and words[0] in scales else (0,)):
        w = words[off:]
        for p in phrases:
            k = len(p)
            if k <= len(w) and tuple(w[:k]) == tuple(p) and off + k > len(best):
                best = tuple(words[:off]) + tuple(p)  # the scale word is part of the unit written ("m ha")
        if best:
            break
    return best


def _unit_tail_end(s: str, b: int, g, extra=()) -> int:
    """Where the figure ending at `b` stops wearing its own unit: past its ordinal suffix and a glued '%',
    then past one declared scale word and the longest declared unit phrase written there (the sentence's
    grammar plus `extra` phrases -- the units of the rows the caller is asking about)."""
    o = re.match(r"(?:st|nd|rd|th)\b", s[b:])
    if o:
        b += o.end()
    if s[b:b + 1] == "%":
        b += 1
    toks: list = []
    for m in _UNIT_TOKEN_RX.finditer(s, b):
        gap = s[(toks[-1][1] if toks else b):m.start()]
        if gap.strip() or "\n" in gap or len(toks) >= 8:
            break
        raw = m.group()
        core = raw.rstrip(".,;:)]*").rstrip(".")
        t = core.lower().strip(_UNIT_PUNCT)
        if not t:
            break
        toks.append((t, m.start() + len(core)))
        if core != raw:
            break
    if not toks:
        return b
    words = [t for t, _e in toks]
    phrases = set(getattr(g, "phrases", ()) or ()) | {tuple(p) for p in extra if p}
    if not phrases:
        phrases = set(_declared_vocab().phrases)
    scales = _declared_vocab().scales
    best = b
    for off in ((0, 1) if len(words) > 1 and words[0] in scales else (0,)):
        w = words[off:]
        for p in phrases:
            k = len(p)
            if 0 < k <= len(w) and tuple(w[:k]) == tuple(p):
                best = max(best, toks[off + k - 1][1])
    return best


def _ctx_of(ctx, number_calls) -> _VCtx:
    return ctx if isinstance(ctx, _VCtx) else _VCtx(number_calls)


# ── THE CITED ROW'S OWN ORDINAL (09-23, lane V) -- the headline check reads what the extractor exempts ──
# MEASURED on three 09-23 pages: "at the 92nd [N33]" (max crush), "now reads 2.6 USD/bu [N42], the 92nd
# [N44]" (deep crush), "feed at the 95th [N39]" (corn/wheat) -- each handle is a PERCENTILE call and the
# ordinal touching it IS its row's value, but cycle-8 rule (e) exempts a bare ordinal ("no percentile word
# follows") as a POSITION, so the handle's own figure was invisible to the charge and the handle was
# convicted by its NEIGHBOURS' numerals. Rule (e) cannot know better -- it is a pure function of the
# sentence. The charge site can: the cited call's served rows declare their unit, and when that unit is the
# percentile family (`_PCTILE_WORD`, the extractor's own grammar, read against the ROW's unit string, never
# the prose's words), an ordinal written DIRECTLY before the handle whose value is in the handle's pool is
# that handle's figure. It can only ever turn a `number_mismatch` into no charge; the extractor, the
# number_unbacked backstop and the cycle-8 frozen view do not move.
_PCTILE_UNIT_RX = re.compile(r"\A" + _PCTILE_WORD + r"s?\b", re.I)
_ORDINAL_BEFORE_RX = re.compile(r"(?<![A-Za-z0-9.,])(\d+(?:\.\d+)?)(?:st|nd|rd|th)\s*\Z", re.I)


def _percentile_call(call: dict) -> bool:
    rows = (call or {}).get("rows") or []
    return bool(rows) and all(_PCTILE_UNIT_RX.match(str((r or {}).get("unit") or "").strip())
                              for r in rows)


def _unbound_handle(sent: str, idx: int, number_calls: list, ctx) -> bool:
    """09-23 (lane V) -- A HANDLE THAT BINDS NO FIGURE MAKES NO NUMERIC CLAIM, SO NO FIGURE CAN CONTRADICT IT.

    THE MEASURED CLASS (09-16 class (a), still the largest on 09-23 by the fact graders' strike tables): a
    handle cited for WORDS -- "in the top decile of that record [N47]", "the lagging export pace [N66]",
    "essentially flat over twenty-one sessions [N66]", "two standard deviations above its ten-year window
    [N13]", "the crush link into meal held [N67]" -- convicted of `number_mismatch` by numerals that belong
    to OTHER handles in the same sentence, each of them backed by its own. The sibling rescue then keeps the
    sentence and DROPS the handle, so a correct citation leaves the page.
    THE BINDING IS THE ESTATE'S OWN "figure [N]" CONVENTION, READ STRUCTURALLY (`_bind`; fix-round review
    FATAL-2): a figure whose own unit runs straight into a handle group IS that group's claim, whatever its
    neighbours back -- "China imports 118 MMT [N2]" is [N2]'s claim even where [N1] carries 118. [N`idx`]
    is unbound only when ALL of:
      (i)  no figure is bound to its group that [N`idx`] itself -- or a group member of the SAME ROW
           IDENTITY (one `_row_id`, C3) -- does not back; an ADDRESSED ordinal ("the 2nd percentile [N9]")
           counts as the group's figure like any claim;
      (i-b) no claim figure written INSIDE its window (from the previous handle group to it -- the clause
           the handle closes) was handed to ANOTHER group only because that group's row carries the same
           value (`_bind`'s "backed") -- so "118 MMT too [N2]" cannot be handed to the [N1] before it because
           [N1] happens to carry 118; a figure bound elsewhere by structure (adjacency, its written unit,
           its clause segment) is that group's, not this one's;
      (ii) EVERY claim numeral in the sentence is backed by a member of the group it binds to.
    (ii) is the fail-closed guard; (i) and (i-b) are what make it test the RIGHT group. Without `_row_id`
    (every board-off call) (i) reduces to "no figure binds to it at all". Words stay free, exactly as in a
    digit-free sentence; the `number_unbacked` backstop still runs on every numeral."""
    ctx = _ctx_of(ctx, number_calls)
    groups, figs, bound = ctx.binding(sent)
    if not groups:
        return False
    mine = [gi for gi, grp in enumerate(groups)
            if any(("N", idx) in _handle_members(m.group(0)) for m in grp)]
    if not mine:
        return False
    rid = str((number_calls[idx - 1] or {}).get("_row_id") or "")
    own_pool = _mismatch_pool(number_calls[idx - 1], _row_vals(number_calls[idx - 1]))
    for gi in mine:
        same = [own_pool]
        if rid:
            for m in groups[gi]:
                for kind, j in _handle_members(m.group(0)):
                    if (kind == "N" and j != idx and 1 <= j <= len(number_calls)
                            and str((number_calls[j - 1] or {}).get("_row_id") or "") == rid):
                        same.append(_mismatch_pool(number_calls[j - 1], _row_vals(number_calls[j - 1])))
        for _a, _b, v, d, kind, how in bound.get(gi) or []:
            if kind != "claim" and how != "adjacent":
                continue
            if rid and any(_num_matches([v], pool, [d]) for pool in same):
                continue
            # the ROW's own printed figure (C4, binding-scoped: an ADDRESSED figure only through what that
            # address printed) -- "drought [N42] peaked at the 99th percentile" is the drought row's peak
            if rid and ctx.pool and ctx.pool_backs(sent, _a, _b, v, d, count=False, rowed_only=True):
                continue
            return False
        # (i-b) the claims INSIDE this group's window that `_bind` handed elsewhere only because that other
        # group's row happens to carry the same value ("backed") -- a coincidence of value, never a structure
        w0 = groups[gi - 1][-1].end() if gi > 0 else 0
        w1 = groups[gi][0].start()
        for ogi, fs in bound.items():
            if ogi == gi:
                continue
            for a, b, v, d, kind, how in fs:
                if kind == "claim" and how == "backed" and w0 <= a and b <= w1:
                    if not any(_num_matches([v], pool, [d]) for pool in same):
                        return False
    for gi, fs in bound.items():
        pools = []
        for m in groups[gi]:
            for kind, j in _handle_members(m.group(0)):
                if kind == "N" and 1 <= j <= len(number_calls):
                    pools.append(_mismatch_pool(number_calls[j - 1], _row_vals(number_calls[j - 1])))
        for _a, _b, v, d, kind, _how in fs:
            if kind != "claim":
                continue
            if any(_num_matches([v], pool, [d]) for pool in pools):
                continue
            if ctx.pool and ctx.pool_backs(sent, _a, _b, v, d, count=False):
                continue                          # the bound group's ROW printed it (C4, binding-scoped)
            return False
    return True


def _own_ordinal(sent: str, idx: int, number_calls: list, pool: list) -> bool:
    """Is [N`idx`]'s own percentile written as the bare ordinal directly in front of it?"""
    if not pool or not (1 <= idx <= len(number_calls or ())) or not _percentile_call(number_calls[idx - 1]):
        return False
    for m in _HANDLE.finditer(sent or ""):
        if ("N", idx) not in _handle_members(m.group(0)):
            continue
        o = _ORDINAL_BEFORE_RX.search(sent[:m.start()])
        if o and _num_matches([float(o.group(1))], pool, [_token_decimals(o.group(1))]):
            return True
    return False


# CYCLE-10 (2026-08-08) -- THE REPAIR FENCES, DELETED WITH THE THING THEY FENCED.
# This span carried the entire rewrite guard: `_unit_class` / `_unit_class_lead` / `_registry_unit_class`
# / `_metric_tell_class` / `_call_unit_class` / `_sentence_unit_class` (the unit-class equality test FOR
# REPAIRS), `_NON_VALUE_SLOT`, `_PCT_METRIC`, `_REPAIR_MAG_RATIO_MAX`, `_LEAD_WINDOW`, `_PROSE_SIGN`,
# `_COND_CTX`, `_THRESHOLD_LEAD` and `_THRESHOLD_NOUN` -- the cycle-8 fences and the cycle-9 (a)-(e)
# allowlist clauses. Every one of them existed to answer 'may a row value be WRITTEN into this slot'.
# Nothing else in this module asked that question, and no other module imports any of them, so they are
# dead code the moment the rewrite is gone. They are REMOVED rather than kept 'in case': a loaded fence
# with no caller is the shape a future cycle re-arms by accident, which is precisely the failure the
# termination branch exists to make structurally impossible. The DURATION / ORDINAL exemptions live on
# in `_claim_number_spans` (cycle-8's charge-side amendment, untouched), and `_handle_members` /
# `_mask_handles` / `_reader_precision_match` stay because charging and the sibling rescue read them.


def _sibling_backed(sent: str, idx: int, number_calls: list[dict], *, ctx=None) -> bool:
    """True when EVERY claim numeral in the sentence is BACKED by some OTHER [N] handle written in that
    same sentence, against that handle's own mismatch pool.

    r5 RCA (2026-08-01). The verifier checks a handle against every numeral in its SENTENCE, so a handle
    cited for a qualitative clause is charged by a numeral it was never quoting: "the anomaly is at
    +0.98 degC and accelerating [N3] [N4]" charges [N4] (the +0.47 monthly step) because 0.98 is not 0.47.
    The fail-closed remedy then rewrote 0.98 -> 0.47 and left [N3] -- which DOES back 0.98 -- pointing at a
    figure that is no longer its own. Measured on both r5 renders: ol_cocoa_thin_record published
    "+0.47 degC ... [N3] [N4]" and ol_bait_bare_target_demanded published "+5 degC [N3]", the same [N3]
    contradicting itself across two rows of ONE deck.
    The number is NOT fabricated here -- a sibling handle materializes it -- so the fail-closed rationale
    ("a fabricated NUMBER survives the loss of its handle") does not apply, and the precise remedy is the
    ORIGINAL one: strip the mis-citing HANDLE and leave the corroborated figure standing.

    ══ D-EC PRE-ARM (2026-09-17) -- THE ONE-NUMERAL SCOPE IS LIFTED: EVERY NUMERAL, NOT EXACTLY ONE ═════
    THE MEASURED DEFECT (the in-VPC pre-arm smoke, 2026-09-16, five real-seat turns at commit 17fed3e4).
    The rescue opened `if len(spans) != 1: return False`, and the four sentences this smoke DELETED carry
    2, 2, 2 and 3 claim numerals -- so the rescue was unavailable by construction to every sentence rich
    enough to be worth keeping. All four are the SAME false-positive shape as the r5 one above: a handle
    cited for a WORDED restatement of its own row, convicted by its neighbours' digits.
        deep tldr   "... a slack export program in the bottom decile of its own record [N40] and US area
                     at 34.76 M ha [N59], and the ocean signal at +1.8 degC [N23] ..."
                    [N40] = 6 percentile, cited for the WORDS 'bottom decile'; 34.76 is [N59]'s own row
                    (34.755) and 1.8 is [N23]'s own row. The whole counter-leg of the TL;DR was deleted.
        corn/wheat  "The tight stocks-to-use ratio [N79], at the 16th percentile of its own record [N81]
                     ... and feed demand at the 95th percentile [N66] ..."   [N79] = the 0.121393 ratio,
                    cited for the WORDS; 16 is [N81]'s row and 95 is [N66]'s. Its deletion left the
                    lowercase orphan "... on confidence alone. planted area at the 98th percentile [N69]".
        palm/rape   "... record Black Sea seed [N5][N14] and softening crush [N11] both loosen -- with the
                     EU growing-season moisture reading, at -0.51 z [N32], 20th percentile [N31] ..."
                    three handles cited for WORDS, and 0.51/20 are [N32]'s (-0.505799) and [N31]'s rows.
        soyoil      "Indonesia's palm-belt drought reads 0.16 z [N62], +0.7 sigma [N63], and the ocean
                     index reads -0.39 degC [N71], on the cool side of its record [N73] ..."
                    [N73] cited for WORDS; every one of 0.16 / 0.7 / 0.39 is a sibling's own row.
    THE ORIGINAL SCOPING ARGUMENT NO LONGER APPLIES TO ITS OWN REMEDY. "With two numerals nobody can say
    which one the charged handle meant" was an argument about REWRITING a numeral -- the ambiguity mattered
    because the repair path had to choose a value to splice. CYCLE-10 deleted that path: the only remedy
    this rescue can reach is DROP THE HANDLE, which needs no such choice.
    THE FAIL-CLOSED RATIONALE IS PRESERVED EXACTLY, AND THAT IS WHY THE TEST IS *EVERY*: a figure may only
    lose its handle when the SENTENCE ITSELF still materializes it from another served row. If ANY claim
    numeral in the sentence is backed by no sibling, this returns False and the sentence dies whole, as
    today -- so a fabricated numeral can never ride out on a correct neighbour's rescue.
    THE COST, STATED: a sentence that attributes the RIGHT figures to the WRONG handles ("stocks 10.72%
    [N50], crush 2.6 [N47]") now keeps its figures and loses both handles, where it used to die. That is
    HEAD's own precedent, not a new doctrine -- the one-numeral arm already accepted it, and
    `number_unbacked` serves figures bare routinely (7 of them on two sentences in this same smoke)."""
    ctx = _ctx_of(ctx, number_calls)
    masked = _mask_handles(sent)
    # 09-23 (C6): the derived unit vocabulary -- the same extraction the charge site reads.
    spans = _claim_number_spans(masked, units=ctx.grammar(sent))
    if not spans:
        return False
    # CYCLE-9 (2026-08-08) AMENDMENT 3a: every MEMBER of every handle token, not just the solitary ones.
    # The gate-6 covenant corruption is exactly this loop failing to see [N5] inside `[N5, N10, N12]`.
    pools = []
    for m in _HANDLE.finditer(sent):
        for kind, j in _handle_members(m.group(0)):
            if kind != "N" or j == idx or not (1 <= j <= len(number_calls)):
                continue
            sib = number_calls[j - 1]
            pools.append(_mismatch_pool(sib, _row_vals(sib)))
    # 09-23 (C4 rule 3b): the served-scalars pool is a backer too -- a figure the BOARD printed, bound to
    # a row this sentence cites (rule 1) or to its own derived unit (rule 2). Absent pool: HEAD's test.
    if not pools and not ctx.pool:
        return False
    # CYCLE-6: the sibling rescue asks the SAME matching question, so it gets the same reader-precision arm
    # -- a sibling that backs "-0.31" against its own -0.30632 row is backing it, and refusing to see that
    # would send the sentence to the whole-drop path this rescue exists to avoid.
    for a, b, v in spans:
        dec = [_token_decimals(masked[a:b])]
        if any(_num_matches([v], pool, dec) for pool in pools):
            continue
        if ctx.pool and ctx.pool_backs(sent, a, b, v, dec[0], key=sent):
            continue
        return False
    return True


# ══ D-EC PRE-ARM, ROUND 2 (2026-09-17) -- A SENTENCE THIS MODULE KEEPS NEVER SERVES A FIGURE WITH
#    NOTHING BEHIND IT ══════════════════════════════════════════════════════════════════════════════
# THE MEASURED DEFECT (round-1 adversarial review, MAJOR-1, reproduced by this lane on the 112 banked
# answers). The round-1 orphan lint refuses a fail-closed whole-sentence drop and takes the handle
# instead -- and on a SINGLE-HANDLE sentence that handle is the only one there is, so all SEVEN
# sentences it saved shipped their figure with NO citation at all:
#     "- Canadian canola production was last read at 22,500,000 MT;"      (draft: "... MT [N14];")
#     "US soyoil ending stocks for MY2025 are 1,552,000 MT;"              "- Rapeseed oil: 18.75;"
#     "- Soybean oil stocks-to-use: 7 ratio on the newest reading;"       "- Soybean oil: 7;"
#     "The nearest served ending-stock rows are dated 2026-05-10 (palm 4,091,000 MT;"
#     "... the Chinese rapeseed-oil stocks-to-use read stands at 0.1036 against ... -0.0451033 ..."
# By this estate's own doctrine a served figure with no handle behind it is worse than a deleted one, so
# the lint bought a broken page off at the price of an uncheckable number. THE ORCHESTRATOR'S RULING
# (2026-09-17), implemented here in the order it states:
#   (1) THE LAST BACKER IS NEVER DROPPED. A charged handle whose pool is the only thing in the sentence
#       that materializes a printed numeral STAYS, whatever else it is charged for. This is the arm that
#       protects the widened sibling rescue from the cost its own build report stated ("a sentence that
#       attributes the RIGHT figures to the WRONG handles now keeps its figures and loses both handles").
#   (2) REPAIR, when the slot is unambiguous: substitute THE CITED HANDLE'S OWN ROW FIGURE at the page's
#       own precision and KEEP the handle, so the figure the reader sees is the row the handle carries.
#   (3) THE FIGURE CUT, when no row figure can be established for that slot: the FIGURE comes off and the
#       WORDS stay -- "was last read at a level this page could not back [N14]". Words are free; only a
#       printed figure must be backed, and a figure nothing can back must stop being printed.
# SCOPE, AND WHY IT IS NOT "EVERY number_mismatch". CYCLE-10 deleted the general rewrite after three
# recorded ops corrupted three sentences, and the dispositive one -- "roughly 0.6 z higher [N3]" against
# a -0.6267 row -- is a SINGLE-HANDLE number_mismatch, i.e. exactly what a general reading of (2) would
# rewrite. It is out of reach here twice over: this ladder is entered ONLY where the alternative is a cut
# that leaves wreckage (`_drop_orphans`), and inside it fences (d) and (f) below refuse that shape on its
# sign and on its own word "higher". `test_cycle10_no_rewrites` keeps every one of its pins.
# ROLLBACK: GRAPHRAG_VERIFY_ORPHAN_REPAIR=off disables (2) alone -- the figure cut then carries every
# slot, and no row value can reach the page by any route.
_FIGCUT_WORDS = "a level this page could not back"
# The unit tail a cut figure takes WITH it: "1,552,000 MT" -> "a level this page could not back", never
# "a level this page could not back MT". A closed vocabulary, read off the estate's own served units.
_FIGCUT_UNIT = (r"(?:%|percent(?:age[ ]points?)?|pp|bps?|MMT|MT|KT|kt|tonnes?|tons?|MMbu|bu|bushels?|"
                r"USD/bu|USD|EUR|cents?|ha|acres?|bales?|cwt|head|contracts?|lots?|z|sigma|"
                r"deg[ ]?C|ratio|index|points?|sessions?|days?|weeks?|months?|years?)")
_FIGCUT_SCALE = r"(?:MM|M|bn|k|K|thousand|million|billion)"
_FIGCUT_TAIL = re.compile(r"\A[ ]?(?:" + _FIGCUT_SCALE + r"[ ]+)?" + _FIGCUT_UNIT + r"(?![A-Za-z])")
# A sign or currency mark glued to the numeral goes with it ("of -0.0451033" must not leave "of -").
_FIGCUT_SIGN = "+-" + "\u2212" + "$"
# A comparative glued to the figure belongs to the figure: "roughly 0.6 z higher" must become "roughly a
# level this page could not back", never "roughly a level this page could not back higher". A closed set
# of one-word comparatives, taken only when it follows the unit immediately.
_FIGCUT_COMP = re.compile(r"\A[ ]+(?:higher|lower|above|below|more|less|up|down|wider|tighter|"
                          r"firmer|softer)\b", re.I)
# SCIENTIFIC NOTATION IS ONE LITERAL, AND IT COST A CORRUPTION TO LEARN IT. `_claim_number_spans` reads
# "-7.61887e-05" as TWO claim numerals (the mantissa and the exponent), and the first draft of this cut
# took them as two figures: the banked `v25_baseline_control/rv_beans_meal` line came back as
# "change a level this page could not backea level this page could not back [N20]". The exponent rides
# with its mantissa here, and the span merge below closes the same class for a RANGE ("0.11-0.12").
_FIGCUT_EXP = re.compile(r"\A[eE][-+" + "\u2212" + r"]?\d+")
# AN ORDINAL SUFFIX IS PART OF THE NUMERAL, AND LEAVING IT BEHIND WRITES INSIDE A WORD. ROUND-2
# REVIEW NEW-MAJOR-1, measured through the shipped `verify_citations`: `_claim_number_spans` ends a
# span at the token CORE by contract, so "the 93rd percentile" hands the cut the span "93" and the
# replacement words weld onto the live "rd" -- "the a level this page could not backrd percentile".
# Same class as the `backea level` exponent corruption, one spelling out, and the ordinal percentile
# is this estate's commonest claim shape (3.35% of writer-prose claim numerals; 2.8% of the ladder's
# own candidate population). Taken BEFORE the unit tail, so "93rd %" still takes its percent sign.
_FIGCUT_ORD = re.compile(r"\A(?:st|nd|rd|th)\b")
# A NUMERAL GLUED INTO A WORD IS A NAME, NOT A FIGURE, AND IS NEVER CUT. `_CLAIM_NUM` already refuses a
# numeral with a LETTER immediately in front of it, but not one behind a hyphen -- and the banked corpus
# writes "the tier-1 material", "COVID-19", "top-3", every one of them a claim numeral that no row can
# ever back. Cutting one would serve "the tier- a level this page could not back material". They are left
# exactly as the writer wrote them: the remedy below is for FIGURES, and this is a name.
_FIGCUT_COMPOUND = re.compile(r"[A-Za-z][-" + chr(0x2010) + chr(0x2011) + r"]\Z")
# A TRANSITIVE COMPARATIVE KEEPS ITS OBJECT. ROUND-2 REVIEW NEW-MAJOR-2: `_FIGCUT_COMP` above took a
# one-word comparative WHATEVER followed it, so verbatim writer prose came back stranded --
# "soyoil sits 1.31603 sigma above its five-year mean [N1]" served as "soyoil sits a level this page
# could not back its five-year mean [N1]", the direction word DELETED and its object left dangling.
# That is the fatal shape at word scale by this estate's own doctrine. The comparative rides with the
# figure only where nothing follows that it could govern -- a handle, punctuation, the end. Where a
# WORD follows, the comparative and its object stay and only the numeral is cut. This arm can only
# ever SHRINK the cut span, so it can mint no corruption of its own.
_FIGCUT_COMP_OBJ = re.compile(r"\A[ ]+[A-Za-z]")
# The words that mean the SLOT already carries the direction or the threshold, so a row value spliced into
# it says something the row does not (the gate-7 "roughly 0.6 z HIGHER [N3]" corruption, and the gate-6
# "rising toward the 1.5 degC THRESHOLD [N4]" one).
_FIGCUT_SLOT_STOP = re.compile(r"\b(?:higher|lower|above|below|under|over|more|less|up|down|toward|"
                               r"towards|threshold|exceed(?:s|ed|ing)?|cross(?:es|ed|ing)?|beyond|past|"
                               r"at[ ]least|at[ ]most|no[ ]more[ ]than|if|when|unless|should|would|"
                               r"were)\b", re.I)


def _figure_span(sent: str, a: int, b: int, *, units=None) -> tuple[int, int]:
    """The span a FIGURE CUT removes: the claim token, the sign or currency mark glued in front of it and
    the exponent, ORDINAL SUFFIX and scale+unit written after it -- plus a comparative that governs
    nothing. `_claim_number_spans` ends at the token CORE by contract, so the unit has to be taken here or
    the page keeps a bare 'MT', the ordinal suffix or the page is written inside a word."""
    while a > 0 and sent[a - 1] in _FIGCUT_SIGN and not (a > 1 and sent[a - 2].isdigit()):
        a -= 1
    e = _FIGCUT_EXP.match(sent[b:])
    if e:
        b += e.end()
    o = _FIGCUT_ORD.match(sent[b:])
    if o:                                                 # "93rd", never "93" and a live "rd"
        b += o.end()
    m = _FIGCUT_TAIL.match(sent[b:])
    # 09-23 (C6): `_FIGCUT_UNIT` is HEAD's FLOOR; a unit the cards or the cited rows DECLARE is taken too,
    # so the cut never leaves "a level this page could not back percentile" beside a percentile row.
    d = _declared_unit_tail(sent, b, units)
    if d and (not m or d > m.end()):
        b += d
    elif m:
        b += m.end()
    c = _FIGCUT_COMP.match(sent[b:])
    if c and _FIGCUT_COMP_OBJ.match(sent[b + c.end():]):
        c = None                                          # it governs an object; both stay
    return a, (b + c.end() if c else b)


def _declared_unit_tail(sent: str, b: int, units) -> int:
    """The length of the longest PRINTED unit phrase (`_UnitGrammar.printed`: the cards' and the cited rows'
    own unit strings, token for token) that the text after offset `b` spells -- blanks allowed between the
    figure and the unit, and the phrase's own trailing punctuation left in place. 0 when none, or when no
    grammar is given. The figure cut's reader: it takes the unit a reader saw printed, never a word only a
    declared spelling knows."""
    g = _as_grammar(units)
    if g is None or not g.printed:
        return 0
    lead = re.match(r"[ ]?", sent[b:])
    start = b + (lead.end() if lead else 0)
    toks: list[tuple[str, int]] = []
    for m in _UNIT_TOKEN_RX.finditer(sent, start):
        if len(toks) >= 8 or (not toks and m.start() != start) or (toks and "\n" in sent[toks[-1][1]:m.start()]):
            break
        raw = m.group()
        core = raw.rstrip(".,;:)]").rstrip(".")
        t = core.lower().strip(_UNIT_PUNCT)
        if not t:
            break
        toks.append((t, m.start() + len(core)))
        if core != raw:
            break
    best = 0
    for p in g.printed:
        k = len(p)
        if 0 < k <= len(toks) and tuple(t for t, _e in toks[:k]) == tuple(p):
            best = max(best, toks[k - 1][1] - b)
    return best


def _page_figure(tok: str, v: float) -> str:
    """`v`'s MAGNITUDE written at the precision -- and in the thousands spelling -- the page used for
    `tok`. The sign is NOT written: it stays the page's own character, which fence (d) has already made
    agree with the row."""
    out = ("%." + str(_token_decimals(tok)) + "f") % abs(v)
    if "," in tok:
        head, _dot, tail = out.partition(".")
        out = "{:,}".format(int(head)) + (("." + tail) if tail else "")
    return out


def _orphan_repair_figure(sent: str, a: int, b: int, pool: list[float]) -> str | None:
    """The row figure this slot may carry, written at the page's precision -- or None, and then the FIGURE
    CUT takes the slot instead. SIX FENCES, every one of them the answer to a RECORDED corruption:

      (a) SOLE ROW -- the cited handle's mismatch pool must hold exactly ONE distinct value at the page's
          own precision. A window call carrying six rows cannot say which one this slot meant, and
          choosing is what gate-6 COV1 did ("toward the 0 degC threshold" out of a multi-row call).
      (b) LIVE ROW -- neither side may be zero while the other is not. A 0/1 FLAG row wrote "is at 1 degC"
          over a correct 0.98 in gate-6 COV2, and 4 of the 7 measured orphan pools are all-zero rows.
      (c) SAME ORDER OF MAGNITUDE -- |row| and |page| within a factor of ten. This is what refuses the
          measured canola slot (22,500,000 written, a 300,000 row) and every scale confusion with it.
      (d) SAME SIGN -- the sign the page wrote must be the sign the row carries. The gate-7 op that ended
          the repair path spliced a -0.6267 row into a "+0.6" slot; it is refused here on this fence
          alone, before any word is read.
      (e) NOT A RANGE MEMBER -- a numeral glued to a dash or slash is half of a span, never a value.
      (f) NO DIRECTION OR THRESHOLD WORD ANYWHERE IN THE SENTENCE -- the cycle-10 verdict, taken whole: a
          fence over unit LABELS cannot see that the slot's own word already carries what the row's signed
          value carries again, so the shape is refused outright rather than fenced.
    The predicate is TOTAL and pure: it reads a sentence, a span and a list of floats, and returns a
    string or None. It never chooses a pool, never reads the environment and never writes."""
    tok = sent[a:b]
    if not pool:
        return None
    seen = {(v < 0, _page_figure(tok, v)) for v in pool}
    if len(seen) != 1:
        return None                                       # (a) the call cannot say which row this slot is
    v = pool[0]
    try:
        page = float(tok.replace(",", ""))
    except ValueError:
        return None
    if (v == 0) != (page == 0):
        return None                                       # (b) a flag row can never write over a reading
    if v and page and max(abs(v), abs(page)) > 10.0 * min(abs(v), abs(page)):
        return None                                       # (c) a scale apart is not a precision fix
    _dash = a > 0 and sent[a - 1] in "-" + "\u2212"
    _range_dash = _dash and a > 1 and sent[a - 2].isdigit()
    if (_dash and not _range_dash) != (v < 0):
        return None                                       # (d) the sign the page wrote is the page's claim
    if _range_dash or (a > 1 and sent[a - 1] in "/" + "\u2013\u2014") or re.match(r"\A[-/]\d", sent[b:]):
        return None                                       # (e) half of a range is not a value
    if _FIGCUT_EXP.match(sent[b:]) or (a > 1 and sent[a - 1] in "eE" and sent[a - 2].isdigit()):
        return None                                       # (e) ...and neither half of 7.6e-05 is one
    if _FIGCUT_SLOT_STOP.search(sent):
        return None                                       # (f) the slot's own words carry the direction
    return _page_figure(tok, v)


def _num_repair(sent: str, idx: int, number_calls: list[dict]) -> None:
    """ALWAYS None. CYCLE-10 (2026-08-08) -- THE TERMINATION BRANCH, EXECUTED: THIS MODULE NO LONGER
    REWRITES PROSE.

    This function used to return a sentence-relative (start, end, replacement) for a number_mismatch it
    judged unambiguously repairable, and PASS 2 spliced that replacement into the reader's page. The
    capability is gone, and so is the CALL: PASS 2 no longer asks. What is retained is the NAME, as an
    always-ineligible predicate, for one reason -- every cycle-4..9 pin interrogates the repair decision
    through it, and keeping one auditable "is this repairable? no, and here is why not" surface is worth
    more than deleting a symbol. Nothing in this module calls it; nothing outside this module may.

    WHY DELETION AND NOT ANOTHER FENCE. Gates 6 and 7 recorded three repair ops and all three corrupted a
    sentence. The third is dispositive: it passed all four clauses of the cycle-9 allowlist -- one solitary
    [N] handle, both unit classes KNOWN AND EQUAL, no threshold noun and no conditional lead, inside one
    order of magnitude with no contradicted sign -- and still turned a correct "roughly 0.6 z higher [N3]"
    into "roughly -0.6267 z higher [N3]". The slot's own word "higher" carried the direction the row's
    signed `*_pace_change` value carried again, and the clause that certified the splice compared unit
    LABELS (z == z), not quantities. No clause over labels can see that, so no fifth clause was admissible.

    THE REMEDY IS THE ONE THIS FUNCTION ALWAYS GAVE FOR AMBIGUITY, now given for everything: the sentence
    is dropped with its audit record and the reader loses a sentence instead of receiving a fabricated one.
    The CHARGE is untouched -- what is flagged number_mismatch is flagged exactly as before -- and the
    sibling-backed rescue still keeps a corroborated figure standing on its own handle.

    GRAPHRAG_VERIFY_NUM_MODE=handle remains the documented rollback to the handle-only strip. There is NO
    flag that restores a rewrite, deliberately: the code to perform one no longer exists."""
    return None


def _coalesce(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Absorb any drop span contained in a larger one and merge the overlaps. The historical
    `sorted(set(drops), reverse=True)` removal corrupted the text the moment two spans overlapped -- which a
    whole-sentence drop swallowing the handle drops inside it does by construction."""
    out: list[tuple[int, int]] = []
    for a, b in sorted(set(spans)):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


# CYCLE-6 REVIEW (2026-08-08), BLOCKER 3 + MAJOR 4 -- THE RELATIVE CEILING ON THE READER-PRECISION ARM.
# The arm shipped as a bare half-unit window, and at d=0 that is a FLAT +-0.5 with no relative floor at
# all. At the magnitudes this estate actually serves (stocks-to-use, z-scores, MMT, $/bu, pct-of-OI) that
# certifies tens-of-percent-wrong numbers as matches: prose "1" against a 1.49 row (33% off) cleared
# `_num_matches`, and `_num_backed(1.0, [0.51], dec=0)` -- the MERGED ALL-ROWS backstop -- returned True on
# a 96% error, widening the R4 cross-row mis-attribution surface rather than narrowing it. "strip -> keep
# only" is not a safety argument when the keep is a WRONG number: refusing those is what the verifier is
# for. It also inverted the precision incentive, certifying the vaguer spelling ("1") while stripping the
# precise one ("1.0") on the identical claim -- the instrument rewarding fewer significant figures.
# THE CEILING IS SIZED AGAINST THE TWO REAL GATE-3 ROWS, which is the whole defect this arm exists for:
#   -0.31 vs -0.30632  ->  1.20% relative   ADMITTED
#   -0.20 vs -0.19516  ->  2.42% relative   ADMITTED
#   1 vs 1.49 (33%), 1 vs 0.51 (96%), 2 vs 2.49 (20%), 0.3 vs 0.34 (11.8%)   ALL REFUSED
# 3% clears the real class with margin and refuses every adversarial one. The denominator is max(|a|,|b|)
# so the test is symmetric in the two magnitudes -- neither the prose nor the row gets to be the yardstick.
# The footer twin (`citations._EXTRA_REL_TOL`) stays TIGHTER at 0.5% and that difference is still the
# correction-(B) doctrine: this arm converts strip->keep, that one MINTS A LINE.
_READER_REL_CEILING = 0.03


def _reader_precision_match(a: float, b: float, d: int | None) -> bool:
    """CYCLE-6 (2026-08-08) THE ONE SANCTIONED AMENDMENT TO THE STRIP RULES. True when the prose magnitude
    `a` is a CORRECT ROUNDING of the row magnitude `b` at the precision the prose itself wrote (`d` decimal
    places, parsed from the matched token by `_token_decimals`). Both arguments are already MAGNITUDES
    (the callers pass abs()), matching this module's standing sign discipline.

    THE MEASURED DEFECT (gate-3 dcw_probe pass1, row `dcw_gas_nitrogen_squeeze` -- reproduced exactly).
    The mechanism sentence "The most recent observed read on EU gas is 15.17 USD/mmbtu [N1] [N5], sitting
    at -0.31 sigma versus its five-year mean [N2]" was charged number_mismatch on [N2] and number_unbacked
    on [N1] and [N5], and the whole sentence went -- taking the ONLY marker-bearing statement of a SERVED
    row with it. Every figure in it was right. The arithmetic:
        row  silver_pink_sheet.natural_gas_eu_usd_mmbtu_zscore_5yr = -0.3063197017144927
        prose                                                        -0.31          (a correct 2-dp round)
        |0.31 - 0.30632| = 0.00368   >   0.01 * 0.30632 = 0.00306   -> `_num_matches` says NO
                                     >   0.01 * 0.31    = 0.00310   -> the reverse arm says NO too
    The identical shape strips the urea leg of the same answer: row -0.19515863509764528, prose "-0.20",
    |0.2 - 0.195159| = 0.00484 > 0.01 * 0.195159 = 0.00195. A RELATIVE tolerance is the wrong instrument
    for a value the reader rounded: at |x| ~ 0.3 a 2-dp restatement can be off by up to 0.005 in ABSOLUTE
    terms, which is 1.6% relative -- so the tighter the row's magnitude, the more certainly a CORRECT
    rounding fails. Nothing about the 1% arms is wrong for their own question; they simply cannot see this
    one, and the remedy is an ADDITIONAL arm, never a loosened one.

    THE TEST IS "a IS b ROUNDED TO d PLACES", stated as the half-unit-in-the-last-written-place window
    (|b - a| <= 0.5 * 10**-d). That is the definition of a correct rounding and it is float-robust, where
    `round(b, d) == a` is not: round() is half-to-EVEN and carries binary-representation artifacts at the
    tie, so it would arbitrarily reject one of the two defensible renderings of an exact .5 boundary
    (row -0.315 -> a reader may honestly write -0.31 or -0.32). Both are accepted here; nothing else is.

    IT CAN ONLY EVER CONVERT strip -> keep, and it is ROUNDING, NEVER BINNING:
        d=2  "-0.31" vs -0.30632  ->  0.00368 <= 0.005   MATCH
        d=2  "-0.32" vs -0.30632  ->  0.01368 >  0.005   NO MATCH
        d=1  "4.2"   vs  4.24     ->  0.04    <= 0.05    MATCH  (a 1-dp restatement of a 2-dp figure is a
                                                                 correct rounding -- allowed, by policy)
        d=0  "446"   vs  445.6    ->  0.4     <= 0.5     MATCH
        d=0  "400"   vs  446      ->  46      >  0.5     NO MATCH  (the binning refusal)
    SCALE 1 ONLY, deliberately: the multi-scale arms answer "is this the same quantity in other units",
    and a rescale bridge stacked on a rounding window would admit a value the reader never wrote.
    ZERO POLICY (as shipped at cycle 6, amended 09-23 below): the callers' `a == 0 or b == 0` guard runs
    FIRST, and a prose "0" can never round-rescue a 0.4 row. `d is None` -> the arm is absent entirely,
    which is what keeps every caller that does not thread decimals byte-identical.

    CYCLE-6 REVIEW (2026-08-08): the window is now ALSO fenced by `_READER_REL_CEILING` (see the constant).
    "a is b rounded to d places" AND "a and b are the same number to within 3%" -- both, always. The pinned
    behaviour above is unchanged (every one of those pairs is inside 3%); what the ceiling removes is the
    d=0 flat-window class, where a vague spelling could certify an arbitrarily wrong small magnitude.

    09-23 FIX ROUND (lane V, BRIEF item 5, THREAT_MODEL V-6) -- A ZERO THE WRITER WROTE AT A KNOWN
    PRECISION REACHES THIS ARM. MEASURED on the cocoa turn: the board printed West Africa's drought z of
    0.000885 as "0 z" (it rounds to zero at every precision a reader uses), the writer copied "0 z [N26]",
    and the zero arm above -- "0 matches only 0" -- charged number_mismatch twice: one clause deleted with
    its 55th-percentile neighbour, one figure cut to "a level this page could not back" beside a footer
    that prints [N26] = 0.00088532 z. A written "0" IS the row rounded to the precision the prose wrote, so
    it is admitted by the SAME two tests every other claim takes: (1) a correct rounding, |row| <=
    0.5 x 10^-d; (2) the cycle-6 ceiling, which for a zero cannot be taken against the claim's own
    magnitude (every non-zero row is 100% away from 0), so it is taken against the only scale a zero has --
    one unit in the last place the writer wrote: |row| <= 3% x 10^-d. Measured consequences, all pinned:
    "0 z" at 0 dp backs the cocoa 0.000885 row; "0" against a 0.4 row is STILL refused (the cycle-6
    deck's own pin: a vague zero never round-rescues a 0.4 row); "0 [N]" against 0.6 still charged; "0.0"
    against 0.06 still charged; a claim with no known written precision (`d is None`) still reads "0
    matches only 0". The ESR zero-aggregate path (a 0 claim against a 0.0 row) is the callers' own branch,
    untouched. A NON-zero claim against a zero row stays refused (a prose "0.004" never rounds onto 0.0)."""
    if d is None or b == 0:
        return False
    if a == 0:
        unit = 10.0 ** (-d)
        return abs(b) <= 0.5 * unit and abs(b) <= _READER_REL_CEILING * unit
    return (abs(b - a) <= 0.5 * 10.0 ** (-d)
            and abs(b - a) <= _READER_REL_CEILING * max(abs(a), abs(b)))


def _num_matches(sent_nums: list[float], row_vals: list[float],
                 sent_decs: list[int] | None = None) -> bool:
    """'31.4 million' vs 31400000, '36.4%' vs 0.3636: equal within 1% at any common reporting scale.
    MAGNITUDE-insensitive to sign: _NUM cannot extract a minus from prose ('fell 5.058 MMT' reads 5.058)
    while injected delta/pct rows are SIGNED (-5.058) -- direction lives in the prose verb, magnitude
    backing is this check's job (Stage-1 RCA: every narrated DECLINE stripped deterministically).
    CYCLE-6: `sent_decs` (positionally parallel to `sent_nums`, from `_claim_numbers_with_decimals`) arms
    the reader-precision arm below. Omitted -> the predicate is exactly the pre-CYCLE-6 one."""
    for k, a0 in enumerate(sent_nums):
        a = abs(a0)
        d = sent_decs[k] if (sent_decs is not None and k < len(sent_decs)) else None
        for b0 in row_vals:
            b = abs(b0)
            if a == 0 or b == 0:
                # T2b Lane-B RCA: ZERO had no match arm at all. Both scale tests are guarded by a
                # truthiness check (`if b and ...` / `if a and ...`) that a 0 row -- or a 0 claim --
                # falls straight through, so "weekly export pace is 0 [N2]" citing a row whose value IS
                # 0.0 was charged number_mismatch. This is the exact case the pattern-records F8 doctrine
                # is built on (a materialized citable 0 = "no firing recorded"), and the ESR pace rows in
                # the T2b deck are literally 0.0. _num_backed already encodes the rule -- 0 matches only
                # 0 -- so mirror it here rather than let a legitimate zero citation strip.
                if a == 0 and b == 0:
                    return True
                if a == 0 and _reader_precision_match(a, b, d):   # 09-23 V-6: "0" at a known precision
                    return True
                continue
            for scale in (1.0, 1e2, 1e3, 1e6, 1e9):
                if abs(a * scale - b) <= 0.01 * b:
                    return True
                if abs(b * scale - a) <= 0.01 * a:
                    return True
            if _reader_precision_match(a, b, d):       # CYCLE-6: correct at the reader's own precision
                return True
    return False


def _unbacked_quote(sent: str, pools: list[list[dict]]) -> str | None:
    """The first quoted span in `sent` that NO pool carries verbatim, or None -- the CO-CITATION shape.
    A pool is one cited handle's resolved items; a sentence citing several handles passes all of them, so
    a span carried by ONE of them is backed for the sentence (D-DV-0(2): 2 of deep's 6 quote_mismatch
    strips were handles correctly backing their own clause while a co-cited handle carried the quote).
    Empty after normalization = nothing to check (a span of pure punctuation claims nothing)."""
    hays = [_norm_quote(" ".join(e.get("text") or "" for e in (p or []))) for p in pools]
    for q in _QUOTE.findall(sent):
        nq = _norm_quote(q)
        if nq and not any(nq in h for h in hays):
            return q
    return None


_VINTAGE_WORD = re.compile(r"\b(?:date[sd]?|dating|vintage|newest|oldest|latest|recent|stale|old|"
                           r"thin|published|publication|knowledge|as[ ]of|behind[ ]this[ ]answer)\b", re.I)
_ISO_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")


def _date_echo(sent: str, matched: list[dict]) -> bool:
    """ROUND-2 DOCKET item B-3 (2026-09-17) -- A DATE THAT EQUALS THE CITATION'S OWN DATE IS LEXICAL
    OVERLAP BY CONSTRUCTION, and `no_lexical_overlap` may not charge it.

    THE MEASURED DEFECT (`prearm_smoke_0916`, quick_rv_palm_rapeoil, 3 of that turn's 15 charges and 3 of
    3 outside the number lane). The sentence is ABOUT the documents' DATES:
        "- Dated documents are thin and old for this pair: the newest behind this answer is 2026-03-31
         [E3], and the substitution mechanics I lean on date to 2023 [E1] and 2022 [E11]."
    `_check_evidence_handle` compares the sentence against each resolved item's TEXT, and a sentence that
    quotes a document's VINTAGE shares no word with its PROSE by construction -- so all three handles were
    stripped and the reader was told three dates with no way to check any of them. The dates are not the
    model's invention: `citation_resolved` records E3 = 2026-03-31, E1 = 2023-03-13, E11 = 2022-03-15, and
    the footer PRINTS them. The resolved item's own metadata is part of what a sentence may echo.

    TWO SHAPES, AND THE SECOND IS FENCED:
      * the FULL ISO date written verbatim ("2026-03-31") -- self-identifying, admitted unconditionally;
      * the item's YEAR alone ("date to 2023") -- admitted ONLY when the sentence also carries a VINTAGE
        word, because a bare year is the commonest numeral in this estate's prose and `2026` would
        otherwise rescue any handle on any sentence mentioning the current marketing year.
    Both arms sit INSIDE the zero-overlap branch, so nothing that already passes the overlap test can
    change; this can only ever KEEP a handle, never charge one."""
    for e in matched or []:
        d = str((e or {}).get("date") or "")[:10]
        if not _ISO_DATE.match(d):
            continue
        if d in (sent or ""):
            return True
        if _VINTAGE_WORD.search(sent or "") and re.search(r"(?<!\d)" + d[:4] + r"(?!\d)", sent or ""):
            return True
    return False


def _check_evidence_handle(sent: str, matched: list[dict], *, quotes: bool = True) -> str | None:
    """Rule violated by an evidence handle in this sentence, or None. `quotes=False` defers the quoted-span
    verdict to the caller's SENTENCE-level pass (the co-citation rule above), which is what the declared-
    handle path in _verify_field does; the undeclared path keeps the single-pool check -- its pool is the
    whole evidence list, a superset of every declared pool, so it can only ever be more permissive."""
    if not matched:
        return "fabricated_citation"                      # ledger names a source/date nobody provided
    texts = " ".join(e.get("text") or "" for e in matched)
    if quotes and _unbacked_quote(sent, [matched]):
        return "quote_mismatch"
    if not (_tokens(sent) & _tokens(texts)) and not (set(_NUM.findall(sent)) & set(_NUM.findall(texts))):
        if _date_echo(sent, matched):
            return None                                   # ROUND-2 B-3: the citation's OWN date, echoed
        # D-RC-15a script gate: a non-Latin sentence (non-Latin letters present AND zero usable
        # [a-z]{5,} tokens) can never share a lexical token with Latin evidence -- for it the overlap
        # test is VACUOUS, not failed, and the digit-STRING intersection above can never equate
        # Arabic-Indic digits with the source's ASCII ones. Fall back to VALUE-level verification:
        # the sentence survives when it makes no numeric claim (source/date attribution already
        # passed upstream), when its numbers are [N]-handle territory (_check_number_handle owns
        # their truth), or when a claim value matches the source's (float-normalized, scale-1 --
        # float() parses Arabic-Indic digit runs). An unbacked pure-[E] magnitude still strips.
        # Latin sentences are untouched by construction: _non_latin is False for them.
        if _non_latin(sent) and not _tokens(sent):
            claim_vals = _claim_numbers_in(_HANDLE.sub("", sent))
            if not claim_vals or re.search(r"\[N\d+", sent):
                return None
            if any(_num_backed(v, _numbers_in(texts)) for v in claim_vals):
                return None
        return "no_lexical_overlap"                       # the claim shares NOTHING with its source
    return None


def _all_row_vals(number_calls: list[dict]) -> list[float]:
    out = []
    for c in number_calls or []:
        for r in (c.get("rows") or []):
            try:
                out.append(float(str(r.get("value")).replace(",", "")))
            except (TypeError, ValueError):
                continue
    return out


def _num_backed(v: float, allv: list[float], tol: float = 0.01, *, dec: int | None = None) -> bool:
    """P9-B (R4): SCALE-1 exact-ish match only. Injected cascade rows are PRE-SCALED to narrate_unit, so a
    hallucinated ~40% must NOT be back-filled by a raw 0.4 ratio or a 4e7 tonnage that _num_matches'
    multi-scale set would bridge -- that bridging is the exact mis-attribution hole the pre-scale normalizer
    closes. Compare at scale 1 within a tight tolerance; 0 matches only 0. MAGNITUDE-insensitive to sign:
    prose numbers arrive unsigned (_NUM has no minus) while delta/pct rows are signed -- the Stage-1 RCA
    showed every narrated decline stripping while identical gains passed.

    CYCLE-6 (2026-08-08) -- `dec` ARMS THE SAME SANCTIONED AMENDMENT HERE, AND THAT IS NOT SCOPE CREEP, IT
    IS WHAT MAKES THE AMENDMENT REACH ITS OWN DEFECT. The gate-3 gas sentence was charged TWICE: [N2] as
    number_mismatch (that is `_num_matches`) and [N1]/[N5] as number_unbacked (that is THIS predicate,
    against the merged all-rows pool). Fixing only the first leaves the sentence stripped by the second
    and the whole rule change inert. One rule -- "a stated value matches a row it is a correct rounding of
    at the precision the prose wrote" -- applied at both places that implement matching. `dec=None` (every
    caller that does not thread it) is the pre-CYCLE-6 predicate exactly. Scale-1 by construction here,
    which is precisely where a reader-precision window belongs."""
    va = abs(v)
    for r in allv:
        ra = abs(r)
        if ra == 0:
            if va == 0:
                return True
        elif abs(va - ra) <= tol * ra or _reader_precision_match(va, ra, dec):
            return True
    return False


# ══ D-HP-12 (H1) -- THE DIGIT-LINT. THE CHARGE LIVES HERE; THE REMEDY LIVES IN THE HANDLE PASS ════════
# The split is the cycle-10 discipline, restated for a new rule: this module decides WHAT IS FLAGGED and
# writes it into the ONE strip ledger (`stripped` / `by_rule` / `strip_audit`), and the renderer decides
# what the reader loses. Keeping the charge here is what keeps `by_rule` comparable across the D-HP
# boundary -- a lint that minted its own counter family would make the class scan (this wave's primary
# gate, section 2) unable to see it.
#
# WHY THE REMEDY CANNOT LIVE HERE, MEASURED FROM THE ORDER OF THE SHIPPED PASSES: `_resolve_number_handles`
# runs AFTER this module and SPLICES row values into the prose (answer.py:4168). A deletion pass that ran
# after the splice would delete every sentence the renderer had just filled in -- the digits it would read
# are the ENGINE's, not the model's. So the remedy runs FIRST in the handle stack, before any splice, and
# it re-detects through THIS function so the two can never disagree about what a bare digit is.
#
# R3, OPTION (b) AS RATIFIED -- THE [E]-CITED EXEMPTION, AND THE HARD COUNTER THAT PRICES IT.
# 10.5% of all typed numerals exist ONLY inside [E] chunk prose (`b_grammar.uncited_numerals`), so a menu
# built from served_rows alone cannot express them: under a handle-only contract the model would either
# keep typing them or lose 850 real figures per corpus. Option (b) keeps the prose whole TODAY and prices
# the hole HONESTLY -- an [E]-cited sentence is EXEMPT from the charge and COUNTED SEPARATELY, so
# "the model never types a number" is measured rather than asserted. The counter is what decides whether
# option (a) (the `[Q]` span handle) is worth its own phase.
# THE EXEMPTION IS SENTENCE-SCOPED AND THAT IS DELIBERATELY GENEROUS: it does not ask whether the [E] item
# actually carries the numeral (that question is `quote_mismatch`'s and it needs a span, which is exactly
# what option (a) would build). A generous exemption costs a COUNT, never a false deletion; the reverse
# would delete correct prose, which is D3.
def bare_digit_verdict(sent: str) -> str | None:
    """D-HP-12's per-SENTENCE verdict, and the ONE producer of it (both this module's charge and
    `answer._drop_bare_digit_sentences`' remedy call exactly this).

      None         -- the sentence states no claim magnitude of its own. Nothing to charge.
      "e_cited"    -- it does, AND it cites an [E] handle: the R3(b) exemption. Counted, never charged.
      "bare_digit" -- it does, and it cites no evidence: the model typed a number under a contract that
                      says it must write a handle in the slot instead.

    THE EXTRACTOR IS D-HP-3's SINGLE PRODUCER (`_mask_handles` + `_claim_number_spans`) -- the one with the
    six measured exemptions (year, range tail, letter-glued code, date day, ordinal, duration modifier) and
    the one `dhp_census.json` itself ran, so every count here is denominated in the same producer every
    census percentage is. It is NOT `orchestrator._stated_values` and NOT `register._level_tokens`: those
    carry different exemption sets, each fixed after its own live false-caution incident.

    THE KIND TEST READS `_handle_members`, not a regex over the text, so a GROUPED `[E1, E2]`, a ranged
    `[E1-E4]` and the bare-lead `[3]` (which has always meant the evidence namespace here) all exempt --
    and an [N]-only sentence never does, because an [N] handle is a slot address, not a source of prose
    figures."""
    s = str(sent or "")
    if not s.strip() or not _claim_number_spans(_mask_handles(s)):
        return None
    for m in _HANDLE.finditer(s):
        if any(k == "E" for k, _i in _handle_members(m.group(0))):
            return "e_cited"
    return "bare_digit"


# ══ S7b R1 -- THE LICENSED-ADJECTIVE VERDICT. THE CHARGE LIVES HERE; THE REMEDY LIVES IN answer.py ═══
# THE FIFTH SANCTIONED AMENDMENT on this module's charge rules (cycle-6 reader precision, cycle-8
# ordinal/duration, cycle-9 grouped handles, cycle-10 the termination of the rewrite arm, D-DA rule (g),
# K9-5 `unspanned_superlative` -- and this). It is authored on `bare_digit_verdict`'s shape above,
# VERBATIM in split and in spirit: this module decides WHAT IS FLAGGED, the renderer decides what the
# reader gets, and both call ONE producer so the count and the page cannot disagree.
#
# WHAT IT IS FOR, MEASURED (scratchpad/recon_s8/REGISTER_CENSUS.md, 2026-09-10, 22 documents / 1,051
# sentences / 11 charged by the shipped market-register fence): `register._is_banned_sentence` scores the
# LICENSED sentence and the BARE sentence IDENTICALLY and deletes both --
#     "Managed-money positioning is crowded -- funds hold 31584 contracts [N25], -2.4 sigma on 156
#      weeks [N26], 4th percentile of its own record [N27]."   val=0 flow=1 laneB=1 struck=True
#     "Positioning looks crowded here."                        val=0 flow=1 laneB=1 struck=True
# Three handles, a value in its own unit, a z on a named window and a 4th-percentile tail buy NOTHING.
# Re-read for SPEECH ACT, 1 of the 11 charged sentences is a present-tense valuation/positioning verdict:
# 4 are conditional/mechanism rules, 4 are receipted dated history, and 2 are explicit DENIALS backed by
# their own rows. The fence charges eleven sentences to catch one -- and deletes 2,302 characters and 11
# bound citation handles (3 [N], 8 [E]) doing it. Precision 1/11 is the ratio K9-5 itself ruled
# unshippable, on the same corpus, for the same reason.
#
# THE RULE: BIND THE FIGURE, NEVER STRIKE THE WORD. A bar adjective is a CLAIM ABOUT A ROW, so it is
# verified like every other claim about a row.
#
# WHY THE BARS ARE READ FROM `state_conventions.yaml` AND NOT WRITTEN HERE. That file is the board's own
# band registry and its header states the law this producer inherits: "EVERY VALUE IS AN OWNER-CURATED
# DESK CONVENTION, and each row says whether it is VERIFIED ... or DECLARED". Copying a band into this
# module would mint a SECOND producer of a desk number, which is the drift class the estate has measured
# three times. So the roster below names REFS and the ARITHMETIC reads their bands.
#
# ONLY THE BARS THE FILE ALREADY DECLARES SHIP. `cheap` / `rich` / `expensive` / `overbought` /
# `oversold` / `squeeze` / `vulnerable` have no convention of their own; the census drew PROPOSAL bands
# for them from the nearest shipped family and the yaml's own owner decision 5 refuses an invented
# absolute band ("an invented one would rank 63 commodities against a number curated for one of them").
# So the licence rests on exactly two shipped families and every other proposal is OWED TO THE OWNER,
# listed in the commit and shipped by nobody:
#   * POSITIONING -- `cot_mm_positioning`, bands [10, 90], VERIFIED ("own-history percentiles over 156
#     weeks"). It licenses `crowded` / `stretched` / `vulnerable` / `squeeze` on a TAIL reading.
#   * THE LEVEL/SPREAD DECILE FAMILY -- `mpob_ending_stocks`, `cbot_board_crush_margin`, `kc_chi_spread`,
#     `white_yellow_spread`, all `percentile_bands` [10, 90] with labels [low, high]. It licenses `cheap`
#     from BELOW and `rich` / `expensive` from ABOVE, on a row IN that family and nowhere else.
#
# THE SQUEEZE LICENCE IS POSITIONING-ONLY BY CONSTRUCTION, and that is not a promise, it is where the
# word is read from: the only `squeez\w*` shapes this verdict is ever ASKED about are the ones
# `register._FLOW_PHRASES` already matched, and that pattern's own block note records why it can never
# carry a bare stem -- the display registry humanises ~24 regime ids INTO "drought / supply / China
# demand / delivery / crush / feedstock / premium squeeze" prose. A fundamental-regime label is not a
# member of the charged population, so no licence can move it.
#
# `not_a_verdict` IS DELIBERATELY GENEROUS, on this module's own stated law one screen up: "a generous
# exemption costs a COUNT, never a false deletion; the reverse would delete correct prose".
#: The adjective -> (family, side) table. `side`: "low" reads the bottom band, "high" the top band,
#: "tail" either. Every member is one of `register._LANE_B_ADJ`'s six words or the positioning-squeeze
#: family -- i.e. exactly the population the shipped fence charges, and not one word wider.
BAR_ADJECTIVES: tuple = (
    ("crowded", "positioning", "tail"),
    ("stretched", "positioning", "tail"),
    ("vulnerable", "positioning", "tail"),
    ("squeeze", "positioning", "tail"),
    ("cheap", "level_decile", "low"),
    ("rich", "level_decile", "high"),
    ("expensive", "level_decile", "high"),
)
#: The two families, as CONVENTION REFS. The bands are never written here -- `_bar_bands` reads them from
#: `state_conventions.yaml` through the board's own ONE loader.
BAR_FAMILY_REFS: dict = {
    "positioning": ("cot_mm_positioning",),
    "level_decile": ("mpob_ending_stocks", "cbot_board_crush_margin", "kc_chi_spread",
                     "white_yellow_spread"),
}
_BAR_ADJ_RX = re.compile(r"\b(" + "|".join(
    (w + r"\w*" if w == "squeeze" else w) for w, _f, _s in BAR_ADJECTIVES) + r")\b", re.I)
# THE THREE EXEMPTING SPEECH ACTS. NEGATION is CLAUSE-scoped and the other two are SENTENCE-scoped, and
# the asymmetry is measured: the census' one genuine present verdict -- "A governed spread series is not
# yet served, so I will characterise the gap only in words: soyoil prints above palm, and soyoil is the
# more stretched of the two against its own five-year mean." -- carries a `not` NINETY characters and two
# clause boundaries before its adjective. A sentence-wide negation test would read that sentence as a
# denial and the licence would exempt the one sentence the fence exists for.
# ROUND-6 REVIEW MINOR 1 (2026-09-15): `un\w+ed` READ CASE-BLIND MATCHES THE WORD 'United'. "United
# States corn positioning is crowded [N1]." -- one of the estate's most common surfaces -- came back
# `not_a_verdict` on a plainly honest PRESENT verdict, so no clause was appended AND the sentence never
# reached `adjectives_unbacked`: the generosity cost the COUNTER rather than the page, which is the one
# direction this module's own law does not license. The negation now has to be a REAL negator. The
# un-prefixed past participles this estate's prose actually uses as denials are NAMED, and they may be
# shouted or sentence-initial; the open `un...ed` branch is LOWER-CASE ONLY, which is the mark that
# separates a denial from a proper noun -- and 'united', 'unified' and 'unimproved' are refused in
# either case, because they are the three the review measured and not one of them denies anything in
# any spelling. Compiled WITHOUT re.I so the lower-case branch can MEAN lower-case; the closed
# vocabularies carry their own scoped (?i:).
_BAR_UN_DENIALS = ("changed", "moved", "supported", "backed", "confirmed")
_BAR_NEGATOR = re.compile(
    r"(?i:\b(?:not|never|no|nor|neither|without|hardly|barely|scarcely"
    r"|un(?:" + "|".join(_BAR_UN_DENIALS) + r"))\b|n[’']t\b)"
    r"|\bun(?!ited\b|ified\b|improved\b)[a-z]+ed\b")
_BAR_CLAUSE_EDGE = re.compile(r"[,;:]|--|—|–")
# CONDITIONAL / MECHANISM. `will` is DELIBERATELY ABSENT: it is bare futurity, and the present verdict
# above carries "I will characterise". Every word here introduces a HYPOTHETICAL or a rule.
_BAR_CONDITIONAL = re.compile(
    r"\b(when|whenever|if|unless|whether|were|would|could|should|might|provided that|"
    r"as long as|in the event)\b", re.I)
# DATED HISTORY: a receipted past fact. BOTH legs are required -- a date alone is not a receipt, and a
# handle alone is not a date.
_BAR_DATE = re.compile(
    r"\b\d{4}-\d{2}(?:-\d{2})?\b|\bMY\s?\d{4}(?:/\d{2,4})?\b"
    r"|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?"
    r"|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}\b", re.I)


#: The two bar memos, KEYED BY THE RESOLVED CONFIG PATH rather than by a constant -- `evidence._hier`'s
#: own re-keying (evidence.py:689), and it is here for the identical measured reason. Both reads go
#: through `extract._CFG`, a module-level SINGLETON that six unit files repoint at a tmp dir, and a
#: one-entry memo keyed on a constant makes that repointing INVISIBLE in one direction (a test pointing
#: `_CFG` at a fixture registry silently reads the real one) and POISONS the process in the other (a
#: read taken while `_CFG` pointed at a directory that does not exist caches `{}` for every later
#: reader, which would make every adjective unbound for the rest of the run). Keying on `str(path)`
#: makes each memo follow the config it actually parsed. Serving never repoints `_CFG`, so serving holds
#: exactly one entry per memo, as a `maxsize=1` cache did.
_BAR_CONV_CACHE: dict = {}
_BAR_REF_CACHE: dict = {}
#: ROUND-3: the THIRD memo, same key, same reason -- the estate's contract roster is read from
#: `commodity_hierarchy.yaml` through `evidence._hier`, which resolves off the same `extract._CFG`
#: singleton -- and the three that joined it when the roster grew a COMMODITY half (the commodity
#: vocabulary, the one compiled alternation over both halves, and the numbers registry the freshness
#: bound reads). Same key, same reason, same one-entry-per-config shape.
_BAR_MKT_CACHE: dict = {}
_BAR_CMD_CACHE: dict = {}
_BAR_RX_CACHE: dict = {}
_BAR_CANON_CACHE: dict = {}
_BAR_REG_CACHE: dict = {}
#: ROUND 4: the entity-vocabulary roster half and the sub-national region -> country map, same key,
#: same reason -- both resolve off the `extract._CFG` singleton six unit files repoint.
_BAR_ENT_CACHE: dict = {}
_BAR_RGN_CACHE: dict = {}
_BAR_NONPLACE_CACHE: dict = {}


def _bar_cfg_key() -> str:
    """The resolved config root the two bar memos are keyed on."""
    try:
        from leviathan.graphrag import extract as _ex
        return str(getattr(_ex, "_CFG", ""))
    except Exception:  # noqa: BLE001 -- an unreadable root is one key like any other
        return ""


def _bar_conventions() -> dict:
    """`state_conventions.yaml`'s `conventions` block, through the board's ONE loader.

    Cached because a verdict is asked per SENTENCE and the file is a build-time constant. A missing or
    unreadable file returns `{}`, which makes every bar UNRESOLVABLE and every verdict fall to
    `unbound_adjective` -- fail-closed on the CHARGE and, because the remedy for that class is a DECLINE
    CLAUSE and never a deletion, fail-open on the reader's page."""
    key = _bar_cfg_key()
    if key in _BAR_CONV_CACHE:
        return _BAR_CONV_CACHE[key]
    try:
        from leviathan.graphrag.state.lint import load_conventions
        out = dict((load_conventions() or {}).get("conventions") or {})
    except Exception:  # noqa: BLE001 -- no registry is not an error here; it is an unresolvable bar
        out = {}
    _BAR_CONV_CACHE[key] = out
    return out


def _bar_bands(family: str, conventions: dict | None = None) -> tuple:
    """(low_cut, high_cut) for a family, read off the yaml's own `bands`, or () when the family's refs
    do not agree on one pair.

    AN AMBIGUOUS FAMILY LICENSES NOTHING -- `register._metric_labels`' own refusal, restated: two refs
    of one family declaring different cuts would make the licence depend on which row the sentence
    happened to cite, so the pair must be unanimous or there is no bar."""
    conv = _bar_conventions() if conventions is None else conventions
    pairs = set()
    for ref in BAR_FAMILY_REFS.get(family, ()):
        row = (conv or {}).get(ref) or {}
        bands = row.get("bands")
        if row.get("kind") != "percentile_bands" or not isinstance(bands, list) or len(bands) < 2:
            continue
        try:
            pairs.add((float(bands[0]), float(bands[-1])))
        except (TypeError, ValueError):
            continue
    return tuple(pairs.pop()) if len(pairs) == 1 else ()


def _bar_ref_index() -> dict:
    """(table, metric) -> the ONE family the pair names, or absent when two families claim it.

    The board's served calls carry `query.table` / `query.metric` (`state.render.sb_call`), never the
    convention ref, so the join is made through the board's own roster (`state.feeders.board_map`).
    MEASURED at authoring time: `kc_chi_spread` and `white_yellow_spread` share
    ('gold_futures_spreads', 'spread_value') -- the same FAMILY, so the pair resolves; a pair claimed by
    two DIFFERENT families would resolve to nothing rather than to a guess.

    THE JOIN IS THE FAMILY'S, NEVER THE SERIES'. (table, metric) names a FAMILY of series -- the board
    emits one `unit='percentile'` call per commodity on `silver_cot/mm_net` -- so this index answers
    "which bar table governs this pair" and nothing at all about WHICH series a row belongs to. That
    second question is `_bar_scope`'s, and `_bar_percentiles` must ask both."""
    key = _bar_cfg_key()
    if key in _BAR_REF_CACHE:
        return _BAR_REF_CACHE[key]
    try:
        from leviathan.graphrag.state.feeders import board_map
        rows = board_map() or {}
    except Exception:  # noqa: BLE001 -- no roster -> no join -> every bar unresolvable
        _BAR_REF_CACHE[key] = {}
        return {}
    out: dict = {}
    # ROUND-3 REVIEW MINOR (2026-09-15): `pair`, NOT `key`. This loop rebound the MEMO KEY, so the
    # store two lines down wrote the index under the LAST (table, metric) tuple and `_bar_cfg_key()`
    # was never in the cache at all -- measured: one call left `_BAR_REF_CACHE` holding the single key
    # ('gold_futures_spreads', 'spread_value'), and 25 verdicts drove 25 `feeders.board_map()` reads.
    # No serving regression (board_map is itself lru_cached, 0.006 ms/call), but the FAILURE branch at
    # the except above DOES store under the config key, so one transient failure pinned `{}` for the
    # process while a success could never pin anything -- the memo was one-way, in the wrong direction.
    for fam, refs in BAR_FAMILY_REFS.items():
        for ref in refs:
            row = rows.get(ref) or {}
            pair = (str(row.get("table") or ""), str(row.get("metric") or ""))
            if not pair[0] or not pair[1]:
                continue
            if out.get(pair, fam) != fam:
                out[pair] = None                    # two families claim it -> nobody may use it
            else:
                out.setdefault(pair, fam)
    out = {k: v for k, v in out.items() if v}
    _BAR_REF_CACHE[key] = out
    return out


# ── S7b R1 REVIEW MAJOR 1 (2026-09-11): THE BAR IS A SERIES' BAR, NOT A FAMILY'S. ────────────────────
# MEASURED THROUGH THE REAL PRODUCER. `state/render.py:703` emits one `unit='percentile'` call PER
# COMMODITY on `silver_cot/mm_net`, so a family join on (table, metric) alone puts every board's
# positioning row in one bucket: with corn at the 3rd percentile as [N1] and cocoa at the 52nd as [N2]
# in ONE turn, "ICE cocoa managed-money positioning is crowded [N1]" resolved `licensed` off CORN's
# reading while the same sentence citing cocoa's own [N2] resolved `weak_adjective` and was corrected.
# `query.commodity` and `query.country` are on every board call (`render.sb_call`) and were read by
# nothing. Two dimensions, and they are asked SEPARATELY rather than as one tuple, because a wheat
# sentence naming Brazil while citing the United States row names its own COMMODITY correctly -- a
# single-tuple test would be satisfied by the commodity half and license the wrong country.
#
# THE RULE IS A CONTRADICTION TEST, NOT AN ATTRIBUTION TEST, and the asymmetry is deliberate. Asking
# "does the sentence NAME this row's series" would refuse every honest sentence whose subject is set by
# its heading or its neighbour; asking "does the sentence name a COMPETING series of this same family
# while naming nothing of this row's own" refuses exactly the shape measured and leaves a comparison
# sentence ("cocoa positioning is crowded [N2] while corn is not") licensed, because it names both.
# THE COMPETING VOCABULARY IS THE TURN'S OWN -- the scopes of the other calls in this family on this
# answer -- so no lexicon is invented and a word shared by two scopes (the exchange token in
# `corn_cbot` / `soybeans_cbot`) subtracts itself.
#
# AND ROW SELECTION IS SCOPED IN TIME. A call whose rows are [55th pct @2026-09-05, 3rd pct @2019-04-02]
# licensed `crowded` off the 2019 row: the bar is a PRESENT verdict's bar, so only the call's newest
# knowledge date participates. Rows carrying no knowledge date at all are used only when NO row on that
# call carries one, which is the board's own single-row shape and leaves it unchanged.
#
# EVERY CLAUSE HERE FAILS CLOSED ON THE LICENCE AND OPEN ON THE PAGE: a refusal returns
# `unbound_adjective`, which is still a verdict, so `register._is_banned_sentence` still relieves the
# STRIKE and the reader keeps the sentence with the decline clause beside it. Nothing here can delete.
def _bar_scope(call: dict | None) -> tuple:
    """One call's SERIES SCOPE -- (commodity, country), lower-cased, off its own query."""
    q = ((call or {}).get("query") or {})
    return (str(q.get("commodity") or "").strip().lower(),
            str(q.get("country") or "").strip().lower())


def _bar_scope_words(seg: str) -> set:
    """The reader words ONE scope segment is named by: the whole de-underscored phrase plus each of its
    tokens of three or more characters (so `corn_cbot` contributes "corn cbot", "corn", "cbot" and
    "United States" contributes "united states", "united", "states" but never the ambiguous "us")."""
    s = str(seg or "").strip().lower().replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return set()
    return {s} | {w for w in s.split(" ") if len(w) >= 3}


def _bar_sent_words(sent: str) -> str:
    """The sentence as a space-delimited lower-case word stream, padded, for whole-word containment.
    ASCII-FOLDED through `_bar_ascii`, so an accented surface is the word it is and not two."""
    return " " + re.sub(r"[^a-z0-9]+", " ", _bar_ascii(sent).lower()).strip() + " "


# ── ROUND-3 REVIEW MAJOR (2026-09-15): THE COMPETING VOCABULARY WAS THE TURN'S, AND THE TURN IS OFTEN
# ONE MARKET WIDE. `others` is the OTHER calls of this family on this answer, so on the modal
# single-commodity board `foreign` is EMPTY and the contradiction test cannot fire at all. MEASURED, with
# NO call of the named market on the turn: "ICE cocoa managed-money positioning is crowded [N1]" citing
# CORN at the 3rd percentile -> `licensed`; "Malaysian palm oil positioning is crowded [N1]" citing the
# same corn row -> `licensed`; "Brazil wheat positioning is crowded [N1]" citing the United States row ->
# `licensed`. All three are the threat direction the brief names ("a figure from a DIFFERENT series, a
# different country"), all three return `unbound_adjective` the moment the competing market IS on the
# turn, and on a `licensed` verdict `_bind_bar_adjectives` appends no clause at all -- so the cross-market
# reading shipped UNQUALIFIED, worse than HEAD (which struck it).
#
# SO THE VOCABULARY GETS A SECOND, STANDING HALF, AND NEITHER HALF IS INVENTED HERE.
#   * COMMODITY -- `display._contracts_hier()`, the estate's 31 declared contracts, read through the same
#     hierarchy `state/render.board_label` prints from. PHRASES ONLY (the de-underscored slug, the node,
#     the exchange code) and never the token split `_bar_scope_words` does for the turn's own scopes:
#     splitting would mint 'oil', 'crude', 'red', 'white' and 'no' as competing MARKETS and refuse
#     honest prose. The one exchange code that is also an English word, ICE, is dropped by name.
#   * COUNTRY -- `geo_lexicon`, which this estate already calls "the binding verifier's ONE geography
#     vocabulary": 34 canonical slugs with their name surfaces and demonyms, the decoy suppression
#     ('South Africa' does not mint 'africa'), the not-a-scope follower blacklist ('the Malaysian
#     ringgit' mints nothing) and the L2 closure (France sits inside the European Union). Its AGGREGATE
#     SENTINEL is honoured as the lexicon's own L1 rule says: a sentence reading 'world'/'global' names a
#     container, and a container is not a disagreement with its contents, so the country dimension
#     stands down.
# THE ASYMMETRY IS UNCHANGED -- this is still a CONTRADICTION test, not an attribution test: a sentence
# naming nothing keeps its licence (its subject is its heading's), and a comparison naming BOTH markets
# keeps it too. What changes is that "names a competing market" no longer requires that market to have
# bought a seat on this turn.
#
# THE MEASURED COST, STATED: a sentence that cites its own market's percentile and mentions a foreign
# country in passing ("CBOT corn positioning is crowded [N1] as Brazilian rain returns") now resolves
# `unbound_adjective` and carries the decline clause. That is the same verdict the TURN half already
# returned whenever a Brazil call happened to be on the answer -- the rule is not new, its reach is --
# and it fails closed on the LICENCE and open on the PAGE: the sentence and its figure both stand.
_BAR_EXCHANGE_HOMONYMS = frozenset({"ice"})     # ...and it is a word: 'ice storm', 'ice damage'
#: ...and the two ways a reader marks that word as the VENUE it also is. An exchange code is
#: spelled in CAPITALS and the English word is not, which is the discriminator round 4 shipped;
#: ROUND-5's ruling (a) adds the other -- the LOCATIVE that can only govern a place or a venue
#: ("positioning is crowded ON ice") -- because the drop must not remove a venue used as a venue.
#: Both admissions cost the same thing when they are wrong: a clause not appended (fail closed).
_BAR_VENUE_USE = re.compile(r"\b(?:on|at)\s+(?:the\s+)?$", re.I)
# ── ROUND-3 REVIEW MAJOR 1 (2026-09-15): THE STANDING ROSTER WAS PHRASES-ONLY, SO IT HELD EVERY WORD A
# DESK DOES NOT USE. Measured with ONLY a corn call on the turn (corn_cbot / united_states @ 3rd pct),
# seven bare market nouns licensed `crowded` off CORN's figure and shipped with no clause at all:
# "Soybean positioning is crowded [N1].", and the same sentence for Wheat, Sugar, Coffee, Palm,
# Soymeal and Cattle. The roster held 'soybeans' but not 'soybean', 'raw sugar' / 'white sugar' but not
# 'sugar', 'arabica coffee' / 'robusta coffee' but not 'coffee', 'hrw wheat' / 'srw wheat' but not
# 'wheat', and NOTHING AT ALL for a COT-universe market with no declared contract (cattle, hogs,
# soymeal as one word). The three probes the round-3 fix was built on -- cocoa, 'Malaysian palm oil',
# 'Brazil wheat' -- are all phrases, which is exactly why a phrase-only vocabulary passed its own gate.
#
# SO THE VOCABULARY READS THE ESTATE'S WHOLE COMMODITY HIERARCHY, AND STILL INVENTS NOTHING. One
# producer, `commodity_hierarchy.yaml` through `evidence._hier()`: the 31 declared CONTRACTS as before,
# and now its `groups` / `complexes` / `context_commodities` members too -- 63 commodity names, which is
# the same universe the COT roster, the transmission chain and the board's own labels are drawn from.
# Each name contributes its de-underscored PHRASE, its tokens, and the two folds a reader actually
# writes: the singular/plural pair ('soybeans' -> 'soybean', 'hogs' -> 'hog') and the desk's own
# contraction of a `soybean X` compound ('soybean meal' -> 'soy meal', 'soymeal').
#
# A TOKEN LIST NEEDS A HOMONYM DROP AND THIS ONE IS NAMED RATHER THAN GUESSED. The roster is 31
# contracts + 51 commodities = 213 reader words, of which 104 are single tokens, and the drop table was
# written by DUMPING THOSE TOKENS AND READING THEM: 37 words name no market on their own and are listed
# below by name in three classes -- the modifiers and categories ('oil', 'meal', 'feed', 'grains'), the
# GRADE words off the slugs ('hard', 'red', 'winter', 'rough', 'frozen', 'crude'), and the PLACE words
# the geo lexicon owns better ('south', 'french', 'malaysian') -- plus 'reference' and 'ice'. Same
# discipline `_BAR_EXCHANGE_HOMONYMS` already applies to ICE; every token that survives is a market
# word in this estate's own prose.
#
# THE ASYMMETRY IS UNCHANGED, AND IT IS WHY A BROAD VOCABULARY IS SAFE HERE: a contradicted scope
# returns `unbound_adjective`, which is still a VERDICT -- `register._is_banned_sentence` still relieves
# HEAD's strike, the sentence and its figure both stand, and the reader gets the decline clause beside
# the word. A false foreign hit costs the LICENCE. A missing one costs a cross-market call on the page.
#: The 22 generic tokens, dropped by name. Each is a MODIFIER or a CATEGORY that names no market alone:
#: a sentence saying "oil" may be about palm, soy, rapeseed, sunflower or crude, and one saying "feed"
#: or "grains" is naming a group the hierarchy itself declares as a container.
_BAR_MARKET_STOP = frozenset({
    # (a) MODIFIERS and CATEGORY words -- a sentence saying "oil" may be about palm, soy, rapeseed,
    #     sunflower or crude, and one saying "feed" or "grains" names a container the file itself fills.
    "oil", "oils", "meal", "meals", "feed", "grains", "cereals", "complex", "demand", "compound",
    "coarse", "minor", "raw", "white", "yellow", "fresh", "used", "cooking", "veg", "vegetable",
    "juice",
    # (b) GRADE words off the contract slugs: hard/soft red winter wheat, rough rice, frozen orange
    #     juice, crude palm oil. Every one is ordinary weather and quality English.
    "crude", "hard", "soft", "red", "rough", "frozen", "winter", "spring",
    # (c) PLACE words -- the COUNTRY dimension owns geography, through `geo_lexicon`, which carries the
    #     demonyms, the decoy suppression and the L2 closure this token split has none of.
    "south", "french", "malaysian", "brazilian", "african", "campinas",
    # (d) and two structural leftovers: `reference` (campinas_corn_reference_bmf) and `ice`, which the
    #     exchange field drops by name and the SLUG token split had quietly put back.
    "reference", "ice",
    # (e) ROUND 4, read off the ENTITY-VOCABULARY dump the same way: three of its alias phrases are
    #     ordinary English before they are markets -- `fame` (the FAME biodiesel spec), `lime` (the
    #     citrus, and also the soil amendment every ag page writes) and `mop` (muriate of potash).
    #     Each is dropped by NAME, and each is still reachable by its full alias ("muriate of potash").
    "fame", "fames", "lime", "limes", "mop", "mops",
})


def _bar_ascii(s: str) -> str:
    """`s` ASCII-FOLDED -- 'azucar' for 'azúcar', 'mais' for 'maïs'.

    ROUND 4, MEASURED: the roster's third half carries the estate's Portuguese, Spanish and French
    alias surfaces, and `_bar_sent_words` builds its word stream with `[^a-z0-9]+ -> ' '`, which does
    not fold an accent -- it SPLITS on it ('az car'). So every accented alias was unreachable from the
    sentence side: 2 of the 137 roster entries could not be named at all. Both sides fold through this
    one function now, which is `extract._normalize`'s own NFKD-and-drop rule, so a word spelled with an
    accent and a word spelled without one are the same word here."""
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()


def _bar_phrase(seg: str) -> str:
    """One scope segment as a single de-underscored, ASCII-folded lower-case phrase (no token split)."""
    return re.sub(r"\s+", " ",
                  _bar_ascii(seg).strip().lower().replace("_", " ").replace("-", " ")).strip()


def _bar_fold(word: str) -> set:
    """A word and its crude singular/plural partner -- 'soybeans'/'soybean', 'hogs'/'hog'. Crude on
    purpose: a reader writes both, and a fold that collided with a different word would be worse than
    none, so it takes a trailing 's' only off a word long enough that dropping it cannot collide
    ('gas', 'less') and adds one only to a word that does not already end in one."""
    w = str(word or "").strip().lower()
    out = {w} if w else set()
    if len(w) >= 4 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        out.add(w[:-1])
    elif len(w) >= 3 and not w.endswith("s"):
        out.add(w + "s")
    return out


def _bar_name_words(name: str, *, contraction: bool = True) -> set:
    """Every reader surface ONE declared name is written by: the phrase, its folds, its non-generic
    tokens with their folds, and the `soybean X` -> `soy X` / `soyX` contraction the desk actually
    writes ('soymeal', 'soyoil') -- which is a MORPHOLOGY over the estate's own name, never a synonym
    list of this module's invention."""
    ph = _bar_phrase(name)
    if not ph:
        return set()
    out = set(_bar_fold(ph))
    toks = ph.split(" ")
    for t in toks:
        if len(t) >= 3 and t not in _BAR_MARKET_STOP:
            out |= _bar_fold(t)
    if contraction and len(toks) > 1 and toks[0] in ("soybean", "soybeans"):
        tail = " ".join(toks[1:])
        out |= _bar_fold("soy " + tail) | _bar_fold("soy" + tail.replace(" ", ""))
        out |= _bar_fold("soy")
    return {w for w in out if len(w) >= 3}


def _bar_hier() -> dict:
    """`commodity_hierarchy.yaml`, through the one reader `display` already uses. {} when unreadable --
    the standing half then contributes nothing and the turn's own scopes decide alone, which is the
    shipped behaviour, so a missing config NARROWS this guard and never widens it."""
    try:
        from leviathan.graphrag import evidence as _ev
        return _ev._hier() or {}
    except Exception:  # noqa: BLE001 -- no hierarchy -> no standing vocabulary, never a wrong one
        return {}


def _bar_contract_vocab() -> tuple:
    """(slug phrase, the reader words that name it) for every CONTRACT the estate declares.

    Memoised on the resolved config path like the other bar reads. ROUND-3: the words are no longer
    phrases only -- see the block note above -- but the ENTRY is still one contract, so
    `_bar_scope_contradicted` can still tell a row's own market from its neighbours."""
    key = _bar_cfg_key()
    if key in _BAR_MKT_CACHE:
        return _BAR_MKT_CACHE[key]
    hier = _bar_hier()
    out: list = []
    for slug, meta in ((hier.get("contracts") or {}) or {}).items():
        words = set(_bar_name_words(slug, contraction=False))
        node = _bar_phrase((meta or {}).get("node") if isinstance(meta, dict) else "")
        if node:
            words |= _bar_name_words(node, contraction=False)
        exch = _bar_phrase((meta or {}).get("exchange") if isinstance(meta, dict) else "")
        if exch and exch not in _BAR_EXCHANGE_HOMONYMS:
            words.add(exch)
        out.append((_bar_phrase(slug), frozenset(w for w in words if w)))
    _BAR_MKT_CACHE[key] = tuple(out)
    return _BAR_MKT_CACHE[key]


#: The hierarchy blocks that declare CONTAINERS rather than markets. `groups` KEYS ('grains',
#: 'oilseeds', 'tropicals') and the `_complex` / `_grains` keys of `complexes` name a basket the file
#: itself fills with members; minting them as competing MARKETS would refuse "the oilseed complex is
#: bid" on every turn. Their MEMBERS are markets and are read.
_BAR_HIER_CONTAINER = re.compile(r"_complex$|_grains$|^oilseeds?$|^vegetable_oils$|^oilseed_meals$"
                                 r"|^coarse_grains$|^soft_commodities$|^tropicals$|^food_grains$"
                                 r"|^grains$", re.I)


def _bar_commodity_vocab() -> tuple:
    """(commodity phrase, the reader words that name it) for the estate's whole declared commodity
    universe -- `groups` members, `complexes` keys and members, `context_commodities`."""
    key = _bar_cfg_key()
    if key in _BAR_CMD_CACHE:
        return _BAR_CMD_CACHE[key]
    hier = _bar_hier()
    names: set = set()
    for members in (hier.get("groups") or {}).values():
        names |= {str(m) for m in (members or [])}
    for ckey, members in (hier.get("complexes") or {}).items():
        names |= {str(m) for m in (members or [])}
        if not _BAR_HIER_CONTAINER.search(str(ckey)):
            names.add(str(ckey))
    names |= {str(m) for m in (hier.get("context_commodities") or [])}
    out = []
    for n in sorted(names):
        if _BAR_HIER_CONTAINER.search(n):
            continue
        words = _bar_name_words(n)
        if words:
            out.append((_bar_phrase(n), frozenset(words)))
    _BAR_CMD_CACHE[key] = tuple(out)
    return _BAR_CMD_CACHE[key]


#: The entity-vocabulary node classes that are MARKETS. `commodity` is the board's and the walk's own
#: node vocabulary; `fertilizer` is a priced input the estate narrates as its own market (urea, potash).
#: Deliberately absent: `region`, `country_origin`, `organization`, `hazard`, `climate_driver`,
#: `state_marker`, `policy_event` (not markets), and `instrument` (a spread is a SERIES of a market
#: already on the roster, and minting "board crush" as a competing market would refuse the estate's own
#: crush prose).
_BAR_ENTITY_CLASSES = ("commodity", "fertilizer")


def _bar_entity_vocab() -> tuple:
    """(node phrase, reader words) for every MARKET the entity vocabulary declares -- the estate's
    OTHER market-word file, and the one the board and the walk narrate from.

    ROUND-4 REVIEW MAJOR (2026-09-15): the roster read `commodity_hierarchy.yaml` alone, so 17 words
    this estate writes in its own prose licensed a corn row on a one-market sentence -- pork, swine,
    pigs (while `hog`/`hogs` were caught: the same market, two surfaces), milk, cheese, whey, butterfat
    (while `dairy` was caught), rye, oats, millet, triticale, buckwheat, urea, potash, lard, groundnut,
    copra. The two files are read by ONE producer here, exactly as the hierarchy's two halves are, so a
    word can enter the roster only by being declared somewhere the estate already maintains.

    ALIASES COUNT. `entity_vocabulary.aliases` is where 'pork' and 'whey' actually live (the NODE is
    `hogs` / `dairy`), and an alias is what a reader writes.

    PHRASES ONLY, AND THAT IS THE CONTRACT HALF'S OWN MEASURED RULE, not a caution. Running the token
    split over these aliases mints 553 words, and reading the dump is what settles it: `all` (from "all
    wheat"), `bean` and `black` (from "black gram"), `broad`, `animal`, `based`, `bio`, `blend`,
    `crop` -- and `crop` alone read "Ice damage to the crop leaves positioning crowded [N1]" as a
    sentence naming the HOG market. So each alias contributes its whole phrase and the crude
    singular/plural fold of it, exactly as `_bar_contract_vocab` shipped before the roster grew a
    commodity half. The 17 words the review measured are single-token aliases (pork, swine, whey, rye,
    oats, urea, potash, lard, copra...), so phrases-only catches every one of them."""
    key = _bar_cfg_key()
    if key in _BAR_ENT_CACHE:
        return _BAR_ENT_CACHE[key]
    out: list = []
    try:
        import yaml as _yaml

        from leviathan.graphrag import extract as _ex
        data = _yaml.safe_load((_ex._CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8")) or {}
        nodes = (data.get("nodes") or {})
        aliases = (data.get("aliases") or {})
        for cls in _BAR_ENTITY_CLASSES:
            for node in (nodes.get(cls) or []):
                words: set = set()
                for surface in [str(node)] + [str(a) for a in (aliases.get(str(node)) or [])]:
                    ph = _bar_phrase(surface)
                    if ph and ph not in _BAR_MARKET_STOP and len(ph) >= 3:
                        words |= {w for w in _bar_fold(ph) if w not in _BAR_MARKET_STOP}
                if words:
                    out.append((_bar_phrase(str(node)), frozenset(words)))
    except Exception:  # noqa: BLE001 -- no vocabulary -> no third half, never a wrong one
        out = []
    _BAR_ENT_CACHE[key] = tuple(out)
    return _BAR_ENT_CACHE[key]


def _bar_market_vocab() -> tuple:
    """The standing market roster: every declared CONTRACT, every declared COMMODITY, and every MARKET
    node the entity vocabulary declares, as (identity phrase, reader words)."""
    return tuple(_bar_contract_vocab()) + tuple(_bar_commodity_vocab()) + tuple(_bar_entity_vocab())


def _bar_canon_map() -> dict:
    """{identity phrase -> canonical market}, memoised: `_bar_canon` is asked once per roster ENTRY per
    verdict now that `mine` folds by canon, and a linear scan of the contracts dict inside that loop is
    the `_bar_ref_index` memo bug in a different costume."""
    key = _bar_cfg_key()
    if key in _BAR_CANON_CACHE:
        return _BAR_CANON_CACHE[key]
    out: dict = {}
    for slug, meta in ((_bar_hier().get("contracts") or {}) or {}).items():
        node = _bar_phrase((meta or {}).get("node") if isinstance(meta, dict) else "")
        out[_bar_phrase(slug)] = node or _bar_phrase(slug)
    _BAR_CANON_CACHE[key] = out
    return out


def _bar_canon(identity: str) -> str:
    """The MARKET a roster identity belongs to: a contract folds onto its hierarchy NODE
    ('corn_cbot' -> 'corn', 'french_maize_matif' -> 'corn'), a commodity is its own market. Used only
    by the two-market SUBJECT rule, where 'the same market said twice' must not read as a comparison."""
    return _bar_canon_map().get(identity, identity)


def _bar_market_rx() -> tuple:
    """(one compiled alternation over every roster word, {word: canonical market}). LONGEST FIRST, so
    'hrw wheat' is one market mention and not two -- `finditer` resumes after a match, so the 'wheat'
    inside it is never counted as a second, competing market."""
    key = _bar_cfg_key()
    if key in _BAR_RX_CACHE:
        return _BAR_RX_CACHE[key]
    words: dict = {}
    for ident, ws in _bar_market_vocab():
        canon = _bar_canon(ident)
        for w in ws:
            words.setdefault(w, canon)
    if not words:
        _BAR_RX_CACHE[key] = (None, {})
        return _BAR_RX_CACHE[key]
    alt = "|".join(re.escape(w) for w in sorted(words, key=lambda x: (-len(x), x)))
    _BAR_RX_CACHE[key] = (re.compile(r"\b(?:" + alt + r")\b", re.I), words)
    return _BAR_RX_CACHE[key]


def _bar_exchange_words() -> frozenset:
    """Every EXCHANGE code the hierarchy declares, as reader words. They stay in the contradiction
    vocabulary (naming MATIF while citing a CBOT row names a competing series) and are kept OUT of the
    two-market subject count: a venue lists many crops and is not one of them."""
    out: set = set()
    for _slug, meta in ((_bar_hier().get("contracts") or {}) or {}).items():
        exch = _bar_phrase((meta or {}).get("exchange") if isinstance(meta, dict) else "")
        if exch:
            out |= _bar_fold(exch)
    return frozenset(out)


def _bar_venue_rx():
    """One alternation over every declared EXCHANGE code, longest first. Memoised on the roster's own
    key; None when the hierarchy is unreadable."""
    key = "venues:" + _bar_cfg_key()
    if key in _BAR_RX_CACHE:
        return _BAR_RX_CACHE[key]
    ws = sorted(_bar_exchange_words(), key=lambda x: (-len(x), x))
    _BAR_RX_CACHE[key] = (re.compile(r"\b(?:" + "|".join(re.escape(w) for w in ws) + r")\b", re.I)
                          if ws else None)
    return _BAR_RX_CACHE[key]


def _bar_named_markets(sent: str, *, venues: bool = False) -> list:
    """[(offset, canonical market)] for every market this sentence NAMES, left to right, longest match
    first and never overlapping. Exchange codes are not markets and do not appear.

    `venues=True` counts them anyway, each under its OWN identity (`venue:cbot`), and that is the
    round-4 review MAJOR's remedy rather than a change of mind about what a venue is. A comparison that
    names only the two EXCHANGES -- "ICE positioning is crowded [N2] while CBOT is quiet [N1]." --
    resolved to no subject at all, so the percentile test went back to OR-ing every handle and read the
    adjective off the OTHER market's row. A venue is still not a market, so `venue:ice` matches no
    call's canons and the comparison FAILS CLOSED: no row resolves, the verdict is `unbound_adjective`
    and the correcting clause appends NOTHING (ruling (3)). The default is False, so every other
    caller -- `_bar_call_canons` included -- reads exactly what it read before."""
    rx, words = _bar_market_rx()
    if rx is None:
        return []
    exch = _bar_exchange_words()
    raw = str(sent or "")
    body = re.sub(r"[_-]", " ", _bar_ascii(raw).lower())
    out = []
    for m in rx.finditer(body):
        w = m.group(0).strip()
        if w in exch:
            if venues:
                out.append((m.start(), "venue:" + w))
            continue
        out.append((m.start(), words.get(w, w)))
    if venues:
        # THE VENUE SCAN IS ITS OWN, and it has to be: `_bar_contract_vocab` drops ICE from the market
        # words BY NAME (it is 'ice storm', 'ice damage'), so the loop above can never see the exact
        # code the review's escape was written in. The homonym is admitted here only in UPPER CASE --
        # an exchange code is spelled that way and the English word is not, which is the same
        # discriminator the desk lint's proper-name rule uses, and it costs a false venue mention
        # nothing worse than a clause not appended (fail closed).
        vrx = _bar_venue_rx()
        if vrx is not None:
            taken = [(p, p + 1) for p, _c in out]
            for m in vrx.finditer(body):
                w = m.group(0).strip()
                if w in _BAR_EXCHANGE_HOMONYMS \
                        and not raw[m.start():m.end()].isupper() \
                        and not _BAR_VENUE_USE.search(body[:m.start()]):
                    continue
                if any(a <= m.start() < b for a, b in taken):
                    continue
                out.append((m.start(), "venue:" + w))
            out.sort(key=lambda t: t[0])
    return out


def _bar_call_canons(call: dict | None) -> set:
    """The markets ONE call's own row belongs to, read through the SAME roster the sentence is read
    through -- so a call scoped on a declared contract (`corn_cbot`), on an undeclared one
    (`cocoa_ice`) and on the bare commodity (`cocoa`) all answer the same market."""
    own = _bar_scope(call)[0]
    if not own:
        return set()
    ph = _bar_phrase(own)
    out = {ph, _bar_canon(ph)}
    out |= {c for _p, c in _bar_named_markets(ph)}
    return {c for c in out if c}


def _bar_region_country() -> dict:
    """{normalised region surface -> the country it belongs to}, from `configs/graphrag/regions.yaml`.

    ROUND-4 REVIEW MAJOR (2026-09-15): `geo_lexicon.slugs_in` resolves COUNTRIES and nothing below
    them, so every place word this estate actually writes stood the geo dimension down -- 'Mato
    Grosso', 'Parana', 'Rio Grande do Sul', 'Sao Paulo', 'Bahia', 'Sabah', 'Johor' all returned the
    empty set, and 8 of 8 sub-national probes licensed off a united_states row.

    ROUND-5 REVIEW MAJOR 2 (b): SIX OF THOSE SEVEN RESOLVED AND THE SEVENTH DID NOT, so the
    paragraph above claimed a fix it did not have, and the paragraph that replaced it claimed one
    this file cannot keep. WHAT THIS MAP RESOLVES IS WHATEVER THE HARVESTER WROTE, and nothing else:
    `configs/graphrag/regions.yaml` is GIT-IGNORED (.gitignore:75) and REGENERATED by
    `scripts/harvest_geographies.py` out of `configs/geographies/`, so a surface hand-added here
    lives in ONE working tree, cannot be committed by path, and is silently reverted by the next
    harvest -- a deck pinned to such a surface is green as a property of a machine rather than of the
    repo. Round 5 added 43 bare surfaces as aliases on 27 entries; round 6 REVERTED them and the file
    is byte-identical to what `harvest_geographies.main()` writes (267 keys, 0 entries differing).

    SO 'Rio Grande do Sul' DOES NOT RESOLVE HERE, AND THAT IS THE SAFE OUTCOME. The cause is
    mechanical: `harvest_geographies._region_name` drops the country-code token and any token of the
    COMMODITY SLUG, so `br_soy_rio_grande_do_sul` under commodity `soybeans_cbot` keeps its `soy`
    (the slug spells 'soybeans', the key spells 'soy') and the region is reachable only as 'soy rio
    grande do sul', which no reader writes. The same shape hides 'Heilongjiang', 'Jilin', 'Inner
    Mongolia', 'Liaoning', 'North Dakota', 'Oklahoma', 'Tennessee', 'Montana' and the rest of the
    commodity-prefix class (`Soy_` / `Hrs_` / `Hrw_` / `Srw_` / `canola_`). A surface that resolves to
    nothing FAILS THE SENTENCE CLOSED -- `_bar_unresolved_place` for the adjunct, `_bar_subject_place`
    for the subject -- which costs a CORRECTION NOT PRINTED and never a wrong figure printed: the
    sentence ships as the writer wrote it. WIDENING THE SURFACES IS THE HARVESTER'S JOB (it should
    emit the bare surface as an alias whenever it strips a commodity prefix), never a hand edit of
    this overlay; that file is outside this lane's declared scope and is DOCKETED for the owner.

    What the map does resolve it resolves through the estate's own harvested file (the one
    `extract._canon_region` reads), with `extract._normalize`'s SURFACE NORMALISATION: one producer
    for "is this word that region", so a region spelled with an underscore, an accent or a space
    resolves the same way here as it does in extraction. Measured on the harvested file: 'Iowa',
    'Illinois', 'Nebraska', 'Kansas', 'Mato Grosso', 'Parana', 'Sao Paulo', 'Bahia', 'Sabah',
    'Johor', 'Uttar Pradesh' and 'Buenos Aires' all resolve, and the country half then judges them."""
    key = _bar_cfg_key()
    if key in _BAR_RGN_CACHE:
        return _BAR_RGN_CACHE[key]
    out: dict = {}
    try:
        import yaml as _yaml

        from leviathan.graphrag import extract as _ex
        data = _yaml.safe_load((_ex._CFG / "regions.yaml").read_text(encoding="utf-8")) or {}
        for canon, meta in (data.get("regions") or {}).items():
            country = str((meta or {}).get("country") or "").strip()
            if not country:
                continue
            for surface in [str(canon)] + [str(a) for a in ((meta or {}).get("aliases") or [])]:
                s = _ex._normalize(surface)
                if len(s) >= 4:                 # a two-letter region code is an English word too often
                    out.setdefault(s, country)
    except Exception:  # noqa: BLE001 -- no map -> the sub-national half stands down, never a guess
        out = {}
    _BAR_RGN_CACHE[key] = out
    return out


def _bar_geo(text: str) -> tuple:
    """(the country slugs `text` names, closed over the lexicon's ancestors; whether it names an
    AGGREGATE sentinel). ((), False) when the lexicon is unreadable -- silence, never a guess.

    A SUB-NATIONAL REGION NAMES ITS COUNTRY (round-4 review MAJOR): 'Mato Grosso' is resolved through
    `regions.yaml` to Brazil and then through the SAME lexicon as the word 'Brazil' would be, so the two
    spellings of one geography cannot disagree."""
    try:
        from leviathan.graphrag import geo_lexicon as _gl
        s = str(text or "")
        found = set(_gl.slugs_in(s))
        rgn = _bar_region_country()
        if rgn:
            words = " " + re.sub(r"[^a-z0-9]+", " ", _bar_ascii(s).lower()).strip() + " "
            for surface, country in rgn.items():
                if (" " + surface + " ") in words:
                    found |= set(_gl.slugs_in(country))
        return frozenset(_gl.closure_of(found)), bool(_gl.sentinel_hit(s))
    except Exception:  # noqa: BLE001 -- no lexicon -> the standing country half stands down
        return frozenset(), False


def _bar_scope_contradicted(sent: str, sent_words: str, own: tuple, others: list) -> bool:
    """Does the sentence name a COMPETING series while naming nothing of this row's own? Asked per
    dimension (commodity, then country); either one contradicted refuses the licence.

    Each dimension asks TWO vocabularies -- the TURN's other calls of this family, and the estate's own
    standing roster (see the block note above) -- and either one may convict.

    ROUND-3 REVIEW MAJOR 2 (2026-09-15): A ROW THAT CARRIES NO SCOPE CANNOT CLAIM ONE. Both halves used
    to run only `if own[dim]`, so a row whose own country is None stood the WHOLE geo dimension down --
    and `state/render.py:671` emits `"country": st.key.country or None`, which is a shape the renderer
    produces every day. Measured on a corn_cbot / country=None call @ 3rd pct: "Brazil positioning is
    crowded [N1].", "Argentine corn positioning is crowded [N1]." and "Ukrainian positioning is crowded
    [N1]." all returned `licensed`, and all three return `unbound_adjective` the moment the row carries
    united_states -- the guard was present and simply un-entered. So an EMPTY own scope now contradicts
    whenever the sentence names ANY market (or any country) at all: the row has nothing to claim it
    with, and the licence fails closed exactly as it does for a wrong one."""
    for dim in (0, 1):
        mine = _bar_scope_words(own[dim])
        foreign: set = set()
        for sc in others:
            if sc[dim] and sc[dim] != own[dim]:
                foreign |= _bar_scope_words(sc[dim])
        if dim == 0:
            # THE TWO SIDES READ THE SAME ROSTER, and they must: `mine` is the SLUG's own tokens, so a
            # row whose slug spells its market differently from its node ('french_maize_matif' -> node
            # `corn`, 'brazilian_arabica_coffee' -> exchange BMF) would find its OWN market's word in
            # the foreign set and refuse a sentence that named it correctly. Measured: 2 of the 31
            # declared contracts before this line, 0 after.
            here = _bar_phrase(own[dim])
            node = _bar_canon(here) if here else ""
            for slug, words in _bar_market_vocab():
                if here and (slug in (here, node) or (node and _bar_canon(slug) == node)):
                    mine |= set(words)          # every SURFACE of this row's own market, node included
                else:
                    foreign |= set(words)
        elif not own[dim]:
            named, aggregate = _bar_geo(sent)
            if named and not aggregate:
                return True                     # a row with no country cannot claim one
        foreign -= mine
        # THE SECOND HALF ASKS WHETHER THE SENTENCE NAMES THIS ROW'S MARKET, and an EXCHANGE CODE does
        # not: CBOT lists corn, soybeans, wheat, rice and two meals, so "Soybeans CBOT positioning is
        # crowded [N1]" citing a CORN row was naming corn's venue and reading as if it had named corn.
        # The code stays in `mine` (so it is not foreign to its own row) and leaves this half.
        named_mine = (mine - _bar_exchange_words()) if dim == 0 else mine
        if foreign and any((" " + w + " ") in sent_words for w in foreign) \
                and not any((" " + w + " ") in sent_words for w in named_mine):
            return True
        if dim == 1 and own[dim]:
            named, aggregate = _bar_geo(sent)
            ours, _ = _bar_geo(own[dim])
            if named and ours and not aggregate and not (named & ours):
                return True
    return False


# ── ROUND-5 REVIEW MAJOR 2 (2026-09-15): THE CORRECTING CLAUSE IS THE LANE'S ONE PRINTED FIGURE, SO A
# CLAUSE BOUND TO THE WRONG SUBJECT IS THE BACKED-FIGURE CLASS. Round 4 closed the two-market and the
# two-VENUE comparisons and left three residual ways a corn row's percentile printed itself beside a
# sentence about something else. All three are fixed the same way -- the row simply does not resolve,
# which is the verdict this module has always returned for "the sentence's market is not this row's"
# -- and all three fail CLOSED: when the subject is not the row's own market beyond doubt, NOTHING is
# appended and the sentence ships exactly as the writer wrote it. Words are free; only the figure the
# clause would print has to be backed.
#
#   (a) ONE VENUE NAMED ALONE. "Positioning is crowded on MATIF [N1]." and "...on ICE [N1]." both
#       printed corn_cbot's 42 -- `_bar_subject_market` asks its question only when TWO distinct
#       markets are named, so a single venue was never tested as a subject at all, and `matif` lands
#       in `mine` rather than `foreign` because `french_maize_matif` canonicalises onto node `corn`.
#       A venue named ALONE is a market mention: if it is not one of the ROW'S OWN venues, the subject
#       is foreign. The vocabulary is the estate's own declared exchange codes (`_bar_exchange_words`,
#       read off `commodity_hierarchy.yaml`'s contracts), never a hand list -- and the ICE homonym drop
#       now keeps a venue USED as a venue.
#   (b) A PLACE THE GEO LEXICON CANNOT RESOLVE. "Positioning in Rio Grande do Sul is crowded [N1]."
#       and "...in Heilongjiang..." took the united_states row because `regions.yaml` carried neither
#       surface (both hide behind the harvester's commodity prefix, `Soy_Rio_Grande_Do_Sul`), and
#       "...on Euronext [N1]." took it because Euronext is a venue this estate declares no contract on.
#       An UNRESOLVED capitalised phrase after a locative preposition, inside the adjective's own
#       clause, means the subject is not the row's market beyond doubt -> no clause. The 43 missing
#       bare surfaces are added to `regions.yaml` in the same sitting, so the docstring above is true.
#   (c) TWO MARKETS, BOTH RESOLVED. "Cocoa positioning is crowded [N2] and corn positioning is crowded
#       [N1]." appended COCOA's 52 at the END of a sentence whose last clause is about corn, whose own
#       row reads 42. The clause is appended at the sentence end, so it binds to the LAST clause: it
#       may be printed only when that clause carries the adjective, names this row's market, and names
#       no other. Never the first contradicting row.
def _bar_adj_word(m) -> str:
    """The BAR_ADJECTIVES table's own word for one `_BAR_ADJ_RX` match -- `squeeze` folds its
    inflections. One producer; `bar_adjective_hits` states the same fold inline and predates it."""
    w = m.group(1).lower()
    return "squeeze" if w.startswith("squeez") else w


def _bar_family_adj(sent: str, family: str) -> list:
    """Every bar-adjective match in `sent` belonging to `family`, in written order."""
    return [m for m in _BAR_ADJ_RX.finditer(str(sent or ""))
            if next((f for a, f, _d in BAR_ADJECTIVES if a == _bar_adj_word(m)), "") == family]


def _bar_clause_spans(sent: str) -> list:
    """(start, end) for each CLAUSE of the sentence, split on `_BAR_CLAUSE_EDGE` -- the same edges
    `_bar_speech_act` scopes a negation by, so "which clause is this word in" has one answer here."""
    s = str(sent or "")
    spans, start = [], 0
    for m in _BAR_CLAUSE_EDGE.finditer(s):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(s)))
    return [(a, b) for a, b in spans if s[a:b].strip()]


def _bar_clause_at(sent: str, pos: int) -> tuple:
    """The clause span containing `pos`, or the whole sentence when the split finds none."""
    for a, b in _bar_clause_spans(sent):
        if a <= pos < b:
            return (a, b)
    return (0, len(str(sent or "")))


def _bar_call_venues(call: dict | None) -> frozenset:
    """The VENUE words this row's own market is listed on, read off the same declared contracts the
    market roster is.

    EXACT FIRST. A row scoped on a DECLARED contract (`corn_cbot`) has ONE venue -- its own exchange
    -- which is what makes "Positioning is crowded on MATIF [N1]." foreign to it even though
    `french_maize_matif` canonicalises onto the same node.

    OTHERWISE THE SET WIDENS to every exchange listing a contract this row's own scope NAMES -- such
    a row could be any of them, so naming one is no evidence of a foreign subject. The match is on
    the scope's own WORDS against the contract roster's words, which is `_bar_scope_contradicted`'s
    `mine` and not a second idea of identity.

    TWO MEASUREMENTS BEHIND THOSE TWO LINES, both taken off the estate's own decks, and neither of
    them a hypothetical. (i) The decks drive `cocoa_ice` and `wheat_cbot`, which are NOT contract
    KEYS (the declarations are `cocoa` and `soft_red_winter_wheat_cbot`), so keying the `contracts`
    dict gave them an EMPTY venue set and read their own exchange as foreign -- four round-3/4 pins
    red in one run. (ii) Reading the row's market through `_bar_call_canons` instead fixed cocoa and
    broke wheat, because `_bar_market_rx` assigns ONE canon per word and the first roster entry
    wins: the bare word 'wheat' canonicalises to `french wheat`, so a `wheat_cbot` row claimed MATIF
    as its venue and read CBOT as foreign. A scope that names no contract at all still resolves to
    the empty set, and an empty set claims no venue: every venue the sentence names is then foreign
    to it, which is the fail-closed half and the shape `_bar_scope_contradicted` already takes for a
    row carrying no country."""
    own = _bar_phrase(_bar_scope(call)[0])
    if not own:
        return frozenset()
    mine = _bar_scope_words(own)
    vocab = dict(_bar_contract_vocab())
    exact, wide = set(), set()
    for slug, meta in ((_bar_hier().get("contracts") or {}) or {}).items():
        exch = _bar_phrase((meta or {}).get("exchange") if isinstance(meta, dict) else "")
        if not exch:
            continue
        ph = _bar_phrase(slug)
        if ph == own:
            exact |= _bar_fold(exch)
        elif set(vocab.get(ph) or ()) & mine:
            wide |= _bar_fold(exch)
    return frozenset(exact or wide)


def _bar_foreign_venue(sent: str, call: dict | None) -> bool:
    """Does the sentence name a VENUE, AND NO MARKET FOR IT TO BELONG TO, that is not one of this
    row's own? (review MAJOR 2 (a).)

    ASKED AT ONE VENUE, NOT TWO. The two-venue comparison was round 4's fix and it reads the SUBJECT
    rule; this reads the ROW, so it fires on the single venue that rule can never see. A venue this
    row IS listed on is not foreign and changes nothing -- "Positioning is crowded on CBOT [N1]." off
    a corn_cbot row still earns its clause.

    ALONE IS LOAD-BEARING, and the estate's own seam check is what says so. The ruling's words are "a
    VENUE token named ALONE is a market mention" -- a venue NEXT TO ITS OWN MARKET is not a subject
    claim of its own, it is the market's address, and the two-market subject rule already owns that
    sentence. `config_check`'s register_seam probe drives exactly it: "ICE cocoa positioning is
    crowded [N2] while CBOT corn is quiet [N1]." must resolve weak_adjective against COCOA, and a
    venue test reading the whole sentence made it unbound by calling CBOT foreign to the cocoa row.
    So this half stands down the moment the sentence names any market at all -- and nothing is lost
    by that, because a sentence naming a market AND a foreign venue is a TWO-MARKET sentence to
    `_bar_clause_bound`, which refuses to place a clause beside a venue the row is not listed on.
    Measured: "Corn positioning is crowded on MATIF [N1]." appends nothing, by (c) rather than by
    this line."""
    named = _bar_named_markets(sent, venues=True)
    if any(not c.startswith("venue:") for _p, c in named):
        return False                        # the venue has a market beside it; (c) decides
    venues = {c[len("venue:"):] for _p, c in named}
    return bool(venues - set(_bar_call_venues(call))) if venues else False


#: A LOCATIVE and the capitalised phrase it governs. The connectives are the ones a place name carries
#: inside itself ('Rio Grande do Sul', 'Free State of Bavaria'); every other token of the phrase must
#: itself be capitalised, so an ordinary lower-case noun ends the phrase and is never read as a place.
_BAR_PLACE_PREP = re.compile(
    r"\b(?:in|on|at|from|across)\s+(?:the\s+)?"
    r"([A-ZÀ-Þ][\w'’.-]*"
    r"(?:\s+(?:de|do|da|dos|das|del|du|des|of|the|and)\s+[A-ZÀ-Þ][\w'’.-]*"
    r"|\s+[A-ZÀ-Þ][\w'’.-]*)*)")
#: The capitalised words after a locative that are NOT places and must not fail the sentence closed.
#: THE CALENDAR IS THE ONLY HAND LIST, and it has to be one -- a month is not an entity this
#: estate declares anywhere. Everything else that is not a place is read off the ESTATE'S OWN
#: entity vocabulary below, the same file the market roster's third half comes from.
_BAR_NOT_A_PLACE = re.compile(
    r"^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r"|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?"
    r"|q[1-4]|h[12]|fy|cy|my|ytd)\b", re.I)
#: The entity-vocabulary node classes that name something which is NOT A GEOGRAPHY: a phenomenon,
#: an institution, a rule or a derived series. `region` and `country_origin` are deliberately
#: ABSENT -- a place must resolve through the GEO LEXICON, where the country half of the
#: contradiction test can then judge it, and admitting a region here would let a foreign
#: geography past the guard rather than through it. `commodity` / `fertilizer` / `energy` /
#: `metal` / `freight` are absent too: the market roster already reads them.
_BAR_NON_PLACE_CLASSES = ("climate_driver", "hazard", "beneficial_weather", "organization",
                          "state_marker", "policy_event", "instrument")


def _bar_non_place_vocab() -> frozenset:
    """Every surface the entity vocabulary declares for a thing that is not a geography -- nodes
    and ALIASES, as whole phrases.

    MEASURED (round 5): 'El Nino' and 'La Nina' stood 3 of the 878 real-seat sentences down on the
    (b) rule -- 'on the El Nino edge', 'on the La Nina edge' -- and both are declared
    `climate_driver` nodes. A phase of the ocean is not a place, and the estate says so in its own
    file; the alternative was a second hand list beside the calendar."""
    key = _bar_cfg_key()
    if key in _BAR_NONPLACE_CACHE:
        return _BAR_NONPLACE_CACHE[key]
    out: set = set()
    try:
        import yaml as _yaml

        from leviathan.graphrag import extract as _ex
        data = _yaml.safe_load((_ex._CFG / "entity_vocabulary.yaml").read_text(encoding="utf-8")) or {}
        nodes, aliases = (data.get("nodes") or {}), (data.get("aliases") or {})
        for cls in _BAR_NON_PLACE_CLASSES:
            for node in (nodes.get(cls) or []):
                for surface in [str(node)] + [str(a) for a in (aliases.get(str(node)) or [])]:
                    ph = _bar_phrase(surface)
                    if len(ph) >= 3:
                        out.add(ph)
    except Exception:  # noqa: BLE001 -- no vocabulary -> the half stands down and (b) fails closed
        out = set()
    _BAR_NONPLACE_CACHE[key] = frozenset(out)
    return _BAR_NONPLACE_CACHE[key]


def _bar_place_resolves(phrase: str) -> bool:
    """Can this estate say what the phrase NAMES -- the calendar, a declared non-geography (a
    climate phase, an institution, a rule, a derived series), a country, a sub-national region, one
    of its own markets, or one of its declared venues? Nothing else resolves, and a phrase that
    resolves to nothing is the fail-closed case.

    THE RESIDUAL, NAMED RATHER THAN HIDDEN. Over the 878 real-seat sentences three surfaces resolve
    to nothing: 'Dalian' (the CITY the DCE is named for, which this estate declares only as the
    exchange code `DCE`), 'US' (the geo lexicon carries 'U.S.' and 'USA' and not the bare two-letter
    form, which `_bar_scope_words` drops by name as too ambiguous to read case-blind) and 'SAME' (an
    ordinary English word shouted for emphasis); the ENSO phases were a fourth until the
    entity-vocabulary leg above. NONE of the three sits in the clause of a bar adjective anywhere in
    the corpus, so the measured cost today is ZERO sentences -- and when one does arrive the cost is
    a CORRECTION NOT PRINTED, never a wrong figure printed: words are free, and the sentence ships as
    written.

    ROUND 6 ADDS A NAMED CLASS TO THAT RESIDUAL rather than a hand edit: every region whose harvested
    key carries a COMMODITY PREFIX is reachable only through that prefix ('soy rio grande do sul'),
    so 'Rio Grande do Sul', 'Heilongjiang', 'Jilin', 'Inner Mongolia', 'Liaoning', 'North Dakota',
    'Oklahoma', 'Tennessee' and 'Montana' resolve to nothing and fail their sentences CLOSED. The
    cure is `scripts/harvest_geographies.py` emitting the bare surface, which is an OWNER DOCKET and
    not this lane's file -- see `_bar_region_country` above."""
    ph = str(phrase or "").strip()
    if not ph or _BAR_NOT_A_PLACE.match(ph):
        return True
    if _bar_phrase(ph) in _bar_non_place_vocab():
        return True
    named, aggregate = _bar_geo(ph)
    if named or aggregate:
        return True
    words = _bar_sent_words(ph)
    rx, _w = _bar_market_rx()
    if rx is not None and rx.search(words):
        return True
    return any((" " + v + " ") in words for v in _bar_exchange_words())


def _bar_unresolved_place(text: str) -> str:
    """The first capitalised phrase `text` places with a locative and cannot resolve, or ""."""
    for m in _BAR_PLACE_PREP.finditer(str(text or "")):
        ph = m.group(1).strip()
        if ph and not _bar_place_resolves(ph):
            return ph
    return ""


# == ROUND-6 REVIEW MAJOR (2026-09-15): (b) WAS GRAMMAR-GATED, AND THE SUBJECT SLOT IS THE HALF IT ==
# MISSED. `_BAR_PLACE_PREP` reads a capitalised place only AFTER in/on/at/from/across, so the very
# same unresolved place refused the clause as an ADJUNCT and TOOK it as the sentence's SUBJECT.
# Measured on the shipped tree, corn_cbot / united_states @ 42nd percentile: "Positioning in Dalian is
# crowded [N1]." appended nothing and "Dalian positioning is crowded [N1]." appended the US board's
# own 42 -- a CBOT percentile printed beside a sentence about the DCE's home city. TEN of twenty
# probed surfaces did it (Dalian, Zhengzhou, Rosario, Paranagua, Santos, Rotterdam, Sinaloa, Midwest,
# Black Sea, Pampas) and five of those are ordinary desk vocabulary in this estate's own prose, so it
# is reachable writing rather than a constructed shape.
#
# THE SUBJECT SLOT IS A GRAMMAR CLAIM THIS MODULE CAN MAKE, and it is the one `_bar_subject_market`
# already makes: English puts the subject before its predicate. A capitalised phrase that HEADS the
# adjective's own clause and is followed IMMEDIATELY by a DESK NOUN ("Dalian positioning", "Black Sea
# basis", "Inner Mongolia net length") is claiming to be the subject of that reading; when this estate
# cannot name it, the sentence stands down exactly as the locative half stands it down.
#
# ADJACENCY IS LOAD-BEARING, and so is ALONE -- the second for the reason round 5 gave the venue half.
#   * IMMEDIATELY: "US corn positioning is crowded [N1]." is an honest positive and 'US' is a NAMED
#     RESIDUAL of `_bar_place_resolves` (the geo lexicon carries 'U.S.' and 'USA', never the bare
#     two-letter form). Letting a market word sit between the phrase and the desk noun would refuse
#     it. So "Dalian corn positioning is crowded [N1]." is NOT read here -- it is a market mention
#     with a place beside it, and the geo dimension owns it.
#   * NOT ALONE (round-6 close-out): an earlier cut stood this half down whenever the clause named a
#     market, on the argument that "Managed-money length in corn is crowded [N1]." needed it. It did
#     not -- 'Managed-money' is a desk qualifier the numbers registry DECLARES (`_bar_desk_words`) --
#     and the bound fail-opened the class this half exists to close ("Dalian positioning in corn is
#     crowded [N1]." printed the CBOT figure). A foreign subject stays foreign however many of the
#     row's own market words follow it; the cost, measured, is two constructed sentences that lose a
#     correction and fail closed.
#
# AND THE HEAD MAY NOT BE A DESK WORD ITSELF: "Net length is crowded [N1].", "Spread is rich [N1]." and
# "Board crush is rich [N1]." are desk readings whose own noun phrase opens with the desk vocabulary,
# not places; the leading article / conjunction words are skipped for the same reason ("The positioning
# is crowded [N1].", "..., while corn positioning is crowded [N1].").
#: The desk nouns a reading is claimed OF -- the ruling's own list. The multi-word entries come FIRST
#: in the alternation so 'net length' is read whole rather than as the name 'Net'.
_BAR_DESK_NOUN = (r"(?i:net\s+length|open\s+interest|positioning|length|basis|crush|spread|board"
                  r"|reading)")
#: The function words that may stand before the subject without BEING it.
_BAR_HEAD_STOP = r"(?i:the|a|an|and|but|so|yet|while|as|which|that|though|although|because)\b"
#: One capitalised token, and the phrase built from them -- the same shape `_BAR_PLACE_PREP` reads
#: after a locative, with the same internal connectives ('Rio Grande do Sul').
_BAR_NAME_TOK = r"[A-ZÀ-Þ][\w'’.-]*"
_BAR_SUBJECT_HEAD = re.compile(
    r"^[\s\"'“‘(\[*_]*(?:" + _BAR_HEAD_STOP + r"\s+)*"
    r"((?!" + _BAR_HEAD_STOP + r")(?!" + _BAR_DESK_NOUN + r"\b)" + _BAR_NAME_TOK +
    r"(?:\s+(?:(?i:de|do|da|dos|das|del|du|des|of|the|and)\s+)?"
    r"(?!" + _BAR_DESK_NOUN + r"\b)" + _BAR_NAME_TOK + r")*)"
    r"\s+" + _BAR_DESK_NOUN + r"\b")


#: One more one-entry-per-config memo, same key, same reason as the four above it.
_BAR_DESKW_CACHE: dict = {}
#: A HYPHEN FOLLOWED BY A LOWER-CASE LETTER is English's own mark of a COMPOUND MODIFIER --
#: 'Managed-money', 'Reporting-fund', 'Non-commercial' -- and never of a proper name: a hyphenated
#: place carries a capital or a connective on the far side ('Guinea-Bissau', 'Rhone-Alpes').
_BAR_COMPOUND_MOD = re.compile(r"-[a-zà-þ]")


def _bar_desk_words() -> frozenset:
    """Every word this estate itself spells in the METRIC LABELS (and metric names) of the tables the
    BAR FAMILIES read -- silver_cot, silver_mpob, gold_board_crush, gold_futures_spreads, taken off
    `_bar_ref_index` so the vocabulary follows the families rather than a constant.

    THE REGISTRY IS THE PRODUCER, not a hand list, and it is the RIGHT producer: these are the words
    the estate uses for the readings a desk noun refers to -- 'managed-money net position', 'open
    interest', 'board crush margin', 'front-month spread', 'palm oil closing stocks'. Scoped to the
    four tables and not to the whole registry, because a wide vocabulary would start exempting the
    place words the guard exists to catch. Unreadable registry -> empty set -> the exemption stands
    down and the guard fails closed, which is this module's rule everywhere."""
    key = _bar_cfg_key()
    if key in _BAR_DESKW_CACHE:
        return _BAR_DESKW_CACHE[key]
    out: set = set()
    reg = _bar_registry()
    if reg is not None:
        for table in {t for t, _m in _bar_ref_index()}:
            try:
                metrics = getattr(reg.get(str(table)), "metrics", None) or {}
                for name, meta in dict(metrics).items():
                    text = "%s %s" % (getattr(meta, "label", "") or "", name)
                    out |= {w for w in re.split(r"[^a-z0-9]+", _bar_ascii(text).lower()) if w}
            except Exception:  # noqa: BLE001,PERF203 -- an unreadable card exempts nothing
                continue
    _BAR_DESKW_CACHE[key] = frozenset(out)
    return _BAR_DESKW_CACHE[key]


def _bar_desk_subject(phrase: str) -> bool:
    """Is this clause head a DESK QUALIFIER rather than a name? (round-6, measured.)

    A capital at the head of a clause is FORCED by position, so 'Managed-money' and 'Dalian' are
    spelled identically and no case test can tell them apart. Two marks can, and both were measured on
    the estate's own 1,021 real-seat sentences, where the subject-claim heads are exactly
    'Managed-money', 'Reporting-fund', 'Pacific', 'ONI' and 'Dalian':
      * the phrase is spelled out of the READING'S OWN VOCABULARY ('Managed-money', 'Managed money',
        'Net', 'Open', 'Board'), which the numbers registry declares; or
      * it is a COMPOUND MODIFIER by its own hyphen ('Reporting-fund', 'Non-commercial').
    THE RESIDUAL IS NAMED: an unhyphenated desk qualifier outside the registry's own words
    ('Speculative positioning is crowded [N1].') is read as a subject claim and stands its sentence
    down -- a correction not printed, and the D-EC decline clause in its place. 0 such sentences in
    the 1,021, and the cure is a LABEL in the registry rather than a list here."""
    ph = str(phrase or "").strip()
    if not ph:
        return False
    if _BAR_COMPOUND_MOD.search(ph):
        return True
    words = [w for w in re.split(r"[^a-z0-9]+", _bar_ascii(ph).lower()) if w]
    desk = _bar_desk_words()
    return bool(words) and bool(desk) and all(w in desk for w in words)

def _bar_subject_place(clause: str) -> str:
    """The capitalised phrase that HEADS `clause`, claims to be the subject of a desk reading, and
    names something this estate cannot resolve -- or "" when there is no such claim.

    A DESK QUALIFIER IS NOT A CLAIM ABOUT A SUBJECT AT ALL -- 'Managed-money positioning',
    'Reporting-fund length' -- and `_bar_desk_subject` above says so out of the registry's own metric
    labels. That half is load-bearing and was measured the hard way: without it this guard refused
    the estate's own flagship LICENSED sentence (the census line this fence was built for) and turned
    a `licensed` verdict into a CHARGE, which is a worse move than the one it was closing.

    OTHERWISE THE PREDICATE IS `_bar_place_resolves`, UNCHANGED: the calendar, a declared
    non-geography, a country, a sub-national region, one of the estate's own markets or one of its
    declared venues. A phrase that RESOLVES is left to the machinery that can judge it -- the geo
    dimension refuses a foreign country or region and the market half refuses a foreign market --
    and only a phrase the estate cannot name at all reaches the fail-closed branch, because no row
    can claim a subject nobody can name. Nothing here strikes: the sentence ships as written,
    without the correction."""
    m = _BAR_SUBJECT_HEAD.match(str(clause or ""))
    if not m:
        return ""
    ph = m.group(1).strip()
    if not ph or _bar_desk_subject(ph) or _bar_place_resolves(ph):
        return ""
    # NO "alone" bound (round-6 close-out): standing this half down whenever the clause names a
    # market re-admitted the exact class it exists to close -- "Dalian positioning in corn is
    # crowded [N1]." printed the CBOT row's figure beside a DCE claim (8 of 8 probed shapes). The
    # desk qualifiers the bound was written for ("Managed-money length in corn") are exempted by
    # _bar_desk_subject's registry producer, so the bound bought nothing real: measured, 0 of 105
    # deck literals and 0 of 1,021 real-seat sentences change; two constructed sentences ("US
    # positioning in corn", "Speculative positioning in corn") lose a correction and fail CLOSED.
    return ph


def _bar_clause_bound(sent: str, word: str, canons, venues) -> bool:
    """May a correcting clause printed at the SENTENCE END be read as belonging to THIS row?
    (review MAJOR 2 (c).)

    A sentence naming ONE market or none is unchanged: the per-row contradiction test, the subject
    rule and the two guards above have already decided it, and the clause lands beside the only
    market there is. When TWO are named the clause has to be PLACED, and this module cannot place it
    -- `answer._bind_bar_adjectives` appends at the sentence END, where a reader binds it to the LAST
    clause. So the last clause must carry the adjective, must name this row's market, and must name
    no other. Anything else appends nothing at all."""
    named = _bar_named_markets(sent, venues=True)
    if len({c for _p, c in named}) < 2:
        return True
    spans = _bar_clause_spans(sent)
    if not spans:
        return False
    lo, hi = spans[-1]
    if not any(lo <= m.start() < hi for m in _BAR_ADJ_RX.finditer(str(sent or ""))
               if _bar_adj_word(m) == word):
        return False                            # the word this clause corrects is in another clause
    here = {c for p, c in named if lo <= p < hi}
    if not here:
        return False                            # ...and a clause naming no market names no subject
    return all((c[len("venue:"):] in set(venues)) if c.startswith("venue:") else (c in set(canons))
               for c in here)


def _bar_current_rows(call: dict | None) -> list:
    """The rows of one call at its NEWEST knowledge date -- the only rows a PRESENT verdict's bar may
    read. When no row on the call carries a knowledge date, every row participates (the board's own
    single-row `sb_call` shape, unchanged)."""
    rows = [r for r in ((call or {}).get("rows") or []) if isinstance(r, dict)]
    kds = [str(r.get("knowledge_date") or "").strip() for r in rows]
    kds = [k for k in kds if k]
    if not kds:
        return rows
    top = max(kds)
    return [r for r in rows if str(r.get("knowledge_date") or "").strip() == top]


# ── ROUND-3 REVIEW MAJOR 3 (2026-09-15): THE ROW WAS SCOPED IN TIME ONLY AGAINST ITS OWN SIBLINGS.
# `_bar_current_rows` keeps the call's NEWEST knowledge date, which closed the mixed-row probe
# ([55th @2026-09-05, 3rd @2019-04-02] -> weak_adjective). But a call whose newest row is ITSELF
# ancient was not bounded at all: rows=[{3rd pct, knowledge_date 2011-01-04}] with query.asof
# 2026-09-05 returned `licensed` for the present-tense "Corn positioning is crowded [N1]." -- a
# fifteen-year-old reading licensing a present verdict. The estate has live precedent for exactly this
# (the 42-day gold_weather_z freeze, 70fa5828, served and reported healthy the whole time).
#
# THE BOUND IS THE CARD'S OWN PROMISE, READ THROUGH THE ONE FUNCTION THAT OWNS IT. `registry
# .lag_days_for(table, metric)` landed at 29de55eb precisely to answer "is this served", and the bound
# is that lag + the card's own PERIOD (its `cadence`) + a stated MARGIN:
#     daily 1 | weekly 7 | biweekly 14 | monthly 31 | annual 366, and an unreadable cadence takes the
#     MODAL card's 31 rather than a guess of its own;
#     the margin is 7 days, and it is the same kind of margin 29de55eb's own per-metric lags carry
#     ("plus a two-day margin", "plus a three-day margin") -- a licence is a question about whether
#     this is the CURRENT reading, not about a publisher's SLA, and a weekend plus a public holiday
#     must not turn Friday's settle into a stale one.
# MEASURED on the three cards the licence can actually reach: silver_cot (weekly, publication lag 6)
# bounds at 20 days; gold_futures_spreads (daily, lag 1) at 9; silver_mpob (monthly, lag 43) at 81.
#
# IT FAILS CLOSED ON THE LICENCE AND OPEN -- AND HONEST -- ON THE PAGE. A row past the bound resolves
# `weak_adjective`, whose remedy NAMES THE ROW'S OWN DATE ("the newest served reading for that market
# is dated 2011-01-04"): the sentence stands, its handle stands, and the one fact the reader was
# missing is put beside the word. A row carrying NO knowledge date, or a turn carrying no `asof`, is
# not measurable and is not charged -- silence, never a fabricated staleness.
_BAR_CADENCE_DAYS = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 31, "annual": 366}
_BAR_STALE_PERIOD_DEFAULT = 31                  # the modal card's cadence, used when none is declared
_BAR_STALE_MARGIN_DAYS = 7
_BAR_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _bar_registry():
    """The numbers registry, memoised on the resolved config path (the other three bar reads' rule).
    None when unreadable -- the freshness bound then falls back to its stated default."""
    key = _bar_cfg_key()
    if key in _BAR_REG_CACHE:
        return _BAR_REG_CACHE[key]
    try:
        from leviathan.graphrag.numbers import registry as _nr
        _BAR_REG_CACHE[key] = _nr.load_registry()
    except Exception:  # noqa: BLE001 -- no registry is not an error here; it is an unmeasurable bound
        _BAR_REG_CACHE[key] = None
    return _BAR_REG_CACHE[key]


def _bar_freshness_bound(call: dict | None) -> int:
    """How many days past the turn's `asof` this call's newest row may sit and still be CURRENT."""
    q = ((call or {}).get("query") or {})
    lag, cadence = None, ""
    reg = _bar_registry()
    if reg is not None:
        try:
            from leviathan.graphrag.numbers import registry as _nr
            ts = reg.get(str(q.get("table") or ""))
            lag = _nr.lag_days_for(ts, str(q.get("metric") or ""))
            if lag is None:
                lag = getattr(ts, "publication_lag_days", None)
            cadence = str(getattr(ts, "cadence", "") or "").strip().lower()
        except Exception:  # noqa: BLE001 -- an unknown card takes the default, never a guess
            lag, cadence = None, ""
    period = _BAR_CADENCE_DAYS.get(cadence, _BAR_STALE_PERIOD_DEFAULT)
    try:
        lag = int(lag or 0)
    except (TypeError, ValueError):
        lag = 0
    return max(0, lag) + period + _BAR_STALE_MARGIN_DAYS


def _bar_row_stale(call: dict | None, row: dict | None) -> str:
    """The row's own knowledge date when it sits PAST the call's freshness bound, else "". Pure: the
    comparison is against the TURN's `asof` and never against a clock."""
    q = ((call or {}).get("query") or {})
    asof = str(q.get("asof") or "").strip()
    kd = str((row or {}).get("knowledge_date") or "").strip()
    if not _BAR_DATE_ONLY.match(asof) or not _BAR_DATE_ONLY.match(kd):
        return ""
    try:
        a = _dt.date(int(asof[:4]), int(asof[5:7]), int(asof[8:10]))
        k = _dt.date(int(kd[:4]), int(kd[5:7]), int(kd[8:10]))
    except ValueError:
        return ""
    # TWO-SIDED (round-4 review MINOR): a row dated AFTER the turn's own as-of is not "current", it is
    # a point-in-time defect -- the estate has live precedent for it (`_pub_date` wrong-early 28.9%,
    # the X2 precondition) -- and this is the guard asking "is this the CURRENT reading". It is charged
    # like any other unusable row: no licence to contradict, so no clause (ruling (3)'s fail-closed).
    if (k - a).days > 0:
        return kd
    return kd if (a - k).days > _bar_freshness_bound(call) else ""


def _bar_readings(sent: str, number_calls: list | None, family: str) -> list:
    """Every percentile reading the sentence's own [N] handles resolve to INSIDE `family`, as
    {"pct", "stale"}: scoped to the row's own SERIES, to that call's newest knowledge date, to the
    freshness bound above, and -- when the sentence names two markets -- to the market its adjective's
    own SUBJECT is (review MAJOR 4).

    SAME-SENTENCE ONLY, which is `bare_digit_verdict`'s scope and `_check_number_handle`'s. The census
    read "same-or-adjacent"; widening the scope here would let a neighbour's row license a word this
    sentence never bound, and on the censused corpus it changes no verdict (every adjacent-bound row in
    it belongs to a sentence the speech-act clauses already exempt)."""
    calls = list(number_calls or [])
    idx = _bar_ref_index()

    def _in_family(c) -> bool:
        q = ((c or {}).get("query") or {})
        return idx.get((str(q.get("table") or ""), str(q.get("metric") or ""))) == family

    # THE TURN'S OWN COMPETING SCOPES, computed once: every OTHER series of this family on this answer.
    fam_scopes: list = []
    for c in calls:
        if _in_family(c):
            sc = _bar_scope(c)
            if sc not in fam_scopes:
                fam_scopes.append(sc)
    words = _bar_sent_words(sent)
    subject = _bar_subject_market(sent, family)
    # (b) AN UNRESOLVED PLACE IN THE ADJECTIVE'S OWN CLAUSE STANDS THE WHOLE SENTENCE DOWN, whether
    # the writer PLACES it with a locative or makes it the SUBJECT (round-6 review MAJOR). It is
    # asked of the sentence rather than of a row because NO row can claim a place this estate
    # cannot name: 'Rio Grande do Sul', 'Heilongjiang' and 'Euronext' all took a united_states corn
    # row as ADJUNCTS, and 'Dalian', 'Black Sea', 'Midwest' and 'Pampas' all took one as SUBJECTS.
    # Scoped to the clause the adjective sits in, so a foreign place mentioned in a LATER clause
    # ('...as Brazilian rain returns') is left to the geo dimension it belongs to.
    for _m in _bar_family_adj(sent, family):
        _a, _b = _bar_clause_at(str(sent or ""), _m.start())
        _clause = str(sent or "")[_a:_b]
        if _bar_unresolved_place(_clause) or _bar_subject_place(_clause):
            return []
    out: list = []
    for m in _HANDLE.finditer(str(sent or "")):
        for kind, i in _handle_members(m.group(0)):
            if kind != "N" or not (1 <= i <= len(calls)):
                continue
            call = calls[i - 1] or {}
            if not _in_family(call):
                continue
            own = _bar_scope(call)
            if _bar_scope_contradicted(str(sent or ""), words, own,
                                       [s for s in fam_scopes if s != own]):
                continue                        # the sentence's market is not this row's market
            if subject is not None and subject not in _bar_call_canons(call):
                continue                        # ...and this row is not the SUBJECT's market
            if _bar_foreign_venue(str(sent or ""), call):
                continue                        # (a) ...nor is it listed on the venue it names
            for r in _bar_current_rows(call):
                if str((r or {}).get("unit") or "").strip().lower() != "percentile":
                    continue
                try:
                    pct = float(str(r.get("value")).replace(",", ""))
                except (TypeError, ValueError):
                    continue
                out.append({"pct": pct, "stale": _bar_row_stale(call, r),
                            "canons": frozenset(_bar_call_canons(call)),
                            "venues": _bar_call_venues(call)})
    return out


# ── ROUND-3 REVIEW MAJOR 4 (2026-09-15): A COMPARISON NAMES TWO MARKETS AND THE OLD RULE OR-ED OVER
# EVERY HANDLE. `_bar_scope_contradicted` asks only whether the sentence names a competing market while
# naming NOTHING of the row's own -- so a sentence naming BOTH satisfies it for BOTH rows, and the
# first handle that cleared the bar won. Measured with calls [corn_cbot @3rd, cocoa @52nd]: "Cocoa
# positioning is crowded [N2] while corn is not [N1]." resolved `licensed` OFF CORN'S 3rd PERCENTILE
# while the cocoa row its own subject cites reads 52 (weak_adjective on its own) -- and a `licensed`
# verdict appends no clause, so an unqualified cross-market crowding call shipped.
#
# THE SUBJECT IS THE NEAREST MARKET TO THE ADJECTIVE'S LEFT, and that is a grammar claim this module can
# actually make: English puts the subject before its predicate, and every shape in the census reads that
# way ("Cocoa positioning is crowded", "CBOT corn managed-money positioning is crowded"). It is asked
# ONLY when the sentence names two DISTINCT markets -- one market named once or five times is not a
# comparison, and a sentence naming none keeps the heading's subject exactly as before. When two are
# named and none sits to the adjective's left, the subject is UNRESOLVED and the licence fails closed
# (`_BAR_NO_SUBJECT`, which no call can ever match) -- the ruling's own "if it cannot resolve the
# subject, unbound".
_BAR_NO_SUBJECT = "\x00unresolved"


def _bar_subject_market(sent: str, family: str) -> str | None:
    """The canonical market this sentence's bar adjective is ABOUT, or None when the sentence is not a
    comparison (and the per-row contradiction test decides alone)."""
    named = _bar_named_markets(sent, venues=True)
    if len({c for _p, c in named}) < 2:
        return None
    s = str(sent or "")
    heads = [m.start() for m in _bar_family_adj(s, family)]
    if not heads:
        return None
    left = [(p, c) for p, c in named if p < heads[0]]
    return left[-1][1] if left else _BAR_NO_SUBJECT


def _bar_percentiles(sent: str, number_calls: list | None, family: str) -> list[float]:
    """The bare percentile readings of `_bar_readings` -- the shape the probes and the deck read."""
    return [r["pct"] for r in _bar_readings(sent, number_calls, family)]


def bar_adjective_hits(sent: str) -> list[str]:
    """The bar adjectives one sentence carries, lower-cased, in written order. `squeeze` folds its own
    inflections (`squeezes` / `squeezed` / `squeezing`) onto the table's word."""
    out: list[str] = []
    for m in _BAR_ADJ_RX.finditer(str(sent or "")):
        w = m.group(1).lower()
        w = "squeeze" if w.startswith("squeez") else w
        if w not in out:
            out.append(w)
    return out


#: The report's shape, so every return carries every key and a reader never has to ask whether a key
#: is absent or false. `pct` / `band` / `word` are the FIGURE-CONTRADICTION facts the owner's ruling
#: (3) asks the clause to name; they are present only when a row of the adjective's own family
#: resolved and was fresh.
_BAR_NO_REPORT: dict = {"verdict": None, "stale": "", "pct": None, "band": (), "word": ""}


def bar_adjective_report(sent: str, number_calls: list | None = None, *,
                         conventions: dict | None = None) -> dict:
    """S7b R1's per-SENTENCE verdict AND the facts its remedy needs beside it, as
    ``{"verdict", "stale", "pct", "band", "word"}``.

    ROUND 4 (WORDS ARE FREE): the verdict no longer decides a STRIKE -- nothing here ever did, and now
    nothing downstream does either. Its one remaining job is the CORRECTING CLAUSE, which is why the
    report carries the served figure (`pct`), the desk convention's own band (`band`) and the adjective
    it belongs to (`word`): the ruling asks the clause to NAME the figure and the band, and a clause
    that names them must be handed them rather than recomputing them beside the producer that knew.

    ONE PRODUCER, TWO READERS. `bar_adjective_verdict` is this function's verdict and nothing else, so
    `register._is_banned_sentence`'s licence clause keeps its exact signature; `answer
    ._bind_bar_adjectives` calls THIS one, because the freshness clause (review MAJOR 3) has to name a
    date and a verdict string cannot carry one. A second producer of "which row licensed this" is the
    F-L drift class this estate names by hand, so there is not one."""
    s = str(sent or "")
    words = bar_adjective_hits(s)
    if not words:
        return dict(_BAR_NO_REPORT, verdict=None)
    if _bar_speech_act(s, words):
        return dict(_BAR_NO_REPORT, verdict="not_a_verdict")
    resolved, stale, inside = False, "", None
    for w in words:
        fam, side = next(((f, d) for a, f, d in BAR_ADJECTIVES if a == w), ("", ""))
        bands = _bar_bands(fam, conventions)
        if not bands:
            continue
        lo, hi = bands
        for r in _bar_readings(s, number_calls, fam):
            resolved = True
            if r["stale"]:
                # A STALE ROW CHARGES AND NEVER LICENSES -- AND NEVER CONTRADICTS (ruling (3)): the
                # reading resolved, so this is not `unbound`, but a row past its own card's promise
                # cannot be the figure a correcting clause names. The date rides the report for the
                # trace and the census; no clause is appended off it.
                stale = stale or r["stale"]
                continue
            pct = r["pct"]
            if (side in ("low", "tail") and pct <= lo) or (side in ("high", "tail") and pct >= hi):
                return dict(_BAR_NO_REPORT, verdict="licensed", pct=pct, band=(lo, hi), word=w)
            if inside is None and _bar_clause_bound(s, w, r.get("canons") or frozenset(),
                                                   r.get("venues") or frozenset()):
                inside = (pct, (lo, hi), w)      # (c) the first contradicting row THE CLAUSE CAN
                                                 # BE READ AGAINST -- never simply the first
    if resolved:
        out = dict(_BAR_NO_REPORT, verdict="weak_adjective", stale=stale)
        if inside is not None:
            out.update(pct=inside[0], band=inside[1], word=inside[2])
        return out
    return dict(_BAR_NO_REPORT, verdict="unbound_adjective")


def bar_adjective_verdict(sent: str, number_calls: list | None = None, *,
                          conventions: dict | None = None) -> str | None:
    """S7b R1's per-SENTENCE verdict (`register._is_banned_sentence`'s licence clause calls exactly
    this; the REMEDY calls `bar_adjective_report`, which returns this verdict and the stale row's date
    beside it).

      None                 -- the sentence carries no bar adjective. Nothing to charge, nothing to
                              license: the shipped fence keeps every decision it has today.
      "not_a_verdict"      -- the adjective is DENIED in its own clause, sits under a conditional or
                              mechanism frame, or belongs to a dated receipted fact. Counted, never
                              charged. On the census corpus that is 10 of the 11 charged sentences.
      "licensed"           -- a present verdict whose own [N] handle resolves to a row that CLEARS the
                              adjective's declared bar. Counted, never charged; the word stands as
                              written.
      "weak_adjective"     -- a present verdict whose row resolves and does NOT clear the bar, OR whose
                              row is PAST ITS CARD'S OWN FRESHNESS BOUND (review MAJOR 3). Charged. The
                              remedy BINDS THE ROW'S OWN FIGURE beside the word, or names its date.
      "unbound_adjective"  -- a present verdict with no percentile row of the right family THAT THE
                              SENTENCE'S OWN MARKET CAN CLAIM: no handle, no row of that family, a row
                              whose series the sentence contradicts (review MAJOR 1/2), a row that is
                              not the market its adjective's SUBJECT names (review MAJOR 4), or only
                              rows older than the call's own newest knowledge date. Charged. The remedy
                              is the D-EC DECLINE clause, which keeps the sentence and its own honest
                              words and states what is missing rather than denying the citation.

    NOTHING HERE STRIKES A SENTENCE, and no verdict this function returns may be used to. The correcting
    fence's only moves are APPEND and word-for-word SUBSTITUTE -- the `_JARGON_SUBS` capability -- never
    the cycle-10 capability (numeral for numeral), which was deleted because a fence comparing unit
    labels cannot see semantics ("roughly 0.6 z higher [N3]" -> "roughly -0.6267 z higher [N3]").

    PURE: no environment, no clock, no network. The freshness bound compares the row's knowledge date
    to the TURN'S OWN `asof` for exactly that reason. `conventions` is threaded when the caller holds
    the block already; None reads the board's own cached loader."""
    return bar_adjective_report(sent, number_calls, conventions=conventions)["verdict"]


def _bar_speech_act(sent: str, words: list[str]) -> bool:
    """Is every bar adjective in this sentence something OTHER than a present verdict? (negation in its
    own clause, a conditional/mechanism frame, or a dated receipted fact)."""
    s = str(sent or "")
    if _BAR_CONDITIONAL.search(s):
        return True
    if _BAR_DATE.search(s) and _HANDLE.search(s):
        return True
    for m in _BAR_ADJ_RX.finditer(s):
        head = s[:m.start()]
        edges = [e.end() for e in _BAR_CLAUSE_EDGE.finditer(head)]
        clause = head[edges[-1]:] if edges else head
        if not _BAR_NEGATOR.search(clause):
            return False
    return bool(words)


# == D-DA UNIT-VOCABULARY GATE (2026-09-06) -- RULE (g)'s STATED RESIDUAL, CAUGHT AT THE CHARGE SITE ====
# THE DOCKETED FOLLOW-UP THE RULE-(g) NOTE PROMISED, BUILT. That note closes with the residual it refused
# to hide: rule (g) is STRUCTURAL ("this numeral is a label's scale"), so a MIS-TRANSCRIBED scale is
# exempted exactly as a correct one is. The measured example is the one the residual pin has held in the
# open since the rule shipped -- `test_verify_unit_scale.py::test_major2_...`, written to go RED the day
# this gate landed, and rewritten as `..._is_caught_at_the_charge_site` on that day, which is today:
# the served row prints `(1000 MT)`, the model writes
#     "US corn feed use is 154,947 (9999 MT) [N1]"
# and 9999 was charged by NOTHING -- the extractor exempts it exactly as it exempts 1000, `quote_mismatch`
# (`_unbacked_quote`) inspects QUOTED spans only, and the footer lane reads the engine's own unit column,
# never the model's prose. The same hole covers a bare second figure standing before a unit word
# ("5900 9999 MT"), which no reading of the SENTENCE ALONE can tell from the legitimate "-83.476 1000 MT".
#
# THE CATCHER IS THE ONE THAT NOTE NAMED, AND IT LIVES WHERE THE SENTENCE MEETS ITS ROWS. The extractor
# cannot take this decision: it is a PURE function of the sentence (and its signature is frozen by the
# cycle-8 termination branch), while the fact that separates 9999 from 1000 is not in the sentence at all
# -- it is in the UNIT STRINGS the sentence's own served rows print. So the gate is a POST-FILTER at the
# charge site and the extractor does not move: `_claim_number_spans` still exempts the token, and
# `_check_number_handle` RE-ADMITS it as a claim when no served row of that sentence prints it. The
# vocabulary is read off the rows the estate actually serves -- `citations.from_number` renders
# `= {value} {unit}` from `row["unit"]` -- so "(1000 MT)", "1000 60 KG BAGS", "60-kg bags",
# "COP per 125-kg carga" and "MMT (cotton: million 480-lb bales)" contribute {1000}, {1000, 60}, {60},
# {125} and {480} respectively.
#
# IT MAY ONLY EVER *ADD* A CHARGE, AND THAT ONE-SIDEDNESS IS ENFORCED BY WHERE THE VALUE IS FED IN. A
# re-admitted token joins `guard_nums` -- the `number_unbacked` all-rows guard -- and NEVER the
# `number_mismatch` pool. `_num_matches` is an ANY-of predicate, so handing it one more numeral could only
# ever RESCUE a mismatched sentence (a mis-transcribed 9999 that happened to coincide with some row value
# would count as the sentence's one match), which is the opposite of what a catcher is for. Feeding the
# guard alone also keeps the remedy PROPORTIONATE, which is what the rule-(g) note demanded of any
# catcher: `number_unbacked` strips the mis-citing HANDLE and leaves the sentence standing, where the
# fail-closed `number_mismatch` would delete it whole.
#
# THE FENCE IS "WHAT THE ROWS THEMSELVES DECLARE", AND IT FAILS OPEN ON EVERY GAP IN THAT RECORD.
# The gate charges only where the served rows state a scale vocabulary and the prose writes one outside it;
# everywhere the record is silent or partial it stands down, and the stand-down is ROW-GRANULAR:
#   * a cited call ANY of whose served rows carries no `unit` makes the sentence's vocabulary UNKNOWN and
#     the gate STANDS DOWN for that whole sentence (the verdict stays the structural one). Row-granular,
#     not call-granular, because `citations.from_number` prints `r['unit'] or _metric_unit(...)`: a row
#     that recorded no unit was still shown to the reader wearing the REGISTRY's label, so a vocabulary
#     built from its unit-bearing neighbours alone would charge the model for copying what the citation
#     printed. MEASURED: 83 of 4074 served calls in the banked corpus are mixed this way (2.0%; 1212
#     empty, 2197 all-unit, 582 no-unit) and 1 of the 46 label-bearing sentences already cites one.
#   * a served row whose unit string carries NO NUMERAL ('MMT', '%', '$/bu') states no SCALE, and that is
#     not the same fact as 'this metric's label has no scale': the registry itself declares
#     "MMT (cotton: million 480-lb bales)" for the very metrics whose rows print the bare "MMT", so a
#     model writing the full label would be charged for the 480 the short row never had room for. Such a
#     row makes the vocabulary UNKNOWN exactly as an unrecorded unit does. THE PRICE IS MEASURED AND
#     STATED: numeral-free units are 2,281 of 2,515 unit-bearing row prints in the banked corpus (90.7%,
#     28 of 30 distinct strings), and standing them down narrows the gate's reach on the control arm from
#     7 of 17 exempted tokens to 4 -- with 0 verdicts moved anywhere in the corpus. One word reverts it
#     to the fail-closed reading (`_UL_VOCAB_NUM.search(u)` -> `u`), and both readings are pinned.
#   * an empty or errored call (`rows: []`) served nothing and states nothing: skipped, never a stand-down.
#   * a sentence citing no in-range [N] handle has no served rows at all -- nothing to check, no charge.
#   * GRAPHRAG_VERIFY_UNIT_VOCAB=off is the documented rollback to the pre-gate charge, byte for byte, the
#     shape `GRAPHRAG_VERIFY_NUM_POOL` / `GRAPHRAG_VERIFY_NUM_MODE` / `GRAPHRAG_CASCADE_QUANT` already
#     have -- and GRAPHRAG_CASCADE_QUANT=off takes the gate with it, at the gate itself rather than at
#     the charge site alone, because the `strip_audit` call below sits OUTSIDE the quant branch and under
#     quant-off would otherwise have listed a magnitude no charge could have used.
#
# MEASURED on the arm rule (g) itself was measured on (`data/batch_runs/
# da_baseline_control_20260904T141206Z.json`, 7 answers, 329 served calls in 25-60 per answer, 266
# sentences by this module's own `_SENT_SPLIT` -- i.e. `claim_count`, the strip-rate denominator --
# replayed end to end through `verify_citations`): 17 rule-(g) scale tokens exempted across 10
# sentences -- 4 of them printed by a served row of their own sentence (vocabulary {1000}), 13
# standing the gate down (the cited call recorded no `unit`, or recorded one with no numeral in it),
# and 0 re-admitted. by_rule is byte-identical to the shipped rule: number_unbacked 3,
# number_mismatch 6, undeclared_unsupported 41, 50 strips -- and so is every one of the nine banked
# prose artifacts together (124 / 28 / 713, 865 strips).
# The gate does not re-open the 33-of-35 false-positive class, and the 13 stand-downs are the honest price
# of refusing to reach for the registry: the gate's reach is exactly as wide as the rows' own recorded
# SCALES, and no wider.
#
# WHAT IT COSTS TO RUN, because a verifier runs on every answer. The gate re-reads the sentence once per
# HANDLE inside `_check_number_handle` and again per audit row, so the honest unit of cost is EXTRACTOR
# RUNS, which is deterministic and reproducible on any box (wall clock on this shared one is not: the
# same file measured -3.4%, +3.8% and +26.2% across three unpaired runs, and +10.7% median with a
# -2.4%..+25.7% p10-p90 across 25 paired rounds). Per control arm, `_claim_number_spans` runs 406 times
# at HEAD. Written naively the gate took that to 603 (+48.5%). Two shape-preserving moves bring it to
# 411 (+1.2%): the CHEAP vocabulary question is asked before the expensive label scan (so 197 walks buy
# 5 scans instead of 197), and the scan itself returns before touching the extractor on a sentence that
# holds no digit-then-unit-word shape at all (`_UL_ANY`). Both are identities, not approximations --
# 13,284 sentence readings across every banked artifact and every pinned shape, 0 divergences.
#
# NOT COVERED, DELIBERATELY:
#   * THE REGISTRY FALLBACK. `citations.from_number` falls back to `_metric_unit(table, metric, commodity)`
#     when a row carries no `unit`; this gate does not. Reading it would make the verifier import the
#     numbers registry in order to take a STRIP decision, and the honest cheap answer is the stand-down
#     above: a call whose rows declare no unit takes its whole sentence out of the gate's reach.
#   * THE SCALE'S ARITHMETIC. The gate asks whether the label's scale is one the sentence's rows PRINT,
#     never whether the figure was rescaled correctly -- "154,947 (1000 MT)" against a row that means
#     154.947 MMT is a conversion question, and this estate has no conversion layer (the price audit's
#     finding), so no verifier rule may pretend to answer it.
#   * A LABEL ON A SENTENCE THAT CITES NO [N]. The bare-digit lint (`bare_digit_verdict`) owns the
#     no-handle sentence and is untouched here: rule (g) can never empty a sentence of claims, so that
#     verdict is exactly what it was.
#
# The numerals a unit string declares. Digit runs, THOUSANDS COMMA INCLUDED -- "1000 480 lb. Bales"
# declares 1000 and 480 (the "lb"/"Bales" words are the label's, not the vocabulary's), and "1,000 MT"
# declares 1000, not {0, 1}. Rule (g) fences the comma on the PROSE side (MAJOR-1: an exempted scale is a
# BARE digit run) and it must NOT be fenced here as well, or a row printing its label in comma form would
# charge the prose that copied the same label bare. Measured: 0 of the 30 distinct unit strings in the
# banked corpus carries a comma, so this is a fence against a shape the estate has not printed yet.
_UL_VOCAB_NUM = re.compile(r"\d[\d,]*")
# THE SCAN'S COST FENCE, and an identity by construction: rule (g) can only exempt a scale that `_UL_TAIL`
# matches, and `_UL_TAIL` is anchored at the end of a BARE digit run -- so a sentence in which this
# un-anchored form (the same pattern with its leading digit) never matches cannot hold a label, and the
# scan below can return before it pays for `_claim_number_spans`. Measured identity over 13,284 sentence
# readings; measured worth: with the reorder below it holds the gate's extractor runs on the control
# arm to 411 per answer set against HEAD's 406, where the naive reading cost 603.
_UL_ANY = re.compile(r"\d" + _UL_GLUE + r"+(?:\d{1,3}" + _UL_GLUE + r"+)?" + _UL_UNIT + r"\b", re.I)


def _unit_label_scale_values(s: str, *, units=None) -> list[float]:
    """The scale tokens rule (g) EXEMPTED in `s`, in order: '154,947 (1000 MT)' -> [1000.0], and
    'arabica 42,300 (1000 60 KG BAGS)' -> [1000.0, 60.0].

    It reads rule (g)'s OWN regexes (`_UL_BARE` / `_UL_TAIL` / `_UL_LEAD`) and takes its anchors from
    `_claim_number_spans`' ACCEPTED spans, so the two readings cannot drift into disagreeing about what a
    label is: an accepted figure anchors the next lead exactly as it does there, every other exemption
    clears the anchor, and a label consumed whole yields BOTH its scale tokens -- the sub-unit weight of
    "1000 60 KG BAGS" is part of the label, so the vocabulary has to see it.
    VALUES, never spans: the charge site asks a membership question and this gate takes no drop decision
    of its own.
    THE ONE PLACE THE RECONSTRUCTION IS NOT AN IDENTITY, and it points the safe way: a token `_CLAIM_NUM`
    matched but `float()` could not parse leaves the extractor's anchor STANDING and clears this one, so
    this scan can only ever report FEWER labels than rule (g) exempted, never more. A miss leaves the
    structural verdict in place -- the fail-open direction, and the same direction every fence below
    takes."""
    s = s or ""
    if units is not None:
        # 09-23 (C6): at a charge site the scale tokens are the ONE scan's own record -- rule (g) over the
        # derived words AND rule (i)'s phrase-order run -- so the gate and the extractor cannot disagree.
        return _claim_scan(s, units=units)[1]
    if not _UL_ANY.search(s):                     # no digit-then-unit-word anywhere: no label, and the
        return []                                 # extractor is never paid for (see `_UL_ANY`)
    accepted = {a for a, _b, _v in _claim_number_spans(s)}
    out: list[float] = []
    anchor: int | None = None
    skip_until = -1
    for m in _CLAIM_NUM.finditer(s):
        core = m.group().rstrip(".,")
        end = m.start() + len(core)
        if m.start() < skip_until:                    # inside a label consumed whole: its second scale
            if _UL_BARE.fullmatch(core):              # `_UL_TAIL`'s region admits only bare digits, so
                out.append(float(core))               # this parse cannot fail and needs no handler
            continue
        if m.start() in accepted:
            anchor = end                              # an ACCEPTED figure -- the only lead a label grows from
            continue
        if anchor is not None and _UL_BARE.fullmatch(core):
            tail = _UL_TAIL.match(s[end:])
            if tail and _UL_LEAD.match(s[anchor:m.start()]):
                skip_until = end + tail.end()
                anchor = None
                out.append(float(core))
                continue
        anchor = None                                 # every other exemption clears the anchor
    return out


def _shown_card_unit(call: dict) -> str:
    """The unit the citation PRINTS for a row that recorded none -- the card's declared unit for the call's
    metric (`citations._metric_unit`, the renderer's own fallback), or "" when the card declares none."""
    q = (call or {}).get("query") or {}
    try:
        from leviathan.graphrag import citations as _cit
        return str(_cit._metric_unit(str(q.get("table") or (call or {}).get("table") or ""),
                                     str(q.get("metric") or (call or {}).get("metric") or ""),
                                     q.get("commodity")) or "").strip()
    except Exception:  # noqa: BLE001 -- no card unit is no shown unit
        return ""


def _served_unit_vocab(sent: str, number_calls: list[dict]) -> set[int] | None:
    """The scale numerals the sentence's OWN served rows print in their unit strings, or None when that
    vocabulary is UNKNOWN and the gate must stand down.

    The rows are those of every [N] handle WRITTEN IN THE SENTENCE, grouped members included -- the
    cycle-9 amendment-3a reading, and admissible here for the same reason: a grouped citation's row was
    served to the reader exactly like a solitary one, and a wider vocabulary can only ever REMOVE a
    charge. A call that served no row (`rows: []`, an errored lookup) states no unit and is skipped; a
    call ANY of whose served rows fails to declare a SCALE returns None -- both the row that recorded no
    `unit` at all and the row whose unit string carries no numeral in it (see the block note: the registry
    declares "MMT (cotton: million 480-lb bales)" for metrics whose rows print the bare "MMT", so the short
    string is evidence about the ROW's rendering, never about the metric's scale vocabulary). Reverting to
    the fail-closed reading is one word (`_UL_VOCAB_NUM.search(u)` -> `u`) and both readings are pinned.

    THE STAND-DOWN IS ROW-GRANULAR, NOT CALL-GRANULAR, AND THE RENDERER IS WHY. `citations.from_number`
    prints `unit = r.get("unit") or _metric_unit(table, metric, commodity)`, so a row that recorded no
    unit was STILL shown to the reader wearing a label -- the REGISTRY's. A per-call `any(units)` test
    would build a vocabulary out of the unit-bearing rows alone and then charge the model for copying the
    label the citation printed for the row beside them: measured, a call serving
    [{8.85, "Million Bushels"}, {154947, no unit}] with `_metric_unit('silver_psd_attributes',
    'Feed Dom. Consumption', 'corn') == '1000 MT'` turned "US corn feed use is 154947 (1000 MT) [N1]"
    into number_unbacked 1 and took the handle. `all` is the fence the block note prices: an unrecorded
    unit anywhere in the call makes the whole sentence's vocabulary UNKNOWN. 83 of 4074 served calls in
    the banked corpus are mixed this way (2.0%; 1212 empty, 2197 all-unit, 582 no-unit) and 1 of the 46
    label-bearing sentences already cites one, so this is a live shape, not a hypothetical."""
    calls = number_calls or []
    vocab: set[int] = set()
    served = False
    for m in _HANDLE.finditer(sent or ""):
        for kind, j in _handle_members(m.group(0)):
            if kind != "N" or not (1 <= j <= len(calls)):
                continue
            rows = ((calls[j - 1] or {}).get("rows") or [])
            if not rows:
                continue
            # 09-23 FIX ROUND (review FATAL-1, CONTRACT C6 "row-granular"): each row is read at the unit
            # the READER WAS SHOWN for it -- its own, else the card's (`citations._metric_unit`, the
            # renderer's own fallback) -- and a row shown NO unit at all contributes nothing and voids
            # nothing (the cotton N1-N7 unit-less duplicate beside the labelled row stood the whole gate
            # down, so a label scale NO cited row prints was never re-admitted). A shown unit that carries
            # no scale still makes the vocabulary UNKNOWN (the measured MMT-gloss fence below).
            units = []
            for r in rows:
                u = str((r or {}).get("unit") or "").strip()
                if not u:
                    u = _shown_card_unit(calls[j - 1])
                if u:
                    units.append(u)
            if not units:
                continue
            if not all(_UL_VOCAB_NUM.search(u) for u in units):
                return None                           # a shown unit with no SCALE in it: vocabulary UNKNOWN
            served = True
            for u in units:
                # every match starts with a digit, so stripping the commas can never empty the token
                vocab.update(int(t.replace(",", "")) for t in _UL_VOCAB_NUM.findall(u))
    return vocab if served else None


def _unit_vocab_claims(sent: str, number_calls: list[dict], *, units=None) -> list[float]:
    """The scale tokens rule (g) exempted that NO served row of this sentence prints -- re-admitted as
    CLAIM magnitudes by the charge site. Empty on every sentence with no label, with no served unit, or
    with a label its own rows declare, which is every sentence of the measured 33-of-35 class.
    The sentence is read handle-stripped, exactly as `_check_number_handle` reads it, so a handle's own
    digits can never be mistaken for a label's scale.
    BOTH ROLLBACKS ARE READ HERE, not at the charge site alone: `_check_number_handle` already sits inside
    the GRAPHRAG_CASCADE_QUANT branch, but the `strip_audit` call does NOT, so under quant-off the audit
    would have listed a re-admitted scale that no charge could have used. The flag's promise is that the
    whole quant guard reverts, and the gate feeds that guard.
    THE CHEAP QUESTION IS ASKED FIRST: the vocabulary walk reads dicts, the label scan runs the extractor,
    and most sentences stand the gate down -- see the block note's CPU line."""
    if os.environ.get("GRAPHRAG_VERIFY_UNIT_VOCAB", "on") == "off":
        return []
    if os.environ.get("GRAPHRAG_CASCADE_QUANT", "on") == "off":
        return []
    vocab = _served_unit_vocab(sent, number_calls)
    if vocab is None:
        return []
    scales = (_unit_label_scale_values(_HANDLE.sub("", sent or "")) if units is None
              else _unit_label_scale_values(_HANDLE.sub("", sent or ""), units=units))
    if not scales:
        return []
    return [v for v in scales if int(v) not in vocab]


def _check_number_handle(sent: str, idx: int, number_calls: list[dict], *, ctx=None) -> str | None:
    if not (1 <= idx <= len(number_calls)):
        return "index_out_of_range"
    ctx = _ctx_of(ctx, number_calls)
    row_vals = _row_vals(number_calls[idx - 1])
    # the HEADLINE check runs against what the cited LINE printed (`shown`), not the whole window it fetched
    pool = _mismatch_pool(number_calls[idx - 1], row_vals)
    # CYCLE-6: the same extraction, now carrying each token's WRITTEN precision alongside its value.
    # 09-23 (C6): extracted with the DERIVED unit vocabulary -- the cards' declared units and this
    # sentence's own served rows -- so a unit the row itself prints ("Million 480 Pound Bales") is never a
    # claim magnitude, and a 4-digit figure in the row's own unit ("1992 contracts") is never a year.
    stripped = _HANDLE.sub("", sent)                               # time/name tokens: NOT claims
    g = ctx.grammar(sent)
    spans = _claim_number_spans(stripped, units=g)
    sent_nums = [v for _a, _b, v in spans]
    sent_decs = [_token_decimals(stripped[a:b]) for a, b, _v in spans]
    if sent_nums and pool and not _num_matches(sent_nums, pool, sent_decs):
        # 09-23: THE CITED ROW'S OWN ORDINAL (see `_own_ordinal`) -- "at the 92nd [N33]" on a percentile
        # call is that call's figure, however rule (e) filed the ordinal.
        if not (_own_ordinal(sent, idx, number_calls, pool)
                or _unbound_handle(sent, idx, number_calls, ctx)):
            return "number_mismatch"
    # P9-B all-numbers guard: EVERY magnitude in a handled sentence (years/range-tails/letter-codes exempt
    # at the extractor) must match SOME injected row across the merged calls -- else "rose to 5900 [N3],
    # up 18%" lets 18 ride UNVERIFIED. Reads ONLY GRAPHRAG_CASCADE_QUANT (the single feature flag): =off
    # fully reverts the stricter verifier.
    # DELIBERATE ASYMMETRY: allv (and the own-row bridge below) stay ALL ROWS even under shown-binding --
    # number_mismatch is the headline check and must be tight, number_unbacked is the loose backstop, and
    # narrowing both would strip every legitimate second figure a window call genuinely supports.
    if os.environ.get("GRAPHRAG_CASCADE_QUANT", "on") != "off":
        allv = _all_row_vals(number_calls)
        # D-DA UNIT-VOCABULARY GATE (2026-09-06): rule (g)'s exemption is STRUCTURAL, so a label scale no
        # served row of this sentence prints comes back here as a CLAIM. The GUARD list only, never the
        # mismatch pool above -- see the block note: an ANY-of predicate can only be RESCUED by one more
        # numeral. A re-admitted token is a bare digit run, so its written precision is 0 by construction.
        _uv = _unit_vocab_claims(sent, number_calls, units=g)
        # backed = scale-1 match vs ANY row (pre-scaled cascade rows), OR the legacy scale-bridge vs the
        # sentence's OWN cited row (a '31.4 million MT' narration of its own raw-MT hybrid row is legitimate;
        # CROSS-row multi-scale backfill stays forbidden -- that is the R4 mis-attribution hole).
        # CYCLE-6: both arms carry the numeral's written precision (see `_reader_precision_match`).
        # 09-23 (C4 rule 3a): OR the served-scalars pool -- a figure the board printed, under rules (1)/(2).
        if (spans or _uv) and allv:
            # the pool is BINDING-SCOPED (C4, fix-round FATAL-4): its test reads the numeral at its offset in
            # the sentence AS WRITTEN, where the handle groups it binds to are
            _at = _stripped_offsets(sent) if ctx.pool else None
            for (a, b, v), d in zip(spans, sent_decs):
                if _num_backed(v, allv, dec=d) or (row_vals and _num_matches([v], row_vals, [d])):
                    continue
                if ctx.pool and ctx.pool_backs(sent, _at[a], _at[b - 1] + 1, v, d, key=sent):
                    continue
                return "number_unbacked"
            for v in _uv:
                if not (_num_backed(v, allv, dec=0) or (row_vals and _num_matches([v], row_vals, [0]))):
                    return "number_unbacked"
    return None


# ══ 09-23 FIX ROUND (lane V) -- PASS 0: ONE VALUE-PRESERVING INSERTION, AND WHY CYCLE-10 ADMITS IT ═══════
# CYCLE-10 deleted the REWRITE: no numeral the writer wrote is ever replaced by another. The same-row
# RE-ADDRESS leaves every character the writer wrote in place and INSERTS only a handle token of a SIBLING
# call (one `_row_id`, CONTRACT C3) after a figure the writer bound to the wrong member of that row's triple
# -- a handle whose call carries that figure AT SCALE 1 and IN THE UNIT THE WRITER WROTE. It is recorded
# (`readdressed`), runs BEFORE the charge so the charge reads the corrected sentence, and is absent from
# `report["repairs"]` (whose `repaired` count keeps its CYCLE-10 meaning).
# THE NOUN-OBJECT SPLICE IS RETIRED (fix-round review FATAL-5). It inserted a call's headline figure in
# front of any two solitary handles joined by one word at the end of a clause -- on UNCHARGED, digit-free
# prose too ("tightened through the summer [N1] and [N2]" became "... summer 2,628,325 tonnes [N1] and 1.89
# months of export cover [N2]"), a verifier writing figures into a sentence that made no numeric claim,
# past the CYCLE-10 licence; and the position template that chose the shape could not tell a noun from a
# citation. The defect it was built for -- the tariff "higher year-on-year [N29] vs [N30]" handles struck
# by a neighbour's numeral and leaving "vs." dangling -- is closed by the binding rule: those handles bind
# no figure, so `_unbound_handle` keeps them and the sentence is served as written.

def _handle_groups(sent: str) -> list:
    """The sentence's handle tokens in written order, ADJACENT tokens (only blanks between) grouped: a group
    shares one binding window, so "68th percentile [N54] [N56]" binds 68 to both, never to neither."""
    groups: list = []
    for m in _HANDLE.finditer(sent or ""):
        if groups and not sent[groups[-1][-1].end():m.start()].strip():
            groups[-1].append(m)
        else:
            groups.append([m])
    return groups


def _written_figures(masked: str, g) -> list:
    """Every figure the sentence WRITES, as (start, end, value, decimals, kind): the claim spans (declared
    vocabulary) and the ordinal tokens cycle-8 rule (e) exempts (kind 'ordinal', end past the suffix)."""
    out = [(a, b, v, _token_decimals(masked[a:b]), "claim") for a, b, v in _claim_number_spans(masked, units=g)]
    for m in _CLAIM_NUM.finditer(masked):
        core = m.group().rstrip(".,")
        if _ORDINAL_AFTER.match(masked[m.start() + len(core):]):
            try:
                v = float(core.replace(",", ""))
            except ValueError:
                continue
            out.append((m.start(), m.start() + len(core) + 2, v, _token_decimals(core), "ordinal"))
    return sorted(out)


def _group_pools(group: list, number_calls: list) -> list:
    """The mismatch pools of every in-range [N] member of one handle group."""
    out = []
    for m in group:
        for kind, j in _handle_members(m.group(0)):
            if kind == "N" and 1 <= j <= len(number_calls or ()):
                out.append(_mismatch_pool(number_calls[j - 1], _row_vals(number_calls[j - 1])))
    return out


def _group_units(group: list, number_calls: list) -> list:
    """The served unit phrases (token tuples, with their declared alternatives) of a group's [N] members."""
    out: list = []
    for m in group:
        for kind, j in _handle_members(m.group(0)):
            if kind == "N" and 1 <= j <= len(number_calls or ()):
                for u in _row_unit_strings(number_calls, [j]):
                    out.extend(_phrase_alternatives(u))
    return out


#: A CLAUSE-SEGMENT BREAK inside one sentence: a list comma, a semicolon, a colon or a dash -- the
#: punctuation the estate's citation grammar already separates handle members and clauses with. A
#: thousands comma ("3,600") is never one: it carries no blank after it.
_SEGMENT_BREAK = re.compile(r",\s|;|:\s|\s-{2,}\s|[" + chr(0x2013) + chr(0x2014) + r"]")


def _row_units_of_group(group: list, number_calls: list) -> list:
    """Every served unit (token tuples) of every call of the ROWS a group's [N] members belong to (one
    `_row_id`, C3 -- the level, the sigma, the percentile of one series), the members' own units included."""
    rids, out = set(), []
    for m in group:
        for kind, j in _handle_members(m.group(0)):
            if kind == "N" and 1 <= j <= len(number_calls or ()):
                rid = (number_calls[j - 1] or {}).get("_row_id")
                if rid:
                    rids.add(str(rid))
                out.extend(_phrase_alternatives(_call_unit(number_calls[j - 1])))
    if rids:
        for c in number_calls or ():
            if str((c or {}).get("_row_id") or "") in rids:
                out.extend(_phrase_alternatives(_call_unit(c)))
    return [t for t in out if t]


def _bind(sent: str, groups: list, figs: list, number_calls: list, g=None) -> dict:
    """{group index: [figure + (how,)]} -- WHICH HANDLE GROUP A WRITTEN FIGURE BELONGS TO, read off the
    estate's own citation grammar, the rows and the units, never off words. In order:
      * "adjacent" -- the FIGURE [N] CONVENTION: the figure's own unit (`_unit_tail_end`: its declared unit
        phrase, the group's own served units) runs straight into the group, nothing else between. The writer
        ADDRESSED the figure there, so it binds there WHATEVER its neighbours back (fix-round review
        FATAL-2: "China imports 118 MMT [N2]" is [N2]'s figure even where [N1] carries 118).
      * "typed" -- exactly one neighbour's ROW carries a member in the unit the writer WROTE ("the 94th
        percentile" beside a stocks handle whose row has a percentile member, and a pace-streak handle whose
        row has none).
      * "segment" -- the handle group that CLOSES the figure's own clause segment (no list comma, semicolon,
        colon or dash between them), else the group inside or OPENING it ("58.5 MMT [N28], at the 99th
        percentile of that record, with exports ..." -- the 99 is [N28]'s clause, not the exports handle's;
        "**Pacific ONI [N19]**: +1.8 degC, the 97th ..." -- the heading's; "China imports 118 MMT too
        [N2]" is [N2]'s clause whatever [N1] carries).
      * "backed" -- no structure decides: one of its two neighbouring groups BACKS it (the one after when both).
      * "window" -- the group written after it (the handle that closes the text it sits in), else the last.
    Every step before "backed" is STRUCTURE (the citation grammar, the rows' units, the clause punctuation);
    value coincidence decides only where structure is silent (fix-round review FATAL-2).
    Adjacent handles are ONE group, so one figure is never split across "[N3] [N4]"."""
    out: dict = {i: [] for i in range(len(groups))}
    if not groups:
        return out
    masked = _mask_handles(sent)
    pools = [_group_pools(grp, number_calls) for grp in groups]
    for f in figs:
        a, b, v, d = f[0], f[1], f[2], f[3]
        nxt = next((gi for gi, grp in enumerate(groups) if grp[0].start() >= b), None)
        prv = next((gi for gi in range(len(groups) - 1, -1, -1) if groups[gi][-1].end() <= a), None)
        if nxt is not None:
            end = _unit_tail_end(masked, b, g, extra=_group_units(groups[nxt], number_calls))
            if not masked[end:groups[nxt][0].start()].strip():
                out[nxt].append(tuple(f) + ("adjacent",))
                continue
        lead = a
        while lead > 0 and masked[lead - 1] in _FIGCUT_SIGN:
            lead -= 1
        cands = [gi for gi in (nxt, prv) if gi is not None]
        if not cands:
            continue
        written = _unit_written_at(masked, b, g)
        if written:
            typed = [gi for gi in cands
                     if any(_unit_equal(written, u) for u in _row_units_of_group(groups[gi], number_calls))]
            if len(typed) == 1:
                out[typed[0]].append(tuple(f) + ("typed",))
                continue
        left = max((m.end() for m in _SEGMENT_BREAK.finditer(masked, 0, lead)), default=0)
        right = next((m.start() for m in _SEGMENT_BREAK.finditer(masked, b)), len(masked))
        if nxt is not None and groups[nxt][0].start() < right:
            out[nxt].append(tuple(f) + ("segment",))
            continue
        if prv is not None and (groups[prv][-1].end() > left      # the segment's own handle, or
                                or not masked[groups[prv][-1].end():left].strip(" \t,;:*_")):  # its opener
            out[prv].append(tuple(f) + ("segment",))
            continue
        backs = [gi for gi in cands if any(_num_matches([v], pool, [d]) for pool in pools[gi])]
        if backs:
            out[backs[0]].append(tuple(f) + ("backed",))
            continue
        out[nxt if nxt is not None else prv].append(tuple(f) + ("window",))
    return out


def _call_unit(call: dict) -> str:
    for r in ((call or {}).get("rows") or []):
        u = str((r or {}).get("unit") or "").strip()
        if u:
            return u
    return ""


def _figure_end(s: str, b: int, unit: str, g=None) -> int:
    """Where a handle for the figure ending at `b` is inserted: past the figure's own ordinal suffix and a
    glued '%', then past the LONGEST unit the text spells there -- the SIBLING row's own unit ("-0.67 z",
    "84th percentile", "35.82 M ha") or a declared unit phrase (one declared scale word allowed in front:
    "622.69 thousand MT") -- so a handle never lands inside "622.69 [N66] thousand MT"."""
    return _unit_tail_end(s, b, g, extra=list(_phrase_alternatives(unit)) if unit else [])


def _readdress_sentence(sent: str, number_calls: list, ctx, field: str, log: list) -> str:
    """SAME-ROW RE-ADDRESS (BRIEF item 2, THREAT_MODEL V-2). THE MEASURED DEFECT: the board mints ONE row as
    three calls (level, sigma, percentile) and hands the chain hop only the LEVEL handle, so the writer
    printed "the Pacific reading [N54] sits at the 35th percentile", "the 68th [N54]", "-0.67 z ... bottom
    decile [N16]" -- the right figure beside the wrong member of its own row -- and the verifier cut the
    figure or killed the clause.
    THE RULE: calls sharing a `_row_id` are one row identity. A figure bound to a solitary [Nh] that h does
    not back AT SCALE 1 is re-addressed to the ONE sibling member that does -- and only where the member
    carries the figure IN THE UNIT THE WRITER WROTE (fix-round review FATAL-3: the value alone, through the
    multi-scale bridge, re-addressed a percentile written "13 1000 MT" to the percentile handle and a sigma
    written "120 months" to the sigma handle): the written unit (`_unit_written_at`) must be the member's
    served unit; a figure written with NO unit must be in the member's printed FORM (an ordinal is the
    printed form of a percentile, `rows.percentile_int`; a cardinal is every other member's). And a figure
    written in the CITED handle's OWN unit is a VALUE the writer got wrong on the right member -- never an
    address to correct -- so it takes HEAD's remedy ("the 2nd percentile [N9]" where [N9] is the 13th).
    AND THE DATE THE WRITER BOUND TO THE FIGURE MUST BE THE MEMBER'S OWN (review FATAL-3's peak / current
    twins): a member's call is dated by its own period -- the current reading by its level date, the
    window extreme by the month it was reached (`window_peak_percentile`, C3). "bottomed at the 13th
    percentile in June 2026" is not the current 13th (dated August), and a window extreme is re-addressed
    to only where the writer wrote the month it was reached ("peaked at the 98th percentile in April 2026")
    -- "now sits at the 2nd percentile" is not the June trough (`_bound_month`, `_member_date_fits`).
    A figure two members back (level 2 vs sigma 2.0) is AMBIGUOUS and left to HEAD's remedy.
    [Nh] STAYS unless the writer ADDRESSED the moved figure to it -- wrote the figure straight into it, or
    [Nh] closes the clause segment the figure sits in ("Crude, 68th percentile of its own record [N54]")
    -- and h's own figure is written nowhere in the sentence (in digits, or in the board's own number
    words): a handle the writer used for its words ("the Pacific reading [N54] sits at the 35th
    percentile", "-0.67 z, read 2026-08, bottom decile [N16]") is a citation, not a mis-address. Only board calls carry `_row_id`, so a board-off turn never reaches this."""
    calls = number_calls or []
    groups, figs, bound = ctx.binding(sent)
    if not groups:
        return sent
    masked = _mask_handles(sent)
    g = ctx.grammar(sent)
    ops: list = []                                    # (pos, kind 0=insert/1=delete, end, text)
    for gi, grp in enumerate(groups):
        if len(grp) != 1:
            continue
        mem = _handle_members(grp[0].group(0))
        if len(mem) != 1 or mem[0][0] != "N" or not (1 <= mem[0][1] <= len(calls)):
            continue
        h = mem[0][1]
        rid = (calls[h - 1] or {}).get("_row_id")
        if not rid:
            continue
        sibs = [k for k in range(1, len(calls) + 1)
                if k != h and (calls[k - 1] or {}).get("_row_id") == rid]
        if not sibs:
            continue
        pool_h = _mismatch_pool(calls[h - 1], _row_vals(calls[h - 1]))
        unit_h = _unit_tokens(_call_unit(calls[h - 1]))
        pools = {k: _mismatch_pool(calls[k - 1], _row_vals(calls[k - 1])) for k in sibs}
        inserted, addressed = [], False
        for a, b, v, d, kind, how in bound.get(gi, []):
            if _num_backed(v, pool_h, dec=d):
                continue
            written = _unit_written_at(masked, b, g)
            if written and _unit_equal(written, unit_h):
                continue                              # the member's own unit: a wrong VALUE, HEAD's remedy
            ordinal = kind == "ordinal" or bool(re.match(r"(?:st|nd|rd|th)\b", masked[b:b + 3]))
            said = _bound_month(masked, b, figs)
            hits = []
            for k in sibs:
                if not _num_backed(v, pools[k], dec=d):
                    continue
                if written:
                    if not _unit_equal(written, _unit_tokens(_call_unit(calls[k - 1]))):
                        continue
                elif ordinal != _percentile_call(calls[k - 1]):
                    continue
                if not _member_date_fits(calls[k - 1], said):
                    continue
                hits.append(k)
            # the SAME member minted twice (a chain hop re-minting its row's triple) is one member, not an
            # ambiguity: distinct members are told apart by the C3 `stat` and the served unit
            members = {(str((((calls[k - 1] or {}).get("rows") or [{}])[0] or {}).get("stat") or ""),
                        _call_unit(calls[k - 1]), tuple(sorted(round(float(x), 9) for x in pools[k])))
                       for k in hits}
            if len(members) != 1:
                continue
            k = min(hits)
            at = _figure_end(masked, b, _call_unit(calls[k - 1]), g)
            nxt = _HANDLE.match(sent[at:].lstrip(" "))
            if nxt and ("N", k) in _handle_members(nxt.group(0)):
                continue                              # already addressed
            ops.append((at, 0, at, " [N%d]" % k))
            inserted.append(k)
            # ADDRESSED: written straight into [Nh], or [Nh] closes the clause segment the figure sits in
            _right = next((m.start() for m in _SEGMENT_BREAK.finditer(masked, b)), len(masked))
            addressed = addressed or how == "adjacent" or (b <= grp[0].start() < _right)
            log.append({"from": h, "to": k, "field": field, "numeral": v})
        if not inserted or not addressed:
            continue
        start = groups[gi - 1][-1].end() if gi else 0
        window = sent[start:grp[0].start()] + (sent[grp[-1].end():] if gi == len(groups) - 1 else "")
        own = (any(_num_backed(v, pool_h, dec=d) for _a, _b, v, d, _k in figs)
               or _worded_own_figure(window, pool_h, calls[h - 1]))
        if not own:
            m = grp[0]
            a0 = m.start() - 1 if m.start() > 0 and sent[m.start() - 1] == " " else m.start()
            ops.append((a0, 1, m.end(), ""))
    if not ops:
        return sent
    out = sent
    for at, kind, end, text in sorted(ops, key=lambda o: (o[0], o[1]), reverse=True):
        out = out[:at] + text + out[end:] if kind == 1 else out[:at] + text + out[at:]
    return out


_MONTH_WORD_RX = re.compile(r"(?<![A-Za-z])(" + _MONTHS + r")\.?\s+((?:19|20)\d{2})(?!\d)", re.I)
_MONTH_ISO_RX = re.compile(r"(?<!\d)((?:19|20)\d{2})-(0[1-9]|1[0-2])(?!\d)")


def _bound_month(masked: str, b: int, figs: list) -> tuple | None:
    """The (year, month) the writer dated the figure ending at `b` with: the first month-year date written
    after it ("in June 2026", "2026-07") before the next figure and inside its own clause segment -- or
    None. The date binds to the figure it follows ("98th percentile in April 2026 and now reads the 68th":
    April is the 98's, never the 68's)."""
    stop = min([f[0] for f in figs if f[0] >= b] + [len(masked)])
    brk = _SEGMENT_BREAK.search(masked, b)
    if brk is not None:
        stop = min(stop, brk.start())
    seg = masked[b:stop]
    best = None
    for m in _MONTH_WORD_RX.finditer(seg):
        best = (m.start(), int(m.group(2)), _mon(m.group(1)))
        break
    for m in _MONTH_ISO_RX.finditer(seg):
        if best is None or m.start() < best[0]:
            best = (m.start(), int(m.group(1)), int(m.group(2)))
        break
    return (best[1], best[2]) if best else None


def _member_date_fits(call: dict, said) -> bool:
    """May `said` (the month the writer dated the figure with, or None) be this member's date? A window
    extreme (C3 `window_peak_percentile`) is chosen ONLY where the writer wrote its own month; any other
    member only where the writer wrote no month, or its own month (a member with no monthly period -- an
    annual one -- cannot be contradicted by a month)."""
    rows = (call or {}).get("rows") or [{}]
    stat = str((rows[0] or {}).get("stat") or "")
    per = str(((call or {}).get("query") or {}).get("period") or "")
    m = _MONTH_ISO_RX.match(per[:7]) if len(per) >= 7 else None
    own = (int(m.group(1)), int(m.group(2))) if m else None
    if stat == "window_peak_percentile":
        return said is not None and own is not None and said == own
    return said is None or own is None or said == own


def _worded_own_figure(window: str, pool: list, call: dict) -> bool:
    """Is the handle's own figure already WRITTEN IN WORDS in its binding window? The integer through the
    board's own number-word producer (`rows.words_for_int`, the SAME function the board prints counts
    with) -- a figure, spelled. (Fix-round review M3: a percentile-family WORD alone never stands in for
    the handle's figure; that was the percentile-word special case the brief rejected.)"""
    w = " " + re.sub(r"\s+", " ", str(window or "").lower()) + " "
    try:
        from leviathan.graphrag.state import rows as _rows
        wfi = getattr(_rows, "words_for_int", None)
        if wfi is None:
            from leviathan.graphrag.state import render as _rnd
            wfi = getattr(_rnd, "words_for_int", None)
    except Exception:  # noqa: BLE001 -- no producer, no worded reading: the shape decides alone
        wfi = None
    if not callable(wfi):
        return False
    for v in pool or []:
        if abs(v - round(v)) < 1e-9 and 0 <= v <= 999999:
            words = str(wfi(int(round(v)))).lower()
            if words and re.search(r"(?<![a-z-])" + re.escape(words) + r"(?![a-z-])", w):
                return True
    return False


# ══ 09-23 FIX ROUND (lane V, BRIEF item 9) -- AN [E] HANDLE IS BOUND BY ITS DOCUMENT'S IDENTITY ═══════════
# THE MEASURED DEFECT (rice turn): "USDA raised 2025/26 global beginning stocks primarily for India ...,
# reported 9 December 2025 [E41]" resolved to a September-2023 WASDE about a parboiled export tax and
# PASSED -- `_check_evidence_handle` asks only whether the sentence shares ONE [a-z]{5,} token with the
# item ("india"). A date the writer binds to a document is a claim ABOUT that document, and the item
# carries three dates it can be checked against: its document date, its event date (at its own precision)
# and every date its own text states. THE RULE: a FULL date (day, month and year -- ISO or written out)
# bound to the handle (the nearest handle to it in the sentence, with no ';' / ':' / dash clause break
# between) that is NONE of those is a `date_contradiction`. REMEDY, correct before delete: when the turn
# holds exactly ONE item of the same source carrying that date, the handle is RE-ADDRESSED to it (the
# footer then names the document the writer dated); otherwise that HANDLE alone is dropped and counted --
# the words stand. A month- or year-precision date is never charged (the writer may be dating the event,
# not the document), and neither is a date the item's text states without a year ("starting on March 10").
_MON_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
              "october", "november", "december")
_MON_RX = r"(?:" + _MONTHS + r")\.?"
_FULL_DATE_RXS = (
    re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)"),
    re.compile(r"(?<![\w])(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MON_RX + r")\s*,?\s+((?:19|20)\d{2})(?!\d)", re.I),
    re.compile(r"(?<![\w])(" + _MON_RX + r")\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+((?:19|20)\d{2})(?!\d)", re.I),
)
_YEARLESS_RXS = (
    re.compile(r"(?<![\w])(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MON_RX + r")(?!\s*,?\s*(?:19|20)\d{2})", re.I),
    re.compile(r"(?<![\w])(" + _MON_RX + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?![\d])(?!\s*,?\s*(?:19|20)\d{2})",
               re.I),
)


def _mon(tok: str) -> int:
    t = str(tok or "").lower().rstrip(".")[:3]
    for i, n in enumerate(_MON_NAMES):
        if n[:3] == t:
            return i + 1
    return 0


def _full_dates(text: str) -> list:
    """(start, end, (y, m, d)) for every FULL date written in `text`."""
    out = []
    for i, rx in enumerate(_FULL_DATE_RXS):
        for m in rx.finditer(text or ""):
            try:
                if i == 0:
                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                elif i == 1:
                    y, mo, d = int(m.group(3)), _mon(m.group(2)), int(m.group(1))
                else:
                    y, mo, d = int(m.group(3)), _mon(m.group(1)), int(m.group(2))
            except (TypeError, ValueError):
                continue
            if 1 <= mo <= 12 and 1 <= d <= 31:
                out.append((m.start(), m.end(), (y, mo, d)))
    return sorted(out)


def _item_dates(item: dict) -> tuple:
    """(full dates, yearless (m, d) pairs, prefix dates) an evidence item carries: its document date, its
    event date at its own precision, and every date its text states."""
    full, yearless, prefixes = set(), set(), set()
    for key in ("date", "event_date"):
        raw = str((item or {}).get(key) or "")[:10]
        mm = re.match(r"((?:19|20)\d{2})(?:-(\d{2}))?(?:-(\d{2}))?", raw)
        if not mm:
            continue
        y = int(mm.group(1))
        mo = int(mm.group(2)) if mm.group(2) else 0
        d = int(mm.group(3)) if mm.group(3) else 0
        prec = str((item or {}).get("event_date_precision") or "") if key == "event_date" else "day"
        if d and prec in ("", "day"):
            full.add((y, mo, d))
        elif mo and prec in ("", "day", "month"):
            prefixes.add((y, mo))
        else:
            prefixes.add((y,))
    text = str((item or {}).get("text") or "")
    for _a, _b, ymd in _full_dates(text):
        full.add(ymd)
    for i, rx in enumerate(_YEARLESS_RXS):
        for m in rx.finditer(text):
            try:
                mo, d = (_mon(m.group(2)), int(m.group(1))) if i == 0 else (_mon(m.group(1)), int(m.group(2)))
            except (TypeError, ValueError):
                continue
            if 1 <= mo <= 12 and 1 <= d <= 31:
                yearless.add((mo, d))
    return full, yearless, prefixes


def _date_fits(ymd: tuple, dates: tuple) -> bool:
    full, yearless, prefixes = dates
    y, mo, d = ymd
    return ymd in full or (mo, d) in yearless or (y, mo) in prefixes or (y,) in prefixes


def _bound_full_dates(text: str, h0: int, h1: int, s0: int, s1: int) -> list:
    """The FULL dates in the sentence text[s0:s1] whose NEAREST handle is the one at text[h0:h1], bound in
    one of the two shapes a writer dates a document with: "<verb> 9 December 2025 [E41]" (the date in the
    handle's own clause -- no ',' ';' ':' or dash between them) or "[E1], reported 2026-04-06" (the date
    right after the handle, at most one comma and two words between). MEASURED on the ten 09-23 pages: the
    wider "no ';' / ':' / dash between" reading bound "the 9 October 2026 print shows feed use falling ...,
    which is the 2011-style substitution [E4]" -- a FUTURE print the falsifier names, not the document's
    date -- to [E4]; the clause shape does not. Ties go to the handle AFTER the date."""
    sent = text[s0:s1]
    hs = [(m.start() + s0, m.end() + s0) for m in _HANDLE.finditer(sent)]
    out = []
    for a, b, ymd in _full_dates(sent):
        a, b = a + s0, b + s0
        best, bd = None, None
        for x0, x1 in hs:
            dist = (x0 - b) if x0 >= b else (a - x1) + 0.5
            if bd is None or dist < bd:
                best, bd = (x0, x1), dist
        if best != (h0, h1):
            continue
        if h0 >= b:                                   # the date BEFORE the handle: same clause
            if re.search(r"[,;:]|--|[" + chr(0x2013) + chr(0x2014) + r"]", text[b:h0]):
                continue
        elif not re.fullmatch(r"\s*,?\s*(?:[A-Za-z]+\s+){0,2}", text[h1:a]):
            continue                                  # the date AFTER it: "[E1], reported <date>" only
        out.append(ymd)
    return out


def _e_date_verdict(text: str, h0: int, h1: int, s0: int, s1: int, items: list, evidence: list):
    """(None, None) when the handle's bound full dates fit its item; ("readdress", new_items) when they
    contradict it and the turn holds exactly ONE same-source document carrying them; ("date_contradiction",
    None) otherwise."""
    dates = _bound_full_dates(text, h0, h1, s0, s1)
    if not dates or not items:
        return None, None
    carried = _item_dates(items[0])
    for it in items[1:]:
        f, y, p = _item_dates(it)
        carried = (carried[0] | f, carried[1] | y, carried[2] | p)
    if any(_date_fits(ymd, carried) for ymd in dates):
        return None, None
    same = _same_source_items({"source": (items[0] or {}).get("source")}, evidence)
    fit = [e for e in same if any(_date_fits(ymd, _item_dates(e)) for ymd in dates)]
    if fit and len(_ledger_documents(fit)) == 1:
        return "readdress", fit
    return "date_contradiction", None


def _positional_support(sent: str, item: dict, evidence: list) -> bool:
    """Does the menu item at an undeclared [E]'s index ACTUALLY support the sentence (THREAT_MODEL A-5: "the
    item that actually supported the sentence")? HEAD's undeclared branch asks only whether SOME item shares
    a token OR a digit string -- a shared "2024" passes it -- and a footer row naming the wrong document is
    worse than none. So the positional item must (i) pass the same check on its own, (ii) share CONTENT
    WORDS with the sentence (HEAD's `_tokens`, not a digit coincidence), and (iii) share at least as many as
    any other item in the menu does -- the index names the document the sentence is closest to, or none."""
    if _check_evidence_handle(sent, [item]) is not None:
        return False
    st = _tokens(sent)
    own = len(st & _tokens((item or {}).get("text") or ""))
    if not own:
        return False
    return all(len(st & _tokens((e or {}).get("text") or "")) <= own for e in evidence or [])


def _resolved_payload(item: dict) -> dict:
    """The `report["resolved"]` payload shape for one evidence item (verify's own, 140-char snippet)."""
    txt = (item or {}).get("text") or ""
    return {"source": item.get("source"), "date": item.get("date"), "source_key": item.get("source_key"),
            "snippet": txt[:140] + ("..." if len(txt) > 140 else ""),
            "char_start": item.get("char_start"), "char_end": item.get("char_end"),
            "offset_kind": item.get("offset_kind")}


def verify_citations(structured: dict | None, evidence: list[dict] | None,
                     number_calls: list[dict] | None = None, *,
                     foreign_names: set[str] | None = None,
                     handle_prose: bool = False,
                     served_scalars: list | None = None) -> dict:
    """Verify + repair `structured` IN PLACE (tldr/mechanism prose, sources ledger); return the report.
    `foreign_names` = regime names that belong to OTHER contracts' DAGs (never routed here) — asserting
    one is the measured cross-contract fabrication class, so the token is stripped and counted.
    The report carries `resolved` ({ref -> the matched item's true metadata}) so the caller can render
    ONE validated source list numbered by the model's own handles (the dual-list mismatch inflated the
    judge's hallucination tally 37->151 while grounding/PIT rose).
    GRAPHRAG_VERIFY=off -> no-op. Never raises: verification must never break an answer.

    == D-HP (H1) -- `handle_prose` IS THE TREATMENT BUNDLE'S ONE KNOB, AND IT ARRIVES AS AN ARGUMENT ====
    This module reads NO environment for it (the `_mr` / `_outlook` threading discipline: the flag is
    resolved ONCE at the serving body and rides down, so no engine under that seam can disagree about
    which lane a turn is on). Default False -> every counter, every branch and every returned byte is the
    pre-D-HP report exactly, which is what makes the control arm byte-identical BY CONSTRUCTION rather
    than by promise. TWO things change when it is True, and both are one-sided:
      (1) an [E] handle whose index is IN RANGE of the single evidence list (D-HP-1's `uniq`) RESOLVES
          POSITIONALLY. This is D-HP-9's pinned ORDER clause. With `sources` dropped from the tool schema
          there is no ledger loop to run, `report['resolved']` would stay {} (this function initialises it
          empty and writes it ONLY from the ledger) and SIX consumers go dark -- including
          `answer._prune_orphan_evidence_handles`, which would then prune EVERY [E] handle from the prose,
          and the LIVE FE chip path, which reads `trace.citation_verifier.resolved` and nothing else.
          Minting here -- the same seam, the same payload shape -- is what keeps that join total.
          IT IS DELIBERATELY NOT A SYNTHESISED LEDGER: writing `structured['sources']` BEFORE this call
          would make `_match_ledger_entry` match by construction and `fabricated_citation` read 0
          TAUTOLOGICALLY. The server re-synthesises the ledger FROM `resolved` AFTER this returns.
          An OUT-OF-RANGE index is untouched and still falls to the undeclared branch -- that is the
          index-range check, and it is the whole check.
      (2) the D-HP-12 DIGIT-LINT charges `bare_digit` per sentence (see `bare_digit_verdict`).

    == 09-23 FIX ROUND (lane V, CONTRACT C15) -- `served_scalars` AND THE REPORT KEYS IT ADDED ==========
    `served_scalars` is the board block's own record of every figure it printed (CONTRACT C4; lane R mints
    it, the seam transports it ONLY when the block rendered, answer threads it). None -- every board-off
    turn -- leaves the pool arm inert by construction. Report keys ADDED ONLY WHEN NON-EMPTY, so a report
    with nothing to say about them has HEAD's shape: `readdressed` (same-row re-address; the noun-object
    splice and its `noun_object_spliced` key are RETIRED by the fix round, review FATAL-5), `pool_backed`, `handles_canonicalised`, `resolved_undeclared` (an undeclared [E] resolved POSITIONALLY to
    the item the turn's evidence menu holds at that index, when that item itself supports the sentence),
    `ledger_ambiguous`, `e_date_readdressed` and `e_numerals_unverified` (claim numerals in [E]-only
    sentences -- OWNER DECISION 13: a counter, never a charge).
    """
    # CYCLE-8 FIX 2(c): `repaired` / `repairs` are ALWAYS present (0 / []), never gated. See the
    # no-laundering note in PASS 2.
    # ROUND-2 DOCKET item B-4 (2026-09-17) -- `strip_sentences` JOINS THE ALWAYS-PRESENT COUNTERS.
    # `stripped` counts OFFENDING HANDLES and `claim_count` counts SENTENCES, so every rate built from the
    # pair mixes its units: the smoke's deep turn reported `strips = 5` over THREE distinct sentences, and
    # the read panel read five findings. `stripped` does NOT move -- it is what every banked number in this
    # estate is denominated in -- and this is the honest numerator beside it: distinct (rule, field,
    # sentence) charges, the same key `strip_audit` de-duplicates on, and unlike `strip_audit` it is
    # populated whether or not GRAPHRAG_STRIP_AUDIT is lit.
    report = _VerifyReport({"enabled": True, "checked": 0, "stripped": 0, "strip_sentences": 0,
                            "corrected": 0, "claim_count": 0,
                            "repaired": 0, "repairs": [], "by_rule": {}, "resolved": {}})
    if os.environ.get("GRAPHRAG_VERIFY", "on") == "off" or not structured:
        report["enabled"] = False
        return report
    try:
        # claim_count (P7-P0.1): the strip-RATE denominator = non-empty SENTENCES across the draft prose,
        # captured FIRST (cheap, regex-only) and BEFORE _verify_field mutates tldr/mechanism — so a later
        # verifier failure still leaves the denominator populated, and an all-uncited answer reads
        # strip_rate 0 rather than NaN (handles-based `checked` stays as the secondary denominator).
        _orig_prose = (structured.get("tldr") or "") + " " + (structured.get("mechanism") or "")
        report["claim_count"] = len([s for s in _SENT_SPLIT.split(_orig_prose) if s.strip()])
        # 09-23 (BRIEF item 7): a bracket that opens as a handle and continues as prose is split to the
        # canonical handle + its own words BEFORE anything reads a handle, so the kinds map, the charge and
        # the footer all see "[N42]". Counted; nothing deleted, no character written but the moved bracket.
        _canon_n = 0
        for _fld in ("tldr", "mechanism"):
            if isinstance(structured.get(_fld), str) and structured.get(_fld):
                structured[_fld], _k = _canonicalise_handles(structured[_fld])
                _canon_n += _k
        if _canon_n:
            report["handles_canonicalised"] = _canon_n

        # W3 RCA: flag-gated capture of the stripped SENTENCE TEXT (counts already live in by_rule, but the
        # fix can't be chosen without seeing WHICH sentences each rule kills). GRAPHRAG_STRIP_AUDIT=off (the
        # default) -> no key, no appends, no cost. Capture ONLY -- no strip decision reads this list.
        _audit_on = os.environ.get("GRAPHRAG_STRIP_AUDIT", "off") != "off"
        if _audit_on:
            report["strip_audit"] = []
        # D-HP-12 / R3(b): the HARD COUNTER that prices the [E]-cited exemption. Present ONLY on the
        # treatment lane (the OFF-arm-clean rule: a key absent is honest, a key present and always zero
        # is a column that says "measured" when nothing measured it). `charged` is the class the ledger
        # also carries under `by_rule['bare_digit']`; `e_cited` is the 10.5%-of-numerals hole R3 option
        # (b) knowingly leaves open, and it is the number that decides whether option (a) is worth a phase.
        if handle_prose:
            report["handle_prose"] = True
            report["bare_digit"] = {"charged": 0, "e_cited": 0}

        # W4 A/B RCA (2026-07-31): a number_mismatch dropped the HANDLE only, so the fabricated FIGURE stayed
        # on the page -- now uncited, which reads as the analyst's own number (the judge scored 4 of these on
        # one row, e.g. "-0.72 degC [N12]" against rows of +0.06). Fail-closed by DEFAULT: DELETE THE WHOLE
        # SENTENCE (CYCLE-10 -- the "rewrite the figure from the cited row when that is unambiguous" arm is
        # gone; see the module note and `_num_repair`). =handle restores the legacy handle-only strip byte
        # for byte; ANY other value (absent included) is the fail-closed drop.
        _failclosed = os.environ.get("GRAPHRAG_VERIFY_NUM_MODE", "") != "handle"
        # ROUND-2 (2026-09-17): the documented rollback for step (2) of the orphan ladder ONLY. With it
        # off the FIGURE CUT carries every slot the lint saves, and no row value can reach the page by any
        # route -- CYCLE-10's guarantee, restored by one environment variable.
        _orphan_repair = os.environ.get("GRAPHRAG_VERIFY_ORPHAN_REPAIR", "on") != "off"

        evidence = evidence or []
        number_calls = number_calls or []
        # 09-23 (C4/C6): ONE charge-site context for the whole run -- the served-scalars pool and the
        # per-sentence derived unit grammar. `served_scalars=None` is an EMPTY pool: HEAD's reading.
        ctx = _VCtx(number_calls, served_scalars)
        _readdressed: list = []
        _resolved_undeclared: dict = {}
        _ledger_ambiguous: dict = {}
        _e_readdressed: list = []
        _e_date_bad: set = set()                    # refs a bound full date contradicted
        _e_date_ok: set = set()                     # refs some sentence cited without contradiction
        _e_numerals = 0
        _row_ids_present = any(isinstance(c, dict) and c.get("_row_id") for c in number_calls)

        # T2b Lane-B RCA (2026-07-28): which KINDS of handle each index is written with in the prose. The
        # ledger `ref` is a BARE INTEGER by contract -- answer.py's tool schema types it {"type":"integer"}
        # and _SYSTEM tells the model "handle [E1] -> {ref: 1, ...} (an integer, not the string \"E1\")".
        # So the `ref.upper().startswith("N")` numbers-skip below was UNREACHABLE for every real serving
        # turn: a model that (correctly) declared its cited [N] rows had each declaration matched against
        # the EVIDENCE list, failed -- a numbers row is not a document -- and was charged
        # fabricated_citation. Measured on gate run 94468a0b: 19 of 50 strips, and in 3 answers it also
        # DELETED the reader's `## Sources` block. The prose kind is the missing discriminator.
        _prose_all = (structured.get("tldr") or "") + "\n" + (structured.get("mechanism") or "")
        _kinds: dict[str, set[str]] = {}
        # CYCLE-9 AMENDMENT 3a: every MEMBER of every token. An index cited ONLY in grouped form used to be
        # absent from this map, so `_is_number_declaration` could not recognize its ledger entry and the row
        # stripped as a fabricated_citation. Backing-side only, and it can only ever KEEP a ledger row.
        for _m in _HANDLE.finditer(_prose_all):
            for _k, _i in _handle_members(_m.group(0)):
                _kinds.setdefault(str(_i), set()).add(_k or "E")

        def _is_number_declaration(ref: str) -> bool:
            """This unmatched ledger entry declares an injected NUMBERS row, not a fabricated document.
            True only when the prose actually wrote [N<ref>] and <ref> indexes a real injected call --
            so a genuine invented source still strips, and an [E<ref>]/[<ref>] entry on the SAME integer
            is still resolved on its own merits (the E/N integer namespaces collide by schema: without
            this the numbers entry overwrote resolved[ref] = [] and stripped the legitimate [E] handle
            that pointed at a real dated item)."""
            return (ref.isdigit() and "N" in _kinds.get(ref, set())
                    and 1 <= int(ref) <= len(number_calls))

        # 1) resolve the model's ledger to real items; correct mistyped dates; drop fabrications
        resolved: dict[str, list[dict]] = {}
        # D-DV-1(iii): the refs whose LEDGER entry found no item. Each one strips its own row as
        # fabricated_citation below AND leaves resolved[ref] = [], which charges every prose sentence citing
        # it -- the s5 A/B's "35 fabricated citations" were ~12 distinct sentences off 6 unmatched rows. The
        # cascade strips are re-keyed `ledger_cascade` so fabricated_citation counts DEFECTS (a cited handle
        # with no such item in the evidence list), not the sentences downstream of one.
        cascade_refs: set[str] = set()
        ambiguous_refs: set[str] = set()
        kept_sources = []
        for s in (structured.get("sources") or []):
            ref = str(s.get("ref", "")).strip().strip("[]")
            if ref.upper().startswith("N"):
                kept_sources.append(s)                    # numbers refs are positional; checked in prose
                continue
            # 09-23 (BRIEF item 8, THREAT_MODEL V-10) -- LEDGER IDENTITY BEFORE ANY DOCUMENT MATCH. MEASURED
            # on the cotton turn: eleven [N] declarations whose SOURCE name ("USDA WASDE") also names a
            # document in the evidence list were matched AS that document and re-dated to it, and the
            # footer bound the 2024/25-2026/27 balance sheet (known 2026-09-11) to a January-2025 WASDE.
            # A ref the prose writes ONLY as [N<ref>], indexing a real call, is a NUMBER declaration and is
            # never offered to the document matcher; an integer the prose ALSO writes as [E<ref>] keeps
            # HEAD's order (the E/N collision rule `_is_number_declaration` documents).
            if _is_number_declaration(ref) and "E" not in _kinds.get(ref, set()):
                kept_sources.append(s)
                continue
            matched = _match_ledger_entry(s, evidence)
            if not matched:
                if _is_number_declaration(ref):           # ditto -- the schema just cost it its "N" prefix
                    kept_sources.append(s)
                    continue
                # 09-23 (V-11): the source names SEVERAL documents and none carries the declared date -- the
                # entry is AMBIGUOUS, not fabricated. Counted, kept in the ledger, never re-dated and never
                # resolved; its prose handle is left standing for the footer's own rowless-ref prune.
                _same = _same_source_items(s, evidence)
                if len(_ledger_documents(_same)) > 1:
                    ambiguous_refs.add(ref)
                    _ledger_ambiguous[ref] = {"source": s.get("source"), "date": s.get("date"),
                                              "candidates": len(_ledger_documents(_same))}
                    kept_sources.append(s)
                    continue
                report["stripped"] += 1
                report["by_rule"]["fabricated_citation"] = report["by_rule"].get("fabricated_citation", 0) + 1
                resolved[ref] = []
                cascade_refs.add(ref)
                continue
            true_date = matched[0].get("date")
            if s.get("date") and true_date and str(s["date"])[:10] != str(true_date)[:10]:
                s = {**s, "date": true_date}
                report["corrected"] += 1
            resolved[ref] = matched
            kept_sources.append(s)
            m0 = matched[0]
            txt = m0.get("text") or ""
            report["resolved"][ref] = {"source": m0.get("source"), "date": m0.get("date"),
                                       "source_key": m0.get("source_key"),
                                       "snippet": txt[:140] + ("..." if len(txt) > 140 else ""),
                                       # Phase F: the span keys ride to structured.sources -> the PDF
                                       # highlight; None on pre-offset vintages (the honest legacy shape)
                                       "char_start": m0.get("char_start"), "char_end": m0.get("char_end"),
                                       "offset_kind": m0.get("offset_kind")}
        structured["sources"] = kept_sources

        # 1b) D-HP-9/D-HP-10 -- UNDER HANDLE-PROSE AN [E] HANDLE IS POSITIONAL, NOT LEDGERED.
        # `[E{i}]` means `uniq[i-1]` in all three places (D-HP-1 (iii)), so an index inside the range the
        # GROUNDING LEDGER line stated is a resolved address by construction and needs no model-authored
        # declaration to prove it. Without this the [E] branch of PASS 1 routes EVERY handle to
        # `undeclared_unsupported` the moment the ledger is gone -- the corpus carries 3,813 [E] markers
        # against ONE such strip today precisely because handles are normally DECLARED.
        # THE PAYLOAD SHAPE IS verify.py's OWN (source/date/source_key/snippet, 140 chars + ellipsis), so
        # `_attach_provenance`, `_cited_sources_block`, `_prune_orphan_evidence_handles`, the FE chip path
        # and `eval._closure_cited` all join exactly as they do on a ledgered turn.
        # A ref the LEDGER already spoke for is never overwritten (including one it CONVICTED -- a
        # `cascade_refs` entry sits in `resolved` as [] and stays there): a conviction outranks a position.
        if handle_prose:
            for _ref, _knds in _kinds.items():
                if "E" not in _knds or _ref in resolved or not _ref.isdigit():
                    continue
                _i = int(_ref)
                if not (1 <= _i <= len(evidence)):
                    continue                              # out of range: the undeclared branch, unchanged
                _item = evidence[_i - 1]
                resolved[_ref] = [_item]
                _txt = _item.get("text") or ""
                report["resolved"][_ref] = {"source": _item.get("source"), "date": _item.get("date"),
                                            "source_key": _item.get("source_key"),
                                            "snippet": _txt[:140] + ("..." if len(_txt) > 140 else ""),
                                            # Phase F: same span keys as the ledgered branch -- the :1057
                                            # comment's shape-parity law is why these two move together
                                            "char_start": _item.get("char_start"),
                                            "char_end": _item.get("char_end"),
                                            "offset_kind": _item.get("offset_kind")}

        # 2) sentence-scoped prose checks; strip violating handles BY POSITION (formatting untouched)
        _BOUND = re.compile(r"[.!?;](?=\s|$)|\n")         # never a decimal point (needs trailing space/EOL)

        def _sentence_span(text: str, pos: int) -> tuple[int, int]:
            start = 0
            end = len(text)
            for b in _BOUND.finditer(text):
                if b.start() < pos:
                    start = b.end()
                elif b.start() >= pos:
                    end = b.end()
                    break
            return start, end

        def _sentence_at(text: str, pos: int) -> str:
            a, b = _sentence_span(text, pos)
            return text[a:b]

        def _drop_span(text: str, s0: int, s1: int) -> tuple[int, int]:
            """The span a WHOLE-SENTENCE drop deletes. A sentence starts AFTER the previous terminator, so it
            already owns its leading space ('A. B. C.' minus B reads 'A. C.'); the first sentence has none, so
            it takes the following space instead and the field never opens on an indent."""
            if s0 == 0:
                while s1 < len(text) and text[s1] == " ":
                    s1 += 1
            return s0, s1

        def _drop_orphans(text: str, s0: int, s1: int) -> bool:
            """D-EC PRE-ARM (2026-09-17), TWO-SIDED since the round-2 review (MAJOR-2). True when deleting
            `text[s0:s1]` would leave a FRAGMENT of a reader's sentence behind, on either side of the cut.

            THE ROOT CAUSE, NAMED AND CLOSED IN BOTH DIRECTIONS. `_BOUND` ends a unit on ';' as well as on
            '.', so a semicolon-joined clause is a droppable "sentence" that is only HALF of what the
            reader reads -- and a cut at a ';' boundary strands the other half whichever half it takes:
              * PROMOTION (the successor side, the smoke's quick corn/wheat orphan). The dropped unit
                itself OPENED a sentence -- nothing but a real terminator ('.', '!', '?'), a line break or
                the field start in front of it -- and the first non-blank character after the span is a
                lowercase letter, so the SECOND half of the reader's sentence is promoted to sentence-
                initial position: "... on confidence alone. planted area at the 98th percentile [N69]".
              * MIRROR (the predecessor side, round-2 review MAJOR-2, measured). The dropped unit is the
                TAIL clause and the LEAD clause is left dangling on a bare semicolon: "Stocks are ample;
                the index sat at -0.693675 z [N1]." served as "Stocks are ample;", and "Corn is tight; the
                ratio reads 0.5 [N1]. Wheat is loose." served as "Corn is tight; Wheat is loose.". The
                round-1 lint covered only the first direction and MADE FOUR MORE of the second than HEAD
                (verifier-made dangling ';' lines, 112 banked answers: HEAD 1, round-1 build 5).
            The mirror test is read off the ROOT and not off the symptom: the head, stripped of trailing
            blanks, ENDS IN ';' -- i.e. the previous `_BOUND` was a semicolon, so this unit is not a
            sentence the reader would recognize as one and no cut here can be clean.
            PURE PREDICATE: it reads the text and takes no decision of its own; PASS 2 owns the remedy."""
            head = text[:s0]
            if head.rstrip().endswith(";"):
                # MIRROR. The lead clause is only left WHOLE when a lowercase continuation follows on the
                # same line ("A; B; c." -> "A; c." reads exactly as the writer punctuated it). An empty
                # tail strands the lead on a bare ';' ("Stocks are ample;"), a line break does the same,
                # and an uppercase successor welds a new sentence onto the semicolon ("Corn is tight;
                # Wheat is loose."). Those three are the measured residue and the ONLY ones refused here.
                return not text[s1:].lstrip(" \t")[:1].islower()
            if head.strip() and not re.search(r"(?:[.!?][\"')\]]?[ \t]*|\n[ \t]*)\Z", head):
                return False
            tail = text[s1:].lstrip(" \t")
            return bool(tail) and tail[0].islower()        # PROMOTION

        foreign = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(foreign_names)) + r")\b") \
            if foreign_names else None

        # D-EC PRE-ARM (2026-09-17) -- ONE SENTENCE, ONE AUDIT ENTRY. The audit is a CAPTURE, and every
        # rule here is charged PER OFFENDING HANDLE, so a sentence whose three handles all fail the same
        # rule wrote the SAME row three times. Measured on the 2026-09-16 smoke: 15 audit rows over five
        # answers, 9 distinct (rule, field, sentence) -- deep's ENSO bullet x3, max's crush sentence x2,
        # palm/rape's rapeseed sentence x3 and its dated-documents bullet x3. A reader counting rows read
        # "15 charges" where the verifier touched nine sentences, and the SMOKE REPORT did exactly that.
        # SCOPE, DELIBERATELY NARROW: this de-duplicates the AUDIT ONLY. `stripped` and `by_rule` keep
        # their per-offending-handle semantics untouched, because they are the estate's standing strip
        # counters and every banked number is denominated in them -- a counter redefinition on the eve of
        # an arm is the first-order threat this sitting is fenced against. No strip decision reads this
        # list (the capture-only contract above), so nothing downstream of a drop can move.
        _audit_seen: set[tuple[str, str, str]] = set()

        def _audit(rule: str, field: str, sent: str) -> None:
            # offending magnitudes = the sentence's CLAIM numbers (citation-handle digits AND the
            # exempted time/name tokens removed -- the SAME extractor the number guard uses), so the
            # audit list agrees with the strip decision and an RCA dump keys stripped text by rule
            # without re-parsing prose.
            # D-DA UNIT-VOCABULARY GATE: a scale token the gate RE-ADMITS is one of this sentence's
            # claim magnitudes, so it rides the audit list too and the promise above holds. Empty on
            # every sentence the gate does not fire on, so no existing audit row moves.
            # ROUND-2 B-4: the de-duplication key is minted whether or not the audit is lit, because
            # `strip_sentences` is a COUNTER and must not depend on a capture flag.
            _key = (rule, field, sent.strip())
            _first = _key not in _audit_seen
            _audit_seen.add(_key)
            report["strip_sentences"] = len(_audit_seen)
            if _audit_on and _first:                      # one sentence, one entry (see the note above)
                _g = ctx.grammar(sent)
                report["strip_audit"].append(
                    {"rule": rule, "field": field, "text": sent.strip(),
                     "numbers": ([v for _a, _b, v in _claim_number_spans(_HANDLE.sub("", sent), units=_g)]
                                 + _unit_vocab_claims(sent, number_calls, units=_g))})

        def _pass0(text: str, field: str) -> str:
            """09-23 PASS 0 -- the one value-preserving insertion (see the block note at `_handle_groups`),
            sentence by sentence on `_BOUND`'s own spans, BEFORE any verdict is read: the same-row
            re-address (board calls only -- nothing to do without a `_row_id`). Each sentence is rebuilt
            from its own pieces, so no offset outside it can move. The noun-object splice that ran here on
            EVERY sentence is retired (fix-round review FATAL-5): it wrote figures into uncharged prose."""
            if not _HANDLE.search(text or ""):
                return text
            out, at = [], 0
            for _b in list(_BOUND.finditer(text)) + [None]:
                _end = _b.end() if _b is not None else len(text)
                if _end <= at:
                    continue
                piece, at = text[at:_end], _end
                if _HANDLE.search(piece):
                    if _row_ids_present:
                        piece = _readdress_sentence(piece, number_calls, ctx, field, _readdressed)
                out.append(piece)
            return "".join(out)

        def _count_e_numerals(text: str) -> int:
            """OWNER DECISION 13 -- claim numerals in sentences whose only handles are [E]: counted, never
            charged (the [E] path checks words and quotes, not figures)."""
            n, at = 0, 0
            for _b in list(_BOUND.finditer(text or "")) + [None]:
                _end = _b.end() if _b is not None else len(text or "")
                if _end <= at:
                    continue
                piece, at = text[at:_end], _end
                kinds_here = {k for m in _HANDLE.finditer(piece) for k, _i in _handle_members(m.group(0))}
                if kinds_here and "N" not in kinds_here:
                    n += len(_claim_number_spans(_mask_handles(piece)))
            return n

        def _verify_field(text: str, field: str = "") -> str:
            nonlocal _e_numerals
            text = _pass0(text, field)
            _e_numerals += _count_e_numerals(text)
            # PASS 1 -- every verdict is read against the ORIGINAL text (positions must all stay comparable);
            # nothing is applied until pass 3. A fail-closed number_mismatch is DEFERRED because its remedy
            # (repair vs whole-sentence drop) depends on the other handles sharing its sentence.
            drops: list[tuple[int, int]] = []
            # ROUND-2 (2026-09-17): the SUBSTITUTIONS the orphan ladder makes -- (start, end, text) in
            # FIELD coordinates, applied beside the deletions in PASS 3. Empty on every field the ladder
            # does not reach, which is every field in the estate's banked corpus but seven sentences.
            edits: list[tuple[int, int, str]] = []
            # ...and the PASS-1 `number_unbacked` handle drops, kept so the ladder can un-take one that
            # turns out to be a printed figure's last backer inside a sentence the orphan lint saves.
            unbacked_drops: list[tuple[int, int, int, int, int]] = []
            undrop: set[tuple[int, int]] = set()
            pending: list[tuple[int, int, str, int]] = []
            # sentence span -> every DECLARED handle in it that resolved, as (handle span, pool, per-handle
            # rule). Their verdict is deferred to PASS 1b because the quoted-span question is a SENTENCE
            # question, and (as in the old per-handle order) it outranks no_lexical_overlap.
            # CYCLE-9 AMENDMENT 3a: the tuple grew a CHARGEABLE flag. A GROUPED token's members contribute
            # their resolved pool to the sentence's quoted-span question (backing) and are never drop
            # candidates and never counted -- see the amendment note at `_HANDLE`.
            quoting: dict[tuple[int, int], list[tuple[int, int, list[dict], str | None, bool]]] = {}
            for m in _HANDLE.finditer(text):
                _members = _handle_members(m.group(0))
                if len(_members) > 1:                     # GROUPED: backing only, never a charge
                    s0, s1 = _sentence_span(text, m.start())
                    for _k, _i in _members:
                        _r = str(_i)
                        if _k != "N" and _r in resolved and _r not in cascade_refs:
                            quoting.setdefault((s0, s1), []).append(
                                (m.start(), m.end(), resolved[_r], None, False))
                    continue
                report["checked"] += 1
                s0, s1 = _sentence_span(text, m.start())
                sent = text[s0:s1]
                if m.group("kind") == "N":
                    rule = _check_number_handle(sent, int(m.group("idx")), number_calls, ctx=ctx)
                else:
                    ref = m.group("idx")
                    if ref in resolved and ref not in cascade_refs:
                        _r = _check_evidence_handle(sent, resolved[ref], quotes=False)
                        if _r is None:
                            # 09-23 (BRIEF item 9): the handle is bound by its document's IDENTITY -- a full
                            # date bound to it must be a date the item carries (see `_e_date_verdict`).
                            _dv, _new = _e_date_verdict(text, m.start(), m.end(), s0, s1, resolved[ref],
                                                        evidence)
                            if _dv == "readdress":
                                resolved[ref] = _new
                                report["resolved"][ref] = _resolved_payload(_new[0])
                                _e_readdressed.append({"ref": ref, "field": field,
                                                       "date": _new[0].get("date")})
                            elif _dv:
                                _r = _dv
                            (_e_date_bad if _dv == "date_contradiction" else _e_date_ok).add(ref)
                        quoting.setdefault((s0, s1), []).append(
                            (m.start(), m.end(), resolved[ref], _r, True))
                        continue                          # verdict AND charge both land in PASS 1b
                    if ref in ambiguous_refs:             # 09-23 (V-11): kept, never re-dated, never charged
                        continue
                    if ref in cascade_refs:               # downstream of an unmatched ledger row, not a
                        rule = "ledger_cascade"           # fabrication of its own (D-DV-1 iii)
                    else:                                 # handle never declared in the ledger: keep it only
                        rule = ("undeclared_unsupported"  # if SOME provided item supports the sentence
                                if _check_evidence_handle(sent, evidence) else None)
                        # 09-23 (BRIEF item 10, C15): an undeclared [E<i>] the turn's evidence MENU holds at
                        # index i, whose item ITSELF supports the sentence (and carries every full date
                        # bound to the handle), is resolved POSITIONALLY -- one document, one address -- so
                        # the footer can emit its row instead of the prune serving its figures bare.
                        if rule is None and ref.isdigit() and 1 <= int(ref) <= len(evidence):
                            _it = evidence[int(ref) - 1]
                            if (_positional_support(sent, _it, evidence)
                                    and _e_date_verdict(text, m.start(), m.end(), s0, s1, [_it],
                                                        evidence)[0] is None):
                                _resolved_undeclared.setdefault(ref, _resolved_payload(_it))
                if rule == "number_mismatch" and _failclosed:
                    pending.append((m.start(), m.end(), s0, s1, sent, int(m.group("idx"))))
                    continue
                if rule:
                    drops.append((m.start(), m.end()))
                    if rule == "number_unbacked":
                        # ROUND-2 MAJOR-1: remembered, not re-decided. `number_unbacked` strips the handle
                        # and leaves the figure -- HEAD's behaviour, untouched everywhere except inside a
                        # sentence the orphan lint KEEPS, where the ladder below may find that this handle
                        # is the last thing backing a figure the reader will still see. The CHARGE is
                        # already counted above either way.
                        unbacked_drops.append((m.start(), m.end(), s0, s1, int(m.group("idx"))))
                    report["stripped"] += 1
                    report["by_rule"][rule] = report["by_rule"].get(rule, 0) + 1
                    _audit(rule, field, sent)

            # PASS 1b -- the QUOTED-SPAN verdict, taken per SENTENCE over every declared handle in it. The
            # old per-handle rule made EVERY cited handle carry EVERY span, so a two-source sentence whose
            # handles each back their own clause stripped the innocent one (D-DV-0(2): 2 of deep's 6). It
            # fires only when NO cited pool carries the span, and then ONCE: the sentence's handles go
            # together as a single strip record, the way a number_mismatch whole-sentence drop already
            # counts (dropped together, charged once). A backed span leaves each handle to answer for its
            # own rule -- quote_mismatch outranking no_lexical_overlap, as the per-handle order did.
            for (q0, q1), group in quoting.items():
                sent = text[q0:q1]
                # CYCLE-9 AMENDMENT 3a: the POOLS include every grouped member's resolved items (a span
                # carried by a group-cited source is backed for the sentence), while only the CHARGEABLE
                # entries can be dropped or counted. A sentence whose only handles are grouped therefore
                # takes no strip at all -- backing added, charges unchanged.
                _chargeable = [e for e in group if e[4]]
                if _unbacked_quote(sent, [p for _a, _b, p, _r, _c in group]) is not None:
                    if _chargeable:
                        for h0, h1, _p, _r, _c in _chargeable:
                            drops.append((h0, h1))
                        report["stripped"] += 1
                        report["by_rule"]["quote_mismatch"] = report["by_rule"].get("quote_mismatch", 0) + 1
                        _audit("quote_mismatch", field, sent)
                    continue
                for h0, h1, _p, rule, _c in _chargeable:
                    if rule:
                        drops.append((h0, h1))
                        report["stripped"] += 1
                        report["by_rule"][rule] = report["by_rule"].get(rule, 0) + 1
                        _audit(rule, field, sent)

            # ══ D-HP-12 -- THE DIGIT-LINT'S CHARGE, PER SENTENCE ═══════════════════════════════════════
            # PER SENTENCE because `claim_count` (the strip-rate denominator every successor metric in
            # D-HP-17 divides by) is SENTENCES, not handles -- charging per numeral would denominate the
            # new class against a quantity nothing else in the ledger uses.
            # IT ADDS NO DROP SPAN. The charge is the ledger entry; the deletion is
            # `answer._drop_bare_digit_sentences`, which runs FIRST in the handle stack (before any value
            # splice can put an ENGINE digit where this pass would read a MODEL one) and re-detects through
            # `bare_digit_verdict`, the one producer both halves share.
            # The walk is `_BOUND`'s own, so the lint's sentence and the strip machinery's sentence are the
            # same span -- a second sentence splitter is how two passes come to disagree about a boundary.
            if handle_prose:
                _lint_at = 0
                for _b in list(_BOUND.finditer(text)) + [None]:
                    _lint_end = _b.end() if _b is not None else len(text)
                    if _lint_end <= _lint_at:
                        continue
                    _lint_sent, _lint_at = text[_lint_at:_lint_end], _lint_end
                    _verdict = bare_digit_verdict(_lint_sent)
                    if _verdict == "e_cited":             # R3(b): counted, never charged, never dropped
                        report["bare_digit"]["e_cited"] += 1
                    elif _verdict == "bare_digit":
                        report["bare_digit"]["charged"] += 1
                        report["stripped"] += 1
                        report["by_rule"]["bare_digit"] = report["by_rule"].get("bare_digit", 0) + 1
                        _audit("bare_digit", field, _lint_sent)

            if foreign:                                   # a regime name from ANOTHER contract's DAG is a
                for m in foreign.finditer(text):          # cross-contract fabrication, never a citation issue
                    drops.append((m.start(), m.end()))
                    report["stripped"] += 1
                    report["by_rule"]["foreign_regime_name"] = report["by_rule"].get("foreign_regime_name", 0) + 1
                    _audit("foreign_regime_name", field, _sentence_at(text, m.start()))

            # PASS 2 -- resolve the deferred mismatches. TWO outcomes per offending handle, since
            # CYCLE-10 (2026-08-08) deleted the third:
            #   * SIBLING-BACKED (r5 RCA, widened D-EC pre-arm): every claim numeral in the sentence is
            #     materialized by another [N] written in it, so no figure here is a fabrication and only
            #     the mis-citing HANDLE goes -- the pre-fix remedy, correctly scoped at last. Decided
            #     FIRST, and it is the ONLY way a charged sentence keeps its figure.
            #   * KILLED: everything else. The sentence goes with its audit record.
            # THE THIRD OUTCOME IS GONE. "REPAIRABLE" used to mean "every mismatched handle in the sentence
            # agrees on the same one-numeral/one-row rewrite, and it survives the fences" -- the figure was
            # rewritten and the handles stayed. Three recorded ops across gates 6-7, three corrupted
            # sentences, the last of them through a clean pass of all four cycle-9 allowlist clauses. The
            # capability is deleted, not re-fenced (see `_num_repair`), so `per_sent` / `edits` / the
            # agreement test have no reason to exist: a pending handle is backed or its sentence dies.
            # D-EC PRE-ARM (2026-09-17) CORRECTION TO THIS NOTE: the rescue is no longer scoped to "the
            # lone numeral". It asks whether EVERY claim numeral in the sentence is backed by a sibling,
            # which is the same fail-closed question asked of the whole sentence instead of of one token;
            # see `_sibling_backed` for the four measured deletions that scope cost.
            #
            # ══ THE ORPHAN LINT -- A CUT MAY NEVER PROMOTE A LOWERCASE CONTINUATION ═══════════════════
            # `_BOUND` terminates a "sentence" on ';' as well as on '.', so a whole-sentence drop can cut
            # a semicolon-joined clause OUT OF THE MIDDLE of a reader's sentence. MEASURED, the smoke's
            # quick corn/wheat turn shipped exactly that: the drop left
            #     "... neither dominates on confidence alone. planted area at the 98th percentile [N69]
            #      points toward lower."
            # -- which a PM grader named "the tell that a fence deleted the bull half". A fence that
            # leaves an orphan clause is FATAL by this estate's own doctrine, so the drop is REFUSED and
            # the proportionate remedy is taken instead: the sentence is KEPT. The event is STAMPED
            # (`report["orphan_kept"]`, minted only when it fires, and its own audit rule name) so a
            # refused fail-closed drop is never silent.
            # THE LINT IS TWO-SIDED (round-2 MAJOR-2): it refuses a cut that PROMOTES a lowercase
            # continuation AND a cut that strands the lead clause of a ';'-joined sentence. See
            # `_drop_orphans` for both arms and for the measured mirror residue it closes.
            # ROUND-2 MAJOR-1 -- THE RESIDUAL ROUND 1 STATED IS NOW CLOSED, NOT STATED. "The sentence is
            # kept and the mis-citing handle alone is removed" left SEVEN banked sentences printing a
            # figure with NO citation at all, which this estate's doctrine calls worse than a deletion.
            # A kept sentence now goes through the ladder below: the LAST BACKER is never dropped, an
            # unambiguous slot is REPAIRED from the cited row at the page's own precision, and a slot no
            # row figure can be established for loses its FIGURE and keeps its WORDS. Nothing this pass
            # keeps serves a claim numeral that no surviving handle in its own sentence materializes.
            killed: set[tuple[int, int]] = set()
            orphaned: set[tuple[int, int]] = set()
            kinds: dict[tuple[int, int], str] = {}        # handle span -> 'backed' | 'unbacked'
            for h0, h1, s0, s1, sent, idx in pending:
                if _sibling_backed(sent, idx, number_calls, ctx=ctx):
                    kinds[(h0, h1)] = "backed"
                    continue
                kinds[(h0, h1)] = "unbacked"
                # ROUND-2 MAJOR-2: the lint is a property of the SENTENCE SPAN, so it is asked BEFORE any
                # handle can decide the sentence's fate. Round 1 asked it per handle and after the
                # sibling test, so one un-rescuable handle in a ';'-joined clause still took the cut and
                # still left the fragment the lint exists to refuse.
                if _drop_orphans(text, s0, s1):
                    orphaned.add((s0, s1))
                else:
                    killed.add((s0, s1))

            # ══ THE KEPT SENTENCES -- THE LADDER (round-2 MAJOR-1). See the block note at
            #    `_orphan_repair_figure`: last backer, then repair, then the figure cut. ═══════════════
            spare: set[tuple[int, int]] = set()           # offending handles that SURVIVE their charge
            remedy: dict[tuple[int, int], str] = {}       # ...and the audit rule each one earns
            by_sent: dict[tuple[int, int], list] = {}
            for h0, h1, s0, s1, sent, idx in pending:
                if (s0, s1) not in killed:
                    by_sent.setdefault((s0, s1), []).append((h0, h1, sent, idx))
            for (s0, s1), items in sorted(by_sent.items()):
                sent = items[0][2]
                masked = _mask_handles(sent)
                _g = ctx.grammar(sent)
                spans = _claim_number_spans(masked, units=_g)
                pools: dict[int, list[float]] = {}
                for m in _HANDLE.finditer(sent):
                    for _k, _j in _handle_members(m.group(0)):
                        if _k == "N" and 1 <= _j <= len(number_calls):
                            pools[_j] = _mismatch_pool(number_calls[_j - 1],
                                                       _row_vals(number_calls[_j - 1]))
                p1 = [(d0, d1, j) for d0, d1, ss0, ss1, j in unbacked_drops if (ss0, ss1) == (s0, s1)]
                charged = {it[3] for it in items} | {j for _d0, _d1, j in p1}
                live = {j: p for j, p in pools.items() if j not in charged}
                # (1) THE LAST BACKER IS NEVER DROPPED. A handle whose own pool is the only thing in this
                # sentence that materializes a printed numeral stays, whatever it is charged for and
                # whichever pass charged it -- a `number_unbacked` drop from PASS 1 is un-taken here for
                # the same reason, because what the reader receives is one sentence, not two passes.
                for a, b, v in spans:
                    dec = [_token_decimals(masked[a:b])]
                    if any(_num_matches([v], p, dec) for p in live.values()):
                        continue
                    for h0, h1, _s, idx in items:
                        if _num_matches([v], pools.get(idx) or [], dec):
                            spare.add((h0, h1))
                            remedy[(h0, h1)] = "number_mismatch_backer_kept"
                            report["backer_kept"] = report.get("backer_kept", 0) + 1
                            live[idx] = pools.get(idx) or []
                            break
                    else:
                        for d0, d1, j in p1:
                            if _num_matches([v], pools.get(j) or [], dec):
                                undrop.add((d0, d1))
                                report["backer_kept"] = report.get("backer_kept", 0) + 1
                                live[j] = pools.get(j) or []
                                break
                # (2)/(3) whatever figure is STILL backed by no surviving handle in this sentence is
                # repaired from the cited row, or -- when no row figure can be established for the slot --
                # cut, with its sign and its unit, and replaced by words.
                unbacked = []
                for a, b, v in spans:
                    dec = [_token_decimals(masked[a:b])]
                    if _FIGCUT_COMPOUND.search(sent[:a]):
                        continue                          # a name, never a figure (see `_FIGCUT_COMPOUND`)
                    if not any(_num_matches([v], p, dec) for p in live.values()):
                        # 09-23 (C4): a figure the board printed, bound by rule (1)/(2), is backed -- it
                        # is never cut to "a level this page could not back".
                        if ctx.pool and ctx.pool_backs(sent, a, b, v, dec[0], key=sent):
                            continue
                        unbacked.append((a, b))
                if not unbacked:
                    continue
                _to = None
                if _orphan_repair and len(items) == 1 and len(pools) == 1 and len(unbacked) == 1:
                    _to = _orphan_repair_figure(sent, unbacked[0][0], unbacked[0][1],
                                                pools.get(items[0][3]) or [])
                if _to is not None:
                    _rule = "number_mismatch_orphan_repaired"
                    edits.append((s0 + unbacked[0][0], s0 + unbacked[0][1], _to))
                    report["repairs"].append({"field": field, "rule": _rule,
                                              "from": sent[unbacked[0][0]:unbacked[0][1]], "to": _to})
                    live[items[0][3]] = pools.get(items[0][3]) or []
                else:
                    _rule = "number_mismatch_orphan_figure_cut"
                    # ONE LITERAL, ONE CUT. Two claim spans separated by nothing but glue are two halves
                    # of one written quantity -- a mantissa and its exponent, the ends of a range -- and
                    # cutting them separately welds the replacement words together (see `_FIGCUT_EXP`).
                    cuts: list[list[int]] = []
                    for a, b in unbacked:
                        fa, fb = _figure_span(sent, a, b, units=_g)
                        if cuts and fa <= cuts[-1][1] + 2 and not re.search(r"[A-Za-z0-9]",
                                                                            sent[cuts[-1][1]:fa]):
                            cuts[-1][1] = max(cuts[-1][1], fb)
                        else:
                            cuts.append([fa, fb])
                    for fa, fb in cuts:
                        edits.append((s0 + fa, s0 + fb, _FIGCUT_WORDS))
                        report["repairs"].append({"field": field, "rule": _rule,
                                                  "from": sent[fa:fb], "to": _FIGCUT_WORDS})
                # THE HANDLE STAYS only where it cannot be MIS-READ: a sentence whose only [N] handle this
                # is. Where the sentence carries others, a handle left beside a neighbour's backed figure
                # would read as backing it -- the W4 A/B mis-attribution class -- so it goes, and the
                # sentence still serves no figure with nothing behind it.
                for h0, h1, _s, _idx in items:
                    remedy.setdefault((h0, h1), _rule)
                    if len(pools) == 1:
                        spare.add((h0, h1))

            for h0, h1, s0, s1, sent, _idx in pending:    # counted per OFFENDING handle, as every rule is
                report["stripped"] += 1
                report["by_rule"]["number_mismatch"] = report["by_rule"].get("number_mismatch", 0) + 1
                if (s0, s1) in killed:
                    drops.append(_drop_span(text, s0, s1))
                    _audit("number_mismatch", field, sent)
                    continue
                if (h0, h1) in spare:                     # it survived its charge: eval.py's `repaired`
                    report["repaired"] += 1
                else:                                     # the mis-citation alone is removed
                    drops.append((h0, h1))
                _rule = remedy.get((h0, h1))
                if _rule is None:                         # ROUND-2 MAJOR-4: labelled by the HANDLE's own
                    _rule = ("number_mismatch_orphan_kept"  # verdict, never by its sentence's
                             if kinds.get((h0, h1)) == "unbacked" else "number_mismatch")
                _audit(_rule, field, sent)
            if orphaned:                                  # ROUND-2 MAJOR-4: ORPHANS, never handles
                # ROUND-3 NEW-MAJOR-3: ACCUMULATED, like `backer_kept` beside it. `_verify_field`
                # runs once for `tldr` and once for `mechanism` and `orphaned` is its own local, so
                # the plain assignment made the answer-level counter read the SECOND field alone --
                # a deep turn carrying bulleted ";"-joined prose in both fields under-reported every
                # time, and this is the number the handoff asks lane F to print per answer.
                report["orphan_kept"] = report.get("orphan_kept", 0) + len(orphaned)

            # PASS 3 -- apply. Coalesce the drops first so a sentence span ABSORBS the handle spans inside it
            # (no double-drop, no corrupted slice), then rewrite in reverse position order.
            # CYCLE-10: every op is now a DELETION. There is no `edits` list to merge in and no mutation
            # record to emit -- `report["repairs"]` is the always-present field CYCLE-8 FIX 2(c) made
            # unconditional, and it stays present and stays EMPTY, so the artifact schema is unchanged and
            # `eval.verifier_panel` keeps printing its (now always 0) repair count.
            spans = _coalesce([d for d in drops if d not in undrop])
            ops = [(a, b, "") for a, b in spans]
            # ROUND-2: the orphan ladder's substitutions ride the SAME apply pass, and a substitution
            # inside a span this pass is deleting is discarded rather than spliced into a hole -- the
            # ladder only ever edits KEPT sentences, so the guard is a structural impossibility made
            # explicit, not a live branch.
            for a, b, v in edits:
                if not any(x <= a and b <= y for x, y in spans):
                    ops.append((a, b, v))
            for a, b, v in sorted(ops, reverse=True):
                text = text[:a] + v + text[b:]
            # CYCLE-5 (2026-08-07) TIDY-1 -- THE STRIP SEAMS, REPORTED. Purely ADDITIVE: this loop reads
            # the ops that were just applied and writes ONE new report key. It takes no decision, changes
            # no span, moves no counter -- the rule semantics above are frozen, and a reader of `stripped`
            # / `by_rule` / `strip_audit` sees byte-identical values with and without these three lines.
            #
            # WHAT IT IS FOR. A whole-sentence drop that removes the FIRST sentence of a non-first
            # paragraph leaves the rest of that paragraph opening on the space that used to separate the
            # two (`_drop_span` eats the trailing space only when the sentence started the FIELD). Gate-2
            # shipped four of these in two passes -- " That sits in El Nino territory, not La Nina.",
            # " if the ONI crosses into strong El Nino territory ...", " within recent range (...)" -- each
            # a headless continuation whose antecedent the verifier had correctly removed. The renderer can
            # only repair that safely if it knows WHERE a strip happened, and the honest carrier is the
            # text that now FOLLOWS the cut: a position would not survive humanize/scaffold/sanitize, but a
            # normalized prefix of the successor text does. Absent when nothing was deleted (OFF-arm-clean).
            #
            # FIX-CYCLE-2 (major 7): the seam is recorded as a NORMALIZED KEY and the SERIALIZED copy is
            # gated on GRAPHRAG_STRIP_AUDIT, the same gate `strip_audit` uses for the same reason. H1
            # FOLD ROUND 5 (W-A) moved the 40-character cut OFF the mint and ONTO that copy: the record
            # appended below keeps the key at its full `_SEAM_LOOKAHEAD` width for the licence compare,
            # and `_projected_seam` cuts a COPY for the projection. The tidy pass reads the internal
            # `report.strip_seams` carrier, which is always populated and which nothing downstream can
            # serialize. See `_VerifyReport` / `_seam_key` / `_projected_seam` above.
            #
            # H1 FOLD ROUND 3 (2026-08-13) -- FIX X2, THE PRODUCER TAG. Every seam now carries `src`,
            # naming the pass that minted it. The carrier is shared: `answer._mint_strip_seam` writes into
            # THIS list from the render passes (FIX Z12), so "the verifier's own drop record" was not a
            # property a reader could check -- and `answer._slot_orphan_licensed` was reading it as one.
            # `src` makes provenance explicit at the producer instead of inferred at the consumer.
            # THIS PRODUCER IS SLOT-EMPTYING: it removes a handle span from INSIDE a sentence, so its
            # seams are the ONE record that a value slot was emptied here, and they are what the
            # slot-orphan licence accepts. TIDY-2 (`answer._seam_adjacent`) accepts every tag -- its job is
            # seam repair and every producer opens a repairable seam.
            # H1 FOLD ROUND 3 -- FIX X6, THE EMPTY-KEY DECISION, STATED HERE AND AT `_mint_strip_seam`.
            # A strip applied at the very END of a field leaves no successor text, so the key is "". This
            # producer MINTS IT ANYWAY and that is deliberate: an end-of-field strip is a real position and
            # a real emptied slot ("...stood at [N9]" with no terminator), and refusing the seam would
            # blind the licence to the field-final case -- the commonest shape under handle-only prose.
            # Whole-sentence producers keep the opposite rule (they skip empty keys) because an empty key
            # can never TIDY-2-join to an orphan line, which is the only thing their seams are for.
            # H1 FOLD ROUND 4 (2026-08-13) -- FIX Y1: THE KEY IS MINTED FROM THE TEXT THIS FUNCTION IS
            # ABOUT TO RETURN, NOT FROM THE TEXT IT IS HOLDING.
            # THE DEFECT, REPRODUCED ON THE ESTATE'S OWN STORED PROSE. The `return` below applies
            # `_strip_cleanup` -- and a positional strip that empties a slot in front of a "."/","/";"
            # leaves exactly the " ." that cleanup closes. Minting before it therefore recorded a key ONE
            # CHARACTER LONGER, at every cut, than the string the renderer would read. A single strip
            # survives that (its key is the field-final "." or "", which carries no later cut inside the
            # window) but a field with TWO OR MORE strips does not: every seam but the LAST one spans a
            # later cut, the extra space lands inside the 32-char compare, `answer._slot_orphan_licensed`
            # refuses, and only the field-final cue sentence is remedied. Measured pre-fix:
            # "Stocks stood at [N9]. Exports totalled at [N8]." -> 2 seams, 1 drop, and the reader got
            # "Stocks stood at."; three strips shipped two fragments, four shipped three; both handle
            # namespaces; the comma spelling likewise. On stored prose,
            # data/.../tier_20260812T051533Z.json shipped "In MY2023 it was" while its immediate
            # neighbour -- whose key had no later cut in it -- was correctly removed. The asymmetry
            # INSIDE ONE FIELD was the whole tell.
            # WHY THE WINDOW, NOT THE RETURN VALUE. Cleaning `text[_pos:_pos+_SEAM_LOOKAHEAD]` is
            # provably the same compare as cleaning the whole field and re-deriving the offset, and it
            # needs no offset arithmetic (which is what would actually be fragile here):
            #   * `_strip_cleanup` only ever DELETES SPACES, so a match that straddles the window's LEFT
            #     edge can only delete characters BEFORE `_pos` -- and `_seam_key` strips leading
            #     whitespace anyway, so the key is identical either way;
            #   * a match straddling the RIGHT edge can only differ at raw offset ~120, i.e. far past the
            #     32 NORMALIZED characters `_slot_orphan_licensed` compares (it caps at 32 and floors at
            #     8, matching shorter keys whole), so no reachable difference survives into the compare;
            #   * and it never crosses a newline, so a cut at the end of a line cannot borrow the next.
            # The consumer additionally canonicalizes both sides (`answer._licence_canon`, FIX Y2), which
            # covers the same whitespace class for the OTHER producer; this fix is still stated here
            # because the honest key is the producer's own contract, and it is pinned as such.
            _shift = 0
            for a, b, v in sorted(ops):
                _pos = a + _shift
                _shift += len(v) - (b - a)
                if v == "":
                    _seam = {"field": field,
                             "key": _seam_key(_strip_cleanup(text[_pos:_pos + _SEAM_LOOKAHEAD])),
                             "src": "verify"}
                    report.strip_seams.append(_seam)
                    if _audit_on:
                        # W-A: a CUT COPY, never `_seam` itself -- the carrier stays full width.
                        report.setdefault("strip_seams", []).append(_projected_seam(_seam))
            return _strip_cleanup(text)

        for fld in ("tldr", "mechanism"):
            if structured.get(fld):
                structured[fld] = _verify_field(structured[fld], fld)
        # 09-23 (C15): the added keys, each ONLY when it has something to say.
        if _readdressed:
            report["readdressed"] = _readdressed
        if ctx.pool_hits:
            report["pool_backed"] = len({(k, a) for k, a, _v in ctx.pool_hits})
        if _resolved_undeclared:
            report["resolved_undeclared"] = _resolved_undeclared
        if _ledger_ambiguous:
            report["ledger_ambiguous"] = _ledger_ambiguous
        if _e_readdressed:
            report["e_date_readdressed"] = _e_readdressed
        if _e_numerals:
            report["e_numerals_unverified"] = _e_numerals
        # 09-23 (BRIEF item 9): a ledger entry EVERY citing sentence dated against its own document is not
        # that document -- its resolution and its ledger row go, as a fabricated entry's do, so the footer
        # can never print the contradicted document under the ref (the rice [E41] -> 2023 WASDE line).
        # A ref that ALSO backs some sentence without contradiction keeps both.
        for _ref in sorted(_e_date_bad - _e_date_ok):
            report["resolved"].pop(_ref, None)
            structured["sources"] = [x for x in (structured.get("sources") or [])
                                     if str(x.get("ref", "")).strip().strip("[]") != _ref]
    except Exception:  # noqa: BLE001 — a verifier bug must never eat an answer
        report["error"] = True
    return report


# ═══ COVERAGE HELPERS -- COUNTERS, NEVER CHARGES (STATE ENGINE S7 item 1) ═══════════════════════════
# THREE PUBLIC READERS OVER THE PREDICATES THIS MODULE ALREADY OWNS, and they exist so that a coverage
# instrument one package over does not have to reach for `_num_matches`, `_mismatch_pool`,
# `_claim_numbers_with_decimals`, `_mask_handles`, `_handle_members` and `_SENT_SPLIT` by their private
# names. NOT ONE OF THEM CAN CHARGE ANYTHING: no report, no `by_rule`, no strip, no return value the
# verifier reads. That separation is the (1b) lesson stated as code -- out-of-range [N] were caught
# 1054/1054 while wrong-but-VALID [N] were missed 217/1054, so counting handles is not checking
# bindings, and the thing that BINDS a board figure stays `_check_number_handle` above, unchanged.


def sentences(prose: str) -> list[str]:
    """The prose as this module's OWN sentences (`_SENT_SPLIT`), blanks dropped. One splitter in the
    estate: a coverage figure counted over a second sentence boundary would not be comparable with the
    strip-rate denominator (`claim_count`), which is split by this one."""
    return [s for s in _SENT_SPLIT.split(str(prose or "")) if s.strip()]


def cited_number_handles(prose: str) -> frozenset[int]:
    """Every `[N]` index the prose cites, through THE handle parser (`_HANDLE` + `_handle_members`).

    IT IS NOT THE NAIVE TEST. `eval._cascade_stats` asks `f"[{id}]" in prose`, which cannot see a
    GROUPED token (`[N41,42]`, `[N41-43]`); `_handle_members` is the shipped parser for exactly that
    shape, so a writer that grouped three handles into one token is credited with all three rather than
    with none. Pass POST-VERIFY `structured` prose and never `out['answer']` -- the `## Sources` footer
    re-renders every ledgered handle including the ones the verifier just stripped."""
    out: set[int] = set()
    for m in _HANDLE.finditer(str(prose or "")):
        for kind, idx in _handle_members(m.group(0)):
            if kind == "N":
                out.add(int(idx))
    return frozenset(out)


def row_pool(call: dict) -> list[float]:
    """What a citation of THIS call may claim: `_mismatch_pool`'s own pool -- the magnitudes the panel
    line PRINTED (`shown`) when the engine recorded them, else every row. The board's rows always carry
    `shown`, so a board figure is checked against the one magnitude its own handle was minted with."""
    return _mismatch_pool(call or {}, _row_vals(call or {}))


def figure_referenced(sents, values) -> bool:
    """Does any sentence carry a magnitude that matches any of `values` under `_num_matches`?

    THE SAME PREDICATE THE VERIFIER CHARGES WITH, used here only to COUNT. Handles are masked first
    (`_mask_handles`) so a handle's own digits can never be read as a claim, and the reader-precision
    arm rides along because `_claim_numbers_with_decimals` returns the decimals beside the values.

    IT IS DELIBERATELY THE LOOSE READ, and a caller reporting it should say so: `_num_matches` bridges
    five reporting scales, so a value match is evidence that a row reached the page and is not proof
    that THAT row did. The tight read is the cited-handle set above; report both."""
    vals = [v for v in (values or [])]
    if not vals:
        return False
    for s in sents or ():
        nums, decs = _claim_numbers_with_decimals(_mask_handles(s))
        if nums and _num_matches(nums, vals, decs):
            return True
    return False
