"""THE CASCADE NOTCH -- the ladder's third place, priced and metered, shipping DARK (2026-09-06).

Design: docs/private/SCAN_TIER_DESIGN.md section 3 (F9 the credit ledger, F10 the ceiling check) and the
owner's word of 2026-09-06: "keep Cascade just as we designed it to be the third place on the scaler".

WHAT THIS DECK OWNS, and what it deliberately does not. `tests/unit/test_dmw_credit_seam.py` is and stays
the authority for the SEAM -- the kill switch, the gate order, the 429 body, the lease, the reconcile, the
idempotency. This deck owns the TIER: that a `max` turn costs TWO credits end to end, that `deep` still
costs one and `quick` still costs nothing beside it, that a Cascade turn which cannot fit in the remaining
grant is refused exactly the way an Analysis turn is, and that none of it is reachable until a deployment
NAMES the dark preset in `GRAPHRAG_MODES`.

  1. THE PRICE AND THE METER, together. `_CREDIT_PRICES['max'] == 2` and `rm.is_metered('max')` -- the two
     halves the design says must move in one commit, because a priced tier that reads unmetered declines
     EC-3's fill patience on the dearest turn the product sells.
  2. THE LADDER, MEASURED THROUGH THE ROUTE: quick debits nothing, deep debits 1, max debits 2, on the same
     store, in the same run.
  3. THE REFUSAL, AND THE WORDS IT USES. A grant with ONE credit left refuses Cascade (429, the locked
     body) and still admits Analysis. This is the case a 0/1 ladder never had: "not exhausted" and
     "cannot afford this tier" are different facts, and only the second one is new. BOTH STATES ARE
     PINNED THROUGH THE ROUTE, at the sentence and not at its truthiness -- the 2026-09-07 fix pass,
     which found this deck naming the distinction in a test title while asserting only `body['detail']`
     was non-empty, and the body meanwhile saying `remaining: 1` beside "monthly credit limit reached".
     The sentence is also HALF OF A PAIR: the depth control says the same thing before the submit, and
     from the word "costs" onward the two agree word for word.
  4. THE DARKNESS. With `GRAPHRAG_MODES=quick,deep` a Cascade request is honored as `standard` and charged
     NOTHING -- the gate prices what will ACTUALLY run. The flip is one env value: `quick,deep,max`.
  5. THE UNDELIVERED CASCADE TURN. A floored `max` turn (honored stamp, no walk stamp) nets ZERO, so the
     estate stops billing rather than billing for depth it cannot prove it delivered -- at 2 credits a turn
     that direction matters twice as much as it did at 1.
  6. DEEP RESEARCH IS OFF. `GRAPHRAG_DOSSIER=off` 404s every dossier route, which is what makes the FE's
     dark standalone button and this server agree. Pinned here because the serving revision that ships the
     notch sets `GRAPHRAG_DOSSIER=off` and `GRAPHRAG_MODES=quick,deep,max` TOGETHER.
  7. THE LINT. `config_check.check_cascade_notch()` is green at HEAD -- price, meter, darkness, the arm
     controls' zeros, and the FE roster parity clause that reads store/mode.ts.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st


class _FakeGraph:
    contracts = {"corn": object()}
    version = "gcascade0001"


class _Ledger:
    """The D-MW-23 ledger contract in memory, with a call log. A COMPACT twin of the fake in
    test_dmw_credit_seam: this deck asserts on AMOUNTS, not on the seam's choreography, so it carries only
    what the amounts need. The seam's own deck keeps the full one."""

    def __init__(self, *, pre_spent: int = 0):
        self.calls: list[tuple] = []
        self.spent: dict[tuple, int] = {}
        self.turns: dict[tuple, int] = {}
        self.ops: set = set()
        self.leases: dict = {}
        self.pre_spent = int(pre_spent)

    def _used(self, user_id: str, period: str) -> int:
        return self.spent.get((user_id, period), self.pre_spent)

    def incr_turn_quota(self, user_id: str, day: str, cap: int) -> None:
        self.calls.append(("incr_turn_quota", user_id, day, cap))
        n = self.turns.get((user_id, day), 0)
        if n >= cap:
            raise st.QuotaExceeded(f"daily turn limit {cap} reached")
        self.turns[(user_id, day)] = n + 1

    def read_quota(self, user_id: str, period: str) -> int:
        self.calls.append(("read_quota", user_id, period))
        return self._used(user_id, period)

    def debit(self, user_id: str, period: str, amount: int, cap: int, *, op_id: str,
              ref: str | None = None) -> bool:
        self.calls.append(("debit", user_id, period, amount, cap, op_id, ref))
        if op_id in self.ops:
            return False
        used = self._used(user_id, period)
        if amount > cap or used > cap - amount:      # the legal-expression shape: :limit = cap - amount
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
        self.spent[(user_id, period)] = max(0, self._used(user_id, period) - amount)
        return True

    def acquire_lease(self, user_id: str, *, lease_seconds: int = st.LEASE_SECONDS,
                      now: float | None = None) -> str | None:
        self.calls.append(("acquire_lease", user_id, lease_seconds))
        if self.leases.get(user_id):
            return None
        self.leases[user_id] = f"tok{len(self.calls)}"
        return self.leases[user_id]

    def release_lease(self, user_id: str, token: str | None = None) -> None:
        self.calls.append(("release_lease", user_id, token))
        if token is not None and self.leases.get(user_id) != token:
            return
        self.leases.pop(user_id, None)

    def debits(self) -> list[tuple]:
        """(amount, ref) for every debit that was ATTEMPTED -- the tier's price, as charged."""
        return [(c[3], c[6]) for c in self.calls if c[0] == "debit"]

    def net(self) -> int:
        """Credits consumed. Falls back to the pre-seeded balance when nothing was ever written -- a
        refused debit raises BEFORE it writes, and 'the ledger did not move' has to be readable as the
        number it started at, not as zero."""
        return sum(self.spent.values()) if self.spent else self.pre_spent


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("GRAPHRAG_CREDITS", "GRAPHRAG_CREDITS_LIMIT", "GRAPHRAG_TURN_QUOTA", "GRAPHRAG_MODES",
              "GRAPHRAG_AUTH", "GRAPHRAG_SESSIONS", "GRAPHRAG_DOSSIER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setitem(sv._STATE, "graph", _FakeGraph())


def _use(monkeypatch, store):
    monkeypatch.setitem(sv._STATE, "store", store)
    return store


def _result(honored: str, *, walked: bool = True) -> dict:
    """A respond()-shaped result. `walked` writes the GROUNDED-WALK STAMP that IS the delivery signal."""
    return {"answer": "A", "intent": "reasoning",
            "trace": {"walk_shape": {"n_seeds": 6, "kept_by_depth": {"0": 6}}} if walked else {},
            "intent_decision": {"intent": "reasoning",
                                "mode": {"requested": "max", "honored": honored, "invalid": False}}}


def _client(monkeypatch, fn, *, modes: str = "quick,deep,max", credits: str = "on"):
    from leviathan.graphrag import orchestrator as orch
    monkeypatch.setenv("GRAPHRAG_CREDITS", credits)
    monkeypatch.setenv("GRAPHRAG_MODES", modes)
    monkeypatch.setattr(orch, "respond", fn)
    return TestClient(sv.app)


# ══ 1. THE PRICE AND THE METER MOVE TOGETHER ═════════════════════════════════════════════════════════
def test_max_is_priced_at_two_and_reads_metered():
    """F9's two halves, in one assertion apiece. Either one alone is a defect: a priced-and-unmetered
    `max` bills two credits for a turn EC-3 then treats as unpaid (declining the fill patience the width
    is FOR), and a metered-and-unpriced one delivers the widest walk in the estate for nothing."""
    from leviathan.graphrag import reasoning_modes as rm
    assert sv._CREDIT_PRICES[rm.MAX] == 2
    assert sv._credit_price(rm.MAX) == 2
    assert rm.MAX in rm.METERED_BASES and rm.is_metered(rm.MAX) is True
    # The ladder the product sells, in the two places that decide money.
    assert (sv._credit_price(rm.QUICK), sv._credit_price(rm.DEEP), sv._credit_price(rm.MAX)) == (0, 1, 2)


def test_max_is_still_dark_and_is_honored_only_by_name(monkeypatch):
    """PRICING IS NOT HONORING, and the order is deliberate: the price ships FIRST so the flip can be one
    env value without a window in which the widest tier is free. `serving_names()` is untouched, so
    `GRAPHRAG_MODES=on` cannot sweep Cascade in -- only `quick,deep,max` can."""
    from leviathan.graphrag import orchestrator as orch
    from leviathan.graphrag import reasoning_modes as rm
    assert rm.MAX in rm.DARK_NAMES
    assert rm.serving_names() == frozenset({"quick", "standard", "deep"})
    monkeypatch.setenv("GRAPHRAG_MODES", "on")
    assert rm.MAX not in orch._modes_enabled()              # the wildcard never means a dark preset
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep,max")
    assert rm.MAX in orch._modes_enabled()                  # THE FLIP, in one value


# ══ 2. THE LADDER, THROUGH THE ROUTE ═════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("mode,honored,charged", [("quick", "quick", 0), ("deep", "deep", 1),
                                                  ("max", "max", 2)])
