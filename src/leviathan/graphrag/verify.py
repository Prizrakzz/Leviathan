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
fail-closed -- the figure is rewritten from the cited row, or the whole sentence goes.
"""
from __future__ import annotations

import os
import re

# The optional trailing letter consumes model-minted variants like [E1b]: unmatched they LEAK to the
# reader as literal text (Stage-1 RCA q7); matched they resolve by idx and strip like any other handle.
_HANDLE = re.compile(r"\[(?P<kind>[NE]?)(?P<idx>\d+)(?:[a-z])?\]")
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
#   * what it carries is a NORMALIZED 40-char KEY (whitespace-collapsed, case-folded), not the prose. The
#     renderer join was always a normalized-prefix compare capped at 32 chars, so the key is everything the
#     join can use and nothing it cannot.
# The tidy pass must still work in PRODUCTION with the gate off, so the seams also ride an INTERNAL,
# NON-SERIALIZED carrier: `_VerifyReport.strip_seams`, an attribute on the returned dict subclass. It is
# invisible to json.dumps, to `dict(...)`, to every projection and whitelist -- so no client, artifact or
# durable record can ever see it -- while `answer._tidy_strip_orphans`, which is handed the report OBJECT
# two lines after `verify_citations` returns, reads it directly.
_SEAM_KEY_CHARS = 40


def _seam_key(s: str) -> str:
    """The normalized, bounded comparison form of a seam's successor text. `answer._seam_key` is the same
    normalization on the renderer side (whitespace-collapsed, case-folded) -- applying it here is what makes
    the join possible without shipping prose, and re-applying it there is idempotent."""
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()[:_SEAM_KEY_CHARS]


class _VerifyReport(dict):
    """The verifier report: a plain dict to every consumer, plus ONE attribute (`strip_seams`) that no
    serializer, projection or whitelist can see. See the seam note above for why the carrier must be
    off-dict rather than a gated key."""

    __slots__ = ("strip_seams",)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.strip_seams: list[dict] = []
# Denomination words that make a prose numeral scale-relative ('31.4 million MT'): a repair may not splice
# a row value next to one -- the row may be raw while the numeral is denominated (see _num_repair).
_SCALE_WORD = re.compile(r"\b(?:thousand|million|billion|trillion)\b", re.IGNORECASE)
# r5 RCA (2026-08-01): UNIT CLASSES for the repair guard. The measured defect was a TEMPERATURE rewritten
# from a RUN COUNT -- cascade._pace_legs binds a pace_streak call's `shown` to the streak length (5) with
# unit 'months' (cascade.py:1420), so a sentence citing the streak beside an ONI level repaired
# "+0.98 degC" to "+5 degC": a physically impossible anomaly, minted by the verifier itself. A repair may
# only splice a value whose unit belongs to the same class as the numeral it replaces. Unrecognized tokens
# resolve to None and NEVER refuse -- the guard fires on KNOWN disagreement only, so every legacy/agent-lane
# call (no `unit` key at all) repairs exactly as before.
_UNIT_CLASSES = {
    "count": ("day", "days", "week", "weeks", "month", "months", "quarter", "quarters",
              "year", "years", "period", "periods", "observation", "observations", "obs",
              "count", "counts", "times", "readings"),
    "pct": ("%", "percent", "percentage", "pct", "pp", "ppt", "bps"),
    "temp": ("c", "f", "k", "degc", "degf", "celsius", "fahrenheit", "kelvin"),
    "mass": ("mt", "mmt", "kt", "tonne", "tonnes", "ton", "tons", "kg", "lb", "lbs",
             "pound", "pounds", "bu", "mmbu", "bushel", "bushels", "bale", "bales", "cwt"),
    "area": ("ha", "hectare", "hectares", "acre", "acres"),
    "money": ("usd", "us$", "$", "eur", "brl", "myr", "cny", "cent", "cents", "usc"),
    "index": ("z", "sigma", "index", "points", "pts", "idx"),
}
_UNIT_OF = {tok: cls for cls, toks in _UNIT_CLASSES.items() for tok in toks}
# The synthetic metric suffix a streak call carries (cascade._pace_synth stamps
# query.metric = '<metric>_pace_streak'): the same COUNT tell as the unit, surviving a call whose row lost
# its unit key. A run length is never a magnitude, whatever else the record says.
_COUNT_METRIC = re.compile(r"_pace_streak\Z")
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
    The span ENDS at the token core, so the sentence punctuation _CLAIM_NUM sweeps up is never part of it
    (a repair rewrites the numeral, never the full stop after it).

    `cycle8=False` returns the PRE-AMENDMENT view -- rules (a)-(d) only, exactly as HEAD extracted. It has
    exactly one caller (`_num_repair`'s ambiguity gate, CYCLE-8 REVIEW MAJOR 4) and it exists because
    REMOVING a numeral from a sentence changes how many numerals that sentence has, which is the input to a
    decision that is not an extraction decision at all. See `_num_repair`."""
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


