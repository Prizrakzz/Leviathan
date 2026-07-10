"""Stage 5.3 R1: S3-backed HF model cache. Exercises the sync/populate/ensure branch logic with a fake S3
client and a fake model download — no boto3, no torch, no network."""
from __future__ import annotations

import os

import pytest
from leviathan.graphrag import hf_cache


class FakeS3:
    """Minimal boto3 s3-client stand-in: an in-memory {(bucket, key): bytes} object store."""

    def __init__(self, existing: dict | None = None):
        self.store: dict[tuple[str, str], bytes] = dict(existing or {})
        self.uploaded: list[str] = []
        self.downloaded: list[str] = []

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=1000):
        keys = [k for (b, k) in self.store if b == Bucket and k.startswith(Prefix)][:MaxKeys]
        return {"KeyCount": len(keys), "Contents": [{"Key": k} for k in keys]}

    def upload_file(self, filename, Bucket, Key):
        with open(filename, "rb") as f:
            self.store[(Bucket, Key)] = f.read()
        self.uploaded.append(Key)

    def download_file(self, Bucket, Key, Filename):
        os.makedirs(os.path.dirname(Filename), exist_ok=True)
        with open(Filename, "wb") as f:
            f.write(self.store[(Bucket, Key)])
        self.downloaded.append(Key)

    def get_paginator(self, name):
        s3 = self

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for (b, k) in s3.store if b == Bucket and k.startswith(Prefix)]}

        return _P()


@pytest.fixture
def hf_home(tmp_path, monkeypatch):
    home = tmp_path / "hf"
    monkeypatch.setenv("HF_HOME", str(home))
    monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)
    return home


def _fake_download(home):
    """Emulate _download_models: write a couple of files under the hub layout hf_cache checks for."""
    for model in ("BAAI--bge-m3", "BAAI--bge-reranker-v2-m3"):
        d = home / "hub" / f"models--{model}" / "snapshots" / "abc"
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text("{}", encoding="utf-8")
        (d / "model.safetensors").write_bytes(b"weights")


def test_parse():
    assert hf_cache._parse("s3://bucket/models/hf") == ("bucket", "models/hf")
    assert hf_cache._parse("s3://bucket/models/hf/") == ("bucket", "models/hf")
    assert hf_cache._parse("bucket/p") == ("bucket", "p")


def test_populate_uploads_tree(hf_home, monkeypatch):
    monkeypatch.setattr(hf_cache, "_download_models", lambda: _fake_download(hf_home))
    s3 = FakeS3()
    res = hf_cache.populate("s3://bkt/models/hf", s3=s3)
    assert res["uploaded"] == 4                                   # 2 files x 2 models
    # keys are prefixed and preserve the relative hub path
    assert ("bkt", "models/hf/hub/models--BAAI--bge-m3/snapshots/abc/config.json") in s3.store
    assert all(k.startswith("models/hf/") for k in s3.uploaded)


def test_ensure_seeds_when_s3_empty(hf_home, monkeypatch):
    monkeypatch.setattr(hf_cache, "_download_models", lambda: _fake_download(hf_home))
    s3 = FakeS3()                                                # empty -> not populated -> seed
    res = hf_cache.ensure("s3://bkt/models/hf", s3=s3)
    assert res.get("seeded") is True and res["action"] == "populate"
    assert s3.uploaded and not s3.downloaded


def test_ensure_syncs_when_s3_populated(hf_home, monkeypatch):
    # Pre-seed S3, leave HF_HOME empty -> ensure() must download, not re-seed.
    existing = {
        ("bkt", "models/hf/hub/models--BAAI--bge-m3/snapshots/abc/config.json"): b"{}",
        ("bkt", "models/hf/hub/models--BAAI--bge-reranker-v2-m3/snapshots/abc/config.json"): b"{}",
    }
    s3 = FakeS3(existing)
    called = {"dl": False}
    monkeypatch.setattr(hf_cache, "_download_models", lambda: called.__setitem__("dl", True))
    res = hf_cache.ensure("s3://bkt/models/hf", s3=s3)
    assert res["action"] == "sync" and res["downloaded"] == 2
    assert called["dl"] is False                                 # never touched HuggingFace
    assert (hf_home / "hub" / "models--BAAI--bge-m3" / "snapshots" / "abc" / "config.json").exists()


def test_sync_skips_when_local_already_populated(hf_home):
    _fake_download(hf_home)                                      # local cache already has both models
    s3 = FakeS3({("bkt", "models/hf/x"): b"z"})
    res = hf_cache.sync("s3://bkt/models/hf", s3=s3)
    assert res["skipped"] is True and res["downloaded"] == 0 and not s3.downloaded


def test_is_populated(hf_home):
    assert hf_cache.is_populated("s3://bkt/p", s3=FakeS3()) is False
    assert hf_cache.is_populated("s3://bkt/p", s3=FakeS3({("bkt", "p/f"): b"1"})) is True


def test_download_models_prunes_to_safetensors(monkeypatch):
    # _download_models must snapshot_download each model with the redundant weight formats ignored (keeps the
    # cache lean). Inject a fake huggingface_hub so the test needs no real install/network.
    import sys
    import types

    calls: list[tuple[str, tuple]] = []
    fake = types.ModuleType("huggingface_hub")
    fake.snapshot_download = lambda repo_id, ignore_patterns=None: calls.append((repo_id, tuple(ignore_patterns or ())))
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    hf_cache._download_models()
    assert [c[0] for c in calls] == list(hf_cache.MODELS)
    for _repo, ignored in calls:
        assert set(hf_cache._IGNORE_PATTERNS).issubset(set(ignored))
        assert "pytorch_model.bin" in ignored and "*.onnx" in ignored


def test_sync_serial_path_when_workers_1(hf_home, monkeypatch):
    monkeypatch.setenv("GRAPHRAG_HF_S3_WORKERS", "1")
    assert hf_cache._workers() == 1
    existing = {("bkt", "models/hf/v2/hub/models--BAAI--bge-m3/snapshots/abc/model.safetensors"): b"w",
                ("bkt", "models/hf/v2/hub/models--BAAI--bge-reranker-v2-m3/snapshots/abc/model.safetensors"): b"w"}
    s3 = FakeS3(existing)
    res = hf_cache.sync("s3://bkt/models/hf/v2", s3=s3)
    assert res["downloaded"] == 2 and not res["skipped"]
    assert (hf_home / "hub" / "models--BAAI--bge-m3" / "snapshots" / "abc" / "model.safetensors").exists()


def test_workers_default_and_bad_value(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_HF_S3_WORKERS", raising=False)
    assert hf_cache._workers() == 16
    monkeypatch.setenv("GRAPHRAG_HF_S3_WORKERS", "notanint")
    assert hf_cache._workers() == 16
