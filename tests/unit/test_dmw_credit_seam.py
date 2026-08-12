"""D-MW-24 -- the SERVING CREDIT SEAM (hermetic: no LLM, no AWS, no real store).

What is pinned here, in the order the plan pins it:

  1. THE KILL SWITCH. `GRAPHRAG_CREDITS` absent/off => not one metering line executes and not one store
     call is made on the turn path. The store double asserts this by RAISING on every ledger method.
  2. THE GATE ORDER. Credits are checked on the requested-and-allowlisted tier BEFORE the daily-turn
     increment, so an out-of-credits 429 never burns one of the user's 50 daily turns -- and the reverse,
     a daily-cap 429 after a successful debit, credits the debit back.
  3. THE 429 BODY. `{error, limit, remaining, reset_at, detail}` at the TOP level, from an app-level
     exception handler over `CreditsExceeded` -- the only dependency-raisable, top-level-shaped
     construct. It fires BEFORE the stream opens (status 429, not a 200 that starts streaming).
  4. RECONCILE. Every early-return that delivers no metered depth credits back, idempotently: the
     trivial-router reply, the guardrail refusal, an honored-tier DOWNGRADE (requested deep, honored
     standard -- the ledger nets to ZERO), and any exception before the result event.
  5. THE LEASE. Single-in-flight for metered tiers, released in a finally on every terminal path;
     a concurrent metered turn is refused, an EXPIRED lease is admitted (the lease is not a TTL).
  6. THE COMMIT POINT. The charge commits when the result event is enqueued; a disconnect after compute
     is charged (the recorded trade).

P5 REVIEW FIXES, pinned in sections 10-12 and inside 3/4 above:
  F1  the gate is UNREACHABLE for a params-invalid request -- zero ledger writes, no lease, both routes.
  F2  DELIVERY is the grounded-walk stamp, not the honored-mode stamp: a deterministic-floor turn on the
      metered tier nets ZERO (the floor carries the honored stamp and delivered no depth).
  F4  the charge is IDEMPOTENT across requests off the client's per-question `turn_id`.
  F5  the lease release is OWNERSHIP-FENCED by the token it was admitted with.
  F9  the 429's `error` is a machine slug; the human sentence stays in `detail`.

The store here is a FAKE with a CALL LOG, implementing the D-MW-23 ledger contract this seam calls
(`debit/credit/acquire_lease/release_lease` + the shipped `read_quota`/`incr_turn_quota`). The last
test in the file re-runs the same choreography against the REAL InMemoryStore twin, so a signature
drift between D-MW-23 and this seam cannot hide behind the fake.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st


class _FakeGraph:
    contracts = {"corn": object()}
    version = "gdmw24aabbcc"


class _LedgerStore:
    """The D-MW-23 contract, in memory, with a CALL LOG (the kill-switch pin reads the log)."""

    def __init__(self, *, balance_cap: int | None = None):
        self.calls: list[tuple] = []
        self.spent: dict[tuple, int] = {}          # (user, period) -> credits consumed
        self.turns: dict[tuple, int] = {}          # (user, day) -> daily turns
        self.ops: set = set()                      # op_id idempotency keys
        self.leases: dict = {}                     # user -> True while held
        self.balance_cap = balance_cap             # pre-spend the grant down to this many remaining

    # ── the shipped meters (byte-untouched primitives) ────────────────────────────────────────────
    def incr_turn_quota(self, user_id: str, day: str, cap: int) -> None:
        self.calls.append(("incr_turn_quota", user_id, day, cap))
        n = self.turns.get((user_id, day), 0)
        if n >= cap:
            raise st.QuotaExceeded(f"daily turn limit {cap} reached")
        self.turns[(user_id, day)] = n + 1

    def read_quota(self, user_id: str, period: str) -> int:
        self.calls.append(("read_quota", user_id, period))
        return int(self.spent.get((user_id, period), 0))

    # ── the ledger (D-MW-23) ──────────────────────────────────────────────────────────────────────
    def debit(self, user_id: str, period: str, amount: int, cap: int, *, op_id: str,
              ref: str | None = None) -> bool:
        self.calls.append(("debit", user_id, period, amount, cap, op_id, ref))
        if op_id in self.ops:                      # idempotent: a client retry is a no-op
            return False
        used = self.spent.get((user_id, period), 0)
        if amount > cap or used > cap - amount:    # the legal-expression shape: :limit = cap - amount
            raise st.QuotaExceeded(f"credit limit {cap} reached")
        self.ops.add(op_id)
        self.spent[(user_id, period)] = used + amount
        return True

    def credit(self, user_id: str, period: str, amount: int, *, op_id: str,
               ref: str | None = None) -> bool:
        self.calls.append(("credit", user_id, period, amount, op_id, ref))
        if op_id in self.ops:
            return False
        self.ops.add(op_id)
        self.spent[(user_id, period)] = max(0, self.spent.get((user_id, period), 0) - amount)
        return True

    def acquire_lease(self, user_id: str, *, lease_seconds: int = st.LEASE_SECONDS,
                      now: float | None = None) -> str | None:
        self.calls.append(("acquire_lease", user_id, lease_seconds))
        if self.leases.get(user_id):
            return None
        self.leases[user_id] = f"tok{len(self.calls)}"                # the OWNER TOKEN (F5)
        return self.leases[user_id]

    def release_lease(self, user_id: str, token: str | None = None) -> None:
        self.calls.append(("release_lease", user_id, token))
        if token is not None and self.leases.get(user_id) != token:
            return                                                    # ownership-fenced, like both stores
        self.leases.pop(user_id, None)

    # ── conveniences for the tests ────────────────────────────────────────────────────────────────
    def kinds(self) -> list:
        return [c[0] for c in self.calls]

    def balance(self, user: str, limit: int = 100) -> int:
        return limit - self.spent.get((user, sv._credits_period()), 0)


class _RefusingStore(_LedgerStore):
    """Every method RAISES. Any store touch on a kill-switch-off turn is therefore a hard failure."""

    def _boom(self, *a, **kw):
        raise AssertionError("the store was touched with GRAPHRAG_CREDITS off")

    debit = credit = acquire_lease = release_lease = read_quota = _boom


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("GRAPHRAG_CREDITS", "GRAPHRAG_CREDITS_LIMIT", "GRAPHRAG_TURN_QUOTA",
              "GRAPHRAG_MODES", "GRAPHRAG_AUTH", "GRAPHRAG_SESSIONS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setitem(sv._STATE, "graph", _FakeGraph())


def _use(monkeypatch, store):
    monkeypatch.setitem(sv._STATE, "store", store)
    return store


def _respond(monkeypatch, fn):
    from leviathan.graphrag import orchestrator as orch
    monkeypatch.setattr(orch, "respond", fn)
    return TestClient(sv.app)


def _result(honored: str | None = "standard", answer: str = "A", walked: bool = True) -> dict:
    """A respond()-shaped result carrying (or not carrying) the honored-mode stamp.

    `walked` writes the GROUNDED-WALK STAMP `trace.walk_shape` that planner.grounded_subgraph puts on
    every walk. It is the reconcile's delivery signal (F2), so a DELIVERED turn must carry it and every
    no-depth lane must not — see `_floor_result` for the population that carries the honored stamp and
    no walk at all."""
    out: dict = {"answer": answer, "intent": "reasoning",
                 "trace": {"walk_shape": {"n_seeds": 3, "kept_by_depth": {"0": 3}}} if walked else {}}
    if honored is not None:
        out["intent_decision"] = {"intent": "reasoning", "mode": {"requested": "deep",
                                                                 "honored": honored, "invalid": False}}
    else:
        out["intent_decision"] = {"intent": "social", "trivial": "greeting"}   # the early-return shape
    return out


def _floor_result(honored: str = "deep") -> dict:
    """THE DETERMINISTIC FLOOR, exactly as orchestrator.py emits it: the '(analysis engine unavailable)'
    banner plus raw evidence lines, `trace.floor` set, NO walk stamp -- and the honored-mode stamp still
    present, because `res['intent_decision'] = decided` runs on the way out, after the floor replaced the
    branch. Historically 17.6% of all turns."""
    return {"answer": "(analysis engine unavailable)\n\n- [2026-08-01] a source: text",
            "intent": "reasoning", "model": "(unavailable)",
            "trace": {"floor": "evidence_only", "floor_cause": "provider_5xx",
                      "error": "RuntimeError: provider down"},
            "intent_decision": {"intent": "reasoning",
                                "mode": {"requested": "deep", "honored": honored, "invalid": False}}}


def _metered(monkeypatch, honored: str = "deep"):
    """Credits ON, deep honored by the allowlist, and a respond() that returns that honored stamp."""
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep")
    return _respond(monkeypatch, lambda q, **kw: _result(honored))


# ══ 1. THE KILL SWITCH ═══════════════════════════════════════════════════════════════════════════════
def test_credits_off_makes_zero_store_calls_on_the_turn_path(monkeypatch):
    """DARK-FIRST: with the flag absent, the request path is byte-identical to its pre-D-MW self."""
    _use(monkeypatch, _RefusingStore())
    c = _respond(monkeypatch, lambda q, **kw: _result("deep"))
    r = c.post("/v1/respond", json={"question": "corn?", "mode": "deep"})
    assert r.status_code == 200 and r.json()["answer"] == "A"


def test_credits_off_leaves_no_charge_on_the_identity_and_never_settles(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    c = _respond(monkeypatch, lambda q, **kw: _result("deep"))
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.calls == []                       # no debit, no lease, no read -- nothing at all
    assert sv._credit_gate({"sub": "u"}, "deep") is None


@pytest.mark.parametrize("value,on", [("on", True), ("1", True), ("true", True), ("TRUE", True),
                                      ("off", False), ("", False), ("maybe", False)])
def test_the_kill_switch_grammar(monkeypatch, value, on):
    monkeypatch.setenv("GRAPHRAG_CREDITS", value)
    assert sv._credits_on() is on


def test_credits_absent_is_off(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_CREDITS", raising=False)
    assert sv._credits_on() is False


# ══ 2. THE PRICE TABLE (the 2-notch ship) ════════════════════════════════════════════════════════════
def test_only_deep_is_priced_and_the_dark_tiers_are_absent():
    """Scan (quick) is UNMETERED; max/max_c0 are DARK and therefore carry no price at all."""
    from leviathan.graphrag import reasoning_modes as rm
    assert sv._CREDIT_PRICES == {rm.DEEP: 1}
    assert sv._credit_price(rm.QUICK) == 0 and sv._credit_price(rm.STANDARD) == 0
    assert sv._credit_price(rm.MAX) == 0 and sv._credit_price(rm.MAX_C0) == 0
    assert sv._credit_price(None) == 0 and sv._credit_price("nonsense") == 0


def test_a_quick_turn_is_unmetered_even_with_credits_on(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep")
    c = _respond(monkeypatch, lambda q, **kw: _result("quick"))
    assert c.post("/v1/respond", json={"question": "q", "mode": "quick"}).status_code == 200
    assert s.calls == []                       # the default experience never touches the ledger


def test_a_tier_the_allowlist_does_not_honor_is_not_charged(monkeypatch):
    """The gate prices what will ACTUALLY run: deep requested, allowlist dark => standard => free."""
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")            # GRAPHRAG_MODES absent => nothing honored
    c = _respond(monkeypatch, lambda q, **kw: _result("standard"))
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.calls == []


# ══ 3. THE GATE: DEBIT, ORDER, AND THE 429 ═══════════════════════════════════════════════════════════
def test_a_deep_turn_debits_one_credit(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    c = _metered(monkeypatch)
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.balance("local", 100) == 99
    assert [k for k in s.kinds() if k in ("acquire_lease", "debit", "credit", "release_lease")] == \
        ["acquire_lease", "debit", "release_lease"]             # lease -> charge -> release, no refund


def test_the_429_body_is_top_level_shaped(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS_LIMIT", "2")
    s.spent[("local", sv._credits_period())] = 2                # grant fully spent
    c = _metered(monkeypatch)
    r = c.post("/v1/respond", json={"question": "q", "mode": "deep"})
    assert r.status_code == 429
    body = r.json()
    assert set(body) == {"error", "limit", "remaining", "reset_at", "detail"}
    # F9: `error` is a MACHINE SLUG (the FE types it as `CreditsRefusal.code`); the sentence is `detail`.
    assert body["error"] == "credits_exceeded" == sv._CREDITS_ERROR_CODE
    assert body["error"] not in body["detail"]                  # the slug is not the human sentence
    assert body["limit"] == 2 and body["remaining"] == 0
    assert body["reset_at"].endswith("T00:00:00Z") and body["reset_at"][8:10] == "01"
    assert isinstance(body["detail"], str) and str(body["limit"]) in body["detail"]


def test_an_out_of_credits_429_does_not_burn_a_daily_turn(monkeypatch):
    """THE PINNED ORDER: credits first, the daily counter only after."""
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_TURN_QUOTA", "50")
    monkeypatch.setenv("GRAPHRAG_CREDITS_LIMIT", "1")
    s.spent[("local", sv._credits_period())] = 1
    c = _metered(monkeypatch)
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 429
    assert "incr_turn_quota" not in s.kinds()
    assert s.turns == {}


def test_a_daily_cap_429_credits_the_debit_back(monkeypatch):
    """The reverse hazard: the debit succeeded, then the daily cap refused the turn -- net zero."""
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_TURN_QUOTA", "1")
    c = _metered(monkeypatch)
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    r = c.post("/v1/respond", json={"question": "q", "mode": "deep"})
    assert r.status_code == 429 and "daily turn limit" in r.json()["detail"]
    assert s.balance("local", 100) == 99                        # the second turn's credit came back
    assert s.leases == {}                                       # and its lease was released


def test_the_429_fires_before_the_stream_opens(monkeypatch):
    """A StreamingResponse cannot 429 once its generator starts, so the refusal must be the STATUS."""
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS_LIMIT", "1")
    s.spent[("local", sv._credits_period())] = 1
    c = _metered(monkeypatch)
    with c.stream("GET", "/v1/respond/stream", params={"question": "q", "mode": "deep"}) as r:
        assert r.status_code == 429
        text = "".join(r.iter_text())
    assert "event: stage" not in text and "event: result" not in text
    assert json.loads(text)["error"] == "credits_exceeded"


def test_the_gate_reads_the_mode_from_the_stream_query_param(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    c = _metered(monkeypatch)
    with c.stream("GET", "/v1/respond/stream", params={"question": "q", "mode": "deep"}) as r:
        assert r.status_code == 200
        "".join(r.iter_text())
    assert s.balance("local", 100) == 99


def test_the_post_body_stays_top_level_when_the_dependency_declares_it(monkeypatch):
    """FastAPI counts body params by NAME: the dependency's `body` and the handler's `body` are one
    field, so the wire contract is unchanged (two names would EMBED the body and break every client)."""
    seen = {}
    _use(monkeypatch, _LedgerStore())
    c = _respond(monkeypatch, lambda q, **kw: seen.update(q=q, mode=kw.get("mode")) or _result("standard"))
    r = c.post("/v1/respond", json={"question": "corn outlook", "mode": "deep", "session_id": "s1"})
    assert r.status_code == 200 and seen == {"q": "corn outlook", "mode": "deep"}


def test_the_openapi_body_is_still_a_bare_ask(monkeypatch):
    """The same pin read off the SCHEMA, where an accidental embed would show up as a Body_ wrapper."""
    spec = TestClient(sv.app).get("/openapi.json").json()
    body = spec["paths"]["/v1/respond"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/Ask"}
    params = [p["name"] for p in spec["paths"]["/v1/respond/stream"]["get"]["parameters"]]
    assert params.count("mode") == 1                            # one query param, not two


# ══ 4. STEP 2 -- RECONCILE ═══════════════════════════════════════════════════════════════════════════
def test_max_requested_honored_standard_nets_the_ledger_to_zero(monkeypatch):
    """THE PINNED RECONCILE: a user is never charged for depth they did not receive."""
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "deep")               # deep priced+honored, max is not honored
    c = _respond(monkeypatch, lambda q, **kw: _result("standard"))   # the DOWNGRADE
    # deep is what the gate charges for; the turn comes back honored=standard.
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.balance("local", 100) == 100
    assert s.kinds().count("debit") == 1 and s.kinds().count("credit") == 1


def test_a_max_request_is_never_charged(monkeypatch):
    """THE RATIFIED ADJUSTMENT to the plan's 'max-requested-honored-standard nets zero' pin: the 2-notch
    ship gives max NO PRICE, so the property holds one step earlier -- a max request never enters the
    ledger at all, whether the allowlist honors it (the dark eval arm) or downgrades it."""
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    for allowlist, honored in (("deep", "standard"), ("max", "max")):
        monkeypatch.setenv("GRAPHRAG_MODES", allowlist)
        c = _respond(monkeypatch, lambda q, **kw: _result(honored))
        assert c.post("/v1/respond", json={"question": "q", "mode": "max"}).status_code == 200
    assert s.calls == [] and s.balance("local", 100) == 100


def test_a_deterministic_floor_turn_on_the_metered_tier_nets_ZERO(monkeypatch):
    """F2, THE PINNED REFUND: the floor delivers a service banner plus raw evidence lines -- no synthesis,
    no cascade, no walk -- and it carries the honored-mode stamp anyway (orchestrator stamps
    `intent_decision` on the way OUT, after the floor replaced the branch). Reading that stamp alone
    charged a full credit for the single largest no-depth population in the estate."""
    s = _use(monkeypatch, st.InMemoryStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep")
    period = sv._credits_period()
    c = _respond(monkeypatch, lambda q, **kw: _floor_result("deep"))
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.read_quota("local", period) == 0                   # charged, then credited back: NET ZERO
    assert [r_["kind"] for r_ in s.list_ledger("local", period)] == ["debit", "credit"]
    assert s._leases == {}


def test_the_delivery_signal_is_the_walk_stamp_not_the_honored_stamp():
    """The unit form of the same fix, stated as the rule: `_honored_mode` reads as DELIVERED only when the
    grounded-walk artifact is on the trace. Both no-walk lanes read as delivered-nothing."""
    assert sv._honored_mode(_result("deep")) == "deep"                       # a real walk
    assert sv._honored_mode(_floor_result("deep")) is None                   # the floor
    assert sv._honored_mode(_result("deep", walked=False)) is None           # any other no-walk lane
    assert sv._honored_mode(None) is None
    assert sv._grounded_walk_ran(_result("deep")) is True
    assert sv._grounded_walk_ran(_floor_result("deep")) is False


@pytest.mark.parametrize("early", ["trivial", "guardrail"])
def test_early_returns_credit_back(monkeypatch, early):
    """The trivial-router reply and the guardrail refusal both return ABOVE the mode resolution, so
    neither carries an honored stamp -- and neither is charged."""
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "deep")
    canned = ({"answer": "hi", "intent": "social", "intent_decision": {"intent": "social",
                                                                      "trivial": "greeting"}}
              if early == "trivial" else
              {"answer": "I can't help with that.", "intent": "refused", "intent_decision": {}})
    c = _respond(monkeypatch, lambda q, **kw: dict(canned))
    assert c.post("/v1/respond", json={"question": "hello", "mode": "deep"}).status_code == 200
    assert s.balance("local", 100) == 100


def test_a_pre_result_exception_credits_back_on_the_post_route(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "deep")

    def boom(q, **kw):
        raise RuntimeError("engine down")

    c = _respond(monkeypatch, boom)
    with pytest.raises(RuntimeError):
        c.post("/v1/respond", json={"question": "q", "mode": "deep"})
    assert s.balance("local", 100) == 100 and s.leases == {}


def test_a_pre_result_exception_credits_back_on_the_stream(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "deep")

    def boom(q, **kw):
        raise RuntimeError("engine down")

    c = _respond(monkeypatch, boom)
    with c.stream("GET", "/v1/respond/stream", params={"question": "q", "mode": "deep"}) as r:
        text = "".join(r.iter_text())
    assert "event: error" in text
    assert s.balance("local", 100) == 100 and s.leases == {}


def test_the_refund_is_idempotent(monkeypatch):
    """A double settle (the store op_id AND the local `settled` flag) refunds exactly once."""
    s = _use(monkeypatch, _LedgerStore())
    charge = {"sub": "u", "period": sv._credits_period(), "amount": 1, "op_id": "turn-x",
              "honored": "deep", "lease": False, "settled": False}
    s.spent[("u", charge["period"])] = 1
    sv._settle_credit(charge, None)
    sv._settle_credit(charge, None)
    sv._settle_credit(dict(charge, settled=False), None)        # a fresh record, same op_id
    assert s.spent[("u", charge["period"])] == 0
    assert s.kinds().count("credit") == 2                       # called twice, applied once


def test_a_delivered_turn_is_not_refunded_by_a_later_failure(monkeypatch):
    """The commit is the RESULT ENQUEUE: a failure after it (persistence, a broken pipe) is still a
    delivered, charged turn."""
    s = _use(monkeypatch, _LedgerStore())
    charge = {"sub": "u", "period": sv._credits_period(), "amount": 1, "op_id": "turn-y",
              "honored": "deep", "lease": False, "settled": False}
    s.spent[("u", charge["period"])] = 1
    sv._settle_credit(charge, _result("deep"))                  # commit: delivered == charged, no refund
    sv._settle_credit(charge, None)                             # the late failure path: no-op
    assert s.spent[("u", charge["period"])] == 1 and "credit" not in s.kinds()


def test_the_charge_never_leaks_onto_the_saved_turn(monkeypatch):
    """The private slot is POPPED in the handler: nothing downstream (history, profile) sees it."""
    s = _use(monkeypatch, _LedgerStore())
    seen = {}
    monkeypatch.setattr(sv, "_save_turn", lambda ident, sid, res, question="": seen.update(ident=dict(ident)))
    c = _metered(monkeypatch)
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert sv._CREDIT_KEY not in seen["ident"]


# ══ 5. THE SINGLE-IN-FLIGHT LEASE ════════════════════════════════════════════════════════════════════
def test_a_concurrent_metered_turn_is_refused(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    s.leases["local"] = True                                    # another turn holds the lease
    c = _metered(monkeypatch)
    r = c.post("/v1/respond", json={"question": "q", "mode": "deep"})
    assert r.status_code == 429 and "already running" in r.json()["detail"]
    assert "debit" not in s.kinds()                             # refused BEFORE the charge


def test_an_expired_lease_admits_the_turn(monkeypatch):
    """The lease is not a TTL: expiry is an ADMISSION CONDITION at the store, so a crashed turn cannot
    lock a user out for the up-to-48h a DynamoDB TTL sweep may take. Exercised on the REAL twin -- the
    expiry branch is the store's, and a fake that always admits would prove nothing."""
    s = _use(monkeypatch, st.InMemoryStore())
    s._leases["local"] = (time.time() - 1, "stale-owner")       # a lease that expired one second ago
    c = _metered(monkeypatch)
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.read_quota("local", sv._credits_period()) == 1     # admitted AND charged


