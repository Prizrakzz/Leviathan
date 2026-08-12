"""D-MW-23: the credit ledger core (store layer). Hermetic — no AWS, no LLM, no network.

What this file pins:
  * the CAP CLAUSE the plan pre-registered: a debit of amount=3 against cap 100 at n=98 is REJECTED,
    and the condition that does it carries NO ARITHMETIC (DynamoDB ConditionExpressions forbid it —
    the draft's `n + :amt <= :cap` would have been a ValidationException on every metered turn);
  * IDEMPOTENCY: a replayed op_id (double charge, double refund, refund race) is a NO-OP, never a
    spurious 429 and never a second charge — index-aware CancellationReasons parsing is what
    separates 'already applied' from 'over cap';
  * the LEASE guard: a concurrent metered turn is refused, an EXPIRED lease is admitted (a crashed
    turn must not lock a user out for the ~48h DynamoDB TTL deletion window);
  * the monthly period key (reset is free because the period is IN the key);
  * InMemory/Dynamo PARITY on the whole story, run as one scenario against both stores;
  * THE THREE SHIPPED METERS ARE UNTOUCHED (daily turn, suggest, dossier monthly): they never enter
    the transactional path, their expressions are byte-identical, and they still raise QuotaExceeded
    off ConditionalCheckFailedException — the failure type a transactional wrapping would have
    changed, silently failing all three caps OPEN.

The fake DynamoDB below EVALUATES conditions (real all-or-nothing transaction semantics, index-aligned
CancellationReasons) but cannot validate expression SYNTAX — no mock can. That clause belongs to the
D-MW-26 staging pass against DynamoDB-local / the real table under a test sub.
"""
from __future__ import annotations

import calendar
import inspect
import operator
import re

import pytest
from botocore.exceptions import ClientError
from leviathan.graphrag import store as st

AUG = calendar.timegm((2026, 8, 12, 10, 0, 0, 0, 0, 0))              # a fixed UTC instant
PERIOD = "credits#2026-08"


# ── a condition-evaluating DynamoDB stand-in ────────────────────────────────────────────────────────
_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "=": operator.eq}


def _eval_clause(item: dict, clause: str, vals: dict) -> bool:
    clause = clause.strip()
    if clause.startswith("attribute_not_exists("):
        return clause[len("attribute_not_exists("):-1] not in item
    if clause.startswith("attribute_exists("):
        return clause[len("attribute_exists("):-1] in item
    attr, op, ph = clause.split()
    cur = item.get(attr)
    if cur is None:
        return False
    want = vals[ph]
    if "S" in want:                                                  # the lease OWNER TOKEN (F5) is a string
        return _OPS[op](str(cur.get("S")), str(want["S"]))
    return _OPS[op](int(cur["N"]), int(want["N"]))


def _eval_cond(item: dict, expr, vals: dict) -> bool:
    if not expr:
        return True
    return any(_eval_clause(item, c, vals or {}) for c in expr.split(" OR "))


