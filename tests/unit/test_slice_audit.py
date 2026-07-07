"""W1.5 slice-precision spot-audit tests -- fully mocked (no S3, no Anthropic, no spend).

Pins the four load-bearing pieces: the <=k sampler, the one-request-per-prop judge builder (slice name in
every prompt), the precision collector over mocked YES/NO results, and the --dry-run that submits nothing
and prints an ASCII cost line (Windows cp1252). All hermetic + synthetic -- no real DAG/slice IP.
"""
from __future__ import annotations

from leviathan.graphrag import slice_audit as sa


def _recs(n, source="usda_gain_x", text="Brazil frost cut arabica output."):
    """Synthetic driver-slice records shaped like ev.load_index output (id/date/source/source_key/text)."""
    return [{"id": f"c{i}", "driver": "frost", "date": "2019-06-01", "source": source,
             "source_key": f"text/source={source}/year=2019/document.json",
             "text": f"{text} ({i})"} for i in range(n)]


# ── sampler ────────────────────────────────────────────────────────────────────────
def test_sample_takes_at_most_k_and_is_deterministic():
    recs = _recs(25)
    picked = sa.sample_props(recs, k=10, seed=1)
    assert len(picked) == 10
    assert all(p in recs for p in picked)
    assert picked == sa.sample_props(recs, k=10, seed=1)          # seeded -> reproducible


def test_sample_returns_all_when_fewer_than_k():
    recs = _recs(4)
    assert len(sa.sample_props(recs, k=10, seed=1)) == 4


# ── request builder ─────────────────────────────────────────────────────────────────
def test_build_requests_one_per_prop_with_slice_name_in_prompt():
    sampled = {"el_nino": _recs(3), "freight": _recs(2)}
    reqs, manifest = sa.build_requests(sampled, model=sa.ex.HAIKU)
    assert len(reqs) == 5 == len(manifest)
    assert len({r["custom_id"] for r in reqs}) == 5             # custom_ids unique
    for r in reqs:
        m = manifest[r["custom_id"]]
        content = r["params"]["messages"][0]["content"]
        assert m["slice"] in content                           # slice name in the judge prompt
        assert r["params"]["model"] == sa.ex.HAIKU
        assert "tools" not in r["params"]                      # plain YES/NO judge, no tool schema
    assert {manifest[r["custom_id"]]["slice"] for r in reqs} == {"el_nino", "freight"}
    assert all(re_ok(cid) for cid in manifest)                 # API-legal custom_ids


def re_ok(cid: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid))


# ── fake Anthropic batch client (yes/no text results) ────────────────────────────────
def _text_result(cid, text, in_tok=30, out_tok=12):
    blk = type("Blk", (), {"type": "text", "text": text})()
    usage = type("U", (), {"input_tokens": in_tok, "output_tokens": out_tok})()
    msg = type("Msg", (), {"content": [blk], "usage": usage})()
    res = type("Res", (), {"type": "succeeded", "message": msg})()
    return type("Wrap", (), {"custom_id": cid, "result": res})()


class _FakeBatches:
    def __init__(self, verdicts):
        self._verdicts = verdicts                              # {cid -> "YES ..."/"NO ..."}
        self.created = None

    def create(self, requests):
        self.created = requests
        return type("B", (), {"id": "batch_audit"})()

    def retrieve(self, bid):
        return type("B", (), {"processing_status": "ended"})()

    def results(self, bid):
        for cid, text in self._verdicts.items():
            yield _text_result(cid, text)


class _FakeClient:
    def __init__(self, verdicts):
        self.messages = type("M", (), {"batches": _FakeBatches(verdicts)})()


# ── collector ────────────────────────────────────────────────────────────────────────
def test_collect_tabulates_precision():
    sampled = {"el_nino": _recs(4)}
    reqs, manifest = sa.build_requests(sampled, model=sa.ex.HAIKU)
    cids = [r["custom_id"] for r in reqs]
    verdicts = {cids[0]: "YES\nclearly about El Nino.",
                cids[1]: "yes: on-topic ENSO signal",
                cids[2]: "YES - about the Pacific oscillation",
                cids[3]: "NO\nthis is about ocean freight, misfiled."}     # 3 YES / 1 NO -> 0.75
    out = sa.collect_precision(_FakeClient(verdicts), "batch_audit", manifest, model=sa.ex.HAIKU)
    s = out["slices"]["el_nino"]
    assert s["n_judged"] == 4 and s["n_yes"] == 3
    assert abs(s["precision"] - 0.75) < 1e-9
    assert len(s["misfiled"]) == 1 and "freight" in s["misfiled"][0]["reason"]
    assert out["n_fail"] == 0
    assert out["cost_usd"] > 0                                  # billed off mocked usage tokens


def test_collect_counts_unparseable_verdict_as_fail():
    sampled = {"freight": _recs(2)}
    reqs, manifest = sa.build_requests(sampled, model=sa.ex.HAIKU)
    cids = [r["custom_id"] for r in reqs]
    verdicts = {cids[0]: "YES on-topic", cids[1]: "Hmm, unclear -- cannot tell"}
    out = sa.collect_precision(_FakeClient(verdicts), "b", manifest, model=sa.ex.HAIKU)
    s = out["slices"]["freight"]
    assert s["n_judged"] == 1 and s["n_yes"] == 1               # the unscored verdict left the denominator
    assert out["n_fail"] == 1


def test_verdict_parsing_edge_cases():
    def msg(t):
        blk = type("Blk", (), {"type": "text", "text": t})()
        return type("Msg", (), {"content": [blk]})()
    assert sa._verdict_of(msg("YES, it belongs.")) is True
    assert sa._verdict_of(msg("no -- off topic")) is False
    assert sa._verdict_of(msg("**YES**\nreason")) is True
    assert sa._verdict_of(msg("Maybe, hard to say")) is None


# ── cost estimate + dry-run ──────────────────────────────────────────────────────────
def test_estimate_cost_scales_with_props():
    small = sa.estimate_cost({"a": _recs(2)}, model=sa.ex.HAIKU)
    big = sa.estimate_cost({"a": _recs(10)}, model=sa.ex.HAIKU)
    assert small["n_props"] == 2 and big["n_props"] == 10
    assert big["est_usd"] > small["est_usd"] > 0


def test_dry_run_prints_ascii_cost_and_submits_nothing(monkeypatch, capsys):
    monkeypatch.setattr(sa.ev, "load_index", lambda node: _recs(12))
    rc = sa.main(["--dry-run", "--slices", "el_nino,freight", "--k", "10"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No API calls" in out and "$" in out
    assert "20 props" in out                                   # 2 slices x min(10,12) sampled
    out.encode("ascii")                                        # ASCII-only stdout; raises on any unicode leak


def test_gather_samples_skips_empty_slices(monkeypatch, capsys):
    monkeypatch.setattr(sa.ev, "load_index",
                        lambda node: _recs(3) if node == "drivers/has_props" else [])
    sampled = sa._gather_samples(["has_props", "empty_slice"], k=10, seed=1)
    assert set(sampled) == {"has_props"}                       # empty slice dropped, not an empty batch req
    assert "empty_slice" in capsys.readouterr().out
