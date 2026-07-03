"""
LeBonbon Food scraper — nouveautés food & drink parisiennes
Listing : https://www.lebonbon.fr/paris/food-et-drink/actu/
Vérifie uniquement le premier article (le plus récent).
Matche sur mots-clés ou sur le mois courant en français.
Extraction via LLM (Groq).
"""

import asyncio
import logging
import re
from datetime import date

from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm
import geocoder

logger = logging.getLogger(__name__)

BASE        = "https://www.lebonbon.fr"
LISTING_URL = f"{BASE}/paris/food-et-drink/actu/"

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
# Variantes accentuées pour matcher dans les titres
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
        r"|" + mois_pattern +
        r")\b",
        re.I,
    )


def _matches(href: str, text: str, pattern: re.Pattern) -> bool:
    slug = href.rstrip("/").split("/")[-1]
    return bool(pattern.search(slug) or pattern.search(text))


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
                logger.warning("[lebonbon_food] listing HTTP %s", resp.status if resp else "?")
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
            logger.exception("[lebonbon_food] erreur listing")
            await browser.close()
            return []

        if not articles:
            logger.info("[lebonbon_food] aucun article trouvé")
            await browser.close()
            return []

        art = articles[0]
        logger.info("[lebonbon_food] premier article : %s", art["href"].rstrip("/").split("/")[-1])

        if not _matches(art["href"], art["text"], pattern):
            logger.info("[lebonbon_food] pas de mot-clé match — rien à insérer")
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
                extracted = extract_with_llm(page_text)
                if extracted.get("titre"):
                    from datetime import datetime, timedelta
                    date_fin = None
                    if extracted.get("date_debut") and extracted.get("duree_jours"):
                        try:
                            d = datetime.strptime(extracted["date_debut"], "%Y-%m-%d")
                            date_fin = (d + timedelta(days=int(extracted["duree_jours"]))).strftime("%Y-%m-%d")
                        except Exception:
                            pass

                    adresse = extracted.get("adresse") or ""
                    lat, lng = None, None
                    if adresse:
                        lat, lng = geocoder.geocode(adresse)
                    if not lat:
                        logger.debug(
                            "[lebonbon_food] skipped (pas de coords) : %s",
                            extracted.get("titre", art["href"])
                        )
                    else:
                        events.append({
                            "titre":       extracted.get("titre", ""),
                            "description": extracted.get("description", ""),
                            "adresse":     adresse,
                            "lat":         lat,
                            "lng":         lng,
                            "date_debut":  extracted.get("date_debut"),
                            "date_fin":    date_fin,
                            "categorie":   extracted.get("categorie", "autre"),
                            "source":      "lebonbon_food",
                            "url":         art["href"],
                            "image_url":   page_data.get("img"),
                        })
                else:
                    logger.debug("[lebonbon_food] LLM sans résultat pour %s", art["href"])

        except Exception:
            logger.exception("[lebonbon_food] erreur article %s", art["href"])

        await browser.close()
    return events


class LeBonbonFood(BaseScraper):
    name = "lebonbon_food"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    logging.basicConfig(level=logging.DEBUG)

    scraper = LeBonbonFood()
    events = scraper.scrape()

    print(f"\n{'═'*60}")
    print(f"RÉSULTAT : {len(events)} events extraits")
    print(f"{'═'*60}")
    for ev in events:
        print(f"\n  titre      : {ev['titre']}")
        print(f"  date_debut : {ev['date_debut']}")
        print(f"  date_fin   : {ev['date_fin']}")
        print(f"  adresse    : {ev['adresse']}")
        print(f"  lat/lng    : {ev.get('lat')}, {ev.get('lng')}")
        print(f"  categorie  : {ev['categorie']}")
        print(f"  url        : {ev['url']}")