# CYCLE-8 REVIEW (2026-08-08), MINOR 7 -- the '-points' TAIL. `_UNIT_OF` knows percent / percentage / pct /
# pp / ppt / bps, and it did NOT know 'pct-points', so `_unit_class('pct-points')` was None, the target slot
# classified as nothing, and BOTH percent fences ((d2) and the `percent of` arm) fell through: the palm
# corruption reappeared verbatim on that one spelling ("roughly 2 pct-points below the average" ->
# "1,629,801"). The tail is stripped rather than enumerated so 'pct-point', 'pct-pts', 'percentage-points'
# and the '-pt' singular all land on their head token's class.
_UNIT_TAIL = re.compile(r"[-_](?:point|points|pt|pts)\Z", re.I)


def _unit_class(tok: str) -> str | None:
    """The unit CLASS of one prose/row token, or None when it is not a unit this guard recognizes. The
    degree sign is stripped so a draft's 'degC' and its '°C' twin land on the same class -- the r5 drafts
    write both, and the guard must not depend on which one the model reached for. A '-points' TAIL is
    stripped too (CYCLE-8 REVIEW MINOR 7, see `_UNIT_TAIL`) -- only after the direct lookup fails, so the
    bare 'points'/'pts' tokens `_UNIT_CLASSES['index']` owns keep resolving to `index` and are untouched."""
    t = (tok or "").strip().strip(".,;:!?()[]'\"").replace("°", "").lower()
    if not t:
        return None
    return _UNIT_OF.get(t) or _UNIT_OF.get(_UNIT_TAIL.sub("", t))


def _unit_class_lead(u: str) -> str | None:
    """CYCLE-8 (2026-08-08): `_unit_class` on the whole string, else on its LEADING token. A card's declared
    unit is often a phrase -- 'sigma vs 5-yr mean', 'BRL per USD (FRED)', 'Million Bushels' -- and the class
    is decided by its head. This is cycle-7's own reading (`citations._UNIT_CLASSES` anchors every pattern
    at \\A); applying it here is what lets the registry fallback below classify anything at all."""
    cls = _unit_class(u)
    if cls is None:
        m = re.match(r"\s*(\S+)", str(u or ""))
        cls = _unit_class(m.group(1)) if m else None
    return cls


def _registry_unit_class(call: dict) -> str | None:
    """CYCLE-8 FIX 2(b) -- THE CARD'S OWN UNIT, when the ROW carries none.

    THE MEASURED DEFECT (gate-5 `dcw_palm_stocks_print`, pass2). The repair spliced 1,629,801 -- an MT
    production print -- into "roughly 2 percent below the five-year average", shipping a 1,629,801 PERCENT
    claim. Cycle-7's unit-class fence was live and did not fire: it reads `row['unit']`, the served MPOB rows
    carry `unit: null`, and an unclassifiable source has always been the FAIL-OPEN case ("a call that
    declares NO unit repairs exactly as before"). But that call is not unit-less -- `silver_mpob`'s card
    declares `production_cpo_mt = MT`, and cycle-7's OWN fence on the citations side reads exactly that
    declaration (`citations._metric_unit`). So the fence had the answer available and was looking in the one
    place the estate's cascade/agent rows most often leave empty.

    Registry-backed and FAIL-OPEN at every step: an unknown table, a metric with no declared unit, a missing
    registry, a fixture whose `query` names nothing real -> None, and the repair proceeds exactly as it did
    before. Imported lazily; `citations` does not import this module, so there is no cycle."""
    q = (call or {}).get("query") or {}
    try:
        from leviathan.graphrag import citations as _cit
        return _unit_class_lead(_cit._metric_unit(str(q.get("table") or ""), str(q.get("metric") or ""),
                                                  q.get("commodity")))
    except Exception:  # noqa: BLE001 -- a unit lookup must never be the thing that breaks an answer
        return None


