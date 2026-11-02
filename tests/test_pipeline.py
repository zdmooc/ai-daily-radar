"""Tests du pipeline. Les flux utilisés ici sont des exemples synthétiques
(domaine example.com), pas de vraies actualités."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from pipeline import llm as llm_mod
from pipeline.collect import collect_arxiv, collect_hf_daily, collect_hn, collect_rss
from pipeline.enrich import deduplicate, enrich
from pipeline.llm import LLMConfig, parse_answer
from pipeline.model import Item, canonical_url, clean_text
from pipeline.publish import load_seen, publish

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY = yaml.safe_load((ROOT / "taxonomy.yaml").read_text())["tags"]
NOW = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Exemple</title>
<item><title>Example lab releases an open-weight LLM agent</title>
<link>https://example.com/post-1?utm_source=rss</link>
<pubDate>Thu, 15 Jan 2026 07:00:00 GMT</pubDate>
<description>&lt;p&gt;A synthetic &lt;b&gt;example&lt;/b&gt; entry about agents.&lt;/p&gt;</description></item>
<item><title>No link item</title><pubDate>Thu, 15 Jan 2026 07:00:00 GMT</pubDate></item>
<item><title>Script link</title><link>javascript:alert(1)</link>
<pubDate>Thu, 15 Jan 2026 07:00:00 GMT</pubDate></item>
</channel></rss>"""

ARXIV = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2601.01234v2</id>
<published>2026-01-14T18:00:00Z</published>
<title>Example paper on retrieval</title>
<summary>Synthetic abstract about RAG and embeddings.</summary>
<author><name>A. Example</name></author></entry>
</feed>"""

SRC_RSS = {"id": "ex", "name": "Exemple", "category": "news"}
SRC_ARXIV = {"id": "arxiv", "name": "arXiv", "category": "research"}
SRC_HF = {"id": "hf", "name": "HF Daily", "category": "research"}
SRC_HN = {"id": "hn", "name": "HN", "category": "community"}


def test_clean_text_and_canonical_url():
    assert clean_text("<p>Bonjour&nbsp;<b>monde</b></p>") == "Bonjour monde"
    assert clean_text("un deux trois quatre", limit=9).endswith("…")
    assert canonical_url("http://www.Example.com/a/?utm_source=x&id=3") == "https://example.com/a?id=3"


def test_collect_rss_keeps_only_valid_entries():
    items = collect_rss(SRC_RSS, content=RSS)
    assert [i.title for i in items] == ["Example lab releases an open-weight LLM agent"]
    assert items[0].excerpt == "A synthetic example entry about agents."


def test_collect_arxiv_and_hf_share_paper_id():
    paper = collect_arxiv(SRC_ARXIV, content=ARXIV)[0]
    assert paper.arxiv_id == "2601.01234"
    assert paper.pdf_url == "https://arxiv.org/pdf/2601.01234"
    hf = collect_hf_daily(SRC_HF, content=[{
        "title": "Example paper on retrieval", "publishedAt": "2026-01-15T06:00:00Z",
        "paper": {"id": "2601.01234", "upvotes": 42, "authors": [{"name": "A. Example"}]},
    }])[0]
    assert hf.id == paper.id
    merged = deduplicate([hf, paper])
    assert len(merged) == 1 and merged[0].engagement == 42 and merged[0].also_in == ["arXiv"]


def test_collect_hn_dedups_hits():
    hit = {"objectID": "1", "title": "Show HN: example", "url": "https://example.com/x",
           "created_at": "2026-01-15T05:00:00Z", "points": 120}
    items = collect_hn(SRC_HN, content=[{"hits": [hit]}, {"hits": [hit]}], now=NOW)
    assert len(items) == 1 and items[0].discussion_url.endswith("id=1")


def test_enrich_without_llm_tags_and_scores():
    items = collect_rss(SRC_RSS, content=RSS)
    out = enrich(items, TAXONOMY, {"ex": 5}, LLMConfig())
    assert "agents" in out[0].tags and "llm" in out[0].tags
    assert out[0].summary_kind == "excerpt" and 0 < out[0].score <= 100


def test_enrich_with_llm(monkeypatch):
    monkeypatch.setattr(llm_mod, "_call", lambda cfg, prompt:
                        'Voici : {"resume": "Résumé de test.", "tags": ["agents", "inconnu"], "importance": 5}')
    import pipeline.enrich as enrich_mod
    monkeypatch.setattr(enrich_mod, "summarize", llm_mod.summarize)
    items = collect_rss(SRC_RSS, content=RSS)
    out = enrich(items, TAXONOMY, {"ex": 3}, LLMConfig(provider="ollama", model="test"))
    assert out[0].summary == "Résumé de test."
    assert out[0].summary_kind == "ai" and out[0].tags == ["agents"]


def test_parse_answer_rejects_garbage():
    assert parse_answer("pas de json", {"llm"}) is None
    assert parse_answer('{"resume": ""}', {"llm"}) is None
    assert parse_answer('{"resume": "ok", "importance": "x"}', {"llm"})["importance"] == 3


def test_publish_merges_and_is_idempotent(tmp_path):
    item = Item(title="Example", url="https://example.com/a", source_id="ex", source_name="Exemple",
                category="news", published=NOW)
    kwargs = dict(data_dir=tmp_path, day=date(2026, 1, 15), generated_at=NOW,
                  llm_label="none", source_status={"ex": "ok (1)"})
    first = publish([item], seen=load_seen(tmp_path), **kwargs)
    second = publish([item], seen=load_seen(tmp_path), **kwargs)
    assert first["added"] == 1 and second["added"] == 0 and second["total"] == 1
    assert item.id in load_seen(tmp_path)


def test_publish_prunes_old_seen(tmp_path):
    old = (date(2026, 1, 15) - timedelta(days=40)).isoformat()
    publish([], data_dir=tmp_path, day=date(2026, 1, 15), generated_at=NOW, llm_label="none",
            source_status={}, seen={"ancien": old})
    assert "ancien" not in load_seen(tmp_path)


def test_sources_file_is_valid():
    from pipeline.collect import COLLECTORS
    config = yaml.safe_load((ROOT / "sources.yaml").read_text())
    ids = [s["id"] for s in config["sources"]]
    assert len(ids) == len(set(ids))
    for src in config["sources"]:
        assert src["type"] in COLLECTORS, src["id"]
        assert src["category"] in {"news", "research", "community"}, src["id"]
        assert 1 <= src["weight"] <= 5, src["id"]
