"""
Scraper : Expositions des musées parisiens — parser générique BS4
Flow :
  1. Overpass → liste des musées avec website dans le radius
  2. MUSEUM_CONFIGS → URL agenda connue (bypass nav) ou find_agenda_url fallback
  3. _parse_generic → extraction BS4 multi-patterns (article/card, <time>, regex date FR)

Aucun appel LLM, aucun coût.
museum_name = tags.name OSM pour que le frontend puisse matcher.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import dateparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from ..base import BaseScraper

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent.parent / ".env")

DAYS_CUTOFF    = 30
THROTTLE_HOURS = 6

# Cache homepage → agenda_url découverte dynamiquement
_agenda_url_cache: dict[str, str | None] = {}

AGENDA_KEYWORDS = [
    "exposition", "exhibition", "agenda", "programmation",
    "whats-on", "what-s-on", "en-cours", "current",
]

# ── URLs agenda connues pour les 30 grands musées parisiens ───────────────────
# Clé : netloc sans "www." — valeur : URL directe de la page expositions
MUSEUM_CONFIGS: dict[str, str] = {
    "louvre.fr":                           "https://www.louvre.fr/expositions-et-evenements/expositions",
    "musee-orsay.fr":                      "https://www.musee-orsay.fr/fr/expositions",
    "centrepompidou.fr":                   "https://www.centrepompidou.fr/fr/au-programme/expositions",
    "museepicassoparis.fr":                "https://www.museepicassoparis.fr/fr/expositions-en-cours",
    "quaibranly.fr":                       "https://www.quaibranly.fr/fr/agenda/",
    "musee-rodin.fr":                      "https://www.musee-rodin.fr/fr/expositions",
    "marmottan.fr":                        "https://www.marmottan.fr/expositions/",
    "musee-orangerie.fr":                  "https://www.musee-orangerie.fr/fr/programme/agenda",
    "guimet.fr":                           "https://www.guimet.fr/fr/expositions/",
    "mam.paris.fr":                        "https://www.mam.paris.fr/fr/expositions",
    "palaisdetokyo.com":                   "https://www.palaisdetokyo.com/programmation/",
    "lesartsdecoratifs.fr":                "https://www.lesartsdecoratifs.fr/expositions-et-evenements/",
    "fondationlouisvuitton.fr":            "https://www.fondationlouisvuitton.fr/fr/expositions.html",
    "imarabe.org":                         "https://www.imarabe.org/fr/expositions",
    "petitpalais.paris.fr":               "https://www.petitpalais.paris.fr/expositions",
    "palaisgalliera.paris.fr":            "https://www.palaisgalliera.paris.fr/expositions",
    "musee-jacquemart-andre.com":          "https://www.musee-jacquemart-andre.com/fr/expositions",
    "mahj.org":                            "https://www.mahj.org/fr/programme/l-agenda-du-mahj?f%5B0%5D=field_ag_type_manifestation%3A422",
    "mep-fr.org":                          "https://www.mep-fr.org/programme/",
    "museecognacqjay.paris.fr":           "https://www.museecognacqjay.paris.fr/expositions",
    "musee-moyenage.fr":                   "https://www.musee-moyenage.fr/fr/expositions.html",
    "museedelhomme.fr":                    "https://www.museedelhomme.fr/fr/expositions",
    "cite-sciences.fr":                    "https://www.cite-sciences.fr/fr/au-programme/expos-temporaires",
    "musee-armee.fr":                      "https://www.musee-armee.fr/programmation/expositions.html",
    "fondationazzedinealaia.org":          "https://fondationazzedinealaia.org/expositions/",
    "maisonsvictorhugo.paris.fr":         "https://www.maisonsvictorhugo.paris.fr/paris/agenda",
    "atelier-lumieres.com":               "https://www.atelier-lumieres.com/fr/programmation",
    "museedemontmartre.fr":               "https://www.museedemontmartre.fr/expositions/",
    "paris.si.se":                         "https://paris.si.se/agenda/",
    "carnavalet.paris.fr":                 "https://www.carnavalet.paris.fr/expositions/expositions-en-cours",
    "musee-delacroix.fr":                  "https://www.musee-delacroix.fr/fr/expositions",
    "grandpalais-immersif.fr":             "https://www.grandpalais-immersif.fr/programmation/",
    "chassenature.org":                    "https://www.chassenature.org/expositions/",
    "memorialdelashoah.org":              "https://billetterie.memorialdelashoah.org/fr/evenements/expositions-temporaires",
    "archives-nationales.culture.gouv.fr":"https://www.archives-nationales.culture.gouv.fr/expositions",
}


# ── Overpass ──────────────────────────────────────────────────────────────────

def resolve_museums_from_osm(lat: float, lng: float, radius_m: int) -> list[dict]:
    query = (
        f"[out:json][timeout:25];\n"
        f"(\n"
        f'  node["tourism"="museum"](around:{radius_m},{lat},{lng});\n'
        f'  way["tourism"="museum"](around:{radius_m},{lat},{lng});\n'
        f");\nout center;"
    )
    for overpass_url in [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]:
        try:
            resp = requests.post(overpass_url, data={"data": query}, timeout=30)
            if resp.ok:
                break
        except Exception:
            continue
    else:
        logger.warning("[museum_events] Overpass inaccessible")
        return []

    museums = []
    for el in resp.json().get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name:fr") or tags.get("name")
        website = tags.get("website") or tags.get("contact:website")
        if not name or not website:
            continue
        lat_el = el.get("lat") or (el.get("center") or {}).get("lat")
        lng_el = el.get("lon") or (el.get("center") or {}).get("lon")
        if not lat_el or not lng_el:
            continue
        museums.append({
            "nom":     name,
            "website": website.rstrip("/"),
            "lat":     float(lat_el),
            "lng":     float(lng_el),
        })

    logger.info("[museum_events] Overpass : %d musées avec website", len(museums))
    return museums


# ── URL agenda ────────────────────────────────────────────────────────────────

def _known_agenda_url(website: str) -> str | None:
    domain = urlparse(website).netloc.removeprefix("www.")
    return MUSEUM_CONFIGS.get(domain)


async def find_agenda_url(page, website: str) -> str | None:
    """Fetch la homepage et cherche un lien agenda dans la nav (fallback)."""
    if website in _agenda_url_cache:
        return _agenda_url_cache[website]
    try:
        resp = await page.goto(website, wait_until="domcontentloaded", timeout=20_000)
        if not resp or resp.status >= 400:
            _agenda_url_cache[website] = None
            return None
        await page.wait_for_timeout(1000)

        links: list[dict] = await page.evaluate("""() => {
            const selectors = ['nav','header','[role="navigation"]','.menu','.nav','.navbar'];
            let scope = document;
            for (const s of selectors) {
                const el = document.querySelector(s);
                if (el) { scope = el; break; }
            }
            return Array.from(scope.querySelectorAll('a[href]'))
                .map(a => ({ href: a.href, text: a.textContent.trim().toLowerCase() }))
                .filter(l => l.href.startsWith('http'));
        }""")

        base_domain = urlparse(website).netloc
        for kw in AGENDA_KEYWORDS:
            for link in links:
                href = link.get("href", "")
                if kw not in href.lower() and kw not in link.get("text", ""):
                    continue
                if urlparse(href).netloc != base_domain:
                    continue
                _agenda_url_cache[website] = href
                logger.info("[museum_events] %s → agenda (nav) : %s", website, href)
                return href

        _agenda_url_cache[website] = None
        return None
    except Exception as exc:
        logger.warning("[museum_events] find_agenda_url(%s) : %s", website, exc)
        _agenda_url_cache[website] = None
        return None


# ── Parser générique BS4 ──────────────────────────────────────────────────────

_DATE_RE = re.compile(
    r'\b(\d{1,2})\s+'
    r'(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|'
    r'septembre|octobre|novembre|d[eé]cembre)'
    r'\s+(\d{4})\b',
    re.I,
)

# Handles "29 avril - 16 août 2026": first date has no year, second has one
_DATE_RANGE_PARTIAL_RE = re.compile(
    r'\b(\d{1,2})\s+(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|'
    r'septembre|octobre|novembre|d[eé]cembre)\b'
    r'.{0,25}?'
    r'\b(\d{1,2})\s+(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|'
    r'septembre|octobre|novembre|d[eé]cembre)\s+(\d{4})\b',
    re.I,
)

_MONTH_NUM = {
    "janvier": 1, "fevrier": 2, "février": 2,
    "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12, "décembre": 12,
}

# Titres à ignorer (pages système, consentement, nav...)
_SKIP_TITLE_RE = re.compile(
    r'cookie|consentement|confidential|accepter|politique|newsletter|'
    r'^(accueil|contact|menu|navigation|réseaux|suivez|horaires|tarif|billetterie|'
    r'collection|exposition$|agenda$|programme$|events?$)$',
    re.I,
)

# Textes de heading qui ressemblent à des dates (à ne pas prendre comme titre)
_DATE_HEADING_RE = re.compile(
    r'^(jusqu|du\b|le\b|au\b|\d{1,2}\s|[\d/–-]+\s*(jan|fév|mar|avr|mai|juin|juil|ao|sep|oct|nov|déc))',
    re.I,
)


def _norm_date(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}', text):
        return text[:10]
    dt = dateparser.parse(text, languages=["fr"],
                          settings={"PREFER_DAY_OF_MONTH": "first"})
    return dt.strftime("%Y-%m-%d") if dt else None


def _extract_dates(el) -> tuple[str | None, str | None]:
    """Extrait (date_debut, date_fin) depuis un élément BS4."""
    # 1. Balises <time datetime="...">
    time_els = el.find_all("time")
    iso_dates = [t.get("datetime", "")[:10] for t in time_els if t.get("datetime")]
    if len(iso_dates) >= 2:
        return iso_dates[0], iso_dates[-1]
    if len(iso_dates) == 1:
        return iso_dates[0], None

    text = el.get_text(" ", strip=True)

    # 2. Deux dates complètes (day month year)
    matches = _DATE_RE.findall(text)
    if len(matches) >= 2:
        def to_iso(m):
            return _norm_date(f"{m[0]} {m[1]} {m[2]}")
        return to_iso(matches[0]), to_iso(matches[-1])

    # 3. Plage partielle : "29 avril – 16 août 2026" (seule la 2e date a l'année)
    pm = _DATE_RANGE_PARTIAL_RE.search(text)
    if pm:
        day1, mon1, day2, mon2, year = pm.group(1), pm.group(2), pm.group(3), pm.group(4), pm.group(5)
        y = int(year)
        m1 = _MONTH_NUM.get(mon1.lower().replace("é","e").replace("û","u").replace("ô","o"), 1)
        m2 = _MONTH_NUM.get(mon2.lower().replace("é","e").replace("û","u").replace("ô","o"), 1)
        # Cross-year range: "15 novembre – 12 mars 2026" → début en 2025
        year1 = y - 1 if m1 > m2 else y
        debut = _norm_date(f"{day1} {mon1} {year1}")
        fin   = _norm_date(f"{day2} {mon2} {year}")
        return debut, fin

    # 4. Une seule date complète
    if matches:
        def to_iso(m):
            return _norm_date(f"{m[0]} {m[1]} {m[2]}")
        return to_iso(matches[0]), None

    return None, None


def _best_title(el) -> str | None:
    """Retourne le meilleur titre de l'élément : heading non-date, non-nav."""
    for h in el.find_all(["h1", "h2", "h3", "h4", "h5"]):
        text = h.get_text(strip=True)
        if len(text) < 5:
            continue
        if _DATE_HEADING_RE.search(text):
            continue
        if _SKIP_TITLE_RE.search(text):
            continue
        return text
    return None


