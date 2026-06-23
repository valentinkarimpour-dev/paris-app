"""
Numero Popup scraper — pop-up stores parisiens identifiés dans Numéro magazine
Source : https://numero.com/?s=pop-up&post_type[]=post
Ouvre le dernier article en date chaque jour.
Deux types :
  - Article liste : paragraphes "L'adresse ? Pop-up Name, dates, adresse."
  - Article single : dernier <em> contenant "Pop-up Name, dates, adresse."
Extraction structurelle (regex) — pas de LLM.
"""

import logging
import re
import unicodedata
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup

from ..base import BaseScraper

logger = logging.getLogger(__name__)

BASE         = "https://numero.com"
LISTING_URL  = f"{BASE}/?s=pop-up&post_type%5B%5D=post&post_type%5B%5D=contributor&post_type%5B%5D=portrait"

_ARR_TO_CP = {str(i): f"750{i:02d}" for i in range(1, 21)}

def _normalize_adresse(addr: str) -> str:
    """Convertit 'paris 3 ème' / 'paris 3ème' / 'paris 3e' → '75003 Paris'."""
    if not addr:
        return addr
    def replace_arr(m):
        n = m.group(1).lstrip("0") or "0"
        cp = _ARR_TO_CP.get(n)
        return f"{cp} Paris" if cp else m.group(0)
    addr = re.sub(r"paris\s+(\d{1,2})\s*(?:ème|eme|me|er|e)\b", replace_arr, addr, flags=re.I)
    # Aussi nettoyer la virgule double éventuelle
    addr = re.sub(r",\s*,", ",", addr).strip().strip(",").strip()
    return addr


