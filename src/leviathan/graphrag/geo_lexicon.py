"""THE GEO LEXICON (D-HP-25, plan 10.30.3(vii)) -- the ONE vocabulary the binding verifier's geography
axis is built on, and the ONLY place a country surface form is spelled.

WHY IT LIVES IN ``src/`` AND NOT IN ``configs/``, WHICH IS A LANDMINE THIS ESTATE HAS ALREADY STEPPED ON.
``configs/graphrag/`` is GITIGNORED; a worktree-built image does not carry it. A lexicon that loaded from
there would import EMPTY inside a worker image and the verifier would silently compare nothing -- a
detector that fires zero times and a detector that is switched off are indistinguishable from any
artifact. In ``src/`` it BAKES INTO EVERY IMAGE, so "the comparator had no vocabulary" is not a state
this module can be in.

LEAF MODULE, BY THE ``response_contracts.py`` DISCIPLINE: no ``leviathan`` imports, no I/O at import time
except the OPTIONAL developer lint below, and nothing here reads the environment. Two consumers
(``answer._handle_geo_phrase`` on the claim side, ``answer._receipt_geo_text`` and the ``[E]``
containment pass on the receipt side) must never be able to disagree about what "France" is, which is why
there is exactly one table and exactly one matcher.

THE FOUR FAIL-OPEN LAWS ARE ENFORCED HERE, NOT AT THE CALL SITES (plan 10.30.3(vi)). A geo verifier's
failure mode is NOT missing a swap -- it is DELETING A CORRECT SENTENCE -- so every guard in this file
resolves toward NOT MINTING A TOKEN:

  L1  AGGREGATE SENTINELS. ``world / global / worldwide / total / international / all origins`` (and
      ``European Union`` when no member state is named beside it -- that half is the caller's, because
      only the caller knows what else the clause owns) force the comparison OFF on EITHER side. An
      aggregate is a CONTAINER, and a container disagreeing with its contents is not a disagreement.
  L2  ANCESTOR CLOSURE, ADDITIVE ONLY. ``canon_closure`` ADDS ancestors and never REPLACES:
      ``{france} -> {france, european_union}``. A REPLACING fold is forbidden and the reason is
      ``numbers/cascade.py:529``'s ``_PSD_COUNTRY_FOLD`` (``{"France": "European Union",
      "Cote Divoire": "Cote d'Ivoire"}``): applied as a replacement it turns a France claim into an EU
      claim and then convicts it against a France receipt. Applied ADDITIVELY it can only ever make the
      two sides intersect, which is the only direction a deletion-armed check may be tuned in.
  L3  MULTI-GEO DECLINE. Enforced by the CALLER (it owns the window), but this module makes it
      computable: ``extract_geos`` returns EVERY token with its span, so "does this window name more
      than one country" is a read rather than an inference.
  L4  NOT-A-SCOPE FORMS, all four of them here:
      (a) WORD-BOUNDARY MATCHING ONLY, the ``harvest.build_matcher`` idiom (accent-insensitive,
          case-insensitive, longest-first alternation). NO SUBSTRING HITS, EVER.
      (b) A surface followed by a CURRENCY / HOLIDAY / INSTRUMENT noun mints NO token -- the
          "Brazilian real" and "Chinese New Year" classes.
      (c) HOMONYMS ARE DROPPED, NOT GUESSED: ``turkey`` the bird (the decision is
          ``numbers/agent.py:96``'s and is REUSED here rather than re-derived), ``chile`` the pepper.
      (d) ANY SURFACE MAPPING TO MORE THAN ONE CANONICAL SLUG IS DROPPED. Ambiguity resolves to
          SILENCE. This is computed at import time over the table below, so a later edit that
          introduces a collision disarms that surface automatically instead of guessing.

THE DECOY SET is (a) and (d) meeting: ``south american`` contains ``american`` and would otherwise mint
``united_states`` on every South American crop sentence in the corpus, and ``gulf of mexico`` is a US
shipping region, not Mexico. Decoys ride the SAME longest-first alternation, so they WIN the span and
emit nothing -- which is the only construction that actually suppresses the shorter surface inside them.

BARE ``us`` IS DELIBERATELY ABSENT from ``united_states``' surfaces and it is recorded here rather than
left to be re-discovered: matching is case-INSENSITIVE, so ``us`` the pronoun ("told us", "gives us")
would mint the United States on ordinary prose. ``u.s.``, ``u.s``, ``usa``, ``u.s.a.``,
``united states`` and ``american`` carry the country; the two-letter form is refused.
"""

