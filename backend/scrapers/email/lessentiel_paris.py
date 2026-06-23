"""
L'Essentiel Paris — newsletter redaction@paris.lessentiel.fr
Source : IMAP valentinainewsletters@gmail.com
"""

import logging

from bs4 import BeautifulSoup

from ..base import BaseScraper, extract_list_with_llm
from utils.email_reader import fetch_emails

logger = logging.getLogger(__name__)


class LessentielParis(BaseScraper):
    name = "lessentiel_paris"
    base_url = "https://paris.lessentiel.fr"

    def scrape(self) -> list[dict]:
        emails = fetch_emails("lessentiel.fr", max_count=30)
        if not emails:
            logger.warning("[lessentiel_paris] aucun email récupéré")
            return []

        events = []
        for em in emails:
            html = em.get("html") or ""
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True) if html else em.get("text", "")
            if not text or "paris" not in text.lower():
                continue

            extracted_list = extract_list_with_llm(text)
            for extracted in extracted_list:
                if not extracted.get("titre"):
                    continue
                events.append({
                    "titre":        extracted.get("titre", ""),
                    "description":  extracted.get("description", ""),
                    "adresse":      extracted.get("adresse") or "",
                    "date_debut":   extracted.get("date_debut"),
                    "duree_jours":  extracted.get("duree_jours"),
                    "categorie":    extracted.get("categorie", "autre"),
                    "source":       "lessentiel_paris",
                    "url":          self.base_url,
                })

        logger.info("[lessentiel_paris] %d événements extraits depuis %d emails", len(events), len(emails))
        return events
