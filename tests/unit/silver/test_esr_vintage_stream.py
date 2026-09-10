"""LEVIATHAN_ESR_VINTAGE_STREAM -- the pins for per-vintage frame streaming (ESR compact producer).

WHAT THIS DECK IS FOR.  ``jobs/batch/bronze_to_silver_esr_task.py --vintage-mode all`` holds every
per-file frame AND the ``pd.concat`` copy at once.  MEASURED: the estate paid for that twice with
exit 137 ("container killed due to memory usage") -- 2026-09-03T14:05:43Z on
``leviathan-dev-esr-bronze-to-silver:7`` (2 vCPU / 4,096 MiB) and 2026-09-04T08:46:27Z on
``leviathan-dev-silver-publisher-runner:35`` (1 vCPU / 4,096 MiB).  At the post-OOM 12,288 MiB the
concat peak is 8.98 GiB = 74.8 % today; weekly bronze growth of 1.353 GiB of concat peak puts the
2026-09-17 fire at 97.4 % and the 2026-09-24 fire at 108.6 % -- the fire the arithmetic says cannot
complete.  The mechanism streams the FRAMES, accumulates the OBJECTS and calls the UNCHANGED
publisher ONCE.

THE FIXTURE (built here, deterministically, from the real transforms -- no binary fixture files):
3 as_of vintages x 2 commodities x 2 market years = 12 bronze objects.

    vintages       20260806, 20260813, 20260820  (all Thursdays -- FAS ESR's release weekday)
    commodities    401 corn_cbot, 801 soybeans_cbot
    market years   2024 CLOSED (tape stops 2025-08-30) and 2025 OPEN (tape at the release week)
    the defect     401/MY2025 REGRESSES at the third vintage: max week_ending 2026-08-08 -> 2026-05-16

Every bronze object is produced by the REAL ``transform_esr_json_to_bronze`` from synthetic FAS
JSON, and read back through the REAL ``transform_esr_bronze_to_silver``, so these pins measure the
production path and not a mock of it.

THE ORDER SHAPE THIS DECK PINS, and the choice it records.  Design 2.7 offers two shapes for move 1
(collect frames in SUBMIT order rather than ``as_completed`` order).  Applied ALWAYS it rewrites 89
of 214 canonical bodies and the flag-off path stops being byte-identical to HEAD.  Applied ONLY on
the flag-on path, ``LEVIATHAN_ESR_VINTAGE_STREAM=off`` runs HEAD's algorithm character for
character -- which is the estate's own convention for a dark producer lever
(``jobs/batch/futures_eod_task.py:459-461``: "restore the pre-Lane-A arithmetic BYTE FOR BYTE, not
nearly").  THIS BUILD TAKES THE GATED SHAPE, and the deck pins all three consequences:

  * flag-off == HEAD, under an IDENTICAL completion order, whatever that order is;
  * flag-on  == flag-off, when HEAD's completion order happens to equal submit order;
  * flag-on  != flag-off in BYTES (and only in bytes) when it does not -- the named, expected
    rewrite the orchestrator pays once at sequencing step 2.

HEAD is transcribed inline (``_head_build_objects``) rather than fetched with ``git show``: once
this change is committed, ``HEAD:jobs/batch/bronze_to_silver_esr_task.py`` IS this change and a
git-based comparison would be vacuously self-equal.  The one-time real comparison against
``git show HEAD:...`` was run in a scratch copy before the commit; this transcription is what keeps
it pinned afterwards.

AWS-free: an in-memory object store and a deterministic single-threaded pool, so completion order
is a test INPUT rather than thread timing.  The F002 network guard never fires.
"""
from __future__ import annotations

import ast
import datetime
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest
from leviathan.silver.publisher import ManifestState
from leviathan.transforms.raw_to_bronze.usda_esr import transform_esr_json_to_bronze

from tests.unit.silver.conftest import canonical_authorization, dryrun_authorization

_REPO = Path(__file__).resolve().parents[3]
_PRODUCER = _REPO / "jobs" / "batch" / "bronze_to_silver_esr_task.py"
_BRONZE_TASK = _REPO / "jobs" / "batch" / "esr_task.py"
BUCKET = "leviathan-test"
REGION = "us-east-1"
BRONZE_PREFIX = "bronze/production/source=usda_esr/"

VINTAGES = ("20260806", "20260813", "20260820")
CODES = ((401, "corn_cbot"), (801, "soybeans_cbot"))
CLOSED_MY, OPEN_MY = 2024, 2025


