"""PRICE_AND_PLAYBOOKS W1a -- the CEPEA cash-reference leg. Hermetic: no network, no AWS.

The widget fixture is the VERBATIM live payload shape (fetched 2026-07-29, HTTP 200,
``application/javascript``, 1,988 B for id 23), reduced to the markup the parser reads. The archive
fixture is a CELL GRID rather than workbook bytes: no library in this estate can WRITE a legacy
.xls, and everything worth testing on that path is grid logic, so the transform is split at the OLE
boundary.

What this file pins is mostly what must NOT happen: no USD column reaching a BRL row, no delivery
month on a cash index, no synthetic ``raw_symbol``, and no 403 challenge body becoming a quiet
empty result.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest
from leviathan.silver import futures_eod_contracts as FC
from leviathan.silver.registry import load_registry
from leviathan.storage.paths import (
    cepea_indicator_prefix,
    raw_cepea_wayback_key,
    raw_cepea_widget_key,
)
from leviathan.transforms.bronze_to_silver import cepea as S
from leviathan.transforms.raw_to_bronze import cepea as T

_REPO = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TASK = _load("jobs/batch/futures_eod_task.py", "futures_eod_task_cepea")
FETCH = _load("jobs/ingest/fetch_cepea_daily.py", "fetch_cepea_daily")
WAYBACK = _load("jobs/ingest/fetch_cepea_wayback_history.py", "fetch_cepea_wayback_history")
LIVE = _load("jobs/ingest/fetch_cepea_live_history.py", "fetch_cepea_live_history")

# The live markup, verbatim in shape. The product name is accented Portuguese in the real payload;
# the escapes below ARE those characters, and the fact that the parser must fold them rather than
# match them is the reason the id -- not the name -- is the mapping key.
_ARABICA = "Caf\u00e9 Ar\u00e1bica"   # the real accented name, escaped (this file is ASCII)
_CORN = "Milho"

_WIDGET_FMT = """document.write(`<style type="text/css">.imagenet-widget-tabela td {{}}</style>
<table class="imagenet-widget-tabela">
    <thead>
        <tr><th>Data</th><th>Produto</th><th>Valor</th></tr>
    </thead>
    <tfoot>
        <tr><td colspan="2">Fonte: Cepea</td><td></td></tr>
    </tfoot>
    <tbody>
                        <tr>
                    <td>{date}</td>
                    <td><span class="maior">{product}</span><br /> <span class="unidade">{basis}</span></td>
                    <td>{currency} <span class="maior">{value}</span></td>
                </tr>
                    </tbody>
</table>`)"""


def widget(indicator: int = 23, *, date: str = "28/07/2026", value: str = "1.782,18",
           product: str | None = None, basis: str = "sc de 60kg",
           currency: str = "R$") -> bytes:
    name = product if product is not None else (_ARABICA if indicator == 23 else _CORN)
    return _WIDGET_FMT.format(date=date, product=name, basis=basis, currency=currency,
                              value=value).encode("utf-8")


# The archive workbook: header on row 3, then Data | A vista R$ | A vista US$.
def history_grid(rows=None) -> list[list]:
    head = [
        ["CEPEA/ESALQ", "", ""],
        ["", "", ""],
        ["Data", "A vista R$", "A vista US$"],
    ]
    body = rows if rows is not None else [
        ["02/09/1996", "123,09", "121,50"],
        ["03/09/1996", "124,10", "122,40"],
        ["04/09/1996", 125.11, 123.30],
        ["", "", ""],
        ["06/06/2025", "2.410,55", "435,20"],
    ]
    return head + [list(r) for r in body]


# ---------------------------------------------------------------------------
class TestWidget:
    def test_the_live_payload_shape_parses(self):
        bronze, stats = T.build_cepea_widget_bronze(widget(23), indicator_id=23,
                                                    as_of_date="2026-07-29")
        assert stats["leviathan_slug"] == "brazilian_arabica_coffee"
        assert stats["trade_date"] == "2026-07-28"
        assert stats["as_of_date"] == "2026-07-29"
        assert len(bronze) == 1
        assert float(bronze["value_brl"].iloc[0]) == pytest.approx(1782.18)

    def test_the_slug_comes_from_the_id_not_the_name(self):
        """The product name is accented Portuguese; the numeric id is the vendor's identity."""
        bronze, _ = T.build_cepea_widget_bronze(widget(77, value="65,22"), indicator_id=77)
        assert bronze["leviathan_slug"].iloc[0] == "campinas_corn_reference_bmf"
        assert float(bronze["value_brl"].iloc[0]) == pytest.approx(65.22)
        with pytest.raises(ValueError, match="not curated"):
            T.slug_for_indicator(99)

    def test_the_widget_serving_another_indicator_is_caught(self):
        with pytest.raises(ValueError, match="curated token"):
            T.build_cepea_widget_bronze(widget(23, product=_CORN), indicator_id=23)

    def test_a_changed_quotation_basis_is_a_hard_error(self):
        """CONTRACT_MAP pins BRL/60-kg bag. If the venue republishes per tonne, a producer that
        ignored the basis string would keep writing a now-wrong unit onto real numbers."""
        with pytest.raises(ValueError, match="60-kg bag"):
            T.build_cepea_widget_bronze(widget(23, basis="por tonelada"), indicator_id=23)

    def test_a_usd_value_is_refused_rather_than_converted(self):
        """There is no FX conversion at ingest, ever."""
        with pytest.raises(ValueError, match="no 'R\\$' marker|marker"):
            T.build_cepea_widget_bronze(widget(23, currency="US$"), indicator_id=23)

    def test_a_challenge_body_is_a_hard_failure_not_an_empty_result(self):
        junk = b"<html><head><title>Just a moment...</title></head><body>cdn-cgi/content</body></html>"
        with pytest.raises(ValueError, match="no <tbody>"):
            T.build_cepea_widget_bronze(junk, indicator_id=23)

    def test_brazilian_decimals(self):
        assert T.parse_brl("1.782,18") == pytest.approx(1782.18)
        assert T.parse_brl("65,22") == pytest.approx(65.22)
        assert T.parse_brl("R$ 12.345,67") == pytest.approx(12345.67)
        with pytest.raises(ValueError, match="BRL decimal"):
            T.parse_brl("")

    def test_the_indicator_map_is_bound_to_the_contract_map_and_to_cash_index_slugs(self):
        assert T._lint_indicator_map() == []
        assert set(T.CEPEA_INDICATORS.values()) == set(FC.CASH_INDEX_SLUGS)


