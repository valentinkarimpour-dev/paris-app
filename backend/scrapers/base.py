import json
import logging
import os
import re
import re as _re_region
import sys
from abc import ABC, abstractmethod
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
import geocoder

logger = logging.getLogger(__name__)

_IDF_DEPTS = frozenset({'91', '92', '93', '94', '95'})


def _classify_region(adresse: str | None, lat: float | None) -> str:
    """Classifie 'paris' ou 'ile_de_france' depuis adresse ou lat."""
    if adresse:
        m = _re_region.search(r'\b(75|91|92|93|94|95)\d{3}\b', adresse)
        if m:
            dept = m.group(1)
            return 'ile_de_france' if dept in _IDF_DEPTS else 'paris'
    if lat is not None:
        if lat < 48.815 or lat > 48.905:
            return 'ile_de_france'
    return 'paris'


_groq_client = None

def _get_groq():
    global _groq_client
    if _groq_client:
        return _groq_client
    # Cherche .env en remontant
    current = Path(__file__).parent
    for _ in range(5):
        candidate = current / ".env"
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            break
        current = current.parent
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    try:
        from groq import Groq
        _groq_client = Groq(api_key=key)
        return _groq_client
    except Exception:
        return None


def extract_with_llm(page_text: str) -> dict:
    """
    Passe le texte brut d'un article à Groq et retourne un dict structuré :
    {titre, description, adresse, date_debut, duree_jours, categorie}
    Retourne {} si échec.
    """
    client = _get_groq()
    if not client:
        return {}

    prompt = f"""Tu analyses un article sur un lieu ou événement parisien.
Extrait ces informations et réponds UNIQUEMENT en JSON valide, sans commentaire.

Champs attendus :
- titre        : nom propre de l'événement, de l'exposition ou du lieu.
                     Si l'article décrit un événement dans un lieu connu,
                     le titre est le nom de l'événement/exposition, pas le lieu.
                     Ex: "Exposition Pomellato" et non "Palais de Tokyo",
                     "Festival Yardland" et non "Hippodrome de Vincennes",
                     "L'Alcazar" si c'est le restaurant lui-même qui est décrit.
- description  : résumé en 2 phrases max, neutre et factuel
- adresse      : adresse complète avec numéro + rue + code postal
    parisien si disponible. Si pas d'adresse de rue
    mais un lieu nommé est mentionné (musée, salle,
    parc, palais, hippodrome, stade, jardin, galerie),
    retourner le nom du lieu seul
    (ex: "Palais de Tokyo", "Jardins des Tuileries",
    "Hippodrome de Vincennes", "Grande Halle de la Villette").
    null uniquement si aucune localisation n'est
    mentionnée dans le texte.
- date_debut   : date d'ouverture ou de début au format YYYY-MM-DD.
    Si seul le jour et le mois sont mentionnés sans l'année, utilise l'année en cours ({date.today().year}).
    Exemples de patterns à détecter :
      "ouvre le 15 juin" → "{date.today().year}-06-15"
      "à partir du 3 juillet" → "{date.today().year}-07-03"
      "du 20 juin au 5 juillet" → date_debut = "{date.today().year}-06-20"
      "depuis le 1er mai" → "{date.today().year}-05-01"
    null si aucune date de début n'est mentionnée ou inférable.
- date_fin      : YYYY-MM-DD | null si lieu permanent. Exemples dates explicites : 'jusqu'au 31 août' → {date.today().year}-08-31 ; 'du 20 juin au 5 juillet' → {date.today().year}-07-05 ; 'pour 3 semaines' → date_debut + 21j. Si date_fin absente mais expression saisonnière décrit la DURÉE : 'pour l'été'/'tout l'été'/'jusqu'à la rentrée' → {datetime.now().year}-09-22 ; 'pour l'hiver' → {datetime.now().year + 1}-03-20 ; 'pour le printemps' → {datetime.now().year}-06-21 ; 'jusqu'à l'automne' → {datetime.now().year}-12-21. N'inférer QUE si l'expression qualifie la durée. 'ambiance d'été', 'cocktails estivaux' → null.
- duree_jours  : si date_debut et date_fin sont tous deux présents, calcule la différence en jours.
    Sinon convertis les expressions textuelles :
    "1 semaine" → 7, "2 semaines" → 14, "1 mois" → 30, "2 mois" → 60.
    null si durée inconnue ou événement permanent.
- categorie    : une seule valeur parmi :
    restaurant, bar, exposition, musee, galerie, cafe, brocante, vide-grenier, popup, wellness, rooftop,
    musique, marche, cinema, spectacle, sport, atelier, boutique, loisirs
    Si aucune ne convient, réponds "autre: [ta suggestion en minuscules]" (ex: "autre: festival")

IMPORTANT : si l'article décrit un lieu permanent (restaurant, bar, café, galerie), date_fin doit être null même si une date d'ouverture est mentionnée.

Texte de l'article :
{page_text[:2000]}"""

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        # Retire les balises markdown si présentes (```json ... ```)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        data = {k: (None if v == "null" else v) for k, v in data.items()}
        if "categorie" in data:
            data["categorie"] = _normalize_categorie(data["categorie"])
        return data
    except Exception as e:
        logger.debug("Groq extract_with_llm échoué : %s", e)
        return {}


