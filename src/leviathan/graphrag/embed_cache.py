"""THE EMBED-ONCE CACHE — graph-completion wave Stage 1 (2026-08-21).

THE MEASURED PROBLEM (Stage-0 embed scout, all numbers from the live store): rebuild-slices
re-embeds EVERY routed row on EVERY pass — and multi-label routing embeds each cached prop ~1.76x
WITHIN one pass (725k cached props became 1,277,979 routed rows). The X2 pass paid ~10.5h at
~34 rows/s. The next pass (~1.435M props -> ~2.5M rows) would pay ~21h — and would OOM first,
because the legacy path assigns a ~32.8 KB Python-list vector onto every record that
write_guard.WritePlan.records retains for the whole pass (~83 GB resident at 2.5M rows on the
122,880 MB box).

THE DESIGN (one cache, three walls down):
  * KEY: sha1(text) — the exact twin of the chunk-once law. A re-chunk changes text, so a
    re-chunk correctly invalidates. A stale entry could only ever produce a wrong VECTOR, never a
    wrong POPULATION, so every write-guard fence is untouched.
  * VALUE: the verbatim JSON ARRAY FRAGMENT of the vector ("[0.0123, ...]"), NOT a Python list.
    float32 round-trips these bytes losslessly (measured: tolist() equality AND json.dumps
    byte-identity), and the SPLICE — json.dumps(meta)[:-1] + ', "vector": ' + frag +
    ', "backend": "<b>"}' — reproduces the legacy json.dumps(record) BYTE-IDENTICALLY at ~37us/rec
    vs ~2,500us (the serialization wall: ~2.2h of float formatting at 2.5M rows becomes ~2min).
    Key order is load-bearing: vector second-to-last, backend last — exactly the insertion order
    the legacy _mk assignments produced. Any other placement changes bytes at IDENTICAL length,
    which resolve_prior's after_bytes fence cannot catch.
  * SEED: stream the live slice objects (the 43 commodity + ~120 driver .jsonl already carry
    every routed row's vector inline, backend-stamped) and extract fragments by STRING SLICING —
    never json.loads the vector (44us/rec vs 2,031us; the GIL makes threaded parsing useless).
    ~1 minute of CPU + one in-region pass over ~30 GB.
  * VERIFY (the gate that makes seeding ratifiable): re-embed a random sample of seeded texts and
    require cosine >= 1 - 1e-6 against the seeded bytes. REFUSE the pass on failure — a mixed
    embedding space is undetectable downstream until retrieval quality silently moves. This also
    covers the unpinned-HF-revision hazard (hf snapshot drift = verify failure = loud stop).
  * FALLBACK IS REAL: disabled (the default), seed failure, or verify failure all land on the
    legacy path's exact behaviour. The cache is env-gated (EVIDENCE_EMBED_CACHE=1) so serving and
    eval processes never construct it; the single-text _Q_CACHE memo is untouched.

LEAF MODULE: no leviathan imports. The embed function and store URI are INJECTED so evidence.py
and evidence_batch.py can both use it without cycles.

Projected first cached rebuild (scout arithmetic): seed ~1.28M rows in ~5-10 min, embed only the
~710k genuinely-new texts, serialize by splice — ~3h total instead of ~21h (the plan's "minutes"
applies to later rebuilds where the new-text set is small). Every NEW driver slice the wave adds
costs ZERO embeds: its prop texts are already embedded under a commodity slice.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

_ENV_FLAG = "EVIDENCE_EMBED_CACHE"
_MEM_CAP_ENV = "EVIDENCE_FRAG_MEMO_GB"                 # refuse a seed projected past this (default 48)
_VEC_OPEN = b'"vector": ['
_BACKEND_KEY = b'], "backend": '


def enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").strip() == "1"


def _sha(text: str) -> bytes:
    return hashlib.sha1(text.encode("utf-8")).digest()


class SeedRefused(RuntimeError):
    """Raised when the seed or its verification cannot vouch for the cache — the caller falls back
    to the legacy full-embed path (or aborts, per its own policy). Never degrade to half-seeded."""


class EmbedCache:
    def __init__(self, backend: str):
        self.backend = backend
        self._frags: dict[bytes, str] = {}
        self._verify_pool: list[str] = []              # reservoir of seeded TEXTS (the cache stores only
        self._pool_seen = 0                            # hashes otherwise) so verify() is self-contained
        self._pool_rng = random.Random(0)
        self.stats = {"seeded": 0, "seed_skipped_backend": 0, "seed_objects": 0, "seed_bad_lines": 0,
                      "hits": 0, "misses": 0}
        self._lock = threading.Lock()

    _POOL_CAP = 2000

    def _pool_offer(self, text: str) -> None:
        self._pool_seen += 1
        if len(self._verify_pool) < self._POOL_CAP:
            self._verify_pool.append(text)
        else:
            j = self._pool_rng.randrange(self._pool_seen)
            if j < self._POOL_CAP:
                self._verify_pool[j] = text

    # ── the read/write surface the _mk sites use ────────────────────────────────────────────────
    def fragment(self, text: str) -> Optional[str]:
        f = self._frags.get(_sha(text))
        if f is not None:
            self.stats["hits"] += 1
        else:
            self.stats["misses"] += 1
        return f

    def add(self, text: str, vec: list[float]) -> str:
        """Register a freshly-embedded vector; returns its fragment (the one json.dumps it will
        ever pay). The fragment is byte-identical to what the legacy path would have written."""
        frag = json.dumps(vec)
        self._frags[_sha(text)] = frag
        return frag

    # ── seeding ─────────────────────────────────────────────────────────────────────────────────
    def _extract(self, line: bytes) -> tuple[Optional[str], Optional[str], str]:
        """(text, fragment, disposition) from one slice JSONL line — string-sliced, vector never
        parsed. disposition in {'ok','skipped_backend','bad_line','alien'}; counters are the
        CALLER's job (review m6: workers must not race the stats dict)."""
        # rfind, not find: the REAL vector is always the second-to-last key, so anchoring from the
        # end makes a '"vector": [' occurring INSIDE a prop's text (a prop quoting JSON) unhittable
        # -- with find() such a line would mis-cut and land in bad_lines (safe but lost); with
        # rfind it seeds correctly.
        j = line.rfind(_BACKEND_KEY)
        if j < 0:
            return None, None, "alien"
        i = line.rfind(_VEC_OPEN, 0, j)
        if i < 0:
            return None, None, "alien"
        tail = line[j + len(_BACKEND_KEY):].strip()
        if not tail.startswith(json.dumps(self.backend).encode("ascii")):
            return None, None, "skipped_backend"
        if line[i - 2: i] != b", ":                                        # shape check BEFORE any decode
            return None, None, "bad_line"                                  # (review m1)
        try:
            frag = line[i + len(_VEC_OPEN) - 1: j + 1].decode("ascii")     # "[...]" inclusive
            meta = line[: i - 2] + b"}"                                    # cut ', "vector": ...' cleanly
            text = json.loads(meta)["text"]
        except (ValueError, KeyError, TypeError):                          # review m1: UnicodeDecodeError
            return None, None, "bad_line"                                  # is a ValueError; one malformed
        return text, frag, "ok"                                            # byte is never a pass-killer

    def seed_from_slices(self, *, list_keys: Callable[[], list[str]],
                         stream_lines: Callable[[str], "list[bytes]"],
                         workers: int = 12, mem_cap_gb: Optional[float] = None,
                         log: Callable[[str], None] = lambda s: print(s, flush=True)) -> dict:
        """Fill the cache from the live slice objects. `list_keys` returns the slice object names;
        `stream_lines(key)` yields that object's raw JSONL lines (bytes). Injection keeps this
        module a leaf and the test hermetic. Refuses (SeedRefused) rather than half-seeding."""
        cap_gb = mem_cap_gb if mem_cap_gb is not None else float(os.environ.get(_MEM_CAP_ENV, "48"))
        keys = list_keys()
        if not keys:
            raise SeedRefused("seed found ZERO slice objects — a cache seeded from nothing would "
                              "silently force a full re-embed while claiming to exist")
        t0 = time.time()
        state = {"done": 0, "approx_bytes": 0}

        def _one(key: str) -> None:
            # REVIEW M2: insert UNDER THE LOCK inside the worker and return nothing — pool.map's
            # in-order consumption otherwise let ~all completed objects pile up as unconsumed
            # (text, frag) lists (~doubling seed peak memory). stream_lines is a GENERATOR, so at
            # most `workers` line buffers exist at once, never whole objects.
            local = {"skipped_backend": 0, "bad_lines": 0}
            for line in stream_lines(key):
                text, frag, disp = self._extract(line)
                if disp == "ok":
                    k = _sha(text)
                    with self._lock:
                        if k not in self._frags:
                            self._frags[k] = frag
                            state["approx_bytes"] += len(frag) + 60
                            self._pool_offer(text)
                elif disp == "skipped_backend":
                    local["skipped_backend"] += 1
                elif disp == "bad_line":
                    local["bad_lines"] += 1
            with self._lock:
                self.stats["seed_skipped_backend"] += local["skipped_backend"]
                self.stats["seed_bad_lines"] += local["bad_lines"]
                self.stats["seeded"] = len(self._frags)
                state["done"] += 1
                done, ab = state["done"], state["approx_bytes"]
            if done % 20 == 0 or done == len(keys):
                log(f"  embed-cache seed: {done}/{len(keys)} objects, {len(self._frags):,} unique "
                    f"texts, ~{ab / 1e9:.1f} GB, {time.time() - t0:.0f}s")
            if ab / 1e9 > cap_gb:
                raise SeedRefused(f"seed projected past {_MEM_CAP_ENV}={cap_gb} GB at object "
                                  f"{done}/{len(keys)} — raise the cap deliberately or run uncached")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for _ in pool.map(_one, keys):                 # consume to propagate the FIRST exception
                pass
        self.stats["seed_objects"] = state["done"]
        return dict(self.stats)

    # ── the space-consistency gate ──────────────────────────────────────────────────────────────
    def verify(self, embed_fn: Callable[[list[str]], list[list[float]]], *, sample: int = 500,
               log: Callable[[str], None] = lambda s: print(s, flush=True)) -> None:
        """Re-embed a random sample of SEEDED texts (the reservoir collected during seeding) and
        require cosine >= 1 - 1e-6 vs the seeded bytes. REFUSES (SeedRefused) on any mismatch: a
        drifted HF snapshot or a foreign vector space must stop the pass, never blend into it —
        a mixed space is undetectable downstream until retrieval quality silently moves."""
        if not self._verify_pool:
            raise SeedRefused("verify found no seeded texts to check — refusing an unverified cache")
        rng = random.Random(1)
        picked = rng.sample(self._verify_pool, min(sample, len(self._verify_pool)))
        fresh = embed_fn(picked)
        worst = 1.0
        for text, v in zip(picked, fresh):
            cached = json.loads(self._frags[_sha(text)])
            num = sum(a * b for a, b in zip(cached, v))
            den = (sum(a * a for a in cached) ** 0.5) * (sum(b * b for b in v) ** 0.5) or 1.0
            cos = num / den
            worst = min(worst, cos)
            if cos < 1 - 1e-6:
                raise SeedRefused(f"embed-cache VERIFY FAILED: cosine {cos:.8f} < 1-1e-6 on a seeded "
                                  "text — the live vectors and this process's embedder are NOT the "
                                  "same space (HF snapshot drift?). Refusing the cached pass.")
        log(f"  embed-cache verify: {len(picked)} samples re-embedded, worst cosine {worst:.8f} -- PASS")