class TestHistory:
    def test_the_series_parses_and_the_usd_column_is_discarded(self):
        bronze, stats = T.build_cepea_history_from_grid(history_grid(), indicator_id=23,
                                                        snapshot_ts="20170708153249")
        assert stats["rows_kept"] == 4 and stats["first_trade_date"] == "1996-09-02"
        assert stats["last_trade_date"] == "2025-06-06"
        # The plan's post-ship check: the arabica series' first row is 02/09/1996 123.09.
        first = bronze.iloc[0]
        assert str(first["trade_date"])[:10] == "1996-09-02"
        assert float(first["value_brl"]) == pytest.approx(123.09)
        # 121.50 is the US$ figure on that row. It must appear NOWHERE.
        assert 121.50 not in set(bronze["value_brl"])
        assert "value_usd" not in bronze.columns

    def test_a_missing_header_refuses_to_read_positionally(self):
        """Column 2 is the US$ series, so a positional fallback is a silent currency mutation."""
        grid = history_grid()
        grid[2] = ["Fecha", "Valor", "Dolar"]
        with pytest.raises(ValueError, match="currency mutation"):
            T.build_cepea_history_from_grid(grid, indicator_id=23)

    def test_numeric_and_text_date_cells_both_decode(self):
        bronze, _ = T.build_cepea_history_from_grid(history_grid(), indicator_id=23)
        assert float(bronze[bronze["trade_date"] == pd.Timestamp("1996-09-04")]
                     ["value_brl"].iloc[0]) == pytest.approx(125.11)

    def test_an_empty_workbook_is_a_hard_error(self):
        with pytest.raises(ValueError, match="no dated BRL rows"):
            T.build_cepea_history_from_grid(history_grid(rows=[["", "", ""]]), indicator_id=23)