def test_the_ladder_debits_zero_one_two(monkeypatch, mode, honored, charged):
    """THE WHOLE POINT OF THE NOTCH, measured on the same store in the same run: Scan touches the ledger
    not at all, Analysis takes one, Cascade takes two."""
    s = _use(monkeypatch, _Ledger())
    c = _client(monkeypatch, lambda q, **kw: _result(honored))
    r = c.post("/v1/respond", json={"question": "why is corn tight?", "mode": mode})
    assert r.status_code == 200
    if charged == 0:
        assert s.calls == []                                # the free tier never opens the ledger
    else:
        assert s.debits() == [(charged, honored)]
        assert s.net() == charged
        assert not s.leases, "the single-in-flight lease must be released on the way out"


def test_a_cascade_turn_and_an_analysis_turn_land_three_credits_apart(monkeypatch):
    """The two metered tiers on ONE grant, so the arithmetic is visible rather than inferred from two
    separate runs: 1 + 2 = 3 of the grant spent, and the refs name which tier spent which."""
    s = _use(monkeypatch, _Ledger())
    seq = ["deep", "max"]
    c = _client(monkeypatch, lambda q, **kw: _result(seq.pop(0)))
    assert c.post("/v1/respond", json={"question": "q1", "mode": "deep", "turn_id": "t1"}).status_code == 200
    assert c.post("/v1/respond", json={"question": "q2", "mode": "max", "turn_id": "t2"}).status_code == 200
    assert s.debits() == [(1, "deep"), (2, "max")]
    assert s.net() == 3


