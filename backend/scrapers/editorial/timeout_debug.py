"""
Script de diagnostic TimeOutParis.
Teste 4 articles représentatifs et affiche le pipeline complet :
fetch → détection liste → préparation texte → extraction LLM → résultat.
Ne pas inclure dans les scrapers de production.
"""
import re
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import httpx
from scrapers.editorial.sources import TimeOutParis

URLS = [
    "https://www.timeout.fr/paris/actualites/le-joaillier-italien-pomellato-sexpose-au-palais-de-tokyo-062526",
    "https://www.timeout.fr/paris/actualites/le-food-market-sort-le-grand-jeu-pour-son-dernier-rendez-vous-avant-les-vacances-062526",
    "https://www.timeout.fr/paris/actualites/entre-rap-r-b-et-afrobeats-le-festival-yardland-devoile-la-programmation-bouillante-de-son-edition-2026-012926",
    "https://www.timeout.fr/paris/actualites/coupe-du-monde-onze-fan-zones-grand-paris-061026",
]

DB_PATH = Path(__file__).parent.parent.parent / "events.db"
TABLE = "events_timeout_debug"

scraper = TimeOutParis()


def fetch_jina(url: str) -> str:
    try:
        resp = httpx.get(f"https://r.jina.ai/{url}", headers={"Accept": "text/markdown"}, timeout=20)
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text
    except Exception as e:
        print(f"  Jina exception : {e}")
    return ""


def init_debug_table():
    con = sqlite3.connect(DB_PATH)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            titre TEXT,
            date_debut TEXT,
            date_fin TEXT,
            adresse TEXT,
            lat REAL,
            lng REAL,
            categorie TEXT,
            is_list INTEGER,
            scraped_at TEXT DEFAULT (datetime('now'))
        )
    """)
    con.execute(f"DELETE FROM {TABLE}")
    con.commit()
    con.close()


def insert_debug(url, item, is_list):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        f"INSERT INTO {TABLE} (url, titre, date_debut, date_fin, adresse, lat, lng, categorie, is_list) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            url,
            item.get("titre"),
            item.get("date_debut"),
            item.get("date_fin"),
            item.get("adresse"),
            item.get("lat"),
            item.get("lng"),
            item.get("categorie"),
            1 if is_list else 0,
        )
    )
    con.commit()
    con.close()


def find_quand_ou(text):
    m_quand = scraper._RE_QUAND.search(text)
    m_ou = scraper._RE_OU.search(text)
    quand = m_quand.group(1).strip() if m_quand else "introuvable"
    ou = m_ou.group(1).strip() if m_ou else "introuvable"
    pos_quand = m_quand.start() if m_quand else None
    pos_ou = m_ou.start() if m_ou else None
    return quand, ou, pos_quand, pos_ou


init_debug_table()

for url in URLS:
    SEP = "═" * 70
    print(f"\n{SEP}")
    print(f"URL: {url}")
    print(SEP)

    page_text = fetch_jina(url)
    if not page_text:
        print("  ERREUR : fetch Jina vide")
        continue

    # a) FETCH
    h1_match = re.search(r'\n# ', page_text)
    h1_pos = h1_match.start() if h1_match else None
    quand, ou, pos_quand, pos_ou = find_quand_ou(page_text)

    print(f"\n── a) FETCH")
    print(f"  Longueur totale : {len(page_text)} chars")
    print(f"  H1 position     : {h1_pos if h1_pos is not None else 'introuvable'}")
    if pos_quand:
        ctx_start = max(0, pos_quand - 60)
        ctx = page_text[ctx_start:pos_quand + 100].replace('\n', ' ')
        print(f"  Quand position  : {pos_quand} → '{quand}'")
        print(f"  Contexte        : '{ctx}'")
    else:
        print(f"  Quand           : introuvable")
    if pos_ou:
        print(f"  Où              : '{ou}'")
    else:
        print(f"  Où              : 'introuvable'")

    # b) DÉTECTION LISTE
    is_list = scraper._is_list_article(url, page_text)
    slug = url.rstrip('/').split('/')[-1]
    number_words = r'deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze|quinze|vingt'
    slug_match = re.search(rf'(^|\-)(les\-)?(\d+|{number_words})[\-_]', slug, re.I)
    numbered_h2 = re.findall(r'^##\s+[\*_]{0,2}\d+[\.\)]\s', page_text, re.MULTILINE)

    print(f"\n── b) DÉTECTION LISTE")
    print(f"  is_list_article : {is_list}")
    print(f"  Slug match      : {bool(slug_match)} ({slug_match.group(0).strip('-') if slug_match else 'aucun'})")
    print(f"  H2 numérotés    : {len(numbered_h2)} trouvés")

    if is_list:
        from scrapers.base import extract_list_with_llm
        prepared = scraper._prepare_text_list(page_text)
        print(f"\n── c) TEXTE ENVOYÉ AU LLM (liste)")
        print(f"  Longueur : {len(prepared)} chars")
        print(f"  Début    : {repr(prepared[:200])}...")

        items = extract_list_with_llm(prepared)
        print(f"\n── d) RÉSULTAT LLM")
        print(f"  {len(items)} items extraits :")
        for i, it in enumerate(items, 1):
            print(f"    [{i}] {it.get('titre')} | debut={it.get('date_debut')} | adr={it.get('adresse')}")
            insert_debug(url, it, is_list=True)
    else:
        from scrapers.base import extract_with_llm
        prepared = scraper._prepare_text(page_text)
        print(f"\n── c) TEXTE ENVOYÉ AU LLM (article simple)")
        print(f"  Longueur : {len(prepared)} chars")
        print(f"  Début    : {repr(prepared[:200])}...")

        data = extract_with_llm(prepared)
        print(f"\n── d) RÉSULTAT LLM")
        print(f"  titre      : {data.get('titre')}")
        print(f"  date_debut : {data.get('date_debut')}")
        print(f"  date_fin   : {data.get('date_fin')}")
        print(f"  adresse    : {data.get('adresse')}")
        print(f"  categorie  : {data.get('categorie')}")
        insert_debug(url, data, is_list=False)

print("\n\nDiagnostic terminé.")
print(f"\nLignes insérées dans {TABLE} :")
con = sqlite3.connect(DB_PATH)
for r in con.execute(f"SELECT titre, date_debut, date_fin, adresse, lat, lng, is_list FROM {TABLE}"):
    print(" ", r)
con.close()
