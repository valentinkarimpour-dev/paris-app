"""
INPI RNE scraper — immatriculations F&B du jour à Paris
API : https://registre-national-entreprises.inpi.fr/api
Auth : POST /sso/login → JWT token
Codes NAF ciblés : 56.10A (restauration rapide), 56.30Z (débits de boissons)
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv("/home/valentin/claude/claude_code/.env")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")

INPI_BASE_URL = "https://registre-national-entreprises.inpi.fr/api"
NAF_CIBLES    = {"5610A", "5630Z"}  # sans points — format INPI
PARIS_ZIP     = "75"
GEOCODE_URL   = "https://api-adresse.data.gouv.fr/search/"


@dataclass
class Etablissement:
    siren:       str
    titre:       str
    adresse_raw: str
    code_postal: str
    date_debut:  str | None
    lat:         float | None
    lng:         float | None
    naf:         str
    source:      str = "inpi_api"


def get_token() -> str:
    username = os.getenv("INPI_USERNAME")
    password = os.getenv("INPI_PASSWORD")
    if not username or not password:
        raise RuntimeError("[inpi_api] INPI_USERNAME / INPI_PASSWORD manquants dans .env")

    resp = httpx.post(
        f"{INPI_BASE_URL}/sso/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"[inpi_api] Auth échouée ({resp.status_code}) : {resp.text[:300]}")

    token = resp.json().get("token")
    if not token:
        raise RuntimeError(f"[inpi_api] Pas de token dans la réponse : {resp.text[:300]}")

    logger.info("[inpi_api] Token obtenu")
    return token


def fetch_immatriculations(token: str, date_cible: date) -> list[dict]:
    headers  = {"Authorization": f"Bearer {token}"}
    date_from = date_cible.isoformat()
    date_to   = (date_cible + timedelta(days=1)).isoformat()
    resultats = []
    page = 1

    while True:
        params = {
            "submitDateFrom":  date_from,
            "submitDateTo":    date_to,
            "zipCodes[]":      PARIS_ZIP,
            "activitySectors": "COMMERCIALE",
            "pageSize":        100,
            "page":            page,
        }
        try:
            resp = httpx.get(
                f"{INPI_BASE_URL}/companies",
                params=params,
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("[inpi_api] Erreur fetch page=%d : %s", page, e)
            break

        batch = data if isinstance(data, list) else data.get("companies", data.get("results", []))
        if not batch:
            break

        resultats.extend(batch)
        logger.debug("[inpi_api] page=%d → %d résultats", page, len(batch))

        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.3)

    logger.info("[inpi_api] %d entreprises brutes récupérées", len(resultats))
    return resultats


def _get_entite(entreprise: dict) -> tuple[str, dict]:
    """Retourne (type, sous-dict) pour personnePhysique ou personneMorale."""
    content = entreprise.get("formality", {}).get("content", {})
    for key in ("personnePhysique", "personneMorale"):
        if key in content:
            return key, content[key]
    return "", {}


def _diffusion_autorisee(entreprise: dict) -> bool:
    content = entreprise.get("formality", {}).get("content", {})
    # Champ top-level dans content
    val = content.get("diffusionCommerciale")
    if val is False:
        return False
    # Champ dans personnePhysique
    _, entite = _get_entite(entreprise)
    val2 = entite.get("diffusionCommerciale")
    if val2 is False:
        return False
    return True


def extraire_naf(entreprise: dict) -> str | None:
    siren = entreprise.get("formality", {}).get("siren", "?")
    _, entite = _get_entite(entreprise)
    try:
        naf = entite["etablissementPrincipal"]["descriptionEtablissement"]["codeApe"]
        return naf if naf else None
    except (KeyError, TypeError):
        logger.warning("[inpi_api] NAF absent pour siren=%s", siren)
        return None


def extraire_adresse(entreprise: dict) -> tuple[str, str]:
    _, entite = _get_entite(entreprise)
    try:
        adr = entite["etablissementPrincipal"]["adresse"]
        return adr.get("voie", ""), adr.get("codePostal", "")
    except (KeyError, TypeError):
        return "", ""


def extraire_titre(entreprise: dict) -> str | None:
    """Retourne le nom commercial ou None si absent (entrée ignorée)."""
    kind, entite = _get_entite(entreprise)
    try:
        nom = entite["etablissementPrincipal"]["descriptionEtablissement"].get("nomCommercial")
        if nom:
            return nom
        if kind == "personneMorale":
            denom = entite.get("denomination")
            return denom if denom else None
    except (KeyError, TypeError):
        pass
    return None


def filtrer_et_normaliser(entreprises: list[dict], cibles: set[str] | None = None) -> list[Etablissement]:
    retenus = []
    for e in entreprises:
        if not _diffusion_autorisee(e):
            logger.debug("[inpi_api] diffusion refusée siren=%s", e.get("siren"))
            continue

        naf = extraire_naf(e)
        if not naf or naf not in (cibles or NAF_CIBLES):
            continue

        titre = extraire_titre(e)
        if not titre:
            continue  # pas de nom commercial → on ignore silencieusement

        voie, cp = extraire_adresse(e)
        _, entite = _get_entite(e)
        try:
            date_debut = entite["etablissementPrincipal"]["descriptionEtablissement"].get("dateDebutActivite")
        except (KeyError, TypeError):
            date_debut = None

        retenus.append(Etablissement(
            siren       = e.get("formality", {}).get("siren", ""),
            titre       = titre,
            adresse_raw = voie,
            code_postal = cp,
            date_debut  = date_debut,
            lat         = None,
            lng         = None,
            naf         = naf,
        ))

    logger.info("[inpi_api] %d établissements retenus après filtrage NAF", len(retenus))
    return retenus


def geocoder_etablissement(etab: Etablissement) -> Etablissement:
    query = f"{etab.adresse_raw} {etab.code_postal} Paris".strip()
    try:
        resp = httpx.get(GEOCODE_URL, params={"q": query, "limit": 1}, timeout=10)
        resp.raise_for_status()
        features = resp.json().get("features", [])
        if features:
            coords = features[0]["geometry"]["coordinates"]
            etab.lng = coords[0]
            etab.lat = coords[1]
        else:
            logger.warning("[inpi_api] Géocodage vide pour '%s'", etab.titre)
    except Exception as e:
        logger.warning("[inpi_api] Erreur géocodage '%s' : %s", etab.titre, e)
    time.sleep(0.1)
    return etab


def run(date_cible: date | None = None, naf_cibles: set[str] | None = None) -> list[Etablissement]:
    if date_cible is None:
        date_cible = date.today()

    cibles = naf_cibles or NAF_CIBLES
    logger.info("[inpi_api] Date ciblée : %s | NAF : %s", date_cible, cibles)
    token     = get_token()
    bruts     = fetch_immatriculations(token, date_cible)
    retenus   = filtrer_et_normaliser(bruts, cibles)
    resultats = [geocoder_etablissement(e) for e in retenus]

    geocodes = sum(1 for e in resultats if e.lat is not None)
    logger.info(
        "[inpi_api] Résumé : date=%s | bruts=%d | après NAF=%d | géocodés=%d",
        date_cible, len(bruts), len(retenus), geocodes,
    )
    return resultats


def scrape_inpi(naf_cibles: set[str], categorie: str, date_cible: date | None = None) -> list[dict]:
    """
    Appelé par les scrapers food/drinks. Retourne une liste de dicts
    compatibles avec db.insert_event().
    """
    items = run(date_cible=date_cible, naf_cibles=naf_cibles)
    return [
        {
            "titre":       e.titre,
            "description": "",
            "adresse":     f"{e.adresse_raw} {e.code_postal}".strip(),
            "lat":         e.lat,
            "lng":         e.lng,
            "date_debut":  e.date_debut,
            "date_fin":    None,
            "duree_jours": None,
            "categorie":   categorie,
            "prix":        None,
            "url":         f"https://registre-national-entreprises.inpi.fr/en/enterprise/{e.siren}",
            "image_url":   None,
        }
        for e in items
    ]


if __name__ == "__main__":
    items = run()
    if not items:
        print("Aucun établissement trouvé.")
    for e in items:
        print(f"{e.titre} | {e.naf} | {e.adresse_raw} {e.code_postal} | {e.lat},{e.lng} | {e.date_debut}")