from __future__ import annotations

import functools
import os
import re
import unicodedata

# ══ THE TABLE ═════════════════════════════════════════════════════════════════════════════════════════
# 34 CANONICAL COUNTRIES: the 33 country slugs actually present under `configs/geographies/` (verified by
# the import-time lint below), PLUS `russia`, which the region files do not carry and which the wheat and
# vegoil corpora certainly do.
#
# NAME SURFACES + ADJECTIVALS, seeded from `numbers/agent.py`'s `_ESR_DESTINATIONS` demonym column (the
# shipped, already-measured vocabulary) and completed BY HAND for the 11 slugs that column does not
# reach. THE 11 HAND-ADDED ADJECTIVALS ARE ENUMERATED IN THE PLAN (10.30.3(vii)) SO THE ADDITION IS
# AUDITABLE RATHER THAN INCIDENTAL, and they are exactly:
#   cameroonian, ivorian/ivoirian, ecuadorian/ecuadorean, ethiopian, french, ghanaian, hungarian,
#   paraguayan, polish, romanian, ugandan.
# `polish` IS KNOWN-RISKY and is kept anyway, with its risk recorded: it is also an English verb ("polish
# the numbers"). It survives because a claim-side false token cannot convict on its own -- the receipt
# must POSITIVELY name a different country (V1's both-sides rule, V2's clause (c)) -- and because
# dropping a slug the plan enumerates would be a silent narrowing of a pre-registered vocabulary.
_COUNTRIES: dict[str, dict[str, object]] = {
    "argentina":     {"display": "Argentina",
                      "names": ["argentina"], "adjectivals": ["argentine", "argentinian"]},
    "australia":     {"display": "Australia",
                      "names": ["australia"], "adjectivals": ["australian"]},
    "brazil":        {"display": "Brazil",
                      "names": ["brazil"], "adjectivals": ["brazilian"]},
    "cameroon":      {"display": "Cameroon",
                      "names": ["cameroon"], "adjectivals": ["cameroonian"]},
    "canada":        {"display": "Canada",
                      "names": ["canada"], "adjectivals": ["canadian"]},
    "china":         {"display": "China",
                      "names": ["china"], "adjectivals": ["chinese"]},
    "colombia":      {"display": "Colombia",
                      "names": ["colombia"], "adjectivals": ["colombian"]},
    "cote_divoire":  {"display": "Cote d'Ivoire",
                      "names": ["cote d'ivoire", "cote divoire", "ivory coast"],
                      "adjectivals": ["ivorian", "ivoirian"]},
    "ecuador":       {"display": "Ecuador",
                      "names": ["ecuador"], "adjectivals": ["ecuadorian", "ecuadorean"]},
    "ethiopia":      {"display": "Ethiopia",
                      "names": ["ethiopia"], "adjectivals": ["ethiopian"]},
    "european_union": {"display": "European Union",
                       "names": ["european union", "the european union", "eu"],
                       "adjectivals": ["european"]},
    "france":        {"display": "France",
                      "names": ["france"], "adjectivals": ["french"]},
    "germany":       {"display": "Germany",
                      "names": ["germany"], "adjectivals": ["german"]},
    "ghana":         {"display": "Ghana",
                      "names": ["ghana"], "adjectivals": ["ghanaian"]},
    "honduras":      {"display": "Honduras",
                      "names": ["honduras"], "adjectivals": ["honduran"]},
    "hungary":       {"display": "Hungary",
                      "names": ["hungary"], "adjectivals": ["hungarian"]},
    "india":         {"display": "India",
                      "names": ["india"], "adjectivals": ["indian"]},
    "indonesia":     {"display": "Indonesia",
                      "names": ["indonesia"], "adjectivals": ["indonesian"]},
    "italy":         {"display": "Italy",
                      "names": ["italy"], "adjectivals": ["italian"]},
    "malaysia":      {"display": "Malaysia",
                      "names": ["malaysia"], "adjectivals": ["malaysian"]},
    "mexico":        {"display": "Mexico",
                      "names": ["mexico"], "adjectivals": ["mexican"]},
    "nigeria":       {"display": "Nigeria",
                      "names": ["nigeria"], "adjectivals": ["nigerian"]},
    "pakistan":      {"display": "Pakistan",
                      "names": ["pakistan"], "adjectivals": ["pakistani"]},
    "paraguay":      {"display": "Paraguay",
                      "names": ["paraguay"], "adjectivals": ["paraguayan"]},
    "peru":          {"display": "Peru",
                      "names": ["peru"], "adjectivals": ["peruvian"]},
    "poland":        {"display": "Poland",
                      "names": ["poland"], "adjectivals": ["polish"]},
    "romania":       {"display": "Romania",
                      "names": ["romania"], "adjectivals": ["romanian"]},
    "russia":        {"display": "Russia",
                      "names": ["russia", "russian federation"], "adjectivals": ["russian"]},
    "south_africa":  {"display": "South Africa",
                      "names": ["south africa"], "adjectivals": ["south african"]},
    "thailand":      {"display": "Thailand",
                      "names": ["thailand"], "adjectivals": ["thai"]},
    "uganda":        {"display": "Uganda",
                      "names": ["uganda"], "adjectivals": ["ugandan"]},
    "ukraine":       {"display": "Ukraine",
                      "names": ["ukraine"], "adjectivals": ["ukrainian"]},
    "united_states": {"display": "United States",
                      "names": ["united states", "the united states",
                                "united states of america", "usa", "u.s.a.", "u.s.", "u.s"],
                      "adjectivals": ["american"]},
    "vietnam":       {"display": "Vietnam",
                      "names": ["vietnam", "viet nam"], "adjectivals": ["vietnamese"]},
}

