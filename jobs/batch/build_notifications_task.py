"""P3 morning-brief daily notifications sweep (Phase 8 SECTION III, Track B).

Scan every user profile -> resolve facts.markets (free text) to canonical contract ids -> dedupe
commodities ACROSS users -> ONE trusted-source news sweep per DISTINCT commodity (keyless Google-News
etiquette: cached ambient RSS, intra-run jitter, a global GET cap) -> enum-locked Haiku event extraction
(BEDROCK - never the Anthropic key: serving shares that RPM tier) -> fan typed LiveEvents out to matching
users via an idempotent date-prefixed notification key. Cost is O(distinct commodities), NOT O(users).

Runs on the DEDICATED lightweight `leviathan-dev-notifications` jobdef (1 vCPU / 2 GiB, default command =
this task, GRAPHRAG_PROVIDER=bedrock, retryStrategy 2) - NOT the evidence-build jobdef, whose baked default
command would rebuild the whole evidence store if a scheduler override were ever dropped.

    python jobs/batch/build_notifications_task.py --dry-run     # resolve + sweep + print, write NOTHING
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone

import boto3
from leviathan.common.config import load_env
from leviathan.graphrag import register as reg
from leviathan.graphrag.news import extract_live as nx
from leviathan.graphrag.news import fetch as nf
from leviathan.graphrag.news.contracts import LiveEvent
from leviathan.graphrag.orchestrator import _search_name as search_name

logger = logging.getLogger("build_notifications_task")

_TABLE = os.environ.get("GRAPHRAG_STORE_TABLE", "leviathan-dev-terminal-store")
_DEFAULT_PROBES = ["export ban", "export quota", "export tax"]


def _scan_profiles(db, table: str = _TABLE) -> list[dict]:
    """Raw paginated Scan of sk='profile' -> [{sub, facts}]. Lives OUTSIDE the Store on purpose: the
    PIT-firewalled Store deliberately has no cross-user enumeration (its API is single-user), and only this
    job's dedicated Scan-scoped IAM role may enumerate (the serving role never gets dynamodb:Scan)."""
    out: list[dict] = []
    kw = dict(TableName=table, FilterExpression="sk = :s",
              ExpressionAttributeValues={":s": {"S": "profile"}})
    while True:
        page = db.scan(**kw)
        for it in page.get("Items", []):
            sub = str(it.get("pk", {}).get("S", ""))[len("user#"):]
            facts_raw = (it.get("facts") or {}).get("S")
            try:
                facts = json.loads(facts_raw) if facts_raw else {}
            except (ValueError, TypeError):
                facts = {}                                           # a malformed profile is skipped, not fatal
            if sub:
                out.append({"sub": sub, "facts": facts if isinstance(facts, dict) else {}})
        lek = page.get("LastEvaluatedKey")
        if not lek:
            return out
        kw["ExclusiveStartKey"] = lek


def _humanize(x: str) -> str:
    return reg.sanitize((x or "").replace("_", " "))


_TAG_RE = re.compile(r"<[^>]*>")


def _scrub(text: str, cap: int) -> str:
    """Markup scrub + register rewrite + cap for LLM free text (summary/country). reg.sanitize fixes
    REGISTER (internal jargon -> researcher prose) — it does NOT strip markup; React escaping is the render
    defense, and this keeps raw tags out of the STORED body and the label it folds into."""
    t = _TAG_RE.sub(" ", text or "").replace("<", " ").replace(">", " ")
    return reg.sanitize(" ".join(t.split()))[:cap]


def _resolve_markets(facts: dict, matcher, form_to_cid: dict) -> set[str]:
    """facts.markets (free text) -> canonical contract ids via the news alias matcher. Regions are D1
    (v1 = markets-only; 'Brazil' is not a commodity surface form). Unmappable terms silently skipped."""
    cids: set[str] = set()
    for term in (facts.get("markets") or []):
        for form in (matcher.findall(str(term).lower()) if matcher else []):
            cid = form_to_cid.get(form)
            if cid:
                cids.add(cid)
    return cids


def _iso_date(published: str | None, day: str) -> str:
    """Google-News RSS pubDate is RFC-822 ('Wed, 09 Jul 2026 12:00:00 GMT'); a raw [:10] slice would yield
    'Wed, 09 Ju' garbage, and the attachment PIT gate compares LEXICALLY (str(date) > str(asof)) so garbage
    sorts after every ISO as-of and would PERMANENTLY withhold the notification. Normalize to ISO; fall back
    to the job's UTC day. NEVER slice raw `published`."""
    from email.utils import parsedate_to_datetime
    if published:
        try:
            return parsedate_to_datetime(published).date().isoformat()
        except (TypeError, ValueError):
            pass
    return day


