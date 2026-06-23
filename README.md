# Flâneur Paris

Application de découverte d'événements et d'adresses à Paris, centrée sur la carte.  
Zéro coût d'API — tout repose sur le scraping HTML, les données OSM et des parsers BS4 locaux.

---

## Stack

| Composant | Technologie |
|-----------|-------------|
| Backend | FastAPI + Python 3.12 |
| Scraping | Playwright (sites JS) + Requests + BeautifulSoup 4 |
| Base de données | SQLite (`backend/events.db`) |
| Scheduler | APScheduler (toutes les 24h) |
| Géocodage | Nominatim (OpenStreetMap) |
| Frontend | HTML/CSS/JS vanilla + Leaflet.js |
| Données carte | Overpass API (OpenStreetMap) |

---

## Lancer l'application

```bash
./run.sh
```

Démarre le backend sur **http://localhost:8000** (frontend servi à la racine).

---

## Sources de données

### 1. Événements éditoriaux (scrapers automatiques, toutes les 24h)

| Source | URL | Catégories produites |
|--------|-----|----------------------|
| **Sortir à Paris** | sortiraparis.com | expo, cafe, resto, bienetre, autre |
| **Paris Bouge** | parisbouge.com | expo, brocante, autre |
| **Le Bonbon** | lebonbon.fr | cafe, resto, autre |
| **Do It In Paris** | doitinparis.com | expo, resto, cafe, bienetre, autre |
| **Nouveaux Cafés** | sortiraparis.com/guides | cafe |
| **Nouveaux Restos** | sortiraparis.com/restaurant | resto |
| **NewTable** | fr.newtable.com | resto (nouveaux restaurants uniquement) |

### 2. Brocantes & vide-greniers

| Source | URL | Particularité |
|--------|-----|---------------|
| **Ville de Paris** | paris.fr/pages/brocantes-et-vide-greniers | Dates précises (jour J) + adresse exacte |

### 3. Musées — agendas d'expositions (35 musées parisiens)

Déclenchés à chaque pose de pin sur la carte, puis throttlés à 6h par musée.  
Parser BS4 générique + parsers spécifiques pour certains sites.

| Musée | Domaine |
|-------|---------|
| Louvre | louvre.fr |
| Musée d'Orsay | musee-orsay.fr |
| Centre Pompidou | centrepompidou.fr |
| Musée Picasso | museepicassoparis.fr |
| Quai Branly | quaibranly.fr |
| Musée Rodin | musee-rodin.fr |
| Marmottan Monet | marmottan.fr |
| Musée de l'Orangerie | musee-orangerie.fr |
| Musée Guimet | guimet.fr |
| MAM Paris | mam.paris.fr |
| Palais de Tokyo | palaisdetokyo.com |
| Les Arts Décoratifs | lesartsdecoratifs.fr |
| Fondation Louis Vuitton | fondationlouisvuitton.fr |
| Institut du Monde Arabe | imarabe.org |
| Petit Palais | petitpalais.paris.fr |
| Palais Galliera | palaisgalliera.paris.fr |
| Musée Jacquemart-André | musee-jacquemart-andre.com |
| MAHJ | mahj.org |
| MEP (Photo) | mep-fr.org |
| Musée Cognacq-Jay | museecognacqjay.paris.fr |
| Musée de Cluny | musee-moyenage.fr |
| Musée de l'Homme | museedelhomme.fr |
| Cité des Sciences | cite-sciences.fr |
| Musée de l'Armée | musee-armee.fr |
| Fondation Azzedine Alaïa | fondationazzedinealaia.org |
| Maisons Victor Hugo | maisonsvictorhugo.paris.fr |
| Atelier des Lumières | atelier-lumieres.com |
| Musée de Montmartre | museedemontmartre.fr |
| Institut Suédois | paris.si.se |
| Musée Carnavalet | carnavalet.paris.fr |
| Musée Delacroix | musee-delacroix.fr |
| Grand Palais Immersif | grandpalais-immersif.fr |
| Musée de la Chasse | chassenature.org |
| Mémorial de la Shoah | memorialdelashoah.org |
| Archives Nationales | archives-nationales.culture.gouv.fr |

### 4. Galeries d'art (scraping à la demande)

Découvertes via Overpass OSM (`tourism=gallery`) dans le rayon de recherche.  
Typage automatique via tags OSM puis mots-clés : `photographie`, `sculpture`, `art_contemporain`, `peinture`, `estampe`, `design`, `art_du_monde`, `antiquites`, `illustration`, `street_art`, `inconnu`.  
Extraction d'expositions via parser BS4 multi-stratégies (balises `<time>`, patterns textuels FR, classes CSS).

### 5. Données carte en temps réel (frontend → Overpass)

Récupérées directement depuis le navigateur à chaque recherche :

| Type | Tag OSM |
|------|---------|
| Musées | `tourism=museum` |
| Galeries | `tourism=gallery` |
| Cinémas | `amenity=cinema` |

---

## Catégories

| Catégorie | Emoji | Description |
|-----------|-------|-------------|
| `musee` | 🏛 | Musées (OSM) |
| `galerie` | 🎨 | Galeries d'art (OSM) |
| `cinema` | 🎬 | Cinémas (OSM) |
| `resto` | 🍽 | Restaurants (nouveaux ou signalés) |
| `cafe` | ☕ | Cafés, coffee shops, brunchs |
| `bienetre` | 🧘 | Spas, yoga, pilates, fitness, massage, hammam |
| `expo` | 🖼 | Expositions, galeries éditoriales, vernissages |
| `brocante` | 🏺 | Brocantes et vide-greniers datés |
| `autre` | 📍 | Événements non catégorisés |

