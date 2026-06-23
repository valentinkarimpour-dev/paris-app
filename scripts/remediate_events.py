"""
Remédiation complète de la table events :
  1. Requalification instantanée des catégories legacy (SQL, sans réseau)
  2. Split brocante / vide-grenier pour paris.fr
  3. Re-extraction LLM pour tous les événements avec une vraie URL d'article
"""

import logging
import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from scrapers.base import extract_with_llm, _normalize_categorie
import db as database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DB_PATH = ROOT / "backend" / "events.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

# ── Sources dont les URLs renvoient vers des articles individuels ──
# doitinparis exclu : ses URLs sont des ancres (#) sur une seule page listing
ARTICLE_SOURCES = {"newtable", "sortiraparis", "parisbouge", "lebonbon"}

# ── Domaines qui sont des homepages (pas de contenu à re-fetcher) ──
HOMEPAGE_DOMAINS = {
    "lefooding.com", "timeout.com", "lessentiel.fr",
    "paris.fr/brocantes",           # paris.fr gérés séparément
}


def _is_homepage_url(url: str) -> bool:
    if not url:
        return True
    return any(d in url for d in HOMEPAGE_DOMAINS)


# ─────────────────────────────────────────────────────────────────────────────
# Étape 1 — Requalification SQL instantanée
# ─────────────────────────────────────────────────────────────────────────────
def step1_fix_legacy_categories():
    log.info("Étape 1 : correction des catégories legacy (SQL)")
    mapping = {
        "resto":    "restaurant",
        "expo":     "exposition",
        "bienetre": "wellness",
    }
    conn = sqlite3.connect(DB_PATH)
    total = 0
    for old, new in mapping.items():
        n = conn.execute(
            "UPDATE events SET categorie=? WHERE categorie=?", (new, old)
        ).rowcount
        if n:
            log.info("  %s → %s : %d ligne(s)", old, new, n)
            total += n
    conn.commit()
    conn.close()
    log.info("  Total corrigé : %d", total)


# ─────────────────────────────────────────────────────────────────────────────
# Étape 2 — Split brocante / vide-grenier (paris.fr)
# ─────────────────────────────────────────────────────────────────────────────
def step2_split_brocante_vide_grenier():
    log.info("Étape 2 : split brocante / vide-grenier (paris.fr)")
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("""
        UPDATE events
        SET categorie = 'vide-grenier'
        WHERE source = 'paris.fr'
          AND categorie = 'brocante'
          AND LOWER(titre) LIKE '%vide%grenier%'
    """).rowcount
    conn.commit()
    conn.close()
    log.info("  %d événements requalifiés en vide-grenier", n)