# ══ 3. THE REFUSAL: "not exhausted" and "cannot afford THIS tier" are different facts ════════════════
def _day() -> str:
    """The UTC calendar day both refusal sentences name -- derived, never a literal, so this deck does
    not go red on the first of a month."""
    return sv._credits_reset_at()[:10]


def test_one_credit_left_refuses_cascade_and_still_admits_analysis(monkeypatch):
    """THE CASE A 0/1 LADDER NEVER HAD. With 99 of 100 spent the grant is not empty -- it simply cannot
    cover a two-credit turn. The debit's own conditional expression (`used > cap - amount`) is what makes
    that true without a second rule, and the refusal is the SAME locked 429 body an exhausted Analysis
    gets: a machine slug in `error`, the human sentence in `detail` (P5 F9).

    AND THE SENTENCE IS ASSERTED, NOT MERELY TRUTHY. This test named the distinction in its own title
    from the day it was written and then checked `body['detail']` for truthiness -- so it stood green
    while the body said `remaining: 1` beside "monthly credit limit (100) reached", one strip above a
    badge reading "1 of 100 this month". `api/errors.creditsRefusalFrom` puts `detail` on
    `CreditsRefusal.message` and `CreditsToast` renders it verbatim, so a false sentence here is a false
    sentence on screen. A truthiness assertion on user-facing copy is not an assertion."""
    monkeypatch.setenv("GRAPHRAG_CREDITS_LIMIT", "100")
    s = _use(monkeypatch, _Ledger(pre_spent=99))
    c = _client(monkeypatch, lambda q, **kw: _result("max"))
    r = c.get("/v1/respond/stream", params={"question": "q", "mode": "max"})
    assert r.status_code == 429
    body = r.json()
    assert set(body) == {"error", "limit", "remaining", "reset_at", "detail"}
    assert body["error"] == "credits_exceeded" and body["limit"] == 100
    assert body["remaining"] == 1
    assert body["detail"] == (f"this tier costs two credits and you have 1 left; "
                              f"the grant resets {_day()} (UTC)")
    assert "reached" not in body["detail"], "a grant with a credit left has NOT reached its limit"
    assert s.net() == 99                                    # nothing was taken

    # ...and the cheaper tier is unaffected by the refusal of the dearer one.
    s2 = _use(monkeypatch, _Ledger(pre_spent=99))
    c2 = _client(monkeypatch, lambda q, **kw: _result("deep"))
    assert c2.post("/v1/respond", json={"question": "q", "mode": "deep"}).status_code == 200
    assert s2.debits() == [(1, "deep")] and s2.net() == 100


