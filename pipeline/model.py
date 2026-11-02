"""Format commun d'un élément du radar, quelle que soit sa source."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|ref_src$)")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


@dataclass
class Item:
    title: str
    url: str
    source_id: str
    source_name: str
    category: str  # news | research | community
    published: datetime
    excerpt: str = ""
    authors: list[str] = field(default_factory=list)
    pdf_url: str | None = None
    discussion_url: str | None = None
    engagement: int = 0  # points HN, votes HF…
    also_in: list[str] = field(default_factory=list)
    arxiv_id: str | None = None
    # Rempli par l'enrichissement
    summary: str = ""
    summary_kind: str = "excerpt"  # excerpt | ai
    tags: list[str] = field(default_factory=list)
    score: int = 0

    @property
    def id(self) -> str:
        key = f"arxiv:{self.arxiv_id}" if self.arxiv_id else canonical_url(self.url)
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["id"] = self.id
        data["published"] = self.published.isoformat()
        return data


def clean_text(value: str | None, limit: int | None = None) -> str:
    """Retire le HTML et normalise les espaces."""
    if not value:
        return ""
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", value))).strip()
    if limit and len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut.rstrip(",;:.") + "…"
    return text


def canonical_url(url: str) -> str:
    """URL normalisée pour le dédoublonnage (sans traceurs, sans / final)."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", parts.netloc.lower().removeprefix("www."), path, urlencode(query), ""))


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:80]


def extract_arxiv_id(text: str | None) -> str | None:
    if not text:
        return None
    match = _ARXIV_RE.search(text)
    return match.group(1) if match else None


def is_safe_url(url: str | None) -> bool:
    return bool(url) and urlsplit(url).scheme in ("http", "https")
