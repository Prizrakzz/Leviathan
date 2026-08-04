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


# ---------------------------------------------------------------------------
# D-PR-19 -- the served-date verdict. The 2026-07-29 hole in one class.
# ---------------------------------------------------------------------------
class TestServedDate:
    def test_the_served_date_is_the_cell_the_transform_reads(self):
        """The verdict must be taken on the SAME fact the row will carry, or the producer and the
        transform can disagree about which session landed."""
        payload = widget(23, date="28/07/2026")
        served = T.served_date_from_widget(payload)
        bronze, _ = T.build_cepea_widget_bronze(payload, indicator_id=23)
        assert served == "2026-07-28" == str(bronze["trade_date"].iloc[0])[:10]

    def test_a_payload_that_cannot_name_its_session_is_refused(self):
        with pytest.raises(ValueError, match="no <tbody>"):
            T.served_date_from_widget(b"<html>Just a moment...</html>")
        undated = _WIDGET_FMT.format(date="", product=_CORN, basis="sc de 60kg",
                                     currency="R$", value="65,22").encode("utf-8")
        with pytest.raises(ValueError, match="no dated row"):
            T.served_date_from_widget(undated)

    def test_the_three_way_verdict(self):
        # Wednesday 2026-07-29 is the measured session. Tuesday 07-28 is one business day behind.
        assert T.classify_served_date("2026-07-29", "2026-07-29") == (T.SERVED_FRESH, 0)
        assert T.classify_served_date("2026-07-28", "2026-07-29") == (T.SERVED_STALE, 1)
        # A Monday judged against the previous Friday: the weekend is not two lost sessions.
        assert T.classify_served_date("2026-07-24", "2026-07-27") == (T.SERVED_STALE, 1)
        # A session that has not happened means the SESSION MODEL is wrong, not the venue.
        verdict, lag = T.classify_served_date("2026-07-30", "2026-07-29")
        assert verdict == T.SERVED_AHEAD and lag == -1

    def test_business_days_skip_the_weekend_in_both_directions(self):
        assert T.business_days_between("2026-07-24", "2026-07-27") == 1     # Fri -> Mon
        assert T.business_days_between("2026-07-27", "2026-07-24") == -1
        assert T.business_days_between("2026-07-29", "2026-07-29") == 0

    def test_the_expected_session_is_read_in_brazil_and_rolls_off_the_weekend(self):
        from datetime import datetime as _dt, timezone as _tz

        # The scheduled fire: 22:30Z Wednesday is 19:30 BRT the SAME day.
        assert T.session_for_capture(_dt(2026, 7, 29, 22, 30, tzinfo=_tz.utc)) == "2026-07-29"
        # A hand-run just after midnight UTC is still the PREVIOUS Brazilian day.
        assert T.session_for_capture(_dt(2026, 7, 30, 1, 0, tzinfo=_tz.utc)) == "2026-07-29"
        # Saturday is not a session anywhere; roll back to Friday. This is a weekend rule, not a
        # holiday calendar -- which day Brazil trades is exactly what this leg refuses to curate.
        assert T.session_for_capture(_dt(2026, 8, 1, 22, 30, tzinfo=_tz.utc)) == "2026-07-31"
        assert T.previous_business_day("2026-08-02") == "2026-07-31"