# ---------------------------------------------------------------------------
class TestSilverProjection:
    @staticmethod
    def _silver(date: str = "28/07/2026"):
        frames = [T.build_cepea_widget_bronze(widget(23, date=date), indicator_id=23)[0],
                  T.build_cepea_widget_bronze(widget(77, date=date, value="65,22"),
                                              indicator_id=77)[0]]
        return S.build_cepea_silver(pd.concat(frames, ignore_index=True))

    def test_the_cash_index_discriminator(self):
        """The ONLY rows in this table for which a NULL delivery month is legal."""
        df = self._silver()
        assert list(df.columns) == FC.SILVER_COLUMNS
        assert set(df["instrument_kind"]) == {"cash_index"}
        assert set(df["settle_kind"]) == {"cash_index"}
        assert df["contract_month"].isna().all()
        assert df["raw_symbol"].isna().all(), "a cash index has no vendor contract symbol"
        assert set(df["unit"]) == {"BRL/60-kg bag"} and set(df["currency"]) == {"BRL"}
        assert set(df["source"]) == {"cepea"}

    def test_lint_frame_accepts_the_null_month_only_here(self):
        df = self._silver()
        assert FC.lint_frame(df) == []
        # ... and rejects it the moment the rows claim to be futures.
        bad = df.copy()
        bad["instrument_kind"] = "futures"
        errs = FC.lint_frame(bad)
        assert errs and any("NULL contract_month" in e for e in errs)
        # ... and rejects a delivery month ON a cash row, the other direction.
        bad2 = df.copy()
        bad2["contract_month"] = "2026-09"
        assert any("NON-NULL contract_month" in e for e in FC.lint_frame(bad2))

    def test_everything_but_settle_is_null_by_source(self):
        df = self._silver()
        for col in ("open", "high", "low", "close", "volume", "open_interest", "expiry_date",
                    "dataset"):
            assert df[col].isna().all(), f"{col} must be NULL on a cash reference"
        assert df["settle"].notna().all()

    def test_the_f2_assertion_no_longer_false_fails_on_two_null_symbol_rows(self):
        """THE DEFECT THIS LEG WOULD OTHERWISE INTRODUCE. Both cash slugs write raw_symbol NULL, so
        the original (trade_date, raw_symbol) key grouped arabica and Campinas corn together under
        dropna=False on EVERY date -- size 2 -> 'the F2 double bar survived the ICE_BAR_RULE
        dedupe', which would have blocked every publish table-wide."""
        df = self._silver()
        assert TASK._F2_KEY == ["leviathan_slug", "trade_date", "raw_symbol"]
        TASK.assert_no_duplicates(df)                       # must not raise
        sizes = df.groupby(["trade_date", "raw_symbol"], dropna=False).size()
        assert int(sizes.max()) == 2, "the OLD key really would have collided"

    def test_a_genuine_duplicate_still_fails(self):
        df = pd.concat([self._silver(), self._silver()], ignore_index=True)
        df.loc[0, "settle"] = 1.0                            # not an identical row: a CONFLICT
        with pytest.raises(ValueError, match="duplicate"):
            TASK.assert_no_duplicates(df)

    def test_a_holiday_re_serve_collapses_instead_of_stacking(self):
        """The widget keeps serving the previous session's value on a Brazilian holiday. Two
        identical observations of one slug-day are one row, not a duplicate-key hard fail."""
        one = self._silver()
        two = S.build_cepea_silver(pd.concat([
            T.build_cepea_widget_bronze(widget(23), indicator_id=23)[0],
            T.build_cepea_widget_bronze(widget(23), indicator_id=23)[0],
            T.build_cepea_widget_bronze(widget(77, value="65,22"), indicator_id=77)[0],
        ], ignore_index=True))
        assert len(two) == len(one) == 2
        TASK.assert_no_duplicates(two)

    def test_an_alien_slug_is_refused(self):
        bronze = T.build_cepea_widget_bronze(widget(23), indicator_id=23)[0]
        bronze.loc[0, "leviathan_slug"] = "corn_cbot"
        with pytest.raises(ValueError, match="not CEPEA cash references"):
            S.build_cepea_silver(bronze)

    def test_the_publish_route_passes_the_row_validator(self):
        from leviathan.silver.flat_producer import authorize_for_contract
        from leviathan.silver.partitioned_producer import build_partitioned_publish

        df = self._silver()
        contract = load_registry().table("silver_futures_eod")
        plan = build_partitioned_publish(
            df=df, contract=contract,
            auth=authorize_for_contract(contract, publish_mode="dry-run", env={}),
            job="futures_eod_cepea", partition_cols=TASK._PARTITION_COLS,
            s3_client=None, row_validator=FC.lint_frame)
        assert plan.row_count == 2 and plan.partition_count == 2

    def test_the_front_month_rule_drops_these_rows_rather_than_naming_one(self):
        from leviathan.silver import futures_roll as FR

        for slug in T.CEPEA_INDICATORS.values():
            assert FR.roll_method_for(slug) == FR.METHOD_NONE


