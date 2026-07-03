"""
LeBonbon Food — script de diagnostic
Compare comportement actuel (Passe A) vs fixes proposés (Passe B).
Ne modifie pas lebonbon_food.py.
"""

import asyncio
import logging
import os
import re
import sys
import time
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

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

URLS = [
    "https://www.lebonbon.fr/paris/actu/kodawari-meilleur-ramen-paris-nouvelle-adresse-canard/",
    "https://www.lebonbon.fr/paris/actu/st-germain-ete-rooftop-galeries-lafayette-paris-haussmann/",
    "https://www.lebonbon.fr/paris/actu/fete-sardines-deux-jours-ensoleilles-week-end/",
    "https://www.lebonbon.fr/paris/actu/mohamed-cheikh-premier-restaurant-capitale/",
]

_PREFIX_B = (
    "[RÈGLE TITRE : extraire le nom de l'ÉVÉNEMENT ou du lieu "
    "s'il EST l'événement. Pas uniquement le nom du bâtiment "
    "qui l'accueille.]\n\n"
    "[RÈGLE DATES : si aucune date précise n'est mentionnée "
    "('adresse secrète', 'ouverture prochaine', 'bientôt'), "
    "retourner null pour date_debut et date_fin. "
    "Ne pas inventer de date.]\n\n"
    "[RÈGLE DATES SAISONNIÈRES : 'tout l'été', 'saison estivale', "
    "'à partir du X juin/juillet' → "
    "date_debut=date explicite ou 2026-06-01, "
    "date_fin=2026-09-22.]\n\n"
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

    for i, url in enumerate(URLS):
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
        print("PASSE A — Comportement actuel (extract_with_llm brut)")
        print(SEP2)

        data_a = extract_with_llm(text)

        adresse_a = data_a.get("adresse") or ""
        lat_a, lng_a = None, None
        if adresse_a:
            lat_a, lng_a = geocoder.geocode(adresse_a)
            time.sleep(1)

        inserted_a = bool(data_a.get("titre"))
        verdict_a  = "✓ INSÉRÉ" if inserted_a else "✗ SKIP (pas de titre)"

        print(f"  titre      : {data_a.get('titre')}")
        print(f"  date_debut : {data_a.get('date_debut')}")
        print(f"  date_fin   : {data_a.get('date_fin')}")
        print(f"  duree_jours: {data_a.get('duree_jours')}")
        print(f"  adresse    : {adresse_a!r}")
        print(f"  lat/lng    : {lat_a}, {lng_a}")
        print(f"  categorie  : {data_a.get('categorie')}")
        print(f"  → {verdict_a}")

        # ── PASSE B — Avec fixes ──────────────────────────────────────────
        print(f"\n{SEP2}")
        print("PASSE B — Fixes : prefix + cascade géocodage + filtre skip")
        print(SEP2)

        data_b = extract_with_llm(_PREFIX_B + text[:3000])

        adresse_b = data_b.get("adresse") or ""
        lat_b, lng_b = None, None
        if adresse_b:
            lat_b, lng_b = geocoder.geocode(adresse_b)
            time.sleep(1)
        if not lat_b and adresse_b:
            lat_b, lng_b = geocoder.geocode_freetext(adresse_b)
            time.sleep(1)
        if not lat_b and data_b.get("titre"):
            lat_b, lng_b = geocoder.geocode_freetext(data_b["titre"])
            time.sleep(1)

        date_debut_b = data_b.get("date_debut")
        date_fin_b   = data_b.get("date_fin")

        if date_debut_b is None and lat_b is None:
            verdict_b = "✗ SKIP (pas de date ni de lieu)"
        elif not data_b.get("titre"):
            verdict_b = "✗ SKIP (pas de titre)"
        else:
            verdict_b = "✓ INSÉRÉ"

        print(f"  titre      : {data_b.get('titre')}")
        print(f"  date_debut : {date_debut_b}")
        print(f"  date_fin   : {date_fin_b}")
        print(f"  adresse    : {adresse_b!r}")
        print(f"  lat/lng    : {lat_b}, {lng_b}")
        print(f"  categorie  : {data_b.get('categorie')}")
        print(f"  → {verdict_b}")

    print(f"\n{SEP}\nFin du diagnostic\n{SEP}")


if __name__ == "__main__":
    asyncio.run(main())