# ─────────────────────────────────────────────────────────────────────────────
# Étape 3 — Re-extraction LLM via requests
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_text(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code >= 400:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        # Supprime les balises inutiles
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        return text if len(text) > 300 else None
    except Exception as e:
        log.debug("fetch error %s: %s", url, e)
        return None


def step3_reextract_with_llm(dry_run: bool = False):
    log.info("Étape 3 : re-extraction LLM des articles web")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, titre, url, source, categorie, adresse, date_debut, date_fin, duree_jours
        FROM events
        WHERE source IN ('newtable','sortiraparis','parisbouge','lebonbon')
          AND url IS NOT NULL AND url != ''
          AND url NOT LIKE '%#%'
        ORDER BY source, id
    """).fetchall()

    log.info("  %d événements à traiter", len(rows))

    updated = skipped = failed = 0
    from datetime import datetime, timedelta

    for i, row in enumerate(rows, 1):
        ev_id  = row["id"]
        url    = row["url"]
        source = row["source"]

        log.info("[%d/%d] %s — %s", i, len(rows), source, url[:80])

        text = _fetch_text(url)
        if not text:
            log.warning("  ✗ page inaccessible ou trop courte")
            skipped += 1
            time.sleep(0.5)
            continue

        extracted = extract_with_llm(text)
        if not extracted.get("titre"):
            log.warning("  ✗ LLM n'a rien extrait")
            failed += 1
            time.sleep(1)
            continue

        # Calcul date_fin depuis duree_jours
        date_fin = extracted.get("date_fin") or row["date_fin"]
        duree    = extracted.get("duree_jours")
        if not date_fin and extracted.get("date_debut") and duree:
            try:
                d = datetime.strptime(extracted["date_debut"], "%Y-%m-%d")
                date_fin = (d + timedelta(days=int(duree))).strftime("%Y-%m-%d")
            except Exception:
                pass

        # Calcul duree_jours depuis dates si absent
        if not duree and extracted.get("date_debut") and date_fin:
            try:
                d1 = datetime.strptime(extracted["date_debut"], "%Y-%m-%d")
                d2 = datetime.strptime(date_fin, "%Y-%m-%d")
                duree = (d2 - d1).days
            except Exception:
                pass

        log.info(
            "  ✓ [%s] %s | %s | début=%s duree=%s",
            extracted.get("categorie", "?"),
            extracted.get("titre", "")[:50],
            (extracted.get("adresse") or "")[:40],
            extracted.get("date_debut", "-"),
            duree,
        )

        if not dry_run:
            conn.execute("""
                UPDATE events SET
                    titre        = :titre,
                    description  = :description,
                    adresse      = :adresse,
                    date_debut   = :date_debut,
                    date_fin     = :date_fin,
                    duree_jours  = :duree_jours,
                    categorie    = :categorie
                WHERE id = :id
            """, {
                "titre":        extracted.get("titre") or row["titre"],
                "description":  extracted.get("description"),
                "adresse":      extracted.get("adresse") or row["adresse"],
                "date_debut":   extracted.get("date_debut") or row["date_debut"],
                "date_fin":     date_fin,
                "duree_jours":  duree,
                "categorie":    extracted.get("categorie", row["categorie"]),
                "id":           ev_id,
            })
            conn.commit()

            # Log suggestion si autre:
            cat = extracted.get("categorie", "")
            if cat.startswith("autre:"):
                database.log_category_suggestion(cat.split(":", 1)[1].strip())

        updated += 1
        time.sleep(2.0)  # 2s entre requêtes pour éviter Groq 429

    conn.close()
    log.info(
        "Étape 3 terminée — %d mis à jour, %d pages inaccessibles, %d LLM vide",
        updated, skipped, failed,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Étape 4 — Normalise les catégories restantes via _normalize_categorie
# ─────────────────────────────────────────────────────────────────────────────
def step4_normalize_remaining_categories():
    log.info("Étape 4 : normalisation des catégories restantes")
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, categorie FROM events WHERE categorie IS NOT NULL").fetchall()
    updated = 0
    for ev_id, cat in rows:
        normalized = _normalize_categorie(cat)
        if normalized != cat:
            conn.execute("UPDATE events SET categorie=? WHERE id=?", (normalized, ev_id))
            updated += 1
    conn.commit()
    conn.close()
    log.info("  %d catégories normalisées", updated)


# ─────────────────────────────────────────────────────────────────────────────
# Résumé final
# ─────────────────────────────────────────────────────────────────────────────
def print_summary():
    conn = sqlite3.connect(DB_PATH)
    print("\n──────── État final de la table events ────────")
    rows = conn.execute("""
        SELECT categorie, COUNT(*) as n
        FROM events
        GROUP BY categorie
        ORDER BY n DESC
    """).fetchall()
    for cat, n in rows:
        print(f"  {str(cat):<30} {n:>4}")
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"  {'TOTAL':<30} {total:>4}")

    print("\n──────── Suggestions 'autre:' ────────")
    sugg = conn.execute("""
        SELECT suggestion, count, first_seen
        FROM category_suggestions
        ORDER BY count DESC
    """).fetchall()
    if sugg:
        for s, c, fs in sugg:
            print(f"  {s:<25} ×{c} (depuis {fs[:10]})")
    else:
        print("  (aucune)")
    conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Simule l'étape 3 sans modifier la DB")
    parser.add_argument("--step", type=int, choices=[1,2,3,4],
                        help="Lance uniquement une étape")
    args = parser.parse_args()

    database.init_db()

    if args.step == 1 or not args.step:
        step1_fix_legacy_categories()
    if args.step == 2 or not args.step:
        step2_split_brocante_vide_grenier()
    if args.step == 3 or not args.step:
        step3_reextract_with_llm(dry_run=args.dry_run)
    if args.step == 4 or not args.step:
        step4_normalize_remaining_categories()

    print_summary()
