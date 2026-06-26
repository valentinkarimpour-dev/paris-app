# CLAUDE.md — Flâneur

Document de référence exhaustif basé sur le code réel du repo.
**Lire ce fichier en entier avant de modifier quoi que ce soit.**

---

## 1. Vue d'ensemble

**Flâneur** est une web app de découverte géolocalisée à Paris.
L'utilisateur pose un pin sur une carte, définit un rayon, et voit
tous les événements et lieux d'intérêt autour de lui.

- **Usage :** personnel, desktop-first, Paris uniquement
- **Philosophie :** zéro API payante, dégradation gracieuse si composant indisponible
- **Déploiement :** `http://145.241.168.3:8000/`
- **Python :** 3.12 (voir `.python-version`)
- **Datasette :** `http://145.241.168.3:8001/` (inspection SQLite)

---

## 2. Stack technique

### Backend

| Composant | Technologie |
|---|---|
| Framework | FastAPI + Uvicorn |
| Base de données | SQLite (`backend/events.db`) |
| Scraping JS-heavy | Playwright (Chromium headless) |
| Scraping sites statiques | Jina Reader (`r.jina.ai/{url}`) puis Playwright en fallback |
| Parsing HTML | BeautifulSoup4 + lxml |
| Extraction LLM | Groq — `llama-3.1-8b-instant` (gratuit jusqu'à 14 400 req/jour) |
| Géocodage | Nominatim OSM (`geocoder.py`) — 1 req/s max |
| Géocodage INPI | `api-adresse.data.gouv.fr` (dans `inpi_api.py`) |
| Orchestration | **n8n** (workflow `n8n_daily.json`) — APScheduler interne désactivé |
| Variables d'env | `.env` à la racine du projet |

### Frontend

| Composant | Technologie |
|---|---|
| Carte | Leaflet.js 1.9.4 |
| Tile | CartoDB Voyager |
| POI statiques | Overpass API (cinémas, musées, galeries OSM) |
| Font | Plus Jakarta Sans (Google Fonts) |
| Couleur principale | `rgb(0, 246, 111)` |
| Fichier | `frontend/paris-explorer.html` (single-file HTML) |
| API_BASE | `http://145.241.168.3:8000` |

---

## 3. Structure complète du projet

```
paris_app_project/
├── CLAUDE.md                              ← ce fichier
├── run.sh                                 ← démarre venv + backend + datasette
├── pyproject.toml                         ← Python 3.12, dépendances uv
├── n8n_daily.json                         ← workflow n8n d'orchestration quotidienne
├── .python-version                        ← "3.12"
├── .gitignore
│
├── frontend/
│   └── paris-explorer.html                ← app complète (HTML/CSS/JS vanilla)
│
├── backend/
│   ├── main.py                            ← FastAPI, tous les endpoints
│   ├── db.py                              ← init SQLite, insert_event, get_events_in_radius
│   ├── geocoder.py                        ← Nominatim wrapper (1 req/s, cache en mémoire)
│   ├── scheduler.py                       ← APScheduler (désactivé, remplacé par n8n)
│   ├── requirements.txt
│   ├── events.db                          ← ne pas committer
│   ├── .env                               ← ne jamais committer
│   │
│   ├── utils/
│   │   ├── expo_parser.py                 ← extraction expos BS4+regex (sans LLM)
│   │   ├── typer.py                       ← typage galeries par tags OSM + mots-clés
│   │   ├── url_finder.py                  ← trouve les URLs d'agenda des musées
│   │   └── email_reader.py               ← lecteur IMAP (live.fr mailbox)
│   │
│   └── scrapers/
│       ├── __init__.py                    ← ALL_SCRAPERS, MONTHLY_SCRAPERS, TO_REVIEW
│       ├── base.py                        ← BaseScraper, extract_with_llm, extract_list_with_llm
│       │
│       ├── website/                       ← scrapers Playwright/BS4
│       │   ├── parisbouge_bars.py
│       │   ├── parisbouge_restos.py
│       │   ├── parisbouge_expos.py
│       │   ├── parisbouge_autre.py
│       │   ├── lebonbon_food.py
│       │   ├── lebonbon_drinks.py
│       │   ├── lebonbon_news.py
│       │   ├── nouveaux_cafes.py
│       │   ├── nouveaux_restos.py
│       │   ├── doitinparis.py
│       │   ├── newtable.py
│       │   ├── numero_popup.py
│       │   ├── sortirparis.py             ← ancien scraper website (pas editorial)
│       │   ├── museum_events.py           ← scraper musées + galeries (BS4, sans LLM)
│       │   ├── parismusee_expos.py        ← MONTHLY_SCRAPERS
│       │   ├── museofile.py               ← MONTHLY_SCRAPERS
│       │   └── secrets_of_paris.py        ← MONTHLY_SCRAPERS (anglais → LLM traduit)
│       │
│       ├── editorial/                     ← scrapers Jina + Playwright fallback
│       │   ├── jina_base.py               ← JinaBaseScraper (classe de base)
│       │   └── sources.py                 ← SortirAParis, TimeOutParis
│       │
│       ├── opendata/                      ← scrapers APIs publiques
│       │   ├── paris_opendata.py          ← Que Faire à Paris (brocantes, opendata)
│       │   ├── inpi_api.py                ← logique INPI (token, fetch, filtrage NAF)
│       │   ├── inpi_api_food.py           ← wrapper InpiFoodScraper (NAF 5610A)
│       │   └── inpi_api_drinks.py         ← wrapper InpiDrinksScraper (NAF 5630Z)
│       │
│       └── email/                         ← scrapers IMAP newsletter (TO_REVIEW)
│           ├── timeout_paris.py           ← newsletters TimeOut via IMAP
│           ├── lefooding.py               ← newsletters Le Fooding
│           └── lessentiel_paris.py        ← newsletter L'Essentiel Paris
│
└── scripts/                               ← scripts one-shot, ne pas inclure dans scrapers
    ├── seed_museums_wikipedia.py
    ├── remediate_events.py
    ├── fix_doitinparis_dates.py
    └── api_v1.py
```

---

## 4. Orchestration — n8n (pas APScheduler)

**Important :** le scheduler APScheduler dans `scheduler.py` est désactivé
(`start_scheduler()` commenté dans `main.py`). L'orchestration est entièrement
déléguée à **n8n** via le fichier `n8n_daily.json`.

Workflow n8n quotidien :
```
Schedule Trigger
    → POST /scrapers/run-all        (lance ALL_SCRAPERS en background tasks)
    → Wait 5 min
    → GET /scrapers/last-run        (récupère le résumé du run)
    → IF Success
        → Slack OK
        → Slack Error
```

Pour déclencher un scraper manuellement :
```bash
curl -X POST http://145.241.168.3:8000/scrapers/run/{name}
# ex: curl -X POST http://145.241.168.3:8000/scrapers/run/sortiraparis
```

---

## 5. API Endpoints (main.py)

| Méthode | Route | Paramètres | Description |
|---|---|---|---|
| `GET` | `/` | — | Sert `frontend/paris-explorer.html` |
| `GET` | `/events` | `lat`, `lng`, `radius` (100-5000), `days` (1-365, défaut 30), `cat` (optionnel) | Events dans le rayon |
| `GET` | `/stats` | — | Total events, par catégorie, par source |
| `GET` | `/scrapers` | — | Liste des scrapers disponibles |
| `GET` | `/scrapers/last-run` | — | Résumé du dernier run (run_id, status, inserted, errors) |
| `POST` | `/scrapers/run-all` | — | Lance ALL_SCRAPERS en background |
| `POST` | `/scrapers/run-monthly` | — | Lance MONTHLY_SCRAPERS en background |
| `POST` | `/scrapers/run/{name}` | path: nom du scraper | Lance un scraper spécifique |

**Note :** les endpoints `/museum-events` et `/museum-events/scrape` sont appelés
par le frontend mais **ne sont pas dans main.py actuel** — à vérifier/réimplémenter
si nécessaire.

### Réponse `/events`

```json
{
  "count": 12,
  "events": [
    {
      "id": 42,
      "titre": "rosa rosam rosae",
      "categorie": "cafe",
      "adresse": "27 rue veron, 75018 paris",
      "lat": 48.884,
      "lng": 2.334,
      "date_debut": "2026-03-14",
      "date_fin": null,
      "identified_date": "2026-06-09",
      "source": "sortiraparis",
      "url": "https://...",
      "dist_m": 342
    }
  ]
}
```

---

## 6. Base de données (db.py)

### Schéma commun (toutes les tables `events_{source}`)

```sql
CREATE TABLE IF NOT EXISTS events_{src} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    titre           TEXT NOT NULL,
    description     TEXT,
    adresse         TEXT,
    lat             REAL,
    lng             REAL,
    date_debut      TEXT,           -- YYYY-MM-DD
    date_fin        TEXT,           -- YYYY-MM-DD, NULL si lieu permanent
    duree_jours     INTEGER,
    categorie       TEXT,
    prix            TEXT,           -- deprecated, ne plus utiliser
    source          TEXT,
    url             TEXT UNIQUE,    -- contrainte de déduplication principale
    image_url       TEXT,
    scraped_at      TEXT,
    identified_date TEXT            -- date de 1ère découverte, JAMAIS mise à jour
);
```

### `_SOURCE_TABLES` — liste exhaustive et ordre exact

```python
_SOURCE_TABLES = [
    "timeout_paris",
    "paris_opendata",
    "paris_fr",
    "parisbouge_autre",
    "parisbouge_restos",
    "parisbouge_bars",
    "parisbouge_expos",
    "sortiraparis",
    "newtable",
    "lebonbon_news",
    "lebonbon_food",
    "lebonbon_drinks",
    "parismusee_expos",
    "secrets_of_paris",
    "numero_popup",
    "inpi_food",
    "inpi_drinks",
]
```

La vue `master_events` est un `UNION ALL` de toutes ces tables.

### Autres tables

| Table | Rôle |
|---|---|
| `events` | Table legacy (données migrées vers tables sources) |
| `museum_list` | Musées enrichis (nom, lat, lng, url) |
| `galeries` | Galeries d'art découvertes via Overpass |
| `gallery_events` | Expositions en cours par galerie, avec `confidence=high/low` |
| `gallery_scrape_log` | Historique scrapes galeries (throttling 6h) |
| `scraper_runs` | Log de tous les runs (run_id, scraper, status, inserted, duration_s) |
| `category_suggestions` | Suggestions "autre: X" du LLM pour review manuelle |

### Fonctions importantes

```python
init_db()                    # Crée tables + vue + migrations
insert_event(ev: dict)       # INSERT OR IGNORE (UNIQUE url), retourne True si inséré
get_events_in_radius(lat, lng, radius_m, days=30, cat=None)  # Query principale
upsert_museum(m: dict)       # INSERT OR UPDATE museum_list
scraper_run_start(run_id, scraper)
scraper_run_end(run_id, scraper, inserted, error_msg=None)
get_last_run_summary()       # Résumé complet du dernier run
purge_old_events(keep_days=365)
```

### Règles critiques DB

- `identified_date` = date du premier scraping. **Ne jamais mettre à jour après.**
- `_normalize_str()` lowercase + supprime diacritiques avant insertion.
  → Titres et adresses stockés en minuscules. Le frontend applique `toProper()`.
- `UNIQUE` sur `url` = mécanisme principal de déduplication. Ne pas contourner.
- `prix` est deprecated — ne plus écrire ce champ dans les nouveaux scrapers.

---

## 7. Scrapers — détail complet

### ALL_SCRAPERS (run quotidien via n8n)

| Classe | `name` (= table) | Technologie | Source |
|---|---|---|---|
| `ParisOpenData` | `paris_opendata` | API REST | Que Faire à Paris opendata |
| `ParisBougeAutre` | `parisbouge_autre` | Playwright | parisbouge.com |
| `ParisBougeRestos` | `parisbouge_restos` | Playwright | parisbouge.com |
| `ParisBougeBars` | `parisbouge_bars` | Playwright | parisbouge.com |
| `ParisBougeExpos` | `parisbouge_expos` | Playwright | parisbouge.com |
| `NewTable` | `newtable` | Playwright | fr.newtable.com |
| `LeBonbonNews` | `lebonbon_news` | Playwright+BS4 | lebonbon.fr |
| `LeBonbonFood` | `lebonbon_food` | Playwright+BS4 | lebonbon.fr |
| `LeBonbonDrinks` | `lebonbon_drinks` | Playwright+BS4 | lebonbon.fr |
| `NumeroPopup` | `numero_popup` | Playwright+LLM | numero.com |
| `InpiFoodScraper` | `inpi_food` | API INPI | RNE immatriculations NAF 5610A |
| `InpiDrinksScraper` | `inpi_drinks` | API INPI | RNE immatriculations NAF 5630Z |
| `SortirAParis` | `sortiraparis` | Jina+Playwright+LLM | sortiraparis.com |
| `TimeOutParis` | `timeout_paris` | Jina+Playwright+LLM | timeout.fr/paris |

### MONTHLY_SCRAPERS (run mensuel)

| Classe | `name` | Technologie | Note |
|---|---|---|---|
| `SecretsOfParis` | `secrets_of_paris` | Playwright+LLM | Anglais → LLM traduit en FR |
| `ParisMuseeExpos` | `parismusee_expos` | BS4 | API Paris Musées |
| `MuseofileScraper` | `museofile` | BS4 | Base museofile.culture.fr |

### Email scrapers (TO_REVIEW — hors production)

| Classe | Fichier | Source |
|---|---|---|
| `LeFooding` | `email/lefooding.py` | Newsletter Le Fooding (IMAP) |
| `LessentielParis` | `email/lessentiel_paris.py` | Newsletter L'Essentiel Paris (IMAP) |
| (ancien) `TimeOutParis` | `email/timeout_paris.py` | Newsletter TimeOut via IMAP |

> ⚠️ La classe `TimeOutParis` en `email/` est l'ancienne version newsletter.
> La version active est `editorial/sources.py` (Jina-based).

### Scrapers website legacy (pas dans ALL_SCRAPERS)

- `sortirparis.py` dans `website/` — ancienne version, remplacée par `editorial/sources.py`
- `nouveaux_cafes.py`, `nouveaux_restos.py` — vérifier si encore utilisés

---

## 8. JinaBaseScraper (editorial/)

Stratégie fetch en deux temps :
1. `fetch_jina(url)` : GET `https://r.jina.ai/{url}` → markdown, retourne "" si < 500 chars
2. `fetch_playwright(url)` : fallback Chromium headless si Jina vide

Attributs à surcharger dans les sous-classes :

```python
index_urls: list[str] = []            # pages listant les articles (prioritaire sur index_url)
index_url: str = ""                   # rétrocompat si index_urls vide
article_url_pattern: str = ""         # regex pour filtrer les URLs d'articles
exclude_url_patterns: list[str] = []  # patterns à exclure (agendas génériques, etc.)
max_articles: int = 10                # nb max d'articles par run (total, pas par index)
require_dates: bool = False           # si True, filtre les events éphémères sans dates
```

### SortirAParis (config actuelle)

```python
name = "sortiraparis"
article_url_pattern = r"sortiraparis\.com/.*/articles/\d+"
require_dates = True
exclude_url_patterns = [
    r"que-faire-ce-",
    r"que-faire-a-paris",
    r"bons-plans-du-week",
    r"selection-week-end",
]
max_articles = 15
index_urls = [
    "https://www.sortiraparis.com/hotel-restaurant/restaurant",
    "https://www.sortiraparis.com/hotel-restaurant/cafe-tea-time",
    "https://www.sortiraparis.com/arts-culture/exposition",
    "https://www.sortiraparis.com/articles/tag/pop-up-store",
    "https://www.sortiraparis.com/articles/tag/boutique-ephemere",
]
```

### TimeOutParis (config actuelle)

```python
name = "timeout_paris"
article_url_pattern = r"timeout\.fr/paris/[^/]+/[^/]+-\d{6}$"
require_dates = True
max_articles = 15
index_urls = [
    "https://www.timeout.fr/paris/que-faire-a-paris/les-meilleurs-plans-de-la-semaine",
    "https://www.timeout.fr/paris/que-faire-a-paris/5-choses-a-faire-aujourdhui",
]
```

---

## 9. Extraction LLM (base.py)

**Modèle :** Groq `llama-3.1-8b-instant`, max_tokens=200, temperature=0

**Champs extraits :**

| Champ | Description | Règle clé |
|---|---|---|
| `titre` | Nom propre du lieu | Court, pas de description |
| `description` | Résumé 2 phrases max | Neutre et factuel |
| `adresse` | N° + rue + CP parisien | null si absente |
| `date_debut` | YYYY-MM-DD | null si inconnue |
| `date_fin` | YYYY-MM-DD | **null si lieu permanent** même si date d'ouverture mentionnée |
| `duree_jours` | Entier | Calculé depuis dates ou expression textuelle |
| `categorie` | Voir liste ci-dessous | "autre: suggestion" si rien ne convient |

**Post-processing :**
- `"null"` string → `None` Python
- Blocs markdown ` ```json ` retirés avant parsing
- `_normalize_categorie()` appliqué au champ categorie

**Fonctions disponibles :**
- `extract_with_llm(page_text)` → `dict` (un seul event par article)
- `extract_list_with_llm(page_text, translate_to_french=False)` → `list[dict]` (multi-events, newsletters)
- `extract_venue_llm(title, description)` → `tuple[nom, categorie]`

---

## 10. Catégories valides

```python
VALID_CATS = {
    "restaurant", "bar", "exposition", "musee", "galerie", "cafe",
    "brocante", "vide-grenier", "popup", "wellness", "rooftop",
    "musique", "marche", "cinema", "spectacle", "sport", "atelier", "boutique",
}
# Format invalide → "autre: [suggestion en minuscules]"
```

**Règle absolue :** `"brocante"` = uniquement marchés éphémères.
Jamais pour une boutique permanente.

**Aliases reconnus dans `_normalize_categorie()` :**
`expo → exposition`, `musée → musee`, `pop-up/pop up → popup`, `bien-être → wellness`, etc.

**Filtre `require_dates` par catégorie :**
```python
CATEGORIES_EPHEMERES = {
    "exposition", "popup", "galerie", "musique",
    "spectacle", "cinema", "atelier", "marche",
}
# Ces catégories sont filtrées si dates absentes (quand require_dates=True)
# restaurant, bar, cafe, boutique, wellness, rooftop → passent toujours
```

---

## 11. INPI — immatriculations F&B

**API :** `https://registre-national-entreprises.inpi.fr/api`
**Auth :** POST `/sso/login` → JWT token (credentials dans `.env`)

**Codes NAF ciblés (format sans points) :**
```python
NAF_CIBLES = {
    "5610A",  # Restauration traditionnelle (bistronomique, gastronomique, table)
    "5630Z",  # Débits de boissons (bars, cafés, salons de thé, wine bars)
    # Exclus : 5610B (cantines), 5610C (restauration rapide), 5621Z (traiteurs)
}
```

**Règle légale :** vérifier `diffusionCommerciale`. Si `False`, ne pas insérer.

**Géocodage INPI :** `api-adresse.data.gouv.fr` (pas Nominatim)
```
GET https://api-adresse.data.gouv.fr/search/?q={adresse}&limit=1
```

---

## 12. Museum events (museum_events.py)

Scraper BS4 sans LLM — zéro coût.

**Flow :**
1. Overpass → liste musées avec `website` dans le rayon
2. `MUSEUM_CONFIGS` → URL agenda connue OU `find_agenda_url()` en fallback
3. `_parse_generic()` → extraction BS4 multi-patterns (article/card, `<time>`, regex date FR)
4. Parser spécifique Marmottan (`_parse_marmottan()`)

**Throttling :** 6h par musée (via `gallery_scrape_log`)

**35 musées configurés** (voir README.md pour la liste complète)

**Galeries :** typage via `utils/typer.py` — tags OSM + mots-clés dans nom/description
Types : photographie, sculpture, art_contemporain, peinture, estampe, design,
art_du_monde, antiquites, illustration, street_art, inconnu

---

## 13. Frontend (paris-explorer.html)

### Fonctions principales

```javascript
placePin(lat, lng)              // Pose pin, lance searchEvents()
searchEvents()                  // Fetch Overpass+backend en parallèle, merge, filtre, render
fetchPOI(lat, lng, radius)      // Overpass API → cinémas, musées, galeries OSM
fetchBackendEvents(lat, lng, radius)   // GET /events
fetchMuseumExpos(lat, lng, radius)     // GET /museum-events (endpoint à vérifier)
renderEvents(events)            // Cards dans sidebar
renderMarkers(events)           // Markers Leaflet sur carte
applyPeriodFilter(events)       // Filtre selon periodMode
updateCatCounts(filtered)       // Compteurs dans chips catégorie
toProper(str)                   // Proper case (titres + adresses à l'affichage)
formatSource(source)            // "sortiraparis" → "Sortir à Paris"
```

### Mapping SOURCE_LABELS

```javascript
const SOURCE_LABELS = {
  'lebonbon_food':    'LeBonbon',
  'lebonbon_drinks':  'LeBonbon',
  'lebonbon_news':    'LeBonbon',
  'sortiraparis':     'Sortir à Paris',
  'timeout_paris':    'Time Out Paris',
  'paris_opendata':   'Paris Opendata',
  'paris_fr':         'Paris.fr',
  'parisbouge_bars':  'ParisBouge',
  'parisbouge_restos':'ParisBouge',
  'parisbouge_expos': 'ParisBouge',
  'newtable':         'NewTable',
  'inpi_food':        'INPI',
  'inpi_drinks':      'INPI',
  'numero_popup':     'Numéro',
  'secrets_of_paris': 'Secrets of Paris',
  'parismusee_expos': 'Paris Musées',
  'OpenStreetMap':    'OpenStreetMap',
};
```

### Filtre période (applyPeriodFilter)

```javascript
// "En cours" :
// - Pas de dates du tout → lieu permanent → toujours affiché
// - date_debut dans le futur → masqué
// - date_fin dans le passé → masqué
// - Sinon → affiché
```

### Variables CSS principales

```css
--green:      rgb(0, 246, 111);
--green-dim:  rgba(0, 246, 111, 0.15);
--green-glow: rgba(0, 246, 111, 0.35);
--ink:        #0F1117;
--cream:      #F7F7F5;
--stone:      #8A8F98;
--gold:       #F5C842;
--sidebar-w:  380px;
```

---

## 14. Variables d'environnement (.env)

```env
GROQ_API_KEY=...
INPI_USERNAME=...          # Email du compte data.inpi.fr
INPI_PASSWORD=...          # Mot de passe du compte data.inpi.fr
IMAP_EMAIL=...@live.fr     # Pour scrapers email (TO_REVIEW)
IMAP_PASSWORD=...          # Microsoft App Password (pas le mot de passe du compte)
```

---

## 15. Démarrage (`run.sh`)

```bash
./run.sh
# Crée .venv si absent
# pip install -r backend/requirements.txt
# playwright install chromium (si absent)
# Lance datasette sur :8001 (background)
# Lance uvicorn backend.main:app --reload --port 8000
```

---

## 16. Règles absolues — ne jamais violer

### Interdictions

- Utiliser une API payante (Google Maps, OpenAI, Mapbox...)
- Committer `.env` ou `events.db`
- Faire crasher le scheduler : `scrape()` doit être wrappé try/except dans `run()`
- Modifier `identified_date` après la première insertion
- Classer une boutique permanente en "brocante"
- Modifier `_SOURCE_TABLES` sans créer la table correspondante
- Appeler `start_scheduler()` dans main.py (désactivé, n8n prend le relais)

### Obligations

- Credentials uniquement dans `.env`, chargé via `python-dotenv`
- Playwright uniquement en fallback (après Jina ou requests)
- Sleep entre appels Jina/Groq (rate limiting)
- `UNIQUE` sur `url` pour la déduplication — ne pas contourner
- Vérifier `diffusionCommerciale` dans les données INPI
- Tout nouveau scraper dans `try/except` complet

### Ajouter un nouveau scraper (checklist)

1. Créer la classe dans `scrapers/website/` ou `scrapers/editorial/`
2. Ajouter `"nom_source"` dans `_SOURCE_TABLES` dans `db.py`
3. Importer et ajouter dans `ALL_SCRAPERS` dans `scrapers/__init__.py`
4. Ajouter le label dans `SOURCE_LABELS` dans `frontend/paris-explorer.html`
5. Ne jamais réutiliser un `name` déjà dans `_SOURCE_TABLES`

---

## 17. Décisions d'architecture passées (ne pas remettre en question)

| Décision | Raison |
|---|---|
| SQLite (pas Postgres) | Projet personnel, zéro ops, Datasette pour inspection |
| Une table par scraper | Isolation, purge ciblée, debug facile par source |
| n8n à la place d'APScheduler | Visibilité run, Slack alerts, retry configurable sans redéploiement |
| Groq (pas Claude API) | Gratuit jusqu'à 14 400 req/jour pour llama-3.1-8b |
| Jina Reader pour sites éditoriaux | Plus rapide, pas de browser overhead |
| Nominatim pour géocodage général | Gratuit, OSM, centré France |
| api-adresse.data.gouv.fr pour INPI | Meilleure précision sur adresses parisiennes |
| Overpass pour cinémas/musées/galeries | Données stables, pas besoin de scraper |
| Pas de LLM pour parsers musées/galeries | Coût trop élevé, BS4+regex suffisant |
| `identified_date` immuable | Signal de fraîcheur fiable indépendant des mises à jour |
| `prix` deprecated | Supprimé du frontend, ne plus écrire |

---

## 18. État actuel et prochaines étapes

### Fonctionnel en production
- Scraping quotidien via n8n : 14 scrapers dans ALL_SCRAPERS
- Endpoint `/museum-events` appelé par le frontend — **à vérifier dans main.py**
- Filtres frontend : catégorie, rayon, période (En cours / Récents / Tous)
- Géolocalisation native (bouton 📍)
- Recherche d'adresse (api-adresse.data.gouv.fr)
- Déduplication titres dans `JinaBaseScraper.scrape()`
- Barre fraîcheur, badges "Nouveau", timing ouvert/ferme sur les cards

### Quick wins identifiés
- Persistance position en `localStorage`
- Query params URL (`?lat=&lng=&radius=`) pour partage
- Bouton "Ouvrir dans Google Maps" sur popup
- Clustering markers (Leaflet.markercluster) à grand rayon
- Events sans lat/lng : indicateur visuel dans la card

### TO_REVIEW (avant remise en production)
- Scrapers email (lefooding, lessentiel_paris, email/timeout_paris)
- `sortirparis.py` et `nouveaux_cafes.py`, `nouveaux_restos.py` dans website/
  → vérifier si toujours utiles ou remplacés par les scrapers editorial
