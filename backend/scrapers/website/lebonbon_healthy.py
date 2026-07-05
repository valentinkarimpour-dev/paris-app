"""
LeBonbon Healthy scraper — ouvertures healthy/bien-être parisiens
Listing : https://www.lebonbon.fr/paris/tendances/healthy/
Filtre sur mots d'ouverture dans le slug ou le titre de l'article.
Double passe LLM : Groq custom (adresse/dates) + extract_with_llm (titre/catégorie).
"""

import asyncio
import json
import logging
from datetime import date, timedelta

from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm, VALID_CATEGORIES, _get_groq, matches_ouverture
import geocoder

logger = logging.getLogger(__name__)

BASE         = "https://www.lebonbon.fr"
LISTING_URL  = f"{BASE}/paris/tendances/healthy/"
MAX_ARTICLES = 1

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _extract_structured(text: str) -> dict:
    """Appel Groq direct pour extraire adresse et dates depuis le texte complet.
    N'hérite pas des règles saisonnières de extract_with_llm().
    """
    client = _get_groq()
    if not client:
        return {}
    prompt = (
        "Extrais uniquement ces trois champs depuis ce texte de fin "
        "d'article. Réponds UNIQUEMENT en JSON valide, rien d'autre.\n\n"
        "Champs à extraire :\n"
        "- adresse : adresse complète avec numéro + rue + code postal "
        "si présente. Sinon nom du lieu. null si absente.\n"
        "- date_debut : YYYY-MM-DD si une date d'ouverture ou de "
        "lancement est explicitement mentionnée. Utiliser 2026 par "
        "défaut si année absente. Utiliser uniquement le numéro du "
        "jour et le nom du mois — ignorer le jour de la semaine. "
        "IMPORTANT : les patterns 'Jour : HH:MM - HH:MM' et "
        "'Jour - Jour : HH:MM - HH:MM' (ex: 'Lundi - vendredi : 12:00 - 22:00', "
        "'Mardi : 8:00 - 22:00', 'Samedi - dimanche : 10:00 - 20:00') "
        "sont des horaires d'ouverture, PAS des dates — les ignorer entièrement. "
        "null si aucune date précise.\n"
        "- date_fin : YYYY-MM-DD uniquement si une date de fin est "
        "EXPLICITEMENT mentionnée sous forme de date calendaire. "
        "null dans tous les autres cas — notamment si le texte dit "
        "'cet été', 'tous les week-ends', 'saison estivale', ou "
        "mentionne un événement ponctuel sans lien avec la fermeture "
        "du lieu.\n\n"
        f"Texte :\n{text}"
    )
    try:
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        return {k: (None if v == "null" else v) for k, v in data.items()}
    except Exception as e:
        logger.debug("[lebonbon_healthy] _extract_structured erreur : %s", e)
        return {}


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
                logger.warning("[lebonbon_healthy] listing HTTP %s", resp.status if resp else "?")
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
            logger.exception("[lebonbon_healthy] erreur listing")
            await browser.close()
            return []

        logger.info("[lebonbon_healthy] %d articles récupérés", len(articles))

        # ── Phase 2 : extraction article par article ───────────────────────
        events = []
        for art in articles:
            href     = art["href"]
            art_text = art["text"]
            slug     = href.rstrip("/").split("/")[-1]

            if not matches_ouverture(href, art_text):
                logger.debug("[lebonbon_healthy] skipped (filtre ouverture) : %s", slug)
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

                # Passe 1 — texte complet → adresse + dates (prompt custom)
                result_full = _extract_structured(page_text)

                # Passe 2 — head → titre + description + catégorie
                result_head = extract_with_llm(page_text[:2000])
                if not result_head.get("titre"):
                    logger.debug("[lebonbon_healthy] LLM sans résultat pour %s", href)
                    continue

                cat = result_head.get("categorie", "autre")
                if cat not in VALID_CATEGORIES and not cat.startswith("autre"):
                    cat = "autre"

                extracted = {
                    "titre":       result_head.get("titre"),
                    "description": result_head.get("description"),
                    "categorie":   cat,
                    "adresse":     result_full.get("adresse"),
                    "date_debut":  result_full.get("date_debut"),
                    "date_fin":    result_full.get("date_fin"),
                }

                # Guard J-30 : date_debut trop ancienne → None
                cutoff = (date.today() - timedelta(days=30)).isoformat()
                if extracted.get("date_debut") and extracted["date_debut"] < cutoff:
                    extracted["date_debut"] = None

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
                        "[lebonbon_healthy] skipped (pas de coords) : %s",
                        extracted.get("titre", href)
                    )
                    continue

                if not extracted.get("date_debut"):
                    logger.debug(
                        "[lebonbon_healthy] skipped (pas de date_debut) : %s",
                        extracted.get("titre", href)
                    )
                    continue

                events.append({
                    "titre":       extracted["titre"],
                    "description": extracted.get("description", ""),
                    "adresse":     adresse,
                    "lat":         lat,
                    "lng":         lng,
                    "date_debut":  extracted["date_debut"],
                    "date_fin":    extracted.get("date_fin"),
                    "duree_jours": None,
                    "categorie":   cat,
                    "source":      "lebonbon_healthy",
                    "url":         href,
                    "image_url":   page_data.get("img"),
                })

            except Exception:
                logger.exception("[lebonbon_healthy] erreur article %s", href)

        await browser.close()
    return events


class LeBonBonHealthy(BaseScraper):
    name = "lebonbon_healthy"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    logging.basicConfig(level=logging.DEBUG)

    scraper = LeBonBonHealthy()
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