# CYCLE-8 REVIEW (2026-08-08), MAJOR 6 -- THE REGISTRY-INDEPENDENT ARM, FOR EVERY CLASS.
# FIX 2(b)'s registry lookup is the right instrument and it FAILS OPEN at every step by design (unknown
# table / no declared unit / unreadable registry -> None -> repair as before). Cycle-8 shipped exactly one
# registry-independent lock, (d2), and it covered PERCENT slots only, so a cross-class breach in any other
# dimension still depended on the registry being loadable. This is the general arm: a metric NAME that
# carries an explicit UNIT TOKEN declares the call's dimension without the registry ('ending_stocks_mt',
# 'fob_usd_t', 'stocks_use_pct', 'anomaly_degc', 'basis_usc_bu'). MEASURED against the estate's own naming:
# `production_cpo_mt` -> mass, `urea_usd_mt_zscore_5yr` -> the z tell (index), `ending_stocks_mt_pct` -> pct
# (the pct token is read LAST-WINS, so a pct-of-a-tonnage metric classifies as pct, not mass -- that is the
# same precedence `_PCT_METRIC` already asserts and it is what keeps '-5.11%' slots repairable).
# DELIBERATELY NOT A SEMANTIC GUESS. Only literal unit tokens count. 'oni_level_delta' is an ONI anomaly and
# a human reads degC off the name, but the NAME does not say so, and inventing a class from subject-matter
# would be the fence fabricating the very thing it is checking. Such a call stays unresolved and repairs --
# see the refutation note in `_num_repair` for why fail-closing it instead was measured and rejected.
_METRIC_TELL = (
    ("pct", re.compile(r"(?:\A|_)(?:pct|percent|percentage|pp|ppt|bps)(?:_|\Z)", re.I)),
    ("index", re.compile(r"(?:\A|_)(?:z|zscore|zscr|sigma|idx|index)(?:_|\Z)", re.I)),
    ("temp", re.compile(r"(?:\A|_)(?:degc|degf|celsius|fahrenheit|kelvin)(?:_|\Z)", re.I)),
    # NB 'us' is NOT a money token and a bare 't' is NOT a mass token: 'us_ending_stocks_mt' is a US series,
    # not a currency, and a lone '_t_' is a naming accident away from every table in the estate.
    ("money", re.compile(r"(?:\A|_)(?:usd|brl|eur|myr|cny|usc|cent|cents)(?:_|\Z)", re.I)),
    ("mass", re.compile(r"(?:\A|_)(?:mt|mmt|kt|tonne|tonnes|ton|tons|kg|lb|lbs|bu|mbu|mmbu|bushel|"
                        r"bushels|bale|bales|cwt)(?:_|\Z)", re.I)),
    ("area", re.compile(r"(?:\A|_)(?:ha|hectare|hectares|acre|acres)(?:_|\Z)", re.I)),
)


def _metric_tell_class(call: dict) -> str | None:
    """The unit class a metric NAME literally declares, or None. Registry-independent by construction: it
    reads only the call's own `query.metric`. PRECEDENCE IS DELIBERATE -- `pct` is tested first and wins
    outright, because a percent-denominated metric almost always names its base unit too
    (`ending_stocks_mt_pct`) and the percent IS the dimension of the number the call serves."""
    metric = str(((call or {}).get("query") or {}).get("metric") or "")
    if not metric:
        return None
    for cls, rx in _METRIC_TELL:
        if rx.search(metric):
            return cls
    return None


def _call_unit_class(call: dict, val: float) -> str | None:
    """The unit class the cited call would splice IN: the unit of the row carrying the repair value (a
    synthetic delta/pace record has exactly one row; a windowed level record is matched by value), plus the
    metric-suffix tell for a streak. None = the call declares no unit ANYWHERE -- neither on the row nor on
    its card (CYCLE-8 FIX 2(b), see `_registry_unit_class`) -- the agent lane and every legacy fixture,
    which must keep repairing.

    CYCLE-8 REVIEW (2026-08-08) MAJOR 6 adds the LAST fallback, `_metric_tell_class` -- the call's own metric
    NAME. The order is evidence-strength descending and each step is only reached when the one above it says
    nothing: the ROW is the served fact, the CARD is the table's declaration, the NAME is the call's own
    spelling. Only the first two need the registry, so the third keeps a class available when it is absent
    -- which is the whole of MAJOR 6."""
    if _COUNT_METRIC.search(str(((call or {}).get("query") or {}).get("metric") or "")):
        return "count"
    rows = (call or {}).get("rows") or []
    src = None
    for r in rows:
        try:
            if abs(float(str(r.get("value")).replace(",", "")) - val) <= 1e-9:
                src = r
                break
        except (TypeError, ValueError):
            continue
    row_unit = str((src if src is not None else (rows[0] if rows else {})).get("unit") or "")
    return _unit_class_lead(row_unit) or _registry_unit_class(call) or _metric_tell_class(call)