def _slugify(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    s = nfkd.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# ── Date parsing ────────────────────────────────────────────────────────────

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

# Mois abrégés (listing page)
MOIS_ABBR = {
    "jan": 1, "fév": 2, "fev": 2, "mar": 3, "avr": 4,
    "mai": 5, "juin": 6, "juil": 7, "août": 8, "aout": 8,
    "sept": 9, "sep": 9, "oct": 10, "nov": 11, "déc": 12, "dec": 12,
}

# "du 17 au 27 avril 2026"  (même mois)
_RE_SAME = re.compile(
    r"du\s+(\d+)\w*\s+au\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
    re.I,
)
# "du 11 juin au 4 juillet 2026"  (mois différents)
_RE_DIFF = re.compile(
    r"du\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?\s+au\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
    re.I,
)
# "jusqu'au 7 juin 2026"
_RE_JUSQUAU = re.compile(
    r"jusqu['’`]?au\s+(\d+)\w*\s+(\w+)(?:\s+(\d{4}))?",
    re.I,
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


def _parse_article_date(text: str) -> str | None:
    """Parse une date d'article comme '18 avr 2026' ou '9 juin 2026'."""
    text = text.strip()
    m = re.match(r"(\d+)\s+(\w+)\s+(\d{4})", text)
    if m:
        j, mois_str, an = m.groups()
        mo = MOIS.get(mois_str.lower()) or MOIS_ABBR.get(mois_str.lower())
        if mo:
            try:
                return datetime(int(an), mo, int(j)).strftime("%Y-%m-%d")
            except ValueError:
                pass
    return None


def _parse_info_line(line: str, article_date: str | None) -> dict | None:
    """
    Parse une ligne du type :
      "Pop-up Name, du 17 au 27 avril 2026, au 7 rue Froissard, 75003 Paris."
      "Pop-up Name, jusqu'au 7 juin 2026 à la boutique X, 84 rue Y, Paris 1er."
      "L'adresse ? Pop-up Name, du 12 au 14 juin 2026, 12 rue de Saintonge, Paris 3ème."
    Retourne {titre, date_debut, date_fin, adresse} ou None.
    """
    # Nettoyer le préfixe "L'adresse ?"
    line = re.sub(r"^l[''’]adresse\s*\?\s*", "", line.strip(), flags=re.I)
    line = line.rstrip(".")

    # Chercher le pattern de date et sa position
    date_debut = date_fin = None
    date_match = None

    m = _RE_DIFF.search(line)
    if m and MOIS.get(m.group(2).lower()) and MOIS.get(m.group(5).lower()):
        j1, mo1, an1, j2, mo2, an2 = m.groups()
        an2 = an2 or an1
        date_debut = _parse_date(j1, mo1, an1)
        date_fin   = _parse_date(j2, mo2, an2)
        date_match = m
    else:
        m = _RE_SAME.search(line)
        if m:
            j1, j2, mo, an = m.groups()
            if MOIS.get(mo.lower()):
                date_debut = _parse_date(j1, mo, an)
                date_fin   = _parse_date(j2, mo, an)
                date_match = m
        if not date_match:
            m = _RE_JUSQUAU.search(line)
            if m:
                j, mo, an = m.groups()
                if MOIS.get(mo.lower()):
                    date_fin   = _parse_date(j, mo, an)
                    date_debut = article_date  # date de l'article = date de début
                    date_match = m

    if not date_match:
        return None

    # Titre = tout avant la date, sans virgule finale
    titre_raw = line[:date_match.start()].strip().rstrip(",").strip()
    if not titre_raw:
        return None

    # Adresse = tout après la date, on retire les préfixes de liaison
    addr_raw = line[date_match.end():].strip()
    addr_raw = re.sub(r"^[,\s]+(au\s+|à\s+la\s+|à\s+|dans\s+)?", "", addr_raw, flags=re.I).strip()
    addr_raw = addr_raw.rstrip(".,").strip()
    addr_raw = _normalize_adresse(addr_raw)

    return {
        "titre":      titre_raw,
        "date_debut": date_debut,
        "date_fin":   date_fin,
        "adresse":    addr_raw,
    }


# ── Scraping ────────────────────────────────────────────────────────────────

def _get_latest_article() -> tuple[str, str] | None:
    """Retourne (url, date_str) du dernier article pop-up."""
    try:
        resp = requests.get(LISTING_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception:
        logger.exception("[numero_popup] erreur listing")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    for card in soup.find_all("div", class_=lambda c: c and "post-card" in c and "desktop" in c):
        a = card.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if not href.startswith("http"):
            href = BASE + href

        # Date dans le texte de la card
        text = card.get_text(" ", strip=True)
        # Format : "09 Mode 9 juin 2026 Les pop-up..."
        date_m = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", text)
        date_str = date_m.group(1) if date_m else ""
        return href, date_str

    return None


def _scrape_article(url: str, article_date: str | None) -> list[dict]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception:
        logger.exception("[numero_popup] erreur article %s", url)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Date de l'article (si pas récupérée depuis listing)
    if not article_date:
        time_el = soup.find("time")
        if time_el:
            article_date = _parse_article_date(time_el.get_text(strip=True))

    content = soup.find(class_="entry-content") or soup.find("article")
    if not content:
        logger.warning("[numero_popup] contenu introuvable dans %s", url)
        return []

    paras = [p.get_text(" ", strip=True) for p in content.find_all("p") if p.get_text(strip=True)]

    # ── Type liste : paragraphes "L'adresse ?" ──
    adresse_paras = [p for p in paras if re.match(r"l[''’]adresse", p, re.I)]

    if adresse_paras:
        events = []
        for para in adresse_paras:
            parsed = _parse_info_line(para, article_date)
            if parsed and parsed.get("titre"):
                events.append({**parsed, "url": url})
        logger.info("[numero_popup] article liste : %d pop-ups trouvés", len(events))
        return events

    # ── Type single : dernier <em> contenant "Pop-up" ──
    ems = [em.get_text(" ", strip=True) for em in content.find_all("em")]
    popup_ems = [e for e in ems if re.search(r"pop.?up", e, re.I) and len(e) > 20]

    if popup_ems:
        parsed = _parse_info_line(popup_ems[-1], article_date)
        if parsed and parsed.get("titre"):
            logger.info("[numero_popup] article single : %s", parsed["titre"])
            return [{**parsed, "url": url}]

    logger.info("[numero_popup] aucun pop-up identifiable dans %s", url)
    return []


class NumeroPopup(BaseScraper):
    name = "numero_popup"
    base_url = BASE

    def scrape(self) -> list[dict]:
        result = _get_latest_article()
        if not result:
            return []

        url, date_str = result
        article_date = _parse_article_date(date_str) if date_str else None
        logger.info("[numero_popup] article : %s (date=%s)", url.split("/")[-2], article_date)

        raw_events = _scrape_article(url, article_date)

        return [
            {
                "titre":       ev["titre"],
                "description": "",
                "adresse":     ev.get("adresse") or "",
                "date_debut":  ev.get("date_debut"),
                "date_fin":    ev.get("date_fin"),
                "duree_jours": None,
                "categorie":   "popup",
                "source":      "numero_popup",
                "url":         ev.get("url", url) + "#" + _slugify(ev["titre"]),
                "lat":         None,
                "lng":         None,
                "prix":        None,
            }
            for ev in raw_events
            if ev.get("titre")
        ]
