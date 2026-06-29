import math
import sqlite3
import logging
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "events.db"

# Tables individuelles par scraper validé
_SOURCE_TABLES = [
    "timeout_paris",
    "paris_opendata",
    "paris_fr",
    "parisbouge_autre",
    "parisbouge_restos",
    "parisbouge_bars",
    "parisbouge_expos",
    "sortiraparis",
    "newtable",
    "lebonbon_news",
    "lebonbon_food",
    "lebonbon_drinks",
    "parismusee_expos",
    "secrets_of_paris",
    "numero_popup",
    "inpi_food",
    "inpi_drinks",
]
_SOURCE_TABLES_SET = set(_SOURCE_TABLES)

_EVENT_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS events_{src} (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        titre           TEXT NOT NULL,
        description     TEXT,
        adresse         TEXT,
        lat             REAL,
        lng             REAL,
        date_debut      TEXT,
        date_fin        TEXT,
        duree_jours     INTEGER,
        categorie       TEXT,
        prix            TEXT,
        source          TEXT,
        url             TEXT UNIQUE,
        image_url       TEXT,
        scraped_at      TEXT,
        identified_date TEXT
    )
"""


_LIGATURES = {"œ": "oe", "æ": "ae", "ø": "o", "ß": "ss", "đ": "d", "ł": "l"}


def _normalize_str(s: str | None) -> str | None:
    """Lowercase + ligatures + suppression des diacritiques (é→e, ç→c, œ→oe, etc.)."""
    if not s or not isinstance(s, str):
        return s
    s = s.lower()
    for src, dst in _LIGATURES.items():
        s = s.replace(src, dst)
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS museum_list (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                museum_name   TEXT NOT NULL UNIQUE,
                museum_lat    REAL,
                museum_lng    REAL,
                museum_location TEXT,
                museum_url    TEXT,
                source        TEXT,
                scraped_at    TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_nom ON museum_list(museum_name)")



        conn.execute("""
            CREATE TABLE IF NOT EXISTS scraper_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                scraper     TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'running',
                inserted    INTEGER,
                error_msg   TEXT,
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                duration_s  REAL,
                UNIQUE(run_id, scraper)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_run_id ON scraper_runs(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sr_scraper ON scraper_runs(scraper)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS category_suggestions (
                suggestion  TEXT PRIMARY KEY,
                count       INTEGER NOT NULL DEFAULT 1,
                first_seen  TEXT NOT NULL,
                last_seen   TEXT NOT NULL
            )
        """)


        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                titre           TEXT NOT NULL,
                description     TEXT,
                adresse         TEXT,
                lat             REAL,
                lng             REAL,
                date_debut      TEXT,
                date_fin        TEXT,
                duree_jours     INTEGER,
                categorie       TEXT,
                prix            TEXT,
                source          TEXT,
                url             TEXT UNIQUE,
                image_url       TEXT,
                scraped_at      TEXT,
                identified_date TEXT
            )
        """)

        # Migrations
        for col, typedef in [("identified_date", "TEXT"), ("duree_jours", "INTEGER")]:
            try:
                conn.execute(f"ALTER TABLE events ADD COLUMN {col} {typedef}")
                logger.info("Migration : colonne %s ajoutée", col)
            except sqlite3.OperationalError:
                pass

        # Index (après migration pour que la colonne existe)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_date       ON events(date_debut)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_identified ON events(identified_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cat        ON events(categorie)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_src        ON events(source)")

        # Backfill : lignes existantes sans identified_date
        conn.execute("""
            UPDATE events
            SET identified_date = DATE(scraped_at)
            WHERE identified_date IS NULL AND scraped_at IS NOT NULL
        """)

        # ── Tables par scraper ────────────────────────────────────────────────
        for src in _SOURCE_TABLES:
            conn.execute(_EVENT_TABLE_DDL.format(src=src))
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{src}_date ON events_{src}(date_debut)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{src}_idate ON events_{src}(identified_date)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{src}_cat  ON events_{src}(categorie)")

        # ── Vue master_events (union de toutes les tables sources) ────────────
        conn.execute("DROP VIEW IF EXISTS master_events")
        union = "\n    UNION ALL\n    ".join(
            f"SELECT * FROM events_{src}" for src in _SOURCE_TABLES
        )
        conn.execute(f"CREATE VIEW master_events AS\n    {union}")

        # ── Migration : données existantes → tables sources ───────────────────
        # Certaines sources historiques ont un nom différent dans la colonne source
        _SOURCE_ALIASES = {"paris_fr": "paris.fr"}
        for src in _SOURCE_TABLES:
            old_src = _SOURCE_ALIASES.get(src, src)
            conn.execute(f"""
                INSERT OR IGNORE INTO events_{src}
                    (titre, description, adresse, lat, lng, date_debut, date_fin,
                     duree_jours, categorie, prix, source, url, image_url,
                     scraped_at, identified_date)
                SELECT titre, description, adresse, lat, lng, date_debut, date_fin,
                       duree_jours, categorie, prix, '{src}', url, image_url,
                       scraped_at, identified_date
                FROM events WHERE source = '{old_src}'
            """)
        old_sources = list(_SOURCE_TABLES) + list(_SOURCE_ALIASES.values())
        placeholders = ",".join(f"'{s}'" for s in old_sources)
        migrated = conn.execute(
            f"SELECT COUNT(*) FROM events WHERE source IN ({placeholders})"
        ).fetchone()[0]
        if migrated:
            conn.execute(f"DELETE FROM events WHERE source IN ({placeholders})")
            logger.info("Migration : %d events déplacés vers tables sources", migrated)

        conn.commit()
    logger.info("DB initialisée : %s", DB_PATH)