# ---------------------------------------------------------------------------
class TestRowFloorAndDispatch:
    def test_the_daily_floor_is_an_exact_two(self):
        spec = TASK._SOURCE_SPECS["cepea"]
        df = TestSilverProjection._silver()
        assert TASK.assert_row_floor(df, spec, mode="incremental") == []
        one = df.iloc[:1]
        bad = TASK.assert_row_floor(one, spec, mode="incremental")
        assert len(bad) == 1 and "== 2" in bad[0]

    def test_the_equality_is_not_evaluated_over_a_backfill(self):
        """The archive loads two series whose first rows are EIGHT YEARS apart (arabica 1996-09-02,
        Campinas corn 2004-08-02), so ~2,000 legitimately one-row days sit in the history. An
        equality is a statement about a DAILY publication, not about a backfill."""
        spec = TASK._SOURCE_SPECS["cepea"]
        assert spec.rows_per_day_modes == ("incremental",)
        one = TestSilverProjection._silver().iloc[:1]
        assert TASK.assert_row_floor(one, spec, mode="backfill") == []

    def test_the_leg_is_wired_into_the_host(self):
        assert TASK._SOURCE_SPECS["cepea"].implemented is True
        assert TASK._silver_builder("cepea") is S.build_cepea_silver
        assert TASK._SOURCE_SPECS["cepea"].job == "futures_eod_cepea"