def test_a_cascade_turn_with_the_grant_spent_is_refused_exactly_like_deep(monkeypatch):
    """THE OTHER STATE, and its sentence is the SHIPPED one, unchanged by this pass: an empty grant runs
    nothing at any tier, which is what "monthly credit limit reached" has always meant."""
    monkeypatch.setenv("GRAPHRAG_CREDITS_LIMIT", "10")
    _use(monkeypatch, _Ledger(pre_spent=10))
    c = _client(monkeypatch, lambda q, **kw: _result("max"))
    r = c.post("/v1/respond", json={"question": "q", "mode": "max"})
    assert r.status_code == 429 and r.json()["error"] == "credits_exceeded"
    assert r.json()["remaining"] == 0
    assert r.json()["detail"] == f"monthly credit limit (10) reached; credits reset {_day()}"


def test_the_two_refusals_are_told_apart_through_the_route_on_one_ledger(monkeypatch):
    """BOTH STATES, SAME TIER, SAME ROUTE, SAME GRANT SIZE -- the pair, so the difference is a measured
    fact rather than two tests that happen to disagree. 99 of 100 spent CANNOT AFFORD a Cascade turn;
    100 of 100 is EXHAUSTED. The locked five-key body is identical in shape and the sentences are not,
    which is exactly the property this pass added: `remaining` alone was already right, and a body whose
    structured field and whose words disagree is worse than one that only counts."""
    monkeypatch.setenv("GRAPHRAG_CREDITS_LIMIT", "100")
    said: dict = {}
    for pre_spent, state in ((99, "afford"), (100, "exhausted")):
        _use(monkeypatch, _Ledger(pre_spent=pre_spent))
        c = _client(monkeypatch, lambda q, **kw: _result("max"))
        r = c.post("/v1/respond", json={"question": "q", "mode": "max"})
        assert r.status_code == 429
        body = r.json()
        assert set(body) == {"error", "limit", "remaining", "reset_at", "detail"}   # the body is LOCKED
        assert body["error"] == "credits_exceeded" and body["limit"] == 100
        said[state] = (body["remaining"], body["detail"])
    assert said["afford"][0] == 1 and said["exhausted"][0] == 0
    assert said["afford"][1] != said["exhausted"][1], "one sentence for two states is the defect"
    # Each one says the thing that is TRUE of its own state, and not the thing that is true of the other.
    assert "costs two credits and you have 1 left" in said["afford"][1]
    assert "reached" in said["exhausted"][1] and "costs" not in said["exhausted"][1]


