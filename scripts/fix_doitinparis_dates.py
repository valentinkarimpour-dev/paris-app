"""
Remédiation ciblée : ajoute les dates manquantes aux events doitinparis.
Stratégie :
  1. Charge chaque page de base (une seule fois via Playwright)
  2. Pour chaque event sans date, cherche son titre dans le texte de la page (Ctrl+F)
  3. Extrait les 600 chars autour de la correspondance
  4. LLM extrait date_debut + duree_jours depuis ce contexte
  5. UPDATE en DB sans toucher aux autres champs
"""

import asyncio
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

from playwright.async_api import async_playwright

import logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("scrapers.base").setLevel(logging.DEBUG)

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from scrapers.base import extract_with_llm

DB_PATH = Path(__file__).parent.parent / "backend" / "events.db"


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _find_context(page_text: str, titre: str, window: int = 700) -> str:
    """Retourne le texte autour du titre dans la page (recherche souple)."""
    words = titre.strip().split()

    # Variantes de recherche : titre complet → 4 premiers mots → 3 → 2
    candidates = [titre]
    for n in [4, 3, 2]:
        if len(words) >= n:
            candidates.append(" ".join(words[:n]))

    for term in candidates:
        # Recherche insensible à la casse avec regex (pas de strip accents)
        try:
            m = re.search(re.escape(term), page_text, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 150)
                end   = min(len(page_text), m.end() + window)
                return page_text[start:end]
        except re.error:
            pass

        # Fallback : strip accents sur les deux textes, cherche dans texte normalisé
        norm_page  = _strip_accents(page_text)
        norm_term  = _strip_accents(term)
        try:
            m = re.search(re.escape(norm_term), norm_page, re.IGNORECASE)
            if m:
                start = max(0, m.start() - 150)
                end   = min(len(page_text), m.end() + window)
                return page_text[start:end]
        except re.error:
            pass

    return ""


async def _fetch_page_text(url: str) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="fr-FR",
        )
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2000)
            for _ in range(12):
                await page.evaluate("window.scrollBy(0, 1500)")
                await page.wait_for_timeout(300)
            text = await page.evaluate("() => document.body.innerText")
        except Exception as e:
            print(f"  [ERREUR] fetch {url}: {e}")
            text = ""
        await browser.close()
    return text


def main():
    conn = sqlite3.connect(DB_PATH)

    # Récupère les events sans date groupés par page
    rows = conn.execute("""
        SELECT id, titre, url, date_debut, duree_jours
        FROM events
        WHERE source='doitinparis' AND date_debut IS NULL
        ORDER BY url
    """).fetchall()

    if not rows:
        print("Aucun event doitinparis sans date — rien à faire.")
        return

    print(f"{len(rows)} events à traiter...")

    # Groupe par URL de base
    by_base: dict[str, list] = {}
    for row in rows:
        base = row[2].split("#")[0]
        by_base.setdefault(base, []).append(row)

    updated = 0
    for base_url, events in by_base.items():
        print(f"\n>>> Chargement page : {base_url}")
        page_text = asyncio.run(_fetch_page_text(base_url))
        if not page_text:
            continue
        print(f"    {len(page_text)} chars chargés, {len(events)} events à dater")

        for event_id, titre, url, _, _ in events:
            context = _find_context(page_text, titre)
            if not context:
                print(f"  [{event_id}] «{titre}» — non trouvé dans la page, skip")
                continue

            # Pre-filtrage : le contexte contient-il une vraie date ?
            DATE_MARKERS = re.compile(
                r"\b(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre"
                r"|jan|fev|mars|avr|juil|aout|sep|oct|nov|dec"
                r"|2025|2026|du \d|au \d|jusqu|jusqu'au|ouvert)\b",
                re.IGNORECASE,
            )
            if not DATE_MARKERS.search(context):
                print(f"  [{event_id}] «{titre}» — contexte sans marqueur de date, skip")
                continue

            print(f"  [{event_id}] «{titre}» — contexte trouvé ({len(context)} chars)")

            # Retry LLM jusqu'à 2 fois en cas de rate limit (retour vide)
            extracted = {}
            for attempt in range(3):
                extracted = extract_with_llm(f"Événement : {titre}\n\n{context}")
                if extracted.get("date_debut"):
                    break
                if attempt < 2:
                    time.sleep(3)

            date_debut  = extracted.get("date_debut")
            duree_jours = extracted.get("duree_jours")

            if date_debut:
                conn.execute("""
                    UPDATE events
                    SET date_debut=?, duree_jours=?
                    WHERE id=?
                """, (date_debut, duree_jours, event_id))
                conn.commit()
                print(f"    → date_debut={date_debut}, duree_jours={duree_jours} ✓")
                updated += 1
            else:
                print(f"    → aucune date extraite")

            time.sleep(5)  # conservateur : 6000 tokens/min, ~400 tokens/call

    conn.close()
    print(f"\n=== Terminé : {updated}/{len(rows)} events mis à jour ===")


if __name__ == "__main__":
    main()
