"""
Scraper SortirAParis.com — événements de la semaine
Stocke dans events.db (SQLite) : titre, cat, date, adresse, lat, lng, prix, url, source

Usage :
  python3 scraper.py              # listing + enrichissement détail
  python3 scraper.py --list-only  # listing seulement (plus rapide, pas de 401)
"""

import sys
import sqlite3
import asyncio
import random
from datetime import datetime
from playwright.async_api import async_playwright, Page, BrowserContext

try:
    from playwright_stealth import stealth_async
    STEALTH = True
except ImportError:
    STEALTH = False

DB_PATH = "events.db"
BASE_URL = "https://www.sortiraparis.com"
LIST_ONLY = "--list-only" in sys.argv

# Catégories → (chemin URL, label frontend)
# Brocante et marchés sont dans /loisirs/shopping-mode sur SortirAParis
CATEGORIES = [
    ("/loisirs/cinema",          "cinema"),
    ("/arts-culture/exposition", "expo"),
    ("/scenes/spectacle",        "spectacle"),
    ("/scenes/concert-musique",  "concert"),
    ("/loisirs/shopping-mode",   "brocante"),   # brocante + marchés vintage
]

# Déduire la catégorie depuis le chemin de l'URL de l'article
URL_CAT_MAP = {
    "/loisirs/cinema":          "cinema",
    "/loisirs/gaming":          "autre",
    "/loisirs/shopping-mode":   "brocante",
    "/loisirs/salon":           "expo",
    "/arts-culture/exposition": "expo",
    "/arts-culture/":           "expo",
    "/scenes/spectacle":        "spectacle",
    "/scenes/concert-musique":  "concert",
    "/scenes/":                 "spectacle",
}

CAT_MAP = {
    "cinéma": "cinema", "cinema": "cinema", "film": "cinema", "séries": "cinema",
    "exposition": "expo", "expo": "expo", "musée": "expo", "galerie": "expo",
    "concert": "concert", "musique": "concert",
    "brocante": "brocante", "vide-grenier": "brocante", "antiquités": "brocante",
    "marché": "marche", "marche": "marche",
    "spectacle": "spectacle", "théâtre": "spectacle", "danse": "spectacle",
    "comédie": "spectacle", "cirque": "spectacle", "festival": "spectacle",
}


def normalize_cat(raw: str) -> str:
    if not raw:
        return "autre"
    low = raw.lower().strip()
    for key, val in CAT_MAP.items():
        if key in low:
            return val
    return "autre"


def normalize_price(raw: str) -> str:
    if not raw:
        return ""
    low = raw.lower().strip()
    if any(w in low for w in ["gratuit", "free", "0 €", "0€", "entrée libre"]):
        return "Gratuit"
    return raw.strip()


# ──────────────────────────────────────────
# BASE DE DONNÉES
# ──────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            titre       TEXT NOT NULL,
            cat         TEXT,
            date        TEXT,
            adresse     TEXT,
            lat         REAL,
            lng         REAL,
            prix        TEXT,
            url         TEXT UNIQUE,
            source      TEXT DEFAULT 'SortirAParis',
            scraped_at  TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cat ON events(cat)")
    conn.commit()


def upsert_event(conn: sqlite3.Connection, ev: dict):
    conn.execute("""
        INSERT INTO events (titre, cat, date, adresse, lat, lng, prix, url, source, scraped_at)
        VALUES (:titre, :cat, :date, :adresse, :lat, :lng, :prix, :url, :source, :scraped_at)
        ON CONFLICT(url) DO UPDATE SET
            titre      = excluded.titre,
            cat        = excluded.cat,
            date       = excluded.date,
            adresse    = excluded.adresse,
            prix       = excluded.prix,
            scraped_at = excluded.scraped_at
    """, ev)


# ──────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────

async def rand_delay(min_ms=1000, max_ms=2500):
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def wait_for_site(timeout_s=60) -> bool:
    """Attend que le site soit accessible avant de commencer."""
    import urllib.request, ssl
    deadline = asyncio.get_event_loop().time() + timeout_s
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    while asyncio.get_event_loop().time() < deadline:
        try:
            urllib.request.urlopen(BASE_URL, timeout=5, context=ctx)
            return True
        except Exception:
            print("  Site inaccessible, nouvel essai dans 10s…")
            await asyncio.sleep(10)
    return False