# ---------------------------------------------------------------------------
class TestProducers:
    def test_the_user_agent_is_pinned_and_is_a_browser(self):
        """The default python-requests UA gets a Cloudflare 403 on BOTH ids; a Chrome UA returns
        200. Referer and Accept-Language change nothing -- the UA alone is the gate."""
        assert "Mozilla/5.0" in FETCH.CEPEA_USER_AGENT and "Chrome/" in FETCH.CEPEA_USER_AGENT

    def test_the_host_is_hard_coded(self):
        """cepea.esalq.usp.br 301s here and the redirect double-encodes [] -> %255B%255D, which
        silently yields 'Sem resultados' -- a 200 with no data."""
        assert FETCH.CEPEA_HOST == "www.cepea.org.br"
        assert "esalq.usp.br" not in FETCH.cepea_url(23)
        assert "id_indicador%5B%5D=23" in FETCH.cepea_url(23)

    def test_a_403_raises_and_is_never_an_empty_result(self, monkeypatch):
        class _Resp:
            status_code = 403
            content = b"cdn-cgi/content"

            def raise_for_status(self):
                raise AssertionError("must not reach raise_for_status")

        monkeypatch.setattr(FETCH.requests, "get", lambda url, headers=None, timeout=None: _Resp())
        with pytest.raises(RuntimeError, match="403"):
            FETCH.fetch_indicator(23)

    def test_the_ua_is_actually_sent(self, monkeypatch):
        seen = {}

        class _Resp:
            status_code = 200
            content = widget(23)

            def raise_for_status(self):
                return None

        def _get(url, headers=None, timeout=None):
            seen.update(headers or {})
            return _Resp()

        monkeypatch.setattr(FETCH.requests, "get", _get)
        assert FETCH.fetch_indicator(23) == widget(23)
        assert seen.get("User-Agent") == FETCH.CEPEA_USER_AGENT

    def test_a_challenge_body_is_not_a_widget(self):
        why = FETCH.looks_like_a_widget(b"<html><title>Just a moment...</title></html>")
        assert why and "document.write" in why
        assert FETCH.looks_like_a_widget(widget(23)) is None

    def test_the_raw_keys_separate_the_two_artifact_classes(self):
        daily = raw_cepea_widget_key(23, "2026-07-29")
        history = raw_cepea_wayback_key(23, "20170708153249")
        assert daily.endswith("as_of_date=2026-07-29/widget.js")
        assert history.endswith("history/wayback_20170708153249.xls")
        assert daily.startswith(cepea_indicator_prefix(23))
        assert history.startswith(cepea_indicator_prefix(23))
        assert "/history/" not in daily
        with pytest.raises(ValueError, match="14-digit"):
            raw_cepea_wayback_key(23, "2025")

    def test_the_wayback_snapshots_are_the_captures_that_actually_exist(self):
        # These are the newest captures in the CDX index for the two export URLs (enumerated
        # 2026-07-29). The first cut pinned 2025-shaped timestamps that have no capture at all;
        # Wayback served the 2017 captures anyway and the lie lived in this very test.
        assert set(WAYBACK.CEPEA_SNAPSHOTS) == set(T.CEPEA_INDICATORS)
        assert WAYBACK.CEPEA_SNAPSHOTS[23]["ts"] == "20170708153249"
        assert WAYBACK.CEPEA_SNAPSHOTS[77]["ts"] == "20171027074000"
        assert "id_/" in WAYBACK.snapshot_url(23), "the id_ suffix asks for the ORIGINAL bytes"

    def test_the_coverage_claim_is_the_measured_span(self):
        # Measured off the landed bytes, not inferred from the capture date. If either of these
        # ever reads like a recent year again, something re-introduced the wish-for-a-date bug.
        assert WAYBACK.CEPEA_SNAPSHOTS[23]["last_row"] == "2017-07-07"
        assert WAYBACK.CEPEA_SNAPSHOTS[77]["last_row"] == "2017-10-26"

    def test_a_wayback_placeholder_page_is_not_a_workbook(self):
        why = WAYBACK.looks_like_a_series_workbook(b"<html>not archived</html>")
        assert why and "not a legacy OLE workbook" in why

    def test_a_nearest_capture_redirect_is_refused(self):
        # THE defect: /web/{ts}id_/ does not 404 on an unmatched timestamp, it 200s with the
        # NEAREST capture. Landing those bytes stamps the wrong provenance into the raw key.
        why = WAYBACK.wrong_capture(23, "20250608143948")
        assert why and "not the pinned" in why and "NEAREST" in why
        assert WAYBACK.wrong_capture(23, WAYBACK.CEPEA_SNAPSHOTS[23]["ts"]) is None

    def test_a_response_that_names_no_capture_is_refused(self):
        why = WAYBACK.wrong_capture(77, None)
        assert why and "cannot be established" in why

    def test_a_zero_value_history_row_is_a_placeholder_not_a_price(self):
        # Measured 2026-07-29: the 2017 corn export prints 30/12/2004 = 0.0/0.0 where CEPEA's
        # current record prints 17.37 (between 17.36 and 17.03). Keeping the zero either publishes
        # a fake price or trips F2 uniqueness against the live series. Absence is absence.
        grid = history_grid(rows=[
            ["29/12/2004", "17,36", "6,46"],
            ["30/12/2004", 0.0, 0.0],
            ["03/01/2005", "17,03", "6,37"],
        ])
        bronze, stats = T.build_cepea_history_from_grid(grid, indicator_id=77)
        assert stats["rows_kept"] == 2 and stats["rows_skipped"] == 1
        assert "2004-12-30" not in {str(d)[:10] for d in bronze["trade_date"]}

    def test_history_payload_kind_is_parameterized_for_the_live_leg(self):
        # A live workbook's bronze rows must not wear "wayback" -- provenance travels in the data.
        grid = history_grid()
        bronze, stats = T.build_cepea_history_from_grid(grid, indicator_id=23,
                                                        payload_kind="live")
        assert stats["payload_kind"] == "live"
        assert set(bronze["payload_kind"]) == {"live"}
        bronze2, stats2 = T.build_cepea_history_from_grid(grid, indicator_id=23)
        assert stats2["payload_kind"] == "wayback"

    def test_the_live_leg_lands_under_its_own_stem_and_key(self):
        # live_ vs wayback_: a raw key must never wear a provenance it does not have.
        from leviathan.storage.paths import raw_cepea_live_key

        key = raw_cepea_live_key(23, "20260729190000")
        assert key.endswith("history/live_20260729190000.xls")
        assert "/history/" in key
        with pytest.raises(ValueError, match="14-digit"):
            raw_cepea_live_key(23, "2026")

    def test_the_live_leg_refuses_a_stale_or_foreign_series(self):
        # (d) a series that does not reach past the hole is a stale export wearing a live_ stem;
        # (e) a join-row mismatch means it is not the same series at all. Both must refuse.
        def workbook_rows(last_iso, join_value):
            rows = [["irrelevant banner"], ["Data", "À vista R$", "À vista US$"],
                    ["02/09/1996", "123.09", "121.15"],
                    ["07/07/2017", join_value, "136.18"]]
            d = last_iso.split("-")
            rows.append([f"{d[2]}/{d[1]}/{d[0]}", "1782.18", "348.22"])
            return rows

        real_grid = LIVE._grid  # noqa: SLF001 -- swap the OLE reader for a grid stub
        try:
            LIVE._grid = lambda payload: workbook_rows("2017-08-01", "447.23")
            payload = LIVE._OLE_MAGIC + b"\x00" * LIVE._MIN_BYTES
            why = LIVE.refuse_reason(23, payload)
            assert why and "does not reach past the hole" in why

            LIVE._grid = lambda payload: workbook_rows("2026-07-28", "999.99")
            why = LIVE.refuse_reason(23, payload)
            assert why and "not the same series" in why

            LIVE._grid = lambda payload: workbook_rows("2026-07-28", "447.23")
            assert LIVE.refuse_reason(23, payload) is None
        finally:
            LIVE._grid = real_grid

    def test_the_live_leg_carries_its_license_and_its_never_schedule_posture(self):
        # The CC BY-NC grant and the one-shot posture are part of the LEG, not tribal knowledge.
        assert "CC BY-NC 4.0" in LIVE._LICENSE
        assert "CEPEA" in LIVE._ATTRIBUTION
        assert "cepea.org.br" in LIVE.live_url(23) and "www." not in LIVE.live_url(23)
        assert set(LIVE.CEPEA_LIVE_SERIES) == set(T.CEPEA_INDICATORS)
        from leviathan.common.constants import MIN_RAW_FILE_SIZES

        assert MIN_RAW_FILE_SIZES["cepea_live"] == 100_000

    def test_the_served_capture_is_read_off_the_redirect_and_cross_checked(self):
        class Resp:
            def __init__(self, url, headers):
                self.url, self.headers = url, headers

        target = "http://www.cepea.esalq.usp.br/br/indicador/series/cafe.aspx?id=23"
        agreeing = Resp(f"https://web.archive.org/web/20170708153249id_/{target}",
                        {"Memento-Datetime": "Sat, 08 Jul 2017 15:32:49 GMT"})
        assert WAYBACK.served_capture_ts(agreeing) == "20170708153249"
        # No Memento header: the URL alone still establishes the capture.
        assert WAYBACK.served_capture_ts(Resp(agreeing.url, {})) == "20170708153249"
        # Header and URL disagreeing means the response cannot be trusted at all.
        conflicted = Resp(agreeing.url, {"Memento-Datetime": "Mon, 08 Jun 2025 14:39:48 GMT"})
        with pytest.raises(ValueError, match="disagrees with itself"):
            WAYBACK.served_capture_ts(conflicted)

    def test_the_size_floors_are_wired(self):
        from leviathan.common.constants import MIN_RAW_FILE_SIZES

        assert MIN_RAW_FILE_SIZES["cepea_widget"] == 500
        assert MIN_RAW_FILE_SIZES["cepea_wayback"] == 50_000
