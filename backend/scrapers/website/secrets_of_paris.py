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
import re
import unicodedata
from datetime import datetime, timedelta

from playwright.async_api import async_playwright

from ..base import BaseScraper, _get_groq, _normalize_categorie

logger = logging.getLogger(__name__)


def _slugify(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    s = nfkd.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

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
{page_text[:8000]}"""

    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
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


def _get_urls_to_scrape() -> list[str]:
    now = datetime.now()
    urls = []
    urls.append(f"{BASE}/paris-events-calendar/whats-on-{MONTHS_EN[now.month - 1]}-{now.year}/")
    if now.day <= 3:
        prev = now.replace(day=1) - timedelta(days=1)
        urls.append(f"{BASE}/paris-events-calendar/whats-on-{MONTHS_EN[prev.month - 1]}-{prev.year}/")
    return urls


async def _scrape_async() -> list[dict]:
    urls = _get_urls_to_scrape()
    logger.info("[secrets_of_paris] URLs à scraper : %s", urls)

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

        all_extracted: list[dict] = []
        for url in urls:
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                if not resp or resp.status >= 400:
                    logger.error("[secrets_of_paris] Page inaccessible : HTTP %s", resp.status if resp else "?")
                    continue
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
                logger.exception("[secrets_of_paris] Erreur chargement page %s", url)
                continue

            if not page_text or len(page_text) < 300:
                logger.warning("[secrets_of_paris] Contenu trop court (%d chars) : %s", len(page_text) if page_text else 0, url)
                continue

            extracted = _extract_events(page_text)
            logger.info("[secrets_of_paris] %d événements extraits depuis %s", len(extracted), url)
            for item in extracted:
                item["_source_url"] = url
            all_extracted.extend(extracted)

        await browser.close()

    # Déduplique par slug (priorité au mois courant, en premier dans la liste)
    seen_slugs: set[str] = set()
    events = []
    for extracted in all_extracted:
        if not extracted.get("titre"):
            continue
        slug = _slugify(extracted["titre"])
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        source_url = extracted.pop("_source_url")
        date_fin = None
        if extracted.get("date_debut") and extracted.get("duree_jours"):
            try:
                d = datetime.strptime(extracted["date_debut"], "%Y-%m-%d")
                date_fin = (d + timedelta(days=int(extracted["duree_jours"]))).strftime("%Y-%m-%d")
            except Exception:
                pass
        events.append({
            "titre":       extracted.get("titre", ""),
            "description": extracted.get("description", ""),
            "adresse":     extracted.get("adresse") or "",
            "date_debut":  extracted.get("date_debut"),
            "date_fin":    date_fin,
            "duree_jours": extracted.get("duree_jours"),
            "categorie":   extracted.get("categorie", "autre"),
            "source":      "secrets_of_paris",
            "url":         source_url + "#" + slug,
        })

    logger.info("[secrets_of_paris] %d événements après déduplication", len(events))
    return events


class SecretsOfParis(BaseScraper):
    name = "secrets_of_paris"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())