def _sentence_unit_class(masked: str, a: int, b: int) -> str | None:
    """The unit class governing the numeral at [a, b) of an already-handle-masked sentence: the token that
    FOLLOWS it ('+0.98 degC', '7.2%'), else the token that PRECEDES it (a currency prefix, '$4.20'). Read
    off the MASKED text so a trailing '[N3]' can never be mistaken for a unit."""
    m = re.match(r"\s*(\S+)", masked[b:])
    cls = _unit_class(m.group(1)) if m else None
    if cls is None:
        m = re.search(r"(\S+)\s*\Z", masked[:a])
        cls = _unit_class(m.group(1)) if m else None
    return cls


# CYCLE-8 FIX 2(a) -- THE SLOTS A REPAIR MAY NEVER WRITE INTO. `_num_repair` rewrites a NUMERAL, and it has
# only ever asked "is the rewrite unambiguous", never "is this position a VALUE at all". These three shapes
# are positions where a row value is a category error whatever the arithmetic says:
#   * a DURATION MODIFIER  ('5-year mean')      -- the numeral is a window length (gate-5 corruptions 1+2)
#   * an ORDINAL           ('85th percentile')  -- the numeral is a position
#   * 'N percent OF ...'   ('2 percent of the crop') -- the numeral is a share of a stated whole
# The claim extractor now exempts the first two (the cycle-8 amendment), so on the shipped path this fence
# is a SECOND lock on the same door: it holds under GRAPHRAG_CASCADE_QUANT/pool env variations, under any
# future extractor widening, and for the percent-of shape the extractor deliberately does NOT exempt.
# CYCLE-8 REVIEW (2026-08-08): the duration arm here is DELIBERATELY BROADER than the extractor's, and the
# asymmetry is the point. The extractor decides "is this numeral CHECKABLE" and must err toward CHARGING
# (BLOCKER 2: an over-exemption silently un-verifies the streak and recency lanes). This fence decides "may
# a row value be WRITTEN here" and errs toward REFUSING, because its failure mode is a corrupted sentence
# and its refusal mode is the fail-closed drop every other ambiguity already takes. So any duration noun
# glued to the numeral and continued by a word blocks the rewrite, whether or not the extractor read it as a
# window. HEAD POSITION IS STILL A VALUE SLOT: "the last 5 months [N11]" citing a pace_streak row has a
# handle, not a word, after the noun -- it does not match here and keeps repairing, as cycle-8 intended.
_NON_VALUE_SLOT = re.compile(r"\A(?:(?:st|nd|rd|th)\b|" + _DUR_SEP + _DURATION_NOUN + _DUR_SEP
                             + r"+[A-Za-z]|\s*(?:%|percent|pct)\s+of\b)", re.I)