def _parse_generic(soup: BeautifulSoup, agenda_url: str) -> list[dict]:
    """
    Parser générique multi-patterns.
    Priorité : <article> → <section|div|li> avec classes expo/card/item/program
    Ignore les headings qui ressemblent à des dates ou à du nav.
    """
    results: list[dict] = []
    seen: set[str] = set()

    candidates = list(soup.find_all("article"))
    for tag in ["section", "div", "li"]:
        candidates += soup.find_all(
            tag,
            class_=re.compile(r"expo|exhibit|card|item|program|event", re.I),
        )

    for el in candidates:
        titre = _best_title(el)
        if not titre or titre in seen:
            continue
        seen.add(titre)

        link = el.find("a", href=True)
        url = None
        if link:
            href = link["href"]
            url = href if href.startswith("http") else urljoin(agenda_url, href)

        date_debut, date_fin = _extract_dates(el)

        results.append({
            "titre":      titre,
            "date_debut": date_debut,
            "date_fin":   date_fin,
            "url":        url or agenda_url,
            "statut":     "en_cours",
        })

    logger.debug("[museum_events] _parse_generic → %d candidats", len(results))
    return results


def _parse_marmottan(soup: BeautifulSoup, agenda_url: str) -> list[dict]:
    """Parser spécifique Marmottan : section.MMM_BLOC > div.MMM_BLOC_TEXT."""
    results: list[dict] = []
    for section in soup.find_all("section", class_=re.compile(r"MMM_BLOC", re.I)):
        surtitle = section.find(class_=re.compile(r"SURTITLE", re.I))
        if not surtitle or "exposition" not in surtitle.get_text(strip=True).lower():
            continue
        h2 = section.find("h2")
        if not h2:
            continue
        titre = h2.get_text(strip=True)
        if len(titre) < 5:
            continue
        subtitle = section.find(class_=re.compile(r"SUBTITLE", re.I))
        date_debut, date_fin = _extract_dates(subtitle) if subtitle else (None, None)
        link = section.find("a", href=True)
        url = link["href"] if link else agenda_url
        if url and not url.startswith("http"):
            url = urljoin(agenda_url, url)
        results.append({
            "titre": titre, "date_debut": date_debut,
            "date_fin": date_fin, "url": url, "statut": "en_cours",
        })
    return results


