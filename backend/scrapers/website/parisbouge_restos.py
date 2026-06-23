"""
ParisBouge — nouveaux restaurants à Paris.
Sections ciblées : "NOUVEAUX RESTAURANTS À PARIS" et "CES RESTAURANTS OUVRENT BIENTÔT".
Swiper CSS-mode : tous les slides sont dans le DOM, pas de navigation.
"""

import asyncio
import logging
import re
from datetime import date

from playwright.async_api import async_playwright

from ..base import BaseScraper

logger = logging.getLogger(__name__)

BASE = "https://www.parisbouge.com"
_URL = f"{BASE}/restaurants"
_UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

_JS = """() => {
    const TARGETS = ['NOUVEAUX RESTAURANTS', 'CES RESTAURANTS OUVRENT'];
    const out = [];
    document.querySelectorAll('h2').forEach(h2 => {
        const title = h2.innerText.trim();
        if (!TARGETS.some(t => title.includes(t))) return;
        const section = h2.closest('section');
        if (!section) return;
        const slides = section.querySelectorAll('.swiper-slide');
        const places = [];
        slides.forEach(slide => {
            const nameEl = slide.querySelector('a.text-title');
            if (!nameEl) return;
            const lines = (slide.innerText || '').split('\\n').map(l => l.trim())
                          .filter(l => l && !l.includes('AJOUTER'));
            places.push({ name: nameEl.innerText.trim(), href: nameEl.href, lines: lines });
        });
        if (places.length) out.push({ title: title, places: places });
    });
    return out;
}"""


def _addr_from_lines(lines: list[str], name: str) -> str:
    street, postal = "", ""
    for line in lines:
        if not line or line == name or line.isupper():
            continue
        if re.match(r"^\d", line) and re.search(
            r"Rue|Avenue|Boulevard|Place|Passage|Quai|Impasse|All.e|Square|Sq\.|Cour\b", line, re.I
        ):
            street = line
        elif re.search(r"\b75\d{3}\b", line):
            postal = line
    return ", ".join(filter(None, [street, postal]))


async def _scrape_async() -> list[dict]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=_UA, locale="fr-FR")
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()
        try:
            resp = await page.goto(_URL, wait_until="domcontentloaded", timeout=25_000)
            if not resp or resp.status >= 400:
                logger.warning("[parisbouge_restos] HTTP %s", resp.status if resp else "?")
                return []
            await page.wait_for_timeout(3000)
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 800)")
                await page.wait_for_timeout(400)
            sections = await page.evaluate(_JS)
        except Exception:
            logger.exception("[parisbouge_restos] erreur chargement")
            return []
        finally:
            await browser.close()

    events: list[dict] = []
    seen: set[str] = set()
    for sec in sections:
        for place in sec.get("places", []):
            name = place.get("name", "").strip()
            href = place.get("href", "")
            if not name or href in seen:
                continue
            seen.add(href)
            addr = _addr_from_lines(place.get("lines", []), name)
            if not re.search(r"\b75\d{3}\b", addr):
                continue
            events.append({
                "titre":       name,
                "description": "",
                "adresse":     addr,
                "date_debut":  date.today().strftime("%Y-%m-%d"),
                "date_fin":    None,
                "duree_jours": None,
                "categorie":   "restaurant",
                "source":      "parisbouge_restos",
                "url":         href or _URL,
            })

    logger.info("[parisbouge_restos] %d restaurants extraits", len(events))
    return events


class ParisBougeRestos(BaseScraper):
    name = "parisbouge_restos"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())
