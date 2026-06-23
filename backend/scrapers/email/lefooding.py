"""
Le Fooding — newsletter "adresse de la semaine"
Source : IMAP valentinainewsletters@gmail.com
"""

import logging

from bs4 import BeautifulSoup

from ..base import BaseScraper, extract_with_llm
from utils.email_reader import fetch_emails

logger = logging.getLogger(__name__)


class LeFooding(BaseScraper):
    name = "lefooding"
    base_url = "https://lefooding.com"

    def scrape(self) -> list[dict]:
        emails = fetch_emails("lefooding.com", max_count=50)
        if not emails:
            logger.warning("[lefooding] aucun email récupéré")
            return []

        events = []
        for em in emails:
            subject = em.get("subject", "").lower()
            if "adresse de la semaine" not in subject and "adresse de cette semaine" not in subject:
                continue

            html = em.get("html") or ""
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True) if html else em.get("text", "")
            if not text or "paris" not in text.lower():
                continue

            extracted = extract_with_llm(text)
            if not extracted.get("titre"):
                continue

            events.append({
                "titre":        extracted.get("titre", ""),
                "description":  extracted.get("description", ""),
                "adresse":      extracted.get("adresse") or "",
                "date_debut":   extracted.get("date_debut"),
                "duree_jours":  extracted.get("duree_jours"),
                "categorie":    extracted.get("categorie", "autre"),
                "source":       "lefooding",
                "url":          "https://lefooding.com",
            })

        logger.info("[lefooding] %d adresses extraites depuis %d emails", len(events), len(emails))
        return events
