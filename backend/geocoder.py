import json
import logging
import re
import time
import urllib.parse
import urllib.request

import requests as _requests

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float | None, float | None]] = {}

_HEADERS = {"User-Agent": "flaneur-app/1.0 (contact: flaneur@localhost)"}
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def _nominatim(adresse: str) -> tuple[float | None, float | None]:
    query = adresse.strip()
    if "paris" not in query.lower() and "france" not in query.lower():
        query += ", Paris, France"
    time.sleep(1)
    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
    req = urllib.request.Request(f"{_NOMINATIM_URL}?{params}", headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                lat, lng = float(data[0]["lat"]), float(data[0]["lon"])
                logger.debug("Nominatim '%s' → %.4f, %.4f", adresse, lat, lng)
                return lat, lng
            logger.debug("Nominatim : aucun résultat pour '%s'", adresse)
            return None, None
    except Exception as e:
        logger.warning("Nominatim failed pour '%s' : %s", adresse, e)
        return None, None


def _extract_street_address(adresse: str) -> str:
    """Extrait la partie 'numéro rue CP ville' d'une adresse avec préfixe lieu."""
    parts = [p.strip() for p in adresse.split(',')]
    for i, part in enumerate(parts):
        if re.match(r'^\d+\s+\w', part):
            return ', '.join(parts[i:])
    return adresse


def _adresse_gouv(adresse: str) -> tuple[float | None, float | None]:
    """Géocodage via api-adresse.data.gouv.fr — meilleur sur Paris."""
    try:
        resp = _requests.get(
            'https://api-adresse.data.gouv.fr/search/',
            params={'q': adresse, 'limit': 1, 'citycode': '75'},
            timeout=5,
        )
        resp.raise_for_status()
        features = resp.json().get('features', [])
        if features:
            coords = features[0]['geometry']['coordinates']
            return coords[1], coords[0]  # lat, lng
    except Exception:
        pass
    return None, None


def _nominatim_freetext(query: str) -> tuple[float | None, float | None]:
    """Nominatim en recherche texte libre — pour POI, parcs, monuments."""
    try:
        parts = [p.strip() for p in query.split(',')]
        search_query = parts[0] + ' paris'
        time.sleep(1)
        resp = _requests.get(
            _NOMINATIM_URL,
            params={
                'q': search_query,
                'format': 'json',
                'limit': 1,
                'accept-language': 'fr',
                'countrycodes': 'fr',
            },
            headers={'User-Agent': 'FlaneurBot/1.0'},
            timeout=5,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]['lat']), float(results[0]['lon'])
    except Exception:
        pass
    return None, None


def geocode(adresse: str) -> tuple[float | None, float | None]:
    if not adresse or not adresse.strip():
        return None, None

    key = adresse.strip()
    if key in _cache:
        return _cache[key]

    # Étape 1 : Nominatim avec l'adresse complète
    result = _nominatim(adresse)
    if result != (None, None):
        _cache[key] = result
        return result

    # Étape 2 : extraire la partie "numéro rue CP ville" et retenter Nominatim
    cleaned = _extract_street_address(adresse)
    if cleaned != adresse:
        result = _nominatim(cleaned)
        if result != (None, None):
            _cache[key] = result
            return result

    # Étape 3 : fallback api-adresse.data.gouv.fr
    result = _adresse_gouv(adresse)
    if result != (None, None):
        _cache[key] = result
        return result

    # Étape 4 : Nominatim texte libre (POI, parcs, monuments)
    result = _nominatim_freetext(adresse)
    _cache[key] = result
    return result
