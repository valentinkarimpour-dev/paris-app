"""
ParisMusees Expositions scraper — expositions à venir dans les musées de la Ville de Paris
Source : https://www.parismusees.paris.fr/fr/expositions?filtre_temps=a%20venir
Scraping mensuel. Extraction structurelle, sans LLM.
Format des cards : DD / MM/YY > DD / MM/YY / MUSEE / TITRE
"""

import logging
import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from ..base import BaseScraper

logger = logging.getLogger(__name__)

BASE    = "https://www.parismusees.paris.fr"
LISTING = f"{BASE}/fr/expositions"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


def _parse_date(day: str, mm_yy: str) -> str | None:
    """'24', '02/27' → '2027-02-24'"""
    try:
        m = re.match(r"(\d{1,2})/(\d{2})", mm_yy.strip())
        if not m:
            return None
        month, year_short = int(m.group(1)), int(m.group(2))
        year = 2000 + year_short
        return f"{year}-{month:02d}-{int(day.strip()):02d}"
    except Exception:
        return None


def _parse_card(text: str) -> dict | None:
    """
    Extrait date_debut, date_fin, musee, titre depuis le texte brut d'une card.
    Format : DD\\nMM/YY\\n>\\nDD\\nMM/YY\\n[Exposition\\n][MUSEE\\n]TITRE[\\nsubtitle]
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # Les 5 premières lignes : day / mm-yy / > / day / mm-yy
    if len(lines) < 5:
        return None
    if lines[2] != ">":
        return None

    date_debut = _parse_date(lines[0], lines[1])
    date_fin   = _parse_date(lines[3], lines[4])
    if not date_debut or not date_fin:
        return None

    # Info restante : filtrer les labels parasites
    _SKIP = {"exposition", "concert", "visite", ">"}
    info = [l for l in lines[5:] if l.lower() not in _SKIP]

    if not info:
        return None

    if len(info) == 1:
        # Pas de musée mentionné
        titre, musee = info[0], None
    else:
        # Premier = musée, second = titre, le reste = sous-titre ignoré
        musee = info[0]
        titre = info[1]

    return {
        "titre":      titre,
        "musee":      musee,
        "date_debut": date_debut,
        "date_fin":   date_fin,
    }


def _scrape_page(page_num: int) -> list[dict]:
    try:
        resp = requests.get(
            LISTING,
            params={"filtre_temps": "a venir", "musee": "", "page": page_num},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception:
        logger.exception("[parismusee_expos] erreur page %d", page_num)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=lambda h: h and "/fr/exposition/" in h):
        href = a["href"]
        url = BASE + href if href.startswith("/") else href
        if url in seen:
            continue
        seen.add(url)

        card = a.find_parent(["article", "li"]) or a.find_parent("div")
        if not card:
            continue
        text = card.get_text("\n", strip=True)
        parsed = _parse_card(text)
        if parsed:
            parsed["url"] = url
            results.append(parsed)

    return results


class ParisMuseeExpos(BaseScraper):
    name = "parismusee_expos"
    base_url = BASE

    def scrape(self) -> list[dict]:
        events = []
        seen_urls: set[str] = set()

        for page_num in range(10):  # max 10 pages, s'arrête si vide
            results = _scrape_page(page_num)
            if not results:
                break
            new = [r for r in results if r["url"] not in seen_urls]
            if not new:
                break
            seen_urls.update(r["url"] for r in new)
            events.extend(new)
            logger.debug("[parismusee_expos] page %d : %d expos", page_num, len(new))
            time.sleep(0.5)

        logger.info("[parismusee_expos] %d expositions collectées", len(events))

        return [
            {
                "titre":       ev["titre"],
                "description": "",
                "adresse":     ev["musee"] or "",
                "date_debut":  ev["date_debut"],
                "date_fin":    ev["date_fin"],
                "duree_jours": None,
                "categorie":   "exposition",
                "source":      "parismusee_expos",
                "url":         ev["url"],
                "lat":         None,
                "lng":         None,
                "prix":        None,
            }
            for ev in events
        ]
