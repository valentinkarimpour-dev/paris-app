import sys
import logging
import re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
logging.basicConfig(level=logging.WARNING)

import time
import httpx
from scrapers.base import extract_with_llm, extract_list_with_llm

URLS = [
    "https://www.sortiraparis.com/loisirs/salon/articles/347903-playground-au-centquatre-paris-l-evenement-mode-sport-et-culture-pour-les-kids-ados-et-familles",
    "https://www.sortiraparis.com/loisirs/shopping-mode/articles/347055-bande-de-createurs-est-de-retour-les-20-21-juin-prochains-avec-un-pop-gratuit-dans-paris",
    "https://www.sortiraparis.com/loisirs/shopping-mode/articles/346579-deus-ex-machina-x-officine-generale-2-marques-en-vente-privee-physique-exclusive-avec-the-bradery",
    "https://www.sortiraparis.com/loisirs/shopping-mode/articles/346184-du-fun-des-cadeaux-et-des-economies-d-energie-octopus-installe-son-pop-up-store-a-paris",
    "https://www.sortiraparis.com/scenes/concert-musique/articles/337444-sabaton-pop-up-store-paris",
]

JINA_HEADERS = {"Accept": "text/markdown", "X-Timeout": "15"}

RULE = (
    "[RÈGLE DATES : si aucune date précise n'est mentionnée "
    "('ouverture imminente', 'bientôt', 'prochainement'), "
    "retourner null pour date_debut et date_fin. "
    "Ne pas utiliser les dates de type 'Mis à jour le' ou 'Publié le' "
    "comme date_debut. Ces dates sont éditoriales, pas des dates d'événement.]\n\n"
)

RULE_LIST = (
    "[ATTENTION DATES : l'article peut contenir des dates contradictoires "
    "(ex: 'dimanche 1er mars 2026' dans le corps mais 'dimanche 5 juillet 2026' "
    "dans le titre). La date correcte est celle du TITRE de l'article. "
    "Ignorer les dates dans les liens ou le corps qui contredisent le titre.]\n\n"
)

_NUMBER_WORDS = {
    "un", "une", "deux", "trois", "quatre", "cinq", "six", "sept", "huit",
    "neuf", "dix", "onze", "douze", "quinze", "vingt",
}


def _strip_links(text: str) -> str:
    text = re.sub(r'\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)', '', text)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    return text.strip()


def _is_list_article(url: str, page_text: str) -> bool:
    slug = url.split("/articles/")[1].split("#")[0]
    # Tous les slugs SortirAParis commencent par l'ID numérique (ex: "284553-6-chateaux-...")
    # On le strip pour ne tester que la partie sémantique
    slug_content = re.sub(r'^\d+-', '', slug)
    # La partie contenu commence par un chiffre : "6-chateaux-..."
    if re.match(r'^\d+[-]', slug_content):
        return True
    # La partie contenu commence par un mot-nombre : "six-chateaux-..."
    first_word = slug_content.split("-")[0]
    if first_word in _NUMBER_WORDS:
        return True
    # Page avec au moins 2 H2 numérotés : "## 1.", "## 2."
    if len(re.findall(r'\n## \d+', page_text)) >= 2:
        return True
    return False


def _get_infos(page_text: str) -> tuple[str, int]:
    infos_match = re.search(r'informations?\s+pratiques?', page_text, re.I)
    if infos_match:
        raw = _strip_links(
            page_text[infos_match.start(): infos_match.start() + 1500]
        )
        return raw, infos_match.start()
    return "", -1


def _prepare_text(page_text: str) -> str:
    h1_match = re.search(r'\n# ', page_text)
    h1_pos = h1_match.start() if h1_match else 19000
    prose_match = re.search(
        r'\n\n(?!\[!\[)([A-ZÀ-Ÿa-zà-ÿ].{50,})',
        page_text[h1_pos:]
    )
    prose_start = h1_pos + prose_match.start() if prose_match else h1_pos + 600
    head = page_text[prose_start: prose_start + 600]

    infos, _ = _get_infos(page_text)

    if infos:
        return RULE + head + "\n\n[...]\n\n" + infos
    return RULE + head


