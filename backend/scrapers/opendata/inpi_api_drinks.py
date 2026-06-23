"""
INPI Drinks scraper — nouvelles immatriculations débits de boissons à Paris (NAF 5630Z)
"""
from ..base import BaseScraper
from .inpi_api import scrape_inpi

NAF_CIBLES = {"5630Z"}


class InpiDrinksScraper(BaseScraper):
    name = "inpi_drinks"
    base_url = "https://registre-national-entreprises.inpi.fr"

    def scrape(self) -> list[dict]:
        return [
            {**ev, "source": self.name}
            for ev in scrape_inpi(NAF_CIBLES, "bar")
        ]
