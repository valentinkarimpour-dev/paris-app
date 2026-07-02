import re

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


class TimeOutParis(JinaBaseScraper):
    name = "timeout_paris"
    base_url = "https://www.timeout.fr"
    article_url_pattern = r"timeout\.fr/paris/[^/]+/[^/]+-\d{6}$"
    require_dates = True
    require_location = True
    max_articles = 15
    index_urls = [
        "https://www.timeout.fr/paris/que-faire-a-paris/les-meilleurs-plans-de-la-semaine",
        "https://www.timeout.fr/paris/que-faire-a-paris/5-choses-a-faire-aujourdhui",
    ]

    _RE_QUAND = re.compile(
        r'\*{1,2}Quand\s*\??\*{1,2}\s*:?\s*(.+?)(?:\n|\.?\s*\*{1,2})',
        re.I
    )
    _RE_OU = re.compile(
        r'\*{1,2}O[uù]\s*\??\*{1,2}\s*:?\s*(.+?)(?:\n|\.|$)',
        re.I
    )

    def _extract_quand_ou(self, text: str) -> dict:
        """Extrait date et adresse depuis le bloc Quand/Où de TimeOut."""
        result = {}
        m_quand = self._RE_QUAND.search(text)
        m_ou    = self._RE_OU.search(text)
        if m_quand:
            result["quand_raw"] = m_quand.group(1).strip()
        if m_ou:
            result["adresse_raw"] = m_ou.group(1).strip()
        return result

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
        else:
            # Pas de H1 détecté — si article court, envoyer le tout
            # Si article long (navigation sans H1), sauter les 3500 premiers chars
            if len(page_text) < 4500:
                body = page_text
            else:
                body = page_text[3500:][:5000]
        return hint_block + body

    def _prepare_text_list(self, page_text: str) -> str:
        instruction = (
            "[INSTRUCTION : ceci est un article listant plusieurs lieux ou "
            "événements. N'extrait QUE les entrées qui ont une date de début "
            "ET un lieu explicites. Ignore les entrées dont la date dépend "
            "d'un calendrier externe ('selon les matchs', 'dates variables', "
            "etc.) ou dont l'adresse est absente.]\n\n"
        )
        match = re.search(r'\n# ', page_text)
        if match:
            start = max(0, match.start() - 100)
            content = page_text[start:start + 12000]
        else:
            content = page_text[4000:][:12000]
        return instruction + content
