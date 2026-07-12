"""SILVER-F012/F015 lease: acquire, re-entrant heartbeat, expiry steal, fencing recheck, contention,
release. Uses the in-memory FakeS3 (conditional-write aware). AWS-free."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from leviathan.silver import lease as L
from leviathan.silver.lease import (
    Lease,
    LeaseContended,
    LeaseLost,
    LeaseUnavailable,
    lease_lock_id,
    normalized_partition_set,
)

BASE = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


def _lease(fake_s3, owner="op-a", run="run-1", ttl=900):
    return Lease(bucket="leviathan-test", prefix="silver/", lock_id="silver_x._table",
                 s3_client=fake_s3, owner=owner, run_id=run, ttl_seconds=ttl)


def test_normalized_partition_set_is_order_independent():
    a = normalized_partition_set([["101", "2000"], ["102", "2001"]])
    b = normalized_partition_set([["102", "2001"], ["101", "2000"]])
    assert a == b
    assert normalized_partition_set(None) == "_table"


def test_lock_id_shapes():
    assert lease_lock_id("silver_esr") == "silver_esr._table"
    assert lease_lock_id("silver_esr", [["1", "2", "3"]]).startswith("silver_esr.")


def test_acquire_new_sets_token_one(fake_s3):
    lease = _lease(fake_s3)
    state = lease.acquire(now=BASE)
    assert state.fencing_token == 1
    assert state.owner == "op-a"
    # object landed under the control _locks prefix, not a data prefix.
    assert lease.key == "silver/_locks/silver_x._table.json"
    assert (("leviathan-test", lease.key) in fake_s3.store)


def test_reentrant_acquire_heartbeats_same_token(fake_s3):
    lease = _lease(fake_s3)
    lease.acquire(now=BASE)
    again = lease.acquire(now=BASE + timedelta(seconds=60))
    assert again.fencing_token == 1  # heartbeat, not a new acquisition


def test_second_operator_blocked_while_live(fake_s3):
    a = _lease(fake_s3, owner="op-a", run="run-1")
    a.acquire(now=BASE)
    b = _lease(fake_s3, owner="op-b", run="run-2")
    with pytest.raises(LeaseUnavailable):
        b.acquire(now=BASE + timedelta(seconds=10))


def test_expired_lease_is_stolen_and_token_bumps(fake_s3):
    a = _lease(fake_s3, owner="op-a", run="run-1", ttl=100)
    a.acquire(now=BASE)
    b = _lease(fake_s3, owner="op-b", run="run-2", ttl=100)
    stolen = b.acquire(now=BASE + timedelta(seconds=200))  # a's lease expired
    assert stolen.fencing_token == 2
    assert stolen.owner == "op-b"


def test_recheck_passes_for_current_holder(fake_s3):
    lease = _lease(fake_s3)
    state = lease.acquire(now=BASE)
    # recheck within TTL with the right token passes.
    lease.recheck(state.fencing_token, now=BASE + timedelta(seconds=10))


def test_recheck_fails_after_being_fenced_out(fake_s3):
    """The core fence: a stale holder that lost the lease is refused before it can mutate."""
    a = _lease(fake_s3, owner="op-a", run="run-1", ttl=100)
    granted = a.acquire(now=BASE)
    b = _lease(fake_s3, owner="op-b", run="run-2", ttl=100)
    b.acquire(now=BASE + timedelta(seconds=200))  # steals; token -> 2
    # a still thinks it holds token 1 -> recheck must refuse.
    with pytest.raises(LeaseLost):
        a.recheck(granted.fencing_token, now=BASE + timedelta(seconds=210))


def test_recheck_fails_on_stale_token_even_if_owner_matches(fake_s3):
    lease = _lease(fake_s3)
    lease.acquire(now=BASE)
    with pytest.raises(LeaseLost):
        lease.recheck(99, now=BASE + timedelta(seconds=1))


def test_recheck_fails_when_expired(fake_s3):
    lease = _lease(fake_s3, ttl=100)
    state = lease.acquire(now=BASE)
    with pytest.raises(LeaseLost):
        lease.recheck(state.fencing_token, now=BASE + timedelta(seconds=200))


def test_heartbeat_extends_expiry(fake_s3):
    lease = _lease(fake_s3, ttl=100)
    lease.acquire(now=BASE)
    hb = lease.heartbeat(now=BASE + timedelta(seconds=50))
    # after heartbeat, a recheck well past the original expiry still passes.
    lease.recheck(hb.fencing_token, now=BASE + timedelta(seconds=120))


def test_heartbeat_fails_if_not_holder(fake_s3):
    a = _lease(fake_s3, owner="op-a", run="run-1", ttl=100)
    a.acquire(now=BASE)
    b = _lease(fake_s3, owner="op-b", run="run-2", ttl=100)
    b.acquire(now=BASE + timedelta(seconds=200))
    with pytest.raises(LeaseLost):
        a.heartbeat(now=BASE + timedelta(seconds=210))


def test_release_only_removes_own_lock(fake_s3):
    a = _lease(fake_s3, owner="op-a", run="run-1", ttl=100)
    a.acquire(now=BASE)
    b = _lease(fake_s3, owner="op-b", run="run-2", ttl=100)
    b.acquire(now=BASE + timedelta(seconds=200))  # b now holds it
    a.release()  # a no longer holds it -> must NOT delete b's lock
    assert ("leviathan-test", a.key) in fake_s3.store
    b.release()
    assert ("leviathan-test", b.key) not in fake_s3.store


def test_concurrent_create_race_is_contended(fake_s3, monkeypatch):
    """Two brand-new acquirers: the one that loses the IfNoneMatch create gets LeaseContended."""
    a = _lease(fake_s3, owner="op-a", run="run-1")
    b = _lease(fake_s3, owner="op-b", run="run-2")
    # Both read empty first; simulate by having b create between a's read and a's create.
    orig_read = a._read
    def read_then_let_b_win():
        res = orig_read()
        if res[0] is None and ("leviathan-test", b.key) not in fake_s3.store:
            b.acquire(now=BASE)  # b sneaks in
        return res
    monkeypatch.setattr(a, "_read", read_then_let_b_win)
    with pytest.raises(LeaseContended):
        a.acquire(now=BASE)
