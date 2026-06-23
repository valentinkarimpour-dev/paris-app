"""
Extraction des expos depuis HTML — sans LLM, via BS4 + regex.
Retourne des dicts avec confidence="high"|"low".
"""

import re
from datetime import datetime, timedelta

import dateparser
from bs4 import BeautifulSoup

MOIS_FR = [
    "janvier", "février", "fevrier", "mars", "avril", "mai", "juin",
    "juillet", "août", "aout", "septembre", "octobre", "novembre",
    "décembre", "decembre",
]
_MOIS_PAT = "|".join(MOIS_FR)

_FULL_DATE_RE = re.compile(
    rf"(\d{{1,2}})\s+({_MOIS_PAT})\s+(\d{{4}})", re.I
)
_RANGE_RE = re.compile(
    rf"du\s+(\d{{1,2}})\s+(?:(\w+)\s+)?au\s+(\d{{1,2}})\s+({_MOIS_PAT})(?:\s+(\d{{4}}))?",
    re.I,
)
_UNTIL_RE = re.compile(
    rf"jusqu'au\s+(\d{{1,2}})\s+({_MOIS_PAT})(?:\s+(\d{{4}}))?", re.I
)
_TIME_TAG_RE = re.compile(r'datetime=["\'](\d{4}-\d{2}-\d{2})')

_EXPO_HEADING_RE = re.compile(
    r"(?:exposition|exhibition|expo)\s*[:\-–]\s*(.{5,80})", re.I
)
_CURRENT_RE = re.compile(
    r"(?:en ce moment|currently|on view|actuellement)\s*[:\-–]?\s*(.{5,80})", re.I
)
_EXPO_CLASS_RE = re.compile(
    r"expo|exhibition|current|en-cours|ongoing|title|heading|programme", re.I
)
_DATE_HEADING_RE = re.compile(
    r"^(jusqu|du\b|le\b|au\b|\d{1,2}\s|[\d/–-]+\s*(jan|fév|mar|avr|mai|juin|juil|ao|sep|oct|nov|déc))",
    re.I,
)
_SKIP_RE = re.compile(
    r"cookie|newsletter|navigation|accueil|contact|menu|horaires|tarif|billetterie|abonnement",
    re.I,
)


def _norm_date(text: str) -> str | None:
    if not text:
        return None
    text = text.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    dt = dateparser.parse(text, languages=["fr"], settings={
        "PREFER_DAY_OF_MONTH": "first",
        "PREFER_DATES_FROM": "current_period",
        "RETURN_AS_TIMEZONE_AWARE": False,
    })
    return dt.strftime("%Y-%m-%d") if dt else None


def _extract_dates_from_text(text: str) -> tuple[str | None, str | None]:
    # 1. Balises <time datetime="...">
    iso = _TIME_TAG_RE.findall(text)
    if len(iso) >= 2:
        return iso[0], iso[-1]
    if len(iso) == 1:
        return iso[0], None

    # 2. "du X au Y mois année"
    m = _RANGE_RE.search(text)
    if m:
        year = m.group(5) or str(datetime.now().year)
        mon_debut = m.group(2) or m.group(4)
        debut = _norm_date(f"{m.group(1)} {mon_debut} {year}")
        fin   = _norm_date(f"{m.group(3)} {m.group(4)} {year}")
        return debut, fin

    # 3. "jusqu'au X mois" — sémantique explicite de fin : priorité sur _FULL_DATE_RE
    m = _UNTIL_RE.search(text)
    if m:
        year = m.group(3) or str(datetime.now().year)
        return None, _norm_date(f"{m.group(1)} {m.group(2)} {year}")

    # 4. Deux dates complètes ou une seule
    matches = _FULL_DATE_RE.findall(text)
    if len(matches) >= 2:
        return (_norm_date(f"{matches[0][0]} {matches[0][1]} {matches[0][2]}"),
                _norm_date(f"{matches[-1][0]} {matches[-1][1]} {matches[-1][2]}"))
    if matches:
        return _norm_date(f"{matches[0][0]} {matches[0][1]} {matches[0][2]}"), None

    return None, None


def _is_relevant(date_debut: str | None, date_fin: str | None) -> bool:
    today = datetime.now()
    if date_fin:
        try:
            if datetime.strptime(date_fin, "%Y-%m-%d") < today:
                return False   # expo terminée
        except ValueError:
            pass
    if date_debut:
        try:
            if datetime.strptime(date_debut, "%Y-%m-%d") > today + timedelta(days=30):
                return False   # annonce trop lointaine
        except ValueError:
            pass
    return True


def _best_heading(el) -> str | None:
    for h in el.find_all(["h1", "h2", "h3", "h4", "h5"]):
        text = h.get_text(strip=True)
        if len(text) < 5:
            continue
        if _DATE_HEADING_RE.search(text) or _SKIP_RE.search(text):
            continue
        return text
    return None


def extract_expos_from_html(html: str, url_source: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    scope = soup.find("main") or soup.find("article") or soup.find("body") or soup
    text  = scope.get_text(" ", strip=True)

    results: list[dict] = []
    seen: set[str] = set()

    def _add(titre, date_debut, date_fin, confidence):
        titre = titre.strip().rstrip(".,;")
        if len(titre) < 5 or titre in seen or _SKIP_RE.search(titre):
            return
        seen.add(titre)
        results.append({
            "titre":      titre,
            "artiste":    None,
            "date_debut": date_debut,
            "date_fin":   date_fin,
            "url":        url_source,
            "confidence": confidence,
        })

    # Stratégie A — pattern explicite "Exposition : X" / "En ce moment : X"
    for pattern in [_EXPO_HEADING_RE, _CURRENT_RE]:
        for m in pattern.finditer(text):
            titre = m.group(1)
            ctx   = text[m.start(): m.start() + 500]
            d, f  = _extract_dates_from_text(ctx)
            _add(titre, d, f, "high")

    # Stratégie B — éléments avec classes expo/exhibition/...
    for el in scope.find_all(class_=_EXPO_CLASS_RE):
        titre = _best_heading(el)
        if not titre:
            continue
        el_text   = el.get_text(" ", strip=True)
        d, f      = _extract_dates_from_text(el_text)
        confidence = "high" if (d or f) else "low"
        _add(titre, d, f, confidence)

    # Stratégie C — h1/h2/h3 avec date dans les siblings suivants
    for h in scope.find_all(["h1", "h2", "h3"]):
        titre = h.get_text(strip=True)
        if len(titre) < 5 or _SKIP_RE.search(titre) or _DATE_HEADING_RE.search(titre):
            continue
        # Contexte : les 2 siblings suivants (contiennent les balises <time> et le texte de date)
        ctx_parts: list[str] = []
        sib = h.find_next_sibling()
        if sib:
            ctx_parts.append(str(sib))
            sib2 = sib.find_next_sibling()
            if sib2:
                ctx_parts.append(str(sib2))
        if not ctx_parts:
            continue
        ctx  = " ".join(ctx_parts)
        d, f = _extract_dates_from_text(ctx)
        if d or f:   # n'ajouter que si on a trouvé une date
            _add(titre, d, f, "high")

    filtered = [r for r in results if _is_relevant(r["date_debut"], r["date_fin"])]
    return filtered[:5]