La catégorisation est automatique via mots-clés sur le titre + texte de l'événement.  
Ordre de priorité : `cafe` → `resto` → `expo` → `bienetre` → `autre`.

---

## Marqueurs musées et galeries — 3 états

| Couleur | Signification |
|---------|--------------|
| 🟢 Vert `#4CAF50` | Exposition récente (ouverte dans les 30 derniers jours) |
| 🟡 Or/Violet | Parser fonctionnel, pas d'expo récente en ce moment |
| ⚫ Gris `#5C6470` | Parser KO (site bloqué, JS pur non rendu) ou jamais scrapé |

---

## Logique d'affichage des événements

### Événements standard (restos, cafés, expos, bienetre, autre)
Affichés si `identified_date >= aujourd'hui - N jours` (N = paramètre `days`, défaut 30).  
`identified_date` = date à laquelle le scraper a découvert l'événement.

### NewTable (nouveaux restaurants)
`identified_date = date_debut = 1er du mois d'ouverture`.  
Un restaurant ouvert en avril n'apparaît que si la fenêtre de recherche couvre avril.

### Brocantes datées
Affichées uniquement le jour J : `date_debut ≤ aujourd'hui ≤ date_fin`.

### Brocantes permanentes (marchés aux puces)
`date_debut IS NULL` → toujours visibles dans le rayon.

### Expositions musées & galeries
Affichées si `date_debut` dans les 30 derniers jours ET `date_fin >= aujourd'hui`.

---

## Fréquence de scraping

| Source | Fréquence | Déclencheur |
|--------|-----------|-------------|
| Scrapers éditoriaux (7 sources) | Toutes les 24h | Scheduler au démarrage du serveur |
| Brocantes paris.fr | Toutes les 24h | Scheduler au démarrage du serveur |
| Musées (35 sites) | Max 1x toutes les 6h par musée | Pose de pin sur la carte |
| Galeries | Max 1x toutes les 6h par galerie | Pose de pin sur la carte |

Les scrapers démarrent avec un décalage de 5 minutes entre chaque pour ne pas surcharger les serveurs.

---

## API

| Endpoint | Méthode | Paramètres | Description |
|----------|---------|------------|-------------|
| `/` | GET | — | Frontend HTML |
| `/events` | GET | `lat`, `lng`, `radius`, `days`, `cat` | Événements dans un rayon |
| `/museum-events` | GET | `lat`, `lng`, `radius`, `days` | Musées avec expositions récentes |
| `/museum-events/scrape` | POST | `lat`, `lng`, `radius` | Déclenche le scraping musées |
| `/gallery-data` | GET | `lat`, `lng`, `radius`, `days` | Galeries avec expositions récentes |
| `/gallery-data/scrape` | POST | `lat`, `lng`, `radius` | Déclenche le scraping galeries |
| `/stats` | GET | — | Statistiques base de données |

---

## Structure du projet

```
├── paris-explorer.html          # Frontend (carte Leaflet + UI)
├── run.sh                       # Script de démarrage
├── .env                         # Clés API (non versionné)
├── backend/
│   ├── main.py                  # FastAPI — endpoints
│   ├── db.py                    # SQLite — schéma et requêtes
│   ├── scheduler.py             # APScheduler — scraping automatique
│   ├── geocoder.py              # Nominatim — adresse → coordonnées GPS
│   ├── scrapers/
│   │   ├── base.py              # BaseScraper + detect_category()
│   │   ├── sortirparis.py
│   │   ├── parisbouge.py
│   │   ├── lebonbon.py
│   │   ├── nouveaux_cafes.py
│   │   ├── nouveaux_restos.py
│   │   ├── doitinparis.py
│   │   ├── newtable.py          # Nouveaux restaurants (mois d'ouverture)
│   │   ├── museum_events.py     # 35 musées parisiens
│   │   └── galleries.py        # Galeries OSM + typage + expos
│   └── utils/
│       ├── typer.py             # Typage galeries (OSM tags + mots-clés)
│       ├── expo_parser.py       # Extraction d'expos HTML (sans LLM)
│       └── url_finder.py        # Découverte URL agenda
└── tests/
    └── test_utils.py            # 18 tests unitaires (pytest)
```

---

## Variables d'environnement (`.env`)

```
ANTHROPIC_API_KEY=...          # Clé Anthropic (non utilisée activement — pas de crédits)
NEWSLETTER_EMAIL=...           # Boîte Gmail newsletters
NEWSLETTER_IMAP_PASSWORD=...   # Mot de passe application Google (IMAP)
```

---

## Newsletters (parsers à venir)

Boîte `valentinainewsletters@gmail.com` — inscrite aux newsletters suivantes.  
Les parsers seront écrits à l'arrivée des premiers emails.

| Newsletter | Statut |
|------------|--------|
| Le Fooding | ⏳ En attente du premier email |
| Sortir à Paris | ⏳ En attente |
| Paris Bouge | ⏳ En attente |
| Do It In Paris | ⏳ En attente |
| NewTable | ⏳ En attente |