# ── the process-wide active cache (build processes only; serving never constructs one) ──────────
_ACTIVE: Optional[EmbedCache] = None


def active() -> Optional[EmbedCache]:
    return _ACTIVE


def set_active(cache: Optional[EmbedCache]) -> None:
    """Install/clear the process-wide cache. Only rebuild_slices installs one, and only for its
    own pass (review m4: a leaked active cache would hand _cached_slice_body a backend=None
    divergence on any later in-process caller — rebuild clears it when the pass ends, and
    _cached_slice_body also resolves the backend itself as belt-and-braces)."""
    global _ACTIVE
    _ACTIVE = cache


def splice(meta_json: str, frag: str, backend: str) -> str:
    """The byte-identical serialization: meta (a json.dumps of the record WITHOUT vector/backend)
    spliced with the cached fragment, vector second-to-last and backend last — the legacy
    insertion order, verified byte-for-byte across 30 record/vector shapes (the review's matrix).
    NOTE the exact claim (review m9): byte-identity is for SERIALIZATION of given vectors; fresh
    embeds remain batch-composition-sensitive in the last float bits — cached reuse REDUCES that
    drift, it does not change what a fresh embed would produce."""
    if not meta_json.endswith("}") or meta_json == "{}":       # review m8: an empty/alien meta would
        raise ValueError("splice needs a non-empty JSON object serialization")   # emit invalid JSON
    return meta_json[:-1] + ', "vector": ' + frag + ', "backend": ' + json.dumps(backend) + "}"