def insert_event(ev: dict) -> bool:
    """
    Insère un event dans sa table source (events_{source}).
    Retourne True si inséré, False si URL déjà connue (doublon ignoré).
    identified_date est posée à aujourd'hui et n'est jamais mise à jour par la suite.
    """
    now = datetime.now()
    ev.setdefault("scraped_at", now.isoformat(timespec="seconds"))
    ev.setdefault("identified_date", now.strftime("%Y-%m-%d"))

    # Normalisation des champs texte libres
    for field in ("titre", "description", "adresse"):
        ev[field] = _normalize_str(ev.get(field))

    source = ev.get("source", "")
    table = f"events_{source}" if source in _SOURCE_TABLES_SET else "events"

    try:
        with _conn() as conn:
            cur = conn.execute(f"""
                INSERT OR IGNORE INTO {table}
                    (titre, description, adresse, lat, lng,
                     date_debut, date_fin, duree_jours, categorie, prix,
                     source, url, image_url, scraped_at, identified_date)
                VALUES
                    (:titre, :description, :adresse, :lat, :lng,
                     :date_debut, :date_fin, :duree_jours, :categorie, :prix,
                     :source, :url, :image_url, :scraped_at, :identified_date)
            """, ev)
            conn.commit()
            return cur.rowcount == 1
    except Exception:
        logger.exception("insert_event failed pour url=%s", ev.get("url"))
        return False


def _haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_events_in_radius(lat: float, lng: float, radius_m: int, days: int = 30, cat: str | None = None) -> list[dict]:
    """
    Retourne les events dans le rayon selon deux logiques :
    - Brocantes datées  : date_debut <= today <= date_fin  (affichage le jour J uniquement)
    - Brocantes perma   : date_debut IS NULL  (toujours visibles)
    - Tous les autres   : identified_date >= today - days
    """
    today  = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM master_events
               WHERE lat IS NOT NULL
                 AND lng IS NOT NULL
                 AND (
                   -- événements standards : découverts récemment
                   (categorie != 'brocante' AND identified_date >= :cutoff)
                   -- brocantes permanentes (marchés aux puces, etc.)
                   OR (categorie = 'brocante' AND date_debut IS NULL)
                   -- brocantes datées : aujourd'hui est dans la fenêtre de l'événement
                   OR (categorie = 'brocante' AND date_debut <= :today AND date_fin >= :today)
                 )""",
            {"cutoff": cutoff, "today": today}
        ).fetchall()

    result = []
    for row in rows:
        ev = dict(row)
        ev_cat = ev.get("categorie") or ""
        if cat and not (ev_cat == cat or (cat == "autre" and ev_cat.startswith("autre"))):
            continue
        dist = _haversine(lat, lng, ev["lat"], ev["lng"])
        if dist <= radius_m:
            ev["dist_m"] = round(dist)
            result.append(ev)

    result.sort(key=lambda x: x["dist_m"])
    return result


def _normalize_str(s: str | None) -> str | None:
    if not s:
        return s
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_str.lower().strip()


def upsert_museum(m: dict) -> bool:
    now = datetime.now().isoformat(timespec="seconds")
    m = {**m, "scraped_at": m.get("scraped_at", now)}
    m["museum_name"]     = _normalize_str(m.get("museum_name"))
    m["museum_location"] = _normalize_str(m.get("museum_location"))
    m["museum_url"]      = _normalize_str(m.get("museum_url"))
    m["source"]          = _normalize_str(m.get("source"))
    if not m["museum_name"]:
        return False
    try:
        with _conn() as conn:
            cur = conn.execute("""
                INSERT INTO museum_list (museum_name, museum_lat, museum_lng, museum_location, museum_url, source, scraped_at)
                VALUES (:museum_name, :museum_lat, :museum_lng, :museum_location, :museum_url, :source, :scraped_at)
                ON CONFLICT(museum_name) DO UPDATE SET
                    museum_lat      = excluded.museum_lat,
                    museum_lng      = excluded.museum_lng,
                    museum_location = excluded.museum_location,
                    museum_url      = excluded.museum_url,
                    scraped_at      = excluded.scraped_at
            """, m)
            conn.commit()
            return cur.rowcount == 1
    except Exception:
        logger.exception("upsert_museum failed pour %s", m.get("museum_name"))
        return False




def scraper_run_start(run_id: str, scraper: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO scraper_runs (run_id, scraper, status, started_at)
            VALUES (?, ?, 'running', ?)
        """, (run_id, scraper, now))
        conn.commit()