class _FakeDynamo:
    """Enough DynamoDB to be honest about semantics: conditional writes, ADD, and transactions that
    are all-or-nothing with CancellationReasons ALIGNED TO ITEM INDEX."""

    def __init__(self):
        self.items: dict[tuple, dict] = {}
        self.calls: list[tuple] = []

    # -- helpers
    @staticmethod
    def _key(d: dict) -> tuple:
        return (d["pk"]["S"], d["sk"]["S"])

    def _apply_add(self, key: tuple, spec: dict) -> None:
        expr = spec["UpdateExpression"]
        m = re.fullmatch(r"ADD (\w+) (:\w+)", expr.strip())
        assert m, f"the fake only implements ADD; got {expr!r}"
        attr, ph = m.groups()
        item = self.items.setdefault(key, {"pk": {"S": key[0]}, "sk": {"S": key[1]}})
        cur = int(item.get(attr, {"N": "0"})["N"])
        item[attr] = {"N": str(cur + int(spec["ExpressionAttributeValues"][ph]["N"]))}

    # -- API surface
    def put_item(self, **kw):
        self.calls.append(("put_item", kw))
        key = self._key(kw["Item"])
        if not _eval_cond(self.items.get(key, {}), kw.get("ConditionExpression"),
                          kw.get("ExpressionAttributeValues")):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[key] = dict(kw["Item"])

    def update_item(self, **kw):
        self.calls.append(("update_item", kw))
        key = self._key(kw["Key"])
        if not _eval_cond(self.items.get(key, {}), kw.get("ConditionExpression"),
                          kw.get("ExpressionAttributeValues")):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        self._apply_add(key, kw)

    def get_item(self, **kw):
        self.calls.append(("get_item", kw))
        it = self.items.get(self._key(kw["Key"]))
        return {"Item": dict(it)} if it else {}

    def delete_item(self, **kw):
        self.calls.append(("delete_item", kw))
        key = self._key(kw["Key"])
        # A conditional delete is a real DynamoDB shape and the lease fence (F5) rides it: a failing
        # condition raises and deletes NOTHING. An unconditional delete of an absent item is a no-op.
        if not _eval_cond(self.items.get(key, {}), kw.get("ConditionExpression"),
                          kw.get("ExpressionAttributeValues")):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "DeleteItem")
        self.items.pop(key, None)

    def query(self, **kw):
        self.calls.append(("query", kw))
        vals = kw["ExpressionAttributeValues"]
        pk, pref = vals[":p"]["S"], vals[":k"]["S"]
        rows = [dict(v) for (p, s), v in sorted(self.items.items()) if p == pk and s.startswith(pref)]
        return {"Items": rows}

    def transact_write_items(self, TransactItems):                   # noqa: N803 — botocore's kwarg
        self.calls.append(("transact_write_items", TransactItems))
        reasons, ok_all = [], True
        for entry in TransactItems:
            (op, spec), = entry.items()
            key = self._key(spec["Key"] if op == "Update" else spec["Item"])
            ok = _eval_cond(self.items.get(key, {}), spec.get("ConditionExpression"),
                            spec.get("ExpressionAttributeValues"))
            reasons.append({"Code": "None"} if ok else {"Code": "ConditionalCheckFailed"})
            ok_all &= ok
        if not ok_all:                                               # all-or-nothing: NOTHING is written
            raise ClientError({"Error": {"Code": "TransactionCanceledException"},
                               "CancellationReasons": reasons}, "TransactWriteItems")
        for entry in TransactItems:
            (op, spec), = entry.items()
            if op == "Update":
                self._apply_add(self._key(spec["Key"]), spec)
            else:
                self.items[self._key(spec["Item"])] = dict(spec["Item"])


def _dyn() -> st.DynamoStore:
    return st.DynamoStore(table="t", client=_FakeDynamo())


def _both() -> list:
    return [st.InMemoryStore(), _dyn()]


# ── the period key ──────────────────────────────────────────────────────────────────────────────────
def test_monthly_period_key_and_reset():
    assert st.credits_period(AUG) == PERIOD
    assert st.credits_reset_at(AUG) == "2026-09-01T00:00:00Z"
    dec = calendar.timegm((2026, 12, 31, 23, 59, 0, 0, 0, 0))
    assert st.credits_period(dec) == "credits#2026-12"
    assert st.credits_reset_at(dec) == "2027-01-01T00:00:00Z"        # year rollover


@pytest.mark.parametrize("s", _both())
def test_monthly_rollover_is_free_the_period_is_in_the_key(s):
    assert s.debit("u", PERIOD, 1, 100, op_id="t1:charge") is True
    assert s.read_quota("u", PERIOD) == 1
    assert s.read_quota("u", "credits#2026-09") == 0                 # next month starts absent = zero


def test_credit_sk_is_the_quota_satellite_shape():
    s = _dyn()
    s.debit("u", st.credits_period(AUG), 1, 100, op_id="t1:charge")
    items = s.db.calls[-1][1]
    assert items[0]["Update"]["Key"]["sk"]["S"] == "quota#credits#2026-08"


# ── the pre-registered cap clause ───────────────────────────────────────────────────────────────────
def _fill(s, n: int) -> None:
    for i in range(n):
        assert s.debit("u", PERIOD, 1, 100, op_id=f"seed{i}") is True


@pytest.mark.parametrize("s", _both())
def test_debit_3_against_cap_100_at_98_is_rejected(s):
    """The plan's explicit staging assertion, pinned here in unit form."""
    _fill(s, 98)
    with pytest.raises(st.QuotaExceeded):
        s.debit("u", PERIOD, 3, 100, op_id="t99:charge")
    assert s.read_quota("u", PERIOD) == 98                           # the counter never moved
    assert all(r["op_id"] != "t99:charge" for r in s.list_ledger("u", PERIOD))
    assert s.debit("u", PERIOD, 2, 100, op_id="t99b:charge") is True  # exactly-to-the-cap still passes
    assert s.read_quota("u", PERIOD) == 100


