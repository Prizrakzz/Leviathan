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

import os
import re

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


def _match_ledger_entry(entry: dict, evidence: list[dict]) -> list[dict]:
    """Provided evidence items compatible with a ledger entry: source must match (substring either
    way — the model shortens 'usda_gain_soybean_oil' to 'USDA GAIN'); date must equal when both given."""
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
        for e in evidence:                                # mistyped date becomes a CORRECTION, not a strip
            es = _norm(str(e.get("source") or "")).replace(" ", "_")
            if es and (src in es or es in src):
                out.append(e)
    return out


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


def _claim_number_spans(s: str, *, cycle8: bool = True) -> list[tuple[int, int, float]]:
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
    'grew 5 percent') is untouched by every rule here. A fabricated magnitude ('23.5 MMT' with no such row)
    is untouched by all six rules and still strips.
    The span ENDS at the token core, so the sentence punctuation _CLAIM_NUM sweeps up is never part of it.

    `cycle8=False` returns the PRE-AMENDMENT view -- rules (a)-(d) only, exactly as HEAD extracted. Its one
    caller was `_num_repair`'s ambiguity gate (CYCLE-8 REVIEW MAJOR 4), which CYCLE-10 deleted along with
    the rest of the rewrite path, so the flag now has NO caller in this module. It is KEPT, deliberately:
    this function is the cycle-8 charge-side amendment, which the termination branch freezes EXACTLY as
    shipped, and dropping a parameter of a frozen extractor would be a change to that amendment's surface
    for no behavioural gain. The default (`True`) is the shipped view and is what every caller gets."""
    s = s or ""
    out = []
    for m in _CLAIM_NUM.finditer(s):
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
        if cycle8:
            if _ORDINAL_AFTER.match(after_core):
                continue                                        # (e) an ORDINAL slot: '85th percentile'
            if _DURATION_MOD.match(after_core):
                continue                                        # (f) a DURATION MODIFIER: '5-year mean'
        if (re.fullmatch(r"\d{4}", core) and 1900 <= v <= 2099
                and not _UNIT_AFTER.match(s[m.end():])):        # (a) year -- unless unit-suffixed
            continue
        if re.fullmatch(r"\d{1,2}", core):
            before, after = s[:m.start()], s[m.end():]
            if _RANGE_TAIL.search(before):
                continue                                        # (b) year-range SHORT tail only
            if (_DATE_DAY_TAIL.search(before) or _MONTH_BEFORE.search(before)
                    or (_MONTH_AFTER.match(after) and not _UNIT_AFTER.match(after))):
                continue                                        # (d) the DAY of a date
        out.append((m.start(), m.start() + len(core), v))
    return out


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


def _sibling_backed(sent: str, idx: int, number_calls: list[dict]) -> bool:
    """True when the sentence carries EXACTLY ONE claim numeral and ANOTHER [N] handle in it BACKS that
    numeral against its own mismatch pool.

    r5 RCA (2026-08-01). The verifier checks a handle against every numeral in its SENTENCE, so a handle
    cited for a qualitative clause is charged by a numeral it was never quoting: "the anomaly is at
    +0.98 degC and accelerating [N3] [N4]" charges [N4] (the +0.47 monthly step) because 0.98 is not 0.47.
    The fail-closed remedy then rewrote 0.98 -> 0.47 and left [N3] -- which DOES back 0.98 -- pointing at a
    figure that is no longer its own. Measured on both r5 renders: ol_cocoa_thin_record published
    "+0.47 degC ... [N3] [N4]" and ol_bait_bare_target_demanded published "+5 degC [N3]", the same [N3]
    contradicting itself across two rows of ONE deck.
    The number is NOT fabricated here -- a sibling handle materializes it -- so the fail-closed rationale
    ("a fabricated NUMBER survives the loss of its handle") does not apply, and the precise remedy is the
    ORIGINAL one: strip the mis-citing HANDLE and leave the corroborated figure standing. Scoped to the
    one-numeral shape on purpose: with two numerals nobody can say which one the charged handle meant, and
    that ambiguity keeps the whole-sentence drop."""
    masked = _mask_handles(sent)
    spans = _claim_number_spans(masked)
    if len(spans) != 1:
        return False
    v = spans[0][2]
    # CYCLE-6: the sibling rescue asks the SAME matching question, so it gets the same reader-precision arm
    # -- a sibling that backs "-0.31" against its own -0.30632 row is backing it, and refusing to see that
    # would send the sentence to the whole-drop path this rescue exists to avoid.
    dec = [_token_decimals(masked[spans[0][0]:spans[0][1]])]
    # CYCLE-9 (2026-08-08) AMENDMENT 3a: every MEMBER of every handle token, not just the solitary ones.
    # The gate-6 covenant corruption is exactly this loop failing to see [N5] inside `[N5, N10, N12]`.
    for m in _HANDLE.finditer(sent):
        for kind, j in _handle_members(m.group(0)):
            if kind != "N" or j == idx or not (1 <= j <= len(number_calls)):
                continue
            sib = number_calls[j - 1]
            if _num_matches([v], _mismatch_pool(sib, _row_vals(sib)), dec):
                return True
    return False


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
    ZERO POLICY IS UNTOUCHED: the callers' `a == 0 or b == 0` guard runs FIRST and still means 0 matches
    only 0, so a prose "0" can never round-rescue a 0.4 row. `d is None` -> the arm is absent entirely,
    which is what keeps every caller that does not thread decimals byte-identical.

    CYCLE-6 REVIEW (2026-08-08): the window is now ALSO fenced by `_READER_REL_CEILING` (see the constant).
    "a is b rounded to d places" AND "a and b are the same number to within 3%" -- both, always. The pinned
    behaviour above is unchanged (every one of those pairs is inside 3%); what the ceiling removes is the
    d=0 flat-window class, where a vague spelling could certify an arbitrarily wrong small magnitude."""
    if d is None or a == 0 or b == 0:
        return False
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


