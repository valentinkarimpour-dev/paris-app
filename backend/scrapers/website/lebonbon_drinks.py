"""
LeBonbon Drinks scraper — nouveautés bars, cafés, rooftops parisiens
Listing : https://www.lebonbon.fr/paris/food-et-drink/drink/
Vérifie uniquement le premier article (le plus récent).
Matche sur mots-clés ou sur le mois courant en français.
Extraction via LLM (Groq).
"""

import asyncio
import logging
import re
from datetime import date, datetime, timedelta

from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm

logger = logging.getLogger(__name__)

BASE        = "https://www.lebonbon.fr"
LISTING_URL = f"{BASE}/paris/food-et-drink/drink/"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MOIS_FR = {
    1: "janvier", 2: "fevrier", 3: "mars", 4: "avril",
    5: "mai", 6: "juin", 7: "juillet", 8: "aout",
    9: "septembre", 10: "octobre", 11: "novembre", 12: "decembre",
}
_MOIS_ACCENTS = {
    "fevrier": "f[eé]vrier",
    "aout":    "ao[uû]t",
}


def _build_regex() -> re.Pattern:
    mois = _MOIS_FR[date.today().month]
    mois_pattern = _MOIS_ACCENTS.get(mois, mois)
    return re.compile(
        r"\b("
        r"nouveaux?|nouvelles?|nouvel|nouveaut[eé]s?"
        r"|ouvre(?:nt)?|ouvert(?:e|es|ure)?"
        r"|ouvrir"
        r"|d[eé]barque(?:nt)?"
        r"|inaugure(?:nt)?"
        r"|install[eé]e?s?"
        r"|rouvre(?:nt)?|r[eé]ouvert(?:e|es|ure)?"
        r"|" + mois_pattern +
        r")\b",
        re.I,
    )


def _matches(href: str, text: str, pattern: re.Pattern) -> bool:
    slug = href.rstrip("/").split("/")[-1]
    return bool(pattern.search(slug) or pattern.search(text))


_PRIORITY_CATS = {"rooftop", "bar", "cafe"}

_CAT_HINTS = [
    (re.compile(r"rooftop|terrasse|toit\b", re.I), "rooftop"),
    (re.compile(r"\bbar\b|cocktail|speakeasy", re.I),  "bar"),
    (re.compile(r"\bcaf[eé]\b|coffee|brunch", re.I),   "cafe"),
]


def _resolve_categorie(llm_cat: str, href: str, title: str) -> str:
    slug = href.rstrip("/").split("/")[-1]
    for pattern, cat in _CAT_HINTS:
        if pattern.search(slug) or pattern.search(title):
            return cat
    if llm_cat in _PRIORITY_CATS:
        return llm_cat
    return "bar"


async def _scrape_async() -> list[dict]:
    pattern = _build_regex()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(user_agent=_UA, locale="fr-FR")
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        # ── Phase 1 : premier article uniquement ──
        try:
            resp = await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=25_000)
            if not resp or resp.status >= 400:
                logger.warning("[lebonbon_drinks] listing HTTP %s", resp.status if resp else "?")
                await browser.close()
                return []
            await page.wait_for_timeout(2500)

            articles = await page.evaluate("""() => {
                const seen = new Set();
                return Array.from(document.querySelectorAll('a[class*="articleItem"]'))
                    .filter(a => { if (seen.has(a.href)) return false; seen.add(a.href); return true; })
                    .slice(0, 1)
                    .map(a => ({ href: a.href, text: a.innerText?.trim() || '' }));
            }""")
        except Exception:
            logger.exception("[lebonbon_drinks] erreur listing")
            await browser.close()
            return []

        if not articles:
            logger.info("[lebonbon_drinks] aucun article trouvé")
            await browser.close()
            return []

        art = articles[0]
        logger.info("[lebonbon_drinks] premier article : %s", art["href"].rstrip("/").split("/")[-1])

        if not _matches(art["href"], art["text"], pattern):
            logger.info("[lebonbon_drinks] pas de mot-clé match — rien à insérer")
            await browser.close()
            return []

        # ── Phase 2 : extraction LLM ──
        events = []
        try:
            resp = await page.goto(art["href"], wait_until="domcontentloaded", timeout=25_000)
            if not resp or resp.status >= 400:
                await browser.close()
                return []
            await page.wait_for_timeout(1500)

            page_data = await page.evaluate("""() => ({
                text: document.body.innerText,
                img:  document.querySelector('meta[property="og:image"]')?.content
            })""")

            page_text = page_data.get("text", "")
            if len(page_text) >= 100:
                _prefix = (
                    "[RÈGLE DATES SAISONNIÈRES : si l'article mentionne "
                    "'terrasse estivale', 'saison 2026', 'tout l'été', "
                    "'pour l'été', 'cet été' → inférer "
                    "date_debut=YYYY-06-01 et date_fin=YYYY-09-22 "
                    "avec l'année mentionnée ou l'année courante. "
                    "Ne pas laisser date_fin null dans ces cas.]\n\n"
                )
                extracted = extract_with_llm(_prefix + page_text[:3000])
                if extracted.get("titre"):
                    date_fin = None
                    if extracted.get("date_debut") and extracted.get("duree_jours"):
                        try:
                            d = datetime.strptime(extracted["date_debut"], "%Y-%m-%d")
                            date_fin = (d + timedelta(days=int(extracted["duree_jours"]))).strftime("%Y-%m-%d")
                        except Exception:
                            pass

                    titre = extracted.get("titre", "")
                    categorie = _resolve_categorie(
                        extracted.get("categorie", "autre"),
                        art["href"],
                        titre,
                    )
                    events.append({
                        "titre":       titre,
                        "description": extracted.get("description", ""),
                        "adresse":     extracted.get("adresse") or "",
                        "date_debut":  extracted.get("date_debut"),
                        "date_fin":    date_fin,
                        "categorie":   categorie,
                        "source":      "lebonbon_drinks",
                        "url":         art["href"],
                        "image_url":   page_data.get("img"),
                    })
                else:
                    logger.debug("[lebonbon_drinks] LLM sans résultat pour %s", art["href"])

        except Exception:
            logger.exception("[lebonbon_drinks] erreur article %s", art["href"])

        await browser.close()
    return events


class LeBonbonDrinks(BaseScraper):
    name = "lebonbon_drinks"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())