def _load(path: Path, name: str):
    """Load a standalone job module by path.

    The module is registered in ``sys.modules`` BEFORE exec: ``esr_task`` defines dataclasses, and
    ``dataclasses._is_type`` resolves a string annotation through ``sys.modules[cls.__module__]``.
    Without the registration that lookup returns None and every dataclass in the module explodes at
    definition time -- a failure of the loader, not of the code under test.
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def prod():
    return _load(_PRODUCER, "b2s_esr_task_stream")


@pytest.fixture(scope="module")
def bronze_task():
    return _load(_BRONZE_TASK, "esr_task_tripwire")


# ---------------------------------------------------------------------------
# The fixture bronze set.
# ---------------------------------------------------------------------------
def _weeks(last: datetime.date, n: int = 4) -> list[datetime.date]:
    """*n* consecutive ESR weeks ENDING at *last* (Saturdays), oldest first."""
    return [last - datetime.timedelta(days=7 * i) for i in range(n - 1, -1, -1)]


def _max_week_for(code: int, market_year: int, as_of: str) -> datetime.date:
    """The tape each fixture object ends on -- and the ONE planted defect.

    CLOSED MY2024 stops in Aug 2025: ~1 year behind every release, which is what a real closed
    marketing year looks like and is exactly the shape design F1 measured (25 of 64 raw keys
    refused by a FLAT lag rule, every one of them a closed MY).
    OPEN MY2025 sits at the release week, EXCEPT corn at the third vintage, which regresses --
    the fixture analogue of corn 401/MY2026 going 2026-08-27 -> 2026-05-14 between the
    ``as_of=20260903`` and ``as_of=20260904`` bronze vintages built from ETag-identical raw.
    """
    if market_year == CLOSED_MY:
        return datetime.date(2025, 8, 30)
    release = datetime.date(int(as_of[:4]), int(as_of[4:6]), int(as_of[6:8]))
    if code == 401 and as_of == VINTAGES[2]:
        return datetime.date(2026, 5, 16)          # THE PLANTED REGRESSION
    return release - datetime.timedelta(days=6)    # the Saturday before a Thursday release


def _raw_json(code: int, market_year: int, as_of: str) -> bytes:
    """Synthetic FAS ESR payload. Values are a deterministic function of the keys -- no RNG, so a
    body hash is reproducible across runs and machines."""
    records = []
    for week in _weeks(_max_week_for(code, market_year, as_of)):
        for country in (351, 1220):
            seed = (code + market_year + country + week.toordinal()) % 977
            records.append({
                "commodityCode": code,
                "countryCode": country,
                "marketYear": market_year,
                "weekEndingDate": week.isoformat(),
                "unitId": 1,
                "outstandingSales": float(seed * 10),
                "weeklyExports": float(seed * 2),
                "grossNewSales": float(seed * 3),
                "changes": float(seed),
                "accumulatedExports": float(seed * 4),
                "currentMYNetSales": float(seed * 5),
                "currentMYTotalCommitment": float(seed * 6),
                "nextMYOutstandingSales": float(seed * 7),
                "nextMYNetSales": float(seed * 8),
            })
    return json.dumps(records).encode("utf-8")


def _bronze_key(code: int, market_year: int, as_of: str) -> str:
    return (f"{BRONZE_PREFIX}commodity_code={code}/market_year={market_year}/"
            f"as_of={as_of}/part-000.parquet")


@pytest.fixture(scope="module")
def bronze_store() -> dict[str, bytes]:
    """{bronze key -> parquet bytes}, built through the REAL raw->bronze transform."""
    store: dict[str, bytes] = {}
    for as_of in VINTAGES:
        for code, _slug in CODES:
            for market_year in (CLOSED_MY, OPEN_MY):
                df = transform_esr_json_to_bronze(
                    _raw_json(code, market_year, as_of),
                    commodity_code=code, market_year=market_year,
                    as_of_date=as_of, ingest_date="2026-08-21",
                )
                buf = io.BytesIO()
                df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
                store[_bronze_key(code, market_year, as_of)] = buf.getvalue()
    return store


# ---------------------------------------------------------------------------
# A deterministic pool: completion order becomes a test INPUT, not thread timing.
# ---------------------------------------------------------------------------
class _ImmediateFuture:
    def __init__(self, value):
        self._value = value

    def result(self, timeout=None):
        return self._value


class _DeterministicPool:
    def __init__(self, max_workers=None):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args, **kwargs):
        return _ImmediateFuture(fn(*args, **kwargs))


def _as_completed_in(order: str):
    """Return an ``as_completed`` stand-in yielding futures in *order*.

    ``submit``   -- completion order == submit order (the lucky case).
    ``reverse``  -- the pathological case.  Measured on the live surface, 89 of 214 canonical
                    objects (41.6 %) sit in an order only thread timing explains, so this is not a
                    hypothetical.
    """
    def _as_completed(futures_map, timeout=None):
        futures = list(futures_map)          # dict preserves insertion == submit order
        return futures if order == "submit" else list(reversed(futures))
    return _as_completed


@pytest.fixture
def wired(prod, bronze_store, monkeypatch):
    """Point the producer's S3 helpers at the in-memory bronze set; keep both transforms real."""
    monkeypatch.setattr(prod, "get_thread_local_s3_client", lambda region: object())
    monkeypatch.setattr(prod, "s3_download_with_retry",
                        lambda bucket, key, client=None: bronze_store[key])
    monkeypatch.setattr(prod, "ThreadPoolExecutor", _DeterministicPool)
    return prod


def _digest(objects) -> list[tuple]:
    """THE PIN'S UNIT: (canonical_key, sha256(body), row_count, null_metrics), element for element."""
    return [(o.canonical_key, hashlib.sha256(o.body).hexdigest(), o.row_count,
             tuple(sorted(o.null_metrics.items()))) for o in objects]


def _keys(bronze_store) -> list[str]:
    return sorted(bronze_store)


