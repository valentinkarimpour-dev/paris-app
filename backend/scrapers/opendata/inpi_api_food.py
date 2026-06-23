"""
INPI Food scraper — nouvelles immatriculations restaurants à Paris (NAF 5610A)
"""
from ..base import BaseScraper
from .inpi_api import scrape_inpi

NAF_CIBLES = {"5610A"}


class InpiFoodScraper(BaseScraper):
    name = "inpi_food"
    base_url = "https://registre-national-entreprises.inpi.fr"

    def scrape(self) -> list[dict]:
        return [
            {**ev, "source": self.name}
            for ev in scrape_inpi(NAF_CIBLES, "restaurant")
        ]