# CYCLE-8 FIX 2(b), THE REGISTRY-INDEPENDENT HALF OF THE PERCENT FENCE. `_registry_unit_class` is the
# right instrument and it FAILS OPEN by design (no registry / unknown table -> repair as before), which
# would restore the palm corruption exactly. A PERCENT slot does not need the registry to be fenced: only
# a percent-DENOMINATED call may write into one, and a call declares that in its own METRIC NAME. This is
# `citations._PCT_METRIC_RX`, the metric-name arm of cycle-7's own `_percent_typed`, restated here so the
# fence holds with the registry absent. (`ending_stocks_mt_pct` still repairs a "-5.11%" slot; a bare
# `production_cpo_mt` never can, registry or no registry.)
_PCT_METRIC = re.compile(r"(?:\A|_)pct(?:_|\Z)|percent", re.I)
# CYCLE-8 REVIEW (2026-08-08), MAJOR 5 -- A CONDITIONAL THRESHOLD IS NOT A VALUE SLOT EITHER.
# The one repair that survived cycle-8 anywhere on the gates was itself a non-value-slot rewrite that FIX
# 2(a) does not describe. Gate-4 `dcw_gas_nitrogen_squeeze` shipped
#     "if this crosses above +1 sigma [N4]"   ->   "if this crosses above +0.195159 sigma [N4]"
# -- the numeral is a THRESHOLD the prose is reasoning ABOUT, and replacing it with the CURRENT LEVEL makes
# the sentence assert a falsehood ("if this crosses above the value it already has"). Every existing fence
# passed it: the unit classes agree (index into index), the pool held one value, the sentence held one
# numeral. It is the same category error FIX 2(a) exists to stop, one clause further along.
# THE TEST NEEDS BOTH HALVES and neither alone is sufficient. A CONDITIONAL/temporal-hypothetical marker
# anywhere in the sentence ("if", "once", "unless", "should", "when", "until", "were", "as soon as") AND a
# COMPARISON PREPOSITION immediately before the numeral ("above", "below", "past", "through", "beyond",
# "exceeds", "breaches", "crosses"). A bare comparison is ordinary description -- "the anomaly is above
# +0.98 degC [N3]" is a statement of fact whose numeral SHOULD be repairable -- and a bare conditional says
# nothing about the numeral's role. Requiring both keeps the fence on the shape that was measured.
# THE REFUSAL IS THE FAIL-CLOSED DROP, the same answer this function gives every ambiguity: a threshold
# sentence the verifier cannot certify leaves the page rather than leaving it rewritten into a falsehood.
_COND_CTX = re.compile(r"\b(?:if|once|unless|should|when|whenever|whether|until|till|were|assuming|"
                       r"provided|watch|trigger|triggers|threshold)\b", re.I)
_THRESHOLD_LEAD = re.compile(
    r"\b(?:above|below|under|over|past|through|beyond|exceeds?|exceeding|breaches?|breaching|"
    r"crosses?|crossing|crossed|hits?|hitting|reaches?|reaching|touches?|tops?|clears?)"
    r"\s+(?:the\s+|its\s+|a\s+)?[+\-]?\s*\Z", re.I)


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
    for m in _HANDLE.finditer(sent):
        if m.group("kind") != "N":
            continue
        j = int(m.group("idx"))
        if j == idx or not (1 <= j <= len(number_calls)):
            continue
        sib = number_calls[j - 1]
        if _num_matches([v], _mismatch_pool(sib, _row_vals(sib)), dec):
            return True
    return False