def test_the_refusal_sentence_is_the_control_s_sentence_word_for_word():
    """ONE REFUSAL, ONE VOCABULARY. The depth control blocks this turn BEFORE the submit with
    "Cascade costs two credits and you have 1 left - the grant resets <day> (UTC)"
    (apps/terminal/src/shell/DepthControl.blockedReason, pinned verbatim in DepthControl.test.tsx); the
    server refuses the submits the control could not block -- a balance up to 30s stale, a second tab, a
    direct API call -- and must not describe that same fact in different words.

    THE TWO PERMITTED DIFFERENCES, and only these: the control names the tier by LABEL ("Cascade") while
    the server's only name for it is the wire identifier `max` (which never reaches a screen), and the
    clause join is an em dash on a line versus "; " in a sentence. From the word "costs" onward, the words
    are identical. `config_check.check_cascade_notch` clause (vii) is the reader that keeps them so across
    both files; this asserts the server's half at the exact values that clause probes with.

    The FE line below is transcribed with an ASCII hyphen where the control renders U+2014 -- the join is
    the one place the two are allowed to differ anyway, and this deck's failure output is read on a cp1252
    console. The verbatim line, em dash included, is pinned FE-side in DepthControl.test.tsx."""
    srv = sv._credits_refusal_detail(limit=100, remaining=1, needed=2, reset_at="2026-09-01T00:00:00Z")
    fe = "Cascade costs two credits and you have 1 left - the grant resets 2026-09-01 (UTC)"
    assert srv == "this tier costs two credits and you have 1 left; the grant resets 2026-09-01 (UTC)"
    for clause in ("costs two credits and you have 1 left", "the grant resets 2026-09-01 (UTC)"):
        assert clause in srv and clause in fe
    # The server never puts the wire identifier on screen; that is why it says "this tier" at all.
    assert "max" not in srv


@pytest.mark.parametrize("remaining,needed,expect", [(1, 2, "afford"), (0, 2, "reached"),
                                                     (0, 1, "reached"), (3, 2, "reached")])
def test_the_sentence_is_chosen_by_state_and_falls_back_conservatively(remaining, needed, expect):
    """THE THREE-WAY, at its edges. The affordability sentence is claimed ONLY where the numbers support
    it (`0 < remaining < needed`). The last row is the RACE: a post-debit read that says more is left
    than the debit that just failed would allow -- a refund landing between the two. We refuse to invent
    an affordability claim there and say only what is true of every refusal."""
    d = sv._credits_refusal_detail(limit=100, remaining=remaining, needed=needed,
                                   reset_at="2026-09-01T00:00:00Z")
    assert ("costs" in d) is (expect == "afford")
    assert ("reached" in d) is (expect == "reached")


@pytest.mark.parametrize("n,word", [(1, "one credit"), (2, "two credits"), (3, "3 credits")])
def test_a_price_reads_as_words_the_way_the_badge_says_it(n, word):
    """The figures-and-words rule, and the FE twin it mirrors: `CreditsBadge.creditWord` has these same
    three cases. The digit stays on the badge; the PRICE in a sentence reads as words."""
    assert sv._credit_word(n) == word