def _prepare_text_list(page_text: str) -> str:
    instruction = (
        "[INSTRUCTION : ceci est un article listant plusieurs lieux. "
        "N'extrait QUE les entrées qui ont un lieu explicite. "
        "La date est celle du TITRE de l'article — ignorer toute "
        "date contradictoire dans le corps du texte.]\n\n"
    )
    h1_match = re.search(r'\n# ', page_text)
    if h1_match:
        start = h1_match.start()
        # Sauter le bloc d'images post-H1 (~2000 chars)
        # puis prendre 14000 chars de contenu réel
        content = page_text[start + 2000: start + 14000]
    else:
        content = page_text[20000:][:12000]
    return instruction + content


def _coerce(v):
    return None if v in (None, "null", "None") else v


def _flag_duration(date_debut, date_fin, duree_jours) -> str:
    date_debut  = _coerce(date_debut)
    date_fin    = _coerce(date_fin)
    duree_jours = _coerce(duree_jours)
    flags = []
    if duree_jours and int(duree_jours) > 365:
        flags.append(f"⚠️  duree_jours={duree_jours} > 365")
    if date_debut and date_fin:
        try:
            d0 = datetime.strptime(date_debut, "%Y-%m-%d")
            d1 = datetime.strptime(date_fin, "%Y-%m-%d")
            if (d1 - d0).days > 365:
                flags.append(f"⚠️  date_fin - date_debut = {(d1-d0).days} jours > 365")
        except ValueError:
            pass
    return "  " + "\n  ".join(flags) if flags else ""


for url in URLS:
    slug = url.split("/articles/")[1]
    print("\n" + "=" * 80)
    print(f"URL: {slug}")
    print("=" * 80)

    time.sleep(2)
    page_text = httpx.get(
        "https://r.jina.ai/" + url, headers=JINA_HEADERS, timeout=25
    ).text

    h1_match = re.search(r'\n# ', page_text)
    h1_pos = h1_match.start() if h1_match else -1
    infos_raw, infos_pos = _get_infos(page_text)

    print(f"Longueur: {len(page_text)} chars | H1: {h1_pos} | Infos pratiques: {infos_pos}")

    is_list = _is_list_article(url, page_text)
    print(f"Type: {'📋 LISTE' if is_list else '📄 SIMPLE'}")

    if infos_raw:
        print(f"\n--- Informations pratiques (1500 chars strippés) ---")
        print(infos_raw[:1500])
    else:
        print("\n[Informations pratiques NON TROUVÉES]")

    if is_list:
        combined = _prepare_text_list(page_text)
        print(f"\nCombined list: {len(combined)} chars")
        items = extract_list_with_llm(combined)
        print(f"\nRésultat LLM ({len(items)} items) :")
        for i, item in enumerate(items, 1):
            date_debut = item.get('date_debut')
            date_fin   = item.get('date_fin')
            duree      = item.get('duree_jours')
            print(f"\n  [{i}] titre      : {item.get('titre')}")
            print(f"      date_debut : {date_debut}")
            print(f"      date_fin   : {date_fin}")
            print(f"      adresse    : {item.get('adresse')}")
            print(f"      duree_jours: {duree}")
            print(f"      categorie  : {item.get('categorie')}")
            flag = _flag_duration(date_debut, date_fin, duree)
            if flag:
                print(flag)
    else:
        combined = _prepare_text(page_text)
        print(f"\nCombined: {len(combined)} chars")
        result = extract_with_llm(combined)
        date_debut = result.get('date_debut')
        date_fin   = result.get('date_fin')
        duree      = result.get('duree_jours')
        print(f"\nRésultat LLM:")
        print(f"  titre      : {result.get('titre')}")
        print(f"  date_debut : {date_debut}")
        print(f"  date_fin   : {date_fin}")
        print(f"  adresse    : {result.get('adresse')}")
        print(f"  duree_jours: {duree}")
        print(f"  categorie  : {result.get('categorie')}")
        flag = _flag_duration(date_debut, date_fin, duree)
        if flag:
            print(flag)
