"""Dédoublonnage, thèmes, score d'importance et résumés."""

from __future__ import annotations

import logging
import math
import re

from .llm import LLMConfig, summarize
from .model import Item, canonical_url, title_key

log = logging.getLogger(__name__)


def deduplicate(items: list[Item]) -> list[Item]:
    """Fusionne les doublons (même papier arXiv, même URL ou même titre).

    Le premier élément rencontré est conservé ; les suivants enrichissent
    sa popularité et la liste des autres sources où il apparaît.
    """
    kept: list[Item] = []
    index: dict[str, Item] = {}
    for item in items:
        keys = [canonical_url(item.url)]
        if len(title_key(item.title)) >= 12:
            keys.append("t:" + title_key(item.title))
        if item.arxiv_id:
            keys.append("arxiv:" + item.arxiv_id)
        existing = next((index[k] for k in keys if k in index), None)
        if existing is None:
            kept.append(item)
            for k in keys:
                index[k] = item
            continue
        existing.engagement = max(existing.engagement, item.engagement)
        if item.source_name not in existing.also_in and item.source_name != existing.source_name:
            existing.also_in.append(item.source_name)
        existing.discussion_url = existing.discussion_url or item.discussion_url
        existing.pdf_url = existing.pdf_url or item.pdf_url
        if len(item.excerpt) > len(existing.excerpt):
            existing.excerpt = item.excerpt
    return kept


def _compile(taxonomy: dict) -> dict[str, re.Pattern]:
    patterns = {}
    for tag, spec in taxonomy.items():
        words = sorted((re.escape(k.lower()) for k in spec.get("keywords", [])), key=len, reverse=True)
        if words:
            patterns[tag] = re.compile(r"(?<![a-z0-9])(" + "|".join(words) + r")(?![a-z0-9])")
    return patterns


def keyword_tags(item: Item, patterns: dict[str, re.Pattern], limit: int = 3) -> list[str]:
    title = item.title.lower()
    body = item.excerpt.lower()
    scored = []
    for tag, pattern in patterns.items():
        hits = 3 * len(pattern.findall(title)) + len(pattern.findall(body))
        if hits:
            scored.append((hits, tag))
    scored.sort(reverse=True)
    return [tag for _, tag in scored[:limit]]


def heuristic_score(item: Item, weight: int, importance: int | None = None) -> int:
    """Score sur 100 : poids de la source, popularité, reprises, avis du LLM."""
    score = 10 * weight                                   # 10 à 50
    if item.engagement:
        score += min(25, int(6 * math.log10(1 + item.engagement)))
    score += min(10, 5 * len(item.also_in))
    score += 5 * min(2, len(item.tags))
    if importance is not None:                            # 1..5 -> -10..+30
        score += (importance - 2) * 10
    return max(0, min(100, score))


def enrich(items: list[Item], taxonomy: dict, weights: dict[str, int], llm: LLMConfig) -> list[Item]:
    patterns = _compile(taxonomy)
    allowed = set(taxonomy)

    for item in items:
        item.tags = keyword_tags(item, patterns)
        item.summary = ""  # sans LLM, l'app affiche l'extrait original
        item.summary_kind = "excerpt"
        item.score = heuristic_score(item, weights.get(item.source_id, 2))

    if llm.enabled:
        # On résume en priorité les éléments les mieux notés, dans la limite fixée.
        budget = sorted(items, key=lambda i: i.score, reverse=True)[: llm.max_items]
        log.info("Résumés IA (%s) pour %d éléments", llm.label, len(budget))
        for item in budget:
            answer = summarize(llm, source=item.source_name, title=item.title,
                               excerpt=item.excerpt, allowed_tags=allowed)
            if not answer:
                continue
            item.summary = answer["summary"]
            item.summary_kind = "ai"
            item.tags = answer["tags"] or item.tags
            item.score = heuristic_score(item, weights.get(item.source_id, 2), answer["importance"])

    items.sort(key=lambda i: (i.score, i.published), reverse=True)
    return items