def _num_repair(sent: str, idx: int, number_calls: list[dict]) -> tuple[int, int, str] | None:
    """The UNAMBIGUOUS rewrite for a number_mismatch: sentence-relative (start, end, replacement) when the
    sentence carries EXACTLY ONE claim number AND the cited call's MISMATCH POOL holds exactly one value;
    None (-> the whole sentence goes) for every other shape, because a rewrite that has to GUESS which
    numeral belongs to which row is a second fabrication. The pool is the same one the CHARGE used
    (_mismatch_pool), so a window call showing one endpoint repairs to that endpoint even though it carries
    six member rows -- charging on `shown` and repairing from `rows` would splice in a figure the reader was
    never given. The value lands as a MAGNITUDE:
    _CLAIM_NUM cannot see a minus, so direction stays wherever the prose already put it.
    FOUR REFUSALS beyond ambiguity: (a) a scale word (million/billion/...) in the sentence means the prose
    numeral is denominated and the row value may not be -- splicing a raw row value next to 'million'
    manufactures a new figure, so the sentence goes instead; (b) the replacement must read as prose --
    a large integer lands comma-grouped, and any value {:g} would render in scientific notation is
    refused (an analyst note never says 8.85e+07); (c) a COUNT source (a pace_streak run length, unit
    'months'/'weeks'/'days') may never land anywhere but a count context -- r5 published "+5 degC" for a
    +0.98 degC ONI anomaly because the streak's shown value is 5 and nothing checked that 5 was a number of
    MONTHS; (d) more generally, when BOTH the row's unit and the numeral's prose unit are recognized and
    they disagree (a '%' delta row into a degC sentence, a tonnage into a price), the replacement is
    unit-foreign and is refused. Both unit refusals fall through to the fail-closed default: the sentence
    goes, which is the existing answer to every ambiguity. A call that declares NO unit -- the agent lane,
    every legacy fixture -- is unconstrained by (d) and repairs exactly as it did before.

    CYCLE-8 (2026-08-08) ADDS A FIFTH REFUSAL AND WIDENS (d):
      (e) NON-VALUE SLOT -- the numeral is glued to a duration-modifier / ordinal / percent-of shape, i.e.
          it is a window length, a position, or a share, and no row value belongs there. See
          `_NON_VALUE_SLOT` for the three gate-5 corruptions this closes.
      (d) now reads the CARD's declared unit when the row carries none (`_registry_unit_class`) -- the palm
          corruption spliced an MT tonnage into a percent slot through a row whose `unit` was null.
      (d2) a PERCENT slot may only be written by a percent-DENOMINATED call. (d) fails open without the
          registry; (d2) reads the call's own metric name and does not, so the palm class stays closed
          even where the card is unreadable. See `_PCT_METRIC`.

    THE CYCLE-8 REVIEW (2026-08-08) ADDS TWO MORE AND CLOSES A SCOPE HOLE:
      (f) CONDITIONAL THRESHOLD -- a numeral the prose is reasoning ABOUT ("if this crosses above +1 sigma")
          is not a value slot; overwriting it with the current level makes the sentence assert a falsehood.
          MAJOR 5, and it was live in the working tree. See `_COND_CTX` / `_THRESHOLD_LEAD`.
      (d) now also reads the metric NAME (`_metric_tell_class`) when neither the row nor the card declares a
          unit -- MAJOR 6, the registry-independent arm for every class, not just percent.
      AMBIGUITY IS DECIDED ON THE PRE-AMENDMENT EXTRACTOR (MAJOR 4). Removing a numeral from the extractor
          does not just de-charge it -- it changes how many claim numerals a sentence HAS, and that count is
          the input to the ambiguity refusal. So a family that used to be 2-span (refuse, drop the sentence)
          silently became 1-span (repair, REWRITE the sentence): `_num_repair("gas sits at a 5-year z-score
          of +1.24 sigma [N1]", ...)` returned None at HEAD and returned a rewrite of the reader's z-score
          under cycle-8. That is a scope breach -- the amendment was sanctioned as FALSE-POSITIVE REDUCTION
          IN CLAIM EXTRACTION ONLY, and it had UNLOCKED the repair path on the corpus's most common shape
          (`dcw_gas_nitrogen_squeeze` writes six "a 5-year z-score of X" sentences). The gate is now asked of
          `cycle8=False` spans, which is HEAD's own count, so no sentence becomes repairable that was not
          repairable before. The REWRITE still uses the cycle-8 span; when both views hold exactly one span
          they are by construction the same span (the cycle-8 set is a subset of HEAD's)."""
    if not (1 <= idx <= len(number_calls)):
        return None
    if _SCALE_WORD.search(sent):
        return None
    call = number_calls[idx - 1]
    vals = _mismatch_pool(call, _row_vals(call))
    masked = _mask_handles(sent)
    spans = _claim_number_spans(masked)
    if len(vals) != 1 or len(spans) != 1:
        return None
    if len(_claim_number_spans(masked, cycle8=False)) != 1:
        return None                                       # MAJOR 4: HEAD's ambiguity refusal, preserved
    if _NON_VALUE_SLOT.match(masked[spans[0][1]:]):
        return None                                       # (e) a window length / position / share slot
    if _THRESHOLD_LEAD.search(masked[:spans[0][0]]) and _COND_CTX.search(masked):
        return None                                       # (f) a threshold inside a conditional
    src_cls = _call_unit_class(call, vals[0])
    tgt_cls = _sentence_unit_class(masked, spans[0][0], spans[0][1])
    if src_cls == "count" and tgt_cls != "count":
        return None                                       # (c) a run length is not a magnitude
    if src_cls and tgt_cls and src_cls != tgt_cls:
        return None                                       # (d) unit-foreign replacement
    if tgt_cls == "pct" and src_cls != "pct" and not _PCT_METRIC.search(
            str(((call or {}).get("query") or {}).get("metric") or "")):
        return None                                       # (d2) only a percent CALL writes a percent slot
    av = abs(vals[0])
    repl = f"{av:g}"
    if "e" in repl or "E" in repl:
        if av == int(av):
            repl = f"{int(av):,}"
        else:
            return None
    return spans[0][0], spans[0][1], repl


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
                     foreign_names: set[str] | None = None) -> dict:
    """Verify + repair `structured` IN PLACE (tldr/mechanism prose, sources ledger); return the report.
    `foreign_names` = regime names that belong to OTHER contracts' DAGs (never routed here) — asserting
    one is the measured cross-contract fabrication class, so the token is stripped and counted.
    The report carries `resolved` ({ref -> the matched item's true metadata}) so the caller can render
    ONE validated source list numbered by the model's own handles (the dual-list mismatch inflated the
    judge's hallucination tally 37->151 while grounding/PIT rose).
    GRAPHRAG_VERIFY=off -> no-op. Never raises: verification must never break an answer."""
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

        # W4 A/B RCA (2026-07-31): a number_mismatch dropped the HANDLE only, so the fabricated FIGURE stayed
        # on the page -- now uncited, which reads as the analyst's own number (the judge scored 4 of these on
        # one row, e.g. "-0.72 degC [N12]" against rows of +0.06). Fail-closed by DEFAULT: rewrite the figure
        # from the cited row when that is unambiguous, else delete the whole sentence. =handle restores the
        # legacy handle-only strip byte for byte; ANY other value (absent included) is the new behaviour.
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
        for _m in _HANDLE.finditer(_prose_all):
            _kinds.setdefault(_m.group("idx"), set()).add(_m.group("kind") or "E")

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
            quoting: dict[tuple[int, int], list[tuple[int, int, list[dict], str | None]]] = {}
            for m in _HANDLE.finditer(text):
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
                             _check_evidence_handle(sent, resolved[ref], quotes=False)))
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
                if _unbacked_quote(sent, [p for _a, _b, p, _r in group]) is not None:
                    for h0, h1, _p, _r in group:
                        drops.append((h0, h1))
                    report["stripped"] += 1
                    report["by_rule"]["quote_mismatch"] = report["by_rule"].get("quote_mismatch", 0) + 1
                    _audit("quote_mismatch", field, sent)
                    continue
                for h0, h1, _p, rule in group:
                    if rule:
                        drops.append((h0, h1))
                        report["stripped"] += 1
                        report["by_rule"][rule] = report["by_rule"].get(rule, 0) + 1
                        _audit(rule, field, sent)

            if foreign:                                   # a regime name from ANOTHER contract's DAG is a
                for m in foreign.finditer(text):          # cross-contract fabrication, never a citation issue
                    drops.append((m.start(), m.end()))
                    report["stripped"] += 1
                    report["by_rule"]["foreign_regime_name"] = report["by_rule"].get("foreign_regime_name", 0) + 1
                    _audit("foreign_regime_name", field, _sentence_at(text, m.start()))

            # PASS 2 -- resolve the deferred mismatches. THREE outcomes per offending handle:
            #   * SIBLING-BACKED (r5 RCA): another [N] in the sentence materializes the lone numeral, so the
            #     figure is not a fabrication and only the mis-citing HANDLE goes -- the pre-fix remedy,
            #     correctly scoped at last. Decided FIRST, and it also forbids the rewrite: leaving the
            #     numeral alone is the whole point, so the sentence is never also an edit site.
            #   * REPAIRABLE: every mismatched handle in the sentence agrees on the same one-numeral/one-row
            #     rewrite (and it survives the unit guard) -- the figure is rewritten, the handles stay.
            #   * KILLED: anything else. One killed handle kills the sentence for all of them (the drop wins
            #     over any repair inside it).
            per_sent: dict[tuple[int, int], dict[tuple[int, int], str]] = {}
            killed: set[tuple[int, int]] = set()
            backed: list[tuple[int, int, int, int, str]] = []
            for h0, h1, s0, s1, sent, idx in pending:
                if _sibling_backed(sent, idx, number_calls):
                    backed.append((h0, h1, s0, s1, sent))
                    continue
                rep = _num_repair(sent, idx, number_calls)
                slot = per_sent.setdefault((s0, s1), {})
                if rep is None or slot.get((s0 + rep[0], s0 + rep[1]), rep[2]) != rep[2]:
                    killed.add((s0, s1))
                else:
                    slot[(s0 + rep[0], s0 + rep[1])] = rep[2]
            for _h0, _h1, s0, s1, _sent in backed:        # a corroborated numeral is never rewritten
                per_sent.pop((s0, s1), None)
            edits: dict[tuple[int, int], str] = {}
            for span, slot in per_sent.items():
                if span not in killed:
                    edits.update(slot)
            for h0, h1, s0, s1, sent, _idx in pending:    # counted per OFFENDING handle, as every rule is
                if (s0, s1) in killed:
                    drops.append(_drop_span(text, s0, s1))
                    report["stripped"] += 1
                    report["by_rule"]["number_mismatch"] = report["by_rule"].get("number_mismatch", 0) + 1
                    _audit("number_mismatch", field, sent)
                elif any(b[0] == h0 and b[1] == h1 for b in backed):
                    drops.append((h0, h1))                # the FIGURE stands (a sibling backs it); the
                    report["stripped"] += 1               # mis-citation alone is removed
                    report["by_rule"]["number_mismatch"] = report["by_rule"].get("number_mismatch", 0) + 1
                    _audit("number_mismatch", field, sent)
                else:                                     # the handle SURVIVES -- it now points at its row
                    # CYCLE-8 FIX 2(c) -- NO LAUNDERING. A repair MUTATES THE READER'S PROSE, and until now
                    # the only trace of that was `corrected` (shared with ledger-date fixes) plus a by_rule
                    # key. `stripped` stayed 0, so gate-5's `dcw_palm_stocks_print` -- which shipped
                    # "roughly 1,629,801 percent below the five-year average" -- scored a CLEAN row: the
                    # repair laundered the defect out of the score it was supposed to appear in.
                    # `repaired` is the count and `repairs` the always-present, never-gated record. It
                    # carries NUMERALS ONLY (the before/after token), never prose: the strip_audit gate
                    # exists because raw draft text must not ride an unconditional report key, and a bare
                    # numeral is already on the reader's page. `stripped` and `strip_rate` are deliberately
                    # NOT redefined -- that is the frozen cross-run instrument -- so the honest reading is
                    # "strips AND repairs", which is what `eval.verifier_panel` now prints.
                    # THE TWO COUNT DIFFERENT THINGS ON PURPOSE: `repaired` counts OFFENDING HANDLES that
                    # survived (per-handle, exactly as every rule above counts), `repairs` lists DISTINCT
                    # prose mutations (two handles agreeing on one rewrite are one edit to the reader).
                    report["repaired"] += 1
                    report["corrected"] += 1
                    report["by_rule"]["number_mismatch_repaired"] = \
                        report["by_rule"].get("number_mismatch_repaired", 0) + 1
                    _audit("number_mismatch_repaired", field, sent)

            # PASS 3 -- apply. Coalesce the drops first so a sentence span ABSORBS the handle spans inside it
            # (no double-drop, no corrupted slice), then rewrite in reverse position order.
            spans = _coalesce(drops)
            ops = [(a, b, "") for a, b in spans]
            ops += [(a, b, v) for (a, b), v in edits.items()
                    if not any(x < b and a < y for x, y in spans)]
            # CYCLE-8 FIX 2(c): ONE record per DISTINCT prose mutation the reader actually receives --
            # emitted from the APPLIED ops (an edit swallowed by a drop span never reaches the page and is
            # not a repair), and BEFORE the rewrite loop, so `text[a:b]` is still the numeral as written.
            for a, b, v in sorted(ops):
                if v != "":
                    report["repairs"].append({"field": field, "rule": "number_mismatch_repaired",
                                              "from": text[a:b], "to": v})
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
            # FIX-CYCLE-2 (major 7): the seam is recorded as a NORMALIZED 40-char KEY and the SERIALIZED
            # copy is gated on GRAPHRAG_STRIP_AUDIT, the same gate `strip_audit` uses for the same reason.
            # The tidy pass reads the internal `report.strip_seams` carrier, which is always populated and
            # which nothing downstream can serialize. See `_VerifyReport` / `_seam_key` above.
            _shift = 0
            for a, b, v in sorted(ops):
                _pos = a + _shift
                _shift += len(v) - (b - a)
                if v == "":
                    _seam = {"field": field, "key": _seam_key(text[_pos:_pos + _SEAM_LOOKAHEAD])}
                    report.strip_seams.append(_seam)
                    if _audit_on:
                        report.setdefault("strip_seams", []).append(_seam)
            return re.sub(r" +([.,;])", r"\1", re.sub(r"  +", " ", text))

        for fld in ("tldr", "mechanism"):
            if structured.get(fld):
                structured[fld] = _verify_field(structured[fld], fld)
    except Exception:  # noqa: BLE001 — a verifier bug must never eat an answer
        report["error"] = True
    return report
