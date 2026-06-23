"""
Seed script — Liste des musées de Paris (Wikipedia)
Popule la table `museums` avec nom + adresse complète.

Pour les musées sans adresse explicite (seulement arrondissement),
une recherche Nominatim est effectuée via le nom du musée.

Usage :
    python scripts/seed_museums_wikipedia.py
"""

import logging
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

WIKI_URL    = "https://fr.wikipedia.org/wiki/Liste_des_mus%C3%A9es_de_Paris"
NOMINATIM   = "https://nominatim.openstreetmap.org/search"
HEADERS     = {"User-Agent": "FlaneurApp/1.0 (seed_museums; contact: valentin_karimpour@live.fr)"}
ARR_RE      = re.compile(r"\b(\d{1,2})[eè]r?e?\b", re.I)
ADDR_RE     = re.compile(r"\d+\s*,?\s*(?:rue|avenue|boulevard|place|quai|allée|impasse|passage|square)\b", re.I)


def _fetch_wikipedia() -> list[dict]:
    logger.info("Téléchargement de la page Wikipedia…")
    resp = requests.get(WIKI_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    museums = []
    seen = set()

    for table in soup.find_all("table", class_="wikitable"):
        headers_row = table.find("tr")
        if not headers_row:
            continue
        col_names = [th.get_text(" ", strip=True).lower() for th in headers_row.find_all(["th", "td"])]

        # Repère les colonnes nom / adresse / arrondissement
        idx_nom  = next((i for i, h in enumerate(col_names) if "nom" in h or "musée" in h), 0)
        idx_addr = next((i for i, h in enumerate(col_names) if "adresse" in h), None)
        idx_arr  = next((i for i, h in enumerate(col_names) if "arrond" in h or "arr." in h), None)

        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= idx_nom:
                continue

            nom = cells[idx_nom].get_text(" ", strip=True)
            nom = re.sub(r"\[.*?\]", "", nom).strip()  # retire les notes [1]
            if not nom or nom.lower() in seen:
                continue
            seen.add(nom.lower())

            adresse = ""
            arrondissement = ""

            if idx_addr is not None and len(cells) > idx_addr:
                adresse = cells[idx_addr].get_text(" ", strip=True)
                adresse = re.sub(r"\[.*?\]", "", adresse).strip()

            if idx_arr is not None and len(cells) > idx_arr:
                arrondissement = cells[idx_arr].get_text(" ", strip=True)
                arrondissement = re.sub(r"\[.*?\]", "", arrondissement).strip()

            museums.append({"nom": nom, "adresse": adresse, "arrondissement": arrondissement})

    # Fallback : listes à puces si aucune table exploitable
    if not museums:
        for li in soup.select("div.mw-parser-output li"):
            a = li.find("a")
            if not a:
                continue
            nom = a.get_text(strip=True)
            if len(nom) < 5 or nom.lower() in seen:
                continue
            seen.add(nom.lower())
            museums.append({"nom": nom, "adresse": "", "arrondissement": ""})

    logger.info("%d musées extraits de Wikipedia", len(museums))
    return museums


def _nominatim_lookup(nom: str) -> tuple[str, float | None, float | None]:
    """Cherche un musée par nom sur Nominatim. Retourne (adresse, lat, lng)."""
    try:
        resp = requests.get(
            NOMINATIM,
            params={"q": f"{nom}, Paris", "format": "json", "limit": 1, "addressdetails": 1},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            r = results[0]
            addr_parts = r.get("address", {})
            # Reconstruit une adresse lisible
            numero = addr_parts.get("house_number", "")
            rue    = addr_parts.get("road", "")
            cp     = addr_parts.get("postcode", "")
            ville  = addr_parts.get("city") or addr_parts.get("town", "Paris")
            adresse = f"{numero} {rue}, {cp} {ville}".strip(" ,")
            return adresse, float(r["lat"]), float(r["lon"])
    except Exception as e:
        logger.debug("Nominatim échec pour '%s' : %s", nom, e)
    return "", None, None


def _needs_lookup(adresse: str) -> bool:
    """True si l'adresse ne contient pas de numéro de rue."""
    return not ADDR_RE.search(adresse)


def seed():
    db.init_db()
    museums = _fetch_wikipedia()

    inserted = updated = skipped = 0
    now = datetime.now().isoformat(timespec="seconds")

    with sqlite3.connect(db.DB_PATH) as conn:
        for m in museums:
            nom    = m["nom"]
            adresse = m["adresse"]
            arr    = m["arrondissement"]
            lat = lng = None

            if _needs_lookup(adresse):
                logger.info("Nominatim lookup : %s", nom)
                adresse_found, lat, lng = _nominatim_lookup(nom)
                if adresse_found:
                    adresse = adresse_found
                    logger.info("  → %s", adresse)
                else:
                    logger.warning("  → adresse introuvable, conserve arrondissement : %s", arr)
                time.sleep(1.1)  # Respect de la politique Nominatim (1 req/s)

            try:
                cur = conn.execute("""
                    INSERT INTO museums (nom, adresse, arrondissement, lat, lng, source, scraped_at)
                    VALUES (?, ?, ?, ?, ?, 'wikipedia', ?)
                    ON CONFLICT(nom) DO UPDATE SET
                        adresse        = excluded.adresse,
                        arrondissement = excluded.arrondissement,
                        lat            = excluded.lat,
                        lng            = excluded.lng,
                        scraped_at     = excluded.scraped_at
                """, (nom, adresse, arr, lat, lng, now))
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                logger.warning("Insert échoué pour '%s' : %s", nom, e)
                skipped += 1

        conn.commit()

    logger.info("Seed terminé : %d insérés, %d mis à jour, %d ignorés", inserted, updated, skipped)

    # Aperçu
    with sqlite3.connect(db.DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM museums").fetchone()[0]
        with_addr = conn.execute("SELECT COUNT(*) FROM museums WHERE adresse != ''").fetchone()[0]
        with_coords = conn.execute("SELECT COUNT(*) FROM museums WHERE lat IS NOT NULL").fetchone()[0]
    logger.info("Table museums : %d total | %d avec adresse | %d avec coords", total, with_addr, with_coords)


if __name__ == "__main__":
    seed()