EU_SLUG: str = "european_union"

# ══ L2 -- THE ADDITIVE FOLD, AND IT IS ADDITIVE OR IT IS A DEFECT ═════════════════════════════════════
# `numbers/cascade.py:529`'s `_PSD_COUNTRY_FOLD` has TWO entries and they are two DIFFERENT kinds of fact:
#   * "France" -> "European Union" is an ANCESTOR (PSD reports France inside the EU aggregate), so it
#     becomes a CLOSURE edge: `canon_closure("france") == {"france", "european_union"}`.
#   * "Cote Divoire" -> "Cote d'Ivoire" is a SPELLING, so it is a SURFACE alias above and NOT a closure
#     edge -- both spellings already resolve to the one slug `cote_divoire`.
# `united_states` <-> the spelled-out forms is likewise a SURFACE fact, not a closure edge, and it lives
# in the table above with the bare-`us` refusal recorded at the module docstring.
# WHAT IS DELIBERATELY *NOT* HERE, RECORDED SO IT IS A DECISION AND NOT AN OVERSIGHT: the OTHER five EU
# member states in the table (germany, italy, poland, romania, hungary) get NO `european_union` ancestor,
# because the plan enumerates the fold as `_PSD_COUNTRY_FOLD`'s entries and widening a pre-registered
# vocabulary mid-build is the class of edit this wave refuses. The case it would cover is already covered
# by L1 from the other side: an `European Union` receipt with no member state beside it is an AGGREGATE
# and never compares at all. Recorded as a residual at plan 10.30.11.
_ANCESTORS: dict[str, frozenset[str]] = {
    "france": frozenset({"european_union"}),
}

# ══ L1 -- THE AGGREGATE SENTINELS ═════════════════════════════════════════════════════════════════════
# A container is not a disagreement with its contents. Present on EITHER side -> the comparison is OFF.
# `european_union` is NOT in this set as a WORD: it is a real country-level slug on the ESR/PSD tables and
# its aggregate reading is CONDITIONAL ("when the clause names no member state"), which only the caller
# can evaluate -- see `answer._handle_geo_phrase` and `answer._receipt_geo_text`, which both apply it.
AGGREGATE_SENTINELS: frozenset[str] = frozenset({
    "world", "global", "worldwide", "total", "international", "all origins",
})

