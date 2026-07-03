import asyncio
import logging
import re
import time
import unicodedata as _uc

import httpx
from playwright.async_api import async_playwright

from ..base import BaseScraper, extract_with_llm, extract_list_with_llm, VALID_CATEGORIES

logger = logging.getLogger(__name__)

_CATEGORIES_EPHEMERES = VALID_CATEGORIES - {
    "restaurant", "bar", "cafe", "musee", "galerie", "wellness", "boutique",
}

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def _slugify(s: str) -> str:
    nfkd = _uc.normalize("NFKD", s)
    s = nfkd.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


class JinaBaseScraper(BaseScraper):
    index_url: str = ""
    article_url_pattern: str = ""
    exclude_url_patterns: list[str] = []
    max_articles: int = 10
    require_dates: bool = False

    def fetch_jina(self, url: str) -> str:
        jina_url = f"https://r.jina.ai/{url}"
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.get(jina_url, headers={"Accept": "text/markdown"})
            logger.debug("[%s] Jina %s → status=%d, len=%d", self.name, url, resp.status_code, len(resp.text))
            if resp.status_code == 200 and len(resp.text) > 500:
                return resp.text
        except Exception as e:
            logger.debug("[%s] Jina exception : %s", self.name, e)
        return ""

    def fetch_playwright(self, url: str) -> str:
        async def _fetch() -> str:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                ctx = await browser.new_context(user_agent=_UA, locale="fr-FR")
                await ctx.route("**/*.{png,jpg,jpeg,gif,webp,woff2,woff,ttf}", lambda r: r.abort())
                page = await ctx.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                    await page.wait_for_timeout(2500)
                    for _ in range(5):
                        await page.evaluate("window.scrollBy(0, 800)")
                        await page.wait_for_timeout(300)
                    return await page.content()
                except Exception as e:
                    logger.warning("[%s] Playwright exception sur %s : %s", self.name, url, e)
                    return ""
                finally:
                    await browser.close()

        try:
            return asyncio.run(_fetch())
        except Exception as e:
            logger.warning("[%s] asyncio.run Playwright échoué : %s", self.name, e)
            return ""

    def fetch(self, url: str) -> str:
        result = self.fetch_jina(url)
        if result:
            logger.debug("[%s] fetch via Jina : %s", self.name, url)
            return result
        logger.debug("[%s] Jina vide → fallback Playwright : %s", self.name, url)
        result = self.fetch_playwright(url)
        if result:
            logger.debug("[%s] fetch via Playwright : %s", self.name, url)
        return result

    def extract_article_urls(self, content: str) -> list[str]:
        urls = re.findall(r'\]\((https?://[^)]+)\)', content)
        if not urls:
            urls = re.findall(r'href=["\'](https?://[^"\']+)["\']', content)
        if self.article_url_pattern:
            urls = [u for u in urls if re.search(self.article_url_pattern, u)]
        if self.exclude_url_patterns:
            urls = [u for u in urls if not any(re.search(p, u) for p in self.exclude_url_patterns)]
        return list(dict.fromkeys(urls))[:self.max_articles]

    def scrape(self) -> list[dict]:
        index_urls = getattr(self, "index_urls", None) or ([self.index_url] if self.index_url else [])

        all_article_urls: list[str] = []
        for index_url in index_urls:
            content = self.fetch(index_url)
            if not content:
                logger.warning("[%s] index vide : %s", self.name, index_url)
                continue
            urls = self.extract_article_urls(content)
            all_article_urls.extend(urls)

        article_urls = list(dict.fromkeys(all_article_urls))[:self.max_articles]
        logger.info("[%s] %d articles trouvés sur index", self.name, len(article_urls))

        results = []
        for url in article_urls:
            article_content = self.fetch(url)
            if not article_content:
                logger.warning("[%s] article vide : %s", self.name, url)
                continue
            if self._is_list_article(url, article_content):
                items = extract_list_with_llm(
                    self._prepare_text_list(article_content)
                )
                for item in items:
                    if not item.get("titre"):
                        continue
                    if self.require_dates and not item.get("date_debut"):
                        logger.debug(
                            "[%s] item liste ignoré (pas de date_debut) : %s",
                            self.name, item.get("titre", "?")
                        )
                        continue
                    date_fin = item.get("date_fin")
                    if not date_fin and item.get("date_debut") \
                            and item.get("duree_jours"):
                        try:
                            from datetime import datetime, timedelta
                            d = datetime.strptime(item["date_debut"], "%Y-%m-%d")
                            date_fin = (
                                d + timedelta(days=int(item["duree_jours"]))
                            ).strftime("%Y-%m-%d")
                        except Exception:
                            pass
                    # Géocodage freetext via titre si adresse absente
                    if not item.get("adresse") and item.get("titre"):
                        from geocoder import geocode_freetext
                        lat, lng = geocode_freetext(item["titre"])
                        if lat:
                            item["lat"] = lat
                            item["lng"] = lng
                    # Filtre localisation pour les scrapers qui l'exigent
                    if getattr(self, 'require_location', False):
                        if not item.get("adresse") and not item.get("lat"):
                            logger.debug(
                                "[%s] item liste ignoré (aucune localisation) : %s",
                                self.name, item.get("titre", "?")
                            )
                            continue
                    results.append({
                        "titre":       item.get("titre", ""),
                        "description": item.get("description", ""),
                        "adresse":     item.get("adresse") or "",
                        "date_debut":  item.get("date_debut"),
                        "date_fin":    date_fin,
                        "duree_jours": item.get("duree_jours"),
                        "categorie":   item.get("categorie", "autre"),
                        "source":      self.name,
                        "url":         url + "#" + _slugify(item.get("titre", "")),
                        "image_url":   None,
                    })
            else:
                data = extract_with_llm(self._prepare_text(article_content))
                if not data:
                    continue
                if self.require_dates:
                    categorie = data.get("categorie", "")
                    est_ephemere = (
                        categorie in _CATEGORIES_EPHEMERES
                        or categorie.startswith("autre:")
                    )
                    if est_ephemere and not (data.get("date_debut") and data.get("date_fin")):
                        logger.debug(
                            "[%s] skipped — événement éphémère sans dates : %s",
                            self.name, url
                        )
                        continue
                # Géocodage freetext via titre si adresse absente
                if not data.get("adresse") and data.get("titre"):
                    from geocoder import geocode_freetext
                    lat, lng = geocode_freetext(data["titre"])
                    if lat:
                        data["lat"] = lat
                        data["lng"] = lng
                # Filtre localisation (TimeOutParis uniquement via require_location)
                if getattr(self, 'require_location', False) and not data.get("adresse"):
                    if not data.get("lat"):
                        logger.debug(
                            "[%s] skipped — aucune localisation identifiable : %s",
                            self.name, data.get("titre", "?")
                        )
                        continue
                data["url"] = url
                data["source"] = self.name
                results.append(data)
            time.sleep(1)

        seen_titres = set()
        deduplicated = []
        for item in results:
            titre = (item.get("titre") or "").strip().lower()
            if titre and titre not in seen_titres:
                seen_titres.add(titre)
                deduplicated.append(item)
        return deduplicated

    def _prepare_text(self, page_text: str) -> str:
        """Prépare le texte avant envoi au LLM.
        Surchargeable par les sous-classes pour adapter la découpe.
        Par défaut : texte brut complet (la troncature est dans extract_with_llm).
        """
        return page_text

    def _is_list_article(self, article_url: str, page_text: str) -> bool:
        slug = article_url.rstrip('/').split('/')[-1]
        number_words = (
            r'deux|trois|quatre|cinq|six|sept|huit|neuf|dix|'
            r'onze|douze|quinze|vingt'
        )
        if re.search(rf'(^|\-)(les\-)?(\d+|{number_words})[\-_]', slug, re.I):
            return True
        numbered_h2 = re.findall(
            r'^##\s+[\*_]{0,2}\d+[\.\)]\s',
            page_text, re.MULTILINE
        )
        return len(numbered_h2) >= 3

    def _prepare_text_list(self, page_text: str) -> str:
        instruction = (
            "[INSTRUCTION : ceci est un article listant plusieurs lieux ou "
            "événements. N'extrait QUE les entrées qui ont une date de début "
            "ET un lieu explicites. Ignore les entrées dont la date dépend "
            "d'un calendrier externe ('selon les matchs', 'dates variables', "
            "etc.) ou dont l'adresse est absente.]\n\n"
        )
        content = page_text[4000:][:10000]
        return instruction + content
