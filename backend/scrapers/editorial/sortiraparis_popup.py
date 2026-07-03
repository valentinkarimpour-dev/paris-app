import logging
import re
import time
from datetime import date, timedelta

import httpx

from ..base import BaseScraper, extract_with_llm
import geocoder

logger = logging.getLogger(__name__)

ARTICLE_PATTERN = re.compile(
    r"sortiraparis\.com/[^/]+/[^/]+/articles/\d+"
)


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
        logger.debug("[sortiraparis_popup] Jina : %s", e)
    return ""


def _strip_links(text: str) -> str:
    text = re.sub(r'\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)', '', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    return text.strip()


def _prepare_text(page_text: str) -> str:
    rule = (
        "[RÈGLE DATES : si aucune date précise n'est mentionnée "
        "('ouverture imminente', 'bientôt', 'prochainement'), "
        "retourner null pour date_debut et date_fin. "
        "Ne pas utiliser les dates 'Mis à jour le' ou 'Publié le' "
        "comme date_debut — ce sont des dates éditoriales.]\n\n"
    )
    h1_match = re.search(r'\n# ', page_text)
    h1_pos = h1_match.start() if h1_match else 19000
    prose_match = re.search(
        r'\n\n(?!\[!\[)([A-ZÀ-Ÿa-zà-ÿ].{50,})',
        page_text[h1_pos:]
    )
    if prose_match:
        prose_start = h1_pos + prose_match.start()
        head = page_text[prose_start:prose_start + 600]
    else:
        head = page_text[h1_pos:h1_pos + 600]

    infos_match = re.search(r'informations?\s+pratiques?', page_text, re.I)
    if infos_match:
        infos = _strip_links(
            page_text[infos_match.start():infos_match.start() + 1500]
        )
    else:
        infos = ""

    if infos:
        return rule + head + "\n\n[...]\n\n" + infos
    return rule + head


class SortirAParisPopup(BaseScraper):
    name = "sortiraparis_popup"
    base_url = "https://www.sortiraparis.com"

    INDEX_URL = "https://www.sortiraparis.com/articles/tag/pop-up-store"
    MAX_ARTICLES = 5
    CUTOFF_DAYS = 30

    def _extract_article_urls(self, content: str) -> list[str]:
        urls = re.findall(r'\]\((https?://[^)]+)\)', content)
        urls = [u for u in urls if ARTICLE_PATTERN.search(u)]
        return list(dict.fromkeys(urls))

    def scrape(self) -> list[dict]:
        cutoff = (date.today() - timedelta(days=self.CUTOFF_DAYS)).isoformat()

        index_content = _fetch_jina(self.INDEX_URL)
        if not index_content:
            logger.warning("[sortiraparis_popup] index vide")
            return []

        article_urls = self._extract_article_urls(
            index_content
        )[:self.MAX_ARTICLES]
        logger.info(
            "[sortiraparis_popup] %d articles trouvés", len(article_urls)
        )

        results = []
        seen_titres: set[str] = set()

        for url in article_urls:
            page_text = _fetch_jina(url)
            if not page_text:
                logger.warning(
                    "[sortiraparis_popup] article vide : %s", url
                )
                continue

            data = extract_with_llm(_prepare_text(page_text))
            if not data or not data.get("titre"):
                continue

            if not data.get("date_debut"):
                logger.debug(
                    "[sortiraparis_popup] skipped (pas de date_debut) : %s",
                    data.get("titre")
                )
                continue
            if data["date_debut"] < cutoff:
                logger.debug(
                    "[sortiraparis_popup] skipped (date ancienne %s) : %s",
                    data["date_debut"], data.get("titre")
                )
                continue

            # Filtre durée > 90 jours = boutique permanente déguisée
            date_debut_str = data.get("date_debut")
            date_fin_str   = data.get("date_fin")
            if date_debut_str and date_fin_str:
                try:
                    from datetime import date as _date
                    d1 = _date.fromisoformat(date_debut_str)
                    d2 = _date.fromisoformat(date_fin_str)
                    if (d2 - d1).days > 90:
                        logger.debug(
                            "[sortiraparis_popup] skipped (durée > 90j) : %s",
                            data.get("titre")
                        )
                        continue
                except ValueError:
                    pass

            # Géocodage
            adresse = data.get("adresse") or ""
            lat, lng = None, None
            if adresse:
                lat, lng = geocoder.geocode(adresse)
            if not lat and adresse:
                lat, lng = geocoder.geocode_freetext(adresse)
            if not lat:
                logger.debug(
                    "[sortiraparis_popup] skipped pas de lieu : %s",
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
                "date_debut":  date_debut_str,
                "date_fin":    date_fin_str,
                "duree_jours": data.get("duree_jours"),
                "categorie":   "popup",
                "source":      self.name,
                "url":         url,
                "image_url":   None,
            })

            time.sleep(1)

        logger.info(
            "[sortiraparis_popup] %d events extraits", len(results)
        )
        return results


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    logging.basicConfig(level=logging.DEBUG)

    scraper = SortirAParisPopup()
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
        print(f"  url        : {ev['url']}")
