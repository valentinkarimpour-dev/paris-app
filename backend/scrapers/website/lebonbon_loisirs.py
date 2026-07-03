"""
LeBonbon Loisirs scraper — ouvertures sorties/loisirs parisiens
Listing : https://www.lebonbon.fr/paris/sorties/loisirs/
Filtre sur mots d'ouverture dans le slug ou le titre de l'article.
Extraction via LLM (Groq).
"""

import asyncio
import logging
import re

from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm, VALID_CATEGORIES
import geocoder

logger = logging.getLogger(__name__)

BASE         = "https://www.lebonbon.fr"
LISTING_URL  = f"{BASE}/paris/sorties/loisirs/"
MAX_ARTICLES = 5

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_RE_OUVERTURE = re.compile(
    r'ouvr(?:e|es|ent|ir|ira|irait|ant|ait|aient|ons|ez)'
    r'|r(?:é|e)ouvr(?:e|es|ent|ir|ant|ait)'
    r'|(?:a|ont|vient de|viennent de)\s+ouvert'
    r'|inaugur(?:e|es|ent|er|ation|ait|ants?)'
    r"|s['']install(?:e|es|ent|er|ait)",
    re.I | re.UNICODE,
)



async def _scrape_async() -> list[dict]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(user_agent=_UA, locale="fr-FR")
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        # ── Phase 1 : listing ──────────────────────────────────────────────
        try:
            resp = await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=25_000)
            if not resp or resp.status >= 400:
                logger.warning("[lebonbon_loisirs] listing HTTP %s", resp.status if resp else "?")
                await browser.close()
                return []
            await page.wait_for_timeout(2500)

            articles = await page.evaluate(f"""() => {{
                const seen = new Set();
                return Array.from(document.querySelectorAll('a[class*="articleItem"]'))
                    .filter(a => {{
                        if (seen.has(a.href)) return false;
                        seen.add(a.href);
                        return true;
                    }})
                    .slice(0, {MAX_ARTICLES})
                    .map(a => ({{ href: a.href, text: a.innerText?.trim() || '' }}));
            }}""")
        except Exception:
            logger.exception("[lebonbon_loisirs] erreur listing")
            await browser.close()
            return []

        logger.info("[lebonbon_loisirs] %d articles récupérés", len(articles))

        # ── Phase 2 : extraction LLM article par article ───────────────────
        events = []
        for art in articles:
            href     = art["href"]
            art_text = art["text"]
            slug     = href.rstrip("/").split("/")[-1]

            if not _RE_OUVERTURE.search(slug) and not _RE_OUVERTURE.search(art_text):
                logger.debug("[lebonbon_loisirs] skipped (filtre ouverture) : %s", slug)
                continue

            try:
                resp = await page.goto(href, wait_until="domcontentloaded", timeout=25_000)
                if not resp or resp.status >= 400:
                    continue
                await page.wait_for_timeout(1500)

                page_data = await page.evaluate("""() => ({
                    text: document.body.innerText,
                    img:  document.querySelector('meta[property="og:image"]')?.content
                })""")

                page_text = page_data.get("text", "")
                if len(page_text) < 100:
                    continue

                extracted = extract_with_llm(page_text[:3000])
                if not extracted.get("titre"):
                    logger.debug("[lebonbon_loisirs] LLM sans résultat pour %s", href)
                    continue

                cat = extracted.get("categorie", "autre")
                if cat not in VALID_CATEGORIES and not cat.startswith("autre"):
                    cat = "autre"

                adresse = extracted.get("adresse") or ""
                lat, lng = None, None
                if adresse:
                    lat, lng = geocoder.geocode(adresse)
                if not lat and adresse:
                    lat, lng = geocoder.geocode_freetext(adresse)
                if not lat and extracted.get("titre"):
                    lat, lng = geocoder.geocode_freetext(extracted["titre"])

                if not lat:
                    logger.debug(
                        "[lebonbon_loisirs] skipped (pas de coords) : %s",
                        extracted.get("titre", href)
                    )
                    continue

                if not extracted.get("date_debut"):
                    logger.debug(
                        "[lebonbon_loisirs] skipped (pas de date_debut) : %s",
                        extracted.get("titre", href)
                    )
                    continue

                events.append({
                    "titre":       extracted.get("titre", ""),
                    "description": extracted.get("description", ""),
                    "adresse":     adresse,
                    "lat":         lat,
                    "lng":         lng,
                    "date_debut":  extracted.get("date_debut"),
                    "date_fin":    extracted.get("date_fin"),
                    "duree_jours": extracted.get("duree_jours"),
                    "categorie":   cat,
                    "source":      "lebonbon_loisirs",
                    "url":         href,
                    "image_url":   page_data.get("img"),
                })

            except Exception:
                logger.exception("[lebonbon_loisirs] erreur article %s", href)

        await browser.close()
    return events


class LeBonbonLoisirs(BaseScraper):
    name = "lebonbon_loisirs"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    logging.basicConfig(level=logging.DEBUG)

    scraper = LeBonbonLoisirs()
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