# ══ L4(b) -- THE NOT-A-SCOPE FOLLOWER BLACKLIST ═══════════════════════════════════════════════════════
# A surface followed by one of these mints NO token. Currencies ("the Brazilian real", "the Malaysian
# ringgit", "U.S. dollars per bushel"), holidays ("Chinese New Year") and instruments ("German government
# bonds") are not geographies of a FACT -- they are the units, calendars and instruments a fact is quoted
# in. Suppressing them costs coverage and buys silence, which is the trade this whole module is tuned for.
# Entries may be one or two words; both lengths are tested at the match's right edge.
_FOLLOWER_BLACKLIST: frozenset[str] = frozenset({
    # currency
    "real", "reais", "peso", "pesos", "ringgit", "rupee", "rupees", "rupiah", "yuan", "renminbi",
    "rand", "hryvnia", "zloty", "forint", "leu", "lei", "naira", "cedi", "birr", "baht", "dong",
    "sol", "soles", "euro", "euros", "dollar", "dollars", "franc", "francs", "lira", "ruble",
    "rouble", "rubles", "roubles", "currency", "cent", "cents",
    # holiday / calendar
    "new year", "golden week", "independence day", "national day", "holiday", "holidays",
    # instrument / market plumbing
    "government bond", "government bonds", "bond", "bonds", "treasury", "treasuries", "yield",
    "yields", "central bank", "stock exchange", "exchange rate",
})

# ══ L4(a)+(d) -- THE DECOYS ═══════════════════════════════════════════════════════════════════════════
# Surfaces that CONTAIN a country surface and are NOT that country. They ride the same longest-first
# alternation, WIN the span, and emit nothing -- which is the only construction that actually suppresses
# the shorter form inside them (a post-hoc "was it preceded by 'south'" test is a second grammar, and two
# grammars for one question is how a guard drifts).
# `turkey` and `chile` are here as L4(c): the homonym decision is `numbers/agent.py:96`'s and is REUSED,
# not re-derived. Neither is a slug in the table today, so these two entries are a FENCE AGAINST A FUTURE
# ADDITION rather than a live suppression -- and the unit suite pins them so the fence cannot rot.
_DECOY_SURFACES: frozenset[str] = frozenset({
    "south american", "north american", "latin american", "central american",
    "gulf of mexico", "indian ocean", "south china sea", "indian summer",
    "turkey", "turkeys", "chile", "chiles", "chilli", "chilis",
})


# ══ THE MATCHER -- SELF-CONTAINED, THE `harvest.build_matcher` IDIOM ══════════════════════════════════
# `harvest._Matcher` normalizes the TEXT as well as the forms, which destroys offsets -- and this module's
# whole contract is offsets (the caller's window arithmetic is character-exact). So the normalization here
# is LENGTH-PRESERVING BY CONSTRUCTION: every character maps to exactly one character, so a match position
# in the normalized string is the same position in the original. Accent folding, case folding and the
# curly-apostrophe fold all satisfy that; nothing that changes length is allowed in.
_APOSTROPHES = {"’": "'", "‘": "'", "ʼ": "'", "´": "'", "`": "'"}


def _norm_char(ch: str) -> str:
    """ONE character -> ONE character, accent- and case-folded. Length-preserving is the whole point."""
    if ch in _APOSTROPHES:
        return _APOSTROPHES[ch]
    d = unicodedata.normalize("NFKD", ch)
    base = "".join(c for c in d if not unicodedata.combining(c))
    ch2 = base[0] if base else ch
    low = ch2.lower()
    ch2 = low[0] if low else ch2
    if ch2 in "_- ‐‑‒–—":
        return " "
    return ch2


