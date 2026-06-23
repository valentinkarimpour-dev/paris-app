"""
SortirAParis scraper — pop-ups, nouveautés, brocantes parisiennes
Phase 1 : collecte des URLs via Playwright (site JS + Cloudflare)
Phase 2 : extraction structurée via Groq LLM (titre, description, adresse, dates, catégorie)
"""

import asyncio
import logging

from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm

logger = logging.getLogger(__name__)

BASE = "https://www.sortiraparis.com"

LISTING_URLS = [
    f"{BASE}/loisirs/shopping-mode",
    f"{BASE}/loisirs/bons-plans",
]


async def _scrape_async() -> list[dict]:
    events = []
    seen: set[str] = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
        )
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        # ── Phase 1 : collecte des URLs ──
        article_links: list[str] = []
        for url in LISTING_URLS:
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                if not resp or resp.status >= 400:
                    logger.warning("[sortiraparis] listing %s → %s", url, resp.status if resp else "?")
                    continue
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 1200)")
                    await page.wait_for_timeout(600)

                links = await page.evaluate("""() =>
                    Array.from(document.querySelectorAll('div.slides .title a'))
                        .map(a => a.href)
                        .filter(h => h && h.startsWith('http'))
                """)
                new_links = [l for l in links if l not in seen]
                seen.update(new_links)
                article_links.extend(new_links)
                logger.debug("[sortiraparis] %s : %d articles", url, len(new_links))
                await asyncio.sleep(2)

            except Exception:
                logger.exception("[sortiraparis] erreur listing %s", url)

        logger.info("[sortiraparis] %d articles à traiter", len(article_links))

        # ── Phase 2 : extraction LLM ──
        for art_url in article_links[:40]:
            try:
                resp = await page.goto(art_url, wait_until="domcontentloaded", timeout=25_000)
                if not resp or resp.status >= 400:
                    continue
                await page.wait_for_timeout(800)

                # Texte brut de la page + image og
                page_data = await page.evaluate("""() => ({
                    text: document.body.innerText,
                    img:  document.querySelector('meta[property="og:image"]')?.content
                })""")

                page_text = page_data.get("text", "")
                if len(page_text) < 100:
                    continue

                extracted = extract_with_llm(page_text)
                if not extracted.get("titre"):
                    logger.debug("[sortiraparis] LLM sans résultat pour %s", art_url)
                    continue

                # duree_jours → date_fin
                date_fin = None
                if extracted.get("date_debut") and extracted.get("duree_jours"):
                    try:
                        from datetime import datetime, timedelta
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
                    "categorie":   extracted.get("categorie", "autre"),
                    "prix":        None,
                    "source":      "sortiraparis",
                    "url":         art_url,
                    "image_url":   page_data.get("img"),
                })

                await asyncio.sleep(1)

            except Exception:
                logger.exception("[sortiraparis] erreur article %s", art_url)

        await browser.close()

    return events


class SortirAParis(BaseScraper):
    name = "sortiraparis"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())