def test_the_lease_horizon_is_the_stores_fifteen_minutes(monkeypatch):
    """The seam does NOT re-declare the horizon: it calls `acquire_lease` bare so `LEASE_SECONDS` stays
    the one authority (a second constant here is how the two drift)."""
    s = _use(monkeypatch, _LedgerStore())
    c = _metered(monkeypatch)
    c.post("/v1/respond", json={"question": "q", "mode": "deep"})
    assert st.LEASE_SECONDS == 900
    assert [c_ for c_ in s.calls if c_[0] == "acquire_lease"][0][2] == 900


def test_the_lease_is_released_on_the_stream_path(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    c = _metered(monkeypatch)
    with c.stream("GET", "/v1/respond/stream", params={"question": "q", "mode": "deep"}) as r:
        "".join(r.iter_text())
    assert s.leases == {} and s.kinds().count("release_lease") == 1


# ══ 6. FAIL-OPEN ═════════════════════════════════════════════════════════════════════════════════════
def test_a_store_error_runs_the_turn_unmetered(monkeypatch):
    """The `_metered_identity_quota` fail-open law: an infra glitch must never refuse a paying user."""
    s = _use(monkeypatch, _LedgerStore())

    def dead_debit(*a, **kw):
        raise RuntimeError("dynamo down")

    s.debit = dead_debit
    c = _metered(monkeypatch)
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.leases == {}                                       # and the lease it took was given back


def test_a_lease_error_admits_the_turn(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())

    def dead_lease(*a, **kw):
        raise RuntimeError("dynamo down")

    s.acquire_lease = dead_lease
    c = _metered(monkeypatch)
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.balance("local", 100) == 99                        # still charged; only the lease degraded


# ══ 7. THE BADGE READ ════════════════════════════════════════════════════════════════════════════════
def test_the_badge_is_a_404_when_metering_is_dark(monkeypatch):
    """DARK IS NOT AN ERROR (the dossier-gate idiom, and what api/credits.ts codes against): no meter
    exists, so there is nothing to report and the FE renders no badge -- not a broken one."""
    s = _use(monkeypatch, _LedgerStore())
    assert TestClient(sv.app).get("/v1/credits").status_code == 404
    assert s.calls == []                                        # a dark badge reads nothing


def test_the_badge_reports_the_balance_and_the_reset(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    s.spent[("local", sv._credits_period())] = 7
    body = TestClient(sv.app).get("/v1/credits").json()
    assert body == {"remaining": 93, "limit": 100, "reset_at": sv._credits_reset_at()}


def test_the_badge_fails_open_to_a_full_grant(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())

    def dead_read(*a, **kw):
        raise RuntimeError("dynamo down")

    s.read_quota = dead_read
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    assert TestClient(sv.app).get("/v1/credits").json()["remaining"] == 100


# ══ 8. THE PERIOD KEY ════════════════════════════════════════════════════════════════════════════════
def test_the_period_and_the_reset_are_the_stores_one_authority():
    """The seam DELEGATES both (a second derivation here is how a user is told 'resets September 1' and
    is still refused on September 1)."""
    dec = 1797000000.0                                          # 2026-12-09T14:40:00Z
    assert sv._credits_period(dec) == st.credits_period(dec) == "credits#2026-12"
    assert sv._credits_reset_at(dec) == st.credits_reset_at(dec) == "2027-01-01T00:00:00Z"


def test_the_row_key_is_the_pinned_one():
    """`quota#` + the period => sk='quota#credits#YYYY-MM', disjoint from the three shipped meters."""
    assert sv._credits_period().startswith("credits#")
    assert len(sv._credits_period()) == len("credits#YYYY-MM")


def test_the_limit_env_is_read_with_a_ratified_default(monkeypatch):
    assert sv._credits_limit() == 100
    monkeypatch.setenv("GRAPHRAG_CREDITS_LIMIT", "250")
    assert sv._credits_limit() == 250
    monkeypatch.setenv("GRAPHRAG_CREDITS_LIMIT", "not-a-number")
    assert sv._credits_limit() == 100


# ══ 9. THE INTEGRATION CONTRACT (the seam against the REAL store twin) ═══════════════════════════════
def test_the_whole_seam_runs_against_the_real_store_twin(monkeypatch):
    """No fake: the D-MW-23 InMemoryStore, driven through the HTTP surface. This is what catches a
    signature drift between the ledger and this seam -- charge, refuse, refund, and the daily meter
    left untouched by the refusal."""
    s = _use(monkeypatch, st.InMemoryStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS_LIMIT", "2")
    monkeypatch.setenv("GRAPHRAG_TURN_QUOTA", "50")
    period = sv._credits_period()
    c = _metered(monkeypatch)
    for _ in range(2):
        assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.read_quota("local", period) == 2 and s.read_quota("local", sv._today()) == 2
    r = c.post("/v1/respond", json={"question": "q", "mode": "deep"})     # grant spent
    assert r.status_code == 429 and r.json()["remaining"] == 0
    assert s.read_quota("local", sv._today()) == 2                       # the 429 burned no daily turn
    assert TestClient(sv.app).get("/v1/credits").json()["remaining"] == 0
    # ...and the ledger tells the story: two debits, no refunds, balances 1 then 2.
    rows = s.list_ledger("local", period)
    assert [r_["kind"] for r_ in rows] == ["debit", "debit"]
    assert [r_["balance_after"] for r_ in rows] == [1, 2] and {r_["ref"] for r_ in rows} == {"deep"}


def test_a_downgrade_against_the_real_store_twin_nets_to_zero(monkeypatch):
    """The pinned reconcile, end to end on the real ledger: one debit, one credit, net zero, and BOTH
    rows present for the audit."""
    s = _use(monkeypatch, st.InMemoryStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "deep")
    period = sv._credits_period()
    c = _respond(monkeypatch, lambda q, **kw: _result("standard"))
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s.read_quota("local", period) == 0
    assert [r_["kind"] for r_ in s.list_ledger("local", period)] == ["debit", "credit"]
    assert s._leases == {}


# ══ 10. THE VALIDATION FENCE (F1) ════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("route", ["stream", "post"])
def test_a_params_invalid_request_never_reaches_the_gate(monkeypatch, route):
    """THE BLOCKER THIS CLOSES: FastAPI solves sub-dependencies BEFORE it validates the path operation's
    own params, so a gate declaring only always-valid params could never be SKIPPED. `GET
    /v1/respond/stream?mode=deep` (no question) debited a credit and took the 15-minute lease, then 422'd
    -- and a 422 never enters the generator where every settle and release lives. One credit destroyed,
    metered depth locked out for 15 minutes. The fix is that the dependency declares the endpoint's OWN
    required param, so an invalid request errors in the dependency's params and the gate is not called."""
    s = _use(monkeypatch, _LedgerStore())
    c = _metered(monkeypatch)
    if route == "stream":
        r = c.get("/v1/respond/stream", params={"mode": "deep"})     # no `question`
    else:
        r = c.post("/v1/respond", json={"mode": "deep"})             # no `question`
    assert r.status_code == 422
    assert s.calls == []                                             # ZERO ledger writes...
    assert s.leases == {} and s.spent == {}                          # ...and NO lease, on both routes


# ══ 11. IDEMPOTENT CHARGES (F4) ══════════════════════════════════════════════════════════════════════
def test_two_gate_invocations_with_the_same_turn_id_debit_ONCE(monkeypatch):
    """THE PINNED IDEMPOTENCY, through the HTTP surface. The FE mints one turn id per question and reuses
    it across an SSE reconnect or a retry, so the ledgerop marker collapses the replay: two identical
    submissions of one question cost ONE credit, and the replay's reconcile is a no-op (refunding there
    would give back the ORIGINAL request's credit and hand a delivered turn away for free)."""
    s = _use(monkeypatch, st.InMemoryStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep")
    period = sv._credits_period()
    c = _respond(monkeypatch, lambda q, **kw: _result("deep"))
    body = {"question": "corn?", "mode": "deep", "turn_id": "b7c1-fixed"}
    for _ in range(2):
        assert c.post("/v1/respond", json=body).status_code == 200
    assert s.read_quota("local", period) == 1                        # charged ONCE, not twice
    assert [r_["kind"] for r_ in s.list_ledger("local", period)] == ["debit"]


def test_the_same_turn_id_survives_a_stream_retry_of_one_question(monkeypatch):
    """The GET twin: `turn_id` is a query param, so an SSE reconnect of the same question is the same op."""
    s = _use(monkeypatch, st.InMemoryStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep")
    c = _respond(monkeypatch, lambda q, **kw: _result("deep"))
    for _ in range(2):
        with c.stream("GET", "/v1/respond/stream",
                      params={"question": "q", "mode": "deep", "turn_id": "t-42"}) as r:
            assert r.status_code == 200
            "".join(r.iter_text())
    assert s.read_quota("local", sv._credits_period()) == 1


def test_two_different_questions_are_two_charges(monkeypatch):
    """The other half of the property: idempotency must not collapse two REAL turns into one."""
    s = _use(monkeypatch, st.InMemoryStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep")
    c = _respond(monkeypatch, lambda q, **kw: _result("deep"))
    for tid in ("t-1", "t-2"):
        assert c.post("/v1/respond",
                      json={"question": "q", "mode": "deep", "turn_id": tid}).status_code == 200
    assert s.read_quota("local", sv._credits_period()) == 2


def test_the_op_id_is_derived_from_the_subject_and_the_turn_id():
    """One user's turn id can never collide with another's, the id is sanitised because it lands in a
    DynamoDB sort key, and an ABSENT turn id falls back to a random op (recorded: a bare-curl caller has
    no cross-request idempotency -- the lease is its only protection)."""
    assert sv._op_id("u1", "abc") == "turn-u1-abc"
    assert sv._op_id("u2", "abc") != sv._op_id("u1", "abc")
    assert sv._op_id("u1", "a/b#c ../x") == "turn-u1-abcx"                       # only [A-Za-z0-9_-] survives
    assert sv._op_id("u1", "x" * 200) == "turn-u1-" + "x" * 64                   # bounded
    assert sv._op_id("u1", None) != sv._op_id("u1", None)                        # random when absent
    assert sv._op_id("u1", "") != sv._op_id("u1", "")


def test_a_replay_does_not_refund_the_original_charge(monkeypatch):
    """The replay's charge record is stamped `applied=False`, so its settle is a local no-op. Without it a
    replay that delivered nothing would credit back the credit the FIRST, delivered turn paid."""
    s = _use(monkeypatch, st.InMemoryStore())
    monkeypatch.setenv("GRAPHRAG_CREDITS", "on")
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep")
    period = sv._credits_period()
    c = _respond(monkeypatch, lambda q, **kw: _result("deep"))
    body = {"question": "q", "mode": "deep", "turn_id": "same"}
    assert c.post("/v1/respond", json=body).status_code == 200        # delivered + charged
    c2 = _respond(monkeypatch, lambda q, **kw: _floor_result("deep"))  # the replay FLOORS
    assert c2.post("/v1/respond", json=body).status_code == 200
    assert s.read_quota("local", period) == 1                         # the delivered turn stays charged
    assert [r_["kind"] for r_ in s.list_ledger("local", period)] == ["debit"]


# ══ 12. THE LEASE OWNERSHIP FENCE AT THE SEAM (F5) ═══════════════════════════════════════════════════
def test_the_seam_releases_with_the_token_it_was_admitted_with(monkeypatch):
    s = _use(monkeypatch, _LedgerStore())
    c = _metered(monkeypatch)
    assert c.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    took = [c_ for c_ in s.calls if c_[0] == "acquire_lease"]
    gave = [c_ for c_ in s.calls if c_[0] == "release_lease"]
    assert len(took) == 1 and len(gave) == 1
    assert gave[0][2] == "tok1"                                       # the token, not a bare user id
    assert s.leases == {}