def _check_number_handle(sent: str, idx: int, number_calls: list[dict]) -> str | None:
    if not (1 <= idx <= len(number_calls)):
        return "index_out_of_range"
    row_vals = _row_vals(number_calls[idx - 1])
    # the HEADLINE check runs against what the cited LINE printed (`shown`), not the whole window it fetched
    pool = _mismatch_pool(number_calls[idx - 1], row_vals)
    # CYCLE-6: the same extraction, now carrying each token's WRITTEN precision alongside its value
    sent_nums, sent_decs = _claim_numbers_with_decimals(_HANDLE.sub("", sent))  # time/name tokens: NOT claims
    if sent_nums and pool and not _num_matches(sent_nums, pool, sent_decs):
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
        guard_nums, guard_decs = _claim_numbers_with_decimals(_HANDLE.sub("", sent))  # exemptions: extractor
        # backed = scale-1 match vs ANY row (pre-scaled cascade rows), OR the legacy scale-bridge vs the
        # sentence's OWN cited row (a '31.4 million MT' narration of its own raw-MT hybrid row is legitimate;
        # CROSS-row multi-scale backfill stays forbidden -- that is the R4 mis-attribution hole).
        # CYCLE-6: both arms carry the numeral's written precision (see `_reader_precision_match`).
        if guard_nums and allv and any(
                not (_num_backed(v, allv, dec=d) or (row_vals and _num_matches([v], row_vals, [d])))
                for v, d in zip(guard_nums, guard_decs)):
            return "number_unbacked"
    return None


