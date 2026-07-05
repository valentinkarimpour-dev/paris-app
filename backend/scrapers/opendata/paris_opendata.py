"""
Paris Open Data — que-faire-a-paris
API REST officielle, données en français, coords incluses.
Pas de LLM nécessaire : les champs sont déjà structurés.
"""

import logging
from datetime import datetime, timedelta
from html import unescape
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from ..base import BaseScraper, _normalize_categorie

logger = logging.getLogger(__name__)

_PARIS = ZoneInfo("Europe/Paris")

API_URL = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/que-faire-a-paris-/records"
MAX_RECORDS = 200

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FlaneurBot/1.0)",
    "Accept": "application/json",
}

# Mapping tags QFAP → nos catégories
_TAG_MAP = {
    "expo": "exposition", "exposition": "exposition", "art contemporain": "exposition",
    "photo": "exposition", "photographie": "exposition",
    "musée": "musee", "musee": "musee",
    "galerie": "galerie",
    "concert": "musique", "musique": "musique", "jazz": "musique",
    "spectacle": "spectacle", "théâtre": "spectacle", "theatre": "spectacle",
    "danse": "spectacle", "cirque": "spectacle", "humour": "spectacle",
    "cinéma": "cinema", "cinema": "cinema", "film": "cinema",
    "atelier": "atelier", "stage": "atelier",
    "marché": "marche", "marche": "marche", "brocante": "brocante",
    "vide-grenier": "vide-grenier", "vide grenier": "vide-grenier",
    "restaurant": "restaurant", "gastronomie": "restaurant",
    "café": "cafe", "cafe": "cafe",
    "bien-être": "wellness", "bien être": "wellness", "yoga": "wellness",
    "sport": "sport", "running": "sport",
    "pop-up": "popup", "popup": "popup",
    "boutique": "boutique",
}


def _map_tags(tags_str: str | None) -> str:
    if not tags_str:
        return "autre"
    tags = [t.strip().lower() for t in tags_str.split(";")]
    for tag in tags:
        if tag in _TAG_MAP:
            return _TAG_MAP[tag]
        for key in _TAG_MAP:
            if key in tag:
                return _TAG_MAP[key]
    return _normalize_categorie(tags[0]) if tags else "autre"


def _parse_paris_date(dt_str: str | None) -> str | None:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            result = dt.date()
        else:
            dt_paris = dt.astimezone(_PARIS)
            # L'API Que Faire à Paris borne ses journées à 2h du matin, pas
            # minuit (une journée va de 02:00:00 à 01:59:59 le lendemain).
            # Sans ce recalage, un évènement commençant à 00h30 se retrouve
            # daté du mauvais jour — et pire, une date_fin peut tomber avant
            # sa date_debut si seule l'une des deux est recalée.
            if dt_paris.hour < 2:
                dt_paris = dt_paris - timedelta(days=1)
            result = dt_paris.date()
        return result.isoformat()
    except (ValueError, TypeError):
        return dt_str[:10]


def _strip_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return unescape(soup.get_text(" ", strip=True))


def _fetch_page(offset: int, limit: int = 100) -> list[dict]:
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")
    params = {
        "limit":    limit,
        "offset":   offset,
        "where":    f"date_start>='{now_iso}'",
        "order_by": "date_start",
        "timezone": "Europe/Paris",
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json().get("results", [])


class ParisOpenData(BaseScraper):
    name = "paris_opendata"
    base_url = "https://opendata.paris.fr"

    def scrape(self) -> list[dict]:
        events = []
        seen_ids: set[str] = set()
        offset = 0

        while offset < MAX_RECORDS:
            try:
                records = _fetch_page(offset)
            except Exception:
                logger.exception("[paris_opendata] Erreur API offset=%d", offset)
                break
            if not records:
                break

            for rec in records:
                ev_id = str(rec.get("id") or rec.get("event_id") or "")
                if ev_id in seen_ids:
                    continue
                seen_ids.add(ev_id)

                # Adresse
                parts = filter(None, [
                    rec.get("address_name"),
                    rec.get("address_street"),
                    rec.get("address_zipcode"),
                    rec.get("address_city"),
                ])
                adresse = ", ".join(parts)

                # Coords
                lat_lon = rec.get("lat_lon") or {}
                lat = lat_lon.get("lat")
                lng = lat_lon.get("lon")

                if not adresse or lat is None or lng is None:
                    logger.debug(
                        "[paris_opendata] ignoré (données incomplètes) : %s",
                        rec.get("title") or ev_id,
                    )
                    continue

                # Dates
                date_start = rec.get("date_start", "")
                date_end   = rec.get("date_end", "")
                date_debut = _parse_paris_date(date_start)
                date_fin   = _parse_paris_date(date_end)

                duree_jours = None
                if date_debut and date_fin:
                    try:
                        d1 = datetime.strptime(date_debut, "%Y-%m-%d")
                        d2 = datetime.strptime(date_fin,   "%Y-%m-%d")
                        duree_jours = (d2 - d1).days
                    except Exception:
                        pass

                # Description : lead_text prioritaire, sinon description HTML strippé
                lead = rec.get("lead_text") or ""
                desc_html = rec.get("description") or ""
                description = lead if lead else _strip_html(desc_html)[:400]

                # Catégorie depuis tags
                categorie = _map_tags(rec.get("qfap_tags"))

                # Prix
                prix = rec.get("price_detail") or rec.get("price_type")

                events.append({
                    "titre":       rec.get("title") or rec.get("title_event") or "",
                    "description": description,
                    "adresse":     adresse,
                    "lat":         lat,
                    "lng":         lng,
                    "date_debut":  date_debut,
                    "date_fin":    date_fin,
                    "duree_jours": duree_jours,
                    "categorie":   categorie,
                    "prix":        prix,
                    "source":      "paris_opendata",
                    "url":         rec.get("url") or "",
                    "image_url":   rec.get("cover_url") or rec.get("image_couverture"),
                })

            offset += len(records)
            if len(records) < 100:
                break

        logger.info("[paris_opendata] %d événements récupérés", len(events))
        return events
