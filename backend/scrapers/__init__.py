from .website.parisbouge_autre import ParisBougeAutre
from .website.parisbouge_restos import ParisBougeRestos
from .website.parisbouge_bars import ParisBougeBars
from .website.parisbouge_expos import ParisBougeExpos
from .website.lebonbon_news import LeBonbonNews
from .website.lebonbon_food import LeBonbonFood
from .website.lebonbon_drinks import LeBonbonDrinks
from .website.parismusee_expos import ParisMuseeExpos
from .website.museofile import MuseofileScraper
from .website.nouveaux_cafes import NouveauxCafes
from .website.nouveaux_restos import NouveauxRestos
from .website.doitinparis import DoItInParis
from .website.newtable import NewTable
from .website.numero_popup import NumeroPopup
from .website.secrets_of_paris import SecretsOfParis

from .email.lefooding import LeFooding
from .email.lessentiel_paris import LessentielParis

from .opendata.paris_opendata import ParisOpenData
from .opendata.inpi_api_food import InpiFoodScraper
from .opendata.inpi_api_drinks import InpiDrinksScraper
from .editorial.sources import SortirAParis, TimeOutParis

ALL_SCRAPERS = [
    ParisOpenData,
    ParisBougeAutre,
    ParisBougeRestos,
    ParisBougeBars,
    ParisBougeExpos,
    NewTable,
    LeBonbonNews,
    LeBonbonFood,
    LeBonbonDrinks,
    NumeroPopup,
    InpiFoodScraper,
    InpiDrinksScraper,
    SortirAParis,
    TimeOutParis,
]


# À revoir avant de remettre en production
TO_REVIEW = []

MONTHLY_SCRAPERS = [SecretsOfParis, ParisMuseeExpos, MuseofileScraper]
