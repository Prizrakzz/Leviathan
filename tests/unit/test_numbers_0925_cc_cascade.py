"""09-25 CLOSE-OUT, LANE CC -- THE CASCADE PRINT SITES (VERIFY.md sec 6 item 5, B-1: the carried FATAL RT-2 / D11).

The deep soybean page printed "US dryness at 0.90036 z then [N164] and 0.918692 z now [N165]": the cascade's
level lines (``_fmt_line`` era / current, ``_chain_fmt_line`` hop endpoints) print ``f"{sv:g}"`` -- six
significant digits and no grain -- while the footer label printed "0.9 z". Under the threaded display key
(``CW_DISPLAY_ANALYST``, read ONCE in ``quantify`` as ``_dq`` off the board payload) the value slot is the label's
own reader of the one precision producer and, for one cell of a cross-section, the cell grain at the period the
standing is AT. Display absent -> HEAD's bytes; the ``shown`` binding never moves (B5); ``quantify``'s signature
never moves (the g1x census); ``numbers/`` imports nothing from ``state/`` at import time.

Every value below is the deep page's served row VERBATIM (``served_rows[163]`` / ``[153]``).
"""
from __future__ import annotations

import inspect
import subprocess
import sys

import pytest

from leviathan.graphrag.numbers import cascade as CQ

_ASOF = "2026-09-25"
_N164 = [
    ['2.7787671340878766', '2.295293409824487', '1.7281305635137305', '1.1743706029597594', '0.10019795466420646',
     '-0.3597540379559258', '-1.1055926026687415', '-1.1487915448520964', '-1.3595921362564491',
     '-1.4419279897218942'],
    ['3.0179387176451553', '0.31134992453861954', '-0.04973890160963866', '-0.20923384488011965',
     '-0.45280897873498666', '-0.8631671373460031', '-0.8942872859152978', '-0.9777741092557354',
     '-1.0011766186312248', '-1.7111599291401676'],
    ['0.21045462999062534', '0.10561150696967825', '-0.4344325943130835', '-0.6578368537453283',
     '-0.8481890967778524', '-0.8840115801105805', '-0.9543304707154598', '-1.056636751169537',
     '-1.0952145677879515', '-1.3255619751317091'],
    ['0.9003603729220594', '0.22360679774997883', '-0.9909931939970745', '-1.1052358582314172',
     '-1.136394423597312', '-1.3431102193668325', '-1.519297358258059', '-1.6199559950018934',
     '-1.7140790708552462', '-1.910543822789871'],
]
_ROW = {"table": "gold_weather_z", "metric": "drought_z", "narrate_unit": "z", "scale": 1}
_HOP = "(chain hop 1/2: drought -> United States drought_z)"


@pytest.fixture
def headline_on():
    """The served turns ran the A2b headline rule (``quantify``'s threaded ``headline``): the freshest row."""
    was = CQ._HEADLINE_ON
    CQ._set_headline(True)
    yield
    CQ._set_headline(was)


def _rec(values=None, period="2011-01-01..2011-04-01"):
    rows = [{"value": v, "country": "United States", "year": 2011, "month": m}
            for m, block in enumerate(values or _N164, start=1) for v in block]
    return {"query": {"table": "gold_weather_z", "metric": "drought_z", "commodity": "soybeans_cbot",
                      "country": "United States", "period": period, "asof": _ASOF}, "rows": rows, "status": "ok"}


def _needs_grain():
    from leviathan.graphrag.state import render as R
    if getattr(R, "cell_grain_words", None) is None:
        pytest.skip("lane RT's render.cell_grain_words not on this tree")


def test_CC3_the_deep_soy_N164_era_line_prints_the_cell_and_its_period_under_the_key_and_HEADs_bytes_off(headline_on):
    _needs_grain()
    off = CQ._fmt_line(_rec(), _ROW, 164, era=0)
    on = CQ._fmt_line(_rec(), _ROW, 164, era=0, display=CQ.CW_DISPLAY_ANALYST)
    # HEAD: the served page's figure, six significant digits, no grain -- the line HEAD's own formula builds
    sv = CQ._scaled_val(_rec(), _ROW)
    head = (f"- [N164] soybeans_cbot {CQ._metric_display(_ROW)} 2011-01-01..2011-04-01 ({CQ._era_label(0, _ROW)}, "
            f"as-of {_ASOF}): {sv:g} z".rstrip() + f" ({CQ._z_word(sv)})" + CQ._series_tag(_rec()['query'], _ROW))
    assert off == head and ": 0.90036 z " in off
    assert ": 0.9 z for one United States growing cell (the driest of ten), April 2011 (" in on
    assert "0.90036" not in on
    # everything but the value slot is HEAD's
    assert on.replace("0.9 z for one United States growing cell (the driest of ten), April 2011", "0.90036 z") == off