@pytest.mark.parametrize("s", _both())
def test_a_refused_debit_leaves_the_op_id_reusable(s):
    """A cancelled transaction writes NOTHING — including the ledgerop marker. If it had leaked, the
    retry after a refund would be swallowed as a 'replay' and the user would get free depth."""
    _fill(s, 100)
    with pytest.raises(st.QuotaExceeded):
        s.debit("u", PERIOD, 1, 100, op_id="t101:charge")
    assert s.credit("u", PERIOD, 1, op_id="t50:refund") is True
    assert s.debit("u", PERIOD, 1, 100, op_id="t101:charge") is True
    assert s.read_quota("u", PERIOD) == 100


@pytest.mark.parametrize("s", _both())
def test_amount_larger_than_the_grant_is_refused_on_a_fresh_item(s):
    """`attribute_not_exists(n)` is TRUE on a fresh item, so the condition alone would admit a charge
    bigger than the whole grant. The caller-side guard closes it, in both stores."""
    with pytest.raises(st.QuotaExceeded):
        s.debit("u", PERIOD, 101, 100, op_id="huge")
    assert s.read_quota("u", PERIOD) == 0


def test_debit_condition_carries_no_arithmetic_and_precomputes_the_limit():
    """The ValidationException class: DynamoDB conditions forbid arithmetic, so `:limit = cap - amount`
    is computed caller-side."""
    s = _dyn()
    s.debit("u", PERIOD, 3, 100, op_id="t1:charge")
    upd = s.db.calls[-1][1][0]["Update"]
    assert upd["ConditionExpression"] == "attribute_not_exists(n) OR n <= :limit"
    assert upd["ExpressionAttributeValues"][":limit"] == {"N": "97"}   # 100 - 3, precomputed
    s.credit("u", PERIOD, 3, op_id="t1:refund")
    cred = s.db.calls[-1][1][0]["Update"]
    assert cred["ConditionExpression"] == "n >= :amt"
    for expr in (upd["ConditionExpression"], cred["ConditionExpression"]):
        assert not re.search(r"[+\-*/]", expr)                        # no arithmetic, anywhere


# ── idempotency ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("s", _both())
def test_double_debit_same_op_id_is_a_noop_not_a_429(s):
    assert s.debit("u", PERIOD, 1, 100, op_id="t1:charge", ref="t1") is True
    assert s.debit("u", PERIOD, 1, 100, op_id="t1:charge", ref="t1") is False   # retry -> no-op
    assert s.read_quota("u", PERIOD) == 1
    assert len(s.list_ledger("u", PERIOD)) == 1


@pytest.mark.parametrize("s", _both())
def test_double_refund_and_refund_race_are_noops(s):
    s.debit("u", PERIOD, 1, 100, op_id="t1:charge", ref="t1")
    assert s.credit("u", PERIOD, 1, op_id="t1:refund", ref="t1") is True
    assert s.credit("u", PERIOD, 1, op_id="t1:refund", ref="t1") is False       # double refund
    assert s.read_quota("u", PERIOD) == 0
    assert s.credit("u", PERIOD, 1, op_id="t1:refund-b", ref="t1") is False     # nothing to give back
    assert s.read_quota("u", PERIOD) == 0                                       # never negative


@pytest.mark.parametrize("s", _both())
def test_replay_at_the_cap_is_still_a_noop_not_a_429(s):
    """Index-aware reasons: at n=cap BOTH conditions fail; the ledgerop one wins, because the charge
    already happened and a retry must not become a refusal."""
    _fill(s, 99)
    assert s.debit("u", PERIOD, 1, 100, op_id="last") is True
    assert s.read_quota("u", PERIOD) == 100
    assert s.debit("u", PERIOD, 1, 100, op_id="last") is False
    assert s.read_quota("u", PERIOD) == 100


@pytest.mark.parametrize("s", _both())
def test_downgrade_leaves_the_ledger_net_unchanged(s):
    """The pinned reconcile property: requested max, honored standard -> charged then credited back,
    NET ZERO, with both legs visible in the history."""
    before = s.read_quota("u", PERIOD)
    assert s.debit("u", PERIOD, 3, 100, op_id="turn7:charge", ref="turn7") is True
    assert s.credit("u", PERIOD, 3, op_id="turn7:downgrade-refund", ref="turn7") is True
    assert s.read_quota("u", PERIOD) == before
    rows = s.list_ledger("u", PERIOD)
    assert [r["kind"] for r in rows] == ["debit", "credit"]
    assert sum(r["amount"] for r in rows if r["kind"] == "debit") == \
           sum(r["amount"] for r in rows if r["kind"] == "credit")


