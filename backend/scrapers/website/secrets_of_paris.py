"""
Secrets of Paris — calendrier mensuel des événements
URL : https://secretsofparis.com/paris-events-calendar/whats-on-{month}-{year}/
- Page en anglais → LLM traduit en français
- Playwright requis (rate-limit sur requests)
- À lancer le 1er de chaque mois (via n8n cron séparé)
"""

import asyncio
import json
import logging
from datetime import datetime

from playwright.async_api import async_playwright

from ..base import BaseScraper, _get_groq, _normalize_categorie

logger = logging.getLogger(__name__)

MONTHS_EN = [
    "january","february","march","april","may","june",
    "july","august","september","october","november","december",
]

BASE = "https://secretsofparis.com"


def _extract_events(page_text: str) -> list[dict]:
    """
    Variante locale d'extract_list_with_llm pour Secrets of Paris.
    Règle spécifique : ignorer les événements dont la date ne contient que "through X"
    sans date de début explicite (ex: "through May 10" → ignoré).
    Cas "May 11 through July 13" → date_debut=2026-05-11, date_fin=2026-07-13.
    """
    client = _get_groq()
    if not client:
        return []

    year = datetime.now().year
    prompt = f"""Tu analyses un calendrier d'événements parisiens en anglais.
Extrait TOUS les événements mentionnés et retourne UNIQUEMENT un tableau JSON valide, sans commentaire.
Traduis titre et description en français.

Règles importantes :
- Si la date d'un événement ne contient qu'une date de fin ("through May X", "until May X", "jusqu'au X") sans date de début explicite → IGNORE cet événement, ne l'inclus pas.
- Si la date contient une plage explicite ("May 8–17", "May 8-17", "May 11 through July 13") → date_debut = premier jour, date_fin = dernier jour.
- L'année est {year} sauf indication contraire.

Chaque élément du tableau :
- titre        : nom de l'événement traduit en français
- description  : résumé en 2 phrases max, traduit en français
- adresse      : adresse complète avec rue + code postal parisien (null si absente)
- date_debut   : format YYYY-MM-DD (obligatoire — si inconnue ou uniquement "through X", ignore l'événement)
- duree_jours  : durée en jours entiers (calculée depuis date_debut et date_fin si les deux sont présentes), null si inconnue
- categorie    : une valeur parmi : restaurant, bar, exposition, musee, galerie, cafe, brocante, vide-grenier, popup, wellness, rooftop, musique, marche, cinema, spectacle, sport, atelier, boutique

Contenu :
{page_text[:4000]}"""

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        items = json.loads(raw.strip())
        if not isinstance(items, list):
            items = [items]
        for item in items:
            if "categorie" in item:
                item["categorie"] = _normalize_categorie(item["categorie"])
        # Filtre défensif : exclure tout événement sans date_debut
        return [i for i in items if i.get("date_debut")]
    except Exception as e:
        logger.debug("[secrets_of_paris] LLM échoué : %s", e)
        return []


def _current_month_url() -> str:
    now = datetime.now()
    month = MONTHS_EN[now.month - 1]
    return f"{BASE}/paris-events-calendar/whats-on-{month}-{now.year}/"


async def _scrape_async() -> list[dict]:
    url = _current_month_url()
    logger.info("[secrets_of_paris] URL du mois : %s", url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
        )
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if not resp or resp.status >= 400:
                logger.error("[secrets_of_paris] Page inaccessible : HTTP %s", resp.status if resp else "?")
                await browser.close()
                return []
            await page.wait_for_timeout(2000)

            # Scroll pour charger le contenu lazy-loaded
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 1500)")
                await page.wait_for_timeout(500)

            page_text = await page.evaluate("""() => {
                const el = document.querySelector('article, .entry-content, main, body');
                return el ? el.innerText : document.body.innerText;
            }""")

        except Exception:
            logger.exception("[secrets_of_paris] Erreur chargement page")
            await browser.close()
            return []

        await browser.close()

    if not page_text or len(page_text) < 300:
        logger.warning("[secrets_of_paris] Contenu trop court (%d chars)", len(page_text))
        return []

    extracted_list = _extract_events(page_text)

    events = []
    for extracted in extracted_list:
        if not extracted.get("titre"):
            continue
        events.append({
            "titre":       extracted.get("titre", ""),
            "description": extracted.get("description", ""),
            "adresse":     extracted.get("adresse") or "",
            "date_debut":  extracted.get("date_debut"),
            "duree_jours": extracted.get("duree_jours"),
            "categorie":   extracted.get("categorie", "autre"),
            "source":      "secrets_of_paris",
            "url":         url,
        })

    logger.info("[secrets_of_paris] %d événements extraits", len(events))
    return events


class SecretsOfParis(BaseScraper):
    name = "secrets_of_paris"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())
