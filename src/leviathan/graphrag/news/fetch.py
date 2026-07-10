"""Trusted-source fetchers for the live news/policy agent (GRAPHRAG_PLAN section 7.1).

Query-time only — nothing polls in the background. Three providers, all confined to the domains in
configs/graphrag/news_sources.yaml (never general web):

  rss           direct RSS/Atom feeds, keyless (stdlib XML — no new dependency)
  google_news   keyless site-scoped headline search (the free Reuters-headline wrapper)
  brave_search  optional; activates only when BRAVE_API_KEY is present

Every fetch is snapshotted to s3://<EVIDENCE_S3>/live_events/<date>/ so an answer's live context is
auditable later (query-time search results churn hourly) and a dated event log accumulates for the
future event-study validation. Failures degrade to fewer items, never exceptions — a broken feed must
not break an answer.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from leviathan.graphrag import extract as ex

_NEWS_PATH = ex._CFG / "news_sources.yaml"
_CFG_CACHE = None
_TIMEOUT = 10


def news_cfg() -> dict:
    global _CFG_CACHE
    if _CFG_CACHE is None:
        if not _NEWS_PATH.exists():
            _CFG_CACHE = {}
        else:
            import yaml
            _CFG_CACHE = yaml.safe_load(_NEWS_PATH.read_text(encoding="utf-8")) or {}
    return _CFG_CACHE


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── RSS / Atom (stdlib; tolerant) ─────────────────────────────────────────────────────────────────
def _text(el, *tags) -> str:
    for t in tags:
        found = el.find(t)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def parse_feed(xml_text: str, source: str) -> list[dict]:
    """RSS 2.0 <item> and Atom <entry> -> [{headline, url, published, source}]. Bad XML -> []."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = []
    for it in root.iter("item"):                                   # RSS 2.0
        items.append({"headline": _text(it, "title"), "url": _text(it, "link"),
                      "published": _text(it, "pubDate"), "source": source})
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):     # Atom
        link = it.find("a:link", ns)
        items.append({"headline": _text(it, "{http://www.w3.org/2005/Atom}title"),
                      "url": (link.get("href") if link is not None else ""),
                      "published": _text(it, "{http://www.w3.org/2005/Atom}updated"), "source": source})
    return [i for i in items if i["headline"]]


def _get(url: str, headers: dict | None = None) -> str:
    import requests
    r = requests.get(url, timeout=_TIMEOUT,
                     headers={"User-Agent": "Mozilla/5.0 (leviathan-research)", **(headers or {})})
    r.raise_for_status()
    return r.text


def fetch_rss(cfg: dict) -> list[dict]:
    out = []
    for feed in (cfg.get("feeds") or []):
        try:
            out += parse_feed(_get(feed["url"]), feed.get("source", ""))
        except Exception:  # noqa: BLE001 — one dead feed must not kill the sweep
            continue
    return out


# ── Google News RSS, site-scoped (keyless Reuters wrapper) ────────────────────────────────────────
def fetch_google_news(cfg: dict, queries: list[str]) -> list[dict]:
    domains = cfg.get("domains") or []
    out = []
    for q in queries[: int(cfg.get("max_queries", 4))]:
        for dom in domains:
            try:
                recency = cfg.get("when", "7d")                                      # live = recent by definition
                url = ("https://news.google.com/rss/search?q="                       # no exact-phrase quoting:
                       + urllib.parse.quote(f"{q} site:{dom} when:{recency}")        # terms AND-match
                       + "&hl=en-US&gl=US&ceid=US:en")
                for item in parse_feed(_get(url), dom):
                    item["via"] = "google_news"
                    out.append(item)
            except Exception:  # noqa: BLE001
                continue
    return out


# ── Brave Search (optional, key-gated) ────────────────────────────────────────────────────────────
def fetch_brave(cfg: dict, queries: list[str]) -> list[dict]:
    key = os.environ.get("BRAVE_API_KEY")
    if not key:
        return []
    import requests
    out = []
    sites = " OR ".join(f"site:{d}" for d in (cfg.get("domains") or []))
    for q in queries[:4]:
        try:
            r = requests.get("https://api.search.brave.com/res/v1/web/search",
                             params={"q": f"{q} ({sites})", "count": int(cfg.get("count", 8)),
                                     "freshness": cfg.get("freshness", "pw")},
                             headers={"X-Subscription-Token": key, "Accept": "application/json"},
                             timeout=_TIMEOUT)
            r.raise_for_status()
            for w in (r.json().get("web") or {}).get("results") or []:
                dom = urllib.parse.urlparse(w.get("url", "")).netloc.replace("www.", "")
                out.append({"headline": w.get("title", ""), "url": w.get("url", ""),
                            "published": w.get("age", ""), "source": dom, "via": "brave"})
        except Exception:  # noqa: BLE001
            continue
    return out


# ── the sweep + audit snapshot ────────────────────────────────────────────────────────────────────
def ambient_feed_items(cfg: dict | None = None) -> list[dict]:
    """The ambient (non-query-scoped) RSS pull, exposed so a multi-sweep caller — the P3 daily digest job
    loops gather() over ~30 commodities — can fetch the 2 feeds ONCE per run and hand them back in via
    gather(ambient=...) instead of re-fetching them on every sweep (keyless-source etiquette)."""
    cfg = cfg if cfg is not None else news_cfg()
    prov = cfg.get("providers") or {}
    return fetch_rss(prov["rss"]) if (prov.get("rss") or {}).get("enabled") else []


def gather(queries: list[str], *, cfg: dict | None = None, ambient: list[dict] | None = None) -> list[dict]:
    """One query-time sweep across all enabled providers; deduped by normalized headline. `ambient` (when
    given) replaces the per-call RSS pull with a caller-cached copy — behavior is otherwise unchanged."""
    cfg = cfg if cfg is not None else news_cfg()
    prov = cfg.get("providers") or {}
    items: list[dict] = []
    # QUERY-SCOPED providers first (site-pinned search hits are about the question), then the ambient RSS
    # firehose — otherwise a busy feed crowds the relevant hits out of the max_items cap.
    if (prov.get("google_news") or {}).get("enabled"):
        items += fetch_google_news(prov["google_news"], queries)
    if (prov.get("brave_search") or {}).get("enabled"):
        items += fetch_brave(prov["brave_search"], queries)
    if ambient is not None:
        items += list(ambient)
    elif (prov.get("rss") or {}).get("enabled"):
        items += fetch_rss(prov["rss"])
    now = _now_iso()
    seen, uniq = set(), []
    for i in items:
        sig = ex._normalize(i.get("headline") or "")[:120]
        if not sig or sig in seen:
            continue
        seen.add(sig)
        i["fetched_at"] = now
        uniq.append(i)
    return uniq[: int(cfg.get("max_items", 40))]


def snapshot(items: list[dict], *, s3=None) -> str | None:
    """Audit copy of everything fetched -> s3://<EVIDENCE_S3>/live_events/<date>/<ts>.json (best-effort)."""
    from leviathan.graphrag import evidence as ev
    s3uri = ev._evid_s3()
    if not s3uri or not items:
        return None
    try:
        import boto3
        s3 = s3 or boto3.client("s3")
        now = datetime.now(timezone.utc)
        b, k = ev._parse_s3(s3uri.rstrip("/") + f"/live_events/{now:%Y-%m-%d}/{now:%H%M%S}.json")
        s3.put_object(Bucket=b, Key=k, Body=json.dumps(items, ensure_ascii=True).encode())
        return f"s3://{b}/{k}"
    except Exception:  # noqa: BLE001 — audit is best-effort, never blocks the answer
        return None
