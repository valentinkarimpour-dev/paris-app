# Flâneur Paris

Application de découverte d'événements et d'adresses à Paris, centrée sur la carte.  
L'utilisateur pose un pin sur la carte, définit un rayon, et voit tous les événements autour de lui.

**Production :** `http://145.241.168.3:8000/`

---

## Stack

| Composant | Technologie |
|-----------|-------------|
| Backend | FastAPI + Python 3.12 |
| Base de données | SQLite (`backend/events.db`) |
| Scraping JS-heavy | Playwright (Chromium headless) |
| Scraping sites statiques | Jina Reader (`r.jina.ai`) + Playwright en fallback |
| Parsing HTML | BeautifulSoup4 + lxml |
| Extraction LLM | Groq — `llama-3.1-8b-instant` (gratuit) |
| Géocodage | Nominatim OSM + api-adresse.data.gouv.fr (INPI) |
| Orchestration | n8n (`n8n_daily.json`) — APScheduler désactivé |
| Frontend | HTML + modules ES6 vanilla (`frontend/js/`) + Leaflet.js |
| POI carte | Overpass API (cinémas, musées, galeries OSM) |

---

## Lancer l'application (dev local)

```bash
./run.sh
```

Démarre le backend sur `http://localhost:8000` et Datasette sur `:8001`.

---

## Sources de données

### Quotidien — `ALL_SCRAPERS` (n8n, 6h chaque jour)

| Classe | Source | Technologie |
|--------|--------|-------------|
| `ParisOpenData` | Que Faire à Paris (opendata.paris.fr) | API REST |
| `ParisBougeAutre` / `Restos` / `Bars` / `Expos` | parisbouge.com | Playwright |
| `NewTable` | fr.newtable.com | Playwright |
| `LeBonbonNews` / `Food` / `Drinks` / `Healthy` | lebonbon.fr | Playwright + BS4 |
| `NumeroPopup` | numero.com | Playwright + LLM |
| `InpiFoodScraper` | INPI RNE — NAF 5610A (restauration) | API INPI |
| `InpiDrinksScraper` | INPI RNE — NAF 5630Z (débits de boissons) | API INPI |
| `TimeOutParis` | timeout.fr/paris | Jina + Playwright + LLM |
| `SortirAParisRestaurant` / `Cafes` / `Expos` / `Popup` | sortiraparis.com | Jina + Playwright + LLM |

### Mensuel — `MONTHLY_SCRAPERS` (n8n, uniquement le 1er du mois)

| Classe | Source | Note |
|--------|--------|------|
| `SecretsOfParis` | secretsofparis.com | Anglais → traduit via LLM |
| `ParisMuseeExpos` | API Paris Musées | BS4 |
| `MuseofileScraper` | museofile.culture.fr | BS4 |

---

## Orchestration n8n

Le workflow `n8n_daily.json` se déclenche **tous les jours à 6h** :

```
Schedule (6h daily)
  → POST /scrapers/run-all       ← 18 scrapers en background
  → Wait 6 min
  → GET /scrapers/last-run
  → POST /purge                  ← supprime les événements expirés
  → IF status == "done"
      → Slack OK  (#n8n-workflow-execution)
      → Slack Error
  → IF premier du mois
      → POST /scrapers/run-monthly   ← 3 scrapers mensuels
      → Wait 4 min
      → GET /scrapers/last-run
      → Slack OK/Error mensuel
```

Pour déclencher manuellement :
```bash
curl -X POST http://145.241.168.3:8000/scrapers/run-all
curl -X POST http://145.241.168.3:8000/scrapers/run/{name}
```

---

## API

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/` | Frontend HTML |
| `GET` | `/events` | Événements dans un rayon (`lat`, `lng`, `radius`, `days`, `cat`) |
| `GET` | `/stats` | Total events par catégorie et par source |
| `GET` | `/scrapers` | Liste des scrapers disponibles |
| `GET` | `/scrapers/last-run` | Résumé du dernier run (status, inserted, errors) |
| `POST` | `/scrapers/run-all` | Lance ALL_SCRAPERS en background |
| `POST` | `/scrapers/run-monthly` | Lance MONTHLY_SCRAPERS en background |
| `POST` | `/scrapers/run/{name}` | Lance un scraper spécifique |
| `POST` | `/purge` | Supprime les événements expirés (> 365 jours) |

---

## Catégories

```
restaurant · bar · cafe · exposition · musee · galerie · cinema
spectacle · musique · atelier · brocante · vide-grenier
popup · boutique · wellness · rooftop · sport · marche
autre: <suggestion>
```

---

## Structure du projet

```
paris_app_project/
├── run.sh                        ← démarre venv + backend + datasette
├── n8n_daily.json                ← workflow n8n (quotidien + mensuel)
├── pyproject.toml
│
├── frontend/
│   ├── paris-explorer.html       ← shell HTML, charge css/main.css + js/*
│   ├── css/
│   │   └── main.css              ← styles extraits du HTML
│   ├── js/                       ← modules ES6, orchestrés par app.js
│   │   ├── app.js                ← orchestrateur, câble les autres modules
│   │   ├── config.js             ← constantes (API_BASE, SOURCE_LABELS...)
│   │   ├── state.js              ← état global (events, filteredEvents...)
│   │   ├── api.js                ← appels backend (/events, /stats...)
│   │   ├── map.js                ← carte Leaflet, markers, selectEvent()
│   │   ├── filters.js            ← filtres période/catégorie
│   │   ├── search.js             ← recherche d'événements/adresse
│   │   ├── render.js             ← rendu sidebar + suggestions
│   │   └── utils.js              ← helpers (toProper, formatSource...)
│   └── img/                      ← icônes et images statiques
│
└── backend/
    ├── main.py                   ← FastAPI — endpoints
    ├── db.py                     ← SQLite — schéma, insert, requêtes
    ├── geocoder.py               ← Nominatim wrapper
    ├── scheduler.py              ← APScheduler (désactivé)
    ├── tests/                    ← tests unitaires (pytest)
    ├── utils/
    │   ├── expo_parser.py        ← extraction expos BS4 + regex
    │   ├── typer.py              ← typage galeries OSM
    │   ├── url_finder.py         ← découverte URLs agenda musées
    │   └── email_reader.py       ← lecteur IMAP
    └── scrapers/
        ├── __init__.py           ← ALL_SCRAPERS, MONTHLY_SCRAPERS
        ├── base.py               ← BaseScraper, extract_with_llm, VALID_CATEGORIES
        ├── website/              ← Playwright / BS4
        ├── editorial/            ← Jina + Playwright + LLM
        ├── opendata/             ← APIs publiques (Paris opendata, INPI)
        └── email/                ← IMAP newsletters (TO_REVIEW)
```

---

## Variables d'environnement (`.env`)

```env
GROQ_API_KEY=...
INPI_USERNAME=...
INPI_PASSWORD=...
IMAP_EMAIL=...
IMAP_PASSWORD=...
```

---

## Règles clés

- Zéro API payante (Google Maps, OpenAI, Mapbox…)
- Ne jamais committer `.env` ou `events.db`
- `identified_date` = date de première découverte — immuable après insertion
- Déduplication par `UNIQUE` sur `url` — ne pas contourner
- Playwright uniquement en fallback (après Jina ou requests)
- `prix` est deprecated — ne plus écrire ce champ

Voir `CLAUDE.md` pour la référence technique exhaustive.
