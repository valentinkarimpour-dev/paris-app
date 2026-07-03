"""
LeBonbon Drinks — script de diagnostic
Compare comportement actuel (Passe A) vs fixes proposés (Passe B).
Ne modifie pas lebonbon_drinks.py.
"""

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

# ── Standalone path setup ──────────────────────────────────────────────────
_root = Path(__file__).parent.parent.parent  # → backend/
sys.path.insert(0, str(_root))

_env_file = _root / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())

from playwright.async_api import async_playwright
from scrapers.base import extract_with_llm
import geocoder

logging.basicConfig(level=logging.WARNING)

# ── Constantes copiées de lebonbon_drinks.py ──────────────────────────────
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_PRIORITY_CATS = {"rooftop", "bar", "cafe"}

_CAT_HINTS = [
    (re.compile(r"rooftop|terrasse|toit\b", re.I), "rooftop"),
    (re.compile(r"\bbar\b|cocktail|speakeasy", re.I), "bar"),
    (re.compile(r"\bcaf[eé]\b|coffee|brunch", re.I), "cafe"),
]


def _resolve_categorie(llm_cat: str, href: str, title: str) -> str:
    if llm_cat in _PRIORITY_CATS:
        return llm_cat
    slug = href.rstrip("/").split("/")[-1]
    for pattern, cat in _CAT_HINTS:
        if pattern.search(slug) or pattern.search(title):
            return cat
    return llm_cat


# ── URLs de test ───────────────────────────────────────────────────────────
URLS = [
    "https://www.lebonbon.fr/paris/rooftops/ce-musee-parisien-rouvre-son-rooftop-core/",
    "https://www.lebonbon.fr/paris/rooftops/perchoir-porte-versailles-rooftop-italien/",
]

# ── Prefix Passe B ─────────────────────────────────────────────────────────
_PREFIX_B = (
    "[RÈGLE TITRE : extraire le nom de l'ÉVÉNEMENT ou du lieu "
    "s'il EST l'événement (ex: 'Rooftop Musée d'Orsay', "
    "'Le Perchoir Porte de Versailles'). Ne pas retourner "
    "uniquement le nom du bâtiment s'il accueille un événement "
    "distinct.]\n\n"
    "[RÈGLE DATES SAISONNIÈRES : 'terrasse estivale', 'saison 2026', "
    "'tout l'été' → date_debut=2026-06-01, date_fin=2026-09-22. "
    "'pour l'été 2026' → même inférence.]\n\n"
)


async def _fetch_text(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(user_agent=_UA, locale="fr-FR")
        await ctx.route(
            "**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}",
            lambda r: r.abort(),
        )
        page = await ctx.new_page()
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            if not resp or resp.status >= 400:
                print(f"  HTTP {resp.status if resp else '?'}")
                await browser.close()
                return ""
            await page.wait_for_timeout(1500)
            text = await page.evaluate("() => document.body.innerText")
        except Exception as e:
            print(f"  Playwright error: {e}")
            await browser.close()
            return ""
        await browser.close()
        return text or ""


async def main() -> None:
    SEP  = "═" * 60
    SEP2 = "─" * 40

    for url in URLS:
        slug = url.rstrip("/").split("/")[-1]
        print(f"\n{SEP}")
        print(f"URL : {slug}")
        print(SEP)

        print("\nFetching via Playwright...")
        text = await _fetch_text(url)
        if not text:
            print("  ✗ texte vide — URL inaccessible ?")
            continue
        print(f"  {len(text)} chars récupérés")

        # ── PASSE A — Comportement actuel ─────────────────────────────────
        print(f"\n{SEP2}")
        print("PASSE A — Comportement actuel (extract_with_llm brut, texte complet)")
        print(SEP2)

        data_a = extract_with_llm(text)

        adresse_a = data_a.get("adresse") or ""
        lat_a, lng_a = None, None
        if adresse_a:
            lat_a, lng_a = geocoder.geocode(adresse_a)

        print(f"  titre      : {data_a.get('titre')}")
        print(f"  date_debut : {data_a.get('date_debut')}")
        print(f"  date_fin   : {data_a.get('date_fin')}")
        print(f"  duree_jours: {data_a.get('duree_jours')}")
        print(f"  adresse    : {adresse_a!r}")
        print(f"  lat/lng    : {lat_a}, {lng_a}")
        print(f"  categorie  : {data_a.get('categorie')}")

        # ── PASSE B — Avec fixes ──────────────────────────────────────────
        print(f"\n{SEP2}")
        print("PASSE B — Fixes : prefix + texte[:3000] + cascade géocodage + catégorie")
        print(SEP2)

        data_b = extract_with_llm(_PREFIX_B + text[:3000])

        adresse_b = data_b.get("adresse") or ""
        lat_b, lng_b = None, None
        if adresse_b:
            lat_b, lng_b = geocoder.geocode(adresse_b)
        if not lat_b and adresse_b:
            lat_b, lng_b = geocoder.geocode_freetext(adresse_b)
        if not lat_b and data_b.get("titre"):
            lat_b, lng_b = geocoder.geocode_freetext(data_b["titre"])

        categorie_b = _resolve_categorie(
            data_b.get("categorie", "autre"),
            url,
            data_b.get("titre", ""),
        )

        date_debut_b = data_b.get("date_debut")
        date_fin_b   = data_b.get("date_fin")
        date_ok = bool(date_debut_b and date_fin_b and "2026" in str(date_debut_b))

        print(f"  titre      : {data_b.get('titre')}")
        print(f"  date_debut : {date_debut_b}")
        print(f"  date_fin   : {date_fin_b}")
        print(f"  adresse    : {adresse_b!r}")
        print(f"  lat/lng    : {lat_b}, {lng_b}")
        print(f"  categorie  : {categorie_b}")
        print(f"\n  date estivale inférée : {'✓' if date_ok else '✗'}")
        print(f"  géocodage résolu      : {'✓' if lat_b else '✗'}")

    print(f"\n{SEP}\nFin du diagnostic\n{SEP}")


if __name__ == "__main__":
    asyncio.run(main())
