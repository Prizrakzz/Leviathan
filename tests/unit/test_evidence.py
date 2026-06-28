"""graphdev evidence slice — mocked (no S3/Bedrock/spend)."""
from __future__ import annotations

import json
import types
from datetime import date

from leviathan.graphrag import evidence as ev


class _Prop:                                                    # minimal stand-in for contracts.Chunk
    def __init__(self, cid, prop, d, source="GAIN"):
        self.chunk_id, self.proposition, self.document_date, self.source = cid, prop, d, source


def _fake_chunker(**kw):
    return [_Prop("c1", "Brazil frost devastated arabica coffee in 2021.", date(2021, 7, 20)),
            _Prop("c2", "Unrelated macro note about bonds.", date(2021, 7, 20))]


def _bow_embed(texts, **kw):                                    # deterministic bag-of-words vectors
    vocab = ["frost", "drought", "coffee", "bonds", "rain"]
    return [[1.0 if w in t.lower() else 0.0 for w in vocab] for t in texts]


def test_embed_backend_dispatch(monkeypatch):
    import pytest
    monkeypatch.setattr(ev, "_bge_local", lambda texts: [[0.1, 0.2] for _ in texts])
    assert ev.embed(["a", "b"], backend="bge_local") == [[0.1, 0.2], [0.1, 0.2]]
    body = types.SimpleNamespace(read=lambda: json.dumps({"embedding": [1.0, 2.0]}).encode())
    fake_bedrock = types.SimpleNamespace(invoke_model=lambda **kw: {"body": body})
    assert ev.embed(["x"], backend="titan", bedrock=fake_bedrock) == [[1.0, 2.0]]
    assert ev.embed([], backend="titan") == []                       # empty short-circuits before any call
    with pytest.raises(ValueError):
        ev.embed(["x"], backend="nope")


def test_cosine_and_doc_date():
    assert round(ev._cosine([1, 0], [1, 0]), 3) == 1.0 and ev._cosine([1, 0], [0, 1]) == 0.0
    assert ev._doc_date({"document_date": "2021-07-20"}, "k") == date(2021, 7, 20)
    assert ev._doc_date({}, "text/x/2014/y/document.json").year == 2014   # year-from-key fallback


def test_retrieve_cosine_ranking_and_pit(monkeypatch):
    monkeypatch.setattr(ev, "embed", _bow_embed)
    recs = [{"id": i, "date": d, "source": "GAIN", "source_key": f"k{i}", "text": t,
             "vector": _bow_embed([t])[0]}
            for i, (t, d) in enumerate([("frost hit coffee", "2021-07-20"),
                                        ("drought struck later", "2024-01-01"),
                                        ("bonds macro note", "2021-07-20")])]
    hits = ev.retrieve("frost coffee damage", "arabica_coffee", k=2, records=recs)
    assert hits[0]["text"] == "frost hit coffee" and all("bonds" not in h["text"] for h in hits)
    pit = ev.retrieve("drought", "arabica_coffee", k=5, asof="2022-01-01", records=recs)
    assert pit and all(h["date"] <= "2022-01-01" for h in pit)             # the 2024 prop excluded


def test_build_index_keeps_on_topic_props_and_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "_EVID_DIR", tmp_path)
    monkeypatch.setattr(ev, "embed", _bow_embed)
    monkeypatch.setattr(ev, "sample_keys", lambda *a, **k: ["text/coffee/2021/x/document.json"])
    body = types.SimpleNamespace(read=lambda: json.dumps(
        {"full_text": "Brazil frost hit arabica coffee hard in 2021."}).encode())
    fake_s3 = types.SimpleNamespace(get_object=lambda **kw: {"Body": body})

    n = ev.build_index(fake_s3, node="arabica_coffee", aliases=["arabica"], year_windows=[(2021, 2021)],
                       n_docs=1, bedrock=object(), chunker=_fake_chunker)
    assert n == 1                                                          # bonds prop dropped (off-topic)
    recs = ev.load_index("arabica_coffee")
    assert len(recs) == 1 and "frost" in recs[0]["text"] and len(recs[0]["vector"]) == 5