# ══ 4. THE DARKNESS: the gate prices what will ACTUALLY run ══════════════════════════════════════════
def test_cascade_on_todays_serving_allowlist_is_free_because_it_is_not_honored(monkeypatch):
    """THE STATE THIS COMMIT SHIPS IN. `GRAPHRAG_MODES=quick,deep` is what serving carries today, so a
    Cascade request resolves to `standard` and the gate charges what will run: nothing. The user is not
    billed for a tier the deployment declined to honor -- and the FE half of the same fact is the notch's
    served-roster gate (store/mode.servedModes), which blocks the notch instead of selling that turn."""
    s = _use(monkeypatch, _Ledger())
    c = _client(monkeypatch, lambda q, **kw: _result("standard"), modes="quick,deep")
    assert c.post("/v1/respond", json={"question": "q", "mode": "max"}).status_code == 200
    assert s.calls == []                                    # no debit, no lease, no read


def test_credits_off_leaves_a_cascade_turn_untouched(monkeypatch):
    """THE KILL SWITCH still governs the dearest tier: flag off => not one metering line runs."""
    s = _use(monkeypatch, _Ledger())
    c = _client(monkeypatch, lambda q, **kw: _result("max"), credits="off")
    assert c.post("/v1/respond", json={"question": "q", "mode": "max"}).status_code == 200
    assert s.calls == []


# ══ 5. AN UNDELIVERED CASCADE TURN NETS ZERO ═════════════════════════════════════════════════════════
def test_a_floored_cascade_turn_refunds_all_two_credits(monkeypatch):
    """F2, at twice the stake. The deterministic floor carries the HONORED stamp and no walk stamp, so
    `_honored_mode` reads None and the reconcile hands back the whole charge. At 2 credits a turn, billing
    for depth we cannot prove we delivered is the one failure worth over-correcting for."""
    s = _use(monkeypatch, _Ledger())
    c = _client(monkeypatch, lambda q, **kw: _result("max", walked=False))
    assert c.post("/v1/respond", json={"question": "q", "mode": "max"}).status_code == 200
    assert s.debits() == [(2, "max")]
    assert [c2 for c2 in s.calls if c2[0] == "credit"], "the undelivered turn was never refunded"
    assert s.net() == 0


def test_a_cascade_request_downgraded_to_standard_nets_zero(monkeypatch):
    """The honored-tier DOWNGRADE, on the dearest tier: charged 2 at the gate on the requested-and-allowed
    name, delivered `standard`, so the ledger ends where it started."""
    s = _use(monkeypatch, _Ledger())
    c = _client(monkeypatch, lambda q, **kw: _result("standard"))
    assert c.post("/v1/respond", json={"question": "q", "mode": "max"}).status_code == 200
    assert s.debits() == [(2, "max")]
    assert s.net() == 0


# ══ 6. DEEP RESEARCH IS OFF ON THE REVISION THAT SHIPS THE NOTCH ════════════════════════════════════
@pytest.mark.parametrize("flag", [None, "", "off"])
def test_dossier_routes_404_when_the_flag_is_off(monkeypatch, flag):
    """VERIFIED, THEN PINNED (it already held; nothing in this commit changes it). The FE ships Deep
    Research as a DARK standalone button, and the serving revision that carries the Cascade notch sets
    `GRAPHRAG_DOSSIER=off` in the SAME revision as `GRAPHRAG_MODES=quick,deep,max`. This is the backend
    half of that agreement: with the flag off, `dossier.allowed()` is False and every route 404s --
    indistinguishable from a build that never had the feature, which is what a dark button should mean."""
    if flag is None:
        monkeypatch.delenv("GRAPHRAG_DOSSIER", raising=False)
    else:
        monkeypatch.setenv("GRAPHRAG_DOSSIER", flag)
    _use(monkeypatch, _Ledger())
    c = TestClient(sv.app)
    assert c.post("/v1/dossier", json={"question": "how tight is corn?"}).status_code == 404
    assert c.get("/v1/dossier/quota").status_code == 404
    assert c.get("/v1/dossier/d-1").status_code == 404