def extract_list_with_llm(page_text: str, translate_to_french: bool = False) -> list[dict]:
    """
    Variante pour les contenus multi-événements (newsletters, emails).
    Retourne une liste de dicts structurés.
    """
    client = _get_groq()
    if not client:
        return []

    translation_note = "\nIMPORTANT : le contenu est en anglais — traduis titre et description en français." if translate_to_french else ""

    prompt = f"""Tu analyses un contenu listant plusieurs lieux ou événements parisiens.
Extrait TOUS les lieux/événements mentionnés et retourne UNIQUEMENT un tableau JSON valide, sans commentaire.{translation_note}

Chaque élément du tableau doit avoir :
- titre        : nom propre du lieu ou événement
- description  : résumé en 2 phrases max
- adresse      : adresse complète avec numéro + rue + code postal
                     si disponible. Si pas d'adresse de rue mais un lieu
                     nommé est mentionné (musée, salle, parc, palais,
                     hippodrome, stade, jardin, galerie), retourner le
                     nom du lieu seul (ex: "Hippodrome de Vincennes",
                     "Palais de Tokyo", "Grande Halle de la Villette").
                     null uniquement si aucune localisation n'est
                     mentionnée.
- date_debut   : date au format YYYY-MM-DD (null si inconnue)
- duree_jours  : durée en nombre entier de jours. Convertis : "pendant 7 jours" → 7,
    "1 semaine" → 7, "2 semaines" → 14, "1 mois" → 30, "2 mois" → 60, etc.
    Si date_debut et date_fin sont toutes deux explicites, calcule la différence en jours.
    null si l'événement est permanent ou si la durée est inconnue.
- categorie    : une valeur parmi :
    restaurant, bar, exposition, musee, galerie, cafe, brocante, vide-grenier, popup, wellness, rooftop,
    musique, marche, cinema, spectacle, sport, atelier, boutique, loisirs
    Si aucune ne convient, réponds "autre: [ta suggestion en minuscules]" (ex: "autre: festival")

IMPORTANT : sois concis dans les descriptions (1 phrase max) pour permettre d'extraire tous les items sans troncature.

Contenu :
{page_text[:10000]}"""

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        items = result if isinstance(result, list) else [result]
        for item in items:
            if "categorie" in item:
                item["categorie"] = _normalize_categorie(item["categorie"])
        return items
    except Exception as e:
        logger.debug("Groq extract_list_with_llm échoué : %s", e)
        return []


