"""
NouveauxRestos scraper — nouveaux restaurants à Paris
Source : SortirAParis rubrique restaurant
Phase 1 : collecte des URLs récentes (Playwright)
Phase 2 : extraction via Groq LLM
"""

import asyncio
import logging

from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm

logger = logging.getLogger(__name__)

LISTING_URL  = "https://www.sortiraparis.com/hotel-restaurant/restaurant"
MAX_ARTICLES = 30
RECENT_KEYWORDS = {"nouveau", "ouverture", "ouvre", "opening", "inauguration", "arrive"}


def _is_recent_url(url: str) -> bool:
    slug = url.split("/")[-1].lower()
    return any(kw in slug for kw in RECENT_KEYWORDS)


async def _scrape_async() -> list[dict]:
    events = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        # ── Phase 1 : collecte des URLs ──
        try:
            resp = await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=25_000)
            if not resp or resp.status >= 400:
                logger.warning("[nouveaux_restos] listing inaccessible")
                await browser.close()
                return []
        except Exception:
            logger.exception("[nouveaux_restos] impossible de charger le listing")
            await browser.close()
            return []

        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 1500)")
            await page.wait_for_timeout(600)

        all_links: list[str] = await page.evaluate("""() => {
            const seen = new Set();
            return Array.from(document.querySelectorAll('a[href*="/restaurant/articles/"]'))
                .map(a => a.href)
                .filter(h => { if (seen.has(h)) return false; seen.add(h); return true; });
        }""")

        article_links = [l for l in all_links if _is_recent_url(l)][:MAX_ARTICLES]
        logger.info("[nouveaux_restos] %d articles récents à traiter", len(article_links))

        # ── Phase 2 : extraction LLM ──
        for url in article_links:
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                if not resp or resp.status >= 400:
                    continue
                await page.wait_for_timeout(1000)

                page_data = await page.evaluate("""() => ({
                    text: document.body.innerText,
                    img:  document.querySelector('meta[property="og:image"]')?.content
                })""")

                extracted = extract_with_llm(page_data.get("text", ""))
                if not extracted.get("titre"):
                    continue

                events.append({
                    "titre":       extracted.get("titre", ""),
                    "description": extracted.get("description", ""),
                    "adresse":     extracted.get("adresse") or "",
                    "date_debut":  extracted.get("date_debut"),
                    "categorie":   "resto",
                    "source":      "sortiraparis",
                    "url":         url,
                    "image_url":   page_data.get("img"),
                })
                await asyncio.sleep(2)
            except Exception:
                logger.exception("[nouveaux_restos] erreur %s", url)

        await browser.close()
    return events


class NouveauxRestos(BaseScraper):
    name = "nouveaux_restos"
    base_url = LISTING_URL

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())
