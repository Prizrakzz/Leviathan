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


def _claim_number_spans(s: str) -> list[tuple[int, int, float]]:
    """(start, end, value) per claim magnitude, positions into `s`. EXEMPT (never a claim): (a) a bare
    4-digit calendar year 1900-2099 with no decimal/comma ('2,021' and '2010.5' keep their punctuation and
    stay magnitudes) -- UNLESS a unit token follows ('exports hit 1950 MMT' IS a claim); (b) the 1-2 digit
    tail of a YEAR range ('1998-99' -> the '99'); (c) any digit run immediately preceded by a letter (B40,
    T2, MY2021, CO2), handled by _CLAIM_NUM's lookbehind; (d) the 1-2 digit DAY of a date, ISO
    ('2026-05-30') or long-form on either side of the month name ('25 July 2026', 'July 25, 2026'). A
    fabricated magnitude ('23.5 MMT' with no such row) is untouched by all four rules and still strips.
    The span ENDS at the token core, so the sentence punctuation _CLAIM_NUM sweeps up is never part of it
    (a repair rewrites the numeral, never the full stop after it)."""
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


def _unit_class(tok: str) -> str | None:
    """The unit CLASS of one prose/row token, or None when it is not a unit this guard recognizes. The
    degree sign is stripped so a draft's 'degC' and its '°C' twin land on the same class -- the r5 drafts
    write both, and the guard must not depend on which one the model reached for."""
    t = (tok or "").strip().strip(".,;:!?()[]'\"").replace("°", "").lower()
    return _UNIT_OF.get(t) if t else None


def _call_unit_class(call: dict, val: float) -> str | None:
    """The unit class the cited call would splice IN: the unit of the row carrying the repair value (a
    synthetic delta/pace record has exactly one row; a windowed level record is matched by value), plus the
    metric-suffix tell for a streak. None = the call declares no unit -- the agent lane and every legacy
    fixture, which must keep repairing."""
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
    return _unit_class(str((src if src is not None else (rows[0] if rows else {})).get("unit") or ""))


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
    spans = _claim_number_spans(_mask_handles(sent))
    if len(spans) != 1:
        return False
    v = spans[0][2]
    for m in _HANDLE.finditer(sent):
        if m.group("kind") != "N":
            continue
        j = int(m.group("idx"))
        if j == idx or not (1 <= j <= len(number_calls)):
            continue
        sib = number_calls[j - 1]
        if _num_matches([v], _mismatch_pool(sib, _row_vals(sib))):
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
    every legacy fixture -- is unconstrained by (d) and repairs exactly as it did before."""
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
    src_cls = _call_unit_class(call, vals[0])
    tgt_cls = _sentence_unit_class(masked, spans[0][0], spans[0][1])
    if src_cls == "count" and tgt_cls != "count":
        return None                                       # (c) a run length is not a magnitude
    if src_cls and tgt_cls and src_cls != tgt_cls:
        return None                                       # (d) unit-foreign replacement
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


def _num_matches(sent_nums: list[float], row_vals: list[float]) -> bool:
    """'31.4 million' vs 31400000, '36.4%' vs 0.3636: equal within 1% at any common reporting scale.
    MAGNITUDE-insensitive to sign: _NUM cannot extract a minus from prose ('fell 5.058 MMT' reads 5.058)
    while injected delta/pct rows are SIGNED (-5.058) -- direction lives in the prose verb, magnitude
    backing is this check's job (Stage-1 RCA: every narrated DECLINE stripped deterministically)."""
    for a0 in sent_nums:
        a = abs(a0)
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
    return False


def _check_evidence_handle(sent: str, matched: list[dict]) -> str | None:
    """Rule violated by an evidence handle in this sentence, or None."""
    if not matched:
        return "fabricated_citation"                      # ledger names a source/date nobody provided
    texts = " ".join(e.get("text") or "" for e in matched)
    for q in _QUOTE.findall(sent):
        if _norm(q) not in _norm(texts):
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


def _num_backed(v: float, allv: list[float], tol: float = 0.01) -> bool:
    """P9-B (R4): SCALE-1 exact-ish match only. Injected cascade rows are PRE-SCALED to narrate_unit, so a
    hallucinated ~40% must NOT be back-filled by a raw 0.4 ratio or a 4e7 tonnage that _num_matches'
    multi-scale set would bridge -- that bridging is the exact mis-attribution hole the pre-scale normalizer
    closes. Compare at scale 1 within a tight tolerance; 0 matches only 0. MAGNITUDE-insensitive to sign:
    prose numbers arrive unsigned (_NUM has no minus) while delta/pct rows are signed -- the Stage-1 RCA
    showed every narrated decline stripping while identical gains passed."""
    va = abs(v)
    for r in allv:
        ra = abs(r)
        if ra == 0:
            if va == 0:
                return True
        elif abs(va - ra) <= tol * ra:
            return True
    return False


def _check_number_handle(sent: str, idx: int, number_calls: list[dict]) -> str | None:
    if not (1 <= idx <= len(number_calls)):
        return "index_out_of_range"
    row_vals = _row_vals(number_calls[idx - 1])
    # the HEADLINE check runs against what the cited LINE printed (`shown`), not the whole window it fetched
    pool = _mismatch_pool(number_calls[idx - 1], row_vals)
    sent_nums = _claim_numbers_in(_HANDLE.sub("", sent))         # time/name tokens are NOT claims
    if sent_nums and pool and not _num_matches(sent_nums, pool):
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
        guard_nums = _claim_numbers_in(_HANDLE.sub("", sent))     # exemptions live in the extractor now
        # backed = scale-1 match vs ANY row (pre-scaled cascade rows), OR the legacy scale-bridge vs the
        # sentence's OWN cited row (a '31.4 million MT' narration of its own raw-MT hybrid row is legitimate;
        # CROSS-row multi-scale backfill stays forbidden -- that is the R4 mis-attribution hole).
        if guard_nums and allv and any(
                not (_num_backed(v, allv) or (row_vals and _num_matches([v], row_vals)))
                for v in guard_nums):
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
    report = {"enabled": True, "checked": 0, "stripped": 0, "corrected": 0, "claim_count": 0,
              "by_rule": {}, "resolved": {}}
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
            for m in _HANDLE.finditer(text):
                report["checked"] += 1
                s0, s1 = _sentence_span(text, m.start())
                sent = text[s0:s1]
                if m.group("kind") == "N":
                    rule = _check_number_handle(sent, int(m.group("idx")), number_calls)
                else:
                    ref = m.group("idx")
                    if ref in resolved:
                        rule = _check_evidence_handle(sent, resolved[ref])
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
            for a, b, v in sorted(ops, reverse=True):
                text = text[:a] + v + text[b:]
            return re.sub(r" +([.,;])", r"\1", re.sub(r"  +", " ", text))

        for fld in ("tldr", "mechanism"):
            if structured.get(fld):
                structured[fld] = _verify_field(structured[fld], fld)
    except Exception:  # noqa: BLE001 — a verifier bug must never eat an answer
        report["error"] = True
    return report
