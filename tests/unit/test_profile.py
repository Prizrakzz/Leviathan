"""Phase 6.6 — settings / profile facts / onboarding backend. Hermetic: InMemory store, stub Dynamo
clients, no AWS / no LLM. Covers store.update_profile (both backends), get_profile decoding, the
auth-gated GET/PUT /v1/profile routes + fact sanitization, and the suggester facts-fold (W5)."""
from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from leviathan.graphrag import api_models as M
from leviathan.graphrag import server as sv
from leviathan.graphrag import store as st


def _client(monkeypatch):
    monkeypatch.setitem(sv._STATE, "store", st.InMemoryStore())
    return TestClient(sv.app)


# ── store: update_profile (InMemory) ─────────────────────────────────────────────────────────────────
def test_update_profile_inmemory_facts_and_onboarded():
    s = st.InMemoryStore()
    s.update_profile("u1", facts={"markets": ["coffee"]})
    p = s.get_profile("u1")
    assert p["facts"] == {"markets": ["coffee"]} and "onboarded" not in p
    s.update_profile("u1", onboarded=True)                             # partial: facts unchanged, flag set
    p = s.get_profile("u1")
    assert p["facts"] == {"markets": ["coffee"]} and p["onboarded"] is True
    first_ob = p["onboarded_at"]
    s.update_profile("u1", facts={"markets": ["sugar"]})              # facts REPLACED wholesale
    s.update_profile("u1", onboarded=True)                            # onboarded_at is sticky (if_not_exists)
    p = s.get_profile("u1")
    assert p["facts"] == {"markets": ["sugar"]} and p["onboarded_at"] == first_ob


def test_update_profile_inmemory_noop_when_all_none():
    s = st.InMemoryStore()
    s.update_profile("u1")                                            # creates the record but sets nothing
    p = s.get_profile("u1")
    assert p is not None and "facts" not in p and "onboarded" not in p


def test_touch_and_update_profile_share_one_item_disjoint_attrs():
    """The two writers touch disjoint attributes on the same profile item — neither clobbers the other."""
    s = st.InMemoryStore()
    s.touch_profile("u1", email="a@b.c", name="Alice")               # bookkeeping
    s.update_profile("u1", facts={"seat": "trader"}, onboarded=True)  # prefs
    p = s.get_profile("u1")
    assert p["email"] == "a@b.c" and p["turn_count"] == 1
    assert p["facts"] == {"seat": "trader"} and p["onboarded"] is True


# ── store: update_profile + get_profile (Dynamo) ─────────────────────────────────────────────────────
def test_update_profile_dynamo_update_expression():
    calls = []

    class _Db:
        def update_item(self, **kw):
            calls.append(kw)

    s = st.DynamoStore(table="t", client=_Db())
    s.update_profile("u1", facts={"markets": ["coffee", "sugar"]}, onboarded=True)
    kw = calls[0]
    assert kw["Key"] == {"pk": {"S": "user#u1"}, "sk": {"S": "profile"}}
    expr = kw["UpdateExpression"]
    assert expr.startswith("SET ") and "facts = :f" in expr and "onboarded = :ob" in expr
    assert "if_not_exists(onboarded_at" in expr
    vals = kw["ExpressionAttributeValues"]
    assert json.loads(vals[":f"]["S"]) == {"markets": ["coffee", "sugar"]}   # facts stored as a JSON string
    assert vals[":ob"] == {"BOOL": True}


def test_update_profile_dynamo_noop_when_all_none():
    calls = []

    class _Db:
        def update_item(self, **kw):
            calls.append(kw)

    st.DynamoStore(table="t", client=_Db()).update_profile("u1")     # nothing to set -> no Dynamo call
    assert calls == []


def test_get_profile_dynamo_decodes_native_and_facts_json():
    class _Db:
        def get_item(self, **kw):
            return {"Item": {
                "pk": {"S": "user#u1"}, "sk": {"S": "profile"},
                "turn_count": {"N": "7"}, "email": {"S": "a@b.c"},
                "onboarded": {"BOOL": True},
                "facts": {"S": json.dumps({"markets": ["coffee"], "seat": "trader"})},
            }}

    p = st.DynamoStore(table="t", client=_Db()).get_profile("u1")
    assert p["turn_count"] == 7 and p["email"] == "a@b.c" and p["onboarded"] is True
    assert p["facts"] == {"markets": ["coffee"], "seat": "trader"}    # deserialized dict, not the raw string


def test_get_profile_dynamo_bad_facts_json_degrades_to_empty():
    class _Db:
        def get_item(self, **kw):
            return {"Item": {"pk": {"S": "user#u1"}, "sk": {"S": "profile"},
                             "facts": {"S": "{not json"}}}

    assert st.DynamoStore(table="t", client=_Db()).get_profile("u1")["facts"] == {}


# ── fact sanitization (server) ───────────────────────────────────────────────────────────────────────
def test_sanitize_facts_bounds_and_drops_unknown_keys():
    dirty = {
        "markets": ["coffee", "  ", "sugar", "x" * 500],             # blank dropped, over-long truncated
        "regions": [f"r{i}" for i in range(30)],                     # capped to 12
        "notes": ["a note"],
        "seat": "  trader  ",
        "evil": ["injected instruction"],                           # unknown key -> dropped
        "not_a_list": "scalar",
    }
    out = sv._sanitize_facts(dirty)
    assert set(out) == {"markets", "regions", "notes", "seat"}
    assert out["markets"] == ["coffee", "sugar", "x" * 140]
    assert len(out["regions"]) == 12
    assert out["seat"] == "trader"
    assert sv._sanitize_facts("nope") == {} and sv._sanitize_facts(None) == {}


# ── routes: GET / PUT /v1/profile ────────────────────────────────────────────────────────────────────
def test_get_profile_route_defaults_for_fresh_user(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/v1/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "local" and body["facts"] == {} and body["onboarded"] is False
    assert body["turn_count"] == 0


def test_put_profile_route_sanitizes_and_persists(monkeypatch):
    c = _client(monkeypatch)
    r = c.put("/v1/profile", json={"facts": {"markets": ["coffee"], "evil": ["x"]}, "onboarded": True})
    assert r.status_code == 200
    body = r.json()
    assert body["facts"] == {"markets": ["coffee"]} and body["onboarded"] is True   # unknown key dropped
    # a partial update leaves facts untouched while flipping nothing it didn't send
    r2 = c.put("/v1/profile", json={"facts": {"regions": ["Brazil"]}})
    assert r2.json()["facts"] == {"regions": ["Brazil"]} and r2.json()["onboarded"] is True
    # GET now reflects the last write
    assert c.get("/v1/profile").json()["facts"] == {"regions": ["Brazil"]}


# ── W5: the suggester folds every fact key into the prompt ────────────────────────────────────────────
def test_suggest_prompt_folds_all_fact_keys(monkeypatch):
    monkeypatch.setitem(sv._STATE, "suggest_news", (time.time(), []))  # fresh cache -> no background fetch
    body = M.SuggestRequest(question="coffee?", tldr="stocks thin")
    facts = {"markets": ["coffee"], "regions": ["Brazil"], "seat": "trader", "notes": ["watch frost"]}
    prompt = sv._suggest_prompt(body, facts)
    assert "coffee" in prompt and "Brazil" in prompt                 # markets + regions -> interests
    assert "User seat: trader" in prompt
    assert "watch frost" in prompt