def extract_venue_llm(title: str, description: str = "") -> tuple[str, str]:
    """Appelle Groq pour extraire nom du lieu + catégorie depuis un titre seul."""
    client = _get_groq()
    if not client:
        return "", ""
    prompt = (
        "Extrait le nom du lieu/établissement et sa catégorie depuis ce texte.\n"
        "Catégories possibles : restaurant, bar, exposition, musee, galerie, cafe, brocante, vide-grenier, popup, wellness, rooftop, musique, marche, cinema, spectacle, sport, atelier, boutique, loisirs, autre\n"
        "Réponds UNIQUEMENT en JSON : {\"nom\": \"...\", \"categorie\": \"...\"}\n\n"
        f"Titre: {title}\n"
        f"Description: {description[:300]}"
    )
    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)
        return data.get("nom", ""), data.get("categorie", "")
    except Exception as e:
        logger.debug("Groq extraction échouée : %s", e)
        return "", ""

VALID_CATEGORIES: frozenset[str] = frozenset({
    "restaurant", "bar", "exposition", "musee", "galerie", "cafe",
    "brocante", "vide-grenier", "popup", "wellness", "rooftop",
    "musique", "marche", "cinema", "spectacle", "sport", "atelier", "boutique",
    "loisirs",
})

VALID_CATS = VALID_CATEGORIES  # rétrocompat

_ALIASES = {
    "expo": "exposition", "musée": "musee", "galerie d'art": "galerie",
    "bien-etre": "wellness", "bienetre": "wellness", "bien être": "wellness",
    "pop-up": "popup", "pop up": "popup",
    "cinéma": "cinema",
    "marché": "marche",
}


def _normalize_categorie(cat: str) -> str:
    if not cat:
        return "autre: inconnu"
    c = cat.lower().strip()
    if c in VALID_CATEGORIES:
        return c
    if c == "autre":
        return "autre"
    if c in _ALIASES:
        return _ALIASES[c]
    if c.startswith("autre:"):
        suggestion = c.split(":", 1)[1].strip() or "inconnu"
        return f"autre: {suggestion}"
    return f"autre: {c}"

OUVERTURE_RE = re.compile(
    r"\bouvr(?:e|es|ent|ir|ira|irait|ant|ait|aient|ons|ez)\b"
    r"|\br(?:é|e)ouvr(?:e|es|ent|ir|ant|ait)\b"
    r"|\b(?:a|ont|vient de|viennent de)\s+ouvert\b"
    r"|\binaugur(?:e|es|ent|er|ation|ait|ants?)\b"
    r"|\bs['’]install(?:e|es|ent|er|ait)\b",
    re.I | re.UNICODE,
)


def matches_ouverture(href: str, text: str) -> bool:
    """Détecte une annonce d'ouverture/réouverture/inauguration/installation
    dans le slug d'URL ou le texte visible d'un article (lebonbon_healthy,
    lebonbon_loisirs). Les \\b évitent de matcher un mot qui contient la
    sous-chaîne par hasard (ex: "redécouvrir" contient "ouvrir").
    """
    slug = href.rstrip("/").split("/")[-1]
    return bool(OUVERTURE_RE.search(slug) or OUVERTURE_RE.search(text))


