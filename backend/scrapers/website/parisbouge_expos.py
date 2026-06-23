"""
ParisBouge — expositions à Paris.
Sections ciblées (mois-agnostiques) :
  - "DÉBUTENT EN"           → expos qui débutent ce mois-ci
  - "PROCHAINES EXPOSITIONS" → expos à venir

Structure : swiper dans section.mt-8, même DOM que restaurants.
Adresse = nom du lieu (musée/galerie), pas d'adresse de rue.
Dates extraites par regex depuis la ligne de texte du slide (pas de LLM).
"""

import asyncio
import logging
import re
from datetime import date, datetime

from playwright.async_api import async_playwright

from ..base import BaseScraper

logger = logging.getLogger(__name__)

BASE = "https://www.parisbouge.com"
_URL = f"{BASE}/paris/events/category/exposition"
_UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

_SECTION_TARGETS = ["DÉBUTENT EN", "PROCHAINES EXPOSITIONS"]

_JS = """() => {
    const TARGETS = ['DÉBUTENT EN', 'PROCHAINES EXPOSITIONS'];
    const out = [];
    document.querySelectorAll('h2').forEach(h2 => {
        const title = h2.innerText.trim().toUpperCase();
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
        if (places.length) out.push({ title: h2.innerText.trim(), places: places });
    });
    return out;
}"""

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# Jours de semaine optionnels avant le numéro de jour
_OPT_JOUR = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
_OJ = f"(?:{_OPT_JOUR})?"


def _parse_date(j: str, mois_str: str, an: str | None) -> str | None:
    mo = MOIS.get(mois_str.lower())
    if not mo:
        return None
    y = int(an) if an and str(an).isdigit() else date.today().year
    try:
        return datetime(y, mo, int(j)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_date_line(text: str) -> tuple[str | None, str | None, int | None]:
    """Extrait (date_debut, date_fin, duree_jours) depuis une ligne de date de slide."""
    text = text.replace("\xa0", " ")

    # "du [jour] X mois1 [YYYY] au [jour] Y mois2 [YYYY]"
    m = re.search(
        r"du\s+" + _OJ + r"(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?\s+au\s+" + _OJ + r"(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
        text, re.I,
    )
    if m:
        j1, m1, a1, j2, m2, a2 = m.groups()
        if m1.lower() in MOIS and m2.lower() in MOIS:
            if not a2:
                a2 = a1
            d1, d2 = _parse_date(j1, m1, a1), _parse_date(j2, m2, a2)
            if d1 and d2:
                delta = (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
                return d1, d2, delta if delta > 0 else None
            return d1, d2, None

    # "du [jour] X au [jour] Y mois [YYYY]" (même mois)
    m = re.search(
        r"du\s+" + _OJ + r"(\d+)\w*\s+au\s+" + _OJ + r"(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
        text, re.I,
    )
    if m:
        j1, j2, mois, an = m.groups()
        if mois.lower() in MOIS:
            d1, d2 = _parse_date(j1, mois, an), _parse_date(j2, mois, an)
            if d1 and d2:
                delta = (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
                return d1, d2, delta if delta > 0 else None

    # "[jour] X mois [YYYY]" — jour unique
    m = re.search(_OJ + r"(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?", text, re.I)
    if m:
        j, mois, an = m.groups()
        if mois.lower() in MOIS:
            d = _parse_date(j, mois, an)
            if d:
                return d, d, 1

    return None, None, None


async def _scrape_async() -> list[dict]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=_UA, locale="fr-FR")
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()
        try:
            resp = await page.goto(_URL, wait_until="domcontentloaded", timeout=25_000)
            if not resp or resp.status >= 400:
                logger.warning("[parisbouge_expos] HTTP %s", resp.status if resp else "?")
                return []
            await page.wait_for_timeout(3000)
            for _ in range(8):
                await page.evaluate("window.scrollBy(0, 800)")
                await page.wait_for_timeout(400)
            sections = await page.evaluate(_JS)
        except Exception:
            logger.exception("[parisbouge_expos] erreur chargement")
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

            # Structure des lines après filtrage AJOUTER :
            # lines[0] = titre (même que name)
            # lines[1] = date (ex: "du mercredi 2 juin au dimanche 6 septembre")
            # lines[2] = lieu (ex: "Grand Palais")
            lines = place.get("lines", [])
            date_line = lines[1] if len(lines) > 1 else ""
            lieu = lines[2] if len(lines) > 2 else ""

            date_debut, date_fin, duree_jours = _parse_date_line(date_line)

            events.append({
                "titre":       name,
                "description": "",
                "adresse":     lieu,
                "date_debut":  date_debut,
                "date_fin":    date_fin,
                "duree_jours": duree_jours,
                "categorie":   "exposition",
                "source":      "parisbouge_expos",
                "url":         href or _URL,
            })

    logger.info("[parisbouge_expos] %d expositions extraites", len(events))
    return events


class ParisBougeExpos(BaseScraper):
    name = "parisbouge_expos"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())
