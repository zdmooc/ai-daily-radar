# Radar IA — veille quotidienne sur l'intelligence artificielle

Application mobile (PWA) qui rassemble chaque matin l'actualité IA : annonces des labs,
médias spécialisés, articles de recherche et discussions de la communauté.
Chaque élément est classé par thème, noté, et — si un LLM est configuré — résumé en français.

**App :** https://zdmooc.github.io/ai-daily-radar/ (une fois GitHub Pages activé, voir plus bas)

## Principe

Tout le traitement est fait **avant** la lecture : un workflow GitHub Actions tourne
chaque matin, collecte les sources, les enrichit, et publie des fichiers JSON statiques.
L'app ne fait que lire ces fichiers. Pas de serveur, pas de base de données, coût nul
tant qu'aucun LLM payant n'est branché.

```
sources.yaml ─► collecte ─► dédoublonnage ─► thèmes + score (+ résumé LLM) ─► app/data/*.json ─► PWA
                 (GitHub Actions, chaque jour 05:17 UTC)                       (GitHub Pages)
```

Détails et décisions : [docs/architecture.md](docs/architecture.md).

## Contenu du dépôt

| Chemin | Rôle |
|---|---|
| `sources.yaml` | Liste des sources (flux RSS, arXiv, Hugging Face Daily Papers, Hacker News) |
| `taxonomy.yaml` | Thèmes du radar et mots-clés associés |
| `pipeline/` | Code Python : `collect` → `enrich` (+ `llm`) → `publish`, lancé par `run` |
| `app/` | La PWA (HTML/CSS/JS sans build) et ses données dans `app/data/` |
| `tests/` | Tests du pipeline (`pytest`) |
| `.github/workflows/daily.yml` | Collecte quotidienne, commit des données, déploiement Pages |

## Mise en route (une seule fois)

1. **Activer GitHub Pages** : *Settings → Pages → Build and deployment → Source : GitHub Actions*.
2. **Autoriser le workflow à écrire** : *Settings → Actions → General → Workflow permissions →
   Read and write permissions*.
3. **Premier remplissage** : *Actions → Radar quotidien → Run workflow*, avec
   `window_hours = 168` pour récupérer la dernière semaine.
4. Ouvrir l'app sur le téléphone, puis *Partager → Sur l'écran d'accueil* (iPhone)
   ou *Installer l'application* (Android).

Ensuite, le workflow tourne seul chaque matin.

## Activer les résumés en français (optionnel)

Sans LLM, l'app affiche l'extrait original de la source (souvent en anglais) et les thèmes
sont attribués par mots-clés. Pour des résumés IA, définir dans
*Settings → Secrets and variables → Actions* :

| Nom | Type | Exemple |
|---|---|---|
| `RADAR_LLM_PROVIDER` | variable | `openai` (toute API compatible OpenAI), `anthropic` ou `ollama` |
| `RADAR_LLM_MODEL` | variable | nom exact du modèle chez le fournisseur choisi |
| `RADAR_LLM_BASE_URL` | variable | à renseigner pour un service compatible OpenAI autre qu'OpenAI |
| `RADAR_LLM_MAX_ITEMS` | variable | nombre max. d'éléments résumés par jour (défaut : 40) — plafonne le coût |
| `RADAR_LLM_API_KEY` | **secret** | clé d'API du fournisseur |

Remarque : les abonnements grand public (Claude Pro, ChatGPT Plus…) ne donnent pas accès
à l'API. Il faut une clé d'API, ou un modèle local via Ollama (voir ci-dessous).

## Lancer en local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m pipeline.run --dry-run                 # affiche le top 20 sans rien écrire
python -m pipeline.run --only openai arxiv       # limiter à certaines sources
python -m pipeline.run                           # écrit dans app/data/
python -m http.server -d app 8000                # puis http://localhost:8000
```

Avec un modèle local (gratuit, sur ta machine) :

```bash
export RADAR_LLM_PROVIDER=ollama RADAR_LLM_MODEL=<modèle installé dans Ollama>
python -m pipeline.run
git add app/data && git commit -m "data: radar local" && git push
```

## Ajouter une source

Ajouter un bloc dans `sources.yaml` (types : `rss`, `arxiv`, `hf_daily`, `hn`).
Une source qui échoue est signalée dans l'onglet **Archives** et n'empêche pas les autres
d'être collectées.

## Droits et lecture

L'app stocke le titre, un court extrait fourni par le flux, le résumé éventuel et le lien.
Le texte intégral reste sur le site d'origine (bouton « Lire l'original ») ; les articles
arXiv s'ouvrent en PDF.

## Feuille de route

- **V1 (ce dépôt)** : collecte multi-sources, thèmes, score, résumés optionnels, PWA
  (À la une, Recherche, Favoris, Archives), lecture hors ligne.
- **V2** : regroupement en dossiers thématiques (embeddings), glossaire IA de A à Z,
  recherche plein texte sur tout l'historique.
- **V3** : dossier de recherche approfondie hebdomadaire rédigé par un agent (avec sources),
  notifications, tableau de bord des tendances.