# Dispatch : domain → parser spécifique (None = générique)
_SPECIFIC_PARSERS: dict[str, callable] = {
    "marmottan.fr": _parse_marmottan,
}


def _parse_page(soup: BeautifulSoup, agenda_url: str, website: str) -> list[dict]:
    domain = urlparse(website).netloc.removeprefix("www.")
    parser = _SPECIFIC_PARSERS.get(domain, _parse_generic)
    return parser(soup, agenda_url)


# ── Throttle DB ───────────────────────────────────────────────────────────────

def _recently_scraped(museum_name: str, hours: int = THROTTLE_HOURS) -> bool:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import db
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    with db._conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM museum_scrape_log WHERE museum_name=? AND scraped_at>=? LIMIT 1",
            (museum_name, cutoff),
        ).fetchone()
    return row is not None


def _is_recent_or_current(date_debut: str | None, statut: str) -> bool:
    if statut == "en_cours":
        return True
    if not date_debut:
        return False
    try:
        dt = datetime.strptime(date_debut, "%Y-%m-%d")
        return dt >= datetime.now() - timedelta(days=DAYS_CUTOFF)
    except ValueError:
        return False


# ── Scraping principal ────────────────────────────────────────────────────────

async def _scrape_async(lat: float, lng: float, radius_m: int) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    all_expos: list[dict] = []

    museums = resolve_museums_from_osm(lat, lng, radius_m)
    if not museums:
        return []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="fr-FR",
        )
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        for museum in museums:
            nom     = museum["nom"]
            website = museum["website"]
            m_lat   = museum["lat"]
            m_lng   = museum["lng"]

            if _recently_scraped(nom):
                logger.info("[museum_events] %s — skip (scrapé < %dh)", nom, THROTTLE_HOURS)
                continue

            # URL agenda : connue ou découverte
            agenda_url = _known_agenda_url(website)
            if agenda_url:
                logger.info("[museum_events] %s → agenda (config) : %s", nom, agenda_url)
            else:
                agenda_url = await find_agenda_url(page, website)

            if not agenda_url:
                logger.info("[museum_events] %s — pas d'URL agenda", nom)
                continue

            try:
                resp = await page.goto(agenda_url, wait_until="domcontentloaded", timeout=25_000)
                if not resp or resp.status >= 400:
                    logger.warning("[museum_events] %s → HTTP %s", nom, getattr(resp, "status", "?"))
                    continue
                await page.wait_for_timeout(1500)
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 1500)")
                    await page.wait_for_timeout(300)
                html = await page.content()
            except Exception:
                logger.exception("[museum_events] Erreur fetch %s", nom)
                continue

            soup  = BeautifulSoup(html, "html.parser")
            expos = _parse_page(soup, agenda_url, website)
            logger.info("[museum_events] %s : %d expos parsées", nom, len(expos))

            # Log la tentative (expo_count = max historique → distingue "parser OK" de "parser KO")
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent.parent))
            import db as _db
            _db.log_museum_scrape(nom, len(expos))

            kept = 0
            for expo in expos:
                statut     = expo.get("statut", "en_cours")
                date_debut = expo.get("date_debut")
                if not _is_recent_or_current(date_debut, statut):
                    continue
                all_expos.append({
                    "museum_name": nom,
                    "museum_lat":  m_lat,
                    "museum_lng":  m_lng,
                    "expo_titre":  expo["titre"],
                    "expo_url":    expo["url"],
                    "date_debut":  date_debut,
                    "date_fin":    expo.get("date_fin"),
                    "source":      "generic_parser",
                })
                kept += 1

            logger.info("[museum_events] %s : %d/%d expos retenues", nom, kept, len(expos))
            await asyncio.sleep(2)

        await browser.close()

    logger.info("[museum_events] Total : %d expos", len(all_expos))
    return all_expos


class MuseumEventsScraper(BaseScraper):
    name     = "museum_events"
    base_url = "https://overpass-api.de"

    def scrape(self, lat: float = 48.8566, lng: float = 2.3522, radius_m: int = 5000) -> list[dict]:
        return asyncio.run(_scrape_async(lat, lng, radius_m))

    def run(self, lat: float = 48.8566, lng: float = 2.3522, radius_m: int = 5000) -> int:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        import db

        logger.info("[museum_events] Début (lat=%.4f lng=%.4f r=%dm)", lat, lng, radius_m)
        try:
            expos = self.scrape(lat, lng, radius_m)
        except Exception:
            logger.exception("[museum_events] scrape() a planté")
            return 0

        inserted = 0
        for ex in expos:
            if db.insert_museum_event(ex):
                inserted += 1
        logger.info("[museum_events] Terminé : %d/%d insérées", inserted, len(expos))
        return inserted