# ── ledger rows ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("s", _both())
def test_ledger_row_shape_and_scoping(s):
    s.debit("u", PERIOD, 2, 100, op_id="turn3:charge", ref="turn3")
    row, = s.list_ledger("u", PERIOD)
    assert {"kind", "amount", "ref", "balance_after"} <= set(row)
    assert (row["kind"], row["amount"], row["ref"], row["balance_after"]) == ("debit", 2, "turn3", 2)
    assert s.list_ledger("u", "credits#2026-09") == []                # period-scoped
    assert s.list_ledger("other", PERIOD) == []                       # user-scoped, no leak


def test_ledger_keys_and_the_ttl_invariant():
    """sk shapes are the pinned ones, and NEITHER ledger row carries `expires_at`: a ledgerop that
    aged out would re-open the double-charge window it exists to close."""
    s = _dyn()
    s.debit("u", PERIOD, 1, 100, op_id="turn3:charge", ref="turn3")
    items = s.db.calls[-1][1]
    assert items[1]["Put"]["Item"]["sk"]["S"] == "ledgerop#turn3:charge"
    assert items[1]["Put"]["ConditionExpression"] == "attribute_not_exists(sk)"
    assert items[2]["Put"]["Item"]["sk"]["S"].startswith(f"ledger#{PERIOD}#")
    assert all("expires_at" not in i["Put"]["Item"] for i in items[1:])
    assert all(it["pk"]["S"] == "user#u" for it in
               [items[0]["Update"]["Key"], items[1]["Put"]["Item"], items[2]["Put"]["Item"]])


def test_ledger_read_skips_a_junk_row():
    s = _dyn()
    s.debit("u", PERIOD, 1, 100, op_id="ok")
    s.db.items[("user#u", f"ledger#{PERIOD}#junk")] = {"pk": {"S": "user#u"},
                                                       "sk": {"S": f"ledger#{PERIOD}#junk"}}
    assert [r["op_id"] for r in s.list_ledger("u", PERIOD)] == ["ok"]


def test_non_condition_dynamo_errors_propagate():
    """A swallowed AccessDenied (the ConditionCheckItem/transaction IAM gap) would turn every metered
    turn unmetered with no signal. The store raises; the policy layer owns the fail-open decision."""
    class _Boom(_FakeDynamo):
        def transact_write_items(self, TransactItems):               # noqa: N803
            raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "TransactWriteItems")

    s = st.DynamoStore(table="t", client=_Boom())
    with pytest.raises(ClientError):
        s.debit("u", PERIOD, 1, 100, op_id="x")
    with pytest.raises(ClientError):
        s.credit("u", PERIOD, 1, op_id="x")


@pytest.mark.parametrize("s", _both())
def test_non_positive_amounts_are_a_programming_error(s):
    for bad in (0, -1):
        with pytest.raises(ValueError):
            s.debit("u", PERIOD, bad, 100, op_id="z")
        with pytest.raises(ValueError):
            s.credit("u", PERIOD, bad, op_id="z")


# ── the in-flight lease ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("s", _both())
def test_concurrent_metered_turn_refused_expired_lease_admitted(s):
    first = s.acquire_lease("u", now=AUG)
    assert first                                                      # a truthy OWNER TOKEN, not a bool
    assert s.acquire_lease("u", now=AUG + 1) is None                  # concurrent metered turn refused
    assert s.acquire_lease("u", now=AUG + 900) is None                # the lease is live to its instant
    assert s.acquire_lease("u", now=AUG + 901)                        # expired lease -> ADMITTED
    assert s.acquire_lease("other", now=AUG + 1)                      # per-user, not global
    s.release_lease("u")
    assert s.acquire_lease("u", now=AUG + 902)                        # released -> immediately free
    s.release_lease("nobody")                                         # unknown -> no-op, never raises


