import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta

import httpx

from ..base import BaseScraper, extract_with_llm, extract_list_with_llm
import geocoder

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_RE_QUAND = re.compile(
    r'\*{1,2}Quand\s*\??\*{1,2}\s*:?\s*(.+?)(?:\n|\.?\s*\*{1,2})',
    re.I
)
_RE_OU = re.compile(
    r'\*{1,2}O[uù]\s*\??\*{1,2}\s*:?\s*(.+?)(?:\n|\.|$)',
    re.I
)


def _slugify(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    s = nfkd.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _fetch_jina(url: str) -> str:
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                f"https://r.jina.ai/{url}",
                headers={"Accept": "text/markdown"}
            )
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text
    except Exception as e:
        logger.debug("[timeout_paris] Jina exception : %s", e)
    return ""


class TimeOutParisScraper(BaseScraper):
    name = "timeout_paris"
    base_url = "https://www.timeout.fr"

    INDEX_URLS = [
        "https://www.timeout.fr/paris/que-faire-a-paris/les-meilleurs-plans-de-la-semaine",
        "https://www.timeout.fr/paris/que-faire-a-paris/5-choses-a-faire-aujourdhui",
    ]
    ARTICLE_PATTERN = re.compile(
        r"timeout\.fr/paris/[^/]+/[^/]+-\d{6}$"
    )
    MAX_ARTICLES = 15

    def _extract_article_urls(self, content: str) -> list[str]:
        urls = re.findall(r'\]\((https?://[^)]+)\)', content)
        urls = [u for u in urls if self.ARTICLE_PATTERN.search(u)]
        return list(dict.fromkeys(urls))

    def _extract_quand_ou(self, text: str) -> dict:
        result = {}
        m = _RE_QUAND.search(text)
        if m:
            result["quand_raw"] = m.group(1).strip()
        m = _RE_OU.search(text)
        if m:
            result["adresse_raw"] = m.group(1).strip()
        return result

    def _is_list_article(self, url: str, page_text: str) -> bool:
        slug = url.rstrip('/').split('/')[-1]
        number_words = (
            r'deux|trois|quatre|cinq|six|sept|huit|neuf|dix|'
            r'onze|douze|quinze|vingt'
        )
        if re.search(
            rf'(^|\-)(les\-)?(\d+|{number_words})[\-_]', slug, re.I
        ):
            return True
        numbered_h2 = re.findall(
            r'^##\s+[\*_]{0,2}\d+[\.\)]\s', page_text, re.MULTILINE
        )
        return len(numbered_h2) >= 3

    def _prepare_text(self, page_text: str) -> str:
        hints = self._extract_quand_ou(page_text)
        hint_block = ""
        if hints.get("quand_raw"):
            hint_block += f"[DATE DE L'ÉVÉNEMENT : {hints['quand_raw']}]\n"
        if hints.get("adresse_raw"):
            hint_block += f"[LIEU DE L'ÉVÉNEMENT : {hints['adresse_raw']}]\n"
        if hint_block:
            hint_block += "\n"
        match = re.search(r'\n# ', page_text)
        if match:
            start = max(0, match.start() - 100)
            body = page_text[start:start + 5000]
        elif len(page_text) < 4500:
            body = page_text
        else:
            body = page_text[3500:][:5000]
        return hint_block + body

    def _prepare_text_list(self, page_text: str) -> str:
        instruction = (
            "[INSTRUCTION : ceci est un article listant plusieurs lieux ou "
            "événements. N'extrait QUE les entrées qui ont une date de début "
            "ET un lieu explicites. Ignore les entrées dont la date dépend "
            "d'un calendrier externe ('selon les matchs', 'dates variables') "
            "ou dont l'adresse est absente.]\n\n"
        )
        match = re.search(r'\n# ', page_text)
        if match:
            start = max(0, match.start() - 100)
            content = page_text[start:start + 6000]
        else:
            content = page_text[4000:][:6000]
        return instruction + content

    def scrape(self) -> list[dict]:
        from datetime import date as _date, timedelta as _timedelta
        cutoff_str = (_date.today() - _timedelta(days=30)).isoformat()

        all_urls: list[str] = []
        for index_url in self.INDEX_URLS:
            content = _fetch_jina(index_url)
            if not content:
                logger.warning("[timeout_paris] index vide : %s", index_url)
                continue
            all_urls.extend(self._extract_article_urls(content))

        article_urls = list(dict.fromkeys(all_urls))[:self.MAX_ARTICLES]
        logger.info("[timeout_paris] %d articles trouvés", len(article_urls))

        results = []
        seen_titres: set[str] = set()

        for url in article_urls:
            page_text = _fetch_jina(url)
            if not page_text:
                logger.warning("[timeout_paris] article vide : %s", url)
                continue

            is_list = self._is_list_article(url, page_text)

            if is_list:
                prepared = self._prepare_text_list(page_text)
                items = extract_list_with_llm(prepared)

                for item in items:
                    if not item.get("titre"):
                        continue
                    if not item.get("date_debut"):
                        logger.debug(
                            "[timeout_paris] item ignoré (pas de date) : %s",
                            item.get("titre")
                        )
                        continue
                    if item["date_debut"] < cutoff_str:
                        logger.debug(
                            "[timeout_paris] item ignoré (date passée %s) : %s",
                            item["date_debut"], item.get("titre")
                        )
                        continue
                    if item.get("categorie") == "restaurant" \
                            and not item.get("date_debut"):
                        logger.debug(
                            "[timeout_paris] item ignoré (restaurant sans date) : %s",
                            item.get("titre")
                        )
                        continue
                    adresse = item.get("adresse") or ""
                    lat, lng = None, None
                    if adresse:
                        lat, lng = geocoder.geocode(adresse)
                    if not lat and item.get("titre"):
                        lat, lng = geocoder.geocode_freetext(item["titre"])
                    if not lat:
                        logger.debug(
                            "[timeout_paris] item ignoré (pas de lieu) : %s",
                            item.get("titre")
                        )
                        continue
                    date_fin = item.get("date_fin")
                    if not date_fin and item.get("date_debut") \
                            and item.get("duree_jours"):
                        try:
                            d = datetime.strptime(
                                item["date_debut"], "%Y-%m-%d"
                            )
                            date_fin = (
                                d + timedelta(days=int(item["duree_jours"]))
                            ).strftime("%Y-%m-%d")
                        except Exception:
                            pass
                    titre = item.get("titre", "")
                    if titre.lower() in seen_titres:
                        continue
                    seen_titres.add(titre.lower())
                    results.append({
                        "titre":       titre,
                        "description": item.get("description", ""),
                        "adresse":     adresse,
                        "lat":         lat,
                        "lng":         lng,
                        "date_debut":  item.get("date_debut"),
                        "date_fin":    date_fin,
                        "duree_jours": item.get("duree_jours"),
                        "categorie":   item.get("categorie", "autre"),
                        "source":      self.name,
                        "url":         url + "#" + _slugify(titre),
                        "image_url":   None,
                    })

            else:
                prepared = self._prepare_text(page_text)
                data = extract_with_llm(prepared)
                if not data or not data.get("titre"):
                    continue
                if not data.get("adresse"):
                    hints = self._extract_quand_ou(page_text)
                    if hints.get("adresse_raw"):
                        data["adresse"] = hints["adresse_raw"]
                EPHEMERES = {
                    "exposition", "popup", "galerie", "musique",
                    "spectacle", "cinema", "atelier", "marche",
                }
                cat = data.get("categorie", "")
                est_ephemere = cat in EPHEMERES or cat.startswith("autre:")
                if est_ephemere and not (
                    data.get("date_debut") and data.get("date_fin")
                ):
                    logger.debug(
                        "[timeout_paris] skipped (éphémère sans dates) : %s",
                        url
                    )
                    continue
                if data.get("date_debut") and data["date_debut"] < cutoff_str:
                    logger.debug(
                        "[timeout_paris] skipped (date passée %s) : %s",
                        data["date_debut"], data.get("titre")
                    )
                    continue
                if cat == "restaurant" and not data.get("date_debut"):
                    logger.debug(
                        "[timeout_paris] skipped (restaurant sans date_debut) : %s",
                        url
                    )
                    continue
                adresse = data.get("adresse") or ""
                lat, lng = None, None
                if adresse:
                    lat, lng = geocoder.geocode(adresse)
                if not lat and data.get("titre"):
                    lat, lng = geocoder.geocode_freetext(data["titre"])
                if not lat:
                    logger.debug(
                        "[timeout_paris] skipped (pas de lieu) : %s",
                        data.get("titre")
                    )
                    continue
                titre = data.get("titre", "")
                if titre.lower() in seen_titres:
                    continue
                seen_titres.add(titre.lower())
                results.append({
                    "titre":       titre,
                    "description": data.get("description", ""),
                    "adresse":     adresse,
                    "lat":         lat,
                    "lng":         lng,
                    "date_debut":  data.get("date_debut"),
                    "date_fin":    data.get("date_fin"),
                    "duree_jours": data.get("duree_jours"),
                    "categorie":   cat,
                    "source":      self.name,
                    "url":         url,
                    "image_url":   None,
                })

            time.sleep(1)

        logger.info("[timeout_paris] %d events extraits", len(results))
        return results


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    logging.basicConfig(level=logging.DEBUG)

    scraper = TimeOutParisScraper()
    events = scraper.scrape()

    print(f"\n{'═'*60}")
    print(f"RÉSULTAT : {len(events)} events extraits")
    print(f"{'═'*60}")
    for ev in events:
        print(f"\n  titre      : {ev['titre']}")
        print(f"  date_debut : {ev['date_debut']}")
        print(f"  date_fin   : {ev['date_fin']}")
        print(f"  adresse    : {ev['adresse']}")
        print(f"  lat/lng    : {ev.get('lat')}, {ev.get('lng')}")
        print(f"  categorie  : {ev['categorie']}")
        print(f"  url        : {ev['url']}")