def test_the_dossier_flag_is_what_gates_it_not_the_modes_allowlist(monkeypatch):
    """Stated so the two flags are never conflated on a flip: `GRAPHRAG_MODES` decides which TIERS are
    honored; `GRAPHRAG_DOSSIER` decides whether the dossier ROUTES exist. Cascade being served says
    nothing about Deep Research, and that independence is the point of two flags."""
    monkeypatch.setenv("GRAPHRAG_MODES", "quick,deep,max")
    monkeypatch.delenv("GRAPHRAG_DOSSIER", raising=False)
    _use(monkeypatch, _Ledger())
    assert TestClient(sv.app).get("/v1/dossier/quota").status_code == 404


# ══ 7. THE LINT ══════════════════════════════════════════════════════════════════════════════════════
def test_config_check_cascade_notch_is_green():
    """The three-file fact (price / meter / FE roster) has one reader, and it is green at HEAD. Clause
    (vi) is the one with history: it reads `DARK_TIERS` out of apps/terminal/src/store/mode.ts and
    asserts it equals `reasoning_modes.DARK_NAMES` name-for-name -- the census that went stale twice
    because the FE test could only compare it against a literal copy of itself."""
    from leviathan.graphrag import config_check as cc
    assert cc.check_cascade_notch() == []


def test_the_lint_catches_an_unpriced_or_unmetered_cascade(monkeypatch):
    """A lint nobody has seen fail is a lint nobody can trust. Both halves of F9, broken on purpose."""
    from leviathan.graphrag import config_check as cc
    from leviathan.graphrag import reasoning_modes as rm
    monkeypatch.setattr(cc, "_server_credit_prices", lambda: {rm.DEEP: 1})
    errs = cc.check_cascade_notch()
    assert any("not the ratified 2" in e for e in errs)
    monkeypatch.setattr(rm, "METERED_BASES", frozenset({rm.DEEP}))
    assert any("priced but NOT metered" in e for e in cc.check_cascade_notch())


def test_the_lint_catches_the_two_refusal_sentences_drifting_apart(monkeypatch):
    """CLAUSE (vii), BROKEN THREE WAYS. It is the only reader of an agreement that spans two languages,
    so it is the one clause whose failure modes must be seen rather than assumed. Baseline green, then:
    the control's line reworded, the control's line deleted, and the server's template renamed."""
    from leviathan.graphrag import config_check as cc
    assert cc._cascade_refusal_copy_errors() == []
    real = cc._fe_depth_control_text() or ""
    assert "costs ${price}" in real, "the probe's own anchor must exist, or the mutants prove nothing"

    monkeypatch.setattr(cc, "_fe_depth_control_text",
                        lambda: real.replace("and you have ${have}", "and your balance is ${have}"))
    assert any("does not contain the server's own words" in e for e in cc._cascade_refusal_copy_errors())

    monkeypatch.setattr(cc, "_fe_depth_control_text",
                        lambda: real.replace("costs ${price}", "is priced at ${price}"))
    assert any("no affordability line" in e for e in cc._cascade_refusal_copy_errors())

    monkeypatch.setattr(cc, "_fe_depth_control_text", lambda: real)
    monkeypatch.setattr(cc, "_server_module_const", lambda name: None)
    assert any("_CREDITS_INSUFFICIENT_DETAIL is missing" in e
               for e in cc._cascade_refusal_copy_errors())


def test_the_lint_skips_the_copy_clause_when_the_fe_tree_is_absent(monkeypatch):
    """A serving image carries no `apps/`. The clause must NOTE and pass there, never fail on the one
    machine that cannot fix it -- the same rule clause (vi) follows."""
    from leviathan.graphrag import config_check as cc
    monkeypatch.setattr(cc, "_fe_depth_control_text", lambda: None)
    assert cc._cascade_refusal_copy_errors() == []
