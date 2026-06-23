"""
Découverte de l'URL agenda d'une galerie — requests uniquement (pas de Playwright).
Trois méthodes dans l'ordre : HEAD sur chemins standards → parse nav → homepage.
"""

import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

COMMON_PATHS = [
    "/expositions", "/expositions-en-cours", "/exposition",
    "/agenda", "/programme", "/programmation",
    "/exhibitions", "/current", "/en-cours",
    "/fr/expositions", "/fr/agenda", "/fr/exposition",
    "/what-s-on", "/whats-on", "/now",
    "/galerie", "/galerie-en-cours",
]

NAV_KEYWORDS = [
    "exposition", "exhibition", "agenda", "current", "en cours",
    "programme", "whats-on", "what-s-on", "programmation",
]

_SOCIAL = {"instagram.com", "facebook.com", "twitter.com", "artsy.net", "x.com"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def is_social(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return any(s in domain for s in _SOCIAL)


def find_agenda_url(website: str, timeout: int = 8) -> str | None:
    if is_social(website):
        return None

    base   = website.rstrip("/")
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    sess = requests.Session()
    sess.headers.update(_HEADERS)

    # Méthode 1 : HEAD sur chemins connus
    for path in COMMON_PATHS:
        url = origin + path
        try:
            r = sess.head(url, timeout=timeout, allow_redirects=True)
            if r.status_code == 200:
                logger.info("[url_finder] %s → %s (HEAD)", website, url)
                return url
        except Exception:
            continue

    # Méthode 2 : parser la navigation de la homepage
    try:
        r = sess.get(base, timeout=timeout)
        if r.ok:
            soup  = BeautifulSoup(r.text, "html.parser")
            scope = soup.find("nav") or soup.find("header") or soup
            for a in scope.find_all("a", href=True):
                href    = a["href"]
                text    = a.get_text(strip=True).lower()
                abs_url = href if href.startswith("http") else urljoin(base, href)
                if urlparse(abs_url).netloc != parsed.netloc:
                    continue
                if any(kw in href.lower() or kw in text for kw in NAV_KEYWORDS):
                    logger.info("[url_finder] %s → %s (nav)", website, abs_url)
                    return abs_url
    except Exception as exc:
        logger.warning("[url_finder] %s nav scan failed: %s", website, exc)

    # Méthode 3 : homepage en fallback
    logger.info("[url_finder] %s → homepage fallback", website)
    return base