@pytest.mark.parametrize("s", _both())
def test_an_expired_workers_release_does_not_delete_the_live_lease(s):
    """THE OWNERSHIP FENCE (F5). Turn A's lease expires, so turn B is admitted; A's stale `finally` then
    calls release. Without the token that delete removed B's LIVE lease and a third concurrent metered
    turn walked in — the lease is the only thing standing between two metered turns and a double spend."""
    a = s.acquire_lease("u", now=AUG)
    assert s.acquire_lease("u", now=AUG + 100) is None                # B refused while A is live
    b = s.acquire_lease("u", now=AUG + 1000)                          # A expired -> B admitted
    assert b and b != a                                               # an expired takeover mints a FRESH token
    s.release_lease("u", a)                                           # A's stale finally, 15 minutes late
    assert s.acquire_lease("u", now=AUG + 1001) is None               # ...and B's lease is STILL held
    s.release_lease("u", b)                                           # only the owner can drop it
    assert s.acquire_lease("u", now=AUG + 1002)


def test_lease_condition_and_ttl_attr():
    s = _dyn()
    token = s.acquire_lease("u", now=AUG)
    assert token
    kw = s.db.calls[-1][1]
    assert kw["Item"]["sk"]["S"] == "inflight#u"
    assert kw["ConditionExpression"] == "attribute_not_exists(sk) OR expires_at < :now"
    assert kw["Item"]["expires_at"] == {"N": str(int(AUG) + 900)}     # 15-minute LEASE, TTL is only GC
    assert kw["Item"]["lease_token"] == {"S": token}                  # the owner token rides the item (F5)
    assert kw["ExpressionAttributeValues"][":now"] == {"N": str(int(AUG))}
    s.release_lease("u", token)
    assert s.db.calls[-1][0] == "delete_item"
    assert s.db.calls[-1][1]["ConditionExpression"] == "lease_token = :t"
    assert ("user#u", "inflight#u") not in s.db.items


def test_a_tokenless_release_is_the_unconditional_operator_sweep():
    """`token=None` keeps the old unconditional delete for an operator with no token to hand — stated as
    a deliberate escape hatch, not left as an accident of a default argument."""
    s = _dyn()
    assert s.acquire_lease("u", now=AUG)
    s.release_lease("u")
    assert "ConditionExpression" not in s.db.calls[-1][1]
    assert ("user#u", "inflight#u") not in s.db.items


def test_lease_non_condition_error_propagates_so_the_caller_can_admit():
    class _Boom(_FakeDynamo):
        def put_item(self, **kw):
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem")

    with pytest.raises(ClientError):
        st.DynamoStore(table="t", client=_Boom()).acquire_lease("u")


# ── THE THREE SHIPPED METERS ARE UNTOUCHED ──────────────────────────────────────────────────────────
_SHIPPED = (st.DynamoStore.incr_turn_quota, st.DynamoStore.read_quota, st.DynamoStore.refund_quota)


def test_shipped_meters_never_enter_the_transactional_path():
    """Behavioural byte-check: the daily-turn, suggest and dossier meters all ride ONE primitive; a
    transaction anywhere in it explodes this test. (Wrapping them would swap
    ConditionalCheckFailedException for TransactionCanceledException and fail all three caps OPEN.)"""
    class _NoTransact(_FakeDynamo):
        def transact_write_items(self, TransactItems):               # noqa: N803
            raise AssertionError("a shipped meter must never use TransactWriteItems")

    s = st.DynamoStore(table="t", client=_NoTransact())
    s.incr_turn_quota("u", "2026-08-12", 50)                          # daily turn
    s.incr_turn_quota("u", "suggest#2026-08-12", 30)                  # suggest
    s.incr_turn_quota("u", "dossier#2026-08", 4)                      # dossier monthly
    s.refund_quota("u", "dossier#2026-08")
    assert s.read_quota("u", "2026-08-12") == 1
    assert {c[0] for c in s.db.calls} == {"update_item", "get_item"}
    assert all("transact_write_items" not in inspect.getsource(m) for m in _SHIPPED)


def test_shipped_meter_expressions_are_byte_identical():
    s = _dyn()
    s.incr_turn_quota("u", "2026-08-12", 50)
    kw = s.db.calls[-1][1]
    assert kw["UpdateExpression"] == "ADD n :one"
    assert kw["ConditionExpression"] == "attribute_not_exists(n) OR n < :cap"
    assert kw["ExpressionAttributeValues"] == {":one": {"N": "1"}, ":cap": {"N": "50"}}
    assert kw["Key"]["sk"] == {"S": "quota#2026-08-12"}
    s.refund_quota("u", "2026-08-12")
    kw = s.db.calls[-1][1]
    assert kw["UpdateExpression"] == "ADD n :neg"
    assert kw["ConditionExpression"] == "n > :zero"