def scraper_run_end(run_id: str, scraper: str, inserted: int, error_msg: str | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        started = conn.execute(
            "SELECT started_at FROM scraper_runs WHERE run_id=? AND scraper=?",
            (run_id, scraper)
        ).fetchone()
        duration = None
        if started:
            try:
                d = datetime.fromisoformat(started[0])
                duration = round((datetime.now() - d).total_seconds(), 1)
            except Exception:
                pass
        status = "error" if error_msg else "done"
        conn.execute("""
            UPDATE scraper_runs
            SET status=?, inserted=?, error_msg=?, finished_at=?, duration_s=?
            WHERE run_id=? AND scraper=?
        """, (status, inserted, error_msg, now, duration, run_id, scraper))
        conn.commit()


def get_last_run_summary() -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT run_id FROM scraper_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {"run_id": None, "status": "never_run"}
        run_id = row[0]
        rows = conn.execute(
            "SELECT scraper, status, inserted, error_msg, started_at, finished_at, duration_s "
            "FROM scraper_runs WHERE run_id=? ORDER BY started_at",
            (run_id,)
        ).fetchall()

    scrapers = {}
    total_inserted = 0
    still_running = 0
    errors = 0
    for r in rows:
        scrapers[r[0]] = {
            "status":      r[1],
            "inserted":    r[2],
            "error_msg":   r[3],
            "started_at":  r[4],
            "finished_at": r[5],
            "duration_s":  r[6],
        }
        if r[1] == "running":
            still_running += 1
        elif r[1] == "error":
            errors += 1
        if r[2]:
            total_inserted += r[2]

    if still_running:
        batch_status = "running"
    elif errors:
        batch_status = "partial_error" if errors < len(rows) else "error"
    else:
        batch_status = "done"

    triggered_at = rows[0][4] if rows else None
    return {
        "run_id":          run_id,
        "triggered_at":    triggered_at,
        "status":          batch_status,
        "total_inserted":  total_inserted,
        "completed":       len(rows) - still_running,
        "total_scrapers":  len(rows),
        "errors":          errors,
        "scrapers":        scrapers,
    }


def log_category_suggestion(suggestion: str) -> None:
    """Incrémente le compteur d'une suggestion 'autre: X'."""
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute("""
            INSERT INTO category_suggestions (suggestion, count, first_seen, last_seen)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(suggestion) DO UPDATE SET
                count     = category_suggestions.count + 1,
                last_seen = excluded.last_seen
        """, (suggestion, now, now))
        conn.commit()


def purge_old_events(keep_days: int = 365) -> dict:
    """
    Supprime les events trop anciens (identified_date) et les events expirés (date_fin).
    Retourne les compteurs par source pour le reporting.
    """
    # 1. Purge par ancienneté
    cutoff_old = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    with _conn() as conn:
        total_old = 0
        for src in _SOURCE_TABLES:
            total_old += conn.execute(
                f"DELETE FROM events_{src} WHERE identified_date < ?", (cutoff_old,)
            ).rowcount
        total_old += conn.execute(
            "DELETE FROM events WHERE identified_date < ?", (cutoff_old,)
        ).rowcount
        conn.commit()
    if total_old:
        logger.info("Purge : %d events supprimés (identified_date < %s)", total_old, cutoff_old)

    # 2. Purge par date_fin dépassée — retourne le détail par source
    cutoff_exp = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    deleted_by_source = {}
    with _conn() as conn:
        cur = conn.cursor()
        for src in _SOURCE_TABLES:
            table = f"events_{src}"
            try:
                cur.execute(
                    f"DELETE FROM {table} WHERE date_fin IS NOT NULL AND date_fin < ?",
                    (cutoff_exp,),
                )
                if cur.rowcount:
                    deleted_by_source[src] = cur.rowcount
            except Exception:
                logger.warning("[purge] table %s introuvable ou erreur", table)
        conn.commit()
    total_exp = sum(deleted_by_source.values())
    logger.info("[purge] %d événements expirés supprimés (date_fin < %s)", total_exp, cutoff_exp)

    return {"deleted_by_source": deleted_by_source, "total_deleted": total_exp}
