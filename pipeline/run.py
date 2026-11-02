"""Point d'entrée : python -m pipeline.run [--data-dir app/data] [--dry-run]"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .collect import collect_all
from .enrich import deduplicate, enrich
from .llm import LLMConfig
from .publish import load_seen, publish

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Radar IA — collecte quotidienne")
    parser.add_argument("--sources", type=Path, default=ROOT / "sources.yaml")
    parser.add_argument("--taxonomy", type=Path, default=ROOT / "taxonomy.yaml")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "app" / "data")
    parser.add_argument("--only", nargs="*", help="limiter à ces identifiants de source")
    parser.add_argument("--window-hours", type=int, help="remplace settings.window_hours (ex. 168 pour un premier remplissage)")
    parser.add_argument("--dry-run", action="store_true", help="affiche le résultat sans rien écrire")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    log = logging.getLogger("radar")

    config = yaml.safe_load(args.sources.read_text(encoding="utf-8"))
    settings = config.get("settings", {})
    sources = config["sources"]
    if args.only:
        sources = [s for s in sources if s["id"] in args.only]
    taxonomy = yaml.safe_load(args.taxonomy.read_text(encoding="utf-8"))["tags"]
    llm = LLMConfig.from_env()

    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo(settings.get("timezone", "Europe/Paris"))).date()
    window = now - timedelta(hours=args.window_hours or settings.get("window_hours", 48))

    items, status = collect_all(sources, settings.get("max_items_per_source", 30))
    seen = load_seen(args.data_dir)
    fresh = [i for i in items if i.published >= window]
    fresh = deduplicate(fresh)
    fresh = [i for i in fresh if i.id not in seen]
    log.info("%d collectés, %d récents et nouveaux", len(items), len(fresh))

    weights = {s["id"]: int(s.get("weight", 2)) for s in sources}
    fresh = enrich(fresh, taxonomy, weights, llm)

    if args.dry_run:
        for item in fresh[:20]:
            print(f"{item.score:3d}  [{item.source_id}] {item.title}  {item.tags}")
        return 0

    result = publish(fresh, data_dir=args.data_dir, day=day, generated_at=now,
                     llm_label=llm.label, source_status=status, seen=seen,
                     tag_labels={k: v.get("label", k) for k, v in taxonomy.items()})
    log.info("Jour %(day)s : %(added)d ajoutés, %(total)d au total", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