@functools.lru_cache(maxsize=512)
def normalize(text: str) -> str:
    """The scanned form of `text`, SAME LENGTH, so every offset below is an offset into the original.

    CACHED, BOUNDED, AND THE REASON IS THE `[E]` PASS: V2 scans a receipt's FULL STORED TEXT twice per
    candidate (once for the aggregate sentinels, once for the country surfaces) and this normalizer is
    per-character Python. The cache is a pure function of its input, so it changes no answer -- it only
    stops one evidence chunk being walked character-by-character four times in a turn. `maxsize` is small
    on purpose: this holds evidence bodies, and an unbounded cache in a long-lived serving process is a
    leak wearing a performance argument."""
    return "".join(_norm_char(c) for c in (text or ""))


def _surface_rx_body(surface: str) -> str:
    """One surface as a regex fragment: escaped, with every internal space widened to `\\s+` so a corpus
    newline or a double space inside 'united states' cannot hide the match."""
    return r"\s+".join(re.escape(p) for p in surface.split(" ") if p)


def _build() -> tuple[dict[str, str], frozenset[str], re.Pattern | None]:
    """Build the surface -> slug index, the DROPPED-as-ambiguous set (L4(d)), and the one matcher.

    AMBIGUITY IS COMPUTED, NEVER ASSUMED: a surface reached from two slugs is removed from the index and
    recorded, so a later edit to the table cannot introduce a silent guess."""
    seen: dict[str, set[str]] = {}
    for slug, entry in _COUNTRIES.items():
        for surface in list(entry["names"]) + list(entry["adjectivals"]):    # type: ignore[arg-type]
            nf = normalize(surface).strip()
            if len(nf) <= 1:
                continue
            seen.setdefault(nf, set()).add(slug)
    dropped = {nf for nf, slugs in seen.items() if len(slugs) > 1}
    index = {nf: next(iter(slugs)) for nf, slugs in seen.items() if len(slugs) == 1}
    decoys = {normalize(d).strip() for d in _DECOY_SURFACES}
    decoys |= dropped                              # an ambiguous surface is consumed and emits nothing
    for nf in decoys:
        index.pop(nf, None)
    keys = sorted(set(index) | decoys, key=len, reverse=True)   # LONGEST-FIRST: 'south african' > 'south
    if not keys:                                                # africa'; 'south american' > 'american'
        return index, frozenset(dropped), None
    body = "|".join(_surface_rx_body(k) for k in keys)
    # WORD-BOUNDARY, spelled as explicit look-arounds rather than `\b`: several surfaces END in '.'
    # ('u.s.'), and `\b` after a period is a boundary that does not exist. This form is exact on both.
    rx = re.compile(r"(?<![a-z0-9])(?:" + body + r")(?![a-z0-9])")
    return index, frozenset(dropped), rx


_SURFACE_TO_SLUG, AMBIGUOUS_SURFACES, _MATCH_RX = _build()

_SENTINEL_RX = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(_surface_rx_body(normalize(s).strip())
                                   for s in sorted(AGGREGATE_SENTINELS, key=len, reverse=True))
    + r")(?![a-z0-9])")

_FOLLOWER_MAX_WORDS = 2
_POSSESSIVE_RX = re.compile(r"^(?:'s|s')?\s*")
_WORD_RX = re.compile(r"[a-z0-9'.]+")


def _follower_blacklisted(norm: str, end: int) -> bool:
    """L4(b): does a currency / holiday / instrument noun stand immediately after the match?"""
    tail = norm[end:end + 48]
    tail = tail[_POSSESSIVE_RX.match(tail).end():]           # 'China's', 'Brazilians''
    words = _WORD_RX.findall(tail)[:_FOLLOWER_MAX_WORDS]
    for n in range(len(words), 0, -1):
        if " ".join(words[:n]).strip(".") in _FOLLOWER_BLACKLIST:
            return True
    return False