def _build_notification(ev: LiveEvent, day: str) -> dict:
    """A stored notification body. extract_live only LENGTH-CAPS its free text (reg.sanitize runs on the
    attach path, which a stored notification body never re-enters) - so sanitize + cap HERE, before the
    country folds into the label. label + query are built from ENUM/graph-derived values only; the raw
    headline lives exclusively in the `event` audit blob, which the API projects off the wire."""
    summary = _scrub(ev.summary, 300)
    country = (_scrub(ev.country, 60) or None) if ev.country else None
    comm_label = search_name(ev.commodity) if ev.commodity else ev.commodity
    subject = _humanize(ev.driver_id) if ev.driver_id else _humanize(ev.event_type)
    query = f"Has {subject} hit {comm_label} before? What cascaded?"
    label = f"{_humanize(ev.event_type)} - {comm_label}" + (f" ({country})" if country else "")
    # one-per-(driver, commodity, day) is the INTENDED digest granularity (fatigue guard; v1.1 may widen)
    notif_id = f"{day}#{ev.driver_id or ev.event_type}#{ev.commodity}"
    return {"notif_id": notif_id, "created_at": datetime.now(timezone.utc).isoformat(),
            "event_type": ev.event_type, "commodity": ev.commodity, "date": _iso_date(ev.published, day),
            "summary": summary, "country": country, "label": label, "query": query,
            "driver_id": ev.driver_id, "event": ev.model_dump()}


def _bedrock_haiku_call():
    """Forced-tool Haiku adapter for nx.extract_events, pinned to BEDROCK. Serving runs on the Anthropic
    API and shares its per-minute RPM tier - a daily multi-commodity sweep must live in the separate Bedrock
    quota lane (and never burn Anthropic credit). The retry policy is the serving backoff (availability
    errors only)."""
    os.environ["GRAPHRAG_PROVIDER"] = "bedrock"                      # pin BEFORE the client resolves
    from leviathan.graphrag import extract as ex
    from leviathan.graphrag import providers as pv
    client = pv.make_client()

    def call(system: str, user: str, *, model: str = nx.HAIKU, tool: dict) -> dict:
        out, _ = pv.with_retry(lambda: ex.call_opus(client, system, user,
                                                    model=pv.resolve_model(model), tool=tool))
        return out

    return call


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    ap = argparse.ArgumentParser(description="P3 daily morning-brief notifications sweep.")
    ap.add_argument("--dry-run", action="store_true", help="resolve + sweep + print; write no notifications")
    ap.add_argument("--jitter", type=float, default=2.0, help="max seconds of random sleep between commodities")
    ap.add_argument("--max-commodities", type=int, default=33, help="per-run distinct-commodity cap")
    args = ap.parse_args()
    load_env()

    from leviathan.graphrag import graph as g  # same seam as server._graph()
    from leviathan.graphrag import store as st

    db = boto3.client("dynamodb")
    graph = g.CausalGraph.load()
    matcher, form_to_cid = nx._commodity_matcher(graph)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    profiles = _scan_profiles(db)
    user_cids = {p["sub"]: _resolve_markets(p["facts"], matcher, form_to_cid) for p in profiles}
    distinct = sorted({c for cids in user_cids.values() for c in cids})[: args.max_commodities]
    logger.info("profiles=%d distinct_commodities=%d: %s", len(profiles), len(distinct), distinct)
    if not distinct:
        logger.info("no mappable watchlists; nothing to sweep (D3: no-facts users get no digest)")
        return 0

    cid_to_users: dict[str, list[str]] = {}
    for sub, cids in user_cids.items():
        for cid in cids:
            cid_to_users.setdefault(cid, []).append(sub)

    probes = list(nf.news_cfg().get("default_probe_keywords") or _DEFAULT_PROBES)
    store = st.DynamoStore(table=_TABLE, client=db)
    call = _bedrock_haiku_call()
    ambient = nf.ambient_feed_items()                                # the 2 ambient RSS feeds, ONCE per run
    get_budget = int(os.environ.get("NOTIF_GET_CAP", "600"))         # global keyless-GET cap; WARN when hit
    written = 0
    # ONE sweep per distinct commodity (dedupe ACROSS users); fan out per commodity AS EACH completes so a
    # late failure (throttle, feed outage) keeps every earlier commodity's notifications.
    for cid in distinct:
        if get_budget <= 0:
            logger.warning("GET budget exhausted before %s; stopping the sweep early", cid)
            break
        terms = [f"{p} {search_name(cid)}" for p in probes]
        try:                                                         # one bad commodity must NOT abort the run
            items = nf.gather(terms, ambient=ambient)
            get_budget -= len(terms) * 4                             # ~3 probes x 4 domains per sweep
            try:
                nf.snapshot(items)                                   # audit -> live_events/<date>/ (gather does NOT)
            except Exception:  # noqa: BLE001 - the audit copy is best-effort, never fatal
                logger.warning("snapshot failed for %s (non-fatal)", cid)
            evs = [e for e in nx.extract_events(items, call=call, graph=graph) if e.commodity == cid]
        except Exception:  # noqa: BLE001 - isolate this commodity, continue with the rest
            logger.warning("sweep failed for %s; continuing", cid, exc_info=True)
            continue
        if not items:
            logger.warning("empty provider response for %s (429/rate-limit day?)", cid)   # visible, never silent
        logger.info("commodity=%s headlines=%d events=%d", cid, len(items), len(evs))
        for ev in evs:
            body = _build_notification(ev, day)
            for sub in cid_to_users.get(cid, []):
                if args.dry_run:
                    logger.info("[DRY] %s <- %s (%s)", sub, body["notif_id"], body["label"])
                    continue
                if store.append_notification(sub, body["notif_id"], body):
                    written += 1
        time.sleep(random.uniform(0, args.jitter))                   # etiquette between commodity sweeps
    logger.info("done: wrote %d notification(s) (dry_run=%s)", written, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
