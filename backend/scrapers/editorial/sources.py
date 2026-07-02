from .jina_base import JinaBaseScraper


class SortirAParis(JinaBaseScraper):
    name = "sortiraparis"
    base_url = "https://www.sortiraparis.com"
    article_url_pattern = r"sortiraparis\.com/.*/articles/\d+"
    require_dates = True
    exclude_url_patterns = [
        r"que-faire-ce-",
        r"que-faire-a-paris",
        r"bons-plans-du-week",
        r"selection-week-end",
    ]
    max_articles = 15
    index_urls = [
        "https://www.sortiraparis.com/hotel-restaurant/restaurant",
        "https://www.sortiraparis.com/hotel-restaurant/cafe-tea-time",
        "https://www.sortiraparis.com/arts-culture/exposition",
        "https://www.sortiraparis.com/articles/tag/pop-up-store",
        "https://www.sortiraparis.com/articles/tag/boutique-ephemere",
    ]

    def _prepare_text(self, page_text: str) -> str:
        """SortirAParis : adresse dans 'Infos pratiques' en fin de page.
        On envoie le début (date, description) + la fin (adresse).
        """
        head = page_text[:3000]
        tail = page_text[-2000:]
        if len(page_text) > 5000:
            return head + "\n\n[...contenu intermédiaire omis...]\n\n" + tail
        return page_text
