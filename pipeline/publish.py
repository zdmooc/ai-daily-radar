"""Écriture des données statiques lues par l'application.

    app/data/index.json          liste des jours disponibles + état des sources
    app/data/daily/AAAA-MM-JJ.json  éléments du jour
    app/data/seen.json           identifiants déjà publiés (évite les répétitions)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .model import Item

SEEN_RETENTION_DAYS = 30


def _read(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_seen(data_dir: Path) -> dict[str, str]:
    return _read(data_dir / "seen.json", {})


def publish(
    items: list[Item],
    *,
    data_dir: Path,
    day: date,
    generated_at: datetime,
    llm_label: str,
    source_status: dict[str, str],
    seen: dict[str, str],
    tag_labels: dict[str, str] | None = None,
) -> dict:
    """Ajoute les nouveaux éléments au fichier du jour et met à jour les index."""
    day_str = day.isoformat()
    day_path = data_dir / "daily" / f"{day_str}.json"

    current = _read(day_path, {"date": day_str, "items": []})
    known = {i["id"] for i in current["items"]}
    new_items = [i.to_dict() for i in items if i.id not in known]
    merged = current["items"] + new_items
    merged.sort(key=lambda i: (i["score"], i["published"]), reverse=True)

    current.update(date=day_str, generated_at=generated_at.isoformat(), llm=llm_label, items=merged)
    _write(day_path, current)

    for item in new_items:
        seen[item["id"]] = day_str
    cutoff = (day - timedelta(days=SEEN_RETENTION_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    _write(data_dir / "seen.json", seen)

    days = []
    for path in sorted((data_dir / "daily").glob("*.json"), reverse=True):
        content = _read(path, {"items": []})
        days.append({"date": path.stem, "count": len(content["items"])})
    index = {
        "generated_at": generated_at.isoformat(),
        "llm": llm_label,
        "days": days,
        "tags": tag_labels or {},
        "sources": source_status,
    }
    _write(data_dir / "index.json", index)
    return {"day": day_str, "added": len(new_items), "total": len(merged)}