class TestProducerServedDateGate:
    """The producer half. Everything here is the 2026-07-29 sequence replayed hermetically."""

    @staticmethod
    def _captures(served: dict[int, str], expected: str) -> dict[int, dict]:
        out = {}
        for ind, day in served.items():
            verdict, lag = T.classify_served_date(day, expected)
            out[ind] = {"key": f"k{ind}", "payload": b"", "served_date": day,
                        "verdict": verdict, "lag": lag}
        return out

    def test_a_fresh_group_lands(self):
        caps = self._captures({23: "2026-07-29", 77: "2026-07-29"}, "2026-07-29")
        land, disp, _ = FETCH.group_verdict(caps, expected_session="2026-07-29")
        assert land is True and disp == "land"

    def test_a_stale_re_serve_is_withheld_and_that_is_the_2026_07_29_defect(self):
        """MEASURED: the 17:00Z manual run served 28/07/2026 against session 2026-07-29 and landed
        anyway -- which is what made the 22:30Z scheduled fire a no-op (raw_exists short-circuits on
        the CAPTURE-date key). Withholding leaves the key free for that fire."""
        caps = self._captures({23: "2026-07-28", 77: "2026-07-28"}, "2026-07-29")
        land, disp, why = FETCH.group_verdict(caps, expected_session="2026-07-29")
        assert land is False and disp == "withhold_stale"
        assert "2026-07-28" in why and "2026-07-29" in why

    def test_the_withhold_is_both_indicators_or_neither(self):
        """Trap (ii): the per-day silver floor is an EQUALITY. A rule that withheld one cash
        reference and landed the other would turn a clean day into a floor violation."""
        caps = self._captures({23: "2026-07-29", 77: "2026-07-28"}, "2026-07-29")
        land, disp, why = FETCH.group_verdict(caps, expected_session="2026-07-29")
        assert land is False and disp == "refuse_split", "a split capture must never half-land"
        assert "disagree" in why

    def test_a_session_that_has_not_happened_is_a_hard_refusal(self):
        caps = self._captures({23: "2026-07-30", 77: "2026-07-30"}, "2026-07-29")
        land, disp, _ = FETCH.group_verdict(caps, expected_session="2026-07-29")
        assert land is False and disp == "refuse_ahead"

    def test_land_and_declare_remains_available_as_the_fallback(self):
        """The ratified B2 shape: land the re-serve, but say so in raw_meta."""
        caps = self._captures({23: "2026-07-28", 77: "2026-07-28"}, "2026-07-29")
        land, disp, _ = FETCH.group_verdict(caps, expected_session="2026-07-29",
                                            on_stale="land")
        assert land is True and disp == "land_declared_stale"

    def test_a_holiday_takes_the_withhold_path_not_a_failure(self, monkeypatch):
        """A hard fail on served != expected would red ~10 Brazilian holidays a year. The exit code
        is what separates 'nothing was owed' from 'something broke'."""
        rc, landed = self._run(monkeypatch, served="27/07/2026", expected="2026-07-28")
        assert rc == 0, "a holiday must not fail the leg"
        assert landed == [], "a re-serve carries no new session, so nothing is landed"

    def test_an_early_capture_lands_nothing_and_exits_clean(self, monkeypatch):
        rc, landed = self._run(monkeypatch, served="28/07/2026", expected="2026-07-29")
        assert rc == 0 and landed == []

    def test_a_fresh_capture_lands_both_with_the_licence_and_the_declaration(self, monkeypatch):
        """D-PR-20 + D-PR-19 in one record: the CC BY-NC grant travels with the bytes on the DAILY
        route, and the object states which session it serves."""
        rc, landed = self._run(monkeypatch, served="29/07/2026", expected="2026-07-29")
        assert rc == 0 and len(landed) == 2
        for _key, extra in landed:
            assert extra["license"] == FETCH._LICENSE and "CC BY-NC 4.0" in extra["license"]
            assert extra["attribution"] == FETCH._ATTRIBUTION
            assert extra["served_date"] == "2026-07-29"
            assert extra["expected_session"] == "2026-07-29"
            assert extra["served_lag_business_days"] == 0
            assert extra["served_verdict"] == T.SERVED_FRESH
            assert "NEVER schedule" not in extra["posture"], \
                "this IS the scheduled route; the one-shot posture belongs to the apex leg"

    def test_the_ahead_case_lands_nothing_and_FAILS(self, monkeypatch):
        rc, landed = self._run(monkeypatch, served="30/07/2026", expected="2026-07-29")
        assert rc == 1 and landed == []

    def test_the_daily_licence_string_is_the_same_object_as_the_one_shot_s(self):
        """Same data, same licence, two routes. The asymmetry D-PR-20 closes was that only one of
        them recorded it -- this pins them so they cannot drift apart again."""
        assert FETCH._LICENSE == LIVE._LICENSE
        assert FETCH._ATTRIBUTION == LIVE._ATTRIBUTION
        assert FETCH._LICENSE == T.CEPEA_LICENSE

    @staticmethod
    def _run(monkeypatch, *, served: str, expected: str, on_stale: str = "withhold"):
        """Drive ``main()`` with S3 and HTTP stubbed. Returns ``(exit_code, [(key, extra), ...])``."""
        landed: list[tuple[str, dict]] = []

        monkeypatch.setattr(FETCH, "raw_exists", lambda *a, **k: False)
        monkeypatch.setattr(FETCH, "fetch_indicator",
                            lambda ind, **k: widget(ind, date=served,
                                                    value="1.782,18" if ind == 23 else "65,22"))
        monkeypatch.setattr(FETCH, "land_bytes",
                            lambda bucket, key, data, **kw: landed.append((key, kw.get("extra"))))
        monkeypatch.setattr(FETCH.time, "sleep", lambda *_a, **_k: None)
        rc = FETCH.main(["--bucket", "b", "--aws-region", "us-east-1", "--sleep", "0",
                         "--expected-session", expected, "--on-stale", on_stale])
        return rc, landed