def verify_citations(structured: dict | None, evidence: list[dict] | None,
                     number_calls: list[dict] | None = None, *,
                     foreign_names: set[str] | None = None,
                     handle_prose: bool = False) -> dict:
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
    """
    # CYCLE-8 FIX 2(c): `repaired` / `repairs` are ALWAYS present (0 / []), never gated. See the
    # no-laundering note in PASS 2.
    report = _VerifyReport({"enabled": True, "checked": 0, "stripped": 0, "corrected": 0, "claim_count": 0,
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

        evidence = evidence or []
        number_calls = number_calls or []

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
        kept_sources = []
        for s in (structured.get("sources") or []):
            ref = str(s.get("ref", "")).strip().strip("[]")
            if ref.upper().startswith("N"):
                kept_sources.append(s)                    # numbers refs are positional; checked in prose
                continue
            matched = _match_ledger_entry(s, evidence)
            if not matched:
                if _is_number_declaration(ref):           # ditto -- the schema just cost it its "N" prefix
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
                                       "snippet": txt[:140] + ("..." if len(txt) > 140 else "")}
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
                                            "snippet": _txt[:140] + ("..." if len(_txt) > 140 else "")}

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

        foreign = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(foreign_names)) + r")\b") \
            if foreign_names else None

        def _audit(rule: str, field: str, sent: str) -> None:
            # offending magnitudes = the sentence's CLAIM numbers (citation-handle digits AND the
            # exempted time/name tokens removed -- the SAME extractor the number guard uses), so the
            # audit list agrees with the strip decision and an RCA dump keys stripped text by rule
            # without re-parsing prose.
            if _audit_on:
                report["strip_audit"].append(
                    {"rule": rule, "field": field, "text": sent.strip(),
                     "numbers": _claim_numbers_in(_HANDLE.sub("", sent))})

        def _verify_field(text: str, field: str = "") -> str:
            # PASS 1 -- every verdict is read against the ORIGINAL text (positions must all stay comparable);
            # nothing is applied until pass 3. A fail-closed number_mismatch is DEFERRED because its remedy
            # (repair vs whole-sentence drop) depends on the other handles sharing its sentence.
            drops: list[tuple[int, int]] = []
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
                    rule = _check_number_handle(sent, int(m.group("idx")), number_calls)
                else:
                    ref = m.group("idx")
                    if ref in resolved and ref not in cascade_refs:
                        quoting.setdefault((s0, s1), []).append(
                            (m.start(), m.end(), resolved[ref],
                             _check_evidence_handle(sent, resolved[ref], quotes=False), True))
                        continue                          # verdict AND charge both land in PASS 1b
                    if ref in cascade_refs:               # downstream of an unmatched ledger row, not a
                        rule = "ledger_cascade"           # fabrication of its own (D-DV-1 iii)
                    else:                                 # handle never declared in the ledger: keep it only
                        rule = ("undeclared_unsupported"  # if SOME provided item supports the sentence
                                if _check_evidence_handle(sent, evidence) else None)
                if rule == "number_mismatch" and _failclosed:
                    pending.append((m.start(), m.end(), s0, s1, sent, int(m.group("idx"))))
                    continue
                if rule:
                    drops.append((m.start(), m.end()))
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
            #   * SIBLING-BACKED (r5 RCA): another [N] in the sentence materializes the lone numeral, so the
            #     figure is not a fabrication and only the mis-citing HANDLE goes -- the pre-fix remedy,
            #     correctly scoped at last. Decided FIRST, and it is the ONLY way a charged sentence keeps
            #     its figure.
            #   * KILLED: everything else. The sentence goes with its audit record.
            # THE THIRD OUTCOME IS GONE. "REPAIRABLE" used to mean "every mismatched handle in the sentence
            # agrees on the same one-numeral/one-row rewrite, and it survives the fences" -- the figure was
            # rewritten and the handles stayed. Three recorded ops across gates 6-7, three corrupted
            # sentences, the last of them through a clean pass of all four cycle-9 allowlist clauses. The
            # capability is deleted, not re-fenced (see `_num_repair`), so `per_sent` / `edits` / the
            # agreement test have no reason to exist: a pending handle is backed or its sentence dies.
            killed: set[tuple[int, int]] = set()
            backed: list[tuple[int, int, int, int, str]] = []
            for h0, h1, s0, s1, sent, idx in pending:
                if _sibling_backed(sent, idx, number_calls):
                    backed.append((h0, h1, s0, s1, sent))
                    continue
                killed.add((s0, s1))
            for h0, h1, s0, s1, sent, _idx in pending:    # counted per OFFENDING handle, as every rule is
                if (s0, s1) in killed:
                    drops.append(_drop_span(text, s0, s1))
                    report["stripped"] += 1
                    report["by_rule"]["number_mismatch"] = report["by_rule"].get("number_mismatch", 0) + 1
                    _audit("number_mismatch", field, sent)
                else:                                     # sibling-backed: the FIGURE stands, the
                    drops.append((h0, h1))                # mis-citation alone is removed
                    report["stripped"] += 1
                    report["by_rule"]["number_mismatch"] = report["by_rule"].get("number_mismatch", 0) + 1
                    _audit("number_mismatch", field, sent)

            # PASS 3 -- apply. Coalesce the drops first so a sentence span ABSORBS the handle spans inside it
            # (no double-drop, no corrupted slice), then rewrite in reverse position order.
            # CYCLE-10: every op is now a DELETION. There is no `edits` list to merge in and no mutation
            # record to emit -- `report["repairs"]` is the always-present field CYCLE-8 FIX 2(c) made
            # unconditional, and it stays present and stays EMPTY, so the artifact schema is unchanged and
            # `eval.verifier_panel` keeps printing its (now always 0) repair count.
            spans = _coalesce(drops)
            ops = [(a, b, "") for a, b in spans]
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
    except Exception:  # noqa: BLE001 — a verifier bug must never eat an answer
        report["error"] = True
    return report