def test_CC3_the_chain_hop_endpoint_line_takes_the_same_value_slot(headline_on):
    _needs_grain()
    off = CQ._chain_fmt_line(_rec(), _ROW, 164, label=_HOP)
    on = CQ._chain_fmt_line(_rec(), _ROW, 164, label=_HOP, display=CQ.CW_DISPLAY_ANALYST)
    assert ": 0.90036 z [series:" in off
    assert ": 0.9 z for one United States growing cell (the driest of ten), April 2011 [series:" in on
    assert on.replace("0.9 z for one United States growing cell (the driest of ten), April 2011", "0.90036 z") == off
    cur_off = CQ._chain_fmt_line(_rec(), _ROW, 165, label=_HOP, current=True)
    cur_on = CQ._chain_fmt_line(_rec(), _ROW, 165, label=_HOP, current=True, display=CQ.CW_DISPLAY_ANALYST)
    assert " current (as-of " in cur_off and " current (as-of " in cur_on
    assert "the driest of ten" in cur_on and "the driest of ten" not in cur_off


def test_CC3_a_level_that_is_no_cell_takes_the_precision_alone_never_a_grain_or_a_period(headline_on):
    # deep served_rows[153] (N154): the ONI over January-April 2011, four monthly rows, one per period
    rec = {"query": {"table": "silver_noaa_oni", "metric": "oni_anom", "commodity": "soybeans_cbot",
                     "country": "United States", "period": "2011-01-01..2011-04-01", "asof": _ASOF},
           "rows": [{"value": v, "year": 2011, "month": m} for m, v in
                    ((1, "-1.29"), (2, "-1.06"), (3, "-0.85"), (4, "-0.6812345"))], "status": "ok"}
    row = {"table": "silver_noaa_oni", "metric": "oni_anom", "narrate_unit": "degC", "scale": 1}
    off = CQ._fmt_line(rec, row, 154, era=0)
    on = CQ._fmt_line(rec, row, 154, era=0, display=CQ.CW_DISPLAY_ANALYST)
    assert ": -0.681234 degC" in off                                     # HEAD's six significant digits
    assert "0.681234" not in on and "cell" not in on and "April 2011" not in on
    assert on.replace(on.split("): ", 1)[1].split(" [series:")[0], "-0.681234 degC") == off


def test_CC3_the_append_sites_thread_the_key_and_the_shown_binding_never_moves(headline_on):
    _needs_grain()
    key = ("soybeans_cbot", "drought")
    base = _rec()

    def recs():
        r_era = dict(base, node_key=key, leg=("era", 0), era_idx=0, my=None)
        r_cur = dict(_rec(period="2025-09-25..2026-09-25"), node_key=key, leg=("current",), era_idx=None, my=None)
        return [r_era, r_cur]

    def run(**kw):
        calls: list = []
        lines, _trace, _d = CQ._assemble(recs(), [{"specs": [{"node_key": key}], "row": _ROW}], 0, calls, **kw)
        return lines, calls
    off_lines, off_calls = run()
    on_lines, on_calls = run(display=CQ.CW_DISPLAY_ANALYST)
    assert len([ln for ln in off_lines if ln.startswith("- [N")]) == 2 == len(off_calls)   # the era + the current
    assert [c.get("shown") for c in off_calls] == [c.get("shown") for c in on_calls]       # B5: bound = sv
    assert [c.get("rows") for c in off_calls] == [c.get("rows") for c in on_calls]
    assert any("the driest of ten" in ln for ln in on_lines)
    assert not any("the driest of ten" in ln for ln in off_lines)


def test_CC3_the_key_is_keyword_only_with_HEADs_default_and_quantify_does_not_move():
    for fn in (CQ._fmt_line, CQ._chain_fmt_line):
        p = inspect.signature(fn).parameters["display"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is None
    assert "display" not in inspect.signature(CQ.quantify).parameters            # the g1x census pins it
    src = inspect.getsource(CQ._assemble) + inspect.getsource(CQ._chain_legs)
    assert src.count('**({"display": display} if display else {})') >= 6       # 4 level sites + 2 pct sites


def test_CC3_numbers_imports_nothing_from_state_at_import_time():
    out = subprocess.run([sys.executable, "-c",
                          "import sys; import leviathan.graphrag.numbers.cascade; "
                          "print(sorted(m for m in sys.modules if m.startswith('leviathan.graphrag.state')))"],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
