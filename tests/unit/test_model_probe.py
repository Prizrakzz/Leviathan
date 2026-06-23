"""WS-C Haiku-vs-Sonnet bake-off — mocked unit tests (no network): Haiku pricing, cost/cache accounting,
and the ADOPT/TRADEOFF/KEEP decision bands."""
from __future__ import annotations

from leviathan.graphrag import extract as ex
from leviathan.graphrag import model_probe as mp


def _res(name, model, out_tok=350, read=4000):
    r = mp.Res(name=name, model=model)
    r.usages = [ex.Usage(input_tokens=80, output_tokens=out_tok, cache_read=read) for _ in range(5)]
    r.extractions = [ex.ChunkExtraction() for _ in range(5)]
    return r


def test_haiku_priced_and_cheaper():
    pin, pout = ex.price(ex.HAIKU)
    assert (pin, pout) == (1.0 / 1e6, 5.0 / 1e6)
    u = ex.Usage(input_tokens=80, output_tokens=350, cache_read=4000)
    assert u.cost_for(ex.HAIKU, "5m") < u.cost_for(ex.SONNET, "5m")     # cheaper per call


def test_res_warm_and_cache_accounting():
    r = _res("HAIKU", ex.HAIKU)
    assert r.warm_per_call() > 0 and r.mean_out() == 350
    assert mp.Res("HAIKU", ex.HAIKU, usages=[ex.Usage(cache_read=4000)]).cache_writes() == 0   # silent miss
    assert mp.Res("HAIKU", ex.HAIKU, usages=[ex.Usage(cache_creation=4000)]).cache_writes() == 1


def _scores(haiku_edge):
    return {"SONNET": {"edge_g": (0.55, 0.32), "ent_g": (0.9, 0.8), "quant_g": (0.8, 0.7)},
            "HAIKU": {"edge_g": haiku_edge, "ent_g": (0.9, 0.8), "quant_g": (0.8, 0.7), "edge_f": (0.9, 0.9)}}


def test_report_adopt_when_recall_holds():
    res = {"SONNET": _res("SONNET", ex.SONNET), "HAIKU": _res("HAIKU", ex.HAIKU)}
    rep = mp.build_report(res, _scores((0.54, 0.31)), 5)        # 0.54/0.55=0.98 ≥95%, precision ok
    assert "ADOPT HAIKU" in rep and "cheaper" in rep


def test_report_tradeoff_band():
    res = {"SONNET": _res("SONNET", ex.SONNET), "HAIKU": _res("HAIKU", ex.HAIKU)}
    rep = mp.build_report(res, _scores((0.50, 0.31)), 5)        # 0.50/0.55=0.91 → 85–95%
    assert "TRADEOFF" in rep


def test_report_keep_sonnet_when_recall_collapses():
    res = {"SONNET": _res("SONNET", ex.SONNET), "HAIKU": _res("HAIKU", ex.HAIKU)}
    rep = mp.build_report(res, _scores((0.40, 0.31)), 5)        # 0.40/0.55=0.73 < 85%
    assert "KEEP SONNET" in rep


def test_report_flags_haiku_cache_silent_miss():
    res = {"SONNET": _res("SONNET", ex.SONNET),
           "HAIKU": mp.Res("HAIKU", ex.HAIKU,
                           usages=[ex.Usage(input_tokens=4267, output_tokens=350) for _ in range(5)],  # no cache
                           extractions=[ex.ChunkExtraction() for _ in range(5)])}
    rep = mp.build_report(res, _scores((0.54, 0.31)), 5)
    assert "SILENT MISS" in rep