CAT_KEYWORDS = {
    "expo": [
        "exposition", "vernissage", "musée", "photographie", "peinture",
        "sculpture", "installation", "œuvre", "artiste", "galerie d'art",
        "art contemporain", "retrospective", "rétrospective", "commissaire",
        "collection permanente", "collection", "biennale",
    ],
    "cinema": [
        "cinéma", "film", "projection", "séance", "réalisateur", "acteur",
        "avant-première", "documentaire", "court-métrage", "long-métrage",
        "festival de cinéma", "salle obscure",
    ],
    "brocante": [
        "brocante", "vide-grenier", "marché aux puces", "puces", "antiquités",
        "antiquaire", "braderie", "foire à la", "objets anciens",
    ],
    "resto": [
        "restaurant", "brasserie", "bistrot", "gastronomie", "chef", "dîner",
        "déjeuner", "cuisine", "menu", "carte", "table", "trattoria", "izakaya",
        "ramen", "sushi", "pizzeria", "burger", "street food", "cantine",
        "bouchon", "auberge", "taverne", "festin", "repas", "gourmand",
    ],
    "cafe": [
        "café", "coffee", "brunch", "barista", "salon de thé", "tea room",
        "torréfaction", "espresso", "latte", "pâtisserie", "boulangerie",
        "viennoiserie", "tea", "thé", "chocolat chaud", "brûlerie",
    ],
    "bienetre": [
        "spa", "sauna", "yoga", "pilates", "massage", "hammam", "fitness",
        "natation", "méditation", "meditation", "salle de sport", "cours de sport",
        "stretching", "sophro", "sophrologie", "bien-être", "detox", "retraite",
        "bain froid", "cryothérapie", "piscine", "bain", "thermes",
    ],
}


def detect_category(text: str) -> str:
    low = text.lower()
    for cat, keywords in CAT_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return cat
    return "autre"


class BaseScraper(ABC):
    name: str = "base"
    base_url: str = ""

    @abstractmethod
    def scrape(self) -> list[dict]:
        """Retourne une liste de dicts conformes au schéma events."""

    def run(self, run_id: str | None = None) -> int:
        """Scrape, géocode, insère en DB. Retourne le nombre d'events insérés."""
        from datetime import datetime, timedelta
        logger.info("[%s] Début du scraping", self.name)
        if run_id:
            db.scraper_run_start(run_id, self.name)
        try:
            events = self.scrape()
        except Exception as e:
            logger.exception("[%s] scrape() a levé une exception — scraper ignoré", self.name)
            if run_id:
                db.scraper_run_end(run_id, self.name, 0, str(e))
            return 0

        inserted = 0
        for ev in events:
            ev.setdefault("lat", None)
            ev.setdefault("lng", None)
            ev["source"] = self.name
            ev.setdefault("description", None)
            ev.setdefault("date_fin", None)
            ev.setdefault("duree_jours", None)
            ev.setdefault("prix", None)
            ev.setdefault("image_url", None)
            ev.setdefault("url", None)

            # Calcul date_fin depuis duree_jours si date_fin absente
            if not ev.get("date_fin") and ev.get("date_debut") and ev.get("duree_jours"):
                try:
                    d = datetime.strptime(ev["date_debut"], "%Y-%m-%d")
                    ev["date_fin"] = (d + timedelta(days=int(ev["duree_jours"]))).strftime("%Y-%m-%d")
                except Exception:
                    pass

            # Calcul duree_jours depuis date_debut + date_fin si duree_jours absent
            if not ev.get("duree_jours") and ev.get("date_debut") and ev.get("date_fin"):
                try:
                    d1 = datetime.strptime(ev["date_debut"], "%Y-%m-%d")
                    d2 = datetime.strptime(ev["date_fin"], "%Y-%m-%d")
                    ev["duree_jours"] = (d2 - d1).days
                except Exception:
                    pass

            # Géocodage si pas de coords
            if not ev.get("lat") and ev.get("adresse"):
                lat, lng = geocoder.geocode(ev["adresse"])
                ev["lat"] = lat
                ev["lng"] = lng

            # Classification région
            if not ev.get("location_region"):
                ev["location_region"] = _classify_region(
                    ev.get("adresse"), ev.get("lat")
                )

            # Log les suggestions "autre: X" pour revue ultérieure
            cat = ev.get("categorie", "")
            if cat and cat.startswith("autre:"):
                suggestion = cat.split(":", 1)[1].strip()
                db.log_category_suggestion(suggestion)

            if db.insert_event(ev):
                inserted += 1

        logger.info("[%s] Terminé : %d/%d events insérés", self.name, inserted, len(events))
        if run_id:
            db.scraper_run_end(run_id, self.name, inserted)
        return inserted