# ---------------------------------------------------------------------------
# Structural helpers. The wiring claims in this deck are about the SHAPE of a call site, so they
# are read off the parse tree rather than matched as substrings: a substring pin dies to a rename,
# and every one of these sentences must survive one.
# ---------------------------------------------------------------------------
def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _call_name(node: ast.AST) -> str | None:
    """``f(...)`` -> "f"; ``obj.f(...)`` -> "f"; anything else -> None."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _calls_to(tree: ast.AST, name: str) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if _call_name(n) == name]


def _function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found -- the wiring pin cannot be evaluated")


def _module_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# HEAD, transcribed. jobs/batch/bronze_to_silver_esr_task.py:361-381 at ff7923d4/5bc5837e.
# ---------------------------------------------------------------------------
def _head_build_objects(prod, keys_to_read, vintage_mode):
    """HEAD's whole-history path, verbatim in behaviour: one pool over every key, results collected
    in ``as_completed`` order, one ``pd.concat(ignore_index=True)``, one ``build_staged_objects``."""
    frames = []
    with prod.ThreadPoolExecutor(max_workers=prod._WORKERS) as pool:
        futures = {pool.submit(prod._read_and_transform, k, BUCKET, REGION): k
                   for k in keys_to_read}
        for fut in prod.as_completed(futures):
            result = fut.result()
            if result is not None and not result.empty:
                frames.append(result)
    combined = pd.concat(frames, ignore_index=True)
    return prod.build_staged_objects(combined, vintage_mode)


def _build(prod, monkeypatch, bronze_store, *, stream: bool, order: str,
           vintage_mode=None, head=False):
    monkeypatch.setattr(prod, "as_completed", _as_completed_in(order))
    mode = vintage_mode or prod.VINTAGE_ALL
    keys = _keys(bronze_store)
    if head:
        return _head_build_objects(prod, keys, mode)
    return prod.build_objects(keys, BUCKET, REGION, mode, stream=stream)


# ===========================================================================
# PIN 1 -- flag OFF is HEAD, byte for byte, under any completion order.
# ===========================================================================
class TestFlagOffIsHead:
    @pytest.mark.parametrize("order", ["submit", "reverse"])
    def test_flag_off_equals_head_element_for_element(self, wired, monkeypatch, bronze_store,
                                                      order):
        """THE ROLLBACK GUARANTEE. Same completion order in, same objects out -- same canonical
        keys, same sha256 bodies, same row counts, same null metrics, same ORDER of the list (which
        is also the manifest's inputs/outputs/partition_actions order)."""
        off = _build(wired, monkeypatch, bronze_store, stream=False, order=order)
        head = _build(wired, monkeypatch, bronze_store, stream=False, order=order, head=True)
        assert _digest(off) == _digest(head)
        assert len(off) == len(VINTAGES) * len(CODES)      # 3 vintages x 2 slugs = 6 objects

    def test_the_two_completion_orders_really_do_produce_different_bytes(
            self, wired, monkeypatch, bronze_store):
        """The fixture is not accidentally order-insensitive. If this ever passes trivially, PIN 1
        stops proving anything and PIN 3's named byte move stops being measurable."""
        submit_order = _build(wired, monkeypatch, bronze_store, stream=False, order="submit")
        reverse_order = _build(wired, monkeypatch, bronze_store, stream=False, order="reverse")
        assert [d[0] for d in _digest(submit_order)] == [d[0] for d in _digest(reverse_order)]
        assert [d[2] for d in _digest(submit_order)] == [d[2] for d in _digest(reverse_order)]
        moved = [a[0] for a, b in zip(_digest(submit_order), _digest(reverse_order)) if a[1] != b[1]]
        assert moved, ("HEAD's completion order changes no fixture body -- the fixture no longer "
                       "reproduces the 89-of-214 row-order accident this deck exists to pin.")


# ===========================================================================
# PIN 2 -- flag ON is a pure memory change: zero data change, object by object.
# ===========================================================================
class TestFlagOnIsAPureMemoryChange:
    def test_streamed_objects_equal_the_whole_history_objects(self, wired, monkeypatch,
                                                              bronze_store):
        """Against the flag-off run whose completion order HAPPENED to be submit order -- i.e.
        against the post-move-1 baseline the orchestrator captures at sequencing step 2."""
        off = _build(wired, monkeypatch, bronze_store, stream=False, order="submit")
        on = _build(wired, monkeypatch, bronze_store, stream=True, order="submit")
        assert _digest(on) == _digest(off)

    def test_against_a_scrambled_flag_off_only_the_BYTES_move(self, wired, monkeypatch,
                                                              bronze_store):
        """THE NAMED BYTE MOVE, and its exact boundary.

        Against a flag-off run whose completion order was NOT submit order, the streamed objects
        carry the same canonical keys, the same row counts and the same null metrics -- and some
        bodies hash differently, because the rows inside them are in a different (now deterministic,
        ascending market_year) order. That is design 2.7 move 1: on the live surface it rewrites 89
        of 214 canonical objects, which is why the order fix rides the flag here and why the
        baseline is captured AFTER it lands, never against today's accidentally-ordered bodies.
        """
        off = _build(wired, monkeypatch, bronze_store, stream=False, order="reverse")
        on = _build(wired, monkeypatch, bronze_store, stream=True, order="reverse")
        assert [(d[0], d[2], d[3]) for d in _digest(on)] == [(d[0], d[2], d[3]) for d in _digest(off)]
        rewritten = [a[0] for a, b in zip(_digest(on), _digest(off)) if a[1] != b[1]]
        assert rewritten, "the fixture must exhibit the rewrite, or the pin proves nothing"

    def test_streaming_is_stable_across_completion_orders(self, wired, monkeypatch, bronze_store):
        """Flag ON does not depend on thread timing at all: that is what move 1 buys."""
        a = _build(wired, monkeypatch, bronze_store, stream=True, order="submit")
        b = _build(wired, monkeypatch, bronze_store, stream=True, order="reverse")
        assert _digest(a) == _digest(b)

    def test_object_order_is_canonical_key_order(self, wired, monkeypatch, bronze_store):
        on = _build(wired, monkeypatch, bronze_store, stream=True, order="reverse")
        keys = [o.canonical_key for o in on]
        assert keys == sorted(keys)


# ===========================================================================
# PIN 3 -- vintage parity: per-vintage counts equal the whole-history counts.
# ===========================================================================
class TestVintageParity:
    def test_row_counts_per_vintage_and_in_total(self, wired, monkeypatch, bronze_store):
        off = _build(wired, monkeypatch, bronze_store, stream=False, order="submit")
        on = _build(wired, monkeypatch, bronze_store, stream=True, order="submit")
        by_off = {o.canonical_key: o.row_count for o in off}
        by_on = {o.canonical_key: o.row_count for o in on}
        assert by_on == by_off
        assert sum(by_on.values()) == sum(by_off.values())
        # and the whole frame is partitioned with no loss: 3 vintages x 2 slugs, each slug carrying
        # BOTH market years' rows (2 MY x 4 weeks x 2 countries = 16).
        assert set(by_on.values()) == {16}

    def test_each_object_holds_exactly_its_slug_and_vintage(self, wired, monkeypatch,
                                                            bronze_store):
        on = _build(wired, monkeypatch, bronze_store, stream=True, order="submit")
        for obj in on:
            frame = pq.read_table(io.BytesIO(obj.body)).to_pandas()
            assert set(frame["as_of_date"].unique()) == {obj.partition_values[1]}
            assert set(frame["commodity_name"].unique()) == {obj.partition_values[0]}
            assert sorted(frame["market_year"].unique()) == [CLOSED_MY, OPEN_MY]


# ===========================================================================
# PIN 4 -- the memory pin: peak resident frame is ONE vintage, never the sum.
# ===========================================================================
class TestMemoryPin:
    def test_peak_frame_rows_is_the_largest_single_vintage_not_the_sum(
            self, wired, monkeypatch, bronze_store):
        """The instrument the whole change is judged on, in rows rather than bytes so CI can hold
        it. Flag OFF the resident frame is the WHOLE history; flag ON it is one vintage."""
        _build(wired, monkeypatch, bronze_store, stream=False, order="submit")
        whole_history_rows = wired.LAST_PEAK_FRAME_ROWS
        _build(wired, monkeypatch, bronze_store, stream=True, order="submit")
        streamed_peak_rows = wired.LAST_PEAK_FRAME_ROWS

        per_vintage = len(CODES) * 2 * 4 * 2          # 2 slugs x 2 MY x 4 weeks x 2 countries
        assert whole_history_rows == per_vintage * len(VINTAGES)
        assert streamed_peak_rows == per_vintage
        assert streamed_peak_rows * len(VINTAGES) == whole_history_rows

    def test_the_peak_probe_logs_and_never_raises(self, wired):
        """The instrument ships ALWAYS ON, so it must be incapable of failing a run: no cgroup file
        on this platform, no ru_maxrss on Windows, still one clean report."""
        probe = wired.PeakMemoryProbe(interval=0.01)
        probe.sample()
        probe.report()
        probe.report()          # idempotent -- atexit plus an explicit call must not double-log
        assert probe.samples >= 1


# ===========================================================================
# PIN 5 -- one manifest, publisher untouched, partition_actions covers every object.
# ===========================================================================
class TestOneManifest:
    def _table_input(self):
        return {
            "Name": "silver_esr_compact",
            "StorageDescriptor": {
                "Columns": [{"Name": "commodity_code", "Type": "smallint"}],
                "Location": f"s3://{BUCKET}/silver/esr",
                "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                "SerdeInfo": {"SerializationLibrary": "serde", "Parameters": {}},
                "Parameters": {},
            },
        }

    def test_streamed_objects_publish_through_exactly_one_run(self, wired, monkeypatch,
                                                              bronze_store, fake_glue, fake_s3):
        """Design 2.1's load-bearing claim: ``publisher.py`` is not touched and ``run()`` is called
        ONCE with ALL objects, so PartitionPublisher._repair still walks EVERY partition and the
        post-ALTER descriptor self-heal survives. If a future refactor streams the PUBLISH instead
        of the frames, ``partition_actions`` collapses to the last vintage and this fails."""
        fake_glue.tables["silver_esr_compact"] = self._table_input()
        objects = _build(wired, monkeypatch, bronze_store, stream=True, order="submit")

        calls = []
        real_run = wired.ShadowPublisher.run

        def _counting_run(self, objs):
            calls.append(len(objs))
            return real_run(self, objs)

        monkeypatch.setattr(wired.ShadowPublisher, "run", _counting_run)
        manifest = wired.publish_esr_compact(
            objects, bucket=BUCKET, s3_client=fake_s3, glue_client=fake_glue,
            auth=canonical_authorization(), vintage_mode=wired.VINTAGE_ALL,
        )

        assert calls == [len(objects)], "exactly ONE run(), carrying EVERY object"
        assert manifest.state == ManifestState.CERTIFIED
        assert len(manifest.partition_actions) == len(objects)
        assert len(manifest.inputs) == len(objects)
        assert len(manifest.outputs) == len(objects)
        assert len(manifest.row_key_null_metrics) == len(objects)
        # every (slug, as_of) partition registered -- 3 vintages x 2 slugs
        assert len({tuple(a["values"]) for a in manifest.partition_actions}) == len(objects)
        manifests = [k for k in fake_s3.keys() if "/_manifests/" in k]
        assert manifests == ["silver/esr/_manifests/silver_esr_compact-all.json"], (
            "ONE manifest, at the constant key scripts/ops/esr_netcommitment_runbook.py:156 "
            "hardcodes and verdict() reads")

    def test_run_id_default_is_unchanged(self, wired, monkeypatch, bronze_store, fake_s3):
        seen = {}
        real = wired.ShadowPublisher
        monkeypatch.setattr(wired, "ShadowPublisher",
                            lambda **kw: (seen.update(kw), real(**kw))[1])
        objects = _build(wired, monkeypatch, bronze_store, stream=True, order="submit")
        wired.publish_esr_compact(
            objects, bucket=BUCKET, s3_client=fake_s3, glue_client=None,
            auth=dryrun_authorization(), vintage_mode=wired.VINTAGE_ALL,
        )
        assert seen["run_id"] == "silver_esr_compact-all"
        assert seen["reconcile_schema_widen"] is True


# ===========================================================================
# PIN 6 -- the fences.
# ===========================================================================
class TestFences:
    def test_flag_default_is_off(self, prod):
        assert prod.vintage_stream_enabled({}) is False
        assert prod.vintage_stream_enabled({"LEVIATHAN_ESR_VINTAGE_STREAM": ""}) is False
        assert prod.vintage_stream_enabled({"LEVIATHAN_ESR_VINTAGE_STREAM": "off"}) is False
        for value in ("on", "ON", " on ", "1", "true", "yes"):
            assert prod.vintage_stream_enabled({"LEVIATHAN_ESR_VINTAGE_STREAM": value}) is True

    def test_streaming_is_inert_under_vintage_mode_latest(self, wired, monkeypatch, bronze_store):
        """THE FENCE. Under ``latest`` one object per slug is built from keys spanning several
        as_of vintages, so a per-vintage loop would mint the SAME canonical key once per vintage and
        the publisher's second copy_object would silently overwrite the first. The flag falls back
        instead, and flag-on == flag-off under ``latest``, byte for byte."""
        latest_keys = sorted(
            k for k in bronze_store
            if f"as_of={VINTAGES[-1]}" in k or f"as_of={VINTAGES[0]}" in k
        )
        monkeypatch.setattr(wired, "as_completed", _as_completed_in("submit"))
        off = wired.build_objects(latest_keys, BUCKET, REGION, wired.VINTAGE_LATEST, stream=False)
        on = wired.build_objects(latest_keys, BUCKET, REGION, wired.VINTAGE_LATEST, stream=True)
        assert _digest(on) == _digest(off)
        assert len({o.canonical_key for o in on}) == len(on) == len(CODES)

    def test_a_vintage_collision_is_refused_not_overwritten(self, prod):
        """If a bronze key's ``as_of=`` segment ever disagreed with its frame's ``as_of_date``
        column, two vintage groups would mint the same canonical key and the second promote would
        win silently. Named and refused."""
        made = prod.StagedObject(
            canonical_key="silver/esr/commodity=corn_cbot/as_of=20260806/part-000.parquet",
            body=b"x", partition_values=["corn_cbot", "20260806"], row_count=1, null_metrics={},
        )
        with pytest.raises(prod.VintageCollisionError, match="more than one as_of vintage"):
            prod._assert_no_vintage_collision([made, made])

    def test_build_objects_WIRES_the_collision_guard(self, prod, bronze_store, monkeypatch):
        """REVERT-TO-RED, and the hole this deck shipped with. The test above proves the guard
        REFUSES; nothing proved ``build_objects`` CALLS it -- replacing
        ``_assert_no_vintage_collision(objects)`` with ``pass`` left all 31 tests green, so the
        flag-on path's only protection against silent row loss was unpinned at exactly the line a
        refactor deletes it from. Four other mutants WERE caught (un-gating ``submit_order`` on the
        flag-off branch, accumulating instead of ``max()`` in the peak, dropping the reindex
        refusal, flipping the flag default); this one was not.

        The collision is BUILT, not mocked: corn/MY2025's vintage-0 bronze is ALSO filed under the
        vintage-1 ``as_of=`` key segment. The streaming loop groups by the KEY segment while
        ``build_staged_objects`` mints the canonical key from the frame's own ``as_of_date``
        COLUMN, so group v1 and group v0 both mint ``commodity=corn_cbot/as_of=<v0>`` and the
        publisher's second ``copy_object`` would silently overwrite the first."""
        misfiled = dict(bronze_store)
        misfiled[_bronze_key(401, OPEN_MY, VINTAGES[1])] = \
            bronze_store[_bronze_key(401, OPEN_MY, VINTAGES[0])]
        monkeypatch.setattr(prod, "get_thread_local_s3_client", lambda region: object())
        monkeypatch.setattr(prod, "s3_download_with_retry",
                            lambda bucket, key, client=None: misfiled[key])
        monkeypatch.setattr(prod, "ThreadPoolExecutor", _DeterministicPool)
        monkeypatch.setattr(prod, "as_completed", _as_completed_in("submit"))
        keys = sorted(misfiled)

        with pytest.raises(prod.VintageCollisionError) as excinfo:
            prod.build_objects(keys, BUCKET, REGION, prod.VINTAGE_ALL, stream=True)
        assert f"as_of={VINTAGES[0]}" in str(excinfo.value)
        assert "corn_cbot" in str(excinfo.value)

        # ARMING NOTE, pinned rather than written down: the two arms diverge in FAILURE MODE, not
        # only in memory. On the SAME bronze condition flag OFF mints no duplicate key at all --
        # the whole-history concat merges the duplicated rows into ONE object and publishes it.
        # Arming the flag converts a silent data condition into a hard weekly-fire failure, which
        # is the designed fail-closed behaviour and is what the orchestrator is buying.
        off = prod.build_objects(keys, BUCKET, REGION, prod.VINTAGE_ALL, stream=False)
        assert len({o.canonical_key for o in off}) == len(off)

    def test_the_collision_guard_sees_every_object_not_a_subset(
            self, wired, monkeypatch, bronze_store):
        """A guard called on one vintage's objects would pass a cross-vintage collision. It runs
        ONCE, over the whole accumulated set, before the sort."""
        seen: list[list] = []
        real = wired._assert_no_vintage_collision

        def _recording(objects):
            seen.append(list(objects))
            return real(objects)

        monkeypatch.setattr(wired, "_assert_no_vintage_collision", _recording)
        objects = _build(wired, monkeypatch, bronze_store, stream=True, order="submit")
        assert len(seen) == 1, "one guard call, over the accumulation -- not one per vintage"
        assert sorted(o.canonical_key for o in seen[0]) == \
            sorted(o.canonical_key for o in objects)

    def test_emitted_columns_match_what_the_transform_actually_emits(self, prod, bronze_store):
        """EMITTED_COLUMNS is the streaming loop's reindex target. A column the transform emits and
        this list omits would be DROPPED; the reindex refuses rather than drops, so this pin is what
        keeps that refusal from becoming a production failure."""
        key = _bronze_key(401, OPEN_MY, VINTAGES[0])
        frame = pq.read_table(io.BytesIO(bronze_store[key])).to_pandas()
        from leviathan.transforms.bronze_to_silver.usda_esr import transform_esr_bronze_to_silver
        silver = transform_esr_bronze_to_silver(frame, OPEN_MY)
        assert list(silver.columns) == list(prod.EMITTED_COLUMNS)

    def test_reindex_refuses_an_undeclared_column_rather_than_dropping_it(self, prod):
        frame = pd.DataFrame({c: [0] for c in prod.EMITTED_COLUMNS})
        frame["a_column_the_contract_does_not_know"] = 1
        with pytest.raises(ValueError, match="not in EMITTED_COLUMNS"):
            prod._reindex_emitted(frame)

    def test_the_f032_ordering_guard_still_runs_on_the_full_listing(self, prod):
        """Design R4: a per-vintage re-check would weaken the guard to "this vintage has bronze",
        which is the esr_weekly_ingest race it exists to stop. The guard is untouched and still
        refuses an empty selection."""
        with pytest.raises(prod.BronzeNotReadyError):
            prod.assert_bronze_ready([], [])
        with pytest.raises(prod.BronzeNotReadyError):
            prod.assert_bronze_ready([f"{BRONZE_PREFIX}garbage.parquet"], [])


# ===========================================================================
# PIN 7 -- the as_of law's tripwires, COUNTER-ONLY.
# ===========================================================================
class TestAsOfTripwiresAreCounterOnly:
    def _observations(self, task) -> list:
        out = []
        for as_of in VINTAGES:
            for code, _slug in CODES:
                for market_year in (CLOSED_MY, OPEN_MY):
                    out.append(task.BronzeVintageObservation(
                        commodity_code=code, market_year=market_year, as_of_date=as_of,
                        rows=16, max_week_ending=_max_week_for(code, market_year, as_of),
                        bronze_key=_bronze_key(code, market_year, as_of),
                    ))
        return out

    def test_3a_refuses_nothing_on_a_closed_marketing_year(self, bronze_task):
        """DESIGN F1, reproduced in miniature. The CLOSED MY2024 objects sit ~355 days behind every
        release -- far past the 8-day bound -- and 3a exempts every one of them by construction.
        Unconditioned, the same bound refused 25 of the 64 raw keys of ``as_of=20260903``, and all
        25 were closed marketing years."""
        observations = self._observations(bronze_task)
        closed = [o for o in observations if o.market_year == CLOSED_MY]
        assert closed and all(
            (bronze_task.esr_release_on_or_before(
                datetime.date(int(o.as_of_date[:4]), int(o.as_of_date[4:6]), int(o.as_of_date[6:8])))
             - o.max_week_ending).days > 300 for o in closed), "the closed MY must be very stale"

        findings = bronze_task.evaluate_open_my_freshness(observations)
        assert [f for f in findings if f.market_year == CLOSED_MY] == []

    def test_3a_names_the_open_marketing_year_that_really_is_stale(self, bronze_task):
        """The planted corn regression is ALSO a freshness failure on the open MY -- 3a and 3b are
        independent instruments that happen to agree here."""
        findings = bronze_task.evaluate_open_my_freshness(self._observations(bronze_task))
        named = {(f.commodity_code, f.as_of_date) for f in findings}
        assert (401, VINTAGES[2]) in named
        assert all(f.market_year == OPEN_MY for f in findings)
        assert all(f.rule == "3a-open-my-freshness" for f in findings)

    def test_3b_names_the_regression_and_only_the_regression(self, bronze_task):
        """The check nothing in the estate does today: corn's open-MY tape goes BACKWARDS between
        two vintages. On the live surface that is 401/MY2026 at 2026-08-27 -> 2026-05-14, from
        ETag-identical raw -- the open defect (design R10) this tripwire surfaces and does not fix.
        """
        observations = self._observations(bronze_task)
        early = [o for o in observations if o.as_of_date < VINTAGES[2]]
        late = [o for o in observations if o.as_of_date == VINTAGES[2]]
        priors = bronze_task.priors_from_observations(early)

        findings = bronze_task.evaluate_bronze_regression(late, priors)
        assert [(f.commodity_code, f.market_year) for f in findings] == [(401, OPEN_MY)]
        assert "REGRESSED" in findings[0].detail and "2026-05-16" in findings[0].detail

    def test_3b_is_silent_on_a_first_vintage(self, bronze_task):
        """No prior is not a finding. Inventing a baseline for a pair's first vintage is exactly
        the frequency-floor mistake."""
        observations = [o for o in self._observations(bronze_task) if o.as_of_date == VINTAGES[0]]
        assert bronze_task.evaluate_bronze_regression(observations, {}) == []

    def test_the_shadow_report_refuses_nothing(self, bronze_task, caplog):
        """The whole point of the shadow: findings are LOGGED, the return value is advisory, and no
        code path in the task consumes it to drop, skip or fail a key."""
        with caplog.at_level("WARNING"):
            freshness, regressions = bronze_task.report_tripwires(self._observations(bronze_task))
        assert regressions, "the planted regression must be named"
        assert any("WOULD REFUSE (shadow only)" in r.message for r in caplog.records)

        # STRUCTURAL, not textual. The shipped version of this pin asserted three literal
        # substrings ("if freshness", "if regressions", "sys.exit(2) if") were absent -- which a
        # rename of either local, or `if report_tripwires(...)[1]:`, walks straight past. The claim
        # is about the SHAPE of the call, so it is checked on the parse tree: every call to
        # report_tripwires must be a bare expression statement, which is the one form in the
        # language whose value cannot be bound, tested, indexed or returned.
        tree = ast.parse(_BRONZE_TASK.read_text(encoding="utf-8"))
        parents = _parent_map(tree)
        bare, consuming = 0, []
        for call in _calls_to(tree, "report_tripwires"):
            if isinstance(parents.get(call), ast.Expr):
                bare += 1
            else:
                consuming.append(type(parents.get(call)).__name__)
        assert bare == 1, f"expected exactly one bare report_tripwires() statement, found {bare}"
        assert consuming == [], (
            f"report_tripwires' return value is CONSUMED by {consuming}; the shadow refuses "
            f"nothing and nothing may branch on it")

    def test_the_prior_index_comes_from_ONE_listing(self, bronze_task, bronze_store):
        """``shadow-prior``'s cost control: one paginated LIST answers "which vintages exist for
        this pair", never one LIST per key. A per-key listing would build 8,920 boto3 clients."""
        index = bronze_task.build_prior_vintage_index(sorted(bronze_store))
        assert index[(401, OPEN_MY)] == list(VINTAGES)
        assert set(index) == {(code, my) for code, _ in CODES for my in (CLOSED_MY, OPEN_MY)}
        # a key with no as_of= segment contributes nothing rather than a fabricated vintage
        assert bronze_task.build_prior_vintage_index(
            [f"{BRONZE_PREFIX}commodity_code=401/market_year=2025/part-000.parquet"]) == {}

    def test_no_earlier_vintage_reads_nothing_at_all(self, bronze_task):
        """The first vintage of a pair must not trigger a GET. If it did, ``shadow-prior`` would
        pay a read per key on a first backfill for a comparison that cannot exist."""
        def _boom(*a, **kw):  # pragma: no cover - must never be reached
            raise AssertionError("shadow-prior read the store with no earlier vintage")
        assert bronze_task._prior_bronze_max_week_ending(
            _boom, BUCKET, 401, OPEN_MY, VINTAGES[0], [VINTAGES[0], VINTAGES[2]]) is None

    def test_max_week_ending_never_raises(self, bronze_task, bronze_store):
        key = _bronze_key(401, OPEN_MY, VINTAGES[0])
        frame = pq.read_table(io.BytesIO(bronze_store[key])).to_pandas()
        assert bronze_task._max_week_ending(frame) == _max_week_for(401, OPEN_MY, VINTAGES[0])
        assert bronze_task._max_week_ending(pd.DataFrame()) is None
        assert bronze_task._max_week_ending(pd.DataFrame({"other": [1]})) is None

    def test_tripwire_mode_default_costs_nothing(self, bronze_task):
        assert bronze_task.tripwire_mode({}) == bronze_task.TRIPWIRE_SHADOW
        assert bronze_task.tripwire_mode({"LEVIATHAN_ESR_ASOF_TRIPWIRE": "off"}) == \
            bronze_task.TRIPWIRE_OFF
        assert bronze_task.tripwire_mode({"LEVIATHAN_ESR_ASOF_TRIPWIRE": "shadow-prior"}) == \
            bronze_task.TRIPWIRE_SHADOW_PRIOR


# ===========================================================================
# PIN 8 -- the release derivation and its mirrors.
# ===========================================================================
class TestReleaseDerivationAndMirrors:
    def test_the_sibling_pairs_floor_to_their_thursday(self, bronze_task):
        """The three measured sibling pairs, by date: a Friday/Sunday re-run floors back to the
        Thursday release and would overwrite that partition rather than mint a sibling."""
        d = datetime.date
        assert bronze_task.esr_release_on_or_before(d(2026, 9, 4)) == d(2026, 9, 3)   # Fri -> Thu
        assert bronze_task.esr_release_on_or_before(d(2026, 7, 24)) == d(2026, 7, 23)  # Fri -> Thu
        assert bronze_task.esr_release_on_or_before(d(2026, 8, 16)) == d(2026, 8, 13)  # Sun -> Thu
        assert bronze_task.esr_release_on_or_before(d(2026, 9, 3)) == d(2026, 9, 3)   # Thu -> itself

    def test_the_fetch_shadow_derivation_agrees_and_changes_no_key(self):
        """``jobs/ingest/fetch_usda_esr.py`` logs the derived release BESIDE the label it uses. The
        derivation must agree with the bronze task's, and the fetch must still write ``as_of_date``
        unmodified -- this is a counter, not the law's enforcing half."""
        from jobs.ingest import fetch_usda_esr as F
        d = datetime.date
        for day in (d(2026, 9, 4), d(2026, 9, 3), d(2026, 8, 16), d(2026, 7, 24), d(2026, 5, 24)):
            assert F.esr_release_on_or_before(day) == \
                _load(_BRONZE_TASK, "esr_task_mirror_check").esr_release_on_or_before(day)
        source = (_REPO / "jobs" / "ingest" / "fetch_usda_esr.py").read_text(encoding="utf-8")
        assert "raw_esr_weekly_key(code, year, as_of_date)" in source, (
            "the key must still be minted from the label ACTUALLY USED; the derivation is shadow")
        assert "_derived_label" in source and "as_of_date = _derived_label" not in source

    def test_the_marketing_year_mirror_equals_the_fetchers_over_the_whole_universe(
            self, bronze_task):
        """The mirror hazard, closed behaviourally rather than structurally: every code of the
        measured 44-code source universe must resolve to the SAME marketing year in the bronze
        task's mirror and in the fetcher that owns the table."""
        from jobs.ingest import fetch_usda_esr as F
        references = [datetime.date(2026, m, 15) for m in range(1, 13)]
        for code in F._TARGET_COMMODITY_CODES:
            for reference in references:
                assert bronze_task.open_marketing_year(code, reference) == \
                    F._current_marketing_year(code, reference), (code, reference)


# ===========================================================================
# PIN 9 -- main()'s WIRING. Everything above drives build_objects / report_tripwires directly, so
# main() itself was correct by INSPECTION only: a mutant that hard-coded ``stream=False`` in main,
# or moved the peak-memory report behind the FAILED exit, or dropped the tripwire dispatch, left
# every other test in this file green. These pins read the parse tree, so they survive a rename of
# any local and die to a change in SHAPE -- which is what the sentences actually claim.
# ===========================================================================
class TestMainWiring:
    def test_main_reads_the_flag_and_passes_it_through(self):
        """``stream = vintage_stream_enabled()`` -> ``build_objects(..., stream=stream)``. Pinned
        as two links so that hard-coding EITHER end is red: a literal ``stream=False`` disarms the
        whole mechanism silently, and a literal ``stream=True`` arms a dark lever the owner has not
        sequenced (the real fire is behind lane C's S7 promote)."""
        main = _function(_module_tree(_PRODUCER), "main")

        bound = {
            target.id
            for node in ast.walk(main) if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and _call_name(node.value) == "vintage_stream_enabled"
        }
        assert bound, "main() must read the flag through vintage_stream_enabled()"

        calls = _calls_to(main, "build_objects")
        assert len(calls) == 1, f"expected one build_objects call site in main(), found {len(calls)}"
        keywords = {kw.arg: kw.value for kw in calls[0].keywords}
        assert "stream" in keywords, "stream= must be passed EXPLICITLY; it is keyword-only"
        passed = keywords["stream"]
        assert isinstance(passed, ast.Name), (
            f"stream= is wired to a {type(passed).__name__}, not to the name the flag was read "
            f"into -- a hard-coded value makes LEVIATHAN_ESR_VINTAGE_STREAM inert")
        assert passed.id in bound, (
            f"stream={passed.id} is not the name vintage_stream_enabled() was assigned to {bound}")

    def test_the_peak_probe_reports_before_the_failed_exit(self):
        """The instrument exists to measure the fire that dies. Reporting after the FAILED branch
        would lose the peak on exactly the runs the two exit-137s made this change for."""
        main = _function(_module_tree(_PRODUCER), "main")
        report_lines = [c.lineno for c in _calls_to(main, "report")]
        assert len(report_lines) == 1, "one probe.report() in main()"
        failed_exits = [
            node.lineno for node in ast.walk(main)
            if isinstance(node, ast.If) and _calls_to(node, "exit")
            and any(isinstance(x, ast.Attribute) and x.attr == "state" for x in ast.walk(node.test))
        ]
        assert failed_exits, "the manifest FAILED branch must still be there"
        assert report_lines[0] < min(failed_exits), (
            "probe.report() must run BEFORE the FAILED exit, or the peak is lost on the runs it "
            "was built to measure")

    def test_main_dispatches_the_tripwires_and_nothing_branches_on_them(self):
        """The bronze task's half: the mode is read once, the shadow is dispatched, and no
        ``sys.exit`` in main() is reached from a test that names anything the instrument produces.
        This is the sentence "the tripwires refuse nothing" as a structure rather than as a
        substring search."""
        tree = _module_tree(_BRONZE_TASK)
        main = _function(tree, "main")

        modes = {
            target.id
            for node in ast.walk(main) if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and _call_name(node.value) == "tripwire_mode"
        }
        assert modes, "main() must read the mode through tripwire_mode()"
        assert _calls_to(main, "report_tripwires"), "main() must still dispatch the shadow"

        # No name ANYWHERE in the module is bound from report_tripwires (the bare-statement pin in
        # TestAsOfTripwiresAreCounterOnly says the same thing from the other side), and no exit is
        # guarded by anything the instrument produces.
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Return)):
                assert _call_name(getattr(node, "value", None)) != "report_tripwires", (
                    "report_tripwires' return value is bound or returned; it is advisory")

        tripwire_names = set(modes) | {
            "freshness", "regressions", "findings", "finding", "observations", "s3_priors",
            "prior_index", "report_tripwires",
        }
        guarded = [
            {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            for node in ast.walk(main)
            if isinstance(node, ast.If) and _calls_to(node, "exit")
        ]
        assert guarded, "main() must still hold at least one guarded exit"
        for names in guarded:
            assert not (names & tripwire_names), (
                f"an exit is guarded by {sorted(names & tripwire_names)} -- the shadow would stop "
                f"being counter-only")


# ===========================================================================
# PIN 10 -- the coverage the bronze fixture cannot reach, and the seed's determinism.
# ===========================================================================
class TestEveryMarketingYearStartMonth:
    """The bronze fixture's two commodities (401 corn, 801 soybeans) are both Sep-start, so 3a's
    open/closed conditioning runs end to end for ONE of the three start-month groups. The mirror
    pin in TestReleaseDerivationAndMirrors proves the groups themselves are the fetcher's over all
    44 codes; these drive the CLAUSE for a member of each group, from observations built by hand
    rather than from bronze, so Jun (wheat) and Aug (cotton, rice) are exercised too."""

    _REFERENCE = "20260820"          # a Thursday: esr_release_on_or_before is the identity here

    def _obs(self, task, code, market_year, week_ending):
        return task.BronzeVintageObservation(
            commodity_code=code, market_year=market_year, as_of_date=self._REFERENCE,
            rows=16, max_week_ending=week_ending,
            bronze_key=f"{BRONZE_PREFIX}commodity_code={code}/market_year={market_year}/"
                       f"as_of={self._REFERENCE}/part-000.parquet",
        )

    @pytest.mark.parametrize("code,start_month,group", [
        (101, 6, "wheat (Jun 1)"),
        (1201, 8, "cotton (Aug 1)"),
        (1501, 8, "rice (Aug 1)"),
        (401, 9, "corn (Sep 1)"),
    ])
    def test_the_open_my_is_judged_and_the_closed_one_is_exempt(
            self, bronze_task, code, start_month, group):
        release = datetime.date(2026, 8, 20)
        assert bronze_task._marketing_year_start_month(code) == start_month, group
        open_my = bronze_task.open_marketing_year(code, release)

        fresh = self._obs(bronze_task, code, open_my, release - datetime.timedelta(days=6))
        stale = self._obs(bronze_task, code, open_my, datetime.date(2026, 5, 16))
        closed = self._obs(bronze_task, code, open_my - 1, datetime.date(2025, 8, 30))

        assert bronze_task.evaluate_open_my_freshness([fresh]) == [], (
            f"{group}: a healthy open MY sits 6 d back and must not be named")
        named = bronze_task.evaluate_open_my_freshness([stale])
        assert [f.commodity_code for f in named] == [code], f"{group}: a stale open MY is named"
        assert named[0].rule == "3a-open-my-freshness"
        assert bronze_task.evaluate_open_my_freshness([closed]) == [], (
            f"{group}: the CLOSED marketing year is exempt by construction -- that exemption IS "
            f"clause 3a, and unconditioned the same bound refused 25 of 64 raw keys")

    def test_the_open_my_boundary_is_the_groups_own_start_month(self, bronze_task):
        """The day the open MY rolls is the group's start month, not January and not a shared
        date -- so an August observation is judged against MY2026 for cotton and MY2025 for corn.
        Getting this wrong would exempt the OPEN year and judge the CLOSED one, which is clause 3a
        inverted rather than merely wrong."""
        august = datetime.date(2026, 8, 20)
        july = datetime.date(2026, 7, 20)
        assert bronze_task.open_marketing_year(1201, august) == 2026   # Aug-start: rolled
        assert bronze_task.open_marketing_year(401, august) == 2025    # Sep-start: not yet
        assert bronze_task.open_marketing_year(101, july) == 2026      # Jun-start: rolled
        assert bronze_task.open_marketing_year(401, july) == 2025


class TestShadowPriorSeedIsDeterministic:
    """``shadow-prior`` writes its seed index from _WORKERS threads. The GIL makes each store
    atomic but not the read-modify-write, so a run holding SEVERAL vintages of one pair (a
    re-bronze -- never the weekly single-vintage fire this mode is for) had a last-writer-wins
    seed: the later vintages' "priors" are IN-RUN objects, and arrival order decided which one
    survived. Advisory either way -- a wrong seed can only SUPPRESS a finding, since 3b walks the
    in-run timeline itself -- but it made a counter non-reproducible, so a rule replaced the race:
    keep the EARLIEST candidate, which is the one that actually precedes the run."""

    def test_the_earliest_candidate_wins_whatever_the_arrival_order(self, bronze_task):
        d = datetime.date
        for arrivals in ([("20260806", d(2026, 8, 1)), ("20260813", d(2026, 8, 8))],
                         [("20260813", d(2026, 8, 8)), ("20260806", d(2026, 8, 1))]):
            out: dict = {}
            for got in arrivals:
                bronze_task._record_prior(out, 401, OPEN_MY, got)
            assert out[(401, OPEN_MY)] == ("20260806", d(2026, 8, 1)), (
                "the out-of-run predecessor is the earliest candidate, whichever lands first")

    def test_it_is_concurrency_safe_and_a_None_sink_is_a_no_op(self, bronze_task):
        import threading
        out: dict = {}
        candidates = [(f"2026080{i}", datetime.date(2026, 8, i)) for i in range(1, 10)]
        threads = [threading.Thread(target=bronze_task._record_prior, args=(out, 401, OPEN_MY, c))
                   for c in candidates]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert out[(401, OPEN_MY)] == candidates[0]
        assert bronze_task._record_prior(None, 401, OPEN_MY, candidates[0]) is None
        assert bronze_task._PRIORS_LOCK.acquire(blocking=False), "the lock must not be left held"
        bronze_task._PRIORS_LOCK.release()

    def test_the_default_mode_is_shadow_and_an_unknown_value_says_so(self, bronze_task, caplog):
        """THE ONE MECHANISM IN THIS SITTING THAT IS NOT DEFAULT-OFF, pinned so it is read rather
        than discovered in a log: an unset LEVIATHAN_ESR_ASOF_TRIPWIRE means ``shadow``, which
        counts on every weekly fire. A TYPO must not silently disable an instrument, so it also
        lands on ``shadow`` -- and now names the value it did not recognise instead of falling
        through in silence. ``off`` is the way back, and it is the only way back."""
        assert bronze_task.tripwire_mode({}) == bronze_task.TRIPWIRE_SHADOW
        with caplog.at_level("WARNING"):
            assert bronze_task.tripwire_mode(
                {"LEVIATHAN_ESR_ASOF_TRIPWIRE": "shdaow"}) == bronze_task.TRIPWIRE_SHADOW
        assert any("not a recognised mode" in r.message for r in caplog.records)
        caplog.clear()
        with caplog.at_level("WARNING"):
            for silent in ("", "shadow", "on", "true", "1", "yes", "SHADOW", " shadow "):
                assert bronze_task.tripwire_mode(
                    {"LEVIATHAN_ESR_ASOF_TRIPWIRE": silent}) == bronze_task.TRIPWIRE_SHADOW
        assert [r for r in caplog.records if "not a recognised mode" in r.message] == [], (
            "the accepted spellings must not warn")

class TestTripwiresAreNaTSafe:
    """THE DATA-SHAPED PIN the structural pins could not carry (verify seat, 2026-09-07): a frame whose
    week_ending_date is all-missing, or mixed with missing, must yield an observation the clauses can
    hold without raising -- the counter-only shadow ships DEFAULT-ON into the live weekly fire, and
    isinstance(pd.NaT, datetime.date) is True, so the first cut handed NaT through as a date."""

    def _obs(self, bronze_task, **known):
        T = bronze_task.BronzeVintageObservation
        base = {f: None for f in T._fields}
        base.update({"commodity_code": 401, "market_year": OPEN_MY, "as_of_date": VINTAGES[0],
                     "rows": 16, "bronze_key": "bronze/k"})
        base.update(known)
        return T(**{k: v for k, v in base.items() if k in T._fields})

    def test_all_nat_column_reads_none_not_nat(self, bronze_task):
        df = pd.DataFrame({"week_ending_date": pd.to_datetime([None, None])})
        assert df["week_ending_date"].isna().all()
        assert bronze_task._max_week_ending(df) is None

    def test_unparseable_strings_read_none(self, bronze_task):
        df = pd.DataFrame({"week_ending_date": ["", "n/a"]})
        assert bronze_task._max_week_ending(df) is None

    def test_one_bad_row_no_longer_blinds_the_object(self, bronze_task):
        good = datetime.date(2026, 8, 8)
        df = pd.DataFrame({"week_ending_date": [good, pd.NaT, datetime.date(2026, 8, 1)]})
        assert bronze_task._max_week_ending(df) == good

    def test_a_none_observation_never_raises_in_3b_and_never_becomes_the_prior(self, bronze_task):
        early = self._obs(bronze_task, as_of_date=VINTAGES[0], max_week_ending=datetime.date(2026, 8, 8))
        blind = self._obs(bronze_task, as_of_date=VINTAGES[1], max_week_ending=None)
        late = self._obs(bronze_task, as_of_date=VINTAGES[2], max_week_ending=datetime.date(2026, 8, 1))
        findings = bronze_task.evaluate_bronze_regression([early, blind, late], {})
        # the regression is measured EARLY -> LATE across the blind vintage; the blind one is neither
        # a finding nor the prior
        assert [(f.as_of_date) for f in findings] == [VINTAGES[2]]
        assert bronze_task.evaluate_open_my_freshness([blind]) == []

    def test_the_shadow_report_holds_a_none_observation(self, bronze_task):
        early = self._obs(bronze_task, as_of_date=VINTAGES[0], max_week_ending=datetime.date(2026, 8, 8))
        blind = self._obs(bronze_task, as_of_date=VINTAGES[1], max_week_ending=None)
        a, b = bronze_task.report_tripwires([early, blind], None)
        assert isinstance(a, list) and isinstance(b, list)