def test_daily_cap_still_raises_quota_exceeded_at_the_cap():
    """The failure type that matters: ConditionalCheckFailedException -> QuotaExceeded, unchanged."""
    s = _dyn()
    for _ in range(3):
        s.incr_turn_quota("u", "2026-08-12", 3)
    with pytest.raises(st.QuotaExceeded):
        s.incr_turn_quota("u", "2026-08-12", 3)
    in_mem = st.InMemoryStore()
    for _ in range(3):
        in_mem.incr_turn_quota("u", "2026-08-12", 3)
    with pytest.raises(st.QuotaExceeded):
        in_mem.incr_turn_quota("u", "2026-08-12", 3)


def test_dossier_meter_still_refuses_at_its_own_limit(monkeypatch):
    """End-to-end on the shipped dossier path (its own primitive, its own key family), proving the
    credit ledger did not disturb it."""
    from leviathan.graphrag import dossier as ds
    monkeypatch.setenv("GRAPHRAG_AUTH", "on")
    monkeypatch.delenv(ds.ADMIN_FLAG, raising=False)
    s = st.InMemoryStore()
    ident = {"sub": "u"}
    for _ in range(ds.QUOTA_LIMIT):
        assert ds.consume_quota(s, ident) == ds.quota_period()
    with pytest.raises(st.QuotaExceeded):
        ds.consume_quota(s, ident)


@pytest.mark.parametrize("s", _both())
def test_credits_and_the_daily_counter_are_disjoint_keys(s):
    """Two meters, one table: spending credits must not burn daily turns, and vice versa."""
    s.debit("u", PERIOD, 3, 100, op_id="t1:charge")
    s.incr_turn_quota("u", "2026-08-12", 50)
    assert s.read_quota("u", PERIOD) == 3
    assert s.read_quota("u", "2026-08-12") == 1
    s.credit("u", PERIOD, 3, op_id="t1:refund")
    assert s.read_quota("u", PERIOD) == 0
    assert s.read_quota("u", "2026-08-12") == 1                       # the daily turn stays spent


# ── InMemory <-> Dynamo parity, one story run against both ──────────────────────────────────────────
def _story(s) -> list:
    out = []
    out.append(s.debit("u", PERIOD, 1, 5, op_id="a:charge", ref="a"))
    out.append(s.debit("u", PERIOD, 1, 5, op_id="a:charge", ref="a"))
    out.append(s.debit("u", PERIOD, 3, 5, op_id="b:charge", ref="b"))
    out.append(s.read_quota("u", PERIOD))
    try:
        s.debit("u", PERIOD, 3, 5, op_id="c:charge", ref="c")
        out.append("admitted")
    except st.QuotaExceeded:
        out.append("refused")
    out.append(s.credit("u", PERIOD, 3, op_id="b:refund", ref="b"))
    out.append(s.credit("u", PERIOD, 3, op_id="b:refund", ref="b"))
    out.append(s.read_quota("u", PERIOD))
    out.append([(r["kind"], r["amount"], r["ref"], r["balance_after"]) for r in s.list_ledger("u", PERIOD)])
    # Lease legs report ADMISSION, not the token itself: the token is random by design, so the two
    # stores can only agree on the boolean. The token's own semantics are pinned above, on both twins.
    first = s.acquire_lease("u", now=AUG)
    out.append(bool(first))
    out.append(bool(s.acquire_lease("u", now=AUG + 10)))
    taken_over = s.acquire_lease("u", now=AUG + 5000)
    out.append(bool(taken_over))
    out.append(taken_over != first)                                   # the takeover minted a FRESH token
    s.release_lease("u", first)                                       # the fenced-out owner releases nothing
    out.append(bool(s.acquire_lease("u", now=AUG + 5001)))
    s.release_lease("u", taken_over)
    out.append(bool(s.acquire_lease("u", now=AUG + 5002)))
    return out


def test_inmemory_dynamo_parity():
    mem, dyn = st.InMemoryStore(), _dyn()
    assert _story(mem) == _story(dyn)
    assert _story(st.InMemoryStore()) == [
        True, False, True, 4, "refused", True, False, 1,
        [("debit", 1, "a", 1), ("debit", 3, "b", 4), ("credit", 3, "b", 1)],
        True, False, True, True, False, True]                        # the story, spelled out once
