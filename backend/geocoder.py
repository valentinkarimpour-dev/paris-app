import json
import logging
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float | None, float | None]] = {}

_HEADERS = {"User-Agent": "flaneur-app/1.0 (contact: flaneur@localhost)"}
_URL = "https://nominatim.openstreetmap.org/search"


def geocode(address: str) -> tuple[float | None, float | None]:
    if not address or not address.strip():
        return None, None

    query = address.strip()
    if "paris" not in query.lower() and "france" not in query.lower():
        query += ", Paris, France"

    if query in _cache:
        return _cache[query]

    time.sleep(1)  # Nominatim : 1 req/s max

    params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1})
    req = urllib.request.Request(f"{_URL}?{params}", headers=_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                lat = float(data[0]["lat"])
                lng = float(data[0]["lon"])
                _cache[query] = (lat, lng)
                logger.debug("Geocoded '%s' → %.4f, %.4f", address, lat, lng)
                return lat, lng
            else:
                logger.warning("Geocode : aucun résultat pour '%s'", address)
                _cache[query] = (None, None)
                return None, None
    except Exception as e:
        logger.warning("Geocode failed pour '%s' : %s", address, e)
        _cache[query] = (None, None)
        return None, None
