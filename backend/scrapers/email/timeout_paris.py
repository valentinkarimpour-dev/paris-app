"""
TimeOut Paris — newsletter éditoriale
Stratégie :
  1. Lit les emails IMAP de timeout.com
  2. Extrait tous les liens qui redirigent vers timeout.fr/paris/actualites/
  3. Pour chaque article :
       - Si pas de balises OÙ ? / QUAND ? → ignoré
       - Si article multi-expos (plusieurs H2 + OÙ/QUAND) → N événements
       - Sinon → 1 événement, titre/description via LLM (H1 + chapô + corps)
  4. Adresse et dates extraites depuis les blocs OÙ/QUAND (regex, pas LLM)
"""

import asyncio
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm
from utils.email_reader import fetch_emails

logger = logging.getLogger(__name__)

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}


def _parse_date(j, m, a=None):
    mo = MOIS.get(m.lower())
    if not mo:
        return None
    y = int(a) if a and a.isdigit() else date.today().year
    try:
        return datetime(y, mo, int(j)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _last_day_of_month(mo, y=None):
    import calendar
    y = y or date.today().year
    return calendar.monthrange(y, mo)[1]


def _parse_quand(text):
    """Retourne (date_debut, date_fin, duree_jours) depuis un texte QUAND."""
    today = date.today().strftime("%Y-%m-%d")
    text = text.replace("\xa0", " ")

    # Pré-calcul : "fin du mois" → dernier jour du mois cité (ou mois courant)
    fin_du_mois = None
    if re.search(r"fin du mois", text, re.I):
        mois_pattern = "|".join(re.escape(k) for k in MOIS)
        m_mois = re.search(r"\b(" + mois_pattern + r")\b", text, re.I)
        mo = MOIS[m_mois.group(1).lower()] if m_mois else date.today().month
        y = date.today().year
        fin_du_mois = datetime(y, mo, _last_day_of_month(mo, y)).strftime("%Y-%m-%d")

    # "du X mois1 au Y mois2 [YYYY]"
    m = re.search(
        r"du\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?\s+au\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
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

    # "du X au Y mois [YYYY]" (même mois)
    m = re.search(
        r"du\s+(\d+)\w*\s+au\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
        text, re.I,
    )
    if m:
        j1, j2, mois, an = m.groups()
        if mois.lower() in MOIS:
            d1, d2 = _parse_date(j1, mois, an), _parse_date(j2, mois, an)
            if d1 and d2:
                delta = (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
                return d1, d2, delta if delta > 0 else None

    # "jusqu'au X mois [YYYY]"
    m = re.search(r"jusqu[''']?au\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?", text, re.I)
    if m:
        j, mois, an = m.groups()
        d2 = _parse_date(j, mois, an)
        if d2:
            delta = (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days
            return today, d2, delta if delta > 0 else None

    # "le X mois [YYYY]" (jour unique)
    m = re.search(r"\ble\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?", text, re.I)
    if m:
        j, mois, an = m.groups()
        if mois.lower() in MOIS:
            d = _parse_date(j, mois, an)
            if d:
                return d, d, 1

    # "du X mois [YYYY]" — date de début, fin_du_mois si présent
    m = re.search(r"\bdu\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?", text, re.I)
    if m:
        j, mois, an = m.groups()
        if mois.lower() in MOIS:
            d1 = _parse_date(j, mois, an)
            if d1:
                d2 = fin_du_mois
                if d1 and d2:
                    delta = (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
                    return d1, d2, delta if delta > 0 else None
                return d1, None, None

    # Seulement "fin du mois" sans date de début explicite
    if fin_du_mois:
        delta = (datetime.strptime(fin_du_mois, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days
        return today, fin_du_mois, delta if delta > 0 else None

    return None, None, None


def _parse_bloc(text):
    """Extrait (adresse, date_debut, date_fin, duree_jours) depuis un texte OÙ/QUAND."""
    text = text.replace("\xa0", " ")
    adresse, quand_raw = "", ""

    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        # OÙ et QUAND sur la même ligne
        if "Où ?" in line and "Quand ?" in line:
            parts = line.split("Quand ?", 1)
            ou_part = parts[0].replace("Où ?", "").strip().strip(".")
            if ou_part:
                adresse = ou_part
            quand_raw = parts[1].strip()
        elif "Où ?" in line:
            val = line.replace("Où ?", "").strip().strip(".")
            if val:
                adresse = val
        elif "Quand ?" in line:
            val = line.replace("Quand ?", "").strip()
            if val:
                quand_raw = val

    date_debut, date_fin, duree_jours = _parse_quand(quand_raw)
    return adresse.strip(". "), date_debut, date_fin, duree_jours


def _ou_quand_bloc(nodes, start=0, stop=None):
    """
    Combine les nœuds contenant OÙ ou QUAND entre start et stop.
    Retourne (bloc_text, has_quand).
    """
    if stop is None:
        stop = len(nodes)
    lines = [n["text"] for n in nodes[start:stop] if "Où ?" in n["text"] or "Quand ?" in n["text"]]
    bloc = "\n".join(lines)
    return bloc, "Quand ?" in bloc


async def _extract_article(page, url):
    """
    Charge un article timeout.fr et retourne la liste des événements extraits.
    Retourne [] si pas de balise OÙ/QUAND ou si URL non pertinente.
    """
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        if not resp or resp.status >= 400:
            return []
        await page.wait_for_timeout(1500)
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(400)
    except Exception:
        logger.debug("[timeout] erreur chargement %s", url)
        return []

    final_url = page.url
    if "timeout.fr/paris" not in final_url:
        return []

    # Collecte des nœuds feuilles dans l'ordre DOM
    nodes = await page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('h1, h2, h3, p, span, time, div').forEach(el => {
            if (el.querySelector('h1,h2,h3,p,div')) return;
            const t = (el.innerText || '').trim();
            if (!t || t.length < 8) return;
            if (t.startsWith('window.') || t.startsWith('{"')) return;
            out.push({ tag: el.tagName, text: t });
        });
        return out;
    }""")

    has_quand = any("Quand ?" in n["text"] for n in nodes)
    if not has_quand:
        logger.debug("[timeout] pas de QUAND : %s", final_url)
        return []

    # Positions des H2 dans nodes
    h2_positions = [i for i, n in enumerate(nodes) if n["tag"] == "H2" and len(n["text"]) > 5]

    # Multi-expos : au moins 3 H2 dont chacun a un bloc QUAND associé
    if len(h2_positions) >= 3:
        confirmed = 0
        for idx, pos in enumerate(h2_positions):
            next_pos = h2_positions[idx + 1] if idx + 1 < len(h2_positions) else len(nodes)
            _, found = _ou_quand_bloc(nodes, pos + 1, next_pos)
            if found:
                confirmed += 1
        if confirmed >= 3:
            return _extract_multi(nodes, h2_positions, final_url)

    return await _extract_single(page, nodes, final_url)


def _extract_multi(nodes, h2_positions, url):
    """Article multi-expos : un événement par H2 ayant un bloc OÙ/QUAND."""
    events = []
    for idx, pos in enumerate(h2_positions):
        h2_text = nodes[pos]["text"].replace("\xa0", " ")
        lc = h2_text.rfind(",")
        titre = h2_text[:lc].strip() if lc > 0 else h2_text.strip()
        if not titre:
            continue

        next_pos = h2_positions[idx + 1] if idx + 1 < len(h2_positions) else len(nodes)
        bloc, found = _ou_quand_bloc(nodes, pos + 1, next_pos)
        if not found:
            continue

        adresse, date_debut, date_fin, duree_jours = _parse_bloc(bloc)
        events.append({
            "titre":       titre,
            "description": "",
            "adresse":     adresse,
            "date_debut":  date_debut,
            "date_fin":    date_fin,
            "duree_jours": duree_jours,
            "categorie":   "exposition",
            "source":      "timeout_paris",
            "url":         url,
        })

    logger.info("[timeout] multi-expos %s → %d événements", url.split("/")[-1][:50], len(events))
    return events


async def _extract_single(page, nodes, url):
    """Article événement unique : LLM pour titre/description, OÙ/QUAND pour adresse/dates."""
    # H1
    h1 = next((n["text"] for n in nodes if n["tag"] == "H1"), "")

    # Chapô : premier P
    chapo = next((n["text"] for n in nodes if n["tag"] == "P" and len(n["text"]) > 20), "")

    # Corps : texte brut entre la légende photo et OÙ/QUAND (via body.innerText)
    raw_body = await page.evaluate("() => document.body.innerText")
    corps = ""
    if h1 and h1 in raw_body:
        after_h1 = raw_body[raw_body.index(h1) + len(h1):]
        # Coupe avant OÙ ? ou Quand ?
        cut = re.search(r"Où \?|Quand \?", after_h1)
        if cut:
            after_h1 = after_h1[: cut.start()]
        # Retire les lignes courtes (crédits, navigation, date)
        paras = [l.strip() for l in after_h1.splitlines() if len(l.strip()) > 40]
        corps = " ".join(paras[:6])

    context = f"Titre : {h1}\nSous-titre : {chapo}\nCorps : {corps[:800]}"
    llm = extract_with_llm(context)

    titre = llm.get("titre") or h1
    description = llm.get("description") or chapo
    categorie = llm.get("categorie") or "autre"

    # OÙ/QUAND : combine tous les nœuds portant ces marqueurs
    bloc, found = _ou_quand_bloc(nodes)
    if not found:
        return []

    adresse, date_debut, date_fin, duree_jours = _parse_bloc(bloc)

    return [{
        "titre":       titre,
        "description": description,
        "adresse":     adresse,
        "date_debut":  date_debut,
        "date_fin":    date_fin,
        "duree_jours": duree_jours,
        "categorie":   categorie,
        "source":      "timeout_paris",
        "url":         url,
    }]


def _extract_links(html):
    """Extrait les liens timeout depuis le HTML d'un email."""
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "timeout" in href and "unsubscribe" not in href.lower():
            links.add(href)
    return links


async def _scrape_async(emails):
    all_events = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="fr-FR",
        )
        await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
        page = await ctx.new_page()

        seen_urls = set()
        for em in emails:
            html = em.get("html") or ""
            if not html:
                continue
            links = _extract_links(html)
            for link in links:
                events = await _extract_article(page, link)
                for ev in events:
                    final = ev["url"]
                    if final not in seen_urls:
                        seen_urls.add(final)
                        all_events.append(ev)

        await browser.close()

    return all_events


class TimeOutParis(BaseScraper):
    name = "timeout_paris"
    base_url = "https://www.timeout.fr/paris"

    def scrape(self) -> list[dict]:
        emails = fetch_emails("timeout.com", max_count=30)
        if not emails:
            logger.warning("[timeout_paris] aucun email récupéré")
            return []

        events = asyncio.run(_scrape_async(emails))
        logger.info("[timeout_paris] %d événements extraits", len(events))
        return events
