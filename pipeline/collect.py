"""Collecte des sources : flux RSS/Atom, arXiv, Hugging Face Daily Papers, Hacker News."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

import feedparser
import requests

from .model import Item, clean_text, extract_arxiv_id, is_safe_url

log = logging.getLogger(__name__)

USER_AGENT = "ai-daily-radar/0.1 (+https://github.com/zdmooc/ai-daily-radar)"
TIMEOUT = 25
EXCERPT_LIMIT = 600


def _get(url: str, **params) -> requests.Response:
    resp = requests.get(url, params=params or None, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(time.mktime(value), tz=timezone.utc)
    return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


# --- Collecteurs par type ------------------------------------------------------


def collect_rss(src: dict, content: bytes | None = None) -> list[Item]:
    raw = content if content is not None else _get(src["url"]).content
    feed = feedparser.parse(raw)
    items = []
    for entry in feed.entries:
        link = entry.get("link")
        published = _entry_date(entry)
        if not (entry.get("title") and is_safe_url(link) and published):
            continue
        body = entry.get("summary") or ""
        if not body and entry.get("content"):
            body = entry["content"][0].get("value", "")
        items.append(
            Item(
                title=clean_text(entry["title"]),
                url=link,
                source_id=src["id"],
                source_name=src["name"],
                category=src.get("category", "news"),
                published=published,
                excerpt=clean_text(body, EXCERPT_LIMIT),
                authors=[a.get("name", "") for a in entry.get("authors", []) if a.get("name")][:6],
            )
        )
    return items


def collect_arxiv(src: dict, content: bytes | None = None) -> list[Item]:
    if content is None:
        query = " OR ".join(f"cat:{c}" for c in src.get("categories", ["cs.AI"]))
        content = _get(
            "https://export.arxiv.org/api/query",
            search_query=query,
            sortBy="submittedDate",
            sortOrder="descending",
            max_results=src.get("max_results", 40),
        ).content
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        arxiv_id = extract_arxiv_id(entry.get("id"))
        published = _entry_date(entry)
        if not (arxiv_id and published):
            continue
        items.append(
            Item(
                title=clean_text(entry.get("title")),
                url=f"https://arxiv.org/abs/{arxiv_id}",
                source_id=src["id"],
                source_name=src["name"],
                category=src.get("category", "research"),
                published=published,
                excerpt=clean_text(entry.get("summary"), EXCERPT_LIMIT),
                authors=[a.get("name", "") for a in entry.get("authors", [])][:6],
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                arxiv_id=arxiv_id,
            )
        )
    return items


def collect_hf_daily(src: dict, content: list | None = None) -> list[Item]:
    data = content if content is not None else _get(src["url"], limit=src.get("limit", 30)).json()
    items = []
    for row in data:
        paper = row.get("paper") or {}
        arxiv_id = extract_arxiv_id(paper.get("id"))
        published = _parse_iso(row.get("publishedAt") or paper.get("publishedAt"))
        title = row.get("title") or paper.get("title")
        if not (arxiv_id and published and title):
            continue
        items.append(
            Item(
                title=clean_text(title),
                url=f"https://huggingface.co/papers/{arxiv_id}",
                source_id=src["id"],
                source_name=src["name"],
                category=src.get("category", "research"),
                published=published,
                excerpt=clean_text(paper.get("summary"), EXCERPT_LIMIT),
                authors=[a.get("name", "") for a in paper.get("authors", []) if a.get("name")][:6],
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                engagement=int(paper.get("upvotes") or 0),
                arxiv_id=arxiv_id,
            )
        )
    return items


def collect_hn(src: dict, content: list[dict] | None = None, now: datetime | None = None) -> list[Item]:
    now = now or datetime.now(timezone.utc)
    since = int((now - timedelta(hours=48)).timestamp())
    pages = content
    if pages is None:
        pages = []
        for query in src.get("queries", ["AI"]):
            pages.append(
                _get(
                    "https://hn.algolia.com/api/v1/search",
                    query=query,
                    tags="story",
                    numericFilters=f"points>={src.get('min_points', 80)},created_at_i>={since}",
                    hitsPerPage=20,
                ).json()
            )
    seen, items = set(), []
    for page in pages:
        for hit in page.get("hits", []):
            object_id = hit.get("objectID")
            discussion = f"https://news.ycombinator.com/item?id={object_id}"
            url = hit.get("url") or discussion
            published = _parse_iso(hit.get("created_at"))
            if object_id in seen or not (hit.get("title") and published and is_safe_url(url)):
                continue
            seen.add(object_id)
            items.append(
                Item(
                    title=clean_text(hit["title"]),
                    url=url,
                    source_id=src["id"],
                    source_name=src["name"],
                    category=src.get("category", "community"),
                    published=published,
                    discussion_url=discussion,
                    engagement=int(hit.get("points") or 0),
                    arxiv_id=extract_arxiv_id(url) if "arxiv.org" in url else None,
                )
            )
    return items


COLLECTORS: dict[str, Callable[[dict], list[Item]]] = {
    "rss": collect_rss,
    "arxiv": collect_arxiv,
    "hf_daily": collect_hf_daily,
    "hn": collect_hn,
}


def collect_all(sources: Iterable[dict], max_per_source: int = 30) -> tuple[list[Item], dict[str, str]]:
    """Collecte toutes les sources actives. Retourne (éléments, état par source)."""
    items: list[Item] = []
    status: dict[str, str] = {}
    for src in sources:
        if not src.get("enabled", True):
            continue
        collector = COLLECTORS.get(src.get("type"))
        if collector is None:
            status[src["id"]] = f"type inconnu : {src.get('type')}"
            continue
        try:
            found = collector(src)
            found.sort(key=lambda i: i.published, reverse=True)
            items.extend(found[:max_per_source])
            status[src["id"]] = f"ok ({len(found)})"
            log.info("%-20s %3d éléments", src["id"], len(found))
        except Exception as exc:  # une source en panne ne bloque pas les autres
            status[src["id"]] = f"erreur : {type(exc).__name__}"
            log.warning("%-20s ÉCHEC : %s", src["id"], exc)
    return items, status
