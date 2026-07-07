"""Stdlib near-duplicate gate for the evidence heavy pass (GRAPHRAG_PLAN Phase 7 P3 W2.3).

The E4 heavy pass quadruples the corpus; re-chunking content we already hold burns Haiku dollars for
zero new evidence. This is a from-scratch near-dup filter -- `datasketch` is NOT installed (torch lives
only in the embedder image), so the sketch is a bottom-k MinHash over word-shingles plus an exact-dup
md5 short-circuit, all stdlib.

Two design constraints from the P3 verification (corrections #6, law #6/#7):
  * PROP-SPACE corpus side. The chunks/ cache stores PROPOSITIONS ONLY -- no full_text (`_write_doc_cache`).
    So a cached doc's signature is built from its rewritten prop texts, ONCE, from bytes the caller already
    listed; there is NO corpus-side full_text re-fetch (no S3 GET storm). Because props are rewritten, the
    prop-space Jaccard catches STRUCTURAL near-dups; the exact-dup md5 (candidate full_text) catches verbatim
    re-submits the prop-space signature would miss.
  * NO SILENT SKIPS. Every skip carries {source_key, reason, score, partial_60k_flag}; a >FULLTEXT_CAP doc
    is flagged partially-covered and is NEVER auto-skipped on tail novelty (the head may dup while the tail is
    genuinely new) -- only an exact md5 dup retires it.

The gate runs inside `evidence_batch._build_requests_from_docs`, where the candidate body is already in hand.
Embedding-cosine novelty (higher precision) is deferred to the embedder image, per decision D4.
"""
from __future__ import annotations

import hashlib
import re

_WORD = re.compile(r"\w+", re.UNICODE)

DEFAULT_K = 8               # shingle width in words (correction #6)
DEFAULT_NUM = 128           # bottom-k MinHash signature size
DEFAULT_THRESHOLD = 0.85    # conservative: skip only a near-certain dup (D4 -- over-skip is the feared failure)
FULLTEXT_CAP = 60000        # mirrors evidence_batch._FULLTEXT_CAP (the head-cut the chunker applies)


def normalize(text: str) -> str:
    """Lowercased, whitespace-collapsed form -- the unit BOTH md5 and shingling see, so trivial reflow or
    casing differences do not read as novelty (nor mask an exact dup)."""
    return " ".join((text or "").lower().split())


def md5_hex(text: str) -> str:
    """md5 of the normalized text -- the exact-dup short-circuit key (an identical body, byte-for-byte after
    normalization, never needs re-chunking)."""
    return hashlib.md5(normalize(text).encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _h(gram: str) -> int:
    """64-bit blake2b digest of a shingle -> int. blake2b (not the salted builtin ``hash()``) so signatures
    are STABLE across processes and runs -- a re-run must reproduce the same skip decisions (law #7)."""
    return int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")


def shingle_hashes(text: str, k: int = DEFAULT_K) -> set:
    """The set of k-word shingle hashes over the normalized token stream. A text shorter than k words has no
    full k-gram, so it collapses to a single whole-text shingle -- it still gets a (tiny) signature instead of
    an empty one that would read as Jaccard 0 against everything."""
    toks = _tokens(text)
    if len(toks) < k:
        return {_h(" ".join(toks))} if toks else set()
    return {_h(" ".join(toks[i:i + k])) for i in range(len(toks) - k + 1)}


def signature(text: str, *, k: int = DEFAULT_K, num: int = DEFAULT_NUM) -> list:
    """Bottom-k MinHash sketch: the ``num`` smallest shingle hashes, sorted ascending. Deterministic and
    stdlib-only. Empty text -> empty signature (its Jaccard with anything is 0)."""
    return sorted(shingle_hashes(text, k))[:num]


def jaccard(sig_a, sig_b) -> float:
    """KMV bottom-k Jaccard estimate between two bottom-k sketches: over the shared-depth smallest hashes of
    the UNION, the fraction present in BOTH. Returns 0.0 when either sketch is empty. Symmetric."""
    a, b = set(sig_a), set(sig_b)
    if not a or not b:
        return 0.0
    depth = min(len(a), len(b))                      # both are bottom-k; estimate on the shallower sketch's depth
    union = sorted(a | b)[:depth]
    if not union:
        return 0.0
    inter = sum(1 for h in union if h in a and h in b)
    return inter / len(union)


def corpus_signatures(props_by_doc: dict, *, k: int = DEFAULT_K, num: int = DEFAULT_NUM) -> dict:
    """{doc_id -> prop-space signature}, built ONCE from already-loaded chunks/ props (prop texts joined per
    doc). Prop-space by construction (the cache has no full_text); the caller lists chunks/ once and passes the
    loaded props, so there is no per-doc S3 work here (law #6)."""
    return {doc_id: signature(" ".join((p.get("text") or "") for p in props), k=k, num=num)
            for doc_id, props in props_by_doc.items()}


class NoveltyGate:
    """Accumulating near-dup gate for one heavy-pass fill.

    Seeded ONCE with the cached corpus's prop-space signatures. Each candidate is checked against those PLUS
    every candidate already admitted this pass (so an intra-batch dup is caught too), then -- if admitted --
    its own md5 + signature join the accumulators. Verdicts are self-describing for the skip ledger. The gate
    never mutates its inputs and holds no S3 handle (stdlib only)."""

    def __init__(self, corpus_sigs: dict | None = None, corpus_md5s=None, *,
                 k: int = DEFAULT_K, num: int = DEFAULT_NUM,
                 threshold: float = DEFAULT_THRESHOLD, cap: int = FULLTEXT_CAP):
        self.k, self.num, self.threshold, self.cap = k, num, threshold, cap
        self._sigs: dict = dict(corpus_sigs or {})      # doc_id/source_key -> signature
        self._md5s: set = set(corpus_md5s or ())        # normalized-full_text md5s already seen

    def _nearest(self, sig) -> tuple:
        best_id, best = None, 0.0
        for cid, csig in self._sigs.items():
            j = jaccard(sig, csig)
            if j > best:
                best, best_id = j, cid
        return best_id, best

    def check(self, source_key: str, full_text: str) -> dict:
        """Verdict for one candidate: {source_key, skip, reason, score, partial_60k_flag, nearest}. reason in
        {exact_dup, near_dup, partial_kept, novel}. An exact md5 dup always skips; a Jaccard >= threshold skips
        UNLESS the doc is >cap (tail-novelty protection -> partial_kept). Admitted candidates are registered so
        later ones in the same pass dedup against them."""
        text = full_text or ""
        partial = len(text) > self.cap
        md5 = md5_hex(text)
        if md5 in self._md5s:
            return {"source_key": source_key, "skip": True, "reason": "exact_dup",
                    "score": 1.0, "partial_60k_flag": partial, "nearest": None}
        sig = signature(text, k=self.k, num=self.num)
        best_id, best = self._nearest(sig)
        over = best >= self.threshold
        skip = over and not partial                     # long docs are never auto-skipped on tail novelty
        if not skip:                                    # admit -> future candidates in this pass dedup against it
            self._md5s.add(md5)
            self._sigs[source_key] = sig
        reason = "near_dup" if skip else ("partial_kept" if over else "novel")
        return {"source_key": source_key, "skip": skip, "reason": reason,
                "score": round(float(best), 4), "partial_60k_flag": partial, "nearest": best_id}