async def safe_goto(page: Page, url: str, retries=2, detail=False) -> bool:
    """Navigue vers url. detail=True utilise des délais plus longs (pages articles)."""
    for attempt in range(retries + 1):
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=40_000)
            if resp and resp.status == 401:
                return False
            # Délai post-chargement
            if detail:
                await rand_delay(2000, 4000)
            else:
                await rand_delay(800, 1500)
            return True
        except Exception as e:
            wait = 8000 + attempt * 5000  # backoff exponentiel
            if attempt < retries:
                print(f"    ↺ Retry {attempt+1} dans {wait//1000}s…")
                await asyncio.sleep(wait / 1000)
            else:
                print(f"    ✗ {url.split('/')[-1]}: bloqué")
                return False
    return False


# ──────────────────────────────────────────
# SCRAPE LISTING
# ──────────────────────────────────────────

async def scrape_listing(page: Page, cat_path: str, cat_label: str) -> list[dict]:
    url = f"{BASE_URL}{cat_path}"
    print(f"\n→ [{cat_label}] {url}")
    events = []

    ok = await safe_goto(page, url)
    if not ok:
        print("  ⚠ Inaccessible")
        return events

    # Scroll pour charger le lazy-load
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, 1200)")
        await page.wait_for_timeout(500)

    cards = await page.query_selector_all("div.slides")
    print(f"  {len(cards)} cards")

    for card in cards:
        try:
            title_el = await card.query_selector(".title a")
            if not title_el:
                continue
            titre = (await title_el.inner_text()).strip()
            href = await title_el.get_attribute("href") or ""
            if not titre or not href:
                continue
            event_url = href if href.startswith("http") else BASE_URL + href

            # Catégorie déduite depuis l'URL de l'article (plus fiable que le HTML)
            cat = cat_label
            for prefix, mapped in URL_CAT_MAP.items():
                if event_url.replace(BASE_URL, "").startswith(prefix):
                    cat = mapped
                    break

            events.append({
                "titre": titre,
                "cat": cat,
                "url": event_url,
                "date": None,
                "adresse": None,
                "lat": None,
                "lng": None,
                "prix": None,
            })
        except Exception:
            continue

    print(f"  → {len(events)} collectés")
    return events


# ──────────────────────────────────────────
# SCRAPE DÉTAIL
# ──────────────────────────────────────────

async def enrich_event(page: Page, ev: dict) -> dict:
    """
    Visite la page détail et extrait date, adresse, lat/lng, prix
    depuis le bloc #practical-info de SortirAParis.
    """
    import re

    ok = await safe_goto(page, ev["url"], detail=True)
    if not ok:
        return ev

    html = await page.content()
    if len(html) < 5000:  # page de sécurité / bot-check
        return ev

    # ── Adresse (microdata Schema.org) ──
    adresse = ""
    parts = []
    for prop in ["streetAddress", "postalCode", "addressLocality"]:
        el = await page.query_selector(f"[itemprop='{prop}']")
        if el:
            t = (await el.inner_text()).strip()
            if t:
                parts.append(t)
    if parts:
        adresse = " ".join(parts)

    # ── Coordonnées (injectées dans _mapHandler.init) ──
    lat, lng = None, None
    m = re.search(
        r'_mapHandler\.init\([^)]*"markers"\s*:\s*\[{"l"\s*:([\d.]+),"L"\s*:([\d.]+)',
        html
    )
    if m:
        try:
            lat = float(m.group(1))
            lng = float(m.group(2))
        except ValueError:
            pass

    # ── Date (ISO meta + texte) ──
    date = ""
    start_el = await page.query_selector("meta[itemprop='startDate']")
    end_el   = await page.query_selector("meta[itemprop='endDate']")
    if start_el:
        start = (await start_el.get_attribute("content") or "")[:10]  # YYYY-MM-DD
        end   = ""
        if end_el:
            end_raw = (await end_el.get_attribute("content") or "")[:10]
            if end_raw != start:
                end = end_raw
        date = f"Du {start}" + (f" au {end}" if end else "")
    # Fallback : texte lisible ("Du 1er mai au 31 mai")
    if not date:
        m_date = re.search(
            r'Du\s+[^<]{5,60}(?:au\s+[^<]{5,60})?',
            html[max(0, html.find("practical-info")):html.find("practical-info") + 3000]
            if "practical-info" in html else html
        )
        if m_date:
            date = re.sub(r'\s+', ' ', m_date.group()).strip()

    # ── Prix (<strong>Tarifs</strong><br>PRIX<br>) ──
    prix = ""
    m_prix = re.search(r'<strong>Tarifs</strong><br>\s*([^<\n]+)', html)
    if m_prix:
        prix = m_prix.group(1).strip()
    if not prix:
        body_lower = html.lower()
        if "gratuit" in body_lower or "entrée libre" in body_lower:
            prix = "Gratuit"

    return {
        **ev,
        "adresse": adresse or ev.get("adresse"),
        "lat": lat or ev.get("lat"),
        "lng": lng or ev.get("lng"),
        "date": date or ev.get("date"),
        "prix": normalize_price(prix) if prix else ev.get("prix"),
    }


# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────

async def main():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # Attendre que le site soit accessible (protection contre le rate-limit)
    print("▶ Vérification de l'accès au site…")
    accessible = await wait_for_site(timeout_s=120)
    if not accessible:
        print("✗ Site inaccessible après 2min. Réessaie plus tard.")
        conn.close()
        return

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        ctx: BrowserContext = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
            viewport={"width": 1280, "height": 900},
            java_script_enabled=True,
        )
        # Bloque les ressources lourdes pour aller plus vite
        await ctx.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff2,woff,eot,ttf,otf}",
            lambda r: r.abort()
        )
        await ctx.route(
            "**/{ads,doubleclick,googlesyndication,google-analytics,facebook,linkedin}**",
            lambda r: r.abort()
        )

        page = await ctx.new_page()
        if STEALTH:
            await stealth_async(page)

        # Session homepage — récupère le cookie anti-bot
        print("▶ Établissement de la session…")
        await rand_delay(500, 1000)
        ok = await safe_goto(page, BASE_URL)
        if not ok:
            print("✗ Impossible d'accéder à la homepage.")
            await browser.close()
            conn.close()
            return
        await rand_delay(1500, 3000)

        # ── Phase 1 : listings ──
        all_events: list[dict] = []
        seen_urls: set[str] = set()

        for cat_path, cat_label in CATEGORIES:
            items = await scrape_listing(page, cat_path, cat_label)
            for ev in items:
                if ev["url"] not in seen_urls:
                    seen_urls.add(ev["url"])
                    all_events.append(ev)
            await rand_delay(1500, 3000)

        print(f"\n── {len(all_events)} événements uniques (phase listing) ──")

        # ── Phase 2 : enrichissement ──
        enriched = []
        if not LIST_ONLY:
            print("▶ Enrichissement des détails (Ctrl+C pour sauter)…")
            blocked = 0
            consecutive_fails = 0
            for i, ev in enumerate(all_events):
                print(f"  [{i+1}/{len(all_events)}] {ev['titre'][:55]}")
                ev_enriched = await enrich_event(page, ev)
                got_data = ev_enriched.get("date") or ev_enriched.get("adresse") or ev_enriched.get("prix")
                if not got_data:
                    blocked += 1
                    consecutive_fails += 1
                    # Pause longue après 2 échecs consécutifs — laisse le WAF se réinitialiser
                    if consecutive_fails >= 2:
                        print(f"    ⏸ Pause 15s (WAF rate-limit)…")
                        await asyncio.sleep(15)
                        consecutive_fails = 0
                else:
                    consecutive_fails = 0
                ev_enriched["source"] = "SortirAParis"
                ev_enriched["scraped_at"] = datetime.now().isoformat(timespec="seconds")
                enriched.append(ev_enriched)
                # Délai humain entre chaque page détail (3-6s)
                await rand_delay(3000, 6000)
            print(f"\n── Détails: {len(all_events)-blocked} enrichis, {blocked} bloqués ──")
        else:
            print("▶ Mode listing-only (--list-only activé)")
            ts = datetime.now().isoformat(timespec="seconds")
            for ev in all_events:
                ev["source"] = "SortirAParis"
                ev["scraped_at"] = ts
                enriched.append(ev)

        await browser.close()

    # ── Sauvegarde ──
    saved = 0
    for ev in enriched:
        try:
            upsert_event(conn, ev)
            saved += 1
        except Exception as e:
            print(f"  ✗ DB: {ev.get('titre','?')[:40]} — {e}")

    conn.commit()
    conn.close()
    print(f"\n✓ {saved}/{len(enriched)} événements enregistrés dans {DB_PATH}")

    # Aperçu
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT titre, cat, date, prix, adresse FROM events ORDER BY id DESC LIMIT 15"
    ).fetchall()
    conn.close()

    print("\n── Aperçu ──────────────────────────────────────────────────")
    print(f"{'CAT':10}  {'TITRE':45}  {'PRIX':10}  DATE")
    print("─" * 90)
    for r in rows:
        print(
            f"{(r['cat'] or '?'):10}  {(r['titre'] or '')[:45]:45}  "
            f"{(r['prix'] or '—'):10}  {r['date'] or '—'}"
        )


if __name__ == "__main__":
    asyncio.run(main())