# ══ THE PUBLIC API ════════════════════════════════════════════════════════════════════════════════════
def extract_geos(text: str) -> list[tuple[int, int, str]]:
    """Every canonical geography `text` names, as `(start, end, slug)` INTO `text`'s OWN offsets.

    AFTER ALL FOUR GUARDS. A returned tuple is a token the verifier may reason about; anything the guards
    refused simply is not here, and the caller never has to know why. Never raises -- a vocabulary lookup
    that can break a turn is not a vocabulary lookup."""
    if not text or _MATCH_RX is None:
        return []
    try:
        norm = normalize(text)
        out: list[tuple[int, int, str]] = []
        for m in _MATCH_RX.finditer(norm):
            key = re.sub(r"\s+", " ", m.group(0)).strip()
            slug = _SURFACE_TO_SLUG.get(key)
            if slug is None:                    # a DECOY or an AMBIGUOUS surface: span consumed, silence
                continue
            if _follower_blacklisted(norm, m.end()):
                continue
            out.append((m.start(), m.end(), slug))
        return out
    except Exception:                           # noqa: BLE001 -- fail toward NOT comparing
        return []


def canon_closure(slug: str | None) -> set[str]:
    """L2, ADDITIVE: the slug plus every ancestor it folds into. `{france} -> {france, european_union}`.

    NEVER A REPLACEMENT. A replacing fold turns a France claim into an EU claim and then convicts it
    against a France receipt, which is the exact defect `_PSD_COUNTRY_FOLD` would have introduced here.
    An unknown slug closes to itself so a caller can never be handed an empty set for a real token."""
    s = str(slug or "").strip()
    if not s:
        return set()
    return {s} | set(_ANCESTORS.get(s, frozenset()))


def closure_of(slugs) -> set[str]:
    """`canon_closure` over an iterable, unioned. The shape both comparison sides are held in."""
    out: set[str] = set()
    for s in (slugs or ()):
        out |= canon_closure(s)
    return out


def sentinel_hit(text: str) -> bool:
    """L1: does `text` name an AGGREGATE (`world / global / worldwide / total / international /
    all origins`)? The EU-when-unaccompanied half is the caller's -- see the note at
    `AGGREGATE_SENTINELS`."""
    if not text:
        return False
    try:
        return _SENTINEL_RX.search(normalize(text)) is not None
    except Exception:                           # noqa: BLE001 -- fail toward NOT comparing
        return True


def slugs_in(text: str) -> set[str]:
    """The distinct canonical slugs `text` names, guards applied. Convenience over `extract_geos`."""
    return {s for (_a, _b, s) in extract_geos(text)}


def display(slug: str | None) -> str:
    entry = _COUNTRIES.get(str(slug or ""))
    return str(entry["display"]) if entry else ""


# ══ THE IMPORT-TIME LINT -- A DEVELOPER INSTRUMENT, NEVER A RUNTIME DEPENDENCY ════════════════════════
# `configs/geographies/` is NOT gitignored today, but an image is built from a subset of the tree and this
# module MUST import clean without it (that is the whole reason the lexicon is in `src/`). So the lint is
# SKIP-SILENT WHEN THE DIRECTORY IS ABSENT and never raises when it is present: it records into
# `LEXICON_LINT`, which the unit suite reads. A lexicon that refuses to import because a config drifted is
# a serving outage caused by a linter.
_GEO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "configs", "geographies")
_SLUG_RX = re.compile(r"country:\s*([a-z_]+)")
LEXICON_LINT: list[str] = []
CONFIG_SLUGS: frozenset[str] = frozenset()


def _lint() -> None:
    global CONFIG_SLUGS
    try:
        if not os.path.isdir(_GEO_DIR):
            return                                          # SKIP-SILENT: an image without the configs
        found: set[str] = set()
        for name in sorted(os.listdir(_GEO_DIR)):
            if not name.endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(_GEO_DIR, name), "r", encoding="utf-8") as fh:
                found |= set(_SLUG_RX.findall(fh.read()))
        CONFIG_SLUGS = frozenset(found)
        missing = sorted(found - set(_COUNTRIES))
        if missing:
            LEXICON_LINT.append("configs/geographies country slugs absent from the lexicon: "
                                + ", ".join(missing))
    except Exception as exc:                                # noqa: BLE001 -- never a runtime dependency
        LEXICON_LINT.append(f"lint skipped: {exc}")


_lint()
