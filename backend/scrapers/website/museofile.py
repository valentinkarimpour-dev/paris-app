"""
Museofile scraper — liste des musées de Paris (base Museofile, Ministère de la Culture)
API : https://data.culture.gouv.fr/api/explore/v2.1/catalog/datasets/musees-de-france-base-museofile/records
Filtre : departement = Paris (75)
Scraping mensuel. Pas de LLM — extraction directe depuis l'API JSON.
"""

import logging
import time

import requests

from ..base import BaseScraper
import db

logger = logging.getLogger(__name__)

API_URL = (
    "https://data.culture.gouv.fr/api/explore/v2.1/catalog/datasets"
    "/musees-de-france-base-museofile/records"
)

PARAMS_BASE = {
    "where": 'region="Ile-de-France" AND departement="Paris"',
    "limit": 100,
    "offset": 0,
}

HEADERS = {"Accept": "application/json"}


class MuseofileScraper(BaseScraper):
    name = "museofile"
    base_url = "https://data.culture.gouv.fr"

    def scrape(self) -> list[dict]:
        records = []
        offset = 0

        while True:
            params = {**PARAMS_BASE, "offset": offset}
            try:
                resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                logger.exception("[museofile] erreur API offset=%d", offset)
                break

            batch = data.get("results", [])
            if not batch:
                break
            records.extend(batch)

            total = data.get("total_count", 0)
            offset += len(batch)
            if offset >= total:
                break
            time.sleep(0.3)

        logger.info("[museofile] %d musées récupérés", len(records))

        museums = []
        for r in records:
            nom = r.get("nom_officiel") or r.get("autnom") or ""
            if not nom:
                continue

            coords = r.get("coordonnees") or {}
            lat = coords.get("lat")
            lng = coords.get("lon")

            adresse = r.get("adresse") or ""
            cp = r.get("code_postal") or ""
            ville = r.get("ville") or ""
            location_parts = [p for p in [adresse, cp, ville] if p]
            location = ", ".join(location_parts)

            url = r.get("url") or ""
            if url and not url.startswith("http"):
                url = "https://" + url

            museums.append({
                "museum_name":     nom,
                "museum_lat":      lat,
                "museum_lng":      lng,
                "museum_location": location,
                "museum_url":      url or None,
                "source":          "museofile",
            })

        return museums

    def run(self, run_id: str | None = None) -> int:
        logger.info("[museofile] Début du scraping")
        if run_id:
            db.scraper_run_start(run_id, self.name)
        try:
            museums = self.scrape()
        except Exception as e:
            logger.exception("[museofile] scrape() a planté")
            if run_id:
                db.scraper_run_end(run_id, self.name, 0, str(e))
            return 0

        inserted = sum(1 for m in museums if db.upsert_museum(m))
        logger.info("[museofile] Terminé : %d/%d musées upsertés", inserted, len(museums))
        if run_id:
            db.scraper_run_end(run_id, self.name, inserted)
        return inserted
