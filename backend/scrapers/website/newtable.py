"""
NewTable scraper — nouveaux restaurants parisiens
Source : https://fr.newtable.com/restaurants-paris.php?order=ouverture
Filtre uniquement les restaurants ouverts dans le mois courant.
Extraction structurelle, sans LLM.
"""

import logging
import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from ..base import BaseScraper

logger = logging.getLogger(__name__)

BASE    = "https://fr.newtable.com"
LISTING = f"{BASE}/restaurants-paris.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

_MOIS_FR = {
    1: "Janvier", 2: "Février",  3: "Mars",     4: "Avril",
    5: "Mai",     6: "Juin",     7: "Juillet",  8: "Août",
    9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre",
}


def _current_month_label() -> str:
    today = date.today()
    return f"{_MOIS_FR[today.month]} {today.year}"


def _parse_address(soup: BeautifulSoup) -> str:
    """Extrait l'adresse depuis la page individuelle.
    Format attendu : "29 Rue du Dragon - 75006Paris"
    """
    for p in soup.find_all("p"):
        txt = p.get_text(" ", strip=True)
        if re.search(r"\b75\d{3}", txt) and re.search(
            r"\b(rue|avenue|boulevard|place|quai|passage|impasse|all[eé]e|square)\b", txt, re.I
        ):
            txt = re.sub(r"\s+-\s+", ", ", txt)
            txt = re.sub(r"(\d{5})\s*Paris", r"\1 Paris", txt)
            return txt.strip()
    return ""


def _scrape_listing() -> list[dict]:
    target_label = _current_month_label()
    today = date.today()
    date_debut = f"{today.year}-{today.month:02d}"

    try:
        resp = requests.get(LISTING, params={"order": "ouverture"}, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception:
        logger.exception("[newtable] erreur chargement listing")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    seen: set[str] = set()

    for col in soup.find_all("div", class_="col"):
        span = col.find("span")
        if not span:
            continue
        span_text = span.get_text(strip=True)
        if not span_text.startswith("Ouvert en :"):
            continue
        label = span_text.split(":", 1)[1].strip()
        if label != target_label:
            continue

        link_tag = col.find("a", class_="date-ouverture")
        if not link_tag:
            continue
        href = link_tag.get("href", "")
        if not href:
            continue
        url = BASE + "/" + href.lstrip("/")
        if url in seen:
            continue
        seen.add(url)

        # Nom : "Dragon (75006)" → "Dragon"
        name = ""
        title_p = col.find("p", class_="lite-title")
        if title_p:
            a = title_p.find("a")
            if a:
                name = re.sub(r"\s*\(\d{5}\)\s*$", "", a.get_text(strip=True)).strip()
        if not name:
            img = col.find("img")
            if img and img.get("alt"):
                name = re.sub(r"\s+Paris\s+\d+.*$", "", img["alt"], flags=re.I).strip()

        results.append({"name": name, "url": url, "date_debut": date_debut})

    return results


class NewTable(BaseScraper):
    name = "newtable"
    base_url = BASE

    def scrape(self) -> list[dict]:
        candidates = _scrape_listing()
        logger.info("[newtable] %d restaurants ouverts ce mois-ci", len(candidates))

        events = []
        for item in candidates:
            try:
                resp = requests.get(item["url"], headers=HEADERS, timeout=15)
                if resp.status_code >= 400:
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                adresse = _parse_address(soup)
                if not adresse:
                    logger.debug("[newtable] %s ignoré (adresse manquante)", item["name"])
                    continue

                events.append({
                    "titre":       item["name"],
                    "description": "",
                    "adresse":     adresse,
                    "date_debut":  item["date_debut"],
                    "date_fin":    None,
                    "duree_jours": None,
                    "categorie":   "restaurant",
                    "source":      "newtable",
                    "url":         item["url"],
                })
                time.sleep(0.5)
            except Exception:
                logger.exception("[newtable] erreur fiche %s", item["url"])

        return events
