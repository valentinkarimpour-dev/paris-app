"""
LeBonbon News scraper — nouveautés parisiennes
Listing : https://www.lebonbon.fr/paris/actu/news/
Filtre les 5 premiers articles contenant "nouveau/nouvel/nouvelle/nouveauté"
puis extrait chaque article via LLM (Groq).
"""

import asyncio
import logging
import re

from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm
import geocoder

logger = logging.getLogger(__name__)

BASE        = "https://www.lebonbon.fr"
LISTING_URL = f"{BASE}/paris/actu/news/"
TOP_N       = 5

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Nouveau, nouveaux, nouvelle, nouvelles, nouvel, nouveauté(s)
_NOUVEAU_RE = re.compile(
    r"\b(nouveaux?|nouvelles?|nouvel|nouveaut[eé]s?|ouvert(e|es|ure)?|ouvrir)\b", re.I
)


def _matches_nouveau(href: str, text: str) -> bool:
    slug = href.rstrip("/").split("/")[-1]
    return bool(_NOUVEAU_RE.search(slug) or _NOUVEAU_RE.search(text))


async def _scrape_async() -> list[dict]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(user_agent=_UA, locale="fr-FR")
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        # ── Phase 1 : 5 premiers articles ──
        try:
            resp = await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=25_000)
            if not resp or resp.status >= 400:
                logger.warning("[lebonbon_news] listing HTTP %s", resp.status if resp else "?")
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
                    .slice(0, {TOP_N})
                    .map(a => ({{ href: a.href, text: a.innerText?.trim() || '' }}));
            }}""")
        except Exception:
            logger.exception("[lebonbon_news] erreur listing")
            await browser.close()
            return []

        logger.info("[lebonbon_news] %d articles récupérés", len(articles))

        # ── Filtre "nouveau" ──
        candidates = [a for a in articles if _matches_nouveau(a["href"], a["text"])]
        logger.info("[lebonbon_news] %d articles avec 'nouveau'", len(candidates))

        if not candidates:
            await browser.close()
            return []

        # ── Phase 2 : extraction LLM article par article ──
        events = []
        for art in candidates:
            art_url = art["href"]
            try:
                resp = await page.goto(art_url, wait_until="domcontentloaded", timeout=25_000)
                if not resp or resp.status >= 400:
                    continue
                await page.wait_for_timeout(1500)

                # URL après chargement (ne pas scroller pour éviter le changement d'URL)
                if page.url != art_url:
                    logger.debug("[lebonbon_news] redirect %s → %s", art_url, page.url)

                page_data = await page.evaluate("""() => ({
                    text: document.body.innerText,
                    img:  document.querySelector('meta[property="og:image"]')?.content
                })""")

                page_text = page_data.get("text", "")
                if len(page_text) < 100:
                    continue

                extracted = extract_with_llm(page_text)
                if not extracted.get("titre"):
                    logger.debug("[lebonbon_news] LLM sans résultat pour %s", art_url)
                    continue

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
                        "[lebonbon_news] skipped (pas de coords) : %s",
                        extracted.get("titre", art_url)
                    )
                    continue

                events.append({
                    "titre":       extracted.get("titre", ""),
                    "description": extracted.get("description", ""),
                    "adresse":     adresse,
                    "lat":         lat,
                    "lng":         lng,
                    "date_debut":  extracted.get("date_debut"),
                    "date_fin":    date_fin,
                    "categorie":   extracted.get("categorie", "autre"),
                    "source":      "lebonbon_news",
                    "url":         art_url,
                    "image_url":   page_data.get("img"),
                })

            except Exception:
                logger.exception("[lebonbon_news] erreur article %s", art_url)

        await browser.close()
    return events


class LeBonbonNews(BaseScraper):
    name = "lebonbon_news"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    logging.basicConfig(level=logging.DEBUG)

    scraper = LeBonbonNews()
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
