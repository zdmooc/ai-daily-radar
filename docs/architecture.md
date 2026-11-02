# Architecture — Radar IA

## 1. Besoin

Disposer, sur mobile, d'une veille IA quotidienne qui :

1. collecte automatiquement l'actualité (labs, médias, recherche, communauté) ;
2. trie, classe par thème et note l'importance de chaque élément ;
3. résume en français (si un LLM est disponible) ;
4. regroupe les sujets en dossiers et tendances de fond (V2) ;
5. produit chaque semaine un dossier de recherche approfondie (V3) ;
6. permet de tout lire depuis l'app, y compris hors ligne.

## 2. Principes

| # | Principe | Conséquence |
|---|---|---|
| P1 | **Traitement avant la lecture** | Le pipeline prépare tout ; l'app ne fait que lire des fichiers statiques. |
| P2 | **Coût nul par défaut** | GitHub Actions + GitHub Pages ; le LLM est optionnel et plafonné. |
| P3 | **Robustesse par source** | Une source en panne est journalisée et ignorée, jamais bloquante. |
| P4 | **Configuration plutôt que code** | Sources et thèmes dans des fichiers YAML. |
| P5 | **Fournisseur LLM interchangeable** | Une seule interface : Ollama, API compatible OpenAI, Anthropic. |
| P6 | **Respect des contenus** | Extrait + lien, pas de recopie du texte intégral. |
| P7 | **Données traçables** | Les JSON sont versionnés dans Git : l'historique du radar est l'historique du dépôt. |

## 3. Vue en couches

```
┌───────────────────────────────────────────────────────────────┐
│ Sources        RSS labs/médias · arXiv · HF Daily Papers · HN │
├───────────────────────────────────────────────────────────────┤
│ Collecte       pipeline/collect.py   → format commun « Item » │
│ Préparation    fenêtre temporelle · dédoublonnage · déjà vus  │
│ Enrichissement pipeline/enrich.py    thèmes · score /100      │
│                pipeline/llm.py       résumé FR (optionnel)    │
│ Publication    pipeline/publish.py   app/data/*.json          │
├───────────────────────────────────────────────────────────────┤
│ Orchestration  GitHub Actions (cron quotidien + manuel)       │
│ Hébergement    GitHub Pages                                   │
├───────────────────────────────────────────────────────────────┤
│ Présentation   PWA : À la une · Recherche · Favoris · Archives│
│                service worker (hors ligne) · localStorage     │
└───────────────────────────────────────────────────────────────┘
```

## 4. Données

`app/data/index.json`

```json
{ "generated_at": "…", "llm": "none | fournisseur:modèle",
  "days": [{ "date": "AAAA-MM-JJ", "count": 0 }],
  "tags": { "agents": "Agents" },
  "sources": { "openai": "ok (12)" } }
```

`app/data/daily/AAAA-MM-JJ.json` : `{ date, generated_at, llm, items: [Item] }`

Champs d'un `Item` : `id`, `title`, `url`, `source_id`, `source_name`, `category`
(`news` · `research` · `community`), `published`, `excerpt`, `summary`, `summary_kind`
(`excerpt` · `ai`), `tags`, `score`, `authors`, `pdf_url`, `discussion_url`, `engagement`,
`also_in`, `arxiv_id`.

`app/data/seen.json` : identifiants déjà publiés (30 jours) pour ne pas republier un élément.

## 5. Règles de traitement

- **Identifiant** : identifiant arXiv s'il existe (un papier vu sur arXiv, Hugging Face et
  Hacker News devient un seul élément), sinon URL normalisée (sans traceurs `utm_*`).
- **Dédoublonnage** : même papier, même URL ou même titre normalisé. Le doublon enrichit
  l'élément conservé (popularité, « aussi repris par »).
- **Score /100** (heuristique, documentée dans `enrich.heuristic_score`) : poids de la source,
  popularité (points HN, votes HF, échelle logarithmique), reprises par d'autres sources,
  nombre de thèmes et, si un LLM est actif, son estimation d'importance (1 à 5).
- **Thèmes** : taxonomie fixe (`taxonomy.yaml`). Sans LLM : mots-clés ; avec LLM : le modèle
  choisit parmi les mêmes identifiants (toute valeur hors liste est rejetée).
- **Résumés** : le LLM ne reçoit que le titre et l'extrait, avec la consigne de ne rien
  inventer ; l'app indique toujours « Résumé IA » et garde l'extrait original visible.

## 6. Décisions

| Décision | Choix | Alternatives écartées |
|---|---|---|
| Type d'app | PWA sans build | Natif / React Native : stores, build, coût de maintenance |
| Back-end | Aucun (fichiers statiques) | API + base : serveur à héberger et sécuriser |
| Orchestration | GitHub Actions cron | Serveur cron perso : disponibilité à gérer |
| Stockage | JSON versionnés dans Git | Base de données : inutile au volume d'une veille perso |
| LLM | Optionnel, multi-fournisseur | LLM imposé : coût et dépendance dès le départ |

## 7. Évolutions prévues

- **V2** : embeddings des éléments → regroupement en dossiers thématiques ; glossaire A–Z
  alimenté par les nouveaux termes ; index de recherche plein texte (MiniSearch/Pagefind).
- **V3** : agent hebdomadaire qui choisit les sujets les plus actifs, rassemble les sources et
  rédige un dossier cité ; notifications Web Push (sur iPhone, uniquement PWA installée) ;
  tableau de bord des tendances par thème.
