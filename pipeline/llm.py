"""Accès optionnel à un LLM pour résumer en français et classer les éléments.

Configuration par variables d'environnement :

    RADAR_LLM_PROVIDER   none (défaut) | ollama | openai | anthropic
    RADAR_LLM_MODEL      nom du modèle (obligatoire si un fournisseur est choisi)
    RADAR_LLM_BASE_URL   URL de l'API (ollama : http://localhost:11434 ;
                         openai : https://api.openai.com/v1 ou tout service
                         compatible OpenAI — Mistral, Groq, OpenRouter, llama.cpp…)
    RADAR_LLM_API_KEY    clé d'API (openai / anthropic)
    RADAR_LLM_MAX_ITEMS  nombre maximum d'éléments résumés par exécution (défaut 40)

Sans fournisseur, le pipeline fonctionne quand même : il garde l'extrait
original et attribue les thèmes par mots-clés.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

PROMPT = """Tu es l'éditeur d'une revue de presse quotidienne sur l'intelligence artificielle.
Pour l'élément ci-dessous, réponds UNIQUEMENT avec un objet JSON :
{{"resume": "...", "tags": [...], "importance": n}}

- "resume" : 2 à 3 phrases en français, factuelles, sans formule d'introduction.
  N'invente rien : appuie-toi seulement sur le titre et l'extrait fournis.
- "tags" : 1 à 3 identifiants choisis UNIQUEMENT dans cette liste : {tags}
- "importance" : entier de 1 (anecdotique) à 5 (événement majeur pour le secteur).

Source : {source}
Titre : {title}
Extrait : {excerpt}
"""


@dataclass
class LLMConfig:
    provider: str = "none"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    max_items: int = 40

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = os.getenv("RADAR_LLM_PROVIDER", "none").strip().lower() or "none"
        cfg = cls(
            provider=provider,
            model=os.getenv("RADAR_LLM_MODEL", "").strip(),
            base_url=os.getenv("RADAR_LLM_BASE_URL", "").strip().rstrip("/"),
            api_key=os.getenv("RADAR_LLM_API_KEY", "").strip(),
            max_items=int(os.getenv("RADAR_LLM_MAX_ITEMS", "40")),
        )
        if cfg.enabled and not cfg.model:
            raise SystemExit(f"RADAR_LLM_MODEL est obligatoire avec le fournisseur « {provider} ».")
        return cfg

    @property
    def enabled(self) -> bool:
        return self.provider != "none"

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}" if self.enabled else "none"


def _call(cfg: LLMConfig, prompt: str) -> str:
    if cfg.provider == "ollama":
        url = (cfg.base_url or "http://localhost:11434") + "/api/chat"
        body = {"model": cfg.model, "stream": False, "format": "json",
                "messages": [{"role": "user", "content": prompt}]}
        resp = requests.post(url, json=body, timeout=180)
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    if cfg.provider == "openai":
        url = (cfg.base_url or "https://api.openai.com/v1") + "/chat/completions"
        body = {"model": cfg.model, "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}]}
        resp = requests.post(url, json=body, timeout=90,
                             headers={"Authorization": f"Bearer {cfg.api_key}"})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    if cfg.provider == "anthropic":
        url = (cfg.base_url or "https://api.anthropic.com") + "/v1/messages"
        body = {"model": cfg.model, "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}]}
        resp = requests.post(url, json=body, timeout=90, headers={
            "x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"})
        resp.raise_for_status()
        return "".join(b.get("text", "") for b in resp.json()["content"])

    raise ValueError(f"Fournisseur LLM inconnu : {cfg.provider}")


def parse_answer(text: str, allowed_tags: set[str]) -> dict | None:
    """Extrait l'objet JSON de la réponse du modèle et le valide."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    summary = str(data.get("resume", "")).strip()
    if not summary:
        return None
    tags = [t for t in data.get("tags", []) if t in allowed_tags][:3]
    try:
        importance = min(5, max(1, int(data.get("importance", 3))))
    except (TypeError, ValueError):
        importance = 3
    return {"summary": summary, "tags": tags, "importance": importance}


def summarize(cfg: LLMConfig, *, source: str, title: str, excerpt: str, allowed_tags: set[str]) -> dict | None:
    prompt = PROMPT.format(tags=", ".join(sorted(allowed_tags)), source=source,
                           title=title, excerpt=excerpt or "(aucun extrait)")
    try:
        return parse_answer(_call(cfg, prompt), allowed_tags)
    except Exception as exc:
        log.warning("LLM indisponible pour « %s » : %s", title[:60], exc)
        return None
