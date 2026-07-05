from .website.parisbouge_autre import ParisBougeAutre
from .website.parisbouge_restos import ParisBougeRestos
from .website.parisbouge_bars import ParisBougeBars
from .website.parisbouge_expos import ParisBougeExpos
from .website.lebonbon_news import LeBonbonNews
from .website.lebonbon_food import LeBonbonFood
from .website.lebonbon_drinks import LeBonbonDrinks
from .website.lebonbon_healthy import LeBonBonHealthy
from .website.lebonbon_loisirs import LeBonbonLoisirs
from .website.parismusee_expos import ParisMuseeExpos
from .website.museofile import MuseofileScraper
from .website.newtable import NewTable
from .website.numero_popup import NumeroPopup
from .website.secrets_of_paris import SecretsOfParis

from .email.lefooding import LeFooding
from .email.lessentiel_paris import LessentielParis

from .opendata.paris_opendata import ParisOpenData
from .opendata.inpi_api_food import InpiFoodScraper
from .opendata.inpi_api_drinks import InpiDrinksScraper
from .editorial.sources import SortirAParis
from .editorial.timeout_paris import TimeOutParisScraper as TimeOutParis
from .editorial.sortiraparis_restaurant import SortirAParisRestaurant
from .editorial.sortiraparis_cafes import SortirAParisCafes
from .editorial.sortiraparis_expos import SortirAParisExpos
from .editorial.sortiraparis_popup import SortirAParisPopup

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
    LeBonBonHealthy,
    LeBonbonLoisirs,
    NumeroPopup,
    InpiFoodScraper,
    InpiDrinksScraper,
    TimeOutParis,
    SortirAParisRestaurant,
    SortirAParisCafes,
    SortirAParisExpos,
    SortirAParisPopup,
]


# À revoir avant de remettre en production
TO_REVIEW = []

MONTHLY_SCRAPERS = [SecretsOfParis, ParisMuseeExpos, MuseofileScraper]
