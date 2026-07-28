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
that merely mistype a real item are corrected in place.
"""
from __future__ import annotations

import os
import re

# The optional trailing letter consumes model-minted variants like [E1b]: unmatched they LEAK to the
# reader as literal text (Stage-1 RCA q7); matched they resolve by idx and strip like any other handle.
_HANDLE = re.compile(r"\[(?P<kind>[NE]?)(?P<idx>\d+)(?:[a-z])?\]")
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


def _claim_numbers_in(s: str) -> list[float]:
    """Magnitudes only. EXEMPT (never a claim): (a) a bare 4-digit calendar year 1900-2099 with no
    decimal/comma ('2,021' and '2010.5' keep their punctuation and stay magnitudes) -- UNLESS a unit
    token follows ('exports hit 1950 MMT' IS a claim); (b) the 1-2 digit tail of a YEAR
    range ('1998-99' -> the '99'); (c) any digit run immediately preceded by a letter (B40, T2, MY2021,
    CO2), handled by _CLAIM_NUM's lookbehind; (d) the 1-2 digit DAY of a date, ISO ('2026-05-30') or
    long-form on either side of the month name ('25 July 2026', 'July 25, 2026'). A fabricated magnitude
    ('23.5 MMT' with no such row) is untouched by all four rules and still strips."""
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
        out.append(v)
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
    row_vals = []
    for r in (number_calls[idx - 1].get("rows") or []):
        try:
            row_vals.append(float(str(r.get("value")).replace(",", "")))
        except (TypeError, ValueError):
            continue
    sent_nums = _claim_numbers_in(_HANDLE.sub("", sent))         # time/name tokens are NOT claims
    if sent_nums and row_vals and not _num_matches(sent_nums, row_vals):
        return "number_mismatch"
    # P9-B all-numbers guard: EVERY magnitude in a handled sentence (years/range-tails/letter-codes exempt
    # at the extractor) must match SOME injected row across the merged calls -- else "rose to 5900 [N3],
    # up 18%" lets 18 ride UNVERIFIED. Reads ONLY GRAPHRAG_CASCADE_QUANT (the single feature flag): =off
    # fully reverts the stricter verifier.
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

        def _sentence_at(text: str, pos: int) -> str:
            start = 0
            end = len(text)
            for b in _BOUND.finditer(text):
                if b.start() < pos:
                    start = b.end()
                elif b.start() >= pos:
                    end = b.end()
                    break
            return text[start:end]

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
            drops: list[tuple[int, int]] = []
            for m in _HANDLE.finditer(text):
                report["checked"] += 1
                sent = _sentence_at(text, m.start())
                if m.group("kind") == "N":
                    rule = _check_number_handle(sent, int(m.group("idx")), number_calls)
                else:
                    ref = m.group("idx")
                    if ref in resolved:
                        rule = _check_evidence_handle(sent, resolved[ref])
                    else:                                 # handle never declared in the ledger: keep it only
                        rule = ("undeclared_unsupported"  # if SOME provided item supports the sentence
                                if _check_evidence_handle(sent, evidence) else None)
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
            for a, b in sorted(set(drops), reverse=True):
                text = text[:a] + text[b:]
            return re.sub(r" +([.,;])", r"\1", re.sub(r"  +", " ", text))

        for fld in ("tldr", "mechanism"):
            if structured.get(fld):
                structured[fld] = _verify_field(structured[fld], fld)
    except Exception:  # noqa: BLE001 — a verifier bug must never eat an answer
        report["error"] = True
    return report
