"""
ParisBouge — événements généraux (musique, spectacles, etc.)
Stratégie : liste d'articles depuis /paris/events/ → LLM par article.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm

logger = logging.getLogger(__name__)

BASE = "https://www.parisbouge.com"
_LISTING_URL = f"{BASE}/paris/events/"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


async def _scrape_async() -> list[dict]:
    all_events: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=_UA, locale="fr-FR")
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        try:
            resp = await page.goto(_LISTING_URL, wait_until="domcontentloaded", timeout=20_000)
            if not resp or resp.status >= 400:
                logger.warning("[parisbouge_autre] listing HTTP %s", resp.status if resp else "?")
                await browser.close()
                return []
            await page.wait_for_timeout(1500)
            links = await page.evaluate(
                "() => Array.from(document.querySelectorAll('[class*=\"card\"] h4 a'))"
                ".map(a => a.href).filter(h => h && h.startsWith('http'))"
            )
        except Exception:
            logger.exception("[parisbouge_autre] erreur listing")
            await browser.close()
            return []

        seen: set[str] = set()
        article_links = [l for l in links if l not in seen and not seen.add(l)]  # type: ignore[func-returns-value]
        logger.info("[parisbouge_autre] %d articles à traiter", len(article_links))

        for art_url in article_links[:40]:
            try:
                resp = await page.goto(art_url, wait_until="domcontentloaded", timeout=20_000)
                if not resp or resp.status >= 400:
                    continue
                await page.wait_for_timeout(800)
                page_data = await page.evaluate(
                    "() => ({ text: document.body.innerText,"
                    " img: document.querySelector('meta[property=\"og:image\"]')?.content })"
                )
                extracted = extract_with_llm(page_data.get("text", ""))
                if not extracted.get("titre"):
                    continue
                date_fin = None
                if extracted.get("date_debut") and extracted.get("duree_jours"):
                    try:
                        d = datetime.strptime(extracted["date_debut"], "%Y-%m-%d")
                        date_fin = (d + timedelta(days=int(extracted["duree_jours"]))).strftime("%Y-%m-%d")
                    except Exception:
                        pass
                all_events.append({
                    "titre":       extracted.get("titre", ""),
                    "description": extracted.get("description", ""),
                    "adresse":     extracted.get("adresse") or "",
                    "date_debut":  extracted.get("date_debut"),
                    "date_fin":    date_fin,
                    "duree_jours": extracted.get("duree_jours"),
                    "categorie":   extracted.get("categorie", "autre"),
                    "source":      "parisbouge_autre",
                    "url":         art_url,
                    "image_url":   page_data.get("img"),
                })
                await asyncio.sleep(1)
            except Exception:
                logger.exception("[parisbouge_autre] erreur article %s", art_url)

        await browser.close()

    logger.info("[parisbouge_autre] %d événements extraits", len(all_events))
    return all_events


class ParisBougeAutre(BaseScraper):
    name = "parisbouge_autre"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())
