"""
DoItInParis scraper — que faire à Paris (guides mensuels/hebdo)
Structure : articles pérennes mis à jour chaque semaine/mois.
Chaque section div.title-article = 1 événement.

LLM (extract_list_with_llm, 1-2 appels/article) → titre, adresse, catégorie.
Regex sur balises <em> → date_debut, date_fin, duree_jours (déterministe, sans LLM).
Fusion par index de section.
"""

import asyncio
import logging
import re
from datetime import date, datetime

from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_list_with_llm

logger = logging.getLogger(__name__)

BASE = "https://www.doitinparis.com"

ARTICLE_URLS = [
    f"{BASE}/fr/que-faire-a-paris-week-end-24566",
    f"{BASE}/fr/que-faire-a-paris-en-ce-moment-26091",
]

_SKIP_HEADINGS = {
    "et toujours...", "en ce moment à paris", "à lire aussi",
    "à voir aussi", "notre sélection", "les bons plans",
}

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# "du 9 au 30 juin 2026" — mois partagé, après le 2e jour
_RE_SAME = re.compile(
    r"du\s+(\d+)\w*\s+au\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
# "du 14 avril au 20 septembre [2026]" — mois différents
_RE_DIFF = re.compile(
    r"du\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?\s+au\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
# "jusqu'au 26 juillet [2026]"
_RE_JUSQU = re.compile(
    r"jusqu['']?au\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
# "le 21 juin [2026]" — événement d'un jour
_RE_LE = re.compile(
    r"\ble\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
# "les 19, 20 et 21 juin 2026" — plage implicite (premier + dernier jour)
_RE_LES = re.compile(
    r"\bles?\s+(\d+)(?:\w*[\s,]+\d+\w*[\s,]+(?:et\s+)?)(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
    re.IGNORECASE,
)


def _parse_date(jour: str, mois_str: str, annee: str | None) -> str | None:
    m = MOIS.get(mois_str.lower())
    if not m:
        return None
    y = int(annee) if annee and annee.isdigit() else date.today().year
    try:
        return datetime(y, m, int(jour)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _dates_from_em(em_texts: list[str]) -> tuple[str | None, str | None, int | None]:
    """Extrait (date_debut, date_fin, duree_jours) depuis les textes italiques."""
    combined = " ".join(em_texts)

    # "du 9 au 30 juin 2026" (mois partagé)
    m = _RE_SAME.search(combined)
    if m:
        j1, j2, mois, an = m.groups()
        d1, d2 = _parse_date(j1, mois, an), _parse_date(j2, mois, an)
        if d1 and d2:
            delta = (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
            return d1, d2, delta if delta > 0 else None
        return d1, d2, None

    # "du 14 avril au 20 septembre" (mois différents, vérifiés dans MOIS)
    m = _RE_DIFF.search(combined)
    if m:
        j1, mois1, an1, j2, mois2, an2 = m.groups()
        if mois1.lower() in MOIS and mois2.lower() in MOIS:
            if not an2:
                an2 = an1
            d1, d2 = _parse_date(j1, mois1, an1), _parse_date(j2, mois2, an2)
            if d1 and d2:
                delta = (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
                return d1, d2, delta if delta > 0 else None
            return d1, d2, None

    # "jusqu'au 26 juillet" → date_fin seulement
    m = _RE_JUSQU.search(combined)
    if m:
        j, mois_str, an = m.groups()
        d_fin = _parse_date(j, mois_str, an)
        if d_fin:
            return None, d_fin, None

    # "les 19, 20 et 21 juin 2026" → premier + dernier jour
    m = _RE_LES.search(combined)
    if m:
        j1, j2, mois, an = m.groups()
        if mois.lower() in MOIS:
            d1, d2 = _parse_date(j1, mois, an), _parse_date(j2, mois, an)
            if d1 and d2:
                delta = (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
                return d1, d2, delta if delta > 0 else 1

    # "le 21 juin" → événement d'un seul jour
    m = _RE_LE.search(combined)
    if m:
        j, mois_str, an = m.groups()
        if mois_str.lower() in MOIS:
            d = _parse_date(j, mois_str, an)
            if d:
                return d, d, 1

    return None, None, None


def _normalize_date(d: str | None) -> str | None:
    if not d:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m"):
        try:
            return datetime.strptime(d.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return d if re.match(r"\d{4}-\d{2}-\d{2}", d or "") else None


def _slugify(titre: str) -> str:
    s = titre.lower()
    for src, dst in [("à","a"),("â","a"),("é","e"),("è","e"),("ê","e"),
                     ("î","i"),("ô","o"),("ù","u"),("û","u"),("ç","c")]:
        s = s.replace(src, dst)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


async def _extract_article(page, base_url: str, scrape_date: str) -> list[dict]:
    try:
        resp = await page.goto(base_url, wait_until="domcontentloaded", timeout=25_000)
        if not resp or resp.status >= 400:
            return []
        await page.wait_for_timeout(2000)
        for _ in range(10):
            await page.evaluate("window.scrollBy(0, 1500)")
            await page.wait_for_timeout(300)

        image_url = await page.evaluate(
            "() => document.querySelector('meta[property=\"og:image\"]')?.content"
        )

        sections = await page.evaluate("""() => {
            const results = [];
            const firstSection = document.querySelector('div.title-article');
            if (!firstSection) return results;
            const container = firstSection.parentElement;
            let current = null;
            for (const el of container.children) {
                if (el.classList && el.classList.contains('title-article')) {
                    if (current) results.push(current);
                    current = { heading: el.innerText.trim(), body_text: '', em_infos: [] };
                } else if (current && el.tagName === 'P') {
                    const bodyT = el.innerText?.trim();
                    if (bodyT) current.body_text += bodyT + ' ';

                    // <em> contenant adresse ou date
                    el.querySelectorAll('em').forEach(em => {
                        const t = em.innerText?.trim();
                        if (!t || t.startsWith('©') || t.length < 6) return;
                        const hasAddr = /rue|avenue|boulevard|place|quai|Paris/i.test(t);
                        const hasDate = /du \\d|jusqu|ouvert|juin|juillet|août|mai|avril|mars|septembre/i.test(t);
                        if (hasAddr || hasDate) current.em_infos.push(t);
                    });
                }
            }
            if (current) results.push(current);
            return results;
        }""")
    except Exception:
        logger.exception("[doitinparis] erreur chargement %s", base_url)
        return []

    if not sections:
        logger.warning("[doitinparis] aucune section dans %s", base_url)
        return []

    # Filtre les sections sans contenu utile
    sections = [
        s for s in sections
        if s.get("heading") and s["heading"].lower() not in _SKIP_HEADINGS
        and (s.get("body_text") or s.get("em_infos"))
    ]

    # Construit le texte structuré pour le LLM (titre + adresse + catégorie)
    year = date.today().year
    year_header = f"[Article Paris {year} — les dates sans année sont en {year}]\n\n"

    # Envoie en chunks de ~3500 chars
    chunks: list[tuple[int, int]] = []   # (start_idx, end_idx) par chunk
    chunk_texts: list[str] = []
    chunk_buf = year_header
    chunk_start = 0

    for i, sec in enumerate(sections):
        sec_text = f"=== {sec['heading']} ===\n{(sec.get('body_text') or '')[:600]}\n\n"
        if len(chunk_buf) + len(sec_text) > 3500 and i > chunk_start:
            chunks.append((chunk_start, i))
            chunk_texts.append(chunk_buf)
            chunk_buf = year_header + sec_text
            chunk_start = i
        else:
            chunk_buf += sec_text

    if chunk_buf != year_header:
        chunks.append((chunk_start, len(sections)))
        chunk_texts.append(chunk_buf)

    # Appels LLM (1-2 par article)
    llm_events_ordered: list[dict | None] = [None] * len(sections)
    for (start, end), text in zip(chunks, chunk_texts):
        batch = extract_list_with_llm(text)
        n_expected = end - start
        if len(batch) != n_expected:
            logger.warning(
                "[doitinparis] chunk %d-%d : %d sections → %d events LLM",
                start, end, n_expected, len(batch),
            )
        for offset, ev in enumerate(batch[:n_expected]):
            llm_events_ordered[start + offset] = ev

    # Fusionne LLM + em-dates par index
    events = []
    for sec, llm_ev in zip(sections, llm_events_ordered):
        heading  = sec["heading"]
        em_infos = sec.get("em_infos", [])

        # Dates déterministes : em_infos d'abord, puis corps du texte en fallback
        date_debut, date_fin, duree_jours = _dates_from_em(em_infos)
        if not date_debut and not date_fin:
            body = sec.get("body_text") or ""
            date_debut, date_fin, duree_jours = _dates_from_em([body[:2000]])

        # "jusqu'au" : date_fin sans date_debut → date_debut = scrape_date
        if date_fin and not date_debut:
            date_debut = scrape_date

        # Fallback LLM si regex n'a rien trouvé
        if not date_debut and llm_ev:
            date_debut = _normalize_date(llm_ev.get("date_debut"))
        if not duree_jours and llm_ev:
            duree_jours = llm_ev.get("duree_jours")

        titre    = (llm_ev or {}).get("titre") or heading.title()
        adresse  = (llm_ev or {}).get("adresse") or ""
        categorie = (llm_ev or {}).get("categorie") or "autre"
        description = (llm_ev or {}).get("description") or (sec.get("body_text") or "")[:300]

        events.append({
            "titre":       titre,
            "description": description[:300],
            "adresse":     adresse,
            "date_debut":  date_debut,
            "date_fin":    date_fin,
            "duree_jours": duree_jours,
            "categorie":   categorie,
            "source":      "doitinparis",
            "url":         f"{base_url}#{_slugify(heading)}",
            "image_url":   image_url,
        })

    logger.info("[doitinparis] %s → %d événements", base_url.split("/")[-1], len(events))
    return events


async def _scrape_async() -> list[dict]:
    scrape_date = date.today().strftime("%Y-%m-%d")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        all_events = []
        for url in ARTICLE_URLS:
            events = await _extract_article(page, url, scrape_date)
            all_events.extend(events)

        await browser.close()

    logger.info("[doitinparis] total : %d événements", len(all_events))
    return all_events


class DoItInParis(BaseScraper):
    name = "doitinparis"
    base_url = BASE

    def scrape(self) -> list[dict]:
        return asyncio.run(_scrape_async())
