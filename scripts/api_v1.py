"""
API FastAPI — événements Paris
GET /api/events?lat=48.85&lng=2.35&radius=500&cat=all
"""

import math
import sqlite3
from contextlib import contextmanager
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DB_PATH = "events.db"

app = FastAPI(title="Flâneur API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@app.get("/api/events")
def search_events(
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    radius: int = Query(500, ge=100, le=5000),
    cat: str = Query("all"),
):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, titre, cat, date, adresse, lat, lng, prix, url, source FROM events"
        ).fetchall()

    results = []
    for r in rows:
        ev = dict(r)

        # Filtre catégorie
        if cat != "all":
            if cat == "gratuit":
                if (ev["prix"] or "").lower() != "gratuit":
                    continue
            elif ev["cat"] != cat:
                continue

        # Calcul distance
        if lat is not None and lng is not None and ev["lat"] and ev["lng"]:
            dist = haversine(lat, lng, ev["lat"], ev["lng"])
            if dist > radius:
                continue
            ev["dist"] = round(dist)
        else:
            ev["dist"] = None  # pas de coords → inclus dans la liste, absent de la carte

        results.append(ev)

    # Tri : d'abord ceux avec distance (croissant), puis sans coords
    results.sort(key=lambda e: (e["dist"] is None, e["dist"] or 0))
    return results


@app.get("/")
def serve_frontend():
    return FileResponse("paris-explorer.html")


@app.get("/api/stats")
def stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        with_coords = conn.execute("SELECT COUNT(*) FROM events WHERE lat IS NOT NULL").fetchone()[0]
        by_cat = conn.execute("SELECT cat, COUNT(*) as n FROM events GROUP BY cat").fetchall()
    return {
        "total": total,
        "with_coords": with_coords,
        "by_cat": {r["cat"]: r["n"] for r in by_cat},
    }
