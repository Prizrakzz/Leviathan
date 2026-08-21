"""The EMBED-ONCE CACHE (graph-completion wave Stage 1) — the properties that make it safe to arm.

The cache's whole risk surface is byte-drift and space-mixing: a spliced record that differs from
the legacy json.dumps by ONE byte silently re-rolls slices on the next pass (resolve_prior's
after_bytes fence only catches LENGTH changes), and a seeded vector from a different embedder
space corrupts retrieval invisibly. So the pins here are byte-for-byte equality against the
legacy path, fail-closed seeding, and a verify gate that refuses rather than blends.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from leviathan.graphrag import embed_cache as ec
from leviathan.graphrag import evidence as ev

_REPO = Path(__file__).resolve().parents[2]

_VEC = [round(0.001 * i - 0.5, 6) for i in range(8)]          # small dim: the math not the model
_REC = {"id": "r000001#0", "date": "2021-07-20", "source": "usda_gain_coffee",
        "source_key": "text/s/document.json", "text": "July frost hit Sul de Minas",
        "event_date": None, "event_date_precision": None, "char_start": 100, "char_end": 127,
        "offset_kind": "exact", "chunk_version": "aa123a122f12-20260820",
        "date_kind": "publication", "date_layout": "anchored"}


def _legacy_line(rec: dict, vec: list[float], backend: str = "bge_local") -> str:
    r = dict(rec)
    r["vector"], r["backend"] = vec, backend                  # the legacy _mk assignment order
    return json.dumps(r)


# ── splice byte-identity: the load-bearing property ─────────────────────────────────────────────
def test_splice_reproduces_the_legacy_bytes_exactly():
    legacy = _legacy_line(_REC, _VEC)
    spliced = ec.splice(json.dumps(_REC), json.dumps(_VEC), "bge_local")
    assert spliced == legacy                                  # byte-for-byte, key order included


def test_splice_key_order_is_vector_then_backend_last():
    spliced = ec.splice(json.dumps(_REC), json.dumps(_VEC), "bge_local")
    keys = list(json.loads(spliced))
    assert keys[-2:] == ["vector", "backend"]


# ── extraction: string-sliced, never a vector parse ─────────────────────────────────────────────
def test_extract_round_trips_a_real_slice_line():
    cache = ec.EmbedCache("bge_local")
    line = _legacy_line(_REC, _VEC).encode("utf-8")
    text, frag, disp = cache._extract(line)
    assert disp == "ok" and text == _REC["text"]
    assert frag == json.dumps(_VEC)
    # and the fragment re-splices to the original line exactly
    assert ec.splice(json.dumps(_REC), frag, "bge_local").encode("utf-8") == line


def test_extract_survives_a_prop_that_quotes_json():
    """The rfind anchoring: a prop TEXT containing the sentinel string still seeds correctly
    (json.dumps escapes the quotes, but belt-and-braces the anchor comes from the END)."""
    rec = {**_REC, "text": 'the doc said {"vector": [1.0], "backend": "x"} verbatim'}
    cache = ec.EmbedCache("bge_local")
    text, frag, disp = cache._extract(_legacy_line(rec, _VEC).encode("utf-8"))
    assert disp == "ok" and text == rec["text"] and frag == json.dumps(_VEC)


def test_extract_skips_a_foreign_backend():
    cache = ec.EmbedCache("bge_local")
    line = _legacy_line(_REC, _VEC, backend="titan").encode("utf-8")
    assert cache._extract(line) == (None, None, "skipped_backend")


def test_extract_refuses_alien_shapes_and_bad_bytes_without_guessing():
    cache = ec.EmbedCache("bge_local")
    assert cache._extract(b'{"text": "no vector here"}')[2] == "alien"
    assert cache._extract(b'not json at all')[2] == "alien"
    weird = b'{"text": "x","vector": [1.0], "backend": "bge_local"}'      # no ', ' before vector
    assert cache._extract(weird)[2] == "bad_line"
    # review m1: a malformed byte is a skipped LINE, never an exception (UnicodeDecodeError class)
    broken = b'{"text": "\xff", "vector": [1.0], "backend": "bge_local"}'
    assert cache._extract(broken)[2] == "bad_line"


# ── seeding: fail-closed, deduped, capped ───────────────────────────────────────────────────────
def _fake_store(lines_by_key: dict):
    return (lambda: list(lines_by_key), lambda k: lines_by_key[k])


def test_seed_dedupes_across_objects_and_counts():
    a = _legacy_line(_REC, _VEC).encode("utf-8")
    b = _legacy_line({**_REC, "text": "another prop"}, _VEC).encode("utf-8")
    list_keys, stream = _fake_store({"corn.jsonl": [a, b], "drivers/frost.jsonl": [a]})
    cache = ec.EmbedCache("bge_local")
    stats = cache.seed_from_slices(list_keys=list_keys, stream_lines=stream, workers=2,
                                   log=lambda s: None)
    assert stats["seeded"] == 2                               # the duplicate text seeded once
    assert cache.fragment(_REC["text"]) == json.dumps(_VEC)
    assert cache.stats["hits"] == 1


def test_seed_refuses_an_empty_universe():
    cache = ec.EmbedCache("bge_local")
    with pytest.raises(ec.SeedRefused):
        cache.seed_from_slices(list_keys=lambda: [], stream_lines=lambda k: [], log=lambda s: None)


def test_seed_refuses_past_the_memory_cap():
    lines = [_legacy_line({**_REC, "text": f"prop {i}"}, _VEC).encode("utf-8") for i in range(50)]
    list_keys, stream = _fake_store({"corn.jsonl": lines})
    cache = ec.EmbedCache("bge_local")
    with pytest.raises(ec.SeedRefused):
        cache.seed_from_slices(list_keys=list_keys, stream_lines=stream, mem_cap_gb=1e-9,
                               log=lambda s: None)


# ── the verify gate: refuse, never blend ────────────────────────────────────────────────────────
def _seeded_cache(n: int = 10) -> ec.EmbedCache:
    lines = [_legacy_line({**_REC, "text": f"prop {i}"}, _VEC).encode("utf-8") for i in range(n)]
    list_keys, stream = _fake_store({"corn.jsonl": lines})
    cache = ec.EmbedCache("bge_local")
    cache.seed_from_slices(list_keys=list_keys, stream_lines=stream, log=lambda s: None)
    return cache


def test_verify_passes_when_the_space_matches():
    cache = _seeded_cache()
    cache.verify(lambda texts: [list(_VEC) for _ in texts], sample=5, log=lambda s: None)


def test_verify_refuses_a_drifted_space():
    cache = _seeded_cache()
    drifted = list(reversed([v * -1 for v in _VEC]))          # a genuinely different direction --
    with pytest.raises(ec.SeedRefused):                        # near-parallel shifts are NOT drift
        cache.verify(lambda texts: [drifted for _ in texts], sample=5, log=lambda s: None)


def test_verify_tolerance_is_tight_not_cosmetic():
    """The gate must catch even a small genuine rotation: one component's sign flipped moves the
    cosine well past 1e-6 on any real vector -- if this passes, the threshold is doing work."""
    cache = _seeded_cache()
    flipped = list(_VEC)
    flipped[0] = -flipped[0] - 0.2
    with pytest.raises(ec.SeedRefused):
        cache.verify(lambda texts: [flipped for _ in texts], sample=5, log=lambda s: None)


def test_verify_refuses_an_unseeded_cache():
    cache = ec.EmbedCache("bge_local")
    with pytest.raises(ec.SeedRefused):
        cache.verify(lambda texts: [], log=lambda s: None)


# ── the _mk integration: byte-identical slices, no vector on the records ────────────────────────
def test_cached_slice_body_matches_legacy_and_never_attaches_vectors(monkeypatch):
    recs = [dict(_REC), {**_REC, "id": "r000002#0", "text": "stocks were already low"},
            {**_REC, "id": "r000003#0", "text": "a third, uncached prop"}]
    vec_by_text = {r["text"]: [round(0.01 * i + j, 6) for i in range(8)] for j, r in enumerate(recs)}
    legacy = "\n".join(_legacy_line(r, vec_by_text[r["text"]]) for r in recs)

    cache = ec.EmbedCache("bge_local")
    cache.add(recs[0]["text"], vec_by_text[recs[0]["text"]])              # one pre-seeded text
    calls = {"n": 0}

    def fake_embed_raw(texts, *, backend, bedrock=None, **kw):
        calls["n"] += 1
        assert backend == "bge_local"
        return [vec_by_text[t] for t in texts]

    monkeypatch.setattr(ev, "_embed_raw", fake_embed_raw)
    body = ev._cached_slice_body(recs, backend="bge_local", cache=cache, slice_name="corn")
    assert body == legacy                                                 # byte-for-byte
    assert calls["n"] == 1                                                # ONE batched embed of the 2 misses
    assert all("vector" not in r for r in recs)                           # the OOM class stays dead
    # a second pass over the same records embeds NOTHING
    body2 = ev._cached_slice_body(recs, backend="bge_local", cache=cache, slice_name="corn")
    assert body2 == legacy and calls["n"] == 1


def test_cache_is_off_by_default_and_env_gated(monkeypatch):
    monkeypatch.delenv("EVIDENCE_EMBED_CACHE", raising=False)
    assert ec.enabled() is False
    monkeypatch.setenv("EVIDENCE_EMBED_CACHE", "1")
    assert ec.enabled() is True
    assert ec.active() is None                                            # never constructed implicitly


# ── the jobdef/Dockerfile fences (the mute fix must not regress silently) ───────────────────────
def test_jobdef_env_carries_unbuffered_and_cache_flags():
    src = (_REPO / "jobs" / "utils" / "register_evidence_jobdef.py").read_text(encoding="utf-8")
    assert '"PYTHONUNBUFFERED", "value": "1"' in src
    assert '"EVIDENCE_EMBED_CACHE", "value": "1"' in src


def test_dockerfile_carries_unbuffered():
    src = (_REPO / "docker" / "leviathan_embedder" / "Dockerfile").read_text(encoding="utf-8")
    assert "PYTHONUNBUFFERED=1" in src