# ---------------------------------------------------------------------------
# D-PR-19 / D-PR-46 / D-PR-48 -- the silver-side session-gap assertion
# ---------------------------------------------------------------------------
class TestSessionGap:
    @staticmethod
    def _frame(days_by_slug: dict[str, list[str]]) -> pd.DataFrame:
        frames = []
        for ind, slug in T.CEPEA_INDICATORS.items():
            for day in days_by_slug.get(slug, []):
                d, m, y = day[8:10], day[5:7], day[:4]
                frames.append(T.build_cepea_widget_bronze(
                    widget(ind, date=f"{d}/{m}/{y}",
                           value="1.782,18" if ind == 23 else "65,22"), indicator_id=ind)[0])
        return S.build_cepea_silver(pd.concat(frames, ignore_index=True))

    @staticmethod
    def _both(days: list[str]) -> pd.DataFrame:
        return TestSessionGap._frame({slug: days for slug in T.CEPEA_INDICATORS.values()})

    def test_a_lost_session_is_named(self):
        """The 07-29 shape: the venue traded Wednesday, CEPEA published nothing."""
        week = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"]
        df = self._both(["2026-07-27", "2026-07-28", "2026-07-30"])
        gaps = S.cepea_session_gaps(df, venue_sessions=week, waived=frozenset())
        assert len(gaps) == 1 and gaps[0].startswith("2026-07-29")
        assert "lost session" in gaps[0]

    def test_a_holiday_does_not_false_fire(self):
        """THE acceptance case. On a Brazilian holiday the venue does not trade either, so the day
        is simply absent from the session set and there is no hole to report. This is why the
        assertion is defined against venue sessions and not against business days."""
        df = self._both(["2026-07-27", "2026-07-28", "2026-07-30"])
        sessions_without_the_holiday = ["2026-07-27", "2026-07-28", "2026-07-30"]
        assert S.cepea_session_gaps(df, venue_sessions=sessions_without_the_holiday) == []

    def test_a_bare_business_day_calendar_is_what_would_have_false_fired(self):
        """Kept as the counter-example the design turns on: 2026-07-29 is a Wednesday, so a
        business-day contiguity test cannot tell the holiday case from the lost-session case."""
        df = self._both(["2026-07-27", "2026-07-28", "2026-07-30"])
        business_days = [str(d)[:10] for d in pd.bdate_range("2026-07-27", "2026-07-30")]
        assert S.cepea_session_gaps(df, venue_sessions=business_days, waived=frozenset())

    def test_the_known_hole_is_waived_so_the_wave_ships_no_permanent_red(self):
        """D-PR-48. 2026-07-29 is measured, declared and irrecoverable from the scheduled route;
        without the waiver every fire whose window touches July would red forever."""
        assert "2026-07-29" in S.CEPEA_WAIVED_SESSIONS
        df = self._both(["2026-07-27", "2026-07-28", "2026-07-30"])
        week = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"]
        assert S.cepea_session_gaps(df, venue_sessions=week) == []

    def test_the_check_is_window_only_and_never_reaches_behind_the_frame(self):
        """A frontier-relative check cannot be reddened by history it did not load."""
        df = self._both(["2026-07-30", "2026-07-31"])
        july = [str(d)[:10] for d in pd.bdate_range("2026-07-01", "2026-07-31")]
        assert S.cepea_session_gaps(df, venue_sessions=july, waived=frozenset()) == []

    def test_a_half_day_names_the_missing_indicator(self):
        """Trap (ii) from the other side: the equality floor knows the day is short, not which
        cash reference vanished."""
        df = self._frame({"brazilian_arabica_coffee": ["2026-07-30", "2026-07-31"],
                          "campinas_corn_reference_bmf": ["2026-07-30"]})
        gaps = S.cepea_session_gaps(df, venue_sessions=["2026-07-30", "2026-07-31"])
        assert len(gaps) == 1 and gaps[0].startswith("2026-07-31")
        assert "HALF day" in gaps[0] and "campinas_corn_reference_bmf" in gaps[0]

    def test_without_a_session_calendar_the_assertion_is_inert_and_says_so(self, caplog):
        """Refusing to guess is a no-op. A no-op that announces itself is recoverable; ten false
        reds a year is not."""
        df = self._both(["2026-07-27", "2026-07-30"])
        with caplog.at_level("WARNING"):
            assert S.cepea_session_gaps(df, venue_sessions=None) == []
        assert any("INERT" in r.message for r in caplog.records)

    def test_the_ratified_calendar_slug_is_this_leg_s_own_output(self):
        """D-PR-46 names silver_futures_prices / campinas_corn_reference_bmf as the session
        calendar. That slug IS CEPEA indicator 77, so a day CEPEA lost is missing from both sides
        of the comparison and cancels out. Pinned here so a GREEN report is never read as coverage
        until an independent Brazilian venue series names the calendar."""
        conflicts = S.session_calendar_conflicts()
        assert conflicts and "cancels out" in conflicts[0]
        assert S.session_calendar_conflicts("some_independent_b3_series") == []
